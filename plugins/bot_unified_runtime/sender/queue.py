from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Protocol

from plugins.bot_unified_runtime.audit import AuditRepository
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    DeliveryReceipt,
    ReceiptState,
    SendRequest,
)
from plugins.bot_unified_runtime.sender.receipts import skipped_receipt, sent_receipt


SQLITE_QUEUE_TRANSPORT = "sqlite_queue"
PROCESSING_STATE = "processing"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _queued_receipt(send_request: SendRequest) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.QUEUED,
        transport=SQLITE_QUEUE_TRANSPORT,
        public_message="queued",
    )


@dataclass(frozen=True)
class QueuedSendRequest:
    send_request: SendRequest
    state: ReceiptState
    retry_count: int
    next_retry_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lease_expires_at: datetime | None = None


class SendQueue(Protocol):
    sent_requests: list[SendRequest]

    def submit(self, send_request: SendRequest) -> DeliveryReceipt:
        raise NotImplementedError

    def find_request(self, request_id: str) -> SendRequest | None:
        raise NotImplementedError

    def safe_summary(self) -> dict[str, int]:
        raise NotImplementedError


class InMemorySendQueue:
    def __init__(self, audit_logger: AuditRepository) -> None:
        self.audit_logger = audit_logger
        self.sent_requests: list[SendRequest] = []
        self._dedupe_keys: set[str] = set()

    def submit(self, send_request: SendRequest) -> DeliveryReceipt:
        if send_request.dedupe_key in self._dedupe_keys:
            receipt = skipped_receipt(send_request, "duplicate dedupe_key")
            event = "skipped_duplicate"
        else:
            self._dedupe_keys.add(send_request.dedupe_key)
            self.sent_requests.append(send_request)
            receipt = sent_receipt(send_request)
            event = "sent"

        self.audit_logger.append(
            AuditRecord(
                request_id=send_request.request_id,
                session_id=send_request.session_id,
                capability_id=send_request.capability_id,
                stage="sender",
                event=event,
                severity=send_request.content.risk_level,
                public_message=receipt.public_message,
                private_debug=f"transport={receipt.transport} state={receipt.state.value}",
            )
        )
        return receipt

    def find_request(self, request_id: str) -> SendRequest | None:
        normalized = request_id.strip()
        if not normalized:
            return None
        return next(
            (
                request
                for request in reversed(self.sent_requests)
                if request.request_id == normalized
            ),
            None,
        )

    def safe_summary(self) -> dict[str, int]:
        return {
            ReceiptState.QUEUED.value: 0,
            ReceiptState.FAILED_RETRYABLE.value: 0,
            ReceiptState.FAILED_FINAL.value: 0,
            ReceiptState.SENT.value: len(self.sent_requests),
            ReceiptState.SKIPPED.value: 0,
            PROCESSING_STATE: 0,
        }


class SQLiteSendRequestQueue:
    def __init__(
        self,
        db_path: str | Path,
        audit_logger: AuditRepository,
        *,
        max_items: int = 1000,
        max_attempts: int = 3,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 300,
    ) -> None:
        self.db_path = Path(db_path)
        self.audit_logger = audit_logger
        self.max_items = max(1, int(max_items))
        self.max_attempts = max(1, int(max_attempts))
        self.retry_base_seconds = max(1, int(retry_base_seconds))
        self.retry_max_seconds = max(self.retry_base_seconds, int(retry_max_seconds))
        self.sent_requests: list[SendRequest] = []

    def submit(
        self,
        send_request: SendRequest,
        *,
        now: datetime | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        self._ensure_schema()
        with closing(self._connect()) as connection, connection:
            existing = connection.execute(
                """
                SELECT request_id
                FROM send_requests
                WHERE dedupe_key = ?
                LIMIT 1
                """,
                (send_request.dedupe_key,),
            ).fetchone()
            if existing is not None:
                receipt = skipped_receipt(send_request, "duplicate dedupe_key")
                event = "skipped_duplicate"
            else:
                connection.execute(
                    """
                    INSERT INTO send_requests (
                        dedupe_key,
                        request_id,
                        state,
                        request_json,
                        retry_count,
                        next_retry_at,
                        last_public_message,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        send_request.dedupe_key,
                        send_request.request_id,
                        ReceiptState.QUEUED.value,
                        send_request.model_dump_json(),
                        0,
                        current_time.isoformat(),
                        "queued",
                        current_time.isoformat(),
                        current_time.isoformat(),
                    ),
                )
                self._prune(connection)
                self.sent_requests.append(send_request)
                receipt = _queued_receipt(send_request)
                event = "queued"

        self._append_sender_audit(send_request, receipt, event)
        return receipt

    def list_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
    ) -> list[QueuedSendRequest]:
        current_time = now or _utc_now()
        self._ensure_schema()
        safe_limit = max(1, int(limit))
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                SELECT *
                FROM send_requests
                WHERE state IN (?, ?)
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY created_at ASC, rowid ASC
                LIMIT ?
                """,
                (
                    ReceiptState.QUEUED.value,
                    ReceiptState.FAILED_RETRYABLE.value,
                    current_time.isoformat(),
                    safe_limit,
                ),
            )
            return [self._entry_from_row(row) for row in cursor.fetchall()]

    def find_request(self, request_id: str) -> SendRequest | None:
        normalized = request_id.strip()
        if not normalized:
            return None
        entry = self._find_entry_by_request_id(normalized)
        return entry.send_request if entry is not None else None

    def claim_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
        lease_seconds: int = 60,
    ) -> list[QueuedSendRequest]:
        current_time = now or _utc_now()
        safe_limit = max(1, int(limit))
        safe_lease_seconds = max(1, int(lease_seconds))
        lease_expires_at = current_time + timedelta(seconds=safe_lease_seconds)
        self._ensure_schema()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM send_requests
                    WHERE (
                        state IN (?, ?)
                        AND (next_retry_at IS NULL OR next_retry_at <= ?)
                    )
                    OR (
                        state = ?
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at <= ?
                    )
                    ORDER BY created_at ASC, rowid ASC
                    LIMIT ?
                    """,
                    (
                        ReceiptState.QUEUED.value,
                        ReceiptState.FAILED_RETRYABLE.value,
                        current_time.isoformat(),
                        PROCESSING_STATE,
                        current_time.isoformat(),
                        safe_limit,
                    ),
                ).fetchall()
                for row in rows:
                    claimed_from_state = (
                        str(row["claimed_from_state"])
                        if row["state"] == PROCESSING_STATE
                        and row["claimed_from_state"] is not None
                        else str(row["state"])
                    )
                    connection.execute(
                        """
                        UPDATE send_requests
                        SET state = ?,
                            claimed_from_state = ?,
                            lease_expires_at = ?,
                            updated_at = ?
                        WHERE dedupe_key = ?
                        """,
                        (
                            PROCESSING_STATE,
                            claimed_from_state,
                            lease_expires_at.isoformat(),
                            current_time.isoformat(),
                            row["dedupe_key"],
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return [self._entry_from_row(row) for row in rows]

    def mark_retryable_failure(
        self,
        request_id: str,
        public_message: str,
        *,
        now: datetime | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        entry = self._find_entry_by_request_id(request_id)
        if entry is None:
            return DeliveryReceipt(
                request_id=request_id,
                state=ReceiptState.FAILED_FINAL,
                transport=SQLITE_QUEUE_TRANSPORT,
                public_message="send request not found",
            )

        retry_count = entry.retry_count + 1
        if retry_count >= self.max_attempts:
            receipt = self._update_state(
                entry.send_request,
                state=ReceiptState.FAILED_FINAL,
                retry_count=retry_count,
                next_retry_at=None,
                public_message=public_message,
                now=current_time,
            )
            event = "send_failed_final"
        else:
            next_retry_at = current_time + timedelta(
                seconds=self._backoff_seconds(retry_count)
            )
            receipt = self._update_state(
                entry.send_request,
                state=ReceiptState.FAILED_RETRYABLE,
                retry_count=retry_count,
                next_retry_at=next_retry_at,
                public_message=public_message,
                now=current_time,
            )
            event = "send_failed_retryable"

        self._append_sender_audit(entry.send_request, receipt, event)
        return receipt

    def mark_sent(
        self,
        request_id: str,
        public_message: str = "sent",
        *,
        now: datetime | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        entry = self._find_entry_by_request_id(request_id)
        if entry is None:
            return DeliveryReceipt(
                request_id=request_id,
                state=ReceiptState.FAILED_FINAL,
                transport=SQLITE_QUEUE_TRANSPORT,
                public_message="send request not found",
            )
        receipt = self._update_state(
            entry.send_request,
            state=ReceiptState.SENT,
            retry_count=entry.retry_count,
            next_retry_at=None,
            public_message=public_message,
            now=current_time,
        )
        self._append_sender_audit(entry.send_request, receipt, "send_marked_sent")
        return receipt

    def mark_final_failure(
        self,
        request_id: str,
        public_message: str,
        *,
        now: datetime | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        entry = self._find_entry_by_request_id(request_id)
        if entry is None:
            return DeliveryReceipt(
                request_id=request_id,
                state=ReceiptState.FAILED_FINAL,
                transport=SQLITE_QUEUE_TRANSPORT,
                public_message="send request not found",
            )
        receipt = self._update_state(
            entry.send_request,
            state=ReceiptState.FAILED_FINAL,
            retry_count=entry.retry_count,
            next_retry_at=None,
            public_message=public_message,
            now=current_time,
        )
        self._append_sender_audit(entry.send_request, receipt, "send_failed_final")
        return receipt

    def safe_summary(self) -> dict[str, int]:
        self._ensure_schema()
        summary = {
            ReceiptState.QUEUED.value: 0,
            ReceiptState.FAILED_RETRYABLE.value: 0,
            ReceiptState.FAILED_FINAL.value: 0,
            ReceiptState.SENT.value: 0,
            ReceiptState.SKIPPED.value: 0,
            PROCESSING_STATE: 0,
        }
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                SELECT state, COUNT(*) AS count
                FROM send_requests
                GROUP BY state
                """
            )
            for row in cursor.fetchall():
                state = str(row["state"])
                if state in summary:
                    summary[state] = int(row["count"])
        return summary

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS send_requests (
                    dedupe_key TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    retry_count INTEGER NOT NULL,
                    next_retry_at TEXT,
                    claimed_from_state TEXT,
                    lease_expires_at TEXT,
                    last_public_message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(
                connection,
                "send_requests",
                "claimed_from_state",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "send_requests",
                "lease_expires_at",
                "TEXT",
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_send_requests_request_id
                ON send_requests (request_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_send_requests_state_due
                ON send_requests (state, next_retry_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_send_requests_processing_lease
                ON send_requests (state, lease_expires_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
            )

    def _prune(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM send_requests
            WHERE dedupe_key NOT IN (
                SELECT dedupe_key
                FROM send_requests
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
            )
            """,
            (self.max_items,),
        )

    def _find_entry_by_request_id(self, request_id: str) -> QueuedSendRequest | None:
        self._ensure_schema()
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT *
                FROM send_requests
                WHERE request_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (request_id,),
            ).fetchone()
        return self._entry_from_row(row) if row is not None else None

    def _entry_from_row(self, row: sqlite3.Row) -> QueuedSendRequest:
        raw_state = str(row["state"])
        public_state = (
            str(row["claimed_from_state"])
            if raw_state == PROCESSING_STATE and row["claimed_from_state"] is not None
            else raw_state
        )
        return QueuedSendRequest(
            send_request=SendRequest.model_validate_json(str(row["request_json"])),
            state=ReceiptState(public_state),
            retry_count=int(row["retry_count"]),
            next_retry_at=(
                datetime.fromisoformat(str(row["next_retry_at"]))
                if row["next_retry_at"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            lease_expires_at=(
                datetime.fromisoformat(str(row["lease_expires_at"]))
                if row["lease_expires_at"] is not None
                else None
            ),
        )

    def _update_state(
        self,
        send_request: SendRequest,
        *,
        state: ReceiptState,
        retry_count: int,
        next_retry_at: datetime | None,
        public_message: str,
        now: datetime,
    ) -> DeliveryReceipt:
        self._ensure_schema()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE send_requests
                SET state = ?,
                    retry_count = ?,
                    next_retry_at = ?,
                    claimed_from_state = NULL,
                    lease_expires_at = NULL,
                    last_public_message = ?,
                    updated_at = ?
                WHERE request_id = ?
                """,
                (
                    state.value,
                    retry_count,
                    next_retry_at.isoformat() if next_retry_at is not None else None,
                    public_message,
                    now.isoformat(),
                    send_request.request_id,
                ),
            )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=state,
            transport=SQLITE_QUEUE_TRANSPORT,
            retry_count=retry_count,
            next_retry_at=next_retry_at,
            public_message=public_message,
        )

    def _backoff_seconds(self, retry_count: int) -> int:
        exponent = max(0, retry_count - 1)
        return min(
            self.retry_max_seconds,
            self.retry_base_seconds * (2**exponent),
        )

    def _append_sender_audit(
        self,
        send_request: SendRequest,
        receipt: DeliveryReceipt,
        event: str,
    ) -> None:
        self.audit_logger.append(
            AuditRecord(
                request_id=send_request.request_id,
                session_id=send_request.session_id,
                capability_id=send_request.capability_id,
                stage="sender",
                event=event,
                severity=send_request.content.risk_level,
                public_message=receipt.public_message,
                private_debug=(
                    f"transport={receipt.transport} "
                    f"state={receipt.state.value} retry_count={receipt.retry_count}"
                ),
            )
        )


def build_send_queue(
    config: Config,
    audit_logger: AuditRepository,
) -> InMemorySendQueue | SQLiteSendRequestQueue:
    enabled = bool(getattr(config, "bot_send_queue_enabled", False))
    db_path = str(getattr(config, "bot_send_queue_db_path", "")).strip()
    if enabled and db_path:
        return SQLiteSendRequestQueue(
            db_path,
            audit_logger=audit_logger,
            max_items=int(getattr(config, "bot_send_queue_max_items", 1000)),
            max_attempts=int(getattr(config, "bot_send_queue_max_attempts", 3)),
            retry_base_seconds=int(
                getattr(config, "bot_send_queue_retry_base_seconds", 30)
            ),
            retry_max_seconds=int(
                getattr(config, "bot_send_queue_retry_max_seconds", 300)
            ),
        )
    return InMemorySendQueue(audit_logger=audit_logger)

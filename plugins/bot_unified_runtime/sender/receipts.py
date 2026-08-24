from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    ReceiptState,
    SendRequest,
)


class ReceiptRepository(Protocol):
    def record(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        raise NotImplementedError

    def latest(self, request_id: str | None = None) -> DeliveryReceipt | None:
        raise NotImplementedError

    def find(self, token: str) -> DeliveryReceipt | None:
        raise NotImplementedError

    def list_receipts(self, request_id: str | None = None) -> list[DeliveryReceipt]:
        raise NotImplementedError


class InMemoryReceiptRepository:
    def __init__(self) -> None:
        self._receipts: list[DeliveryReceipt] = []

    def record(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        self._receipts.append(receipt)
        return receipt

    def latest(self, request_id: str | None = None) -> DeliveryReceipt | None:
        receipts = self.list_receipts(request_id)
        return receipts[-1] if receipts else None

    def find(self, token: str) -> DeliveryReceipt | None:
        if not token:
            return None
        for receipt in reversed(self._receipts):
            if receipt.request_id == token or receipt.debug_id == token:
                return receipt
        return None

    def list_receipts(self, request_id: str | None = None) -> list[DeliveryReceipt]:
        if request_id is None:
            return list(self._receipts)
        return [receipt for receipt in self._receipts if receipt.request_id == request_id]


class SQLiteReceiptRepository:
    def __init__(self, db_path: str | Path, max_items: int = 1000) -> None:
        self.db_path = Path(db_path)
        self.max_items = max(1, int(max_items))

    def record(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        self._ensure_schema()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO delivery_receipts (
                    debug_id,
                    request_id,
                    state,
                    transport,
                    provider_message_id,
                    retry_count,
                    next_retry_at,
                    public_message,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(debug_id) DO UPDATE SET
                    request_id=excluded.request_id,
                    state=excluded.state,
                    transport=excluded.transport,
                    provider_message_id=excluded.provider_message_id,
                    retry_count=excluded.retry_count,
                    next_retry_at=excluded.next_retry_at,
                    public_message=excluded.public_message,
                    created_at=excluded.created_at
                """,
                (
                    receipt.debug_id,
                    receipt.request_id,
                    receipt.state.value,
                    receipt.transport,
                    receipt.provider_message_id,
                    receipt.retry_count,
                    receipt.next_retry_at.isoformat()
                    if receipt.next_retry_at is not None
                    else None,
                    receipt.public_message,
                    receipt.created_at.isoformat(),
                ),
            )
            self._prune(connection)
        return receipt

    def latest(self, request_id: str | None = None) -> DeliveryReceipt | None:
        self._ensure_schema()
        with self._connect() as connection:
            if request_id is None:
                cursor = connection.execute(
                    """
                    SELECT *
                    FROM delivery_receipts
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT 1
                    """
                )
            else:
                cursor = connection.execute(
                    """
                    SELECT *
                    FROM delivery_receipts
                    WHERE request_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (request_id,),
                )
            row = cursor.fetchone()
            return self._from_row(row) if row is not None else None

    def find(self, token: str) -> DeliveryReceipt | None:
        if not token:
            return None
        self._ensure_schema()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT *
                FROM delivery_receipts
                WHERE request_id = ? OR debug_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (token, token),
            )
            row = cursor.fetchone()
            return self._from_row(row) if row is not None else None

    def list_receipts(self, request_id: str | None = None) -> list[DeliveryReceipt]:
        self._ensure_schema()
        with self._connect() as connection:
            if request_id is None:
                cursor = connection.execute(
                    """
                    SELECT *
                    FROM delivery_receipts
                    ORDER BY created_at ASC, rowid ASC
                    """
                )
            else:
                cursor = connection.execute(
                    """
                    SELECT *
                    FROM delivery_receipts
                    WHERE request_id = ?
                    ORDER BY created_at ASC, rowid ASC
                    """,
                    (request_id,),
                )
            return [self._from_row(row) for row in cursor.fetchall()]

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_receipts (
                    debug_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    transport TEXT NOT NULL,
                    provider_message_id TEXT,
                    retry_count INTEGER NOT NULL,
                    next_retry_at TEXT,
                    public_message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_delivery_receipts_request_time
                ON delivery_receipts (request_id, created_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_delivery_receipts_created_at
                ON delivery_receipts (created_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _prune(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM delivery_receipts
            WHERE debug_id NOT IN (
                SELECT debug_id
                FROM delivery_receipts
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
            )
            """,
            (self.max_items,),
        )

    def _from_row(self, row: sqlite3.Row) -> DeliveryReceipt:
        return DeliveryReceipt(
            request_id=str(row["request_id"]),
            state=ReceiptState(str(row["state"])),
            transport=str(row["transport"]),
            provider_message_id=(
                str(row["provider_message_id"])
                if row["provider_message_id"] is not None
                else None
            ),
            retry_count=int(row["retry_count"]),
            next_retry_at=(
                datetime.fromisoformat(str(row["next_retry_at"]))
                if row["next_retry_at"] is not None
                else None
            ),
            public_message=str(row["public_message"]),
            debug_id=str(row["debug_id"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )


def sent_receipt(send_request: SendRequest) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SENT,
        transport="memory",
        public_message="sent",
    )


def skipped_receipt(send_request: SendRequest, reason: str) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SKIPPED,
        transport="memory",
        public_message=reason,
    )


def blocked_receipt(send_request: SendRequest, reason: str) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.BLOCKED,
        transport="blocked",
        public_message=reason,
    )


def build_receipt_repository(config: Config) -> ReceiptRepository:
    enabled = bool(getattr(config, "bot_receipts_enabled", False))
    db_path = str(getattr(config, "bot_receipts_db_path", "")).strip()
    max_items = int(getattr(config, "bot_receipts_max_items", 1000))
    if enabled and db_path:
        return SQLiteReceiptRepository(db_path, max_items=max_items)
    return InMemoryReceiptRepository()

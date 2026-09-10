from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.audit import AuditRepository
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    DeliveryReceipt,
    OperationalIssue,
    ReceiptState,
    SendRequest,
)
from plugins.bot_unified_runtime.sender.receipts import sent_receipt, skipped_receipt

SQLITE_QUEUE_TRANSPORT = "sqlite_queue"
PROCESSING_STATE = "processing"
# 新入队行的认领宽限期：submit 写入 next_retry_at=now+宽限期，宽限期内
# worker 的 claim_due 不得认领该行——入队后的首次投递由 handler 内联
# 负责（不走租约协议），避免 worker 与内联投递竞态重复发送同一消息。
# 宽限期过后该行仍在 QUEUED 态（例如进程重启丢了内联投递），由 worker 接管。
_INLINE_DELIVERY_GRACE_SECONDS = 60
# B-4（管线检视 #6）：bot_unavailable 挂起语义参数。
# 挂起期间不消耗重试预算，重试间隔取固定 90s 下限（NapCat 断线窗口内
# 慢速重探，不随重试预算配置变化）；入队超过绝对年龄上限（默认 30min，
# 可经 bot_send_bot_unavailable_max_age_seconds 覆盖）仍不可投才置终态
# （防 A4 契约下死挂行无限堆积）。
_BOT_UNAVAILABLE_KIND = "bot_unavailable"
_BOT_UNAVAILABLE_RETRY_DELAY_SECONDS = 90.0
_BOT_UNAVAILABLE_MAX_AGE_SECONDS = 1800.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _queued_receipt(send_request: SendRequest) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.QUEUED,
        transport=SQLITE_QUEUE_TRANSPORT,
        public_message="" if send_request.operational_issue is not None else "queued",
        operational_issue=send_request.operational_issue,
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
    def submit(self, send_request: SendRequest) -> DeliveryReceipt:
        raise NotImplementedError

    def find_request(self, request_id: str) -> SendRequest | None:
        raise NotImplementedError

    def safe_summary(self) -> dict[str, int]:
        raise NotImplementedError


class InMemorySendQueue:
    """内存发送队列：有界（FIFO 淘汰最旧请求及其去重键）。

    完整 SendRequest（含渲染正文）每条 KB 级且进程内常驻，无上界时随
    消息量线性吃内存、find_request 全量倒扫越来越慢。
    """

    def __init__(self, audit_logger: AuditRepository, *, max_requests: int = 500) -> None:
        self.audit_logger = audit_logger
        self.max_requests = max(1, int(max_requests))
        self.sent_requests: list[SendRequest] = []
        self._dedupe_keys: set[str] = set()

    def submit(self, send_request: SendRequest) -> DeliveryReceipt:
        if send_request.dedupe_key in self._dedupe_keys:
            receipt = skipped_receipt(send_request, "duplicate dedupe_key")
            event = "skipped_duplicate"
        else:
            while len(self.sent_requests) >= self.max_requests:
                evicted = self.sent_requests.pop(0)
                self._dedupe_keys.discard(evicted.dedupe_key)
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
        bot_unavailable_max_age_seconds: float | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.audit_logger = audit_logger
        self.max_items = max(1, int(max_items))
        self.max_attempts = max(1, int(max_attempts))
        self.retry_base_seconds = max(1, int(retry_base_seconds))
        self.retry_max_seconds = max(self.retry_base_seconds, int(retry_max_seconds))
        # bot_unavailable 挂起的绝对年龄上限：None 用模块默认常量。
        self._bot_unavailable_max_age_seconds = (
            float(bot_unavailable_max_age_seconds)
            if bot_unavailable_max_age_seconds is not None
            else _BOT_UNAVAILABLE_MAX_AGE_SECONDS
        )
        # 每次操作都重跑建表 DDL 是纯浪费：进程内建一次即可（含 WAL 切换）。
        self._schema_ready = False
        # 进程内长连接（B-10，管线检视 #13）：check_same_thread=False +
        # 锁串行化，消除每操作建连开销与 mark_* 跨连接两事务的非原子读改写。
        self._connection: sqlite3.Connection | None = None
        self._connection_lock = threading.RLock()

    def _ensure_schema_once(self) -> None:
        if self._schema_ready:
            return
        self._ensure_schema()
        self._schema_ready = True

    def _shared_connection(self) -> sqlite3.Connection:
        with self._connection_lock:
            if self._connection is None:
                connection = sqlite3.connect(
                    self.db_path, timeout=5.0, check_same_thread=False
                )
                connection.row_factory = sqlite3.Row
                self._connection = connection
            return self._connection

    def _discard_connection(self) -> None:
        with self._connection_lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except sqlite3.Error:
                    pass
                self._connection = None

    @contextmanager
    def _transaction(self):
        """共享连接上的读写事务：显式 BEGIN，正常提交、异常回滚。

        读-改-写（mark_* 查 entry 后更新）由此成为真正的单事务；
        sqlite3.Error 额外丢弃连接（库级损坏/断连时复用不安全）。
        """
        with self._connection_lock:
            connection = self._shared_connection()
            try:
                connection.execute("BEGIN")
                yield connection
            except sqlite3.Error:
                connection.rollback()
                self._discard_connection()
                raise
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @contextmanager
    def _transaction_immediate(self):
        """写优先事务：认领租约用 IMMEDIATE 先取写锁，避免锁升级死锁。"""
        with self._connection_lock:
            connection = self._shared_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
            except sqlite3.Error:
                connection.rollback()
                self._discard_connection()
                raise
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @contextmanager
    def _locked_connection(self):
        """只读操作对共享连接的持锁借用。"""
        with self._connection_lock:
            yield self._shared_connection()

    def submit(
        self,
        send_request: SendRequest,
        *,
        now: datetime | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            # 去重与写入必须原子：SELECT→INSERT 两步在并发下会同时通过
            # 检查并在主键冲突时抛未捕获 IntegrityError；改为单条
            # INSERT ... ON CONFLICT DO NOTHING，冲突即重复。
            cursor = connection.execute(
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
                ON CONFLICT(dedupe_key) DO NOTHING
                """,
                (
                    send_request.dedupe_key,
                    send_request.request_id,
                    ReceiptState.QUEUED.value,
                    send_request.model_dump_json(),
                    0,
                    (
                        current_time
                        + timedelta(seconds=_INLINE_DELIVERY_GRACE_SECONDS)
                    ).isoformat(),
                    "" if send_request.operational_issue is not None else "queued",
                    current_time.isoformat(),
                    current_time.isoformat(),
                ),
            )
            if cursor.rowcount == 0:
                receipt = skipped_receipt(send_request, "duplicate dedupe_key")
                event = "skipped_duplicate"
            else:
                self._prune(connection)
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
        self._ensure_schema_once()
        safe_limit = max(1, int(limit))
        with self._locked_connection() as connection:
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
        self._ensure_schema_once()
        with self._transaction_immediate() as connection:
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
            claimed_keys: list[str] = []
            for row in rows:
                claimed_from_state = (
                    str(row["claimed_from_state"])
                    if row["state"] == PROCESSING_STATE
                    and row["claimed_from_state"] is not None
                    else str(row["state"])
                )
                retry_count = int(row["retry_count"])
                if row["state"] == PROCESSING_STATE:
                    # 租约过期重认领意味着上一次投递结果未知（可能已送达），
                    # 必须计入尝试次数；否则进程崩溃循环会无限重发。
                    retry_count += 1
                    if retry_count >= self.max_attempts:
                        self._finalize_expired_lease(
                            connection, row, retry_count, current_time
                        )
                        continue
                connection.execute(
                    """
                    UPDATE send_requests
                    SET state = ?,
                        claimed_from_state = ?,
                        lease_expires_at = ?,
                        retry_count = ?,
                        updated_at = ?
                    WHERE dedupe_key = ?
                    """,
                    (
                        PROCESSING_STATE,
                        claimed_from_state,
                        lease_expires_at.isoformat(),
                        retry_count,
                        current_time.isoformat(),
                        row["dedupe_key"],
                    ),
                )
                claimed_keys.append(str(row["dedupe_key"]))
            if not claimed_keys:
                return []
            # 重读认领后的行：返回条目须反映本次认领写入的 retry_count。
            placeholders = ",".join("?" for _ in claimed_keys)
            refreshed = connection.execute(
                f"""
                SELECT *
                FROM send_requests
                WHERE dedupe_key IN ({placeholders})
                ORDER BY created_at ASC, rowid ASC
                """,
                claimed_keys,
            ).fetchall()
        return [self._entry_from_row(row) for row in refreshed]

    def _finalize_expired_lease(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        retry_count: int,
        current_time: datetime,
    ) -> None:
        """租约反复过期的行达到 max_attempts 后置终态，不再交投。"""
        connection.execute(
            """
            UPDATE send_requests
            SET state = ?,
                claimed_from_state = NULL,
                lease_expires_at = NULL,
                next_retry_at = NULL,
                retry_count = ?,
                updated_at = ?
            WHERE dedupe_key = ?
            """,
            (
                ReceiptState.FAILED_FINAL.value,
                retry_count,
                current_time.isoformat(),
                row["dedupe_key"],
            ),
        )
        send_request = SendRequest.model_validate_json(str(row["request_json"]))
        receipt = DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=SQLITE_QUEUE_TRANSPORT,
            retry_count=retry_count,
            public_message="",
        )
        self._append_sender_audit(send_request, receipt, "send_failed_final")

    def _defer_for_bot_unavailable(
        self,
        connection: sqlite3.Connection,
        entry: QueuedSendRequest,
        issue: OperationalIssue,
        public_message: str,
        *,
        now: datetime,
    ) -> DeliveryReceipt:
        """B-4（管线检视 #6）：NapCat 断线的投递挂起，不消耗重试预算。

        bot_unavailable 是环境性暂态：照常计入 attempts 会让断线期间排队的
        回复在 ~3 分钟内烧完 max_attempts 后被 FAILED_FINAL 静默丢弃。这里
        只顺延下次尝试时间、不递增 retry_count（挂起至 bot 恢复，恢复后
        下一轮认领即投）；入队超过 bot_unavailable 年龄上限仍不可投才置
        终态，防止 A4 契约（非终态永不淘汰）下死挂行无限堆积。
        """
        hold_expired = (
            now - entry.created_at
        ).total_seconds() >= self._bot_unavailable_max_age_seconds
        if hold_expired:
            receipt = self._update_state_in(
                connection,
                entry.send_request,
                state=ReceiptState.FAILED_FINAL,
                retry_count=entry.retry_count,
                next_retry_at=None,
                public_message=public_message,
                now=now,
                operational_issue=issue,
            )
            event = "send_failed_final"
        else:
            next_retry_at = now + timedelta(
                seconds=max(
                    self.retry_base_seconds, _BOT_UNAVAILABLE_RETRY_DELAY_SECONDS
                )
            )
            receipt = self._update_state_in(
                connection,
                entry.send_request,
                state=ReceiptState.FAILED_RETRYABLE,
                retry_count=entry.retry_count,
                next_retry_at=next_retry_at,
                public_message=public_message,
                now=now,
                operational_issue=issue,
            )
            event = "send_deferred_bot_unavailable"
        self._append_sender_audit(entry.send_request, receipt, event)
        return receipt

    def mark_retryable_failure(
        self,
        request_id: str,
        public_message: str,
        *,
        now: datetime | None = None,
        operational_issue: OperationalIssue | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            entry = self._find_entry_in(connection, request_id)
            if entry is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )

            issue = operational_issue or entry.send_request.operational_issue
            public_message = "" if issue is not None else public_message
            if issue is not None and str(issue.kind) == _BOT_UNAVAILABLE_KIND:
                return self._defer_for_bot_unavailable(
                    connection, entry, issue, public_message, now=current_time
                )
            retry_count = entry.retry_count + 1
            if retry_count >= self.max_attempts:
                receipt = self._update_state_in(
                    connection,
                    entry.send_request,
                    state=ReceiptState.FAILED_FINAL,
                    retry_count=retry_count,
                    next_retry_at=None,
                    public_message=public_message,
                    now=current_time,
                    operational_issue=issue,
                )
                event = "send_failed_final"
            else:
                next_retry_at = current_time + timedelta(
                    seconds=self._backoff_seconds(retry_count)
                )
                receipt = self._update_state_in(
                    connection,
                    entry.send_request,
                    state=ReceiptState.FAILED_RETRYABLE,
                    retry_count=retry_count,
                    next_retry_at=next_retry_at,
                    public_message=public_message,
                    now=current_time,
                    operational_issue=issue,
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
        operational_issue: OperationalIssue | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            entry = self._find_entry_in(connection, request_id)
            if entry is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )
            issue = operational_issue or entry.send_request.operational_issue
            public_message = "" if issue is not None else public_message
            receipt = self._update_state_in(
                connection,
                entry.send_request,
                state=ReceiptState.SENT,
                retry_count=entry.retry_count,
                next_retry_at=None,
                public_message=public_message,
                now=current_time,
                operational_issue=issue,
            )
        self._append_sender_audit(entry.send_request, receipt, "send_marked_sent")
        return receipt

    def mark_final_failure(
        self,
        request_id: str,
        public_message: str,
        *,
        now: datetime | None = None,
        operational_issue: OperationalIssue | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            entry = self._find_entry_in(connection, request_id)
            if entry is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )
            issue = operational_issue or entry.send_request.operational_issue
            public_message = "" if issue is not None else public_message
            receipt = self._update_state_in(
                connection,
                entry.send_request,
                state=ReceiptState.FAILED_FINAL,
                retry_count=entry.retry_count,
                next_retry_at=None,
                public_message=public_message,
                now=current_time,
                operational_issue=issue,
            )
        self._append_sender_audit(entry.send_request, receipt, "send_failed_final")
        return receipt

    def safe_summary(self) -> dict[str, int]:
        self._ensure_schema_once()
        summary = {
            ReceiptState.QUEUED.value: 0,
            ReceiptState.FAILED_RETRYABLE.value: 0,
            ReceiptState.FAILED_FINAL.value: 0,
            ReceiptState.SENT.value: 0,
            ReceiptState.SKIPPED.value: 0,
            PROCESSING_STATE: 0,
        }
        with self._locked_connection() as connection:
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
            # WAL：订阅推送并发读写场景减少 busy；切换失败（如网络盘不支持）
            # 降级为默认 journal 模式，不致命。
            try:
                connection.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass
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
        # timeout：写锁被占时最多等 5s 再报 busy，避免默认语义下偶发立即失败。
        connection = sqlite3.connect(self.db_path, timeout=5.0)
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
        # 只淘汰终态行（死信不堆积）：非终态（QUEUED/PROCESSING/
        # FAILED_RETRYABLE）是待投递或在途消息，被容量/时间序挤掉等于
        # 静默丢消息，故永不淘汰（A4 契约：宁可表超限也不丢在途）。
        connection.execute(
            """
            DELETE FROM send_requests
            WHERE state IN (?, ?, ?)
              AND dedupe_key NOT IN (
                SELECT dedupe_key
                FROM send_requests
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
            )
            """,
            (
                ReceiptState.SENT.value,
                ReceiptState.FAILED_FINAL.value,
                ReceiptState.SKIPPED.value,
                self.max_items,
            ),
        )
        self._warn_if_over_soft_ceiling(connection)

    def _warn_if_over_soft_ceiling(
        self, connection: sqlite3.Connection
    ) -> None:
        """A4 契约不丢在途消息，但超限必须可观测：超过 8×max_items 告警一次。"""
        row = connection.execute(
            "SELECT COUNT(*) FROM send_requests"
        ).fetchone()
        total = int(row[0]) if row is not None else 0
        ceiling = max(1, self.max_items) * 8
        if total > ceiling:
            if not getattr(self, "_soft_ceiling_warned", False):
                self._soft_ceiling_warned = True
                logging.getLogger(__name__).warning(
                    "send queue over soft ceiling rows=%s max_items=%s "
                    "(in-flight rows are protected by A4, check worker health)",
                    total,
                    self.max_items,
                )
        else:
            self._soft_ceiling_warned = False

    def _find_entry_by_request_id(self, request_id: str) -> QueuedSendRequest | None:
        self._ensure_schema_once()
        with self._locked_connection() as connection:
            return self._find_entry_in(connection, request_id)

    def _find_entry_in(
        self, connection: sqlite3.Connection, request_id: str
    ) -> QueuedSendRequest | None:
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

    def _update_state_in(
        self,
        connection: sqlite3.Connection,
        send_request: SendRequest,
        *,
        state: ReceiptState,
        retry_count: int,
        next_retry_at: datetime | None,
        public_message: str,
        now: datetime,
        operational_issue: OperationalIssue | None = None,
    ) -> DeliveryReceipt:
        """在调用方事务内更新行状态（mark_* 的单事务写路径）。"""
        issue = operational_issue or send_request.operational_issue
        public_message = "" if issue is not None else public_message
        persisted_request = (
            send_request.model_copy(update={"operational_issue": issue})
            if issue is not send_request.operational_issue
            else send_request
        )
        connection.execute(
            """
            UPDATE send_requests
            SET state = ?,
                request_json = ?,
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
                persisted_request.model_dump_json(),
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
            operational_issue=issue,
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
            bot_unavailable_max_age_seconds=float(
                getattr(config, "bot_send_bot_unavailable_max_age_seconds", 1800.0)
            ),
        )
    return InMemorySendQueue(audit_logger=audit_logger)

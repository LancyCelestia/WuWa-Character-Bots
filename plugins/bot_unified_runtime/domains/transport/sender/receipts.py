from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    OperationalIssue,
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
    """内存回执仓库：有界（FIFO 淘汰最旧）。

    每条消息（含被拦截的）都记一条回执且进程内常驻，无上界时随运行
    时长线性吃内存、find/list 全量倒扫越来越慢。
    """

    def __init__(self, *, max_receipts: int = 1000) -> None:
        self.max_receipts = max(1, int(max_receipts))
        self._receipts: list[DeliveryReceipt] = []

    def record(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        while len(self._receipts) >= self.max_receipts:
            self._receipts.pop(0)
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
        # 每次操作都重跑建表 DDL 是纯浪费：进程内建一次即可（含 WAL 切换）。
        self._schema_ready = False
        # 进程内长连接（B-10，管线检视 #13）：消除每操作建连开销
        # （旧实现 with self._connect() 从不 close，连接全靠 GC 回收）。
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
        """共享连接上的写事务：正常提交、异常回滚（sqlite3.Error 弃连接）。"""
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
    def _locked_connection(self):
        """只读操作对共享连接的持锁借用。"""
        with self._connection_lock:
            yield self._shared_connection()

    def record(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        self._ensure_schema_once()
        if receipt.operational_issue is not None:
            receipt = receipt.model_copy(update={"public_message": ""})
        with self._transaction() as connection:
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
                    operational_issue_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(debug_id) DO UPDATE SET
                    request_id=excluded.request_id,
                    state=excluded.state,
                    transport=excluded.transport,
                    provider_message_id=excluded.provider_message_id,
                    retry_count=excluded.retry_count,
                    next_retry_at=excluded.next_retry_at,
                    public_message=excluded.public_message,
                    operational_issue_json=excluded.operational_issue_json,
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
                    json.dumps(
                        receipt.operational_issue.model_dump(mode="json")
                        if receipt.operational_issue is not None
                        else None,
                        ensure_ascii=False,
                    )
                    if receipt.operational_issue is not None
                    else None,
                    receipt.created_at.isoformat(),
                ),
            )
            self._prune(connection)
        return receipt

    def latest(self, request_id: str | None = None) -> DeliveryReceipt | None:
        self._ensure_schema_once()
        with self._locked_connection() as connection:
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
        self._ensure_schema_once()
        with self._locked_connection() as connection:
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
        self._ensure_schema_once()
        with self._locked_connection() as connection:
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
        with closing(self._connect()) as connection, connection:
            # WAL：并发读写场景减少 busy；切换失败降级为默认模式，不致命。
            try:
                connection.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass
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
                    operational_issue_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(delivery_receipts)")
            }
            if "operational_issue_json" not in columns:
                connection.execute(
                    "ALTER TABLE delivery_receipts ADD COLUMN operational_issue_json TEXT"
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
        # timeout：写锁被占时最多等 5s 再报 busy。
        connection = sqlite3.connect(self.db_path, timeout=5.0)
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
        operational_issue = (
            OperationalIssue.model_validate(json.loads(row["operational_issue_json"]))
            if row["operational_issue_json"]
            else None
        )
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
            public_message="" if operational_issue is not None else str(row["public_message"]),
            debug_id=str(row["debug_id"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            operational_issue=operational_issue,
        )


def sent_receipt(send_request: SendRequest) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SENT,
        transport="memory",
        public_message="sent",
        operational_issue=send_request.operational_issue,
    )


def skipped_receipt(send_request: SendRequest, reason: str) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SKIPPED,
        transport="memory",
        public_message="" if send_request.operational_issue is not None else reason,
        operational_issue=send_request.operational_issue,
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

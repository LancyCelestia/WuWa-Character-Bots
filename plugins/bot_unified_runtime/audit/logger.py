from __future__ import annotations

import re
import sqlite3
from collections import deque
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import AuditRecord, RiskLevel

# 脱敏：键名必须按「含标识符字符的整词」匹配。旧写法 `\b(token|cookie|…)` 在
# `access_token=` 这类**下划线前缀**形态上会失配——`token` 前的 `_` 是单词字符，
# `\b` 不成立，于是 NapCat OneBot WS 的真实形态
# `ws://127.0.0.1:3001/?access_token=<token>` 会**以明文**写进审计/JSONL/日志桥
# （评审 H7，实测 3/11 形态泄漏）。这里改为 `[a-z0-9_]*(关键字)[a-z0-9_]*`，
# 兼容 access_token / refresh_token / csrf_token / x-api-key / db_password 等。
_KEY_VALUE_SECRET_RE = re.compile(
    r"(?i)\b([a-z0-9_]*(?:token|secret|cookie|authkey|password|passwd|apikey|api[_-]?key|"
    r"access[_-]?key|private[_-]?key|credential|session[_-]?id)[a-z0-9_]*)"
    r"\s*[:=]\s*[^\s;&]+"
)
_AUTHORIZATION_RE = re.compile(r"(?i)\b(authorization)\s*:\s*bearer\s+[^\s;]+")
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[^\s;]+")
_OPENAI_KEY_RE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9][A-Za-z0-9_-]{8,}")


class AuditRepository(Protocol):
    def append(self, record: AuditRecord) -> AuditRecord:
        raise NotImplementedError

    def list_records(self, request_id: str | None = None) -> list[AuditRecord]:
        raise NotImplementedError


def redact_private_debug(value: str) -> str:
    redacted = _KEY_VALUE_SECRET_RE.sub(
        lambda match: f"{match.group(1)}=[redacted]",
        value,
    )
    redacted = _AUTHORIZATION_RE.sub(
        lambda match: f"{match.group(1)}: Bearer [redacted]",
        redacted,
    )
    redacted = _BEARER_RE.sub(
        lambda match: f"{match.group(1)} [redacted]",
        redacted,
    )
    redacted = _OPENAI_KEY_RE.sub("sk-[redacted]", redacted)
    return redacted


class InMemoryAuditLogger:
    """内存审计仓库：有界（FIFO 淘汰最旧）+ request_id 索引。

    每条消息会写 3-8 条审计记录且进程内常驻——无上界时随运行时长线性
    吃内存，list_records 全表扫描随累积退化成 O(M²)。上限与 SQLite 版
    的 bot_audit_max_items 语义对齐（默认同 1000）。
    """

    def __init__(self, *, max_entries: int = 1000) -> None:
        self._max_entries = max(1, int(max_entries))
        self._records: deque[AuditRecord] = deque(maxlen=self._max_entries)
        self._by_request: dict[str, list[AuditRecord]] = {}

    def append(self, record: AuditRecord) -> AuditRecord:
        safe_record = record.model_copy(
            update={"private_debug": redact_private_debug(record.private_debug)}
        )
        evicted = None
        if len(self._records) >= self._max_entries:
            evicted = self._records[0]
        self._records.append(safe_record)
        if evicted is not None:
            bucket = self._by_request.get(evicted.request_id)
            if bucket is not None:
                try:
                    bucket.remove(evicted)
                except ValueError:
                    pass
                if not bucket:
                    del self._by_request[evicted.request_id]
        self._by_request.setdefault(safe_record.request_id, []).append(safe_record)
        return safe_record

    def list_records(self, request_id: str | None = None) -> list[AuditRecord]:
        if request_id is None:
            return list(self._records)
        return list(self._by_request.get(request_id, []))


class SQLiteAuditRepository:
    def __init__(self, db_path: str | Path, max_items: int = 1000) -> None:
        self.db_path = Path(db_path)
        self.max_items = max(1, int(max_items))
        # 每次 append 都重跑建表 DDL 是纯浪费：进程内建一次即可。
        self._schema_ready = False

    def _ensure_schema_once(self) -> None:
        if self._schema_ready:
            return
        self._ensure_schema()
        self._schema_ready = True

    def append(self, record: AuditRecord) -> AuditRecord:
        self._ensure_schema_once()
        safe_record = record.model_copy(
            update={"private_debug": redact_private_debug(record.private_debug)}
        )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO audit_records (
                    audit_id,
                    request_id,
                    session_id,
                    capability_id,
                    stage,
                    event,
                    severity,
                    public_message,
                    private_debug,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(audit_id) DO UPDATE SET
                    request_id=excluded.request_id,
                    session_id=excluded.session_id,
                    capability_id=excluded.capability_id,
                    stage=excluded.stage,
                    event=excluded.event,
                    severity=excluded.severity,
                    public_message=excluded.public_message,
                    private_debug=excluded.private_debug,
                    created_at=excluded.created_at
                """,
                (
                    safe_record.audit_id,
                    safe_record.request_id,
                    safe_record.session_id,
                    safe_record.capability_id,
                    safe_record.stage,
                    safe_record.event,
                    safe_record.severity.value,
                    safe_record.public_message,
                    safe_record.private_debug,
                    safe_record.created_at.isoformat(),
                ),
            )
            self._prune(connection)
        return safe_record

    def list_records(self, request_id: str | None = None) -> list[AuditRecord]:
        self._ensure_schema_once()
        with closing(self._connect()) as connection, connection:
            if request_id is None:
                cursor = connection.execute(
                    """
                    SELECT *
                    FROM audit_records
                    ORDER BY created_at ASC, rowid ASC
                    """
                )
            else:
                cursor = connection.execute(
                    """
                    SELECT *
                    FROM audit_records
                    WHERE request_id = ?
                    ORDER BY created_at ASC, rowid ASC
                    """,
                    (request_id,),
                )
            return [self._from_row(row) for row in cursor.fetchall()]

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_records (
                    audit_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    event TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    public_message TEXT NOT NULL,
                    private_debug TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_records_request_time
                ON audit_records (request_id, created_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _prune(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM audit_records
            WHERE audit_id NOT IN (
                SELECT audit_id
                FROM audit_records
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
            )
            """,
            (self.max_items,),
        )

    def _from_row(self, row: sqlite3.Row) -> AuditRecord:
        return AuditRecord(
            audit_id=str(row["audit_id"]),
            request_id=str(row["request_id"]),
            session_id=str(row["session_id"]),
            capability_id=str(row["capability_id"]),
            stage=str(row["stage"]),
            event=str(row["event"]),
            severity=RiskLevel(str(row["severity"])),
            public_message=str(row["public_message"]),
            private_debug=str(row["private_debug"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )


def build_audit_repository(config: Config) -> AuditRepository:
    enabled = bool(getattr(config, "bot_audit_enabled", False))
    db_path = str(getattr(config, "bot_audit_db_path", "")).strip()
    max_items = int(getattr(config, "bot_audit_max_items", 1000))
    if enabled and db_path:
        return SQLiteAuditRepository(db_path, max_items=max_items)
    return InMemoryAuditLogger(max_entries=max_items)

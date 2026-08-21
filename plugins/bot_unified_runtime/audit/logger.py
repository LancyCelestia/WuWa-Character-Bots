from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import sqlite3
from typing import Protocol

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import AuditRecord, RiskLevel

_KEY_VALUE_SECRET_RE = re.compile(
    r"(?i)\b(token|cookie|authkey|password|secret|api[_-]?key)\s*[:=]\s*[^\s;]+"
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
    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> AuditRecord:
        safe_record = record.model_copy(
            update={"private_debug": redact_private_debug(record.private_debug)}
        )
        self._records.append(safe_record)
        return safe_record

    def list_records(self, request_id: str | None = None) -> list[AuditRecord]:
        if request_id is None:
            return list(self._records)
        return [record for record in self._records if record.request_id == request_id]


class SQLiteAuditRepository:
    def __init__(self, db_path: str | Path, max_items: int = 1000) -> None:
        self.db_path = Path(db_path)
        self.max_items = max(1, int(max_items))

    def append(self, record: AuditRecord) -> AuditRecord:
        self._ensure_schema()
        safe_record = record.model_copy(
            update={"private_debug": redact_private_debug(record.private_debug)}
        )
        with self._connect() as connection:
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
        self._ensure_schema()
        with self._connect() as connection:
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
        with self._connect() as connection:
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
    return InMemoryAuditLogger()

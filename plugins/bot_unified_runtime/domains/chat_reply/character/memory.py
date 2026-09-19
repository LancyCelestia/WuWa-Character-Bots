from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.contracts import MemoryRetrievalResult, PrivacyLevel

MEMORY_SENSITIVITIES = frozenset({"public", "group", "personal", "credentialed"})


class MemoryProvider(Protocol):
    def retrieve(
        self,
        *,
        request_id: str,
        requester_id: str,
        subject_user_id: str,
        session_id: str,
        query_text: str,
        max_items: int,
        max_chars: int,
    ) -> MemoryRetrievalResult:
        raise NotImplementedError


class NullMemoryProvider:
    def retrieve(
        self,
        *,
        request_id: str,
        requester_id: str,
        subject_user_id: str,
        session_id: str,
        query_text: str,
        max_items: int,
        max_chars: int,
    ) -> MemoryRetrievalResult:
        return MemoryRetrievalResult(request_id=request_id)


class SQLiteMemoryRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def upsert_fact(
        self,
        *,
        fact_id: str,
        subject_user_id: str,
        session_id: str,
        memory_kind: str,
        text: str,
        confidence: float = 0.8,
        source: str = "sqlite",
        sensitivity: str = "personal",
        scope_key: str | None = None,
    ) -> None:
        self._ensure_schema()
        now = datetime.now(UTC).isoformat()
        normalized_sensitivity = normalize_memory_sensitivity(sensitivity)
        normalized_scope_key = scope_key or build_scope_key(session_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_facts (
                    fact_id,
                    subject_user_id,
                    session_id,
                    memory_kind,
                    text,
                    confidence,
                    source,
                    sensitivity,
                    scope_key,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fact_id) DO UPDATE SET
                    subject_user_id=excluded.subject_user_id,
                    session_id=excluded.session_id,
                    memory_kind=excluded.memory_kind,
                    text=excluded.text,
                    confidence=excluded.confidence,
                    source=excluded.source,
                    sensitivity=excluded.sensitivity,
                    scope_key=excluded.scope_key,
                    updated_at=excluded.updated_at
                """,
                (
                    fact_id,
                    subject_user_id,
                    session_id,
                    memory_kind,
                    text,
                    confidence,
                    source,
                    normalized_sensitivity,
                    normalized_scope_key,
                    now,
                    now,
                ),
            )

    def retrieve(
        self,
        *,
        request_id: str,
        requester_id: str,
        subject_user_id: str,
        session_id: str,
        query_text: str,
        max_items: int,
        max_chars: int,
    ) -> MemoryRetrievalResult:
        if max_items <= 0 or max_chars <= 0:
            return MemoryRetrievalResult(request_id=request_id, privacy_level=PrivacyLevel.PERSONAL)
        if requester_id != subject_user_id:
            return MemoryRetrievalResult(request_id=request_id, privacy_level=PrivacyLevel.PERSONAL)
        self._ensure_schema()
        rows = self._fetch_candidate_rows(
            subject_user_id=subject_user_id,
            session_id=session_id,
            limit=max_items,
        )
        facts: list[dict[str, str]] = []
        chars_used = 0
        for row in rows:
            text = str(row["text"])
            remaining = max_chars - chars_used
            if remaining <= 0:
                break
            if len(text) > remaining:
                text = _clip_text(text, remaining)
            facts.append(
                {
                    "fact_id": str(row["fact_id"]),
                    "kind": str(row["memory_kind"]),
                    "text": text,
                    "source": str(row["source"]),
                    "sensitivity": str(row["sensitivity"] or "personal"),
                    "scope_key": str(row["scope_key"] or build_scope_key(str(row["session_id"]))),
                }
            )
            chars_used += len(text)
            if len(facts) >= max_items:
                break
        confidence = max((float(row["confidence"]) for row in rows[: len(facts)]), default=0.0)
        return MemoryRetrievalResult(
            request_id=request_id,
            facts=facts,
            confidence=confidence,
            privacy_level=PrivacyLevel.PERSONAL,
        )

    def delete_fact(
        self,
        *,
        fact_id: str,
        subject_user_id: str,
        session_id: str,
    ) -> bool:
        self._ensure_schema()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM memory_facts
                WHERE fact_id = ?
                  AND subject_user_id = ?
                  AND session_id IN (?, '', '*', 'global')
                """,
                (fact_id, subject_user_id, session_id),
            )
            return cursor.rowcount > 0

    def _fetch_candidate_rows(
        self,
        *,
        subject_user_id: str,
        session_id: str,
        limit: int,
    ) -> list[sqlite3.Row]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT fact_id, session_id, memory_kind, text, confidence, source, sensitivity, scope_key
                FROM memory_facts
                WHERE subject_user_id = ?
                  AND session_id IN (?, '', '*', 'global')
                ORDER BY updated_at DESC, fact_id DESC
                LIMIT ?
                """,
                (subject_user_id, session_id, limit),
            )
            return list(cursor.fetchall())

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_facts (
                    fact_id TEXT PRIMARY KEY,
                    subject_user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    memory_kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.8,
                    source TEXT NOT NULL DEFAULT 'sqlite',
                    sensitivity TEXT NOT NULL DEFAULT 'personal',
                    scope_key TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(connection, "memory_facts", "sensitivity", "TEXT NOT NULL DEFAULT 'personal'")
            self._ensure_column(connection, "memory_facts", "scope_key", "TEXT NOT NULL DEFAULT ''")

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
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection


def build_memory_provider(config: object) -> MemoryProvider:
    enabled = bool(getattr(config, "bot_memory_enabled", False))
    db_path = str(getattr(config, "bot_memory_db_path", "")).strip()
    if not enabled or not db_path:
        return NullMemoryProvider()
    return SQLiteMemoryRepository(db_path)


def build_fact_id(subject_user_id: str, session_id: str, text: str) -> str:
    digest = sha1(f"{subject_user_id}:{session_id}:{text}".encode()).hexdigest()[:12]
    return f"fact_{digest}"


def build_scope_key(session_id: str) -> str:
    normalized = session_id.strip() or "global"
    if normalized in {"*", "global"}:
        return "global"
    return f"session:{normalized}"


def normalize_memory_sensitivity(value: str) -> str:
    normalized = value.strip().lower() or "personal"
    if normalized not in MEMORY_SENSITIVITIES:
        raise ValueError(f"unsupported memory sensitivity: {value}")
    return normalized


def _clip_text(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 1:
        return "…"
    return f"{value[: max_chars - 1]}…"

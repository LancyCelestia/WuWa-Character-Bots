from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path
from typing import Any, Protocol

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
    """旧 ``memory_facts`` 仓储（v1 真身）。

    ``bus`` 注入位（WP6 记忆总线 v2）：**不传=逐字节旧行为**（默认，且生产现存
    两处构造点都不传）；传了则写/删/读三面统一走总线，本仓储退化为「总线未启用
    时的旧路径 + 总线的影子读来源」。开关只在装配层判（``build_memory_provider``），
    仓储自身不读配置——避免同一份开关在两层各判一次而漂移。
    """

    def __init__(self, db_path: str | Path, *, bus: Any | None = None) -> None:
        self.db_path = Path(db_path)
        self._bus = bus

    @property
    def bus(self) -> Any | None:
        return self._bus

    @property
    def recall_mode(self) -> str:
        """本仓储的取数口径（装配层与观测面据此归因，不是第二套开关判定）。

        ``legacy_newest_n`` = 总线没开：SQL 只按 ``updated_at DESC`` 取最近 N 条，
        **``query_text`` 收下不用**——本轮注入可能与话题毫不相干。这是有意的
        关态旧行为（逐字节不变），但必须是个可读到的事实而不是沉默。
        """
        return "memory_bus" if self._bus is not None else "legacy_newest_n"

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
        provenance: str = "explicit",
    ) -> str:
        """写入一条事实，返回**落库后的真实 id**（命令面要拿它回话/删除）。

        旧路径逐字节不变（含返回入参 fact_id）；总线路径返回总线自己的 memory_id——
        总线按槽位合并，同一条偏好再说一次会回到既有那行的 id，而不是新造一个。
        """
        if self._bus is not None:
            # 总线口径：显式命令=explicit（永远压过归纳），槽位/极性等由总线算。
            outcome = self._bus.absorb(
                owner_id=subject_user_id,
                subject_user_id=subject_user_id,
                text=text,
                session_id=session_id,
                category=memory_kind,
                confidence=confidence,
                provenance=provenance,
                source=source,
                sensitivity=sensitivity,
            )
            return str(getattr(outcome, "memory_id", "") or fact_id)
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
        return fact_id

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
        if self._bus is not None:
            from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
                MemoryBusProvider,
            )

            return MemoryBusProvider(self._bus).retrieve(
                request_id=request_id,
                requester_id=requester_id,
                subject_user_id=subject_user_id,
                session_id=session_id,
                query_text=query_text,
                max_items=max_items,
                max_chars=max_chars,
            )
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
        if self._bus is not None:
            # 总线口径：真删=墓碑先行 + 行翻 forgotten（旧库这条是硬 DELETE）。
            return self._bus.forget(
                memory_id=fact_id, owner_id=subject_user_id, forgotten_by=subject_user_id
            )
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

    def list_rows_for_subject(self, subject_user_id: str) -> list[dict[str, Any]]:
        """总线影子读来源：旧库该主体的存活行（只读，不改写、不复活）。"""
        self._ensure_schema()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT fact_id, subject_user_id, session_id, memory_kind, text,
                       confidence, source, sensitivity, scope_key, created_at, updated_at
                FROM memory_facts
                WHERE subject_user_id = ?
                ORDER BY updated_at ASC, fact_id ASC
                LIMIT 200
                """,
                (subject_user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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


def build_memory_read_path(
    config: object,
) -> tuple[MemoryProvider, MemoryProvider | None]:
    """召回侧唯一装配口：给出 ``(主腿, 兜底腿)``，两腿**永不同时打分**。

    - 开关关=逐字节旧行为：主腿=只认 ``memory_facts`` 的旧仓储（``recall_mode=
      `` ``legacy_newest_n``，按时间取最近 N 条、不看本轮查询），兜底腿=None；
      **不建总线库、不开新连接**。
    - 开关开=主腿=``MemoryBusProvider``（v2 统一打分召回，旧库行作为 explicit
      影子候选并进同一套打分），兜底腿=同一个旧仓储实例——只在总线**抛异常**时
      经合并层调用一次，且那次降级必须落审计（``providers`` 侧执法）。
      兜底腿平时不参与，故不存在「两套排序串接」；它的 ``memory_facts`` 读面
      与总线影子读同源同库，不会多出第二身份。
    """
    enabled = bool(getattr(config, "bot_memory_enabled", False))
    db_path = str(getattr(config, "bot_memory_db_path", "")).strip()
    if not enabled or not db_path:
        return NullMemoryProvider(), None
    repository = SQLiteMemoryRepository(db_path)
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
        MemoryBusProvider,
        build_memory_bus,
    )

    bus = build_memory_bus(
        config, legacy_explicit_reader=repository.list_rows_for_subject
    )
    if bus is None:
        return repository, None
    return MemoryBusProvider(bus), repository


def build_memory_repository(config: object) -> MemoryProvider:
    """旧签名兼容口：只要主腿（消费腿请用 ``build_memory_read_path``）。"""
    primary, _fallback = build_memory_read_path(config)
    return primary


def build_memory_provider(config: object) -> MemoryProvider:
    return build_memory_repository(config)


def build_memory_bus_for_writer(config: object) -> Any | None:
    """写入侧装配口（沉淀路径）：总线开着就给出总线，否则 None=旧路径。

    与召回侧共用 ``bot_memory_db_path`` 的单一 store 连接（``shared_bus_store``
    按路径缓存），两条路永远看的是同一张表——这正是「一个真身存储」的落点。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
        build_memory_bus,
    )

    return build_memory_bus(config)


def legacy_explicit_reader_for(db_path: str | Path) -> Callable[[str], list[dict[str, Any]]]:
    """把「按主体读旧库行」包成总线要的注入缝。"""
    repository = SQLiteMemoryRepository(db_path)
    return repository.list_rows_for_subject


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

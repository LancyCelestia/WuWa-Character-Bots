from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.contracts import (
    ConversationHistoryResult,
    ConversationTurn,
    PrivacyLevel,
)


class ConversationHistoryProvider(Protocol):
    def retrieve(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        max_turns: int,
        max_chars: int,
    ) -> ConversationHistoryResult:
        raise NotImplementedError


class ConversationHistoryRecorder(Protocol):
    def append_turn(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        role: str,
        text: str,
        kind: str = "chat",
    ) -> None:
        raise NotImplementedError


class ConversationHistoryCleaner(Protocol):
    def clear_scope(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
    ) -> int:
        raise NotImplementedError


class ConversationHistoryStore(
    ConversationHistoryProvider,
    ConversationHistoryRecorder,
    ConversationHistoryCleaner,
    Protocol,
):
    pass


class NullConversationHistoryProvider:
    def append_turn(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        role: str,
        text: str,
        kind: str = "chat",
    ) -> None:
        return None

    def retrieve(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        max_turns: int,
        max_chars: int,
    ) -> ConversationHistoryResult:
        return ConversationHistoryResult(request_id=request_id)

    def clear_scope(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
    ) -> int:
        return 0


class InMemoryConversationHistoryStore:
    """进程内最近对话历史：给控制台 REPL 等本地入口提供多轮连续性。

    重启即清空，不落盘；仅用于测试体验，真实机器人仍用
    SQLiteConversationHistoryRepository。
    """

    def __init__(self, *, max_turns: int = 40) -> None:
        self.max_turns = max(1, int(max_turns))
        self._turns: list[ConversationTurn] = []

    def append_turn(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        role: str,
        text: str,
        kind: str = "chat",
    ) -> None:
        clean_text = text.strip()
        if not clean_text:
            return
        self._turns.append(
            ConversationTurn(
                role=role,
                text=clean_text,
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns :]

    def retrieve(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        max_turns: int,
        max_chars: int,
    ) -> ConversationHistoryResult:
        selected: list[ConversationTurn] = []
        chars_used = 0
        for turn in reversed(self._turns):
            if len(selected) >= max_turns:
                break
            remaining = max_chars - chars_used
            if remaining <= 0:
                break
            text = _clip_text(turn.text, remaining)
            selected.append(
                ConversationTurn(
                    role=turn.role,
                    text=text,
                    created_at=turn.created_at,
                )
            )
            chars_used += len(text)
        selected.reverse()
        return ConversationHistoryResult(
            request_id=request_id,
            turns=selected,
            privacy_level=PrivacyLevel.PERSONAL,
        )

    def clear_scope(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
    ) -> int:
        cleared = len(self._turns)
        self._turns = []
        return cleared


class SQLiteConversationHistoryRepository:
    def __init__(self, db_path: str | Path, *, max_items: int = 1000) -> None:
        self.db_path = Path(db_path)
        self.max_items = max(1, int(max_items))

    def append_turn(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        role: str,
        text: str,
        kind: str = "chat",
    ) -> None:
        clean_text = text.strip()
        if not clean_text:
            return
        self._ensure_schema()
        safe_kind = kind if kind in {"chat", "command", "system"} else "chat"
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_turns (
                    request_id,
                    platform,
                    adapter,
                    bot_id,
                    session_id,
                    sender_id,
                    role,
                    text,
                    created_at,
                    kind
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    platform,
                    adapter,
                    bot_id,
                    session_id,
                    sender_id,
                    role,
                    clean_text,
                    now,
                    safe_kind,
                ),
            )
            self._prune_scope(
                connection,
                platform=platform,
                adapter=adapter,
                bot_id=bot_id,
                session_id=session_id,
                sender_id=sender_id,
            )

    def retrieve(
        self,
        *,
        request_id: str,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        max_turns: int,
        max_chars: int,
    ) -> ConversationHistoryResult:
        if max_turns <= 0 or max_chars <= 0:
            return ConversationHistoryResult(request_id=request_id)
        self._ensure_schema()
        rows = self._fetch_rows(
            platform=platform,
            adapter=adapter,
            bot_id=bot_id,
            session_id=session_id,
            sender_id=sender_id,
            limit=max_turns,
        )
        selected: list[ConversationTurn] = []
        chars_used = 0
        for row in rows:
            remaining = max_chars - chars_used
            if remaining <= 0:
                break
            text = str(row["text"])
            if len(text) > remaining:
                text = _clip_text(text, remaining)
            selected.append(
                ConversationTurn(
                    role=str(row["role"]),
                    text=text,
                    created_at=str(row["created_at"]),
                )
            )
            chars_used += len(text)
        return ConversationHistoryResult(
            request_id=request_id,
            turns=list(reversed(selected)),
            privacy_level=PrivacyLevel.PERSONAL,
        )

    def clear_scope(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
    ) -> int:
        self._ensure_schema()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM conversation_turns
                WHERE platform = ?
                  AND adapter = ?
                  AND bot_id = ?
                  AND session_id = ?
                  AND sender_id = ?
                """,
                (platform, adapter, bot_id, session_id, sender_id),
            )
            return max(0, cursor.rowcount)

    def _fetch_rows(
        self,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
        limit: int,
    ) -> list[sqlite3.Row]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT role, text, created_at
                FROM conversation_turns
                WHERE platform = ?
                  AND adapter = ?
                  AND bot_id = ?
                  AND session_id = ?
                  AND sender_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (platform, adapter, bot_id, session_id, sender_id, limit),
            )
            return list(cursor.fetchall())

    def _prune_scope(
        self,
        connection: sqlite3.Connection,
        *,
        platform: str,
        adapter: str,
        bot_id: str,
        session_id: str,
        sender_id: str,
    ) -> None:
        connection.execute(
            """
            DELETE FROM conversation_turns
            WHERE platform = ?
              AND adapter = ?
              AND bot_id = ?
              AND session_id = ?
              AND sender_id = ?
              AND rowid NOT IN (
                  SELECT rowid
                  FROM conversation_turns
                  WHERE platform = ?
                    AND adapter = ?
                    AND bot_id = ?
                    AND session_id = ?
                    AND sender_id = ?
                  ORDER BY created_at DESC, rowid DESC
                  LIMIT ?
              )
            """,
            (
                platform,
                adapter,
                bot_id,
                session_id,
                sender_id,
                platform,
                adapter,
                bot_id,
                session_id,
                sender_id,
                self.max_items,
            ),
        )

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    request_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            # 兼容旧表：补充 kind 列，区分 LLM 人设回复（chat）与
            # 命令/被动回复（command），供群共享摘要过滤使用。
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(conversation_turns)"
                ).fetchall()
            }
            if "kind" not in columns:
                connection.execute(
                    "ALTER TABLE conversation_turns "
                    "ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_turns_scope_time
                ON conversation_turns (
                    platform,
                    adapter,
                    bot_id,
                    session_id,
                    sender_id,
                    created_at
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection


def build_conversation_history_provider(config: object) -> ConversationHistoryStore:
    enabled = bool(getattr(config, "bot_history_enabled", False))
    db_path = str(getattr(config, "bot_history_db_path", "")).strip()
    max_items = int(getattr(config, "bot_history_max_items", 1000))
    if not enabled or not db_path:
        return NullConversationHistoryProvider()
    return SQLiteConversationHistoryRepository(db_path, max_items=max_items)


def _clip_text(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 1:
        return "…"
    return f"{value[: max_chars - 1]}…"

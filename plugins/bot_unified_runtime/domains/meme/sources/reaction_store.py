"""贴纸回应持久化库（bot.reactions，B 线 2026-09-16）：把所有表情贴纸存下来。

职责单一：识别到的 emoji_like 事件按 (会话, 消息, emoji) 幂等落库、
按 emoji 聚合统计（谁最常用贴什么）、保留期裁剪（防无界增长）。
本模块绝不产生任何对外发送；与进程内环形缓冲（runtime/reactions.py
ReactionBuffer，10 分钟 TTL）互补——缓冲管「当前语境注入」，本库管
「长期记忆与统计」。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reaction_events (
    event_id    TEXT PRIMARY KEY,
    session_key TEXT NOT NULL,
    user_id     TEXT NOT NULL DEFAULT '',
    message_id  TEXT NOT NULL DEFAULT '',
    emoji_id    TEXT NOT NULL,
    emoji_text  TEXT NOT NULL DEFAULT '',
    count       INTEGER NOT NULL DEFAULT 1,
    platform    TEXT NOT NULL DEFAULT 'qq',
    occurred_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reaction_events_time ON reaction_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_reaction_events_emoji ON reaction_events(emoji_id);
CREATE INDEX IF NOT EXISTS idx_reaction_events_session ON reaction_events(session_key);
"""


class ReactionStore:
    """每操作独立连接的轻量 SQLite 库（CampusStore 同风格）。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def record_event(
        self,
        *,
        session_key: str,
        user_id: str,
        message_id: str,
        emoji_id: str,
        emoji_text: str = "",
        count: int = 1,
        platform: str = "qq",
        occurred_at: float | None = None,
    ) -> bool:
        """幂等落库：(session, message, emoji) 重复事件合并计数；空 emoji 忽略。

        返回是否新写入（重复/空忽略返回 False，调用方静默即可）。
        """
        safe_emoji = str(emoji_id or "").strip()
        safe_session = str(session_key or "").strip()
        if not safe_emoji or not safe_session:
            return False
        try:
            occurred = float(occurred_at if occurred_at is not None else time.time())
            count_value = max(1, int(count or 1))
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO reaction_events"
                    " (event_id, session_key, user_id, message_id, emoji_id,"
                    "  emoji_text, count, platform, occurred_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(event_id) DO UPDATE SET"
                    "  count = count + excluded.count",
                    (
                        f"{safe_session}:{str(message_id or '').strip()}:{safe_emoji}",
                        safe_session,
                        str(user_id or "").strip(),
                        str(message_id or "").strip(),
                        safe_emoji,
                        str(emoji_text or "").strip(),
                        count_value,
                        str(platform or "qq"),
                        occurred,
                    ),
                )
                return cursor.rowcount > 0
        except sqlite3.Error:
            return False

    def emoji_stats(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """按 emoji 聚合：最常被贴的表情（次数降序）。"""
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT emoji_id, emoji_text, SUM(count) AS total, COUNT(*) AS events"
                    " FROM reaction_events GROUP BY emoji_id"
                    " ORDER BY total DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
            return [
                {
                    "emoji_id": str(row["emoji_id"]),
                    "emoji_text": str(row["emoji_text"] or ""),
                    "total": int(row["total"]),
                    "events": int(row["events"]),
                }
                for row in rows
            ]
        except sqlite3.Error:
            return []

    def user_stats(self, user_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """某用户最常贴的表情（次数降序）。"""
        safe_user = str(user_id or "").strip()
        if not safe_user:
            return []
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT emoji_id, emoji_text, SUM(count) AS total"
                    " FROM reaction_events WHERE user_id = ?"
                    " GROUP BY emoji_id ORDER BY total DESC LIMIT ?",
                    (safe_user, max(1, int(limit))),
                ).fetchall()
            return [
                {
                    "emoji_id": str(row["emoji_id"]),
                    "emoji_text": str(row["emoji_text"] or ""),
                    "total": int(row["total"]),
                }
                for row in rows
            ]
        except sqlite3.Error:
            return []

    def prune(self, *, keep_days: int = 90) -> int:
        """保留期裁剪；返回删除行数。"""
        if keep_days <= 0:
            return 0
        cutoff = time.time() - float(keep_days) * 86400.0
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM reaction_events WHERE occurred_at < ?", (cutoff,)
                )
                return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        except sqlite3.Error:
            return 0

"""校园信息管家消息库：学校账号所在群消息的本地持久化。

职责单一：按 message_id 幂等落库、按日期读回、保留期裁剪（防无界增长）。
所有写入口都在 domains.assistant.campus.campus.CampusForwardService 背后，
本模块绝不产生任何对外发送。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS campus_messages (
    message_id  TEXT PRIMARY KEY,
    self_id     TEXT NOT NULL DEFAULT '',
    group_id    TEXT NOT NULL,
    sender_id   TEXT NOT NULL DEFAULT '',
    sender_name TEXT NOT NULL DEFAULT '',
    text        TEXT NOT NULL DEFAULT '',
    date_key    TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campus_messages_date ON campus_messages(date_key);
"""


class CampusStore:
    """每操作独立连接的轻量 SQLite 库（与 SQLiteGroupDigestProvider 同风格）。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def record_message(
        self,
        *,
        message_id: str,
        self_id: str,
        group_id: str,
        sender_id: str = "",
        sender_name: str = "",
        text: str = "",
        date_key: str,
        occurred_at: str,
    ) -> bool:
        """幂等落库；message_id 重复（或为空）返回 False。"""
        safe_id = str(message_id).strip()
        if not safe_id:
            return False
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO campus_messages (
                        message_id, self_id, group_id,
                        sender_id, sender_name, text,
                        date_key, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        safe_id,
                        str(self_id or "").strip(),
                        str(group_id or "").strip(),
                        str(sender_id or "").strip(),
                        str(sender_name or "").strip(),
                        str(text or "").strip(),
                        str(date_key).strip(),
                        str(occurred_at).strip(),
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return cursor.rowcount > 0

    def list_day(self, date_key: str) -> list[Any]:
        """按日期键（YYYY-MM-DD）读回当日全部消息，按发生时间排序。"""
        with self._connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT message_id, self_id, group_id, sender_id,
                           sender_name, text, date_key, occurred_at
                    FROM campus_messages
                    WHERE date_key = ?
                    ORDER BY occurred_at, rowid
                    """,
                    (str(date_key).strip(),),
                ).fetchall()
            )

    def prune(self, *, keep_days: int = 90, now: datetime | None = None) -> int:
        """删除保留期外的旧行，返回删除条数；防消息库无界增长。"""
        current = now or datetime.now().astimezone()
        cutoff = (current - timedelta(days=max(1, int(keep_days)))).date().isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM campus_messages WHERE date_key < ?", (cutoff,)
            )
        return cursor.rowcount

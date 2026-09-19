"""出站 result-unknown 账本与重连对账（交接 P0.4 尾巴）。

OneBot 发送超时意味着消息可能已送达也可能没送达（result_unknown）。
本模块把这类"结果未知"持久化到 SQLite 账本；机器人重连时对账：

- 统计仍在 pending 的历史未知结果，写 ``result_unknown_reconciled`` 事件并
  通知管理员（由调用方决定是否告警）；
- 超过 TTL 的记录标记 ``expired``（OneBot 无按 request_id 查历史消息的 API，
  无法自动确认送达，保留人工排查入口）；
- OneBot 不提供"这条消息到底发没发出去"的查询接口，因此不做自动重发——
  重复发送的风险大于漏发，宁可记录、提示、不盲发。

账本纯本地，不产生任何网络请求。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReconcileSummary:
    pending: int
    expired: int
    by_bot: dict[str, int]
    purged: int = 0

    def render(self) -> str:
        if self.pending == 0 and self.expired == 0:
            return "无历史 result-unknown 待对账。"
        return (
            f"重连对账：pending={self.pending} expired={self.expired} "
            + " ".join(f"{bot}×{count}" for bot, count in sorted(self.by_bot.items()))
        )


class ResultUnknownLedger:
    """result-unknown 持久化账本；线程安全，纯本地 SQLite。"""

    def __init__(
        self,
        db_path: str | Path,
        *,
        expire_seconds: float = 86400.0,
        purge_after_seconds: float | None = None,
        clock: Any = time.time,
    ) -> None:
        self.db_path = Path(db_path)
        self.expire_seconds = max(60.0, float(expire_seconds))
        # 过期行在标记 expired 后仍保留一个排查窗口，超过 purge_after_seconds
        # 才物理删除（默认与 expire_seconds 相同），防台账随时间无上限增长。
        self.purge_after_seconds = (
            self.expire_seconds
            if purge_after_seconds is None
            else max(60.0, float(purge_after_seconds))
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS result_unknown (
                    request_id TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    session_type TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    capability_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    resolved_at REAL,
                    PRIMARY KEY (request_id, created_at)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_result_unknown_status_created
                ON result_unknown (status, created_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def record(
        self,
        *,
        request_id: str,
        adapter: str,
        bot_id: str,
        session_type: str = "",
        session_id: str = "",
        capability_id: str = "",
    ) -> bool:
        """记录一次 result-unknown；重复 request_id 不重复记。"""
        if not request_id or not adapter:
            return False
        with self._lock:
            with closing(self._connect()) as connection, connection:
                existing = connection.execute(
                    "SELECT 1 FROM result_unknown WHERE request_id = ? LIMIT 1",
                    (request_id,),
                ).fetchone()
                if existing is not None:
                    return False
                connection.execute(
                    """
                    INSERT INTO result_unknown
                        (request_id, adapter, bot_id, session_type, session_id, capability_id, created_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        request_id,
                        adapter,
                        bot_id,
                        session_type,
                        session_id,
                        capability_id,
                        float(self._clock()),
                    ),
                )
            return True

    def reconcile(self, *, bot_id: str | None = None) -> ReconcileSummary:
        """重连对账：过期标记 expired，返回仍 pending 的摘要。

        顺带执行 TTL 清理：删除已过期超过 ``purge_after_seconds`` 的行，
        台账不会随历史对账无上限增长（pending 行永不清理）。
        """
        now = float(self._clock())
        cutoff = now - self.expire_seconds
        purge_cutoff = now - self.purge_after_seconds
        by_bot: dict[str, int] = {}
        pending = 0
        expired = 0
        purged = 0
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                    UPDATE result_unknown SET status = 'expired', resolved_at = ?
                    WHERE status = 'pending' AND created_at < ?
                    """,
                (now, cutoff),
            )
            expired = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            purged = connection.execute(
                """
                    DELETE FROM result_unknown
                    WHERE status = 'expired'
                      AND COALESCE(resolved_at, created_at) <= ?
                    """,
                (purge_cutoff,),
            ).rowcount
            purged = purged if purged and purged > 0 else 0
            rows = connection.execute(
                """
                    SELECT bot_id, COUNT(*) AS n FROM result_unknown
                    WHERE status = 'pending'
                    GROUP BY bot_id
                    """
            ).fetchall()
            for row in rows:
                count = int(row["n"])
                by_bot[str(row["bot_id"])] = count
                pending += count
        return ReconcileSummary(
            pending=pending, expired=expired, by_bot=by_bot, purged=purged
        )

    def purge_expired(self, *, now: float | None = None) -> int:
        """手动 TTL 清理：删除过期超过 ``purge_after_seconds`` 的行，返回删除数。"""
        moment = float(self._clock() if now is None else now)
        purge_cutoff = moment - self.purge_after_seconds
        with self._lock, closing(self._connect()) as connection, connection:
            removed = connection.execute(
                """
                    DELETE FROM result_unknown
                    WHERE status = 'expired'
                      AND COALESCE(resolved_at, created_at) <= ?
                    """,
                (purge_cutoff,),
            ).rowcount
        return removed if removed and removed > 0 else 0

    def pending_count(self) -> int:
        with self._lock, closing(self._connect()) as connection, connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM result_unknown WHERE status = 'pending'"
                ).fetchone()[0]
            )

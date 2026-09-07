"""入站事件幂等表（交接 P0.4：同事件重复投递去重）。

OneBot/NapCat 断线重连可能重放同一事件；同一 (adapter, bot_id, message_id)
被同一能力处理两次会造成重复回复。提供两种后端，同一 claim 接口：
- EventIdempotencyTable：进程内 TTL 去重，重启即失效；
- SqliteEventIdempotencyTable：SQLite 持久化，跨重启仍拦截重放事件。

共同语义：
- 键 = adapter | bot_id | message_id（无 message_id 的事件不做去重，避免误伤）；
- 同一键对同一 capability_id 只放行一次；不同能力互不影响（多 matcher 合法共存）；
- TTL 过期与容量上限自动回收。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any


def build_event_dedupe_key(message: Any) -> str:
    """构造事件去重键；缺少稳定 message_id 时返回空串（调用方跳过去重）。"""
    message_id = str(getattr(message, "message_id", "") or "").strip()
    if not message_id:
        return ""
    adapter = str(getattr(message, "adapter", "") or "").strip().lower()
    bot_id = str(getattr(message, "bot_id", "") or "").strip()
    return f"{adapter}|{bot_id}|{message_id}"


class EventIdempotencyTable:
    """进程内 TTL 幂等表：claim() 返回 True 表示首次出现（放行处理）。"""

    def __init__(
        self,
        *,
        ttl_seconds: float = 3600.0,
        max_entries: int = 4096,
        clock: Any = time.monotonic,
    ) -> None:
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._clock = clock
        self._lock = threading.Lock()
        # key -> (capability_id, last_seen_monotonic)
        self._entries: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def claim(self, key: str, *, capability_id: str) -> bool:
        if not key:
            return True
        now = float(self._clock())
        with self._lock:
            self._evict_expired(now)
            previous = self._entries.get(key)
            if previous is not None and previous[0] == capability_id:
                # 重复事件：刷新时间戳并拒绝。
                self._entries.move_to_end(key)
                self._entries[key] = (previous[0], now)
                return False
            self._entries[key] = (capability_id, now)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return True

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self.ttl_seconds
        while self._entries:
            _, (_, seen_at) = next(iter(self._entries.items()))
            if seen_at >= cutoff:
                break
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            self._evict_expired(float(self._clock()))
            return len(self._entries)


class SqliteEventIdempotencyTable:
    """SQLite 持久化幂等表：与 EventIdempotencyTable 同接口，跨重启拦截重放。

    时间戳用 wall clock（time.time()）存储，重启后 TTL 判定仍然成立；
    写路径串行化在本进程锁内，跨进程依赖 SQLite 自身文件锁兜底。
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        ttl_seconds: float = 3600.0,
        max_entries: int = 4096,
        clock: Any = time.time,
    ) -> None:
        self.db_path = Path(db_path)
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._clock = clock
        self._lock = threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS event_idempotency (
                    event_key TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    claimed_at_unix REAL NOT NULL,
                    PRIMARY KEY (event_key, capability_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_idempotency_claimed_at
                ON event_idempotency (claimed_at_unix)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        return connection

    def claim(self, key: str, *, capability_id: str) -> bool:
        if not key:
            return True
        now = float(self._clock())
        cutoff = now - self.ttl_seconds
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM event_idempotency WHERE claimed_at_unix < ?",
                    (cutoff,),
                )
                existing = connection.execute(
                    """
                    SELECT 1 FROM event_idempotency
                    WHERE event_key = ? AND capability_id = ?
                    """,
                    (key, capability_id),
                ).fetchone()
                if existing is not None:
                    # 重复事件：刷新时间戳并拒绝。
                    connection.execute(
                        """
                        UPDATE event_idempotency SET claimed_at_unix = ?
                        WHERE event_key = ? AND capability_id = ?
                        """,
                        (now, key, capability_id),
                    )
                    return False
                connection.execute(
                    """
                    INSERT INTO event_idempotency
                        (event_key, capability_id, claimed_at_unix)
                    VALUES (?, ?, ?)
                    """,
                    (key, capability_id, now),
                )
                self._prune(connection, cutoff)
            return True

    def _prune(self, connection: sqlite3.Connection, cutoff: float) -> None:
        connection.execute(
            "DELETE FROM event_idempotency WHERE claimed_at_unix < ?",
            (cutoff,),
        )
        overflow = connection.execute(
            "SELECT COUNT(*) FROM event_idempotency"
        ).fetchone()[0] - self.max_entries
        if overflow > 0:
            connection.execute(
                """
                DELETE FROM event_idempotency WHERE rowid IN (
                    SELECT rowid FROM event_idempotency
                    ORDER BY claimed_at_unix ASC, rowid ASC LIMIT ?
                )
                """,
                (overflow,),
            )

    def __len__(self) -> int:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM event_idempotency WHERE claimed_at_unix < ?",
                    (float(self._clock()) - self.ttl_seconds,),
                )
                count = connection.execute(
                    "SELECT COUNT(*) FROM event_idempotency"
                ).fetchone()[0]
            return int(count)


def build_event_idempotency_table(
    *,
    enabled: bool,
    db_path: str | Path | None,
    ttl_seconds: float,
    max_entries: int,
) -> EventIdempotencyTable | SqliteEventIdempotencyTable | None:
    """按配置选择后端：disabled=None；db_path 非空→SQLite；否则进程内。"""
    if not enabled:
        return None
    if db_path and str(db_path).strip():
        return SqliteEventIdempotencyTable(
            db_path,
            ttl_seconds=ttl_seconds,
            max_entries=max_entries,
        )
    return EventIdempotencyTable(ttl_seconds=ttl_seconds, max_entries=max_entries)

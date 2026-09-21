"""结构化运行事件；无默认 Runtime 路径、日志采集器或进程级单例。

装配方显式创建 RuntimeEventService(path)，然后 RuntimeEventBus(service).start()；
关闭时 bus.close(timeout=...) 排空队列，False 表示 writer 仍在退出，需再次等待。
service 每次操作独立开关连接，无额外 close。publish 返回 False 必须视为未接收。

方案状态：这是结构化诊断事件层，不是已接入真实日志正文的控制台。
隐私边界：message 只输出分类固定摘要，绝不保存调用方自由文本；details 为递归
白名单标量（仅操作标识、状态、计数/耗时），不是 prompt、聊天记录或异常栈容器。
summary 仅接受结构字典，内部沿用同一白名单；自由文本摘要一律丢弃。
调用方仍须保证 *_id 是操作标识，不把用户正文编码后冒充标识。
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any
from uuid import UUID, uuid4

from plugins.bot_unified_runtime.domains.ops.audit.logger import redact_private_debug
from plugins.bot_unified_runtime.output.plain_text import redact_local_secrets

EVENT_CATEGORIES = (
    "debug",
    "info",
    "warning",
    "error",
    "success",
    "critical",
    "detail",
)
EVENT_SOURCES = (
    "bot",
    "nonebot",
    "napcat",
    "telegram",
    "mail",
    "control_plane",
    "decision_engine",
    "pipeline",
    "sender",
    "llm",
    "database",
    "scheduler",
    "capability",
    "renderer",
)
_MESSAGES = dict(
    zip(
        EVENT_CATEGORIES,
        (
            "调试事件",
            "运行信息",
            "运行警告",
            "操作失败",
            "操作成功",
            "严重异常",
            "运行详情",
        ),
        strict=True,
    )
)
_ID_KEYS = frozenset(
    {
        "request_id",
        "trace_id",
        "session_id",
        "capability_id",
        "model_id",
        "status",
        "error_code",
    }
)
_NUMBER_KEYS = frozenset(
    {
        "latency",
        "latency_ms",
        "duration_ms",
        "retry_count",
        "http_status",
        "token_count",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "queue_depth",
    }
)
DETAIL_KEYS = _ID_KEYS | _NUMBER_KEYS | {"summary"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}\Z")
_MAX_CURSOR = 2**63 - 1


def _redact(text: str) -> str:
    # Fail closed: the older DTO helper deliberately falls back to raw text.
    try:
        return redact_local_secrets(redact_private_debug(text[:2048]))
    except (RuntimeError, TypeError, ValueError, LookupError, AttributeError):
        return ""


def _safe_details(details: Any) -> dict[str, Any]:
    budget = 128

    def clean(value: Any, key: str = "", depth: int = 0) -> Any:
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > 4:
            return None
        if key == "summary" and type(value) is not dict:
            return None
        if type(value) is dict:
            result = {}
            # Only examine known keys; unknown/credentials/cookie/authorization
            # branches are discarded wholesale at EVERY depth, including lists.
            for name in sorted(DETAIL_KEYS):
                if name in value:
                    safe = clean(value[name], name, depth + 1)
                    if safe is not None:
                        result[name] = safe
            return result or None
        if type(value) is list:
            items = [clean(item, key, depth + 1) for item in value[:16]]
            return [item for item in items if item is not None] or None
        if key in _NUMBER_KEYS:
            if (
                type(value) in (int, float)
                and 0 <= value <= 10**15
                and math.isfinite(value)
            ):
                if key.endswith(("count", "tokens")) or key in {
                    "http_status",
                    "queue_depth",
                }:
                    return value if type(value) is int else None
                return value
            return None
        if key in _ID_KEYS and type(value) is str and len(value) <= 128:
            safe = _redact(value)
            # Drop rather than partially keep redacted identifiers. No paths,
            # SQL fragments, free text, newlines or rendered user bodies.
            return safe if safe == value and _IDENTIFIER.fullmatch(safe) else None
        return None

    if type(details) is not dict:
        return {}
    return clean(details) or {}


def _integer(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


@dataclass(frozen=True)
class RuntimeLogEvent:
    source: str
    category: str
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    cursor: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        )
    )

    def __post_init__(self) -> None:
        if self.source not in EVENT_SOURCES or self.category not in EVENT_CATEGORIES:
            raise ValueError("Invalid event classification")
        try:
            if (
                not isinstance(self.event_id, str)
                or UUID(self.event_id).hex != self.event_id
            ):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError("Invalid event identifier") from None
        if not _integer(self.cursor, 0, _MAX_CURSOR):
            raise ValueError("Invalid event cursor")
        try:
            stamp = datetime.fromisoformat(self.created_at)
            if stamp.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("Invalid event timestamp") from None
        object.__setattr__(
            self,
            "created_at",
            stamp.astimezone(timezone.utc).isoformat(timespec="milliseconds"),
        )
        _redact(self.message if type(self.message) is str else "")
        object.__setattr__(self, "message", _MESSAGES[self.category])
        object.__setattr__(self, "details", _safe_details(self.details))

    def to_dict(self) -> dict[str, Any]:
        # A fresh projection also prevents mutating nested details via query DTOs.
        return {
            "cursor": self.cursor,
            "event_id": self.event_id,
            "created_at": self.created_at,
            "source": self.source,
            "category": self.category,
            "message": _MESSAGES[self.category],
            "details": _safe_details(self.details),
        }


class CursorExpired(ValueError):
    def __init__(self, oldest_cursor: int) -> None:
        super().__init__("Requested cursor is outside the retained event window")
        self.oldest_cursor = oldest_cursor


class EventStoreUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Event storage is unavailable")


class RuntimeEventService:
    """Ascending cursor/keyset pages with global retention-gap detection.

    after=None explicitly means start at the oldest AVAILABLE event. Explicit
    after=N means replay everything after N, or fail; filters never hide a gap.
    Retention is count-based. Constructor/append/query are synchronous; keep them
    off the ASGI event loop. No db_path/SQL is accepted from HTTP parameters.
    """

    def __init__(self, db_path: str | Path, *, max_events: int = 10000) -> None:
        if not _integer(max_events, 1, 1000000):
            raise ValueError("Invalid retention bound")
        self.db_path = Path(db_path)
        self.max_events = max_events
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runtime_log_events (
                    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runtime_events_source_cursor ON runtime_log_events(source, cursor);
                CREATE INDEX IF NOT EXISTS runtime_events_category_cursor ON runtime_log_events(category, cursor);
                CREATE TABLE IF NOT EXISTS runtime_event_watermark (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    pruned_through INTEGER NOT NULL, high_cursor INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO runtime_event_watermark VALUES (1, 0, 0);
            """)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(sqlite3.connect(str(self.db_path), timeout=1.0)) as connection:
                connection.row_factory = sqlite3.Row
                with connection:
                    yield connection
        except (sqlite3.Error, OSError):
            raise EventStoreUnavailable() from None

    @staticmethod
    def _event(row: sqlite3.Row) -> RuntimeLogEvent:
        return RuntimeLogEvent(**{**dict(row), "details": json.loads(row["details"])})

    def append(self, event: RuntimeLogEvent) -> RuntimeLogEvent:
        safe = RuntimeLogEvent(**event.to_dict())
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO runtime_log_events(event_id, created_at, source, category, message, details) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    safe.event_id,
                    safe.created_at,
                    safe.source,
                    safe.category,
                    safe.message,
                    json.dumps(
                        safe.details,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    ),
                ),
            )
            row = connection.execute(
                "SELECT * FROM runtime_log_events WHERE event_id=?", (safe.event_id,)
            ).fetchone()
            connection.execute(
                "UPDATE runtime_event_watermark SET high_cursor=MAX(high_cursor, ?) WHERE singleton=1",
                (row["cursor"],),
            )
            cutoff = connection.execute(
                "SELECT cursor FROM runtime_log_events ORDER BY cursor DESC LIMIT 1 OFFSET ?",
                (self.max_events,),
            ).fetchone()
            if cutoff:
                connection.execute(
                    "DELETE FROM runtime_log_events WHERE cursor<=?",
                    (cutoff["cursor"],),
                )
                connection.execute(
                    "UPDATE runtime_event_watermark SET pruned_through=MAX(pruned_through, ?) WHERE singleton=1",
                    (cutoff["cursor"],),
                )
            return self._event(row)

    def query(
        self,
        *,
        after: int | None = None,
        limit: int = 50,
        source: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        if not _integer(limit, 1, 500) or (
            after is not None and not _integer(after, 0, _MAX_CURSOR)
        ):
            raise ValueError("Invalid pagination")
        if (source is not None and source not in EVENT_SOURCES) or (
            category is not None and category not in EVENT_CATEGORIES
        ):
            raise ValueError("Invalid event filter")
        with self._connection() as connection:
            # Watermark check and page must see the SAME snapshot while writer prunes.
            connection.execute("BEGIN")
            bounds = connection.execute(
                "SELECT * FROM runtime_event_watermark WHERE singleton=1"
            ).fetchone()
            floor, high = bounds["pruned_through"], bounds["high_cursor"]
            if after is not None and after < floor:
                oldest = connection.execute(
                    "SELECT MIN(cursor) FROM runtime_log_events"
                ).fetchone()[0]
                raise CursorExpired(oldest or high + 1)
            if after is not None and after > high:
                raise ValueError("Cursor is ahead of this event store")
            conditions = ["cursor>?"]
            params: list[Any] = [floor if after is None else after]
            for column, value in (("source", source), ("category", category)):
                if value is not None:
                    conditions.append(f"{column}=?")
                    params.append(value)
            rows = connection.execute(
                "SELECT * FROM runtime_log_events WHERE "
                + " AND ".join(conditions)
                + " ORDER BY cursor LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            items = [self._event(row).to_dict() for row in rows[:limit]]
            more = len(rows) > limit
            # Once this snapshot is exhausted, advance past nonmatching rows too.
            return {
                "items": items,
                "next_cursor": items[-1]["cursor"] if more else high,
                "has_more": more,
                "high_cursor": high,
            }

    def get(self, event_id: str) -> dict[str, Any] | None:
        if not isinstance(event_id, str) or not _IDENTIFIER.fullmatch(event_id):
            raise ValueError("Invalid event identifier")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_log_events WHERE event_id=?", (event_id,)
            ).fetchone()
            return self._event(row).to_dict() if row else None


class RuntimeEventBus:
    """Bounded MPSC ingress; no SQLite or writer locks on the publish path.

    Queue overflow and rejected lifecycle calls return False. A write failure is
    counted, not retried indefinitely; accepted means queued, NOT durable. This
    is a best-effort diagnostic bus, not a transactional business-event outbox.
    """

    def __init__(self, service: RuntimeEventService, *, capacity: int = 1024) -> None:
        if not _integer(capacity, 1, 65536):
            raise ValueError("Invalid queue capacity")
        self.service = service
        self._queue: Queue[RuntimeLogEvent] = Queue(maxsize=capacity)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._accepting = False
        self.dropped_count = 0
        self.rejected_count = 0
        self.written_count = 0
        self.write_error_count = 0

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("A closed event bus cannot restart")
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._write, name="runtime-event-writer", daemon=True
            )
            self._thread.start()
            self._accepting = True

    def publish(self, event: RuntimeLogEvent) -> bool:
        # Never wait behind start/close or another publisher. Rejected lifecycle
        # contention is counted separately from a full queue.
        if not self._lock.acquire(blocking=False):
            self.rejected_count += 1
            return False
        try:
            if not self._accepting:
                self.rejected_count += 1
                return False
            try:
                # Detach mutable details, redact again BEFORE entering the queue.
                self._queue.put_nowait(RuntimeLogEvent(**event.to_dict()))
                return True
            except Full:
                self.dropped_count += 1
                return False
        finally:
            self._lock.release()

    def _write(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                event = self._queue.get(timeout=0.05)
            except Empty:
                continue
            try:
                self.service.append(event)
                self.written_count += 1
            except (RuntimeError, sqlite3.Error, OSError, ValueError, TypeError):
                # Never log raw exceptions, paths, SQL or original payloads.
                self.write_error_count += 1
            finally:
                self._queue.task_done()

    def close(self, timeout: float = 5.0) -> bool:
        if (
            not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout < 0
        ):
            raise ValueError("Invalid shutdown timeout")
        with self._lock:
            self._accepting = False
            self._stop.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return not self.is_running

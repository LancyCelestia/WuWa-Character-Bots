from __future__ import annotations

import sqlite3
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Protocol

from pydantic import Field, field_validator

from plugins.bot_unified_runtime.contracts import IncomingMessage
from plugins.bot_unified_runtime.contracts.runtime import StrictBaseModel, new_debug_id

CHAT_CAPABILITY_IDS = {"bot.chat"}
DEFAULT_BYPASS_ROLES = ["admin"]


class RateLimitDecision(StrictBaseModel):
    allowed: bool
    reason: str = "allowed"
    retry_after_seconds: int = 0
    audit_tags: list[str] = Field(default_factory=lambda: ["rate_limit:ok"])
    debug_id: str = Field(default_factory=new_debug_id)


class RateLimitSettings(StrictBaseModel):
    enabled: bool = True
    window_seconds: int = 60
    chat_global_max_requests: int = 60
    chat_session_max_requests: int = 6
    chat_sender_max_requests: int = 4
    target_min_interval_seconds: int = 0
    proactive_window_seconds: int = 3600
    proactive_group_max_replies: int = 6
    proactive_group_cooldown_seconds: int = 90
    bypass_roles: list[str] = Field(default_factory=lambda: list(DEFAULT_BYPASS_ROLES))

    @field_validator("window_seconds")
    @classmethod
    def require_positive_window(cls, value: int) -> int:
        if value < 1:
            raise ValueError("rate limit window must be at least 1 second")
        return value

    @field_validator(
        "chat_global_max_requests",
        "chat_session_max_requests",
        "chat_sender_max_requests",
    )
    @classmethod
    def require_positive_limits(cls, value: int) -> int:
        if value < 1:
            raise ValueError("rate limit request caps must be at least 1")
        return value

    @field_validator("target_min_interval_seconds", "proactive_window_seconds", "proactive_group_cooldown_seconds")
    @classmethod
    def require_non_negative_interval(cls, value: int) -> int:
        if value < 0:
            raise ValueError("target min interval must not be negative")
        return value

    @field_validator("proactive_group_max_replies")
    @classmethod
    def require_positive_proactive_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("proactive group reply cap must be at least 1")
        return value

    @field_validator("bypass_roles")
    @classmethod
    def normalize_bypass_roles(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values if value.strip()]
        return list(dict.fromkeys(normalized))


class RateLimiter(Protocol):
    def check_and_record(
        self,
        message: IncomingMessage,
        capability_id: str,
        *,
        amount: int = 1,
        interactive: bool = False,
        proactive: bool = False,
    ) -> RateLimitDecision:
        raise NotImplementedError


class InMemoryRateLimiter:
    # 桶清扫间隔：只访问被命中的桶会让未再命中的桶永久滞留（键集合无界增长）。
    _SWEEP_INTERVAL_SECONDS = 600.0

    def __init__(
        self,
        settings: RateLimitSettings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or RateLimitSettings()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._buckets: dict[str, deque[datetime]] = defaultdict(deque)
        self._last_sweep = time.monotonic()

    def _maybe_sweep(self, now: datetime) -> None:
        """低频清扫空/过期桶，防止长期运行下键集合无界增长。"""
        if time.monotonic() - self._last_sweep < self._SWEEP_INTERVAL_SECONDS:
            return
        self._last_sweep = time.monotonic()
        horizon = max(
            self.settings.window_seconds,
            self.settings.target_min_interval_seconds,
            self.settings.proactive_window_seconds,
        )
        for key in list(self._buckets.keys()):
            bucket = self._buckets.get(key)  # .get 不触发 defaultdict 建桶
            if bucket is None:
                continue
            while bucket and (now - bucket[0]).total_seconds() >= horizon:
                bucket.popleft()
            if not bucket:
                del self._buckets[key]

    def check_and_record(
        self,
        message: IncomingMessage,
        capability_id: str,
        *,
        amount: int = 1,
        interactive: bool = False,
        proactive: bool = False,
    ) -> RateLimitDecision:
        if proactive:
            return self._check_proactive(message, capability_id)
        if interactive:
            return RateLimitDecision(
                allowed=True,
                reason="interactive_bypass",
                audit_tags=["rate_limit:interactive_bypass"],
            )
        safe_amount = max(1, int(amount))
        if not self.settings.enabled:
            return RateLimitDecision(
                allowed=True,
                reason="disabled",
                audit_tags=["rate_limit:disabled"],
            )
        if capability_id not in CHAT_CAPABILITY_IDS:
            return RateLimitDecision(
                allowed=True,
                reason="non_chat_capability",
                audit_tags=["rate_limit:non_chat"],
            )
        if self._has_bypass_role(message):
            return RateLimitDecision(
                allowed=True,
                reason="role_bypass",
                audit_tags=["rate_limit:bypass_role"],
            )

        now = self.clock()
        self._maybe_sweep(now)
        target_key = self._target_bucket_key(capability_id, message)
        if self.settings.target_min_interval_seconds > 0:
            target_bucket = self._buckets[target_key]
            self._prune_for_interval(target_bucket, now)
            if target_bucket:
                return RateLimitDecision(
                    allowed=False,
                    reason="target_min_interval",
                    retry_after_seconds=self._target_retry_after_seconds(
                        target_bucket,
                        now,
                    ),
                    audit_tags=[
                        "rate_limit:blocked",
                        "rate_limit:target_min_interval",
                    ],
                )

        scoped_buckets = [
            (
                "global",
                self._bucket_key(capability_id, "global", "all"),
                self.settings.chat_global_max_requests,
            ),
            (
                "session",
                self._bucket_key(capability_id, "session", message.session_id),
                self.settings.chat_session_max_requests,
            ),
            (
                "sender",
                self._bucket_key(capability_id, "sender", message.sender_id),
                self.settings.chat_sender_max_requests,
            ),
        ]
        for _scope, key, _limit in scoped_buckets:
            self._prune(self._buckets[key], now)

        for scope, key, limit in scoped_buckets:
            bucket = self._buckets[key]
            if len(bucket) + safe_amount > limit:
                return RateLimitDecision(
                    allowed=False,
                    reason=f"{scope}_window_exceeded",
                    retry_after_seconds=self._retry_after_seconds(bucket, now),
                    audit_tags=[
                        "rate_limit:blocked",
                        f"rate_limit:{scope}_window_exceeded",
                    ],
                )

        for _scope, key, _limit in scoped_buckets:
            bucket = self._buckets[key]
            for _ in range(safe_amount):
                bucket.append(now)
        if self.settings.target_min_interval_seconds > 0:
            self._buckets[target_key].append(now)

        return RateLimitDecision(
            allowed=True,
            reason="allowed",
            audit_tags=["rate_limit:ok"],
        )

    def _check_proactive(self, message: IncomingMessage, capability_id: str) -> RateLimitDecision:
        if not self.settings.enabled:
            return RateLimitDecision(
                allowed=True,
                reason="disabled",
                audit_tags=["rate_limit:disabled"],
            )
        now = self.clock()
        self._maybe_sweep(now)
        key = self._bucket_key(
            capability_id,
            "proactive_group",
            message.group_id or message.session_id,
        )
        bucket = self._buckets[key]
        window = max(1, self.settings.proactive_window_seconds)
        while bucket and (now - bucket[0]).total_seconds() >= window:
            bucket.popleft()
        if bucket and self.settings.proactive_group_cooldown_seconds > 0:
            elapsed = (now - bucket[-1]).total_seconds()
            if elapsed < self.settings.proactive_group_cooldown_seconds:
                return RateLimitDecision(
                    allowed=False,
                    reason="proactive_cooldown",
                    retry_after_seconds=max(
                        1,
                        int(self.settings.proactive_group_cooldown_seconds - elapsed),
                    ),
                    audit_tags=[
                        "rate_limit:proactive_blocked",
                        "rate_limit:proactive_cooldown",
                    ],
                )
        if len(bucket) >= self.settings.proactive_group_max_replies:
            return RateLimitDecision(
                allowed=False,
                reason="proactive_window_exceeded",
                retry_after_seconds=window,
                audit_tags=[
                    "rate_limit:proactive_blocked",
                    "rate_limit:proactive_window_exceeded",
                ],
            )
        bucket.append(now)
        return RateLimitDecision(
            allowed=True,
            reason="proactive_allowed",
            audit_tags=["rate_limit:proactive_allowed"],
        )

    def _has_bypass_role(self, message: IncomingMessage) -> bool:
        bypass_roles = set(self.settings.bypass_roles)
        return any(role.strip().lower() in bypass_roles for role in message.sender_roles)

    def _prune(self, bucket: deque[datetime], now: datetime) -> None:
        cutoff_seconds = self.settings.window_seconds
        while bucket and (now - bucket[0]).total_seconds() >= cutoff_seconds:
            bucket.popleft()

    def _retry_after_seconds(self, bucket: deque[datetime], now: datetime) -> int:
        if not bucket:
            return self.settings.window_seconds
        elapsed = int((now - bucket[0]).total_seconds())
        return max(1, self.settings.window_seconds - elapsed)

    def _prune_for_interval(self, bucket: deque[datetime], now: datetime) -> None:
        cutoff_seconds = self.settings.target_min_interval_seconds
        while bucket and (now - bucket[0]).total_seconds() >= cutoff_seconds:
            bucket.popleft()

    def _target_retry_after_seconds(self, bucket: deque[datetime], now: datetime) -> int:
        if not bucket:
            return self.settings.target_min_interval_seconds
        elapsed = int((now - bucket[-1]).total_seconds())
        return max(1, self.settings.target_min_interval_seconds - elapsed)

    @staticmethod
    def _bucket_key(capability_id: str, scope: str, value: str) -> str:
        return f"{capability_id}:{scope}:{value}"

    @classmethod
    def _target_bucket_key(cls, capability_id: str, message: IncomingMessage) -> str:
        target = message.group_id or message.sender_id or message.session_id
        return cls._bucket_key(capability_id, "target", target)


class SQLiteRateLimiter:
    # 建表 DDL 一次即可：此前每次 check 都跑 2 条 DDL + 新建连接。
    # 键为 resolve 后的 db 路径，多实例共享同一库时不重复建表。
    _schema_ready_paths: ClassVar[set[str]] = set()
    _SCHEMA_LOCK = threading.Lock()
    # 全表过期清理间隔（低频）：逐桶 prune 只清理被访问的键，
    # 不被访问的键会永久滞留并拖慢 COUNT/DELETE。
    _CLEANUP_INTERVAL_SECONDS = 300.0

    def __init__(
        self,
        db_path: str | Path,
        settings: RateLimitSettings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.settings = settings or RateLimitSettings()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        # APScheduler 线程与事件循环并发调用 check：进程内锁串行化，
        # 跨进程并发由 SQLite 文件锁 + busy_timeout 兜底，避免
        # "database is locked" 直接变成用户可见失败。
        self._lock = threading.Lock()
        self._last_cleanup = 0.0

    def check_and_record(
        self,
        message: IncomingMessage,
        capability_id: str,
        *,
        amount: int = 1,
        interactive: bool = False,
        proactive: bool = False,
    ) -> RateLimitDecision:
        if proactive:
            return self._check_proactive(message, capability_id)
        if interactive:
            return RateLimitDecision(
                allowed=True,
                reason="interactive_bypass",
                audit_tags=["rate_limit:interactive_bypass"],
            )
        safe_amount = max(1, int(amount))
        if not self.settings.enabled:
            return RateLimitDecision(
                allowed=True,
                reason="disabled",
                audit_tags=["rate_limit:disabled"],
            )
        if capability_id not in CHAT_CAPABILITY_IDS:
            return RateLimitDecision(
                allowed=True,
                reason="non_chat_capability",
                audit_tags=["rate_limit:non_chat"],
            )
        if self._has_bypass_role(message):
            return RateLimitDecision(
                allowed=True,
                reason="role_bypass",
                audit_tags=["rate_limit:bypass_role"],
            )

        with self._lock:
            return self._check_and_record_locked(
                message, capability_id, safe_amount
            )

    def _check_and_record_locked(
        self,
        message: IncomingMessage,
        capability_id: str,
        safe_amount: int,
    ) -> RateLimitDecision:
        self._ensure_schema()
        now = self.clock()
        now_epoch = now.timestamp()
        cutoff_epoch = now_epoch - self.settings.window_seconds
        target_key = self._target_bucket_key(capability_id, message)
        target_cutoff_epoch = now_epoch - self.settings.target_min_interval_seconds
        scoped_buckets = [
            (
                "global",
                self._bucket_key(capability_id, "global", "all"),
                self.settings.chat_global_max_requests,
            ),
            (
                "session",
                self._bucket_key(capability_id, "session", message.session_id),
                self.settings.chat_session_max_requests,
            ),
            (
                "sender",
                self._bucket_key(capability_id, "sender", message.sender_id),
                self.settings.chat_sender_max_requests,
            ),
        ]
        with closing(self._connect()) as connection, connection:
            self._cleanup_expired(connection, now_epoch)
            for _scope, key, _limit in scoped_buckets:
                self._prune(connection, key, cutoff_epoch)
            if self.settings.target_min_interval_seconds > 0:
                self._prune(connection, target_key, target_cutoff_epoch)
                latest_target_event = self._latest_created_at(connection, target_key)
                if latest_target_event is not None:
                    return RateLimitDecision(
                        allowed=False,
                        reason="target_min_interval",
                        retry_after_seconds=self._target_retry_after_seconds_from_epoch(
                            latest_target_event,
                            now_epoch,
                        ),
                        audit_tags=[
                            "rate_limit:blocked",
                            "rate_limit:target_min_interval",
                        ],
                    )

            for scope, key, limit in scoped_buckets:
                count = self._count(connection, key)
                if count + safe_amount > limit:
                    return RateLimitDecision(
                        allowed=False,
                        reason=f"{scope}_window_exceeded",
                        retry_after_seconds=self._retry_after_seconds(
                            connection,
                            key,
                            now_epoch,
                        ),
                        audit_tags=[
                            "rate_limit:blocked",
                            f"rate_limit:{scope}_window_exceeded",
                        ],
                    )

            for _scope, key, _limit in scoped_buckets:
                connection.executemany(
                    """
                    INSERT INTO rate_limit_events (bucket_key, created_at)
                    VALUES (?, ?)
                    """,
                    [(key, now_epoch) for _ in range(safe_amount)],
                )
            if self.settings.target_min_interval_seconds > 0:
                connection.execute(
                    """
                    INSERT INTO rate_limit_events (bucket_key, created_at)
                    VALUES (?, ?)
                    """,
                    (target_key, now_epoch),
                )

        return RateLimitDecision(
            allowed=True,
            reason="allowed",
            audit_tags=["rate_limit:ok"],
        )

    def _check_proactive(self, message: IncomingMessage, capability_id: str) -> RateLimitDecision:
        if not self.settings.enabled:
            return RateLimitDecision(
                allowed=True,
                reason="disabled",
                audit_tags=["rate_limit:disabled"],
            )
        with self._lock:
            self._ensure_schema()
            now_epoch = self.clock().timestamp()
            key = self._bucket_key(
                capability_id,
                "proactive_group",
                message.group_id or message.session_id,
            )
            cutoff = now_epoch - max(1, self.settings.proactive_window_seconds)
            with closing(self._connect()) as connection, connection:
                self._cleanup_expired(connection, now_epoch)
                self._prune(connection, key, cutoff)
                count = self._count(connection, key)
                latest = self._latest_created_at(connection, key)
                if latest is not None and self.settings.proactive_group_cooldown_seconds > 0:
                    elapsed = now_epoch - latest
                    if elapsed < self.settings.proactive_group_cooldown_seconds:
                        return RateLimitDecision(
                            allowed=False,
                            reason="proactive_cooldown",
                            retry_after_seconds=max(
                                1,
                                int(self.settings.proactive_group_cooldown_seconds - elapsed),
                            ),
                            audit_tags=[
                                "rate_limit:proactive_blocked",
                                "rate_limit:proactive_cooldown",
                            ],
                        )
                if count >= self.settings.proactive_group_max_replies:
                    return RateLimitDecision(
                        allowed=False,
                        reason="proactive_window_exceeded",
                        retry_after_seconds=max(1, self.settings.proactive_window_seconds),
                        audit_tags=[
                            "rate_limit:proactive_blocked",
                            "rate_limit:proactive_window_exceeded",
                        ],
                    )
                connection.execute(
                    "INSERT INTO rate_limit_events (bucket_key, created_at) VALUES (?, ?)",
                    (key, now_epoch),
                )
        return RateLimitDecision(
            allowed=True,
            reason="proactive_allowed",
            audit_tags=["rate_limit:proactive_allowed"],
        )

    def _has_bypass_role(self, message: IncomingMessage) -> bool:
        bypass_roles = set(self.settings.bypass_roles)
        return any(role.strip().lower() in bypass_roles for role in message.sender_roles)

    def _ensure_schema(self) -> None:
        try:
            schema_key = str(self.db_path.resolve())
        except OSError:
            schema_key = str(self.db_path)
        if schema_key in SQLiteRateLimiter._schema_ready_paths:
            return
        with SQLiteRateLimiter._SCHEMA_LOCK:
            if schema_key in SQLiteRateLimiter._schema_ready_paths:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rate_limit_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bucket_key TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_rate_limit_events_bucket_time
                    ON rate_limit_events (bucket_key, created_at)
                    """
                )
            SQLiteRateLimiter._schema_ready_paths.add(schema_key)

    def _cleanup_expired(
        self,
        connection: sqlite3.Connection,
        now_epoch: float,
    ) -> None:
        """低频全表过期清理：删除超过所有限制窗口的旧事件行。"""
        if time.monotonic() - self._last_cleanup < self._CLEANUP_INTERVAL_SECONDS:
            return
        self._last_cleanup = time.monotonic()
        horizon = max(
            self.settings.window_seconds,
            self.settings.target_min_interval_seconds,
            self.settings.proactive_window_seconds,
        )
        connection.execute(
            "DELETE FROM rate_limit_events WHERE created_at < ?",
            (now_epoch - horizon - 1.0,),
        )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=5.0)

    def _prune(
        self,
        connection: sqlite3.Connection,
        bucket_key: str,
        cutoff_epoch: float,
    ) -> None:
        connection.execute(
            """
            DELETE FROM rate_limit_events
            WHERE bucket_key = ? AND created_at <= ?
            """,
            (bucket_key, cutoff_epoch),
        )

    def _count(self, connection: sqlite3.Connection, bucket_key: str) -> int:
        cursor = connection.execute(
            """
            SELECT COUNT(*)
            FROM rate_limit_events
            WHERE bucket_key = ?
            """,
            (bucket_key,),
        )
        value = cursor.fetchone()[0]
        return int(value)

    def _retry_after_seconds(
        self,
        connection: sqlite3.Connection,
        bucket_key: str,
        now_epoch: float,
    ) -> int:
        cursor = connection.execute(
            """
            SELECT MIN(created_at)
            FROM rate_limit_events
            WHERE bucket_key = ?
            """,
            (bucket_key,),
        )
        oldest = cursor.fetchone()[0]
        if oldest is None:
            return self.settings.window_seconds
        elapsed = int(now_epoch - float(oldest))
        return max(1, self.settings.window_seconds - elapsed)

    def _latest_created_at(
        self,
        connection: sqlite3.Connection,
        bucket_key: str,
    ) -> float | None:
        cursor = connection.execute(
            """
            SELECT MAX(created_at)
            FROM rate_limit_events
            WHERE bucket_key = ?
            """,
            (bucket_key,),
        )
        latest = cursor.fetchone()[0]
        return float(latest) if latest is not None else None

    def _target_retry_after_seconds_from_epoch(
        self,
        latest_epoch: float,
        now_epoch: float,
    ) -> int:
        elapsed = int(now_epoch - latest_epoch)
        return max(1, self.settings.target_min_interval_seconds - elapsed)

    @staticmethod
    def _bucket_key(capability_id: str, scope: str, value: str) -> str:
        return f"{capability_id}:{scope}:{value}"

    @classmethod
    def _target_bucket_key(cls, capability_id: str, message: IncomingMessage) -> str:
        target = message.group_id or message.sender_id or message.session_id
        return cls._bucket_key(capability_id, "target", target)


def build_rate_limit_settings(config: object) -> RateLimitSettings:
    return RateLimitSettings(
        enabled=bool(getattr(config, "bot_rate_limit_enabled", True)),
        window_seconds=int(getattr(config, "bot_rate_limit_window_seconds", 60)),
        chat_global_max_requests=int(
            getattr(config, "bot_rate_limit_chat_global_max_requests", 60)
        ),
        chat_session_max_requests=int(
            getattr(config, "bot_rate_limit_chat_session_max_requests", 6)
        ),
        chat_sender_max_requests=int(
            getattr(config, "bot_rate_limit_chat_sender_max_requests", 4)
        ),
        target_min_interval_seconds=int(
            getattr(config, "bot_rate_limit_target_min_interval_seconds", 0)
        ),
        proactive_window_seconds=3600,
        proactive_group_max_replies=int(
            getattr(config, "bot_group_proactive_max_replies_per_hour", 6)
        ),
        proactive_group_cooldown_seconds=int(
            getattr(config, "bot_group_proactive_cooldown_seconds", 90)
        ),
        bypass_roles=list(
            getattr(config, "bot_rate_limit_bypass_roles", DEFAULT_BYPASS_ROLES)
        ),
    )


def build_rate_limiter(config: object) -> RateLimiter:
    settings = build_rate_limit_settings(config)
    db_path = str(getattr(config, "bot_rate_limit_db_path", "")).strip()
    if db_path:
        return SQLiteRateLimiter(db_path, settings=settings)
    return InMemoryRateLimiter(settings)

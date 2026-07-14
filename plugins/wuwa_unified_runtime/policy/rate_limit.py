from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Protocol

from pydantic import Field, field_validator

from plugins.wuwa_unified_runtime.contracts import IncomingMessage
from plugins.wuwa_unified_runtime.contracts.runtime import StrictBaseModel, new_debug_id

CHAT_CAPABILITY_IDS = {"wuwa.chat"}
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

    @field_validator("target_min_interval_seconds")
    @classmethod
    def require_non_negative_interval(cls, value: int) -> int:
        if value < 0:
            raise ValueError("target min interval must not be negative")
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
    ) -> RateLimitDecision:
        raise NotImplementedError


class InMemoryRateLimiter:
    def __init__(
        self,
        settings: RateLimitSettings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or RateLimitSettings()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._buckets: dict[str, deque[datetime]] = defaultdict(deque)

    def check_and_record(
        self,
        message: IncomingMessage,
        capability_id: str,
        *,
        amount: int = 1,
    ) -> RateLimitDecision:
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

    def check_and_record(
        self,
        message: IncomingMessage,
        capability_id: str,
        *,
        amount: int = 1,
    ) -> RateLimitDecision:
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
        with self._connect() as connection:
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

    def _has_bypass_role(self, message: IncomingMessage) -> bool:
        bypass_roles = set(self.settings.bypass_roles)
        return any(role.strip().lower() in bypass_roles for role in message.sender_roles)

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
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

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

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
        enabled=bool(getattr(config, "wuwa_rate_limit_enabled", True)),
        window_seconds=int(getattr(config, "wuwa_rate_limit_window_seconds", 60)),
        chat_global_max_requests=int(
            getattr(config, "wuwa_rate_limit_chat_global_max_requests", 60)
        ),
        chat_session_max_requests=int(
            getattr(config, "wuwa_rate_limit_chat_session_max_requests", 6)
        ),
        chat_sender_max_requests=int(
            getattr(config, "wuwa_rate_limit_chat_sender_max_requests", 4)
        ),
        target_min_interval_seconds=int(
            getattr(config, "wuwa_rate_limit_target_min_interval_seconds", 0)
        ),
        bypass_roles=list(
            getattr(config, "wuwa_rate_limit_bypass_roles", DEFAULT_BYPASS_ROLES)
        ),
    )


def build_rate_limiter(config: object) -> RateLimiter:
    settings = build_rate_limit_settings(config)
    db_path = str(getattr(config, "wuwa_rate_limit_db_path", "")).strip()
    if db_path:
        return SQLiteRateLimiter(db_path, settings=settings)
    return InMemoryRateLimiter(settings)

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
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    StrictBaseModel,
    new_debug_id,
)

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
    # R3 防刷屏（2026-09-12 用户裁定）：同一发送者两次 bot.chat 回复的最小
    # 间隔（秒）。1 分钟喊 5 次只回 1 次；不受 bypass_roles 豁免（刷屏保护
    # 对所有人一致）。0 = 关闭。
    chat_sender_min_interval_seconds: int = 45
    target_min_interval_seconds: int = 0
    proactive_window_seconds: int = 3600
    proactive_group_max_replies: int = 6
    proactive_group_cooldown_seconds: int = 90
    # 群聊专属句数帽（用户口径：每小时 60 句、每分钟 3 句）。0 = 该帽不生效。
    group_hourly_max_requests: int = 0
    group_minute_max_requests: int = 0
    # 用户情绪低落时的豁免：安抚不该被句数帽挡住（"要紧的事不受限制"）。
    emotion_exempt_enabled: bool = True
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

    @field_validator("group_hourly_max_requests", "group_minute_max_requests")
    @classmethod
    def require_non_negative_group_caps(cls, value: int) -> int:
        # 0 = 该帽不生效（显式语义，避免 min(n, 0)=0 把帽反向变成"不限"）。
        if value < 0:
            raise ValueError("group request caps must not be negative")
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

    # 审查 A-18：rollback 是**可选能力**，故意不进 Protocol——测试桩与
    # 第三方实现只保证 check_and_record；调用方（pipeline）用 getattr 探测，
    # 缺失即跳过回滚（fail-open）。InMemory/SQLite 两实现均已提供。


# R3 记账可能携带的放行型 reason（allowed 之外）。审查 A-04 序下 R3 记账
# 先于 interactive/role_bypass/emotion_exempt 各早退执行，这些路径返回时
# sender_interval 桶已 +1——rollback 必须同样覆盖，否则能力失败后管理员的
# 下一次点名/情绪豁免消息会被残留记账误拦。其余 reason（disabled/
# non_chat_capability/各拦截）在 R3 门之前或 R3 门未命中，零记账。
_R3_RECORD_CARRYING_REASONS = frozenset(
    {"interactive_bypass", "role_bypass", "emotion_exempt"}
)


def _sender_interval_record_applies(
    settings: RateLimitSettings,
    message: IncomingMessage,
    capability_id: str,
) -> bool:
    """R3 同人点名最小间隔「放行即记账」的生效条件（check/rollback 共用）。

    审查 A-04 序：该检查先于 interactive_bypass 早退执行，命中且放行时
    sender_interval 桶已 +1——所以 reason=interactive_bypass 的 decision
    也携带这条记账，rollback 必须覆盖。InMemory 与 SQLite 的 check 侧把
    条件拆在两处（外层门 + 函数内），但「已记账」的生效集相同，即本函数。
    """
    return bool(
        settings.enabled
        and capability_id in CHAT_CAPABILITY_IDS
        and settings.chat_sender_min_interval_seconds > 0
        and message.mentions_bot
        and message.session_type.value == "group"
    )


def _group_windows_record_applies(
    settings: RateLimitSettings,
    message: IncomingMessage,
) -> bool:
    """群句数帽在 allowed 路径「已记账」的条件（rollback 用）。

    情绪豁免命中时 check_and_record 直接以 reason=emotion_exempt 返回且
    零记账，走不到 allowed，故此处无需复判豁免。
    """
    return bool(
        is_group_session(message)
        and (
            settings.group_hourly_max_requests > 0
            or settings.group_minute_max_requests > 0
        )
    )


# 情绪低落标签集合：命中即豁免群句数帽（"要紧的事不受限制"）。
_DISTRESS_LABELS = frozenset({"support_needed", "lonely", "low_energy", "frustrated"})


def is_group_session(message: IncomingMessage) -> bool:
    """是否群聊会话（群句数帽只作用于群）。"""
    session_type = getattr(message, "session_type", None)
    value = getattr(session_type, "value", session_type)
    if str(value).strip().lower() == "group":
        return True
    return bool(getattr(message, "group_id", None))


def distress_exemption(message: IncomingMessage) -> RateLimitDecision | None:
    """用户情绪低落时的限流豁免决定（不命中返回 None）。

    复用聊天链路的规则情绪识别（纯关键词匹配、无 I/O），命中
    support_needed / lonely / low_energy / frustrated 即豁免。
    识别失败按"不豁免"处理，保持限流而不是放开。
    """
    text = str(getattr(message, "plain_text", "") or "")
    if not text.strip():
        return None
    try:
        from plugins.bot_unified_runtime.character.emotion import (
            RuleBasedEmotionProvider,
        )

        # 直接构造规则识别器：不依赖 config（限流器拿不到完整 Config），
        # 也避免把"情绪功能总开关"耦合进限流豁免判断。
        signals = RuleBasedEmotionProvider(max_signals=4).analyze(
            request_id=str(getattr(message, "request_id", "") or ""),
            sender_id=str(getattr(message, "sender_id", "") or ""),
            session_id=str(getattr(message, "session_id", "") or ""),
            query_text=text,
        )
    except Exception:  # noqa: BLE001 - 识别失败按不豁免处理。
        return None
    # 注意字段名是 emotion_label（不是 label）——写错会静默恒不豁免。
    labels = {
        str(getattr(signal, "emotion_label", "") or "").strip().lower()
        for signal in signals
    }
    hit = labels & _DISTRESS_LABELS
    if not hit:
        return None
    return RateLimitDecision(
        allowed=True,
        reason="emotion_exempt",
        audit_tags=[
            "rate_limit:emotion_exempt",
            f"rate_limit:emotion:{min(hit)}",
        ],
    )


class InMemoryRateLimiter:
    # 桶清扫间隔：只访问被命中的桶会让未再命中的桶永久滞留（键集合无界增长）。
    _SWEEP_INTERVAL_SECONDS = 600.0

    def __init__(
        self,
        settings: RateLimitSettings | Callable[[], RateLimitSettings] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # settings 可以是静态对象，也可以是**每次判定实时求值**的 callable——
        # 后者让 /bot runtime set 改的群句数帽/情绪豁免立刻生效，而不是等重启。
        self._settings_source = settings or RateLimitSettings()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._buckets: dict[str, deque[datetime]] = defaultdict(deque)
        self._last_sweep = time.monotonic()

    @property
    def settings(self) -> RateLimitSettings:
        """当前限流设置（callable 时实时求值；失败回退默认，保持限流不放开）。"""
        source = self._settings_source
        if callable(source):
            try:
                resolved = source()
            except Exception:  # noqa: BLE001 - 求值失败回退默认设置。
                return RateLimitSettings()
            return resolved if isinstance(resolved, RateLimitSettings) else RateLimitSettings()
        return source

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
        # R3 同人点名最小间隔：必须先于 interactive 早退（审查 A-04：原顺序
        # interactive_bypass 早退在前，旧 226-233 行）——pipeline 把「群聊 @bot」
        # 标记为 interactive，bypass 在前时 45s 冷却对最该防刷屏的群点名永不
        # 生效，私聊（interactive=False）反被误拦，防护方向打反。会话门只认
        # 群聊：私聊连续对话是正常形态，点名冷却不适用。enabled=False 或非
        # chat 能力不检查，与下方短路语义一致；先于 role bypass 的例外语义
        # （刷屏保护人人平等）不变。
        if (
            self.settings.enabled
            and capability_id in CHAT_CAPABILITY_IDS
            and self.settings.chat_sender_min_interval_seconds > 0
            and message.mentions_bot
            and message.session_type.value == "group"
        ):
            decision = self._check_sender_min_interval(
                message, capability_id, self.clock()
            )
            if decision is not None:
                return decision
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
        # 群聊专属句数帽（用户口径：每小时 60 句、每分钟 3 句）。情绪低落时豁免。
        group_limited = self._check_group_windows(
            capability_id, message, now, safe_amount
        )
        if group_limited is not None:
            return group_limited
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

    def rollback(
        self,
        message: IncomingMessage,
        capability_id: str,
        *,
        amount: int = 1,
        reason: str = "allowed",
    ) -> None:
        """审查 A-18 额度回滚：撤销一次 check_and_record 的真实记账。

        只处理确实写过桶的 reason（与 check_and_record 返回值一一对应）：
        - allowed：global/session/sender 各 amount + target 1（若启用）
          + 群窗口各 amount（若启用且群聊且非情绪豁免）+ R3 sender_interval 1
          （若命中点名条件）；
        - interactive_bypass / role_bypass / emotion_exempt：仅 R3
          sender_interval 1——A-04 序下 R3 记账先于这三个早退/分流（见
          _R3_RECORD_CARRYING_REASONS）；
        - proactive_allowed：proactive_group 桶 1。
        其余 reason（各拦截/禁用/非 chat）本就零记账，直接返回。
        从桶尾移除最近记账：回滚紧跟能力失败/重复拒绝发生，本调用写入的
        时间戳通常就是桶尾；并发同刻碰撞至多多退一条，方向是放宽而非误拦，
        随窗口滚动自愈。
        """
        safe_amount = max(1, int(amount))
        if reason == "proactive_allowed":
            self._pop_recent(
                self._buckets.get(
                    self._bucket_key(
                        capability_id,
                        "proactive_group",
                        message.group_id or message.session_id,
                    )
                ),
                1,
            )
            return
        if reason != "allowed" and reason not in _R3_RECORD_CARRYING_REASONS:
            return
        if _sender_interval_record_applies(self.settings, message, capability_id):
            self._pop_recent(
                self._buckets.get(self._sender_interval_key(capability_id, message)),
                1,
            )
        if reason != "allowed":
            return
        if _group_windows_record_applies(self.settings, message):
            group_key = str(message.group_id or message.session_id)
            for scope in ("group_hour", "group_minute"):
                # 镜像 _check_group_windows 的 active 判定：帽 <=0 的窗口没记账。
                if scope == "group_hour" and self.settings.group_hourly_max_requests <= 0:
                    continue
                if scope == "group_minute" and self.settings.group_minute_max_requests <= 0:
                    continue
                self._pop_recent(
                    self._buckets.get(self._bucket_key(capability_id, scope, group_key)),
                    safe_amount,
                )
        if self.settings.target_min_interval_seconds > 0:
            self._pop_recent(
                self._buckets.get(self._target_bucket_key(capability_id, message)),
                1,
            )
        for scope, value in (
            ("global", "all"),
            ("session", message.session_id),
            ("sender", message.sender_id),
        ):
            self._pop_recent(
                self._buckets.get(self._bucket_key(capability_id, scope, value)),
                safe_amount,
            )

    @staticmethod
    def _pop_recent(bucket: deque[datetime] | None, count: int) -> None:
        """从桶尾移除至多 count 条记账；.get 取桶不触发 defaultdict 建桶。"""
        if not bucket:
            return
        for _ in range(max(0, int(count))):
            if not bucket:
                return
            bucket.pop()

    def _sender_interval_key(self, capability_id: str, message: IncomingMessage) -> str:
        return self._bucket_key(capability_id, "sender_interval", message.sender_id)

    def _check_sender_min_interval(
        self, message: IncomingMessage, capability_id: str, now: datetime
    ) -> RateLimitDecision | None:
        bucket = self._buckets[self._sender_interval_key(capability_id, message)]
        if bucket:
            elapsed = (now - bucket[-1]).total_seconds()
            if elapsed < self.settings.chat_sender_min_interval_seconds:
                return RateLimitDecision(
                    allowed=False,
                    reason="sender_min_interval",
                    retry_after_seconds=max(
                        1,
                        int(self.settings.chat_sender_min_interval_seconds - elapsed),
                    ),
                    audit_tags=["rate_limit:blocked", "rate_limit:sender_min_interval"],
                )
        bucket.append(now)
        return None

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

    def _check_group_windows(
        self,
        capability_id: str,
        message: IncomingMessage,
        now: datetime,
        amount: int,
    ) -> RateLimitDecision | None:
        """群聊每小时/每分钟滑动窗口判定；通过则记账并返回 None。

        只作用于群聊；两个窗口任一超限即拒绝（先判后记，避免部分记账）。
        """
        if not is_group_session(message):
            return None
        if (
            self.settings.group_hourly_max_requests <= 0
            and self.settings.group_minute_max_requests <= 0
        ):
            return None
        exemption = (
            distress_exemption(message) if self.settings.emotion_exempt_enabled else None
        )
        if exemption is not None:
            return exemption
        group_key = str(message.group_id or message.session_id)
        active: list[tuple[str, deque[datetime], int, int]] = []
        for scope, window_seconds, limit in (
            ("group_hour", 3600, self.settings.group_hourly_max_requests),
            ("group_minute", 60, self.settings.group_minute_max_requests),
        ):
            if limit <= 0:
                continue
            bucket = self._buckets[self._bucket_key(capability_id, scope, group_key)]
            while bucket and (now - bucket[0]).total_seconds() >= window_seconds:
                bucket.popleft()
            active.append((scope, bucket, limit, window_seconds))
        for scope, bucket, limit, window_seconds in active:
            if len(bucket) + amount > limit:
                retry_after = window_seconds
                if bucket:
                    elapsed = int((now - bucket[0]).total_seconds())
                    retry_after = max(1, window_seconds - elapsed)
                return RateLimitDecision(
                    allowed=False,
                    reason=f"{scope}_exceeded",
                    retry_after_seconds=retry_after,
                    audit_tags=["rate_limit:blocked", f"rate_limit:{scope}_exceeded"],
                )
        for _scope, bucket, _limit, _window in active:
            for _range in range(amount):
                bucket.append(now)
        return None

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
        # R3 同人点名最小间隔：先于 interactive 早退与 role bypass（审查 A-04：
        # 旧顺序 interactive_bypass 早退在前、旧 528-533 行，而 pipeline 把
        # 「群聊 @bot」标记为 interactive，45s 冷却对最该防刷屏的群点名永不
        # 生效，私聊（interactive=False）反被误拦）。会话门只认群聊——私聊
        # 连续对话是正常形态，点名冷却不适用；enabled=False 或非 chat 能力
        # 不检查，对齐下方短路语义；与 InMemory 实现同序同语义。
        if (
            self.settings.enabled
            and capability_id in CHAT_CAPABILITY_IDS
            and message.session_type.value == "group"
        ):
            min_interval_decision = self._check_sender_min_interval(
                message, capability_id
            )
            if min_interval_decision is not None:
                return min_interval_decision
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

    def _check_sender_min_interval(
        self, message: IncomingMessage, capability_id: str
    ) -> RateLimitDecision | None:
        """SQLite 版同人点名最小间隔；放行即记录（bot 真回复才进入冷却）。"""
        if self.settings.chat_sender_min_interval_seconds <= 0:
            return None
        if not message.mentions_bot:
            return None  # 仅点名回复防刷屏；主动接话/图片路径不受限
        self._ensure_schema()
        now_epoch = self.clock().timestamp()
        key = self._bucket_key(capability_id, "sender_interval", message.sender_id)
        with closing(self._connect()) as connection, connection:
            self._cleanup_expired(connection, now_epoch)
            latest = self._latest_created_at(connection, key)
            if latest is not None:
                elapsed = now_epoch - latest
                if elapsed < self.settings.chat_sender_min_interval_seconds:
                    return RateLimitDecision(
                        allowed=False,
                        reason="sender_min_interval",
                        retry_after_seconds=max(
                            1,
                            int(
                                self.settings.chat_sender_min_interval_seconds
                                - elapsed
                            ),
                        ),
                        audit_tags=[
                            "rate_limit:blocked",
                            "rate_limit:sender_min_interval",
                        ],
                    )
            connection.execute(
                "INSERT INTO rate_limit_events (bucket_key, created_at) VALUES (?, ?)",
                (key, now_epoch),
            )
        return None

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
            # 群聊专属句数帽（语义对齐 InMemoryRateLimiter._check_group_windows）：
            # 先判后记，豁免/拒绝都直接返回、不写入任何桶。
            group_limited = self._check_group_windows(
                connection, message, capability_id, now_epoch, safe_amount
            )
            if group_limited is not None:
                return group_limited
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

    def rollback(
        self,
        message: IncomingMessage,
        capability_id: str,
        *,
        amount: int = 1,
        reason: str = "allowed",
    ) -> None:
        """审查 A-18 额度回滚（SQLite 版，桶集判定与 InMemory 版同语）。

        镜像 check_and_record 的写路径：只删「确实写入过」的桶，每桶按
        created_at DESC, id DESC 删最近记账。allowed 携带全桶记账；
        interactive_bypass / role_bypass / emotion_exempt 仅携带 R3
        sender_interval 记账（A-04 序，见 _R3_RECORD_CARRYING_REASONS）；
        其余 reason 零记账直接返回。
        """
        safe_amount = max(1, int(amount))
        deletes: list[tuple[str, int]] = []
        if reason == "proactive_allowed":
            deletes.append(
                (
                    self._bucket_key(
                        capability_id,
                        "proactive_group",
                        message.group_id or message.session_id,
                    ),
                    1,
                )
            )
        else:
            if reason != "allowed" and reason not in _R3_RECORD_CARRYING_REASONS:
                return
            if _sender_interval_record_applies(self.settings, message, capability_id):
                deletes.append(
                    (
                        self._bucket_key(
                            capability_id, "sender_interval", message.sender_id
                        ),
                        1,
                    )
                )
            if reason != "allowed":
                # 仅 R3 记账：group/target/scoped 桶在这些早退路径未写过。
                if deletes:
                    self._apply_deletes(deletes)
                return
            if _group_windows_record_applies(self.settings, message):
                group_key = str(message.group_id or message.session_id)
                if self.settings.group_hourly_max_requests > 0:
                    deletes.append(
                        (self._bucket_key(capability_id, "group_hour", group_key), safe_amount)
                    )
                if self.settings.group_minute_max_requests > 0:
                    deletes.append(
                        (self._bucket_key(capability_id, "group_minute", group_key), safe_amount)
                    )
            if self.settings.target_min_interval_seconds > 0:
                deletes.append(
                    (self._target_bucket_key(capability_id, message), 1)
                )
            for scope, value in (
                ("global", "all"),
                ("session", message.session_id),
                ("sender", message.sender_id),
            ):
                deletes.append(
                    (self._bucket_key(capability_id, scope, value), safe_amount)
                )
        if not deletes:
            return
        self._apply_deletes(deletes)

    def _apply_deletes(self, deletes: list[tuple[str, int]]) -> None:
        with self._lock:
            self._ensure_schema()
            with closing(self._connect()) as connection, connection:
                for bucket_key, count in deletes:
                    self._delete_latest(connection, bucket_key, count)

    @staticmethod
    def _delete_latest(
        connection: sqlite3.Connection,
        bucket_key: str,
        count: int,
    ) -> None:
        """删除桶内最近 count 条记账（created_at 降序，同刻按 id 降序）。"""
        connection.execute(
            """
            DELETE FROM rate_limit_events WHERE rowid IN (
                SELECT rowid FROM rate_limit_events
                WHERE bucket_key = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
            )
            """,
            (bucket_key, max(0, int(count))),
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

    def _check_group_windows(
        self,
        connection: sqlite3.Connection,
        message: IncomingMessage,
        capability_id: str,
        now_epoch: float,
        amount: int,
    ) -> RateLimitDecision | None:
        """群聊每小时/每分钟滑动窗口判定（SQLite 版，语义对齐 InMemory 实现）。

        只作用于群聊；两个窗口任一超限即拒绝且不记账（先判后记，避免部分记账）；
        情绪低落豁免命中时直接放行，同样不记账。判定通过才写入时间戳行。
        """
        if not is_group_session(message):
            return None
        if (
            self.settings.group_hourly_max_requests <= 0
            and self.settings.group_minute_max_requests <= 0
        ):
            return None
        exemption = (
            distress_exemption(message) if self.settings.emotion_exempt_enabled else None
        )
        if exemption is not None:
            return exemption
        group_key = str(message.group_id or message.session_id)
        active: list[tuple[str, str, int, int]] = []
        for scope, window_seconds, limit in (
            ("group_hour", 3600, self.settings.group_hourly_max_requests),
            ("group_minute", 60, self.settings.group_minute_max_requests),
        ):
            if limit <= 0:
                continue
            bucket_key = self._bucket_key(capability_id, scope, group_key)
            self._prune(connection, bucket_key, now_epoch - window_seconds)
            active.append((scope, bucket_key, limit, window_seconds))
        for scope, bucket_key, limit, window_seconds in active:
            if self._count(connection, bucket_key) + amount > limit:
                return RateLimitDecision(
                    allowed=False,
                    reason=f"{scope}_exceeded",
                    retry_after_seconds=self._window_retry_after_seconds(
                        connection, bucket_key, now_epoch, window_seconds
                    ),
                    audit_tags=["rate_limit:blocked", f"rate_limit:{scope}_exceeded"],
                )
        for _scope, bucket_key, _limit, _window in active:
            connection.executemany(
                """
                INSERT INTO rate_limit_events (bucket_key, created_at)
                VALUES (?, ?)
                """,
                [(bucket_key, now_epoch) for _ in range(amount)],
            )
        return None

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
            # 群句数帽窗口：低频清理不得删掉仍在计数窗口内的时间戳行，
            # 否则小时帽会少算（proactive 窗口被调小时这里兜底）。
            3600 if self.settings.group_hourly_max_requests > 0 else 0,
            60 if self.settings.group_minute_max_requests > 0 else 0,
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
        return self._window_retry_after_seconds(
            connection, bucket_key, now_epoch, self.settings.window_seconds
        )

    def _window_retry_after_seconds(
        self,
        connection: sqlite3.Connection,
        bucket_key: str,
        now_epoch: float,
        window_seconds: int,
    ) -> int:
        """按桶内最老存活事件估算解禁秒数（空桶回退整窗，对齐 InMemory）。"""
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
            return window_seconds
        elapsed = int(now_epoch - float(oldest))
        return max(1, window_seconds - elapsed)

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
        group_hourly_max_requests=int(
            getattr(config, "bot_rate_limit_group_max_per_hour", 0) or 0
        ),
        group_minute_max_requests=int(
            getattr(config, "bot_rate_limit_group_max_per_minute", 0) or 0
        ),
        emotion_exempt_enabled=bool(
            getattr(config, "bot_rate_limit_emotion_exempt", True)
        ),
        bypass_roles=list(
            getattr(config, "bot_rate_limit_bypass_roles", DEFAULT_BYPASS_ROLES)
        ),
    )


def build_rate_limiter(
    config: object,
    *,
    settings_provider: Callable[[], RateLimitSettings] | None = None,
) -> RateLimiter:
    """构造限流器。

    传 ``settings_provider`` 时每次判定实时求值（群句数帽/情绪豁免可热改）；
    否则退回启动期快照（旧行为）。
    """
    settings = settings_provider if settings_provider is not None else build_rate_limit_settings(config)
    db_path = str(getattr(config, "bot_rate_limit_db_path", "")).strip()
    if db_path:
        # SQLite 版目前不支持 callable settings（其判定走 SQL 窗口），传静态快照。
        resolved = settings() if callable(settings) else settings
        return SQLiteRateLimiter(db_path, settings=resolved)
    return InMemoryRateLimiter(settings)

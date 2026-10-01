from __future__ import annotations

import hashlib
import math
import sqlite3
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import ClassVar, Protocol

from pydantic import Field, field_validator

from plugins.bot_unified_runtime.contracts import IncomingMessage
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    StrictBaseModel,
    new_debug_id,
)

from . import redrive_ledger

# ---- 「聊天类」名册的唯一落点（W1 并册）------------------------------------
# 曾三处各写一份字面量（限流侧 / 安静侧 / 预算侧），安静侧还把 `bot.content`
# 算成聊天、限流侧把它算成命令 ⇒ 同一条能力两本账，改一处漏一处。
# 名册只准从这里导入（quiet_hours.py 已改吃本模块，`reply_budget.py` 那枚同名
# 集合在别席手里，登记进交接面）。两层**不同判据、同一真身**：
# 窄层＝走聊天句数账/点名最小间隔、且**不进命令帽**的那一层；判据与管道
# `interactive` 那句（`capability_id != "bot.chat"`）同口径，少罩一个能力就是零限流。
CHAT_CAPABILITY_IDS = frozenset({"bot.chat"})
# 宽层＝「由消息内容自己触发的被动回复」（聊天 + 链接解析）＝安静时间本该拦的那层。
# `bot.content` 是回复不是命令（真身＝`runtime/base_router.py` 的 RouteKind.CONTENT
# 册，链接命中即触发）：夜里没人 @ 它就不该开口；而限流侧它仍归命令帽罩 ⇒ 两层
# 各有读点、字面量只在这里出现一次。
CHAT_LIKE_CAPABILITY_IDS = CHAT_CAPABILITY_IDS | frozenset({"bot.content"})
DEFAULT_BYPASS_ROLES = ["admin"]

# 群节奏层的桶名（InMemory 与 SQLite 共用同一组 scope，判定序也共用）。
PACING_SCOPE_TOKENS = "group_pacing_tokens"
PACING_SCOPE_MINUTE = "group_pace_minute"
PACING_SCOPE_LAST = "group_pace_last"
PACING_SCOPE_VISION_LAST = "group_pace_vision_last"
PACING_MINUTE_WINDOW_SECONDS = 60


def interval_wait_seconds(interval_seconds: float, elapsed_seconds: float) -> int:
    """「还剩几秒解禁」的唯一真身：**向上取整**、至少 1 秒。

    旧写法 `int(间隔 - elapsed)` 向下截断——报出去的值最多比解禁点短 1 秒，
    而 pipeline 只睡报出来的秒数（`_schedule_rate_limit_redrive` →
    `_redrive_after`），睡完仍差零点几秒被拦，补回额度（`max_attempts=1`）
    恰好在当场用光 ⇒ 连发消息静默丢弃（2026-09-25 用户裁定第 2 项）。
    向上取整是唯一安全方向：至多多等一秒，不会等完还进不去。

    点名最小间隔（InMemory/SQLite 两把尺）、群主动接话冷却、节奏层文字/图类
    独立间隔与分钟窗全部共读这一枚算式；AST 锁
    `tests/test_policy_queue_not_drop.py::test_interval_arithmetic_has_a_single_truth_source`
    禁止第二份截断副本回流。
    """
    return max(1, math.ceil(float(interval_seconds) - float(elapsed_seconds)))


def sender_interval_ledger_key(
    capability_id: str, sender_id: str, group_id: str = ""
) -> str:
    """冷却桶键＝补回账本键的单一格式（两后端与 `redrive_wait_seconds` 共用）。

    需求项 2（2026-09-29 用户裁定）：**同一发送者在同一群的连发**才算同一份配额——
    旧键只有 sender ⇒ A 群的点名冷却会误伤 B 群的点名（跨群连坐，从来不是防刷屏
    的本意）。键里编入 group_id；群号缺失的形态（非群会话根本走不到 R3，理论不
    存在）回落旧格式，保证读写两侧永远同键。
    """
    if str(group_id or "").strip():
        return f"{capability_id}:sender_interval:{str(group_id).strip()}:{sender_id}"
    return f"{capability_id}:sender_interval:{sender_id}"


@dataclass
class _TokenState:
    """一处令牌桶状态：剩余令牌 + 上次回血时刻（epoch 秒）。"""

    tokens: float
    updated_at: float


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
    # ---- 群聊节奏层（2026-09-24 T7，采纳 T6 令牌桶主干）--------------------
    # 她描述的问题：**想设"1 小时 30 句"，但刚开始就能把限额飞速跑光，之后整段
    # 沉默**。滑动对数窗天然不防突发（T6 实测：只开小时帽 30 ⇒ 2 分钟放 30 条、
    # 随后静默 58 分钟）。令牌桶把"团块配额"换成"匀速额度"：容量 B 决定开局连发
    # 上限，速率 x/小时决定长期额度，桶空后每 3600/x 秒必回一句 ⇒ **最坏静默
    # 从"整窗"降为 3600/x 秒**。
    # x = 每小时补充多少句（0 = 整个节奏层不生效，含下面的分钟帽与最小间隔）。
    group_pacing_tokens_per_hour: int = 0
    # B = 桶容量（可连发上限；开局最多连发 B 句，不会一把打光小时额度）。
    group_pacing_burst_capacity: int = 5
    # 节奏层的分钟外骨架（与上面的小时桶是两道独立的帽，缺一都可能被突发绕过）。
    group_pacing_max_per_minute: int = 3
    # 相邻两句群非点名回复的最小间隔（0 = 不设间隔）。
    group_pacing_min_interval_seconds: int = 20
    # 图片/表情包类**自己的**独立最小间隔（用户裁定：群聊接图必须跟主动回复频率
    # 走，不再每条必回；与文字共用同一个小时桶，另加这道更宽的间隔）。0 = 不设。
    group_vision_min_interval_seconds: int = 120
    # 用户情绪低落时的豁免：安抚不该被句数帽挡住（"要紧的事不受限制"）。
    emotion_exempt_enabled: bool = True
    bypass_roles: list[str] = Field(default_factory=lambda: list(DEFAULT_BYPASS_ROLES))
    # ---- 命令腿独立帽（E05 缺口二）----------------------------------------
    # 缺陷底账：pipeline 把 `capability_id != "bot.chat"` 一律标 interactive=True，
    # 而两把限流器都在 interactive 处直接放行（InMemory `_check_command_leg` 落点
    # 之前那条腿），紧随其后还有第二条漏腿 non_chat_capability ⇒ 全部命令能力
    # **零限流**：任意成员可在群里把 /bot 敲到算力见底。
    # 修法：命令帽先于那两条早退腿执行，非 chat 能力一律先过这道帽；`bypass_roles`
    # （缺省 ["admin"]，超管经 roles.py 叠 admin）仍享旧豁免语义，管理员自救通道不锁。
    # 记账与 chat 句数帽**分册**（scope 前缀 command_*），能力失败退还才不会对错账。
    command_enabled: bool = True
    command_window_seconds: int = 60
    # 0 = 该腿不生效（与群句数帽同口径，避免 min(n,0) 反向变成"不限"）。
    command_sender_max_requests: int = 12
    command_group_max_requests: int = 20
    # 命令腿自己的旁路脸：缺省沿用 DEFAULT_BYPASS_ROLES 的脸，与 chat 侧旁路解耦
    # （要把管理员也关进帽子里改这一枚，别顺手改 bypass_roles 动到聊天侧语义）。
    command_bypass_roles: list[str] = Field(
        default_factory=lambda: list(DEFAULT_BYPASS_ROLES)
    )

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

    @field_validator(
        "group_pacing_tokens_per_hour",
        "group_pacing_max_per_minute",
        "group_pacing_min_interval_seconds",
        "group_vision_min_interval_seconds",
    )
    @classmethod
    def require_non_negative_pacing(cls, value: int) -> int:
        # 与群帽同口径：0 = 该项不生效（节奏层整体由 tokens_per_hour>0 点火），
        # 负数是写错了，绝不允许（min(n, 负数) 会把帽反向变成"不限"）。
        if value < 0:
            raise ValueError("group pacing parameters must not be negative")
        return value

    @field_validator("group_pacing_burst_capacity")
    @classmethod
    def require_positive_burst_capacity(cls, value: int) -> int:
        # 容量 0 会让节奏层"点火却一句都发不出"（tokens_per_hour>0 时永久静默），
        # 属自相矛盾的参数 ⇒ 装载期就拒，不留到运行期哑掉。
        if value < 1:
            raise ValueError("group pacing burst capacity must be at least 1")
        return value

    @field_validator("bypass_roles", "command_bypass_roles")
    @classmethod
    def normalize_bypass_roles(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values if value.strip()]
        return list(dict.fromkeys(normalized))

    @field_validator("command_window_seconds")
    @classmethod
    def require_positive_command_window(cls, value: int) -> int:
        if value < 1:
            raise ValueError("command rate limit window must be at least 1 second")
        return value

    @field_validator("command_sender_max_requests", "command_group_max_requests")
    @classmethod
    def require_non_negative_command_caps(cls, value: int) -> int:
        # 0 = 该腿不生效；负数是写错了（min(n, 负数) 会把帽反向变成"不限"）。
        if value < 0:
            raise ValueError("command request caps must not be negative")
        return value


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
# 先于 interactive/role_bypass 各早退执行，这些路径返回时 sender_interval
# 桶已 +1——rollback 必须同样覆盖，否则能力失败后管理员的下一次点名会被
# 残留记账误拦。其余 reason（disabled/non_chat_capability/各拦截）在 R3 门
# 之前或 R3 门未命中，零记账。
# 2026-09-24 裁定 3 后 emotion_exempt 不再属于本集合：豁免改判为"只免最小
# 间隔、句数额度照常且照常记账"，它走 _FULL_RECORD_REASONS 的全额回滚。
_R3_RECORD_CARRYING_REASONS = frozenset({"interactive_bypass", "role_bypass"})

# 「放行即全额记账」的 reason 集合：allowed 与 emotion_exempt（裁定 3 后
# 豁免消息同样消耗句数额度并落全部账，rollback 必须对称退还）。
_FULL_RECORD_REASONS = frozenset({"allowed", "emotion_exempt"})

# 命令腿（E05 缺口二）放行时携带的记账 reason。刻意**不**并入
# _FULL_RECORD_REASONS：命令账与 chat 句数账是两本账，混用会让能力失败时
# 退错账（退到没写过的 chat 桶、却漏退真写过的 command 桶）。
_COMMAND_RECORD_CARRYING_REASONS = frozenset({"command_allowed"})

# 命令腿的两格桶名（InMemory 与 SQLite 共用同一组 scope，禁第二套命名）。
COMMAND_SCOPE_SENDER = "command_sender"
COMMAND_SCOPE_GROUP = "command_group"


def rate_limit_bucket_key(capability_id: str, scope: str, value: str) -> str:
    """桶键格式的单一真身：两把限流器的 `_bucket_key` 都只是它的一层皮。

    命令腿的 check 侧与 rollback 侧要拿同一枚键退账（退错桶＝白占一格冷却位，
    同 2026-09-29 需求项 2 治的那一刀），所以键形只准有一份。
    """
    return f"{capability_id}:{scope}:{value}"


def command_leg_buckets(
    settings: RateLimitSettings, capability_id: str, message: IncomingMessage
) -> list[tuple[str, str, int]]:
    """命令腿要读写哪几格桶：``[(scope, bucket_key, cap), ...]``。

    check 侧与 rollback 侧**共读这一枚**（两把限流器也用同一份），因为：
    - 群腿只在群聊会话建账——私聊不记群账，也不许被别人的群帽连坐；
    - ``cap <= 0`` 的腿根本不写桶，rollback 若照单全退就会退到没写过的桶；
    - 退账退错桶＝白占一格冷却位（2026-09-29 需求项 2 治的同一刀）。
    """
    legs: list[tuple[str, str, int]] = []
    for scope, cap in (
        (COMMAND_SCOPE_SENDER, settings.command_sender_max_requests),
        (COMMAND_SCOPE_GROUP, settings.command_group_max_requests),
    ):
        if cap <= 0:
            continue
        if scope == COMMAND_SCOPE_GROUP and not is_group_session(message):
            continue
        value = (
            message.sender_id
            if scope == COMMAND_SCOPE_SENDER
            else str(message.group_id or message.session_id)
        )
        legs.append((scope, rate_limit_bucket_key(capability_id, scope, value), int(cap)))
    return legs


def command_leg_applies(settings: RateLimitSettings, capability_id: str) -> bool:
    """命令腿帽对这次调用是否生效（check/rollback 共用的生效集）。

    只罩非 chat 能力（＝pipeline 判 interactive 的同一口径，不新造能力清单）；
    整门 disabled 时命令腿也哑（与既有 `enabled=False` 一条总闸的语义一致）；
    两格帽都 <=0 时整腿不建账（回退旧行为）。
    """
    return bool(
        settings.enabled
        and settings.command_enabled
        and capability_id not in CHAT_CAPABILITY_IDS
        and (
            settings.command_sender_max_requests > 0
            or settings.command_group_max_requests > 0
        )
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
    """群句数帽在放行路径「已记账」的条件（rollback 用）。

    2026-09-24 裁定 3：情绪豁免不再早退零记账——豁免消息照常过句数帽并落账，
    只免最小间隔。所以 allowed 与 emotion_exempt 两条放行 reason 都命中本条件。
    """
    return bool(
        is_group_session(message)
        and (
            settings.group_hourly_max_requests > 0
            or settings.group_minute_max_requests > 0
        )
    )


# 情绪低落标签集合：命中即豁免最小间隔（"要紧的事不被节奏拖住"）。
# 2026-09-24 裁定 3：豁免面从"免句数帽"收窄为"只免最小间隔"，
# 小时/分钟额度与令牌桶对豁免消息照常生效、照常记账。
_DISTRESS_LABELS = frozenset({"support_needed", "lonely", "low_energy", "frustrated"})


def is_group_session(message: IncomingMessage) -> bool:
    """是否群聊会话（群句数帽只作用于群）。"""
    session_type = getattr(message, "session_type", None)
    value = getattr(session_type, "value", session_type)
    if str(value).strip().lower() == "group":
        return True
    return bool(getattr(message, "group_id", None))


def group_pacing_applies(settings: RateLimitSettings, message: IncomingMessage) -> bool:
    """群节奏层对这条消息是否生效：只建桶时点火（x<=0 = 整层关）、只罩群聊。

    私聊与「@ 点名/命令」流量走不到这里（``interactive_bypass`` 早退在它之前），
    这正是 T6 §伍 Q1 推荐并被采纳的口径——"每小时 x 句"只罩**非点名**流量，
    @ 必回是人格教义，不动。
    """
    return bool(
        settings.enabled
        and settings.group_pacing_tokens_per_hour > 0
        and is_group_session(message)
    )


def refilled_tokens(
    *, tokens: float, updated_at: float, now_epoch: float, per_hour: int, capacity: int
) -> float:
    """按秒回血后的令牌数（**纯函数**：只算不写，判定与落账分离＝B-1 的教训）。"""
    gained = max(0.0, now_epoch - updated_at) * (per_hour / 3600.0)
    return min(float(capacity), max(0.0, tokens) + gained)


def tokens_wait_seconds(*, available: float, needed: float, per_hour: int) -> int:
    """还差 ``needed-available`` 格令牌 ⇒ 按回血节拍还要等几秒（x 句/小时 = 每 3600/x 秒 1 格）。"""
    if per_hour <= 0 or available >= needed:
        return 0
    return max(1, math.ceil((needed - available) * 3600.0 / per_hour))


def pacing_consumption(amount: int, capacity: int) -> int:
    """一次放行扣掉几格令牌：**按桶容量封顶**。

    ``amount`` 来自 reply_budget（一条消息可拆多句外送）。若允许 amount > 容量，
    门槛永远跨不过去 ⇒ 该群从此刻起一句都发不出（参数写小只该显得迟钝，
    不该把路堵死）。
    """
    return max(1, min(int(amount), int(capacity)))


def _message_is_visual(message: IncomingMessage) -> bool:
    """图片/表情包/视频段判定：复用门禁的同一个公共谓词，不留第二份段类型副本。

    延迟导入的理由与 ``distress_exemption`` 同口径——policy 包内两个模块互引，
    放模块顶层会把 import 顺序变成硬约束。
    """
    from .gate import message_has_visual_content

    return message_has_visual_content(message)


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
        from plugins.bot_unified_runtime.domains.chat_reply.character.emotion import (
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


def emotion_interval_exemption(
    settings: RateLimitSettings, message: IncomingMessage
) -> RateLimitDecision | None:
    """情绪/好感豁免是否触发；返回豁免决定（含标签）或 None。

    2026-09-24 裁定 3：豁免只免**最小间隔**（节奏层间隔、图类独立间隔、
    target 间隔），不免任何句数额度——小时帽/分钟帽/令牌桶/session/sender/
    global 对豁免消息照常判定、照常记账（否则一条难过消息能连开 60 句）。
    覆盖面沿用既有口径、不扩大：仅群聊，且仅当至少一道群数量面（小时帽/
    分钟帽/节奏层）在运行时才询问——旧实现里豁免只在群窗判定里被咨询，
    两帽皆 0 时该判定整体不存在，豁免也无从触发。
    InMemory 与 SQLite 共用本函数：两把尺的豁免语义必须同源。
    """
    if not settings.emotion_exempt_enabled or not is_group_session(message):
        return None
    if not (
        settings.group_hourly_max_requests > 0
        or settings.group_minute_max_requests > 0
        or group_pacing_applies(settings, message)
    ):
        return None
    return distress_exemption(message)


class InMemoryRateLimiter:
    # 桶清扫间隔：只访问被命中的桶会让未再命中的桶永久滞留（键集合无界增长）。
    _SWEEP_INTERVAL_SECONDS = 600.0

    def __init__(
        self,
        settings: RateLimitSettings | Callable[[], RateLimitSettings] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        # settings 可以是静态对象，也可以是**每次判定实时求值**的 callable——
        # 后者让 /bot runtime set 改的群句数帽/情绪豁免立刻生效，而不是等重启。
        self._settings_source = settings or RateLimitSettings()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        # 节流用**单调钟**，与上面的墙钟分开，而且缺省就是 `time.monotonic`
        # ⇒ 不注入时与历史形态逐字节相同。开这一枚缝的唯一理由见 `_maybe_sweep`
        # 的注释（PX-9：清扫体 600 秒才执行一次，离线套件永不进树，
        # 体内一枚未定义名要到"重启约 10 分钟后的第一条群消息"才炸）。
        # 刻意**不**改吃 `self.clock`（墙钟）：本仓有 NTP 授时
        # （`runtime/timesync.py`，重启后 ~65s 起每 10 分钟校时），节流若吃墙钟，
        # 一次向后的校时跳变就会把清扫无限推后（键集合无界增长）——
        # 为了可测性把生产语义改差，属"变绿手段"，不做。
        self._monotonic: Callable[[], float] = monotonic or time.monotonic
        self._buckets: dict[str, deque[datetime]] = defaultdict(deque)
        # 群节奏桶的令牌状态（每群一格，键同 _buckets 命名口径）。
        self._pacing_tokens: dict[str, _TokenState] = {}
        self._last_sweep = self._monotonic()

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
        """低频清扫空/过期桶，防止长期运行下键集合无界增长。

        节流吃 `self._monotonic`（缺省 `time.monotonic`）：测试注入假单调钟即可
        把「跨过 600 秒」这一件事演出来，**600 这个业务值一字未动**。
        """
        if self._monotonic() - self._last_sweep < self._SWEEP_INTERVAL_SECONDS:
            return
        self._last_sweep = self._monotonic()
        settings = self.settings
        horizon = max(
            settings.window_seconds,
            settings.target_min_interval_seconds,
            settings.proactive_window_seconds,
            settings.group_pacing_min_interval_seconds,
            settings.group_vision_min_interval_seconds,
            PACING_MINUTE_WINDOW_SECONDS
            if settings.group_pacing_max_per_minute > 0
            else 0,
        )
        for key in list(self._buckets.keys()):
            bucket = self._buckets.get(key)  # .get 不触发 defaultdict 建桶
            if bucket is None:
                continue
            while bucket and (now - bucket[0]).total_seconds() >= horizon:
                bucket.popleft()
            if not bucket:
                del self._buckets[key]
        # 令牌桶状态：一整轮容量都没回满过（即早已封顶）就可以扔，重建成满桶
        # 与保留它在判定上等价（首见即满桶），却省一份常驻内存。
        # ⚠ 这里曾写成一枚**本作用域内不存在的名字** ``pacing``（ruff F821/mypy
        # name-defined 都抓得到，测试抓不到）：本函数只在 ``_SWEEP_INTERVAL_SECONDS``
        # （600 秒）之后才执行，而 ``_last_sweep`` 在构造时就置为当下 ⇒
        # **离线套件永远跑不到这一行，生产则在重启约 10 分钟后的第一条群消息上抛
        # NameError**。现按上面已经解析好的 ``settings`` 取数，口径不变。
        # 2026-09-24 S-W12：这条分支的可达性现在有设计过的缝（构造参数 ``monotonic``）
        # 与公开入口锁兜着 —— 旧形态只能靠手拨 `_last_sweep` 再**直调本私有方法**，
        # 一旦将来新增一条不经过清扫的公开路径，那把锁会照样绿。
        idle_cap_seconds = (
            3600.0 * max(1, settings.group_pacing_burst_capacity)
            / max(1, settings.group_pacing_tokens_per_hour)
            if settings.group_pacing_tokens_per_hour > 0
            else 0.0
        )
        if idle_cap_seconds > 0:
            now_epoch = now.timestamp()
            for key in list(self._pacing_tokens.keys()):
                state = self._pacing_tokens.get(key)
                if state is None:
                    continue
                if now_epoch - state.updated_at >= idle_cap_seconds:
                    del self._pacing_tokens[key]

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
        # E05 缺口二 · 命令腿帽必须在两条早退腿（interactive_bypass /
        # non_chat_capability）**之前**：只挡其中一条，将来 E06 一改
        # `capability_id != "bot.chat"` 那句判据，命令就会从另一条腿漏出去。
        # R3 点名最小间隔仍在最前（A-04 序不动）。
        command_decision = self._check_command_leg(
            message, capability_id, max(1, int(amount))
        )
        if command_decision is not None:
            return command_decision
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
        # 判定与落账分离（B-1 根修，2026-09-24 T7）：每一条帽只负责"判"，判定通过
        # 时把**该帽要写的账**登记进 commits；只有全部帽都放行才统一执行。
        # 旧序是群窗口先判先记、之后才轮到 target/session/sender 帽拒绝 ⇒
        # 一句都没回的消息照样占掉群小时额度（T6 实测 22 真回占满 30 额度）。
        commits: list[Callable[[], None]] = []
        # 情绪/好感豁免（2026-09-24 裁定 3）：只免最小间隔、不免句数额度。
        # 判一次、把结果透传给节奏层与 target 间隔门；句数帽照常判定照常记账。
        exemption = emotion_interval_exemption(self.settings, message)
        interval_exempt = exemption is not None
        # 群聊专属句数帽（用户口径：每小时 60 句、每分钟 3 句）。
        group_limited = self._evaluate_group_windows(
            capability_id, message, now, safe_amount, commits
        )
        if group_limited is not None:
            return group_limited
        pacing_limited = self._evaluate_group_pacing(
            capability_id, message, now, safe_amount, commits,
            interval_exempt=interval_exempt,
        )
        if pacing_limited is not None:
            return pacing_limited
        target_key = self._target_bucket_key(capability_id, message)
        # target 最小间隔也是"间隔"：豁免时放行，但下面照常落一格时间戳
        #（豁免只救这一条消息自己，不给后续消息铺路）。
        if self.settings.target_min_interval_seconds > 0 and not interval_exempt:
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

        for commit in commits:
            commit()
        for _scope, key, _limit in scoped_buckets:
            bucket = self._buckets[key]
            for _ in range(safe_amount):
                bucket.append(now)
        if self.settings.target_min_interval_seconds > 0:
            self._buckets[target_key].append(now)

        if exemption is not None:
            # 裁定 3 后豁免是"全额记账的放行"，reason 保留 emotion_exempt
            # 供审计识别，rollback 按 _FULL_RECORD_REASONS 对称退还。
            return RateLimitDecision(
                allowed=True,
                reason="emotion_exempt",
                audit_tags=[*exemption.audit_tags, "rate_limit:ok"],
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
        if reason in _COMMAND_RECORD_CARRYING_REASONS:
            # 命令腿只写过 command_* 两格（chat 桶一格没动），退还必须同键同格：
            # 走 check 侧同一个 `command_leg_buckets`，禁第二份键形。
            for _scope, key, _cap in command_leg_buckets(
                self.settings, capability_id, message
            ):
                self._pop_recent(self._buckets.get(key), safe_amount)
            return
        if reason != "proactive_allowed" and (
            reason not in _FULL_RECORD_REASONS
            and reason not in _R3_RECORD_CARRYING_REASONS
        ):
            return
        if _sender_interval_record_applies(self.settings, message, capability_id):
            self._pop_recent(
                self._buckets.get(self._sender_interval_key(capability_id, message)),
                1,
            )
        if reason not in _FULL_RECORD_REASONS:
            return
        if _group_windows_record_applies(self.settings, message):
            group_key = str(message.group_id or message.session_id)
            for scope in ("group_hour", "group_minute"):
                # 镜像 _evaluate_group_windows 的 active 判定：帽 <=0 的窗口没记账。
                if scope == "group_hour" and self.settings.group_hourly_max_requests <= 0:
                    continue
                if scope == "group_minute" and self.settings.group_minute_max_requests <= 0:
                    continue
                self._pop_recent(
                    self._buckets.get(self._bucket_key(capability_id, scope, group_key)),
                    safe_amount,
                )
        if group_pacing_applies(self.settings, message):
            self._rollback_group_pacing(capability_id, message, safe_amount)
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
        return sender_interval_ledger_key(
            capability_id, message.sender_id, str(message.group_id or "")
        )

    def _check_sender_min_interval(
        self, message: IncomingMessage, capability_id: str, now: datetime
    ) -> RateLimitDecision | None:
        bucket = self._buckets[self._sender_interval_key(capability_id, message)]
        if bucket:
            elapsed = (now - bucket[-1]).total_seconds()
            interval = self.settings.chat_sender_min_interval_seconds
            if elapsed < interval:
                retry_after = interval_wait_seconds(interval, elapsed)
                decision = RateLimitDecision(
                    allowed=False,
                    reason="sender_min_interval",
                    retry_after_seconds=retry_after,
                    audit_tags=["rate_limit:blocked", "rate_limit:sender_min_interval"],
                )
                # 排队账本（第 2 项 B 路根修）：同人同轮多条被拦的消息如果都
                # 约在同一解禁瞬间，头一条通过会把冷却钟重新拨走、其余当场再
                # 被拦且补回额度只有 1 次 ⇒ 集体陪葬。拒绝即登记（debug_id
                # 与交出的 decision 同枚——读侧按它精确认领），后到的排队
                # 位自动让开一个完整间隔。
                redrive_ledger.reserve_slot(
                    sender_interval_ledger_key(
                        capability_id, message.sender_id, str(message.group_id or "")
                    ),
                    debug_id=decision.debug_id,
                    now=now.timestamp(),
                    base_wait=float(retry_after),
                    interval_seconds=float(interval),
                )
                return decision
        # 放行。补回到访的那一条（redrive_count≥1）消耗最早成熟的预留，并把
        # 冷却钟拨到 max(now, 回位时刻)——"占坑即销"：比回位早醒也要占掉这个
        # 槽位，否则同人下一条会挤进同一格；槽位销账后不留幽灵槽推后新人
        # （test_stale_slot_never_inflates_a_later_question 锁死两头）。
        advanced_to = self._consume_redrive_slot(message, capability_id, now)
        bucket.append(advanced_to if advanced_to is not None else now)
        return None

    @staticmethod
    def _consume_redrive_slot(
        message: IncomingMessage, capability_id: str, now: datetime
    ) -> datetime | None:
        """补回到访放行时销账并回交应拨到的冷却钟时刻（无需移动时 None）。"""
        if int(getattr(message, "redrive_count", 0) or 0) < 1:
            return None
        slot = redrive_ledger.consume_earliest_matured(
            sender_interval_ledger_key(
                capability_id, message.sender_id, str(message.group_id or "")
            ),
            now=now.timestamp(),
        )
        if slot is None or slot <= now.timestamp():
            return None
        return now + timedelta(seconds=slot - now.timestamp())

    def _check_command_leg(
        self, message: IncomingMessage, capability_id: str, safe_amount: int
    ) -> RateLimitDecision | None:
        """命令腿分钟帽（InMemory 版），判定与落账同在一处、先判后记。

        返回 None＝本腿不适用（chat 能力／整门哑／旁路脸／帽为 0），调用侧照旧走
        既有早退腿；返回 decision＝本腿已判完并记完账 ⇒ 命令流量**不进** chat 句数
        账（两本账，见 `_COMMAND_RECORD_CARRYING_REASONS` 与 rollback 的对称退还）。
        """
        settings = self.settings
        if not command_leg_applies(settings, capability_id):
            return None
        if self._has_command_bypass_role(message):
            return None
        legs = command_leg_buckets(settings, capability_id, message)
        if not legs:
            return None
        now = self.clock()
        self._maybe_sweep(now)
        window = max(1, settings.command_window_seconds)
        for _scope, key, _cap in legs:
            self._prune_window(self._buckets[key], now, window)
        for _scope, key, cap in legs:
            bucket = self._buckets[key]
            if len(bucket) + safe_amount > cap:
                return RateLimitDecision(
                    allowed=False,
                    reason="command_rate_limited",
                    retry_after_seconds=self._window_retry_after(bucket, now, window),
                    audit_tags=[
                        "rate_limit:blocked",
                        f"rate_limit:{_scope}_exceeded",
                    ],
                )
        for _scope, key, _cap in legs:
            bucket = self._buckets[key]
            for _ in range(safe_amount):
                bucket.append(now)
        return RateLimitDecision(
            allowed=True,
            reason="command_allowed",
            audit_tags=["rate_limit:command_allowed"],
        )

    def _has_command_bypass_role(self, message: IncomingMessage) -> bool:
        """命令腿旁路脸（缺省 ["admin"]，超管经 roles.py 叠 admin）——管理员自救通道。"""
        bypass_roles = set(self.settings.command_bypass_roles)
        return any(role.strip().lower() in bypass_roles for role in message.sender_roles)

    def _prune_window(self, bucket: deque[datetime], now: datetime, window: int) -> None:
        """按指定窗口清扫（`_prune` 只会读 chat 的 window_seconds，命令帽另有窗）。"""
        while bucket and (now - bucket[0]).total_seconds() >= window:
            bucket.popleft()

    def _window_retry_after(self, bucket: deque[datetime], now: datetime, window: int) -> int:
        if not bucket:
            return window
        elapsed = int((now - bucket[0]).total_seconds())
        return max(1, window - elapsed)

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
                    retry_after_seconds=interval_wait_seconds(
                        self.settings.proactive_group_cooldown_seconds, elapsed
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

    def _evaluate_group_windows(
        self,
        capability_id: str,
        message: IncomingMessage,
        now: datetime,
        amount: int,
        commits: list[Callable[[], None]],
    ) -> RateLimitDecision | None:
        """群聊每小时/每分钟滑动窗口判定；**只判不记**，通过后登记落账动作给 commits。

        只作用于群聊；两个窗口任一超限即拒绝（拒绝时一格都不写，见 B-1 根修说明）。
        情绪豁免命中即放行且不记账——覆盖面按既有口径不变（只免群帽）。
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

        def _commit() -> None:
            for _scope, bucket, _limit, _window in active:
                for _ in range(amount):
                    bucket.append(now)

        commits.append(_commit)
        return None

    def _evaluate_group_pacing(
        self,
        capability_id: str,
        message: IncomingMessage,
        now: datetime,
        amount: int,
        commits: list[Callable[[], None]],
        *,
        interval_exempt: bool = False,
    ) -> RateLimitDecision | None:
        """群节奏层（令牌桶 + 分钟帽 + 最小间隔，含图类独立间隔）判定：**只判不记**。

        与 ``_evaluate_group_windows`` 同一套哲学——通过时把落账动作登记给
        ``commits``，由调用方在**全部帽都放行之后**统一执行；任一帽拒绝则一格不写
        （B-1 幽灵扣减的根修口径，节奏层自己也不许再犯一次）。
        顺序：间隔位（图类那道先判、文字那道后判——宽者先判才能让
        ``retry_after_seconds`` 报真正卡住的那道，而不是预告 20 秒后再撞第二次）
        → 分钟帽 → 令牌桶（先便宜后贵，且被拦原因更贴近用户感受）。
        图类间隔不是第 4 层：它与文字间隔同在间隔位、同用一条帽、共用同一个
        ``_message_is_visual`` 谓词，只是各自一格账（scope 不同）。
        """
        settings = self.settings
        if not group_pacing_applies(settings, message):
            return None
        group_key = str(message.group_id or message.session_id)
        now_epoch = now.timestamp()
        capacity = settings.group_pacing_burst_capacity
        needed = pacing_consumption(amount, capacity)

        interval = settings.group_pacing_min_interval_seconds
        last_key = self._bucket_key(capability_id, PACING_SCOPE_LAST, group_key)
        # 图类独立间隔（用户裁定「图片 120 秒」）。判定/记账/退账三面共用同一枚
        # ``_message_is_visual`` 谓词（真身在 policy/gate.py 的
        # ``message_has_visual_content``），本处不写第二套段类型判据。
        # ⚠ ``vision_interval > 0`` 写在 ``and`` 左边是有意的短路：参数为 0 时连谓词
        # 都不调用 ⇒ 整层惰性、逐字节回到本格落地前的形态。
        vision_interval = settings.group_vision_min_interval_seconds
        visual = vision_interval > 0 and _message_is_visual(message)
        # 取 max：图类间隔不窄于文字间隔。两条帽各自成账（不同 scope），max 不会
        # 让文字间隔变宽；反过来若把图配得比文字还窄，这道门自然由文字间隔兜住。
        vision_gap = max(interval, vision_interval) if visual else 0
        vision_key = self._bucket_key(capability_id, PACING_SCOPE_VISION_LAST, group_key)
        # 宽者先判：这样 retry_after_seconds 报的是真正卡住的那道，而不是让调用方
        # 按 20 秒白等一轮、再被 120 秒那道第二次拦下（预告失真）。
        if visual and not interval_exempt:
            vision_bucket = self._buckets[vision_key]
            while vision_bucket and (
                now - vision_bucket[0]
            ).total_seconds() >= vision_gap:
                vision_bucket.popleft()
            if vision_bucket:
                vision_elapsed = (now - vision_bucket[-1]).total_seconds()
                return RateLimitDecision(
                    allowed=False,
                    reason="group_pacing_vision_min_interval",
                    retry_after_seconds=interval_wait_seconds(vision_gap, vision_elapsed),
                    audit_tags=[
                        "rate_limit:blocked",
                        "rate_limit:group_pacing_vision_min_interval",
                    ],
                )
        if interval > 0 and not interval_exempt:
            last = self._buckets[last_key]
            while last and (now - last[0]).total_seconds() >= interval:
                last.popleft()
            if last:
                elapsed = (now - last[-1]).total_seconds()
                return RateLimitDecision(
                    allowed=False,
                    reason="group_pacing_min_interval",
                    retry_after_seconds=interval_wait_seconds(interval, elapsed),
                    audit_tags=[
                        "rate_limit:blocked",
                        "rate_limit:group_pacing_min_interval",
                    ],
                )

        minute_limit = settings.group_pacing_max_per_minute
        minute_key = self._bucket_key(capability_id, PACING_SCOPE_MINUTE, group_key)
        if minute_limit > 0:
            minute_bucket = self._buckets[minute_key]
            while minute_bucket and (
                now - minute_bucket[0]
            ).total_seconds() >= PACING_MINUTE_WINDOW_SECONDS:
                minute_bucket.popleft()
            if len(minute_bucket) + needed > minute_limit:
                elapsed_oldest = (now - minute_bucket[0]).total_seconds()
                return RateLimitDecision(
                    allowed=False,
                    reason="group_pacing_minute_exceeded",
                    retry_after_seconds=interval_wait_seconds(
                        PACING_MINUTE_WINDOW_SECONDS, elapsed_oldest
                    ),
                    audit_tags=[
                        "rate_limit:blocked",
                        "rate_limit:group_pacing_minute_exceeded",
                    ],
                )

        state = self._pacing_tokens.get(
            self._bucket_key(capability_id, PACING_SCOPE_TOKENS, group_key)
        )
        # 首见即满桶：开局最多连发 B 句，之后按 3600/x 秒一句回血（"绝不瞬间打光"）。
        available = (
            float(capacity)
            if state is None
            else refilled_tokens(
                tokens=state.tokens,
                updated_at=state.updated_at,
                now_epoch=now_epoch,
                per_hour=settings.group_pacing_tokens_per_hour,
                capacity=capacity,
            )
        )
        if available + 1e-9 < needed:
            return RateLimitDecision(
                allowed=False,
                reason="group_pacing_tokens_exhausted",
                retry_after_seconds=tokens_wait_seconds(
                    available=available,
                    needed=float(needed),
                    per_hour=settings.group_pacing_tokens_per_hour,
                ),
                audit_tags=[
                    "rate_limit:blocked",
                    "rate_limit:group_pacing_tokens_exhausted",
                ],
            )

        def _commit() -> None:
            token_key = self._bucket_key(
                capability_id, PACING_SCOPE_TOKENS, group_key
            )
            current = self._pacing_tokens.get(token_key)
            if current is None:
                current = _TokenState(tokens=float(capacity), updated_at=now_epoch)
                self._pacing_tokens[token_key] = current
            current.tokens = max(0.0, available - needed)
            current.updated_at = now_epoch
            if minute_limit > 0:
                bucket = self._buckets[minute_key]
                for _ in range(needed):
                    bucket.append(now)
            if interval > 0:
                last_bucket = self._buckets[last_key]
                last_bucket.clear()  # 只留"上一句"一格：间隔判定不需要历史
                last_bucket.append(now)
            if visual:
                # 图类那一格的账。条件与退账侧（``_rollback_group_pacing``）逐字同形
                # （``vision_interval > 0 ∧ 含视觉段``），否则退账退错桶。
                # 豁免只免"判"、不免"记"——与上面文字间隔同一语义：被豁免的这一句
                # 照样把图类钟拨走，别人下一句该等还得等。
                vision_bucket = self._buckets[vision_key]
                vision_bucket.clear()
                vision_bucket.append(now)

        commits.append(_commit)
        return None

    def _rollback_group_pacing(
        self, capability_id: str, message: IncomingMessage, amount: int
    ) -> None:
        """退掉一次节奏记账（A-18）：令牌按容量封顶退回，分钟/间隔戳各回一格。

        与 check 侧共用同一套 scope 命名与"上一句只留一格"的语义；多退一格的方向
        是放宽（与 ``_pop_recent`` 既有取舍同口径），不会误拦别人。
        """
        settings = self.settings
        group_key = str(message.group_id or message.session_id)
        needed = pacing_consumption(amount, settings.group_pacing_burst_capacity)
        if settings.group_pacing_max_per_minute > 0:
            self._pop_recent(
                self._buckets.get(
                    self._bucket_key(capability_id, PACING_SCOPE_MINUTE, group_key)
                ),
                needed,
            )
        if settings.group_pacing_min_interval_seconds > 0:
            self._pop_recent(
                self._buckets.get(
                    self._bucket_key(capability_id, PACING_SCOPE_LAST, group_key)
                ),
                1,
            )
        if settings.group_vision_min_interval_seconds > 0 and _message_is_visual(message):
            self._pop_recent(
                self._buckets.get(
                    self._bucket_key(
                        capability_id, PACING_SCOPE_VISION_LAST, group_key
                    )
                ),
                1,
            )
        state = self._pacing_tokens.get(
            self._bucket_key(capability_id, PACING_SCOPE_TOKENS, group_key)
        )
        if state is None:
            return
        now_epoch = self.clock().timestamp()
        available = refilled_tokens(
            tokens=state.tokens,
            updated_at=state.updated_at,
            now_epoch=now_epoch,
            per_hour=settings.group_pacing_tokens_per_hour,
            capacity=settings.group_pacing_burst_capacity,
        )
        state.tokens = min(
            float(settings.group_pacing_burst_capacity), available + needed
        )
        state.updated_at = now_epoch

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
        settings: RateLimitSettings | Callable[[], RateLimitSettings] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        # settings 与 InMemory 版同型：静态对象或**每轮现读**的 callable。
        # 旧装配口把 callable 当场烘成快照（"SQLite 版不支持热改"的根因，
        # AGENTS 台账 #3 限流面），现在原样透传——/bot runtime set 改的
        # 冷却窗口/句数帽在重启前就到得了 SQLite 这一把尺。
        self._settings_source = settings or RateLimitSettings()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        # 与 InMemory 同一枚缝、同一套理由（见 InMemoryRateLimiter.__init__）。
        # 缺省 `time.monotonic` ⇒ 生产逐字节现状。注意 `_last_cleanup` **保持 0.0**
        # （首访即清，历史语义）——把它改成"当下"会让清理推迟 300 秒，是行为变更，
        # 本席不动；测试要驱动它就把假单调钟往前拨。
        self._monotonic: Callable[[], float] = monotonic or time.monotonic
        # APScheduler 线程与事件循环并发调用 check：进程内锁串行化，
        # 跨进程并发由 SQLite 文件锁 + busy_timeout 兜底，避免
        # "database is locked" 直接变成用户可见失败。
        self._lock = threading.Lock()
        self._last_cleanup = 0.0

    @property
    def settings(self) -> RateLimitSettings:
        """当前限流设置（callable 时实时求值；失败回退默认，保持限流不放开）。

        与 ``InMemoryRateLimiter.settings`` 逐字同语义——两把尺的热改面是同一件事，
        任何一把独走都会让「/bot runtime set」按注入路径给出两种答案。
        """
        source = self._settings_source
        if callable(source):
            try:
                resolved = source()
            except Exception:  # noqa: BLE001 - 求值失败回退默认设置。
                return RateLimitSettings()
            return resolved if isinstance(resolved, RateLimitSettings) else RateLimitSettings()
        return source

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
        # E05 缺口二 · 命令腿帽先于两条早退腿（与 InMemory 同序同语义；生产走
        # SQLite，只补内存版＝第二基线假绿）。
        command_decision = self._check_command_leg(
            message, capability_id, max(1, int(amount))
        )
        if command_decision is not None:
            return command_decision
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
        key = sender_interval_ledger_key(
            capability_id, message.sender_id, str(message.group_id or "")
        )
        with closing(self._connect()) as connection, connection:
            self._cleanup_expired(connection, now_epoch)
            latest = self._latest_created_at(connection, key)
            if latest is not None:
                elapsed = now_epoch - latest
                interval = self.settings.chat_sender_min_interval_seconds
                if elapsed < interval:
                    retry_after = interval_wait_seconds(interval, elapsed)
                    decision = RateLimitDecision(
                        allowed=False,
                        reason="sender_min_interval",
                        retry_after_seconds=retry_after,
                        audit_tags=[
                            "rate_limit:blocked",
                            "rate_limit:sender_min_interval",
                        ],
                    )
                    # 排队账本：与 InMemory 版同一本、同一键形、同一语义
                    # （拒绝即登记，读侧按 decision.debug_id 精确认领）。
                    redrive_ledger.reserve_slot(
                        key,
                        debug_id=decision.debug_id,
                        now=now_epoch,
                        base_wait=float(retry_after),
                        interval_seconds=float(interval),
                    )
                    return decision
            insert_epoch = now_epoch
            if int(getattr(message, "redrive_count", 0) or 0) >= 1:
                # 补回到访放行：销掉最早成熟的预留；若比回位时刻早醒，把记账
                # 点拨到回位时刻（占坑即销，与 InMemory 同语义）。
                slot = redrive_ledger.consume_earliest_matured(key, now=now_epoch)
                if slot is not None and slot > now_epoch:
                    insert_epoch = slot
            connection.execute(
                "INSERT INTO rate_limit_events (bucket_key, created_at) VALUES (?, ?)",
                (key, insert_epoch),
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
            # 判定与落账分离（B-1 根修，与 InMemory 同序同语义）：群句数帽/target
            # /session/sender 各帽全部只判，通过者把要写的账登记进 commits；
            # 任一帽拒绝 ⇒ 一格都不写。
            commits: list[Callable[[], None]] = []
            # 豁免判一次、透传给节奏层与 target 间隔门，与 InMemory 同源同语义
            # （裁定 3：只免最小间隔，句数帽照常判定照常记账）。
            exemption = emotion_interval_exemption(self.settings, message)
            interval_exempt = exemption is not None
            # 群聊专属句数帽（语义对齐 InMemoryRateLimiter._evaluate_group_windows）：
            # 豁免/拒绝都直接返回、不写入任何桶。
            group_limited = self._evaluate_group_windows(
                connection, message, capability_id, now_epoch, safe_amount, commits
            )
            if group_limited is not None:
                return group_limited
            pacing_limited = self._evaluate_group_pacing(
                connection,
                message,
                capability_id,
                now_epoch,
                safe_amount,
                commits,
                interval_exempt=interval_exempt,
            )
            if pacing_limited is not None:
                return pacing_limited
            if self.settings.target_min_interval_seconds > 0 and not interval_exempt:
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

            for commit in commits:
                commit()
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
        refund: tuple[str, int] | None = None
        if reason in _COMMAND_RECORD_CARRYING_REASONS:
            # 命令腿的对称退还（与 InMemory 版同判据、同键形）：只弹 command_* 两格，
            # 每格 safe_amount；chat 桶在命令路径从未写过，故一律不碰。
            deletes.extend(
                (key, safe_amount)
                for _scope, key, _cap in command_leg_buckets(
                    self.settings, capability_id, message
                )
            )
            self._apply_deletes(deletes)
            return
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
                        # 与 check 侧同键形（含 group 腿，2026-09-29 需求项 2）：
                        # 退账退错桶＝冷却钟白占一格，同人同群下一条被多拦一次。
                        sender_interval_ledger_key(
                            capability_id,
                            message.sender_id,
                            str(message.group_id or ""),
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
            if group_pacing_applies(self.settings, message):
                deletes.extend(self._group_pacing_rollback_deletes(message, capability_id, safe_amount))
                refund = (
                    self._bucket_key(
                        capability_id,
                        PACING_SCOPE_TOKENS,
                        str(message.group_id or message.session_id),
                    ),
                    pacing_consumption(
                        safe_amount, self.settings.group_pacing_burst_capacity
                    ),
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
        if not deletes and refund is None:
            return
        self._apply_deletes(deletes, refund=refund)

    def _group_pacing_rollback_deletes(
        self, message: IncomingMessage, capability_id: str, amount: int
    ) -> list[tuple[str, int]]:
        """节奏层**事件侧**退账（SQLite 版），与 InMemory ``_rollback_group_pacing`` 同条同款。

        三个 scope 名与 InMemory 逐字一致（同一把尺的两面）：分钟帽退 ``needed`` 格、
        最小间隔退 1 格（"上一句"只留一格）、图类独立间隔仅在该消息确实含视觉段时退。
        方向与 InMemory 同：宁可多退一格（放宽），不可少退（误拦别人）。
        令牌本身**不在这张表里**，由调用方带 ``refund`` 走 ``_refund_pacing_state``。
        """
        settings = self.settings
        group_key = str(message.group_id or message.session_id)
        needed = pacing_consumption(amount, settings.group_pacing_burst_capacity)
        deletes: list[tuple[str, int]] = []
        if settings.group_pacing_max_per_minute > 0:
            deletes.append(
                (self._bucket_key(capability_id, PACING_SCOPE_MINUTE, group_key), needed)
            )
        if settings.group_pacing_min_interval_seconds > 0:
            deletes.append(
                (self._bucket_key(capability_id, PACING_SCOPE_LAST, group_key), 1)
            )
        if settings.group_vision_min_interval_seconds > 0 and _message_is_visual(message):
            deletes.append(
                (
                    self._bucket_key(capability_id, PACING_SCOPE_VISION_LAST, group_key),
                    1,
                )
            )
        return deletes

    def _apply_deletes(
        self, deletes: list[tuple[str, int]], *, refund: tuple[str, int] | None = None
    ) -> None:
        with self._lock:
            self._ensure_schema()
            with closing(self._connect()) as connection, connection:
                for bucket_key, count in deletes:
                    self._delete_latest(connection, bucket_key, count)
                if refund is not None:
                    # 令牌桶是**另一张表**（rate_limit_pacing_tokens），不在事件流里。
                    # 旧代码把 refund 算出来却从不消费 ⇒ "拒绝要退还额度"这条裁定
                    # 在 SQLite 侧等于没做（InMemory 侧一直是做的）。
                    refund_key, refund_amount = refund
                    self._refund_pacing_state(
                        connection,
                        refund_key,
                        amount=float(refund_amount),
                        now_epoch=self.clock().timestamp(),
                        per_hour=self.settings.group_pacing_tokens_per_hour,
                        capacity=self.settings.group_pacing_burst_capacity,
                    )

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

    def _check_command_leg(
        self, message: IncomingMessage, capability_id: str, safe_amount: int
    ) -> RateLimitDecision | None:
        """命令腿分钟帽（SQLite 版，生产真身），与 InMemory 同序同语义同桶键。

        先判后记：任一格超帽 ⇒ 一格都不写（同一事务内判定与插入，拒绝直接返回）。
        返回 None＝本腿不适用，调用侧照旧走既有早退腿。
        """
        settings = self.settings
        if not command_leg_applies(settings, capability_id):
            return None
        if self._has_command_bypass_role(message):
            return None
        legs = command_leg_buckets(settings, capability_id, message)
        if not legs:
            return None
        window = max(1, settings.command_window_seconds)
        with self._lock:
            self._ensure_schema()
            now_epoch = self.clock().timestamp()
            cutoff_epoch = now_epoch - window
            with closing(self._connect()) as connection, connection:
                self._cleanup_expired(connection, now_epoch)
                for _scope, key, _cap in legs:
                    self._prune(connection, key, cutoff_epoch)
                for _scope, key, cap in legs:
                    if self._count(connection, key) + safe_amount > cap:
                        return RateLimitDecision(
                            allowed=False,
                            reason="command_rate_limited",
                            retry_after_seconds=self._window_retry_after_seconds(
                                connection, key, now_epoch, window
                            ),
                            audit_tags=[
                                "rate_limit:blocked",
                                f"rate_limit:{_scope}_exceeded",
                            ],
                        )
                for _scope, key, _cap in legs:
                    connection.executemany(
                        """
                        INSERT INTO rate_limit_events (bucket_key, created_at)
                        VALUES (?, ?)
                        """,
                        [(key, now_epoch) for _ in range(safe_amount)],
                    )
        return RateLimitDecision(
            allowed=True,
            reason="command_allowed",
            audit_tags=["rate_limit:command_allowed"],
        )

    def _has_command_bypass_role(self, message: IncomingMessage) -> bool:
        """命令腿旁路脸（与 InMemory 同款，缺省 ["admin"]＝管理员自救通道）。"""
        bypass_roles = set(self.settings.command_bypass_roles)
        return any(role.strip().lower() in bypass_roles for role in message.sender_roles)

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
                            retry_after_seconds=interval_wait_seconds(
                                self.settings.proactive_group_cooldown_seconds,
                                elapsed,
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

    def _evaluate_group_windows(
        self,
        connection: sqlite3.Connection,
        message: IncomingMessage,
        capability_id: str,
        now_epoch: float,
        amount: int,
        commits: list[Callable[[], None]],
    ) -> RateLimitDecision | None:
        """群聊每小时/每分钟滑动窗口判定（SQLite 版，语义对齐 InMemory 实现）。

        只作用于群聊；两个窗口任一超限即拒绝且不记账（**只判不记**，见 B-1 根修）；
        情绪低落豁免命中时直接放行，同样不记账。判定通过时把时间戳行的写入登记进
        commits，由调用方在全部帽都放行后统一执行。
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

        rows = [
            (bucket_key, now_epoch)
            for _scope, bucket_key, _limit, _window in active
            for _ in range(amount)
        ]

        def _commit() -> None:
            connection.executemany(
                """
                INSERT INTO rate_limit_events (bucket_key, created_at)
                VALUES (?, ?)
                """,
                rows,
            )

        commits.append(_commit)
        return None

    def _evaluate_group_pacing(
        self,
        connection: sqlite3.Connection,
        message: IncomingMessage,
        capability_id: str,
        now_epoch: float,
        amount: int,
        commits: list[Callable[[], None]],
        *,
        interval_exempt: bool = False,
    ) -> RateLimitDecision | None:
        """群节奏层（SQLite 版）：**只判不记**，与 InMemory 同序同算术。

        间隔/分钟帽用既有事件表（scope 与 InMemory 同名），令牌状态单独一行；
        判定通过的账登记进 commits，由调用方在全部帽放行后统一写。
        """
        settings = self.settings
        if not group_pacing_applies(settings, message):
            return None
        group_key = str(message.group_id or message.session_id)
        capacity = settings.group_pacing_burst_capacity
        needed = pacing_consumption(amount, capacity)

        interval = settings.group_pacing_min_interval_seconds
        last_key = self._bucket_key(capability_id, PACING_SCOPE_LAST, group_key)
        # 图类独立间隔（SQLite 版）：与 InMemory 同条同算术同顺序（宽者先判）。
        # 谓词短路方向也一致——参数为 0 时不调用 ``_message_is_visual``。
        vision_interval = settings.group_vision_min_interval_seconds
        visual = vision_interval > 0 and _message_is_visual(message)
        vision_gap = max(interval, vision_interval) if visual else 0
        vision_key = self._bucket_key(capability_id, PACING_SCOPE_VISION_LAST, group_key)
        if visual and not interval_exempt:
            self._prune(connection, vision_key, now_epoch - vision_gap)
            latest_vision = self._latest_created_at(connection, vision_key)
            if latest_vision is not None:
                return RateLimitDecision(
                    allowed=False,
                    reason="group_pacing_vision_min_interval",
                    retry_after_seconds=interval_wait_seconds(
                        vision_gap, now_epoch - latest_vision
                    ),
                    audit_tags=[
                        "rate_limit:blocked",
                        "rate_limit:group_pacing_vision_min_interval",
                    ],
                )
        if interval > 0 and not interval_exempt:
            self._prune(connection, last_key, now_epoch - interval)
            latest = self._latest_created_at(connection, last_key)
            if latest is not None:
                return RateLimitDecision(
                    allowed=False,
                    reason="group_pacing_min_interval",
                    retry_after_seconds=interval_wait_seconds(
                        interval, now_epoch - latest
                    ),
                    audit_tags=[
                        "rate_limit:blocked",
                        "rate_limit:group_pacing_min_interval",
                    ],
                )

        minute_limit = settings.group_pacing_max_per_minute
        minute_key = self._bucket_key(capability_id, PACING_SCOPE_MINUTE, group_key)
        if minute_limit > 0:
            self._prune(
                connection, minute_key, now_epoch - PACING_MINUTE_WINDOW_SECONDS
            )
            if self._count(connection, minute_key) + needed > minute_limit:
                oldest = self._oldest_created_at(connection, minute_key)
                elapsed_oldest = (
                    now_epoch - oldest if oldest is not None else 0.0
                )
                return RateLimitDecision(
                    allowed=False,
                    reason="group_pacing_minute_exceeded",
                    retry_after_seconds=interval_wait_seconds(
                        PACING_MINUTE_WINDOW_SECONDS, elapsed_oldest
                    ),
                    audit_tags=[
                        "rate_limit:blocked",
                        "rate_limit:group_pacing_minute_exceeded",
                    ],
                )

        token_key = self._bucket_key(capability_id, PACING_SCOPE_TOKENS, group_key)
        state = self._read_pacing_state(connection, token_key)
        # 首见即满桶（与 InMemory 同一条教义：开局最多连发 B 句，之后按节拍回血）。
        available = (
            float(capacity)
            if state is None
            else refilled_tokens(
                tokens=state.tokens,
                updated_at=state.updated_at,
                now_epoch=now_epoch,
                per_hour=settings.group_pacing_tokens_per_hour,
                capacity=capacity,
            )
        )
        if available + 1e-9 < needed:
            return RateLimitDecision(
                allowed=False,
                reason="group_pacing_tokens_exhausted",
                retry_after_seconds=tokens_wait_seconds(
                    available=available,
                    needed=float(needed),
                    per_hour=settings.group_pacing_tokens_per_hour,
                ),
                audit_tags=[
                    "rate_limit:blocked",
                    "rate_limit:group_pacing_tokens_exhausted",
                ],
            )

        def _commit() -> None:
            self._write_pacing_state(
                connection, token_key, max(0.0, available - needed), now_epoch
            )
            if minute_limit > 0:
                connection.executemany(
                    """
                    INSERT INTO rate_limit_events (bucket_key, created_at)
                    VALUES (?, ?)
                    """,
                    [(minute_key, now_epoch) for _ in range(needed)],
                )
            if interval > 0:
                # 只留"上一句"一格：与 InMemory 的 clear()+append() 同语义。
                connection.execute(
                    "DELETE FROM rate_limit_events WHERE bucket_key = ?",
                    (last_key,),
                )
                connection.execute(
                    """
                    INSERT INTO rate_limit_events (bucket_key, created_at)
                    VALUES (?, ?)
                    """,
                    (last_key, now_epoch),
                )
            if visual:
                # 图类那一格的账（SQLite 版）：DELETE-then-INSERT 一格，与 InMemory
                # 的 clear()+append() 同语义；条件与退账侧
                # ``_group_pacing_rollback_deletes`` 逐字同形。豁免同样只免判不免记。
                connection.execute(
                    "DELETE FROM rate_limit_events WHERE bucket_key = ?",
                    (vision_key,),
                )
                connection.execute(
                    """
                    INSERT INTO rate_limit_events (bucket_key, created_at)
                    VALUES (?, ?)
                    """,
                    (vision_key, now_epoch),
                )

        commits.append(_commit)
        return None

    def _read_pacing_state(
        self, connection: sqlite3.Connection, bucket_key: str
    ) -> _TokenState | None:
        cursor = connection.execute(
            "SELECT tokens, updated_at FROM rate_limit_pacing_tokens WHERE bucket_key = ?",
            (bucket_key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return _TokenState(tokens=float(row[0]), updated_at=float(row[1]))

    def _write_pacing_state(
        self,
        connection: sqlite3.Connection,
        bucket_key: str,
        tokens: float,
        updated_at: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO rate_limit_pacing_tokens (bucket_key, tokens, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(bucket_key) DO UPDATE SET
                tokens = excluded.tokens,
                updated_at = excluded.updated_at
            """,
            (bucket_key, tokens, updated_at),
        )

    def _refund_pacing_state(
        self,
        connection: sqlite3.Connection,
        bucket_key: str,
        *,
        amount: float,
        now_epoch: float,
        per_hour: int,
        capacity: int,
    ) -> None:
        """回滚时把令牌退回去（先按节拍补算到当下，再封顶在容量内）。"""
        state = self._read_pacing_state(connection, bucket_key)
        if state is None:
            return
        available = refilled_tokens(
            tokens=state.tokens,
            updated_at=state.updated_at,
            now_epoch=now_epoch,
            per_hour=per_hour,
            capacity=capacity,
        )
        self._write_pacing_state(
            connection,
            bucket_key,
            min(float(capacity), available + max(0.0, amount)),
            now_epoch,
        )

    def _oldest_created_at(
        self, connection: sqlite3.Connection, bucket_key: str
    ) -> float | None:
        cursor = connection.execute(
            "SELECT MIN(created_at) FROM rate_limit_events WHERE bucket_key = ?",
            (bucket_key,),
        )
        oldest = cursor.fetchone()[0]
        return float(oldest) if oldest is not None else None

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
                # 群节奏桶的令牌状态：每群一行 (tokens, updated_at)，比逐条插事件行
                # 更省；与 InMemory 的 _pacing_tokens 同一套算术（共用模块级纯函数）。
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rate_limit_pacing_tokens (
                        bucket_key TEXT PRIMARY KEY,
                        tokens REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                    """
                )
            SQLiteRateLimiter._schema_ready_paths.add(schema_key)

    def _cleanup_expired(
        self,
        connection: sqlite3.Connection,
        now_epoch: float,
    ) -> None:
        """低频全表过期清理：删除超过所有限制窗口的旧事件行。"""
        if self._monotonic() - self._last_cleanup < self._CLEANUP_INTERVAL_SECONDS:
            return
        self._last_cleanup = self._monotonic()
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


# ---------------------------------------------------------------------------
# 补回参数的**唯一数值真身**（2026-09-28 需求 2 残留收尾；同「阈值字面量收一处」的
# ack 族口径：数字只在这里写一遍，dataclass 缺省与装配口兜底都指过来）。
# ---------------------------------------------------------------------------
# 窗口不写字面量、按点名间隔派生：补回排队账本给同人连发的第 N 条排的回位是
# (N-1)×间隔，"整轮排得下"的算术就是 N×间隔。R3 间隔缺省住在 `RateLimitSettings`
# 的字段缺省里（现值 45 秒），所以这里反射取它，不抄第二份 45——谁抬间隔，
# 补回窗口跟着走，不再出现"180=4×45 的账被间隔改动悄悄写爆"那种静默丢。
_DEFAULT_SENDER_INTERVAL_SECONDS = int(
    RateLimitSettings.model_fields["chat_sender_min_interval_seconds"].default
)
# 6 格 = 连发 6 条整轮排得下（第 6 条回位 5×45＝225 秒 ＋ 一格余量）。
DEFAULT_REDRIVE_MAX_WAIT_SECONDS = float(6 * _DEFAULT_SENDER_INTERVAL_SECONDS)
# 有界重放的上限：3 次够"让位—再让位—收敛"，再大就是重放循环的风险面。
DEFAULT_REDRIVE_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class RedriveSettings:
    """被限流挡下的消息「期后补回」的参数（2026-09-25 用户裁定第 2 项）。

    旧行为是一刀静默丢弃：同人 45 秒最小间隔拦掉的那几条既不重投、也不进会话
    历史，用户看到的是「喊三声只应一次，后两声凭空消失」。这里改成：等到解禁
    那一刻再补跑一次，补不起（还要等太久/已补过）才维持原样静默。

    ⚠ 下面两枚缺省是**代码面真身**；`config.py` 的同名字段缺省已于 2026-09-29 抬到
    同源（270.0 / 3）。生产生效值走 `build_redrive_settings` 从 Config 搬的那一条腿，
    所以线上真身仍看 config.py——两侧不同源由
    `tests/test_redrive_window_exhaustion.py::test_config_default_matches_the_code_truth`
    当场判红（不许两份口径长期并存）。
    """

    enabled: bool = True
    # 还要等这么久以内才补（秒）：超过就说明拦我的是"更晚才解禁的那一道"，
    # 但**不再丢弃**——排到这一格（最近可用槽）再判一次，见 `redrive_wait_seconds`。
    # 数值按"整轮连发排不下"反推：6×点名间隔缺省 ⇒ 连发 6 条的第 6 条（回位 5×45=225s）
    # 落进窗口，还余一格吸收到达差与向上取整。上一档 180＝4×45 只到第 5 条，
    # 第 6 条起仍被吞（2026-09-28 用户点名需求 2 的残留）。
    max_wait_seconds: float = DEFAULT_REDRIVE_MAX_WAIT_SECONDS
    # 一条消息最多补几次（防重放循环）。1 次不够用的原因：超窗改"排到最近可用槽"后，
    # 补回到访那条可能仍被前一条拨走的冷却钟拦住（醒来早于真解禁点），一发额度
    # 当场陪葬＝又回到静默丢。3 次给"让位—再让位—收敛"，仍是有界重放。
    max_attempts: int = DEFAULT_REDRIVE_MAX_ATTEMPTS


# 只对这些拒绝原因补回：都是「同一时刻太密」类，等一小会儿就该放行。
# 刻意不含 quiet_hours（安静时间补回等于凌晨攒到早上集体轰炸）。
# 也刻意不含 proactive_cooldown / proactive_window_exceeded（2026-09-29 需求项 2 之 3
# 的边界，用户口径原文＝「不得放宽对 bot 主动搭话的防骚扰门」）：这两道正是
# 「主动窗口 + 主动冷却」本身。把它们的拒绝排进补回队列＝给同一次主动接话多发几次
# 机会，那就是拿防骚扰门当摆设——被它们拦下是**本分**，不是吞消息。
# 需要澄清的口径差：门禁抽签已选中要接话那条腿被**太密类**（下表其余各因）拦下时
# 仍然补回（那是白抽签），判据住在 `_is_directed_request(..., proactive_selected=True)`
# 的显式标签腿，由 pipeline 当场把已算好的 `proactive_request` 递进来——
# 补的是「已经欠下的那句」，不是「再抽一次签」。
# 也刻意不含 command_rate_limited（E05 缺口二，W1 复核后维持）：补回是把整条消息
# 重放**完整链路**（`pipeline._redrive_after` 复用 handle_async），而 `_is_directed_request`
# 把所有非 chat 能力都算「欠一句回复」⇒ 一旦进白名单，每条被帽命令都会重放
# `max_attempts` 次，每次都重新过命令帽：12/分钟的帽被 3 次重放吃成最多 36 句，
# 洪水只是延后并没有被挡住；用户手动重敲过的还会几分钟后二次刷屏。
# 「被帽命令静默无回执」是**回执面**的账（pipeline 那条 `public_message=""`，
# 且 `pick_rate_limit_exhausted_notice` 现役零消费者＝说明面本身没接线），
# 该补在说明上，不该用重放去补。
_REDRIVE_REASONS = frozenset(
    {
        "sender_min_interval",
        "target_min_interval",
        "sender_window_exceeded",
        "session_window_exceeded",
        "global_window_exceeded",
        "group_minute_exceeded",
        "group_hour_exceeded",
        "group_pacing_min_interval",
        "group_pacing_vision_min_interval",
        "group_pacing_minute_exceeded",
        "group_pacing_tokens_exhausted",
    }
)


def is_density_redrive_reason(reason: str) -> bool:
    """该拒因是否属「太密类、值得补回」——pipeline 的可见说明判据共读这里，
    不在调用侧抄第二份名册（规则 10：名单会漂）。"""
    return reason in _REDRIVE_REASONS


# ---------------------------------------------------------------------------
# 补回封顶耗尽的**可见说明**（2026-09-29 需求项 2 之 1）：
# 「用户在群里连发的每一条，最终都必须被回，不许静默吞」——补不回时至少说一句。
# 口径：守岸人语气、承认没答上、请对方再说一次；**不编造原因**（不说"在忙"、
# 不报队列数字、不提限流），不碰 ACK_TEXT_BANNED 那类客服腔。
# ---------------------------------------------------------------------------
RATE_LIMIT_EXHAUSTED_NOTICE_POOL: tuple[str, ...] = (
    "这句我在队里排到尽头也没赶上——不是没看见，是没答上。再说一次好吗。",
    "刚刚排在它前面的太多，它没能走进这一轮。你再说一次，我不让它在半路等没。",
    "这一条我终究没接住，不编个理由搪塞你。重新说一次，这次我排在头一个答。",
)

_NOTICE_CURSOR_LOCK = threading.Lock()
_NOTICE_CURSOR = 0


def pick_rate_limit_exhausted_notice(session_id: str) -> str:
    """轮换取句；同一会话相邻两次不重复（手法与回执池同源，不新开第二套状态）。"""
    pool = RATE_LIMIT_EXHAUSTED_NOTICE_POOL
    if not pool:
        return ""
    digest = int(
        hashlib.blake2b(str(session_id or "").encode("utf-8"), digest_size=8).hexdigest(),
        16,
    )
    global _NOTICE_CURSOR
    with _NOTICE_CURSOR_LOCK:
        index = _NOTICE_CURSOR
        _NOTICE_CURSOR += 1
    return pool[(index + digest) % len(pool)]


def _is_directed_request(
    message: IncomingMessage, capability_id: str, *, proactive_selected: bool = False
) -> bool:
    """这条被拦的消息是不是「欠一句回复」。

    三条算欠账（需求项 2 之 2 的收口口径）：① 非聊天能力＝命令类（`/bot xxx`、点歌、
    天气…），命令要落地就得回；② 私聊与一切非群会话＝用户开口找 bot；③ 群聊里点名了
    bot。**外加调用方的显式标签** `proactive_selected`：门禁这一轮已经抽中要接话的那条腿
    （含视觉回复腿）也欠一句——被「太密」吞掉就是白抽签。

    为什么标签必须由调用方传、本件不自己猜：群聊里没点名又没被抽中的真·路过闲聊，
    `evaluate_policy` 早就以 `passive_group_message` 拒了（policy/gate.py），正常根本到
    不了限流面；真到了也不该补，补它＝把刷屏放大。09-25 那条「没 @ 的群闲聊不补回」
    今天仍在场，由 `tests/test_throttle_redrive_and_adaptive_ack.py` 与
    `tests/test_redrive_window_exhaustion.py` 两把锁钉住。

    2026-09-29 中途曾把这枚判据改成「走到这里的一律欠账」（`return True`），实跑把
    上述两把锁打成红：那等于同时放宽「主动接话」与「没 @ 闲聊」两道防骚扰门，与需求
    项 2 之 3 正面冲突，已按裁定撤回。撤回后需求 2 的覆盖不受影响——用户连发要么点了名
    （③）、要么被抽中（标签），两条路都进补回队列。
    """
    if proactive_selected:
        return True
    if capability_id not in CHAT_CAPABILITY_IDS:
        return True  # 非聊天能力都是命令类（/bot xxx、点歌、天气…）。
    if message.session_type.value != "group":
        return True
    return bool(message.mentions_bot)


def redrive_wait_seconds(
    settings: RedriveSettings,
    message: IncomingMessage,
    capability_id: str,
    decision: RateLimitDecision,
    *,
    proactive_selected: bool = False,
) -> float | None:
    """这条被拦的消息该不该补、要等几秒；不该补返回 None。

    只判不排程（排程在 pipeline）。点名间隔类拒绝读补回排队账本：同人同轮的
    多条被拦消息由账本给出各自的排队回位（互差≥一个间隔），读的是限流器在
    拒绝当场登记的预留、按 ``decision.debug_id`` 精确认领——外来/陈旧的决定
    读不到账，一律按原判秒数走，行为逐字节等于旧口径。

    `proactive_selected` 见 `_is_directed_request`：群自动回复腿是否算「欠一句回复」，
    由调用方（pipeline 已算出 `proactive_request`）传入；缺省 False 保持现状。
    """
    if not settings.enabled or decision.allowed:
        return None
    if decision.reason not in _REDRIVE_REASONS:
        return None
    if not _is_directed_request(message, capability_id, proactive_selected=proactive_selected):
        return None
    if int(getattr(message, "redrive_count", 0) or 0) >= max(0, settings.max_attempts):
        return None
    wait = max(0.0, float(decision.retry_after_seconds or 0))
    if wait <= 0:
        return None
    if decision.reason == "sender_min_interval":
        reserved = redrive_ledger.reserved_wait_for(
            sender_interval_ledger_key(
                capability_id,
                str(message.sender_id or ""),
                str(getattr(message, "group_id", "") or ""),
            ),
            debug_id=str(decision.debug_id or ""),
        )
        if reserved is not None:
            wait = reserved
    cap = max(1.0, settings.max_wait_seconds)
    # 超窗不再"弃"：钳制到窗口这一格（= 最近可用槽）再走一遍原链路。
    # 旧写法在这里 return None，等于把"排队排到窗口外"的那几条读成"不必回"——
    # 她需求 2 的残留（连发 6 条只回 5 条）就是这么来的：账本给第 6 条排到
    # 225 秒、窗口 180 秒 ⇒ 当场判弃。改成钳制之后：
    # ① 上限仍然是硬上界（绝不满一小时后突然冒一句——小时级帽那条老判据还在，
    #    只是从"直接不回"变成"到点再看一眼，多半仍被拦，然后按额度收口"）；
    # ② 重放有界：`max_attempts` 的额度门在上方，钳制过的醒来最多 3 次；
    # ③ 醒来那一次走的是完整链路（门禁/限流/审核/出站闸再过一遍），不是旁路。
    wait = min(wait, cap)
    return wait


def build_redrive_settings(config: object) -> RedriveSettings:
    """装配补回参数；读不到 Config 的替身一律回落到保守缺省。"""
    defaults = RedriveSettings()
    return RedriveSettings(
        enabled=bool(getattr(config, "bot_chat_rate_limit_redrive_enabled", True)),
        max_wait_seconds=float(
            getattr(
                config,
                "bot_chat_rate_limit_redrive_max_wait_seconds",
                defaults.max_wait_seconds,
            )
        ),
        max_attempts=int(
            getattr(
                config,
                "bot_chat_rate_limit_redrive_max_attempts",
                defaults.max_attempts,
            )
        ),
    )


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
        # R3 同人点名最小间隔此前是**读点幽灵**：键在 config.py 在册、装配口却从不
        # 搬 ⇒ 实际生效值恒等于 dataclass 缺省 45，改 .env 与 /bot runtime set 全无效
        # （2026-09-25 现算坐实）。补上读点，这一刀才真的可调。
        chat_sender_min_interval_seconds=int(
            getattr(config, "bot_rate_limit_chat_sender_min_interval_seconds", 45)
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
        # 节奏层五枚参数此前在这里**没有读点**（2026-09-24 T7 落地席根修）：
        # 键在 config.py 与 RESTART_REQUIRED_KEYS 都在册，但装配口不搬 ⇒ 模型字段
        # 停在缺省 0 ⇒ group_pacing_applies() 恒 False ⇒ 用户裁定的整套节奏
        # （桶容量/分钟帽/最小间隔/图类独立间隔）在 .env 里填了也不生效。
        # 缺省取 0（= 整层关）而不是 config.py 的 60：**属性缺失只该发生在
        # 非 Config 替身上**，那种场合按 fail-closed 处理，绝不让"读不到"变成
        # "自动开始限流"。真 Config 永远带字段，行为由 .env 决定。
        group_pacing_tokens_per_hour=int(
            getattr(config, "bot_rate_limit_group_pacing_tokens_per_hour", 0) or 0
        ),
        group_pacing_burst_capacity=int(
            getattr(config, "bot_rate_limit_group_pacing_burst_capacity", 5)
        ),
        group_pacing_max_per_minute=int(
            getattr(config, "bot_rate_limit_group_pacing_max_per_minute", 3)
        ),
        group_pacing_min_interval_seconds=int(
            getattr(config, "bot_rate_limit_group_pacing_min_interval_seconds", 20)
        ),
        group_vision_min_interval_seconds=int(
            getattr(config, "bot_rate_limit_group_vision_min_interval_seconds", 120)
        ),
        emotion_exempt_enabled=bool(
            getattr(config, "bot_rate_limit_emotion_exempt", True)
        ),
        bypass_roles=list(
            getattr(config, "bot_rate_limit_bypass_roles", DEFAULT_BYPASS_ROLES)
        ),
        # 命令腿帽（E05 缺口二）读点。缺省全写在代码面：config 无该字段时取本处
        # 缺省 ⇒ 帽默认生效且不炸构造（"三面同批"落地前也能生效，见
        # patches/E05-CONFIG-REQUEST.md；真 Config 补上字段后由 .env 决定）。
        command_enabled=bool(getattr(config, "bot_rate_limit_command_enabled", True)),
        command_window_seconds=int(
            getattr(config, "bot_rate_limit_command_window_seconds", 60)
        ),
        command_sender_max_requests=int(
            getattr(config, "bot_rate_limit_command_sender_max_requests", 12)
        ),
        command_group_max_requests=int(
            getattr(config, "bot_rate_limit_command_group_max_requests", 20)
        ),
        command_bypass_roles=list(
            getattr(config, "bot_rate_limit_command_bypass_roles", DEFAULT_BYPASS_ROLES)
        ),
    )


def build_rate_limiter(
    config: object,
    *,
    settings_provider: Callable[[], RateLimitSettings] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RateLimiter:
    """构造限流器。

    传 ``settings_provider`` 时每次判定实时求值（群句数帽/情绪豁免/点名间隔
    可热改，两把尺同权）；否则退回启动期快照（旧行为）。
    ``clock`` 缺省 None=真实墙钟；注入假钟只为确定性测试（两后端构造器本已
    支持，装配口此前不转发 ⇒ 经装配口构造的用例没法把"过了几秒"演出来）。
    """
    settings = settings_provider if settings_provider is not None else build_rate_limit_settings(config)
    db_path = str(getattr(config, "bot_rate_limit_db_path", "")).strip()
    if db_path:
        # SQLite 版如今同样吃 callable（每轮现读——AGENTS 台账 #3 的限流面根修，
        # `test_sqlite_limiter_reads_settings_hot_from_the_provider` 锁死）；
        # 不传 provider 时拿到的是静态对象，行为与旧快照逐字节相同。
        return SQLiteRateLimiter(db_path, settings=settings, clock=clock)
    return InMemoryRateLimiter(settings, clock=clock)

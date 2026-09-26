"""限流补回（第 2 项）与回执自适应阈值（第 6 项）的回归锁。

两条都是"用户看得见但代码里没痕迹"的行为，所以除了纯函数判据，
还各配一发真跑通路的用例：补回必须真的把那句被拦的话回出来，
自适应必须在网关慢的时候**不**发回执。
"""

from __future__ import annotations

import asyncio

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    ReceiptState,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    RateLimitDecision,
    RedriveSettings,
    build_rate_limit_settings,
    redrive_wait_seconds,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.progress_ack import (
    ProgressAckSettings,
    effective_ack_delay_seconds,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue


def _message(
    text: str = "守岸人 在吗",
    *,
    session_type: SessionType = SessionType.GROUP,
    mentions_bot: bool = True,
    sender_id: str = "u1",
    group_id: str | None = "10",
    redrive_count: int = 0,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot_v11",
        bot_id="3958874605",
        session_id=(
            f"group_{group_id}_{sender_id}"
            if session_type is SessionType.GROUP
            else f"private_{sender_id}"
        ),
        session_type=session_type,
        sender_id=sender_id,
        group_id=group_id,
        plain_text=text,
        mentions_bot=mentions_bot,
        redrive_count=redrive_count,
    )


def _denied(reason: str, retry_after: int = 30) -> RateLimitDecision:
    return RateLimitDecision(
        allowed=False, reason=reason, retry_after_seconds=retry_after
    )


# --------------------------------------------------------------------------
# 第 6 项：回执阈值跟着网关当下快慢走
# --------------------------------------------------------------------------


@pytest.mark.parametrize("gateway_ema_ms", [None, 0, -1, "not-a-number"])
def test_missing_measurement_falls_back_to_configured_threshold(
    gateway_ema_ms: object,
) -> None:
    """测不到就按原值判——观测面坏了不许把回执功能一起带走。"""
    settings = ProgressAckSettings(enabled=True, delay_seconds=15.0)
    assert effective_ack_delay_seconds(settings, gateway_ema_ms) == 15.0  # type: ignore[arg-type]


def test_fast_gateway_still_uses_the_floor_not_the_raw_multiplication() -> None:
    settings = ProgressAckSettings(enabled=True, delay_seconds=15.0)
    # 2000ms × 2.0 = 4s，但下限 15s ⇒ 仍按 15s（不比旧口径更早开口）。
    assert effective_ack_delay_seconds(settings, 2000) == 15.0


def test_slow_gateway_raises_the_bar_so_jitter_stops_triggering_acks() -> None:
    """现网实测的慢跳（grok ema 13.7s）必须把阈值抬到远高于 15s。"""
    settings = ProgressAckSettings(enabled=True, delay_seconds=15.0)
    raised = effective_ack_delay_seconds(settings, 13700)
    assert raised == pytest.approx(27.4)
    assert raised > settings.delay_seconds


def test_threshold_is_capped_so_a_broken_gateway_still_warns() -> None:
    settings = ProgressAckSettings(enabled=True, delay_seconds=15.0)
    assert effective_ack_delay_seconds(settings, 500_000) == settings.delay_cap_seconds


def test_adaptive_off_is_byte_identical_to_old_behaviour() -> None:
    settings = ProgressAckSettings(enabled=True, delay_seconds=15.0, adaptive_enabled=False)
    assert effective_ack_delay_seconds(settings, 99_000) == 15.0


def test_configured_threshold_is_never_silently_rewritten() -> None:
    """本函数不得给 delay_seconds 兜下限（下限钳制归 from_config）。

    写这条是因为第一版就犯了 max(1.0, …) 的错，把亚秒配置就地改写，
    三条既有回执用例当场红。
    """
    settings = ProgressAckSettings(enabled=True, delay_seconds=0.02)
    assert effective_ack_delay_seconds(settings, None) == 0.02


def test_from_config_reads_the_four_new_keys() -> None:
    class _Cfg:
        bot_chat_progress_ack_enabled = True
        bot_chat_progress_ack_delay_seconds = 15.0
        bot_chat_progress_ack_cooldown_seconds = 60.0
        bot_chat_progress_ack_adaptive_enabled = True
        bot_chat_progress_ack_delay_floor_seconds = 12.0
        bot_chat_progress_ack_delay_cap_seconds = 80.0
        bot_chat_progress_ack_latency_multiplier = 2.5

    settings = ProgressAckSettings.from_config(_Cfg())
    assert (
        settings.adaptive_enabled is True
        and settings.delay_floor_seconds == 12.0
        and settings.delay_cap_seconds == 80.0
        and settings.latency_multiplier == 2.5
    )


# --------------------------------------------------------------------------
# 第 2 项：被限流拦下的明确请求不再静默消失
# --------------------------------------------------------------------------


def test_group_mention_blocked_by_sender_interval_is_scheduled_for_redrive() -> None:
    """这就是她说的"消息被吞"：群内 @ 撞 45 秒冷却，旧行为是凭空消失。"""
    wait = redrive_wait_seconds(
        RedriveSettings(), _message(), "bot.chat", _denied("sender_min_interval", 12)
    )
    assert wait == 12.0


def test_private_chat_blocked_by_sender_cap_is_scheduled_for_redrive() -> None:
    wait = redrive_wait_seconds(
        RedriveSettings(),
        _message(session_type=SessionType.PRIVATE, mentions_bot=False, group_id=None),
        "bot.chat",
        _denied("sender_window_exceeded", 8),
    )
    assert wait == 8.0


@pytest.mark.parametrize(
    "reason",
    ["proactive_cooldown", "proactive_window_exceeded", "quiet_hours"],
)
def test_proactive_and_quiet_hours_are_never_redriven(reason: str) -> None:
    """主动接话本就该被拦；安静时间补回等于凌晨攒到早上集体轰炸。"""
    assert (
        redrive_wait_seconds(RedriveSettings(), _message(), "bot.chat", _denied(reason))
        is None
    )


def test_unmentioned_group_chatter_is_not_redriven() -> None:
    """没 @ 的群闲聊本就不欠回复，补回只会把刷屏放大。"""
    message = _message(mentions_bot=False)
    assert (
        redrive_wait_seconds(
            RedriveSettings(), message, "bot.chat", _denied("sender_min_interval")
        )
        is None
    )


def test_allowed_decision_never_redrives() -> None:
    assert (
        redrive_wait_seconds(
            RedriveSettings(),
            _message(),
            "bot.chat",
            RateLimitDecision(allowed=True),
        )
        is None
    )


def test_wait_beyond_the_cap_is_dropped_not_deferred_forever() -> None:
    """小时级帽在拦时，隔一小时突然冒一句比不回更糟。"""
    assert (
        redrive_wait_seconds(
            RedriveSettings(max_wait_seconds=90.0),
            _message(),
            "bot.chat",
            _denied("sender_min_interval", 3600),
        )
        is None
    )


def test_attempt_budget_is_respected() -> None:
    spent = _message(redrive_count=1)
    assert (
        redrive_wait_seconds(
            RedriveSettings(max_attempts=1), spent, "bot.chat", _denied("sender_min_interval", 5)
        )
        is None
    )


def test_disabled_switch_returns_none() -> None:
    assert (
        redrive_wait_seconds(
            RedriveSettings(enabled=False),
            _message(),
            "bot.chat",
            _denied("sender_min_interval", 5),
        )
        is None
    )


def test_r45s_interval_key_is_no_longer_a_read_point_ghost() -> None:
    """`bot_rate_limit_chat_sender_min_interval_seconds` 此前在装配口没有读点，
    改 .env 完全无效；补上读点后这里必须真的搬值。"""

    class _Cfg:
        bot_rate_limit_chat_sender_min_interval_seconds = 5

    assert build_rate_limit_settings(_Cfg()).chat_sender_min_interval_seconds == 5


# --------------------------------------------------------------------------
# 通路：被拦的那一条到底有没有被回出来
# --------------------------------------------------------------------------


class _OneThenPassLimiter:
    """第一次拦、之后放行——照生产 R3 的语义（被拒不重新计时）。"""

    def __init__(self) -> None:
        self.calls = 0

    def check_and_record(self, message, capability_id, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _denied("sender_min_interval", 1)
        return RateLimitDecision(allowed=True)


class _NullAudit:
    def append(self, record: object) -> None:
        return


def _pipeline_with(**kwargs: object) -> RuntimePipeline:
    return RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAudit()),
        audit_logger=_NullAudit(),
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_blocked_group_mention_is_actually_answered_after_the_wait() -> None:
    limiter = _OneThenPassLimiter()
    acked: list = []
    pipeline = _pipeline_with(
        rate_limiter=limiter,  # type: ignore[arg-type]
        redrive_settings=RedriveSettings(max_wait_seconds=5.0),
        progress_ack_settings=ProgressAckSettings(
            enabled=True, delay_seconds=0.01, adaptive_enabled=False
        ),
        progress_ack_submit=acked.append,
    )

    async def capability(message, decision):
        return CapabilityResult(reply_text="回你了")

    receipt = await pipeline.handle_async(_message(), capability, capability_id="bot.chat")
    assert receipt.state is ReceiptState.BLOCKED
    assert receipt.retry_count == 1
    assert receipt.next_retry_at is not None
    assert receipt.next_retry_at.tzinfo is not None, "补回截止点必须带时区"
    assert limiter.calls == 1

    # 等到补回跑完：这一次必须真把回复走完，而不是又多一次静默。
    await asyncio.sleep(2.0)
    assert limiter.calls == 2, "补回任务没有重跑链路"
    assert pipeline._redrive_tasks == set(), "补完的任务要从强引用集合里摘掉"


@pytest.mark.asyncio
async def test_sync_handle_path_still_drops_silently_and_is_unchanged() -> None:
    """同步 handle 没有可重放的协程 ⇒ 不补回，行为逐字节保持原样。"""
    limiter = _OneThenPassLimiter()
    pipeline = _pipeline_with(
        rate_limiter=limiter,  # type: ignore[arg-type]
        redrive_settings=RedriveSettings(),
    )

    def capability(message, decision):
        return CapabilityResult(reply_text="回你了")

    receipt = pipeline.handle(_message(), capability, capability_id="bot.chat")
    assert receipt.state is ReceiptState.BLOCKED
    assert receipt.retry_count == 0

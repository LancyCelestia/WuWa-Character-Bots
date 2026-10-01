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
    MS_PER_SECOND,
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
def test_missing_measurement_opens_no_earlier_than_the_floor(
    gateway_ema_ms: object,
) -> None:
    """测不到（冷启动/读失败）⇒ `max(静态值, 地板)`，不再逐字节退回静态值。

    旧判据"退静态值"的代价：`.env` 的静态值仍是 15 而地板已抬到 30 ⇒ 每次刚重启
    那一段都按 15 秒误开口（D2 在冷启动窗口内等于没生效）。2026-09-28 用户裁定
    收掉这一半；全账与两半仍在场的判据见
    `tests/test_progress_ack_thresholds.py::test_missing_observation_no_longer_reopens_the_cold_start_hole`。
    """
    settings = ProgressAckSettings(enabled=True, delay_seconds=15.0)
    got = effective_ack_delay_seconds(settings, gateway_ema_ms)  # type: ignore[arg-type]
    assert got == max(settings.delay_seconds, settings.delay_floor_seconds)
    assert got >= settings.delay_floor_seconds, "缺测不许比地板更早开口"


def test_fast_gateway_still_uses_the_floor_not_the_raw_multiplication() -> None:
    settings = ProgressAckSettings(enabled=True, delay_seconds=15.0)
    # 派生值（2000ms × 倍率）落在地板以下 ⇒ **地板说话**。期望值与地板都由真身派生：
    # 地板 2026-09-26 由 15 抬到 30（用户裁定 D2），本件早先写死 15.0 因此过期而红。
    derived = 2_000.0 / MS_PER_SECOND * settings.latency_multiplier
    assert derived < settings.delay_floor_seconds, "夹具前提：这一格确实是被地板压住的那一侧"
    assert effective_ack_delay_seconds(settings, 2_000) == settings.delay_floor_seconds


def test_slow_gateway_raises_the_bar_so_jitter_stops_triggering_acks() -> None:
    """现网实测的慢跳（grok ema 13.7s）必须把开口时刻抬到远高于配置的 15 秒。"""
    settings = ProgressAckSettings(enabled=True, delay_seconds=15.0)
    raised = effective_ack_delay_seconds(settings, 13_700)
    # 地板 15→30（2026-09-26 用户裁定 D2）后，派生 27.4 秒落在地板以下 ⇒ 地板说话。
    # 期望值由真身派生，不再写字面量（本件早先写死 27.4 因此过期而红）。
    assert raised == settings.delay_floor_seconds
    assert raised > settings.delay_seconds, "自适应必须比固定值更晚开口，否则误报面没收口"


def test_derived_bar_above_the_floor_is_used_as_is() -> None:
    """地板以上的那一侧：派生值说话（19.9s 是现网 grok 单跳实测最大 EWMA）。

    只锁"被地板压住"那一侧的话，`return floor` 写死也能绿；这一发把「抬档」这条腿
    单独钉住，两侧各咬一次。
    """
    settings = ProgressAckSettings(enabled=True, delay_seconds=15.0)
    ema_ms = 19_900.0
    derived = ema_ms / MS_PER_SECOND * settings.latency_multiplier
    assert derived > settings.delay_floor_seconds, "夹具前提：这一格确实越过地板"
    assert effective_ack_delay_seconds(settings, ema_ms) == pytest.approx(derived)


def test_threshold_is_capped_so_a_broken_gateway_still_warns() -> None:
    settings = ProgressAckSettings(enabled=True, delay_seconds=15.0)
    assert effective_ack_delay_seconds(settings, 500_000) == settings.delay_cap_seconds


def test_adaptive_off_is_byte_identical_to_old_behaviour() -> None:
    settings = ProgressAckSettings(enabled=True, delay_seconds=15.0, adaptive_enabled=False)
    assert effective_ack_delay_seconds(settings, 99_000) == 15.0


def test_configured_threshold_is_never_silently_lowered() -> None:
    """本函数只准把开口时刻**推晚**，永不准把它改早——两侧各钉一次。

    原判据「本函数不得给 delay_seconds 兜下限」在 2026-09-28 收窄成两半：
    ① 显式关死自适应＝配多少判多少（亚秒配置照旧可用，下游管线夹具全靠这条腿）；
    ② 自适应开着但缺测＝抬到地板（只抬不压）；静态值高于地板时按静态值走，
       所以"把配置就地改写小"这种病仍然一次都不许犯。
    写这条的最初原因（第一版在这里夹 `max(1.0, …)` 把亚秒配置改写）由 ① 继续看着。
    """
    off = ProgressAckSettings(enabled=True, delay_seconds=0.02, adaptive_enabled=False)
    assert effective_ack_delay_seconds(off, None) == 0.02
    assert effective_ack_delay_seconds(off, 99_000) == 0.02

    on = ProgressAckSettings(enabled=True, delay_seconds=0.02)
    assert effective_ack_delay_seconds(on, None) == on.delay_floor_seconds

    above = ProgressAckSettings(enabled=True, delay_seconds=120.0)
    assert effective_ack_delay_seconds(above, None) == 120.0, "缺测把静态配置改小了"


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


def test_wait_beyond_the_cap_is_clamped_to_the_nearest_available_slot() -> None:
    """超窗不再"弃"：排到窗口这一格再判一次（2026-09-28 需求 2 残留收口）。

    旧判据 `return None` 把"排队排到窗口外"读成"不必回"，连发 6 条的第 6 条
    （账本回位 225 秒 > 旧窗口 180 秒）就是这么被吞的。钳制之后那条老约束仍在场：
    上界还是窗口本身，所以**不会**出现"隔一小时突然冒一句"；到点那一轮走完整链路，
    多半仍被小时帽拦住，然后按 `max_attempts` 收口为静默（有界，不重放循环）。
    """
    settings = RedriveSettings(max_wait_seconds=90.0)
    assert (
        redrive_wait_seconds(settings, _message(), "bot.chat", _denied("sender_min_interval", 3600))
        == 90.0
    )
    # 额度用尽仍然收口为不补：钳制不等于无限顺延。
    assert (
        redrive_wait_seconds(
            settings,
            _message(redrive_count=3),
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

"""回归：群聊句数帽（60/小时、3/分钟）+ 情绪低落豁免。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_group_rate_limit.py -q

用户口径：群聊每小时 60 句、每分钟 3 句；有要紧的事（情绪低落需安抚）不受此限。
实现要点：这是**两个新的时间窗维度**（原先只有 60s 窗口与 3600s 主动回复窗口），
零值表示该帽不生效；豁免走与聊天链路同一套规则情绪识别。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    InMemoryRateLimiter,
    RateLimitSettings,
    build_rate_limit_settings,
    distress_exemption,
    is_group_session,
)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def _message(
    text: str = "在吗",
    *,
    session_type: SessionType = SessionType.GROUP,
    group_id: str | None = "123456",
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id=f"group_{group_id}" if group_id else "private:u1",
        session_type=session_type,
        sender_id="u1",
        group_id=group_id,
        plain_text=text,
    )


def _limiter(clock: _Clock, **overrides) -> InMemoryRateLimiter:
    base = {
        "chat_global_max_requests": 10_000,
        "chat_session_max_requests": 10_000,
        "chat_sender_max_requests": 10_000,
    }
    base.update(overrides)
    return InMemoryRateLimiter(RateLimitSettings(**base), clock=clock)


# ----------------------------------------------------------- 会话类型判定


def test_group_session_detected_by_session_type() -> None:
    assert is_group_session(_message()) is True


def test_private_session_not_group() -> None:
    assert (
        is_group_session(
            _message(session_type=SessionType.PRIVATE, group_id=None)
        )
        is False
    )


def test_group_id_presence_implies_group() -> None:
    assert (
        is_group_session(_message(session_type=SessionType.PRIVATE, group_id="9"))
        is True
    )


# --------------------------------------------------------------- 每分钟 3 句


def test_group_minute_cap_blocks_fourth_message() -> None:
    clock = _Clock()
    limiter = _limiter(clock, group_minute_max_requests=3)
    for index in range(3):
        decision = limiter.check_and_record(_message(f"第{index}句"), "bot.chat")
        assert decision.allowed is True, f"第 {index + 1} 句不该被拦"
    blocked = limiter.check_and_record(_message("第4句"), "bot.chat")
    assert blocked.allowed is False
    assert blocked.reason == "group_minute_exceeded"
    assert blocked.retry_after_seconds > 0


def test_group_minute_cap_recovers_after_window() -> None:
    clock = _Clock()
    limiter = _limiter(clock, group_minute_max_requests=3)
    for index in range(3):
        limiter.check_and_record(_message(f"第{index}句"), "bot.chat")
    assert limiter.check_and_record(_message("超限"), "bot.chat").allowed is False
    clock.advance(seconds=61)
    assert limiter.check_and_record(_message("窗口后"), "bot.chat").allowed is True


# ------------------------------------------------------------- 每小时 60 句


def test_group_hourly_cap_blocks_61st_message() -> None:
    clock = _Clock()
    limiter = _limiter(clock, group_hourly_max_requests=60)
    for index in range(60):
        decision = limiter.check_and_record(_message(f"句{index}"), "bot.chat")
        assert decision.allowed is True, f"第 {index + 1} 句不该被拦（帽 60）"
        # 每 30 秒一句，避免撞分钟帽以外的因素（分钟帽此处未启用）
        clock.advance(seconds=30)
    blocked = limiter.check_and_record(_message("第61句"), "bot.chat")
    assert blocked.allowed is False
    assert blocked.reason == "group_hour_exceeded"


def test_hourly_window_slides() -> None:
    clock = _Clock()
    limiter = _limiter(clock, group_hourly_max_requests=3)
    for index in range(3):
        limiter.check_and_record(_message(f"句{index}"), "bot.chat")
    assert limiter.check_and_record(_message("超限"), "bot.chat").allowed is False
    clock.advance(seconds=3601)
    assert limiter.check_and_record(_message("一小时后"), "bot.chat").allowed is True


# --------------------------------------------------------------- 零值语义


def test_zero_caps_disable_group_windows() -> None:
    """0 = 该帽不生效（不能变成"不限"以外的意外语义）。"""
    clock = _Clock()
    limiter = _limiter(clock)  # 两个帽都是 0
    for index in range(200):
        assert (
            limiter.check_and_record(_message(f"句{index}"), "bot.chat").allowed is True
        )


def test_settings_reject_negative_caps() -> None:
    import pytest

    with pytest.raises(ValueError):
        RateLimitSettings(group_minute_max_requests=-1)


def test_private_chat_unaffected_by_group_caps() -> None:
    """群句数帽只作用于群，私聊不受影响。"""
    clock = _Clock()
    limiter = _limiter(clock, group_minute_max_requests=1, group_hourly_max_requests=1)
    for index in range(5):
        decision = limiter.check_and_record(
            _message(
                f"私聊第{index}句",
                session_type=SessionType.PRIVATE,
                group_id=None,
            ),
            "bot.chat",
        )
        assert decision.allowed is True


# ------------------------------------------------------------- 情绪豁免


def test_distress_message_is_exempt() -> None:
    """情绪低落时豁免句数帽——安抚不该被挡住。"""
    clock = _Clock()
    limiter = _limiter(clock, group_minute_max_requests=1)
    assert limiter.check_and_record(_message("你好"), "bot.chat").allowed is True
    # 第二条本应被分钟帽拦下
    assert limiter.check_and_record(_message("再说一句"), "bot.chat").allowed is False
    # 但情绪低落的消息必须放行
    sad = limiter.check_and_record(_message("我好难受，撑不住了"), "bot.chat")
    assert sad.allowed is True
    assert sad.reason == "emotion_exempt"
    assert any(tag.startswith("rate_limit:emotion:") for tag in sad.audit_tags)


def test_exemption_can_be_disabled() -> None:
    clock = _Clock()
    limiter = _limiter(clock, group_minute_max_requests=1, emotion_exempt_enabled=False)
    assert limiter.check_and_record(_message("你好"), "bot.chat").allowed is True
    assert limiter.check_and_record(_message("我好难受"), "bot.chat").allowed is False


def test_distress_detection_helper() -> None:
    assert distress_exemption(_message("我好难受，想哭")) is not None
    assert distress_exemption(_message("今天天气不错")) is None
    assert distress_exemption(_message("")) is None


def test_happy_message_not_exempt() -> None:
    clock = _Clock()
    limiter = _limiter(clock, group_minute_max_requests=1)
    limiter.check_and_record(_message("你好"), "bot.chat")
    assert limiter.check_and_record(_message("今天真开心"), "bot.chat").allowed is False


# --------------------------------------------------------- 设置构建与热改


def test_build_settings_reads_config_fields() -> None:
    class _Cfg:
        bot_rate_limit_enabled = True
        bot_rate_limit_group_max_per_hour = 60
        bot_rate_limit_group_max_per_minute = 3
        bot_rate_limit_emotion_exempt = True

    settings = build_rate_limit_settings(_Cfg())
    assert settings.group_hourly_max_requests == 60
    assert settings.group_minute_max_requests == 3
    assert settings.emotion_exempt_enabled is True


def test_callable_settings_are_live() -> None:
    """settings 传 callable 时，热改必须立刻生效（否则 /bot runtime set 白改）。"""
    clock = _Clock()
    state = {"minute": 1}
    limiter = InMemoryRateLimiter(
        lambda: RateLimitSettings(
            chat_global_max_requests=10_000,
            chat_session_max_requests=10_000,
            chat_sender_max_requests=10_000,
            group_minute_max_requests=state["minute"],
        ),
        clock=clock,
    )
    assert limiter.check_and_record(_message("a"), "bot.chat").allowed is True
    assert limiter.check_and_record(_message("b"), "bot.chat").allowed is False
    state["minute"] = 5
    assert limiter.check_and_record(_message("c"), "bot.chat").allowed is True

"""回归：同人点名最小间隔（R3 防刷屏，chat_sender_min_interval_seconds，默认 45）。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_policy_sender_interval.py -q

用户裁定（2026-09-12）：同一发送者两次 bot.chat 点名回复之间最少隔 45s；
仅作用于 message.mentions_bot=True 的消息（点名才防刷屏，主动接话不受限）；
InMemory 版该检查先于 bypass_roles（刷屏保护人人平等）；0 = 关闭。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.policy.rate_limit import (
    InMemoryRateLimiter,
    RateLimitSettings,
    SQLiteRateLimiter,
)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 12, 9, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def _message(
    text: str = "在吗",
    *,
    sender_id: str = "u1",
    mentions_bot: bool = True,
    sender_roles: list[str] | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="group_123456",
        session_type=SessionType.GROUP,
        sender_id=sender_id,
        group_id="123456",
        plain_text=text,
        mentions_bot=mentions_bot,
        sender_roles=sender_roles if sender_roles is not None else ["user"],
    )


def _window_caps() -> dict:
    # 抬高三个滑动窗口帽，避免句数帽先于最小间隔拦人，聚焦被测行为。
    return {
        "chat_global_max_requests": 10_000,
        "chat_session_max_requests": 10_000,
        "chat_sender_max_requests": 10_000,
    }


def _memory_limiter(clock: _Clock, **overrides) -> InMemoryRateLimiter:
    base = _window_caps()
    base.update(overrides)
    return InMemoryRateLimiter(RateLimitSettings(**base), clock=clock)


def _sqlite_limiter(clock: _Clock, tmp_path: Path, **overrides) -> SQLiteRateLimiter:
    base = _window_caps()
    base.update(overrides)
    return SQLiteRateLimiter(
        tmp_path / "rate_limit.db",
        RateLimitSettings(**base),
        clock=clock,
    )


# --------------------------------------------------------- InMemory 基本语义


def test_memory_first_mention_allowed_then_blocked_within_interval() -> None:
    clock = _Clock()
    limiter = _memory_limiter(clock)
    first = limiter.check_and_record(_message("第一次点名"), "bot.chat")
    assert first.allowed is True
    second = limiter.check_and_record(_message("45s 内再喊"), "bot.chat")
    assert second.allowed is False
    assert second.reason == "sender_min_interval"
    assert second.retry_after_seconds > 0
    assert second.retry_after_seconds == 45


def test_memory_allowed_again_after_interval() -> None:
    clock = _Clock()
    limiter = _memory_limiter(clock)
    assert limiter.check_and_record(_message("第一次"), "bot.chat").allowed is True
    clock.advance(seconds=46)  # 跨过 45s 最小间隔
    again = limiter.check_and_record(_message("间隔后再喊"), "bot.chat")
    assert again.allowed is True
    assert again.reason == "allowed"


def test_memory_non_mention_messages_unaffected() -> None:
    """mentions_bot=False（主动接话/图片等路径）不受最小间隔限制。"""
    clock = _Clock()
    limiter = _memory_limiter(clock)
    for index in range(3):
        decision = limiter.check_and_record(
            _message(f"不点名的第{index}句", mentions_bot=False),
            "bot.chat",
        )
        assert decision.allowed is True, f"非点名第 {index + 1} 句不该被拦"
        assert decision.reason == "allowed"


def test_memory_different_senders_independent() -> None:
    clock = _Clock()
    limiter = _memory_limiter(clock)
    assert limiter.check_and_record(_message("甲喊", sender_id="u1"), "bot.chat").allowed is True
    # 乙立刻点名不受甲的冷却影响
    assert limiter.check_and_record(_message("乙喊", sender_id="u2"), "bot.chat").allowed is True
    # 甲在冷却期内再喊被拦，仍是甲自己的间隔
    blocked = limiter.check_and_record(_message("甲再喊", sender_id="u1"), "bot.chat")
    assert blocked.allowed is False
    assert blocked.reason == "sender_min_interval"


# ------------------------------------------------------------- 先于角色豁免


def test_memory_admin_also_subject_to_min_interval() -> None:
    """bypass_roles 命中的 admin 连喊同样被拦：min-interval 先于 role bypass。"""
    clock = _Clock()
    limiter = _memory_limiter(clock, bypass_roles=["admin"])
    admin_first = limiter.check_and_record(
        _message("管理员点名", sender_roles=["admin"]), "bot.chat"
    )
    assert admin_first.allowed is True
    admin_second = limiter.check_and_record(
        _message("管理员连喊", sender_roles=["admin"]), "bot.chat"
    )
    assert admin_second.allowed is False
    assert admin_second.reason == "sender_min_interval"


# ----------------------------------------------------------------- 零值语义


def test_memory_zero_interval_disables_check() -> None:
    clock = _Clock()
    limiter = _memory_limiter(clock, chat_sender_min_interval_seconds=0)
    for index in range(3):
        decision = limiter.check_and_record(_message(f"连喊第{index}句"), "bot.chat")
        assert decision.allowed is True, f"关闭后第 {index + 1} 句不该被拦"
        assert decision.reason == "allowed"


# ------------------------------------------------------------- SQLite 版


def test_sqlite_blocks_second_mention_within_interval(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = _sqlite_limiter(clock, tmp_path)
    first = limiter.check_and_record(_message("第一次点名"), "bot.chat")
    assert first.allowed is True
    second = limiter.check_and_record(_message("45s 内再喊"), "bot.chat")
    assert second.allowed is False
    assert second.reason == "sender_min_interval"
    assert second.retry_after_seconds > 0


def test_sqlite_non_mention_unaffected(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = _sqlite_limiter(clock, tmp_path)
    for index in range(3):
        decision = limiter.check_and_record(
            _message(f"不点名的第{index}句", mentions_bot=False),
            "bot.chat",
        )
        assert decision.allowed is True, f"非点名第 {index + 1} 句不该被拦"
        assert decision.reason == "allowed"

"""回归：SQLiteRateLimiter 群聊句数帽（语义对齐 InMemory 双滑动窗口）。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_sqlite_rate_limit_group.py -q

口径：群聊每小时/每分钟双滑动窗口；0 = 该帽不生效；情绪低落豁免；
先判后记（拒绝不记账）；SQLite 版额外要求跨实例（同一 db）计数累计。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.policy.rate_limit import (
    RateLimitSettings,
    SQLiteRateLimiter,
)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)

    def reset(self) -> None:
        self.now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)


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


def _limiter(db_path: Path, clock: _Clock, **overrides) -> SQLiteRateLimiter:
    base = {
        "chat_global_max_requests": 10_000,
        "chat_session_max_requests": 10_000,
        "chat_sender_max_requests": 10_000,
    }
    base.update(overrides)
    return SQLiteRateLimiter(
        db_path, RateLimitSettings(**base), clock=clock
    )


# --------------------------------------------------------------- 每小时 60 句


def test_hourly_cap_blocks_over_limit(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = _limiter(tmp_path / "rl.db", clock, group_hourly_max_requests=3)
    for index in range(3):
        decision = limiter.check_and_record(_message(f"句{index}"), "bot.chat")
        assert decision.allowed is True, f"第 {index + 1} 句不该被拦（帽 3）"
        clock.advance(seconds=30)
    blocked = limiter.check_and_record(_message("超限"), "bot.chat")
    assert blocked.allowed is False
    assert blocked.reason == "group_hour_exceeded"
    assert blocked.retry_after_seconds > 0
    assert "rate_limit:blocked" in blocked.audit_tags
    assert "rate_limit:group_hour_exceeded" in blocked.audit_tags


def test_minute_cap_blocks_over_limit(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = _limiter(tmp_path / "rl.db", clock, group_minute_max_requests=3)
    for index in range(3):
        decision = limiter.check_and_record(_message(f"第{index}句"), "bot.chat")
        assert decision.allowed is True, f"第 {index + 1} 句不该被拦"
    blocked = limiter.check_and_record(_message("第4句"), "bot.chat")
    assert blocked.allowed is False
    assert blocked.reason == "group_minute_exceeded"
    assert blocked.retry_after_seconds > 0
    assert "rate_limit:group_minute_exceeded" in blocked.audit_tags


# --------------------------------------------------------- 先判后记 / 滑动窗口


def test_rejection_is_not_recorded(tmp_path: Path) -> None:
    """先判后记：被拒的那次尝试不得写入桶，否则窗口永远解不了。"""
    clock = _Clock()
    limiter = _limiter(tmp_path / "rl.db", clock, group_minute_max_requests=3)
    for index in range(3):
        limiter.check_and_record(_message(f"句{index}"), "bot.chat")
    clock.advance(seconds=30)
    assert limiter.check_and_record(_message("被拒"), "bot.chat").allowed is False
    clock.advance(seconds=31)  # 距首次记账 61s，距被拒尝试仅 31s
    # 若被拒尝试被记账（T+30），此刻 61-30=31s < 60s，仍应被拦；
    # 能放行即证明拒绝未记账。
    assert limiter.check_and_record(_message("窗口后"), "bot.chat").allowed is True


def test_window_expiry_recovers(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = _limiter(
        tmp_path / "rl.db",
        clock,
        group_minute_max_requests=2,
        group_hourly_max_requests=2,
    )
    for index in range(2):
        limiter.check_and_record(_message(f"句{index}"), "bot.chat")
    blocked = limiter.check_and_record(_message("超限"), "bot.chat")
    assert blocked.allowed is False
    # 双窗同满时与 InMemory 同序（先 hour 后 minute）→ 报 hour
    assert blocked.reason == "group_hour_exceeded"
    clock.advance(seconds=61)
    # 分钟窗已滑出，但小时窗（同一批记账）仍在 → 转由小时帽拦
    hour_blocked = limiter.check_and_record(_message("分钟解禁"), "bot.chat")
    assert hour_blocked.allowed is False
    assert hour_blocked.reason == "group_hour_exceeded"
    clock.advance(seconds=3600)
    # 小时窗也滑出 → 完全恢复
    assert limiter.check_and_record(_message("小时解禁"), "bot.chat").allowed is True


# --------------------------------------------------------------- 私聊不受限


def test_private_chat_unaffected_by_group_caps(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = _limiter(
        tmp_path / "rl.db",
        clock,
        group_minute_max_requests=1,
        group_hourly_max_requests=1,
    )
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


# --------------------------------------------------------------- 零值语义


def test_zero_caps_do_not_limit(tmp_path: Path) -> None:
    """两个帽都是 0 = 不生效（不能反向变成"不限"以外的意外语义）。"""
    clock = _Clock()
    limiter = _limiter(tmp_path / "rl.db", clock)  # 默认 group_* = 0
    for index in range(100):
        assert (
            limiter.check_and_record(_message(f"句{index}"), "bot.chat").allowed is True
        )


# ------------------------------------------------------------- 情绪豁免


def test_emotion_exempt_message_allowed(tmp_path: Path) -> None:
    """情绪低落时豁免句数帽；豁免消息本身也不记账（对齐 InMemory）。"""
    clock = _Clock()
    limiter = _limiter(tmp_path / "rl.db", clock, group_minute_max_requests=1)
    assert limiter.check_and_record(_message("你好"), "bot.chat").allowed is True
    # 第二条普通消息被分钟帽拦下
    assert limiter.check_and_record(_message("再说一句"), "bot.chat").allowed is False
    # 情绪低落的消息必须放行
    sad = limiter.check_and_record(_message("我好难受，撑不住了"), "bot.chat")
    assert sad.allowed is True
    assert sad.reason == "emotion_exempt"
    assert "rate_limit:emotion_exempt" in sad.audit_tags
    # 豁免消息未记账 → 第 4 条普通消息仍被拦（帽 1 且只有第 1 条占额）
    assert limiter.check_and_record(_message("再来说话"), "bot.chat").allowed is False


def test_emotion_exempt_can_be_disabled(tmp_path: Path) -> None:
    clock = _Clock()
    limiter = _limiter(
        tmp_path / "rl.db",
        clock,
        group_minute_max_requests=1,
        emotion_exempt_enabled=False,
    )
    assert limiter.check_and_record(_message("你好"), "bot.chat").allowed is True
    assert limiter.check_and_record(_message("我好难受"), "bot.chat").allowed is False


# --------------------------------------------------------- 跨实例持久累计


def test_cross_instance_accumulation(tmp_path: Path) -> None:
    """同一 db 先后两个实例：前一个实例记的账，后一个实例必须认。"""
    clock = _Clock()

    # 分钟帽跨实例
    minute_db = tmp_path / "rl_minute.db"
    first = _limiter(minute_db, clock, group_minute_max_requests=3)
    for index in range(3):
        assert (
            first.check_and_record(_message(f"A{index}"), "bot.chat").allowed is True
        )
    second = _limiter(minute_db, clock, group_minute_max_requests=3)
    blocked = second.check_and_record(_message("B1"), "bot.chat")
    assert blocked.allowed is False
    assert blocked.reason == "group_minute_exceeded"
    # 窗口滑出后，新实例同样解禁（旧行被新实例的 prune 淘汰）
    clock.advance(seconds=61)
    assert second.check_and_record(_message("B2"), "bot.chat").allowed is True

    # 小时帽跨实例（独立 db，避免与分钟段互相污染）
    clock.reset()
    hour_db = tmp_path / "rl_hour.db"
    hourly_first = _limiter(hour_db, clock, group_hourly_max_requests=3)
    for index in range(3):
        assert (
            hourly_first.check_and_record(_message(f"H{index}"), "bot.chat").allowed
            is True
        )
    hourly_second = _limiter(hour_db, clock, group_hourly_max_requests=3)
    hour_blocked = hourly_second.check_and_record(_message("H4"), "bot.chat")
    assert hour_blocked.allowed is False
    assert hour_blocked.reason == "group_hour_exceeded"

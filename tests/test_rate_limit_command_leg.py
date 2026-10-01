"""E05 缺口二 · 命令腿独立分钟帽（rate_limit.py，InMemory 与 SQLite 两套实现各跑一遍）。

    PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_rate_limit_command_leg.py -q \
      -p no:cacheprovider --basetemp=$TEMP/qoder-e05/bt

缺陷底账：pipeline 把 `capability_id != "bot.chat"` 一律标 interactive=True，而两把限流器
都在 interactive 处直接 `return allowed=True`（interactive_bypass），紧随其后还有第二条
漏腿 non_chat_capability ⇒ **全部命令能力零限流**，任意成员可在群里把 /bot 敲到算力见底。

本段的判据口径（用户裁定）：
- 「免帽」不再 wholesale 成立——非 chat 能力一律先过命令帽，只有 `bypass_roles`
  （缺省 ["admin"]，含超管叠加）仍享旧豁免语义；
- 命令账与 chat 句数账**两本账**，互不消耗（混用会让能力失败退还错账）；
- 先判后记：任一腿拒绝 ⇒ 两格都不写；
- `command_rate_limited` 刻意**不进** `_REDRIVE_REASONS`（补回＝把洪水延后集中）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    CHAT_CAPABILITY_IDS,
    InMemoryRateLimiter,
    RateLimitSettings,
    SQLiteRateLimiter,
    build_rate_limit_settings,
    is_density_redrive_reason,
)

_LEGACY_EXEMPT_REASONS = {"interactive_bypass", "role_bypass", "non_chat_capability"}


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def _cmd(
    sender_id: str = "u1",
    *,
    text: str = "/bot help",
    group_id: str | None = "123",
    session_type: SessionType = SessionType.GROUP,
    roles: tuple[str, ...] = ("user",),
    mentions: bool = False,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=f"group_{group_id}" if group_id else f"private:{sender_id}",
        session_type=session_type,
        sender_id=sender_id,
        group_id=group_id,
        plain_text=text,
        mentions_bot=mentions,
        sender_roles=list(roles),
    )


@pytest.fixture(params=["memory", "sqlite"])
def make_limiter(request, tmp_path: Path):
    """两套实现同一把尺：生产走 SQLite，只测内存版＝第二基线假绿。"""

    def _make(clock: _Clock, db: str = "rl", **overrides: object):
        caps: dict = {
            "chat_global_max_requests": 10_000,
            "chat_session_max_requests": 10_000,
            "chat_sender_max_requests": 10_000,
        }
        caps.update(overrides)
        settings = RateLimitSettings(**caps)
        if request.param == "sqlite":
            return SQLiteRateLimiter(tmp_path / f"{db}.db", settings, clock=clock)
        return InMemoryRateLimiter(settings, clock=clock)

    return _make


# ---------------------------------------------------------------------------
# 合法形：命令照样能过，只是有帽
# ---------------------------------------------------------------------------


def test_commands_are_allowed_up_to_the_sender_cap(make_limiter) -> None:
    clock = _Clock()
    limiter = make_limiter(clock, command_sender_max_requests=3, command_group_max_requests=0)
    for index in range(3):
        decision = limiter.check_and_record(_cmd(f"u{index}"), "bot.music", interactive=True)
        assert decision.allowed is True, index
        assert decision.reason == "command_allowed"


def test_window_slides_and_recovers(make_limiter) -> None:
    clock = _Clock()
    limiter = make_limiter(clock, command_sender_max_requests=1, command_group_max_requests=0)
    assert limiter.check_and_record(_cmd(), "bot.music", interactive=True).allowed is True
    assert limiter.check_and_record(_cmd(), "bot.music", interactive=True).allowed is False
    clock.advance(seconds=61)
    assert limiter.check_and_record(_cmd(), "bot.music", interactive=True).allowed is True


def test_admin_bypass_semantics_preserved(make_limiter) -> None:
    """bypass_roles=["admin"]（超管自动叠 admin）仍享旧豁免：不记账、不拒。"""
    clock = _Clock()
    limiter = make_limiter(clock, command_sender_max_requests=1, command_group_max_requests=0)
    for _ in range(5):
        decision = limiter.check_and_record(
            _cmd(roles=("admin",)), "bot.music", interactive=True
        )
        assert decision.allowed is True
        assert decision.reason in _LEGACY_EXEMPT_REASONS


def test_custom_command_bypass_roles(make_limiter) -> None:
    clock = _Clock()
    limiter = make_limiter(
        clock,
        command_sender_max_requests=1,
        command_group_max_requests=0,
        command_bypass_roles=["super_admin"],
    )
    # admin 不再豁免（名册被换成只认 super_admin）
    assert limiter.check_and_record(_cmd(roles=("admin",)), "bot.music").allowed is True
    assert limiter.check_and_record(_cmd(roles=("admin",)), "bot.music").allowed is False
    for _ in range(5):
        assert (
            limiter.check_and_record(
                _cmd("u9", roles=("super_admin",)), "bot.music"
            ).allowed
            is True
        )


# ---------------------------------------------------------------------------
# 越界形：洪水必拒
# ---------------------------------------------------------------------------


def test_command_flood_is_denied_with_retry(make_limiter) -> None:
    clock = _Clock()
    limiter = make_limiter(clock, command_sender_max_requests=3, command_group_max_requests=0)
    for _ in range(3):
        assert limiter.check_and_record(_cmd(), "bot.music", interactive=True).allowed is True
    blocked = limiter.check_and_record(_cmd(), "bot.music", interactive=True)
    assert blocked.allowed is False
    assert blocked.reason == "command_rate_limited"
    assert blocked.retry_after_seconds > 0
    assert "rate_limit:command_sender_exceeded" in blocked.audit_tags


@pytest.mark.parametrize("interactive", [True, False])
def test_cap_holds_whatever_the_interactive_flag_claims(make_limiter, interactive: bool) -> None:
    """两条早退腿都在帽后面 ⇒ interactive 报什么值都漏不出去（E06 改判据也不失守）。"""
    clock = _Clock()
    limiter = make_limiter(clock, command_sender_max_requests=2, command_group_max_requests=0)
    assert limiter.check_and_record(_cmd(), "bot.music", interactive=interactive).allowed
    assert limiter.check_and_record(_cmd(), "bot.music", interactive=interactive).allowed
    assert not limiter.check_and_record(
        _cmd(), "bot.music", interactive=interactive
    ).allowed


def test_group_leg_caps_many_senders(make_limiter) -> None:
    clock = _Clock()
    limiter = make_limiter(
        clock, command_sender_max_requests=10_000, command_group_max_requests=2
    )
    assert limiter.check_and_record(_cmd("u1"), "bot.music", interactive=True).allowed
    assert limiter.check_and_record(_cmd("u2"), "bot.music", interactive=True).allowed
    blocked = limiter.check_and_record(_cmd("u3"), "bot.music", interactive=True)
    assert blocked.allowed is False
    assert "rate_limit:command_group_exceeded" in blocked.audit_tags


def test_group_leg_does_not_leak_across_groups_or_into_private(make_limiter) -> None:
    clock = _Clock()
    limiter = make_limiter(
        clock, command_sender_max_requests=10_000, command_group_max_requests=2
    )
    assert limiter.check_and_record(_cmd("u1"), "bot.music").allowed
    assert limiter.check_and_record(_cmd("u2"), "bot.music").allowed
    assert not limiter.check_and_record(_cmd("u3"), "bot.music").allowed
    # 另一个群：另一本账
    assert limiter.check_and_record(_cmd("u4", group_id="999"), "bot.music").allowed
    # 私聊：不记群账，也不受群帽连坐
    private = _cmd("u5", group_id=None, session_type=SessionType.PRIVATE)
    assert limiter.check_and_record(private, "bot.music").allowed


def test_denied_command_records_nothing(make_limiter) -> None:
    """先判后记：sender 腿拒掉的命令不许吃掉群腿额度。"""
    clock = _Clock()
    limiter = make_limiter(
        clock, command_sender_max_requests=2, command_group_max_requests=3
    )
    assert limiter.check_and_record(_cmd("u1"), "bot.music").allowed
    assert limiter.check_and_record(_cmd("u1"), "bot.music").allowed
    assert not limiter.check_and_record(_cmd("u1"), "bot.music").allowed
    # 群账此时应仍是 2 格：u2 还能过第 3 格，u3 才被群帽拒
    assert limiter.check_and_record(_cmd("u2"), "bot.music").allowed
    assert not limiter.check_and_record(_cmd("u3"), "bot.music").allowed


# ---------------------------------------------------------------------------
# 两本账：命令不消耗 chat 句数帽，chat 也不落命令账
# ---------------------------------------------------------------------------


def test_commands_do_not_consume_chat_sentence_quota(make_limiter) -> None:
    clock = _Clock()
    limiter = make_limiter(
        clock,
        chat_sender_max_requests=1,
        chat_session_max_requests=10_000,
        chat_global_max_requests=10_000,
        command_sender_max_requests=10_000,
        command_group_max_requests=0,
    )
    assert limiter.check_and_record(_cmd(), "bot.chat").reason == "allowed"
    # 命令放行走自己的账，不碰 chat 桶
    assert limiter.check_and_record(_cmd(), "bot.music").reason == "command_allowed"
    # 第二句 chat 仍被 chat 自己的帽拒 ⇒ 证明命令没替它记过账
    assert not limiter.check_and_record(_cmd(), "bot.chat").allowed


def test_chat_capability_never_enters_the_command_leg(make_limiter) -> None:
    clock = _Clock()
    limiter = make_limiter(clock, command_sender_max_requests=1, command_group_max_requests=1)
    assert "bot.chat" in CHAT_CAPABILITY_IDS
    for _ in range(5):
        decision = limiter.check_and_record(_cmd(text="你好"), "bot.chat")
        assert decision.reason != "command_allowed"
        assert decision.reason != "command_rate_limited"


# ---------------------------------------------------------------------------
# 止血开关与"帽为 0＝该腿不生效"
# ---------------------------------------------------------------------------


def test_disabled_command_cap_restores_legacy_bypass(make_limiter) -> None:
    clock = _Clock()
    limiter = make_limiter(
        clock, command_enabled=False, command_sender_max_requests=1, command_group_max_requests=1
    )
    for _ in range(5):
        decision = limiter.check_and_record(_cmd(), "bot.music", interactive=True)
        assert decision.allowed is True
        assert decision.reason in _LEGACY_EXEMPT_REASONS


def test_zero_caps_disable_both_legs(make_limiter) -> None:
    clock = _Clock()
    limiter = make_limiter(
        clock, command_sender_max_requests=0, command_group_max_requests=0
    )
    for _ in range(5):
        assert limiter.check_and_record(_cmd(), "bot.music", interactive=True).allowed


def test_limiter_disabled_is_still_a_single_silence_switch(make_limiter) -> None:
    """`enabled=False`＝整门哑（既有语义，本席不动）：命令腿也一起哑。

    现状锁死：既有实现把 `interactive` 早退腿排在 `enabled` 判定**之前**
    （InMemory/SQLite 同形），所以 interactive=True 时报的是 interactive_bypass、
    interactive=False 时报 disabled——两者都"不限流"，方向一致。改这枚顺序属
    既有语义变更（红线外），本段只锁「命令腿绝不越过总闸去限流」。
    """
    clock = _Clock()
    limiter = make_limiter(
        clock, enabled=False, command_sender_max_requests=1, command_group_max_requests=1
    )
    for _ in range(3):
        decision = limiter.check_and_record(_cmd(), "bot.music", interactive=True)
        assert decision.allowed is True
        assert decision.reason != "command_rate_limited"
    for _ in range(3):
        decision = limiter.check_and_record(_cmd(), "bot.music", interactive=False)
        assert decision.allowed is True
        assert decision.reason == "disabled"


# ---------------------------------------------------------------------------
# 补回面：被命令帽拦下不排队补回（洪水延后集中不是救火）
# ---------------------------------------------------------------------------


def test_command_rate_limited_is_not_a_redrive_reason() -> None:
    assert is_density_redrive_reason("command_rate_limited") is False


# ---------------------------------------------------------------------------
# 两套实现同序同语义（同一剧本，reason 序列必须逐格相同）
# ---------------------------------------------------------------------------


def test_both_backends_agree_on_the_same_script(tmp_path: Path) -> None:
    def _run(limiter) -> list[tuple[bool, str]]:
        out: list[tuple[bool, str]] = []
        clock = _Clock()
        limiter.clock = clock  # SQLite/InMemory 都以属性暴露 clock
        for sender, capability in (
            ("u1", "bot.music"),
            ("u1", "bot.music"),
            ("u1", "bot.music"),
            ("u2", "bot.music"),
            ("u2", "bot.music"),
            ("u1", "bot.chat"),
        ):
            decision = limiter.check_and_record(_cmd(sender), capability, interactive=True)
            out.append((decision.allowed, decision.reason))
        return out

    caps = {
        "chat_global_max_requests": 10_000,
        "chat_session_max_requests": 10_000,
        "chat_sender_max_requests": 10_000,
        "command_sender_max_requests": 2,
        "command_group_max_requests": 3,
    }
    memory = _run(InMemoryRateLimiter(RateLimitSettings(**caps)))
    sqlite = _run(SQLiteRateLimiter(tmp_path / "coerce.db", RateLimitSettings(**caps)))
    assert memory == sqlite


# ---------------------------------------------------------------------------
# 装配读点：config 有键就搬，没键取代码缺省（不炸构造）
# ---------------------------------------------------------------------------


def test_build_settings_reads_the_new_command_keys() -> None:
    class _Config:
        bot_rate_limit_command_enabled = False
        bot_rate_limit_command_window_seconds = 120
        bot_rate_limit_command_sender_max_requests = 7
        bot_rate_limit_command_group_max_requests = 9
        bot_rate_limit_command_bypass_roles = ["super_admin"]

    settings = build_rate_limit_settings(_Config())
    assert settings.command_enabled is False
    assert settings.command_window_seconds == 120
    assert settings.command_sender_max_requests == 7
    assert settings.command_group_max_requests == 9
    assert settings.command_bypass_roles == ["super_admin"]


def test_build_settings_defaults_on_plain_object() -> None:
    settings = build_rate_limit_settings(object())
    assert settings.command_enabled is True
    assert settings.command_window_seconds == 60
    assert settings.command_sender_max_requests == 12
    assert settings.command_group_max_requests == 20
    assert settings.command_bypass_roles == ["admin"]


def test_settings_reject_negative_command_caps() -> None:
    with pytest.raises(Exception):
        RateLimitSettings(command_sender_max_requests=-1)
    with pytest.raises(Exception):
        RateLimitSettings(command_window_seconds=0)

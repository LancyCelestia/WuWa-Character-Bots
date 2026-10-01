"""回归：安静时间门（policy/quiet_hours.py，审查 A-16 零覆盖补测）。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_policy_quiet_hours.py -q \
        --basetemp=$TEMP/a16 -p no:cacheprovider

锁死的现状行为（全部离线、注入时钟、零 sleep）：
- 跨午夜窗口 [start>end)：start 闭、end 开——23:00 整拦、05:59 拦、06:00 整放；
- 同日窗口 [start<end)：start 闭、end 开；
- start==end → 全天静默。
  审查 A-15：全天静默语义待产品裁定，此处仅按实现现状如实锁死。
- 豁免优先级：enabled 开关 > bypass_roles（大小写不敏感）> session_types 过滤
  > 窗口判定 > direct_request。
- E05 缺口三改判据后的形状：direct_request 缺省＝`@bot` **且**命令类能力才豁免
  （`∧`）；`session_types` 缺省含 private。旧 `∨` 形状经
  `direct_bypass_requires_both=False` 止血回退（配对锁见本文件 direct_request 段）。
- 非法时间串/时区在 pydantic 校验期即拒绝（ValidationError）；settings 为
  callable 时求值异常或类型不对 → 回退默认（enabled=False，不误拦消息）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
    QuietHoursChecker,
    QuietHoursSettings,
    build_quiet_hours_checker,
    build_quiet_hours_settings,
)


def _utc(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 14, hour, minute, tzinfo=timezone.utc)


def _naive(hour: int, minute: int) -> datetime:
    # 故意无 tzinfo：测试实现把 naive 时钟当 UTC 的现状。
    return datetime(2026, 9, 14, hour, minute)  # noqa: DTZ001


def _settings(**overrides) -> QuietHoursSettings:
    base: dict = {
        "enabled": True,
        "start_time": "23:00",
        "end_time": "07:00",
        "timezone_name": "UTC",
    }
    base.update(overrides)
    return QuietHoursSettings(**base)


def _msg(
    session_type: SessionType = SessionType.GROUP,
    *,
    roles: tuple[str, ...] = ("user",),
    mentions: bool = False,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot1",
        session_id="g1" if session_type is SessionType.GROUP else "p1",
        session_type=session_type,
        sender_id="u1",
        sender_roles=list(roles),
        mentions_bot=mentions,
    )


def _checker(
    settings: QuietHoursSettings | None = None,
    *,
    clock,
) -> QuietHoursChecker:
    return QuietHoursChecker(settings or _settings(), clock=clock)


# ---------------------------------------------------------------------------
# 开关
# ---------------------------------------------------------------------------


def test_disabled_gate_allows_even_inside_window() -> None:
    checker = _checker(_settings(enabled=False), clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "disabled"


def test_default_construction_is_disabled_allows() -> None:
    # 无参构造（生产兜底形态）：enabled 缺省 False，任何时刻都放行。
    checker = QuietHoursChecker()
    decision = checker.check(_msg(), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "disabled"


# ---------------------------------------------------------------------------
# 跨午夜窗口（start > end）：[23:00, 次日 06:00)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute", "expect_allowed"),
    [
        (23, 0, False),  # start 闭区间：整点即拦
        (23, 30, False),
        (0, 0, False),  # 午夜仍在窗口内
        (5, 59, False),
        (6, 0, True),  # end 开区间：整点即放
        (6, 1, True),
        (22, 59, True),
    ],
)
def test_cross_midnight_window_boundaries(
    hour: int, minute: int, expect_allowed: bool
) -> None:
    checker = _checker(_settings(end_time="06:00"),
                       clock=lambda: _utc(hour, minute))
    decision = checker.check(_msg(), "bot.chat")
    assert decision.allowed is expect_allowed
    if expect_allowed:
        assert decision.reason == "outside_quiet_hours"
    else:
        assert decision.reason == "quiet_hours"


# ---------------------------------------------------------------------------
# 同日窗口（start < end）：[06:00, 23:00)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute", "expect_allowed"),
    [
        (6, 0, False),
        (12, 0, False),
        (22, 59, False),
        (23, 0, True),  # end 开区间
        (5, 59, True),
    ],
)
def test_same_day_window_boundaries(
    hour: int, minute: int, expect_allowed: bool
) -> None:
    checker = _checker(_settings(start_time="06:00", end_time="23:00"),
                       clock=lambda: _utc(hour, minute))
    decision = checker.check(_msg(), "bot.chat")
    assert decision.allowed is expect_allowed


# ---------------------------------------------------------------------------
# start == end：按实现现状 = 全天静默
# 审查 A-15：全天静默语义待产品裁定，此处只锁现状，不改判定。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("hour", "minute"), [(0, 0), (12, 0), (23, 59)])
def test_start_equals_end_blocks_all_day(hour: int, minute: int) -> None:
    checker = _checker(_settings(start_time="00:00", end_time="00:00"),
                       clock=lambda: _utc(hour, minute))
    decision = checker.check(_msg(), "bot.chat")
    assert decision.allowed is False
    assert decision.reason == "quiet_hours"


def test_start_equals_end_nonzero_value_also_all_day() -> None:
    checker = _checker(_settings(start_time="08:00", end_time="08:00"),
                       clock=lambda: _utc(8, 0))
    assert checker.check(_msg(), "bot.chat").allowed is False


# ---------------------------------------------------------------------------
# BYPASS_ROLES 豁免
# ---------------------------------------------------------------------------


def test_admin_bypass_inside_window() -> None:
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(roles=("admin",)), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "role_bypass"


def test_bypass_role_match_case_insensitive() -> None:
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(roles=("ADMIN",)), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "role_bypass"


def test_settings_bypass_roles_normalized_case() -> None:
    settings = _settings(bypass_roles=["Super_Admin "])
    checker = _checker(settings, clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(roles=("super_admin",)), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "role_bypass"


def test_non_bypass_role_still_blocked() -> None:
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(roles=("trusted",)), "bot.chat")
    assert decision.allowed is False
    assert decision.reason == "quiet_hours"


def test_custom_bypass_roles_replace_default_admin() -> None:
    settings = _settings(bypass_roles=["super_admin"])
    checker = _checker(settings, clock=lambda: _utc(23, 30))
    assert checker.check(_msg(roles=("admin",)), "bot.chat").allowed is False
    decision = checker.check(_msg(roles=("super_admin",)), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "role_bypass"


def test_role_bypass_precedes_session_type_filter() -> None:
    # 现状锁死：豁免判定在 session_types 过滤之前——私聊不在默认 session_types
    # 里，但 admin 仍以 role_bypass 放行（而非 session_type_excluded）。
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(SessionType.PRIVATE, roles=("admin",)), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "role_bypass"


# ---------------------------------------------------------------------------
# SESSION_TYPES 过滤（E05 缺口三：缺省含 group + private）
# ---------------------------------------------------------------------------


def test_private_session_is_covered_by_default() -> None:
    """缺省会话册含 private ⇒ 私聊不再整条免检（旧行为：session_type_excluded）。"""
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(SessionType.PRIVATE), "bot.chat")
    assert decision.allowed is False
    assert decision.reason == "quiet_hours"


def test_email_still_opt_in() -> None:
    """email 属配置面 opt-in（F1 口径不动）：新缺省册里没有它，未登记就是缺席。"""
    assert QuietHoursSettings().session_types == ["group", "private"]
    checker = _checker(_settings(session_types=["group"]), clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(SessionType.PRIVATE), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "session_type_excluded"


def test_group_session_blocked_inside_window() -> None:
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(SessionType.GROUP), "bot.chat")
    assert decision.allowed is False
    assert decision.reason == "quiet_hours"


def test_private_only_window_blocks_private() -> None:
    settings = _settings(session_types=["private"])
    checker = _checker(settings, clock=lambda: _utc(23, 30))
    assert checker.check(_msg(SessionType.PRIVATE), "bot.chat").allowed is False
    decision = checker.check(_msg(SessionType.GROUP), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "session_type_excluded"


def test_channel_session_always_excluded() -> None:
    # 校验器收 private/group/email（F1 修复，S-FIX-MAILINGRESS-R）；
    # channel/console 仍永远落在过滤白名单外。email 的「可收且 opt-in」形制
    # 由 tests/test_mail_ingress_locks.py F1 段执法。
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(SessionType.CHANNEL), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "session_type_excluded"


def test_session_types_normalized_case_and_space() -> None:
    settings = _settings(session_types=[" GROUP "])
    checker = _checker(settings, clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(SessionType.GROUP), "bot.chat")
    assert decision.allowed is False
    assert decision.reason == "quiet_hours"


def test_session_types_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        _settings(session_types=["guild"])


# ---------------------------------------------------------------------------
# direct_request 豁免（E05 缺口三：`@` 与非 chat 能力**同现**才旁路）
# 判据不吃文本形状——mentions_bot 与 capability_id 两维就够（命令文本长什么样
# 属路由侧的事，安静时间不该再第二条判据）。
# ---------------------------------------------------------------------------


def test_mentioned_command_bypasses_inside_window() -> None:
    """合法形：`@bot` + 命令类能力＝真点名办事，夜间照旧要能救。"""
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(mentions=True), "bot.music")
    assert decision.allowed is True
    assert decision.reason == "direct_request_bypass"
    assert "quiet_hours:direct_request_bypass" in decision.audit_tags


def test_command_without_mention_is_blocked() -> None:
    """越界形：不打 @ 的任意命令能力夜里不再白拿旁路（这就是缺口本身）。"""
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(), "bot.music")
    assert decision.allowed is False
    assert decision.reason == "quiet_hours"
    assert decision.audit_tags == [
        "quiet_hours:blocked",
        "quiet_hours:session:group",
        "quiet_hours:capability:bot.music",
    ]


def test_mentioned_chat_is_blocked_by_default() -> None:
    """只 @ 不说事（bot.chat）夜里不唤醒 bot——安静时间就是给 bot 睡觉用的。"""
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(mentions=True), "bot.chat")
    assert decision.allowed is False
    assert decision.reason == "quiet_hours"


@pytest.mark.parametrize(
    ("mentions", "capability_id", "expect_allowed"),
    [
        (True, "bot.chat", False),  # 旧形状里这一腿靠 mentions 免检
        (False, "bot.music", False),  # 旧形状里这一腿靠非 chat 免检
        (True, "bot.music", True),  # 两条件同现才免检
        (False, "bot.chat", False),
    ],
)
def test_and_truth_table(
    mentions: bool, capability_id: str, expect_allowed: bool
) -> None:
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(mentions=mentions), capability_id)
    assert decision.allowed is expect_allowed


def test_legacy_or_bypass_available_via_flag() -> None:
    """止血开关：direct_bypass_requires_both=False 逐字节回退旧 `∨` 语义。"""
    checker = _checker(
        _settings(direct_bypass_requires_both=False), clock=lambda: _utc(23, 30)
    )
    assert checker.check(_msg(mentions=True), "bot.chat").reason == (
        "direct_request_bypass"
    )
    assert checker.check(_msg(), "bot.music").reason == "direct_request_bypass"


def test_role_bypass_still_precedes_the_direct_leg() -> None:
    """顺序红线：admin 的 role_bypass 仍在最前，本门只动直连豁免那条腿。"""
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(roles=("admin",)), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "role_bypass"


@pytest.mark.parametrize("capability_id", ["bot.chat", "bot.content"])
def test_chat_and_content_capabilities_blocked(capability_id: str) -> None:
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(), capability_id)
    assert decision.allowed is False
    assert decision.reason == "quiet_hours"


def test_blocked_decision_carries_audit_tags() -> None:
    checker = _checker(clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(), "bot.chat")
    assert decision.allowed is False
    assert decision.audit_tags == [
        "quiet_hours:blocked",
        "quiet_hours:session:group",
        "quiet_hours:capability:bot.chat",
    ]


# ---------------------------------------------------------------------------
# 时区换算与 naive 时钟
# ---------------------------------------------------------------------------


def test_default_hongkong_timezone_conversion() -> None:
    # settings 缺省 Asia/Hong_Kong（UTC+8）：15:30Z = 23:30 本地 → 窗口内。
    settings = QuietHoursSettings(enabled=True, start_time="23:00", end_time="07:00")
    checker = QuietHoursChecker(settings, clock=lambda: _utc(15, 30))
    assert checker.check(_msg(), "bot.chat").allowed is False
    checker = QuietHoursChecker(settings, clock=lambda: _utc(14, 30))  # 22:30 本地
    decision = checker.check(_msg(), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "outside_quiet_hours"


def test_naive_clock_treated_as_utc() -> None:
    settings = _settings(timezone_name="UTC")
    checker = QuietHoursChecker(settings, clock=lambda: _naive(23, 30))
    assert checker.check(_msg(), "bot.chat").allowed is False
    checker = QuietHoursChecker(settings, clock=lambda: _naive(12, 0))
    assert checker.check(_msg(), "bot.chat").allowed is True


# ---------------------------------------------------------------------------
# settings 热改（callable provider）与求值容错
# ---------------------------------------------------------------------------


def test_settings_provider_hot_reload_takes_effect() -> None:
    state = {"enabled": False}
    checker = QuietHoursChecker(
        lambda: _settings(enabled=state["enabled"]),
        clock=lambda: _utc(23, 30),
    )
    assert checker.check(_msg(), "bot.chat").reason == "disabled"
    state["enabled"] = True
    decision = checker.check(_msg(), "bot.chat")
    assert decision.allowed is False
    assert decision.reason == "quiet_hours"


def test_settings_provider_exception_falls_back_to_default() -> None:
    def _boom() -> QuietHoursSettings:
        raise RuntimeError("store unavailable")

    checker = QuietHoursChecker(_boom, clock=lambda: _utc(23, 30))
    decision = checker.check(_msg(), "bot.chat")
    # 回退默认 = enabled=False：求值失败不误拦消息。
    assert decision.allowed is True
    assert decision.reason == "disabled"


def test_settings_provider_wrong_type_falls_back_to_default() -> None:
    checker = QuietHoursChecker(
        lambda: {"enabled": True},  # type: ignore[arg-type,return-value]
        clock=lambda: _utc(23, 30),
    )
    decision = checker.check(_msg(), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "disabled"


# ---------------------------------------------------------------------------
# 非法时间串 / 非法时区：校验期即拒绝（按实现现状锁死）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_time",
    ["24:00", "23:60", "-1:00", "abc", "23", "23:00:00", "", "  "],
)
def test_invalid_time_strings_rejected(bad_time: str) -> None:
    with pytest.raises(ValidationError):
        QuietHoursSettings(start_time=bad_time)
    with pytest.raises(ValidationError):
        QuietHoursSettings(end_time=bad_time)


def test_time_string_whitespace_trimmed() -> None:
    settings = _settings(start_time=" 23:30 ", end_time=" 06:00 ")
    assert settings.start_time == "23:30"
    assert settings.end_time == "06:00"


def test_unpadded_hm_accepted_and_treated_numerically() -> None:
    # 现状锁死：_parse_hhmm 不要求零填充，"7:5" 语义 = 07:05。
    settings = _settings(start_time="7:5", end_time="9:0")
    checker = _checker(settings, clock=lambda: _utc(7, 5))
    assert checker.check(_msg(), "bot.chat").allowed is False
    checker = _checker(settings, clock=lambda: _utc(6, 59))
    decision = checker.check(_msg(), "bot.chat")
    assert decision.allowed is True
    assert decision.reason == "outside_quiet_hours"


@pytest.mark.parametrize("bad_tz", ["", "  ", "Mars/Phobos"])
def test_invalid_timezone_rejected(bad_tz: str) -> None:
    with pytest.raises(ValidationError):
        QuietHoursSettings(timezone_name=bad_tz)


# ---------------------------------------------------------------------------
# config 装配入口
# ---------------------------------------------------------------------------


class _Config:
    bot_quiet_hours_enabled: ClassVar[bool] = True
    bot_quiet_hours_start: ClassVar[str] = "22:00"
    bot_quiet_hours_end: ClassVar[str] = "06:30"
    bot_quiet_hours_timezone: ClassVar[str] = "UTC"
    bot_quiet_hours_session_types: ClassVar[list[str]] = ["group", "private"]
    bot_quiet_hours_bypass_roles: ClassVar[list[str]] = ["admin", "super_admin"]
    bot_quiet_hours_direct_bypass_requires_both: ClassVar[bool] = False


def test_build_settings_from_config_maps_all_fields() -> None:
    settings = build_quiet_hours_settings(_Config())
    assert settings.enabled is True
    assert settings.start_time == "22:00"
    assert settings.end_time == "06:30"
    assert settings.timezone_name == "UTC"
    assert settings.session_types == ["group", "private"]
    assert settings.bypass_roles == ["admin", "super_admin"]
    assert settings.direct_bypass_requires_both is False


def test_build_settings_defaults_on_plain_object() -> None:
    settings = build_quiet_hours_settings(object())
    assert settings.enabled is False
    assert settings.start_time == "23:00"
    assert settings.end_time == "07:00"
    assert settings.session_types == ["group", "private"]
    assert settings.bypass_roles == ["admin"]
    # 缺口三的新缺省＝收紧形（Config 无字段时也照样生效，不靠三面登记才生效）。
    assert settings.direct_bypass_requires_both is True


def test_build_checker_uses_provider_when_given() -> None:
    provider_state = {"enabled": False}
    checker = build_quiet_hours_checker(
        _Config(),
        settings_provider=lambda: _settings(enabled=provider_state["enabled"]),
    )
    checker.clock = lambda: _utc(23, 30)  # 注入时钟，保持全离线
    assert checker.check(_msg(), "bot.chat").reason == "disabled"
    provider_state["enabled"] = True
    assert checker.check(_msg(), "bot.chat").allowed is False


def test_build_checker_snapshots_config_without_provider() -> None:
    checker = build_quiet_hours_checker(_Config())
    checker.clock = lambda: _utc(22, 30)
    decision = checker.check(_msg(), "bot.chat")
    assert decision.allowed is False
    assert decision.reason == "quiet_hours"

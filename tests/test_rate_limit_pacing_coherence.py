"""T7 节奏层「一致性 + 活性」补锁席（SEAT-W7 新建，与 test_rate_limit_pacing.py 互补）。

三件事，都是 ``test_rate_limit_pacing.py`` 那把尺**量不到**的面：

1. **清扫体的活性锁**。``InMemoryRateLimiter._maybe_sweep`` 只在
   ``time.monotonic() - _last_sweep >= 600`` 时执行，而 ``_last_sweep`` 在**构造时**
   就置为当下 ⇒ 离线套件里这条分支永不进树。本文件把节流计强制拨到过去，
   真正执行一次清扫：2026-09-24 落地时该分支内有一枚未定义名（``pacing``），
   NameError 只会在"重启约 10 分钟后的第一条群消息"上炸——**全绿套件看不见**。
2. **分钟帽在其可达形态下必须真的拦得住**。分钟帽与最小间隔是一对冗余参数
   （3 句 × 20 秒 = 60 秒），只在间隔被关掉/被豁免时才是唯一约束；本文件用
   ``group_pacing_min_interval_seconds=0`` 把间隔挪开，单独量分钟帽的形状：
   窗口内超帽即拦、最旧一格出窗即放（两把尺同轨迹）。
3. **节奏五键的名字必须是 config.py 上那五个名字**。本仓 ``extra="ignore"``
   ⇒ 键名写错等同没填（静默死键）。这两条把「装配口读得到」钉成生产装载路径的
   证据，而不只是手工替身的证据。

纪律：全离线、注入时钟、SQLite 走 tmp_path，零网络。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    InMemoryRateLimiter,
    RateLimitSettings,
    SQLiteRateLimiter,
    build_rate_limit_settings,
)

PACING_CONFIG_FIELDS = (
    "bot_rate_limit_group_pacing_tokens_per_hour",
    "bot_rate_limit_group_pacing_burst_capacity",
    "bot_rate_limit_group_pacing_max_per_minute",
    "bot_rate_limit_group_pacing_min_interval_seconds",
    "bot_rate_limit_group_vision_min_interval_seconds",
)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def _message(text: str = "在吗") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group_123456",
        session_type=SessionType.GROUP,
        sender_id="u1",
        group_id="123456",
        plain_text=text,
        raw_segments=[],
    )


def _settings(**overrides: Any) -> RateLimitSettings:
    base: dict[str, Any] = {
        "chat_global_max_requests": 10_000,
        "chat_session_max_requests": 10_000,
        "chat_sender_max_requests": 10_000,
        "group_pacing_tokens_per_hour": 30,
        "group_pacing_burst_capacity": 5,
        "group_pacing_max_per_minute": 3,
        "group_pacing_min_interval_seconds": 20,
    }
    base.update(overrides)
    return RateLimitSettings(**base)


@pytest.fixture
def both(tmp_path: Path):
    def _make(**overrides: Any):
        memory_clock = _Clock()
        sqlite_clock = _Clock()
        return [
            ("InMemory", InMemoryRateLimiter(_settings(**overrides), clock=memory_clock), memory_clock),
            (
                "SQLite",
                SQLiteRateLimiter(
                    tmp_path / f"coherence_{abs(hash(repr(sorted(overrides.items()))))}.db",
                    _settings(**overrides),
                    clock=sqlite_clock,
                ),
                sqlite_clock,
            ),
        ]

    return _make


# ------------------------------------------------------- ① 清扫体活性（NameError 面）


def test_sweep_branch_is_reachable_and_raises_nothing() -> None:
    """把节流计拨到过去 ⇒ 真跑一次清扫；清扫体里任何未定义名都会当场炸出来。

    两把牙：① **不抛**（2026-09-24 落地时该分支里有一枚未定义名，全绿套件跑不到这一行）；
    ② **真的清了**——过期的令牌状态必须被扔掉（把 `_maybe_sweep` 换成空转也必红）。
    """
    clock = _Clock()
    limiter = InMemoryRateLimiter(_settings(), clock=clock)
    assert limiter.check_and_record(_message("第一句"), "bot.chat").allowed is True
    assert limiter._pacing_tokens, "前置条件不成立：节奏层没建桶，本用例就是空跑"
    # 让令牌状态过期：idle_cap = 3600×B/x = 3600×5/30 = 600 秒，推进 700 秒必然越过。
    clock.advance(seconds=700)
    limiter._last_sweep = time.monotonic() - (limiter._SWEEP_INTERVAL_SECONDS + 1.0)
    limiter._maybe_sweep(clock())
    assert limiter._pacing_tokens == {}, "清扫未执行：过期令牌状态仍在（键集合无界增长）"
    # 清掉之后按"首见即满桶"重建 ⇒ 判定等价，不会把额度变成零。
    assert limiter.check_and_record(_message("清扫后"), "bot.chat").allowed is True


def test_sweep_keeps_recent_pacing_state(tmp_path: Path) -> None:
    """清扫只裁过期的：没到 idle_cap 的桶必须留着，否则额度凭空满血复活。"""
    clock = _Clock()
    limiter = InMemoryRateLimiter(
        _settings(group_pacing_max_per_minute=0, group_pacing_min_interval_seconds=0),
        clock=clock,
    )
    for _ in range(5):  # 打空 B=5
        assert limiter.check_and_record(_message("打光"), "bot.chat").allowed is True
    exhausted = limiter.check_and_record(_message("第6句"), "bot.chat")
    assert (exhausted.allowed, exhausted.reason) == (False, "group_pacing_tokens_exhausted")
    # 60 秒只回半格（30 句/小时 = 120 秒一格），既证明状态没被清扫掉，也证明清扫不回血。
    clock.advance(seconds=60)
    limiter._last_sweep = time.monotonic() - (limiter._SWEEP_INTERVAL_SECONDS + 1.0)
    denied = limiter.check_and_record(_message("清扫不该回血"), "bot.chat")
    assert denied.allowed is False, denied


# ------------------------------------------- ② 分钟帽在其可达形态下拦得住 / 出窗即放


def test_minute_cap_is_the_binding_constraint_when_interval_is_off(both) -> None:
    """间隔关掉后，分钟帽是唯一外骨架：窗内第 4 句必拦、最旧一格出窗必放。"""
    for name, limiter, clock in both(group_pacing_min_interval_seconds=0):
        for index in range(3):
            decision = limiter.check_and_record(_message(f"句{index}"), "bot.chat")
            assert decision.allowed is True, f"{name} 第 {index} 句被误拦 reason={decision.reason}"
        over_cap = limiter.check_and_record(_message("第4句"), "bot.chat")
        assert (over_cap.allowed, over_cap.reason) == (
            False,
            "group_pacing_minute_exceeded",
        ), f"{name}: 分钟帽未拦住第 4 句 → {over_cap.allowed}/{over_cap.reason}"
        assert over_cap.retry_after_seconds > 0, f"{name}: 拦下却没给解禁预告"
        clock.advance(seconds=61)  # 最旧一格出 60 秒窗
        after = limiter.check_and_record(_message("出窗后"), "bot.chat")
        assert after.allowed is True, f"{name}: 出窗后仍被拦 reason={after.reason}"


def test_minute_cap_counts_rolling_window_not_cumulative(both) -> None:
    """长跑口径：帽是滚动窗，不是"累计到封顶就永久静默"。

    令牌面抬到不会成为约束（600 句/时、容量 600），只留分钟帽这一道，
    看 21 秒间隔（= 3 句/分以内）能否持续放行。
    """
    for name, limiter, clock in both(
        group_pacing_min_interval_seconds=0,
        group_pacing_tokens_per_hour=600,
        group_pacing_burst_capacity=600,
    ):
        denied: list[int] = []
        for index in range(60):  # 每 21 秒一句，共 21 分钟
            if not limiter.check_and_record(_message("节奏"), "bot.chat").allowed:
                denied.append(index)
            clock.advance(seconds=21)
        assert not denied, f"{name}: 滚动窗被实现成累计账，被拦下标 {denied[:5]}（共 {len(denied)} 句）"


# -------------------------------------- ③ 五枚键名 = config.py 真身字段（生产装载路径）


def test_pacing_field_names_exist_on_real_config() -> None:
    """键名漂移 = 静默死键（本仓 extra=ignore）。装配口读的名字必须在册。"""
    from plugins.bot_unified_runtime.config import Config

    fields = set(Config.model_fields)
    missing = [name for name in PACING_CONFIG_FIELDS if name not in fields]
    assert not missing, f"config.py 缺字段：{missing}"


def test_pacing_values_flow_through_a_config_shaped_source() -> None:
    """值必须**按那五个名字**搬进 RateLimitSettings（名字写错这里就红）。"""

    class _Cfg:
        pass

    cfg = _Cfg()
    probes = {
        PACING_CONFIG_FIELDS[0]: 11,
        PACING_CONFIG_FIELDS[1]: 1,
        PACING_CONFIG_FIELDS[2]: 2,
        PACING_CONFIG_FIELDS[3]: 3,
        PACING_CONFIG_FIELDS[4]: 4,
    }
    for name, value in probes.items():
        setattr(cfg, name, value)
    settings = build_rate_limit_settings(cfg)
    assert settings.group_pacing_tokens_per_hour == 11, settings
    assert settings.group_pacing_burst_capacity == 1, settings
    assert settings.group_pacing_max_per_minute == 2, settings
    assert settings.group_pacing_min_interval_seconds == 3, settings
    assert settings.group_vision_min_interval_seconds == 4, settings


def test_missing_pacing_fields_fail_closed_to_layer_off() -> None:
    """读不到键 ⇒ 整层关（0），绝不允许"读不到"变成"自动开始限流"。"""
    from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
        group_pacing_applies,
    )

    class _Empty:
        pass

    settings = build_rate_limit_settings(_Empty())
    assert settings.group_pacing_tokens_per_hour == 0
    assert group_pacing_applies(settings, _message()) is False

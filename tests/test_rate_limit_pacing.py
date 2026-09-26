"""T7 群聊节奏波回归：B-1 幽灵扣减 + 令牌桶匀速节奏 + 群图并入同一节奏。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_rate_limit_pacing.py -q

三件事（用户裁定 2026-09-24：「群聊的图片/表情包接话必须跟主动回复频率走」
「想要 1 小时 30 句，但绝不允许开局瞬间打光后长时间静默」）：

1. **B-1 幽灵扣减**：被 session/sender/target 帽拒掉的消息，今天照样把群小时
   桶记满（真回 22 句却占掉 30 额度，T6 离线仿真 S1/S3/S3b）。修法是判定序改成
   **「先判后记」结构**：所有帽只判不写，全过之后统一落账。InMemory 与 SQLite
   两实现同犯、同修，本文件对两实现跑**同一份脚本**并逐条比对轨迹。
2. **令牌桶节奏**：小时额度改为按秒回血的桶（容量 B 限突发、速率 x/小时定长期
   额度），把「打光后静默 ≈ 整窗」压成「最坏静默 ≈ 3600/x 秒」。
3. **群图并入同一节奏**：图片/表情包类不再 100% 必回——与文字主动接话共用同一个
   群节奏桶，并额外受自己的独立最小间隔约束。

纪律：全部走公共入口 ``check_and_record``/``rollback`` + 注入时钟，零网络零真库
（SQLite 用 tmp_path）；静默时长是**测出来的**，不是手写的期望值。
"""
from __future__ import annotations

import zlib
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    InMemoryRateLimiter,
    RateLimitSettings,
    SQLiteRateLimiter,
)


class _Clock:
    """注入时钟：节奏与窗口的一切判定都必须由它驱动（可复现、可测试）。"""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def _message(
    text: str = "在吗",
    *,
    session_type: SessionType = SessionType.GROUP,
    group_id: str | None = "123456",
    sender_id: str = "u1",
    with_image: bool = False,
) -> IncomingMessage:
    raw_segments: list[dict[str, Any]] = []
    if with_image:
        # 生产形态的图片段（http URL 直传）。"这是图片"由限流器与门禁共用的同一个
        # 视觉谓词判定，测试绝不手写结论（本波已两次栽在手写被测前提上）。
        raw_segments = [{"type": "image", "data": {"url": "https://cdn.example/a.jpg"}}]
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=f"group_{group_id}" if group_id else f"private:{sender_id}",
        session_type=session_type,
        sender_id=sender_id,
        group_id=group_id,
        plain_text=text,
        raw_segments=raw_segments,
    )


# 抬高与当前用例无关的窗口帽，聚焦被测维度（与 test_group_rate_limit 同法）。
_WIDE: dict[str, int] = {
    "chat_global_max_requests": 10_000,
    "chat_session_max_requests": 10_000,
    "chat_sender_max_requests": 10_000,
}


def _settings(**overrides: Any) -> RateLimitSettings:
    base = dict(_WIDE)
    base.update(overrides)
    return RateLimitSettings(**base)


def _memory(clock: _Clock, **overrides: Any) -> InMemoryRateLimiter:
    return InMemoryRateLimiter(_settings(**overrides), clock=clock)


def _sqlite(
    clock: _Clock, tmp_path: Path, name: str, **overrides: Any
) -> SQLiteRateLimiter:
    return SQLiteRateLimiter(tmp_path / name, _settings(**overrides), clock=clock)


@pytest.fixture
def both(tmp_path: Path):
    """同参构造两个实现：两把尺必须量出同一条轨迹（本仓被"后端偷偷不一致"咬过）。"""

    def _make(**overrides: Any):
        memory_clock = _Clock()
        sqlite_clock = _Clock()
        return [
            (
                "InMemory",
                _memory(memory_clock, **overrides),
                memory_clock,
            ),
            (
                "SQLite",
                _sqlite(sqlite_clock, tmp_path, f"rl_{_digest(overrides)}.db", **overrides),
                sqlite_clock,
            ),
        ]

    return _make


def _digest(overrides: dict[str, Any]) -> str:
    """按参数给用例各自的库文件，避免跨用例互相污染记账（键名含 ``=`` 不宜入文件名）。"""
    return format(zlib.crc32(repr(sorted(overrides.items())).encode("utf-8")), "08x")


def _trace(
    limiter: Any, clock: _Clock, steps: list[tuple[str, int]]
) -> list[tuple[str, bool, str]]:
    """按 (文本, 之前前进秒数) 脚本跑一遍，返回 (步名, allowed, reason) 轨迹。"""
    trail: list[tuple[str, bool, str]] = []
    for label, advance_seconds in steps:
        if advance_seconds:
            clock.advance(seconds=advance_seconds)
        decision = limiter.check_and_record(_message(label), "bot.chat")
        trail.append((label, decision.allowed, decision.reason))
    return trail


# =================================================================== ① B-1 幽灵扣减


def test_sender_cap_rejection_does_not_consume_group_hour_budget(both) -> None:
    """被 sender 帽拒掉的那几句**没回**，就不该占群小时额度（B-1 主案）。

    修前实况：群窗口先判先记，之后才轮到 sender 帽拒绝 ⇒ 幽灵记账，小时帽被
    "其实没发出去的话"占满 ⇒ 用户看到的就是"没回几句却静默一小时"。
    """
    for name, limiter, clock in both(
        chat_sender_max_requests=1, group_hourly_max_requests=2
    ):
        # 第 1 句：放行（群小时 1/2、sender 1/1）。
        first = limiter.check_and_record(_message("句1"), "bot.chat")
        assert (first.allowed, first.reason) == (True, "allowed"), name
        # 第 2 句：同 sender 同刻，被 sender 帽拒（修前它还会顺手记满群小时桶）。
        second = limiter.check_and_record(_message("句2"), "bot.chat")
        assert (second.allowed, second.reason) == (
            False,
            "sender_window_exceeded",
        ), name
        # sender 窗滚出后（60s 帽、走 61s），小时桶只该占着第 1 句那一格。
        clock.advance(seconds=61)
        third = limiter.check_and_record(_message("句3"), "bot.chat")
        assert third.allowed is True, (
            f"{name}: 被拒的消息不得占用群小时额度（幽灵扣减未修），"
            f"实得 reason={third.reason}"
        )
        assert third.reason == "allowed", name


def test_target_interval_rejection_does_not_consume_group_hour_budget(both) -> None:
    """B-1 第二面：target 最小间隔拒绝同样不得记账。"""
    for name, limiter, clock in both(
        target_min_interval_seconds=30, group_hourly_max_requests=2
    ):
        first = limiter.check_and_record(_message("句1"), "bot.chat")
        assert (first.allowed, first.reason) == (True, "allowed"), name
        clock.advance(seconds=5)
        denied = limiter.check_and_record(_message("句2"), "bot.chat")
        assert (denied.allowed, denied.reason) == (False, "target_min_interval"), name
        clock.advance(seconds=61)
        after = limiter.check_and_record(_message("句3"), "bot.chat")
        assert after.allowed is True, (
            f"{name}: 间隔拒绝不得占用群小时额度，实得 reason={after.reason}"
        )


def test_session_cap_rejection_does_not_consume_group_minute_budget(both) -> None:
    """B-1 第三面：session 帽拒绝不得占分钟桶（T6 S3：allowed=1、denied=1、桶 2 条）。

    时间轴刻意卡在 57s/58s/61s：两句"没回的话"各留一格幽灵账（t=57、t=58），
    到 t=61 时真回复那格（t=0）已滑出分钟窗，幽灵两格还在 ⇒ 修前分钟帽（2 句）
    被两句没回的话占满、句4 被 group_minute_exceeded 冤死。
    句3 的理由本身就是幽灵的指纹：修前它是 group_minute_exceeded（被 1 秒前那句
    没回的话挤掉），修后才是它真正撞上的 session 帽。
    """
    for name, limiter, clock in both(
        chat_session_max_requests=1, group_minute_max_requests=2
    ):
        assert limiter.check_and_record(_message("句1"), "bot.chat").allowed is True
        clock.advance(seconds=57)
        denied = limiter.check_and_record(_message("句2"), "bot.chat")
        assert (denied.allowed, denied.reason) == (False, "session_window_exceeded"), name
        clock.advance(seconds=1)
        denied_again = limiter.check_and_record(_message("句3"), "bot.chat")
        assert (denied_again.allowed, denied_again.reason) == (
            False,
            "session_window_exceeded",
        ), name
        clock.advance(seconds=3)
        after = limiter.check_and_record(_message("句4"), "bot.chat")
        assert after.allowed is True, (
            f"{name}: 幽灵扣减未修（句2/句3 没回却占了分钟额度），reason={after.reason}"
        )


def test_group_budget_trace_is_identical_across_implementations(both) -> None:
    """两实现跑同一脚本 ⇒ 同一条 (allowed, reason) 轨迹，且放行句数不含被拒尝试。

    脚本口径：sender 帽 1 句/60s、群小时帽 3 句。同 sender 的重复尝试必然被拒，
    它们**一句都没回**，所以小时额度只由真回复消耗：句1/句2/句3 打满 3 格后，
    句4 才被群小时帽拦下（幽灵记账会提前一格把它拦死）。
    """
    steps = [
        ("句1", 0),
        ("句1b", 2),   # 同 sender 2 秒后再来：被 sender 帽拒
        ("句2", 61),
        ("句2b", 2),   # 同样被拒
        ("句3", 61),
        ("句4", 61),
        ("句5", 3540),  # 距最早的真回复越过 3600s，小时额度才滑出
    ]
    trails = []
    for name, limiter, clock in both(
        chat_sender_max_requests=1, group_hourly_max_requests=3
    ):
        trails.append(_trace(limiter, clock, steps))
    assert trails[0] == trails[1], "InMemory 与 SQLite 判定序不等价"
    assert [label for label, ok, _ in trails[0] if ok] == ["句1", "句2", "句3", "句5"], (
        trails[0]
    )
    reasons = {(label, ok): reason for label, ok, reason in trails[0]}
    assert reasons[("句1b", False)] == "sender_window_exceeded", trails[0]
    assert reasons[("句2b", False)] == "sender_window_exceeded", trails[0]
    assert reasons[("句4", False)] == "group_hour_exceeded", trails[0]


# =================================================================== ② 令牌桶节奏

_PACING = {
    # 用户裁定 2026-09-24 的四个数（T6 建议缺省起步）：1 小时 30 句、可连发 5 句、
    # 每分钟 3 句、相邻两句至少隔 20 秒。
    "group_pacing_tokens_per_hour": 30,
    "group_pacing_burst_capacity": 5,
    "group_pacing_max_per_minute": 3,
    "group_pacing_min_interval_seconds": 20,
}


def _pacing(**overrides: Any) -> dict[str, Any]:
    base = dict(_PACING)
    base.update(overrides)
    return base


def _replied_times(
    limiter: Any,
    clock: _Clock,
    *,
    arrivals: int,
    every_seconds: int,
) -> list[datetime]:
    """喂一条"刷屏群"流量（每 ``every_seconds`` 秒一句、共 ``arrivals`` 句），返回真放行时刻。

    静默时长由这条时间线**量出来**，不是写进断言的期望值。
    """
    replied: list[datetime] = []
    for _ in range(arrivals):
        decision = limiter.check_and_record(_message("图来了"), "bot.chat")
        if decision.allowed:
            replied.append(clock.now)
        clock.advance(seconds=every_seconds)
    return replied


def _worst_silence_seconds(replied: list[datetime]) -> float:
    gaps = [
        (later - earlier).total_seconds()
        for earlier, later in pairwise(replied)
    ]
    return max(gaps) if gaps else -1.0


def test_pacing_layer_is_inert_when_hour_tokens_are_zero(both) -> None:
    """0 = 整层不生效（与仓内"0=不生效"同口径）：默认参数下零行为变更。"""
    for name, limiter, clock in both():
        for index in range(200):
            decision = limiter.check_and_record(_message(f"句{index}"), "bot.chat")
            assert decision.allowed is True, f"{name} 第 {index} 句被误拦"


def test_burst_capacity_is_the_only_opening_run(both) -> None:
    """开局连发上限＝桶容量 B（用户红线："绝不允许开局瞬间打光"）。"""
    for name, limiter, _clock in both(**_pacing(group_pacing_max_per_minute=0,
                                                group_pacing_min_interval_seconds=0)):
        allowed = [
            limiter.check_and_record(_message(f"句{i}"), "bot.chat").allowed
            for i in range(12)
        ]
        assert allowed[:5] == [True] * 5, name
        assert allowed[5:] == [False] * 7, f"{name}: 突发未被桶容量 B=5 掐住 → {allowed}"


def test_bucket_refills_at_the_hourly_rate(both) -> None:
    """桶空后每 3600/x 秒必回一句：x=30 ⇒ 120 秒一句（这是"最长静默"的物理上界）。"""
    for name, limiter, clock in both(
        **_pacing(group_pacing_max_per_minute=0, group_pacing_min_interval_seconds=0)
    ):
        for _ in range(5):  # 打空 B=5
            assert limiter.check_and_record(_message("打光"), "bot.chat").allowed is True
        denied = limiter.check_and_record(_message("第6句"), "bot.chat")
        assert (denied.allowed, denied.reason) == (
            False,
            "group_pacing_tokens_exhausted",
        ), name
        clock.advance(seconds=119)
        assert limiter.check_and_record(_message("还差1秒"), "bot.chat").allowed is False, name
        clock.advance(seconds=2)
        back = limiter.check_and_record(_message("回血到点"), "bot.chat")
        assert (back.allowed, back.reason) == (True, "allowed"), name
        assert denied.retry_after_seconds <= 121, (
            f"{name}: 解禁预告应贴近回血节拍，实得 {denied.retry_after_seconds}"
        )


def test_minute_cap_and_min_interval_shape_the_sustained_rate(both) -> None:
    """节奏层的外骨架：相邻至少 20 秒；而在 20 秒间隔下，分钟帽**结构上轮不到它当约束**。

    ⚠ 本条原写法断的是"第 4 句被 `group_pacing_minute_exceeded` 拦"，实测永不可能成立：
    帽 3 句/分 与 间隔 20 秒满足 3×20=60，而分钟窗的 prune 判据是
    `age >= PACING_MINUTE_WINDOW_SECONDS`（窗长 60 秒），⇒ 任何一格满 60 秒龄就先出窗，
    于是 60 秒窗内永远凑不满第 4 句，约束非豁免流量的一直是最小间隔。
    ★ 而且这条冗余**与间隔开关无关**：主代理实测把间隔调成 0、仍按 21 秒步距打五句，五句全放行
      —— 因为 21 秒步距本身就把到达率限死在 3 句/分以内（60/21<3）。
      分钟帽真正会拦的只有"亚 20 秒突发"，而那形态恰好被 20 秒间隔门禁掉
      ⇒ **对非豁免流量，分钟帽是一格恒冗余**；它只在情绪豁免命中、或被显式调成
      `group_pacing_min_interval_seconds=0` 且来速快于 20 秒时才是唯一约束。
    分钟帽的**可达**覆盖在两处：
    `test_rate_limit_pacing_coherence.py::test_minute_cap_is_the_binding_constraint_when_interval_is_off`
    （间隔关掉、同一时刻连打四句）与 `::test_minute_cap_counts_rolling_window_not_cumulative`（滚动窗语义）。
    这里保留"第 4 句放行"这一断言，目的是把上面那条算术分工**钉住**：
    谁把间隔调到 <20 秒、或把分钟帽调低，这一格就会当场改判——那正是逼他重看两道约束分工的时机。
    """
    for name, limiter, clock in both(**_pacing()):
        assert limiter.check_and_record(_message("第1句"), "bot.chat").allowed is True
        too_soon = limiter.check_and_record(_message("紧接着"), "bot.chat")
        assert (too_soon.allowed, too_soon.reason) == (
            False,
            "group_pacing_min_interval",
        ), name
        clock.advance(seconds=21)
        assert limiter.check_and_record(_message("第2句"), "bot.chat").allowed is True
        clock.advance(seconds=21)
        assert limiter.check_and_record(_message("第3句"), "bot.chat").allowed is True
        clock.advance(seconds=21)  # 间隔够；窗内已用两格，第 4 格进窗时最旧那格已出窗
        sustained = limiter.check_and_record(_message("第4句"), "bot.chat")
        assert sustained.allowed is True, (
            f"{name}: 20 秒间隔下分钟帽本不该成为约束，却把第 4 句拦了 →"
            f" {sustained.reason}（说明两帽分工变了，去看本条 docstring 的算术）"
        )


def test_pacing_does_not_reach_private_chat_or_mentions(both) -> None:
    """节奏只罩群聊非点名流量：私聊有问必回、@ 与命令照旧免检（人格教义）。"""
    for name, limiter, clock in both(**_pacing()):
        for index in range(20):
            private = limiter.check_and_record(
                _message(f"私聊{index}", session_type=SessionType.PRIVATE, group_id=None),
                "bot.chat",
            )
            assert private.allowed is True, f"{name}: 私聊被群节奏误拦 reason={private.reason}"
        for index in range(20):
            mentioned = limiter.check_and_record(
                _message(f"点名{index}"), "bot.chat", interactive=True
            )
            assert mentioned.allowed is True, f"{name}: @点名被群节奏误拦"


def test_pacing_state_survives_a_new_limiter_instance(tmp_path: Path) -> None:
    """SQLite 态桶是持久账：重启/换实例不得让额度满血复活（B-2 的桶面）。"""
    clock = _Clock()
    first = _sqlite(
        clock,
        tmp_path,
        "rl_persist.db",
        **_pacing(group_pacing_max_per_minute=0, group_pacing_min_interval_seconds=0),
    )
    for _ in range(5):
        assert first.check_and_record(_message("打光"), "bot.chat").allowed is True
    second = _sqlite(
        clock,
        tmp_path,
        "rl_persist.db",
        **_pacing(group_pacing_max_per_minute=0, group_pacing_min_interval_seconds=0),
    )
    drained = second.check_and_record(_message("新实例"), "bot.chat")
    assert (drained.allowed, drained.reason) == (
        False,
        "group_pacing_tokens_exhausted",
    ), "SQLite 桶未持久化：换实例即满血"


def test_rollback_returns_pacing_quota(both) -> None:
    """能力失败回滚（A-18）必须连节奏账一起退，否则失败的回复白占额度。"""
    for name, limiter, _clock in both(
        **_pacing(group_pacing_max_per_minute=0, group_pacing_min_interval_seconds=0)
    ):
        message = _message("会失败的一句")
        decision = limiter.check_and_record(message, "bot.chat")
        assert decision.allowed is True, name
        for _ in range(4):
            assert limiter.check_and_record(_message("打光"), "bot.chat").allowed is True
        exhausted = limiter.check_and_record(_message("第7句"), "bot.chat")
        assert exhausted.allowed is False, name

        limiter.rollback(message, "bot.chat", reason="allowed")

        refunded = limiter.check_and_record(_message("回滚后又一句"), "bot.chat")
        assert refunded.allowed is True, (
            f"{name}: rollback 未归还节奏额度，reason={refunded.reason}"
        )


def test_pacing_rejects_negative_parameters() -> None:
    for key in (
        "group_pacing_tokens_per_hour",
        "group_pacing_burst_capacity",
        "group_pacing_max_per_minute",
        "group_pacing_min_interval_seconds",
        "group_vision_min_interval_seconds",
    ):
        with pytest.raises(ValueError):
            _settings(**{key: -1})


def test_pacing_settings_are_read_from_config_fields() -> None:
    """五枚节奏参数必须有真读点（否则键是死的、.env 填了不生效）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
        build_rate_limit_settings,
    )

    class _Cfg:
        bot_rate_limit_group_pacing_tokens_per_hour = 30
        bot_rate_limit_group_pacing_burst_capacity = 5
        bot_rate_limit_group_pacing_max_per_minute = 3
        bot_rate_limit_group_pacing_min_interval_seconds = 20
        bot_rate_limit_group_vision_min_interval_seconds = 120

    settings = build_rate_limit_settings(_Cfg())
    assert settings.group_pacing_tokens_per_hour == 30
    assert settings.group_pacing_burst_capacity == 5
    assert settings.group_pacing_max_per_minute == 3
    assert settings.group_pacing_min_interval_seconds == 20
    assert settings.group_vision_min_interval_seconds == 120


# ---------------------------------------------------- 突发打光 → 静默（实测上界）


def test_hour_cap_alone_still_drains_then_goes_silent() -> None:
    """反例基线（修前形态，只开小时帽 30）：两分钟打光、随后近一小时全哑。

    这条锁的是"为什么必须换节奏层"：静默时长由时间线量出，不是手写常数。
    """
    clock = _Clock()
    limiter = _memory(clock, group_hourly_max_requests=30)
    replied = _replied_times(limiter, clock, arrivals=700, every_seconds=6)
    assert len(replied) >= 30
    assert _worst_silence_seconds(replied) > 3000, (
        f"仅小时帽的突发形态已改变（实测最长静默 "
        f"{_worst_silence_seconds(replied):.0f}s），本基线需重新定性"
    )


def test_pacing_keeps_replies_available_instead_of_going_silent(both) -> None:
    """同一条刷屏时间线换成节奏层：最长静默从"近一小时"压到 2 分钟量级。"""
    for name, limiter, clock in both(**_pacing()):
        replied = _replied_times(limiter, clock, arrivals=700, every_seconds=6)
        assert len(replied) >= 5, f"{name}: 开局连发被掐死"
        worst = _worst_silence_seconds(replied)
        assert 0 < worst <= 240, (
            f"{name}: 令牌桶未能给出匀速节奏，实测最长静默 {worst:.0f}s"
        )


# =================================================================== ③ 群图并入同一节奏（待写）

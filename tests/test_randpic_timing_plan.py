"""随机发图「三时机」决策件的行为锁（席 PIC，需求 15）。

判据本体＝``domains/meme/capabilities/randpic_timing.plan_randpic``：一件**纯函数**
（时机 × 概率 × 冷却 × 去重账），不读配置、不碰时钟、不做 IO——时钟与骰子由调用侧
交进来，所以「这一轮到底发不发、为什么不发」在离线测试里可判定、可复现。
根装配文件（``__init__.py``，本席禁写面）需要的接线块写在 ``patch-PIC.md``。

四格：
① 三时机各自の门：指令路（用户开口）只要开关与货；两条主动路还要概率/冷却/
   每小时上限/blocked/安静窗——**顺序即语义**，安静窗与名单不许烧冷却；
② hold 必带代号，不许静默 return（旧写法六处 ``return`` 全无留痕，用户与审计都
   不知道这一轮为什么没图）；
③ 桶账与会话键形状单源（``canonical_bucket_key``），私聊按人、群聊按群，两腿同账；
④ seed 恒非空、含「时机+会话+消息」三维：同一条消息重放判定恒定（可复现），
   不同消息不会永远算到同一张（不得总发同一张）；指令路 seed 与能力层那枚字面
   f-string 逐字节对齐（AST 锁住的是那处，本件只对它，不搬走）。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.meme.capabilities import (
    randpic_timing as timing,
)


def _knobs(**overrides: object) -> timing.RandpicKnobs:
    base: dict[str, object] = {
        "enabled": True,
        "probability": 0.5,
        "cooldown_seconds": 600.0,
        "max_per_hour": 2,
        "window_seconds": 0.0,
    }
    base.update(overrides)
    return timing.RandpicKnobs(**base)  # type: ignore[arg-type]


def _turn(timing_name: str, **overrides: object) -> timing.RandpicTurn:
    base: dict[str, object] = {
        "timing": timing_name,
        "session_key": "group_42_7",
        "message_key": "msg-1",
        "group_id": "42",
        "user_id": "7",
    }
    base.update(overrides)
    return timing.RandpicTurn(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------- ① 三时机的门


def test_command_timing_sends_whenever_switched_on() -> None:
    """用户开口要图：不吃概率、不吃冷却（拒发才是更糟的行为）。"""
    plan = timing.plan_randpic(
        _turn(timing.TIMING_COMMAND),
        _knobs(enabled=True, probability=0.0, cooldown_seconds=99999.0),
        seed=timing.dispatch_seed(timing.TIMING_COMMAND, "group_42_7", "msg-1"),
        gate_verdict=(False, "gate_probability"),
    )
    assert plan.send is True
    assert plan.allow_exhausted is True
    assert plan.reason == "command"


def test_command_timing_respects_the_master_switch() -> None:
    plan = timing.plan_randpic(
        _turn(timing.TIMING_COMMAND), _knobs(enabled=False), seed="s", 
    )
    assert plan.send is False
    assert plan.reason == "disabled"


@pytest.mark.parametrize(
    "case,kwargs,expected",
    [
        ("关闭", {"knobs": _knobs(enabled=False)}, "disabled"),
        ("名单", {"blocked": True}, "blocked_target"),
        ("安静窗", {"quiet_active": True}, "quiet_hours"),
        ("无目标", {"turn_over": {"user_id": ""}}, "no_target"),
        ("概率未中", {"gate_verdict": (False, "gate_probability")}, "gate_probability"),
        ("冷却中", {"gate_verdict": (False, "gate_cooldown")}, "gate_cooldown"),
        ("每小时上限", {"gate_verdict": (False, "gate_hourly_cap")}, "gate_hourly_cap"),
        ("同消息已发过", {"gate_verdict": (False, "gate_already_reacted")}, "gate_already_reacted"),
    ],
)
def test_proactive_timings_hold_with_their_own_reason(case: str, kwargs: dict, expected: str) -> None:
    """主动腿的每一格拒绝都要有自己的代号——六处静默 return 的旧形态不许复活。"""
    overrides = dict(kwargs)
    turn_over = overrides.pop("turn_over", None)
    turn = _turn(timing.TIMING_AFTER_REPLY, **(turn_over or {}))
    plan = timing.plan_randpic(
        turn, overrides.pop("knobs", _knobs()), seed="s", **overrides
    )
    assert plan.send is False, case
    assert plan.reason == expected, case
    assert plan.audit_tags, "hold 也必须留痕"


def test_proactive_leg_never_recycles_a_recently_sent_image() -> None:
    """主动腿 allow_exhausted=False：整库都在窗内时不发（宁缺不刷屏），指令腿才回收。"""
    for name in (timing.TIMING_AFTER_REPLY, timing.TIMING_POKE):
        plan = timing.plan_randpic(_turn(name), _knobs(), seed="s")
        assert plan.send is True and plan.allow_exhausted is False, name


def test_quiet_hours_and_blocked_run_before_the_gate_verdict() -> None:
    """顺序即语义：安静窗/名单拦下时，五层门的「已放行」也不算数。

    门链的 commit 语义住在调用侧（``ProactiveGate.allow`` 返回 True 即登记冷却），
    判定件因此**只接受数据**（``gate_verdict`` 元组）而不接受门对象：把对象交进来
    就等于在这里替调用侧烧掉一次冷却——「被安静窗拦下」记进冷却等于让拦不住的门
    反咬后续动作。本件用「门已放行 + 安静窗开着 ⇒ 仍 hold」证明这条顺序。
    """
    plan = timing.plan_randpic(
        _turn(timing.TIMING_AFTER_REPLY),
        _knobs(),
        seed="s",
        quiet_active=True,
        gate_verdict=(True, ""),
    )
    assert plan.send is False and plan.reason == "quiet_hours"


def test_gate_state_enters_as_data_not_as_an_object() -> None:
    params = inspect.signature(timing.plan_randpic).parameters
    assert params["gate_verdict"].default is None, "缺省必须是「还没掷骰」"
    assert not any(
        name in {"gate", "store", "window", "ledger", "dispatcher"} for name in params
    ), "判定件接受了门/账本对象 ⇒ commit 会发生在纯函数里"


def test_two_stage_contract_keeps_the_gate_last() -> None:
    """两阶段契约：便宜门全过 ⇒ 先回 ``gate_pending``，调用侧这才准叫五层门。

    门的 ``verdict``/``allow`` 判定即 commit（登记冷却+滑窗）。若判定件让调用侧
    「先把门跑了再交进来」，被安静窗/名单拦下的那一轮就白烧了一次冷却——
    拦不住的门反咬后续动作，正是 ``proactive_action_allowed`` 那条顺序判据要防的。
    """
    stage_one = timing.plan_randpic(_turn(timing.TIMING_AFTER_REPLY), _knobs(), seed="s")
    assert stage_one.send is True and stage_one.reason == "gate_pending"
    stage_two = timing.plan_randpic(
        _turn(timing.TIMING_AFTER_REPLY), _knobs(), seed="s", gate_verdict=(True, "")
    )
    assert stage_two.send is True and stage_two.reason == "planned_after_reply"
    blocked_first = timing.plan_randpic(
        _turn(timing.TIMING_AFTER_REPLY),
        _knobs(),
        seed="s",
        blocked=True,
        gate_verdict=(True, ""),
    )
    assert blocked_first.reason == "blocked_target", "名单拦下时门已经跑过 ⇒ 顺序被写反了"


# ---------------------------------------------------------- ② 纯函数与确定性


def test_plan_is_pure_and_deterministic() -> None:
    a = timing.plan_randpic(_turn(timing.TIMING_POKE), _knobs(), seed="poke:a")
    b = timing.plan_randpic(_turn(timing.TIMING_POKE), _knobs(), seed="poke:a")
    assert a == b, "同输入必须同输出（纯函数：内部不许藏时钟/随机）"


def test_plan_carries_no_wall_clock_or_random_dependency() -> None:
    source = Path(timing.__file__).read_text(encoding="utf-8")
    body = source.split("def plan_randpic", 1)[1].split("\ndef ", 1)[0]
    for token in ("time.", "random.", "getattr(", "open(", "Path(", ".resolve("):
        assert token not in body, f"判定本体里出现了 {token} ⇒ 不再是纯函数"


# ---------------------------------------------------------- ③ 桶账形状单源


@pytest.mark.parametrize(
    "session_key,expected",
    [
        ("group_42_7", "group_42"),
        ("group_42", "group_42"),
        ("private_7", "private_7"),
        ("", ""),
    ],
)
def test_bucket_key_uses_the_single_canonical_shape(session_key: str, expected: str) -> None:
    plan = timing.plan_randpic(_turn(timing.TIMING_AFTER_REPLY, session_key=session_key), _knobs(), seed="s")
    assert plan.bucket_key == expected


def test_group_and_private_scopes_are_the_same_ledger_as_randpic() -> None:
    """桶账真身在 ``randpic.canonical_bucket_key``，本件只许用它（禁第二把尺）。"""
    from plugins.bot_unified_runtime.domains.meme.capabilities import randpic

    for key in ("group_42_7", "private_7", "group_42"):
        assert (
            timing.plan_randpic(_turn(timing.TIMING_POKE, session_key=key), _knobs(), seed="s").bucket_key
            == randpic.canonical_bucket_key(key)
        )


# ---------------------------------------------------------- ④ seed 面


def test_seed_has_three_dimensions_and_is_stable_per_message() -> None:
    first = timing.dispatch_seed(timing.TIMING_AFTER_REPLY, "group_42_7", "msg-1")
    assert first == timing.dispatch_seed(timing.TIMING_AFTER_REPLY, "group_42_7", "msg-1")
    for part in (timing.TIMING_AFTER_REPLY, "group_42_7", "msg-1"):
        assert part in first, f"seed 少了「{part}」这一维 ⇒ 重放摇摆或跨会话撞车"


def test_seeds_spread_across_messages_instead_of_collapsing_to_one() -> None:
    """不得总发同一张：同会话 40 条消息的 seed 必须各不相同（时机+消息维都在串里）。"""
    seeds = {
        timing.dispatch_seed(timing.TIMING_POKE, "group_42", f"msg-{index}")
        for index in range(40)
    }
    assert len(seeds) == 40


def test_command_seed_matches_the_capability_literal() -> None:
    """指令路 seed 的唯一字面真身仍在能力层（AST 锁那儿）；本件与它逐字节对齐。"""
    import inspect

    from plugins.bot_unified_runtime.domains.meme.capabilities import randpic

    assert timing.dispatch_seed(timing.TIMING_COMMAND, "group_42_7", "msg-9") == "randpic:group_42_7:msg-9"
    assert "_pick_for_command" in {
        name for name, _obj in inspect.getmembers(randpic, inspect.isfunction)
    }


def test_each_timing_uses_its_own_salt_so_legs_do_not_share_one_roll() -> None:
    plans = {
        name: timing.plan_randpic(_turn(name), _knobs(), seed="s").salt
        for name in (timing.TIMING_COMMAND, timing.TIMING_AFTER_REPLY, timing.TIMING_POKE)
    }
    assert len(set(plans.values())) == 3, plans


@pytest.mark.parametrize("name", [timing.TIMING_COMMAND, timing.TIMING_AFTER_REPLY, timing.TIMING_POKE])
def test_audit_tags_name_the_timing_and_the_outcome(name: str) -> None:
    plan = timing.plan_randpic(_turn(name), _knobs(), seed="s")
    assert any(name in tag for tag in plan.audit_tags)
    assert plan.capability_id == "bot.randpic"

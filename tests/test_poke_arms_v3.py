"""P14 波「戳一戳臂矩阵 + 跟戳 + 说完话顺手戳」离线回归。

三块都是**离线**判定：不发网络、不落源码树（写只写 ``tmp_path``）。
覆盖：臂选择确定性（旧三臂池逐字节不变 / 六臂池扩容不重洗旧值）、每道门
（概率 0 与 1、冷却、安静时间、blocked 名单——黑名单永远赢）、失败降级
（图库空/文件消失/语音不可用）、以及**开关关掉时新行为一条都不发生**。
根装配文件那半边用 AST 活性锁（先例：tests/test_progress_ack.py），
锁的是「装配段真把门与投递接上了」，不是文字承诺。
"""

from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    PokeDispatcher,
    PokeEvent,
    is_blocked_target,
    proactive_action_allowed,
    quiet_hours_active,
    resolve_poke_follow_target,
    resolve_poke_reply,
    resolve_poke_reply_mode,
)
from plugins.bot_unified_runtime.domains.meme.reactions.engine import ProactiveGate

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"


def _config(**overrides):
    """poke 相关配置缺省（与 config.py 的字段缺省一一对应，逐项可覆写）。"""
    base = {
        "bot_poke_enabled": True,
        "bot_poke_private_cooldown_seconds": 30.0,
        "bot_poke_group_cooldown_seconds": 10.0,
        "bot_poke_probability": 1.0,
        "bot_poke_reply_enabled": True,
        "bot_poke_poke_back": True,
        "bot_poke_group_text": "",
        "bot_poke_private_text": "",
        "bot_poke_reply_mode": "mix",
        "bot_poke_extra_arms_enabled": False,
        "bot_poke_affinity_enabled": False,
        "bot_quiet_hours_enabled": False,
        "bot_quiet_hours_start": "00:00",
        "bot_quiet_hours_end": "23:59",
        "bot_quiet_hours_timezone": "UTC",
        "bot_quiet_hours_session_types": ["group"],
        "bot_quiet_hours_bypass_roles": ["admin"],
        "bot_blocked_user_ids": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _clock(start: float = 1000.0):
    state = {"now": start}

    def clock() -> float:
        return state["now"]

    clock.advance = lambda delta: state.__setitem__("now", state["now"] + delta)  # type: ignore[attr-defined]
    return clock


def _dispatcher(clock=None) -> PokeDispatcher:
    return PokeDispatcher(clock=clock or _clock())


def _poke_event(*, group="42", user="7", target=None, bot="10000"):
    return PokeEvent(
        target_id=bot if target is None else target,
        user_id=user,
        group_id=group,
        sub_type="poke",
    )


# --------------------------------------------------------------- 臂选择确定性
def test_explicit_arms_all_six_pass_through() -> None:
    for arm in ("fixed", "llm", "meme", "voice", "randpic", "poke"):
        assert (
            resolve_poke_reply_mode(
                configured=arm, group="g", sender="u", bucket=1, extra_arms_enabled=False
            )
            == arm
        )


def test_legacy_mix_pool_unchanged_when_extra_arms_off() -> None:
    """关态=旧三臂：任意 (群,人,桶) 的判定值与 P14 之前逐字节同形。"""
    for bucket in range(60):
        got = resolve_poke_reply_mode(
            configured="mix", group="g", sender="u", bucket=bucket
        )
        # 旧实现的判据（手算复刻，不 import 旧常量）：三臂、同一 seed、同一取模。
        digest = hashlib.sha256(f"poke-mode:g:u:{bucket}".encode()).hexdigest()
        expected = ("fixed", "llm", "meme")[int(digest[:8], 16) % 3]
        assert got == expected, f"bucket={bucket} 关态被改判：{got} != {expected}"
        assert got in {"fixed", "llm", "meme"}


def test_extra_arms_off_never_emits_new_arms() -> None:
    for bucket in range(300):
        mode = resolve_poke_reply_mode(
            configured="mix",
            group="g",
            sender=f"u{bucket}",
            bucket=bucket,
            extra_arms_enabled=False,
        )
        assert mode not in {"voice", "randpic", "poke"}


def test_extra_arms_on_reaches_all_five_required_arms() -> None:
    """开态六臂池真能轮到我们全部要求的那五类表达（反证池没被写死成三臂）。"""
    seen = {
        resolve_poke_reply_mode(
            configured="mix",
            group="g",
            sender=f"u{bucket}",
            bucket=bucket,
            extra_arms_enabled=True,
        )
        for bucket in range(400)
    }
    assert seen == {"fixed", "llm", "meme", "voice", "randpic", "poke"}


def test_extra_arms_on_keeps_legacy_bucket_values() -> None:
    """扩臂只往后追加：旧三臂的下标位不变 ⇒ 开臂瞬间同桶旧值不重洗。"""
    for bucket in range(40):
        legacy = resolve_poke_reply_mode(
            configured="mix", group="g", sender="u", bucket=bucket
        )
        extended = resolve_poke_reply_mode(
            configured="mix",
            group="g",
            sender="u",
            bucket=bucket,
            extra_arms_enabled=True,
        )
        index = ("fixed", "llm", "meme", "voice", "randpic", "poke").index(extended)
        if index < 3:
            assert extended == legacy
        else:
            assert extended in {"voice", "randpic", "poke"}


def test_mix_selection_is_deterministic_across_instances() -> None:
    first = resolve_poke_reply_mode(
        configured="mix", group="g", sender="u", bucket=9, extra_arms_enabled=True
    )
    second = resolve_poke_reply_mode(
        configured="mix", group="g", sender="u", bucket=9, extra_arms_enabled=True
    )
    assert first == second


# ------------------------------------------------------------------ 组装与回退
def test_voice_arm_keeps_text_leg_when_audio_missing() -> None:
    text, image = resolve_poke_reply("voice", fixed_text="潮汐很安静")
    assert text == "潮汐很安静" and image is None


def test_randpic_arm_returns_only_image() -> None:
    text, image = resolve_poke_reply(
        "randpic", fixed_text="固定话术", randpic_path="x:/a.png"
    )
    assert (text, image) == ("", "x:/a.png")


def test_randpic_arm_empty_gallery_falls_back_to_fixed() -> None:
    text, image = resolve_poke_reply("randpic", fixed_text="固定话术", randpic_path=None)
    assert (text, image) == ("固定话术", None)


def test_poke_arm_emits_nothing_extra() -> None:
    text, image = resolve_poke_reply("poke", fixed_text="固定话术")
    assert (text, image) == ("", None)


def test_dispatcher_poke_arm_degrades_when_back_unavailable() -> None:
    """回戳不可用时「只回戳」臂退回固定话术——不许静默空回。"""
    dispatcher = _dispatcher()
    reaction = dispatcher.build_poke_reaction(
        _poke_event(),
        bot_id="10000",
        config=_config(bot_poke_reply_mode="poke"),
        poke_back_available=False,
    )
    assert reaction is not None
    assert reaction.mode == "fixed" and reaction.reply
    assert "poke_arm_fallback_no_poke_back" in reaction.audit_tags


def test_dispatcher_poke_arm_suppresses_text_when_back_available() -> None:
    reaction = _dispatcher().build_poke_reaction(
        _poke_event(),
        bot_id="10000",
        config=_config(bot_poke_reply_mode="poke"),
        poke_back_available=True,
    )
    assert reaction is not None
    assert reaction.mode == "poke" and reaction.poke_back and reaction.active


def test_dispatcher_extra_arms_reads_config_switch() -> None:
    """开关只在 extra_arms=True 时进六臂池（臂由 sender 扫出来，不靠运气）。"""

    def reaction_for(bucket_sender: str, *, extra: bool):
        dispatcher = PokeDispatcher(clock=_clock())
        return dispatcher.build_poke_reaction(
            _poke_event(user=bucket_sender),
            bot_id="10000",
            config=_config(bot_poke_extra_arms_enabled=extra),
        )

    off_modes = {(reaction_for(f"u{i}", extra=False)).mode for i in range(200)}
    on_modes = {(reaction_for(f"u{i}", extra=True)).mode for i in range(200)}
    assert off_modes <= {"fixed", "llm", "meme"}
    assert {"voice", "randpic", "poke"} <= on_modes


def test_cooled_down_poke_still_suppresses_every_arm() -> None:
    clock = _clock()
    dispatcher = _dispatcher(clock)
    config = _config(bot_poke_reply_mode="voice", bot_poke_poke_back=False)
    first = dispatcher.build_poke_reaction(
        _poke_event(group="", target="10000"), bot_id="10000", config=config
    )
    assert first is not None and first.mode == "voice"
    # 同戳者私聊冷却窗内第二发：任何臂都不出（冷却先于形态）。
    assert (
        dispatcher.build_poke_reaction(
            _poke_event(group="", target="10000"), bot_id="10000", config=config
        )
        is None
    )


# --------------------------------------------------------------------- 跟戳判定
def test_follow_target_requires_group_and_third_party() -> None:
    ok = resolve_poke_follow_target(_poke_event(target="9"), bot_id="10000")
    assert ok is not None and ok.target_id == "9" and ok.poker_id == "7"
    assert resolve_poke_follow_target(_poke_event(), bot_id="10000") is None
    assert (
        resolve_poke_follow_target(_poke_event(group="", target="9"), bot_id="10000")
        is None
    )
    assert resolve_poke_follow_target(_poke_event(target=""), bot_id="10000") is None


def test_follow_never_fires_for_poke_on_bot() -> None:
    """两路互斥：戳机器人自己那一发绝不会被跟戳腿重复处理。"""
    assert resolve_poke_follow_target(_poke_event(target="10000"), bot_id="10000") is None


# ------------------------------------------------------------------ 主动动作门
def test_action_off_by_default_blocks_everything() -> None:
    gate = ProactiveGate(clock=_clock())
    assert not proactive_action_allowed(
        _config(),
        prefix="bot_poke_follow_",
        gate=gate,
        session_key="group_42_9",
        message_key="poke-follow:7:42",
        group_id="42",
        user_id="9",
    )
    assert not proactive_action_allowed(
        _config(),
        prefix="bot_poke_after_reply_",
        gate=ProactiveGate(clock=_clock()),
        session_key="private_7",
        message_key="poke-spoke:reply:m1",
        user_id="7",
    )
    assert not proactive_action_allowed(
        _config(),
        prefix="bot_randpic_dispatch_",
        gate=ProactiveGate(clock=_clock()),
        session_key="private_7",
        message_key="randpic:m1",
        user_id="7",
    )


def test_probability_zero_and_one_boundaries() -> None:
    def allowed(probability: float, message_key: str) -> bool:
        return proactive_action_allowed(
            _config(
                bot_poke_after_reply_enabled=True,
                bot_poke_after_reply_probability=probability,
                bot_poke_after_reply_cooldown_seconds=0.0,
                bot_poke_after_reply_max_per_hour=50,
            ),
            prefix="bot_poke_after_reply_",
            gate=ProactiveGate(clock=_clock()),
            session_key="private_7",
            message_key=message_key,
            user_id="7",
        )

    assert not allowed(0.0, "m1")
    assert allowed(1.0, "m2") and allowed(1.0, "m3")


def test_cooldown_and_hourly_ceiling_hold_back_follow_ups() -> None:
    clock = _clock()
    gate = ProactiveGate(clock=clock)
    config = _config(
        bot_poke_follow_enabled=True,
        bot_poke_follow_probability=1.0,
        bot_poke_follow_cooldown_seconds=120.0,
        bot_poke_follow_max_per_hour=2,
    )

    def fire(message_key: str) -> bool:
        return proactive_action_allowed(
            config,
            prefix="bot_poke_follow_",
            gate=gate,
            session_key="group_42_9",
            message_key=message_key,
            group_id="42",
            user_id="9",
        )

    assert fire("a")
    assert not fire("b")  # 冷却窗内
    clock.advance(121.0)
    assert fire("c")
    clock.advance(121.0)
    assert not fire("d")  # 每小时上限=2 已用满


def test_blocked_roster_beats_probability_one() -> None:
    """黑名单永远赢：blocked 名单里的人，概率 1.0 也一票否决。"""
    config = _config(
        bot_poke_after_reply_enabled=True,
        bot_poke_after_reply_probability=1.0,
        bot_poke_after_reply_cooldown_seconds=0.0,
        bot_poke_after_reply_max_per_hour=99,
        bot_blocked_user_ids=["7"],
    )
    assert not proactive_action_allowed(
        config,
        prefix="bot_poke_after_reply_",
        gate=ProactiveGate(clock=_clock()),
        session_key="private_7",
        message_key="m1",
        user_id="7",
    )
    assert is_blocked_target(config, "7")
    assert not is_blocked_target(config, "8")


def test_quiet_hours_blocks_group_scope_and_honours_session_types() -> None:
    noon = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    on = {"bot_quiet_hours_enabled": True}
    assert quiet_hours_active(_config(**on), session_scope="group", now=noon)
    assert not quiet_hours_active(
        _config(**on, bot_quiet_hours_session_types=["private"]),
        session_scope="group",
        now=noon,
    )
    assert not quiet_hours_active(
        _config(bot_quiet_hours_enabled=False), session_scope="group", now=noon
    )
    # 窗的两端：03:00 在 00:00-06:00 内、12:00 不在（比较式方向没写反）。
    assert quiet_hours_active(
        _config(**on, bot_quiet_hours_start="00:00", bot_quiet_hours_end="06:00"),
        session_scope="group",
        now=datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
    )
    assert not quiet_hours_active(
        _config(**on, bot_quiet_hours_start="00:00", bot_quiet_hours_end="06:00"),
        session_scope="group",
        now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    # 跨日窗（22:00-06:00）两头都算安静。
    assert quiet_hours_active(
        _config(**on, bot_quiet_hours_start="22:00", bot_quiet_hours_end="06:00"),
        session_scope="group",
        now=datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc),
    )


def test_quiet_hours_blocks_action_even_at_probability_one() -> None:
    # start==end 在判据里=整天都在窗内（不依赖真实钟点，测试不 flaky）。
    config = _config(
        bot_poke_after_reply_enabled=True,
        bot_poke_after_reply_probability=1.0,
        bot_poke_after_reply_cooldown_seconds=0.0,
        bot_poke_after_reply_max_per_hour=99,
        bot_quiet_hours_enabled=True,
        bot_quiet_hours_start="03:00",
        bot_quiet_hours_end="03:00",
    )
    assert not proactive_action_allowed(
        config,
        prefix="bot_poke_after_reply_",
        gate=ProactiveGate(clock=_clock()),
        session_key="group_42_9",
        message_key="m1",
        group_id="42",
        user_id="9",
    )


def test_quiet_hours_gate_does_not_burn_cooldown_when_it_denies() -> None:
    """被安静窗拦下不许占冷却坑：否则拦一次反而让窗开后第一发也掷不出。"""
    clock = _clock()
    gate = ProactiveGate(clock=clock)
    blocked = _config(
        bot_poke_after_reply_enabled=True,
        bot_quiet_hours_enabled=True,
        bot_quiet_hours_start="03:00",
        bot_quiet_hours_end="03:00",
    )
    assert not proactive_action_allowed(
        blocked,
        prefix="bot_poke_after_reply_",
        gate=gate,
        session_key="group_42_9",
        message_key="m1",
        group_id="42",
        user_id="9",
    )
    open_config = _config(
        bot_poke_after_reply_enabled=True,
        bot_quiet_hours_enabled=False,
        bot_poke_after_reply_probability=1.0,
        bot_poke_after_reply_cooldown_seconds=0.0,
    )
    assert proactive_action_allowed(
        open_config,
        prefix="bot_poke_after_reply_",
        gate=gate,
        session_key="group_42_9",
        message_key="m2",
        group_id="42",
        user_id="9",
    )


def test_missing_target_never_fires() -> None:
    config = _config(
        bot_poke_after_reply_enabled=True,
        bot_poke_after_reply_probability=1.0,
        bot_quiet_hours_enabled=False,
    )
    gate = ProactiveGate(clock=_clock())
    assert not proactive_action_allowed(
        config,
        prefix="bot_poke_after_reply_",
        gate=gate,
        session_key="group_42_",
        message_key="m1",
        group_id="42",
        user_id="",
    )
    assert not gate.has_rolled("group_42_", "m1")  # 没目标连掷骰都不该发生


# ------------------------------------------------------- 根装配段活性锁（AST）
@pytest.mark.parametrize(
    ("handler", "required"),
    [
        ("_handle_poke_notice", ["_maybe_follow_poke", "poke_back_available"]),
        (
            "_handle_chat",
            ["_maybe_poke_after_bot_spoke", "_maybe_dispatch_randpic"],
        ),
        ("_handle_group_increase", ["_maybe_poke_after_bot_spoke"]),
    ],
)
def test_root_wiring_reaches_the_new_paths(handler: str, required: list) -> None:
    """装配段真接上了：门身调用、投递出口、跟戳腿都在 handler 体内出现。

    只读 AST 不 import 根件（根件 import 会拉起整个插件装配）。缺任一处即红
    ——注毒验证过：把 ``_maybe_dispatch_randpic(...)`` 那一段删掉本锁当场红。
    """
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == handler
    )
    body = ast.dump(node)
    for name in required:
        assert name in body, f"{handler} 里找不到 {name}＝接线没落进真身"


def test_voice_arm_goes_through_tts_capability_not_a_second_path() -> None:
    """语音臂只许复用 bot.tts 命令能力；本件里禁出现第二份合成调用。"""
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_poke_voice_pair"
    )
    names = {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    attrs = {
        call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    }
    assert "build_tts_capability" in names, "语音臂没走唯一能力入口"
    # 第二通路形态：直接打引擎 HTTP / 直接调 synthesize。
    assert "synthesize" not in names and "post" not in attrs

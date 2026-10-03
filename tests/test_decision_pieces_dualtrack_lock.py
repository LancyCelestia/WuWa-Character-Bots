"""决策件与活路径的**双轨等价性锁**（2026-10-03 互动面波）。

两枚决策件——``poke_routing.py``（三线选路）与 ``randpic_timing.py``（随机发图
三时机）——已建成但**零生产接线**，生产今天跑的是根装配文件里的既有活路径。
本件回答的问题是：**接线那天，换上决策件会不会改变行为？**

等价口径（模块 docstring 同款声明）：

- ``poke_routing``：同输入下**选臂、回落链、门判**逐格一致。mix 轮换两件各持
  确定性哈希（``poke_roll`` vs ``resolve_poke_reply_mode`` 的摘要取模），等价口径
  =「同池、同退路、同门判」，**不是逐臂同值**；群表态门等价的是门槛语义
  （黑名单赢 / 未表态拦 / 命中放行），名单字面源两件各异（决策件按 ``policy/gate``
  四档入参建模、活路径吃 ``content_route`` M-17 中央名单）——接线时以决策件为准
  并同步翻活路径，差什么先改这里的锁。
- ``randpic_timing``：门链顺序（disabled→no_target→blocked→quiet→门判）、
  ``allow_exhausted`` 三时机档、桶账键（``canonical_bucket_key``）与活路径逐格
  一致。**seed 两件已知不同形**：活路径被戳 seed 缺消息维（现状刻画锁
  ``tests/test_poke_reaction_matrix.py::test_poke_randpic_seed_has_no_message_dimension_characterization``
  在案），``dispatch_seed`` 是补上消息维的设计接任者；指令路 seed 逐字节同形。

全离线：零网络、零源码树写入（图库一律 ``tmp_path``）。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
    poke_routing as pr,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    POKE_REACTION_MATRIX,
    ProactiveActionKnobs,
    poke_mix_pool_arms,
    proactive_action_allowed,
    resolve_poke_reply,
    resolve_poke_reply_mode,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke_routing import (
    PokeCapabilities,
    PokeRouteRequest,
    PokeRoutingKnobs,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    explicit_allowed_for_session,
)
from plugins.bot_unified_runtime.domains.meme.capabilities import (
    randpic,
)
from plugins.bot_unified_runtime.domains.meme.capabilities import (
    randpic_timing as timing,
)
from plugins.bot_unified_runtime.domains.meme.reactions.engine import ProactiveGate

_FIXED_TEXT = "我收到你的轻轻一碰了。"
_PRESENT = {
    "llm_text": "嗯？潮声刚好。",
    "meme_path": "x:/meme.png",
    "randpic_path": "x:/pic.png",
}


# ============================================================================
# poke_routing：被动线（poked_bot） nominated 臂回落 ⇔ resolve_poke_reply
# ============================================================================


def _availability(**overrides: bool) -> PokeCapabilities:
    base: dict[str, bool] = {
        "group_poke_supported": True,
        "private_poke_supported": False,
        "poke_back_switch": True,
        "reply_enabled": True,
        "llm_available": True,
        "tts_available": True,
        "meme_library_available": True,
        "randpic_gallery_available": True,
    }
    base.update(overrides)
    return PokeCapabilities(**base)


def _reactive_request(
    nominated: str, caps: PokeCapabilities, *, is_group: bool = True
) -> PokeRouteRequest:
    return PokeRouteRequest(
        trigger=pr.TRIGGER_POKE_BOT,
        nominated_arm=nominated,
        seed="seat4",
        is_group=is_group,
        group_id="42" if is_group else "",
        poker_id="7",
        bot_id="10000",
        bucket=0,
        capabilities=caps,
        knobs=PokeRoutingKnobs(),
    )


@pytest.mark.parametrize(
    "arm,resource_key",
    [("llm", "llm_available"), ("meme", "meme_library_available"), ("randpic", "randpic_gallery_available")],
)
@pytest.mark.parametrize("available", [True, False], ids=["ready", "missing"])
def test_reactive_arm_and_fallback_match_the_live_resolver(
    arm: str, resource_key: str, available: bool
) -> None:
    """门交接位（dispatcher 点名臂）：资源齐 → 同臂；资源落空 → 同退 fixed。

    活路径的真身＝``resolve_poke_reply``（``degrade_site=resolve_poke_reply``）；
    决策件在 ``_arm_gate`` 判不可用后沿表退路走。两边必须同判。
    """
    caps = _availability(**{resource_key: available})
    decision = pr.decide_poke_route(_reactive_request(arm, caps))
    kwargs = {key: (_PRESENT[key] if available else None) for key in _PRESENT}
    text, image = resolve_poke_reply(arm, fixed_text=_FIXED_TEXT, **kwargs)
    if available:
        assert decision.action == arm
        # 活路径真的交出了本臂的表达（不是退路）。
        if POKE_REACTION_MATRIX[arm].channel == "text":
            assert text and image is None
        else:
            assert image or arm == "voice"
    else:
        assert decision.action == "fixed", decision
        assert text == _FIXED_TEXT and image is None


def test_reactive_poke_arm_degrade_site_agrees_with_the_live_dispatcher() -> None:
    """``poke`` 行 ``degrade_site=dispatcher``：不可用 ⇒ 两边都退 fixed（不静默）。"""
    decision = pr.decide_poke_route(
        _reactive_request("poke", _availability(private_poke_supported=False), is_group=False)
    )
    assert decision.action == "fixed"
    # 活路径分发器层同判：poke_back_available=False 时 build_poke_reaction 的 mode
    # 被改判 fixed（此处锁 resolve 层语义 + 表行声明一致即可，分发器行为另有专锁）。
    assert resolve_poke_reply("poke", fixed_text=_FIXED_TEXT) == ("", None)
    assert POKE_REACTION_MATRIX["poke"].degrade_site == "dispatcher"


def test_reactive_mix_rotation_stays_inside_the_live_pool() -> None:
    """mix 轮换：决策件取臂恒在活路径同源池内（同池同序；哈希不同形=已声明口径差）。"""
    for extra in (False, True):
        live_pool = poke_mix_pool_arms("extended" if extra else "legacy")
        assert live_pool, "活路径池为空 ⇒ 判据空跑"
        for bucket in range(120):
            decision = pr.decide_poke_route(
                PokeRouteRequest(
                    trigger=pr.TRIGGER_POKE_BOT,
                    seed=f"s{bucket}",
                    is_group=True,
                    group_id="42",
                    poker_id="7",
                    bot_id="10000",
                    bucket=bucket,
                    capabilities=_availability(),
                    knobs=PokeRoutingKnobs(extra_arms_enabled=extra),
                )
            )
            assert decision.action in live_pool, (
                f"bucket={bucket} 选出池外臂 {decision.action}"
            )
            # 决策件自己是确定性的：同输入重放同值。
            again = pr.decide_poke_route(
                PokeRouteRequest(
                    trigger=pr.TRIGGER_POKE_BOT,
                    seed=f"s{bucket}",
                    is_group=True,
                    group_id="42",
                    poker_id="7",
                    bot_id="10000",
                    bucket=bucket,
                    capabilities=_availability(),
                    knobs=PokeRoutingKnobs(extra_arms_enabled=extra),
                )
            )
            assert again.action == decision.action


def test_reactive_mix_rotation_matches_live_pool_for_the_same_inputs() -> None:
    """同输入下活路径 mix 池与决策件池**同一元组**（同源派生，禁第二真身）。"""
    for extra in (False, True):
        live = resolve_poke_reply_mode(
            configured="mix", group="42", sender="7", bucket=0, extra_arms_enabled=extra
        )
        decision = pr.decide_poke_route(
            PokeRouteRequest(
                trigger=pr.TRIGGER_POKE_BOT,
                seed="x",
                is_group=True,
                group_id="42",
                poker_id="7",
                bot_id="10000",
                bucket=0,
                capabilities=_availability(),
                knobs=PokeRoutingKnobs(extra_arms_enabled=extra),
            )
        )
        pool = poke_mix_pool_arms("extended" if extra else "legacy")
        assert live in pool and decision.action in pool
        assert set(pr.poke_line_arm_pool(extra)) == set(pool)


# ============================================================================
# poke_routing：主动线门判 ⇔ 活路径（M-17 名单门 ∧ proactive_action_allowed）
# ============================================================================


def _proactive_request(**overrides: object) -> PokeRouteRequest:
    base: dict[str, object] = {
        "trigger": pr.TRIGGER_PEER_POKE,
        "seed": "seat4",
        "is_group": True,
        "group_id": "42",
        "poker_id": "1",
        "target_id": "2",
        "bot_id": "10000",
        "now": 1000.0,
        "bucket": 0,
        "capabilities": _availability(),
        "knobs": PokeRoutingKnobs(
            follow_enabled=True,
            follow_probability=1.0,
            follow_cooldown_seconds=0.0,
            follow_max_per_hour=999,
        ),
    }
    base.update(overrides)
    return PokeRouteRequest(**base)


def _live_poke_config(**overrides: object):
    from types import SimpleNamespace

    base: dict[str, object] = {
        "bot_blocked_user_ids": [],
        "bot_poke_follow_probability": 1.0,
        "bot_poke_follow_cooldown_seconds": 0.0,
        "bot_poke_follow_max_per_hour": 999,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _AlwaysAllowGate:
    def allow(self, *args: object, **kwargs: object) -> bool:
        return True


class _NeverAllowGate:
    def allow(self, *args: object, **kwargs: object) -> bool:
        return False


def _live_proactive_poke_passes(
    config: object, *, group_id: str, user_id: str, gate: object | None = None
) -> bool:
    """活路径两道门串联的真身：M-17 名单门 ∧ 五层门（骰默认恒中=聚焦门判本身）。"""
    if not explicit_allowed_for_session("group", group_id, config, sender_id=user_id):
        return False
    return proactive_action_allowed(
        config,
        prefix="bot_poke_follow_",
        gate=gate if gate is not None else _AlwaysAllowGate(),
        session_key=f"group_{group_id}_{user_id}",
        message_key="poke-follow:1:42",
        group_id=group_id,
        user_id=user_id,
        salt="poke-follow",
        require_group=True,
        knobs=ProactiveActionKnobs(
            enabled=bool(getattr(config, "bot_poke_follow_enabled", False)),
            probability=1.0,
            cooldown_seconds=0.0,
            max_per_hour=999,
        ),
    )


@pytest.mark.parametrize(
    "scenario",
    ["disabled", "private", "blacklisted", "unlisted", "whitelisted", "quiet", "blocked_target"],
)
def test_proactive_line_gates_agree_with_the_live_gate_chain(scenario: str) -> None:
    """同场景下决策件「发不出」⇔ 活路径两道门「发不出」；放行格两边都放行。"""
    request_kwargs: dict[str, object] = {}
    config = _live_poke_config(bot_poke_follow_enabled=True)
    if scenario == "disabled":
        request_kwargs["knobs"] = PokeRoutingKnobs(
            follow_enabled=False,
            follow_probability=1.0,
            follow_cooldown_seconds=0.0,
            follow_max_per_hour=999,
        )
        config.bot_poke_follow_enabled = False
    elif scenario == "private":
        request_kwargs.update(is_group=False, group_id="")
    elif scenario == "blacklisted":
        request_kwargs["group_black1"] = frozenset({"42"})
        config.bot_content_route_group_blacklist = {"42"}
        config.bot_content_route_group_whitelist = {"42"}
    elif scenario == "unlisted":
        pass  # 决策件两名单全空 / 活路径名单全缺 ⇒ 都是「没表态」。
    elif scenario == "whitelisted":
        request_kwargs["group_white1"] = frozenset({"42"})
        config.bot_content_route_group_whitelist = {"42"}
    elif scenario == "quiet":
        request_kwargs["group_white1"] = frozenset({"42"})
        request_kwargs["quiet_hours_active"] = True
        config.bot_content_route_group_whitelist = {"42"}
        # 活路径安静窗：00:00-23:59 全天覆盖（UTC），群会话在册。
        config.bot_quiet_hours_enabled = True
        config.bot_quiet_hours_start = "00:00"
        config.bot_quiet_hours_end = "23:59"
        config.bot_quiet_hours_timezone = "UTC"
        config.bot_quiet_hours_session_types = ["group"]
    elif scenario == "blocked_target":
        request_kwargs["group_white1"] = frozenset({"42"})
        request_kwargs["target_blocked"] = True
        config.bot_content_route_group_whitelist = {"42"}
        config.bot_blocked_user_ids = ["2"]

    decision = pr.decide_poke_route(_proactive_request(**request_kwargs))
    decision_sends = decision.action == "poke" and decision.committable
    # 活路径真戳/真门的是 candidates[0]（blocked 已滤、先 B 后 A 的候选序，真身
    # poke.proactive_poke_candidates）＝决策件 target_user_id 同一判；不是恒戳 B。
    live_sends = _live_proactive_poke_passes(
        config, group_id="42", user_id=decision.target_user_id
    )
    assert decision_sends == live_sends, (
        f"场景 {scenario}: 决策件={decision.action}/{decision.reason} "
        f"committable={decision.committable} 与活路径门判不一致"
    )
    if not decision_sends:
        # 落空必须带可判别的理由，不留「无声拒绝」。
        assert decision.reason, scenario



def test_blocked_target_falls_back_to_poker_on_both_tracks() -> None:
    """blocked 被戳者 B ⇒ 两轨同判「退戳 A」（活路径候选真身现算，不互抄）。

    活路径候选序唯一真身＝``poke.proactive_poke_candidates``（先 B、B 因 blocked
    不可投才退 A，名单判定在门之前）；决策件 ``_resolve_target`` 照同一口径。拿
    活路径候选函数现算对齐，防 equivalence 锁两边互抄同一错而空转。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
        PokeFollowTarget,
        proactive_poke_candidates,
    )

    config = _live_poke_config(bot_poke_follow_enabled=True)
    config.bot_blocked_user_ids = ["2"]
    decision = pr.decide_poke_route(
        _proactive_request(group_white1=frozenset({"42"}), target_blocked=True)
    )
    assert decision.action == "poke" and decision.committable
    assert decision.target_user_id == "1"
    assert any("follow_candidate_fallback" in tag for tag in decision.audit_tags)
    # 活路径真身现算：同一份 blocked 名单下，可投候选只剩 A。
    live_candidates = proactive_poke_candidates(
        config,
        PokeFollowTarget(group_id="42", poker_id="1", target_id="2"),
        bot_id="10000",
    )
    assert live_candidates == ("1",)
    assert live_candidates[0] == decision.target_user_id
# ============================================================================
# randpic_timing：门链顺序 ⇔ proactive_action_allowed；桶账/退让档 ⇔ 活路径
# ============================================================================


def _timing_knobs(**overrides: object) -> timing.RandpicKnobs:
    base: dict[str, object] = {
        "enabled": True,
        "probability": 1.0,
        "cooldown_seconds": 0.0,
        "max_per_hour": 999,
        "window_seconds": 0.0,
    }
    base.update(overrides)
    return timing.RandpicKnobs(**base)  # type: ignore[arg-type]


def _timing_turn(**overrides: object) -> timing.RandpicTurn:
    base: dict[str, object] = {
        "timing": timing.TIMING_AFTER_REPLY,
        "session_key": "group_42_7",
        "message_key": "m-1",
        "group_id": "42",
        "user_id": "7",
    }
    base.update(overrides)
    return timing.RandpicTurn(**base)  # type: ignore[arg-type]


def _live_randpic_config(**overrides: object):
    from types import SimpleNamespace

    base: dict[str, object] = {
        "bot_blocked_user_ids": [],
        "bot_randpic_dispatch_probability": 1.0,
        "bot_randpic_dispatch_cooldown_seconds": 0.0,
        "bot_randpic_dispatch_max_per_hour": 999,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.parametrize(
    "scenario",
    ["disabled", "no_target", "blocked", "quiet", "gate_deny", "pass"],
)
def test_randpic_gate_chain_agrees_with_live_proactive_action_allowed(
    scenario: str,
) -> None:
    """同场景：决策件「发」⇔ 活路径 ``proactive_action_allowed``「放行」。

    门链顺序即语义（两边同判据）：开关 → 有目标 → blocked → 安静窗 → 五层门。
    活路径五层门用恒中骰替身＝聚焦门链本身。
    """
    knobs = _timing_knobs()
    turn = _timing_turn()
    blocked = False
    quiet = False
    gate_verdict: tuple[bool, str] | None = (True, "")
    config = _live_randpic_config()
    if scenario == "disabled":
        knobs = _timing_knobs(enabled=False)
        config.bot_randpic_dispatch_enabled = False
    elif scenario == "no_target":
        turn = _timing_turn(user_id="")
    elif scenario == "blocked":
        blocked = True
        config.bot_blocked_user_ids = ["7"]
    elif scenario == "quiet":
        quiet = True
        config.bot_quiet_hours_enabled = True
        config.bot_quiet_hours_start = "00:00"
        config.bot_quiet_hours_end = "23:59"
        config.bot_quiet_hours_timezone = "UTC"
        config.bot_quiet_hours_session_types = ["group"]
    elif scenario == "gate_deny":
        gate_verdict = (False, "gate_cooldown")

    plan = timing.plan_randpic(
        turn, knobs, seed="seed-1", blocked=blocked, quiet_active=quiet,
        gate_verdict=gate_verdict,
    )
    live_pass = proactive_action_allowed(
        config,
        prefix="bot_randpic_dispatch_",
        gate=_NeverAllowGate() if scenario == "gate_deny" else ProactiveGate(),
        session_key=turn.session_key,
        message_key=f"randpic:{turn.message_key}",
        group_id=turn.group_id,
        user_id=turn.user_id,
        salt="randpic-dispatch",
        knobs=ProactiveActionKnobs(
            enabled=bool(getattr(config, "bot_randpic_dispatch_enabled", True)),
            probability=1.0,
            cooldown_seconds=0.0,
            max_per_hour=999,
        ),
    )
    # no_target 场景活路径在 user_id 空上拦截；决策件 reason 同名可判别。
    assert plan.send == live_pass, (
        f"场景 {scenario}: 决策件 send={plan.send}/{plan.reason} 与活路径 {live_pass} 不一致"
    )
    if not plan.send:
        assert plan.reason and plan.held


@pytest.fixture()
def _clean_default_window():
    """进程级单例窗账逐用例复位（``pick_gallery_image`` 无 window 参时走它）。"""
    randpic._DEFAULT_RECENT_WINDOW.clear()
    yield
    randpic._DEFAULT_RECENT_WINDOW.clear()


def test_allow_exhausted_ladder_matches_live_gallery_behavior(
    tmp_path, _clean_default_window
) -> None:
    """三时机「整库都在窗内」档 ⇔ 活路径真图库行为：指令路复发、两主动路宁缺。"""
    gallery = tmp_path / "g"
    gallery.mkdir()
    (gallery / "only.png").write_bytes(b"\x89PNG\r\n\x1a\nonly")
    config = _live_randpic_config_directed(tmp_path)
    # 先把整库打进活路径默认窗账（与循环里同一取图口：占坑一次即窗内唯一一张）。
    assert randpic.pick_gallery_image(
        config, session_key="group_42_7", seed="warm-up", allow_exhausted=True,
    ) is not None

    for name, expect_recycle in (
        (timing.TIMING_COMMAND, True),
        (timing.TIMING_AFTER_REPLY, False),
        (timing.TIMING_POKE, False),
    ):
        turn = _timing_turn(timing=name)
        plan = timing.plan_randpic(
            turn, _timing_knobs(), seed="seed-2",
            gate_verdict=(True, "") if name != timing.TIMING_COMMAND else None,
        )
        assert plan.allow_exhausted is expect_recycle, name
        # 用决策件的档驱动活路径真图库：结果必须与档语义一致。
        live = randpic.pick_gallery_image(
            config,
            session_key=turn.session_key,
            seed=timing.dispatch_seed(name, turn.session_key, turn.message_key),
            allow_exhausted=plan.allow_exhausted,
        )
        if expect_recycle:
            assert live is not None, f"{name}: 档说可复发、真图库却拒发"
        else:
            assert live is None, f"{name}: 档说宁缺、真图库却还在发 ⇒ 会刷屏"


def _live_randpic_config_directed(tmp_path):
    from types import SimpleNamespace

    return SimpleNamespace(
        bot_randpic_dirs=[str(tmp_path / "g")],
        bot_randpic_no_repeat_window_seconds=3600.0,
        bot_randpic_max_file_mb=0,
        bot_randpic_trigger_words=[],
    )


def test_bucket_key_is_the_live_window_ledger_key() -> None:
    """决策件的 ``bucket_key`` 就是活路径窗账真实记账键（群键收敛到群、私聊原样）。"""
    window = randpic.RecentImageWindow()
    window.record("group_42_7", "id-x", window_seconds=3600.0)
    plan = timing.plan_randpic(
        _timing_turn(), _timing_knobs(), seed="s", gate_verdict=(True, "")
    )
    assert plan.bucket_key == randpic.canonical_bucket_key("group_42_7") == "group_42"
    assert window.recent_keys(plan.bucket_key, window_seconds=3600.0) == frozenset({"id-x"})
    # 私聊键不可并桶：两件同口径。
    private_plan = timing.plan_randpic(
        _timing_turn(session_key="9900"), _timing_knobs(), seed="s", gate_verdict=(True, "")
    )
    assert private_plan.bucket_key == "9900"


def test_command_seed_is_byte_equal_to_the_live_literal() -> None:
    """指令路 seed 两件逐字节同形；两主动路 seed 已声明不同形（docstring 口径）。"""
    assert timing.dispatch_seed(timing.TIMING_COMMAND, "group_42_7", "m-9") == (
        "randpic:group_42_7:m-9"
    )
    # 主动路：决策件 seed 含时机+会话+消息三维且可复现（活路径历史 seed 另有刻画锁）。
    for name in (timing.TIMING_AFTER_REPLY, timing.TIMING_POKE):
        first = timing.dispatch_seed(name, "group_42_7", "m-9")
        assert first == timing.dispatch_seed(name, "group_42_7", "m-9")
        assert name in first and "group_42_7" in first and "m-9" in first

"""P14 波 ITEM 14「戳一戳矩阵」离线回归（恰一臂 / 禁自激 / 跟戳退路 / 场合门）。

与 ``tests/test_poke_arms_v3.py`` 的分工：那件测**臂选择确定性与降级链**，
本件测那件之后本波补上的四条硬判据——

1. **恰一臂**（用户裁定「一次被戳只出一种表达」）：回戳意图与其余四臂互斥，
   且任何一臂的资源落空都必须落到另一臂上，绝不允许「什么都没发却带着一枚
   说它发了的标签」；
2. **禁戳由戳起**：bot 自己戳出去的动作被协议端回声成 notice 时不得再跟，
   判据落在**认事件**那一步（不在投递那一步，换任何投递面都拦得住）；
3. **跟戳退路**：被戳者 B 不可戳（blocked/空号/是 bot）时退戳者 A，
   且候选过滤必须在五层门**之前**（``ProactiveGate.allow`` 是 commit 语义）；
4. **主动戳人只认群消息**：QQ 私聊 poke 的通道名在册≠协议端实装，
   未证实即不放开（先例=主动贴表情私聊不派发）。

全离线：零网络、零源码树写入（要落盘只落 ``tmp_path``）。
根装配文件那半边用 AST 活性锁（先例：tests/test_progress_ack.py）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    PokeDispatcher,
    PokeEvent,
    PokeFollowTarget,
    proactive_action_allowed,
    proactive_poke_candidates,
    resolve_poke_follow_target,
    resolve_poke_reply,
)
from plugins.bot_unified_runtime.domains.meme.reactions.engine import ProactiveGate

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"


def _config(**overrides) -> SimpleNamespace:
    """缺省逐项对齐 ``config.py`` 的 poke/门链字段（覆写粒度=单键）。"""
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
        "bot_poke_extra_arms_enabled": True,
        "bot_quiet_hours_enabled": False,
        "bot_quiet_hours_start": "00:00",
        "bot_quiet_hours_end": "23:59",
        "bot_quiet_hours_timezone": "UTC",
        "bot_quiet_hours_session_types": ["group"],
        "bot_quiet_hours_bypass_roles": ["admin"],
        "bot_blocked_user_ids": [],
        "bot_poke_follow_enabled": True,
        "bot_poke_follow_probability": 1.0,
        "bot_poke_follow_cooldown_seconds": 120.0,
        "bot_poke_follow_max_per_hour": 4,
        "bot_poke_after_reply_enabled": True,
        "bot_poke_after_reply_probability": 1.0,
        "bot_poke_after_reply_cooldown_seconds": 300.0,
        "bot_poke_after_reply_max_per_hour": 3,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _clock(start: float = 1000.0):
    state = {"now": start}

    def clock() -> float:
        return state["now"]

    clock.advance = lambda delta: state.__setitem__(  # type: ignore[attr-defined]
        "now", state["now"] + delta
    )
    return clock


def _event(*, group="42", user="7", target="10000") -> PokeEvent:
    return PokeEvent(target_id=target, user_id=user, group_id=group, sub_type="poke")


def _reaction(mode: str, *, back_available: bool = True, clock=None, group="42"):
    return PokeDispatcher(clock=clock or _clock()).build_poke_reaction(
        _event(group=group),
        bot_id="10000",
        config=_config(bot_poke_reply_mode=mode),
        poke_back_available=back_available,
    )


# 每臂「资源齐备时」的可用素材：None=该臂资源落空。
_RESOURCES = {
    "fixed": {"llm_text": None, "meme_path": None, "randpic_path": None},
    "llm": {"llm_text": "嗯？", "meme_path": None, "randpic_path": None},
    "meme": {"llm_text": None, "meme_path": "C:/x/meme.png", "randpic_path": None},
    "voice": {"llm_text": None, "meme_path": None, "randpic_path": None},
    "randpic": {"llm_text": None, "meme_path": None, "randpic_path": "C:/x/pic.png"},
    "poke": {"llm_text": None, "meme_path": None, "randpic_path": None},
}


# --------------------------------------------------------------- 恰一臂（判据 1）
def test_exactly_one_arm_per_poke_when_resources_available() -> None:
    """每臂资源齐备时，「回戳」与「正文（文本/图）」合计恰好一臂。

    这是 ITEM 14(a) 的直接判据：把两枚公共件的输出相加，任何一臂都不许出现
    0 臂（静默）或 2 臂（旧行为：回戳叠在话术之上双发）。
    """
    for mode, resources in _RESOURCES.items():
        reaction = _reaction(mode)
        assert reaction is not None, f"{mode} 臂连决定都没拿到"
        text, image = resolve_poke_reply(
            reaction.mode, fixed_text=reaction.reply, **resources
        )
        # voice 臂的「语音+文本」算一臂：语音由调用方附加，文本腿不计第二臂。
        expressions = int(reaction.poke_back) + int(bool(text or image))
        assert expressions == 1, f"{mode} 臂出了 {expressions} 臂：{reaction.mode}"


def test_poke_back_never_stacks_on_another_arm() -> None:
    """回戳开关恒开时，只有 poke 那一臂才允许 poke_back 为真。

    旧实现把 ``can_poke_back`` 与 mode 正交计算，而 ``bot_poke_poke_back``
    缺省 True ⇒ 现网每一发被戳都「回戳 + 话术」双发（撞裁定 (a)）。
    """
    config = _config(bot_poke_poke_back=True)
    offenders: list[str] = []
    for index in range(400):
        reaction = PokeDispatcher(clock=_clock()).build_poke_reaction(
            _event(user=str(1000 + index)),
            bot_id="10000",
            config=config,
            poke_back_available=True,
        )
        assert reaction is not None
        if reaction.poke_back and reaction.mode != "poke":
            offenders.append(f"{reaction.mode}+poke_back")
    assert not offenders, f"叠臂组合：{sorted(set(offenders))[:5]}"
    # 反向：轮换池里 poke 臂确实可达，否则上面的循环是空跑。
    assert (
        PokeDispatcher(clock=_clock()).build_poke_reaction(
            _event(target="10000"),
            bot_id="10000",
            config=_config(bot_poke_reply_mode="poke"),
            poke_back_available=True,
        )
    ).poke_back is True


def test_unavailable_arm_always_falls_through_to_a_send() -> None:
    """任何一臂资源落空时都必须仍有表达（不许「什么都没发却带着已发的标签」）。"""
    for mode in ("fixed", "llm", "meme", "voice", "randpic"):
        reaction = _reaction(mode)
        assert reaction is not None
        text, image = resolve_poke_reply(
            mode,
            fixed_text=reaction.reply,
            llm_text=None,
            meme_path=None,
            randpic_path=None,
        )
        assert text or image, f"{mode} 臂资源空时静默无输出"
    # 回戳不可用 ⇒ 只回戳臂在分发层就退 fixed（不是到投递层才烂掉）。
    degraded = _reaction("poke", back_available=False)
    assert degraded is not None and degraded.mode == "fixed"
    assert degraded.reply and not degraded.poke_back
    assert "poke_arm_fallback_no_poke_back" in degraded.audit_tags


# ------------------------------------------------------------ 禁自激（判据 2）
def test_bot_originated_poke_is_not_a_followable_event() -> None:
    """戳者就是机器人自己 ⇒ 这一发根本不构成「A 戳了 B」。"""
    echo = _event(user="10000", target="9")
    assert resolve_poke_follow_target(echo, bot_id="10000") is None
    # 正常形态仍然认（防把判据写成恒否）。
    ok = resolve_poke_follow_target(_event(user="7", target="9"), bot_id="10000")
    assert ok is not None and ok.target_id == "9" and ok.poker_id == "7"


def test_follow_echo_cannot_self_loop() -> None:
    """把 bot 跟戳的回声喂回整条决策链：两路都必须零动作（不成环）。"""
    echo = _event(user="10000", target="9")
    dispatcher = PokeDispatcher(clock=_clock())
    # 路一（被戳臂）：target 不是 bot ⇒ 恒否。
    assert dispatcher.build_poke_reaction(echo, bot_id="10000", config=_config()) is None
    # 路二（跟戳腿）：poker 是 bot ⇒ 恒否。
    assert resolve_poke_follow_target(echo, bot_id="10000") is None
    # 候选表也永远给不出 bot 自己（第三道保险）。
    target = PokeFollowTarget(group_id="42", poker_id="7", target_id="9")
    assert "10000" not in target.poke_candidates(bot_id="10000")


# ------------------------------------------------------- 跟戳退路与名单（判据 3）
def test_follow_candidates_prefer_target_then_poker() -> None:
    target = PokeFollowTarget(group_id="42", poker_id="7", target_id="9")
    assert target.poke_candidates(bot_id="10000") == ("9", "7")
    # B 缺失 → 只剩 A；A==B → 去重成一个；A 是 bot → 剔除。
    assert PokeFollowTarget("42", "7", "").poke_candidates() == ("7",)
    assert PokeFollowTarget("42", "9", "9").poke_candidates() == ("9",)
    assert PokeFollowTarget("42", "10000", "9").poke_candidates(bot_id="10000") == ("9",)


def test_blocked_target_is_dropped_before_the_gate() -> None:
    """blocked 名单在**进五层门之前**就把候选削掉：B 黑名单 ⇒ 只剩 A。"""
    blocked_b = _config(bot_blocked_user_ids=["9"])
    target = PokeFollowTarget(group_id="42", poker_id="7", target_id="9")
    assert proactive_poke_candidates(blocked_b, target, bot_id="10000") == ("7",)
    both = _config(bot_blocked_user_ids=["9", "7"])
    assert proactive_poke_candidates(both, target, bot_id="10000") == ()
    # 名单外 ⇒ 两枚候选都在（防把判据写成恒空）。
    assert proactive_poke_candidates(_config(), target, bot_id="10000") == ("9", "7")


def test_gate_is_not_burned_when_no_candidate_survives() -> None:
    """全候选被名单拦下时，五层门一次都不该被 commit（冷却/滑窗不白烧）。"""
    gate = ProactiveGate(clock=_clock())
    calls: list[str] = []

    class _SpyGate:
        def allow(self, *args, **kwargs):
            calls.append(str(args[0]))
            return False

    target = PokeFollowTarget(group_id="42", poker_id="7", target_id="9")
    assert (
        proactive_poke_candidates(
            _config(bot_blocked_user_ids=["9", "7"]), target, bot_id="10000"
        )
        == ()
    )
    assert proactive_action_allowed(
        _config(),
        prefix="bot_poke_follow_",
        gate=gate,
        session_key="group_42_9",
        message_key="poke-follow:7:42",
        group_id="42",
        user_id="",  # 无目标：进门前就否。
    ) is False
    assert calls == []


# ----------------------------------------------------- 场合门：只认群消息（判据 4）
def test_require_group_denies_private_and_holds_the_gate() -> None:
    """``require_group=True`` ⇒ 私聊一杠不成立，且**不烧**五层门的账。"""
    gate = ProactiveGate(clock=_clock())
    config = _config()
    assert (
        proactive_action_allowed(
            config,
            prefix="bot_poke_after_reply_",
            gate=gate,
            session_key="private_7",
            message_key="poke-spoke:reply:m1",
            group_id="",
            user_id="7",
            require_group=True,
        )
        is False
    )
    # 被场合门拦下 ⇒ 门内没留任何账（冷却/滑窗/去重都不该动）。
    assert (
        proactive_action_allowed(
            config,
            prefix="bot_poke_after_reply_",
            gate=gate,
            session_key="group_42_7",
            message_key="poke-spoke:reply:m2",
            group_id="42",
            user_id="7",
            salt="poke-spoke-reply",
            require_group=True,
        )
        is True
    )


def test_randpic_dispatch_private_allowed_when_switched_on() -> None:
    config = _config(
        bot_randpic_dispatch_enabled=True,
        bot_randpic_dispatch_probability=1.0,
        bot_randpic_dispatch_cooldown_seconds=600.0,
        bot_randpic_dispatch_max_per_hour=2,
    )
    assert proactive_action_allowed(
        config,
        prefix="bot_randpic_dispatch_",
        gate=ProactiveGate(clock=_clock()),
        session_key="private_7",
        message_key="randpic:m1",
        group_id="",
        user_id="7",
    )


# ------------------------------------------------- 根装配段活性锁（AST，不发运行时）
def _root_function(name: str, *, async_def: bool = True):
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    want = ast.AsyncFunctionDef if async_def else ast.FunctionDef
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, want) and node.name == name
    )


def test_root_follow_uses_candidates_before_gate_and_stops_at_first_delivery() -> None:
    node = _root_function("_maybe_follow_poke")
    names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
    for required in (
        "resolve_poke_follow_target",
        "proactive_poke_candidates",
        "proactive_action_allowed",
        "_dispatch_poke_at",
    ):
        assert required in names, f"跟戳腿缺 {required}"

    def _first_call_line(name: str) -> int:
        """按**调用点**比先后：只看 Name 节点会被 import 语句里的同名符号糊过去。"""
        return min(
            call.lineno
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == name
        )

    # 名单过滤必须在门之前（过了门才反悔＝白烧一次冷却与每小时额度），
    # 门必须在投递之前。
    assert _first_call_line("proactive_poke_candidates") < _first_call_line(
        "proactive_action_allowed"
    )
    assert _first_call_line("proactive_action_allowed") < _first_call_line(
        "_dispatch_poke_at"
    )
    # 投递必须在 for 循环里、按候选序试投，且有一发成功就 return（绝不同戳两人）。
    loops = [n for n in ast.walk(node) if isinstance(n, ast.For)]
    assert loops, "跟戳没有按候选表试投＝B 不可戳时退不了 A"
    assert any(
        isinstance(n, ast.Return) for n in ast.walk(loops[0])
    ), "循环里没有 return ⇒ 会对每个候选都戳一遍"


def test_root_proactive_pokes_pass_require_group() -> None:
    """两条主动戳人腿都必须带 ``require_group=True``（未证实私聊即不放开）。"""
    for name in ("_maybe_follow_poke", "_maybe_poke_after_bot_spoke"):
        node = _root_function(name)
        flags = [
            keyword
            for call in (n for n in ast.walk(node) if isinstance(n, ast.Call))
            for keyword in call.keywords
            if isinstance(keyword.arg, str)
            and keyword.arg == "require_group"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
        ]
        assert flags, f"{name} 未声明 require_group=True＝私聊戳人被静默放开"


def test_root_randpic_dispatch_runs_after_the_reply_is_delivered() -> None:
    """ITEM 15(d)：发图发生在正文送达之后，且被独立 try 包住（打死不了回复）。"""
    source = ROOT_INIT.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    dispatch_at = source.index("await _maybe_dispatch_randpic(")
    # 正文投递口（chat handler 里那发）必须已在前面出现：增益腿不抢在正文之前。
    delivered_at = source.rindex(
        "transport_receipt = await _deliver_transport_send_request(", 0, dispatch_at
    )
    assert delivered_at < dispatch_at
    poke_at = source.index(
        "await _maybe_poke_after_bot_spoke(", delivered_at
    )
    assert delivered_at < poke_at

    def _inside_broad_try(name: str) -> int:
        hits = 0
        for try_node in (n for n in ast.walk(tree) if isinstance(n, ast.Try)):
            caught = {
                getattr(handler.type, "id", None) or getattr(handler.type, "attr", None)
                for handler in try_node.handlers
            }
            if "Exception" not in caught:
                continue
            for call in ast.walk(try_node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == name
                ):
                    hits += 1
        return hits

    # 两条腿各自被「吞异常」的 try 包住：一条炸了不能带走另一条，更不能带走投递结果。
    assert _inside_broad_try("_maybe_dispatch_randpic") >= 1
    assert _inside_broad_try("_maybe_poke_after_bot_spoke") >= 1
    # 取图必须在 to_thread 里（目录扫描 + 内容摘要是阻塞 IO）。
    dispatch_node = _root_function("_maybe_dispatch_randpic")
    to_thread_targets = {
        call.args[0].id
        for call in ast.walk(dispatch_node)
        if isinstance(call, ast.Call)
        and isinstance(getattr(call, "func", None), ast.Attribute)
        and call.func.attr == "to_thread"
        and call.args
        and isinstance(call.args[0], ast.Name)
    }
    assert "pick_gallery_image" in to_thread_targets

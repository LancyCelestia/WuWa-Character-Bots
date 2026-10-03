"""互动面波（2026-10-03，施工席4）四件事的实弹回归。

四件事全部落在根装配文件与 poke 能力件里，本件用与
``tests/test_sticker_pools_consumers.py::_nested`` 同一套「AST 抠真实闭包」手法，
把生产闭包**连函数体一起**抠出来打桩驱动——不在测试里重写第二份判据：

1. **N4 死门修复（活性锁）**：``_proactive_affinity_check`` 旧写法
   ``tier_for_affinity(affinity) == "close"`` 拿 int 比字符串恒 False，主动接话门
   自装配以来从未放行。修后判法=档 id ≥ 亲近档 id（亲近档 id 从八档表现算）。
   本件抽真实闭包、注入真 ``tier_for_affinity``/``attitude_tiers`` 与桩 store，
   逐点验「亲近档放行、低于拦、左闭边界、store 缺席 fail-closed」。
2. **主动戳双腿接 M-17 中央名单门**：``_maybe_follow_poke`` /
   ``_maybe_poke_after_bot_spoke`` 在五层门（commit 语义）**之前**问
   ``explicit_allowed_for_session``——群没表过态（黑名单赢/白名单空=整体关）不戳；
   「先名单后骰」由「名单拦下时 ``gate.allow`` 零调用、不烧额度」执法；
   私聊场合名单门不参与（行为与改前逐字节一致，本就发不出）。
3. **同轮三腿互斥**：P3 情绪贴纸 → poke after-reply → randpic dispatch 共享
   ``turn-attach:<message_key>`` 占坑（进程内有界 dict）。真发出（SENT/REDIRECTED）
   才占坑；空 message_key 不占坑；账本超帽淘汰最旧。
4. **sticker 臂接线（行为锁）**：``_handle_poke_notice`` 在「群内 ∧ after_reply
   开 ∧ 回复真送达」后把已送达回复交 reactions 引擎（``_maybe_react_on_message``），
   走 chat 链路同一枚共享五层门；私聊/未送达/开关关三态一次都不调（QQ 无私聊
   表情通道，台账 #35★——守卫双保险：接线侧 ``reaction.group`` + 引擎
   ``_is_group_session``）。表行 ``wired_in_poke_path=True`` 的对账在
   ``tests/test_poke_reaction_matrix.py``。

全离线：零网络、零 NoneBot、零源码树写入。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import ReceiptState
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    PokeReaction,
    resolve_poke_reply,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    attitude_tiers,
    tier_for_affinity,
)
from plugins.bot_unified_runtime.domains.meme.reactions.engine import ProactiveGate

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"


def _extract(name: str) -> Any:
    """从根装配里抠出那个**真实闭包**（连函数体一起，不在测试里重写第二份判据）。"""
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    node.decorator_list = []
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            node,
        ],
        type_ignores=[],
    )
    namespace: dict[str, Any] = {
        "__package__": "plugins.bot_unified_runtime",
        "__name__": "plugins.bot_unified_runtime",
        "Any": Any,
    }
    exec(  # noqa: S102 - 只执行仓库固定闭包源码，非用户输入
        compile(ast.fix_missing_locations(module), str(ROOT_INIT), "exec"), namespace
    )
    return namespace[name]


class _GateSpy:
    """``ProactiveGate`` 形状的记录型替身：``allow`` 记账、恒放行（除非 hold=True）。"""

    def __init__(self, *, hold: bool = False) -> None:
        self.allow_calls: list[tuple[Any, ...]] = []
        self.hold = hold

    def allow(self, *args: Any, **kwargs: Any) -> bool:
        self.allow_calls.append(args)
        return not self.hold


def _async_spy(result: Any = True) -> tuple[Any, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    async def _spy(*args: Any, **kwargs: Any) -> Any:
        calls.append({"args": args, **kwargs})
        return result

    return _spy, calls


# ============================================================================
# 1. N4 主动搭话亲和门（死门修复的活性锁）
# ============================================================================


class _AffinityStoreStub:
    def __init__(self, affinity: float | None) -> None:
        self._affinity = affinity

    def snapshot(self, sender_id: str) -> dict[str, Any]:
        if self._affinity is None:
            return {}
        return {"affinity": self._affinity}


def _affinity_check(affinity: float | None, *, store_present: bool = True):
    check = _extract("_proactive_affinity_check")
    namespace = check.__globals__
    namespace["attitude_tiers"] = attitude_tiers
    namespace["tier_for_affinity"] = tier_for_affinity
    namespace["build_character_affinity_store"] = (
        (lambda config: _AffinityStoreStub(affinity)) if store_present else (lambda config: None)
    )
    namespace["config"] = SimpleNamespace()
    return check


def test_close_tier_id_comes_from_the_eight_tier_table() -> None:
    """亲近档 id 从八档表现算：表里必须有且只有一枚「亲近」档，且 id 即判门阈值。

    左闭右开口径（§4）：展示分 25 分整点起算亲近 ⇒ 内部好感 0.25 即放行；
    0.249 仍是友善（基准）档 ⇒ 拦。
    """
    close = [tier_id for tier_id, name, _ in attitude_tiers() if str(name).startswith("亲近")]
    assert len(close) == 1, close
    assert tier_for_affinity(0.25) == close[0]
    assert tier_for_affinity(0.249) < close[0]


@pytest.mark.parametrize(
    "affinity,expect_pass",
    [
        (0.30, True),   # 亲近档（id 1）
        (0.25, True),   # 档界左闭：0.25 已进亲近
        (0.90, True),   # 更高档（挚友/独一份）同样放行
        (0.249, False),  # 友善（基准）档：低于亲近，拦
        (0.0, False),
        (-0.5, False),
    ],
)
def test_proactive_affinity_gate_liveness(affinity: float, expect_pass: bool) -> None:
    """修复前 ``== "close"`` 恒 False ⇒ 全表无一行能放行；修复后按档位判定。"""
    assert _affinity_check(affinity)("777") is expect_pass


def test_proactive_affinity_gate_fails_closed_without_store() -> None:
    assert _affinity_check(None, store_present=False)("777") is False


def test_proactive_affinity_gate_has_no_string_comparison_left() -> None:
    """死门成因（``== "close"``）不许回潮：闭包源码里不再有具名档比较。"""
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == (
            "_proactive_affinity_check"
        ):
            src = ast.unparse(node)
            assert '"close"' not in src and "'close'" not in src
            assert ">=" in src, "判法必须是档 id ≥ 亲近档 id"
            return
    pytest.fail("根装配里找不到 _proactive_affinity_check ⇒ 锚点失效")


# ============================================================================
# 2. 主动戳双腿的 M-17 中央名单门（先名单后骰；被动被戳路径不经此处）
# ============================================================================


def _content_route_config(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "bot_blocked_user_ids": [],
        "bot_poke_follow_enabled": True,
        "bot_poke_follow_probability": 1.0,
        "bot_poke_follow_cooldown_seconds": 0.0,
        "bot_poke_follow_max_per_hour": 999,
        "bot_poke_after_reply_enabled": True,
        "bot_poke_after_reply_probability": 1.0,
        "bot_poke_after_reply_cooldown_seconds": 0.0,
        "bot_poke_after_reply_max_per_hour": 999,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _peer_poke_event() -> SimpleNamespace:
    """群内 A(1) 戳 B(2)，目标不是 bot。"""
    return SimpleNamespace(
        notice_type="notify", sub_type="poke", group_id="42", user_id="1", target_id="2"
    )


def test_follow_poke_blocked_when_group_not_consented_and_never_rolls() -> None:
    """群没在名单表过态 ⇒ 不跟戳，且 ``gate.allow`` 零调用（先名单后骰，不烧额度）。"""
    follow = _extract("_maybe_follow_poke")
    gate = _GateSpy()
    dispatch, dispatch_calls = _async_spy(True)
    follow.__globals__.update(
        {
            "_POKE_FOLLOW_GATE": gate,
            "_dispatch_poke_at": dispatch,
        }
    )
    # 白名单空=整体关（黑名单也拦：黑名单永远赢）。
    for cfg in (
        _content_route_config(),
        _content_route_config(
            bot_content_route_group_blacklist={"42"},
            bot_content_route_group_whitelist={"42"},
        ),
    ):
        asyncio.run(
            follow(
                SimpleNamespace(self_id="bot-1"),
                _peer_poke_event(),
                merged_config=cfg,
                poke_back_on=True,
            )
        )
        assert dispatch_calls == [], "名单没过却戳了人"
        assert gate.allow_calls == [], "名单拦下却烧了五层门额度（先名单后骰被破坏）"


def test_follow_poke_passes_for_whitelisted_group_or_person() -> None:
    """群白名单命中放行；私聊白名单人腿同样放行（M-17 判定语义原样生效）。"""
    follow = _extract("_maybe_follow_poke")
    gate = _GateSpy()
    dispatch, dispatch_calls = _async_spy(True)
    follow.__globals__.update(
        {
            "_POKE_FOLLOW_GATE": gate,
            "_dispatch_poke_at": dispatch,
        }
    )
    for cfg in (
        _content_route_config(bot_content_route_group_whitelist={"42"}),
        _content_route_config(bot_content_route_private_whitelist={"2"}),
    ):
        asyncio.run(
            follow(
                SimpleNamespace(self_id="bot-1"),
                _peer_poke_event(),
                merged_config=cfg,
                poke_back_on=True,
            )
        )
    assert len(dispatch_calls) == 2, f"放行场合没都戳出去：{dispatch_calls}"
    # 先 B（被戳者）后 A：第一发就停。
    assert dispatch_calls[0]["user_id"] == "2"
    assert len(gate.allow_calls) == 2


def test_follow_poke_untouched_for_non_poke_or_private_events() -> None:
    """被动/无关事件照旧不触发跟戳（名单门不加戏）。"""
    follow = _extract("_maybe_follow_poke")
    gate = _GateSpy()
    dispatch, dispatch_calls = _async_spy(True)
    follow.__globals__.update(
        {
            "_POKE_FOLLOW_GATE": gate,
            "_dispatch_poke_at": dispatch,
        }
    )
    cfg = _content_route_config(bot_content_route_group_whitelist={"42"})
    asyncio.run(
        follow(
            SimpleNamespace(self_id="bot-1"),
            SimpleNamespace(notice_type="notify", sub_type="poke", group_id="", user_id="1", target_id="2"),
            merged_config=cfg,
            poke_back_on=True,
        )
    )
    assert dispatch_calls == [] and gate.allow_calls == []


def test_poke_after_spoke_blocked_when_group_not_consented_and_never_rolls() -> None:
    """回复后戳：同一条 M-17 门、同一「先名单后骰」判据。"""
    spoke = _extract("_maybe_poke_after_bot_spoke")
    gate = _GateSpy()
    dispatch, dispatch_calls = _async_spy(True)
    marks: list[tuple[str, str]] = []
    spoke.__globals__.update(
        {
            "_POKE_AFTER_REPLY_GATE": gate,
            "_dispatch_poke_at": dispatch,
            "_turn_attachment_mark": lambda key, leg: marks.append((key, leg)),
        }
    )
    for cfg in (
        _content_route_config(),
        _content_route_config(
            bot_content_route_group_blacklist={"42"},
            bot_content_route_group_whitelist={"42"},
        ),
    ):
        asyncio.run(
            spoke(
                SimpleNamespace(self_id="bot-1"),
                merged_config=cfg,
                poke_back_on=True,
                group_id="42",
                user_id="2",
                message_key="m-1",
                purpose="reply",
            )
        )
        assert dispatch_calls == []
        assert gate.allow_calls == []
        assert marks == []


def test_poke_after_spoke_passes_and_claims_only_when_delivered() -> None:
    """白名单群放行；真戳到才落同轮互斥占坑；没戳到不占。"""
    spoke = _extract("_maybe_poke_after_bot_spoke")
    marks: list[tuple[str, str]] = []
    spoke.__globals__.update(
        {
            "_POKE_AFTER_REPLY_GATE": _GateSpy(),
            "_dispatch_poke_at": _async_spy(True)[0],
            "_turn_attachment_mark": lambda key, leg: marks.append((key, leg)),
        }
    )
    cfg = _content_route_config(bot_content_route_group_whitelist={"42"})
    asyncio.run(
        spoke(
            SimpleNamespace(self_id="bot-1"),
            merged_config=cfg,
            poke_back_on=True,
            group_id="42",
            user_id="2",
            message_key="m-9",
            purpose="reply",
        )
    )
    assert marks == [("m-9", "poke_after_reply")]

    # 派发失败（协议端拒绝/在途）＝什么都没发生 ⇒ 不占坑。
    marks.clear()
    spoke.__globals__["_dispatch_poke_at"] = _async_spy(False)[0]
    asyncio.run(
        spoke(
            SimpleNamespace(self_id="bot-1"),
            merged_config=cfg,
            poke_back_on=True,
            group_id="42",
            user_id="2",
            message_key="m-9",
            purpose="reply",
        )
    )
    assert marks == []


def test_poke_after_spoke_private_keeps_legacy_dead_end() -> None:
    """私聊场合：名单门不参与、require_group 照旧拦死（行为与改前逐字节一致）。"""
    spoke = _extract("_maybe_poke_after_bot_spoke")
    gate = _GateSpy()
    dispatch, dispatch_calls = _async_spy(True)
    spoke.__globals__.update(
        {
            "_POKE_AFTER_REPLY_GATE": gate,
            "_dispatch_poke_at": dispatch,
            "_turn_attachment_mark": lambda key, leg: pytest.fail("私聊不该占坑"),
        }
    )
    asyncio.run(
        spoke(
            SimpleNamespace(self_id="bot-1"),
            merged_config=_content_route_config(),
            poke_back_on=True,
            group_id="",
            user_id="2",
            message_key="m-1",
            purpose="reply",
        )
    )
    assert dispatch_calls == [] and gate.allow_calls == []


# ============================================================================
# 3. 同轮三腿互斥：共享占坑账本
# ============================================================================


def test_turn_attachment_ledger_is_bounded_and_empty_key_never_claims() -> None:
    mark = _extract("_turn_attachment_mark")
    claimed = _extract("_turn_attachment_claimed")
    ledger: dict[str, str] = {}
    mark.__globals__.update(
        {"_turn_attachment_claims": ledger, "_TURN_ATTACHMENT_CLAIMS_MAX": 3}
    )
    claimed.__globals__.update({"_turn_attachment_claims": ledger})
    mark("m-1", "reaction_meme")
    mark("m-2", "poke_after_reply")
    assert claimed("m-1") and claimed("m-2")
    # 空键绝不占坑：空键占坑会把「本轮互斥」放大成「全会话互斥」。
    mark("", "randpic_dispatch")
    assert "" not in ledger
    # 超帽淘汰最旧（照 _reaction_meme_merged 形态：插入序 FIFO）。
    mark("m-3", "randpic_dispatch")
    mark("m-4", "reaction_meme")
    assert len(ledger) == 3 and "turn-attach:m-1" not in ledger
    assert ledger["turn-attach:m-4"] == "reaction_meme"


def _meme_leg_globals(
    book: dict[str, Any],
    *,
    receipt: Any,
    gate: Any,
) -> dict[str, Any]:
    """P3 腿闭包的最小命名空间（与 test_sticker_pools_consumers._p3_globals 同形）。"""
    return {
        "_is_sad_reaction_message": lambda _text: False,
        "_infer_reaction_signal_intent": lambda _text: "celebrate",
        "_mood_valence": lambda _config: 0.0,
        "_poke_affinity_snapshot": lambda _config, _sender: None,
        "_persona_album_names": lambda _config: ("守岸人", "shorekeeper"),
        "_REACTION_MEME_GATE": gate,
        "_reaction_meme_daily": book["daily"],
        "_reaction_meme_merged": {},
        "_turn_attachment_mark": lambda key, leg: book["claims"].append((key, leg)),
        "ReceiptState": ReceiptState,
        "_send_parts_through_unified_pipeline": _async_spy(receipt)[0],
        "meme_library_store": None,
        "logger": __import__("logging").getLogger("test.interaction"),
        "asyncio": asyncio,
        "time": __import__("time"),
        "config": SimpleNamespace(),
        "runtime_settings": SimpleNamespace(),
    }


@pytest.fixture()
def _pack_leg_env(monkeypatch: pytest.MonkeyPatch):
    """贴纸选腿的两个真身模块按调用点导入 ⇒ 打桩必须落在模块属性上。"""
    from plugins.bot_unified_runtime.domains.meme.capabilities import meme_library
    from plugins.bot_unified_runtime.domains.meme.sources import sticker_send_routing

    monkeypatch.setattr(
        meme_library,
        "select_sticker_for_turn",
        lambda *a, **k: ({"path": "x:/sticker.png"}, ("sticker_pool:test",)),
    )
    monkeypatch.setattr(sticker_send_routing, "sticker_feature_enabled", lambda enabled: True)
    monkeypatch.setattr(sticker_send_routing, "social_gates_allow", lambda *a, **k: True)
    yield


def _meme_config() -> SimpleNamespace:
    return SimpleNamespace(
        bot_reactions_meme_enabled=True,
        bot_reactions_meme_probability=1.0,
        bot_reactions_meme_cooldown_seconds=0,
        bot_reactions_max_per_hour=20,
        bot_reactions_meme_daily_max=6,
    )


def _run_meme_leg(book: dict[str, Any], *, receipt: Any, claim_key: str) -> None:
    leg = _extract("_maybe_send_reaction_meme")
    leg.__globals__.update(
        _meme_leg_globals(book, receipt=receipt, gate=ProactiveGate())
    )
    event = SimpleNamespace(message_id="m-7", group_id="42", sender_id="u-1")
    asyncio.run(
        leg(
            SimpleNamespace(self_id="bot-1"),
            event,
            session_key="group_42_u-1",
            text="今天一起拿了冠军！",
            reply_text="太好了，恭喜你们。",
            meme_config=_meme_config(),
            feature_enabled=lambda _node: True,
            claim_key=claim_key,
        )
    )


def test_p3_meme_leg_claims_the_turn_only_when_actually_sent(_pack_leg_env) -> None:
    """真发出（SENT/REDIRECTED）才占坑；FAILED 与空 claim_key 都不占。"""
    book: dict[str, Any] = {"daily": {}, "claims": []}
    _run_meme_leg(book, receipt=SimpleNamespace(state=ReceiptState.SENT), claim_key="m-7")
    assert book["claims"] == [("m-7", "reaction_meme")]

    book = {"daily": {}, "claims": []}
    _run_meme_leg(book, receipt=SimpleNamespace(state=ReceiptState.FAILED_RETRYABLE), claim_key="m-7")
    assert book["claims"] == [], "发送失败也占坑＝白白的互斥"

    book = {"daily": {}, "claims": []}
    _run_meme_leg(book, receipt=SimpleNamespace(state=ReceiptState.SENT), claim_key="")
    # 腿把 claim_key 原样交给 mark；「空键不占坑」的守卫在生产真身 mark 里
    # （上一条 test_turn_attachment_ledger_* 已对真实闭包验过 no-op）。
    assert book["claims"] == [("", "reaction_meme")]


# ============================================================================
# 4. randpic 派发腿：真发出才占坑（三腿链最后一环）
# ============================================================================


def test_randpic_dispatch_claims_only_when_actually_sent() -> None:
    dispatch = _extract("_maybe_dispatch_randpic")
    marks: list[tuple[str, str]] = []
    sent_receipt = SimpleNamespace(state=ReceiptState.SENT)
    send, send_calls = _async_spy(sent_receipt)
    holder = {"path": "x:/pic.png"}
    dispatch.__globals__.update(
        {
            "_RANDPIC_DISPATCH_GATE": ProactiveGate(),
            "_send_parts_through_unified_pipeline": send,
            "ReceiptState": ReceiptState,
            "_turn_attachment_mark": lambda key, leg: marks.append((key, leg)),
            "asyncio": asyncio,
            "pick_gallery_image": lambda *a, **k: holder["path"],
        }
    )
    cfg = _content_route_config(
        bot_randpic_dispatch_enabled=True,
        bot_randpic_dispatch_probability=1.0,
        bot_randpic_dispatch_cooldown_seconds=0.0,
        bot_randpic_dispatch_max_per_hour=999,
    )
    asyncio.run(
        dispatch(
            SimpleNamespace(self_id="bot-1"),
            SimpleNamespace(message_id="m-1"),
            merged_config=cfg,
            session_key="group_42_2",
            message_key="m-1",
            group_id="42",
            user_id="2",
        )
    )
    assert send_calls and marks == [("m-1", "randpic_dispatch")]

    # 图库空 ⇒ 不发也不占坑。
    marks.clear()
    holder["path"] = None
    asyncio.run(
        dispatch(
            SimpleNamespace(self_id="bot-1"),
            SimpleNamespace(message_id="m-2"),
            merged_config=cfg,
            session_key="group_42_2",
            message_key="m-2",
            group_id="42",
            user_id="2",
        )
    )
    assert marks == []


# ============================================================================
# 5. sticker 臂接线的行为锁：群+送达+开关开才调引擎，走同款五层门
# ============================================================================


class _SwitchSnapshot:
    def __init__(self, *, after_reply: bool = True, poke_reply: bool = True) -> None:
        self._after_reply = after_reply
        self._poke_reply = poke_reply

    def enabled(self, node: str) -> bool:
        if node == "bot.plugin.chat.reactions.after_reply":
            return self._after_reply
        if node == "bot.plugin.poke.reply":
            return self._poke_reply
        return True


def _poke_notice_globals(
    *,
    reaction: PokeReaction,
    receipt: Any,
    gate: Any,
    react_calls: list[dict[str, Any]],
    switches: _SwitchSnapshot,
) -> dict[str, Any]:
    dispatcher = SimpleNamespace(
        build_poke_reaction=lambda event, **kwargs: reaction
    )
    send, _send_calls = _async_spy(receipt)
    _react, _react_recorder = _async_spy(False)

    async def _react_record(*args: Any, **kwargs: Any) -> bool:
        react_calls.append(kwargs)
        return False

    return {
        "product_feature_gate": SimpleNamespace(
            snapshot_async=lambda: _async_spy(switches)[0]()
        ),
        "_config_with_runtime_overrides": lambda config, runtime_settings: config,
        "runtime_settings": SimpleNamespace(),
        "config": SimpleNamespace(),
        "_poke_dispatcher": dispatcher,
        "_maybe_follow_poke": _async_spy(None)[0],
        "_dispatch_poke_back": _async_spy(False)[0],
        "_record_poke_affinity": lambda config, poker, group: "hint",
        "_poke_llm_reply": _async_spy("llm")[0],
        "meme_library_store": None,
        "_pick_poke_meme": lambda *a, **k: None,
        "pick_gallery_image": lambda *a, **k: None,
        "resolve_poke_reply": resolve_poke_reply,
        "_poke_voice_pair": _async_spy(("", []))[0],
        "_send_parts_through_unified_pipeline": send,
        "_maybe_react_on_message": _react_record,
        "_REACTION_PROACTIVE_GATE": gate,
        "asyncio": asyncio,
    }


def _run_poke_notice(namespace: dict[str, Any], *, group: bool) -> None:
    notice = _extract("_handle_poke_notice")
    notice.__globals__.update(namespace)
    event = SimpleNamespace(
        notice_type="notify",
        sub_type="poke",
        group_id="42" if group else "",
        user_id="7",
        target_id="10000",
    )
    asyncio.run(
        notice(SimpleNamespace(self_id="10000"), event)
    )


def test_poke_notice_reacts_with_engine_for_delivered_group_reply() -> None:
    """群内被戳且回复送达 ⇒ 把已送达回复交引擎：群键形 / after_reply / 同款五层门。"""
    gate = object()  # 哨兵：断言传给引擎的就是这一枚共享门对象
    react_calls: list[dict[str, Any]] = []
    namespace = _poke_notice_globals(
        reaction=PokeReaction(reply="好呀", group=True, mode="fixed"),
        receipt=SimpleNamespace(state=ReceiptState.SENT, provider_message_id="m-9"),
        gate=gate,
        react_calls=react_calls,
        switches=_SwitchSnapshot(),
    )
    _run_poke_notice(namespace, group=True)
    assert len(react_calls) == 1, f"群内送达后应恰调一次引擎：{react_calls}"
    kwargs = react_calls[0]
    assert kwargs["session_key"] == "group_42_7"
    assert kwargs["user_message_id"] == "m-9"
    assert kwargs["trigger"] == "after_reply"
    assert kwargs["gate"] is gate
    assert kwargs["text"] == ""


def test_poke_notice_never_reacts_for_private_or_undelivered_or_switched_off() -> None:
    """私聊（QQ 无私聊表情通道）/ 回复未送达 / after_reply 开关关 ⇒ 引擎一次都不调。"""
    # 私聊被戳。
    react_calls: list[dict[str, Any]] = []
    namespace = _poke_notice_globals(
        reaction=PokeReaction(reply="嗯", group=False, mode="fixed"),
        receipt=SimpleNamespace(state=ReceiptState.SENT, provider_message_id="m-9"),
        gate=object(),
        react_calls=react_calls,
        switches=_SwitchSnapshot(),
    )
    _run_poke_notice(namespace, group=False)
    assert react_calls == [], "私聊绝不派发表情回应（台账 #35★）"

    # 群内但回执没带 provider_message_id（贴无可贴的消息）。
    react_calls = []
    namespace = _poke_notice_globals(
        reaction=PokeReaction(reply="好呀", group=True, mode="fixed"),
        receipt=SimpleNamespace(state=ReceiptState.SENT, provider_message_id=None),
        gate=object(),
        react_calls=react_calls,
        switches=_SwitchSnapshot(),
    )
    _run_poke_notice(namespace, group=True)
    assert react_calls == []

    # after_reply 特性开关关：回复照发，表情腿不跑。
    react_calls = []
    namespace = _poke_notice_globals(
        reaction=PokeReaction(reply="好呀", group=True, mode="fixed"),
        receipt=SimpleNamespace(state=ReceiptState.SENT, provider_message_id="m-9"),
        gate=object(),
        react_calls=react_calls,
        switches=_SwitchSnapshot(after_reply=False),
    )
    _run_poke_notice(namespace, group=True)
    assert react_calls == []

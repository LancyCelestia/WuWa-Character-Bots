"""三条「发贴纸」消费腿的**换池锁**（S-STICKER-POOLS，2026-09-29）+ S2 案二**同消息并图钩子**的锁（W4R，2026-09-30）。

> 用例数以实跑为准（AGENTS 规则 10），本文不手写计数。

钉的是下面这些事，全部离线：

1. **主动腿只吃贴纸池**：``select_sticker_for_turn(..., pool_policy="packs_only")``
   命中时交回 ``sticker_packs.pick_sticker`` 那张，并留 ``sticker_pool:sticker_packs``；
2. **主动腿绝不回退吸收池**：贴纸池挑不出（空 / 关 / 件缺席 / 抛异常）时交回
   ``(None, [... "sticker_pool:none"])``，且**根本不碰** ``store.weighted_pick``
   ——这一条是用户实弹点名的红线（现网「没命令自己甩图」甩的就是别人群里的截图）；
3. **指令路保留兜底**：缺省 ``pool_policy`` 下贴纸池空 ⇒ 落回既有表情库加权腿，
   并留 ``sticker_pool:meme_library``（审计轨能答「这张来自哪个池」）；
4. **三道硬门**：``bot.plugin.sticker_packs`` 特性门（**没给快照查询口＝不通过**）、
   ``is_blocked_target``、``quiet_hours_active``，一条不过就什么都不发；
5. **P3 腿端到端**（AST 抠出根装配里的真实闭包跑实链路）：全门开 ∧ 池子有货 ⇒ 发一张；
   池子空 ⇒ 零发送、零异常、静默（审计轨 ``none`` 可查），且吸收池那条路一次都没被走过；
6. **戳一戳 meme 臂同规则**：挑不出 ⇒ ``None`` ⇒ ``resolve_poke_reply`` 落回固定话术。

``sticker_packs`` 由另一席并行落笔，本件**不 import 它的真身**：所有用例经
``sys.modules`` 注入替身。缺席态另有一把锁，且**由夹具以 ``None`` 占坑真造**
（件早已在树里 ⇒ 光清缓存等于没模拟，详见 :func:`_packs_module_absent_by_default`）。
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import logging
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    ContextBundle,
    ConversationHistoryResult,
    IncomingMessage,
    MemoryRetrievalResult,
    PersonaProfile,
    PrivacyLevel,
    ReceiptState,
    RetrievalResult,
    RiskLevel,
    SendPolicy,
    SessionType,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    _sticker_attach_parts,
    build_chat_result,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    resolve_poke_reply,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import LLMReply
from plugins.bot_unified_runtime.domains.meme.capabilities.meme_library import (
    select_sticker_for_turn,
)
from plugins.bot_unified_runtime.domains.meme.reactions.engine import ProactiveGate
from plugins.bot_unified_runtime.domains.meme.sources import sticker_send_routing

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "plugins/bot_unified_runtime/__init__.py"
CHAT_SOURCE = ROOT / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py"
PACKS_MODULE = "plugins.bot_unified_runtime.domains.meme.sources.sticker_packs"
#: 池件的磁盘路径——缺席锁用它自证「本锁测的是导入失败、不是件没了」。
PACKS_SOURCE = ROOT / "plugins/bot_unified_runtime/domains/meme/sources/sticker_packs.py"
SOURCES_PACKAGE = "plugins.bot_unified_runtime.domains.meme.sources"

PACKS = sticker_send_routing.POOL_STICKER_PACKS
LIBRARY = sticker_send_routing.POOL_MEME_LIBRARY
NONE_POOL = sticker_send_routing.POOL_NONE
PACKS_ONLY = sticker_send_routing.POOL_POLICY_PACKS_ONLY
PACKS_THEN_LIBRARY = sticker_send_routing.POOL_POLICY_PACKS_THEN_LIBRARY
FEATURE_ID = sticker_send_routing.STICKER_PACKS_FEATURE_ID

#: 吸收池替身会交回的那张图——本件所有「绝不回退」断言的靶子。
ABSORBED = "C:/absorbed/group_screenshot.png"


# --------------------------------------------------------------------- 替身
class RecordingStore:
    """吸收池替身：一旦被调就记账——「主动腿有没有偷偷回退」的探针。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def weighted_pick(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(kwargs)
        return {"path": ABSORBED, "sticker_reason": "why=random"}

    def eligible_count(self, **_kwargs: Any) -> int:  # pragma: no cover - 未被调
        return 0


class FakeStickerPacks:
    """``sticker_packs`` 替身（真身归另一席，本件零 import）。"""

    def __init__(
        self,
        *,
        images: tuple[str, ...] = (),
        picks: tuple[str, ...] | None = None,
        disabled: bool = False,
        boom: bool = False,
    ) -> None:
        self.images = [] if disabled else [Path(item) for item in images]
        self._picks = list(picks) if picks is not None else list(self.images)
        self.boom = boom
        self.pick_calls: list[dict[str, Any]] = []

    def list_sticker_images(self, config: Any) -> list[Path]:
        return list(self.images)

    def configured_sticker_dir(self, config: Any) -> Path | None:
        return self.images[0].parent if self.images else None

    def pick_sticker(
        self,
        config: Any,
        *,
        session_key: str = "",
        seed: str = "",
        allow_exhausted: bool = True,
        persona_names: tuple[str, ...] = (),
        prefer_tags: tuple[str, ...] = (),
        locked_subdirs: tuple[str, ...] = (),
    ) -> Path | None:
        if self.boom:
            raise RuntimeError("pack picker exploded")
        self.pick_calls.append(
            {
                "session_key": session_key,
                "seed": seed,
                "allow_exhausted": allow_exhausted,
                "persona_names": tuple(persona_names or ()),
                "prefer_tags": tuple(prefer_tags or ()),
                "locked_subdirs": tuple(locked_subdirs or ()),
            }
        )
        return self._picks[0] if self._picks else None


class SendSpy:
    """``_send_parts_through_unified_pipeline`` 替身：记账，不真发。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        async def _coro() -> SimpleNamespace:
            self.calls.append({"args": args, **kwargs})
            return SimpleNamespace(status="SENT")

        return _coro()

    @property
    def count(self) -> int:
        return len(self.calls)


def _config(**overrides: Any) -> SimpleNamespace:
    """一枚「什么都像 Config」的鸭子类型配置：只放本件用到的键。"""
    base: dict[str, Any] = {
        "bot_reactions_meme_enabled": True,
        "bot_reactions_meme_probability": 1.0,
        "bot_reactions_meme_cooldown_seconds": 0.0,
        "bot_reactions_max_per_hour": 99,
        "bot_reactions_meme_daily_max": 6,
        "bot_reactions_sentiment_enabled": False,
        "bot_meme_library_prefer": [],
        "bot_meme_library_nsfw_max": 0.2,
        "bot_meme_sticker_scope_mode": "global",
        "bot_blocked_user_ids": [],
        "bot_quiet_hours_enabled": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


#: 整日在窗内的安静时间配置（start == end ⇒ 恒真，判据见 poke.quiet_hours_active）。
def _always_quiet(**overrides: Any) -> SimpleNamespace:
    return _config(
        bot_quiet_hours_enabled=True,
        bot_quiet_hours_start="00:00",
        bot_quiet_hours_end="00:00",
        bot_quiet_hours_timezone="UTC",
        bot_quiet_hours_session_types=["group", "private"],
        **overrides,
    )


@pytest.fixture(autouse=True)
def _packs_module_absent_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认态：``sticker_packs`` **引不到**——缺席腿的锁要靠这个才咬得住。

    换代记录（本夹具原本只清 ``sys.modules`` + 删包属性）：那两下只在**件还没落盘**
    的世界里等于「缺席」。件已在树里之后，``from . import sticker_packs`` 会就地
    重新加载真身 ⇒ 缺席锁实际读到的是「件在场 ∧ 池子恰好空」，看着绿、其实空转。
    现按 ``None`` 占坑：CPython 见到 ``sys.modules[name] is None`` 直接抛
    ``ImportError``，走的正是生产腿 ``sticker_packs_module`` 那条「导入失败＝诚实
    缺席」真分支（现网对应件被裁掉 / 依赖导入炸）。
    """
    monkeypatch.setitem(sys.modules, PACKS_MODULE, None)
    monkeypatch.delattr(importlib.import_module(SOURCES_PACKAGE), "sticker_packs", raising=False)
    sticker_send_routing.reset_pool_audit()


@pytest.fixture
def install_packs(monkeypatch: pytest.MonkeyPatch):
    """把替身装成 ``sticker_packs`` 真身（``from . import sticker_packs`` 走得通）。"""

    def _install(packs: FakeStickerPacks) -> FakeStickerPacks:
        holder = ModuleType(PACKS_MODULE)
        for name in ("pick_sticker", "list_sticker_images", "configured_sticker_dir"):
            setattr(holder, name, getattr(packs, name))
        holder.packs = packs  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, PACKS_MODULE, holder)
        monkeypatch.setattr(
            importlib.import_module(SOURCES_PACKAGE), "sticker_packs", holder, raising=False
        )
        return packs

    return _install


# ---------------------------------------------------------------- 1. 池子命中
def test_packs_only_leg_uses_pack_image(install_packs) -> None:
    packs = install_packs(FakeStickerPacks(images=("D:/packs/红猪/a.png",)))
    picked, tags = select_sticker_for_turn(
        RecordingStore(),
        session_key="group_1_2",
        config=_config(),
        pool_policy=PACKS_ONLY,
        pool_seed="seed-a",
    )
    assert picked is not None and str(picked["path"]).endswith("a.png")
    assert picked["pool"] == PACKS
    assert f"sticker_pool:{PACKS}" in tags
    assert tags[0] == "meme_sticker"
    assert packs.pick_calls[0]["session_key"] == "group_1_2"
    assert packs.pick_calls[0]["seed"] == "seed-a"
    assert packs.pick_calls[0]["allow_exhausted"] is False, "主动腿整库在窗内也不许退「最久没发」"
    assert sticker_send_routing.last_pool_for("group_1_2") == PACKS


def test_pack_seed_defaults_to_session_key(install_packs) -> None:
    packs = install_packs(FakeStickerPacks(images=("D:/packs/a.png",)))
    select_sticker_for_turn(
        None, session_key="private_7", config=_config(), pool_policy=PACKS_ONLY
    )
    assert packs.pick_calls and packs.pick_calls[0]["seed"] == "private_7"


# ------------------------------------------------- 2. 主动腿绝不回退吸收池
@pytest.mark.parametrize(
    "packs",
    [
        pytest.param(FakeStickerPacks(), id="池子空"),
        pytest.param(FakeStickerPacks(disabled=True), id="开关关掉＝交回空表"),
        pytest.param(FakeStickerPacks(images=("D:/packs/a.png",), picks=()), id="有货但挑不出"),
        pytest.param(FakeStickerPacks(images=("D:/packa/a.png",), boom=True), id="挑图抛异常"),
    ],
)
def test_packs_only_never_touches_meme_library(packs, install_packs) -> None:
    install_packs(packs)
    store = RecordingStore()
    picked, tags = select_sticker_for_turn(
        store,
        session_key="group_9_9",
        config=_config(),
        pool_policy=PACKS_ONLY,
        reply_text="今天一起拿了冠军！",
    )
    assert picked is None, "主动腿回退成吸收池那张＝红线破"
    assert store.calls == [], "packs_only 下根本不该调 weighted_pick"
    assert "none" in tags and f"sticker_pool:{NONE_POOL}" in tags
    assert sticker_send_routing.last_pool_for("group_9_9") == NONE_POOL


def test_packs_only_with_absent_pack_module_is_silent() -> None:
    """``sticker_packs`` 引不到（夹具占坑）⇒ 不发、不抛、审计轨留 none。"""
    store = RecordingStore()
    picked, tags = select_sticker_for_turn(
        store, session_key="group_5_5", config=_config(), pool_policy=PACKS_ONLY
    )
    assert picked is None
    assert store.calls == []
    assert f"sticker_pool:{NONE_POOL}" in tags


def test_pool_available_reports_absent_module() -> None:
    # 件确在树里 ⇒ 本锁测的是「导入失败＝诚实缺席」那条真分支（夹具 None 占坑模拟），
    # 不是「另一席未落笔」的哨兵；哪天件真被搬走，这句先红、提醒换代而不是空转。
    assert PACKS_SOURCE.exists(), "贴纸池件已不在树里：缺席锁的口径该重算"
    assert sticker_send_routing.sticker_packs_module() is None
    assert sticker_send_routing.pool_available(_config()) is False
    assert sticker_send_routing.configured_sticker_dir(_config()) is None
    assert sticker_send_routing.pick_from_packs(_config()) is None
    assert sticker_send_routing.list_pack_images(_config()) == []
    # ``module_absent`` 而非 ``missing``：这一枚才分得开「件引不到」与「件在场但池空」。
    assert sticker_send_routing.pool_verdict(_config()) == "module_absent"


def test_pool_available_tracks_the_pack_switch(install_packs) -> None:
    """「开关关掉」的读数＝``list_sticker_images`` 交回空 ⇒ ``pool_available`` False。

    开关的读点在 ``sticker_packs`` 自家（本仓不立第二判据口），所以这里锁的是
    「路由件只看池子拿不拿得出东西」这一条，不是再去读一遍 ``bot_sticker_enabled``。
    """
    install_packs(FakeStickerPacks(disabled=True, images=("D:/packs/a.png",)))
    assert sticker_send_routing.pool_available(_config()) is False
    install_packs(FakeStickerPacks(images=("D:/packs/a.png",)))
    assert sticker_send_routing.pool_available(_config()) is True


# ------------------------------------------------------- 3. 指令路保留兜底
def test_command_policy_falls_back_to_meme_library_when_pool_empty(install_packs) -> None:
    install_packs(FakeStickerPacks())
    store = RecordingStore()
    picked, tags = select_sticker_for_turn(
        store,
        session_key="group_3_3",
        sender_id="u3",
        config=_config(),
        pool_policy=PACKS_THEN_LIBRARY,
    )
    assert picked is not None and str(picked["path"]) == ABSORBED
    assert store.calls, "指令路池子空 ⇒ 必须落回既有加权腿"
    assert f"sticker_pool:{LIBRARY}" in tags
    assert sticker_send_routing.last_pool_for("group_3_3") == LIBRARY


def test_command_policy_prefers_pack_when_available(install_packs) -> None:
    install_packs(FakeStickerPacks(images=("D:/packs/b.png",)))
    store = RecordingStore()
    picked, _tags = select_sticker_for_turn(
        store, session_key="group_3_3", config=_config(), pool_policy=PACKS_THEN_LIBRARY
    )
    assert picked is not None and str(picked["path"]).endswith("b.png")
    assert store.calls == [], "池子有货时不许再动吸收池"


def test_default_policy_is_the_command_policy() -> None:
    """缺省档必须是「先池后库」：漏传 ``pool_policy`` 的旧调用点行为逐字节不变。"""
    import inspect

    signature = inspect.signature(select_sticker_for_turn)
    assert signature.parameters["pool_policy"].default == PACKS_THEN_LIBRARY


# ---------------------------------------------------------------- 4. 三道硬门
def test_feature_gate_is_fail_closed() -> None:
    assert sticker_send_routing.sticker_feature_enabled(None) is False
    assert sticker_send_routing.sticker_feature_enabled(lambda _id: False) is False
    assert sticker_send_routing.sticker_feature_enabled(lambda _id: True) is True

    def boom(_id: str) -> bool:
        raise OSError("snapshot unreadable")

    assert sticker_send_routing.sticker_feature_enabled(boom) is False
    seen: list[str] = []
    sticker_send_routing.sticker_feature_enabled(seen.append)
    assert seen == [FEATURE_ID]


def test_unregistered_feature_is_closed_in_real_catalog() -> None:
    """真目录里没登记 ``bot.plugin.sticker_packs`` ⇒ 快照恒否 ⇒ 主动腿结构性不发。

    登记是另一席的活（feature_catalog 行 + 文档同步）。这条锁读的是**登记前**的
    真实读数：没登记就必须是「关」，而不是「查不到当开」。
    """
    from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
        build_product_descriptors,
    )

    ids = {item.id for item in build_product_descriptors()}
    assert sticker_send_routing.sticker_feature_enabled(lambda node: node in ids) is (
        FEATURE_ID in ids
    )


def test_social_gates_block_blocked_list() -> None:
    config = _config(bot_blocked_user_ids=["bad-actor"])
    assert (
        sticker_send_routing.social_gates_allow(config, group_id="g", user_id="bad-actor")
        is False
    )
    assert (
        sticker_send_routing.social_gates_allow(config, group_id="g", user_id="ok") is True
    )


def test_social_gates_block_quiet_hours_and_missing_target() -> None:
    assert sticker_send_routing.social_gates_allow(_always_quiet(), group_id="g", user_id="u") is False
    assert sticker_send_routing.social_gates_allow(_config(), group_id="g", user_id="") is False
    assert sticker_send_routing.social_gates_allow(None, group_id="g", user_id="u") is False


# ------------------------------------------- 5. P3 腿端到端（AST 抠真实闭包）
def _nested(name: str) -> Any:
    """从根装配里抠出那个**真实闭包**（连函数体一起，不在测试里重写第二份判据）。"""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
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
        compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace
    )
    return namespace[name]


def _fresh_accounts() -> dict[str, Any]:
    """「同一本账」的三件共享对象：日额度 / 五层门 / 并图互斥标。

    钩子与腿必须**共用**这三件（不是各拿一份），否则 S2 并图就悄悄开出了第二本
    额度账与第二个冷却门——那是本波点名要禁的事。
    """
    return {"daily": {}, "gate": ProactiveGate(), "merged": {}}


def _p3_globals(
    *, store: Any, send: SendSpy, accounts: dict[str, Any] | None = None
) -> dict[str, Any]:
    book = accounts if accounts is not None else _fresh_accounts()
    return {
        "_is_sad_reaction_message": lambda _text: False,
        "_infer_reaction_signal_intent": lambda _text: "celebrate",
        "_mood_valence": lambda _config: 0.0,
        "_poke_affinity_snapshot": lambda _config, _sender: None,
        # 人格分册（2026-09-29 B1）之后腿里要现取册名；AST 抠出来的闭包拿不到
        # 外层那个真身，不注入就是 NameError 被调用点的 ``except Exception`` 静吃
        # ——「腿在测试里跑到了」与「腿在生产里发得出」是两回事，本波实踩。
        "_persona_album_names": lambda _config: ("守岸人", "shorekeeper"),
        "_REACTION_MEME_GATE": book["gate"],
        "_reaction_meme_daily": book["daily"],
        "_reaction_meme_merged": book["merged"],
        "_REACTION_MEME_MERGED_MAX": 8,
        # 同轮三腿互斥（2026-10-03）：腿真发出（SENT/REDIRECTED）后落占坑。抠出来的
        # 闭包拿不到外层真身，注入记录型替身——占坑账进 book["claims"]，既有断言
        # 不受影响（不传 claim_key 的旧调用路径不会触达它）。
        "_turn_attachment_mark": lambda key, leg: book.setdefault("claims", []).append(
            (key, leg)
        ),
        "ReceiptState": ReceiptState,
        "_send_parts_through_unified_pipeline": send,
        "meme_library_store": store,
        "logger": logging.getLogger("test.sticker_pools"),
        "asyncio": asyncio,
        "time": time,
    }


def _run_p3(
    *,
    store: Any,
    send: SendSpy,
    config: Any = None,
    feature_enabled: Any = lambda _node: True,
    event: Any = None,
    accounts: dict[str, Any] | None = None,
) -> None:
    leg = _nested("_maybe_send_reaction_meme")
    leg.__globals__.update(_p3_globals(store=store, send=send, accounts=accounts))
    bot = SimpleNamespace(self_id="bot-1")
    target = event or SimpleNamespace(message_id="m-1", group_id="111", sender_id="u-1")
    asyncio.run(
        leg(
            bot,
            target,
            session_key="group_111_u_1",
            text="今天一起拿了冠军！",
            reply_text="太好了，恭喜你们。",
            meme_config=config if config is not None else _config(),
            feature_enabled=feature_enabled,
        )
    )


def test_p3_fires_only_with_pack_and_all_gates(install_packs) -> None:
    install_packs(FakeStickerPacks(images=("D:/packs/红猪/ok.png",)))
    store = RecordingStore()
    send = SendSpy()
    _run_p3(store=store, send=send)
    assert send.count == 1, "全门开 ∧ 池子有货 ⇒ 必须发"
    assert str(send.calls[0]["image"]).endswith("ok.png")
    assert send.calls[0]["image"] != ABSORBED
    assert store.calls == [], "P3 一条都不许碰吸收池"
    tags = send.calls[0]["audit_tags"]
    assert "sticker_pack" in tags and "reaction_meme" in tags
    assert f"sticker_pool:{PACKS}" in tags
    assert send.calls[0]["capability_id"] == "bot.chat", "capability_id 不许改名"


def test_p3_empty_pack_sends_nothing_and_never_degrades(install_packs) -> None:
    install_packs(FakeStickerPacks())
    store = RecordingStore()
    send = SendSpy()
    _run_p3(store=store, send=send)
    assert send.count == 0, "池子空 ⇒ 静默不发（SILENT_AUDIT）"
    assert store.calls == [], "空池绝不退化成发吸收池那张（整条腿的存在理由）"
    assert sticker_send_routing.last_pool_for("group_111_u_1") == NONE_POOL


def test_p3_absent_pack_module_sends_nothing() -> None:
    store = RecordingStore()
    send = SendSpy()
    _run_p3(store=store, send=send)
    assert send.count == 0 and store.calls == []
    assert sticker_send_routing.last_pool_for("group_111_u_1") == NONE_POOL


@pytest.mark.parametrize(
    "kwargs, why",
    [
        ({"feature_enabled": None}, "没给快照查询口"),
        ({"feature_enabled": lambda _node: False}, "特性门未开"),
        ({"config": _config(bot_blocked_user_ids=["u-1"])}, "在 blocked 名单"),
        ({"config": _always_quiet()}, "在安静时间窗"),
        ({"config": _config(bot_reactions_meme_enabled=False)}, "功能开关关"),
        ({"event": SimpleNamespace(message_id="m-1", group_id="", sender_id="")}, "判不出目标"),
    ],
)
def test_p3_hard_gates_all_required(kwargs, why, install_packs) -> None:
    install_packs(FakeStickerPacks(images=("D:/packs/x.png",)))
    store = RecordingStore()
    send = SendSpy()
    _run_p3(store=store, send=send, **kwargs)
    assert send.count == 0, f"{why}时仍发＝门没执法"
    assert store.calls == []


def test_p3_leg_routes_to_packs_only_and_drops_the_library_store() -> None:
    """P3 腿调门面时必须 ``store=None`` ∧ ``pool_policy=packs_only``（AST 现算）。

    只断「发出去的那张不是吸收池图」不够：真身要钉的是**根本没去问吸收池**。
    """
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    leg = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.AsyncFunctionDef) and item.name == "_maybe_send_reaction_meme"
    )
    calls = [
        item
        for item in ast.walk(leg)
        if isinstance(item, ast.Call)
        and (
            (isinstance(item.func, ast.Name) and item.func.id == "select_sticker_for_turn")
            # 现网形：门面作为**可调用对象**交给 `asyncio.to_thread`（不是直接调用）。
            # 判据不缩面——两种形都认，认不出就红，而不是默默数到零。
            or any(
                isinstance(arg, ast.Name) and arg.id == "select_sticker_for_turn"
                for arg in item.args
            )
        )
    ]
    assert calls, "P3 腿已不调门面——本锁前提变了，改判据别删锁"
    for call in calls:
        facade_is_direct_call = (
            isinstance(call.func, ast.Name) and call.func.id == "select_sticker_for_turn"
        )
        positional = call.args if facade_is_direct_call else call.args[1:]
        assert positional and isinstance(positional[0], ast.Constant), (
            "第一实参要显式传 None"
        )
        assert positional[0].value is None, (
            "还在把 meme_library_store 递给门面＝回退通道没关死"
        )
        keywords = {k.arg: k for k in call.keywords}
        assert "pool_policy" in keywords, "没钉 packs_only ⇒ 吸收池随时能溜回来"
        assert "PACKS_ONLY" in ast.unparse(keywords["pool_policy"].value)


def test_p3_signature_asks_for_the_snapshot() -> None:
    """根装配的 P3 腿必须**收**快照查询口，且调用点真的传（漏传＝绕开门）。"""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    leg = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.AsyncFunctionDef) and item.name == "_maybe_send_reaction_meme"
    )
    assert any(arg.arg == "feature_enabled" for arg in leg.args.kwonlyargs)
    calls = [
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == "_maybe_send_reaction_meme"
    ]
    assert calls, "P3 腿在生产面已无人调用"
    assert all(
        any(k.arg == "feature_enabled" for k in call.keywords) for call in calls
    ), "调用点漏传 feature_enabled ⇒ 特性门被绕开"


# ---------------- P3 腿「缺属性＝fail-closed」锁（席位 T23，2026-10-01）----
# 开关真身 config.py 缺省 False（09-28 实弹后下调），而本腿入口门（:5368）与
# knobs.enabled（:5407）两枚 getattr 兜底长期写 True ⇒ 交来的对象**没有这枚属性**
# （None / 鸭子桩 / 属性缺失）时这条主动外发腿静默放行，与本波 S2/S3 四条腿
# （:5557/:5600/:5694/:5717，兜底已 False）及在册口径「没给＝按不通过算」反向。
# 既有参数化锁只覆盖「属性在场且 False」（本文件 :519/:951/:1319），缺属性态
# 此前无锁 ⇒ 本格补两枚：行为腿 + AST 逐枚腿。
def test_p3_missing_meme_switch_is_fail_closed(install_packs) -> None:
    """传入对象没有 `bot_reactions_meme_enabled` 这枚属性 ⇒ 零发送（主动外发腿）。

    控制腿先跑一遍「属性在场且 True ⇒ 照发」，证明本腿不是空跑出来的绿。
    """
    install_packs(FakeStickerPacks(images=("D:/packs/x.png",)))
    control = _config()  # 属性在场且 True
    send_control = SendSpy()
    _run_p3(store=RecordingStore(), send=send_control, config=control)
    assert send_control.count == 1, (
        "控制腿没发 ⇒ 本腿从一开始就是哑的，下面那句断言只是空跑"
    )
    duck = _config()
    delattr(duck, "bot_reactions_meme_enabled")  # 只剩「没有这枚字段」一个差异
    assert not hasattr(duck, "bot_reactions_meme_enabled")
    send = SendSpy()
    _run_p3(store=RecordingStore(), send=send, config=duck)
    assert send.count == 0, "属性缺失⇒主动外发腿静默放行＝fail-open，兜底必须 False"


def test_p3_meme_switch_getattr_defaults_are_fail_closed() -> None:
    """AST 逐枚锁：本腿里该开关**每一枚** getattr 字面兜底都必须是 False。

    行为锁判不中两枚读点的**各自**归属：:5368 入口先 return ⇒ 单翻 :5407 回 True
    时上面那枚仍绿；两枚**一起**翻回 True 它才红。本枚按字面量逐枚数，
    任意一枚翻回 True 即红——「注毒两腿」各自的牙在这里。
    """
    fn = _fn_node("_maybe_send_reaction_meme")
    defaults = [
        node.args[2]
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 3
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "bot_reactions_meme_enabled"
    ]
    assert len(defaults) >= 2, (
        f"本腿对开关的带兜底读点少于 2 枚＝读点被搬走，改判据别删锁：{len(defaults)}"
    )
    for node in defaults:
        assert isinstance(node, ast.Constant) and node.value is False, (
            "主动外发腿的兜底 True＝「忘了传」隐式档，翻回 False：" + ast.unparse(node)
        )


# ------------------------------------------------- 6. 戳一戳 meme 臂同规则
def _call_pick_poke_meme(store: Any, config: Any, **kwargs: Any) -> Any:
    picker = _nested("_pick_poke_meme")
    picker.__globals__.update(
        {
            "_mood_valence": lambda _config: 0.0,
            "_poke_affinity_snapshot": lambda _config, _sender: None,
            # 人格分册之后臂里要现取册名。不注入＝臂内 NameError 被外层 `except
            # Exception` 静吃 ⇒ 表现是「挑不出」（None），而不是报错——本波实踩：
            # 静吃的 NameError 会让「腿哑了」看起来像「池子空了」。
            "_persona_album_names": lambda _config: ("守岸人", "shorekeeper"),
        }
    )
    return picker(store, config, **kwargs)


def test_poke_meme_arm_uses_pack(install_packs) -> None:
    install_packs(FakeStickerPacks(images=("D:/packs/poke.png",)))
    store = RecordingStore()
    path = _call_pick_poke_meme(
        store,
        _config(),
        session_key="group_1_2",
        sender_id="u-1",
        group_id="1",
        feature_enabled=lambda _node: True,
    )
    assert path and str(path).endswith("poke.png")
    assert store.calls == []
    text, image = resolve_poke_reply("meme", fixed_text="嗯？", meme_path=path)
    assert image and not text


def test_poke_meme_arm_empty_pack_falls_back_to_fixed_text(install_packs) -> None:
    install_packs(FakeStickerPacks())
    store = RecordingStore()
    path = _call_pick_poke_meme(
        store,
        _config(),
        session_key="group_1_2",
        sender_id="u-1",
        group_id="1",
        feature_enabled=lambda _node: True,
    )
    assert path is None
    assert store.calls == [], "戳一戳也不许回退吸收池"
    text, image = resolve_poke_reply("meme", fixed_text="嗯？", meme_path=path)
    assert (text, image) == ("嗯？", None), "挑不出 ⇒ 回固定话术，不端图"


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"feature_enabled": None}, id="没给快照口"),
        pytest.param({"feature_enabled": lambda _node: False}, id="特性门关"),
        pytest.param({}, id="完全漏传"),
    ],
)
def test_poke_meme_arm_needs_the_feature_gate(kwargs, install_packs) -> None:
    install_packs(FakeStickerPacks(images=("D:/packs/poke.png",)))
    assert (
        _call_pick_poke_meme(
            RecordingStore(),
            _config(),
            session_key="s",
            sender_id="u-1",
            group_id="1",
            **kwargs,
        )
        is None
    )


def test_poke_meme_arm_respects_blocked_and_quiet_hours(install_packs) -> None:
    install_packs(FakeStickerPacks(images=("D:/packs/poke.png",)))
    assert (
        _call_pick_poke_meme(
            RecordingStore(),
            _config(bot_blocked_user_ids=["u-1"]),
            session_key="s",
            sender_id="u-1",
            group_id="1",
            feature_enabled=lambda _node: True,
        )
        is None
    )
    assert (
        _call_pick_poke_meme(
            RecordingStore(),
            _always_quiet(),
            session_key="s",
            sender_id="u-1",
            group_id="1",
            feature_enabled=lambda _node: True,
        )
        is None
    )


#: 「把可调用对象连同参数交给线程池跑」的包装口（主动腿都不许阻塞事件循环）。
_THREAD_DISPATCH_FUNCS = ("to_thread", "run_in_executor")


def _poke_meme_wire_sites(tree: Any) -> list[Any]:
    """抠出根装配里**真在调** ``_pick_poke_meme`` 的那几处。

    两种写法都是「接线在」，只认直呼会把现役腿读成已无人调用：
      ① ``_pick_poke_meme(store, config, ...)``
      ② ``asyncio.to_thread(_pick_poke_meme, store, config, ...)``——根装配用的就是
      这形（挑图要扫盘，不能在事件循环里跑）。判据不变：被交出去的那一枚必须带齐
      下面断言的关键字，包装形只是换个调用口、不是少传参数的免罪符。
    """
    sites: list[Any] = []
    for item in ast.walk(tree):
        if not isinstance(item, ast.Call):
            continue
        if isinstance(item.func, ast.Name) and item.func.id == "_pick_poke_meme":
            sites.append(item)
            continue
        wrapped = getattr(item.func, "attr", "") if isinstance(item.func, ast.Attribute) else ""
        first = item.args[0] if item.args else None
        if wrapped in _THREAD_DISPATCH_FUNCS and isinstance(first, ast.Name) \
                and first.id == "_pick_poke_meme":
            sites.append(item)
    return sites


def test_poke_call_site_passes_snapshot_and_group() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    calls = _poke_meme_wire_sites(tree)
    assert calls, "戳一戳 meme 臂已无人调用"
    for call in calls:
        keywords = {k.arg for k in call.keywords}
        assert {"feature_enabled", "group_id"} <= keywords, keywords


def test_poke_meme_library_store_is_no_longer_reachable_from_the_arm() -> None:
    """臂上 ``pool_policy`` 必须钉成 packs_only（同 P3：只断结果不断通路不够）。"""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    arm = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == "_pick_poke_meme"
    )
    calls = [
        item
        for item in ast.walk(arm)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == "select_sticker_for_turn"
    ]
    assert calls, "戳一戳臂已不调门面——本锁前提变了，改判据别删锁"
    for call in calls:
        keywords = {k.arg: k for k in call.keywords}
        assert "pool_policy" in keywords
        assert "PACKS_ONLY" in ast.unparse(keywords["pool_policy"].value)


# ----------------------------------------------------------- 审计轨自身
def test_audit_trail_is_keyed_by_session_and_ignores_blank_keys() -> None:
    sticker_send_routing.remember_pool("s-1", PACKS)
    sticker_send_routing.remember_pool("s-2", LIBRARY)
    sticker_send_routing.remember_pool("   ", PACKS)
    assert sticker_send_routing.last_pool_for("s-1") == PACKS
    assert sticker_send_routing.last_pool_for("s-2") == LIBRARY
    assert sticker_send_routing.last_pool_for("never-seen") == NONE_POOL
    assert sticker_send_routing.last_pool_for("") == NONE_POOL


def test_audit_trail_is_bounded() -> None:
    cap = sticker_send_routing._MAX_TRACKED_SESSIONS
    for index in range(cap + 50):
        sticker_send_routing.remember_pool(f"s{index}", PACKS)
    assert len(sticker_send_routing._LAST_POOL) <= cap
    # 最旧的键先被挤出去，最新一批必须还在（有界≠清空）。
    assert sticker_send_routing.last_pool_for("s0") == NONE_POOL
    assert sticker_send_routing.last_pool_for(f"s{cap + 49}") == PACKS


def test_audit_tag_shape_is_stable() -> None:
    assert sticker_send_routing.pool_audit_tag(PACKS) == "sticker_pool:sticker_packs"
    assert sticker_send_routing.pool_audit_tag("") == f"sticker_pool:{NONE_POOL}"


def test_policy_names_are_the_two_documented_states() -> None:
    assert sticker_send_routing.POOL_POLICIES == (PACKS_ONLY, PACKS_THEN_LIBRARY)


# ============================ S2 案二：回执同消息并图（席位 W4R，2026-09-30）====
#
# 钉六件事，全部离线：
#   ① 钩子成功 ⇒ 主成功回执带 `images` ∧ `kind="mixed"` ∧ `sticker_same_message`，
#      且 P3 腿**不再另发第二条**（互斥标生效）；
#   ② 钩子抛 ⇒ 退回纯文字、腿照旧发单图、对话零崩；
#   ③ 任一硬门关 ⇒ 一张都不附（与腿同序同参，没有第二套判据口）；
#   ④ 私聊 ⇒ 钩子一次都不成立（#35 红线口径；私聊那条腿行为与改前逐字节一致）；
#   ⑤ 日额度仍是**同一本**：并图 + 腿跑完，只 +1 不 +2；
#   ⑥ AST 锁：注入点在 chat.py 的**主成功回执**，且全树没有第二本额度账符号。

HOOK_NAME = "_sticker_attach_for_reply"


def _hook_globals(
    *,
    config: Any,
    accounts: dict[str, Any],
    store: Any = None,
    sad: bool = False,
) -> dict[str, Any]:
    """钩子那份 globals：与腿共用 `accounts`（同一本日额 / 同一枚门 / 同一张互斥标）。"""
    return {
        **_p3_globals(store=store, send=SendSpy(), accounts=accounts),
        "_is_sad_reaction_message": lambda _text: sad,
        "config": config,
        "runtime_settings": None,
        "_config_with_runtime_overrides": lambda pconfig, _settings: pconfig,
    }


def _real_hook(
    *,
    config: Any = None,
    accounts: dict[str, Any] | None = None,
    feature_enabled: Any = lambda _node: True,
    sad: bool = False,
) -> Any:
    """把根装配里的**真实钩子**包成 chat.py 见到的形参注入面（生产同款 lambda）。"""
    hook = _nested(HOOK_NAME)
    hook.__globals__.update(
        _hook_globals(
            config=config if config is not None else _config(),
            accounts=accounts if accounts is not None else _fresh_accounts(),
            sad=sad,
        )
    )

    def _wrapper(**kwargs: Any) -> Any:
        return hook(feature_enabled=feature_enabled, **kwargs)

    return _wrapper


def _call_hook(
    *,
    config: Any = None,
    accounts: dict[str, Any] | None = None,
    feature_enabled: Any = lambda _node: True,
    text: str = "今天一起拿了冠军！",
    reply_text: str = "太好了，恭喜你们。",
    session_key: str = "group_111_u_1",
    group_id: str = "111",
    sender_id: str = "u-1",
    message_id: str = "m-1",
    sad: bool = False,
) -> Any:
    return _real_hook(
        config=config, accounts=accounts, feature_enabled=feature_enabled, sad=sad
    )(
        text=text,
        reply_text=reply_text,
        session_key=session_key,
        group_id=group_id,
        sender_id=sender_id,
        message_id=message_id,
    )


class OkProvider:
    """本轮成功的 LLM 替身：正文字字固定，好让附图断言只可能来自钩子那一路。"""

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        return LLMReply(text="太好了，恭喜你们。", provider="fake", model="m")


def _chat_message(*, group: bool, message_id: str = "m-1") -> IncomingMessage:
    if group:
        return IncomingMessage(
            platform="qq", adapter="onebot", bot_id="bot-1",
            session_id="group_111_u_1", session_type=SessionType.GROUP,
            sender_id="u-1", group_id="111", message_id=message_id,
            plain_text="今天一起拿了冠军！",
        )
    return IncomingMessage(
        platform="qq", adapter="onebot", bot_id="bot-1",
        session_id="private_u_1", session_type=SessionType.PRIVATE,
        sender_id="u-1", message_id=message_id,
        plain_text="今天一起拿了冠军！",
    )


def _chat_result(message: IncomingMessage, **options: Any) -> Any:
    decision = BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=message.session_type,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )
    context = ContextBundle(
        request_id=message.request_id,
        persona=PersonaProfile(
            profile_id="shorekeeper", version="1",
            display_name="守岸人", identity="守岸人",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id=message.request_id),
        conversation_history=ConversationHistoryResult(request_id=message.request_id),
        knowledge_results=RetrievalResult(request_id=message.request_id),
        current_message=message.plain_text,
        sender_id=message.sender_id,
        session_id=message.session_id,
    )
    return build_chat_result(
        message, decision, context, llm_provider=OkProvider(), **options
    )


def test_attach_parts_normalizer_accepts_only_two_shapes() -> None:
    assert _sticker_attach_parts(("D:/packs/a.png", ["sticker_pack"])) == (
        "D:/packs/a.png", ["sticker_pack"])
    assert _sticker_attach_parts("D:/packs/a.png") == ("D:/packs/a.png", [])
    for junk in (None, "", "   ", 7, ("", ["x"]), ()):
        assert _sticker_attach_parts(junk)[0] == "", f"{junk!r} 不该被当成一张图"


def test_hook_success_attaches_image_and_sends_no_second_message(install_packs) -> None:
    """① 真钩子 + 真 chat 回执：图并进正文，且腿查标跳过（**绝不双发**）。"""
    install_packs(FakeStickerPacks(images=("D:/packs/红猪/ok.png",)))
    accounts = _fresh_accounts()
    result = _chat_result(
        _chat_message(group=True), sticker_attach_hook=_real_hook(accounts=accounts)
    )
    assert result.kind == "mixed", "并图成功却还报 text＝契约没接住"
    assert len(result.images) == 1 and str(result.images[0]["file"]).endswith("ok.png")
    assert "sticker_same_message" in result.audit_tags
    assert "sticker_pack" in result.audit_tags and "reaction_meme" in result.audit_tags
    assert f"sticker_pool:{PACKS}" in result.audit_tags, "池子形态标丢了＝审计断线"
    assert result.body == "太好了，恭喜你们。" or "恭喜" in result.body
    send = SendSpy()
    _run_p3(store=RecordingStore(), send=send, accounts=accounts)
    assert send.count == 0, "已并图还另发一条空文本图消息＝双发"
    assert "meme:m-1" in accounts["merged"]


def test_hook_failure_falls_back_to_text_and_leg_still_sends(install_packs) -> None:
    """② 钩子抛 ⇒ 纯文字照发、腿照旧补单图、对话零崩（fail-open 回旧行为）。"""
    install_packs(FakeStickerPacks(images=("D:/packs/红猪/ok.png",)))

    def _boom(**_kwargs: Any) -> None:
        raise RuntimeError("hook exploded")

    result = _chat_result(_chat_message(group=True), sticker_attach_hook=_boom)
    assert result.kind == "text" and result.images == []
    assert "sticker_same_message" not in result.audit_tags
    assert result.body == "太好了，恭喜你们。", "贴纸坏了不许把正文一起带走"

    send = SendSpy()
    _run_p3(store=RecordingStore(), send=send)
    assert send.count == 1, "钩子没成 ⇒ 腿必须照旧补发（不许让贴纸凭空消失）"

    # 钩子内部炸（门面抛）也同口径：交回 None、零异常外泄。
    install_packs(FakeStickerPacks(images=("D:/packs/红猪/ok.png",), boom=True))
    assert _call_hook() is None


@pytest.mark.parametrize(
    "kwargs, why",
    [
        ({"feature_enabled": None}, "没给快照查询口"),
        ({"feature_enabled": lambda _node: False}, "特性门未开"),
        ({"config": _config(bot_blocked_user_ids=["u-1"])}, "在 blocked 名单"),
        ({"config": _always_quiet()}, "在安静时间窗"),
        ({"config": _config(bot_reactions_meme_enabled=False)}, "功能开关关"),
        ({"text": "我妈走了", "reply_text": "我听着呢。", "sad": True}, "C1 悲伤门"),
    ],
)
def test_hook_attaches_nothing_when_any_hard_gate_is_closed(kwargs, why, install_packs) -> None:
    """③ 门链一条不过 ⇒ 一张都不附（与 P3 腿同一批门、同一个顺序）。"""
    install_packs(FakeStickerPacks(images=("D:/packs/x.png",)))
    accounts = _fresh_accounts()
    assert _call_hook(accounts=accounts, **kwargs) is None, f"{why}时仍附图＝门没执法"
    assert accounts["merged"] == {}, f"{why}时仍登记互斥标＝贴纸会凭空消失"
    assert accounts["daily"] == {}, f"{why}时不许记额度（第二本账的雏形）"
    # 钩子拒了 ⇒ 腿那条路一切照旧（同一枚门对象、同一本账，钩子没把它吃掉）。
    send = SendSpy()
    _run_p3(store=RecordingStore(), send=send, accounts=accounts)
    assert send.count == 1, f"{why}时钩子拒了，腿也不该被连坐"


def test_hook_never_attaches_in_private_chat(install_packs) -> None:
    """④ 私聊：钩子一次都不成立（#35 红线口径，私聊路径与改前逐字节一致）。"""
    install_packs(FakeStickerPacks(images=("D:/packs/x.png",)))
    merged = _fresh_accounts()
    result = _chat_result(
        _chat_message(group=False),
        sticker_attach_hook=_real_hook(accounts=merged),
    )
    assert result.kind == "text" and result.images == []
    assert merged["merged"] == {} and merged["daily"] == {}, "私聊不许记额度/互斥账"
    # 会话键才是判定口：带群号但键非群形，同样不附。
    assert _call_hook(session_key="private_u_1", group_id="111") is None
    assert _call_hook(group_id="") is None


def test_hook_and_leg_share_one_daily_account(install_packs) -> None:
    """⑤ 日额度只有**一本**：并图 + 腿都跑完，读数只 +1。"""
    install_packs(FakeStickerPacks(images=("D:/packs/one.png", "D:/packs/two.png")))
    accounts = _fresh_accounts()
    attached = _call_hook(accounts=accounts)
    assert attached and str(attached[0]).endswith("one.png")
    assert accounts["daily"]["group_111_u_1"][1] == 1, accounts["daily"]
    send = SendSpy()
    _run_p3(store=RecordingStore(), send=send, accounts=accounts)
    assert send.count == 0
    assert accounts["daily"]["group_111_u_1"][1] == 1, (
        f"并图后再走腿＝第二本账/双计：{accounts['daily']}")


def test_hook_passes_persona_albums_to_the_facade(install_packs) -> None:
    """选图必须穿现役人格册名（缺册＝诚实缺席），并图这一路不许例外。"""
    packs = install_packs(FakeStickerPacks(images=("D:/packs/守岸人/x.png",)))
    assert _call_hook() is not None
    assert packs.pick_calls and packs.pick_calls[0]["persona_names"] == (
        "守岸人", "shorekeeper")
    assert packs.pick_calls[0]["prefer_tags"] is not None, "语境标签面没穿＝判据断线"
    assert isinstance(packs.pick_calls[0]["prefer_tags"], tuple)
    assert packs.pick_calls[0]["locked_subdirs"] is not None, "S4 私藏锁没穿＝越档可发"


def _leg_ast_and_call_nodes() -> tuple[Any, ...]:
    return tuple(ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8-sig"))))


def test_attach_injection_site_is_the_main_success_receipt() -> None:
    """⑥ AST 锁：钩子只可能挂在 chat.py 的**主成功回执**那一个 return 上。"""
    tree = ast.parse(CHAT_SOURCE.read_text(encoding="utf-8-sig"))
    builder = next(
        item for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == "build_chat_result"
    )
    pops = [
        item for item in ast.walk(builder)
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
        and item.func.attr == "pop"
        and item.args and getattr(item.args[0], "value", None) == "sticker_attach_hook"
    ]
    assert pops, "chat.py 不再消费 sticker_attach_hook＝注入线断了，改判据别删锁"
    returns = [
        item for item in ast.walk(builder)
        if isinstance(item, ast.Return) and isinstance(item.value, ast.Call)
        and getattr(item.value.func, "id", "") == "CapabilityResult"
    ]
    main = [
        call for call in (r.value for r in returns)
        if any(
            k.arg == "capability_id" and "decision.capability_id" in ast.unparse(k.value)
            for k in call.keywords
        )
    ]
    assert len(main) == 1, f"主成功回执应当唯一，实得 {len(main)}"
    keywords = {k.arg for k in main[0].keywords}
    assert {"kind", "images", "audit_tags"} <= keywords, keywords
    # 附图判定必须**早于**这个 return（否则回执永远拿不到图）。
    hook_call = next(
        item for item in ast.walk(builder)
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
        and item.func.id == "sticker_attach_hook"
    )
    assert hook_call.lineno < main[0].lineno
    source_text = CHAT_SOURCE.read_text(encoding="utf-8-sig")
    assert '"sticker_same_message"' in source_text
    assert "sticker_attach_hook=" in SOURCE.read_text(encoding="utf-8-sig"), (
        "根装配没把钩子交出去＝S2 只在测试里活着"
    )


def test_no_second_daily_or_gate_account_appeared() -> None:
    """⑥b 全树只有一本日额度账、一枚 P3 专用门：钩子必须复用它们。"""
    nodes = _leg_ast_and_call_nodes()
    assigned: set[str] = set()
    for item in nodes:
        targets: list[Any] = []
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            targets = [item.target]
        elif isinstance(item, ast.Assign):
            targets = [t for t in item.targets if isinstance(t, ast.Name)]
        for target in targets:
            if "reaction_meme_daily" in target.id:
                assigned.add(target.id)
    assert assigned == {"_reaction_meme_daily"}, f"冒出第二本日额账：{sorted(assigned)}"
    bound_gate_names = {
        target.id
        for item in nodes
        for target in (
            [item.target]
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            else [t for t in getattr(item, "targets", []) if isinstance(t, ast.Name)]
        )
        if target.id == "_REACTION_MEME_GATE"
    }
    assert bound_gate_names == {"_REACTION_MEME_GATE"}, (
        "P3 那枚五层门被另绑了一份＝第二个冷却/滑窗账"
    )
    consumed = {
        item.id for item in nodes
        if isinstance(item, ast.Name) and item.id in {
            "_reaction_meme_daily", "_REACTION_MEME_GATE", "_reaction_meme_merged"
        }
    }
    assert consumed == {
        "_reaction_meme_daily", "_REACTION_MEME_GATE", "_reaction_meme_merged"
    }, consumed
    for fn_name in ("_maybe_send_reaction_meme", HOOK_NAME):
        fn = next(
            item for item in nodes
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == fn_name
        )
        used = {node.id for node in ast.walk(fn) if isinstance(node, ast.Name)}
        assert {"_reaction_meme_daily", "_REACTION_MEME_GATE"} <= used, (
            f"{fn_name} 不再吃同一本账/同一枚门＝绕门或另立账"
        )


def test_leg_skips_when_reply_already_carried_the_sticker(install_packs) -> None:
    """腿入口查标：本轮已并图 ⇒ 直接 return，连门账都不再动。"""
    install_packs(FakeStickerPacks(images=("D:/packs/x.png",)))
    accounts = _fresh_accounts()
    accounts["merged"]["meme:m-1"] = "D:/packs/x.png"
    send = SendSpy()
    _run_p3(store=RecordingStore(), send=send, accounts=accounts)
    assert send.count == 0
    assert accounts["daily"] == {}, "跳过的一轮不该再记一次日额度"


# ================= S3 face 回应联动补发（席位 W7S，2026-09-30）=================
#
# 钉七件事，全部离线：
#   ① 全门开 ∧ 池子有货 ⇒ 补发 1 张，audit 含 `reaction_emoji_sticker` ∧
#      `sticker_pack` ∧ `sticker_pool:*`，且**永不**碰吸收池；
#   ② 任一硬门关（特性关 / 名单 / 安静窗 / 日帽满 / 无群号 / 开关关 / 池子空）
#      ⇒ 零发送、零额度记账（被拒的那一轮不许吃掉额度＝poke 波立的判据）；
#   ③ 私聊绝不发（#35 红线锁形，参照 `tests/test_reactions.py
#      ::test_private_session_never_calls_set_msg_emoji_like`：私聊在派发前拒掉，
#      连反查都不发——零 API 调用，不是「查完再拒」）；
#   ④ 取不到可靠正文（反查失败 / 那条不是我的消息 / 正文空 / 反查抛）⇒ 不发 +
#      debug 痕（错配比不贴更糟，P3 波判据原样适用）；
#   ⑤ AST 锁：新腿不新建日额度 dict、不实例化第二枚门、字面配置键集合与 P3 腿
#      **逐枚相等**（D3「零新字段」）、不写 S2 的并图互斥标、不直呼 `get_msg`；
#   ⑥ 与 P3 互不压制：同一 message_id 两腿各自记账（各 +1，不重复 +2），S2 并图标
#      在场时 P3 让路而 S3 照发（S3 不读那枚标，也没资格压制别人）；
#   ⑦ handler 接线：识别段（归一 + 双写）行为与改前一致；
#      `bot.plugin.chat.reactions.meme` 关 ⇒ 一次都不派发；补发腿抛 ⇒ handler 吞掉。

S3_LEG = "_maybe_send_sticker_for_emoji_like"
S3_RESOLVER = "_reaction_target_message_text"
S3_HANDLER = "_handle_msg_emoji_like_notice"
S3_TAG = "reaction_emoji_sticker"
# 反查喉 `_make_onebot_reply_lookup` 按 OneBot 协议把 message_id 收成 int
# （`getter(message_id=int(message_id))`，真身未随本波改动）——非数字 id 在那条路上
# 结构性取不到正文。夹具必须用**可 int 化**的数字 id，否则「全门开就该发」几枚锁
# 是空跑出来的绿（注毒见该枚：把此常量改回非数字 ⇒ 三枚红）。
S3_MESSAGE_ID = "10086"
BOT_SELF_ID = "1110001"
REPLIED_TEXT = "太好了，恭喜你们。"


def _fn_node(name: str) -> ast.AST:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    return next(
        item
        for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )


def _call_keyword(fn: ast.AST, callee: str, keyword: str) -> ast.expr:
    """取某个调用的关键字实参节点（取不到就红——不许「数到零也算通过」的空档）。"""
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == callee
        ):
            for item in node.keywords:
                if item.arg == keyword:
                    return item.value
    raise AssertionError(
        f"{callee}(...) 里没有 {keyword}= ——判据换了地方，改尺别删锁"
    )


def _string_constants(node: ast.AST) -> set[str]:
    return {
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }


class FakeMsgBot:
    """补发腿的假 bot：`get_msg` 反查口 + `self_id`（「那条是我的消息」的协议凭证）。"""

    def __init__(
        self,
        *,
        self_id: str = BOT_SELF_ID,
        payload: Any = "default",
        boom: bool = False,
    ) -> None:
        self.self_id = self_id
        self.payload = _group_message_payload() if payload == "default" else payload
        self.boom = boom
        self.calls: list[Any] = []

    async def get_msg(self, *, message_id: Any) -> Any:
        self.calls.append(message_id)
        if self.boom:
            raise RuntimeError("get_msg exploded")
        return self.payload


def _group_message_payload(
    text: str = REPLIED_TEXT, *, sender_user_id: Any = BOT_SELF_ID
) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    if text:
        segments.append({"type": "text", "data": {"text": text}})
    # 非文本段：本腿要的是「说了什么」这句话，face/图片段不许混进正文。
    segments.append({"type": "face", "data": {"face_id": "66"}})
    return {
        "message": segments,
        "sender": {"user_id": sender_user_id, "nickname": "守岸人"},
    }


def _reaction(**overrides: Any) -> SimpleNamespace:
    """归一后的贴纸回应事件（`normalize_onebot_emoji_like` 的产物形）。"""
    base: dict[str, Any] = {
        "platform": "qq",
        "session_key": "group_111_u_1",
        "user_id": "u-1",
        "message_id": S3_MESSAGE_ID,
        "emoji_id": "66",
        "emoji_text": "「爱心」",
        "count": 1,
        "ts": 0.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _notice_event(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "notice_type": "group_msg_emoji_like",
        "group_id": "111",
        "user_id": "u-1",
        "message_id": S3_MESSAGE_ID,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _s3_text_resolver() -> Any:
    """真身解析器链（连 `get_msg` 归一那段一起抠出来，不在测试里重写第二份判据）。"""
    resolver = _nested(S3_RESOLVER)
    builder = _nested("_make_onebot_reply_lookup")
    builder.__globals__["_onebot_segments_from_message_payload"] = _nested(
        "_onebot_segments_from_message_payload"
    )
    builder.__globals__["asyncio"] = asyncio
    resolver.__globals__["_make_onebot_reply_lookup"] = builder
    resolver.__globals__["logger"] = logging.getLogger("test.sticker_pools")
    resolver.__globals__["asyncio"] = asyncio
    return resolver


def _run_s3(
    *,
    send: SendSpy,
    accounts: dict[str, Any] | None = None,
    config: Any = None,
    feature_enabled: Any = lambda _node: True,
    reaction: Any = None,
    event: Any = None,
    bot: Any = None,
    store: Any = None,
    sad_words: tuple[str, ...] = (),
) -> dict[str, Any]:
    """跑根装配里那条**真实补发腿**（AST 抠闭包 + 注入同一本账）。"""
    book = accounts if accounts is not None else _fresh_accounts()
    shared = _p3_globals(store=store, send=send, accounts=book)
    shared["_reaction_target_message_text"] = _s3_text_resolver()
    if sad_words:
        shared["_is_sad_reaction_message"] = lambda text: any(
            word in str(text or "") for word in sad_words
        )
    leg = _nested(S3_LEG)
    leg.__globals__.update(shared)
    target_bot = bot if bot is not None else FakeMsgBot()
    asyncio.run(
        leg(
            target_bot,
            event if event is not None else _notice_event(),
            reaction_event=reaction if reaction is not None else _reaction(),
            meme_config=config if config is not None else _config(),
            feature_enabled=feature_enabled,
        )
    )
    return {"accounts": book, "bot": target_bot}


def test_s3_fires_with_all_gates_open_and_pack_stock(install_packs) -> None:
    """① 全门开 ∧ 池子有货 ⇒ 恰好一张，审计三形齐（新标 + 池子 + 形态）。"""
    install_packs(FakeStickerPacks(images=("D:/packs/守岸人/ok.png",)))
    store = RecordingStore()
    send = SendSpy()
    book = _run_s3(store=store, send=send)
    assert send.count == 1, "全门开且有货却不发＝接线断了"
    assert str(send.calls[0]["image"]).endswith("ok.png")
    assert send.calls[0]["image"] != ABSORBED
    assert send.calls[0]["text"] == "", "补发腿只补图，正文是对方早就看到的那句"
    tags = send.calls[0]["audit_tags"]
    assert S3_TAG in tags, f"审计里没有 {S3_TAG}＝这条腿在现网无法被认出来"
    assert "sticker_pack" in tags and "reaction_meme" in tags
    assert f"sticker_pool:{PACKS}" in tags, "池子形态标丢了＝审计断线"
    assert send.calls[0]["capability_id"] == "bot.chat", "capability_id 不许改名"
    assert store.calls == [], "补发腿一条都不许碰吸收池（P3 的红线不因换了触发点而松）"
    assert book["accounts"]["daily"]["group_111_u_1"][1] == 1, book["accounts"]["daily"]
    assert book["accounts"]["merged"] == {}, "本腿不许写 S2 的并图互斥标"
    assert sticker_send_routing.last_pool_for("group_111_u_1") == PACKS


@pytest.mark.parametrize(
    "kwargs, why",
    [
        ({"feature_enabled": None}, "没给快照查询口"),
        ({"feature_enabled": lambda _node: False}, "贴纸池特性门未开"),
        ({"config": _config(bot_blocked_user_ids=["u-1"])}, "在 blocked 名单"),
        ({"config": _always_quiet()}, "在安静时间窗"),
        ({"config": _config(bot_reactions_meme_enabled=False)}, "功能开关关"),
        ({"event": _notice_event(group_id="")}, "事件不带群号"),
        ({"reaction": _reaction(message_id="")}, "被回应消息无 id"),
        ({"reaction": _reaction(user_id="")}, "认不出是谁的回应"),
    ],
)
def test_s3_hard_gates_all_required(kwargs, why, install_packs) -> None:
    """② 任一硬门关 ⇒ 零发送、零记账（同一族门，一条不过就不许出图）。"""
    install_packs(FakeStickerPacks(images=("D:/packs/x.png",)))
    send = SendSpy()
    book = _run_s3(send=send, **kwargs)
    assert send.count == 0, f"{why}时仍发＝门没执法"
    assert book["accounts"]["daily"] == {}, f"{why}时不许记日额度（第二本账的雏形）"
    assert book["accounts"]["merged"] == {}


def test_s3_daily_cap_full_sends_nothing(install_packs) -> None:
    """② 续：日帽满 ⇒ 不发，且**不 +1**（满了还涨＝帽形同虚设）。"""
    install_packs(FakeStickerPacks(images=("D:/packs/x.png",)))
    accounts = _fresh_accounts()
    today = int(time.strftime("%Y%m%d", time.localtime()))
    accounts["daily"]["group_111_u_1"] = (today, 6)
    send = SendSpy()
    _run_s3(send=send, accounts=accounts)
    assert send.count == 0, "日帽满时仍发＝帽没执法"
    assert accounts["daily"]["group_111_u_1"] == (today, 6), accounts["daily"]


def test_s3_empty_pack_sends_nothing_and_never_degrades(install_packs) -> None:
    """② 续：池子空 ⇒ 静默不发，绝不退化成吸收池那张。"""
    install_packs(FakeStickerPacks())
    store = RecordingStore()
    send = SendSpy()
    book = _run_s3(store=store, send=send)
    assert send.count == 0 and store.calls == []
    assert book["accounts"]["daily"] == {}, "挑不出图的一轮不许记额度"
    assert sticker_send_routing.last_pool_for("group_111_u_1") == NONE_POOL


def test_s3_absent_pack_module_sends_nothing() -> None:
    """② 续：`sticker_packs` 件缺席（另一席没落笔的真实世界）⇒ 不发、不炸。"""
    send = SendSpy()
    book = _run_s3(send=send)
    assert send.count == 0
    assert book["accounts"]["daily"] == {}


def test_s3_never_sends_in_private_session(install_packs) -> None:
    """③ 私聊绝不补发（#35 红线锁形）：私聊在派发前拒，连反查都不发。"""
    install_packs(FakeStickerPacks(images=("D:/packs/x.png",)))
    # 私聊键形＝裸 uid（镜像 OneBot `get_session_id`，见 session_keys.build_session_key）
    for private_key in ("9900", "u-1"):
        send = SendSpy()
        bot = FakeMsgBot()
        book = _run_s3(
            send=send,
            bot=bot,
            reaction=_reaction(session_key=private_key),
            event=_notice_event(group_id=""),
        )
        assert send.count == 0, f"私聊键 {private_key} 仍补发＝#35 红线破了"
        assert bot.calls == [], "私聊那条路连 get_msg 都不该发（派发前拒，不是查完再拒）"
        assert book["accounts"]["daily"] == {}, "私聊不许记额度"
    # 会话键才是判定口：带群号但键非群形 ⇒ 同样不发、同样零反查。
    send = SendSpy()
    bot = FakeMsgBot()
    _run_s3(send=send, bot=bot, reaction=_reaction(session_key="private_u_1"))
    assert send.count == 0 and bot.calls == []
    # 反向也钉：群聊键 ∧ 群号在场 ⇒ 反查真的发生（否则上面三条是空跑出来的绿）。
    send_ok = SendSpy()
    bot_ok = FakeMsgBot()
    _run_s3(send=send_ok, bot=bot_ok)
    assert bot_ok.calls == [int(S3_MESSAGE_ID)], "群聊路径没走反查＝③ 的三条断言全是空跑"
    assert send_ok.count == 1


@pytest.mark.parametrize(
    "bot_kwargs, why",
    [
        ({"payload": None}, "反查失败（取不到更深层）"),
        ({"payload": _group_message_payload(sender_user_id="999999")}, "那条不是我的消息"),
        ({"payload": _group_message_payload("")}, "我的消息但没有文本段"),
        ({"payload": {"message": [], "sender": {"user_id": BOT_SELF_ID}}}, "段列表是空的"),
        ({"payload": {"message": None, "sender": None}}, "整个 payload 形状不对"),
        ({"boom": True}, "反查抛异常"),
        ({"self_id": ""}, "认不出 bot 自己是谁"),
    ],
)
def test_s3_without_reliable_text_is_honest_silent(bot_kwargs, why, install_packs, caplog) -> None:
    """④ 取不到可靠正文 ⇒ 诚实不发 + debug 痕（错配比不贴更糟）。"""
    install_packs(FakeStickerPacks(images=("D:/packs/x.png",)))
    send = SendSpy()
    accounts = _fresh_accounts()
    with caplog.at_level(logging.DEBUG, logger="test.sticker_pools"):
        _run_s3(send=send, accounts=accounts, bot=FakeMsgBot(**bot_kwargs))
    assert send.count == 0, f"{why}时仍发＝把「猜一张」当成了兜底"
    assert accounts["daily"] == {}
    assert any(
        "no reliable source text" in record.getMessage() for record in caplog.records
    ), f"{why}时没留痕＝静默失效无法被排查"


def test_s3_sad_gate_covers_both_faces(install_packs) -> None:
    """④ 续：C1 悲伤门在本腿读两面——对方的表情本身、以及我自己那句丧事正文。

    两面都钉，还顺手钉出「先判悲伤、后反查」的次序：对方表情自己就是丧事时，
    连一次 `get_msg` 都不该发（省外呼，也更少碰别人的消息正文）。
    """
    install_packs(FakeStickerPacks(images=("D:/packs/x.png",)))
    send = SendSpy()
    out = _run_s3(send=send, sad_words=("爱心",), reaction=_reaction(emoji_text="「爱心」"))
    assert send.count == 0, "对方的表情命中悲伤词族仍补图＝C1 破了"
    assert out["bot"].calls == [], "悲伤在反查之前就该拒掉"
    assert out["accounts"]["daily"] == {}

    send_two = SendSpy()
    out_two = _run_s3(
        send=send_two,
        sad_words=("走了",),
        bot=FakeMsgBot(payload=_group_message_payload("我妈走了，我陪着她。")),
    )
    assert send_two.count == 0, "我自己那句是丧事场合还配图＝C1 的第二面没执法"
    assert out_two["bot"].calls == [int(S3_MESSAGE_ID)], "第二面要先取到正文才判得动（判据不是空转）"
    assert out_two["accounts"]["daily"] == {}


# ------------------------------------------------------------------- ⑤ AST 锁
def _literal_config_keys(fn: ast.AST) -> set[str]:
    """函数体内按**字面键名**读到的 `bot_*` 配置键（getattr 第二实参是字符串常量）。"""
    keys: set[str] = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and str(node.args[1].value).startswith("bot_")
        ):
            keys.add(str(node.args[1].value))
    return keys


def test_s3_reads_no_new_config_field() -> None:
    """⑤a 零新配置字段（D3）：本腿的字面键集合与 P3 腿**逐枚相等**。"""
    p3_keys = _literal_config_keys(_fn_node("_maybe_send_reaction_meme"))
    leg_keys = _literal_config_keys(_fn_node(S3_LEG))
    assert leg_keys == p3_keys, (
        f"本腿多读/少读字面键＝新增字段会红登记总账：{sorted(leg_keys ^ p3_keys)}")
    assert leg_keys, "一把尺都读不到＝本腿已经绕开门链，改判据别删锁"


def test_s3_opens_no_second_daily_or_gate_account() -> None:
    """⑤b 不起第二本账：不新建日额度 dict、不实例化第二枚门、门与帽都是同一对象。"""
    leg = _fn_node(S3_LEG)
    bound: set[str] = set()
    for node in ast.walk(leg):
        targets: list[ast.expr] = []
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        for target in targets:
            if "reaction_meme" in target.id.lower():
                bound.add(target.id)
    assert bound == set(), f"补发腿里长出了新的账/门绑定：{sorted(bound)}"
    used = {node.id for node in ast.walk(leg) if isinstance(node, ast.Name)}
    assert {"_reaction_meme_daily", "_REACTION_MEME_GATE"} <= used, (
        "本腿不再吃同一本账/同一枚门＝绕门或另立账"
    )
    assert "_reaction_meme_merged" not in used, (
        "本腿读了 S2 的并图互斥标＝会静默压制 P3（简报点名的禁区）"
    )
    assert "_ReactionProactiveGateClass" not in used and "ProactiveGate" not in used, (
        "本腿自己实例化了门＝第二枚冷却/滑窗账"
    )
    assert _call_keyword(leg, "proactive_action_allowed", "gate").id == "_REACTION_MEME_GATE", (
        "gate= 不是那枚共享门"
    )
    assert _call_keyword(leg, "proactive_action_allowed", "prefix").value == "bot_reactions_meme_"
    assert _call_keyword(leg, "proactive_action_allowed", "salt").value == "reaction-meme"
    assert any(
        item.arg == "knobs" for item in _calls_named(leg, "proactive_action_allowed")[0].keywords
    ), "没传 knobs＝退回按 prefix 动态取数（配置登记总账直读尺看不见那把尺）"
    # 帽必须是同一本 dict 的下标读写，不是另起一张表。
    subscripts = {
        node.value.id
        for node in ast.walk(leg)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and "daily" in node.value.id
    }
    assert subscripts == {"_reaction_meme_daily"}, subscripts


def _calls_named(fn: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


def test_s3_message_key_does_not_borrow_the_p3_namespace() -> None:
    """⑤c 去重键各占各的形：本腿 `emoji:`，P3 与钩子仍是 `meme:`（互不占坑才有互不压制）。

    比的是 `proactive_action_allowed(message_key=…)` 那枚 f-string 的**前缀常量**，
    不是整段源码文本——docstring 里提到过 `meme:` 是解释，不是记账。
    """
    assert _fstring_head(
        _call_keyword(_fn_node(S3_LEG), "proactive_action_allowed", "message_key")
    ) == "emoji:"
    for name in ("_maybe_send_reaction_meme", HOOK_NAME):
        key = _call_keyword(_fn_node(name), "proactive_action_allowed", "message_key")
        assert _fstring_head(key) == "meme:", f"{name} 的 message_key 前缀被改＝两腿并成一格"


def _fstring_head(node: ast.expr) -> str:
    """f-string 的首段常量（去重键的命名空间前缀）；不是这个形就红。"""
    assert isinstance(node, ast.JoinedStr) and node.values, ast.dump(node)
    head = node.values[0]
    assert isinstance(head, ast.Constant) and isinstance(head.value, str), ast.unparse(node)
    return str(head.value)


def _attribute_names(node: ast.AST) -> set[str]:
    return {item.attr for item in ast.walk(node) if isinstance(item, ast.Attribute)}


def test_s3_text_source_is_the_single_existing_lookup_throat() -> None:
    """⑤d 取正文只有一个喉：`get_msg` 的既有注入口，本腿与解析器都不直呼协议 API。

    比的是 AST 里的属性名，不是源码文本——两处的 docstring 都在**解释** get_msg，
    文本尺会把解释当成调用（本仓最典型的假绿反过来：假红）。
    """
    resolver = _fn_node(S3_RESOLVER)
    leg = _fn_node(S3_LEG)
    resolver_names = {item.id for item in ast.walk(resolver) if isinstance(item, ast.Name)}
    assert "_make_onebot_reply_lookup" in resolver_names, (
        "反查不再走既有注入口＝开出了第二条取数路（引用链那条腿的同一枚喉被绕过）"
    )
    leg_names = {item.id for item in ast.walk(leg) if isinstance(item, ast.Name)}
    assert S3_RESOLVER in leg_names, "本腿没调用正文解析器＝文本源判定整段是空的"
    for node, label in ((resolver, "解析器"), (leg, "补发腿")):
        attrs = _attribute_names(node)
        for banned in ("get_msg", "call_api", "get_plaintext"):
            assert banned not in attrs, f"{label} 里出现 .{banned}＝第二通路/必炸口"


def test_s3_fires_on_non_numeric_message_id(install_packs) -> None:
    """字符串 id 平台（TG/Discord）不许永久哑火：反查喉只在真是数字时才 int()。

    旧形是 `getter(message_id=int(message_id))`，非数字 id 在 try 之前就被 ValueError
    吞成 None，读数和「反查失败」一模一样＝坏在无人知。控制腿钉数字 id 照发，
    证明这一枚不是靠空跑变绿。
    """
    install_packs(FakeStickerPacks(images=("D:/packs/守岸人/ok.png",)))
    for message_id, label in ((S3_MESSAGE_ID, "数字 id"), ("abc-123", "字符串 id")):
        send = SendSpy()
        accounts = _fresh_accounts()
        book = _run_s3(
            send=send, accounts=accounts, reaction=_reaction(message_id=message_id)
        )
        assert send.count == 1, f"{label} 路没发＝反查喉把 id 形态当失败吞了"
        assert book["accounts"]["daily"], f"{label} 路没记账＝同一本帽没走到"


def test_s3_facade_call_keeps_packs_only_and_no_library_store() -> None:
    """⑤e 选图穿参与 P3 同形：store=None ∧ packs_only ∧ 人格册名 ∧ 池子种子另立。"""
    leg = _fn_node(S3_LEG)
    calls = [
        node
        for node in ast.walk(leg)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "select_sticker_for_turn")
            or any(
                isinstance(arg, ast.Name) and arg.id == "select_sticker_for_turn"
                for arg in node.args
            )
        )
    ]
    assert calls, "本腿已不调门面——选图判据换了地方，改判据别删锁"
    for call in calls:
        direct = isinstance(call.func, ast.Name) and call.func.id == "select_sticker_for_turn"
        positional = call.args if direct else call.args[1:]
        assert positional and isinstance(positional[0], ast.Constant), "第一实参要显式传 None"
        assert positional[0].value is None, "把吸收池递给门面＝回退通道没关死"
        keywords = {k.arg: k for k in call.keywords}
        assert {"pool_policy", "pool_seed", "persona_albums", "turn_text", "reply_text"} <= set(
            keywords
        ), sorted(keywords)
        assert "PACKS_ONLY" in ast.unparse(keywords["pool_policy"].value)
        assert "_persona_album_names" in ast.unparse(keywords["persona_albums"].value)
        seed = keywords["pool_seed"].value
        assert isinstance(seed, ast.JoinedStr) and isinstance(seed.values[0], ast.Constant)
        assert seed.values[0].value == "reaction-emoji:", (
            "池子种子与本腿语义不符＝轮换账串到 P3 那一格"
        )
    used = {node.id for node in ast.walk(leg) if isinstance(node, ast.Name)}
    assert "meme_library_store" not in used, "本腿还留着吸收池的名字＝第二通路预备役"


def test_s3_handler_is_wired_and_recognition_leg_unchanged() -> None:
    """⑤f 接线锁：补发只挂在 notice handler 里，且派发点把快照查询口传了。"""
    handler = _fn_node(S3_HANDLER)
    calls = _calls_named(handler, S3_LEG)
    assert calls, "handler 不再派发补发腿＝S3 整条线断了，改判据别删锁"
    for call in calls:
        keywords = {k.arg for k in call.keywords}
        assert {"reaction_event", "meme_config", "feature_enabled"} <= keywords, keywords
    assert [node for node in ast.walk(handler) if isinstance(node, ast.Try)], (
        "派发点没有 try 兜底＝补发炸了会把 notice 链路一起带走"
    )
    literals = _string_constants(handler)
    assert "bot.plugin.chat.reactions.meme" in literals, (
        "特性门 id 没在派发点判＝本腿绕过了在册开关"
    )
    assert "bot.plugin.chat.reactions.receive" in literals, "识别段自己的门不许丢"
    # 一次 notice 最多一张：派发点在循环**之外**（循环内的话多枚 likes 会各发一张）。
    loop_bodies = [
        node
        for node in ast.walk(handler)
        if isinstance(node, (ast.For, ast.AsyncFor))
    ]
    assert loop_bodies, "handler 的归一循环不见了＝识别段被改写，本锁前提变了"
    for loop in loop_bodies:
        assert _calls_nested(loop, S3_LEG) == [], (
            "补发腿被放进了归一循环里＝一次回应可能补多张"
        )
    # 全树只有一条 notice 派发点（不许长出第二条补发路）。
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    dispatch_sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == S3_LEG
    ]
    assert len(dispatch_sites) == 1, f"补发腿派发点应当唯一，实得 {len(dispatch_sites)}"


def _calls_nested(scope: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(scope)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


# ------------------------------------------------------------- ⑥ 与 P3 互不压制
def test_s3_and_p3_spend_the_same_daily_book(install_packs) -> None:
    """⑥ 同一本账（D3「不起第二本账」）：只钉**账实一致**，不钉「发不发」。

    注毒实测记录（说明为什么这里**不写**「P3 花满 daily_max=1 ⇒ S3 不发」那条看似
    更硬的判据）：把本腿的帽读数改成
    `_reaction_meme_daily.get(session_key + "!s3", ...)`（`__init__.py:5610`）后，
    「P3 先手 + `daily_max=1` ⇒ S3 零发送」实测**仍绿**＝没有牙。原因是两腿共用同
    一枚五层门 `_REACTION_MEME_GATE`，同窗第二发在帽之前就已被
    `proactive_action_allowed` 挡下 ⇒ 「不发」既可来自门也可来自帽，判不出帽。
    帽面交给两枚**有牙**的锁分管：
      ① `test_s3_daily_cap_full_sends_nothing`：手工预填同一本账 ⇒ 上面同一注毒
        实测 RED（poisoned: 1 failed / 恢复后 green）；
      ② `test_s3_opens_no_second_daily_or_gate_account`：AST 面钉本腿读写的是同一
        枚 `_reaction_meme_daily`，且没新立第二本账／第二枚门。
    本枚因此只钉「发了必记账、没发必不记账、两腿都不写 S2 的并图标」。
    """
    install_packs(FakeStickerPacks(images=("D:/packs/one.png", "D:/packs/two.png")))
    accounts = _fresh_accounts()
    p3_send = SendSpy()
    _run_p3(store=RecordingStore(), send=p3_send, accounts=accounts)
    assert p3_send.count == 1
    assert accounts["daily"]["group_111_u_1"][1] == 1, accounts["daily"]
    s3_send = SendSpy()
    _run_s3(send=s3_send, accounts=accounts, store=RecordingStore())
    assert accounts["daily"]["group_111_u_1"][1] == (
        2 if s3_send.count == 1 else 1
    ), f"发了不记账／没发却记账＝账实不符 {accounts['daily']}"
    assert accounts["merged"] == {}, "两腿都不该写 S2 的并图标"


def test_s3_ignores_the_s2_merged_marker(install_packs) -> None:
    """⑥ 续：S2 已并图 ⇒ P3 让路（既有锁形），S3 照发（它没资格读别人的互斥标）。"""
    install_packs(FakeStickerPacks(images=("D:/packs/x.png",)))
    accounts = _fresh_accounts()
    # P3 侧的并图标按它自己那条聊天消息的 id 记（`meme:` 是 P3 的命名空间）。
    accounts["merged"]["meme:m-1"] = "D:/packs/x.png"
    p3_send = SendSpy()
    _run_p3(store=RecordingStore(), send=p3_send, accounts=accounts)
    assert p3_send.count == 0, "并图后 P3 该让路（这条是 S2 已有的行为，不许被本波改掉）"
    s3_send = SendSpy()
    _run_s3(send=s3_send, accounts=accounts, store=RecordingStore())
    assert s3_send.count == 1, "本腿查了别人的互斥标＝静默压制 P3 的同型病"
    # 行为面之外再钉源码面：本腿源码里连 `merged` 这枚账名都不该出现。
    assert "merged" not in ast.unparse(_fn_node(S3_LEG)), "本腿源码出现 merged＝开始读别人的互斥标"
    assert accounts["daily"]["group_111_u_1"][1] == 1, accounts["daily"]


# --------------------------------------------------------------- ⑦ handler 实跑
class RecordingBuffer:
    """`SHARED_REACTION_BUFFER` 替身：只记「识别段有没有照写」。"""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


class RecordingReactionStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record_event(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)


class _FakeSnapshot:
    def __init__(self, states: dict[str, bool]) -> None:
        self._states = dict(states)

    def enabled(self, node: str) -> bool:
        return bool(self._states.get(str(node), False))


class _FakeFeatureGate:
    def __init__(self, states: dict[str, bool]) -> None:
        self._snapshot = _FakeSnapshot(states)

    async def snapshot_async(self) -> _FakeSnapshot:
        return self._snapshot


def _run_handler(
    *,
    states: dict[str, bool] | None = None,
    event: Any = None,
    leg_error: Exception | None = None,
) -> dict[str, Any]:
    from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
        normalize_onebot_emoji_like,
    )

    dispatches: list[dict[str, Any]] = []

    async def _leg(_bot: Any, _event: Any, **kwargs: Any) -> None:
        dispatches.append(kwargs)
        if leg_error is not None:
            raise leg_error

    handler = _nested(S3_HANDLER)
    handler.__globals__.update(
        {
            "product_feature_gate": _FakeFeatureGate(
                states
                if states is not None
                else {
                    "bot.plugin.chat.reactions.receive": True,
                    "bot.plugin.chat.reactions.meme": True,
                    "bot.plugin.sticker_packs": True,
                }
            ),
            "_normalize_onebot_emoji_like": normalize_onebot_emoji_like,
            "_REACTION_BUFFER": RecordingBuffer(),
            "_reaction_store": RecordingReactionStore(),
            "_maybe_send_sticker_for_emoji_like": _leg,
            "_config_with_runtime_overrides": lambda pconfig, _settings: pconfig,
            "config": _config(),
            "runtime_settings": None,
            "logger": logging.getLogger("test.sticker_pools"),
            "asyncio": asyncio,
            "time": time,
        }
    )
    buffer = handler.__globals__["_REACTION_BUFFER"]
    store = handler.__globals__["_reaction_store"]
    asyncio.run(handler(SimpleNamespace(self_id=BOT_SELF_ID), event or _notice_event(
        likes=[{"emoji_id": "66", "count": 1}]
    )))
    return {
        "buffer": buffer,
        "store": store,
        "dispatches": dispatches,
        "handler": handler,
    }


def test_handler_records_recognition_then_dispatches_once(install_packs) -> None:
    """⑦ 识别段照写、补发段恰好一次派发（多枚 likes 也只一张），参数齐。"""
    event = _notice_event(
        likes=[{"emoji_id": "66", "count": 1}, {"emoji_id": "1", "count": 2}]
    )
    out = _run_handler(event=event)
    assert len(out["buffer"].events) == 2, "识别段被本波改坏了（缓冲少写）"
    assert len(out["store"].rows) == 2, "识别段被本波改坏了（落库少写）"
    assert out["store"].rows[0]["message_id"] == S3_MESSAGE_ID
    assert len(out["dispatches"]) == 1, "一次 notice 补两张＝刷屏，且没交给五层门去重"
    kwargs = out["dispatches"][0]
    assert kwargs["reaction_event"].emoji_id == "66", "应当取第一条回应代表这次 notice"
    # 键形按中央构造器现算（手写串会随 `build_session_key` 改口径而漂移）。
    from plugins.bot_unified_runtime.domains.core.session_keys import build_session_key
    assert kwargs["reaction_event"].session_key == build_session_key("111", "u-1")
    assert callable(kwargs["feature_enabled"]), "派发点没把快照查询口交出去＝特性门被绕开"
    assert kwargs["meme_config"] is not None


def test_handler_stays_silent_when_meme_feature_is_off() -> None:
    """⑦ 续：`bot.plugin.chat.reactions.meme` 关 ⇒ 识别照做、补发一次都不派发。"""
    out = _run_handler(states={"bot.plugin.chat.reactions.receive": True})
    assert out["dispatches"] == []
    assert len(out["buffer"].events) == 1, "特性门关只该关掉补发，不该关掉识别"
    assert len(out["store"].rows) == 1


def test_handler_stays_silent_when_receive_feature_is_off() -> None:
    """⑦ 续：`…reactions.receive` 关 ⇒ 整段都不动（识别与补发同一条 handler 的门）。"""
    out = _run_handler(states={})
    assert out["dispatches"] == []
    assert out["buffer"].events == [] and out["store"].rows == []


def test_handler_swallows_leg_failure(caplog) -> None:
    """⑦ 续：补发腿抛 ⇒ handler 吞掉并留痕，识别段已写的不回滚、异常不外泄。"""
    with caplog.at_level(logging.DEBUG, logger="test.sticker_pools"):
        out = _run_handler(leg_error=RuntimeError("leg exploded"))
    assert len(out["buffer"].events) == 1, "补发炸了不许把识别段一起带走"
    assert len(out["dispatches"]) == 1
    assert any("dispatch failed" in r.getMessage() for r in caplog.records), (
        "吞异常还不留痕＝静默失效"
    )


def test_handler_recognition_exception_does_not_dispatch() -> None:
    """⑦ 续：归一段自己抛（协议形态没见过）⇒ 不派发，异常也不外泄。"""

    class _Boom:
        notice_type = "group_msg_emoji_like"
        group_id = "111"
        user_id = "u-1"

        @property
        def message_id(self) -> Any:  # 归一取 id 时炸
            raise ValueError("no message id")

        likes: ClassVar[list[dict[str, Any]]] = []

    out = _run_handler(event=_Boom())
    assert out["dispatches"] == [], "归一失败还继续派发＝拿着不存在的语境往外发图"



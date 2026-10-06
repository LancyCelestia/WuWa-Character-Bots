"""描写档取键口的 **platform 接线判据**（席 na-land，2026-10-04 深夜；接席 na-keyfix §7 的点名待办）。

席 na-keyfix 把唯一的取键口 `content_route._narration_person_key` 换成
`session_keys.person_scope_key(平台域, 用户号)`，平台域只归一自
`policy/roles.platform_domain_of`，**拿不到平台事实就 fail-closed**（不反解会话键）。
但那枚 `platform` 参数当时**没有任何生产调用方交值** ⇒ 描写钉今天只落在"平台盲"的
空域桶/裸私聊键上，而 §4 那五枚新锁是按**接线后**的形状写的。本件收的就是那一格：

1. **四个生产调用点各交一次平台事实**（`capabilities/chat.py` 三处
   `resolve_intimate_context` ＋ 根 `__init__.py` 的 `/bot 描写` 派发一支），
   值**只准**出自契约字段 `IncomingMessage.platform`——绝不让代码去**猜**（反解会话键
   ＝T-1 那族病根的另一型）。
2. **同数字号的 QQ 私聊轮与 TG 私聊轮不共钉**（双向现算）。
3. **认不出的平台只会给出更窄的那一格**（speech／不授予），永不更宽。
4. **重启模拟**：换一具全新的引擎实例（进程内档态清零）之后，本人的描写钉照旧读得到。

🔴 本件判的是**接线**：平台那一维之外，会话那一维（I-2 的 (平台域, 会话, 人) 三段键，
2026-10-04 裁定）与"公共空间归哪一侧"（用户 2026-10-06 裁「telegram：群侧」）也都各有一枚
调用点锁，见下面 ③ 段——**三处消费方必须交同一个会话事实**，只接一侧就是 #33★ 那族病。

夹具铁律照 `tests/test_narration_axis_styles.py`（规则 6／台账 #66★／#76★）：走
`/bot reply`-类命令面与聊天主链的测试必 monkeypatch `shared_reply_policy_store`；
库路径交仓库外 `%TEMP%` 绝对路径；号全用合成值；生产库零写入。
"""
from __future__ import annotations

import ast
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    ContextBundle,
    ConversationHistoryResult,
    IncomingMessage,
    MemoryRetrievalResult,
    PersonaProfile,
    PrivacyLevel,
    RetrievalResult,
    RiskLevel,
    SendPolicy,
    SessionType,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import LLMReply
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    content_route as cr,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    intimate_control as ic,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    SHARED_CONTENT_ROUTE_ENGINE,
    grants_intimate_narration,
)

_ROOT = Path(__file__).resolve().parents[1]
_CHAT_SRC = (
    _ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "capabilities"
    / "chat.py"
)
_INIT_SRC = _ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
_IC_SRC = (
    _ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "intimate_control.py"
)

_QQ_UID = "7770002299"
_TG_SESSION = f"private_{_QQ_UID}"          # TG 私聊键形（中央件 FORM_PRIVATE 的另一写法）
_QQ_SESSION = _QQ_UID                        # QQ 私聊键形＝裸号
_UNKNOWN_PLATFORM = "mochat"                 # 认不出的平台（`platform_domain_of` → 空域）

#: 接线的**唯一写法**（na-keyfix §7.1 原话的口径）：只转述契约字段、缺省空串＝拿不到，
#: 绝不在调用处猜平台。三处注入缝逐字同形，注毒腿按这一枚整行做锚（docstring 里
#: 出现这串字面不算，`splitlines` 后逐行比 ⇒ 锚在真接线行上）。
_PLATFORM_LINE = 'platform=str(getattr(message, "platform", "") or ""),'


# ---------------------------------------------------------------- 夹具（本件自建）
#
# 刻意**不**用 `_load_sibling` 把 `tests/test_narration_axis_styles.py` 再执行一遍：
# 二次执行会多开一份临时库目录、并把那件在盘上的副作用带进同一次批跑（本席 2026-10-04
# 实跑：批里多出三枚与本席判据无关的红，把本件摘掉同批就绿）。夹具是夹具、不是判据——
# 判据仍旧只读真身（`chat.RP_STYLE_BLOCKS`／`cr.NARRATION_MODE_SCENE`），这里只造消息、
# 造上下文、造一本仓库外的临时偏好库。
_CONFIG_KEYS: dict[str, object] = {
    "bot_content_route_enabled": True,
    "bot_content_route_model": "grok-4.6",
    "bot_content_route_order": "grok-4.6,gemini-3.8-flash",
    "bot_content_route_words": "",
    "bot_content_route_intimate_threshold": 60.0,
    "bot_content_route_normal_threshold": 25.0,
    "bot_content_route_context_turns": 4,
    "bot_content_route_max_ttl_minutes": 120.0,
    "bot_content_route_idle_reset_minutes": 10.0,
    "bot_content_route_group_per_user_enabled": True,
}


def _config(db_path: str, **overrides: object) -> SimpleNamespace:
    base: dict[str, object] = dict(_CONFIG_KEYS)
    base["bot_addressing_preferences_db_path"] = db_path
    base.update(overrides)
    return SimpleNamespace(**base)


class _CapturingProvider:
    """记录收到的 messages 并原样成功返回（触发 prompt 组装全链）。"""

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self.messages = messages
        return LLMReply(text="嗯，我在听。你慢慢说。", provider="fake", model="m")


def _system_join(provider: _CapturingProvider) -> str:
    return "\n".join(
        str(item.get("content") or "")
        for item in provider.messages
        if item.get("role") == "system"
    )


def _section_header(instruction: str) -> str:
    """段落头从常量**真身**派生（不抄第二份字面，口径同 `test_rp_style_directives.py`）。"""
    head, marker, _ = instruction.partition("】")
    assert marker and head.startswith("【"), f"样式段缺【…】段落头：{instruction[:20]!r}"
    return f"{head}】"


@pytest.fixture(autouse=True)
def _no_production_reply_policy_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """聊天主链懒建的进程级策略 store 收成 None ⇒ 本件零生产库读写（台账 #76★）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character import reply_policy

    monkeypatch.setattr(reply_policy, "shared_reply_policy_store", lambda config: None)


@pytest.fixture(autouse=True)
def _clean_content_route_sessions() -> Any:
    """逐枚换新进程内档态（她裁过"重启即空"那一格就是本件的重启模拟面）。"""
    saved = SHARED_CONTENT_ROUTE_ENGINE._sessions
    SHARED_CONTENT_ROUTE_ENGINE._sessions = OrderedDict()
    yield SHARED_CONTENT_ROUTE_ENGINE
    SHARED_CONTENT_ROUTE_ENGINE._sessions = saved


def _message(*, platform: str, session_id: str) -> IncomingMessage:
    return IncomingMessage(
        platform=platform,
        adapter="onebot" if platform == "qq" else platform,
        bot_id="bot-wire",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id=_QQ_UID,
        plain_text="那你会怎么陪我。",
    )


def _one_turn(*, platform: str, session_id: str, cfg: Any) -> str:
    """走**生产注入缝**跑一轮，返回进模型的 system 段拼接（判的是接线，不是纯函数）。"""
    message = _message(platform=platform, session_id=session_id)
    provider = _CapturingProvider()
    chat.build_chat_result(
        message,
        _decision(message),
        _context(message),
        llm_provider=provider,
        content_route_config=cfg,
    )
    return _system_join(provider)


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def _context(message: IncomingMessage) -> ContextBundle:
    return ContextBundle(
        request_id=message.request_id,
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default", action_brackets=True),
        memory_results=MemoryRetrievalResult(request_id=message.request_id),
        conversation_history=ConversationHistoryResult(request_id=message.request_id),
        knowledge_results=RetrievalResult(request_id=message.request_id),
        current_message=message.plain_text,
        sender_id=_QQ_UID,
        session_id=message.session_id,
    )


def _pin(*, platform: str, session_id: str, cfg: Any, mode: str) -> None:
    """经轴心唯一的写腿落一枚**本人**描写钉（键口与读侧同一枚 `_narration_person_key`）。"""
    assert cr.write_narration_pin(
        session_id, mode=mode, sender_id=_QQ_UID, config=cfg, platform=platform
    ) is True, "描写钉没写进去＝下面的断言全在空跑"


def _scene_headers() -> tuple[str, ...]:
    """两格"铺开了写"的段落头（现算自选择表，不抄字面；两格**互斥**，判据只判"有没有吃到其中一格"）。"""
    return tuple(
        _section_header(block)
        for (mode, _intimate), block in chat.RP_STYLE_BLOCKS.items()
        if mode == cr.NARRATION_MODE_SCENE
    )


def _got_scene_block(joined: str) -> bool:
    return any(header in joined for header in _scene_headers())


def _db_cfg(tmp_path: Path, tag: str) -> SimpleNamespace:
    """每一段判据各拿一本**自己的**临时库（同库同号＝前一段写的钉会污染后一段）。

    路径来自 pytest 的 `tmp_path`（仓库外、**Runtime 外**，台账 #76★ 假红坑；规则 6）。
    描写钉按 (平台域, 用户号) 归属＝**按人全局**，一个文件里同名测试者共用一本库必然互吃。
    """
    return _config(str(tmp_path / f"wiring-{tag}.sqlite3"))


# ---------------------------------------------------------------- ① 接线形状（AST）


def _call_sites(src: str, func_name: str) -> list[ast.Call]:
    tree = ast.parse(src, filename="<src>")
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == func_name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == func_name)
        )
    ]


def _kwarg_source(src: str, call: ast.Call, name: str) -> str:
    for kw in call.keywords:
        if kw.arg == name:
            return ast.get_source_segment(src, kw.value) or ""
    return ""


def _missing_platform_sites(src: str, path_name: str) -> list[str]:
    """每一处 `resolve_intimate_context(...)` 都必须交平台事实，且值只准出自契约字段。

    判据方向刻意是"每一处都查"而不是"数一处接了"：接一侧＝na-keyfix §7.1 点名的
    #33★ 两形不相交（写在 ``qq:<uid>``、读在 ``<uid>`` ⇒ 钉永不上效）。
    """
    bad: list[str] = []
    for call in _call_sites(src, "resolve_intimate_context"):
        given = _kwarg_source(src, call, "platform")
        if not given:
            bad.append(f"{path_name}:{call.lineno} 没交 platform")
            continue
        if "message" not in given or "platform" not in given:
            bad.append(
                f"{path_name}:{call.lineno} platform={given!r} 不是从契约字段 "
                "IncomingMessage.platform 取的（猜平台＝T-1 同族）"
            )
    return bad


def test_every_injection_site_threads_the_platform_from_the_contract_field() -> None:
    """`chat.py` 三处注入缝调用点**逐处**交 `message.platform`（一处不缺、一处不猜）。"""
    src = _CHAT_SRC.read_text(encoding="utf-8")
    assert len(_call_sites(src, "resolve_intimate_context")) == 3, (
        "注入缝调用点数量变了：请同步本锁与接线，别留半件"
    )
    assert _missing_platform_sites(src, _CHAT_SRC.name) == []


def test_the_narration_command_leg_in_the_root_gets_the_platform() -> None:
    """根 `__init__.py` 的 `/bot 描写` 那一支把 `message.platform` 交给 handler。

    只转述契约字段：`platform=` 的值必须点名 `message` 的 platform，硬写 `"qq"` 之类
    ＝把命令面钉死在一个平台上（写进去的键与读出来的键从此永不相交）。
    """
    src = _INIT_SRC.read_text(encoding="utf-8")
    hits = [
        call
        for call in _call_sites(src, "build_narration_control_result")
    ]
    assert len(hits) == 1, f"描写档命令面应有恰好一支派发，现算 {len(hits)} 支"
    given = _kwarg_source(src, hits[0], "platform")
    assert given, f"根 __init__.py 的描写档派发没交 platform：{ast.dump(hits[0])[:200]}"
    assert "message" in given and "platform" in given, f"platform={given!r} 不是契约字段"


def test_wiring_lock_goes_red_on_a_temp_copy_strip_one_site(tmp_path: Path) -> None:
    """注毒自证（失效形态 247／#68★）：抹掉一处 `platform=` ⇒ 同一把尺必红。

    副本落 `%TEMP%`，源码树一字不动。模拟的正是 na-keyfix §7.1 点名的"只接一侧"那种半件。
    """
    original = _CHAT_SRC.read_text(encoding="utf-8")
    total = original.count(_PLATFORM_LINE)
    assert total == 3, f"三处注入缝接线形状变了（现算 {total} 处）：请同步本件"
    lines = original.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.strip() == _PLATFORM_LINE)
    lines[index] = ""
    poisoned = "".join(lines)
    assert poisoned != original, "注毒没落到任何一处＝本件空跑"
    assert poisoned.count(_PLATFORM_LINE) == total - 1, "注毒没恰好少一处（多了就是改错了地方）"
    work = tmp_path / "chat_strip.py"
    work.write_text(poisoned, encoding="utf-8")
    hits = _missing_platform_sites(poisoned, work.name)
    assert len(hits) == 1, f"抹掉一处接线后尺没照出来：{hits}"
    assert "没交 platform" in hits[0], hits[0]


# ---------------------------------------------------------------- ② 行为面（现算）


def test_qq_and_tg_turns_of_the_same_number_do_not_share_a_pin(tmp_path: Path) -> None:
    """(a) 同数字号：QQ 私聊钉上的 `scene` **不**跟着走到 TG 私聊，反向亦然。

    这一格就是席 na-keyfix §1 复现的 B-1（`group_-1001_<uid>` 与裸 `<uid>` 折成同一段）
    的**接线后**形态：不接平台时两侧都会吃到同一枚钉。
    """
    cfg = _db_cfg(tmp_path, "qq-pin")
    _pin(platform="qq", session_id=_QQ_SESSION, cfg=cfg, mode=cr.NARRATION_MODE_SCENE)
    joined_qq = _one_turn(platform="qq", session_id=_QQ_SESSION, cfg=cfg)
    joined_tg = _one_turn(platform="telegram", session_id=_TG_SESSION, cfg=cfg)
    assert _got_scene_block(joined_qq), "QQ 侧钉了 scene 却没拿到任何铺设段＝接线没通"
    assert not _got_scene_block(joined_tg), "TG 同号吃到了 QQ 那枚钉＝互串"
    assert _section_header(chat.NORMAL_NO_ACTION_INSTRUCTION) in joined_tg

    other = _db_cfg(tmp_path, "tg-pin")
    _pin(platform="telegram", session_id=_TG_SESSION, cfg=other, mode=cr.NARRATION_MODE_SCENE)
    joined_tg2 = _one_turn(platform="telegram", session_id=_TG_SESSION, cfg=other)
    joined_qq2 = _one_turn(platform="qq", session_id=_QQ_SESSION, cfg=other)
    assert _got_scene_block(joined_tg2), "TG 侧钉了 scene 却没拿到铺设段"
    assert not _got_scene_block(joined_qq2), "QQ 侧吃到了 TG 那枚钉＝互串（反向）"


def test_unknown_platform_only_ever_narrows_the_reading(tmp_path: Path) -> None:
    """(b) 认不出的平台 ⇒ 只可能比已知平台**更窄**：绝不因"平台未知"就通配吃钉。

    判据按两侧各现算一次并比"是否拿到铺设"，不比字面长度（少给＝安全侧）。
    """
    cfg = _db_cfg(tmp_path, "unknown-platform")
    _pin(platform="qq", session_id=_QQ_SESSION, cfg=cfg, mode=cr.NARRATION_MODE_SCENE)
    joined_known = _one_turn(platform="qq", session_id=_QQ_SESSION, cfg=cfg)
    joined_unknown = _one_turn(platform=_UNKNOWN_PLATFORM, session_id=_QQ_SESSION, cfg=cfg)
    assert any(h in joined_known for h in _scene_headers()), "已知平台侧连铺设段都没拿到＝夹具坏了"
    for header in _scene_headers():
        assert header not in joined_unknown, (
            f"未知平台吃到了已知平台的钉（{header!r}）＝把 fail-closed 写成了通配"
        )
    ctx_unknown = cr.resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type="private",
        sender_id=_QQ_UID,
        session_key=_QQ_SESSION,
        config=cfg,
        platform=_UNKNOWN_PLATFORM,
    )
    assert grants_intimate_narration(str(ctx_unknown["narration_source"])) is False, ctx_unknown


def test_the_pin_survives_a_fresh_engine_instance(tmp_path: Path) -> None:
    """(c) 重启模拟：换一具全新引擎（进程内档态空）后，本人那枚钉照旧读得到。

    台账 #76★ 那一格（档态住在进程内 LRU、重启即空）只影响**亲密轴**；描写钉在库里 ⇒
    接线后必须"跨引擎实例"仍成立，否则接线接的是一枚每次重启都要重钉的键。
    """
    cfg = _db_cfg(tmp_path, "fresh-engine")
    _pin(platform="qq", session_id=_QQ_SESSION, cfg=cfg, mode=cr.NARRATION_MODE_SCENE)
    fresh = cr.ContentRouteEngine()
    ctx = cr.resolve_intimate_context(
        fresh,
        session_type="private",
        sender_id=_QQ_UID,
        session_key=_QQ_SESSION,
        config=cfg,
        platform="qq",
    )
    assert ctx["narration_mode"] == cr.NARRATION_MODE_SCENE, ctx
    assert grants_intimate_narration(str(ctx["narration_source"])) is True, ctx
    SHARED_CONTENT_ROUTE_ENGINE._sessions = OrderedDict()
    joined = _one_turn(platform="qq", session_id=_QQ_SESSION, cfg=cfg)
    assert any(h in joined for h in _scene_headers()), "新引擎实例读不到自己的钉＝键形随进程漂"


# -------------------------------------- ③ 会话维接线（I-2 落地 ＋ 用户 2026-10-06 裁「telegram：群侧」）

#: 描写钉的**会话段**唯一的交法：命令面三处取钉口各转述一次本函数已有的 `session_type`
#: （契约字段 `IncomingMessage.session_type` 的规范值），与注入缝那一支同源。
_CONV_LINE = "conversation_type=session_type,"

#: 会话面归侧的**唯一判据**名（`content_route.is_public_space_session`）；样式表选择点
#: 只准转述它，抄一份 `== "group"` 就是第二把尺（公共空间判据三处共用，见轴心 docstring）。
_PUBLIC_RULER = "is_public_space_session"


def _missing_conversation_type_sites(src: str, path_name: str) -> list[str]:
    """三枚取钉口（读／写／收）每一处都必须交会话事实，且值只准出自 `session_type`。"""
    bad: list[str] = []
    for name in ("read_narration_pin", "write_narration_pin", "clear_narration_pin"):
        for call in _call_sites(src, name):
            given = _kwarg_source(src, call, "conversation_type")
            if not given:
                bad.append(f"{path_name}:{call.lineno} `{name}` 没交 conversation_type")
            elif "session_type" not in given:
                bad.append(
                    f"{path_name}:{call.lineno} {name}(..., conversation_type={given!r}) "
                    "交的不是本函数已有的 session_type（猜键形＝T-1 同族）"
                )
    return bad


def test_every_narration_pin_site_in_the_command_leg_threads_the_session_type() -> None:
    """`intimate_control.py` 三处取钉口**逐处**交 `conversation_type=session_type`。

    未接的那一侧会落到 `("private", "")` 那一格，而注入缝按 (`"channel"`, 键) 去读 ⇒
    她在 TG 频道里 `/bot 描写 scene` 钉进去，聊天主链永远读不到（写在 A 形、读在 B 形，
    #33★ 那族在会话维上的另一型；台账 T-1 的复发形态）。
    """
    src = _IC_SRC.read_text(encoding="utf-8")
    sites = [
        call
        for name in ("read_narration_pin", "write_narration_pin", "clear_narration_pin")
        for call in _call_sites(src, name)
    ]
    assert len(sites) == 3, f"取钉口数量变了（现算 {len(sites)} 处）：请同步本锁与接线"
    assert _missing_conversation_type_sites(src, _IC_SRC.name) == []
    assert src.count(_CONV_LINE) == 3, (
        f"三处接线形状变了（现算 {src.count(_CONV_LINE)} 处）：请同步本件"
    )


def _style_group_source(src: str) -> str:
    """样式表选择点那一处 `group=` 的**源码文本**（选择点全仓唯一，多处＝先同步本件）。"""
    calls = _call_sites(src, "resolve_rp_style_block")
    assert len(calls) == 1, f"样式段注入点应恰好一处，现算 {len(calls)} 处"
    return _kwarg_source(src, calls[0], "group")


def test_the_style_table_choice_uses_the_one_public_space_ruler() -> None:
    """样式表选择点（`chat.py` 唯一一处 `resolve_rp_style_block`）的 `group=` 只准转述中央判据。

    方向是**变严**：`channel` 归群侧后，群侧那张表（不落笔身形／衣着）覆盖的会话面只会
    更大，不会更小；把判据抄回 `== "group"` 等于悄悄把频道放回了私聊面。
    """
    src = _CHAT_SRC.read_text(encoding="utf-8")
    given = _style_group_source(src)
    assert _PUBLIC_RULER in given, (
        f"group={given!r} 没走中央那把尺 `{_PUBLIC_RULER}`＝第二把尺（或频道归侧没接上）"
    )
    assert f"def {_PUBLIC_RULER}" not in src, "chat.py 里自己造了一枚同名判据＝第二真身"
    assert f"{_PUBLIC_RULER}," in src, "chat.py 没从 content_route 导入那把尺"


def _channel_reading(cfg: Any, session_key: str) -> dict[str, Any]:
    return cr.resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type="channel",
        sender_id=_QQ_UID,
        session_key=session_key,
        config=cfg,
        platform="telegram",
    )


#: 两形都要：`channel_<chat.id>` 是 TG 侧写法（键形自己带得出"频道"，前缀 fallback 兜得住）；
#: `guild_<g>_channel_<c>_<u>` 是官方 QQ 适配器写法，中央件 `session_keys` docstring 第 4 条
#: 明写它**不判** ⇒ 只有契约字段 `session_type` 交进来才分得开桶。只测前一形＝把 fallback
#: 当接线（真接线没被量到）。
_CHANNEL_KEYS = ("channel_-1001234567890", "guild_98765_43210_7770002299")


@pytest.mark.parametrize("session_key", _CHANNEL_KEYS)
def test_a_channel_pin_written_by_the_command_is_read_by_the_injection_leg(
    session_key: str, tmp_path: Path
) -> None:
    """行为面（不只形状）：频道里管理员亲手钉下的 `scene`，注入缝那次读数必须吃到。

    键形一律现算自中央件（`route_key` 由 `resolve_intimate_context` 交回），测试不猜第四形。
    """
    cfg = _db_cfg(tmp_path, f"channel-roundtrip-{session_key[:6]}")
    before = _channel_reading(cfg, session_key)
    assert before["narration_mode"] != cr.NARRATION_MODE_SCENE, (
        "夹具没清干净：这一格改判前就已经是 scene，下面的断言会在空跑"
    )
    ic.build_narration_control_result(
        config=cfg,
        request_id="req-channel-pin",
        subcommand="scene",
        session_type="channel",
        session_key=session_key,
        sender_id=_QQ_UID,
        sender_roles=["super_admin"],
        platform="telegram",
    )
    after = _channel_reading(cfg, session_key)
    assert after["narration_mode"] == cr.NARRATION_MODE_SCENE, (
        f"命令面钉在频道里、注入缝读不到（现算 {after['narration_mode']!r}）"
        "＝会话维只接了一侧"
    )
    assert grants_intimate_narration(str(after["narration_source"])) is True, after

    private = cr.resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type="private",
        sender_id=_QQ_UID,
        session_key=f"private_{_QQ_UID}",
        config=cfg,
        platform="telegram",
    )
    assert private["narration_mode"] != cr.NARRATION_MODE_SCENE, (
        "频道那枚钉串进了私聊那一格＝换会话不用重开（I-2 要求换会话重钉）"
    )


def test_conversation_wiring_lock_goes_red_on_a_poisoned_copy() -> None:
    """注毒自证两腿：抹掉一处 `conversation_type=` ⇒ 尺红；把 `group=` 换回手抄的等值判断 ⇒ 尺红。

    只毒内存里的副本，源码树一字不动（失效形态 247／#68★：修法在册≠修好在盘）。
    """
    original = _IC_SRC.read_text(encoding="utf-8")
    total = original.count(_CONV_LINE)
    assert total == 3, f"命令面接线形状变了（现算 {total} 处）：请同步本件"
    lines = original.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.strip() == _CONV_LINE)
    lines[index] = ""
    stripped = "".join(lines)
    assert stripped.count(_CONV_LINE) == total - 1, "注毒没恰好少一处"
    hits = _missing_conversation_type_sites(stripped, "ic_strip.py")
    assert len(hits) == 1 and "没交 conversation_type" in hits[0], hits

    src = _CHAT_SRC.read_text(encoding="utf-8")
    given = _style_group_source(src)
    assert _PUBLIC_RULER in given, "选择点还没走中央判据＝注毒腿没有可毒的锚（先接线性）"
    poisoned_chat = src.replace(f"group={given}", 'group=_session_type_value == "group"', 1)
    assert poisoned_chat != src, "注毒没落到选择点＝空跑"
    assert _PUBLIC_RULER not in _style_group_source(poisoned_chat), (
        "手抄一份等值判断后尺没照出来＝这把尺是瞎的"
    )


# ---- ③ 续：拿不到契约字段那一退的**方向**（`guild_` 形 × 未接线调用方）
#
# 缺陷（席 guildfall 报，2026-10-06）：`_narration_store_scope` 的 docstring 自称"只有拿不到
# 契约字段时才退到**前缀 fallback**——那一退的方向是 fail-closed（宁可多分一刀桶，也绝不把
# 公共空间的钉折进私聊那一格）"，可那一退只认 `channel_` 一形。官方 QQ 适配器的频道键是另一形
# `guild_<g>_channel_<c>_<u>`（`session_keys` docstring 第 1 条与第 4 条都在册）⇒ 不交
# `session_type` 的调用方把一枚**公共空间**的钉折进 `("private", "")` 那一格＝与它自称的方向
# **正好反向**，同一枚钉因此还在"交会话事实"与"没交"两侧**读写分叉**。
# 🔴 本段只判**兜底方向**：契约字段仍是正解——生产三处取钉口（`read`／`write`／`clear`
# `_narration_pin`）都交会话事实，那由上面
# `test_every_narration_pin_site_in_the_command_leg_threads_the_session_type` 锁着，
# 它咬得住的自证在 `test_conversation_wiring_lock_goes_red_on_a_poisoned_copy`。
# 🔴 方向＝只准**变严**：`guild_` 那几行从**共桶**（私聊格）拆成**各按整键分桶**；群格与
# 私聊格的既有键形、零迁移承诺（裸号／`private_`／`friend_`／`console_` 诸形照旧
# `("private", "")`）一字不动 ⇒ 另有一枚"其余各形逐格不漂"的锁在同一段里守着。

#: 键形只复用 ③ 段已在册的两形（`_CHANNEL_KEYS`），本段不自拼第四形；成员派生键一律经
#: 真身构造口 `content_route.member_session_key` 造（其逆即轴心在用的 `split_member_session_key`），
#: 认形只准用中央件 `parse_session_key`。
_GUILD_CHANNEL_KEY: str = _CHANNEL_KEYS[1]
_TG_CHANNEL_KEY: str = _CHANNEL_KEYS[0]
_OTHER_GUILD_CHANNEL_KEY: str = "guild_11111_22222_7770002299"  # 同一在册形，只换号
#: 私聊那一格的**真身**（不抄字面）：轴心 fail-closed 的兜底落点就是这两个常量。
_PRIVATE_CELL: tuple[str, str] = (cr._EXPLICIT_PIN_SESSION_TYPE, cr._EXPLICIT_PIN_SESSION_ID)


@pytest.mark.parametrize(
    "session_key",
    [_GUILD_CHANNEL_KEY, cr.member_session_key(_GUILD_CHANNEL_KEY, _QQ_UID)],
    ids=["guild_形", "guild_形+成员段"],
)
def test_the_prefix_fallback_does_not_fold_a_guild_key_into_the_private_cell(
    session_key: str,
) -> None:
    """不交 `session_type` 时，`guild_` 形既不得落进私聊格，也必须与交了契约字段的读侧同格。

    三句断言：①不是 `("private", "")`；②`session_type` 在场／缺席两侧**同一格**（＝"同一枚钉
    在接线侧与未接线侧读写分叉"这一族就此闭合）；③会话段非空 ⇒ 频道之间仍各按整键分桶
    （I-2 那枚"换会话要重开"的齿在群侧同样咬合，不换格＝全频道共用一格）。
    """
    unwired = cr._narration_store_scope(session_key)
    wired = cr._narration_store_scope(session_key, SessionType.CHANNEL.value)
    assert unwired != _PRIVATE_CELL, (
        f"未接线的兜底把公共空间（官方 QQ 频道形）的钉折进了私聊那一格：{unwired!r}"
        "＝docstring 自称的 fail-closed 方向写反了"
    )
    assert unwired == wired, (
        f"兜底与接线不同格（未交={unwired!r} / 交了={wired!r}）＝读写分叉"
    )
    assert unwired[0] == SessionType.CHANNEL.value, unwired
    assert unwired[1], f"会话段是空串＝所有频道共用一格（换会话不用重开）：{unwired!r}"
    assert cr._narration_store_scope(_OTHER_GUILD_CHANNEL_KEY) != unwired, (
        "另一枚频道键与它同桶＝把分桶改成了共桶（本段只准变严）"
    )


def test_the_other_key_shapes_keep_their_cells_untouched() -> None:
    """真值表里其余各形**逐格不漂**：群格三形、私聊格四形、已有的 `channel_` 兜底照旧。

    这枚锁守的是"变严不许顺手搬家"：`friend_`／`console_`／裸号／`private_` 都是**私聊面**
    （中央件 docstring 第 4 条在册），把它们的兜底也"补全"出去＝把零迁移承诺吃掉了。
    """
    group_cell = (SessionType.GROUP.value, "123456")
    cases: tuple[tuple[str, tuple[str, str]], ...] = (
        ("group:123456", group_cell),
        (f"group_123456_{_QQ_UID}", group_cell),
        (cr.member_session_key(f"group_123456_{_QQ_UID}", _QQ_UID), group_cell),
        (_QQ_SESSION, _PRIVATE_CELL),  # QQ 私聊＝裸号
        (_TG_SESSION, _PRIVATE_CELL),  # TG 私聊键形
        ("friend_OX001abc", _PRIVATE_CELL),  # 中央件第 4 条在册：`friend_<openid>`＝私聊面
        ("console_7770002299", _PRIVATE_CELL),  # 同条在册：console 的 `<channel>_<user>`
        (_TG_CHANNEL_KEY, (SessionType.CHANNEL.value, _TG_CHANNEL_KEY)),  # 原有兜底不迁
    )
    for key, want in cases:
        assert cr._narration_store_scope(key) == want, f"{key} 那一格漂了（现算 {want!r}）"


def test_an_unwired_write_leg_lands_where_the_wired_read_leg_looks(tmp_path: Path) -> None:
    """行为面（不只纯函数）：未接线的写腿落库后，注入缝按契约字段读数必须吃到**同一格**。

    修前这一格是**反着**的两件事：写腿把频道钉折进 `("private", "")` ⇒ ①注入缝按
    (`"channel"`, 键) 读不到她钉下的那一格；②反倒被**私聊**那一轮读到＝换会话不用重开
    （I-2 的齿在群侧失灵）。第三枚消费者（`clear`）同轴性一并判：写进了新桶却收不回
    ＝"写了收不掉"那一族。
    """
    cfg = _db_cfg(tmp_path, "guild-fallback-roundtrip")
    before = _channel_reading(cfg, _GUILD_CHANNEL_KEY)
    assert before["narration_mode"] != cr.NARRATION_MODE_SCENE, (
        "夹具没清干净：这一格改判前就已经是 scene，下面的断言会在空跑"
    )
    assert cr.write_narration_pin(
        _GUILD_CHANNEL_KEY,
        mode=cr.NARRATION_MODE_SCENE,
        sender_id=_QQ_UID,
        config=cfg,
        platform="telegram",
    ) is True, "描写钉没写进去＝下面的断言全在空跑"

    after = _channel_reading(cfg, _GUILD_CHANNEL_KEY)
    assert after["narration_mode"] == cr.NARRATION_MODE_SCENE, (
        f"未接线写腿落在 {cr._narration_store_scope(_GUILD_CHANNEL_KEY)!r}、"
        f"注入缝按 {cr._narration_store_scope(_GUILD_CHANNEL_KEY, SessionType.CHANNEL.value)!r} 读"
        "＝同一枚钉读写分叉（兜底那一退把公共空间折进了私聊格）"
    )
    assert grants_intimate_narration(str(after["narration_source"])) is True, after

    private = cr.resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type="private",
        sender_id=_QQ_UID,
        session_key=_TG_SESSION,
        config=cfg,
        platform="telegram",
    )
    assert private["narration_mode"] != cr.NARRATION_MODE_SCENE, (
        "频道那枚钉被私聊那一轮吃到了＝兜底把公共空间折进私聊格的行为面实锤"
    )

    assert cr.clear_narration_pin(
        _GUILD_CHANNEL_KEY, sender_id=_QQ_UID, config=cfg, platform="telegram"
    ) is True, "收腿没落库＝下面那条断言在空跑"
    assert _channel_reading(cfg, _GUILD_CHANNEL_KEY)["narration_mode"] != cr.NARRATION_MODE_SCENE, (
        "写腿与收腿不同轴＝写了收不掉"
    )


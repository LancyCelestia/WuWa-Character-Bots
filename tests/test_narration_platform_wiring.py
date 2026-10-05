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

🔴 本波**只**接平台这一维：钉的作用域**仍是"整个人"全局**（`(平台域, 用户号)`），
不是"每 (平台, 会话, 人)"——会话那一维是**另一条待裁的裁定**（等设计回报），别把
这里读成已经做完。

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

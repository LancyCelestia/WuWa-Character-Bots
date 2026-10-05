"""第五根轴＝描写档（speech／scene）的样式段・篇幅・审计面（席 na2-style，2026-10-05）。

用户的裁定（2026-10-04 已批，见 `docs/HANDBOOK.md` §76.8 的 G-1…G-4 那一行）：

- **G-1**：普通模式也能进 `scene` ⇒ 场景样式段**不能再住在亲密专属的那一段里**。
- **G-4＝乙**（2026-10-04 深夜改判，原话「普通档既然都改成场景模式了，那就把衣着和
  环境也都写上，这些都挺重要的」）：普通模式 `scene` 写「语言＋动作＋神态＋心理＋
  外貌**观感**＋**衣着**＋**周遭环境**」，仍**不写落在身体上的细部**（锁骨、腰线那一类）；
  那一类只有亲密模式 `scene`（现役五维段那一格）许可。六硬线与"普通档不是性描写档"一字未动。
- 默认 `speech`（只写说出口的话）；`scene` 那一轮的篇幅**只有**通过既有那把授予尺
  （`content_route.grants_intimate_narration(narration_source)`）才拿得到登记表顶格档「铺写」。

本文件判的是**样式面／篇幅面／审计面**三件事。轴本体（常量、`resolve_intimate_context`
的 `narration_mode`／`narration_source` 两枚键、命令表、按人持久钉）归席 na1-core，
住在 `runtime/content_route.py`＋`runtime/intimate_control.py`＋`character/addressing.py`
——本文件**一概不重推优先序**：判据一律走真实链路（`apply_manual`／`write_narration_pin`
→ `resolve_intimate_context` → 注入缝），只有「轴说 scene 而尺没点头」那一枚**防御腿**
用 monkeypatch 造出真实链路给不出的形状（轴心自己会 fail-closed，正常写不出这枚）。

判据用的**词表全部从真身 import**，本文件不抄第二份（规则 10）：

- 描写四维 ← `tests/test_reply_policy_permanent.py::_SCENE_DIMENSIONS`
- 身体细部词表 ← `capabilities/chat.py::SCENE_CORPORAL_TERMS`（G-4乙 的唯一体，证人＝
  亲密段那句「彼此的形貌与衣着」里的**形貌**；衣着自乙 起归普通档许可，不再充当分界）
- 衣着词表 ← `capabilities/chat.py::NORMAL_SCENE_CLOTHING_TERMS`（同一家的第二枚表，
  判"许可里有、禁令里没有"，本件不抄第二份名单）
- R-18 精确词表 ← `tests/test_copy_redline_gate.py::R18_TERMS`
- 性语境／体态红线尺 ← `security/content_safety.py::_SEXUAL_CONTEXT_RE`／
  `_BODY_TYPE_PATTERN`（六硬线的机器面）
- 群聊出站内容尺 ← `domains/render/reviewer.py::_PUBLIC_OUTPUT_UNSAFE`

生产库隔离：本文件所有轮次都走 `build_chat_result`，而 `.env` 的 Runtime 根指向生产
（台账 #66★＋#76 两处踩过）⇒ 有一枚 autouse 夹具把 `shared_reply_policy_store` 收成
None，任何一枚用例都不许打开她的真实偏好库；描写钉与亲密钉一律落在本件独有的
`%TEMP%` 临时库里（`_TMP_DATA_DIR`）。
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

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

# 红线尺与词表＝真身 import（绝不在测试里抄第二份；抄了就不叫锁，叫另一份会漂移的散文）
from plugins.bot_unified_runtime.domains.chat_reply.security.content_safety import (
    _BODY_TYPE_PATTERN,
    _SEXUAL_CONTEXT_RE,
)
from plugins.bot_unified_runtime.domains.render.reviewer import _PUBLIC_OUTPUT_UNSAFE

# DATAFIX：称谓偏好／描写钉 store 无键时走生产缺省路径 ⇒ 把测试读写的 sqlite 落到
# 运行数据根。显式注入本件独有临时绝对路径（家规同 tests/test_rp_style_directives.py 顶部）。
_TMP_DATA_DIR = tempfile.mkdtemp(prefix="thyg-nar-axis-")
_TEMP_WORK = Path(tempfile.gettempdir()) / "seat-na2-style-work"
_REPO = Path(__file__).resolve().parents[1]


def _load_sibling(relative: str):
    """按路径加载同树那件真身（只取词表/助手，不复制第二份——口径同
    `test_rp_style_directives.py::test_persona_prose_does_not_smuggle_length_doctrine`）。"""
    path = _REPO / "tests" / relative
    spec = importlib.util.spec_from_file_location(f"_nar_axis_src_{path.stem}", path)
    assert spec is not None and spec.loader is not None, f"同树真身加载失败：{path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_RP_HELPERS = _load_sibling("test_rp_style_directives.py")
_SCENE_DIMENSIONS: tuple[str, ...] = _load_sibling(
    "test_reply_policy_permanent.py"
)._SCENE_DIMENSIONS
_R18_TERMS: tuple[str, ...] = _load_sibling("test_copy_redline_gate.py").R18_TERMS

_section_header = _RP_HELPERS._section_header
_length_line_of = _RP_HELPERS._length_line_of
_system_join = _RP_HELPERS._system_join


# ---------------------------------------------------------------- 构造器（离线 mock）


@pytest.fixture(autouse=True)
def _no_production_reply_policy_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """聊天主链懒建的进程级策略 store 一律收成 None ⇒ 本文件零生产库读写。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character import reply_policy

    monkeypatch.setattr(reply_policy, "shared_reply_policy_store", lambda config: None)


def _config(**overrides: object) -> SimpleNamespace:
    """每枚配置各拿一本**自己的**临时偏好库（席 na-land 接线之后必须如此，理由在册）。

    描写钉的键是 `person_scope_key(平台域, 用户号)`＝**按人全局**（G-3 的实现面），本文件
    所有用例的 `sender_id` 都是 `user-nar` ⇒ 共用一本库时，前一枚用例钉的 `scene` 会静默
    漏进后一枚（接线之前不会：写侧没交平台事实，键落回"裸会话键"，各用例天然隔开）。
    生产本来就是这个形状（同一个人换会话仍带着自己的钉），所以这里修的是**夹具的隔离**，
    不是判据：一次 `_config()` 一本库，读写两侧同库同平台，用例之间互不吃钉。
    """
    isolated_db_dir = tempfile.mkdtemp(prefix="nar-axis-db-", dir=_TMP_DATA_DIR)
    base: dict[str, object] = {
        "bot_addressing_preferences_db_path": os.path.join(
            isolated_db_dir, "addressing_preferences.sqlite3"
        ),
        "bot_content_route_enabled": True,
        "bot_content_route_model": "grok-4.6",
        "bot_content_route_order": "grok-4.6,gemini-3.8-flash",
        "bot_content_route_words": "",
        "bot_content_route_intimate_threshold": 60.0,
        "bot_content_route_normal_threshold": 25.0,
        "bot_content_route_context_turns": 4,
        "bot_content_route_max_ttl_minutes": 120.0,
        "bot_content_route_idle_reset_minutes": 10.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _message(session_id: str, text: str = "今天有点累，想和你说说话。") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id="user-nar",
        plain_text=text,
    )


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


def _context(session_id: str, *, action_brackets: bool = True) -> ContextBundle:
    return ContextBundle(
        request_id="req-nar-axis",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
        ),
        tone=ToneProfile(
            profile_id="shorekeeper", mode="default", action_brackets=action_brackets
        ),
        memory_results=MemoryRetrievalResult(request_id="req-nar-axis"),
        conversation_history=ConversationHistoryResult(request_id="req-nar-axis"),
        knowledge_results=RetrievalResult(request_id="req-nar-axis"),
        current_message="今天有点累，想和你说说话。",
        sender_id="user-nar",
        session_id=session_id,
    )


class _CapturingProvider:
    """记录收到的 messages 并原样成功返回（触发 prompt 组装全链）。"""

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def generate(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> LLMReply:
        self.messages = messages
        return LLMReply(text="嗯，我在听。你慢慢说。", provider="fake", model="m")


def _one_turn(
    session: str, cfg: object, *, text: str = "那你会怎么陪我。"
) -> tuple[str, object]:
    """跑一轮并返回 `(进模型的 system 段拼接, CapabilityResult)`。"""
    provider = _CapturingProvider()
    message = _message(session, text=text)
    result = chat.build_chat_result(
        message,
        _decision(message),
        _context(session),
        llm_provider=provider,
        content_route_config=cfg,
    )
    return _system_join(provider), result


def _open_intimate(session: str, cfg: object) -> None:
    """真实链路：本人显式开亲密档（来源＝`manual_command`，在授予面上）。"""
    assert SHARED_CONTENT_ROUTE_ENGINE.apply_manual(session, "intimate", cfg) is True


def _pin_narration(session: str, cfg: object, mode: str) -> None:
    """真实链路：把**本人**的描写档钉到 `mode`（G-2/G-3 那一枚持久钉，读写同口）。

    键由轴心的唯一取键口算出（`_narration_person_key`），这里传的 session_key／sender_id
    与注入缝那一次合成同形 ⇒ 不猜键形（#33★ 那族"两形永不相交"的老坑）。
    🔴 `platform` 必须与 `_message()` 那一枚**同值**（席 na-land 接线之后生产两侧都交
    `IncomingMessage.platform`；这里不交＝写在裸键、读在 ``qq:<uid>`` ⇒ 钉永不上效，
    正是席 na-keyfix §7.1 点名的"只接一侧"那种半件）。
    """
    assert cr.write_narration_pin(
        session, mode=mode, sender_id="user-nar", config=cfg, platform="qq"
    ) is True, "描写钉没写进去＝本波判据全部退化成缺省，下面的断言什么都没测"


def _granting_sources() -> list[str]:
    """现算「哪些来源拿到叙述授予」——不点名、不抄成员表（G-2 之后第 4 支 `narration_pin`
    一落地这里自动跟上）。"""
    found: list[str] = []
    for name in dir(cr):
        if not name.startswith("INTIMATE_SOURCE_"):
            continue
        value = getattr(cr, name)
        if isinstance(value, str) and value and grants_intimate_narration(value):
            found.append(value)
    return found


def _non_granting_sources() -> list[str]:
    found: list[str] = []
    for name in dir(cr):
        if not name.startswith("INTIMATE_SOURCE_"):
            continue
        value = getattr(cr, name)
        if isinstance(value, str) and value and not grants_intimate_narration(value):
            found.append(value)
    return found


def _install_axis(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str,
    source: str,
    narration_mode: str,
    narration_source: str,
    tier: str = cr.INTIMATE_TIER_L2,
) -> None:
    """把一枚**真实链路造不出来**的读数喂进注入缝读的那一枚 dict（防御腿专用）。

    注入缝只转述这枚 dict（判定时机在 `observe_turn` 之后，台账 #53★），所以这里给什么
    chat.py 就读什么——正因如此它也只能用来判"读数自相矛盾时怎么收"，不用来判优先序
    （优先序归轴心，另有 `tests/test_narration_axis_*.py` 那些件守着）。
    """

    def _fake(engine: object, **kwargs: object) -> dict[str, object]:
        return {
            "eligible": True,
            "route_key": str(kwargs.get("session_key") or ""),
            "mode": mode,
            "source": source,
            "tier": tier,
            "narration_mode": narration_mode,
            "narration_source": narration_source,
        }

    monkeypatch.setattr(chat, "resolve_intimate_context", _fake)


def _style_blocks() -> list[str]:
    """全部样式段＝从**选择表**派生，不手写第二枚名册（席简报第 4 条的规矩；
    失效形态 244＝靠硬抄常量名册的锁对新常量天生隐形）。"""
    return sorted({str(block) for block in chat.RP_STYLE_BLOCKS.values()})


def _permission_clause(block: str, marker: str) -> str:
    """取「许可半句」＝分界枚之前那段。分界枚缺席 ⇒ 整段当许可判（**只会更严**，
    且下面那枚在场守卫当场红——不许静默退化成不判）。"""
    permission, found, _ban = block.partition(marker)
    assert found, f"许可/禁令分界枚 {marker!r} 不在文案里 ⇒ 两截分不开，判据将退化成整段扫"
    return permission


def _ban_clause(block: str, marker: str) -> str:
    _permission, found, ban = block.partition(marker)
    assert found, f"许可/禁令分界枚 {marker!r} 不在文案里"
    return found + ban


def _screen_hit_terms(text: str) -> list[str]:
    """按群聊出站那把真尺统计命中的**规则名**（只回名字，断言里不留原文）。"""
    return [label for label, pattern in _PUBLIC_OUTPUT_UNSAFE if pattern.search(text)]


# ================================================================ ① 轴读数 → 样式段选择


def test_axis_tokens_are_agreed_between_the_axis_owner_and_the_injection_seam() -> None:
    """轴心的两枚取值与注入缝读的**必须逐字相同**（不同＝静默把 scene 收进只说话）。"""
    scene = str(cr.NARRATION_MODE_SCENE)
    speech = str(cr.NARRATION_MODE_SPEECH)
    assert chat.NARRATION_MODE_SCENE == scene, (
        f"轴心 scene＝{scene!r}，注入缝读的是 {chat.NARRATION_MODE_SCENE!r}"
    )
    assert chat.NARRATION_MODE_SPEECH == speech, (
        f"轴心 speech＝{speech!r}，注入缝读的是 {chat.NARRATION_MODE_SPEECH!r}"
    )
    assert scene != speech
    # 轴心的缺省也必须是 speech（G-1 裁"默认只说话"）——缺省漂了，本文件所有缺省腿都白测
    assert cr.NARRATION_MODE_DEFAULT == speech


def test_selection_table_covers_both_modes_times_both_scopes() -> None:
    """选择表必须**全覆盖**（两档 × 亲密/非亲密），且每格都是一段带段落头的散文。

    表驱动＝没有嵌套 ad-hoc 分支。表里有几格、有几段全部现算，本文件不抄数（规则 10）。
    """
    scene, speech = str(cr.NARRATION_MODE_SCENE), str(cr.NARRATION_MODE_SPEECH)
    assert set(chat.RP_STYLE_BLOCKS) == {
        (scene, True),
        (scene, False),
        (speech, True),
        (speech, False),
    }
    for (mode_value, intimate), block in chat.RP_STYLE_BLOCKS.items():
        assert isinstance(block, str) and block.startswith("【"), (
            f"样式段 (mode={mode_value!r}, intimate={intimate}) 不是带段落头的散文"
        )
    assert len(_style_blocks()) >= 3, "样式段总数少于三块＝新段根本没挂进表"


def test_unknown_axis_value_fails_closed_to_speech() -> None:
    """认不出的轴值一律收到「只说话」那一格——放宽只能由裁定带来，不能由笔误带来。"""
    speech_only = chat.resolve_rp_style_block("werewolf", intimate=True)
    assert speech_only == chat.RP_STYLE_BLOCKS[(str(cr.NARRATION_MODE_SPEECH), True)]
    assert speech_only is not chat.INTIMATE_RP_STYLE_INSTRUCTION


def test_intimate_mode_without_a_narration_pin_opens_the_scene_axis() -> None:
    """H-1＝甲（2026-10-04 晚裁定「开'亲密'的话，就给 scene 场景」，真实链路）。

    改写本件的旧判据（"只开亲密档、没钉描写档 ⇒ 只说话"）成文于 **H-1 未裁**那几天：
    裁定落地后这一格的正确答案翻了——亲手把亲密档推上去，就同时拿到铺开写的场景。
    收回的那条路是她自己点名的 `/bot 描写 speech`（本轮明示／持久钉仍是**更高**的优先级，
    下面那枚改写的标签锁判的就是"她说了只说话"那一格照旧只说话；轴心的优先级锁
    `tests/test_narration_axis_command.py::test_speech_pin_does_not_grant_even_under_an_intimate_admin_pin`
    钉的是同一件事的两端）。
    🔴 没被放宽的两格（防过修）：**自动腿仍不授予**——Master Love 名单派生与好感度达档
    自动都不在授予面上，它们这一轮拿的还是日常只说话段（`test_ungranted_master_love_turn_still_carries_no_narration_tag`
    ／`test_axis_swap_leaves_the_relation_tone_leg_untouched` 逐字判着），五维段只授予
    "人亲手推动"那几支。
    """
    cfg = _config()
    session = "private:nar-axis-intimate-speech"
    _open_intimate(session, cfg)
    joined, _result = _one_turn(session, cfg)
    assert _section_header(chat.INTIMATE_RP_STYLE_INSTRUCTION) in joined
    assert _section_header(chat.SPEECH_ONLY_STYLE_INSTRUCTION) not in joined
    assert "动作、神态、呼吸、触感、心理" in joined


def test_intimate_scene_keeps_the_existing_five_dimension_block_byte_for_byte() -> None:
    """亲密 + `scene`（真实链路：开档＋钉档）⇒ 仍用现役五维段，且**逐字节**对得上在册值。

    来历（台账 #76）：这段散文被改写过两次，两次都是裁定点名要的——
    ①2026-10-03/04 让**首格括注不自报分级标签**（标签词一旦回到文本里，群聊出站那把尺
      命中即整条丢 ⇒「她开了却什么都收不到」）；
    ②2026-10-04 深夜 I-1 要环境**被交代**并说出"那是什么样的美"（现值 `b23affd3…`，
      前值 `d3e46c2c…`；许可范围五维一字未动，只补了环境那一句，且那句里**没有**任何
      人格名物——名物由人格正文每轮供给，切人格自动换一套）。
    用 sha 而不是 `in`：`in` 只看得到子串，改一个标点也照样绿；sha 看的是整段。
    ⚠ 台账 #76★：哈希门在 HEAD 轴本就红（入库未重录），判漂移只读看清单。
    """
    assert (
        hashlib.sha256(chat.INTIMATE_RP_STYLE_INSTRUCTION.encode("utf-8")).hexdigest()
        == "b23affd37c788f26f17f964e0a1efc32ba73e1dbdf8221fe86ed0ba61428c4e1"
    ), "五维段被改写了：请连同本锁一起重录，并确认改写没收窄许可范围"
    cfg = _config()
    session = "private:nar-axis-intimate-scene"
    _open_intimate(session, cfg)
    _pin_narration(session, cfg, cr.NARRATION_MODE_SCENE)
    joined, _result = _one_turn(session, cfg)
    assert _section_header(chat.INTIMATE_RP_STYLE_INSTRUCTION) in joined
    assert _section_header(chat.NORMAL_SCENE_STYLE_INSTRUCTION) not in joined
    assert _section_header(chat.SPEECH_ONLY_STYLE_INSTRUCTION) not in joined


def test_normal_mode_scene_gets_the_new_scene_block() -> None:
    """G-1（真实链路）：普通模式钉了 `scene` ⇒ 拿**新的日常场景段**，既不是五维段也不是只说话段。"""
    cfg = _config()
    session = "private:nar-axis-normal-scene"
    _pin_narration(session, cfg, cr.NARRATION_MODE_SCENE)
    joined, _result = _one_turn(session, cfg)
    assert _section_header(chat.NORMAL_SCENE_STYLE_INSTRUCTION) in joined
    assert _section_header(chat.INTIMATE_RP_STYLE_INSTRUCTION) not in joined
    assert _section_header(chat.SPEECH_ONLY_STYLE_INSTRUCTION) not in joined
    assert _section_header(chat.NORMAL_NO_ACTION_INSTRUCTION) not in joined


def test_scene_without_the_grant_never_reaches_a_scene_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """轴说 `scene` 而那把尺没点头 ⇒ 一律回落只说话（防御腿：授予面之外没有第二条路）。

    真实链路造不出这枚读数（轴心自己会 fail-closed），所以这一枚用 monkeypatch 注入缝
    读的那一枚 dict；它判的是**注入缝自己**收到矛盾读数时的行为，不判优先序。
    """
    non_granting = _non_granting_sources()
    assert non_granting, "现算不到任何不授予来源＝尺被放宽了，本锁无从下判"
    _install_axis(
        monkeypatch,
        mode="intimate",
        source=non_granting[0],
        narration_mode=cr.NARRATION_MODE_SCENE,
        narration_source=non_granting[0],
    )
    joined, result = _one_turn("private:nar-axis-scene-ungranted", _config())
    assert _section_header(chat.NORMAL_NO_ACTION_INSTRUCTION) in joined
    for block in (
        chat.INTIMATE_RP_STYLE_INSTRUCTION,
        chat.NORMAL_SCENE_STYLE_INSTRUCTION,
        chat.SPEECH_ONLY_STYLE_INSTRUCTION,
    ):
        assert _section_header(block) not in joined
    assert _narration_tags(result) == [], "未授予的轮次拿到了授予标签"


# ================================================================ ② G-4＝乙：普通场景段的身体面边界


def test_normal_scene_block_permits_the_four_dimensions_and_appearance_as_impression() -> None:
    """普通模式 `scene` 的**许可半句**必须点名四维＋外貌＋**衣着**，且一个身体细部词都不许有。

    许可／禁令两截用 chat.py 交出的分界枚切（`NORMAL_SCENE_BAN_CLAUSE_MARKER`）：
    禁令那一截按本仓家规**必须**点名它禁的是哪几样（口径同成对锁读
    `NORMAL_NO_ACTION_INSTRUCTION` 禁令本体那半句），整段扫词会把禁令里的名字误当许可。
    G-4＝乙（2026-10-04 深夜「把衣着和环境也都写上」）之后，衣着这一类**归许可**，
    所以这里两头都判：许可半句少了衣着＝乙 没落地；身体细部词表（`SCENE_CORPORAL_TERMS`
    真身，本件不抄第二份）里任何一枚长进许可半句＝界线被越过。
    """
    permission = _permission_clause(
        chat.NORMAL_SCENE_STYLE_INSTRUCTION, chat.NORMAL_SCENE_BAN_CLAUSE_MARKER
    )
    for dimension in _SCENE_DIMENSIONS:
        assert dimension in permission, f"许可半句没准写「{dimension}」＝G-4乙 少了一维"
    assert any(
        term in permission for term in chat.NORMAL_SCENE_CLOTHING_TERMS
    ), "许可半句没点名衣着这一类 ⇒ G-4乙 没落地（她点名的『衣着』被漏写）"
    for term in chat.SCENE_CORPORAL_TERMS:
        assert term not in permission, f"许可半句出现身体细部词「{term}」⇒ G-4乙 的界线被越过"
    # 注毒自证：把一枚身体细部词塞进许可半句，判据必须当场失效
    poisoned = permission + f"她的{chat.SCENE_CORPORAL_TERMS[0]}也值得一写。"
    assert any(word in poisoned for word in chat.SCENE_CORPORAL_TERMS), (
        "注毒后仍判得出「无身体面词」＝词表是空表，本锁在空跑"
    )


def test_normal_scene_ban_clause_actually_names_the_corporal_axis() -> None:
    """禁令半句必须**点名**禁的是落在身体上的细部，且一枚衣着词都不许再出现在那里。

    G-4＝乙 之后这一腿是双刃的：没点名＝界线是句空话；把衣着留在禁令里＝与许可半句
    同轮拆台（那正是这半道裁定要改的东西）。
    """
    ban = _ban_clause(
        chat.NORMAL_SCENE_STYLE_INSTRUCTION, chat.NORMAL_SCENE_BAN_CLAUSE_MARKER
    )
    named = [term for term in chat.SCENE_CORPORAL_TERMS if term in ban]
    assert named, "禁令半句没点名身体细部词表 ⇒ G-4乙 的边界只是句空话"
    still_banned_clothing = [term for term in chat.NORMAL_SCENE_CLOTHING_TERMS if term in ban]
    assert not still_banned_clothing, f"禁令半句还在禁衣着这一类 {still_banned_clothing}"
    emptied = ban
    for term in chat.SCENE_CORPORAL_TERMS:
        emptied = emptied.replace(term, "", 1)
    assert not any(term in emptied for term in named), (
        "抹掉点名却没让判据失效＝本锁在空跑"
    )


def test_corporal_axis_is_the_real_difference_between_the_two_scene_blocks() -> None:
    """身体细部词表必须**真的**画在两段的分界上：亲密段许可它，普通场景段禁它。

    这张词表不是"随手挑几个词"（那样它会悄悄漂成一枚与散文无关的清单）：它的证人是
    现役五维段那句「彼此的形貌与衣着」里的**形貌**（衣着那一半自 G-4＝乙 起两段都许可，
    不再充当分界）。证人不在 ⇒ 词表与实际许可已脱钩 ⇒ 红。
    """
    assert any(
        term in chat.INTIMATE_RP_STYLE_INSTRUCTION for term in chat.SCENE_CORPORAL_TERMS
    ), "五维段里找不到身体细部词表的任何一枚 ⇒ 词表已与实际许可脱钩"
    normal_permission = _permission_clause(
        chat.NORMAL_SCENE_STYLE_INSTRUCTION, chat.NORMAL_SCENE_BAN_CLAUSE_MARKER
    )
    for term in chat.SCENE_CORPORAL_TERMS:
        assert term not in normal_permission
        assert term not in chat.SPEECH_ONLY_STYLE_INSTRUCTION


def test_new_blocks_carry_no_red_line_lexicon_anywhere() -> None:
    """每一段样式文案对**红线机器面**零命中：性语境尺、体态尺、R-18 精确词表。

    R-18 六硬线写死在人格文件与 affinity 态度文本里（规则 8），本席一处都不改、也不削弱。
    普通模式 `scene` 的边界是**结构性**的（不许可身体面描写），不是另写一套分级话术
    ⇒ 这三把尺上必须一个词都没碰到。需要边界措辞时保持"非身体化"口径，不发明 R-18 话术。
    """
    for block in _style_blocks():
        assert not _SEXUAL_CONTEXT_RE.search(block), "样式段带性语境词面 ⇒ 撞六硬线词表"
        assert not _BODY_TYPE_PATTERN.search(block), "样式段带体态词面 ⇒ 撞幼态 fail-closed 尺"
        hit = [term for term in _R18_TERMS if term in block]
        assert not hit, f"样式段带 R-18 精确词表 {hit}"


def test_speech_block_bans_every_scene_dimension() -> None:
    """「只说话」那段必须把四维**逐一点名禁掉**（她 09-28 原话「普通档只是说话」）。

    「语言」**不在**四维表里：这段的立身句就是"只用说话来回应"，禁它＝要求它禁掉自己的
    正文（理由在册于 `test_reply_policy_permanent.py` 的 `_SCENE_DIMENSIONS` 上方，不重抄）。
    """
    block = chat.SPEECH_ONLY_STYLE_INSTRUCTION
    for dimension in _SCENE_DIMENSIONS:
        assert dimension in block, f"只说话段没点名禁「{dimension}」"
    permission = _permission_clause(block, chat.SPEECH_ONLY_BAN_CLAUSE_MARKER)
    assert not any(
        term in permission for term in _SCENE_DIMENSIONS
    ), "只说话段的许可半句里长出了描写维度 ⇒ 与禁令自相拆台"


def test_four_headers_are_pairwise_distinct() -> None:
    """四段各有自己的头——互斥判据（`X not in joined`）的前提；同头＝那些负锁全成空判。"""
    headers = [_section_header(block) for block in _style_blocks()]
    assert len(headers) == len(set(headers)), f"样式段段落头撞车：{headers}"


# ================================================================ ②′ I-1：环境必须被交代（2026-10-04 深夜）


def test_both_scene_cells_instruct_the_environment_and_the_beauty_judgement() -> None:
    """两格 `scene` 都得**交代周遭**，并且说出"那是什么样的美"（I-1 的两判据）。

    她原话：scene 要「交代周遭环境是什么，以及到底是什么样的美」。席 sceneimagery 现算的
    缺口＝日常 `scene` 段**一个字的环境都没有**，亲密段只有三枚括注名词、没有那一条判据。
    判据落点＝`chat.py::SCENE_ENVIRONMENT_MARKER` 那枚短标记（**标记由 chat.py 交出**，
    本件不抄第二份散文），两格 `scene` 都必须带上它，两格 `speech` 都必须不带它
    （只说话那两格是**禁令侧**：环境留到描写档打开之后再铺开）。
    """
    scene_cells = {
        key: block for key, block in chat.RP_STYLE_BLOCKS.items() if key[0] == cr.NARRATION_MODE_SCENE
    }
    speech_cells = {
        key: block for key, block in chat.RP_STYLE_BLOCKS.items() if key[0] != cr.NARRATION_MODE_SCENE
    }
    assert scene_cells and speech_cells, "选择表少了某一侧的格子 ⇒ 本件无从判"
    marker = chat.SCENE_ENVIRONMENT_MARKER
    assert 0 < len(marker) < 40, f"分界／标记枚要短（{marker!r}），长过 40 字会被名册当独立段扫"
    for key, block in scene_cells.items():
        assert marker in block, f"scene 格 {key} 没交代环境＝I-1 那一格还空着"
        permission = _permission_clause(block, marker)
        assert len(permission) > 0, f"scene 格 {key} 的许可半句是空串＝环境句被当成了禁令"
    for key, block in speech_cells.items():
        assert marker not in block, f"speech 格 {key} 出现了环境许可句 ⇒ 与它自己的禁令拆台"


def test_environment_reaches_the_model_and_its_nouns_come_from_the_persona_text(tmp_path: Path) -> None:
    """注入面实测（离线）：`scene` 那一轮的环境句**真到了模型眼前**，而名物来自人格正文。

    两条分开判，因为病根是两条：
    ① 文案写了却没进 prompt（分区被裁／段没挂进表）⇒ 拿现算的 system 段判；
    ② 代码替人格说话＝把守岸人的名物写死进样式段，切人格后全绿却失真（她原话
       「要跟着人格人设和 BOT 有关，因为我后面可能会切换人格」）。这一枚用**合成**人格正文
       （两枚盘上不存在的杜撰名物）现算：名物出现在 prompt 里、却**不在**任何样式段常量里
       ⇒ 供应那条腿长在人格侧，不是长在代码侧。真身的意象族名另有那枚在册锁
       （`test_reply_style_imagery_default.py::test_imagery_family_names_are_not_hardcoded_in_code`）判。
    """
    invented = ("盐径灯炉", "潮钟与碑")
    persona_text = "意象只用与你自己相关的：" + "、".join(invented) + "。禁止天马行空乱用。"
    cfg = _config()
    session = "private:nar-axis-env-scene"
    _pin_narration(session, cfg, cr.NARRATION_MODE_SCENE)
    provider = _CapturingProvider()
    message = _message(session)
    base = _context(session)
    context = base.model_copy(
        update={
            "persona": base.persona.model_copy(update={"raw_text": persona_text, "identity": persona_text})
        }
    )
    chat.build_chat_result(
        message,
        _decision(message),
        context,
        llm_provider=provider,
        content_route_config=cfg,
    )
    joined = _system_join(provider)
    assert chat.SCENE_ENVIRONMENT_MARKER in joined, "环境判据没进这一轮的 prompt＝写了等于没写"
    for noun in invented:
        assert noun in joined, f"{noun} 没进 prompt＝人格正文那条供应腿断了"
        for block in chat.RP_STYLE_BLOCKS.values():
            assert noun not in block, f"杜撰名物 {noun} 长在样式段里＝代码替人格说话"
    # 负面：只说话那一轮不许拿到环境许可（禁令侧照旧）
    plain = _one_turn("private:nar-axis-env-speech", _config())
    assert chat.SCENE_ENVIRONMENT_MARKER not in plain


# ================================================================ ③ 篇幅：scene 只有经授予尺才到顶格


def test_scene_reaches_the_top_tier_and_only_through_the_grant() -> None:
    """`scene` 那一轮的长度指令＝登记表顶格档；**未授予**时同一条轴读数也升不上去。

    数值全从登记表取（本文件一个数字都不抄，规则 10）。两态都走真实链路：
    普通模式钉了 scene ⇒ 顶格；轴说 scene 而来源不在授予面上（防御腿）⇒ 不升。
    """
    cfg = _config()
    session = "private:nar-axis-len-normal-scene"
    _pin_narration(session, cfg, cr.NARRATION_MODE_SCENE)
    top = chat.REPLY_LENGTH_TIERS[chat._REPLY_TIER_TOP_ID]
    joined, _result = _one_turn(session, cfg)
    line = _length_line_of(joined)
    assert f"当前档＝{top.label_cn}" in line, f"授予+scene 没到顶格档：{line}"
    assert f"不少于 {top.min_chars} 字" in line and f"不超过 {top.max_chars} 字" in line, line


def test_intimate_scene_reaches_the_top_tier_too() -> None:
    """亲密 + scene ⇒ 顶格档照旧（§76/S17 那条裁定在新轴下的正位：它挂的是"铺开写"）。"""
    cfg = _config()
    session = "private:nar-axis-len-intimate-scene"
    _open_intimate(session, cfg)
    _pin_narration(session, cfg, cr.NARRATION_MODE_SCENE)
    joined, _result = _one_turn(session, cfg)
    top = chat.REPLY_LENGTH_TIERS[chat._REPLY_TIER_TOP_ID]
    line = _length_line_of(joined)
    assert f"当前档＝{top.label_cn}" in line, line
    assert _section_header(chat.INTIMATE_RP_STYLE_INSTRUCTION) in joined


def test_scene_without_grant_does_not_move_the_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """简报第 2 条的反面：`mode` 说 scene 但**尺没点头** ⇒ 那一行逐字等于未升格的读数。

    这就是 `test_reply_length_tier.py::test_scene_tier_is_only_reachable_through_the_
    narration_grant` 那条锁在新轴下**仍然咬得住**的证明——本席没加第二条长度规则，
    升格整条腿仍挂在同一把尺上（矩阵一字未动，见下面那枚借真身复跑的锁）。
    """
    non_granting = _non_granting_sources()
    _install_axis(
        monkeypatch,
        mode="intimate",
        source=non_granting[0],
        narration_mode=cr.NARRATION_MODE_SCENE,
        narration_source=non_granting[0],
    )
    message = _message("private:nar-axis-len-ungranted")
    joined, _result = _one_turn("private:nar-axis-len-ungranted", _config())
    line = _length_line_of(joined)
    top = chat.REPLY_LENGTH_TIERS[chat._REPLY_TIER_TOP_ID]
    assert top.label_cn not in line, f"未授予的轮次被抬进了顶格档：{line}"
    assert line == chat.reply_length_guidance_text(
        chat.resolve_reply_length_tier("", message.plain_text)
    ), "未授予轮的长度指令不再是那条单一真身 ⇒ 长出了第二把尺"


def test_speech_turn_keeps_today_tier_resolution() -> None:
    """`speech` 那一轮**今天的选档一字不动**（简报第 2 条），且拿不到顶格档的交付面。

    反向保护：把长度升格挂在"进了亲密档"而不是"scene"上，同一轮就会读到只说话段＋
    铺写交付面（那一段散文点名的就是周遭／动作／触感）⇒ 两句拆台话（本仓老坑）。
    H-1＝甲（2026-10-04 晚）之后"亲手开了亲密"这一格会直接拿到 `scene`，所以这里要造
    出**真的说了"只说话"**的那一轮＝开亲密＋本人把描写钉收回 `speech`（判据一字未松，
    只是夹具跟着裁定换了一格——旧夹具今天测的是 scene 轮，测不到 speech 轮的选档）。
    """
    cfg = _config()
    session = "private:nar-axis-speech-tier"
    _open_intimate(session, cfg)
    _pin_narration(session, cfg, cr.NARRATION_MODE_SPEECH)
    message = _message(session, text="那你会怎么陪我。")
    joined, _result = _one_turn(session, cfg)
    line = _length_line_of(joined)
    assert line == chat.reply_length_guidance_text(
        chat.resolve_reply_length_tier("", message.plain_text)
    ), f"speech 轮的档位被动了：{line!r}"
    top = chat.REPLY_LENGTH_TIERS[chat._REPLY_TIER_TOP_ID]
    assert _section_header(chat.SPEECH_ONLY_STYLE_INSTRUCTION) in joined
    assert f"当前档＝{top.label_cn}" not in line


def test_scene_tier_still_unreachable_from_the_global_matrix() -> None:
    """**借那把既有的锁现跑一次**（不复写判据）：全局长度仍到不了铺写档。

    `test_reply_length_tier.py::test_scene_tier_is_only_reachable_through_the_narration_grant`
    判的是「登记表矩阵没有任何一格指向顶格档」——新轴挂在**授予腿**上、与矩阵无关，
    所以它既不空转也不该被放宽。这里直接调用那一件真身：它若红，本文件当场红。
    """
    _load_sibling("test_reply_length_tier.py").test_scene_tier_is_only_reachable_through_the_narration_grant()


class _MultiCallProvider:
    """记录**每一跳**的 messages（出口地板腿的重问是第二跳）并恒回一条短答案。

    短答案（11 字）必然低于任何一档的下限 ⇒ 一定触达地板腿，于是"地板追的是哪一档"
    就写在它重问那跳的那句指令里——这是唯一能把两把尺**现算**比对出来的形状。
    """

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def generate(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> LLMReply:
        self.calls.append([dict(item) for item in messages])
        return LLMReply(text="嗯，我在听。你慢慢说。", provider="fake", model="m")


def _run_multicall(session: str, cfg: object) -> list[list[dict[str, str]]]:
    provider = _MultiCallProvider()
    message = _message(session)
    chat.build_chat_result(
        message,
        _decision(message),
        _context(session),
        llm_provider=provider,
        content_route_config=cfg,
    )
    return provider.calls


def _prompt_line_tier_label(messages: list[dict[str, str]]) -> str:
    prefix = chat.TIER_LINE_PREFIX
    lines = [
        line
        for item in messages
        if str(item.get("role") or "") == "system"
        for line in str(item.get("content") or "").splitlines()
        if line.startswith(prefix)
    ]
    assert len(lines) == 1, f"长度指令必须恰好一条，实得 {len(lines)}"
    return lines[0].split("当前档＝", 1)[1].split("）", 1)[0]


def _floor_chase_tier_label(messages: list[dict[str, str]]) -> str:
    for item in messages:
        content = str(item.get("content") or "")
        if "低于本轮生效长度档" in content:
            return content.split("低于本轮生效长度档（", 1)[1].split("，", 1)[0]
    raise AssertionError("重问那跳里没有地板指令句＝地板腿根本没跑")


def test_prompt_line_and_exit_floor_share_the_axis_ruler() -> None:
    """两把尺必须同档：提示词那一行说什么档，出口地板就追什么档（三态现算）。

    来历：`_reply_length_floor_leg` 自己的注释写着"免得长成提示词要适中、地板只追到
    简洁的两把尺"。第五根轴把升格谓词从"进了亲密档"换成"本轮铺开写"之后，**两条腿要
    一起换**——只换一条就会出现"只说话那一轮被出口追到 600 字场景铺写"的缺牙，
    而那一句正写着「动作、神态、心理与外貌一概不落笔」。本件按三态各跑一遍现算比对。
    """
    top = chat.REPLY_LENGTH_TIERS[chat._REPLY_TIER_TOP_ID]
    cases: list[tuple[str, str, object]] = []

    cfg_intimate_scene = _config()
    session_intimate_scene = "private:nar-axis-twoflegs-intimate-scene"
    _open_intimate(session_intimate_scene, cfg_intimate_scene)
    _pin_narration(session_intimate_scene, cfg_intimate_scene, cr.NARRATION_MODE_SCENE)
    cases.append((session_intimate_scene, "亲密＋scene", cfg_intimate_scene))

    cfg_intimate_speech = _config()
    session_intimate_speech = "private:nar-axis-twoflegs-intimate-speech"
    _open_intimate(session_intimate_speech, cfg_intimate_speech)
    # H-1＝甲（2026-10-04 晚）之后"开了亲密而什么都不说"＝scene 轮，这一格只能由她自己
    # 把描写收回 speech 造出来（判据、比对的三态形状、两把尺同档那条都一字未动）。
    _pin_narration(session_intimate_speech, cfg_intimate_speech, cr.NARRATION_MODE_SPEECH)
    cases.append((session_intimate_speech, "亲密＋钉 speech", cfg_intimate_speech))

    cfg_normal_scene = _config()
    session_normal_scene = "private:nar-axis-twoflegs-normal-scene"
    _pin_narration(session_normal_scene, cfg_normal_scene, cr.NARRATION_MODE_SCENE)
    cases.append((session_normal_scene, "普通＋scene", cfg_normal_scene))

    seen_scene = False
    for session_key, label, cfg in cases:
        calls = _run_multicall(session_key, cfg)
        assert len(calls) >= 2, f"{label}：地板腿没跑＝本件没比对到两把尺"
        prompt_label = _prompt_line_tier_label(calls[0])
        floor_label = _floor_chase_tier_label(calls[1])
        assert prompt_label == floor_label, (
            f"{label} 两把尺分叉：提示词那一行＝{prompt_label!r}，出口地板追＝{floor_label!r}"
        )
        if label.endswith("speech"):
            assert prompt_label != top.label_cn, (
                f"{label}：只说话的那轮拿到了顶格档 {prompt_label!r}"
            )
        else:
            seen_scene = True
            assert prompt_label == top.label_cn, (
                f"{label}：scene 那一轮没走到顶格档（现算＝{prompt_label!r}）"
            )
    assert seen_scene, "三态里一枚 scene 都没跑到＝本件空跑"


# ================================================================ ④ 审计标签：同一枚标签加一轴


def _narration_tags(result: object) -> list[str]:
    return [
        str(tag)
        for tag in (getattr(result, "audit_tags", None) or [])
        if str(tag).startswith("rp_narration:")
    ]


def test_granted_scene_turn_tags_the_narration_axis() -> None:
    """授予轮的标签加一轴读数 `nar=`——同一枚标签、同一个出口，不新增日志面。"""
    cfg = _config()
    session = "private:nar-axis-tag-scene"
    _open_intimate(session, cfg)
    _pin_narration(session, cfg, cr.NARRATION_MODE_SCENE)
    joined, result = _one_turn(session, cfg)
    tags = _narration_tags(result)
    assert len(tags) == 1, f"授予轮的叙述标签应有恰好一枚：{tags}"
    tag = tags[0]
    assert re.fullmatch(
        rf"rp_narration:[a-z0-9]+:[a-z0-9]+:grant=1:nar={cr.NARRATION_MODE_SCENE}", tag
    ), tag
    assert _section_header(chat.INTIMATE_RP_STYLE_INSTRUCTION) in joined
    assert "user-nar" not in tag and " " not in tag and "\n" not in tag


def test_granted_intimate_on_speech_still_tags_with_nar_speech() -> None:
    """拿到亲密授予、但**本人把描写收回 speech** ⇒ 标签照旧在场、`nar=speech`。

    这格是旧写法最漏的一支：标签只挂在亲密段上时，"她开了亲密档却只说话"与"她根本没
    拿到授予"在队列行上长得一模一样，审计只能从字数反推。
    H-1＝甲（2026-10-04 晚）之后"开了亲密却只说话"这一格**只能由她自己说出来**
    （`/bot 描写 speech`，持久钉或本轮明示）——旧写法靠"什么都不做"就能造出这一格，
    今天什么都不做会拿到 `scene`，所以这里把收回那一句真的说出来；判据（两态可分辨、
    `nar=` 跟着轴走）一字未松。
    """
    cfg = _config()
    session = "private:nar-axis-tag-speech"
    _open_intimate(session, cfg)
    _pin_narration(session, cfg, cr.NARRATION_MODE_SPEECH)
    _joined, result = _one_turn(session, cfg)
    tags = _narration_tags(result)
    assert len(tags) == 1, f"授予轮的叙述标签应有恰好一枚：{tags}"
    assert re.fullmatch(
        rf"rp_narration:intimate:[a-z0-9]+:grant=1:nar={cr.NARRATION_MODE_SPEECH}", tags[0]
    ), tags[0]


def test_normal_mode_scene_tags_with_nar_scene() -> None:
    """普通模式经描写钉拿到 `scene` ⇒ 同一枚标签留痕（`grant=` 那一格答的是亲密授予，
    `nar=` 答的是这一轴——两枚一起看就知道是哪种授予，字段语义都没被改宽）。"""
    cfg = _config()
    session = "private:nar-axis-tag-normal-scene"
    _pin_narration(session, cfg, cr.NARRATION_MODE_SCENE)
    _joined, result = _one_turn(session, cfg)
    tags = _narration_tags(result)
    assert len(tags) == 1, tags
    assert re.fullmatch(
        rf"rp_narration:normal:[a-z0-9]+:grant=0:nar={cr.NARRATION_MODE_SCENE}", tags[0]
    ), tags[0]


def test_ungranted_master_love_turn_still_carries_no_narration_tag() -> None:
    """未授予轮（ML 自动档）不带走「授予才有」的字段——新轴下这一条一个字不许松。"""
    cfg = _config(bot_master_love_enabled=True, bot_master_love_admins=["user-nar"])
    _joined, result = _one_turn("private:nar-axis-tag-ml", cfg)
    assert _narration_tags(result) == []


def test_axis_swap_leaves_the_relation_tone_leg_untouched() -> None:
    """**换描写档只换描写维度**（她 09-28 那句「换了个档，结果文风全部都变了，那肯定不对」）。

    量具刻意选 Master Love：它是"只给语气、不给叙述授予"的那一支（§76 裁定的原形），
    所以两态之间**只有样式段与长度档**该变——语气那一格必须逐字在场、一字不变。
    两态各自拿到的段也对得上：ML＋钉 `scene` ⇒ 日常场景段（G-1 那一格，与"她进没进亲密档"
    无关），ML＋缺省 ⇒ 日常只说话段。
    """
    ml_cfg = {
        "bot_master_love_enabled": True,
        "bot_master_love_admins": ["user-nar"],
    }
    cfg_scene = _config(**ml_cfg)
    session_scene = "private:nar-axis-tone-scene"
    _pin_narration(session_scene, cfg_scene, cr.NARRATION_MODE_SCENE)
    joined_scene, result_scene = _one_turn(session_scene, cfg_scene)

    cfg_speech = _config(**ml_cfg)
    joined_speech, _result = _one_turn("private:nar-axis-tone-speech", cfg_speech)

    # ① 语气格两态都在场且就是那一枚真身（本波一格都没动它）
    assert cr.MASTER_LOVE_INSTRUCTION in joined_scene
    assert cr.MASTER_LOVE_INSTRUCTION in joined_speech
    # ② 样式段按轴分岔：ML＋scene 拿日常场景段，ML＋缺省 拿日常只说话段
    assert _section_header(chat.NORMAL_SCENE_STYLE_INSTRUCTION) in joined_scene
    assert _section_header(chat.INTIMATE_RP_STYLE_INSTRUCTION) not in joined_scene
    assert _section_header(chat.NORMAL_NO_ACTION_INSTRUCTION) in joined_speech
    # ③ 长度档跟着**那把尺**走，不跟亲密态走：ML 从没拿到亲密叙述授予（grant=0），
    #    但描写钉给的是 `narration_pin`⇒ 这一轮照样升到顶格档。
    top = chat.REPLY_LENGTH_TIERS[chat._REPLY_TIER_TOP_ID]
    assert f"当前档＝{top.label_cn}" in _length_line_of(joined_scene)
    assert f"当前档＝{top.label_cn}" not in _length_line_of(joined_speech)
    tags = _narration_tags(result_scene)
    assert tags == [
        tag for tag in tags if tag.endswith(f":nar={cr.NARRATION_MODE_SCENE}")
    ], tags


# ================================================================ ⑤ 词界事故：新段也不自报标签


def test_no_block_self_reports_a_rating_label_in_its_header() -> None:
    """段落头与首格括注都不许自带分级标签名（§76 那处改写的纪律，扩到两块新段）。

    成因（台账 #76）：首格"（含…）"那种写法会被模型原样复述进正文，而群聊出站那把尺
    命中即整条丢 ⇒ 她在群里"什么都收不到"。判据用尺的**模式**扫段头两处结构，
    词表不在这儿重写（规则 10）。
    """
    for block in _style_blocks():
        head = block.split("】", 1)[0]
        first_parenthetical = ""
        match = re.search(r"（[^）]*）", block)
        if match and match.start() < len(head) + 40:
            first_parenthetical = match.group(0)
        for probe in (head, first_parenthetical):
            assert not _screen_hit_terms(probe), f"段头自带标签字样会被群聊尺整条丢：{probe!r}"


def test_every_style_block_is_screen_clean_and_poison_proof_runs_through_a_temp_copy() -> None:
    """选择表里**每一段**（含两块新段）对群聊出站尺零命中；注毒走 %TEMP% 副本往返。

    副本往返（写盘→读回→再过尺）证明的不是"内存里那串恰好干净"，而是这段文本落到文件
    里、被另一条通路读回来时仍不命中 ⇒ 排除任何"内存别名把毒吃掉"的空跑形态。
    """
    blocks = _style_blocks()
    assert len(blocks) >= 3
    for index, block in enumerate(blocks):
        assert _screen_hit_terms(block) == []
        work = _TEMP_WORK / "screen-poison"
        work.mkdir(parents=True, exist_ok=True)
        path = work / f"block-{index}.txt"
        path.write_text(
            block + _RP_HELPERS._one_literal_token_from_screen(), encoding="utf-8"
        )
        try:
            assert _screen_hit_terms(path.read_text(encoding="utf-8")), (
                "注毒写盘再读回仍不命中＝这把尺对本段是空跑的"
            )
        finally:
            path.unlink(missing_ok=True)


def test_screen_lock_roster_is_derived_not_hand_copied() -> None:
    """不变锁的枚举面＝选择表的值集；表里加一段，锁自动多扫一段（简报第 4 条的缺牙）。

    反向锁死"手写名册"那种写法：任何**挂进表里**的段都必在枚举面上；没挂进表的段
    压根注入不了（表是唯一选择口，见 `resolve_rp_style_block`），于是不需要在文案锁上
    多一行——枚举面与注入面从此不可能各行其是。
    """
    from_table = {str(block) for block in chat.RP_STYLE_BLOCKS.values()}
    assert set(_style_blocks()) == from_table
    for block_name in (
        "INTIMATE_RP_STYLE_INSTRUCTION",
        "NORMAL_NO_ACTION_INSTRUCTION",
        "NORMAL_SCENE_STYLE_INSTRUCTION",
        "SPEECH_ONLY_STYLE_INSTRUCTION",
    ):
        assert getattr(chat, block_name) in from_table, (
            f"{block_name} 没在选择表里 ⇒ 注入面与文案锁枚举面从此各行其是"
        )

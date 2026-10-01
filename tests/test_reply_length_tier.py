"""需求 18 第 9 项「回复长度分档（太短、有时不够详细）」的数值判据与活性锁。

席位 S-T-TIER-1（2026-09-26）。本件锁四件事，全部**跑到函数或跑到渲染**，
不许退化成「提示词里那句话在场」的字符串在场断言：

① 档位真身：三档各自的数值区间存在，且指引文本里的数值是从登记表**派生**的
   （改登记表 ⇒ 文本跟着改；把数值删掉 ⇒ 本件红）；
② 选档真身：四类问题（时效检索 / 知识问答 / 闲聊短句 / 报错确认）× 三种配置档
   的生效档由 `select_reply_length_tier` 逐个返回期望值（把 auto 那一腿改成永不
   命中 ⇒ 本件红）；
③ 执行面：从能力装配点一路到 system prompt，两支渲染分支（人设原文 / 字段重组）
   都真的把那行带数值的长度指令发出去（删掉渲染调用 ⇒ 本件红）；
④ 唯一真身：`chat.py` 里不许再有第二处手抄的长度散文或手抄字数——AST 门执法，
   并带一发注毒自证（把门本身打红才算门活着）。

另锁需求项 (d)：分档不许建立在一只读不到的键上（`bot_reply_detail` 必须是真
Config 字段；未知值归一为 auto 而不是静默变详细）。
"""

from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.runtime.question_intent import (
    QuestionIntent,
    classify_question_intent,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    RuntimeSettingsStore,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_PY = (
    _REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "capabilities"
    / "chat.py"
)

# ---- 四类问题的锚点样本（先钉住分类器今天的输出，再钉住分档） ----------------

TIMELY_TEXT = "英伟达股价现在多少"          # 时效检索 → WEB_SEARCH
KNOWLEDGE_TEXT = "守岸人与黑海岸是什么关系"  # 知识问答 → KNOWLEDGE_FIRST
SMALLTALK_TEXT = "你好"                     # 闲聊短句 → NEUTRAL / SMALL_TALK
ERROR_ACK_TEXT = "语音合成一直报错"          # 报错确认 → NEUTRAL / HOW_TO_TECHNICAL

_ANCHORS: dict[str, tuple[str, str, str]] = {
    # 问题类型 → (样本文本, 期望 intent, 期望 category)
    chat.REPLY_QTYPE_TIMELY: (TIMELY_TEXT, "web_search", "CURRENT_REAL_WORLD"),
    chat.REPLY_QTYPE_KNOWLEDGE: (
        KNOWLEDGE_TEXT,
        "knowledge_first",
        "LOCAL_KNOWLEDGE",
    ),
    chat.REPLY_QTYPE_SMALLTALK: (SMALLTALK_TEXT, "neutral", "SMALL_TALK"),
    chat.REPLY_QTYPE_ERROR_ACK: (ERROR_ACK_TEXT, "neutral", "HOW_TO_TECHNICAL"),
}


def _question_type_of(text: str) -> str:
    """走生产同一条判据链：文本 → 意图分类器 → 题型。"""
    decision = classify_question_intent(text)
    return chat.classify_reply_question_type(
        intent=decision.intent, category=decision.category
    )


# ============================ ① 档位真身：数值区间 ============================


def test_every_tier_carries_numeric_bounds_and_is_a_strict_ladder() -> None:
    tiers = [
        chat.REPLY_TIER_CONCISE,
        chat.REPLY_TIER_STANDARD,
        chat.REPLY_TIER_DETAIL,
    ]
    assert [tier.tier_id for tier in tiers] == ["concise", "standard", "detail"]
    for tier in tiers:
        assert tier.min_chars > 0, f"{tier.tier_id} 档没有下限 ⇒ 「太短」不可判"
        assert tier.max_chars == 0 or tier.max_chars > tier.min_chars
        assert tier.coverage.strip(), f"{tier.tier_id} 档只给了字数没给交付面"
        assert tier.label_cn.strip()
    # 严格阶梯：上限一档高过一档，否则「分档」只是三句不同的散文。
    assert (
        chat.REPLY_TIER_CONCISE.min_chars
        < chat.REPLY_TIER_STANDARD.min_chars
        < chat.REPLY_TIER_DETAIL.min_chars
    )
    assert chat.REPLY_TIER_STANDARD.max_chars and (
        chat.REPLY_TIER_STANDARD.max_chars < chat.REPLY_TIER_DETAIL.min_chars * 3
    ), "适中档上限高到吞掉详尽档 ⇒ 两档实际同一档"


def test_guidance_numbers_are_derived_from_the_registry_not_hand_written() -> None:
    """数值派生自登记表：把登记表换掉 ⇒ 文本跟着换（写死数字的实现对这句必红）。"""
    for tier_id, tier in chat.REPLY_LENGTH_TIERS.items():
        line = chat.reply_length_guidance_text(tier_id)
        assert str(tier.min_chars) in line
        assert line.startswith("回复长度分档")
        assert tier.coverage in line
        if tier.max_chars:
            assert f"不超过 {tier.max_chars} 字" in line
        else:
            assert "上不封顶" in line

    patched = dataclasses.replace(chat.REPLY_TIER_DETAIL, min_chars=480)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setitem(chat.REPLY_LENGTH_TIERS, "detail", patched)
        line = chat.reply_length_guidance_text("detail")
    assert "不少于 480 字" in line, "改登记表不改了文本 ⇒ 数值另有真身"
    assert "不少于 300 字" not in line


def test_unknown_tier_name_injects_no_length_instruction() -> None:
    """未知档名回空串（既有夹具里的 "brief" 走这一支），与旧散文分支同形。"""
    for value in ("", "brief", "详细", None):
        assert chat.reply_length_guidance_text(value) == ""


# ============================ ② 选档真身：题型 × 配置档 ============================


@pytest.mark.parametrize("qtype", sorted(_ANCHORS))
def test_anchor_texts_map_to_the_expected_question_type(qtype: str) -> None:
    text, intent_value, category = _ANCHORS[qtype]
    decision = classify_question_intent(text)
    assert decision.intent.value == intent_value, (
        f"锚点样本 {text!r} 的分类漂移了（{decision.intent.value}），"
        "先修样本归属再谈分档，别让判据挂在会变的地基上"
    )
    assert decision.category == category
    assert decision.intent is QuestionIntent(intent_value)
    assert _question_type_of(text) == qtype


def test_selection_matrix_matches_the_ruling_cell_by_cell() -> None:
    """四类问题 × 三档配置的期望值逐个断言（注毒任一格 ⇒ 本件红）。"""
    expected = {
        # (配置档, 题型) → 生效档
        ("auto", chat.REPLY_QTYPE_TIMELY): "detail",
        ("auto", chat.REPLY_QTYPE_KNOWLEDGE): "detail",
        ("auto", chat.REPLY_QTYPE_SMALLTALK): "standard",
        ("auto", chat.REPLY_QTYPE_ERROR_ACK): "standard",
        ("detail", chat.REPLY_QTYPE_TIMELY): "detail",
        ("detail", chat.REPLY_QTYPE_KNOWLEDGE): "detail",
        ("detail", chat.REPLY_QTYPE_SMALLTALK): "standard",
        ("detail", chat.REPLY_QTYPE_ERROR_ACK): "standard",
        ("concise", chat.REPLY_QTYPE_TIMELY): "concise",
        ("concise", chat.REPLY_QTYPE_KNOWLEDGE): "concise",
        ("concise", chat.REPLY_QTYPE_SMALLTALK): "concise",
        ("concise", chat.REPLY_QTYPE_ERROR_ACK): "concise",
    }
    for (mode, qtype), tier in expected.items():
        got = chat.select_reply_length_tier(detail_mode=mode, question_type=qtype)
        assert got == tier, f"配置 {mode} × 题型 {qtype} ⇒ 期望 {tier}，实得 {got}"


def test_tier_matrix_is_total_over_types_and_modes() -> None:
    """表必须全覆盖：漏一格就静默走兜底映射，等于那一型问题没判据。"""
    for qtype in chat.REPLY_QUESTION_TYPES:
        row = chat.REPLY_TIER_MATRIX.get(qtype)
        assert row is not None, f"题型 {qtype} 没进分档表"
        for mode in sorted(chat.REPLY_DETAIL_MODES):
            assert row.get(mode) in chat.REPLY_LENGTH_TIERS, f"{qtype}×{mode} 未登记"
    assert set(chat.REPLY_TIER_MATRIX) == set(chat.REPLY_QUESTION_TYPES)
    # 题型必须由分类器可达：登记了却永远选不到的行＝死判据。
    reached = {_question_type_of(_ANCHORS[q][0]) for q in _ANCHORS}
    assert reached <= set(chat.REPLY_QUESTION_TYPES)
    assert reached == {
        chat.REPLY_QTYPE_TIMELY,
        chat.REPLY_QTYPE_KNOWLEDGE,
        chat.REPLY_QTYPE_SMALLTALK,
        chat.REPLY_QTYPE_ERROR_ACK,
    }, "四类问题里有样本选不出对应档 ⇒ 该型问题今天没有可执行判据"


def test_unreachable_mode_and_unknown_values_degrade_to_auto_not_detail() -> None:
    """未知值归一为 auto（旧代码同形）；显式精简永不被判据悄悄抬回详细。"""
    assert chat.normalize_reply_detail_mode("fancy") == "auto"
    assert chat.normalize_reply_detail_mode("") == "auto"
    assert chat.normalize_reply_detail_mode("DETAIL") == "detail"
    assert chat.normalize_reply_detail_mode(None) == "auto"
    tier = chat.select_reply_length_tier(
        detail_mode="fancy", question_type=chat.REPLY_QTYPE_SMALLTALK
    )
    assert tier == chat.REPLY_TIER_STANDARD_ID, (
        "未知值被当成 detail ⇒ 一句「你好」也要求写详尽"
    )
    assert chat.select_reply_length_tier(
        detail_mode="fancy", question_type=chat.REPLY_QTYPE_KNOWLEDGE
    ) == chat.REPLY_TIER_DETAIL_ID


# ============================ ③ 执行面：一路到 system prompt ============================


def _prompt_for(text: str, *, raw_persona: str, reply_detail: str) -> str:
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        NullCharacterContextProvider,
    )

    context = NullCharacterContextProvider().build_context(
        "req-tier", "sender-tier", "private-sender-tier", text
    )
    context = context.model_copy(update={"context_budget": 12000, "reply_detail": reply_detail})
    context.persona.raw_text = raw_persona
    return chat.build_chat_prompt(context)[0]["content"]


@pytest.mark.parametrize("raw_persona", ["", "你是守岸人，人设原文必须保持不变。"])
def test_both_render_branches_emit_the_selected_numeric_tier(raw_persona: str) -> None:
    """两支渲染分支（人设原文 / 字段重组）必须发同一行带数值的长度指令。

    旧实现两处各抄一句散文、措辞还不同 ⇒ 同一条判据在生产与降级形态下不一致。
    """
    detail_prompt = _prompt_for(
        KNOWLEDGE_TEXT, raw_persona=raw_persona, reply_detail="auto"
    )
    assert "回复长度分档（当前档＝详尽）" in detail_prompt
    assert f"不少于 {chat.REPLY_TIER_DETAIL.min_chars} 字" in detail_prompt
    assert "不少于 12 字" not in detail_prompt

    small_prompt = _prompt_for(
        SMALLTALK_TEXT, raw_persona=raw_persona, reply_detail="auto"
    )
    assert "回复长度分档（当前档＝适中）" in small_prompt
    assert f"不超过 {chat.REPLY_TIER_STANDARD.max_chars} 字" in small_prompt
    assert "回复长度分档（当前档＝详尽）" not in small_prompt
    if raw_persona:
        assert raw_persona in detail_prompt, "长度指令挤掉了人设原文主体"


def test_concise_tier_is_only_reachable_by_an_explicit_pin() -> None:
    """人格一致性判据：题型自己绝不把回复判进简洁档。

    立论现身（2026-09-28 改口）：人格【回复长度】已撤成**让位条款**——长度只由本轮
    那一行档位说，且「一段话说完是日常默认的形、无论落在哪一档都绝不回半截话」。
    题型自选简洁档＝没人表态就被压到 ≤60 字，既违背她「默认别太长、但要把话说完」，
    也会让档位行与人格那句互相拆台。简洁档只有用户显式钉「精简」这一条路
    （想改口径只改矩阵那一格）。
    """
    for qtype in chat.REPLY_QUESTION_TYPES:
        assert chat.select_reply_length_tier(
            detail_mode="auto", question_type=qtype
        ) != chat.REPLY_TIER_CONCISE_ID, f"{qtype} 在 auto 下被压成简洁档"
        assert chat.select_reply_length_tier(
            detail_mode="detail", question_type=qtype
        ) != chat.REPLY_TIER_CONCISE_ID, f"{qtype} 在 detail 下被压成简洁档"
    assert chat.select_reply_length_tier(
        detail_mode="concise", question_type=chat.REPLY_QTYPE_KNOWLEDGE
    ) == chat.REPLY_TIER_CONCISE_ID
    # 适中档下限 ≥100＝她「默认不要太长，但可以有多句话」里「多句」的下界
    # （数值唯一真身＝REPLY_LENGTH_TIERS，改数值只改登记表那一处）。
    assert chat.REPLY_TIER_STANDARD.min_chars >= 100


def test_production_column_pinned_detail_still_tiers_by_question_type() -> None:
    """现网 `BOT_REPLY_DETAIL=detail` 钉死那一列也必须分档：

    知识题 ⇒ 详尽（有下限），寒暄 ⇒ 适中（不再与知识题共用同一句散文）。
    """
    knowledge = _prompt_for(KNOWLEDGE_TEXT, raw_persona="人格", reply_detail="detail")
    smalltalk = _prompt_for(SMALLTALK_TEXT, raw_persona="人格", reply_detail="detail")
    assert "当前档＝详尽" in knowledge
    assert "当前档＝适中" in smalltalk
    assert f"不少于 {chat.REPLY_TIER_STANDARD.min_chars} 字" in smalltalk


def _capability_prompt(text: str, *, reply_detail: str, override: str | None) -> str:
    """从能力装配点跑一遍：覆盖 → 归一 → context → 渲染，返回真进模型的提示词。"""
    from plugins.bot_unified_runtime.contracts import (
        BotDecision,
        CapabilityResult,
        IncomingMessage,
        SessionType,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        NullCharacterContextProvider,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
        StaticLLMProvider,
    )

    captured: dict[str, object] = {}

    def fake_build_chat_result(**kwargs):
        captured["mode"] = kwargs["context"].reply_detail
        captured["prompt"] = chat.build_chat_prompt(kwargs["context"])[0]["content"]
        return CapabilityResult(
            request_id=kwargs["message"].request_id, kind="text", body="ok"
        )

    monkey = pytest.MonkeyPatch()
    monkey.setattr(chat, "build_chat_result", fake_build_chat_result)
    try:
        settings = RuntimeSettingsStore(allow_no_gate=True)
        if override is not None:
            settings.set_override("BOT_REPLY_DETAIL", override)
        capability = chat.build_chat_capability(
            NullCharacterContextProvider(),
            StaticLLMProvider(),
            reply_detail=reply_detail,
            runtime_settings=settings,
        )
        message = IncomingMessage(
            platform="qq",
            adapter="nonebot",
            bot_id="b",
            session_id="private:tier-u",
            sender_id="tier-u",
            session_type=SessionType.PRIVATE,
            plain_text=text,
            mentions_bot=True,
        )
        decision = BotDecision(
            request_id=message.request_id,
            should_respond=True,
            mode="chat",
            trigger="private",
            capability_id="bot.chat",
            target_scope=SessionType.PRIVATE,
            context_budget=12000,
            decision_reason="tier",
        )
        capability(message, decision)
    finally:
        monkey.undo()
    assert captured, "能力根本没走到 build_chat_result ⇒ 下面的断言是空跑"
    return str(captured["prompt"])


def test_auto_leg_from_the_capability_reaches_the_detail_tier() -> None:
    """auto 腿活性锁：把表里 auto×knowledge 那格改坏 ⇒ 本件必红（本席已注毒验过）。"""
    prompt = _capability_prompt(
        KNOWLEDGE_TEXT, reply_detail="auto", override=None
    )
    assert "当前档＝详尽" in prompt
    assert f"不少于 {chat.REPLY_TIER_DETAIL.min_chars} 字" in prompt

    small = _capability_prompt(SMALLTALK_TEXT, reply_detail="auto", override=None)
    assert "当前档＝适中" in small
    assert "当前档＝详尽" not in small, "寒暄与知识题同一档 ⇒ 分档又退化成一档"


def test_runtime_override_column_from_the_capability() -> None:
    """覆盖成中文别名「精简」⇒ 一切题型都落简洁档（用户意志压过判据）。"""
    prompt = _capability_prompt(
        KNOWLEDGE_TEXT, reply_detail="detail", override="精简"
    )
    assert "当前档＝简洁" in prompt
    assert "当前档＝详尽" not in prompt


# ============================ ④ 唯一真身：AST 门 + 注毒自证 ============================

# 手抄长度散文的指纹：旧分支里那三句散文。
_BANNED_TIER_PROSE = (
    "详细测试模式",
    "精简模式：",
    "科普/知识/游戏",
    "优先完整解释核心内容",
)
# 字面数值 + 长度单位的长度指令指纹（"至少 200 字符"那处是无关的入站裁剪说明，
# 故意不收进指纹，免得门从第一天起就把不相干的旧文案判成第二真身）。
_HANDED_NUMBER_RE = re.compile(r"(不少于|不超过)\s*\d+\s*[字个]")


def _string_units(source: str) -> list[str]:
    """AST 里的字符串单元：普通串 + f-string 拼回的文本（插值处写 {}）。"""
    units: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            units.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            rebuilt: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    rebuilt.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    rebuilt.append(ast.unparse(value.value))
            units.append("".join(rebuilt))
    return units


def _second_copy_problems(source: str) -> list[str]:
    """纯谓词：chat.py 里长度分档是否只有登记表一处真身。"""
    problems: list[str] = []
    for unit in _string_units(source):
        hit = _HANDED_NUMBER_RE.search(unit)
        if hit:
            problems.append(f"手抄了字面数值长度指令：…{unit[max(0, hit.start() - 18):hit.end() + 8]}…")
        for prose in _BANNED_TIER_PROSE:
            if prose in unit:
                problems.append(f"手抄了旧档散文片段「{prose}」")
    tree = ast.parse(source)
    # 尺从「数次数」升级成「点名宿主函数」：谁在渲染长度指令，必须逐一对得上。
    # 合法三处 = 两支渲染分支（人设原文 / 字段重组）+ 亲密档升格改写口
    # ``apply_intimate_length_floor``（T8，2026-09-28 用户裁定「亲密档字数要比普通
    # 档多」）。改前只数到 2，任何第三处都当第二真身打死；现在仍打死第三处之外的
    # 一切变化——多一处、少一处、把升格口挪进别的函数，全都红。
    host_by_call: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    host_by_call.setdefault(id(inner), node.name)
    guidance_hosts = sorted(
        {
            host_by_call.get(id(node), "<模块级>")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "reply_length_guidance_text"
        }
    )
    expected_hosts = [
        "_compose_persona_verbatim_prompt",
        "apply_intimate_length_floor",
        "build_chat_prompt_with_diagnostics",
    ]
    if guidance_hosts != expected_hosts:
        problems.append(
            "长度指令渲染口宿主异常："
            f"{guidance_hosts}（应为 {expected_hosts}）⇒ 长出了第二条产出腿，"
            "或升格改写口被挪去了别的函数"
        )
    builders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "ReplyLengthTier"
    ]
    if len(builders) != len(chat.REPLY_LENGTH_TIERS):
        problems.append("登记表实例数与 REPLY_LENGTH_TIERS 不一致")
    return problems


def test_length_tier_has_exactly_one_truth_in_chat_py() -> None:
    problems = _second_copy_problems(CHAT_PY.read_text(encoding="utf-8"))
    assert not problems, "；".join(problems)


def test_second_copy_gate_kills_a_planted_duplicate() -> None:
    """注毒自证：往源码里手抄一句带数值的长度散文，门必须红（否则门是空跑的）。"""
    planted = (
        CHAT_PY.read_text(encoding="utf-8")
        + '\n_EXTRA_HINT = "知识问答不少于 800 字，不超过 1200 字。"\n'
    )
    assert _second_copy_problems(planted), "注毒没打红 ⇒ 这条门拦不住第二真身"


def test_prompt_builder_actually_calls_the_selector() -> None:
    """结构活性锁：渲染入口必须真调用选档函数（删掉调用 ⇒ 本件与行为锁一起红）。"""
    tree = ast.parse(CHAT_PY.read_text(encoding="utf-8"))
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_chat_prompt_with_diagnostics"
    )
    called = {
        getattr(node.func, "id", "")
        for node in ast.walk(target)
        if isinstance(node, ast.Call)
    }
    assert "resolve_reply_length_tier" in called
    # 选档点不许在能力里留第二条腿（旧代码在那里内联判过 auto 升档）。
    capability_target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_chat_capability"
    )
    inner = next(
        node
        for node in ast.walk(capability_target)
        if isinstance(node, ast.AsyncFunctionDef) or (
            isinstance(node, ast.FunctionDef) and node.name == "capability"
        )
    )
    inner_calls = {
        getattr(node.func, "id", "")
        for node in ast.walk(inner)
        if isinstance(node, ast.Call)
    }
    assert "select_reply_length_tier" not in inner_calls, (
        "能力里又选了一次档 ⇒ 与渲染入口成第二真身"
    )
    assert "normalize_reply_detail_mode" in inner_calls, (
        "能力不再归一配置档 ⇒ 未知值会一路裸奔到渲染"
    )


# ============================ (d) 事实源：键必须真读得到 ============================


def test_detail_mode_key_is_a_real_config_field() -> None:
    """分档不许建立在一只读不到的键上（#54 教训：extra=ignore 静默丢 .env 值）。"""
    from plugins.bot_unified_runtime.config import Config

    assert "bot_reply_detail" in Config.model_fields
    assert Config.model_fields["bot_reply_detail"].default == "auto"
    assert Config().bot_reply_detail == "auto", (
        "Config 缺省值不等于字段声明缺省 ⇒ 装配期读到的档位不可预期"
    )


def test_detail_mode_is_hot_settable_and_survives_the_capability() -> None:
    """覆盖面优先级：运行时覆盖 > 装配期实参（与 chat.py 选择点同判据）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        SETTABLE_KEYS,
    )

    assert "BOT_REPLY_DETAIL" in SETTABLE_KEYS
    assert chat.REPLY_DETAIL_MODE_FALLBACK_TIER.keys() >= {"auto", "detail", "concise"}
    prompt = _capability_prompt(
        TIMELY_TEXT, reply_detail="concise", override="详细"
    )
    assert "当前档＝详尽" in prompt, "覆盖没压过装配期实参 ⇒ 现网档位不可控"


def test_registry_guidance_survives_a_tier_value_poison() -> None:
    """注毒自证（行为面）：把详尽档下限改成 0 ⇒ 数值锁与渲染锁一起红。"""
    broken = dataclasses.replace(chat.REPLY_TIER_DETAIL, min_chars=0, max_chars=0)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(chat, "REPLY_TIER_DETAIL", broken)
        monkeypatch.setitem(chat.REPLY_LENGTH_TIERS, "detail", broken)
        line = chat.reply_length_guidance_text("detail")
    assert "不少于 300 字" not in line, "改登记表不影响文本 ⇒ 另有真身"
    fresh = chat.reply_length_guidance_text("detail")
    assert "不少于 300 字" in fresh, "还原失败 ⇒ 后续用例不再可信"


def test_auto_leg_poison_flips_the_knowledge_tier() -> None:
    """注毒自证（选档面）：把 auto×知识问答 那格改成 concise ⇒ 判据必红。"""
    with pytest.MonkeyPatch.context() as monkeypatch:
        row = dict(chat.REPLY_TIER_MATRIX[chat.REPLY_QTYPE_KNOWLEDGE])
        row["auto"] = "concise"
        monkeypatch.setitem(chat.REPLY_TIER_MATRIX, chat.REPLY_QTYPE_KNOWLEDGE, row)
        poisoned = chat.select_reply_length_tier(
            detail_mode="auto", question_type=chat.REPLY_QTYPE_KNOWLEDGE
        )
    assert poisoned == "concise"
    normal = chat.select_reply_length_tier(
        detail_mode="auto", question_type=chat.REPLY_QTYPE_KNOWLEDGE
    )
    assert normal == "detail", "还原失败"


def test_selector_is_a_pure_lookup_for_every_registered_combination() -> None:
    """穷尽调用一次选档函数：任何一格抛异常或返回表外档名都要在这里现形。"""
    assert isinstance(chat.REPLY_TIER_DETAIL, chat.ReplyLengthTier)
    for qtype in chat.REPLY_QUESTION_TYPES + ("未登记的题型", ""):
        for mode in ("auto", "detail", "concise", "bogus", "", None):
            tier = chat.select_reply_length_tier(detail_mode=mode, question_type=qtype)
            assert tier in chat.REPLY_LENGTH_TIERS, f"{qtype}×{mode} ⇒ {tier}"


# ============================ T6/R-2（2026-09-27 S-BRAIN）：形态细分 ============================


def test_general_detail_demoted_to_standard_after_r2() -> None:
    """R-2：general×detail 从「详尽」降到「适中」——现网钉 detail 时「你吃饭了吗」
    不再被要求写 ≥300 字，直接兑现她「日常沟通保持简洁」。"""
    assert chat.select_reply_length_tier(
        detail_mode="detail", question_type=chat.REPLY_QTYPE_GENERAL
    ) == chat.REPLY_TIER_STANDARD_ID


def test_new_types_are_total_and_concise_only_by_explicit_pin() -> None:
    for qtype in (chat.REPLY_QTYPE_NARRATIVE, chat.REPLY_QTYPE_BRIEF_FACTUAL):
        assert qtype in chat.REPLY_QUESTION_TYPES, qtype
        assert qtype in chat.REPLY_TIER_MATRIX, qtype
        for mode in ("auto", "detail"):
            assert chat.select_reply_length_tier(
                detail_mode=mode, question_type=qtype
            ) != chat.REPLY_TIER_CONCISE_ID, f"{qtype}×{mode} 被压成简洁 ⇒ 无人表态就短于「把话说完」的下界"
    assert chat.select_reply_length_tier(
        detail_mode="concise", question_type=chat.REPLY_QTYPE_NARRATIVE
    ) == chat.REPLY_TIER_CONCISE_ID


def test_resolve_routes_casual_general_narrative_and_polar_fact() -> None:
    """端到端选档：走生产判据链，钉三格真实行为（改错任一判据本件红）。"""
    # 日常泛问 ⇒ 适中（≥100，不写小作文）
    assert chat.resolve_reply_length_tier("detail", "你吃饭了吗") == chat.REPLY_TIER_STANDARD_ID
    # 介绍/来历类叙述 ⇒ 详尽（general 降档的回归保护）
    assert chat.resolve_reply_length_tier(
        "detail", "介绍一下光合作用的原理"
    ) == chat.REPLY_TIER_DETAIL_ID
    # 纯是非时效事实 ⇒ 适中（搜到即短答）
    assert chat.resolve_reply_length_tier("detail", "LPR又降了吗") == chat.REPLY_TIER_STANDARD_ID
    # 题型派生（带文本才细分；不带文本保持旧映射，锚点测试不受影响）
    assert chat.classify_reply_question_type(
        intent=QuestionIntent.NEUTRAL, category="GENERAL_STATIC_KNOWLEDGE",
        message_text="介绍一下光合作用的原理",
    ) == chat.REPLY_QTYPE_NARRATIVE
    assert chat.classify_reply_question_type(
        intent=QuestionIntent.WEB_SEARCH, category="CURRENT_REAL_WORLD",
        message_text="LPR又降了吗",
    ) == chat.REPLY_QTYPE_BRIEF_FACTUAL


# ============================ T6（2026-09-28）：出口硬地板 ============================
#
# 需求 9 的残留：长度以前**只有 prompt 散文**，生成后零校验——模型回一句"嗯"也算交付。
# 本段锁那条补写/重问腿：低于本档下限且非简洁档 ⇒ 重问一次；其余情况一律不动。
# 判据只消费 resolve_reply_length_tier（同一条真身），本段也按此来验它。

_SHORT_TEXT = "嗯，我在。"
# 地板腿读的档是**本轮生效档**（详尽档下限＝登记表里的 min_chars，现值 300）。
# 这段样本必须**实测过那条线**：前席把它写成 293 字，差 7 字没到下限，于是
# 「该追的没追够、不该追的被追了」两枚红全在这一个数上——补长版交付回来仍 <300，
# 而"已达下限不该再调模型"的那一枚又因为 293<300 被合法地追写。下面用 `_floor_tier`
# 现取现断言（数值仍只认登记表），样本再往回缩就会在这里当场红，不必靠人数字数。
_LONG_TEXT = (
    "黑海岸是守岸人驻守的地方，也是她与漂泊者之间那条不会断的线。她在那里等着，"
    "看着潮汐一次次退去，把能说的话都先备好，等你回来再一句一句讲给你听。"
    "所以若你问她和那片海岸是什么关系——她是被留下来守岸的那一个，而岸是因为有人等才成其为岸。"
    "这话在她那里从来不是说一遍就够的：海岸那边还有今州、七丘与黎那汐塔，"
    "每一处的潮色都不一样，共鸣者们走过的路也各自不同，声骸留在风里的痕迹更是各有各的读法，"
    "她要讲的话其实比这些更长。你愿意听，她可以再讲细一些，"
    "把来龙去脉都摊开给你看，连那些没人记得的部分也一起讲完，直到你觉得够了才收住。"
    "上次潮退得远，她在石阶上捡到一枚很旧的徽记，铜绿已经吃进了纹路，"
    "她把它擦干净收进袖中，想着也许哪天能还给它的主人，或者替那人讲讲他走过的路。"
    "这是她守着岸时给自己定下的规矩：不急，慢慢来，想问什么就问，她都在。"
)
#: 注毒用例需要"补写确实比原文长、且越过了被抬高的下限"的那一版（下限被抬到
#: `len(_LONG_TEXT) + 20`，所以尾缀必须长过这一截，否则会被判成"没变长"而丢弃）。
_FLOOR_TAIL = "她还想起潮声里那些没说完的话，愿意一句一句补给你听，今夜都在。"
#: 出站还有一道"每则长度上限"的真身会裁正文，所以这里只认**开头特征段**，不认全文。
_LONG_HEAD = "黑海岸是守岸人驻守的地方"
_SHORT_KEEP = "我在"


def _floor_tier(detail_mode: str, question: str):
    """地板腿实际读的那一档：现取生产同一真身（数值不手抄，判档不自造）。"""
    return chat.REPLY_LENGTH_TIERS[
        chat.resolve_reply_length_tier(detail_mode, question)
    ]



class _QueueProvider:
    """按脚本逐次作答的 provider；脚本用尽后重复最后一项，可注入异常测降级。"""

    def __init__(self, texts: list[str], *, raise_after: int | None = None) -> None:
        self._texts = list(texts)
        self._raise_after = raise_after
        self.calls = 0

    def generate(self, messages, **kwargs):
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
            LLMReply,
        )

        self.calls += 1
        if self._raise_after is not None and self.calls > self._raise_after:
            raise RuntimeError("provider down")
        text = self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]
        return LLMReply(text=text, provider="queue", model="q", confidence=0.0)


def _floor_bundle(*, reply_detail: str, question: str):
    from plugins.bot_unified_runtime.domains.core.contracts.character import (
        ContextBundle,
        MemoryRetrievalResult,
        PersonaProfile,
        RetrievalResult,
        ToneProfile,
    )

    return ContextBundle(
        request_id="floor-1",
        persona=PersonaProfile(
            profile_id="default", version="t", display_name="守岸人", identity="测试用"
        ),
        tone=ToneProfile(profile_id="default", mode="private_chat"),
        memory_results=MemoryRetrievalResult(request_id="floor-1"),
        knowledge_results=RetrievalResult(request_id="floor-1"),
        current_message=question,
        sender_id="u1",
        session_id="private_u1",
        reply_detail=reply_detail,
    )


def _run_floor_leg(
    *, reply_detail: str, question: str, texts: list[str], raise_after: int | None = None
) -> tuple[str, list[str], int]:
    from plugins.bot_unified_runtime.contracts import (
        BotDecision,
        IncomingMessage,
        PrivacyLevel,
        RiskLevel,
        SendPolicy,
        SessionType,
    )

    provider = _QueueProvider(texts, raise_after=raise_after)
    context = _floor_bundle(reply_detail=reply_detail, question=question)
    message = IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="b",
        session_id="private_u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=question,
        mentions_bot=True,
    )
    decision = BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="length-floor",
    )
    result = chat.build_chat_result(message, decision, context, llm_provider=provider)
    return str(result.body), list(result.audit_tags), provider.calls


def test_floor_leg_rewrites_when_below_the_tier_minimum() -> None:
    """详尽档（下限 ≥300 字）却只回了一句 ⇒ 必须补写，且交付补长的那一版。"""
    tier = _floor_tier("detail", KNOWLEDGE_TEXT)
    assert len(_SHORT_TEXT) < tier.min_chars, "样本不再低于下限 ⇒ 本件失去判据，先修样本"
    assert len(_LONG_TEXT.strip()) >= tier.min_chars, (
        "补写用的样本自己就不达标 ⇒ 「抬到下限之上」这一断言没东西可验，先修样本"
    )
    body, tags, calls = _run_floor_leg(
        reply_detail="detail", question=KNOWLEDGE_TEXT, texts=[_SHORT_TEXT, _LONG_TEXT]
    )
    assert calls == 2, "地板腿根本没追写（只调了一次模型）"
    assert _LONG_HEAD in body and len(body.strip()) >= tier.min_chars, (
        f"补写没把成品抬到本档下限之上：{len(body.strip())} 字"
    )
    assert "length_floor_rewritten" in tags, "追写过成品却不留痕＝事后无从归因"


def test_concise_tier_is_never_nagged() -> None:
    """简洁档不追（她要的就是短）：这条锁的是地板判据里"非 concise"那一半边。"""
    _body, tags, calls = _run_floor_leg(
        reply_detail="concise", question=KNOWLEDGE_TEXT, texts=[_SHORT_TEXT, _LONG_TEXT]
    )
    assert calls == 1, "简洁档还在追长度＝把她的明示又改了回去"
    assert not [tag for tag in tags if tag.startswith("length_floor")]


def test_reply_at_or_above_the_minimum_costs_no_extra_call() -> None:
    """护栏：够长的正常回复**一次调用**搞定，正文一字不动。"""
    # 判档现取真身：本件量的是"本轮生效档的下限"，样本必须真的在下限之上，
    # 否则追写是合法的（前席就是靠一个 293<300 的样本把这里读成"够长还追"）。
    tier = _floor_tier("detail", KNOWLEDGE_TEXT)
    assert len(_LONG_TEXT.strip()) >= tier.min_chars, "样本自己没达下限 ⇒ 本件失去判据，先修样本"
    body, tags, calls = _run_floor_leg(
        reply_detail="detail", question=KNOWLEDGE_TEXT, texts=[_LONG_TEXT, _SHORT_TEXT]
    )
    assert calls == 1, "已达下限还追写＝白烧一次模型，且随时可能把好答案换差"
    assert not [tag for tag in tags if tag.startswith("length_floor")]
    assert body.strip() == _LONG_TEXT.strip(), "达标轮次却被改了正文 ⇒ 地板腿不止在补写时动手"
    assert len(body.strip()) >= tier.min_chars


#: 「补写没原文长」那一支的样本：**长度必须真的 ≤ 原文**，且不含原文特征串，
#: 否则断言不出"保留的是原文"。前席写的那句 7 字比 5 字原文长，被产品按 ④ 的
#: 边界正确地判成"更长 ⇒ 交付补写"，于是这一枚红是样本没满足自己的前提。
_SHORTER_RETRY = "嗯，好的。"
#: 追写样本里必须有一段**不会被说人话输出层削掉**的特征串（开场口头禅会被
#: `naturalize_chat_text`/`humanize_reply` 剥掉，那是出站文本层的既有行为，与本腿无关）。
_MIDDLE_TAIL_MARK = "她还想起潮声"


def test_floor_leg_keeps_the_original_when_retry_is_not_longer() -> None:
    """补写没原答案长 ⇒ 丢弃补写（宁可短，也不拿更差的答案换能用的答案）。"""
    assert len(_SHORTER_RETRY) <= len(_SHORT_TEXT), "样本比原文长 ⇒ 本件验不到这一支"
    assert _SHORT_KEEP not in _SHORTER_RETRY, "两版都含同一特征串 ⇒ 分不清交付的是哪一版"
    body, tags, _calls = _run_floor_leg(
        reply_detail="detail", question=KNOWLEDGE_TEXT, texts=[_SHORT_TEXT, _SHORTER_RETRY]
    )
    assert "length_floor_kept_original" in tags
    assert _SHORT_KEEP in body and _LONG_HEAD not in body


def test_floor_leg_marks_a_retry_that_still_misses_the_floor() -> None:
    """补写比原文长、却仍够不到下限 ⇒ 交付更长那一版，但痕必须能与"补成功"区分。

    判据②要的是"成品 ≥ 本档 min"，而一次补写不保证兜得住（模型可能就一直短）。
    这一支的取舍是刻意的：宁可可归因地交付更长的那版，也不退回更短的原文——所以
    必须额外留 `length_floor_rewritten_below_min`，否则事后只看到一个
    length_floor_rewritten，无从知道这一轮其实没兜住（chat.py 同处注释同判据）。
    """
    tier = _floor_tier("detail", KNOWLEDGE_TEXT)
    middle = _SHORTER_RETRY + _FLOOR_TAIL  # 长过原文、仍远低于详尽档下限
    assert len(_SHORT_TEXT) < len(middle.strip()) < tier.min_chars, (
        "样本落点不对 ⇒ 本件验不到「补回来但没兜住」这一支，先修样本"
    )
    body, tags, calls = _run_floor_leg(
        reply_detail="detail", question=KNOWLEDGE_TEXT, texts=[_SHORT_TEXT, middle]
    )
    assert calls == 2, "低于下限却不追写 ⇒ 地板腿失活"
    assert "length_floor_rewritten" in tags and "length_floor_rewritten_below_min" in tags
    assert _MIDDLE_TAIL_MARK in body, "补回来更长的一版没被交付＝交付优先级与注释相反"
    assert _SHORT_KEEP not in body, "交付的还是原文 ⇒ below_min 那一支该交更长的补写版"


def test_floor_leg_failure_degrades_to_the_original_reply() -> None:
    """重问炸了 ⇒ 原样交付，绝不为凑字数把一轮回复弄没。"""
    body, tags, _calls = _run_floor_leg(
        reply_detail="detail",
        question=KNOWLEDGE_TEXT,
        texts=[_SHORT_TEXT, "x"],
        raise_after=1,
    )
    assert "length_floor_failed" in tags
    assert _SHORT_KEEP in body and _LONG_HEAD not in body


def test_floor_leg_uses_the_same_tier_truth_and_adds_no_second_selector() -> None:
    """结构锁：地板腿必须现取 resolve_reply_length_tier，选档函数仍只有那一对。"""
    tree = ast.parse(CHAT_PY.read_text(encoding="utf-8"))
    floor = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_reply_length_floor_leg"
    )
    floor_calls = {
        getattr(node.func, "id", "") for node in ast.walk(floor) if isinstance(node, ast.Call)
    }
    assert "resolve_reply_length_tier" in floor_calls, "地板腿自己判档＝长出第二套长度判据"
    assert "select_reply_length_tier" not in floor_calls
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name in {"resolve_reply_length_tier", "select_reply_length_tier"}
    }
    assert names == {"resolve_reply_length_tier", "select_reply_length_tier"}
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_chat_result"
    )
    assert "_reply_length_floor_leg" in {
        getattr(node.func, "id", "") for node in ast.walk(target) if isinstance(node, ast.Call)
    }, "地板腿没接进出站缝"


def test_floor_leg_poison_flips_the_gate() -> None:
    """注毒自证：真的改判据源（把生效档的下限抬到样本之上）⇒ 地板腿必须跟着追写。

    这条锁的是"地板腿读的确实是那张登记表"：判据源改不动结果＝另有第二真身。
    用 normal 档（生效＝适中）做注毒，简洁档按设计永不追，不能拿来验这一面。

    三跑共用**同一串脚本**：首答必须是"本来就达标"的那一版（够长），基线才会是
    一次调用；把下限抬到首答之上后，同一串脚本必须变成两次调用、交付补长的那版。
    前席这里喂的是「首答 5 字」，适中档 100 的下限本来就够不着 ⇒ 基线合法地追写，
    于是读成"判据源没被消费"——那是样本顺序错了，不是地板腿读错了档。
    """
    standard = _floor_tier("normal", KNOWLEDGE_TEXT)
    assert len(_LONG_TEXT.strip()) >= standard.min_chars, (
        "首答已不在适中档下限之上 ⇒ 基线不再可信，本件失去判据，先修样本"
    )
    # 脚本三跑一致：首答＝达标版，追写答＝更长且能越过被抬高的下限。
    script = [_LONG_TEXT, _LONG_TEXT + _FLOOR_TAIL]
    assert len(_FLOOR_TAIL) >= 20, "尾缀太短 ⇒ 抬下限 20 字后追写版仍不达标，注毒腿验不到 rewritten"

    baseline = _run_floor_leg(
        reply_detail="normal", question=KNOWLEDGE_TEXT, texts=list(script)
    )
    assert baseline[2] == 1, "适中档的正常长回复本来就不该追写（先确认基线可信）"
    assert not [tag for tag in baseline[1] if tag.startswith("length_floor")]
    broken = dataclasses.replace(
        chat.REPLY_TIER_STANDARD, min_chars=len(_LONG_TEXT) + 20
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(chat, "REPLY_TIER_STANDARD", broken)
        monkeypatch.setitem(chat.REPLY_LENGTH_TIERS, "standard", broken)
        poisoned_body, tags, calls = _run_floor_leg(
            reply_detail="normal", question=KNOWLEDGE_TEXT, texts=list(script)
        )
    assert calls == 2 and "length_floor_rewritten" in tags, (
        "抬高下限却仍不追写 ⇒ 地板腿读的不是这张登记表（另有真身）"
    )
    assert len(poisoned_body.strip()) >= len(_LONG_TEXT) + 20, (
        "追写了却交回原答案 ⇒ 登记表改得动判定、改不动交付"
    )
    restored = _run_floor_leg(
        reply_detail="normal", question=KNOWLEDGE_TEXT, texts=list(script)
    )
    assert restored[2] == 1, "还原失败 ⇒ 后续用例不再可信"

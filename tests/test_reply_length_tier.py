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

    `personas/shorekeeper/identity.md`【回复长度】要求「日常搭话……通常不少于
    百来字」，若 auto 把寒暄压到 ≤60 字，模型同一轮会读到两句互相拆台的话。
    简洁档只有用户显式钉「精简」这一条路（想改口径只改矩阵那一格）。
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
    # standard 档下限与人格里的「百来字」对齐（改数值只改登记表那一处）。
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
        settings = RuntimeSettingsStore()
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
    guidance_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "reply_length_guidance_text"
    ]
    # 两支渲染分支各一次 = 2；多一处就是有人又抄了一条产出腿。
    if len(guidance_calls) != 2:
        problems.append(
            f"reply_length_guidance_text 调用点 {len(guidance_calls)} 处（应为 2："
            "人设原文分支 + 字段重组分支）⇒ 长度指令可能还有第二条产出路径"
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

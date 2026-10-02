"""席 P11（2026-10-04，用户裁定「用户明说别联网 ⇒ 【现实关系】整块不得进 prompt」）。

量什么
------
真身缺陷：【现实关系】（实体关系册一跳检索）此前只照「册里有这个名字」放行，
用户明说"别联网"照样把现实事实塞进 prompt＝违抗本轮指令。

① 否决腿：句子含中央词表认得的拒绝说法（``别联网``/``不要联网``/``不用查``/``别搜索``）
   且句里确有在册实体（``registered_entity_hit`` 为真）⇒ ``reality_relation_note_for``
   必为空串，装配后的 prompt 里【现实关系】整块缺席。
② 对照腿：同句去掉那句拒绝 ⇒ 仍照旧注入（不许把修复做成"这块干脆不出了"）。
③ 尺的归属腿：判据必须住在**中央分类器**（``classify_question_intent`` 的
   ``explicit_no_web``），不是 providers 自己那份关键词表——
   假的"中央说没拒绝"⇒ 照出；假的"中央说拒绝了（而句子里一个拒绝字都没有）"⇒ 不照出。
   附一格形状容错：中央结论缺 ``reason`` 格（既有注毒件就喂这种只填被读字段的假决策）
   ⇒ 当"本轮没否决"处理，不许被 except 吃成整块缺席。
④ 反第二本账静态锁：``reality_relation_note_for`` 函数体里不许出现中文拒绝词字面量，
   只许出现 ``explicit_no_web`` 那枚码。

全离线：只读随包种子、零联网、零写盘、不 import NoneBot、不碰生产 Runtime。
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    ContextBundle,
    ConversationHistoryResult,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat as rp
from plugins.bot_unified_runtime.domains.chat_reply.character import providers
from plugins.bot_unified_runtime.domains.chat_reply.runtime import question_intent
from plugins.bot_unified_runtime.domains.core.search import entity_relations as er

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDERS_SRC = (
    REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "character"
    / "providers.py"
)

REALITY_SECTION = "【现实关系】"
LINE_ARROW = " → "
SIGNED_LINE_MARK = "（已核）"

#: 中央 ``_NO_WEB_RE`` 真认得的四种说法（本件**不自造词表**：这四条能过否决腿，
#: 靠的就是那把尺；尺改了这里就红，正是本锁想要的耦合方向）。
REFUSALS = ("别联网", "不要联网", "不用查网上", "别搜索")

#: 同一件在册实体（鸣潮）的两种问法：带拒绝 / 不带拒绝。拒绝短语一律前缀，
#: 使两腿除那句意愿之外**逐字节同形**，别让别的变量替修复说话。
REFUSED_QUERIES = tuple(f"{word}，鸣潮是哪个公司开发的" for word in REFUSALS)
NEUTRAL_QUERY = "鸣潮是哪个公司开发的"


@pytest.fixture(autouse=True)
def _restore_seed_cache():
    """``load_seed`` 按路径缓存 ⇒ 本件不留毒给下一枚测试。"""
    er.load_seed.cache_clear()
    yield
    er.load_seed.cache_clear()


def _context(*, note: str, message: str) -> ContextBundle:
    return ContextBundle(
        request_id="req-p11",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人，黑海岸的守护者",
            raw_text="# 角色沉浸要求\n\n你就是守岸人本人，以第一人称思考与回应。",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-p11"),
        conversation_history=ConversationHistoryResult(request_id="req-p11"),
        knowledge_results=RetrievalResult(request_id="req-p11", chunks=[]),
        current_message=message,
        sender_id="user-p11",
        session_id="private:user-p11",
        reality_relation_note=note,
        context_budget=24576,
    )


def _prompt(context: ContextBundle) -> str:
    return rp.build_chat_prompt(context)[0]["content"]


def _ruling_for(text: str) -> question_intent.IntentDecision:
    """中央那把尺的原样结论（先自证它确实判了 ``explicit_no_web``，否则腿①是空转）。"""
    return question_intent.classify_question_intent(text)


# ---------------------------------------------------------------------------
# ① 否决腿：说了别联网 ⇒ 整块不注入
# ---------------------------------------------------------------------------
def test_explicit_no_web_vetoes_the_reality_relation_block() -> None:
    for query in REFUSED_QUERIES:
        ruling = _ruling_for(query)
        assert ruling.reason == "explicit_no_web", (query, ruling.reason)
        assert er.registered_entity_hit(query) is True, (
            f"{query}：册里没这个名字 ⇒ 就算空了也证明不了否决"
        )
        assert providers.reality_relation_note_for(query) == "", (
            f"用户说了别联网还端现实关系块：{query}"
        )


def test_refused_turn_leaves_no_section_in_the_assembled_prompt() -> None:
    """端到端：走真装配口，prompt 里既没区块标题也没事实行。"""
    for query in REFUSED_QUERIES:
        prompt = _prompt(
            _context(note=providers.reality_relation_note_for(query), message=query)
        )
        assert REALITY_SECTION not in prompt, f"拒绝那轮长出了【现实关系】：{query}"
        assert LINE_ARROW not in prompt and SIGNED_LINE_MARK not in prompt, query


# ---------------------------------------------------------------------------
# ② 对照腿：没说 ⇒ 照旧注入（修复不得顺手关掉整条链路）
# ---------------------------------------------------------------------------
def test_without_refusal_the_block_is_still_injected() -> None:
    assert _ruling_for(NEUTRAL_QUERY).reason != "explicit_no_web"
    assert er.registered_entity_hit(NEUTRAL_QUERY) is True
    note = providers.reality_relation_note_for(NEUTRAL_QUERY)
    assert note, "没说别联网却没端出现实关系＝把修复做成了退役"
    assert "《鸣潮》" in note and "库洛" in note, note


def test_unrefused_turn_renders_the_section_in_the_prompt() -> None:
    note = providers.reality_relation_note_for(NEUTRAL_QUERY)
    prompt = _prompt(_context(note=note, message=NEUTRAL_QUERY))
    assert REALITY_SECTION in prompt and note.splitlines()[0] in prompt
    _messages, diagnostics = rp.build_chat_prompt_with_diagnostics(
        _context(note=note, message=NEUTRAL_QUERY)
    )
    assert not diagnostics.clipped_to_context_budget, "私聊预算被这块挤崩了"


# ---------------------------------------------------------------------------
# ③ 尺的归属：判据住在中央分类器，providers 不持有第二把尺
# ---------------------------------------------------------------------------
def _fake_ruling(reason: str, category: str) -> Any:
    real = _ruling_for(NEUTRAL_QUERY)
    replaced = replace(real, reason=reason, category=category)
    return replaced


def test_veto_follows_the_central_ruling_not_the_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """假中央说"没拒绝"⇒ 照出（providers 自己没再扫一遍关键词）；
    假中央说"拒绝了"而句子里一个拒绝字都没有 ⇒ 不照出（否决只认那枚码）。"""
    refused = f"{REFUSALS[0]}，{NEUTRAL_QUERY}"
    monkeypatch.setattr(
        providers,
        "classify_question_intent",
        lambda _text: _fake_ruling("domain_fallback", "LOCAL_KNOWLEDGE"),
    )
    assert providers.reality_relation_note_for(refused) != "", (
        "中央没判 explicit_no_web 却缺席＝providers 里藏了第二份词表"
    )

    monkeypatch.setattr(
        providers,
        "classify_question_intent",
        lambda _text: _fake_ruling("explicit_no_web", "LOCAL_KNOWLEDGE"),
    )
    assert providers.reality_relation_note_for(NEUTRAL_QUERY) == "", (
        "中央判了 explicit_no_web 却仍端出来＝没接那把尺"
    )


def test_veto_tolerates_a_ruling_missing_the_reason_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """形状容错锁：中央结论缺 ``reason`` 格（既有注毒件
    ``test_entity_gate_before_classification._NeverDecision`` 就喂这种只填被读字段的假决策）
    ⇒ 当"本轮没有否决"处理、实体命中照端，不许被本函数的 except 吃成整块缺席。"""

    class _CategoryOnly:
        category = "LOCAL_KNOWLEDGE"

    monkeypatch.setattr(providers, "classify_question_intent", lambda _t: _CategoryOnly())
    assert er.registered_entity_hit(NEUTRAL_QUERY) is True
    assert providers.reality_relation_note_for(NEUTRAL_QUERY) != "", (
        "缺 reason 格被当成否决＝把缺席和违令混成一回事"
    )


# ---------------------------------------------------------------------------
# ④ 反第二本账静态锁：函数体里只许出现那枚码，不许出现中文拒绝词
# ---------------------------------------------------------------------------


def test_providers_holds_no_second_refusal_word_table() -> None:
    tree = ast.parse(PROVIDERS_SRC.read_text(encoding="utf-8"), filename=str(PROVIDERS_SRC))
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "reality_relation_note_for"
    )
    body_literals = [
        constant.value
        for stmt in fn.body[1:]  # body[0] ＝ docstring（散文里提那几个词是允许的）
        for constant in ast.walk(stmt)
        if isinstance(constant, ast.Constant) and isinstance(constant.value, str)
    ]
    joined = "".join(body_literals)
    assert "explicit_no_web" in body_literals, "否决没走中央那枚 reason 码"
    for word in (*REFUSALS, "不要搜索", "无需联网", "只用本地"):
        assert word not in joined, f"providers 里长出了第二份拒绝词表：{word}"
    # 零新配置键：这道门不读任何 BOT_* 环境名。
    assert not any(lit.startswith("BOT_") for lit in body_literals), body_literals


# ---------------------------------------------------------------------------
# ⑤ 端到端腿（席 P11b 复核补）：台账 §73 事故原句走**真实装配链**
#    ``FileCharacterContextProvider.build_context``（providers 第 954 行那处注入点）
#    → ``chat.build_chat_prompt_with_diagnostics``。
#    本腿同时是「chat.py 要不要动」的现算答案：分区有无全由 providers 侧那枚否决决定，
#    chat.py 的渲染行（``dynamic_parts += ["", "【现实关系】", note]``）一字未改。
#    只读装配：不传任何 store／provider ⇒ 零网络、零写盘。
# ---------------------------------------------------------------------------
ACCIDENT_QUERY = "别联网，随便聊聊鸣潮"  #: 台账 §73 事故原句（否决 + 在册实体）
PLAIN_QUERY = "鸣潮最新版本更新了吗"  #: 同域不加否决的对照句


def _real_bundle(query_text: str) -> ContextBundle:
    provider = providers.FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="1",
        persona_files=[],
        knowledge_files=[],
    )
    return provider.build_context(
        request_id="req-p11b",
        sender_id="user-p11b",
        session_id="private:user-p11b",
        query_text=query_text,
    )


def test_accident_sentence_end_to_end_via_the_real_assembly_chain() -> None:
    vetoed = _real_bundle(ACCIDENT_QUERY)
    assert vetoed.reality_relation_note == "", vetoed.reality_relation_note
    messages, diagnostics = rp.build_chat_prompt_with_diagnostics(vetoed)
    prompt = messages[0]["content"]
    assert REALITY_SECTION not in prompt, prompt.partition(REALITY_SECTION)[0]
    assert not diagnostics.clipped_to_context_budget

    control = _real_bundle(PLAIN_QUERY)
    assert control.reality_relation_note != "", (
        "不加否决的对照句在真装配链上也被吃掉＝把否决做成了退役"
    )
    control_prompt = rp.build_chat_prompt_with_diagnostics(control)[0][0]["content"]
    assert REALITY_SECTION in control_prompt
    assert control.reality_relation_note.splitlines()[0] in control_prompt

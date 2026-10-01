"""T3 跨库次序的**穿生产腿**活性锁（2026-09-28，S-POLICY 摘牌波）。

判据链：``build_chat_capability`` → ``FileCharacterContextProvider.build_context``
→ ``provide()`` 里的每轮重排（``search_service.reorder_knowledge_chunks`` ←
``resolve_answer_order``）→ ``build_chat_result`` → 提示词 → **录制型 provider
实收**。任何一环被拆掉（把重排删了、把判据换成手写序、把阶梯读点改回常量表），
本件立刻红；本席不直调判据自证自判（那是本仓反复出现过的假绿形态）。

锁三件事：
① 背景档（人物关系/设定题）人格库在前 —— 与改前手写 ``[persona, wiki]`` 同序；
② 时效档（最新版本/卡池题）百科知识库退到人格库**之前**（本地库只当背景参考），
   这正是 ``ANSWER_SOURCE_LADDER_LATEST`` 的语义，旧写法在两条问题上给同一个序；
③ 单库/无命中/未标注库名等退化形态一律**一字不动**（判据不得把好数据重排坏）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    FileCharacterContextProvider,
)
from plugins.bot_unified_runtime.domains.core.search import search_service
from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
    MergedKnowledgeRetriever,
)

BACKGROUND_TEXT = "守岸人与黑海岸是什么关系"
LATEST_TEXT = "鸣潮最新版本卡池更新了什么"


def _chunk(chunk_id: str, content: str, *, library: str):
    from plugins.bot_unified_runtime.contracts import KnowledgeChunk

    return KnowledgeChunk(
        chunk_id=chunk_id,
        content=content,
        source_id=f"{library}/page/{chunk_id}",
        title=f"条目{chunk_id}",
        source_library=library,
    )


class _FakeLeg:
    """一路检索器：只负责"这座库里查到了什么"，不参与任何排序判据。"""

    available = True

    def __init__(self, chunks: list) -> None:
        self._chunks = chunks

    def retrieve(self, query_text: str) -> list:
        return list(self._chunks)


def _provider(tmp_path: Path) -> FileCharacterContextProvider:
    persona_leg = _FakeLeg(
        [
            _chunk("p1", "人格资料一：守岸人是黑海岸的守望者。", library=search_service.KB_SOURCE_PERSONA),
            _chunk("p2", "人格资料二：她守在岸边等待漂泊者。", library=search_service.KB_SOURCE_PERSONA),
        ]
    )
    wiki_leg = _FakeLeg(
        [
            _chunk("w1", "百科资料一：黑海岸组织的公开条目。", library=search_service.KB_SOURCE_WIKI),
            _chunk("w2", "百科资料二：鸣潮新版本卡池的词条正文。", library=search_service.KB_SOURCE_WIKI),
        ]
    )
    merged = MergedKnowledgeRetriever(
        [persona_leg, wiki_leg],
        libraries=[search_service.KB_SOURCE_PERSONA, search_service.KB_SOURCE_WIKI],
    )
    return FileCharacterContextProvider(
        persona_profile_id="default",
        persona_display_name="守岸人",
        persona_version="0",
        persona_files=[],
        knowledge_files=[],
        vector_retriever=merged.retrieve,
    )


class RecordingProvider:
    """记下每次实收的 messages；本件据此判「次序真的到了模型眼前」。"""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages, **kwargs):
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
            LLMReply,
        )

        self.calls.append([dict(item) for item in messages])
        return LLMReply(text="收到了。", provider="rec", model="rec", confidence=0.0)

    @property
    def prompt(self) -> str:
        return "\n".join(
            str(item.get("content") or "") for item in (self.calls[-1] if self.calls else [])
        )


def _run(tmp_path: Path, text: str) -> str:
    recorder = RecordingProvider()
    capability = chat.build_chat_capability(
        _provider(tmp_path), recorder, reply_detail="detail"
    )
    message = IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="b",
        session_id="private-order-u",
        session_type=SessionType.PRIVATE,
        sender_id="order-u",
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
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        context_budget=12000,
        decision_reason="answer-order-lock",
    )
    capability(message, decision)
    assert recorder.calls, "能力没走到 provider ⇒ 本件是空跑"
    return recorder.prompt


def _library_positions(prompt: str) -> tuple[int, int]:
    persona = prompt.find("库 人格资料库")
    wiki = prompt.find("库 百科知识库")
    assert persona >= 0 and wiki >= 0, (
        f"两条库的命中身份行没同时出现在提示词里：persona={persona} wiki={wiki}"
        "（身份行缺失 ⇒ 这里判次序没有意义，先查呈现腿）"
    )
    return persona, wiki


def test_background_question_keeps_persona_library_first(tmp_path: Path) -> None:
    persona, wiki = _library_positions(_run(tmp_path, BACKGROUND_TEXT))
    assert persona < wiki, "背景档里本地人格库必须先行（库已有的内容不该被随手网页盖过去）"


def test_latest_question_puts_wiki_library_before_persona(tmp_path: Path) -> None:
    """时效档翻转：这一条就是「手写 ``[persona, wiki]``」永远给不出的那一格。"""
    from plugins.bot_unified_runtime.domains.core.search.search_intent import (
        detect_acg_intent,
    )

    assert detect_acg_intent(LATEST_TEXT).wants_latest, (
        "样本不再被判成时效档 ⇒ 本件退化成背景档的重复断言，先修样本"
    )
    persona, wiki = _library_positions(_run(tmp_path, LATEST_TEXT))
    assert wiki < persona, "时效档下本地库退到背景参考位（判据真身＝ANSWER_SOURCE_LADDER_LATEST）"


def test_two_questions_of_different_timeliness_do_not_get_the_same_order(tmp_path: Path) -> None:
    bg_persona, bg_wiki = _library_positions(_run(tmp_path, BACKGROUND_TEXT))
    lt_persona, lt_wiki = _library_positions(_run(tmp_path, LATEST_TEXT))
    assert (bg_persona < bg_wiki) != (lt_persona < lt_wiki), (
        "两档给出同一个序 ⇒ 阶梯没有每轮参与，判据又退化成装配期一次写死"
    )


# ============================ 退化形态：判据不许把好数据排坏 ============================


def test_unstamped_chunks_keep_their_original_order() -> None:
    class _Bare:
        def __init__(self, chunk_id: str) -> None:
            self.chunk_id = chunk_id
            self.content = f"正文{chunk_id}"
            self.source_id = "明日方舟/prts_arknights/正文/某页__94671"
            self.title = ""
            self.source_library = ""

    items = [_Bare("a"), _Bare("b"), _Bare("c")]
    for wants_latest in (False, True):
        assert search_service.reorder_knowledge_chunks(
            items, wants_latest=wants_latest
        ) == items, "未标注库名时不得凭空改变相对次序（那是另一座库的判据）"


def test_single_library_input_is_returned_unchanged() -> None:
    only = [
        _chunk("w1", "一", library=search_service.KB_SOURCE_WIKI),
        _chunk("w2", "二", library=search_service.KB_SOURCE_WIKI),
    ]
    assert search_service.reorder_knowledge_chunks(only, wants_latest=True) == only
    assert search_service.reorder_knowledge_chunks([], wants_latest=True) == []


def test_reorder_interleaves_instead_of_grouping_whole_libraries() -> None:
    """交错（各家一条一条轮着取）是既有交付形态：整座库连排会让后一座库被预算裁光。"""
    items = [
        _chunk("p1", "人格一", library=search_service.KB_SOURCE_PERSONA),
        _chunk("w1", "百科一", library=search_service.KB_SOURCE_WIKI),
        _chunk("p2", "人格二", library=search_service.KB_SOURCE_PERSONA),
        _chunk("w2", "百科二", library=search_service.KB_SOURCE_WIKI),
    ]
    latest = search_service.reorder_knowledge_chunks(items, wants_latest=True)
    assert [c.chunk_id for c in latest] == ["w1", "p1", "w2", "p2"]
    background = search_service.reorder_knowledge_chunks(items, wants_latest=False)
    assert [c.chunk_id for c in background] == ["p1", "w1", "p2", "w2"]


def test_poisoning_the_ladder_flips_the_runtime_order() -> None:
    """注毒自证：把阶梯的时效档改成"人格库在前" ⇒ 上面那两条行为锁必有一条红。

    判据真的被消费过一次才算数——真身改不动结果＝这条腿根本没通电。
    """
    broken_ladder = (
        search_service.KB_SOURCE_PERSONA,
        search_service.KB_SOURCE_WIKI,
        "bilibili",
        "moegirl",
        "bangumi",
        "general",
    )
    items = [
        _chunk("p1", "人格一", library=search_service.KB_SOURCE_PERSONA),
        _chunk("w1", "百科一", library=search_service.KB_SOURCE_WIKI),
    ]
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(search_service, "ANSWER_SOURCE_LADDER_LATEST", broken_ladder)
        poisoned = search_service.reorder_knowledge_chunks(items, wants_latest=True)
    assert [c.chunk_id for c in poisoned] == ["p1", "w1"], "注毒没改变结果 ⇒ 阶梯不通电"
    fresh = search_service.reorder_knowledge_chunks(items, wants_latest=True)
    assert [c.chunk_id for c in fresh] == ["w1", "p1"], "还原失败 ⇒ 后续断言不再可信"

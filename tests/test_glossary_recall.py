"""审查 O-06：术语/时梗分区按关键词召回（替代每轮全量注入）回归测试。

覆盖五门：
①query 命中召回对应条目（含别名、大小写/全角归一）；
②零命中且非术语问句 → 【世界观】/【时梗备注】分区整块不出现
  （既有空分区不渲染语义保持）；
③召回上限截断（≤RECALL_MAX_ENTRIES=8，对齐 SEED_MAX_ENTRIES 惯例）；
④兜底路径：零命中但本轮明确询问术语（question_intent 术语类）→ 回退全量防漏答；
⑤trend 层同型处理 + provider.recall 接口可用。
全部离线：不联网、不写源码树。
"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.contracts import (
    ContextBundle,
    GlossaryContext,
    GlossaryEntry,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
    TrendContext,
    TrendNote,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_chat_prompt,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    glossary as glossary_mod,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.glossary import (
    RECALL_MAX_ENTRIES,
    FileGlossaryProvider,
    NullGlossaryProvider,
    is_term_question,
    recall_entries,
    recall_trend_notes,
)

PERSONA_TEXT = "# 角色沉浸要求\n\n你就是守岸人本人，以第一人称思考与回应。"


def _context(
    *,
    current_message: str,
    entries: list[GlossaryEntry] | None = None,
    notes: list[TrendNote] | None = None,
) -> ContextBundle:
    return ContextBundle(
        request_id="req-1",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
            raw_text=PERSONA_TEXT,
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-1"),
        knowledge_results=RetrievalResult(request_id="req-1"),
        glossary_context=GlossaryContext(request_id="req-1", entries=entries or []),
        trend_context=TrendContext(request_id="req-1", notes=notes or []),
        current_message=current_message,
        sender_id="user-1",
        session_id="private:user-1",
    )


def _entries(*terms: str) -> list[GlossaryEntry]:
    return [GlossaryEntry(term=term, explanation=f"{term}的解释") for term in terms]


# ---- ① query 命中召回对应条目 ----


def test_recall_hits_matching_entries_only() -> None:
    entries = _entries("今州", "黑海岸", "星槎海中枢")

    hits = recall_entries(entries, "今州和黑海岸好玩吗")

    assert [entry.term for entry in hits] == ["今州", "黑海岸"], (
        "命中条目按原顺序返回，未命中的条目不得混入"
    )


def test_recall_matches_alias_and_normalizes_case_fullwidth() -> None:
    entries = [
        GlossaryEntry(term="漂泊者（Rover）", explanation="主角的称呼"),
        GlossaryEntry(term="UP池", explanation="限时卡池"),
    ]

    # 别名命中：括号内英文名。
    assert [e.term for e in recall_entries(entries, "rover 是谁")] == ["漂泊者（Rover）"]
    # 大小写归一：小写 query 命中大写术语。
    assert [e.term for e in recall_entries(entries, "up池什么时候保底")] == ["UP池"]
    # 全角归一：全角字母 query 命中半角术语。
    assert [e.term for e in recall_entries(entries, "ＵＰ池是什么")] == ["UP池"]


def test_recall_empty_or_blank_query_returns_empty() -> None:
    entries = _entries("今州")

    assert recall_entries(entries, "") == []
    assert recall_entries(entries, "   ") == []


# ---- ② 零命中且非术语问句 → 分区整块不出现 ----


def test_prompt_glossary_section_absent_on_zero_hit() -> None:
    # 「你好呀」零命中且非术语问句 →【世界观】不得出现（空分区不渲染语义保持）。
    context = _context(current_message="你好呀", entries=_entries("今州"))
    system_prompt = build_chat_prompt(context)[0]["content"]

    assert "【世界观】" not in system_prompt
    assert "今州的解释" not in system_prompt


def test_prompt_trend_section_absent_on_zero_hit() -> None:
    notes = [TrendNote(topic="模拟宇宙", note="流行追忆流派")]
    context = _context(current_message="你好呀", notes=notes)
    system_prompt = build_chat_prompt(context)[0]["content"]

    assert "【时梗备注】" not in system_prompt


# ---- ③ 召回上限截断（≤8）----


def test_recall_limit_truncates_to_cap() -> None:
    terms = tuple(f"词条{i:02d}" for i in range(12))
    entries = _entries(*terms)
    query = " ".join(terms)  # 全部命中

    hits = recall_entries(entries, query)
    assert len(hits) == RECALL_MAX_ENTRIES == 8
    assert [entry.term for entry in hits] == list(terms[:8]), "截断按文件内优先级保序"

    assert len(recall_entries(entries, query, limit=2)) == 2
    assert recall_entries(entries, query, limit=0) == []


# ---- ④ 兜底：零命中 + question_intent 术语类 → 回退全量 ----


def test_prompt_fallback_full_on_zero_hit_term_question() -> None:
    # 「什么是虫洞」不含任何术语 → 召回为零；但属静态概念释义提问
    # （GENERAL_STATIC_KNOWLEDGE）→ 回退全量注入防漏答。
    entries = _entries("今州", "黑海岸")
    context = _context(current_message="什么是虫洞", entries=entries)
    system_prompt = build_chat_prompt(context)[0]["content"]

    assert "【世界观】" in system_prompt
    assert "今州的解释" in system_prompt
    assert "黑海岸的解释" in system_prompt


def test_prompt_no_fallback_for_smalltalk() -> None:
    # 零命中 + 闲聊（非术语问句）→ 不回退，分区不出现（O-06 防膨胀本意）。
    entries = _entries("今州")
    context = _context(current_message="你好呀", entries=entries)
    system_prompt = build_chat_prompt(context)[0]["content"]

    assert "【世界观】" not in system_prompt


def test_is_term_question_classification() -> None:
    assert is_term_question("什么是虫洞")  # 静态概念释义
    assert is_term_question("声骸是什么")  # 世界观域词（LOCAL_KNOWLEDGE）
    assert not is_term_question("你好")  # 闲聊
    assert not is_term_question("今天天气怎么样")  # 实时信息（WEB_SEARCH）
    assert not is_term_question("")  # 空文本


# ---- ⑤ trend 层同型处理 + provider.recall 接口 ----


def test_trend_recall_hits_and_fallback() -> None:
    notes = [
        TrendNote(topic="模拟宇宙", note="流行追忆流派"),
        TrendNote(topic="深渊", note="本期压力较大"),
    ]

    # 命中：只召回 topic 出现在 query 中的备注，保序。
    hits = recall_trend_notes(notes, "模拟宇宙新流派怎么样")
    assert [note.topic for note in hits] == ["模拟宇宙"]
    # 零命中。
    assert recall_trend_notes(notes, "你好呀") == []

    # 兜底同型：零命中 + 术语问句 → prompt 回退全量时梗备注。
    context = _context(current_message="什么是虫洞", notes=notes)
    system_prompt = build_chat_prompt(context)[0]["content"]
    assert "【时梗备注】" in system_prompt
    assert "流行追忆流派" in system_prompt


def test_file_provider_recall_interface(tmp_path) -> None:
    lines = "\n".join(f"**词条{letter}**：解释{letter}" for letter in "ABC")
    file = tmp_path / "glossary.md"
    file.write_text(lines, encoding="utf-8")
    provider = FileGlossaryProvider(glossary_files=[file])

    hits = provider.recall("词条B相关讨论")
    assert [entry.term for entry in hits.entries] == ["词条B"]

    # limit 参数生效（query 同时含多个完整术语，截断按原顺序取前 2）；
    # Null 实现恒为空（不抛异常）。
    assert len(provider.recall("词条A词条B词条C", limit=2).entries) == 2
    assert NullGlossaryProvider().recall("词条").entries == []


def test_default_provider_recall_uses_seed(tmp_path) -> None:
    # 默认装配（空配置→随包种子）也具备召回接口，且命中种子词条。
    provider = glossary_mod.build_glossary_provider(
        SimpleNamespace(bot_glossary_files=[], bot_glossary_max_chars=1500)
    )
    hits = provider.recall("今州在哪个国家")

    assert [entry.term for entry in hits.entries] == ["今州"]

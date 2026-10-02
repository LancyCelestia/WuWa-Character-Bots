"""席 S19（2026-10-03，用户裁定「实体查表提到问句分类之前」）：顺序锁 + 撞名对照 + A/B 读数。

量什么
------
① 顺序：``registered_entity_hit``（册里有这个名字）＝第一道放行理由，分类器退为第二道
   （只在查不到名字时才判）。本案主诉句「明日方舟是谁开发的」改前 ``never``、不出块。
② 误触发防线（本案命门）：短拉丁别名（``CD``/``CP``/``CQ``/``BW``）、人格名
   （``kind == character``）、册里标未核的实体 ⇒ 单凭整词命中不放行，要「整句即该实体」
   或「与 ``ENTITY_GATE_DOMAIN_TERMS`` 共现」。六句日常话逐句现算，断言**零误出块**。
③ A/B 读数（离线，走真装配口 ``build_chat_prompt_with_diagnostics``）：四句改前/改后的
   在场判据与字符增量；未核实体（CICF）出场必须照样带「待核」。
④ 册口径降级读数：``COMICUP located_in 广州`` 边由已核降为未核（verified 计数前后）。

全部零联网、零写盘、不碰生产路径；种子只按真册读（本件不改它）。
"""

from __future__ import annotations

from pathlib import Path

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
REALITY_SECTION = "【现实关系】"
LINE_ARROW = " → "
SIGNED_LINE_MARK = "（已核）"

#: 本案主诉 + 对照句（六句日常话必须零误出块——缺这条＝把幻觉从另一侧放进来）。
MAIN_CASE = "明日方舟是谁开发的"
AB_QUERIES = (
    MAIN_CASE,
    "绝区零是谁开发的",
    "库洛科技在哪里",
    "鸣潮是哪个公司开发的",
)
CONTROL_QUERIES = (
    "今天心情不好",
    "帮我看看这段代码",
    "晚安",
    "cp 命令怎么用",
    "这个CD盘多少钱",
    "守岸人你喜欢什么",
)

#: 改前那道门的判据（**逐字照抄 HEAD 的 ``reality_relation_note_for``**，只用于 A/B 对账；
#: 真身仍以 ``providers.reality_relation_note_for`` 为准，本常量不构成第二处放行判据）。
_HEAD_CATEGORIES = frozenset(
    {"EXTERNAL_ENTITY", "CURRENT_REAL_WORLD", "LOCAL_KNOWLEDGE", "GENERAL_STATIC_KNOWLEDGE"}
)


class _NeverDecision:
    """假决策：只填被读到的那一个字段（分类器判"这不是现实题"）。"""

    category: str = "SMALL_TALK"


@pytest.fixture(autouse=True)
def _restore_seed_cache():
    """``load_seed`` 按路径缓存（键是路径字符串，不认 mtime）⇒ 注毒件自己收口，别留毒。"""
    er.load_seed.cache_clear()
    yield
    er.load_seed.cache_clear()


def _note_before(text: str) -> str:
    if not text.strip():
        return ""
    if question_intent.classify_question_intent(text).category not in _HEAD_CATEGORIES:
        return ""
    return "\n".join(er.reality_relation_lines(text))


def _context(*, note: str, message: str, budget: int = 24576) -> ContextBundle:
    return ContextBundle(
        request_id="req-s19",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人，黑海岸的守护者",
            raw_text="# 角色沉浸要求\n\n你就是守岸人本人，以第一人称思考与回应。",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-s19"),
        conversation_history=ConversationHistoryResult(request_id="req-s19"),
        knowledge_results=RetrievalResult(request_id="req-s19", chunks=[]),
        current_message=message,
        sender_id="user-s19",
        session_id="private:user-s19",
        reality_relation_note=note,
        context_budget=budget,
    )


def _render(note: str, message: str, budget: int = 24576) -> tuple[str, bool]:
    messages, diag = rp.build_chat_prompt_with_diagnostics(
        _context(note=note, message=message, budget=budget)
    )
    return messages[0]["content"], diag.clipped_to_context_budget


# ---------------------------------------------------------------------------
# ① 顺序：实体命中在前，分类器退为第二道门
# ---------------------------------------------------------------------------
def test_entity_hit_gates_without_the_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """顺序锁：把分类器那道门**人为关死**（只返回一枚不在放行表里的类别），
    实体命中照样放行 ⇒ 证明放行不再依赖分类器先判。"""
    assert er.registered_entity_hit(MAIN_CASE) is True
    note = providers.reality_relation_note_for(MAIN_CASE)
    assert "上海鹰角网络科技有限公司" in note, note
    assert SIGNED_LINE_MARK in note, f"已核陈述没带状态字据：{note}"
    monkeypatch.setattr(providers, "classify_question_intent", lambda _t: _NeverDecision())
    assert providers.reality_relation_note_for(MAIN_CASE) != "", "实体命中仍被分类器拦着＝顺序没改"
    # 另一腿：查不到名字的问句还得靠那道门——门没被拆，只是被挪到第二位。
    assert providers.reality_relation_note_for("今天心情不好") == ""


def test_classifier_still_gates_when_the_ledger_has_no_name() -> None:
    """查不到名字 ⇒ 一切照 HEAD：分类器不放行就一个字都不端。"""
    for query in ("别联网，随便聊聊光合作用", "帮我看看这段代码", "晚安"):
        assert er.registered_entity_hit(query) is False, query
        assert providers.reality_relation_note_for(query) == "", query
        assert _note_before(query) == "", query


# ---------------------------------------------------------------------------
# ② 误触发防线：六句日常话零出块（命门）
# ---------------------------------------------------------------------------
def test_ambiguous_short_and_persona_hits_are_not_enough() -> None:
    assert er.match_entities_in("这个CD盘多少钱") == ("ComiDay",), "整词命中本身没坏（判据复用）"
    assert er.match_entities_in("cp 命令怎么用") == ()
    assert er.relation_query_admissible("这个CD盘多少钱") is False
    assert er.relation_query_admissible("守岸人你喜欢什么") is False
    assert er.registered_entity_hit("这个CD盘多少钱") is False
    assert er.registered_entity_hit("守岸人你喜欢什么") is False
    # 反证：短名一旦有共现证据/整句即它 ⇒ 照旧放行（纪律不是把功能一刀切死）。
    assert er.registered_entity_hit("CP 展在哪") is True
    assert er.registered_entity_hit("CICF") is True
    assert er.registered_entity_hit("CICF是什么") is True
    assert er.registered_entity_hit("守岸人出自哪个游戏") is True


@pytest.mark.parametrize("query", CONTROL_QUERIES)
def test_control_sentences_render_no_relation_block(query: str) -> None:
    assert providers.reality_relation_note_for(query) == "", f"误出块：{query}"
    text, _ = _render("", query)
    assert REALITY_SECTION not in text, f"对照组长出了分区：{query}"
    assert LINE_ARROW not in text and SIGNED_LINE_MARK not in text, f"对照组混进事实行：{query}"


# ---------------------------------------------------------------------------
# ③ A/B 读数（走真装配口）+ 未核必带「待核」
# ---------------------------------------------------------------------------
def test_ab_readings_four_queries(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    lines: list[str] = []
    for query in AB_QUERIES:
        before = _note_before(query)
        after = providers.reality_relation_note_for(query)
        category = question_intent.classify_question_intent(query).category
        text_before, clipped_before = _render(before, query)
        text_after, clipped_after = _render(after, query)
        group_after, group_clipped = _render(after, query, budget=16384)
        group_before, _ = _render(before, query, budget=16384)
        record = (
            f"S19AB|{query}|cat={category}|before={len(before)}|after={len(after)}"
            f"|delta={len(text_after) - len(text_before)}"
            f"|section_before={REALITY_SECTION in text_before}"
            f"|section_after={REALITY_SECTION in text_after}"
            f"|group_delta={len(group_after) - len(group_before)}"
            f"|clipped_before={clipped_before}|clipped_after={clipped_after}"
            f"|group_clipped_after={group_clipped}"
            f"|hit={er.registered_entity_hit(query)}"
            f"|admissible={er.relation_query_admissible(query)}"
        )
        print(record)
        lines.append(record)
        assert not clipped_after, f"私聊预算被这块挤崩：{query}"
        assert not group_clipped, f"群聊生效预算被挤崩：{query}"
        if er.match_entities_in(query):
            assert REALITY_SECTION in text_after and after, f"在册实体的现实题没接上：{query}"
        else:
            # 绝区零不在册 ⇒ 诚实缺席：不端块、不拿别人的条目顶（台账 #51★「没检索禁写它没有」同族）。
            assert after == "" and REALITY_SECTION not in text_after, f"缺席实体被硬端出块：{query}"
    (tmp_path / "s19_ab_readings.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert capsys.readouterr().out.count("S19AB|") == len(AB_QUERIES)


def test_unverified_entity_still_carries_the_pending_prefix() -> None:
    """未核实体（CICF）经新顺序出场 ⇒ 照样带「待核」，降级不许被"放行更容易"冲掉。"""
    note = providers.reality_relation_note_for("CICF是什么")
    assert note and er.unverified_prefix() in note, note
    assert SIGNED_LINE_MARK not in note, f"未核条目混进了已核字据：{note}"
    text, _ = _render(note, "CICF是什么")
    assert REALITY_SECTION in text and er.unverified_prefix() in text


def test_gate_stays_fail_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """新加的两把尺自己炸 ⇒ 本轮分区缺席；掏空册 ⇒ 整块不渲染（既有纪律一字不动）。"""

    def _boom(*_a: object, **_k: object) -> bool:
        raise RuntimeError("尺坏了")

    monkeypatch.setattr(providers, "relation_query_admissible", _boom)
    assert providers.reality_relation_note_for(MAIN_CASE) == ""
    monkeypatch.undo()
    empty = tmp_path / "empty_seed.json"
    empty.write_text('{"entities": [], "relations": []}', encoding="utf-8")
    monkeypatch.setattr(er, "SEED_PATH", empty)
    er.load_seed.cache_clear()  # 缓存键是路径字符串（None），原地换 SEED_PATH 必须自己清
    for query in (MAIN_CASE, *CONTROL_QUERIES):
        assert providers.reality_relation_note_for(query) == "", query
        assert REALITY_SECTION not in _render("", query)[0], query


# ---------------------------------------------------------------------------
# ④ 册口径降级读数（本席只动这一条边）
# ---------------------------------------------------------------------------
def test_seed_comicup_edge_demoted_and_counts_printed(capsys: pytest.CaptureFixture[str]) -> None:
    seed = er.load_seed()
    verified_edges = sum(1 for triple in seed.relations if triple.verified)
    unverified_entities = sum(1 for record in seed.entities if not record.verified)
    print(
        f"S19SEED|relations={len(seed.relations)}|verified={verified_edges}"
        f"|unverified_entities={unverified_entities}|size={er.SEED_PATH.stat().st_size}"
    )
    comicup = [
        triple
        for triple in seed.relations
        if triple.subject == "COMICUP" and triple.relation == er.RELATION_LOCATED_IN
    ]
    assert len(comicup) == 1 and comicup[0].verified is False, "COMICUP located_in 未降级"
    assert unverified_entities == 11, "只许动这一条边 ⇒ 实体待核计数不得跟着变"
    report = capsys.readouterr().out
    assert "S19SEED|" in report

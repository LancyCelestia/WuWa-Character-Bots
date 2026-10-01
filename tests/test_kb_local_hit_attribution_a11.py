"""A-11 锁：知识命中「算哪座库」只有一个读点，且它不是页级 source_id。

起因（2026-09-27 生产实弹）：`bot.chat:ValidationError` ×3 ——
`KnowledgeHitView.library` 限 64 字符，被塞进页级 source_id
（`鸣潮/fandom_wutheringwaves/…__37468`）当场炸；同一处口径错位还让
「谁先答」阶梯的 `local_hit` **结构上永不成立**（阶梯只认 `persona`/`kb_wiki`），
于是每条带本地命中的问题都无谓降级联网。

四条锁各自堵一个回潮面：①合并点必须标注；②阶梯必须判到本地命中；
③64 字符上限必须不再被页级 id 撞穿；④认不出的来源**不许猜前缀**造库名。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    _chunk_hit_library,
    _kb_hits_by_source,
)
from plugins.bot_unified_runtime.domains.core.contracts.character import KnowledgeChunk
from plugins.bot_unified_runtime.domains.core.search import search_service as SS
from plugins.bot_unified_runtime.domains.core.search.search_service import (
    chunk_source_library,
    knowledge_hit_view,
)
from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
    MergedKnowledgeRetriever,
)

# 生产实测形态：页级 source_id 撞穿 library 的 64 字符上限（真值更长，此处取
# 同一构造式的一条 68 字符样本；断言里显式核长度，别让"超长"这个前提自己造假）。
LONG_PAGE_ID = (
    "鸣潮/fandom_wutheringwaves/正文/"
    "Retribution and Customs (2025-10-30)__38040"
)


class _FakeLeg:
    """最小检索器替身：只交回预置块，available 由入参决定。"""

    def __init__(self, chunks, *, available=True):
        self._chunks = list(chunks)
        self.available = available

    def retrieve(self, _query):
        return list(self._chunks)


def _chunk(chunk_id: str, source_id: str, *, title: str = "某条目") -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        title=title,
        content=f"{title}的正文，够长以免被当成空块丢掉。" * 3,
    )


def test_merged_retriever_stamps_declared_library_per_leg():
    """标注按**路**发生：同一条块的 source_library 来自它那一腿，不是猜的。"""
    persona_chunk = _chunk("p1", "鸣潮库街区百科")
    wiki_chunk = _chunk("w1", LONG_PAGE_ID)
    merged = MergedKnowledgeRetriever(
        [_FakeLeg([persona_chunk]), _FakeLeg([wiki_chunk])],
        libraries=[SS.KB_SOURCE_PERSONA, SS.KB_SOURCE_WIKI],
    )
    out = merged.retrieve("任意查询")
    by_id = {chunk.chunk_id: chunk for chunk in out}
    assert by_id["p1"].source_library == SS.KB_SOURCE_PERSONA
    assert by_id["w1"].source_library == SS.KB_SOURCE_WIKI
    # 页级身份不许被改写：它仍是原样，只是不再是"库名"。
    assert by_id["w1"].source_id == LONG_PAGE_ID


def test_merged_retriever_without_libraries_keeps_legacy_shape():
    """不交 libraries ⇒ 逐字节维持旧行为（他席既有五处用法零改动）。"""
    chunk = _chunk("w1", LONG_PAGE_ID)
    merged = MergedKnowledgeRetriever([_FakeLeg([chunk])])
    out = merged.retrieve("q")
    assert out[0].source_library == ""
    assert out[0].chunk_id == "w1"


def test_merged_retriever_length_mismatch_stamps_nothing():
    """腿数与库名数不等 ⇒ 整体不标注并留痕，绝不按位置瞎配。"""
    chunk = _chunk("w1", LONG_PAGE_ID)
    merged = MergedKnowledgeRetriever(
        [_FakeLeg([chunk]), _FakeLeg([_chunk("w2", "别处/页__1")])],
        libraries=[SS.KB_SOURCE_WIKI],
    )
    assert all(out.source_library == "" for out in merged.retrieve("q"))


def test_ladder_counts_declared_library_so_local_hit_holds():
    """判据主战场：只带库名进阶梯 ⇒ `local_hit` 成立、不再无谓降级联网。"""
    chunk = _chunk("w1", LONG_PAGE_ID)
    chunk.source_library = SS.KB_SOURCE_WIKI
    hits = _kb_hits_by_source([chunk, chunk])
    assert hits == {SS.KB_SOURCE_WIKI: 2}
    order = SS.resolve_answer_order(
        hits_by_source=hits, wants_latest=False, web_search_intended=False
    )
    assert order.reason == "local_hit_first"
    assert order.degrade_to_web is False
    assert order.first_answer_source == SS.KB_SOURCE_WIKI


def test_unstamped_chunk_never_smuggles_page_id_as_library():
    """没标注 ⇒ 交回哨兵库名；**绝不**按前缀猜、也绝不把页级 id 当库名往外递。"""
    unstamped = _chunk("w1", LONG_PAGE_ID)
    assert chunk_source_library(unstamped) == ""
    assert _chunk_hit_library(unstamped) == "未标注来源"
    assert _chunk_hit_library(_chunk("w2", "   ")) == "未标注来源"


def test_long_page_source_id_no_longer_reaches_library_field():
    """崩溃回归锁：页级 id 超长时，两条路都进不了 `library` 位。"""
    unstamped = _chunk("w1", LONG_PAGE_ID)
    assert len(unstamped.source_id) > 64  # 前提：这条真值确实超上限
    view = knowledge_hit_view(
        library=_chunk_hit_library(unstamped), chunk=unstamped
    )
    assert view.library == "未标注来源"
    stamped = unstamped.model_copy(
        update={"source_library": SS.KB_SOURCE_WIKI}
    )
    assert len(_chunk_hit_library(stamped)) <= 64
    assert knowledge_hit_view(
        library=_chunk_hit_library(stamped), chunk=stamped
    ).library == SS.KB_SOURCE_WIKI


def test_chunk_source_library_rejects_unregistered_names():
    """族名表外的一切值（含伪造的 "kb_wiki2"）一律判"没标注"。"""
    forged = _chunk("w1", "别处/页__1")
    forged.source_library = "kb_wiki2"
    assert chunk_source_library(forged) == ""
    forged.source_library = SS.KB_SOURCE_PERSONA
    assert chunk_source_library(forged) == SS.KB_SOURCE_PERSONA

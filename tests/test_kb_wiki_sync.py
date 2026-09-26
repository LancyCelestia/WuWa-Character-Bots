"""Crawl Wiki 知识库桥回归：分块、hash 幂等同步、FTS 降级策略、合并检索。"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import KnowledgeChunk
from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)
from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
    MergedKnowledgeRetriever,
    split_doc_chunks,
    sync_kb_wiki,
)


class _FakeEmbedder:
    """确定性假嵌入：文本 hash 派生 8 维向量，使幂等/重嵌逻辑可离线验证。"""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.sha1(text.encode("utf-8")).digest()
            vectors.append([byte / 255.0 for byte in digest[:8]])
        return vectors


def _store(tmp_path, **kwargs) -> SqliteVectorKnowledgeStore:
    defaults: dict = {
        "db_path": tmp_path / "kb_wiki_embeddings.sqlite3",
        "embed_provider": _FakeEmbedder(),
        "chunk_chars": 800,
        "top_k": 4,
        "signature": "test|fake-embedder",
        "auto_reset": True,
    }
    defaults.update(kwargs)
    return SqliteVectorKnowledgeStore(**defaults)


def _doc(doc_id: str, text: str, *, title: str = "", topic: str = "梗知识") -> dict:
    title = title or doc_id.rsplit("/", 1)[-1]
    chunks = split_doc_chunks(text, title, hard_limit=800)
    return {
        "id": doc_id,
        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "topic": topic,
        "source": "moegirl",
        "title": title,
        "chunks": chunks,
    }


# ---------------------------------------------------------------- 分块


def test_split_doc_chunks_heading_and_hardcut():
    text = "首段。\n## 技能\n技能内容。\n## 台词\n台词内容。"
    chunks = split_doc_chunks(text, "某梗", hard_limit=800)
    assert chunks[0].startswith("【某梗】")
    assert "【某梗｜技能】" in chunks[1]
    assert "【某梗｜台词】" in chunks[2]

    long_section = "## 长\n" + "字" * 2000
    hard = split_doc_chunks(long_section, "长梗", hard_limit=200)
    assert len(hard) >= 3
    assert all(len(chunk) <= 260 for chunk in hard)
    assert any(chunk.startswith("【长梗｜续】") for chunk in hard)

    assert split_doc_chunks("   \n  ", "空梗") == []


# ---------------------------------------------------------------- 幂等同步


def test_sync_documents_idempotent_and_removed(tmp_path):
    store = _store(tmp_path)
    docs = [_doc("梗知识/moegirl/A梗", "A 梗正文。" * 30), _doc("梗知识/moegirl/B梗", "B 梗正文。" * 30)]
    stats = store.sync_documents(docs)
    assert stats["added"] == 2 and stats["skipped"] == 0
    total_chunks = stats["chunks"]
    assert store.document_count() == 2

    # 重复执行：hash 一致全部跳过，不产生重复向量/块。
    again = store.sync_documents(docs)
    assert again["added"] == 0 and again["changed"] == 0
    assert again["skipped"] == 2 and again["chunks"] == 0
    assert store.stats()["total"] == total_chunks

    # hash 变化：整文档重切重写，块数不累积。
    docs[0] = _doc("梗知识/moegirl/A梗", "A 梗新正文。" * 30)
    changed = store.sync_documents(docs)
    assert changed["changed"] == 1 and changed["added"] == 0
    assert store.stats()["total"] == total_chunks

    # removed_ids：文档与其全部块一并删除。
    removed = store.sync_documents(docs, removed_ids=["梗知识/moegirl/B梗"])
    assert removed["removed"] == 1
    assert store.document_count() == 1
    remaining = {
        row["source_id"]
        for row in store._connect().execute("SELECT source_id FROM knowledge_chunks")
    }
    assert remaining == {"梗知识/moegirl/A梗"}


def test_sync_documents_full_mode_prunes_missing(tmp_path):
    store = _store(tmp_path)
    store.sync_documents(
        [_doc("梗知识/moegirl/A梗", "正文A"), _doc("梗知识/moegirl/B梗", "正文B")]
    )
    # full 流里 B 消失 → 自动清除；A 未变跳过。
    stats = store.sync_documents([_doc("梗知识/moegirl/A梗", "正文A")], full=True)
    assert stats["removed"] == 1 and stats["skipped"] == 1
    assert store.document_count() == 1


def test_sync_documents_clears_fts_signature(tmp_path):
    store = _store(tmp_path)
    store.sync_documents([_doc("梗知识/moegirl/A梗", "正文A")])
    assert store.ensure_fts_index() is True
    store.sync_documents([_doc("梗知识/moegirl/A梗", "正文A换")])
    assert store._stored_fts_signature() == ""


def test_embed_pending_custom_batch_size(tmp_path):
    """embed_pending(batch_size=N) 应按 N 切批（本地 Ollama 大批提吞吐的依据）。"""

    class _CountingEmbedder(_FakeEmbedder):
        def __init__(self) -> None:
            super().__init__()
            self.sizes: list[int] = []

        def embed_texts(self, texts):
            self.sizes.append(len(texts))
            return super().embed_texts(texts)

    embedder = _CountingEmbedder()
    store = _store(tmp_path, embed_provider=embedder)
    docs = [
        _doc(f"梗知识/moegirl/梗{i}", f"正文{i}。" * 20) for i in range(5)
    ]
    store.sync_documents(docs)
    done, pending = store.embed_pending(None, batch_size=2)
    assert (done, pending) == (5, 5)
    # 首点是 #50 的冷启动预热（一发廉价调用换掉"首批扛模型加载"），
    # 真批次仍严格按 2 切：2+2+1，批大小是本锁的语义，总次数不是。
    assert embedder.sizes[0] == 1, f"应有一次前置预热：{embedder.sizes}"
    assert embedder.sizes[1:] == [2, 2, 1], f"切批形状被改动：{embedder.sizes}"
    assert store.stats()["embedded"] == 5


# ---------------------------------------------------------------- 检索链路（离线端到端）


def test_retrieve_after_sync_and_ann(tmp_path):
    store = _store(tmp_path)
    docs = [
        _doc("梗知识/moegirl/谐音梗", "谐音梗是利用读音相近的词语制造笑点的梗。" * 10),
        _doc("梗知识/moegirl/AI梗", "AI梗泛指人工智能相关的流行语。" * 10),
    ]
    store.sync_documents(docs)
    store.embed_pending(None)
    assert store.build_ann_index()["built"] is True
    hits = store.retrieve("谐音梗是什么", files=None)
    assert hits, "同步+嵌入+索引后检索应命中"
    assert all(isinstance(chunk, KnowledgeChunk) for chunk in hits)


def test_fts_auto_rebuild_disabled_degrades(tmp_path):
    store = _store(tmp_path, fts_auto_rebuild=False)
    store.sync_documents([_doc("梗知识/moegirl/A梗", "正文A" * 50)])
    # 签名缺失时检索路径不内联重建（大库防卡消息），force=True 才重建。
    assert store.ensure_fts_index() is False
    assert store.ensure_fts_index(force=True) is True
    assert store.ensure_fts_index() is True


# ---------------------------------------------------------------- 合并检索器


def test_entry_title_bonus_ranks_entry_page_first(tmp_path):
    """自然问句包含词条名时，词条页应排在正文堆词的噪声页之前。"""

    store = _store(tmp_path)
    docs = [
        _doc("梗知识/moegirl/目标条目", "这是一段与查询措辞几乎无关的说明性正文。"),
        _doc(
            "梗知识/moegirl/干扰页面",
            "有什么用有什么用：正文密集堆叠查询词的干扰页。有什么用。",
        ),
    ]
    store.sync_documents(docs)
    hits = store.retrieve("目标条目有什么用", files=None)
    assert hits, "词条名+关键词均应产生候选"
    assert hits[0].title.startswith("目标条目"), (
        f"词条名命中应排第一，实际排序: {[c.title for c in hits]}"
    )


# ---------------------------------------------------------------- 词条名切分与前缀匹配


def test_entry_title_match_len_segment_and_prefix():
    """词条名按 _/-/空白切分后：段包含命中，纯中文段 2~4 字前缀命中。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
        _entry_title_match_len,
    )

    # 全名包含（wiki「标题·来源」剥后缀后命中）。
    assert _entry_title_match_len("纳西妲·moegirl", "纳西妲的元素战技叫什么") == 3
    # 人格库下划线词条名：切分出「纳西妲」段包含命中。
    assert _entry_title_match_len("纳西妲_背景故事", "聊聊纳西妲") == 3
    assert _entry_title_match_len("纳西妲_背景故事", "纳西妲的背景") == 3
    # 切分出的子题段整体包含命中（长度取段长）。
    assert _entry_title_match_len("尘歌壶_系统说明", "怎么进入系统说明界面") == 4
    # 纯中文长段前缀命中：查询只提到词条名前几个字。
    assert _entry_title_match_len("尘歌壶系统说明", "尘歌壶怎么用") == 3
    assert _entry_title_match_len("西风骑士团", "西风骑士的职责是什么") == 4
    # 连字符/空白切分同样生效。
    assert _entry_title_match_len("深境螺旋-第12层", "深境螺旋多少层满星") == 4
    assert _entry_title_match_len("枫丹科学院 档案", "枫丹科学院在哪") == 5
    # 未命中：无包含、无前缀、非纯中文段不走前缀。
    assert _entry_title_match_len("枫丹科学院", "须弥城的天气如何") == 0
    assert _entry_title_match_len("AI梗图鉴", "今天天气怎么样") == 0
    # 过短段（1 字）不参与匹配。
    assert _entry_title_match_len("猫 睡姿大全", "猫有多大") == 0


def test_entry_title_prefix_match_ranks_entry_page_first(tmp_path):
    """人格库式词条名：查询只提到词条名前 2~4 字也能把词条页顶到最前。"""

    store = _store(tmp_path)
    docs = [
        _doc(
            "梗知识/moegirl/尘歌壶系统说明",
            "这是一段与查询措辞几乎无关的说明性正文。",
            title="尘歌壶系统说明",
        ),
        _doc(
            "梗知识/moegirl/干扰页面",
            "怎么用怎么用：正文密集堆叠查询词的干扰页。怎么用。",
        ),
    ]
    store.sync_documents(docs)
    hits = store.retrieve("尘歌壶怎么用", files=None)
    assert hits, "前缀命中词条名+关键词均应产生候选"
    assert hits[0].title.startswith("尘歌壶"), (
        f"词条名前缀命中应排第一，实际排序: {[c.title for c in hits]}"
    )


def test_entry_title_segment_match_hits_underscored_title(tmp_path):
    """下划线词条名的切分段（主名）被查询包含时，词条页应排在干扰页之前。"""

    store = _store(tmp_path)
    docs = [
        _doc(
            "梗知识/moegirl/纳西妲_背景故事",
            "这是一段与查询措辞几乎无关的说明性正文。",
            title="纳西妲_背景故事",
        ),
        _doc(
            "梗知识/moegirl/干扰页面",
            "元素战技元素战技：正文密集堆叠查询词的干扰页。元素战技。",
        ),
    ]
    store.sync_documents(docs)
    hits = store.retrieve("纳西妲的元素战技叫什么", files=None)
    assert hits, "词条名切分段+关键词均应产生候选"
    assert hits[0].title.startswith("纳西妲"), (
        f"词条名切分段命中应排第一，实际排序: {[c.title for c in hits]}"
    )


def test_merged_retriever_interleaves_and_dedupes():
    def _chunk(chunk_id: str) -> KnowledgeChunk:
        return KnowledgeChunk(chunk_id=chunk_id, source_id=chunk_id, title=chunk_id, content=chunk_id)

    class _R:
        available = True

        def __init__(self, chunks: list[str]) -> None:
            self._chunks = chunks

        def retrieve(self, query_text: str) -> list[KnowledgeChunk]:
            return [_chunk(chunk_id) for chunk_id in self._chunks]

    class _Broken:
        available = True

        def retrieve(self, query_text: str) -> list[KnowledgeChunk]:
            raise RuntimeError("boom")

    merged = MergedKnowledgeRetriever([_R(["a1", "a2"]), _Broken(), _R(["b1", "a1"])])
    ids = [chunk.chunk_id for chunk in merged.retrieve("q")]
    assert ids == ["a1", "b1", "a2"]


# ---------------------------------------------------------------- updates.jsonl 增量


def test_sync_kb_wiki_incremental_from_updates(tmp_path):
    kb_dir = tmp_path / "knowledge_base"
    kb_dir.mkdir()
    (kb_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "generated_at": "2026-09-08T00:00:00Z",
                "documents": 2,
                "entries": {},
                "added": ["梗知识/moegirl/A梗"],
                "changed": [],
                "removed": ["梗知识/moegirl/C梗"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    text = "谐音梗正文。" * 40
    (kb_dir / "updates.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "op": "upsert",
                        "id": "梗知识/moegirl/A梗",
                        "topic": "梗知识",
                        "source": "moegirl",
                        "title": "A梗",
                        "url": "",
                        "text": text,
                        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    },
                    ensure_ascii=False,
                ),
                json.dumps({"op": "delete", "id": "梗知识/moegirl/C梗"}, ensure_ascii=False),
            ]
        ),
        encoding="utf-8",
    )
    config = SimpleNamespace(
        bot_kb_wiki_root=str(tmp_path / "wiki_root"),
        bot_kb_wiki_topics="",
        bot_kb_wiki_chunk_chars=800,
    )
    # 把 root 指到 tmp：kb_paths 用 root/crawl_output/knowledge_base。
    config.bot_kb_wiki_root = str(tmp_path)
    (tmp_path / "crawl_output").mkdir()
    kb_dir.rename(tmp_path / "crawl_output" / "knowledge_base")

    store = _store(tmp_path / "store.sqlite3")
    stats = sync_kb_wiki(store, config)
    assert stats["added"] == 1
    # 首次灌库时 C 梗在本地从未存在：removed 清单无物可删，计 0 才是幂等语义。
    assert stats["removed"] == 0
    assert store.document_count() == 1

    # 幂等：同一轮增量重放零变更。
    replay = sync_kb_wiki(store, config)
    assert replay["added"] == 0 and replay["removed"] == 0 and replay["skipped"] == 1


# ---------------------------------------------------------------- 维基库关键词通道接线（S-WIKI-FTS）
#
# 缺陷：kb_wiki._build_store 用 fts_auto_rebuild=False（检索进程故意不内联建），
# 注释承诺"重建由 kb-sync 负责"，而 force=True 的 FTS 构建此前只埋在
# build_ann_index 之内（vector_knowledge.py:2776 faiss 缺失 / :3125 publish 之后）。
# 但 run_kb_sync_task 的 ANN 重建门在"零变更夜"整个跳过 build_ann_index ⇒ 那两处
# force 落点都到不了 ⇒ 维基库一旦错过有 ANN 重建的那一夜，此后每零变更夜都不建
# FTS，关键词通道恒 0 行（生产实测：维基库 knowledge_chunks_fts=0、无 fts_signature，
# 而个人库同名表 35283 行满）。修法：kb-sync 收尾补一次 ensure_fts_index(force=True)。


def _kb_sync_config(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_kb_wiki_db_path=str(tmp_path / "kb_wiki_embeddings.sqlite3"),
        bot_kb_wiki_chunk_chars=800,
        bot_kb_wiki_embed_batch=128,
    )


def _zero_change_sync(monkeypatch) -> None:
    """把 sync_kb_wiki 打成"本轮零变更"：无 added/changed/removed、不碰库内容。"""
    from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

    monkeypatch.setattr(
        kb_wiki,
        "sync_kb_wiki",
        lambda store, config, *, full=False, on_progress=None: {
            "added": 0,
            "changed": 0,
            "removed": 0,
            "skipped": 1,
            "chunks": 0,
        },
    )


def test_zero_change_night_builds_wiki_fts_through_kbsync(tmp_path, monkeypatch):
    """① 零变更夜（无新 chunk、ANN 重建门跳过）维基库 FTS 仍被 force 建起来。"""
    from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

    store = _store(tmp_path, fts_auto_rebuild=False, auto_reset=False)
    store.sync_documents([_doc("梗知识/moegirl/纳西妲", "纳西妲是须弥的草神，掌管智慧与知识。" * 8)])
    # 检索进程绝不内联重建（fts_auto_rebuild=False 的原设计，本锁不许放宽）。
    assert store.ensure_fts_index() is False
    assert store._stored_fts_signature() == ""
    # 无待嵌行 ⇒ stats.embedded==0 ⇒ ANN 重建门整个跳过 build_ann_index（零变更夜实况）。
    _zero_change_sync(monkeypatch)
    config = _kb_sync_config(tmp_path)

    result = kb_wiki.run_kb_sync_task(config, store=store, embed=False)

    assert result["ok"] is True
    assert result["ann_reason"] == "unchanged_skip"  # build_ann_index 没被调 ⇒ 唯一旧 force 落点被绕过
    assert result["fts_built"] is True
    assert store._stored_fts_signature() != ""  # FTS 由收尾那一次 force 建起来
    assert store.ensure_fts_index() is True
    # 关键词通道确实能命中专有名词（二游角色名这类精确字面）。
    populated = store._connect().execute(
        "SELECT COUNT(*) FROM knowledge_chunks_fts"
    ).fetchone()[0]
    assert populated >= 1
    assert store._match_candidates(["纳西妲"], 5), "FTS 建好后关键词通道应命中词条名"


def test_wiki_search_store_still_has_fts_auto_rebuild_off(monkeypatch, tmp_path):
    """② fts_auto_rebuild=False 的生产构造值不许翻：检索进程仍不内联重建。

    注毒目标：把 kb_wiki.py 的 ``fts_auto_rebuild=False`` 翻成 True ⇒ 本锁必红，
    证明"大库不在消息热路径内联建分钟级索引"这条设计还在执法。
    """
    from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

    monkeypatch.setattr(
        kb_wiki,
        "_build_provider",
        lambda config, *, timeout_override=None: SimpleNamespace(signature=""),
    )
    store = kb_wiki._build_store(
        SimpleNamespace(bot_kb_wiki_db_path=str(tmp_path / "kb_wiki_embeddings.sqlite3")),
        auto_reset=False,
    )
    assert store.fts_auto_rebuild is False
    # 行为后果：签名缺失时检索路径不内联重建（与 test_fts_auto_rebuild_disabled_degrades 同源）。
    store.sync_documents([_doc("梗知识/moegirl/A梗", "正文A" * 50)])
    assert store.ensure_fts_index() is False
    assert store._stored_fts_signature() == ""


def test_wiki_fts_rebuild_idempotent_across_zero_change_nights(tmp_path, monkeypatch):
    """③ 签名在位时幂等：非重建夜收尾那一次只是 meta 比对，绝不重扫全表。"""
    from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

    store = _store(tmp_path, fts_auto_rebuild=False, auto_reset=False)
    store.sync_documents([_doc("梗知识/moegirl/纳西妲", "纳西妲是草神。" * 8)])
    _zero_change_sync(monkeypatch)
    config = _kb_sync_config(tmp_path)

    first = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert first["fts_built"] is True
    signature = store._stored_fts_signature()
    assert signature != ""

    rebuild_calls = {"n": 0}
    original_rebuild = store._rebuild_fts

    def counting_rebuild():
        rebuild_calls["n"] += 1
        return original_rebuild()

    monkeypatch.setattr(store, "_rebuild_fts", counting_rebuild)
    store._fts_valid = None  # 绕开进程内缓存，逼它走"读签名即跳过"的幂等判定

    second = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert second["fts_built"] is True
    assert store._stored_fts_signature() == signature
    assert rebuild_calls["n"] == 0, "签名在位仍全表重建 ⇒ 收尾那一次不幂等，会把每夜变成重建夜"


@pytest.mark.parametrize(
    ("text", "title", "expected_prefix"),
    [("## 起源\n内容", "X梗", "【X梗｜起源】")],
)
def test_split_doc_chunks_prefix(text, title, expected_prefix):
    assert any(chunk.startswith(expected_prefix) for chunk in split_doc_chunks(text, title))

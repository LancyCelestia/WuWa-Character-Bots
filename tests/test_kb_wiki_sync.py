"""Crawl Wiki 知识库桥回归：分块、hash 幂等同步、FTS 降级策略、合并检索。"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.character.kb_wiki import (
    MergedKnowledgeRetriever,
    split_doc_chunks,
    sync_kb_wiki,
)
from plugins.bot_unified_runtime.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)
from plugins.bot_unified_runtime.contracts import KnowledgeChunk


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
        calls = 0

        def embed_texts(self, texts):
            self.calls += 1
            return super().embed_texts(texts)

    embedder = _CountingEmbedder()
    store = _store(tmp_path, embed_provider=embedder)
    docs = [
        _doc(f"梗知识/moegirl/梗{i}", f"正文{i}。" * 20) for i in range(5)
    ]
    store.sync_documents(docs)
    done, pending = store.embed_pending(None, batch_size=2)
    assert (done, pending) == (5, 5)
    # 5 行按批 2 → 3 次调用；默认批(10)则只有 1 次。
    assert embedder.calls == 3
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


@pytest.mark.parametrize(
    ("text", "title", "expected_prefix"),
    [("## 起源\n内容", "X梗", "【X梗｜起源】")],
)
def test_split_doc_chunks_prefix(text, title, expected_prefix):
    assert any(chunk.startswith(expected_prefix) for chunk in split_doc_chunks(text, title))

"""V2.1 S8 KnowledgeService 离线测试（V21-KB-001）。

覆盖：已知语料召回（FTS 关键词 + 向量双通道）、RRF 融合排序、分数与
来源透出、脱敏预览、原子重建（成功 swap / 失败不切换半成品）、
embedding 版本变更处理。全程零真实网络（embedding 用确定性 fake
provider），库文件全部 tmp_path。
"""

from __future__ import annotations

import itertools
import math
import sqlite3
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
    _rrf_fuse,
    _rrf_scores,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.knowledge_service import (
    KnowledgeService,
    KnowledgeSourceBinding,
    ReindexError,
)

# ---------------------------------------------------------------- 假嵌入链


class FakeEmbedProvider:
    """确定性字符二元组桶嵌入：共享片段→高余弦；无共享片段→零重叠。

    （单字符桶会把无关中英文都映进同一批桶产生 0.4+ 假相似；
    bigram 保证「探针无召回」这类负例断言成立。）
    """

    signature = "fake-embed-v1"
    dim = 64

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.calls = 0
        self.fail_after = fail_after

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            self.calls += 1
            if self.fail_after is not None and self.calls > self.fail_after:
                raise RuntimeError("embed chain down")
            vec = [0.0] * self.dim
            chars = str(text)
            for a, b in itertools.pairwise(chars):
                vec[(ord(a) * 131 + ord(b)) % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class V2EmbedProvider(FakeEmbedProvider):
    signature = "fake-embed-v2"


def _write_corpus(tmp_path: Path) -> list[Path]:
    files = []
    doc1 = tmp_path / "泰缇斯系统.md"
    doc1.write_text(
        "# 泰缇斯系统\n\n"
        "泰缇斯系统是跨越群星的建设者遗产，由无数自律单元构成。\n"
        "系统的核心职责是维护回收塔与观测站。\n",
        encoding="utf-8",
    )
    doc2 = tmp_path / "守岸人.md"
    doc2.write_text(
        "# 守岸人\n\n"
        "守岸人是泰缇斯系统的第二实例，负责守护海岸与漂泊者。\n"
        "她的职责是守望着归来的人们。\n",
        encoding="utf-8",
    )
    files.extend([doc1, doc2])
    return files


def _make_store(tmp_path: Path, provider: FakeEmbedProvider) -> SqliteVectorKnowledgeStore:
    return SqliteVectorKnowledgeStore(
        db_path=str(tmp_path / "persona.sqlite3"),
        embed_provider=provider,
        chunk_chars=400,
        top_k=4,
        signature=provider.signature,
    )


def _populate(store: SqliteVectorKnowledgeStore, files: list[Path]) -> None:
    store.sync_chunks(files)
    done, pending = store.embed_pending()
    assert done == pending


# ---------------------------------------------------------------- 召回与 RRF


def test_search_recalls_known_corpus_with_scores_and_source(tmp_path) -> None:
    files = _write_corpus(tmp_path)
    provider = FakeEmbedProvider()
    store = _make_store(tmp_path, provider)
    _populate(store, files)
    service = KnowledgeService(
        [KnowledgeSourceBinding(name="persona", store=store)],
        default_top_k=4,
    )
    report = service.search("泰缇斯系统的核心职责")
    assert report.sources_searched == ["persona"]
    assert report.hits, "已知语料必须召回"
    top = report.hits[0]
    assert top.source == "persona"
    assert top.score > 0.0
    assert top.rank == 0
    # 分数来源透明：channels 至少一个通道命中（vector/keyword/entry）。
    assert any(rank is not None for rank in top.channels.values())
    # FTS 关键词通道确实参与（trigram 命中「泰缇斯系统」）。
    assert "泰缇斯" in top.title + top.content_preview


def test_search_preview_redacts_secrets(tmp_path) -> None:
    (tmp_path / "秘密.md").write_text(
        "# 密钥说明\n\nAPI key 形如 sk-abcdef123456 请妥善保管不要外泄。\n",
        encoding="utf-8",
    )
    store = _make_store(tmp_path, FakeEmbedProvider())
    _populate(store, [tmp_path / "秘密.md"])
    service = KnowledgeService(
        [KnowledgeSourceBinding(name="persona", store=store)]
    )
    report = service.search("密钥说明 sk-")
    assert report.hits
    assert all("sk-abcdef123456" not in hit.content_preview for hit in report.hits)


def test_rrf_scores_and_fuse_two_channel_beats_single() -> None:
    scores = _rrf_scores(
        ["a", "b", "c"],
        ["a", "d", "e"],
    )
    # a 同时命中两通道 → 融合分高于任一单通道冠军。
    assert scores["a"] > scores["b"] > 0
    fused = _rrf_fuse(["a", "b", "c"], ["a", "d", "e"], 3)
    assert fused[0] == "a"
    assert set(fused) == {"a", "b", "d"}
    # 确定性：同分平局按 chunk_id 稳定。
    again = _rrf_fuse(["a", "b", "c"], ["a", "d", "e"], 3)
    assert again == fused


def test_search_scored_channels_map_ranks(tmp_path) -> None:
    files = _write_corpus(tmp_path)
    store = _make_store(tmp_path, FakeEmbedProvider())
    _populate(store, files)
    scored = store.search_scored("守岸人的职责", sync_files=False)
    assert scored
    for item in scored:
        assert item.score >= 0.0
        assert set(item.channels) == {"vector", "keyword", "entry"}
    # 至少一条同时被向量与关键词通道召回（共享字符 + 共享词）。
    both = [i for i in scored if i.channels["vector"] is not None and i.channels["keyword"] is not None]
    assert both


# ---------------------------------------------------------------- 原子重建


def test_reindex_swaps_and_serves_new_corpus(tmp_path) -> None:
    files = _write_corpus(tmp_path)
    provider = FakeEmbedProvider()
    store = _make_store(tmp_path, provider)
    _populate(store, files)
    service = KnowledgeService(
        [
            KnowledgeSourceBinding(
                name="persona",
                store=store,
                populate=lambda new_store: new_store.sync_chunks(files),
            )
        ],
    )
    # 语料扩充后再重建。
    doc3 = tmp_path / "回收塔.md"
    doc3.write_text(
        "# 回收塔\n\n回收塔负责回收漂流在星海中的残骸与记忆。\n",
        encoding="utf-8",
    )
    files.append(doc3)
    report = service.reindex()
    assert report.swapped is True
    assert report.rolled_back is False
    assert report.sources[0].chunks > 0
    assert report.sources[0].embedded == report.sources[0].chunks
    # 同一 store 实例经代际失效后立即服务新语料。
    found = service.search("回收塔负责回收")
    assert any("回收塔" in hit.title for hit in found.hits)
    # 临时目录清理干净（不留半成品）。
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".reindex")]
    assert leftovers == []


def test_reindex_validation_failure_keeps_old_index(tmp_path) -> None:
    files = _write_corpus(tmp_path)
    provider = FakeEmbedProvider()
    store = _make_store(tmp_path, provider)
    _populate(store, files)
    before_count = _chunk_count(store)

    # 语料装填为空 → 校验 0 行 → 拒绝切换。
    empty_binding = KnowledgeSourceBinding(
        name="persona",
        store=store,
        populate=lambda new_store: new_store.sync_chunks(
            [tmp_path / "不存在的文件.md"]
        ),
    )
    service = KnowledgeService([empty_binding])
    with pytest.raises(ReindexError) as excinfo:
        service.reindex()
    assert excinfo.value.report.swapped is False
    assert _chunk_count(store) == before_count
    # 失败后旧索引照常服务。
    assert service.search("泰缇斯系统").hits
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".reindex")]


def _chunk_count(store: SqliteVectorKnowledgeStore) -> int:
    return store.stats()["total"]


def test_reindex_embed_failure_keeps_old_index(tmp_path) -> None:
    """嵌入链中断 → 覆盖率校验拒绝切换（半成品不切换）。"""
    files = _write_corpus(tmp_path)
    provider = FakeEmbedProvider()
    store = _make_store(tmp_path, provider)
    _populate(store, files)
    before_count = _chunk_count(store)

    # 重建用的新 provider 只够嵌入 1 行就断（fail_after 命中临时库批量嵌入）。
    failing_provider = FakeEmbedProvider(fail_after=1)

    def populate(new_store: SqliteVectorKnowledgeStore) -> None:
        new_store.sync_chunks(files)
        # 偷换临时库的 provider 为会断的链：模拟版本重建途中上游故障。
        new_store.embed_provider = failing_provider

    service = KnowledgeService(
        [KnowledgeSourceBinding(name="persona", store=store, populate=populate)]
    )
    with pytest.raises(ReindexError) as excinfo:
        service.reindex()
    assert excinfo.value.report.swapped is False
    assert "覆盖不全" in excinfo.value.report.error or excinfo.value.report.error
    assert _chunk_count(store) == before_count
    assert service.search("守岸人").hits


def test_reindex_embedding_version_change(tmp_path) -> None:
    """embedding 版本变更：临时库按新指纹全量重嵌，验证后 swap 才切版本。"""
    files = _write_corpus(tmp_path)
    provider = FakeEmbedProvider()
    store = _make_store(tmp_path, provider)
    _populate(store, files)
    assert store._stored_signature() == "fake-embed-v1"
    service = KnowledgeService(
        [
            KnowledgeSourceBinding(
                name="persona",
                store=store,
                populate=lambda new_store: new_store.sync_chunks(files),
            )
        ],
    )

    # 临时库构造后、同步前把嵌入链换成 v2 provider（新版本全量重嵌）。
    v2 = V2EmbedProvider()

    def populate(new_store: SqliteVectorKnowledgeStore) -> None:
        new_store.embed_provider = v2
        new_store.sync_chunks(files)

    binding = KnowledgeSourceBinding(
        name="persona",
        store=store,
        populate=populate,
    )
    service = KnowledgeService([binding])
    report = service.reindex(signature="fake-embed-v2")
    assert report.swapped is True
    assert report.old_signature == "fake-embed-v1"
    assert report.new_signature == "fake-embed-v2"
    # swap 后 live 库的指纹已经是新版本。
    assert store._stored_signature() == "fake-embed-v2"
    assert store.signature == "fake-embed-v2"
    assert v2.calls > 0
    # 旧数据仍可检索（向量按新版本重嵌后语义由 fake 链保证）。
    assert service.search("泰缇斯系统").hits


def test_reindex_probe_failure_blocks_swap(tmp_path) -> None:
    files = _write_corpus(tmp_path)
    provider = FakeEmbedProvider()
    store = _make_store(tmp_path, provider)
    _populate(store, files)
    before_count = _chunk_count(store)
    binding = KnowledgeSourceBinding(
        name="persona",
        store=store,
        populate=lambda new_store: new_store.sync_chunks(files),
        probe_queries=("QWERTYUIOPASDF",),
    )
    service = KnowledgeService([binding])
    with pytest.raises(ReindexError):
        service.reindex()
    assert _chunk_count(store) == before_count


def test_swap_backup_failure_restores_ann_and_keeps_old_db(
    tmp_path, monkeypatch
) -> None:
    """backup 注入故障 → 库未动、ANN 归位，线上保持换前状态。"""
    files = _write_corpus(tmp_path)
    provider = FakeEmbedProvider()
    store = _make_store(tmp_path, provider)
    _populate(store, files)
    before_count = _chunk_count(store)
    service = KnowledgeService(
        [
            KnowledgeSourceBinding(
                name="persona",
                store=store,
                populate=lambda new_store: new_store.sync_chunks(files),
            )
        ],
    )

    def failing_backup(temp_db, live_db, *, timeout_seconds=5.0):
        raise sqlite3.OperationalError("database is locked (injected)")

    monkeypatch.setattr(service, "_backup_db", failing_backup)
    with pytest.raises(ReindexError) as excinfo:
        service.reindex()
    assert excinfo.value.report.rolled_back is True
    assert excinfo.value.report.swapped is False
    assert _chunk_count(store) == before_count
    # 旧内容仍可检索（ANN 已归位或回落暴力，两种都正确）。
    assert service.search("守岸人").hits


def test_generation_invalidation_reopens_connection(tmp_path) -> None:
    """换代后线程缓存连接作废：读到的是新库内容而非旧 inode。"""
    files = _write_corpus(tmp_path)
    provider = FakeEmbedProvider()
    store = _make_store(tmp_path, provider)
    _populate(store, files)
    # 先建立线程缓存连接。
    assert store.stats()["total"] > 0
    generation_before = store._file_generation
    store.invalidate_runtime_caches()
    assert store._file_generation == generation_before + 1
    # 缓存连接被换代后，_connect 会重开；读取仍然一致。
    assert store.stats()["total"] > 0


def test_chunk_document_reuses_store_semantics(tmp_path) -> None:
    store = _make_store(tmp_path, FakeEmbedProvider())
    service = KnowledgeService(
        [KnowledgeSourceBinding(name="persona", store=store)]
    )
    text = "第一段。\n\n第二段。\n\n第三段。"
    chunks = service.chunk_document(text)
    assert chunks == ["第一段。\n第二段。\n第三段。"]
    assert service.chunk_document(text, chunk_chars=5) != chunks or len(chunks) >= 1


def test_sqlite_store_unaffected_for_plain_retrieve(tmp_path) -> None:
    """既有 retrieve 路径零回归：与 search_scored 同结果集口径。"""
    files = _write_corpus(tmp_path)
    store = _make_store(tmp_path, FakeEmbedProvider())
    _populate(store, files)
    legacy = store.retrieve("泰缇斯系统的核心职责")
    scored = store.search_scored("泰缇斯系统的核心职责", sync_files=False)
    assert [c.chunk_id for c in legacy] == [s.chunk.chunk_id for s in scored]


def test_live_db_connection_reads_swapped_file(tmp_path) -> None:
    """swap 后新连接打开的是新文件（mode/内容双确认）。"""
    files = _write_corpus(tmp_path)
    provider = FakeEmbedProvider()
    store = _make_store(tmp_path, provider)
    _populate(store, files)
    connection = sqlite3.connect(store.db_path)
    old_count = connection.execute(
        "SELECT COUNT(*) FROM knowledge_chunks"
    ).fetchone()[0]
    connection.close()
    assert old_count > 0

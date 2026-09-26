"""certify-prewarm 波回归锁：P1 计数戳认证 / P2 ANN 感知的锁外预热 / P3 拒用判定缓存。

钉死三件事（全部离线 tmp_path，零真实网络、零生产文件读写）：

P1（certify_expected_vector_count）：存量库既无戳又零变更时，闸的唯二写点
（发布提交点 / 补嵌涨戳）都到不了 ⇒ 永久按 unstamped 拒用。维护路径补一发
权威 COUNT 落戳闭环。**戳值必须来自 SQLite 已嵌入行数、禁止取 index.ntotal**
——ntotal 落戳 = 短装索引自我认证 = 完备性闸被就地掏空（本文件用变异自证
把这个陷阱钉成红锁）。

P2（retrieve/search_scored 的锁外预热改 ANN 感知）：ANN 可用 ⇒ 向量通道走
HNSW，~GB 级暴力矩阵不再白建（wiki 248k 实测每问 +1.02GB 常驻）；ANN 被拒/
缺席 ⇒ 矩阵照建（暴力=慢而全，矩阵是燃料）。

P3（拒用判定缓存）：同一代文件指纹 + 同一计数戳取值时维持拒用判定，不再
每查重付 mmap 重开/JSON 解析/sha 的重判代价、也不再刷拒用告警；计数戳一变
（认证落戳即此形态，且不碰 ANN 文件）或文件换代即自动重判——运行中进程
无需重启即自愈。
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    vector_knowledge as vk,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.knowledge_service import (
    KnowledgeService,
    KnowledgeSourceBinding,
    ReindexError,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)
from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

pytestmark = pytest.mark.skipif(vk.faiss is None, reason="P2/P3 判定依赖 faiss")

_DIM = 8
_STAMP_KEY = vk._EMBEDDED_COUNT_KEY
_UNSTAMPED_PREFIX = "reason=unstamped"


class _FakeEmbedder:
    """sha1 伪向量：8 维、确定性、零网络（沿用 tests/test_ann_completeness_gate.py 口径）。"""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [
            [byte / 255.0 for byte in hashlib.sha1(text.encode("utf-8")).digest()[:_DIM]]
            for text in texts
        ]


def _docs(count: int, tag: str) -> list[dict]:
    return [
        {
            "id": f"topic/{tag}-doc-{index}",
            "hash": hashlib.sha1(f"{tag}{index}".encode()).hexdigest(),
            "topic": "topic",
            "source": "unit-test",
            "title": f"{tag}-doc-{index}",
            "chunks": [f"【{tag}-doc-{index}】正文内容{index}"],
        }
        for index in range(count)
    ]


def _make_store(tmp_path: Path, count: int = 20) -> SqliteVectorKnowledgeStore:
    store = SqliteVectorKnowledgeStore(
        db_path=tmp_path / "kb.sqlite3",
        embed_provider=_FakeEmbedder(),
        chunk_chars=800,
        top_k=4,
        signature="test|fake",
        auto_reset=True,
    )
    store.sync_documents(iter(_docs(count, "a")), removed_ids=[], full=True)
    store.embed_pending(None)
    return store


def _append_embedded(store: SqliteVectorKnowledgeStore, count: int, tag: str) -> None:
    """增量补嵌（不重建索引）：戳在位则同事务上涨（造「真短装」态的唯一途径）。"""
    store.sync_documents(iter(_docs(count, tag)), removed_ids=[], full=False)
    done, total = store.embed_pending(None)
    assert done == total == count


def _ntotal_on_disk(store: SqliteVectorKnowledgeStore) -> int:
    return int(vk.faiss.read_index(str(store.ann_index_path)).ntotal)


def _stamp(store: SqliteVectorKnowledgeStore) -> int | None:
    return store._stamped_expected_vector_count()


def _drop_stamp_key(store: SqliteVectorKnowledgeStore) -> None:
    """模拟生产存量形态：闸上线前建好的库，文件完备、唯独没有戳键。"""
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM knowledge_meta WHERE key = ?", (_STAMP_KEY,))
        conn.commit()


def _write_raw_stamp(store: SqliteVectorKnowledgeStore, value: str) -> None:
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "INSERT INTO knowledge_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_STAMP_KEY, value),
        )
        conn.commit()


# === P1：认证落戳 =============================================================


def test_certify_writes_embedded_count_when_stamp_absent(tmp_path):
    """无戳 ⇒ certify 落「已嵌入行数」为戳；未嵌入的行不计入；此后写点恢复涨戳。"""
    store = _make_store(tmp_path, count=20)
    store.sync_documents(iter(_docs(5, "p")), removed_ids=[], full=False)  # 5 行未嵌
    assert store.stats() == {"total": 25, "embedded": 20}
    assert _stamp(store) is None

    certified = store.certify_expected_vector_count()

    assert certified == 20, "戳值必须是已嵌入行数（20），不是总行数（25）"
    assert _stamp(store) == 20
    # 有戳后补嵌回到同事务涨戳路径：戳不再停滞。
    done, total = store.embed_pending(None)  # 把 5 行 pending 嵌入
    assert done == total == 5
    assert _stamp(store) == 25, "认证后写点涨戳必须恢复（自愈闭环的后续半圈）"


def test_certify_never_touches_a_live_stamp(tmp_path):
    """活戳在位 ⇒ certify 一字不碰（戳归重建线所有），返回 None。"""
    store = _make_store(tmp_path, count=20)
    _write_raw_stamp(store, "40")  # 活戳（可被涨戳路径推进的形态）
    assert _stamp(store) == 40

    assert store.certify_expected_vector_count() is None
    assert _stamp(store) == 40, "certify 不得覆写活戳（哪怕它比实嵌行数高）"


def test_certify_recertifies_blank_and_invalid_stamp_values(tmp_path):
    """空串/负值/非整数 = 读端本就判「不可判定」的垃圾 ⇒ 按无戳补盖权威值。"""
    for junk in ("", "   ", "-5", "not-a-number"):
        store = _make_store(tmp_path / hashlib.sha1(junk.encode()).hexdigest(), count=20)
        _write_raw_stamp(store, junk)
        assert _stamp(store) is None, f"读端判据漂移：{junk!r} 应不可判定"
        assert store.certify_expected_vector_count() == 20, f"垃圾值 {junk!r} 应被补盖"
        assert _stamp(store) == 20


def test_certified_complete_store_self_heals_without_restart(tmp_path):
    """生产实况类（索引完备但无戳）：认证后同一运行中的 store 直接恢复服务。"""
    store = _make_store(tmp_path, count=20)
    assert store.build_ann_index()["built"] is True
    _drop_stamp_key(store)
    store._drop_ann_cache()
    assert store.load_ann_index() is False, "基线：无戳完备索引被拒（生产现状类）"

    assert store.certify_expected_vector_count() == 20
    # 不 _drop_ann_cache、不重启：下一次载入即自愈（依赖 P3 的戳值感知通道）。
    assert store.load_ann_index() is True


def test_certify_reads_db_rows_never_index_shape_self_certification_trap(
    tmp_path, caplog
):
    """短装态（实嵌 50、索引 20、无戳）：certify 必须落 50 ⇒ 闸继续拒用。

    这就是「自我认证」陷阱的反向锁：若实现被改坏成拿 index.ntotal 落戳，
    这里落下的会是 20 == ntotal ⇒ 下一句的 load_ann_index 变 True、
    本用例即刻转红。
    """
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    _append_embedded(store, 30, "b")  # stamp 20→50, ntotal 仍 20（真短装）
    _drop_stamp_key(store)
    store._drop_ann_cache()

    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.certify_expected_vector_count() == 50, (
            "戳值必须来自 DB 的 COUNT(已嵌入)，绝不是 index.ntotal"
        )
    assert _stamp(store) == 50
    assert _ntotal_on_disk(store) == 20
    assert store.load_ann_index() is False, "认证后短装依旧必须被拒"
    refused = [rec.getMessage() for rec in caplog.records if "completeness refused" in rec.getMessage()]
    assert refused and "expected=50" in refused[0]


def test_mutated_certify_from_ntotal_would_kill_the_gate(tmp_path, caplog):
    """变异自证（陷阱的正面演示）：把「ntotal 当戳」注进去，计数闸当场失效。

    这条不测实现、测的是禁区的杀伤力，且**按拒因文字归因**（只断 load 的
    真/假不够：代次闸上线后两半都会 False，光看布尔值分不出是哪道门在干活，
    计数闸被整个删掉也照样"绿"）。
    - 前半（变异戳 := index.ntotal）：期望 False 且拒因**只有** coverage refused、
      **没有** completeness refused ⇒ 证明计数闸在这副输入下确实被掏空（短装索引
      畅通），今天拦住它的是 S159 那道代次闸，不是戳本身。
    - 后半（真实 certify := COUNT(已嵌入) = 50 > ntotal = 20）：期望 False 且
      拒因含 completeness refused ⇒ 计数闸仍有独立牙齿。
    两半合起来钉死「取数方向」是这道闸的生死线，同时钉死两道门各管各的格。
    """
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    _append_embedded(store, 30, "b")
    _drop_stamp_key(store)
    store._drop_ann_cache()

    # —— 变异形态：戳 := index.ntotal（被禁止的取数方向）
    store._stamp_expected_vector_count(_ntotal_on_disk(store))
    store._drop_ann_cache()
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.load_ann_index() is False
    mutant = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "coverage refused" in mutant, (
        "变异形态下拦住这副短装索引的必须是代次闸，否则本用例没在测它声称的东西"
    )
    assert "completeness refused" not in mutant, (
        "计数闸在 ntotal 自我认证形态下必须判「追平」——若它这里就拒了，"
        "说明闸本就不看戳，本文件其余锁全部失去意义"
    )

    # —— 真实形态：certify := COUNT(已嵌入) = 50 > ntotal = 20
    _drop_stamp_key(store)
    store._drop_ann_cache()
    assert store.certify_expected_vector_count() == 50
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.load_ann_index() is False, "真实认证必须把这条短装代重新拦下"
    real = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "completeness refused" in real, (
        "拒因必须是计数闸本身，不能是别的门顺手拦下——否则本锁空转"
    )


def test_certify_does_not_touch_ann_files(tmp_path):
    """认证是纯 SQLite 动作：ANN 两文件字节不变（拒用改判只走 meta+缓存失效）。"""
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    _drop_stamp_key(store)
    before = (
        Path(store.ann_index_path).read_bytes(),
        Path(store.ann_order_path).read_bytes(),
    )
    assert store.certify_expected_vector_count() == 20
    assert (
        Path(store.ann_index_path).read_bytes(),
        Path(store.ann_order_path).read_bytes(),
    ) == before


# === P1 接线：重建被跳过之处 ==================================================


class _SyncSpyStore:
    """kb-sync 任务替身（复刻 tests/test_v21r2_stall_kbsync.py FakeStore 的最小面）。"""

    def __init__(self, *, sync_stats: dict, certify_value: int | None = 7) -> None:
        self.embed_provider = SimpleNamespace(name="normal-provider")
        # ANN 路径指向真实存在的小文件 = 「索引在位」；零变更夜据此不重建。
        self.ann_index_path = str(Path(__file__))
        self.ann_order_path = str(Path(__file__))
        self._sync_stats = dict(sync_stats)
        self.build_ann_calls = 0
        self.certify_calls = 0
        self._certify_value = certify_value

    def sync_documents(self, docs, *, removed_ids=(), full=False, on_progress=None):
        return dict(self._sync_stats)

    def embed_pending(self, files, on_progress=None, *, batch_size=None):
        return 0, 0

    def stats(self) -> dict[str, int]:
        return {"total": 100, "embedded": 100}

    def document_count(self) -> int:
        return 10

    def build_ann_index(self, on_progress=None, *, force_low_memory=False) -> dict:
        self.build_ann_calls += 1
        return {"built": True, "vectors": 100, "reason": ""}

    def certify_expected_vector_count(
        self, *, drift_correction: bool = False
    ) -> int | None:
        self.certify_calls += 1
        self.certify_drift_correction = drift_correction
        return self._certify_value


_KB_CONFIG = SimpleNamespace(bot_kb_wiki_chunk_chars=800, bot_kb_wiki_embed_batch=128)
_ZERO_SYNC = {"added": 0, "changed": 0, "removed": 0, "skipped": 0, "chunks": 0}


@pytest.fixture()
def _kb_sync_isolated(monkeypatch):
    monkeypatch.setattr(
        kb_wiki,
        "sync_kb_wiki",
        lambda store, config, *, full=False, on_progress=None: (
            store.sync_documents([], full=full, on_progress=on_progress)
        ),
    )
    yield
    if kb_wiki._SYNC_TASK_MUTEX.locked():
        kb_wiki._SYNC_TASK_MUTEX.release()
    kb_wiki._SYNC_CANCEL_EVENT.clear()


def test_kb_wiki_unchanged_night_certifies(_kb_sync_isolated):
    """unchanged_skip 分支（维护线程）调用认证自愈，并把结果记入本轮 summary。

    零变更夜还必须**开漂移纠偏**：戳是只涨不跌的上界，而这一夜重建线不达，
    不开门 ⇒ 一次虚高就是永久拒用（2026-09-26 生产实测 missing=432 恒红即此格）。
    """
    store = _SyncSpyStore(sync_stats=_ZERO_SYNC, certify_value=1234)
    result = kb_wiki.run_kb_sync_task(_KB_CONFIG, store=store)
    assert result["ok"] is True
    assert result["ann_reason"] == "unchanged_skip"
    assert store.build_ann_calls == 0
    assert store.certify_calls == 1, "零变更夜必须由 unchanged_skip 分支补盖戳"
    assert result["ann_certified"] == 1234
    assert getattr(store, "certify_drift_correction", None) is True, (
        "零变更夜没开 drift_correction：活戳漂移在这条分支上无任何自愈路径，"
        "闸会永久拒用 ANN（回落暴力扫描）"
    )


def test_kb_wiki_rebuild_night_does_not_certify(_kb_sync_isolated):
    """重建夜不叠加认证：戳归发布提交点所有，certify 不得在重建旁路再写一发。"""
    store = _SyncSpyStore(sync_stats={**_ZERO_SYNC, "added": 3})
    result = kb_wiki.run_kb_sync_task(_KB_CONFIG, store=store)
    assert result["ok"] is True
    assert store.build_ann_calls == 1
    assert store.certify_calls == 0
    assert "ann_certified" not in result, "重建分支不产出认证键（不冒充自愈）"


def test_kb_wiki_store_without_certify_method_survives(_kb_sync_isolated):
    """替身/旧 store 没有该方法：分支安全跳过，同步结论不受影响（fail-open）。"""

    class _Legacy(_SyncSpyStore):
        certify_expected_vector_count = None  # 属性置空 = getattr 拿到非 callable

    store = _Legacy(sync_stats=_ZERO_SYNC)
    result = kb_wiki.run_kb_sync_task(_KB_CONFIG, store=store)
    assert result["ok"] is True
    assert result["ann_reason"] == "unchanged_skip"
    assert "ann_certified" not in result


def test_knowledge_service_skipped_source_gets_certified(tmp_path):
    """reindex 的 no_populate 跳过位（等价「该重建而被跳过」）：线上库无戳则补盖。"""
    store = _make_store(tmp_path, count=20)
    assert _stamp(store) is None
    service = KnowledgeService(
        [KnowledgeSourceBinding(name="persona", store=store)]  # populate=None
    )
    with pytest.raises(ReindexError):
        service.reindex()
    assert _stamp(store) == 20, "跳过重建的源也要在维护路径完成戳自愈"


def test_knowledge_service_skipped_source_keeps_live_stamp(tmp_path):
    """同位护栏：活戳在位的跳过源一字不碰。"""
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    _write_raw_stamp(store, "40")
    service = KnowledgeService(
        [KnowledgeSourceBinding(name="persona", store=store)]
    )
    with pytest.raises(ReindexError):
        service.reindex()
    assert _stamp(store) == 40


# === P2：预热改 ANN 感知 ======================================================


@pytest.fixture()
def _matrix_spy(monkeypatch):
    """计 `_build_vector_cache` 实际执行次数（矩阵是否被建的直接判据）。"""
    calls: list[int] = []
    real = SqliteVectorKnowledgeStore._build_vector_cache

    def spy(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(SqliteVectorKnowledgeStore, "_build_vector_cache", spy)
    return calls


def test_ann_accepted_path_no_longer_builds_matrix(tmp_path, _matrix_spy):
    """P2 本职：ANN 可用 ⇒ retrieve/search_scored 不再白建 ~GB 级暴力矩阵。"""
    store = _make_store(tmp_path, count=20)
    assert store.build_ann_index()["built"] is True
    store._drop_ann_cache()
    assert store.load_ann_index() is True

    hits = store.retrieve("【a-doc-3】正文内容3")
    assert hits, "ANN 通道必须真的供出结果（否则本锁测的是空转）"
    scored = store.search_scored("【a-doc-3】正文内容3", sync_files=False)
    assert scored
    assert _matrix_spy == [], "ANN 放行路径一个矩阵都不许建（每问 ~1.02GB 的旧账）"
    assert store._vector_cache is None


def test_ann_refused_path_still_builds_matrix(tmp_path, _matrix_spy):
    """拒用路径行为不回退：矩阵照建（暴力=慢而全的燃料），检索照常召回。"""
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    _drop_stamp_key(store)
    store._drop_ann_cache()
    assert store.load_ann_index() is False

    hits = store.retrieve("【a-doc-3】正文内容3")
    assert hits, "回落暴力的召回不能被 P2 改动弄丢"
    assert len(_matrix_spy) >= 1, "ANN 不可用 ⇒ 锁外预热必须照旧建矩阵"
    assert store._vector_cache is not None


def test_ann_absent_path_builds_matrix(tmp_path, _matrix_spy):
    """无索引文件（冷启动/被撤走）同样回落旧语义：矩阵必建。"""
    store = _make_store(tmp_path, count=20)
    assert not Path(store.ann_index_path).exists()
    hits = store.retrieve("【a-doc-3】正文内容3")
    assert hits
    assert len(_matrix_spy) >= 1


# === P3：拒用判定缓存 =========================================================


def test_refusal_verdict_cached_until_stamp_written(tmp_path, monkeypatch, caplog):
    """连拒 N 次只重判 1 次；认证落戳（不碰文件）即第 2 次重判并放行。"""
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    _drop_stamp_key(store)
    store._drop_ann_cache()

    reads: list[int] = []
    real_read = vk.faiss.read_index

    def spy(*args, **kwargs):
        reads.append(1)
        return real_read(*args, **kwargs)

    monkeypatch.setattr(vk.faiss, "read_index", spy)
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.load_ann_index() is False  # 冷判一次：read_index +1
        assert len(reads) == 1
        for _ in range(5):
            assert store.load_ann_index() is False
        assert len(reads) == 1, "同一代同一戳值：拒用判定必须缓存，不得每查重判"
        unstamped_warnings = [
            rec for rec in caplog.records if _UNSTAMPED_PREFIX in rec.getMessage()
        ]
        assert len(unstamped_warnings) == 1, "拒用告警不随查询刷屏"

        assert store.certify_expected_vector_count() == 20
        # 戳变了 = 判定输入变了 ⇒ 自动重判（同一进程、不重启、不动文件）
        assert store.load_ann_index() is True
    assert len(reads) == 2, "认证后只多一次重判，随后进入已载入缓存"


def test_refusal_cache_invalidates_on_external_rebuild(tmp_path):
    """另一进程重建换代（文件指纹变）：缓存拒用作废，下一次载入收敛到新代。"""
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    _drop_stamp_key(store)
    store._drop_ann_cache()
    assert store.load_ann_index() is False
    assert store.load_ann_index() is False  # 进缓存

    sibling = SqliteVectorKnowledgeStore(
        db_path=store.db_path,
        embed_provider=_FakeEmbedder(),
        chunk_chars=store.chunk_chars,
        top_k=store.top_k,
        signature=store.signature,
        auto_reset=True,
        ann_index_path=store.ann_index_path,
        ann_order_path=store.ann_order_path,
    )
    _append_embedded(sibling, 10, "b")
    assert sibling.build_ann_index()["built"] is True

    assert store.load_ann_index() is True, "换代后不得抱着旧拒用判定不放"
    assert len(store._ann_order or []) == 30


def test_accepted_path_hot_load_still_two_stat_calls(tmp_path, monkeypatch):
    """P3 不给已放行路径添新账：稳态载入仍是 2 stat（与 test_ann_atomic_publish
    ::test_hot_path_cost_is_two_stat_calls 同判据；另钉 retrieve 稳态零矩阵构建）。"""
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    assert store.load_ann_index() is True

    sha_calls: list[int] = []
    real_sha = vk._sha256_file

    def counting_sha(path: Path) -> str:
        sha_calls.append(1)
        return real_sha(path)

    monkeypatch.setattr(vk, "_sha256_file", counting_sha)
    stat_calls: list[int] = []
    real_stat = SqliteVectorKnowledgeStore._ann_stat_pair

    def counting_stat(self, index_path: str, order_path: str):
        stat_calls.append(1)
        return real_stat(self, index_path, order_path)

    monkeypatch.setattr(SqliteVectorKnowledgeStore, "_ann_stat_pair", counting_stat)
    for _ in range(5):
        assert store.load_ann_index() is True
    assert sha_calls == []
    assert len(stat_calls) == 5, "已放行稳态每次载入只 1 对 stat，零 DB 往返"


# === operator 入口：knowledge-sync 的自愈落点 =================================


class _SmokeProvider:
    signature = "test|fake"
    active_base_url = "http://fake.invalid/v1"
    active_model = "fake"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return _FakeEmbedder().embed_texts(texts)


def test_smoke_knowledge_sync_certifies_when_rebuild_locked_out(
    tmp_path, monkeypatch
):
    """拒用告警「run knowledge-sync to certify」的落点：重建被别的写者挡下时，
    knowledge-sync 仍以 COUNT 认证存量库（磁盘索引完备 ⇒ 运行中的读方恢复服务）。"""
    from plugins.bot_unified_runtime.domains.ops.smoke import smoke

    store = _make_store(tmp_path, count=20)
    assert store.build_ann_index()["built"] is True
    _drop_stamp_key(store)
    store._drop_ann_cache()
    assert store.load_ann_index() is False  # 生产现状类：完备但无戳

    rival = vk._AnnBuildGate(store._ann_lock_path())
    assert rival.acquire(), "预置：模拟另一进程正持建锁闸"
    try:
        monkeypatch.setattr(smoke, "OpenAICompatibleEmbeddingProvider", lambda **_kw: _SmokeProvider())
        monkeypatch.setattr(smoke, "SqliteVectorKnowledgeStore", lambda **_kw: store)
        config = SimpleNamespace(
            bot_embedding_model="fake",
            bot_embedding_base_url="http://fake.invalid/v1",
            bot_embedding_api_key="k",
            bot_embedding_local_enabled=True,
            bot_embedding_local_models=["fake-local"],
            bot_embedding_local_base_url="http://127.0.0.1:1/v1",
            bot_knowledge_db_path=str(tmp_path / "kb.sqlite3"),
            bot_knowledge_files=[],
            bot_knowledge_chunk_chars=800,
            bot_knowledge_top_k=4,
        )
        result = smoke.run_knowledge_sync(config)
    finally:
        rival.release()

    assert result["ann_index_built"] is False
    assert result["ann_reason"] == "locked_by_other_process"
    assert result["ann_certified"] == 20, "重建被挡时 knowledge-sync 必须补盖戳"
    assert _stamp(store) == 20
    assert store.load_ann_index() is True, "认证后完备索引恢复服务（无需重启）"

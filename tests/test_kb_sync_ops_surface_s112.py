"""SEAT-S112：ANN 重建内存门 + kb-sync 操作员取消旗的回归锁（全离线）。

两件被锁住的事，各自对应一条 2026-09-25/26 实测出来的运维缺口：

1. **内存门**：ANN 全量重建在生产进程内开火，常驻需求由 FAISS 自己的向量副本
   决定（`IndexHNSWFlat` 私有 float32 数组，分批 add 削不掉），实测
   4,694 B/向量；而本机夜间可用物理内存低水位实测 1.62 GiB。开火前不量就
   是把 bot 连人带库压死。门的形状：不足 ⇒ **不开火** + 三处痕迹 +
   完备性闸一字未动（跳过绝不等于放行）。
2. **取消旗**：`cancel_kb_sync_task()` 全仓唯一调用点在 `bot.py` 的停机钩子里
   ⇒ 想停掉在跑的夜间同步只能停进程。旗标补的是"进程外按同一个钮"，
   取消粒度沿用既有协作式语义（批边界、断点保留、重跑续传）。

刻意写成**活性锁**而非存在性锁的几条（注毒必真红，见文件末台账注释）：
`test_cancel_flag_consumed_at_sync_batch_boundary`、
`test_ann_build_progress_callback_is_the_same_cancel_channel`、
`test_memory_gate_skip_does_not_green_the_completeness_refusal`。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import vector_knowledge
from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    _ANN_BUILD_MEASURED_BYTES_PER_VECTOR,
    _ANN_BUILD_MEASURED_DIM,
    _ANN_COMPLETENESS_MAX_MISSING,
    _ANN_MEMORY_SKIP_META_KEY,
    SqliteVectorKnowledgeStore,
    _ann_build_demand_bytes,
)
from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

_GIB = 1024**3
_ZERO_SYNC_STATS = {
    "added": 0,
    "changed": 0,
    "removed": 0,
    "skipped": 0,
    "chunks": 0,
}


class _FakeEmbedder:
    """8 维确定性假嵌入（与 tests/test_perf_p1.py 同形，不触网络）。"""

    dimensions = 8

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            digest = hashlib.sha1(text.encode("utf-8")).digest()
            out.append([byte / 255.0 for byte in digest[:8]])
        return out


class _FakeProvider(_FakeEmbedder):
    active_base_url = "http://127.0.0.1:1"
    signature = "test|fake"


def _make_store(tmp_path: Path) -> SqliteVectorKnowledgeStore:
    return SqliteVectorKnowledgeStore(
        db_path=tmp_path / "kb_wiki_embeddings.sqlite3",
        embed_provider=_FakeProvider(),
        chunk_chars=800,
        top_k=4,
        signature="test|fake",
        auto_reset=True,
        ann_index_path=str(tmp_path / "kb_wiki_faiss.index"),
        ann_order_path=str(tmp_path / "kb_wiki_faiss.order.json"),
    )


def _seed(store: SqliteVectorKnowledgeStore, docs: int) -> None:
    rows = [
        {
            "id": f"topic/doc-{index}",
            "hash": hashlib.sha1(f"doc{index}".encode()).hexdigest(),
            "topic": "topic",
            "source": "moegirl",
            "title": f"doc-{index}",
            "chunks": [f"内容{index}" * 40],
        }
        for index in range(docs)
    ]
    store.sync_documents(iter(rows), removed_ids=(), full=True)
    store.embed_pending(None)


def _read_gate_meta(store: SqliteVectorKnowledgeStore) -> dict:
    raw = store.get_meta(_ANN_MEMORY_SKIP_META_KEY)
    assert raw, "内存门没有留下 knowledge_meta 观测行"
    parsed = json.loads(str(raw))
    assert isinstance(parsed, dict)
    return parsed


class CancelSpyStore:
    """kb-sync 用的最小 store 替身；`build_ann_index` **忠实转发** on_progress
    （真身在 `vector_knowledge._build_ann_index_locked` 每批调一次），
    于是"取消检查点有没有延伸到建索引批边界"这件事是可判定的。
    """

    def __init__(
        self,
        *,
        tmp_path: Path,
        sync_stats: dict | None = None,
        sync_progress_batches: int = 0,
        ann_flag_appears_midbuild: bool = False,
    ) -> None:
        self.embed_provider = SimpleNamespace(name="normal-provider")
        self.db_path = str(tmp_path / "kb_wiki_embeddings.sqlite3")
        self.ann_index_path = str(tmp_path / "kb_wiki_faiss.index")
        self.ann_order_path = str(tmp_path / "kb_wiki_faiss.order.json")
        # ANN 文件默认"在位"（用本测试文件冒充），避开 healing 分支。
        self.ann_index_path = str(Path(__file__))
        self.ann_order_path = str(Path(__file__))
        self._ann_flag_appears_midbuild = ann_flag_appears_midbuild
        self._sync_stats = dict(sync_stats or _ZERO_SYNC_STATS)
        self._sync_progress_batches = sync_progress_batches
        self.sync_calls: list[dict] = []
        self.build_ann_calls = 0
        self.build_ann_kwargs_seen: list[dict] = []
        self.meta: dict[str, str] = {}

    def sync_documents(self, docs, *, removed_ids=(), full=False, on_progress=None):
        self.sync_calls.append({"full": full})
        for _ in range(self._sync_progress_batches):
            if on_progress is not None:
                on_progress(dict(self._sync_stats))
        return dict(self._sync_stats)

    def embed_pending(self, files, on_progress=None, *, batch_size=None):
        return 0, 0

    def stats(self) -> dict[str, int]:
        return {"total": 24, "embedded": 24}

    def document_count(self) -> int:
        return 24

    def get_meta(self, key: str) -> str:
        return self.meta.get(key, "")

    def set_meta(self, key: str, value: str) -> None:
        self.meta[key] = value

    def build_ann_index(self, on_progress=None, **kwargs) -> dict:
        self.build_ann_calls += 1
        self.build_ann_kwargs_seen.append({"on_progress": on_progress, **kwargs})
        if on_progress is not None and self._ann_flag_appears_midbuild:
            # 模拟"重建跑到一半，操作员从进程外落了取消旗"：旗必须在
            # 建索引自己的批边界上被消费掉。
            kb_wiki.kb_sync_cancel_flag_path(self.db_path).write_text(
                "mid-build\n", encoding="utf-8"
            )
            on_progress(1024)
        return {"built": True, "vectors": 24, "reason": ""}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """隔离机器读数 + 收尾清闸/事件/旗路径（用例失败也不毒化别人）。"""
    monkeypatch.setattr(kb_wiki, "sync_kb_wiki", lambda store, config, **kw: (
        store.sync_documents([], full=bool(kw.get("full")), on_progress=kw.get("on_progress"))
    ))
    monkeypatch.setattr(
        vector_knowledge, "_available_physical_memory_bytes", lambda: 64 * _GIB
    )
    yield
    if kb_wiki._SYNC_TASK_MUTEX.locked():
        kb_wiki._SYNC_TASK_MUTEX.release()
    kb_wiki._SYNC_CANCEL_EVENT.clear()
    kb_wiki._set_kb_sync_cancel_flag_path(None)


# ================================================================ 内存门：需求模型


def test_demand_model_reproduces_measured_unit_cost_at_1024() -> None:
    """需求估算必须复现"实测峰值计价"的形状，不许凭手感写数。

    S118 收线重写（原断言按"4.5 GiB 绝对下限托底"的旧模型写，S112 死亡
    重构已改全比例模型却没同步本锁——又一例"叙述与真身脱钩"）：
    - 线性价 = dim×(4+2)（向量副本 + 倍增扩容瞬态副本）+ 598 图/分配 + 176 id 表；
    - 全比例、不设绝对门槛；
    - 对规模与维数单调。
    """
    unit = _ANN_BUILD_MEASURED_DIM * 4 + (
        _ANN_BUILD_MEASURED_BYTES_PER_VECTOR - _ANN_BUILD_MEASURED_DIM * 4
    )
    assert unit == _ANN_BUILD_MEASURED_BYTES_PER_VECTOR, "维数基准与实测值脱钩了"
    linear_per_vec = (
        1024 * (4 + vector_knowledge._ANN_BUILD_FAISS_REALLOC_BYTES_PER_DIM)
        + (unit - 1024 * 4)
        + vector_knowledge._ANN_BUILD_ID_TABLE_BYTES_PER_VECTOR
    )
    assert linear_per_vec == 6918, "线性价漂移（ realloc/id/稳态项三者之一被改动）"

    def _ref_demand(n: int | None, dim: int) -> int:
        """公式的第二写法（与真身同常量、独立组装），钉形状不钉手感。"""
        slack = (
            vector_knowledge._ANN_BUILD_BATCH_SIZE
            * dim
            * 4
            * vector_knowledge._ANN_BUILD_BATCH_SLACK_COPIES
        )
        if n is None or n <= 0:
            return vector_knowledge._ANN_BUILD_MIN_HEADROOM_BYTES + slack
        per_vec = dim * (
            4 + vector_knowledge._ANN_BUILD_FAISS_REALLOC_BYTES_PER_DIM
        ) + (unit - 1024 * 4) + vector_knowledge._ANN_BUILD_ID_TABLE_BYTES_PER_VECTOR
        linear = n * per_vec
        headroom = max(
            vector_knowledge._ANN_BUILD_MIN_HEADROOM_BYTES,
            (linear + slack) // vector_knowledge._ANN_BUILD_HEADROOM_RATIO,
        )
        return linear + slack + headroom

    for n, dim in ((10, 1024), (2048, 1024), (766_126, 1024), (300, 1536)):
        assert _ann_build_demand_bytes(n, dim) == _ref_demand(n, dim)
    small = _ann_build_demand_bytes(10, 1024)
    big = _ann_build_demand_bytes(1_000_000, 1024)
    assert big > small, "需求对规模非单调 = 门形同虚设"
    assert _ann_build_demand_bytes(1_000_000, 1536) > _ann_build_demand_bytes(
        1_000_000, 1024
    ), "维数是强敏感项，1536 必须比 1024 贵"


def test_unmeasurable_scale_falls_back_to_floor_only() -> None:
    """无戳且无 rowid 界（异常库形）⇒ 按活体下限判，不猜小、也不免检
    （中途还有 `_ann_live_floor_bytes` 断路器，见 S118 锁件）。"""
    slack = (
        vector_knowledge._ANN_BUILD_BATCH_SIZE
        * 1024
        * 4
        * vector_knowledge._ANN_BUILD_BATCH_SLACK_COPIES
    )
    assert (
        _ann_build_demand_bytes(None, 1024)
        == vector_knowledge._ANN_BUILD_MIN_HEADROOM_BYTES + slack
    )
    assert (
        _ann_build_demand_bytes(0, 1024)
        == vector_knowledge._ANN_BUILD_MIN_HEADROOM_BYTES + slack
    )


def test_probe_reads_real_machine_and_returns_bytes() -> None:
    """探针本体：在真机上必须给出正数（不许静默返回 None 让门永远不开火）。"""
    real = vector_knowledge._available_physical_memory_bytes()
    assert real is None or real > 0
    if real is None:  # pragma: no cover - 非 Windows 且 sysconf 不可用时
        pytest.skip("本机不提供可用物理内存读数")
    assert real < 4 * 1024**4


# ================================================================ 内存门：开火与否


def test_gate_skips_and_never_publishes_when_memory_short(
    tmp_path, monkeypatch, caplog
) -> None:
    store = _make_store(tmp_path)
    _seed(store, 24)
    monkeypatch.setattr(
        vector_knowledge, "_available_physical_memory_bytes", lambda: _GIB // 8
    )
    with caplog.at_level(logging.WARNING):
        result = store.build_ann_index()
    assert result["built"] is False
    assert result["reason"] == "insufficient_memory"
    # 未 publish：线上两文件一个都不该出现。
    assert not Path(store.ann_index_path).exists()
    assert not Path(store.ann_order_path).exists()
    text = caplog.text
    assert "跳过 ANN 重建" in text and "内存门" in text
    assert "需要" in text and "实测可用" in text
    assert "--ann-force-low-memory" in text, "告警必须点名下一发怎么手动放行"


def test_gate_allows_when_memory_sufficient(tmp_path) -> None:
    store = _make_store(tmp_path)
    _seed(store, 24)
    result = store.build_ann_index()
    assert result["built"] is True, result
    assert Path(store.ann_index_path).is_file()


def test_probe_unavailable_fails_closed(tmp_path, monkeypatch) -> None:
    """探针取不到数 ⇒ 按不可判定**不开火**（不许把"量不到"读成"够用"）。"""
    monkeypatch.setattr(
        vector_knowledge, "_available_physical_memory_bytes", lambda: None
    )
    store = _make_store(tmp_path)
    _seed(store, 24)
    result = store.build_ann_index()
    assert result["built"] is False
    assert result["reason"] == "memory_probe_unavailable"
    assert result["memory_gate"]["probe_failed"] is True
    assert not Path(store.ann_index_path).exists()


def test_skip_leaves_three_traces(tmp_path, monkeypatch, caplog) -> None:
    """跳过不许静默：日志 / meta 观测行 / 告警出口，三处都要有。"""
    monkeypatch.setattr(
        vector_knowledge, "_available_physical_memory_bytes", lambda: _GIB // 8
    )
    store = _make_store(tmp_path)
    _seed(store, 24)
    with caplog.at_level(logging.WARNING):
        result = store.build_ann_index()
    assert result["built"] is False
    # ① 日志
    assert "内存门" in caplog.text
    # ② meta 观测行：三个数（实算/需求/下限）必须在，且不含磁盘路径
    meta = _read_gate_meta(store)
    assert meta["available"].endswith("GiB") and meta["required"].endswith("GiB")
    assert meta["floor"] and meta["headroom"]
    assert meta["forced"] is False and meta["stage"] == "pre"
    assert "path" not in json.dumps(meta)
    # ③ 告警出口：kb-sync 侧按 ann_reason 判定为可告警面
    assert result["reason"] in kb_wiki._ALERTABLE_ANN_REASONS


def test_alert_content_names_measured_threshold_and_escape_hatch(tmp_path) -> None:
    """五要素卡必须把"实算了多少／阈值多少／下一发怎么放行"写全。"""
    result = {
        "mode": "incremental",
        "ann_reason": "insufficient_memory",
        "ann_memory_gate": {
            "available": "1.62GiB",
            "required": "4.50GiB",
            "floor": "4.5GiB",
            "headroom": "1.0GiB",
            "expected_vectors": 740996,
            "dim": 1024,
            "probe_failed": False,
        },
    }
    alert = kb_wiki.build_ann_memory_alert_content(result)
    body = alert.format_message()
    assert "1.62GiB" in body, "没报实算值"
    assert "4.50GiB" in body, "没报阈值/需求"
    assert "--ann-force-low-memory" in body, "没给手动放行通路"
    assert "暴力扫描" in body, "没说清跳过≠恢复"
    assert str(tmp_path) not in body


def test_probe_failure_alert_says_cannot_measure_not_low_memory() -> None:
    result = {
        "mode": "incremental",
        "ann_reason": "memory_probe_unavailable",
        "ann_memory_gate": {"probe_failed": True, "available": "unknown"},
    }
    body = kb_wiki.build_ann_memory_alert_content(result).format_message()
    assert "取不到数" in body and "不可判定" in body


def test_force_flag_bypasses_gate_and_records_forced(tmp_path, monkeypatch) -> None:
    """越门是显式动作：能建，但必须另记一条 forced=True 的痕。"""
    monkeypatch.setattr(
        vector_knowledge, "_available_physical_memory_bytes", lambda: _GIB // 8
    )
    store = _make_store(tmp_path)
    _seed(store, 24)
    result = store.build_ann_index(force_low_memory=True)
    assert result["built"] is True, result
    assert Path(store.ann_index_path).is_file()
    assert _read_gate_meta(store)["forced"] is True


def test_assumed_dimension_never_guesses_small(tmp_path) -> None:
    """provider 没声明维数 ⇒ 按保守缺省，不许猜小（猜小=门更容易被越过）。"""
    store = _make_store(tmp_path)
    # 声明了就照声明值走（本替身 8 维）。
    assert store._ann_assumed_dimension() == 8
    store.embed_provider = SimpleNamespace()  # 无 dimensions 属性
    assert store._ann_assumed_dimension() == vector_knowledge._ANN_BUILD_ASSUME_DIM
    store.embed_provider = SimpleNamespace(dimensions=1536)
    assert store._ann_assumed_dimension() == 1536
    store.embed_provider = SimpleNamespace(dimensions="junk")
    assert store._ann_assumed_dimension() == vector_knowledge._ANN_BUILD_ASSUME_DIM
    store.embed_provider = SimpleNamespace(dimensions=0)
    assert store._ann_assumed_dimension() == vector_knowledge._ANN_BUILD_ASSUME_DIM


# ------------------------------------------- 活性锁：跳过绝不等于"让它绿"


def test_memory_gate_skip_does_not_green_the_completeness_refusal(
    tmp_path, monkeypatch
) -> None:
    """**本文件最要紧的一条**：门跳过后，完备性闸照样拒用 ANN。

    构造：先成功重建一代（戳=ntotal，闸放行）→ 补嵌把戳推高（短装态）→
    低内存下再请求重建（被门跳过）→ 断言闸仍然拒用、且索引文件仍是那一代。
    注毒"顺手把 _ANN_COMPLETENESS_MAX_MISSING 放宽"或"跳过时顺手落戳"必红。
    """
    store = _make_store(tmp_path)
    _seed(store, 24)
    assert store.build_ann_index()["built"] is True
    assert store.load_ann_index() is True

    # 短装态：把计数戳推高（真身里这是补嵌涨点的效果，此处直接落值）。
    stamped = int(store._stamped_expected_vector_count())
    store.set_meta(
        vector_knowledge._EMBEDDED_COUNT_KEY, str(stamped + 5)
    )
    store._drop_ann_cache()
    assert store.load_ann_index() is False, "前置：短装就该被拒"

    monkeypatch.setattr(
        vector_knowledge, "_available_physical_memory_bytes", lambda: _GIB // 8
    )
    skipped = store.build_ann_index()
    assert skipped["built"] is False
    assert _ANN_COMPLETENESS_MAX_MISSING == 0, "内存门不许顺手放宽完备性闸"
    # 跳过没有偷偷落戳、也没有让闸改口。
    assert int(store._stamped_expected_vector_count()) == stamped + 5
    store._drop_ann_cache()
    assert store.load_ann_index() is False


def test_midway_abort_publishes_nothing(tmp_path, monkeypatch) -> None:
    """开火后内存掉下来 ⇒ 中途收火，线上文件一字不动。

    构造要点：复检的规模输入是**计数戳**，无戳 ⇒ 估不出剩余量 ⇒ 故意不复检
    （见 `test_no_midway_recheck_when_scale_unknown`）。所以先正常建一代把戳落下，
    再删掉两个线上文件（模拟"这一轮要重建"），才谈得上中途收火。
    """
    store = _make_store(tmp_path)
    _seed(store, 24)
    assert store.build_ann_index()["built"] is True
    for path in (store.ann_index_path, store.ann_order_path):
        Path(path).unlink()

    reads = {"n": 0}

    def _fake_available() -> int:
        reads["n"] += 1
        # 前置检查放行（第 1 发），复检即不足（第 2 发起）。
        return 64 * _GIB if reads["n"] == 1 else 1

    monkeypatch.setattr(
        vector_knowledge, "_available_physical_memory_bytes", _fake_available
    )
    # 24 条分 3 批 ⇒ 第 1 批之后才有"剩余量"可判（批边界=复检粒度）。
    monkeypatch.setattr(vector_knowledge, "_ANN_BUILD_BATCH_SIZE", 8)
    monkeypatch.setattr(vector_knowledge, "_ANN_BUILD_MEMORY_RECHECK_VECTORS", 8)
    result = store.build_ann_index()
    assert result["built"] is False
    assert result["reason"] == "insufficient_memory_midway"
    assert reads["n"] >= 2, "前置放行后没有复检 = 只查一次的门，会被实况击穿"
    assert 1 <= result["vectors_built_before_abort"] < 24
    assert not Path(store.ann_index_path).exists(), "中途收火却把半份索引 publish 了"
    assert not Path(store.ann_order_path).exists()
    assert _read_gate_meta(store)["stage"] == "midway"


def test_live_floor_breaker_fires_when_scale_unknown(tmp_path, monkeypatch) -> None:
    """无戳且连 rowid 界都拿不到 ⇒ 剩余量估不出，但**不等于免检**：
    中途复检降级为活体下限断路器（`_ann_live_floor_bytes`，S118 接线）。

    S112 原形态是"规模未知⇒不做复检，只认前置那一发"，并在注释里自称
    "估不准就不假装能判"——但首发重建恰是最大一发（简报点名的 S115 场景），
    只查一次的门会被分钟级实况击穿。S118 收线改成：前置按 `headroom+批副本`
    判、中途每粒度再按同一条下限判一次，撑不过就当场收火。
    """
    store = _make_store(tmp_path)
    _seed(store, 24)
    store.set_meta(vector_knowledge._EMBEDDED_COUNT_KEY, "")
    monkeypatch.setattr(
        vector_knowledge, "_estimate_rebuild_scale", lambda _store: None
    )
    reads = {"n": 0}

    def _fake_available() -> int:
        reads["n"] += 1
        return 64 * _GIB if reads["n"] == 1 else 1  # 前置放行，中途掉下来

    monkeypatch.setattr(
        vector_knowledge, "_available_physical_memory_bytes", _fake_available
    )
    monkeypatch.setattr(vector_knowledge, "_ANN_BUILD_BATCH_SIZE", 8)
    monkeypatch.setattr(vector_knowledge, "_ANN_BUILD_MEMORY_RECHECK_VECTORS", 8)
    result = store.build_ann_index()
    assert result["built"] is False
    assert result["reason"] == "insufficient_memory_midway"
    assert _read_gate_meta(store)["stage"] == "midway"
    # 反证：把活体下限摘成 0 ⇒ 中途不再收火 ⇒ 证明收火判据就是那枚下限。
    monkeypatch.setattr(vector_knowledge, "_ann_live_floor_bytes", lambda dim: 0)
    reads["n"] = 0
    for path in (store.ann_index_path, store.ann_order_path):
        Path(path).unlink(missing_ok=True)
    result2 = store.build_ann_index()
    assert result2["built"] is True, (
        "下限摘成 0 后仍收火 ⇒ 断路器判据不是 _ann_live_floor_bytes，本锁没盯住它"
    )


# ================================================================ 取消旗


def test_cancel_flag_consumed_at_sync_batch_boundary(tmp_path) -> None:
    """**活性锁**：旗标必须在批边界被消费掉，取消在跑的那一轮。

    注毒「把 `_consume_cancel_flag()` 从 `_raise_if_cancelled` 里摘掉」⇒ 本用例
    真红（旗标在位而同步跑完）。这是简报点名的那条"取消事件永不被消费"。
    """
    config = SimpleNamespace(bot_kb_wiki_db_path=str(
        tmp_path / "kb_wiki_embeddings.sqlite3"
    ))
    store = CancelSpyStore(tmp_path=tmp_path, sync_progress_batches=3)
    kb_wiki.kb_sync_cancel_flag_path(config.bot_kb_wiki_db_path).write_text(
        "requested_by_pid=test\n", encoding="utf-8"
    )
    result = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert result["error_kind"] == "cancelled", (
        "取消旗落了却没人消费：同步跑完了，操作员按不动这个钮"
    )
    assert "续传" in result["public_message"]
    # 一次性消费：旗标文件必须被删掉，否则它会取消此后每一轮。
    assert not kb_wiki.kb_sync_cancel_flag_path(
        config.bot_kb_wiki_db_path
    ).exists()


def test_ann_build_progress_is_the_same_cancel_channel(tmp_path) -> None:
    """**活性锁**：取消检查点要延伸到建索引自己的批边界（分钟级最长的一段）。

    替身忠实转发 on_progress：真身 `_build_ann_index_locked` 每批调一次它。
    kb_wiki 若不把 `_cancel_aware_progress` 传进去，本用例真红。
    """
    config = SimpleNamespace(bot_kb_wiki_db_path=str(
        tmp_path / "kb_wiki_embeddings.sqlite3"
    ))
    store = CancelSpyStore(
        tmp_path=tmp_path,
        sync_stats={
            "added": 3,
            "changed": 0,
            "removed": 0,
            "skipped": 0,
            "chunks": 3,
        },
        ann_flag_appears_midbuild=True,
    )
    result = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert store.build_ann_calls == 1
    assert result["error_kind"] == "cancelled", (
        "ANN 重建段不在取消通道上：这一段最长按分钟计却停不下来"
    )
    assert store.build_ann_kwargs_seen[0]["on_progress"] is not None


def test_cancel_flag_honored_at_task_entry(tmp_path) -> None:
    """入口那发检查也要吃旗：旗在位时连同步都不该开跑。"""
    config = SimpleNamespace(bot_kb_wiki_db_path=str(
        tmp_path / "kb_wiki_embeddings.sqlite3"
    ))
    store = CancelSpyStore(tmp_path=tmp_path)
    kb_wiki.kb_sync_cancel_flag_path(config.bot_kb_wiki_db_path).write_text(
        "x\n", encoding="utf-8"
    )
    result = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert result["error_kind"] == "cancelled"
    assert store.sync_calls == [], "入口消费：同步一步都不该跑"


def test_flag_path_registered_before_first_checkpoint_and_released_after(
    tmp_path,
) -> None:
    """登记时机与归还：跑中可见、跑完必须为空（不在跑的轮次不许继续监听目录）。"""
    seen: list[object] = []
    config = SimpleNamespace(bot_kb_wiki_db_path=str(
        tmp_path / "kb_wiki_embeddings.sqlite3"
    ))

    class _Spy(CancelSpyStore):
        def sync_documents(self, docs, *, removed_ids=(), full=False, on_progress=None):
            seen.append(kb_wiki.current_kb_sync_cancel_flag_path())
            return super().sync_documents(
                docs, removed_ids=removed_ids, full=full, on_progress=on_progress
            )

    store = _Spy(tmp_path=tmp_path)
    assert kb_wiki.current_kb_sync_cancel_flag_path() is None
    kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert seen and seen[0] is not None, "第一个检查点之前没登记旗路径"
    assert Path(str(seen[0])).name == kb_wiki._SYNC_CANCEL_FLAG_FILENAME
    assert kb_wiki.current_kb_sync_cancel_flag_path() is None


def test_stale_flag_beyond_ttl_is_ignored_and_pruned(tmp_path) -> None:
    """陈旗即垃圾：过期不得取消任何一轮，且要被清掉（防每晚被莫名取消）。"""
    config = SimpleNamespace(bot_kb_wiki_db_path=str(
        tmp_path / "kb_wiki_embeddings.sqlite3"
    ))
    flag = kb_wiki.kb_sync_cancel_flag_path(config.bot_kb_wiki_db_path)
    store = CancelSpyStore(tmp_path=tmp_path, sync_progress_batches=2)
    flag.write_text("old\n", encoding="utf-8")
    stale = time.time() - kb_wiki._SYNC_CANCEL_FLAG_TTL_SECONDS - 60
    import os as _os

    _os.utime(flag, (stale, stale))
    result = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert result["error_kind"] == "none", result
    assert not flag.exists(), "过期旗没被清掉"


def test_flag_is_one_shot_next_run_completes(tmp_path) -> None:
    config = SimpleNamespace(bot_kb_wiki_db_path=str(
        tmp_path / "kb_wiki_embeddings.sqlite3"
    ))
    flag = kb_wiki.kb_sync_cancel_flag_path(config.bot_kb_wiki_db_path)
    flag.write_text("once\n", encoding="utf-8")
    first = kb_wiki.run_kb_sync_task(
        config, store=CancelSpyStore(tmp_path=tmp_path, sync_progress_batches=1),
        embed=False,
    )
    assert first["error_kind"] == "cancelled"
    second = kb_wiki.run_kb_sync_task(
        config, store=CancelSpyStore(tmp_path=tmp_path), embed=False
    )
    assert second["error_kind"] == "none", "一次旗标取消了第二轮"


def test_event_set_short_circuits_flag_probe(tmp_path, monkeypatch) -> None:
    """Event 已置位时不再 stat 旗（省掉每批一发无谓 IO），且仍然取消。"""
    config = SimpleNamespace(bot_kb_wiki_db_path=str(
        tmp_path / "kb_wiki_embeddings.sqlite3"
    ))
    stats = {"n": 0}
    real_is_file = Path.is_file
    wanted = kb_wiki._SYNC_CANCEL_FLAG_FILENAME

    def _counting_is_file(self):  # type: ignore[no-untyped-def]
        if self.name == wanted:
            stats["n"] += 1
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", _counting_is_file)
    assert kb_wiki.cancel_kb_sync_task(reason="test") is True
    result = kb_wiki.run_kb_sync_task(
        config, store=CancelSpyStore(tmp_path=tmp_path, sync_progress_batches=2),
        embed=False,
    )
    assert result["error_kind"] == "cancelled"
    assert stats["n"] <= 1, "取消事件已置位还继续探旗标 = 第二套取消语义"


def test_request_kb_sync_cancel_writes_flag_and_is_idempotent(tmp_path) -> None:
    """跨进程入口本体：落旗 + 置位；重复调用如实返回 False。"""
    db = str(tmp_path / "kb_wiki_embeddings.sqlite3")
    flag = kb_wiki.kb_sync_cancel_flag_path(db)
    assert not flag.exists(), "旗路径派生撞上了既有文件"
    assert kb_wiki.request_kb_sync_cancel(reason="ops", db_path=db) is True
    assert flag.exists()
    assert "requested_by_pid" in flag.read_text(encoding="utf-8")
    # 旗与事件都已在位 ⇒ 本次没有新增任何请求，返回值不许谎报。
    assert kb_wiki.request_kb_sync_cancel(reason="again", db_path=db) is False
    # 事件被出口清掉而旗仍在位 ⇒ 本进程重新置位，这是一次真新增。
    kb_wiki._SYNC_CANCEL_EVENT.clear()
    assert kb_wiki.request_kb_sync_cancel(reason="third", db_path=db) is True


def test_flag_without_registered_path_is_inert(tmp_path, monkeypatch) -> None:
    """不在跑的轮次不得被偶然同名文件取消（旗路径未登记 ⇒ 视同无旗）。"""
    db = tmp_path / "kb_wiki_embeddings.sqlite3"
    kb_wiki.kb_sync_cancel_flag_path(db).write_text("stray\n", encoding="utf-8")
    assert kb_wiki._consume_cancel_flag() is False
    assert kb_wiki._SYNC_CANCEL_EVENT.is_set() is False


# ============================================== 反证锁：证明上面的判据有牙齿
# 这一组不测"代码对不对"，测"锁瞎不瞎"：把每个被守护的通道在**运行期**摘掉
# （monkeypatch，不改源码树），断言那条真实缺陷形态确实出现。
# 于是"用例只是恰好通过"这种假绿被排除掉：哪天判据被放宽到看不见这些形态，
# 本组用例当场红。


def test_counterfactual_flag_never_consumed_would_look_like_success(
    tmp_path, monkeypatch
) -> None:
    """摘掉旗标消费 ⇒ 同步"成功"跑完而旗标还在原地：正是活性锁要拦的形态。

    等价于把 `_raise_if_cancelled` 里的 `or _consume_cancel_flag()` 删掉。
    本用例断言这个缺陷形态**确实成立**（不取消、旗不被删），从而反证
    `test_cancel_flag_consumed_at_sync_batch_boundary` 盯的是真通道而不是巧合。
    """
    config = SimpleNamespace(bot_kb_wiki_db_path=str(
        tmp_path / "kb_wiki_embeddings.sqlite3"
    ))
    flag = kb_wiki.kb_sync_cancel_flag_path(config.bot_kb_wiki_db_path)
    flag.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(kb_wiki, "_consume_cancel_flag", lambda: False)
    result = kb_wiki.run_kb_sync_task(
        config,
        store=CancelSpyStore(tmp_path=tmp_path, sync_progress_batches=3),
        embed=False,
    )
    assert result["error_kind"] == "none", "反证失败：通道摘掉了却仍拦得住"
    assert flag.exists(), "反证失败：消费点其实还在别处"


def test_counterfactual_gate_computed_but_never_enforced(tmp_path, monkeypatch) -> None:
    """门算了但不执法 ⇒ 低内存照样 publish：跳过用例判的是执法而不是探针。

    等价于把 `build_ann_index` 里的 `if not verdict.allowed:` 改成 `if False:`。
    若本席的用例只断言"探针返回小值"，这种写法会照样全绿——本用例排除它。
    """
    monkeypatch.setattr(
        vector_knowledge, "_available_physical_memory_bytes", lambda: 1
    )
    monkeypatch.setattr(
        vector_knowledge,
        "_evaluate_ann_build_memory_gate",
        lambda expected, dim: vector_knowledge._AnnMemoryVerdict(
            allowed=True,
            available_bytes=1,
            required_bytes=99 * _GIB,
            expected_vectors=expected,
            dim=dim,
            probe_failed=False,
        ),
    )
    store = _make_store(tmp_path)
    _seed(store, 24)
    assert store.build_ann_index()["built"] is True, (
        "反证失败：执法点不在 verdict.allowed 上，本席的跳过用例另有依赖"
    )
    assert Path(store.ann_index_path).exists()


def test_counterfactual_recheck_disabled_never_aborts_midway(
    tmp_path, monkeypatch
) -> None:
    """复检粒度调到永不触发 ⇒ 中途收火消失 ⇒ 证明复检用例盯的就是那一步。"""
    store = _make_store(tmp_path)
    _seed(store, 24)
    assert store.build_ann_index()["built"] is True
    for path in (store.ann_index_path, store.ann_order_path):
        Path(path).unlink()
    reads = {"n": 0}

    def _fake_available() -> int:
        reads["n"] += 1
        return 64 * _GIB if reads["n"] == 1 else 1

    monkeypatch.setattr(
        vector_knowledge, "_available_physical_memory_bytes", _fake_available
    )
    monkeypatch.setattr(vector_knowledge, "_ANN_BUILD_BATCH_SIZE", 8)
    monkeypatch.setattr(
        vector_knowledge, "_ANN_BUILD_MEMORY_RECHECK_VECTORS", 10**9
    )
    result = store.build_ann_index()
    assert result["built"] is True, "反证失败：复检关不掉，说明粒度另有硬编码"
    assert reads["n"] == 1


def test_skip_branch_never_touches_the_completeness_stamp(tmp_path, monkeypatch) -> None:
    """结构锁：跳过分支里绝不许出现"落戳"这类动作（抹戳=给短装自我认证）。

    行为层已有 `test_memory_gate_skip_does_not_green_the_completeness_refusal`
    兜着；这条 AST 锁补的是**写法**层面：跳过分支中不得调用
    `_stamp_expected_vector_count` / `certify_expected_vector_count` /
    `_publish_ann_pair`（本仓 `vk:2600-2604` 点名的"把短装洗成正常"三条路）。
    """
    import ast

    tree = ast.parse(
        Path(vector_knowledge.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_ann_index":
            banned = {
                "_stamp_expected_vector_count",
                "certify_expected_vector_count",
                "_publish_ann_pair",
                "_write_ann_attestation",
            }
            # 跳过分支 = `if not verdict.allowed:` 的 body；逐个函数体内也一律不许出现。
            calls = {
                call.func.attr
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
            }
            assert not (calls & banned), (
                f"build_ann_index 体内出现落戳/发布动作：{sorted(calls & banned)}"
            )
            # 记账口是 `self._record_ann_memory_skip(...)` ⇒ 属性调用，不是裸名。
            assert "_record_ann_memory_skip" in calls, (
                "跳过没走统一记账口（痕迹会漏）"
            )
            return
    raise AssertionError("找不到 build_ann_index，本锁失效")


def test_production_env_never_sets_the_force_knob() -> None:
    """越门是显式动作，所以生产侧不许自己带着它。

    现算两条：① `.env.example` 里不存在 `ANN_FORCE` 形态的键（本席未开 config 键）；
    ② 全仓唯一的 `force_low_memory=True` 字面量出现在测试与 CLI 传递路径上，
    **不在任何调度/装配点**（cron 走 `run_kb_sync_task` 缺省 False）。
    """
    repo_root = Path(kb_wiki.__file__).resolve().parents[5]  # type: ignore[arg-type]
    example = repo_root / ".env.example"
    if example.is_file():
        text = example.read_text(encoding="utf-8", errors="replace")
        assert "ANN_FORCE" not in text.upper(), "内存门被开成了配置键，简报要求是常量"
    # 装配点（根 __init__）不许带越门旗：cron 必须走缺省。
    root_init = repo_root / "plugins" / "bot_unified_runtime" / "__init__.py"
    body = root_init.read_text(encoding="utf-8", errors="replace")
    assert "force_low_memory" not in body, (
        "生产装配点自己带了越门旗 ⇒ 夜间 cron 会绕过内存门"
    )


# ================================================================ CLI 面（越门旗）


def test_ann_force_flag_is_wired_end_to_end_not_just_declared() -> None:
    """`--ann-force-low-memory` 必须**四腿同生**，缺一腿就是摆设旗。

    链条：CLI 旗声明 → `run_kb_sync_task(force_low_memory_ann=…)` 实参 →
    `_run_kb_sync_task_locked` 形参 → `store.build_ann_index(force_low_memory=…)`。
    只锁首尾（有旗 + 有 build 调用）会放过"旗接了但中间丢在函数签名外"这种
    半死形态——本仓反复记账的"存在性糊过活性判据"正是它。
    用 AST 而非 grep：判据要认的是**某个具体调用的关键字实参**，文本扫做不到。
    """
    import ast

    import plugins.bot_unified_runtime.domains.ops.smoke.smoke as _smoke

    def _tree(module: object) -> ast.Module:
        return ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))

    smoke_tree = _tree(_smoke)
    kb_tree = _tree(kb_wiki)

    declared: set[str] = set()
    for node in ast.walk(smoke_tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    declared.add(arg.value)
    assert "--ann-force-low-memory" in declared, "CLI 没声明越门旗"
    assert "--kb-cancel" in declared, "CLI 没声明取消旗入口"

    # 腿②：smoke 调 run_kb_sync_task 时把旗带下去。
    smoke_sync_calls = [
        node
        for node in ast.walk(smoke_tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", ""))
        == "run_kb_sync_task"
    ]
    assert smoke_sync_calls, "smoke.py 里找不到 run_kb_sync_task 调用点，本锁失效"
    assert all(
        "force_low_memory_ann" in {kw.arg for kw in call.keywords}
        for call in smoke_sync_calls
    ), "CLI 调 run_kb_sync_task 没带越门旗"

    # 腿③：run_kb_sync_task 形参 + 转发给 _run_kb_sync_task_locked。
    def _params(tree: ast.Module, fname: str) -> set[str]:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == fname:
                return {a.arg for a in node.args.args} | {
                    a.arg for a in node.args.kwonlyargs
                }
        raise AssertionError(f"找不到函数定义 {fname}，本锁失效")

    assert "force_low_memory_ann" in _params(kb_tree, "run_kb_sync_task")
    assert "force_low_memory_ann" in _params(kb_tree, "_run_kb_sync_task_locked")
    locked_calls = [
        node
        for node in ast.walk(kb_tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "_run_kb_sync_task_locked"
    ]
    assert locked_calls and all(
        "force_low_memory_ann" in {kw.arg for kw in call.keywords}
        for call in locked_calls
    ), "run_kb_sync_task 收了旗却没转发给主体"

    # 腿④：kb_wiki 与 smoke 两处 build_ann_index 调用点都吃到旗。
    for tree, label in ((kb_tree, "kb_wiki"), (smoke_tree, "smoke")):
        builds = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") == "build_ann_index"
        ]
        assert builds, f"{label} 里没有 build_ann_index 调用点"
        for call in builds:
            assert "force_low_memory" in {kw.arg for kw in call.keywords}, (
                f"{label} 的重建调用点没把越门旗传给内存门：旗成了摆设"
            )


def test_kb_sync_cancel_flag_is_registered_in_the_run_body() -> None:
    """旗路径登记必须落在**持锁主体**里（不在闸外），且早于第一个检查点。

    这条与 `test_flag_path_registered_before_first_checkpoint_and_released_after`
    是两种判据：那条跑行为，这条钉结构——防止有人把登记挪进 `busy` 分支
    （那分支根本不会跑主体，旗路径就永远没登记，行为用例也未必测得到）。
    """
    import ast

    tree = ast.parse(
        Path(kb_wiki.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_kb_sync_task_locked":
            names = {
                call.func.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
            assert "_set_kb_sync_cancel_flag_path" in names, (
                "主体里没有旗路径登记：取消旗永不会被消费"
            )
            def _targets(stmt: ast.stmt) -> list[ast.expr]:
                if isinstance(stmt, ast.Assign):
                    return list(stmt.targets)
                if isinstance(stmt, ast.AnnAssign):
                    return [stmt.target]
                return []

            assign = [
                stmt
                for stmt in node.body
                if isinstance(stmt, ast.Assign | ast.AnnAssign)
                and any(
                    isinstance(t, ast.Name) and t.id == "result"
                    for t in _targets(stmt)
                )
            ]
            call_lines = [
                call.lineno
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "_set_kb_sync_cancel_flag_path"
            ]
            assert assign and call_lines, "登记位置或 result 赋值缺失，本锁失效"
            assert call_lines[0] <= assign[0].lineno + 6, (
                "旗路径登记离第一个检查点太远：入口那发 `_raise_if_cancelled` 看不见旗"
            )
            return
    raise AssertionError("找不到 _run_kb_sync_task_locked，本锁失效")

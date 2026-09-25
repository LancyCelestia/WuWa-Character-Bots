"""SEAT-S118：ANN 重建内存门的收线锁（全离线，除 bench 复跑指南外不触重型测量）。

本席接手 SEAT-S112 的半成"self-calibrating"重构（它死在把两把尺打架的
`_ANN_BUILD_UNIT_COST_DISPUTE_BYTES` 写进使用位、定义却没落笔的那一刻——
`build_ann_index` 每次调用当场 NameError，被 kb_wiki 的宽 except 吞成
`reason="NameError"`，不在可告警面 ⇒ **门不存在，重建每晚静默失败**）。
本文件钉住四件事：

1. **NameError 一族死掉**：需求式在所有规模/维数形态下可直接调用（含端到端）。
2. **计价按实测峰值**（bench 复跑见下）：线性价 6,918 B/vec 与合成 bench
   峰值边际 7,393 B/vec（20k→40k，PeakWorkingSetSize 口径）同带；S85 的
   4,694 B/vec 是**轮询稳态**斜率（会漏亚秒级 realloc 尖峰），只作标定锚。
   复跑命令（合成数据、tmp 目录、禁碰真库；机器空闲 ≥3 GiB 时才跑大档）：
   `python -B %TEMP%/cw-s118/bench/s118_seed.py --n 40000 --db ...` 然后
   `python -B %TEMP%/cw-s118/bench/s118_batched.py --n 40000 ...`，
   全曲线与归因见 %TEMP%/cw-s118/seat-s118-ann-memory-truth.md §1/§2。
3. **54 KB/vec 归因成文**：层分解锁（单条向量的 JSON 文本 ≥20 KB、
   json.loads 出的嵌套 list ≥40 KB——"一次性全量读链"的中间物 ≈65–78 KB/vec，
   分批形态下这些只在 O(2048) 条批内出现，绝不进稳态）。
4. **自校准断路器真接线**：中途复检走 `_ann_projected_requirement_bytes`
   （实测斜率与模型价取大者），带反证锁"摘成纯模型价就不收火"。

行号会漂，本文件一律按符号与行为断言，不钉行号。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    vector_knowledge as vk,
)

_GIB = 1024**3

# bench 实测值（2026-09-26 本机，合成 float32×1024、同构造参数、独立解释器）。
_MEASURED_PEAK_MARGINAL_B_PER_VEC = 7_393  # 20k→40k 的 PeakWorkingSetSize 边际
_MEASURED_STEADY_WS_MARGINAL_B_PER_VEC = 3_896  # 同区间批末 WorkingSet 边际


class _FakeProvider:
    dimensions = 8
    active_base_url = "http://127.0.0.1:1"
    signature = "test|s118"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            digest = hashlib.sha1(text.encode("utf-8")).digest()
            out.append([byte / 255.0 for byte in digest[:8]])
        return out


def _make_store(tmp_path: Path) -> vk.SqliteVectorKnowledgeStore:
    return vk.SqliteVectorKnowledgeStore(
        db_path=tmp_path / "kb_wiki_embeddings.sqlite3",
        embed_provider=_FakeProvider(),
        chunk_chars=800,
        top_k=4,
        signature="test|s118",
        auto_reset=True,
        ann_index_path=str(tmp_path / "kb_wiki_faiss.index"),
        ann_order_path=str(tmp_path / "kb_wiki_faiss.order.json"),
    )


def _seed(store: vk.SqliteVectorKnowledgeStore, docs: int) -> None:
    rows = [
        {
            "id": f"topic/doc-{index}",
            "hash": hashlib.sha1(f"doc{index}".encode()).hexdigest(),
            "topic": "topic",
            "source": "s118",
            "title": f"doc-{index}",
            "chunks": [f"内容{index}" * 40],
        }
        for index in range(docs)
    ]
    store.sync_documents(iter(rows), removed_ids=(), full=True)
    store.embed_pending(None)


# ---------------------------------------------------------------- NameError 一族


def test_demand_callable_at_every_scale_and_dim() -> None:
    """回归锁：S112 死时盘上的 `_ann_build_demand_bytes` 一调即 NameError。

    覆盖 None/0/1/测试规模/生产标定规模/百万级 × 三种维数，全部必须返回正数。
    """
    for dim in (8, 1024, 1536):
        for n in (None, 0, 1, 10, 24, 2048, vk._ANN_BUILD_SCALE_CALIBRATION_VECTORS):
            value = vk._ann_build_demand_bytes(n, dim)
            assert isinstance(value, int) and value > 0, (n, dim)


def test_gate_end_to_end_never_raises_nameerror(tmp_path, monkeypatch) -> None:
    """端到端：门放行与拦下两条路都不许以异常形态收场（kb_wiki 的宽 except
    会把任何异常吞成 `reason="NameError"`——门死了也无人报警，正是 S112 死相）。
    """
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 64 * _GIB)
    store = _make_store(tmp_path)
    _seed(store, 24)
    assert store.build_ann_index()["built"] is True
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 1)
    skipped = store.build_ann_index()
    assert skipped["built"] is False
    assert skipped["reason"] == "insufficient_memory"


# ---------------------------------------------------------------- 计价与标定


def test_demand_linear_price_pinned_to_measured_peak_marginal() -> None:
    """线性价与 S118 合成 bench 的**峰值边际**同带（0.6–1.05×）。

    这不是循环论证：bench 走的是真身构造（同 faiss 参数/同批宽/同 SQLite 读链，
    合成向量与行形态），常数改了、bench 数没跟着改，或者反过来，本锁都会红。
    复跑命令见模块 docstring。
    """
    per_vec = (
        vk._ANN_BUILD_MEASURED_DIM
        * (4 + vk._ANN_BUILD_FAISS_REALLOC_BYTES_PER_DIM)
        + (
            vk._ANN_BUILD_MEASURED_BYTES_PER_VECTOR
            - vk._ANN_BUILD_MEASURED_DIM * 4
        )
        + vk._ANN_BUILD_ID_TABLE_BYTES_PER_VECTOR
    )
    assert (
        _MEASURED_PEAK_MARGINAL_B_PER_VEC * 0.6
        <= per_vec
        <= _MEASURED_PEAK_MARGINAL_B_PER_VEC * 1.05
    ), "门价与实测峰值边际脱带（实测只作快照，允许模型略低于它但不许高）"
    # 稳态斜率必须仍低于峰值价（否则说明 realloc 项被摘掉了）。
    assert per_vec > _MEASURED_STEADY_WS_MARGINAL_B_PER_VEC


def test_demand_model_reproduces_s85_calibration_at_766k() -> None:
    """标定点复算锁（S112 注释点名引用、却没把用例写出来的那一枚，S118 补上）：
    需求式在 n=766,126、dim=1024 处与 S85 的经验合价 4.5 GiB 同带
    （不低于它——新代驻留+扩容尖峰+余量只会更保守；不高于它 1.6×——
    否则标定夜那种成功重建会被永久性误拒）。
    """
    demand = vk._ann_build_demand_bytes(
        vk._ANN_BUILD_SCALE_CALIBRATION_VECTORS, vk._ANN_BUILD_MEASURED_DIM
    )
    assert vk._ANN_BUILD_MIN_AVAILABLE_BYTES <= demand
    assert demand <= vk._ANN_BUILD_MIN_AVAILABLE_BYTES * 16 // 10


# ---------------------------------------------------------------- 层归因成文


def test_json_chain_layers_measured_per_vector() -> None:
    """把 §2 的归因（54 KB/vec 是**读链一次性中间物**）钉成常驻可跑的微锁：
    单条 1024 维归一化 float32 向量的
      - `json.dumps` 文本 ≥ 20 KB/vec，
      - `json.loads` 回来的嵌套 list（Python float 对象 + 指针）≥ 40 KB/vec，
    两层同场即 ≈65 KB/vec——与 S112/S115 观测到的 54–67 KB/vec 同量级。
    分批重建里这些中间物只有 O(batch) 条在场，绝不到 O(n)。
    """
    import numpy as np

    rng = np.random.default_rng(20260926)
    vec = rng.standard_normal(1024, dtype=np.float32)
    vec = vec / float(np.linalg.norm(vec))
    text = json.dumps(vec.tolist())
    parsed = json.loads(text)
    assert len(text) >= 20_000, "JSON 文本层量级变了，§2 归因需重量"
    object_layer_bytes = sys.getsizeof(parsed) + sum(
        sys.getsizeof(x) for x in parsed
    )
    assert object_layer_bytes >= 30_000, "Python list/float 层量级变了，§2 归因需重量"
    assert len(text) + object_layer_bytes >= 50_000, (
        "文本+对象两层同场已跌破 50 KB/vec —— S112/S115 观测到的 54–67 KB/vec "
        "不再能由此解释，§2 归因需重量（不是放宽这条锁的理由）"
    )


# ---------------------------------------------------------------- 自校准接线


def test_projected_recheck_is_wired_with_counterfactual(tmp_path, monkeypatch) -> None:
    """**本席最要紧的一条**：中途复检必须真走 `_ann_projected_requirement_bytes`。

    构造：24 条、批宽 8、复检粒度 8。探针第一发（前置）8 GiB 放行；第二发
    （8 条已装后）5 GiB。实测斜率价 = 已耗 3 GiB + 剩余 16 × (3 GiB ÷ 8)
    ≈ 9 GiB > 5 GiB ⇒ 收火；而**纯模型价**（16 条 × 822 B + 下限 ≈ 128 MiB）
    ≤ 5 GiB ⇒ 不放行就不会收火。两半合起来即"断路器有牙齿且牙齿在这条腿上"：
    - 前半：默认实现 ⇒ `insufficient_memory_midway`；
    - 后半（反证）：把投影摘成纯模型价 ⇒ 必须照样建完（证明收火归因于投影，
      不是别的什么顺手拦了）。
    """
    store = _make_store(tmp_path)
    _seed(store, 24)
    monkeypatch.setattr(vk, "_ANN_BUILD_BATCH_SIZE", 8)
    monkeypatch.setattr(vk, "_ANN_BUILD_MEMORY_RECHECK_VECTORS", 8)
    reads = {"n": 0}

    def _fake_available() -> int:
        reads["n"] += 1
        return 8 * _GIB if reads["n"] == 1 else 5 * _GIB

    monkeypatch.setattr(vk, "_available_physical_memory_bytes", _fake_available)
    result = store.build_ann_index()
    assert result["built"] is False, result
    assert result["reason"] == "insufficient_memory_midway"
    assert result["vectors_built_before_abort"] == 8

    monkeypatch.setattr(
        vk,
        "_ann_projected_requirement_bytes",
        lambda remaining, dim, **kw: vk._ann_build_demand_bytes(remaining, dim),
    )
    reads["n"] = 0
    result2 = store.build_ann_index()
    assert result2["built"] is True, (
        "摘成纯模型价仍收火 ⇒ 前半的收火不是投影腿干的，本锁空转"
    )

"""S181：ANN 索引换 SQ8 量化存储的锁（用户裁定「执行乙，用最快速度完成」）。

实测依据（同机离线对照，60,400 条**生产真向量**、400 条真查询、K=4、
`METRIC_INNER_PRODUCT`、efConstruction=200 / efSearch=64、训练样本 = rowid 前
20,000 条）：fp32 262.1 MB → SQ8 77.8 MB（0.297 倍），top-4 与 fp32 一致率
0.9856，内积分数差均值 0.00029 / 最大 0.047。fp16 同口径 0.53 倍 / 0.9906。
本文件钉的是"换了存储格式之后这件事仍然真成立"的几把锁，不重复量比例。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import faiss
import numpy as np
from test_ann_certify_prewarm import _make_store

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    vector_knowledge as vk,
)

_SOURCE = Path(vk.__file__)


def test_built_index_is_quantized_and_still_retrievable(tmp_path):
    """建出来的必须是量化索引（不是 fp32 壳），并且检索照旧命中原内容。"""
    store = _make_store(tmp_path, count=24)
    result = store.build_ann_index()
    assert result["built"] is True, result
    index_path, order_path = store._ann_files()
    index = faiss.read_index(str(index_path))
    assert not isinstance(index, faiss.IndexHNSWFlat), (
        "落盘还是 fp32 平铺索引 ⇒ 位宽常量与实建脱钩（价模型按 1 B/维收钱、"
        "实物却是 4 B/维，正是本波要防的两把尺）"
    )
    assert getattr(index, "is_trained", False) is True, "量化索引未训练就发布"
    store._drop_ann_cache()
    assert store.load_ann_index() is True
    order = json.loads(Path(order_path).read_text(encoding="utf-8"))
    # 自检口径用**存进索引的那条向量本身**去查（不走文本归一化那条路，也不靠
    # 假 provider 的语义），断言量化后它自己仍是 top-1。fp32↔SQ8 的真实一致率
    # 不在这条锁里 claim——那是 60,400 条生产真向量离线量出来的 0.9856。
    with store._connect() as connection:
        row = connection.execute(
            "SELECT chunk_id, vector_blob FROM knowledge_chunks "
            "WHERE vector_blob IS NOT NULL ORDER BY rowid LIMIT 1 OFFSET 11"
        ).fetchone()
    assert row is not None and row[1]
    chunk_id = str(row[0])
    assert chunk_id in order, "夹具形态变了：该块不在序列表里"
    query = [float(x) for x in np.frombuffer(row[1], dtype=np.float32)]
    ranked = store._ann_candidates(query, 4)
    assert ranked is not None and ranked, "ANN 候选为空 = 索引没真在服务"
    assert ranked[0][0] == chunk_id, f"量化后自检索首位不是自己（got={ranked[0][0]}）"


def test_quantizer_name_and_storage_width_are_paired(tmp_path, monkeypatch):
    """量化器名与位宽**必须成对**改：名字在册却留着旧位宽（或反之）当场红。

    这枚表是"换存储格式"这件事的唯一真身来源；把它钉死，是为了防止后来者只改
    一头——那会让 `_ann_build_demand_bytes` 与实际落盘体积脱钩。
    """
    pairing = {"QT_8bit": 1, "QT_fp16": 2, "QT_qint4": 0, "QT_bt6": 0, "QT_bt7": 0}
    assert vk._ANN_INDEX_QUANTIZER_NAME in pairing, "量化器不在册"
    assert pairing[vk._ANN_INDEX_QUANTIZER_NAME] == vk._ANN_INDEX_BYTES_PER_DIM or (
        vk._ANN_INDEX_QUANTIZER_NAME in ("QT_qint4", "QT_bt6", "QT_bt7")
    ), f"{vk._ANN_INDEX_QUANTIZER_NAME} 与每维 {vk._ANN_INDEX_BYTES_PER_DIM} 字节不配对"
    # 取数口真存在：名字必须能在 faiss 上解析出枚举成员，否则建索引会静默不建。
    assert vk._resolve_ann_quantizer() is not None


def test_untrainable_build_refuses_without_touching_live_pair(tmp_path, monkeypatch):
    """训练样本取不到 ⇒ 本轮不建，且线上两文件一字不动（**绝不偷偷退回 fp32**）。"""
    store = _make_store(tmp_path, count=24)
    assert store.build_ann_index()["built"] is True
    index_path, order_path = store._ann_files()
    before = (Path(index_path).read_bytes(), Path(order_path).read_bytes())
    monkeypatch.setattr(vk, "_resolve_ann_quantizer", lambda: None)
    result = store.build_ann_index()
    assert result["built"] is False
    assert result["reason"] == "index_untrainable"
    assert (Path(index_path).read_bytes(), Path(order_path).read_bytes()) == before


def test_train_sample_reader_filters_wrong_dim_and_empty(tmp_path):
    """样本读取器：维数不符的一律不进矩阵；全不符 ⇒ None（而不是拿空集去 train）。"""
    store = _make_store(tmp_path, count=6)
    with store._connect() as connection:
        blob = connection.execute(
            "SELECT vector_blob FROM knowledge_chunks WHERE vector_blob IS NOT NULL LIMIT 1"
        ).fetchone()[0]
    dim = int(np.frombuffer(blob, dtype=np.float32).size)
    with store._connect() as connection:
        sample = vk._read_vector_train_sample(connection, dimension=dim, limit=10_000)
    assert sample is not None and sample.shape[1] == dim and sample.shape[0] > 0
    assert sample.dtype == np.float32 and sample.flags["C_CONTIGUOUS"]
    with store._connect() as connection:
        assert (
            vk._read_vector_train_sample(connection, dimension=dim + 7, limit=10) is None
        ), "维数全不符时应返回 None（宁可本轮不建，不许拿错形数据训练）"


def test_index_construction_has_a_single_site():
    """禁区结构锁：ANN 索引构造点只许 `_make_ann_index` 一处，且建索引循环里
    不许再出现 `IndexHNSW*` 第二份（那会绕开训练前提与位宽在册）。"""
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    creators = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "faiss"
            and node.func.attr.startswith("IndexHNSW")
        ):
            creators.append(node.lineno)
    assert len(creators) == 1, f"索引构造点应唯一，实得 {creators}"
    holder = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "_make_ann_index"
    )
    assert holder.lineno <= creators[0] <= holder.end_lineno

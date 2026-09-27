"""SEAT-S159 三件锁：内存计价重定标 / 代次守卫（删+增同轮假绿） / FTS 独立喂入口。

背景（2026-09-26 夜生产实测，数字为简报输入，按 fixture 复算，不现开生产库）：
- 21:33 kb-sync：changed=328、removed=714、嵌入 3,798 块；计数戳随删除降到
  740,267 < ntotal 740,996 ⇒ 完备性闸按「多出可容忍」放行了一副**既缺 3,798
  条新向量、又留着死 id** 的旧索引——戳是标量，`ntotal >= stamp` 在
  「先删后嵌同轮」下必然成立却不代表覆盖（本文件 §2 组复现它）。
- 同一轮 ANN 被内存门挡下：`insufficient_memory_midway`，要价 14.04 GiB，
  而实测全量重建峰值 3.6–3.9 GiB（09-22 / 09-25 两次观测）——中途腿把
  「首批实吃」按单位斜率**线性外推到剩余全部**，早期吃进以读链页缓存为主
  （生产折算 ≈20 KB/vec，模型边际价 6.9 KB/vec 的 2.9 倍），外推价对任何
  机器都判死 ⇒ 32 GiB 机器 10 GiB 空闲也永远不许开火（§1 组重放该形状）。
- 维基库 knowledge_chunks_fts 0 行：force=True 的旧唯一落点在 ANN 成功
  publish 之后，ANN 被挡 ⇒ FTS 恒饿（§3 组锁 kb-sync 收尾喂入口）。

三组的红→绿逐条留证于 .superpowers/sdd/2026-09-26-kb-recovery/
SEAT-S159-pricing-guard-fts.md。行号会漂，一律按符号与行为断言。
"""

from __future__ import annotations

import ast
import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_ann_certify_prewarm import (
    _STAMP_KEY,
    _append_embedded,
    _docs,
    _drop_stamp_key,
    _FakeEmbedder,
    _make_store,
    _ntotal_on_disk,
    _stamp,
    _write_raw_stamp,
)

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    vector_knowledge as vk,
)
from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

_GIB = 1024**3

# 生产实测定标（简报输入；§1 的算式据此复算，不许拍脑袋改）：
_MEASURED_FULL_REBUILD_PEAK_GIB_LOW = 3.6  # 09-22 / 09-25 两跑观测带下沿
_MEASURED_FULL_REBUILD_PEAK_GIB_HIGH = 3.9  # 上沿
_PRODUCTION_STAMP_TONIGHT = 740_267  # 今晚删除侧对称记账后的库真值戳
_PRODUCTION_MIDWAY_PRICE_TONIGHT_GIB = 14.04  # 今晚内存门实际报出的要价

_SOURCE = Path(vk.__file__)


# =============================================================================
# §2 代次守卫：先复现假绿，再钉三把锁
# =============================================================================


def _published_store(tmp_path, count: int = 20):
    """建一副「索引==库==戳」的完备代，返回 (store, 发布时嵌入代数)。"""
    store = _make_store(tmp_path, count=count)
    assert store.build_ann_index()["built"] is True
    return store, store._embed_generation_now()


def _sibling_store(
    store: vk.SqliteVectorKnowledgeStore,
) -> vk.SqliteVectorKnowledgeStore:
    """同库、同 ANN 路径的**另一个实例** = 生产里「另一个进程」的等价形态。

    为什么要它：`build_ann_index` 全程持着实例自己的 `_maintenance_lock`
    （`threading.Lock`，非重入），同实例在重建回调里再调 `embed_pending`
    必然自锁死。真实场景里趁重建补嵌的写者本就是另一个进程（各持各的锁、
    各开各的连接），独立实例照这个形态复现，判据不用降。
    """
    return vk.SqliteVectorKnowledgeStore(
        db_path=store.db_path,
        embed_provider=_FakeEmbedder(),
        chunk_chars=store.chunk_chars,
        top_k=store.top_k,
        signature=store.signature,
        auto_reset=True,
        ann_index_path=store.ann_index_path,
        ann_order_path=store.ann_order_path,
    )


def _delete_embedded_docs(store, tag: str, count: int) -> None:
    """走 removed_ids 正路删文档（每 doc 一块，全部带向量）——戳同轮拉低。"""
    store.sync_documents(
        iter(_docs(0, tag)),
        removed_ids=[f"topic/{tag}-doc-{i}" for i in range(count)],
        full=False,
    )


def test_false_green_repro_delete_then_reinsert_round(tmp_path, caplog):
    """简报点名的洞：索引 20、删 5、又嵌 5 ⇒ 戳 20 == ntotal 20，旧闸放行。

    修法落地前 `load_ann_index()` 对这样一副**不含新 5 条**的索引返回 True，
    这就是今晚生产 740,267 < 740,996 恒绿的缩小版。修完后本用例断言 False，
    且拒用原因可归因（coverage refused + 两个代次值都点名）。
    """
    store, covered_at_publish = _published_store(tmp_path)
    _delete_embedded_docs(store, "a", 5)  # 20 → 15
    _append_embedded(store, 5, "n")  # 15 → 20（索引里并没有这 5 条新 id）
    # 前提锁：纯计数判据在这副库上必然放行——本用例若红在这三行，洞已不在、
    # 或夹具变形，两种都要先复核再判。
    assert _stamp(store) == 20 == _ntotal_on_disk(store)
    assert store._embed_generation_now() > covered_at_publish, "嵌了新一批，代数必涨"

    store._drop_ann_cache()
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.load_ann_index() is False, (
            "删+嵌同轮的旧索引被放行 = 假绿（今晚生产实况）"
        )
    refused = [
        rec.getMessage() for rec in caplog.records if "coverage refused" in rec.getMessage()
    ]
    assert refused and "embed_generation=" in refused[0], "拒用必须可归因到代次"


def test_pure_deletion_round_still_accepted(tmp_path):
    """反向锁（别把删除记账废掉）：纯删除轮戳 15 < ntotal 20、代数没涨 ⇒ 仍放行。

    这条今天就是绿的，修完必须**依旧**绿——它钉的是守卫不许误杀
    「多出向量可容忍」那一格，也不许让 `_lower_expected_vector_count` 白干。
    """
    store, covered = _published_store(tmp_path)
    _delete_embedded_docs(store, "a", 5)
    assert _stamp(store) == 15 and store._embed_generation_now() == covered
    store._drop_ann_cache()
    assert store.load_ann_index() is True, "纯删除轮拒用 = 把对称记账打回原形"


def test_generation_refusal_is_cached_and_self_heals_on_rebuild(tmp_path, monkeypatch):
    """拒用缓存：同代同戳同代数维持拒用不重付 faiss/sha；重建换代即收敛到新代。"""
    store, _ = _published_store(tmp_path)
    _delete_embedded_docs(store, "a", 5)
    _append_embedded(store, 5, "n")
    store._drop_ann_cache()

    reads: list[int] = []
    real_read = vk.faiss.read_index

    def spy(*args, **kwargs):
        reads.append(1)
        return real_read(*args, **kwargs)

    monkeypatch.setattr(vk.faiss, "read_index", spy)
    sha_calls: list[int] = []
    real_sha = vk._sha256_file

    def sha_spy(path):
        sha_calls.append(1)
        return real_sha(path)

    monkeypatch.setattr(vk, "_sha256_file", sha_spy)
    assert store.load_ann_index() is False
    first_reads, first_shas = len(reads), len(sha_calls)
    for _ in range(6):
        assert store.load_ann_index() is False
    assert len(reads) == first_reads, "代次拒用不得每查重付 mmap 重开"
    assert len(sha_calls) == first_shas, "代次拒用不得每查重付 order sha"

    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 64 * _GIB)
    assert store.build_ann_index()["built"] is True
    assert store.load_ann_index() is True, "重建后不得抱着旧拒用判定不放"
    assert store._attested_covered_generation() == store._embed_generation_now()


def test_stamp_raise_cannot_launder_generation(tmp_path):
    """洗绿禁区：只动戳（升降都行）不许翻代次判定——代次只认嵌入提交点。"""
    store, covered = _published_store(tmp_path)
    _delete_embedded_docs(store, "a", 5)
    _append_embedded(store, 5, "n")
    store._drop_ann_cache()
    assert store.load_ann_index() is False
    store._stamp_expected_vector_count(_ntotal_on_disk(store))  # 「把戳抬高回去」
    store._drop_ann_cache()
    assert store.load_ann_index() is False, (
        "戳自我认证 + 代次放行 = 完备性闸二次被掏空（test_ann_certify_prewarm 同族陷阱）"
    )
    assert store._attested_covered_generation() == covered, "落戳点不许顺手抬代次"


def test_certify_new_stamp_does_not_move_covered_generation(tmp_path):
    """无戳补盖只证「库形真值」，不证「代次覆盖」——补盖后旧代继续被守卫拒。"""
    store, covered = _published_store(tmp_path)  # covered := G_publish
    _append_embedded(store, 5, "n")  # 戳 25 > ntotal 20：旧闸先拦一下
    _delete_embedded_docs(store, "n", 5)  # 再把新 5 条删回去：戳回 20 == ntotal
    assert _stamp(store) == 20 == _ntotal_on_disk(store)
    store._drop_ann_cache()
    assert store.load_ann_index() is False  # 代次拦（今天红：放行）
    _drop_stamp_key(store)
    assert store.certify_expected_vector_count() == 20
    assert store._attested_covered_generation() == covered, (
        "certify 补盖不许抬代次证明——它就是这条洗绿路的注毒形态"
    )
    store._drop_ann_cache()
    assert store.load_ann_index() is False


def test_reconcile_success_advances_covered_generation(tmp_path, monkeypatch):
    """集合级自证成立处（id 集恒等的重嵌）代次证明必须跟到位，
    否则纠偏成功后守卫又不认账——判据自相矛盾、库被永久钉暴力。

    构造改写于此（2026-09-26 SEAT-S161）：首版用「换内容重嵌」想造出
    「id 集恒等 + 代次前进」，但 chunk_id 本身就是正文的派生物
    （`sync_documents`/`sync_chunks` 里都是 `sha1(路径:序号:正文)`），
    **换内容必然换 id** ⇒ `reconcile_ann_completeness` 的集合格当场判
    `id_set_mismatch`（实测日志坐实），集合级自证在这种形态下数学上不可能成立。
    同一形状的唯一诚实构造是「正文一字不动、向量作废重嵌」：走真漏斗
    `_clear_all_vectors` 清向量（戳同事务归 0，与 `embed_pending` 重嵌把戳涨回
    20、代次至少 +1）。**断言与判据一字未动**。
    另把纠偏的内存地板 monkeypatch 掉：那是与本锁无关的另一道门，留着它 =
    让这条锁看这台机器今晚的空闲内存脸色（邻居件 test_ann_stamp_drift_correction
    的同族用例同样按需 patch）——只消除假红，不放宽任何判定。
    """
    store, covered = _published_store(tmp_path)
    assert covered >= 1
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 64 * _GIB)
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        assert store._clear_all_vectors(conn) == 20, "前提：全库向量作废（真漏斗）"
        conn.commit()
    assert store.embed_pending(None) == (20, 20)  # 重嵌：id 集不变、代数 +≥1
    assert store._embed_generation_now() > covered
    _write_raw_stamp(store, "25")  # 「戳虚高、集合恒等」的纠偏可成立态
    store._drop_ann_cache()
    assert store.load_ann_index() is False
    assert store.certify_expected_vector_count(drift_correction=True) == 20
    assert store._attested_covered_generation() == store._embed_generation_now()
    store._drop_ann_cache()
    assert store.load_ann_index() is True, "纠偏证明了覆盖，守卫必须认账"


def test_publish_records_build_start_generation(tmp_path, monkeypatch):
    """发布盖章的代次 = **光标打开时**的代数：重建期间别处又嵌了东西，
    新代不被自己背书（继续拒用，下轮重建收编），方向只严不松。

    构造纪律（本件改写于此，2026-09-26 SEAT-S161）：中途那一批必须由**另一个
    store 实例**提交。首版直接调 `store.embed_pending`，而 `build_ann_index` 全程
    持着 `self._maintenance_lock`（`threading.Lock`，非重入）——同实例再进
    `embed_pending` 就是自锁死，整条用例永久挂死（实测 90s 无输出被强杀）。
    生产上"重建期间别处在补嵌"的写者本就是**另一个进程**（各持自己的维护锁），
    独立实例正是它的等价形态；触发点后移到 `faiss.write_index`（读向量的光标
    此刻已经关闭，避免同表读写在 rollback journal 下互相咬住）。
    断言与判据一字未动。
    """
    store = _make_store(tmp_path, count=20)
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 64 * _GIB)
    monkeypatch.setattr(vk, "_ANN_BUILD_BATCH_SIZE", 8)
    g_at_start = store._embed_generation_now()  # 20 条已嵌完，光标还没开
    rival = _sibling_store(store)
    real_write_index = vk.faiss.write_index
    state = {"fired": False}

    def write_index_then_embed(index, path):
        out = real_write_index(index, path)
        if not state["fired"]:
            state["fired"] = True
            _append_embedded(rival, 4, "late")  # 首批之后：另一路又提交了一批
        return out

    monkeypatch.setattr(vk.faiss, "write_index", write_index_then_embed)
    assert store.build_ann_index()["built"] is True
    att = store._read_ann_attestation()
    assert int(att["embed_generation"]) == g_at_start, (
        "发布盖章必须钉在光标打开时的代数，不是 publish 现读的"
    )
    assert store._embed_generation_now() > int(att["embed_generation"])
    store._drop_ann_cache()
    assert store.load_ann_index() is False, "中途补嵌后这一代也不许放行"
    monkeypatch.setattr(vk.faiss, "write_index", real_write_index)
    assert store.build_ann_index()["built"] is True  # 下一轮把 late 批收编
    store._drop_ann_cache()
    assert store.load_ann_index() is True, "干净重建后必须收敛回放行"


def test_generation_funnel_structure_locks():
    """活性/禁区三发结构锁：
    ① 推进 `_advance_embed_generation` 的调用点只许 `_save_vectors`（唯一向量写点）；
    ② 给 `embed_generation` 下标赋值的只许 `certify_expected_vector_count`
      （纠偏提交点），且 `_publish_ann_pair` 的代际证明字典必须含这个键；
    ③ `_stamp_expected_vector_count` 体内不许出现任何代次推进（洗绿禁区）。
    """
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    funcs = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    advancers = {
        name
        for name, fn in funcs.items()
        if any(
            isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and c.func.attr == "_advance_embed_generation"
            for c in ast.walk(fn)
        )
    }
    assert advancers == {"_save_vectors"}, f"代次推进调用点越界：{sorted(advancers)}"

    writers: set[str] = set()
    for name, fn in funcs.items():
        for node in ast.walk(fn):
            if isinstance(node, (ast.Assign, ast.AugAssign)) and any(
                isinstance(t, ast.Subscript)
                and isinstance(t.slice, ast.Constant)
                and t.slice.value == "embed_generation"
                for t in getattr(node, "targets", [getattr(node, "target", None)])
            ):
                writers.add(name)
    assert writers <= {"certify_expected_vector_count"}, (
        f"代次证明下标写点越界（第二个盖章口 = 第二真身）：{sorted(writers)}"
    )
    publish_body_has_key = any(
        isinstance(n, ast.Constant) and n.value == "embed_generation"
        for n in ast.walk(funcs["_publish_ann_pair"])
    )
    assert publish_body_has_key, "_publish_ann_pair 没把代次记进代际证明"
    assert not any(
        isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute)
        and c.func.attr == "_advance_embed_generation"
        for c in ast.walk(funcs["_stamp_expected_vector_count"])
    ), "落戳口推进代次 = 把「抬高回去」洗绿写进正门"


def test_load_path_cold_accept_is_two_meta_point_reads(tmp_path):
    """守卫不给请求路径添账：冷载入放行只许 2 发 knowledge_meta 点查
    （ann_signature + 三键合一 IN 查询），零 knowledge_chunks 触碰。"""
    store, _ = _published_store(tmp_path)
    store._drop_ann_cache()
    traced: list[str] = []
    connection = store._connect()
    connection.set_trace_callback(lambda sql: traced.append(str(sql)))
    try:
        assert store.load_ann_index() is True
    finally:
        connection.set_trace_callback(None)
    meta_reads = [sql for sql in traced if "knowledge_meta" in sql]
    assert len(meta_reads) == 2, f"冷载入 meta 读点失配（钉的是成本不是猜）：{meta_reads}"
    assert [sql for sql in traced if "knowledge_chunks" in sql] == []
    combined = [sql for sql in meta_reads if " IN (" in sql]
    assert len(combined) == 1, "计数戳/代数/代际证明必须一发 IN 查询合取"


def test_combined_meta_read_uses_pk_search(tmp_path):
    """三键 IN 查询仍是主键 SEARCH——写成全表 SCAN 就是把每问一发变扫库。"""
    store, _ = _published_store(tmp_path)
    sql = "SELECT key, value FROM knowledge_meta WHERE key IN (?, ?, ?)"
    with sqlite3.connect(store.db_path) as conn:
        plan = "\n".join(
            str(row[-1])
            for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", ("a", "b", "c"))
        )
    assert "SCAN knowledge_meta" not in plan, plan


def test_generation_bump_survives_stamp_absent_store(tmp_path):
    """无戳库补嵌照常涨代次（不建戳，但覆盖证明不能瞎）：
    `_bump_expected_vector_count` 的「无戳不建戳」纪律不适用于代次计数。"""
    store = _make_store(tmp_path, count=10)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM knowledge_meta WHERE key = ?", (_STAMP_KEY,))
        conn.commit()
    before = store._embed_generation_now()
    _append_embedded(store, 4, "x")
    assert store._embed_generation_now() > before
    assert _stamp(store) is None, "代次推进不许顺路建戳（那是另一条禁区）"


# =============================================================================
# §1 内存计价：与实测峰值同阶 + 显式安全余量 + 10 GiB 必须开火
# =============================================================================


def test_demand_price_is_same_order_as_measured_peak():
    """今晚规模上，前置门要价与**实测全量峰值**同带：≥ 峰值下沿（不许偷偷调小
    线性价本身）、≤ 峰值上沿 × 2（与实测同阶，余量必须有限名有据）。

    那 3.6–3.9 GiB 的峰值是 **fp32 时代**量到的（`IndexHNSWFlat`，每维 4 字节），
    所以这条锁按位宽=4 复算——它钉的是"线性价的形状没被人为压低"，与存储格式
    无关。SQ8（S181）自己的价由 `_ANN_INDEX_SQ8_*` 那两枚常量钉在下一节。
    """
    dim = 1024
    storage_fp32 = vk._ANN_INDEX_BYTES_PER_DIM
    try:
        vk._ANN_INDEX_BYTES_PER_DIM = 4  # 复算 fp32 时代的价
        demand = vk._ann_build_demand_bytes(_PRODUCTION_STAMP_TONIGHT, dim)
    finally:
        vk._ANN_INDEX_BYTES_PER_DIM = storage_fp32
    assert demand >= _MEASURED_FULL_REBUILD_PEAK_GIB_LOW * _GIB, (
        "模型价低于实测峰值本身 = 把线性价调小冒充重定标（裁定明令禁止）"
    )
    assert demand <= _MEASURED_FULL_REBUILD_PEAK_GIB_HIGH * _GIB * 2, (
        f"要价 {demand / _GIB:.2f}GiB 脱离实测峰值 3.6–3.9GiB 两个倍数"
        f" = 今晚 {_PRODUCTION_MIDWAY_PRICE_TONIGHT_GIB}GiB 的旧病"
    )


def test_sq8_price_tracks_measured_storage_ratio():
    """S181 换存储格式的价必须跟着落盘比例走，且**不许偷偷替回 fp32**。

    实测（60,400 条生产真向量、400 条真查询、K=4、同图参数）：
      fp32 262.1 MB → SQ8 77.8 MB = 0.297 倍，top-4 一致率 0.9856。
    这里钉三件：① 现役位宽必须是 1（8-bit），② 要价必须落在"实测比例 ± 一倍"
    这个带内（不许有人把位宽改回 4 却留着量化器名、也不许把价压到比例的两倍以下
    充当更省），③ 今晚真实形状（740,267 条 / 1024 维）下 **2.4 GiB 可用必须放行、
    1.2 GiB 仍必须拒**——放行是换存储格式要买的东西（fp32 时代要 6.0 GiB），
    拒则是门不许被改成摆设。
    """
    assert vk._ANN_INDEX_BYTES_PER_DIM == 1, "位宽不再是 1 ⇒ 上面那份实测比例作废"
    assert vk._ANN_INDEX_QUANTIZER_NAME == "QT_8bit", "量化器与位宽脱钩"
    demand = vk._ann_build_demand_bytes(_PRODUCTION_STAMP_TONIGHT, 1024)
    fp32_demand = 4.0 * _GIB  # 同规模 fp32 实测峰值带（3.6–3.9）
    assert fp32_demand * 0.20 <= demand <= fp32_demand * 0.75, (
        f"SQ8 要价 {demand / _GIB:.2f}GiB 与实测落盘比例 0.297 脱带"
    )
    real = vk._available_physical_memory_bytes
    try:
        vk._available_physical_memory_bytes = lambda: int(2.4 * _GIB)
        verdict = vk._evaluate_ann_build_memory_gate(_PRODUCTION_STAMP_TONIGHT, 1024)
        vk._available_physical_memory_bytes = lambda: int(1.2 * _GIB)
        low = vk._evaluate_ann_build_memory_gate(_PRODUCTION_STAMP_TONIGHT, 1024)
    finally:
        vk._available_physical_memory_bytes = real
    assert verdict.allowed is True, (
        f"换存储却买不到开火 = 这趟白改（要价 {verdict.required_bytes / _GIB:.2f}GiB "
        f"vs 2.4GiB 可用）"
    )
    assert low.allowed is False, "低于要价仍放行 = 门被改成了摆设"


def test_gate_allows_fire_on_32gib_machine_at_10gib_free():
    """裁定③：32 GiB 机器 10 GiB 空闲必须允许开火（今晚形状要价下旧门恒拒）。
    反向牙：2 GiB 空闲仍必须拒——重定价不许把真低内存也放行。"""
    real = vk._available_physical_memory_bytes
    try:
        vk._available_physical_memory_bytes = lambda: 10 * _GIB
        verdict = vk._evaluate_ann_build_memory_gate(_PRODUCTION_STAMP_TONIGHT, 1024)
        vk._available_physical_memory_bytes = lambda: 2 * _GIB
        low = vk._evaluate_ann_build_memory_gate(_PRODUCTION_STAMP_TONIGHT, 1024)
    finally:
        vk._available_physical_memory_bytes = real
    assert verdict.allowed is True, (
        f"10GiB 空闲被拒：要价 {verdict.required_bytes / _GIB:.2f}GiB"
        "（同阶于实测峰值+显式余量的新价必须放行今晚形状）"
    )
    assert low.allowed is False, "2GiB 空闲放行 = 把 OOM 守卫改成了摆设"


def test_midway_observed_leg_no_longer_extrapolates_early_slope(tmp_path, monkeypatch):
    """今晚 14.04GiB 的出生地：中途腿拿「首批实吃」线性外推剩余全部。
    早期吃进以读链页缓存为主，外推价对任何机器都判死。
    新口径 = 已吃实账 + 剩余模型价。

    重放形状：前置 2GiB 放行，8 条后已耗 0.62GiB（单位 83MiB——外推必死），
    可用 1.38GiB。旧式 0.62+16×83MiB+余量 ≈ 2.1GiB > 1.38 ⇒ 收火；
    新式 0.62+模型(16,8) ≈ 0.75GiB ≤ 1.38 ⇒ 建完。
    """
    store = _make_store(tmp_path, count=24)
    monkeypatch.setattr(vk, "_ANN_BUILD_BATCH_SIZE", 8)
    monkeypatch.setattr(vk, "_ANN_BUILD_MEMORY_RECHECK_VECTORS", 8)
    reads = {"n": 0}

    def _fake_available() -> int:
        reads["n"] += 1
        return 2 * _GIB if reads["n"] == 1 else int(1.38 * _GIB)

    monkeypatch.setattr(vk, "_available_physical_memory_bytes", _fake_available)
    result = store.build_ann_index()
    assert result["built"] is True, (
        f"首批页缓存吃进被外推成整场需求 = 旧病复发：{result.get('reason')}"
        f"（要价 {result.get('memory_gate', {}).get('required')}）"
    )


def test_midway_breaker_still_bites_when_really_eaten(tmp_path, monkeypatch):
    """断路器不许被重定标摘牙：前置 8GiB，8 条后实测只剩 0.9GiB（真吃掉
    7.1GiB——不是缓存，是账）⇒ 「已吃+模型剩余」必收火。
    反证腿：摘成纯模型价必须建完（证明收火归因于观测腿，不是别的顺手拦）。"""
    store = _make_store(tmp_path, count=24)
    monkeypatch.setattr(vk, "_ANN_BUILD_BATCH_SIZE", 8)
    monkeypatch.setattr(vk, "_ANN_BUILD_MEMORY_RECHECK_VECTORS", 8)
    reads = {"n": 0}

    def _fake_available() -> int:
        reads["n"] += 1
        return 8 * _GIB if reads["n"] == 1 else int(0.9 * _GIB)

    monkeypatch.setattr(vk, "_available_physical_memory_bytes", _fake_available)
    result = store.build_ann_index()
    assert result["built"] is False
    assert result["reason"] == "insufficient_memory_midway", result

    monkeypatch.setattr(
        vk,
        "_ann_projected_requirement_bytes",
        lambda remaining, dim, **kw: vk._ann_build_demand_bytes(remaining, dim),
    )
    reads["n"] = 0
    assert store.build_ann_index()["built"] is True, "收火不是观测腿干的 = 本锁空转"


def test_price_constants_documented_as_calibration():
    """要求①：常量块白纸黑字「标定不是物理下限」+ 显式命名的安全余量；
    要求②：复算口径逐字节可重算（式子改了忘同步锁必红）。"""
    source = _SOURCE.read_text(encoding="utf-8")
    const_block = source.split("# --- ANN 重建内存门", 1)[1].split(
        "def _available_physical_memory_bytes", 1
    )[0]
    assert "标定" in const_block and "不是物理下限" in const_block, "标定身份没写进常量块"
    assert "安全余量" in const_block, "显式命名的安全余量没在册"
    assert "_ANN_INDEX_BYTES_PER_DIM" in const_block, (
        "存储位宽没进这枚常量块——价模型的第一项就是它，写在块外等于"
        "让'换存储格式'绕过复算口径"
    )
    n = 100_000
    dim = 1024
    demand = vk._ann_build_demand_bytes(n, dim)
    storage = dim * vk._ANN_INDEX_BYTES_PER_DIM
    per_vector = (
        storage
        + storage * vk._ANN_BUILD_FAISS_REALLOC_BYTES_PER_DIM // 4
        + (vk._ANN_BUILD_MEASURED_BYTES_PER_VECTOR - vk._ANN_BUILD_MEASURED_DIM * 4)
        + vk._ANN_BUILD_ID_TABLE_BYTES_PER_VECTOR
    )
    linear = n * per_vector
    slack = vk._ann_build_batch_slack_bytes(dim)
    margin = max(
        vk._ANN_BUILD_MIN_HEADROOM_BYTES,
        (linear + slack) // vk._ANN_BUILD_HEADROOM_RATIO,
    )
    assert demand == linear + slack + margin, "复算口径与实价脱钩"


def test_force_escape_flag_semantics_unchanged(tmp_path, monkeypatch):
    """要求④：`--ann-force-low-memory` 越门路径一字不动——低内存照样拦、
    越门照样开火（越门记痕与计数账在 s156 件，本锁钉「存在且有效」的活性）。"""
    store = _make_store(tmp_path, count=8)
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 1)
    assert store.build_ann_index()["reason"] == "insufficient_memory"
    assert store.build_ann_index(force_low_memory=True)["built"] is True, (
        "越门旗标失效 = 运维放行通道被没收"
    )


# =============================================================================
# §3 FTS：不依赖 ANN publish 的喂入口（可见 + 不连带改判 + 不上请求路径）
# =============================================================================


class _FtsTaskStore:
    """kb-sync 任务替身：ANN 被内存门挡死（简报里 FTS 饿死的触发形态），
    ensure/status 两个口按剧本行为。"""

    def __init__(self, *, ensure_mode: str, rows: int = 20, signature: str = "a" * 40) -> None:
        self.embed_provider = SimpleNamespace(name="p")
        self.ann_index_path = str(Path(__file__))
        self.ann_order_path = str(Path(__file__))
        self._ensure_mode = ensure_mode
        self._rows = rows
        self._signature = signature
        self.ensure_calls: list[bool] = []
        self.meta: dict[str, str] = {}
        self.build_ann_calls = 0

    def sync_documents(self, docs, *, removed_ids=(), full=False, on_progress=None):
        return {"added": 3, "changed": 0, "removed": 0, "skipped": 0, "chunks": 3}

    def embed_pending(self, files, on_progress=None, *, batch_size=None):
        return 0, 0

    def stats(self) -> dict[str, int]:
        return {"total": self._rows, "embedded": self._rows}

    def document_count(self) -> int:
        return 10

    def build_ann_index(self, on_progress=None, *, force_low_memory=False) -> dict:
        self.build_ann_calls += 1
        return {"built": False, "reason": "insufficient_memory"}

    def certify_expected_vector_count(self, *, drift_correction: bool = False):
        return None

    def ensure_fts_index(self, *, force: bool = False) -> bool:
        self.ensure_calls.append(force)
        if self._ensure_mode == "raise":
            raise RuntimeError("fts5 unavailable")
        return self._ensure_mode == "ok"

    def fts_index_status(self) -> dict:
        if self._ensure_mode != "ok":
            return {"rows": 0, "signature": "", "table_present": False}
        return {"rows": self._rows, "signature": self._signature, "table_present": True}

    def set_meta(self, key: str, value: str) -> None:
        self.meta[key] = value

    def get_meta(self, key: str) -> str:
        return self.meta.get(key, "")


_FTS_CONFIG = SimpleNamespace(bot_kb_wiki_chunk_chars=800, bot_kb_wiki_embed_batch=128)


@pytest.fixture()
def _fts_sync_isolated(monkeypatch):
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


def test_fts_fed_and_visible_even_when_ann_refused(_fts_sync_isolated):
    """①+③：ANN 被内存门挡下的那一轮，FTS 照常被喂，且 summary 报行数与签名。"""
    store = _FtsTaskStore(ensure_mode="ok", rows=123_456, signature="b" * 40)
    result = kb_wiki.run_kb_sync_task(_FTS_CONFIG, store=store)
    assert store.build_ann_calls == 1 and store.ensure_calls == [True]
    assert result["ann_built"] is False, "FTS 喂入口不许反手把 ANN 结论洗成成功"
    assert result["fts_built"] is True
    assert result["fts_rows"] == 123_456
    assert result["fts_signature"] == ("b" * 40)[:16]
    summary = kb_wiki._sync_summary(result)
    assert summary["fts_built"] is True and summary["fts_rows"] == 123_456
    assert summary["fts_signature"] == ("b" * 40)[:16]
    assert "关键词通道" in str(result["public_message"]), "告警读者读不到 FTS 面 = 白喂"


def test_fts_failure_does_not_touch_sync_or_ann_verdict(_fts_sync_isolated):
    """④反向锁：FTS 炸了 ⇒ ok 与 ann 结论逐字不动（不升级也不连坐下），
    但失败本身必须点名可归因，不许静默吞。"""
    store = _FtsTaskStore(ensure_mode="raise")
    result = kb_wiki.run_kb_sync_task(_FTS_CONFIG, store=store)
    assert result["ok"] is True
    assert result["ann_built"] is False and result["ann_reason"] == "insufficient_memory"
    assert result["fts_built"] is False
    msg = str(result["public_message"])
    assert "关键词通道" in msg and "fts5 unavailable" in msg, "失败不可归因 = 又一次静默 except"
    summary = kb_wiki._sync_summary(result)
    assert summary["fts_built"] is False


def test_fts_ensure_false_is_reported_not_fabricated(_fts_sync_isolated):
    """ensure 返回 False（非异常）同样如实上账，行数/签名走 status 真值。"""
    store = _FtsTaskStore(ensure_mode="false")
    result = kb_wiki.run_kb_sync_task(_FTS_CONFIG, store=store)
    assert result["fts_built"] is False
    assert result["fts_rows"] == 0
    assert result["fts_signature"] == ""
    assert "关键词通道" in str(result["public_message"])


def test_real_store_fts_index_status_matches_truth(tmp_path):
    """status 不是第二口径：行数=真表 COUNT、签名=真 meta 行。"""
    store = _make_store(tmp_path, count=6)
    assert store.ensure_fts_index(force=True) is True
    status = store.fts_index_status()
    with sqlite3.connect(store.db_path) as conn:
        rows = int(conn.execute("SELECT COUNT(*) FROM knowledge_chunks_fts").fetchone()[0])
    assert status["rows"] == rows == store.stats()["total"]
    assert status["signature"] == store._stored_fts_signature()
    assert status["table_present"] is True


def test_fts_status_never_on_request_path(tmp_path, monkeypatch):
    """②：重口径只住维护线程——retrieve 全程零 `fts_index_status` 调用。"""
    store = _make_store(tmp_path, count=20)
    calls: list[int] = []
    real = vk.SqliteVectorKnowledgeStore.fts_index_status

    def spy(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(vk.SqliteVectorKnowledgeStore, "fts_index_status", spy)
    assert store.retrieve("【a-doc-3】正文内容3")
    assert store.ensure_fts_index(force=True) is True
    assert calls == [], "关键词行数进了请求路径 = 每条消息全表计数"


def test_kb_wiki_tail_feed_is_outside_ann_branch():
    """接线活性锁：收尾 ensure 必须在 ANN 重建 if/else 的**外面**，
    否则「ANN 被挡 ⇒ FTS 挨饿」原病复发。AST 判，不靠肉眼。"""
    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/bot_unified_runtime/domains/location/knowledge/kb_wiki.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    task = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_run_kb_sync_task_locked"
    )
    ensure_sites = [
        node
        for node in ast.walk(task)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "ensure_fts_index"
    ]
    assert ensure_sites, "kb-sync 收尾的 ensure_fts_index(force=True) 调用点消失了"
    ann_if = next(
        node
        for node in ast.walk(task)
        if isinstance(node, ast.If)
        and any(
            isinstance(c, ast.Name) and c.id == "sync_changed" for c in ast.walk(node.test)
        )
    )
    for site in ensure_sites:
        assert site.lineno > ann_if.orelse[-1].lineno, (
            "收尾喂入点缩回了 ANN 分支体内 = 病根复位（判据变松）"
        )


# =============================================================================
# §4 FTS 失败留痕（P-4，2026-09-27 晨）：建没建成必须一行可判
#
# 本波实况：夜间收尾报 fts_built=false 而**零原因**——`_rebuild_fts` 的
# `except sqlite3.Error: return None` 与 `ensure_fts_index` 的
# `except Exception: return False` 各吞一层，判「为什么没建成」只能靠猜
# （我据此猜了 schema、猜了毒行、猜了盘量，五发探针问的是不存在的问题）。
# 两把锁各钉一条出口：异常必须落一条 WARNING 且点名异常类型。
# =============================================================================


def test_fts_rebuild_failure_logs_the_exception_type(tmp_path, caplog, monkeypatch):
    """`_rebuild_fts` 撞上 sqlite 错误时，必须留一行点名类型的 WARNING，不许静默退 None。"""
    store = _make_store(tmp_path, count=8)
    assert store.build_ann_index()["built"] is True
    monkeypatch.setattr(vk, "_FTS_CREATE_SQL", "CREATE VIRTUAL TABLE broken_fts USING fts5(")

    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store._rebuild_fts() is None, "建表语句被截断，重建必须失败"

    reasons = [r.getMessage() for r in caplog.records if "fts" in r.getMessage().lower()]
    assert reasons, "FTS 重建失败必须留痕（本波就是靠这里没留痕猜了五轮）"
    assert "OperationalError" in reasons[0], f"留痕必须点名异常类型：{reasons[0]}"


def test_ensure_fts_index_logs_the_outer_exception(tmp_path, caplog, monkeypatch):
    """`ensure_fts_index` 的外层兜底同理：降级为纯向量通道可以，不出声不行。"""
    store = _make_store(tmp_path, count=8)

    def _boom() -> None:
        raise RuntimeError("fts5 module missing (simulated)")

    monkeypatch.setattr(store, "_ensure_fts_table", _boom)
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.ensure_fts_index(force=True) is False

    reasons = [r.getMessage() for r in caplog.records if "RuntimeError" in r.getMessage()]
    assert reasons, "外层 except 吞掉非 sqlite 异常时也必须点名（否则两把锁只钉住一半）"
    assert "fts5 module missing (simulated)" in reasons[0], "原因原文要可归因，不许只剩类型名"

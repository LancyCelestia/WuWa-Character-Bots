"""ANN 完备性闸回归锁（task #47：签名相等绝不等于索引完备）。

钉死的事实（2026-09-21 实弹根因）：`embedding_signature` 与 `ann_signature` 存的都是
同一个模型/端点指纹，补嵌再多行都不动它俩；`.index` 与 `.order.json` 的同代校验
（`ntotal == len(order)`）只证明两个文件彼此对得上，证明不了它们追得上 SQLite。
于是「两周前建、只覆盖当时向量」的索引可以一直被判新鲜，新嵌入内容对向量通道
永久隐身，而所有体检面全绿。

本套用例锁住修法与它的成本边界：

1. 载入期把 `index.ntotal` 与 knowledge_meta 里的计数戳比一次，短装即判索引不可用，
   回落**既有**暴力通道（`_vector_candidates` → numpy 矩阵 / 纯 Python 余弦），
   并出结构化告警，两个数字同屏点名。
2. 计数戳的权威赋值点只有 ANN 提交点（`_publish_ann_pair` := index.ntotal），
   此后只有唯一向量写点（`_save_vectors`）在同一事务里推高它。
3. 载入路径**绝不**出现 `SELECT COUNT(*) ... WHERE vector_json IS NOT NULL`
   （该表实测 23.8s 的 JSON 列扫描）——用 EXPLAIN QUERY PLAN 与 SQL 轨迹把它钉成
   结构判据，不用墙钟判据。

全程离线 tmp_path，零真实网络、零生产文件读写。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    vector_knowledge as vk,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)

pytestmark = pytest.mark.skipif(vk.faiss is None, reason="faiss 缺失时本套无意义")

_DIM = 8
_WARN_PREFIX = "knowledge ANN completeness refused"


class _FakeEmbedder:
    """sha1 伪向量：8 维、确定性、零网络（沿用 tests/test_ann_atomic_publish.py 口径）。"""

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


def _append_embedded(store: SqliteVectorKnowledgeStore, count: int, tag: str) -> str:
    """增量加 N 条文档并补嵌（**不重建索引**）——这正是造短装态的唯一途径。

    走的是公开入口：sync_documents(full=False) 只插新块（vector_json=NULL），
    embed_pending → _save_vectors 落向量。返回最后一条新块的 chunk_id。
    """
    store.sync_documents(iter(_docs(count, tag)), removed_ids=[], full=False)
    done, total = store.embed_pending(None)
    assert done == total == count, f"补嵌未完成：{done}/{total}"
    with sqlite3.connect(store.db_path) as conn:
        chunk_id = conn.execute(
            "SELECT chunk_id FROM knowledge_chunks WHERE source_id = ? ORDER BY chunk_id",
            (f"topic/{tag}-doc-{count - 1}",),
        ).fetchone()[0]
    return str(chunk_id)


def _ntotal_on_disk(store: SqliteVectorKnowledgeStore) -> int:
    return int(vk.faiss.read_index(str(store.ann_index_path)).ntotal)


def _signatures(store: SqliteVectorKnowledgeStore) -> tuple[str, str]:
    with sqlite3.connect(store.db_path) as conn:
        rows = {
            str(row[0]): str(row[1])
            for row in conn.execute(
                "SELECT key, value FROM knowledge_meta "
                "WHERE key IN ('ann_signature','embedding_signature')"
            )
        }
    return rows.get("ann_signature", ""), rows.get("embedding_signature", "")


def _stamp(store: SqliteVectorKnowledgeStore) -> int | None:
    return store._stamped_expected_vector_count()


# --- ①落戳 / 涨戳：戳的两个（也是仅有的）写入点 --------------------------------


def test_publish_stamps_expected_count_equal_to_live_ntotal(tmp_path):
    """提交点落戳：戳 == 索引实装向量数 == 已嵌入行数（三者在建成后必须同值）。"""
    store = _make_store(tmp_path, count=20)
    result = store.build_ann_index()
    assert result["built"] is True and result["vectors"] == 20

    assert _stamp(store) == 20, "提交点必须把本代向量数落成完备性基线"
    assert _ntotal_on_disk(store) == _stamp(store), "戳必须与索引实装数等值"
    assert store.stats()["embedded"] == _stamp(store), "戳必须等于库里已嵌入行数"
    assert store.load_ann_index() is True


def test_write_point_bumps_stamp_in_lockstep_with_embedded_rows(tmp_path):
    """唯一写点涨戳：每补嵌一行，戳 +1；索引没重建 ⇒ 戳与 ntotal 拉开缺口。"""
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    assert _stamp(store) == 20

    _append_embedded(store, 30, "b")

    assert _stamp(store) == 50, "补嵌 30 行必须把戳从 20 推到 50"
    assert store.stats()["embedded"] == 50
    assert _ntotal_on_disk(store) == 20, "没重建就不该动索引（短装态成立）"


def test_stamp_bump_participates_in_the_callers_transaction(tmp_path):
    """戳必须与向量同事务：回滚留下虚高的戳 = 永久假短装；提交则必须真涨。

    直接驱动 `_save_vectors` 使用的那对语句（调用方连接、调用方事务），
    走 rollback / commit 两条出口——只测公开 API 形状测不出这个性质。
    """
    store = _make_store(tmp_path, count=20)
    assert store.build_ann_index()["built"] is True
    assert _stamp(store) == 20

    conn = sqlite3.connect(store.db_path)
    try:
        SqliteVectorKnowledgeStore._bump_expected_vector_count(conn, 5)
        conn.rollback()
    finally:
        conn.close()
    assert _stamp(store) == 20, "回滚后戳必须仍是 20，不许留下 25 的假短装"

    conn = sqlite3.connect(store.db_path)
    try:
        SqliteVectorKnowledgeStore._bump_expected_vector_count(conn, 5)
        conn.commit()
    finally:
        conn.close()
    assert _stamp(store) == 25, "提交时戳必须真的推进（bump 不是空操作）"


def test_stamp_absent_is_never_seeded_from_zero_at_the_write_point(tmp_path):
    """无戳不建戳：从 0 起算会造出远小于真实向量数的戳，反而把短装洗成正常。

    存量库正是这形态——上万行嵌于本闸上线之前，补嵌只能让它继续「不可判定」，
    由载入端按不可认证拒绝，等 knowledge-sync 重建来认证。
    """
    store = _make_store(tmp_path, count=20)  # 只 embed，从未 build ⇒ 无戳
    assert store.stats()["embedded"] == 20
    assert _stamp(store) is None

    _append_embedded(store, 5, "b")

    assert _stamp(store) is None, "无戳时写点不得凭空造一个 5 出来"
    assert store.stats()["embedded"] == 25, "已嵌入 25 行却拿着戳 5 = 危险方向，必须不发生"


# --- ②短装拒用 + 结构化告警 + 回落既有暴力通道 --------------------------------


def test_consistent_stamped_index_loads_and_is_actually_used(tmp_path):
    """(a) 盖过戳且追得平的索引：载入成功，且向量通道真走 HNSW。"""
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    store._drop_ann_cache()

    assert store.load_ann_index() is True
    assert store._ann_index is not None
    assert store._ann_candidates([0.1] * _DIM, 4) is not None, "ANN 通道必须参战"


def test_short_index_is_refused_and_falls_back_with_structured_warning(
    tmp_path, caplog
):
    """(b) 短装索引：拒用 → 回落暴力 → 告警同屏点名两个数字，且新内容真的召得回。

    这是本闸的本职用例：它同时复现生产事故的判据形态——两个签名逐字节相等，
    成对校验也过（两个文件同代），只有「索引 vs SQLite」这一维能把它拦下。
    """
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    assert store.load_ann_index() is True

    new_chunk_id = _append_embedded(store, 30, "b")
    ann_sig, embed_sig = _signatures(store)
    assert ann_sig == embed_sig == "test|fake", (
        "用例没复现生产条件：签名相等才说明『签名新鲜』救不了短装"
    )

    store._drop_ann_cache()
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.load_ann_index() is False, "短装索引绝不许被当成新鲜"
    messages = [rec.getMessage() for rec in caplog.records if _WARN_PREFIX in rec.getMessage()]
    assert len(messages) == 1, f"结构化告警必须恰好一条，实得 {messages}"
    line = messages[0]
    assert "ntotal=20" in line, f"告警须点名索引实装数：{line}"
    assert "expected=50" in line, f"告警须点名库里应装数：{line}"
    assert "missing=30" in line, f"告警须点名差额：{line}"

    # 回落的是既有暴力通道，不是第二条实现。
    assert store._ann_candidates([0.1] * _DIM, 4) is None
    query = store.embed_provider.embed_texts(["【b-doc-29】正文内容29"])[0]
    chunk_ids, best = store._vector_candidates(query)
    assert new_chunk_id in chunk_ids, "暴力通道必须看得见新嵌入的块（这才是用户要的结果）"
    assert best > 0.9, f"自身查询应近乎满相似，实得 {best}"

    # 重建即自愈：戳重新落到 ntotal，闸放行。
    assert store.build_ann_index()["built"] is True
    store._drop_ann_cache()
    assert store.load_ann_index() is True
    assert _stamp(store) == _ntotal_on_disk(store) == 50


def test_legacy_unstamped_index_is_refused_as_uncertifiable(tmp_path, caplog):
    """存量库首次载入（本闸最关心的一条）：无戳 = 不可认证 ⇒ 拒用，绝不按 0 放行。

    模拟「索引由闸上线前的代码建好、文件与签名都完好、只是没有戳」。
    """
    store = _make_store(tmp_path, count=20)
    assert store.build_ann_index()["built"] is True
    store._drop_ann_cache()
    assert store.load_ann_index() is True

    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM knowledge_meta WHERE key = ?", (vk._EMBEDDED_COUNT_KEY,))
        conn.commit()
    assert _stamp(store) is None

    store._drop_ann_cache()
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.load_ann_index() is False, "无从证明完备的索引不得被当作完备"
    messages = [rec.getMessage() for rec in caplog.records if _WARN_PREFIX in rec.getMessage()]
    assert len(messages) == 1, f"缺戳必须出一条告警，实得 {messages}"
    assert "expected=unknown" in messages[0]
    assert vk._EMBEDDED_COUNT_KEY in messages[0], "告警要点名缺的是哪个键"
    assert Path(store.ann_index_path).is_file(), "拒用是只读判定，不许动线上产物"
    assert store._ann_candidates([0.1] * _DIM, 4) is None


def test_surplus_vectors_are_not_mistaken_for_shortfall(tmp_path):
    """只有「短装」这一侧拒用：索引比戳多（发布中途被杀留下的旧小戳）必须放行。

    那个索引本身是装满的，判它可用才是对的；反向多判就是无谓的永久暴力回落。
    """
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    store._stamp_expected_vector_count(10)  # 戳落后于文件的残态
    assert _ntotal_on_disk(store) == 20

    store._drop_ann_cache()
    assert store.load_ann_index() is True


def test_pair_checks_still_bite_before_the_completeness_gate(tmp_path):
    """闸是加在成对校验之后、不是取代它：混代（order 少一条）走的仍是 pair refused。"""
    store = _make_store(tmp_path, count=20)
    assert store.build_ann_index()["built"] is True
    order_path = Path(store.ann_order_path)
    order = json.loads(order_path.read_text(encoding="utf-8"))
    order_path.write_text(json.dumps(order[:-1]), encoding="utf-8")

    store._drop_ann_cache()
    assert store.load_ann_index() is False
    assert _stamp(store) == 20, "成对校验就该拦下，不该走到完备性判定"


# --- ③成本边界：载入路径没有那发 23.8s 扫描 -----------------------------------


def test_load_path_reads_only_meta_and_never_scans_chunks(tmp_path):
    """(c) 载入路径实际查了什么：只有 knowledge_meta 的主键点查，零 knowledge_chunks 触碰。

    结构判据，不用墙钟判据（本机计时噪声大，且 23.8s 是生产表规模下的数字）。
    """
    store = _make_store(tmp_path, count=20)
    assert store.build_ann_index()["built"] is True
    assert store.load_ann_index() is True
    store._drop_ann_cache()

    traced: list[str] = []
    connection = store._connect()
    connection.set_trace_callback(lambda sql: traced.append(str(sql)))
    try:
        assert store.load_ann_index() is True
    finally:
        connection.set_trace_callback(None)

    assert traced, "冷载入必须至少读几发 meta，空轨迹说明用例失钉"
    chunk_reads = [sql for sql in traced if "knowledge_chunks" in sql]
    assert chunk_reads == [], f"载入路径不得扫 chunks 表：{chunk_reads}"
    count_reads = [sql for sql in traced if "COUNT(" in sql.upper()]
    assert count_reads == [], f"载入路径不得有计数扫描：{count_reads}"
    assert all("knowledge_meta" in sql for sql in traced), f"只许读 meta：{traced}"
    # 戳读确实发生：ann_signature + attestation + 计数戳 = 恰好三发 meta 点查。
    assert len([sql for sql in traced if "knowledge_meta" in sql]) == 3, traced


def test_stamp_lookup_is_index_search_while_banned_count_is_table_scan(tmp_path):
    """把「便宜」和「贵」写成查询计划对照，而不是注释里的口头承诺。"""
    store = _make_store(tmp_path, count=20)

    def plan(sql: str) -> str:
        with sqlite3.connect(store.db_path) as conn:
            return "\n".join(
                str(row[-1]) for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}")
            )

    stamp_plan = plan(
        f"SELECT value FROM knowledge_meta WHERE key = '{vk._EMBEDDED_COUNT_KEY}'"
    )
    assert "SEARCH knowledge_meta" in stamp_plan, stamp_plan
    assert "USING INDEX" in stamp_plan, f"计数戳必须是主键点查：{stamp_plan}"

    banned_plan = plan(
        "SELECT COUNT(*) FROM knowledge_chunks "
        "WHERE vector_json IS NOT NULL AND vector_json != ''"
    )
    assert "SCAN knowledge_chunks" in banned_plan, (
        f"对照前提不成立：这条在库里不是全表扫描，用例失去意义：{banned_plan}"
    )
    assert "SEARCH" not in banned_plan, banned_plan


# --- ④注毒自证：这道闸不是空转 ------------------------------------------------


def test_completeness_gate_is_load_bearing(tmp_path):
    """(d) 变异探针：把阈值放宽到永远放行（等价于闸门失效），同一状态必须变回 True。

    反向也钉：阈值恢复后必须重新拒用。这一条证明上一条用例的红**是这道闸造成的**，
    而不是签名不匹配、成对校验失败之类的旁因——否则「拒用」那类断言可以靠任何
    一处早退糊过去，锁就失去杀伤力。
    """
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    _append_embedded(store, 30, "b")
    store._drop_ann_cache()
    assert store.load_ann_index() is False, "基线：短装态在真实阈值下必须被拒"

    original = vk._ANN_COMPLETENESS_MAX_MISSING
    vk._ANN_COMPLETENESS_MAX_MISSING = 10**9  # 注毒：闸门等效失效
    try:
        store._drop_ann_cache()
        assert store.load_ann_index() is True, (
            "注毒后仍拒用 ⇒ 上一轮的拒用与这道闸无关，完备性锁是假锁"
        )
    finally:
        vk._ANN_COMPLETENESS_MAX_MISSING = original

    store._drop_ann_cache()
    assert store.load_ann_index() is False, "撤毒必须恢复拒用（判据可逆）"


def test_never_refuse_a_certified_complete_index(tmp_path):
    """注毒的反向自证：闸也不得「恒拒」——追得平的戳必须放行，否则回落成常态。"""
    store = _make_store(tmp_path, count=20)
    store.build_ann_index()
    assert _stamp(store) == _ntotal_on_disk(store)

    for _ in range(3):
        store._drop_ann_cache()
        assert store.load_ann_index() is True, "完备且盖戳的索引被拒 = 闸门写反了方向"


def test_crash_before_publish_with_grown_corpus_is_refused(tmp_path, monkeypatch):
    """发布中途被杀 + 语料已涨：留下的旧代是真短装，必须拒用。

    与 tests/test_ann_atomic_publish.py:137
    `test_crash_before_publish_leaves_only_complete_previous_generation` 的
    `assert store.load_ann_index() is True, "旧代仍完整可用（回落不应发生）"`
    直接冲突：那条用例的 _seed(full=True) 先把索引所基于的 20 行删掉、再补嵌 40
    行，此刻库里已嵌 40 行而索引只装 20 行（且那 20 行的块已被删）——正是本闸
    要拦的形态。按本任务边界不改他波测试文件，改由本用例把新口径钉住，冲突与
    建议改法写进进度报告。
    """
    store = _make_store(tmp_path, count=20)
    assert store.build_ann_index()["built"] is True
    assert store.load_ann_index() is True

    def boom(_tmp_path: Path, _target: Path):
        raise OSError(28, "simulated ENOSPC mid-publish")

    monkeypatch.setattr(vk, "_atomic_replace_from", boom)
    store.sync_documents(iter(_docs(40, "b")), removed_ids=[], full=True)
    store.embed_pending(None)
    with pytest.raises(RuntimeError, match="ANN 原子换入失败"):
        store.build_ann_index()
    monkeypatch.undo()

    assert _ntotal_on_disk(store) == 20, "换入失败不许动线上文件"
    assert store.stats()["embedded"] == 40
    store._drop_ann_cache()
    assert store.load_ann_index() is False, "库里 40 行、索引 20 条：旧代不再「完整可用」"

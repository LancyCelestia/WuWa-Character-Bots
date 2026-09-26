"""SEAT-S201：ANN 整代重建断点续传的锁（全离线 tmp_path，零网络、零生产文件）。

背景（2026-09-26/27 夜）：本机连着几夜 OOM，每次重建都从第 0 条重跑 74 万条。
检查点三件套（半成品索引 / 半成品序列表 / knowledge_meta 一行 JSON）把"已装到
哪"落盘；续跑判据六道，任一不成立即整份丢弃重跑（原因进日志与返回字典）。

本文件每把锁各拦一种回归（编号对简报）：
① test_midway_abort_then_resume_publishes_full_index
   —— 拦"检查点写了却续不上/续错了还发布"：中途收火后再跑必须真从检查点
   续起（resumed_from>0），最终发布件 ntotal == len(order) == 库内已嵌入数。
② test_generation_change_during_gap_forces_rerun
   —— 拦"期间补嵌被续跑光标永久漏掉"：代次不等必须丢弃（resumed_from==0），
   且 publish 的代际证明盖**最终首段**（第二次开光标那一刻）的代次。
②b test_resumed_segment_publishes_first_segment_generation
   —— 拦"续跑段给自己现盖章"：中途补嵌发生在**续跑成功之后**时，发布章必须
   沿用首段（第一次中断前）的代次 ⇒ 该代被载入端拒用（危险方向被牙咬住）。
③ test_stamp_change_during_gap_forces_rerun
   —— 拦"order 里留死 id 的半成品被续用"（同 09-26 假绿形状）：戳不等 ⇒ 丢弃。
④ test_missing_or_truncated_wip_files_drop_without_crash
   —— 拦"半成品被动过还硬续"：文件没了/被截断 ⇒ 丢弃重跑、不崩、不发布半份。
⑤ test_publish_success_removes_checkpoint_trio
   —— 拦"残留长存"：publish 前三件确实在场（防本锁空转），publish 后行与
   两文件（含 .part）必须一个不剩。
⑥ test_wip_names_never_share_prefix_with_live_files
   + test_publish_atomic_replace_sequence_never_touches_wip
   —— 结构锁 + 行为锁：`.wip` 前缀与线上两枚零共前缀；`_publish_ann_pair`
   源码里不许出现 wip 字样；原子替换按调用方归因后，publish 序列的目标只许
   是线上两枚、检查点序列的目标只许是 `.wip` 两枚（半成品绝不被当成品发布、
   也绝不直写线上）。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from pathlib import Path

import faiss
import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    vector_knowledge as vk,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)

pytestmark = pytest.mark.skipif(vk.faiss is None, reason="faiss 缺失时本套无意义")

_GIB = 1024**3


class _FakeProvider:
    """8 维确定性伪向量；**声明 dimensions=8**（续跑判据④按本轮维数估计比对，
    不声明会退回 1024 保守假设——那是另一格行为，本套不测它）。"""

    dimensions = 8
    active_base_url = "http://127.0.0.1:1"
    signature = "test|s201"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            digest = hashlib.sha1(text.encode("utf-8")).digest()
            out.append([byte / 255.0 for byte in digest[:8]])
        return out


def _make_store(tmp_path: Path) -> SqliteVectorKnowledgeStore:
    return SqliteVectorKnowledgeStore(
        db_path=tmp_path / "kb_wiki_embeddings.sqlite3",
        embed_provider=_FakeProvider(),
        chunk_chars=800,
        top_k=4,
        signature="test|s201",
        auto_reset=True,
        ann_index_path=str(tmp_path / "kb_wiki_faiss.index"),
        ann_order_path=str(tmp_path / "kb_wiki_faiss.order.json"),
    )


def _seed(
    store: SqliteVectorKnowledgeStore, docs: int, *, tag: str = "a", full: bool = True
) -> None:
    """full=True 与兄弟件同形（清单外文档连块删除）；**补嵌必须 full=False**
    （清单外不删，才是"另一路又提交了一批"的形状）。"""
    rows = [
        {
            "id": f"topic/{tag}-doc-{index}",
            "hash": hashlib.sha1(f"{tag}{index}".encode()).hexdigest(),
            "topic": "topic",
            "source": "s201",
            "title": f"{tag}-doc-{index}",
            "chunks": [f"内容{tag}{index}" * 40],
        }
        for index in range(docs)
    ]
    store.sync_documents(iter(rows), removed_ids=(), full=full)
    store.embed_pending(None)


def _tiny_windows(monkeypatch) -> None:
    """批宽 8、复检与检查点同窗 8：24 条语料就能跨过两个落盘窗。"""
    monkeypatch.setattr(vk, "_ANN_BUILD_BATCH_SIZE", 8)
    monkeypatch.setattr(vk, "_ANN_BUILD_MEMORY_RECHECK_VECTORS", 8)


def _memory_sequence(monkeypatch, readings: list[int]) -> None:
    """按调用序投喂可用内存（预飞一读、每复检窗一读）；用完恒 64 GiB。"""
    state = {"n": 0}

    def fake() -> int:
        i = state["n"]
        state["n"] += 1
        return readings[i] if i < len(readings) else 64 * _GIB

    monkeypatch.setattr(vk, "_available_physical_memory_bytes", fake)


def _abort_midway_with_checkpoint(store, monkeypatch, total: int = 24) -> dict:
    """跑到"检查点已落 @8、复检在 @16 收火"的固定形态，返回第一跑结果。

    读序：#1 预飞 64G 放行 → 装 8 条 → #2 窗@8 复检 64G 放行 ⇒ **落检查点
    （wip_vectors=8, last_rowid=8）** → 装到 16 条 → #3 窗@16 复检 1 字节 ⇒
    收火。此刻三件套在盘、线上两文件一字未动。
    """
    _tiny_windows(monkeypatch)
    _memory_sequence(monkeypatch, [64 * _GIB, 64 * _GIB, 1])
    result = store.build_ann_index()
    assert result["built"] is False
    assert result["reason"] == "insufficient_memory_midway"
    assert result["vectors_built_before_abort"] == 16
    assert result["resumed_from"] == 0
    assert result["checkpoint_dropped_reason"] == ""
    return result


def _checkpoint_row(store) -> dict | None:
    raw = store.get_meta(vk._ANN_BUILD_CHECKPOINT_KEY)
    if not raw:
        return None
    return json.loads(raw)


def _db_embedded_count(store) -> int:
    with store._connect() as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM knowledge_chunks "
                "WHERE vector_json IS NOT NULL AND vector_json != ''"
            ).fetchone()[0]
        )


def _live_pair_present(store) -> tuple[bool, bool]:
    index_path, order_path = store._ann_files()
    return Path(index_path).exists(), Path(order_path).exists()


# --- ① 收火后第二跑必须真续上 --------------------------------------------------


def test_midway_abort_then_resume_publishes_full_index(tmp_path, monkeypatch, caplog):
    """①：跑一半强制中断（内存门中途收火）后再跑，必须 resumed_from>0 且
    最终发布件 ntotal == len(order) == 库内已嵌入数。

    拦的回归：检查点落了但没人读（等于没做）；或续跑接错位点/接错列表，
    发布出一副"看着满、实际错位"的索引。
    """
    store = _make_store(tmp_path)
    _seed(store, 24)
    first = _abort_midway_with_checkpoint(store, monkeypatch)
    row = _checkpoint_row(store)
    assert row is not None and row["wip_vectors"] == 8 and row["last_rowid"] == 8
    wip_index, wip_order = store._ann_wip_paths()
    assert wip_index.exists() and wip_order.exists()
    # 中途收火绝不允许动线上件（既有纪律，不因本波松动）
    assert _live_pair_present(store) == (False, False)
    assert first["memory_gate"]["stage"] == "midway"

    _memory_sequence(monkeypatch, [64 * _GIB])
    with caplog.at_level(logging.INFO, logger=vk.logger.name):
        second = store.build_ann_index()
    assert second["built"] is True, second
    assert second["resumed_from"] == 8
    assert second["checkpoint_dropped_reason"] == ""
    assert any("从检查点续跑" in rec.getMessage() for rec in caplog.records), (
        "续跑发生过必须看得见（日志面）"
    )
    index_path, order_path = store._ann_files()
    ntotal = int(faiss.read_index(str(index_path)).ntotal)
    order = json.loads(Path(order_path).read_text(encoding="utf-8"))
    embedded = _db_embedded_count(store)
    assert ntotal == len(order) == embedded == 24
    # 续跑发布出来的这一代必须能通过全部既有门（载入端不认 = 白建）
    store._drop_ann_cache()
    assert store.load_ann_index() is True


# --- ② 间隙里补嵌过 ⇒ 丢弃重跑，且章是"最终首段"的 ----------------------------


def test_generation_change_during_gap_forces_rerun(tmp_path, monkeypatch, caplog):
    """②：第一次中断后、第二次开跑前补嵌一批（代次变了）⇒ 必须丢弃重跑
    （resumed_from==0），最终 publish 的代际证明 embed_generation 等于**最终
    首段**（= 第二次开光标那一刻）的取值。

    拦的回归：续跑光标 rowid>last_rowid 会把"NULL→有值"的新补行永久漏掉；
    以及"续跑段自己盖新章"把代次守卫洗成自证。
    """
    store = _make_store(tmp_path)
    _seed(store, 24)
    _abort_midway_with_checkpoint(store, monkeypatch)
    stale_row = _checkpoint_row(store)
    assert stale_row is not None

    _seed(store, 4, tag="late", full=False)  # 另一路补嵌一批：代次 +1（有戳则同事务上涨）
    g_after_append = store._embed_generation_now()
    assert g_after_append > int(stale_row["embed_generation"])

    _memory_sequence(monkeypatch, [64 * _GIB])
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        second = store.build_ann_index()
    assert second["built"] is True, second
    assert second["resumed_from"] == 0
    assert second["checkpoint_dropped_reason"] == "embed_generation_changed"
    assert any("embed_generation_changed" in rec.getMessage() for rec in caplog.records)
    att = store._read_ann_attestation()
    assert int(att[vk._ATTEST_EMBED_GENERATION_FIELD]) == g_after_append, (
        "重跑段的章必须盖它自己首段开光标那一刻的代次——既不许沿用被丢的旧章，"
        "也不许 publish 现读"
    )
    assert int(att["ntotal"]) == 28


def test_resumed_segment_publishes_first_segment_generation(tmp_path, monkeypatch):
    """②b：补嵌发生在**续跑进行中之际** ⇒ 发布章仍沿用首段（第一次开光标）的
    代次 ⇒ 这一代被载入端拒用（覆盖不含迟到批次），绝不"续跑段现读现盖"。

    拦的回归：把 publish 入参换成 `_embed_generation_now()` 的"自己给自己
    盖章"——那正是 S159 在直跑路径上钉死、续跑这条新腿必须同样钉死的形态。
    构造纪律同 tests/test_kb_pricing_guard_fts_s159.py::
    test_publish_records_build_start_generation：中途那批由**另一实例**提交
    （生产上中途写者本就是另一个进程）。
    """
    store = _make_store(tmp_path)
    _seed(store, 24)
    _abort_midway_with_checkpoint(store, monkeypatch)
    row = _checkpoint_row(store)
    assert row is not None
    first_segment_generation = int(row["embed_generation"])

    rival = SqliteVectorKnowledgeStore(
        db_path=store.db_path,
        embed_provider=_FakeProvider(),
        chunk_chars=store.chunk_chars,
        top_k=store.top_k,
        signature=store.signature,
        auto_reset=True,
        ann_index_path=store.ann_index_path,
        ann_order_path=store.ann_order_path,
    )
    _tiny_windows(monkeypatch)
    _memory_sequence(monkeypatch, [64 * _GIB])
    state = {"fired": False}

    def late_batch_during_resume(built_so_far: int) -> None:
        # 续跑进度到 16（第二窗、检查点已换入）时，另一路提交一批新嵌入。
        if built_so_far >= 16 and not state["fired"]:
            state["fired"] = True
            _seed(rival, 4, tag="late", full=False)

    result = store.build_ann_index(on_progress=late_batch_during_resume)
    assert result["built"] is True, result
    assert result["resumed_from"] == 8
    assert state["fired"] is True, "中途补嵌没发生 = 本锁空转"
    assert store._embed_generation_now() > first_segment_generation
    att = store._read_ann_attestation()
    assert int(att[vk._ATTEST_EMBED_GENERATION_FIELD]) == first_segment_generation, (
        "续跑段现读现盖 = 把没装进索引的迟到批次写进覆盖证明（洗守卫）"
    )
    store._drop_ann_cache()
    assert store.load_ann_index() is False, (
        "带迟到批次的这一代必须被代次闸拒用（下轮重建收编）"
    )


# --- ③ 间隙里删过一批（戳变了）⇒ 丢弃 ------------------------------------------


def test_stamp_change_during_gap_forces_rerun(tmp_path, monkeypatch):
    """③：中断后清掉两行向量并把戳降两格（真实删除轮的可见形态：戳动、代次
    不动）⇒ 丢弃检查点重跑，最终发布件不含死 id。

    拦的回归：半成品 order 里留着死 id 还被续用并发出去——2026-09-26 那枚
    "戳对上就放行"的假绿的检查点变体。代次这条腿②已单独钉过，本锁钉的是
    **戳这条腿独立开火**（两腿若并成一格，将来谁先被摘掉都无人知道）。
    """
    store = _make_store(tmp_path)
    _seed(store, 24)
    # 计数戳只随 publish 落地（"无戳不建戳"是 `_bump_expected_vector_count`
    # 在册语义）——要有"戳被删除拉低"可测，先得有一代真发布过。
    _tiny_windows(monkeypatch)
    _memory_sequence(monkeypatch, [64 * _GIB])
    assert store.build_ann_index()["built"] is True
    assert store._stamped_expected_vector_count() == 24

    _abort_midway_with_checkpoint(store, monkeypatch)
    row = _checkpoint_row(store)
    assert row is not None
    g_before = store._embed_generation_now()
    assert int(row["embed_generation"]) == g_before, "前提：只动戳不碰代次"
    assert int(row["expected_vector_count"]) == 24, "前提：检查点背的是有戳代的戳"
    stamp_before = store._stamped_expected_vector_count()
    assert stamp_before is not None

    with store._connect() as connection:
        # 删掉检查点批次里的一条（order 会含死 id）+ 另一条，共两行向量。
        victim_ids = json.loads(Path(store._ann_wip_paths()[1]).read_text(encoding="utf-8"))
        connection.execute(
            "UPDATE knowledge_chunks SET vector_json = '', vector_blob = NULL "
            "WHERE chunk_id IN (?, ?)",
            (victim_ids[0], victim_ids[7]),
        )
        remaining = int(
            connection.execute(
                "SELECT COUNT(*) FROM knowledge_chunks "
                "WHERE vector_json IS NOT NULL AND vector_json != ''"
            ).fetchone()[0]
        )
    assert remaining == 22, "夹具删除腿没生效，本锁测不到它声称的东西"
    store.set_meta(vk._EMBEDDED_COUNT_KEY, str(int(stamp_before) - 2))
    assert store._embed_generation_now() == g_before

    _memory_sequence(monkeypatch, [64 * _GIB])
    second = store.build_ann_index()
    assert second["built"] is True, second
    assert second["resumed_from"] == 0
    assert second["checkpoint_dropped_reason"] == "expected_vector_count_changed"
    index_path, order_path = store._ann_files()
    order = json.loads(Path(order_path).read_text(encoding="utf-8"))
    assert int(faiss.read_index(str(index_path)).ntotal) == len(order) == 22
    assert victim_ids[0] not in order and victim_ids[7] not in order, (
        "死 id 不得出现在发布件里（这就是丢弃判据存在的理由）"
    )


# --- ④ 半成品被动过（删除/截断）⇒ 丢弃且不崩 -----------------------------------


def test_missing_wip_files_drop_and_rerun(tmp_path, monkeypatch):
    """④a：meta 行在、两枚 `.wip` 文件被人删掉 ⇒ wip_files_missing，重跑不崩。"""
    store = _make_store(tmp_path)
    _seed(store, 24)
    _abort_midway_with_checkpoint(store, monkeypatch)
    wip_index, wip_order = store._ann_wip_paths()
    wip_index.unlink()
    wip_order.unlink()
    _memory_sequence(monkeypatch, [64 * _GIB])
    second = store.build_ann_index()
    assert second["built"] is True, second
    assert second["resumed_from"] == 0
    assert second["checkpoint_dropped_reason"] == "wip_files_missing"
    assert _checkpoint_row(store) is None, "丢弃即清账，不许留幽灵行"


def test_truncated_wip_index_drops_and_rerun(tmp_path, monkeypatch):
    """④b：半成品索引被截断（半写残体）⇒ wip_index_unreadable，重跑不崩、
    绝不拿残体去 publish。"""
    store = _make_store(tmp_path)
    _seed(store, 24)
    _abort_midway_with_checkpoint(store, monkeypatch)
    wip_index, _wip_order = store._ann_wip_paths()
    raw = wip_index.read_bytes()
    wip_index.write_bytes(raw[: max(1, len(raw) // 2)])
    _memory_sequence(monkeypatch, [64 * _GIB])
    second = store.build_ann_index()
    assert second["built"] is True, second
    assert second["resumed_from"] == 0
    assert second["checkpoint_dropped_reason"] == "wip_index_unreadable"
    index_path, order_path = store._ann_files()
    ntotal = int(faiss.read_index(str(index_path)).ntotal)
    order = json.loads(Path(order_path).read_text(encoding="utf-8"))
    assert ntotal == len(order) == _db_embedded_count(store) == 24


# --- ⑤ publish 成功后三件套一个不剩 --------------------------------------------


def test_publish_success_removes_checkpoint_trio(tmp_path, monkeypatch):
    """⑤：干净一轮（批宽 8、同窗 8 ⇒ 中途两落检查点）后，`.wip` 两枚、
    `.part` 残体、meta 行必须全不存在；并且**发布前它们确实在场**——
    否则本锁就空转成"检查了个寂寞"。"""
    store = _make_store(tmp_path)
    _seed(store, 24)
    _tiny_windows(monkeypatch)
    _memory_sequence(monkeypatch, [64 * _GIB])
    observed: list[tuple[int, bool, bool]] = []

    def probe(built_so_far: int) -> None:
        # progress(16) 发生在第二窗复检放行之后 ⇒ 此刻三件套必须齐、且
        # wip 索引实装 8 条（第一窗那份）。
        if built_so_far == 16:
            wip_index, wip_order = store._ann_wip_paths()
            row = _checkpoint_row(store)
            ok = (
                row is not None
                and int(row["wip_vectors"]) == 8
                and wip_index.exists()
                and wip_order.exists()
                and int(faiss.read_index(str(wip_index)).ntotal) == 8
            )
            observed.append((built_so_far, ok, True))

    result = store.build_ann_index(on_progress=probe)
    assert result["built"] is True, result
    assert result["resumed_from"] == 0
    assert observed == [(16, True, True)], "发布前检查点从未在场 = 本锁失去对象"
    assert _checkpoint_row(store) is None
    wip_index, wip_order = store._ann_wip_paths()
    assert not wip_index.exists() and not wip_order.exists()
    for pattern in (".wip-*", "*.part"):
        assert list(wip_index.parent.glob(pattern)) == [], f"残留未清：{pattern}"
    # 线上目录里只剩该有的：两枚成品 + 建锁件（锁文件允许存在）
    assert _live_pair_present(store) == (True, True)


# --- ⑥ 结构锁：命名与前缀、publish 序列不碰 `.wip` ------------------------------


def test_wip_names_never_share_prefix_with_live_files(tmp_path):
    """⑥-1：`.wip-` 前缀命名与线上两枚**零共前缀**、同目录、不同名。

    拦的回归：半成品与成品共前缀（如 `kb_wiki_faiss.index.wip`）——按
    `线上名*` 展开的运维 glob 会把它当成品家属误伤/误认。
    """
    store = _make_store(tmp_path)
    index_live, order_live = store._ann_files()
    wip_index, wip_order = store._ann_wip_paths()
    for live, wip in (
        (Path(index_live), wip_index),
        (Path(order_live), wip_order),
    ):
        assert wip.name.startswith(vk._ANN_WIP_PREFIX)
        assert wip.name != live.name
        assert not wip.name.startswith(live.name), "半成品不得以线上名开头"
        assert not live.name.startswith(wip.name), "线上名不得以半成品名开头"
        assert wip.parent == live.parent, "半成品必须贴在自己线上件的同目录"
    assert wip_index != Path(index_live) and wip_order != Path(order_live)
    # publish 的源码里一个字都不许出现 wip（半成品绝不可能被当成品发布）
    publish_source = inspect.getsource(SqliteVectorKnowledgeStore._publish_ann_pair)
    assert "wip" not in publish_source, "_publish_ann_pair 引用了半成品（禁）"


def test_publish_atomic_replace_sequence_never_touches_wip(tmp_path, monkeypatch):
    """⑥-2 行为锁：原子替换按**调用方**归因后——
    ① publish 序列的目标只许是线上两枚，且全程无 `.wip`；
    ② 检查点落盘确实经原子替换（有 `.wip` 目标、且来自 `_save_ann_checkpoint`）；
    ③ 检查点序列的目标绝不许碰到线上两枚（半成品不得直写线上）。

    拦的回归：把半成品 replace 到线上、或把成品 replace 到 `.wip`——两个方向
    都是"半份当成品 / 成品被半份顶掉"。
    """
    store = _make_store(tmp_path)
    _seed(store, 24)
    _tiny_windows(monkeypatch)
    _memory_sequence(monkeypatch, [64 * _GIB])
    live_names = {Path(name).name for name in store._ann_files()}
    calls: list[tuple[str, str]] = []
    real_replace = vk._atomic_replace_from

    def spy(tmp_path_: Path, target: Path) -> None:
        caller = inspect.stack()[1].function
        calls.append((caller, target.name))
        return real_replace(tmp_path_, target)

    monkeypatch.setattr(vk, "_atomic_replace_from", spy)
    result = store.build_ann_index()
    assert result["built"] is True, result
    publish_calls = [name for caller, name in calls if caller == "_publish_ann_pair"]
    checkpoint_calls = [name for caller, name in calls if caller == "_save_ann_checkpoint"]
    assert set(publish_calls) == live_names, (
        f"publish 的替换序列必须恰好换入线上两枚，实得 {publish_calls}"
    )
    assert all(".wip" not in name for caller, name in calls if caller == "_publish_ann_pair")
    assert checkpoint_calls and all(
        name.startswith(vk._ANN_WIP_PREFIX) for name in checkpoint_calls
    ), f"检查点应经原子替换落 .wip，实得 {checkpoint_calls}"
    assert not (set(checkpoint_calls) & live_names), "半成品不得直写线上件"
    others = {caller for caller, _name in calls} - {"_publish_ann_pair", "_save_ann_checkpoint"}
    assert not others, f"原子替换出现未登记调用方：{others}"


def test_build_query_promises_rowid_order(tmp_path):
    """⑥-3 结构锁（"扫描必须可续"的形态面）：建索引那条 SELECT 必须显式
    `rowid > ?` + `ORDER BY rowid`——隐式序不是承诺。

    拦的回归：将来有人"优化"掉 ORDER BY 或把续跑位点从过滤里删了，扫描
    就不再可从 last_rowid 精确续起（检查点③判据当场失去对象）。
    """
    source = Path(vk.__file__).read_text(encoding="utf-8")
    tail = source.split("def _build_ann_index_locked", 1)[1]
    query = tail.split("FROM knowledge_chunks", 1)[1].split('"""', 1)[0]
    assert "rowid > ?" in query, f"续跑位点过滤丢了：{query[:200]!r}"
    assert "ORDER BY rowid" in query, f"扫描顺序承诺丢了：{query[:200]!r}"
    assert "SELECT rowid," in tail.split("connection.execute(", 1)[1], (
        "rowid 必须进选择列表，rows[-1]['rowid'] 才取得到"
    )


def test_store_uses_wal_for_mid_scan_sibling_writes(tmp_path):
    """②b 的承重前提：库在 WAL（续跑扫描进行中另一实例可提交；rollback
    journal 下读事务会把补嵌挤成 SQLITE_BUSY，本套构造即失真）。"""
    store = _make_store(tmp_path)
    with store._connect() as connection:
        mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    assert mode == "wal", f"夹具库不在 WAL（{mode}），②b 的中途补嵌构造不可靠"

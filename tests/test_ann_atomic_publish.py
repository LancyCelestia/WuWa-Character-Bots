"""ANN 索引原子发布 / 跨进程建锁 / 代际可见性回归锁（fix-ann-atomic-write）。

钉死三件事（全部离线 tmp_path，零真实网络、零生产文件读写）：

1. `.faiss.index` 永不就地覆写——写同目录 `.tmp` + fsync + `os.replace`；
   写盘中途被杀时线上只存在「完整旧版」，读者不可能观察到半写文件。
2. `.index` 与 `.order.json` 成对换入——代际证明（SQLite knowledge_meta）
   作提交点，混代（一个新一旧）一律拒绝服务、回落暴力扫描。
3. 跨进程互斥 + 代际可见性——另一进程重建后，运行中的读方无需重启即收敛。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    vector_knowledge as vk,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)

pytestmark = pytest.mark.skipif(vk.faiss is None, reason="faiss 缺失时本套无意义")


class _FakeEmbedder:
    """sha1 伪向量：8 维、确定性、零网络（沿用 tests/test_perf_p1.py 口径）。"""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.sha1(text.encode("utf-8")).digest()
            vectors.append([byte / 255.0 for byte in digest[:8]])
        return vectors


def _seed(store: SqliteVectorKnowledgeStore, count: int, *, tag: str = "a") -> None:
    docs = [
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
    store.sync_documents(iter(docs), removed_ids=[], full=True)
    store.embed_pending(None)


def _make_store(tmp_path: Path, count: int = 20) -> SqliteVectorKnowledgeStore:
    store = SqliteVectorKnowledgeStore(
        db_path=tmp_path / "kb.sqlite3",
        embed_provider=_FakeEmbedder(),
        chunk_chars=800,
        top_k=4,
        signature="test|fake",
        auto_reset=True,
    )
    _seed(store, count)
    return store


def _sibling_store(store: SqliteVectorKnowledgeStore) -> SqliteVectorKnowledgeStore:
    """同 db + 同 ANN 路径的第二个实例：离线模拟"另一个进程"。"""
    return SqliteVectorKnowledgeStore(
        db_path=store.db_path,
        embed_provider=_FakeEmbedder(),
        chunk_chars=store.chunk_chars,
        top_k=store.top_k,
        signature=store.signature,
        auto_reset=True,
        ann_index_path=store.ann_index_path,
        ann_order_path=store.ann_order_path,
    )


def _live_pair(store: SqliteVectorKnowledgeStore) -> tuple[bytes, bytes]:
    return (
        Path(store.ann_index_path).read_bytes(),
        Path(store.ann_order_path).read_bytes(),
    )


# --- ①半写文件不可见 ----------------------------------------------------------


def test_faiss_write_never_targets_the_live_index_path(tmp_path, monkeypatch):
    """核心缺陷：旧实现把 `faiss.write_index(index, index_path)` 直接盖线上。

    断言写盘那一刻 faiss 拿到的目标路径必须是 `.tmp`，且线上文件字节不变。
    """
    store = _make_store(tmp_path)
    assert store.build_ann_index()["built"] is True
    index_path = Path(store.ann_index_path)
    order_path = Path(store.ann_order_path)
    before = (index_path.read_bytes(), order_path.read_bytes())

    real_write_index = vk.faiss.write_index
    observed: list[tuple[str, bool]] = []

    def spy(index, where, *args, **kwargs):
        where_str = str(where)
        # 线上文件此刻仍是完整旧版（旧实现在这里已经把它截断成半写了）
        observed.append(
            (where_str, index_path.read_bytes() == before[0] and order_path.read_bytes() == before[1])
        )
        return real_write_index(index, where, *args, **kwargs)

    monkeypatch.setattr(vk.faiss, "write_index", spy)
    _seed(store, 40, tag="b")
    result = store.build_ann_index()

    assert result["built"] is True
    assert observed, "构建期必须发生一次 faiss 落盘"
    assert all(untouched for _where, untouched in observed)
    for where, _untouched in observed:
        assert where != str(index_path), "禁止就地覆写线上索引"
        assert where.endswith(".tmp")
    # 换代确实发生：新一代比旧代大（40 条 vs 20 条）
    assert index_path.read_bytes() != before[0]
    assert len(json.loads(order_path.read_text(encoding="utf-8"))) == 40


def test_crash_before_publish_leaves_only_complete_previous_generation(
    tmp_path, monkeypatch
):
    """模拟"写完 tmp、还没换入就被杀"：线上仍是完整旧代，读者照常服务。"""
    store = _make_store(tmp_path)
    assert store.build_ann_index()["built"] is True
    assert store.load_ann_index() is True
    before = _live_pair(store)

    real_atomic = vk._atomic_replace_from

    def boom(tmp_path_: Path, target: Path):
        raise OSError(28, "simulated ENOSPC mid-publish")

    monkeypatch.setattr(vk, "_atomic_replace_from", boom)
    _seed(store, 40, tag="b")
    with pytest.raises(RuntimeError, match="ANN 原子换入失败"):
        store.build_ann_index()

    assert _live_pair(store) == before, "换入失败必须一位字节都不动线上文件"
    assert list(Path(store.ann_index_path).parent.glob("*.tmp")) == []
    store._drop_ann_cache()
    # 2026-09-22 完整性闸（#47）改了本例后半的**期望**，不改本例的**判据**：
    # 上面 `_seed(store, 40)` 已把语料推到 60 条向量，而盘上仍是 20 条那一代，
    # 所以"旧代字节完整"与"旧代可用于检索"自此是两件事——前者仍由上面的
    # `_live_pair == before` 守着，后者必须被拒（放行＝新嵌的 40 条在向量通道隐形，
    # 正是本闸要拦的形态）。拒的方向是安全的：回落暴力＝慢而全，不是少结果。
    assert store.load_ann_index() is False, "短装的旧代必须被完整性闸拒用"
    assert store._ann_index is None, "拒用不得把短装索引缓存住"
    monkeypatch.setattr(vk, "_atomic_replace_from", real_atomic)
    # 真重建一次即自愈：落戳＝ntotal，同一对文件随即被判可用。
    assert store.build_ann_index()["built"] is True
    store._drop_ann_cache()
    assert store.load_ann_index() is True, "重建后应重新认证通过"


# --- ②成对换入 ---------------------------------------------------------------


def test_mixed_generation_pair_is_never_served(tmp_path, monkeypatch):
    """`.index` 换入成功、`.order.json` 换入失败 → 混代必须被读方拒绝。"""
    store = _make_store(tmp_path)
    assert store.build_ann_index()["built"] is True
    store._drop_ann_cache()
    assert store.load_ann_index() is True
    assert len(store._ann_order or []) == 20

    calls: list[str] = []
    real_atomic = vk._atomic_replace_from

    def flaky(tmp_path_: Path, target: Path):
        calls.append(target.name)
        if len(calls) >= 2:  # 第二个文件（order.json）换入时炸掉
            raise OSError(5, "simulated mid-pair failure")
        return real_atomic(tmp_path_, target)

    monkeypatch.setattr(vk, "_atomic_replace_from", flaky)
    _seed(store, 40, tag="b")
    with pytest.raises(RuntimeError, match="ANN 原子换入失败"):
        store.build_ann_index()

    index_path = Path(store.ann_index_path)
    order_path = Path(store.ann_order_path)
    new_index_count = vk.faiss.read_index(str(index_path)).ntotal
    old_order_count = len(json.loads(order_path.read_text(encoding="utf-8")))
    assert new_index_count != old_order_count, "用例未造出真正的混代"

    store._drop_ann_cache()
    assert store.load_ann_index() is False, "混代绝不载入（宁可慢，不可错答）"
    assert store._ann_candidates([0.1] * 8, 4) is None


def test_pair_attestation_tamper_is_refused(tmp_path):
    """只改序列表（代际证明不匹配）→ 拒绝；这是"一新一旧"的另一半形态。"""
    store = _make_store(tmp_path)
    assert store.build_ann_index()["built"] is True
    order_path = Path(store.ann_order_path)
    order = json.loads(order_path.read_text(encoding="utf-8"))
    order_path.write_text(json.dumps(order[:-1]), encoding="utf-8")  # 少一条
    store._drop_ann_cache()
    assert store.load_ann_index() is False


def test_successful_build_publishes_consistent_pair(tmp_path):
    store = _make_store(tmp_path, count=30)
    result = store.build_ann_index()
    assert result["built"] is True and result["vectors"] == 30
    assert result["ann_attested"] is True
    index_path, order_path = store._ann_files()
    assert vk.faiss.read_index(str(index_path)).ntotal == len(
        json.loads(Path(order_path).read_text(encoding="utf-8"))
    )
    assert store.load_ann_index() is True
    assert store._ann_candidates([0.2] * 8, 3) is not None


def test_legacy_artifacts_without_attestation_still_load(tmp_path):
    """向后兼容：真存量库两行俱无（本功能上线前建的），必须照常可用。

    「两行俱无」是这个用例唯一成立的前提：`ann_embed_generation` 与代际证明
    同批引入，上线前的库两枚都不存在 ⇒ 代次按 0 读 ⇒ 逐字节现状。只删证明、
    留着代次行那不是存量库，是被删过一行 meta —— 另一枚用例
    ::test_attestation_deleted_under_live_generation_is_refused 钉那一格。
    """
    store = _make_store(tmp_path)
    assert store.build_ann_index()["built"] is True
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM knowledge_meta WHERE key = ?", (vk._ANN_ATTESTATION_KEY,))
        conn.execute("DELETE FROM knowledge_meta WHERE key = ?", (vk._EMBED_GENERATION_KEY,))
        conn.commit()
    store._drop_ann_cache()
    assert store.load_ann_index() is True


def test_attestation_deleted_under_live_generation_is_refused(tmp_path, caplog):
    """绕行口封堵：只删代际证明、代次行还在 ⇒ 必须拒用，不许"没证明=没代次"。

    这一格原来是开着的（S163 实测：删掉 `ann_pair_attestation` 那行 meta，
    今晚的假绿态 load 由 False 翻回 True；伪造一条 `embed_generation=10^9`
    同样放行）。计数闸与代次闸当时同源于那一行证明，删一行就把两道门一起
    关掉。修法＝证明缺席且代次 > 0 按最严一档判。
    """
    store = _make_store(tmp_path)
    assert store.build_ann_index()["built"] is True
    assert store.load_ann_index() is True
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM knowledge_meta WHERE key = ?", (vk._ANN_ATTESTATION_KEY,))
        conn.commit()
    assert store._embed_generation_now() > 0, "前提：代次行仍在且非零"
    store._drop_ann_cache()
    with caplog.at_level(logging.WARNING, logger=vk.logger.name):
        assert store.load_ann_index() is False, (
            "删一行 meta 就关掉两道闸 = 守卫可自豁免（本用例要拦的就是它）"
        )
    refused = [
        rec.getMessage()
        for rec in caplog.records
        if "coverage refused" in rec.getMessage()
    ]
    assert refused and "attested_generation=absent" in refused[0], "拒因必须可归因"
    # 自愈链：重建会重新盖章发布，代次与证明同时回到一致 ⇒ 恢复放行。
    assert store.build_ann_index()["built"] is True
    store._drop_ann_cache()
    assert store.load_ann_index() is True


# --- ③跨进程锁 ---------------------------------------------------------------


def test_second_writer_is_locked_out_and_files_untouched(tmp_path):
    """另一进程持锁期间：本进程让路，且绝不碰线上文件（补嵌 vs smoke 撞车场景）。"""
    store = _make_store(tmp_path)
    assert store.build_ann_index()["built"] is True
    before = _live_pair(store)

    rival = vk._AnnBuildGate(store._ann_lock_path())
    assert rival.acquire() is True
    try:
        other = _sibling_store(store)
        _seed(other, 40, tag="b")
        result = other.build_ann_index()
        assert result["built"] is False
        assert result["reason"] == "locked_by_other_process"
        assert _live_pair(store) == before, "抢不到锁就不许动文件"
    finally:
        rival.release()

    reloaded = _sibling_store(store)
    assert reloaded.build_ann_index()["built"] is True, "锁释放后即可正常重建"


def test_publish_refuses_to_write_without_the_lock(tmp_path):
    """持锁期外覆写 = 直接拒绝（堵住未来任何绕过 build_ann_index 的旁路写口）。"""
    store = _make_store(tmp_path)
    index = vk.faiss.IndexHNSWFlat(8, 32, vk.faiss.METRIC_INNER_PRODUCT)
    with pytest.raises(RuntimeError, match="拒绝在无跨进程建锁的情况下覆写"):
        store._publish_ann_pair(index, ["chunk-1"])
    assert not Path(store.ann_index_path).exists()
    assert not Path(store.ann_order_path).exists()


_CHILD_LOCK_SCRIPT = """
import msvcrt, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o666)
msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
sys.stdout.write("LOCKED\\n")
sys.stdout.flush()
time.sleep(float(sys.argv[2]))
"""


@pytest.mark.skipif(sys.platform != "win32", reason="子进程脚本用 msvcrt，仅 win32")
def test_lock_excludes_a_real_second_process(tmp_path):
    """真·两进程语义：子进程持锁期间主进程抢不到，子进程退出后立刻抢得到。"""
    lock_file = tmp_path / "kb.faiss.index.build.lock"
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", _CHILD_LOCK_SCRIPT, str(lock_file), "4"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        assert child.stdout is not None
        first = child.stdout.readline().strip()
        assert first == "LOCKED", f"子进程加锁失败：{first!r} {child.stderr.read() if child.stderr else ''}"
        gate = vk._AnnBuildGate(lock_file)
        assert gate.acquire(timeout_seconds=0.6) is False, "另一进程持锁时必须抢不到"
    finally:
        child.wait(timeout=20)
    late = vk._AnnBuildGate(lock_file)
    assert late.acquire(timeout_seconds=1.0) is True, "持锁进程消失后自动可获取"
    late.release()


# --- ④代际可见性（不重启即收敛） --------------------------------------------


def test_running_reader_converges_on_external_rebuild(tmp_path):
    """运行中的读方在外部原子换入新代后，下一次检索即收敛，无需重启 Bot。"""
    bot_store = _make_store(tmp_path, count=20)
    assert bot_store.build_ann_index()["built"] is True
    assert bot_store.load_ann_index() is True
    cached_object = bot_store._ann_index
    assert cached_object is not None
    assert len(bot_store._ann_order or []) == 20

    worker = _sibling_store(bot_store)
    _seed(worker, 40, tag="b")
    assert worker.build_ann_index()["built"] is True

    assert bot_store.load_ann_index() is True, "外部换代后读方应重开而非判不可用"
    assert len(bot_store._ann_order or []) == 40, "必须收敛到新一代"
    assert bot_store._ann_index is not cached_object
    assert bot_store._ann_candidates([0.1] * 8, 4) is not None


def test_reader_falls_back_when_generation_vanishes(tmp_path):
    """外部把 ANN 文件撤走（重建中的移出阶段）：立刻判不可用，回落暴力。"""
    store = _make_store(tmp_path)
    assert store.build_ann_index()["built"] is True
    assert store.load_ann_index() is True
    Path(store.ann_index_path).unlink()
    assert store.load_ann_index() is False
    assert store._ann_candidates([0.1] * 8, 4) is None


def test_build_ann_index_returns_without_self_deadlock(tmp_path):
    """锁序守卫：`_maintenance_lock` 是非重入 Lock，wrapper 与重建主体
    只能有一处取它。取重了就是每次重建自锁死——用线程 + 超时把它钉成
    失败而不是挂住整个套件。"""
    store = _make_store(tmp_path)
    outcome: dict[str, object] = {}

    def run() -> None:
        outcome["result"] = store.build_ann_index()

    worker = threading.Thread(target=run, daemon=True)
    started = time.monotonic()
    worker.start()
    worker.join(timeout=60)
    assert not worker.is_alive(), "build_ann_index 自锁死：未在 60s 内返回"
    assert outcome["result"]["built"] is True
    assert time.monotonic() - started < 60


def test_in_process_second_build_waits_not_locked_out(tmp_path):
    """进程内仍按旧语义排队（维护锁在外、建锁闸在内）：同进程并发重建不该
    被跨进程闸误判成"别人在建"而跳过。"""
    store = _make_store(tmp_path)
    assert store.build_ann_index()["built"] is True
    order_path = Path(store.ann_order_path)
    before = order_path.read_bytes()

    store._maintenance_lock.acquire()
    attempt: dict[str, object] = {}

    def run() -> None:
        attempt["result"] = store.build_ann_index()

    waiter = threading.Thread(target=run, daemon=True)
    waiter.start()
    time.sleep(0.5)
    assert waiter.is_alive(), "维护锁被占用时第二次重建应排队等待，而非立刻返回"
    store._maintenance_lock.release()
    waiter.join(timeout=60)
    assert not waiter.is_alive()
    assert attempt["result"]["built"] is True
    assert order_path.read_bytes() == before, "行数未变（20 条）→ 序列表应逐字节一致"


def test_hot_path_cost_is_two_stat_calls(tmp_path, monkeypatch):
    """代际感知不得把每次检索变成哈希/DB 往返：稳态只 stat 两个文件。"""
    store = _make_store(tmp_path)
    assert store.build_ann_index()["built"] is True
    assert store.load_ann_index() is True

    sha_calls: list[int] = []
    real_sha = vk._sha256_file

    def counting_sha(path: Path) -> str:
        sha_calls.append(1)
        return real_sha(path)

    monkeypatch.setattr(vk, "_sha256_file", counting_sha)
    for _ in range(5):
        assert store.load_ann_index() is True
    assert sha_calls == [], "缓存命中期不应重算摘要（只比对文件指纹）"

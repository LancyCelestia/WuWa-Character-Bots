"""rebuild_ann_index 运维脚本的离线回归（全 tmp_path，零网络、零真库、零写入真面目）.

四条简报腿 + 端到端：
① dry-run 零写入断言（craft 库与真 store 两种形态各一）；
② 内存门拒绝腿（8.5GiB 入口地板 / 探针不可判定 fail-closed / 需求式预检）；
③ no-op 判定腿（对齐+索引比库新 ⇒ 短路放行；错位/陈旧 ⇒ 越过 no-op 进门）；
④ 签名对读取腿（_read_signature_pair 缺行/缺表）；
⑤ 端到端：真 faiss 重建把 ann_signature 盖回 embedding_signature + .bak 登记；
   空库重建失败自动回滚旧索引对。

真库零接触：所有库都是 tmp_path 手搓或临时小 store；内存探针经
vk._available_physical_memory_bytes 注入（S201 同款缝）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import rebuild_ann_index as rai

_GIB = 1024**3
_SIG_A = "test-sig|aligned-A"
_SIG_OLD = "test-sig|stale-OLD"

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    vector_knowledge as vk,
)

# faiss 只缺在 vk.faiss 上可见；非 faiss 腿（签名/门/幂等）不依赖它照跑
_FAISS_MISSING = vk.faiss is None

needs_faiss = pytest.mark.skipif(_FAISS_MISSING, reason="faiss 缺失时端到端腿无意义")


# ---------------------------------------------------------------------------
# 夹具构造（手搓库，非 faiss 腿零 faiss 依赖）
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE knowledge_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE knowledge_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT,
    title TEXT,
    content TEXT,
    content_hash TEXT,
    vector_json TEXT,
    vector_blob BLOB,
    persona_id TEXT NOT NULL DEFAULT ''
);
"""

_DB_T0 = 1_700_000_000.0  # 任取的固定时刻；索引对在其上/下偏移，构成新鲜/陈旧


def craft_db(
    db_path: Path,
    *,
    embed_sig: str = "",
    ann_sig: str = "",
    dim: int | None = None,
    stamp: int | None = None,
    chunks: int = 3,
    vector_rows: int = 0,
    dim_real: int = 8,
) -> Path:
    """手搓一个最小知识库：签名/戳进 knowledge_meta，前 vector_rows 行带真
    float32 blob + 同形 JSON（blob 供训练取样、json 供扫描过滤，双列齐装）。"""
    import numpy as np

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(_SCHEMA)
        meta: dict[str, str] = {}
        if embed_sig:
            meta[rai.EMBED_SIG_KEY] = embed_sig
        if ann_sig:
            meta[rai.ANN_SIG_KEY] = ann_sig
        if dim is not None:
            meta[rai.VECTOR_DIM_KEY] = str(dim)
        if stamp is not None:
            meta["ann_expected_vector_count"] = str(stamp)
        con.executemany(
            "INSERT INTO knowledge_meta (key, value) VALUES (?, ?)", sorted(meta.items())
        )
        for i in range(chunks):
            vector_json = None
            blob = None
            if i < vector_rows:
                vec = (np.arange(dim_real, dtype=np.float32) + i) / 10.0
                blob = vec.tobytes()
                vector_json = json.dumps([round(float(x), 6) for x in vec])
            con.execute(
                "INSERT INTO knowledge_chunks (chunk_id, content, vector_json, vector_blob) "
                "VALUES (?, ?, ?, ?)",
                (f"doc/c-{i}", f"内容{i}", vector_json, blob),
            )
        con.commit()
    finally:
        con.close()
    os.utime(db_path, (_DB_T0, _DB_T0))
    return db_path


def craft_pair(db_path: Path, *, mtime: float | None = None) -> tuple[Path, Path]:
    """手搓 ANN 对两枚（内容是假字节——非 faiss 腿只关心存在性/mtime/字节守恒）。"""
    index_path, order_path = rai.default_pair_paths(db_path)
    index_path.write_bytes(b"FAKE-INDEX-BYTES")
    order_path.write_bytes(b'["doc/c-0"]')
    stamp = _DB_T0 if mtime is None else mtime
    os.utime(index_path, (stamp, stamp))
    os.utime(order_path, (stamp, stamp))
    return index_path, order_path


def snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    """目录态快照：文件名 → (size, mtime_ns, sha256)。零写入判定的尺。"""
    out: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.iterdir()):
        if path.is_file():
            stat = path.stat()
            out[path.name] = (
                stat.st_size,
                stat.st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
    return out


def assert_only_sidecars_added(before: dict, after: dict, db_name: str) -> None:
    """快照对比：既有文件逐一恒等；新增只许 -shm/-wal（SQLite 只读连接的
    旁车机制，非数据写入；WAL 库旁车缺席时才可能发生）。"""
    for name, fact in before.items():
        assert after.get(name) == fact, f"既有文件被动了：{name}"
    allowed = {f"{db_name}-shm", f"{db_name}-wal"}
    for name in after.keys() - before.keys():
        assert name in allowed, f"冒出了非旁车新文件：{name}"


def read_meta(db_path: Path, key: str) -> str | None:
    con = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        row = con.execute(
            "SELECT value FROM knowledge_meta WHERE key = ?", (key,)
        ).fetchone()
    finally:
        con.close()
    return None if row is None else ("" if row[0] is None else str(row[0]))


# ---------------------------------------------------------------------------
# ④ 签名对读取腿 + 派生尺
# ---------------------------------------------------------------------------


def test_signature_pair_reader_present_missing_and_unopenable(tmp_path):
    db = craft_db(tmp_path / "kb_wiki_embeddings.sqlite3", embed_sig="sig|e", ann_sig="sig|a")
    assert rai._read_signature_pair(db) == ("sig|a", "sig|e"), "取回序必须是 (ann, embedding)"

    empty = tmp_path / "empty.sqlite3"
    empty.write_bytes(b"")
    assert rai._read_signature_pair(empty) is None, "无表 ⇒ None（无从判定），不许猜空串"


def test_default_pair_paths_matches_two_production_construction_points():
    kb = Path(r"C:\rt\data\knowledge_embeddings.sqlite3")
    wiki = Path(r"C:\rt\data\kb_wiki_embeddings.sqlite3")
    assert rai.default_pair_paths(kb) == (
        kb.with_name("knowledge_faiss.index"),
        kb.with_name("knowledge_faiss.order.json"),
    )
    assert rai.default_pair_paths(wiki) == (
        wiki.with_name("kb_wiki_faiss.index"),
        wiki.with_name("kb_wiki_faiss.order.json"),
    )
    other = Path(r"C:\rt\data\whatever.sqlite3")
    assert rai.default_pair_paths(other)[0].name == "knowledge_faiss.index", (
        "非 *_embeddings 库回落 store 通用缺省名"
    )


# ---------------------------------------------------------------------------
# ① dry-run 零写入腿（craft 库形态）
# ---------------------------------------------------------------------------


def test_dry_run_reports_misaligned_pair_and_writes_nothing(tmp_path, capsys):
    db = craft_db(
        tmp_path / "kb_wiki_embeddings.sqlite3",
        embed_sig="sig|embedding-real-value-0123456789abcd",
        ann_sig="sig|ann-drifted",
        dim=8,
        stamp=3,
        chunks=3,
    )
    craft_pair(db)
    before = snapshot(tmp_path)

    rc = rai.main(["--dry-run", "--db", str(db)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "sig|embedding-real-value" in out and "sig|ann-drifted" in out, "两枚签名都要上屏"
    assert "未对齐" in out
    assert "chunk 总数（COUNT(*)）: 3" in out
    assert "空闲物理内存" in out and "重建预估内存" in out
    assert "断点续传检查点: 无（干净态）" in out
    after = snapshot(tmp_path)
    assert_only_sidecars_added(before, after, db.name)
    assert rai._read_signature_pair(db) == ("sig|ann-drifted", "sig|embedding-real-value-0123456789abcd")


# ---------------------------------------------------------------------------
# ③ no-op 判定腿
# ---------------------------------------------------------------------------


def test_noop_when_aligned_and_pair_fresher_even_on_dry_memory(tmp_path, monkeypatch, capsys):
    """对齐 + 索引比库新 ⇒ no-op，且先于内存门短路（探针给 1 字节也不该拒绝）。"""
    db = craft_db(tmp_path / "kb_wiki_embeddings.sqlite3", embed_sig=_SIG_A, ann_sig=_SIG_A)
    craft_pair(db, mtime=_DB_T0 + 3600)
    before = snapshot(tmp_path)
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 1)

    rc = rai.main(["--db", str(db)])

    assert rc == 0
    assert "no-op" in capsys.readouterr().out
    assert snapshot(tmp_path) == before, "no-op 一根手指都不许动"


@pytest.mark.parametrize(
    ("embed_sig", "ann_sig", "pair_mtime", "why"),
    [
        (_SIG_A, _SIG_OLD, _DB_T0 + 3600, "签名错位"),
        (_SIG_A, _SIG_A, _DB_T0 - 3600, "对齐但索引陈旧"),
    ],
    ids=["misaligned", "stale-pair"],
)
def test_not_noop_goes_past_idempotence_into_memory_gate(
    tmp_path, monkeypatch, capsys, embed_sig, ann_sig, pair_mtime, why
):
    """错位 / 陈旧两种形态都必须越过幂等门、撞上内存入口门（给 1 字节 ⇒ 拒绝），
    且全程零写入、零 .bak——证明流程真的走到门而不是停在 no-op。"""
    db = craft_db(tmp_path / "kb_wiki_embeddings.sqlite3", embed_sig=embed_sig, ann_sig=ann_sig)
    craft_pair(db, mtime=pair_mtime)
    before = snapshot(tmp_path)
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 1)

    rc = rai.main(["--db", str(db)])

    assert rc == 3, f"{why} 的形态必须进门后被内存门拒绝"
    captured = capsys.readouterr()
    assert "入口地板" in captured.err
    assert "no-op" not in captured.out
    after = snapshot(tmp_path)
    assert_only_sidecars_added(before, after, db.name)


# ---------------------------------------------------------------------------
# ② 内存门拒绝腿（地板 / 探针不可判定 / 需求式）
# ---------------------------------------------------------------------------


def test_memory_gate_refuses_below_floor_without_touching_anything(tmp_path, monkeypatch, capsys):
    db = craft_db(
        tmp_path / "kb_wiki_embeddings.sqlite3", embed_sig=_SIG_A, ann_sig=_SIG_OLD, stamp=3
    )
    craft_pair(db)
    before = snapshot(tmp_path)
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: rai.MIN_FREE_BYTES - 1)

    rc = rai.main(["--db", str(db)])

    assert rc == 3
    assert "8.50GiB" in capsys.readouterr().err, "拒绝话里要点名门槛读数"
    assert snapshot(tmp_path) == before, "被门拒绝 = 一根手指都不许动"


def test_memory_probe_unavailable_fails_closed(tmp_path, monkeypatch, capsys):
    db = craft_db(tmp_path / "kb_wiki_embeddings.sqlite3", embed_sig=_SIG_A, ann_sig=_SIG_OLD)
    craft_pair(db)
    before = snapshot(tmp_path)
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: None)

    rc = rai.main(["--db", str(db)])

    assert rc == 3
    assert "无法测量" in capsys.readouterr().err, "探针不可判定必须按 fail-closed 拒绝"
    assert snapshot(tmp_path) == before


def test_demand_gate_refuses_when_model_price_exceeds_free(tmp_path, monkeypatch, capsys):
    """空闲过了 8.5GiB 地板、但需求式要价更高 ⇒ 仍拒（双门各自独立开火）。"""
    db = craft_db(
        tmp_path / "kb_wiki_embeddings.sqlite3",
        embed_sig=_SIG_A,
        ann_sig=_SIG_OLD,
        dim=8,
        stamp=10_000_000,  # 1000 万条 × 8 维 ⇒ 需求 ≈9.2GiB > 投喂的 9GiB
    )
    craft_pair(db)
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 9 * _GIB)

    rc = rai.main(["--db", str(db)])

    assert rc == 3
    assert "需求式预估" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# ⑤ 端到端（真 faiss）：重建对齐签名 + .bak 登记 / 失败回滚
# ---------------------------------------------------------------------------


@needs_faiss
def test_rebuild_aligns_signatures_and_bakes_old_pair(tmp_path, monkeypatch, capsys):
    """核心场景（翻车形态）：embed=A / ann=OLD + 假索引对在盘 ⇒ 实跑后
    ann 被发布点盖回 A、旧对带 UTC 时刻改名 .bak、载入端认这代索引。"""
    import faiss

    db = craft_db(
        tmp_path / "kb_wiki_embeddings.sqlite3",
        embed_sig=_SIG_A,
        ann_sig=_SIG_OLD,
        dim=8,
        stamp=30,
        chunks=30,
        vector_rows=30,
    )
    index_path, order_path = craft_pair(db, mtime=_DB_T0 - 3600)
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 64 * _GIB)

    rc = rai.main(["--db", str(db)])

    assert rc == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "对齐判定: 已对齐" in out
    assert "旧签名对" in out and "新签名对" in out
    assert "[备份登记]" in out, "旧索引对必须登记去向"
    # 新签名对：发布点把 ann 盖回 embedding
    assert rai._read_signature_pair(db) == (_SIG_A, _SIG_A)
    assert read_meta(db, "ann_pair_attestation") is not None
    attestation = json.loads(str(read_meta(db, "ann_pair_attestation")))
    assert attestation["signature"] == _SIG_A
    assert attestation["ntotal"] == 30
    # 新对是真 faiss 索引且装满
    assert index_path.is_file() and order_path.is_file()
    assert int(faiss.read_index(str(index_path)).ntotal) == 30
    assert len(json.loads(order_path.read_text(encoding="utf-8"))) == 30
    # 旧对带 .bak 时刻戳保留、字节守恒（两枚各归各位）
    bak_index = [p.name for p in tmp_path.iterdir() if ".index.bak-" in p.name]
    bak_order = [p.name for p in tmp_path.iterdir() if ".order.json.bak-" in p.name]
    assert len(bak_index) == 1 and len(bak_order) == 1, f"旧对两枚都该在 .bak 家属里：{bak_index}/{bak_order}"
    assert (tmp_path / bak_index[0]).read_bytes() == b"FAKE-INDEX-BYTES"
    assert (tmp_path / bak_order[0]).read_bytes() == b'["doc/c-0"]'
    # 检查点三件套完成使命：行与半成品一个不剩
    assert read_meta(db, vk._ANN_BUILD_CHECKPOINT_KEY) is None
    assert not list(tmp_path.glob(".wip-*"))
    # 载入端（运行时语义）认这代索引
    store = vk.SqliteVectorKnowledgeStore(
        db_path=str(db),
        embed_provider=type("P", (), {"dimensions": 8})(),
        signature=_SIG_A,
        auto_reset=False,
        ann_index_path=str(index_path),
        ann_order_path=str(order_path),
    )
    assert store.load_ann_index() is True


@needs_faiss
def test_failed_build_rolls_back_bak_to_live_pair(tmp_path, monkeypatch, capsys):
    """空库（无可嵌行）重建必然 reason=empty ⇒ 未发布必须自动回滚：
    旧对原字节回到线上名、.bak 一个不留、签名面一字未动、退出码 4。"""
    db = craft_db(
        tmp_path / "kb_wiki_embeddings.sqlite3",
        embed_sig=_SIG_A,
        ann_sig=_SIG_OLD,
        dim=8,
        chunks=0,
    )
    index_path, order_path = craft_pair(db)
    before_pair = (index_path.read_bytes(), order_path.read_bytes())
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 64 * _GIB)

    rc = rai.main(["--db", str(db)])

    assert rc == 4
    err = capsys.readouterr().err
    assert "reason=empty" in err and "已回滚" in err
    assert index_path.read_bytes() == before_pair[0]
    assert order_path.read_bytes() == before_pair[1]
    assert not list(tmp_path.glob("*.bak-*")), "回滚后 .bak 不许残留"
    assert rai._read_signature_pair(db) == (_SIG_OLD, _SIG_A), "失败重建不许动签名面"


# ---------------------------------------------------------------------------
# ① dry-run 零写入腿（真 store 形态：检查点/代际证明/内存门留痕全在场的富态）
# ---------------------------------------------------------------------------


class _FakeProvider:
    """8 维确定性伪向量（S201 同款）；仅 seeding 用，dry-run 不经它。"""

    dimensions = 8

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            digest = hashlib.sha1(text.encode("utf-8")).digest()
            out.append([byte / 255.0 for byte in digest[:8]])
        return out


@needs_faiss
def test_dry_run_on_seeded_store_reports_full_state_and_writes_nothing(
    tmp_path, monkeypatch, capsys
):
    """真 store 先发布一代、再制造中断检查点，dry-run 必须看见全部富态
    （对齐判定 / 代际证明 / 检查点行 / 半成品在场），且目录零数据写入。"""
    db_path = tmp_path / "kb_wiki_embeddings.sqlite3"
    index_path = tmp_path / "kb_wiki_faiss.index"
    order_path = tmp_path / "kb_wiki_faiss.order.json"
    store = vk.SqliteVectorKnowledgeStore(
        db_path=str(db_path),
        embed_provider=_FakeProvider(),
        chunk_chars=800,
        top_k=4,
        signature=_SIG_A,
        auto_reset=True,
        ann_index_path=str(index_path),
        ann_order_path=str(order_path),
    )
    rows = [
        {
            "id": f"topic/doc-{i}",
            "hash": hashlib.sha1(f"d{i}".encode()).hexdigest(),
            "topic": "topic",
            "source": "rai",
            "title": f"doc-{i}",
            "chunks": [f"内容{i}" * 40],
        }
        for i in range(40)
    ]
    monkeypatch.setattr(vk, "_ANN_BUILD_BATCH_SIZE", 8)
    monkeypatch.setattr(vk, "_ANN_BUILD_MEMORY_RECHECK_VECTORS", 8)
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 64 * _GIB)
    store.sync_documents(iter(rows), removed_ids=(), full=True)
    store.embed_pending(None)
    assert store.build_ann_index()["built"] is True, "前提：先有一代干净发布"
    # 制造中断检查点：第二窗复检给 1 字节 ⇒ 收火留三件套
    reads = {"n": 0}

    def _abort_sequence() -> int:
        reads["n"] += 1
        return 1 if reads["n"] == 3 else 64 * _GIB

    monkeypatch.setattr(vk, "_available_physical_memory_bytes", _abort_sequence)
    aborted = store.build_ann_index()
    assert aborted["reason"] == "insufficient_memory_midway" and aborted["resumed_from"] == 0
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 64 * _GIB)
    assert read_meta(db_path, vk._ANN_BUILD_CHECKPOINT_KEY) is not None, "前提：检查点行在盘"

    before = snapshot(tmp_path)
    rc = rai.main(["--dry-run", "--db", str(db_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "已对齐" in out, "干净发布过的一代必须报对齐"
    assert "断点续传检查点: 已装" in out
    assert "半成品: 在场" in out
    assert "代际证明: ntotal=" in out
    after = snapshot(tmp_path)
    assert_only_sidecars_added(before, after, db_path.name)


# ---------------------------------------------------------------------------
# --help 中文说明齐全
# ---------------------------------------------------------------------------


def test_help_is_chinese_and_complete(capsys):
    with pytest.raises(SystemExit) as excinfo:
        rai.main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for needle in ("只读体检", "强制重建", "退出码", "断点续跑", "--db"):
        assert needle in out, f"--help 缺中文说明：{needle}"

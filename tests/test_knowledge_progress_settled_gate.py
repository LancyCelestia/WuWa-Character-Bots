"""`scripts/knowledge_progress.py` 的收工判据离线锁（零网络、零生产库）。

立锁缘由（2026-09-22 本波自己踩的）：kb-sync 摘要里的 `embed_pending` 是**本轮投料数（分母）**，
不是"还剩多少没嵌"。把它读成剩余量，就会写出一条永不成立的判据 `embed_pending == 0`，
而一次完全成功的同步（实跑值 `chunks=embedded=embed_pending=24060`）会被判成"没收工"。
同型错误还有第二条：块表 100% 带向量也不等于收工（投料阶段就把行落库了）。
本锁用一正两负三例把这两条钉死。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import knowledge_progress as kp

SUMMARY_COMPLETE = {
    "started_at": "2026-09-21T22:39:50Z",
    "finished_at": "2026-09-21T23:10:27Z",
    "ok": True,
    "error_kind": "none",
    "added": 7662,
    "changed": 0,
    "removed": 0,
    "chunks": 24060,
    "embedded": 24060,
    "embed_pending": 24060,
    "documents_after": 12,
    "chunks_after": 40,
    "embedded_after": 40,
    "ann_rebuilt": True,
    "reconcile_status": "ok",
}


def _make_store(root: Path, *, embedded_rows: int, summary: dict, ann_expected: int) -> None:
    """造一枚最小 wiki 库：40 条块行、12 篇台账、一枚收工摘要。"""
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(data / "kb_wiki_embeddings.sqlite3")
    with con:
        con.execute("CREATE TABLE knowledge_docs (doc_id TEXT PRIMARY KEY)")
        con.execute(
            "CREATE TABLE knowledge_chunks (chunk_id TEXT PRIMARY KEY, vector_json TEXT)"
        )
        con.execute("CREATE TABLE knowledge_meta (key TEXT PRIMARY KEY, value TEXT)")
        con.executemany(
            "INSERT INTO knowledge_docs VALUES (?)", [(f"d{i}",) for i in range(12)]
        )
        con.executemany(
            "INSERT INTO knowledge_chunks VALUES (?, ?)",
            [(f"c{i}", "[0.1]" if i < embedded_rows else "") for i in range(40)],
        )
        con.execute(
            "INSERT INTO knowledge_meta VALUES ('kb_sync_last_summary', ?)",
            (json.dumps(summary, ensure_ascii=False),),
        )
        con.execute(
            "INSERT INTO knowledge_meta VALUES ('ann_expected_vector_count', ?)",
            (str(ann_expected),),
        )
    con.close()
    # memory 库也要有一枚，否则脚本会打「打不开」而不是进度
    (data / "knowledge_embeddings.sqlite3").touch()


def _run(monkeypatch, root: Path, capsys, argv: tuple[str, ...] = ()) -> str:
    monkeypatch.setattr(kp, "runtime_path", lambda rel: root / rel)
    kp.main(list(argv))
    return capsys.readouterr().out


def test_finished_round_is_settled_even_though_embed_pending_is_nonzero(monkeypatch, tmp_path, capsys):
    """实跑真值复刻：embed_pending=本轮投料数，done>=pending 即清空。"""
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40)
    out = _run(monkeypatch, tmp_path, capsys)
    assert "这一轮已投完收工" in out
    assert "[!!]" not in out


def test_row_counts_alone_are_not_a_settlement_criterion(monkeypatch, tmp_path, capsys):
    """块行 100% 带向量、但本轮只嵌了分母的一半 ⇒ 必须判未收工。"""
    half = dict(SUMMARY_COMPLETE, embedded=12000, embed_pending=24060)
    _make_store(tmp_path, embedded_rows=40, summary=half, ann_expected=40)
    out = _run(monkeypatch, tmp_path, capsys)
    assert "未收工" in out
    assert "[!!] 本轮队列清空" in out


def test_ann_count_drift_blocks_settlement(monkeypatch, tmp_path, capsys):
    """摘要自称投完，但 ANN 应嵌数与库内已嵌数两本账不同源 ⇒ 不算收工。"""
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=16)
    out = _run(monkeypatch, tmp_path, capsys)
    assert "未收工" in out
    assert "[!!] ANN 应嵌数" in out


def test_missing_summary_is_reported_honestly(monkeypatch, tmp_path, capsys):
    """库里有条目却从没跑完过同步：不得凭行数说"完成"。"""
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40)
    store = tmp_path / "data" / "kb_wiki_embeddings.sqlite3"
    con = sqlite3.connect(store)
    with con:
        con.execute("DELETE FROM knowledge_meta WHERE key = 'kb_sync_last_summary'")
    con.close()
    out = _run(monkeypatch, tmp_path, capsys)
    assert "还没有 kb-sync 收工摘要" in out
    assert "已投完收工" not in out


def test_stale_round_before_baseline_never_counts_as_tonight_settled(monkeypatch, tmp_path, capsys):
    """**上一轮**完全收工，但今晚这档还没开跑 ⇒ 不许打「已投完收工」。

    值守脚本就栽过这一格：它第一轮就 grep 到"收工"自行退出，而那时生产侧
    连新摘要都还没写。判据必须带基线（`--since`），否则报的是历史不是今夜。
    """
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40)
    out = _run(monkeypatch, tmp_path, capsys, ("--since", "2026-09-22T00:00:00Z"))
    assert "本轮未开始" in out
    assert "已投完收工" not in out, "拿上一轮的收工冒充今晚＝假绿"


def test_baseline_older_than_the_round_still_reports_settled(monkeypatch, tmp_path, capsys):
    """基线早于本轮 started_at 时，判据照常成立（守卫不许把正常路径也堵死）。"""
    _make_store(tmp_path, embedded_rows=40, summary=SUMMARY_COMPLETE, ann_expected=40)
    out = _run(monkeypatch, tmp_path, capsys, ("--since", "2026-09-01T00:00:00Z"))
    assert "这一轮已投完收工" in out

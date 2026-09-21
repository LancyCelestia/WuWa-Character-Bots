"""kb-sync 元数据闸「有界窗口计数」判据回归（2026-09-20 判据形态修复席）。

旧形态：``corpus_has_time_fields`` 只看 documents.jsonl **首行**有没有
``crawled_at``，用一条样本给整个语料（75,737 行）背书——行序一变（某个无
时间字段的源排到最前），全库回填被一票否决，且记出的 ``skipped_*`` 状态看
起来像"语料本来就没这字段"，没人会去查。

修复形态：读前 N 行（缺省 300，流式、绝不吞全文件）统计带字段行数，按
「≥1 行且 ≥ 窗口 10%」的统计阈值决定刷不刷，并把 ``metadata_probed`` /
``metadata_with_time`` 实测数透出到结果与落库摘要，判据依据可见。

本文件锁三件事：
1. 首行无字段但窗口内大量带字段 → 修复后正常刷新（旧判据在此红）；
2. 前 N 行全不带字段 → 仍诚实判 skipped，不硬刷一库 NULL（含窗口外有字段、
   杂散带字段的"噪声"两种变体）；
3. probed/with_time 进了同步结果与 ``knowledge_meta`` 摘要，可断言可观测。

全离线：语料目录 tmp_path 现造，store 用假嵌入器，零网络、不碰生产库。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki
from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
    SqliteVectorKnowledgeStore,
    probe_corpus_time_fields,
)

_TOPIC = "梗知识"
_WINDOW = kb_wiki._METADATA_PROBE_WINDOW_LINES


class _FakeEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[0.1] * 8 for _ in texts]


def _store(tmp_path: Path, name: str) -> SqliteVectorKnowledgeStore:
    return SqliteVectorKnowledgeStore(
        db_path=tmp_path / f"{name}.sqlite3",
        embed_provider=_FakeEmbedder(),
        chunk_chars=800,
        top_k=4,
        signature="test|fake-embedder",
        auto_reset=True,
    )


def _corpus_row(
    doc_id: str,
    text: str,
    *,
    enriched: bool,
    source: str = "moegirl",
) -> dict:
    row = {
        "op": "upsert",
        "id": doc_id,
        "topic": _TOPIC,
        "source": source,
        "title": doc_id.rsplit("/", 1)[-1],
        "path": f"{_TOPIC}/{source}/{doc_id.rsplit('/', 1)[-1]}.md",
        "url": "",
        "text": text,
        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    if enriched:
        row["updated_at"] = "2026-09-19T00:00:00Z"
        row["crawled_at"] = "2026-09-20T08:00:00Z"
    return row


def _write_documents(tmp_path: Path, rows: list[dict], *, updates: list[dict]) -> None:
    """落 documents.jsonl + manifest.json（updates 可为空 = 本轮无 diff）。"""
    kb_dir = tmp_path / "crawl_output" / "knowledge_base"
    kb_dir.mkdir(parents=True, exist_ok=True)
    with (kb_dir / "documents.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    {k: v for k, v in row.items() if k != "op"}, ensure_ascii=False
                )
                + "\n"
            )
    with (kb_dir / "updates.jsonl").open("w", encoding="utf-8") as handle:
        for row in updates:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "schema_version": "1.1",
        "generated_at": "2026-09-20T00:00:00Z",
        "documents": len(rows),
        "entries": {str(r["id"]): str(r["hash"]) for r in rows},
        "added": [str(r["id"]) for r in updates if r.get("op") == "upsert"],
        "changed": [],
        "removed": [],
    }
    (kb_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_kb_wiki_root=str(tmp_path),
        bot_kb_wiki_topics="",
        bot_kb_wiki_chunk_chars=800,
        bot_kb_wiki_embed_batch=128,
    )


def _seed_ledger_plain(
    tmp_path: Path, name: str, rows: list[dict]
) -> SqliteVectorKnowledgeStore:
    """先把全 plain 语料同步进台账（时间元数据全 NULL），返回 store。"""
    store = _store(tmp_path, name)
    _write_documents(tmp_path, rows, updates=rows)
    first = kb_wiki.run_kb_sync_task(_config(tmp_path), store=store, embed=False)
    assert first["ok"] is True, first["public_message"]
    assert first["metadata_status"] == "skipped_corpus_without_time_fields"
    assert store.documents_missing_metadata() == len(rows)
    return store


def _rows(n: int, *, enriched_from: int = 1 << 30) -> list[dict]:
    """n 条语料行；下标 >= enriched_from 的带时间字段（正文与 hash 不受影响）。"""
    return [
        _corpus_row(
            f"{_TOPIC}/moegirl/Doc{i:04d}",
            f"窗口判据正文 {i}。" * 12,
            enriched=i >= enriched_from,
        )
        for i in range(n)
    ]


# ------------------------------------------------ ① 首行否决 → 窗口计数救回


def test_plain_first_line_no_longer_vetoes_whole_corpus(tmp_path: Path) -> None:
    """首行无时间字段、但第 2..N 行大量带字段：旧判据整库跳过，新判据正常刷新。

    RED 演示：旧实现只看首行——把同一语料的首行判成"语料没这字段"，
    300 篇的回填被 1 行样本一票否决；新实现按窗口计数放行并逐篇回填。
    """
    plain = _rows(_WINDOW)  # 300 条全 plain，先入台账
    store = _seed_ledger_plain(tmp_path, "rescue", plain)

    # 爬虫侧增强重导：首行依旧不带字段（行序陷阱），第 2..300 行都带。
    enriched = _rows(_WINDOW, enriched_from=1)
    _write_documents(tmp_path, enriched, updates=[])  # hash 全不变 → diff 为空
    first_line = (
        tmp_path.joinpath("crawl_output", "knowledge_base", "documents.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert "crawled_at" not in first_line, "样本形态必须复现行序陷阱"

    result = kb_wiki.run_kb_sync_task(_config(tmp_path), store=store, embed=False)
    assert result["metadata_status"] == "ok", (
        "首行一票否决的旧形态必须被窗口计数取代"
    )
    assert result["metadata_probed"] == _WINDOW
    assert result["metadata_with_time"] == _WINDOW - 1
    assert result["metadata_refreshed"] == 2 * (_WINDOW - 1)  # 两列逐篇回填
    assert store.documents_missing_metadata() == 1  # 仅首行那条确实没数据


# ------------------------------------------------ ② 全不带字段 → 诚实跳过


def test_all_plain_window_still_skips_honestly(tmp_path: Path) -> None:
    """前 N 行确实全无时间字段：仍判 skipped，不硬刷一库 NULL（向后兼容）。"""
    plain = _rows(_WINDOW)
    store = _seed_ledger_plain(tmp_path, "honest", plain)
    result = kb_wiki.run_kb_sync_task(_config(tmp_path), store=store, embed=False)
    assert result["metadata_status"] == "skipped_corpus_without_time_fields"
    assert result["metadata_refreshed"] == 0
    assert store.documents_missing_metadata() == _WINDOW  # 一条 NULL 都没被硬刷


def test_enriched_rows_beyond_window_do_not_trigger_scan(tmp_path: Path) -> None:
    """有界窗口的设计边界：字段只出现在第 N+1 行之后 → 本窗判据不动、不刷。

    锁两件事：判据只付前 N 行的顺序读（不吞 GB 级全文件）；probed 恰等于
    窗口大小，读数的人能看到"我只查了前 300 行"。
    """
    rows = _rows(_WINDOW + 50, enriched_from=_WINDOW)
    _write_documents(tmp_path, rows, updates=[])
    probe = probe_corpus_time_fields(tmp_path / "crawl_output" / "knowledge_base")
    assert probe["probed"] == _WINDOW and probe["with_time"] == 0
    assert probe["has_fields"] is False


def test_stray_enriched_line_among_plain_is_noise(tmp_path: Path) -> None:
    """300 行里只 1 行带字段的杂散噪声：撑不过 10% 阈值，不刷。"""
    rows = _rows(_WINDOW)
    rows[7] = {
        **rows[7],
        "updated_at": "2026-09-19T00:00:00Z",
        "crawled_at": "2026-09-20T08:00:00Z",
    }
    _write_documents(tmp_path, rows, updates=[])
    probe = probe_corpus_time_fields(tmp_path / "crawl_output" / "knowledge_base")
    assert probe["probed"] == _WINDOW and probe["with_time"] == 1
    assert probe["has_fields"] is False


# ------------------------------------------------ ③ 判据依据可观测


def test_probe_stats_visible_in_result_and_summary(tmp_path: Path) -> None:
    """probed/with_time 同时进同步结果与 knowledge_meta 摘要（ok/skipped 两路）。"""
    plain = _rows(10)
    store = _store(tmp_path, "observe")
    _write_documents(tmp_path, plain, updates=plain)
    skipped = kb_wiki.run_kb_sync_task(_config(tmp_path), store=store, embed=False)
    assert skipped["metadata_status"] == "skipped_corpus_without_time_fields"
    assert skipped["metadata_probed"] == 10 and skipped["metadata_with_time"] == 0
    summary = kb_wiki.read_kb_sync_summary(store)
    assert summary["metadata_probed"] == 10 and summary["metadata_with_time"] == 0
    assert summary["metadata_status"] == "skipped_corpus_without_time_fields"

    enriched = _rows(10, enriched_from=0)
    _write_documents(tmp_path, enriched, updates=[])
    ok = kb_wiki.run_kb_sync_task(_config(tmp_path), store=store, embed=False)
    assert ok["metadata_status"] == "ok"
    assert ok["metadata_probed"] == 10 and ok["metadata_with_time"] == 10
    summary = kb_wiki.read_kb_sync_summary(store)
    assert summary["metadata_probed"] == 10 and summary["metadata_with_time"] == 10


# ------------------------------------------------ 探针本体细节


def test_probe_ignores_blank_and_broken_lines(tmp_path: Path) -> None:
    """空行与坏 JSON 行不给任何样本背书：不计分子也不计分母。"""
    kb_dir = tmp_path / "crawl_output" / "knowledge_base"
    kb_dir.mkdir(parents=True)
    good = [
        _corpus_row(f"{_TOPIC}/moegirl/G{i}", f"正文{i}。" * 5, enriched=i > 0)
        for i in range(3)
    ]
    with (kb_dir / "documents.jsonl").open("w", encoding="utf-8") as handle:
        handle.write("\n")
        handle.write("{不是合法 json}\n")
        for row in good:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    probe = probe_corpus_time_fields(kb_dir)
    assert probe == {"probed": 3, "with_time": 2, "has_fields": True}


def test_probe_missing_file_is_honest_zero(tmp_path: Path) -> None:
    probe = probe_corpus_time_fields(tmp_path / "nowhere")
    assert probe == {"probed": 0, "with_time": 0, "has_fields": False}


def test_single_enriched_line_corpus_backfills(tmp_path: Path) -> None:
    """微型语料（1 行带字段）：阈值下限 1，照常刷——与旧行为向后一致。"""
    rows = _rows(1, enriched_from=0)
    _write_documents(tmp_path, rows, updates=[])
    probe = probe_corpus_time_fields(tmp_path / "crawl_output" / "knowledge_base")
    assert probe == {"probed": 1, "with_time": 1, "has_fields": True}


def test_corpus_has_time_fields_wrapper_agrees_with_probe(tmp_path: Path) -> None:
    """兼容包装：bool 视图与探针判定同源，不再各自为政。"""
    _write_documents(tmp_path, _rows(_WINDOW, enriched_from=1), updates=[])
    kb_dir = tmp_path / "crawl_output" / "knowledge_base"
    assert kb_wiki.corpus_has_time_fields(kb_dir) is (
        probe_corpus_time_fields(kb_dir)["has_fields"]
    )

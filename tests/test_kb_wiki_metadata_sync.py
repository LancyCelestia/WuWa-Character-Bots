"""kb-sync 时间元数据 / 清单对账 / 同步可观测性回归（2026-09-20 元数据批）。

四件事各自的锁：

1. **台账时间元数据**：``knowledge_docs`` 的 ``source_updated_at``/``crawl_at``
   两列（列名是与 Crawl Wiki 导出层的契约）幂等迁移存量库、由同步写入；
2. **零嵌入成本回填**：``refresh_kb_metadata`` 只 UPDATE 台账两列——chunk 的
   vector_json/vector_blob 字节与 content_hash 一字不变、FTS/ANN 签名不动、
   嵌入调用数为 0（爬虫侧只加时间字段、正文未改时不得触发全量重嵌）；
3. **清单对账兜底**：``updates.jsonl`` 每轮覆盖写、只含本轮 diff，爬虫一天两档
   导出而 Bot 只读一档时前档 diff 永久丢失 —— 改用 ``manifest.entries`` 全量
   id→hash 快照与台账对账补齐缺项、删除多项；清单不完整时挂起删除（宁留不错删）；
4. **可观测性**：每轮 summary 落 ``knowledge_meta`` 单行 JSON（含耗时/成败/
   对账/回填），失败与部分失败走注入的告警 sink（未注入退回 WARNING 日志），
   WebUI 知识页读同一把 key 透出「上次同步时间/成败/新增条数」。

全离线：语料目录用 tmp_path 现造，store 用假嵌入器（确定性向量），零网络。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.control_plane import webui_knowledge
from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki
from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
    SqliteVectorKnowledgeStore,
    refresh_kb_metadata,
    sync_kb_wiki,
)

_TOPIC = "梗知识"


class _CountingEmbedder:
    """确定性假嵌入 + 调用计数：零嵌入路径必须一次都不调。"""

    def __init__(self) -> None:
        self.calls = 0
        self.texts: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.texts.extend(texts)
        vectors = []
        for text in texts:
            digest = hashlib.sha1(text.encode("utf-8")).digest()
            vectors.append([byte / 255.0 for byte in digest[:8]])
        return vectors


def _store(tmp_path: Path, **kwargs) -> SqliteVectorKnowledgeStore:
    defaults: dict = {
        "db_path": tmp_path / "kb_wiki_embeddings.sqlite3",
        "embed_provider": _CountingEmbedder(),
        "chunk_chars": 800,
        "top_k": 4,
        "signature": "test|fake-embedder",
        "auto_reset": True,
    }
    defaults.update(kwargs)
    return SqliteVectorKnowledgeStore(**defaults)


def _corpus_row(
    doc_id: str,
    text: str,
    *,
    title: str = "",
    source: str = "moegirl",
    updated_at: str | None = None,
    crawled_at: str | None = None,
) -> dict:
    """一条导出语料行（既有八字段一字不动 + 可选时间字段）。"""
    row = {
        "op": "upsert",
        "id": doc_id,
        "topic": _TOPIC,
        "source": source,
        "title": title or doc_id.rsplit("/", 1)[-1],
        "path": f"{_TOPIC}/{source}/{doc_id.rsplit('/', 1)[-1]}.md",
        "url": "",
        "text": text,
        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    if updated_at is not None:
        row["updated_at"] = updated_at
    if crawled_at is not None:
        row["crawled_at"] = crawled_at
    return row


def _write_corpus(
    tmp_path: Path,
    *,
    documents: list[dict],
    updates: list[dict],
    removed: list[str] | None = None,
    documents_total: int | None = None,
    topic_stats: dict | None = None,
) -> dict:
    """按 Crawl Wiki 导出协议落盘三件套，返回 manifest。"""
    kb_dir = tmp_path / "crawl_output" / "knowledge_base"
    kb_dir.mkdir(parents=True, exist_ok=True)
    with (kb_dir / "documents.jsonl").open("w", encoding="utf-8") as handle:
        for row in documents:
            # documents.jsonl 是快照、无 op 键（与导出层形状一致）。
            handle.write(
                json.dumps(
                    {key: value for key, value in row.items() if key != "op"},
                    ensure_ascii=False,
                )
                + "\n"
            )
    with (kb_dir / "updates.jsonl").open("w", encoding="utf-8") as handle:
        for row in updates:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "schema_version": "1.1",
        "generated_at": "2026-09-20T00:00:00Z",
        "documents": (
            len(documents) if documents_total is None else documents_total
        ),
        "entries": {str(row["id"]): str(row["hash"]) for row in documents},
        "added": [str(row["id"]) for row in updates if row.get("op") == "upsert"],
        "changed": [],
        "removed": removed or [],
    }
    if topic_stats is not None:
        manifest["topics"] = topic_stats
    (kb_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def _config(tmp_path: Path, **overrides) -> SimpleNamespace:
    config = SimpleNamespace(
        bot_kb_wiki_root=str(tmp_path),
        bot_kb_wiki_topics="",
        bot_kb_wiki_chunk_chars=800,
        bot_kb_wiki_embed_batch=128,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _ledger_rows(store: SqliteVectorKnowledgeStore) -> dict[str, tuple]:
    with store._connect() as connection:
        return {
            str(row["doc_id"]): (row["hash"], row["source_updated_at"], row["crawl_at"])
            for row in connection.execute(
                "SELECT doc_id, hash, source_updated_at, crawl_at FROM knowledge_docs"
            )
        }


def _chunk_fingerprint(store: SqliteVectorKnowledgeStore) -> list[tuple]:
    """全部 chunk 的（id, 正文 hash, vector_json, vector_blob）——零嵌入的硬判据。"""
    with store._connect() as connection:
        return [
            (
                str(row["chunk_id"]),
                str(row["content_hash"]),
                row["vector_json"],
                row["vector_blob"],
            )
            for row in connection.execute(
                "SELECT chunk_id, content_hash, vector_json, vector_blob"
                " FROM knowledge_chunks ORDER BY chunk_id"
            )
        ]


# ---------------------------------------------------------------- 1 列迁移


def test_legacy_ledger_gets_time_columns_idempotently(tmp_path: Path) -> None:
    """存量库（老五列台账）开一次即补两列，再开一次不报错、既有行取值 NULL。"""
    db_path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE knowledge_chunks (
                chunk_id TEXT PRIMARY KEY, source_id TEXT, title TEXT,
                content TEXT, content_hash TEXT, vector_json TEXT,
                vector_blob BLOB
            );
            CREATE TABLE knowledge_meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE knowledge_docs (
                doc_id TEXT PRIMARY KEY, topic TEXT, source TEXT,
                title TEXT, hash TEXT
            );
            INSERT INTO knowledge_docs (doc_id, topic, source, title, hash)
            VALUES ('梗知识/moegirl/老文档', '梗知识', 'moegirl', '老文档', 'h');
            """
        )

    for _ in range(2):  # 幂等：第二次开库不得因重复 ALTER 抛错
        store = _store(tmp_path, db_path=db_path, auto_reset=False)
        columns = {
            str(row[1])
            for row in store._connect().execute("PRAGMA table_info(knowledge_docs)")
        }
        assert {"source_updated_at", "crawl_at"} <= columns
    assert _ledger_rows(store)["梗知识/moegirl/老文档"] == ("h", None, None)
    # 「从未回填」是 NULL，不是空串：空串保留给「上游确无编辑时间」。
    assert store.documents_missing_metadata() == 1


def test_sync_documents_writes_time_columns_and_keeps_unknown_as_null(
    tmp_path: Path,
) -> None:
    """同步带时间字段就落两列；未增强导出（无该键）留 NULL，绝不写空串冒充。"""
    store = _store(tmp_path / "s1.sqlite3")
    docs = [
        {
            "id": "梗知识/moegirl/A",
            "hash": "h-a",
            "topic": _TOPIC,
            "source": "moegirl",
            "title": "A",
            "chunks": ["正文 A"],
            "source_updated_at": "2026-09-19T00:00:00Z",
            "crawl_at": "2026-09-19T01:00:00Z",
        },
        {
            "id": "梗知识/moegirl/B",
            "hash": "h-b",
            "topic": _TOPIC,
            "source": "baidu_baike",
            "title": "B",
            "chunks": ["正文 B"],
            "source_updated_at": "",  # 上游没有可信编辑时间 → 空串（非 NULL）
        },
    ]
    store.sync_documents(docs)
    ledger = _ledger_rows(store)
    assert ledger["梗知识/moegirl/A"] == (
        "h-a",
        "2026-09-19T00:00:00Z",
        "2026-09-19T01:00:00Z",
    )
    assert ledger["梗知识/moegirl/B"] == ("h-b", "", None)


def test_hash_unchanged_replay_refreshes_time_columns_only(tmp_path: Path) -> None:
    """hash 未变的重复同步：块与向量不动、只把时间元数据补齐，并计入统计。"""
    store = _store(tmp_path / "s2.sqlite3")
    doc = {
        "id": "梗知识/moegirl/A",
        "hash": "h-a",
        "topic": _TOPIC,
        "source": "moegirl",
        "title": "A",
        "chunks": ["正文 A"],
    }
    store.sync_documents([doc])
    before = _chunk_fingerprint(store)
    stats = store.sync_documents(
        [{**doc, "source_updated_at": "2026-09-20T00:00:00Z", "crawl_at": "2026-09-20T01:00:00Z"}]
    )
    assert stats["skipped"] == 1 and stats["chunks"] == 0
    assert stats["metadata_refreshed"] == 2
    assert _chunk_fingerprint(store) == before
    assert _ledger_rows(store)["梗知识/moegirl/A"][1:] == (
        "2026-09-20T00:00:00Z",
        "2026-09-20T01:00:00Z",
    )


# ---------------------------------------------------------------- 2 零嵌入回填


def test_refresh_kb_metadata_costs_zero_embeddings(tmp_path: Path) -> None:
    """首晚回填：向量字节/hash 一字不变、FTS/ANN 签名不动、嵌入调用数为 0。"""
    text_a = "谐音梗正文。" * 40
    text_b = "AI梗正文。" * 40
    rows = [
        _corpus_row("梗知识/moegirl/A", text_a),  # 旧导出：没有时间字段
        _corpus_row("梗知识/moegirl/B", text_b, source="baidu_baike"),
    ]
    _write_corpus(tmp_path, documents=rows, updates=rows)
    store = _store(tmp_path / "refresh.sqlite3")
    embedder = _CountingEmbedder()
    store.embed_provider = embedder
    sync_kb_wiki(store, _config(tmp_path))
    assert store.embed_pending(None)[0] == store.stats()["total"]
    assert store.build_ann_index()["built"] is True
    calls_after_embed = embedder.calls
    fingerprint = _chunk_fingerprint(store)
    with store._connect() as connection:
        fts_before = store._stored_fts_signature()
        ann_before = str(
            connection.execute(
                "SELECT value FROM knowledge_meta WHERE key = 'ann_signature'"
            ).fetchone()[0]
        )
    assert store.documents_missing_metadata() == 2

    # 爬虫侧只加时间字段、正文与 hash 一字不动地重导一次。
    enriched = [
        {**row, "updated_at": "2026-09-18T00:00:00Z", "crawled_at": "2026-09-19T16:00:00Z"}
        for row in rows
    ]
    enriched[1]["updated_at"] = ""  # 非 MediaWiki 系源：上游编辑时间诚实为空
    _write_corpus(tmp_path, documents=enriched, updates=enriched[:1])
    stats = refresh_kb_metadata(store, _config(tmp_path))
    assert stats["matched"] == 2 and stats["refreshed"] == 4
    assert stats["missing"] == 0 and stats["stale"] == 0
    assert store.documents_missing_metadata() == 0
    assert embedder.calls == calls_after_embed, "零嵌入成本：一次嵌入都不许调"
    assert _chunk_fingerprint(store) == fingerprint, "chunk 向量与 hash 字节必须不变"
    assert store._stored_fts_signature() == fts_before
    with store._connect() as connection:
        assert (
            str(
                connection.execute(
                    "SELECT value FROM knowledge_meta WHERE key = 'ann_signature'"
                ).fetchone()[0]
            )
            == ann_before
        )
    assert _ledger_rows(store)["梗知识/moegirl/B"][1:] == (
        "",
        "2026-09-19T16:00:00Z",
    )

    # 幂等：再刷一遍零写入。
    again = refresh_kb_metadata(store, _config(tmp_path))
    assert again["refreshed"] == 0 and again["matched"] == 2


def test_refresh_skips_hash_drift_and_unknown_docs(tmp_path: Path) -> None:
    """hash 变了却没走同步：时间值描述的是另一个内容版本，写进去就是假元数据。"""
    text = "会变的正文。" * 30
    _write_corpus(
        tmp_path,
        documents=[_corpus_row("梗知识/moegirl/A", text)],
        updates=[],
    )
    store = _store(tmp_path / "stale.sqlite3")
    store.sync_documents(
        [
            {
                "id": "梗知识/moegirl/A",
                "hash": "old-hash",
                "topic": _TOPIC,
                "source": "moegirl",
                "title": "A",
                "chunks": ["旧正文"],
            }
        ]
    )
    stats = refresh_kb_metadata(store, _config(tmp_path))
    assert stats["stale"] == 1 and stats["refreshed"] == 0
    assert stats["missing"] == 0
    assert _ledger_rows(store)["梗知识/moegirl/A"][1:] == (None, None)
    assert store.documents_missing_metadata() == 1

    # 台账里没有的文档：记 missing，交由同步/对账路径处理，回填不越权插行。
    with (tmp_path / "crawl_output" / "knowledge_base" / "documents.jsonl").open(
        "a", encoding="utf-8"
    ) as handle:
        handle.write(
            json.dumps(_corpus_row("梗知识/moegirl/NEW", "新文档正文。" * 20), ensure_ascii=False)
            + "\n"
        )
    assert refresh_kb_metadata(store, _config(tmp_path))["missing"] == 1


def test_run_kb_sync_task_auto_backfills_once(tmp_path: Path) -> None:
    """run_kb_sync_task 自动回填：语料未增强时只记原因不白扫；带上字段后一次刷完。"""
    store = _store(tmp_path / "auto.sqlite3")
    config = _config(tmp_path)
    plain = [_corpus_row("梗知识/moegirl/A", "自动回填正文。" * 30)]
    _write_corpus(tmp_path, documents=plain, updates=plain)

    first = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert first["ok"] is True, first["public_message"]
    assert first["metadata_gaps"] == 1
    assert first["metadata_status"] == "skipped_corpus_without_time_fields"
    assert first["metadata_refreshed"] == 0

    # 爬虫侧升级后重导（正文一字未改、只多两个时间字段；本轮 diff 为空）。
    enriched = [
        {
            **plain[0],
            "updated_at": "2026-09-19T00:00:00Z",
            "crawled_at": "2026-09-20T08:00:00Z",
        }
    ]
    _write_corpus(tmp_path, documents=enriched, updates=[])
    second = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert second["metadata_status"] == "ok"
    assert second["metadata_refreshed"] == 2 and second["metadata_gaps"] == 1
    assert store.documents_missing_metadata() == 0

    third = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    assert third["metadata_status"] == "not_needed" and third["metadata_gaps"] == 0


# ---------------------------------------------------------------- 3 清单对账


def test_reconcile_recovers_docs_lost_by_overwritten_updates(tmp_path: Path) -> None:
    """前档新增、diff 被后档覆盖：updates.jsonl 里查无此条，仍能通过对账收进来。"""
    early = _corpus_row(
        "梗知识/moegirl/前档新增", "前档文档正文。" * 30, crawled_at="2026-09-20T08:00:00Z"
    )
    late = _corpus_row(
        "梗知识/moegirl/后档新增", "后档文档正文。" * 30, crawled_at="2026-09-20T15:00:00Z"
    )
    # documents.jsonl 是全量快照（两档都在），updates.jsonl 只有后档 diff。
    _write_corpus(tmp_path, documents=[early, late], updates=[late])
    store = _store(tmp_path / "reconcile.sqlite3")

    stats = sync_kb_wiki(store, _config(tmp_path))
    assert stats["added"] == 2, "前档被覆盖的 diff 必须由 manifest 对账补回"
    assert stats["reconcile_missing"] == 2 and stats["reconcile_status"] == "ok"
    assert store.document_count() == 2
    # 补回的行同样带时间元数据（走的是同一条 _to_sync_doc）。
    assert _ledger_rows(store)["梗知识/moegirl/前档新增"][2] == "2026-09-20T08:00:00Z"

    # 幂等：重放零变更（updates 里那条被 skipped，前档那条已入库、对账不再报缺）。
    replay = sync_kb_wiki(store, _config(tmp_path))
    assert replay["added"] == 0 and replay["changed"] == 0 and replay["removed"] == 0
    assert replay["skipped"] == 1 and replay["reconcile_missing"] == 0
    assert store.document_count() == 2


def test_reconcile_detects_hash_drift_and_removes_extras(tmp_path: Path) -> None:
    """台账缺项补、多项删：hash 漂移与上游已删文档都不再依赖 updates.jsonl。"""
    a_old = _corpus_row("梗知识/moegirl/A", "旧版正文。" * 30)
    ghost = _corpus_row("梗知识/moegirl/已删", "上游已删的正文。" * 30)
    store = _store(tmp_path / "reconcile2.sqlite3")
    _write_corpus(tmp_path, documents=[a_old, ghost], updates=[a_old, ghost])
    sync_kb_wiki(store, _config(tmp_path))
    assert store.document_count() == 2

    # 第二轮：A 内容变了却没进 updates（diff 被覆盖）、已删 从清单消失。
    a_new = _corpus_row("梗知识/moegirl/A", "新版正文不一样。" * 30)
    _write_corpus(tmp_path, documents=[a_new], updates=[], removed=["梗知识/moegirl/已删"])
    stats = sync_kb_wiki(store, _config(tmp_path))
    assert stats["changed"] == 1 and stats["reconcile_missing"] == 1
    assert stats["removed"] == 1
    assert store.document_count() == 1
    assert _ledger_rows(store)["梗知识/moegirl/A"][0] == a_new["hash"]


def test_reconcile_never_deletes_from_incomplete_manifest(tmp_path: Path) -> None:
    """documents 与 entries 条数不等（清单自相矛盾）→ 放弃对账，一条都不删。"""
    rows = [
        _corpus_row("梗知识/moegirl/A", "正文 A。" * 30),
        _corpus_row("梗知识/moegirl/B", "正文 B。" * 30),
    ]
    store = _store(tmp_path / "reconcile3.sqlite3")
    _write_corpus(tmp_path, documents=rows, updates=rows)
    sync_kb_wiki(store, _config(tmp_path))

    _write_corpus(
        tmp_path,
        documents=[rows[0]],
        updates=[],
        documents_total=99,  # 声称 99 条、entries 只有 1 条
    )
    stats = sync_kb_wiki(store, _config(tmp_path))
    assert stats["reconcile_status"] == "skipped_manifest_incomplete"
    assert stats["removed"] == 0 and store.document_count() == 2


def test_reconcile_holds_removal_for_uncovered_topic(tmp_path: Path) -> None:
    """爬虫按 topic 子集导出：未覆盖域的台账行挂起不删，状态点名。"""
    kept = _corpus_row("鸣潮/bilibili_wiki_wutheringwaves/A", "鸣潮正文。" * 30)
    other = _corpus_row("战双帕弥什/bilibili_wiki_zspms/B", "战双正文。" * 30)
    store = _store(tmp_path / "reconcile4.sqlite3")
    _write_corpus(tmp_path, documents=[kept, other], updates=[kept, other])
    sync_kb_wiki(store, _config(tmp_path))
    assert store.document_count() == 2

    # 本轮清单只覆盖 鸣潮 域：战双 台账行成了「清单查无」，但绝不据此删除。
    _write_corpus(
        tmp_path,
        documents=[kept],
        updates=[],
        topic_stats={"鸣潮": {"documents": 1, "max_crawled_at": "2026-09-20T15:00:00Z"}},
    )
    stats = sync_kb_wiki(store, _config(tmp_path))
    assert stats["reconcile_status"] == "remove_suspended"
    assert stats["reconcile_held"] == 1 and stats["reconcile_extra"] == 0
    assert store.document_count() == 2


# ---------------------------------------------------------------- 4 可观测性


def test_sync_summary_lands_in_knowledge_meta(tmp_path: Path) -> None:
    """每轮 summary 落 knowledge_meta（单行 JSON）：WebUI 与 CLI 读同一份记录。"""
    rows = [_corpus_row("梗知识/moegirl/A", "摘要正文。" * 30)]
    _write_corpus(tmp_path, documents=rows, updates=rows)
    store = _store(tmp_path / "summary.sqlite3")
    config = _config(tmp_path)

    result = kb_wiki.run_kb_sync_task(config, store=store, embed=False)
    summary = kb_wiki.read_kb_sync_summary(store)
    assert summary["ok"] is True and summary["error_kind"] == "none"
    assert summary["mode"] == "incremental"
    assert summary["added"] == result["added"] == 1
    assert summary["duration_ms"] == result["duration_ms"]
    assert summary["started_at"] and summary["finished_at"]
    assert summary["metadata_refreshed"] == result["metadata_refreshed"]
    assert summary["reconcile_missing"] == 1
    assert "documents.jsonl" not in json.dumps(summary, ensure_ascii=False)  # 不外泄路径
    with store._connect() as connection:
        raw = str(
            connection.execute(
                "SELECT value FROM knowledge_meta WHERE key = ?",
                (kb_wiki.SYNC_SUMMARY_META_KEY,),
            ).fetchone()[0]
        )
    assert json.loads(raw)["added"] == 1


def test_failed_sync_records_summary_and_alerts(tmp_path: Path) -> None:
    """语料缺失 → 摘要记 error_kind=kb_missing 且走告警 sink（静默≠无痕）。"""
    alerts: list = []
    kb_wiki.set_kb_sync_alert_sink(alerts.append)
    try:
        store = _store(tmp_path / "fail.sqlite3")
        result = kb_wiki.run_kb_sync_task(_config(tmp_path), store=store)  # 无清单文件
        assert result["error_kind"] == "kb_missing" and result["ok"] is False
        summary = kb_wiki.read_kb_sync_summary(store)
        assert summary["ok"] is False and summary["error_kind"] == "kb_missing"
        assert summary["public_message"]
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.level == "warning"
        assert "kb_missing" in alert.what_happened
        assert alert.title and alert.impact and alert.fix_suggestion and alert.location
    finally:
        kb_wiki.set_kb_sync_alert_sink(None)


def test_partial_embed_alerts_and_success_does_not(tmp_path: Path) -> None:
    """嵌入只做了一半 → error_kind=partial 必告警；跑通与取消不告警。"""
    rows = [_corpus_row("梗知识/moegirl/A", "部分嵌入正文。" * 30)]
    _write_corpus(tmp_path, documents=rows, updates=rows)
    alerts: list = []
    kb_wiki.set_kb_sync_alert_sink(alerts.append)
    try:
        # 空链 provider（无任何嵌入端点）：待嵌行一行也嵌不完 → partial。
        store = _store(tmp_path / "partial.sqlite3", embed_provider=object())
        result = kb_wiki.run_kb_sync_task(_config(tmp_path), store=store)
        assert result["error_kind"] == "partial", result
        assert [alert.level for alert in alerts] == ["warning"]
        assert "嵌入只完成" in alerts[0].what_happened

        alerts.clear()
        ok_store = _store(tmp_path / "ok.sqlite3")
        ok = kb_wiki.run_kb_sync_task(_config(tmp_path), store=ok_store, embed=False)
        assert ok["ok"] is True and alerts == []

        alerts.clear()
        kb_wiki.cancel_kb_sync_task(reason="unit-test")
        cancelled = kb_wiki.run_kb_sync_task(_config(tmp_path), store=ok_store)
        assert cancelled["error_kind"] == "cancelled" and alerts == []
        assert kb_wiki.read_kb_sync_summary(ok_store)["error_kind"] == "cancelled"
    finally:
        kb_wiki.set_kb_sync_alert_sink(None)


def test_alert_sink_none_falls_back_to_log(tmp_path: Path, caplog) -> None:
    """未注入 sink 时退回 WARNING 日志（与注入前的旧行为一致，不静默吞掉）。"""
    kb_wiki.set_kb_sync_alert_sink(None)
    store = _store(tmp_path / "logfallback.sqlite3")
    with caplog.at_level("WARNING"):
        result = kb_wiki.run_kb_sync_task(_config(tmp_path), store=store)
    assert result["error_kind"] == "kb_missing"
    assert any("kb_wiki_sync 需要关注" in record.message for record in caplog.records)


def test_broken_sink_cannot_break_sync(tmp_path: Path) -> None:
    """告警链路自身故障必须 fail-open：同步结果照常返回、异常不外抛。"""
    def _boom(_alert) -> None:
        raise RuntimeError("sink 炸了")

    kb_wiki.set_kb_sync_alert_sink(_boom)
    try:
        store = _store(tmp_path / "brokensink.sqlite3")
        result = kb_wiki.run_kb_sync_task(_config(tmp_path), store=store)
        assert result["error_kind"] == "kb_missing"
        assert kb_wiki.read_kb_sync_summary(store)["ok"] is False
    finally:
        kb_wiki.set_kb_sync_alert_sink(None)


# ---------------------------------------------------------------- 契约一致性


def test_webui_reads_the_same_meta_key_and_column_names() -> None:
    """跨文件契约锁：摘要键与台账列名两处必须一致（改一处必红）。"""
    assert webui_knowledge._KB_SYNC_SUMMARY_KEY == kb_wiki.SYNC_SUMMARY_META_KEY
    from plugins.bot_unified_runtime.domains.chat_reply.character import (
        vector_knowledge,
    )

    assert set(vector_knowledge._DOC_METADATA_COLUMNS) == set(
        webui_knowledge._KB_DOC_TIME_COLUMNS
    )
    # 语料行字段名是与爬虫导出层的契约（KB_HANDOFF / kb_time_export 侧同名）。
    assert kb_wiki._TIME_FIELD_TO_LEDGER_COLUMN == (
        ("updated_at", "source_updated_at"),
        ("crawled_at", "crawl_at"),
    )


def test_row_time_metadata_ignores_absent_keys() -> None:
    assert kb_wiki.row_time_metadata({"updated_at": "", "crawled_at": "2026-01-01T00:00:00Z"}) == {
        "source_updated_at": "",
        "crawl_at": "2026-01-01T00:00:00Z",
    }
    assert kb_wiki.row_time_metadata({"id": "x"}) == {}


@pytest.mark.parametrize(
    ("documents_total", "expected_status", "expected_missing"),
    [(None, "ok", {"梗知识/moegirl/A"}), (99, "skipped_manifest_incomplete", set())],
)
def test_manifest_index_guards(
    tmp_path: Path,
    documents_total: int | None,
    expected_status: str,
    expected_missing: set[str],
) -> None:
    row = _corpus_row("梗知识/moegirl/A", "正文。" * 30)
    _write_corpus(
        tmp_path,
        documents=[row],
        updates=[row],
        documents_total=documents_total,
    )
    manifest = json.loads(
        (tmp_path / "crawl_output" / "knowledge_base" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    stats, missing, extra = kb_wiki.reconcile_with_manifest(
        _store(tmp_path / "index.sqlite3"), manifest, []
    )
    assert stats["reconcile_status"] == expected_status
    assert missing == expected_missing and extra == set()
    # topics 过滤双向一致：不在配置域内的清单条目不参与对账。
    scoped = kb_wiki.reconcile_with_manifest(
        _store(tmp_path / "index2.sqlite3"), manifest, ["别的域"]
    )
    assert scoped[1] == set() and scoped[2] == set()

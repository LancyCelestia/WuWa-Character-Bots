"""S22 席：启动期幂等补列/建索引必须成为**可见事件**（一次 WARN，复跑静默）。

现场（主会话现算，非回忆）：``SqliteVectorKnowledgeStore._ensure_schema`` 在建店时做
``CREATE TABLE IF NOT EXISTS`` + 两处 ``ALTER TABLE ... ADD COLUMN``（if missing）+
两处 ``CREATE INDEX IF NOT EXISTS``。2026-10-02 23:38:22 bot 重启，23:38:34 两枚库
（人格库 / wiki 库）就被自动加了 ``persona_id`` 列与索引，事前无备份、**日志零行**。
用户裁定（P-1）＝保留幂等补列（元数据级、缺省 ``''``＝未归属、读侧行为不变，
仿 ``vector_blob``/好感度 v5 在册先例），只把"我改了 schema"变成可诊断事件。

本件钉三件事（台账 241 教训：判据要两侧都非零，缺席即 skip 那一侧天生无牙）：

1. 旧 schema 库（无 ``persona_id`` 列）进店 ⇒ **恰好一条** WARN，四问齐：
   哪个库文件、哪张表、加了什么（列 + 索引）、是否首次（本行只在真改动那次出现）；
2. 同一枚库再进店（幂等复跑）⇒ 该事件 **零条**（不许每次重启刷一行）；
3. WARN 里不得出现盘符绝对路径形态（规则 3 出口口径：只出文件名 + 父目录名，
   各过 ``redact_local_secrets``，绝不写 ``self.db_path`` 原文）。

全离线：只用 ``tmp_path`` 临时库，绝不碰 ``ChatBot_Runtime/``（禁 DDL/DML）。
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)

_EVENT = "knowledge_schema_auto_migration"
# 盘符绝对路径形态（`C:\` 与 `C:/` 两形，同 redact_local_secrets 的盘符哨兵）。
_DRIVE_PATH_RE = re.compile(r"[A-Za-z]:[\\/]")
_DB_NAME = "kbschema_test.sqlite3"


class _StubEmbedder:
    def embed_texts(self, texts):
        return [[0.0, 0.0, 1.0] for _ in texts]


def _store(db_path: Path) -> SqliteVectorKnowledgeStore:
    return SqliteVectorKnowledgeStore(
        db_path=db_path,
        embed_provider=_StubEmbedder(),
        signature="test|fake",
        auto_reset=False,
        fts_auto_rebuild=False,
    )


def _make_old_schema_db(db_path: Path) -> None:
    """复现 10-02 的生产现场：**已有**旧表（无 vector_blob / persona_id、无索引）。"""
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE knowledge_chunks (
                chunk_id TEXT PRIMARY KEY,
                source_id TEXT,
                title TEXT,
                content TEXT,
                content_hash TEXT,
                vector_json TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO knowledge_chunks VALUES "
            "('c1', 's1', 't1', '既有内容', 'h1', NULL)"
        )


def _event_records(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if _EVENT in r.getMessage()]


def test_old_schema_db_entry_emits_exactly_one_notice(tmp_path: Path, caplog) -> None:
    db_path = tmp_path / _DB_NAME
    _make_old_schema_db(db_path)

    with caplog.at_level(
        logging.WARNING,
        logger="plugins.bot_unified_runtime.domains.chat_reply.character"
        ".vector_knowledge",
    ):
        _store(db_path)

    events = _event_records(caplog)
    assert len(events) == 1, events
    message = events[0]
    # 四问齐：库文件 / 表 / 加了什么 / 首次（出现即首次，复跑不再出现由第二腿钉）。
    assert f"db_file={_DB_NAME}" in message, message
    assert "table=knowledge_chunks" in message, message
    assert "added_columns=vector_blob,persona_id" in message, message
    assert (
        "added_indexes=idx_knowledge_chunks_persona,idx_knowledge_chunks_source"
        in message
    ), message


def test_notice_never_leaks_absolute_drive_letter_path(tmp_path: Path, caplog) -> None:
    db_path = tmp_path / _DB_NAME
    _make_old_schema_db(db_path)

    with caplog.at_level(
        logging.WARNING,
        logger="plugins.bot_unified_runtime.domains.chat_reply.character"
        ".vector_knowledge",
    ):
        _store(db_path)

    events = _event_records(caplog)
    assert len(events) == 1, events
    message = events[0]
    assert not _DRIVE_PATH_RE.search(message), message
    # 最硬的一条：临时库的绝对路径原文一个字都不许出现在日志里。
    assert str(db_path) not in message, message
    assert str(tmp_path) not in message, message


def test_idempotent_re_entry_stays_silent(tmp_path: Path, caplog) -> None:
    db_path = tmp_path / _DB_NAME
    _make_old_schema_db(db_path)
    logger_name = (
        "plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge"
    )

    with caplog.at_level(logging.WARNING, logger=logger_name):
        first = _store(db_path)
        assert len(_event_records(caplog)) == 1, _event_records(caplog)
        first._conn_tls.connection = None
        caplog.clear()
        second = _store(db_path)

    assert _event_records(caplog) == [], _event_records(caplog)

    # 存量与判据都不许被这次改动动到：列在册、原行仍在、读侧仍把未归属当可见。
    with second._connect() as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(knowledge_chunks)")
        }
        indexes = {
            str(row[1])
            for row in connection.execute("PRAGMA index_list(knowledge_chunks)")
        }
        kept = [
            (str(row["chunk_id"]), str(row["persona_id"]))
            for row in connection.execute(
                "SELECT chunk_id, persona_id FROM knowledge_chunks"
            )
        ]
    assert {"vector_blob", "persona_id"} <= columns, columns
    assert {
        "idx_knowledge_chunks_persona",
        "idx_knowledge_chunks_source",
    } <= indexes, indexes
    # 补列后原行照在、归属为 ''＝未归属（读侧仍可见 ⇒ 零行为变化）。
    assert kept == [("c1", "")], kept


def test_fresh_db_entry_notices_index_creation_only(tmp_path: Path, caplog) -> None:
    """全新库：CREATE TABLE 已内带两列 ⇒ 只该报"建了索引"，不虚报补列。"""
    db_path = tmp_path / _DB_NAME
    logger_name = (
        "plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge"
    )

    with caplog.at_level(logging.WARNING, logger=logger_name):
        _store(db_path)

    events = _event_records(caplog)
    assert len(events) == 1, events
    assert "added_columns=-" in events[0], events[0]
    assert "idx_knowledge_chunks_persona" in events[0], events[0]
    # 再复跑一次仍静默（判据不区分新旧库）。
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=logger_name):
        _store(db_path)
    assert _event_records(caplog) == [], _event_records(caplog)


if __name__ == "__main__":  # pragma: no cover - 便于按简报里的卫生前缀直跑
    raise SystemExit(pytest.main([__file__, "-q"]))

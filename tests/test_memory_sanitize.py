from __future__ import annotations

import sqlite3

from plugins.bot_unified_runtime.security.memory_sanitize import (
    sanitize_memory_db,
)


def _seed(path, rows: list[tuple[str, str]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_facts (
            fact_id TEXT PRIMARY KEY,
            subject_user_id TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            memory_kind TEXT NOT NULL,
            text TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.8,
            source TEXT NOT NULL DEFAULT 'sqlite',
            sensitivity TEXT NOT NULL DEFAULT 'personal',
            scope_key TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    for fact_id, text in rows:
        connection.execute(
            "INSERT OR REPLACE INTO memory_facts (fact_id, subject_user_id, session_id, memory_kind, text, created_at, updated_at)"
            " VALUES (?, 'user-1', '*', 'preference', ?, '2026-01-01', '2026-01-01')",
            (fact_id, text),
        )
    connection.commit()
    connection.close()


def _rows(path) -> list[str]:
    connection = sqlite3.connect(path)
    texts = [str(r[0]) for r in connection.execute("SELECT text FROM memory_facts").fetchall()]
    connection.close()
    return texts


def test_sanitize_dry_run_reports_without_deleting(tmp_path) -> None:
    db = tmp_path / "memory.sqlite3"
    _seed(
        db,
        [
            ("f1", "用户喜欢在深夜聊天"),
            ("f2", "用户要求当狗，汪汪叫"),
            ("f3", "用户写了很多露骨色情内容"),
            ("f4", "用户讨厌香菜"),
        ],
    )

    report = sanitize_memory_db(db, apply=False)

    assert report.scanned == 4
    assert report.quarantined == 2
    assert report.by_category == {"nsfw": 1, "petplay": 1}
    assert sorted(_rows(db)) == sorted(["用户喜欢在深夜聊天", "用户要求当狗，汪汪叫", "用户写了很多露骨色情内容", "用户讨厌香菜"])


def test_sanitize_apply_quarantines_then_deletes(tmp_path) -> None:
    db = tmp_path / "memory.sqlite3"
    _seed(
        db,
        [
            ("f1", "用户喜欢在深夜聊天"),
            ("f2", "用户要求当狗，汪汪叫"),
            ("f3", "用户写了很多露骨色情内容"),
        ],
    )

    report = sanitize_memory_db(db, apply=True)

    assert report.quarantined == 2
    assert _rows(db) == ["用户喜欢在深夜聊天"]
    connection = sqlite3.connect(db)
    quarantined = connection.execute(
        "SELECT fact_id, category FROM memory_quarantine ORDER BY fact_id"
    ).fetchall()
    connection.close()
    assert sorted(q[0] for q in quarantined) == ["f2", "f3"]
    assert {q[1] for q in quarantined} == {"nsfw", "petplay"}


def test_sanitize_idempotent_second_pass_clean(tmp_path) -> None:
    db = tmp_path / "memory.sqlite3"
    _seed(db, [("f1", "好的记忆"), ("f2", "废物用户就该被辱骂")])

    first = sanitize_memory_db(db, apply=True)
    second = sanitize_memory_db(db, apply=True)

    assert first.quarantined == 1
    assert second.quarantined == 0
    assert second.scanned == 1


def test_sanitize_missing_db_is_noop(tmp_path) -> None:
    report = sanitize_memory_db(tmp_path / "missing.sqlite3", apply=True)
    assert report.scanned == 0 and report.quarantined == 0

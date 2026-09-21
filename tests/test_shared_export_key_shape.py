"""2026-09-21 深读波 D3-1 回归锁：公共会话导出的群键形必须与生产写侧一致。

病灶（`character/shared_export.py:93` 与 `:131`）：读侧两处都按**冒号形**
``group:<群号>`` 认群，而 ``conversation_turns.session_id`` 由摄取层
NoneBot ``get_session_id()`` 产出，群聊形态是**下划线形**
``group_<群号>_<发送者>``（同 bug 的读侧第一处 ``shared_group.py`` 已由 F4 席
2026-09-20 根修并有 `tests/test_shared_group_key_alignment.py` 双向锁；本文件
是同一 bug 的漏网第二、三处）。后果：

- ``include_private=False`` 的 SQL 过滤 ``LIKE 'group:%'`` → **群导出恒 0 行**；
- 逐行 ``startswith("group:")`` 分类 → 真群行被判 ``private`` →
  ``privacy_level=PERSONAL``（群记录以个人私密级出库，语义反向）。

修法口径＝复用中央判据 ``domains/core/session_keys``（``is_group_session_key``
与两枚前缀常量），不再在本文件持第二份键形字面量。全部离线、临时库，零生产库触碰。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import PrivacyLevel
from plugins.bot_unified_runtime.domains.chat_reply.character.shared_export import (
    SQLiteSharedConversationExporter,
)

_ROWS: tuple[tuple[str, str, str], ...] = (
    # (session_id, role, text) —— 第 1 条＝生产真实群键形，第 2 条＝历史/合成形
    ("group_123_456", "user", "群里说的话甲"),
    ("group:905", "assistant", "群里说的话乙"),
    ("group_123_789", "user", "群里说的话丙"),
    ("private_7001", "user", "私聊说的话"),
    ("3865067623", "user", "裸 uid 私聊"),
    ("groupX123_456", "user", "下划线未转义时会误吞的诱饵行"),
)


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    path = tmp_path / "wuwa_history.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE conversation_turns (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'chat'
            )
            """
        )
        connection.executemany(
            "INSERT INTO conversation_turns (created_at, session_id, role, text, kind)"
            " VALUES (?, ?, ?, ?, 'chat')",
            [(f"2026-09-20T10:00:{i:02d}", sid, role, text) for i, (sid, role, text) in enumerate(_ROWS)],
        )
        connection.commit()
    finally:
        connection.close()
    return path


def test_group_rows_survive_default_export(db: Path) -> None:
    """缺省（不导私聊）必须真的导出群行——旧冒号形过滤下本断言恒 0 行。"""
    records = SQLiteSharedConversationExporter(db).export(limit=50)
    texts = {record.redacted_text for record in records}
    assert {"群里说的话甲", "群里说的话乙", "群里说的话丙"} <= texts, texts
    assert "私聊说的话" not in texts and "裸 uid 私聊" not in texts, texts


def test_underscore_is_not_a_like_wildcard(db: Path) -> None:
    """门有牙：``group_`` 的下划线必须已按 LIKE 转义，诱饵行 ``groupX123_456`` 不得入库。"""
    texts = {record.redacted_text for record in SQLiteSharedConversationExporter(db).export(limit=50)}
    assert "下划线未转义时会误吞的诱饵行" not in texts, texts


def test_group_rows_are_classified_group_not_personal(db: Path) -> None:
    """逐行分类必须走中央判据：两种群形都判 group → privacy_level=GROUP。"""
    records = SQLiteSharedConversationExporter(db).export(limit=50)
    assert records, "空导出会让本锁静默空转"
    for record in records:
        assert record.session_kind == "group", (record.session_kind, record.redacted_text)
        assert record.privacy_level is PrivacyLevel.GROUP, record.redacted_text


def test_include_private_admits_private_rows(db: Path) -> None:
    """放开私聊面时私聊行进入导出，但分类仍是 private（不得反过来把私聊判成群）。"""
    records = SQLiteSharedConversationExporter(db, include_private=True).export(limit=50)
    by_text = {record.redacted_text: record for record in records}
    assert by_text["私聊说的话"].session_kind == "private"
    assert by_text["私聊说的话"].privacy_level is PrivacyLevel.PERSONAL
    assert by_text["群里说的话甲"].session_kind == "group"

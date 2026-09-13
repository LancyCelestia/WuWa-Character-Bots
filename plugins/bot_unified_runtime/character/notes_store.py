"""笔记存储（notes_store）：SQLite 笔记/待办（WAL 先于 DDL；单连接 + 锁）。

设计（2026-09-13 六域批）：
- 字段：id/user_id/chat_id/content_md/kind/todo_state/created_at/updated_at/
  done_at。content_md **原样存储 Markdown**（#/## 三级标题、列表、图片引用行）。
- kind：``note``（普通笔记）/ ``todo``（待办，content_md 含 ``- [ ]`` 勾选框
  时自动判为 todo）；todo_state：``open`` / ``done``（done_at 记勾选时刻）。
- 图片不在库里存字节：content_md 落 ``![图片N](文件名)`` 引用行，文件本体
  存 data/notes_images/<chat 摘要>/<文件名>（capabilities/notes.py 负责
  落盘与回发；store 只认文本）。
- 数量上限：单会话笔记数 ≥ max_notes_per_chat 时 add 拒绝（返回 None），
  由能力层给人话提示。
- 会话隔离：一切读写都带 chat_id（=message.session_id），A 群看不到 B 群。
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# ``- [ ]`` / ``[ ]`` 开头的待办勾选框（判 todo 的唯一依据，确定性）。
_TODO_BOX_RE = re.compile(r"(?m)^\s*[-*]?\s*\[\s?\]\s")

# 勾选框前缀（display_headline 单行摘要剥壳用）：``- [ ] ``/``[x] ``/``☐ ``
# 等形态；与 capabilities/notes.py 的 _TODO_BOX_PREFIX_RE 同一风格。
_TODO_BOX_PREFIX_RE = re.compile(r"^[-*]?\s*\[[ xX]?\]\s*|^[☐☑☒]\s*")


def detect_note_kind(content_md: str) -> tuple[str, str]:
    """内容 → (kind, todo_state)：含未勾选框 = 待办；否则普通笔记。"""
    if _TODO_BOX_RE.search(str(content_md or "")):
        return "todo", "open"
    return "note", ""


@dataclass(frozen=True)
class Note:
    note_id: int
    user_id: str
    chat_id: str
    content_md: str
    kind: str
    todo_state: str
    created_at: str
    updated_at: str
    done_at: str

    @property
    def is_todo(self) -> bool:
        return self.kind == "todo"

    @property
    def is_open(self) -> bool:
        return self.kind == "todo" and self.todo_state == "open"

    def display_headline(self, *, max_chars: int = 24) -> str:
        """列表/确认用的单行摘要：首行非图片，剥勾选框标记，截到 max_chars。"""
        for raw_line in str(self.content_md or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("![图片"):
                continue
            line = _TODO_BOX_PREFIX_RE.sub("", line).strip()
            return line[:max_chars] if line else "(空待办)"
        return "(空笔记)"


def _utc_now_iso() -> str:
    # UTC aware 口径（字段只做展示/幂等，不做时刻比较）。
    return datetime.now(UTC).isoformat()


class NotesStore:
    """SQLite 笔记 store（与 ReminderStore 同一套卫生习惯）。"""

    def __init__(self, path: str | Path, *, max_notes_per_chat: int = 200) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._max_per_chat = max(1, int(max_notes_per_chat))
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT '',
                    chat_id TEXT NOT NULL,
                    content_md TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'note',
                    todo_state TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    done_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_chat ON notes(chat_id, note_id)"
            )

    # -- 写面 -----------------------------------------------------------------

    def add(
        self,
        *,
        user_id: str,
        chat_id: str,
        content_md: str,
        kind: str | None = None,
        todo_state: str | None = None,
    ) -> Note | None:
        """新增笔记；单会话数量达上限时返回 None（不覆盖旧内容）。"""
        content_md = str(content_md or "").strip()
        if not content_md:
            raise ValueError("content_md 不能为空")
        if kind is None:
            kind, todo_state = detect_note_kind(content_md)
        created = _utc_now_iso()
        with self._lock, self._conn:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM notes WHERE chat_id = ?", (chat_id,)
            ).fetchone()[0]
            if int(count or 0) >= self._max_per_chat:
                return None
            cursor = self._conn.execute(
                "INSERT INTO notes (user_id, chat_id, content_md, kind, todo_state,"
                " created_at, updated_at, done_at) VALUES (?, ?, ?, ?, ?, ?, ?, '')",
                (str(user_id), str(chat_id), content_md, str(kind),
                 str(todo_state or ""), created, created),
            )
            note_id = int(cursor.lastrowid or 0)
        return Note(
            note_id=note_id, user_id=str(user_id), chat_id=str(chat_id),
            content_md=content_md, kind=str(kind), todo_state=str(todo_state or ""),
            created_at=created, updated_at=created, done_at="",
        )

    def mark_done(self, note_id: int, chat_id: str) -> Note | None:
        """勾选待办（幂等：已完成的重复勾选返回原记录且不再刷新 done_at）。

        锁纪律：UPDATE 与 ``self.get()`` 必须分两段——``threading.Lock``
        不可重入，持锁调 ``self.get()``（其内部再次取锁）会死锁
        （2026-09-13 实测：重复勾选路径整线程挂死，pytest 卡死定位）。
        """
        done_at = _utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE notes SET todo_state = 'done', done_at = ?, updated_at = ?"
                " WHERE note_id = ? AND chat_id = ? AND kind = 'todo'"
                " AND todo_state <> 'done'",
                (done_at, done_at, int(note_id), str(chat_id)),
            )
        # 无论本轮是否实际勾上，都返回最新记录（幂等语义：不刷新 done_at）。
        return self.get(int(note_id), chat_id)

    def delete(self, note_id: int, chat_id: str) -> Note | None:
        """删除笔记，返回被删记录（供能力层清理图片文件）；未命中返回 None。"""
        note = self.get(int(note_id), chat_id)
        if note is None:
            return None
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM notes WHERE note_id = ? AND chat_id = ?",
                (int(note_id), str(chat_id)),
            )
        return note

    # -- 读面 -----------------------------------------------------------------

    def count_chat(self, chat_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM notes WHERE chat_id = ?", (str(chat_id),)
            ).fetchone()
        return int(row[0] or 0)

    def get(self, note_id: int, chat_id: str) -> Note | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT note_id, user_id, chat_id, content_md, kind, todo_state,"
                " created_at, updated_at, done_at FROM notes"
                " WHERE note_id = ? AND chat_id = ?",
                (int(note_id), str(chat_id)),
            ).fetchone()
        return self._row_to_note(row)

    def list_notes(self, chat_id: str, *, limit: int = 50) -> list[Note]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT note_id, user_id, chat_id, content_md, kind, todo_state,"
                " created_at, updated_at, done_at FROM notes"
                " WHERE chat_id = ? ORDER BY note_id ASC LIMIT ?",
                (str(chat_id), int(limit)),
            ).fetchall()
        return [note for note in (self._row_to_note(row) for row in rows) if note]

    def list_open_todos(self, chat_id: str, *, limit: int = 50) -> list[Note]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT note_id, user_id, chat_id, content_md, kind, todo_state,"
                " created_at, updated_at, done_at FROM notes"
                " WHERE chat_id = ? AND kind = 'todo' AND todo_state = 'open'"
                " ORDER BY note_id ASC LIMIT ?",
                (str(chat_id), int(limit)),
            ).fetchall()
        return [note for note in (self._row_to_note(row) for row in rows) if note]

    # -- 内部 -----------------------------------------------------------------

    @staticmethod
    def _row_to_note(row: tuple | None) -> Note | None:
        if row is None:
            return None
        return Note(
            note_id=int(row[0]), user_id=str(row[1]), chat_id=str(row[2]),
            content_md=str(row[3]), kind=str(row[4]), todo_state=str(row[5]),
            created_at=str(row[6]), updated_at=str(row[7]), done_at=str(row[8]),
        )

    def close(self) -> None:
        self._conn.close()


_STORES: dict[str, NotesStore] = {}
_STORES_LOCK = threading.Lock()


def build_notes_store(config: object) -> NotesStore:
    """进程级共享笔记 store（与 build_reminder_store 同模式）。"""
    from plugins.bot_unified_runtime.character.providers import build_runtime_data_path

    db_path = str(
        build_runtime_data_path(
            config, str(getattr(config, "bot_notes_db_path", "data/notes.sqlite3"))
        )
    )
    max_per_chat = int(getattr(config, "bot_notes_max_per_chat", 200) or 200)
    with _STORES_LOCK:
        store = _STORES.get(db_path)
        if store is None:
            store = NotesStore(db_path, max_notes_per_chat=max_per_chat)
            _STORES[db_path] = store
        return store


def reset_stores_for_tests() -> None:
    """测试专用：清空共享 store 缓存（防 tmp_path 跨用例串库）。"""
    with _STORES_LOCK:
        _STORES.clear()


__all__ = [
    "Note",
    "NotesStore",
    "build_notes_store",
    "detect_note_kind",
    "reset_stores_for_tests",
]

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

# 未勾选条目行（todo_match_texts 逐行判定用）：与 _TODO_BOX_RE 同口径去 (?m)。
_TODO_OPEN_LINE_RE = re.compile(r"^\s*[-*]?\s*\[\s?\]\s")

# 勾选框行（未勾与已勾都认，``- [ ]``/``- [x]``/``- [X]``）：审查 A-06 逐条
# 勾选的定位基准——稳定条目号按「全部勾选框行」的文档行序编号，若只对未勾
# 行编号，勾掉一条会让其余编号整体前移、并发下指错行。
_BOX_ANY_LINE_RE = re.compile(r"^\s*[-*]?\s*\[[ xX]?\]\s")

# 未勾选框的行内形态（分组捕获便于整体改写为 [x]）；与 _TODO_OPEN_LINE_RE
# 同一族，多两组括号。``\g<1>``/``\g<2>`` 防组号与字面 x 粘连歧义。
_BOX_OPEN_INLINE_RE = re.compile(r"^(\s*[-*]?\s*\[)\s?(\]\s)")

# 已勾行（未勾与已勾的行级判定分家）：撤销勾选（审查 A-14）用它把已勾行
# 从全部勾选框行里挑出来；大小写 [x]/[X] 都认，与 _BOX_ANY_LINE_RE 同口径。
_BOX_DONE_LINE_RE = re.compile(r"^\s*[-*]?\s*\[[xX]\]\s")

# 已勾框的行内形态（分组捕获便于回写为 [ ]）：与 _BOX_OPEN_INLINE_RE 同一
# 族；回写统一落规范形态 ``[ ] ``（方括号内补一个空格），缩进与行内其余
# 文本由捕获组原样保留。
_BOX_DONE_INLINE_RE = re.compile(r"^(\s*[-*]?\s*\[)[xX](\]\s)")


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

    def todo_match_texts(self, *, max_chars: int = 40) -> list[str]:
        """勾选匹配用的待办条目行：每条**未勾选** todo 行剥壳后的文本。

        与 display_headline（首行摘要）的分工：自然语言勾选（「买牛奶
        搞定了」）的候选必须是逐条条目而非整篇标题，否则 ``采购清单
        \\n- [ ] 买牛奶`` 的候选是「采购清单」，「买牛奶」永远勾不掉
        （2026-09-13 勾选回归修复）。已勾选（``[x]``）行不算候选。
        """
        texts: list[str] = []
        for raw_line in str(self.content_md or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("![图片"):
                continue
            if not _TODO_OPEN_LINE_RE.match(line):
                continue
            text = _TODO_BOX_PREFIX_RE.sub("", line).strip()
            if text:
                texts.append(text[:max_chars])
        return texts

    def todo_open_items(self) -> list[tuple[int, str]]:
        """未勾条目清单：``[(稳定条目号, 剥壳文本)]``（审查 A-06 新增）。

        稳定条目号 = content_md 里**全部勾选框行**（含已勾）的文档行序
        （0 基），与 ``mark_item_done`` 的 item_index 同一口径——勾掉一条
        不会让其余编号前移，跨调用稳定可回写。已勾行占号但不进候选。
        与 todo_match_texts（仅文本、供模糊匹配）的分工：本方法额外给出
        可直接交给 mark_item_done 的编号。
        """
        items: list[tuple[int, str]] = []
        stable_index = -1
        for raw_line in str(self.content_md or "").splitlines():
            if not _BOX_ANY_LINE_RE.match(raw_line):
                continue
            stable_index += 1
            if not _TODO_OPEN_LINE_RE.match(raw_line):
                continue  # 已勾行：占号不进候选。
            text = _TODO_BOX_PREFIX_RE.sub("", raw_line.strip()).strip()
            if text:
                items.append((stable_index, text))
        return items

    def todo_checked_items(self) -> list[tuple[int, str]]:
        """已勾条目清单：``[(稳定条目号, 剥壳文本)]``（审查 A-14 撤销入口）。

        todo_open_items 的镜像：条目号 = content_md 里**全部勾选框行**（含
        未勾）的文档行序（0 基），可直接交给 ``mark_item_undone`` 回写；
        未勾行占号不进候选。自然语言撤销（「<事项>还没做」）在已勾条目里
        找匹配对象，匹配文本与本方法返回的剥壳文本同口径。
        """
        items: list[tuple[int, str]] = []
        stable_index = -1
        for raw_line in str(self.content_md or "").splitlines():
            if not _BOX_ANY_LINE_RE.match(raw_line):
                continue
            stable_index += 1
            if not _BOX_DONE_LINE_RE.match(raw_line):
                continue  # 未勾行：占号不进候选。
            text = _TODO_BOX_PREFIX_RE.sub("", raw_line.strip()).strip()
            if text:
                items.append((stable_index, text))
        return items


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
        """整篇勾选（兼容路径，审查 A-06 后**仅限非条目类待办使用**）。

        语义原样保留：一条 UPDATE 把整篇置 done（幂等：已完成的重复勾选
        返回原记录且不再刷新 done_at）；content_md 里的 ``- [ ]`` **不回写
        ``[x]``**——这正是 A-06 缺陷本体，条目类待办一律走
        ``mark_item_done``。现存调用方：reminder 关键词勾选流（域外，
        待其自行切换条目 API）与本 store 的历史数据收口分支。

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

    def mark_item_done(
        self, note_id: int, chat_id: str, item_index: int
    ) -> Note | None:
        """按条目勾选待办（审查 A-06：勾一条只动一条，不再整篇置完成）。

        契约：
        - ``item_index`` 为 **0 基**，按 content_md 中**全部勾选框行**（含
          已勾 ``[x]``）的文档行序编号——含已勾行是为了编号跨调用稳定
          （只对未勾行编号的话，勾掉一条其余编号会整体前移）。
        - 目标行未勾（``[ ]``）：改写为 ``[x]``，缩进与行内其余文本原样；
          改写后已无未勾行 → ``todo_state='done'`` + ``done_at=now``（全部
          勾完才算整篇完成）；仍有未勾行 → ``todo_state`` 保持原值，只刷
          ``updated_at``。
        - 幂等：目标行已是 ``[x]`` → **完全无写入**（done_at、updated_at
          都不动），返回当前记录。
        - 越界（笔记不存在 / 非待办 / item_index 不落在任何勾选框行，含
          负数）→ 返回 None，零写入。调用方若要区分「笔记不存在」与
          「编号越界」请自行先 get（能力层就是这么做的）。
        - 并发：读-算-写三段间可能被并发改写，UPDATE 带 ``content_md``
          守护条件，守护失败则重读重算（有限次），不吞别人的勾选。

        锁纪律（同 mark_done，2026-09-13 实测教训）：``threading.Lock``
        不可重入，UPDATE 与 ``self.get()`` 必须分两段取锁，持锁调
        ``self.get()`` 会死锁。
        """
        note_id = int(note_id)
        item_index = int(item_index)
        # 有限重试：并发改写同一篇时 content_md 守护失败 → 重读重算。
        for _attempt in range(5):
            note = self.get(note_id, chat_id)
            if note is None or not note.is_todo:
                return None
            lines = str(note.content_md or "").splitlines(keepends=True)
            box_positions = [
                position for position, line in enumerate(lines)
                if _BOX_ANY_LINE_RE.match(line)
            ]
            if not 0 <= item_index < len(box_positions):
                return None
            target = lines[box_positions[item_index]]
            if not _TODO_OPEN_LINE_RE.match(target):
                # 已勾行重复勾选：幂等无写入，返回当前记录。
                return note
            new_lines = list(lines)
            new_lines[box_positions[item_index]] = _BOX_OPEN_INLINE_RE.sub(
                r"\g<1>x\g<2>", target, count=1
            )
            new_content = "".join(new_lines)
            # 全部勾完才置整篇 done（以改写后的全文判定，与 detect 同口径）。
            all_done = _TODO_BOX_RE.search(new_content) is None
            now = _utc_now_iso()
            with self._lock, self._conn:
                cursor = self._conn.execute(
                    "UPDATE notes SET content_md = ?, updated_at = ?,"
                    " todo_state = ?, done_at = ?"
                    " WHERE note_id = ? AND chat_id = ? AND content_md = ?",
                    (
                        new_content,
                        now,
                        "done" if all_done else str(note.todo_state),
                        now if all_done else str(note.done_at),
                        note_id,
                        str(chat_id),
                        str(note.content_md),
                    ),
                )
                changed = int(cursor.rowcount or 0)
            if changed:
                # 锁纪律：get() 在持锁段之外单独取锁。
                return self.get(note_id, chat_id)
            # 守护失败：并发改写了同一篇，重读重算；重试耗尽则返回最新态。
        return self.get(note_id, chat_id)

    def mark_item_undone(
        self, note_id: int, chat_id: str, item_index: int
    ) -> Note | None:
        """按条目撤销勾选（审查 A-14：mark_item_done 的对称逆操作）。

        契约（与 mark_item_done 完全同口径，只是改写方向相反）：
        - ``item_index`` 为 **0 基**，按 content_md 中**全部勾选框行**（含
          未勾 ``[ ]``）的文档行序编号——与 ``todo_checked_items``/
          ``mark_item_done`` 同一稳定编号，勾/撤销来回切换不错位。
        - 目标行已勾（``[x]``/``[X]``）：回写为规范形态 ``[ ]``，缩进与
          行内其余文本原样；回写后该篇必有未勾行 → ``todo_state='open'``
          且 ``done_at=''``（整篇 done 是「最后一条被勾完」触发的，撤销
          任意一条都意味着不再全勾完，无论撤销的是不是最后那条）。
        - 幂等：目标行未勾 → **完全无写入**（updated_at 也不动），返回
          当前记录。
        - 越界（笔记不存在 / 非待办 / item_index 不落在任何勾选框行，含
          负数）→ 返回 None，零写入。
        - 并发：UPDATE 带 ``content_md`` 守护条件，守护失败重读重算
          （有限次），不吞别人的勾选/撤销。

        锁纪律（同 mark_done）：``threading.Lock`` 不可重入，UPDATE 与
        ``self.get()`` 必须分两段取锁，持锁调 ``self.get()`` 会死锁。
        """
        note_id = int(note_id)
        item_index = int(item_index)
        # 有限重试：并发改写同一篇时 content_md 守护失败 → 重读重算。
        for _attempt in range(5):
            note = self.get(note_id, chat_id)
            if note is None or not note.is_todo:
                return None
            lines = str(note.content_md or "").splitlines(keepends=True)
            box_positions = [
                position for position, line in enumerate(lines)
                if _BOX_ANY_LINE_RE.match(line)
            ]
            if not 0 <= item_index < len(box_positions):
                return None
            target = lines[box_positions[item_index]]
            if not _BOX_DONE_LINE_RE.match(target):
                # 未勾行再撤销：幂等无写入，返回当前记录。
                return note
            new_lines = list(lines)
            new_lines[box_positions[item_index]] = _BOX_DONE_INLINE_RE.sub(
                r"\g<1> \g<2>", target, count=1
            )
            new_content = "".join(new_lines)
            # 撤销后必有未勾行：整篇一律回 open、done_at 清空（不做条件
            # 分支——「撤销的恰是最后一条」与「撤销的是中间一条」结论相同）。
            now = _utc_now_iso()
            with self._lock, self._conn:
                cursor = self._conn.execute(
                    "UPDATE notes SET content_md = ?, updated_at = ?,"
                    " todo_state = 'open', done_at = ''"
                    " WHERE note_id = ? AND chat_id = ? AND content_md = ?",
                    (
                        new_content,
                        now,
                        note_id,
                        str(chat_id),
                        str(note.content_md),
                    ),
                )
                changed = int(cursor.rowcount or 0)
            if changed:
                # 锁纪律：get() 在持锁段之外单独取锁。
                return self.get(note_id, chat_id)
            # 守护失败：并发改写了同一篇，重读重算；重试耗尽则返回最新态。
        return self.get(note_id, chat_id)

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

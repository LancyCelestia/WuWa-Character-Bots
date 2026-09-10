"""人格小习惯评审区（L4「persona quirk」慢变量）。

分层思想（借鉴 OpenPersona 的分层人格设计，全部代码与表结构为本仓库原创）：
- 人格核心（personas/<name>/identity.md 等）经 character/providers.py 只读加载，
  保持 FROZEN——运行时任何角色（反思管线、管理员命令）都不自动改写核心档案；
- 缓慢演化的「小习惯」住在本模块的评审区（SQLite 表 persona_quirks）：
  - propose：反思/观测管线只能把候选送进 pending_review 队列（数量封顶，
    满时逐出最旧），未批准前对 prompt 零影响；
  - approve：管理员过审后转 active，才允许经 render_prompt_section 注入
    prompt（纯自然语言，不外泄任何 id/状态/时间等簿记字段）；
  - retire：active/pending 都可退役，退出渲染但保留历史行；
  - add_direct：管理员手动录入，跳过评审直接生效（同文本去重规则一致：
    已 active 原样返回；命中 pending 视为当场转正；命中 retired 视为复活）。

线程模型与 affinity.py / mood.py 相同：进程内单一 SQLite 连接 +
threading.Lock 串行全部读写，check_same_thread=False 允许事件循环与
offload 线程池跨线程共用同一连接；WAL 在任何 DML 之前设置。
"""

from __future__ import annotations

import builtins
import hashlib
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

STATUS_PENDING = "pending_review"
STATUS_ACTIVE = "active"
STATUS_RETIRED = "retired"
_STATUSES: frozenset[str] = frozenset({STATUS_PENDING, STATUS_ACTIVE, STATUS_RETIRED})

# prompt 注入区块的固定引导语（渲染时置于首行；条目逐行以「- 」起头）。
_PROMPT_HEADER = "最近养成的小习惯（可自然运用，不要刻意罗列）："


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc(moment: datetime) -> str:
    """统一落库格式（UTC，字典序即时间序）；naive 视作 UTC 处理。"""
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_quirk_text(text: str) -> str:
    """去重规范化：折叠全部空白为单空格 + casefold。"""
    return " ".join((text or "").split()).casefold()


def _quirk_id_for(normalized: str) -> str:
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Quirk:
    """一条小习惯的完整簿记视图（admin/审计用；prompt 渲染只取 quirk_text）。"""

    quirk_id: str
    quirk_text: str
    status: str
    source: str
    created_at: str
    reviewed_at: str | None


def _row_to_quirk(row: sqlite3.Row) -> Quirk:
    reviewed = row["reviewed_at"]
    return Quirk(
        quirk_id=str(row["quirk_id"]),
        quirk_text=str(row["quirk_text"]),
        status=str(row["status"]),
        source=str(row["source"]),
        created_at=str(row["created_at"]),
        reviewed_at=None if reviewed is None else str(reviewed),
    )


_SELECT_COLUMNS = "quirk_id, quirk_text, status, source, created_at, reviewed_at"


class QuirkStore:
    """SQLite 小习惯评审区；线程安全；pending 对 prompt 零影响。"""

    def __init__(
        self,
        path: str | Path,
        *,
        max_pending: int = 20,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_pending < 1:
            raise ValueError("max_pending must be >= 1")
        self.db_path = Path(path)
        self._max_pending = int(max_pending)
        self._clock: Callable[[], datetime] = clock if clock is not None else _utc_now
        self._lock = threading.Lock()
        # 进程内复用单一连接（同 affinity.py）：全部操作已在 self._lock 下
        # 串行，check_same_thread=False 允许事件循环与 offload 线程池跨线程
        # 共用同一连接。
        self._connection: sqlite3.Connection | None = None
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            connection = sqlite3.connect(
                self.db_path, timeout=5.0, check_same_thread=False
            )
            connection.row_factory = sqlite3.Row
            # WAL 必须在任何 DML 之前、且连接尚无事务时设置。
            connection.execute("PRAGMA journal_mode=WAL")
            self._connection = connection
        return self._connection

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS persona_quirks (
                    quirk_id TEXT PRIMARY KEY,
                    quirk_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending_review'
                        CHECK (status IN ('pending_review', 'active', 'retired')),
                    source TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                )
                """
            )

    def _now_text(self) -> str:
        return _format_utc(self._clock())

    def close(self) -> None:
        """关闭底层连接（幂等）；仅测试与优雅停机使用。"""
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def propose(self, text: str, source: str = "") -> Quirk:
        """提交一条候选小习惯（只进 pending_review，对 prompt 零影响）。

        - 空白折叠 + casefold 去重：同文本已有 active/pending 行 → 原样返回；
        - 同文本已 retired：再次被提出视为新证据，原地复活回 pending_review
          （主键唯一，只能覆写旧行；重新走评审）；
        - pending 队列封顶 max_pending：满时先逐出最旧（DELETE），再插入新行。
        """
        normalized = normalize_quirk_text(text)
        if not normalized:
            raise ValueError("quirk text 不能为空")
        display_text = " ".join((text or "").split())
        quirk_id = _quirk_id_for(normalized)
        now_text = self._now_text()
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM persona_quirks WHERE quirk_id = ?",
                (quirk_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["status"]) in {STATUS_ACTIVE, STATUS_PENDING}:
                    return _row_to_quirk(existing)
                connection.execute(
                    "UPDATE persona_quirks SET status = 'pending_review', source = ?,"
                    " created_at = ?, reviewed_at = NULL WHERE quirk_id = ?",
                    (source, now_text, quirk_id),
                )
                return Quirk(
                    quirk_id=quirk_id,
                    quirk_text=str(existing["quirk_text"]),
                    status=STATUS_PENDING,
                    source=source,
                    created_at=now_text,
                    reviewed_at=None,
                )
            pending_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM persona_quirks WHERE status = 'pending_review'"
                ).fetchone()[0]
            )
            # 队列封顶：满时先逐出最旧 pending（腾出空位再插入，总数恒 ≤ max_pending）。
            overflow = max(0, pending_count - self._max_pending + 1)
            if overflow > 0:
                stale = connection.execute(
                    "SELECT quirk_id FROM persona_quirks WHERE status = 'pending_review'"
                    " ORDER BY created_at ASC, rowid ASC LIMIT ?",
                    (overflow,),
                ).fetchall()
                for row in stale:
                    connection.execute(
                        "DELETE FROM persona_quirks WHERE quirk_id = ?",
                        (str(row["quirk_id"]),),
                    )
            connection.execute(
                "INSERT INTO persona_quirks"
                " (quirk_id, quirk_text, status, source, created_at, reviewed_at)"
                " VALUES (?, ?, 'pending_review', ?, ?, NULL)",
                (quirk_id, display_text, source, now_text),
            )
            return Quirk(
                quirk_id=quirk_id,
                quirk_text=display_text,
                status=STATUS_PENDING,
                source=source,
                created_at=now_text,
                reviewed_at=None,
            )

    def approve(self, quirk_id: str) -> bool:
        """pending → active；非 pending 或不存在返回 False。"""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE persona_quirks SET status = 'active', reviewed_at = ?"
                " WHERE quirk_id = ? AND status = 'pending_review'",
                (self._now_text(), str(quirk_id).strip()),
            )
        return cursor.rowcount > 0

    def retire(self, quirk_id: str) -> bool:
        """active/pending → retired（保留历史行，退出渲染）；否则 False。"""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE persona_quirks SET status = 'retired', reviewed_at = ?"
                " WHERE quirk_id = ? AND status IN ('active', 'pending_review')",
                (self._now_text(), str(quirk_id).strip()),
            )
        return cursor.rowcount > 0

    def add_direct(self, text: str, source: str = "admin") -> Quirk:
        """管理员手动录入：跳过评审直接 active（去重规则与 propose 一致）。

        命中已有行时保留原行的 source/created_at（提案来源不撒谎），只改状态。
        """
        normalized = normalize_quirk_text(text)
        if not normalized:
            raise ValueError("quirk text 不能为空")
        display_text = " ".join((text or "").split())
        quirk_id = _quirk_id_for(normalized)
        now_text = self._now_text()
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM persona_quirks WHERE quirk_id = ?",
                (quirk_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["status"]) == STATUS_ACTIVE:
                    return _row_to_quirk(existing)
                connection.execute(
                    "UPDATE persona_quirks SET status = 'active', reviewed_at = ?"
                    " WHERE quirk_id = ?",
                    (now_text, quirk_id),
                )
                return Quirk(
                    quirk_id=quirk_id,
                    quirk_text=str(existing["quirk_text"]),
                    status=STATUS_ACTIVE,
                    source=str(existing["source"]),
                    created_at=str(existing["created_at"]),
                    reviewed_at=now_text,
                )
            connection.execute(
                "INSERT INTO persona_quirks"
                " (quirk_id, quirk_text, status, source, created_at, reviewed_at)"
                " VALUES (?, ?, 'active', ?, ?, ?)",
                (quirk_id, display_text, source, now_text, now_text),
            )
            return Quirk(
                quirk_id=quirk_id,
                quirk_text=display_text,
                status=STATUS_ACTIVE,
                source=source,
                created_at=now_text,
                reviewed_at=now_text,
            )

    def list(self, status: str | None = None, limit: int = 50) -> builtins.list[Quirk]:
        """列出小习惯（默认全状态、最新 created_at 在前）。"""
        if status is not None and status not in _STATUSES:
            raise ValueError(f"未知状态：{status}")
        query = f"SELECT {_SELECT_COLUMNS} FROM persona_quirks"
        params: list[object] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_row_to_quirk(row) for row in rows]

    def list_active(self, limit: int = 50) -> builtins.list[Quirk]:
        """列出 active 小习惯，最近过审（reviewed_at）在前。"""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM persona_quirks"
                " WHERE status = 'active'"
                " ORDER BY reviewed_at DESC, rowid DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [_row_to_quirk(row) for row in rows]

    def render_prompt_section(self, max_active: int = 6) -> str:
        """渲染注入 prompt 的小习惯区块；无 active 时返回空串。

        只输出自然语言：引导语 + 逐行「- 文本」，不外泄 id/状态/时间/来源。
        """
        if int(max_active) <= 0:
            return ""
        quirks = self.list_active(limit=int(max_active))
        if not quirks:
            return ""
        lines = [_PROMPT_HEADER]
        lines.extend(f"- {quirk.quirk_text}" for quirk in quirks)
        return "\n".join(lines)

    def counts(self) -> dict[str, int]:
        """按状态计数（三种状态齐全，缺失记 0）。"""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) FROM persona_quirks GROUP BY status"
            ).fetchall()
        result = {status: 0 for status in (STATUS_PENDING, STATUS_ACTIVE, STATUS_RETIRED)}
        for row in rows:
            result[str(row["status"])] = int(row[1])
        return result

"""会话级身份记忆（管理员设置）：每个群聊/私聊窗口独立的称呼与身份标签。

与 L4 quirk 演化区的分工：quirks 是 bot 自身习惯的审核制演化；本模块是
**管理员显式设置**的会话身份——例如规定 bot 在某个群里叫「岸宝」、带
「花房值日」标签。硬约束（防 OOC）：会话身份只调整称呼与语气亲疏，
核心人格事实（守岸人/黑海岸代行者）由 persona 文件冻结，渲染文本里
内建护栏声明，任何标签都不能推翻。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class SessionIdentity:
    session_key: str
    nickname: str
    tags: tuple[str, ...]
    set_by: str
    updated_at: str


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_tags(raw: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        items = [item.strip() for item in raw.replace("，", ",").split(",")]
    else:
        items = [str(item).strip() for item in raw]
    seen: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return tuple(seen[:8])


class SessionIdentityStore:
    """SQLite 会话身份 store（WAL 先于 DDL；单连接 + threading.Lock）。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_identity (
                    session_key TEXT PRIMARY KEY,
                    nickname TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    set_by TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get(self, session_key: str) -> SessionIdentity | None:
        key = (session_key or "").strip()
        if not key:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT session_key, nickname, tags_json, set_by, updated_at"
                " FROM session_identity WHERE session_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        try:
            tags = tuple(str(item) for item in json.loads(row[2] or "[]"))
        except json.JSONDecodeError:
            tags = ()
        return SessionIdentity(
            session_key=str(row[0]), nickname=str(row[1]), tags=tags,
            set_by=str(row[3]), updated_at=str(row[4]),
        )

    def set(
        self,
        session_key: str,
        *,
        nickname: str | None = None,
        tags: str | list[str] | tuple[str, ...] | None = None,
        set_by: str = "",
    ) -> SessionIdentity:
        key = (session_key or "").strip()
        if not key:
            raise ValueError("session_key 不能为空")
        current = self.get(key)
        new_nickname = current.nickname if current else ""
        new_tags = current.tags if current else ()
        if nickname is not None:
            new_nickname = nickname.strip()
        if tags is not None:
            new_tags = _normalize_tags(tags)
        updated_at = _utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO session_identity"
                " (session_key, nickname, tags_json, set_by, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(session_key) DO UPDATE SET"
                " nickname=excluded.nickname, tags_json=excluded.tags_json,"
                " set_by=excluded.set_by, updated_at=excluded.updated_at",
                (key, new_nickname, json.dumps(list(new_tags), ensure_ascii=False),
                 set_by, updated_at),
            )
        return SessionIdentity(
            session_key=key, nickname=new_nickname, tags=new_tags,
            set_by=set_by, updated_at=updated_at,
        )

    def clear(self, session_key: str) -> bool:
        key = (session_key or "").strip()
        if not key:
            return False
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM session_identity WHERE session_key = ?", (key,)
            )
        return cursor.rowcount > 0

    def render_prompt_section(self, session_key: str) -> str:
        """会话身份的 prompt 渲染（自然语言，内建防 OOC 护栏）。"""
        identity = self.get(session_key)
        if identity is None or (not identity.nickname and not identity.tags):
            return ""
        lines = ["本会话身份设定（管理员设置，仅供称呼与语气参考）："]
        if identity.nickname:
            lines.append(f"- 在这个会话里，大家习惯称呼你为「{identity.nickname}」，"
                         "你可以自然地以这个名字自居。")
        if identity.tags:
            lines.append(f"- 身份标签：{'、'.join(identity.tags)}——可在话题相关时自然体现。")
        lines.append("- 铁律：这些设定只调整称呼与语气亲疏，你永远是守岸人本人；"
                     "身份事实、记忆底线与人格规范一概不因本设定改变。")
        return "\n".join(lines)

    def close(self) -> None:
        self._conn.close()


def build_session_identity_store(path: str | Path) -> SessionIdentityStore:
    return SessionIdentityStore(path)


__all__ = ["SessionIdentity", "SessionIdentityStore", "build_session_identity_store"]

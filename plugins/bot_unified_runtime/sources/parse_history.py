"""链接解析历史存储：SQLite 持久化 + 查询。

每次成功解析（含降级卡片）都会落一条记录，供 ``/bot parse`` 查询。
数据在 git 忽略的 ``data/`` 下，不进入任何 LLM 上下文。
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import CapabilityResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS parse_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    sender_id TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    item_id TEXT NOT NULL DEFAULT '',
    item_kind TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    parse_depth TEXT NOT NULL DEFAULT '',
    body_preview TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_parse_history_created
    ON parse_history (created_at DESC);
"""


@dataclass(frozen=True)
class ParseHistoryEntry:
    platform: str
    item_kind: str
    title: str
    url: str
    parse_depth: str
    created_at: str
    body_preview: str = ""
    item_id: str = ""


class SQLiteParseHistoryStore:
    def __init__(self, db_path: str | Path, *, max_items: int = 2000) -> None:
        self.db_path = Path(db_path)
        self.max_items = max(100, int(max_items))
        self._lock = threading.Lock()
        if str(self.db_path).strip():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(_SCHEMA)
        connection.commit()

    def record(
        self,
        *,
        request_id: str,
        session_id: str = "",
        sender_id: str = "",
        platform: str = "",
        item_id: str = "",
        item_kind: str = "",
        title: str = "",
        url: str = "",
        parse_depth: str = "",
        body_preview: str = "",
    ) -> None:
        if not str(self.db_path).strip():
            return
        with self._lock:
            try:
                connection = self._connect()
                try:
                    self._ensure_schema(connection)
                    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    connection.execute(
                        "INSERT INTO parse_history "
                        "(request_id, session_id, sender_id, platform, item_id, "
                        "item_kind, title, url, parse_depth, body_preview, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            request_id,
                            session_id,
                            sender_id,
                            platform,
                            item_id,
                            item_kind,
                            title[:200],
                            url[:1000],
                            parse_depth,
                            body_preview[:500],
                            now,
                        ),
                    )
                    connection.execute(
                        "DELETE FROM parse_history WHERE id NOT IN "
                        "(SELECT id FROM parse_history ORDER BY id DESC LIMIT ?)",
                        (self.max_items,),
                    )
                    connection.commit()
                finally:
                    connection.close()
            except Exception:  # noqa: BLE001 - 历史存储失败不影响主链路。
                return

    def list_recent(self, *, limit: int = 10) -> list[ParseHistoryEntry]:
        if not str(self.db_path).strip() or not self.db_path.exists():
            return []
        with self._lock:
            try:
                connection = self._connect()
                try:
                    self._ensure_schema(connection)
                    rows = connection.execute(
                        "SELECT platform, item_kind, title, url, parse_depth, "
                        "created_at, body_preview, item_id "
                        "FROM parse_history ORDER BY id DESC LIMIT ?",
                        (max(1, min(int(limit), 100)),),
                    ).fetchall()
                finally:
                    connection.close()
            except Exception:  # noqa: BLE001
                return []
        return [
            ParseHistoryEntry(
                platform=row[0],
                item_kind=row[1],
                title=row[2],
                url=row[3],
                parse_depth=row[4],
                created_at=row[5],
                body_preview=row[6],
                item_id=row[7],
            )
            for row in rows
        ]


class InMemoryParseHistoryStore:
    """内存版：不落盘，进程内可查（测试与关闭持久化时用）。"""

    def __init__(self, *, max_items: int = 200) -> None:
        self.max_items = max(100, int(max_items))
        self._entries: list[ParseHistoryEntry] = []

    def record(self, **kwargs: object) -> None:
        self._entries.append(
            ParseHistoryEntry(
                platform=str(kwargs.get("platform") or ""),
                item_kind=str(kwargs.get("item_kind") or ""),
                title=str(kwargs.get("title") or ""),
                url=str(kwargs.get("url") or ""),
                parse_depth=str(kwargs.get("parse_depth") or ""),
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                body_preview=str(kwargs.get("body_preview") or "")[:500],
                item_id=str(kwargs.get("item_id") or ""),
            )
        )
        if len(self._entries) > self.max_items:
            self._entries = self._entries[-self.max_items :]

    def list_recent(self, *, limit: int = 10) -> list[ParseHistoryEntry]:
        return list(reversed(self._entries[-max(1, min(int(limit), 100)) :]))


def build_parse_history_store(config: object) -> object:
    """按配置构建：启用且给路径 → SQLite；否则内存。"""
    enabled = bool(getattr(config, "bot_parse_history_enabled", True))
    db_path = str(getattr(config, "bot_parse_history_db_path", "") or "")
    max_items = int(getattr(config, "bot_parse_history_max_items", 2000))
    if enabled and db_path:
        return SQLiteParseHistoryStore(db_path, max_items=max_items)
    return InMemoryParseHistoryStore(max_items=max_items)


def build_parse_history_result(
    store: Any,
    *,
    request_id: str = "",
    query: str = "",
) -> CapabilityResult:
    """`/bot parse [数量]` 查询结果（CapabilityResult）。"""
    from plugins.bot_unified_runtime.contracts import (
        PrivacyLevel,
        RiskLevel,
    )

    limit = 10
    tokens = (query or "").split()
    for token in tokens:
        if token.isdigit():
            limit = int(token)
            break
    entries = store.list_recent(limit=limit)
    if not entries:
        return CapabilityResult(
            request_id=request_id or "parse-history",
            capability_id="bot.parse",
            kind="text",
            title="解析历史",
            body="还没有解析记录。发一条支持的链接试试。",
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["parse_history", "parse_history_empty"],
        )
    lines = [f"最近解析记录（{len(entries)} 条）："]
    for entry in entries:
        lines.append(
            f"- [{entry.platform}] {entry.title[:40]}（{entry.parse_depth}，"
            f"{entry.created_at[:16].replace('T', ' ')}）\n  {entry.url[:120]}"
        )
    return CapabilityResult(
        request_id=request_id or "parse-history",
        capability_id="bot.parse",
        kind="text",
        title="解析历史",
        body="\n".join(lines),
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        audit_tags=["parse_history", f"parse_history_count:{len(entries)}"],
    )

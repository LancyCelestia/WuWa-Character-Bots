"""媒体档案库：把 chat_message_id 与视频文件、平台元数据、CC 字幕、感知简报关联存档。

聊天链路在机器人发出视频（bot_sent）、用户发来视频（user_sent）、链接解析出视频但未下载
（parsed_only）时写入档案；用户回复某条视频消息追问时按 chat_message_id 反查，命中即可
复用已缓存的感知简报，避免重复分析。进程内单实例，写入时顺带 TTL/FIFO 剪枝。

设计约束：媒体记忆缺失不阻断聊天——写路径失败记 warning 后吞掉（register 返回 ""、
update_brief/touch/prune 静默），读路径失败/未命中返回 None；绝不向调用方抛异常。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from plugins.bot_unified_runtime.contracts.runtime import StrictBaseModel

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "data/media_registry.sqlite3"
_DEFAULT_TTL_SECONDS = 604800
_DEFAULT_MAX_ROWS = 5000

_COLUMNS = (
    "media_id",
    "chat_message_id",
    "session_id",
    "source_kind",
    "platform",
    "item_id",
    "canonical_url",
    "title",
    "creator_name",
    "duration_ms",
    "local_path",
    "subtitle_text",
    "brief_text",
    "brief_signals",
    "created_at",
    "last_accessed_at",
)

# 重复注册时允许被新记录的非空值原位覆盖的文本字段（其余列以首次注册为准）。
_MERGEABLE_TEXT_FIELDS = (
    "source_kind",
    "platform",
    "item_id",
    "canonical_url",
    "title",
    "creator_name",
    "local_path",
    "subtitle_text",
    "brief_text",
    "brief_signals",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_assets (
    media_id TEXT PRIMARY KEY,
    chat_message_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    item_id TEXT NOT NULL DEFAULT '',
    canonical_url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    creator_name TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER,
    local_path TEXT NOT NULL DEFAULT '',
    subtitle_text TEXT NOT NULL DEFAULT '',
    brief_text TEXT NOT NULL DEFAULT '',
    brief_signals TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL DEFAULT 0,
    last_accessed_at INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_media_assets_message_session
    ON media_assets (chat_message_id, session_id)
    WHERE chat_message_id <> '';
CREATE INDEX IF NOT EXISTS idx_media_assets_session_created
    ON media_assets (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_assets_last_accessed
    ON media_assets (last_accessed_at);
"""

_INSERT_SQL = (
    f"INSERT INTO media_assets ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _COLUMNS)})"
)


class MediaAssetRecord(StrictBaseModel):
    media_id: str
    chat_message_id: str  # 锚点：bot_sent=发送回执 message_id；user_sent=来消息 id
    session_id: str
    source_kind: str  # "bot_sent" | "user_sent" | "parsed_only"
    platform: str = ""
    item_id: str = ""
    canonical_url: str = ""
    title: str = ""
    creator_name: str = ""
    duration_ms: int | None = None
    local_path: str = ""
    subtitle_text: str = ""
    brief_text: str = ""
    brief_signals: str = ""  # JSON 字符串，如 {"frames": true, "asr": false}
    created_at: int = 0  # UTC 秒；0 时自动 int(time.time())
    last_accessed_at: int = 0  # 0 时自动等于 created_at


class SQLiteMediaRegistry:
    """SQLite 版媒体档案库：进程内单实例，持久连接 + 线程锁保证并发安全。"""

    def __init__(
        self,
        db_path: str | Path,
        *,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        max_rows: int = _DEFAULT_MAX_ROWS,
    ) -> None:
        self.db_path = Path(db_path)
        self.ttl_seconds = int(ttl_seconds)
        self.max_rows = max(1, int(max_rows))
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if str(self.db_path).strip():
            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                logger.warning("媒体档案库目录创建失败：%s", self.db_path, exc_info=True)

    def register(self, record: MediaAssetRecord) -> str:
        """落一条档案；同 (chat_message_id, session_id) 已存在则原位更新并复用 media_id。"""
        now = int(time.time())
        created_at = int(record.created_at) if record.created_at else now
        last_accessed_at = (
            int(record.last_accessed_at) if record.last_accessed_at else created_at
        )
        row_values = {
            "chat_message_id": record.chat_message_id,
            "session_id": record.session_id,
            "source_kind": record.source_kind,
            "platform": record.platform,
            "item_id": record.item_id,
            "canonical_url": record.canonical_url,
            "title": record.title,
            "creator_name": record.creator_name,
            "duration_ms": record.duration_ms,
            "local_path": record.local_path,
            "subtitle_text": record.subtitle_text,
            "brief_text": record.brief_text,
            "brief_signals": record.brief_signals,
            "created_at": created_at,
            "last_accessed_at": last_accessed_at,
        }
        with self._lock:
            try:
                connection = self._get_connection()
                existing = connection.execute(
                    "SELECT * FROM media_assets "
                    "WHERE chat_message_id = ? AND session_id = ? LIMIT 1",
                    (record.chat_message_id, record.session_id),
                ).fetchone()
                if existing is not None:
                    media_id = self._merge_existing(
                        connection, existing, record, last_accessed_at, now
                    )
                    connection.commit()
                    return media_id
                media_id = str(record.media_id) or uuid.uuid4().hex
                connection.execute(
                    _INSERT_SQL,
                    [media_id] + [row_values[name] for name in _COLUMNS[1:]],
                )
                # 每次写入顺带剪枝，档案库不无限膨胀。
                self._prune_locked(connection, now)
                connection.commit()
                return media_id
            except Exception:
                logger.warning(
                    "媒体档案库写入失败（chat_message_id=%s）",
                    record.chat_message_id,
                    exc_info=True,
                )
                return ""

    def lookup_by_message_id(self, message_id: str) -> MediaAssetRecord | None:
        """按 chat_message_id 反查最新一条；命中即 touch 刷新 last_accessed_at。"""
        with self._lock:
            try:
                connection = self._get_connection()
                row = connection.execute(
                    "SELECT * FROM media_assets WHERE chat_message_id = ? "
                    "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    (message_id,),
                ).fetchone()
                if row is None:
                    return None
                connection.execute(
                    "UPDATE media_assets SET last_accessed_at = ? WHERE media_id = ?",
                    (int(time.time()), str(row["media_id"])),
                )
                connection.commit()
                return _record_from_row(row)
            except Exception:
                logger.warning(
                    "媒体档案库反查失败（message_id=%s）", message_id, exc_info=True
                )
                return None

    def lookup_recent_in_session(
        self, session_id: str, *, within_seconds: int
    ) -> MediaAssetRecord | None:
        """取会话内 created_at 距今 within_seconds 之内最新的一条；命中即 touch。"""
        now = int(time.time())
        with self._lock:
            try:
                connection = self._get_connection()
                row = connection.execute(
                    "SELECT * FROM media_assets WHERE session_id = ? "
                    "AND created_at >= ? "
                    "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    (session_id, now - max(0, int(within_seconds))),
                ).fetchone()
                if row is None:
                    return None
                connection.execute(
                    "UPDATE media_assets SET last_accessed_at = ? WHERE media_id = ?",
                    (now, str(row["media_id"])),
                )
                connection.commit()
                return _record_from_row(row)
            except Exception:
                logger.warning(
                    "媒体档案库会话查询失败（session_id=%s）", session_id, exc_info=True
                )
                return None

    def update_brief(self, media_id: str, brief_text: str, brief_signals: str) -> None:
        """回填感知简报；media_id 不存在或失败时静默（warning），不阻断聊天。"""
        with self._lock:
            try:
                connection = self._get_connection()
                connection.execute(
                    "UPDATE media_assets SET brief_text = ?, brief_signals = ? "
                    "WHERE media_id = ?",
                    (brief_text, brief_signals, media_id),
                )
                connection.commit()
            except Exception:
                logger.warning(
                    "媒体档案库简报更新失败（media_id=%s）", media_id, exc_info=True
                )

    def touch(self, media_id: str) -> None:
        with self._lock:
            try:
                connection = self._get_connection()
                connection.execute(
                    "UPDATE media_assets SET last_accessed_at = ? WHERE media_id = ?",
                    (int(time.time()), media_id),
                )
                connection.commit()
            except Exception:
                logger.warning(
                    "媒体档案库 touch 失败（media_id=%s）", media_id, exc_info=True
                )

    def prune(self, *, now: int | None = None) -> int:
        """先按 TTL 删冷数据，再按 created_at 最旧优先删到 max_rows 内；返回删除条数。"""
        current = int(time.time()) if now is None else int(now)
        with self._lock:
            try:
                connection = self._get_connection()
                removed = self._prune_locked(connection, current)
                connection.commit()
                return removed
            except Exception:
                logger.warning("媒体档案库剪枝失败", exc_info=True)
                return 0

    def close(self) -> None:
        with self._lock:
            if self._conn is None:
                return
            try:
                self._conn.close()
            except Exception:
                logger.warning("媒体档案库连接关闭失败", exc_info=True)
            finally:
                self._conn = None

    def _merge_existing(
        self,
        connection: sqlite3.Connection,
        existing: sqlite3.Row,
        record: MediaAssetRecord,
        last_accessed_at: int,
        now: int,
    ) -> str:
        """原位合并：非空文本字段/duration_ms 覆盖，last_accessed 只进不退。"""
        media_id = str(existing["media_id"])
        merged = {name: existing[name] for name in _COLUMNS}
        for field in _MERGEABLE_TEXT_FIELDS:
            value = str(getattr(record, field) or "")
            if value:
                merged[field] = value
        if record.duration_ms is not None:
            merged["duration_ms"] = int(record.duration_ms)
        merged["last_accessed_at"] = max(
            int(existing["last_accessed_at"] or 0), last_accessed_at
        )
        assignments = ", ".join(f"{name} = ?" for name in _COLUMNS)
        connection.execute(
            f"UPDATE media_assets SET {assignments} WHERE media_id = ?",
            [merged[name] for name in _COLUMNS] + [media_id],
        )
        self._prune_locked(connection, now)
        return media_id

    def _prune_locked(self, connection: sqlite3.Connection, now: int) -> int:
        removed = 0
        cursor = connection.execute(
            "DELETE FROM media_assets WHERE last_accessed_at < ?",
            (now - self.ttl_seconds,),
        )
        removed += max(0, cursor.rowcount)
        cursor = connection.execute(
            """
            DELETE FROM media_assets
            WHERE media_id NOT IN (
                SELECT media_id FROM media_assets
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
            )
            """,
            (self.max_rows,),
        )
        removed += max(0, cursor.rowcount)
        return removed

    def _get_connection(self) -> sqlite3.Connection:
        """惰性建持久连接（调用方须已持有 self._lock）。"""
        if self._conn is None:
            connection = sqlite3.connect(
                self.db_path, timeout=10, check_same_thread=False
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)
            connection.commit()
            self._conn = connection
        return self._conn


def _record_from_row(row: sqlite3.Row) -> MediaAssetRecord:
    duration = row["duration_ms"]
    return MediaAssetRecord(
        media_id=str(row["media_id"]),
        chat_message_id=str(row["chat_message_id"]),
        session_id=str(row["session_id"]),
        source_kind=str(row["source_kind"]),
        platform=str(row["platform"]),
        item_id=str(row["item_id"]),
        canonical_url=str(row["canonical_url"]),
        title=str(row["title"]),
        creator_name=str(row["creator_name"]),
        duration_ms=int(duration) if duration is not None else None,
        local_path=str(row["local_path"]),
        subtitle_text=str(row["subtitle_text"]),
        brief_text=str(row["brief_text"]),
        brief_signals=str(row["brief_signals"]),
        created_at=int(row["created_at"]),
        last_accessed_at=int(row["last_accessed_at"]),
    )


def _resolve_runtime_path(value: str) -> Path:
    """data/... → 配置的 Runtime 数据根（复用 runtime_paths 规则）。"""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    import sys

    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        from scripts.runtime_paths import runtime_path

        return runtime_path(value)
    except Exception:
        logger.warning(
            "runtime_path 解析失败，退回源码树 data/（value=%s）", value, exc_info=True
        )
        return project_root / path


def build_media_registry(
    config: object | None,
    *,
    ttl_seconds: int | None = None,
    max_rows: int | None = None,
) -> SQLiteMediaRegistry | None:
    """按配置构建；config 为 None 时用默认路径构造（便于测试）。"""
    raw_path = (
        str(getattr(config, "bot_media_registry_path", "") or "").strip()
        or _DEFAULT_DB_PATH
    )
    effective_ttl = int(
        ttl_seconds
        if ttl_seconds is not None
        else getattr(
            config, "bot_media_registry_ttl_seconds", _DEFAULT_TTL_SECONDS
        )
    )
    effective_rows = int(
        max_rows
        if max_rows is not None
        else getattr(config, "bot_media_registry_max_rows", _DEFAULT_MAX_ROWS)
    )
    try:
        return SQLiteMediaRegistry(
            _resolve_runtime_path(raw_path),
            ttl_seconds=effective_ttl,
            max_rows=effective_rows,
        )
    except Exception:
        logger.warning("媒体档案库初始化失败（path=%s）", raw_path, exc_info=True)
        return None

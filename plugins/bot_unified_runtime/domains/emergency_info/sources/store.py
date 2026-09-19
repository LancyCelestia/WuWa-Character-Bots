"""紧急信息 SQLite 存储（本地持久层：幂等落库 + 状态裁决 + 保留期裁剪）。

样板出处（九个统一自证）：
- 库文件形态=「每操作独立连接的轻量 SQLite 库」，抄
  `domains/assistant/campus/campus_store.py:30-42`（`CampusStore`）；
- 采集侧幂等键 = `(source_id, external_id)` UNIQUE，抄 E5 §4.3 的口径
  （campus 用 `message_id TEXT PRIMARY KEY` 同族思路，`campus_store.py:17`）；
- 状态 CHECK 约束与「只从 pending 转正」的 SQL 守卫，抄
  `domains/chat_reply/character/quirks.py:157-176`（建表 CHECK）与
  `:292-300`（`UPDATE ... WHERE quirk_id=? AND status='pending_review'`）；
- `date_key` 列 + 保留期裁剪防无界增长，抄 `campus_store.py:23-26/:101-109`；
- 缺省库路径经 `scripts/runtime_paths.py` 重映射到 Runtime 数据根，抄
  `domains/chat_reply/character/persona_service.py:738-752`
  （`build_persona_service`：`db_path is None → runtime_path(DEFAULT_DB_PATH)`），
  对应铁律 6 与 `bot_campus_db_path` 先例（config.py:424 + path_fields :1161）。

本模块绝不发送任何对外消息，也绝不 import LLM/网络面。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyLevel,
    EmergencyStatus,
    as_utc,
    build_emergency_item,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    date_key_of,
)

#: 缺省库路径（相对 `data/`，装配时必须经 `runtime_path` 重映射，不得落源码树）。
DEFAULT_DB_PATH = "data/emergency_info.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS emergency_items (
    item_id     TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    color_label TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    expires_at  TEXT,
    date_key    TEXT NOT NULL,
    level       TEXT,
    credibility REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewed_by TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_emergency_items_source
    ON emergency_items(source_id, external_id);
CREATE INDEX IF NOT EXISTS idx_emergency_items_status
    ON emergency_items(status, occurred_at);
CREATE INDEX IF NOT EXISTS idx_emergency_items_date
    ON emergency_items(date_key);
"""

_SELECT_COLUMNS = (
    "item_id, source_id, source_kind, external_id, title, body, url, "
    "color_label, occurred_at, fetched_at, expires_at, level, credibility, "
    "status, reviewed_by, reviewed_at"
)


def _format_utc(moment: datetime) -> str:
    """统一落库格式（UTC ISO，字典序即时间序）；naive 视作 UTC。

    逐字同构 `quirks.py:57-62 _format_utc`。
    """
    return as_utc(moment).isoformat()


def _row_to_item(row: sqlite3.Row) -> EmergencyItem | None:
    """行 → 条目；库里存量行不合契约时返回 None（D-1：不硬凑）。

    `date_key` 是本表的裁剪辅助列，不属于契约，故不塞进 payload。
    """
    payload = {key: value for key, value in dict(row).items() if key != "date_key"}
    if payload.get("level") in (None, ""):
        payload["level"] = None
    if payload.get("status") in (None, ""):
        payload["status"] = EmergencyStatus.PENDING.value
    return build_emergency_item(payload)


class EmergencyStore:
    """紧急信息条目库：幂等落库、审核裁决写入、按状态读回、保留期裁剪。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    # ------------------------------------------------------------ 写入

    def upsert_item(self, item: EmergencyItem) -> bool:
        """幂等插入：同 item_id 或同 (source_id, external_id) 重复 ⇒ False 不覆盖。

        采集器重跑、SnowLuma 重连重发同一事件都只会落一次（同 campus 的
        message_id 幂等语义）；本函数**不做**「重复即更新」，因为紧急条目的
        状态一旦被重复导入覆盖回 pending，等于把已过审条目悄悄撤回，风险更大。
        """
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO emergency_items (
                        item_id, source_id, source_kind, external_id,
                        title, body, url, color_label,
                        occurred_at, fetched_at, expires_at, date_key,
                        level, credibility, status, reviewed_by, reviewed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.item_id,
                        item.source_id,
                        item.source_kind,
                        item.external_id,
                        item.title,
                        item.body,
                        item.url,
                        item.color_label,
                        _format_utc(item.occurred_at),
                        _format_utc(item.fetched_at),
                        _format_utc(item.expires_at) if item.expires_at else None,
                        date_key_of(item.occurred_at),
                        item.level.value if item.level is not None else None,
                        float(item.credibility),
                        item.status.value,
                        item.reviewed_by,
                        _format_utc(item.reviewed_at) if item.reviewed_at else None,
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return cursor.rowcount > 0

    def apply_review(
        self,
        item_id: str,
        *,
        target: EmergencyStatus,
        reviewer_id: str,
        at: datetime,
    ) -> bool:
        """状态裁决：只改 pending 行（守卫与 quirks.approve 同型）。"""
        if target is EmergencyStatus.PENDING:
            return False
        reviewer = str(reviewer_id or "").strip()
        if not reviewer:
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE emergency_items SET status = ?, reviewed_by = ?, reviewed_at = ?"
                " WHERE item_id = ? AND status = 'pending'",
                (target.value, reviewer, _format_utc(at), str(item_id or "").strip()),
            )
        return cursor.rowcount > 0

    def set_level(self, item_id: str, *, level: EmergencyLevel) -> bool:
        """把定级结果写回库：仅过审条目可写（D-8「approve 后才参与定级」的存储侧锁）。"""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE emergency_items SET level = ?"
                " WHERE item_id = ? AND status = 'approved'",
                (level.value, str(item_id or "").strip()),
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------ 读回

    def get(self, item_id: str) -> EmergencyItem | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM emergency_items WHERE item_id = ?",
                (str(item_id or "").strip(),),
            ).fetchone()
        return None if row is None else _row_to_item(row)

    def list_by_status(
        self, status: EmergencyStatus, *, limit: int = 50
    ) -> list[EmergencyItem]:
        """按状态读回（新→旧）；limit 非正即空表，不放开成全表扫描。"""
        cap = int(limit)
        if cap <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM emergency_items"
                " WHERE status = ? ORDER BY occurred_at DESC, rowid DESC LIMIT ?",
                (status.value, cap),
            ).fetchall()
        items = [_row_to_item(row) for row in rows]
        return [item for item in items if item is not None]

    # ------------------------------------------------------------ 卫生

    def prune(self, *, keep_days: int = 90, now: datetime | None = None) -> int:
        """删除保留期外的旧条目，返回删除条数（防库无界增长，抄 campus 同族）。"""
        current = (now or datetime.now().astimezone()).astimezone()
        cutoff = (current - timedelta(days=max(1, int(keep_days)))).date().isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM emergency_items WHERE date_key < ?", (cutoff,)
            )
        return cursor.rowcount


def build_emergency_store(db_path: str | Path | None = None) -> EmergencyStore:
    """装配入口：缺省路径经 `runtime_path` 重映射到 Runtime 数据根（不入源码树）。

    逐字同构 `persona_service.py:738-752`。配置键 `bot_emergency_db_path`
    属 B8/B9 合流席的 config.py 落地请求（且必须进 `path_fields` 重映射表）。
    """
    if db_path is None:
        from scripts.runtime_paths import runtime_path

        db_path = runtime_path(DEFAULT_DB_PATH)
    return EmergencyStore(db_path)


__all__ = [
    "DEFAULT_DB_PATH",
    "EmergencyStore",
    "build_emergency_store",
]

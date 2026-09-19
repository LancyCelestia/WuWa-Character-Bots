"""V2.1 记忆存储层（MemoryStoreV21）：四表 schema + 墓碑 + 绑定 + 投影。

重建说明（2026-09-18）：原文件在板块归类事故中被垫片覆写，本文件依据
tests/test_memory_service_v21.py（41 例契约）+ docs/db-owners.md §二登记
+ docs/design/v21r2-v2-memory-log.md 设计要点重建。

表（均 ensure_schema 幂等建，WAL+busy_timeout=1000ms）：
- memory_entries_v21：记忆行，永不 DELETE（遗忘=status 翻 forgotten）
- memory_tombstones_v21：墓碑（遗忘/拒绝双记录），重建/恢复不复活的依据
- memory_identity_bindings_v21：跨平台身份绑定（只增不改）
- memory_index_v21：可再生投影（rebuild_projection 重建，可整表清）

并发口径（2026-09-18 修复）：连接以 check_same_thread=False 共享，因此
**所有**公开方法（含读路径）都必须持同一把可重入锁；此前读路径裸用连接，
8 线程并发 propose 时抛 sqlite3.InterfaceError('not an error')/API misuse。
锁用 RLock，允许同线程内嵌套调用（如 insert_entry → upsert_index_row）。
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS memory_entries_v21 (
        memory_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        session_id TEXT NOT NULL DEFAULT 'global',
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending_review',
        version INTEGER NOT NULL DEFAULT 1,
        text TEXT NOT NULL,
        confidence REAL NOT NULL,
        sensitivity TEXT NOT NULL DEFAULT 'personal',
        source TEXT NOT NULL DEFAULT 'manual',
        source_event_id TEXT NOT NULL DEFAULT '',
        correction_of TEXT,
        ttl_seconds INTEGER,
        expires_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        used_at TEXT,
        reviewed_by TEXT,
        reviewed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_tombstones_v21 (
        memory_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        original_version INTEGER NOT NULL,
        forgotten_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_identity_bindings_v21 (
        identity_key TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_index_v21 (
        memory_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        status TEXT NOT NULL
    )
    """,
    # 幂等核心：同 source_event_id 只允许一行（空 source_event_id 不参与）。
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_memory_owner_source_event
        ON memory_entries_v21 (owner_id, source_event_id)
        WHERE source_event_id <> ''
    """,
)


class MemoryStoreUnavailable(RuntimeError):
    """存储层不可用（连接/约束/磁盘等）——由服务层转译或上抛。"""


class MemoryStoreV21:
    """记忆行存储：SQL 层即排除墓碑（读路径防复活的第一道闸）。"""

    def __init__(self, path: str | Any) -> None:
        self._path = str(path)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=1000")
        self._connection.row_factory = sqlite3.Row
        self.ensure_schema()

    # ---------------------------------------------------------------- 基础

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def ensure_schema(self) -> None:
        with self._lock:
            for statement in _SCHEMA_STATEMENTS:
                self._connection.execute(statement)
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    # ---------------------------------------------------------------- 条目

    def insert_entry(self, entry: dict[str, Any]) -> str | None:
        """插入记忆行；同 (owner, source_event_id) 命中唯一索引 → 返回既有 id。

        返回 None 表示幂等合流（并发/重复 propose 收敛到已有行）。
        """
        with self._lock:
            try:
                self._connection.execute(
                    """
                    INSERT INTO memory_entries_v21 (
                        memory_id, owner_id, session_id, kind, status, version,
                        text, confidence, sensitivity, source, source_event_id,
                        correction_of, ttl_seconds, expires_at,
                        created_at, updated_at
                    ) VALUES (
                        :memory_id, :owner_id, :session_id, :kind, :status, :version,
                        :text, :confidence, :sensitivity, :source, :source_event_id,
                        :correction_of, :ttl_seconds, :expires_at,
                        :created_at, :updated_at
                    )
                    """,
                    entry,
                )
                self._connection.commit()
            except sqlite3.IntegrityError:
                self._connection.rollback()
                row = self._connection.execute(
                    "SELECT memory_id FROM memory_entries_v21 "
                    "WHERE owner_id = :owner_id AND source_event_id = :source_event_id",
                    {
                        "owner_id": entry["owner_id"],
                        "source_event_id": entry["source_event_id"],
                    },
                ).fetchone()
                if row is None:
                    raise MemoryStoreUnavailable("记忆行插入冲突且无法定位既有行")
                return str(row["memory_id"])
        self.upsert_index_row(
            entry["memory_id"], entry["owner_id"], entry["session_id"], entry["status"]
        )
        return None

    def get_entry(self, memory_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM memory_entries_v21 WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def update_entry(self, memory_id: str, fields: dict[str, Any]) -> bool:
        if not fields:
            return False
        assignments = ", ".join(f"{name} = :{name}" for name in fields)
        fields = {**fields, "memory_id": memory_id}
        with self._lock:
            cursor = self._connection.execute(
                f"UPDATE memory_entries_v21 SET {assignments} WHERE memory_id = :memory_id",
                fields,
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def list_entries(
        self,
        *,
        owner_id: str,
        session_ids: tuple[str, ...],
        statuses: tuple[str, ...] = ("active",),
    ) -> list[dict[str, Any]]:
        """owner+session 可见行（SQL 层联墓碑表排除——恢复/复活也压不住）。"""
        placeholders_sessions = ", ".join("?" for _ in session_ids)
        placeholders_status = ", ".join("?" for _ in statuses)
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT e.* FROM memory_entries_v21 e
                WHERE e.owner_id = ?
                  AND e.session_id IN ({sessions})
                  AND e.status IN ({statuses})
                  AND NOT EXISTS (
                      SELECT 1 FROM memory_tombstones_v21 t
                      WHERE t.memory_id = e.memory_id
                  )
                ORDER BY e.created_at ASC, e.memory_id ASC
                """.format(
                    sessions=placeholders_sessions or "''",
                    statuses=placeholders_status or "''",
                ),
                (owner_id, *session_ids, *statuses),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_entries_by_owner(self, owner_id: str) -> list[dict[str, Any]]:
        """审计面：含 forgotten——历史留痕（不含已拒绝入不了库的行）。"""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT e.* FROM memory_entries_v21 e
                WHERE e.owner_id = ?
                ORDER BY e.created_at ASC, e.memory_id ASC
                """,
                (owner_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_all_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM memory_entries_v21 ORDER BY created_at ASC, memory_id ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------------------------------------------------------- 墓碑

    def insert_tombstone(self, tombstone: dict[str, Any]) -> bool:
        """插入墓碑（幂等：同 id 重复插返回 False）。"""
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO memory_tombstones_v21 (
                    memory_id, owner_id, reason, original_version,
                    forgotten_by, created_at
                ) VALUES (
                    :memory_id, :owner_id, :reason, :original_version,
                    :forgotten_by, :created_at
                )
                """,
                tombstone,
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def has_tombstone(self, memory_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM memory_tombstones_v21 WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        return row is not None

    def list_tombstones(self, owner_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM memory_tombstones_v21 WHERE owner_id = ? "
                "ORDER BY created_at ASC, memory_id ASC",
                (owner_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_all_tombstones(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM memory_tombstones_v21 ORDER BY created_at ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------------------------------------------------------- 投影

    def upsert_index_row(
        self, memory_id: str, owner_id: str, session_id: str, status: str
    ) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO memory_index_v21
                    (memory_id, owner_id, session_id, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (memory_id) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    session_id = excluded.session_id,
                    status = excluded.status
                """,
                (memory_id, owner_id, session_id, status),
            )
            self._connection.commit()

    def remove_index_row(self, memory_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM memory_index_v21 WHERE memory_id = ?", (memory_id,)
            )
            self._connection.commit()

    def index_contains(self, memory_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM memory_index_v21 WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        return row is not None

    def clear_index(self) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM memory_index_v21")
            self._connection.commit()

    # ---------------------------------------------------------------- 绑定

    def upsert_binding(
        self, identity_key: str, owner_id: str, created_by: str, created_at: str
    ) -> bool:
        """绑定只增不改：同 identity_key 已有不同 owner 时不覆盖（先到先得）。"""
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO memory_identity_bindings_v21
                    (identity_key, owner_id, created_by, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (identity_key, owner_id, created_by, created_at),
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def resolve_binding(self, identity_key: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT owner_id FROM memory_identity_bindings_v21 WHERE identity_key = ?",
                (identity_key,),
            ).fetchone()
        return str(row["owner_id"]) if row is not None else None

    def list_bindings(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM memory_identity_bindings_v21 ORDER BY created_at ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------------------------------------------------------- 备份恢复

    def backup_tables(self) -> dict[str, list[dict[str, Any]]]:
        """读取四表全量（restore_from 用；行序稳定保证重建等价）。"""
        tables: dict[str, list[dict[str, Any]]] = {}
        with self._lock:
            for table in (
                "memory_entries_v21",
                "memory_tombstones_v21",
                "memory_identity_bindings_v21",
                "memory_index_v21",
            ):
                tables[table] = [
                    dict(row)
                    for row in self._connection.execute(f"SELECT * FROM {table}")
                ]
        return tables

    def restore_tables(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        """整库替换（备份恢复语义）：先清后插，顺序=条目→墓碑→绑定→投影。

        批量插入必须用 executemany：命名占位符 + execute(list_of_dict) 会被
        sqlite3 当成「单条语句 + 位置参数序列」，行数≠列数时直接报
        "Incorrect number of bindings supplied"（2026-09-18 修复）。
        """
        with self._lock:
            self._connection.execute("DELETE FROM memory_index_v21")
            self._connection.execute("DELETE FROM memory_tombstones_v21")
            self._connection.execute("DELETE FROM memory_identity_bindings_v21")
            self._connection.execute("DELETE FROM memory_entries_v21")
            for table in (
                "memory_entries_v21",
                "memory_tombstones_v21",
                "memory_identity_bindings_v21",
                "memory_index_v21",
            ):
                rows = tables.get(table, [])
                if not rows:
                    continue
                names = list(rows[0].keys())
                placeholders = ", ".join(f":{name}" for name in names)
                self._connection.executemany(
                    f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders})",
                    rows,
                )
            self._connection.commit()

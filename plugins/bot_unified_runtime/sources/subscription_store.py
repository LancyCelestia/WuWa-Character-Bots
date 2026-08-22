"""订阅系统 SQLite 存储（纯 stdlib sqlite3）。

默认落盘 ``data/subscriptions.sqlite3``。所有写操作先确保建表；
异常一律抛出，方便调用方与测试明确感知失败。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from plugins.bot_unified_runtime.contracts.subscription import (
    SubscriptionCursor,
    SubscriptionDestination,
    SubscriptionSpec,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SubscriptionStore:
    def __init__(self, db_path: str = "data/subscriptions.sqlite3") -> None:
        self._db_path = str(db_path or "data/subscriptions.sqlite3")
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def _get_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            directory = os.path.dirname(os.path.abspath(self._db_path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            connection = sqlite3.connect(
                self._db_path,
                timeout=30.0,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            self._ensure_schema(connection)
            self._connection = connection
        return self._connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                target_kind TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_name TEXT NOT NULL DEFAULT '',
                destinations TEXT NOT NULL DEFAULT '[]',
                send_policy TEXT NOT NULL DEFAULT 'instant',
                digest_enabled INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                health_state TEXT NOT NULL DEFAULT 'healthy',
                failure_count INTEGER NOT NULL DEFAULT 0,
                backoff_until TEXT,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS cursors (
                spec_id TEXT PRIMARY KEY,
                last_item_id TEXT NOT NULL DEFAULT '',
                last_timestamp TEXT NOT NULL DEFAULT '',
                cursor_payload TEXT NOT NULL DEFAULT '{}',
                failure_count INTEGER NOT NULL DEFAULT 0,
                backoff_until TEXT,
                last_success_at TEXT,
                last_failure_at TEXT
            );
            CREATE TABLE IF NOT EXISTS push_log (
                spec_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                pushed_at TEXT NOT NULL,
                PRIMARY KEY (spec_id, item_id, kind)
            );
            CREATE TABLE IF NOT EXISTS digest_pending (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spec_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_digest_pending_spec_item
                ON digest_pending (spec_id, item_id);
            """
        )

    @staticmethod
    def _serialize_destinations(
        destinations: list[SubscriptionDestination],
    ) -> str:
        values = []
        for destination in destinations:
            if isinstance(destination, SubscriptionDestination):
                values.append(destination.model_dump(mode="json"))
            else:
                values.append(
                    SubscriptionDestination.model_validate(destination).model_dump(
                        mode="json"
                    )
                )
        return json.dumps(values, ensure_ascii=False)

    @staticmethod
    def _spec_from_row(row: sqlite3.Row) -> SubscriptionSpec:
        values = dict(row)
        try:
            destinations = json.loads(values.get("destinations") or "[]")
        except ValueError as exc:
            raise RuntimeError("订阅目的地 JSON 已损坏") from exc
        values["destinations"] = [
            SubscriptionDestination.model_validate(item)
            for item in destinations
        ]
        return SubscriptionSpec.model_validate(values)

    @staticmethod
    def _cursor_from_row(row: sqlite3.Row) -> SubscriptionCursor:
        values = dict(row)
        try:
            values["cursor_payload"] = json.loads(
                values.get("cursor_payload") or "{}"
            )
        except ValueError as exc:
            raise RuntimeError("订阅游标 JSON 已损坏") from exc
        return SubscriptionCursor.model_validate(values)

    def upsert_spec(self, spec: SubscriptionSpec) -> None:
        with self._lock:
            connection = self._get_connection()
            destinations_json = self._serialize_destinations(spec.destinations)
            with connection:
                connection.execute(
                    """
                    INSERT INTO subscriptions (
                        id, platform, target_kind, target_id, target_name,
                        destinations, send_policy, digest_enabled, enabled,
                        health_state, failure_count, backoff_until,
                        created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        platform = excluded.platform,
                        target_kind = excluded.target_kind,
                        target_id = excluded.target_id,
                        target_name = excluded.target_name,
                        destinations = excluded.destinations,
                        send_policy = excluded.send_policy,
                        digest_enabled = excluded.digest_enabled,
                        enabled = excluded.enabled,
                        health_state = excluded.health_state,
                        failure_count = excluded.failure_count,
                        backoff_until = excluded.backoff_until,
                        created_by = excluded.created_by,
                        created_at = excluded.created_at
                    """,
                    (
                        spec.id,
                        spec.platform,
                        spec.target_kind,
                        spec.target_id,
                        spec.target_name,
                        destinations_json,
                        spec.send_policy,
                        int(spec.digest_enabled),
                        int(spec.enabled),
                        spec.health_state,
                        int(spec.failure_count),
                        spec.backoff_until,
                        spec.created_by,
                        spec.created_at,
                    ),
                )

    def list_specs(self) -> list[SubscriptionSpec]:
        with self._lock:
            connection = self._get_connection()
            rows = connection.execute(
                "SELECT * FROM subscriptions ORDER BY id"
            ).fetchall()
            return [self._spec_from_row(row) for row in rows]

    def get_spec(self, spec_id: str) -> SubscriptionSpec | None:
        with self._lock:
            connection = self._get_connection()
            row = connection.execute(
                "SELECT * FROM subscriptions WHERE id = ?", (spec_id,)
            ).fetchone()
            return self._spec_from_row(row) if row is not None else None

    def delete_spec(self, spec_id: str) -> bool:
        with self._lock:
            connection = self._get_connection()
            with connection:
                deleted = connection.execute(
                    "DELETE FROM subscriptions WHERE id = ?", (spec_id,)
                ).rowcount
                if not deleted:
                    return False
                connection.execute(
                    "DELETE FROM cursors WHERE spec_id = ?", (spec_id,)
                )
                connection.execute(
                    "DELETE FROM push_log WHERE spec_id = ?", (spec_id,)
                )
                connection.execute(
                    "DELETE FROM digest_pending WHERE spec_id = ?", (spec_id,)
                )
            return bool(deleted)

    def set_spec_enabled(self, spec_id: str, enabled: bool) -> bool:
        with self._lock:
            connection = self._get_connection()
            with connection:
                updated = connection.execute(
                    "UPDATE subscriptions SET enabled = ? WHERE id = ?",
                    (int(bool(enabled)), spec_id),
                ).rowcount
            return bool(updated)

    def set_spec_health(self, spec_id: str, state: str, error: str = "") -> None:
        # 表结构与 SubscriptionSpec 一致，没有独立 error 列；error 仅保留在
        # 接口中以兼容 watcher/诊断调用，这里只更新 health_state。
        with self._lock:
            connection = self._get_connection()
            with connection:
                connection.execute(
                    "UPDATE subscriptions SET health_state = ? WHERE id = ?",
                    (state, spec_id),
                )

    def get_cursor(self, spec_id: str) -> SubscriptionCursor | None:
        with self._lock:
            connection = self._get_connection()
            row = connection.execute(
                "SELECT * FROM cursors WHERE spec_id = ?", (spec_id,)
            ).fetchone()
            return self._cursor_from_row(row) if row is not None else None

    def save_cursor(self, cursor: SubscriptionCursor) -> None:
        payload_json = json.dumps(cursor.cursor_payload, ensure_ascii=False)
        with self._lock:
            connection = self._get_connection()
            with connection:
                connection.execute(
                    """
                    INSERT INTO cursors (
                        spec_id, last_item_id, last_timestamp, cursor_payload,
                        failure_count, backoff_until, last_success_at,
                        last_failure_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(spec_id) DO UPDATE SET
                        last_item_id = excluded.last_item_id,
                        last_timestamp = excluded.last_timestamp,
                        cursor_payload = excluded.cursor_payload,
                        failure_count = excluded.failure_count,
                        backoff_until = excluded.backoff_until,
                        last_success_at = excluded.last_success_at,
                        last_failure_at = excluded.last_failure_at
                    """,
                    (
                        cursor.spec_id,
                        cursor.last_item_id,
                        cursor.last_timestamp,
                        payload_json,
                        int(cursor.failure_count),
                        cursor.backoff_until,
                        cursor.last_success_at,
                        cursor.last_failure_at,
                    ),
                )

    def record_failure(self, spec_id: str, backoff_seconds: int) -> None:
        now = _utc_now_iso()
        backoff_until = datetime.now(timezone.utc).timestamp() + max(
            0, int(backoff_seconds)
        )
        backoff_until_iso = datetime.fromtimestamp(
            backoff_until, tz=timezone.utc
        ).isoformat()
        with self._lock:
            connection = self._get_connection()
            with connection:
                connection.execute(
                    """
                    UPDATE subscriptions
                    SET failure_count = failure_count + 1,
                        backoff_until = ?
                    WHERE id = ?
                    """,
                    (backoff_until_iso, spec_id),
                )
                connection.execute(
                    """
                    INSERT INTO cursors (
                        spec_id, failure_count, backoff_until, last_failure_at
                    ) VALUES (?, 1, ?, ?)
                    ON CONFLICT(spec_id) DO UPDATE SET
                        failure_count = failure_count + 1,
                        backoff_until = excluded.backoff_until,
                        last_failure_at = excluded.last_failure_at
                    """,
                    (spec_id, backoff_until_iso, now),
                )

    def already_pushed(self, spec_id: str, item_id: str, kind: str) -> bool:
        with self._lock:
            connection = self._get_connection()
            row = connection.execute(
                "SELECT 1 FROM push_log "
                "WHERE spec_id = ? AND item_id = ? AND kind = ?",
                (spec_id, item_id, kind),
            ).fetchone()
            return row is not None

    def mark_pushed(self, spec_id: str, item_id: str, kind: str) -> None:
        with self._lock:
            connection = self._get_connection()
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO push_log "
                    "(spec_id, item_id, kind, pushed_at) VALUES (?, ?, ?, ?)",
                    (spec_id, item_id, kind, _utc_now_iso()),
                )

    def add_digest_pending(
        self,
        spec_id: str,
        item_id: str,
        title: str,
        url: str,
        summary: str,
    ) -> None:
        with self._lock:
            connection = self._get_connection()
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO digest_pending "
                    "(spec_id, item_id, title, url, summary, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (spec_id, item_id, title, url, summary, _utc_now_iso()),
                )

    def pop_digest_pending(self, spec_id: str) -> list[dict[str, Any]]:
        with self._lock:
            connection = self._get_connection()
            with connection:
                rows = connection.execute(
                    "SELECT * FROM digest_pending WHERE spec_id = ? ORDER BY id",
                    (spec_id,),
                ).fetchall()
                if not rows:
                    return []
                ids = [row["id"] for row in rows]
                connection.executemany(
                    "DELETE FROM digest_pending WHERE id = ?",
                    [(row_id,) for row_id in ids],
                )
            return [dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

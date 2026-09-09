"""V2 subscription persistence: targets, cursors, seen items and outbox."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from plugins.bot_unified_runtime.contracts.subscription import (
    ContentReference,
    SubscriptionCursorV2,
    SubscriptionDestinationV2,
    SubscriptionFetchResult,
    SubscriptionOutboxEvent,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscription_migration import (
    prepare_subscription_database,
)

# ---- 有界化常量（审计 P2#10：outbox/seen 表随推送量线性增长） ----
# subscription_outbox 中 state='sent' 的行只保留近期：已推送事件仅剩排障
# 价值，默认 14 天（覆盖常见排障窗口），到期由 prune_stale_rows 裁剪。
_OUTBOX_SENT_RETENTION_DAYS = 14
# 推送重试上限：attempts 达到后转入死信（state='dead'，claim 不再捞起），
# 默认 5 次——按指数退避计约半小时内放弃，避免坏事件无限重试。
_OUTBOX_MAX_ATTEMPTS = 5
# subscription_seen 去重行 TTL：默认 90 天。TTL 清掉的条目若仍出现在某
# 频道的最新列表里会被再次推送，因此取远大于 outbox 保留期的值（只有
# 超过 90 天无任何新内容的极静默频道才可能触发）。
_SEEN_RETENTION_DAYS = 90
# 清理节流：默认每小时至多执行一次，避免高频写路径反复跑 DELETE。
_PRUNE_INTERVAL_SECONDS = 3600.0


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class SubscriptionStoreV2:
    def __init__(
        self,
        db_path: str = "data/subscriptions.sqlite3",
        *,
        config: Any | None = None,
        outbox_sent_retention_days: int | None = None,
        seen_retention_days: int | None = None,
        outbox_max_attempts: int | None = None,
    ) -> None:
        self._db_path = prepare_subscription_database(db_path)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        # 审计 P2#10：保留期/重试上限可用 config 属性覆盖，其次构造参数，
        # 最后回退模块常量（数值依据见常量处注释）。
        self._outbox_sent_retention_days = int(
            outbox_sent_retention_days
            or getattr(config, "bot_subscription_outbox_sent_retention_days", 0)
            or _OUTBOX_SENT_RETENTION_DAYS
        )
        self._seen_retention_days = int(
            seen_retention_days
            or getattr(config, "bot_subscription_seen_retention_days", 0)
            or _SEEN_RETENTION_DAYS
        )
        self._outbox_max_attempts = int(
            outbox_max_attempts
            or getattr(config, "bot_subscription_outbox_max_attempts", 0)
            or _OUTBOX_MAX_ATTEMPTS
        )
        self._last_prune_monotonic = 0.0

    @property
    def db_path(self) -> str:
        return self._db_path

    def _get_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            directory = os.path.dirname(os.path.abspath(self._db_path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            self._connection = sqlite3.connect(
                self._db_path,
                timeout=30,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._ensure_schema(self._connection)
        return self._connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', '2');
            CREATE TABLE IF NOT EXISTS subscription_targets (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                target_kind TEXT NOT NULL,
                target_key TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                target_payload TEXT NOT NULL DEFAULT '{}',
                source_mode TEXT NOT NULL DEFAULT 'pull',
                enabled INTEGER NOT NULL DEFAULT 1,
                health_state TEXT NOT NULL DEFAULT 'healthy',
                base_interval_seconds INTEGER NOT NULL,
                jitter_ratio REAL NOT NULL,
                baseline_initialized INTEGER NOT NULL DEFAULT 0,
                next_poll_at TEXT,
                lease_until TEXT,
                failure_count INTEGER NOT NULL DEFAULT 0,
                backoff_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(platform, target_kind, target_key)
            );
            CREATE TABLE IF NOT EXISTS subscription_destinations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id TEXT NOT NULL,
                transport TEXT NOT NULL,
                scope TEXT NOT NULL,
                destination_id TEXT NOT NULL,
                bot_id TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                digest_enabled INTEGER NOT NULL DEFAULT 0,
                UNIQUE(target_id, transport, scope, destination_id, bot_id),
                FOREIGN KEY(target_id) REFERENCES subscription_targets(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS subscription_cursors (
                target_id TEXT NOT NULL,
                stream TEXT NOT NULL,
                last_item_id TEXT NOT NULL DEFAULT '',
                last_timestamp TEXT,
                cursor_payload TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(target_id, stream),
                FOREIGN KEY(target_id) REFERENCES subscription_targets(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS subscription_seen_items (
                target_id TEXT NOT NULL,
                item_kind TEXT NOT NULL,
                item_id TEXT NOT NULL,
                published_at TEXT,
                discovered_at TEXT NOT NULL,
                PRIMARY KEY(target_id, item_kind, item_id),
                FOREIGN KEY(target_id) REFERENCES subscription_targets(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS subscription_outbox (
                event_id TEXT PRIMARY KEY,
                target_id TEXT NOT NULL,
                item_kind TEXT NOT NULL,
                item_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                payload TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                UNIQUE(target_id, item_kind, item_id, reason),
                FOREIGN KEY(target_id) REFERENCES subscription_targets(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS subscription_poll_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                result TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0,
                error_code TEXT NOT NULL DEFAULT ''
            );
            """
        )

    @staticmethod
    def _target(row: sqlite3.Row) -> SubscriptionTarget:
        values = dict(row)
        values["target_payload"] = json.loads(values.pop("target_payload") or "{}")
        values["enabled"] = bool(values["enabled"])
        values["baseline_initialized"] = bool(values["baseline_initialized"])
        values["next_poll_at"] = _dt(values["next_poll_at"])
        values["lease_until"] = _dt(values["lease_until"])
        values["backoff_until"] = _dt(values["backoff_until"])
        values["created_at"] = _dt(values["created_at"])
        values["updated_at"] = _dt(values["updated_at"])
        return SubscriptionTarget.model_validate(values)

    def upsert_target(self, target: SubscriptionTarget) -> None:
        values = target.model_dump(mode="json")
        values["target_payload"] = json.dumps(values["target_payload"], ensure_ascii=False)
        values["enabled"] = int(values["enabled"])
        values["baseline_initialized"] = int(values["baseline_initialized"])
        with self._lock:
            connection = self._get_connection()
            with connection:
                connection.execute(
                    """
                    INSERT INTO subscription_targets (
                        id, platform, target_kind, target_key, display_name,
                        target_payload, source_mode, enabled, health_state,
                        base_interval_seconds, jitter_ratio, baseline_initialized,
                        next_poll_at, lease_until, failure_count, backoff_until,
                        created_at, updated_at
                    ) VALUES (:id, :platform, :target_kind, :target_key, :display_name,
                        :target_payload, :source_mode, :enabled, :health_state,
                        :base_interval_seconds, :jitter_ratio, :baseline_initialized,
                        :next_poll_at, :lease_until, :failure_count, :backoff_until,
                        :created_at, :updated_at)
                    ON CONFLICT(id) DO UPDATE SET
                        platform=excluded.platform, target_kind=excluded.target_kind,
                        target_key=excluded.target_key, display_name=excluded.display_name,
                        target_payload=excluded.target_payload, source_mode=excluded.source_mode,
                        enabled=excluded.enabled, health_state=excluded.health_state,
                        base_interval_seconds=excluded.base_interval_seconds,
                        jitter_ratio=excluded.jitter_ratio,
                        baseline_initialized=excluded.baseline_initialized,
                        next_poll_at=excluded.next_poll_at, lease_until=excluded.lease_until,
                        failure_count=excluded.failure_count, backoff_until=excluded.backoff_until,
                        created_at=excluded.created_at, updated_at=excluded.updated_at
                    """,
                    {
                        **values,
                        "next_poll_at": _iso(target.next_poll_at) if target.next_poll_at else None,
                        "lease_until": _iso(target.lease_until) if target.lease_until else None,
                        "backoff_until": _iso(target.backoff_until) if target.backoff_until else None,
                        "created_at": _iso(target.created_at),
                        "updated_at": _iso(target.updated_at),
                    },
                )

    def get_target(self, target_id: str) -> SubscriptionTarget | None:
        with self._lock:
            row = self._get_connection().execute(
                "SELECT * FROM subscription_targets WHERE id = ?", (target_id,)
            ).fetchone()
            return self._target(row) if row is not None else None

    def list_targets(self, *, due_before: datetime | None = None) -> list[SubscriptionTarget]:
        with self._lock:
            if due_before is None:
                rows = self._get_connection().execute(
                    "SELECT * FROM subscription_targets ORDER BY id"
                ).fetchall()
            else:
                rows = self._get_connection().execute(
                    "SELECT * FROM subscription_targets WHERE next_poll_at IS NULL OR next_poll_at <= ? ORDER BY id",
                    (_iso(due_before),),
                ).fetchall()
            return [self._target(row) for row in rows]

    def claim_due_target(self, target_id: str, now: datetime, lease_seconds: int) -> bool:
        lease_until = now.astimezone(timezone.utc).timestamp() + max(1, int(lease_seconds))
        lease = datetime.fromtimestamp(lease_until, timezone.utc)
        with self._lock:
            connection = self._get_connection()
            with connection:
                updated = connection.execute(
                    """
                    UPDATE subscription_targets
                    SET lease_until = ?
                    WHERE id = ? AND enabled = 1
                      AND (lease_until IS NULL OR lease_until <= ?)
                    """,
                    (_iso(lease), target_id, _iso(now)),
                ).rowcount
            return bool(updated)

    def release_target(self, target_id: str, *, next_poll_at: datetime) -> None:
        with self._lock:
            connection = self._get_connection()
            with connection:
                connection.execute(
                    "UPDATE subscription_targets SET lease_until = NULL, next_poll_at = ?, updated_at = ? WHERE id = ?",
                    (_iso(next_poll_at), _iso(datetime.now(timezone.utc)), target_id),
                )

    def add_destination(self, destination: SubscriptionDestinationV2) -> None:
        with self._lock, self._get_connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO subscription_destinations
                    (target_id, transport, scope, destination_id, bot_id,
                     enabled, digest_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    destination.target_id,
                    destination.transport,
                    destination.scope,
                    destination.destination_id,
                    destination.bot_id,
                    int(destination.enabled),
                    int(destination.digest_enabled),
                ),
            )

    def list_destinations(self, target_id: str) -> list[SubscriptionDestinationV2]:
        with self._lock:
            rows = self._get_connection().execute(
                "SELECT * FROM subscription_destinations WHERE target_id = ? ORDER BY id",
                (target_id,),
            ).fetchall()
            return [
                SubscriptionDestinationV2(
                    id=str(row["id"]),
                    target_id=str(row["target_id"]),
                    transport=str(row["transport"]),
                    scope=str(row["scope"]),
                    destination_id=str(row["destination_id"]),
                    bot_id=str(row["bot_id"] or ""),
                    enabled=bool(row["enabled"]),
                    digest_enabled=bool(row["digest_enabled"]),
                )
                for row in rows
            ]

    def set_target_enabled(self, target_id: str, enabled: bool) -> bool:
        with self._lock, self._get_connection() as connection:
            return bool(
                connection.execute(
                    "UPDATE subscription_targets SET enabled = ?, updated_at = ? WHERE id = ?",
                    (int(bool(enabled)), _iso(datetime.now(timezone.utc)), target_id),
                ).rowcount
            )

    def delete_target(self, target_id: str) -> bool:
        with self._lock, self._get_connection() as connection:
            return bool(
                connection.execute(
                    "DELETE FROM subscription_targets WHERE id = ?", (target_id,)
                ).rowcount
            )

    def get_cursors(self, target_id: str) -> dict[str, SubscriptionCursorV2]:
        with self._lock:
            rows = self._get_connection().execute(
                "SELECT * FROM subscription_cursors WHERE target_id = ?", (target_id,)
            ).fetchall()
            result: dict[str, SubscriptionCursorV2] = {}
            for row in rows:
                result[str(row["stream"])] = SubscriptionCursorV2(
                    target_id=str(row["target_id"]),
                    stream=str(row["stream"]),
                    last_item_id=str(row["last_item_id"]),
                    last_timestamp=_dt(row["last_timestamp"]),
                    cursor_payload=json.loads(row["cursor_payload"] or "{}"),
                    updated_at=_dt(row["updated_at"]) or datetime.now(timezone.utc),
                )
            return result

    def save_fetch_result(
        self,
        target: SubscriptionTarget,
        result: SubscriptionFetchResult,
        *,
        baseline: bool,
    ) -> list[SubscriptionOutboxEvent]:
        now = datetime.now(timezone.utc)
        events: list[SubscriptionOutboxEvent] = []
        with self._lock:
            connection = self._get_connection()
            with connection:
                for item in result.items:
                    inserted = connection.execute(
                        """
                        INSERT OR IGNORE INTO subscription_seen_items
                            (target_id, item_kind, item_id, published_at, discovered_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            target.id,
                            item.item_kind,
                            item.item_id,
                            _iso(item.published_at) if item.published_at else None,
                            _iso(now),
                        ),
                    ).rowcount
                    if not inserted or baseline:
                        continue
                    event_id = f"{target.id}:{item.item_kind}:{item.item_id}"
                    event = SubscriptionOutboxEvent(
                        event_id=event_id,
                        target_id=target.id,
                        item=item,
                        reason="new_item",
                        next_attempt_at=now,
                        created_at=now,
                    )
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO subscription_outbox
                            (event_id, target_id, item_kind, item_id, reason, payload,
                             state, attempts, next_attempt_at, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                        """,
                        (
                            event.event_id,
                            event.target_id,
                            item.item_kind,
                            item.item_id,
                            event.reason,
                            json.dumps(item.model_dump(mode="json"), ensure_ascii=False),
                            _iso(event.next_attempt_at),
                            _iso(event.created_at),
                        ),
                    )
                    events.append(event)
                for cursor in result.cursors:
                    connection.execute(
                        """
                        INSERT INTO subscription_cursors
                            (target_id, stream, last_item_id, last_timestamp, cursor_payload, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(target_id, stream) DO UPDATE SET
                            last_item_id=excluded.last_item_id,
                            last_timestamp=excluded.last_timestamp,
                            cursor_payload=excluded.cursor_payload,
                            updated_at=excluded.updated_at
                        """,
                        (
                            cursor.target_id,
                            cursor.stream,
                            cursor.last_item_id,
                            _iso(cursor.last_timestamp) if cursor.last_timestamp else None,
                            json.dumps(cursor.cursor_payload, ensure_ascii=False),
                            _iso(cursor.updated_at),
                        ),
                    )
                connection.execute(
                    "UPDATE subscription_targets SET baseline_initialized = 1 WHERE id = ?",
                    (target.id,),
                )
        self.prune_stale_rows()
        return events

    def prune_stale_rows(
        self, *, now: datetime | None = None, force: bool = False
    ) -> int:
        """按保留期裁剪 sent outbox 行与 seen 去重行（审计 P2#10）。

        默认按 ``_PRUNE_INTERVAL_SECONDS`` 节流（每小时至多一次）；
        测试/运维可 ``force=True`` 立即执行。返回删除的行数。
        """
        moment = now or datetime.now(timezone.utc)
        monotonic_now = time.monotonic()
        if not force and (
            monotonic_now - self._last_prune_monotonic < _PRUNE_INTERVAL_SECONDS
        ):
            return 0
        self._last_prune_monotonic = monotonic_now
        sent_cutoff = _iso(
            moment - timedelta(days=self._outbox_sent_retention_days)
        )
        seen_cutoff = _iso(moment - timedelta(days=self._seen_retention_days))
        with self._lock, self._get_connection() as connection:
            removed_outbox = connection.execute(
                "DELETE FROM subscription_outbox "
                "WHERE state='sent' AND COALESCE(sent_at, created_at) <= ?",
                (sent_cutoff,),
            ).rowcount
            removed_seen = connection.execute(
                "DELETE FROM subscription_seen_items WHERE discovered_at <= ?",
                (seen_cutoff,),
            ).rowcount
        return int(removed_outbox) + int(removed_seen)

    def record_failure(self, target_id: str, error_code: str, *, retry_at: datetime) -> None:
        with self._lock:
            connection = self._get_connection()
            with connection:
                connection.execute(
                    """
                    UPDATE subscription_targets
                    SET health_state = ?, failure_count = failure_count + 1,
                        backoff_until = ?, lease_until = NULL,
                        next_poll_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        str(error_code or "network_error"),
                        _iso(retry_at),
                        _iso(retry_at),
                        _iso(datetime.now(timezone.utc)),
                        target_id,
                    ),
                )

    def claim_outbox(self, now: datetime, limit: int) -> list[SubscriptionOutboxEvent]:
        with self._lock:
            connection = self._get_connection()
            with connection:
                rows = connection.execute(
                    """
                    SELECT * FROM subscription_outbox
                    WHERE state IN ('pending', 'retry') AND next_attempt_at <= ?
                    ORDER BY created_at LIMIT ?
                    """,
                    (_iso(now), max(1, int(limit))),
                ).fetchall()
                events: list[SubscriptionOutboxEvent] = []
                for row in rows:
                    connection.execute(
                        "UPDATE subscription_outbox SET state='sending', attempts=attempts+1 WHERE event_id=?",
                        (row["event_id"],),
                    )
                    events.append(
                        SubscriptionOutboxEvent(
                            event_id=str(row["event_id"]),
                            target_id=str(row["target_id"]),
                            item=ContentReference.model_validate(json.loads(row["payload"])),
                            reason=str(row["reason"]),
                            state="sending",
                            attempts=int(row["attempts"]) + 1,
                            next_attempt_at=_dt(row["next_attempt_at"]) or now,
                            created_at=_dt(row["created_at"]) or now,
                        )
                    )
                return events

    def mark_outbox_sent(self, event_id: str, sent_at: datetime) -> None:
        with self._lock, self._get_connection() as connection:
            connection.execute(
                "UPDATE subscription_outbox SET state='sent', sent_at=? WHERE event_id=?",
                (_iso(sent_at), event_id),
            )
        # 审计 P2#10：sent 行按保留期裁剪，不再永久堆积。
        self.prune_stale_rows(now=sent_at)

    def mark_outbox_retry(self, event_id: str, next_attempt_at: datetime) -> None:
        with self._lock, self._get_connection() as connection:
            row = connection.execute(
                "SELECT attempts FROM subscription_outbox WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is not None and int(row["attempts"]) >= self._outbox_max_attempts:
                # 审计 P2#10：重试无上限会永久占住队列；超限转死信，
                # state='dead' 不会被 claim_outbox 再捞起。
                connection.execute(
                    "UPDATE subscription_outbox SET state='dead' WHERE event_id=?",
                    (event_id,),
                )
                return
            connection.execute(
                "UPDATE subscription_outbox SET state='retry', next_attempt_at=? WHERE event_id=?",
                (_iso(next_attempt_at), event_id),
            )

    def outbox_state(self, event_id: str) -> str | None:
        with self._lock:
            row = self._get_connection().execute(
                "SELECT state FROM subscription_outbox WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            return str(row["state"]) if row is not None else None

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

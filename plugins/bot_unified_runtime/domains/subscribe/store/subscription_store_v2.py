"""V2 subscription persistence: targets, cursors, seen items and outbox."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from plugins.bot_unified_runtime.contracts import OperationalIssue, RiskLevel
from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    ContentReference,
    SubscriptionCursorV2,
    SubscriptionDestinationV2,
    SubscriptionFetchResult,
    SubscriptionOutboxEvent,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_migration import (
    prepare_subscription_database,
)

_LOGGER = logging.getLogger(__name__)

# ---- 有界化常量（审计 P2#10：outbox/seen 表随推送量线性增长） ----
# subscription_outbox 中 state='sent' 的行只保留近期：已推送事件仅剩排障
# 价值，默认 14 天（覆盖常见排障窗口），到期由 prune_stale_rows 裁剪。
_OUTBOX_SENT_RETENTION_DAYS = 14
# 推送重试上限：attempts 达到后转入死信（state='dead'，claim 不再捞起），
# 默认 5 次——按指数退避计约半小时内放弃，避免坏事件无限重试。
_OUTBOX_MAX_ATTEMPTS = 5
# sending 滞留回收秒数：claim 把事件置为 state='sending' 后若进程在投递中
# 崩溃，该行不再被 claim（只捞 pending/retry），推送静默丢失。claim 会同时
# 回收 sending 超过此时长的陈旧行（claim 时把 next_attempt_at 刷新为当前
# 时刻，超时判定因此精确），默认 300 秒远大于正常投递耗时。
_OUTBOX_SENDING_STALE_SECONDS = 300.0
# subscription_seen 去重行 TTL：默认 90 天。TTL 清掉的条目若仍出现在某
# 频道的最新列表里会被再次推送，因此取远大于 outbox 保留期的值（只有
# 超过 90 天无任何新内容的极静默频道才可能触发）。
_SEEN_RETENTION_DAYS = 90
# 清理节流：默认每小时至多执行一次，避免高频写路径反复跑 DELETE。
_PRUNE_INTERVAL_SECONDS = 3600.0
# 审查 J-03：死信告警 stage 固定前缀。kind 内含订阅 id 与目的地列表，
# 抑制键 = (stage, 订阅 id, 目的地)——与 runtime/alerts 队列告警的
# (stage, kind) 成键风格一致，300s 窗口内同一订阅同一目的地只报一次。
_DEAD_ALERT_STAGE = "subscription_outbox_dead"


def subscription_platform_enabled(config: Any, platform: str) -> bool:
    """审查 J-02：订阅 per-platform 开关的唯一切换实现。

    订阅 add 拒绝（capabilities/subscribe_v2）与轮询跳过
    （subscription_scheduler）两处共用本函数，防两处语义漂移。
    键名 = ``bot_subscribe_platform_<platform>``，与 V2 注册表 resolve 出的
    target.platform 标识逐字对齐（music 平台以 provider 名 netease 落库）；
    未登记的平台（已摘除的 twitter、未来新平台）一律视为开放——开关只做
    「关闸」，不隐式扩大管控面。与 bot_subscribe_enabled 总开关叠加：总
    开关在路由层（base_router subscribe_match）拦整个订阅系统，平台开关
    只影响本平台。config 实例进程启动时固定，改键需重启生效。
    """
    name = str(platform or "").strip().lower()
    if not name:
        return True
    return bool(getattr(config, f"bot_subscribe_platform_{name}", True))


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
        outbox_sending_stale_seconds: float | None = None,
        dead_letter_sink: Callable[[OperationalIssue], None] | None = None,
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
        self._outbox_sending_stale_seconds = float(
            outbox_sending_stale_seconds
            or getattr(config, "bot_subscription_outbox_sending_stale_seconds", 0)
            or _OUTBOX_SENDING_STALE_SECONDS
        )
        self._last_prune_monotonic = 0.0
        # 审查 J-03：死信（state='dead'）转移时的告警出口。sink 为同步回调
        # （mark_outbox_retry 在工作线程执行，禁止注入 async 回调），缺省
        # None 时降级为 WARNING 日志；管理员通道接线属装配层职责
        # （subscription_runtime_v2 构造 store 处后续传入）。
        self._dead_letter_sink = dead_letter_sink
        # 延迟导入：runtime 包 __init__ 会级联拉起 pipeline 等装配层模块，
        # 本 store 是底层组件，顶层导入有成环与导入成本风险（同
        # sources/downloader.py 的函数内导入先例）。抑制窗口 300s 与项目
        # 告警族（queue/result_unknown）口径一致。
        from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
            AdminAlertSuppression,
        )

        self._dead_alert_suppression = AdminAlertSuppression()

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
            CREATE TABLE IF NOT EXISTS subscription_target_metadata (
                target_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (target_id, key),
                FOREIGN KEY(target_id) REFERENCES subscription_targets(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS subscription_outbox_deliveries (
                event_id TEXT NOT NULL,
                destination_key TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (event_id, destination_key),
                FOREIGN KEY(event_id) REFERENCES subscription_outbox(event_id) ON DELETE CASCADE
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

    def release_target_lease(self, target_id: str) -> None:
        """异常兜底：只清租约，不回写 next_poll_at。

        回写过期的 next_poll_at 会让退避失效（目标每周期立即重轮询）；
        保持原 next_poll_at 时，租约清空后目标到点自然可再次 claim。
        """
        with self._lock, self._get_connection() as connection:
            connection.execute(
                "UPDATE subscription_targets SET lease_until = NULL, updated_at = ? WHERE id = ?",
                (_iso(datetime.now(timezone.utc)), target_id),
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

    def set_destination_enabled(self, destination_id: int, enabled: bool) -> bool:
        """目的地级暂停/恢复（审计重发现 P2：此前 pause/resume 作用于整条
        target，一个目的地的管理员能影响其他群/私聊的推送）。"""
        with self._lock, self._get_connection() as connection:
            return bool(
                connection.execute(
                    "UPDATE subscription_destinations SET enabled = ? WHERE id = ?",
                    (int(bool(enabled)), int(destination_id)),
                ).rowcount
            )

    def delete_destination(self, destination_id: int) -> bool:
        """目的地级移除；最后一个目的地移除后由调用方决定是否删 target。"""
        with self._lock, self._get_connection() as connection:
            return bool(
                connection.execute(
                    "DELETE FROM subscription_destinations WHERE id = ?",
                    (int(destination_id),),
                ).rowcount
            )

    def set_target_enabled(self, target_id: str, enabled: bool) -> bool:
        with self._lock, self._get_connection() as connection:
            return bool(
                connection.execute(
                    "UPDATE subscription_targets SET enabled = ?, updated_at = ? WHERE id = ?",
                    (int(bool(enabled)), _iso(datetime.now(timezone.utc)), target_id),
                ).rowcount
            )

    def set_target_metadata(self, target_id: str, metadata: dict[str, Any]) -> None:
        """合并写入目标运行期元数据（如 X rest_id），键级 upsert。

        adapter 在 fetch 中向 ``target.target_payload`` 注入的显式元数据由
        调度器经本 API 落库：既有 target_payload 是建订时的静态载荷，而
        rest_id 这类解析产物需要独立、可查询的持久化位置，重启后由
        ``get_target_metadata`` 回灌。value 以 JSON 文本存储，任意
        JSON 兼容类型均可往返；空 dict 不写库。
        """
        if not metadata:
            return
        now = _iso(datetime.now(timezone.utc))
        with self._lock, self._get_connection() as connection:
            connection.executemany(
                """
                INSERT INTO subscription_target_metadata (target_id, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(target_id, key) DO UPDATE SET
                    value=excluded.value, updated_at=excluded.updated_at
                """,
                [
                    (target_id, str(key), json.dumps(value, ensure_ascii=False), now)
                    for key, value in metadata.items()
                ],
            )

    def get_target_metadata(self, target_id: str) -> dict[str, Any]:
        with self._lock:
            rows = self._get_connection().execute(
                "SELECT key, value FROM subscription_target_metadata WHERE target_id = ?",
                (target_id,),
            ).fetchall()
            return {str(row["key"]): json.loads(row["value"]) for row in rows}

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
        sending_stale_cutoff = _iso(
            now - timedelta(seconds=self._outbox_sending_stale_seconds)
        )
        with self._lock:
            connection = self._get_connection()
            with connection:
                rows = connection.execute(
                    """
                    SELECT * FROM subscription_outbox
                    WHERE (state IN ('pending', 'retry') AND next_attempt_at <= ?)
                       OR (state = 'sending' AND next_attempt_at <= ?)
                    ORDER BY created_at LIMIT ?
                    """,
                    (_iso(now), sending_stale_cutoff, max(1, int(limit))),
                ).fetchall()
                events: list[SubscriptionOutboxEvent] = []
                for row in rows:
                    # 审计 E2-3：claim 时把 next_attempt_at 刷新为当前时刻，
                    # sending 行的超时回收判定因此精确（不会被刚 claim 的行误回收）。
                    connection.execute(
                        "UPDATE subscription_outbox SET state='sending', attempts=attempts+1, next_attempt_at=? WHERE event_id=?",
                        (_iso(now), row["event_id"]),
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
        dead_info: tuple[str, int] | None = None
        with self._lock:
            connection = self._get_connection()
            with connection:
                row = connection.execute(
                    "SELECT attempts, target_id FROM subscription_outbox WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if row is not None and int(row["attempts"]) >= self._outbox_max_attempts:
                    # 审计 P2#10：重试无上限会永久占住队列；超限转死信，
                    # state='dead' 不会被 claim_outbox 再捞起。
                    connection.execute(
                        "UPDATE subscription_outbox SET state='dead' WHERE event_id=?",
                        (event_id,),
                    )
                    dead_info = (str(row["target_id"]), int(row["attempts"]))
                else:
                    connection.execute(
                        "UPDATE subscription_outbox SET state='retry', next_attempt_at=? WHERE event_id=?",
                        (_iso(next_attempt_at), event_id),
                    )
        if dead_info is not None:
            # 审查 J-03：告警必须在事务提交之后发——这里的 list_destinations
            # 查询与 sink 回调都不得处于未提交事务内，且告警故障只记日志，
            # 不回滚、不影响重试记账主链路。
            target_id, attempts = dead_info
            self._emit_dead_letter_alert(event_id, target_id, attempts)

    def _emit_dead_letter_alert(self, event_id: str, target_id: str, attempts: int) -> None:
        """审查 J-03：死信（state='dead'）此前全仓无告警无重投入口——5 次重试
        后静默丢弃。转移时产生一条 runtime/alerts 告警：内容复用
        OperationalIssue 契约（kind 含订阅 id 与目的地），抑制复用
        AdminAlertSuppression（300s 窗口，键 = stage+订阅+目的地，风格对齐
        队列告警）。sink 缺省 None 时降级 WARNING 日志。任何异常只记日志。
        """
        try:
            destinations = self.list_destinations(target_id)
            dest_token = (
                ",".join(f"{d.scope}:{d.destination_id}" for d in destinations)
                or "none"
            )
            allowed, _suppressed_count = self._dead_alert_suppression.allow(
                (_DEAD_ALERT_STAGE, target_id, dest_token)
            )
            if not allowed:
                return
            issue = OperationalIssue(
                stage=_DEAD_ALERT_STAGE,
                kind=f"subscription:{target_id}|dest:{dest_token}",
                retryable=False,
                severity=RiskLevel.MEDIUM,
                safe_summary=(
                    f"订阅推送重试 {max(1, attempts)} 次仍失败，事件转死信暂停推送"
                    f"（目的地 {dest_token}）；可调 requeue_dead({event_id!r}) 重投"
                ),
                attempts=max(1, attempts),
                debug_id=event_id,
            )
            if self._dead_letter_sink is not None:
                self._dead_letter_sink(issue)
            else:
                _LOGGER.warning(
                    "subscription dead letter: %s", issue.model_dump_json()
                )
        except Exception:
            _LOGGER.warning(
                "dead letter alert emission failed for %s", event_id, exc_info=True
            )

    def requeue_dead(self, event_id: str, *, now: datetime | None = None) -> bool:
        """审查 J-03：死信重投入口（仅 store 方法，无 UI，供未来管理员命令接线）。

        幂等：单条 UPDATE 带 ``state='dead'`` 谓词，重复调用第二次匹配不到
        行、无副作用，返回 False。重投语义：state 回 ``'pending'``（本表
        “待发队列”状态——claim_outbox 只捞 pending/retry，无 queued 字面量），
        attempts 清零（重获完整重试预算），next_attempt_at 置为 now 让
        claim 立即可捞。返回是否真的发生了重投。
        """
        moment = _iso(now or datetime.now(timezone.utc))
        with self._lock, self._get_connection() as connection:
            updated = connection.execute(
                "UPDATE subscription_outbox SET state='pending', attempts=0, "
                "next_attempt_at=? WHERE event_id=? AND state='dead'",
                (moment, event_id),
            ).rowcount
        return bool(updated)

    def record_outbox_deliveries(
        self,
        event_id: str,
        destination_keys: Sequence[str],
        *,
        sent_at: datetime | None = None,
    ) -> int:
        """审查 J-04：目的地级投递成功台账。

        (event_id, destination_key) 主键即最小唯一约束。调度器在「投递成功」
        与「标记 sent」两写之间先落本台账：两写之间崩溃/超时后，重投前查重
        命中即可跳过整事件，杜绝重复推送。destination_key 取
        subscription_destinations 行 id（稳定自增主键）；外键级联跟随 outbox
        行清理（sent 保留期裁剪/目标删除），台账不堆积。返回新增行数。
        """
        keys = [str(key) for key in destination_keys if str(key)]
        if not keys:
            return 0
        moment = _iso(sent_at or datetime.now(timezone.utc))
        with self._lock, self._get_connection() as connection:
            cursor = connection.executemany(
                "INSERT OR IGNORE INTO subscription_outbox_deliveries "
                "(event_id, destination_key, sent_at) VALUES (?, ?, ?)",
                [(event_id, key, moment) for key in keys],
            )
            return int(cursor.rowcount)

    def outbox_undelivered_destinations(
        self,
        event_id: str,
        destination_keys: Sequence[str],
    ) -> list[str]:
        """审查 J-04：返回给定目的地中尚无投递成功记录的子集（投递前查重）。

        空列表直接返回空（调用方对「无目的地」必须维持既有投递语义，
        不得凭空判为已覆盖）。
        """
        keys = [str(key) for key in destination_keys if str(key)]
        if not keys:
            return []
        placeholders = ",".join("?" * len(keys))
        with self._lock:
            rows = self._get_connection().execute(
                "SELECT destination_key FROM subscription_outbox_deliveries "
                f"WHERE event_id = ? AND destination_key IN ({placeholders})",
                (event_id, *keys),
            ).fetchall()
        covered = {str(row["destination_key"]) for row in rows}
        return [key for key in keys if key not in covered]

    def outbox_state(self, event_id: str) -> str | None:
        with self._lock:
            row = self._get_connection().execute(
                "SELECT state FROM subscription_outbox WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            return str(row["state"]) if row is not None else None

    # ---- async 门面（性能分诊 P2-1：调度器此前在 event loop 上直跑同步
    # SQLite，活跃源多条 item 时造成毫秒级 loop 停顿）。同步实现保持不动、
    # 被 asyncio.to_thread 下放到工作线程执行；线程安全由既有 self._lock
    # （RLock + check_same_thread=False 连接）保证，语义与直调完全一致。
    # 调度器（subscription_scheduler）只经这些门面访问存储。----

    async def upsert_target_async(self, target: SubscriptionTarget) -> None:
        return await asyncio.to_thread(self.upsert_target, target)

    async def list_targets_async(
        self, *, due_before: datetime | None = None
    ) -> list[SubscriptionTarget]:
        return await asyncio.to_thread(self.list_targets, due_before=due_before)

    async def claim_due_target_async(
        self, target_id: str, now: datetime, lease_seconds: int
    ) -> bool:
        return await asyncio.to_thread(
            self.claim_due_target, target_id, now, lease_seconds
        )

    async def release_target_async(
        self, target_id: str, *, next_poll_at: datetime
    ) -> None:
        return await asyncio.to_thread(
            self.release_target, target_id, next_poll_at=next_poll_at
        )

    async def release_target_lease_async(self, target_id: str) -> None:
        return await asyncio.to_thread(self.release_target_lease, target_id)

    async def record_failure_async(
        self, target_id: str, error_code: str, *, retry_at: datetime
    ) -> None:
        return await asyncio.to_thread(
            self.record_failure, target_id, error_code, retry_at=retry_at
        )

    async def get_cursors_async(
        self, target_id: str
    ) -> dict[str, SubscriptionCursorV2]:
        return await asyncio.to_thread(self.get_cursors, target_id)

    async def get_target_metadata_async(self, target_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_target_metadata, target_id)

    async def set_target_metadata_async(
        self, target_id: str, metadata: dict[str, Any]
    ) -> None:
        return await asyncio.to_thread(self.set_target_metadata, target_id, metadata)

    async def save_fetch_result_async(
        self,
        target: SubscriptionTarget,
        result: SubscriptionFetchResult,
        *,
        baseline: bool,
    ) -> list[SubscriptionOutboxEvent]:
        return await asyncio.to_thread(
            self.save_fetch_result, target, result, baseline=baseline
        )

    async def claim_outbox_async(
        self, now: datetime, limit: int
    ) -> list[SubscriptionOutboxEvent]:
        return await asyncio.to_thread(self.claim_outbox, now, limit)

    async def mark_outbox_sent_async(self, event_id: str, sent_at: datetime) -> None:
        return await asyncio.to_thread(self.mark_outbox_sent, event_id, sent_at)

    async def mark_outbox_retry_async(
        self, event_id: str, next_attempt_at: datetime
    ) -> None:
        return await asyncio.to_thread(
            self.mark_outbox_retry, event_id, next_attempt_at
        )

    async def outbox_state_async(self, event_id: str) -> str | None:
        return await asyncio.to_thread(self.outbox_state, event_id)

    # ---- 审查 J-04/J-03 新增门面：调度器投递前查重 / 成功台账 / 死信重投
    # 与调度器其余存储访问一样，只经 *_async 门面（P2-1 离环约定）。----

    async def list_destinations_async(self, target_id: str) -> list[SubscriptionDestinationV2]:
        return await asyncio.to_thread(self.list_destinations, target_id)

    async def record_outbox_deliveries_async(
        self,
        event_id: str,
        destination_keys: Sequence[str],
        *,
        sent_at: datetime | None = None,
    ) -> int:
        return await asyncio.to_thread(
            self.record_outbox_deliveries,
            event_id,
            destination_keys,
            sent_at=sent_at,
        )

    async def outbox_undelivered_destinations_async(
        self,
        event_id: str,
        destination_keys: Sequence[str],
    ) -> list[str]:
        return await asyncio.to_thread(
            self.outbox_undelivered_destinations, event_id, destination_keys
        )

    async def requeue_dead_async(self, event_id: str, *, now: datetime | None = None) -> bool:
        return await asyncio.to_thread(self.requeue_dead, event_id, now=now)

    async def add_destination_async(self, destination: SubscriptionDestinationV2) -> None:
        return await asyncio.to_thread(self.add_destination, destination)

    async def set_destination_enabled_async(
        self, destination_id: int, enabled: bool
    ) -> bool:
        return await asyncio.to_thread(
            self.set_destination_enabled, destination_id, enabled
        )

    async def set_target_enabled_async(self, target_id: str, enabled: bool) -> bool:
        return await asyncio.to_thread(self.set_target_enabled, target_id, enabled)

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

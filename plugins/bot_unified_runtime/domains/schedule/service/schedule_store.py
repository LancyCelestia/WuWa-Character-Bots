"""S11 日程链确定性核心——SQLite 持久层（V2.1 §4.2 调度器语义）。

- 库路径经 scripts/runtime_paths 重映射（data/ 前缀 → ChatBot_Runtime），
  测试一律传 tmp_path 显式路径。
- PRAGMA：journal_mode=WAL、busy_timeout=1000ms、synchronous=NORMAL；
  单连接 + threading.Lock，写路径全部 BEGIN IMMEDIATE 事务内完成
  （两个并发领取因此天然线性化——先到者得租约）。
- 时间索引 idx_occ_due(status, due_epoch)：claim_due 走索引，不扫全表。
- 租约语义：lease_owner + lease_expires_epoch；默认轮询 5s、单次 ≤50 条、
  租约 300s；重启后过期租约可被重新领取（reconcile 到期项）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.schedule.service.schedule_dag import Occurrence

DEFAULT_POLL_SECONDS = 5.0
DEFAULT_CLAIM_LIMIT = 50
DEFAULT_LEASE_SECONDS = 300

SCHEMA = """
CREATE TABLE IF NOT EXISTS schedule_plans (
    plan_id      TEXT PRIMARY KEY,
    owner        TEXT NOT NULL,
    timezone     TEXT NOT NULL,
    revision     INTEGER NOT NULL,
    state        TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_utc  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_occurrences (
    occurrence_id      TEXT PRIMARY KEY,
    plan_id            TEXT NOT NULL,
    rule_id            TEXT NOT NULL,
    rule_revision      INTEGER NOT NULL,
    task_id            TEXT NOT NULL,
    title              TEXT NOT NULL,
    scheduled_at_utc   TEXT NOT NULL,
    due_epoch          REAL NOT NULL,
    duration_minutes   INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'pending',
    tags_json          TEXT NOT NULL DEFAULT '[]',
    lease_owner        TEXT,
    lease_expires_epoch REAL,
    updated_utc        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_occ_due ON schedule_occurrences (status, due_epoch);
CREATE INDEX IF NOT EXISTS idx_occ_plan ON schedule_occurrences (plan_id, rule_id);

CREATE TABLE IF NOT EXISTS schedule_send_log (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner         TEXT NOT NULL,
    occurrence_id TEXT NOT NULL,
    kind          TEXT NOT NULL,
    sent_epoch    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sendlog_owner_time ON schedule_send_log (owner, sent_epoch);

CREATE TABLE IF NOT EXISTS schedule_quiet_exceptions (
    occurrence_id TEXT PRIMARY KEY,
    owner         TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    created_utc   TEXT NOT NULL
);
"""

STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"
STATUS_DIGEST = "digest"
STATUS_SKIPPED = "skipped"
STATUS_EXPIRED = "expired"
STATUS_ASK = "ask"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _epoch(dt: datetime) -> float:
    return dt.astimezone(timezone.utc).timestamp()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["tags"] = json.loads(data.pop("tags_json", "[]") or "[]")
    return data


class ScheduleStore:
    """SQLite 日程存储（WAL；单连接 + Lock；写路径 BEGIN IMMEDIATE）。"""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=1000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)

    # ------------------------------------------------------------------ plan
    def upsert_plan(self, plan: Any, *, payload_json: str, now_utc: datetime) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO schedule_plans
                    (plan_id, owner, timezone, revision, state, payload_json, updated_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    owner=excluded.owner, timezone=excluded.timezone,
                    revision=excluded.revision, state=excluded.state,
                    payload_json=excluded.payload_json, updated_utc=excluded.updated_utc
                """,
                (plan.plan_id, plan.owner, plan.timezone, plan.revision, plan.state, payload_json, _iso(now_utc)),
            )

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM schedule_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json"))
        return data

    # ----------------------------------------------------------- occurrences
    def upsert_occurrences(self, occurrences: list[Occurrence], *, now_utc: datetime) -> int:
        """INSERT OR IGNORE → occurrence_id 主键天然幂等；返回新插入条数。"""
        inserted = 0
        stamp = _iso(now_utc)
        with self._lock, self._conn:
            for occ in occurrences:
                cursor = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO schedule_occurrences
                        (occurrence_id, plan_id, rule_id, rule_revision, task_id, title,
                         scheduled_at_utc, due_epoch, duration_minutes, status, tags_json, updated_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        occ.occurrence_id,
                        occ.plan_id,
                        occ.rule_id,
                        occ.rule_revision,
                        occ.task_id,
                        occ.title,
                        occ.scheduled_at_utc,
                        _epoch(datetime.fromisoformat(occ.scheduled_at_utc)),
                        occ.duration_minutes,
                        json.dumps(occ.tags),
                        stamp,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def get_occurrence(self, occurrence_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM schedule_occurrences WHERE occurrence_id = ?", (occurrence_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None

    def list_occurrences(
        self,
        plan_id: str | None = None,
        *,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM schedule_occurrences WHERE 1=1"
        params: list[Any] = []
        if plan_id is not None:
            sql += " AND plan_id = ?"
            params.append(plan_id)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY due_epoch LIMIT ?"
        params.append(limit)
        return [_row_to_dict(r) for r in self._conn.execute(sql, params)]

    # ----------------------------------------------------------------- claim
    def claim_due(
        self,
        now_utc: datetime,
        *,
        worker_id: str,
        limit: int = DEFAULT_CLAIM_LIMIT,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> list[dict[str, Any]]:
        """领取到期项（BEGIN IMMEDIATE 下 SELECT→UPDATE 线性化，先到者得租约）。

        WHERE status='pending' AND due_epoch <= now
          AND (lease_owner IS NULL OR lease_expires_epoch <= now)
        走 idx_occ_due 索引；不扫全表。
        """
        now_epoch = _epoch(now_utc)
        lease_expire = now_epoch + lease_seconds
        claimed: list[dict[str, Any]] = []
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self._conn.execute(
                    """
                    SELECT * FROM schedule_occurrences
                    WHERE status = 'pending' AND due_epoch <= ?
                      AND (lease_owner IS NULL OR lease_expires_epoch <= ?)
                    ORDER BY due_epoch
                    LIMIT ?
                    """,
                    (now_epoch, now_epoch, limit),
                ).fetchall()
                for row in rows:
                    updated = self._conn.execute(
                        """
                        UPDATE schedule_occurrences
                        SET lease_owner = ?, lease_expires_epoch = ?, updated_utc = ?
                        WHERE occurrence_id = ? AND status = 'pending'
                        """,
                        (worker_id, lease_expire, _iso(now_utc), row["occurrence_id"]),
                    )
                    if updated.rowcount:
                        claimed_row = _row_to_dict(row)
                        # 返回领取后的租约快照（SELECT 发生在 UPDATE 前）。
                        claimed_row["lease_owner"] = worker_id
                        claimed_row["lease_expires_epoch"] = lease_expire
                        claimed.append(claimed_row)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return claimed

    def release_lease(self, occurrence_id: str, *, now_utc: datetime) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE schedule_occurrences SET lease_owner = NULL, lease_expires_epoch = NULL, updated_utc = ?"
                " WHERE occurrence_id = ?",
                (_iso(now_utc), occurrence_id),
            )

    # ------------------------------------------------------------ lifecycle
    def mark_done(self, occurrence_id: str, *, now_utc: datetime) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE schedule_occurrences SET status = 'done', lease_owner = NULL,"
                " lease_expires_epoch = NULL, updated_utc = ? WHERE occurrence_id = ? AND status != 'cancelled'",
                (_iso(now_utc), occurrence_id),
            )
        return bool(cur.rowcount)

    def snooze(self, occurrence_id: str, minutes: int, *, now_utc: datetime) -> dict[str, Any] | None:
        """顺延：due = now + minutes，状态回 pending，清租约。"""
        new_due = now_utc + timedelta(minutes=minutes)
        stamp = _iso(now_utc)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE schedule_occurrences SET due_epoch = ?, status = 'pending',"
                " lease_owner = NULL, lease_expires_epoch = NULL, updated_utc = ?"
                " WHERE occurrence_id = ? AND status NOT IN ('cancelled', 'done', 'expired')",
                (_epoch(new_due), stamp, occurrence_id),
            )
            if not cur.rowcount:
                return None
        return self.get_occurrence(occurrence_id)

    def cancel_occurrence(self, occurrence_id: str, *, now_utc: datetime) -> dict[str, Any]:
        """取消与发送在租约处线性化：已被活跃租约领取 → in_flight（在途无法保证撤回）。"""
        stamp = _iso(now_utc)
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM schedule_occurrences WHERE occurrence_id = ?", (occurrence_id,)
                ).fetchone()
                if row is None:
                    result: dict[str, Any] = {"status": "not_found"}
                elif row["status"] == "cancelled":
                    result = {"status": "cancelled", "occurrence": _row_to_dict(row)}
                elif row["status"] == "done":
                    result = {"status": "already_done", "occurrence": _row_to_dict(row)}
                elif row["lease_owner"] is not None and (row["lease_expires_epoch"] or 0) > _epoch(now_utc):
                    result = {"status": "in_flight", "occurrence": _row_to_dict(row)}
                else:
                    self._conn.execute(
                        "UPDATE schedule_occurrences SET status = 'cancelled', lease_owner = NULL,"
                        " lease_expires_epoch = NULL, updated_utc = ? WHERE occurrence_id = ?",
                        (stamp, occurrence_id),
                    )
                    fresh = self._conn.execute(
                        "SELECT * FROM schedule_occurrences WHERE occurrence_id = ?", (occurrence_id,)
                    ).fetchone()
                    result = {"status": "cancelled", "occurrence": _row_to_dict(fresh)}
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return result

    def set_status(self, occurrence_id: str, status: str, *, now_utc: datetime) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE schedule_occurrences SET status = ?, updated_utc = ? WHERE occurrence_id = ?",
                (status, _iso(now_utc), occurrence_id),
            )
        return bool(cur.rowcount)

    def supersede_rule(
        self,
        plan_id: str,
        rule_id: str,
        old_revision: int,
        *,
        now_utc: datetime,
    ) -> int:
        """规则改期后：该规则旧版本的未来 pending 实例批量退役为 superseded。"""
        stamp = _iso(now_utc)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE schedule_occurrences SET status = 'superseded', updated_utc = ?"
                " WHERE plan_id = ? AND rule_id = ? AND rule_revision = ? AND status = 'pending'",
                (stamp, plan_id, rule_id, old_revision),
            )
        return cur.rowcount

    def fetch_missed(
        self,
        now_utc: datetime,
        *,
        grace_minutes: int,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """status=pending 且 due 已过的项（reconcile 输入）。走 idx_occ_due。"""
        cutoff = _epoch(now_utc)
        rows = self._conn.execute(
            "SELECT * FROM schedule_occurrences WHERE status = 'pending' AND due_epoch <= ?"
            " ORDER BY due_epoch LIMIT ?",
            (cutoff, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # ----------------------------------------------------------- rate limits
    def log_send(self, owner: str, occurrence_id: str, *, kind: str, now_utc: datetime) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO schedule_send_log (owner, occurrence_id, kind, sent_epoch) VALUES (?, ?, ?, ?)",
                (owner, occurrence_id, kind, _epoch(now_utc)),
            )

    def count_sends(self, owner: str, *, since_utc: datetime) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM schedule_send_log WHERE owner = ? AND sent_epoch >= ?",
            (owner, _epoch(since_utc)),
        ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------ quiet exceptions
    def add_quiet_exception(self, occurrence_id: str, *, owner: str, reason: str, now_utc: datetime) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO schedule_quiet_exceptions (occurrence_id, owner, reason, created_utc)"
                " VALUES (?, ?, ?, ?)",
                (occurrence_id, owner, reason, _iso(now_utc)),
            )

    def list_quiet_exceptions(self, owner: str | None = None) -> list[dict[str, Any]]:
        if owner is None:
            rows = self._conn.execute("SELECT * FROM schedule_quiet_exceptions ORDER BY created_utc").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM schedule_quiet_exceptions WHERE owner = ? ORDER BY created_utc", (owner,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ diagnostics
    def explain_due_query(self) -> str:
        plan = self._conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM schedule_occurrences"
            " WHERE status = 'pending' AND due_epoch <= 1 ORDER BY due_epoch LIMIT 50"
        ).fetchall()
        return "; ".join(r["detail"] for r in plan)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

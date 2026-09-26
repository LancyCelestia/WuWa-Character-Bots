"""日程板存储扩展（第 20 项波）：复用 S11 V2.1 引擎的表与事务，只加查询不加表。

**为什么是子类而不是新表**（AGENTS 无第二真身）：日程的数据模型唯一真身是
``domains/schedule/service/`` 全家（plan/task/rule/occurrence + 租约 + 物化），
配置键 ``bot_schedule_db_path`` 与 runtime_paths 重映射也早已在册。本模块把
「一张个人日程板」映射为 ``plan_id = "board-<owner>"`` 的单个 plan（设计见
docs/design/schedule-board-and-proxy-reply.md §1），这里只补三类引擎门面没有的
**读侧/卫生侧**能力：

1. 按 owner 反查板子（plans.owner 有列无索引查询口）；
2. 改可见性时同步重打已物化的未来 pending 实例标签（payload 只管以后新物化，
   现网实例不改就会「改了开关、旧条目还按旧口径被读到」）；
3. 终态实例的限期物理清理（prune，90 天，写操作顺带跑，失败不阻塞业务）。

schema 零变更 ⇒ 无 ALTER-if-missing；写路径仍全部经 ``ScheduleService``
（乐观 revision、幂等物化、租约线性化），本件不开第二条写口。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from plugins.bot_unified_runtime.domains.schedule.service.schedule_store import (
    ScheduleStore,
)

logger = logging.getLogger(__name__)

BOARD_PLAN_PREFIX = "board-"

#: 终态集合（与 schedule_store 的 STATUS_* 一致；done/digest/skipped/expired/cancelled
#: 再加展开退役的 superseded 与 ask 之后被处理的 ask 不列——ask 还在等人回答，不清）。
_TERMINAL_STATUSES = ("done", "cancelled", "superseded", "expired", "digest", "skipped")

_PURGE_LIMIT_PER_PASS = 500


class ScheduleBoardStore(ScheduleStore):
    """引擎 store 的只加不改扩展（同连接、同 PRAGMA、同锁）。"""

    # --------------------------------------------------------------- 反查
    def plan_id_for_owner(self, owner: str) -> str | None:
        """owner → 板子 plan_id（每 owner 至多一块 board- plan；无则 None）。"""
        row = self._conn.execute(
            "SELECT plan_id FROM schedule_plans WHERE owner = ? AND plan_id LIKE ?"
            " ORDER BY updated_utc ASC LIMIT 1",
            (str(owner), f"{BOARD_PLAN_PREFIX}%"),
        ).fetchone()
        return str(row[0]) if row else None

    def plan_rows_for_owner(self, owner: str) -> list[tuple[str, str]]:
        """owner 的全部 board plans（plan_id, payload_json）——多超管场景兜底。"""
        rows = self._conn.execute(
            "SELECT plan_id, payload_json FROM schedule_plans"
            " WHERE owner = ? AND plan_id LIKE ? ORDER BY updated_utc ASC",
            (str(owner), f"{BOARD_PLAN_PREFIX}%"),
        ).fetchall()
        return [(str(r[0]), str(r[1])) for r in rows]

    # ----------------------------------------------------- 可见性重打（写）
    def retag_future_occurrences(
        self,
        plan_id: str,
        rule_id: str,
        *,
        public: bool,
        after_epoch: float,
        now_utc: datetime | None = None,
    ) -> int:
        """把该规则未来 pending 实例的 ``vis:public`` 标签按新口径重打，返回改动数。

        与 plan payload 的 task.tags 同批更新（调用方保证）：payload 管「以后物化的」，
        本方法管「已经躺在库里的」，两头一致才没有「改了不生效」的半截状态。
        逐行读改写（pending 未来实例数有界：horizon 30 天 × 规则数，不养第二条锁）。
        """
        stamp = (now_utc or datetime.now(UTC)).isoformat()
        touched = 0
        with self._lock, self._conn:
            # 读也在锁内：与写同事务窗口，避免「读后标签被并发改写再盲覆盖」。
            rows = self._conn.execute(
                "SELECT occurrence_id, tags_json FROM schedule_occurrences"
                " WHERE plan_id = ? AND rule_id = ? AND status = 'pending' AND due_epoch > ?",
                (plan_id, rule_id, after_epoch),
            ).fetchall()
            for row in rows:
                try:
                    tags = json.loads(row[1] or "[]")
                except ValueError:
                    tags = []
                has_public = "vis:public" in tags
                if has_public == public:
                    continue
                tags = [t for t in tags if t != "vis:public"]
                if public:
                    tags.append("vis:public")
                self._conn.execute(
                    "UPDATE schedule_occurrences SET tags_json = ?, updated_utc = ?"
                    " WHERE occurrence_id = ?",
                    (json.dumps(tags, ensure_ascii=False), stamp, row[0]),
                )
                touched += 1
        return touched

    # ------------------------------------------------- 卫生：终态限期清理
    def purge_terminal(self, *, before_epoch: float, limit: int = _PURGE_LIMIT_PER_PASS) -> int:
        """物理删除 ``due_epoch < before_epoch`` 的终态实例（写操作顺带调用）。

        只删实例行，绝不动 plans（板子本体与历史事实留在 payload 里，诚实可溯）；
        绝不动订阅式资产——本表没有。失败由调用方吞并记日志，清理不阻塞记录。
        """
        placeholders = ",".join("?" for _ in _TERMINAL_STATUSES)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"DELETE FROM schedule_occurrences WHERE occurrence_id IN ("
                f" SELECT occurrence_id FROM schedule_occurrences"
                f" WHERE status IN ({placeholders}) AND due_epoch < ? LIMIT ?)",
                (*_TERMINAL_STATUSES, before_epoch, int(limit)),
            )
            return int(cursor.rowcount or 0)


# ---------------------------------------------------------------------------
# 进程级共享构造（提醒域 build_reminder_store 同族口径：同路径单例，防连接泄漏）
# ---------------------------------------------------------------------------
_BOARD_STORES: dict[str, ScheduleBoardStore] = {}
_BOARD_STORES_LOCK = threading.Lock()


def build_board_store(config: Any | None = None) -> ScheduleBoardStore:
    """日程板 store（生产装配点）：路径走 ``bot_schedule_db_path`` + runtime_paths 重映射。

    时区口径绑定与提醒链路同源（``configure_reminder_timezone``），日程自然语言
    解析（reminders.parse_time_target）与展示换算共用这一把配置时区尺。
    """
    from scripts.runtime_paths import runtime_path

    from plugins.bot_unified_runtime.domains.schedule.store.reminders import (
        configure_reminder_timezone,
    )

    configure_reminder_timezone(str(getattr(config, "bot_timezone", "") or ""))
    raw = str(getattr(config, "bot_schedule_db_path", "data/schedules_v21.sqlite3") or
               "data/schedules_v21.sqlite3")
    path = str(runtime_path(raw))
    with _BOARD_STORES_LOCK:
        store = _BOARD_STORES.get(path)
        if store is None:
            store = ScheduleBoardStore(path)
            _BOARD_STORES[path] = store
        return store


def build_board_service(config: Any | None = None) -> Any:
    """日程板门面（复用 ScheduleService，store 用本件子类）。"""
    from plugins.bot_unified_runtime.domains.schedule.service.schedule_service import (
        ScheduleService,
    )

    return ScheduleService(build_board_store(config))


def purge_horizon_days() -> int:
    """终态实例保留天数（存储卫生常量；设计规格 §4，不做成配置键）。"""
    return 90


def purge_cutoff_epoch(now_utc: datetime | None = None, *, retention_days: int | None = None) -> float:
    """prune 分界（epoch 秒）：早于该时刻的终态实例可清理。"""
    current = now_utc or datetime.now(UTC)
    days = purge_horizon_days() if retention_days is None else max(1, int(retention_days))
    return (current - timedelta(days=days)).timestamp()


__all__ = [
    "BOARD_PLAN_PREFIX",
    "ScheduleBoardStore",
    "build_board_service",
    "build_board_store",
    "purge_cutoff_epoch",
    "purge_horizon_days",
]

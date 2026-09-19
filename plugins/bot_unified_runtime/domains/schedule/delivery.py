"""S11 余量交付③——occurrence 到点真实投递接线（V2.1 §4.2 调度/投递半边）。

职责边界：
- 消费 W10 引擎（``domains.schedule.service.ScheduleService``，只读复用禁改）：
  ``claim_due``（精确一次租约）→ ``split_quiet_hours``（安静时间门）→
  ``acquire_send_slot``（防风暴门：每分钟 3/每小时 20，超限 digest 合并）→
  ``snooze`` / ``set_status``（复用既有状态机面；snooze 自带清租约回 pending）。
- 出站只走既有 SendQueue 的 ``submit`` 面（鸭子类型消费 ``SendQueue`` 协议，
  **不 import transport 本体、不改 sender**）：``deliver_after=now`` 显式声明
  无内联首投（后台投递语义，worker 认领）。**真实出站端口未授权**——本层到
  队列提交为止，receipt 状态按返回值如实记录；绝不绕队列直发。
- 失败重试：submit 抛错/FAILED_RETRYABLE → ``snooze`` 指数退避（复用引擎续投
  语义），超过 ``max_retries`` → ``delivery_failed`` 终态。重试计数在本服务实例
  内存记账（进程重启归零属已知边界：重启本就伴随 reconcile 重新分流）。
- 调休/节假日例外表：``CalendarExceptions``（数据文件+加载器）。**未知年份=
  unknown 不猜**；只有显式登记的 holiday/workday 才改变投递（follow_calendar
  标签选择性生效），unknown 照常投递但在回执里如实标注。
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from plugins.bot_unified_runtime.domains.schedule.service.schedule_service import (
    ScheduleService,
)

__all__ = [
    "CalendarExceptions",
    "DeliveryOutcome",
    "DeliveryTickReport",
    "ScheduleDeliveryService",
    "build_schedule_delivery_service",
]

_logger = logging.getLogger(__name__)

# 例外表缺省模板（随包数据文件；管理员可经 config 指向自己的补录文件）。
_DEFAULT_EXCEPTIONS_ASSET = Path(__file__).resolve().parent / "data" / "calendar_exceptions.json"

_DEFAULT_RETRY_BASE_SECONDS = 60


class _QueueProtocol(Protocol):
    """SendQueue 协议的鸭子切片（只消费 submit；不 import transport 本体）。"""

    def submit(self, send_request: Any, *, deliver_after: datetime | None = None) -> Any: ...


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeliveryOutcome(_Strict):
    """单条实例的投递回执（诚实记录；receipt_state 取队列返回值原样）。"""

    occurrence_id: str
    status: str  # submitted|deferred_quiet|digest|retry_scheduled|delivery_failed|calendar_deferred|not_authorized
    receipt_state: str = ""  # queue 返回的 DeliveryReceipt.state.value；未提交=空
    detail: str = ""


class DeliveryTickReport(_Strict):
    checked: int = 0
    outcomes: list[DeliveryOutcome] = Field(default_factory=list)


class CalendarExceptions:
    """调休/节假日例外表加载器（数据文件 + unknown 语义）。

    - ``resolve(day)`` 返回 ``"holiday" | "workday" | "regular" | "unknown"``；
      **年份不在表或日期键缺失一律 unknown**——unknown 绝不当作 holiday 也不
      当作 regular 宣称，投递层只在显式 known 时改变行为。
    - 文件缺失/JSON 坏 → 空表（全部 unknown），不抛异常不臆造数据。
    """

    def __init__(self, table: dict[str, dict[str, dict[str, str]]] | None = None) -> None:
        self._table: dict[str, dict[str, dict[str, str]]] = table or {}

    @classmethod
    def load(cls, *paths: Path | str | None) -> CalendarExceptions:
        merged: dict[str, dict[str, dict[str, str]]] = {}
        for path in paths:
            if not path:
                continue
            candidate = Path(str(path))
            if not candidate.is_file():
                continue
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _logger.warning("schedule exceptions file unreadable: %s", candidate)
                continue
            exceptions = payload.get("exceptions") if isinstance(payload, dict) else None
            if not isinstance(exceptions, dict):
                continue
            for year, entry in exceptions.items():
                if not isinstance(entry, dict):
                    continue
                slot = merged.setdefault(str(year), {"holidays": {}, "workdays": {}})
                for kind in ("holidays", "workdays"):
                    section = entry.get(kind)
                    if isinstance(section, dict):
                        slot[kind].update({str(k): str(v) for k, v in section.items()})
        return cls(merged)

    @classmethod
    def load_default(cls, overlay_path: Path | str | None = None) -> CalendarExceptions:
        """随包模板 + 管理员 overlay（后者优先，同键覆盖）。"""
        return cls.load(_DEFAULT_EXCEPTIONS_ASSET, overlay_path)

    def resolve(self, day: date) -> str:
        entry = self._table.get(str(day.year))
        if entry is None:
            return "unknown"
        key = day.isoformat()
        if key in entry.get("holidays", {}):
            return "holiday"
        if key in entry.get("workdays", {}):
            return "workday"
        return "unknown"

    def years_known(self) -> list[int]:
        return sorted(int(y) for y in self._table if str(y).isdigit())


class ScheduleDeliveryService:
    """occurrence→SendQueue 投递门面（quiet/storm 门全部复用引擎）。"""

    def __init__(
        self,
        service: ScheduleService,
        queue: _QueueProtocol | None,
        *,
        calendar: CalendarExceptions | None = None,
        max_retries: int = 3,
        retry_base_seconds: float = _DEFAULT_RETRY_BASE_SECONDS,
        clock: Any = None,
        request_builder: Any = None,
    ) -> None:
        self._service = service
        self._queue = queue
        self._calendar = calendar or CalendarExceptions()
        self.max_retries = max(1, int(max_retries))
        self.retry_base_seconds = max(1.0, float(retry_base_seconds))
        self._clock = clock  # 可注入 now() -> datetime（UTC aware）
        # request_builder(owner, occurrence_row) -> SendRequest：DI 出站构造
        # （生产接线席注入真实构造器；None=干跑，只到 decision 为止）。
        self._request_builder = request_builder
        self._attempts: dict[str, int] = {}

    # ------------------------------------------------------------------ 时钟
    def _now(self) -> datetime:
        value = self._clock() if self._clock is not None else datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    # ------------------------------------------------------------------ 主循环
    def delivery_tick(
        self, worker_id: str = "schedule-delivery", *, limit: int = 50
    ) -> DeliveryTickReport:
        """领取到期→安静分流→风暴门→队列提交→回执落账（单轮；轮询由装配席驱动）。"""
        report = DeliveryTickReport()
        now = self._now()
        claimed = self._service.claim_due(worker_id, limit=limit)
        report.checked = len(claimed)
        if not claimed:
            return report
        split = self._service.split_quiet_hours(claimed)
        for row in split.deferred:
            report.outcomes.append(
                DeliveryOutcome(
                    occurrence_id=str(row["occurrence_id"]),
                    status="deferred_quiet",
                    detail=f"deferred_to={row.get('deferred_to_utc', '')}",
                )
            )
        plans = self._plan_cache(split.deliver_now)
        for row in split.deliver_now:
            owner, tzname = plans[str(row["plan_id"])]
            report.outcomes.append(self._deliver_one(owner, tzname, row, now=now))
        return report

    # ------------------------------------------------------------------ 单条投递
    def _deliver_one(
        self,
        owner: str,
        tzname: str,
        row: dict[str, Any],
        *,
        now: datetime,
    ) -> DeliveryOutcome:
        occurrence_id = str(row["occurrence_id"])
        # 校历例外（只对显式 follow_calendar 标签生效；unknown 照常投递并标注）。
        calendar_status = self._calendar_check(row, tzname)
        if calendar_status == "holiday":
            self._service.snooze(occurrence_id, 24 * 60)
            return DeliveryOutcome(
                occurrence_id=occurrence_id,
                status="calendar_deferred",
                detail="known holiday; snoozed 1 day",
            )

        decision = self._service.acquire_send_slot(owner, occurrence_id)
        if decision.decision == "digest":
            self._service._store.set_status(occurrence_id, "digest", now_utc=now)
            return DeliveryOutcome(
                occurrence_id=occurrence_id,
                status="digest",
                detail=decision.reason,
            )

        if self._queue is None or self._request_builder is None:
            # 干跑/未授权出站：租约释放保持 pending，回执如实记 not_authorized。
            self._service.release_lease(occurrence_id)
            return DeliveryOutcome(
                occurrence_id=occurrence_id,
                status="not_authorized",
                detail="queue or request_builder not wired; real outbound port unauthorized",
            )

        request = self._request_builder(owner, row)
        attempt = self._attempts.get(occurrence_id, 0) + 1
        try:
            receipt = self._queue.submit(request, deliver_after=now)
        except Exception as exc:  # noqa: BLE001 - 队列异常→退避重试，绝不悬挂租约
            return self._schedule_retry(
                occurrence_id, attempt, reason=type(exc).__name__, now=now
            )
        state = str(getattr(getattr(receipt, "state", None), "value", "") or "")
        if state == "failed_retryable":
            return self._schedule_retry(
                occurrence_id, attempt, reason=f"receipt={state}", now=now
            )
        if state in ("failed_final", "blocked"):
            self._service._store.set_status(occurrence_id, "delivery_failed", now_utc=now)
            return DeliveryOutcome(
                occurrence_id=occurrence_id,
                status="delivery_failed",
                receipt_state=state,
                detail="terminal receipt from queue",
            )
        self._service._store.set_status(occurrence_id, "queued", now_utc=now)
        return DeliveryOutcome(
            occurrence_id=occurrence_id,
            status="submitted",
            receipt_state=state or "queued",
            detail=f"calendar={calendar_status}" if calendar_status == "unknown" else "",
        )

    # ------------------------------------------------------------------ 辅助
    def _plan_cache(self, rows: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
        """plan_id → (owner, timezone)；只读消费 store 现有查询面。"""
        cache: dict[str, tuple[str, str]] = {}
        for row in rows:
            plan_id = str(row["plan_id"])
            if plan_id in cache:
                continue
            stored = self._service._store.get_plan(plan_id)
            if stored is None:
                cache[plan_id] = (plan_id, "UTC")
                continue
            try:
                ZoneInfo(str(stored["payload"].get("timezone") or "UTC"))
                tzname = str(stored["payload"].get("timezone") or "UTC")
            except Exception:  # noqa: BLE001 - 时区坏→UTC 兜底（不阻断投递）
                tzname = "UTC"
            cache[plan_id] = (str(stored["owner"]), tzname)
        return cache

    def _calendar_check(self, row: dict[str, Any], tzname: str) -> str:
        tags = row.get("tags") or []
        if "follow_calendar" not in tags:
            return "regular"
        scheduled = datetime.fromisoformat(str(row["scheduled_at_utc"]))
        try:
            local_day = scheduled.astimezone(ZoneInfo(tzname)).date()
        except Exception:  # noqa: BLE001 - 时区坏→UTC 日
            local_day = scheduled.astimezone(timezone.utc).date()
        return self._calendar.resolve(local_day)

    def _schedule_retry(
        self,
        occurrence_id: str,
        attempt: int,
        *,
        reason: str,
        now: datetime,
    ) -> DeliveryOutcome:
        """退避重试：snooze 回 pending（自带清租约）；超限→delivery_failed 终态。"""
        self._attempts[occurrence_id] = attempt
        if attempt >= self.max_retries:
            self._service._store.set_status(occurrence_id, "delivery_failed", now_utc=now)
            self._attempts.pop(occurrence_id, None)
            return DeliveryOutcome(
                occurrence_id=occurrence_id,
                status="delivery_failed",
                detail=f"retries exhausted ({attempt}/{self.max_retries}): {reason}",
            )
        delay_minutes = max(1, int(self.retry_base_seconds * (2 ** max(0, attempt - 1)) // 60))
        self._service.snooze(occurrence_id, delay_minutes)
        return DeliveryOutcome(
            occurrence_id=occurrence_id,
            status="retry_scheduled",
            detail=f"attempt={attempt} backoff_minutes={delay_minutes} reason={reason}",
        )


def build_schedule_delivery_service(
    config: Any,
    queue: _QueueProtocol | None,
    *,
    service: ScheduleService | None = None,
    request_builder: Any = None,
    clock: Any = None,
) -> ScheduleDeliveryService:
    """生产装配位：config 只读 getattr（键见 config.py bot_schedule_* 键块）。

    ``queue`` 由接线席传入既有 SendQueue 实例（本席不 import transport 本体、
    不构造队列）；``request_builder`` 同为接线席注入的出站构造器。真实出站
    端口未授权前传 None → tick 只到 decision 干跑为止（诚实不伪装成功）。
    """
    if service is None:
        from plugins.bot_unified_runtime.domains.schedule.service.schedule_service import (
            build_schedule_service,
        )

        service = build_schedule_service(config)
    overlay = getattr(config, "bot_schedule_exceptions_path", "") or None
    return ScheduleDeliveryService(
        service,
        queue,
        calendar=CalendarExceptions.load_default(overlay),
        max_retries=int(getattr(config, "bot_schedule_delivery_max_retries", 3) or 3),
        clock=clock,
        request_builder=request_builder,
    )

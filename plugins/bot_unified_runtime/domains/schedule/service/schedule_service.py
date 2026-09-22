"""S11 日程链确定性核心——服务门面（V2.1 §4）。

接线位说明：
- ``build_schedule_service(config)`` 是后续生产接线的唯一装配点（config 只读
  getattr，不依赖 config.py 具体字段；默认库路径 data/schedules_v21.sqlite3 经
  scripts/runtime_paths 重映射）。LLM 草稿解析 / 课表截图识别 / 真实投递不在此层，
  发送面只消费本层产出的 ``SendDecision`` / ``DigestBundle`` / claim 租约结果。
- 函数对照合同 §4.2：parse_plan / validate_plan_dag(dag) / resolve_calendar /
  expand_occurrences(rrule) / preview_reschedule / confirm_plan / claim_due /
  mark_task_done / snooze / cancel_occurrence / reconcile_missed 全部落位；
  recognize_timetable 属课表截图识别（LLM/视觉），不在确定性核心（遗留项）。
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from plugins.bot_unified_runtime.domains.schedule.service.schedule_dag import (
    DagValidationResult,
    Occurrence,
    QuietHours,
    RecurrenceRule,
    ScheduleError,
    ScheduleErrorCode,
    SchedulePlan,
    validate_plan_dag,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_rrule import (
    DEFAULT_HORIZON_DAYS,
    DEFAULT_MAX_OCCURRENCES,
    ExpansionResult,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_rrule import (
    expand_occurrences as expand_plan_occurrences,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_store import (
    DEFAULT_CLAIM_LIMIT,
    DEFAULT_LEASE_SECONDS,
    DEFAULT_POLL_SECONDS,
    ScheduleStore,
)

# v21r2 W10 随迁：domains/schedule/service/ 比原 runtime/ 深两层，parents[3]→[5]
# 仍解析到工作区根（sys.path 注入语义不变）。
_PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class _Base(BaseModel):
    """DTO 基类：禁未知字段（风格对齐 contracts/runtime.StrictBaseModel）。"""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class RescheduleChange(_Base):
    """改期请求：以规则为目标（时间住在 rule.local_time）。"""

    rule_id: str
    new_local_time: str | None = None  # "HH:MM"
    shift_minutes: int = 0  # 或整体平移（负=提前）

    @property
    def is_noop(self) -> bool:
        return self.new_local_time is None and self.shift_minutes == 0


class RescheduleDiffEntry(_Base):
    rule_id: str
    occurrence_id: str
    old_at_utc: str
    new_at_utc: str
    title: str
    soft: bool


class RescheduleConflict(_Base):
    code: str  # schedule_conflict（硬预约不许静默顺延 / 硬碰撞）
    rule_id: str
    message: str
    task_ids: list[str] = Field(default_factory=list)


class ReschedulePreview(_Base):
    ok: bool
    diff: list[RescheduleDiffEntry] = Field(default_factory=list)
    conflicts: list[RescheduleConflict] = Field(default_factory=list)
    new_revision: int | None = None


class ReconcileReport(_Base):
    checked: int = 0
    late_send_once: list[str] = Field(default_factory=list)  # grace 内保持 pending 迟发一次
    digested: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    ask: list[str] = Field(default_factory=list)
    expired: list[str] = Field(default_factory=list)  # 抢票类 → occurrence_expired


class ReminderItem(_Base):
    reminder_id: str  # 每 offset 唯一（hash(occurrence_id, offset)）
    occurrence_id: str
    offset_minutes: int
    due_utc: str


class QuietSplit(_Base):
    deliver_now: list[dict[str, Any]] = Field(default_factory=list)
    deferred: list[dict[str, Any]] = Field(default_factory=list)  # 已顺延至安静结束


class SendDecision(_Base):
    decision: str  # allow | digest
    reason: str = ""


class DigestBundle(_Base):
    owner: str
    total: int = 0
    items: list[dict[str, Any]] = Field(default_factory=list)


def parse_plan(payload: dict[str, Any]) -> SchedulePlan:
    """确定性 dict→SchedulePlan（合同 parse_plan 的确定性半边；LLM 草稿解析不在本层）。"""
    return SchedulePlan.model_validate(payload)


def _shift_hhmm(hhmm: str, minutes: int) -> str:
    """HH:MM 环语义平移（支持跨午夜/负向），纯分钟算术不引入 naive datetime。"""
    hh, mm = hhmm.split(":")
    total = (int(hh) * 60 + int(mm) + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


class ScheduleService:
    def __init__(
        self,
        store: ScheduleStore,
        *,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        horizon_days: int = DEFAULT_HORIZON_DAYS,
        max_occurrences: int = DEFAULT_MAX_OCCURRENCES,
        max_sends_per_minute: int = 3,
        max_sends_per_hour: int = 20,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.poll_seconds = poll_seconds
        self.horizon_days = horizon_days
        self.max_occurrences = max_occurrences
        self.max_sends_per_minute = max_sends_per_minute
        self.max_sends_per_hour = max_sends_per_hour

    # ------------------------------------------------------------------ clock
    def now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    # ------------------------------------------------------------ plan 生命周期
    def submit_plan(
        self,
        plan: SchedulePlan,
        *,
        expected_revision: int | None = None,
        confirm: bool = False,
    ) -> DagValidationResult:
        """校验 DAG → 版本校验 → 落库（draft 或 active）。循环直接抛 schedule_cycle。"""
        validation = validate_plan_dag(plan)
        if not validation.ok:
            code = validation.first_code() or ScheduleErrorCode.SCHEDULE_CYCLE
            raise ScheduleError(code, validation.issues[0].message)
        existing = self._store.get_plan(plan.plan_id)
        if existing is not None:
            if expected_revision is None:
                raise ScheduleError(
                    ScheduleErrorCode.VERSION_CONFLICT,
                    f"plan {plan.plan_id} exists; expected_revision is required to overwrite",
                )
            if int(existing["revision"]) != expected_revision:
                raise ScheduleError(
                    ScheduleErrorCode.VERSION_CONFLICT,
                    f"plan {plan.plan_id} revision {existing['revision']} != expected {expected_revision}",
                )
        if confirm:
            plan = plan.model_copy(update={"state": "active"})
        self._store.upsert_plan(plan, payload_json=plan.model_dump_json(), now_utc=self.now())
        return validation

    def get_plan(self, plan_id: str) -> SchedulePlan:
        stored = self._store.get_plan(plan_id)
        if stored is None:
            raise ScheduleError(ScheduleErrorCode.MISSING_CALENDAR, f"plan {plan_id} not found")
        return SchedulePlan.model_validate(stored["payload"])

    def confirm_plan(self, plan_id: str, *, expected_revision: int | None = None) -> SchedulePlan:
        plan = self.get_plan(plan_id)
        if expected_revision is not None and plan.revision != expected_revision:
            raise ScheduleError(
                ScheduleErrorCode.VERSION_CONFLICT,
                f"plan {plan_id} revision {plan.revision} != expected {expected_revision}",
            )
        validate_plan_dag(plan)  # 确认前重新校验版本与结构
        active = plan.model_copy(update={"state": "active"})
        self._store.upsert_plan(active, payload_json=active.model_dump_json(), now_utc=self.now())
        return active

    # -------------------------------------------------------------- 日历与展开
    def resolve_calendar(
        self,
        plan: SchedulePlan | str,
        *,
        horizon_days: int | None = None,
    ) -> dict[str, list[str]]:
        """每条规则在物化窗口内的本地日期序列（展示口径：本地日）。"""
        plan = self.get_plan(plan) if isinstance(plan, str) else plan
        tz = ZoneInfo(plan.timezone)
        now_utc = self.now()
        local_today = now_utc.astimezone(tz).date()
        days = horizon_days or self.horizon_days
        window_end = local_today + timedelta(days=days)

        from plugins.bot_unified_runtime.domains.schedule.service.schedule_rrule import (
            iter_rule_dates,
        )

        return {
            rule.rule_id: [d.isoformat() for d in iter_rule_dates(rule, local_today, window_end)]
            for rule in plan.rules
        }

    def expand_occurrences(self, plan: SchedulePlan | str) -> ExpansionResult:
        """物化未来 horizon_days 实例并落库（幂等）；返回 ExpansionResult。"""
        plan = self.get_plan(plan) if isinstance(plan, str) else plan
        result = expand_plan_occurrences(
            plan,
            now_utc=self.now(),
            horizon_days=self.horizon_days,
            max_occurrences=self.max_occurrences,
        )
        result.inserted_ids = [occ.occurrence_id for occ in result.occurrences]
        new_rows = self._store.upsert_occurrences(result.occurrences, now_utc=self.now())
        result.notes.append(f"upserted={len(result.occurrences)} new_rows={new_rows}")
        return result

    # ------------------------------------------------------------------ 改期
    def preview_reschedule(
        self,
        plan_id: str,
        changes: list[RescheduleChange],
        *,
        expected_revision: int,
    ) -> ReschedulePreview:
        """软时间窗 → diff + new_revision；硬预约 → schedule_conflict 不静默顺延。

        附带硬碰撞检测：改动后若两条硬规则实例落到同一本地日+同一本地时刻 → conflict。
        """
        plan = self.get_plan(plan_id)
        if plan.revision != expected_revision:
            raise ScheduleError(
                ScheduleErrorCode.VERSION_CONFLICT,
                f"plan {plan_id} revision {plan.revision} != expected {expected_revision}",
            )
        preview = ReschedulePreview(ok=True)
        rule_index = {r.rule_id: r for r in plan.rules}
        task_index = {t.task_id: t for t in plan.tasks}

        from plugins.bot_unified_runtime.domains.schedule.service.schedule_rrule import (
            occurrence_identity,
            resolve_local,
        )

        tz = ZoneInfo(plan.timezone)
        calendar = self.resolve_calendar(plan)

        def effective_time(rule: RecurrenceRule) -> str:
            change = next((c for c in changes if c.rule_id == rule.rule_id), None)
            if change is None or change.is_noop:
                return rule.local_time
            if change.new_local_time is not None:
                return change.new_local_time
            return _shift_hhmm(rule.local_time, change.shift_minutes)

        for change in changes:
            rule = rule_index.get(change.rule_id)
            if rule is None:
                preview.ok = False
                preview.conflicts.append(
                    RescheduleConflict(
                        code=ScheduleErrorCode.SCHEDULE_CONFLICT,
                        rule_id=change.rule_id,
                        message=f"unknown rule {change.rule_id}",
                    )
                )
                continue
            task = task_index.get(rule.task_id)
            old_time = rule.local_time
            new_time = effective_time(rule)
            if new_time == old_time or change.is_noop:
                continue
            soft = bool(task and task.soft_window_minutes > 0)
            if not soft:
                preview.ok = False
                preview.conflicts.append(
                    RescheduleConflict(
                        code=ScheduleErrorCode.SCHEDULE_CONFLICT,
                        rule_id=rule.rule_id,
                        message=(
                            f"rule {rule.rule_id} drives hard booking of task {rule.task_id};"
                            " explicit re-booking required (no silent shift)"
                        ),
                        task_ids=[rule.task_id],
                    )
                )
                continue
            for day_str in calendar.get(rule.rule_id, []):
                day = date.fromisoformat(day_str)
                old_res = resolve_local(tz, day, old_time)
                new_res = resolve_local(tz, day, new_time)
                preview.diff.append(
                    RescheduleDiffEntry(
                        rule_id=rule.rule_id,
                        occurrence_id=occurrence_identity(rule.rule_id, rule.rule_revision, old_res.utc_value),
                        old_at_utc=old_res.utc_value.isoformat(),
                        new_at_utc=new_res.utc_value.isoformat(),
                        title=task.title if task else rule.rule_id,
                        soft=True,
                    )
                )

        # 硬碰撞检测：以改动后的有效时刻两两比对（同日同时刻的两条硬规则 → conflict）。
        seen: dict[str, str] = {}
        for rule in plan.rules:
            task = task_index.get(rule.task_id)
            if task is None or not task.is_hard:
                continue
            stamp = effective_time(rule)
            for day_str in calendar.get(rule.rule_id, []):
                key = f"{day_str}T{stamp}"
                prior = seen.get(key)
                if prior is not None and prior != rule.rule_id:
                    preview.ok = False
                    preview.conflicts.append(
                        RescheduleConflict(
                            code=ScheduleErrorCode.SCHEDULE_CONFLICT,
                            rule_id=rule.rule_id,
                            message=f"hard occurrences collide at {key}",
                            task_ids=[rule.task_id],
                        )
                    )
                elif prior is None:
                    seen[key] = rule.rule_id

        preview.new_revision = plan.revision + 1
        return preview

    def apply_reschedule(
        self,
        plan_id: str,
        changes: list[RescheduleChange],
        *,
        expected_revision: int,
    ) -> ReschedulePreview:
        """确认改期：版本重校验 → 应用 → 旧版本未来实例退役 → 重物化。"""
        preview = self.preview_reschedule(plan_id, changes, expected_revision=expected_revision)
        if not preview.ok:
            return preview
        plan = self.get_plan(plan_id)
        now = self.now()
        superseded = 0
        for change in changes:
            if change.is_noop:
                continue
            rule = next((r for r in plan.rules if r.rule_id == change.rule_id), None)
            if rule is None:
                continue
            if change.new_local_time is not None:
                rule.local_time = change.new_local_time
            else:
                rule.local_time = _shift_hhmm(rule.local_time, change.shift_minutes)
            superseded += self._store.supersede_rule(plan_id, rule.rule_id, rule.rule_revision, now_utc=now)
            rule.rule_revision += 1
        bumped = plan.model_copy(update={"revision": plan.revision + 1})
        self._store.upsert_plan(bumped, payload_json=bumped.model_dump_json(), now_utc=now)
        self.expand_occurrences(bumped)
        preview.new_revision = bumped.revision
        return preview

    # ------------------------------------------------------------- 租约与生命周期
    def claim_due(self, worker_id: str, *, limit: int = DEFAULT_CLAIM_LIMIT) -> list[dict[str, Any]]:
        return self._store.claim_due(
            self.now(), worker_id=worker_id, limit=limit, lease_seconds=DEFAULT_LEASE_SECONDS
        )

    def mark_task_done(self, occurrence_id: str) -> bool:
        return self._store.mark_done(occurrence_id, now_utc=self.now())

    def snooze(self, occurrence_id: str, minutes: int) -> dict[str, Any] | None:
        return self._store.snooze(occurrence_id, minutes, now_utc=self.now())

    def cancel_occurrence(self, occurrence_id: str) -> dict[str, Any]:
        return self._store.cancel_occurrence(occurrence_id, now_utc=self.now())

    def release_lease(self, occurrence_id: str) -> None:
        self._store.release_lease(occurrence_id, now_utc=self.now())

    # ------------------------------------------------------------------ 错过
    def reconcile_missed(self, *, grace_minutes: int = 15) -> ReconcileReport:
        """离线恢复：到期未处理的 pending 实例按策略分流。

        - rush 类（tags 含 rush）→ expired（occurrence_expired，绝不当"即将开售"）
        - 其余按 plan reminder_policy.missed_policy：
            send_once → grace 内保持 pending（迟发一次），超出 → digest
            digest/skip/ask → 直接落对应状态
        重启后用新 store 句柄再跑一遍即为 reconcile 到期项。
        """
        now = self.now()
        report = ReconcileReport()
        missed = self._store.fetch_missed(now, grace_minutes=grace_minutes)
        report.checked = len(missed)
        plan_cache: dict[str, SchedulePlan] = {}
        for row in missed:
            plan = plan_cache.get(row["plan_id"])
            if plan is None:
                stored = self._store.get_plan(row["plan_id"])
                if stored is None:
                    continue
                plan = SchedulePlan.model_validate(stored["payload"])
                plan_cache[row["plan_id"]] = plan
            tags = row.get("tags") or []
            occ_id = row["occurrence_id"]
            if "rush" in tags:
                self._store.set_status(occ_id, "expired", now_utc=now)
                report.expired.append(occ_id)
                continue
            policy = plan.reminder_policy
            age_minutes = (now - datetime.fromisoformat(row["scheduled_at_utc"])).total_seconds() / 60.0
            missed_policy = policy.missed_policy
            if missed_policy == "send_once":
                if age_minutes <= (grace_minutes if grace_minutes is not None else policy.grace_minutes):
                    report.late_send_once.append(occ_id)  # 保持 pending，投递层迟发一次
                    continue
                self._store.set_status(occ_id, "digest", now_utc=now)
                report.digested.append(occ_id)
            elif missed_policy == "digest":
                self._store.set_status(occ_id, "digest", now_utc=now)
                report.digested.append(occ_id)
            elif missed_policy == "skip":
                self._store.set_status(occ_id, "skipped", now_utc=now)
                report.skipped.append(occ_id)
            else:  # ask
                self._store.set_status(occ_id, "ask", now_utc=now)
                report.ask.append(occ_id)
        return report

    # -------------------------------------------------------------- 安静时间
    @staticmethod
    def is_quiet(qh: QuietHours, local_t: time) -> bool:
        start = time.fromisoformat(qh.start)
        end = time.fromisoformat(qh.end)
        if start == end:
            return False
        if start < end:
            return start <= local_t < end
        return local_t >= start or local_t < end  # 跨午夜

    @staticmethod
    def next_quiet_end(qh: QuietHours, local_now: datetime) -> datetime:
        end_t = time.fromisoformat(qh.end)
        candidate = local_now.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate += timedelta(days=1)
        # 若当前不在安静窗内，也返回下一个 end（调用方仅在安静时调用）
        return candidate

    def split_quiet_hours(self, claimed: list[dict[str, Any]]) -> QuietSplit:
        """非紧急 → 顺延至安静结束；urgent 或显式批准例外 → 立即发。"""
        result = QuietSplit()
        now = self.now()
        plan_cache: dict[str, SchedulePlan] = {}
        for row in claimed:
            plan = plan_cache.get(row["plan_id"])
            if plan is None:
                stored = self._store.get_plan(row["plan_id"])
                if stored is None:
                    result.deliver_now.append(row)
                    continue
                plan = SchedulePlan.model_validate(stored["payload"])
                plan_cache[row["plan_id"]] = plan
            tz = ZoneInfo(plan.timezone)
            local_now = now.astimezone(tz)
            if not self.is_quiet(plan.quiet_hours, local_now.time()):
                result.deliver_now.append(row)
                continue
            exceptions = {e["occurrence_id"] for e in self._store.list_quiet_exceptions(plan.owner)}
            policy = plan.reminder_policy
            approved = row["occurrence_id"] in exceptions
            if policy.urgent or approved or policy.quiet_hours_behavior == "send":
                result.deliver_now.append(row)
                continue
            quiet_end_local = self.next_quiet_end(plan.quiet_hours, local_now)
            delay_minutes = max(
                1, int((quiet_end_local - local_now).total_seconds() // 60) + 1
            )
            self._store.snooze(row["occurrence_id"], delay_minutes, now_utc=now)
            deferred_row = dict(row)
            deferred_row["deferred_to_utc"] = quiet_end_local.astimezone(timezone.utc).isoformat()
            result.deferred.append(deferred_row)
        return result

    def approve_quiet_exception(self, occurrence_id: str, *, owner: str, reason: str = "") -> None:
        self._store.add_quiet_exception(occurrence_id, owner=owner, reason=reason, now_utc=self.now())

    def list_quiet_exceptions(self, owner: str | None = None) -> list[dict[str, Any]]:
        return self._store.list_quiet_exceptions(owner)

    # ----------------------------------------------------------------- 防风暴
    def acquire_send_slot(self, owner: str, occurrence_id: str) -> SendDecision:
        """每主体每分钟 ≤3 条、每小时 ≤20 条；超限 → 合并摘要（digest 决策）。

        确定性计数落 schedule_send_log；发送层拿 decision 自行执行（接口留位）。
        """
        now = self.now()
        minute_ago = now - timedelta(seconds=60)
        hour_ago = now - timedelta(seconds=3600)
        in_minute = self._store.count_sends(owner, since_utc=minute_ago)
        in_hour = self._store.count_sends(owner, since_utc=hour_ago)
        if in_minute >= self.max_sends_per_minute:
            self._store.log_send(owner, occurrence_id, kind="digest_merged", now_utc=now)
            return SendDecision(
                decision="digest",
                reason=f"per-minute cap {self.max_sends_per_minute} reached ({in_minute} in last 60s)",
            )
        if in_hour >= self.max_sends_per_hour:
            self._store.log_send(owner, occurrence_id, kind="digest_merged", now_utc=now)
            return SendDecision(
                decision="digest",
                reason=f"per-hour cap {self.max_sends_per_hour} reached ({in_hour} in last hour)",
            )
        self._store.log_send(owner, occurrence_id, kind="immediate", now_utc=now)
        return SendDecision(decision="allow")

    def build_digest(self, owner: str) -> DigestBundle:
        """合并摘要（确定性：按 plan 分组、标题聚合计数）。发送层留接口。"""
        bundle = DigestBundle(owner=owner)
        plan_ids = [
            row["plan_id"]
            for row in self._store.list_occurrences(status="digest")
        ]
        seen_plans: set[str] = set()
        for row in self._store.list_occurrences(status="digest"):
            stored = self._store.get_plan(row["plan_id"])
            if stored is not None and stored["owner"] != owner:
                continue
            if row["plan_id"] not in seen_plans:
                seen_plans.add(row["plan_id"])
            bundle.total += 1
            bundle.items.append(
                {
                    "occurrence_id": row["occurrence_id"],
                    "plan_id": row["plan_id"],
                    "title": row["title"],
                    "scheduled_at_utc": row["scheduled_at_utc"],
                }
            )
        del plan_ids
        return bundle

    # ----------------------------------------------------------------- 提醒
    def build_reminders(self, plan: SchedulePlan, occurrence: Occurrence) -> list[ReminderItem]:
        """默认前 10 分钟 + 准点；单实例 ≤4 条（模型层已钳）。每 offset 唯一 id。"""
        at = datetime.fromisoformat(occurrence.scheduled_at_utc)
        items: list[ReminderItem] = []
        for offset in plan.reminder_policy.offsets_minutes[:4]:
            payload = f"{occurrence.occurrence_id}|{offset}"
            items.append(
                ReminderItem(
                    reminder_id=hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20],
                    occurrence_id=occurrence.occurrence_id,
                    offset_minutes=offset,
                    due_utc=(at + timedelta(minutes=offset)).isoformat(),
                )
            )
        return items


def build_schedule_service(
    config: Any | None = None,
    *,
    store: ScheduleStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ScheduleService:
    """生产装配点（后续接线位）：默认库路径经 runtime_paths 重映射。"""
    if store is None:
        from scripts.runtime_paths import runtime_path

        raw_path = str(getattr(config, "bot_schedule_db_path", "data/schedules_v21.sqlite3") or "data/schedules_v21.sqlite3")
        store = ScheduleStore(runtime_path(raw_path))
    return ScheduleService(store, clock=clock)

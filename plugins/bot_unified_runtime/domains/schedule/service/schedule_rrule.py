"""S11 日程链确定性核心——日历解析与 RRULE 有限子集展开（V2.1 §4.2）。

- UTC 存储 + IANA(zoneinfo) 展示；不随 OS 时区漂移（全部显式传 tz）。
- RRULE 有限子集：once / daily / weekly / weekly_by_day（指定周几）/
  teaching_week（单双教学周，奇偶相对学期起点周，跨年按真实日历）。
- DST：不存在时刻（春季跳变）→ 自动顺延 gap 并提示修正
  （status=corrected_nonexistent）；歧义时刻（秋季回拨）→ fold 语义，
  默认 fold=0 取较早瞬时，status=ambiguous_fold0/1 供上层提示确认。
- occurrence_id = hash(rule_id, rule_revision, scheduled_at_utc)（sha256 截断），
  重复导入幂等；每 plan 物化上限 max_occurrences（默认 1000）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from plugins.bot_unified_runtime.domains.schedule.service.schedule_dag import (
    Occurrence,
    RecurrenceRule,
    RuleKind,
    ScheduleError,
    ScheduleErrorCode,
    SchedulePlan,
    _parse_hhmm,
)

DEFAULT_HORIZON_DAYS = 30
DEFAULT_MAX_OCCURRENCES = 1000


@dataclass(frozen=True)
class LocalTimeResolution:
    """单次「本地墙上时刻 → UTC」解析结果。

    status:
      ok                    —— 唯一确定
      corrected_nonexistent —— DST 春跳不存在时刻，已顺延 gap 修正
      ambiguous_fold0       —— DST 秋跳歧义，取较早瞬时（fold=0）
      ambiguous_fold1       —— DST 秋跳歧义，取较晚瞬时（fold=1）
    """

    status: str
    local_value: datetime
    utc_value: datetime
    note: str = ""


def resolve_local(
    tz: ZoneInfo,
    day: date,
    hhmm: str,
    *,
    fold: int = 0,
    strict: bool = False,
) -> LocalTimeResolution:
    """本地日期+HH:MM → UTC。strict=True 时歧义/不存在直接抛
    ambiguous_local_time（交给用户确认），默认确定性策略自动处理。"""
    hh, mm = _parse_hhmm(hhmm, field="hhmm")
    # 墙上时刻（naive by design）：fold 语义要求先构造 naive 再挂 tz。
    naive = datetime(day.year, day.month, day.day, hh, mm)  # noqa: DTZ001
    dt0 = naive.replace(tzinfo=tz, fold=0)
    dt1 = naive.replace(tzinfo=tz, fold=1)
    off0 = dt0.utcoffset()
    off1 = dt1.utcoffset()
    assert off0 is not None and off1 is not None  # zoneinfo 恒有 offset

    if off0 == off1:
        return LocalTimeResolution("ok", dt0, dt0.astimezone(timezone.utc))

    # offset 随 fold 变化 → 歧义（秋拨）或不存在（春跳）。
    round_trip = dt0.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
    if round_trip == naive:
        # 歧义时刻：两个真实瞬时。
        chosen = dt0 if fold == 0 else dt1
        status = "ambiguous_fold0" if fold == 0 else "ambiguous_fold1"
        note = (
            "clock fallback: local time occurs twice; fold=0 picks the earlier instant"
            if fold == 0
            else "clock fallback: local time occurs twice; fold=1 picks the later instant"
        )
        if strict:
            raise ScheduleError(
                ScheduleErrorCode.AMBIGUOUS_LOCAL_TIME,
                f"{naive} in {tz!s} is ambiguous (DST fallback); explicit fold required",
            )
        return LocalTimeResolution(status, chosen, chosen.astimezone(timezone.utc), note)

    # 不存在时刻（春跳 gap）：顺延 gap 修正（02:30 → 03:30）。
    gap = off1 - off0
    corrected_naive = naive + gap
    corrected = corrected_naive.replace(tzinfo=tz, fold=0)
    note = f"nonexistent local time {naive} corrected forward by {gap}"
    if strict:
        raise ScheduleError(
            ScheduleErrorCode.AMBIGUOUS_LOCAL_TIME,
            f"{naive} in {tz!s} does not exist (DST gap); {note}",
        )
    return LocalTimeResolution("corrected_nonexistent", corrected, corrected.astimezone(timezone.utc), note)


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _week_parity_of(day: date, anchor: date) -> str:
    """教学周奇偶：锚所在周为第 1 周（odd）；按周一锚定。"""
    week_index = (monday_of(day) - monday_of(anchor)).days // 7
    return "odd" if week_index % 2 == 0 else "even"


def iter_rule_dates(rule: RecurrenceRule, window_start: date, window_end: date) -> list[date]:
    """规则在 [window_start, window_end]（本地日）内的日期序列。

    跨年直接走真实日历（date 算术），单双周按周一锚定周数——天然正确。
    """
    if rule.end_date is not None:
        end_bound = date.fromisoformat(rule.end_date)
        window_end = min(window_end, end_bound)
    start = date.fromisoformat(rule.start_date)
    if start > window_end:
        return []
    first = max(start, window_start)

    if rule.kind is RuleKind.ONCE:
        return [start] if window_start <= start <= window_end else []

    days: list[date] = []
    if rule.kind is RuleKind.DAILY:
        cursor = first
        while cursor <= window_end:
            days.append(cursor)
            cursor += timedelta(days=1)
        return days

    if rule.kind is RuleKind.WEEKLY:
        anchor_weekday = start.weekday()
        cursor = first
        # 推进到第一个匹配星期
        while cursor.weekday() != anchor_weekday and cursor <= window_end:
            cursor += timedelta(days=1)
        while cursor <= window_end:
            days.append(cursor)
            cursor += timedelta(days=7)
        return days

    wanted = set(rule.weekdays)
    anchor_raw = rule.parity_anchor_date or rule.start_date
    anchor = date.fromisoformat(anchor_raw)
    wanted_parity = rule.week_parity.value if rule.week_parity is not None else None
    cursor = first
    while cursor <= window_end:
        if cursor.weekday() in wanted and (
            rule.kind is RuleKind.WEEKLY_BY_DAY or _week_parity_of(cursor, anchor) == wanted_parity
        ):
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


@dataclass
class ExpansionResult:
    occurrences: list[Occurrence] = field(default_factory=list)
    inserted_ids: list[str] = field(default_factory=list)
    truncated: bool = False
    notes: list[str] = field(default_factory=list)  # DST 修正/歧义提示

    @property
    def occurrence_ids(self) -> list[str]:
        return [o.occurrence_id for o in self.occurrences]


def occurrence_identity(rule_id: str, rule_revision: int, scheduled_at_utc: datetime) -> str:
    """occurrence_id = hash(rule_id, rule_revision, scheduled_at_utc)（契约 §4.2）。"""
    payload = f"{rule_id}|{int(rule_revision)}|{scheduled_at_utc.astimezone(timezone.utc).isoformat()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def expand_occurrences(
    plan: SchedulePlan,
    *,
    now_utc: datetime,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    max_occurrences: int = DEFAULT_MAX_OCCURRENCES,
    tz: ZoneInfo | None = None,
) -> ExpansionResult:
    """物化未来 horizon_days（默认 30）天的实例；每 plan ≤ max_occurrences。

    只物化 scheduled_at_utc >= now_utc 的实例（未来 30 天口径）。
    幂等：同 rule_revision 同时刻 → 相同 occurrence_id。
    """
    tz = tz or ZoneInfo(plan.timezone)
    now_utc = now_utc.astimezone(timezone.utc)
    local_today = now_utc.astimezone(tz).date()
    window_start = local_today
    window_end = local_today + timedelta(days=horizon_days)

    task_index = {t.task_id: t for t in plan.tasks}
    result = ExpansionResult()
    seen_ids: set[str] = set()

    for rule in plan.rules:
        task = task_index.get(rule.task_id)
        if task is None:
            result.notes.append(f"rule {rule.rule_id} references unknown task {rule.task_id}; skipped")
            continue
        for day in iter_rule_dates(rule, window_start, window_end):
            resolution = resolve_local(tz, day, rule.local_time)
            if resolution.status != "ok":
                result.notes.append(
                    f"rule {rule.rule_id} @ {day} {rule.local_time}: {resolution.status} ({resolution.note})"
                )
            at_utc = resolution.utc_value
            if at_utc < now_utc:
                continue
            occ_id = occurrence_identity(rule.rule_id, rule.rule_revision, at_utc)
            if occ_id in seen_ids:
                continue
            if len(seen_ids) >= max_occurrences:
                result.truncated = True
                result.notes.append(
                    f"plan {plan.plan_id}: occurrence cap {max_occurrences} reached; further instances skipped"
                )
                return result
            seen_ids.add(occ_id)
            result.occurrences.append(
                Occurrence(
                    occurrence_id=occ_id,
                    plan_id=plan.plan_id,
                    rule_id=rule.rule_id,
                    rule_revision=rule.rule_revision,
                    task_id=task.task_id,
                    title=task.title,
                    scheduled_at_utc=at_utc.isoformat(),
                    duration_minutes=task.duration_minutes or 0,
                    tags=list(task.tags),
                )
            )

    result.occurrences.sort(key=lambda o: o.scheduled_at_utc)
    return result

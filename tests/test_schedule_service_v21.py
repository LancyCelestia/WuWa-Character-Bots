"""S11 日程链确定性核心回归（V2.1 §4 / V21-TIME-001 时区部分 + V21-SCHEDULE-002/003）。

全部离线：固定时钟（FixedClock）+ tmp_path 隔离 SQLite；零网络、零 NoneBot 运行时。

覆盖面（对应任务书 10 项）：
- DAG：环检测 schedule_cycle、拓扑序、max_tasks/max_edges 上限、相对链最早窗口
- RRULE：once/daily/weekly/weekly_by_day/teaching_week（单双周）、跨年
- 时区：DST 春跳不存在时刻顺延修正、秋拨 fold 双瞬时、展开注释提示
- 幂等：occurrence_id=hash(rule_id, rule_revision, at)；重复导入零新增；
  rule_revision 变更产生新实例；不同日期同名任务各自独立
- 版本：expected_revision 不符 → version_conflict；preview 改期软窗 diff+新版本、
  硬预约 schedule_conflict 不静默顺延、硬碰撞检测
- 租约：claim_due 到期领取、并发领取唯一（4 线程 4 连接）、limit 上限、
  时间索引导 EXPLAIN QUERY PLAN 走 idx_occ_due
- 竞态：cancel 后 claim 不成功；已 claim 的 cancel 返回 in_flight
- 错过：离线一周 reconcile（grace 内 send_once 保持可投递、超出 digest、
  rush 标 occurrence_expired、skip/ask/digest 策略分流）；重启（新句柄）reconcile
- 防风暴：每分钟 ≤3 / 每小时 ≤20，超限 digest 合并决策
- 安静时间：非紧急延后到安静结束、urgent 与显式例外立即发、例外可查询
- 提醒：默认 -10min+准点、>4 offset 模型拒绝、reminder_id 每 offset 唯一
"""

from __future__ import annotations

import threading
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.domains.core.contracts.errors import get_error_spec
from plugins.bot_unified_runtime.domains.schedule.service.schedule_dag import (
    DEFAULT_MAX_EDGES,
    DEFAULT_MAX_TASKS,
    DependencyEdge,
    Occurrence,
    RecurrenceRule,
    ReminderPolicy,
    ScheduleError,
    SchedulePlan,
    TaskKind,
    TaskTemplate,
    WeekParity,
    compute_earliest,
    validate_plan_dag,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_service import (
    RescheduleChange,
    ScheduleService,
    build_schedule_service,
    parse_plan,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_store import (
    ScheduleStore,
)
from plugins.bot_unified_runtime.runtime.schedule_rrule import (
    iter_rule_dates,
    occurrence_identity,
    resolve_local,
)

# --------------------------------------------------------------------------- 工具
SH = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")


class FixedClock:
    def __init__(self, start: datetime) -> None:
        self._now = start.astimezone(timezone.utc)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now = self._now + timedelta(**kwargs)

    def set(self, value: datetime) -> None:
        self._now = value.astimezone(timezone.utc)


BASE = datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc)  # 北京时间 2026-09-17 11:00


def make_plan(**overrides: object) -> SchedulePlan:
    payload: dict = {
        "plan_id": "plan_main",
        "owner": "user_1",
        "timezone": "Asia/Shanghai",
        "tasks": [
            TaskTemplate(
                task_id="t_class",
                title="高等数学",
                kind=TaskKind.FIXED_TIME,
                fixed_local_time="08:00",
            )
        ],
        "rules": [
            RecurrenceRule(
                rule_id="r_class",
                task_id="t_class",
                kind="weekly_by_day",
                start_date="2026-09-01",
                local_time="08:00",
                weekdays=[0],  # 每周一
            )
        ],
    }
    payload.update(overrides)
    return SchedulePlan.model_validate(payload)


def make_service(tmp_path, clock: FixedClock, **kwargs: object) -> ScheduleService:
    store = ScheduleStore(tmp_path / "schedule.sqlite3")
    return ScheduleService(store, clock=clock, **kwargs)


def materialize_simple(service: ScheduleService, plan: SchedulePlan) -> list[str]:
    service.submit_plan(plan, confirm=True)
    result = service.expand_occurrences(plan)
    return [o.occurrence_id for o in result.occurrences]


# ----------------------------------------------------------------- 1. DAG 校验
class TestDag:
    def test_cycle_rejected_with_schedule_cycle_code(self) -> None:
        plan = make_plan(
            tasks=[
                TaskTemplate(task_id="a", title="A", kind=TaskKind.DURATION, duration_minutes=10),
                TaskTemplate(task_id="b", title="B", kind=TaskKind.DURATION, duration_minutes=10),
                TaskTemplate(task_id="c", title="C", kind=TaskKind.DURATION, duration_minutes=10),
            ],
            edges=[
                DependencyEdge(edge_id="e1", predecessor="a", successor="b"),
                DependencyEdge(edge_id="e2", predecessor="b", successor="c"),
                DependencyEdge(edge_id="e3", predecessor="c", successor="a"),
            ],
        )
        result = validate_plan_dag(plan)
        assert not result.ok
        assert result.issues[0].code == "schedule_cycle"
        assert set(result.issues[0].task_ids) == {"a", "b", "c"}
        with pytest.raises(ScheduleError) as excinfo:
            ScheduleService(ScheduleStore(":memory:")).submit_plan(plan)
        assert excinfo.value.code == "schedule_cycle"

    def test_topological_order_ok(self) -> None:
        plan = make_plan(
            tasks=[
                TaskTemplate(task_id="a", title="A", kind=TaskKind.DURATION, duration_minutes=10),
                TaskTemplate(task_id="b", title="B", kind=TaskKind.DURATION, duration_minutes=10),
                TaskTemplate(task_id="c", title="C", kind=TaskKind.DURATION, duration_minutes=10),
            ],
            edges=[
                DependencyEdge(edge_id="e1", predecessor="a", successor="b"),
                DependencyEdge(edge_id="e2", predecessor="b", successor="c"),
            ],
        )
        result = validate_plan_dag(plan)
        assert result.ok
        assert result.order == ["a", "b", "c"]

    def test_max_tasks_limit(self) -> None:
        tasks = [
            TaskTemplate(task_id=f"t{i}", title=f"T{i}", kind=TaskKind.DURATION, duration_minutes=5)
            for i in range(DEFAULT_MAX_TASKS + 1)
        ]
        result = validate_plan_dag(make_plan(tasks=tasks))
        assert not result.ok
        assert result.issues[0].code == "plan_limit_exceeded"

    def test_max_edges_limit(self) -> None:
        # 100 任务 + 恰好 300 条前向边（gap 1..4 截断到 300，全部向前无环）。
        tasks = [
            TaskTemplate(task_id=f"t{i}", title=f"T{i}", kind=TaskKind.DURATION, duration_minutes=5)
            for i in range(DEFAULT_MAX_TASKS)
        ]
        edges: list[DependencyEdge] = []
        for gap in range(1, 5):
            for i in range(DEFAULT_MAX_TASKS - gap):
                if len(edges) >= DEFAULT_MAX_EDGES:
                    break
                edges.append(
                    DependencyEdge(edge_id=f"e{len(edges)}", predecessor=f"t{i}", successor=f"t{i + gap}")
                )
        assert len(edges) == DEFAULT_MAX_EDGES
        ok_result = validate_plan_dag(make_plan(tasks=tasks, edges=edges))
        assert ok_result.ok
        edges.append(DependencyEdge(edge_id="overflow", predecessor="t0", successor="t5"))
        over_result = validate_plan_dag(make_plan(tasks=tasks, edges=edges))
        assert not over_result.ok
        assert over_result.issues[0].code == "plan_limit_exceeded"

    def test_compute_earliest_relative_chain(self) -> None:
        plan = make_plan(
            tasks=[
                TaskTemplate(
                    task_id="t_wake",
                    title="起床",
                    kind=TaskKind.FIXED_TIME,
                    fixed_local_time="07:00",
                ),
                TaskTemplate(
                    task_id="t_commute",
                    title="通勤",
                    kind=TaskKind.RELATIVE_TO_START,
                    anchor_task_id="t_wake",
                    offset_minutes=30,
                    duration_minutes=40,
                ),
                TaskTemplate(
                    task_id="t_review",
                    title="课前复习",
                    kind=TaskKind.RELATIVE_TO_FINISH,
                    anchor_task_id="t_commute",
                    offset_minutes=-10,
                    duration_minutes=10,
                ),
            ],
        )
        anchor = (datetime(2026, 9, 21, 23, 0, tzinfo=timezone.utc), datetime(2026, 9, 21, 23, 10, tzinfo=timezone.utc))
        windows = compute_earliest(plan, {"t_wake": anchor})
        assert windows["t_commute"] == (
            anchor[0] + timedelta(minutes=30),
            anchor[0] + timedelta(minutes=70),
        )
        assert windows["t_review"] == (
            anchor[0] + timedelta(minutes=60),
            anchor[0] + timedelta(minutes=70),
        )

    def test_compute_earliest_missing_anchor_calendar(self) -> None:
        plan = make_plan()
        with pytest.raises(ScheduleError) as excinfo:
            compute_earliest(plan, {})
        assert excinfo.value.code == "missing_calendar"


# ------------------------------------------------------------ 2. RRULE 与日历
class TestRrule:
    def test_once_daily_weekly_weekday_kinds(self) -> None:
        window_start = date(2026, 9, 7)  # 周一
        window_end = date(2026, 9, 20)  # 两周

        def rule(kind: str, **kw: object) -> RecurrenceRule:
            return RecurrenceRule(
                rule_id="r", task_id="t", kind=kind, start_date="2026-09-07", local_time="08:00", **kw  # type: ignore[arg-type]
            )

        assert iter_rule_dates(rule("once"), window_start, window_end) == [date(2026, 9, 7)]
        daily = iter_rule_dates(rule("daily"), window_start, window_end)
        assert len(daily) == 14
        weekly = iter_rule_dates(rule("weekly"), window_start, window_end)
        assert weekly == [date(2026, 9, 7), date(2026, 9, 14)]
        by_day = iter_rule_dates(rule("weekly_by_day", weekdays=[1, 3]), window_start, window_end)  # 周二/周四
        assert len(by_day) == 4
        assert all(d.weekday() in (1, 3) for d in by_day)

    def test_teaching_week_parity_and_cross_year(self) -> None:
        odd_rule = RecurrenceRule(
            rule_id="r_odd",
            task_id="t",
            kind="teaching_week",
            start_date="2026-09-01",
            local_time="08:00",
            weekdays=[0],
            week_parity=WeekParity.ODD,
            parity_anchor_date="2026-09-07",
        )
        window = (date(2026, 9, 17), date(2026, 10, 17))
        # 窗口内周一：09-21(第3周 odd)、09-28(第4周 even)、10-05(第5周 odd)、10-12(第6周 even)
        assert iter_rule_dates(odd_rule, *window) == [date(2026, 9, 21), date(2026, 10, 5)]
        even_rule = odd_rule.model_copy(update={"week_parity": WeekParity.EVEN})
        assert iter_rule_dates(even_rule, *window) == [date(2026, 9, 28), date(2026, 10, 12)]

    def test_cross_year_dates_via_service(self, tmp_path) -> None:
        clock = FixedClock(datetime(2026, 12, 28, 0, 0, tzinfo=timezone.utc))
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        plan = make_plan(
            tasks=[TaskTemplate(task_id="t_run", title="晨跑", kind=TaskKind.FIXED_TIME, fixed_local_time="07:30")],
            rules=[
                RecurrenceRule(
                    rule_id="r_run", task_id="t_run", kind="daily", start_date="2026-12-01", local_time="07:30"
                )
            ],
        )
        service.submit_plan(plan, confirm=True)
        result = service.expand_occurrences(plan)
        days = [o.scheduled_at_utc[:10] for o in result.occurrences]
        assert any(d.startswith("2026-12") for d in days)
        assert any(d.startswith("2027-01") for d in days)
        # 跨年连续：12-31 → 01-01 相邻两天
        assert "2026-12-31" in days and "2027-01-01" in days


# ------------------------------------------------------- 3. 时区 / DST / fold
class TestTimezone:
    def test_resolve_local_plain(self) -> None:
        res = resolve_local(SH, date(2026, 9, 21), "08:00")
        assert res.status == "ok"
        assert res.utc_value == datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)

    def test_dst_nonexistent_time_corrected(self) -> None:
        # 2026-03-08 美国 NY 02:00→03:00 春跳；02:30 不存在 → 顺延至 03:30 EDT。
        res = resolve_local(NY, date(2026, 3, 8), "02:30")
        assert res.status == "corrected_nonexistent"
        assert res.utc_value == datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)
        assert "corrected" in res.note

    def test_dst_fold_two_instants(self) -> None:
        # 2026-11-01 NY 02:00→01:00 秋拨；01:30 出现两次。
        early = resolve_local(NY, date(2026, 11, 1), "01:30", fold=0)
        late = resolve_local(NY, date(2026, 11, 1), "01:30", fold=1)
        assert early.status == "ambiguous_fold0"
        assert late.status == "ambiguous_fold1"
        assert early.utc_value == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)  # EDT UTC-4
        assert late.utc_value == datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)  # EST UTC-5

    def test_dst_expansion_notes(self, tmp_path) -> None:
        clock = FixedClock(datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc))
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        plan = make_plan(
            timezone="America/New_York",
            tasks=[TaskTemplate(task_id="t_stand", title="晨会", kind=TaskKind.FIXED_TIME, fixed_local_time="02:30")],
            rules=[
                RecurrenceRule(rule_id="r_stand", task_id="t_stand", kind="daily", start_date="2026-03-01", local_time="02:30")
            ],
        )
        service.submit_plan(plan, confirm=True)
        result = service.expand_occurrences(plan)
        mar8 = next(o for o in result.occurrences if o.scheduled_at_utc.startswith("2026-03-08"))
        assert mar8.scheduled_at_utc.startswith("2026-03-08T07:30")  # 02:30→03:30 EDT = 07:30Z
        assert any("corrected_nonexistent" in n for n in result.notes)

    def test_fold_expansion_note(self, tmp_path) -> None:
        clock = FixedClock(datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc))
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        plan = make_plan(
            timezone="America/New_York",
            tasks=[TaskTemplate(task_id="t_shift", title="夜班", kind=TaskKind.FIXED_TIME, fixed_local_time="01:30")],
            rules=[
                RecurrenceRule(rule_id="r_shift", task_id="t_shift", kind="once", start_date="2026-11-01", local_time="01:30")
            ],
        )
        service.submit_plan(plan, confirm=True)
        result = service.expand_occurrences(plan)
        assert len(result.occurrences) == 1
        assert result.occurrences[0].scheduled_at_utc.startswith("2026-11-01T05:30")  # fold=0 较早瞬时
        assert any("ambiguous_fold0" in n for n in result.notes)


# --------------------------------------------------- 4. 幂等 / 同名 / occurrence_id
class TestIdempotency:
    def test_occurrence_identity_shape_and_revision_change(self) -> None:
        at = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)
        id1 = occurrence_identity("r1", 1, at)
        id2 = occurrence_identity("r1", 1, at)
        id3 = occurrence_identity("r1", 2, at)
        assert id1 == id2 and id1 != id3
        assert len(id1) == 20

    def test_double_import_is_noop(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        plan = make_plan()
        service.submit_plan(plan, confirm=True)
        first = service.expand_occurrences(plan)
        second = service.expand_occurrences(plan)  # 同一计划重复导入（不再重复 submit）
        assert len(first.occurrences) > 0
        assert len(second.occurrences) == len(first.occurrences)
        # 落库层面：第二次导入 new_rows == 0
        assert "new_rows=0" in second.notes[-1]

    def test_same_title_different_dates_distinct_ids(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        plan = make_plan(
            tasks=[TaskTemplate(task_id="t_class", title="高等数学", kind=TaskKind.FIXED_TIME, fixed_local_time="08:00")],
            rules=[
                RecurrenceRule(rule_id="r_class", task_id="t_class", kind="weekly", start_date="2026-09-14", local_time="08:00")
            ],
        )
        ids = materialize_simple(service, plan)
        assert len(ids) == len(set(ids)) >= 2  # 每周一各自独立实例
        rows = service._store.list_occurrences("plan_main")
        titles = {r["title"] for r in rows}
        assert titles == {"高等数学"}
        dates = {r["scheduled_at_utc"][:10] for r in rows}
        assert len(dates) >= 2  # 不同日期同名任务并存

    def test_rule_revision_bump_materializes_new_instances(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        store = ScheduleStore(tmp_path / "s.sqlite3")
        service = ScheduleService(store, clock=clock)
        plan = make_plan()
        service.submit_plan(plan, confirm=True)
        v1_ids = [o.occurrence_id for o in service.expand_occurrences(plan).occurrences]
        bumped = plan.model_copy(deep=True)
        bumped.rules[0].local_time = "09:00"
        bumped.rules[0].rule_revision = 2
        store.supersede_rule(plan.plan_id, "r_class", 1, now_utc=clock())
        v2 = service.expand_occurrences(bumped)
        v2_ids = [o.occurrence_id for o in v2.occurrences]
        assert v1_ids and set(v1_ids).isdisjoint(v2_ids)  # 版本变更 → 新 id
        surviving = [r for r in store.list_occurrences(plan.plan_id, status="pending")]
        assert {r["rule_revision"] for r in surviving} == {2}

    def test_per_plan_occurrence_cap(self, tmp_path) -> None:
        # 40 条 daily 规则 × ~31 天 ≈ 1240 > 1000 → 触顶截断且不超发。
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        rules = [
            RecurrenceRule(rule_id=f"r{i:03d}", task_id="t0", kind="daily", start_date="2026-09-01", local_time="08:00")
            for i in range(40)
        ]
        plan = make_plan(
            tasks=[
                TaskTemplate(task_id="t0", title="容量", kind=TaskKind.FIXED_TIME, fixed_local_time="08:00"),
            ],
            rules=rules,
        )
        service.submit_plan(plan, confirm=True)
        result = service.expand_occurrences(plan)
        assert result.truncated
        assert len(result.occurrences) == 1000  # 上限即停，绝不超发


# ---------------------------------------------------- 5. 版本 / 改期 / 冲突
class TestVersionAndReschedule:
    def test_version_conflict_on_stale_revision(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        plan = make_plan()
        service.submit_plan(plan)
        with pytest.raises(ScheduleError) as excinfo:
            service.submit_plan(plan, expected_revision=99)
        assert excinfo.value.code == "version_conflict"
        with pytest.raises(ScheduleError):
            service.preview_reschedule("plan_main", [RescheduleChange(rule_id="r_class", new_local_time="09:00")], expected_revision=99)

    def test_soft_reschedule_diff_and_new_revision(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        plan = make_plan(
            tasks=[
                TaskTemplate(
                    task_id="t_class",
                    title="选修课",
                    kind=TaskKind.FIXED_TIME,
                    fixed_local_time="08:00",
                    soft_window_minutes=30,
                )
            ],
        )
        service.submit_plan(plan)
        preview = service.preview_reschedule(
            "plan_main", [RescheduleChange(rule_id="r_class", new_local_time="08:30")], expected_revision=1
        )
        assert preview.ok
        assert preview.new_revision == 2
        assert preview.diff and all(e.soft for e in preview.diff)
        assert all(e.old_at_utc != e.new_at_utc for e in preview.diff)

    def test_hard_reschedule_conflicts_no_silent_shift(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        plan = make_plan()  # t_class 硬预约（soft_window_minutes=0）
        service.submit_plan(plan)
        preview = service.preview_reschedule(
            "plan_main", [RescheduleChange(rule_id="r_class", new_local_time="10:00")], expected_revision=1
        )
        assert not preview.ok
        assert preview.diff == []
        assert preview.conflicts[0].code == "schedule_conflict"

    def test_hard_collision_detection(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        plan = make_plan(
            tasks=[
                TaskTemplate(task_id="t_a", title="硬A", kind=TaskKind.FIXED_TIME, fixed_local_time="08:00"),
                TaskTemplate(task_id="t_b", title="硬B", kind=TaskKind.FIXED_TIME, fixed_local_time="08:00"),
            ],
            rules=[
                RecurrenceRule(rule_id="r_a", task_id="t_a", kind="weekly", start_date="2026-09-14", local_time="08:00"),
                RecurrenceRule(rule_id="r_b", task_id="t_b", kind="weekly", start_date="2026-09-14", local_time="08:00"),
            ],
        )
        service.submit_plan(plan)
        preview = service.preview_reschedule("plan_main", [], expected_revision=1)
        assert not preview.ok
        assert any(c.message.startswith("hard occurrences collide") for c in preview.conflicts)

    def test_apply_reschedule_bumps_revision_and_supersedes(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        store = ScheduleStore(tmp_path / "s.sqlite3")
        service = ScheduleService(store, clock=clock)
        plan = make_plan(
            tasks=[
                TaskTemplate(
                    task_id="t_class", title="选修课", kind=TaskKind.FIXED_TIME,
                    fixed_local_time="08:00", soft_window_minutes=30,
                )
            ],
        )
        service.submit_plan(plan, confirm=True)
        service.expand_occurrences(plan)
        preview = service.apply_reschedule(
            "plan_main", [RescheduleChange(rule_id="r_class", new_local_time="08:30")], expected_revision=1
        )
        assert preview.ok and preview.new_revision == 2
        pending = store.list_occurrences("plan_main", status="pending")
        assert pending and all(r["rule_revision"] == 2 for r in pending)
        superseded = store.list_occurrences("plan_main", status="superseded")
        assert superseded  # 旧版本实例已退役


# ------------------------------------------------------- 6. 租约 / 竞态 / 索引
def make_due_occurrences(
    service: ScheduleService,
    count: int,
    *,
    tags: list[str] | None = None,
    id_prefix: str = "occ",
) -> list[str]:
    clock = service.now()
    models = []
    for i in range(count):
        at = clock - timedelta(minutes=i + 1)
        models.append(
            Occurrence(
                occurrence_id=f"{id_prefix}_{i:03d}",
                plan_id="plan_main",
                rule_id="r0",
                rule_revision=1,
                task_id="t0",
                title=f"任务{i}",
                scheduled_at_utc=at.isoformat(),
                duration_minutes=0,
                tags=tags or [],
            )
        )
    service._store.upsert_occurrences(models, now_utc=clock)
    return [m.occurrence_id for m in models]


class TestClaimLease:
    def test_claim_due_returns_only_due_and_limits(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        make_due_occurrences(service, 5)
        # 未来项不可领取
        service._store.upsert_occurrences(
            [
                Occurrence(
                    occurrence_id="occ_future",
                    plan_id="plan_main",
                    rule_id="r0",
                    rule_revision=1,
                    task_id="t0",
                    title="未来",
                    scheduled_at_utc=(clock() + timedelta(hours=1)).isoformat(),
                    duration_minutes=0,
                    tags=[],
                )
            ],
            now_utc=clock(),
        )
        claimed = service.claim_due("worker_1", limit=3)
        assert len(claimed) == 3
        assert all(r["lease_owner"] == "worker_1" for r in claimed)
        again = service.claim_due("worker_1", limit=10)
        assert {r["occurrence_id"] for r in again}.isdisjoint({r["occurrence_id"] for r in claimed})
        assert len(again) == 2  # 只剩 2 条到期

    def test_claim_concurrent_unique(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        path = tmp_path / "s.sqlite3"
        service = ScheduleService(ScheduleStore(path), clock=clock)
        ids = make_due_occurrences(service, 12)
        workers = 4
        barrier = threading.Barrier(workers)
        results: list[list[str]] = [[] for _ in range(workers)]

        def worker(idx: int) -> None:
            handle = ScheduleService(ScheduleStore(path), clock=clock)
            barrier.wait()
            got = handle.claim_due(f"worker_{idx}")
            results[idx] = [r["occurrence_id"] for r in got]

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        flat = [oid for chunk in results for oid in chunk]
        assert sorted(flat) == sorted(ids)  # 全部被领取
        assert len(flat) == len(set(flat))  # 且只被领取一次（租约唯一）

    def test_due_query_uses_time_index(self, tmp_path) -> None:
        store = ScheduleStore(tmp_path / "s.sqlite3")
        plan_text = store.explain_due_query().upper()
        assert "IDX_OCC_DUE" in plan_text  # 不扫全表

    def test_cancel_then_claim_fails(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        (oid,) = make_due_occurrences(service, 1)
        result = service.cancel_occurrence(oid)
        assert result["status"] == "cancelled"
        assert service.claim_due("worker_1") == []

    def test_cancel_after_claim_is_in_flight(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        (oid,) = make_due_occurrences(service, 1)
        assert service.claim_due("worker_1")
        result = service.cancel_occurrence(oid)
        assert result["status"] == "in_flight"  # 在途无法保证撤回
        # 租约过期后可取消
        clock.advance(seconds=301)
        assert service.cancel_occurrence(oid)["status"] == "cancelled"

    def test_mark_done_and_snooze(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        (oid,) = make_due_occurrences(service, 1, id_prefix="done")
        assert service.mark_task_done(oid)
        row = service._store.get_occurrence(oid)
        assert row["status"] == "done"
        (oid2,) = make_due_occurrences(service, 1, id_prefix="snz")
        snoozed = service.snooze(oid2, 10)
        assert snoozed is not None and snoozed["status"] == "pending"
        assert service.claim_due("worker_1") == []  # 顺延后不再到期


# ---------------------------------------------------------- 7. 错过策略 reconcile
class TestReconcileMissed:
    def _seed(self, tmp_path, *, policy: str, tags: list[str] | None = None, clock_offset: timedelta):
        clock = FixedClock(BASE)
        store = ScheduleStore(tmp_path / "s.sqlite3")
        service = ScheduleService(store, clock=clock)
        plan = make_plan(reminder_policy=ReminderPolicy(missed_policy=policy))
        service.submit_plan(plan, confirm=True)
        at = BASE + clock_offset
        occ = Occurrence(
            occurrence_id=f"occ_{policy}_{clock_offset.total_seconds():.0f}",
            plan_id="plan_main", rule_id="r0", rule_revision=1,
            task_id="t_class", title="高等数学",
            scheduled_at_utc=at.isoformat(), duration_minutes=0, tags=tags or [],
        )
        store.upsert_occurrences([occ], now_utc=BASE)
        return service, store, occ.occurrence_id

    def test_within_grace_stays_sendable(self, tmp_path) -> None:
        service, store, oid = self._seed(tmp_path, policy="send_once", clock_offset=timedelta(minutes=-5))
        report = service.reconcile_missed()
        assert oid in report.late_send_once
        assert store.get_occurrence(oid)["status"] == "pending"  # 保持可投递（迟发一次）

    def test_beyond_grace_goes_digest(self, tmp_path) -> None:
        service, store, oid = self._seed(tmp_path, policy="send_once", clock_offset=timedelta(days=-7))
        report = service.reconcile_missed()
        assert oid in report.digested
        assert store.get_occurrence(oid)["status"] == "digest"

    def test_rush_expires(self, tmp_path) -> None:
        service, store, oid = self._seed(
            tmp_path, policy="send_once", tags=["rush"], clock_offset=timedelta(minutes=-3)
        )
        report = service.reconcile_missed()
        assert oid in report.expired
        assert store.get_occurrence(oid)["status"] == "expired"  # 绝不当"即将开售"

    @pytest.mark.parametrize("policy,status,report_key", [
        ("skip", "skipped", "skipped"),
        ("ask", "ask", "ask"),
        ("digest", "digest", "digested"),
    ])
    def test_explicit_policies(self, tmp_path, policy, status, report_key) -> None:
        service, store, oid = self._seed(tmp_path, policy=policy, clock_offset=timedelta(days=-7))
        report = service.reconcile_missed()
        assert getattr(report, report_key) == [oid]
        assert store.get_occurrence(oid)["status"] == status

    def test_restart_reconcile_with_fresh_handle(self, tmp_path) -> None:
        # 离线一周：重启后新 store 句柄跑 reconcile 到期项。
        clock = FixedClock(BASE)
        path = tmp_path / "s.sqlite3"
        service = ScheduleService(ScheduleStore(path), clock=clock)
        plan = make_plan()
        service.submit_plan(plan, confirm=True)
        old = Occurrence(
            occurrence_id="occ_offline", plan_id="plan_main", rule_id="r_class", rule_revision=1,
            task_id="t_class", title="高等数学",
            scheduled_at_utc=(BASE - timedelta(days=7)).isoformat(), duration_minutes=0, tags=[],
        )
        recent = Occurrence(
            occurrence_id="occ_recent", plan_id="plan_main", rule_id="r_class", rule_revision=1,
            task_id="t_class", title="高等数学",
            scheduled_at_utc=(BASE - timedelta(minutes=10)).isoformat(), duration_minutes=0, tags=[],
        )
        service._store.upsert_occurrences([old, recent], now_utc=BASE)
        del service  # 模拟进程重启
        clock2 = FixedClock(BASE + timedelta(minutes=5))  # 重启后 5 分钟：recent 迟到 15 分钟内
        revived = ScheduleService(ScheduleStore(path), clock=clock2)
        report = revived.reconcile_missed()
        assert "occ_recent" in report.late_send_once  # 15 分钟 grace 内 → 补发一次
        assert "occ_offline" in report.digested  # 一周前 → 合并摘要


# ------------------------------------------------------------- 8. 防风暴限流
class TestStormGate:
    def test_per_minute_cap_merges_to_digest(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        decisions = [service.acquire_send_slot("u1", f"occ_{i}") for i in range(5)]
        assert [d.decision for d in decisions[:3]] == ["allow", "allow", "allow"]
        assert all(d.decision == "digest" for d in decisions[3:])

    def test_per_hour_cap_merges_to_digest(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        outcomes = []
        for i in range(21):
            outcomes.append(service.acquire_send_slot("u2", f"occ_{i}").decision)
            clock.advance(seconds=61)  # 错开分钟窗（61s 间距内任一 60s 窗 ≤2 条）
        assert outcomes[:20] == ["allow"] * 20
        assert outcomes[20] == "digest"  # 第 21 条触发小时上限

    def test_digest_bundle_groups_by_owner(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        plan = make_plan()
        service.submit_plan(plan, confirm=True)
        make_due_occurrences(service, 2)
        store = service._store
        for row in store.list_occurrences("plan_main", status="pending"):
            store.set_status(row["occurrence_id"], "digest", now_utc=clock())
        bundle = service.build_digest("user_1")
        assert bundle.total == 2
        assert {i["plan_id"] for i in bundle.items} == {"plan_main"}
        assert service.build_digest("someone_else").total == 0


# --------------------------------------------------------------- 9. 安静时间
class TestQuietHours:
    def _quiet_plan(self, **policy_kwargs: object) -> SchedulePlan:
        policy = {"urgent": False} if not policy_kwargs else dict(policy_kwargs)
        return make_plan(reminder_policy=ReminderPolicy(**policy))  # type: ignore[arg-type]

    def test_non_urgent_deferred_to_quiet_end(self, tmp_path) -> None:
        # 北京时间 2026-09-17 02:00 = 前一日 18:00Z，处于 23:00-07:00 安静窗。
        clock = FixedClock(datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc))
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        service.submit_plan(self._quiet_plan(), confirm=True)
        make_due_occurrences(service, 1)
        claimed = service.claim_due("worker_1")
        split = service.split_quiet_hours(claimed)
        assert split.deliver_now == []
        assert len(split.deferred) == 1
        assert split.deferred[0]["deferred_to_utc"] == "2026-09-16T23:00:00+00:00"  # 本地 07:00
        row = service._store.get_occurrence(claimed[0]["occurrence_id"])
        assert row["status"] == "pending" and row["lease_owner"] is None  # 已顺延并释放租约

    def test_urgent_and_approved_exception_pass(self, tmp_path) -> None:
        clock = FixedClock(datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc))
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        urgent_plan = make_plan(reminder_policy=ReminderPolicy(urgent=True))
        service.submit_plan(urgent_plan, confirm=True)
        make_due_occurrences(service, 1)
        split = service.split_quiet_hours(service.claim_due("w"))
        assert len(split.deliver_now) == 1 and split.deferred == []

        # 非紧急 + 显式批准例外：立即发，且例外可查询。
        clock.set(BASE)
        make_due_occurrences(service, 1)
        row = service.claim_due("w")[0]
        clock.set(datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc))
        service.approve_quiet_exception(row["occurrence_id"], owner="user_1", reason="用户指定硬时点")
        split2 = service.split_quiet_hours([row])
        assert len(split2.deliver_now) == 1
        exceptions = service.list_quiet_exceptions("user_1")
        assert any(e["occurrence_id"] == row["occurrence_id"] for e in exceptions)

    def test_quiet_window_boundaries(self) -> None:
        qh = parse_plan({"plan_id": "p", "owner": "o", "timezone": "UTC"}).quiet_hours
        assert ScheduleService.is_quiet(qh, time(23, 30))
        assert ScheduleService.is_quiet(qh, time(3, 0))
        assert not ScheduleService.is_quiet(qh, time(12, 0))
        assert not ScheduleService.is_quiet(qh, time(7, 0))  # end 开区间


# ------------------------------------------------------------------- 10. 提醒
class TestReminders:
    def test_default_offsets_and_unique_ids(self, tmp_path) -> None:
        clock = FixedClock(BASE)
        service = ScheduleService(ScheduleStore(tmp_path / "s.sqlite3"), clock=clock)
        plan = make_plan()
        occ = Occurrence(
            occurrence_id="occ_r", plan_id="plan_main", rule_id="r_class", rule_revision=1,
            task_id="t_class", title="高等数学",
            scheduled_at_utc="2026-09-21T00:00:00+00:00", duration_minutes=0, tags=[],
        )
        items = service.build_reminders(plan, occ)
        assert [(i.offset_minutes) for i in items] == [-10, 0]  # 默认前 10 分钟 + 准点
        assert len({i.reminder_id for i in items}) == 2  # 每 offset 唯一 reminder_id
        assert items[0].due_utc == "2026-09-20T23:50:00+00:00"

    def test_more_than_four_offsets_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReminderPolicy(offsets_minutes=(-40, -30, -20, -10, 0))

    def test_rush_configurable_offsets(self) -> None:
        policy = ReminderPolicy(offsets_minutes=(-10, -1, 0))
        assert list(policy.offsets_minutes) == [-10, -1, 0]  # 抢票：前 10 分钟/1 分钟/准点


# ------------------------------------------------------------------- 11. 杂项
class TestMisc:
    def test_parse_plan_roundtrip_and_unknown_tz(self) -> None:
        plan = make_plan()
        parsed = parse_plan(plan.model_dump(mode="json"))
        assert parsed.plan_id == plan.plan_id
        with pytest.raises(ValidationError):
            make_plan(timezone="Mars/Olympus_Mons")

    def test_default_store_path_via_runtime_paths(self, tmp_path, monkeypatch) -> None:
        # 工厂接线位：默认 data/ 路径重映射（monkeypatch runtime_data_dir 到 tmp）。
        import scripts.runtime_paths as rp

        monkeypatch.setattr(rp, "runtime_data_dir", lambda: tmp_path)
        config = SimpleNamespace(bot_schedule_db_path="data/schedules_v21.sqlite3")
        service = build_schedule_service(config)
        assert service._store._path.startswith(str(tmp_path))
        service._store.close()

    def test_error_codes_registered_in_contract(self) -> None:
        for code in (
            "schedule_cycle", "missing_calendar", "ambiguous_local_time",
            "schedule_conflict", "occurrence_expired", "version_conflict",
        ):
            assert get_error_spec(code).code == code

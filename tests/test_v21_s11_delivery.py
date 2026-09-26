"""v21r2 S11 余量交付③——occurrence→SendQueue 投递接线回归（全离线全 mock）。

覆盖：tick 全链（claim→quiet 分流→风暴门→submit→回执落账）；deliver_after=now
语义；安静时间 deferred 不出站；风暴门 digest 合并不出站；submit 抛错退避重试
（snooze 复用）与超限 delivery_failed；未授权出站=not_authorized 干跑不伪装；
例外表 known holiday 顺延 / 未知年份 unknown 照常投递并如实标注 / 文件缺失=
空表；SendRequest 真构造可行性（campus 同款字段面）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.core.contracts import (
    PrivacyLevel,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.schedule.delivery import (
    CalendarExceptions,
    ScheduleDeliveryService,
    build_schedule_delivery_service,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_dag import (
    Occurrence,
    RecurrenceRule,
    SchedulePlan,
    TaskTemplate,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_service import (
    ScheduleService,
    build_schedule_service,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_store import (
    ScheduleStore,
)

# 固定时钟：2026-09-18 03:00 UTC = 北京 11:00（默认安静窗 23:00-07:00 之外）。
_NOW = datetime(2026, 9, 18, 3, 0, 0, tzinfo=timezone.utc)
_TODAY = "2026-09-18"


def fixed_clock():
    return lambda: _NOW


def mutable_clock():
    """可拨时钟：service 与 delivery 共享同一时钟面（测退避后续投）。"""
    state = {"now": _NOW}

    def clock() -> datetime:
        return state["now"]

    return state, clock


class FakeQueue:
    """SendQueue 协议桩：记录 submit 调用；可注入异常或回执状态。"""

    def __init__(self, *, state: str = "queued", error: Exception | None = None) -> None:
        self.state = state
        self.error = error
        self.submitted: list[dict[str, object]] = []

    def submit(self, send_request: object, *, deliver_after: datetime | None = None) -> object:
        self.submitted.append({"request": send_request, "deliver_after": deliver_after})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(state=SimpleNamespace(value=self.state))


def build_request(owner: str, row: dict[str, object]) -> SendRequest:
    """生产同款 SendRequest 构造（字段面对齐 campus 先例）——证明提交面可行。"""
    request_id = f"sch-{row['occurrence_id']}"  # type: ignore[arg-type]
    return SendRequest(
        request_id=request_id,
        session_id=f"private:{owner}",
        target_scope=SessionType.PRIVATE,
        target_id=owner,
        capability_id="bot.schedule_reminder",
        content=RenderedOutput(
            request_id=request_id,
            content_type="text",
            content_ref={},
            text_fallback=f"提醒：{row['title']}",  # type: ignore[arg-type]
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.QUEUED,
        priority="normal",
        max_messages=1,
        dedupe_key=f"schedule:{row['occurrence_id']}",  # type: ignore[arg-type]
        cooldown_key=f"schedule:{owner}",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="shorekeeper",
    )


def make_service(
    tmp_path: object,
    *,
    plan_id: str = "plan-a",
    owner: str = "10001",
    title: str = "交作业",
    tags: list[str] | None = None,
    quiet: str = "23:00",
    end: str = "07:00",
    clock=None,
):
    """建 plan（active）+ 直接 upsert 一条**已到期**实例（北京 10:00 = 02:00 UTC，
    早于固定 now 03:00 UTC）。expand 只物化未来实例，故到期件由测试直插（与
    W10 claim 测试同法），投递链路本身零特判。"""
    store = ScheduleStore(tmp_path / "schedules.sqlite3")  # type: ignore[operator]
    service = ScheduleService(store, clock=clock or fixed_clock())
    plan = SchedulePlan(
        plan_id=plan_id,
        owner=owner,
        timezone="Asia/Shanghai",
        tasks=[TaskTemplate(task_id="t1", title=title, kind="fixed_time", fixed_local_time="10:00")],
        rules=[
            RecurrenceRule(
                rule_id="r1",
                task_id="t1",
                kind="once",
                start_date=_TODAY,
                local_time="10:00",
            )
        ],
        quiet_hours={"start": quiet, "end": end},
    )
    service.submit_plan(plan, confirm=True)
    store.upsert_occurrences(
        [
            Occurrence(
                occurrence_id=f"occ-{plan_id}",
                plan_id=plan_id,
                rule_id="r1",
                rule_revision=1,
                task_id="t1",
                title=title,
                scheduled_at_utc="2026-09-18T02:00:00+00:00",
                duration_minutes=0,
                tags=list(tags or []),
            )
        ],
        now_utc=_NOW,
    )
    return service


def first_row(service: ScheduleService, plan_id: str = "plan-a") -> dict[str, object]:
    rows = service._store.list_occurrences(plan_id=plan_id)
    assert rows
    return rows[0]


class TestDeliveryTick:
    def test_submit_to_queue_and_receipt_recorded(self, tmp_path) -> None:
        service = make_service(tmp_path)
        queue = FakeQueue()
        delivery = ScheduleDeliveryService(
            service, queue, clock=fixed_clock(), request_builder=build_request
        )
        report = delivery.delivery_tick()
        assert report.checked == 1
        outcome = report.outcomes[0]
        assert outcome.status == "submitted"
        assert outcome.receipt_state == "queued"
        assert queue.submitted and len(queue.submitted) == 1
        # deliver_after=now：显式声明无内联首投（后台投递语义）。
        assert queue.submitted[0]["deliver_after"] == _NOW
        request = queue.submitted[0]["request"]
        assert isinstance(request, SendRequest)
        assert request.dedupe_key.startswith("schedule:")
        assert service._store.get_occurrence(str(first_row(service)["occurrence_id"]))["status"] == "queued"

    def test_second_tick_does_not_resubmit(self, tmp_path) -> None:
        service = make_service(tmp_path)
        delivery = ScheduleDeliveryService(
            service, FakeQueue(), clock=fixed_clock(), request_builder=build_request
        )
        delivery.delivery_tick()
        second = delivery.delivery_tick()
        assert second.checked == 0  # 已 queued 且租约消费，不再领取

    def test_quiet_hours_defers_without_outbound(self, tmp_path) -> None:
        service = make_service(tmp_path, quiet="00:00", end="23:59")  # 全天安静
        queue = FakeQueue()
        delivery = ScheduleDeliveryService(
            service, queue, clock=fixed_clock(), request_builder=build_request
        )
        report = delivery.delivery_tick()
        assert report.outcomes[0].status == "deferred_quiet"
        assert queue.submitted == []
        # 引擎已把实例 snooze 到安静结束（回 pending 清租约）。

    def test_storm_gate_merges_into_digest(self, tmp_path) -> None:
        service = make_service(tmp_path)
        service.max_sends_per_minute = 0  # 强制每分钟配额为 0 → 一律 digest
        queue = FakeQueue()
        delivery = ScheduleDeliveryService(
            service, queue, clock=fixed_clock(), request_builder=build_request
        )
        report = delivery.delivery_tick()
        assert report.outcomes[0].status == "digest"
        assert "digest" in report.outcomes[0].detail or report.outcomes[0].detail
        assert queue.submitted == []
        row = first_row(service)
        assert service._store.get_occurrence(str(row["occurrence_id"]))["status"] == "digest"

    def test_not_authorized_outbound_is_honest_dry_run(self, tmp_path) -> None:
        service = make_service(tmp_path)
        # queue=None（真实出站端口未授权）：干跑，不伪装成功。
        delivery = ScheduleDeliveryService(service, None, clock=fixed_clock())
        report = delivery.delivery_tick()
        assert report.outcomes[0].status == "not_authorized"
        assert "unauthorized" in report.outcomes[0].detail
        row = first_row(service)
        assert service._store.get_occurrence(str(row["occurrence_id"]))["status"] == "pending"

    def test_assembly_factory_dry_run(self, tmp_path) -> None:
        config = SimpleNamespace(
            bot_schedule_db_path=str(tmp_path / "asm.sqlite3"),
            bot_schedule_delivery_max_retries=2,
            bot_schedule_exceptions_path="",
        )
        service = build_schedule_service(config, clock=fixed_clock())
        delivery = build_schedule_delivery_service(config, None, service=service, clock=fixed_clock())
        assert delivery.max_retries == 2
        assert delivery._calendar.resolve(_NOW.date()) == "unknown"  # 模板表为空 → unknown


class TestRetrySemantics:
    def test_submit_error_backs_off_then_recovers(self, tmp_path) -> None:
        state, clock = mutable_clock()
        service = make_service(tmp_path, clock=clock)
        queue = FakeQueue(error=RuntimeError("queue down"))
        delivery = ScheduleDeliveryService(
            service, queue, clock=clock, request_builder=build_request
        )
        report = delivery.delivery_tick()
        assert report.outcomes[0].status == "retry_scheduled"
        assert "attempt=1" in report.outcomes[0].detail
        row = first_row(service)
        stored = service._store.get_occurrence(str(row["occurrence_id"]))
        assert stored["status"] == "pending"  # snooze 回 pending
        assert stored["due_epoch"] > _NOW.timestamp()  # 退避到未来
        # 拨钟越过退避窗、队列恢复后下一轮成功。
        queue.error = None
        state["now"] = _NOW + timedelta(minutes=5)
        report2 = delivery.delivery_tick()
        assert report2.outcomes[0].status == "submitted"

    def test_retries_exhausted_terminal_state(self, tmp_path) -> None:
        service = make_service(tmp_path)
        queue = FakeQueue(error=RuntimeError("queue down"))
        delivery = ScheduleDeliveryService(
            service, queue, clock=fixed_clock(), request_builder=build_request, max_retries=1
        )
        report = delivery.delivery_tick()
        assert report.outcomes[0].status == "delivery_failed"
        row = first_row(service)
        assert service._store.get_occurrence(str(row["occurrence_id"]))["status"] == "delivery_failed"

    def test_retryable_receipt_schedules_retry(self, tmp_path) -> None:
        service = make_service(tmp_path)
        queue = FakeQueue(state="failed_retryable")
        delivery = ScheduleDeliveryService(
            service, queue, clock=fixed_clock(), request_builder=build_request
        )
        report = delivery.delivery_tick()
        assert report.outcomes[0].status == "retry_scheduled"

    def test_final_receipt_is_terminal(self, tmp_path) -> None:
        service = make_service(tmp_path)
        queue = FakeQueue(state="failed_final")
        delivery = ScheduleDeliveryService(
            service, queue, clock=fixed_clock(), request_builder=build_request
        )
        report = delivery.delivery_tick()
        assert report.outcomes[0].status == "delivery_failed"
        assert report.outcomes[0].receipt_state == "failed_final"


class TestCalendarExceptions:
    def _tagged(self, tmp_path, *, tags: list[str]):
        return make_service(tmp_path, plan_id="plan-c", owner="10002", title="晨会", tags=tags)

    def test_known_holiday_defers_follow_calendar(self, tmp_path) -> None:
        service = self._tagged(tmp_path, tags=["follow_calendar"])
        calendar = CalendarExceptions(
            {"2026": {"holidays": {_TODAY: "调休放假"}, "workdays": {}}}
        )
        queue = FakeQueue()
        delivery = ScheduleDeliveryService(
            service, queue, calendar=calendar, clock=fixed_clock(), request_builder=build_request
        )
        report = delivery.delivery_tick()
        assert report.outcomes[0].status == "calendar_deferred"
        assert queue.submitted == []

    def test_unknown_year_delivers_with_honest_note(self, tmp_path) -> None:
        # 表里只有 2025 年：2026 = unknown → 照常投递，回执如实标注。
        service = self._tagged(tmp_path, tags=["follow_calendar"])
        calendar = CalendarExceptions({"2025": {"holidays": {_TODAY: "旧数据"}, "workdays": {}}})
        queue = FakeQueue()
        delivery = ScheduleDeliveryService(
            service, queue, calendar=calendar, clock=fixed_clock(), request_builder=build_request
        )
        report = delivery.delivery_tick()
        assert report.outcomes[0].status == "submitted"
        assert report.outcomes[0].detail == "calendar=unknown"
        assert len(queue.submitted) == 1

    def test_tag_absent_calendar_not_consulted(self, tmp_path) -> None:
        service = self._tagged(tmp_path, tags=[])
        calendar = CalendarExceptions({"2026": {"holidays": {_TODAY: "放假"}, "workdays": {}}})
        queue = FakeQueue()
        delivery = ScheduleDeliveryService(
            service, queue, calendar=calendar, clock=fixed_clock(), request_builder=build_request
        )
        report = delivery.delivery_tick()
        assert report.outcomes[0].status == "submitted"
        assert report.outcomes[0].detail == ""  # 无 unknown 标注（根本没查表）

    def test_known_workday_delivers_normally(self, tmp_path) -> None:
        service = self._tagged(tmp_path, tags=["follow_calendar"])
        calendar = CalendarExceptions({"2026": {"holidays": {}, "workdays": {_TODAY: "调休上班"}}})
        queue = FakeQueue()
        delivery = ScheduleDeliveryService(
            service, queue, calendar=calendar, clock=fixed_clock(), request_builder=build_request
        )
        report = delivery.delivery_tick()
        assert report.outcomes[0].status == "submitted"
        assert report.outcomes[0].detail == ""  # workday=显式常规日，无标注

    def test_loader_missing_and_malformed_files_empty(self, tmp_path) -> None:
        empty = CalendarExceptions.load(tmp_path / "nope.json")  # type: ignore[arg-type]
        assert empty.resolve(_NOW.date()) == "unknown"
        assert empty.years_known() == []
        bad = tmp_path / "bad.json"  # type: ignore[operator]
        bad.write_text("{not json", encoding="utf-8")
        assert CalendarExceptions.load(bad).years_known() == []

    def test_loader_overlay_overrides_template(self, tmp_path) -> None:
        overlay = tmp_path / "overlay.json"  # type: ignore[operator]
        overlay.write_text(
            json.dumps({"exceptions": {"2026": {"holidays": {_TODAY: "国庆"}, "workdays": {}}}}),
            encoding="utf-8",
        )
        calendar = CalendarExceptions.load_default(overlay)
        assert calendar.resolve(_NOW.date()) == "holiday"
        assert calendar.years_known() == [2026]

    def test_unknown_within_known_year_not_claimed_as_regular(self) -> None:
        calendar = CalendarExceptions({"2026": {"holidays": {"2026-10-01": "国庆"}, "workdays": {}}})
        # 年内无键日期 → unknown（绝不当作常规日宣称）。
        assert calendar.resolve(datetime(2026, 9, 18, tzinfo=timezone.utc).date()) == "unknown"

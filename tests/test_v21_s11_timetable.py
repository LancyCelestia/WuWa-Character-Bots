"""v21r2 S11 余量交付②——课表截图→结构草稿回归（全离线，视觉 provider 全 mock）。

覆盖：OCR JSON→CourseEntry（行列/合并/置信度保留）；单双周/节次→时间映射；
缺学期起点或节次表=needs_clarification 拒发布；先验覆盖 OCR；重复导入指纹
去重（同名不同时刻各自保留）；坏 provider→空草稿；发布 payload 过 DAG 校验；
提示词无泄露词；识图装配助手空 registry 返回 None。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.schedule.service.schedule_dag import (
    validate_plan_dag,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_service import (
    parse_plan,
)
from plugins.bot_unified_runtime.domains.schedule.timetable import (
    CourseEntry,
    TimetableDraft,
    build_timetable_provider,
    fingerprint_image_bytes,
    merge_timetable_drafts,
    recognize_timetable,
    timetable_draft_to_plan_payload,
)

_LEAK_MARKERS = ("route", "registry", "model_router", "system prompt", "注入", "工具调用")


class FakeVision:
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate(self, messages: list[dict[str, object]], **kwargs: object) -> object:
        self.calls.append({"messages": messages, **kwargs})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(text=self.text)


_OCR_JSON = json.dumps(
    {
        "semester_start": "2026-09-07",
        "period_table": {"1": ["08:00", "08:45"], "2": ["08:55", "09:40"]},
        "courses": [
            {
                "course_name": "高等数学",
                "weekday": 0,
                "periods": [1, 2],
                "start_time": None,
                "end_time": None,
                "week_parity": "odd",
                "week_start": 1,
                "week_end": 16,
                "location": "教一 101",
                "teacher": "张老师",
                "confidence": 0.95,
                "source_row": 2,
                "source_col": 1,
                "merged": True,
            },
            {
                "course_name": "大学英语",
                "weekday": 2,
                "periods": [],
                "start_time": "14:00",
                "end_time": "15:35",
                "week_parity": "both",
                "confidence": 0.9,
                "source_row": 3,
                "source_col": 4,
                "merged": False,
            },
            {
                "course_name": "看不清的课",
                "weekday": 4,
                "confidence": 0.1,
            },
        ],
    },
    ensure_ascii=False,
)


class TestRecognize:
    def test_ocr_json_to_structured_draft(self) -> None:
        provider = FakeVision(_OCR_JSON)
        draft = recognize_timetable(provider, ["data:image/png;base64,xxx"])
        assert draft.semester_start == "2026-09-07"
        assert draft.period_table[1] == ["08:00", "08:45"]
        # 低置信条目丢弃（0.1 < 0.3），不收不猜。
        assert [c.course_name for c in draft.courses] == ["高等数学", "大学英语"]
        math = draft.courses[0]
        assert math.source_row == 2 and math.source_col == 1 and math.merged is True
        assert math.week_parity == "odd" and math.week_start == 1 and math.week_end == 16
        # 节次映射：periods [1,2] → 08:00 起 09:40 止。
        assert math.start_time == "08:00" and math.end_time == "09:40"
        english = draft.courses[1]
        assert english.has_time() and english.week_parity == "both"
        # 出站消息面：system+user、含 image_url 段。
        assert len(provider.calls) == 1

    def test_prior_overrides_ocr(self) -> None:
        provider = FakeVision(_OCR_JSON)
        draft = recognize_timetable(
            provider,
            ["x"],
            semester_start="2026-09-01",
            period_table={1: ["08:30", "09:15"], 2: ["09:25", "10:10"]},
        )
        assert draft.semester_start == "2026-09-01"
        assert draft.period_table[1] == ["08:30", "09:15"]
        assert draft.courses[0].end_time == "10:10"

    def test_provider_failure_empty_draft_not_guess(self) -> None:
        provider = FakeVision(error=RuntimeError("vision down"))
        draft = recognize_timetable(provider, ["x"], image_bytes=b"img")
        assert draft.courses == []
        assert draft.image_fingerprint == fingerprint_image_bytes(b"img")
        assert draft.needs_clarification

    def test_non_timetable_reply_empty(self) -> None:
        draft = recognize_timetable(FakeVision("这不是课程表"), ["x"])
        assert draft.courses == []


class TestClarificationGate:
    def test_missing_semester_blocks_publish(self) -> None:
        draft = TimetableDraft(
            courses=[
                CourseEntry(
                    course_name="高数",
                    weekday=0,
                    periods=[1],
                    start_time="08:00",
                    end_time="08:45",
                    week_parity="odd",
                )
            ],
            semester_start=None,
        )
        assert draft.needs_clarification
        assert any("学期" in q for q in draft.missing_clarifications())
        with pytest.raises(ValueError, match="not publishable"):
            timetable_draft_to_plan_payload(draft, plan_id="p", owner="u")

    def test_missing_period_table_blocks_publish(self) -> None:
        draft = TimetableDraft(
            courses=[CourseEntry(course_name="高数", weekday=0, periods=[1, 2])]
        )
        assert draft.needs_clarification
        assert any("几点到几点" in q for q in draft.missing_clarifications())
        with pytest.raises(ValueError):
            timetable_draft_to_plan_payload(draft, plan_id="p", owner="u")

    def test_partial_period_table_reports_missing_periods(self) -> None:
        draft = TimetableDraft(
            courses=[CourseEntry(course_name="高数", weekday=0, periods=[1, 7])],
            period_table={1: ["08:00", "08:45"]},
        )
        assert any("第 [7]" in q for q in draft.missing_clarifications())

    def test_no_courses_asks(self) -> None:
        assert any("没有认出课程" in q for q in TimetableDraft().missing_clarifications())


class TestPublish:
    def test_complete_draft_publishes_valid_plan(self) -> None:
        draft = TimetableDraft(
            courses=[
                CourseEntry(
                    course_name="高数",
                    weekday=0,
                    start_time="08:00",
                    end_time="08:45",
                    week_parity="odd",
                ),
                CourseEntry(course_name="英语", weekday=2, start_time="14:00", end_time="15:35"),
            ],
            semester_start="2026-09-07",
        )
        payload = timetable_draft_to_plan_payload(draft, plan_id="tt-1", owner="u1")
        assert payload["state"] == "draft"
        plan = parse_plan(payload)
        assert validate_plan_dag(plan).ok
        kinds = {r.kind.value for r in plan.rules}
        assert kinds == {"teaching_week", "weekly_by_day"}

    def test_hard_booking_course_not_soft(self) -> None:
        draft = TimetableDraft(
            courses=[CourseEntry(course_name="高数", weekday=0, start_time="08:00", end_time="08:45")],
            semester_start="2026-09-07",
        )
        payload = timetable_draft_to_plan_payload(draft, plan_id="tt-2", owner="u1")
        assert all(t["soft_window_minutes"] == 0 for t in payload["tasks"])  # 上课=硬预约


class TestDedupe:
    def _course(self, name: str = "高数", start: str = "08:00") -> CourseEntry:
        return CourseEntry(course_name=name, weekday=0, start_time=start, end_time="08:45")

    def test_same_fingerprint_skipped(self) -> None:
        first = TimetableDraft(courses=[self._course()], semester_start="2026-09-07")
        again = TimetableDraft(courses=[self._course()])
        merged, report = merge_timetable_drafts(again, first)
        assert report.skipped == 1 and report.added == 0
        assert len(merged.courses) == 1
        assert merged.semester_start == "2026-09-07"  # 先导入的学期信息保留

    def test_same_name_different_time_kept_both(self) -> None:
        first = TimetableDraft(courses=[self._course(start="08:00")])
        again = TimetableDraft(courses=[self._course(start="10:00")])
        merged, report = merge_timetable_drafts(again, first)
        assert report.added == 1 and report.skipped == 0
        assert {c.start_time for c in merged.courses} == {"08:00", "10:00"}

    def test_first_import_adds_all(self) -> None:
        draft = TimetableDraft(courses=[self._course(), CourseEntry(course_name="英语", weekday=1)])
        merged, report = merge_timetable_drafts(draft, None)
        assert report.added == 2 and len(merged.courses) == 2


class TestPromptHygieneAndAssembly:
    def test_prompt_no_leak_markers(self) -> None:
        from plugins.bot_unified_runtime.domains.schedule.timetable import (
            prompt_text as _prompt_text,
        )

        text = _prompt_text().lower()
        for marker in _LEAK_MARKERS:
            assert marker not in text

    def test_build_provider_none_when_registry_empty(self) -> None:
        config = SimpleNamespace(bot_vision_model_registry={}, bot_vision_enabled=False)
        assert build_timetable_provider(config) is None

    def test_image_bytes_fingerprint(self) -> None:
        assert fingerprint_image_bytes(b"a") == fingerprint_image_bytes(b"a")
        assert fingerprint_image_bytes(b"a") != fingerprint_image_bytes(b"b")

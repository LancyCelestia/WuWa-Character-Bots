"""v21r2 S11 余量交付①——LLM 日程草稿解析回归（全离线，零网络零 NoneBot）。

覆盖：合法 JSON→结构草稿；坏 JSON/空回复→LLMDraftError；缺日期/低置信→
needs_clarification 澄清问题（禁猜断言）；模板链种子；草稿→plan payload 可过
DAG 校验；购物/抢票模板无购买执行步；出站提示词无泄露词；装配开关缺省关。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.domains.schedule.llm_draft import (
    TEMPLATE_CHAINS,
    LLMDraftError,
    ScheduleDraft,
    build_schedule_llm,
    classify_template,
    draft_date_floor,
    draft_to_plan_payload,
    parse_schedule_draft,
    prompt_texts,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_dag import (
    SchedulePlan,
    validate_plan_dag,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_service import (
    parse_plan,
)

# 泄露词自检表（与实现保持同表断言；出站文本出现即红）。
_LEAK_MARKERS = (
    "route",
    "registry",
    "model_router",
    "system prompt",
    "注入",
    "工具调用",
    "function call",
)


class FakeGenerate:
    """DI 桩：返回预置文本；记录调用参数供断言。"""

    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[dict[str, object]] = []

    def __call__(self, messages: list[dict[str, str]], **kwargs: object) -> object:
        self.calls.append({"messages": messages, **kwargs})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(text=self.text)


_VALID = json.dumps(
    {
        "template": "trip",
        "title": "周末出行",
        "timezone": "Asia/Shanghai",
        "actions": [
            {
                "step_id": "证件检查",
                "title": "检查证件",
                "local_time": "09:00",
                "date": "2026-09-26",
                "duration_minutes": 30,
            },
            {
                "step_id": "出发",
                "title": "出发去车站",
                "after_step": "证件检查",
                "duration_minutes": 60,
            },
        ],
        "confidence": 0.9,
    },
    ensure_ascii=False,
)


class TestDraftParsing:
    def test_valid_json_full_fields(self) -> None:
        gen = FakeGenerate(_VALID)
        draft = parse_schedule_draft("周六去外地，先查证件再出发", gen)
        assert draft.template == "trip"
        assert len(draft.actions) == 2
        assert draft.actions[0].local_time == "09:00"
        assert draft.actions[1].after_step == "证件检查"
        assert draft.confidence == pytest.approx(0.9)
        assert not draft.needs_clarification
        # 出站调用面：system+user 两条、低温小预算。
        assert len(gen.calls) == 1
        messages = gen.calls[0]["messages"]
        assert [m["role"] for m in messages] == ["system", "user"]  # type: ignore[index]
        assert gen.calls[0]["temperature"] == 0.1  # type: ignore[typeddict-item]

    def test_bad_json_raises_no_guess(self) -> None:
        with pytest.raises(LLMDraftError):
            parse_schedule_draft("明天提醒我", FakeGenerate("我觉得明天就行"))

    def test_non_object_json_raises(self) -> None:
        with pytest.raises(LLMDraftError):
            parse_schedule_draft("x", FakeGenerate("[1,2,3]"))

    def test_generator_exception_propagates(self) -> None:
        gen = FakeGenerate(error=RuntimeError("router down"))
        with pytest.raises(RuntimeError):
            parse_schedule_draft("x", gen)

    def test_unknown_template_falls_back_to_classifier(self) -> None:
        payload = json.dumps({"template": "nonsense", "title": "t", "actions": []}, ensure_ascii=False)
        draft = parse_schedule_draft("帮我抢票", FakeGenerate(payload))
        assert draft.template == "ticket"

    def test_actions_with_unknown_fields_dropped_not_guessed(self) -> None:
        payload = json.dumps(
            {
                "template": "custom",
                "title": "t",
                "actions": [{"step_id": "a", "title": "A", "secret_plan": "x"}],
            },
            ensure_ascii=False,
        )
        draft = parse_schedule_draft("x", FakeGenerate(payload))
        # 坏字段条目丢弃（禁猜不补），notes 如实记录无可识别安排。
        assert draft.actions == []
        assert any("没有可识别" in n for n in draft.notes)


class TestClarificationNoGuess:
    def test_missing_date_needs_clarification(self) -> None:
        payload = json.dumps(
            {
                "template": "errand",
                "title": "办证",
                "actions": [{"step_id": "出发", "title": "出发"}],
                "confidence": 0.9,
            },
            ensure_ascii=False,
        )
        draft = parse_schedule_draft("我要去办证", FakeGenerate(payload))
        assert "date" in draft.missing_fields
        assert draft.needs_clarification
        questions = draft.clarification_questions()
        assert questions and all(q.strip() for q in questions)

    def test_missing_date_never_invents_one(self) -> None:
        payload = json.dumps(
            {
                "template": "errand",
                "title": "办证",
                "actions": [{"step_id": "出发", "title": "出发", "local_time": "10:00"}],
                "confidence": 0.9,
            },
            ensure_ascii=False,
        )
        draft = parse_schedule_draft("我要去办证", FakeGenerate(payload))
        assert all(a.date is None for a in draft.actions)
        with pytest.raises(LLMDraftError):
            draft_to_plan_payload(draft, plan_id="p1", owner="u1")

    def test_low_confidence_needs_clarification(self) -> None:
        payload = json.dumps(
            {
                "template": "meal",
                "title": "吃饭",
                "actions": [
                    {"step_id": "s", "title": "S", "local_time": "12:00", "date": "2026-09-20"}
                ],
                "confidence": 0.2,
            },
            ensure_ascii=False,
        )
        draft = parse_schedule_draft("好像要吃个饭", FakeGenerate(payload))
        assert draft.confidence == pytest.approx(0.2)
        assert draft.needs_clarification
        assert any("把握" in q for q in draft.clarification_questions())

    def test_untyped_time_without_date_rejected_at_publish(self) -> None:
        draft = ScheduleDraft(
            template="custom",
            title="t",
            actions=[
                {"step_id": "a", "title": "A", "local_time": "10:00", "date": "2026-09-21"},
                {"step_id": "b", "title": "B", "local_time": "11:00"},
            ],
            confidence=0.95,
        )
        with pytest.raises(LLMDraftError, match="missing date fact"):
            draft_to_plan_payload(draft, plan_id="p1", owner="u1")


class TestTemplateChains:
    def test_seven_families_have_default_chains(self) -> None:
        assert set(TEMPLATE_CHAINS) == {
            "timetable",
            "workday",
            "errand",
            "trip",
            "ticket",
            "shopping",
            "meal",
        }
        assert TEMPLATE_CHAINS["workday"] == ("起床", "早餐", "通勤", "到岗", "午餐", "下班")

    def test_seed_chain_when_model_gives_no_steps(self) -> None:
        payload = json.dumps(
            {"template": "workday", "title": "上班", "actions": [], "confidence": 0.9},
            ensure_ascii=False,
        )
        draft = parse_schedule_draft("明天上班", FakeGenerate(payload))
        assert [a.step_id for a in draft.actions] == list(TEMPLATE_CHAINS["workday"])
        assert draft.actions[1].after_step == "起床"

    def test_ticket_chain_marks_rush_only_reminders(self) -> None:
        payload = json.dumps(
            {"template": "ticket", "title": "抢票", "actions": [], "confidence": 0.9},
            ensure_ascii=False,
        )
        draft = parse_schedule_draft("下周抢票", FakeGenerate(payload))
        rush_steps = [a for a in draft.actions if "rush" in a.tags]
        assert {a.step_id for a in rush_steps} == {"开售前提醒", "开售提醒"}

    def test_shopping_chain_has_no_purchase_execution_step(self) -> None:
        payload = json.dumps(
            {"template": "shopping", "title": "购物", "actions": [], "confidence": 0.9},
            ensure_ascii=False,
        )
        draft = parse_schedule_draft("买点东西", FakeGenerate(payload))
        steps = [a.step_id for a in draft.actions]
        assert "下单记录" in steps  # 只提醒用户自己下单后的记录节点
        for action in draft.actions:
            assert not {"pay", "purchase", "auto_buy"} & set(action.tags)
            assert "支付" not in action.title and "代付" not in action.title


class TestDraftToPlan:
    def test_complete_draft_publishes_valid_dag(self) -> None:
        draft = parse_schedule_draft("x", FakeGenerate(_VALID))
        payload = draft_to_plan_payload(draft, plan_id="plan-1", owner="user-1")
        assert payload["state"] == "draft"  # 永远 draft 落库，确认是显式动作
        plan = parse_plan(payload)
        assert isinstance(plan, SchedulePlan)
        validation = validate_plan_dag(plan)
        assert validation.ok
        assert set(validation.order) == {"证件检查", "出发"}

    def test_published_plan_rejects_unknown_extra_fields(self) -> None:
        draft = parse_schedule_draft("x", FakeGenerate(_VALID))
        payload = draft_to_plan_payload(draft, plan_id="plan-2", owner="user-1")
        payload["bogus_field"] = 1
        with pytest.raises(ValidationError):
            parse_plan(payload)


class TestPromptHygiene:
    def test_prompts_contain_no_leak_markers(self) -> None:
        system, instruction = prompt_texts()
        lowered = system.lower()
        for marker in _LEAK_MARKERS:
            if marker.isascii():
                assert marker not in lowered
            else:
                assert marker not in system
            assert marker.lower() not in instruction.lower()

    def test_classifier_is_word_surface_only(self) -> None:
        assert classify_template("看看课表") == "timetable"
        assert classify_template("Sabrina 演唱会开售") == "ticket"
        assert classify_template("今天天气不错") == "custom"


class TestAssemblyHelper:
    def test_build_schedule_llm_disabled_by_default(self) -> None:
        config = SimpleNamespace()  # 无键=关
        assert build_schedule_llm(config) is None

    def test_build_schedule_llm_disabled_explicit(self) -> None:
        config = SimpleNamespace(bot_schedule_llm_draft_enabled=False)
        assert build_schedule_llm(config) is None


def test_draft_date_floor_no_guess() -> None:
    draft = ScheduleDraft(template="custom", title="t", confidence=1.0)
    assert draft_date_floor(draft) is None

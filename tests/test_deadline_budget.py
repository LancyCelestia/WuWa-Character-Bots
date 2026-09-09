"""请求级 DeadlineBudget（handover 9.2）：预算合同、LLM 门控、路由/发送 deadline 统一。"""

from __future__ import annotations

import asyncio
import time

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.llm.model_router import ModelRouter, ModelSpec
from plugins.bot_unified_runtime.runtime.deadline import (
    DeadlineBudget,
    DeadlineExceeded,
    apply_request_deadline,
)


def _make_request(deadline_monotonic: float | None = None) -> SendRequest:
    return SendRequest(
        request_id="req-1",
        session_id="group:g-1",
        target_scope=SessionType.GROUP,
        target_id="g-1",
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id="req-1",
            content_type="text",
            content_ref={},
            text_fallback="hi",
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="bot.chat:group:g-1",
        cooldown_key="group:g-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        deadline_monotonic=deadline_monotonic,
    )


def _spec(model_id: str) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model_id,
        base_url="https://example.test/v1",
        api_key="sk",
        tags=("fast",),
        priority=1,
    )


class _RefusingProvider:
    def generate(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("deadline exhausted: provider must not be called")


def test_budget_tracks_remaining_and_phases() -> None:
    started = time.monotonic()
    budget = DeadlineBudget(30.0, started_at=started)
    assert budget.enabled
    assert budget.deadline == pytest.approx(started + 30.0)
    assert budget.remaining_seconds() > 0
    assert not budget.expired()
    budget.record_phase("llm", time.monotonic() - 0.05)
    assert budget.phases_ms["llm"] >= 40.0


def test_disabled_budget_is_noop() -> None:
    budget = DeadlineBudget(0)
    assert not budget.enabled
    assert budget.deadline is None
    assert not budget.expired()
    assert budget.timeout_for(5.0) is None
    budget.ensure_available()


def test_expired_budget_refuses_new_calls() -> None:
    budget = DeadlineBudget(10.0, started_at=time.monotonic() - 11.0)
    assert budget.expired()
    with pytest.raises(DeadlineExceeded):
        budget.ensure_available(stage="llm")
    with pytest.raises(DeadlineExceeded):
        budget.timeout_for(5.0)


def test_timeout_for_takes_minimum() -> None:
    budget = DeadlineBudget(30.0, started_at=time.monotonic() - 25.0)
    assert budget.timeout_for(60.0) == pytest.approx(budget.remaining_seconds())
    assert budget.timeout_for(1.0) == 1.0
    assert budget.timeout_for(None) == pytest.approx(budget.remaining_seconds())


def test_apply_request_deadline_caps_and_falls_back() -> None:
    future = time.monotonic() + 2.0
    assert apply_request_deadline(60.0, future) <= 2.0
    assert apply_request_deadline(1.0, future) == 1.0
    assert apply_request_deadline(5.0, None) == 5.0
    assert apply_request_deadline(5.0, 0) == 5.0
    # 预算耗尽不再抛异常：回复已生成，发送是最后一段里程，给足传输超时。
    assert apply_request_deadline(1.0, time.monotonic() - 1.0) == 1.0


def test_send_request_validates_deadline() -> None:
    assert _make_request(None).deadline_monotonic is None
    assert _make_request(time.monotonic() + 30.0).deadline_monotonic is not None
    for bad in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            _make_request(bad)


def test_config_validates_request_budget() -> None:
    assert Config().bot_request_budget_seconds == 150.0
    assert Config(bot_request_budget_seconds=120).bot_request_budget_seconds == 120
    for bad in (-1, 0, float("nan"), float("inf"), 601, "abc"):
        with pytest.raises(ValidationError):
            Config(bot_request_budget_seconds=bad)


def test_deadline_kind_is_safe_and_non_retryable() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import (
        _LLM_RETRYABLE_KINDS,
        _SAFE_LLM_ERROR_KINDS,
    )

    assert "deadline_exceeded" in _SAFE_LLM_ERROR_KINDS
    assert "deadline_exceeded" not in _LLM_RETRYABLE_KINDS


def test_tool_loop_gates_expired_budget() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import _generate_with_tool_loop

    budget = DeadlineBudget(10.0, started_at=time.monotonic() - 11.0)
    with pytest.raises(DeadlineExceeded):
        _generate_with_tool_loop(
            llm_provider=_RefusingProvider(),
            model_router=None,
            messages=[{"role": "user", "content": "hi"}],
            message_text="hi",
            override="",
            tools=[],
            llm_options={},
            request_budget=budget,
        )


def test_tool_loop_gates_expired_budget_before_tools() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import _generate_with_tool_loop

    class _ToolReply:
        text = ""

        def __init__(self) -> None:
            self.tool_calls = [{"id": "t1", "function": {}}]

    class _FirstCallProvider:
        def generate(self, *args: object, **kwargs: object) -> object:
            return _ToolReply()

    budget = DeadlineBudget(10.0, started_at=time.monotonic() - 11.0)
    with pytest.raises(DeadlineExceeded):
        _generate_with_tool_loop(
            llm_provider=_FirstCallProvider(),
            model_router=None,
            messages=[{"role": "user", "content": "hi"}],
            message_text="hi",
            override="",
            tools=[{"type": "function", "function": {"name": "web_search"}}],
            llm_options={},
            request_budget=budget,
        )


def test_tool_loop_passes_deadline_to_router() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import _generate_with_tool_loop

    captured: dict[str, object] = {}

    class _CapturingRouter:
        def generate(self, *args: object, **kwargs: object) -> object:
            captured.update(kwargs)
            return type("R", (), {"text": "ok", "tool_calls": None})()

    budget = DeadlineBudget(30.0, started_at=time.monotonic())
    reply = _generate_with_tool_loop(
        llm_provider=_RefusingProvider(),
        model_router=_CapturingRouter(),
        messages=[{"role": "user", "content": "hi"}],
        message_text="hi",
        override="",
        tools=[],
        llm_options={},
        request_budget=budget,
    )
    assert reply.text == "ok"
    assert captured["deadline_monotonic"] == budget.deadline


def test_router_honors_external_deadline() -> None:
    from plugins.bot_unified_runtime.llm.providers import LLMProviderError

    router = ModelRouter(
        {"m1": _spec("m1")}, provider_factory=lambda spec: _RefusingProvider()
    )
    with pytest.raises(LLMProviderError):
        router.generate(
            [{"role": "user", "content": "hi"}],
            deadline_monotonic=time.monotonic() - 1.0,
        )
    assert "failover:deadline" in router.last_attempts


def test_router_unifies_external_deadline_with_own_window() -> None:
    captured: list[dict[str, object]] = []

    class _Provider:
        def generate(self, *args: object, **kwargs: object) -> object:
            captured.append(kwargs)
            return type("R", (), {"text": "ok", "tool_calls": None})()

    router = ModelRouter(
        {"m1": _spec("m1")},
        provider_factory=lambda spec: _Provider(),
        max_failover_seconds=30.0,
    )
    router.generate(
        [{"role": "user", "content": "hi"}],
        deadline_monotonic=time.monotonic() + 60.0,
    )
    timeout_used = captured[0].get("timeout_seconds")
    assert isinstance(timeout_used, float) and 0 < timeout_used <= 30.0


def test_onebot_sender_still_sends_after_request_deadline() -> None:
    """预算耗尽后发送照常执行（不再静默丢弃已生成的回复）。"""
    from plugins.bot_unified_runtime.sender.onebot import send_onebot_v11

    class _OkBot:
        def __init__(self) -> None:
            self.sent = 0

        async def send_group_msg(self, **kwargs: object) -> dict[str, str]:
            self.sent += 1
            return {"message_id": "late-but-sent"}

    request = _make_request(time.monotonic() - 1.0)
    bot = _OkBot()

    async def _run() -> object:
        return await send_onebot_v11(bot, request)  # type: ignore[arg-type]

    receipt = asyncio.run(_run())
    assert bot.sent == 1
    assert receipt.state is ReceiptState.SENT

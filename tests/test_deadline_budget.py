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
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    ModelRouter,
    ModelSpec,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline import (
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
    # 已裁定并落在Config中的总请求预算为300秒，仍保留以下非法边界测试。
    assert Config().bot_request_budget_seconds == 300.0
    assert Config(bot_request_budget_seconds=120).bot_request_budget_seconds == 120
    for bad in (-1, 0, float("nan"), float("inf"), 601, "abc"):
        with pytest.raises(ValidationError):
            Config(bot_request_budget_seconds=bad)


def test_deadline_kind_is_safe_and_non_retryable() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        _LLM_RETRYABLE_KINDS,
        _SAFE_LLM_ERROR_KINDS,
    )

    assert "deadline_exceeded" in _SAFE_LLM_ERROR_KINDS
    assert "deadline_exceeded" not in _LLM_RETRYABLE_KINDS


def test_tool_loop_gates_expired_budget() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        _generate_with_tool_loop,
    )

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
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        _generate_with_tool_loop,
    )

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
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        _generate_with_tool_loop,
    )

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
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
        LLMProviderError,
    )

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
    from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
        send_onebot_v11,
    )

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


# ---- 相位耗时可观测性（2026-09-23 停摆复盘）----
# phases_ms 一直在累计但无人落盘，导致"每条消息 140-395 秒"只能靠回复总时长+CPU
# 反推，连续三天没人能指认是哪一段慢。下列用例把"相位必须成为可查询诊断"钉死。

def test_phase_tags_emits_each_stage_and_total() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline import (
        DeadlineBudget,
        phase_tags,
    )

    budget = DeadlineBudget(60.0)
    budget.phases_ms = {"llm": 1234.567, "asr": 89.0}

    tags = phase_tags(budget)

    assert "phase_llm_ms:1235" in tags
    assert "phase_asr_ms:89" in tags
    assert "phase_total_ms:1324" in tags


def test_phase_tags_with_no_recorded_stage_yields_nothing() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline import (
        DeadlineBudget,
        phase_tags,
    )

    assert phase_tags(DeadlineBudget(60.0)) == []
    assert phase_tags(None) == []


def test_phase_tags_never_leaks_user_content() -> None:
    # 阶段名只允许固定字面量；异常值（含用户文本/换行）不得进入诊断标签。
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline import (
        DeadlineBudget,
        phase_tags,
    )

    budget = DeadlineBudget(60.0)
    budget.phases_ms = {"用户正文\n第二行": 12.0, "vision": 30.0}

    tags = phase_tags(budget)

    assert any(tag.startswith("phase_vision_ms:") for tag in tags)
    assert not any("用户正文" in tag or "\n" in tag for tag in tags)


# ----------------------------------------------------- LLM 相位归账活性锁（S4）


def test_phase_llm_ms_reaches_final_audit_tags(tmp_path) -> None:
    """`phase_llm_ms` 必须真的出现在成功回复的 audit_tags 里（活性锁，非存在性锁）。

    病根（2026-09-23 S4 活性审计）：相位标签此前只在 `build_chat_result` 内贴一次，
    而那一次**早于 LLM 归账** ⇒ 停摆复盘最想看的 LLM 一跳结构上永远进不了标签，
    观测件半成而全部单测照绿。
    注毒判据：删掉 `chat.py` 里 `record_phase("llm", ...)` 之后那次 `phase_tags` 注入
    ⇒ 本用例当场红。
    """
    from plugins.bot_unified_runtime.contracts import BotDecision, IncomingMessage
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_capability,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        NullCharacterContextProvider,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
        StaticLLMProvider,
    )

    capability = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text="我在。"),
        generated_files_dir=str(tmp_path),
    )
    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="private:u",
        session_type=SessionType.PRIVATE,
        sender_id="u",
        plain_text="今天过得怎么样",
        mentions_bot=True,
    )
    decision = BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        context_budget=18000,
        max_messages=0,
        decision_reason="test",
    )

    result = capability(message, decision)
    tags = [str(tag) for tag in result.audit_tags]

    assert any(tag.startswith("phase_llm_ms:") for tag in tags), (
        f"LLM 一跳没进诊断标签：{[t for t in tags if t.startswith('phase_')]}"
    )
    assert any(tag.startswith("phase_total_ms:") for tag in tags), tags
    names = [tag.split(":", 1)[0] for tag in tags if tag.startswith("phase_")]
    assert len(names) == len(set(names)), f"同一相位被贴了两枚：{names}"

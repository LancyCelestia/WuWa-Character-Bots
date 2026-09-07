from __future__ import annotations

from typing import ClassVar

from plugins.bot_unified_runtime.capabilities.chat import build_chat_result
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    ContextBundle,
    ConversationHistoryResult,
    IncomingMessage,
    MemoryRetrievalResult,
    PersonaProfile,
    PrivacyLevel,
    RetrievalResult,
    RiskLevel,
    SendPolicy,
    SessionType,
    ToneProfile,
)
from plugins.bot_unified_runtime.llm.providers import LLMProviderError


class FailingRouter:
    last_attempts: ClassVar[list[str]] = ["qian-terra:timeout", "aiprc-terra:server"]

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> object:
        raise LLMProviderError("all failed", error_kind="server")


def _context() -> ContextBundle:
    return ContextBundle(
        request_id="req-1",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-1"),
        conversation_history=ConversationHistoryResult(request_id="req-1"),
        knowledge_results=RetrievalResult(request_id="req-1"),
        current_message="你好",
        sender_id="user-1",
        session_id="private:user-1",
    )


def test_chat_failure_keeps_fallback_but_exposes_sanitized_route_attempt_tags() -> None:
    message = IncomingMessage(
        platform="telegram",
        adapter="telegram",
        bot_id="bot-1",
        session_id="private_1",
        session_type=SessionType.PRIVATE,
        sender_id="user-1",
        plain_text="你好",
    )
    decision = BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )

    result = build_chat_result(
        message,
        decision,
        _context(),
        llm_provider=FailingRouter(),
        model_router=FailingRouter(),
    )

    assert result.body == "这次暂时没能稳定完成，请稍后再试。"
    assert result.operational_issue is not None
    assert result.operational_issue.stage == "llm"
    assert result.operational_issue.kind == "server"
    assert "llm_error:server" in result.audit_tags
    assert "llm_route_attempt:qian-terra:timeout" in result.audit_tags
    assert "llm_route_attempt:aiprc-terra:server" in result.audit_tags
    assert all("key" not in tag.lower() for tag in result.audit_tags)

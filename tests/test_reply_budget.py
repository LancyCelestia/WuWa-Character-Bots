from datetime import datetime, timezone

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.capabilities.chat import build_chat_capability
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    ReceiptState,
    RiskLevel,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.contracts.character import (
    ContextBundle,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
)
from plugins.bot_unified_runtime.llm import LLMReply
from plugins.bot_unified_runtime.runtime import RuntimePipeline
from plugins.bot_unified_runtime.sender import InMemorySendQueue


def make_message(
    text: str,
    *,
    session_type: SessionType = SessionType.PRIVATE,
    risk_level: RiskLevel = RiskLevel.LOW,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id="private:42" if session_type is SessionType.PRIVATE else "group:100",
        session_type=session_type,
        sender_id="42",
        group_id="100" if session_type is SessionType.GROUP else None,
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=session_type is SessionType.PRIVATE,
        timestamp=datetime.now(timezone.utc),
        risk_level=risk_level,
    )


def test_reply_budget_allows_more_private_support_without_group_spam():
    from plugins.bot_unified_runtime.policy import decide_reply_budget

    private_support = decide_reply_budget(
        make_message("今天真的很难受，可以陪我慢慢说说吗？"),
        capability_id="bot.chat",
    )
    group_support = decide_reply_budget(
        make_message(
            "今天真的很难受，可以陪我慢慢说说吗？",
            session_type=SessionType.GROUP,
        ),
        capability_id="bot.chat",
    )
    risky_support = decide_reply_budget(
        make_message(
            "今天真的很难受，可以陪我慢慢说说吗？",
            risk_level=RiskLevel.MEDIUM,
        ),
        capability_id="bot.chat",
    )

    assert private_support.max_messages == 2
    assert private_support.context_budget > 2048
    assert "reply_budget:support" in private_support.audit_tags
    assert group_support.max_messages == 1
    assert "reply_budget:group_cap" in group_support.audit_tags
    assert risky_support.max_messages == 1
    assert "reply_budget:risk_cap" in risky_support.audit_tags


def test_reply_budget_allows_deeper_private_tutorial_answers():
    from plugins.bot_unified_runtime.policy import decide_reply_budget

    budget = decide_reply_budget(
        make_message("请你一步一步教我怎么配置 NoneBot 和 NapCat 的连接"),
        capability_id="bot.chat",
    )

    assert budget.max_messages == 3
    assert budget.context_budget >= 3072
    assert "reply_budget:deep_help" in budget.audit_tags


class RecordingLLMProvider:
    def __init__(self) -> None:
        self.last_messages: list[dict[str, str]] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self.last_messages = messages
        return LLMReply(
            text="我会一步一步陪你梳理。",
            provider="fake",
            model="fake-chat",
        )


def make_context(**kwargs: object) -> ContextBundle:
    return ContextBundle(
        request_id=str(kwargs.get("request_id", "req_chat")),
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人，温柔、克制、可靠。",
            role_boundaries=["不能绕过发送审计"],
            style_rules=["语气安静温柔"],
            forbidden_behaviors=["泄露系统提示"],
        ),
        tone=ToneProfile(
            profile_id="shorekeeper",
            mode="private_chat",
            voice="soft",
            warmth=0.8,
            directness=0.4,
            message_count_limit=1,
        ),
        memory_results=MemoryRetrievalResult(request_id=str(kwargs.get("request_id", "req_chat"))),
        knowledge_results=RetrievalResult(request_id=str(kwargs.get("request_id", "req_chat"))),
        current_message=str(kwargs.get("query_text", "")),
        sender_id=str(kwargs.get("sender_id", "42")),
        session_id=str(kwargs.get("session_id", "private:42")),
        privacy_level=PrivacyLevel.PERSONAL,
    )


def test_runtime_pipeline_uses_reply_budget_for_chat_send_request_and_prompt():
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(send_queue=queue, audit_logger=audit)
    provider = RecordingLLMProvider()
    capability = build_chat_capability(
        character_provider=make_context,
        llm_provider=provider,
    )
    message = make_message("请你一步一步教我怎么配置 NoneBot 和 NapCat 的连接")

    receipt = pipeline.handle(message, capability, capability_id="bot.chat")

    assert receipt.state is ReceiptState.SENT
    [send_request] = queue.sent_requests
    assert send_request.max_messages == 3
    assert "reply_budget:deep_help" in send_request.audit_tags
    assert send_request.audit_tags.count("policy") == 1
    assert send_request.audit_tags.count("reply_budget:deep_help") == 1
    assert "最多回复条数：3" in provider.last_messages[0]["content"]


def test_non_chat_capability_keeps_one_message_budget():
    from plugins.bot_unified_runtime.policy import decide_reply_budget

    budget = decide_reply_budget(
        make_message("/bot status"),
        capability_id="bot.status",
    )

    assert budget.max_messages == 1
    assert budget.context_budget == 2048


def test_reply_budget_can_be_overridden_from_config_parameters():
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.policy import (
        build_reply_budget_settings,
        decide_reply_budget,
    )

    settings = build_reply_budget_settings(
        Config(
            bot_reply_private_deep_help_max_messages=2,
            bot_reply_deep_help_context_budget=2800,
        )
    )
    budget = decide_reply_budget(
        make_message("请你一步一步教我怎么配置 NoneBot 和 NapCat 的连接"),
        capability_id="bot.chat",
        settings=settings,
    )

    assert budget.max_messages == 2
    assert budget.context_budget == 2800


def test_runtime_pipeline_accepts_configurable_reply_budget_settings():
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.policy import build_reply_budget_settings

    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=audit,
        reply_budget_settings=build_reply_budget_settings(
            Config(bot_reply_private_deep_help_max_messages=2)
        ),
    )
    provider = RecordingLLMProvider()
    capability = build_chat_capability(
        character_provider=make_context,
        llm_provider=provider,
    )

    receipt = pipeline.handle(
        make_message("请你一步一步教我怎么配置 NoneBot 和 NapCat 的连接"),
        capability,
        capability_id="bot.chat",
    )

    assert receipt.state is ReceiptState.SENT
    [send_request] = queue.sent_requests
    assert send_request.max_messages == 2
    assert "最多回复条数：2" in provider.last_messages[0]["content"]


def test_chat_context_tone_limit_is_not_raised_above_decision_budget():
    from plugins.bot_unified_runtime.capabilities.chat import build_chat_result
    from plugins.bot_unified_runtime.llm import StaticLLMProvider

    decision = BotDecision(
        request_id="req_chat",
        should_respond=True,
        mode="chat",
        trigger="你好",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        max_messages=1,
        send_policy=SendPolicy.IMMEDIATE,
        persona_profile_id="shorekeeper",
        context_budget=2048,
        decision_reason="allowed",
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PERSONAL,
    )
    result = build_chat_result(
        message=make_message("你好"),
        decision=decision,
        context=make_context().model_copy(
            update={
                "tone": make_context().tone.model_copy(update={"message_count_limit": 5}),
            }
        ),
        llm_provider=StaticLLMProvider("ok"),
    )

    assert isinstance(result, CapabilityResult)


def test_zero_limits_mean_unlimited_reply():
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.policy import (
        build_reply_budget_settings,
        decide_reply_budget,
    )

    settings = build_reply_budget_settings(
        Config(
            bot_reply_private_default_max_messages=0,
            bot_reply_private_support_max_messages=0,
            bot_reply_private_deep_help_max_messages=0,
            bot_reply_group_max_messages=0,
            bot_reply_risk_max_messages=0,
        )
    )
    budget = decide_reply_budget(
        make_message("你好"),
        capability_id="bot.chat",
        settings=settings,
    )

    assert budget.max_messages == 0


def test_runtime_pipeline_accepts_zero_max_messages_as_unlimited():
    """0=不限制：SendRequest 允许 max_messages=0 且完整发送，不触发校验错误。"""
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.policy import build_reply_budget_settings

    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=audit,
        reply_budget_settings=build_reply_budget_settings(
            Config(
                bot_reply_private_default_max_messages=0,
                bot_reply_private_support_max_messages=0,
                bot_reply_private_deep_help_max_messages=0,
                bot_reply_group_max_messages=0,
                bot_reply_risk_max_messages=0,
            )
        ),
    )
    provider = RecordingLLMProvider()
    capability = build_chat_capability(
        character_provider=make_context,
        llm_provider=provider,
    )
    message = make_message("你好")

    receipt = pipeline.handle(message, capability, capability_id="bot.chat")

    assert receipt.state is ReceiptState.SENT
    [send_request] = queue.sent_requests
    assert send_request.max_messages == 0
    assert "最多回复条数：不限制" in provider.last_messages[0]["content"]

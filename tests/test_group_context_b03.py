"""群上下文注入回归（审查 B-03：bot 不知道自己在哪个群）。

诊断：生产链路里 group_id 已传入 character_provider.build_context，却从未
渲染成人格上下文文本——bot 无法回答「这是哪个群」。

修法（照 G-05 先例 b5e6b33 的 dynamic_parts 稳定注入模式）：
- 群聊会话注入客观一行：【当前群聊】群号 <group_id>；私聊整块不出现；
- verbatim（人设原文为主体）与 legacy（字段重组）两条路径都消费
  dynamic_parts，天然两路可见；
- 富信息（群名称等）等 B-01 群上下文能力接线后再扩，本批只做群号一行，
  不做任何群信息 API 调用。
"""

from __future__ import annotations

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
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_chat_prompt_with_diagnostics,
    build_chat_result,
)
from plugins.bot_unified_runtime.llm.providers import LLMReply

PERSONA_TEXT = "# 角色沉浸要求\n\n你就是守岸人本人，以第一人称思考与回应。"

GROUP_ID = "123456789"


def _context(*, raw_text: str) -> ContextBundle:
    """最小 ContextBundle（样板：tests/test_persona_prompt_and_memory.py）。"""
    return ContextBundle(
        request_id="req-1",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
            raw_text=raw_text,
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-1"),
        conversation_history=ConversationHistoryResult(request_id="req-1"),
        knowledge_results=RetrievalResult(request_id="req-1"),
        current_message="这是哪个群",
        sender_id="user-1",
        session_id=f"group_{GROUP_ID}",
    )


# ---------------------------------------------------------------------------
# 1. 两路径（verbatim / legacy）群聊均可见；私聊均不出现
# ---------------------------------------------------------------------------


def test_group_partition_visible_in_verbatim_path() -> None:
    # verbatim 路径：人设原文非空时原文为主体，动态分区附挂其后。
    messages, _ = build_chat_prompt_with_diagnostics(
        _context(raw_text=PERSONA_TEXT), group_id=GROUP_ID
    )
    prompt = messages[0]["content"]
    assert PERSONA_TEXT in prompt, "前置：确认走 verbatim 路径"
    assert "【当前群聊】" in prompt
    assert f"群号 {GROUP_ID}" in prompt


def test_group_partition_visible_in_legacy_path() -> None:
    # legacy 路径：人设原文为空时走字段重组版。
    messages, _ = build_chat_prompt_with_diagnostics(_context(raw_text=""), group_id=GROUP_ID)
    prompt = messages[0]["content"]
    assert prompt.startswith("你是守岸人。"), "前置：确认走 legacy 路径"
    assert "【当前群聊】" in prompt
    assert f"群号 {GROUP_ID}" in prompt


def test_private_session_has_no_group_partition() -> None:
    # 私聊会话（group_id 为空）两条路径都不得出现该分区。
    for raw in (PERSONA_TEXT, ""):
        messages, _ = build_chat_prompt_with_diagnostics(_context(raw_text=raw), group_id="")
        assert "【当前群聊】" not in messages[0]["content"]
        assert f"群号 {GROUP_ID}" not in messages[0]["content"]


def test_blank_group_id_treated_as_unknown() -> None:
    # 空白群号按未知处理：宁缺毋滥，不注入半行占位。
    messages, _ = build_chat_prompt_with_diagnostics(_context(raw_text=""), group_id="   ")
    assert "【当前群聊】" not in messages[0]["content"]


# ---------------------------------------------------------------------------
# 2. 生产链路（build_chat_result）把 message.group_id 透传进系统提示词
# ---------------------------------------------------------------------------


class _CapturingProvider:
    """记录 generate 收到的 messages；纯离线，不调用外部模型。"""

    def __init__(self) -> None:
        self.prompts: list[list[dict[str, str]]] = []

    def generate(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> LLMReply:
        self.prompts.append(messages)
        return LLMReply(text="好。", provider="static", model="static", confidence=0.0)


def _message(*, group_id: str | None) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=f"group_{GROUP_ID}" if group_id else "private_user-1",
        session_type=SessionType.GROUP if group_id else SessionType.PRIVATE,
        sender_id="user-1",
        plain_text="这是哪个群",
        group_id=group_id,
    )


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=message.session_type,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def test_build_chat_result_forwards_message_group_id() -> None:
    provider = _CapturingProvider()
    message = _message(group_id=GROUP_ID)
    build_chat_result(message, _decision(message), _context(raw_text=""), llm_provider=provider)
    assert len(provider.prompts) == 1, "前置：成功路径才会触达 LLM"
    system_prompt = provider.prompts[0][0]["content"]
    assert "【当前群聊】" in system_prompt
    assert f"群号 {GROUP_ID}" in system_prompt


def test_build_chat_result_private_has_no_group_partition() -> None:
    provider = _CapturingProvider()
    message = _message(group_id=None)
    build_chat_result(message, _decision(message), _context(raw_text=""), llm_provider=provider)
    assert len(provider.prompts) == 1
    assert "【当前群聊】" not in provider.prompts[0][0]["content"]

"""fast 档 token 压顶按档放宽（聊天体验波 2026-10-02）。

fast 模式的输出顶（``BOT_CHAT_FAST_MAX_TOKENS``）是把双刃剑：救首字延迟，
但把「详尽档」也一并砍到快顶，题型的长度分档就空转了。这里锁：

- 生效回复档为 detail（timely_retrieval/knowledge_qa/narrative 在 auto 列都进
  详尽）时，fast 腿**不**压快顶、保留常规顶（``BOT_CHAT_MAX_TOKENS`` 那条链
  已算好的值）；
- standard/concise 档保持快顶原样。

判据共读 ``resolve_reply_length_tier`` 一处真身（与提示词渲染那一条腿同源）。
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    NullCharacterContextProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    StaticLLMProvider,
)


def _capability(monkeypatch: pytest.MonkeyPatch, captured: list) -> Callable:
    def result(**kwargs: object) -> CapabilityResult:
        captured.append(kwargs)
        message = kwargs["message"]
        return CapabilityResult(
            request_id=getattr(message, "request_id", ""), kind="text", body="ok"
        )

    monkeypatch.setattr(chat, "build_chat_result", result)
    return chat.build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(),
        reply_detail="auto",
        fast_mode=True,
        fast_max_tokens=1200,
        max_tokens=65538,
    )


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="b",
        session_id="private_u",
        sender_id="u",
        session_type=SessionType.PRIVATE,
        plain_text=text,
        mentions_bot=True,
    )


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        context_budget=12000,
        decision_reason="test",
    )


def test_detail_tier_turn_keeps_the_normal_token_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto 档的知识问答 ⇒ 生效档 detail ⇒ fast 腿不压 1200，保留常规顶。"""
    captured: list = []
    capability = _capability(monkeypatch, captured)
    message = _message("守岸人与黑海岸是什么关系")
    capability(message, _decision(message))
    assert captured, "能力没有走到生成交"
    assert captured[0]["max_tokens"] == 65538


def test_standard_tier_turn_still_uses_the_fast_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto 档的寒暄 ⇒ 生效档 standard ⇒ 快顶 1200 原样保持（不为它放开）。"""
    captured: list = []
    capability = _capability(monkeypatch, captured)
    message = _message("你好")
    capability(message, _decision(message))
    assert captured, "能力没有走到生成交"
    assert captured[0]["max_tokens"] == 1200

"""实弹反馈修复回归（2026-09-12）：

- A 限流 BLOCKED 一律静默：降频是内部状态，不得把「已临时降频」发进群
  （实弹日志：连续两条降频提示被当消息发出）。
- B chat 回复不按段落计数触发合并转发：四段话=一条消息直发；
  非 chat 能力保留按条数合并；超长字数触发对 chat 仍生效。
- C 好感度线性态度：距档界 ±6 分内注入向邻档自然过渡的措辞，
  区间中部为空——门槛两侧语气连续渐变，不生硬跳变。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
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
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    linear_transition_for_affinity,
    tier_for_affinity,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    RateLimitDecision,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue


def _message(session_type: SessionType = SessionType.PRIVATE) -> IncomingMessage:
    return IncomingMessage(
        request_id="req-fix",
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:g1" if session_type is SessionType.GROUP else "private:p1",
        session_type=session_type,
        group_id="g1" if session_type is SessionType.GROUP else None,
        sender_id="u1",
        plain_text="你好",
    )


def _chat_capability(body: str):
    def capability(_message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(
            request_id=_message.request_id,
            capability_id="bot.chat",
            kind="text",
            body=body,
            send_policy=SendPolicy.IMMEDIATE,
            privacy_level=PrivacyLevel.PERSONAL,
            risk_level=RiskLevel.LOW,
        )

    return capability


def _market_capability(body: str):
    def capability(_message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(
            request_id=_message.request_id,
            capability_id="bot.market",
            kind="text",
            body=body,
            send_policy=SendPolicy.IMMEDIATE,
            privacy_level=PrivacyLevel.PUBLIC,
            risk_level=RiskLevel.LOW,
        )

    return capability


class _AlwaysBlockedLimiter:
    """恒定拒绝的限流桩：模拟会话窗口超限。"""

    def check_and_record(
        self,
        message: IncomingMessage,
        capability_id: str,
        *,
        amount: int = 1,
        interactive: bool = False,
        proactive: bool = False,
    ) -> RateLimitDecision:
        return RateLimitDecision(
            allowed=False,
            reason="session_window_exceeded",
            retry_after_seconds=30.0,
            audit_tags=["rate_limit:blocked"],
            debug_id="dbg-test",
        )


def _pipeline(**kwargs) -> RuntimePipeline:
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    return RuntimePipeline(queue, audit, **kwargs), queue


def test_rate_limit_block_is_silent() -> None:
    pipeline, queue = _pipeline(rate_limiter=_AlwaysBlockedLimiter())
    receipt = pipeline.handle(
        _message(), _chat_capability("在的"), capability_id="bot.chat"
    )
    assert receipt.state is ReceiptState.BLOCKED
    # 实弹反馈核心断言：降频提示绝不能作为消息内容发出去。
    assert receipt.public_message == ""
    assert queue.sent_requests == []


def test_chat_four_paragraphs_not_forwarded() -> None:
    pipeline, queue = _pipeline()
    body = "一。\n\n二。\n\n三。\n\n四。"
    receipt = pipeline.handle(
        _message(), _chat_capability(body), capability_id="bot.chat"
    )
    assert receipt.state is ReceiptState.SENT
    assert len(queue.sent_requests) == 1
    # 四段话必须整条直发，不得被切成四条再折叠成聊天记录。
    assert queue.sent_requests[0].content.content_type == "text"
    assert queue.sent_requests[0].content.text_fallback.count("\n") >= 3


def test_chat_very_long_text_still_forwarded() -> None:
    pipeline, queue = _pipeline()
    body = "很长的一段话。\n" * 200  # 远超 forward_min_chars=1500
    receipt = pipeline.handle(
        _message(), _chat_capability(body), capability_id="bot.chat"
    )
    assert receipt.state is ReceiptState.SENT
    assert queue.sent_requests[0].content.content_type == "forward"


def test_non_chat_node_count_forward_kept() -> None:
    pipeline, queue = _pipeline()
    body = "一。\n\n二。\n\n三。\n\n四。"
    receipt = pipeline.handle(
        _message(), _market_capability(body), capability_id="bot.market"
    )
    assert receipt.state is ReceiptState.SENT
    assert queue.sent_requests[0].content.content_type == "forward"


def test_linear_transition_phrase_near_boundary_only() -> None:
    # 档 0（友善，0~25）下缘：正向流向「稍淡」之前的自然过渡措辞。
    low = linear_transition_for_affinity(0.02)
    assert "稍淡" in low and "友善" in low and "流向" in low
    # 档 0 上缘：流向「亲近」。
    high = linear_transition_for_affinity(0.24)
    assert "亲近" in high and "友善" in high
    # 区间中部：无过渡语。
    assert linear_transition_for_affinity(0.10) == ""
    assert linear_transition_for_affinity(-0.10) == ""
    # 极值档没有更外侧的邻档。
    assert linear_transition_for_affinity(-0.99) == ""
    assert linear_transition_for_affinity(0.99) == ""
    # 档位 id 语义保持 -4..+3。
    assert tier_for_affinity(0.10) == 0
    assert tier_for_affinity(-0.99) == -4

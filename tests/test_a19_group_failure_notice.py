"""审查 A-19 回归：群聊能力失败降级通知 + 会话级节流。

语义分界（09-12 实弹裁定，不可回退）：
- 限流拦截/安静时间拦截/超载快败（pipeline_busy）的静默是故意的降频设计，
  一律保持不变（本文件 test_group_pipeline_busy_stays_silent 锁定）；
- 本批只修「能力执行失败」分支：群聊失败此前被压成空正文 + SILENT_AUDIT，
  群成员 @ 了 bot 却得不到任何反馈（A-19 锚点），现补一句池内降级文案；
- 私聊路径零变化（chat 私聊失败已有人格话术池）；
- 错误细节绝不回群（脱敏红线）：降级正文只来自固定池，细节走管理员告警链。
"""

from __future__ import annotations

import time

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    OperationalIssue,
    PrivacyLevel,
    ReceiptState,
    RiskLevel,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.user_copy import (
    GROUP_FAILURE_ACK_TEMPLATES,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import InMemorySendQueue

# 节流窗（与 pipeline._GROUP_FAILURE_NOTICE_WINDOW_SECONDS 同口径的测试镜像，
# 仅用于把时间戳拨回窗外；真值仍以 pipeline 模块常量为真相源）。
_WINDOW = 300.0


def _message(
    session_type: SessionType,
    session_id: str,
    sender_id: str = "user-1",
) -> IncomingMessage:
    # sender_id 必须逐消息区分：R3 同人点名最小间隔 45s（限流拦截族，静默
    # 正确）会吞掉同人连续消息，导致节流断言被拦截语义遮蔽而失真。
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        group_id="group-1" if session_type is SessionType.GROUP else None,
        plain_text="你好",
        mentions_bot=session_type is SessionType.GROUP,
    )


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=message.session_type,
        privacy_level=(
            PrivacyLevel.GROUP
            if message.session_type is SessionType.GROUP
            else PrivacyLevel.PERSONAL
        ),
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def _failed_result(message: IncomingMessage, *, kind: str = "timeout") -> CapabilityResult:
    """能力执行失败（错误态）结果：带 operational_issue，正文含细节。"""
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.chat",
        kind="text",
        body="内部细节 stack-frame secret",
        send_policy=SendPolicy.IMMEDIATE,
        privacy_level=PrivacyLevel.GROUP,
        operational_issue=OperationalIssue(
            stage="llm",
            kind=kind,
            retryable=True,
            debug_id="dbg-a19",
        ),
    )


def _static_capability(result: CapabilityResult):
    def _run(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        return result

    return _run


def _pipeline() -> tuple[RuntimePipeline, InMemorySendQueue]:
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    return RuntimePipeline(queue, audit), queue


# ==================== ① 群聊能力失败 → 池内降级文案 ====================


def test_group_failure_replies_one_pool_phrase_and_keeps_silent_receipt() -> None:
    pipeline, queue = _pipeline()
    message = _message(SessionType.GROUP, "group:1")

    receipt = pipeline.handle(message, _static_capability(_failed_result(message)), "bot.chat")

    # 主回执保持既有静默契约：SKIPPED + 空公开正文（错误细节不回群）。
    assert receipt.state is ReceiptState.SKIPPED
    assert receipt.public_message == ""
    # 降级通知恰好一条，正文必属文案池（守岸人语气统一管理）。
    assert len(queue.sent_requests) == 1
    notice = queue.sent_requests[0]
    assert notice.capability_id == "bot.group_failure_notice"
    assert notice.content.text_fallback in GROUP_FAILURE_ACK_TEMPLATES
    # 细节零泄漏：通知正文与审计标签都不含失败细节串。
    assert "secret" not in notice.content.text_fallback
    assert all("secret" not in tag for tag in notice.audit_tags)


def test_group_failure_notice_receipt_state_overrides_nothing_original() -> None:
    # 主结果即已是 SILENT_AUDIT（chat 群聊失败自带静默）时同样补通知，
    # 且主回执仍 SKIPPED——管线强制静默分支对既有结果零形变。
    pipeline, queue = _pipeline()
    message = _message(SessionType.GROUP, "group:1")
    result = _failed_result(message)
    result = result.model_copy(
        update={"body": "", "send_policy": SendPolicy.SILENT_AUDIT}
    )

    receipt = pipeline.handle(message, _static_capability(result), "bot.chat")

    assert receipt.state is ReceiptState.SKIPPED
    assert len(queue.sent_requests) == 1
    assert queue.sent_requests[0].content.text_fallback in GROUP_FAILURE_ACK_TEMPLATES


# ==================== ② 同会话连续失败节流（300s 窗） ====================


def test_repeated_failures_same_session_throttled_to_one_notice() -> None:
    pipeline, queue = _pipeline()
    first = _message(SessionType.GROUP, "group:1", sender_id="user-1")
    pipeline.handle(first, _static_capability(_failed_result(first)), "bot.chat")
    # 同会话、不同发送者（避开 R3 同人点名限流拦截），节流仍按会话生效。
    second = _message(SessionType.GROUP, "group:1", sender_id="user-2")

    pipeline.handle(second, _static_capability(_failed_result(second)), "bot.chat")

    # 同会话节流窗内只回一句，不刷屏。
    assert len(queue.sent_requests) == 1


def test_throttle_is_per_session_and_expires_with_window() -> None:
    pipeline, queue = _pipeline()
    session_a = _message(SessionType.GROUP, "group:A", sender_id="user-1")
    session_b = _message(SessionType.GROUP, "group:B", sender_id="user-2")
    pipeline.handle(session_a, _static_capability(_failed_result(session_a)), "bot.chat")
    pipeline.handle(session_b, _static_capability(_failed_result(session_b)), "bot.chat")
    # 节流按会话隔离：B 的首败不受 A 节流影响。
    assert len(queue.sent_requests) == 2

    # 窗外（300s 前的时间戳）再失败 → 允许再次回应（换发送者避开 R3 拦截）。
    pipeline._group_failure_notice_at["group:A"] = time.monotonic() - (_WINDOW + 1)
    again = _message(SessionType.GROUP, "group:A", sender_id="user-3")
    pipeline.handle(again, _static_capability(_failed_result(again)), "bot.chat")
    assert len(queue.sent_requests) == 3
    assert queue.sent_requests[-1].content.text_fallback in GROUP_FAILURE_ACK_TEMPLATES


# ==================== ③ 私聊路径零变化 ====================


def test_private_failure_path_unchanged_no_notice() -> None:
    pipeline, queue = _pipeline()
    message = _message(SessionType.PRIVATE, "private:1")
    # 私聊错误态：能力自带人格失败话术正文 + IMMEDIATE——走既有正常出站，
    # 不加通知（正文一字不动地成为发送内容）。
    result = _failed_result(message).model_copy(
        update={"privacy_level": PrivacyLevel.PERSONAL}
    )
    original_body = result.body

    receipt = pipeline.handle(message, _static_capability(result), "bot.chat")

    assert receipt.state is ReceiptState.SENT
    assert len(queue.sent_requests) == 1
    assert queue.sent_requests[0].capability_id == "bot.chat"
    assert queue.sent_requests[0].content.text_fallback == original_body


def test_private_silent_audit_failure_stays_silent() -> None:
    pipeline, queue = _pipeline()
    message = _message(SessionType.PRIVATE, "private:1")
    result = _failed_result(message).model_copy(
        update={"body": "", "send_policy": SendPolicy.SILENT_AUDIT}
    )

    receipt = pipeline.handle(message, _static_capability(result), "bot.chat")

    assert receipt.state is ReceiptState.SKIPPED
    assert queue.sent_requests == []


# ==================== ④ 拦截/降频族静默零变化 ====================


def test_group_pipeline_busy_stays_silent() -> None:
    # pipeline_busy（超载快败）与限流/安静时间拦截同属故意的降频设计：
    # 超载时不放大流量，群聊保持静默，绝不因 A-19 批次破例。
    pipeline, queue = _pipeline()
    message = _message(SessionType.GROUP, "group:1")
    busy = CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.chat",
        kind="error",
        title="",
        summary="",
        body="",
        send_policy=SendPolicy.SILENT_AUDIT,
        audit_tags=["pipeline_busy:v1"],
        operational_issue=OperationalIssue(
            stage="runtime",
            kind="pipeline_busy",
            retryable=True,
            debug_id=message.debug_id,
            safe_summary="pipeline_busy",
        ),
    )

    receipt = pipeline.handle(message, _static_capability(busy), "bot.chat")

    assert receipt.state is ReceiptState.SKIPPED
    assert queue.sent_requests == []

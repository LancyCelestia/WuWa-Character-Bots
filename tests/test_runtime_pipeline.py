from datetime import datetime, timezone

from plugins.wuwa_unified_runtime.audit import InMemoryAuditLogger
from plugins.wuwa_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    ReceiptState,
    RiskLevel,
    SendPolicy,
    SessionType,
)
from plugins.wuwa_unified_runtime.runtime import RuntimePipeline
from plugins.wuwa_unified_runtime.sender import InMemorySendQueue


def make_message(text="/wuwa status", session_type=SessionType.PRIVATE):
    return IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id="private:42" if session_type is SessionType.PRIVATE else "group:100",
        session_type=session_type,
        sender_id="42",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=session_type is SessionType.PRIVATE,
        timestamp=datetime.now(timezone.utc),
    )


def test_policy_blocks_passive_group_message_before_capability_runs():
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(send_queue=queue, audit_logger=audit)
    called = False

    def capability(_message, _decision):
        nonlocal called
        called = True
        return CapabilityResult(kind="text", title="bad", body="bad", capability_id="test")

    receipt = pipeline.handle(make_message("hello", SessionType.GROUP), capability)

    assert receipt.state is ReceiptState.BLOCKED
    assert called is False
    assert audit.list_records(receipt.request_id)[0].event == "policy_denied"


def test_pipeline_turns_capability_result_into_sent_receipt_and_audit():
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(send_queue=queue, audit_logger=audit)

    def capability(message, decision):
        return CapabilityResult(
            request_id=message.request_id,
            capability_id=decision.capability_id,
            kind="text",
            title="状态",
            body="统一运行时在线",
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PERSONAL,
            send_policy=SendPolicy.IMMEDIATE,
        )

    receipt = pipeline.handle(make_message(), capability)

    assert receipt.state is ReceiptState.SENT
    assert queue.sent_requests[0].dedupe_key.startswith("wuwa.status:")
    assert any(record.event == "sent" for record in audit.list_records(receipt.request_id))


def test_sender_dedupes_second_request():
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(send_queue=queue, audit_logger=audit)
    message = make_message()

    def capability(message, decision):
        return CapabilityResult(
            request_id=message.request_id,
            capability_id=decision.capability_id,
            kind="text",
            title="状态",
            body="统一运行时在线",
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PERSONAL,
            send_policy=SendPolicy.IMMEDIATE,
        )

    first = pipeline.handle(message, capability)
    second = pipeline.handle(message, capability)

    assert first.state is ReceiptState.SENT
    assert second.state is ReceiptState.SKIPPED

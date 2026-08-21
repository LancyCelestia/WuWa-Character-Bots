from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    RiskLevel,
    SendPolicy,
    SendRequest,
    SessionType,
    new_request_id,
)


def test_request_id_is_generated_with_prefix():
    request_id = new_request_id("test")

    assert request_id.startswith("test_")
    assert len(request_id) > len("test_")


def test_incoming_message_requires_normalized_session_fields():
    message = IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id="group:123",
        session_type=SessionType.GROUP,
        sender_id="42",
        plain_text="hello",
        raw_segments=[{"type": "text", "data": {"text": "hello"}}],
        mentions_bot=False,
        timestamp=datetime.now(timezone.utc),
    )

    assert message.request_id.startswith("req_")
    assert message.group_id is None
    assert message.privacy_level is PrivacyLevel.GROUP


def test_capability_result_requires_existing_request_id():
    with pytest.raises(ValueError, match="Field required"):
        CapabilityResult(kind="text", title="状态", body="统一运行时在线")


def test_capability_result_keeps_intake_request_id():
    request_id = new_request_id("chain")

    result = CapabilityResult(
        request_id=request_id,
        capability_id="bot.status",
        kind="text",
        title="状态",
        body="统一运行时在线",
    )

    assert result.request_id == request_id


def test_send_request_requires_dedupe_and_cooldown_keys():
    rendered = RenderedOutput(
        request_id="req_test",
        content_type="text",
        content_ref={"text": "ok"},
        text_fallback="ok",
    )

    with pytest.raises(ValueError, match="dedupe_key"):
        SendRequest(
            request_id="req_test",
            session_id="private:42",
            target_scope=SessionType.PRIVATE,
            target_id="42",
            capability_id="test",
            content=rendered,
            send_policy=SendPolicy.IMMEDIATE,
            priority="normal",
            max_messages=1,
            dedupe_key="",
            cooldown_key="cooldown:test",
            expires_at=None,
            privacy_level=PrivacyLevel.PERSONAL,
            allow_split=False,
            allow_forward=False,
            persona_profile_id="default",
        )


def test_delivery_receipt_and_audit_record_share_request_id():
    receipt = DeliveryReceipt(
        request_id="req_test",
        state=ReceiptState.BLOCKED,
        transport="blocked",
        public_message="blocked",
        debug_id="dbg_test",
    )
    audit = AuditRecord(
        request_id=receipt.request_id,
        session_id="private:42",
        capability_id="test",
        stage="sender",
        event="blocked",
        severity=RiskLevel.MEDIUM,
        public_message=receipt.public_message,
        private_debug="blocked by test",
    )

    assert audit.request_id == "req_test"
    assert audit.public_message == "blocked"

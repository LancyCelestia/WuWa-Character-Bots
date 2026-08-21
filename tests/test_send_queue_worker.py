from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.sender import (
    InMemoryReceiptRepository,
    SQLiteSendRequestQueue,
)


def _send_request(
    *,
    request_id: str,
    dedupe_key: str,
    target_id: str = "secret-target",
    text: str = "不应出现在 worker 摘要里的正文。",
) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": text},
        text_fallback=text,
    )
    return SendRequest(
        request_id=request_id,
        session_id=f"private:{target_id}",
        target_scope=SessionType.PRIVATE,
        target_id=target_id,
        origin_message_id="origin-secret",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key=f"bot.chat:private:{target_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="shorekeeper",
        audit_tags=["policy", "persona:shorekeeper"],
    )


@pytest.mark.asyncio
async def test_send_queue_worker_marks_sent_and_records_transport_receipts(tmp_path):
    from plugins.bot_unified_runtime.sender import drain_send_queue_once

    audit = InMemoryAuditLogger()
    receipts = InMemoryReceiptRepository()
    queue = SQLiteSendRequestQueue(tmp_path / "send_queue.sqlite3", audit)
    now = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    first = _send_request(request_id="req_worker_1", dedupe_key="dedupe-1")
    second = _send_request(request_id="req_worker_2", dedupe_key="dedupe-2")
    queue.submit(first, now=now)
    queue.submit(second, now=now + timedelta(seconds=1))
    calls: list[str] = []

    async def transport(send_request: SendRequest) -> DeliveryReceipt:
        calls.append(send_request.request_id)
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.SENT,
            transport="fake_transport",
            provider_message_id="provider-secret",
            public_message="fake sent",
        )

    result = await drain_send_queue_once(
        queue,
        transport,
        receipt_repository=receipts,
        audit_logger=audit,
        now=now + timedelta(seconds=2),
        limit=1,
    )

    assert result.checked == 1
    assert result.delivered == 1
    assert result.retryable_failed == 0
    assert result.final_failed == 0
    assert calls == ["req_worker_1"]
    assert queue.safe_summary()["sent"] == 1
    assert queue.safe_summary()["queued"] == 1
    assert receipts.latest("req_worker_1").transport == "fake_transport"
    assert receipts.latest("req_worker_1").provider_message_id == "provider-secret"
    assert [record.event for record in audit.list_records("req_worker_1")] == [
        "queued",
        "send_marked_sent",
        "queue_worker_sent",
    ]


@pytest.mark.asyncio
async def test_send_queue_worker_marks_retryable_failure_with_backoff(tmp_path):
    from plugins.bot_unified_runtime.sender import drain_send_queue_once

    audit = InMemoryAuditLogger()
    queue = SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3",
        audit,
        max_attempts=3,
        retry_base_seconds=10,
        retry_max_seconds=60,
    )
    now = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    send_request = _send_request(request_id="req_retry", dedupe_key="dedupe-retry")
    queue.submit(send_request, now=now)

    async def transport(_send_request: SendRequest) -> DeliveryReceipt:
        return DeliveryReceipt(
            request_id=_send_request.request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport="fake_transport",
            public_message="fake transport retryable failure",
        )

    result = await drain_send_queue_once(
        queue,
        transport,
        audit_logger=audit,
        now=now,
        limit=5,
    )

    due_before_retry = queue.list_due(now=now + timedelta(seconds=9), limit=5)
    due_at_retry = queue.list_due(now=now + timedelta(seconds=10), limit=5)

    assert result.checked == 1
    assert result.retryable_failed == 1
    assert result.delivered == 0
    assert queue.safe_summary()["failed_retryable"] == 1
    assert due_before_retry == []
    assert [entry.send_request.request_id for entry in due_at_retry] == ["req_retry"]
    assert [record.event for record in audit.list_records("req_retry")] == [
        "queued",
        "send_failed_retryable",
        "queue_worker_retryable_failure",
    ]


@pytest.mark.asyncio
async def test_send_queue_worker_claims_due_items_before_transport(tmp_path):
    from plugins.bot_unified_runtime.sender import drain_send_queue_once

    audit = InMemoryAuditLogger()
    queue = SQLiteSendRequestQueue(tmp_path / "send_queue.sqlite3", audit)
    now = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    send_request = _send_request(
        request_id="req_claim_worker",
        dedupe_key="dedupe-claim-worker",
    )
    queue.submit(send_request, now=now)

    async def transport(_send_request: SendRequest) -> DeliveryReceipt:
        assert queue.list_due(now=now, limit=5) == []
        assert queue.safe_summary()["processing"] == 1
        return DeliveryReceipt(
            request_id=_send_request.request_id,
            state=ReceiptState.SENT,
            transport="fake_transport",
            public_message="fake sent",
        )

    result = await drain_send_queue_once(
        queue,
        transport,
        audit_logger=audit,
        now=now,
        limit=5,
    )

    assert result.checked == 1
    assert result.delivered == 1
    assert queue.safe_summary()["processing"] == 0
    assert queue.safe_summary()["sent"] == 1


@pytest.mark.asyncio
async def test_send_queue_worker_turns_blocked_transport_result_into_final_failure(tmp_path):
    from plugins.bot_unified_runtime.sender import drain_send_queue_once

    audit = InMemoryAuditLogger()
    queue = SQLiteSendRequestQueue(tmp_path / "send_queue.sqlite3", audit)
    now = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    send_request = _send_request(
        request_id="req_blocked",
        dedupe_key="dedupe-blocked",
        target_id="secret-target",
    )
    queue.submit(send_request, now=now)

    async def transport(_send_request: SendRequest) -> DeliveryReceipt:
        return DeliveryReceipt(
            request_id=_send_request.request_id,
            state=ReceiptState.BLOCKED,
            transport="fake_transport",
            public_message="unsupported target type",
        )

    result = await drain_send_queue_once(
        queue,
        transport,
        audit_logger=audit,
        now=now,
        limit=5,
    )

    summary = queue.safe_summary()
    rendered_result = repr(result.model_dump())

    assert result.checked == 1
    assert result.final_failed == 1
    assert summary["queued"] == 0
    assert summary["failed_final"] == 1
    assert queue.list_due(now=now + timedelta(days=1), limit=5) == []
    assert "secret-target" not in rendered_result
    assert "不应出现在" not in rendered_result
    assert [record.event for record in audit.list_records("req_blocked")] == [
        "queued",
        "send_failed_final",
        "queue_worker_final_failure",
    ]

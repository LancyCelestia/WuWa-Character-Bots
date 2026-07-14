from __future__ import annotations

from datetime import UTC, datetime, timedelta

from plugins.wuwa_unified_runtime.audit import InMemoryAuditLogger
from plugins.wuwa_unified_runtime.config import Config
from plugins.wuwa_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.wuwa_unified_runtime.sender import (
    InMemorySendQueue,
    SQLiteSendRequestQueue,
    build_send_queue,
)


def _send_request(
    *,
    request_id: str = "req_queue_1",
    dedupe_key: str = "wuwa.chat:private:42:hello",
    target_id: str = "42",
    text: str = "你好，漂泊者。",
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
        origin_message_id="origin_1",
        capability_id="wuwa.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key=f"wuwa.chat:private:{target_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="shorekeeper",
        audit_tags=["policy", "persona:shorekeeper"],
    )


def test_sqlite_send_queue_persists_due_requests_and_dedupes(tmp_path):
    audit = InMemoryAuditLogger()
    now = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    db_path = tmp_path / "send_queue.sqlite3"
    queue = SQLiteSendRequestQueue(db_path, audit_logger=audit, max_items=10)
    send_request = _send_request(target_id="secret-target")

    first_receipt = queue.submit(send_request, now=now)
    duplicate_receipt = queue.submit(send_request, now=now + timedelta(seconds=1))
    reopened = SQLiteSendRequestQueue(db_path, audit_logger=audit, max_items=10)
    due = reopened.list_due(now=now, limit=5)

    assert first_receipt.state is ReceiptState.QUEUED
    assert first_receipt.transport == "sqlite_queue"
    assert duplicate_receipt.state is ReceiptState.SKIPPED
    assert duplicate_receipt.public_message == "duplicate dedupe_key"
    assert [entry.send_request.request_id for entry in due] == [send_request.request_id]
    assert due[0].send_request.target_id == "secret-target"
    assert due[0].retry_count == 0
    assert [record.event for record in audit.list_records(send_request.request_id)] == [
        "queued",
        "skipped_duplicate",
    ]
    assert "secret-target" not in first_receipt.public_message
    assert "secret-target" not in duplicate_receipt.public_message


def test_sqlite_send_queue_finds_request_after_reopen(tmp_path):
    audit = InMemoryAuditLogger()
    db_path = tmp_path / "send_queue.sqlite3"
    queue = SQLiteSendRequestQueue(db_path, audit_logger=audit, max_items=10)
    send_request = _send_request(
        request_id="req_find_after_reopen",
        dedupe_key="dedupe-find-after-reopen",
        target_id="secret-target",
    )
    queue.submit(send_request)

    reopened = SQLiteSendRequestQueue(db_path, audit_logger=audit, max_items=10)
    found = reopened.find_request("req_find_after_reopen")

    assert found is not None
    assert found.request_id == "req_find_after_reopen"
    assert found.target_id == "secret-target"
    assert reopened.find_request("missing") is None


def test_sqlite_send_queue_retries_with_backoff_and_final_failure(tmp_path):
    audit = InMemoryAuditLogger()
    now = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    queue = SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3",
        audit_logger=audit,
        max_items=10,
        max_attempts=2,
        retry_base_seconds=10,
        retry_max_seconds=60,
    )
    send_request = _send_request()
    queue.submit(send_request, now=now)

    retryable = queue.mark_retryable_failure(
        send_request.request_id,
        "OneBot V11 发送失败，debug_id=dbg_retry",
        now=now,
    )
    before_retry = queue.list_due(now=now + timedelta(seconds=9), limit=5)
    at_retry = queue.list_due(now=now + timedelta(seconds=10), limit=5)
    final = queue.mark_retryable_failure(
        send_request.request_id,
        "OneBot V11 发送失败，debug_id=dbg_final",
        now=now + timedelta(seconds=10),
    )

    assert retryable.state is ReceiptState.FAILED_RETRYABLE
    assert retryable.retry_count == 1
    assert retryable.next_retry_at == now + timedelta(seconds=10)
    assert before_retry == []
    assert [entry.send_request.request_id for entry in at_retry] == [
        send_request.request_id
    ]
    assert at_retry[0].retry_count == 1
    assert final.state is ReceiptState.FAILED_FINAL
    assert final.retry_count == 2
    assert final.next_retry_at is None
    assert queue.list_due(now=now + timedelta(minutes=10), limit=5) == []
    assert [record.event for record in audit.list_records(send_request.request_id)] == [
        "queued",
        "send_failed_retryable",
        "send_failed_final",
    ]


def test_sqlite_send_queue_claims_due_requests_with_lease(tmp_path):
    audit = InMemoryAuditLogger()
    now = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    queue = SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3",
        audit_logger=audit,
        max_items=10,
    )
    first = _send_request(request_id="req_claim_1", dedupe_key="dedupe-claim-1")
    second = _send_request(request_id="req_claim_2", dedupe_key="dedupe-claim-2")
    queue.submit(first, now=now)
    queue.submit(second, now=now + timedelta(seconds=1))

    claimed = queue.claim_due(
        now=now + timedelta(seconds=2),
        limit=1,
        lease_seconds=30,
    )
    claimed_again = queue.claim_due(
        now=now + timedelta(seconds=3),
        limit=5,
        lease_seconds=30,
    )
    after_lease = queue.claim_due(
        now=now + timedelta(seconds=33),
        limit=5,
        lease_seconds=30,
    )

    assert [entry.send_request.request_id for entry in claimed] == ["req_claim_1"]
    assert claimed[0].state is ReceiptState.QUEUED
    assert [entry.send_request.request_id for entry in claimed_again] == ["req_claim_2"]
    assert queue.safe_summary()["processing"] == 2
    assert [entry.send_request.request_id for entry in after_lease] == [
        "req_claim_1",
        "req_claim_2",
    ]
    assert queue.safe_summary()["processing"] == 2


def test_sqlite_send_queue_claimed_request_is_released_after_retryable_failure(tmp_path):
    audit = InMemoryAuditLogger()
    now = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    queue = SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3",
        audit_logger=audit,
        max_items=10,
        max_attempts=3,
        retry_base_seconds=10,
        retry_max_seconds=60,
    )
    send_request = _send_request(request_id="req_claim_retry", dedupe_key="dedupe-claim-retry")
    queue.submit(send_request, now=now)
    claimed = queue.claim_due(now=now, limit=1, lease_seconds=30)

    retryable = queue.mark_retryable_failure(
        send_request.request_id,
        "OneBot V11 发送失败，debug_id=dbg_retry",
        now=now,
    )

    assert [entry.send_request.request_id for entry in claimed] == [
        "req_claim_retry"
    ]
    assert retryable.state is ReceiptState.FAILED_RETRYABLE
    assert queue.safe_summary()["processing"] == 0
    assert queue.list_due(now=now + timedelta(seconds=9), limit=5) == []
    assert [entry.send_request.request_id for entry in queue.list_due(now=now + timedelta(seconds=10), limit=5)] == [
        "req_claim_retry"
    ]


def test_sqlite_send_queue_safe_summary_hides_targets_and_payloads(tmp_path):
    audit = InMemoryAuditLogger()
    queue = SQLiteSendRequestQueue(
        tmp_path / "send_queue.sqlite3",
        audit_logger=audit,
        max_items=10,
    )
    queue.submit(
        _send_request(
            target_id="123456789",
            text="这是一段不应出现在摘要里的私聊正文。",
        )
    )

    summary = queue.safe_summary()
    rendered_summary = repr(summary)

    assert summary["queued"] == 1
    assert summary["processing"] == 0
    assert summary["failed_retryable"] == 0
    assert summary["failed_final"] == 0
    assert "123456789" not in rendered_summary
    assert "私聊正文" not in rendered_summary
    assert "shorekeeper" not in rendered_summary


def test_build_send_queue_uses_sqlite_only_when_enabled(tmp_path):
    audit = InMemoryAuditLogger()
    sqlite_queue = build_send_queue(
        Config(
            wuwa_send_queue_enabled=True,
            wuwa_send_queue_db_path=str(tmp_path / "send_queue.sqlite3"),
            wuwa_send_queue_max_items=9,
            wuwa_send_queue_max_attempts=4,
            wuwa_send_queue_retry_base_seconds=7,
            wuwa_send_queue_retry_max_seconds=70,
        ),
        audit_logger=audit,
    )
    memory_queue = build_send_queue(Config(wuwa_send_queue_enabled=False), audit)

    assert isinstance(sqlite_queue, SQLiteSendRequestQueue)
    assert sqlite_queue.max_items == 9
    assert sqlite_queue.max_attempts == 4
    assert sqlite_queue.retry_base_seconds == 7
    assert sqlite_queue.retry_max_seconds == 70
    assert isinstance(memory_queue, InMemorySendQueue)

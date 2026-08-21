from __future__ import annotations

from datetime import UTC, datetime

from plugins.bot_unified_runtime.audit import (
    InMemoryAuditLogger,
    SQLiteAuditRepository,
    build_audit_repository,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    ReceiptState,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.runtime import RuntimePipeline
from plugins.bot_unified_runtime.sender import (
    InMemorySendQueue,
    SQLiteReceiptRepository,
    build_receipt_repository,
)


def _audit_record(
    *,
    request_id: str,
    event: str = "sent",
    private_debug: str = "token=raw-token cookie=raw-cookie",
) -> AuditRecord:
    return AuditRecord(
        request_id=request_id,
        session_id="private:42",
        capability_id="bot.chat",
        stage="sender",
        event=event,
        severity=RiskLevel.LOW,
        public_message="sent",
        private_debug=private_debug,
        created_at=datetime.now(UTC),
    )


def _message(text: str = "你好") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="bot-1",
        session_id="private:42",
        session_type=SessionType.PRIVATE,
        sender_id="42",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=True,
    )


def test_sqlite_audit_repository_redacts_persists_filters_and_prunes(tmp_path):
    db_path = tmp_path / "nested" / "audit.sqlite3"
    repository = SQLiteAuditRepository(db_path, max_items=2)

    first = repository.append(_audit_record(request_id="req_1", event="first"))
    repository.append(_audit_record(request_id="req_2", event="second"))
    third = repository.append(_audit_record(request_id="req_1", event="third"))
    reopened = SQLiteAuditRepository(db_path, max_items=2)

    assert db_path.exists()
    assert "raw-token" not in first.private_debug
    assert "cookie=[redacted]" in first.private_debug
    assert [record.event for record in reopened.list_records()] == ["second", "third"]
    assert reopened.list_records("req_1") == [third]
    assert reopened.list_records("missing") == []
    assert all(record.audit_id != first.audit_id for record in reopened.list_records())


def test_sqlite_audit_repository_redacts_colon_style_secrets(tmp_path):
    repository = SQLiteAuditRepository(tmp_path / "audit.sqlite3")

    stored = repository.append(
        _audit_record(
            request_id="req_colon",
            private_debug="token: raw-token cookie: raw-cookie",
        )
    )

    assert "raw-token" not in stored.private_debug
    assert "raw-cookie" not in stored.private_debug
    assert "token=[redacted]" in stored.private_debug
    assert "cookie=[redacted]" in stored.private_debug


def test_build_audit_repository_uses_sqlite_only_when_enabled(tmp_path):
    sqlite_repository = build_audit_repository(
        Config(
            bot_audit_enabled=True,
            bot_audit_db_path=str(tmp_path / "audit.sqlite3"),
            bot_audit_max_items=7,
        )
    )
    memory_repository = build_audit_repository(Config(bot_audit_enabled=False))

    assert isinstance(sqlite_repository, SQLiteAuditRepository)
    assert sqlite_repository.max_items == 7
    assert isinstance(memory_repository, InMemoryAuditLogger)


def test_sqlite_receipt_repository_persists_finds_and_prunes(tmp_path):
    db_path = tmp_path / "receipts.sqlite3"
    repository = SQLiteReceiptRepository(db_path, max_items=2)
    first = DeliveryReceipt(
        request_id="req_1",
        state=ReceiptState.SENT,
        transport="memory",
        public_message="sent",
        debug_id="debug_1",
    )
    second = DeliveryReceipt(
        request_id="req_2",
        state=ReceiptState.FAILED_RETRYABLE,
        transport="onebot.v11",
        provider_message_id="provider_msg_2",
        public_message="OneBot V11 发送失败，debug_id=debug_2",
        debug_id="debug_2",
    )
    third = DeliveryReceipt(
        request_id="req_3",
        state=ReceiptState.BLOCKED,
        transport="policy",
        public_message="blocked",
        debug_id="debug_3",
    )

    repository.record(first)
    repository.record(second)
    repository.record(third)
    reopened = SQLiteReceiptRepository(db_path, max_items=2)

    assert reopened.find("req_1") is None
    assert reopened.find("debug_2") == second
    assert reopened.latest() == third
    assert reopened.list_receipts() == [second, third]
    assert reopened.list_receipts("req_2") == [second]


def test_build_receipt_repository_uses_sqlite_only_when_enabled(tmp_path):
    sqlite_repository = build_receipt_repository(
        Config(
            bot_receipts_enabled=True,
            bot_receipts_db_path=str(tmp_path / "receipts.sqlite3"),
            bot_receipts_max_items=9,
        )
    )
    memory_repository = build_receipt_repository(Config(bot_receipts_enabled=False))

    assert isinstance(sqlite_repository, SQLiteReceiptRepository)
    assert sqlite_repository.max_items == 9
    assert memory_repository.latest() is None


def test_runtime_pipeline_records_policy_and_sender_receipts(tmp_path):
    audit = InMemoryAuditLogger()
    receipt_repository = SQLiteReceiptRepository(tmp_path / "receipts.sqlite3", max_items=10)
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=audit,
        receipt_repository=receipt_repository,
    )
    passive_group = _message("只是路过").model_copy(
        update={
            "session_id": "group:100",
            "session_type": SessionType.GROUP,
            "mentions_bot": False,
        }
    )

    blocked = pipeline.handle(passive_group, lambda message, decision: None, "bot.chat")
    sent = pipeline.handle(
        _message("你好"),
        lambda message, decision: CapabilityResult(
            request_id=message.request_id,
            capability_id=decision.capability_id,
            kind="text",
            body="我在这里。",
        ),
        "bot.chat",
    )

    assert receipt_repository.find(blocked.debug_id) == blocked
    assert receipt_repository.find(sent.request_id) == sent
    assert [receipt.state for receipt in receipt_repository.list_receipts()] == [
        ReceiptState.BLOCKED,
        ReceiptState.SENT,
    ]

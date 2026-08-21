from __future__ import annotations

import asyncio
from dataclasses import dataclass

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.sender import InMemoryReceiptRepository
from plugins.bot_unified_runtime.sender.queue import (
    InMemorySendQueue,
    SQLiteSendRequestQueue,
)


@dataclass
class FakeScheduler:
    jobs: list[dict[str, object]]

    def __init__(self) -> None:
        self.jobs = []

    def add_job(self, func, trigger: str, **kwargs: object) -> object:
        job = {"func": func, "trigger": trigger, **kwargs}
        self.jobs.append(job)
        return job


def _send_request(request_id: str = "req_scheduler") -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": "scheduler test"},
        text_fallback="scheduler test",
    )
    return SendRequest(
        request_id=request_id,
        session_id="private:42",
        target_scope=SessionType.PRIVATE,
        target_id="42",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=f"dedupe:{request_id}",
        cooldown_key="bot.chat:private:42",
        privacy_level=rendered.privacy_level,
        persona_profile_id="shorekeeper",
    )


class FakeBot:
    async def send_private_msg(self, **_kwargs: object) -> dict[str, int]:
        return {"message_id": 123}


def test_send_queue_scheduler_is_disabled_by_default(tmp_path):
    from plugins.bot_unified_runtime import _register_send_queue_scheduler

    audit = InMemoryAuditLogger()
    scheduler = FakeScheduler()
    queue = SQLiteSendRequestQueue(tmp_path / "queue.sqlite3", audit)

    result = _register_send_queue_scheduler(
        scheduler=scheduler,
        config=Config(),
        send_queue=queue,
        audit_logger=audit,
        receipt_repository=InMemoryReceiptRepository(),
        bot_provider=lambda: FakeBot(),
    )

    assert result["registered"] is False
    assert result["reason"] == "disabled"
    assert scheduler.jobs == []


def test_send_queue_scheduler_requires_drainable_sqlite_queue():
    from plugins.bot_unified_runtime import _register_send_queue_scheduler

    audit = InMemoryAuditLogger()
    scheduler = FakeScheduler()
    queue = InMemorySendQueue(audit_logger=audit)

    result = _register_send_queue_scheduler(
        scheduler=scheduler,
        config=Config(bot_send_queue_worker_enabled=True),
        send_queue=queue,
        audit_logger=audit,
        receipt_repository=InMemoryReceiptRepository(),
        bot_provider=lambda: FakeBot(),
    )

    assert result["registered"] is False
    assert result["reason"] == "queue_not_drainable"
    assert scheduler.jobs == []


def test_send_queue_scheduler_registers_interval_job_and_drains_queue(tmp_path):
    from plugins.bot_unified_runtime import _register_send_queue_scheduler

    audit = InMemoryAuditLogger()
    receipts = InMemoryReceiptRepository()
    scheduler = FakeScheduler()
    queue = SQLiteSendRequestQueue(tmp_path / "queue.sqlite3", audit)
    queue.submit(_send_request())

    result = _register_send_queue_scheduler(
        scheduler=scheduler,
        config=Config(
            bot_send_queue_worker_enabled=True,
            bot_send_queue_worker_interval_seconds=7,
            bot_send_queue_worker_batch_size=3,
        ),
        send_queue=queue,
        audit_logger=audit,
        receipt_repository=receipts,
        bot_provider=lambda: FakeBot(),
    )

    assert result == {
        "registered": True,
        "reason": "registered",
        "interval_seconds": 7,
        "batch_size": 3,
    }
    assert len(scheduler.jobs) == 1
    [job] = scheduler.jobs
    assert job["trigger"] == "interval"
    assert job["seconds"] == 7
    assert job["id"] == "bot_send_queue_worker"
    assert job["max_instances"] == 1
    assert job["coalesce"] is True

    asyncio.run(job["func"]())

    assert queue.safe_summary()["sent"] == 1
    assert receipts.latest("req_scheduler").state is ReceiptState.SENT
    assert any(
        record.event == "queue_worker_sent"
        for record in audit.list_records("req_scheduler")
    )


def test_send_queue_scheduler_job_is_safe_when_no_bot_is_online(tmp_path):
    from plugins.bot_unified_runtime import _register_send_queue_scheduler

    audit = InMemoryAuditLogger()
    scheduler = FakeScheduler()
    queue = SQLiteSendRequestQueue(tmp_path / "queue.sqlite3", audit)
    queue.submit(_send_request("req_no_bot"))

    _register_send_queue_scheduler(
        scheduler=scheduler,
        config=Config(bot_send_queue_worker_enabled=True),
        send_queue=queue,
        audit_logger=audit,
        receipt_repository=InMemoryReceiptRepository(),
        bot_provider=lambda: None,
    )

    asyncio.run(scheduler.jobs[0]["func"]())

    assert queue.safe_summary()["failed_retryable"] == 1
    assert any(
        record.event == "queue_worker_retryable_failure"
        for record in audit.list_records("req_no_bot")
    )

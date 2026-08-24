from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from plugins.bot_unified_runtime.audit import AuditRepository
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    DeliveryReceipt,
    ReceiptState,
    RiskLevel,
    SendRequest,
    new_debug_id,
)
from plugins.bot_unified_runtime.sender.queue import QueuedSendRequest
from plugins.bot_unified_runtime.sender.receipts import ReceiptRepository

SEND_QUEUE_WORKER_TRANSPORT = "send_queue_worker"
SendTransport = Callable[[SendRequest], Awaitable[DeliveryReceipt]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DrainableSendQueue(Protocol):
    def claim_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
        lease_seconds: int = 60,
    ) -> list[QueuedSendRequest]:
        raise NotImplementedError

    def list_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
    ) -> list[QueuedSendRequest]:
        raise NotImplementedError

    def mark_sent(
        self,
        request_id: str,
        public_message: str = "sent",
        *,
        now: datetime | None = None,
    ) -> DeliveryReceipt:
        raise NotImplementedError

    def mark_retryable_failure(
        self,
        request_id: str,
        public_message: str,
        *,
        now: datetime | None = None,
    ) -> DeliveryReceipt:
        raise NotImplementedError

    def mark_final_failure(
        self,
        request_id: str,
        public_message: str,
        *,
        now: datetime | None = None,
    ) -> DeliveryReceipt:
        raise NotImplementedError


class SendQueueWorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checked: int = 0
    delivered: int = 0
    retryable_failed: int = 0
    final_failed: int = 0
    skipped: int = 0
    receipt_record_failed: int = 0


async def drain_send_queue_once(
    send_queue: DrainableSendQueue,
    transport: SendTransport,
    *,
    receipt_repository: ReceiptRepository | None = None,
    audit_logger: AuditRepository | None = None,
    now: datetime | None = None,
    limit: int = 20,
) -> SendQueueWorkerResult:
    current_time = now or _utc_now()
    entries = _claim_or_list_due(send_queue, now=current_time, limit=limit)
    counters = {
        "checked": len(entries),
        "delivered": 0,
        "retryable_failed": 0,
        "final_failed": 0,
        "skipped": 0,
        "receipt_record_failed": 0,
    }

    for entry in entries:
        receipt = await _call_transport_safely(entry.send_request, transport)
        if receipt_repository is not None:
            try:
                receipt_repository.record(receipt)
            except Exception as exc:  # noqa: BLE001 - sending already happened.
                counters["receipt_record_failed"] += 1
                _append_worker_audit_safely(
                    audit_logger,
                    entry.send_request,
                    event="queue_worker_receipt_record_failed",
                    receipt=receipt,
                    private_debug=f"{type(exc).__name__}: {exc}",
                )

        queue_receipt = _update_queue_state(
            send_queue,
            entry.send_request,
            receipt,
            now=current_time,
        )
        if queue_receipt.state is ReceiptState.SENT:
            counters["delivered"] += 1
            event = "queue_worker_sent"
        elif queue_receipt.state is ReceiptState.FAILED_RETRYABLE:
            counters["retryable_failed"] += 1
            event = "queue_worker_retryable_failure"
        elif queue_receipt.state is ReceiptState.SKIPPED:
            counters["skipped"] += 1
            event = "queue_worker_skipped"
        else:
            counters["final_failed"] += 1
            event = "queue_worker_final_failure"
        _append_worker_audit_safely(
            audit_logger,
            entry.send_request,
            event=event,
            receipt=receipt,
        )

    return SendQueueWorkerResult(**counters)


def _claim_or_list_due(
    send_queue: DrainableSendQueue,
    *,
    now: datetime,
    limit: int,
) -> list[QueuedSendRequest]:
    claim_due = getattr(send_queue, "claim_due", None)
    if callable(claim_due):
        return claim_due(now=now, limit=limit)
    return send_queue.list_due(now=now, limit=limit)


async def _call_transport_safely(
    send_request: SendRequest,
    transport: SendTransport,
) -> DeliveryReceipt:
    try:
        return await transport(send_request)
    except Exception:  # noqa: BLE001 - 传输异常统一转为可重试失败回执。
        debug_id = new_debug_id()
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport=SEND_QUEUE_WORKER_TRANSPORT,
            public_message=f"发送队列 worker 投递失败，debug_id={debug_id}",
            debug_id=debug_id,
        )


def _update_queue_state(
    send_queue: DrainableSendQueue,
    send_request: SendRequest,
    receipt: DeliveryReceipt,
    *,
    now: datetime,
) -> DeliveryReceipt:
    if receipt.state is ReceiptState.SENT:
        return send_queue.mark_sent(
            send_request.request_id,
            receipt.public_message or "sent",
            now=now,
        )
    if receipt.state is ReceiptState.FAILED_RETRYABLE:
        return send_queue.mark_retryable_failure(
            send_request.request_id,
            receipt.public_message or "failed_retryable",
            now=now,
        )
    if receipt.state is ReceiptState.SKIPPED:
        return send_queue.mark_final_failure(
            send_request.request_id,
            receipt.public_message or "skipped",
            now=now,
        ).model_copy(update={"state": ReceiptState.SKIPPED})
    return send_queue.mark_final_failure(
        send_request.request_id,
        receipt.public_message or receipt.state.value,
        now=now,
    )


def _append_worker_audit_safely(
    audit_logger: AuditRepository | None,
    send_request: SendRequest,
    *,
    event: str,
    receipt: DeliveryReceipt,
    private_debug: str | None = None,
) -> None:
    if audit_logger is None:
        return
    debug = private_debug or _safe_worker_debug(receipt)
    try:
        audit_logger.append(
            AuditRecord(
                request_id=send_request.request_id,
                session_id=send_request.session_id,
                capability_id=send_request.capability_id,
                stage="sender",
                event=event,
                severity=send_request.content.risk_level or RiskLevel.LOW,
                public_message=receipt.public_message,
                private_debug=debug,
            )
        )
    except Exception:  # noqa: BLE001 - 审计写入失败时静默跳过，不阻断发送。
        return


def _safe_worker_debug(receipt: DeliveryReceipt) -> str:
    provider_state = " provider_message_id=[internal]" if receipt.provider_message_id else ""
    return (
        f"transport={receipt.transport} "
        f"state={receipt.state.value} "
        f"retry_count={receipt.retry_count}"
        f"{provider_state}"
    )


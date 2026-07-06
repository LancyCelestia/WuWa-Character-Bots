from __future__ import annotations

from plugins.wuwa_unified_runtime.contracts import DeliveryReceipt, ReceiptState, SendRequest


def sent_receipt(send_request: SendRequest) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SENT,
        transport="memory",
        public_message="sent",
    )


def skipped_receipt(send_request: SendRequest, reason: str) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SKIPPED,
        transport="memory",
        public_message=reason,
    )


def blocked_receipt(send_request: SendRequest, reason: str) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.BLOCKED,
        transport="blocked",
        public_message=reason,
    )

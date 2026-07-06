from __future__ import annotations

from plugins.wuwa_unified_runtime.audit import AuditRepository
from plugins.wuwa_unified_runtime.contracts import AuditRecord, DeliveryReceipt, ReceiptState, SendRequest
from plugins.wuwa_unified_runtime.sender.receipts import skipped_receipt, sent_receipt


class InMemorySendQueue:
    def __init__(self, audit_logger: AuditRepository) -> None:
        self.audit_logger = audit_logger
        self.sent_requests: list[SendRequest] = []
        self._dedupe_keys: set[str] = set()

    def submit(self, send_request: SendRequest) -> DeliveryReceipt:
        if send_request.dedupe_key in self._dedupe_keys:
            receipt = skipped_receipt(send_request, "duplicate dedupe_key")
            event = "skipped_duplicate"
        else:
            self._dedupe_keys.add(send_request.dedupe_key)
            self.sent_requests.append(send_request)
            receipt = sent_receipt(send_request)
            event = "sent"

        self.audit_logger.append(
            AuditRecord(
                request_id=send_request.request_id,
                session_id=send_request.session_id,
                capability_id=send_request.capability_id,
                stage="sender",
                event=event,
                severity=send_request.content.risk_level,
                public_message=receipt.public_message,
                private_debug=f"transport={receipt.transport} state={receipt.state.value}",
            )
        )
        return receipt

from __future__ import annotations

from collections.abc import Callable

from plugins.wuwa_unified_runtime.audit import AuditRepository, redact_private_debug
from plugins.wuwa_unified_runtime.contracts import (
    AuditRecord,
    BotDecision,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    PrivacyLevel,
    ReceiptState,
    RiskLevel,
    SendPolicy,
    SendRequest,
)
from plugins.wuwa_unified_runtime.output import render_reviewed_output, review_capability_result
from plugins.wuwa_unified_runtime.policy import evaluate_policy
from plugins.wuwa_unified_runtime.sender import InMemorySendQueue

CapabilityCallable = Callable[[IncomingMessage, BotDecision], CapabilityResult]


class RuntimePipeline:
    def __init__(
        self,
        send_queue: InMemorySendQueue,
        audit_logger: AuditRepository,
    ) -> None:
        self.send_queue = send_queue
        self.audit_logger = audit_logger
        self.policy_evaluator = evaluate_policy

    def _append_audit_safely(self, record: AuditRecord) -> None:
        try:
            self.audit_logger.append(record)
        except Exception:
            return

    def handle(
        self,
        message: IncomingMessage,
        capability: CapabilityCallable,
        capability_id: str = "wuwa.status",
    ) -> DeliveryReceipt:
        try:
            policy = self.policy_evaluator(message, capability_id)
            if not policy.allowed:
                receipt = DeliveryReceipt(
                    request_id=message.request_id,
                    state=ReceiptState.BLOCKED,
                    transport="policy",
                    public_message="该场景下未启用主动回复。",
                    debug_id=policy.debug_id,
                )
                self._append_audit_safely(
                    AuditRecord(
                        request_id=message.request_id,
                        session_id=message.session_id,
                        capability_id=capability_id,
                        stage="policy",
                        event="policy_denied",
                        severity=policy.risk_level,
                        public_message=receipt.public_message,
                        private_debug=policy.reason,
                    )
                )
                return receipt

            decision = BotDecision(
                request_id=message.request_id,
                should_respond=True,
                mode="command",
                trigger=message.plain_text.strip() or "message",
                capability_id=capability_id,
                target_scope=message.session_type,
                max_messages=1,
                send_policy=SendPolicy.IMMEDIATE,
                persona_profile_id="default",
                context_budget=2048,
                decision_reason=policy.reason,
                risk_level=policy.risk_level,
                privacy_level=policy.privacy_level,
                audit_tags=policy.audit_tags,
            )
            result = capability(message, decision)
            review = review_capability_result(result, decision)
            if not review.approved:
                receipt = DeliveryReceipt(
                    request_id=message.request_id,
                    state=ReceiptState.BLOCKED,
                    transport="reviewer",
                    public_message="输出未通过安全或隐私检查。",
                    debug_id=review.debug_id,
                )
                self._append_audit_safely(
                    AuditRecord(
                        request_id=message.request_id,
                        session_id=message.session_id,
                        capability_id=decision.capability_id,
                        stage="review",
                        event=review.action.value,
                        severity=review.risk_level,
                        public_message=receipt.public_message,
                        private_debug="; ".join(review.reasons),
                    )
                )
                return receipt

            rendered = render_reviewed_output(result, review)
            if decision.target_scope.value == "group" and not message.group_id:
                receipt = DeliveryReceipt(
                    request_id=message.request_id,
                    state=ReceiptState.BLOCKED,
                    transport="runtime",
                    public_message="群消息缺少 group_id，已阻断发送。",
                    debug_id=message.debug_id,
                )
                self._append_audit_safely(
                    AuditRecord(
                        request_id=message.request_id,
                        session_id=message.session_id,
                        capability_id=decision.capability_id,
                        stage="runtime",
                        event="missing_group_id",
                        severity=RiskLevel.MEDIUM,
                        public_message=receipt.public_message,
                        private_debug="target_scope=group but IncomingMessage.group_id is empty",
                    )
                )
                return receipt
            send_request = SendRequest(
                request_id=message.request_id,
                session_id=message.session_id,
                target_scope=decision.target_scope,
                target_id=message.group_id or message.sender_id,
                origin_message_id=message.message_id,
                capability_id=decision.capability_id,
                content=rendered,
                send_policy=decision.send_policy,
                priority="normal",
                max_messages=decision.max_messages,
                dedupe_key=f"{decision.capability_id}:{message.session_id}:{rendered.text_fallback}",
                cooldown_key=policy.cooldown_key,
                expires_at=None,
                privacy_level=review.privacy_level,
                allow_split=False,
                allow_forward=review.privacy_level is PrivacyLevel.PUBLIC,
                persona_profile_id=decision.persona_profile_id,
                audit_tags=decision.audit_tags,
            )
            return self.send_queue.submit(send_request)
        except Exception as exc:  # pragma: no cover - exercised by integration tests later.
            debug_id = message.debug_id
            public_message = f"运行时内部错误，debug_id={debug_id}"
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=capability_id,
                    stage="runtime",
                    event="internal_error",
                    severity=RiskLevel.HIGH,
                    public_message=public_message,
                    private_debug=redact_private_debug(repr(exc)),
                )
            )
            return DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.FAILED_FINAL,
                transport="runtime",
                public_message=public_message,
                debug_id=debug_id,
            )

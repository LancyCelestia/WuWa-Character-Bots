from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from plugins.wuwa_unified_runtime.audit import AuditRepository, redact_private_debug
from plugins.wuwa_unified_runtime.contracts import (
    AuditRecord,
    BotDecision,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    PrivacyLevel,
    PolicyEvaluation,
    ReceiptState,
    ReviewResult,
    RiskLevel,
    SendPolicy,
    SendRequest,
)
from plugins.wuwa_unified_runtime.output import (
    build_forward_output,
    render_reviewed_output,
    review_capability_result,
    should_forward_long_text,
)
from plugins.wuwa_unified_runtime.policy import (
    InMemoryRateLimiter,
    PolicySettings,
    QuietHoursChecker,
    RateLimiter,
    ReplyBudgetSettings,
    RoleSettings,
    decide_reply_budget,
    evaluate_policy,
)
from plugins.wuwa_unified_runtime.sender import (
    InMemoryReceiptRepository,
    ReceiptRepository,
    SendQueue,
)

CapabilityCallable = Callable[[IncomingMessage, BotDecision], CapabilityResult]
AsyncCapabilityCallable = Callable[
    [IncomingMessage, BotDecision], Awaitable[CapabilityResult]
]


def offload_capability(capability: CapabilityCallable) -> AsyncCapabilityCallable:
    async def wrapped(
        message: IncomingMessage,
        decision: BotDecision,
    ) -> CapabilityResult:
        return await asyncio.to_thread(capability, message, decision)

    return wrapped

RUNTIME_CONTROL_BYPASS_CAPABILITY_IDS = {
    "wuwa.status",
    "wuwa.help",
    "wuwa.why",
    "wuwa.receipt",
    "wuwa.audit",
    "wuwa.recent",
    "wuwa.queue",
    "wuwa.context",
    "wuwa.llm",
    "wuwa.setup.llm",
    "wuwa.config",
    "wuwa.readiness",
    "wuwa.dialogue",
    "wuwa.roles",
    "wuwa.history",
    "wuwa.control",
}


@dataclass
class RuntimeControlState:
    paused: bool = False
    reason: str = "running"
    updated_by_state: str = "missing"

    def pause(self, *, actor_id: str = "", reason: str = "manual_pause") -> None:
        self.paused = True
        self.reason = reason
        self.updated_by_state = "set" if actor_id else "missing"

    def resume(self, *, actor_id: str = "", reason: str = "manual_resume") -> None:
        self.paused = False
        self.reason = reason
        self.updated_by_state = "set" if actor_id else "missing"

    def allows(self, capability_id: str) -> bool:
        return not self.paused or capability_id in RUNTIME_CONTROL_BYPASS_CAPABILITY_IDS


@dataclass(frozen=True)
class _PreparedRuntime:
    message: IncomingMessage
    decision: BotDecision
    policy: PolicyEvaluation


def _resolve_persona_profile_id(
    decision: BotDecision,
    result: CapabilityResult,
) -> str:
    for tag in result.audit_tags:
        if tag.startswith("persona:"):
            persona_id = tag.removeprefix("persona:").strip()
            if persona_id:
                return persona_id
    return decision.persona_profile_id


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result


def _looks_like_review_reason(review: ReviewResult, marker: str) -> bool:
    normalized_marker = marker.lower()
    return any(normalized_marker in reason.lower() for reason in review.reasons)


def _persona_display_name(result: CapabilityResult) -> str:
    title = result.title.strip()
    suffix = "的回复"
    if title.endswith(suffix):
        name = title[: -len(suffix)].strip()
        if name:
            return name
    return "已设定的人格"


def _review_block_public_message(
    result: CapabilityResult,
    review: ReviewResult,
) -> str:
    if _looks_like_review_reason(review, "unsafe output leakage"):
        return "输出未通过安全或隐私检查。"
    if _looks_like_review_reason(review, "persona drift"):
        persona_name = _persona_display_name(result)
        return (
            "我刚刚没有把话说稳。"
            f"让我回到{persona_name}的位置上："
            "你可以把问题再说一遍，我会按既定人格、记忆和知识库重新回答。"
        )
    return "输出未通过安全或隐私检查。"


def _rate_limit_public_message(reason: str) -> str:
    if reason == "target_min_interval":
        return "当前目标回复间隔过短，已临时降频。"
    if reason == "global_window_exceeded":
        return "当前机器人整体回复过于频繁，已临时降频。"
    return "当前会话回复过于频繁，已临时降频。"


class RuntimePipeline:
    def __init__(
        self,
        send_queue: SendQueue,
        audit_logger: AuditRepository,
        reply_budget_settings: ReplyBudgetSettings | None = None,
        role_settings: RoleSettings | None = None,
        group_command_prefix: str = "/wuwa",
        runtime_enabled: bool = True,
        receipt_repository: ReceiptRepository | None = None,
        rate_limiter: RateLimiter | None = None,
        quiet_hours_checker: QuietHoursChecker | None = None,
        runtime_control: RuntimeControlState | None = None,
        forward_min_chars: int = 1500,
        forward_max_nodes: int = 6,
        forward_node_chars: int = 900,
    ) -> None:
        self.send_queue = send_queue
        self.audit_logger = audit_logger
        self.receipt_repository = receipt_repository or InMemoryReceiptRepository()
        self.runtime_enabled = runtime_enabled
        self.runtime_control = runtime_control or RuntimeControlState()
        self.rate_limiter = rate_limiter or InMemoryRateLimiter()
        self.quiet_hours_checker = quiet_hours_checker or QuietHoursChecker()
        self.forward_min_chars = max(1, int(forward_min_chars))
        self.forward_max_nodes = max(1, int(forward_max_nodes))
        self.forward_node_chars = max(200, int(forward_node_chars))
        policy_settings = PolicySettings(group_command_prefix=group_command_prefix)
        self.policy_evaluator = (
            lambda message, capability_id: evaluate_policy(
                message,
                capability_id,
                settings=policy_settings,
            )
        )
        self.reply_budget_settings = reply_budget_settings
        self.role_settings = role_settings

    def _append_audit_safely(self, record: AuditRecord) -> None:
        try:
            self.audit_logger.append(record)
        except Exception:
            return

    def _record_receipt_safely(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        try:
            return self.receipt_repository.record(receipt)
        except Exception:
            return receipt

    def _prepare(
        self,
        message: IncomingMessage,
        capability_id: str,
    ) -> _PreparedRuntime | DeliveryReceipt:
        if not self.runtime_enabled:
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="policy",
                public_message="统一运行时已暂停。",
                debug_id=message.debug_id,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=capability_id,
                    stage="policy",
                    event="runtime_disabled",
                    severity=RiskLevel.MEDIUM,
                    public_message=receipt.public_message,
                    private_debug="wuwa_runtime_enabled=false",
                )
            )
            return self._record_receipt_safely(receipt)
        if self.role_settings is not None:
            message = message.model_copy(
                update={"sender_roles": self.role_settings.resolve_roles(message)}
            )
        if not self.runtime_control.allows(capability_id):
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="policy",
                public_message="统一运行时已暂停。",
                debug_id=message.debug_id,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=capability_id,
                    stage="policy",
                    event="runtime_paused",
                    severity=RiskLevel.MEDIUM,
                    public_message=receipt.public_message,
                    private_debug=f"reason={self.runtime_control.reason}",
                )
            )
            return self._record_receipt_safely(receipt)
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
            return self._record_receipt_safely(receipt)

        quiet_hours = self.quiet_hours_checker.check(message, capability_id)
        if not quiet_hours.allowed:
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="policy",
                public_message="当前处于安静时间，已暂停非必要回复。",
                debug_id=quiet_hours.debug_id,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=capability_id,
                    stage="policy",
                    event="quiet_hours_blocked",
                    severity=RiskLevel.LOW,
                    public_message=receipt.public_message,
                    private_debug=(
                        f"reason={quiet_hours.reason}; "
                        f"audit_tags={','.join(quiet_hours.audit_tags)}"
                    ),
                )
            )
            return self._record_receipt_safely(receipt)

        reply_budget = decide_reply_budget(
            message,
            capability_id,
            settings=self.reply_budget_settings,
        )
        rate_limit = self.rate_limiter.check_and_record(
            message,
            capability_id,
            amount=reply_budget.max_messages,
        )
        if not rate_limit.allowed:
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="policy",
                public_message=_rate_limit_public_message(rate_limit.reason),
                debug_id=rate_limit.debug_id,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=capability_id,
                    stage="policy",
                    event="rate_limited",
                    severity=RiskLevel.MEDIUM,
                    public_message=receipt.public_message,
                    private_debug=(
                        f"reason={rate_limit.reason}; "
                        f"retry_after_seconds={rate_limit.retry_after_seconds}"
                    ),
                )
            )
            return self._record_receipt_safely(receipt)
        decision = BotDecision(
            request_id=message.request_id,
            should_respond=True,
            mode="command",
            trigger=message.plain_text.strip() or "message",
            capability_id=capability_id,
            target_scope=message.session_type,
            max_messages=reply_budget.max_messages,
            send_policy=SendPolicy.IMMEDIATE,
            persona_profile_id="default",
            context_budget=reply_budget.context_budget,
            decision_reason=f"{policy.reason}; {reply_budget.reason}",
            risk_level=policy.risk_level,
            privacy_level=policy.privacy_level,
            actor_roles=policy.actor_roles,
            audit_tags=[
                *policy.audit_tags,
                *reply_budget.audit_tags,
                *rate_limit.audit_tags,
            ],
        )
        return _PreparedRuntime(message=message, decision=decision, policy=policy)

    def _complete(
        self,
        prepared: _PreparedRuntime,
        result: CapabilityResult,
    ) -> DeliveryReceipt:
        message = prepared.message
        decision = prepared.decision
        review = review_capability_result(result, decision)
        if not review.approved:
            public_message = _review_block_public_message(result, review)
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="reviewer",
                public_message=public_message,
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
                    public_message=public_message,
                    private_debug="; ".join(review.reasons),
                )
            )
            return self._record_receipt_safely(receipt)

        rendered = render_reviewed_output(result, review)
        use_forward = False
        if (
            rendered.content_type == "text"
            and should_forward_long_text(
                rendered.text_fallback,
                min_chars=self.forward_min_chars,
            )
        ):
            rendered = build_forward_output(
                message.request_id,
                rendered.text_fallback,
                node_chars=self.forward_node_chars,
                max_nodes=self.forward_max_nodes,
                sender_name=message.sender_display_name or "",
                risk_level=rendered.risk_level,
                privacy_level=rendered.privacy_level,
            )
            use_forward = True
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
            return self._record_receipt_safely(receipt)
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
            dedupe_key=(
                f"{decision.capability_id}:{message.session_id}:"
                f"{rendered.text_fallback}"
            ),
            cooldown_key=prepared.policy.cooldown_key,
            expires_at=None,
            privacy_level=review.privacy_level,
            allow_split=use_forward,
            allow_forward=use_forward or review.privacy_level is PrivacyLevel.PUBLIC,
            persona_profile_id=_resolve_persona_profile_id(decision, result),
            audit_tags=_dedupe_tags([*decision.audit_tags, *result.audit_tags]),
        )
        return self._record_receipt_safely(self.send_queue.submit(send_request))

    def _internal_error(
        self,
        message: IncomingMessage,
        capability_id: str,
        exc: Exception,
    ) -> DeliveryReceipt:
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
        receipt = DeliveryReceipt(
            request_id=message.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport="runtime",
            public_message=public_message,
            debug_id=debug_id,
        )
        return self._record_receipt_safely(receipt)

    def handle(
        self,
        message: IncomingMessage,
        capability: CapabilityCallable,
        capability_id: str = "wuwa.status",
    ) -> DeliveryReceipt:
        try:
            prepared = self._prepare(message, capability_id)
            if isinstance(prepared, DeliveryReceipt):
                return prepared
            return self._complete(
                prepared,
                capability(prepared.message, prepared.decision),
            )
        except Exception as exc:  # pragma: no cover - integration fallback.
            return self._internal_error(message, capability_id, exc)

    async def handle_async(
        self,
        message: IncomingMessage,
        capability: AsyncCapabilityCallable,
        capability_id: str = "wuwa.status",
    ) -> DeliveryReceipt:
        try:
            prepared = self._prepare(message, capability_id)
            if isinstance(prepared, DeliveryReceipt):
                return prepared
            result = await capability(prepared.message, prepared.decision)
            return self._complete(prepared, result)
        except Exception as exc:  # pragma: no cover - integration fallback.
            return self._internal_error(message, capability_id, exc)

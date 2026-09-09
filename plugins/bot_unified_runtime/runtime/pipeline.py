from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import asyncio
import atexit
import os
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from plugins.bot_unified_runtime.audit import AuditRepository, redact_private_debug
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    BotDecision,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    OperationalIssue,
    PolicyEvaluation,
    PrivacyLevel,
    ReceiptState,
    ReviewResult,
    RiskLevel,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.output import (
    build_forward_output,
    render_reviewed_output,
    review_capability_result,
    should_forward_long_text,
)
from plugins.bot_unified_runtime.policy import (
    InMemoryRateLimiter,
    PolicySettings,
    QuietHoursChecker,
    RateLimiter,
    ReplyBudgetSettings,
    RoleSettings,
    decide_reply_budget,
    evaluate_policy,
)
from plugins.bot_unified_runtime.runtime.event_idempotency import (
    EventIdempotencyTable,
    SqliteEventIdempotencyTable,
    build_event_dedupe_key,
)
from plugins.bot_unified_runtime.sender import (
    InMemoryReceiptRepository,
    ReceiptRepository,
    SendQueue,
)

CapabilityCallable = Callable[[IncomingMessage, BotDecision], CapabilityResult]
AsyncCapabilityCallable = Callable[
    [IncomingMessage, BotDecision], Awaitable[CapabilityResult]
]


# ==================== 聊天专用有界线程池（管线检视 #4） ====================
# 聊天能力是长任务（同步 LLM + ffmpeg 抽帧 + ASR + 串行检索，单条最长 150s）。
# 原先经 asyncio.to_thread 挤占默认线程池（min(32, cpu+4)），与语音转码、kb
# 拉取、订阅适配器共享；突发并发打满后所有 to_thread 任务排队，全站延迟
# 分钟级叠加。现改为管线专用有界池：worker 数与等待队列均有界，超限快败
# 返回 busy 结果而非无限排队；默认线程池完全留给管线外的 to_thread 用户，
# 其 shutdown_default_executor 语义不受影响。

_CHAT_POOL_WORKERS_DEFAULT = 8
_CHAT_POOL_WORKERS_MIN = 1
_CHAT_POOL_WORKERS_MAX = 64
_CHAT_POOL_WORKERS_ENV = "BOT_PIPELINE_MAX_WORKERS"


class _BoundedSubmissionGate:
    """有界提交闸：在途（运行+排队）超过许可数时 try_acquire 立即失败。

    只用 threading.Lock 计数，不引入事件循环绑定原语（跨 loop 与测试安全），
    提交路径 O(1) 非阻塞。许可数 = worker 数 + 等待队列深度，即 ThreadPool
    内部队列之外的第二道、也是唯一一道有界闸。
    """

    __slots__ = ("_in_flight", "_lock", "_permits")

    def __init__(self, permits: int) -> None:
        self._lock = threading.Lock()
        self._permits = max(1, int(permits))
        self._in_flight = 0

    def try_acquire(self) -> bool:
        with self._lock:
            if self._in_flight >= self._permits:
                return False
            self._in_flight += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    @property
    def permits(self) -> int:
        return self._permits

    @property
    def in_flight(self) -> int:
        """当前在途（运行+排队）任务数；测试与诊断用。"""
        with self._lock:
            return self._in_flight


_chat_pool_lock = threading.Lock()
_chat_pool: ThreadPoolExecutor | None = None
_chat_pool_gate: _BoundedSubmissionGate | None = None


def _resolve_chat_pool_workers() -> int:
    """worker 数解析链：nonebot driver config → os.environ → 默认 8，钳位 1..64。

    与 llm/channel_health.py 的 config→env→默认同源模式。pipeline 不接收
    注入 config（构造方在插件 __init__，不在本任务文件域），故经惰性
    get_driver 读取；未初始化（单元测试/裸脚本）时自动短路。仅在池首次
    创建时读取一次，运行中改配置需重启（与 .env 注册表语义一致）。
    """
    raw_values: list[object] = []
    try:
        import nonebot

        driver_config = nonebot.get_driver().config
        raw_values.append(getattr(driver_config, "bot_pipeline_max_workers", None))
    except Exception:  # noqa: BLE001, S110 - 单元测试/独立脚本场景，静默落到下一级。
        pass
    raw_values.append(os.environ.get(_CHAT_POOL_WORKERS_ENV))
    for raw in raw_values:
        if raw is None:
            continue
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        return max(_CHAT_POOL_WORKERS_MIN, min(_CHAT_POOL_WORKERS_MAX, value))
    return _CHAT_POOL_WORKERS_DEFAULT


def _shutdown_chat_pool() -> None:
    """模块级关闭钩子：未启动的排队提交取消，已在跑的任务不等待。"""
    global _chat_pool, _chat_pool_gate
    with _chat_pool_lock:
        pool, _chat_pool, _chat_pool_gate = _chat_pool, None, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def _get_chat_pool() -> tuple[ThreadPoolExecutor, _BoundedSubmissionGate]:
    """懒创建管线专用池：worker N（config/env/默认 8），在途上限 2N（N 跑 + N 等）。"""
    global _chat_pool, _chat_pool_gate
    pool, gate = _chat_pool, _chat_pool_gate
    if pool is not None and gate is not None:
        return pool, gate
    with _chat_pool_lock:
        if _chat_pool is None or _chat_pool_gate is None:
            workers = _resolve_chat_pool_workers()
            _chat_pool = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="chat-pipeline",
            )
            atexit.register(_shutdown_chat_pool)
            _chat_pool_gate = _BoundedSubmissionGate(workers * 2)
        return _chat_pool, _chat_pool_gate


def _pipeline_busy_result(
    message: IncomingMessage,
    decision: BotDecision,
) -> CapabilityResult:
    """超限快败结果：SILENT_AUDIT 只留审计痕，不外发话术（超载时不放大流量）。"""
    return CapabilityResult(
        request_id=message.request_id,
        capability_id=decision.capability_id,
        kind="error",
        title="",
        summary="",
        body="",
        send_policy=SendPolicy.SILENT_AUDIT,
        audit_tags=["pipeline_busy:v1"],
        operational_issue=OperationalIssue(
            stage="runtime",
            kind="pipeline_busy",
            retryable=True,
            debug_id=message.debug_id,
            safe_summary="pipeline_busy",
        ),
    )


def offload_capability(capability: CapabilityCallable) -> AsyncCapabilityCallable:
    async def wrapped(
        message: IncomingMessage,
        decision: BotDecision,
    ) -> CapabilityResult:
        pool, gate = _get_chat_pool()
        if not gate.try_acquire():
            return _pipeline_busy_result(message, decision)
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(pool, capability, message, decision)
        finally:
            gate.release()

    return wrapped

RUNTIME_CONTROL_BYPASS_CAPABILITY_IDS = {
    "bot.status",
    "bot.help",
    "bot.why",
    "bot.receipt",
    "bot.audit",
    "bot.recent",
    "bot.queue",
    "bot.context",
    "bot.llm",
    "bot.setup.llm",
    "bot.config",
    "bot.readiness",
    "bot.dialogue",
    "bot.roles",
    "bot.history",
    "bot.control",
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
        group_command_prefix: str = "/bot",
        runtime_enabled: bool = True,
        receipt_repository: ReceiptRepository | None = None,
        rate_limiter: RateLimiter | None = None,
        quiet_hours_checker: QuietHoursChecker | None = None,
        runtime_control: RuntimeControlState | None = None,
        forward_min_chars: int = 1500,
        forward_max_nodes: int = 0,
        forward_node_chars: int = 900,
        alias_command_check: Callable[[str], bool] | None = None,
        group_auto_reply_enabled: bool = False,
        group_auto_reply_probability: float = 0.0,
        vision_reply_probability: float = 1.0,
        group_black1: frozenset[str] = frozenset(),
        group_black2: frozenset[str] = frozenset(),
        group_white1: frozenset[str] = frozenset(),
        group_white2: frozenset[str] = frozenset(),
        natural_chat_check: Callable[[str], bool] | None = None,
        group_lists_provider: Callable[[], dict[str, frozenset[str]]] | None = None,
        idempotency_table: EventIdempotencyTable | SqliteEventIdempotencyTable | None = None,
    ) -> None:
        self.send_queue = send_queue
        self.audit_logger = audit_logger
        self.receipt_repository = receipt_repository or InMemoryReceiptRepository()
        self.runtime_enabled = runtime_enabled
        self.runtime_control = runtime_control or RuntimeControlState()
        self.rate_limiter = rate_limiter or InMemoryRateLimiter()
        self.quiet_hours_checker = quiet_hours_checker or QuietHoursChecker()
        # 0=禁用合并转发（短消息与已分段回复都直接发送）。
        self.forward_min_chars = int(forward_min_chars)
        self.forward_max_nodes = max(0, int(forward_max_nodes))
        self.forward_node_chars = max(200, int(forward_node_chars))
        policy_settings = PolicySettings(
            group_command_prefix=group_command_prefix,
            group_auto_reply_enabled=group_auto_reply_enabled,
            group_auto_reply_probability=group_auto_reply_probability,
            vision_reply_probability=vision_reply_probability,
            group_black1=frozenset(group_black1),
            group_black2=frozenset(group_black2),
            group_white1=frozenset(group_white1),
            group_white2=frozenset(group_white2),
            natural_chat_check=natural_chat_check,
            group_lists_provider=group_lists_provider,
            extra_command_check=alias_command_check,
        )
        self.policy_evaluator = (
            lambda message, capability_id: evaluate_policy(
                message,
                capability_id,
                settings=policy_settings,
            )
        )
        self.reply_budget_settings = reply_budget_settings
        self.role_settings = role_settings
        # 事件幂等表：None=关闭（默认）；启用后同一事件对同一能力只处理一次。
        self.idempotency_table: EventIdempotencyTable | SqliteEventIdempotencyTable | None = (
            idempotency_table
        )

    def _append_audit_safely(self, record: AuditRecord) -> None:
        try:
            self.audit_logger.append(record)
        except Exception:  # noqa: BLE001 - 审计写入失败时静默跳过，不阻断流水线。
            return

    def _record_receipt_safely(
        self,
        receipt: DeliveryReceipt,
        message: IncomingMessage | None = None,
    ) -> DeliveryReceipt:
        is_group_silent_failure = (
            message is not None
            and message.session_type.value == "group"
            and receipt.state
            in {
                ReceiptState.BLOCKED,
                ReceiptState.FAILED_RETRYABLE,
                ReceiptState.FAILED_FINAL,
            }
            and (
                receipt.transport == "runtime"
                or receipt.public_message == "该场景下未启用主动回复。"
            )
        )
        if is_group_silent_failure:
            receipt = receipt.model_copy(update={"public_message": ""})
        try:
            return self.receipt_repository.record(receipt)
        except Exception:  # noqa: BLE001 - 回执持久化失败时返回原始回执降级。
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
                    private_debug="bot_runtime_enabled=false",
                )
            )
            return self._record_receipt_safely(receipt, message)
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
            return self._record_receipt_safely(receipt, message)
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
            return self._record_receipt_safely(receipt, message)

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
            return self._record_receipt_safely(receipt, message)

        reply_budget = decide_reply_budget(
            message,
            capability_id,
            settings=self.reply_budget_settings,
        )
        proactive_request = "proactive_reply:selected" in policy.audit_tags
        interactive_request = (
            not proactive_request
            and (
                (message.session_type.value == "group" and message.mentions_bot)
                or capability_id != "bot.chat"
            )
        )
        rate_limit = self.rate_limiter.check_and_record(
            message,
            capability_id,
            amount=reply_budget.max_messages,
            interactive=interactive_request,
            proactive=proactive_request,
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
            return self._record_receipt_safely(receipt, message)
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
        if (
            result.operational_issue is not None
            and message.session_type in {SessionType.GROUP, SessionType.CHANNEL}
        ):
            result = result.model_copy(
                update={"body": "", "send_policy": SendPolicy.SILENT_AUDIT}
            )
        if result.send_policy is SendPolicy.SILENT_AUDIT:
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.SKIPPED,
                transport="runtime",
                public_message="",
                debug_id=(result.operational_issue.debug_id if result.operational_issue else result.debug_id),
                operational_issue=result.operational_issue,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=decision.capability_id,
                    stage="runtime",
                    event="silent_audit",
                    severity=result.risk_level,
                    public_message="",
                    private_debug="; ".join(result.audit_tags) or "silent_audit",
                )
            )
            return self._record_receipt_safely(receipt, message)
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
            return self._record_receipt_safely(receipt, message)

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
            return self._record_receipt_safely(receipt, message)
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
                f"{message.message_id or message.request_id}"
            ),
            cooldown_key=prepared.policy.cooldown_key,
            expires_at=None,
            privacy_level=review.privacy_level,
            allow_split=use_forward,
            allow_forward=use_forward or review.privacy_level is PrivacyLevel.PUBLIC,
            deadline_monotonic=getattr(result, "deadline_monotonic", None),
            persona_profile_id=_resolve_persona_profile_id(decision, result),
            adapter=message.adapter,
            bot_id=message.bot_id,
            audit_tags=_dedupe_tags([*decision.audit_tags, *result.audit_tags,
                *(["chat_plain_text:v1"] if result.capability_id == "bot.chat" else [])]),
            operational_issue=result.operational_issue,
        )
        return self._record_receipt_safely(self.send_queue.submit(send_request), message)

    def _internal_error(
        self,
        message: IncomingMessage,
        capability_id: str,
        exc: Exception,
    ) -> DeliveryReceipt:
        debug_id = message.debug_id
        issue = OperationalIssue(
            stage="runtime",
            kind="internal_error",
            retryable=False,
            debug_id=debug_id,
            safe_summary="internal_error",
        )
        public_message = ""
        # 可观测性：能力层未预期异常必须留痕（类型+消息摘要+关键栈帧），
        # 否则线上只能看到"internal_error"四个词，无法定位。
        logger.exception(
            "capability internal error capability_id=%s debug_id=%s type=%s detail=%s",
            capability_id,
            debug_id,
            type(exc).__name__,
            redact_private_debug(str(exc)[:300]),
        )
        self._append_audit_safely(
            AuditRecord(
                request_id=message.request_id,
                session_id=message.session_id,
                capability_id=capability_id,
                stage="runtime",
                event="internal_error",
                severity=RiskLevel.HIGH,
                public_message=public_message,
                private_debug=redact_private_debug(
                    f"{type(exc).__name__}: {str(exc)[:200]}"
                ),
            )
        )
        receipt = DeliveryReceipt(
            request_id=message.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport="runtime",
            public_message=public_message,
            debug_id=debug_id,
            operational_issue=issue,
        )
        return self._record_receipt_safely(receipt, message)

    def _duplicate_receipt(
        self,
        message: IncomingMessage,
        capability_id: str,
    ) -> DeliveryReceipt:
        receipt = DeliveryReceipt(
            request_id=message.request_id,
            state=ReceiptState.BLOCKED,
            transport="policy",
            public_message="该事件已处理过，忽略重复投递。",
            debug_id=message.debug_id,
        )
        self._append_audit_safely(
            AuditRecord(
                request_id=message.request_id,
                session_id=message.session_id,
                capability_id=capability_id,
                stage="policy",
                event="duplicate_event",
                severity=RiskLevel.LOW,
                public_message=receipt.public_message,
                private_debug="idempotency=duplicate_drop",
            )
        )
        return self._record_receipt_safely(receipt, message)

    def _claim_event(self, message: IncomingMessage, capability_id: str) -> bool:
        table = self.idempotency_table
        if table is None:
            return True
        key = build_event_dedupe_key(message)
        if not key:
            return True
        try:
            return table.claim(key, capability_id=capability_id)
        except Exception:  # noqa: BLE001 - 幂等表异常时放行，不阻断主链路。
            return True

    def handle(
        self,
        message: IncomingMessage,
        capability: CapabilityCallable,
        capability_id: str = "bot.status",
    ) -> DeliveryReceipt:
        try:
            if not self._claim_event(message, capability_id):
                return self._duplicate_receipt(message, capability_id)
            prepared = self._prepare(message, capability_id)
            if isinstance(prepared, DeliveryReceipt):
                return prepared
            return self._complete(
                prepared,
                capability(prepared.message, prepared.decision),
            )
        except Exception as exc:  # pragma: no cover - integration fallback.  # noqa: BLE001 - 能力调用异常统一转为内部错误回执。
            return self._internal_error(message, capability_id, exc)

    async def handle_async(
        self,
        message: IncomingMessage,
        capability: AsyncCapabilityCallable,
        capability_id: str = "bot.status",
    ) -> DeliveryReceipt:
        try:
            if not self._claim_event(message, capability_id):
                return self._duplicate_receipt(message, capability_id)
            prepared = self._prepare(message, capability_id)
            if isinstance(prepared, DeliveryReceipt):
                return prepared
            result = await capability(prepared.message, prepared.decision)
            return self._complete(prepared, result)
        except Exception as exc:  # pragma: no cover - integration fallback.  # noqa: BLE001 - 能力调用异常统一转为内部错误回执。
            return self._internal_error(message, capability_id, exc)

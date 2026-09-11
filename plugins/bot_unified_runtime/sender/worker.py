from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict

from plugins.bot_unified_runtime.audit import AuditRepository
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    DeliveryReceipt,
    OperationalIssue,
    ReceiptState,
    RiskLevel,
    SendRequest,
    SessionType,
    new_debug_id,
)
from plugins.bot_unified_runtime.sender.queue import (
    PartProgress,
    QueuedSendRequest,
)
from plugins.bot_unified_runtime.sender.receipts import ReceiptRepository

SEND_QUEUE_WORKER_TRANSPORT = "send_queue_worker"
SendTransport = Callable[[SendRequest], Awaitable[DeliveryReceipt]]
# §9.3 UNKNOWN 确认协议：确认器注入点（生产默认 None → 无法确认的 UNKNOWN
# part 永不盲发，停在 PARTIAL 待人工/平台确认）。语义：
#   True  = 平台确认已送达（如 get_msg 命中）→ part 标 SENT，跳过；
#   False = 平台确认未送达 → part 回 PENDING，允许重发一次；
#   None  = 无法确认 → part 保持 UNKNOWN，绝不重发（防重复投递优先）。
UnknownPartConfirmer = Callable[[SendRequest, int], Awaitable[bool | None]]

# create_task 返回的 task 只被事件循环弱引用，无强引用时可能在完成前被 GC。
# 模块级集合持引用，done callback 里移除。
_background_tasks: set[asyncio.Task] = set()


def _spawn_background_task(coro: Awaitable) -> asyncio.Task:
    task: asyncio.Task = asyncio.create_task(coro)  # type: ignore[arg-type]
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


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


class PartStoreQueue(Protocol):
    """§9.3：具备 part 级进度存储的队列（SQLiteSendRequestQueue）。

    worker 经鸭子类型探测该能力；内存队列不实现 → 整条 part 语义自动关闭，
    走既有请求级整发路径。
    """

    max_attempts: int

    def ensure_parts_planned(
        self,
        request_id: str,
        payload_digests: list[str],
        *,
        now: datetime | None = None,
    ) -> PartProgress | None:
        raise NotImplementedError

    def part_progress(self, request_id: str) -> PartProgress | None:
        raise NotImplementedError

    def mark_part_attempt(
        self, request_id: str, part_index: int, *, now: datetime | None = None
    ) -> bool:
        raise NotImplementedError

    def mark_part_sent(
        self,
        request_id: str,
        part_index: int,
        *,
        provider_message_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        raise NotImplementedError

    def mark_part_unknown(
        self,
        request_id: str,
        part_index: int,
        *,
        error_kind: str | None = None,
        provider_message_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        raise NotImplementedError

    def mark_part_failed_final(
        self,
        request_id: str,
        part_index: int,
        *,
        error_kind: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        raise NotImplementedError

    def mark_part_pending(
        self, request_id: str, part_index: int, *, now: datetime | None = None
    ) -> bool:
        raise NotImplementedError

    def mark_partial(
        self,
        request_id: str,
        *,
        resumable: bool = True,
        now: datetime | None = None,
        operational_issue: OperationalIssue | None = None,
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
    # §9.3 part 级观测：本次 pass 内 part 成功数 / 仍处 UNKNOWN 的 part 数 /
    # 置 PARTIAL 断点的请求数 / 带 part 断点续发的请求数。
    parts_delivered: int = 0
    parts_unknown: int = 0
    partial_deferred: int = 0
    partials_resumed: int = 0
    operational_issues: tuple[OperationalIssue, ...] = ()


async def drain_send_queue_once(
    send_queue: DrainableSendQueue,
    transport: SendTransport,
    *,
    receipt_repository: ReceiptRepository | None = None,
    audit_logger: AuditRepository | None = None,
    now: datetime | None = None,
    limit: int = 20,
    operational_notifier: Callable[[DeliveryReceipt], object] | None = None,
    unknown_part_confirmer: UnknownPartConfirmer | None = None,
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
        "parts_delivered": 0,
        "parts_unknown": 0,
        "partial_deferred": 0,
        "partials_resumed": 0,
    }
    operational_issues: list[OperationalIssue] = []

    for entry in entries:
        part_outcome = await _try_deliver_by_parts(
            send_queue,
            entry,
            transport,
            receipt_repository=receipt_repository,
            audit_logger=audit_logger,
            now=current_time,
            unknown_part_confirmer=unknown_part_confirmer,
        )
        if part_outcome is None:
            receipt = await _call_transport_safely(entry.send_request, transport)
            queue_receipt = _update_queue_state(
                send_queue,
                entry.send_request,
                receipt,
                now=current_time,
            )
            ended_partial = False
        else:
            receipt = part_outcome.receipt
            queue_receipt = part_outcome.queue_receipt
            ended_partial = part_outcome.ended_partial
            counters["parts_delivered"] += part_outcome.parts_delivered
            counters["parts_unknown"] += part_outcome.parts_unknown
            counters["partials_resumed"] += 1 if part_outcome.resumed else 0
        if receipt.operational_issue is None and entry.send_request.operational_issue is not None:
            receipt = receipt.model_copy(
                update={
                    "operational_issue": entry.send_request.operational_issue,
                    "public_message": "",
                }
            )
        if receipt.operational_issue is not None:
            operational_issues.append(receipt.operational_issue)
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
                    private_debug=type(exc).__name__,
                )

        if receipt.operational_issue is not None and queue_receipt.operational_issue is None:
            queue_receipt = queue_receipt.model_copy(
                update={
                    "operational_issue": receipt.operational_issue,
                    "public_message": "",
                }
            )
        if ended_partial:
            counters["partial_deferred"] += 1
            event = "queue_worker_partial_deferred"
        elif queue_receipt.state is ReceiptState.SENT:
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
            receipt=queue_receipt,
        )
        await _notify_operational_issue_safely(
            operational_notifier,
            entry.send_request,
            queue_receipt,
        )

    return SendQueueWorkerResult(
        **counters,
        operational_issues=tuple(operational_issues),
    )


async def _notify_operational_issue_safely(
    notifier: Callable[..., object] | None,
    send_request: SendRequest,
    receipt: DeliveryReceipt,
) -> None:
    if notifier is None or receipt.operational_issue is None:
        return
    try:
        try:
            parameters = inspect.signature(notifier).parameters
            positional = [
                parameter
                for parameter in parameters.values()
                if parameter.kind
                in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                }
            ]
            accepts_varargs = any(
                parameter.kind is inspect.Parameter.VAR_POSITIONAL
                for parameter in parameters.values()
            )
        except (TypeError, ValueError):
            positional = []
            accepts_varargs = True
        value = (
            notifier(send_request, receipt)
            if accepts_varargs or len(positional) >= 2
            else notifier(receipt)
        )
        if inspect.isawaitable(value):
            async def _await_notification() -> None:
                try:
                    await value
                except Exception:  # noqa: BLE001 - alerting is a side channel.
                    return

            _spawn_background_task(_await_notification())
            # Start the task without waiting for the notifier's I/O to finish.
            await asyncio.sleep(0)
    except Exception:  # noqa: BLE001 - alerting must not affect queue state.
        return


def _call_queue_state_method(
    send_queue: DrainableSendQueue,
    method_name: str,
    request_id: str,
    public_message: str,
    *,
    now: datetime,
    operational_issue: OperationalIssue | None,
) -> DeliveryReceipt:
    method = getattr(send_queue, method_name)
    try:
        parameters = inspect.signature(method).parameters
        supports_issue = "operational_issue" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
    except (TypeError, ValueError):
        supports_issue = False
    kwargs: dict[str, object] = {"now": now}
    if supports_issue:
        kwargs["operational_issue"] = operational_issue
    return method(request_id, public_message, **kwargs)


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
            public_message="",
            debug_id=debug_id,
            operational_issue=OperationalIssue(
                stage="queue",
                kind="transport_exception",
                retryable=True,
                safe_summary="transport_exception",
                debug_id=debug_id,
            ),
        )


# ---- §9.3 part 级分片投递：UNKNOWN 确认协议 + PARTIAL 断点续发 -------------
# 只对 content_type="chunks" 且队列具备 part 存储 API（SQLiteSendRequestQueue）
# 的请求生效；其余请求完全走既有整发语义。核心不变量：全链路绝不重发已送达
# part；UNKNOWN part 在无法确认时绝不重发（防重复投递优先于防漏发）。


@dataclass(frozen=True)
class _PartDeliveryOutcome:
    """一次 part 化投递的结果（供 drain 主循环统一记账）。"""

    receipt: DeliveryReceipt
    queue_receipt: DeliveryReceipt
    ended_partial: bool = False
    parts_delivered: int = 0
    parts_unknown: int = 0
    resumed: bool = False


def _chunk_part_plan(send_request: SendRequest) -> list[str] | None:
    """提取分片计划；非 chunks 内容返回 None（走既有整发语义）。"""
    content = send_request.content
    if str(content.content_type).strip().lower() != "chunks":
        return None
    if send_request.target_scope not in (SessionType.PRIVATE, SessionType.GROUP):
        return None
    raw_chunks = content.content_ref.get("chunks")
    chunks = (
        [str(item).strip() for item in raw_chunks if str(item).strip()]
        if isinstance(raw_chunks, list)
        else []
    )
    if not chunks:
        chunks = [content.text_fallback]
    return chunks or None


def _payload_digest(chunk: str) -> str:
    """payload 摘要（规格 §9.3.2）：只存摘要，不存用户正文副本。"""
    return hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16]


def _single_part_request(send_request: SendRequest, chunk: str) -> SendRequest:
    """构造单 part 子请求：part_index 由 chunks 里的原始位置保持稳定键。"""
    content = send_request.content.model_copy(
        update={"content_ref": {"chunks": [chunk]}}
    )
    return send_request.model_copy(update={"content": content})


def _part_store(send_queue: DrainableSendQueue) -> PartStoreQueue | None:
    """鸭子类型探测队列的 part 存储 API；内存队列等无此 API → None。"""
    if callable(getattr(send_queue, "ensure_parts_planned", None)) and callable(
        getattr(send_queue, "mark_part_sent", None)
    ):
        return cast(PartStoreQueue, send_queue)
    return None


async def _confirm_unknown_part_safely(
    confirmer: UnknownPartConfirmer,
    send_request: SendRequest,
    part_index: int,
) -> bool | None:
    try:
        return await confirmer(send_request, part_index)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - 确认是旁路；失败=无法确认，绝不盲发。
        return None


def _record_part_receipt_safely(
    receipt_repository: ReceiptRepository | None,
    receipt: DeliveryReceipt,
    send_request: SendRequest,
    audit_logger: AuditRepository | None,
) -> None:
    if receipt_repository is None:
        return
    try:
        receipt_repository.record(receipt)
    except Exception as exc:  # noqa: BLE001 - 回执记录失败不影响投递。
        _append_worker_audit_safely(
            audit_logger,
            send_request,
            event="queue_worker_receipt_record_failed",
            receipt=receipt,
            private_debug=type(exc).__name__,
        )


def _part_issue(kind: str) -> OperationalIssue:
    debug_id = new_debug_id()
    return OperationalIssue(
        stage="queue",
        kind=kind,
        retryable=False,
        safe_summary=kind,
        debug_id=debug_id,
    )


async def _try_deliver_by_parts(
    send_queue: DrainableSendQueue,
    entry: QueuedSendRequest,
    transport: SendTransport,
    *,
    receipt_repository: ReceiptRepository | None,
    audit_logger: AuditRepository | None,
    now: datetime,
    unknown_part_confirmer: UnknownPartConfirmer | None = None,
) -> _PartDeliveryOutcome | None:
    """part 级投递入口；返回 None 表示降级为既有整发路径。

    降级只发生在规划事务（原子）失败且未产生任何副作用时——此后任何存储
    异常一律按 result_unknown 终态化，绝不回落整发（已送达 part 会被重发）。
    """
    store = _part_store(send_queue)
    chunks = _chunk_part_plan(entry.send_request)
    if store is None or not chunks:
        return None
    request = entry.send_request
    request_id = request.request_id
    logger = logging.getLogger(__name__)
    resumed = entry.parts is not None and (
        entry.parts.delivered > 0 or bool(entry.parts.unknown_indexes())
    )
    try:
        planned = store.ensure_parts_planned(
            request_id,
            [_payload_digest(chunk) for chunk in chunks],
            now=now,
        )
    except Exception:  # noqa: BLE001 - 规划失败且零副作用 → 安全降级整发。
        logger.warning(
            "part plan persist failed, falling back to whole-request delivery request_id=%s",
            request_id,
        )
        return None
    if planned is None:
        return None

    parts_delivered = 0
    parts_unknown = 0
    progress_made = False
    last_receipt: DeliveryReceipt | None = None
    try:
        progress = planned
        # 1) UNKNOWN 确认协议：先查 part 回执（provider_message_id），再问
        #    确认器（get_msg 等价物）；无法确认的 UNKNOWN 保持原状不重发。
        for part_index in progress.unknown_indexes():
            record = progress.records.get(part_index)
            verdict: bool | None = None
            if record is not None and record.provider_message_id:
                verdict = True
            elif unknown_part_confirmer is not None:
                verdict = await _confirm_unknown_part_safely(
                    unknown_part_confirmer, request, part_index
                )
            if verdict is True:
                store.mark_part_sent(request_id, part_index, now=now)
                parts_delivered += 1
                progress_made = True
            elif verdict is False:
                # 平台明确「未送达」：重发安全，回到 PENDING。
                store.mark_part_pending(request_id, part_index, now=now)
                progress_made = True
            else:
                parts_unknown += 1

        # 2) 顺序续发 PENDING part（attempts 达上限的 part 跳过，靠请求级
        #    退避循环最终收敛到终态）。
        progress = store.part_progress(request_id) or progress
        attempts_cap = max(1, int(store.max_attempts))
        for part_index in progress.pending_indexes():
            record = progress.records.get(part_index)
            if record is not None and record.attempts >= attempts_cap:
                continue
            store.mark_part_attempt(request_id, part_index, now=now)
            receipt = await _call_transport_safely(
                _single_part_request(request, chunks[part_index]), transport
            )
            last_receipt = receipt
            _record_part_receipt_safely(
                receipt_repository, receipt, request, audit_logger
            )
            if receipt.state is ReceiptState.SENT:
                store.mark_part_sent(
                    request_id,
                    part_index,
                    provider_message_id=receipt.provider_message_id,
                    now=now,
                )
                parts_delivered += 1
                progress_made = True
            elif receipt.state is ReceiptState.FAILED_RETRYABLE:
                # 明确可重试的失败：回 PENDING，本轮继续发后续 part
                # （规格验收场景 2：只补发失败 part，后续 part 照常推进）。
                store.mark_part_pending(request_id, part_index, now=now)
            else:
                issue_kind = (
                    receipt.operational_issue.kind
                    if receipt.operational_issue is not None
                    else ""
                )
                if issue_kind == "result_unknown":
                    store.mark_part_unknown(
                        request_id, part_index, error_kind=issue_kind, now=now
                    )
                    parts_unknown += 1
                else:
                    store.mark_part_failed_final(
                        request_id, part_index, error_kind=issue_kind or None, now=now
                    )
                # 结果未知/明确终败后停止后续 part：连接可能已不可靠，
                # 与既有「有副作用即不整体重投」语义一致。
                break
    except Exception:  # noqa: BLE001 - part 存储中途异常：绝不回落整发。
        logger.warning(
            "part delivery persistence failed request_id=%s", request_id
        )
        issue = _part_issue("result_unknown")
        receipt = DeliveryReceipt(
            request_id=request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=SEND_QUEUE_WORKER_TRANSPORT,
            public_message="",
            debug_id=issue.debug_id,
            operational_issue=issue,
        )
        queue_receipt = _finalize_part_outcome_safely(
            send_queue, request_id, receipt, now=now
        )
        return _PartDeliveryOutcome(
            receipt=receipt,
            queue_receipt=queue_receipt,
            parts_delivered=parts_delivered,
            parts_unknown=parts_unknown,
            resumed=resumed,
        )

    # 3) 收敛终态：全部 SENT 才算成功；存在 UNKNOWN 置 PARTIAL 断点；
    #    剩余可重试 part 走既有退避循环；无可推进项按既有终态处理。
    #    读回退失败用本 pass 内存快照收敛；收敛本身异常则按 result_unknown
    #    兜底终态化（任何异常不抛主链路）。
    try:
        progress = store.part_progress(request_id) or progress
    except Exception:  # noqa: BLE001 - 快照兜底，见函数 docstring。
        logging.getLogger(__name__).debug(
            "part progress refresh failed, using in-pass snapshot request_id=%s",
            request_id,
        )
    try:
        return _converge_part_end_state(
            send_queue,
            store,
            request_id,
            progress,
            last_receipt=last_receipt,
            progress_made=progress_made,
            parts_delivered=parts_delivered,
            parts_unknown=parts_unknown,
            resumed=resumed,
            now=now,
        )
    except Exception:  # noqa: BLE001 - 收敛失败绝不抛出，按结果未知兜底。
        logging.getLogger(__name__).warning(
            "part end-state convergence failed request_id=%s", request_id
        )
        issue = _part_issue("result_unknown")
        receipt = DeliveryReceipt(
            request_id=request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=SEND_QUEUE_WORKER_TRANSPORT,
            public_message="",
            debug_id=issue.debug_id,
            operational_issue=issue,
        )
        return _PartDeliveryOutcome(
            receipt=receipt,
            queue_receipt=_finalize_part_outcome_safely(
                send_queue, request_id, receipt, now=now
            ),
            parts_delivered=parts_delivered,
            parts_unknown=parts_unknown,
            resumed=resumed,
        )


def _converge_part_end_state(
    send_queue: DrainableSendQueue,
    store: PartStoreQueue,
    request_id: str,
    progress: PartProgress,
    *,
    last_receipt: DeliveryReceipt | None,
    progress_made: bool,
    parts_delivered: int,
    parts_unknown: int,
    resumed: bool,
    now: datetime,
) -> _PartDeliveryOutcome:
    """part 投递后的终态收敛（由 _try_deliver_by_parts 的兜底 try 包裹调用）。"""
    if progress.total > 0 and progress.delivered == progress.total:
        queue_receipt = _call_queue_state_method(
            send_queue, "mark_sent", request_id, "sent", now=now, operational_issue=None
        )
        receipt = last_receipt or DeliveryReceipt(
            request_id=request_id,
            state=ReceiptState.SENT,
            transport=SEND_QUEUE_WORKER_TRANSPORT,
            public_message="sent",
        )
        return _PartDeliveryOutcome(
            receipt=receipt,
            queue_receipt=queue_receipt,
            parts_delivered=parts_delivered,
            parts_unknown=parts_unknown,
            resumed=resumed,
        )
    if progress.unknown_indexes():
        issue = _part_issue("result_unknown")
        queue_receipt = store.mark_partial(
            request_id,
            resumable=progress_made,
            now=now,
            operational_issue=issue,
        )
        receipt = DeliveryReceipt(
            request_id=request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=SEND_QUEUE_WORKER_TRANSPORT,
            public_message="",
            debug_id=issue.debug_id,
            operational_issue=issue,
        )
        return _PartDeliveryOutcome(
            receipt=receipt,
            queue_receipt=queue_receipt,
            ended_partial=True,
            parts_delivered=parts_delivered,
            parts_unknown=parts_unknown,
            resumed=resumed,
        )
    if progress.pending_indexes():
        queue_receipt = _call_queue_state_method(
            send_queue,
            "mark_retryable_failure",
            request_id,
            "failed_retryable",
            now=now,
            operational_issue=None,
        )
        receipt = last_receipt or DeliveryReceipt(
            request_id=request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport=SEND_QUEUE_WORKER_TRANSPORT,
            public_message="",
            operational_issue=_part_issue("part_delivery_retryable"),
        )
        return _PartDeliveryOutcome(
            receipt=receipt,
            queue_receipt=queue_receipt,
            parts_delivered=parts_delivered,
            parts_unknown=parts_unknown,
            resumed=resumed,
        )
    queue_receipt = _call_queue_state_method(
        send_queue,
        "mark_final_failure",
        request_id,
        "failed_final",
        now=now,
        operational_issue=None,
    )
    receipt = last_receipt or DeliveryReceipt(
        request_id=request_id,
        state=ReceiptState.FAILED_FINAL,
        transport=SEND_QUEUE_WORKER_TRANSPORT,
        public_message="",
    )
    return _PartDeliveryOutcome(
        receipt=receipt,
        queue_receipt=queue_receipt,
        parts_delivered=parts_delivered,
        parts_unknown=parts_unknown,
        resumed=resumed,
    )


def _finalize_part_outcome_safely(
    send_queue: DrainableSendQueue,
    request_id: str,
    receipt: DeliveryReceipt,
    *,
    now: datetime,
) -> DeliveryReceipt:
    """part 存储异常后的兜底终态化；再失败则原样返回回执（不抛主链路）。"""
    try:
        return _call_queue_state_method(
            send_queue,
            "mark_final_failure",
            request_id,
            "",
            now=now,
            operational_issue=receipt.operational_issue,
        )
    except Exception:  # noqa: BLE001 - 队列也不可用时只能放弃状态推进。
        return receipt


def _update_queue_state(
    send_queue: DrainableSendQueue,
    send_request: SendRequest,
    receipt: DeliveryReceipt,
    *,
    now: datetime,
) -> DeliveryReceipt:
    issue = receipt.operational_issue or send_request.operational_issue
    public_message = "" if issue is not None else receipt.public_message
    if receipt.state is ReceiptState.SENT:
        return _call_queue_state_method(
            send_queue,
            "mark_sent",
            send_request.request_id,
            public_message or "sent",
            now=now,
            operational_issue=issue,
        )
    if receipt.state is ReceiptState.FAILED_RETRYABLE:
        return _call_queue_state_method(
            send_queue,
            "mark_retryable_failure",
            send_request.request_id,
            public_message if issue is not None else public_message or "failed_retryable",
            now=now,
            operational_issue=issue,
        )
    if receipt.state is ReceiptState.SKIPPED:
        return _call_queue_state_method(
            send_queue,
            "mark_final_failure",
            send_request.request_id,
            public_message or "skipped",
            now=now,
            operational_issue=issue,
        ).model_copy(update={"state": ReceiptState.SKIPPED, "operational_issue": issue})
    return _call_queue_state_method(
        send_queue,
        "mark_final_failure",
        send_request.request_id,
        public_message if issue is not None else public_message or receipt.state.value,
        now=now,
        operational_issue=issue,
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


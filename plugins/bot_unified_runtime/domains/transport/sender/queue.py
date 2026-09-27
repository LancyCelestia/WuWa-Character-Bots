from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.audit import AuditRepository
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    DeliveryReceipt,
    OperationalIssue,
    ReceiptState,
    SendRequest,
)
from plugins.bot_unified_runtime.domains.transport.sender.receipts import (
    sent_receipt,
    skipped_receipt,
)
from plugins.bot_unified_runtime.domains.transport.sender.timeout import (
    resolve_transport_timeout,
)

SQLITE_QUEUE_TRANSPORT = "sqlite_queue"
PROCESSING_STATE = "processing"
# §9.3 part 级幂等恢复：PARTIAL 是请求行终态（contracts/ 本轮禁改，无法新增
# ReceiptState 枚举成员，故以裸字符串落库）。语义：parts_delivered>0 且未全部
# 送达时不得置 FAILED_FINAL 盲重发，也不得伪装成功——记录断点，由补偿扫描
# （claim_due 扫 state='partial' 且 next_retry_at 到期的行）续发剩余 part。
PARTIAL_ROW_STATE = "partial"
# part 级状态机（规格 §9.3.2）：PENDING/SENT/UNKNOWN/FAILED_FINAL。
PART_STATE_PENDING = "pending"
PART_STATE_SENT = "sent"
PART_STATE_UNKNOWN = "unknown"
PART_STATE_FAILED_FINAL = "failed_final"
# PARTIAL 行补偿扫描的重试间隔：与 bot_unavailable 挂起的 90s 对齐（慢速重探，
# 不随 retry_base_seconds 变化；确认类扫描本身不重发任何 part）。
_PARTIAL_RESUME_BACKOFF_SECONDS = 90.0
# 死租约有界回收（S-FIX-TRANS-LEASE）：state='processing' 但 lease_expires_at
# 为 NULL 的行（A-20 租约协议上线前的存量认领行——_backfill_session_id 回填
# session_id 后开始参与同会话互斥；或异常/人工直写遗留）此前是双重的洞：
# ①外层认领臂要求「租约非空且已过期」→ 该行永不被重认领，永远停在
#   processing；②NOT EXISTS 互斥臂把 NULL 租约当「永远在途」→ 同会话所有
#   后续行被永久阻塞（饥饿）。修法：NULL 租约以 updated_at 为心跳，缺席超过
#   本窗口即不再算在途，且该行本身进入认领候选（走既有 PROCESSING 臂：
#   retry_count+1、重写租约，预算烧尽经 _finalize_expired_lease/PARTIAL 收口
#   ——不新建第二套状态机）。窗口取 300s：现役 claim 必写非空租约，NULL 租约
#   的 processing 行按定义是「无人正当持有」的遗留行（旧版认领后崩溃/迁移
#   半态）；即便存在持 NULL 租约仍在慢速投递的行，其每个 part 尝试都经
#   mark_part_attempt→_refresh_request_part_summary_in 推进 updated_at，
#   窗内误杀要求「无租约且心跳静默 ≥5 分钟」，属进程级病态，与 _inline_claims
#   台账对永久悬挂的处理口径一致（防重复投递优先于防漏发）。
_DEAD_LEASE_RECLAIM_SECONDS = 300.0
# 新入队行的认领宽限期：submit 写入 next_retry_at=now+宽限期，宽限期内
# worker 的 claim_due 不得认领该行——入队后的首次投递由 handler 内联
# 负责（不走租约协议），避免 worker 与内联投递竞态重复发送同一消息。
# 宽限期过后该行仍在 QUEUED 态（例如进程重启丢了内联投递），由 worker 接管。
# 审查 A-22：纯时间错开不可论证正确——内联耗时超过宽限期（多分片×传输
# 超时、事件循环停顿）时 worker 仍会认领在途行 → 双发。故时间宽限只保留
# 「跨重启丢失内联投递」的兜底职责；同进程内的硬互斥由进程内联认领台账
# （_inline_claims，见 SQLiteSendRequestQueue）承担：内联在途期间 worker
# 不得认领，与宽限期长短无关。
_INLINE_DELIVERY_GRACE_SECONDS = 60


def _inline_delivery_grace_seconds() -> float:
    """内联首投认领宽限期 = max(60s, 3×传输硬超时)（终审 Important 耦合修复）。

    内联首投最坏耗时 ≈ 3×传输超时+缓冲；宽限期小于它时 worker 会在内联未
    完成时认领同一行 → 同一条消息双发。传输超时是运维旋钮
    （bot_transport_timeout_seconds，默认 15s），宽限期随之取 max 防漂移。
    """
    try:
        transport_timeout = float(resolve_transport_timeout())
    except Exception:  # noqa: BLE001 - 取不到配置回退默认 15s。
        transport_timeout = 15.0
    return max(
        float(_INLINE_DELIVERY_GRACE_SECONDS), 3.0 * max(0.0, transport_timeout)
    )
# B-4（管线检视 #6）：bot_unavailable 挂起语义参数。
# 挂起期间不消耗重试预算，重试间隔取固定 90s 下限（SnowLuma 断线窗口内
# 慢速重探，不随重试预算配置变化）；入队超过绝对年龄上限（默认 30min，
# 可经 bot_send_bot_unavailable_max_age_seconds 覆盖）仍不可投才置终态
# （防 A4 契约下死挂行无限堆积）。
_BOT_UNAVAILABLE_KIND = "bot_unavailable"
_BOT_UNAVAILABLE_RETRY_DELAY_SECONDS = 90.0
_BOT_UNAVAILABLE_MAX_AGE_SECONDS = 1800.0


class _CorruptQueueRow(Exception):
    """队列行无法还原为条目的哨兵异常（毒行隔离，评审 H9）。

    ``_entry_from_row`` 把解析期的一切异常（pydantic ValidationError、非法
    时间戳、缺列）统一包成本类型，调用方据此把该行就地终态化并跳过，避免
    **单条**坏行毒死整批已认领的消息。
    """

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        # 只接受普通 Exception：调用方按 `Exception | None` 使用该属性，
        # 避免把 BaseException 混进日志/类型面（system-exiting 异常不在此路径）。
        original = cause if cause is not None else self.__cause__
        self.cause: Exception | None = (
            original if isinstance(original, Exception) else None
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _part_key(request_id: str, part_index: int) -> str:
    """规格 §9.3.1：part 稳定键 = message_request_id + part_index，重试不换键。"""
    return f"{request_id}#part{int(part_index)}"


def _queued_receipt(send_request: SendRequest) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.QUEUED,
        transport=SQLITE_QUEUE_TRANSPORT,
        public_message="" if send_request.operational_issue is not None else "queued",
        operational_issue=send_request.operational_issue,
    )


@dataclass(frozen=True)
class QueuedSendRequest:
    send_request: SendRequest
    state: ReceiptState
    retry_count: int
    next_retry_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lease_expires_at: datetime | None = None
    # §9.3：part 级进度（仅 SQLite 队列装载；None=无 part 跟踪，走既有整发语义）。
    parts: PartProgress | None = None


@dataclass(frozen=True)
class PartRecord:
    """单条 part 的持久化状态（send_request_parts 行投影）。"""

    part_index: int
    state: str
    attempts: int = 0
    last_error_kind: str | None = None
    provider_message_id: str | None = None
    payload_digest: str | None = None


@dataclass(frozen=True)
class PartProgress:
    """一个请求的 part 级进度快照（只读视图）。"""

    total: int
    records: dict[int, PartRecord]

    @property
    def delivered(self) -> int:
        return sum(1 for record in self.records.values() if record.state == PART_STATE_SENT)

    def indexes_in_state(self, state: str) -> list[int]:
        return sorted(
            index for index, record in self.records.items() if record.state == state
        )

    def pending_indexes(self) -> list[int]:
        return self.indexes_in_state(PART_STATE_PENDING)

    def unknown_indexes(self) -> list[int]:
        return self.indexes_in_state(PART_STATE_UNKNOWN)


class SendQueue(Protocol):
    def submit(self, send_request: SendRequest) -> DeliveryReceipt:
        raise NotImplementedError

    def find_request(self, request_id: str) -> SendRequest | None:
        raise NotImplementedError

    def safe_summary(self) -> dict[str, int]:
        raise NotImplementedError


class InMemorySendQueue:
    """内存发送队列：有界（FIFO 淘汰最旧请求及其去重键）。

    完整 SendRequest（含渲染正文）每条 KB 级且进程内常驻，无上界时随
    消息量线性吃内存、find_request 全量倒扫越来越慢。
    """

    def __init__(self, audit_logger: AuditRepository, *, max_requests: int = 500) -> None:
        self.audit_logger = audit_logger
        self.max_requests = max(1, int(max_requests))
        self.sent_requests: list[SendRequest] = []
        self._dedupe_keys: set[str] = set()

    def submit(self, send_request: SendRequest) -> DeliveryReceipt:
        if send_request.dedupe_key in self._dedupe_keys:
            receipt = skipped_receipt(send_request, "duplicate dedupe_key")
            event = "skipped_duplicate"
        else:
            while len(self.sent_requests) >= self.max_requests:
                evicted = self.sent_requests.pop(0)
                self._dedupe_keys.discard(evicted.dedupe_key)
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

    def find_request(self, request_id: str) -> SendRequest | None:
        normalized = request_id.strip()
        if not normalized:
            return None
        return next(
            (
                request
                for request in reversed(self.sent_requests)
                if request.request_id == normalized
            ),
            None,
        )

    def safe_summary(self) -> dict[str, int]:
        return {
            ReceiptState.QUEUED.value: 0,
            ReceiptState.FAILED_RETRYABLE.value: 0,
            ReceiptState.FAILED_FINAL.value: 0,
            ReceiptState.SENT.value: len(self.sent_requests),
            ReceiptState.SKIPPED.value: 0,
            PROCESSING_STATE: 0,
        }


class SQLiteSendRequestQueue:
    def __init__(
        self,
        db_path: str | Path,
        audit_logger: AuditRepository,
        *,
        max_items: int = 1000,
        max_attempts: int = 3,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 300,
        bot_unavailable_max_age_seconds: float | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.audit_logger = audit_logger
        self.max_items = max(1, int(max_items))
        self.max_attempts = max(1, int(max_attempts))
        self.retry_base_seconds = max(1, int(retry_base_seconds))
        self.retry_max_seconds = max(self.retry_base_seconds, int(retry_max_seconds))
        # bot_unavailable 挂起的绝对年龄上限：None 用模块默认常量。
        self._bot_unavailable_max_age_seconds = (
            float(bot_unavailable_max_age_seconds)
            if bot_unavailable_max_age_seconds is not None
            else _BOT_UNAVAILABLE_MAX_AGE_SECONDS
        )
        self._soft_ceiling_warned = False
        # 每次操作都重跑建表 DDL 是纯浪费：进程内建一次即可（含 WAL 切换）。
        self._schema_ready = False
        # 进程内长连接（B-10，管线检视 #13）：check_same_thread=False +
        # 锁串行化，消除每操作建连开销与 mark_* 跨连接两事务的非原子读改写。
        self._connection: sqlite3.Connection | None = None
        self._connection_lock = threading.RLock()
        # 审查 A-22：进程内联认领台账（request_id → 提交任务）。
        # 生产内联首投是「同一协程内 submit → transport → mark_*」的同任务
        # 序列，worker 是跨任务认领者——台账把「内联在途」从时间推断
        # （宽限期）升级为任务存活推断：提交任务未终结且认领者非本人时，
        # claim_due 否决该行，内联耗时再长也不会被重复投递。生命周期：
        #   登记 = submit 成功插入且未声明 deliver_after（事件循环内才登记，
        #          线程提交退回纯时间宽限=既有语义）；
        #   释放 = mark_sent / mark_retryable_failure / mark_final_failure /
        #          mark_partial（内联已终结，无论成败）+ claim_due 遇死认领
        #          （提交任务已终结仍未 mark_*，取消/异常路径）惰性清簿；
        #   重启 = 台账随进程消亡，磁盘 next_retry_at 宽限兜底（现状语义）。
        # 台账只活在内联窗口内，条目数与在途消息数同阶；任务永久悬挂属进程
        # 级病态，对应行保持不认领（防重复投递优先于防漏发，与 §9.3 一致）。
        self._inline_claims: dict[str, asyncio.Task[None]] = {}

    def _ensure_schema_once(self) -> None:
        if self._schema_ready:
            return
        self._ensure_schema()
        self._schema_ready = True

    def _shared_connection(self) -> sqlite3.Connection:
        with self._connection_lock:
            if self._connection is None:
                connection = sqlite3.connect(
                    self.db_path, timeout=5.0, check_same_thread=False
                )
                connection.row_factory = sqlite3.Row
                self._connection = connection
            return self._connection

    def _discard_connection(self) -> None:
        with self._connection_lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except sqlite3.Error:
                    pass
                self._connection = None

    @contextmanager
    def _transaction(self):
        """共享连接上的读写事务：显式 BEGIN，正常提交、异常回滚。

        读-改-写（mark_* 查 entry 后更新）由此成为真正的单事务；
        sqlite3.Error 额外丢弃连接（库级损坏/断连时复用不安全）。
        """
        with self._connection_lock:
            connection = self._shared_connection()
            try:
                connection.execute("BEGIN")
                yield connection
            except sqlite3.Error:
                connection.rollback()
                self._discard_connection()
                raise
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @contextmanager
    def _transaction_immediate(self):
        """写优先事务：认领租约用 IMMEDIATE 先取写锁，避免锁升级死锁。

        毒行隔离（评审 H9）：``_CorruptQueueRow`` 是**业务失败而非事务失败**，
        因此先提交已完成的工作（认领写入 + 坏行终态化），再向外抛出——若走
        通用回滚分支，已提交的认领会被撤销，坏行又退回 QUEUED 每轮重复毒杀，
        正是事故的原始形态。DB 级错误（sqlite3.Error）仍走回滚+丢连接。
        """
        with self._connection_lock:
            connection = self._shared_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
            except sqlite3.Error:
                connection.rollback()
                self._discard_connection()
                raise
            except _CorruptQueueRow:
                # 提交：本批的认领与坏行终态化必须落盘才能达成隔离目的。
                try:
                    connection.commit()
                except sqlite3.Error:
                    connection.rollback()
                    self._discard_connection()
                raise
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @contextmanager
    def _locked_connection(self):
        """只读操作对共享连接的持锁借用。"""
        with self._connection_lock:
            yield self._shared_connection()

    # ---- 审查 A-22：内联首投认领台账 ----------------------------------------
    # 竞态窗口论证：内联首投（handler 协程）与 worker 投递（调度任务）是两个
    # 无共享同步原语的并发投递者，原先只靠 next_retry_at 时间错开——内联耗时
    # 超过宽限期（多分片×传输超时、事件循环停顿）即双发。台账以「提交任务
    # 是否终结」为在途信号：任务存活=内联仍持行；任务终结（正常路径必经
    # mark_* 四口之一，异常/取消路径由死认领清簿兜底）=行可被 worker 接管。
    # 所有读写都在 _connection_lock（RLock）临界区内，与既有锁序一致。

    def _register_inline_claim(self, request_id: str) -> None:
        """登记内联首投认领；仅事件循环内调用生效（须在连接锁临界区内）。

        线程提交（无运行中事件循环）不登记：退回纯时间宽限=既有语义。
        """
        try:
            task = asyncio.current_task()
        except RuntimeError:  # 无事件循环（如后台渲染线程提交）
            return
        if task is None:
            return
        self._inline_claims[request_id] = task

    def _release_inline_claim(self, request_id: str) -> None:
        """释放内联认领（mark_* 终结口调用；须在连接锁临界区内）。"""
        self._inline_claims.pop(request_id, None)

    def _inline_claim_blocks(
        self, request_id: str, claimer: asyncio.Task[None] | None
    ) -> bool:
        """该行的内联认领是否否决本次认领（须在连接锁临界区内）。

        - 无台账条目：不否决（正常 worker 认领/跨重启恢复路径）。
        - 条目任务已终结：死认领（取消/异常未及 mark_*）→ 清簿放行，保住
          「内联丢失后 worker 接管」的恢复语义。
        - 条目任务存活且认领者就是提交任务本人（同一协程 submit 后自行
          drain，如测试/顺序管线）：不否决——单协程内天然串行，不存在
          跨任务竞态；跨任务认领者（生产 worker）被否决，这正是 A-22 目标。
        """
        entry = self._inline_claims.get(request_id)
        if entry is None:
            return False
        if entry.done():
            self._inline_claims.pop(request_id, None)
            return False
        return entry is not claimer

    def submit(
        self,
        send_request: SendRequest,
        *,
        now: datetime | None = None,
        deliver_after: datetime | None = None,
    ) -> DeliveryReceipt:
        """入队；``deliver_after`` 指定 worker 最早投递时刻（A-plus）。

        - 缺省 ``None``：与既有行为字节级一致（next_retry_at=内联宽限期，
          首叛逆由 handler 内联负责，宽限过后 worker 接管）。
        - 非 ``None``：该行在 ``deliver_after`` 之前 claim_due/list_due 均不
          认领（不到点不投递）。调用方以该参数**覆盖**内联宽限，即声明此
          请求无内联首投（如后台线程补发），不存在 worker 抢跑双发窗口。
        """
        current_time = now or _utc_now()
        next_retry_at = (
            deliver_after
            if deliver_after is not None
            else current_time + timedelta(seconds=_inline_delivery_grace_seconds())
        )
        self._ensure_schema_once()
        with self._transaction() as connection:
            # 去重与写入必须原子：SELECT→INSERT 两步在并发下会同时通过
            # 检查并在主键冲突时抛未捕获 IntegrityError；改为单条
            # INSERT ... ON CONFLICT DO NOTHING，冲突即重复。
            cursor = connection.execute(
                """
                INSERT INTO send_requests (
                    dedupe_key,
                    request_id,
                    state,
                    request_json,
                    retry_count,
                    next_retry_at,
                    last_public_message,
                    created_at,
                    updated_at,
                    session_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO NOTHING
                """,
                (
                    send_request.dedupe_key,
                    send_request.request_id,
                    ReceiptState.QUEUED.value,
                    send_request.model_dump_json(),
                    0,
                    next_retry_at.isoformat(),
                    "" if send_request.operational_issue is not None else "queued",
                    current_time.isoformat(),
                    current_time.isoformat(),
                    send_request.session_id,
                ),
            )
            if cursor.rowcount == 0:
                receipt = skipped_receipt(send_request, "duplicate dedupe_key")
                event = "skipped_duplicate"
            else:
                self._prune(connection)
                receipt = _queued_receipt(send_request)
                event = "queued"
                # 审查 A-22：缺省入队（无 deliver_after）= 声明本行有内联首投，
                # 登记认领台账堵 worker 抢跑双发窗口；deliver_after 入队（如
                # 错误卡补发）声明无内联首投，绝不登记（worker 到点照常认领）。
                if deliver_after is None:
                    self._register_inline_claim(send_request.request_id)

        self._append_sender_audit(send_request, receipt, event)
        return receipt

    def list_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
    ) -> list[QueuedSendRequest]:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        safe_limit = max(1, int(limit))
        with self._locked_connection() as connection:
            return self._list_due_unlocked(connection, current_time, safe_limit)

    def find_request(self, request_id: str) -> SendRequest | None:
        normalized = request_id.strip()
        if not normalized:
            return None
        entry = self._find_entry_by_request_id(normalized)
        return entry.send_request if entry is not None else None

    def claim_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
        lease_seconds: int = 60,
    ) -> list[QueuedSendRequest]:
        current_time = now or _utc_now()
        safe_limit = max(1, int(limit))
        safe_lease_seconds = max(1, int(lease_seconds))
        lease_expires_at = current_time + timedelta(seconds=safe_lease_seconds)
        # 死租约有界回收（见 _DEAD_LEASE_RECLAIM_SECONDS 头注）：NULL 租约的
        # processing 行按「距最后一次写入是否超过回收窗」判在途/死，不再
        # 永远算在途。updated_at 即心跳列（claim/mark_*/part 汇总写都推进）。
        dead_lease_cutoff = (
            current_time - timedelta(seconds=_DEAD_LEASE_RECLAIM_SECONDS)
        ).isoformat()
        self._ensure_schema_once()
        # 审查 A-22：认领者身份（无事件循环的线程认领 → None，视作跨任务
        # 认领者，内联在途否决照常生效）。
        try:
            claimer_task: asyncio.Task[None] | None = asyncio.current_task()
        except RuntimeError:
            claimer_task = None
        with self._transaction_immediate() as connection:
            # 审查 A-20（worker 侧）per-session 串行化：同会话已有在途认领
            # （state='processing' 且租约未过期）时，该会话的其余到期行不得
            # 进入本批候选——投递顺序只能在认领口保证，投递侧锁无法约束
            # 并发认领者。租约已过期的 processing 行视为死认领，不阻塞同
            # 会话（崩溃恢复场景顺序本已不可保，但队列不得因此停摆）；
            # rowid<>self 排除自身，让本行的租约过期重认领照常进行。
            # session_id IS NULL 的存量行（迁移前/毒行）不参与互斥，行为与
            # 既有语义一致。
            rows = connection.execute(
                """
                SELECT *
                FROM send_requests
                WHERE (
                    (state IN (?, ?) AND (next_retry_at IS NULL OR next_retry_at <= ?))
                    OR (
                        state = ?
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at <= ?
                    )
                    OR (
                        state = ?
                        AND next_retry_at IS NOT NULL
                        AND next_retry_at <= ?
                    )
                    OR (
                        state = ?
                        AND lease_expires_at IS NULL
                        AND updated_at <= ?
                    )
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM send_requests AS in_flight
                    WHERE in_flight.session_id IS NOT NULL
                      AND in_flight.session_id = send_requests.session_id
                      AND in_flight.state = ?
                      AND in_flight.rowid <> send_requests.rowid
                      AND (
                          (
                              in_flight.lease_expires_at IS NOT NULL
                              AND in_flight.lease_expires_at > ?
                          )
                          OR (
                              in_flight.lease_expires_at IS NULL
                              AND in_flight.updated_at > ?
                          )
                      )
                )
                ORDER BY created_at ASC, rowid ASC
                LIMIT ?
                """,
                (
                    ReceiptState.QUEUED.value,
                    ReceiptState.FAILED_RETRYABLE.value,
                    current_time.isoformat(),
                    PROCESSING_STATE,
                    current_time.isoformat(),
                    PARTIAL_ROW_STATE,
                    current_time.isoformat(),
                    PROCESSING_STATE,
                    dead_lease_cutoff,
                    PROCESSING_STATE,
                    current_time.isoformat(),
                    dead_lease_cutoff,
                    safe_limit,
                ),
            ).fetchall()
            claimed_keys: list[str] = []
            for row in rows:
                # 审查 A-22：内联首投在途（提交任务存活且认领者非本人）的行
                # 一律否决认领——不区分 QUEUED 到期 / 租约过期 / PARTIAL 续发
                # 入口，内联耗时超过宽限期也不会被 worker 重复投递。被否决行
                # 本 pass 跳过，下轮 claim 重查（任务终结后自动放行）。
                if self._inline_claim_blocks(str(row["request_id"]), claimer_task):
                    continue
                if row["state"] == PARTIAL_ROW_STATE:
                    # §9.3 补偿扫描：PARTIAL 行续发。claimed_from_state 只能取
                    # 合法 ReceiptState 值（'partial' 会让 _entry_from_row 误判
                    # 毒行）；续发预算由 part 级 attempts 约束，不烧请求级
                    # retry_count（PARTIAL 行通常是请求预算已烧尽后转换来的）。
                    claimed_from_state = ReceiptState.FAILED_RETRYABLE.value
                    retry_count = int(row["retry_count"])
                else:
                    claimed_from_state = (
                        str(row["claimed_from_state"])
                        if row["state"] == PROCESSING_STATE
                        and row["claimed_from_state"] is not None
                        else str(row["state"])
                    )
                    retry_count = int(row["retry_count"])
                    if row["state"] == PROCESSING_STATE:
                        # 租约过期重认领意味着上一次投递结果未知（可能已送达），
                        # 必须计入尝试次数；否则进程崩溃循环会无限重发。
                        retry_count += 1
                        if retry_count >= self.max_attempts:
                            self._finalize_expired_lease(
                                connection, row, retry_count, current_time
                            )
                            continue
                # 审查 A-20：本批内的同会话多行照常一并认领——单 pass 内
                # worker 按 created_at 顺序逐条投递，批内天然有序；拆散反而
                # 会把错误报告「ack+卡片」这类同批逻辑对拆到两个 pass（30s 错
                # 位）。跨请求会话内顺序由上方 NOT EXISTS 保证：并发认领者
                # 在同会话已有在途（租约未过期）行时拿不到新候选。
                connection.execute(
                    """
                    UPDATE send_requests
                    SET state = ?,
                        claimed_from_state = ?,
                        lease_expires_at = ?,
                        retry_count = ?,
                        updated_at = ?
                    WHERE dedupe_key = ?
                    """,
                    (
                        PROCESSING_STATE,
                        claimed_from_state,
                        lease_expires_at.isoformat(),
                        retry_count,
                        current_time.isoformat(),
                        row["dedupe_key"],
                    ),
                )
                claimed_keys.append(str(row["dedupe_key"]))
            if not claimed_keys:
                return []
            # 重读认领后的行：返回条目须反映本次认领写入的 retry_count。
            placeholders = ",".join("?" for _ in claimed_keys)
            refreshed = connection.execute(
                f"""
                SELECT *
                FROM send_requests
                WHERE dedupe_key IN ({placeholders})
                ORDER BY created_at ASC, rowid ASC
                """,
                claimed_keys,
            ).fetchall()
        return self._entries_from_rows(refreshed, connection)

    # ---- 毒行隔离（评审 H9）------------------------------------------------
    # 90f590e 只给 _finalize_expired_lease 加了隔离，_entry_from_row 的两个
    # 调用点（claim_due 批量重读 / list_due / find_request）仍会让**单条**
    # request_json 损坏的行把整批已认领的行一起拖垮：claim_due 的事务此时
    # 已提交，行已变 processing，异常却让整批条目全部丢弃 → 队列周期性停摆
    # 且同批健康行从未投递。这里逐行解析并把坏行就地终态化。

    def _list_due_unlocked(
        self, connection: sqlite3.Connection, current_time: datetime, limit: int
    ) -> list[QueuedSendRequest]:
        """list_due 的裸查询体（调用方已完成加锁与建表）。"""
        cursor = connection.execute(
            """
            SELECT *
            FROM send_requests
            WHERE state IN (?, ?)
              AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY created_at ASC, rowid ASC
            LIMIT ?
            """,
                (
                    ReceiptState.QUEUED.value,
                    ReceiptState.FAILED_RETRYABLE.value,
                    current_time.isoformat(),
                    limit,
                ),
            )
        return self._entries_from_rows(cursor.fetchall(), connection)

    def _corrupt_row_kind(self, row: sqlite3.Row, exc: Exception) -> str:
        """区分「跨版本未知字段」与「结构真损坏」，供日志与审计归类。"""
        name = type(exc).__name__
        if name in {"ValidationError", "ValueError", "KeyError", "TypeError"}:
            return "unknown_field" if "Extra inputs" in str(exc) else "invalid_payload"
        return "invalid_payload"

    def _finalize_corrupt_row(
        self,
        row: sqlite3.Row,
        exc: Exception | None,
        current_time: datetime | None = None,
    ) -> None:
        """把无法解析的队列行就地置终态，避免它每轮都毒死整个批次。

        关键：**不要**在调用方那条共享连接上执行。该连接以 autocommit 模式
        创建（``isolation_level=None``），``BEGIN``/``commit``/``rollback`` 都是
        无效操作，DML 会留下一个隐式打开的事务——后果是终态化时隐时现、并把
        连接卡在怪异状态（实测：行停在 processing）。这里改用独立短连接，
        使隔离动作与调用方的连接状态彻底解耦。

        与非终态行永不被 _prune 淘汰的契约一致：置 FAILED_FINAL 后由既有
        A4 淘汰路径回收；不删除行，保留事后取证能力。
        """
        stamp = (current_time or _utc_now()).isoformat()
        dedupe_key = str(row["dedupe_key"])
        kind = "invalid_payload" if exc is None else self._corrupt_row_kind(row, exc)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    UPDATE send_requests
                    SET state = ?,
                        claimed_from_state = NULL,
                        lease_expires_at = NULL,
                        next_retry_at = NULL,
                        updated_at = ?
                    WHERE dedupe_key = ?
                    """,
                    (ReceiptState.FAILED_FINAL.value, stamp, dedupe_key),
                )
        except sqlite3.Error as db_exc:
            logging.getLogger(__name__).warning(
                "corrupt-row finalize failed dedupe_key=%s error=%s",
                dedupe_key,
                db_exc,
            )
        logging.getLogger(__name__).warning(
            "corrupt send-queue row skipped and finalized kind=%s dedupe_key=%s error=%s",
            kind,
            dedupe_key,
            type(exc).__name__ if exc is not None else "unknown",
        )

    def _entries_from_rows(
        self, rows: list[sqlite3.Row], connection: sqlite3.Connection
    ) -> list[QueuedSendRequest]:
        """逐行解析：坏行终态化后跳过，健康行照常返回（毒行隔离）。"""
        entries: list[QueuedSendRequest] = []
        for row in rows:
            try:
                entries.append(self._entry_from_row(row, connection))
            except _CorruptQueueRow as exc:
                self._finalize_corrupt_row(row, exc.cause)
        return entries

    def _finalize_expired_lease(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        retry_count: int,
        current_time: datetime,
    ) -> None:
        """租约反复过期的行达到 max_attempts 后置终态，不再交投。"""
        # §9.3 断点守卫：已有 part 送达且未全部完成时改置 PARTIAL（带扫描
        # 退避），租约循环烧完请求预算也不得整封盲重发。
        if self._convert_terminal_to_partial_in(
            connection, str(row["request_id"]), now=current_time
        ):
            logging.getLogger(__name__).warning(
                "expired-lease row deferred to partial breakpoint request_id=%s",
                row["request_id"],
            )
            return
        connection.execute(
            """
            UPDATE send_requests
            SET state = ?,
                claimed_from_state = NULL,
                lease_expires_at = NULL,
                next_retry_at = NULL,
                retry_count = ?,
                updated_at = ?
            WHERE dedupe_key = ?
            """,
            (
                ReceiptState.FAILED_FINAL.value,
                retry_count,
                current_time.isoformat(),
                row["dedupe_key"],
            ),
        )
        try:
            send_request = SendRequest.model_validate_json(str(row["request_json"]))
        except Exception:  # noqa: BLE001 - 毒行隔离（终审 Important）：request_json
            # 损坏时行已随上方 UPDATE 置终态，降级为日志——绝不让单条坏行把
            # 整个 claim_due 批次的认领事务拖到回滚停摆。
            logging.getLogger(__name__).warning(
                "expired-lease row finalized without audit (corrupt request_json)"
            )
            return
        receipt = DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=SQLITE_QUEUE_TRANSPORT,
            retry_count=retry_count,
            public_message="",
        )
        self._append_sender_audit(send_request, receipt, "send_failed_final")

    def _defer_for_bot_unavailable(
        self,
        connection: sqlite3.Connection,
        entry: QueuedSendRequest,
        issue: OperationalIssue,
        public_message: str,
        *,
        now: datetime,
    ) -> DeliveryReceipt:
        """B-4（管线检视 #6）：SnowLuma 断线的投递挂起，不消耗重试预算。

        bot_unavailable 是环境性暂态：照常计入 attempts 会让断线期间排队的
        回复在 ~3 分钟内烧完 max_attempts 后被 FAILED_FINAL 静默丢弃。这里
        只顺延下次尝试时间、不递增 retry_count（挂起至 bot 恢复，恢复后
        下一轮认领即投）；入队超过 bot_unavailable 年龄上限仍不可投才置
        终态，防止 A4 契约（非终态永不淘汰）下死挂行无限堆积。
        """
        hold_expired = (
            now - entry.created_at
        ).total_seconds() >= self._bot_unavailable_max_age_seconds
        if hold_expired:
            receipt = self._update_state_in(
                connection,
                entry.send_request,
                state=ReceiptState.FAILED_FINAL,
                retry_count=entry.retry_count,
                next_retry_at=None,
                public_message=public_message,
                now=now,
                operational_issue=issue,
            )
            event = "send_failed_final"
        else:
            next_retry_at = now + timedelta(
                seconds=max(
                    self.retry_base_seconds, _BOT_UNAVAILABLE_RETRY_DELAY_SECONDS
                )
            )
            receipt = self._update_state_in(
                connection,
                entry.send_request,
                state=ReceiptState.FAILED_RETRYABLE,
                retry_count=entry.retry_count,
                next_retry_at=next_retry_at,
                public_message=public_message,
                now=now,
                operational_issue=issue,
            )
            event = "send_deferred_bot_unavailable"
        self._append_sender_audit(entry.send_request, receipt, event)
        return receipt

    def mark_retryable_failure(
        self,
        request_id: str,
        public_message: str,
        *,
        now: datetime | None = None,
        operational_issue: OperationalIssue | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            # 审查 A-22：内联首投已走到终结口（无论成败）即释放认领台账，
            # 行交还既有重试/接管语义；「not found」分支也先释放防台账泄漏。
            self._release_inline_claim(request_id)
            entry = self._find_entry_in(connection, request_id)
            if entry is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )

            issue = operational_issue or entry.send_request.operational_issue
            public_message = "" if issue is not None else public_message
            if issue is not None and str(issue.kind) == _BOT_UNAVAILABLE_KIND:
                return self._defer_for_bot_unavailable(
                    connection, entry, issue, public_message, now=current_time
                )
            retry_count = entry.retry_count + 1
            if retry_count >= self.max_attempts:
                # §9.3 断点守卫：请求重试预算烧尽但有 part 已送达时改置
                # PARTIAL 断点（补偿扫描续发），不整封 FAILED_FINAL 盲重发。
                if self._convert_terminal_to_partial_in(
                    connection, request_id, now=current_time
                ):
                    receipt = DeliveryReceipt(
                        request_id=request_id,
                        state=ReceiptState.FAILED_FINAL,
                        transport=SQLITE_QUEUE_TRANSPORT,
                        retry_count=retry_count,
                        public_message="",
                        operational_issue=issue,
                    )
                    self._append_sender_audit(
                        entry.send_request, receipt, "send_deferred_partial"
                    )
                    return receipt
                receipt = self._update_state_in(
                    connection,
                    entry.send_request,
                    state=ReceiptState.FAILED_FINAL,
                    retry_count=retry_count,
                    next_retry_at=None,
                    public_message=public_message,
                    now=current_time,
                    operational_issue=issue,
                )
                event = "send_failed_final"
            else:
                next_retry_at = current_time + timedelta(
                    seconds=self._backoff_seconds(retry_count)
                )
                receipt = self._update_state_in(
                    connection,
                    entry.send_request,
                    state=ReceiptState.FAILED_RETRYABLE,
                    retry_count=retry_count,
                    next_retry_at=next_retry_at,
                    public_message=public_message,
                    now=current_time,
                    operational_issue=issue,
                )
                event = "send_failed_retryable"

        self._append_sender_audit(entry.send_request, receipt, event)
        return receipt

    def mark_sent(
        self,
        request_id: str,
        public_message: str = "sent",
        *,
        now: datetime | None = None,
        operational_issue: OperationalIssue | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            # 审查 A-22：内联首投成功即释放认领台账（行置 SENT 后 worker
            # 本就不可认领，释放只为台账生命周期与行状态一致）。
            self._release_inline_claim(request_id)
            entry = self._find_entry_in(connection, request_id)
            if entry is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )
            issue = operational_issue or entry.send_request.operational_issue
            public_message = "" if issue is not None else public_message
            receipt = self._update_state_in(
                connection,
                entry.send_request,
                state=ReceiptState.SENT,
                retry_count=entry.retry_count,
                next_retry_at=None,
                public_message=public_message,
                now=current_time,
                operational_issue=issue,
            )
        self._append_sender_audit(entry.send_request, receipt, "send_marked_sent")
        return receipt

    def mark_final_failure(
        self,
        request_id: str,
        public_message: str,
        *,
        now: datetime | None = None,
        operational_issue: OperationalIssue | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            # 审查 A-22：内联首投终败即释放认领台账（有已送达 part 时由
            # 下方断点守卫改置 PARTIAL，台账同样终结——内联已结束）。
            self._release_inline_claim(request_id)
            entry = self._find_entry_in(connection, request_id)
            if entry is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )
            issue = operational_issue or entry.send_request.operational_issue
            public_message = "" if issue is not None else public_message
            # §9.3 断点守卫：显式终态失败前，若已有 part 送达且未全部完成，
            # 改置 PARTIAL 断点由补偿扫描续发，绝不整封盲重发已送达内容。
            if self._convert_terminal_to_partial_in(
                connection, request_id, now=current_time
            ):
                receipt = DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    retry_count=entry.retry_count,
                    public_message="",
                    operational_issue=issue,
                )
                self._append_sender_audit(
                    entry.send_request, receipt, "send_deferred_partial"
                )
                return receipt
            receipt = self._update_state_in(
                connection,
                entry.send_request,
                state=ReceiptState.FAILED_FINAL,
                retry_count=entry.retry_count,
                next_retry_at=None,
                public_message=public_message,
                now=current_time,
                operational_issue=issue,
            )
        self._append_sender_audit(entry.send_request, receipt, "send_failed_final")
        return receipt

    # ---- §9.3 part 级幂等进度与 PARTIAL 断点 --------------------------------
    # 目标：长回复切成多个 part 后，每个 part 成功即落库；已 SENT 的 part 永不
    # 重发；结果未知的 part 记 UNKNOWN 走确认协议；有副作用又无法立即完成时
    # 请求行置 PARTIAL 终态+断点，由 claim_due 的补偿扫描续发剩余 part。
    # 所有写路径沿用共享连接单事务（WAL）惯例；part 明细表与请求行汇总列在同
    # 一事务内更新。

    def ensure_parts_planned(
        self,
        request_id: str,
        payload_digests: list[str],
        *,
        now: datetime | None = None,
    ) -> PartProgress | None:
        """首次 part 化发送前预写全部 PENDING part 行（幂等，ON CONFLICT 跳过）。

        只保存 payload 摘要，不保存用户正文副本（规格 §9.3.2）。请求行不存在
        或写入失败时返回 None，调用方降级为既有整发语义。
        """
        current_time = now or _utc_now()
        digests = list(payload_digests)
        if not digests:
            return None
        self._ensure_schema_once()
        try:
            with self._transaction() as connection:
                total = len(digests)
                for index, digest in enumerate(digests):
                    connection.execute(
                        """
                        INSERT INTO send_request_parts (
                            part_key,
                            request_id,
                            part_index,
                            parts_total,
                            state,
                            attempts,
                            payload_digest,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(part_key) DO NOTHING
                        """,
                        (
                            _part_key(request_id, index),
                            request_id,
                            index,
                            total,
                            PART_STATE_PENDING,
                            0,
                            digest,
                            current_time.isoformat(),
                        ),
                    )
                self._refresh_request_part_summary_in(connection, request_id, now=current_time)
                return self._load_part_progress_in(connection, request_id)
        except sqlite3.Error:
            logger = logging.getLogger(__name__)
            logger.warning(
                "part plan persist failed request_id=%s", request_id
            )
            return None

    def part_progress(self, request_id: str) -> PartProgress | None:
        """读取请求的 part 级进度快照（只读；无 part 跟踪时返回 None）。"""
        self._ensure_schema_once()
        with self._locked_connection() as connection:
            return self._load_part_progress_in(connection, request_id)

    def list_partial_requests(self, *, now: datetime | None = None) -> list[QueuedSendRequest]:
        """PARTIAL 断点行的运维/测试视图（含休眠行，供人工确认与排查）。"""
        del now  # 保持签名稳定：扫描不依赖时间，断点行无论是否可调度都可见。
        self._ensure_schema_once()
        with self._locked_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM send_requests
                WHERE state = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (PARTIAL_ROW_STATE,),
            ).fetchall()
            return self._entries_from_rows(rows, connection)

    def mark_part_attempt(
        self,
        request_id: str,
        part_index: int,
        *,
        now: datetime | None = None,
    ) -> bool:
        """发送前原子写入：state→PENDING 且 attempts+1（规格 §9.3.3）。

        崩溃在写入后、dispatch 前只会多计一次尝试（保守方向，受 attempts
        上限约束），绝不会漏记「可能已在平台侧送达」的事实。
        """
        return self._update_part_row(
            request_id,
            part_index,
            state=PART_STATE_PENDING,
            increment_attempts=True,
            now=now,
        )

    def mark_part_sent(
        self,
        request_id: str,
        part_index: int,
        *,
        provider_message_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        return self._update_part_row(
            request_id,
            part_index,
            state=PART_STATE_SENT,
            provider_message_id=provider_message_id,
            now=now,
        )

    def mark_part_unknown(
        self,
        request_id: str,
        part_index: int,
        *,
        error_kind: str | None = None,
        provider_message_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """结果未知（超时/断连/无法判定）：记 UNKNOWN，绝不静默当失败盲重发。"""
        return self._update_part_row(
            request_id,
            part_index,
            state=PART_STATE_UNKNOWN,
            last_error_kind=error_kind,
            provider_message_id=provider_message_id,
            now=now,
        )

    def mark_part_failed_final(
        self,
        request_id: str,
        part_index: int,
        *,
        error_kind: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """平台明确拒绝且不可重试（如 403）：该 part 终态，不回 PENDING。"""
        return self._update_part_row(
            request_id,
            part_index,
            state=PART_STATE_FAILED_FINAL,
            last_error_kind=error_kind,
            now=now,
        )

    def mark_part_pending(
        self,
        request_id: str,
        part_index: int,
        *,
        now: datetime | None = None,
    ) -> bool:
        """明确可重试的失败（或确认「未送达」的 UNKNOWN）回到 PENDING。"""
        return self._update_part_row(
            request_id,
            part_index,
            state=PART_STATE_PENDING,
            now=now,
        )

    def _update_part_row(
        self,
        request_id: str,
        part_index: int,
        *,
        state: str,
        increment_attempts: bool = False,
        last_error_kind: str | None = None,
        provider_message_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    """
                    SELECT parts_total
                    FROM send_request_parts
                    WHERE part_key = ?
                    """,
                    (_part_key(request_id, part_index),),
                ).fetchone()
                if row is None:
                    return False
                assignments = ["state = ?", "updated_at = ?"]
                params: list[object] = [state, current_time.isoformat()]
                if increment_attempts:
                    assignments.append("attempts = attempts + 1")
                if last_error_kind is not None:
                    assignments.append("last_error_kind = ?")
                    params.append(last_error_kind)
                if provider_message_id is not None:
                    assignments.append("provider_message_id = ?")
                    params.append(provider_message_id)
                params.extend([request_id, part_index])
                connection.execute(
                    f"""
                    UPDATE send_request_parts
                    SET {", ".join(assignments)}
                    WHERE request_id = ? AND part_index = ?
                    """,
                    params,
                )
                self._refresh_request_part_summary_in(
                    connection, request_id, now=current_time
                )
            return True
        except sqlite3.Error:
            logging.getLogger(__name__).warning(
                "part state persist failed request_id=%s part_index=%s state=%s",
                request_id,
                part_index,
                state,
            )
            return False

    def _refresh_request_part_summary_in(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        *,
        now: datetime,
    ) -> None:
        """把 part 明细表汇总进请求行列（同事务；必须在调用方事务内执行）。"""
        rows = connection.execute(
            """
            SELECT part_index, parts_total, state
            FROM send_request_parts
            WHERE request_id = ?
            ORDER BY part_index ASC
            """,
            (request_id,),
        ).fetchall()
        if not rows:
            return
        total = max(int(row["parts_total"]) for row in rows)
        delivered = sum(1 for row in rows if str(row["state"]) == PART_STATE_SENT)
        progress_json = json.dumps(
            {str(row["part_index"]): str(row["state"]) for row in rows},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        connection.execute(
            """
            UPDATE send_requests
            SET parts_total = ?,
                parts_delivered = ?,
                parts_progress = ?,
                updated_at = ?
            WHERE request_id = ?
            """,
            (
                total,
                delivered,
                progress_json,
                now.isoformat(),
                request_id,
            ),
        )

    def _load_part_progress_in(
        self,
        connection: sqlite3.Connection,
        request_id: str,
    ) -> PartProgress | None:
        """在调用方连接上读取 part 进度（事务内/持锁读均可，RLock 可重入）。"""
        rows = connection.execute(
            """
            SELECT part_index, parts_total, state, attempts, last_error_kind,
                   provider_message_id, payload_digest
            FROM send_request_parts
            WHERE request_id = ?
            ORDER BY part_index ASC
            """,
            (request_id,),
        ).fetchall()
        if not rows:
            return None
        records: dict[int, PartRecord] = {}
        total = 1
        for row in rows:
            index = int(row["part_index"])
            total = max(total, index + 1, int(row["parts_total"]))
            records[index] = PartRecord(
                part_index=index,
                state=str(row["state"]),
                attempts=int(row["attempts"]),
                last_error_kind=(
                    str(row["last_error_kind"])
                    if row["last_error_kind"] is not None
                    else None
                ),
                provider_message_id=(
                    str(row["provider_message_id"])
                    if row["provider_message_id"] is not None
                    else None
                ),
                payload_digest=(
                    str(row["payload_digest"])
                    if row["payload_digest"] is not None
                    else None
                ),
            )
        return PartProgress(total=total, records=records)

    def mark_partial(
        self,
        request_id: str,
        *,
        resumable: bool = True,
        now: datetime | None = None,
        operational_issue: OperationalIssue | None = None,
    ) -> DeliveryReceipt:
        """置 PARTIAL 终态+断点：有已送达 part 但无法立即全部完成。

        resumable=True 时带 90s 补偿扫描退避（下轮 claim_due 扫描续发/确认）；
        resumable=False（本轮零进展：无可续发 part 且确认无变化）时休眠
        （next_retry_at=NULL），仍可经 list_partial_requests 检视或人工推进。
        """
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            # 审查 A-22：PARTIAL 收敛属于 worker 投递侧终结口，顺手释放
            # 认领台账（内联路径不会产生 PARTIAL，防御性对齐生命周期）。
            self._release_inline_claim(request_id)
            entry = self._find_entry_in(connection, request_id)
            if entry is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )
            issue = operational_issue or entry.send_request.operational_issue
            next_retry_at = (
                current_time + timedelta(seconds=_PARTIAL_RESUME_BACKOFF_SECONDS)
                if resumable
                else None
            )
            connection.execute(
                """
                UPDATE send_requests
                SET state = ?,
                    claimed_from_state = NULL,
                    lease_expires_at = NULL,
                    next_retry_at = ?,
                    last_public_message = '',
                    updated_at = ?
                WHERE request_id = ?
                """,
                (
                    PARTIAL_ROW_STATE,
                    next_retry_at.isoformat() if next_retry_at is not None else None,
                    current_time.isoformat(),
                    request_id,
                ),
            )
            receipt = DeliveryReceipt(
                request_id=request_id,
                state=ReceiptState.FAILED_FINAL,
                transport=SQLITE_QUEUE_TRANSPORT,
                retry_count=entry.retry_count,
                next_retry_at=next_retry_at,
                public_message="",
                operational_issue=issue,
            )
        self._append_sender_audit(entry.send_request, receipt, "send_deferred_partial")
        return receipt

    def _convert_terminal_to_partial_in(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        *,
        now: datetime,
    ) -> bool:
        """FAILED_FINAL 前的断点守卫：0<已送达<总数 时改写 PARTIAL。

        在调用方事务内执行；返回 True 表示调用方应跳过 FAILED_FINAL 写入
        （PARTIAL 断点已落库，由补偿扫描续发，绝不整封盲重发）。
        """
        progress = self._load_part_progress_in(connection, request_id)
        if progress is None or progress.total <= 0:
            return False
        if not 0 < progress.delivered < progress.total:
            return False
        next_retry_at = now + timedelta(seconds=_PARTIAL_RESUME_BACKOFF_SECONDS)
        connection.execute(
            """
            UPDATE send_requests
            SET state = ?,
                claimed_from_state = NULL,
                lease_expires_at = NULL,
                next_retry_at = ?,
                updated_at = ?
            WHERE request_id = ?
            """,
            (
                PARTIAL_ROW_STATE,
                next_retry_at.isoformat(),
                now.isoformat(),
                request_id,
            ),
        )
        return True

    def safe_summary(self) -> dict[str, int]:
        self._ensure_schema_once()
        summary = {
            ReceiptState.QUEUED.value: 0,
            ReceiptState.FAILED_RETRYABLE.value: 0,
            ReceiptState.FAILED_FINAL.value: 0,
            ReceiptState.SENT.value: 0,
            ReceiptState.SKIPPED.value: 0,
            PROCESSING_STATE: 0,
            PARTIAL_ROW_STATE: 0,
        }
        with self._locked_connection() as connection:
            cursor = connection.execute(
                """
                SELECT state, COUNT(*) AS count
                FROM send_requests
                GROUP BY state
                """
            )
            for row in cursor.fetchall():
                state = str(row["state"])
                if state in summary:
                    summary[state] = int(row["count"])
        return summary

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            # WAL：订阅推送并发读写场景减少 busy；切换失败（如网络盘不支持）
            # 降级为默认 journal 模式，不致命。
            try:
                connection.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS send_requests (
                    dedupe_key TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    retry_count INTEGER NOT NULL,
                    next_retry_at TEXT,
                    claimed_from_state TEXT,
                    lease_expires_at TEXT,
                    last_public_message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    session_id TEXT
                )
                """
            )
            # 审查 A-20（worker 侧）：per-session 串行化需要 SQL 层可比较的
            # session_id 列（session_id 在 request_json 里，纯 SQL 无法用
            # JSON1 之外的廉价手段取值；落列后 claim 的同会话互斥才可索引）。
            self._ensure_column(
                connection,
                "send_requests",
                "session_id",
                "TEXT",
            )
            self._backfill_session_id(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_send_requests_session_state
                ON send_requests (session_id, state)
                """
            )
            self._ensure_column(
                connection,
                "send_requests",
                "claimed_from_state",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "send_requests",
                "lease_expires_at",
                "TEXT",
            )
            # §9.3 请求行 part 级进度扩展：total/delivered 汇总 + 逐 part 状态
            # JSON 镜像（{"0":"sent",...}）。权威逐 part 明细在 send_request_parts
            # 伴生表，请求行列只是同事务内写入的廉价读视图。
            self._ensure_column(
                connection,
                "send_requests",
                "parts_total",
                "INTEGER",
            )
            self._ensure_column(
                connection,
                "send_requests",
                "parts_delivered",
                "INTEGER",
            )
            self._ensure_column(
                connection,
                "send_requests",
                "parts_progress",
                "TEXT",
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS send_request_parts (
                    part_key TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    part_index INTEGER NOT NULL,
                    parts_total INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    last_error_kind TEXT,
                    provider_message_id TEXT,
                    payload_digest TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_send_request_parts_request
                ON send_request_parts (request_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_send_requests_request_id
                ON send_requests (request_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_send_requests_state_due
                ON send_requests (state, next_retry_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_send_requests_processing_lease
                ON send_requests (state, lease_expires_at)
                """
            )

    def _backfill_session_id(self, connection: sqlite3.Connection) -> None:
        """审查 A-20：存量行回填 session_id（迁移前行没有该列）。

        从 request_json 提取（JSON1，SQLite>=3.38 默认内置）；request_json
        损坏的行由 json_valid 过滤，绝不因回填扩大毒行影响面。SQLite 无
        JSON1 时静默跳过——旧行退回既有行为（不参与同会话互斥），不致命。
        """
        try:
            connection.execute(
                """
                UPDATE send_requests
                SET session_id = json_extract(request_json, '$.session_id')
                WHERE session_id IS NULL
                  AND json_valid(request_json)
                  AND json_extract(request_json, '$.session_id') IS NOT NULL
                """
            )
        except sqlite3.Error:
            return

    def _connect(self) -> sqlite3.Connection:
        # timeout：写锁被占时最多等 5s 再报 busy，避免默认语义下偶发立即失败。
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
            )

    def _prune(self, connection: sqlite3.Connection) -> None:
        # 只淘汰终态行（死信不堆积）：非终态（QUEUED/PROCESSING/
        # FAILED_RETRYABLE）是待投递或在途消息，被容量/时间序挤掉等于
        # 静默丢消息，故永不淘汰（A4 契约：宁可表超限也不丢在途）。
        connection.execute(
            """
            DELETE FROM send_requests
            WHERE state IN (?, ?, ?)
              AND dedupe_key NOT IN (
                SELECT dedupe_key
                FROM send_requests
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
            )
            """,
            (
                ReceiptState.SENT.value,
                ReceiptState.FAILED_FINAL.value,
                ReceiptState.SKIPPED.value,
                self.max_items,
            ),
        )
        self._warn_if_over_soft_ceiling(connection)

    def _warn_if_over_soft_ceiling(
        self, connection: sqlite3.Connection
    ) -> None:
        """A4 契约不丢在途消息，但超限必须可观测：超过 8×max_items 告警一次。"""
        row = connection.execute(
            "SELECT COUNT(*) FROM send_requests"
        ).fetchone()
        total = int(row[0]) if row is not None else 0
        ceiling = max(1, self.max_items) * 8
        if total > ceiling:
            if not getattr(self, "_soft_ceiling_warned", False):
                self._soft_ceiling_warned = True
                logging.getLogger(__name__).warning(
                    "send queue over soft ceiling rows=%s max_items=%s "
                    "(in-flight rows are protected by A4, check worker health)",
                    total,
                    self.max_items,
                )
        else:
            self._soft_ceiling_warned = False

    def _find_entry_by_request_id(self, request_id: str) -> QueuedSendRequest | None:
        self._ensure_schema_once()
        with self._locked_connection() as connection:
            return self._find_entry_in(connection, request_id)

    def _find_entry_in(
        self, connection: sqlite3.Connection, request_id: str
    ) -> QueuedSendRequest | None:
        row = connection.execute(
            """
            SELECT *
            FROM send_requests
            WHERE request_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return self._entry_from_row(row, connection)
        except _CorruptQueueRow as exc:
            self._finalize_corrupt_row(row, exc.cause)
            return None

    def _entry_from_row(
        self, row: sqlite3.Row, connection: sqlite3.Connection
    ) -> QueuedSendRequest:
        """把队列行还原为条目；坏行统一抛 ``_CorruptQueueRow`` 供调用方隔离。

        解析失败（跨版本未知字段 / request_json 损坏 / 时间戳非法）在这里被
        包成固定类型的哨兵异常：调用方据此把该行就地终态化并**跳过**，而不是
        让单条坏行把整批已认领的消息一起丢弃。
        """
        try:
            raw_state = str(row["state"])
            if raw_state == PARTIAL_ROW_STATE:
                # 'partial' 不是 ReceiptState 成员：对外投影为 FAILED_FINAL
                # （终态语义一致）；part 级断点经 entry.parts 供 worker 续发。
                public_state = ReceiptState.FAILED_FINAL.value
            else:
                public_state = (
                    str(row["claimed_from_state"])
                    if raw_state == PROCESSING_STATE and row["claimed_from_state"] is not None
                    else raw_state
                )
            # 建表/迁移后 SELECT * 必含 parts_total 列；极端损坏场景由外层
            # _CorruptQueueRow 兜底隔离。
            parts_total = row["parts_total"]
            parts = self._load_part_progress_in(connection, str(row["request_id"]))
            if parts_total is not None and int(parts_total) > 0 and parts is None:
                # part 明细丢失但请求行声明了分片：进度不可信，按毒行隔离
                # （终态化，绝不整封盲重发——防重复投递优先）。
                raise ValueError("part progress missing for chunked request")
            return QueuedSendRequest(
                send_request=SendRequest.model_validate_json(str(row["request_json"])),
                state=ReceiptState(public_state),
                retry_count=int(row["retry_count"]),
                next_retry_at=(
                    datetime.fromisoformat(str(row["next_retry_at"]))
                    if row["next_retry_at"] is not None
                    else None
                ),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
                lease_expires_at=(
                    datetime.fromisoformat(str(row["lease_expires_at"]))
                    if row["lease_expires_at"] is not None
                    else None
                ),
                parts=parts,
            )
        except Exception as exc:
            raise _CorruptQueueRow(
                f"unparsable queue row dedupe_key={row['dedupe_key']}", cause=exc
            ) from exc

    def _update_state_in(
        self,
        connection: sqlite3.Connection,
        send_request: SendRequest,
        *,
        state: ReceiptState,
        retry_count: int,
        next_retry_at: datetime | None,
        public_message: str,
        now: datetime,
        operational_issue: OperationalIssue | None = None,
    ) -> DeliveryReceipt:
        """在调用方事务内更新行状态（mark_* 的单事务写路径）。"""
        issue = operational_issue or send_request.operational_issue
        public_message = "" if issue is not None else public_message
        persisted_request = (
            send_request.model_copy(update={"operational_issue": issue})
            if issue is not send_request.operational_issue
            else send_request
        )
        connection.execute(
            """
            UPDATE send_requests
            SET state = ?,
                request_json = ?,
                retry_count = ?,
                next_retry_at = ?,
                claimed_from_state = NULL,
                lease_expires_at = NULL,
                last_public_message = ?,
                updated_at = ?
            WHERE request_id = ?
            """,
            (
                state.value,
                persisted_request.model_dump_json(),
                retry_count,
                next_retry_at.isoformat() if next_retry_at is not None else None,
                public_message,
                now.isoformat(),
                send_request.request_id,
            ),
        )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=state,
            transport=SQLITE_QUEUE_TRANSPORT,
            retry_count=retry_count,
            next_retry_at=next_retry_at,
            public_message=public_message,
            operational_issue=issue,
        )

    def _backoff_seconds(self, retry_count: int) -> int:
        exponent = max(0, retry_count - 1)
        return min(
            self.retry_max_seconds,
            self.retry_base_seconds * (2**exponent),
        )

    def _append_sender_audit(
        self,
        send_request: SendRequest,
        receipt: DeliveryReceipt,
        event: str,
    ) -> None:
        self.audit_logger.append(
            AuditRecord(
                request_id=send_request.request_id,
                session_id=send_request.session_id,
                capability_id=send_request.capability_id,
                stage="sender",
                event=event,
                severity=send_request.content.risk_level,
                public_message=receipt.public_message,
                private_debug=(
                    f"transport={receipt.transport} "
                    f"state={receipt.state.value} retry_count={receipt.retry_count}"
                ),
            )
        )


def build_send_queue(
    config: Config,
    audit_logger: AuditRepository,
) -> InMemorySendQueue | SQLiteSendRequestQueue:
    enabled = bool(getattr(config, "bot_send_queue_enabled", False))
    db_path = str(getattr(config, "bot_send_queue_db_path", "")).strip()
    if enabled and db_path:
        return SQLiteSendRequestQueue(
            db_path,
            audit_logger=audit_logger,
            max_items=int(getattr(config, "bot_send_queue_max_items", 1000)),
            max_attempts=int(getattr(config, "bot_send_queue_max_attempts", 3)),
            retry_base_seconds=int(
                getattr(config, "bot_send_queue_retry_base_seconds", 30)
            ),
            retry_max_seconds=int(
                getattr(config, "bot_send_queue_retry_max_seconds", 300)
            ),
            bot_unavailable_max_age_seconds=float(
                getattr(config, "bot_send_bot_unavailable_max_age_seconds", 1800.0)
            ),
        )
    return InMemorySendQueue(audit_logger=audit_logger)

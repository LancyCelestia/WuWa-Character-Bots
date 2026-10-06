from __future__ import annotations

import asyncio
import hashlib
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
#   半态）。
# 心跳覆盖面口径修正（SEAT-ATK-QUEUE Q-G2/Q-G3，2026-09-27）：
#   * 仅 part 跟踪行（chunks/mixed）在投递**期间**有逐次心跳——每个 part 尝试
#     都经 mark_part_attempt→_refresh_request_part_summary_in 推进 updated_at；
#     整发行（无 part 行）投递期间 updated_at 不推进，其心跳只有 claim 写入与
#     投递结束的 mark_* 两拍。窗内误杀整发行要求「无租约且从认领起心跳静默
#     ≥5 分钟」，即一次投递耗时超窗——属进程级病态，与 _inline_claims 台账对
#     永久悬挂的处理口径一致（防重复投递优先于防漏发）。
#   * 「同一 pass 内击穿 300s 窗」的原语漏洞已修：worker 一个 pass 只在开头取
#     一次 now，旧版所有状态写原样回写这枚 pass-start 时刻 → 刚写入的心跳可以
#     是 5 分钟前的。现所有 updated_at 写统一经 _heartbeat_iso()：取
#     max(注入时刻, 墙钟)，注入的未来值照旧生效（测试确定性不破），过去/陈旧
#     值被墙钟顶起（心跳永不吃旧）。租约与 next_retry_at 仍按注入时刻计算。
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
# VIS（2026-10-06 澜汐裁定「发丢了没人喊是最贵的一种坏」）：**被年龄闸判死刑**
# 那一臂的告警代号（真身＝本常量，两面人话在册：`alerts._KIND_PLAIN` 与
# `error_report._ISSUE_REASON_LABELS`；缺登记时走既有兜底句，不另开通道）。
# 为什么换代号而不是照抄 `bot_unavailable`：worker 的告警腿
# （`worker._notify_operational_issue_safely`，R2 2026-09-17）对
# `kind=="bot_unavailable"` 一律只留 DEBUG、不打管理员告警——那句防的是「启动期
# 成批挂起逐条骚扰管理员」，判据吃的是**挂起**语义；而行被本臂写成终态后既不再
# 被认领也不会自动补发，再套同一句静默就等于「71 条消息没了、没有任何出口说过
# 一句」（真机验收事故原形，全账 §76.20）。
# 🔴 只换**返回回执**里的那一枚 issue：盘上 `request_json` 落的仍是挂起代号
# （`_update_state_in` 收到的还是传进来的原 issue），事后取证面逐字不变；
# 认领判据/重试预算/终态判定/幂等键形一律未动；抑制走装配现场那枚
# `operational_alert_suppression`（`AdminAlertSuppression`，缺省 300s），不自造节流。
_BOT_UNAVAILABLE_DROP_KIND = "send_queue_dropped_bot_unavailable"
# Q-G7（SEAT-ATK-QUEUE）休眠 PARTIAL 永久停摆的收口三件（S-FIX-QPARK 补丁）：
# ① mark_partial(resumable=False) 不再写 next_retry_at=NULL 的永久死档——
#   「无可推进 PENDING part（且 attempts 未烧尽）」的行直接终态化 FAILED_FINAL
#   （可被 _prune 剪、part 明细账保留供取证）；「还有可推进 part」的行强制回
#   补偿退避（视同 resumable，绝不静默停放）。原则一句话：宁漏不双发不等于
#   宁停不报。
# ② 告警行（admin_alert_card/bot.alert/bot.error_report/admin_alert 标记）
#   自身就是告警链载体，任何形态的休眠档都不许落在它们身上。
# ③ 补丁上线前已存在的休眠行（生产 P2 名册 10 枚）由 _prune 顶部按 TTL 扫成
#   终态——只终态化、绝不重投。
_DORMANT_PARTIAL_SWEEP_SECONDS = 7 * 86400.0
# 告警行身份三源（任一命中即算，见 _is_alert_send_request）：capability 登记、
# 键形前缀、审计标签。键形前缀对齐 alerts.build_admin_alert_card_send_request
# （admin_alert_card:*）与管线告警能力键形（bot.alert:*）。
_ALERT_CAPABILITY_IDS = frozenset({"bot.alert", "bot.error_report"})
_ALERT_DEDUPE_PREFIXES = ("admin_alert_card:", "bot.alert:")
_ALERT_AUDIT_TAGS = frozenset({"admin_alert"})


class PartLedgerConflictError(Exception):
    """Q-G5：part 账本守卫拒绝复用——同一行身份下已存的 part 行 payload_digest
    与本次规划不一致（或旧无主账本无法安全收养）。调用方（worker）绝不可
    因此回落整发（已送达 part 会被重发），只能按 result_unknown 收口。"""


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


def _heartbeat_iso(now: datetime) -> str:
    """心跳列（updated_at）专用时间戳：max(调用方注入时刻, 墙钟)。

    Q-G3（SEAT-ATK-QUEUE）：worker 一个 pass 只在开头取一次 now，旧版所有
    状态写原样回写这枚 pass-start 时刻——长 pass（批量×分片×超时）里刚发生
    的写入会盖上几分钟前的戳，300s 缺席判据可在同一 pass 被击穿。现心跳只准
    前进不准吃旧值：注入的未来值照旧生效（保持测试确定性），过去/陈旧值被
    墙钟顶起。注意只用于 updated_at——租约与 next_retry_at 仍按注入时刻计算，
    不改调度语义。naive 注入值不比较墙钟（无法安全取 max），原样落盘。
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        return now.isoformat()
    wall = _utc_now()
    return max(now, wall).isoformat()


def _part_identity_token(dedupe_key: str) -> str:
    """行身份 → part_key 后缀（sha256[:16]）。dedupe_key 可含任意字符
    （冒号/井号皆有可能），故不裸拼原文，用摘要定长段，杜绝分隔符歧义。"""
    return hashlib.sha256(str(dedupe_key).encode("utf-8")).hexdigest()[:16]


def _part_key(request_id: str, part_index: int, dedupe_key: str | None = None) -> str:
    """规格 §9.3.1：part 稳定键 = 请求身份 + part_index，重试不换键。

    Q-G5（SEAT-ATK-QUEUE）：旧键只含 request_id，而同 request_id 可以有多行
    （error_report ack/card 共键设计，审查 E-12）⇒ 兄弟行共用一本 part 账，
    B 一条没发账上已全送达。现键带行身份（dedupe_key 摘要段）。
    ``dedupe_key=None``＝无主旧账格式（仅用于寻址升级前遗留行），新写入一律
    传身份。part_key 此后只当不透明主键用；检索一律走
    (request_id, dedupe_key, part_index)。
    """
    if dedupe_key is None:
        return f"{request_id}#part{int(part_index)}"
    return f"{request_id}#part{int(part_index)}#{_part_identity_token(dedupe_key)}"


def _is_alert_send_request(send_request: SendRequest) -> bool:
    """该行是否告警链成员（Q-G7 ②，三源任一命中即算）。

    生产 P2 名册 10 枚 parked 里 5 枚是 admin_alert_card、3 枚是 bot.alert —
    告警自己失踪是最坏形状，故这类行绝不许进永久休眠档。"""
    if send_request.capability_id in _ALERT_CAPABILITY_IDS:
        return True
    dedupe_key = str(send_request.dedupe_key or "")
    if dedupe_key.startswith(_ALERT_DEDUPE_PREFIXES):
        return True
    return bool(_ALERT_AUDIT_TAGS.intersection(send_request.audit_tags))


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
    # Q-G1（SEAT-ATK-QUEUE）：行主键 dedupe_key（行身份）。payload 里的
    # dedupe_key 在历史共键覆写行（生产 7 行实锤）上可能与行主键不等值，
    # 写路径一律以此为准；旧构造方（内存路径/测试直构）缺省 None → 回退
    # payload 值。
    row_dedupe_key: str | None = None


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
        # 审查 A-22：进程内联认领台账（dedupe_key → (request_id, 提交任务)）。
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
        # Q-G6（SEAT-ATK-QUEUE）：键从 request_id 改为行身份 dedupe_key——
        # 旧形状「一槽一任务」下兄弟行互相顶槽（后登记的顶掉前任），且任一
        # 终结口整槽清空 ⇒ 前任仍在途已失去 A-22 保护（防双发盾失效）。
        # 现每行一槽互不顶替；释放只精准清自己的槽（显式身份）或本任务在
        # 该 request_id 下自持的槽（内联 legacy 口）。
        self._inline_claims: dict[str, tuple[str, asyncio.Task[None]]] = {}

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

    def close(self) -> None:
        """显式收尾口：释放 B-10 单条长连接（生产无人调用＝语义零改动）。

        供临时目录/测试等「实例随目录销毁」的调用方在清理前关闭句柄——
        Windows 上打开的 sqlite 文件不可 unlink（WinError 32）。
        """
        self._discard_connection()

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

    # ---- 审查 A-22：内联首投认领台账（行身份键） ----------------------------
    # 竞态窗口论证：内联首投（handler 协程）与 worker 投递（调度任务）是两个
    # 无共享同步原语的并发投递者，原先只靠 next_retry_at 时间错开——内联耗时
    # 超过宽限期（多分片×传输超时、事件循环停顿）即双发。台账以「提交任务
    # 是否终结」为在途信号：任务存活=内联仍持行；任务终结（正常路径必经
    # mark_* 四口之一，异常/取消路径由死认领清簿兜底）=行可被 worker 接管。
    # 所有读写都在 _connection_lock（RLock）临界区内，与既有锁序一致。
    # Q-G6（SEAT-ATK-QUEUE）：槽键从 request_id 改为行身份 dedupe_key——旧
    # 「一槽一任务」形状下，共 request_id 的兄弟行后登记的顶掉前任，且任一
    # 终结口整槽清空 ⇒ 前任仍在 await 传输却已失去 A-22 保护。现每行一槽、
    # 释放只精准清自己（显式身份或本任务自持槽），互不顶替。

    def _register_inline_claim(self, send_request: SendRequest) -> None:
        """登记内联首投认领（dedupe_key → (request_id, 提交任务)）；仅事件
        循环内调用生效（须在连接锁临界区内）。

        线程提交（无运行中事件循环）不登记：退回纯时间宽限=既有语义。
        """
        try:
            task = asyncio.current_task()
        except RuntimeError:  # 无事件循环（如后台渲染线程提交）
            return
        if task is None:
            return
        self._inline_claims[send_request.dedupe_key] = (send_request.request_id, task)

    def _release_inline_claim(
        self, request_id: str, dedupe_key: str | None = None
    ) -> None:
        """释放内联认领（mark_* 终结口调用；须在连接锁临界区内）。

        - 携带行身份（显式 dedupe_key 或终结口解析所得）：只清自己那一槽。
        - 无身份（legacy 口，如根装配 `mark_sent(request_id)`）：按调用任务
          精准释放——只清「本任务以该 request_id 登记」的槽；兄弟任务的槽
          原样保留（那正是 A-22 要保的在途保护）。线程内调用无法归属调用者，
          不猜——死认领槽由 claim_due 惰性清簿兜底（既有语义）。
        """
        if dedupe_key is not None:
            entry = self._inline_claims.get(dedupe_key)
            if entry is not None and entry[0] == request_id:
                self._inline_claims.pop(dedupe_key, None)
            return
        try:
            task = asyncio.current_task()
        except RuntimeError:
            task = None
        if task is None:
            return
        for key, (stored_rid, stored_task) in list(self._inline_claims.items()):
            if stored_rid == request_id and stored_task is task:
                self._inline_claims.pop(key, None)

    def _inline_claim_identity_for_caller(self, request_id: str) -> str | None:
        """Q-G1 内联精准寻址：无显式 dedupe_key 的 mark_* 调用先问台账——
        当前任务若正是该 request_id 某槽的提交任务，返回其行身份。

        生产内联链（根装配 `_record_transport_receipt`，本席禁改）只传
        request_id；共 request_id 的兄弟行在「取最新一行」启发式下可能拿错。
        台账登记发生于 submit、与任务同体，是该调用「想终结哪一行」的权威
        答案（同一协程 submit → transport → mark_* 序列）。
        """
        try:
            task = asyncio.current_task()
        except RuntimeError:
            return None
        if task is None:
            return None
        for key, (stored_rid, stored_task) in self._inline_claims.items():
            if stored_rid == request_id and stored_task is task:
                return key
        return None

    def _inline_claim_blocks(
        self, dedupe_key: str, claimer: asyncio.Task[None] | None
    ) -> bool:
        """该行的内联认领是否否决本次认领（须在连接锁临界区内）。

        - 无台账条目：不否决（正常 worker 认领/跨重启恢复路径）。
        - 条目任务已终结：死认领（取消/异常未及 mark_*）→ 清簿放行，保住
          「内联丢失后 worker 接管」的恢复语义。
        - 条目任务存活且认领者就是提交任务本人（同一协程 submit 后自行
          drain，如测试/顺序管线）：不否决——单协程内天然串行，不存在
          跨任务竞态；跨任务认领者（生产 worker）被否决，这正是 A-22 目标。
        """
        entry = self._inline_claims.get(dedupe_key)
        if entry is None:
            return False
        _, task = entry
        if task.done():
            self._inline_claims.pop(dedupe_key, None)
            return False
        return task is not claimer

    def _inline_claim_alive(self, dedupe_key: str) -> bool:
        """僵尸清扫前的存活探测：有任务正内联持有该行 → 不许终态化。

        与 _inline_claim_blocks 不同，本探测不清簿（清扫不是认领）。
        """
        entry = self._inline_claims.get(dedupe_key)
        if entry is None:
            return False
        return not entry[1].done()

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
                    session_id,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    # Q-G4：行级投递期限落列（claim 认领口与僵尸清扫的执法点）。
                    (
                        send_request.expires_at.isoformat()
                        if send_request.expires_at is not None
                        else None
                    ),
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
                # Q-G6：登记键＝行身份 dedupe_key（兄弟行各占各槽）。
                if deliver_after is None:
                    self._register_inline_claim(send_request)

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
            # Q-G4（SEAT-ATK-QUEUE）：僵尸 processing 行清扫先于一切认领。
            self._finalize_zombie_processing_rows(connection, current_time)
            # 审查 A-20（worker 侧）per-session 串行化：同会话已有在途认领
            # （state='processing' 且租约未过期）时，该会话的其余到期行不得
            # 进入本批候选——投递顺序只能在认领口保证，投递侧锁无法约束
            # 并发认领者。租约已过期的 processing 行视为死认领，不阻塞同
            # 会话（崩溃恢复场景顺序本已不可保，但队列不得因此停摆）；
            # rowid<>self 排除自身，让本行的租约过期重认领照常进行。
            # session_id IS NULL 的存量行（迁移前/毒行）不参与互斥，行为与
            # 既有语义一致。
            # Q-G4：两条 PROCESSING 臂都加 expires_at 门（NULL=未声明期限，
            # 照旧可重认领）——过期行绝不作为新任务重投。
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
                        AND (expires_at IS NULL OR expires_at > ?)
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
                        AND (expires_at IS NULL OR expires_at > ?)
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
                    current_time.isoformat(),
                    PARTIAL_ROW_STATE,
                    current_time.isoformat(),
                    PROCESSING_STATE,
                    dead_lease_cutoff,
                    current_time.isoformat(),
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
                # Q-G6：否决判据按行身份查自己的槽，兄弟行不再互相顶替。
                if self._inline_claim_blocks(str(row["dedupe_key"]), claimer_task):
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
                        # Q-G3：心跳只前进不吃旧（注入的未来值照旧生效）。
                        _heartbeat_iso(current_time),
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
            # F-4（SEAT-ATK-SENDQ，2026-09-27）：条目重建回同一事务内——
            # `_entries_from_rows` 里的 part 进度 SELECT 若在事务外跑，会与
            # 他线程 BEGIN 交错、读到未提交态（对方回滚＝幻影进度）。
            return self._entries_from_rows(refreshed, connection, in_transaction=True)

    def _finalize_zombie_processing_rows(
        self, connection: sqlite3.Connection, current_time: datetime
    ) -> None:
        """Q-G4（SEAT-ATK-QUEUE）：过期/心跳久旱的 PROCESSING 僵尸行终态化，先于认领。

        审计原判：认领 SQL 无年龄条件、payload 的 expires_at 在队列/worker
        零执法点 ⇒ 一条陈旧 processing 行会在死租约窗（300s）后被当新任务
        重发（「几天前的话突然又发一遍」）。修法两刀：
        ①认领口：两条 PROCESSING 臂补 ``expires_at IS NULL OR expires_at > ?``
          （见 claim_due SQL），过期行不再进候选；
        ②清扫口（本方法）：把「声明期限已过」或「心跳（updated_at）距墙钟
          久旱超过 ``_BOT_UNAVAILABLE_MAX_AGE_SECONDS``（同一年龄常量，不建
          第二真身；实例可配）」的 processing 行走 _finalize_expired_lease
          收口（有已送达 part → PARTIAL 断点，否则 FAILED_FINAL + 审计）——
          终态化比重投更符合「宁漏不双发」。

        口径说明：
        - 年龄量在**心跳**上而非 created_at：健康 worker 认领时经
          _heartbeat_iso 把 updated_at 顶到墙钟，「刚被认领、正在投递」的
          行永不被清扫（A-20 并发认领互斥回归 test_a20① 是存量契约，清扫
          若按入队年龄判就把在投行当场终态化——首版踩坑后改为此口径）；
          真正僵尸的行自最后一次写入起已静默 ≥ 年龄窗。
        - 年龄以墙钟计（注入时刻是测试虚构钟，不得把刚生成的行「吹老」）；
          expires_at 比较用当轮认领时刻（与租约/到期同用一把注入钟）。
        - 本进程仍内联持有（台账任务存活）的行跳过不清。
        - 病态越界情形（一次投递真实耗时超年龄窗后结束）：清扫只动账面，
          在途传输的收尾 mark_* 仍按行身份写回本行，不产生第二认领者。
        - 批 LIMIT 20：每 pass 少量消化即可（僵尸按定义不再生成），不抢
          认领主路径的锁预算；单行终态化异常只跳过本行，绝不拖垮认领事务。
        """
        wall_now = _utc_now()
        stale_before = (
            wall_now - timedelta(seconds=self._bot_unavailable_max_age_seconds)
        ).isoformat()
        try:
            zombies = connection.execute(
                """
                SELECT *
                FROM send_requests
                WHERE state = ?
                  AND (
                        (expires_at IS NOT NULL AND expires_at <= ?)
                     OR (updated_at IS NOT NULL AND updated_at <= ?)
                  )
                ORDER BY created_at ASC, rowid ASC
                LIMIT 20
                """,
                (PROCESSING_STATE, current_time.isoformat(), stale_before),
            ).fetchall()
        except sqlite3.Error:
            return
        for row in zombies:
            dedupe_key = str(row["dedupe_key"])
            if self._inline_claim_alive(dedupe_key):
                continue
            try:
                self._finalize_expired_lease(
                    connection, row, int(row["retry_count"]), current_time
                )
            except sqlite3.Error as exc:
                logging.getLogger(__name__).warning(
                    "zombie finalize failed dedupe_key=%s error=%s",
                    dedupe_key,
                    exc,
                )

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
        *,
        shared_connection: sqlite3.Connection | None = None,
    ) -> None:
        """把无法解析的队列行就地置终态，避免它每轮都毒死整个批次。

        关键（默认腿）：**不要**在调用方那条共享连接上执行。该连接以 autocommit
        模式创建（``isolation_level=None``），``BEGIN``/``commit``/``rollback``
        都是无效操作，DML 会留下一个隐式打开的事务——后果是终态化时隐时现、并把
        连接卡在怪异状态（实测：行停在 processing）。这里改用独立短连接，
        使隔离动作与调用方的连接状态彻底解耦。

        F-4 例外腿（SENDQ × 主代理合并批 2026-09-27）：``claim_due`` 的条目
        重建已挪进 IMMEDIATE 事务内（同事务读回防幻影进度），此时独立短连接
        会被外层写锁挡到 busy 超时（毒行停在 processing，实测回归）。故给
        ``shared_connection`` 时**直接在打开着本事务的连接上 UPDATE**——并入
        外层事务、随其一起提交，原子性反而更强；独立短连接语义只保留给
        事务外调用方。

        与非终态行永不被 _prune 淘汰的契约一致：置 FAILED_FINAL 后由既有
        A4 淘汰路径回收；不删除行，保留事后取证能力。
        """
        stamp = (current_time or _utc_now()).isoformat()
        dedupe_key = str(row["dedupe_key"])
        kind = "invalid_payload" if exc is None else self._corrupt_row_kind(row, exc)
        finalize_sql = """
                    UPDATE send_requests
                    SET state = ?,
                        claimed_from_state = NULL,
                        lease_expires_at = NULL,
                        next_retry_at = NULL,
                        updated_at = ?
                    WHERE dedupe_key = ?
                    """
        finalize_params = (ReceiptState.FAILED_FINAL.value, stamp, dedupe_key)
        try:
            if shared_connection is not None:
                shared_connection.execute(finalize_sql, finalize_params)
            else:
                with closing(self._connect()) as connection, connection:
                    connection.execute(finalize_sql, finalize_params)
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
        self,
        rows: list[sqlite3.Row],
        connection: sqlite3.Connection,
        *,
        in_transaction: bool = False,
    ) -> list[QueuedSendRequest]:
        """逐行解析：坏行终态化后跳过，健康行照常返回（毒行隔离）。

        F-4（SENDQ × 主代理合并批 2026-09-27）：仅 ``claim_due`` 的读回发生在
        IMMEDIATE 写事务内（``in_transaction=True``）——毒行终态化必须并入同一
        事务（shared_connection 腿）；独立短连接会被外层写锁挡到超时（毒行停
        processing，实测回归坐实）。其余读点连接上下文不同，盲并会撞
        "cannot start a transaction within a transaction"（实测）——两腿以
        in_transaction 显式区分、不猜。
        """
        entries: list[QueuedSendRequest] = []
        for row in rows:
            try:
                entries.append(self._entry_from_row(row, connection))
            except _CorruptQueueRow as exc:
                self._finalize_corrupt_row(
                    row,
                    exc.cause,
                    shared_connection=connection if in_transaction else None,
                )
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
        # Q-G1：断点守卫与终态化都按行主键寻址（终结口本就持有 row.dedupe_key）。
        if self._convert_terminal_to_partial_in(
            connection,
            str(row["request_id"]),
            now=current_time,
            dedupe_key=str(row["dedupe_key"]),
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
                _heartbeat_iso(current_time),
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
        dedupe_key: str,
    ) -> DeliveryReceipt:
        """B-4（管线检视 #6）：SnowLuma 断线的投递挂起，不消耗重试预算。

        bot_unavailable 是环境性暂态：照常计入 attempts 会让断线期间排队的
        回复在 ~3 分钟内烧完 max_attempts 后被 FAILED_FINAL 静默丢弃。这里
        只顺延下次尝试时间、不递增 retry_count（挂起至 bot 恢复，恢复后
        下一轮认领即投）；入队超过 bot_unavailable 年龄上限仍不可投才置
        终态，防止 A4 契约（非终态永不淘汰）下死挂行无限堆积。

        VIS（2026-10-06）：终态那一臂**必须出声**——挂起臂继续静默（每个 tick 都
        喊就是刷屏），被判死刑的臂不再静默（丢了没人喊是最贵的一种坏）。
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
                dedupe_key=dedupe_key,
            )
            # VIS（2026-10-06）：这一臂从此出声。只改写**返回回执**里的那枚 issue
            # （换成 `_bot_unavailable_drop_issue` 那枚终态代号），既有链条就把它送到
            # 中央告警口：queue → worker `_notify_operational_issue_safely` →
            # 装配 `operational_notifier`（`__init__._notify_queue_operational_receipt`）
            # → `alerts.notify_operational_issue`（300s 抑制窗 + 诊断卡照旧，fail-open
            # 也照旧：告警腿整段 try/except，炸了只留痕、不改回执）。
            # 行上落的仍是原挂起 issue（上方 `_update_state_in` 已提交），盘上账与
            # 审计行（`send_failed_final`，读的是 state/retry_count/public_message）
            # 逐字不变；挂起那一臂（else）仍不带这枚代号 ⇒ 不会每个 tick 都喊。
            receipt = receipt.model_copy(
                update={
                    "operational_issue": self._bot_unavailable_drop_issue(
                        entry, issue, now=now
                    )
                }
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
                dedupe_key=dedupe_key,
            )
            event = "send_deferred_bot_unavailable"
        self._append_sender_audit(entry.send_request, receipt, event)
        return receipt

    def _bot_unavailable_drop_issue(
        self,
        entry: QueuedSendRequest,
        issue: OperationalIssue,
        *,
        now: datetime,
    ) -> OperationalIssue:
        """年龄闸终态那一臂的人话抓手（只喂告警面：不落盘、不参与任何判定）。

        一条告警要能自己回答四件事——因为什么（`kind` 的中文在册）、哪一枚请求、
        投给哪个会话、还能不能补发（`retryable=False` ⇒ 告警的「要不要再试」行说
        「重试也没用，得有人看一眼」；队列侧的事实是终态行永不再被认领、也不会
        自动补发）。批量的「多少条」不在这里编：那是既有抑制窗的读数
        （`AdminAlertSuppression` → 告警的「同时压着 N 条同类没重复发」行）。
        `safe_summary` 保持单行且≤118 字——`alerts` 的「具体情况」行按 120 裁、
        技术行按 60 裁，把最要命的两件（哪一枚请求/哪个会话）排在前面。
        """
        request = entry.send_request
        held_seconds = max(0.0, (now - entry.created_at).total_seconds())
        summary = " ".join(
            (
                _BOT_UNAVAILABLE_DROP_KIND,
                f"req={str(request.request_id)[:24]}",
                f"sess={str(request.session_id)[:30]}",
                f"held={held_seconds:.0f}s>={self._bot_unavailable_max_age_seconds:.0f}s",
            )
        )
        return OperationalIssue(
            stage="queue",
            kind=_BOT_UNAVAILABLE_DROP_KIND,
            retryable=False,
            severity=issue.severity,
            attempts=max(1, int(entry.retry_count)),
            safe_summary=summary[:118],
        )

    def mark_retryable_failure(
        self,
        request_id: str,
        public_message: str,
        *,
        now: datetime | None = None,
        operational_issue: OperationalIssue | None = None,
        dedupe_key: str | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            # Q-G1：终结口一律先定行身份（显式 > 内联台账 > 最新行启发式），
            # 之后所有读写都按该身份寻址——不再以非唯一 request_id 为谓词。
            identity = self._resolve_update_identity_in(connection, request_id, dedupe_key)
            # 审查 A-22（Q-G6）：内联首投已走到终结口（无论成败）即释放本行
            # 认领槽；只清自己的槽，兄弟行在途保护原样保留。
            self._release_inline_claim(request_id, identity)
            if identity is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )
            entry = self._find_entry_in(connection, request_id, dedupe_key=identity)
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
                    connection,
                    entry,
                    issue,
                    public_message,
                    now=current_time,
                    dedupe_key=identity,
                )
            retry_count = entry.retry_count + 1
            if retry_count >= self.max_attempts:
                # §9.3 断点守卫：请求重试预算烧尽但有 part 已送达时改置
                # PARTIAL 断点（补偿扫描续发），不整封 FAILED_FINAL 盲重发。
                if self._convert_terminal_to_partial_in(
                    connection, request_id, now=current_time, dedupe_key=identity
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
                    dedupe_key=identity,
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
                    dedupe_key=identity,
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
        dedupe_key: str | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            # Q-G1：行身份寻址（显式 > 内联台账 > 最新行启发式）。
            identity = self._resolve_update_identity_in(connection, request_id, dedupe_key)
            # 审查 A-22（Q-G6）：内联首投成功即释放本行认领槽（行置 SENT 后
            # worker 本就不可认领，释放只为台账生命周期与行状态一致）。
            self._release_inline_claim(request_id, identity)
            if identity is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )
            entry = self._find_entry_in(connection, request_id, dedupe_key=identity)
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
                dedupe_key=identity,
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
        dedupe_key: str | None = None,
    ) -> DeliveryReceipt:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            # Q-G1：行身份寻址（显式 > 内联台账 > 最新行启发式）。
            identity = self._resolve_update_identity_in(connection, request_id, dedupe_key)
            # 审查 A-22（Q-G6）：内联首投终败即释放本行认领槽（有已送达 part
            # 时由下方断点守卫改置 PARTIAL，台账同样终结——内联已结束）。
            self._release_inline_claim(request_id, identity)
            if identity is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )
            entry = self._find_entry_in(connection, request_id, dedupe_key=identity)
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
                connection, request_id, now=current_time, dedupe_key=identity
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
                dedupe_key=identity,
            )
        self._append_sender_audit(entry.send_request, receipt, "send_failed_final")
        return receipt

    # ---- §9.3 part 级幂等进度与 PARTIAL 断点 --------------------------------
    # 目标：长回复切成多个 part 后，每个 part 成功即落库；已 SENT 的 part 永不
    # 重发；结果未知的 part 记 UNKNOWN 走确认协议；有副作用又无法立即完成时
    # 请求行置 PARTIAL 终态+断点，由 claim_due 的补偿扫描续发剩余 part。
    # 所有写路径沿用共享连接单事务（WAL）惯例；part 明细表与请求行汇总列在同
    # 一事务内更新。

    def _resolve_update_identity_in(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        dedupe_key: str | None,
    ) -> str | None:
        """Q-G1 终结口行身份解析：显式 > 内联台账（本任务自持槽）> 最新行。

        返回行主键 dedupe_key；库里没有该 request_id 的任何行时返回 None
        （调用方走 not-found 回执，与既有语义一致）。绝不返回 request_id
        当身份用——那正是共键写扇出的原罪。
        """
        if dedupe_key is not None:
            return str(dedupe_key)
        inline = self._inline_claim_identity_for_caller(request_id)
        if inline is not None:
            return inline
        row = connection.execute(
            """
            SELECT dedupe_key
            FROM send_requests
            WHERE request_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (request_id,),
        ).fetchone()
        return None if row is None else str(row["dedupe_key"])

    def _part_ledger_identity_in(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        dedupe_key: str | None,
    ) -> str | None:
        """Q-G5 part 账本身份判定。

        解析优先级同终结口（显式 > 最新行）。在此基础上做旧账迁移判定：
        - 该身份已有 part 行 → 用它（正常续账）。
        - 身份无行、但存在无主旧账（dedupe_key IS NULL 的升级前行）→
          返回 None＝沿用旧格式账本继续记账（绝不另起一本新账把已送达
          part 重发）；ensure_parts_planned 会把旧账收养进身份。
        - 库上无任何相关行 → 用身份开新账（新写入不再产生无主行）。
        """
        if dedupe_key is None:
            return None
        identity_rows = connection.execute(
            """
            SELECT 1 FROM send_request_parts
            WHERE request_id = ? AND dedupe_key = ?
            LIMIT 1
            """,
            (request_id, dedupe_key),
        ).fetchone()
        if identity_rows is not None:
            return dedupe_key
        orphan_rows = connection.execute(
            """
            SELECT 1 FROM send_request_parts
            WHERE request_id = ? AND dedupe_key IS NULL
            LIMIT 1
            """,
            (request_id,),
        ).fetchone()
        if orphan_rows is not None:
            return None
        return dedupe_key

    def ensure_parts_planned(
        self,
        request_id: str,
        payload_digests: list[str],
        *,
        now: datetime | None = None,
        dedupe_key: str | None = None,
    ) -> PartProgress | None:
        """首次 part 化发送前预写全部 PENDING part 行（幂等，ON CONFLICT 跳过）。

        只保存 payload 摘要，不保存用户正文副本（规格 §9.3.2）。请求行不存在
        或写入失败时返回 None，调用方降级为既有整发语义。

        Q-G5 账本守卫：本身份账上已存行必须与本次规划的 digest 逐位一致，
        不一致 ⇒ 抛 PartLedgerConflictError——调用方（worker）绝不回落整发
        （已送达 part 会被重发），只能按 result_unknown 收口。无主旧账
        （升级前遗留 NULL 身份行）digest 全等时收养入身份，否则同样拒绝。
        """
        current_time = now or _utc_now()
        digests = list(payload_digests)
        if not digests:
            return None
        self._ensure_schema_once()
        try:
            with self._transaction() as connection:
                resolved = self._resolve_update_identity_in(
                    connection, request_id, dedupe_key
                )
                ledger = self._part_ledger_identity_in(connection, request_id, resolved)
                self._guard_part_ledger_digests(
                    connection, request_id, ledger, digests, adopt_into=resolved
                )
                if ledger is None and resolved is not None:
                    # 收养成功路径：守卫已把无主旧账回填身份 → 本笔起按身份记账。
                    ledger = resolved
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
                            updated_at,
                            dedupe_key
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(part_key) DO NOTHING
                        """,
                        (
                            _part_key(request_id, index, ledger),
                            request_id,
                            index,
                            total,
                            PART_STATE_PENDING,
                            0,
                            digest,
                            current_time.isoformat(),
                            ledger,
                        ),
                    )
                self._refresh_request_part_summary_in(
                    connection,
                    request_id,
                    now=current_time,
                    dedupe_key=ledger,
                    row_identity=resolved,
                )
                return self._load_part_progress_in(
                    connection, request_id, dedupe_key=ledger
                )
        except PartLedgerConflictError:
            raise
        except sqlite3.Error:
            logger = logging.getLogger(__name__)
            logger.warning(
                "part plan persist failed request_id=%s", request_id
            )
            return None

    def _guard_part_ledger_digests(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        ledger: str | None,
        digests: list[str],
        *,
        adopt_into: str | None = None,
    ) -> None:
        """Q-G5：账本 digest 一致性守卫 + 无主旧账收养。

        - ledger 为身份：逐位比对（仅比对本次规划覆盖到的 index）。
        - ledger 为 None 但 adopt_into 有身份：面对的是无主旧账——digest 全等
          且 index 集合吻合则收养（回填 dedupe_key 列），否则拒绝。
        任一 digest 不等 → PartLedgerConflictError（宁停发不混账）。
        """
        if ledger is not None:
            rows = connection.execute(
                """
                SELECT part_index, payload_digest
                FROM send_request_parts
                WHERE request_id = ? AND dedupe_key = ?
                """,
                (request_id, ledger),
            ).fetchall()
            for row in rows:
                index = int(row["part_index"])
                stored = row["payload_digest"]
                if stored is None or index >= len(digests):
                    continue
                if str(stored) != str(digests[index]):
                    raise PartLedgerConflictError(
                        f"part ledger digest mismatch request_id={request_id} "
                        f"part_index={index}"
                    )
            return
        # ledger None：可能是无主旧账（升级遗留）。有身份可收养时才检查。
        orphan = connection.execute(
            """
            SELECT part_index, payload_digest
            FROM send_request_parts
            WHERE request_id = ? AND dedupe_key IS NULL
            """,
            (request_id,),
        ).fetchall()
        if not orphan:
            return
        orphan_map = {int(r["part_index"]): r["payload_digest"] for r in orphan}
        adoptable = adopt_into is not None and len(orphan_map) == len(digests)
        if adoptable:
            for index, digest in enumerate(digests):
                stored = orphan_map.get(index)
                if stored is None or str(stored) != str(digest):
                    adoptable = False
                    break
        if adoptable and adopt_into is not None:
            connection.execute(
                """
                UPDATE send_request_parts
                SET dedupe_key = ?
                WHERE request_id = ? AND dedupe_key IS NULL
                """,
                (adopt_into, request_id),
            )
            return
        if adopt_into is None:
            # 无身份可收养（请求行都还没有）：旧账原样留着，本轮按旧格式续写。
            return
        raise PartLedgerConflictError(
            f"legacy part ledger not adoptable request_id={request_id}"
        )

    def part_progress(
        self, request_id: str, *, dedupe_key: str | None = None
    ) -> PartProgress | None:
        """读取请求的 part 级进度快照（只读；无 part 跟踪时返回 None）。

        未显式给身份时按终结口同式解析行身份（最新行→该身份的账，账空回退
        无主旧账），与 mark_part_*/ensure_parts_planned 的寻址保持一致。
        """
        self._ensure_schema_once()
        with self._locked_connection() as connection:
            identity = self._resolve_update_identity_in(
                connection, request_id, dedupe_key
            )
            return self._load_part_progress_in(
                connection, request_id, dedupe_key=identity
            )

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
        dedupe_key: str | None = None,
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
            dedupe_key=dedupe_key,
        )

    def mark_part_sent(
        self,
        request_id: str,
        part_index: int,
        *,
        provider_message_id: str | None = None,
        now: datetime | None = None,
        dedupe_key: str | None = None,
    ) -> bool:
        return self._update_part_row(
            request_id,
            part_index,
            state=PART_STATE_SENT,
            provider_message_id=provider_message_id,
            now=now,
            dedupe_key=dedupe_key,
        )

    def mark_part_unknown(
        self,
        request_id: str,
        part_index: int,
        *,
        error_kind: str | None = None,
        error_detail: str | None = None,
        provider_message_id: str | None = None,
        now: datetime | None = None,
        dedupe_key: str | None = None,
    ) -> bool:
        """结果未知（超时/断连/无法判定）：记 UNKNOWN，绝不静默当失败盲重发。"""
        return self._update_part_row(
            request_id,
            part_index,
            state=PART_STATE_UNKNOWN,
            last_error_kind=error_kind,
            last_error_detail=error_detail,
            provider_message_id=provider_message_id,
            now=now,
            dedupe_key=dedupe_key,
        )

    def mark_part_failed_final(
        self,
        request_id: str,
        part_index: int,
        *,
        error_kind: str | None = None,
        error_detail: str | None = None,
        now: datetime | None = None,
        dedupe_key: str | None = None,
    ) -> bool:
        """平台明确拒绝且不可重试（如 403）：该 part 终态，不回 PENDING。"""
        return self._update_part_row(
            request_id,
            part_index,
            state=PART_STATE_FAILED_FINAL,
            last_error_kind=error_kind,
            last_error_detail=error_detail,
            now=now,
            dedupe_key=dedupe_key,
        )

    def mark_part_pending(
        self,
        request_id: str,
        part_index: int,
        *,
        now: datetime | None = None,
        dedupe_key: str | None = None,
    ) -> bool:
        """明确可重试的失败（或确认「未送达」的 UNKNOWN）回到 PENDING。"""
        return self._update_part_row(
            request_id,
            part_index,
            state=PART_STATE_PENDING,
            now=now,
            dedupe_key=dedupe_key,
        )

    def _update_part_row(
        self,
        request_id: str,
        part_index: int,
        *,
        state: str,
        increment_attempts: bool = False,
        last_error_kind: str | None = None,
        last_error_detail: str | None = None,
        provider_message_id: str | None = None,
        now: datetime | None = None,
        dedupe_key: str | None = None,
    ) -> bool:
        current_time = now or _utc_now()
        self._ensure_schema_once()
        try:
            with self._transaction() as connection:
                resolved = self._resolve_update_identity_in(
                    connection, request_id, dedupe_key
                )
                ledger = self._part_ledger_identity_in(connection, request_id, resolved)
                # Q-G5：行定位改 (request_id, dedupe_key, part_index) 三元组，
                # 兄弟行不再同键互踩；UPDATE 谓词含身份列（结构锁执法）。
                row = connection.execute(
                    """
                    SELECT parts_total
                    FROM send_request_parts
                    WHERE request_id = ? AND part_index = ?
                      AND dedupe_key IS ?
                    """,
                    (request_id, part_index, ledger),
                ).fetchone()
                if row is None:
                    return False
                assignments = ["state = ?", "updated_at = ?"]
                params: list[object] = [state, _heartbeat_iso(current_time)]
                if increment_attempts:
                    assignments.append("attempts = attempts + 1")
                if last_error_kind is not None:
                    assignments.append("last_error_kind = ?")
                    params.append(last_error_kind)
                if last_error_detail is not None:
                    # SEAT-SENDTERM A2：结构因单列存写侧自截（防越界写入），
                    # 读侧 NULL＝旧行无原因可考，与「不回填不猜」一致。
                    assignments.append("last_error_detail = ?")
                    params.append(str(last_error_detail)[:96])
                if provider_message_id is not None:
                    assignments.append("provider_message_id = ?")
                    params.append(provider_message_id)
                elif state in (PART_STATE_PENDING, PART_STATE_UNKNOWN):
                    # F-3（SEAT-ATK-SENDQ，2026-09-27）：part 转回 pending/unknown
                    # 必清残号——worker UNKNOWN 对账的本地列短路只准吃确认器写入的
                    # 现号，历史残号不得把「没确认」洗成「已送达」（红线：UNKNOWN
                    # 只由确认器/人工销案）。
                    assignments.append("provider_message_id = NULL")
                params.extend([request_id, part_index, ledger])
                connection.execute(
                    f"""
                    UPDATE send_request_parts
                    SET {", ".join(assignments)}
                    WHERE request_id = ? AND part_index = ?
                      AND dedupe_key IS ?
                    """,
                    params,
                )
                self._refresh_request_part_summary_in(
                    connection,
                    request_id,
                    now=current_time,
                    dedupe_key=ledger,
                    row_identity=resolved,
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
        dedupe_key: str | None = None,
        row_identity: str | None = None,
    ) -> None:
        """把 part 明细表汇总进请求行列（同事务；必须在调用方事务内执行）。

        Q-G3 头注配套事实（诚实口径）：本汇总是唯一的「投递期间心跳」写点，
        且**只对有 part 跟踪的行存在**——无 part 行的整发行直接 return，
        其 updated_at 只在 claim 与终结 mark_* 两拍推进。
        Q-G1：汇总谓词收口到行主键 dedupe_key（本函数旧版 `WHERE request_id`
        正是共键兄弟行互相改写 parts_* 的通路）。
        ``dedupe_key``＝被汇总的 part 账身份（None＝无主旧账）；
        ``row_identity``＝被改写的请求行主键（缺省跟随 dedupe_key；孤儿旧账
        模式下请求行仍要被汇总，故两枚分开传）。
        """
        rows = connection.execute(
            """
            SELECT part_index, parts_total, state
            FROM send_request_parts
            WHERE request_id = ? AND dedupe_key IS ?
            ORDER BY part_index ASC
            """,
            (request_id, dedupe_key),
        ).fetchall()
        if not rows:
            return
        target = row_identity if row_identity is not None else dedupe_key
        if target is None:
            # 请求行不存在（无主账且解析不出身份）：与旧版「UPDATE 不中任何行」
            # 同形——但绝不以 request_id 为谓词去碰兄弟行。
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
            WHERE dedupe_key = ?
            """,
            (
                total,
                delivered,
                progress_json,
                _heartbeat_iso(now),
                target,
            ),
        )

    def _load_part_progress_in(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        *,
        dedupe_key: str | None = None,
    ) -> PartProgress | None:
        """在调用方连接上读取 part 进度（事务内/持锁读均可，RLock 可重入）。

        Q-G5：进度按 (request_id, dedupe_key) 读；身份账读空时回退读无主旧账
        （升级遗留行），保证历史行不被误判「part 明细丢失」毒行；两本账互不
        混读——身份账存在即以其为准，兄弟行不再共账。
        """
        rows = connection.execute(
            """
            SELECT part_index, parts_total, state, attempts, last_error_kind,
                   provider_message_id, payload_digest
            FROM send_request_parts
            WHERE request_id = ? AND dedupe_key IS ?
            ORDER BY part_index ASC
            """,
            (request_id, dedupe_key),
        ).fetchall()
        if not rows and dedupe_key is not None:
            rows = connection.execute(
                """
                SELECT part_index, parts_total, state, attempts, last_error_kind,
                       provider_message_id, payload_digest
                FROM send_request_parts
                WHERE request_id = ? AND dedupe_key IS NULL
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
        dedupe_key: str | None = None,
    ) -> DeliveryReceipt:
        """置 PARTIAL 终态+断点：有已送达 part 但无法立即全部完成。

        resumable=True 时带 90s 补偿扫描退避（下轮 claim_due 扫描续发/确认）；
        resumable=False（本轮零进展：无可续发 part 且确认无变化）时休眠
        （next_retry_at=NULL），仍可经 list_partial_requests 检视或人工推进。
        """
        current_time = now or _utc_now()
        self._ensure_schema_once()
        with self._transaction() as connection:
            # Q-G1：行身份寻址；终结口只清本行的认领槽（Q-G6）。
            identity = self._resolve_update_identity_in(connection, request_id, dedupe_key)
            # 审查 A-22：PARTIAL 收敛属于 worker 投递侧终结口，顺手释放
            # 认领台账（内联路径不会产生 PARTIAL，防御性对齐生命周期）。
            self._release_inline_claim(request_id, identity)
            if identity is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )
            entry = self._find_entry_in(connection, request_id, dedupe_key=identity)
            if entry is None:
                return DeliveryReceipt(
                    request_id=request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=SQLITE_QUEUE_TRANSPORT,
                    public_message="send request not found",
                    operational_issue=operational_issue,
                )
            issue = operational_issue or entry.send_request.operational_issue
            if not resumable:
                # Q-G7 ①：休眠轮的收敛判定必须先于 PARTIAL 写入。
                decision = self._dormancy_decision_in(connection, entry, request_id)
                if decision == "final":
                    return self._finalize_dormant_partial_in(
                        connection, entry, request_id, issue=issue, now=current_time
                    )
                if decision == "backoff":
                    # 还有可推进 part：绝不允许落成 NULL 死档，强制视为可续发
                    # （现役 worker 路径造不出该形态，防御未来新调用点）。
                    resumable = True
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
                WHERE dedupe_key = ?
                """,
                (
                    PARTIAL_ROW_STATE,
                    next_retry_at.isoformat() if next_retry_at is not None else None,
                    _heartbeat_iso(current_time),
                    identity,
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

    def _dormancy_decision_in(
        self,
        connection: sqlite3.Connection,
        entry: QueuedSendRequest,
        request_id: str,
    ) -> str:
        """休眠轮（resumable=False）三态判定："final" / "backoff" / "dormant"。

        - 仍有 PENDING 且 attempts 未烧尽的 part ⇒ "backoff"（可推进的行不许
          停放；告警行同规则——停放/终态都救不回未送达的告警，续投才救得回，
          而 backoff 既非 parked 也非静默）。
        - 无可推进 part（只剩 SENT/UNKNOWN/FAILED_FINAL，或 attempts 全烧尽）
          ⇒ "final"：休眠 ≡ 永久停摆（confirmer 缺席时每轮必为零进展），
          直接终态化，宁可漏不盲重发。
        - 无 part 账本 ⇒ 告警行 "final"（无账本无法证明可推进，停放代价对
          告警不可接受），其余保持既有休眠语义（生产 P2 名册全部带账本，
          该分支只兜非 worker 调用点）。
        """
        if _is_alert_send_request(entry.send_request):
            progress = self._load_part_progress_in(
            connection, request_id, dedupe_key=entry.row_dedupe_key
        )
            if progress is None or progress.total <= 0:
                return "final"
        else:
            progress = self._load_part_progress_in(
            connection, request_id, dedupe_key=entry.row_dedupe_key
        )
            if progress is None or progress.total <= 0:
                return "dormant"
        attempts_cap = max(1, self.max_attempts)
        can_progress = any(
            record.state == PART_STATE_PENDING and record.attempts < attempts_cap
            for record in progress.records.values()
        )
        return "backoff" if can_progress else "final"

    def _finalize_dormant_partial_in(
        self,
        connection: sqlite3.Connection,
        entry: QueuedSendRequest,
        request_id: str,
        *,
        issue: OperationalIssue | None,
        now: datetime,
    ) -> DeliveryReceipt:
        """Q-G7 ① 的终态口：休眠轮直接写 FAILED_FINAL（调用方事务内执行）。

        part 明细账原样保留（SENT 的仍是 SENT、UNKNOWN 的仍是 UNKNOWN）——
        这是「诚实回执」的取证面：事后能从 send_request_parts 查出到底送达
        了几段、哪几段结果未知。绝不重发任何 part（宁漏不双发）。
        谓词用行身份 dedupe_key（不新增共键写）。updated_at 写用
        _heartbeat_iso(now)（QKEY 心跳纪律件）；若基线无该原语则退直接
        isoformat（合并次序说明见 SEAT-FIX-QPARK §五）。
        """
        progress = self._load_part_progress_in(
            connection, request_id, dedupe_key=entry.row_dedupe_key
        )
        delivered = progress.delivered if progress is not None else 0
        total = progress.total if progress is not None else 0
        summary = f"dormant_final delivered={delivered}/{total}"
        row_identity = (
            getattr(entry, "row_dedupe_key", None) or entry.send_request.dedupe_key
        )
        heartbeat = globals().get("_heartbeat_iso")
        updated_at = heartbeat(now) if callable(heartbeat) else now.isoformat()
        connection.execute(
            """
            UPDATE send_requests
            SET state = ?,
                claimed_from_state = NULL,
                lease_expires_at = NULL,
                next_retry_at = NULL,
                last_public_message = ?,
                updated_at = ?
            WHERE dedupe_key = ?
            """,
            (
                ReceiptState.FAILED_FINAL.value,
                summary,
                updated_at,
                row_identity,
            ),
        )
        final_issue = issue or OperationalIssue(
            stage="queue",
            kind="dormant_partial_final",
            retryable=False,
            safe_summary="dormant_partial_final",
        )
        receipt = DeliveryReceipt(
            request_id=request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=SQLITE_QUEUE_TRANSPORT,
            retry_count=entry.retry_count,
            next_retry_at=None,
            public_message="",
            operational_issue=final_issue,
        )
        self._append_sender_audit(entry.send_request, receipt, "send_dormant_final")
        return receipt

    def list_dormant_partials(
        self, *, now: datetime | None = None, limit: int = 20
    ) -> list[QueuedSendRequest]:
        """休眠 PARTIAL 视图（state=partial 且 next_retry_at IS NULL）。

        Q-G7 修复落地后该形态只剩「上线前存量」与极窄的非 worker 分支；
        供 worker busy 观测与运维点名（SEAT-ATK-QUEUE Q-G7 修法③）。
        del now 保持签名与时间无关。"""
        del now
        self._ensure_schema_once()
        safe_limit = max(1, int(limit))
        with self._locked_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM send_requests
                WHERE state = ? AND next_retry_at IS NULL
                ORDER BY created_at ASC, rowid ASC
                LIMIT ?
                """,
                (PARTIAL_ROW_STATE, safe_limit),
            ).fetchall()
            return self._entries_from_rows(rows, connection)

    def _convert_terminal_to_partial_in(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        *,
        now: datetime,
        dedupe_key: str | None = None,
    ) -> bool:
        """FAILED_FINAL 前的断点守卫：0<已送达<总数 时改写 PARTIAL。

        在调用方事务内执行；返回 True 表示调用方应跳过 FAILED_FINAL 写入
        （PARTIAL 断点已落库，由补偿扫描续发，绝不整封盲重发）。
        Q-G1：进度判定与改写都按行身份（终结口/租约收口都持有 dedupe_key）。
        """
        identity = dedupe_key or self._resolve_update_identity_in(
            connection, request_id, None
        )
        if identity is None:
            return False
        progress = self._load_part_progress_in(
            connection, request_id, dedupe_key=identity
        )
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
            WHERE dedupe_key = ?
            """,
            (
                PARTIAL_ROW_STATE,
                next_retry_at.isoformat(),
                _heartbeat_iso(now),
                identity,
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
            # SEAT-ATK-QUEUE Q-G4：行级投递期限列（SendRequest.expires_at 的
            # SQL 可比较投影）。此前 expires_at 在队列/worker 零执法点——陈旧
            # processing 行 300s 后会被当新任务重发。claim_due 的 PROCESSING
            # 两臂据此拒绝认领过期行，僵尸清扫（_finalize_zombie_processing_
            # rows）据此终态化。存量行自 request_json 回填（同 session_id 口）。
            self._ensure_column(
                connection,
                "send_requests",
                "expires_at",
                "TEXT",
            )
            self._backfill_expires_at(connection)
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
            # SEAT-ATK-QUEUE Q-G5：part 账本行身份列（send_requests.dedupe_key
            # 的引用）。旧 part_key 只含 request_id，共 request_id 的兄弟行
            # 共用一本账（B 一条没发账上全送达）。新行一律带身份；旧行
            # （列 NULL）＝无主旧账，只被显式收养或留作惰性读，绝不静默混用。
            self._ensure_column(
                connection,
                "send_request_parts",
                "dedupe_key",
                "TEXT",
            )
            # SEAT-SENDTERM A1/A2（2026-10-04）：「为什么失败」的结构因列（如
            # ``retcode_failure retcode=403 status=failed``）。此前 part 明细只有
            # ``last_error_kind``＝失败**族**，判死用的那枚 OneBot 退码在
            # ``sender/onebot.py`` 用完即丢 ⇒ 事后无从复核是哪枚码判的生死。
            # 与上方 dedupe_key 同法：additive ALTER-if-missing（元数据级、非破坏
            # 性、幂等），旧行 NULL＝无原因可考，不回填、不猜。内容全部由 sender
            # 侧结构化拼装（数字 + 协议状态词白名单形状），适配器/异常自由文本按
            # tests/test_operational_failures.py:368-373 裁决锁不入册。
            # db-owners 门（tests/test_db_owners_coverage.py 尺①键名/尺②文件名）
            # 比对的是 config.py 库路径键 ⇄ 登记的库文件名，本列既不加库键也不加
            # 库文件 ⇒ 该门不受本改动影响（已实跑复核）。
            self._ensure_column(
                connection,
                "send_request_parts",
                "last_error_detail",
                "TEXT",
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_send_request_parts_request
                ON send_request_parts (request_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_send_request_parts_identity
                ON send_request_parts (request_id, dedupe_key)
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
            # SEAT-Q1-QUEUE-SCAN-20261002（P5.9）：留存窗口「最新 max_items 行」
            # 的有序读侧。_prune 每次 submit 都跑（submit→_prune，非惰性），其
            # keeper 子查询 `ORDER BY created_at DESC, rowid DESC LIMIT ?` 此前
            # 无索引可用 ⇒ EXPLAIN QUERY PLAN = `SCAN send_requests` +
            # `USE TEMP B-TREE FOR ORDER BY`（生产只读副本实测 1000 行、恰好
            # pinned 在 max_items：均值 4.849 ms/次 submit，且那一轮一行都不必删）。
            # 建索引后子查询变成 `SCAN ... USING COVERING INDEX
            # idx_send_requests_created_at`、临时 B 树消失、读侧被 LIMIT 截断。
            # 🔴 键序必须是**裸 ASC 单列** `created_at`，不许"顺手"改成 DESC：
            # 索引叶子键恒为 (created_at, rowid ASC)，倒着走恰好等于
            # `created_at DESC, rowid DESC`；写成 `(created_at DESC)` 时叶子变成
            # (created_at DESC, rowid ASC)，正走倒走都对不上那枚 rowid DESC，
            # 优化器退回 `USE TEMP B-TREE FOR LAST TERM OF ORDER BY`（两形均已在
            # 生产副本上实测对比，读数记在工单）。想写 `(created_at, rowid)`
            # 显式双列也不行——SQLite 拒绝把 rowid 当索引列（`no such column`）。
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_send_requests_created_at
                ON send_requests (created_at)
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

    def _backfill_expires_at(self, connection: sqlite3.Connection) -> None:
        """Q-G4：存量行回填 expires_at（与 _backfill_session_id 同法同规矩：
        json_valid 过滤，SQLite 无 JSON1 时静默跳过，回填失败不致命）。"""
        try:
            connection.execute(
                """
                UPDATE send_requests
                SET expires_at = json_extract(request_json, '$.expires_at')
                WHERE expires_at IS NULL
                  AND json_valid(request_json)
                  AND json_extract(request_json, '$.expires_at') IS NOT NULL
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
        # Q-G7 ③ 唯一例外——休眠 PARTIAL（next_retry_at IS NULL，永不再被
        # 认领、等价于已丢）超 TTL 后先扫成 FAILED_FINAL，再进上面的终态剪
        # 除集；只改状态绝不重投（宁漏不双发）。新休眠已由 mark_partial
        # 终态口在源头堵住，本腿只收历史存量（SEAT-ATK-QUEUE §二-P2 10 枚）。
        cutoff = (
            _utc_now() - timedelta(seconds=_DORMANT_PARTIAL_SWEEP_SECONDS)
        ).isoformat()
        # Q-G1 结构锁合规（主代理合并批 2026-09-27）：批量 UPDATE 必须带行
        # 主键——同事务内先取休眠行键集，再逐行以 dedupe_key 落终态（休眠集
        # 以十计，逐行成本可忽略；两语句同处 _prune 的写事务内，原子性不变）。
        dormant_keys = [
            str(row["dedupe_key"])
            for row in connection.execute(
                """
                SELECT dedupe_key FROM send_requests
                WHERE state = ?
                  AND next_retry_at IS NULL
                  AND updated_at <= ?
                """,
                (PARTIAL_ROW_STATE, cutoff),
            ).fetchall()
        ]
        for dormant_key in dormant_keys:
            connection.execute(
                """
                UPDATE send_requests
                SET state = ?,
                    claimed_from_state = NULL,
                    lease_expires_at = NULL,
                    last_public_message = 'dormant_partial_swept',
                    updated_at = ?
                WHERE dedupe_key = ?
                """,
                (
                    ReceiptState.FAILED_FINAL.value,
                    _utc_now().isoformat(),
                    dormant_key,
                ),
            )
        # SEAT-Q1-QUEUE-SCAN-20261002（P5.9）：反连接键从 `dedupe_key`（TEXT 主
        # 键原文）换成 `rowid`。两件事，都不动语义：
        # ① 让 keeper 子查询吃上新建的 idx_send_requests_created_at 且**免回表**
        #    ——子查询只吐 rowid，索引叶子自带 rowid ⇒ COVERING；旧形态要逐行
        #    回表取 dedupe_key 原文（同索引同数据实测 2.083 ms vs 0.212 ms，
        #    读数记在工单 §3）。
        # ② 顺带堵掉 `dedupe_key NOT IN (…)` 的 NULL 陷阱：SQLite 的
        #    `TEXT PRIMARY KEY` 不隐含 NOT NULL（实测可插 NULL 主键行），
        #    一旦 keeper 集里落进一枚 NULL dedupe_key，`NOT IN` 对整个集合判
        #    NULL ⇒ 剪枝静默变成「一行都不删」且不报错（HEAD 代码上已复现：
        #    最新行为 NULL 时删除数 0，而对照的无 NULL 场景删 4）。rowid 恒非空。
        #    现网 `dedupe_key IS NULL` 行数＝0（只读实测），故此腿在现网无现值差异，
        #    它买的是「以后也不许退回那个形状」。
        # 等价性（不许靠"看起来一样"签字）：(created_at, rowid) 因 rowid 唯一而
        # 全序，故「按该序取前 N 行」的行集与取键方式无关——dedupe_key 是主键，
        # row ↔ dedupe_key 双射。生产副本上 cap=0/1/10/500/999/1000/1500/100000
        # 八档逐档比过删除集，全等（读数记在工单 §3），另有锁
        # tests/test_queue_prune_index_lock.py
        # ::test_prune_keeps_exactly_the_newest_window_with_created_at_ties。
        # 只剪终态（SENT/FAILED_FINAL/SKIPPED）：PARTIAL/QUEUED/PROCESSING/
        # FAILED_RETRYABLE 不在 state IN 集内，A4「非终态永不淘汰」原样不动。
        connection.execute(
            """
            DELETE FROM send_requests
            WHERE state IN (?, ?, ?)
              AND rowid NOT IN (
                SELECT rowid
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
        self,
        connection: sqlite3.Connection,
        request_id: str,
        *,
        dedupe_key: str | None = None,
    ) -> QueuedSendRequest | None:
        """按行身份取条目（Q-G1）。

        给了 dedupe_key 就按行主键精确取一行；没给才回退「按 request_id 取
        最新一行」的旧启发式（find_request 等只读口保持既有寻址语义）。
        写路径一律先经 _resolve_update_identity_in 定身份再来取。
        """
        if dedupe_key is not None:
            row = connection.execute(
                """
                SELECT *
                FROM send_requests
                WHERE dedupe_key = ?
                """,
                (dedupe_key,),
            ).fetchone()
        else:
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
            # Q-G1/Q-G5：part 进度按行主键身份读（兄弟行各读各账）；行身份
            # 随条目带出（worker 终结口据此寻址，不再依赖 payload 自述）。
            row_dedupe_key = str(row["dedupe_key"])
            parts = self._load_part_progress_in(
                connection, str(row["request_id"]), dedupe_key=row_dedupe_key
            )
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
                row_dedupe_key=row_dedupe_key,
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
        dedupe_key: str,
    ) -> DeliveryReceipt:
        """在调用方事务内更新行状态（mark_* 的单事务写路径）。

        Q-G1（SEAT-ATK-QUEUE，Critical）：谓词收口到行主键 dedupe_key。
        旧版 `WHERE request_id = ?` 在同 request_id 多行（error_report
        ack/card 共键设计，审查 E-12 刻意保留）时一次写覆全组：已 SENT 行
        被复活带兄弟正文再认领＝双发、未发行被写成 SENT＝静默丢、两行
        request_json 洗成同一份＝正文销毁（生产 7 行实锤＋离线复刻两全）。
        行身份由终结口解析（显式 > 内联台账 > 最新行）并线程传入。
        """
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
            WHERE dedupe_key = ?
            """,
            (
                state.value,
                persisted_request.model_dump_json(),
                retry_count,
                next_retry_at.isoformat() if next_retry_at is not None else None,
                public_message,
                _heartbeat_iso(now),
                dedupe_key,
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

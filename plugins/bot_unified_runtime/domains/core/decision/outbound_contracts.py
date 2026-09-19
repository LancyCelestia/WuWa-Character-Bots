"""V2.1 S6 出站收编契约层（A16）：OutboundIntent 严格 DTO + 出站准入协议 +
许可租约 + 同事件幂等去重/UNKNOWN 对账协议。

合同来源（本模块是它们的机器可执行形态）：
- 主规范 §10（docs/design/backend-v2-implementation-guide.md）：
  「OutboundIntent含operation/target/parts/feature_id/policy_revision/dedupe_key/
  expires_at/trace_id。Transport固定映射平台方法，不接原始API名。发送前复验权限、
  feature、过期、确认和part状态；领取受控许可为线性化点，之后在途调用不能承诺撤回。
  pause停领取，drain等指定任务集完成，不删除队列；UNKNOWN先对账，无平台幂等时
  不承诺exactly-once。」
- V21-DISPATCH-001 / V21-DELIVERY-001（docs/design/backend-v2-acceptance-matrix.md）
- 风险 5（docs/design/v21-risk-red-report.md）：出站直连坐标清单。

边界（诚实声明）：
- 本模块是**地基**，不是接线。生产迁移由后续席位按
  ``decision/outbound_registry.py`` 的入口接管登记表逐点执行。
- 本模块零 nonebot / 零网络 / 零配置依赖（仅 pydantic + stdlib），可在隔离
  环境独立导入（tests/test_outbound_v21.py 有导入探针）。
- 不承诺 exactly-once：无平台幂等通道的发送，UNKNOWN 只能对账后定性，
  绝不盲重发（``ReconciliationLedger`` 强制）。
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "OPERATION_TRANSITIONS",
    "PART_TRANSITIONS",
    "AdmissionDenied",
    "AdmissionTicket",
    "AdmissionVerdict",
    "CancelOutcome",
    "ConfirmationCheck",
    "DedupeIndex",
    "DrainReport",
    "DuplicateClaim",
    "ExpiryCheck",
    "FeatureGateCheck",
    "IllegalOutboundTransition",
    "LeasePaused",
    "OperationStateCheck",
    "OutboundAdmissionCheck",
    "OutboundAdmissionGate",
    "OutboundIntent",
    "OutboundOperation",
    "OutboundOperationState",
    "OutboundPart",
    "OutboundPartState",
    "OutboundTarget",
    "PartStateCheck",
    "PermissionCheck",
    "PermitLease",
    "PermitToken",
    "ReconciliationLedger",
    "UnknownPendingError",
    "derive_dedupe_key",
    "operation_has_inflight_claim",
    "transition_operation",
    "transition_part",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _StrictModel(BaseModel):
    """extra=forbid（未知字段拒绝）+ 非 float 宽松；有限性逐字段显式校验。"""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# ---------------------------------------------------------------------------
# 枚举与状态机
# ---------------------------------------------------------------------------


class OutboundOperation(str, Enum):
    """出站操作类别（§10 收编面：send/edit/delete/reaction/poke/file/mail）。"""

    SEND_MESSAGE = "send_message"
    SEND_FILE = "send_file"
    SEND_MAIL = "send_mail"
    STICKER = "sticker"
    REACTION = "reaction"
    POKE = "poke"
    EDIT = "edit"
    DELETE = "delete"


class OutboundPartState(str, Enum):
    """part 级状态机：queued→sending→delivered/failed/unknown/cancelled。

    unknown 仅可经对账（reconcile）落到 delivered/failed；failed/cancelled
    为终态，重试 = 构造新 part（旧 part 不复活，审计链不闭环则不重发）。
    """

    QUEUED = "queued"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class OutboundOperationState(str, Enum):
    """operation 级状态机：pending→admitted→running→succeeded/failed/unknown/
    cancelled。cancel_requested ≠ cancelled（见 ``OutboundIntent``）。"""

    PENDING = "pending"
    ADMITTED = "admitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


PART_TRANSITIONS: Mapping[OutboundPartState, frozenset[OutboundPartState]] = {
    OutboundPartState.QUEUED: frozenset(
        {OutboundPartState.SENDING, OutboundPartState.CANCELLED}
    ),
    OutboundPartState.SENDING: frozenset(
        {
            OutboundPartState.DELIVERED,
            OutboundPartState.FAILED,
            OutboundPartState.UNKNOWN,
        }
    ),
    OutboundPartState.DELIVERED: frozenset(),
    OutboundPartState.FAILED: frozenset(),
    # 对账专用出口：unknown 只能经 reconcile 定性，不允许直接重发。
    OutboundPartState.UNKNOWN: frozenset(
        {OutboundPartState.DELIVERED, OutboundPartState.FAILED}
    ),
    OutboundPartState.CANCELLED: frozenset(),
}

OPERATION_TRANSITIONS: Mapping[OutboundOperationState, frozenset[OutboundOperationState]] = {
    OutboundOperationState.PENDING: frozenset(
        {OutboundOperationState.ADMITTED, OutboundOperationState.CANCELLED}
    ),
    OutboundOperationState.ADMITTED: frozenset(
        {OutboundOperationState.RUNNING, OutboundOperationState.CANCELLED}
    ),
    OutboundOperationState.RUNNING: frozenset(
        {
            OutboundOperationState.SUCCEEDED,
            OutboundOperationState.FAILED,
            OutboundOperationState.UNKNOWN,
        }
    ),
    OutboundOperationState.SUCCEEDED: frozenset(),
    OutboundOperationState.FAILED: frozenset(),
    # 对账专用出口：unknown 只能经 reconcile 定性。
    OutboundOperationState.UNKNOWN: frozenset(
        {OutboundOperationState.SUCCEEDED, OutboundOperationState.FAILED}
    ),
    OutboundOperationState.CANCELLED: frozenset(),
}


class IllegalOutboundTransition(Exception):
    """非法状态迁移（拒绝而非静默跳转）。"""

    def __init__(
        self,
        kind: str,
        current: str,
        target: str,
        ident: str = "",
    ) -> None:
        self.kind = kind
        self.current = current
        self.target = target
        self.ident = ident
        super().__init__(
            f"illegal {kind} transition {current} -> {target}"
            + (f" (id={ident})" if ident else "")
        )


def transition_part(
    part: OutboundPart, target: OutboundPartState
) -> OutboundPart:
    """校验并返回迁移后的 part（不可变模型，返回新实例）。"""
    allowed = PART_TRANSITIONS[part.state]
    if target not in allowed:
        raise IllegalOutboundTransition(
            "part", part.state.value, target.value, part.part_id
        )
    return part.model_copy(update={"state": target})


def operation_has_inflight_claim(intent: OutboundIntent) -> bool:
    """任一 part 处于 sending = 已领取且在途调用可能已发出（不可承诺撤回）。"""
    return any(part.state is OutboundPartState.SENDING for part in intent.parts)


def transition_operation(
    intent: OutboundIntent, target: OutboundOperationState
) -> OutboundIntent:
    """校验并返回迁移后的 intent（不可变模型，返回新实例）。

    取消语义：cancel_requested 是标记不是状态；真正落到 CANCELLED 仅允许在
    无在途领取（无 sending part）时发生——领取后在途调用不可承诺撤回（§10）。
    """
    allowed = OPERATION_TRANSITIONS[intent.operation_state]
    if target not in allowed:
        raise IllegalOutboundTransition(
            "operation", intent.operation_state.value, target.value, intent.trace_id
        )
    if (
        target is OutboundOperationState.CANCELLED
        and operation_has_inflight_claim(intent)
    ):
        raise IllegalOutboundTransition(
            "operation",
            intent.operation_state.value,
            target.value,
            intent.trace_id + ":inflight-claim-irreversible",
        )
    return intent.model_copy(update={"operation_state": target})


# ---------------------------------------------------------------------------
# 严格 DTO
# ---------------------------------------------------------------------------


def _require_non_blank(value: str, field: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field} must be non-blank")
    return value


def _require_aware_utc(value: datetime | None, field: str) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware (naive datetime rejected)")
    return value


def _reject_non_finite(value: float | None, field: str) -> float | None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{field} must be finite (NaN/Inf rejected)")
    return value


class OutboundTarget(_StrictModel):
    """出站目标：平台 + 会话形态 + 目标 id（平台原样字符串，不猜测）。"""

    platform: str
    session_type: str  # private / group / channel / email / console（登记表口径）
    target_id: str
    bot_id: str = ""
    adapter: str = ""

    @field_validator("platform", "session_type", "target_id")
    @classmethod
    def _non_blank(cls, value: str, info: Any) -> str:
        return _require_non_blank(value, str(info.field_name))


class OutboundPart(_StrictModel):
    """出站 part：最小投递单元，带独立状态机与平台回执 id。"""

    part_id: str
    kind: str = "text"  # text / image / file / audio / video / sticker / ...
    state: OutboundPartState = OutboundPartState.QUEUED
    # 内容引用（不内联正文本体；渲染/审查产物由上游持引用）。
    content_ref: dict[str, Any] = Field(default_factory=dict)
    provider_message_id: str | None = None
    error_code: str | None = None

    @field_validator("part_id")
    @classmethod
    def _non_blank_part_id(cls, value: str) -> str:
        return _require_non_blank(value, "part_id")


class OutboundIntent(_StrictModel):
    """§10 出站意图唯一载体（严格 DTO）。

    cancel_requested ≠ cancelled：取消请求是**标记**，任何人不得据标记宣称
    「已撤回」；终态取消必须经状态机显式迁移（且无在途领取）。
    """

    operation: OutboundOperation
    target: OutboundTarget
    parts: list[OutboundPart] = Field(min_length=1)
    feature_id: str
    policy_revision: str
    dedupe_key: str
    expires_at: datetime | None = None
    trace_id: str
    operation_state: OutboundOperationState = OutboundOperationState.PENDING
    cancel_requested: bool = False
    created_at: datetime = Field(default_factory=_utc_now)
    # 发送预算等运行时约束（有限浮点；None=未启用）。占位字段同时用于
    # NaN/Inf 拒绝的契约锚点。
    budget_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("feature_id", "policy_revision", "dedupe_key", "trace_id")
    @classmethod
    def _non_blank_ids(cls, value: str, info: Any) -> str:
        return _require_non_blank(value, str(info.field_name))

    @field_validator("expires_at", "created_at")
    @classmethod
    def _aware_datetimes(cls, value: datetime | None, info: Any) -> datetime | None:
        return _require_aware_utc(value, str(info.field_name))

    @field_validator("budget_ms")
    @classmethod
    def _finite_budget(cls, value: float | None) -> float | None:
        return _reject_non_finite(value, "budget_ms")

    @field_validator("parts")
    @classmethod
    def _unique_part_ids(cls, value: list[OutboundPart]) -> list[OutboundPart]:
        ids = [part.part_id for part in value]
        if len(ids) != len(set(ids)):
            raise ValueError("part_id must be unique within an intent")
        return value

    @model_validator(mode="after")
    def _states_consistent(self) -> OutboundIntent:
        if self.operation_state in (
            OutboundOperationState.PENDING,
            OutboundOperationState.ADMITTED,
        ):
            for part in self.parts:
                if part.state not in (
                    OutboundPartState.QUEUED,
                    OutboundPartState.CANCELLED,
                ):
                    raise ValueError(
                        "operation pending/admitted requires all parts queued/cancelled; "
                        f"part {part.part_id} is {part.state.value}"
                    )
        if self.cancel_requested and self.operation_state in (
            OutboundOperationState.SUCCEEDED,
            OutboundOperationState.FAILED,
        ):
            raise ValueError(
                "cancel_requested must not be set on a settled operation "
                "(cancel_requested is not cancelled)"
            )
        return self


# ---------------------------------------------------------------------------
# 出站准入协议（发送前复验）
# ---------------------------------------------------------------------------


class AdmissionVerdict(_StrictModel):
    """单个复验钩子的裁决。allow=False 时 reason_code 必填。"""

    check_name: str
    allow: bool
    reason_code: str | None = None
    detail: str = ""

    @model_validator(mode="after")
    def _deny_requires_reason(self) -> AdmissionVerdict:
        if not self.allow and not (self.reason_code and self.reason_code.strip()):
            raise ValueError("deny verdict requires reason_code")
        return self


class AdmissionDenied(Exception):
    """准入拒绝（携带首个拒绝钩子与其 reason_code）。"""

    def __init__(self, verdict: AdmissionVerdict) -> None:
        self.verdict = verdict
        super().__init__(f"admission denied by {verdict.check_name}: {verdict.reason_code}")


class OutboundAdmissionCheck(Protocol):
    """发送前复验钩子接口：权限 / feature 开关 / 过期 / 确认 / part 状态。

    实现必须为**纯校验**（无副作用、无发送、无阻塞 IO）；异步资源查询由
    接线席位在钩子外预取后以闭包注入。
    """

    name: str

    def check(self, intent: OutboundIntent) -> AdmissionVerdict: ...


class ExpiryCheck:
    """过期复验：expires_at 已过 → 拒绝（绝不发送过期意图）。"""

    name = "expiry"

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(timezone.utc))

    def check(self, intent: OutboundIntent) -> AdmissionVerdict:
        if intent.expires_at is not None and intent.expires_at <= self._now():
            return AdmissionVerdict(
                check_name=self.name, allow=False, reason_code="expired"
            )
        return AdmissionVerdict(check_name=self.name, allow=True)


class PartStateCheck:
    """part 状态复验：仅全部 QUEUED 的意图可准入（PARTIAL 断点续发走新意图）。"""

    name = "part_state"

    def check(self, intent: OutboundIntent) -> AdmissionVerdict:
        bad = [p.part_id for p in intent.parts if p.state is not OutboundPartState.QUEUED]
        if bad:
            return AdmissionVerdict(
                check_name=self.name,
                allow=False,
                reason_code="parts_not_queued",
                detail=",".join(bad)[:200],
            )
        return AdmissionVerdict(check_name=self.name, allow=True)


class OperationStateCheck:
    """operation 状态复验：仅 PENDING/ADMITTED 可进入发送准备。"""

    name = "operation_state"
    _allowed = frozenset(
        {OutboundOperationState.PENDING, OutboundOperationState.ADMITTED}
    )

    def check(self, intent: OutboundIntent) -> AdmissionVerdict:
        if intent.operation_state not in self._allowed:
            return AdmissionVerdict(
                check_name=self.name,
                allow=False,
                reason_code="operation_not_admittable",
                detail=intent.operation_state.value,
            )
        return AdmissionVerdict(check_name=self.name, allow=True)


class FeatureGateCheck:
    """feature 开关复验：``is_enabled(feature_id)`` 为假 → 拒绝。

    谓词由接线席位注入（runtime/feature_gate 等），本模块不绑实现。
    """

    name = "feature_gate"

    def __init__(self, is_enabled: Callable[[str], bool]) -> None:
        self._is_enabled = is_enabled

    def check(self, intent: OutboundIntent) -> AdmissionVerdict:
        if not self._is_enabled(intent.feature_id):
            return AdmissionVerdict(
                check_name=self.name,
                allow=False,
                reason_code="feature_disabled",
                detail=intent.feature_id,
            )
        return AdmissionVerdict(check_name=self.name, allow=True)


class PermissionCheck:
    """权限复验：``allowed(intent)`` 为假 → 拒绝（谓词由接线席位注入）。"""

    name = "permission"

    def __init__(self, allowed: Callable[[OutboundIntent], bool]) -> None:
        self._allowed = allowed

    def check(self, intent: OutboundIntent) -> AdmissionVerdict:
        if not self._allowed(intent):
            return AdmissionVerdict(
                check_name=self.name, allow=False, reason_code="permission_denied"
            )
        return AdmissionVerdict(check_name=self.name, allow=True)


class ConfirmationCheck:
    """确认复验（ADMIN_CONFIRM 类策略）：``confirmed(intent)`` 为假 → 拒绝。

    确认凭据建议绑定内容 hash/目标/policy_revision——修改使旧确认失效
    （§10 workspace 确认语义同源），由接线席位实现谓词。
    """

    name = "confirmation"

    def __init__(self, confirmed: Callable[[OutboundIntent], bool]) -> None:
        self._confirmed = confirmed

    def check(self, intent: OutboundIntent) -> AdmissionVerdict:
        if not self._confirmed(intent):
            return AdmissionVerdict(
                check_name=self.name, allow=False, reason_code="confirmation_missing"
            )
        return AdmissionVerdict(check_name=self.name, allow=True)


class AdmissionTicket(_StrictModel):
    """准入通过凭据：钉住准入时刻的 policy_revision（审计对账锚点）。"""

    dedupe_key: str
    trace_id: str
    feature_id: str
    policy_revision: str
    admitted_at: datetime = Field(default_factory=_utc_now)
    passed_checks: list[str] = Field(default_factory=list)


class OutboundAdmissionGate:
    """准入门：按固定顺序跑全部复验钩子，首个拒绝即短路。

    固定顺序 = expiry → part_state → operation_state → feature_gate →
    permission → confirmation（探测成本低者在前；顺序在构造时冻结并可审计）。
    准入通过后调用方仍须取得许可租约（线性化点在 ``PermitLease.acquire``）。
    """

    def __init__(self, checks: Sequence[OutboundAdmissionCheck] | None = None) -> None:
        if checks is None:
            checks = [
                ExpiryCheck(),
                PartStateCheck(),
                OperationStateCheck(),
            ]
        self._checks = list(checks)

    @property
    def check_order(self) -> list[str]:
        return [check.name for check in self._checks]

    def admit(self, intent: OutboundIntent) -> AdmissionTicket:
        passed: list[str] = []
        for check in self._checks:
            verdict = check.check(intent)
            if not verdict.allow:
                raise AdmissionDenied(verdict)
            passed.append(check.name)
        return AdmissionTicket(
            dedupe_key=intent.dedupe_key,
            trace_id=intent.trace_id,
            feature_id=intent.feature_id,
            policy_revision=intent.policy_revision,
            passed_checks=passed,
        )


# ---------------------------------------------------------------------------
# 许可租约（领取受控许可 = 线性化点）
# ---------------------------------------------------------------------------


class LeasePaused(Exception):
    """租约已 pause：停发新许可（停领取，不删队列）。"""


class DuplicateClaim(Exception):
    """同一 key 的许可已被领取且未释放（并发 claim 唯一性的显式失败面）。"""

    def __init__(self, key: str, holder: str) -> None:
        self.key = key
        self.holder = holder
        super().__init__(f"permit already claimed: key={key} holder={holder}")


class CancelOutcome(_StrictModel):
    """取消尝试结果。granted=False 时不可宣称撤回（理由显式）。"""

    granted: bool
    reason: str  # cancelled / irreversible_inflight / not_held / ...


class PermitToken(_StrictModel):
    """一次领取的凭证（不可变；释放/不可逆标记由租约管理）。"""

    key: str
    holder: str
    acquired_monotonic: float
    irreversible: bool = False

    def try_cancel(self) -> CancelOutcome:
        """Token 侧视图：不可逆标记后取消一律拒绝（在途调用不可承诺撤回）。

        真正的取消执行（释放租约等）走 ``PermitLease.cancel``；本方法只做
        无副作用的语义判定，供审计与测试断言。
        """
        if self.irreversible:
            return CancelOutcome(
                granted=False, reason="irreversible_inflight_call"
            )
        return CancelOutcome(granted=True, reason="pre_dispatch_cancel")


class DrainReport(_StrictModel):
    """drain 结果：仅等待指定任务集完成，**不含任何队列删除**。"""

    waited_keys: list[str]
    completed: list[str]
    timed_out: list[str]
    elapsed_ms: float = Field(default=0.0)

    @field_validator("elapsed_ms")
    @classmethod
    def _finite_elapsed(cls, value: float) -> float:
        return _reject_non_finite(value, "elapsed_ms") or 0.0


class PermitLease:
    """受控许可租约。

    语义（§10 逐条落点）：
    - **线性化点**：``acquire`` 的临界区（lock 保护）。同一 key 并发 claim
      恰有一个胜者；acquire 返回即代表「该意图已领取，准备派发」。
    - **pause**：停发新许可（停领取）；已领取的不受影响；**不删队列**——
      本类根本不持队列，pause 只关闸门。
    - **drain(keys)**：等待指定任务集全部释放（完成），超时如实上报；
      同样不删队列。
    - **claim→irreversible**：派发真实平台调用前调 ``mark_irreversible``；
      标记后 ``cancel`` 拒绝（在途调用不可承诺撤回），只能等结果落状态机。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._paused = False
        self._inflight: dict[str, PermitToken] = {}

    # -- 闸门 ---------------------------------------------------------------
    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    # -- 领取 / 释放 ---------------------------------------------------------
    def acquire(self, key: str, *, holder: str = "") -> PermitToken:
        """领取许可（线性化点）。paused→LeasePaused；key 已被领取→DuplicateClaim。"""
        if not key or not key.strip():
            raise ValueError("permit key must be non-blank")
        with self._cond:
            if self._paused:
                raise LeasePaused("permit lease is paused: not claiming new tasks")
            if key in self._inflight:
                raise DuplicateClaim(key, self._inflight[key].holder)
            token = PermitToken(
                key=key,
                holder=holder,
                acquired_monotonic=time.monotonic(),
            )
            self._inflight[key] = token
            return token

    def release(self, token: PermitToken) -> None:
        with self._cond:
            held = self._inflight.get(token.key)
            if held is None or held.holder != token.holder:
                raise KeyError(f"permit not held by {token.holder!r}: {token.key}")
            del self._inflight[token.key]
            self._cond.notify_all()

    def mark_irreversible(self, token: PermitToken) -> PermitToken:
        """claim→irreversible 标记：此后在途调用不可承诺撤回（§10 原文语义）。

        返回带标记的新 token；调用方应以返回值继续持有。
        """
        marked = token.model_copy(update={"irreversible": True})
        with self._lock:
            current = self._inflight.get(token.key)
            if current is None or current.holder != token.holder:
                raise KeyError(f"permit not held by {token.holder!r}: {token.key}")
            self._inflight[token.key] = marked
        return marked

    def cancel(self, token: PermitToken) -> CancelOutcome:
        """取消领取：未 irreversible → 释放并批准；已 irreversible → 拒绝。"""
        if token.irreversible:
            return CancelOutcome(granted=False, reason="irreversible_inflight_call")
        try:
            self.release(token)
        except KeyError:
            return CancelOutcome(granted=False, reason="not_held")
        return CancelOutcome(granted=True, reason="cancelled_before_dispatch")

    # -- drain ---------------------------------------------------------------
    def drain(
        self,
        keys: Iterable[str] | None = None,
        *,
        timeout_s: float | None = None,
    ) -> DrainReport:
        """等待指定任务集（默认全部在途）释放完成；**不删除任何队列内容**。

        timeout_s=None 表示无限等待；超时的 key 如实进 timed_out（不撒谎）。
        """
        wanted = list(keys) if keys is not None else None
        start = time.monotonic()
        with self._cond:
            # waited 集合在等待前定格：wanted 显式给定用 wanted；
            # 未给定（等全部）则快照当前全量在途 key（等待完成后原集不可再恢复）。
            waited = wanted if wanted is not None else sorted(self._inflight)

            def _pending() -> list[str]:
                inflight_keys = list(self._inflight)
                if wanted is None:
                    return inflight_keys
                return [k for k in wanted if k in self._inflight]

            if timeout_s is None:
                while _pending():
                    self._cond.wait(timeout=0.5)
            else:
                deadline = start + timeout_s
                while _pending():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._cond.wait(timeout=min(remaining, 0.5))
            pending = _pending()
            completed = [k for k in waited if k not in set(pending)]
        elapsed_ms = (time.monotonic() - start) * 1000.0
        return DrainReport(
            waited_keys=waited,
            completed=completed,
            timed_out=pending,
            elapsed_ms=elapsed_ms,
        )

    def inflight_keys(self) -> list[str]:
        with self._lock:
            return sorted(self._inflight)


# ---------------------------------------------------------------------------
# 同事件同幂等键去重 + UNKNOWN 对账
# ---------------------------------------------------------------------------


def derive_dedupe_key(platform: str, event_id: str, entry_kind: str) -> str:
    """幂等键 = 来源平台 + 事件 id + 入口 kind 的确定性派生。

    - 确定性：同三元组恒同键（无时间、无随机、无 dict 序）。
    - 跨入口不碰撞：entry_kind 进入键体——同事件经不同入口（如 matcher 与
      scheduler）产生不同键，互不吞并。
    - 「同事件同幂等键」：同平台+同事件+同入口重复投递 → 同键 → 去重。
    """
    for name, value in (("platform", platform), ("event_id", event_id), ("entry_kind", entry_kind)):
        if not value or not value.strip():
            raise ValueError(f"dedupe key component {name!r} must be non-blank")
        if any(ch in value for ch in (":", "\n", "\r")):
            raise ValueError(
                f"dedupe key component {name!r} must not contain ':' or newlines"
            )
    return f"{platform}:{entry_kind}:{event_id}"


class DedupeIndex:
    """同事件同幂等键去重索引（线程安全，先到先得）。

    只做键级判定；不持队列、不定性结果（结果定性走 ``ReconciliationLedger``）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[str, str] = {}  # key -> 首见 holder/说明

    def claim_first(self, key: str, holder: str = "") -> bool:
        """首个返回 True（获得发送权）；重复同键返回 False（去重）。"""
        if not key or not key.strip():
            raise ValueError("dedupe key must be non-blank")
        with self._lock:
            if key in self._seen:
                return False
            self._seen[key] = holder
            return True

    def first_holder(self, key: str) -> str | None:
        with self._lock:
            return self._seen.get(key)


class UnknownPendingError(Exception):
    """UNKNOWN 未对账即请求重发：拒绝（先对账，不盲重发）。"""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(
            f"UNKNOWN outcome pending reconciliation, retry forbidden: key={key}"
        )


class ReconciliationLedger:
    """UNKNOWN 对账台账：UNKNOWN 只能经对账定性，定性前禁止重试。

    §10 原文：「UNKNOWN先对账，无平台幂等时不承诺exactly-once」——本台账把
    「不盲重发」做成硬门：``assert_may_retry`` 在存在未对账 UNKNOWN 时抛
    ``UnknownPendingError``。定性后（delivered/failed）门开；delivered 定性
    意味着重发即重复，调用方应据此拒绝重发（键已在 DedupeIndex）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, str] = {}  # key -> 取证坐标/说明
        self._resolved: dict[str, str] = {}  # key -> delivered/failed

    def record_unknown(self, key: str, coordinate: str = "") -> None:
        """发送结果未知（超时/断连/无回执）→ 记入待对账。"""
        if not key or not key.strip():
            raise ValueError("dedupe key must be non-blank")
        with self._lock:
            self._pending[key] = coordinate

    def is_pending(self, key: str) -> bool:
        with self._lock:
            return key in self._pending

    def reconcile(self, key: str, final_state: str) -> str:
        """对账定性：final_state ∈ {delivered, failed}；未记录的 key 拒绝。"""
        normalized = final_state.strip().lower()
        if normalized not in ("delivered", "failed"):
            raise ValueError(
                "reconcile final_state must be 'delivered' or 'failed', "
                f"got {final_state!r}"
            )
        with self._lock:
            if key not in self._pending:
                raise KeyError(f"no pending UNKNOWN for key: {key}")
            del self._pending[key]
            self._resolved[key] = normalized
        return normalized

    def assert_may_retry(self, key: str) -> None:
        """重发前置断言：存在未对账 UNKNOWN → UnknownPendingError。"""
        with self._lock:
            if key in self._pending:
                raise UnknownPendingError(key)

    def resolved_state(self, key: str) -> str | None:
        with self._lock:
            return self._resolved.get(key)

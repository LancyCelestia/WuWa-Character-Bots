"""AcceptanceRunner：一次授权驱动的自动场景执行引擎（V21-ACCEPTANCE-001 唯一载体）。

背景：验收此前只有 ``scripts/e2e_acceptance.py`` 手工触发脚本，没有「授权包→
场景计划→串行执行→证据报告」的引擎。本模块把这条链路收拢成依赖可注入、
全离线确定性可测的骨架（ACC 席新建件；合同=backend-v2-product-extensions.md
§8.1/§8.2 + 验收矩阵 V21-ACCEPTANCE-001）。

合同逐条对齐：

- **授权包**（§8.1 ``AcceptanceAuthorization`` 字段一一落位）：id/principal/
  admin 收件人/目标白名单/场景白名单/provider 白名单/按币种金额预算+单项上限/
  调用次数上限/max_assets/时间窗/data_scope/maintenance_actions/revoke_version。
  **默认拒绝未列动作**：目标白名单空=禁一切发送；场景白名单空=禁一切场景；
  provider 白名单空=禁一切带 provider 的调用。
- **串行执行**（§8.2）：步依序跑，绝无并发分发、绝不扫描联系人随意发送。
- **边界闸**：每步分发前过五道闸——撤销→时间窗→目标授权→provider 授权→
  预算；任一拒绝即停，剩余步 skipped。**撤销只停在分发边界**：在途步骤
  （已 deliver 的调用）跑完才停，不强杀已发出。
- **预算**：成本在真实 attempt 发生即扣（失败回执也计，合同「每真实 attempt
  采集」「取消保留已计费 attempt」）；``TransportNotWired`` = 未发生 attempt
  不扣。超预算步骤拒执行。
- **层级单独记录**（§8.2 L0-L4）：场景声明 level，报告逐 run 原样记录。
- **blocked/skipped/unknown 不得算 pass**：RunStatus 只有 passed/failed/blocked
  三态；中断即 blocked。
- **不把 fake 结果混入 live**：报告原样记录 transport 类名与层级；真实
  transport 本轮未接线——``NotWiredTransport`` 诚实抛 ``TransportNotWired``，
  步标 ``not_wired``，绝不伪称通过（live_validation=unknown）。
- **幂等**：transport 按 ``idempotency_key`` 去重（mock 返回 duplicated=True，
  真实发送数不增）；runner 同 ``run_id`` 重跑返回缓存报告零重发。SQLite
  持久化与「重启续跑不重发成功 part」属后续接线席（本骨架为内存级，如实）。
- **脱敏**：报告内 payload/detail/error 全走结构化脱敏+render 真身
  ``redact_local_secrets`` 懒加载（失败落本地兜底正则，incident/service.py
  同构，不跨席依赖）。

职责边界（克制原则）：

- 骨架不做：真实出站、报告持久化/30 天保留、资产接口、SSE、控制面 REST、
  场景重试 attempt 历史——均属 §8.2 后续接线，接口面已留（transport Protocol、
  run_id、build_id/manifest_revision 透传字段）。
- 无新增 config 键：全部阈值为构造参数/DTO 字段（recovery 先例，热调由
  装配席注入）。

用法::

    from plugins.bot_unified_runtime.domains.ops.acceptance import (
        AcceptanceRunner,
        AuthorizationPackage,
        MockAcceptanceTransport,
    )
    from plugins.bot_unified_runtime.domains.ops.acceptance.scenarios import (
        build_send_queue_roundtrip_scenario,
    )

    auth = AuthorizationPackage(
        authorization_id="auth-1",
        principal="super_admin",
        admin_recipients=("10001",),
        allowed_targets=("mock:send_queue",),
        allowed_scenarios=("send_queue_roundtrip_mock",),
        provider_allowlist=("queue_local",),
        max_requests=10,
        budget_by_currency={"CNY": Decimal("1.00")},
    )
    runner = AcceptanceRunner()
    report = runner.run(
        build_send_queue_roundtrip_scenario(), auth, MockAcceptanceTransport()
    )
    assert report.status is RunStatus.PASSED
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_CURRENCY",
    "AcceptanceRunner",
    "AcceptanceTransport",
    "AssertionContext",
    "AssertionFn",
    "AuthorizationPackage",
    "AuthorizationRequired",
    "BudgetLedger",
    "BudgetSnapshot",
    "MockAcceptanceTransport",
    "NotWiredTransport",
    "RevocationToken",
    "RunReport",
    "RunStatus",
    "ScenarioPlan",
    "ScenarioStep",
    "StepKind",
    "StepResult",
    "StepStatus",
    "StopReason",
    "TransportNotWired",
    "TransportReceipt",
    "TransportRequest",
    "redact_mapping",
    "redact_text",
]

#: 默认计价币种（合同 §8.1 按币种预算；缺省 CNY 与账单口径一致）。
DEFAULT_CURRENCY = "CNY"

Clock = Callable[[], datetime]


# ---------------------------------------------------------------------------
# 枚举与状态
# ---------------------------------------------------------------------------


class StepKind(str, Enum):
    """步骤种类：能力调用（经 transport，耗预算）或本地断言（零成本零出站）。"""

    CALL = "call"
    ASSERT = "assert"


class StepStatus(str, Enum):
    """逐步状态。拒绝类=该步未发生任何 attempt；skipped=引擎停机后未跑到。"""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    REJECTED_BUDGET = "rejected_budget"
    REJECTED_WINDOW = "rejected_window"
    REJECTED_REVOKED = "rejected_revoked"
    REJECTED_NOT_AUTHORIZED = "rejected_not_authorized"
    NOT_WIRED = "not_wired"
    SKIPPED_NOT_RUN = "skipped_not_run"


class StopReason(str, Enum):
    """run 停机原因。COMPLETED=全部步执行完毕。"""

    COMPLETED = "completed"
    STEP_FAILED = "step_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    WINDOW_CLOSED = "window_closed"
    REVOKED = "revoked"
    NOT_AUTHORIZED = "not_authorized"
    NOT_WIRED = "not_wired"


class RunStatus(str, Enum):
    """run 总状态（合同：blocked/skipped/unknown 不得算 pass，故三态互斥）。"""

    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class AuthorizationRequired(RuntimeError):
    """无授权包拒绝启动（合同 §8.1：默认拒绝未列动作）。"""


# ---------------------------------------------------------------------------
# 传输层（Protocol 注入；真实 transport 本轮不接=not_wired）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransportRequest:
    """出站请求（引擎构造；payload 已在步内冻结拷贝）。"""

    action: str
    target: str
    payload: Mapping[str, Any]
    idempotency_key: str
    trace_id: str


@dataclass(frozen=True)
class TransportReceipt:
    """传输回执。duplicated=True 表示命中幂等键、未产生新的真实发送。"""

    accepted: bool
    receipt_id: str
    trace_id: str
    duplicated: bool = False
    detail: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None


class TransportNotWired(RuntimeError):
    """真实出站端口未接线（本轮合同禁真实出站；诚实上抛不伪装）。"""


@runtime_checkable
class AcceptanceTransport(Protocol):
    """传输注入面：离线=MockAcceptanceTransport；真实=后续接线席实现本协议。"""

    def deliver(self, request: TransportRequest) -> TransportReceipt:
        """执行一次出站 attempt（同步；引擎串行调用，绝不并发）。"""
        ...


class MockAcceptanceTransport:
    """离线 fake transport（L1 层级）：确定性、零网络零线程零等待。

    - 按 ``idempotency_key`` 去重：同键二次请求返回首笔回执、
      ``duplicated=True``，真实发送计数不增；
    - ``fail_actions``/``fail_keys`` 可脚本化失败（按 action 或幂等键命中）；
    - ``on_deliver`` 钩子可在真实 deliver 语义内执行副作用（如测试中置位
      撤销令牌，模拟「撤销发生在在途调用期间」）；
    - ``detail`` 附带 ``mock_deliver_count``/``mock_send_count`` 供断言面。
    """

    def __init__(
        self,
        *,
        fail_actions: Mapping[str, str] | None = None,
        fail_keys: Mapping[str, str] | None = None,
        on_deliver: Callable[[TransportRequest], None] | None = None,
    ) -> None:
        self.fail_actions = dict(fail_actions or {})
        self.fail_keys = dict(fail_keys or {})
        self.on_deliver = on_deliver
        self.requests: list[TransportRequest] = []
        self.receipts: list[TransportReceipt] = []
        self._receipts_by_key: dict[str, TransportReceipt] = {}
        self._seq = 0

    @property
    def deliver_count(self) -> int:
        """deliver 被调次数（含幂等命中；真实 attempt 数用 send_count）。"""
        return len(self.requests)

    @property
    def send_count(self) -> int:
        """真实 attempt 数（幂等命中不重复计数）。"""
        return len(self.receipts)

    def deliver(self, request: TransportRequest) -> TransportReceipt:
        self.requests.append(request)
        if self.on_deliver is not None:
            self.on_deliver(request)
        seen = self._receipts_by_key.get(request.idempotency_key)
        if seen is not None:
            return TransportReceipt(
                accepted=seen.accepted,
                receipt_id=seen.receipt_id,
                trace_id=seen.trace_id,
                duplicated=True,
                detail={
                    **dict(seen.detail),
                    "mock_deliver_count": self.deliver_count,
                    "mock_send_count": self.send_count,
                },
                error=seen.error,
            )
        error = self.fail_keys.get(request.idempotency_key) or self.fail_actions.get(
            request.action
        )
        self._seq += 1
        accepted = error is None
        receipt = TransportReceipt(
            accepted=accepted,
            receipt_id=f"rcpt-{self._seq:04d}",
            trace_id=request.trace_id,
            detail={
                "mock_deliver_count": self.deliver_count,
                "mock_send_count": self.send_count + 1,
            },
            error=error,
        )
        self.receipts.append(receipt)
        self._receipts_by_key[request.idempotency_key] = receipt
        return receipt


class NotWiredTransport:
    """真实出站占位：deliver 一律抛 :class:`TransportNotWired`。

    本轮合同禁真实出站（live_validation=unknown）；接线席以真实
    transport 实现同一 :class:`AcceptanceTransport` 协议替换本类，
    引擎侧零改动。
    """

    def deliver(self, request: TransportRequest) -> TransportReceipt:
        raise TransportNotWired(
            "acceptance: 真实出站 transport 未接线（not_wired）；"
            "本轮合同 mock-only，不做真实发送"
        )

# ---------------------------------------------------------------------------
# 授权包与撤销令牌
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthorizationPackage:
    """授权包（合同 §8.1 ``AcceptanceAuthorization`` 对齐，默认拒绝未列动作）。

    字段对照：id→authorization_id、principal→principal、admin 收件人→
    admin_recipients、allowed_targets→allowed_targets（平台白名单目标）、
    allowed_scenarios→allowed_scenarios、provider_allowlist→provider_allowlist、
    currency_budgets→budget_by_currency、单项上限→per_call_max、
    max_requests→max_requests、max_assets→max_assets、valid_from/to→
    valid_from/valid_to、maintenance_actions→maintenance_actions、
    data_scope→data_scope、revoke_version→revoke_version（+revoked 预置位）。

    撤销语义：``revoked=True`` 为预置撤销（run 启动即拒绝）；运行期撤销走
    :class:`RevocationToken` 句柄（可变，传给 ``runner.run``），两者任一置位
    即停——在途步骤完成后停止，不强杀已发出。
    """

    authorization_id: str
    principal: str
    admin_recipients: tuple[str, ...] = ()
    allowed_targets: tuple[str, ...] = ()
    allowed_scenarios: tuple[str, ...] = ()
    provider_allowlist: tuple[str, ...] = ()
    max_requests: int = 0
    budget_by_currency: Mapping[str, Decimal] = field(default_factory=dict)
    per_call_max: Mapping[str, Decimal] = field(default_factory=dict)
    max_assets: int = 0
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    maintenance_actions: tuple[str, ...] = ()
    data_scope: str = "sandbox_only"
    revoked: bool = False
    revoke_version: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "budget_by_currency", _as_decimal_map(self.budget_by_currency)
        )
        object.__setattr__(self, "per_call_max", _as_decimal_map(self.per_call_max))

    def window_open_at(self, now: datetime) -> bool:
        return not (
            (self.valid_from is not None and now < _ensure_aware(self.valid_from))
            or (self.valid_to is not None and now >= _ensure_aware(self.valid_to))
        )


class RevocationToken:
    """运行期撤销令牌：置位后引擎在下一分发边界立即停止后续分发。

    只置位不回绕（撤销不可逆；续期走新授权包）。在途步骤（已 deliver 的
    调用）不被强杀，跑完后引擎停。
    """

    def __init__(self, reason: str = "") -> None:
        self._revoked = False
        self._reason = reason
        self._revoked_at: datetime | None = None

    def revoke(self, reason: str = "") -> None:
        """置位撤销（幂等；后调的 reason 不覆盖先记的）。"""
        if not self._revoked:
            self._reason = reason or self._reason or "revoked"
            self._revoked = True
            self._revoked_at = datetime.now(timezone.utc)

    @property
    def is_revoked(self) -> bool:
        return self._revoked

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def revoked_at(self) -> datetime | None:
        return self._revoked_at


# ---------------------------------------------------------------------------
# 场景计划
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssertionContext:
    """断言求值上下文（只读视图；transport 仅暴露统计/回执，不暴露写入口）。"""

    run_id: str
    scenario_id: str
    step_id: str
    payload: Mapping[str, Any]
    results: Mapping[str, StepResult]
    receipts: Mapping[str, TransportReceipt]
    transport: Any = None

    def send_count(self) -> int | None:
        """真实 attempt 数（mock 语义；transport 未暴露时 None=unknown）。"""
        count = getattr(self.transport, "send_count", None)
        return count if isinstance(count, int) else None


AssertionFn = Callable[[AssertionContext], tuple[bool, str]]


@dataclass(frozen=True)
class ScenarioStep:
    """场景步：能力调用（CALL，耗预算、过五道闸）或本地断言（ASSERT）。

    ``cost_requests``/``cost_by_currency`` 为预算扣减声明；断言签名
    ``AssertionFn`` 收到 :class:`AssertionContext` 返回 (ok, detail)。
    """

    step_id: str
    kind: StepKind
    action: str = ""
    target: str = ""
    provider: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    cost_requests: int = 0
    cost_by_currency: Mapping[str, Decimal] = field(default_factory=dict)
    assertion: AssertionFn | None = None
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(
            self, "cost_by_currency", _as_decimal_map(self.cost_by_currency)
        )


@dataclass(frozen=True)
class ScenarioPlan:
    """有序场景计划（合同 §8.2 注册 Scenario 的最小形态；level 单独记录）。"""

    scenario_id: str
    title: str
    level: str
    steps: tuple[ScenarioStep, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))


# ---------------------------------------------------------------------------
# 预算账
# ---------------------------------------------------------------------------


def _as_decimal_map(raw: Mapping[str, Any]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for key, value in raw.items():
        try:
            out[str(key)] = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"预算金额非法: {key}={value!r}") from exc
    return out


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass
class BudgetLedger:
    """预算账：调用次数 + 按币种金额（含单项上限）；attempt 发生即记账。"""

    max_requests: int
    budget_by_currency: Mapping[str, Decimal] = field(default_factory=dict)
    per_call_max: Mapping[str, Decimal] = field(default_factory=dict)
    used_requests: int = 0
    used_by_currency: dict[str, Decimal] = field(default_factory=dict)

    @classmethod
    def from_authorization(cls, auth: AuthorizationPackage) -> BudgetLedger:
        return cls(
            max_requests=auth.max_requests,
            budget_by_currency=dict(_as_decimal_map(auth.budget_by_currency)),
            per_call_max=dict(_as_decimal_map(auth.per_call_max)),
        )

    def check(self, step: ScenarioStep) -> str | None:
        """预检：可负担返回 None；否则返回拒绝原因（不记账）。"""
        if step.kind is not StepKind.CALL:
            return None
        if self.used_requests + step.cost_requests > self.max_requests:
            return (
                f"调用次数超预算: {self.used_requests}+{step.cost_requests}"
                f">{self.max_requests}"
            )
        for currency, cost in step.cost_by_currency.items():
            cap = self.per_call_max.get(currency)
            if cap is not None and cost > cap:
                return f"单项超上限[{currency}]: {cost}>{cap}"
            budget = self.budget_by_currency.get(currency)
            if budget is None:
                if cost > 0:
                    return f"币种未授权[{currency}]: 金额 {cost} 无预算"
                continue
            used = self.used_by_currency.get(currency, Decimal(0))
            if used + cost > budget:
                return f"金额超预算[{currency}]: {used}+{cost}>{budget}"
        return None

    def apply(self, step: ScenarioStep) -> None:
        """记账（真实 attempt 发生即调，失败回执也计）。"""
        self.used_requests += step.cost_requests
        for currency, cost in step.cost_by_currency.items():
            self.used_by_currency[currency] = (
                self.used_by_currency.get(currency, Decimal(0)) + cost
            )

    def snapshot(self) -> BudgetSnapshot:
        remaining = {
            currency: budget - self.used_by_currency.get(currency, Decimal(0))
            for currency, budget in self.budget_by_currency.items()
        }
        return BudgetSnapshot(
            max_requests=self.max_requests,
            used_requests=self.used_requests,
            used_by_currency=dict(self.used_by_currency),
            remaining_by_currency=remaining,
        )


@dataclass(frozen=True)
class BudgetSnapshot:
    """报告内预算快照（合同 §8.2 AcceptanceRun.budget 最小形态）。"""

    max_requests: int
    used_requests: int
    used_by_currency: Mapping[str, Decimal] = field(default_factory=dict)
    remaining_by_currency: Mapping[str, Decimal] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 脱敏（render 真身懒加载 + 本地兜底；incident/service.py 同构不跨席依赖）
# ---------------------------------------------------------------------------

_SECRET_KEY_RE = re.compile(
    r"(?i)(token|secret|api_?key|password|authorization|cookie|credential)"
)
_FALLBACK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_-]{6,}"),
    re.compile(r"BOT_[A-Z0-9_]{2,}\s*=\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{6,}"),
)

_REDACT_FN: Callable[[str], str] | None = None
_REDACT_TRIED = False


def _load_redactor() -> Callable[[str], str] | None:
    """render 真身 ``redact_local_secrets`` 懒加载（不可用→None 走兜底）。"""
    global _REDACT_FN, _REDACT_TRIED
    if _REDACT_TRIED:
        return _REDACT_FN
    _REDACT_TRIED = True
    try:
        from plugins.bot_unified_runtime.domains.render.plain_text import (
            redact_local_secrets as _fn,
        )

        _REDACT_FN = _fn
    except Exception:  # noqa: BLE001 - fail-open：脱敏兜底必须可用
        logger.warning("acceptance: redact_local_secrets unavailable, fallback on")
        _REDACT_FN = None
    return _REDACT_FN


def _fallback_redact(text: str) -> str:
    out = text
    for pattern in _FALLBACK_PATTERNS:
        out = pattern.sub("***", out)
    return out


def redact_text(text: str | None, *, max_chars: int = 500) -> str:
    """自由文本脱敏入口（render 真身优先，兜底正则；失败再兜一层）。"""
    if not text:
        return ""
    value = text[:max_chars]
    try:
        fn = _load_redactor()
        value = (fn or _fallback_redact)(value)
    except Exception:
        logger.exception("acceptance: redaction failed, using fallback patterns")
        value = _fallback_redact(value)
    return value


def redact_mapping(value: Any) -> Any:
    """结构化脱敏：secret 形键→``***``；str 值过 redact_text；容器递归。"""
    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY_RE.search(key):
                out[key] = "***"
            else:
                out[key] = redact_mapping(item)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_mapping(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


# ---------------------------------------------------------------------------
# 执行报告
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepResult:
    """逐步结果（payload 已脱敏；trace/receipt 关联合同 §8.2 证据面）。"""

    step_id: str
    kind: StepKind
    status: StepStatus
    detail: str = ""
    trace_id: str | None = None
    receipt_id: str | None = None
    accepted: bool | None = None
    duplicated: bool | None = None
    cost_requests: int = 0
    cost_by_currency: Mapping[str, Decimal] = field(default_factory=dict)
    redacted_payload: Mapping[str, Any] = field(default_factory=dict)
    detail_map: Mapping[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class RunReport:
    """执行报告（合同 §8.2 AcceptanceRun 骨架最小形态，脱敏后出账）。"""

    run_id: str
    scenario_id: str
    scenario_title: str
    level: str
    authorization_id: str
    transport: str
    status: RunStatus
    stop_reason: StopReason
    started_at: datetime
    finished_at: datetime
    steps: tuple[StepResult, ...] = ()
    budget: BudgetSnapshot | None = None
    trace_ids: tuple[str, ...] = ()
    build_id: str = "unknown"
    manifest_revision: str = "unknown"
    notes: tuple[str, ...] = ()

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for step in self.steps:
            counts[step.status.value] = counts.get(step.status.value, 0) + 1
        return counts

    def to_summary(self) -> dict[str, Any]:
        """摘要（供 admin 通知/控制面投影；已脱敏字段再导出安全）。"""
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "level": self.level,
            "authorization_id": self.authorization_id,
            "transport": self.transport,
            "status": self.status.value,
            "stop_reason": self.stop_reason.value,
            "status_counts": self.status_counts(),
            "budget": {
                "used_requests": self.budget.used_requests if self.budget else None,
                "remaining_by_currency": dict(
                    self.budget.remaining_by_currency
                )
                if self.budget
                else {},
            },
            "trace_ids": list(self.trace_ids),
            "build_id": self.build_id,
            "manifest_revision": self.manifest_revision,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------

_UNSET = object()


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class AcceptanceRunner:
    """串行场景执行引擎：授权闸+预算闸+时间窗闸+撤销响应+脱敏报告。

    - 无授权包 → :class:`AuthorizationRequired`（拒绝启动，零步执行）；
    - 授权包预置 revoked / 场景未列 → 启动即 blocked，零分发；
    - 同 ``run_id`` 重跑 → 返回缓存报告（幂等，零重发零重复扣账）；
    - 全部依赖（clock/transport/revocation）可注入，离线确定性。
    """

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock: Clock = clock or (lambda: datetime.now(timezone.utc))
        self._reports: dict[str, RunReport] = {}
        self._seq = 0

    # -- 公开面 ------------------------------------------------------------

    def run(
        self,
        scenario: ScenarioPlan,
        authorization: AuthorizationPackage | None,
        transport: AcceptanceTransport,
        *,
        revocation: RevocationToken | None = None,
        run_id: str | None = None,
        stop_on_failure: bool = True,
        build_id: str = "unknown",
        manifest_revision: str = "unknown",
    ) -> RunReport:
        """执行一个场景（串行；同 run_id 幂等返回缓存报告）。"""
        if authorization is None:
            raise AuthorizationRequired(
                "acceptance: 无授权包，拒绝启动（合同 §8.1 默认拒绝）"
            )
        if run_id is None:
            self._seq += 1
            run_id = f"run-{authorization.authorization_id}-{self._seq:04d}"
        cached = self._reports.get(run_id)
        if cached is not None:
            logger.info("acceptance: run_id=%s 幂等重跑，返回缓存报告", run_id)
            return cached

        started_at = self._clock()
        now = _ensure_aware(started_at)
        results: list[StepResult] = []
        ledger = BudgetLedger.from_authorization(authorization)
        receipts_by_step: dict[str, TransportReceipt] = {}

        stop_reason, start_status, start_detail = self._gate_run_start(
            scenario, authorization, revocation, now
        )
        if stop_reason is not None:
            # 启动即拒：全部步按拒绝态落账，零分发。
            for step in scenario.steps:
                results.append(
                    StepResult(
                        step_id=step.step_id,
                        kind=step.kind,
                        status=start_status,
                        detail=start_detail,
                    )
                )
            status = RunStatus.BLOCKED
        else:
            stop_reason, status = self._execute_steps(
                scenario=scenario,
                authorization=authorization,
                transport=transport,
                revocation=revocation,
                ledger=ledger,
                run_id=run_id,
                results=results,
                receipts_by_step=receipts_by_step,
                stop_on_failure=stop_on_failure,
            )

        finished_at = self._clock()
        report = self._build_report(
            run_id=run_id,
            scenario=scenario,
            authorization=authorization,
            transport=transport,
            status=status,
            stop_reason=stop_reason,
            results=results,
            ledger=ledger,
            started_at=started_at,
            finished_at=finished_at,
            build_id=build_id,
            manifest_revision=manifest_revision,
        )
        self._reports[run_id] = report
        return report

    def get_report(self, run_id: str) -> RunReport | None:
        return self._reports.get(run_id)

    # -- 启动闸 ------------------------------------------------------------

    def _gate_run_start(
        self,
        scenario: ScenarioPlan,
        authorization: AuthorizationPackage,
        revocation: RevocationToken | None,
        now: datetime,
    ) -> tuple[StopReason | None, StepStatus, str]:
        """启动即闸（零分发）：撤销→场景未列→时间窗；放行返回 (None, PENDING, "")。"""
        if authorization.revoked or (revocation is not None and revocation.is_revoked):
            reason = (
                f"授权 {authorization.authorization_id} 已撤销"
                f"(revoke_version={authorization.revoke_version})"
            )
            if revocation is not None and revocation.is_revoked:
                reason += f"; token={revocation.reason}"
            return StopReason.REVOKED, StepStatus.REJECTED_REVOKED, reason
        if (
            authorization.allowed_scenarios
            and scenario.scenario_id not in authorization.allowed_scenarios
        ):
            return (
                StopReason.NOT_AUTHORIZED,
                StepStatus.REJECTED_NOT_AUTHORIZED,
                f"场景 {scenario.scenario_id} 未列入授权包（默认拒绝）",
            )
        if not authorization.window_open_at(now):
            return (
                StopReason.WINDOW_CLOSED,
                StepStatus.REJECTED_WINDOW,
                f"时间窗外（now={now.isoformat()}）",
            )
        return None, StepStatus.PENDING, ""

    # -- 主循环 ------------------------------------------------------------

    def _execute_steps(
        self,
        *,
        scenario: ScenarioPlan,
        authorization: AuthorizationPackage,
        transport: AcceptanceTransport,
        revocation: RevocationToken | None,
        ledger: BudgetLedger,
        run_id: str,
        results: list[StepResult],
        receipts_by_step: dict[str, TransportReceipt],
        stop_on_failure: bool,
    ) -> tuple[StopReason, RunStatus]:
        def skip_rest(index: int, reason: StopReason) -> tuple[StopReason, RunStatus]:
            for step in scenario.steps[index:]:
                results.append(
                    StepResult(
                        step_id=step.step_id,
                        kind=step.kind,
                        status=StepStatus.SKIPPED_NOT_RUN,
                        detail=f"run 因 {reason.value} 停机，未执行",
                    )
                )
            if reason is StopReason.COMPLETED:
                return reason, RunStatus.PASSED
            return reason, RunStatus.BLOCKED

        for index, step in enumerate(scenario.steps):
            now = _ensure_aware(self._clock())

            # 闸 1：撤销（只停在分发边界；在途步已在上一轮跑完，不强杀）。
            if authorization.revoked or (
                revocation is not None and revocation.is_revoked
            ):
                reason = (
                    f"撤销令牌置位({revocation.reason})"
                    if revocation is not None and revocation.is_revoked
                    else "授权包预置撤销"
                )
                results.append(
                    StepResult(
                        step_id=step.step_id,
                        kind=step.kind,
                        status=StepStatus.REJECTED_REVOKED,
                        detail=reason,
                    )
                )
                return skip_rest(index + 1, StopReason.REVOKED)

            # 闸 2：时间窗。
            if not authorization.window_open_at(now):
                results.append(
                    StepResult(
                        step_id=step.step_id,
                        kind=step.kind,
                        status=StepStatus.REJECTED_WINDOW,
                        detail=f"时间窗外（now={now.isoformat()}）",
                    )
                )
                return skip_rest(index + 1, StopReason.WINDOW_CLOSED)

            # 闸 3/4：目标与 provider 授权（默认拒绝；ASSERT 本地零出站不过此闸）。
            if step.kind is StepKind.CALL:
                rejected = self._gate_step_authorization(step, authorization)
                if rejected is not None:
                    results.append(rejected)
                    return skip_rest(index + 1, StopReason.NOT_AUTHORIZED)

                # 闸 5：预算（超预算步骤拒执行，不发生 attempt）。
                afford_error = ledger.check(step)
                if afford_error is not None:
                    results.append(
                        StepResult(
                            step_id=step.step_id,
                            kind=step.kind,
                            status=StepStatus.REJECTED_BUDGET,
                            detail=afford_error,
                        )
                    )
                    return skip_rest(index + 1, StopReason.BUDGET_EXHAUSTED)

            # 执行。
            result = self._run_step(
                step=step,
                scenario_id=scenario.scenario_id,
                authorization=authorization,
                transport=transport,
                ledger=ledger,
                run_id=run_id,
                results=results,
                receipts_by_step=receipts_by_step,
            )
            results.append(result)
            if not stop_on_failure:
                continue
            if result.status in (StepStatus.FAILED, StepStatus.ERROR):
                return skip_rest(index + 1, StopReason.STEP_FAILED)
            if result.status is StepStatus.NOT_WIRED:
                # 真实出站未接线：诚实终局，不继续后续步（live=unknown 不伪装）。
                return skip_rest(index + 1, StopReason.NOT_WIRED)

        return skip_rest(len(scenario.steps), StopReason.COMPLETED)

    def _gate_step_authorization(
        self, step: ScenarioStep, authorization: AuthorizationPackage
    ) -> StepResult | None:
        if step.target not in authorization.allowed_targets:
            return StepResult(
                step_id=step.step_id,
                kind=step.kind,
                status=StepStatus.REJECTED_NOT_AUTHORIZED,
                detail=f"目标 {step.target!r} 未列入授权白名单（默认拒绝）",
            )
        if step.provider and step.provider not in authorization.provider_allowlist:
            return StepResult(
                step_id=step.step_id,
                kind=step.kind,
                status=StepStatus.REJECTED_NOT_AUTHORIZED,
                detail=f"provider {step.provider!r} 未列入授权白名单（默认拒绝）",
            )
        return None

    def _run_step(
        self,
        *,
        step: ScenarioStep,
        scenario_id: str,
        authorization: AuthorizationPackage,
        transport: AcceptanceTransport,
        ledger: BudgetLedger,
        run_id: str,
        results: list[StepResult],
        receipts_by_step: dict[str, TransportReceipt],
    ) -> StepResult:
        started_at = self._clock()
        redacted_payload = redact_mapping(step.payload)

        if step.kind is StepKind.ASSERT:
            context = AssertionContext(
                run_id=run_id,
                scenario_id=scenario_id,
                step_id=step.step_id,
                payload=step.payload,
                results={r.step_id: r for r in results},
                receipts=receipts_by_step,
                transport=transport,
            )
            ok, detail = True, "no-op assertion"
            try:
                if step.assertion is not None:
                    ok, detail = step.assertion(context)
            except Exception as exc:  # noqa: BLE001 - 断言异常=失败不外溢
                ok, detail = False, f"assertion error: {redact_text(str(exc))}"
            return StepResult(
                step_id=step.step_id,
                kind=step.kind,
                status=StepStatus.PASSED if ok else StepStatus.FAILED,
                detail=redact_text(detail),
                cost_requests=0,
                redacted_payload=redacted_payload,
                started_at=started_at,
                finished_at=self._clock(),
            )

        # CALL：真实 attempt 发生即记账（失败回执也计；合同「每真实 attempt 采集」）。
        idem = step.idempotency_key or f"{run_id}:{step.step_id}"
        request = TransportRequest(
            action=step.action,
            target=step.target,
            payload=dict(step.payload),
            idempotency_key=idem,
            trace_id=f"{run_id}:{step.step_id}",
        )
        try:
            receipt = transport.deliver(request)
        except TransportNotWired as exc:
            return StepResult(
                step_id=step.step_id,
                kind=step.kind,
                status=StepStatus.NOT_WIRED,
                detail=redact_text(str(exc)),
                redacted_payload=redacted_payload,
                started_at=started_at,
                finished_at=self._clock(),
            )
        except Exception as exc:  # noqa: BLE001 - transport 异常=attempt 已发生，记账
            ledger.apply(step)
            return StepResult(
                step_id=step.step_id,
                kind=step.kind,
                status=StepStatus.ERROR,
                detail=redact_text(f"transport error: {exc}"),
                cost_requests=step.cost_requests,
                cost_by_currency=dict(step.cost_by_currency),
                redacted_payload=redacted_payload,
                started_at=started_at,
                finished_at=self._clock(),
            )
        ledger.apply(step)
        receipts_by_step[step.step_id] = receipt
        if receipt.accepted:
            outcome_detail = "accepted" if not receipt.duplicated else "duplicated"
        else:
            outcome_detail = "rejected by transport"
        return StepResult(
            step_id=step.step_id,
            kind=step.kind,
            status=StepStatus.PASSED if receipt.accepted else StepStatus.FAILED,
            detail=redact_text(receipt.error or outcome_detail),
            trace_id=receipt.trace_id,
            receipt_id=receipt.receipt_id,
            accepted=receipt.accepted,
            duplicated=receipt.duplicated,
            cost_requests=step.cost_requests,
            cost_by_currency=dict(step.cost_by_currency),
            redacted_payload=redacted_payload,
            detail_map=redact_mapping(receipt.detail),
            started_at=started_at,
            finished_at=self._clock(),
        )

    # -- 报告 --------------------------------------------------------------

    def _build_report(
        self,
        *,
        run_id: str,
        scenario: ScenarioPlan,
        authorization: AuthorizationPackage,
        transport: AcceptanceTransport,
        status: RunStatus,
        stop_reason: StopReason,
        results: list[StepResult],
        ledger: BudgetLedger,
        started_at: datetime,
        finished_at: datetime,
        build_id: str,
        manifest_revision: str,
    ) -> RunReport:
        trace_ids = tuple(
            r.trace_id for r in results if r.trace_id
        )
        notes = [
            "real transport not wired (not_wired); live_validation=unknown",
            (
                f"authorization revoke_version={authorization.revoke_version}"
                f" data_scope={authorization.data_scope}"
            ),
        ]
        return RunReport(
            run_id=run_id,
            scenario_id=scenario.scenario_id,
            scenario_title=scenario.title,
            level=scenario.level,
            authorization_id=authorization.authorization_id,
            transport=type(transport).__name__,
            status=status,
            stop_reason=stop_reason,
            started_at=started_at,
            finished_at=finished_at,
            steps=tuple(results),
            budget=ledger.snapshot(),
            trace_ids=trace_ids,
            build_id=build_id,
            manifest_revision=manifest_revision,
            notes=tuple(notes),
        )

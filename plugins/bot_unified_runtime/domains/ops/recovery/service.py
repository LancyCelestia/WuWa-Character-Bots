"""统一运行自愈服务（V21-HEAL-001 唯一载体，S14 席新建件）。

背景：自愈逻辑此前散在 runtime/alerts.py（重连对账）、sender/worker.py
（bot_unavailable 挂起重试）等处，没有统一的「分类→预算→动作→验证→
稳定窗口→风暴熔断」链路。本模块把这条链路收拢成一个依赖可注入、
全离线确定性可测的服务；**自身不做任何真实重连/回滚**——真实动作由
executor 注入（装配席把 NapCat 重连、worker 恢复等真实执行体接进来）。

合同锚点（backend-v2-implementation-guide.md §12 L260-262，逐条对齐）：

- 自愈只做：重连、有限重试、worker 恢复、缓存重建、资源回滚、UNKNOWN
  对账（DEFAULT_ACTION_BY_KIND 六动作一一对应）；
- **每资源 10 分钟最多 3 次**（attempt_window_seconds=600 / max=3）；
- **full-jitter 指数退避，基础 1s、上限 30s**（失败动作后进入退避，
  ``rng`` 可注入保证离线确定性）；
- 数据库疑损不删库、不更改密钥/代理/权限/人格/审计——这是 executor
  实现侧纪律，本服务不提供也不会注册此类动作；
- 代码修复（脱敏故障包→隔离 checkout→待审补丁，不自动部署）不在自愈
  范围，只归类为 ``PATCH_REQUIRED`` 不可重试并上报。

职责边界（克制原则）：

- **分类**：可恢复 6 类 vs 不可重试 4 类。不可重试只上报，绝不用恢复
  动作硬试（重试必然复发）。
- **预算**：每组件滚动窗内最多 ``max_attempts_per_window`` 次恢复动作，
  超预算升级上报，不再动作。
- **验证**：动作后走注入的 verifier 复核；无 verifier 时诚实标注
  ``verified=None``（未验证），不伪称已恢复。
- **稳定窗口**：动作成功后 ``stable_window_seconds`` 内同组件复发 →
  升级档位（warning→error→critical）；窗口外安静则档位归零重来。
- **风暴熔断**：全局滚动窗内恢复动作启动次数超 ``storm_threshold`` →
  熔断打开（只上报不动作），防「故障→恢复→再故障」递归放大；冷却期满
  放行探测（清空风暴计数重新累计），再次超阈值会再次熔断。
- **失败透明**：executor/reporter/verifier 抛异常一律捕获降级
  （fail-open），绝不向调用方外溢异常。

挂接坐标（本席零编辑既有文件，留接线席；详见 docs/design/v21r2-s14-log.md §三）::

    from plugins.bot_unified_runtime.domains.ops.recovery import RecoveryService
    from plugins.bot_unified_runtime.domains.ops.incident import IncidentService

    service = RecoveryService(executor=真实执行体, reporter=IncidentService(...))
    decision = service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK, ...)

- 无新增 config 键：阈值全部为模块常量/构造参数（热调由接线席注入）。
"""

from __future__ import annotations

import logging
import random
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_ACTION_BY_KIND",
    "DEFAULT_POLICY",
    "FailureContext",
    "FailureKind",
    "IncidentReporter",
    "RecoveryAction",
    "RecoveryDecision",
    "RecoveryExecutor",
    "RecoveryOutcome",
    "RecoveryPolicy",
    "RecoveryService",
]


class FailureKind(str, Enum):
    """故障分类：前 6 类可恢复（各有默认恢复动作），后 4 类不可重试。

    可恢复对应指南 §12 自愈白名单：重连（网络/依赖）、有限重试（限流）、
    worker 恢复（资源忙/停滞）、缓存重建与 UNKNOWN 对账（状态陈旧）。
    PATCH_REQUIRED=代码缺陷需走待审补丁流程（不是自愈，只上报）。
    """

    TRANSIENT_NETWORK = "transient_network"
    RATE_LIMITED = "rate_limited"
    RESOURCE_BUSY = "resource_busy"
    DEPENDENCY_DEGRADED = "dependency_degraded"
    STALE_STATE = "stale_state"
    WORKER_STALLED = "worker_stalled"
    INVALID_INPUT = "invalid_input"
    AUTH_DENIED = "auth_denied"
    PERMANENT = "permanent"
    PATCH_REQUIRED = "patch_required"

    @property
    def is_recoverable(self) -> bool:
        return self in _RECOVERABLE_KINDS


_RECOVERABLE_KINDS = frozenset(
    {
        FailureKind.TRANSIENT_NETWORK,
        FailureKind.RATE_LIMITED,
        FailureKind.RESOURCE_BUSY,
        FailureKind.DEPENDENCY_DEGRADED,
        FailureKind.STALE_STATE,
        FailureKind.WORKER_STALLED,
    }
)


@dataclass(frozen=True)
class RecoveryAction:
    """一次恢复动作的描述（executor 据此执行；cooldown_seconds 为同组件
    两次动作的最小间隔）。"""

    name: str
    label: str = ""
    cooldown_seconds: float = 0.0


#: 分类 → 默认恢复动作（指南 §12 六动作白名单）。不可重试类刻意缺席：
#: 没有动作就不该硬试。
DEFAULT_ACTION_BY_KIND: Mapping[FailureKind, RecoveryAction] = {
    FailureKind.TRANSIENT_NETWORK: RecoveryAction("reconnect", "重连通道", 5.0),
    FailureKind.RATE_LIMITED: RecoveryAction("cooldown_backoff", "限流退避", 30.0),
    FailureKind.RESOURCE_BUSY: RecoveryAction("drain_backlog", "排空积压", 2.0),
    FailureKind.DEPENDENCY_DEGRADED: RecoveryAction(
        "reconnect_dependency", "重连依赖", 10.0
    ),
    FailureKind.STALE_STATE: RecoveryAction(
        "reconcile_state", "重建缓存/UNKNOWN 对账", 15.0
    ),
    FailureKind.WORKER_STALLED: RecoveryAction("restart_worker", "重启 worker", 20.0),
}


@dataclass(frozen=True)
class RecoveryPolicy:
    """自愈预算与熔断阈值（全部可注入；缺省=DEFAULT_POLICY）。

    ``max_attempts_per_window``/``attempt_window_seconds`` 对齐指南 §12
    「每资源 10 分钟最多 3 次」；``backoff_*`` 对齐「full-jitter 基础 1s
    上限 30s」。
    """

    #: 每组件滚动窗内允许的最大恢复动作次数（指南 §12：3 次）。
    max_attempts_per_window: int = 3
    #: 滚动窗口长度（秒；指南 §12：10 分钟）。
    attempt_window_seconds: float = 600.0
    #: 稳定窗口：动作后该时长内同组件复发 → 升级档位。
    stable_window_seconds: float = 60.0
    #: full-jitter 退避基数（秒）。
    backoff_base_seconds: float = 1.0
    #: full-jitter 退避上限（秒）。
    backoff_max_seconds: float = 30.0
    #: 风暴熔断：全局滚动窗内恢复动作启动次数超过该值 → 熔断打开。
    storm_threshold: int = 6
    #: 风暴计数窗口长度（秒）。
    storm_window_seconds: float = 60.0
    #: 熔断打开持续时长（秒），期满放行探测。
    circuit_open_seconds: float = 600.0


DEFAULT_POLICY = RecoveryPolicy()


@dataclass(frozen=True)
class FailureContext:
    """一次故障的位置与说明（summary 由调用方保证不含明文密钥；最终出站
    前仍会被 IncidentService 二次脱敏）。"""

    component: str
    kind: FailureKind
    summary: str = ""
    trace_id: str | None = None


@dataclass(frozen=True)
class RecoveryOutcome:
    """executor/验证后的结果。verified 三态：True/False 已验证，None 未
    验证（未配 verifier）——不伪称已恢复。"""

    success: bool
    detail: str = ""
    verified: bool | None = None


@dataclass(frozen=True)
class RecoveryDecision:
    """handle_failure 的完整决策记录（含未动作时的原因）。"""

    component: str
    kind: FailureKind
    at: float
    attempted: bool
    reason: str
    action: RecoveryAction | None = None
    outcome: RecoveryOutcome | None = None
    escalation_tier: int = 0
    escalated: bool = False
    severity: str = "warning"


class RecoveryExecutor(Protocol):
    """真实恢复动作执行体协议（接线席注入；测试用 mock）。

    实现侧纪律（指南 §12）：数据库疑损不删库；不改密钥/代理/权限/人格/
    审计；代码修复走 PATCH_REQUIRED 上报而非自愈动作。
    """

    def execute(self, action: RecoveryAction, context: FailureContext) -> RecoveryOutcome: ...


@runtime_checkable
class IncidentReporter(Protocol):
    """事件上报协议：与 domains/ops/incident.IncidentService.report_incident
    同签名（结构化满足即可注入）。实现方必须自身 fail-open。"""

    def report_incident(
        self,
        *,
        component: str,
        severity: str,
        explanation: str,
        method: str = "",
        trace_id: str | None = None,
        user_text: str | None = None,
    ) -> None: ...


def _severity_for_tier(tier: int) -> str:
    if tier <= 1:
        return "warning"
    if tier == 2:
        return "error"
    return "critical"


@dataclass
class _ComponentState:
    """每组件运行态（进程内；重启即失忆，属已知边界）。"""

    attempt_times: deque[float] = field(default_factory=deque)
    last_attempt: float | None = None
    last_failure_at: float | None = None
    backoff_until: float = 0.0
    tier: int = 0
    last_activity: float = 0.0


class RecoveryService:
    """统一自愈入口：分类 → 预算内动作 → 动作后验证 → 稳定窗口 → 风暴熔断。

    ``executor`` 必注入（真实动作协议）；``verifier``/``reporter`` 可选；
    ``monotonic``/``rng`` 注入实现全离线确定性测试。本类所有公开方法不抛
    异常（fail-open）。
    """

    def __init__(
        self,
        *,
        executor: RecoveryExecutor,
        policy: RecoveryPolicy = DEFAULT_POLICY,
        verifier: Callable[[FailureContext, RecoveryAction], bool] | None = None,
        reporter: IncidentReporter | None = None,
        actions: Mapping[FailureKind, RecoveryAction] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        rng: Callable[[float, float], float] = random.uniform,
        max_tracked_components: int = 256,
    ) -> None:
        self._executor = executor
        self._policy = policy
        self._verifier = verifier
        self._reporter = reporter
        self._actions = dict(DEFAULT_ACTION_BY_KIND if actions is None else actions)
        self._monotonic = monotonic
        self._rng = rng
        self._max_components = max(8, int(max_tracked_components))
        self._components: dict[str, _ComponentState] = {}
        self._global_attempts: deque[float] = deque()
        self._circuit_opened_at: float | None = None
        self._circuit_reported = False
        # 观测计数
        self.attempts_total = 0
        self.recoveries_succeeded = 0
        self.recoveries_failed = 0
        self.escalations_total = 0
        self.storms_opened = 0

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def handle_failure(
        self,
        component: str,
        kind: FailureKind,
        *,
        summary: str = "",
        trace_id: str | None = None,
    ) -> RecoveryDecision:
        """故障上报入口（同步、不抛异常）。返回完整决策记录。"""
        now = self._monotonic()
        context = FailureContext(
            component=component, kind=kind, summary=summary, trace_id=trace_id
        )
        try:
            return self._handle(context, now)
        except Exception:  # pragma: no cover - 防御性兜底，fail-open
            logger.exception("recovery: internal error while handling %s", component)
            return RecoveryDecision(
                component=component,
                kind=kind,
                at=now,
                attempted=False,
                reason="internal_error",
                severity="error",
            )

    def snapshot(self) -> dict[str, Any]:
        """观测投影（控制面/测试用；只读、无副作用）。"""
        now = self._monotonic()
        components: dict[str, Any] = {}
        for name, state in self._components.items():
            self._prune(state.attempt_times, now, self._policy.attempt_window_seconds)
            components[name] = {
                "attempts_in_window": len(state.attempt_times),
                "tier": state.tier,
                "backoff_remaining": max(0.0, state.backoff_until - now),
                "last_attempt_age": (
                    None
                    if state.last_attempt is None
                    else max(0.0, now - state.last_attempt)
                ),
            }
        return {
            "attempts_total": self.attempts_total,
            "recoveries_succeeded": self.recoveries_succeeded,
            "recoveries_failed": self.recoveries_failed,
            "escalations_total": self.escalations_total,
            "storms_opened": self.storms_opened,
            "circuit_open": self._circuit_opened_at is not None,
            "components": components,
        }

    # ------------------------------------------------------------------
    # 内部链路
    # ------------------------------------------------------------------

    def _handle(self, context: FailureContext, now: float) -> RecoveryDecision:
        state = self._state_for(context.component, now)
        state.last_activity = now

        # 不可重试：只上报，不动作，不参与稳定窗/风暴计数。
        if not context.kind.is_recoverable:
            self._report(
                component=context.component,
                severity="error",
                explanation=context.summary or f"不可重试失败: {context.kind.value}",
                method="无（不可重试，仅上报）",
                trace_id=context.trace_id,
            )
            return RecoveryDecision(
                component=context.component,
                kind=context.kind,
                at=now,
                attempted=False,
                reason="non_retryable",
                severity="error",
            )

        tier, escalated = self._advance_tier(state, now)
        severity = _severity_for_tier(tier)

        # 风暴熔断：全局闸门优先于一切动作。
        if self._check_circuit(now):
            if not self._circuit_reported:
                self._circuit_reported = True
                self.storms_opened += 1
                self.escalations_total += 1
                recent = self._count_recent_attempts(now)
                self._report(
                    component=context.component,
                    severity="critical",
                    explanation=(
                        f"恢复风暴熔断：窗口 {self._policy.storm_window_seconds:.0f}s 内已启动 "
                        f"{recent} 次恢复动作（阈值 {self._policy.storm_threshold}），"
                        "暂停动作防递归"
                    ),
                    method="storm_circuit_open",
                    trace_id=context.trace_id,
                )
            return RecoveryDecision(
                component=context.component,
                kind=context.kind,
                at=now,
                attempted=False,
                reason="storm_circuit_open",
                escalation_tier=tier,
                escalated=True,
                severity="critical",
            )

        action = self._actions.get(context.kind)
        if action is None:
            return RecoveryDecision(
                component=context.component,
                kind=context.kind,
                at=now,
                attempted=False,
                reason="no_action_registered",
                escalation_tier=tier,
                severity=severity,
            )

        # full-jitter 退避（失败动作后进入）与同组件最小动作间隔。
        if now < state.backoff_until:
            return RecoveryDecision(
                component=context.component,
                kind=context.kind,
                at=now,
                attempted=False,
                reason="backoff",
                action=action,
                escalation_tier=tier,
                severity=severity,
            )
        if (
            state.last_attempt is not None
            and now - state.last_attempt < action.cooldown_seconds
        ):
            return RecoveryDecision(
                component=context.component,
                kind=context.kind,
                at=now,
                attempted=False,
                reason="cooldown_active",
                action=action,
                escalation_tier=tier,
                severity=severity,
            )

        # 每组件滚动窗预算（指南 §12：每资源 10 分钟最多 3 次）。
        self._prune(state.attempt_times, now, self._policy.attempt_window_seconds)
        if len(state.attempt_times) >= self._policy.max_attempts_per_window:
            budget_severity = _severity_for_tier(max(tier, 2))
            self.escalations_total += 1
            base = context.summary or f"{context.kind.value} 复发超预算"
            self._report(
                component=context.component,
                severity=budget_severity,
                explanation=(
                    f"{base}（窗口 {self._policy.attempt_window_seconds:.0f}s 内已 "
                    f"{len(state.attempt_times)} 次动作，超出预算暂停恢复）"
                ),
                method=(
                    f"budget({self._policy.max_attempts_per_window}/"
                    f"{self._policy.attempt_window_seconds:.0f}s)"
                ),
                trace_id=context.trace_id,
            )
            return RecoveryDecision(
                component=context.component,
                kind=context.kind,
                at=now,
                attempted=False,
                reason="budget_exhausted",
                action=action,
                escalation_tier=tier,
                escalated=True,
                severity=budget_severity,
            )

        # 记账（风暴计数在此累计）。
        state.attempt_times.append(now)
        state.last_attempt = now
        self._global_attempts.append(now)
        self.attempts_total += 1

        outcome = self._run_executor(action, context)
        if outcome.success:
            outcome = self._verify(action, context, outcome)

        if outcome.success:
            self.recoveries_succeeded += 1
            reason = "action_succeeded"
            # 成功即安静（克制原则）：上报交给决策记录，不触发 incident。
        else:
            self.recoveries_failed += 1
            if outcome.verified is False:
                reason = "verify_failed"
            elif outcome.detail.startswith("executor_error"):
                reason = "executor_error"
            else:
                reason = "action_failed"
            # 失败动作进入 full-jitter 退避（基础 1s、上限 30s，指南 §12）。
            state.backoff_until = now + self._backoff_seconds(
                len(state.attempt_times)
            )
            self._report(
                component=context.component,
                severity=severity,
                explanation=(context.summary or f"{context.kind.value} 恢复未成功")
                + (f"；{outcome.detail}" if outcome.detail else ""),
                method=action.name,
                trace_id=context.trace_id,
            )

        return RecoveryDecision(
            component=context.component,
            kind=context.kind,
            at=now,
            attempted=True,
            reason=reason,
            action=action,
            outcome=outcome,
            escalation_tier=tier,
            escalated=escalated,
            severity=severity,
        )

    # ------------------------------------------------------------------
    # 稳定窗口 / 风暴 / 执行 / 上报
    # ------------------------------------------------------------------

    def _advance_tier(self, state: _ComponentState, now: float) -> tuple[int, bool]:
        """稳定窗口语义：窗口内复发升级一档；窗口外安静则归零后重新起档。"""
        stable = self._policy.stable_window_seconds
        if state.last_failure_at is not None and now - state.last_failure_at >= stable:
            state.tier = 0
        state.last_failure_at = now
        state.tier += 1
        escalated = state.tier >= 2
        return state.tier, escalated

    def _backoff_seconds(self, attempt_count: int) -> float:
        """full-jitter：uniform(base, min(max, base * 2^(n-1)))。"""
        base = max(0.0, self._policy.backoff_base_seconds)
        ceiling = min(
            self._policy.backoff_max_seconds,
            base * (2 ** max(0, attempt_count - 1)),
        )
        if ceiling <= base:
            return base
        return float(self._rng(base, ceiling))

    def _check_circuit(self, now: float) -> bool:
        if self._circuit_opened_at is not None:
            if now - self._circuit_opened_at < self._policy.circuit_open_seconds:
                return True
            # 冷却期满：放行探测（宽恕风暴计数重新累计）。
            logger.info(
                "recovery: storm circuit half-open after %.0fs, probing again",
                now - self._circuit_opened_at,
            )
            self._circuit_opened_at = None
            self._circuit_reported = False
            self._global_attempts.clear()
            return False
        self._prune(self._global_attempts, now, self._policy.storm_window_seconds)
        if len(self._global_attempts) >= self._policy.storm_threshold:
            self._circuit_opened_at = now
            return True
        return False

    def _count_recent_attempts(self, now: float) -> int:
        self._prune(self._global_attempts, now, self._policy.storm_window_seconds)
        return len(self._global_attempts)

    def _run_executor(
        self, action: RecoveryAction, context: FailureContext
    ) -> RecoveryOutcome:
        try:
            outcome = self._executor.execute(action, context)
        except Exception as exc:  # executor 缺陷不得外溢
            logger.exception(
                "recovery: executor %s raised for %s", action.name, context.component
            )
            return RecoveryOutcome(
                success=False, detail=f"executor_error: {type(exc).__name__}"
            )
        if not isinstance(outcome, RecoveryOutcome):
            return RecoveryOutcome(
                success=False, detail="executor_error: invalid outcome type"
            )
        return outcome

    def _verify(
        self, action: RecoveryAction, context: FailureContext, outcome: RecoveryOutcome
    ) -> RecoveryOutcome:
        if self._verifier is None:
            return outcome  # verified=None：未验证，不伪称已恢复
        try:
            ok = bool(self._verifier(context, action))
        except Exception:
            logger.exception(
                "recovery: verifier raised for %s after %s",
                context.component,
                action.name,
            )
            ok = False
        if ok:
            return replace(outcome, verified=True)
        return replace(
            outcome,
            success=False,
            verified=False,
            detail=(outcome.detail + "；" if outcome.detail else "") + "验证未通过",
        )

    def _report(
        self,
        *,
        component: str,
        severity: str,
        explanation: str,
        method: str,
        trace_id: str | None,
    ) -> None:
        if self._reporter is None:
            return
        try:
            self._reporter.report_incident(
                component=component,
                severity=severity,
                explanation=explanation,
                method=method,
                trace_id=trace_id,
            )
        except Exception:
            logger.exception("recovery: incident reporter failed (fail-open)")

    def _state_for(self, component: str, now: float) -> _ComponentState:
        state = self._components.get(component)
        if state is None:
            state = _ComponentState(last_activity=now)
            self._components[component] = state
            self._evict_if_needed(now)
        return state

    def _evict_if_needed(self, now: float) -> None:
        if len(self._components) <= self._max_components:
            return
        oldest = min(self._components, key=lambda n: self._components[n].last_activity)
        del self._components[oldest]

    @staticmethod
    def _prune(times: deque[float], now: float, window_seconds: float) -> None:
        horizon = now - window_seconds
        while times and times[0] <= horizon:
            times.popleft()

"""S14 席：RecoveryService 离线回归（V21-HEAL-001）。

覆盖：可恢复/不可重试分类、预算（每资源 10min≤3 次）、full-jitter 退避、
动作后验证（含 verifier 异常）、稳定窗口复发升级、风暴熔断与 half-open
探测、executor/reporter 异常 fail-open、与 IncidentService 集成。全离线：
clock/rng/executor/reporter 全注入，零等待零网络零线程。
"""
from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.domains.ops.incident.service import IncidentService
from plugins.bot_unified_runtime.domains.ops.recovery import (
    DEFAULT_ACTION_BY_KIND,
    FailureKind,
    RecoveryOutcome,
    RecoveryPolicy,
    RecoveryService,
)
from plugins.bot_unified_runtime.domains.ops.recovery.service import (
    IncidentReporter,
    _severity_for_tier,
)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class MockExecutor:
    """可脚本化 executor：script 依序弹出的结果 / raw 依序弹出的非法返回 /
    raise_on_call 抛异常 / 缺省成功。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.script: list[RecoveryOutcome] = []
        self.raw: list[Any] = []
        self.raise_on_call: Exception | None = None
        self.default = RecoveryOutcome(success=True, detail="ok")

    def execute(self, action: Any, context: Any) -> Any:
        self.calls.append((action.name, context.component))
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if self.raw:
            return self.raw.pop(0)
        if self.script:
            return self.script.pop(0)
        return self.default


class RecordingReporter:
    def __init__(self) -> None:
        self.reports: list[dict[str, Any]] = []

    def report_incident(self, **kwargs: Any) -> None:
        self.reports.append(kwargs)


class ExplodingReporter:
    def report_incident(self, **kwargs: Any) -> None:
        raise RuntimeError("reporter down")


def fixed_rng(low: float, high: float) -> float:
    return (low + high) / 2.0


def make_service(
    clock: FakeClock,
    executor: MockExecutor | None = None,
    *,
    verifier: Any = None,
    reporter: Any = None,
    policy: RecoveryPolicy | None = None,
) -> tuple[RecoveryService, MockExecutor, RecordingReporter]:
    exec_ = executor if executor is not None else MockExecutor()
    rep = reporter if reporter is not None else RecordingReporter()
    service = RecoveryService(
        executor=exec_,
        policy=policy or RecoveryPolicy(),
        verifier=verifier,
        reporter=rep,
        monotonic=clock,
        rng=fixed_rng,
    )
    return service, exec_, rep


# ----------------------------------------------------------------------
# 分类
# ----------------------------------------------------------------------


def test_kind_classification_and_default_actions():
    recoverable = {
        FailureKind.TRANSIENT_NETWORK,
        FailureKind.RATE_LIMITED,
        FailureKind.RESOURCE_BUSY,
        FailureKind.DEPENDENCY_DEGRADED,
        FailureKind.STALE_STATE,
        FailureKind.WORKER_STALLED,
    }
    non_retryable = {
        FailureKind.INVALID_INPUT,
        FailureKind.AUTH_DENIED,
        FailureKind.PERMANENT,
        FailureKind.PATCH_REQUIRED,
    }
    assert {k for k in FailureKind if k.is_recoverable} == recoverable
    assert {k for k in FailureKind if not k.is_recoverable} == non_retryable
    assert set(DEFAULT_ACTION_BY_KIND) == recoverable  # 不可重试刻意无动作
    for action in DEFAULT_ACTION_BY_KIND.values():
        assert action.name
        assert action.cooldown_seconds >= 0


# ----------------------------------------------------------------------
# 基本链路
# ----------------------------------------------------------------------


def test_non_retryable_reports_without_action():
    clock = FakeClock()
    service, executor, reporter = make_service(clock)
    decision = service.handle_failure(
        "worker", FailureKind.INVALID_INPUT, summary="bad payload"
    )
    assert decision.attempted is False
    assert decision.reason == "non_retryable"
    assert decision.severity == "error"
    assert executor.calls == []
    assert len(reporter.reports) == 1
    report = reporter.reports[0]
    assert report["severity"] == "error"
    assert report["component"] == "worker"
    assert "不可重试" in report["method"]


def test_patch_required_is_non_retryable_and_reports_summary():
    clock = FakeClock()
    service, executor, reporter = make_service(clock)
    decision = service.handle_failure(
        "pipeline", FailureKind.PATCH_REQUIRED, summary="AttributeError in chat.py"
    )
    assert decision.reason == "non_retryable"
    assert executor.calls == []
    assert "AttributeError" in reporter.reports[0]["explanation"]


def test_recoverable_success_is_quiet_and_verified_unknown():
    clock = FakeClock()
    service, _executor, reporter = make_service(clock)
    decision = service.handle_failure(
        "napcat_ws", FailureKind.TRANSIENT_NETWORK, summary="ws dropped"
    )
    assert decision.attempted is True
    assert decision.reason == "action_succeeded"
    assert decision.action is not None
    assert decision.action.name == "reconnect"
    assert decision.outcome is not None
    assert decision.outcome.success is True
    assert decision.outcome.verified is None  # 无 verifier：诚实未验证
    assert decision.escalated is False
    assert decision.severity == "warning"
    assert reporter.reports == []  # 成功即安静（克制原则）
    assert service.attempts_total == 1
    assert service.recoveries_succeeded == 1


def test_verifier_pass_marks_verified_true():
    clock = FakeClock()
    checks: list[str] = []

    def verifier(context: Any, action: Any) -> bool:
        checks.append(action.name)
        return True

    service, _executor, _reporter = make_service(clock, verifier=verifier)
    decision = service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    assert decision.outcome is not None
    assert decision.outcome.verified is True
    assert decision.reason == "action_succeeded"
    assert checks == ["reconnect"]


def test_verifier_failure_fails_action_and_reports():
    clock = FakeClock()
    service, _executor, reporter = make_service(clock, verifier=lambda c, a: False)
    decision = service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    assert decision.reason == "verify_failed"
    assert decision.outcome is not None
    assert decision.outcome.success is False
    assert decision.outcome.verified is False
    assert "验证未通过" in decision.outcome.detail
    assert service.recoveries_succeeded == 0
    assert service.recoveries_failed == 1
    assert len(reporter.reports) == 1
    assert reporter.reports[0]["severity"] == "warning"
    assert reporter.reports[0]["method"] == "reconnect"


def test_verifier_exception_counts_as_failed():
    clock = FakeClock()

    def bad_verifier(context: Any, action: Any) -> bool:
        raise RuntimeError("probe broke")

    service, _executor, _reporter = make_service(clock, verifier=bad_verifier)
    decision = service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    assert decision.reason == "verify_failed"
    assert decision.outcome is not None
    assert decision.outcome.verified is False


# ----------------------------------------------------------------------
# 预算 / 退避 / 冷却
# ----------------------------------------------------------------------


def test_budget_exhaustion_after_three_attempts_per_window():
    clock = FakeClock()
    service, executor, reporter = make_service(clock)
    executor.script = [
        RecoveryOutcome(success=False, detail="still down"),
    ]
    # 资源忙动作冷却 2s：t=0 失败（退避 1s）、t=2 成功、t=4 成功、t=6 超预算。
    r1 = service.handle_failure("queue", FailureKind.RESOURCE_BUSY)
    assert r1.reason == "action_failed"
    clock.advance(2.0)
    r2 = service.handle_failure("queue", FailureKind.RESOURCE_BUSY)
    assert r2.reason == "action_succeeded"
    clock.advance(2.0)
    r3 = service.handle_failure("queue", FailureKind.RESOURCE_BUSY)
    assert r3.reason == "action_succeeded"
    clock.advance(2.0)
    r4 = service.handle_failure("queue", FailureKind.RESOURCE_BUSY)
    assert r4.attempted is False
    assert r4.reason == "budget_exhausted"
    assert r4.escalated is True
    assert r4.severity == "critical"  # tier 已升到 3+，预算上报不降档
    assert len(executor.calls) == 3  # 预算外不再动作
    assert service.escalations_total >= 1
    budget_reports = [r for r in reporter.reports if r["method"].startswith("budget(")]
    assert budget_reports
    assert "超出预算" in budget_reports[0]["explanation"]


def test_full_jitter_backoff_after_failed_attempt():
    clock = FakeClock()
    service, executor, _ = make_service(clock)
    executor.script = [RecoveryOutcome(success=False)]
    service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    clock.advance(0.5)  # 退避期内（base 1s）
    blocked = service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    assert blocked.attempted is False
    assert blocked.reason == "backoff"
    clock.advance(5.5)  # 退避已过、动作冷却 5s 已过
    ok = service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    assert ok.attempted is True
    assert ok.reason == "action_succeeded"
    assert len(executor.calls) == 2


def test_backoff_ceiling_capped_at_policy_max():
    clock = FakeClock()
    policy = RecoveryPolicy(backoff_base_seconds=1.0, backoff_max_seconds=30.0)
    service, _, _ = make_service(clock, policy=policy)
    assert service._backoff_seconds(1) == 1.0  # 2^0 → ceiling=base → 取 base
    assert service._backoff_seconds(2) == 1.5  # uniform(1, 2) 中值
    assert service._backoff_seconds(10) == 15.5  # uniform(1, 30) 中值（封顶）


def test_action_cooldown_blocks_second_attempt():
    clock = FakeClock()
    service, executor, _ = make_service(clock)
    service.handle_failure("llm", FailureKind.RATE_LIMITED)  # 限流动作冷却 30s
    clock.advance(10.0)
    decision = service.handle_failure("llm", FailureKind.RATE_LIMITED)
    assert decision.attempted is False
    assert decision.reason == "cooldown_active"
    assert len(executor.calls) == 1


# ----------------------------------------------------------------------
# 稳定窗口
# ----------------------------------------------------------------------


def test_stable_window_recurrence_escalates_then_resets():
    clock = FakeClock()
    service, _executor, _reporter = make_service(clock)
    d1 = service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    assert (d1.escalation_tier, d1.severity, d1.escalated) == (1, "warning", False)
    clock.advance(10.0)  # 稳定窗（60s）内复发 → 升级
    d2 = service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    assert (d2.escalation_tier, d2.severity, d2.escalated) == (2, "error", True)
    clock.advance(90.0)  # 窗外安静 → 归零重来
    d3 = service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    assert (d3.escalation_tier, d3.severity, d3.escalated) == (1, "warning", False)
    assert _severity_for_tier(3) == "critical"
    assert _severity_for_tier(0) == "warning"


# ----------------------------------------------------------------------
# 风暴熔断
# ----------------------------------------------------------------------


def test_storm_circuit_opens_blocks_and_reports_once():
    clock = FakeClock()
    policy = RecoveryPolicy(storm_threshold=3)
    service, executor, reporter = make_service(clock, policy=policy)
    for component in ("c1", "c2", "c3"):
        decision = service.handle_failure(component, FailureKind.TRANSIENT_NETWORK)
        assert decision.reason == "action_succeeded"
    blocked = service.handle_failure("c4", FailureKind.TRANSIENT_NETWORK)
    assert blocked.attempted is False
    assert blocked.reason == "storm_circuit_open"
    assert blocked.severity == "critical"
    assert blocked.escalated is True
    assert len(executor.calls) == 3  # 第 4 个组件被熔断拦下
    assert service.storms_opened == 1
    assert len(reporter.reports) == 1  # 边沿触发一次
    assert reporter.reports[0]["severity"] == "critical"
    assert reporter.reports[0]["method"] == "storm_circuit_open"
    again = service.handle_failure("c5", FailureKind.TRANSIENT_NETWORK)
    assert again.reason == "storm_circuit_open"
    assert len(reporter.reports) == 1  # 熔断期内不重复上报（防递归刷屏）
    assert service.snapshot()["circuit_open"] is True


def test_circuit_half_open_allows_probe_after_cooldown():
    clock = FakeClock()
    policy = RecoveryPolicy(storm_threshold=3, circuit_open_seconds=600.0)
    service, executor, _ = make_service(clock, policy=policy)
    for component in ("c1", "c2", "c3"):
        service.handle_failure(component, FailureKind.TRANSIENT_NETWORK)
    assert service.handle_failure("c4", FailureKind.TRANSIENT_NETWORK).reason == (
        "storm_circuit_open"
    )
    clock.advance(601.0)
    probe = service.handle_failure("c6", FailureKind.TRANSIENT_NETWORK)
    assert probe.attempted is True  # half-open 放行探测
    assert len(executor.calls) == 4
    assert service.snapshot()["circuit_open"] is False


# ----------------------------------------------------------------------
# fail-open 与集成
# ----------------------------------------------------------------------


def test_executor_exception_is_fail_open():
    clock = FakeClock()
    executor = MockExecutor()
    executor.raise_on_call = RuntimeError("ws reconnect exploded")
    service, executor, reporter = make_service(clock, executor)
    decision = service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    assert decision.attempted is True
    assert decision.reason == "executor_error"
    assert decision.outcome is not None
    assert decision.outcome.success is False
    assert "RuntimeError" in decision.outcome.detail
    assert len(reporter.reports) == 1


def test_executor_invalid_outcome_type_is_fail_open():
    clock = FakeClock()
    executor = MockExecutor()
    executor.raw = [object()]  # type: ignore[list-item]
    service, _, _reporter = make_service(clock, executor)
    decision = service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    assert decision.reason == "executor_error"
    assert "invalid outcome" in (decision.outcome.detail if decision.outcome else "")


def test_reporter_exception_does_not_break_handling():
    clock = FakeClock()
    service, executor, _ = make_service(clock, reporter=ExplodingReporter())
    decision = service.handle_failure("worker", FailureKind.AUTH_DENIED)
    assert decision.reason == "non_retryable"  # reporter 炸了链路照常走完
    assert executor.calls == []


def test_snapshot_shape():
    clock = FakeClock()
    service, _executor, _ = make_service(clock)
    service.handle_failure("napcat_ws", FailureKind.TRANSIENT_NETWORK)
    snap = service.snapshot()
    for key in (
        "attempts_total",
        "recoveries_succeeded",
        "recoveries_failed",
        "escalations_total",
        "storms_opened",
        "circuit_open",
        "components",
    ):
        assert key in snap
    assert snap["attempts_total"] == 1
    assert snap["components"]["napcat_ws"]["attempts_in_window"] == 1


def test_incident_reporter_protocol_satisfied_by_incident_service():
    assert isinstance(IncidentService(), IncidentReporter)  # runtime_checkable


def test_integration_recovery_to_incident_with_redaction():
    clock = FakeClock()
    sink_records: list[Any] = []

    class Sink:
        def emit(self, incident: Any) -> None:
            sink_records.append(incident)

    incidents = IncidentService(sink=Sink())
    service = RecoveryService(
        executor=MockExecutor(),
        reporter=incidents,  # type: ignore[arg-type]
        monotonic=clock,
        rng=fixed_rng,
    )
    decision = service.handle_failure(
        "chat_chain",
        FailureKind.PERMANENT,
        summary="model refused; key sk-abcdef123456 leaked in logs",
        trace_id="tr-42",
    )
    assert decision.reason == "non_retryable"
    assert len(sink_records) == 1
    found = incidents.list_incidents()
    assert len(found) == 1
    incident = found[0]
    assert incident.component == "chat_chain"
    assert incident.severity == "error"
    assert incident.trace_id == "tr-42"
    assert "sk-abcdef123456" not in incident.explanation  # 出站前已脱敏
    assert "不可重试" in incident.method


def test_package_placeholder_init_resolves_service():
    # 前任只留了 __init__.py 占位（service.py 缺失曾整包 ImportError）。
    from plugins.bot_unified_runtime.domains.ops import recovery as recovery_pkg

    assert recovery_pkg.RecoveryService is RecoveryService
    assert recovery_pkg.DEFAULT_ACTION_BY_KIND is DEFAULT_ACTION_BY_KIND

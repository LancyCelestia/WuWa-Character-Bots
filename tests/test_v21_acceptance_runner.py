"""ACC 席：AcceptanceRunner 离线回归（V21-ACCEPTANCE-001）。

覆盖：无授权拒绝启动、默认拒绝（场景/目标/provider 白名单）、预算硬闸
（次数/币种/单项上限）、时间窗闸（窗前/窗外/中途越窗）、撤销（预置位/
运行期置位→在途步完成后停止、已计费保留）、mock transport 全流程、
幂等去重与同 run_id 重跑零重发、报告脱敏、not_wired 诚实、失败停机。
全离线：clock/transport/revocation 全注入，零网络零线程零等待。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from plugins.bot_unified_runtime.domains.ops.acceptance import (
    AcceptanceRunner,
    AuthorizationPackage,
    AuthorizationRequired,
    BudgetLedger,
    MockAcceptanceTransport,
    NotWiredTransport,
    RevocationToken,
    RunStatus,
    ScenarioPlan,
    ScenarioStep,
    StepKind,
    StepStatus,
    StopReason,
    redact_mapping,
)
from plugins.bot_unified_runtime.domains.ops.acceptance.scenarios import (
    DEFAULT_SCENARIOS,
    build_divination_idempotency_scenario,
    build_overbudget_drill_scenario,
    build_send_queue_roundtrip_scenario,
    get_scenario,
)

# ---------------------------------------------------------------------------
# 注入件
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    """确定性时钟：恒定返回；advance 手动推进（模拟真实调用期间时间流逝）。"""

    def __init__(self, start: datetime = _T0) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


def mk_runner(clock: FakeClock | None = None) -> AcceptanceRunner:
    """统一构造：缺省固定钟（杜绝墙钟漂移，含合法窗口用例）。"""
    return AcceptanceRunner(clock=clock or FakeClock())


def make_auth(**overrides: object) -> AuthorizationPackage:
    base: dict[str, object] = {
        "authorization_id": "auth-acc-1",
        "principal": "super_admin",
        "admin_recipients": ("10001",),
        "allowed_targets": (
            "mock:send_queue",
            "mock:divination_rest",
            "mock:drill",
            "mock:secret_probe",
        ),
        "allowed_scenarios": (
            "send_queue_roundtrip_mock",
            "divination_rest_idempotent",
            "overbudget_drill",
            "redaction_probe",
            "failure_probe",
            "cost_probe",
            "jpy_probe",
            "percall_probe",
            "assert_probe",
            "drill_probe",
        ),
        "provider_allowlist": ("queue_local", "divination_local", "drill_local"),
        "max_requests": 64,
        "budget_by_currency": {"CNY": Decimal("1.00")},
    }
    base.update(overrides)
    return AuthorizationPackage(**base)  # type: ignore[arg-type]


def one_call_scenario(
    scenario_id: str = "drill_probe",
    *,
    target: str = "mock:drill",
    provider: str = "drill_local",
    payload: dict[str, object] | None = None,
    cost_requests: int = 1,
    cost_cny: str | None = None,
    idempotency_key: str = "",
) -> ScenarioPlan:
    return ScenarioPlan(
        scenario_id=scenario_id,
        title="探针场景",
        level="L0_pure",
        steps=(
            ScenarioStep(
                step_id="probe-1",
                kind=StepKind.CALL,
                action="drill.noop",
                target=target,
                provider=provider,
                payload=payload or {},
                idempotency_key=idempotency_key,
                cost_requests=cost_requests,
                cost_by_currency={"CNY": Decimal(cost_cny)} if cost_cny else {},
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 启动闸（无授权拒绝 + 默认拒绝）
# ---------------------------------------------------------------------------


class TestStartGates:
    def test_no_authorization_refuses_start(self) -> None:
        transport = MockAcceptanceTransport()
        with pytest.raises(AuthorizationRequired):
            mk_runner().run(build_send_queue_roundtrip_scenario(), None, transport)
        assert transport.deliver_count == 0

    def test_revoked_authorization_blocks_start(self) -> None:
        transport = MockAcceptanceTransport()
        report = mk_runner().run(
            build_send_queue_roundtrip_scenario(),
            make_auth(revoked=True, revoke_version=7),
            transport,
        )
        assert report.status is RunStatus.BLOCKED
        assert report.stop_reason is StopReason.REVOKED
        assert transport.deliver_count == 0
        assert all(s.status is StepStatus.REJECTED_REVOKED for s in report.steps)
        assert any("revoke_version=7" in note for note in report.notes)

    def test_unlisted_scenario_blocked(self) -> None:
        transport = MockAcceptanceTransport()
        plan = one_call_scenario("not_registered_scenario")
        report = mk_runner().run(plan, make_auth(), transport)
        assert report.status is RunStatus.BLOCKED
        assert report.stop_reason is StopReason.NOT_AUTHORIZED
        assert transport.deliver_count == 0
        assert report.steps[0].status is StepStatus.REJECTED_NOT_AUTHORIZED

    def test_empty_target_allowlist_blocks_sends(self) -> None:
        transport = MockAcceptanceTransport()
        report = mk_runner().run(
            build_send_queue_roundtrip_scenario(),
            make_auth(allowed_targets=()),
            transport,
        )
        assert report.status is RunStatus.BLOCKED
        assert report.stop_reason is StopReason.NOT_AUTHORIZED
        assert transport.deliver_count == 0

    def test_unlisted_target_rejected(self) -> None:
        transport = MockAcceptanceTransport()
        plan = one_call_scenario(target="https://real.example.com/send")
        report = mk_runner().run(plan, make_auth(), transport)
        assert report.stop_reason is StopReason.NOT_AUTHORIZED
        assert report.steps[0].status is StepStatus.REJECTED_NOT_AUTHORIZED
        assert transport.deliver_count == 0

    def test_unlisted_provider_rejected(self) -> None:
        transport = MockAcceptanceTransport()
        plan = one_call_scenario(provider="unauthorized_provider")
        report = mk_runner().run(plan, make_auth(), transport)
        assert report.stop_reason is StopReason.NOT_AUTHORIZED
        assert "provider" in report.steps[0].detail
        assert transport.deliver_count == 0


# ---------------------------------------------------------------------------
# 预算硬闸
# ---------------------------------------------------------------------------


class TestBudgetGate:
    def test_overbudget_step_rejected_and_run_stops(self) -> None:
        transport = MockAcceptanceTransport()
        report = mk_runner().run(
            build_overbudget_drill_scenario(),
            make_auth(max_requests=2),
            transport,
        )
        assert report.status is RunStatus.BLOCKED
        assert report.stop_reason is StopReason.BUDGET_EXHAUSTED
        assert report.steps[0].status is StepStatus.PASSED
        assert report.steps[1].status is StepStatus.PASSED
        assert report.steps[2].status is StepStatus.REJECTED_BUDGET
        assert "超预算" in report.steps[2].detail
        assert report.budget is not None
        assert report.budget.used_requests == 2

    def test_currency_budget_exhausted(self) -> None:
        transport = MockAcceptanceTransport()
        plan = ScenarioPlan(
            scenario_id="cost_probe",
            title="费用探针",
            level="L0_pure",
            steps=(
                ScenarioStep(
                    step_id="cost-1",
                    kind=StepKind.CALL,
                    action="drill.noop",
                    target="mock:drill",
                    provider="drill_local",
                    cost_requests=1,
                    cost_by_currency={"CNY": Decimal("0.30")},
                ),
                ScenarioStep(
                    step_id="cost-2",
                    kind=StepKind.CALL,
                    action="drill.noop",
                    target="mock:drill",
                    provider="drill_local",
                    cost_requests=1,
                    cost_by_currency={"CNY": Decimal("0.80")},
                ),
            ),
        )
        report = mk_runner().run(
            plan,
            make_auth(budget_by_currency={"CNY": Decimal("0.50")}),
            transport,
        )
        assert report.stop_reason is StopReason.BUDGET_EXHAUSTED
        assert report.steps[0].status is StepStatus.PASSED
        assert report.steps[1].status is StepStatus.REJECTED_BUDGET
        assert report.budget is not None
        assert report.budget.used_by_currency["CNY"] == Decimal("0.30")
        assert report.budget.remaining_by_currency["CNY"] == Decimal("0.20")

    def test_unauthorized_currency_rejected(self) -> None:
        transport = MockAcceptanceTransport()
        plan = ScenarioPlan(
            scenario_id="jpy_probe",
            title="未授权币种",
            level="L0_pure",
            steps=(
                ScenarioStep(
                    step_id="jpy-1",
                    kind=StepKind.CALL,
                    action="drill.noop",
                    target="mock:drill",
                    provider="drill_local",
                    cost_requests=1,
                    cost_by_currency={"JPY": Decimal(10)},
                ),
            ),
        )
        report = mk_runner().run(
            plan,
            make_auth(budget_by_currency={}),
            transport,
        )
        assert report.steps[0].status is StepStatus.REJECTED_BUDGET
        assert "JPY" in report.steps[0].detail
        assert transport.deliver_count == 0

    def test_per_call_max_rejected(self) -> None:
        transport = MockAcceptanceTransport()
        plan = one_call_scenario("percall_probe", cost_cny="0.90")
        report = mk_runner().run(
            plan,
            make_auth(per_call_max={"CNY": Decimal("0.50")}),
            transport,
        )
        assert report.steps[0].status is StepStatus.REJECTED_BUDGET
        assert "单项超上限" in report.steps[0].detail
        assert transport.deliver_count == 0

    def test_ledger_check_does_not_charge(self) -> None:
        ledger = BudgetLedger(max_requests=1)
        step = one_call_scenario().steps[0]
        assert ledger.check(step) is None
        assert ledger.used_requests == 0
        ledger.apply(step)
        assert ledger.check(step) == "调用次数超预算: 1+1>1"


# ---------------------------------------------------------------------------
# 时间窗闸
# ---------------------------------------------------------------------------


class TestWindowGate:
    def test_before_window_blocks_start(self) -> None:
        transport = MockAcceptanceTransport()
        report = mk_runner().run(
            build_send_queue_roundtrip_scenario(),
            make_auth(valid_from=_T0 + timedelta(hours=1)),
            transport,
        )
        assert report.status is RunStatus.BLOCKED
        assert report.stop_reason is StopReason.WINDOW_CLOSED
        assert transport.deliver_count == 0

    def test_after_window_blocks_start(self) -> None:
        transport = MockAcceptanceTransport()
        report = mk_runner().run(
            build_send_queue_roundtrip_scenario(),
            make_auth(valid_to=_T0 - timedelta(minutes=1)),
            transport,
        )
        assert report.stop_reason is StopReason.WINDOW_CLOSED
        assert transport.deliver_count == 0

    def test_window_expiry_midrun_skips_rest(self) -> None:
        # 时间在真实调用期间流逝：每次 deliver 推进 60s，valid_to=+100s
        # → 步1（t=0 过闸）过、步2（t=60 过闸）过、步3（t=120 过闸）被拒。
        clock = FakeClock()
        transport = MockAcceptanceTransport(on_deliver=lambda _req: clock.advance(60))
        report = mk_runner(clock).run(
            build_overbudget_drill_scenario(),  # 三步 CALL
            make_auth(valid_to=_T0 + timedelta(seconds=100)),
            transport,
        )
        assert report.steps[0].status is StepStatus.PASSED
        assert report.steps[1].status is StepStatus.PASSED
        assert report.steps[2].status is StepStatus.REJECTED_WINDOW
        assert report.stop_reason is StopReason.WINDOW_CLOSED
        assert report.status is RunStatus.BLOCKED
        assert transport.deliver_count == 2

    def test_window_open_runs(self) -> None:
        transport = MockAcceptanceTransport()
        report = mk_runner().run(
            build_send_queue_roundtrip_scenario(),
            make_auth(
                valid_from=_T0 - timedelta(minutes=5),
                valid_to=_T0 + timedelta(minutes=5),
            ),
            transport,
        )
        assert report.status is RunStatus.PASSED


# ---------------------------------------------------------------------------
# 撤销
# ---------------------------------------------------------------------------


class TestRevocation:
    def test_revocation_midrun_stops_after_in_flight_step(self) -> None:
        token = RevocationToken()
        transport = MockAcceptanceTransport(
            on_deliver=lambda _req: token.revoke("用户撤销")
        )
        report = mk_runner().run(
            build_overbudget_drill_scenario(),  # 三步 CALL，串行
            make_auth(),
            transport,
            revocation=token,
        )
        # 在途步（第一步，撤销发生在其 deliver 内）跑完并计费，不强杀。
        assert report.steps[0].status is StepStatus.PASSED
        assert report.steps[0].cost_requests == 1
        # 下一分发边界立即停：第二步 REJECTED_REVOKED，第三步 skipped。
        assert report.steps[1].status is StepStatus.REJECTED_REVOKED
        assert report.steps[2].status is StepStatus.SKIPPED_NOT_RUN
        assert report.stop_reason is StopReason.REVOKED
        assert report.status is RunStatus.BLOCKED
        assert transport.deliver_count == 1
        assert report.budget is not None
        assert report.budget.used_requests == 1  # 已计费 attempt 保留
        assert "用户撤销" in report.steps[1].detail

    def test_pre_revoked_token_blocks_start(self) -> None:
        token = RevocationToken()
        token.revoke("提前撤销")
        transport = MockAcceptanceTransport()
        report = mk_runner().run(
            build_send_queue_roundtrip_scenario(),
            make_auth(),
            transport,
            revocation=token,
        )
        assert report.stop_reason is StopReason.REVOKED
        assert transport.deliver_count == 0

    def test_revocation_idempotent_keeps_first_reason(self) -> None:
        token = RevocationToken()
        token.revoke("first")
        token.revoke("second")
        assert token.is_revoked
        assert token.reason == "first"


# ---------------------------------------------------------------------------
# mock 全流程 + 幂等 + 场景注册表
# ---------------------------------------------------------------------------


class TestMockTransportFlow:
    def test_send_queue_roundtrip_full_flow(self) -> None:
        transport = MockAcceptanceTransport()
        report = mk_runner().run(
            build_send_queue_roundtrip_scenario(), make_auth(), transport
        )
        assert report.status is RunStatus.PASSED
        assert report.stop_reason is StopReason.COMPLETED
        assert all(step.status is StepStatus.PASSED for step in report.steps)
        assert transport.deliver_count == 2
        assert transport.send_count == 1  # 幂等重投不产生第二次真实发送
        assert report.budget is not None
        assert report.budget.used_requests == 2
        assert report.budget.used_by_currency["CNY"] == Decimal("0.02")
        # trace 关联：CALL 步 receipt/trace 落报告。
        call_steps = [s for s in report.steps if s.kind is StepKind.CALL]
        assert all(s.receipt_id for s in call_steps)
        assert len(report.trace_ids) == 2
        assert report.transport == "MockAcceptanceTransport"
        assert report.level == "L1_fake_transport"

    def test_divination_idempotent_same_receipt(self) -> None:
        transport = MockAcceptanceTransport()
        report = mk_runner().run(
            build_divination_idempotency_scenario(), make_auth(), transport
        )
        assert report.status is RunStatus.PASSED
        r1, r2 = report.steps[0], report.steps[1]
        assert r1.receipt_id == r2.receipt_id
        assert r2.duplicated is True
        assert transport.send_count == 1

    def test_idempotent_rerun_same_run_id_no_resent(self) -> None:
        transport = MockAcceptanceTransport()
        runner = mk_runner()
        first = runner.run(
            build_send_queue_roundtrip_scenario(),
            make_auth(),
            transport,
            run_id="fixed-run",
        )
        second = runner.run(
            build_send_queue_roundtrip_scenario(),
            make_auth(),
            transport,
            run_id="fixed-run",
        )
        assert first is second
        assert transport.deliver_count == 2  # 重跑零重发零重复扣账
        assert runner.get_report("fixed-run") is first
        assert runner.get_report("missing") is None

    def test_scenario_registry(self) -> None:
        assert set(DEFAULT_SCENARIOS) == {
            "send_queue_roundtrip_mock",
            "divination_rest_idempotent",
            "overbudget_drill",
        }
        assert (
            get_scenario("send_queue_roundtrip_mock").scenario_id
            == "send_queue_roundtrip_mock"
        )
        with pytest.raises(KeyError):
            get_scenario("nope")
        a = build_send_queue_roundtrip_scenario()
        b = build_send_queue_roundtrip_scenario()
        # 计划元数据逐项一致（dataclass 等值含新建断言闭包，按身份不等属预期）。
        assert a is not b
        assert a.scenario_id == b.scenario_id
        assert a.level == b.level
        assert [s.step_id for s in a.steps] == [s.step_id for s in b.steps]
        assert [s.kind for s in a.steps] == [s.kind for s in b.steps]
        assert [s.idempotency_key for s in a.steps] == [
            s.idempotency_key for s in b.steps
        ]


# ---------------------------------------------------------------------------
# 报告脱敏 + 失败计费
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_report_payload_and_error_redacted(self) -> None:
        transport = MockAcceptanceTransport(
            fail_keys={"probe:leak": "upstream sk-abcdef123456 exploded"}
        )
        plan = ScenarioPlan(
            scenario_id="redaction_probe",
            title="脱敏探针",
            level="L0_pure",
            steps=(
                ScenarioStep(
                    step_id="leak-1",
                    kind=StepKind.CALL,
                    action="drill.noop",
                    target="mock:secret_probe",
                    provider="drill_local",
                    payload={
                        "api_key": "sk-abcdef123456",
                        "note": "普通文本不打码",
                        "count": 3,
                    },
                    idempotency_key="probe:leak",
                    cost_requests=1,
                ),
            ),
        )
        report = mk_runner().run(plan, make_auth(), transport)
        step = report.steps[0]
        assert step.status is StepStatus.FAILED
        assert step.redacted_payload["api_key"] == "***"
        assert step.redacted_payload["note"] == "普通文本不打码"
        assert step.redacted_payload["count"] == 3
        assert "abcdef123456" not in step.detail

    def test_redact_mapping_masks_nested_secret_keys(self) -> None:
        masked = redact_mapping(
            {"outer": {"authorization": "Bearer xyz", "keep": 1}, "list": ["a"]}
        )
        assert masked["outer"]["authorization"] == "***"
        assert masked["outer"]["keep"] == 1
        assert masked["list"] == ["a"]

    def test_failed_attempt_still_billed(self) -> None:
        transport = MockAcceptanceTransport(fail_actions={"drill.noop": "boom"})
        plan = one_call_scenario("failure_probe")
        report = mk_runner().run(plan, make_auth(), transport)
        assert report.steps[0].status is StepStatus.FAILED
        assert report.budget is not None
        assert report.budget.used_requests == 1  # 真实 attempt 即计费
        assert report.status is RunStatus.BLOCKED
        assert report.stop_reason is StopReason.STEP_FAILED
        assert report.steps[0].cost_requests == 1


# ---------------------------------------------------------------------------
# not_wired 诚实 + 断言失败停机 + 摘要
# ---------------------------------------------------------------------------


class TestHonestyPaths:
    def test_not_wired_transport_honest(self) -> None:
        transport = NotWiredTransport()
        report = mk_runner().run(
            build_send_queue_roundtrip_scenario(), make_auth(), transport
        )
        assert report.steps[0].status is StepStatus.NOT_WIRED
        assert report.stop_reason is StopReason.NOT_WIRED
        assert report.status is RunStatus.BLOCKED
        assert report.transport == "NotWiredTransport"
        # 未发生真实 attempt → 不扣预算（诚实零消耗）。
        assert report.budget is not None
        assert report.budget.used_requests == 0
        assert any("not_wired" in note for note in report.notes)

    def test_assertion_failure_stops_run(self) -> None:
        def _always_fail(_ctx: object) -> tuple[bool, str]:
            return False, "故意失败"

        plan = ScenarioPlan(
            scenario_id="assert_probe",
            title="断言失败探针",
            level="L0_pure",
            steps=(
                ScenarioStep(
                    step_id="a-1",
                    kind=StepKind.ASSERT,
                    assertion=_always_fail,  # type: ignore[arg-type]
                ),
                ScenarioStep(step_id="a-2", kind=StepKind.ASSERT),
            ),
        )
        transport = MockAcceptanceTransport()
        report = mk_runner().run(plan, make_auth(), transport)
        assert report.steps[0].status is StepStatus.FAILED
        assert report.steps[1].status is StepStatus.SKIPPED_NOT_RUN
        assert report.stop_reason is StopReason.STEP_FAILED
        assert report.status is RunStatus.BLOCKED
        # blocked/skipped 不得算 pass：状态计数无 passed 步。
        assert report.status_counts().get("passed", 0) == 0

    def test_report_summary_shape(self) -> None:
        transport = MockAcceptanceTransport()
        report = mk_runner().run(
            build_send_queue_roundtrip_scenario(),
            make_auth(),
            transport,
            build_id="b-1",
            manifest_revision="mr-9",
        )
        summary = report.to_summary()
        assert summary["run_id"] == report.run_id
        assert summary["status"] == "passed"
        assert summary["build_id"] == "b-1"
        assert summary["manifest_revision"] == "mr-9"
        assert summary["status_counts"] == {"passed": 5}
        assert summary["budget"]["used_requests"] == 2

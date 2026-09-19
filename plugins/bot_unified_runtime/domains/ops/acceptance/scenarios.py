"""离线示例场景库（V21-ACCEPTANCE-001：演示 AcceptanceRunner 引擎能力）。

全部场景为 L0（纯函数/预算闸演练）/ L1（本地 fake transport）层级——
合同 §8.2 层级单独记录，本轮**不提供** L2-L4 场景（真实 OS 沙箱/真实
provider/真实平台端到端属后续接线席）。场景只声明计划（步序+成本+断言），
执行一律经 :class:`AcceptanceRunner`，零真实出站。

场景清单：

- ``send_queue_roundtrip_mock``（L1）：发送队列往返 mock——入队→回执断言→
  同幂等键重投→去重断言（真实发送数不增）。演示 CALL/ASSERT 混排与幂等。
- ``divination_rest_idempotent``（L1）：占卜 REST 幂等——同 idempotency_key
  两次请求共享同一回执（缓存语义），真实调用数=1。演示 provider 白名单闸。
- ``overbudget_drill``（L0）：预算闸演练——三步各耗 1 次调用，配
  ``max_requests=2`` 的授权包即第三步被拒、run 以 ``budget_exhausted`` 停。
  演示拒绝路径的逐步状态落账（引擎能力自证，本身不该 PASSED）。

断言工厂返回 ``AssertionFn``（收 :class:`AssertionContext` 返回 (ok, detail)）；
mock 语义统计（``send_count`` 等）经鸭子类型读取，transport 未暴露时如实
unknown 不硬断言。
"""

from __future__ import annotations

from decimal import Decimal

from plugins.bot_unified_runtime.domains.ops.acceptance.runner import (
    AssertionContext,
    AssertionFn,
    ScenarioPlan,
    ScenarioStep,
    StepKind,
    StepStatus,
)

__all__ = [
    "DEFAULT_SCENARIOS",
    "build_divination_idempotency_scenario",
    "build_overbudget_drill_scenario",
    "build_send_queue_roundtrip_scenario",
    "expect_mock_send_count",
    "expect_same_receipt",
    "expect_step_accepted",
    "expect_step_duplicated",
    "expect_step_status",
    "get_scenario",
]


# ---------------------------------------------------------------------------
# 断言工厂
# ---------------------------------------------------------------------------


def expect_step_status(step_id: str, expected: StepStatus) -> AssertionFn:
    """断言某步处于期望状态（最通用的引擎能力演示断言）。"""

    def _assert(context: AssertionContext) -> tuple[bool, str]:
        result = context.results.get(step_id)
        if result is None:
            return False, f"步 {step_id} 无结果（未执行？）"
        ok = result.status is expected
        return ok, f"{step_id}.status={result.status.value} (期望 {expected.value})"

    return _assert


def expect_step_accepted(step_id: str) -> AssertionFn:
    """断言某 CALL 步回执被接受且非幂等命中（真实首投）。"""

    def _assert(context: AssertionContext) -> tuple[bool, str]:
        receipt = context.receipts.get(step_id)
        if receipt is None:
            return False, f"步 {step_id} 无回执（未执行或非 CALL）"
        ok = receipt.accepted and not receipt.duplicated
        return ok, (
            f"{step_id}: accepted={receipt.accepted} duplicated={receipt.duplicated}"
        )

    return _assert


def expect_step_duplicated(step_id: str) -> AssertionFn:
    """断言某 CALL 步命中幂等去重（同键重投未产生新发送）。"""

    def _assert(context: AssertionContext) -> tuple[bool, str]:
        receipt = context.receipts.get(step_id)
        if receipt is None:
            return False, f"步 {step_id} 无回执（未执行或非 CALL）"
        return receipt.duplicated, f"{step_id}: duplicated={receipt.duplicated}"

    return _assert


def expect_same_receipt(step_a: str, step_b: str) -> AssertionFn:
    """断言两步共享同一回执（REST 幂等缓存语义的核心证据）。"""

    def _assert(context: AssertionContext) -> tuple[bool, str]:
        ra = context.receipts.get(step_a)
        rb = context.receipts.get(step_b)
        if ra is None or rb is None:
            return False, f"回执缺失: {step_a}={ra is not None} {step_b}={rb is not None}"
        ok = ra.receipt_id == rb.receipt_id
        return ok, f"{step_a}/{step_b} receipt_id: {ra.receipt_id}/{rb.receipt_id}"

    return _assert


def expect_mock_send_count(expected: int) -> AssertionFn:
    """断言 mock 真实发送计数（幂等去重后不增）；transport 未暴露→unknown 失败。"""

    def _assert(context: AssertionContext) -> tuple[bool, str]:
        count = context.send_count()
        if count is None:
            return False, "transport 未暴露 send_count（unknown，不硬算 pass）"
        return count == expected, f"mock_send_count={count} (期望 {expected})"

    return _assert


# ---------------------------------------------------------------------------
# 场景定义
# ---------------------------------------------------------------------------


def build_send_queue_roundtrip_scenario() -> ScenarioPlan:
    """L1 发送队列往返 mock：入队→回执断言→同键重投→去重断言。"""
    return ScenarioPlan(
        scenario_id="send_queue_roundtrip_mock",
        title="发送队列往返（mock transport）",
        level="L1_fake_transport",
        description=(
            "入队一条 mock 消息→断言回执接受→同幂等键重投→断言 duplicated 且"
            "真实发送数仍为 1（幂等重跑不重发）。"
        ),
        steps=(
            ScenarioStep(
                step_id="sq-1-submit",
                kind=StepKind.CALL,
                action="send_queue.submit",
                target="mock:send_queue",
                provider="queue_local",
                payload={"message_id": "m-acc-001", "text": "验收往返 mock"},
                idempotency_key="acc:sq:m-acc-001",
                cost_requests=1,
                cost_by_currency={"CNY": Decimal("0.01")},
            ),
            ScenarioStep(
                step_id="sq-2-assert-accepted",
                kind=StepKind.ASSERT,
                assertion=expect_step_accepted("sq-1-submit"),
            ),
            ScenarioStep(
                step_id="sq-3-resubmit",
                kind=StepKind.CALL,
                action="send_queue.submit",
                target="mock:send_queue",
                provider="queue_local",
                payload={"message_id": "m-acc-001", "text": "验收往返 mock"},
                idempotency_key="acc:sq:m-acc-001",
                cost_requests=1,
                cost_by_currency={"CNY": Decimal("0.01")},
            ),
            ScenarioStep(
                step_id="sq-4-assert-dedup",
                kind=StepKind.ASSERT,
                assertion=expect_step_duplicated("sq-3-resubmit"),
            ),
            ScenarioStep(
                step_id="sq-5-assert-send-count",
                kind=StepKind.ASSERT,
                assertion=expect_mock_send_count(1),
            ),
        ),
    )


def build_divination_idempotency_scenario() -> ScenarioPlan:
    """L1 占卜 REST 幂等：同键两次请求共享同一回执，真实调用数=1。"""
    return ScenarioPlan(
        scenario_id="divination_rest_idempotent",
        title="占卜 REST 幂等（mock transport）",
        level="L1_fake_transport",
        description=(
            "同 idempotency_key 连发两次 tarot/draw → 两步共享同一 receipt_id"
            "（缓存语义），mock 真实调用数=1。演示 provider 白名单闸在位。"
        ),
        steps=(
            ScenarioStep(
                step_id="dv-1-draw",
                kind=StepKind.CALL,
                action="rest.get",
                target="mock:divination_rest",
                provider="divination_local",
                payload={"endpoint": "tarot/draw", "deck_key": "2026-09-18"},
                idempotency_key="acc:dv:tarot:2026-09-18",
                cost_requests=1,
                cost_by_currency={"CNY": Decimal("0.00")},
            ),
            ScenarioStep(
                step_id="dv-2-draw-again",
                kind=StepKind.CALL,
                action="rest.get",
                target="mock:divination_rest",
                provider="divination_local",
                payload={"endpoint": "tarot/draw", "deck_key": "2026-09-18"},
                idempotency_key="acc:dv:tarot:2026-09-18",
                cost_requests=1,
                cost_by_currency={"CNY": Decimal("0.00")},
            ),
            ScenarioStep(
                step_id="dv-3-assert-same-receipt",
                kind=StepKind.ASSERT,
                assertion=expect_same_receipt("dv-1-draw", "dv-2-draw-again"),
            ),
            ScenarioStep(
                step_id="dv-4-assert-send-count",
                kind=StepKind.ASSERT,
                assertion=expect_mock_send_count(1),
            ),
        ),
    )


def build_overbudget_drill_scenario() -> ScenarioPlan:
    """L0 预算闸演练：三步各耗 1 次，配 max_requests=2 授权包即第三步被拒。

    注意：本场景**设计上不通过**——它演示的是「超预算步骤拒执行+run 以
    budget_exhausted 停+拒绝步落账 rejected_budget、剩余步 skipped」这条
    引擎硬闸路径；配足预算才可全绿。
    """
    steps = []
    for index in range(1, 4):
        steps.append(
            ScenarioStep(
                step_id=f"ob-{index}-call",
                kind=StepKind.CALL,
                action="drill.noop",
                target="mock:drill",
                provider="drill_local",
                payload={"seq": index},
                cost_requests=1,
            )
        )
    return ScenarioPlan(
        scenario_id="overbudget_drill",
        title="预算闸演练（设计性拒绝路径）",
        level="L0_pure",
        description="三步各耗 1 次调用；授权包 max_requests<3 时第三步被预算闸拒绝。",
        steps=tuple(steps),
    )


# ---------------------------------------------------------------------------
# 注册表（合同 §9 ScenarioRegistry 最小形态：显式注册、按 id 取用）
# ---------------------------------------------------------------------------

DEFAULT_SCENARIOS: dict[str, ScenarioPlan] = {
    plan.scenario_id: plan
    for plan in (
        build_send_queue_roundtrip_scenario(),
        build_divination_idempotency_scenario(),
        build_overbudget_drill_scenario(),
    )
}


def get_scenario(scenario_id: str) -> ScenarioPlan:
    """按 id 取场景（返回缓存计划；步/载荷只读，引擎不改写）。"""
    plan = DEFAULT_SCENARIOS.get(scenario_id)
    if plan is None:
        raise KeyError(
            f"场景未注册: {scenario_id}（已注册: {sorted(DEFAULT_SCENARIOS)}）"
        )
    return plan

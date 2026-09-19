"""ops/acceptance：一次授权自动场景执行（V21-ACCEPTANCE-001 唯一载体）。

AcceptanceRunner：授权包（收件人/目标与场景/provider 白名单/金额与调用预算/
时间窗/撤销令牌）驱动 ScenarioPlan 串行执行；预算/时间窗/撤销/授权四类硬闸；
mock transport 离线全流程；报告逐步状态+预算消耗+trace 关联+脱敏。

**真实出站本轮不接**：``NotWiredTransport`` 诚实 ``not_wired``；
live_validation=unknown。真实 transport 由后续接线席实现
``AcceptanceTransport`` 协议注入，引擎零改动。
"""

from .runner import (
    DEFAULT_CURRENCY,
    AcceptanceRunner,
    AcceptanceTransport,
    AssertionContext,
    AssertionFn,
    AuthorizationPackage,
    AuthorizationRequired,
    BudgetLedger,
    BudgetSnapshot,
    MockAcceptanceTransport,
    NotWiredTransport,
    RevocationToken,
    RunReport,
    RunStatus,
    ScenarioPlan,
    ScenarioStep,
    StepKind,
    StepResult,
    StepStatus,
    StopReason,
    TransportNotWired,
    TransportReceipt,
    TransportRequest,
    redact_mapping,
    redact_text,
)
from .scenarios import (
    DEFAULT_SCENARIOS,
    build_divination_idempotency_scenario,
    build_overbudget_drill_scenario,
    build_send_queue_roundtrip_scenario,
    get_scenario,
)

__all__ = [
    "DEFAULT_CURRENCY",
    "DEFAULT_SCENARIOS",
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
    "build_divination_idempotency_scenario",
    "build_overbudget_drill_scenario",
    "build_send_queue_roundtrip_scenario",
    "get_scenario",
    "redact_mapping",
    "redact_text",
]

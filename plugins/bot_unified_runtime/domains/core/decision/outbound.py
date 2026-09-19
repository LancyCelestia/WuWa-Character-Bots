"""V2.1 S6 中央 Dispatcher 出站收编地基（A16）：统一出口门面。

合同：主规范 §10（Dispatcher/出站/纯文本）——OutboundIntent 严格 DTO、
Transport 固定映射、发送前复验、许可租约线性化点、UNKNOWN 先对账。
本门面保持轻导入：契约与注册表零 nonebot / 零网络 / 零配置依赖。

模块分层（本席文件域，全部新增）：
- ``outbound_contracts``：DTO / 状态机 / 准入协议 / 许可租约 / 幂等与对账。
- ``outbound_registry``：Transport 固定映射注册表 + 入口接管登记表（A1 投影）。
- 本模块：稳定出口（接线席位只 import 这里，内部分层可继续演化）。

生产接线由后续席位按 ``outbound_registry.build_default_takeover_registry()``
的登记表逐点迁移；本席**不改任何现存文件**（__init__.py 与 sender/ 均为
热区，只读）。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.core.decision.outbound_contracts import (
    OPERATION_TRANSITIONS,
    PART_TRANSITIONS,
    AdmissionDenied,
    AdmissionTicket,
    AdmissionVerdict,
    CancelOutcome,
    ConfirmationCheck,
    DedupeIndex,
    DrainReport,
    DuplicateClaim,
    ExpiryCheck,
    FeatureGateCheck,
    IllegalOutboundTransition,
    LeasePaused,
    OperationStateCheck,
    OutboundAdmissionCheck,
    OutboundAdmissionGate,
    OutboundIntent,
    OutboundOperation,
    OutboundOperationState,
    OutboundPart,
    OutboundPartState,
    OutboundTarget,
    PartStateCheck,
    PermissionCheck,
    PermitLease,
    PermitToken,
    ReconciliationLedger,
    UnknownPendingError,
    derive_dedupe_key,
    operation_has_inflight_claim,
    transition_operation,
    transition_part,
)
from plugins.bot_unified_runtime.domains.core.decision.outbound_registry import (
    DirectSendCategory,
    DirectSendEntry,
    EntryKind,
    MatcherEntry,
    MigrationStatus,
    RouteGroupEntry,
    SchedulerEntry,
    TakeoverChecklist,
    TakeoverRegistry,
    TransportChannel,
    TransportEntry,
    TransportPlatform,
    TransportRegistry,
    UnregisteredTransportError,
    build_default_takeover_registry,
    build_default_transport_registry,
)

# 导出面按 RUF022 字母序排列（分组语义见各段定义处；此处不再内联分组注释，
# 否则排序会把注释留在错误位置）。
__all__ = [
    "OPERATION_TRANSITIONS",
    "PART_TRANSITIONS",
    "AdmissionDenied",
    "AdmissionTicket",
    "AdmissionVerdict",
    "CancelOutcome",
    "ConfirmationCheck",
    "DedupeIndex",
    "DirectSendCategory",
    "DirectSendEntry",
    "DrainReport",
    "DuplicateClaim",
    "EntryKind",
    "ExpiryCheck",
    "FeatureGateCheck",
    "IllegalOutboundTransition",
    "LeasePaused",
    "MatcherEntry",
    "MigrationStatus",
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
    "RouteGroupEntry",
    "SchedulerEntry",
    "TakeoverChecklist",
    "TakeoverRegistry",
    "TransportChannel",
    "TransportEntry",
    "TransportPlatform",
    "TransportRegistry",
    "UnknownPendingError",
    "UnregisteredTransportError",
    "build_default_takeover_registry",
    "build_default_transport_registry",
    "derive_dedupe_key",
    "operation_has_inflight_claim",
    "transition_operation",
    "transition_part",
]

"""domains/ops/repair：自修复编排服务（V21-REPAIR-001 唯一载体）。

RepairService：失败测试坐标 → 两轮预算内生成**待审补丁**（unified diff
落 pending 待审区）→ 沙箱跑目标测试验证 → 过=verified_pending 仍不应用 /
两轮未过=abandoned+RED 保留声明+诊断报告。绝不直接写目标文件；越权应用
面（apply_to_target/deploy_patch）一律拒绝并审计。脱敏复用 render 真身
redact_local_secrets（懒加载单一事实源）。
"""

from .service import (
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MAX_TEXT_CHARS,
    FORBIDDEN_TARGET_PARTS,
    LoggingRepairAuditSink,
    NoopVerifier,
    PatchApplyError,
    PatchGenerator,
    PatchProposal,
    RepairAuditSink,
    RepairRequest,
    RepairService,
    RepairStatus,
    RepairTicket,
    RepairVerifier,
    SandboxCopyVerifier,
    StaticProposalGenerator,
    TargetRejectedError,
    UnauthorizedRepairOperation,
    VerificationResult,
    apply_unified_diff,
    redact_text,
    redact_user_text,
)

__all__ = [
    "DEFAULT_MAX_ROUNDS",
    "DEFAULT_MAX_TEXT_CHARS",
    "FORBIDDEN_TARGET_PARTS",
    "LoggingRepairAuditSink",
    "NoopVerifier",
    "PatchApplyError",
    "PatchGenerator",
    "PatchProposal",
    "RepairAuditSink",
    "RepairRequest",
    "RepairService",
    "RepairStatus",
    "RepairTicket",
    "RepairVerifier",
    "SandboxCopyVerifier",
    "StaticProposalGenerator",
    "TargetRejectedError",
    "UnauthorizedRepairOperation",
    "VerificationResult",
    "apply_unified_diff",
    "redact_text",
    "redact_user_text",
]

"""domains/ops/recovery：统一运行自愈（V21-HEAL-001 唯一载体）。"""

from .service import (
    DEFAULT_ACTION_BY_KIND,
    FailureKind,
    IncidentReporter,
    RecoveryAction,
    RecoveryDecision,
    RecoveryExecutor,
    RecoveryOutcome,
    RecoveryPolicy,
    RecoveryService,
)

__all__ = [
    "DEFAULT_ACTION_BY_KIND",
    "FailureKind",
    "IncidentReporter",
    "RecoveryAction",
    "RecoveryDecision",
    "RecoveryExecutor",
    "RecoveryOutcome",
    "RecoveryPolicy",
    "RecoveryService",
]

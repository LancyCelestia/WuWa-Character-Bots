from __future__ import annotations

from plugins.wuwa_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    PrivacyLevel,
    ReviewAction,
    ReviewResult,
    RiskLevel,
    SessionType,
)


def review_capability_result(
    result: CapabilityResult,
    decision: BotDecision,
) -> ReviewResult:
    reasons: list[str] = []
    action = ReviewAction.ALLOW
    approved = True

    if result.risk_level is RiskLevel.CRITICAL:
        approved = False
        action = ReviewAction.BLOCK
        reasons.append("critical risk is blocked")

    if (
        result.privacy_level in {PrivacyLevel.PERSONAL, PrivacyLevel.CREDENTIALED}
        and decision.target_scope is SessionType.GROUP
    ):
        approved = False
        action = ReviewAction.MOVE_PRIVATE
        reasons.append("personal output cannot be sent to group")

    return ReviewResult(
        request_id=result.request_id,
        approved=approved,
        action=action,
        risk_level=result.risk_level,
        privacy_level=result.privacy_level,
        reasons=reasons,
        safe_text=result.body or result.summary or result.title,
        debug_id=result.debug_id,
    )

from __future__ import annotations

from plugins.wuwa_unified_runtime.contracts import (
    IncomingMessage,
    PolicyEvaluation,
    PrivacyLevel,
    RiskLevel,
    SessionType,
)

COMMAND_PREFIX = "/wuwa"


def evaluate_policy(
    message: IncomingMessage,
    capability_id: str,
) -> PolicyEvaluation:
    cooldown_key = f"{capability_id}:{message.session_id}:{message.sender_id}"

    if message.risk_level is RiskLevel.CRITICAL:
        return PolicyEvaluation(
            request_id=message.request_id,
            allowed=False,
            reason="critical_input_risk",
            risk_level=RiskLevel.CRITICAL,
            cooldown_key=cooldown_key,
            privacy_level=message.privacy_level or PrivacyLevel.PERSONAL,
            audit_tags=["policy", "critical_input_blocked"],
        )

    if message.session_type is SessionType.GROUP:
        text = message.plain_text.strip()
        command_triggered = text.startswith(COMMAND_PREFIX)
        if not command_triggered and not message.mentions_bot:
            return PolicyEvaluation(
                request_id=message.request_id,
                allowed=False,
                reason="passive_group_message",
                risk_level=RiskLevel.LOW,
                cooldown_key=cooldown_key,
                privacy_level=PrivacyLevel.GROUP,
                audit_tags=["policy", "group_observe_only"],
            )

    return PolicyEvaluation(
        request_id=message.request_id,
        allowed=True,
        reason="allowed",
        risk_level=message.risk_level,
        cooldown_key=cooldown_key,
        privacy_level=message.privacy_level or PrivacyLevel.PUBLIC,
        audit_tags=["policy"],
    )

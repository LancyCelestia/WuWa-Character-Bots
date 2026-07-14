from __future__ import annotations

from dataclasses import dataclass

from plugins.wuwa_unified_runtime.contracts import (
    IncomingMessage,
    PolicyEvaluation,
    PrivacyLevel,
    RiskLevel,
    SessionType,
)
from .roles import ROLE_BLOCKED, role_audit_tags

COMMAND_PREFIX = "/wuwa"


@dataclass(frozen=True)
class PolicySettings:
    group_command_prefix: str = COMMAND_PREFIX


def evaluate_policy(
    message: IncomingMessage,
    capability_id: str,
    settings: PolicySettings | None = None,
) -> PolicyEvaluation:
    cooldown_key = f"{capability_id}:{message.session_id}:{message.sender_id}"
    active_settings = settings or PolicySettings()
    actor_roles = message.sender_roles
    role_tags = role_audit_tags(actor_roles)

    if ROLE_BLOCKED in actor_roles:
        return PolicyEvaluation(
            request_id=message.request_id,
            allowed=False,
            reason="sender_blocked",
            risk_level=RiskLevel.MEDIUM,
            cooldown_key=cooldown_key,
            privacy_level=message.privacy_level or PrivacyLevel.PERSONAL,
            actor_roles=actor_roles,
            audit_tags=["policy", *role_tags, "sender_blocked"],
        )

    if message.risk_level is RiskLevel.CRITICAL:
        return PolicyEvaluation(
            request_id=message.request_id,
            allowed=False,
            reason="critical_input_risk",
            risk_level=RiskLevel.CRITICAL,
            cooldown_key=cooldown_key,
            privacy_level=message.privacy_level or PrivacyLevel.PERSONAL,
            actor_roles=actor_roles,
            audit_tags=["policy", *role_tags, "critical_input_blocked"],
        )

    if message.session_type is SessionType.GROUP:
        text = message.plain_text.strip()
        command_triggered = text.startswith(active_settings.group_command_prefix)
        if not command_triggered and not message.mentions_bot:
            return PolicyEvaluation(
                request_id=message.request_id,
                allowed=False,
                reason="passive_group_message",
                risk_level=RiskLevel.LOW,
                cooldown_key=cooldown_key,
                privacy_level=PrivacyLevel.GROUP,
                actor_roles=actor_roles,
                audit_tags=["policy", *role_tags, "group_observe_only"],
            )

    return PolicyEvaluation(
        request_id=message.request_id,
        allowed=True,
        reason="allowed",
        risk_level=message.risk_level,
        cooldown_key=cooldown_key,
        privacy_level=message.privacy_level or PrivacyLevel.PUBLIC,
        actor_roles=actor_roles,
        audit_tags=["policy", *role_tags],
    )

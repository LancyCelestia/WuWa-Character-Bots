from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    PolicyEvaluation,
    PrivacyLevel,
    RiskLevel,
    SessionType,
)
from .roles import ROLE_BLOCKED, role_audit_tags

COMMAND_PREFIX = "/bot"


@dataclass(frozen=True)
class PolicySettings:
    group_command_prefix: str = COMMAND_PREFIX
    # 额外命令判定：例如角色昵称命令（/岸宝帮助）在群聊中视为命令触发。
    extra_command_check: Callable[[str], bool] | None = None
    # 群聊自动接话：关闭时只有命令/点名才回复；开启时按概率抽签回复。
    group_auto_reply_enabled: bool = False
    group_auto_reply_probability: float = 0.0


def deterministic_group_reply_lottery(seed: str, probability: float) -> bool:
    """确定性抽签：同一消息永远得到同一结果（可复现、可测试）。

    用 SHA-256 前 8 位映射到 [0,10000)，避免用随机数导致测试与
    审计不可复现。
    """
    if probability <= 0:
        return False
    if probability >= 1:
        return True
    bucket = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 10000
    return bucket < probability * 10000


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
        extra_check = active_settings.extra_command_check
        if extra_check is not None and extra_check(text):
            command_triggered = True
        if not command_triggered and not message.mentions_bot:
            auto_reply = (
                active_settings.group_auto_reply_enabled
                and deterministic_group_reply_lottery(
                    f"{message.session_id}:{message.message_id or message.request_id}",
                    active_settings.group_auto_reply_probability,
                )
            )
            if not auto_reply:
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

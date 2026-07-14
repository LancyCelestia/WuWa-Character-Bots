from __future__ import annotations

from dataclasses import dataclass

from plugins.wuwa_unified_runtime.config import Config
from plugins.wuwa_unified_runtime.contracts import IncomingMessage

ROLE_USER = "user"
ROLE_TRUSTED = "trusted"
ROLE_ENTERPRISE = "enterprise"
ROLE_ADMIN = "admin"
ROLE_BLOCKED = "blocked"
ROLE_ORDER = (ROLE_USER, ROLE_TRUSTED, ROLE_ENTERPRISE, ROLE_ADMIN, ROLE_BLOCKED)


@dataclass(frozen=True)
class RoleSettings:
    admin_user_ids: frozenset[str]
    enterprise_user_ids: frozenset[str]
    trusted_user_ids: frozenset[str]
    blocked_user_ids: frozenset[str]

    def resolve_roles(self, message: IncomingMessage) -> list[str]:
        sender_id = message.sender_id.strip()
        roles = {ROLE_USER}
        if sender_id in self.trusted_user_ids:
            roles.add(ROLE_TRUSTED)
        if sender_id in self.enterprise_user_ids:
            roles.add(ROLE_ENTERPRISE)
        if sender_id in self.admin_user_ids:
            roles.add(ROLE_ADMIN)
        if sender_id in self.blocked_user_ids:
            roles.add(ROLE_BLOCKED)
        return [role for role in ROLE_ORDER if role in roles]

    def counts(self) -> dict[str, int]:
        return {
            ROLE_ADMIN: len(self.admin_user_ids),
            ROLE_ENTERPRISE: len(self.enterprise_user_ids),
            ROLE_TRUSTED: len(self.trusted_user_ids),
            ROLE_BLOCKED: len(self.blocked_user_ids),
        }


def build_role_settings(config: Config) -> RoleSettings:
    return RoleSettings(
        admin_user_ids=frozenset(config.wuwa_admin_user_ids),
        enterprise_user_ids=frozenset(config.wuwa_enterprise_user_ids),
        trusted_user_ids=frozenset(config.wuwa_trusted_user_ids),
        blocked_user_ids=frozenset(config.wuwa_blocked_user_ids),
    )


def role_audit_tags(roles: list[str]) -> list[str]:
    return [f"role:{role}" for role in roles if role != ROLE_USER]

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from plugins.wuwa_unified_runtime.contracts import IncomingMessage
from plugins.wuwa_unified_runtime.contracts.runtime import StrictBaseModel, new_debug_id

DEFAULT_BYPASS_ROLES = ["admin"]
DEFAULT_SESSION_TYPES = ["group"]


class QuietHoursDecision(StrictBaseModel):
    allowed: bool
    reason: str = "allowed"
    audit_tags: list[str] = Field(default_factory=lambda: ["quiet_hours:ok"])
    debug_id: str = Field(default_factory=new_debug_id)


class QuietHoursSettings(StrictBaseModel):
    enabled: bool = False
    start_time: str = "23:00"
    end_time: str = "07:00"
    timezone_name: str = "Asia/Hong_Kong"
    session_types: list[str] = Field(default_factory=lambda: list(DEFAULT_SESSION_TYPES))
    bypass_roles: list[str] = Field(default_factory=lambda: list(DEFAULT_BYPASS_ROLES))

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_clock_time(cls, value: str) -> str:
        _parse_hhmm(value)
        return value.strip()

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("quiet hours timezone must not be empty")
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown quiet hours timezone: {normalized}") from exc
        return normalized

    @field_validator("session_types")
    @classmethod
    def normalize_session_types(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values if value.strip()]
        allowed = {"private", "group"}
        invalid = [value for value in normalized if value not in allowed]
        if invalid:
            raise ValueError("quiet hours session types must be private or group")
        return list(dict.fromkeys(normalized))

    @field_validator("bypass_roles")
    @classmethod
    def normalize_bypass_roles(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values if value.strip()]
        return list(dict.fromkeys(normalized))


class QuietHoursChecker:
    def __init__(
        self,
        settings: QuietHoursSettings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or QuietHoursSettings()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def check(
        self,
        message: IncomingMessage,
        capability_id: str,
    ) -> QuietHoursDecision:
        if not self.settings.enabled:
            return QuietHoursDecision(
                allowed=True,
                reason="disabled",
                audit_tags=["quiet_hours:disabled"],
            )
        if self._has_bypass_role(message):
            return QuietHoursDecision(
                allowed=True,
                reason="role_bypass",
                audit_tags=["quiet_hours:bypass_role"],
            )
        if message.session_type.value not in set(self.settings.session_types):
            return QuietHoursDecision(
                allowed=True,
                reason="session_type_excluded",
                audit_tags=["quiet_hours:session_excluded"],
            )
        if not self._is_in_quiet_hours():
            return QuietHoursDecision(
                allowed=True,
                reason="outside_quiet_hours",
                audit_tags=["quiet_hours:ok"],
            )
        return QuietHoursDecision(
            allowed=False,
            reason="quiet_hours",
            audit_tags=[
                "quiet_hours:blocked",
                f"quiet_hours:session:{message.session_type.value}",
                f"quiet_hours:capability:{capability_id}",
            ],
        )

    def _has_bypass_role(self, message: IncomingMessage) -> bool:
        bypass_roles = set(self.settings.bypass_roles)
        return any(role.strip().lower() in bypass_roles for role in message.sender_roles)

    def _is_in_quiet_hours(self) -> bool:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        local_time = now.astimezone(ZoneInfo(self.settings.timezone_name)).time()
        start = _parse_hhmm(self.settings.start_time)
        end = _parse_hhmm(self.settings.end_time)
        if start == end:
            return True
        if start < end:
            return start <= local_time < end
        return local_time >= start or local_time < end


def build_quiet_hours_settings(config: object) -> QuietHoursSettings:
    return QuietHoursSettings(
        enabled=bool(getattr(config, "wuwa_quiet_hours_enabled", False)),
        start_time=str(getattr(config, "wuwa_quiet_hours_start", "23:00")),
        end_time=str(getattr(config, "wuwa_quiet_hours_end", "07:00")),
        timezone_name=str(getattr(config, "wuwa_quiet_hours_timezone", "Asia/Hong_Kong")),
        session_types=list(
            getattr(config, "wuwa_quiet_hours_session_types", DEFAULT_SESSION_TYPES)
        ),
        bypass_roles=list(
            getattr(config, "wuwa_quiet_hours_bypass_roles", DEFAULT_BYPASS_ROLES)
        ),
    )


def build_quiet_hours_checker(config: object) -> QuietHoursChecker:
    return QuietHoursChecker(build_quiet_hours_settings(config))


def _parse_hhmm(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("quiet hours time must use HH:MM")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError("quiet hours time must use numeric HH:MM") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("quiet hours time is out of range")
    return time(hour=hour, minute=minute)

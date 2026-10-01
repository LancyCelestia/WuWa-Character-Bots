from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from plugins.bot_unified_runtime.contracts import IncomingMessage
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    StrictBaseModel,
    new_debug_id,
)

DEFAULT_BYPASS_ROLES = ["admin"]
# E05 缺口三：私聊 formerly 整条不在覆盖面上（`["group"]`），"安静时间"对私聊
# 形同虚设——夜间任意命令与任意私聊都直接免检。缺省含 private。
# ⚠ 生产真身缺省住在 config.py 的 `bot_quiet_hours_session_types`（现值 ["group"]），
# `build_quiet_hours_settings` 只在 Config **没有**该字段时才回落到这里；本枚改动
# 要在生产生效必须同批改 config.py 缺省（＝三面同批，见 patches/E05-CONFIG-REQUEST.md），
# 且 `.env` 若显式写了 BOT_QUIET_HOURS_SESSION_TYPES=group 仍会盖住新缺省。
DEFAULT_SESSION_TYPES = ["group", "private"]
# 「聊天类」能力＝安静时间本该拦的那些；不在这张表里的就是命令类能力。
CHAT_LIKE_CAPABILITY_IDS = frozenset({"bot.chat", "bot.content"})
# F1（S-MAILINGRESS 审计 / S-FIX-MAILINGRESS-R 修复）：email 入枚举面。
# 判据与运行时咽喉 `chat_reply/runtime/settings.py::_session_types_converter`
# 对齐——那里早收 email、这里不收，就是「同一键两本枚举账」：/bot runtime set
# 写 email 能落库，策略校验器却永不认（台账 #50/#56 同族坑）。修法只扩枚举面：
# 覆盖判定仍走 `check()` 的 `session_type.value` 单一中央真身（本文件 :111 一腿、
# outbound_gate 的 `_quiet_verdict` 读同一份 session_types），**mail 没有第二道闸**。
# 与 QQ 私聊同形制＝**可收、opt-in**：缺省仍是 group，配置收编才生效。
CONFIGURABLE_SESSION_TYPES = {"private", "group", "email"}


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
    # 直连豁免的形状（E05 缺口三）：True＝`@bot` **且**命令类能力才豁免（`∧`）；
    # False＝旧行为「`@` 或非 bot.chat/bot.content **任一**即旁路」（`∨`，仅供止血回退）。
    # 旧形状的后果＝安静时段内任意命令能力、任意 @ 全免 ⇒ 这道门夜间等于没上。
    direct_bypass_requires_both: bool = True

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
        # F1 修复：枚举面收 email（与运行时咽喉 _session_types_converter 对齐，
        # 见模块头 CONFIGURABLE_SESSION_TYPES 注释）。判定真身仍是 check() 的
        # session_type.value 比对（:119 单腿），此处只扩「可配置」面、不造第二道闸。
        invalid = [value for value in normalized if value not in CONFIGURABLE_SESSION_TYPES]
        if invalid:
            raise ValueError(
                "quiet hours session types must be one of private/group/email"
            )
        return list(dict.fromkeys(normalized))

    @field_validator("bypass_roles")
    @classmethod
    def normalize_bypass_roles(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values if value.strip()]
        return list(dict.fromkeys(normalized))


class QuietHoursChecker:
    def __init__(
        self,
        settings: QuietHoursSettings | Callable[[], QuietHoursSettings] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # settings 可以是静态对象，也可以是**每次判定时求值的 callable**。
        # 后者让安静时间能读运行时 store 热改（否则装配期快照会把
        # /bot runtime set 的效果吃掉，直到进程重启才生效）。
        self._settings_source = settings or QuietHoursSettings()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def settings(self) -> QuietHoursSettings:
        """当前安静时间设置（callable 时实时求值）。"""
        source = self._settings_source
        if callable(source):
            try:
                resolved = source()
            except Exception:  # noqa: BLE001 - 求值失败回退默认（不误拦消息）。
                return QuietHoursSettings()
            return resolved if isinstance(resolved, QuietHoursSettings) else QuietHoursSettings()
        return source

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
        if self._is_direct_request(message, capability_id):
            return QuietHoursDecision(
                allowed=True,
                reason="direct_request_bypass",
                audit_tags=["quiet_hours:direct_request_bypass"],
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

    def _is_direct_request(self, message: IncomingMessage, capability_id: str) -> bool:
        """直连豁免判据（E05 缺口三：`or` 收成分离为 `and`）。

        缺省 strict＝`@bot` **且**命令类能力（不在 CHAT_LIKE_CAPABILITY_IDS）才豁免：
        - 旧形状里"非 bot.chat 即旁路"这一腿＝**任意命令能力夜间全免**，正是缺口本身；
        - "只 @ 不说事"那一腿夜间也不再唤醒 bot——安静时间就是给 bot 睡觉用的，
          真要点名办事走 `@bot /bot …`（两条件同现）这条腿。
        旁路顺序仍排在 `_has_bypass_role` 之后（admin 在最前，既有语义不动）。
        """
        mentioned = bool(message.mentions_bot)
        command_like = capability_id not in CHAT_LIKE_CAPABILITY_IDS
        if self.settings.direct_bypass_requires_both:
            return mentioned and command_like
        return mentioned or command_like

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
        enabled=bool(getattr(config, "bot_quiet_hours_enabled", False)),
        start_time=str(getattr(config, "bot_quiet_hours_start", "23:00")),
        end_time=str(getattr(config, "bot_quiet_hours_end", "07:00")),
        timezone_name=str(getattr(config, "bot_quiet_hours_timezone", "Asia/Hong_Kong")),
        session_types=list(
            getattr(config, "bot_quiet_hours_session_types", DEFAULT_SESSION_TYPES)
        ),
        bypass_roles=list(
            getattr(config, "bot_quiet_hours_bypass_roles", DEFAULT_BYPASS_ROLES)
        ),
        # 缺口三的收紧开关读点：config 无该字段时取 True＝新行为生效（三面登记见
        # patches/E05-CONFIG-REQUEST.md，补字段前后这段都不会炸构造）。
        direct_bypass_requires_both=bool(
            getattr(config, "bot_quiet_hours_direct_bypass_requires_both", True)
        ),
    )


def build_quiet_hours_checker(
    config: object,
    *,
    settings_provider: Callable[[], QuietHoursSettings] | None = None,
) -> QuietHoursChecker:
    """构造安静时间检查器。

    传 ``settings_provider`` 时每次判定实时求值（可读运行时 store 热改）；
    否则退回启动期快照（旧行为）。
    """
    if settings_provider is not None:
        return QuietHoursChecker(settings_provider)
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

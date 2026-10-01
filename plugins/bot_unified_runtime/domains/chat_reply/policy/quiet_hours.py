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

from .rate_limit import CHAT_LIKE_CAPABILITY_IDS

DEFAULT_BYPASS_ROLES = ["admin"]
# 覆盖册缺省＝**只罩 group**。私聊/email 要不要进覆盖面属**配置面**（键
# `BOT_QUIET_HOURS_SESSION_TYPES`，枚举面见下方 `CONFIGURABLE_SESSION_TYPES`），
# 由用户裁、由 config.py 落，**不由补丁焊死**：曾有版本把 private 擅自写进这里，
# 于是「夜间私聊自己也被哑」这件事在代码里就发生了，三面登记（config 字段 /
# settings 热改态 / `.env.example`）一行没动——台账 #68★「只补一面必红另一面」。
# 现值真身＝`config.py` 的 `bot_quiet_hours_session_types`（缺省 ["group"]）；
# `build_quiet_hours_settings` 只在 Config **没有**该字段时才回落到这里。
DEFAULT_SESSION_TYPES = ["group"]
# 「聊天类」名册的唯一落点在 `rate_limit.py`（限流侧与安静侧同一真身，禁第二处
# 字面量；两层判据不同已在彼处注释写清）。本模块只吃宽层＝被动回复类。
# F1（S-MAILINGRESS 审计 / S-FIX-MAILINGRESS-R 修复）：email 入枚举面。
# 判据与运行时咽喉 `chat_reply/runtime/settings.py::_session_types_converter`
# 对齐——那里早收 email、这里不收，就是「同一键两本枚举账」：/bot runtime set
# 写 email 能落库，策略校验器却永不认（台账 #50/#56 同族坑）。修法只扩枚举面：
# 覆盖判定仍走 `check()` 里 `session_type.value` 比对这一条中央腿（本文件不另开
# 第二道闸，outbound_gate 的 `_quiet_verdict` 读同一份 session_types）。
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
    # 直连豁免的**两条腿各自一枚开关**（2026-10-01 用户裁定「夜间 @bot 点名仍必应」）。
    # 曾被并成单枚 `direct_bypass_requires_both`＝把两腿焊成 `∧`，后果是夜里
    # ①只 @ 不说话的聊天被拦、②指令族也被拦——两枚都是 v21r2 凌晨实弹事故换来的
    # 锁（`tests/test_v21r2_hotzone_quiet_silence.py` 的
    # `test_quiet_hours_direct_mention_bypass_preserved` 与
    # `test_quiet_hours_command_capability_bypass_preserved`，其 docstring 写死
    # 「既有门语义不变：mentions_bot 直通、非聊天类能力直通」）。缺省两腿**都照旧
    # 旁路**＝那两把锁的形状；要收紧哪一腿在配置面单独立键裁（读点见
    # `build_quiet_hours_settings`），不在补丁里代裁。
    direct_bypass_covers_mentions: bool = True
    direct_bypass_covers_commands: bool = True

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
        # 见模块头 CONFIGURABLE_SESSION_TYPES 注释）。判定真身仍是 `check()` 里
        # 「`session_type.value` 是否在 session_types 册上」那一条中央腿，
        # 此处只扩「可配置」面、不造第二道闸。
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
        leg = self._direct_bypass_leg(message, capability_id)
        if leg:
            return QuietHoursDecision(
                allowed=True,
                reason="direct_request_bypass",
                audit_tags=[
                    "quiet_hours:direct_request_bypass",
                    f"quiet_hours:bypass:{leg}",
                ],
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

    def _direct_bypass_leg(self, message: IncomingMessage, capability_id: str) -> str:
        """这条消息命中哪一腿直连豁免（`""`＝不豁免）。

        两腿各读各的开关、互不顶替（用户裁定 2026-10-01）：
        - `mentions`：@bot 点名——夜里仍必应，与能力是不是聊天类无关；
        - `commands`：命令类能力（不在宽层名册 `CHAT_LIKE_CAPABILITY_IDS` 里）——
          指令族照旧直通；`bot.content`（链接解析）属被动回复，不在这一腿。
        命中的腿名进 audit_tags（`quiet_hours:bypass:{mentions|commands}`），
        复盘时才分得清「夜里被放行的那条到底是点名还是命令」。
        旁路顺序仍排在 `_has_bypass_role` 之后（admin 在最前，既有语义不动）。
        """
        settings = self.settings
        if settings.direct_bypass_covers_mentions and message.mentions_bot:
            return "mentions"
        if settings.direct_bypass_covers_commands and (
            capability_id not in CHAT_LIKE_CAPABILITY_IDS
        ):
            return "commands"
        return ""

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
        # 直连豁免两腿的读点：Config 无该字段时取**代码缺省 True＝两腿照旧旁路**
        # （既有门语义，v21r2 两把锁钉的就是这一形）。要收紧哪一腿在配置面裁，
        # 三面同批（config 字段 + settings 热改态登记 + `.env.example`）。
        direct_bypass_covers_mentions=bool(
            getattr(config, "bot_quiet_hours_direct_bypass_mentions", True)
        ),
        direct_bypass_covers_commands=bool(
            getattr(config, "bot_quiet_hours_direct_bypass_commands", True)
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

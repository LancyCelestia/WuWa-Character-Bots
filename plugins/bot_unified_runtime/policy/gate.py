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

# 四档群聊策略槽位；动态名单 provider 用这些键返回覆盖集合。
GROUP_POLICY_SLOTS = ("black1", "black2", "white1", "white2")


@dataclass(frozen=True)
class PolicySettings:
    group_command_prefix: str = COMMAND_PREFIX
    # 额外命令判定：例如角色昵称命令（/岸宝帮助）在群聊中视为命令触发。
    extra_command_check: Callable[[str], bool] | None = None
    # 群聊自动接话：关闭时只有命令/点名才回复；开启时按概率抽签回复。
    group_auto_reply_enabled: bool = False
    group_auto_reply_probability: float = 0.0
    # 群聊回复策略：black1/black2/white1/white2 四张静态群号集合。
    group_black1: frozenset[str] = frozenset()
    group_black2: frozenset[str] = frozenset()
    group_white1: frozenset[str] = frozenset()
    group_white2: frozenset[str] = frozenset()
    # 白名单1 的自然语言提问判定：命中即视为有效触发（不带@/斜杠也回）。
    natural_chat_check: Callable[[str], bool] | None = None
    # 白名单1 的已支持链接判定：未提供时使用已注册内容解析器的规则。
    supported_url_check: Callable[[str], bool] | None = None
    # 白名单1 图片消息的回复概率：独立于闲聊抽签（发图希望被看到时设 1.0）。
    vision_reply_probability: float = 1.0
    # 动态名单 provider：返回 {black1/black2/white1/white2: 群号集合}。
    # 返回的键会覆盖对应静态集合（管理员热改优先于 .env），未返回的键保持静态。
    group_lists_provider: Callable[[], dict[str, frozenset[str]]] | None = None


def _message_has_image(message: IncomingMessage) -> bool:
    """消息是否携带图片/表情包段（供白名单1图片回复概率判定）。"""
    from plugins.bot_unified_runtime.sources.vision_describe import extract_image_urls

    try:
        return bool(extract_image_urls(getattr(message, "raw_segments", None)))
    except Exception:  # noqa: BLE001 - 图片判定失败按无图处理。
        return False


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


def _effective_group_lists(settings: PolicySettings) -> dict[str, frozenset[str]]:
    """合并静态四档名单与运行时 provider 名单。

    语义：provider 返回的键是权威值（管理员热改覆盖 .env）；返回 None
    的键沿用静态集合；provider 抛异常或返回非 dict 时安全回退静态集合，
    绝不让名单读取失败阻塞消息链路。
    """
    effective: dict[str, frozenset[str]] = {
        "black1": settings.group_black1,
        "black2": settings.group_black2,
        "white1": settings.group_white1,
        "white2": settings.group_white2,
    }
    provider = settings.group_lists_provider
    if provider is None:
        return effective
    try:
        dynamic = provider()
    except Exception:  # noqa: BLE001 - 名单读取失败降级为静态配置。
        return effective
    if not isinstance(dynamic, dict):
        return effective
    for slot in GROUP_POLICY_SLOTS:
        value = dynamic.get(slot)
        if value is not None:
            effective[slot] = frozenset(
                str(item).strip() for item in value if str(item).strip()
            )
    return effective


def _has_supported_url(text: str, settings: PolicySettings) -> bool:
    """Return whether text contains a URL handled by the content parser registry.

    A checker may be injected for a deployment-specific parser set. The default
    uses the registered parser rules only; it never performs a network request.
    """
    checker = settings.supported_url_check
    if checker is not None:
        try:
            return bool(checker(text))
        except Exception:  # noqa: BLE001 - URL trigger failures stay silent.
            return False
    try:
        from plugins.bot_unified_runtime.sources.parsers import (
            build_content_parser_registry,
            build_source_input,
        )

        source_input = build_source_input(text)
        registry = build_content_parser_registry()["registry"]
        return bool(registry.match(source_input))
    except Exception:  # noqa: BLE001 - Parser setup must not open the group gate.
        return False


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

    # 私聊：有问必回（角色/风险拦截除外），不做群聊策略限制。
    if message.session_type is SessionType.GROUP:
        text = message.plain_text.strip()
        command_triggered = text.startswith(active_settings.group_command_prefix)
        extra_check = active_settings.extra_command_check
        if extra_check is not None and extra_check(text):
            command_triggered = True
        group_id = message.group_id or ""
        group_lists = _effective_group_lists(active_settings)

        def _denied(reason: str, tags: tuple[str, ...]) -> PolicyEvaluation:
            return PolicyEvaluation(
                request_id=message.request_id,
                allowed=False,
                reason=reason,
                risk_level=RiskLevel.LOW,
                cooldown_key=cooldown_key,
                privacy_level=PrivacyLevel.GROUP,
                actor_roles=actor_roles,
                audit_tags=["policy", *role_tags, *tags],
            )

        # 优先级：黑名单1 > 黑名单2 > 白名单2 > 白名单1；黑名单是硬否决。
        # 黑名单1：完全静默，只接收不发送。
        if group_id in group_lists["black1"]:
            return _denied("group_black1", ("group_black1",))

        # 黑名单2：只回“@它且带指令”的消息；不艾特的斜杠指令也不回。
        if group_id in group_lists["black2"] and not (message.mentions_bot and command_triggered):
                return _denied("group_black2", ("group_black2",))

        # 白名单2：只回“@它”或显式命令，普通消息不主动接话。
        if group_id in group_lists["white2"] and not (
            message.mentions_bot or command_triggered
        ):
            return _denied("group_white2_need_trigger", ("group_white2",))

        # 白名单1：有效触发包括指令、点名、自然语言提问/能力和已支持链接。
        # 无论历史自动接话配置为何，未触发的群消息都只观察不回复。
        white1_group = group_id in group_lists["white1"]
        natural_triggered = False
        supported_url_triggered = False
        if white1_group and not command_triggered and not message.mentions_bot:
            natural_check = active_settings.natural_chat_check
            if natural_check is not None:
                try:
                    natural_triggered = bool(natural_check(text))
                except Exception:  # noqa: BLE001 - 判定失败按未触发处理。
                    natural_triggered = False
            supported_url_triggered = _has_supported_url(text, active_settings)

        if (
            not command_triggered
            and not message.mentions_bot
            and not natural_triggered
            and not supported_url_triggered
        ):
            # 白名单1 的图片/表情包：独立回复概率（默认 1.0，发图即被识别回应）；
            # 与闲聊抽签分开，避免表情包多的群被 0.05 的闲聊概率淹没。
            if (
                white1_group
                and _message_has_image(message)
                and deterministic_group_reply_lottery(
                    f"vision:{message.session_id}:{message.message_id or message.request_id}",
                    active_settings.vision_reply_probability,
                )
            ):
                return PolicyEvaluation(
                    request_id=message.request_id,
                    allowed=True,
                    reason="vision_reply_selected",
                    risk_level=RiskLevel.LOW,
                    cooldown_key=cooldown_key,
                    privacy_level=PrivacyLevel.GROUP,
                    actor_roles=actor_roles,
                    audit_tags=["policy", *role_tags, "vision_reply:selected"],
                )
            if (
                white1_group
                and active_settings.group_auto_reply_enabled
                and deterministic_group_reply_lottery(
                    f"{message.session_id}:{message.message_id or message.request_id}",
                    active_settings.group_auto_reply_probability,
                )
            ):
                return PolicyEvaluation(
                    request_id=message.request_id,
                    allowed=True,
                    reason="proactive_reply_selected",
                    risk_level=RiskLevel.LOW,
                    cooldown_key=cooldown_key,
                    privacy_level=PrivacyLevel.GROUP,
                    actor_roles=actor_roles,
                    audit_tags=["policy", *role_tags, "proactive_reply:selected"],
                )
            return _denied("passive_group_message", ("group_observe_only",))

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

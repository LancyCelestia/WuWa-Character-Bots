"""bot.subscribe 命令能力。

文本前缀 ``/bot subscribe``。子命令：
- add <链接|platform:kind:id> [到本群|私聊我] [--digest]
- list / remove <id> / pause <id> / resume <id> / check <id> / status

权限：群内 list/到本群 add 与操作本群订阅要求管理员（角色 admin 或
``BOT_ADMIN_USER_IDS``）；私聊用户只能管理自己创建的私聊订阅。
"""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, cast

from plugins.bot_unified_runtime.contracts import CapabilityResult, IncomingMessage
from plugins.bot_unified_runtime.contracts.subscription import (
    SubscriptionDestination,
    SubscriptionSpec,
)
from plugins.bot_unified_runtime.sources.subscription_store import SubscriptionStore
from plugins.bot_unified_runtime.sources.subscriptions import (
    build_subscription_registry,
)

_SUBSCRIBE_RE = re.compile(
    r"^\s*(?:/bot\s+)?subscribe(?:\s+(?P<rest>.*))?$",
    re.IGNORECASE,
)

_USAGE = (
    "订阅用法：\n"
    "/bot subscribe add <链接|platform:kind:id> [到本群|私聊我] [--digest]\n"
    "/bot subscribe list\n"
    "/bot subscribe remove <id>\n"
    "/bot subscribe pause <id>\n"
    "/bot subscribe resume <id>\n"
    "/bot subscribe check <id>\n"
    "/bot subscribe status"
)


_SUBSCRIBE_EN_RE = re.compile(r"^\s*(?:[/!！]?subscribe)\s*(?P<rest>.*)$", re.IGNORECASE)
_SUBSCRIBE_ZH_RE = re.compile(r"^\s*(?:[/!！]?订阅)\s*(?P<rest>.*)$", re.IGNORECASE)
_SUBSCRIBE_ACTION_ZH = {
    "添加": "add",
    "新增": "add",
    "删除": "remove",
    "移除": "remove",
    "列表": "list",
    "暂停": "pause",
    "恢复": "resume",
    "继续": "resume",
    "检查": "check",
    "状态": "status",
}


def normalize_subscribe_text(text: str) -> str:
    """把 `/订阅 添加 ...`、`subscribe add ...` 统一成 `/bot subscribe add ...`。"""
    stripped = (text or "").strip()
    if not stripped:
        return stripped
    match = _SUBSCRIBE_ZH_RE.match(stripped) or _SUBSCRIBE_EN_RE.match(stripped) or _SUBSCRIBE_RE.match(stripped)
    if match is None:
        return stripped
    rest = (match.group("rest") or "").strip()
    parts = rest.split() if rest else []
    action = parts[0] if parts else ""
    normalized_action = _SUBSCRIBE_ACTION_ZH.get(action, action)
    tail = " ".join(parts[1:]) if parts else ""
    if normalized_action:
        rest = f"{normalized_action} {tail}".strip()
    return f"/bot subscribe {rest}".strip()


def is_subscribe_command(text: str) -> bool:
    stripped = (text or "").strip()
    return (
        _SUBSCRIBE_RE.match(stripped) is not None
        or _SUBSCRIBE_ZH_RE.match(stripped) is not None
        or _SUBSCRIBE_EN_RE.match(stripped) is not None
    )


def is_standalone_subscribe_command(text: str) -> bool:
    """只匹配 `/订阅 ...`、`!订阅 ...` 或裸 `subscribe ...`，不含 `/bot ...`。"""
    stripped = (text or "").strip()
    if stripped.lower().startswith("/bot"):
        return False
    return re.match(r"^(?:[/!！]?(?:订阅|subscribe))(?:\s+|$)", stripped, re.IGNORECASE) is not None


def build_subscribe_capability(
    store: Any | None = None,
    registry: Any | None = None,
    config: Any | None = None,
) -> Any:
    if store is None:
        store = SubscriptionStore()
    if registry is None:
        registry = build_subscription_registry()

    from plugins.bot_unified_runtime.sources.parsers import build_cookie_provider

    cookie_provider = build_cookie_provider(config)
    proxy = str(getattr(config, "bot_download_proxy", "") or "")

    def _ctx(platform: str = "") -> dict[str, str]:
        return {
            "cookie_header": cookie_provider.cookie_header(platform or ""),
            "proxy": proxy,
        }

    def _roles(message: IncomingMessage) -> list[str]:
        return [
            str(role).strip().lower()
            for role in getattr(message, "sender_roles", []) or []
            if str(role).strip()
        ]

    def _is_admin(message: IncomingMessage) -> bool:
        if "admin" in _roles(message):
            return True
        admin_ids = {str(value) for value in (getattr(config, "bot_admin_user_ids", []) or [])}
        return str(getattr(message, "sender_id", "")) in admin_ids

    def _result(
        message: IncomingMessage,
        body: str,
        audit_tags: list[str],
        title: str = "",
    ) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.subscribe",
            kind="text",
            title=title,
            body=body,
            audit_tags=audit_tags,
        )

    def _can_operate(message: IncomingMessage, spec: SubscriptionSpec) -> bool:
        group_id = getattr(message, "group_id", None)
        if group_id:
            return _is_admin(message) and any(
                destination.scope == "group"
                and destination.target_id == group_id
                for destination in spec.destinations
            )
        return str(spec.created_by) == str(getattr(message, "sender_id", ""))

    def _format_spec(spec: SubscriptionSpec) -> str:
        state = "启用" if spec.enabled else "暂停"
        mode = "日报" if spec.digest_enabled else "即时"
        return f"{spec.id} | {spec.platform} | {spec.target_name} | {state} | {mode}"

    def capability(
        message: IncomingMessage,
        decision: Any,
    ) -> CapabilityResult:
        text = normalize_subscribe_text(getattr(message, "plain_text", "") or "")
        match = _SUBSCRIBE_RE.match(text.strip())
        if match is None:
            return _result(message, _USAGE, ["subscribe_help"], "订阅")
        rest = (match.group("rest") or "").strip()
        if not rest:
            return _result(message, _USAGE, ["subscribe_help"], "订阅")

        parts = rest.split()
        action = parts[0].lower()
        args = parts[1:]
        tag = f"subscribe_{action}" if action in {
            "add", "list", "remove", "pause", "resume", "check", "status",
        } else "subscribe_help"

        if action == "add":
            digest_flag = "--digest" in args
            tokens = [token for token in args if token != "--digest"]
            want_group = "到本群" in tokens
            tokens = [
                token
                for token in tokens
                if token not in ("到本群", "私聊我")
            ]
            if len(tokens) != 1:
                return _result(message, _USAGE, [tag, "subscribe_bad_format"], "订阅")
            raw_target = tokens[0]
            try:
                resolved = registry.resolve_target(raw_target)
            except ValueError as exc:
                return _result(
                    message,
                    f"订阅目标解析失败：{exc}",
                    [tag, "subscribe_target_invalid"],
                    "订阅",
                )

            group_id = getattr(message, "group_id", None)
            if want_group:
                if not group_id:
                    return _result(
                        message,
                        "私聊消息无法订阅到群聊，请直接私聊订阅或在群里发送「到本群」。",
                        [tag, "subscribe_group_denied"],
                        "订阅",
                    )
                if not _is_admin(message):
                    return _result(
                        message,
                        "只有管理员才能把订阅推送到本群。",
                        [tag, "subscribe_group_denied"],
                        "订阅",
                    )
                destination = SubscriptionDestination(
                    scope="group", target_id=str(group_id)
                )
                destination_label = f"群 {group_id}"
            else:
                destination = SubscriptionDestination(
                    scope="private", target_id=str(message.sender_id)
                )
                destination_label = f"私聊 {message.sender_id}"

            spec_id = (
                f"{resolved['platform']}:{resolved['target_kind']}:"
                f"{resolved['target_id']}"
            )
            existing = store.get_spec(spec_id)
            destinations = (
                [*existing.destinations] if existing is not None else []
            )
            if destination not in destinations:
                destinations.append(destination)
            spec = SubscriptionSpec(
                id=spec_id,
                platform=resolved["platform"],
                target_kind=resolved["target_kind"],
                target_id=resolved["target_id"],
                target_name=resolved["target_name"],
                destinations=destinations,
                send_policy="instant",
                digest_enabled=(
                    (existing.digest_enabled if existing is not None else False)
                    or digest_flag
                ),
                enabled=(existing.enabled if existing is not None else True),
                health_state=(
                    existing.health_state if existing is not None else "healthy"
                ),
                failure_count=(
                    existing.failure_count if existing is not None else 0
                ),
                backoff_until=(
                    existing.backoff_until if existing is not None else None
                ),
                created_by=(
                    existing.created_by if existing is not None else str(message.sender_id)
                ),
                created_at=(
                    existing.created_at
                    if existing is not None
                    else datetime.now(timezone.utc).isoformat()
                ),
            )
            store.upsert_spec(spec)
            digest_note = "（日报汇总）" if spec.digest_enabled else "（即时推送）"
            return _result(
                message,
                (
                    f"订阅已添加：{spec_id}（{spec.target_name}）\n"
                    f"推送方式：{destination_label}{digest_note}"
                ),
                [tag],
                "订阅",
            )

        if action == "list":
            specs = store.list_specs()
            group_id = getattr(message, "group_id", None)
            if group_id:
                if not _is_admin(message):
                    return _result(
                        message,
                        "只有管理员才能查看本群订阅。",
                        [tag, "subscribe_group_denied"],
                        "订阅",
                    )
                filtered = [
                    spec
                    for spec in specs
                    if any(
                        destination.scope == "group"
                        and destination.target_id == group_id
                        for destination in spec.destinations
                    )
                ]
            else:
                filtered = [
                    spec
                    for spec in specs
                    if any(
                        destination.scope == "private"
                        and destination.target_id == str(message.sender_id)
                        for destination in spec.destinations
                    )
                ]
            if not filtered:
                return _result(
                    message,
                    "还没有订阅。发送「/bot subscribe add <链接>」添加。",
                    [tag],
                    "订阅",
                )
            return _result(
                message,
                "当前订阅：\n" + "\n".join(_format_spec(spec) for spec in filtered),
                [tag],
                "订阅",
            )

        if action in {"remove", "pause", "resume"}:
            if len(args) != 1:
                return _result(message, _USAGE, [tag, "subscribe_bad_format"], "订阅")
            spec_id = args[0]
            spec = cast(SubscriptionSpec, store.get_spec(spec_id))
            if spec is None:
                return _result(
                    message,
                    f"订阅不存在：{spec_id}",
                    [tag, "subscribe_not_found"],
                    "订阅",
                )
            if not _can_operate(message, spec):
                return _result(
                    message,
                    "没有权限操作该订阅。",
                    [tag, "subscribe_denied"],
                    "订阅",
                )
            if action == "remove":
                store.delete_spec(spec_id)
                return _result(
                    message,
                    f"已删除订阅：{spec_id}",
                    [tag],
                    "订阅",
                )
            store.set_spec_enabled(spec_id, action == "resume")
            verb = "恢复" if action == "resume" else "暂停"
            return _result(
                message,
                f"已{verb}订阅：{spec_id}",
                [tag],
                "订阅",
            )

        if action == "check":
            if len(args) != 1:
                return _result(message, _USAGE, [tag, "subscribe_bad_format"], "订阅")
            spec_id = args[0]
            spec = cast(SubscriptionSpec, store.get_spec(spec_id))
            if spec is None:
                return _result(
                    message,
                    f"订阅不存在：{spec_id}",
                    [tag, "subscribe_not_found"],
                    "订阅",
                )
            adapter = registry.find(spec.platform)
            if adapter is None:
                return _result(
                    message,
                    f"平台 {spec.platform} 的订阅 adapter 不可用。",
                    [tag, "subscribe_adapter_missing"],
                    "订阅",
                )
            cursor = store.get_cursor(spec_id)
            try:
                result = asyncio.run(
                    adapter.fetch_latest(spec, cursor, _ctx(spec.platform))
                )
            except Exception as exc:  # noqa: BLE001 - 用户需要失败原因。
                return _result(
                    message,
                    f"检查失败：{exc}",
                    [tag, "subscribe_check_failed"],
                    "订阅",
                )
            if result.error and not result.items:
                return _result(
                    message,
                    f"检查失败：{result.error}",
                    [tag, "subscribe_check_failed"],
                    "订阅",
                )
            new_items = [
                item
                for item in result.items
                if not store.already_pushed(spec_id, item.item_id, item.kind)
            ]
            if not new_items:
                return _result(
                    message,
                    f"订阅 {spec_id} 检查完成：无新增。",
                    [tag],
                    "订阅",
                )
            preview = "\n".join(
                f"- 《{item.title}》 {item.url}" for item in new_items[:5]
            )
            return _result(
                message,
                f"订阅 {spec_id} 检查完成：新增 {len(new_items)} 条。\n{preview}",
                [tag],
                "订阅",
            )

        if action == "status":
            specs = store.list_specs()
            counters = Counter(spec.platform for spec in specs)
            lines = [f"订阅总数：{len(specs)}"]
            lines.extend(
                f"{platform}：{count}"
                for platform, count in sorted(counters.items())
            )
            return _result(message, "\n".join(lines), [tag], "订阅")

        return _result(message, _USAGE, [tag], "订阅")

    return capability


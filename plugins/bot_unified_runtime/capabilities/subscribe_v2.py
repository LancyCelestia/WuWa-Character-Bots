"""V2 subscription command backend.

The command surface is intentionally small; all persistence is delegated to
SubscriptionStoreV2 and target parsing to the V2 adapters.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SubscriptionDestinationV2,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.subscription_store_v2 import (
    SubscriptionStoreV2,
)


def _normalize(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("/bot "):
        stripped = stripped[5:].strip()
    if stripped.startswith("/订阅"):
        return "subscribe" + stripped[3:]
    if stripped.startswith("订阅"):
        return "subscribe" + stripped[2:]
    return stripped


def build_subscribe_capability_v2(
    *, store: SubscriptionStoreV2, adapters: list[Any], config: Any
) -> Any:
    def result(message: IncomingMessage, body: str, tags: list[str]) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.subscribe",
            kind="text",
            title="订阅",
            body=body,
            audit_tags=tags,
        )

    def _roles(message: IncomingMessage) -> list[str]:
        return [
            str(role).strip().lower()
            for role in getattr(message, "sender_roles", []) or []
            if str(role).strip()
        ]

    def _is_admin(message: IncomingMessage) -> bool:
        # 管理员判定沿用 v1 同源机制（audit P1#2）：admin 角色 + BOT_ADMIN_USER_IDS。
        if "admin" in _roles(message):
            return True
        admin_ids = {
            str(value) for value in (getattr(config, "bot_admin_user_ids", []) or [])
        }
        return str(getattr(message, "sender_id", "")) in admin_ids

    def _session_scope(message: IncomingMessage) -> str:
        return str(getattr(getattr(message, "session_type", None), "value", "private"))

    def _own_destinations(message: IncomingMessage, target_id: str) -> list[Any]:
        """当前会话在这条订阅下的目的地（私聊=自己；群=本群）。"""
        destinations = store.list_destinations(target_id)
        scope = _session_scope(message)
        if scope == "group":
            group_id = str(getattr(message, "group_id", "") or "")
            return [
                destination
                for destination in destinations
                if destination.scope == "group" and destination.destination_id == group_id
            ]
        sender_id = str(getattr(message, "sender_id", ""))
        return [
            destination
            for destination in destinations
            if destination.scope == "private" and destination.destination_id == sender_id
        ]

    def _can_operate(message: IncomingMessage, target_id: str) -> bool:
        """移植 v1 的创建者/目的地归属校验（审计 P1#2）。

        群内：管理员且该订阅确实推往本群；私聊：只允许操作推给自己的订阅。
        """
        if _session_scope(message) == "group":
            return _is_admin(message) and bool(
                _own_destinations(message, target_id)
            )
        return bool(_own_destinations(message, target_id))

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        parts = _normalize(message.plain_text).split()
        if not parts or parts[0].lower() != "subscribe":
            return result(message, "用法：订阅 add <公开目标> / 订阅 list", ["subscribe_help"])
        action = parts[1].lower() if len(parts) > 1 else "help"
        if action == "add":
            if len(parts) < 3:
                return result(message, "用法：订阅 add <公开目标>", ["subscribe_bad_format"])
            raw_target = parts[2]
            target: SubscriptionTarget | None = None
            last_error: Exception | None = None
            runtime_error: Exception | None = None
            for adapter in adapters:
                try:
                    target = asyncio.run(
                        adapter.resolve_target(raw_target, {"config": config})
                    )
                    break
                except (ValueError, TypeError) as exc:
                    last_error = exc
                except RuntimeError as exc:
                    # 审计 P3#26：事件循环类错误与普通解析失败分开呈现，
                    # 不再统一吞进「解析失败：None」。
                    runtime_error = exc
            if target is None:
                if runtime_error is not None:
                    return result(
                        message,
                        f"订阅解析器运行异常（可能处于运行中的事件循环）：{runtime_error}",
                        ["subscribe_target_invalid"],
                    )
                if last_error is not None:
                    return result(
                        message,
                        f"订阅目标解析失败：{last_error}",
                        ["subscribe_target_invalid"],
                    )
                return result(
                    message,
                    f"无法识别订阅平台或链接格式：{raw_target}",
                    ["subscribe_target_invalid"],
                )
            existing = store.get_target(target.id)
            if existing is not None:
                # 审计 P1#2：重加不改 enabled——管理员暂停的订阅不会被静默重启。
                target = existing.model_copy(
                    update={"updated_at": datetime.now(timezone.utc)}
                )
            store.upsert_target(target)
            transport = str(getattr(message, "adapter", "onebot.v11") or "onebot.v11")
            scope = _session_scope(message)
            store.add_destination(
                SubscriptionDestinationV2(
                    id="",
                    target_id=target.id,
                    transport=transport,
                    scope=scope,
                    destination_id=str(message.group_id or message.sender_id),
                    bot_id=str(message.bot_id or ""),
                )
            )
            return result(message, f"订阅已添加：{target.id}", ["subscribe_add"])

        target_id = parts[2] if len(parts) > 2 else ""
        if action == "list":
            # 审计 P1#2：list 不再向所有人泄露全部订阅——
            # 私聊只列推给自己的订阅；群内仅管理员可查看本群订阅。
            if _session_scope(message) == "group" and not _is_admin(message):
                return result(
                    message,
                    "只有管理员才能查看本群订阅。",
                    ["subscribe_list_denied"],
                )
            targets = [
                target
                for target in store.list_targets()
                if _own_destinations(message, target.id)
            ]
            body = "当前订阅：\n" + "\n".join(
                f"{target.id} | {target.platform} | {target.display_name} | "
                f"{'启用' if target.enabled else '暂停'}"
                for target in targets
            ) if targets else "当前没有订阅。"
            return result(message, body, ["subscribe_list"])
        if action in {"pause", "resume", "remove"}:
            target = store.get_target(target_id)
            if target is None:
                return result(message, f"订阅不存在：{target_id}", ["subscribe_not_found"])
            if not _can_operate(message, target_id):
                return result(
                    message,
                    "没有权限操作该订阅。",
                    [f"subscribe_{action}_denied"],
                )
            if action == "remove":
                store.delete_target(target_id)
                body = f"已删除订阅：{target_id}"
            else:
                enabled = action == "resume"
                store.set_target_enabled(target_id, enabled)
                body = f"已{'恢复' if enabled else '暂停'}订阅：{target_id}"
            return result(message, body, [f"subscribe_{action}"])
        return result(message, "用法：订阅 add <公开目标> / 订阅 list / 订阅 pause|resume|remove <id>", ["subscribe_help"])

    return capability

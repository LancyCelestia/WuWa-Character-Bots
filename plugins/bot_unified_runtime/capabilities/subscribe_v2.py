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
            for adapter in adapters:
                try:
                    target = asyncio.run(
                        adapter.resolve_target(raw_target, {"config": config})
                    )
                    break
                except (ValueError, RuntimeError, TypeError) as exc:
                    last_error = exc
            if target is None:
                return result(
                    message,
                    f"订阅目标解析失败：{last_error or '无法识别订阅平台'}",
                    ["subscribe_target_invalid"],
                )
            existing = store.get_target(target.id)
            if existing is not None:
                target = existing.model_copy(
                    update={"enabled": True, "updated_at": datetime.now(timezone.utc)}
                )
            store.upsert_target(target)
            transport = str(getattr(message, "adapter", "onebot.v11") or "onebot.v11")
            scope = str(getattr(getattr(message, "session_type", None), "value", "private"))
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
            targets = store.list_targets()
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

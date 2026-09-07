"""Unified outbound delivery gateway for all adapter transports."""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from plugins.bot_unified_runtime.contracts import DeliveryReceipt, SendRequest


class UnifiedDeliveryGateway:
    def __init__(
        self,
        *,
        onebot_sender: Callable[[Any, SendRequest], Awaitable[DeliveryReceipt]],
        nonebot_sender: Callable[[Any, Any, SendRequest], Awaitable[DeliveryReceipt]],
        record_receipt: Callable[[DeliveryReceipt, SendRequest], Any],
    ) -> None:
        self.onebot_sender = onebot_sender
        self.nonebot_sender = nonebot_sender
        self.record_receipt = record_receipt

    @staticmethod
    def _adapter_name(bot: Any) -> str:
        adapter = getattr(bot, "adapter", None)
        getter = getattr(adapter, "get_name", None)
        value = getter() if callable(getter) else getattr(adapter, "name", "")
        return str(value or "").strip().lower()

    async def deliver(
        self,
        bot: Any,
        event: Any,
        send_request: SendRequest,
    ) -> DeliveryReceipt:
        adapter_name = self._adapter_name(bot)
        if not adapter_name or adapter_name in {"onebot", "onebot v11"}:
            receipt = await self.onebot_sender(bot, send_request)
        else:
            receipt = await self.nonebot_sender(bot, event, send_request)
        recorded = self.record_receipt(receipt, send_request)
        if inspect.isawaitable(recorded):
            return await recorded
        return recorded
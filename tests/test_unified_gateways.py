from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import DeliveryReceipt, ReceiptState
from plugins.bot_unified_runtime.runtime.ingress import IngressGateway
from plugins.bot_unified_runtime.sender.gateway import UnifiedDeliveryGateway


def _request():
    return SimpleNamespace(request_id="req-1", adapter="onebot", bot_id="bot-1")


def test_ingress_gateway_normalizes_event_through_one_boundary():
    calls = []

    def normalizer(event, *, bot_id):
        calls.append((event, bot_id))
        return {"request_id": "req-1", "plain_text": "hello"}

    gateway = IngressGateway(normalizer)
    result = gateway.from_event("event", bot_id="bot-1")

    assert result["plain_text"] == "hello"
    assert calls == [("event", "bot-1")]


@pytest.mark.asyncio
async def test_unified_delivery_gateway_routes_onebot_and_records_receipt():
    calls = []

    async def onebot_sender(bot, request):
        calls.append(("onebot", bot, request.request_id))
        return DeliveryReceipt(
            request_id=request.request_id,
            state=ReceiptState.SENT,
            transport="onebot.v11",
            public_message="sent",
        )

    async def nonebot_sender(bot, event, request):
        calls.append(("nonebot", bot, event, request.request_id))
        return DeliveryReceipt(
            request_id=request.request_id,
            state=ReceiptState.SENT,
            transport="nonebot",
            public_message="sent",
        )

    recorded = []

    async def record(receipt, request):
        recorded.append((receipt.state.value, request.request_id))
        return receipt

    gateway = UnifiedDeliveryGateway(
        onebot_sender=onebot_sender,
        nonebot_sender=nonebot_sender,
        record_receipt=record,
    )
    bot = SimpleNamespace(adapter=SimpleNamespace(get_name=lambda: "OneBot V11"))

    receipt = await gateway.deliver(bot, "event", _request())

    assert receipt.state is ReceiptState.SENT
    assert calls == [("onebot", bot, "req-1")]
    assert recorded == [("sent", "req-1")]
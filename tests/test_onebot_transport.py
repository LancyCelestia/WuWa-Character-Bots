from __future__ import annotations

import asyncio
import json
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.sender.onebot import (
    build_onebot_message_segments,
    send_onebot_v11,
)


def _send_request(
    *,
    target_scope: SessionType = SessionType.PRIVATE,
    target_id: str = "42",
    text: str = "你好，漂泊者。",
    content_type: str = "text",
    content_ref: dict[str, Any] | None = None,
    allow_forward: bool = False,
) -> SendRequest:
    rendered = RenderedOutput(
        request_id="req_test",
        content_type=content_type,
        content_ref=content_ref or {"text": text},
        text_fallback=text,
    )
    return SendRequest(
        request_id="req_test",
        session_id=f"{target_scope.value}_{target_id}",
        target_scope=target_scope,
        target_id=target_id,
        origin_message_id="origin_1",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=f"bot.chat:{target_id}:{text}",
        cooldown_key=f"bot.chat:{target_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_forward=allow_forward,
        persona_profile_id="shorekeeper",
    )


class FakePrivateBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def send_private_msg(self, **kwargs: Any) -> dict[str, int]:
        self.calls.append(("send_private_msg", kwargs))
        return {"message_id": 123}

    async def send_group_msg(self, **kwargs: Any) -> dict[str, int]:
        raise AssertionError("group API should not be called")


class FakeGroupBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def send_group_msg(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("send_group_msg", kwargs))
        return {"message_id": "group-msg-9"}

    async def send_private_msg(self, **kwargs: Any) -> dict[str, str]:
        raise AssertionError("private API should not be called")


class FakeForwardBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def send_group_forward_msg(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("send_group_forward_msg", kwargs))
        return {"status": "ok", "retcode": 0, "data": {"message_id": "forward-1"}}

    async def send_private_forward_msg(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("send_private_forward_msg", kwargs))
        return {"message_id": "forward-2"}

    async def send_group_msg(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("fallback group message API should not be called")

    async def send_private_msg(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("fallback private message API should not be called")


class FakeCallApiForwardBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_api(self, api: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((api, kwargs))
        return {"status": "ok", "retcode": 0, "message_id": "forward-call-api"}

    async def send_group_msg(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("fallback group message API should not be called")

    async def send_private_msg(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("fallback private message API should not be called")


class ExplodingBot:
    async def send_private_msg(self, **kwargs: Any) -> dict[str, int]:
        raise RuntimeError("send failed token=super-secret")

    async def send_group_msg(self, **kwargs: Any) -> dict[str, int]:
        raise AssertionError("group API should not be called")


class RetcodeBot:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    async def send_private_msg(self, **kwargs: Any) -> dict[str, Any]:
        return self.response

    async def send_group_msg(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("group API should not be called")


def test_onebot_text_segments_from_send_request() -> None:
    send_request = _send_request(text="潮声还在。")

    segments = build_onebot_message_segments(send_request)

    assert segments == [{"type": "text", "data": {"text": "潮声还在。"}}]


def test_onebot_image_segment_from_rendered_image_output() -> None:
    send_request = _send_request(
        text="图片发送失败时显示这段文字。",
        content_type="image",
        content_ref={"file": "file:///tmp/shorekeeper-card.png"},
    )

    segments = build_onebot_message_segments(send_request)

    assert segments == [
        {
            "type": "image",
            "data": {"file": "file:///tmp/shorekeeper-card.png"},
        }
    ]


def test_onebot_card_segment_from_rendered_json_card_output() -> None:
    send_request = _send_request(
        text="卡片发送失败时显示这段文字。",
        content_type="card",
        content_ref={
            "onebot_json": {
                "app": "com.tencent.structmsg",
                "desc": "守岸人",
                "meta": {"news": {"title": "潮声"}},
            }
        },
    )

    segments = build_onebot_message_segments(send_request)

    assert segments[0]["type"] == "json"
    payload = json.loads(segments[0]["data"]["data"])
    assert payload["app"] == "com.tencent.structmsg"
    assert payload["meta"]["news"]["title"] == "潮声"


def test_onebot_mixed_segments_keep_order_and_skip_invalid_parts() -> None:
    send_request = _send_request(
        text="混合消息发送失败时显示这段文字。",
        content_type="mixed",
        content_ref={
            "parts": [
                {"type": "text", "text": "先看这一段。"},
                {"type": "image", "file": "https://example.invalid/card.png"},
                {"type": "card", "onebot_json": {"app": "demo", "desc": "card"}},
                {"type": "image"},
            ]
        },
    )

    segments = build_onebot_message_segments(send_request)

    assert segments[0] == {"type": "text", "data": {"text": "先看这一段。"}}
    assert segments[1] == {
        "type": "image",
        "data": {"file": "https://example.invalid/card.png"},
    }
    assert segments[2]["type"] == "json"
    assert json.loads(segments[2]["data"]["data"]) == {"app": "demo", "desc": "card"}
    assert len(segments) == 3


def test_onebot_segments_fallback_to_text_for_unsupported_output() -> None:
    send_request = _send_request(
        text="这是安全降级文本。",
        content_type="forward",
        content_ref={"nodes": [{"name": "守岸人", "content": "还没接 forward API"}]},
    )

    segments = build_onebot_message_segments(send_request)

    assert segments == [{"type": "text", "data": {"text": "这是安全降级文本。"}}]


def test_onebot_transport_sends_private_msg_and_maps_message_id() -> None:
    bot = FakePrivateBot()
    send_request = _send_request(target_scope=SessionType.PRIVATE, target_id="42")

    receipt = asyncio.run(send_onebot_v11(bot, send_request))

    assert receipt.state is ReceiptState.SENT
    assert receipt.transport == "onebot.v11"
    assert receipt.provider_message_id == "123"
    assert bot.calls == [
        (
            "send_private_msg",
            {
                "user_id": 42,
                "message": [{"type": "text", "data": {"text": "你好，漂泊者。"}}],
            },
        )
    ]


def test_onebot_transport_sends_group_msg_and_maps_message_id() -> None:
    bot = FakeGroupBot()
    send_request = _send_request(target_scope=SessionType.GROUP, target_id="10001")

    receipt = asyncio.run(send_onebot_v11(bot, send_request))

    assert receipt.state is ReceiptState.SENT
    assert receipt.transport == "onebot.v11"
    assert receipt.provider_message_id == "group-msg-9"
    assert bot.calls == [
        (
            "send_group_msg",
            {
                "group_id": 10001,
                "message": [{"type": "text", "data": {"text": "你好，漂泊者。"}}],
            },
        )
    ]


def test_onebot_transport_uses_group_forward_api_when_allowed() -> None:
    bot = FakeForwardBot()
    messages = [
        {
            "type": "node",
            "data": {
                "name": "守岸人",
                "uin": "10000",
                "content": [{"type": "text", "data": {"text": "第一段"}}],
            },
        }
    ]
    send_request = _send_request(
        target_scope=SessionType.GROUP,
        target_id="10001",
        text="合并转发不可用时的降级文本。",
        content_type="forward",
        content_ref={"messages": messages},
        allow_forward=True,
    )

    receipt = asyncio.run(send_onebot_v11(bot, send_request))

    assert receipt.state is ReceiptState.SENT
    assert receipt.provider_message_id == "forward-1"
    assert bot.calls == [
        (
            "send_group_forward_msg",
            {"group_id": 10001, "messages": messages},
        )
    ]


def test_onebot_transport_uses_private_forward_api_when_allowed() -> None:
    bot = FakeForwardBot()
    messages = [
        {
            "type": "node",
            "data": {
                "name": "守岸人",
                "uin": "10000",
                "content": "私聊合并转发正文",
            },
        }
    ]
    send_request = _send_request(
        target_scope=SessionType.PRIVATE,
        target_id="42",
        text="合并转发不可用时的降级文本。",
        content_type="forward",
        content_ref={"nodes": messages},
        allow_forward=True,
    )

    receipt = asyncio.run(send_onebot_v11(bot, send_request))

    assert receipt.state is ReceiptState.SENT
    assert receipt.provider_message_id == "forward-2"
    assert bot.calls == [
        (
            "send_private_forward_msg",
            {"user_id": 42, "messages": messages},
        )
    ]


def test_onebot_transport_uses_call_api_for_forward_extension_when_needed() -> None:
    bot = FakeCallApiForwardBot()
    messages = [{"type": "node", "data": {"name": "守岸人", "uin": "10000", "content": "摘要"}}]
    send_request = _send_request(
        target_scope=SessionType.GROUP,
        target_id="10001",
        text="合并转发不可用时的降级文本。",
        content_type="forward",
        content_ref={"messages": messages},
        allow_forward=True,
    )

    receipt = asyncio.run(send_onebot_v11(bot, send_request))

    assert receipt.state is ReceiptState.SENT
    assert receipt.provider_message_id == "forward-call-api"
    assert bot.calls == [
        (
            "send_group_forward_msg",
            {"group_id": 10001, "messages": messages},
        )
    ]


def test_onebot_transport_falls_back_when_forward_not_allowed() -> None:
    bot = FakeGroupBot()
    messages = [{"type": "node", "data": {"name": "守岸人", "uin": "10000", "content": "摘要"}}]
    send_request = _send_request(
        target_scope=SessionType.GROUP,
        target_id="10001",
        text="合并转发不可用时的降级文本。",
        content_type="forward",
        content_ref={"messages": messages},
        allow_forward=False,
    )

    receipt = asyncio.run(send_onebot_v11(bot, send_request))

    assert receipt.state is ReceiptState.SENT
    assert receipt.provider_message_id == "group-msg-9"
    assert bot.calls == [
        (
            "send_group_msg",
            {
                "group_id": 10001,
                "message": [
                    {"type": "text", "data": {"text": "合并转发不可用时的降级文本。"}}
                ],
            },
        )
    ]


def test_onebot_transport_maps_exceptions_to_retryable_failure() -> None:
    bot = ExplodingBot()
    send_request = _send_request(target_scope=SessionType.PRIVATE, target_id="42")

    receipt = asyncio.run(send_onebot_v11(bot, send_request))

    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert receipt.transport == "onebot.v11"
    assert "debug_id=" in receipt.public_message
    assert "super-secret" not in receipt.public_message


def test_onebot_transport_accepts_ok_status_with_nested_message_id() -> None:
    bot = RetcodeBot({"status": "ok", "retcode": 0, "data": {"message_id": 456}})
    send_request = _send_request(target_scope=SessionType.PRIVATE, target_id="42")

    receipt = asyncio.run(send_onebot_v11(bot, send_request))

    assert receipt.state is ReceiptState.SENT
    assert receipt.provider_message_id == "456"
    assert receipt.public_message == "sent"


def test_onebot_transport_maps_transient_retcode_to_retryable_failure() -> None:
    bot = RetcodeBot(
        {
            "status": "failed",
            "retcode": 100,
            "message": "network timeout token=super-secret",
        }
    )
    send_request = _send_request(target_scope=SessionType.PRIVATE, target_id="42")

    receipt = asyncio.run(send_onebot_v11(bot, send_request))

    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert receipt.transport == "onebot.v11"
    assert "debug_id=" in receipt.public_message
    assert "retcode=100" in receipt.public_message
    assert "super-secret" not in receipt.public_message
    assert receipt.provider_message_id is None


def test_onebot_transport_maps_permission_retcode_to_final_failure() -> None:
    bot = RetcodeBot(
        {
            "status": "failed",
            "retcode": 1403,
            "wording": "permission denied cookie=super-secret",
        }
    )
    send_request = _send_request(target_scope=SessionType.PRIVATE, target_id="42")

    receipt = asyncio.run(send_onebot_v11(bot, send_request))

    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.transport == "onebot.v11"
    assert "debug_id=" in receipt.public_message
    assert "retcode=1403" in receipt.public_message
    assert "super-secret" not in receipt.public_message
    assert receipt.provider_message_id is None


def test_onebot_transport_blocks_unsupported_target_scope() -> None:
    bot = FakePrivateBot()
    send_request = _send_request(target_scope=SessionType.EMAIL, target_id="a@example.com")

    receipt = asyncio.run(send_onebot_v11(bot, send_request))

    assert receipt.state is ReceiptState.BLOCKED
    assert receipt.transport == "onebot.v11"
    assert bot.calls == []

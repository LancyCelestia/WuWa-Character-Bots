import asyncio
import json
import threading
import time

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.sources.gscore_bridge import (
    DisabledGsCoreBridge,
    build_gscore_bridge,
    build_message_receive,
    build_message_send,
    gscore_readiness,
    roles_to_user_pm,
)


def test_build_message_receive_payload():
    payload = build_message_receive(
        bot_id="NoneBot2",
        bot_self_id="3958874605",
        msg_id="m123",
        user_type="group",
        group_id="10001",
        user_id="42",
        user_pm=6,
        content=[{"type": "text", "data": "你好"}],
        sender={"nickname": "季落"},
    )

    assert payload["bot_id"] == "NoneBot2"
    assert payload["group_id"] == "10001"
    assert payload["user_pm"] == 6
    assert payload["content"][0]["type"] == "text"
    assert payload["sender"]["nickname"] == "季落"
    assert "msg_id" in payload


def test_build_message_send_payload_with_echo():
    payload = build_message_send(
        target_type="direct",
        target_id="42",
        content=[{"type": "text", "data": "回复"}],
        echo="req_1",
    )

    assert payload["target_type"] == "direct"
    assert payload["target_id"] == "42"
    assert payload["echo"] == "req_1"
    assert payload["content"][0]["data"] == "回复"


def test_roles_to_user_pm_mapping():
    assert roles_to_user_pm(["admin", "user"]) == 1
    assert roles_to_user_pm(["trusted", "user"], user_type="group") == 3
    assert roles_to_user_pm(["user"], user_type="group") == 6
    assert roles_to_user_pm(["user"], user_type="direct") == 6


def test_bridge_disabled_by_default():
    bridge = build_gscore_bridge(Config())

    assert isinstance(bridge, DisabledGsCoreBridge)
    assert bridge.is_connected() is False
    assert bridge.report_message({}) is False
    assert bridge.send_message({}) is False


def test_gscore_readiness_defaults():
    readiness = gscore_readiness(Config())

    assert readiness["enabled"] is False
    assert readiness["status"] == "disabled"
    assert readiness["host"] == ""
    assert readiness["ws_token_set"] is False


def test_gscore_readiness_enabled_shape():
    config = Config(
        bot_gscore_enabled=True,
        bot_gscore_host="127.0.0.1",
        bot_gscore_port=8765,
        bot_gscore_ws_token="secret-token",
        bot_gscore_bot_id="NoneBot2",
    )

    readiness = gscore_readiness(config)
    assert readiness["enabled"] is True
    assert readiness["host"] == "127.0.0.1"
    assert readiness["port"] == 8765
    assert readiness["ws_token_set"] is True
    # 不暴露 token 原文。
    assert "secret-token" not in str(readiness)


def test_bridge_live_round_trip_against_mock_gscore_server():
    """真·适配往返：本地起一个早柚协议的 mock WS 服务端。

    桥接发送 MessageReceive 上报 → 服务端回 MessageSend → on_message 回调收到。
    """
    websockets = pytest.importorskip("websockets")
    from websockets.asyncio import server as ws_server

    received: list[dict] = []
    replies_sent: list[dict] = []
    got_callback: list[dict] = []
    server_holder: list = []

    async def handler(connection) -> None:
        # 早柚协议：ws://HOST:PORT/{BOT_ID}?token={WS_TOKEN}
        assert connection.request.path == "/NoneBot2?token=test-token"
        async for raw in connection:
            payload = json.loads(raw)
            received.append(payload)
            reply = build_message_send(
                target_type="group",
                target_id="10001",
                content=[{"type": "text", "data": "gsuid 收到"}],
                echo=payload.get("echo", ""),
            )
            replies_sent.append(reply)
            await connection.send(json.dumps(reply, ensure_ascii=False))

    def run_server() -> None:
        async def start() -> None:
            async with ws_server.serve(handler, "127.0.0.1", 0) as server:
                server_holder.append(server)
                port = server.sockets[0].getsockname()[1]
                server_holder.append(port)
                await asyncio.Future()  # 永不返回，直到测试结束

        asyncio.run(start())

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while len(server_holder) < 2 and time.time() < deadline:
        time.sleep(0.05)
    assert len(server_holder) == 2, "mock GsCore server failed to start"
    port = server_holder[1]

    config = Config(
        bot_gscore_enabled=True,
        bot_gscore_host="127.0.0.1",
        bot_gscore_port=port,
        bot_gscore_ws_token="test-token",
        bot_gscore_max_retry=2,
        bot_gscore_bot_id="NoneBot2",
    )
    bridge = build_gscore_bridge(config, on_message=lambda payload: got_callback.append(payload))
    bridge.start()

    payload = build_message_receive(
        bot_id="NoneBot2",
        bot_self_id="3958874605",
        msg_id="m-live-1",
        user_type="group",
        group_id="10001",
        user_id="42",
        user_pm=6,
        content=[{"type": "text", "data": "你好"}],
        sender={"nickname": "季落"},
    )
    assert bridge.report_message(payload) is True

    deadline = time.time() + 10
    while not got_callback and time.time() < deadline:
        time.sleep(0.05)
    bridge.stop()

    assert len(received) == 1
    assert received[0]["msg_id"] == "m-live-1"
    assert received[0]["content"][0]["data"] == "你好"
    assert len(replies_sent) == 1
    assert len(got_callback) == 1
    assert got_callback[0]["target_type"] == "group"
    assert got_callback[0]["content"][0]["data"] == "gsuid 收到"

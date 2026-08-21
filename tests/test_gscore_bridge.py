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

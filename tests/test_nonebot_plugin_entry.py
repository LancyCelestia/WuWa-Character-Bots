import importlib


def test_nonebot_plugin_imports_and_has_metadata():
    module = importlib.import_module("plugins.wuwa_unified_runtime")
    meta = module.__plugin_meta__

    assert meta.name == "WuWa Unified Runtime"
    assert "~onebot.v11" in meta.supported_adapters


def test_status_capability_returns_structured_result():
    from plugins.wuwa_unified_runtime.capabilities.echo import build_status_result, route_wuwa_command

    result = build_status_result(request_id="req_test")

    assert result.capability_id == "wuwa.status"
    assert result.body == "统一运行时在线"
    assert route_wuwa_command("status").body == "统一运行时在线"


def test_wuwa_command_rejects_unknown_subcommand():
    from plugins.wuwa_unified_runtime.capabilities.echo import route_wuwa_command

    result = route_wuwa_command("anything")

    assert result.capability_id == "wuwa.help"
    assert "用法" in result.body


def test_auto_send_command_returns_preview_only_text():
    from plugins.wuwa_unified_runtime.capabilities.auto_send import (
        build_auto_send_preview_text,
        is_auto_send_command_text,
    )

    command = "报存 给 A、B 发邮件，主题：周末安排，内容根据你对他们的了解分别写"
    preview = build_auto_send_preview_text(
        command,
        actor_sender_id="42",
        actor_session_id="private:42",
    )

    assert is_auto_send_command_text(command) is True
    assert is_auto_send_command_text("/报存 给 A 发消息，内容测试") is False
    assert "草稿预览" in preview
    assert "A、B" in preview
    assert "确认发送" not in preview


def test_plugin_entry_uses_strict_command_and_plain_autosend_rule():
    import inspect
    import plugins.wuwa_unified_runtime as plugin_entry

    source = inspect.getsource(plugin_entry)

    assert "force_whitespace=True" in source
    assert "on_message" in source

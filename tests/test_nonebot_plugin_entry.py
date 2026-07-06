import importlib


def test_nonebot_plugin_imports_and_has_metadata():
    module = importlib.import_module("plugins.wuwa_unified_runtime")
    meta = module.__plugin_meta__

    assert meta.name == "WuWa Unified Runtime"
    assert "~onebot.v11" in meta.supported_adapters


def test_status_capability_returns_structured_result():
    from plugins.wuwa_unified_runtime.capabilities.echo import build_status_result

    result = build_status_result(request_id="req_test")

    assert result.capability_id == "wuwa.status"
    assert result.body == "统一运行时在线"

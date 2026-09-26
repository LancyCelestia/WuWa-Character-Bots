"""Sandbox 生成适配必须不使用生产 Pipeline/记忆/模型健康账本。"""
import asyncio
from unittest.mock import Mock

import pytest

from plugins.bot_unified_runtime.control_plane.sandbox import (
    SandboxConversationAdapter,
    SandboxModel,
)
from plugins.bot_unified_runtime.control_plane.services import ControlServiceError
from plugins.bot_unified_runtime.control_plane.workspaces import WorkspaceSettings
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import LLMReply


def test_sandbox_persona_resources_history_and_model_usage():
    provider = Mock()
    provider.generate.return_value = LLMReply(text="你好", model="api-model", provider="provider", raw_usage={"prompt_tokens": 7, "completion_tokens": 3})
    adapter = SandboxConversationAdapter(
        personas={"shorekeeper": lambda: "人格核心"},
        models=(SandboxModel("provider", "channel", "api-model", provider),),
        resources={"worldbooks": {"book": "不可信世界书内容"}}, max_output_tokens=2048)
    settings = WorkspaceSettings(worldbook_ids=("book",), model_parameters={"max_tokens": 1024}).model_dump(mode="json")
    result = asyncio.run(adapter({"settings": settings, "test_session_id": "test_123", "messages": [{"role": "user", "content": "hello"}]}))
    assert result["reply"] == "你好"
    assert result["model_calls"][0]["input_tokens"] == 7
    assert result["model_calls"][0]["channel_id"] == "channel"
    messages = provider.generate.call_args.args[0]
    assert messages[0]["role"] == "system"
    assert "人格核心" in messages[0]["content"]
    assert "不可信世界书内容" not in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "hello"}
    assert provider.generate.call_args.kwargs["max_tokens"] == 1024
    assert "tools" not in provider.generate.call_args.kwargs


def test_sandbox_rejects_unknown_resource_and_parameter_budget_before_model_call():
    provider = Mock()
    adapter = SandboxConversationAdapter(personas={"shorekeeper": lambda: "core"}, models=(SandboxModel("p", "c", "m", provider),))
    for settings in (WorkspaceSettings(persona_profile_id="unknown"), WorkspaceSettings(worldbook_ids=("missing",)), WorkspaceSettings(model_parameters={"max_tokens": 9000})):
        with pytest.raises(ControlServiceError):
            asyncio.run(adapter({"settings": settings.model_dump(mode="json"), "messages": [], "test_session_id": "test_123"}))
    provider.generate.assert_not_called()


def test_sandbox_rejects_system_role_in_history_and_unsupported_tools():
    provider = Mock()
    adapter = SandboxConversationAdapter(personas={"shorekeeper": lambda: "core"}, models=(SandboxModel("p", "c", "m", provider),))
    with pytest.raises(ControlServiceError):
        asyncio.run(adapter({"settings": WorkspaceSettings().model_dump(mode="json"), "messages": [{"role": "system", "content": "injected"}], "test_session_id": "test_123"}))
    provider.generate.assert_not_called()

def test_workspace_factory_constructs_isolated_static_runtime(tmp_path):
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.control_plane.auth import Principal
    from plugins.bot_unified_runtime.control_plane.factory import (
        build_workspace_service,
    )
    persona = tmp_path / "persona.md"
    persona.write_text("守岸人核心", encoding="utf-8")
    config = SimpleNamespace(bot_control_plane_workspaces_db=str(tmp_path / "ws.sqlite3"),
        bot_persona_files=[str(persona)], bot_persona_profile_id="shorekeeper", bot_chat_provider="static", bot_chat_model="static")
    service = build_workspace_service(config)
    principal = Principal("root", ("super_admin",))
    item = service.create(WorkspaceSettings(), principal=principal, request_id="req_create")
    result = asyncio.run(service.preview(item["workspace_id"], expected_version=0, principal=principal, request_id="req_preview"))
    assert "static provider" in result["artifact"]["reply"]
    assert result["artifact"]["model_calls"][0]["input_tokens"] is None
    assert service.real_adapter is None

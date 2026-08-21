from __future__ import annotations

import inspect
from pathlib import Path

from plugins.wuwa_unified_runtime.config import Config
from plugins.wuwa_unified_runtime.contracts import PrivacyLevel


def _setup_config(tmp_path: Path) -> Config:
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")
    return Config(
        wuwa_persona_files=[str(persona_file)],
        wuwa_chat_provider="static",
        wuwa_chat_model="static",
        wuwa_chat_api_key="sk-live-secret",
    )


def test_admin_llm_setup_query_returns_safe_setup_checklist(tmp_path):
    from plugins.wuwa_unified_runtime.capabilities.debug import (
        build_llm_setup_query_result,
    )

    result = build_llm_setup_query_result(
        _setup_config(tmp_path),
        request_id="req_llm_setup",
        actor_roles=["user", "admin"],
    )

    assert result.capability_id == "wuwa.setup.llm"
    assert result.request_id == "req_llm_setup"
    assert result.privacy_level is PrivacyLevel.PERSONAL
    assert "LLM 接入清单" in result.body
    assert "llm_setup_status=needs_env_edit" in result.body
    assert "ready_for_real_llm=false" in result.body
    assert "llm_readiness_status=local_only" in result.body
    assert "llm_next_action=configure_real_llm" in result.body
    assert "llm_readiness_reasons=provider_not_real" in result.body
    assert "llm_fix_hints=BOT_CHAT_PROVIDER=openai_compatible" in result.body
    assert "required_env_keys=BOT_CHAT_PROVIDER,BOT_CHAT_MODEL" in result.body
    assert "missing_or_placeholder_env_keys=BOT_CHAT_PROVIDER" in result.body
    assert "safe_env_template=BOT_CHAT_PROVIDER=openai_compatible;" in result.body
    assert "BOT_CHAT_API_KEY=<real_api_key>" in result.body
    assert "next_commands=powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 config-smoke;" in result.body
    assert "manual_steps=复制安全占位模板到 .env 并替换模型服务配置。;" in result.body
    assert "real_llm_probe_performed=false" in result.body
    assert "napcat_connected=false" in result.body
    assert "message_sent=false" in result.body
    assert "writes_env=false" in result.body
    assert "secrets_hidden=true" in result.body
    assert "不调用真实 LLM" in result.body
    assert "不展示密钥" in result.body

    forbidden_fragments = [
        "sk-live-secret",
        str(tmp_path),
        "守岸人来自黑海岸",
        "Authorization",
        "Bearer",
        "system_prompt",
        "prompt=",
        "target_id",
        "provider_message_id",
        "private_debug",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in result.body


def test_non_admin_llm_setup_query_is_rejected_without_leaking_config(tmp_path):
    from plugins.wuwa_unified_runtime.capabilities.debug import (
        build_llm_setup_query_result,
    )

    result = build_llm_setup_query_result(
        _setup_config(tmp_path),
        request_id="req_llm_setup",
        actor_roles=["user"],
    )

    assert result.capability_id == "wuwa.setup.llm"
    assert "只有管理员可以查看运行时排障记录" in result.body
    assert "llm_setup_status" not in result.body
    assert "BOT_CHAT_PROVIDER" not in result.body
    assert "sk-live-secret" not in result.body
    assert str(tmp_path) not in result.body


def test_plugin_entry_exposes_admin_llm_setup_command_without_self_overwrite():
    import plugins.wuwa_unified_runtime as plugin_entry

    source = inspect.getsource(plugin_entry)

    assert "build_llm_setup_query_result" in source
    assert 'capability_id = "wuwa.setup.llm"' in source
    assert 'command_text == "setup llm"' in source
    assert "wuwa.setup.llm" in plugin_entry.NO_RUNTIME_DIAGNOSTIC_CAPABILITY_IDS


def test_help_text_mentions_llm_setup_command():
    from plugins.wuwa_unified_runtime.capabilities.echo import build_help_result

    result = build_help_result(request_id="req_help")

    assert "/wuwa setup llm" in result.body

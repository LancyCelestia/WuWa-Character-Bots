from __future__ import annotations

import inspect

from plugins.wuwa_unified_runtime.config import Config
from plugins.wuwa_unified_runtime.contracts import PrivacyLevel
from plugins.wuwa_unified_runtime.llm import LLMProviderError, LLMReply


class _EchoProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.last_messages: list[dict[str, str]] = []
        self.last_kwargs: dict[str, object] = {}

    def generate(self, messages, **kwargs):
        self.calls += 1
        self.last_messages = messages
        self.last_kwargs = kwargs
        return LLMReply(
            text="诊断连接正常。",
            provider="openai_compatible",
            model=str(kwargs.get("model") or "diag-model"),
            confidence=1.0,
            raw_usage={"total_tokens": 16, "finish_reason": "length"},
        )


class _RaisingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        raise LLMProviderError(
            "upstream rejected request api_key=sk-live-secret token=raw-token"
        )


class _TimeoutProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        raise LLMProviderError("request timed out", error_kind="timeout")


class _UnexpectedProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        raise RuntimeError("Authorization: Bearer sk-live-secret token=raw-token")


def test_admin_llm_query_calls_provider_and_returns_safe_summary():
    from plugins.wuwa_unified_runtime.capabilities.debug import build_llm_query_result

    provider = _EchoProvider()
    result = build_llm_query_result(
        Config(
            wuwa_chat_provider="openai_compatible",
            wuwa_chat_model="diag-model",
            wuwa_chat_api_key="sk-live-secret",
            wuwa_chat_base_url="https://llm.example/v1",
            wuwa_chat_temperature=0.7,
            wuwa_chat_max_tokens=512,
        ),
        request_id="req_llm",
        actor_roles=["user", "admin"],
        llm_provider=provider,
    )

    assert provider.calls == 1
    assert provider.last_messages[0]["role"] == "system"
    assert provider.last_kwargs["temperature"] == 0.3
    assert provider.last_kwargs["max_tokens"] == 128
    assert result.capability_id == "wuwa.llm"
    assert result.request_id == "req_llm"
    assert result.privacy_level is PrivacyLevel.PERSONAL
    assert "LLM 诊断" in result.body
    assert "ok=true" in result.body
    assert "provider=openai_compatible" in result.body
    assert "model=diag-model" in result.body
    assert "endpoint_url=https://llm.example/v1/chat/completions" in result.body
    assert "api_key=set" in result.body
    assert "error_kind=none" in result.body
    assert "reply_preview_chars=7" in result.body
    assert "usage_total_tokens=16" in result.body
    assert "llm_finish_reason=length" in result.body
    assert "diagnostic_temperature=0.3" in result.body
    assert "diagnostic_max_tokens=128" in result.body
    assert "timeout_seconds=30" in result.body
    assert "sk-live-secret" not in result.body
    assert "raw-token" not in result.body
    assert "Authorization" not in result.body
    assert "Bearer" not in result.body


def test_non_admin_llm_query_is_rejected_without_calling_provider():
    from plugins.wuwa_unified_runtime.capabilities.debug import build_llm_query_result

    provider = _EchoProvider()
    result = build_llm_query_result(
        Config(
            wuwa_chat_provider="openai_compatible",
            wuwa_chat_model="diag-model",
            wuwa_chat_api_key="sk-live-secret",
        ),
        request_id="req_llm",
        actor_roles=["user"],
        llm_provider=provider,
    )

    assert provider.calls == 0
    assert result.capability_id == "wuwa.llm"
    assert "只有管理员可以查看运行时排障记录" in result.body
    assert "diag-model" not in result.body
    assert "sk-live-secret" not in result.body


def test_llm_query_reports_missing_key_without_network_call():
    from plugins.wuwa_unified_runtime.capabilities.debug import build_llm_query_result

    provider = _EchoProvider()
    result = build_llm_query_result(
        Config(
            wuwa_chat_provider="openai_compatible",
            wuwa_chat_model="diag-model",
            wuwa_chat_api_key="your-api-key",
            wuwa_chat_base_url="https://llm.example/v1",
        ),
        request_id="req_llm",
        actor_roles=["admin"],
        llm_provider=provider,
    )

    assert provider.calls == 0
    assert "ok=false" in result.body
    assert "api_key=missing" in result.body
    assert "error_kind=config_missing" in result.body
    assert "your-api-key" not in result.body


def test_llm_query_reports_missing_model_and_base_url_without_network_call(tmp_path):
    from plugins.wuwa_unified_runtime.capabilities.debug import build_llm_query_result

    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")
    knowledge_file = tmp_path / "knowledge.md"
    knowledge_file.write_text("守岸人会守望漂泊者。", encoding="utf-8")
    provider = _EchoProvider()

    result = build_llm_query_result(
        Config(
            wuwa_persona_files=[str(persona_file)],
            wuwa_knowledge_files=[str(knowledge_file)],
            wuwa_chat_provider="openai_compatible",
            wuwa_chat_model="your-model-name",
            wuwa_chat_api_key="sk-live-secret",
            wuwa_chat_base_url="",
        ),
        request_id="req_llm",
        actor_roles=["admin"],
        llm_provider=provider,
    )

    assert provider.calls == 0
    assert "ok=false" in result.body
    assert "ready_for_real_llm=false" in result.body
    assert "llm_readiness_status=blocked" in result.body
    assert "llm_next_action=fix_config" in result.body
    assert "llm_readiness_reasons=openai_model_missing,openai_base_url_missing" in result.body
    assert (
        "llm_fix_hints=BOT_CHAT_MODEL=<model_name>,"
        "BOT_CHAT_BASE_URL=<openai_compatible_base_url>"
    ) in result.body
    assert "error_kind=config_missing" in result.body
    assert "endpoint_url=" in result.body
    assert "sk-live-secret" not in result.body


def test_llm_query_treats_safe_template_credentials_as_missing_without_network_call(
    tmp_path,
):
    from plugins.wuwa_unified_runtime.capabilities.debug import build_llm_query_result

    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")
    provider = _EchoProvider()

    result = build_llm_query_result(
        Config(
            wuwa_persona_files=[str(persona_file)],
            wuwa_chat_provider="openai_compatible",
            wuwa_chat_model="<model_name>",
            wuwa_chat_api_key="<real_api_key>",
            wuwa_chat_base_url="https://llm.example/v1",
        ),
        request_id="req_llm",
        actor_roles=["admin"],
        llm_provider=provider,
    )

    assert provider.calls == 0
    assert "api_key=missing" in result.body
    assert "openai_api_key_missing" in result.body
    assert "openai_model_missing" in result.body


def test_llm_query_reports_invalid_generation_parameters_without_network_call(tmp_path):
    from plugins.wuwa_unified_runtime.capabilities.debug import build_llm_query_result

    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")
    knowledge_file = tmp_path / "knowledge.md"
    knowledge_file.write_text("守岸人会守望漂泊者。", encoding="utf-8")
    provider = _EchoProvider()

    result = build_llm_query_result(
        Config(
            wuwa_persona_files=[str(persona_file)],
            wuwa_knowledge_files=[str(knowledge_file)],
            wuwa_chat_provider="openai_compatible",
            wuwa_chat_model="diag-model",
            wuwa_chat_api_key="sk-live-secret",
            wuwa_chat_base_url="https://llm.example/v1",
            wuwa_chat_temperature=4,
            wuwa_chat_max_tokens=0,
            wuwa_chat_timeout_seconds=0,
        ),
        request_id="req_llm",
        actor_roles=["admin"],
        llm_provider=provider,
    )

    assert provider.calls == 0
    assert "ok=false" in result.body
    assert "ready_for_real_llm=false" in result.body
    assert "llm_readiness_status=blocked" in result.body
    assert "llm_next_action=fix_config" in result.body
    assert (
        "llm_readiness_reasons=openai_temperature_invalid,"
        "openai_max_tokens_invalid,openai_timeout_seconds_invalid"
    ) in result.body
    assert (
        "llm_fix_hints=BOT_CHAT_TEMPERATURE=0.0..2.0,"
        "BOT_CHAT_MAX_TOKENS>=1,BOT_CHAT_TIMEOUT_SECONDS>0"
    ) in result.body
    assert "error_kind=config_missing" in result.body
    assert "diagnostic_temperature=0" in result.body
    assert "diagnostic_max_tokens=0" in result.body
    assert "timeout_seconds=0" in result.body
    assert "sk-live-secret" not in result.body
    assert str(tmp_path) not in result.body


def test_llm_query_reports_unsafe_base_url_without_leaking_credentials(tmp_path):
    from plugins.wuwa_unified_runtime.capabilities.debug import build_llm_query_result

    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text("守岸人来自黑海岸。\n说话温柔克制。", encoding="utf-8")
    knowledge_file = tmp_path / "knowledge.md"
    knowledge_file.write_text("守岸人会守望漂泊者。", encoding="utf-8")
    provider = _EchoProvider()

    result = build_llm_query_result(
        Config(
            wuwa_persona_files=[str(persona_file)],
            wuwa_knowledge_files=[str(knowledge_file)],
            wuwa_chat_provider="openai_compatible",
            wuwa_chat_model="diag-model",
            wuwa_chat_api_key="sk-live-secret",
            wuwa_chat_base_url="https://user:raw-password@llm.example/v1",
        ),
        request_id="req_llm",
        actor_roles=["admin"],
        llm_provider=provider,
    )

    assert provider.calls == 0
    assert "ok=false" in result.body
    assert "ready_for_real_llm=false" in result.body
    assert "llm_readiness_status=blocked" in result.body
    assert "llm_next_action=fix_config" in result.body
    assert "llm_readiness_reasons=openai_base_url_unsafe" in result.body
    assert "llm_fix_hints=remove_credentials_from_BOT_CHAT_BASE_URL" in result.body
    assert "error_kind=config_missing" in result.body
    assert "endpoint_url=https://[redacted]@llm.example/v1/chat/completions" in result.body
    assert "raw-password" not in result.body
    assert "user:raw-password" not in result.body
    assert "sk-live-secret" not in result.body


def test_llm_query_redacts_provider_error_details():
    from plugins.wuwa_unified_runtime.capabilities.debug import build_llm_query_result

    provider = _RaisingProvider()
    result = build_llm_query_result(
        Config(
            wuwa_chat_provider="openai_compatible",
            wuwa_chat_model="diag-model",
            wuwa_chat_api_key="sk-live-secret",
            wuwa_chat_base_url="https://llm.example/v1",
        ),
        request_id="req_llm",
        actor_roles=["admin"],
        llm_provider=provider,
    )

    assert provider.calls == 1
    assert "ok=false" in result.body
    assert "error_kind=provider_error" in result.body
    assert "sk-live-secret" not in result.body
    assert "raw-token" not in result.body
    assert "api_key=[redacted]" not in result.body
    assert "token=[redacted]" not in result.body


def test_llm_query_uses_provider_error_kind_when_available():
    from plugins.wuwa_unified_runtime.capabilities.debug import build_llm_query_result

    provider = _TimeoutProvider()
    result = build_llm_query_result(
        Config(
            wuwa_chat_provider="openai_compatible",
            wuwa_chat_model="diag-model",
            wuwa_chat_api_key="sk-live-secret",
            wuwa_chat_base_url="https://llm.example/v1",
        ),
        request_id="req_llm",
        actor_roles=["admin"],
        llm_provider=provider,
    )

    assert provider.calls == 1
    assert "ok=false" in result.body
    assert "error_kind=timeout" in result.body
    assert "超时" in result.body


def test_llm_query_wraps_unexpected_provider_errors_safely():
    from plugins.wuwa_unified_runtime.capabilities.debug import build_llm_query_result

    provider = _UnexpectedProvider()
    result = build_llm_query_result(
        Config(
            wuwa_chat_provider="openai_compatible",
            wuwa_chat_model="diag-model",
            wuwa_chat_api_key="sk-live-secret",
            wuwa_chat_base_url="https://llm.example/v1",
        ),
        request_id="req_llm",
        actor_roles=["admin"],
        llm_provider=provider,
    )

    assert provider.calls == 1
    assert "ok=false" in result.body
    assert "error_kind=provider_error" in result.body
    assert "sk-live-secret" not in result.body
    assert "raw-token" not in result.body
    assert "Authorization" not in result.body


def test_plugin_entry_exposes_admin_llm_command_without_self_overwrite():
    import plugins.wuwa_unified_runtime as plugin_entry

    source = inspect.getsource(plugin_entry)

    assert "build_llm_query_result" in source
    assert 'capability_id = "wuwa.llm"' in source
    assert "wuwa.llm" in plugin_entry.NO_RUNTIME_DIAGNOSTIC_CAPABILITY_IDS
    assert "wuwa.control" in plugin_entry.NO_RUNTIME_DIAGNOSTIC_CAPABILITY_IDS


def test_help_text_mentions_llm_command():
    from plugins.wuwa_unified_runtime.capabilities.echo import build_help_result

    result = build_help_result(request_id="req_help")

    assert "/wuwa llm" in result.body

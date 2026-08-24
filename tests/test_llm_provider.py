import json
from email.message import Message
import io
from urllib import error

import pytest

from plugins.bot_unified_runtime import _build_chat_llm_provider
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.llm import (
    LLMProviderError,
    OpenAICompatibleLLMProvider,
)


class FakeHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class RecordingUrlopen:
    def __init__(self, response_payload: dict | None = None, exception: Exception | None = None) -> None:
        self.response_payload = response_payload or {
            "choices": [{"message": {"content": "连接正常。"}}],
            "usage": {"total_tokens": 9},
        }
        self.exception = exception
        self.calls = 0
        self.last_request = None
        self.last_timeout: float | None = None

    def __call__(self, http_request, timeout: float):
        self.calls += 1
        self.last_request = http_request
        self.last_timeout = timeout
        if self.exception:
            raise self.exception
        return FakeHTTPResponse(self.response_payload)


def _http_error(code: int) -> error.HTTPError:
    return error.HTTPError(
        url="https://llm.example/v1/chat/completions",
        code=code,
        msg="HTTP error",
        hdrs=Message(),
        fp=io.BytesIO(b'{"error":"nope"}'),
    )


def _http_error_with_body(code: int, body: bytes) -> error.HTTPError:
    return error.HTTPError(
        url="https://llm.example/v1/chat/completions",
        code=code,
        msg="HTTP error",
        hdrs=Message(),
        fp=io.BytesIO(body),
    )


def test_openai_compatible_provider_sends_expected_payload_headers_and_timeout():
    urlopen = RecordingUrlopen()
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        base_url="https://llm.example/v1/",
        timeout_seconds=12.5,
        urlopen=urlopen,
    )

    reply = provider.generate(
        [{"role": "user", "content": "你好"}],
        model="override-model",
        temperature=0.2,
        max_tokens=64,
    )

    request = urlopen.last_request
    payload = json.loads(request.data.decode("utf-8"))

    assert urlopen.calls == 1
    assert request.full_url == "https://llm.example/v1/chat/completions"
    assert request.get_method() == "POST"
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert request.headers["Content-type"] == "application/json"
    assert urlopen.last_timeout == 12.5
    assert payload["model"] == "override-model"
    assert payload["messages"] == [{"role": "user", "content": "你好"}]
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 64
    assert reply.text == "连接正常。"
    assert reply.raw_usage == {"total_tokens": 9}


def test_openai_compatible_provider_omits_max_tokens_when_unlimited():
    """max_tokens=0 表示不设上限：不向 API 传该字段。"""
    urlopen = RecordingUrlopen()
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        base_url="https://llm.example/v1/",
        urlopen=urlopen,
    )

    provider.generate(
        [{"role": "user", "content": "你好"}],
        max_tokens=0,
    )

    payload = json.loads(urlopen.last_request.data.decode("utf-8"))
    assert "max_tokens" not in payload


def test_openai_compatible_provider_accepts_full_chat_completions_endpoint():
    urlopen = RecordingUrlopen()
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        base_url="https://llm.example/v1/chat/completions/",
        urlopen=urlopen,
    )

    provider.generate([{"role": "user", "content": "你好"}])

    assert urlopen.last_request.full_url == "https://llm.example/v1/chat/completions"
    assert provider.endpoint_url == "https://llm.example/v1/chat/completions"


def test_openai_compatible_provider_rejects_base_url_with_credentials_before_network_call():
    urlopen = RecordingUrlopen()
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        base_url="https://user:raw-password@llm.example/v1",
        urlopen=urlopen,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "你好"}])

    assert urlopen.calls == 0
    assert exc_info.value.error_kind == "config_missing"
    assert "base_url" in str(exc_info.value)
    assert "raw-password" not in str(exc_info.value)


def test_openai_compatible_provider_rejects_non_http_base_url_before_network_call():
    urlopen = RecordingUrlopen()
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        base_url="file:///C:/secret",
        urlopen=urlopen,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "你好"}])

    assert urlopen.calls == 0
    assert exc_info.value.error_kind == "config_missing"
    assert "base_url" in str(exc_info.value)
    assert "C:/secret" not in str(exc_info.value)


def test_openai_compatible_provider_reports_invalid_response_schema():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(response_payload={"choices": []}),
    )

    with pytest.raises(LLMProviderError, match="schema") as exc_info:
        provider.generate([{"role": "user", "content": "你好"}])

    assert exc_info.value.error_kind == "schema"


def test_openai_compatible_provider_accepts_text_content_parts():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(
            response_payload={
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "第一段连接正常。"},
                                {"type": "text", "text": "第二段也正常。"},
                            ]
                        }
                    }
                ],
                "usage": {"total_tokens": 13},
            }
        ),
    )

    reply = provider.generate([{"role": "user", "content": "你好"}])

    assert reply.text == "第一段连接正常。\n第二段也正常。"
    assert reply.raw_usage == {"total_tokens": 13}


def test_openai_compatible_provider_ignores_non_object_usage_payload():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(
            response_payload={
                "choices": [{"message": {"content": "连接正常。"}}],
                "usage": ["not", "an", "object"],
            }
        ),
    )

    reply = provider.generate([{"role": "user", "content": "hello"}])

    assert reply.text == "连接正常。"
    assert reply.raw_usage == {}


def test_openai_compatible_provider_carries_safe_finish_reason_in_usage():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(
            response_payload={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": "连接正常。"},
                    }
                ],
                "usage": {"total_tokens": 9},
            }
        ),
    )

    reply = provider.generate([{"role": "user", "content": "你好"}])

    assert reply.raw_usage == {"total_tokens": 9, "finish_reason": "length"}


def test_openai_compatible_provider_drops_unsafe_finish_reason_details():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(
            response_payload={
                "choices": [
                    {
                        "finish_reason": "length Authorization: Bearer sk-live-secret",
                        "message": {"content": "连接正常。"},
                    }
                ],
                "usage": {"total_tokens": 9},
            }
        ),
    )

    reply = provider.generate([{"role": "user", "content": "你好"}])

    assert reply.raw_usage == {"total_tokens": 9}
    assert "sk-live-secret" not in str(reply.raw_usage)
    assert "Authorization" not in str(reply.raw_usage)


def test_openai_compatible_provider_classifies_unexpected_content_type_as_schema_error():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(
            response_payload={
                "choices": [{"message": {"content": {"unexpected": "shape"}}}]
            }
        ),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "你好"}])

    assert exc_info.value.error_kind == "schema"


def test_openai_compatible_provider_maps_network_errors_to_provider_errors():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(exception=error.URLError("connection refused")),
    )

    with pytest.raises(LLMProviderError, match="network") as exc_info:
        provider.generate([{"role": "user", "content": "你好"}])

    assert exc_info.value.error_kind == "network"


def test_openai_compatible_provider_does_not_leak_url_error_reason_details():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(
            exception=error.URLError("proxy used Authorization: Bearer sk-live-secret")
        ),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "hello"}])

    assert exc_info.value.error_kind == "network"
    assert "sk-live-secret" not in str(exc_info.value)
    assert "Authorization" not in str(exc_info.value)


def test_openai_compatible_provider_does_not_leak_http_response_body_details():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(
            exception=_http_error_with_body(
                401,
                b'{"error":"Authorization: Bearer sk-live-secret"}',
            )
        ),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "hello"}])

    assert exc_info.value.error_kind == "auth"
    assert "sk-live-secret" not in str(exc_info.value)
    assert "Authorization" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("status_code", "expected_kind"),
    [
        (401, "auth"),
        (403, "auth"),
        (429, "rate_limited"),
        (500, "server"),
        (418, "http"),
    ],
)
def test_openai_compatible_provider_classifies_http_errors(status_code, expected_kind):
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(exception=_http_error(status_code)),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "你好"}])

    assert exc_info.value.error_kind == expected_kind


def test_openai_compatible_provider_classifies_timeout_errors():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(exception=TimeoutError("timed out")),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "你好"}])

    assert exc_info.value.error_kind == "timeout"


def test_openai_compatible_provider_classifies_empty_text_as_empty_response():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(
            response_payload={"choices": [{"message": {"content": "   "}}]}
        ),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "你好"}])

    assert exc_info.value.error_kind == "empty_response"


def test_openai_compatible_provider_classifies_refusal_without_content_as_empty_response():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(
            response_payload={
                "choices": [
                    {
                        "message": {
                            "refusal": "I cannot comply. Authorization: Bearer sk-live-secret"
                        }
                    }
                ]
            }
        ),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "你好"}])

    assert exc_info.value.error_kind == "empty_response"
    assert "sk-live-secret" not in str(exc_info.value)
    assert "Authorization" not in str(exc_info.value)


def test_openai_compatible_provider_classifies_missing_content_as_empty_response():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(response_payload={"choices": [{"message": {}}]}),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "你好"}])

    assert exc_info.value.error_kind == "empty_response"


def test_openai_compatible_provider_wraps_unexpected_transport_errors_without_leaking_details():
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        urlopen=RecordingUrlopen(
            exception=RuntimeError(
                "proxy exploded with Authorization: Bearer sk-live-secret"
            )
        ),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "hello"}])

    assert exc_info.value.error_kind == "provider_error"
    assert "sk-live-secret" not in str(exc_info.value)
    assert "Authorization" not in str(exc_info.value)


def test_chat_provider_factory_uses_configured_timeout():
    provider = _build_chat_llm_provider(
        Config(
            bot_chat_provider="openai_compatible",
            bot_chat_model="diag-model",
            bot_chat_api_key="sk-test",
            bot_chat_timeout_seconds=7.5,
        )
    )

    assert isinstance(provider, OpenAICompatibleLLMProvider)
    assert provider.timeout_seconds == 7.5

def test_provider_returns_tool_calls_when_content_is_empty_and_passes_tools_payload():
    payload = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": '{"query": "守岸人"}',
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"total_tokens": 12},
    }
    urlopen = RecordingUrlopen(payload)
    provider = OpenAICompatibleLLMProvider(
        api_key="sk-test",
        model="default-model",
        base_url="https://llm.example/v1/",
        urlopen=urlopen,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "联网搜索",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]
    reply = provider.generate(
        [{"role": "user", "content": "守岸人是谁"}],
        tools=tools,
    )
    sent = json.loads(urlopen.last_request.data.decode("utf-8"))
    assert sent["tools"][0]["function"]["name"] == "web_search"
    assert reply.text == ""
    assert reply.tool_calls[0]["function"]["name"] == "web_search"
    assert reply.tool_calls[0]["function"]["arguments"] == '{"query": "守岸人"}'
    assert reply.raw_usage["finish_reason"] == "tool_calls"


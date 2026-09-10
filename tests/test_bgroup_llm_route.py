"""B组 llm 域回归（管线检视 #2/#7 + B-14 旧快照迁移）。

- B-2：未识别 4xx 归 bad_request 且可故障转移；invalid_request /
  unsupported_parameter / http 不再判死整条多候选路由。
- B-5：生产传输路径走进程级 httpx.Client（连接池复用）+ 响应体 8MB 限长。
- B-14：路由侧动态注册表对无 source 标记的旧快照按 env 镜像语义自动迁移。
"""

from __future__ import annotations

import httpx
import pytest

import plugins.bot_unified_runtime.llm.providers as providers_module
from plugins.bot_unified_runtime.llm.model_router import ModelRouter, ModelSpec
from plugins.bot_unified_runtime.llm.providers import (
    LLMProviderError,
    LLMReply,
    OpenAICompatibleLLMProvider,
    should_failover,
)


class _FakeProvider:
    def __init__(self, model_id: str, failures: dict[str, str], calls: list[str]) -> None:
        self.model_id = model_id
        self.failures = failures
        self.calls = calls

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self.calls.append(self.model_id)
        error_kind = self.failures.get(self.model_id)
        if error_kind:
            raise LLMProviderError(error_kind, error_kind=error_kind)
        return LLMReply(text=f"ok:{self.model_id}", provider="fake", model=self.model_id)


def _spec(model_id: str, priority: int, *, api_key: str = "key") -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model_id,
        base_url="https://example.test/v1",
        api_key=api_key,
        tags=("fast",),
        priority=priority,
    )


# ==================== B-2：4xx 渠道相关错误可故障转移 ====================


@pytest.mark.parametrize(
    "error_kind",
    ["bad_request", "invalid_request", "unsupported_parameter", "http"],
)
def test_request_error_kinds_are_failoverable(error_kind: str) -> None:
    assert should_failover(error_kind)


@pytest.mark.parametrize(
    "error_kind",
    ["bad_request", "invalid_request", "unsupported_parameter"],
)
def test_param_error_kinds_strip_retry_then_fail_over(error_kind: str) -> None:
    """剥参类别（B-2 契约）：先同渠道去参重试一次，仍失败才转移下一候选。"""
    calls: list[str] = []
    router = ModelRouter(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        provider_factory=lambda spec: _FakeProvider(
            spec.model_id, {"first": error_kind}, calls
        ),
    )

    reply = router.generate(
        [{"role": "user", "content": "hello"}],
        message_text="hello",
        reasoning_effort="high",
    )

    assert reply.text == "ok:second"
    assert calls == ["first", "first", "second"]
    assert router.last_attempts == [f"first:{error_kind}", "second:success"]


@pytest.mark.parametrize("error_kind", ["http"])
def test_unclassified_request_errors_fail_over_directly(error_kind: str) -> None:
    calls: list[str] = []
    router = ModelRouter(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        provider_factory=lambda spec: _FakeProvider(
            spec.model_id, {"first": error_kind}, calls
        ),
    )

    reply = router.generate([{"role": "user", "content": "hello"}], message_text="hello")

    assert reply.text == "ok:second"
    assert calls == ["first", "second"]
    assert router.last_attempts == [f"first:{error_kind}", "second:success"]


# ==================== B-5 + B-2：httpx 生产路径 ====================


_OPEN_MOCK_CLIENTS: list[httpx.Client] = []


@pytest.fixture(autouse=True)
def _close_mock_clients():
    yield
    while _OPEN_MOCK_CLIENTS:
        _OPEN_MOCK_CLIENTS.pop().close()


def _httpx_provider(
    monkeypatch: pytest.MonkeyPatch, handler: object
) -> OpenAICompatibleLLMProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    _OPEN_MOCK_CLIENTS.append(client)
    monkeypatch.setattr(providers_module, "_shared_http_client", lambda proxy="": client)
    return OpenAICompatibleLLMProvider(
        api_key="test-key",
        model="model-a",
        base_url="https://example.test/v1",
    )


def test_httpx_plain_400_without_english_markers_is_failoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """报告原始触发场景：中文 400 文案不再把多候选路由打成单点。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "参数 reasoning_effort 不受支持"}})

    provider = _httpx_provider(monkeypatch, handler)

    with pytest.raises(LLMProviderError) as raised:
        provider.generate([{"role": "user", "content": "hi"}])

    assert raised.value.error_kind == "bad_request"
    assert should_failover(raised.value.error_kind)


def test_httpx_transport_success_sends_auth_and_browser_ua(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    provider = _httpx_provider(monkeypatch, handler)
    reply = provider.generate([{"role": "user", "content": "hi"}])

    assert reply.text == "ok"
    assert seen[0]["authorization"] == "Bearer test-key"
    # 部分中转站 WAF 拦截 Python 默认 UA，浏览器 UA 语义必须保留。
    assert seen[0]["user-agent"] == "Mozilla/5.0"


def test_httpx_transport_response_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (providers_module._MAX_RESPONSE_BYTES + 1))

    provider = _httpx_provider(monkeypatch, handler)

    with pytest.raises(LLMProviderError) as raised:
        provider.generate([{"role": "user", "content": "hi"}])

    assert raised.value.error_kind == "provider_error"
    assert should_failover(raised.value.error_kind)


def test_httpx_transport_timeout_maps_to_timeout_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    provider = _httpx_provider(monkeypatch, handler)

    with pytest.raises(LLMProviderError) as raised:
        provider.generate([{"role": "user", "content": "hi"}])

    assert raised.value.error_kind == "timeout"


# ==================== B-14：路由侧旧快照自动迁移 ====================


def _fresh_base_specs() -> dict[str, ModelSpec]:
    return {
        "env-a": ModelSpec(
            model_id="env-a",
            model="gemini-fresh",
            base_url="https://fresh.example/v1",
            api_key="sk-fresh-plain",
            api_keys=("sk-fresh-plain",),
            tags=("fast",),
            priority=5,
        ),
    }


def test_legacy_unmarked_snapshot_migrates_to_env_fresh_content() -> None:
    """无 source 标记的存量条目不再整体遮蔽 .env 同名条目。"""
    legacy = {
        "env-a": {
            "model": "gemini-STALE",
            "base_url": "http://stale.example/v1",
            "api_key": "sk-stale",
            "priority": 2,
        }
    }
    router = ModelRouter(
        _fresh_base_specs(),
        provider_factory=lambda spec: None,
        dynamic_registry=lambda: legacy,
    )

    router._refresh_dynamic_registry()

    spec = router.specs["env-a"]
    assert spec.model == "gemini-fresh"
    assert spec.base_url == "https://fresh.example/v1"
    assert spec.api_key == "sk-fresh-plain"
    # 快照里的 priority（管理员重排序意图）保留。


def test_unmarked_entry_without_env_counterpart_stays_wholesale() -> None:
    """纯运行时条目（.env 无同名 id）整体生效，行为不变。"""
    legacy = {
        "custom": {
            "model": "custom-model",
            "base_url": "http://custom.example/v1",
            "api_key": "sk-custom",
            "priority": 1,
        }
    }
    router = ModelRouter(
        _fresh_base_specs(),
        provider_factory=lambda spec: None,
        dynamic_registry=lambda: legacy,
    )

    router._refresh_dynamic_registry()

    spec = router.specs["custom"]
    assert spec.model == "custom-model"
    assert spec.api_key == "sk-custom"


def test_env_mirror_of_removed_env_id_still_dropped() -> None:
    legacy = {
        "gone": {"model": "x", "base_url": "http://x/v1", "source": "env", "priority": 1},
    }
    router = ModelRouter(
        _fresh_base_specs(),
        provider_factory=lambda spec: None,
        dynamic_registry=lambda: legacy,
    )

    router._refresh_dynamic_registry()

    assert "gone" not in router.specs

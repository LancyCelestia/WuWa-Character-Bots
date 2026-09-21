"""B-2（管线检视 #2）HTTP 400 语义分类回归矩阵。

锁定「分类器 → 故障转移消费侧」全链路每个语义类别的去向：
- 400 按响应体语义分类：参数不支持（含中文措辞）→ 同渠道去参重试；
  上下文超限 / 未知 4xx → 归 bad_request 兜底，先去参一次再转移；
- 鉴权失败（401/403）按状态码优先，不被响应体措辞升级进去参重试类别，
  同一渠道内只按密钥列表轮换、绝不重试同一把坏 key；
- 5xx / 超时 / 网络类维持可转移语义。
全部离线：httpx.MockTransport 模拟中转站，不发起真实网络请求。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers as providers_module
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    _PARAM_STRIP_RETRY_KINDS,
    ModelRouter,
    ModelSpec,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMReply,
    OpenAICompatibleLLMProvider,
    _classify_http_error,
    should_failover,
)


def _chat_completion(text: str = "ok") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _spec(
    model_id: str,
    priority: int,
    *,
    api_key: str = "key",
    api_keys: tuple[str, ...] = (),
) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model_id,
        base_url="https://example.test/v1",
        api_key=api_key,
        api_keys=api_keys,
        tags=("fast",),
        priority=priority,
    )


class _RecordingProvider:
    """包装真实 provider，记录路由层每次调用的候选 id 与是否携带 reasoning_effort。"""

    def __init__(
        self,
        inner: OpenAICompatibleLLMProvider,
        model_id: str,
        calls: list[str],
    ) -> None:
        self._inner = inner
        self.model_id = model_id
        self.calls = calls
        self.saw_reasoning_effort: list[bool] = []

    def generate(
        self,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> LLMReply:
        self.saw_reasoning_effort.append("reasoning_effort" in kwargs)
        self.calls.append(self.model_id)
        return self._inner.generate(messages, **kwargs)


def _httpx_router(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
    specs: list[ModelSpec],
) -> tuple[ModelRouter, list[_RecordingProvider], list[str]]:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    monkeypatch.setattr(providers_module, "_shared_http_client", lambda proxy="": client)
    calls: list[str] = []
    wrappers: list[_RecordingProvider] = []

    def factory(spec: ModelSpec) -> _RecordingProvider:
        inner = OpenAICompatibleLLMProvider(
            api_key=spec.api_key,
            model=spec.model,
            base_url=spec.base_url,
        )
        wrapper = _RecordingProvider(inner, spec.model_id, calls)
        wrappers.append(wrapper)
        return wrapper

    router = ModelRouter(
        {spec.model_id: spec for spec in specs},
        provider_factory=factory,  # type: ignore[arg-type]
    )
    return router, wrappers, calls


# ==================== 分类矩阵：状态码与响应体语义 ====================


@pytest.mark.parametrize(
    ("status_code", "body", "expected"),
    [
        # 明确的参数拒绝（英文措辞）→ 去参重试类别。
        (400, '{"error":{"message":"unsupported parameter: reasoning_effort"}}', "unsupported_parameter"),
        # 中文措辞的参数拒绝：无英文标记命中，归渠道相关 bad_request 兜底
        # （同样在去参重试类别内，措辞漂移不再把渠道打成单点）。
        (400, '{"error":{"message":"参数 reasoning_effort 不受支持"}}', "bad_request"),
        # 上下文超限（OpenAI 英文原文措辞）：可转移类别，不做去参重试死磕。
        (
            400,
            ("This model's maximum context length is 4097 tokens. "
             "However, your messages resulted in 5000 tokens."),
            "bad_request",
        ),
        # "Bad Request" 措辞命中 invalid_request 标记（同属去参重试类别）。
        (400, '{"error":{"message":"Bad Request"}}', "invalid_request"),
        # 未知 400 / 冷门 4xx：无任何标记命中，归渠道相关 bad_request 兜底。
        (400, '{"error":{"message":"request rejected"}}', "bad_request"),
        (418, "teapot", "bad_request"),
        # 参数字段变化的 422 也按参数类别收编。
        (422, '{"error":{"message":"invalid parameter: temperature"}}', "unsupported_parameter"),
        # 鉴权/限流/服务端：状态码优先于响应体语义。
        (401, "", "auth"),
        (403, "", "auth"),
        # 对抗措辞：401/403 即使携带参数类关键词也不得升级为可去参重试。
        (401, '{"error":{"message":"unsupported parameter"}}', "auth"),
        (403, "unknown parameter", "auth"),
        (429, "", "rate_limited"),
        (500, "", "server"),
        (502, "bad gateway", "server"),
        (599, "relay exploded", "server"),
    ],
)
def test_classify_http_error_matrix(
    status_code: int, body: str, expected: str
) -> None:
    assert _classify_http_error(status_code, body) == expected


# ==================== 消费侧决策：故障转移与去参重试类别 ====================


@pytest.mark.parametrize(
    "error_kind",
    [
        "timeout",
        "network",
        "server",
        "rate_limited",
        "provider_error",
        "empty_response",
        "model_not_found",
        "unsupported_model",
        "bad_request",
        "invalid_request",
        "unsupported_parameter",
        "http",
        "auth",
        "schema",
    ],
)
def test_failoverable_kinds_decision(error_kind: str) -> None:
    assert should_failover(error_kind)


@pytest.mark.parametrize("error_kind", ["config_missing", "provider_not_configured"])
def test_fatal_kinds_do_not_failover(error_kind: str) -> None:
    assert not should_failover(error_kind)


def test_param_strip_retry_kinds_extend_mechanism_without_auth() -> None:
    """去参重试沿用既有机制扩展；鉴权失败绝不进入该重试循环。"""
    assert _PARAM_STRIP_RETRY_KINDS == {
        "unsupported_parameter",
        "bad_request",
        "invalid_request",
    }
    assert "auth" not in _PARAM_STRIP_RETRY_KINDS
    assert "server" not in _PARAM_STRIP_RETRY_KINDS
    assert "rate_limited" not in _PARAM_STRIP_RETRY_KINDS


# ==================== 端到端：中转站 400 → 分类 → 路由决策 ====================


def test_chinese_unsupported_parameter_400_strips_and_retries_same_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """中文措辞的参数拒绝：同渠道去参重试成功，而不是放弃该渠道。"""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if "reasoning_effort" in payload:
            return httpx.Response(
                400,
                json={"error": {"message": "参数 reasoning_effort 不受支持"}},
            )
        return httpx.Response(200, json=_chat_completion("ok-without-param"))

    router, wrappers, calls = _httpx_router(
        monkeypatch, handler, [_spec("first", 1)]
    )

    reply = router.generate(
        [{"role": "user", "content": "hello"}],
        message_text="hello",
        reasoning_effort="high",
    )

    assert reply.text == "ok-without-param"
    assert calls == ["first", "first"]
    assert wrappers[0].saw_reasoning_effort == [True, False]
    assert router.last_attempts == ["first:success_without_reasoning"]


def test_context_length_400_without_reasoning_effort_fails_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上下文超限 400（去参也救不了）直接转移下一候选。"""
    body = (
        "This model's maximum context length is 4097 tokens. "
        "However, your messages resulted in 5000 tokens."
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload.get("model") == "second":
            return httpx.Response(200, json=_chat_completion("ok:second"))
        return httpx.Response(400, json={"error": {"message": body}})

    router, _wrappers, calls = _httpx_router(
        monkeypatch,
        handler,
        [_spec("first", 1), _spec("second", 2)],
    )

    reply = router.generate(
        [{"role": "user", "content": "hello"}], message_text="hello"
    )

    assert reply.text == "ok:second"
    assert calls == ["first", "second"]
    assert router.last_attempts == ["first:bad_request", "second:success"]


def test_unknown_400_gets_one_strip_retry_then_fails_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知措辞的 400：携带 reasoning_effort 时先去参重试一次，无效再转移。"""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload.get("model") == "second":
            return httpx.Response(200, json=_chat_completion("ok:second"))
        return httpx.Response(400, json={"error": {"message": "request rejected"}})

    router, wrappers, calls = _httpx_router(
        monkeypatch,
        handler,
        [_spec("first", 1), _spec("second", 2)],
    )

    reply = router.generate(
        [{"role": "user", "content": "hello"}],
        message_text="hello",
        reasoning_effort="high",
    )

    assert reply.text == "ok:second"
    assert calls == ["first", "first", "second"]
    assert wrappers[0].saw_reasoning_effort == [True, False]
    assert router.last_attempts == ["first:bad_request", "second:success"]


def test_auth_401_never_strip_retried_and_never_retries_same_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """401 判死当前尝试：不去参重试、不重试同一把 key，只按密钥列表轮换一次。"""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload.get("model") == "second":
            return httpx.Response(200, json=_chat_completion("ok:second"))
        # 对抗措辞：错误体携带参数类关键词，也不得把 401 升级进去参重试。
        return httpx.Response(
            401,
            json={"error": {"message": "unsupported parameter in request"}},
        )

    router, wrappers, calls = _httpx_router(
        monkeypatch,
        handler,
        [
            _spec("first", 1, api_key="k1", api_keys=("k1", "k2")),
            _spec("second", 2),
        ],
    )

    reply = router.generate(
        [{"role": "user", "content": "hello"}],
        message_text="hello",
        reasoning_effort="high",
    )

    assert reply.text == "ok:second"
    # first 的两把 key 各试一次（不重复），随后转移 second；每把 key 的
    # 失败各留一条 attempts 记号。
    assert calls == ["first", "first", "second"]
    first_wrappers = [w for w in wrappers if w.model_id == "first"]
    assert len(first_wrappers) == 2
    for wrapper in first_wrappers:
        # 401 不触发去参重试：每次调用都带着原参数。
        assert wrapper.saw_reasoning_effort == [True]
    assert router.last_attempts == [
        "first:auth",
        "first:auth",
        "second:success",
    ]


def test_server_5xx_fails_over_to_next_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload.get("model") == "second":
            return httpx.Response(200, json=_chat_completion("ok:second"))
        return httpx.Response(503, text="<html>upstream unavailable</html>")

    router, _wrappers, calls = _httpx_router(
        monkeypatch,
        handler,
        [_spec("first", 1), _spec("second", 2)],
    )

    reply = router.generate(
        [{"role": "user", "content": "hello"}], message_text="hello"
    )

    assert reply.text == "ok:second"
    assert calls == ["first", "second"]
    assert router.last_attempts == ["first:server", "second:success"]

"""管线检视第二轮 LLM 域回归（B-2 / B-5 收尾）。

覆盖：
- 去参重试泛化：渠道 4xx 措辞漂移（bad_request/invalid_request）且请求
  携带 reasoning_effort 时，先在同一渠道去参重试一次再进入故障转移；
- auth/schema 渠道相关可转移（死 key / 挑战页不再打死整条路由）；
- httpx 响应体限长（_read_stream_limited）与进程级客户端复用。
全部离线：provider 为假实现，不发起真实网络请求。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.llm.model_router import ModelRouter, ModelSpec
from plugins.bot_unified_runtime.llm.providers import (
    LLMProviderError,
    LLMReply,
    _classify_http_error,
    _read_stream_limited,
    _shared_http_client,
    should_failover,
)


class _StripAwareProvider:
    """首调按 failures 抛错；记录每次调用是否携带 reasoning_effort。

    ``strip_fixes`` 为真时，若本次调用未携带 reasoning_effort 则返回成功
    ——模拟「渠道只是不认识该参数，去参后即可用」。
    """

    def __init__(
        self,
        model_id: str,
        failures: dict[str, str],
        calls: list[str],
        *,
        strip_fixes: bool = False,
    ) -> None:
        self.model_id = model_id
        self.failures = failures
        self.calls = calls
        self.strip_fixes = strip_fixes
        self.saw_reasoning_effort: list[bool] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self.saw_reasoning_effort.append("reasoning_effort" in kwargs)
        self.calls.append(self.model_id)
        error_kind = self.failures.get(self.model_id)
        if error_kind:
            if self.strip_fixes and self.saw_reasoning_effort[-1] is False:
                self.failures.pop(self.model_id, None)
            else:
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


# ==================== 去参重试泛化（管线检视 #2） ====================


@pytest.mark.parametrize("error_kind", ["bad_request", "invalid_request"])
def test_generic_4xx_with_reasoning_effort_strips_and_retries_same_channel(
    error_kind: str,
) -> None:
    calls: list[str] = []
    provider = _StripAwareProvider(
        "first", {"first": error_kind}, calls, strip_fixes=True
    )

    router = ModelRouter(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        provider_factory=lambda spec: provider,
    )
    reply = router.generate(
        [{"role": "user", "content": "hello"}],
        message_text="hello",
        reasoning_effort="high",
    )

    assert reply.text == "ok:first"
    assert calls == ["first", "first"], "应在同一渠道去参重试，而非放弃该渠道"
    assert provider.saw_reasoning_effort == [True, False]
    assert router.last_attempts == ["first:success_without_reasoning"]


def test_unsupported_parameter_strip_retry_still_works() -> None:
    calls: list[str] = []
    provider = _StripAwareProvider(
        "first", {"first": "unsupported_parameter"}, calls, strip_fixes=True
    )

    router = ModelRouter(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        provider_factory=lambda spec: provider,
    )
    reply = router.generate(
        [{"role": "user", "content": "hello"}],
        message_text="hello",
        reasoning_effort="high",
    )

    assert reply.text == "ok:first"
    assert router.last_attempts == ["first:success_without_reasoning"]


def test_generic_4xx_without_reasoning_effort_fails_over() -> None:
    calls: list[str] = []
    failures = {"first": "bad_request"}

    class _Kind400:
        def __init__(self, model_id: str) -> None:
            self.model_id = model_id

        def generate(
            self, messages: list[dict[str, str]], **kwargs: object
        ) -> LLMReply:
            calls.append(self.model_id)
            error_kind = failures.get(self.model_id)
            if error_kind:
                raise LLMProviderError("拒绝", error_kind=error_kind)
            return LLMReply(text=f"ok:{self.model_id}", provider="fake", model=self.model_id)

    router = ModelRouter(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        provider_factory=lambda spec: _Kind400(spec.model_id),
    )
    reply = router.generate(
        [{"role": "user", "content": "hello"}], message_text="hello"
    )

    assert reply.text == "ok:second"
    assert calls == ["first", "second"]


# ==================== auth / schema 渠道相关可转移 ====================


def test_auth_and_schema_are_failoverable_kinds() -> None:
    assert should_failover("auth")
    assert should_failover("schema")
    assert not should_failover("config_missing")


class _KindProvider:
    def __init__(
        self, model_id: str, failures: dict[str, str], calls: list[str]
    ) -> None:
        self.model_id = model_id
        self.failures = failures
        self.calls = calls

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self.calls.append(self.model_id)
        error_kind = self.failures.get(self.model_id)
        if error_kind:
            raise LLMProviderError(error_kind, error_kind=error_kind)
        return LLMReply(text=f"ok:{self.model_id}", provider="fake", model=self.model_id)


@pytest.mark.parametrize("error_kind", ["auth", "schema"])
def test_dead_key_or_garbage_relay_does_not_kill_route(error_kind: str) -> None:
    calls: list[str] = []
    failures = {"first": error_kind}

    router = ModelRouter(
        {"first": _spec("first", 1), "second": _spec("second", 2)},
        provider_factory=lambda spec: _KindProvider(spec.model_id, failures, calls),
    )
    reply = router.generate(
        [{"role": "user", "content": "hello"}], message_text="hello"
    )

    assert reply.text == "ok:second"
    assert calls == ["first", "second"]


# ==================== B-5：响应限长与客户端复用 ====================


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def iter_bytes(self) -> object:
        return iter(self._chunks)


def test_read_stream_limited_rejects_oversized_body() -> None:
    big_chunk = b"x" * 1024
    response = _FakeStreamResponse([big_chunk] * 3)
    with pytest.raises(LLMProviderError):
        _read_stream_limited(response, 2 * 1024)  # type: ignore[arg-type]


def test_read_stream_limited_allows_body_under_limit() -> None:
    response = _FakeStreamResponse([b"ab", b"cd"])
    assert _read_stream_limited(response, 1024) == b"abcd"  # type: ignore[arg-type]


def test_shared_http_client_reused_per_proxy_key() -> None:
    first = _shared_http_client("")
    second = _shared_http_client("")
    proxied = _shared_http_client("http://127.0.0.1:7890")
    assert first is second
    assert proxied is not first


# ==================== B-2：分类器兜底语义 ====================


def test_classify_http_error_generic_4xx_is_channel_specific() -> None:
    # 中文措辞/未知格式的 400 也归入渠道相关 bad_request（可转移）。
    assert _classify_http_error(400, "参数错误：上下文长度超出限制") == "bad_request"
    assert _classify_http_error(422, "unknown field: reasoning_effort") in {
        "unsupported_parameter",
        "bad_request",
    }
    assert _classify_http_error(401, "") == "auth"
    assert _classify_http_error(429, "") == "rate_limited"
    assert _classify_http_error(503, "") == "server"

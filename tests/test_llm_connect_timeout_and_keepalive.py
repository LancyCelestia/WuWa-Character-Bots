"""LLM 出站超时与连接复用回归（2026-09-29 中转站间歇性超时不回复事故）。

与 `test_llm_loopback_direct.py`（同批事故的代理归属腿）互补，本件只管两件事：

1. **connect 快败的效力**：客户端级 `connect=5s` 必须在生产路径真的生效。
   历史形态是每请求 `timeout=<标量>`，httpx 会把 connect/read/write/pool 四档
   一起改成同一个值 ⇒ 建连也等满单跳预算（40s），链级 fail-fast 要 5 跳才认输。
   现算判据＝每请求传 `httpx.Timeout`，connect 恒短、read 等于本轮预算。
2. **空闲保活不与本机出口同档竞走**：Clash 对存量隧道的静默回收实测落在
   5–20s，而 httpx 缺省 `keepalive_expiry` 恰是 5.0s ⇒ 半开连接被池子交出
   去复用就挂到读超时。判据＝显式压到 2.0s。

另附 AST/源码结构锁：`client.stream(` 的 `timeout=` 不得回到标量传法。
全部离线：不建真实连接，靠构造参数与调用 kwargs 捕获。
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest

import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers as providers_module
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    _CONNECT_TIMEOUT_SECONDS,
    _HTTP_CLIENTS,
    _KEEPALIVE_EXPIRY_SECONDS,
    OpenAICompatibleLLMProvider,
)

_REMOTE_KEY = "http://connect-timeout-probe.invalid:9"


def _purge(key: str) -> None:
    client = _HTTP_CLIENTS.pop(key, None)
    if client is not None:
        client.close()


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.status_code = 200
        self._payload = payload

    def iter_bytes(self) -> Iterator[bytes]:
        yield self._payload


class _FakeClient:
    """捕获 `client.stream(...)` 的 kwargs，返回可读假响应。"""

    def __init__(self, payload: bytes = b'{"choices":[{"message":{"content":"ok"}}]}') -> None:
        self.stream_calls: list[dict[str, Any]] = []
        self._payload = payload

    @contextmanager
    def stream(self, method: str, url: str, **kwargs: Any) -> Any:
        self.stream_calls.append({"method": method, "url": url, **kwargs})
        yield _FakeResponse(self._payload)


def _provider_with(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> OpenAICompatibleLLMProvider:
    monkeypatch.setattr(providers_module, "_shared_http_client", lambda *a, **k: client)
    return OpenAICompatibleLLMProvider(
        api_key="test-key",
        model="model-a",
        base_url="https://relay.invalid/v1",
    )


# ==================== 客户端级：connect 与保活 ====================


def test_shared_client_pins_connect_and_keepalive_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """共享客户端必须同时钉住 connect 上限与低于出口回收窗的保活上限。"""
    real = httpx.Client
    captured: list[dict[str, Any]] = []

    def spy(**kwargs: Any) -> httpx.Client:
        captured.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(httpx, "Client", spy)
    assert _REMOTE_KEY not in _HTTP_CLIENTS
    try:
        providers_module._shared_http_client(_REMOTE_KEY)
        assert captured
        timeout = captured[0]["timeout"]
        limits = captured[0]["limits"]
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.connect == _CONNECT_TIMEOUT_SECONDS == 5.0
        assert limits.keepalive_expiry == _KEEPALIVE_EXPIRY_SECONDS == 2.0
    finally:
        _purge(_REMOTE_KEY)


# ==================== 每请求：只覆盖读预算 ====================


def test_per_request_timeout_keeps_connect_fast_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单跳 40s 预算下，connect 仍是 5s 快败、read 才是 40s。"""
    client = _FakeClient()
    provider = _provider_with(monkeypatch, client)

    provider._post_via_httpx(b"{}", {"Content-Type": "application/json"}, 40.0)

    assert len(client.stream_calls) == 1
    timeout = client.stream_calls[0]["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.read == 40.0
    assert timeout.connect == 5.0


def test_connect_budget_clamps_below_its_own_cap_when_hop_is_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """短预算腿（自适应收紧/探针）：connect 不得反超本轮预算。"""
    client = _FakeClient()
    provider = _provider_with(monkeypatch, client)

    provider._post_via_httpx(b"{}", {"Content-Type": "application/json"}, 2.0)

    timeout = client.stream_calls[0]["timeout"]
    assert timeout.read == 2.0
    assert timeout.connect == 2.0


def test_scalar_timeout_does_not_return_to_stream_call() -> None:
    """结构锁：`client.stream(` 的 timeout= 必须是 Timeout 变量，非标量形参。

    标量传法＝把 connect 一起改成读预算，本件两根判据同时失效且不报错，
    只有源码形态能拦住。
    """
    src = inspect.getsource(OpenAICompatibleLLMProvider._post_via_httpx)
    stream_call = src[src.index("client.stream(") :]
    stream_call = stream_call[: stream_call.index(") as response")]
    assert "timeout=stream_timeout" in stream_call
    assert "timeout=request_timeout" not in stream_call

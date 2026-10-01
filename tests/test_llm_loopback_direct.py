"""LLM 回环网关硬直连回归（2026-09-29 Clash 7890 拒连窗事故）。

- endpoint 指向 127.0.0.1/::1/localhost ⇒ 走 ``loopback:direct`` 桶：
  proxy=None 且 trust_env=False，环境变量与 Windows 系统代理不参与；
- 远端 endpoint 维持原语义：显式代理键透传、空代理键仍 trust_env=True
  （temporal 天气依赖空桶的环境回落，不得波及）；
- 渠道健康探针对回环目标同样旁路代理。
全部离线：不建真实连接，靠 httpx.Client 构造参数捕获断言。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Self

import httpx
import pytest

import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers as providers_module
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
    probe_entry,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    _HTTP_CLIENTS,
    _LOOPBACK_DIRECT_KEY,
    LLMProviderError,
    OpenAICompatibleLLMProvider,
    _loopback_endpoint,
    _shared_http_client,
)


def _chat_completion() -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _capture_httpx_client(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """换掉 httpx.Client 捕获构造参数，仍返回真 Client 供缓存语义复用。"""
    real = httpx.Client
    captured: list[dict[str, Any]] = []

    def spy(**kwargs: Any) -> httpx.Client:
        captured.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(httpx, "Client", spy)
    return captured


def _purge(key: str) -> None:
    client = _HTTP_CLIENTS.pop(key, None)
    if client is not None:
        client.close()


# ==================== 回环判定 ====================


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("http://127.0.0.1:8090/v1/chat/completions", True),
        ("http://localhost:8090/v1/chat/completions", True),
        ("http://[::1]:8090/v1/chat/completions", True),
        ("HTTP://127.0.0.1:8090/V1/CHAT/COMPLETIONS", True),
        ("https://example.test/v1/chat/completions", False),
        ("https://api.open-meteo.com/v1/forecast", False),
        ("", False),
        ("not a url", False),
    ],
)
def test_loopback_endpoint_detection(endpoint: str, expected: bool) -> None:
    assert _loopback_endpoint(endpoint) is expected


# ==================== 共享客户端分桶 ====================


def test_loopback_bucket_is_hard_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    """回环桶：proxy=None + trust_env=False，环境/系统代理不参与。"""
    captured = _capture_httpx_client(monkeypatch)
    assert _LOOPBACK_DIRECT_KEY not in _HTTP_CLIENTS
    try:
        client = _shared_http_client("http://127.0.0.1:7890", force_direct=True)
        assert _HTTP_CLIENTS[_LOOPBACK_DIRECT_KEY] is client
        # 同桶复用（连接池语义不回退）。
        assert _shared_http_client("", force_direct=True) is client
        assert captured
        assert captured[0]["proxy"] is None
        assert captured[0]["trust_env"] is False
    finally:
        _purge(_LOOPBACK_DIRECT_KEY)


def test_empty_proxy_bucket_keeps_trust_env_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空代理键（远端无代理）语义不回退：trust_env=True 保持环境回落。

    无条件 purge 空桶再验：既存用例（如 test_prfix_llm）会向进程级缓存
    留下 open 客户端，若只在 preexisting is None 时清理，本用例会被
    短路成零构造（09-30 席B 二分实证的顺序依赖红）。
    """
    captured = _capture_httpx_client(monkeypatch)
    preexisting = _HTTP_CLIENTS.pop("", None)
    if preexisting is not None:
        preexisting.close()
    try:
        _shared_http_client("")
        assert captured
        assert captured[0]["proxy"] is None
        assert captured[0]["trust_env"] is True
    finally:
        _purge("")


def test_explicit_proxy_bucket_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式代理键：proxy 透传、trust_env=True，行为零变化。"""
    captured = _capture_httpx_client(monkeypatch)
    key = "http://bucket-probe.invalid:9"
    try:
        _shared_http_client(key)
        assert captured
        assert captured[0]["proxy"] == key
        assert captured[0]["trust_env"] is True
    finally:
        _purge(key)


# ==================== 生产传输路由 ====================


def _routed_provider(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    proxy: str,
    *,
    seen: list[tuple[str, bool]],
) -> OpenAICompatibleLLMProvider:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_chat_completion())
        )
    )

    def spy(proxy_key: str = "", *, force_direct: bool = False) -> httpx.Client:
        seen.append((proxy_key, force_direct))
        return client

    monkeypatch.setattr(providers_module, "_shared_http_client", spy)
    return OpenAICompatibleLLMProvider(
        api_key="test-key",
        model="model-a",
        base_url=base_url,
        proxy=proxy,
    )


def test_production_loopback_routes_to_direct_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置了代理的渠道，endpoint 指向回环时也强制硬直连桶。"""
    seen: list[tuple[str, bool]] = []
    provider = _routed_provider(
        monkeypatch,
        base_url="http://127.0.0.1:8090/v1",
        proxy="http://127.0.0.1:7890",
        seen=seen,
    )

    reply = provider.generate([{"role": "user", "content": "hi"}])

    assert reply.text == "ok"
    # 产品要求＝这一跳被强制硬直连（force_direct=True）；代理键原样透传是
    # 既有语义（分桶在 _shared_http_client 内部按 force_direct 改判），不在此断言。
    assert [flag for _key, flag in seen] == [True]


def test_production_remote_keeps_proxy_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """远端 endpoint：代理键原样透传，不进回环桶。"""
    seen: list[tuple[str, bool]] = []
    provider = _routed_provider(
        monkeypatch,
        base_url="https://example.test/v1",
        proxy="http://127.0.0.1:7890",
        seen=seen,
    )

    provider.generate([{"role": "user", "content": "hi"}])

    assert seen == [("http://127.0.0.1:7890", False)]


# ==================== 渠道健康探针 ====================


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.text = ""

    def json(self) -> dict[str, Any]:
        return {}


def _probe_client_spy(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.append(kwargs)

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
            return _FakeResponse(200)

    monkeypatch.setattr(httpx, "Client", FakeClient)
    return captured


@pytest.mark.parametrize(
    ("base_url", "loopback"),
    [
        ("http://127.0.0.1:8090/v1", True),
        ("https://example.test/v1", False),
    ],
)
def test_channel_health_probe_proxy_semantics(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    loopback: bool,
) -> None:
    """探针：回环目标旁路代理硬直连；远端目标代理透传不变。"""
    captured = _probe_client_spy(monkeypatch)
    spec = SimpleNamespace(base_url=base_url, model="model-a", api_key="k")

    ok, _latency, err = probe_entry(
        spec,
        proxy="http://127.0.0.1:7890",
        timeout_seconds=5.0,
        api_key_override="k",
    )

    assert ok, err
    assert captured
    if loopback:
        assert captured[0]["proxy"] is None
        assert captured[0]["trust_env"] is False
    else:
        assert captured[0]["proxy"] == "http://127.0.0.1:7890"
        assert captured[0]["trust_env"] is True


def test_loopback_bucket_survives_across_providers() -> None:
    """回环桶跨 provider 复用同一实例（缓存键与代理值无关）。"""
    _purge(_LOOPBACK_DIRECT_KEY)
    try:
        first = OpenAICompatibleLLMProvider(
            api_key="k",
            model="m-1",
            base_url="http://127.0.0.1:8090/v1",
            proxy="http://127.0.0.1:7890",
        )
        second = OpenAICompatibleLLMProvider(
            api_key="k",
            model="m-2",
            base_url="http://localhost:8090/v1",
            proxy="",
        )
        # 构造期不建连（既有语义），传输期才落桶：直接调内部取桶。
        client_a = _shared_http_client(
            first.proxy, force_direct=_loopback_endpoint(first.endpoint_url)
        )
        client_b = _shared_http_client(
            second.proxy, force_direct=_loopback_endpoint(second.endpoint_url)
        )
        assert client_a is client_b
        assert _HTTP_CLIENTS[_LOOPBACK_DIRECT_KEY] is client_a
    finally:
        _purge(_LOOPBACK_DIRECT_KEY)


def test_llm_provider_error_kind_untouched() -> None:
    """守卫：本波不碰错误分类面（防手滑回归的哨兵断言）。"""
    assert LLMProviderError("x", error_kind="network").error_kind == "network"


# ==================== 异常原文 detail（W1-② 证据链） ====================


@pytest.mark.parametrize(
    ("exc", "expected_kind", "needle"),
    [
        (httpx.ConnectTimeout("timed out while connecting"), "network", "ConnectTimeout"),
        (httpx.ReadTimeout("the read operation timed out"), "timeout", "ReadTimeout"),
        (httpx.ConnectError("connection refused by peer"), "network", "ConnectError"),
        (
            httpx.RemoteProtocolError("server disconnected without sending a response"),
            "network",
            "RemoteProtocolError",
        ),
    ],
)
def test_transport_detail_carries_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    expected_kind: str,
    needle: str,
) -> None:
    """detail 携带底层异常原文缩略（≤200 字符），message 面保持不变。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        providers_module,
        "_shared_http_client",
        lambda proxy="", force_direct=False: client,
    )
    provider = OpenAICompatibleLLMProvider(
        api_key="test-key",
        model="model-a",
        base_url="https://example.test/v1",
        proxy="http://127.0.0.1:7890",
    )

    with pytest.raises(LLMProviderError) as raised:
        provider.generate([{"role": "user", "content": "hi"}])

    assert raised.value.error_kind == expected_kind
    assert needle in raised.value.detail
    assert len(raised.value.detail) <= 200


def test_detail_truncated_and_multiline_flattened() -> None:
    """多行异常折单行、超长截断 200（防日志爆行）。"""
    err = LLMProviderError(
        "LLM request timed out",
        error_kind="timeout",
        detail="ReadTimeout: line-one\nline-two  \nline-three" + "x" * 300,
    )
    assert "\n" not in err.detail
    assert len(err.detail) <= 200
    assert err.detail.startswith("ReadTimeout: line-one / line-two / line-three")

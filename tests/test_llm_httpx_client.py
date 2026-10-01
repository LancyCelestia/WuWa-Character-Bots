"""B-5（管线检视 #7）httpx.Client 进程级单例与响应限长回归。

- 单例惰性创建：构造 provider 不建立连接，首个请求才落 Client；
- 并发首建线程安全：多线程同时取同一代理维度的 Client 只建一个实例；
- 生产传输每次请求经 _shared_http_client 取共享实例（连接池复用）；
- 每请求超时映射到 httpx.Timeout(connect/read/write/pool)，语义不回退；
- 超大响应体 / 超大错误体被拒并归入可转移错误，绝不静默吞掉。
全部离线：httpx.MockTransport 模拟中转站；惰性/线程安全用例使用独立
探测代理键并在收尾关闭清理，不污染其他用例的客户端缓存。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import httpx
import pytest

import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers as providers_module
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    _HTTP_CLIENTS,
    _MAX_ERROR_BODY_BYTES,
    _MAX_RESPONSE_BYTES,
    LLMProviderError,
    OpenAICompatibleLLMProvider,
    _shared_http_client,
    should_failover,
)


def _chat_completion(text: str = "ok") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _mock_provider(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> OpenAICompatibleLLMProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    monkeypatch.setattr(
        providers_module, "_shared_http_client", lambda proxy="", **_kw: client
    )
    return OpenAICompatibleLLMProvider(
        api_key="test-key",
        model="model-a",
        base_url="https://example.test/v1",
    )


def _purge_probe_client(key: str) -> None:
    client = _HTTP_CLIENTS.pop(key, None)
    if client is not None:
        client.close()


# ==================== 单例：惰性创建与线程安全 ====================


def test_provider_construction_does_not_create_clients() -> None:
    """模块导入期与 provider 构造期都不得建立连接（惰性单例）。"""
    before = set(_HTTP_CLIENTS)
    for index in range(3):
        OpenAICompatibleLLMProvider(
            api_key="k",
            model=f"m-{index}",
            base_url="https://example.test/v1",
        )
    assert set(_HTTP_CLIENTS) == before


def test_shared_http_client_lazy_per_proxy_key() -> None:
    key = "http://lazy-probe.invalid:9"
    assert key not in _HTTP_CLIENTS
    try:
        client = _shared_http_client(key)
        assert isinstance(client, httpx.Client)
        assert _HTTP_CLIENTS[key] is client
        # 同键重复取用返回同一实例（连接池复用）。
        assert _shared_http_client(key) is client
    finally:
        _purge_probe_client(key)


def test_shared_http_client_buckets_by_proxy_key() -> None:
    """分桶语义：不同代理键各持独立 Client，代理与空代理互不串池。"""
    key_a = "http://bucket-a.invalid:9"
    key_b = "http://bucket-b.invalid:9"
    assert key_a not in _HTTP_CLIENTS and key_b not in _HTTP_CLIENTS
    # 空代理键是生产默认桶：若此前已存在则测试后原样归还。
    preexisting_direct = _HTTP_CLIENTS.get("")
    try:
        client_a = _shared_http_client(key_a)
        client_b = _shared_http_client(key_b)
        client_direct = _shared_http_client("")
        assert client_a is not client_b
        assert client_a is not client_direct
        assert client_b is not client_direct
        # 各桶内仍保持单例。
        assert _shared_http_client(key_a) is client_a
        assert _shared_http_client(key_b) is client_b
        assert _shared_http_client("") is client_direct
    finally:
        _purge_probe_client(key_a)
        _purge_probe_client(key_b)
        if preexisting_direct is None:
            _purge_probe_client("")


def test_shared_http_client_creation_is_thread_safe() -> None:
    """并发首建：工作线程同时取同一键，进程内只落一个 Client。"""
    key = "http://thread-probe.invalid:9"
    assert key not in _HTTP_CLIENTS
    workers = 8
    barrier = threading.Barrier(workers)
    results: list[httpx.Client] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait()
            client = _shared_http_client(key)
            with lock:
                results.append(client)
        except Exception as exc:  # noqa: BLE001 - 测试内收集即断言失败。
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        _purge_probe_client(key)
    assert not errors
    assert len(results) == workers
    assert len({id(client) for client in results}) == 1


def test_production_transport_reuses_shared_client_across_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生产传输每次请求经 _shared_http_client 取数，多次请求命中同一实例。"""
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_chat_completion())
        )
    )
    seen: list[httpx.Client] = []

    def spy(proxy: str = "", **_kw: object) -> httpx.Client:
        seen.append(client)
        return client

    monkeypatch.setattr(providers_module, "_shared_http_client", spy)
    provider = OpenAICompatibleLLMProvider(
        api_key="test-key",
        model="model-a",
        base_url="https://example.test/v1",
    )

    first = provider.generate([{"role": "user", "content": "hi"}])
    second = provider.generate([{"role": "user", "content": "hi"}])

    assert first.text == "ok"
    assert second.text == "ok"
    assert len(seen) == 2
    assert seen[0] is seen[1]


# ==================== 超时映射 ====================


def test_per_request_timeout_maps_to_httpx_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """调用方超时覆盖映射到 httpx.Timeout(connect/read)，默认值不回退。"""
    seen_timeouts: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_timeouts.append(request.extensions.get("timeout"))
        return httpx.Response(200, json=_chat_completion())

    provider = _mock_provider(monkeypatch, handler)

    provider.generate([{"role": "user", "content": "hi"}], timeout_seconds=5)
    override = seen_timeouts[0]
    assert isinstance(override, dict)
    assert override["connect"] == 5.0
    assert override["read"] == 5.0

    provider.generate([{"role": "user", "content": "hi"}])
    default = seen_timeouts[1]
    assert isinstance(default, dict)
    # 2026-09-29 断言翻转（同批事故根修）：本腿此前锁的是"connect 随读预算
    # 放大"＝标量传法把四档一起改成 30s，客户端那份 connect 快败从未生效。
    # 读预算照旧交调用方，connect 恒守快败上限。
    assert default["connect"] == providers_module._CONNECT_TIMEOUT_SECONDS
    assert default["read"] == provider.timeout_seconds


@pytest.mark.parametrize(
    ("exc", "expected_kind"),
    [
        (httpx.ConnectTimeout("boom"), "network"),
        (httpx.ReadTimeout("boom"), "timeout"),
        (httpx.ConnectError("boom"), "network"),
    ],
)
def test_transport_exception_kind_mapping(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    expected_kind: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    provider = _mock_provider(monkeypatch, handler)

    with pytest.raises(LLMProviderError) as raised:
        provider.generate([{"role": "user", "content": "hi"}])

    assert raised.value.error_kind == expected_kind
    assert should_failover(raised.value.error_kind)


# ==================== 响应体限长 ====================


def test_oversized_success_body_rejected_as_failoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (_MAX_RESPONSE_BYTES + 1))

    provider = _mock_provider(monkeypatch, handler)

    with pytest.raises(LLMProviderError) as raised:
        provider.generate([{"role": "user", "content": "hi"}])

    assert raised.value.error_kind == "provider_error"
    assert should_failover(raised.value.error_kind)


def test_oversized_error_body_rejected_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """错误体超限也按既有错误路径判为可转移，绝不静默吞掉。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=b"x" * (_MAX_ERROR_BODY_BYTES + 1))

    provider = _mock_provider(monkeypatch, handler)

    with pytest.raises(LLMProviderError) as raised:
        provider.generate([{"role": "user", "content": "hi"}])

    # 超限错误体被截断后仍按状态码分类（400→bad_request），
    # 不得因读体超限误判为 provider_error（掩盖真实状态码）。
    assert raised.value.error_kind == "bad_request"
    assert should_failover(raised.value.error_kind)

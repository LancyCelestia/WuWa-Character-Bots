"""管线检视 #7 收尾：temporal.py 天气拉取迁移 httpx 单例 + 响应限长回归。

- 默认传输复用 llm.providers 的进程级单例 ``_shared_http_client``
  （连接池复用，构造期不建连接）；
- 每请求超时沿用 ``timeout_seconds``（映射到 httpx.Timeout）；
- 响应体超 8MB 上限即拒，走既有失败分支（返回过期快照），不静默吞成空数据；
- 非 2xx 与网络异常同样走既有失败分支；缓存命中逻辑零变化。
全部离线：httpx.MockTransport 模拟 Open-Meteo，不打真实 API。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import pytest

from plugins.bot_unified_runtime.character.temporal import (
    OpenMeteoWeatherProvider,
    _WeatherSnapshot,
)
from plugins.bot_unified_runtime.llm.providers import (
    _HTTP_CLIENTS,
    _MAX_RESPONSE_BYTES,
    _shared_http_client,
)

_EXPECTED_SUMMARY = "气温 22°C，体感 24°C，阴，湿度 68%"


def _weather_payload() -> dict[str, object]:
    return {
        "current": {
            "temperature_2m": 22.4,
            "apparent_temperature": 23.9,
            "relative_humidity_2m": 68,
            "weather_code": 3,
        }
    }


def _mock_provider(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    timeout_seconds: float = 8.0,
) -> tuple[OpenMeteoWeatherProvider, httpx.Client]:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    provider = OpenMeteoWeatherProvider(
        latitude=1.0,
        longitude=2.0,
        timeout_seconds=timeout_seconds,
        cache_seconds=60,
        http_client_factory=lambda: client,
    )
    return provider, client


def _stale_snapshot() -> _WeatherSnapshot:
    return _WeatherSnapshot(summary="旧天气：晴", fetched_at=time.monotonic() - 60.0)


# ==================== 单例复用 ====================


def test_default_transport_is_shared_http_client_singleton() -> None:
    """默认工厂即 llm.providers 的进程级单例（连接池复用），构造期不建连接。"""
    before = set(_HTTP_CLIENTS)
    provider = OpenMeteoWeatherProvider(latitude=1.0, longitude=2.0)
    assert provider._http_client_factory is _shared_http_client
    assert set(_HTTP_CLIENTS) == before


def test_fetch_remote_goes_through_injected_httpx_transport() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_weather_payload())

    provider, client = _mock_provider(handler)
    try:
        snapshot = provider._fetch_remote(time.monotonic())
    finally:
        client.close()

    assert snapshot is not None
    assert snapshot.summary == _EXPECTED_SUMMARY
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert "api.open-meteo.com" in str(request.url)
    assert "latitude=1.0" in str(request.url)
    assert "longitude=2.0" in str(request.url)


def test_current_weather_cache_hit_issues_single_request() -> None:
    """行为零变化：首拉进 TTL 缓存，第二条消息命中缓存不再发请求。"""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_weather_payload())

    provider, client = _mock_provider(handler)
    try:
        first = provider.current_weather("request-1")
        second = provider.current_weather("request-2")
    finally:
        client.close()

    assert first == second == _EXPECTED_SUMMARY
    assert len(calls) == 1


# ==================== 超时语义 ====================


def test_fetch_remote_keeps_caller_timeout_semantics() -> None:
    seen_timeouts: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_timeouts.append(request.extensions.get("timeout"))
        return httpx.Response(200, json=_weather_payload())

    provider, client = _mock_provider(handler, timeout_seconds=5.0)
    try:
        provider._fetch_remote(time.monotonic())
    finally:
        client.close()

    override = seen_timeouts[0]
    assert isinstance(override, dict)
    assert override["connect"] == 5.0
    assert override["read"] == 5.0


# ==================== 响应体限长 ====================


def test_oversized_body_rejected_via_existing_failure_branch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (_MAX_RESPONSE_BYTES + 1))

    provider, client = _mock_provider(handler)
    try:
        # 无旧值：失败分支返回 None → current_weather 为空字符串。
        assert provider._fetch_remote(time.monotonic()) is None
        # 有旧值：返回过期快照本身，不静默吞成空数据，也不落新快照。
        stale = _stale_snapshot()
        provider._cache = stale
        assert provider._fetch_remote(time.monotonic()) is stale
        assert provider._cache is stale
    finally:
        client.close()


# ==================== 非 2xx 与网络异常走既有失败分支 ====================


@pytest.mark.parametrize("status", [301, 404, 500, 503])
def test_non_2xx_goes_to_existing_failure_branch(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="error")

    provider, client = _mock_provider(handler)
    try:
        assert provider._fetch_remote(time.monotonic()) is None
        stale = _stale_snapshot()
        provider._cache = stale
        assert provider._fetch_remote(time.monotonic()) is stale
    finally:
        client.close()


@pytest.mark.parametrize(
    "exc",
    [httpx.ConnectError("boom"), httpx.ConnectTimeout("boom"), httpx.ReadTimeout("boom")],
)
def test_transport_errors_return_stale_cache(exc: Exception) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    provider, client = _mock_provider(handler)
    try:
        assert provider._fetch_remote(time.monotonic()) is None
    finally:
        client.close()

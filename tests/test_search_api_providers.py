from __future__ import annotations

import json
from types import SimpleNamespace

import httpx

from plugins.bot_unified_runtime.config import Config, translate_env_keys
from plugins.bot_unified_runtime.sources.web_search import (
    LangSearchWebSearchProvider,
    TavilyWebSearchProvider,
    TinyFishFetchProvider,
    YouSearchProvider,
    build_web_search_provider,
)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_tavily_provider_sends_configurable_json_and_normalizes_results():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["authorization"]
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"results": [{"title": "T", "url": "https://t.example", "content": "C"}]},
        )

    provider = TavilyWebSearchProvider(
        api_key="tavily-key",
        endpoint="https://tavily.test/search",
        options={"topic": "news", "include_answer": True},
        client=_client(handler),
    )

    hits = provider.search("latest", max_results=4)

    assert seen["authorization"] == "Bearer tavily-key"
    assert seen["payload"]["query"] == "latest"
    assert seen["payload"]["max_results"] == 4
    assert seen["payload"]["topic"] == "news"
    assert hits[0].title == "T"
    assert hits[0].snippet == "C"


def test_you_provider_uses_post_and_x_api_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["key"] = request.headers["X-API-Key"]
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"results": [{"title": "Y", "url": "https://y.example", "description": "D"}]},
        )

    provider = YouSearchProvider(
        api_key="you-key",
        endpoint="https://you.test/v1/search",
        options={"freshness": "week"},
        client=_client(handler),
    )

    hits = provider.search("query", max_results=3)

    assert seen == {
        "method": "POST",
        "key": "you-key",
        "payload": {"query": "query", "count": 3, "freshness": "week"},
    }
    assert hits[0].snippet == "D"


def test_langsearch_provider_normalizes_nested_web_pages_response():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "webPages": {
                        "value": [
                            {"name": "L", "url": "https://l.example", "snippet": "S"}
                        ]
                    }
                }
            },
        )

    provider = LangSearchWebSearchProvider(
        api_key="lang-key",
        endpoint="https://lang.test/v1/web-search",
        client=_client(handler),
    )

    hits = provider.search("query", max_results=2)

    assert hits[0].title == "L"
    assert hits[0].snippet == "S"


def test_tinyfish_fetch_provider_returns正文_without_network_dependency():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "tiny-key"
        assert json.loads(request.content)["url"] == "https://source.example/article"
        return httpx.Response(200, json={"content": "正文内容"})

    provider = TinyFishFetchProvider(
        api_key="tiny-key",
        endpoint="https://tiny.test/fetch",
        client=_client(handler),
    )

    assert provider.fetch_page_text("https://source.example/article", max_chars=20) == "正文内容"


def test_provider_retries_transient_transport_error_then_succeeds():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("transient", request=request)
        return httpx.Response(
            200,
            json={"results": [{"title": "T", "url": "https://t.example", "content": "C"}]},
        )

    provider = TavilyWebSearchProvider(
        api_key="tavily-key",
        endpoint="https://tavily.test/search",
        client=_client(handler),
        retry_attempts=1,
        retry_backoff_seconds=0.0,
    )

    hits = provider.search("q", max_results=2)

    assert calls["count"] == 2
    assert hits[0].title == "T"


def test_provider_does_not_retry_http_status_errors():
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500, json={"error": "server"})

    provider = TavilyWebSearchProvider(
        api_key="tavily-key",
        endpoint="https://tavily.test/search",
        client=_client(handler),
        retry_attempts=2,
        retry_backoff_seconds=0.0,
    )

    assert provider.search("q", max_results=2) == []
    assert calls["count"] == 1


def test_builder_uses_tavily_you_langsearch_and_excludes_bing():
    config = SimpleNamespace(
        bot_web_search_enabled=True,
        bot_web_search_provider="tavily",
        bot_web_search_fallback_providers=["you", "langsearch"],
        bot_web_search_timeout_seconds=3,
        bot_download_proxy="",
        bot_web_search_tavily_api_key="tavily",
        bot_web_search_you_api_key="you",
        bot_web_search_langsearch_api_key="lang",
        bot_web_search_tinyfish_api_key="tiny",
        bot_web_search_provider_options={},
    )
    provider = build_web_search_provider(config)

    assert [item.name for item in provider.providers] == ["tavily", "you", "langsearch"]
    assert all(item.name != "bing" for item in provider.providers)

def test_search_config_parses_json_and_env_key_references():
    config = Config.model_validate(
        translate_env_keys(
            {
                "BOT_WEB_SEARCH_PROVIDER": "tavily",
                "BOT_WEB_SEARCH_FALLBACK_PROVIDERS": "[\"you\",\"langsearch\"]",
                "BOT_WEB_SEARCH_PROVIDER_OPTIONS": "{\"tavily\":{\"topic\":\"news\"}}",
                "BOT_WEB_SEARCH_TAVILY_API_KEY": "env:BOT_SEARCH_TAVILY_API_KEY",
                "BOT_SEARCH_TAVILY_API_KEY": "local-tavily-key",
            }
        )
    )

    assert config.bot_web_search_fallback_providers == ["you", "langsearch"]
    assert config.bot_web_search_provider_options == {"tavily": {"topic": "news"}}
    assert config.bot_search_tavily_api_key == "local-tavily-key"

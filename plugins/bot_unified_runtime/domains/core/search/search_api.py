"""Configurable search API adapters used by the unified web search chain."""

from __future__ import annotations

import os
import time
import urllib.parse
from collections.abc import Mapping
from typing import Any

import httpx

from plugins.bot_unified_runtime.domains.core.search.web_search import WebSearchHit

_DEFAULT_ENDPOINTS = {
    "tavily": "https://api.tavily.com/search",
    "you": "https://api.you.com/v1/search",
    "tinyfish": "https://api.search.tinyfish.ai",
    "langsearch": "https://api.langsearch.com/v1/web-search",
}


def resolve_search_secret(value: object, config: object | None = None) -> str:
    text = str(value or "").strip()
    if not text.lower().startswith("env:"):
        return text
    env_name = text[4:].strip()
    if not env_name:
        return ""
    env_value = os.environ.get(env_name, "")
    if env_value:
        return env_value
    if config is not None:
        return str(getattr(config, env_name.lower(), "") or "").strip()
    return ""


def _safe_options(options: object) -> dict[str, Any]:
    return dict(options) if isinstance(options, Mapping) else {}


def _headers(options: Mapping[str, Any], api_key: str, scheme: str) -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if api_key:
        if scheme == "x-api-key":
            headers["X-API-Key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"
    custom = options.get("headers")
    if isinstance(custom, Mapping):
        headers.update({str(key): str(value) for key, value in custom.items()})
    return headers


def _request_overrides(options: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    params = options.get("params")
    body = options.get("body")
    return (
        dict(params) if isinstance(params, Mapping) else {},
        dict(body) if isinstance(body, Mapping) else {},
    )


def _find_result_items(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    preferred_keys = (
        "results",
        "items",
        "organic_results",
        "webPages",
        "web_pages",
        "value",
        "data",
    )
    for key in preferred_keys:
        value = payload.get(key)
        if isinstance(value, list):
            items = [item for item in value if isinstance(item, Mapping)]
            if items:
                return items
        if isinstance(value, Mapping):
            items = _find_result_items(value)
            if items:
                return items
    for value in payload.values():
        items = _find_result_items(value)
        if items:
            return items
    return []


def _first_text(item: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            parts = [str(part).strip() for part in value if str(part).strip()]
            if parts:
                return " ".join(parts)
    return ""


def _first_scalar(item: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    """`_first_text` 的标量版：额外接受数字/布尔形态的时间戳（各家写法不一）。"""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


#: 结果条目里「来源域名」的候选键（各家叫法不一：Tavily ``display_status`` 无、
#: Serp/Bing 形 ``displayLink``、You 形 ``channel``…）。**只登记真实回传字段**，
#: 拿不到就由 URL 现推（``_domain_from_url``），绝不写死一个假域名冒充来源。
_SOURCE_DOMAIN_KEYS = ("source_domain", "displayLink", "site_name", "siteName", "hostname", "host")

#: 结果条目里「发布时间」的候选键。同为**只取源站回传值**：缺字段就留空串，
#: 不许拿抓取时刻顶替（``search_service`` 对 ``published_at`` 同一条纪律，此处不另立口径）。
_PUBLISHED_AT_KEYS = (
    "published_at",
    "publishedAt",
    "published_date",
    "publishedDate",
    "page_age",
    "time_last_updated",
    "last_updated",
    "first_published",
    "timestamp",
)


def _domain_from_url(url: str) -> str:
    """由 URL 现推裸域名（小写、去端口、去 userinfo、去单一 ``www.`` 前缀）。

    为什么这一层必须由检索链自己做：``normalize_search_results`` 过去只造
    ``WebSearchHit(title, snippet, url)``，``source_domain`` 恒为空串，于是
    ``source_authority.authority_tier("")`` 一律 ``TIER_UNKNOWN``、``_is_junk``
    的域名字典闸永不命中、按域来源优先级表与 prompt 的 ``-[域名]`` 前缀全部失明
    ——「权威源优先」在生产 key 主链上等于没接（免 key 的 DDG/Bing 两家自己填了
    域名，所以这条只在有 key 的链上塌）。留空 ``www.`` 剥离是刻意的窄口径：
    只剥这一枚最常见前缀，不做任意子串处理，避免把 ``wwwharmful.example`` 这类
    畸形域洗成看起来干净的形状。
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        netloc = urllib.parse.urlsplit(raw).netloc
    except ValueError:
        return ""
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[1]
    netloc = netloc.split(":", 1)[0].strip(".").lower()
    return netloc.removeprefix("www.")


def normalize_search_results(payload: object, *, max_results: int) -> list[WebSearchHit]:
    hits: list[WebSearchHit] = []
    seen: set[str] = set()
    for item in _find_result_items(payload):
        url = _first_text(item, ("url", "link", "href"))
        if not url or not url.startswith(("http://", "https://")):
            continue
        title = _first_text(item, ("title", "name", "heading")) or url
        snippet = _first_text(
            item,
            ("content", "snippet", "description", "text", "summary", "raw_content"),
        )
        # 域名两把尺：源站自己报的用源站的，报了就现推——两者都没有才留空串。
        source_domain = _first_text(item, _SOURCE_DOMAIN_KEYS) or _domain_from_url(url)
        # 发布时间只透传、不解析、不推断：空串＝源站没给，排序层据此判「无日期」。
        published_at = _first_scalar(item, _PUBLISHED_AT_KEYS)
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        hits.append(
            WebSearchHit(
                title=title,
                snippet=snippet,
                url=url,
                source_domain=source_domain,
                published_at=published_at,
            )
        )
        if len(hits) >= max(1, int(max_results)):
            break
    return hits



def extract_page_text(payload: object) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, Mapping):
        for key in ("content", "markdown", "text", "body", "data", "result", "raw_content", "results"):
            value = payload.get(key)
            text = extract_page_text(value)
            if text:
                return text
    if isinstance(payload, list):
        for value in payload:
            text = extract_page_text(value)
            if text:
                return text
    return ""


class _JsonSearchProvider:
    scheme = "bearer"
    method = "POST"
    #: 声明本 provider 是否接受**请求级** body 追加层（``extra_body``）。缺省 False＝
    #: 检索链对它绝不开该通道；只有声明了参数形态的 Tavily 类置 True
    #: （WEBCFG-AUDIT E-3：time_range 是 Tavily 的请求级旋钮，其余引擎结构上无此参数）。
    accepts_extra_body = False

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        timeout_seconds: float = 6.0,
        proxy: str = "",
        options: Mapping[str, Any] | None = None,
        client: httpx.Client | None = None,
        retry_attempts: int = 1,
        retry_backoff_seconds: float = 0.25,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.endpoint = str(endpoint or "").strip()
        self.timeout_seconds = max(0.5, float(timeout_seconds))
        self.proxy = str(proxy or "").strip()
        self.options = _safe_options(options or {})
        self._client = client
        self.retry_attempts = max(0, int(retry_attempts))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))

    def _client_or_create(self) -> tuple[httpx.Client, bool]:
        if self._client is not None:
            return self._client, False
        return (
            httpx.Client(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=True,
                proxy=self.proxy or None,
            ),
            True,
        )

    def _request_json(
        self,
        query: str,
        max_results: int,
        body_override: Mapping[str, Any] | None = None,
    ) -> object:
        if not self.api_key or not self.endpoint or not query.strip():
            return {}
        client, owned = self._client_or_create()
        try:
            params, body_overrides = _request_overrides(self.options)
            body = self._build_body(query, max_results)
            body.update({key: value for key, value in self.options.items() if key not in {"headers", "params", "body"}})
            body.update(body_overrides)
            if body_override:
                body.update(body_override)
            attempts = self.retry_attempts
            for attempt in range(attempts + 1):
                try:
                    response = client.request(
                        self.method,
                        self.endpoint,
                        headers=_headers(self.options, self.api_key, self.scheme),
                        params=(body if self.method == "GET" else params) or None,
                        json=body if self.method == "POST" else None,
                    )
                    response.raise_for_status()
                    return response.json()
                except httpx.TransportError:
                    # 超时/连接抖动原地短重试；HTTP 状态错误直接交给链式回退。
                    if attempt >= attempts:
                        return {}
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
        except Exception:  # noqa: BLE001 - provider failure is handled by chain fallback.
            return {}
        finally:
            if owned:
                client.close()
        return {}

    def _build_body(self, query: str, max_results: int) -> dict[str, Any]:
        return {"query": query, "max_results": max(1, int(max_results))}

    def search(
        self,
        query: str,
        *,
        max_results: int = 3,
        extra_body: Mapping[str, Any] | None = None,
    ) -> list[WebSearchHit]:
        # ``extra_body``＝请求级最后合并层（盖过装配期烘档值），仅对声明
        # ``accepts_extra_body`` 的形态由链注入；None＝逐字节现状。
        return normalize_search_results(
            self._request_json(query, max_results, body_override=extra_body),
            max_results=max_results,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


class TavilyWebSearchProvider(_JsonSearchProvider):
    name = "tavily"
    #: Tavily 请求体认 ``time_range``（day/week/month/year）——链级时效窗
    #: 唯一可注入的引擎形态（缺省 False 的基类声明见 ``_JsonSearchProvider``）。
    accepts_extra_body = True

    def _build_body(self, query: str, max_results: int) -> dict[str, Any]:
        return {"query": query, "max_results": max(1, int(max_results))}

    def image_urls(self, query: str, *, max_results: int = 8) -> list[str]:
        """图搜通道（include_images=True）：按 API 给序返回图片直链候选。

        响应 images 项兼容两种形态：纯 URL 字符串与 {url: ...} 对象；
        未配 key / 网络 / 解析失败一律返回空表，由调用方走候选降级链。
        """
        payload = self._request_json(
            query, max_results, body_override={"include_images": True}
        )
        if not isinstance(payload, Mapping):
            return []
        raw = payload.get("images")
        if not isinstance(raw, list):
            return []
        urls: list[str] = []
        for item in raw:
            if isinstance(item, str):
                url = item.strip()
            elif isinstance(item, Mapping):
                url = str(item.get("url") or "").strip()
            else:
                continue
            if url:
                urls.append(url)
        return urls[: max(1, int(max_results))]


class YouSearchProvider(_JsonSearchProvider):
    name = "you"
    scheme = "x-api-key"

    def _build_body(self, query: str, max_results: int) -> dict[str, Any]:
        return {"query": query, "count": max(1, int(max_results))}


class LangSearchWebSearchProvider(_JsonSearchProvider):
    name = "langsearch"

    def _build_body(self, query: str, max_results: int) -> dict[str, Any]:
        return {"query": query, "count": max(1, int(max_results))}


class TinyFishWebSearchProvider(_JsonSearchProvider):
    name = "tinyfish"
    scheme = "x-api-key"
    method = "GET"

    def _build_body(self, query: str, max_results: int) -> dict[str, Any]:
        return {"query": query, "page": 1, "count": max(1, int(max_results))}


class TinyFishFetchProvider:
    name = "tinyfish-fetch"

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        timeout_seconds: float = 15.0,
        proxy: str = "",
        options: Mapping[str, Any] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.endpoint = str(endpoint or "").strip()
        self.timeout_seconds = max(0.5, float(timeout_seconds))
        self.proxy = str(proxy or "").strip()
        self.options = _safe_options(options or {})
        self._client = client

    def fetch_page_text(self, url: str, *, max_chars: int = 3000) -> str:
        if not self.api_key or not self.endpoint or not url.startswith(("http://", "https://")):
            return ""
        client = self._client or httpx.Client(
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=True,
            proxy=self.proxy or None,
        )
        owned = self._client is None
        try:
            params, body_overrides = _request_overrides(self.options)
            # TinyFish Fetch API：POST https://api.fetch.tinyfish.ai，body {"urls": [...]}，
            # results[].text 为提取正文（errors[] 逐 URL 报错不影响其余）。
            body = {"urls": [url], "format": "markdown"}
            body.update({key: value for key, value in self.options.items() if key not in {"headers", "params", "body"}})
            body.update(body_overrides)
            response = client.post(
                self.endpoint,
                headers=_headers(self.options, self.api_key, "x-api-key"),
                params=params or None,
                json=body,
            )
            response.raise_for_status()
            return extract_page_text(response.json())[: max(1, int(max_chars))]
        except Exception:  # noqa: BLE001 -正文抓取失败由上层回退通用抓取。
            return ""
        finally:
            if owned:
                client.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


class TavilyExtractFetchProvider:
    """Tavily extract 正文抓取：TinyFish 之后的抓取回退，复用同一 Tavily key。"""

    name = "tavily-extract"
    scheme = "bearer"

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = "https://api.tavily.com/extract",
        timeout_seconds: float = 15.0,
        proxy: str = "",
        options: Mapping[str, Any] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.endpoint = str(endpoint or "").strip()
        self.timeout_seconds = max(0.5, float(timeout_seconds))
        self.proxy = str(proxy or "").strip()
        self.options = _safe_options(options or {})
        self._client = client

    def fetch_page_text(self, url: str, *, max_chars: int = 3000) -> str:
        if not self.api_key or not self.endpoint or not url.startswith(("http://", "https://")):
            return ""
        client = self._client or httpx.Client(
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=True,
            proxy=self.proxy or None,
        )
        owned = self._client is None
        try:
            params, body_overrides = _request_overrides(self.options)
            body = {"urls": [url]}
            body.update({key: value for key, value in self.options.items() if key not in {"headers", "params", "body"}})
            body.update(body_overrides)
            response = client.post(
                self.endpoint,
                headers=_headers(self.options, self.api_key, self.scheme),
                params=params or None,
                json=body,
            )
            response.raise_for_status()
            return extract_page_text(response.json())[: max(1, int(max_chars))]
        except Exception:  # noqa: BLE001 - 抓取失败由上层回退通用抓取。
            return ""
        finally:
            if owned:
                client.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


class CompositePageFetchProvider:
    """按顺序尝试多个正文抓取器，任一命中即返回；全部失败再走通用抓取。"""

    name = "composite-fetch"

    def __init__(self, fetchers: list[Any]) -> None:
        self.fetchers = [fetcher for fetcher in fetchers if fetcher is not None]

    def fetch_page_text(self, url: str, *, max_chars: int = 3000) -> str:
        for fetcher in self.fetchers:
            try:
                text = str(fetcher.fetch_page_text(url, max_chars=max_chars) or "")
            except Exception:  # noqa: BLE001 - 单个抓取器失败回退下一个。
                text = ""
            if text:
                return text
        return ""

    def close(self) -> None:
        for fetcher in self.fetchers:
            close = getattr(fetcher, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001, S110 - 关闭失败忽略。
                    pass


def build_api_search_provider(
    config: object,
    *,
    timeout_seconds: float,
    proxy: str,
) -> tuple[
    list[_JsonSearchProvider],
    TinyFishFetchProvider | TavilyExtractFetchProvider | CompositePageFetchProvider | None,
]:
    primary = str(getattr(config, "bot_web_search_provider", "tavily") or "tavily").strip().lower()
    fallback = getattr(config, "bot_web_search_fallback_providers", ("you", "langsearch")) or ()
    names: list[str] = []
    for name in [primary, *fallback]:
        normalized = str(name).strip().lower()
        if normalized in {"tavily", "you", "tinyfish", "langsearch"} and normalized not in names:
            names.append(normalized)
    options_by_provider = getattr(config, "bot_web_search_provider_options", {}) or {}
    tavily_first_class = (
        ("search_depth", "bot_web_search_tavily_search_depth"),
        ("time_range", "bot_web_search_tavily_time_range"),
    )
    providers: list[_JsonSearchProvider] = []
    for name in names:
        provider_options = _safe_options(options_by_provider.get(name, {}) if isinstance(options_by_provider, Mapping) else {})
        if name == "tavily":
            for body_key, config_field in tavily_first_class:
                value = str(getattr(config, config_field, "") or "").strip()
                if value and body_key not in provider_options:
                    provider_options[body_key] = value
        key_value = provider_options.pop(
            "api_key",
            getattr(config, f"bot_web_search_{name}_api_key", ""),
        )
        endpoint = str(
            provider_options.pop(
                "endpoint",
                getattr(config, f"bot_web_search_{name}_endpoint", _DEFAULT_ENDPOINTS[name]),
            )
            or _DEFAULT_ENDPOINTS[name]
        )
        api_key = resolve_search_secret(key_value, config)
        provider_type = {
            "tavily": TavilyWebSearchProvider,
            "you": YouSearchProvider,
            "tinyfish": TinyFishWebSearchProvider,
            "langsearch": LangSearchWebSearchProvider,
        }[name]
        if api_key and endpoint:
            providers.append(
                provider_type(
                    api_key=api_key,
                    endpoint=endpoint,
                    timeout_seconds=timeout_seconds,
                    proxy=proxy,
                    options=provider_options,
                )
            )

    tinyfish_key = resolve_search_secret(
        getattr(config, "bot_web_search_tinyfish_api_key", ""), config
    )
    tinyfish_endpoint = str(
        getattr(config, "bot_web_search_tinyfish_fetch_endpoint", "") or ""
    ).strip()
    fetch_timeout = float(
        getattr(config, "bot_web_search_fetch_timeout_seconds", 15.0) or 15.0
    )
    fetchers: list[Any] = []
    if tinyfish_key and tinyfish_endpoint:
        fetchers.append(
            TinyFishFetchProvider(
                api_key=tinyfish_key,
                endpoint=tinyfish_endpoint,
                timeout_seconds=fetch_timeout,
                proxy=proxy,
                options=_safe_options(
                    options_by_provider.get("tinyfish_fetch", {})
                    if isinstance(options_by_provider, Mapping)
                    else {}
                ),
            )
        )
    if bool(getattr(config, "bot_web_search_tavily_extract_enabled", False)):
        tavily_key = resolve_search_secret(
            getattr(config, "bot_web_search_tavily_api_key", ""), config
        )
        tavily_extract_endpoint = str(
            getattr(config, "bot_web_search_tavily_extract_endpoint", "")
            or "https://api.tavily.com/extract"
        ).strip()
        if tavily_key and tavily_extract_endpoint:
            fetchers.append(
                TavilyExtractFetchProvider(
                    api_key=tavily_key,
                    endpoint=tavily_extract_endpoint,
                    timeout_seconds=fetch_timeout,
                    proxy=proxy,
                    options=_safe_options(
                        options_by_provider.get("tavily_extract", {})
                        if isinstance(options_by_provider, Mapping)
                        else {}
                    ),
                )
            )
    if not fetchers:
        return providers, None
    if len(fetchers) == 1:
        return providers, fetchers[0]
    return providers, CompositePageFetchProvider(fetchers)

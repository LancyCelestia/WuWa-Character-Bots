"""按需联网检索提供器（意图判定见 runtime/question_intent.py）。

- 默认关闭（BOT_WEB_SEARCH_ENABLED=false）；
- 支持代理（BOT_DOWNLOAD_PROXY，例如 http://127.0.0.1:7890），外网检索走代理；
- Tavily → You.com → LangSearch API 链式回退；TinyFish 可选用于正文抓取；不接 Bing；
- 传输层统一使用 httpx：同步路径用 ``httpx.Client``（keep-alive 连接池），
  异步路径用 ``httpx.AsyncClient``，供 stdio MCP 服务器等异步调用方使用；
- 单次超时短、失败静默降级为空，绝不拖慢对话。
"""

from __future__ import annotations

import asyncio
import html
import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

import httpx

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# 注释与隐藏块（含 head 元信息）是间接 Prompt 注入的常见载体，正文入 Prompt 前先剥离。
_HTML_HIDDEN_BLOCK_RE = re.compile(
    r"<(script|style|noscript|template|iframe|object|embed|svg)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_HTML_HEAD_BLOCK_RE = re.compile(r"<head[^>]*>.*?</head>", re.DOTALL | re.IGNORECASE)
# nav/footer/aside/form/dialog 是导航/页脚/侧栏/表单类样板块（去广告向），与注入隐藏块分开剥。
_HTML_BOILERPLATE_BLOCK_RE = re.compile(
    r"<(nav|footer|aside|form|dialog)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass(frozen=True)
class WebSearchHit:
    title: str
    snippet: str
    url: str
    source_domain: str = ""


class WebSearchProvider(Protocol):
    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        """返回过滤后的搜索命中；失败/超时返回空列表。"""


class NullWebSearchProvider:
    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        return []


def _proxy_value(proxy: str) -> str | None:
    """返回统一代理地址；httpx 0.28 起 proxy 参数用单值覆盖所有 scheme。"""
    proxy = str(proxy or "").strip()
    return proxy or None


def _build_sync_client(proxy: str, timeout_seconds: float) -> httpx.Client:
    """构建带 keep-alive 连接池的同步 httpx 客户端。

    测试可通过 monkeypatch 本函数注入假 transport 或伪造网络错误。
    """
    return httpx.Client(
        headers=dict(_DEFAULT_HEADERS),
        timeout=httpx.Timeout(float(timeout_seconds)),
        follow_redirects=True,
        proxy=_proxy_value(proxy),
    )


def _build_async_client(proxy: str, timeout_seconds: float) -> httpx.AsyncClient:
    """构建带 keep-alive 连接池的异步 httpx 客户端（测试可 monkeypatch 注入）。"""
    return httpx.AsyncClient(
        headers=dict(_DEFAULT_HEADERS),
        timeout=httpx.Timeout(float(timeout_seconds)),
        follow_redirects=True,
        proxy=_proxy_value(proxy),
    )


def _fetch(
    url: str,
    *,
    proxy: str,
    timeout_seconds: float,
    client: httpx.Client | None = None,
) -> str | None:
    """同步抓取页面文本；失败/超时静默返回 None，绝不向上抛网络异常。"""
    if not url:
        return None
    owns_client = client is None
    try:
        if client is None:
            client = _build_sync_client(proxy, timeout_seconds)
        response = client.get(url)
        response.raise_for_status()
        return response.text
    except Exception:  # noqa: BLE001 - 请求失败静默返回 None。
        return None
    finally:
        if owns_client and client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001, S110 - 连接关闭失败忽略。
                pass


async def _fetch_async(
    url: str,
    *,
    proxy: str,
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """异步抓取页面文本；失败/超时静默返回 None。传入的 client 由调用方负责关闭。"""
    if not url:
        return None
    owns_client = client is None
    try:
        if client is None:
            client = _build_async_client(proxy, timeout_seconds)
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    except Exception:  # noqa: BLE001 - 请求失败静默返回 None。
        return None
    finally:
        if owns_client and client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001, S110 - 连接关闭失败忽略。
                pass


_JUNK_DOMAINS = frozenset(
    {
        "hgcha.com", "hanyuguoxue.com", "zidian.gushici.net",
        "zdic.net", "dict.cn", "xh.5156edu.com",
    }
)
_QUERY_STOP_TOKENS = frozenset({"百科", "最新", "更新", "版本", "内容", "公司", "官方", "游戏", "什么", "是", "查询", "介绍", "背景"})

# 来源域名的轻量加权顺序：百科类域名靠前；最后一级 "wiki" 是兜底模糊匹配。
_ENCYCLOPEDIA_DOMAIN_FRAGMENTS = (
    "moegirl.org.cn",
    "moegirl.org",
    "zh.wikipedia.org",
    "wikipedia.org",
    "baike.baidu.com",
    "baike.com",
    "wiki",
)


def _query_key_tokens(query: str) -> list[str]:
    tokens = re.split(r"[\s，,、。]+", query or "")
    return [
        token
        for token in tokens
        if len(token) >= 2 and token not in _QUERY_STOP_TOKENS
    ]


def _clean_text(value: str) -> str:
    """解码 HTML 实体并把所有连续空白归一为单个空格。"""
    return " ".join(html.unescape(value or "").split())


def _hit_text(hit: WebSearchHit) -> str:
    return _clean_text(f"{hit.title} {hit.snippet}")


def _domain_priority(hit: WebSearchHit) -> tuple[int, str]:
    """按来源域名打分（数值越小越靠前）；未命中百科片段的域名排最后。"""
    domain = (hit.source_domain or "").lower()
    for index, fragment in enumerate(_ENCYCLOPEDIA_DOMAIN_FRAGMENTS):
        if fragment in domain:
            return (index, domain)
    return (len(_ENCYCLOPEDIA_DOMAIN_FRAGMENTS), domain)


def _is_junk(hit: WebSearchHit) -> bool:
    domain = (hit.source_domain or "").lower()
    if domain in _JUNK_DOMAINS:
        return True
    text = _hit_text(hit)
    return any(
        marker in text
        for marker in ("汉语汉字", "拼音", "笔顺", "部首", "新华字典")
    )


def _filter_relevant(hits: list[WebSearchHit], query: str) -> list[WebSearchHit]:
    """过滤垃圾结果；有关键词匹配时优先保留匹配项；最后按来源域名轻量加权。"""
    kept = [hit for hit in hits if not _is_junk(hit)]
    key_tokens = _query_key_tokens(query)
    if key_tokens:
        matched = [
            hit
            for hit in kept
            if any(token in _hit_text(hit) for token in key_tokens)
        ]
        if matched:
            kept = matched
    # Python 排序稳定：同权重的结果保持抓取顺序，整体确定、可测试。
    return sorted(kept, key=_domain_priority)


def fetch_page_text(
    url: str,
    *,
    proxy: str = "",
    timeout_seconds: float = 6.0,
    max_chars: int = 800,
) -> str:
    """打开最相关结果页面并抽取正文（去标签），失败返回空串。"""
    if not url or not url.startswith("http"):
        return ""
    html_text = _fetch(url, proxy=proxy, timeout_seconds=timeout_seconds)
    if not html_text:
        return ""
    text = _HTML_COMMENT_RE.sub(" ", html_text)
    text = _HTML_HIDDEN_BLOCK_RE.sub(" ", text)
    text = _HTML_BOILERPLATE_BLOCK_RE.sub(" ", text)
    text = _HTML_HEAD_BLOCK_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub("\n", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 12]
    return "\n".join(lines)[:max_chars]


class DuckDuckGoWebSearchProvider:
    """免费 DuckDuckGo HTML 搜索（无 key）。"""

    name = "ddg"

    def __init__(self, *, timeout_seconds: float = 3.0, proxy: str = "") -> None:
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.proxy = str(proxy or "")
        self._client: httpx.Client | None = None

    def _url_for(self, term: str) -> str:
        return "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(term)

    def _get_client(self) -> httpx.Client:
        """惰性创建并复用同步客户端，保持 keep-alive 连接池。"""
        if self._client is None or self._client.is_closed:
            self._client = _build_sync_client(self.proxy, self.timeout_seconds)
        return self._client

    def close(self) -> None:
        """释放内部连接池；幂等，关闭后下次检索会重建。"""
        client, self._client = self._client, None
        if client is not None and not client.is_closed:
            try:
                client.close()
            except Exception:  # noqa: BLE001, S110 - 连接关闭失败忽略。
                pass

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        term = (query or "").strip()
        if not term:
            return []
        try:
            html_text = _fetch(
                self._url_for(term),
                proxy=self.proxy,
                timeout_seconds=self.timeout_seconds,
                client=self._get_client(),
            )
        except Exception:  # noqa: BLE001 - 搜索失败静默返回空结果。
            return []
        if not html_text:
            return []
        return _filter_relevant(
            _extract_ddg_hits(html_text, max_results=max_results), term
        )

    async def search_async(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> list[WebSearchHit]:
        """异步检索；复用调用方传入的 AsyncClient 以共享连接池。"""
        term = (query or "").strip()
        if not term:
            return []
        try:
            html_text = await _fetch_async(
                self._url_for(term),
                proxy=self.proxy,
                timeout_seconds=self.timeout_seconds,
                client=client,
            )
        except Exception:  # noqa: BLE001 - 搜索失败静默返回空结果。
            return []
        if not html_text:
            return []
        return _filter_relevant(
            _extract_ddg_hits(html_text, max_results=max_results), term
        )


class BingWebSearchProvider:
    """Bing 国际版 HTML 搜索（无 key，作为 DDG 不可用时的备份）。"""

    name = "bing"

    def __init__(self, *, timeout_seconds: float = 4.0, proxy: str = "") -> None:
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.proxy = str(proxy or "")
        self._client: httpx.Client | None = None

    def _url_for(self, term: str) -> str:
        return (
            "https://www.bing.com/search?q="
            + urllib.parse.quote(term)
            + "&setlang=zh-cn&count=10"
        )

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = _build_sync_client(self.proxy, self.timeout_seconds)
        return self._client

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None and not client.is_closed:
            try:
                client.close()
            except Exception:  # noqa: BLE001, S110 - 连接关闭失败忽略。
                pass

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        term = (query or "").strip()
        if not term:
            return []
        try:
            html_text = _fetch(
                self._url_for(term),
                proxy=self.proxy,
                timeout_seconds=self.timeout_seconds,
                client=self._get_client(),
            )
        except Exception:  # noqa: BLE001 - 搜索失败静默返回空结果。
            return []
        if not html_text:
            return []
        return _filter_relevant(
            _extract_bing_hits(html_text, max_results=max_results), term
        )

    async def search_async(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> list[WebSearchHit]:
        """异步检索（DDG 失败后的 Bing 兜底同样支持）。"""
        term = (query or "").strip()
        if not term:
            return []
        try:
            html_text = await _fetch_async(
                self._url_for(term),
                proxy=self.proxy,
                timeout_seconds=self.timeout_seconds,
                client=client,
            )
        except Exception:  # noqa: BLE001 - 搜索失败静默返回空结果。
            return []
        if not html_text:
            return []
        return _filter_relevant(
            _extract_bing_hits(html_text, max_results=max_results), term
        )



# 搜索结果质量过滤（对标 tavily 插件社区的"污染源"处理思路）：
# 低质域名直接剔除；snippet 过短的结果降权排后而非丢弃（保序稳定过滤）。
_LOW_QUALITY_URL_RE = re.compile(
    r"(?:pinterest\.|csdn\.net/.*/(login|vip)|quora\.com/(?!Profile)|answers\.microsoft\.com|"
    r"baidu\.com/(?:link|s\?)|so\.com/link|verydemo|fx361|docin|doc88|renrendoc|book118)",
    re.IGNORECASE,
)
_MIN_SNIPPET_CHARS = 24


def filter_search_hits(hits: list[WebSearchHit]) -> list[WebSearchHit]:
    """剔除低质域名与无摘要命中；保持原相对顺序。"""
    kept: list[WebSearchHit] = []
    deferred: list[WebSearchHit] = []
    for hit in hits:
        url = hit.url or ""
        if _LOW_QUALITY_URL_RE.search(url):
            continue
        snippet = (hit.snippet or "").strip()
        if len(snippet) < _MIN_SNIPPET_CHARS and not hit.title:
            continue
        if len(snippet) < _MIN_SNIPPET_CHARS:
            deferred.append(hit)
        else:
            kept.append(hit)
    return kept + deferred


class ChainedWebSearchProvider:
    """按顺序尝试多个提供器，任一命中即返回；记录命中的提供器名。"""

    def __init__(
        self,
        providers: list[WebSearchProvider],
        *,
        timeout_seconds: float = 5.0,
        proxy: str = "",
        page_fetcher: object | None = None,
    ) -> None:
        self.providers = providers
        self.timeout_seconds = timeout_seconds
        self.proxy = proxy
        self.page_fetcher = page_fetcher
        self.last_provider_name = ""

    def fetch_page_text(self, url: str, *, max_chars: int = 800) -> str:
        fetcher = self.page_fetcher
        method = getattr(fetcher, "fetch_page_text", None)
        if callable(method):
            text = str(method(url, max_chars=max_chars) or "")
            if text:
                return text

        return fetch_page_text(
            url,
            proxy=self.proxy,
            timeout_seconds=self.timeout_seconds,
            max_chars=max_chars,
        )
    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        for provider in self.providers:
            try:
                hits = provider.search(query, max_results=max_results)
            except Exception:  # noqa: BLE001 - 单提供器失败回退下一提供器。
                hits = []
            if hits:
                self.last_provider_name = str(getattr(provider, "name", "unknown"))
                return filter_search_hits(hits)
        return []

    async def search_async(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> list[WebSearchHit]:
        """异步链式回退：任一提供器命中即返回，语义与同步 search 一致。"""
        for provider in self.providers:
            try:
                method = getattr(provider, "search_async", None)
                if callable(method):
                    hits = await method(query, max_results=max_results, client=client)
                else:
                    hits = provider.search(query, max_results=max_results)
            except Exception:  # noqa: BLE001 - 单提供器失败回退下一提供器。
                hits = []
            if hits:
                return hits
        return []

    def close(self) -> None:
        """关闭内部各提供器的连接池（幂等）。"""
        for provider in self.providers:
            close = getattr(provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001, S110 - 关闭失败忽略。
                    pass


__all__ = [
    "LangSearchWebSearchProvider",
    "TavilyWebSearchProvider",
    "TinyFishFetchProvider",
    "TinyFishWebSearchProvider",
    "YouSearchProvider",
]

from .search_api import (
    LangSearchWebSearchProvider,
    TavilyWebSearchProvider,
    TinyFishFetchProvider,
    TinyFishWebSearchProvider,
    YouSearchProvider,
    build_api_search_provider,
)


def _build_chained_provider(
    timeout_seconds: float,
    proxy: str,
    config: object | None = None,
) -> ChainedWebSearchProvider:
    """Build the configured API chain: Tavily, You.com, LangSearch, optional TinyFish."""
    if config is None:
        return ChainedWebSearchProvider([], timeout_seconds=timeout_seconds, proxy=proxy)
    providers, fetcher = build_api_search_provider(
        config,
        timeout_seconds=timeout_seconds,
        proxy=proxy,
    )
    return ChainedWebSearchProvider(
        list(providers),
        timeout_seconds=timeout_seconds,
        proxy=proxy,
        page_fetcher=fetcher,
    )


def build_web_search_provider(config: object | None = None) -> WebSearchProvider:
    """Build the configured API provider chain; disabled or unconfigured means no search."""
    enabled = bool(getattr(config, "bot_web_search_enabled", False)) if config else False
    if not enabled or config is None:
        return NullWebSearchProvider()
    timeout = float(getattr(config, "bot_web_search_timeout_seconds", 6.0) or 6.0)
    proxy = str(getattr(config, "bot_download_proxy", "") or "").strip()
    return _build_chained_provider(timeout, proxy, config)

def _hit_dedupe_key(hit: WebSearchHit) -> str:
    """跨查询去重的稳定键：URL 小写、去尾部斜杠；无 URL 回退为标题。"""
    url = (hit.url or "").strip().rstrip("/").lower()
    return url or _clean_text(hit.title).lower()


async def search_async(
    query: str,
    *,
    max_results: int = 3,
    timeout_seconds: float = 3.0,
    proxy: str = "",
) -> list[WebSearchHit]:
    """异步联网搜索：DDG 优先、Bing 兜底；失败/超时静默返回空列表。"""
    provider = _build_chained_provider(timeout_seconds, proxy)
    client: httpx.AsyncClient | None = None
    try:
        client = _build_async_client(proxy, timeout_seconds)
        async with client:
            return await provider.search_async(
                query, max_results=max_results, client=client
                )
    except Exception:  # noqa: BLE001 - 搜索失败静默返回空结果。
        return []
    finally:
        if client is not None and not client.is_closed:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001, S110 - 连接关闭失败忽略。
                pass


async def search_multi_async(
    queries: Iterable[str],
    max_results: int = 3,
    *,
    timeout_seconds: float = 3.0,
    proxy: str = "",
) -> list[WebSearchHit]:
    """并发执行多个查询（每个查询仍 DDG 优先、Bing 兜底），按 URL 去重合并。

    结果顺序由查询顺序与每个查询内部的命中顺序共同决定，保持确定性。
    """
    query_list = [str(query or "").strip() for query in queries]
    query_list = [query for query in query_list if query]
    if not query_list:
        return []
    provider = _build_chained_provider(timeout_seconds, proxy)
    client: httpx.AsyncClient | None = None
    try:
        client = _build_async_client(proxy, timeout_seconds)
        async with client:
            results = await asyncio.gather(
                *[
                    provider.search_async(
                        query, max_results=max_results, client=client
                    )
                    for query in query_list
                ],
                return_exceptions=True,
                )
    except Exception:  # noqa: BLE001 - 搜索失败静默返回空结果。
        return []
    finally:
        if client is not None and not client.is_closed:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001, S110 - 连接关闭失败忽略。
                pass
    merged: list[WebSearchHit] = []
    seen: set[str] = set()
    for result in results:
        if isinstance(result, BaseException):
            continue
        for hit in result:
            key = _hit_dedupe_key(hit)
            if key in seen:
                continue
            seen.add(key)
            merged.append(hit)
    return merged


def _extract_ddg_hits(html_text: str, *, max_results: int = 3) -> list[WebSearchHit]:
    hits: list[WebSearchHit] = []
    blocks = re.split(r'class="result"|class="result ', html_text)[1:]
    for block in blocks:
        title_match = re.search(
            r'class="result__a"[^>]*>(.*?)</a>', block, re.DOTALL
        )
        snippet_match = re.search(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>', block, re.DOTALL
        )
        link_match = re.search(r'href="(https?://[^"]+)"', block)
        if not title_match or not link_match:
            continue
        title = _clean_text(_HTML_TAG_RE.sub("", title_match.group(1)))
        snippet = (
            _clean_text(_HTML_TAG_RE.sub("", snippet_match.group(1)))
            if snippet_match
            else ""
        )
        url = link_match.group(1)
        if url.startswith("//"):
            url = "https:" + url
        domain = urllib.parse.urlsplit(url).netloc
        hits.append(
            WebSearchHit(title=title, snippet=snippet, url=url, source_domain=domain)
        )
        if len(hits) >= max_results:
            break
    return hits


def _extract_bing_hits(html_text: str, *, max_results: int = 3) -> list[WebSearchHit]:
    hits: list[WebSearchHit] = []
    blocks = re.split(r'<li class="b_algo"', html_text)[1:]
    for block in blocks:
        title_match = re.search(r"<h2[^>]*><a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.DOTALL)
        if not title_match:
            continue
        url = title_match.group(1)
        title = _clean_text(_HTML_TAG_RE.sub("", title_match.group(2)))
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
        snippet = (
            _clean_text(_HTML_TAG_RE.sub("", snippet_match.group(1)))
            if snippet_match
            else ""
        )
        domain = urllib.parse.urlsplit(url).netloc
        hits.append(
            WebSearchHit(title=title, snippet=snippet, url=url, source_domain=domain)
        )
        if len(hits) >= max_results:
            break
    return hits

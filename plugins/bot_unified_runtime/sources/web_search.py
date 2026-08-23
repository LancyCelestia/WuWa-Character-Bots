"""按需联网检索提供器（意图判定见 runtime/question_intent.py）。

- 默认关闭（BOT_WEB_SEARCH_ENABLED=false）；
- 支持代理（BOT_DOWNLOAD_PROXY，例如 http://127.0.0.1:7890），外网检索走代理；
- DuckDuckGo HTML 优先，失败/为空自动换 Bing HTML；
- 单次超时短、失败静默降级为空，绝不拖慢对话。
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

_HTML_TAG_RE = re.compile(r"<[^>]+>")


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


def _build_opener(proxy: str, timeout_seconds: float) -> urllib.request.OpenerDirector:
    handlers: list = []
    if proxy:
        handlers.append(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener(*handlers)


def _fetch(url: str, *, proxy: str, timeout_seconds: float) -> str | None:
    try:
        opener = _build_opener(proxy, timeout_seconds)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with opener.open(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        return None


_JUNK_DOMAINS = frozenset(
    {
        "hgcha.com", "hanyuguoxue.com", "zidian.gushici.net",
        "zdic.net", "dict.cn", "xh.5156edu.com",
    }
)
_QUERY_STOP_TOKENS = frozenset({"百科", "最新", "更新", "版本", "内容", "公司", "官方", "游戏", "什么", "是", "查询", "介绍", "背景"})


def _query_key_tokens(query: str) -> list[str]:
    tokens = re.split(r"[\s，,、。]+", query or "")
    return [
        token
        for token in tokens
        if len(token) >= 2 and token not in _QUERY_STOP_TOKENS
    ]


def _is_junk(hit: WebSearchHit) -> bool:
    domain = (hit.source_domain or "").lower()
    if domain in _JUNK_DOMAINS:
        return True
    text = f"{hit.title} {hit.snippet}"
    if any(marker in text for marker in ("汉语汉字", "拼音", "笔顺", "部首", "新华字典")):
        return True
    return False


def _filter_relevant(hits: list[WebSearchHit], query: str) -> list[WebSearchHit]:
    key_tokens = _query_key_tokens(query)
    kept = [hit for hit in hits if not _is_junk(hit)]
    if key_tokens:
        matched = [
            hit
            for hit in kept
            if any(token in f"{hit.title} {hit.snippet}" for token in key_tokens)
        ]
        if matched:
            return matched
    return kept


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
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
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

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        term = (query or "").strip()
        if not term:
            return []
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(term)
        html_text = _fetch(
            url, proxy=self.proxy, timeout_seconds=self.timeout_seconds
        )
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

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        term = (query or "").strip()
        if not term:
            return []
        url = (
            "https://www.bing.com/search?q="
            + urllib.parse.quote(term)
            + "&setlang=zh-cn&count=10"
        )
        html_text = _fetch(
            url, proxy=self.proxy, timeout_seconds=self.timeout_seconds
        )
        if not html_text:
            return []
        return _filter_relevant(
            _extract_bing_hits(html_text, max_results=max_results), term
        )


class ChainedWebSearchProvider:
    """按顺序尝试多个提供器，任一命中即返回；记录命中的提供器名。"""

    def __init__(
        self,
        providers: list[WebSearchProvider],
        *,
        timeout_seconds: float = 5.0,
        proxy: str = "",
    ) -> None:
        self.providers = providers
        self.timeout_seconds = timeout_seconds
        self.proxy = proxy

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        for provider in self.providers:
            try:
                hits = provider.search(query, max_results=max_results)
            except Exception:
                hits = []
            if hits:
                return hits
        return []


def build_web_search_provider(config: object | None = None) -> WebSearchProvider:
    """按配置构建：未启用返回 Null；启用时 DDG → Bing 链式，带代理。"""
    enabled = bool(getattr(config, "bot_web_search_enabled", False)) if config else False
    if not enabled:
        return NullWebSearchProvider()
    timeout = (
        float(getattr(config, "bot_web_search_timeout_seconds", 3.0) or 3.0)
        if config
        else 3.0
    )
    proxy = (
        str(getattr(config, "bot_download_proxy", "") or "").strip()
        if config
        else ""
    )
    return ChainedWebSearchProvider(
        [
            DuckDuckGoWebSearchProvider(timeout_seconds=timeout, proxy=proxy),
            BingWebSearchProvider(timeout_seconds=min(timeout + 1.0, 6.0), proxy=proxy),
        ],
        timeout_seconds=timeout,
        proxy=proxy,
    )


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
        title = html.unescape(_HTML_TAG_RE.sub("", title_match.group(1)).strip())
        snippet = (
            html.unescape(_HTML_TAG_RE.sub("", snippet_match.group(1)).strip())
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
        title = html.unescape(_HTML_TAG_RE.sub("", title_match.group(2)).strip())
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
        snippet = (
            html.unescape(_HTML_TAG_RE.sub("", snippet_match.group(1)).strip())
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

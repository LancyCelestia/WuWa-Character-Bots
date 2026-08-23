"""按需联网检索（默认关闭）：现实时效性问题才搜，世界观问题永远走本地知识库。

设计目标（用户要求）：
- 问鸣潮世界观内容时速度最快：意图判定为 knowledge_only，不联网，直接用本地向量知识库；
- 问现实生活中的时效性问题（新闻/价格/汇率/最新/今天发生什么）才触发搜索；
- 搜索失败/超时静默降级为空，绝不拖慢或阻断回复；
- 结果作为 untrusted 事实注入上下文，模型自己决定是否采用。

默认 `BOT_WEB_SEARCH_ENABLED=false`；开启后仅在强信号触发时联网。
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

_HTML_TAG_RE = re.compile(r"<[^>]+")

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


class DuckDuckGoWebSearchProvider:
    """免费 DuckDuckGo HTML 搜索（无 key）。"""

    def __init__(self, *, timeout_seconds: float = 3.0) -> None:
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        term = (query or "").strip()
        if not term:
            return []
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(term)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                html_text = response.read().decode("utf-8", errors="replace")
        except Exception:
            return []
        return _extract_ddg_hits(html_text, max_results=max_results)


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
        title = _HTML_TAG_RE.sub("", title_match.group(1))
        snippet = (
            _HTML_TAG_RE.sub("", snippet_match.group(1))
            if snippet_match
            else ""
        )
        url = link_match.group(1)
        domain = urllib.parse.urlsplit(url).netloc
        hits.append(
            WebSearchHit(
                title=title.strip(),
                snippet=snippet.strip(),
                url=url,
                source_domain=domain,
            )
        )
        if len(hits) >= max_results:
            break
    return hits

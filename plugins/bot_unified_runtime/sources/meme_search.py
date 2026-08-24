"""按需梗搜索：让大模型在必要时自己查"最近的梗/热词"。

设计（符合"默认不注入时梗，需要时让模型去搜"）：

- 聊天链路检测到"问梗"信号（"是什么梗/啥意思/什么梗/XX是什么意思"、
  引号短词、热门缩写）时，先走 ``MemeSearchProvider`` 搜索；
- 结果按**来源白名单**（B 站、小红书、萌娘百科等二次元平台）过滤；
- 再按**不适内容规则**过滤（三次元烂梗、冒犯/低俗/无意义内容）；
- 命中的条目作为 untrusted 事实附到对话上下文，模型自己决定用不用。

默认关闭（``BOT_MEME_SEARCH_ENABLED=false``）；离线或搜索失败时
安全降级为"未检索到"，不阻塞回复、不报错。后端可插拔：
``DuckDuckGoMemeSearchProvider`` 使用免费 HTML 接口，之后可替换为
B 站/小红书官方 API 或自建搜索。
"""

from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

_MEME_ASK_PATTERN = re.compile(
    r"(是什么梗|什么梗|啥梗|啥意思|什么意思|是什么意思|怎么来的|出自哪里)"
)
_QUOTE_CHARS = '"\'""''\u201c\u201d\u2018\u2019'
_QUOTED_TERM = re.compile(
    rf"[{re.escape(_QUOTE_CHARS)}]([^{re.escape(_QUOTE_CHARS)}]{{2,20}})[{re.escape(_QUOTE_CHARS)}]"
)

# 二次元/ACG 来源白名单（域名子串匹配）。
PREFERRED_DOMAINS: tuple[str, ...] = (
    "bilibili.com",
    "xiaohongshu.com",
    "zh.moegirl.org.cn",
    "moegirl.org.cn",
    "huijiwiki.com",
    "zhihu.com",
    "weibo.com",
    "douyin.com",
)

# 二次元指数权重：只用于确定性排序/过滤（阈值 0.5），
# 不进 LLM、不产生额外 token 消耗。
DOMAIN_WEIGHTS: dict[str, float] = {
    "moegirl.org.cn": 1.0,
    "zh.moegirl.org.cn": 1.0,
    "bilibili.com": 0.9,
    "huijiwiki.com": 0.85,
    "xiaohongshu.com": 0.8,
    "zhihu.com": 0.6,
    "weibo.com": 0.5,
    "douyin.com": 0.5,
}
MIN_SCORE_TO_KEEP = 0.5

# 不适内容规则：命中即丢弃该条结果（三次元烂梗/冒犯/低俗）。
BLOCKED_TERMS: tuple[str, ...] = (
    "去世",
    "病逝",
    "坠亡",
    "车祸",
    "跳楼",
    "自杀",
    "抑郁去世",
    "辱骂",
    "性侵",
    "强奸",
    "裸",
    "排泄",
    "恋尸",
    "分尸",
    "歧视",
    "灭绝",
)


@dataclass(frozen=True)
class MemeSearchResult:
    term: str
    summary: str
    source_domain: str
    url: str
    searched_at: float
    score: float = 0.5


class MemeSearchProvider(Protocol):
    def search(self, term: str, *, max_results: int = 3) -> list[MemeSearchResult]:
        """搜索一个梗/热词，返回过滤后的结果；失败返回空列表。"""


class NullMemeSearchProvider:
    def search(self, term: str, *, max_results: int = 3) -> list[MemeSearchResult]:
        return []


class DuckDuckGoMemeSearchProvider:
    """免费 DuckDuckGo HTML 搜索 + 白名单 + 不适过滤。

    不依赖 API key；只取标题/摘要，不渲染页面。结果域名不在白名单
    时丢弃；标题或摘要命中不适规则时丢弃。
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        cache_seconds: int = 600,
        preferred_domains: tuple[str, ...] = PREFERRED_DOMAINS,
        blocked_terms: tuple[str, ...] = BLOCKED_TERMS,
    ) -> None:
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.cache_seconds = max(30, int(cache_seconds))
        self.preferred_domains = preferred_domains
        self.blocked_terms = blocked_terms
        self._cache: dict[str, tuple[float, list[MemeSearchResult]]] = {}

    def search(self, term: str, *, max_results: int = 3) -> list[MemeSearchResult]:
        query = (term or "").strip()
        if not query:
            return []
        key = query.lower()
        cached_at, cached = self._cache.get(key, (0.0, []))
        if time.monotonic() - cached_at <= self.cache_seconds:
            return cached[:max_results]
        results = self._fetch(query)
        self._cache[key] = (time.monotonic(), results)
        return results[:max_results]

    def _fetch(self, query: str) -> list[MemeSearchResult]:
        url = (
            "https://html.duckduckgo.com/html/?q="
            + urllib.parse.quote(f"{query} 是什么梗")
        )
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
                html = response.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 搜索请求失败静默返回空结果。
            return []
        items = _extract_ddg_items(html)
        return filter_meme_results(
            query,
            items,
            preferred_domains=self.preferred_domains,
            blocked_terms=self.blocked_terms,
        )


def filter_meme_results(
    query: str,
    items: list[tuple[str, str, str]],
    *,
    preferred_domains: tuple[str, ...] = PREFERRED_DOMAINS,
    blocked_terms: tuple[str, ...] = BLOCKED_TERMS,
) -> list[MemeSearchResult]:
    """域名白名单 + 不适内容过滤 + 二次元指数评分排序。

    评分是纯规则（域名权重 + 命中查询词），只用于排序和阈值过滤，
    不会进入 LLM 判断，避免额外 token 开销。
    """
    results: list[MemeSearchResult] = []
    normalized_query = (query or "").strip().lower()
    for title, snippet, href in items:
        domain = _domain_of(href)
        if domain and not any(pref in domain for pref in preferred_domains):
            continue
        combined = f"{title} {snippet}"
        lowered = combined.lower()
        if any(blocked in lowered for blocked in blocked_terms):
            continue
        summary = snippet.strip() or title.strip()
        score = 0.0
        for weight_domain, weight in DOMAIN_WEIGHTS.items():
            if weight_domain in domain:
                score = weight
                break
        if normalized_query and normalized_query in lowered:
            score = min(1.0, score + 0.1)
        if score < MIN_SCORE_TO_KEEP:
            continue
        results.append(
            MemeSearchResult(
                term=query,
                summary=summary[:240],
                source_domain=domain or "unknown",
                url=href,
                searched_at=time.time(),
                score=score,
            )
        )
    results.sort(key=lambda result: (-result.score, result.source_domain))
    return results


def _extract_ddg_items(html: str) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    for block in re.split(r'class="result', html)[1:]:
        title_match = re.search(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            re.DOTALL,
        )
        snippet_match = re.search(
            r'class="result__snippet"[^>]*>(.*?)</a>',
            block,
            re.DOTALL,
        )
        if not title_match:
            continue
        href = title_match.group(1)
        title = _strip_html(title_match.group(2))
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        if title:
            items.append((title, snippet, href))
    return items


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip()


def _domain_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc.lower()
    except ValueError:
        return ""


def extract_meme_query(text: str) -> str | None:
    """从消息里提取"想查的梗/热词"；没有明显信号返回 None。"""
    stripped = (text or "").strip()
    if not stripped:
        return None
    quoted = _QUOTED_TERM.search(stripped)
    if quoted:
        return quoted.group(1).strip()
    if _MEME_ASK_PATTERN.search(stripped):
        cleaned = _MEME_ASK_PATTERN.sub(" ", stripped)
        cleaned = re.sub(r"[，。！？!?,.、\s]+", " ", cleaned).strip()
        candidate = cleaned[:24].strip()
        if candidate:
            return candidate
        return None
    # 热门缩写/短词形态：3-6 个英文字母或 2-6 个汉字，且带问号。
    short = re.search(r"([A-Za-z]{3,6}|[\u4e00-\u9fff]{2,6})\s*[?？]", stripped)
    if short:
        return short.group(1).strip()
    return None


def build_meme_search_provider(config: object) -> MemeSearchProvider:
    enabled = bool(getattr(config, "bot_meme_search_enabled", False))
    if not enabled:
        return NullMemeSearchProvider()
    return DuckDuckGoMemeSearchProvider(
        timeout_seconds=float(getattr(config, "bot_meme_search_timeout_seconds", 8.0)),
        cache_seconds=int(getattr(config, "bot_meme_search_cache_seconds", 600)),
    )

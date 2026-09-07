"""维基百科查询（自写薄层，直接调 MediaWiki 公开 api.php）。

只依赖标准 MediaWiki API（action=opensearch / action=query），
不引入任何 AGPL/GPL 第三方代码。
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

_USER_AGENT = (
    "BotCharacterBots/0.1 (NoneBot2 wiki lookup; contact: local user)"
    " Mozilla/5.0"
)

# 维基页面内容变化很慢：短 TTL 缓存 + 最小请求间隔，
# 避免重复外呼拖慢回复，也避免触发站点的速率限制。
WIKI_CACHE_TTL_SECONDS = 900.0
WIKI_MIN_REQUEST_INTERVAL_SECONDS = 1.0
WIKI_CACHE_MAX_ENTRIES = 256

_CACHE_LOCK = threading.Lock()
_WIKI_RESPONSE_CACHE: dict[str, tuple[float, object]] = {}
_LAST_WIKI_REQUEST: list[float] = [0.0]


def clear_wiki_cache() -> None:
    """清空 wiki 响应缓存（测试与运行时管理用）。"""
    with _CACHE_LOCK:
        _WIKI_RESPONSE_CACHE.clear()
        _LAST_WIKI_REQUEST[0] = 0.0


def _cached_get_json(url: str, *, timeout: int, proxy: str) -> object:
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _WIKI_RESPONSE_CACHE.get(url)
        if hit is not None and now - hit[0] < WIKI_CACHE_TTL_SECONDS:
            return hit[1]
        wait = _LAST_WIKI_REQUEST[0] + WIKI_MIN_REQUEST_INTERVAL_SECONDS - now
    if wait > 0:
        time.sleep(min(wait, 5.0))
    payload = http_get_json(url, user_agent=_USER_AGENT, proxy=proxy, timeout=timeout)
    with _CACHE_LOCK:
        _LAST_WIKI_REQUEST[0] = time.monotonic()
        if len(_WIKI_RESPONSE_CACHE) >= WIKI_CACHE_MAX_ENTRIES:
            _WIKI_RESPONSE_CACHE.clear()
        _WIKI_RESPONSE_CACHE[url] = (time.monotonic(), payload)
    return payload


def _api_base(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


def wiki_search(query: str, *, lang: str = "zh", limit: int = 5, proxy: str = "") -> list[str]:
    """搜索词条名（opensearch）。"""
    payload = _cached_get_json(
        _api_base(lang)
        + "?action=opensearch&format=json&redirects=resolve&limit="
        + str(max(1, min(int(limit), 10)))
        + f"&search={urllib.parse.quote(query)}",
        proxy=proxy,
        timeout=10,
    )
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    titles = payload[1]
    return [str(title) for title in titles if str(title).strip()]


def wiki_summary(
    title: str,
    *,
    lang: str = "zh",
    max_chars: int = 600,
    proxy: str = "",
) -> str:
    """词条简介（intro 段纯文本）。"""
    payload = _cached_get_json(
        _api_base(lang)
        + "?action=query&prop=extracts%7Cpageprops&exintro=1&explaintext=1&redirects=1"
        + "&converttitles=1&variant=zh-hans&format=json&formatversion=2"
        + f"&titles={urllib.parse.quote(title)}",
        proxy=proxy,
        timeout=10,
    )
    data = payload.get("query", {}) if isinstance(payload, dict) else {}
    if any(item.get("tofragment") for item in data.get("redirects", [])):
        # A redirect into a character list must not return the entire game's intro.
        return ""
    pages = data.get("pages") or []
    if not pages or "missing" in pages[0] or "disambiguation" in pages[0].get("pageprops", {}):
        return ""
    extract = str(pages[0].get("extract") or "").strip()
    return _clip_summary(extract, max_chars)


def _normalize_title(value: str) -> str:
    """Normalize harmless title variants for deterministic matching."""
    value = re.sub(r"[\s_]+", "", (value or "").strip()).casefold()
    # MediaWiki may return traditional Chinese while the user types simplified.
    return value.replace("鳴", "鸣").replace("灣", "湾").replace("國", "国")


def _format_wiki_result(title: str, summary: str, *, lang: str) -> str:
    url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
    return f"{title}\n{summary}\n链接：{url}"


def wiki_lookup(
    query: str,
    *,
    lang: str = "zh",
    max_chars: int = 600,
    proxy: str = "",
    entry_pages: tuple[str, ...] = ("鳴潮角色列表",),
) -> str | None:
    """Return an exact page or an exact entry in a full-text search candidate.

    MediaWiki opensearch is relevance-ranked, not an identity lookup. Never
    accept its first result when it is unrelated to the requested title.
    """
    wanted = (query or "").strip().strip("·•。！？?,，；;：: ").strip("《》")
    if not wanted:
        return None
    # Direct title lookup prevents a broad search result such as a list page
    # from shadowing an exact article.
    try:
        exact = wiki_summary(wanted, lang=lang, max_chars=max_chars, proxy=proxy)
    except ParseHttpError:
        exact = ""
    if exact:
        return _format_wiki_result(wanted, exact, lang=lang)
    return _lookup_embedded_entry(wanted, lang=lang, max_chars=max_chars, proxy=proxy,
                                  entry_pages=entry_pages)


@dataclass
class _WikiNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_WikiNode | str] = field(default_factory=list)

    def anchor(self) -> str:
        if self.attrs.get("id"):
            return self.attrs["id"]
        return next((value for child in self.children if isinstance(child, _WikiNode)
                     if (value := child.anchor())), "")

    def text(self) -> str:
        if self.tag in {"script", "style", "sup"}:
            return ""
        return "".join(child.text() if isinstance(child, _WikiNode) else child
                       for child in self.children)


class _WikiHTML(HTMLParser):
    """Small structural reader; keep section/dl/table boundaries, not tag regexes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _WikiNode("root")
        self.stack = [self.root]
        self.nodes: list[_WikiNode] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _WikiNode(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        self.nodes.append(node)
        if tag not in {"br", "img", "hr", "meta", "link", "input", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _entry_terms(query: str) -> list[str]:
    normalized = _normalize_title(query)
    # Permit a work-qualified request to match an unqualified character heading.
    unqualified = re.sub(r"^鸣潮[：:·-]?", "", normalized)
    return list(dict.fromkeys(term for term in (normalized, unqualified) if term))


def _clip_summary(text: str, limit: int) -> str:
    text = re.sub(r"[ \t]+", " ", text).strip()
    limit = max(1, min(int(limit), 4000))
    if len(text) <= limit:
        return text
    prefix = text[:limit]
    boundary = max(prefix.rfind(mark) for mark in "。！？.!?\n")
    if boundary >= limit // 2:
        prefix = prefix[:boundary + 1]
    return prefix.rstrip() + "…"


def _embedded_excerpt(html: str, query: str) -> tuple[str, str, str] | None:
    parser = _WikiHTML()
    parser.feed(html[:2_000_000])
    terms = _entry_terms(query)
    headings = {"h2", "h3", "h4", "h5", "h6", "dt"}
    blocks = [node for node in parser.nodes if node.tag in headings | {"dd", "p", "tr"}]
    for index, node in enumerate(blocks):
        label = node.text().strip()
        if node.tag == "tr":
            cells = [child for child in node.children
                     if isinstance(child, _WikiNode) and child.tag in {"th", "td"}]
            if not cells:
                continue
            label = cells[0].text().strip()
        elif node.tag not in headings:
            continue
        normalized = _normalize_title(label)
        # Heading suffixes can contain voice actors, editing UI or disambiguation.
        if not any(normalized == term or normalized.startswith((term + "（", term + "(", term + "["))
                   for term in terms):
            continue
        if node.tag == "tr":
            return label, node.text().strip(), node.anchor()
        pieces: list[str] = []
        for following in blocks[index + 1:]:
            if following.tag in headings:
                break
            value = following.text().strip()
            if value and not any(value in previous for previous in pieces):
                pieces.append(value)
        if pieces:
            return label, "\n".join(pieces), node.anchor()
    return None


def _lookup_embedded_entry(
    query: str, *, lang: str, max_chars: int, proxy: str, entry_pages: tuple[str, ...],
) -> str | None:
    """Exact entries in configured index pages first, then full-text candidates.

    Search ranking can omit an existing character list entirely. Configured
    pages are candidate sources, not authority to match unrelated content.
    """
    def candidates():
        yield from (title for title in entry_pages[:3] if title.strip())
        params = urllib.parse.urlencode({
            "action": "query", "list": "search", "srsearch": '"' + _entry_terms(query)[-1] + '"',
            "srnamespace": 0, "srlimit": 3, "format": "json", "formatversion": 2,
        })
        try:
            payload = _cached_get_json(_api_base(lang) + "?" + params, proxy=proxy, timeout=5)
            results = payload.get("query", {}).get("search", []) if isinstance(payload, dict) else []
            for item in results[:3]:
                title = str(item.get("title") or "")
                if title:
                    yield title
        except (ParseHttpError, TypeError, ValueError, AttributeError):
            return

    seen: set[str] = set()
    for title in candidates():
        if title in seen:
            continue
        seen.add(title)
        try:
            params = urllib.parse.urlencode({"action": "parse", "page": title, "prop": "text",
                "redirects": 1, "variant": "zh-hans", "format": "json", "formatversion": 2})
            page = _cached_get_json(_api_base(lang) + "?" + params, proxy=proxy, timeout=5)
            parsed = page.get("parse", {}) if isinstance(page, dict) else {}
            html = parsed.get("text", "")
            if isinstance(html, dict):
                html = html.get("*", "")
            excerpt = _embedded_excerpt(str(html), query)
            if excerpt is None:
                continue
            label, text, anchor = excerpt
            canonical = str(parsed.get("title") or title)
            url = (f"https://{lang}.wikipedia.org/wiki/"
                   + urllib.parse.quote(canonical.replace(" ", "_")))
            if anchor:
                url += "#" + urllib.parse.quote(anchor)
            return (f"{label}（来源：{canonical}中的条目，非独立页面）\n"
                    + _clip_summary(text, max_chars) + "\n链接：" + url)
        except (ParseHttpError, TypeError, ValueError, AttributeError):
            continue
    return None


_GAME_NOISE_RE = re.compile(r"(?:\b(?:19|20)\d{2}\b|(?:立项|公布|公开|公测|发售|发行|上线|上市|开发于|工作室成立).{0,24}(?:年|月|日)|\d{4}年)", re.IGNORECASE)

def build_wiki_brief(text: str, *, max_chars: int = 1800) -> str:
    """Turn a page/list excerpt into a user-oriented entity brief.

    This is intentionally deterministic: it prioritizes what/creator/type,
    premise, gameplay and a conservative current-status line, while dropping
    chronology and boilerplate. It does not invent facts.
    """
    raw = re.sub(r"\s+", " ", (text or "")).strip()
    if not raw:
        return ""
    sections: dict[str, str] = {}
    current = "overview"
    chunks = re.split(r"(?:^|\s)==+\s*([^=\n]+?)\s*==+", raw)
    if chunks:
        sections[current] = chunks[0]
        for i in range(1, len(chunks), 2):
            current = chunks[i].strip().lower()
            sections[current] = chunks[i + 1] if i + 1 < len(chunks) else ""
    def clean(value: str) -> str:
        value = _GAME_NOISE_RE.sub("", value)
        value = re.sub(r"\s{2,}", " ", value).strip(" ，。；;")
        return value
    overview = clean(sections.get("overview", raw))
    gameplay = clean(next((v for k, v in sections.items() if any(x in k for x in ("玩法", "游戏", "系统"))), ""))
    story = clean(next((v for k, v in sections.items() if any(x in k for x in ("剧情", "故事", "世界观"))), ""))
    status = clean(next((v for k, v in sections.items() if any(x in k for x in ("运营", "现状", "发行", "更新"))), ""))
    lines = []
    if overview: lines.append("这是什么：" + overview)
    if gameplay: lines.append("主要玩法：" + gameplay)
    if story: lines.append("核心故事：" + story)
    lines.append("当前状态：" + (status or "现有页面没有给出足够的当前状态信息。"))
    result = "\n".join(lines)
    return _clip_summary(result, max_chars)

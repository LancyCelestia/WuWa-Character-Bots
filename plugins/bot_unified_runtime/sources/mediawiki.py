"""维基百科查询（自写薄层，直接调 MediaWiki 公开 api.php）。

只依赖标准 MediaWiki API（action=opensearch / action=query），
不引入任何 AGPL/GPL 第三方代码。
"""

from __future__ import annotations

import urllib.parse

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

_USER_AGENT = (
    "BotCharacterBots/0.1 (NoneBot2 wiki lookup; contact: local user)"
    " Mozilla/5.0"
)


def _api_base(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


def wiki_search(query: str, *, lang: str = "zh", limit: int = 5, proxy: str = "") -> list[str]:
    """搜索词条名（opensearch）。"""
    payload = http_get_json(
        _api_base(lang)
        + "?action=opensearch&format=json&redirects=resolve&limit="
        + str(max(1, min(int(limit), 10)))
        + f"&search={urllib.parse.quote(query)}",
        user_agent=_USER_AGENT,
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
    payload = http_get_json(
        _api_base(lang)
        + "?action=query&prop=extracts&exintro=1&explaintext=1&redirects=1"
        + "&format=json&formatversion=2"
        + f"&titles={urllib.parse.quote(title)}",
        user_agent=_USER_AGENT,
        proxy=proxy,
        timeout=10,
    )
    pages = ((payload or {}).get("query") or {}).get("pages") or []
    if not pages:
        return ""
    extract = str(pages[0].get("extract") or "").strip()
    if len(extract) > max_chars:
        extract = extract[:max_chars].rstrip() + "…"
    return extract


def wiki_lookup(
    query: str,
    *,
    lang: str = "zh",
    max_chars: int = 600,
    proxy: str = "",
) -> str | None:
    """搜索词条并返回 (标题, 简介) 文案；找不到返回 None。"""
    try:
        titles = wiki_search(query, lang=lang, proxy=proxy)
    except ParseHttpError:
        return None
    if not titles:
        return None
    title = titles[0]
    summary = ""
    try:
        summary = wiki_summary(title, lang=lang, max_chars=max_chars, proxy=proxy)
    except ParseHttpError:
        summary = ""
    if not summary:
        return None
    url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
    return f"{title}\n{summary}\n链接：{url}"

"""萌娘百科（mzh.moegirl.org.cn）链接解析。

- 词条页（``index.php?title=词条名`` 或 ``/词条路径``）：
  优先走 MediaWiki api.php 匿名查询（action=query&prop=extracts|pageimages，
  已实测匿名可用；action=parse 被站方禁用），拿词条名 / 首图 / 正文首段；
  api 失败回退页面 og meta（og:title 内嵌 mw-page-title-main span，需剥标签；
  og:description 可能混入 .mw-parser-output 样式噪音，需清洗）。
- ``/#/post/...`` 社区帖：hash 路由 SPA，服务端只返回壳页，公开 API 探查
  不可得，诚实降级为浅层入口卡（不伪造内容）。
"""

from __future__ import annotations

import html
import re
import urllib.parse

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
    parsed_cover_url,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
    http_get_text,
)

# MediaWiki 匿名查询接口（词条元信息 + 首图 + 首段纯文本）。
_MOEGIRL_API = "https://mzh.moegirl.org.cn/api.php"

# 词条路径里可能出现的语言前缀（/zh-cn/词条、/en/词条…），不是词条名。
_LANGUAGE_PREFIXES = frozenset(
    {"zh", "zh-cn", "zh-hans", "zh-hant", "zh-tw", "zh-hk", "zh-mo", "zh-my",
     "zh-sg", "en", "ja", "ko", "ar", "de", "es", "fr", "ru", "it", "pt", "vi", "th"}
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MW_STYLE_NOISE_RE = re.compile(r"\.mw-parser-output\b.*$", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_wiki_title(value: object) -> str:
    """剥掉 og:title 内嵌的 <span class="mw-page-title-main"> 等标签。"""
    text = html.unescape(str(value or ""))
    text = _HTML_TAG_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _clean_og_description(value: object) -> str:
    """去掉 og:description 混入的 .mw-parser-output 样式噪音并压缩空白。"""
    text = html.unescape(str(value or ""))
    text = _MW_STYLE_NOISE_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _moegirl_entry_title(url: str) -> str:
    """从 URL 提取词条名：index.php?title= 参数优先，其次路径段。"""
    parts = urllib.parse.urlsplit(url)
    if "title" in urllib.parse.parse_qs(parts.query):
        raw = urllib.parse.parse_qs(parts.query)["title"][0].strip()
        if raw:
            return raw
    path = parts.path or ""
    if path.startswith("/index.php") or not path.strip("/"):
        return ""
    segments = [seg for seg in path.split("/") if seg]
    for seg in segments:
        lowered = seg.lower()
        if lowered in _LANGUAGE_PREFIXES:
            continue
        return urllib.parse.unquote(seg)
    return ""


def _moegirl_api_lookup(
    title: str,
    *,
    cookie_header: str = "",
    proxy: str = "",
) -> ParsedContent | None:
    """api.php 匿名查询：词条名 / 首图 / 首段纯文本摘要。"""
    api = (
        f"{_MOEGIRL_API}?action=query&prop=extracts%7Cpageimages&exintro=1"
        "&explaintext=1&piprop=thumbnail&pithumbsize=600&redirects=1"
        f"&titles={urllib.parse.quote(title)}&formatversion=2&format=json"
    )
    payload = http_get_json(api, timeout=10, cookie=cookie_header, proxy=proxy)
    pages = ((payload or {}).get("query") or {}).get("pages") or []
    page = next((p for p in pages if isinstance(p, dict) and p.get("title")), None)
    if page is None or page.get("missing"):
        return None
    extract = str(page.get("extract") or "").strip()
    if len(extract) > 300:
        extract = extract[:300] + "…"
    thumbnail = (page.get("thumbnail") or {}).get("source") or ""
    return build_parsed_content(
        platform="moegirl",
        item_id=str(page.get("pageid") or ""),
        item_kind="article",
        title=str(page.get("title") or title),
        summary=extract,
        cover_url=str(thumbnail),
        canonical_url=f"https://mzh.moegirl.org.cn/{urllib.parse.quote(str(page.get('title') or title))}",
        parse_depth="deep",
        page_type="wiki",
        detail={"source": "mediawiki-api"},
    )


def _moegirl_page_og(
    url: str,
    *,
    cookie_header: str = "",
    proxy: str = "",
) -> ParsedContent:
    """词条页 og 兜底：复用 generic._og_scrape，再清洗内嵌标签与样式噪音。"""
    item = _moegirl_scrape_raw(url, cookie_header=cookie_header, proxy=proxy)
    identity = item.identity
    content = item.content
    title = _clean_wiki_title(content.title if content else "")
    if not title:
        raise ParseHttpError("moegirl: no parsable title in page")
    summary = _clean_og_description(content.summary if content else "")
    return build_parsed_content(
        platform=identity.platform if identity else "moegirl",
        item_id=identity.item_id if identity else "",
        item_kind="article",
        title=title,
        summary=summary,
        cover_url=parsed_cover_url(item),
        canonical_url=identity.canonical_url if identity else url,
        parse_depth="shallow",
        page_type="wiki",
    )


def _moegirl_scrape_raw(
    url: str,
    *,
    cookie_header: str = "",
    proxy: str = "",
) -> ParsedContent:
    """直接抓词条页并提取 og meta（含 ld+json 头图兜底）。"""
    _, text = http_get_text(url, timeout=12, cookie=cookie_header, proxy=proxy)
    title = ""
    match = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        text,
        re.IGNORECASE,
    )
    if match:
        title = html.unescape(match.group(1))
    if not title:
        match = re.search(r"<title[^>]*>([^<]+)</title>", text, re.IGNORECASE)
        if match:
            title = html.unescape(match.group(1))
    if not title:
        raise ParseHttpError("moegirl: no title in page")
    cover = ""
    match = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        text,
        re.IGNORECASE,
    )
    if match:
        cover = html.unescape(match.group(1))
    summary = ""
    match = re.search(
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
        text,
        re.IGNORECASE,
    )
    if match:
        summary = html.unescape(match.group(1))
    canonical = ""
    match = re.search(
        r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)',
        text,
        re.IGNORECASE,
    )
    if match:
        canonical = html.unescape(match.group(1))
    return build_parsed_content(
        platform="moegirl",
        item_id="",
        item_kind="article",
        title=title,
        summary=summary[:300],
        cover_url=cover,
        canonical_url=canonical or url,
        parse_depth="shallow",
        page_type="wiki",
    )


def _moegirl_community_post_card(url: str) -> ParsedContent:
    """社区帖（hash 路由 SPA）：服务端无内容可取，诚实降级入口卡。"""
    return build_parsed_content(
        platform="moegirl",
        item_id="",
        item_kind="post",
        title="萌娘百科社区帖",
        summary="（社区帖是前端渲染页面，机器人拿不到正文与互动数据；"
        "点开链接即可查看原帖）",
        canonical_url=url,
        parse_depth="shallow",
        page_type="community",
    )


def parse_moegirl(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """萌娘百科入口：词条 → api/og 深解析；社区帖 → 诚实浅卡。"""
    if "#/post/" in url or "#/" in url:
        return _moegirl_community_post_card(url)
    title = _moegirl_entry_title(url)
    if title:
        try:
            item = _moegirl_api_lookup(title, cookie_header=cookie_header, proxy=proxy)
            if item is not None:
                return item
        except Exception:  # noqa: BLE001, S110 - api 失败回退页面 og。
            pass
        try:
            return _moegirl_page_og(url, cookie_header=cookie_header, proxy=proxy)
        except Exception:  # noqa: BLE001, S110 - og 失败给静态词条卡。
            pass
        return build_parsed_content(
            platform="moegirl",
            item_id="",
            item_kind="article",
            title=title,
            summary=f"（萌娘百科词条「{title}」页面读取失败，点开链接查看）",
            canonical_url=url,
            parse_depth="shallow",
            page_type="wiki",
        )
    # 非词条路径（Special: 等）：og 尽力而为，再不行给静态卡。
    try:
        return _moegirl_page_og(url, cookie_header=cookie_header, proxy=proxy)
    except Exception:  # noqa: BLE001
        return build_parsed_content(
            platform="moegirl",
            item_id="",
            item_kind="page",
            title="萌娘百科页面",
            summary="（该页面无法直接提取内容，点开链接查看）",
            canonical_url=url,
            parse_depth="shallow",
        )

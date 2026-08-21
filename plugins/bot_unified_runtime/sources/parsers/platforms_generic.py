"""社交 / 视频 / 社区平台浅层解析（抖音、小红书、油管、推特、小黑盒、
米游社、森空岛、库街区）。

原则：能用公开 oEmbed / og meta 拿到标题、作者、封面就发信息卡；
需要登录 cookie / 逆向签名的平台明确标注 ``parse_depth=shallow``，
不伪造凭据，不下载视频（去水印留待后续按需接入）。
"""

from __future__ import annotations

import json
import re
import urllib.parse

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
    http_get_text,
    resolve_short_link,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_bilibili import PlatformParse

_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
    re.IGNORECASE,
)
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
    re.IGNORECASE,
)
_OG_DESC_RE = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
    re.IGNORECASE,
)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)


def _unescape_html(value: str) -> str:
    return (
        value.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .strip()
    )


def _og_scrape(
    url: str,
    *,
    platform: str,
    item_kind: str,
    note: str = "",
    referer: str = "",
) -> PlatformParse:
    final_url, text = http_get_text(url, timeout=10, referer=referer or url)
    title = ""
    match = _OG_TITLE_RE.search(text)
    if match:
        title = _unescape_html(match.group(1))
    if not title:
        match = _TITLE_TAG_RE.search(text)
        if match:
            title = _unescape_html(match.group(1))
    if not title:
        raise ParseHttpError(f"{platform}: no title in page")
    cover = ""
    match = _OG_IMAGE_RE.search(text)
    if match:
        cover = _unescape_html(match.group(1))
    summary = ""
    match = _OG_DESC_RE.search(text)
    if match:
        summary = _unescape_html(match.group(1))
        if len(summary) > 200:
            summary = summary[:200] + "…"
    if note and summary:
        summary = f"{note}\n{summary}"
    elif note:
        summary = note
    return PlatformParse(
        platform=platform,
        item_id="",
        item_kind=item_kind,
        title=title,
        summary=summary,
        cover_url=cover,
        canonical_url=final_url,
        parse_depth="shallow",
    )


def parse_douyin(url: str) -> PlatformParse:
    final_url = url
    if "v.douyin.com" in url:
        final_url = resolve_short_link(url)
    return _og_scrape(
        final_url,
        platform="douyin",
        item_kind="video",
        note="（浅层解析：标题+封面；无水印视频下载需另接解析服务）",
    )


def parse_xiaohongshu(url: str) -> PlatformParse:
    final_url = url
    if "xhslink.com" in url:
        final_url = resolve_short_link(url)
    return _og_scrape(
        final_url,
        platform="xiaohongshu",
        item_kind="note",
        note="（浅层解析；小红书正文/图集需要登录 cookie）",
    )


def parse_youtube(url: str) -> PlatformParse:
    try:
        payload = http_get_json(
            "https://www.youtube.com/oembed"
            f"?url={urllib.parse.quote(url)}&format=json",
            timeout=8,
        )
        return PlatformParse(
            platform="youtube",
            item_id="",
            item_kind="video",
            title=str(payload.get("title") or ""),
            author_name=str(payload.get("author_name") or ""),
            cover_url=str(payload.get("thumbnail_url") or ""),
            canonical_url=url,
            parse_depth="shallow",
        )
    except ParseHttpError:
        return _og_scrape(
            url,
            platform="youtube",
            item_kind="video",
            note="（元信息卡；下载需要 yt-dlp + 代理，未接入）",
        )


def parse_twitter_x(url: str) -> PlatformParse:
    return _og_scrape(
        url,
        platform="twitter",
        item_kind="tweet",
        note="（浅层解析；X 反爬严格，拿不到内容时只有标题）",
    )


def parse_xiaoheihe(url: str) -> PlatformParse:
    return _og_scrape(
        url,
        platform="xiaoheihe",
        item_kind="post",
        note="（浅层解析；小黑盒官方 API 需要逆向签名）",
    )


def parse_miyoushe(url: str) -> PlatformParse:
    return _og_scrape(url, platform="miyoushe", item_kind="post")


def parse_skland(url: str) -> PlatformParse:
    return _og_scrape(url, platform="skland", item_kind="article")


def parse_kurobbs(url: str) -> PlatformParse:
    return _og_scrape(url, platform="kurobbs", item_kind="post")

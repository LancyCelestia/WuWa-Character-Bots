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
    cookie_header: str = "",
) -> PlatformParse:
    final_url, text = http_get_text(
        url, timeout=10, referer=referer or url, cookie=cookie_header
    )
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


def parse_xiaohongshu(url: str, *, cookie_header: str = "") -> PlatformParse:
    """小红书：搜索页 → 关键词卡片；笔记页 → __INITIAL_STATE__ 深解析；
    失败回退 og 浅解析。"""
    final_url = url
    if "xhslink.com" in url:
        final_url = resolve_short_link(url)
    if "/search_result/" in final_url:
        return _xhs_search_result_card(final_url, cookie_header=cookie_header)
    if cookie_header:
        try:
            _, text = http_get_text(
                final_url,
                timeout=10,
                referer="https://www.xiaohongshu.com/",
                cookie=cookie_header,
            )
            item = _xhs_from_initial_state(text, final_url)
            if item is not None:
                return item
        except Exception:  # noqa: BLE001 - 深解析失败回退浅解析。
            pass
    return _og_scrape(
        final_url,
        platform="xiaohongshu",
        item_kind="note",
        note="（浅层解析；小红书正文/图集需要登录 cookie）",
        cookie_header=cookie_header,
    )


def _xhs_initial_state_payload(html: str) -> dict | None:
    """提取并清洗 window.__INITIAL_STATE__（含 undefined / new Map 等 JS 语法）。"""
    marker = "window.__INITIAL_STATE__="
    start = html.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = html.find("</script>", start)
    if end < 0:
        return None
    raw = html[start:end].strip().rstrip(";")
    raw = raw.replace("undefined", "null")
    raw = re.sub(r"new Map\(\[[^\]]*\]\)", "null", raw)
    for candidate in (raw, urllib.parse.unquote(raw)):
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return payload
        except Exception:  # noqa: BLE001
            continue
    return None


def _xhs_search_result_card(url: str, *, cookie_header: str = "") -> PlatformParse:
    """小红书搜索结果页：结果列表走签名接口，这里提取关键词出卡片。"""
    keyword = ""
    if cookie_header:
        try:
            _, text = http_get_text(
                url,
                timeout=10,
                referer="https://www.xiaohongshu.com/",
                cookie=cookie_header,
            )
            payload = _xhs_initial_state_payload(text) or {}
            search = payload.get("search") or {}
            hint = search.get("hintWord") or {}
            keyword = (
                str(hint.get("searchWord") or "")
                or str((search.get("searchContext") or {}).get("keyword") or "")
                or str(hint.get("title") or "")
            ).strip()
        except Exception:  # noqa: BLE001
            pass
    title = f"小红书搜索：{keyword}" if keyword else "小红书搜索结果页"
    return PlatformParse(
        platform="xiaohongshu",
        item_id="",
        item_kind="search",
        title=title,
        summary="（搜索结果列表需要登录态接口签名，这里只给入口；"
        "想看哪条笔记，请把具体笔记链接发我）",
        canonical_url=url,
        parse_depth="shallow",
    )


def _xhs_from_initial_state(html: str, url: str) -> PlatformParse | None:
    payload = _xhs_initial_state_payload(html)
    if payload is None:
        return None
    note_map = ((payload or {}).get("note") or {}).get("noteDetailMap") or {}
    if not note_map:
        return None
    note = next(iter(note_map.values())).get("note") or {}
    if not note.get("title"):
        return None
    user = note.get("user") or {}
    images = [
        str(image.get("urlDefault") or image.get("url") or "")
        for image in (note.get("imageList") or [])
        if image.get("urlDefault") or image.get("url")
    ]
    interact = note.get("interactInfo") or {}
    stats = {}
    for key, label in (("likedCount", "点赞"), ("collectedCount", "收藏"), ("commentCount", "评论"), ("shareCount", "分享")):
        value = interact.get(key)
        if isinstance(value, (int, float)):
            stats[label] = int(value)
    desc = str(note.get("desc") or "").strip()
    if len(desc) > 300:
        desc = desc[:300] + "…"
    return PlatformParse(
        platform="xiaohongshu",
        item_id=str(note.get("noteId") or ""),
        item_kind="video" if note.get("type") == "video" else "note",
        title=str(note.get("title") or ""),
        author_name=str(user.get("nickname") or ""),
        summary=desc,
        cover_url=images[0] if images else "",
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
    )


def parse_douyin(url: str, *, cookie_header: str = "") -> PlatformParse:
    """抖音：cookie 有效时从 _ROUTER_DATA 深解析（标题/作者/封面/互动）；
    页面被反爬验证拦截时给「已保留原链接」的降级卡片。"""
    final_url = url
    if "v.douyin.com" in url:
        final_url = resolve_short_link(url)
    video_id = ""
    match = re.search(r"/video/(\d+)", final_url)
    if match:
        video_id = match.group(1)
    if cookie_header:
        try:
            _, text = http_get_text(
                final_url,
                timeout=10,
                referer="https://www.douyin.com/",
                cookie=cookie_header,
            )
            item = _douyin_from_router_data(text, final_url)
            if item is not None:
                return item
            if len(text) < 2000:
                # 极小页面通常是反爬验证页，直接降级，不再走 og。
                raise ParseHttpError("douyin: anti-bot challenge page")
        except Exception:  # noqa: BLE001 - 深解析失败回退浅解析。
            pass
    og_item = None
    try:
        og_item = _og_scrape(
            final_url,
            platform="douyin",
            item_kind="video",
            note="（浅层解析：标题+封面；无水印视频下载需另接解析服务）",
            cookie_header=cookie_header,
        )
    except Exception:  # noqa: BLE001
        og_item = None
    if og_item is not None:
        return og_item
    return PlatformParse(
        platform="douyin",
        item_id=video_id,
        item_kind="video",
        title="抖音视频链接",
        summary="（抖音页面被反爬验证拦截，当前网络拿不到标题/封面；"
        "已保留原链接，稍后再试或直接打开观看）",
        canonical_url=final_url,
        parse_depth="blocked",
    )


def _douyin_from_router_data(html: str, url: str) -> PlatformParse | None:
    marker = "window._ROUTER_DATA"
    start = html.find(marker)
    if start < 0:
        return None
    start = html.find("{", start)
    if start < 0:
        return None
    end = html.find("</script>", start)
    if end < 0:
        return None
    try:
        payload = json.loads(html[start:end].rstrip(";"))
    except Exception:  # noqa: BLE001
        return None
    loader = (payload or {}).get("loaderData") or {}
    for key, value in loader.items():
        if not isinstance(value, dict):
            continue
        items = (value.get("videoInfoRes") or {}).get("item_list") or []
        if not items:
            continue
        item = items[0]
        author = item.get("author") or {}
        cover_list = (item.get("video") or {}).get("cover") or {}
        covers = cover_list.get("url_list") or []
        stats = (item.get("statistics") or {})
        mapped_stats = {}
        for stat_key, label in (("digg_count", "点赞"), ("comment_count", "评论"), ("share_count", "分享")):
            stat_value = stats.get(stat_key)
            if isinstance(stat_value, (int, float)):
                mapped_stats[label] = int(stat_value)
        desc = str(item.get("desc") or "").strip()
        if len(desc) > 300:
            desc = desc[:300] + "…"
        if not desc and not covers:
            continue
        return PlatformParse(
            platform="douyin",
            item_id=str(item.get("aweme_id") or ""),
            item_kind="video",
            title=desc or "抖音视频",
            author_name=str(author.get("nickname") or ""),
            cover_url=str(covers[0]) if covers else "",
            canonical_url=url,
            stats=mapped_stats,
            parse_depth="deep",
        )
    return None


def parse_youtube(url: str, *, cookie_header: str = "") -> PlatformParse:
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


def parse_twitter_x(url: str, *, cookie_header: str = "") -> PlatformParse:
    return _og_scrape(
        url,
        platform="twitter",
        item_kind="tweet",
        note="（浅层解析；X 反爬严格，拿不到内容时只有标题）",
        cookie_header=cookie_header,
    )


def parse_xiaoheihe(url: str, *, cookie_header: str = "") -> PlatformParse:
    return _og_scrape(
        url,
        platform="xiaoheihe",
        item_kind="post",
        note="（浅层解析；小黑盒官方 API 需要逆向签名）",
        cookie_header=cookie_header,
    )


def parse_miyoushe(url: str, *, cookie_header: str = "") -> PlatformParse:
    return _og_scrape(url, platform="miyoushe", item_kind="post", cookie_header=cookie_header)


def parse_skland(url: str, *, cookie_header: str = "") -> PlatformParse:
    return _og_scrape(url, platform="skland", item_kind="article", cookie_header=cookie_header)


def parse_kurobbs(url: str, *, cookie_header: str = "") -> PlatformParse:
    return _og_scrape(url, platform="kurobbs", item_kind="post", cookie_header=cookie_header)

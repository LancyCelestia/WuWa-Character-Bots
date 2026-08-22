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
from plugins.bot_unified_runtime.sources.parsers.types import PlatformParse

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
    proxy: str = "",
) -> PlatformParse:
    final_url, text = http_get_text(
        url, timeout=10, referer=referer or url, cookie=cookie_header, proxy=proxy
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
            proxy=proxy,
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


def parse_youtube(url: str, *, cookie_header: str = "", proxy: str = "") -> PlatformParse:
    if "/playlist" in url or "list=" in url and "watch" not in url:
        return _youtube_playlist(url, cookie_header=cookie_header, proxy=proxy)
    try:
        payload = http_get_json(
            "https://www.youtube.com/oembed"
            f"?url={urllib.parse.quote(url)}&format=json",
            timeout=8,
            proxy=proxy,
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
            cookie_header=cookie_header,
            proxy=proxy,
        )


def _youtube_playlist(url: str, *, cookie_header: str = "", proxy: str = "") -> PlatformParse:
    """油管歌单/播放列表：页面 og 元信息（标题/数量/封面）。"""
    try:
        return _og_scrape(
            url,
            platform="youtube",
            item_kind="playlist",
            cookie_header=cookie_header,
            proxy=proxy,
        )
    except ParseHttpError:
        return PlatformParse(
            platform="youtube",
            item_id="",
            item_kind="playlist",
            title="YouTube 播放列表",
            summary="（播放列表页面被限制访问，先给入口链接）",
            canonical_url=url,
            parse_depth="shallow",
        )


def parse_twitter_x(url: str, *, cookie_header: str = "", proxy: str = "") -> PlatformParse:
    """推特：优先 fxtwitter 公开聚合接口（正文/媒体/转赞评），失败回退 og。"""
    match = re.search(r"(?:twitter\.com|x\.com)/([^/]+)/status/(\d+)", url)
    if match:
        screen_name, status_id = match.group(1), match.group(2)
        try:
            payload = http_get_json(
                f"https://api.fxtwitter.com/{screen_name}/status/{status_id}",
                timeout=10,
                proxy=proxy,
            )
            tweet = payload.get("tweet") or {}
            if tweet.get("text"):
                author = tweet.get("author") or {}
                stats = {}
                for key, label in (
                    ("retweets", "转推"),
                    ("likes", "喜欢"),
                    ("replies", "评论"),
                    ("quotes", "引用"),
                ):
                    value = tweet.get(key)
                    if isinstance(value, (int, float)):
                        stats[label] = int(value)
                media = tweet.get("media") or {}
                photos = media.get("photos") or []
                videos = media.get("videos") or []
                gifs = media.get("gifs") or []
                summary_lines = [str(tweet.get("text") or "").strip()[:500]]
                media_note = []
                if photos:
                    media_note.append(f"图片 {len(photos)} 张")
                if videos:
                    media_note.append(f"视频 {len(videos)} 个")
                if gifs:
                    media_note.append(f"GIF {len(gifs)} 个")
                if media_note:
                    summary_lines.append("媒体：" + "、".join(media_note))
                cover = ""
                if photos:
                    cover = str(photos[0].get("url") or "")
                elif videos:
                    cover = str(videos[0].get("thumbnail_url") or "")
                created = tweet.get("created_at") or ""
                if created:
                    summary_lines.append(f"时间：{str(created)[:16]}")
                return PlatformParse(
                    platform="twitter",
                    item_id=status_id,
                    item_kind="tweet",
                    title=str(tweet.get("text") or "")[:40] or "推文",
                    author_name=f"{author.get('name') or ''}（@{author.get('screen_name') or screen_name}）",
                    summary="\n".join(summary_lines),
                    cover_url=cover,
                    canonical_url=url,
                    stats=stats,
                    parse_depth="deep",
                )
        except Exception:  # noqa: BLE001 - 聚合接口失败回退 og。
            pass
    return _og_scrape(
        url,
        platform="twitter",
        item_kind="tweet",
        note="（浅层解析；X 反爬严格，拿不到内容时只有标题）",
        cookie_header=cookie_header,
    )


def parse_pixiv(url: str, *, cookie_header: str = "") -> PlatformParse:
    """Pixiv 插画：官方 ajax 公开接口（标题/作者/分辨率/浏览/点赞/收藏/
    评论/标签/图片数量），失败回退页面 og。"""
    match = re.search(r"/artworks/(\d+)", url)
    if not match:
        raise ParseHttpError(f"pixiv: no artwork id in {url}")
    artwork_id = match.group(1)
    try:
        payload = http_get_json(
            f"https://www.pixiv.net/ajax/illust/{artwork_id}",
            referer="https://www.pixiv.net/",
            cookie=cookie_header,
        )
        body = payload.get("body") or {}
        if body.get("title"):
            tags = [str(t.get("tag")) for t in ((body.get("tags") or {}).get("tags") or [])]
            stats = {}
            for key, label in (
                ("viewCount", "浏览"),
                ("likeCount", "喜欢"),
                ("bookmarkCount", "收藏"),
                ("commentCount", "评论"),
            ):
                value = body.get(key)
                if isinstance(value, (int, float)):
                    stats[label] = int(value)
            width, height = body.get("width"), body.get("height")
            if width and height:
                stats["分辨率"] = f"{width}×{height}"
            page_count = body.get("pageCount")
            if page_count:
                stats["图片数量"] = int(page_count)
            type_labels = {0: "插画", 1: "漫画", 2: "动图"}
            kind_label = type_labels.get(int(body.get("illustType") or 0), "插画")
            summary_lines = [f"类型：{kind_label}"]
            if tags:
                summary_lines.append("标签：" + "、".join(tags[:12]))
            desc = str(body.get("description") or "").strip()
            if desc and len(desc) > 300:
                desc = desc[:300] + "…"
            if desc:
                summary_lines.append(f"简介：{desc}")
            # 作者粉丝/作品数（尽力而为）
            user_id = body.get("userId")
            if user_id:
                try:
                    user = http_get_json(
                        f"https://www.pixiv.net/ajax/user/{user_id}?full=1",
                        referer="https://www.pixiv.net/",
                        cookie=cookie_header,
                    )
                    ubody = user.get("body") or {}
                    follower = ubody.get("follower")
                    following = ubody.get("following")
                    if isinstance(follower, (int, float)):
                        summary_lines.append(f"作者粉丝：{int(follower)} · 关注：{int(following or 0)}")
                except Exception:  # noqa: BLE001
                    pass
            # 封面用 embed 代理图（QQ 可直接加载，避免 i.pximg.net 防盗链）
            cover = f"https://embed.pixiv.net/artwork.php?illust_id={artwork_id}"
            return PlatformParse(
                platform="pixiv",
                item_id=artwork_id,
                item_kind="illust",
                title=str(body.get("title") or ""),
                author_name=str(body.get("userName") or ""),
                summary="\n".join(summary_lines),
                cover_url=cover,
                canonical_url=url,
                stats=stats,
                parse_depth="deep",
            )
    except ParseHttpError:
        pass
    return _og_scrape(url, platform="pixiv", item_kind="illust", referer="https://www.pixiv.net/")


def _spa_link_card(
    url: str,
    *,
    platform: str,
    item_kind: str,
    label: str,
) -> PlatformParse:
    """动态渲染站点（无 og/无公开接口）：诚实降级为入口卡片。"""
    return PlatformParse(
        platform=platform,
        item_id="",
        item_kind=item_kind,
        title=f"{label} 链接",
        summary="（该站页面为动态渲染，机器人拿不到具体内容；先保留入口，"
        "点开即可查看）",
        canonical_url=url,
        parse_depth="shallow",
    )


def parse_lofter(url: str, *, cookie_header: str = "") -> PlatformParse:
    if "/post/" in url or "/lpost/" in url:
        return _og_scrape(url, platform="lofter", item_kind="post", cookie_header=cookie_header)
    if "/tag/" in url:
        return _spa_link_card(url, platform="lofter", item_kind="tag", label="Lofter 标签页")
    if "/selection" in url:
        return _spa_link_card(url, platform="lofter", item_kind="collection", label="Lofter 精选")
    if "/theme/" in url:
        return _spa_link_card(url, platform="lofter", item_kind="theme", label="Lofter 主题")
    return _spa_link_card(url, platform="lofter", item_kind="page", label="Lofter 页面")


def parse_allcpp(url: str, *, cookie_header: str = "") -> PlatformParse:
    match = re.search(r"event=(\d+)", url)
    if match:
        return _spa_link_card(
            url,
            platform="allcpp",
            item_kind="event",
            label=f"无差别同人站活动 {match.group(1)}",
        )
    return _spa_link_card(url, platform="allcpp", item_kind="page", label="无差别同人站")


def parse_mihuashi(url: str, *, cookie_header: str = "") -> PlatformParse:
    kind_map = (
        ("/profiles/", "painter", "米画师画师主页"),
        ("/projects/", "project", "米画师企划"),
        ("/stalls/", "stall", "米画师摊宣"),
        ("/artworks/", "artwork", "米画师作品"),
    )
    kind, label = "page", "米画师"
    for path_kind, kind_name, display in kind_map:
        if path_kind in url:
            kind, label = kind_name, display
            break
    return _spa_link_card(url, platform="mihuashi", item_kind=kind, label=label)


def parse_huajia(url: str, *, cookie_header: str = "") -> PlatformParse:
    kind_map = (
        ("/goods/details/", "goods", "网易画加约稿商品"),
        ("/projects/details/", "project", "网易画加企划"),
        ("/profile/", "painter", "网易画加画师主页"),
        ("/works/", "work", "网易画加作品"),
    )
    kind, label = "page", "网易画加"
    for path_kind, kind_name, display in kind_map:
        if path_kind in url:
            kind, label = kind_name, display
            break
    return _spa_link_card(url, platform="huajia", item_kind=kind, label=label)


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

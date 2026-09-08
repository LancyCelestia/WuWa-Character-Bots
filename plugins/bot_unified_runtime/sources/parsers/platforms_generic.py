"""社交 / 视频 / 社区平台浅层解析（抖音、小红书、油管、推特、小黑盒、
米游社、森空岛、库街区）+ Pixiv 扩展页面类型（小说/系列/用户/比赛/排行）。

原则：能用公开 oEmbed / og meta / 匿名 ajax 拿到标题、作者、封面就发信息卡；
需要登录 cookie / 逆向签名的平台明确标注 ``parse_depth=shallow``，
不伪造凭据，不下载视频（去水印留待后续按需接入）。
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from typing import Any

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
    parsed_cover_url,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
    http_get_text,
    http_post_json,
    resolve_short_link,
)

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
) -> ParsedContent:
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
    return build_parsed_content(
        platform=platform,
        item_id="",
        item_kind=item_kind,
        title=title,
        summary=summary,
        cover_url=cover,
        canonical_url=final_url,
        parse_depth="shallow",
    )


def _xhs_note_deep_parse(
    url: str, cookie_header: str = ""
) -> ParsedContent | None:
    """带登录态抓取笔记页并复用 INITIAL_STATE 归一化。"""
    try:
        _, html = http_get_text(
            url,
            timeout=10,
            referer="https://www.xiaohongshu.com/",
            cookie=cookie_header,
        )
    except ParseHttpError:
        return None
    return _xhs_from_initial_state(html, url)


def parse_xiaohongshu(
    url: str,
    *,
    cookie_header: str = "",
    playwright_backend=None,
) -> ParsedContent:
    """小红书：用户主页 → Playwright 深解析；搜索页 → 关键词卡片；
    笔记页 → __INITIAL_STATE__ 深解析；失败回退 og 浅解析。"""
    final_url = url
    if "xhslink.com" in url:
        final_url = resolve_short_link(url)
    # Canonical note path only; preserve the signed query string byte-for-byte.
    parsed = urllib.parse.urlsplit(final_url)
    if parsed.path.startswith("/discovery/item/"):
        final_url = urllib.parse.urlunsplit(parsed._replace(
            path=parsed.path.replace("/discovery/item/", "/explore/", 1)))
    if "/user/profile/" in final_url:
        if playwright_backend is None:
            return _xhs_user_profile_shallow(final_url, cookie_header=cookie_header)
        return _xhs_user_profile_card(final_url, playwright_backend, cookie_header)
    if "/search_result/" in final_url:
        return _xhs_search_result_card(final_url, cookie_header=cookie_header)
    if cookie_header:
        item = _xhs_note_deep_parse(final_url, cookie_header)
        if item is not None:
            return item
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
        except Exception:  # noqa: BLE001, S112 - 候选载荷解析失败继续下一候选。
            continue
    return None


def _xhs_search_result_card(url: str, *, cookie_header: str = "") -> ParsedContent:
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
        except Exception:  # noqa: BLE001, S110 - 关键词提取失败仅给入口卡。
            pass
    title = f"小红书搜索：{keyword}" if keyword else "小红书搜索结果页"
    return build_parsed_content(
        platform="xiaohongshu",
        item_id="",
        item_kind="search",
        title=title,
        summary="（搜索结果列表需要登录态接口签名，这里只给入口；"
        "想看哪条笔记，请把具体笔记链接发我）",
        canonical_url=url,
        parse_depth="shallow",
    )


def _format_epoch(value: object) -> str:
    """秒/毫秒时间戳 → 'YYYY-MM-DD HH:MM'；非法输入返回空串。"""
    try:
        num = int(str(value).strip())
    except (TypeError, ValueError):
        return ""
    if num <= 0:
        return ""
    if num > 10**12:
        num //= 1000
    if num < 10**9:
        return ""
    import datetime

    return datetime.datetime.fromtimestamp(num).strftime("%Y-%m-%d %H:%M")  # noqa: DTZ006 - 与站内其他解析保持本地时间口径。


def _parse_cn_count(value: object) -> int:
    """'1.2万'/'3亿'/123 → int；解析失败返回 0。"""
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        pass
    multiplier = 1
    if text.endswith("亿"):
        multiplier, text = 100000000, text[:-1]
    elif text.endswith("万"):
        multiplier, text = 10000, text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def _xhs_from_initial_state(html: str, url: str) -> ParsedContent | None:
    payload = _xhs_initial_state_payload(html)
    if payload is None:
        return None
    note_map = ((payload or {}).get("note") or {}).get("noteDetailMap") or {}
    if not note_map:
        return None
    note = next(iter(note_map.values())).get("note") or {}
    # 小红书 2026 版 INITIAL_STATE 常返回空 title，正文 desc 仍在：
    # 两者任一存在即视为拿到笔记（否则登录墙下全是空 title 被误判失败）。
    desc_raw = str(note.get("desc") or "").strip()
    title = str(note.get("title") or "").strip()
    if not title and not desc_raw:
        return None
    user = note.get("user") or {}
    images = [
        str(image.get("urlDefault") or image.get("url") or "")
        for image in (note.get("imageList") or [])
        if image.get("urlDefault") or image.get("url")
    ]
    interact = note.get("interactInfo") or {}
    stats: dict[str, object] = {}

    def _xhs_count(value: Any) -> int | None:
        """小红书计数是字符串（"1167"/"1.2万"）→ int。"""
        text = str(value or "").strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
        match = re.match(r"([\d.]+)\s*(万|w|W)", text)
        if match:
            return int(float(match.group(1)) * 10000)
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else None

    for key, label in (
        ("likedCount", "点赞"),
        ("collectedCount", "收藏"),
        ("commentCount", "评论"),
        ("shareCount", "分享"),
    ):
        count = _xhs_count(interact.get(key))
        if count is not None:
            stats[label] = count
    publish_time = _format_epoch(note.get("time") or note.get("lastUpdateTime"))
    if publish_time:
        stats["发布时间"] = publish_time
    author_detail: dict = {}
    if user.get("userId"):
        author_detail["uuid"] = str(user.get("userId"))
    if user.get("avatar"):
        author_detail["avatar"] = str(user.get("avatar"))
    if user.get("desc"):
        author_detail["signature"] = str(user.get("desc")).strip()

    def _xhs_video_stream(note: dict) -> str:
        """笔记视频直链（sns-video 原视频，无水印）：video.media.stream 优先。"""
        sources = [note.get("video") or {}]
        image_list = note.get("imageList") or []
        if image_list and isinstance(image_list[0], dict):
            sources.append(image_list[0].get("video") or {})
        for source in sources:
            media = (source or {}).get("media") or {}
            stream = (media or {}).get("stream") or {}
            if not isinstance(stream, dict):
                continue
            for kind in ("av1", "h264", "hls"):
                entries = stream.get(kind) or []
                for candidate in entries if isinstance(entries, list) else []:
                    if isinstance(candidate, dict) and candidate.get("url"):
                        return str(candidate["url"])
        return ""

    detail: dict = {"author": author_detail} if author_detail else {}
    if images:
        # 全图集进 media；封面取首图（builder 会按 cover_url 保持首图位）。
        detail["images"] = images
    video_url = _xhs_video_stream(note)
    if video_url:
        # 视频直链（sns-video 无水印）：URL + 封面/宽高/时长尽力补齐。
        video_meta: dict[str, Any] = {"url": video_url, "preview_url": images[0] if images else ""}
        video_source = note.get("video") or {}
        if isinstance(video_source, dict):
            for key in ("width", "height", "duration"):
                value = video_source.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    video_meta[key] = int(value)
        detail["video"] = video_meta
    desc = desc_raw
    if len(desc) > 300:
        desc = desc[:300] + "…"
    if not title:
        # 空标题用正文首行截断（与端内展示一致），避免卡上标题区空白。
        first_line = next((line for line in desc.splitlines() if line.strip()), "")
        title = first_line[:40] or "小红书笔记"
    return build_parsed_content(
        platform="xiaohongshu",
        item_id=str(note.get("noteId") or ""),
        item_kind="video" if note.get("type") == "video" else "note",
        title=title,
        author_name=str(user.get("nickname") or ""),
        summary=desc,
        cover_url=images[0] if images else "",
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        detail=detail,
    )


_XHS_USER_PROFILE_RE = re.compile(r"xiaohongshu\.com/user/profile/([0-9a-zA-Z]+)")


def _xhs_cookie_pairs(cookie_header: str) -> list[dict]:
    """把 Cookie 头拆成 Playwright add_cookies 需要的 name/value 列表。"""
    cookies: list[dict] = []
    for chunk in (cookie_header or "").split(";"):
        pair = chunk.strip()
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        name = name.strip()
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": ".xiaohongshu.com",
                "path": "/",
            }
        )
    return cookies


def _xhs_user_note_digest(note: dict) -> dict:
    """把 user_posted / INITIAL_STATE 两种命名字段的笔记规整成摘要字段。"""
    user = note.get("user") or note.get("userInfo") or {}
    if not isinstance(user, dict):
        user = {}
    interact = note.get("interact_info") or note.get("interactInfo") or {}
    if not isinstance(interact, dict):
        interact = {}
    liked = interact.get("liked_count")
    if liked is None:
        liked = interact.get("likedCount")
    collected = interact.get("collected_count")
    if collected is None:
        collected = interact.get("collectedCount")
    title = str(note.get("display_title") or note.get("title") or "").strip()
    cover = ""
    cover_obj = note.get("cover") or {}
    if isinstance(cover_obj, dict):
        cover = str(
            cover_obj.get("url_default")
            or cover_obj.get("url")
            or cover_obj.get("url_pre")
            or ""
        )
        if not cover:
            for info in cover_obj.get("info_list") or []:
                if isinstance(info, dict) and info.get("url"):
                    cover = str(info["url"])
                    break
    if not cover:
        images = note.get("imageList") or note.get("images") or []
        for image in images:
            if isinstance(image, dict) and (
                image.get("urlDefault") or image.get("url")
            ):
                cover = str(image.get("urlDefault") or image.get("url"))
                break
    nickname = str(
        user.get("nickname")
        or user.get("nick_name")
        or user.get("nickName")
        or ""
    ).strip()
    return {
        "title": title,
        "liked_count": liked if liked not in (None, "") else 0,
        "collected_count": collected if collected not in (None, "") else 0,
        "cover_url": cover,
        "nickname": nickname,
    }


def _xhs_user_notes_from_capture(payloads: list[dict]) -> list[dict]:
    """从 capture_json 命中的响应里收集 user_posted 的 notes。"""
    notes: list[dict] = []
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        data = payload.get("data")
        raw_notes = (
            data.get("notes") if isinstance(data, dict) else payload.get("notes")
        )
        if not isinstance(raw_notes, list):
            continue
        for note in raw_notes:
            if not isinstance(note, dict):
                continue
            digest = _xhs_user_note_digest(note)
            if digest["title"]:
                notes.append(digest)
    return notes


def _xhs_user_nickname_from_capture(payloads: list[dict]) -> str:
    """从接口响应的首条笔记 user 字段取昵称（缺失时交给调用方降级）。"""
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        data = payload.get("data")
        raw_notes = (
            data.get("notes") if isinstance(data, dict) else payload.get("notes")
        )
        if not isinstance(raw_notes, list):
            continue
        for note in raw_notes:
            if not isinstance(note, dict):
                continue
            nickname = _xhs_user_note_digest(note).get("nickname")
            if nickname:
                return str(nickname)
    return ""


def _xhs_user_profile_result(
    user_id: str,
    url: str,
    nickname: str,
    notes: list[dict],
    *,
    extra_stats: dict | None = None,
    author_detail: dict | None = None,
) -> ParsedContent:
    """把用户主页数据组装成深度用户卡片。"""
    summary_lines = []
    for note in notes[:6]:
        title = note.get("title") or "未命名笔记"
        liked = note.get("liked_count") or 0
        collected = note.get("collected_count") or 0
        summary_lines.append(f"《{title}》 {liked}赞·{collected}藏")
    cover_url = ""
    for note in notes:
        if note.get("cover_url"):
            cover_url = str(note["cover_url"])
            break
    stats: dict[str, object] = {"笔记数": len(notes)}
    if extra_stats:
        stats.update(extra_stats)
    return build_parsed_content(
        platform="xiaohongshu",
        item_id=user_id,
        item_kind="user",
        title=nickname or f"小红书用户 {user_id}",
        author_name=nickname,
        summary="\n".join(summary_lines),
        cover_url=cover_url,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        detail={"author": author_detail} if author_detail else {},
    )


def _xhs_user_profile_from_initial_state(
    html: str, url: str, user_id: str
) -> ParsedContent | None:
    """从用户主页 SSR 的 __INITIAL_STATE__ 提取昵称与笔记标题。"""
    payload = _xhs_initial_state_payload(html)
    if payload is None:
        return None
    user_state = payload.get("user") or {}
    if not isinstance(user_state, dict):
        user_state = {}
    page_data = user_state.get("userPageData") or {}
    if not isinstance(page_data, dict):
        page_data = {}
    basic = page_data.get("basicInfo") or {}
    if not isinstance(basic, dict):
        basic = {}
    nickname = str(
        basic.get("nickname")
        or basic.get("nickName")
        or user_state.get("nickname")
        or ""
    ).strip()
    raw_notes = user_state.get("notes") or page_data.get("notes") or []
    if not isinstance(raw_notes, list):
        raw_notes = []
    notes: list[dict] = []
    for note in raw_notes:
        if not isinstance(note, dict):
            continue
        digest = _xhs_user_note_digest(note)
        if digest["title"]:
            notes.append(digest)
    if not nickname:
        for note in notes:
            if note.get("nickname"):
                nickname = str(note["nickname"])
                break
    if not nickname and not notes:
        return None
    interactions = page_data.get("interactions")
    extra_stats: dict[str, int] = {}
    if isinstance(interactions, list):
        for row in interactions:
            if not isinstance(row, dict):
                continue
            count = _parse_cn_count(row.get("count"))
            if count <= 0:
                continue
            itype = str(row.get("type") or "")
            if itype == "fans":
                extra_stats["粉丝"] = count
            elif itype == "follows":
                extra_stats["关注"] = count
            elif itype == "interaction":
                extra_stats["获赞"] = count
    author_detail: dict = {}
    if user_id:
        author_detail["uuid"] = str(user_id)
    desc = str(basic.get("desc") or "").strip()
    if desc:
        author_detail["signature"] = desc
    return _xhs_user_profile_result(
        user_id,
        url,
        nickname,
        notes,
        extra_stats=extra_stats,
        author_detail=author_detail,
    )


def _xhs_user_profile_shallow(url: str, cookie_header: str = "") -> ParsedContent:
    """用户主页 og 浅层降级卡。"""
    return _og_scrape(
        url,
        platform="xiaohongshu",
        item_kind="user",
        note="（浅层解析；小红书用户主页需要登录态）",
        cookie_header=cookie_header,
    )


def _xhs_user_profile_card(
    url: str, backend: object, cookie_header: str = ""
) -> ParsedContent:
    """用户主页：先抓 user_posted 接口，再解析 __INITIAL_STATE__，最后 og。"""
    match = _XHS_USER_PROFILE_RE.search(url)
    if match is None:
        raise ParseHttpError("xiaohongshu: 用户主页 URL 缺少 user_id")
    user_id = match.group(1)
    cookies = _xhs_cookie_pairs(cookie_header)
    payloads: list[dict] = []
    try:
        payloads = backend.capture_json(  # type: ignore[attr-defined]
            url,
            cookies=cookies,
            json_filter="/api/sns/web/v1/user_posted",
        )
    except Exception:  # noqa: BLE001 - 接口失败再尝试页面状态解析。
        payloads = []
    notes = _xhs_user_notes_from_capture(payloads)
    nickname = _xhs_user_nickname_from_capture(payloads)
    if notes:
        return _xhs_user_profile_result(user_id, url, nickname, notes)
    try:
        _, html = backend.fetch_html(url, cookies=cookies)  # type: ignore[attr-defined]
        item = _xhs_user_profile_from_initial_state(html, url, user_id)
        if item is not None:
            return item
    except Exception:  # noqa: BLE001, S110 - 页面状态解析失败回退 og。
        pass
    return _xhs_user_profile_shallow(url, cookie_header)


def parse_douyin(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """抖音：cookie 有效时从 _ROUTER_DATA 深解析（标题/作者/封面/互动）；
    页面被反爬验证拦截时给「已保留原链接」的降级卡片。精选页
    ``/jingxuan?modal_id=...`` 会先把 modal_id 归一成 /video/ 链接复用同链路。"""
    final_url = url
    if "v.douyin.com" in url:
        final_url = resolve_short_link(url)
    modal_match = re.search(r"[?&]modal_id=(\d+)", final_url)
    if modal_match and "/video/" not in final_url:
        # 精选弹窗页与视频页同源：modal_id 即视频 id。
        final_url = f"https://www.douyin.com/video/{modal_match.group(1)}"
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
        except Exception:  # noqa: BLE001, S110 - 深解析失败回退浅解析。
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
    return build_parsed_content(
        platform="douyin",
        item_id=video_id,
        item_kind="video",
        title="抖音视频链接",
        summary="（抖音页面被反爬验证拦截，当前网络拿不到标题/封面；"
        "已保留原链接，稍后再试或直接打开观看）",
        canonical_url=final_url,
        parse_depth="blocked",
    )


def _douyin_from_router_data(html: str, url: str) -> ParsedContent | None:
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
    for value in loader.values():
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
        mapped_stats: dict[str, object] = {}
        for stat_key, label in (
            ("digg_count", "点赞"),
            ("comment_count", "评论"),
            ("share_count", "分享"),
            ("play_count", "播放"),
            ("collect_count", "收藏"),
        ):
            stat_value = stats.get(stat_key)
            if isinstance(stat_value, (int, float)):
                mapped_stats[label] = int(stat_value)
        publish_time = _format_epoch(item.get("create_time"))
        if publish_time:
            mapped_stats["发布时间"] = publish_time
        author_detail: dict = {}
        unique_id = str(author.get("unique_id") or "").strip()
        if unique_id:
            author_detail["uuid"] = unique_id
        if author.get("signature"):
            author_detail["signature"] = str(author["signature"])
        if author.get("avatar"):
            author_detail["avatar"] = str(author["avatar"])
        desc = str(item.get("desc") or "").strip()
        if len(desc) > 300:
            desc = desc[:300] + "…"
        if not desc and not covers:
            continue
        return build_parsed_content(
            platform="douyin",
            item_id=str(item.get("aweme_id") or ""),
            item_kind="video",
            title=desc or "抖音视频",
            author_name=str(author.get("nickname") or ""),
            cover_url=str(covers[0]) if covers else "",
            canonical_url=url,
            stats=mapped_stats,
            parse_depth="deep",
            detail={"author": author_detail} if author_detail else {},
        )
    return None


_YOUTUBE_ID_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{6,})")


def _yt_unescape(value: str) -> str:
    """YouTube 页面 JSON 文本：处理 \\n/\\u0026 与 \\uXXXX 转义。

    页面里中文可能是字面 UTF-8，也可能是 \\uXXXX 转义；只在出现转义
    序列时才做 unicode_escape 解码，避免破坏字面中文。
    """
    text = str(value or "").replace("\\n", " ").replace("\\u0026", "&")
    if "\\u" in text:
        try:
            return text.encode("utf-8").decode("unicode_escape", errors="ignore")
        except Exception:  # noqa: BLE001 - 解码失败保留原文。
            return text
    return text


def _truncate_keep_links(text: str, limit: int) -> str:
    """截断文本但保留尾部链接（博主自写跨平台链接不丢）。"""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:limit].rstrip()
    # URL 恰被 limit 切断时：head 尾部是半个链接 → 回退到链接起点，
    # 并从原文取完整 URL 追加（保链接优先于保前文）。
    half_url = re.search(r"https?://\S*$", head)
    if half_url:
        head = head[: half_url.start()].rstrip()
        full_url = re.match(r"https?://\S+", text[half_url.start() :])
        if full_url:
            tail = full_url.group(0)
            more = re.findall(r"https?://[^\s，。；]+", text[half_url.start() + len(tail) :])
            if more:
                tail += " " + more[0]
            return f"{head} … {tail}"
    # 截断后若原文剩余部分仍有 http 链接，追加一条。
    tail_links = re.findall(r"https?://[^\s，。；]+", text[limit:])
    if tail_links:
        return f"{head} … {tail_links[0]}"
    return head + "…"


def _youtube_innertube(video_id: str, *, proxy: str) -> dict[str, Any]:
    """Innertube 匿名端点拿播放量/发布时间/点赞/评论/作者；尽力而为。

    watch 页 HTML 对匿名请求时全时精简（无计数），player/next JSON 端点更稳。
    """
    info: dict[str, Any] = {}
    context: dict[str, Any] = {
        "context": {
            "client": {"clientName": "WEB", "clientVersion": "2.20240701.01.00", "hl": "zh-CN"}
        },
        "videoId": video_id,
    }
    player: dict[str, Any] = {}
    try:
        player = http_post_json(
            "https://www.youtube.com/youtubei/v1/player",
            context,
            timeout=15,
            proxy=proxy,
            referer="https://www.youtube.com/",
        ) or {}
    except Exception:  # noqa: BLE001, S110 - player 失败交给 watch 页正则兜底。
        pass
    details = player.get("videoDetails") or {}
    view_count = str(details.get("viewCount") or "")
    if view_count.isdigit():
        info["浏览量"] = int(view_count)
    micro = ((player.get("microformat") or {}).get("playerMicroformatRenderer")) or {}
    publish = str(micro.get("publishDate") or micro.get("uploadDate") or "")
    if publish:
        info["_publish_date"] = publish[:10]
    if details.get("author"):
        info["_author_name"] = str(details["author"])
    if details.get("authorId"):
        info["_channel_url"] = f"https://www.youtube.com/channel/{details['authorId']}"

    next_text = ""
    try:
        next_payload = http_post_json(
            "https://www.youtube.com/youtubei/v1/next",
            context,
            timeout=15,
            proxy=proxy,
            referer="https://www.youtube.com/",
        )
        next_text = json.dumps(next_payload, ensure_ascii=False) if next_payload else ""
    except Exception:  # noqa: BLE001, S110 - next 失败只少点赞/评论。
        pass
    if next_text:
        match = re.search(r'"commentCount":\{"simpleText":"([\d,.]+[万亿]?)"', next_text)
        if match:
            comment_text = match.group(1).replace(",", "")
            if comment_text.isdigit():
                info["评论"] = int(comment_text)
        for pattern in (
            r'"accessibilityText":"([^"]*?)([\d,.]+[万亿]?)\s*(?:个其他用户|人觉得很?赞|likes)"',
            r'"likeCount":\{"content":"([\d,.]+[万亿]?)"\}',
        ):
            match = re.search(pattern, next_text)
            if match:
                like_text = (match.group(1) + match.group(2)).replace(",", "")
                like_text = re.sub(r"[^\d]", "", like_text.split("个")[0] if "个" in like_text else like_text)
                if like_text.isdigit():
                    info["点赞"] = int(like_text)
                break
        avatar_match = re.search(
            r'"avatar":\{"thumbnails":\[\{"url":"(https://yt3\.ggpht\.com[^"]+)"', next_text
        )
        if avatar_match:
            info["_avatar"] = avatar_match.group(1).replace("\\u0026", "&")
    return info


def _youtube_watch_enrich(url: str, *, proxy: str) -> dict[str, Any]:
    """watch 页尽力提取互动数据与作者信息；任何失败返回空 dict。

    提取项：播放量/点赞/评论数/发布时间/作者名/频道头像/频道链接/认证徽章。
    """
    info: dict[str, Any] = {}
    try:
        _, html = http_get_text(
            url,
            timeout=15,
            proxy=proxy,
            referer="https://www.youtube.com/",
            extra_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6"},
        )
    except Exception:  # noqa: BLE001 - 观看页不可达时其余字段留空。
        return info

    def _rx(pattern: str, group: int = 1) -> str:
        match = re.search(pattern, html)
        return match.group(group).strip() if match else ""

    view_count = _rx(r'"viewCount":"(\d+)"')
    if view_count.isdigit():
        info["浏览量"] = int(view_count)
    duration = _rx(r'"lengthSeconds":"(\d+)"')
    if duration.isdigit():
        info["时长"] = int(duration)
    video_desc = _rx(r'"shortDescription":"((?:[^"\\]|\\.)*?)"')
    if video_desc:
        info["_video_desc"] = _yt_unescape(video_desc)[:300]
    publish_date = _rx(r'"publishDate":"([\d-]{8,10})') or _rx(
        r'"uploadDate":"([\d-]{8,10})'
    )
    if publish_date:
        info["_publish_date"] = publish_date
    # 点赞：多套页面结构依次尝试（中英文页面格式不同）。
    for pattern in (
        r'"expandedLikeCountWithCount":\{"content":"([\d,.]+[万亿]?)',
        r'"accessibilityText":"[^"]*?([\d,.]+[万亿]?)\s*(?:个其他用户|人觉得很?赞|likes)"',
        r'"likeCount":\{"content":"([\d,.]+[万亿]?)',
    ):
        like_text = _rx(pattern).replace(",", "")
        if like_text.isdigit():
            info["点赞"] = int(like_text)
            break
    like_plain = _rx(r'"likeCount":"([\d,.]+)"')
    if "点赞" not in info and like_plain.replace(",", "").isdigit():
        info["点赞"] = int(like_plain.replace(",", ""))
    # 订阅数：watch 页页头就有（"12.8万位订阅者"），不必等 about 页。
    subscriber_label = _rx(
        r'"subscriberCountText":\{"accessibility":\{"accessibilityData":\{"label":"([^"]{1,40})'
    ) or _rx(r'"subscriberCountText":"([^"]{1,40})"')
    subscriber_count = _yt_count(subscriber_label)
    if subscriber_count is not None:
        info["订阅"] = subscriber_count
    # 频道链接：channelUrl 缺失时用 canonicalBaseUrl（/@handle）拼。
    channel_path = _rx(r'"canonicalBaseUrl":"(/@[^"]+)"')
    if channel_path:
        info["_channel_url"] = "https://www.youtube.com" + channel_path.replace("\\u0026", "&")
    if "_avatar" not in info:
        avatar_any = _rx(r'"url":"(https://yt3\.ggpht\.com[^"]+)"')
        if avatar_any:
            info["_avatar"] = avatar_any.replace("\\u0026", "&")
    for pattern in (
        r'"commentCount":\{"simpleText":"([\d,.]+[万亿]?)"\}',
        r'"commentCount":\{"content":"([\d,.]+[万亿]?)"\}',
        r'"text":"([\d,.]+[万亿]?)\s*条评论"',
    ):
        comment_text = _rx(pattern).replace(",", "")
        if comment_text.isdigit():
            info["评论"] = int(comment_text)
            break
    author_name = _rx(r'"author":"((?:[^"\\]|\\.)*?)"')
    if author_name:
        info["_author_name"] = _yt_unescape(author_name)
    avatar = _rx(r'"avatar":\{"thumbnails":\[\{"url":"(https://yt3\.ggpht\.com[^"]+)"')
    if avatar:
        info["_avatar"] = avatar.replace("\\u0026", "&")
    channel_url = _rx(r'"channelUrl":"(https://www\.youtube\.com/(?:channel|@)[^"]+)"')
    if channel_url:
        info["_channel_url"] = channel_url.replace("\\u0026", "&")
    if '"ownerBadges":[{"metadataBadgeRenderer":{"style":"BADGE_STYLE_TYPE_VERIFIED"' in html:
        info["_verified"] = True
    return info


def _yt_count(value: Any) -> int | None:
    """'5.6万位订阅者'/'1.2M subscribers'/123 → int；失败返回 None。"""
    match = re.match(r"([\d,.]+)\s*([万亿KMB]?)", str(value or "").strip())
    if not match:
        return None
    text = match.group(1).replace(",", "")
    if not text.replace(".", "").isdigit():
        return None
    multiplier = {
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
        "万": 10_000,
        "亿": 100_000_000,
    }.get(match.group(2), 1)
    return int(float(text) * multiplier)


def _youtube_about_enrich(channel_url: str, *, proxy: str) -> dict[str, Any]:
    """频道 about 页尽力提取：简介/注册日期/订阅数/视频数；失败返回空 dict。"""
    info: dict[str, Any] = {}
    if not channel_url:
        return info
    try:
        _, html = http_get_text(
            f"{channel_url}/about",
            timeout=15,
            proxy=proxy,
            referer="https://www.youtube.com/",
            extra_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6"},
        )
    except Exception:  # noqa: BLE001 - about 页不可达时字段留空。
        return info

    def _rx(pattern: str) -> str:
        match = re.search(pattern, html)
        return match.group(1).strip() if match else ""

    joined = _rx(r'"joinedDateText":\{"content":"([^"]{4,40})')
    if joined:
        info["_joined"] = joined
    description = _rx(r'\{"aboutChannelViewModel":\{"description":"((?:[^"\\]|\\.)*?)"')
    if not description:
        description = _rx(r'"description":"((?:[^"\\]|\\.)*?)"')
    if description:
        info["_description"] = _truncate_keep_links(_yt_unescape(description), 300)
    # 订阅/视频/总播放：2026 版 about 页为字符串形态（"12.8万位订阅者"），
    # 旧 {"content":...} 形态保留兜底。
    subscriber = _rx(r'"subscriberCountText":"([^"]{1,30})') or _rx(
        r'"subscriberCountText":\{"content":"([^"]{1,30})'
    )
    subscriber_count = _yt_count(subscriber)
    if subscriber_count is not None:
        info["订阅"] = subscriber_count
    video_count = _rx(r'"videoCountText":"([\d,.]+[万亿]?[个]?)') or _rx(
        r'"videoCountText":\{"content":"([\d,.]+[万亿]?)"\}'
    )
    video_digits = re.sub(r"[^\d]", "", video_count)
    if video_digits.isdigit():
        info["视频数"] = int(video_digits)
    total_views = _rx(r'"viewCountText":"([\d,.]+)')
    total_digits = total_views.replace(",", "")
    if total_digits.isdigit():
        info["总播放"] = int(total_digits)
    channel_id = _rx(r'"channelId":"(UC[\w-]{10,})"')
    if channel_id:
        info["_channel_id"] = channel_id
    if '"verified":true' in html:
        info["_verified"] = True
    return info




_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

_YT_SUBSCRIBER_RE = re.compile(
    r"([\d.,]+)\s*(万|千|K|M|百万|订阅者|subscribers?)", re.IGNORECASE
)


def _parse_count_text(text: str) -> int | None:
    match = re.search(r"([\d.,]+)\s*(万|千|[KMB])", text, re.IGNORECASE)
    if not match:
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else None
    number = float(match.group(1).replace(",", ""))
    unit = match.group(2).upper()
    multiplier = {"万": 10000, "千": 1000, "K": 1000, "M": 1000000, "B": 1000000000}.get(unit, 1)
    return int(number * multiplier)


def _youtube_channel_about(channel_url: str, *, proxy: str = "") -> dict:
    """抓频道页 from-about 区块（订阅数/视频数/简介/加入时间/国家）。"""
    try:
        _, html_text = http_get_text(
            channel_url + "/about", user_agent=_UA, timeout=12, proxy=proxy
        )
    except Exception:  # noqa: BLE001 - about 抓取失败返回空。
        return {}
    info: dict[str, str] = {}
    for key in ("subscriberCountText", "videoCountText", "joinedDateText", "viewCountText", "description"):
        match = re.search(rf'"{key}":{{"content":"([^"]{{0,200}})"', html_text)
        if match:
            info[key] = (
                match.group(1)
                .replace("\n", " ")
                .replace("\u0026", "&")
                .encode().decode("unicode_escape", errors="ignore")
            )
    return info


def parse_youtube(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    # 社区帖（/post/...）：oEmbed 不支持，直接 og 抓页面元信息。
    if "/post/" in url:
        try:
            return _og_scrape(
                url,
                platform="youtube",
                item_kind="post",
                cookie_header=cookie_header,
                proxy=proxy,
                referer="https://www.youtube.com/",
            )
        except ParseHttpError:
            return build_parsed_content(
                platform="youtube",
                item_id="",
                item_kind="post",
                title="YouTube 社区帖",
                summary="（社区帖页面不可达，已保留原链接）",
                canonical_url=url,
                parse_depth="shallow",
            )
    # shorts 直链归一成 watch 链接（oEmbed/页面两条链路都更稳）。
    shorts_match = _YOUTUBE_ID_RE.search(url)
    video_id = shorts_match.group(1) if shorts_match else ""
    if "youtube.com/shorts/" in url and video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"
    if "/playlist" in url or "list=" in url and "watch" not in url:
        return _youtube_playlist(url, cookie_header=cookie_header, proxy=proxy)
    payload: dict | None = None
    for attempt in range(2):
        try:
            payload = http_get_json(
                "https://www.youtube.com/oembed"
                f"?url={urllib.parse.quote(url)}&format=json",
                timeout=15,
                proxy=proxy,
            )
            break
        except Exception:  # noqa: BLE001 - oEmbed 失败短停重试一次再走 og。
            payload = None
            if attempt == 0:
                time.sleep(1.5)
    if payload is None:
        return _og_scrape(
            url,
            platform="youtube",
            item_kind="video",
            note="（元信息卡；下载需要 yt-dlp + 代理，未接入）",
            cookie_header=cookie_header,
            proxy=proxy,
        )
    author_detail: dict = {}
    author_url = str(payload.get("author_url") or "")
    if "/@" in author_url:
        handle = author_url.rsplit("/@", 1)[1].split("/")[0].split("?")[0]
        if handle:
            author_detail["handle"] = f"@{handle}"
    # 两跳深抓：watch 页互动数据 → 频道 about 页博主资料。全部尽力而为。
    stats: dict[str, int] = {}
    watch_info = _youtube_watch_enrich(url, proxy=proxy)
    if video_id:
        # Innertube 结构化端点补齐点赞/评论/头像/频道 ID（watch 页匿名
        # 精简后常缺这些）；非空值覆盖 watch 页正则结果。
        try:
            innertube_info = _youtube_innertube(video_id, proxy=proxy)
        except Exception:  # noqa: BLE001 - innertube 失败交给 watch 页结果。
            innertube_info = {}
        for key, value in innertube_info.items():
            if value not in (None, ""):
                watch_info[key] = value
    for key in ("浏览量", "点赞", "评论", "时长"):
        if key in watch_info:
            stats[key] = watch_info[key]
    if watch_info.get("_publish_date"):
        stats["发布时间"] = watch_info["_publish_date"]
    if watch_info.get("_author_name"):
        author_detail["_watch_author_name"] = watch_info["_author_name"]
    if watch_info.get("_avatar"):
        author_detail["avatar"] = watch_info["_avatar"]
    if watch_info.get("订阅"):
        stats["订阅"] = watch_info["订阅"]
    channel_url = str(watch_info.get("_channel_url") or "")
    if "/channel/" in channel_url:
        # 频道 ID（UC 开头）稳定唯一，进 creator.platform_creator_id。
        channel_id = channel_url.rsplit("/channel/", 1)[1].split("/")[0].split("?")[0]
        if channel_id:
            author_detail["uuid"] = channel_id
    video_desc = str(watch_info.get("_video_desc") or "").strip()
    about_info = _youtube_about_enrich(watch_info.get("_channel_url", ""), proxy=proxy)
    if about_info.get("_description") and not author_detail.get("signature"):
        author_detail["signature"] = about_info["_description"]
    if about_info.get("_joined"):
        author_detail["created_at"] = about_info["_joined"]
    if about_info.get("_channel_id") and not author_detail.get("uuid"):
        author_detail["uuid"] = about_info["_channel_id"]
    if about_info.get("订阅"):
        stats["订阅"] = about_info["订阅"]
    if about_info.get("视频数"):
        stats["视频数"] = about_info["视频数"]
    if about_info.get("总播放"):
        stats["总播放"] = about_info["总播放"]
    if about_info.get("_verified") or watch_info.get("_verified"):
        author_detail["official_badge"] = "YouTube 认证频道"
    author_name = str(payload.get("author_name") or "")
    detail: dict = {"author": author_detail} if author_detail else {}
    if watch_info.get("时长"):
        # 时长/预览进 video 元数据 → builder 生成 video 媒体资产。
        detail["video"] = {
            "duration": watch_info["时长"],
            "preview_url": str(payload.get("thumbnail_url") or ""),
        }
    return build_parsed_content(
        platform="youtube",
        item_id=video_id,
        item_kind="video",
        title=str(payload.get("title") or ""),
        author_name=author_name,
        summary=video_desc,
        cover_url=str(payload.get("thumbnail_url") or ""),
        canonical_url=url,
        stats=stats,
        parse_depth="deep" if stats else "shallow",
        detail=detail,
    )


def _youtube_playlist(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
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
        return build_parsed_content(
            platform="youtube",
            item_id="",
            item_kind="playlist",
            title="YouTube 播放列表",
            summary="（播放列表页面被限制访问，先给入口链接）",
            canonical_url=url,
            parse_depth="shallow",
        )


def parse_twitter_x(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
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
            # 门槛 = 接口成功且有 tweet 对象：纯媒体推文 text 为空也走深分支，
            # 否则会掉进 og 兜底被 X 登录墙拒绝（"no title in page"）。
            if payload.get("code") == 200 and tweet:
                raw_text = str((tweet.get("raw_text") or {}).get("text") or "").strip()
                tweet_text = str(tweet.get("text") or "").strip() or raw_text
                author = tweet.get("author") or {}
                stats: dict[str, object] = {}
                for key, label in (
                    ("retweets", "转发"),
                    ("likes", "点赞"),
                    ("replies", "评论"),
                    ("quotes", "引用"),
                ):
                    value = tweet.get(key)
                    if isinstance(value, (int, float)):
                        stats[label] = int(value)
                views = tweet.get("views")
                views_count = views.get("count") if isinstance(views, dict) else views
                if isinstance(views_count, (int, float)) or (
                    isinstance(views_count, str) and views_count.isdigit()
                ):
                    stats["浏览量"] = int(views_count)
                created_ts = tweet.get("created_timestamp")
                if isinstance(created_ts, (int, float)) and created_ts > 0:
                    publish_time = _format_epoch(created_ts)
                else:
                    publish_time = _format_epoch(tweet.get("created_at"))
                if publish_time:
                    stats["发布时间"] = publish_time
                author_detail: dict = {}
                screen = str(author.get("screen_name") or screen_name or "").strip()
                if screen:
                    author_detail["handle"] = f"@{screen}"
                if author.get("avatar_url"):
                    author_detail["avatar"] = str(author["avatar_url"])
                bio = str(author.get("description") or "").strip()
                if bio:
                    author_detail["signature"] = bio
                # 博主资料：粉丝/关注/帖子数/注册日期/认证（fxtwitter author 全提供）。
                followers = author.get("followers")
                if isinstance(followers, (int, float)) and followers > 0:
                    stats["粉丝"] = int(followers)
                    author_detail["fans"] = int(followers)
                following = author.get("following")
                if isinstance(following, (int, float)) and following > 0:
                    stats["关注"] = int(following)
                media_count = author.get("media_count")
                if isinstance(media_count, (int, float)) and media_count > 0:
                    stats["帖子数"] = int(media_count)
                joined = str(author.get("joined") or "").strip()
                if joined:
                    author_detail["created_at"] = joined
                verification = author.get("verification")
                if isinstance(verification, dict) and verification.get("verified"):
                    vtype = str(verification.get("type") or "").lower()
                    author_detail["official_badge"] = (
                        "X 金标认证" if "gold" in vtype else "X 认证"
                    )
                media = tweet.get("media") or {}
                photos = media.get("photos") or []
                videos = media.get("videos") or []
                gifs = media.get("gifs") or []
                summary_lines = [tweet_text[:500]] if tweet_text else []
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
                return build_parsed_content(
                    platform="twitter",
                    item_id=status_id,
                    item_kind="tweet",
                    title="媒体推文" if tweet_text.startswith("https://t.co") else tweet_text[:40],
                    author_name=str(author.get("name") or "") or f"@{screen}",
                    summary="\n".join(summary_lines),
                    cover_url=cover,
                    canonical_url=url,
                    stats=stats,
                    parse_depth="deep",
                    detail={"author": author_detail} if author_detail else {},
                )
        except Exception:  # noqa: BLE001, S110 - 聚合接口失败回退 og。
            pass
    return _og_scrape(
        url,
        platform="twitter",
        item_kind="tweet",
        note="（浅层解析；X 反爬严格，拿不到内容时只有标题）",
        cookie_header=cookie_header,
    )



def _spa_link_card(
    url: str,
    *,
    platform: str,
    item_kind: str,
    label: str,
) -> ParsedContent:
    """动态渲染站点（无 og/无公开接口）：诚实降级为入口卡片。"""
    return build_parsed_content(
        platform=platform,
        item_id="",
        item_kind=item_kind,
        title=f"{label} 链接",
        summary="（该站页面为动态渲染，机器人拿不到具体内容；先保留入口，"
        "点开即可查看）",
        canonical_url=url,
        parse_depth="shallow",
    )




def parse_mihuashi(url: str, *, cookie_header: str = "") -> ParsedContent:
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


def parse_huajia(url: str, *, cookie_header: str = "") -> ParsedContent:
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


def parse_xiaoheihe(url: str, *, cookie_header: str = "") -> ParsedContent:
    return _og_scrape(
        url,
        platform="xiaoheihe",
        item_kind="post",
        note="（浅层解析；小黑盒官方 API 需要逆向签名）",
        cookie_header=cookie_header,
    )


def parse_miyoushe(url: str, *, cookie_header: str = "") -> ParsedContent:
    return _og_scrape(url, platform="miyoushe", item_kind="post", cookie_header=cookie_header)


def parse_skland(url: str, *, cookie_header: str = "") -> ParsedContent:
    return _og_scrape(url, platform="skland", item_kind="article", cookie_header=cookie_header)


def parse_kurobbs(url: str, *, cookie_header: str = "") -> ParsedContent:
    return _og_scrape(url, platform="kurobbs", item_kind="post", cookie_header=cookie_header)


# ---------- Pixiv 扩展页面类型（插画 artworks 主解析在 platforms_pixiv.py） ----------

_PIXIV_REFERER = "https://www.pixiv.net/"
_PIXIV_NOVEL_ID_RE = re.compile(r"novel/show\.php\?id=(\d+)")
_PIXIV_NOVEL_SERIES_RE = re.compile(r"novel/series/(\d+)")
_PIXIV_USER_ID_RE = re.compile(r"pixiv\.net/users/(\d+)")
_PIXIV_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _pixiv_ajax(path: str, *, cookie_header: str, proxy: str) -> dict:
    """Pixiv ajax GET：返回 body；error 或非 dict 视为失败抛 ParseHttpError。"""
    payload = http_get_json(
        f"https://www.pixiv.net/ajax{path}",
        timeout=12,
        referer=_PIXIV_REFERER,
        cookie=cookie_header,
        proxy=proxy,
    )
    if not isinstance(payload, dict) or payload.get("error"):
        raise ParseHttpError(f"pixiv ajax {path} failed")
    body = payload.get("body")
    if not isinstance(body, dict):
        raise ParseHttpError(f"pixiv ajax {path} returned non-dict body")
    return body


def _pixiv_publish_time(value: object) -> str:
    """ISO 时间（含时区）→ 'YYYY-MM-DD HH:MM'；解析失败返回空串。"""
    import datetime

    text = str(value or "").strip()
    if not text:
        return ""
    try:
        moment = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%Y-%m-%d %H:%M")


def _pixiv_plain_text(value: object, limit: int = 300) -> str:
    text = _PIXIV_HTML_TAG_RE.sub("", str(value or "").replace("<br />", "\n").replace("<br>", "\n"))
    text = _unescape_html(text.strip())
    text = re.sub(r"[ \t]+", " ", text)
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def parse_pixiv_novel(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """Pixiv 小说：ajax/novel/{id}（标题/作者/正文摘要/统计/系列），失败回退 og。"""
    match = _PIXIV_NOVEL_ID_RE.search(url)
    if not match:
        raise ParseHttpError("pixiv: no novel id")
    novel_id = match.group(1)
    try:
        body = _pixiv_ajax(f"/novel/{novel_id}", cookie_header=cookie_header, proxy=proxy)
        title = str(body.get("title") or "").strip()
        if not title:
            raise ParseHttpError("pixiv novel missing title")
    except ParseHttpError:
        return _og_scrape(
            url,
            platform="pixiv",
            item_kind="novel",
            referer=_PIXIV_REFERER,
            cookie_header=cookie_header,
            proxy=proxy,
        )
    stats: dict[str, int | str] = {}
    for key, label in (
        ("viewCount", "浏览"),
        ("likeCount", "喜欢"),
        ("bookmarkCount", "收藏"),
        ("commentCount", "评论"),
    ):
        value = body.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            stats[label] = value
    word_count = body.get("wordCount")
    if isinstance(word_count, int) and not isinstance(word_count, bool):
        stats["字数"] = word_count
    publish_time = _pixiv_publish_time(body.get("createDate") or body.get("uploadDate"))
    if publish_time:
        stats["发布时间"] = publish_time
    tags = [
        str(tag.get("tag") or "").strip()
        for tag in ((body.get("tags") or {}).get("tags") or [])
        if isinstance(tag, dict) and tag.get("tag")
    ]
    series = body.get("seriesNavData") or {}
    series_title = str(series.get("title") or "").strip() if isinstance(series, dict) else ""
    summary = _pixiv_plain_text(body.get("description"))
    content_text = _pixiv_plain_text(body.get("content"), 500)
    summary_lines: list[str] = []
    if series_title:
        summary_lines.append(f"系列：{series_title}")
    if publish_time:
        summary_lines.append(f"发布时间：{publish_time}")
    if summary:
        summary_lines.append(f"简介：{summary}")
    if content_text:
        summary_lines.append(f"正文预览：{content_text[:300]}")
    if tags:
        summary_lines.append("标签：" + "、".join(tags[:12]))
    author_detail: dict = {}
    user_id = str(body.get("userId") or "")
    if user_id:
        author_detail["uuid"] = user_id
    cover = str(body.get("coverUrl") or "")
    return build_parsed_content(
        platform="pixiv",
        item_id=novel_id,
        item_kind="novel",
        title=title,
        author_name=str(body.get("userName") or ""),
        summary="\n".join(summary_lines),
        cover_url=cover,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        detail={"author": author_detail} if author_detail else {},
    )


def parse_pixiv_novel_series(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """Pixiv 小说系列：ajax/novel/series/{id}（标题/作者/简介/话数/关注）。"""
    match = _PIXIV_NOVEL_SERIES_RE.search(url)
    if not match:
        raise ParseHttpError("pixiv: no novel series id")
    series_id = match.group(1)
    try:
        body = _pixiv_ajax(
            f"/novel/series/{series_id}", cookie_header=cookie_header, proxy=proxy
        )
        title = str(body.get("title") or "").strip()
        if not title:
            raise ParseHttpError("pixiv novel series missing title")
    except ParseHttpError:
        return _og_scrape(
            url,
            platform="pixiv",
            item_kind="novel_series",
            referer=_PIXIV_REFERER,
            cookie_header=cookie_header,
            proxy=proxy,
        )
    stats: dict[str, int | str] = {}
    published = body.get("publishedContentCount")
    if isinstance(published, int) and not isinstance(published, bool):
        stats["话数"] = published
    watch_count = body.get("watchCount")
    if isinstance(watch_count, int) and not isinstance(watch_count, bool):
        stats["关注"] = watch_count
    word_count = body.get("publishedTotalWordCount")
    if isinstance(word_count, int) and not isinstance(word_count, bool):
        stats["字数"] = word_count
    publish_time = _pixiv_publish_time(body.get("createDate") or body.get("updateDate"))
    if publish_time:
        stats["发布时间"] = publish_time
    tags = [str(tag) for tag in (body.get("tags") or []) if str(tag).strip()]
    caption = _pixiv_plain_text(body.get("caption"))
    summary_lines: list[str] = []
    if caption:
        summary_lines.append(f"简介：{caption}")
    if tags:
        summary_lines.append("标签：" + "、".join(tags[:12]))
    cover = ""
    first_episode = body.get("firstEpisode") or {}
    if isinstance(first_episode, dict):
        cover = str(first_episode.get("url") or "")
    author_detail: dict = {}
    user_id = str(body.get("userId") or "")
    if user_id:
        author_detail["uuid"] = user_id
    return build_parsed_content(
        platform="pixiv",
        item_id=series_id,
        item_kind="novel_series",
        title=title,
        author_name=str(body.get("userName") or ""),
        summary="\n".join(summary_lines),
        cover_url=cover,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        detail={"author": author_detail} if author_detail else {},
    )


def parse_pixiv_user(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """Pixiv 用户主页：ajax/user/{uid}?full=1 + profile/all（昵称/简介/作品数）。"""
    match = _PIXIV_USER_ID_RE.search(url)
    if not match:
        raise ParseHttpError("pixiv: no user id")
    user_id = match.group(1)
    try:
        body = _pixiv_ajax(
            f"/user/{user_id}?full=1", cookie_header=cookie_header, proxy=proxy
        )
        name = str(body.get("name") or "").strip()
        if not name:
            raise ParseHttpError("pixiv user missing name")
    except ParseHttpError:
        return _og_scrape(
            url,
            platform="pixiv",
            item_kind="user",
            referer=_PIXIV_REFERER,
            cookie_header=cookie_header,
            proxy=proxy,
        )
    stats: dict[str, int | str] = {}
    following = body.get("following")
    if isinstance(following, int) and not isinstance(following, bool):
        stats["关注"] = following
    mypixiv = body.get("mypixivCount")
    if isinstance(mypixiv, int) and not isinstance(mypixiv, bool):
        stats["好P友"] = mypixiv
    # 作品数：profile/all 是 {作品id: null} 字典，按键数统计（尽力而为）。
    work_lines: list[str] = []
    try:
        profile = _pixiv_ajax(
            f"/user/{user_id}/profile/all", cookie_header=cookie_header, proxy=proxy
        )
        counts = []
        for key, label in (("illusts", "插画"), ("manga", "漫画"), ("novels", "小说")):
            value = profile.get(key)
            if isinstance(value, dict) and value:
                counts.append(f"{label}{len(value)}")
        if counts:
            work_lines.append("作品：" + " · ".join(counts))
    except ParseHttpError:  # 作品统计失败不影响主卡。
        pass
    comment = _pixiv_plain_text(body.get("comment"), 260)
    summary_lines: list[str] = []
    if work_lines:
        summary_lines.append(work_lines[0])
    if comment:
        summary_lines.append(f"简介：{comment}")
    webpage = str(body.get("webpage") or "").strip()
    if webpage:
        summary_lines.append(f"主页：{webpage}")
    author_detail: dict = {"uuid": user_id}
    avatar = str(body.get("imageBig") or body.get("image") or "")
    if avatar:
        author_detail["avatar"] = avatar
    return build_parsed_content(
        platform="pixiv",
        item_id=user_id,
        item_kind="user",
        title=name,
        author_name=name,
        summary="\n".join(summary_lines),
        cover_url=avatar,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        detail={"author": author_detail},
    )


def parse_pixiv_contest(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """Pixiv 比赛页：og 元信息（标题/简介/主视觉），失败给入口浅卡。"""
    try:
        return _og_scrape(
            url,
            platform="pixiv",
            item_kind="contest",
            referer=_PIXIV_REFERER,
            cookie_header=cookie_header,
            proxy=proxy,
        )
    except ParseHttpError:
        return build_parsed_content(
            platform="pixiv",
            item_id="",
            item_kind="contest",
            title="Pixiv 比赛",
            summary="（比赛页面不可达，已保留原链接）",
            canonical_url=url,
            parse_depth="shallow",
        )


def parse_pixiv_ranking(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """Pixiv 排行榜：列表页无单作品数据，og 标题（含日期）出浅卡。"""
    try:
        item = _og_scrape(
            url,
            platform="pixiv",
            item_kind="ranking",
            referer=_PIXIV_REFERER,
            cookie_header=cookie_header,
            proxy=proxy,
        )
    except ParseHttpError:
        item = build_parsed_content(
            platform="pixiv",
            item_id="",
            item_kind="ranking",
            title="Pixiv 排行榜",
            summary="（排行榜页面不可达，已保留原链接）",
            canonical_url=url,
            parse_depth="shallow",
        )
        return item
    return build_parsed_content(
        platform=item.identity.platform if item.identity else "pixiv",
        item_id="",
        item_kind="ranking",
        title=item.content.title if item.content else "Pixiv 排行榜",
        summary="（排行榜为列表页，想看哪张插画请把具体作品链接发我）",
        cover_url=parsed_cover_url(item),
        canonical_url=url,
        parse_depth="shallow",
        page_type="ranking",
    )

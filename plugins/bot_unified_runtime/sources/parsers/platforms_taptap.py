"""TapTap 动态/视频解析：基于 parser-lite 的 taptap webapiv2 样本。

- 动态：https://www.taptap.cn/webapiv2/moment/v2/detail?moment_id={id}
- 视频：https://www.taptap.cn/webapiv2/video/v4/detail?video_id={id}（与动态同构）
响应包：{"data": {"moment": {...}}, "success": true}
author.user.{name,avatar}；stat.{pv_total,ups,comments,supports}。
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import datetime

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import http_get_json

_MOMENT_RE = re.compile(r"taptap\.(?:cn|io)/moment/(\d+)", re.IGNORECASE)
_VIDEO_RE = re.compile(r"taptap\.(?:cn|io)/video/(\d+)", re.IGNORECASE)


def _fmt_time(seconds: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(seconds or 0))).astimezone()
    except (TypeError, ValueError, OSError):
        return None


def _parse_moment_payload(payload: dict, item_id: str, kind: str) -> ParsedContent | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    moment = (data or {}).get("moment") or (data or {}).get("video") or {}
    if not isinstance(moment, dict) or not moment:
        return None
    user = ((moment.get("author") or {}).get("user")) or {}
    stat = moment.get("stat") or {}
    stats: dict[str, object] = {}
    for src_key, label in (("pv_total", "浏览"), ("ups", "点赞"), ("comments", "评论"), ("supports", "支持"), ("shares", "分享")):
        value = stat.get(src_key)
        if isinstance(value, int):
            stats[label] = value
    content = moment.get("rich_content") or moment.get("content") or ""
    if isinstance(content, dict):
        content = str(content.get("text") or "")
    import html as _html
    import re as _re

    text = _re.sub(r"<[^>]+>", "", _html.unescape(str(content))).strip()
    published_at = _fmt_time(moment.get("publish_time") or moment.get("created_time"))
    cover = ""
    images = moment.get("images") or (moment.get("video") or {}).get("cover") if isinstance(moment.get("video"), dict) else moment.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        cover = str((first or {}).get("url") if isinstance(first, dict) else first or "")
    elif isinstance(images, str):
        cover = images
    return build_parsed_content(
        platform="taptap",
        item_id=item_id,
        item_kind="video" if kind == "video" else "post",
        title=(text[:60] if text else (moment.get("title") or f"TapTap{'视频' if kind == 'video' else '动态'}")),
        author_name=str((user or {}).get("name") or "").strip(),
        summary=text[:1200],
        cover_url=cover,
        canonical_url=f"https://www.taptap.cn/moment/{item_id}" if kind != "video" else f"https://www.taptap.cn/video/{item_id}",
        stats=stats,
        detail={"published_at": published_at} if published_at is not None else {},
        parse_depth="deep",
    )


def parse_taptap_moment(moment_id: str, *, cookie_header: str = "") -> ParsedContent | None:
    payload = http_get_json(
        "https://www.taptap.cn/webapiv2/moment/v2/detail?"
        + urllib.parse.urlencode({"moment_id": moment_id, "X-UA": "V=1&PN=WebApp&LANG=zh_CN"})
        + (("&device=&cookie=" + cookie_header) if cookie_header else ""),
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0",
        timeout=8,
    )
    return _parse_moment_payload(payload if isinstance(payload, dict) else {}, moment_id, "moment")


def parse_taptap_video(video_id: str, *, cookie_header: str = "") -> ParsedContent | None:
    payload = http_get_json(
        "https://www.taptap.cn/webapiv2/video/v4/detail?"
        + urllib.parse.urlencode({"video_id": video_id, "X-UA": "V=1&PN=WebApp&LANG=zh_CN"}),
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0",
        timeout=8,
    )
    return _parse_moment_payload(payload if isinstance(payload, dict) else {}, video_id, "video")


def parse_taptap(url: str, *, cookie_header: str = "") -> ParsedContent:
    moment = _MOMENT_RE.search(url or "")
    if moment:
        result = parse_taptap_moment(moment.group(1), cookie_header=cookie_header)
        if result is not None:
            return result
        raise ValueError(f"taptap: moment unavailable for {url}")
    video = _VIDEO_RE.search(url or "")
    if video:
        result = parse_taptap_video(video.group(1), cookie_header=cookie_header)
        if result is not None:
            return result
        raise ValueError(f"taptap: video unavailable for {url}")
    raise ValueError(f"unsupported taptap url: {url}")

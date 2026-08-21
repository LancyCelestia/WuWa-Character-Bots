"""B 站链接解析：官方公开 view API（匿名可用）。

- 支持 bilibili.com/video/(BV..|av..)、短链 b23.tv。
- 输出：标题 / UP 主 / 封面 / 播放·弹幕·点赞 / 简介。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
    resolve_short_link,
)

_VIEW_API = "https://api.bilibili.com/x/web-interface/view"
_BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AVID_RE = re.compile(r"/av(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class PlatformParse:
    """平台解析结果（渲染层用）。"""

    platform: str
    item_id: str
    item_kind: str
    title: str
    author_name: str = ""
    summary: str = ""
    cover_url: str = ""
    audio_url: str = ""
    canonical_url: str = ""
    stats: dict = field(default_factory=dict)
    parse_depth: str = "deep"


def _lookup_video_by_id(video_id: str, kind: str, *, cookie_header: str = "") -> PlatformParse:
    import urllib.parse

    url = f"{_VIEW_API}?{urllib.parse.quote(kind)}={urllib.parse.quote(video_id)}"
    payload = http_get_json(
        url, referer="https://www.bilibili.com/", cookie=cookie_header
    )
    if payload.get("code") != 0:
        raise ParseHttpError(f"bilibili view api code={payload.get('code')}")
    data = payload.get("data") or {}
    owner = data.get("owner") or {}
    stat = data.get("stat") or {}
    pages = data.get("pages") or []
    desc = str(data.get("desc") or "").strip()
    if len(desc) > 300:
        desc = desc[:300] + "…"
    stats = {}
    for key, label in (("view", "播放"), ("danmaku", "弹幕"), ("like", "点赞"), ("favorite", "收藏")):
        value = stat.get(key)
        if isinstance(value, (int, float)):
            stats[label] = int(value)
    return PlatformParse(
        platform="bilibili",
        item_id=str(data.get("bvid") or video_id),
        item_kind="video",
        title=str(data.get("title") or "").strip(),
        author_name=str(owner.get("name") or ""),
        summary=f"简介：{desc}" if desc else "",
        cover_url=str(data.get("pic") or ""),
        canonical_url=f"https://www.bilibili.com/video/{data.get('bvid') or video_id}",
        stats=stats,
        parse_depth="deep",
    )


def parse_bilibili(url: str, *, cookie_header: str = "") -> PlatformParse:
    """B 站视频链接 → 结构化信息。"""
    final_url = url
    if "b23.tv" in url or "bili2233.cn" in url:
        final_url = resolve_short_link(url)
    match = _BVID_RE.search(final_url)
    if match:
        return _lookup_video_by_id(match.group(1), "bvid", cookie_header=cookie_header)
    match = _AVID_RE.search(final_url)
    if match:
        return _lookup_video_by_id(match.group(1), "aid", cookie_header=cookie_header)
    raise ParseHttpError(f"bilibili: no video id in {final_url}")

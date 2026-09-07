"""Telegram public message parser (HTML only, no Bot API history access)."""
from __future__ import annotations

import html
import re

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.context import ParseFailure
from plugins.bot_unified_runtime.sources.parsers.http_util import http_get_text

_POST_RE = re.compile(
    r"(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z0-9_]{4,})/(\d+)", re.IGNORECASE
)
_INVITE_RE = re.compile(r"(?:t\.me|telegram\.me)/(?:\+|joinchat/)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _count(value: str) -> int | None:
    raw = str(value or "").strip().upper().replace(",", "")
    if not raw:
        return None
    multiplier = 1
    if raw.endswith("K"):
        multiplier, raw = 1000, raw[:-1]
    elif raw.endswith("M"):
        multiplier, raw = 1000000, raw[:-1]
    elif raw.endswith("万"):
        multiplier, raw = 10000, raw[:-1]
    try:
        return int(float(raw) * multiplier)
    except ValueError:
        return None


def _text(value: str) -> str:
    value = _BR_RE.sub("\n", str(value or ""))
    value = _TAG_RE.sub("", value)
    return html.unescape(value).strip()


def _first(pattern: str, body: str) -> str:
    match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
    return html.unescape(match.group(1)).strip() if match else ""


def parse_telegram(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    if _INVITE_RE.search(url or ""):
        raise ParseFailure(
            "unsupported", "telegram", "parse",
            public_message="Telegram 私有邀请链接不支持解析",
        )
    match = _POST_RE.search(url or "")
    if not match:
        raise ParseFailure(
            "unsupported", "telegram", "parse",
            public_message="只支持公开频道的 t.me/<频道>/<消息ID> 链接",
        )
    channel, message_id = match.groups()
    final_url, body = http_get_text(
        url,
        timeout=10,
        referer="https://t.me/",
        cookie=cookie_header,
        proxy=proxy,
    )
    block_match = re.search(
        rf'data-post=["\']{re.escape(channel)}/{re.escape(message_id)}["\'][^>]*>(.*?)(?=<div[^>]+data-post=|</body>|$)',
        body or "",
        re.IGNORECASE | re.DOTALL,
    )
    block = block_match.group(1) if block_match else body
    message_text = _first(r'class=["\'][^"\']*tgme_widget_message_text[^"\']*["\'][^>]*>(.*?)</', block)
    if not message_text:
        message_text = _first(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)', body)
    title = _first(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', body)
    if not title:
        title = f"Telegram {channel}/{message_id}"
    cover = _first(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', body)
    stats: dict[str, int] = {}
    views = _count(_first(r'tgme_widget_message_views[^>]*>([^<]+)', block))
    reactions = _count(_first(r'tgme_widget_message_reactions[^>]*>.*?([\d,.]+(?:K|M|万)?)', block))
    forwards = _count(_first(r'tgme_widget_message_forwards[^>]*>([^<]+)', block))
    if views is not None:
        stats["浏览"] = views
    if reactions is not None:
        stats["爱心"] = reactions
    if forwards is not None:
        stats["转发"] = forwards
    # 消息时间：<time datetime="..."> 权威优先，其次文本兜底。
    publish_at = _first(r'<time[^>]+datetime=["\']([^"\']+)', block or body)
    if not publish_at:
        publish_at = _first(r'<time[^>]*>([^<]+)</time>', block or body)
    # 媒体：图集图片 / 视频文件（t.me 网页版嵌入标签）。
    images: list[str] = []
    for src in re.findall(
        r'class=["\'][^"\']*tgme_widget_message_photo[^"\']*["\'][^>]*src=["\']([^"\']+)',
        block or "",
        re.IGNORECASE,
    ):
        clean = html.unescape(str(src).strip())
        if clean and clean not in images:
            images.append(clean)
    video_url = _first(
        r'class=["\'][^"\']*tgme_widget_message_video[^"\']*["\'][^>]*(?:src|data-src)=["\']([^"\']+)',
        block or "",
    )
    if not video_url:
        video_url = _first(r"<video[^>]+(?:src|data-src)=[\"']([^\"']+)", block or "")
    # 频道资料：标题/头像/简介/订阅数（页面明确出现才取）。
    channel_author: dict[str, object] = {}
    channel_title = _first(r"tgme_channel_info_header_title[^>]*>(.*?)</", body)
    channel_avatar = _first(
        r'tgme_channel_info_header_avatar[^>]*.*?src=["\']([^"\']+)',
        body,
    )
    if not channel_avatar:
        channel_avatar = _first(
            r'class=["\'][^"\']*tgme_page_photo_image[^"\']*["\'][^>]*src=["\']([^"\']+)',
            body,
        )
    channel_bio = _first(
        r'class=["\'][^"\']*tgme_channel_info_description[^"\']*["\'][^>]*>(.*?)</',
        body,
    )
    channel_subscribers = _count(
        _first(r'tgme_channel_info_counter[^>]*>.*?([\d,.]+(?:K|M|万)?)', body)
    )
    if channel_title:
        channel_author["name"] = html.unescape(channel_title)
    if channel_avatar:
        channel_author["avatar"] = html.unescape(channel_avatar)
    if channel_bio:
        channel_author["signature"] = html.unescape(_text(channel_bio))
    if channel_subscribers is not None:
        channel_author["fans"] = channel_subscribers
    detail: dict[str, object] = {
        "author": {
            "name": str(channel_title or channel),
            "handle": channel,
            "profile_url": f"https://t.me/{channel}",
        }
    }
    if publish_at:
        detail["published_at"] = publish_at
    if images:
        detail["images"] = images
    if video_url:
        detail["video"] = {"url": html.unescape(video_url), "preview_url": cover or ""}
    for key, value in channel_author.items():
        detail["author"][key] = value  # type: ignore[index]
    return build_parsed_content(
        platform="telegram",
        item_id=message_id,
        item_kind="post",
        title=title,
        summary=_text(message_text),
        cover_url=cover,
        canonical_url=final_url or url,
        stats=stats,
        parse_depth="deep" if message_text else "shallow",
        detail=detail,
    )

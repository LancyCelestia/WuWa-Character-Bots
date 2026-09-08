"""媒体分享解析第三批：全民K歌/豆包视频/米画师/BUFF（基于 parser-lite 端点与样本）。"""

from __future__ import annotations

import re
import urllib.parse

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
    http_get_text,
)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"

_QSMUSIC_SHARE_RE = re.compile(r"qishui\.douyin\.com/s/([A-Za-z0-9]+)")
_QSMUSIC_TRACK_RE = re.compile(r"track_id[\"']?\s*[:=]\s*[\"']?(\d+)")
_DOUBAO_SHARE_RE = re.compile(r"doubao\.com/video-sharing\?[^\s]*share_id=(\d+)")
_ILLU_ARTICLE_RE = re.compile(r"articleId%3D(\d+)|articleId=(\d+)", re.IGNORECASE)
_BUFF_RE = re.compile(r"buff\.163\.com/[^\s]+")


def parse_qsmusic(url: str, *, cookie_header: str = "") -> ParsedContent:
    """全民K歌（汽水音乐）分享：分享页 HTML 内嵌 loaderData JSON。"""
    match = _QSMUSIC_SHARE_RE.search(url or "")
    if not match:
        raise ValueError(f"qsmusic: no share code in {url}")
    _, html = http_get_text(
        f"https://qishui.douyin.com/s/{match.group(1)}/",
        user_agent=_UA,
        timeout=10,
    )
    track_match = _QSMUSIC_TRACK_RE.search(html or "")
    if not track_match:
        raise ValueError(f"qsmusic: track data not found for {url}")
    # 从 HTML 中截取 track_page JSON 片段（loaderData 结构，样本见 api_txt/qsmusic）。
    title_m = re.search(r'"(?:title|track_name)"\s*:\s*"([^"]{1,80})"', html)
    artist_m = re.search(r'"artist(?:_name)?[A-Za-z]*"\s*:\s*"([^"]{1,60})"', html)
    cover_m = re.search(r'"(?:cover|cover_url)"\s*:\s*"([^"]{20,300})"', html)
    track_id = track_match.group(1)
    return build_parsed_content(
        platform="qsmusic",
        item_id=track_id,
        item_kind="music",
        title=(title_m.group(1).encode().decode("unicode_escape", errors="ignore") if title_m else "汽水音乐"),
        author_name=(artist_m.group(1).encode().decode("unicode_escape", errors="ignore") if artist_m else ""),
        cover_url=cover_m.group(1).replace("\\u002F", "/") if cover_m else "",
        canonical_url=f"https://qishui.douyin.com/s/{match.group(1)}/",
        parse_depth="deep",
    )


def parse_doubao(url: str, *, cookie_header: str = "") -> ParsedContent:
    """豆包 AI 视频分享：get_video_share_info POST（样本 data.play_info/user_info/prompt）。"""
    match = _DOUBAO_SHARE_RE.search(url or "")
    if not match:
        raise ValueError(f"doubao: no share id in {url}")
    share_id = match.group(1)
    try:
        payload = http_get_json(
            "https://www.doubao.com/creativity/share/get_video_share_info?"
            + urllib.parse.urlencode({"share_id": share_id}),
            user_agent=_UA,
            timeout=10,
        )
    except ParseHttpError:
        payload = {}
    data = payload.get("data") if isinstance(payload, dict) else None
    data = data or {}
    user = data.get("user_info") or {}
    play = data.get("play_info") or {}
    video_url = str((play or {}).get("main") or "")
    prompt = str(data.get("prompt") or "").strip()
    return build_parsed_content(
        platform="doubao",
        item_id=share_id,
        item_kind="video",
        title=(prompt[:50] or "豆包 AI 视频"),
        author_name=str((user or {}).get("nickname") or "").strip(),
        summary=(f"Prompt：{prompt}" if prompt else "豆包 AI 生成视频分享"),
        canonical_url=f"https://www.doubao.com/video-sharing?share_id={share_id}",
        detail={
            "video": {"url": video_url} if video_url else {},
            "platform_extra": {"ai_generated": True},
        },
        parse_depth="deep",
    )


def parse_illu(url: str, *, cookie_header: str = "") -> ParsedContent:
    """米画师分享：无公开详情 API 样本，OG 兜底。"""
    match = _ILLU_ARTICLE_RE.search(url or "")
    if not match:
        raise ValueError(f"illu: no article id in {url}")
    article_id = match.group(1) or match.group(2)
    title, description, cover = _og_scrape_page(url)
    if not title:
        raise ValueError(f"illu: page unavailable {article_id}")
    return build_parsed_content(
        platform="illu",
        item_id=article_id,
        item_kind="post",
        title=title,
        summary=description[:1200],
        cover_url=cover,
        canonical_url=url,
        parse_depth="deep",
    )


def parse_buff(url: str, *, cookie_header: str = "") -> ParsedContent:
    """BUFF 饰品分享：详情接口需要登录态，OG 兜底；登录 Cookie 可增强。"""
    if not _BUFF_RE.search(url or ""):
        raise ValueError(f"buff: not a buff url {url}")
    title, description, cover = _og_scrape_page(url)
    if not title:
        raise ValueError("buff: page unavailable")
    return build_parsed_content(
        platform="buff",
        item_id=url.rstrip("/").rsplit("/", 1)[-1],
        item_kind="post",
        title=title,
        summary=description[:1200],
        cover_url=cover,
        canonical_url=url,
        parse_depth="deep",
    )

_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property="og:title"[^>]+content="([^<"]{1,400})"',
    re.IGNORECASE,
)
_OG_DESC_RE = re.compile(
    r'<meta[^>]+property="og:description"[^>]+content="([^<"]{1,400})"',
    re.IGNORECASE,
)
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property="og:image"[^>]+content="([^<"]{1,400})"',
    re.IGNORECASE,
)


def _og_scrape_page(url: str) -> tuple[str, str, str]:
    """No detail API: fall back to OG meta scraping; empty tuple on failure."""
    try:
        _, html_text = http_get_text(url, user_agent=_UA, timeout=10)
    except ParseHttpError:
        return "", "", ""
    mTITLE = _OG_TITLE_RE.search(html_text or "")
    mDESC = _OG_DESC_RE.search(html_text or "")
    mIMAGE = _OG_IMAGE_RE.search(html_text or "")
    return (mTITLE.group(1).strip() if mTITLE else "", mDESC.group(1).strip() if mDESC else "", mIMAGE.group(1).strip() if mIMAGE else "")

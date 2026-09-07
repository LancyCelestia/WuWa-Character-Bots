"""Pixiv 插画深解析：官方 ajax 接口 + 多图分镜分辨率 + 作者作品/粉丝统计。

主接口失败或标题为空时回退到通用 og 浅解析。所有请求都透传 HTTP 代理
（大陆环境需经 127.0.0.1:7890 才能访问 www.pixiv.net）。
"""

from __future__ import annotations

import re
from typing import Any

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import _og_scrape

_PIXIV_REFERER = "https://www.pixiv.net/"
_TYPE_LABELS = {0: "插画", 1: "漫画", 2: "动图"}


def _extract_body(payload: Any) -> Any:
    """兼容 Pixiv ajax 的 ``{"body": ...}`` 包裹与直接返回 body 两种形状。"""
    if isinstance(payload, dict) and "body" in payload:
        return payload.get("body")
    return payload


def _work_count(value: Any) -> int:
    """作品列表接口形如 ``{作品id: None}``，按字典键数量计数。"""
    if isinstance(value, dict):
        return len(value)
    return 0


def _user_id_from_body(body: dict[str, Any]) -> str:
    """userId 实测可能是 int 或数字字符串，统一规整为数字字符串。"""
    raw = body.get("userId")
    if isinstance(raw, int) and not isinstance(raw, bool):
        return str(raw)
    if isinstance(raw, str) and raw.isdigit():
        return raw
    return ""


def _og_fallback(url: str, *, cookie_header: str, proxy: str) -> ParsedContent:
    """浅层降级：复用通用 og 抓取，透传 cookie 与代理。"""
    return _og_scrape(
        url,
        platform="pixiv",
        item_kind="illust",
        referer=_PIXIV_REFERER,
        cookie_header=cookie_header,
        proxy=proxy,
    )


def _append_author_stats(
    lines: list[str],
    user_id: str,
    *,
    cookie_header: str,
    proxy: str,
) -> dict:
    """尽力补充作者作品数与粉丝/关注数；任一请求失败都静默跳过。

    返回结构化作者统计（fans/following/illusts/manga/novels），
    同时保留摘要文本行给文本输出。
    """
    author_stats: dict = {}
    try:
        profile = _extract_body(
            http_get_json(
                f"https://www.pixiv.net/ajax/user/{user_id}/profile/all",
                referer=_PIXIV_REFERER,
                cookie=cookie_header,
                proxy=proxy,
            )
        )
        if isinstance(profile, dict):
            counts = {
                "illusts": _work_count(profile.get("illusts")),
                "manga": _work_count(profile.get("manga")),
                "novels": _work_count(profile.get("novels")),
            }
            if any(counts.values()):
                lines.append(
                    f"作者作品：插画{counts['illusts']} · "
                    f"漫画{counts['manga']} · 小说{counts['novels']}"
                )
                author_stats.update(counts)
    except ParseHttpError:
        pass

    try:
        user = _extract_body(
            http_get_json(
                f"https://www.pixiv.net/ajax/user/{user_id}?full=1",
                referer=_PIXIV_REFERER,
                cookie=cookie_header,
                proxy=proxy,
            )
        )
        if isinstance(user, dict):
            follower = user.get("follower")
            following = user.get("following")
            if isinstance(follower, int) and not isinstance(follower, bool):
                lines.append(
                    f"作者粉丝：{follower} · 关注："
                    f"{following if isinstance(following, int) else 0}"
                )
                author_stats["fans"] = follower
                if isinstance(following, int) and not isinstance(following, bool):
                    author_stats["following"] = following
    except ParseHttpError:
        pass
    return author_stats


def parse_pixiv(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """Pixiv 插画：官方 ajax 深解析，主接口失败回退页面 og 浅解析。"""
    match = re.search(r"/artworks/(\d+)", url)
    if not match:
        raise ParseHttpError("pixiv: no artwork id")
    artwork_id = match.group(1)

    try:
        illust_payload = http_get_json(
            f"https://www.pixiv.net/ajax/illust/{artwork_id}",
            referer=_PIXIV_REFERER,
            cookie=cookie_header,
            proxy=proxy,
        )
    except ParseHttpError:
        return _og_fallback(url, cookie_header=cookie_header, proxy=proxy)

    body = _extract_body(illust_payload)
    if not isinstance(body, dict) or not str(body.get("title") or "").strip():
        return _og_fallback(url, cookie_header=cookie_header, proxy=proxy)

    tags = [
        str(tag.get("tag") or "").strip()
        for tag in ((body.get("tags") or {}).get("tags") or [])
        if isinstance(tag, dict)
    ]
    tags = [tag for tag in tags if tag][:12]

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
    width, height = body.get("width"), body.get("height")
    if isinstance(width, int) and isinstance(height, int):
        stats["分辨率"] = f"{width}×{height}"
    page_count = body.get("pageCount")
    if isinstance(page_count, int) and not isinstance(page_count, bool) and page_count > 0:
        stats["图片数量"] = page_count

    raw_kind = body.get("illustType")
    kind_label = (
        _TYPE_LABELS.get(raw_kind, "插画")
        if isinstance(raw_kind, int) and not isinstance(raw_kind, bool)
        else "插画"
    )
    summary_lines = [f"类型：{kind_label}"]

    # 多图分镜：pages 接口是数组，URL/宽高全部进 media（前 6 页宽高进摘要行）。
    media_meta: list[dict] = []
    try:
        pages = _extract_body(
            http_get_json(
                f"https://www.pixiv.net/ajax/illust/{artwork_id}/pages",
                referer=_PIXIV_REFERER,
                cookie=cookie_header,
                proxy=proxy,
            )
        )
        if isinstance(pages, list) and pages:
            stats["图片数量"] = len(pages)
            frame_parts = []
            for index, page in enumerate(pages, start=1):
                if not isinstance(page, dict):
                    continue
                page_width, page_height = page.get("width"), page.get("height")
                page_urls = page.get("urls") or {}
                page_url = (
                    str(page_urls.get("original") or page_urls.get("regular") or "")
                    if isinstance(page_urls, dict)
                    else ""
                )
                if page_url or (isinstance(page_width, int) and isinstance(page_height, int)):
                    media_meta.append(
                        {
                            "type": "image",
                            "url": page_url or None,
                            "width": page_width if isinstance(page_width, int) else None,
                            "height": page_height if isinstance(page_height, int) else None,
                        }
                    )
                if index <= 6 and isinstance(page_width, int) and isinstance(page_height, int):
                    frame_parts.append(f"P{index} {page_width}×{page_height}")
            if frame_parts:
                suffix = " 等" if len(pages) > 6 else ""
                summary_lines.append("分镜：" + " · ".join(frame_parts) + suffix)
    except ParseHttpError:
        pass

    description = str(body.get("description") or "").strip()
    if len(description) > 300:
        description = description[:300] + "…"
    if description:
        summary_lines.append(f"简介：{description}")
    if tags:
        summary_lines.append("标签：" + "、".join(tags))

    # R-18 / 动图诚实分类（不绕过限制，直链不提供）。
    if body.get("x_restrict") in (1, "1"):
        stats["分级"] = "R-18"
    if raw_kind == 2:
        summary_lines.append("动图：分帧 ZIP，需登录后经官方页面下载")
        stats["动图"] = "分帧 ZIP（需登录）"

    user_id = _user_id_from_body(body)
    detail: dict = {}
    if user_id:
        author_detail: dict = {"uuid": user_id}
        user_name = str(body.get("userName") or "").strip()
        if user_name:
            author_detail["name"] = user_name
        # Pixiv 头像 URL 遵循固定模式（i.pximg.net/user-profile/img/{uid}/{uid}.jpg）。
        author_detail["avatar"] = (
            f"https://i.pximg.net/user-profile/img/{user_id}/{user_id}.jpg"
        )
        structured = _append_author_stats(
            summary_lines, user_id, cookie_header=cookie_header, proxy=proxy
        )
        author_detail.update(structured)
        detail["author"] = author_detail
    if media_meta:
        detail["media"] = media_meta
    create_date = str(body.get("createDate") or "").strip()
    if create_date:
        detail["published_at"] = create_date

    # QQ 可直接加载的 embed 代理图，避免 i.pximg.net 防盗链。
    cover_url = f"https://embed.pixiv.net/artwork.php?illust_id={artwork_id}"
    return build_parsed_content(
        platform="pixiv",
        item_id=artwork_id,
        item_kind="illust",
        title=str(body.get("title") or ""),
        author_name=str(body.get("userName") or ""),
        summary="\n".join(summary_lines),
        cover_url=cover_url,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        detail=detail or None,
    )
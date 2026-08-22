"""Lofter（乐乎）链接深度解析。

- 新版标签页走 newapi/tagPosts.json 表单接口；
- 数字 token 文章走 oldapi/post/detail.api 表单接口；
- 新版 permalink 与动态渲染页面诚实降级为浅层卡片。
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from typing import Any

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_text,
    http_post_form,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import _og_scrape
from plugins.bot_unified_runtime.sources.parsers.types import PlatformParse

_LOFTER_ANDROID_UA = "LOFTER-Android 8.2.36 (V2309A; Android 9; null) WIFI"
_TAG_POSTS_URL = "https://api.lofter.com/newapi/tagPosts.json"
_POST_DETAIL_URL = (
    "https://api.lofter.com/oldapi/post/detail.api?product=lofter-android-7.9.10"
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_NUMERIC_TOKEN_RE = re.compile(r"^(\d+)_(\d+)$")
_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.IGNORECASE)
_TITLE_SUFFIX_RE = re.compile(r"\s*[|｜]\s*LOFTER.*$", re.IGNORECASE)
_THIS_P_RE = re.compile(
    r"""this\.p\s*=\s*\{themeid\s*:\s*['"]([^'"]+)['"],\s*"""
    r"""previewBlogName\s*:\s*['"]([^'"]+)['"]\}"""
)
_THEME_PATH_RE = re.compile(r"/theme/preview/(\d+)")


def _strip_html(value: Any) -> str:
    """去掉 HTML 标签、转义实体并折叠空白。"""
    text = _HTML_TAG_RE.sub("", str(value or ""))
    text = html.unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _as_int(value: Any) -> int:
    """把可空计数安全转成 int，失败统一为 0。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_json_list(value: Any) -> list[Any]:
    """解析可能是 JSON 字符串的列表字段，失败返回空列表。"""
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _path_segments(url: str) -> list[str]:
    return [part for part in urllib.parse.urlsplit(url).path.split("/") if part]


def _segment_after(url: str, marker: str) -> str:
    """取 URL 路径中 marker 后面的一个路径段（无则空串）。"""
    segments = _path_segments(url)
    if marker not in segments:
        return ""
    index = segments.index(marker)
    return segments[index + 1] if index + 1 < len(segments) else ""


def _clean_title(value: str) -> str:
    """清理页面标题并去掉“| LOFTER（乐乎）”类后缀。"""
    value = html.unescape(value or "").strip()
    return _TITLE_SUFFIX_RE.sub("", value).strip()


def _page_title(text: str) -> str:
    match = _TITLE_RE.search(text)
    return _clean_title(match.group(1)) if match else ""


def _parse_tag(url: str, raw_tag: str) -> PlatformParse:
    tag = urllib.parse.unquote(raw_tag).strip()
    if not tag:
        raise ParseHttpError("lofter: missing tag")
    payload = {
        "product": "lofter-android-8.2.36",
        "postTypes": "",
        "offset": 0,
        "postYm": "",
        "returnGiftCombination": "",
        "recentDay": 0,
        "protectedFlag": 0,
        "range": 0,
        "firstpermalink": "null",
        "style": 0,
        "tag": tag,
        "type": "total",
    }
    body = http_post_form(_TAG_POSTS_URL, payload, user_agent=_LOFTER_ANDROID_UA)
    if not isinstance(body, dict) or body.get("code") != 0:
        raise ParseHttpError("lofter: tag API returned failure")
    data = body.get("data") or {}
    items = data.get("list")
    if not isinstance(items, list):
        raise ParseHttpError("lofter: tag API missing post list")

    lines: list[str] = []
    cover_url = ""
    for index, item in enumerate(items[:6], start=1):
        if not isinstance(item, dict):
            continue
        post_data = item.get("postData") or {}
        post_view = post_data.get("postView") or {}
        counts = post_data.get("postCount") or {}
        blog_info = item.get("blogInfo") or post_data.get("blogInfo") or {}
        nickname = str(blog_info.get("blogNickName") or "")
        title = str(post_view.get("title") or "").strip() or "文字/图片贴"
        favorite = _as_int(counts.get("favoriteCount"))
        response = _as_int(counts.get("responseCount"))
        lines.append(f"{index}. {nickname}《{title}》 {favorite}喜欢 · {response}回复")
        if index == 1:
            first_image = post_view.get("firstImage") or {}
            cover_url = str(first_image.get("orign") or "")

    return PlatformParse(
        platform="lofter",
        item_id=tag,
        item_kind="tag",
        title=f"标签：{tag}",
        summary="\n".join(lines),
        cover_url=cover_url,
        canonical_url=url,
        stats={"博文": len(items)},
        parse_depth="deep",
    )


def _parse_post(url: str, cookie_header: str, token: str) -> PlatformParse:
    match = _NUMERIC_TOKEN_RE.fullmatch(token)
    if not match:
        return _og_scrape(
            url,
            platform="lofter",
            item_kind="post",
            cookie_header=cookie_header,
        )
    blog_id, post_id = match.group(1), match.group(2)
    payload = {
        "targetblogid": blog_id,
        "postid": post_id,
        "supportposttypes": "1,2,3,4,5,6",
        "needgetpoststat": "1",
    }
    body = http_post_form(_POST_DETAIL_URL, payload, user_agent=_LOFTER_ANDROID_UA)
    if not isinstance(body, dict):
        raise ParseHttpError("lofter: post API returned failure")
    meta = body.get("meta") or {}
    response_data = body.get("response") or {}
    posts = response_data.get("posts") if isinstance(response_data, dict) else None
    post = None
    if isinstance(posts, list) and posts and isinstance(posts[0], dict):
        post = posts[0].get("post")
    if meta.get("status") != 200 or not isinstance(post, dict) or not post:
        raise ParseHttpError("lofter: post API returned failure")

    counts = post.get("postCount") or {}
    stats: dict[str, int | str] = {}
    for label, key in (
        ("喜欢", "favoriteCount"),
        ("评论", "responseCount"),
        ("分享", "shareCount"),
        ("转发", "reblogCount"),
        ("热度", "postHot"),
    ):
        value = _as_int(counts.get(key))
        if value > 0:
            stats[label] = value

    photos = _parse_json_list(post.get("photoLinks"))
    if photos:
        stats["图片数量"] = len(photos)
        first_photo = photos[0] if isinstance(photos[0], dict) else {}
        width = _as_int(first_photo.get("ow"))
        height = _as_int(first_photo.get("oh"))
        if width > 0 and height > 0:
            stats["分辨率"] = f"{width}×{height}"

    cover_url = ""
    if photos and isinstance(photos[0], dict):
        cover_url = str(photos[0].get("orign") or photos[0].get("raw") or "")
    if not cover_url:
        first_urls = _parse_json_list(post.get("firstImageUrl"))
        if first_urls:
            cover_url = str(first_urls[-1] or "")

    body_text = _strip_html(post.get("digest") or post.get("content") or "")
    if len(body_text) > 300:
        body_text = body_text[:300] + "…"
    tag_list = post.get("tagList")
    tags = [str(tag).strip() for tag in tag_list[:10] if str(tag).strip()] if isinstance(
        tag_list, list
    ) else []
    if tags:
        tag_text = f"标签：{'、'.join(tags)}"
        body_text = f"{body_text}\n{tag_text}" if body_text else tag_text

    blog_info = post.get("blogInfo") or {}
    return PlatformParse(
        platform="lofter",
        item_id=str(post.get("id") or ""),
        item_kind="post",
        title=str(post.get("title") or ""),
        author_name=str(blog_info.get("blogNickName") or ""),
        summary=body_text,
        cover_url=cover_url,
        canonical_url=str(post.get("blogPageUrl") or url),
        stats=stats,
        parse_depth="deep",
    )


def _parse_theme(url: str, path_id: str, text: str) -> PlatformParse:
    match = _THIS_P_RE.search(text)
    if match:
        theme_id = match.group(1)
        preview_blog = match.group(2)
        title = _page_title(text) or f"Lofter 主题 {path_id or theme_id}"
        return PlatformParse(
            platform="lofter",
            item_id=theme_id,
            item_kind="theme",
            title=title,
            summary=f"主题ID：{theme_id} · 预览博客：{preview_blog}",
            canonical_url=url,
            parse_depth="deep",
        )
    title = _page_title(text) or "Lofter 主题页"
    return PlatformParse(
        platform="lofter",
        item_id=path_id,
        item_kind="theme",
        title=title,
        summary="（主题页为动态渲染，仅能提取页面标题；点开链接查看内容）",
        canonical_url=url,
        parse_depth="shallow",
    )


def _parse_selection(url: str, text: str) -> PlatformParse:
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    match_id = str((query.get("id") or [""])[0])
    title = _page_title(text) or (f"Lofter 精选 {match_id}" if match_id else "Lofter 精选")
    return PlatformParse(
        platform="lofter",
        item_id=match_id,
        item_kind="collection",
        title=title,
        summary="（精选合辑页面为动态渲染，仅能提取页面标题；点开链接查看内容）",
        canonical_url=url,
        parse_depth="shallow",
    )


def _parse_trend(url: str) -> PlatformParse:
    return PlatformParse(
        platform="lofter",
        item_id="",
        item_kind="page",
        title="Lofter 趋势页",
        summary="（趋势页为动态渲染，仅能提取页面标题；点开链接查看当前趋势）",
        canonical_url=url,
        parse_depth="shallow",
    )


def parse_lofter(url: str, *, cookie_header: str = "") -> PlatformParse:
    """Lofter 链接解析入口：按页面类型走深度接口或浅层降级。"""
    if "/tag/" in url:
        return _parse_tag(url, _segment_after(url, "tag"))
    if "/post/" in url:
        return _parse_post(url, cookie_header, _segment_after(url, "post"))
    if "/theme/preview/" in url:
        _, text = http_get_text(url)
        path_match = _THEME_PATH_RE.search(urllib.parse.urlsplit(url).path)
        path_id = path_match.group(1) if path_match else ""
        return _parse_theme(url, path_id, text)
    if "/selection" in url:
        _, text = http_get_text(url)
        return _parse_selection(url, text)
    if "/trend" in url:
        http_get_text(url)
        return _parse_trend(url)
    raise ParseHttpError("lofter: unsupported page type")

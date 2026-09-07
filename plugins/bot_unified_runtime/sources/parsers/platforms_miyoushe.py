"""米游社（www.miyoushe.com / bbs.miyoushe.com）链接解析。

- 帖子（``/{game}/article/{postId}``）：公开接口
  ``https://bbs-api.miyoushe.com/post/wapi/getPostFull?post_id=``（已实测
  匿名可用，带 Referer 即可）拿标题 / 正文（quill delta）/ 作者 / 头像 /
  点赞回复浏览收藏转发 / 发布时间 / 板块与话题。
- 板块页（``/{game}/home/{forumId}``）：纯前端渲染且无公开元信息，
  诚实降级入口卡。
"""

from __future__ import annotations

import html
import json
import re

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    http_get_json,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    _format_epoch,
    _og_scrape,
)

_MYS_POST_API = "https://bbs-api.miyoushe.com/post/wapi/getPostFull?post_id={post_id}"
_POST_ID_RE = re.compile(r"miyoushe\.com/(?:[a-z-]+/)?article/(\d+)")
_FORUM_ID_RE = re.compile(r"miyoushe\.com/(?:[a-z-]+/)?home/(\d+)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# 游戏分区（URL 路径前缀 → 显示名），用于板块页浅卡标题。
_GAME_NAMES = {
    "ys": "原神",
    "sr": "崩坏：星穹铁道",
    "zzz": "绝区零",
    "bh3": "崩坏3",
    "dby": "崩坏学园2",
    "xq": "米游社",
    "wd": "未定事件簿",
}


def _mys_strip_html(value: object) -> str:
    text = _HTML_TAG_RE.sub("", str(value or ""))
    text = html.unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _mys_delta_text(structured: object) -> str:
    """quill delta（JSON 字符串或 list）→ 纯文本摘要（图片记 [图]）。"""
    payload: object = structured
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:  # noqa: BLE001 - 非法 JSON 交给 content 兜底。
            return ""
    if not isinstance(payload, list):
        return ""
    parts: list[str] = []
    for block in payload:
        if not isinstance(block, dict):
            continue
        insert = block.get("insert")
        if isinstance(insert, str):
            parts.append(insert)
        elif isinstance(insert, dict) and "image" in insert:
            parts.append(" [图] ")
    text = "".join(parts)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _mys_author_detail(user: dict) -> dict:
    detail: dict = {}
    if user.get("uid"):
        detail["uuid"] = str(user.get("uid"))
    if user.get("avatar_url"):
        detail["avatar"] = str(user.get("avatar_url"))
    if user.get("introduce"):
        detail["signature"] = str(user.get("introduce"))
    return detail


def _mys_post_result(
    outer: dict,
    url: str,
    post_id: str,
) -> ParsedContent | None:
    """getPostFull 的 data.post（outer）→ 深度帖子卡。"""
    inner = outer.get("post") or {}
    if not isinstance(inner, dict):
        return None
    title = str(inner.get("subject") or "").strip()
    if not title:
        return None
    user = outer.get("user") or {}
    stat = outer.get("stat") or {}
    stats: dict = {}
    for key, label in (
        ("like_num", "点赞"),
        ("reply_num", "回复"),
        ("view_num", "浏览"),
        ("bookmark_num", "收藏"),
        ("forward_num", "转发"),
    ):
        value = stat.get(key)
        if isinstance(value, (int, float)) and value > 0:
            stats[label] = int(value)
    publish_time = _format_epoch(inner.get("created_at"))
    if publish_time:
        stats["发布时间"] = publish_time
    summary = _mys_delta_text(inner.get("structured_content"))
    if not summary:
        summary = _mys_strip_html(inner.get("content"))
    if len(summary) > 300:
        summary = summary[:300] + "…"
    cover = ""
    if isinstance(outer.get("cover"), dict) and outer["cover"].get("url"):
        cover = str(outer["cover"]["url"])
    if not cover:
        for image in outer.get("image_list") or []:
            if isinstance(image, dict) and image.get("url"):
                cover = str(image["url"])
                break
    if not cover:
        images = inner.get("images") or []
        if isinstance(images, list) and images:
            cover = str(images[0])
    forum = outer.get("forum") or {}
    topics = [
        str(t.get("name") or "")
        for t in (outer.get("topics") or [])
        if isinstance(t, dict) and t.get("name")
    ]
    detail: dict = {"author": _mys_author_detail(user)} if user else {}
    if forum.get("name"):
        detail["forum"] = str(forum["name"])
    if topics:
        detail["topics"] = topics[:5]
    return build_parsed_content(
        platform="miyoushe",
        item_id=post_id,
        item_kind="post",
        title=title,
        author_name=str(user.get("nickname") or ""),
        summary=summary,
        cover_url=cover,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="post",
        badge="米游社",
        detail=detail,
    )


def _mys_post_card(
    url: str,
    post_id: str,
    *,
    cookie_header: str = "",
    proxy: str = "",
) -> ParsedContent:
    """帖子深解析：getPostFull 匿名可用，失败回退 og。"""
    payload = http_get_json(
        _MYS_POST_API.format(post_id=post_id),
        timeout=12,
        cookie=cookie_header,
        proxy=proxy,
        referer="https://www.miyoushe.com/",
    )
    if (payload or {}).get("retcode") not in (0, "0"):
        raise ValueError(f"miyoushe: retcode={payload.get('retcode')}")
    outer = ((payload or {}).get("data") or {}).get("post") or {}
    item = _mys_post_result(outer, url, post_id)
    if item is None:
        raise ValueError("miyoushe: post payload incomplete")
    return item


def _mys_forum_card(url: str, forum_id: str) -> ParsedContent:
    """板块页静态入口卡（页面无 og、数据动态渲染）。"""
    match = re.search(r"miyoushe\.com/([a-z-]+)/home/", url)
    game_key = match.group(1) if match else ""
    game_name = _GAME_NAMES.get(game_key, "米游社")
    return build_parsed_content(
        platform="miyoushe",
        item_id=forum_id,
        item_kind="forum",
        title=f"{game_name}·米游社板块",
        summary="（板块页为前端渲染列表，机器人拿不到帖子列表；"
        "想看哪篇帖子，请把帖子链接发我）",
        canonical_url=url,
        parse_depth="shallow",
        page_type="forum",
        badge="板块",
    )


def parse_miyoushe(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """米游社入口：帖子深解析，板块页浅卡，其余 og 兜底。"""
    post_match = _POST_ID_RE.search(url)
    if post_match:
        try:
            return _mys_post_card(
                url, post_match.group(1), cookie_header=cookie_header, proxy=proxy
            )
        except Exception:  # noqa: BLE001, S110 - 接口失败回退 og 浅卡。
            pass
        try:
            return _og_scrape(
                url,
                platform="miyoushe",
                item_kind="post",
                note="（浅层解析；米游社帖子详情接口暂不可用）",
                cookie_header=cookie_header,
                proxy=proxy,
            )
        except Exception:  # noqa: BLE001 - og 也没有（页面无 og meta）给静态卡。
            return build_parsed_content(
                platform="miyoushe",
                item_id=post_match.group(1),
                item_kind="post",
                title="米游社帖子",
                summary="（帖子接口与页面元信息均不可得，已保留原链接）",
                canonical_url=url,
                parse_depth="shallow",
                page_type="post",
            )
    forum_match = _FORUM_ID_RE.search(url)
    if forum_match:
        return _mys_forum_card(url, forum_match.group(1))
    try:
        return _og_scrape(url, platform="miyoushe", item_kind="page", cookie_header=cookie_header)
    except Exception:  # noqa: BLE001
        return build_parsed_content(
            platform="miyoushe",
            item_id="",
            item_kind="page",
            title="米游社页面",
            summary="（该页面无法直接提取内容，点开链接查看）",
            canonical_url=url,
            parse_depth="shallow",
        )

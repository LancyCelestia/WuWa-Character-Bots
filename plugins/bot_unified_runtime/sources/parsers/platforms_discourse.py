"""Discourse 论坛解析（linux.do 与 zlb.ink 共用，基于 parser-lite 样本）。

标准 Discourse topic API：GET /t/{id}.json
→ {fancy_title, posts_count, like_count, post_stream.posts[0]:
   {username, cooked, created_at, avatar_template}}
"""

from __future__ import annotations

import re
import urllib.parse

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import http_get_json

_TOPIC_ID_RE = re.compile(r"/t/topic/(\d+)|/t/[^/\s]+/(\d+)|/t/(\d+)")
_COOKED_TAG_RE = re.compile(r"<[^>]+>")


def _extract_topic_id(url: str) -> str | None:
    match = _TOPIC_ID_RE.search(url or "")
    if not match:
        return None
    return match.group(1) or match.group(2) or match.group(3)


def _parse_discourse_topic(
    api_base: str,
    display_base: str,
    topic_id: str,
    *,
    cookie_header: str = "",
) -> ParsedContent:
    payload = http_get_json(
        f"{api_base}/t/{urllib.parse.quote(topic_id)}.json",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0",
        timeout=8,
    )
    data = payload if isinstance(payload, dict) else {}
    title = str(data.get("fancy_title") or data.get("title") or "").strip() or "论坛帖子"
    posts = ((data.get("post_stream") or {}).get("posts")) or []
    first = posts[0] if posts else {}
    author = str(first.get("username") or "").strip()
    import html as _html

    body = _COOKED_TAG_RE.sub(" ", _html.unescape(str(first.get("cooked") or "")))
    body = re.sub(r"\s{2,}", " ", body).strip()
    lines = [f"作者：{author}" if author else "", body[:800]]
    stats: dict[str, object] = {}
    posts_count = data.get("posts_count")
    like_count = data.get("like_count")
    if isinstance(posts_count, int):
        stats["评论"] = max(0, posts_count - 1)
    if isinstance(like_count, int):
        stats["点赞"] = like_count
    import datetime

    created = str(first.get("created_at") or "")
    published_at = None
    if created:
        try:
            published_at = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            published_at = None
    return build_parsed_content(
        platform="discourse",
        item_id=topic_id,
        item_kind="post",
        title=title,
        author_name=author,
        summary="\n".join(line for line in lines if line)[:1200],
        canonical_url=f"{display_base}/t/topic/{topic_id}",
        stats=stats,
        detail={"published_at": published_at} if published_at is not None else {},
        parse_depth="deep",
    )


def parse_linuxdo(url: str, *, cookie_header: str = "") -> ParsedContent:
    topic_id = _extract_topic_id(url or "")
    if not topic_id:
        raise ValueError(f"linuxdo: no topic id in {url}")
    return _parse_discourse_topic("https://linux.do", "https://linux.do", topic_id)


def parse_zlb(url: str, *, cookie_header: str = "") -> ParsedContent:
    topic_id = _extract_topic_id(url or "")
    if not topic_id:
        raise ValueError(f"zlb: no topic id in {url}")
    return _parse_discourse_topic("https://bb.zlb.ink", "https://zlb.ink", topic_id)

"""豆瓣小组话题解析：基于 parser-lite 的 douban API 样本（vertical.json）。

移动端 Rexxar API：https://m.douban.com/rexxar/api/v2/group/topic/{id}
需要 Referer: https://m.douban.com/；风控时降级 None。
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

_TOPIC_RE = re.compile(r"douban\.com/group/topic/(\d+)", re.IGNORECASE)


def parse_douban_topic(topic_id: str, *, cookie_header: str = "") -> ParsedContent | None:
    payload = http_get_json(
        "https://m.douban.com/rexxar/api/v2/group/topic/" + urllib.parse.quote(topic_id),
        extra_headers={"referer": "https://m.douban.com/group/topic/" + topic_id + "/"},
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
        ),
        timeout=8,
    )
    data = payload if isinstance(payload, dict) else {}
    if not data or not data.get("title"):
        return None
    author = data.get("author") or {}
    stats: dict[str, object] = {}
    comments = data.get("comments_count")
    if comments is None and isinstance(data.get("comment_count"), int):
        comments = data.get("comment_count")
    if isinstance(comments, int):
        stats["评论"] = comments
    recs = data.get("recs_count") or data.get("liked_count")
    if isinstance(recs, int):
        stats["点赞"] = recs
    published_at = None
    create_time = str(data.get("create_time") or "").strip()
    if create_time:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                published_at = datetime.strptime(create_time, fmt).astimezone()
                break
            except ValueError:
                continue
    cover = str(data.get("cover_url") or data.get("header_cover") or "")
    return build_parsed_content(
        platform="douban",
        item_id=topic_id,
        item_kind="post",
        title=str(data.get("title") or "").strip() or "豆瓣小组话题",
        author_name=str((author or {}).get("name") or "").strip(),
        summary=str(data.get("abstract") or data.get("content") or "")[:1200],
        cover_url=cover,
        canonical_url=f"https://www.douban.com/group/topic/{topic_id}/",
        stats=stats,
        detail={"published_at": published_at} if published_at is not None else {},
        parse_depth="deep",
    )


def parse_douban(url: str, *, cookie_header: str = "") -> ParsedContent:
    topic = _TOPIC_RE.search(url or "")
    if topic:
        result = parse_douban_topic(topic.group(1), cookie_header=cookie_header)
        if result is not None:
            return result
        raise ValueError(f"douban: topic unavailable for {url}")
    raise ValueError(f"unsupported douban url: {url}")

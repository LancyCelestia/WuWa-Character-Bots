"""社区平台解析第二批：酷安/虎扑/完美对战/5E/网易大道（ds），基于 parser-lite 端点。"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from datetime import datetime

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import http_get_json

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"

_COOLAPK_FEED_RE = re.compile(r"coolapk(?:1s)?\.com/feed/(\d+)", re.IGNORECASE)
_NEXT_DATA_RE = re.compile(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>\s*(.*?)\s*</script>', re.DOTALL)
_HUPU_TID_RE = re.compile(r"bbs(?:-share)?(?:\.hupu\.com)?[/\\](?:topic/)?(\d+)(?:\.html)?|hupu\.com/(\d+)\.html")
_WMPVP_NEWS_RE = re.compile(r"wmpvp\.com/community-(?:pc)?[Dd]etail\.html\?[^#]*\bid=(\d+)")
_5E_TOPIC_RE = re.compile(r"5eplay\.com/forum/(?:share/)?(\d+)")
_DS_FEED_RE = re.compile(r"ds\.163\.com/(?:article|feed)/([A-Za-z0-9]+)")


def _parse_coolapk_feed(feed_id: str, *, cookie_header: str = "") -> ParsedContent:
    payload = http_get_json(
        f"https://www.coolapk1s.com/feed/{feed_id}",
        user_agent=_UA,
        timeout=10,
    )
    # 实际返回可能是 JSON（api 头）或 HTML（web 页含 __NEXT_DATA__）
    feed: dict = {}
    if isinstance(payload, dict) and payload.get("props"):
        feed = (((payload.get("props") or {}).get("pageProps") or {}).get("feed")) or {}
    elif isinstance(payload, dict) and payload.get("data"):
        feed = payload.get("data") or {}
    if not feed:
        raise ValueError(f"coolapk: feed unavailable {feed_id}")
    stats: dict[str, object] = {}
    for key, label in (("likenum", "点赞"), ("replynum", "评论"), ("forwardnum", "转发")):
        value = feed.get(key)
        if isinstance(value, int):
            stats[label] = value
        elif isinstance(value, str) and value.isdigit():
            stats[label] = int(value)
    published_at = None
    dateline = feed.get("dateline")
    if isinstance(dateline, (int, str)) and str(dateline).isdigit():
        published_at = datetime.fromtimestamp(int(dateline)).astimezone()
    import html as _html

    message = _html.unescape(str(feed.get("message") or "")).strip()
    return build_parsed_content(
        platform="coolapk",
        item_id=feed_id,
        item_kind="post",
        title=str(feed.get("title") or "").strip() or f"{feed.get('username') or '酷安'}的动态",
        author_name=str(feed.get("username") or "").strip(),
        summary=message[:1200],
        cover_url=(feed.get("picArr") or [""])[0] if isinstance(feed.get("picArr"), list) and feed.get("picArr") else str(feed.get("message_cover") or ""),
        canonical_url=f"https://www.coolapk.com/feed/{feed_id}",
        stats=stats,
        detail={"published_at": published_at} if published_at is not None else {},
        parse_depth="deep",
    )


def parse_coolapk(url: str, *, cookie_header: str = "") -> ParsedContent:
    match = _COOLAPK_FEED_RE.search(url or "")
    if not match:
        raise ValueError(f"coolapk: no feed id in {url}")
    return _parse_coolapk_feed(match.group(1), cookie_header=cookie_header)


def _hupu_signed_get(url: str, params: dict, *, cookie_header: str = "") -> dict:
    query = "&".join(f"{key}={params[key]}" for key in sorted(params))
    sign = hashlib.md5(f"{query}HUPU_SALT_AKJfoiwer394Jeiow4u309".encode()).hexdigest()
    full = f"{url}?{query}&sign={sign}"
    payload = http_get_json(
        full,
        user_agent=_UA,
        cookie=cookie_header,
        referer="https://bbs.hupu.com/",
        timeout=8,
    )
    return payload if isinstance(payload, dict) else {}


def parse_hupu(url: str, *, cookie_header: str = "") -> ParsedContent:
    match = _HUPU_TID_RE.search(url or "")
    if not match:
        raise ValueError(f"hupu: no topic id in {url}")
    topic_id = match.group(1) or match.group(2)
    payload = _hupu_signed_get(
        "https://bbs-mobileapi.hupu.com/1/7.5.6/threads/detail",
        {"tid": topic_id},
        cookie_header=cookie_header,
    )
    data = ((payload.get("data") or {}).get("result")) or (payload.get("data") or {})
    if not isinstance(data, dict):
        raise ValueError(f"hupu: topic unavailable {topic_id}")  # noqa: TRY004 - 与平台解析器统一用 ValueError
    thread = data.get("thread") or data
    stats: dict[str, object] = {}
    for key, label in (("likes", "点赞"), ("replies", "回复"), ("hits", "浏览")):
        value = thread.get(key)
        if isinstance(value, int):
            stats[label] = value
    import html as _html

    content = _html.unescape(str(thread.get("content") or "")).strip()
    return build_parsed_content(
        platform="hupu",
        item_id=topic_id,
        item_kind="post",
        title=str(thread.get("title") or "").strip() or "虎扑帖子",
        author_name=str(thread.get("username") or "").strip(),
        summary=content[:1200],
        canonical_url=f"https://bbs.hupu.com/{topic_id}.html",
        stats=stats,
        parse_depth="deep",
    )


def parse_wmpvp(url: str, *, cookie_header: str = "") -> ParsedContent:
    match = _WMPVP_NEWS_RE.search(url or "")
    if not match:
        raise ValueError(f"wmpvp: no news id in {url}")
    news_id = match.group(1)
    payload = http_get_json(
        "https://appactivity.wmpvp.com/steamcn/app/news/getAppNewsById",
        user_agent=_UA,
        timeout=8,
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    news_list = (result or {}).get("news") or []
    news = next((n for n in news_list if str(n.get("id")) == news_id), news_list[0] if news_list else None)
    if not isinstance(news, dict):
        raise ValueError(f"wmpvp: news unavailable {news_id}")  # noqa: TRY004 - 平台解析器统一 ValueError
    return build_parsed_content(
        platform="wmpvp",
        item_id=news_id,
        item_kind="post",
        title=str(news.get("title") or news.get("name") or "").strip() or "完美世界新闻",
        author_name=str(news.get("author") or news.get("create_by") or "").strip(),
        summary=str(news.get("description") or news.get("summary") or "")[:1200],
        cover_url=str(news.get("cover") or news.get("img_url") or ""),
        canonical_url=f"https://news.wmpvp.com/community-detail.html?id={news_id}",
        parse_depth="deep",
    )


def parse_5eplay(url: str, *, cookie_header: str = "") -> ParsedContent:
    match = _5E_TOPIC_RE.search(url or "")
    if not match:
        raise ValueError(f"5eplay: no topic id in {url}")
    topic_id = match.group(1)
    payload = http_get_json(
        f"https://app.5eplay.com/api/csgo/forum/topic/{topic_id}",
        user_agent=_UA,
        timeout=8,
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    topic = (data or {}).get("topic") or (data or {})
    if not isinstance(topic, dict) or not topic:
        raise ValueError(f"5eplay: topic unavailable {topic_id}")
    stats: dict[str, object] = {}
    for key, label in (("view_num", "浏览"), ("reply_num", "回复"), ("like_num", "点赞")):
        value = topic.get(key)
        if isinstance(value, int):
            stats[label] = value
    return build_parsed_content(
        platform="5eplay",
        item_id=topic_id,
        item_kind="post",
        title=str(topic.get("title") or "").strip() or "5E 帖子",
        author_name=str((topic.get("user") or {}).get("username") or "").strip(),
        summary=str(topic.get("content") or topic.get("summary") or "")[:1200],
        canonical_url=f"https://csgo.5eplay.com/forum/{topic_id}",
        stats=stats,
        parse_depth="deep",
    )


def parse_ds163(url: str, *, cookie_header: str = "") -> ParsedContent:
    match = _DS_FEED_RE.search(url or "")
    if not match:
        raise ValueError(f"ds163: no feed id in {url}")
    feed_id = match.group(1)
    payload = http_get_json(
        "https://inf.ds.163.com/v1/web/feed/basic/facade?"
        + urllib.parse.urlencode({"feedId": feed_id}),
        user_agent=_UA,
        timeout=8,
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    feed = (data or {}).get("feed") or (data or {})
    if not isinstance(feed, dict) or not feed:
        raise ValueError(f"ds163: feed unavailable {feed_id}")
    return build_parsed_content(
        platform="ds163",
        item_id=feed_id,
        item_kind="post",
        title=str(feed.get("title") or "").strip() or "网易大道动态",
        author_name=str((feed.get("user_info") or {}).get("nickname") or "").strip(),
        summary=str(feed.get("content") or "")[:1200],
        canonical_url=f"https://ds.163.com/feed/{feed_id}",
        parse_depth="deep",
    )

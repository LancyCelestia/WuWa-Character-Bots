"""知乎解析（回答/文章/问题）：基于 parser-lite 的 zhihu API 样本实现。

- 回答：https://www.zhihu.com/api/v4/answers/{id}?include=...
- 文章：https://www.zhihu.com/api/v4/articles/{id}
- 问题：https://www.zhihu.com/api/v4/questions/{id}/feeds（取首答摘要）
知乎风控较严，未登录时可能 403——失败按 None 降级，由上层回退通用抓取。
"""

from __future__ import annotations

import re
import urllib.parse

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import http_get_json

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_ANSWER_RE = re.compile(r"zhihu\.com/question/(\d+)/answer/(\d+)", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"zhuanlan\.zhihu\.com/p/(\d+)", re.IGNORECASE)
_QUESTION_RE = re.compile(r"zhihu\.com/question/(\d+)", re.IGNORECASE)


def _headers(cookie_header: str) -> dict[str, str]:
    headers = {"referer": "https://www.zhihu.com/"}
    if cookie_header:
        headers["cookie"] = cookie_header
    return headers


def _safe_int(value: object) -> int | None:
    try:
        text = str(value or "").strip()
        if text.endswith(("w", "万")):
            return int(float(text.rstrip("w万")) * 10000)
        return int(text)
    except (TypeError, ValueError):
        return None


def _fmt_time(value: object) -> str:
    import datetime

    seconds = _safe_int(value)
    if seconds is None:
        return ""
    return datetime.datetime.fromtimestamp(seconds).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _author_lines(author: dict) -> str:
    name = str((author or {}).get("name") or "").strip()
    headline = str((author or {}).get("headline") or "").strip()
    return " · ".join(part for part in (name, headline) if part)


def parse_zhihu_answer(answer_id: str, *, cookie_header: str = "") -> ParsedContent | None:
    payload = http_get_json(
        "https://www.zhihu.com/api/v4/answers/"
        + urllib.parse.quote(answer_id)
        + "?include=voteup_count,comment_count,content,excerpt,created_time,updated_time",
        extra_headers=_headers(cookie_header),
        user_agent=_USER_AGENT,
        timeout=8,
    )
    data = payload if isinstance(payload, dict) else {}
    if not data:
        return None
    author = data.get("author") or {}
    question = data.get("question")
    title = str(question.get("title") or "") if isinstance(question, dict) else ""
    # API 返回了真实 question.id，别再硬编码 question/0/（卡片链接会 404）。
    question_id = str(question.get("id") or "") if isinstance(question, dict) else ""
    stats: dict[str, object] = {}
    voteup = _safe_int(data.get("voteup_count"))
    comments = _safe_int(data.get("comment_count"))
    if voteup is not None:
        stats["点赞"] = voteup
    if comments is not None:
        stats["评论"] = comments
    import datetime

    created = _safe_int(data.get("created_time"))
    published_at = (
        datetime.datetime.fromtimestamp(created).astimezone() if created is not None else None
    )
    return build_parsed_content(
        platform="zhihu",
        item_id=answer_id,
        item_kind="article",
        title=title or "知乎回答",
        author_name=_author_lines(author),
        summary=str(data.get("excerpt") or "")[:1200],
        canonical_url=(
            f"https://www.zhihu.com/question/{question_id or '0'}/answer/{answer_id}"
        ),
        stats=stats,
        detail={"published_at": published_at} if published_at is not None else {},
        parse_depth="deep",
    )


def parse_zhihu_article(article_id: str, *, cookie_header: str = "") -> ParsedContent | None:
    payload = http_get_json(
        "https://www.zhihu.com/api/v4/articles/" + urllib.parse.quote(article_id),
        extra_headers=_headers(cookie_header),
        user_agent=_USER_AGENT,
        timeout=8,
    )
    data = payload if isinstance(payload, dict) else {}
    if not data:
        return None
    author = data.get("author") or {}
    stats: dict[str, object] = {}
    for src_key, label in (("voteup_count", "点赞"), ("comment_count", "评论"), ("title_image", None)):
        if label is None:
            continue
        value = _safe_int(data.get(src_key))
        if value is not None:
            stats[label] = value
    import datetime

    created = _safe_int(data.get("created"))
    published_at = (
        datetime.datetime.fromtimestamp(created).astimezone() if created is not None else None
    )
    cover = str(data.get("title_image") or data.get("image_url") or "")
    return build_parsed_content(
        platform="zhihu",
        item_id=article_id,
        item_kind="article",
        title=str(data.get("title") or "").strip() or "知乎文章",
        author_name=_author_lines(author),
        summary=str(data.get("excerpt") or "")[:1200],
        cover_url=cover,
        canonical_url=f"https://zhuanlan.zhihu.com/p/{article_id}",
        stats=stats,
        detail={"published_at": published_at} if published_at is not None else {},
        parse_depth="deep",
    )


def parse_zhihu(url: str, *, cookie_header: str = "") -> ParsedContent:
    answer = _ANSWER_RE.search(url or "")
    if answer:
        result = parse_zhihu_answer(answer.group(2), cookie_header=cookie_header)
        if result is not None:
            return result
        raise ValueError(f"zhihu: answer unavailable for {url}")
    article = _ARTICLE_RE.search(url or "")
    if article:
        result = parse_zhihu_article(article.group(1), cookie_header=cookie_header)
        if result is not None:
            return result
        raise ValueError(f"zhihu: article unavailable for {url}")
    raise ValueError(f"unsupported zhihu url: {url}")

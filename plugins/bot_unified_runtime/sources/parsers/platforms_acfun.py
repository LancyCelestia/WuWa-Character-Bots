"""AcFun（www.acfun.cn / live.acfun.cn）链接解析。

- 视频（``/v/ac{id}``）：页面内 ``window.videoInfo``（标题/封面/简介/UP主/
  播放/弹幕/评论/点赞/收藏/香蕉/发布时间/时长）；
- 番剧（``/bangumi/aa{id}``）：``window.bangumiData``（番剧名/横竖封面/简介/
  集数/播放/评论/收藏/点赞/首播时间）；
- 文章（``/a/ac{id}``）：``window.articleInfo``（正文不在 SSR，摘要不可得）；
- 直播（``live.acfun.cn/live/{authorId}``）：``window.__INITIAL_STATE__.liveInfo``
  （标题/封面/人气/点赞/开播状态/主播）；
- 任一状态缺失时回退 og / 静态卡，不抛未捕获异常。
"""

from __future__ import annotations

import json
import re

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    http_get_text,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    _format_epoch,
    _og_scrape,
)

_VIDEO_RE = re.compile(r"acfun\.cn/v/ac(\d+)")
_ARTICLE_RE = re.compile(r"acfun\.cn/a/ac(\d+)")
_BANGUMI_RE = re.compile(r"acfun\.cn/bangumi/aa(\d+)")
_LIVE_RE = re.compile(r"live\.acfun\.cn/live/(\d+)")
_TAG_SPAN_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _acfun_window_json(html_text: str, marker: str) -> dict | None:
    """提取 window.xxx = {...};（raw_decode 到字面量结束，容忍尾缀 [[0]]）。"""
    idx = html_text.find(marker)
    if idx < 0:
        return None
    eq = html_text.find("=", idx)
    if eq < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(html_text[eq + 1 :].lstrip())
    except Exception:  # noqa: BLE001 - 截断/变形时放弃。
        return None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return payload if isinstance(payload, dict) else None


def _acfun_clean(value: object) -> str:
    text = _TAG_SPAN_RE.sub("", str(value or ""))
    return _WHITESPACE_RE.sub(" ", text).strip()


def _acfun_duration(milliseconds: object) -> str:
    """毫秒 → 'MM:SS' / 'HH:MM:SS'；非法输入返回空。"""
    try:
        total = int(str(milliseconds).strip()) // 1000
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _acfun_fetch(url: str, cookie_header: str, proxy: str) -> str:
    _, text = http_get_text(url, timeout=15, cookie=cookie_header, proxy=proxy)
    return text


def _acfun_author_detail(user: dict) -> dict:
    """视频/文章页 user 对象 → detail['author']。"""
    detail: dict = {}
    if user.get("href"):
        detail["uuid"] = str(user.get("href"))
    if user.get("headUrl"):
        detail["avatar"] = str(user.get("headUrl"))
    if user.get("avatarImage") and not detail.get("avatar"):
        detail["avatar"] = str(user.get("avatarImage"))
    fans = user.get("fanCountValue")
    if fans not in (None, "", "0"):
        detail["fans"] = int(fans) if str(fans).isdigit() else fans
    return detail


def _acfun_video_result(info: dict, url: str) -> ParsedContent:
    user = info.get("user") or {}
    title = str(info.get("title") or "").strip() or "AcFun 视频"
    stats: dict = {}
    for key, label in (
        ("viewCount", "播放"),
        ("likeCount", "点赞"),
        ("danmakuCount", "弹幕"),
        ("commentCount", "评论"),
        ("stowCount", "收藏"),
        ("bananaCount", "香蕉"),
    ):
        value = info.get(key)
        if isinstance(value, (int, float)) and value > 0:
            stats[label] = int(value)
    publish_time = _format_epoch(info.get("createTimeMillis"))
    if publish_time:
        stats["发布时间"] = publish_time
    description = _acfun_clean(info.get("description"))
    if len(description) > 300:
        description = description[:300] + "…"
    duration = _acfun_duration(info.get("durationMillis"))
    detail: dict = {"author": _acfun_author_detail(user)} if user else {}
    if duration:
        detail["duration"] = duration
    return build_parsed_content(
        platform="acfun",
        item_id=str(info.get("dougaId") or info.get("groupId") or ""),
        item_kind="video",
        title=title,
        author_name=str(user.get("name") or ""),
        summary=description,
        cover_url=str(info.get("coverUrl") or ""),
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="video",
        badge="AcFun 视频",
        detail=detail,
    )


def _acfun_bangumi_result(data: dict, url: str) -> ParsedContent:
    title = str(data.get("bangumiTitle") or "").strip() or "AcFun 番剧"
    stats: dict = {}
    for key, label in (
        ("playCount", "播放"),
        ("commentCount", "评论"),
        ("stowCount", "收藏"),
        ("bangumiLikeCount", "点赞"),
    ):
        value = data.get(key)
        if isinstance(value, (int, float)) and value > 0:
            stats[label] = int(value)
    episodes = data.get("itemCount")
    if isinstance(episodes, (int, float)) and episodes > 0:
        stats["集数"] = int(episodes)
    first_play = _format_epoch(data.get("firstPlayDate"))
    if first_play:
        stats["首播时间"] = first_play
    intro = _acfun_clean(data.get("bangumiIntro"))
    if len(intro) > 300:
        intro = intro[:300] + "…"
    cover = str(data.get("bangumiCoverImageV") or data.get("bangumiCoverImageH") or "")
    return build_parsed_content(
        platform="acfun",
        item_id=str(data.get("bangumiId") or ""),
        item_kind="bangumi",
        title=title,
        author_name="",
        summary=intro,
        cover_url=cover,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="bangumi",
        badge="番剧",
    )


def _acfun_article_result(info: dict, url: str) -> ParsedContent:
    user = info.get("user") or {}
    title = str(info.get("title") or "").strip() or "AcFun 文章"
    stats: dict = {}
    for key, label in (
        ("viewCount", "阅读"),
        ("likeCount", "点赞"),
        ("commentCount", "评论"),
        ("bananaCount", "香蕉"),
        ("stowCount", "收藏"),
    ):
        value = info.get(key)
        if isinstance(value, (int, float)) and value > 0:
            stats[label] = int(value)
    publish_time = _format_epoch(info.get("createTimeMillis"))
    if publish_time:
        stats["发布时间"] = publish_time
    description = _acfun_clean(info.get("description"))
    if len(description) > 300:
        description = description[:300] + "…"
    if not description:
        # 正文不在 SSR 里（客户端渲染），如实说明拿不到摘要。
        description = "（文章正文由前端渲染，机器人只取到元信息）"
    return build_parsed_content(
        platform="acfun",
        item_id=str(info.get("articleId") or ""),
        item_kind="article",
        title=title,
        author_name=str(user.get("name") or ""),
        summary=description,
        cover_url=str(info.get("coverUrl") or ""),
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="article",
        badge="AcFun 文章",
        detail={"author": _acfun_author_detail(user)} if user else {},
    )


def _acfun_live_result(state: dict, url: str) -> ParsedContent | None:
    live_info = state.get("liveInfo") or {}
    if not isinstance(live_info, dict) or not live_info.get("title"):
        return None
    user = live_info.get("user") or {}
    title = str(live_info.get("title") or "").strip() or "AcFun 直播间"
    stats: dict = {}
    online = live_info.get("onlineCount")
    if isinstance(online, (int, float)) and online >= 0:
        stats["人气"] = int(online)
    likes = live_info.get("likeCount")
    if isinstance(likes, (int, float)) and likes > 0:
        stats["点赞"] = int(likes)
    start_time = _format_epoch(live_info.get("createTime"))
    if start_time:
        stats["开播时间"] = start_time
    # result==0 且有 streamName 视为开播中，其余视为未开播/数据缺失。
    result = live_info.get("result")
    is_living = (result in (0, "0")) and bool(live_info.get("streamName"))
    cover = ""
    cover_urls = live_info.get("coverUrls") or []
    for node in cover_urls:
        if isinstance(node, dict) and node.get("url"):
            cover = str(node["url"])
            break
        if isinstance(node, str):
            cover = node
            break
    author_detail: dict = {}
    if user.get("href"):
        author_detail["uuid"] = str(user.get("href"))
    if user.get("headUrl"):
        author_detail["avatar"] = str(user.get("headUrl"))
    if user.get("signature"):
        author_detail["signature"] = str(user.get("signature"))
    return build_parsed_content(
        platform="acfun",
        item_id=str(live_info.get("authorId") or ""),
        item_kind="live",
        title=title[:60],
        author_name=str(user.get("name") or ""),
        summary=str(user.get("signature") or ""),
        cover_url=cover,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="live",
        badge="直播中" if is_living else "未开播",
        detail={"author": author_detail} if author_detail else {},
    )


def _acfun_static_card(
    url: str,
    *,
    item_kind: str,
    label: str,
) -> ParsedContent:
    return build_parsed_content(
        platform="acfun",
        item_id="",
        item_kind=item_kind,
        title=f"AcFun {label}",
        summary="（该页面数据无法直接提取，点开链接查看）",
        canonical_url=url,
        parse_depth="shallow",
        page_type=item_kind,
    )


def parse_acfun(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """AcFun 入口：视频 / 番剧 / 文章 / 直播分流，失败回退 og 或静态卡。"""
    try:
        if _VIDEO_RE.search(url):
            text = _acfun_fetch(url, cookie_header, proxy)
            info = _acfun_window_json(text, "window.videoInfo")
            if info and info.get("title"):
                return _acfun_video_result(info, url)
        elif _BANGUMI_RE.search(url):
            text = _acfun_fetch(url, cookie_header, proxy)
            data = _acfun_window_json(text, "window.bangumiData")
            if data and data.get("bangumiTitle"):
                return _acfun_bangumi_result(data, url)
        elif _ARTICLE_RE.search(url):
            text = _acfun_fetch(url, cookie_header, proxy)
            info = _acfun_window_json(text, "window.articleInfo")
            if info and info.get("title"):
                return _acfun_article_result(info, url)
        elif _LIVE_RE.search(url):
            text = _acfun_fetch(url, cookie_header, proxy)
            state = _acfun_window_json(text, "window.__INITIAL_STATE__")
            if isinstance(state, dict):
                item = _acfun_live_result(state, url)
                if item is not None:
                    return item
    except Exception:  # noqa: BLE001, S110 - 深解析失败统一回退 og。
        pass
    try:
        return _og_scrape(url, platform="acfun", item_kind="video", cookie_header=cookie_header)
    except Exception:  # noqa: BLE001 - og 也没有时给静态卡。
        if _LIVE_RE.search(url):
            return _acfun_static_card(url, item_kind="live", label="直播间")
        if _BANGUMI_RE.search(url):
            return _acfun_static_card(url, item_kind="bangumi", label="番剧")
        if _ARTICLE_RE.search(url):
            return _acfun_static_card(url, item_kind="article", label="文章")
        return _acfun_static_card(url, item_kind="video", label="视频")

"""快手（www.kuaishou.com / live.kuaishou.com）链接解析。

- 短视频页（``/short-video/{photoId}``）：SSR 页面内 ``window.__APOLLO_STATE__``
  存 Apollo 缓存实体（VisionVideoDetailPhoto / VisionVideoDetailAuthor），
  解析出标题 / 作者 / 封面 / 播放 / 点赞 / 发布时间（计数多为"2.7万"中文数字）。
- 直播间（``live.kuaishou.com/u/{handle}``）：页面内 ``window.__INITIAL_STATE__``
  → liveroom.playList[0] 的 liveStream / author；数据中心 IP 常被风控限流
  （errorType"请求过快"），此时诚实降级入口卡。
- 无登录 Cookie 也可尝试（页面数据在 SSR 里），Cookie 只提高成功率。
"""

from __future__ import annotations

import json
import re

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_text,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    _format_epoch,
    _og_scrape,
    _parse_cn_count,
)

_APOLLO_MARKER = "__APOLLO_STATE__"
_LIVE_STATE_MARKER = "window.__INITIAL_STATE__"
_PHOTO_ID_RE = re.compile(r"kuaishou\.com/(?:short-video|video|fw/photo)/([\w-]+)")
_LIVE_HANDLE_RE = re.compile(r"live\.kuaishou\.com/u/([\w.-]+)")


def _ks_apollo_state(html_text: str) -> dict | None:
    """提取 window.__APOLLO_STATE__ = {...}; 返回 Apollo 缓存。"""
    idx = html_text.find(_APOLLO_MARKER)
    if idx < 0:
        return None
    eq = html_text.find("=", idx)
    if eq < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(html_text[eq + 1 :].lstrip())
    except Exception:  # noqa: BLE001 - 数据截断/变形时放弃。
        return None
    if not isinstance(payload, dict):
        return None
    root = payload.get("defaultClient")
    if isinstance(root, dict):
        return root
    # 兜底：任一 client 分支里含实体就返回。
    for value in payload.values():
        if isinstance(value, dict) and value:
            return value
    return None


def _ks_resolve_ref(root: dict, value: object) -> dict | None:
    """Apollo 引用 {type:'id', id:'VisionVideoDetailAuthor:x'} → 实体。"""
    if isinstance(value, dict) and value.get("id") and value.get("type") in (None, "id"):
        entity = root.get(str(value.get("id")))
        if isinstance(entity, dict):
            return entity
    if isinstance(value, dict) and value.get("__ref"):
        entity = root.get(str(value.get("__ref")))
        if isinstance(entity, dict):
            return entity
    if isinstance(value, dict):
        return value
    return None


def _ks_find_entity(root: dict, typename: str) -> dict | None:
    """按 typename 找第一个实体（VisionVideoDetailPhoto / ...Author）。"""
    for value in root.values():
        if isinstance(value, dict) and value.get("__typename") == typename:
            return value
    return None


def _ks_photo_result(root: dict, url: str, photo_id: str) -> ParsedContent | None:
    """从 Apollo 实体组装视频卡；数据不齐时返回 None 走降级。"""
    photo = _ks_find_entity(root, "VisionVideoDetailPhoto")
    if not photo or not photo.get("caption"):
        return None
    author = _ks_resolve_ref(root, photo.get("author")) or _ks_find_entity(
        root, "VisionVideoDetailAuthor"
    )
    caption = str(photo.get("caption") or "").strip()
    first_line = caption.split("\n")[0].strip() or "快手视频"
    title = first_line[:40] + ("…" if len(first_line) > 40 else "")
    stats: dict = {}
    plays = _parse_cn_count(photo.get("viewCount"))
    likes = _parse_cn_count(photo.get("realLikeCount") or photo.get("likeCount"))
    comments = _parse_cn_count(photo.get("commentCount"))
    if plays:
        stats["播放"] = plays
    if likes:
        stats["点赞"] = likes
    if comments:
        stats["评论"] = comments
    publish_time = _format_epoch(photo.get("timestamp"))
    if publish_time:
        stats["发布时间"] = publish_time
    author = author or {}
    author_name = str(author.get("name") or "")
    author_detail: dict = {}
    if (author or {}).get("id"):
        author_detail["uuid"] = str(author.get("id"))
    if (author or {}).get("headerUrl"):
        author_detail["avatar"] = str(author.get("headerUrl"))
    summary = caption[:500] + ("…" if len(caption) > 500 else "")
    return build_parsed_content(
        platform="kuaishou",
        item_id=str(photo.get("id") or photo_id),
        item_kind="video",
        title=title,
        author_name=author_name,
        summary=summary,
        cover_url=str(photo.get("coverUrl") or ""),
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="photo",
        detail={"author": author_detail} if author_detail else {},
    )


def _ks_photo_card(
    url: str,
    photo_id: str,
    *,
    cookie_header: str = "",
    proxy: str = "",
) -> ParsedContent:
    """短视频页深解析；Apollo 缺失回退 og。"""
    _, text = http_get_text(
        url,
        timeout=15,
        cookie=cookie_header,
        proxy=proxy,
        referer="https://www.kuaishou.com/",
    )
    root = _ks_apollo_state(text)
    if root:
        item = _ks_photo_result(root, url, photo_id)
        if item is not None:
            return item
    raise ParseHttpError("kuaishou: apollo state missing photo")


def _ks_live_result(state: dict, url: str, handle: str) -> ParsedContent | None:
    """从 __INITIAL_STATE__ 的 liveroom.playList 组装直播间卡。"""
    liveroom = state.get("liveroom") or {}
    playlist = liveroom.get("playList") or []
    if not isinstance(playlist, list) or not playlist:
        return None
    first = playlist[0] or {}
    error = first.get("errorType") or {}
    if isinstance(error, dict) and error.get("title"):
        # 风控限流 / 房间不存在：明确标记，交由上层降级。
        return None
    live_stream = first.get("liveStream") or {}
    author = first.get("author") or {}
    if not isinstance(live_stream, dict) or not (live_stream.get("caption") or live_stream.get("id")):
        return None
    is_living = bool(first.get("isLiving")) or bool(live_stream.get("liveStatus") in (2, "2"))
    title = str(live_stream.get("caption") or "").strip() or f"{author.get('name') or handle}的直播间"
    stats: dict = {}
    watching = _parse_cn_count(
        live_stream.get("watchingCount") or live_stream.get("actualWatcherCount")
    )
    if watching:
        stats["观看"] = watching
    publish_time = _format_epoch(live_stream.get("createTime"))
    if publish_time:
        stats["开播时间"] = publish_time
    author_detail: dict = {}
    if author.get("id"):
        author_detail["uuid"] = str(author.get("id"))
    if author.get("coverUrl"):
        author_detail["avatar"] = str(author.get("coverUrl"))
    cover = str(live_stream.get("coverUrl") or author.get("coverUrl") or "")
    game_name = str(live_stream.get("gameName") or "").strip()
    return build_parsed_content(
        platform="kuaishou",
        item_id=str(live_stream.get("id") or handle),
        item_kind="live",
        title=title[:60],
        author_name=str(author.get("name") or handle),
        summary=f"游戏分类：{game_name}" if game_name else "",
        cover_url=cover,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="live",
        badge="直播中" if is_living else "未开播",
        detail={"author": author_detail} if author_detail else {},
    )


def _ks_live_card(
    url: str,
    handle: str,
    *,
    cookie_header: str = "",
    proxy: str = "",
) -> ParsedContent:
    """直播间解析：SSR 状态可用出深卡，被风控限流给诚实入口卡。"""
    try:
        _, text = http_get_text(
            url,
            timeout=15,
            cookie=cookie_header,
            proxy=proxy,
            referer="https://live.kuaishou.com/",
        )
    except ParseHttpError:
        text = ""
    if text:
        idx = text.find(_LIVE_STATE_MARKER)
        if idx >= 0:
            eq = text.find("=", idx)
            try:
                state, _ = json.JSONDecoder().raw_decode(text[eq + 1 :].lstrip())
            except Exception:  # noqa: BLE001 - 状态截断时按限流处理。
                state = None
            if isinstance(state, dict):
                item = _ks_live_result(state, url, handle)
                if item is not None:
                    return item
    # 走到这里：页面被风控限流（errorType 请求过快）或未开播数据为空。
    return build_parsed_content(
        platform="kuaishou",
        item_id=handle,
        item_kind="live",
        title=f"快手直播间 @{handle}",
        summary="（直播间数据由页面脚本动态加载且被快手风控限流，"
        "机器人当前拿不到主播/人气；点开链接即可观看）",
        canonical_url=url,
        parse_depth="shallow",
        page_type="live",
    )


def _ks_fallback(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """其余快手 URL 的 og 兜底。"""
    try:
        return _og_scrape(
            url,
            platform="kuaishou",
            item_kind="page",
            cookie_header=cookie_header,
            proxy=proxy,
        )
    except Exception:  # noqa: BLE001 - og 也失败给静态卡。
        return build_parsed_content(
            platform="kuaishou",
            item_id="",
            item_kind="page",
            title="快手链接",
            summary="（该页面需要登录态或动态渲染，已保留原链接）",
            canonical_url=url,
            parse_depth="shallow",
        )


def parse_kuaishou(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """快手入口：短视频 / 直播间分流，其余 og 兜底。"""
    photo_match = _PHOTO_ID_RE.search(url)
    if photo_match:
        try:
            return _ks_photo_card(
                url, photo_match.group(1), cookie_header=cookie_header, proxy=proxy
            )
        except Exception:  # noqa: BLE001, S110 - 深解析失败回退 og。
            pass
        return _ks_fallback(url, cookie_header=cookie_header, proxy=proxy)
    live_match = _LIVE_HANDLE_RE.search(url)
    if live_match:
        return _ks_live_card(
            url, live_match.group(1), cookie_header=cookie_header, proxy=proxy
        )
    return _ks_fallback(url, cookie_header=cookie_header, proxy=proxy)

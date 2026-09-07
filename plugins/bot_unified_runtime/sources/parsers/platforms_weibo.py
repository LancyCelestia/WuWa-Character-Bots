"""微博（weibo.com / m.weibo.cn）链接解析。

- 单条微博（``weibo.com/{uid}/{bid}``、``m.weibo.cn/status/{bid}``）：
  GET ``https://m.weibo.cn/status/{bid}``（登录态 Cookie 可用）从页面内
  ``window.$render_data`` 提取完整微博：正文 / 作者 / 头像 / 转发评论点赞 /
  发布时间 / 配图；长微博再走 ``/statuses/extend`` 补全文。
- 用户主页（``weibo.com/u/{uid}``）：``m.weibo.cn/api/container/getIndex``
  的 userInfo 拿昵称 / 简介 / 粉丝关注微博数，出深度用户卡。
- 数据不可得时诚实降级（不伪造正文）。
"""

from __future__ import annotations

import datetime
import html
import json
import re
import time
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
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    _og_scrape,
    _parse_cn_count,
    _truncate_keep_links,
)

_WEIBO_STATUS_URL = "https://m.weibo.cn/status/{bid}"
_WEIBO_SHOW_API = "https://m.weibo.cn/statuses/show?id={bid}"
_WEIBO_AJAX_API = "https://weibo.com/ajax/statuses/show?id={bid}"
_WEIBO_EXTEND_URL = "https://m.weibo.cn/statuses/extend?id={id}"
_WEIBO_USER_API = "https://m.weibo.cn/api/container/getIndex?type=uid&value={uid}"
_WEIBO_PC_PROFILE_API = "https://weibo.com/ajax/profile/info?uid={uid}"

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?\s*>", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BID_RE = re.compile(r"weibo\.com/(?:\d+)/([0-9A-Za-z]+)")
_M_STATUS_RE = re.compile(r"m\.weibo\.cn/status/([0-9A-Za-z]+)")
_UID_RE = re.compile(r"weibo\.com/(?:u/)?(\d{5,})(?:[/?#]|$)")

# m.weibo.cn 对 PC UA 一律 302 到访客验证（retcode=6102），即使带登录 Cookie；
# 必须用移动端 UA + XHR 头才会返回 JSON/页面数据（实测确认）。
_WEIBO_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)
_WEIBO_MOBILE_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "MWeibo-Pwa": "1",
    "Accept": "application/json, text/plain, */*",
}


def _strip_html(value: object) -> str:
    """微博正文 HTML → 纯文本（保留 <br> 换行）。"""
    text = str(value or "")
    text = _BR_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _weibo_created_at(value: object) -> str:
    """'Wed Aug 26 17:35:31 +0800 2026' → 'YYYY-MM-DD HH:MM'；失败返回空。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        return ""
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def _weibo_get_text_with_retry(
    url: str,
    *,
    cookie_header: str = "",
    proxy: str = "",
    attempts: int = 3,
    pause: float = 1.5,
) -> str:
    """m.weibo.cn 对连续请求有间歇性风控，失败短停重试后再放弃。"""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            _, text = http_get_text(
                url,
                timeout=12,
                cookie=cookie_header,
                proxy=proxy,
                referer="https://m.weibo.cn/",
                user_agent=_WEIBO_MOBILE_UA,
                extra_headers=_WEIBO_MOBILE_HEADERS,
            )
            if "$render_data" in text or attempt == attempts - 1:
                return text
            last_exc = ParseHttpError("weibo: render_data absent in page")
        except ParseHttpError as exc:
            last_exc = exc
        if attempt < attempts - 1:
            time.sleep(pause)
    raise last_exc or ParseHttpError(f"weibo: GET {url} failed")


def _weibo_render_data(html_text: str) -> dict | None:
    """从 m.weibo.cn 页面提取 window.$render_data = {...}[[0]]; 的对象。"""
    idx = html_text.find("$render_data")
    if idx < 0:
        return None
    eq = html_text.find("=", idx)
    if eq < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(html_text[eq + 1 :].lstrip())
    except Exception:  # noqa: BLE001 - 页面数据被截断/变形时放弃。
        return None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return payload if isinstance(payload, dict) else None


def _weibo_pics(status: dict) -> list[str]:
    """配图列表：优先 pic_infos.largest，退化 pic_ids 拼 large 地址。"""
    urls: list[str] = []
    pic_infos = status.get("pic_infos") or {}
    if isinstance(pic_infos, dict):
        for info in pic_infos.values():
            if not isinstance(info, dict):
                continue
            node = info.get("largest") or info.get("large") or info.get("medium") or {}
            url = str((node or {}).get("url") or "")
            if url:
                urls.append(url)
    if not urls:
        for pic_id in status.get("pic_ids") or []:
            if pic_id:
                urls.append(f"https://wx1.sinaimg.cn/large/{pic_id}.jpg")
    return urls


def _weibo_longtext(status: dict, *, cookie_header: str = "", proxy: str = "") -> str:
    """长微博补全文（statuses/extend），失败返回空串不致命。"""
    if not status.get("isLongText"):
        return ""
    weibo_id = str(status.get("id") or "")
    if not weibo_id:
        return ""
    try:
        payload = http_get_json(
            _WEIBO_EXTEND_URL.format(id=weibo_id),
            timeout=10,
            cookie=cookie_header,
            proxy=proxy,
            referer="https://m.weibo.cn/",
            user_agent=_WEIBO_MOBILE_UA,
            extra_headers=_WEIBO_MOBILE_HEADERS,
        )
        return _strip_html((payload or {}).get("data", {}).get("longTextContent"))
    except Exception:  # noqa: BLE001 - 补全文失败不影响主卡。
        return ""


def _weibo_author_detail(user: dict) -> dict:
    detail: dict = {}
    if user.get("id"):
        detail["uuid"] = str(user.get("id"))
    if user.get("profile_image_url"):
        detail["avatar"] = str(user.get("profile_image_url"))
    if user.get("avatar_hd"):
        detail["avatar_hd"] = str(user.get("avatar_hd"))
    if user.get("description"):
        detail["signature"] = str(user.get("description"))
    followers = _parse_cn_count(user.get("followers_count"))
    if followers:
        detail["fans"] = followers
    following = _parse_cn_count(user.get("follow_count") or user.get("friends_count"))
    if following:
        detail["following"] = following
    statuses = _parse_cn_count(user.get("statuses_count"))
    if statuses:
        detail["posts"] = statuses
    if user.get("verified"):
        detail["verified"] = bool(user.get("verified"))
    if user.get("verified_reason"):
        detail["verified_reason"] = str(user.get("verified_reason"))
    if user.get("created_at"):
        detail["created_at"] = str(user.get("created_at"))
    if user.get("profile_url"):
        detail["profile_url"] = str(user.get("profile_url"))
    return detail


def _weibo_video_meta(status: dict) -> dict | None:
    """视频博文的 page_info → 视频直链/预览/时长/宽高；非视频返回 None。"""
    page_info = status.get("page_info")
    if not isinstance(page_info, dict) or str(page_info.get("type") or "") != "video":
        return None
    media_info = page_info.get("media_info")
    if not isinstance(media_info, dict):
        return None
    video_url = str(
        media_info.get("stream_url_hd")
        or media_info.get("stream_url")
        or media_info.get("mp4_hd_url")
        or media_info.get("mp4_sd_url")
        or ""
    ).strip()
    meta: dict = {}
    if video_url:
        meta["url"] = video_url
    for key in ("duration", "width", "height"):
        value = media_info.get(key)
        if isinstance(value, (int, float)) and value > 0:
            meta[key] = int(value)
    page_pic = page_info.get("page_pic")
    if isinstance(page_pic, dict):
        preview = str(page_pic.get("url") or "")
        if preview:
            meta["preview_url"] = preview
    return meta or None


def _weibo_status_result(status: dict, url: str) -> ParsedContent:
    """把 status 对象规整成深度微博卡（含转发摘要）。"""
    text = _strip_html(
        status.get("raw_text") or status.get("text_raw") or status.get("text")
    )
    longtext = _weibo_longtext(status)
    if longtext and len(longtext) > len(text):
        text = longtext
    if not text:
        raise ParseHttpError("weibo: status has no text")
    author = status.get("user") or {}
    title = text.split("\n")[0][:40] or "微博"
    if len(title) < len(text.split("\n")[0]):
        title += "…"
    stats: dict = {}
    for key, label in (
        ("reposts_count", "转发"),
        ("comments_count", "评论"),
        ("attitudes_count", "点赞"),
        ("favorites_count", "收藏"),
    ):
        value = status.get(key)
        if isinstance(value, (int, float)) and value > 0:
            stats[label] = int(value)
    publish_time = _weibo_created_at(status.get("created_at"))
    if publish_time:
        stats["发布时间"] = publish_time
    pics = _weibo_pics(status)
    summary_lines = [text[:500]]
    if len(text) > 500:
        summary_lines[-1] = text[:500] + "…"
    if len(pics) > 1:
        summary_lines.append(f"配图 {len(pics)} 张")
    retweet = status.get("retweeted_status") or {}
    if isinstance(retweet, dict) and retweet.get("text"):
        retweet_user = (retweet.get("user") or {}).get("screen_name") or ""
        retweet_text = _strip_html(retweet.get("text") or "")[:100]
        summary_lines.append(f"转发 @{retweet_user}：{retweet_text}")
    detail: dict = {"author": _weibo_author_detail(author)} if author else {}
    if pics:
        # 全量配图进 media（封面取首图，builder 保持首图位）。
        detail["images"] = pics
    video_meta = _weibo_video_meta(status)
    if video_meta:
        detail["video"] = video_meta
    return build_parsed_content(
        platform="weibo",
        item_id=str(status.get("id") or status.get("bid") or ""),
        item_kind="post",
        title=title,
        author_name=str(author.get("screen_name") or ""),
        summary="\n".join(summary_lines),
        cover_url=pics[0] if pics else "",
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="mblog",
        badge="微博" if not retweet else "微博·转发",
        detail=detail,
    )


def _weibo_status_card(
    bid: str,
    url: str,
    *,
    cookie_header: str = "",
    proxy: str = "",
) -> ParsedContent:
    """单条微博：三通道深解析。

    1. ``m.weibo.cn/statuses/show?id={bid}``（JSON，接受 bid）；
    2. ``weibo.com/ajax/statuses/show?id={bid}``（PC ajax，text_raw 纯文本）；
    3. ``m.weibo.cn/status/{bid}`` 页面 ``$render_data``（对 302 循环风控带重试）。
    """
    for api, data_key in ((_WEIBO_SHOW_API.format(bid=bid), "data"),):
        for attempt in range(2):
            try:
                payload = http_get_json(
                    api,
                    timeout=10,
                    cookie=cookie_header,
                    proxy=proxy,
                    referer="https://m.weibo.cn/",
                    user_agent=_WEIBO_MOBILE_UA,
                    extra_headers=_WEIBO_MOBILE_HEADERS,
                )
                data = (payload or {}).get(data_key) or {}
                if (payload or {}).get("ok") == 1 and isinstance(data, dict) and data.get("text"):
                    return _weibo_status_result(data, url)
            except Exception:  # noqa: BLE001, S110 - 风控窗口内失败短暂停后重试。
                pass
            if attempt == 0:
                time.sleep(1.0)
    for attempt in range(2):
        try:
            payload = http_get_json(
                _WEIBO_AJAX_API.format(bid=bid),
                timeout=10,
                cookie=cookie_header,
                proxy=proxy,
                referer="https://weibo.com/",
            )
            data = (payload or {}).get("data") or {}
            if (payload or {}).get("ok") == 1 and isinstance(data, dict) and data.get("text_raw"):
                return _weibo_status_result(data, url)
        except Exception:  # noqa: BLE001, S110 - ajax 失败走页面兜底。
            pass
        if attempt == 0:
            time.sleep(1.0)
    text = _weibo_get_text_with_retry(
        _WEIBO_STATUS_URL.format(bid=bid),
        cookie_header=cookie_header,
        proxy=proxy,
    )
    payload = _weibo_render_data(text)
    status = (payload or {}).get("status") or {}
    if not isinstance(status, dict) or (not status.get("text") and not status.get("raw_text")):
        raise ParseHttpError("weibo: render_data missing status")
    return _weibo_status_result(status, url)


def _weibo_user_card(
    uid: str,
    url: str,
    *,
    cookie_header: str = "",
    proxy: str = "",
) -> ParsedContent:
    """用户主页：m.weibo.cn getIndex 失败时回退 weibo.com PC ajax 深度卡片。

    getIndex 对脚本会话常回 ``ok=-100``（需完整浏览器指纹）；PC 端
    ``ajax/profile/info`` 只需要 weibo.com 登录 Cookie（SUB/WBPSESS）。
    """
    payload = None
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            payload = http_get_json(
                _WEIBO_USER_API.format(uid=uid),
                timeout=10,
                cookie=cookie_header,
                proxy=proxy,
                referer="https://m.weibo.cn/",
                user_agent=_WEIBO_MOBILE_UA,
                extra_headers=_WEIBO_MOBILE_HEADERS,
            )
            if payload and payload.get("ok") == 1:
                break
            last_exc = ParseHttpError(f"weibo: getIndex ok={payload.get('ok') if payload else None}")
        except ParseHttpError as exc:
            last_exc = exc
        payload = None
        if attempt < 1:
            time.sleep(1.5)
    user: dict = {}
    if payload is not None and payload.get("ok") == 1:
        user = (payload.get("data") or {}).get("userInfo") or {}
    if not user.get("screen_name"):
        # PC 端替代数据源（带 weibo.com 登录态）。
        try:
            pc_payload = http_get_json(
                _WEIBO_PC_PROFILE_API.format(uid=uid),
                timeout=12,
                cookie=cookie_header,
                proxy=proxy,
                referer=url or f"https://weibo.com/u/{uid}",
                extra_headers={"X-Requested-With": "XMLHttpRequest"},
            )
            if (pc_payload or {}).get("ok") == 1:
                user = (pc_payload.get("data") or {}).get("user") or {}
        except Exception:  # noqa: BLE001, S110 - PC 通道也失败交给上层降级。
            pass
    nickname = str(user.get("screen_name") or "").strip()
    if not nickname:
        raise last_exc or ParseHttpError("weibo: user profile unavailable")
    stats: dict = {}
    followers = _parse_cn_count(user.get("followers_count"))
    follows = _parse_cn_count(user.get("follow_count"))
    posts = _parse_cn_count(user.get("statuses_count"))
    if followers:
        stats["粉丝"] = followers
    if follows:
        stats["关注"] = follows
    if posts:
        stats["微博数"] = posts
    detail: dict = {"author": _weibo_author_detail(user)}
    if user.get("verified_reason"):
        detail["author"]["verified_reason"] = str(user.get("verified_reason"))
    summary = _truncate_keep_links(str(user.get("description") or "").strip(), 300)
    return build_parsed_content(
        platform="weibo",
        item_id=uid,
        item_kind="user",
        title=nickname,
        author_name=nickname,
        summary=summary,
        cover_url=str(user.get("avatar_hd") or user.get("profile_image_url") or ""),
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="profile",
        badge="微博主页",
        detail=detail,
    )


def _weibo_fallback_card(url: str) -> ParsedContent:
    """登录态/风控拦截时的诚实降级卡。"""
    return build_parsed_content(
        platform="weibo",
        item_id="",
        item_kind="post",
        title="微博链接",
        summary="（微博页面需要登录态且反爬严格，当前网络拿不到正文；"
        "已保留原链接，点开即可查看）",
        canonical_url=url,
        parse_depth="shallow",
        page_type="mblog",
    )


def _weibo_bid(url: str) -> str:
    """从 weibo.com/{uid}/{bid} 或 m.weibo.cn/status/{bid} 提取 bid。"""
    match = _BID_RE.search(url) or _M_STATUS_RE.search(url)
    if match:
        return match.group(1)
    # weibo.com/{uid}/{bid}?xxx 形态去掉查询串再取最后一段。
    path = urllib.parse.urlsplit(url).path.strip("/")
    segments = [seg for seg in path.split("/") if seg]
    if len(segments) >= 2 and segments[0].isdigit() and not segments[1].isdigit():
        return segments[1]
    return ""


def _weibo_uid(url: str) -> str:
    """从 weibo.com/u/{uid} 或 weibo.com/{uid} 提取数字 uid。"""
    match = re.search(r"weibo\.com/u/(\d{5,})", url)
    if match:
        return match.group(1)
    path = urllib.parse.urlsplit(url).path.strip("/")
    segments = [seg for seg in path.split("/") if seg]
    if len(segments) == 1 and segments[0].isdigit():
        return segments[0]
    return ""


def parse_weibo(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent:
    """微博入口：单条微博 / 用户主页分流，失败逐级降级。"""
    bid = _weibo_bid(url)
    if bid:
        try:
            return _weibo_status_card(bid, url, cookie_header=cookie_header, proxy=proxy)
        except Exception:  # noqa: BLE001, S110 - 深解析失败回退 og 浅卡。
            pass
        try:
            return _og_scrape(
                url,
                platform="weibo",
                item_kind="post",
                note="（浅层解析；微博正文需要登录态）",
                cookie_header=cookie_header,
                proxy=proxy,
            )
        except Exception:  # noqa: BLE001 - og 也失败给静态卡。
            return _weibo_fallback_card(url)
    uid = _weibo_uid(url)
    if uid:
        try:
            return _weibo_user_card(uid, url, cookie_header=cookie_header, proxy=proxy)
        except Exception:  # noqa: BLE001, S110 - 用户接口失败回退 og。
            pass
        try:
            return _og_scrape(
                url,
                platform="weibo",
                item_kind="user",
                note="（浅层解析；微博用户信息需要登录态）",
                cookie_header=cookie_header,
                proxy=proxy,
            )
        except Exception:  # noqa: BLE001
            return build_parsed_content(
                platform="weibo",
                item_id=uid,
                item_kind="user",
                title=f"微博用户 {uid}",
                summary="（微博用户主页需要登录态，已保留原链接）",
                canonical_url=url,
                parse_depth="shallow",
                page_type="profile",
            )
    # 其他形态（话题页/搜索页等）：og 尽力而为。
    try:
        return _og_scrape(
            url,
            platform="weibo",
            item_kind="page",
            cookie_header=cookie_header,
            proxy=proxy,
        )
    except Exception:  # noqa: BLE001
        return _weibo_fallback_card(url)

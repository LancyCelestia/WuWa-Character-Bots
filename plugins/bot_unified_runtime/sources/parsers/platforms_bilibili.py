"""B 站链接解析：视频 / 直播间 / 个人空间 / 收藏夹 / 动态(opus) / 番剧。

- 视频：官方 view API + 互动数据（播放/弹幕/投币/点赞/收藏/分享/评论/时长/
  分区）+ 作者信息（粉丝/关注/作品数，relation + navnum，尽力而为）。
- 直播间：getInfoByRoom（标题/封面/在线人数/分区/标签）+ 大航海列表（尽力）。
- 空间：card + navnum + relation（昵称/签名/粉丝/关注/视频数/专栏数）。
- 收藏夹：文件夹列表或某个文件夹的前若干条。
- 动态：polymer detail（正文/图片/视频/点赞评论转发）。
- 番剧：页面 og 元信息（标题/封面/简介）。
"""

from __future__ import annotations

import re
import urllib.parse

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
    resolve_short_link,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import _og_scrape
from plugins.bot_unified_runtime.sources.parsers.types import PlatformParse
from plugins.bot_unified_runtime.sources.parsers.wbi import (
    extract_mixin_key,
    sign_wbi,
)

_VIEW_API = "https://api.bilibili.com/x/web-interface/view"
_BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AVID_RE = re.compile(r"/av(\d+)", re.IGNORECASE)
_LIVE_RE = re.compile(r"live\.bilibili\.com/(\d+)")
_SPACE_RE = re.compile(r"space\.bilibili\.com/(\d+)")
_OPUS_RE = re.compile(r"/opus/(\d+)")
_FAVLIST_FID_RE = re.compile(r"[?&]fid=(\d+)")

_OPUS_DETAIL_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/detail"
_WBI_NAV_API = "https://api.bilibili.com/x/web-interface/nav"
_BANGUMI_SS_RE = re.compile(r"/ss(\d+)", re.IGNORECASE)
_BANGUMI_EP_RE = re.compile(r"/ep(\d+)", re.IGNORECASE)
_SERIES_SID_RE = re.compile(r"[?&]sid=(\d+)")
_SERIES_LIST_ML_RE = re.compile(r"/list/ml(\d+)")


def build_wbi_signed_url(
    url: str,
    params: dict,
    *,
    cookie_header: str = "",
    proxy: str = "",
) -> str:
    """构建 WBI 签名 URL。

    算法与 ``wbi.build_wbi_signed_url`` 一致，但刻意复用本模块的
    ``http_get_json`` 名称：平台模块按既有惯例被 monkeypatch，这样
    签名键请求也能被测试/运行时注入，避免产生真实网络请求。
    """
    if params.get("w_rid"):
        return f"{url}?{urllib.parse.urlencode(params)}"
    nav = http_get_json(
        _WBI_NAV_API,
        referer="https://www.bilibili.com/",
        cookie=cookie_header,
        proxy=proxy,
    )
    wbi_img = ((nav or {}).get("data") or {}).get("wbi_img") or {}
    img_url = str(wbi_img.get("img_url") or "")
    sub_url = str(wbi_img.get("sub_url") or "")
    if not img_url or not sub_url:
        raise ParseHttpError("bilibili nav missing wbi_img keys")
    signed = sign_wbi(dict(params), extract_mixin_key(img_url, sub_url))
    return f"{url}?{urllib.parse.urlencode(signed)}"


def _safe_int(value: object) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _format_count(value: int | None) -> str:
    if value is None:
        return "-"
    if value >= 100000000:
        return f"{value / 100000000:.1f}亿"
    if value >= 10000:
        return f"{value / 10000:.1f}万"
    return str(value)


# ---------- 视频 ----------

def _author_enrichment(mid: int, *, cookie_header: str = "") -> str:
    """作者粉丝/关注/作品数，尽力而为。"""
    lines: list[str] = []
    try:
        rel = http_get_json(
            f"https://api.bilibili.com/x/relation/stat?vmid={mid}",
            referer="https://www.bilibili.com/",
            cookie=cookie_header,
        )
        if rel.get("code") == 0:
            data = rel.get("data") or {}
            follower = _safe_int(data.get("follower"))
            following = _safe_int(data.get("following"))
            if follower is not None:
                lines.append(f"粉丝 {_format_count(follower)}")
            if following is not None:
                lines.append(f"关注 {_format_count(following)}")
    except Exception:  # noqa: BLE001
        pass
    try:
        nav = http_get_json(
            f"https://api.bilibili.com/x/space/navnum?mid={mid}",
            referer="https://www.bilibili.com/",
            cookie=cookie_header,
        )
        if nav.get("code") == 0:
            data = nav.get("data") or {}
            for key, label in (("video", "视频"), ("article", "专栏")):
                value = _safe_int(data.get(key))
                if value is not None:
                    lines.append(f"{label} {value}")
    except Exception:  # noqa: BLE001
        pass
    return " · ".join(lines)


def _lookup_video_by_id(video_id: str, kind: str, *, cookie_header: str = "") -> PlatformParse:
    import urllib.parse

    url = f"{_VIEW_API}?{urllib.parse.quote(kind)}={urllib.parse.quote(video_id)}"
    payload = http_get_json(
        url, referer="https://www.bilibili.com/", cookie=cookie_header
    )
    if payload.get("code") != 0:
        raise ParseHttpError(f"bilibili view api code={payload.get('code')}")
    data = payload.get("data") or {}
    owner = data.get("owner") or {}
    stat = data.get("stat") or {}
    pages = data.get("pages") or []
    desc = str(data.get("desc") or "").strip()
    if len(desc) > 500:
        desc = desc[:500] + "…"
    stats = {}
    for key, label in (
        ("view", "播放"),
        ("danmaku", "弹幕"),
        ("reply", "评论"),
        ("like", "点赞"),
        ("coin", "投币"),
        ("favorite", "收藏"),
        ("share", "分享"),
    ):
        value = _safe_int(stat.get(key))
        if value is not None:
            stats[label] = value
    duration = _safe_int(data.get("duration"))
    if duration is not None:
        stats["时长"] = f"{duration // 60}分{duration % 60}秒"
    pages_note = f"；分P {len(pages)}" if len(pages) > 1 else ""
    cid = (pages[0] or {}).get("cid") if pages else data.get("cid")
    summary_lines: list[str] = []
    if data.get("tname"):
        summary_lines.append(f"分区：{data.get('tname')}")
    summary_lines.append(f"时长：{stats.get('时长', '-')}{pages_note}")
    if data.get("copyright") == 1:
        summary_lines.append("类型：转载")
    elif data.get("copyright") == 2:
        summary_lines.append("类型：自制")
    if data.get("pubdate"):
        import datetime

        summary_lines.append(
            f"发布时间：{datetime.datetime.fromtimestamp(data['pubdate']).strftime('%Y-%m-%d')}"
        )
    if desc:
        summary_lines.append(f"简介：{desc}")
    if len(pages) > 1:
        summary_lines.append("分P列表：")
        for index, page in enumerate(pages[:8], start=1):
            part = str(page.get("part") or "").strip() or f"P{index}"
            page_duration = _safe_int(page.get("duration"))
            duration_text = (
                f" {page_duration // 60}分{page_duration % 60}秒"
                if page_duration is not None
                else ""
            )
            summary_lines.append(f"P{index}《{part}》{duration_text}")
    author_extra = ""
    owner_mid = _safe_int(owner.get("mid"))
    if owner_mid:
        author_extra = _author_enrichment(owner_mid, cookie_header=cookie_header)
    return PlatformParse(
        platform="bilibili",
        item_id=str(data.get("bvid") or video_id),
        item_kind="video",
        title=str(data.get("title") or "").strip(),
        author_name=f"{owner.get('name') or ''}"
        + (f"（{author_extra}）" if author_extra else ""),
        summary="\n".join(summary_lines),
        cover_url=str(data.get("pic") or ""),
        canonical_url=f"https://www.bilibili.com/video/{data.get('bvid') or video_id}"
        + (f"?p=1&cid={cid}" if False else ""),
        stats=stats,
        parse_depth="deep",
    )


# ---------- 直播间 ----------

def _parse_live(room_id: str, url: str, *, cookie_header: str = "") -> PlatformParse:
    payload = http_get_json(
        f"https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom?room_id={room_id}",
        referer="https://live.bilibili.com/",
        cookie=cookie_header,
    )
    if payload.get("code") != 0:
        raise ParseHttpError(f"bilibili live api code={payload.get('code')}")
    data = payload.get("data") or {}
    room = data.get("room_info") or {}
    anchor = data.get("anchor_info") or {}
    base = anchor.get("base_info") or {}
    stats: dict[str, object] = {}
    online = _safe_int(room.get("online"))
    if online is not None:
        stats["在线人数"] = _format_count(online)
        stats["人气"] = online
    if room.get("live_start_time"):
        import datetime

        stats["开播时间"] = datetime.datetime.fromtimestamp(
            int(room["live_start_time"])
        ).strftime("%Y-%m-%d %H:%M")
    status = "直播中" if room.get("live_status") == 1 else "未开播"
    summary_lines = [f"状态：{status}"]
    if room.get("parent_area_name") or room.get("area_name"):
        summary_lines.append(
            f"分区：{room.get('parent_area_name') or ''} / {room.get('area_name') or ''}"
        )
    if room.get("tags"):
        raw_tags = room.get("tags")
        if isinstance(raw_tags, str):
            tag_list = [tag for tag in re.split(r"[,，\s]+", raw_tags) if tag]
        else:
            tag_list = [str(tag) for tag in raw_tags]
        if tag_list:
            summary_lines.append("标签：" + "、".join(tag_list[:6]))
    if room.get("description"):
        desc = str(room["description"]).strip()[:300]
        summary_lines.append(f"简介：{desc}")
    uid = _safe_int(room.get("uid"))
    guards = ""
    if uid:
        try:
            guard = http_get_json(
                "https://api.live.bilibili.com/xlive/web-room/v1/guardTopList/get"
                f"?room_id={room_id}&ruid={uid}&page=1",
                referer="https://live.bilibili.com/",
                cookie=cookie_header,
            )
            gdata = (guard or {}).get("data") or {}
            top3 = gdata.get("top3") or []
            guard_bits = [
                f"{item.get('username', '')}（{['', '总督', '提督', '舰长'][_safe_int(item.get('guard_level')) or 0]}）"
                for item in top3
                if item.get("username")
            ]
            if guard_bits:
                guards = "大航海TOP：" + "、".join(guard_bits)
        except Exception:  # noqa: BLE001
            guards = ""
    if guards:
        summary_lines.append(guards)
    return PlatformParse(
        platform="bilibili",
        item_id=room_id,
        item_kind="live",
        title=str(room.get("title") or "直播间"),
        author_name=str(base.get("uname") or ""),
        summary="\n".join(summary_lines),
        cover_url=str(room.get("cover") or ""),
        canonical_url=f"https://live.bilibili.com/{room_id}",
        stats=stats,
        parse_depth="deep",
    )


# ---------- 个人空间 ----------

def _parse_space(mid: str, url: str, *, cookie_header: str = "") -> PlatformParse:
    payload = http_get_json(
        f"https://api.bilibili.com/x/web-interface/card?mid={mid}",
        referer="https://space.bilibili.com/",
        cookie=cookie_header,
    )
    if payload.get("code") != 0:
        raise ParseHttpError(f"bilibili space api code={payload.get('code')}")
    card = (payload.get("data") or {}).get("card") or {}
    stats = {}
    for key, label in (("fans", "粉丝"), ("attention", "关注"), ("like_num", "获赞")):
        value = _safe_int(card.get(key))
        if value is not None:
            stats[label] = value
    summary_lines = []
    if card.get("sign"):
        summary_lines.append(f"签名：{str(card.get('sign')).strip()[:200]}")
    nav_lines: list[str] = []
    try:
        nav = http_get_json(
            f"https://api.bilibili.com/x/space/navnum?mid={mid}",
            referer="https://space.bilibili.com/",
            cookie=cookie_header,
        )
        if nav.get("code") == 0:
            data = nav.get("data") or {}
            for key, label in (("video", "视频"), ("article", "专栏")):
                value = _safe_int(data.get(key))
                if value is not None:
                    nav_lines.append(f"{label} {value}")
            for key, label in (
                ("video", "投稿"),
                ("following", "关注"),
                ("follower", "粉丝"),
                ("article", "专栏"),
            ):
                value = _safe_int(data.get(key))
                if value is not None:
                    stats[label] = value
    except Exception:  # noqa: BLE001
        pass
    if nav_lines:
        summary_lines.append("作品：" + " · ".join(nav_lines))
    level = _safe_int(card.get("level"))
    if level is not None:
        summary_lines.append(f"等级：Lv{level}")
    return PlatformParse(
        platform="bilibili",
        item_id=mid,
        item_kind="user",
        title=str(card.get("name") or "个人空间"),
        summary="\n".join(summary_lines),
        cover_url=str(card.get("face") or ""),
        canonical_url=f"https://space.bilibili.com/{mid}",
        stats=stats,
        parse_depth="deep",
    )


# ---------- 收藏夹 ----------

def _parse_favlist(mid: str, url: str, *, cookie_header: str = "") -> PlatformParse:
    fid_match = _FAVLIST_FID_RE.search(url)
    if fid_match:
        fid = fid_match.group(1)
        folder = http_get_json(
            "https://api.bilibili.com/x/v3/fav/folder/info?media_id=" + fid,
            referer="https://space.bilibili.com/",
            cookie=cookie_header,
        )
        fdata = (folder or {}).get("data") or {}
        title = str(fdata.get("title") or f"收藏夹 {fid}")
        summary_lines = [f"收藏夹：{title}"]
        count = _safe_int(fdata.get("media_count"))
        if count is not None:
            summary_lines.append(f"共 {count} 条")
        items: list[str] = []
        try:
            res = http_get_json(
                f"https://api.bilibili.com/x/v3/fav/resource/list?media_id={fid}&pn=1&ps=20",
                referer="https://space.bilibili.com/",
                cookie=cookie_header,
            )
            medias = ((res or {}).get("data") or {}).get("medias") or []
            for media in medias[:20]:
                items.append(
                    f"- {media.get('title')}（{media.get('bvid') or media.get('id')}）"
                )
        except Exception:  # noqa: BLE001
            pass
        if items:
            summary_lines.append("内容预览（前20条）：\n" + "\n".join(items))
        return PlatformParse(
            platform="bilibili",
            item_id=fid,
            item_kind="collection",
            title=title,
            summary="\n".join(summary_lines),
            cover_url=str(fdata.get("cover") or ""),
            canonical_url=f"https://space.bilibili.com/{mid}/favlist?fid={fid}",
            stats={"数量": count} if count is not None else {},
            parse_depth="deep",
        )
    folders = http_get_json(
        f"https://api.bilibili.com/x/v3/fav/folder/created/list-all?up_mid={mid}",
        referer="https://space.bilibili.com/",
        cookie=cookie_header,
    )
    flist = ((folders or {}).get("data") or {}).get("list") or []
    lines = [f"收藏夹共 {len(flist)} 个："]
    for folder in flist[:20]:
        lines.append(
            f"- {folder.get('title')}（{_safe_int(folder.get('media_count')) or 0} 条，fid={folder.get('id')}）"
        )
    return PlatformParse(
        platform="bilibili",
        item_id=mid,
        item_kind="collection",
        title="收藏夹列表",
        summary="\n".join(lines),
        canonical_url=f"https://space.bilibili.com/{mid}/favlist",
        parse_depth="deep",
    )


# ---------- 动态（opus） ----------

def _parse_opus(opus_id: str, url: str, *, cookie_header: str = "") -> PlatformParse:
    params = {"timezone_offset": -480, "id": opus_id}
    try:
        request_url = build_wbi_signed_url(
            _OPUS_DETAIL_API,
            params,
            cookie_header=cookie_header,
            proxy="",
        )
    except ParseHttpError:
        # nav 不可用/注入环境异常时降级为未签名请求，保持只读优雅降级。
        request_url = f"{_OPUS_DETAIL_API}?{urllib.parse.urlencode(params)}"
    payload = http_get_json(
        request_url,
        referer="https://www.bilibili.com/",
        cookie=cookie_header,
    )
    if payload.get("code") != 0:
        raise ParseHttpError(f"bilibili dynamic api code={payload.get('code')}")
    item = (payload.get("data") or {}).get("item") or {}
    modules = item.get("modules") or {}
    author_mod: dict = {}
    dynamic_mod: dict = {}
    stat_mod: dict = {}
    if isinstance(modules, list):
        # 新版 opus/detail：modules 是列表，按 module_type 区分。
        for module in modules:
            if not isinstance(module, dict):
                continue
            module_type = str(module.get("module_type") or "")
            if module_type == "MODULE_TYPE_AUTHOR":
                author_mod = module.get("module_author") or {}
            elif module_type == "MODULE_TYPE_CONTENT":
                dynamic_mod = module.get("module_content") or {}
            elif module_type == "MODULE_TYPE_STAT":
                stat_mod = module.get("module_stat") or {}
    elif isinstance(modules, dict):
        # 旧版 polymer/detail：modules 是字典，保留兼容。
        author_mod = modules.get("module_author") or {}
        dynamic_mod = modules.get("module_dynamic") or {}
        stat_mod = modules.get("module_stat") or {}
    major = dynamic_mod.get("major") or {}
    desc = (dynamic_mod.get("desc") or {}).get("text") or ""
    if not desc:
        # 新版正文在 paragraphs 的文本节点里（兼容 word/words 两种键）。
        parts: list[str] = []
        for paragraph in (dynamic_mod.get("paragraphs") or []):
            if not isinstance(paragraph, dict):
                continue
            for node in ((paragraph.get("text") or {}).get("nodes") or []):
                if isinstance(node, dict):
                    raw_word = node.get("words") or node.get("word")
                    if isinstance(raw_word, dict):
                        raw_word = raw_word.get("words") or raw_word.get("word")
                    if isinstance(raw_word, str) and raw_word.strip():
                        parts.append(raw_word.strip())
        desc = "".join(parts)
    stats = {}
    for key, label in (
        ("like", "点赞"),
        ("comment", "评论"),
        ("forward", "转发"),
    ):
        raw_value = stat_mod.get(key)
        value = _safe_int(
            raw_value.get("count") if isinstance(raw_value, dict) else raw_value
        )
        if value is not None:
            stats[label] = value
    summary_lines: list[str] = []
    cover = ""
    # 新版图文：图片在 paragraphs 的 pic.pics 里（旧版 draw/opus 路径继续兼容）。
    if isinstance(dynamic_mod.get("paragraphs"), list):
        for paragraph in dynamic_mod.get("paragraphs") or []:
            if not isinstance(paragraph, dict):
                continue
            pic_block = paragraph.get("pic") or {}
            pics = pic_block.get("pics") or []
            if pics and "图片数量" not in str(summary_lines):
                summary_lines.append(f"图片数量：{len(pics)}")
                for index, pic in enumerate(pics[:4], start=1):
                    width, height = pic.get("width"), pic.get("height")
                    summary_lines.append(f"  图{index}：{width}×{height}")
                if len(pics) > 4:
                    summary_lines.append(f"  …共 {len(pics)} 张")
                if not cover and pics:
                    cover = str(pics[0].get("url") or "")
    archive = major.get("archive") or {}
    archive_bvid = ""
    if archive.get("title"):
        summary_lines.append(f"视频：{archive.get('title')}")
        summary_lines.append(f"简介：{str(archive.get('desc') or '').strip()[:200]}")
        archive_bvid = str(archive.get("bvid") or "")
        if archive_bvid:
            summary_lines.append(f"BV：{archive_bvid}（可发 /bot download 该视频链接下载）")
    draw = major.get("draw") or {}
    pics = draw.get("items") or []
    if pics:
        summary_lines.append(f"图片数量：{len(pics)}")
        for index, pic in enumerate(pics[:4], start=1):
            width, height = pic.get("width"), pic.get("height")
            size_kb = (pic.get("size") or 0) / 1024
            summary_lines.append(
                f"  图{index}：{width}×{height}"
                + (f"，约{size_kb:.0f}KB" if size_kb else "")
            )
        if len(pics) > 4:
            summary_lines.append(f"  …共 {len(pics)} 张")
    opus = major.get("opus") or {}
    if opus.get("title"):
        summary_lines.append(f"标题：{opus.get('title')}")
    if opus.get("pics"):
        summary_lines.append(f"图片数量：{len(opus.get('pics'))}")
    if pics:
        cover = str(pics[0].get("src") or "")
    elif (opus.get("pics") or []):
        cover = str(opus["pics"][0].get("url") or "")
    elif archive.get("cover"):
        cover = str(archive.get("cover"))
    topics = dynamic_mod.get("topic") or {}
    topic_names = [str(t.get("name")) for t in (topics.get("list") or [])]
    if topic_names:
        summary_lines.append("话题：" + "、".join(topic_names))
    if desc:
        summary_lines.append(f"正文：{str(desc).strip()[:300]}")
    return PlatformParse(
        platform="bilibili",
        item_id=opus_id,
        item_kind="dynamic",
        title=str(desc[:40] or "动态"),
        author_name=str((author_mod.get("name") or "")),
        summary="\n".join(summary_lines),
        cover_url=cover,
        canonical_url=(
            f"https://www.bilibili.com/video/{archive_bvid}"
            if archive_bvid
            else f"https://www.bilibili.com/opus/{opus_id}"
        ),
        stats=stats,
        parse_depth="deep",
    )


# ---------- 番剧 ----------

_BANGUMI_VIEW_API = "https://api.bilibili.com/pgc/view/web/season"
_BANGUMI_STAT_API = "https://api.bilibili.com/pgc/web/season/stat"


def _bangumi_og_fallback(page_url: str, *, cookie_header: str = "") -> PlatformParse:
    """保留原有 og 浅层解析行为（深度接口失败时兜底）。"""
    try:
        return _og_scrape(
            page_url,
            platform="bilibili",
            item_kind="bangumi",
            cookie_header=cookie_header,
        )
    except ParseHttpError:
        raise ParseHttpError(f"bilibili bangumi page unavailable: {page_url}")


def _parse_bangumi(page_url: str, *, cookie_header: str = "") -> PlatformParse:
    """番剧/电影深度解析：season view + stat，失败回退 og 浅层。"""
    ss_match = _BANGUMI_SS_RE.search(page_url)
    ep_match = _BANGUMI_EP_RE.search(page_url)
    if not ss_match and not ep_match:
        return _bangumi_og_fallback(page_url, cookie_header=cookie_header)
    try:
        if ss_match:
            view_url = f"{_BANGUMI_VIEW_API}?season_id={ss_match.group(1)}"
        else:
            view_url = f"{_BANGUMI_VIEW_API}?ep_id={ep_match.group(1)}"
        payload = http_get_json(
            view_url,
            referer="https://www.bilibili.com/",
            cookie=cookie_header,
        )
        if payload.get("code") != 0:
            raise ParseHttpError(f"bilibili bangumi view api code={payload.get('code')}")
        result = payload.get("result") or {}
        season_id = _safe_int(result.get("season_id"))
        if season_id is None and ss_match:
            season_id = _safe_int(ss_match.group(1))
        if season_id is None:
            raise ParseHttpError("bilibili bangumi missing season_id")
        stat_payload = http_get_json(
            f"{_BANGUMI_STAT_API}?season_id={season_id}",
            referer="https://www.bilibili.com/",
            cookie=cookie_header,
        )
        if stat_payload.get("code") != 0:
            raise ParseHttpError(f"bilibili bangumi stat api code={stat_payload.get('code')}")
        stat = stat_payload.get("result") or {}
        title = str(
            result.get("title")
            or result.get("season_title")
            or f"番剧 {season_id}"
        ).strip()
        type_name = str(result.get("type_name") or "").strip()
        areas = result.get("areas") or []
        area_names: list[str] = []
        for area in areas:
            area_name = area.get("name") if isinstance(area, dict) else str(area)
            if area_name:
                area_names.append(str(area_name))
        new_ep = result.get("new_ep") or {}
        episode_text = str(new_ep.get("desc") or "").strip()
        episodes = result.get("episodes") or []
        try:
            total_episodes = len(episodes)
        except TypeError:
            total_episodes = 0
        if not episode_text and total_episodes:
            episode_text = f"共 {total_episodes} 集"
        evaluate = str(result.get("evaluate") or "").strip()
        if len(evaluate) > 300:
            evaluate = evaluate[:300] + "…"
        summary_lines: list[str] = []
        if type_name:
            summary_lines.append(f"类型：{type_name}")
        if area_names:
            summary_lines.append(f"地区：{'、'.join(area_names)}")
        if episode_text:
            summary_lines.append(f"集数/更新：{episode_text}")
        if evaluate:
            summary_lines.append(f"简介：{evaluate}")
        stats: dict[str, object] = {}
        for key, label in (
            ("favorites", "追番"),
            ("views", "播放"),
            ("danmaku", "弹幕"),
            ("coins", "投币"),
        ):
            value = _safe_int(stat.get(key))
            if value is not None:
                stats[label] = value
        return PlatformParse(
            platform="bilibili",
            item_id=str(season_id),
            item_kind="bangumi",
            title=title,
            author_name="",
            summary="\n".join(summary_lines),
            cover_url=str(result.get("cover") or ""),
            canonical_url=page_url,
            stats=stats,
            parse_depth="deep",
        )
    except Exception:  # noqa: BLE001 - 深度接口失败回退 og 浅层解析。
        return _bangumi_og_fallback(page_url, cookie_header=cookie_header)


# ---------- 合集 / 全集列表 ----------

_SERIES_LIST_API = "https://api.bilibili.com/x/polymer/web-space/seasons_series_list"
_SERIES_ARCHIVES_API = "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list"


def _series_seasons(data: dict) -> list:
    items_lists = data.get("items_lists") or {}
    seasons = items_lists.get("seasons_list")
    if seasons is None:
        seasons = data.get("seasons_list")
    if seasons is None:
        seasons = data.get("list") or []
    return seasons if isinstance(seasons, list) else []


def _series_archives(data: dict) -> list:
    archives = data.get("archives")
    if archives is None:
        archives = data.get("list") or []
    return archives if isinstance(archives, list) else []


def _parse_series(url: str, *, cookie_header: str = "") -> PlatformParse:
    """B 站合集/全集列表：seasons_series_list → seasons_archives_list。"""
    mid_match = _SPACE_RE.search(url)
    mid = mid_match.group(1) if mid_match else ""
    sid_match = _SERIES_SID_RE.search(url) or _SERIES_LIST_ML_RE.search(url)
    sid = sid_match.group(1) if sid_match else ""
    if not mid and not sid:
        raise ParseHttpError(f"bilibili series missing mid/sid: {url}")
    season_id = sid
    title = ""
    if mid:
        payload = http_get_json(
            f"{_SERIES_LIST_API}?mid={mid}&page_num=1&page_size=30",
            referer="https://space.bilibili.com/",
            cookie=cookie_header,
        )
        if payload.get("code") != 0:
            raise ParseHttpError(f"bilibili series list api code={payload.get('code')}")
        seasons = _series_seasons(payload.get("data") or {})
        chosen = None
        if sid:
            for season in seasons:
                if str(_safe_int(season.get("season_id"))) == str(sid):
                    chosen = season
                    break
            if chosen is None and seasons:
                chosen = seasons[0]
        elif seasons:
            chosen = seasons[0]
        if chosen is not None:
            found_id = _safe_int(chosen.get("season_id"))
            season_id = str(
                found_id
                if found_id is not None
                else (chosen.get("season_id") or season_id)
            )
            title = str(chosen.get("name") or "").strip()
        elif not season_id:
            raise ParseHttpError("bilibili series list is empty")
    if not season_id:
        raise ParseHttpError("bilibili series has no season id")
    payload = http_get_json(
        f"{_SERIES_ARCHIVES_API}?mid={mid}&season_id={season_id}&page_num=1&page_size=30",
        referer="https://space.bilibili.com/",
        cookie=cookie_header,
    )
    if payload.get("code") != 0:
        raise ParseHttpError(f"bilibili series archives api code={payload.get('code')}")
    data = payload.get("data") or {}
    archives = _series_archives(data)
    page = data.get("page") or {}
    total = _safe_int(page.get("total"))
    if total is None:
        total = len(archives)
    summary_lines: list[str] = []
    for index, archive in enumerate(archives[:8], start=1):
        archive_title = str(archive.get("title") or "").strip()
        if archive_title:
            summary_lines.append(f"{index}. 《{archive_title}》")
    cover_url = ""
    if archives:
        cover_url = str(archives[0].get("cover") or archives[0].get("pic") or "")
    return PlatformParse(
        platform="bilibili",
        item_id=str(season_id),
        item_kind="collection",
        title=title or f"合集 {season_id}",
        summary="\n".join(summary_lines),
        cover_url=cover_url,
        canonical_url=url,
        stats={"视频数": total},
        parse_depth="deep",
    )


# ---------- 分发 ----------

def parse_bilibili(url: str, *, cookie_header: str = "") -> PlatformParse:
    """B 站链接分发：视频 / 直播间 / 空间 / 收藏夹 / 动态 / 番剧 / 合集。"""
    if "/channel/seriesdetail" in url or "/lists" in url or "/list/ml" in url:
        return _parse_series(url, cookie_header=cookie_header)
    live_match = _LIVE_RE.search(url)
    if live_match:
        return _parse_live(live_match.group(1), url, cookie_header=cookie_header)
    space_match = _SPACE_RE.search(url)
    if space_match:
        if "/favlist" in url:
            return _parse_favlist(space_match.group(1), url, cookie_header=cookie_header)
        return _parse_space(space_match.group(1), url, cookie_header=cookie_header)
    opus_match = _OPUS_RE.search(url)
    if opus_match:
        return _parse_opus(opus_match.group(1), url, cookie_header=cookie_header)
    if "/bangumi/" in url:
        return _parse_bangumi(url, cookie_header=cookie_header)
    final_url = url
    if "b23.tv" in url or "bili2233.cn" in url:
        final_url = resolve_short_link(url)
    match = _BVID_RE.search(final_url)
    if match:
        return _lookup_video_by_id(match.group(1), "bvid", cookie_header=cookie_header)
    match = _AVID_RE.search(final_url)
    if match:
        return _lookup_video_by_id(match.group(1), "aid", cookie_header=cookie_header)
    raise ParseHttpError(f"bilibili: no recognized content in {final_url}")

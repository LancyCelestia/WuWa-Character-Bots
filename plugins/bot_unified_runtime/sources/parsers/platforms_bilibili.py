"""B 站链接解析：视频 / 直播间 / 个人空间 / 收藏夹 / 动态(opus) / 番剧 /
专栏 / 课程(cheese) / 漫画 / 会员购 / 电竞赛事 / 公益 / 游戏中心 / 搜索。

- 视频：官方 view API + 互动数据（播放/弹幕/投币/点赞/收藏/分享/评论/时长/
  分区）+ 作者信息（粉丝/关注/作品数，relation + navnum，尽力而为）。
- 直播间：getInfoByRoom（标题/封面/在线人数/分区/标签）+ 大航海列表（尽力）。
- 空间：card + navnum + relation（昵称/签名/粉丝/关注/视频数/专栏数）。
- 收藏夹：文件夹列表或某个文件夹的前若干条。
- 动态：polymer detail（正文/图片/视频/点赞评论转发）。
- 番剧：season view + stat 深解析，失败回退 og 浅卡。
- 专栏：x/article/view（标题/作者/摘要/首图/互动数据）。
- 课程：pugv/view/web/season（课程标题/UP主/简介/集数/播放）。
- 漫画：twirp 接口有 TLS 风控（code=99），诚实降级浅卡。
- 会员购：show.bilibili.com getV2（项目名/场馆/票价/场次/开售状态）。
- 电竞：x/esports season/centre/info + component/contests/link（赛季/对阵）。
- 游戏中心：line1-h5-pc-api gameinfo（游戏名/简介/开发商/下载量）。
- 公益/搜索页：无公开内容接口，诚实降级关键词/入口浅卡。
"""

from __future__ import annotations

import html as _html
import os
import re
import urllib.parse

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
    resolve_short_link,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    _og_scrape,
    _truncate_keep_links,
)
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
_TDYNAMIC_RE = re.compile(r"(?:t\.bilibili\.com|/dynamic)/(\d+)")
_FAVLIST_FID_RE = re.compile(r"[?&]fid=(\d+)")

_OPUS_DETAIL_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/detail"
_WBI_NAV_API = "https://api.bilibili.com/x/web-interface/nav"
_BANGUMI_SS_RE = re.compile(r"/ss(\d+)", re.IGNORECASE)
_BANGUMI_EP_RE = re.compile(r"/ep(\d+)", re.IGNORECASE)
_SERIES_SID_RE = re.compile(r"[?&]sid=(\d+)")
_SERIES_LIST_ML_RE = re.compile(r"/list/ml(\d+)")

# ---------- 新增页面类型的 ID 提取 ----------
_ARTICLE_ID_RE = re.compile(r"/read/(?:cv|m)?(\d+)", re.IGNORECASE)
_CHEESE_SS_RE = re.compile(r"/cheese/play/ss(\d+)", re.IGNORECASE)
_CHEESE_EP_RE = re.compile(r"/cheese/play/ep(\d+)", re.IGNORECASE)
_MANGA_ID_RE = re.compile(r"manga\.bilibili\.com/detail/mc(\d+)", re.IGNORECASE)
_SHOW_ID_RE = re.compile(r"[?&]id=(\d+)")
_ESPORTS_GID_RE = re.compile(r"[?&]gid=(\d+)")
_ESPORTS_SID_RE = _SERIES_SID_RE
_ESPORTS_MID_RE = re.compile(r"[?&]mid=(\d+)")
_LOVE_UUID_RE = re.compile(r"[?&]uuid=([0-9A-Za-z]+)")
_BILIGAME_ID_RE = re.compile(r"biligame\.com/detail/\?[^\s]*[?&]?id=(\d+)")


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

def _author_enrichment(mid: int, *, cookie_header: str = "") -> tuple[str, dict, dict]:
    """作者粉丝/关注/视频/专栏/签名，尽力而为；返回 (文本, 结构化计数, 作者详情)。

    view 接口的 owner 只有 mid/name/face，签名必须额外调用户卡片接口
    （与空间解析同源：x/web-interface/card 的 data.card.sign）。
    """
    lines: list[str] = []
    counts: dict = {}
    author: dict = {"uuid": str(mid)}
    try:
        card = http_get_json(
            f"https://api.bilibili.com/x/web-interface/card?mid={mid}&photo=false",
            referer="https://www.bilibili.com/",
            cookie=cookie_header,
        )
        if card.get("code") == 0:
            card_data = (card.get("data") or {}).get("card") or {}
            sign = str(card_data.get("sign") or "").strip()
            if sign:
                author["signature"] = sign
    except Exception:  # noqa: BLE001, S110 - 用户卡片接口失败仅跳过签名。
        pass
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
                counts["粉丝"] = follower
                author["fans"] = follower
            if following is not None:
                lines.append(f"关注 {_format_count(following)}")
                counts["关注"] = following
    except Exception:  # noqa: BLE001, S110 - 关系数接口失败仅跳过该统计。
        pass
    try:
        nav = http_get_json(
            f"https://api.bilibili.com/x/space/navnum?mid={mid}",
            referer="https://www.bilibili.com/",
            cookie=cookie_header,
        )
        if nav.get("code") == 0:
            data = nav.get("data") or {}
            for key, label, stats_label in (("video", "视频", "视频数"), ("article", "专栏", "专栏数")):
                value = _safe_int(data.get(key))
                if value is not None:
                    lines.append(f"{label} {value}")
                    counts[stats_label] = value
        if "视频" in counts and author.get("video_count") is None:
            author["video_count"] = counts["视频"]
        if "专栏" in counts:
            author["post_count"] = counts["专栏"]
    except Exception:  # noqa: BLE001, S110 - 视频/专栏统计失败仅跳过。
        pass
    try:
        # 空间获赞数：upstat 需要 WBI 签名；风控/未登录下可能 code!=0，静默跳过。
        upstat_url = build_wbi_signed_url(
            "https://api.bilibili.com/x/space/upstat",
            {"mid": str(mid)},
            cookie_header=cookie_header,
        )
        upstat = http_get_json(
            upstat_url, referer="https://space.bilibili.com/", cookie=cookie_header
        )
        if upstat.get("code") == 0:
            updata = upstat.get("data") or {}
            likes = _safe_int(updata.get("likes") or (updata.get("archive") or {}).get("likes"))
            if likes is not None:
                lines.append(f"获赞 {_format_count(likes)}")
                counts["获赞"] = likes
                author["received_likes"] = likes
    except Exception:  # noqa: BLE001, S110 - 获赞统计失败仅跳过。
        pass
    return " · ".join(lines), counts, author


def _bilibili_ai_conclusion(
    *,
    bvid: str,
    aid: int | None,
    cid: int | None,
    up_mid: int | None,
    cookie_header: str,
) -> dict | None:
    """B 站官方 AI 视频总结（view/conclusion/get，WBI 签名）；失败返回 None。

    响应形态来自 parser-lite 的 ai_conclusion.json 样本：
    data.model_result.{summary, outline:[{title, part_outline?}]}。
    BOT_BILIBILI_AI_SUMMARY=0 可关闭。
    """
    if os.environ.get("BOT_BILIBILI_AI_SUMMARY", "1").strip().lower() in {"0", "false", "off"}:
        return None
    if not bvid or cid is None:
        return None
    params: dict[str, str] = {
        "bvid": bvid,
        "cid": str(cid),
        "web_location": "333.788",
    }
    if aid is not None:
        params["aid"] = str(aid)
    if up_mid is not None:
        params["up_mid"] = str(up_mid)
    url = build_wbi_signed_url(
        "https://api.bilibili.com/x/web-interface/view/conclusion/get",
        params,
        cookie_header=cookie_header,
    )
    payload = http_get_json(
        url, referer="https://www.bilibili.com/", cookie=cookie_header
    )
    if payload.get("code") != 0:
        return None
    model = ((payload.get("data") or {}).get("model_result")) or {}
    if not isinstance(model, dict):
        return None
    summary = str(model.get("summary") or "").strip()
    outline_titles: list[str] = []
    for node in model.get("outline") or []:
        if isinstance(node, dict):
            title = str(node.get("title") or "").strip()
            if title:
                outline_titles.append(title)
    if not summary and not outline_titles:
        return None
    return {"summary": summary, "outline": outline_titles[:6]}


def _lookup_video_by_id(video_id: str, kind: str, *, cookie_header: str = "") -> ParsedContent:
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
    stats: dict[str, object] = {}
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
        # Human-readable duration is retained for the duration pill/summary.
        # Internal transport keys stay out of public stats.
        stats["时长"] = f"{duration // 60}分{duration % 60}秒"
    pubdate = _safe_int(data.get("pubdate"))
    aid = _safe_int(data.get("aid"))
    pages_note = f"；分P {len(pages)}" if len(pages) > 1 else ""
    cid = (pages[0] or {}).get("cid") if pages else data.get("cid")
    summary_lines: list[str] = []
    if data.get("tname"):
        summary_lines.append(f"分区：{data.get('tname')}")
    summary_lines.append(f"时长：{stats.get('时长', '-')}{pages_note}")
    if data.get("pubdate"):
        import datetime

        summary_lines.append(
            f"发布时间：{datetime.datetime.fromtimestamp(data['pubdate']).strftime('%Y-%m-%d %H:%M:%S')}"  # noqa: DTZ006 - 本地时间有意 naive。
        )
    if desc:
        summary_lines.append(f"简介：{desc}")
    ai_conclusion: dict | None = None
    if cid is not None:
        try:
            ai_conclusion = _bilibili_ai_conclusion(
                bvid=str(data.get("bvid") or video_id),
                aid=aid,
                cid=_safe_int(cid),
                up_mid=_safe_int(owner.get("mid")),
                cookie_header=cookie_header,
            )
        except Exception:  # noqa: BLE001 - AI 总结失败静默跳过，不影响解析主链路。
            ai_conclusion = None
    if ai_conclusion:
        summary_lines.append("")  # AI 内容与视频简介之间空一行，视觉分隔。
        ai_summary = str(ai_conclusion.get("summary") or "").strip()
        if ai_summary:
            summary_lines.append(f"AI总结：{ai_summary}")
        outline_titles = [str(t) for t in ai_conclusion.get("outline") or []]
        if outline_titles:
            summary_lines.append("AI大纲：" + " / ".join(outline_titles[:4]))
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
    author_detail: dict = {}
    owner_mid = _safe_int(owner.get("mid"))
    if owner_mid:
        # 粉丝/关注/视频/专栏/获赞归作者栏（Creator 字段），不再混入视频数据栏。
        _, _, author_detail = _author_enrichment(owner_mid, cookie_header=cookie_header)
    video_author: dict = {}
    if owner.get("name"):
        video_author["name"] = str(owner["name"])
    if owner.get("face"):
        video_author["avatar"] = str(owner["face"])
    for key in ("sign", "signature"):
        if owner.get(key):
            video_author["signature"] = str(owner[key])
            break
    card = data.get("card") or {}
    if isinstance(card, dict):
        for dst_key, src_keys in (
            ("name", ("name",)),
            ("avatar", ("face", "avatar")),
            ("signature", ("sign", "signature")),
            ("fans", ("fans", "follower", "fans_count")),
            ("signature", ("sign", "signature")),
        ):
            for src_key in src_keys:
                value = card.get(src_key)
                if value not in (None, ""):
                    video_author[dst_key] = value
                    break
    official_verify = data.get("official_verify") or card.get("official_verify")
    if isinstance(official_verify, dict):
        verify_desc = str(official_verify.get("desc") or "").strip()
        verify_type = _safe_int(official_verify.get("type"))
        if verify_desc:
            video_author["official_badge"] = verify_desc
        elif verify_type is not None and verify_type >= 0:
            # The API did not supply the exact certification text.  State the
            # verified platform without inventing a creator/company identity.
            video_author["official_badge"] = "哔哩哔哩已认证博主"
    vip = data.get("vip") or card.get("vip")
    if isinstance(vip, dict) and _safe_int(vip.get("status")) == 1:
        video_author["official_title"] = "大会员"
    if author_detail:
        video_author.update(author_detail)
    video_meta: dict[str, object] = {"bvid": str(data.get("bvid") or video_id)}
    if aid is not None:
        video_meta["aid"] = aid
    if duration is not None:
        video_meta["duration"] = duration
    if pubdate is not None:
        video_meta["pubdate"] = pubdate
    video_detail: dict = {"video": video_meta}
    if ai_conclusion:
        video_detail["ai_conclusion"] = ai_conclusion
    if video_author:
        video_detail["author"] = video_author
    # 评论区渲染（批次 B）：热门评论前 3 条进 detail；失败静默跳过。
    if aid is not None:
        try:
            reply_payload = http_get_json(
                "https://api.bilibili.com/x/v2/reply?"
                + urllib.parse.urlencode({"type": 1, "oid": aid, "ps": 3, "sort": 1}),
                referer="https://www.bilibili.com/",
                cookie=cookie_header,
                timeout=6,
            )
            replies = ((reply_payload.get("data") or {}).get("replies")) or []
            hot_comments = []
            for reply in replies[:3]:
                member = reply.get("member") or {}
                content = (reply.get("content") or {}).get("message") or ""
                like = (reply.get("like") or 0)
                if content:
                    hot_comments.append(
                        {
                            "author": str(member.get("uname") or "").strip(),
                            "text": str(content).strip()[:120],
                            "likes": like,
                        }
                    )
            if hot_comments:
                video_detail["hot_comments"] = hot_comments
                summary_lines.append("")
                summary_lines.append("热门评论：")
                for comment in hot_comments:
                    author = comment.get("author") or "匿名"
                    text = str(comment.get("text") or "")[:80]
                    likes = comment.get("likes") or 0
                    summary_lines.append(f"· {author}：{text}（赞 {likes}）")
        except Exception:  # noqa: BLE001, S110 - 评论拉取失败不影响解析。
            pass
    if len(pages) > 1:
        # 分 P 列表进 detail：卡片「分P列表」区块与摘要行共用同一份数据。
        video_detail["episodes"] = [
            {
                "index": index,
                "title": str(page.get("part") or "").strip() or f"P{index}",
                "duration_seconds": _safe_int(page.get("duration")),
            }
            for index, page in enumerate(pages, start=1)
        ]
    return build_parsed_content(
        platform="bilibili",
        item_id=str(data.get("bvid") or video_id),
        item_kind="video",
        title=str(data.get("title") or "").strip(),
        author_name=str(owner.get("name") or ""),
        summary="\n".join(summary_lines),
        cover_url=str(data.get("pic") or ""),
        canonical_url=f"https://www.bilibili.com/video/{data.get('bvid') or video_id}"
        + (f"?p=1&cid={cid}" if False else ""),
        stats=stats,
        parse_depth="deep",
        detail=video_detail,
    )


# ---------- 直播间 ----------

def _parse_live(room_id: str, url: str, *, cookie_header: str = "") -> ParsedContent:
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

        stats["开播时间"] = datetime.datetime.fromtimestamp(  # noqa: DTZ006 - 本地时间有意 naive。
            int(room["live_start_time"])
        ).strftime("%Y-%m-%d %H:%M")
    status = "直播中" if room.get("live_status") == 1 else "未开播"
    summary_lines = [f"状态：{status}"]
    if room.get("parent_area_name") or room.get("area_name"):
        summary_lines.append(
            f"分区：{room.get('parent_area_name') or ''} / {room.get('area_name') or ''}"
        )
    if room.get("tags"):
        raw_tags = room.get("tags") or []
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
    live_detail: dict = {}
    if room.get("area_name"):
        live_detail["area"] = str(room["area_name"])
    if room.get("parent_area_name"):
        live_detail["parent_area"] = str(room["parent_area_name"])
    raw_live_tags = room.get("tags")
    if raw_live_tags:
        if isinstance(raw_live_tags, str):
            live_tags = [tag for tag in re.split(r"[,，\s]+", raw_live_tags) if tag]
        elif isinstance(raw_live_tags, list):
            live_tags = [str(tag) for tag in raw_live_tags if tag not in (None, "")]
        else:
            live_tags = [str(raw_live_tags)]
        if live_tags:
            live_detail["tags"] = live_tags
    if room.get("cover"):
        live_detail["cover"] = str(room["cover"])
    if room.get("keyframe"):
        live_detail["keyframe"] = str(room["keyframe"])
    if room.get("title"):
        live_detail["title"] = str(room["title"])
    live_start = _safe_int(room.get("live_start_time"))
    if live_start is not None:
        live_detail["start_time"] = live_start
    if room.get("description"):
        live_detail["intro"] = str(room["description"]).strip()
    # 关键帧等字段由 Room/get_info 尽力补充，失败不影响主解析。
    try:
        extra_payload = http_get_json(
            f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}",
            referer="https://live.bilibili.com/",
            cookie=cookie_header,
        )
        extra_data = (extra_payload or {}).get("data") or {}
        extra_room = extra_data.get("room_info") or extra_data
        for src_key, dst_key in (
            ("area_name", "area"),
            ("parent_area_name", "parent_area"),
            ("cover", "cover"),
            ("keyframe", "keyframe"),
            ("title", "title"),
            ("description", "intro"),
        ):
            if dst_key not in live_detail:
                value = extra_room.get(src_key)
                if value not in (None, ""):
                    live_detail[dst_key] = (
                        str(value).strip() if src_key == "description" else str(value)
                    )
        if "tags" not in live_detail:
            extra_tags = extra_room.get("tags")
            if extra_tags:
                if isinstance(extra_tags, str):
                    parsed_tags = [tag for tag in re.split(r"[,，\s]+", extra_tags) if tag]
                elif isinstance(extra_tags, list):
                    parsed_tags = [
                        str(tag) for tag in extra_tags if tag not in (None, "")
                    ]
                else:
                    parsed_tags = [str(extra_tags)]
                if parsed_tags:
                    live_detail["tags"] = parsed_tags
        if "start_time" not in live_detail:
            extra_start = _safe_int(extra_room.get("live_start_time"))
            if extra_start is not None:
                live_detail["start_time"] = extra_start
    except Exception:  # noqa: BLE001, S110 - 补充详情失败保留基础信息。
        pass
    return build_parsed_content(
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
        detail={"live": live_detail} if live_detail else {},
    )


# ---------- 个人空间 ----------

def _parse_space(mid: str, url: str, *, cookie_header: str = "") -> ParsedContent:
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
        summary_lines.append(f"签名：{_truncate_keep_links(str(card['sign']).strip(), 200)}")
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
                ("video", "视频数"),
                ("following", "关注"),
                ("follower", "粉丝"),
                ("article", "专栏数"),
            ):
                value = _safe_int(data.get(key))
                if value is not None:
                    stats[label] = value
    except Exception:  # noqa: BLE001, S110 - 作品统计失败仅跳过。
        pass
    if nav_lines:
        summary_lines.append("作品：" + " · ".join(nav_lines))
    level = _safe_int(card.get("level"))
    if level is not None:
        summary_lines.append(f"等级：Lv{level}")
    author_detail: dict = {}
    if card.get("mid"):
        author_detail["uuid"] = str(card["mid"])
    if card.get("name"):
        author_detail["name"] = str(card["name"])
    if card.get("face"):
        author_detail["avatar"] = str(card["face"])
    if card.get("sign"):
        author_detail["signature"] = _truncate_keep_links(str(card["sign"]).strip(), 200)
    if card.get("fans"):
        author_detail["fans"] = _safe_int(card["fans"])
    if card.get("attention"):
        author_detail["following"] = _safe_int(card["attention"])
    official_verify = card.get("official_verify")
    if isinstance(official_verify, dict):
        verify_desc = str(official_verify.get("desc") or "").strip()
        if verify_desc:
            author_detail["verified_reason"] = verify_desc
    return build_parsed_content(
        platform="bilibili",
        item_id=str(card.get("mid") or mid),
        item_kind="user",
        title=str(card.get("name") or "个人空间"),
        author_name=str(card.get("name") or ""),
        summary="\n".join(summary_lines),
        cover_url=str(card.get("face") or ""),
        canonical_url=f"https://space.bilibili.com/{mid}",
        stats=stats,
        parse_depth="deep",
        detail={"author": author_detail} if author_detail else {},
    )


# ---------- 收藏夹 ----------

def _parse_favlist(mid: str, url: str, *, cookie_header: str = "") -> ParsedContent:
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
        except Exception:  # noqa: BLE001, S110 - 收藏夹预览失败仅跳过。
            pass
        if items:
            summary_lines.append("内容预览（前20条）：\n" + "\n".join(items))
        return build_parsed_content(
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
    return build_parsed_content(
        platform="bilibili",
        item_id=mid,
        item_kind="collection",
        title="收藏夹列表",
        summary="\n".join(lines),
        canonical_url=f"https://space.bilibili.com/{mid}/favlist",
        parse_depth="deep",
    )


# ---------- 动态（opus） ----------

def _parse_opus(opus_id: str, url: str, *, cookie_header: str = "") -> ParsedContent:
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
    image_urls: list[str] = []
    # 新版图文：图片在 paragraphs 的 pic.pics 里（旧版 draw/opus 路径继续兼容）。
    if isinstance(dynamic_mod.get("paragraphs"), list):
        for paragraph in dynamic_mod.get("paragraphs") or []:
            if not isinstance(paragraph, dict):
                continue
            pic_block = paragraph.get("pic") or {}
            pics = pic_block.get("pics") or []
            for pic in pics:
                pic_url = str((pic or {}).get("url") or "")
                if pic_url:
                    image_urls.append(pic_url)
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
    for pic in pics:
        pic_src = str((pic or {}).get("src") or "")
        if pic_src:
            image_urls.append(pic_src)
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
        summary_lines.append(f"图片数量：{len(opus.get('pics') or [])}")
        for pic in opus.get("pics") or []:
            pic_url = str((pic or {}).get("url") or "")
            if pic_url:
                image_urls.append(pic_url)
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
    detail_author: dict = {}
    for key in ("name", "avatar", "signature", "fans"):
        value = author_mod.get(key)
        if value not in (None, ""):
            detail_author[key] = value
    detail: dict = {}
    if image_urls:
        detail["images"] = image_urls
    if detail_author:
        detail["author"] = detail_author
    return build_parsed_content(
        platform="bilibili",
        item_id=opus_id,
        item_kind="dynamic",
        title=str(desc[:40] or "动态"),
        author_name=str(author_mod.get("name") or ""),
        summary="\n".join(summary_lines),
        cover_url=cover,
        canonical_url=(
            f"https://www.bilibili.com/video/{archive_bvid}"
            if archive_bvid
            else f"https://www.bilibili.com/opus/{opus_id}"
        ),
        stats=stats,
        parse_depth="deep",
        detail=detail,
    )


# ---------- 番剧 ----------

_BANGUMI_VIEW_API = "https://api.bilibili.com/pgc/view/web/season"
_BANGUMI_STAT_API = "https://api.bilibili.com/pgc/web/season/stat"
_SEASON_TYPE_MAP: dict[int, tuple[str, str]] = {
    1: ("bangumi", "番剧"),
    2: ("movie", "电影"),
    3: ("documentary", "纪录片"),
    4: ("guochuang", "国创"),
    5: ("tv", "电视剧"),
    7: ("variety", "综艺"),
}


def _bangumi_og_fallback(page_url: str, *, cookie_header: str = "") -> ParsedContent:
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


def _parse_bangumi(page_url: str, *, cookie_header: str = "") -> ParsedContent:
    """番剧/电影深度解析：season view + stat，失败回退 og 浅层。"""
    ss_match = _BANGUMI_SS_RE.search(page_url)
    ep_match = _BANGUMI_EP_RE.search(page_url)
    if not ss_match and not ep_match:
        return _bangumi_og_fallback(page_url, cookie_header=cookie_header)
    try:
        if ss_match is not None:
            view_url = f"{_BANGUMI_VIEW_API}?season_id={ss_match.group(1)}"
        elif ep_match is not None:
            view_url = f"{_BANGUMI_VIEW_API}?ep_id={ep_match.group(1)}"
        else:
            return _bangumi_og_fallback(page_url, cookie_header=cookie_header)
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
        season_type = _safe_int(result.get("season_type"))
        if season_type is None:
            season_type = _safe_int(result.get("type"))
        page_type, badge = _SEASON_TYPE_MAP.get(season_type or 0, ("", ""))
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
        detail: dict = {}
        detail_episodes: list[dict] = []
        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            episode_item: dict = {}
            index_value = episode.get("index")
            if index_value is None:
                index_value = episode.get("ep_index")
            if index_value is not None:
                episode_item["index"] = index_value
            title_value = str(
                episode.get("long_title") or episode.get("title") or ""
            ).strip()
            if title_value:
                episode_item["title"] = title_value
            duration_value = _safe_int(episode.get("duration"))
            if duration_value is not None:
                episode_item["duration_seconds"] = (
                    duration_value // 1000 if duration_value > 3600 else duration_value
                )
            cover_value = str(episode.get("cover") or "")
            if cover_value:
                episode_item["cover"] = cover_value
            if episode_item:
                detail_episodes.append(episode_item)
        if detail_episodes:
            detail["episodes"] = detail_episodes
        related: list[dict] = []
        for season in result.get("seasons") or []:
            if not isinstance(season, dict):
                continue
            season_item_id = _safe_int(season.get("season_id"))
            if season_item_id is None:
                continue
            related.append(
                {
                    "title": str(
                        season.get("title") or season.get("season_title") or ""
                    ).strip(),
                    "url": f"https://www.bilibili.com/bangumi/play/ss{season_item_id}",
                }
            )
        if related:
            detail["related"] = related
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
        follow = _safe_int(stat.get("follow"))
        if follow is not None:
            stats["追番"] = follow
        return build_parsed_content(
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
            page_type=page_type,
            badge=badge,
            detail=detail,
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


def _parse_series(url: str, *, cookie_header: str = "") -> ParsedContent:
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
    return build_parsed_content(
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


# ---------- 专栏 ----------

_ARTICLE_API = "https://api.bilibili.com/x/article/view"

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _fmt_ts(value: object, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """秒时间戳 → 本地时间字符串；非法输入返回空串。"""
    num = _safe_int(value)
    if not num:
        return ""
    if num > 10**12:
        num //= 1000
    if num < 10**9:
        return ""
    import datetime

    return datetime.datetime.fromtimestamp(num).strftime(fmt)  # noqa: DTZ006 - 本地时间有意 naive。


def _parse_article(article_id: str, url: str, *, cookie_header: str = "") -> ParsedContent:
    """专栏文章：x/article/view（标题/作者/摘要/首图/点赞收藏等）。"""
    payload = http_get_json(
        f"{_ARTICLE_API}?id={article_id}",
        referer="https://www.bilibili.com/read/",
        cookie=cookie_header,
    )
    if payload.get("code") != 0:
        raise ParseHttpError(f"bilibili article api code={payload.get('code')}")
    data = payload.get("data") or {}
    title = str(data.get("title") or "").strip()
    if not title:
        raise ParseHttpError("bilibili article missing title")
    author = data.get("author") or {}
    stat = data.get("stats") or {}
    stats: dict[str, object] = {}
    for key, label in (
        ("view", "阅读"),
        ("like", "点赞"),
        ("favorite", "收藏"),
        ("reply", "评论"),
        ("coin", "投币"),
        ("share", "分享"),
    ):
        value = _safe_int(stat.get(key))
        if value is not None:
            stats[label] = value
    publish_time = _fmt_ts(data.get("publish_time") or data.get("ctime"))
    if publish_time:
        stats["发布时间"] = publish_time
    summary = str(data.get("summary") or "").strip()
    if len(summary) > 300:
        summary = summary[:300] + "…"
    cover = str(data.get("banner_url") or "")
    if not cover:
        image_urls = data.get("image_urls") or []
        if image_urls:
            cover = str(image_urls[0])
    categories = [
        str(c.get("name") or "")
        for c in (data.get("categories") or [])
        if isinstance(c, dict) and c.get("name")
    ]
    author_detail: dict = {}
    if author.get("mid"):
        author_detail["uuid"] = str(author["mid"])
    if author.get("name"):
        author_detail["name"] = str(author["name"])
    if author.get("face"):
        author_detail["avatar"] = str(author["face"])
    detail: dict = {"article": {"id": str(data.get("id") or article_id)}}
    if author_detail:
        detail["author"] = author_detail
    summary_lines: list[str] = []
    if categories:
        summary_lines.append("分区：" + "、".join(categories))
    if publish_time:
        summary_lines.append(f"发布时间：{publish_time}")
    if summary:
        summary_lines.append(f"摘要：{summary}")
    return build_parsed_content(
        platform="bilibili",
        item_id=str(data.get("id") or article_id),
        item_kind="article",
        title=title,
        author_name=str(author.get("name") or ""),
        summary="\n".join(summary_lines),
        cover_url=cover,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="article",
        badge="专栏",
        detail=detail,
    )


# ---------- 付费课程（cheese） ----------

_CHEESE_API = "https://api.bilibili.com/pugv/view/web/season"


def _parse_cheese(season_id: str, url: str, *, cookie_header: str = "") -> ParsedContent:
    """付费课程：pugv season（课程标题/UP主/简介/集数/播放/完结状态）。"""
    payload = http_get_json(
        f"{_CHEESE_API}?season_id={season_id}",
        referer="https://www.bilibili.com/cheese/",
        cookie=cookie_header,
    )
    if payload.get("code") != 0:
        raise ParseHttpError(f"bilibili cheese api code={payload.get('code')}")
    data = payload.get("data") or {}
    title = str(data.get("title") or "").strip()
    if not title:
        raise ParseHttpError("bilibili cheese missing title")
    up = data.get("up_info") or {}
    stat = data.get("stat") or {}
    stats: dict[str, object] = {}
    play = _safe_int(stat.get("play"))
    if play is not None:
        stats["播放"] = play
    ep_count = _safe_int(data.get("ep_count"))
    if ep_count is not None:
        stats["集数"] = ep_count
    release_status = str(data.get("release_status") or "").strip()
    brief = data.get("brief") or {}
    brief_text = ""
    if isinstance(brief, dict):
        brief_text = _HTML_TAG_RE.sub("", str(brief.get("content") or "")).strip()
    summary_lines: list[str] = []
    if up.get("uname"):
        summary_lines.append(f"UP主：{up['uname']}")
    if release_status:
        summary_lines.append(f"状态：{release_status}")
    if ep_count is not None:
        summary_lines.append(f"共 {ep_count} 集")
    episodes = data.get("episodes") or []
    if isinstance(episodes, list):
        preview_bits = []
        for index, episode in enumerate(episodes[:5], start=1):
            ep_title = str((episode or {}).get("title") or "").strip()
            if ep_title:
                preview_bits.append(f"P{index}《{ep_title}》")
        if preview_bits:
            summary_lines.append("目录：" + "、".join(preview_bits) + ("…" if len(episodes) > 5 else ""))
    if brief_text:
        if len(brief_text) > 260:
            brief_text = brief_text[:260] + "…"
        summary_lines.append(f"简介：{brief_text}")
    author_detail: dict = {}
    if up.get("mid"):
        author_detail["uuid"] = str(up["mid"])
    if up.get("avatar"):
        author_detail["avatar"] = str(up["avatar"])
    follower = _safe_int(up.get("follower"))
    if follower is not None:
        author_detail["fans"] = follower
        stats["作者粉丝"] = follower
    detail: dict = {"cheese": {"season_id": season_id, "release_status": release_status}}
    if author_detail:
        detail["author"] = author_detail
    return build_parsed_content(
        platform="bilibili",
        item_id=season_id,
        item_kind="cheese",
        title=title,
        author_name=str(up.get("uname") or ""),
        summary="\n".join(summary_lines),
        cover_url=str(data.get("cover") or ""),
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="cheese",
        badge="课程",
        detail=detail,
    )


# ---------- 漫画 ----------

def _parse_manga_card(manga_id: str, url: str) -> ParsedContent:
    """漫画详情：twirp 接口对非浏览器 TLS 指纹风控（code=99），诚实降级浅卡。

    实测 POST manga.bilibili.com/twirp/comic.v1.Comic/ComicDetail 无论带不带
    Cookie / 浏览器头均返回 {"code":99,"msg":"请求失败,请稍后重试。"}，页面
    HTML 也是无 SSR 的空壳（标题为站点通用文案），故只保留入口链接。
    """
    return build_parsed_content(
        platform="bilibili",
        item_id=f"mc{manga_id}",
        item_kind="manga",
        title=f"哔哩哔哩漫画 mc{manga_id}",
        summary="（漫画详情接口有反爬风控，机器人拿不到标题/封面；已保留原链接，"
        "点开即可查看）",
        canonical_url=url,
        parse_depth="shallow",
        page_type="manga",
        badge="漫画",
    )


# ---------- 会员购 ----------

_SHOW_GETV2_API = "https://show.bilibili.com/api/ticket/project/getV2"


def _strip_html_text(value: object, limit: int = 200) -> str:
    text = _html.unescape(_HTML_TAG_RE.sub("", str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def parse_bilibili_show(url: str, *, cookie_header: str = "") -> ParsedContent:
    """会员购项目：getV2（项目名/场馆/时间/票价/开售状态），可独立注册。"""
    id_match = _SHOW_ID_RE.search(url)
    if not id_match:
        raise ParseHttpError(f"bilibili show missing project id: {url}")
    project_id = id_match.group(1)
    payload = http_get_json(
        f"{_SHOW_GETV2_API}?id={project_id}&project_id={project_id}",
        referer=f"https://show.bilibili.com/platform/detail.html?id={project_id}",
        cookie=cookie_header,
    )
    if isinstance(payload.get("code"), int) and payload["code"] != 0:
        raise ParseHttpError(f"bilibili show api code={payload.get('code')}")
    data = payload.get("data") or {}
    name = str(data.get("name") or "").strip()
    if not name:
        raise ParseHttpError("bilibili show missing project name")
    venue = data.get("venue_info") or {}
    stats: dict[str, object] = {}
    price_low = _safe_int(data.get("price_low"))
    if price_low:
        stats["票价"] = f"¥{price_low / 100:g}起"
    start_text = _fmt_ts(data.get("start_time"), "%Y-%m-%d %H:%M")
    if start_text:
        stats["开始时间"] = start_text
    screens = data.get("screen_list") or []
    sale_flags: list[str] = []
    for screen in screens:
        if not isinstance(screen, dict):
            continue
        flag = (screen.get("saleFlag") or {}).get("display_name")
        if flag and str(flag) not in sale_flags:
            sale_flags.append(str(flag))
    summary_lines: list[str] = []
    project_label = str(data.get("project_label") or "").strip()
    if project_label:
        summary_lines.append(f"档期：{project_label}")
    venue_name = str(venue.get("name") or "").strip()
    if venue_name:
        address = str(venue.get("address_detail") or "").strip()
        summary_lines.append(f"场馆：{venue_name}" + (f"（{address}）" if address else ""))
    if sale_flags:
        summary_lines.append("售票状态：" + "、".join(sale_flags[:4]))
    performance_desc = data.get("performance_desc") or {}
    desc_bits: list[str] = []
    for module in (performance_desc.get("list") or [])[:3]:
        if not isinstance(module, dict):
            continue
        module_name = str(module.get("module_name") or "").strip()
        text = _strip_html_text(module.get("details"), 160)
        if text:
            desc_bits.append(f"{module_name}：{text}" if module_name else text)
    if desc_bits:
        summary_lines.append("\n".join(desc_bits[:2]))
    cover = str(data.get("cover") or "")
    if cover.startswith("//"):
        cover = f"https:{cover}"
    banner = str(data.get("banner") or "")
    detail: dict = {
        "show": {
            "project_id": project_id,
            "price_low": price_low,
            "start_time": _safe_int(data.get("start_time")),
            "end_time": _safe_int(data.get("end_time")),
            "venue": venue_name,
            "address": str(venue.get("address_detail") or ""),
            "sale_flags": sale_flags,
            "banner": banner,
        }
    }
    if data.get("keywords"):
        detail["show"]["keywords"] = str(data["keywords"])
    return build_parsed_content(
        platform="bilibili",
        item_id=project_id,
        item_kind="show",
        title=name,
        summary="\n".join(summary_lines),
        cover_url=cover or banner,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="ticket",
        badge="会员购",
        detail=detail,
    )


# ---------- 电竞赛事 ----------

_ESPORTS_CENTRE_API = "https://api.bilibili.com/x/esports/season/centre/info"
_ESPORTS_CONTESTS_API = "https://api.bilibili.com/x/esports/component/contests/link"


def _match_line(contest: dict) -> str:
    home = str(((contest.get("home") or {}).get("name")) or "?")
    away = str(((contest.get("away") or {}).get("name")) or "?")
    stage = str(contest.get("game_stage") or "").strip()
    home_score = contest.get("home_score")
    away_score = contest.get("away_score")
    if home_score is not None and away_score is not None:
        versus = f"{home} {home_score}:{away_score} {away}"
    else:
        versus = f"{home} vs {away}"
    time_text = _fmt_ts(contest.get("start_time"), "%m-%d %H:%M")
    bits = [time_text, stage, versus]
    return " ".join(bit for bit in bits if bit)


def _parse_match(url: str, *, cookie_header: str = "") -> ParsedContent:
    """电竞赛事：赛季中心信息 + 对阵列表；参数全 0 时诚实浅卡。"""
    gid_match = _ESPORTS_GID_RE.search(url)
    sid_match = _ESPORTS_SID_RE.search(url)
    mid_match = _ESPORTS_MID_RE.search(url)
    gid = gid_match.group(1) if gid_match else ""
    sid = sid_match.group(1) if sid_match else ""
    mid = mid_match.group(1) if mid_match else ""
    # 赛程页模板常带 mid=0&gid=0&tid=0 占位参数，按缺失处理。
    gid = "" if gid == "0" else gid
    sid = "" if sid == "0" else sid
    mid = "" if mid == "0" else mid
    season: dict = {}
    if gid and sid:
        payload = http_get_json(
            f"{_ESPORTS_CENTRE_API}?gid={gid}&sid={sid}",
            referer="https://www.bilibili.com/",
            cookie=cookie_header,
        )
        if payload.get("code") == 0:
            season = (payload.get("data") or {}).get("season") or {}
    if not season and gid:
        # 赛程页只带 gid 时：取该游戏赛季列表里的目标赛季。
        list_payload = http_get_json(
            f"https://api.bilibili.com/x/esports/season/centre/list?gid={gid}",
            referer="https://www.bilibili.com/",
            cookie=cookie_header,
        )
        if list_payload.get("code") == 0:
            seasons = list_payload.get("data") or []
            for item in seasons:
                if not isinstance(item, dict):
                    continue
                if mid and str(item.get("mid")) == mid:
                    season = item
                    break
            if not season and isinstance(seasons, list) and seasons:
                season = seasons[0]
    title = str(season.get("title") or "").strip() if isinstance(season, dict) else ""
    contests: list[dict] = []
    if mid:
        try:
            contest_payload = http_get_json(
                f"{_ESPORTS_CONTESTS_API}?mid={mid}" + (f"&gid={gid}" if gid else ""),
                referer="https://www.bilibili.com/",
                cookie=cookie_header,
            )
            if contest_payload.get("code") == 0:
                data = contest_payload.get("data") or {}
                contests = list(data.get("future") or []) + list(data.get("history") or [])
        except ParseHttpError:  # 对阵列表失败不影响主卡。
            contests = []
    if not contests and isinstance(season, dict) and season.get("mid"):
        try:
            contest_payload = http_get_json(
                f"{_ESPORTS_CONTESTS_API}?mid={season['mid']}",
                referer="https://www.bilibili.com/",
                cookie=cookie_header,
            )
            if contest_payload.get("code") == 0:
                data = contest_payload.get("data") or {}
                contests = list(data.get("future") or []) + list(data.get("history") or [])
        except ParseHttpError:
            contests = []
    if not title and contests:
        for contest in contests:
            season_info = (contest or {}).get("season") or {}
            if season_info.get("title"):
                title = str(season_info["title"])
                break
    if not title:
        return build_parsed_content(
            platform="bilibili",
            item_id="",
            item_kind="match",
            title="哔哩哔哩电竞赛事",
            summary="（赛事页参数为空或接口不可用，机器人拿不到具体赛季信息；"
            "已保留原链接，点开即可查看赛程）",
            canonical_url=url,
            parse_depth="shallow",
            page_type="esports",
            badge="赛事",
        )
    summary_lines: list[str] = []
    stime = _fmt_ts(season.get("stime"), "%Y-%m-%d")
    etime = _fmt_ts(season.get("etime"), "%Y-%m-%d")
    if stime or etime:
        summary_lines.append(f"赛程：{stime} ~ {etime}")
    if contests:
        summary_lines.append("对阵（近期）：")
        for contest in contests[:8]:
            line = _match_line(contest)
            if line:
                summary_lines.append(f"  {line}")
    cover = str(season.get("centre_pc_logo") or season.get("centre_logo") or "")
    stats: dict[str, object] = {}
    if stime:
        stats["开始时间"] = stime
    if contests:
        stats["对阵场次"] = len(contests)
    detail: dict = {"match": {"season_id": str(season.get("id") or sid or "")}}
    if season.get("url"):
        detail["match"]["schedule_url"] = str(season["url"])
    return build_parsed_content(
        platform="bilibili",
        item_id=str(season.get("id") or mid or ""),
        item_kind="match",
        title=title,
        summary="\n".join(summary_lines),
        cover_url=cover if cover.startswith("http") else (f"https://i0.hdslb.com{cover}" if cover else ""),
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="esports",
        badge="赛事",
        detail=detail,
    )


# ---------- 公益（love.bilibili.com） ----------

def _parse_love_card(url: str) -> ParsedContent:
    """公益项目页：纯 SPA 无 SSR 无 og，诚实降级浅卡。"""
    uuid_match = _LOVE_UUID_RE.search(url)
    uuid = uuid_match.group(1) if uuid_match else ""
    return build_parsed_content(
        platform="bilibili",
        item_id=uuid,
        item_kind="charity",
        title="哔哩哔哩公益项目",
        summary="（公益项目页为动态渲染且无公开接口，机器人拿不到项目详情；"
        "已保留原链接，点开即可查看）",
        canonical_url=url,
        parse_depth="shallow",
        page_type="charity",
        badge="公益",
    )


# ---------- 游戏中心（biligame.com） ----------

_BILIGAME_INFO_API = "https://line1-h5-pc-api.biligame.com/game/detail/gameinfo"


def _parse_biligame(game_id: str, url: str, *, cookie_header: str = "") -> ParsedContent:
    """B 站游戏中心游戏页：gameinfo（游戏名/简介/开发商/下载量/图标）。"""
    payload = http_get_json(
        f"{_BILIGAME_INFO_API}?game_base_id={game_id}",
        referer="https://www.biligame.com/",
        cookie=cookie_header,
    )
    if payload.get("code") != 0:
        raise ParseHttpError(f"biligame gameinfo api code={payload.get('code')}")
    data = payload.get("data") or {}
    title = str(data.get("game_name_v2") or data.get("title") or "").strip()
    if not title:
        raise ParseHttpError("biligame gameinfo missing name")
    summary_lines: list[str] = []
    intro = str(data.get("summary") or "").strip()
    if intro:
        summary_lines.append(f"简介：{intro[:260]}")
    developer = str(data.get("developer_name") or "").strip()
    if developer:
        summary_lines.append(f"开发商：{developer}")
    rank_name = str(data.get("rank_type_name") or "").strip()
    rank_num = _safe_int(data.get("game_rank"))
    if rank_name and rank_num:
        summary_lines.append(f"{rank_name}：第 {rank_num} 名")
    stats: dict[str, object] = {}
    downloads = _safe_int(data.get("download_count"))
    if downloads is not None:
        stats["下载量"] = downloads
    icon = str(data.get("icon") or "")
    if icon.startswith("//"):
        icon = f"https:{icon}"
    detail = {
        "game": {
            "game_base_id": game_id,
            "name": title,
            "developer": developer,
            "rank_type": rank_name,
            "rank": rank_num,
        }
    }
    return build_parsed_content(
        platform="bilibili",
        item_id=game_id,
        item_kind="game",
        title=title,
        summary="\n".join(summary_lines),
        cover_url=icon,
        canonical_url=url,
        stats=stats,
        parse_depth="deep",
        page_type="game",
        badge="游戏",
        detail=detail,
    )


# ---------- 搜索页 ----------

def _parse_search_card(url: str) -> ParsedContent:
    """B 站搜索结果页：列表走签名接口，这里提取关键词出浅卡。"""
    keyword = ""
    try:
        query = urllib.parse.urlsplit(url).query
        keyword = str(urllib.parse.parse_qs(query).get("keyword", [""])[0]).strip()
    except ValueError:  # 非法查询串仅丢关键词。
        keyword = ""
    title = f"B站搜索：{keyword}" if keyword else "B站搜索结果页"
    return build_parsed_content(
        platform="bilibili",
        item_id="",
        item_kind="search",
        title=title,
        summary="（搜索结果列表需要登录态接口签名，这里只给入口；"
        "想看哪个视频，请把具体视频链接发我）",
        canonical_url=url,
        parse_depth="shallow",
        page_type="search",
        badge="搜索",
    )


# ---------- 分发 ----------

def parse_bilibili(url: str, *, cookie_header: str = "") -> ParsedContent:
    """B 站链接分发：视频 / 直播间 / 空间 / 收藏夹 / 动态 / 番剧 / 合集 /
    专栏 / 课程 / 漫画 / 会员购 / 电竞 / 公益 / 游戏中心 / 搜索。"""
    if "/channel/seriesdetail" in url or "/lists" in url or "/list/ml" in url:
        return _parse_series(url, cookie_header=cookie_header)
    # --- 子域/新页面类型（在短链解析之前处理，避免误匹配视频正则） ---
    if "love.bilibili.com" in url:
        return _parse_love_card(url)
    if "search.bilibili.com" in url:
        return _parse_search_card(url)
    manga_match = _MANGA_ID_RE.search(url)
    if manga_match:
        return _parse_manga_card(manga_match.group(1), url)
    if "show.bilibili.com" in url and _SHOW_ID_RE.search(url):
        return parse_bilibili_show(url, cookie_header=cookie_header)
    biligame_match = _BILIGAME_ID_RE.search(url)
    if biligame_match:
        return _parse_biligame(biligame_match.group(1), url, cookie_header=cookie_header)
    article_match = _ARTICLE_ID_RE.search(url)
    if article_match:
        return _parse_article(article_match.group(1), url, cookie_header=cookie_header)
    if "/read/" in url:
        # /read/mobile?id=... 等变体：从查询串兜底取专栏 id。
        query_id = _SHOW_ID_RE.search(url)
        if query_id:
            return _parse_article(query_id.group(1), url, cookie_header=cookie_header)
    cheese_ss_match = _CHEESE_SS_RE.search(url)
    if cheese_ss_match:
        return _parse_cheese(cheese_ss_match.group(1), url, cookie_header=cookie_header)
    if "/cheese/" in url:
        # ep 直链拿不到 season_id，诚实浅卡（不虚构 season 映射）。
        ep_match = _CHEESE_EP_RE.search(url)
        return build_parsed_content(
            platform="bilibili",
            item_id=f"ep{ep_match.group(1)}" if ep_match else "",
            item_kind="cheese",
            title="B站付费课程",
            summary="（课程单集链接需要 season 映射接口，这里只给入口；"
            "建议发送课程主页 ss 链接获取完整信息）",
            canonical_url=url,
            parse_depth="shallow",
            page_type="cheese",
            badge="课程",
        )
    if "/match/game" in url or "/v/game/match/" in url:
        return _parse_match(url, cookie_header=cookie_header)
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
    tdynamic_match = _TDYNAMIC_RE.search(url)
    if tdynamic_match:
        return _parse_opus(tdynamic_match.group(1), url, cookie_header=cookie_header)
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

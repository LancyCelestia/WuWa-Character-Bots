"""通用卡片渲染桥接。

移植并适配自一个 MIT 许可的开源卡片渲染上游项目 core/render_html/bridge.py
（完整出处与许可声明见 docs/THIRD_PARTY_NOTICES.md，
Copyright (c) 2024 Les Freire）。

职责：
- parse_to_render_payload(item)：把 PlatformParse（含可选 page_type/badge/
  detail）转换为字段完整的 RenderPayload；
- render_universal_card_html(payload_dict)：合并默认值并用 Jinja2 渲染模板，
  所有顶层变量都有默认值，字段缺失时对应区块整体隐藏；
- QR 码由项目依赖 qrcode[pil] 生成；异常时隐藏二维码区块，不阻断卡片渲染。
"""

from __future__ import annotations

import base64
import colorsys
import html
import io
import os
import re
import threading
import urllib.parse
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any

import jinja2

from ..render_backends import build_render_backend
from .models import ForwardPayload, RenderPayload

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR), encoding="utf-8"),
    autoescape=True,
)
_TEMPLATE = _ENV.get_template("universal_card.html")

# ==================== 平台配色 / 官方名映射 ====================
PLATFORM_COLORS: dict[str, str] = {
    "bilibili": "#fb7299",
    "xiaohongshu": "#ff2442",
    "xhs": "#ff2442",
    "douyin": "#111111",
    "weibo": "#e6162d",
    "youtube": "#ff0000",
    "twitter": "#1d9bf0",
    "x": "#1d9bf0",
    "pixiv": "#0096fa",
    "lofter": "#3fa1ad",
    "allcpp": "#2f6bff",
    "cpp": "#2f6bff",
    # 音乐平台品牌色
    "netease": "#c20c0c",
    "ncm": "#c20c0c",
    "qqmusic": "#00c853",
    "kugou": "#ff5722",
    "kuwo": "#ff6f00",
    "apple_music": "#fa243c",
    "spotify": "#1db954",
    "facebook": "#1877f2",
    "instagram": "#d62976",
}
UNKNOWN_PLATFORM_COLOR = "#607080"

PLATFORM_OFFICIAL_NAMES: dict[str, str] = {
    "bilibili": "Bilibili",
    "xiaohongshu": "Xiaohongshu",
    "xhs": "Xiaohongshu",
    "douyin": "Douyin",
    "weibo": "Weibo",
    "youtube": "YouTube",
    "twitter": "Twitter/X",
    "x": "Twitter/X",
    "pixiv": "Pixiv",
    "lofter": "LOFTER",
    "allcpp": "AllCPP",
    "cpp": "AllCPP",
    "netease": "NetEase Cloud Music",
    "ncm": "NetEase Cloud Music",
    "qqmusic": "QQ Music",
    "kugou": "KuGou Music",
    "kuwo": "Kuwo Music",
    "apple_music": "Apple Music",
    "spotify": "Spotify",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "generic": "Web",
}

# 模板“已知键”特殊标签已覆盖的统计键（其余走通用遍历）。
_KNOWN_STAT_KEYS = frozenset({
    "views", "danmaku", "likes", "favorites", "coins", "comments", "reposts", "shares",
    "following", "followers", "user_likes", "total_views", "quotes", "bookmarks",
    "attention", "fansclub", "high_energy_users", "fleet_total", "captain",
    "admiral", "governor", "is_living", "live_level", "top3_rank", "live_viewers",
    "live_rank", "live_watched", "live_popularity", "official_title",
    # 中文键已由 bridge 提炼到直播间字段，避免重复展示。
    "观看", "在线", "人气",
    "粉丝", "关注", "视频数", "专栏数",
    "时长", "发布时间", "pubdate", "duration", "duration_seconds",
    "AV", "av", "avid", "AV号",
})

_DEFAULT_CONTEXT = RenderPayload().to_dict()

def _resolve_icon_asset_root() -> Path:
    """Resolve card SVG assets outside the AI workspace when available."""
    configured = os.getenv("BOT_CARD_ASSET_DIR", "").strip()
    if configured:
        return Path(configured).expanduser() / "iconfont"

    # Search ancestors instead of depending on a fixed directory depth.
    # This supports both MyWorkspace\ChatBot and Archive\ChatBot\ChatBot layouts.
    for ancestor in Path(__file__).resolve().parents:
        external = ancestor / "ChatBot_Runtime" / "card_render_assets" / "iconfont"
        if external.is_dir():
            return external

    # Development fallback: preserve the old checked-in layout for restoration.
    return Path(__file__).resolve().parent / "assets" / "iconfont"


_ICON_ASSET_ROOT = _resolve_icon_asset_root()
_METRIC_ICON_FILES = {
    "views": "5375/播放数_32.svg",
    "danmaku": "5375/弹幕数_32.svg",
    "comments": "5375/16_ico_reply.svg",
    "likes": "5375/32_ic_赞.svg",
    "coins": "5375/B币_32.svg",
    "favorites": "5375/收藏_32.svg",
    "shares": "5375/分享_32.svg",
}
_PLATFORM_LOGO_FILES = {
    "bilibili": "../platforms/bilibili.svg",
    "douyin": "../platforms/douyin_user.svg",
    "xiaohongshu": "../platforms/xiaohongshu_user.svg",
    "xhs": "../platforms/xiaohongshu_user.svg",
    "weibo": "../platforms/weibo.svg",
    "youtube": "../platforms/youtube_user.svg",
    "twitter": "../platforms/twitter_x_user.svg",
    "x": "../platforms/twitter_x_user.svg",
    "spotify": "../platforms/spotify_user.svg",
    "apple_music": "../platforms/apple_music_user.svg",
    "facebook": "../platforms/facebook_user.svg",
    "instagram": "../platforms/instagram_user.svg",
}
_PLATFORM_FOOTER_LABELS = {
    "bilibili": "哔哩哔哩",
    "xiaohongshu": "小红书",
    "xhs": "小红书",
    "douyin": "抖音",
    "weibo": "微博",
    "youtube": "YouTube",
    "twitter": "Twitter/X",
    "x": "Twitter/X",
    "pixiv": "Pixiv",
    "lofter": "LOFTER",
    "spotify": "Spotify",
    "apple_music": "Apple Music",
    "facebook": "Facebook",
    "instagram": "Instagram",
}


# ==================== 基础工具 ====================
def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip() if isinstance(value, str) else str(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ==================== 本地图片内联 ====================
# playwright 以 about:blank 起页，file:// 子资源被 Chromium 拒载
# （实测白块）；本地图片（如竖切横图拼接结果）必须内联成 data URL 才能进卡。

_INLINE_MAX_BYTES = 12 * 1024 * 1024


def _inline_local_image(url: Any) -> str:
    """本地图片文件 → data URL；远程/ data:/缺失文件原样返回。"""
    raw = str(url or "").strip()
    if not raw or raw.startswith(("http://", "https://", "data:")):
        return raw
    candidate = Path(raw)
    if not candidate.is_file():
        return raw
    try:
        if candidate.stat().st_size > _INLINE_MAX_BYTES:
            return raw
        suffix = candidate.suffix.lower().lstrip(".") or "jpeg"
        mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
        encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
        return f"data:image/{mime};base64,{encoded}"
    except OSError:
        return raw


def _first_stat_value(stats: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = stats.get(key)
        if value is not None and value != "":
            return value
    return None


def _first_stat_int(stats: dict[str, Any], keys: tuple[str, ...]) -> int:
    return _as_int(_first_stat_value(stats, keys))


def _normalize_av_id(value: Any) -> str:
    """Normalize Bilibili AV variants to digits for the header only."""
    text = _as_str(value).strip()
    if not text:
        return ""
    match = re.search(r"(?i)\bav\s*(\d+)\b", text) or re.search(r"\b(\d{5,})\b", text)
    return match.group(1) if match else text.removeprefix("av").removeprefix("AV")


def _format_timestamp(value: Any) -> str:
    text = _as_str(value)
    if not text:
        return ""
    if text.isdigit() and len(text) >= 10:
        try:
            return datetime.fromtimestamp(int(text)).strftime("%Y-%m-%d %H:%M:%S")  # noqa: DTZ006 - 本地时间有意 naive
        except (OverflowError, OSError, ValueError):
            return text
    return text


def _format_duration(seconds: int) -> str:
    seconds = max(0, seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


# ==================== 釉瑚云母洗派生（mica-glass v2 2026-09-12） ====================
# 工艺出处=用户裁定两轮收敛：
# v1「粉里透紫、蓝里透粉」邻近色 pastel 工艺；v2（实弹验收 F3）基底不再随
# 平台色漂移——守岸人标志色（淡蓝/白/深蓝/星空紫）是唯一基底，所有卡片
# （含 weather/eat/help 等无平台语境卡）一律本命洗；平台个性只保留在
# --pc accent（徽章/高亮）与主色斑 ≤35% 透色两层。
# 色相锚点：wash-1 淡蓝 210°（可被平台色相 ±30° 内轻推）、wash-2 星空紫 265°、
# wash-3 深蓝 228°、mist 近白蓝雾 214°。灰阶/未知平台推力为零 → 纯本命洗。

_WASH_HUE_SHIFT = 30 / 360      # 平台色相对本命相的最大推幅
_WASH_HUE_PULL = 0.5            # 平台色相 → 推幅的比例（本命相权重 3:1）
_WASH_SAT_RATIO = 0.55          # pastel 化：输入饱和度保留比例
_WASH_LIGHT = 0.88              # 洗色明度
_WASH_MIST_LIGHT = 0.96         # 雾底明度 ≥94%
_WASH_BASE_HUE = 210 / 360      # 守岸人淡蓝本命相
_WASH_PURPLE_HUE = 265 / 360    # 星空紫
_WASH_DEEP_HUE = 228 / 360      # 深蓝
_WASH_MIST_HUE = 214 / 360      # 雾底淡蓝相
_WASH_BASE_SAT = 0.42           # 本命洗基准饱和度（×0.55 后为柔和 pastel）
_WASH_GRAY_THRESHOLD = 0.10     # S 低于此值视为无有效色相的灰阶（推力归零）


def _wash_hex(hue: float, sat_in: float, light: float) -> str:
    sat = sat_in * _WASH_SAT_RATIO
    red, green, blue = colorsys.hls_to_rgb(hue % 1.0, light, min(sat, 0.60))
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def _derive_wash_tokens(hex_color: str) -> dict[str, str]:
    """守岸人本命釉瑚云母洗四 token（wash_1/2/3/mist，#RRGGBB）。

    纯函数不抛异常：非法值经 _hex_to_rgb 回退中性灰（无有效色相，
    推力归零 → 纯本命洗）。平台色仅在有效色相时把 wash-1 淡蓝往
    平台相轻推（≤±30°，比例 0.5），保证基底永远是守岸人渐变。
    """
    red, green, blue = _hex_to_rgb(hex_color)
    hue, _lightness, sat = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
    base_hue = _WASH_BASE_HUE
    if sat >= _WASH_GRAY_THRESHOLD:
        delta = ((hue - base_hue + 0.5) % 1.0) - 0.5
        shift = max(-_WASH_HUE_SHIFT, min(_WASH_HUE_SHIFT, delta * _WASH_HUE_PULL))
        base_hue = (base_hue + shift) % 1.0
    return {
        "wash_1": _wash_hex(base_hue, _WASH_BASE_SAT, _WASH_LIGHT),
        "wash_2": _wash_hex(_WASH_PURPLE_HUE, 0.40, _WASH_LIGHT),
        "wash_3": _wash_hex(_WASH_DEEP_HUE, 0.45, _WASH_LIGHT + 0.01),
        "wash_mist": _wash_hex(_WASH_MIST_HUE, 0.20, _WASH_MIST_LIGHT),
    }


# ==================== 颜色派生 ====================
def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = (color or "").lstrip("#")
    if len(color) != 6:
        return (96, 112, 128)
    try:
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (96, 112, 128)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _darken(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(channel * 0.8))) for channel in rgb)  # type: ignore[return-value]


def _lighten(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(
        int(channel + (255 - channel) * 0.12) for channel in rgb
    )  # type: ignore[return-value]


# ==================== 字段映射 ====================
def _map_comment(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        "author": _as_str(raw.get("user") or raw.get("author") or raw.get("name")),
        "avatar": _as_str(raw.get("avatar")),
        "level": _as_str(raw.get("level")),
        "time": _as_str(raw.get("time")),
        "content": _as_str(raw.get("content") or raw.get("text")),
        "likes": _as_str(raw.get("likes")),
        "handle": _as_str(raw.get("handle")),
        "title_badge": _as_str(raw.get("title_badge")),
        "dress": _as_str(raw.get("dress")),
        "replies_count": _as_str(raw.get("replies_count")),
        "is_hot": bool(raw.get("is_hot")),
    }


def _clean_card_summary(summary: str) -> str:
    """卡片简介只留博主原文：去时长/发布时间行与“简介：”前缀；
    保留解析器插入的空行分段（AI 总结/热评分隔），连续空行折叠。"""
    kept: list[str] = []
    for raw_line in (summary or "").splitlines():
        line = raw_line.strip()
        if not line:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        head = line.split("：", 1)[0].split(":", 1)[0].strip()
        if head == "简介":
            content = ""
            if "：" in line:
                content = line.split("：", 1)[1]
            elif ":" in line:
                content = line.split(":", 1)[1]
            if content.strip():
                kept.append(content.strip())
            continue
        if head in {"时长", "视频时长", "发布时间", "时间", "上传时间", "分区"}:
            continue
        kept.append(line)
    while kept and kept[0] == "":
        kept.pop(0)
    while kept and kept[-1] == "":
        kept.pop()
    return "\n".join(kept)




def _load_icon_asset(relative_path: str) -> str:
    """Load an Iconfont SVG for inline rendering."""
    if not relative_path:
        return ""
    try:
        return (_ICON_ASSET_ROOT / relative_path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _first_nonempty_stat(stats: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        value = stats.get(key)
        if value is not None and value != "":
            return value
    return None


_METRIC_DEFINITIONS: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "video": (
        ("views", "播放", ("views", "播放", "播放量", "观看", "浏览量")),
        ("danmaku", "弹幕", ("danmaku", "弹幕", "弹幕数")),
        ("comments", "评论", ("comments", "评论", "评论数")),
        ("likes", "点赞", ("likes", "点赞", "赞", "爱心")),
        ("coins", "投币", ("coins", "投币", "硬币")),
        ("favorites", "收藏", ("favorites", "收藏", "收藏数")),
        ("shares", "转发", ("shares", "转发", "转发数", "分享", "reposts")),
    ),
    "dynamic": (
        ("likes", "点赞", ("likes", "点赞", "赞", "爱心")),
        ("shares", "转发", ("shares", "转发", "转发数", "分享", "reposts")),
        ("comments", "评论", ("comments", "评论", "评论数")),
    ),
    "article": (
        ("views", "浏览量", ("views", "浏览量", "浏览", "阅读", "阅读量")),
        ("likes", "点赞", ("likes", "点赞", "赞", "爱心")),
        ("coins", "投币", ("coins", "投币", "硬币")),
        ("favorites", "收藏", ("favorites", "收藏", "收藏数")),
        ("shares", "转发", ("shares", "转发", "转发数", "分享", "reposts")),
        ("comments", "评论", ("comments", "评论", "评论数")),
    ),
    "note": (
        ("likes", "爱心", ("likes", "爱心", "点赞", "赞")),
        ("favorites", "收藏", ("favorites", "收藏", "收藏数")),
        ("comments", "评论", ("comments", "评论", "评论数")),
        ("shares", "转发", ("shares", "转发", "转发数", "分享", "reposts")),
    ),
    "tweet": (
        ("views", "浏览量", ("views", "浏览量", "浏览", "观看")),
        ("likes", "点赞", ("likes", "点赞", "赞", "喜欢")),
        ("comments", "评论", ("comments", "评论", "回复", "评论数")),
        ("shares", "转发", ("shares", "转发", "转发数", "转推", "分享", "reposts", "retweets")),
    ),
}


# 新平台页面类型 → 走 raw 指标策略（stats 原键直接进指标栏，无图标）。
_RAW_METRIC_PAGE_TYPES = frozenset(
    {
        "game", "store_page", "market_listing", "community_hub", "ticket",
        "cheese", "charity", "search", "project", "goods", "share_post",
        "share_video", "public_page", "works",
    }
)
_RAW_METRIC_PLATFORMS = frozenset({"steam", "epic", "mihuashi", "huajia", "facebook"})


def _metric_kind(platform: str, kind: str, page_type: str) -> str:
    if platform in {"xiaohongshu", "xhs"}:
        return "note"
    if kind in {"article", "column", "opus"} or page_type in {"article", "column"}:
        return "article"
    if kind == "tweet" or page_type == "tweet":
        # X 专属指标桶：浏览量/点赞/评论/转发（不含弹幕/投币等视频指标）。
        return "tweet"
    if kind in {"dynamic", "post"} or page_type in {"dynamic", "post"}:
        return "dynamic"
    if kind == "video" or page_type == "video":
        return "video"
    if page_type in _RAW_METRIC_PAGE_TYPES or platform in _RAW_METRIC_PLATFORMS:
        # 新平台（Steam/Epic/米画师/画加/Facebook/会员购等）：stats 原键直接上卡。
        return "raw"
    return "generic"


def _build_metric_items(
    platform: str,
    kind: str,
    page_type: str,
    stats: dict[str, Any],
) -> list[dict[str, Any]]:
    metric_kind = _metric_kind(platform, kind, page_type)
    if metric_kind == "raw":
        # raw：无图标指标卡，stats 原键原标签直接展示（最多 7 项）。
        raw_items: list[dict[str, Any]] = []
        for key, value in stats.items():
            if isinstance(value, (dict, list)) or value in (None, ""):
                continue
            raw_items.append(
                {
                    "key": "raw",
                    "label": str(key),
                    "value": value,
                    "icon_svg": "",
                    "source": "none",
                }
            )
            if len(raw_items) >= 7:
                break
        return raw_items
    definitions = _METRIC_DEFINITIONS.get(metric_kind)
    if definitions is None:
        definitions = (
            ("views", "浏览", ("views", "播放", "播放量", "观看", "浏览", "浏览量")),
            ("likes", "点赞", ("likes", "点赞", "赞", "爱心")),
            ("comments", "评论", ("comments", "评论", "评论数")),
            ("shares", "转发", ("shares", "转发", "转发数", "分享", "reposts")),
        )
    items: list[dict[str, Any]] = []
    for key, label, aliases in definitions:
        value = _first_nonempty_stat(stats, aliases)
        if value is None:
            continue
        items.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "icon_svg": _load_icon_asset(_METRIC_ICON_FILES.get(key, "")),
                "source": "iconfont" if key in _METRIC_ICON_FILES else "none",
            }
        )
    return items


def _format_join_date(value: Any) -> str:
    """博主注册日期归一成 YYYY-MM-DD；支持推特/ISO/中文格式，失败返回空。"""
    raw = _as_str(value).strip()
    if not raw:
        return ""
    import datetime

    for fmt in (
        "%a %b %d %H:%M:%S %z %Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y年%m月%d日",
        "%Y/%m/%d",
    ):
        try:
            return datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")  # noqa: DTZ007 - 仅取日期。
        except ValueError:
            continue
    match = re.match(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", raw)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return ""


# ==================== 嵌套模型 → 渲染投影 ====================
def flat_projection(item: Any) -> Any:
    """把纯嵌套 ParsedContent 还原成渲染投影字典（渲染边界专用）。

    模型层不再有扁平字段；渲染层统一经本函数把嵌套数据 + 各平台
    ``platform_extra`` 还原为卡片需要的扁平形状（stats/detail 等），
    卡片区块与迁移前保持等价（个别标量会经统一格式化，如发布时间补秒）。
    非 ParsedContent 输入原样返回。
    """
    from plugins.bot_unified_runtime.contracts.media import ParsedContent

    if not isinstance(item, ParsedContent):
        return item
    identity = item.identity
    content = item.content
    creator = item.creator
    engagement = item.engagement
    media = list(item.media or [])
    provenance = item.provenance
    content_extras = dict(content.platform_extra or {}) if content else {}
    engagement_extras = dict(engagement.platform_extra or {}) if engagement else {}
    creator_extras = dict(creator.platform_extra or {}) if creator else {}

    platform = identity.platform if identity else ""
    item_id = identity.item_id if identity else ""
    kind = identity.item_kind if identity else ""
    canonical = identity.canonical_url if identity else ""
    title = content.title if content else ""
    summary = content.summary if content else ""
    page_type = str(content_extras.get("page_type") or "")
    badge = str(content_extras.get("badge") or "")
    published_at = content.published_at if content else None

    video_asset = next(
        (asset for asset in media if asset.asset_type == "video"), None
    )

    # 统计栏：统一互动字段 → 卡片已知键（全部在 _KNOWN_STAT_KEYS 内），
    # 平台特有键经 platform_extra 原样透传。
    stats: dict[str, Any] = {}
    if engagement is not None:
        for key, value in (
            ("views", engagement.view_count),
            ("播放次数", engagement.play_count),
            ("likes", engagement.like_count),
            ("comments", engagement.comment_count),
            ("favorites", engagement.favorite_count),
            ("bookmarks", engagement.bookmark_count),
            ("shares", engagement.share_count),
            ("reposts", engagement.repost_count),
            ("quotes", engagement.quote_count),
            ("danmaku", engagement.danmaku_count),
            ("coins", engagement.coin_count),
        ):
            if value is not None:
                stats[key] = value
        if engagement.like_count is None and engagement.heart_count is not None:
            stats["likes"] = engagement.heart_count
    if creator is not None:
        for key, value in (
            ("followers", creator.follower_count),
            ("following", creator.following_count),
            ("posts", creator.post_count),
            ("videos", creator.video_count),
            ("user_likes", creator.received_like_count),
        ):
            if value is not None:
                stats[key] = value
    for key, extra_value in engagement_extras.items():
        if not isinstance(extra_value, (dict, list)):
            stats[key] = extra_value
    if published_at is not None:
        try:
            stats["发布时间"] = published_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            stats["发布时间"] = published_at.strftime("%Y-%m-%d %H:%M:%S")
    if video_asset is not None and video_asset.duration_ms is not None:
        stats["时长"] = video_asset.duration_ms // 1000
    if platform == "bilibili" and item_id.lower().startswith("av"):
        stats["AV号"] = item_id

    # detail：作者/视频/图集/分P/直播/评论/商品/相关等平台扩展原样透传。
    detail: dict[str, Any] = {}
    if creator is not None:
        author: dict[str, Any] = {}
        if creator.name:
            author["name"] = creator.name
        if creator.avatar_url:
            author["avatar"] = creator.avatar_url
        if creator.signature or creator.bio:
            author["signature"] = creator.signature or creator.bio
        if creator.handle:
            author["handle"] = creator.handle
        if creator.platform_creator_id:
            author["uuid"] = creator.platform_creator_id
        verification = creator.verification
        if verification is not None:
            if verification.label:
                author["official_title"] = verification.label
            if verification.type:
                author["official_badge"] = verification.type
            if verification.verified is not None:
                author["verified"] = verification.verified
        if creator.follower_count is not None:
            author["fans"] = creator.follower_count
        if creator.joined_at is not None:
            author["created_at"] = creator.joined_at.isoformat()
        author.update(creator_extras)
        detail["author"] = author
    video: dict[str, Any] = {}
    if video_asset is not None:
        if video_asset.url:
            video["url"] = video_asset.url
        if video_asset.preview_url:
            video["thumbnail_url"] = video_asset.preview_url
        if video_asset.width is not None:
            video["width"] = video_asset.width
        if video_asset.height is not None:
            video["height"] = video_asset.height
        if video_asset.duration_ms is not None:
            video["duration"] = video_asset.duration_ms // 1000
    video_extras = content_extras.get("video")
    if isinstance(video_extras, dict):
        for key, value in video_extras.items():
            video.setdefault(key, value)
    if published_at is not None and "pubdate" not in video:
        video["pubdate"] = int(published_at.timestamp())
    if video:
        detail["video"] = video
    images = content_extras.get("images")
    if isinstance(images, list):
        detail["images"] = [_inline_local_image(url) for url in images if str(url)]
    for key in (
        "episodes", "live", "comments", "goods", "related", "show",
        "pinned_comment", "hot_comment", "hot_comments",
    ):
        if key in content_extras:
            detail[key] = content_extras[key]

    cover = _inline_local_image(content_extras.get("cover_url"))
    return {
        "platform": platform,
        "item_id": item_id,
        "item_kind": kind,
        "page_type": page_type,
        "badge": badge,
        "title": title,
        "summary": summary,
        "cover_url": cover,
        "canonical_url": canonical,
        "author_name": creator.name if creator else "",
        "stats": stats,
        "detail": detail,
        "parse_depth": provenance.parse_depth if provenance else "deep",
    }


def parse_to_render_payload(item: Any) -> RenderPayload:
    """把 PlatformParse（或等价字典）映射为字段完整的 RenderPayload。

    契约中的 page_type/badge/detail 全部可选；缺省时返回一张空但可渲染的
    卡片（各区块隐藏）。纯嵌套 ParsedContent 先经 ``flat_projection``
    还原成渲染投影字典，再走既有映射逻辑。
    """
    item = flat_projection(item)
    platform = _as_str(_get(item, "platform")).strip().lower()
    kind = _as_str(_get(item, "item_kind")).strip().lower()
    page_type = _as_str(_get(item, "page_type")).strip().lower() or kind
    badge = _as_str(_get(item, "badge")).strip()
    item_id = _as_str(_get(item, "item_id")).strip()
    title = _as_str(_get(item, "title")).strip()
    summary = _as_str(_get(item, "summary"))
    cover = _inline_local_image(_get(item, "cover_url"))
    canonical = _as_str(_get(item, "canonical_url"))

    stats_raw = _as_dict(_get(item, "stats"))
    detail = _as_dict(_get(item, "detail"))
    author = _as_dict(detail.get("author"))
    video = _as_dict(detail.get("video"))
    episodes = _as_list(detail.get("episodes"))
    images = _as_list(detail.get("images"))
    live = _as_dict(detail.get("live"))
    comments_raw = _as_list(detail.get("comments"))
    goods = _as_dict(detail.get("goods"))
    related = _as_list(detail.get("related"))

    payload = RenderPayload()
    payload.platform = platform
    payload.type = kind
    payload.page_type = page_type
    payload.title = title
    payload.summary = summary
    payload.text = summary
    payload.url = canonical
    payload.cover_url = cover
    payload.timestamp = (
        _as_str(_get(item, "timestamp"))
        or _as_str(_get(item, "published_at"))
        or _as_str(video.get("pubdate"))
        or _as_str(_first_stat_value(stats_raw, ("发布时间", "时间", "上传时间", "pubdate")))
    )

    # 作者
    payload.name = _as_str(author.get("name")) or _as_str(_get(item, "author_name"))
    payload.avatar = _as_str(author.get("avatar"))
    payload.signature = _as_str(author.get("signature"))
    payload.handle = _as_str(author.get("handle"))
    payload.author_uuid = _as_str(
        author.get("uuid") or author.get("author_uuid") or author.get("unique_id") or author.get("mid")
    )
    join_date = _format_join_date(
        author.get("created_at") or author.get("joined") or author.get("created_date")
    )
    if join_date:
        payload.profile_join_date = join_date
    payload.follower_count = _as_str(author.get("fans"))
    payload.official_title = _as_str(author.get("official_title"))
    payload.official_badge = (
        badge
        or _as_str(author.get("official_badge"))
        or _as_str(author.get("verified"))
        or _as_str(detail.get("badge"))
    )

    # 各类 ID 标签（UID/Handle/BVID/AV/动态/直播/空间/收藏夹/番剧/帖子）
    payload.uid = item_id
    if kind == "dynamic":
        payload.extra_dynamic_id, payload.uid = item_id, ""
    elif kind == "live":
        payload.extra_live_id, payload.uid = item_id, ""
    elif kind in {"user", "space", "painter"}:
        payload.extra_space_id, payload.uid = item_id, ""
    elif kind == "collection":
        payload.extra_favlist_id, payload.uid = item_id, ""
    elif kind == "bangumi":
        payload.extra_bangumi_id, payload.uid = item_id, ""
    elif kind in {"tweet", "note", "post", "article", "opus"}:
        payload.extra_status_id, payload.uid = item_id, ""
    elif platform == "bilibili" and item_id.upper().startswith("BV"):
        payload.bvid, payload.uid = item_id, ""
    elif platform == "bilibili" and item_id.lower().startswith("av"):
        payload.av_id, payload.uid = item_id, ""
    if platform == "bilibili" and not payload.av_id:
        raw_av = video.get("aid") or _first_nonempty_stat(
            stats_raw, ("AV", "av", "avid", "AV号")
        )
        if raw_av not in (None, ""):
            payload.av_id = _normalize_av_id(raw_av)

    # 正文 / 图片 / 横幅
    payload.banner = (
        _as_str(live.get("keyframe"))
        or _as_str(live.get("cover"))
        or cover
    )
    payload.image_urls = [_inline_local_image(url) for url in images if _as_str(url)]

    # 分 P / 剧集
    pages: list[dict[str, Any]] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        duration = _as_int(
            episode.get("duration_seconds", episode.get("duration", 0))
        )
        page_title = _as_str(episode.get("title")) or (
            f"P{_as_str(episode.get('index'))}" if _as_str(episode.get("index")) else ""
        )
        pages.append(
            {
                "title": page_title,
                "duration": duration,
                "cover": _as_str(episode.get("cover")),
            }
        )
    payload.video_pages = pages

    # 作者指标与内容互动分开：渲染投影产出的 stats 里，只把已知作者键
    # 分进 author_stats，其余按视频/通用键分进 video_stats（未知键保留）。
    explicit_author_stats = _as_dict(_get(item, "author_stats"))
    explicit_video_stats = _as_dict(_get(item, "video_stats"))
    author_keys = (
        "followers", "following", "user_likes", "total_views", "videos", "columns",
        "video_count", "column_count", "粉丝", "关注", "获赞", "总播放", "视频数", "专栏数",
        "帖子数", "media_count",
    )
    video_keys = ("views", "danmaku", "comments", "likes", "coins", "favorites", "shares", "reposts", "播放", "播放量", "观看", "浏览", "浏览量", "弹幕", "弹幕数", "评论", "评论数", "点赞", "赞", "投币", "硬币", "收藏", "收藏数", "转发", "转发数")
    payload.author_stats = explicit_author_stats or {
        key: value for key, value in stats_raw.items() if key in author_keys
    }
    payload.video_stats = explicit_video_stats or {
        key: value for key, value in stats_raw.items() if key in video_keys
    }
    if "reposts" in payload.video_stats and "shares" not in payload.video_stats:
        payload.video_stats["shares"] = payload.video_stats["reposts"]
    if _metric_kind(platform, kind, page_type) != "generic":
        metric_source = {
            key: value
            for key, value in (explicit_video_stats or stats_raw).items()
            if key not in author_keys
        }
        payload.stats_bar_items = _build_metric_items(
            platform,
            kind,
            page_type,
            metric_source,
        )

    # 博主结构化数据（视频/空间解析带上的 粉丝/关注/视频数/专栏数）。
    author_metric_specs = (
        ("followers", "粉丝", ("followers", "粉丝", "fans")),
        ("following", "关注", ("following", "关注")),
        ("videos", "视频", ("videos", "video_count", "视频数")),
        ("columns", "专栏", ("columns", "column_count", "专栏数")),
        ("posts", "帖子", ("posts", "media_count", "帖子数")),
        ("user_likes", "获赞", ("user_likes", "获赞", "获赞与收藏")),
    )
    merged_author_stats = {**author, **payload.author_stats}
    for key, label, aliases in author_metric_specs:
        value = _first_nonempty_stat(merged_author_stats, aliases)
        if value is None:
            value = _first_nonempty_stat(stats_raw, aliases)
        if value in (None, ""):
            continue
        # B 站 post_count 语义是专栏数，作者栏标签跟随平台语义。
        if platform == "bilibili" and key == "posts":
            label = "专栏"
        payload.author_stats.setdefault(key, value)
        payload.author_stat_items.append({"key": key, "label": label, "value": value})
        payload.header_l4_items.append({"label": label, "value": value})

    # 第二行：视频ID / 动态ID / 番剧ID / 商品ID
    if kind == "dynamic":
        payload.header_l2_items.append({"label": "动态ID", "value": item_id})
    elif kind == "bangumi":
        payload.header_l2_items.append({"label": "番剧ID", "value": item_id})
    elif kind in {"goods", "ticket", "mall"}:
        payload.header_l2_items.append({"label": "商品ID", "value": item_id})
    elif platform == "bilibili" and item_id.upper().startswith("BV") or platform == "bilibili" and item_id.lower().startswith("av"):
        payload.header_l2_items.append({"label": "视频ID", "value": item_id})

    # 发布时间：精确到年月日时分秒
    pub_raw = video.get("pubdate") or _first_stat_value(
        stats_raw, ("pubdate", "发布时间", "pub_time")
    )
    if pub_raw is not None:
        payload.timestamp = _format_timestamp(pub_raw)

    # 视频时长 / 简介（从 stats 的常见键提炼）
    duration_raw = video.get("duration") or _first_stat_value(
        stats_raw, ("duration", "duration_seconds", "时长")
    )
    if duration_raw is not None:
        payload.video_duration = _format_duration(_as_int(duration_raw))
    desc_raw = _first_stat_value(stats_raw, ("简介", "desc", "description"))
    if desc_raw is not None:
        payload.video_desc = _as_str(desc_raw)

    # 直播间
    payload.live_title = _as_str(live.get("title"))
    payload.live_cover = _as_str(live.get("cover"))
    payload.live_screenshot = _as_str(live.get("keyframe"))
    area_parts = [
        part
        for part in (_as_str(live.get("parent_area")), _as_str(live.get("area")))
        if part
    ]
    payload.live_area = "/".join(area_parts)
    payload.live_tags = " ".join(
        _as_str(tag) for tag in _as_list(live.get("tags")) if _as_str(tag)
    )
    payload.live_desc = _as_str(live.get("intro"))
    live_start = live.get("start_time")
    if live_start not in (None, ""):
        payload.timestamp = _format_timestamp(live_start)
    payload.live_viewers = _first_stat_int(
        stats_raw, ("live_viewers", "观看", "在线")
    )
    payload.live_popularity = _first_stat_int(
        stats_raw, ("live_popularity", "人气")
    )

    # 评论
    payload.comments = [
        _map_comment(comment)
        for comment in comments_raw
        if isinstance(comment, dict)
    ]
    pinned = _as_dict(detail.get("pinned_comment"))
    hot = _as_dict(detail.get("hot_comment"))
    payload.pinned_comment = _map_comment(pinned) if pinned else None
    payload.hot_comment = _map_comment(hot) if hot else None
    # 热评列表（B 站等解析器存 hot_comments 数组）：映射后取前 3 条进模板。
    hot_list = [
        _map_comment(comment)
        for comment in _as_list(detail.get("hot_comments"))
        if isinstance(comment, dict)
    ]
    if not hot_list and payload.hot_comment is not None:
        hot_list = [payload.hot_comment]
    payload.hot_comments = hot_list[:3]

    # 会员购参展嘉宾（detail.show.guests → 独立卡区）。
    show_data = _as_dict(detail.get("show"))
    payload.show_guests = [
        {
            "name": _as_str(guest.get("name")),
            "description": _as_str(guest.get("description")),
            "avatar": _inline_local_image(guest.get("avatar")),
            "book_num": _as_str(guest.get("book_num") or ""),
        }
        for guest in _as_list(show_data.get("guests"))
        if isinstance(guest, dict) and _as_str(guest.get("name"))
    ][:12]
    # 作者栏"帖子/专栏"计数标签：B 站 post_count 语义是专栏数。
    payload.stats_post_label = "专栏" if platform == "bilibili" else "帖子"

    # 商品信息并入正文（模板无独立 goods 块，先以文本行消费契约字段）
    goods_lines: list[str] = []
    if goods:
        goods_title = _as_str(goods.get("title"))
        if goods_title:
            goods_lines.append(f"商品：{goods_title}")
        brand = _as_str(goods.get("brand"))
        category = _as_str(goods.get("category"))
        if brand or category:
            goods_lines.append(" · ".join(part for part in (brand, category) if part))
        price = _as_str(goods.get("price"))
        origin_price = _as_str(goods.get("origin_price"))
        if price or origin_price:
            prices = " / ".join(part for part in (price, origin_price) if part)
            goods_lines.append(f"价格：{prices}")
        intro = _as_str(goods.get("intro"))
        if intro:
            goods_lines.append(intro)
    if goods_lines:
        payload.text = "\n\n".join(
            part for part in (payload.text, "\n".join(goods_lines)) if part
        )

    # 相关链接 → 转发块（纯文本，渲染前统一转义，避免 XSS）
    forward: ForwardPayload | None = None
    if related:
        related_lines: list[str] = []
        for related_item in related:
            if not isinstance(related_item, dict):
                continue
            related_title = _as_str(related_item.get("title"))
            related_url = _as_str(related_item.get("url"))
            if related_title and related_url:
                related_lines.append(f"{related_title} · {related_url}")
            elif related_title or related_url:
                related_lines.append(related_title or related_url)
        if related_lines:
            forward = ForwardPayload(name="相关链接", text="\n".join(related_lines))
    payload.forward = forward

    # 统计栏：标量统计 + 未知键通用条目
    payload.stats = {
        key: value
        for key, value in stats_raw.items()
        if not isinstance(value, (dict, list))
    }
    payload.stats_extra_items = [
        {"label": _as_str(key), "value": value}
        for key, value in payload.stats.items()
        if key not in _KNOWN_STAT_KEYS
    ]

    # 平台主题色 / 页脚
    color = PLATFORM_COLORS.get(platform, UNKNOWN_PLATFORM_COLOR)
    rgb = _hex_to_rgb(color)
    payload.platform_color = color
    payload.platform_color_rgb = f"{rgb[0]},{rgb[1]},{rgb[2]}"
    payload.platform_color_dark = _rgb_to_hex(_darken(rgb))
    payload.platform_color_light = _rgb_to_hex(_lighten(rgb))
    payload.platform_official_name = PLATFORM_OFFICIAL_NAMES.get(platform) or (
        platform.capitalize() if platform else ""
    )
    payload.platform_footer_label = _PLATFORM_FOOTER_LABELS.get(
        platform,
        payload.platform_official_name,
    )
    payload.platform_logo_svg = _load_icon_asset(_PLATFORM_LOGO_FILES.get(platform, ""))
    return payload


# ==================== 渲染 ====================
def _build_qr_data_url(url: str) -> str:
    """生成链接 QR 码；生成失败时返回空串（区块整体隐藏）。"""
    if not url:
        return ""
    try:
        import qrcode
    except Exception:  # noqa: BLE001 - qrcode 不可用时隐藏 QR 区块，不阻断卡片渲染。
        return ""
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=3,
        )
        qr.add_data(url)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:  # noqa: BLE001 - QR 生成失败时隐藏 QR 区块，不阻断卡片渲染。
        return ""


def _coerce_field(field_name: str, value: Any, current: Any) -> Any:
    if field_name == "forward":
        if isinstance(value, (ForwardPayload, dict)):
            return value
        return current
    if isinstance(current, str):
        return _as_str(value)
    if isinstance(current, int):
        return _as_int(value, current)
    if isinstance(current, float):
        return _as_float(value, current)
    if isinstance(current, list):
        return list(value) if isinstance(value, (list, tuple)) else current
    if isinstance(current, dict):
        return _as_dict(value)
    return value if value is not None else current


def _render_payload_from_data(data: dict[str, Any]) -> RenderPayload:
    """任意部分字典 → 完整 RenderPayload。

    先按 PlatformParse 字段映射（page_type/badge/detail 等），再允许
    RenderPayload 风格的显式字段覆盖，二者幂等。
    """
    payload = parse_to_render_payload(data)
    render_fields = {field.name for field in fields(RenderPayload)}
    for key, value in data.items():
        if key in render_fields and value is not None:
            setattr(
                payload,
                key,
                _coerce_field(key, value, getattr(payload, key)),
            )
    return payload


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_RGB_TRIPLET_RE = re.compile(r"^\d{1,3},\s*\d{1,3},\s*\d{1,3}$")


def _safe_css_color(value: Any, fallback: str) -> str:
    """CSS 变量语境只接受 #RRGGBB；非法值（含 CSS 注入载荷）回退中性色。"""
    text = _as_str(value).strip()
    return text if _HEX_COLOR_RE.match(text) else fallback


def _safe_css_rgb(value: Any, fallback: str) -> str:
    text = _as_str(value).strip()
    return text if _RGB_TRIPLET_RE.match(text) else fallback


# data: URL 白名单（评审 M25）：只放行「base64 图片」这一种形态。旧实现在
# data: 分支**原样返回**，而 base64 字符集之外的内容（引号、括号、分号）可以
# 从 `style="background-image:url('{{ banner }}')"` 逃逸出新 CSS 声明——Jinja
# 的 autoescape 只把 `'` 变成 `&#39;`，浏览器解码后照样交给 CSS 解析器。
# 非白名单形态一律返回空串（模板侧表现为无图，安全侧倾斜）。
_CSS_DATA_URL_RE = re.compile(
    r"^data:image/(?:png|jpe?g|gif|webp|bmp|avif);base64,[A-Za-z0-9+/]+={0,2}$",
    re.IGNORECASE,
)


def _css_url_token(url: Any) -> str:
    """CSS url('...') 语境安全化：仅放行 base64 图片 data URL，其余 URL 百分号
    编码，阻断 `') 形式的样式注入。"""
    text = _as_str(url).strip()
    if not text:
        return text
    if text.startswith("data:"):
        return text if _CSS_DATA_URL_RE.match(text) else ""
    return urllib.parse.quote(text, safe=":/?&=%")


def render_universal_card_html(payload_dict: dict[str, Any] | None = None) -> str:
    """渲染通用卡片 HTML。

    payload_dict 可为：
    - card_payload_from_parse 的输出（page_type/badge/detail 等）；
    - 部分 RenderPayload 风格字典；
    - 空字典 / None（渲染一张空卡片）。

    所有顶层变量都有默认值，因此缺字段只会隐藏区块，不会抛异常。
    """
    data = dict(payload_dict or {})
    payload = _render_payload_from_data(data)

    # 显式覆盖后重新归一化统计字段，保证只渲染标量且通用条目同步。
    payload.stats = {
        key: value
        for key, value in payload.stats.items()
        if not isinstance(value, (dict, list))
    }
    payload.stats_extra_items = [
        {"label": _as_str(key), "value": value}
        for key, value in payload.stats.items()
        if key not in _KNOWN_STAT_KEYS
    ]

    # 模板对 text/summary/forward.text 使用 | safe，这里先统一转义防注入；
    # 同时去掉 时长/发布时间 行与“简介：”前缀，简介只留博主原文。
    payload.text = html.escape(_clean_card_summary(_as_str(payload.text)))
    payload.summary = html.escape(_clean_card_summary(_as_str(payload.summary)))
    if isinstance(payload.forward, ForwardPayload):
        payload.forward.text = html.escape(_as_str(payload.forward.text))
    elif isinstance(payload.forward, dict):
        payload.forward = dict(payload.forward)
        payload.forward["text"] = html.escape(_as_str(payload.forward.get("text")))
    # repost.text 走模板 |safe，逐字段预转义（对纯文本内容渲染产物零变化）。
    repost = payload.repost
    if isinstance(repost, dict):
        escaped_repost = dict(repost)
        escaped_repost["text"] = html.escape(_as_str(escaped_repost.get("text")))
        payload.repost = escaped_repost
    elif repost is not None and isinstance(getattr(repost, "text", None), str):
        try:
            repost.text = html.escape(repost.text)
        except AttributeError:
            pass

    # 平台色与横幅图进入 CSS 语境前做格式校验/编码，阻断样式注入。
    payload.platform_color = _safe_css_color(
        payload.platform_color, UNKNOWN_PLATFORM_COLOR
    )
    payload.platform_color_dark = _safe_css_color(
        payload.platform_color_dark, UNKNOWN_PLATFORM_COLOR
    )
    payload.platform_color_light = _safe_css_color(
        payload.platform_color_light, UNKNOWN_PLATFORM_COLOR
    )
    payload.platform_color_rgb = _safe_css_rgb(payload.platform_color_rgb, "96,112,128")
    payload.banner = _css_url_token(payload.banner)
    payload.cover_url = _css_url_token(payload.cover_url)

    # 可选 QR：优先调用方给的 qrcode，其次尝试生成；缺依赖则隐藏。
    if not _as_str(payload.qrcode) and _as_str(payload.url):
        payload.qrcode = _build_qr_data_url(_as_str(payload.url))

    context = dict(_DEFAULT_CONTEXT)
    context.update(payload.to_dict())
    # 釉瑚云母洗：与 --pc 同点注入（mica-glass v1 2026-09-12，工艺出处=用户裁定）。
    context.update(_derive_wash_tokens(payload.platform_color))
    return _TEMPLATE.render(**context)


def _song_candidates_platform_color(platform: str) -> str:
    """候选卡平台色：先精确匹配，再包含关系回退（netease_music→netease）。"""
    color = PLATFORM_COLORS.get(platform)
    if color is not None:
        return color
    matches = [
        (key, value)
        for key, value in PLATFORM_COLORS.items()
        if key and key in platform
    ]
    if matches:
        return max(matches, key=lambda item: len(item[0]))[1]
    return UNKNOWN_PLATFORM_COLOR


# ==================== 全球股指卡（F19 2026-09-12） ====================
_MARKET_CARD_TEMPLATE = _ENV.get_template("market_card.html")


def _spark_points(closes: Any) -> tuple[str, str]:
    """收盘序列（旧→新）→ SVG polyline points + 涨跌描边色（红涨绿跌）。

    点位不足 2 个返回 ("", "")（模板隐藏折线）；任何输入异常同样静默。
    """
    try:
        values = [float(v) for v in (closes or [])]
    except (TypeError, ValueError):
        return "", ""
    if len(values) < 2:
        return "", ""
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    width, height = 128.0, 40.0
    step = width / (len(values) - 1)
    points = " ".join(
        f"{index * step:.1f},{height - (value - low) / span * (height - 4) - 2:.1f}"
        for index, value in enumerate(values)
    )
    color = "#d54941" if values[-1] >= values[0] else "#2e9e6b"
    return points, color


def render_market_card_html(payload_dict: dict[str, Any] | None = None) -> str:
    """渲染全球股指卡 HTML（mica-glass 规范，F19）。

    payload_dict 字段：subtitle、groups=[{name, rows=[{name, price, pct, cls,
    trend=[float,...]}]}]、platform_color、bot_name、bot_avatar_url、
    feature_label。折线由 trend 收盘序列在此生成 polyline points；
    缺数据区块静默隐藏，不抛异常。
    """
    data = dict(payload_dict or {})
    color = _safe_css_color(
        _as_str(data.get("platform_color")) or UNKNOWN_PLATFORM_COLOR,
        UNKNOWN_PLATFORM_COLOR,
    )
    rgb = _hex_to_rgb(color)
    groups_out: list[dict[str, Any]] = []
    for group in _as_list(data.get("groups")):
        if not isinstance(group, dict):
            continue
        rows_out: list[dict[str, Any]] = []
        for row in _as_list(group.get("rows")):
            if not isinstance(row, dict):
                continue
            points, spark_color = _spark_points(row.get("trend"))
            change = _as_float(row.get("change_pct"), 0.0)
            rows_out.append(
                {
                    "name": _as_str(row.get("name")) or "指数",
                    "price": _as_str(row.get("price")),
                    "pct": _as_str(row.get("pct")),
                    "cls": (
                        "up" if change > 0 else ("down" if change < 0 else "flat")
                    ),
                    "spark_points": points,
                    "spark_color": spark_color,
                }
            )
        if rows_out:
            groups_out.append({"name": _as_str(group.get("name")), "rows": rows_out})
    return _MARKET_CARD_TEMPLATE.render(
        platform_color=color,
        platform_color_dark=_rgb_to_hex(_darken(rgb)),
        subtitle=_as_str(data.get("subtitle")),
        groups=groups_out,
        bot_name=_as_str(data.get("bot_name")) or "守岸人",
        bot_avatar_url=_as_str(data.get("bot_avatar_url")),
        feature_label=_as_str(data.get("feature_label")) or "全球股指",
        # 釉瑚云母洗：与 --pc 同点注入（mica-glass v2 本命基底）。
        **_derive_wash_tokens(color),
    )


def render_song_candidates_html(payload_dict: dict[str, Any] | None = None) -> str:
    """渲染点歌多候选选择卡 HTML（Mica 规范）。

    payload_dict 字段：query、platform、platform_name、ttl_seconds、
    candidates=[{index, name, artist, album}, ...]。
    颜色派生复用 PLATFORM_COLORS（精确匹配→包含回退→中性灰），
    artist/album 缺省段静默省略，任何字段缺失都不抛异常。
    """
    data = dict(payload_dict or {})
    platform = _as_str(data.get("platform")).lower()
    color = _song_candidates_platform_color(platform)
    rgb = _hex_to_rgb(color)

    candidates_raw = _as_list(data.get("candidates"))
    candidates: list[dict[str, Any]] = []
    for offset, cand in enumerate(candidates_raw, start=1):
        if not isinstance(cand, dict):
            continue
        index = _as_int(cand.get("index"), offset) or offset
        candidates.append(
            {
                "index": index,
                "index_label": f"{index:02d}",
                "name": _as_str(cand.get("name")) or "未知歌曲",
                "artist": _as_str(cand.get("artist")),
                "album": _as_str(cand.get("album")),
                "is_top": index <= 3,
            }
        )

    template = _ENV.get_template("song_candidates.html")
    return template.render(
        query=_as_str(data.get("query")) or "未知关键词",
        platform=platform,
        platform_name=_as_str(data.get("platform_name"))
        or PLATFORM_OFFICIAL_NAMES.get(platform)
        or (platform.capitalize() if platform else ""),
        platform_color=color,
        platform_color_rgb=f"{rgb[0]},{rgb[1]},{rgb[2]}",
        platform_color_dark=_rgb_to_hex(_darken(rgb)),
        platform_color_light=_rgb_to_hex(_lighten(rgb)),
        ttl_seconds=_as_int(data.get("ttl_seconds"), 300),
        candidates=candidates,
        bot_name=_as_str(data.get("bot_name")) or "守岸人",
        bot_avatar_url=_as_str(data.get("bot_avatar_url")),
        feature_label=_as_str(data.get("feature_label")) or "点歌",
        # 釉瑚云母洗：与 --pc 同点注入（mica-glass v1 2026-09-12）。
        **_derive_wash_tokens(color),
    )


def render_affinity_card_html(payload_dict: dict[str, Any] | None = None) -> str:
    """渲染好感度卡 HTML（Mica 规范，docs/affinity-design.md §9.5）。

    payload_dict 分支字段：mode="group"（rows=[{sender_id, display_name,
    score, tier}]、me_id）与 mode="private"（bot_to_user / user_to_bot =
    {score, tier, bar}、rules=[...]、bot_name）。主色 pc 无平台语境，取
    bot_help_card_color 同源配置，缺省回 UNKNOWN_PLATFORM_COLOR 中性灰。
    任何字段缺失都有默认值，不抛异常。
    """
    data = dict(payload_dict or {})
    template = _ENV.get_template("affinity_card.html")
    pc = _as_str(data.get("pc")) or UNKNOWN_PLATFORM_COLOR
    return template.render(
        pc=pc,
        # 釉瑚云母洗：与 --pc 同点注入（mica-glass v1 2026-09-12）。
        **_derive_wash_tokens(pc),
        title=_as_str(data.get("title")) or "好感度",
        subtitle=_as_str(data.get("subtitle")),
        mode=_as_str(data.get("mode")) or "private",
        me_id=_as_str(data.get("me_id")),
        bot_name=_as_str(data.get("bot_name")) or "守岸人",
        bot_avatar_url=_as_str(data.get("bot_avatar_url")),
        feature_label=_as_str(data.get("feature_label")) or "好感度",
        bot_score=_as_str(data.get("bot_score")) or "10.0",
        rows=[row for row in (data.get("rows") or []) if isinstance(row, dict)],
        steps=[row for row in (data.get("steps") or []) if isinstance(row, dict)],
        tiers=[row for row in (data.get("tiers") or []) if isinstance(row, dict)],
        bot_to_user=data.get("bot_to_user") or {"score": 50.0, "tier": "友善", "bar": 50.0},
        user_to_bot=data.get("user_to_bot") or {"score": 50.0, "tier": "友善", "bar": 50.0},
        rules=[rule for rule in (data.get("rules") or []) if isinstance(rule, dict)],
    )


# ==================== Mermaid 流程图卡（G-MERMAID） ====================
_MERMAID_TEMPLATE = _ENV.get_template("mermaid_card.html")
# 等待条件：.card 里出现 SVG 且不是 mermaid 的语法错误弹窗（error bomb）。
# 脚本加载失败（无网）时条件永不成立，由 wait_js 超时兜底返回 None。
_MERMAID_READY_JS = (
    "() => {"
    " const svg = document.querySelector('.card svg');"
    " if (!svg) { return false; }"
    " return (svg.textContent || '').toLowerCase().indexOf('syntax error') === -1;"
    "}"
)
# 渲染后端单例：None=未初始化，False=已探测到不可用（不重复探测）。
_MERMAID_BACKEND: Any = None
_MERMAID_BACKEND_LOCK = threading.Lock()


def _get_mermaid_backend() -> Any:
    """懒初始化 mermaid 专用截图后端；仅接受 playwright（需要 wait_js）。"""
    global _MERMAID_BACKEND
    with _MERMAID_BACKEND_LOCK:
        if _MERMAID_BACKEND is None:
            backend = build_render_backend("auto")
            _MERMAID_BACKEND = (
                backend
                if getattr(backend, "available", False)
                and getattr(backend, "name", "") == "playwright"
                else False
            )
        return _MERMAID_BACKEND or None


def render_mermaid_html(code: str) -> str:
    """渲染 mermaid 流程图卡 HTML（Mica 规范）。

    code 经 Jinja2 autoescape 转义后注入 <pre class="mermaid">，页面内
    从 jsDelivr CDN 加载 mermaid.min.js 并 startOnLoad 自动出图。
    纯字符串组装，不访问网络，不抛异常；釉瑚云母洗按中性灰派生注入
    （mica-glass v1 2026-09-12）。
    """
    return _MERMAID_TEMPLATE.render(
        code=code or "",
        bot_name="守岸人",
        feature_label="流程图",
        **_derive_wash_tokens(UNKNOWN_PLATFORM_COLOR),
    )


def render_mermaid_png(code: str) -> bytes | None:
    """mermaid 源码 → PNG 字节；任何失败（无网/超时/后端缺失/异常）返回 None。

    走 render_backends 既有截图入口（PlaywrightRenderBackend.render_card），
    通过 wait_js 在截图前等 SVG 真正出现（上限 6s）。
    """
    if not (code or "").strip():
        return None
    try:
        backend = _get_mermaid_backend()
        if backend is None:
            return None
        return backend.render_card(
            {
                "html": render_mermaid_html(code),
                "viewport": {"width": 840, "height": 640},
                "wait_ms": 120,
                "wait_js": _MERMAID_READY_JS,
                "wait_js_timeout_ms": 6000,
            }
        )
    except Exception:  # noqa: BLE001 - mermaid 渲染绝不抛异常，失败降级文本。
        return None


__all__ = [
    "PLATFORM_COLORS",
    "PLATFORM_OFFICIAL_NAMES",
    "ForwardPayload",
    "RenderPayload",
    "flat_projection",
    "parse_to_render_payload",
    "render_affinity_card_html",
    "render_mermaid_html",
    "render_mermaid_png",
    "render_song_candidates_html",
    "render_universal_card_html",
]

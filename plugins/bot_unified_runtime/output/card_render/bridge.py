"""通用卡片渲染桥接。

移植并适配自 astrbot_plugin_parser core/render_html/bridge.py
（https://github.com/Zhalslar/astrbot_plugin_parser，MIT License，
Copyright (c) 2024 Les Freire）。

职责：
- parse_to_render_payload(item)：把 PlatformParse（含可选 page_type/badge/
  detail）转换为字段完整的 RenderPayload；
- render_universal_card_html(payload_dict)：合并默认值并用 Jinja2 渲染模板，
  所有顶层变量都有默认值，字段缺失时对应区块整体隐藏；
- QR 码仅在 import qrcode 成功时生成，不新增依赖。
"""

from __future__ import annotations

import base64
import html
import io
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any

import jinja2

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
}
UNKNOWN_PLATFORM_COLOR = "#607080"

PLATFORM_OFFICIAL_NAMES: dict[str, str] = {
    "bilibili": "Bilibili",
    "xiaohongshu": "Xiaohongshu",
    "xhs": "Xiaohongshu",
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
    "generic": "Web",
}

# 模板“已知键”特殊标签已覆盖的统计键（其余走通用遍历）。
_KNOWN_STAT_KEYS = frozenset({
    "views", "danmaku", "likes", "favorites", "coins", "comments", "reposts",
    "following", "followers", "user_likes", "total_views", "quotes", "bookmarks",
    "attention", "fansclub", "high_energy_users", "fleet_total", "captain",
    "admiral", "governor", "is_living", "live_level", "top3_rank", "live_viewers",
    "live_rank", "live_watched", "live_popularity", "official_title",
    # 中文键已由 bridge 提炼到直播间字段，避免重复展示。
    "观看", "在线", "人气",
})

_DEFAULT_CONTEXT = RenderPayload().to_dict()


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


def _first_stat_value(stats: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = stats.get(key)
        if value is not None and value != "":
            return value
    return None


def _first_stat_int(stats: dict[str, Any], keys: tuple[str, ...]) -> int:
    return _as_int(_first_stat_value(stats, keys))


def _format_timestamp(value: Any) -> str:
    text = _as_str(value)
    if not text:
        return ""
    if text.isdigit() and len(text) >= 10:
        try:
            return datetime.fromtimestamp(int(text)).strftime("%Y-%m-%d %H:%M:%S")
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


def parse_to_render_payload(item: Any) -> RenderPayload:
    """把 PlatformParse（或等价字典）映射为字段完整的 RenderPayload。

    契约中的 page_type/badge/detail 全部可选；缺省时返回一张空但可渲染的
    卡片（各区块隐藏）。
    """
    platform = _as_str(_get(item, "platform")).strip().lower()
    kind = _as_str(_get(item, "item_kind")).strip().lower()
    page_type = _as_str(_get(item, "page_type")).strip().lower() or kind
    badge = _as_str(_get(item, "badge")).strip()
    item_id = _as_str(_get(item, "item_id")).strip()
    title = _as_str(_get(item, "title")).strip()
    summary = _as_str(_get(item, "summary"))
    cover = _as_str(_get(item, "cover_url"))
    canonical = _as_str(_get(item, "canonical_url"))

    stats_raw = _as_dict(_get(item, "stats"))
    detail = _as_dict(_get(item, "detail"))
    author = _as_dict(detail.get("author"))
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

    # 作者
    payload.name = _as_str(author.get("name")) or _as_str(_get(item, "author_name"))
    payload.avatar = _as_str(author.get("avatar"))
    payload.signature = _as_str(author.get("signature"))
    payload.follower_count = _as_str(author.get("fans"))
    payload.official_title = _as_str(author.get("official_title"))
    payload.official_badge = badge or _as_str(detail.get("badge"))

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

    # 正文 / 图片 / 横幅
    payload.banner = (
        _as_str(live.get("keyframe"))
        or _as_str(live.get("cover"))
        or cover
    )
    payload.image_urls = [_as_str(url) for url in images if _as_str(url)]

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

    # 博主结构化数据（视频/空间解析带上的 粉丝/关注/视频数/专栏数）
    for label, key in (("粉丝", "粉丝"), ("关注", "关注"), ("视频数", "视频数"), ("专栏数", "专栏数")):
        value = _first_stat_value(stats_raw, (key,))
        if value not in (None, ""):
            payload.header_l4_items.append({"label": label, "value": value})

    # 第二行：视频ID / 动态ID / 番剧ID / 商品ID
    if kind == "dynamic":
        payload.header_l2_items.append({"label": "动态ID", "value": item_id})
    elif kind == "bangumi":
        payload.header_l2_items.append({"label": "番剧ID", "value": item_id})
    elif kind in {"goods", "ticket", "mall"}:
        payload.header_l2_items.append({"label": "商品ID", "value": item_id})
    elif platform == "bilibili" and item_id.upper().startswith("BV"):
        payload.header_l2_items.append({"label": "视频ID", "value": item_id})
    elif platform == "bilibili" and item_id.lower().startswith("av"):
        payload.header_l2_items.append({"label": "视频ID", "value": item_id})

    # 发布时间：精确到年月日时分秒
    pub_raw = _first_stat_value(stats_raw, ("pubdate", "发布时间", "pub_time"))
    if pub_raw is not None:
        payload.timestamp = _format_timestamp(pub_raw)

    # 视频时长 / 简介（从 stats 的常见键提炼）
    duration_raw = _first_stat_value(stats_raw, ("duration", "duration_seconds", "时长"))
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
    payload.timestamp = _format_timestamp(live.get("start_time"))
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
    return payload


# ==================== 渲染 ====================
def _build_qr_data_url(url: str) -> str:
    """可选 QR 码：qrcode 未安装或生成失败时返回空串（区块整体隐藏）。"""
    if not url:
        return ""
    try:
        import qrcode
    except Exception:
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
    except Exception:
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

    # 模板对 text/summary/forward.text 使用 | safe，这里先统一转义防注入。
    payload.text = html.escape(_as_str(payload.text))
    payload.summary = html.escape(_as_str(payload.summary))
    if isinstance(payload.forward, ForwardPayload):
        payload.forward.text = html.escape(_as_str(payload.forward.text))
    elif isinstance(payload.forward, dict):
        payload.forward = dict(payload.forward)
        payload.forward["text"] = html.escape(_as_str(payload.forward.get("text")))

    # 可选 QR：优先调用方给的 qrcode，其次尝试生成；缺依赖则隐藏。
    if not _as_str(payload.qrcode) and _as_str(payload.url):
        payload.qrcode = _build_qr_data_url(_as_str(payload.url))

    context = dict(_DEFAULT_CONTEXT)
    context.update(payload.to_dict())
    return _TEMPLATE.render(**context)


__all__ = [
    "PLATFORM_COLORS",
    "PLATFORM_OFFICIAL_NAMES",
    "RenderPayload",
    "ForwardPayload",
    "parse_to_render_payload",
    "render_universal_card_html",
]

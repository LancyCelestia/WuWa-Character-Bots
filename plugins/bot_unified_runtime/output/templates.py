"""HTML 卡片模板：把解析结果渲染成可截图的信息卡 HTML。

模板只做展示，不决定发送；所有字段都经 html.escape 防注入。
"""

from __future__ import annotations

import html
from typing import Any

from plugins.bot_unified_runtime.output.card_render.bridge import (
    flat_projection as _flat_projection,
)
from plugins.bot_unified_runtime.output.card_render.bridge import (
    parse_to_render_payload as _parse_to_render_payload,
)
from plugins.bot_unified_runtime.output.card_render.bridge import (
    render_universal_card_html as _render_universal_card_html,
)

_CARD_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  background: transparent;
  display: flex; align-items: flex-start; justify-content: center;
  padding: 0;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
/* 截图容器：透明留白承载柔光阴影（.card 即渲染选择器）。 */
.card {
  width: auto; background: transparent; border: 0; border-radius: 0;
  box-shadow: none; padding: 24px;
}
:root { --pc: __PC__; --pc-dark: __PC_DARK__; --pc-rgb: __PC_RGB__; }
.panel {
  width: 640px;
  background: color-mix(in srgb, var(--pc) 5%, #ffffff);
  border-radius: 18px; overflow: hidden;
  box-shadow: 0 12px 32px rgba(31, 35, 41, 0.10), 0 2px 8px rgba(31, 35, 41, 0.05);
  border: 1px solid color-mix(in srgb, var(--pc) 14%, #e4e6eb);
}
.cover-wrap { position: relative; width: 100%; height: 240px;
  background: linear-gradient(135deg, color-mix(in srgb, var(--pc) 10%, #ffffff) 0%, color-mix(in srgb, var(--pc) 18%, #ffffff) 100%); }
.cover-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cover-fallback { position: absolute; inset: 0; display: flex;
  align-items: center; justify-content: center; font-size: 44px; color: var(--pc); }
.badge { position: absolute; left: 12px; top: 12px; background: rgba(38,46,56,.75);
  color: #fff; font-size: 12px; padding: 3px 10px; border-radius: 999px; }
.body { padding: 14px 18px 16px; }
.title { font-size: 19px; font-weight: 700; color: #2b3440; line-height: 1.4; }
.author { margin-top: 6px; font-size: 13px; color: #66727f; }
.stats { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
.stat { background: color-mix(in srgb, var(--pc) 10%, #ffffff); color: var(--pc-dark);
  font-size: 12px; padding: 3px 9px; border-radius: 999px; }
.summary { margin-top: 10px; font-size: 13px; color: #4a5560;
  line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.footer { margin-top: 10px; font-size: 11px; color: #7a8699;
  border-top: 1px dashed color-mix(in srgb, var(--pc) 12%, #e4e6eb); padding-top: 8px; }
"""


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def render_media_card_html(payload: dict[str, Any]) -> str:
    """结构化 payload → 信息卡 HTML。

    payload 字段：title, platform, author, cover_url, stats{label:value},
    summary（多行文本）, footer。
    """
    title = _esc(payload.get("title")) or "未命名内容"
    platform = _esc(payload.get("platform")) or ""
    author = _esc(payload.get("author")) or ""
    cover = _esc(payload.get("cover_url")) or ""
    stats = payload.get("stats") or {}
    summary = _esc(payload.get("summary")) or ""
    footer = _esc(payload.get("footer")) or ""
    pc = _esc(payload.get("platform_color")) or "#607080"
    pc_dark = _esc(payload.get("platform_color_dark")) or "#4a5866"
    pc_rgb = _esc(payload.get("platform_color_rgb")) or "96,112,128"
    css = (
        _CARD_CSS
        .replace("__PC__", pc)
        .replace("__PC_DARK__", pc_dark)
        .replace("__PC_RGB__", pc_rgb)
    )

    cover_block = ""
    if cover:
        cover_block = (
            f'<img src="{cover}" '
            'onerror="this.style.display=\'none\'" alt="cover"/>'
        )
    stats_html = "".join(
        f'<span class="stat">{_esc(label)} {_esc(value)}</span>'
        for label, value in stats.items()
        if not isinstance(value, (dict, list))
    )
    return (
        "<html><head><meta charset=\"utf-8\"><style>"
        f"{css}</style></head><body><div class=\"card\"><div class=\"panel\">"
        f'<div class="cover-wrap">{cover_block}'
        f'<div class="badge">{platform}</div>'
        '<div class="cover-fallback">🖼</div></div>'
        f'<div class="body"><div class="title">{title}</div>'
        + (f'<div class="author">{author}</div>' if author else "")
        + (f'<div class="stats">{stats_html}</div>' if stats_html else "")
        + (f'<div class="summary">{summary}</div>' if summary else "")
        + (f'<div class="footer">{footer}</div>' if footer else "")
        + "</div></div></div></body></html>"
    )


def card_payload_from_parse(item: Any) -> dict[str, Any]:
    """ParsedContent → 卡片 payload（与内容能力共用）。

    保留旧媒体卡字段（title/platform/author/cover_url/stats/summary/footer），
    同时补充通用卡片需要的 page_type/badge/detail 与作者映射；detail 缺失时
    通用卡片各区块自动隐藏。嵌套模型先经 bridge 渲染投影还原。
    """
    payload = _parse_to_render_payload(item).to_dict()
    flat = _flat_projection(item)
    flat = flat if isinstance(flat, dict) else {}
    payload.update(
        {
            "title": flat.get("title") or payload.get("title", ""),
            "platform": flat.get("platform", ""),
            "author": flat.get("author_name", ""),
            "cover_url": flat.get("cover_url", ""),
            "summary": flat.get("summary", ""),
            "footer": flat.get("canonical_url", ""),
            "page_type": flat.get("page_type") or flat.get("item_kind", ""),
            "badge": flat.get("badge", ""),
            "detail": flat.get("detail", {}),
        }
    )
    return payload


def render_universal_card_html(payload: dict[str, Any]) -> str:
    """渲染通用卡片 HTML（card_render.bridge 的转发入口）。"""
    return _render_universal_card_html(payload)

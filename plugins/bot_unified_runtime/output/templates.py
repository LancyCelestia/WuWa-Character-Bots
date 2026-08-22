"""HTML 卡片模板：把解析结果渲染成可截图的信息卡 HTML。

模板只做展示，不决定发送；所有字段都经 html.escape 防注入。
"""

from __future__ import annotations

import html
from typing import Any

_CARD_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  background: #f3f6fb;
  display: flex; align-items: flex-start; justify-content: center;
  padding: 16px;
}
.card {
  width: 640px; background: #ffffff; border-radius: 14px; overflow: hidden;
  box-shadow: 0 6px 24px rgba(38, 56, 86, 0.12);
  border: 1px solid #e3e9f2;
}
.cover-wrap { position: relative; width: 100%; height: 240px;
  background: linear-gradient(135deg, #dbe7ff 0%, #e9d8ff 100%); }
.cover-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cover-fallback { position: absolute; inset: 0; display: flex;
  align-items: center; justify-content: center; font-size: 44px; color: #8ea4cc; }
.badge { position: absolute; left: 12px; top: 12px; background: rgba(24,33,64,.78);
  color: #fff; font-size: 12px; padding: 3px 10px; border-radius: 999px; }
.body { padding: 14px 18px 16px; }
.title { font-size: 19px; font-weight: 700; color: #17233d; line-height: 1.4; }
.author { margin-top: 6px; font-size: 13px; color: #5a6b8c; }
.stats { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
.stat { background: #eef3fb; color: #3b537e; font-size: 12px;
  padding: 3px 9px; border-radius: 999px; }
.summary { margin-top: 10px; font-size: 13px; color: #41506e;
  line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.footer { margin-top: 10px; font-size: 11px; color: #93a2bf;
  border-top: 1px dashed #e3e9f2; padding-top: 8px; }
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
        f"{_CARD_CSS}</style></head><body><div class=\"card\">"
        f'<div class="cover-wrap">{cover_block}'
        f'<div class="badge">{platform}</div>'
        '<div class="cover-fallback">🖼</div></div>'
        f'<div class="body"><div class="title">{title}</div>'
        + (f'<div class="author">{author}</div>' if author else "")
        + (f'<div class="stats">{stats_html}</div>' if stats_html else "")
        + (f'<div class="summary">{summary}</div>' if summary else "")
        + (f'<div class="footer">{footer}</div>' if footer else "")
        + "</div></div></body></html>"
    )


def card_payload_from_parse(item: Any) -> dict[str, Any]:
    """PlatformParse → 卡片 payload（与内容能力共用）。"""
    return {
        "title": getattr(item, "title", ""),
        "platform": getattr(item, "platform", ""),
        "author": getattr(item, "author_name", ""),
        "cover_url": getattr(item, "cover_url", ""),
        "stats": dict(getattr(item, "stats", {}) or {}),
        "summary": getattr(item, "summary", ""),
        "footer": getattr(item, "canonical_url", ""),
    }

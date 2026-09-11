"""HTML 卡片模板：把解析结果渲染成可截图的信息卡 HTML。

模板只做展示，不决定发送；所有字段都经 html.escape 防注入。
mica-glass v1 2026-09-12：视觉层统一「釉瑚云母 + 液态玻璃 + 渐变漂移」——
底色/色斑用 bridge._derive_wash_tokens 按 --pc 派生的釉瑚洗（__WASH_*__ 注入，
禁纯色），--pc 退为徽章/高亮 accent；半透明白玻璃面板 + 1px 内高光渐变描边、
三枚柔光色斑缓慢漂移 + 内联脚本随机相位（零外部依赖，失败静默）；
数据绑定与 __PC__ 注入契约不变。
"""

from __future__ import annotations

import html
from typing import Any

from plugins.bot_unified_runtime.output.card_render.bridge import (
    _derive_wash_tokens,
)
from plugins.bot_unified_runtime.output.card_render.bridge import (
    flat_projection as _flat_projection,
)
from plugins.bot_unified_runtime.output.card_render.bridge import (
    parse_to_render_payload as _parse_to_render_payload,
)
from plugins.bot_unified_runtime.output.card_render.bridge import (
    render_song_candidates_html as _render_song_candidates_html,
)
from plugins.bot_unified_runtime.output.card_render.bridge import (
    render_universal_card_html as _render_universal_card_html,
)

# mica-glass v1 2026-09-12：随机漂移相位脚本（纯内联零依赖，失败静默回落 CSS 默认值）。
_PHASE_JS = (
    '<script>try{document.documentElement.style.setProperty("--phase",'
    "Math.random().toFixed(4));}catch(e){}</script>"
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
:root { --phase: 0.2; --pc: __PC__; --pc-dark: __PC_DARK__; --pc-rgb: __PC_RGB__;
  /* 釉瑚云母底主题 token，全卡统一（bridge 按 --pc 派生注入；工艺出处=用户裁定）。 */
  --wash-1: __WASH_1__; --wash-2: __WASH_2__; --wash-3: __WASH_3__; --wash-mist: __WASH_MIST__;
  --wash-blob-1: color-mix(in srgb, var(--pc) 14%, var(--wash-1)); }
/* mica-glass：釉瑚云母外壳（雾底打底、wash-1/2 对角透色、wash-3 只作第三色透底，
   不透明基础层）+ 1px 内高光渐变描边；色斑垫底、内容抬升；
   阴影只允许两枚 token。 */
.panel {
  position: relative;
  width: 640px;
  border-radius: 18px; overflow: hidden;
  border: 1px solid transparent;
  background:
    linear-gradient(145deg, var(--wash-mist) 0%,
      color-mix(in srgb, var(--wash-1) 55%, var(--wash-mist)) 30%,
      color-mix(in srgb, var(--wash-2) 48%, var(--wash-mist)) 64%,
      color-mix(in srgb, var(--wash-3) 40%, var(--wash-mist)) 100%) padding-box,
    linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%,
      rgba(255,255,255,.72) 100%) border-box;
  box-shadow: 0 12px 32px rgba(31, 35, 41, 0.10), 0 2px 8px rgba(31, 35, 41, 0.05);
}
.panel > :not(.drift-blobs) { position: relative; z-index: 1; }
/* 渐变漂移色斑（wash 三色半透明互相透过，46s/52s/58s 交错漂移+呼吸）。 */
.drift-blobs { position: absolute; inset: 0; z-index: 0; overflow: hidden;
  pointer-events: none; border-radius: inherit; }
.drift-blob { position: absolute; display: block; border-radius: 50%; will-change: transform; }
.drift-blob.drift-a {
  width: 58%; aspect-ratio: 1; left: -14%; top: -22%;
  background: radial-gradient(closest-side,
    color-mix(in srgb, var(--wash-blob-1) 34%, transparent) 0%,
    color-mix(in srgb, var(--wash-blob-1) 18%, transparent) 46%,
    color-mix(in srgb, var(--wash-blob-1) 5%, transparent) 70%, transparent 100%);
  animation: mica-drift-a 46s ease-in-out infinite alternate;
  animation-delay: calc(var(--phase, 0.2) * -46s);
}
.drift-blob.drift-b {
  width: 52%; aspect-ratio: 1; right: -16%; bottom: -24%;
  background: radial-gradient(closest-side,
    color-mix(in srgb, var(--wash-2) 30%, transparent) 0%,
    color-mix(in srgb, var(--wash-2) 16%, transparent) 48%,
    color-mix(in srgb, var(--wash-2) 5%, transparent) 72%, transparent 100%);
  animation: mica-drift-b 58s ease-in-out infinite alternate;
  animation-delay: calc(var(--phase, 0.2) * -58s - 9s);
}
.drift-blob.drift-c {
  width: 64%; aspect-ratio: 1; left: 22%; top: 34%;
  background: radial-gradient(closest-side,
    color-mix(in srgb, var(--wash-3) 26%, transparent) 0%,
    color-mix(in srgb, var(--wash-3) 14%, transparent) 48%,
    color-mix(in srgb, var(--wash-3) 5%, transparent) 72%, transparent 100%);
  animation: mica-drift-c 52s ease-in-out infinite alternate;
  animation-delay: calc(var(--phase, 0.2) * -52s - 21s);
}
@keyframes mica-drift-a {
  0% { transform: translate3d(-4%, -2%, 0) scale(1); }
  50% { transform: translate3d(7%, 9%, 0) scale(1.18); }
  100% { transform: translate3d(-3%, 14%, 0) scale(.92); }
}
@keyframes mica-drift-b {
  0% { transform: translate3d(3%, 4%, 0) scale(1.05); }
  50% { transform: translate3d(-8%, -6%, 0) scale(.9); }
  100% { transform: translate3d(-2%, -12%, 0) scale(1.2); }
}
@keyframes mica-drift-c {
  0% { transform: translate3d(-5%, 4%, 0) scale(1.1); }
  50% { transform: translate3d(9%, -7%, 0) scale(.88); }
  100% { transform: translate3d(2%, -3%, 0) scale(1.16); }
}
@media (prefers-reduced-motion: reduce) {
  .drift-blob.drift-a, .drift-blob.drift-b, .drift-blob.drift-c { animation: none; }
}
/* 液态玻璃面板：半透明白 + 内高光描边（无 backdrop-filter，透明截图无物可糊）。 */
.glass {
  background:
    linear-gradient(150deg, rgba(255,255,255,.68) 0%, rgba(255,255,255,.44) 100%) padding-box,
    linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%,
      rgba(255,255,255,.72) 100%) border-box;
  border: 1px solid transparent;
  box-shadow: 0 3px 10px rgba(31, 35, 41, 0.06);
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
.stat { background: color-mix(in srgb, var(--pc) 10%, rgba(255, 255, 255, 0.72)); color: var(--pc-dark);
  font-size: 12px; padding: 3px 9px; border-radius: 999px; }
.summary { margin-top: 10px; font-size: 13px; color: #4a5560;
  line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.footer { margin-top: 10px; font-size: 11px; color: #7a8699;
  border-top: 1px dashed color-mix(in srgb, var(--pc) 14%, rgba(255, 255, 255, 0.60)); padding-top: 8px; }
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
    wash = _derive_wash_tokens(pc)
    css = (
        _CARD_CSS
        .replace("__PC__", pc)
        .replace("__PC_DARK__", pc_dark)
        .replace("__PC_RGB__", pc_rgb)
        .replace("__WASH_1__", wash["wash_1"])
        .replace("__WASH_2__", wash["wash_2"])
        .replace("__WASH_3__", wash["wash_3"])
        .replace("__WASH_MIST__", wash["wash_mist"])
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
        '<div class="drift-blobs" aria-hidden="true">'
        '<span class="drift-blob drift-a"></span>'
        '<span class="drift-blob drift-b"></span>'
        '<span class="drift-blob drift-c"></span></div>'
        f'<div class="cover-wrap">{cover_block}'
        f'<div class="badge">{platform}</div>'
        '<div class="cover-fallback">🖼</div></div>'
        f'<div class="body"><div class="title">{title}</div>'
        + (f'<div class="author">{author}</div>' if author else "")
        + (f'<div class="stats">{stats_html}</div>' if stats_html else "")
        + (f'<div class="summary">{summary}</div>' if summary else "")
        + (f'<div class="footer">{footer}</div>' if footer else "")
        + "</div></div></div>" + _PHASE_JS + "</body></html>"
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


def render_song_candidates_html(payload: dict[str, Any]) -> str:
    """渲染点歌候选选择卡 HTML（card_render.bridge 的转发入口）。"""
    return _render_song_candidates_html(payload)

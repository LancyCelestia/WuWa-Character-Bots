"""HTML 卡片模板：把解析结果渲染成可截图的信息卡 HTML。

模板只做展示，不决定发送；所有字段都经 html.escape 防注入。
mica-glass v1 2026-09-12：视觉层统一「釉瑚云母 + 液态玻璃 + 渐变漂移」——
底色/色斑用 bridge._derive_wash_tokens 按 --pc 派生的釉瑚洗（__WASH_*__ 注入，
禁纯色），--pc 退为徽章/高亮 accent；半透明白玻璃面板 + 1px 内高光渐变描边、
三枚柔光色斑缓慢漂移 + 漂移相位按 payload digest 确定注入（E01 D2→D1，
页面零 JS）；数据绑定与 __PC__ 注入契约不变。
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
    payload_phase as _payload_phase,
)
from plugins.bot_unified_runtime.output.card_render.bridge import (
    render_song_candidates_html as _render_song_candidates_html,
)
from plugins.bot_unified_runtime.output.card_render.bridge import (
    render_universal_card_html as _render_universal_card_html,
)
from plugins.bot_unified_runtime.output.card_render.theme_tokens import (
    BRAND_THEME,
    DIVIDER,
    FONT_FAMILY_STACK,
    GLOW_ACCENT,
    SHADOW_PRIMARY,
    SHADOW_SECONDARY,
    SURFACE_TINTS,
)

_CARD_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: var(--font-family);
  background: transparent;
  display: flex; align-items: flex-start; justify-content: center;
  padding: 0;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
/* 截图容器：零留白——元素截图 bbox = 可见卡本体（v2 验收反馈 1）。 */
.card {
  width: auto; background: transparent; border: 0; border-radius: 0;
  box-shadow: none; padding: 0;
}
:root { --phase: __PHASE__; --pc: __PC__; --pc-dark: __PC_DARK__; --pc-rgb: __PC_RGB__;
  /* 釉瑚云母底主题 token，全卡统一（bridge 按 --pc 派生注入；工艺出处=用户裁定）。 */
  --wash-1: __WASH_1__; --wash-2: __WASH_2__; --wash-3: __WASH_3__; --wash-mist: __WASH_MIST__;
  --wash-blob-1: color-mix(in srgb, var(--pc) 35%, var(--wash-1));
  --text-main: __TEXT_MAIN__; --text-sub: __TEXT_SUB__;
  --font-family: __FONT_STACK__;
  --r-shell: __R_SHELL__; --r-panel: __R_PANEL__; --r-tile: __R_TILE__;
  --mica-shadow: __SHADOW_PRIMARY__; --mica-shadow-soft: __SHADOW_SECONDARY__;
  /* vis4 辉光/表面/分隔线（theme_tokens 单一源注入；阴影档位受 mica-builders
     契约锁定为固定两枚，panel 级不入册）。 */
  --glow-accent: __GLOW_ACCENT__; --divider-line: __DIVIDER_LINE__;
  --surface-a: __SURFACE_A__; --surface-b: __SURFACE_B__; --surface-neutral: __SURFACE_NEUTRAL__; }
/* mica-glass：釉瑚云母外壳（雾底打底、wash-1/2 对角透色、wash-3 只作第三色透底，
   不透明基础层）+ 1px 内高光渐变描边；色斑垫底、内容抬升；
   阴影只允许两枚 token。 */
.panel {
  position: relative;
  width: 640px;
  border-radius: var(--r-shell); overflow: hidden;
  border: 1px solid transparent;
  background:
    linear-gradient(145deg, var(--wash-mist) 0%,
      color-mix(in srgb, var(--wash-1) 55%, var(--wash-mist)) 30%,
      color-mix(in srgb, var(--wash-2) 48%, var(--wash-mist)) 64%,
      color-mix(in srgb, var(--wash-3) 40%, var(--wash-mist)) 100%) padding-box,
    linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%,
      rgba(255,255,255,.72) 100%) border-box;
  box-shadow: var(--mica-shadow);
}
.panel > :not(.drift-blobs) { position: relative; z-index: 1; }
/* 渐变漂移色斑（wash 三色半透明互相透过，46s/52s/58s 交错漂移+呼吸）。 */
.drift-blobs { position: absolute; inset: 0; z-index: 0; overflow: hidden;
  pointer-events: none; border-radius: inherit; }
.drift-blob { position: absolute; display: block; border-radius: 50%; will-change: transform; }
.drift-blob.drift-a {
  width: 58%; aspect-ratio: 1; left: -14%; top: -22%;
  background: radial-gradient(closest-side,
    color-mix(in srgb, var(--wash-blob-1) 50%, transparent) 0%,
    color-mix(in srgb, var(--wash-blob-1) 28%, transparent) 46%,
    color-mix(in srgb, var(--wash-blob-1) 6%, transparent) 70%, transparent 100%);
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
  box-shadow: var(--mica-shadow-soft);
}
.cover-wrap { position: relative; width: 100%; height: 240px;
  background: linear-gradient(135deg, color-mix(in srgb, var(--pc) 10%, #ffffff) 0%, color-mix(in srgb, var(--pc) 18%, #ffffff) 100%); }
.cover-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cover-fallback { position: absolute; inset: 0; display: flex;
  align-items: center; justify-content: center; font-size: 44px; color: var(--pc); }
.badge { position: absolute; left: 12px; top: 12px; background: rgba(38,46,56,.75);
  color: #fff; font-size: 12px; padding: 3px 10px; border-radius: 999px; }
.body { padding: 14px 18px 16px; }
.title { font-size: 19px; font-weight: 700; color: var(--text-main); line-height: 1.4; }
.author { margin-top: 6px; font-size: 13px; color: var(--text-sub); }
.stats { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
/* vis5 收口（2026-09-13）：平台色只做文字 accent 不做底色——基规则底色改
   本命中性表面 token；zebra 相邻胶囊 inline 覆盖 var(--surface-a/b)。 */
.stat { background: var(--surface-neutral); color: var(--pc-dark);
  font-size: 12px; padding: 3px 9px; border-radius: 999px; }
.summary { margin-top: 10px; font-size: 13px; color: var(--text-sub);
  line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.footer { margin-top: 10px; font-size: 12px; color: var(--text-sub);
  border-top: var(--divider-line); padding-top: 8px; }
/* F11 页脚：头像 + 机器人名 + 功能名（weather/eat 等媒体卡路径同样强制带）。
   vis4 胶囊化：玻璃底 + 辉光背景层（glow 只作背景层，alpha≥0.05）。 */
.card-footer-bot { margin-top: 10px; display: flex; align-items: center; gap: 7px;
  padding: 8px 12px; border-radius: var(--r-tile);
  background:
    var(--glow-accent) right center / 62% 190% no-repeat,
    linear-gradient(150deg, rgba(255,255,255,.66) 0%, rgba(255,255,255,.46) 100%) padding-box,
    linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%, rgba(255,255,255,.72) 100%) border-box;
  border: 1px solid transparent;
  box-shadow: var(--mica-shadow-soft); }
.cfb-avatar { width: 22px; height: 22px; border-radius: 50%; object-fit: cover;
  border: 1px solid #fff; box-shadow: var(--mica-shadow-soft); }
.cfb-dot { width: 22px; height: 22px; border-radius: 50%; flex-shrink: 0;
  background: color-mix(in srgb, var(--pc) 18%, #fff); color: var(--pc-dark);
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 600; }
.cfb-name { font-size: 12px; font-weight: 650; color: var(--pc-dark); white-space: nowrap; }
.cfb-label { font-size: 12px; color: var(--text-sub); }
"""


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def render_media_card_html(payload: dict[str, Any]) -> str:
    """结构化 payload → 信息卡 HTML。

    payload 字段：title, platform, author, cover_url, stats{label:value},
    summary（多行文本）, footer, bot_name, bot_avatar_url, feature_label。
    无封面时封面区整体折叠（不再渲染占位图块）；canonical_url 为合约
    占位值 about:blank 时按无页脚链接处理（F10）。
    """
    title = _esc(payload.get("title")) or "未命名内容"
    platform = _esc(payload.get("platform")) or ""
    author = _esc(payload.get("author")) or ""
    cover = _esc(payload.get("cover_url")) or ""
    stats = payload.get("stats") or {}
    summary = _esc(payload.get("summary")) or ""
    footer = _esc(payload.get("footer")) or ""
    if footer == "about:blank":
        footer = ""
    bot_name = _esc(payload.get("bot_name")) or "守岸人"
    bot_avatar = _esc(payload.get("bot_avatar_url"))
    feature_label = _esc(payload.get("feature_label"))
    pc = _esc(payload.get("platform_color")) or "#607080"
    pc_dark = _esc(payload.get("platform_color_dark")) or "#4a5866"
    pc_rgb = _esc(payload.get("platform_color_rgb")) or "96,112,128"
    wash = _derive_wash_tokens(pc)
    css = (
        _CARD_CSS
        # E01：漂移相位按 payload digest 确定注入（页面零 JS，同 payload 同帧）。
        .replace("__PHASE__", _payload_phase(payload))
        .replace("__PC__", pc)
        .replace("__PC_DARK__", pc_dark)
        .replace("__PC_RGB__", pc_rgb)
        .replace("__WASH_1__", wash["wash_1"])
        .replace("__WASH_2__", wash["wash_2"])
        .replace("__WASH_3__", wash["wash_3"])
        .replace("__WASH_MIST__", wash["wash_mist"])
        # vis4 辉光/分隔线/三档表面（theme_tokens 单一源，与六张 Jinja 卡同值）。
        .replace("__GLOW_ACCENT__", GLOW_ACCENT)
        .replace("__DIVIDER_LINE__", DIVIDER)
        .replace("__SURFACE_A__", SURFACE_TINTS["tint_a"])
        .replace("__SURFACE_B__", SURFACE_TINTS["tint_b"])
        .replace("__SURFACE_NEUTRAL__", SURFACE_TINTS["tint_neutral"])
        .replace("__TEXT_MAIN__", BRAND_THEME.text_main)
        .replace("__TEXT_SUB__", BRAND_THEME.text_sub)
        .replace("__FONT_STACK__", FONT_FAMILY_STACK)
        .replace("__R_SHELL__", f"{BRAND_THEME.shell_radius}px")
        .replace("__R_PANEL__", f"{BRAND_THEME.panel_radius}px")
        .replace("__R_TILE__", f"{BRAND_THEME.tile_radius}px")
        .replace("__SHADOW_PRIMARY__", SHADOW_PRIMARY)
        .replace("__SHADOW_SECONDARY__", SHADOW_SECONDARY)
    )

    cover_block = ""
    if cover:
        # 徽章显功能名（F10：裸平台键如 "eat" 无意义），缺省回平台名。
        badge_text = feature_label or platform
        cover_block = (
            f'<div class="cover-wrap">'
            f'<img src="{cover}" '
            'onerror="this.style.display=\'none\'" alt="cover"/>'
            f'<div class="badge">{badge_text}</div></div>'
        )
    # 统计胶囊 vis5 zebra：相邻胶囊三档表面交替（本命淡蓝/星空紫，不用平台 accent），
    # 行内 style 只覆盖背景，颜色/圆角沿用 .stat 规则；token 引用与 universal_card
    # 同类胶囊同法（var(--surface-a/b)，值由 :root 注入单一源）。
    stat_items = [
        (label, value)
        for label, value in stats.items()
        if not isinstance(value, (dict, list))
    ]
    stats_html = "".join(
        '<span class="stat" style="background: {}">{} {}</span>'.format(
            "var(--surface-a)" if index % 2 == 0 else "var(--surface-b)",
            _esc(label),
            _esc(value),
        )
        for index, (label, value) in enumerate(stat_items)
    )
    avatar_block = (
        f'<img class="cfb-avatar" src="{bot_avatar}" alt="" '
        'onerror="this.style.display=\'none\'"/>'
        if bot_avatar
        else f'<span class="cfb-dot">{bot_name[:1]}</span>'
    )
    bot_footer = (
        f'<div class="card-footer-bot">{avatar_block}'
        f'<span class="cfb-name">{bot_name}</span>'
        f'<span class="cfb-label">· {feature_label or "Shorekeeper"}</span></div>'
    )
    return (
        "<html><head><meta charset=\"utf-8\"><style>"
        f"{css}</style></head><body><div class=\"card\"><div class=\"panel\">"
        '<div class="drift-blobs" aria-hidden="true">'
        '<span class="drift-blob drift-a"></span>'
        '<span class="drift-blob drift-b"></span>'
        '<span class="drift-blob drift-c"></span></div>'
        + cover_block
        + f'<div class="body"><div class="title">{title}</div>'
        + (f'<div class="author">{author}</div>' if author else "")
        + (f'<div class="stats">{stats_html}</div>' if stats_html else "")
        + (f'<div class="summary">{summary}</div>' if summary else "")
        + (f'<div class="footer">{footer}</div>' if footer else "")
        + bot_footer
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


def render_song_candidates_html(payload: dict[str, Any]) -> str:
    """渲染点歌候选选择卡 HTML（card_render.bridge 的转发入口）。"""
    return _render_song_candidates_html(payload)

"""HTML 卡片模板：把解析结果渲染成可截图的信息卡 HTML。

模板只做展示，不决定发送；所有字段都经 html.escape 防注入。
mica-glass v1 2026-09-12：视觉层统一「釉瑚云母 + 液态玻璃 + 渐变漂移」——
底色/色斑用 bridge._derive_wash_tokens 按 --accent 派生的釉瑚洗（__WASH_*__ 注入，
禁纯色），--accent 退为徽章/高亮 accent；半透明白玻璃面板 + 1px 内高光渐变描边、
三枚柔光色斑缓慢漂移 + 漂移相位按 payload digest 确定注入（E01 D2→D1，
页面零 JS）；数据绑定与 __ACCENT__ 注入契约不变。
"""

from __future__ import annotations

import html
from typing import Any

from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
    _derive_wash_tokens,
)
from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
    flat_projection as _flat_projection,
)
from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
    parse_to_render_payload as _parse_to_render_payload,
)
from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
    payload_phase as _payload_phase,
)
from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
    render_song_candidates_html as _render_song_candidates_html,
)
from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
    render_universal_card_html as _render_universal_card_html,
)
from plugins.bot_unified_runtime.domains.render.card_render.mica_shell import (
    brand_capsule_css,
    brand_capsule_html,
    drift_blobs_html,
    mica_decor_css,
    render_root_tokens,
    shell_base_css,
)
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    DIVIDER,
    GLOW_ACCENT,
    SURFACE_TINTS,
)

_CARD_CSS_HEAD = """
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
/* :root 由 mica_shell.render_root_tokens 单一产出（2026-09-18 渲染统一）：
   公共 token 子集、声明顺序、书写风格全卡一致；media 卡特有项（accent-dark /
   accent-rgb / vis4 六键）经 extras 追加，取值来源不变。 */
:root { __ROOT_TOKENS__ }
"""

# 通水切换（v21r3 统一收尾波 C2/C3，2026-09-19）：.panel 壳层+玻璃两档+色斑层
# 三段由 mica_shell 生成器单一产出拼入（宽度 640=CARD_SHELL_WIDTHS["media"]，
# glass=True 附带 .glass/.glass-foot 两档），手抄副本退役；缺省输出与历史 CSS
# 逐字节等价（CORE 席实弹断言）。尾部段（.cover-wrap 起）保持卡特有规则。
_CARD_CSS = (
    _CARD_CSS_HEAD
    + shell_base_css("panel", width_px=640)
    + "\n"
    + mica_decor_css()
    + "\n"
    + """\
.cover-wrap { position: relative; width: 100%; height: 240px;
  background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 10%, #ffffff) 0%, color-mix(in srgb, var(--accent) 18%, #ffffff) 100%); }
.cover-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cover-fallback { position: absolute; inset: 0; display: flex;
  align-items: center; justify-content: center; font-size: 44px; color: var(--accent); }
.badge { position: absolute; left: 12px; top: 12px; background: rgba(38,46,56,.75);
  color: #fff; font-size: 12px; padding: 3px 10px; border-radius: 999px; }
.body { padding: 14px 18px 16px; }
.title { font-size: 19px; font-weight: 700; color: var(--text-main); line-height: 1.4; }
.author { margin-top: 6px; font-size: 13px; color: var(--text-sub); }
.stats { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
/* vis5 收口（2026-09-13）：平台色只做文字 accent 不做底色——基规则底色改
   本命中性表面 token；zebra 相邻胶囊 inline 覆盖 var(--surface-a/b)。 */
.stat { background: var(--surface-neutral); color: var(--accent-dark);
  font-size: 12px; padding: 3px 9px; border-radius: 999px; }
.summary { margin-top: 10px; font-size: 13px; color: var(--text-sub);
  line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.footer { margin-top: 10px; font-size: 12px; color: var(--text-sub);
  border-top: var(--divider-line); padding-top: 8px; }
"""
    # CAP1 品牌胶囊（头像+中文名+英文名+功能名）：组件 CSS 由 mica_shell 单一
    # 产出注入（本卡 .card-footer-bot/.cfb-* 手抄副本退役，DOM 见函数尾部）。
    + "\n"
    + brand_capsule_css()
)


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
    # 胶囊三输入传**原值**（CAPFIX-B 修 I-1 2026-09-21）：转义层收敛到组件内
    # 一处 = ``mica_shell.brand_capsule_html`` 的 ``html.escape``（与 bridge/
    # Jinja 路同构，全卡都只转义一次）。此前本行先 ``_esc`` 再喂组件、组件又
    # escape 一遍 → 双重转义回归（& 变 &amp;amp;：带 & 的头像直链 404、名字
    # 含 ' 卡面露 &#x27;）。中文名缺省=BRAND_THEME.display_name（CAP1 单一
    # 来源）由组件内部回落，此处不再兜第二处字面量。
    bot_name = str(payload.get("bot_name") or "")
    bot_avatar = str(payload.get("bot_avatar_url") or "")
    feature_label = str(payload.get("feature_label") or "")
    pc = _esc(payload.get("platform_color")) or "#607080"
    pc_dark = _esc(payload.get("platform_color_dark")) or "#4a5866"
    pc_rgb = _esc(payload.get("platform_color_rgb")) or "96,112,128"
    wash = _derive_wash_tokens(pc)
    # :root 单一产出（v21r3 渲染统一步 2）。media 卡原本**没有** --accent-dark /
    # --ink / --muted 三项，接入后补齐——三者均未被本卡 CSS 引用，故视觉零变化；
    # 补齐的意义是让四张直拼卡的公共 token 子集完全一致（改一处全卡生效）。
    tokens = render_root_tokens(
        accent=pc,
        # 与 usage/debug 同语义取「深一档主色」（本卡不消费，仅供公共子集完整）。
        accent_dark=pc_dark,
        phase=_payload_phase(payload),
        wash=wash,
        extras={
            # 2026-09-18 命名统一：--accent-dark 已入固定段，此处不再重复声明
            # （原先 extras 里有一份同值副本，改名后会与固定段撞名）。
            "--accent-rgb": pc_rgb,
            "--glow-accent": GLOW_ACCENT,
            "--divider-line": DIVIDER,
            "--surface-a": SURFACE_TINTS["tint_a"],
            "--surface-b": SURFACE_TINTS["tint_b"],
            "--surface-neutral": SURFACE_TINTS["tint_neutral"],
        },
    )
    css = _CARD_CSS.replace("__ROOT_TOKENS__", tokens)

    cover_block = ""
    if cover:
        # 徽章显功能名（F10：裸平台键如 "eat" 无意义），缺省回平台名。
        # feature_label 现为原值（胶囊输入不预转义，见上），徽章走手写 f-string
        # HTML 故在**用处**转义一次；platform 已在上方 _esc（转义层不变）。
        badge_text = _esc(feature_label) if feature_label else platform
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
    # CAP1：统一品牌胶囊（mica_shell 单一产出；.cfb-* 手抄 DOM 退役）。
    # 旧「feature 空则显 Shorekeeper」占位语义作废——英文名常驻胶囊。
    bot_footer = brand_capsule_html(
        bot_name=bot_name,
        avatar_url=bot_avatar,
        feature_label=feature_label,
    )
    return (
        "<html><head><meta charset=\"utf-8\"><style>"
        f"{css}</style></head><body><div class=\"card\"><div class=\"panel\">"
        # 通水切换（v21r3 C2）：漂移装饰层 DOM 生成器单一产出（与历史三 span
        # 手写字面逐字节一致）。
        + drift_blobs_html()
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

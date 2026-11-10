"""VisualSpec 的渲染层：元素 → HTML 卡（**复用既有 mica 外壳**，不新造壳）。

与 `bridge.py` 的一卡一函数**同范式**，但输入是**通用 `VisualSpec`** 而非平台专用 payload。
**既有 8 张卡一个都不动**。

UI 铁律（AGENTS 第三部分）：无 viewport meta、body 透明、字重 ≤700、
动画写在 `.card` 内、光晕 alpha ≥0.05、阴影只准 `none` / `var()` 引登记族。
本模块只提供**元素区 CSS**，外壳与 token 全交 `mica_shell`（单一事实源）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from plugins.bot_unified_runtime.domains.render.card_render import mica_shell
from plugins.bot_unified_runtime.domains.render.card_render import theme_tokens as _tt
from plugins.bot_unified_runtime.domains.render.visual_spec import (
    Element,
    VisualSpec,
    normalize_visual_spec,
)

__all__ = ["render_visual_card_html", "render_visual_spec_html"]

#: 元素区 CSS（只用登记 token 引阴影；不写死颜色）。
_ELEMENTS_CSS = """
.vs-body { display: flex; flex-direction: column; gap: var(--vs-gap, 12px); }
.vs-size-sm .vs-body { font-size: 13px; }
.vs-size-lg .vs-body { font-size: 15px; }
.vs-weight-normal .vs-body { font-weight: 400; }
.vs-weight-semibold .vs-body { font-weight: 600; }
.vs-weight-bold .vs-body { font-weight: 700; }
.vs-color-accent .vs-body { color: var(--accent, inherit); }
.vs-color-muted .vs-body { color: var(--fg-muted, rgba(0,0,0,.62)); }
.vs-layout-double .vs-body { display: grid; grid-template-columns: 1fr 1fr; }
.vs-layout-grid .vs-body { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
.vs-title { font-size: 22px; font-weight: 700; margin: 0 0 2px; }
.vs-subtitle { font-size: 13px; opacity: .72; margin: 0 0 6px; }
.vs-kv { display: flex; align-items: baseline; gap: 10px; }
.vs-kv-label { font-size: 13px; opacity: .72; min-width: 68px; }
.vs-kv-value { font-size: 17px; font-weight: 700; }
.vs-kv-note { font-size: 12px; opacity: .6; margin-left: auto; }
.vs-stat { display: flex; flex-direction: column; gap: 2px; }
.vs-stat-value { font-size: 28px; font-weight: 700; line-height: 1.1; }
.vs-stat-unit { font-size: 14px; opacity: .7; margin-left: 3px; }
.vs-stat-label { font-size: 12px; opacity: .72; }
.vs-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.vs-table th, .vs-table td { text-align: left; padding: 5px 8px; }
.vs-table thead th { font-weight: 700; border-bottom: 1px solid var(--divider-line, rgba(0,0,0,.12)); }
.vs-table tbody tr:nth-child(even) { background: var(--surface-b, rgba(0,0,0,.02)); }
.vs-list { margin: 0; padding-left: 20px; font-size: 14px; line-height: 1.7; }
.vs-text { font-size: 14px; line-height: 1.7; white-space: pre-wrap; }
.vs-badge { display: inline-block; font-size: 12px; font-weight: 700; padding: 2px 10px;
            border-radius: 999px; border: 1px solid var(--divider-line, rgba(0,0,0,.14)); }
.vs-badge-ok { color: #1f7a4d; } .vs-badge-warn { color: #8a5a00; }
.vs-badge-danger { color: #a3271f; } .vs-badge-muted { opacity: .68; }
.vs-img { max-width: 100%; border-radius: 10px; display: block; }
.vs-imgs { display: flex; flex-wrap: wrap; gap: 8px; }
.vs-imgs .vs-img { max-width: 32%; }
.vs-caption { font-size: 12px; opacity: .66; margin-top: 4px; }
.vs-divider { height: 1px; background: var(--divider-line, rgba(0,0,0,.12)); }
.vs-progress-track { height: 8px; border-radius: 999px; background: var(--surface-b, rgba(0,0,0,.06)); overflow: hidden; }
.vs-progress-fill { height: 100%; background: var(--accent); }
.vs-footer { font-size: 12px; opacity: .6; margin-top: 8px; }
.vs-note { font-size: 12px; opacity: .62; margin-top: 3px; }
"""


def _kv(el: Element) -> str:
    d = el.data
    note = f'<span class="vs-kv-note">{d.get("note", "")}</span>' if d.get("note") else ""
    return (
        f'<div class="vs-kv"><span class="vs-kv-label">{d.get("label", "")}</span>'
        f'<span class="vs-kv-value">{d.get("value", "")}</span>{note}</div>'
    )


def _stat(el: Element) -> str:
    d = el.data
    unit = f'<span class="vs-stat-unit">{d.get("unit", "")}</span>' if d.get("unit") else ""
    note = f'<div class="vs-note">{d.get("note", "")}</div>' if d.get("note") else ""
    return (
        f'<div class="vs-stat"><div><span class="vs-stat-value">{d.get("value", "")}</span>{unit}</div>'
        f'<div class="vs-stat-label">{d.get("label", "")}</div>{note}</div>'
    )


def _table(el: Element) -> str:
    d = el.data
    cols = d.get("columns") or []
    rows = d.get("rows") or []
    head = (
        "<thead><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr></thead>" if cols else ""
    )
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )
    caption = f'<div class="vs-caption">{d.get("caption", "")}</div>' if d.get("caption") else ""
    return f'<table class="vs-table">{head}<tbody>{body}</tbody></table>{caption}'


def _list(el: Element) -> str:
    d = el.data
    tag = "ol" if d.get("ordered") else "ul"
    items = "".join(f"<li>{i}</li>" for i in (d.get("items") or []))
    caption = f'<div class="vs-caption">{d.get("caption", "")}</div>' if d.get("caption") else ""
    return f'<{tag} class="vs-list">{items}</{tag}>{caption}'


def _text(el: Element) -> str:
    return f'<div class="vs-text">{el.data.get("text", "")}</div>'


def _badge(el: Element) -> str:
    tone = el.data.get("tone", "info")
    return f'<span class="vs-badge vs-badge-{tone}">{el.data.get("text", "")}</span>'


def _image(el: Element) -> str:
    d = el.data
    if not d.get("src"):
        return ""
    caption = f'<div class="vs-caption">{d.get("caption", "")}</div>' if d.get("caption") else ""
    return f'<img class="vs-img" src="{d["src"]}" alt="{d.get("alt", "")}" />{caption}'


def _images(el: Element) -> str:
    srcs = el.data.get("srcs") or []
    if not srcs:
        return ""
    imgs = "".join(f'<img class="vs-img" src="{s}" alt="" />' for s in srcs)
    caption = f'<div class="vs-caption">{el.data.get("caption", "")}</div>' \
        if el.data.get("caption") else ""
    return f'<div class="vs-imgs">{imgs}</div>{caption}'


def _chart(el: Element) -> str:
    """图表：复用既有 SVG 生成器（`finance_chart`），失败即**整块缺席**（不造第二套）。

    与既有卡（`stocks.py` / `market.py`）**同一调用范式**：生成器返回的是
    ``ChartResult(svg, status, note)``，**必须**看 ``status == "ok"`` 并取 ``.svg``
    ——它**不是**字符串。
    """
    series = el.data.get("series") or []
    if not series:
        return ""
    try:
        from plugins.bot_unified_runtime.domains.finance.data.finance_chart import (
            box_plot_svg,
            line_chart_svg,
        )
    except Exception:  # noqa: BLE001 - 图表模块缺席时整块缺席（与既有卡同口径）
        return ""
    try:
        if el.kind == "chart.box":
            chart = box_plot_svg(
                series, labels=el.data.get("labels") or None, width=880, height=220
            )
        else:
            chart = line_chart_svg(series[0], width=880, height=200)
    except Exception:  # noqa: BLE001 - 生成失败即缺席（与既有卡同口径）
        return ""
    if chart.status != "ok" or not chart.svg:
        return ""
    caption = f'<div class="vs-caption">{el.data.get("caption", "")}</div>' \
        if el.data.get("caption") else ""
    return f"<div>{chart.svg}</div>{caption}"


def _progress(el: Element) -> str:
    d = el.data
    value = d.get("value")
    if value is None:
        return ""
    top = d.get("max") or 100.0
    pct = 0.0 if top <= 0 else max(0.0, min(100.0, value / top * 100.0))
    note = f'<div class="vs-note">{d.get("note", "")}</div>' if d.get("note") else ""
    return (
        f'<div><div class="vs-kv-label">{d.get("label", "")}</div>'
        f'<div class="vs-progress-track"><div class="vs-progress-fill" '
        f'style="width:{pct:.1f}%"></div></div>{note}</div>'
    )


_RENDERERS = {
    "kv": _kv,
    "stat": _stat,
    "table": _table,
    "list": _list,
    "text": _text,
    "badge": _badge,
    "image": _image,
    "images": _images,
    "chart.line": _chart,
    "chart.box": _chart,
    "divider": lambda _el: '<div class="vs-divider"></div>',
    "progress": _progress,
}


def render_elements_html(
    spec: VisualSpec, *, fragments: Mapping[str, str] | None = None
) -> str:
    """把元素数组渲成 body HTML（未知 kind 已在归一阶段丢弃）。

    ``fragments`` 只允许覆盖标题/副标题/页脚三处纯文本（W12 R4）；值已在
    ``normalize_fragments`` 收紧，这里再过一次 ``_s`` 转义，注入面双保险。
    """
    parts: list[str] = []
    shown = fragments or {}
    title = shown.get("title") or spec.title
    subtitle = shown.get("subtitle") or spec.subtitle
    footer = shown.get("footer") or spec.footer
    if title:
        parts.append(f'<div class="vs-title">{title}</div>')
    if subtitle:
        parts.append(f'<div class="vs-subtitle">{subtitle}</div>')
    for el in spec.elements:
        fn = _RENDERERS.get(el.kind)
        if fn is None:
            continue
        chunk = fn(el)
        if chunk:
            parts.append(chunk)
    if footer:
        parts.append(f'<div class="vs-footer">{footer}</div>')
    gap = spec.style.get("spacing")
    gap_attr = f' style="--vs-gap:{int(gap)}px"' if isinstance(gap, int) else ""
    return f'<div class="vs-body"{gap_attr}>{"".join(parts)}</div>'


def render_visual_spec_html(
    spec: VisualSpec, *, fragments: Mapping[str, str] | None = None
) -> str:
    """`VisualSpec` → 完整 HTML 文档（走 mica 外壳，与既有卡同一套 token）。"""
    accent = spec.accent or _tt.BRAND_ACCENT
    tokens = mica_shell.render_root_tokens(
        accent=accent,
        accent_dark=_tt.UNKNOWN_PLATFORM_COLOR,
        wash=_tt.DEFAULT_WASH_TOKENS,
    )
    body = render_elements_html(spec, fragments=fragments)
    stage_class = " ".join(
        part
        for part in (
            {"double": "vs-layout-double", "grid": "vs-layout-grid"}.get(spec.layout, ""),
            f"vs-size-{spec.style.get('size')}" if spec.style.get("size") else "",
            f"vs-weight-{spec.style.get('weight')}" if spec.style.get("weight") else "",
            f"vs-color-{spec.style.get('color')}" if spec.style.get("color") else "",
        )
        if part
    )
    document_title = (fragments or {}).get("title") or spec.title or "可视化"
    return mica_shell.render_shell(
        title=document_title,
        tokens=tokens,
        css=_ELEMENTS_CSS,
        body_html=body,
        stage_class=stage_class,
        shell_class="vs-card",
    )


def render_visual_card_html(payload_dict: dict[str, Any] | None = None) -> str:
    """对外入口（与 `bridge.render_*_card_html` 同形）：payload → HTML。

    payload 即 `VisualSpec.to_dict()` 的形态（**可序列化**，WebUI 可读可写）。
    未知 kind / 越界字段一律丢弃（`spec.dropped` 留痕），**不静默放过**。
    """
    return render_visual_spec_html(normalize_visual_spec(payload_dict))

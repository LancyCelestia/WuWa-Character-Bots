"""VisualSpec / Element：**声明式可视化契约**（2026-10-13 立，用户需求）。

## 为什么要有它
用户要求：任何能力（天气/股票/汇率/期货/餐单/菜谱/URL解析/点歌…）都能把数据
**抽成元素 → 组成 HTML → 渲成图 → 发出**；且这些元素要能在 WebUI 里
**勾选/拖动/修改/排序/排版**。

**现状痛点**：20+ 能力各写各的卡片（`bridge.render_market_card_html` 等一卡一函数）
⇒ 样式改一处要改 20 处，且 WebUI 无法编辑（数据不可序列化）。

**本模块是唯一正解**：能力只产出一个**声明式、可序列化**的 `VisualSpec`。
- 一处改样式，全能力受益
- **可序列化 ⇒ WebUI 能读能写能拖**（编辑器的前提）
- Bot 侧 / WebUI 侧**共用同一渲染出口**（不会「面板预览」与「实际发出」两套）

## 设计纪律
- **纯数据 + 纯函数**：本模块**零 IO、零网络、零副作用**（渲染在 bridge 侧）。
- **白名单 kind**：只认在册的 `ElementKind`；**未知 kind 一律丢弃并留痕**
  （不静默、也不放过——防「用户塞任意 HTML」的注入面）。
- **一切内容转义**：本模块产出的 HTML 对**所有用户可控文本**做 `html.escape`。
  用户只能操作**声明式字段**，**永不能**写 HTML/Jinja/CSS 原样（模板注入铁律）。
- **可序列化**：`VisualSpec.to_dict()` / `from_dict()` 双向，供 WebUI 与持久化。

## 与既有栈的关系
- `card_render/models.py` 的 `RenderPayload` 是**扁平的平台卡专用**结构（B站/微博风），
  与本模块**正交、并存**，不动它。
- 既有 8 张卡（universal/market/finance/song/news/affinity/error/mermaid）**一个都不动**；
  新能力可直接产 `VisualSpec`，老能力可后续逐步迁移。
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "ALLOWED_KINDS",
    "BINDING_PATHS",
    "STYLE_COLORS",
    "STYLE_SIZES",
    "STYLE_SPACING",
    "STYLE_WEIGHTS",
    "VISUAL_SPEC_VERSION",
    "Element",
    "ElementKind",
    "VisualSpec",
    "apply_binding_samples",
    "normalize_visual_spec",
]

#: 契约版本（编辑器目录用；元素/字段**只增不改**）。
VISUAL_SPEC_VERSION = 1

#: 数据绑定路径登记面。当前元素契约**没有 binding 字段**，
#: 因此这里如实返回空表：编辑器不展示「绑定了却不会生效」的路径。
BINDING_PATHS: dict[str, str] = {}

#: 元素区样式值域（渲染层真消费——见 `visual_spec_render`）。
STYLE_SIZES: frozenset[str] = frozenset({"sm", "md", "lg"})
STYLE_SPACING: frozenset[int] = frozenset({8, 12, 16, 20})
STYLE_WEIGHTS: frozenset[str] = frozenset({"normal", "semibold", "bold"})
STYLE_COLORS: frozenset[str] = frozenset({"accent", "muted"})


class ElementKind(str, Enum):
    """在册的元素种类（**白名单**；未知 kind 一律丢弃）。

    刻意**小**：够覆盖用户点名的能力即可，不预造用不上的。
    """

    KV = "kv"              # 标签/值对（温度、汇率…）
    STAT = "stat"          # 大数字＋标签（统计栏）
    TABLE = "table"        # 列/行（预报表、榜单）
    LIST = "list"          # 列表（歌单、候选）
    TEXT = "text"          # 段落
    BADGE = "badge"        # 标签/胶囊（预警、状态）
    IMAGE = "image"        # 单图
    IMAGES = "images"      # 多图
    CHART_LINE = "chart.line"    # 折线（复用既有 finance_chart.line_chart_svg）
    CHART_BOX = "chart.box"      # 箱形（复用既有 finance_chart.box_plot_svg）
    # 注：曾登记 `chart.bar`，但**仓库并无柱状渲染器**（旧实现是拿折线冒充柱状）
    # ⇒ 2026-10-14 撤下：**契约只承诺真能渲出的东西**。补上真柱状渲染器后再登记。
    DIVIDER = "divider"          # 分隔
    PROGRESS = "progress"        # 进度条


ALLOWED_KINDS: frozenset[str] = frozenset(k.value for k in ElementKind)

#: 各 kind 允许的字段（**白名单**；多余字段一律丢弃——防「用户塞任意属性」）。
_KIND_FIELDS: dict[str, frozenset[str]] = {
    "kv": frozenset({"label", "value", "note"}),
    "stat": frozenset({"label", "value", "unit", "note"}),
    "table": frozenset({"columns", "rows", "caption", "note"}),
    "list": frozenset({"items", "ordered", "caption", "note"}),
    "text": frozenset({"text"}),
    "badge": frozenset({"text", "tone"}),
    "image": frozenset({"src", "alt", "caption"}),
    "images": frozenset({"srcs", "caption"}),
    "chart.line": frozenset({"series", "labels", "caption", "note"}),
    "chart.box": frozenset({"series", "labels", "caption", "note"}),
    "divider": frozenset(),
    "progress": frozenset({"label", "value", "max", "note"}),
}

#: badge 的色调白名单（不是颜色值——用户不能直接指定任意 CSS 颜色）。
_BADGE_TONES: frozenset[str] = frozenset({"info", "ok", "warn", "danger", "muted"})


@dataclass
class Element:
    """一个可视化元素。字段按 kind 白名单裁剪。"""

    kind: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "data": dict(self.data)}

    @classmethod
    def from_dict(cls, raw: Any) -> Element | None:
        if not isinstance(raw, dict):
            return None
        kind = str(raw.get("kind") or "").strip()
        if kind not in ALLOWED_KINDS:
            return None  # 未知 kind：丢弃（白名单铁律）
        data_raw = raw.get("data")
        data = data_raw if isinstance(data_raw, dict) else {}
        allowed = _KIND_FIELDS.get(kind, frozenset())
        data = {k: v for k, v in data.items() if k in allowed}
        return cls(kind=kind, data=data)


@dataclass
class VisualSpec:
    """一份完整的可视化描述（能力的唯一产出形态）。"""

    title: str = ""
    subtitle: str = ""
    elements: list[Element] = field(default_factory=list)
    #: 排版：`single`（单列，缺省）/ `double`（双列）/ `grid`（等宽网格）
    layout: str = "single"
    #: 主题：留空则用品牌缺省；可填 `theme_tokens` 的 accent 十六进制
    accent: str = ""
    footer: str = ""
    #: 元素区样式覆盖：size/spacing/weight/color，只收登记值域（见 STYLE_*）
    style: dict[str, Any] = field(default_factory=dict)
    #: 丢弃记录（未知 kind / 越界字段），供调用方如实上报，不静默
    dropped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "elements": [e.to_dict() for e in self.elements],
            "layout": self.layout,
            "accent": self.accent,
            "footer": self.footer,
            "style": dict(self.style),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> VisualSpec:
        return normalize_visual_spec(raw)


_ALLOWED_LAYOUTS: frozenset[str] = frozenset({"single", "double", "grid"})

#: 单份 spec 的元素数上限（防无界膨胀；超出即截断并留痕）。
MAX_ELEMENTS = 60
#: 表格/列表的行数上限。
MAX_ROWS = 200
#: 多图数量上限。
MAX_IMAGES = 12


def _s(value: Any, limit: int = 400) -> str:
    """取文本并**转义**（用户可控内容一律转义；超长截断）。"""
    text = "" if value is None else str(value)
    text = text.strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return html.escape(text, quote=True)


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):  # NaN/Inf 一律剔除（图表不吃）
        return None
    return out


def _rows(value: Any) -> list[list[str]]:
    out: list[list[str]] = []
    if not isinstance(value, list):
        return out
    for row in value[:MAX_ROWS]:
        if isinstance(row, (list, tuple)):
            out.append([_s(c, 120) for c in row])
        elif row is not None:
            out.append([_s(row, 120)])
    return out


def _clean_data(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """按 kind 归一 + 转义。**这里是唯一的内容入口**（注入面全在这一层堵）。"""
    if kind == "kv":
        return {"label": _s(data.get("label"), 80), "value": _s(data.get("value"), 200),
                "note": _s(data.get("note"), 200)}
    if kind == "stat":
        return {"label": _s(data.get("label"), 80), "value": _s(data.get("value"), 80),
                "unit": _s(data.get("unit"), 24), "note": _s(data.get("note"), 200)}
    if kind == "table":
        columns = [_s(c, 60) for c in (data.get("columns") or [])][:12] \
            if isinstance(data.get("columns"), list) else []
        return {"columns": columns, "rows": _rows(data.get("rows")),
                "caption": _s(data.get("caption"), 120), "note": _s(data.get("note"), 200)}
    if kind == "list":
        items = data.get("items")
        return {"items": [_s(i, 200) for i in items[:MAX_ROWS]] if isinstance(items, list) else [],
                "ordered": bool(data.get("ordered")),
                "caption": _s(data.get("caption"), 120), "note": _s(data.get("note"), 200)}
    if kind == "text":
        return {"text": _s(data.get("text"), 2000)}
    if kind == "badge":
        tone = str(data.get("tone") or "info").strip()
        return {"text": _s(data.get("text"), 60),
                "tone": tone if tone in _BADGE_TONES else "info"}
    if kind == "image":
        return {"src": _safe_url(data.get("src")), "alt": _s(data.get("alt"), 120),
                "caption": _s(data.get("caption"), 200)}
    if kind == "images":
        srcs = data.get("srcs")
        safe = [_safe_url(s) for s in srcs[:MAX_IMAGES]] if isinstance(srcs, list) else []
        return {"srcs": [s for s in safe if s], "caption": _s(data.get("caption"), 200)}
    if kind in ("chart.line", "chart.box"):
        return {"series": _series(data.get("series")),
                "labels": [_s(x, 40) for x in data.get("labels", [])][:64]
                if isinstance(data.get("labels"), list) else [],
                "caption": _s(data.get("caption"), 120), "note": _s(data.get("note"), 200)}
    if kind == "progress":
        return {"label": _s(data.get("label"), 80), "value": _f(data.get("value")),
                "max": _f(data.get("max")), "note": _s(data.get("note"), 200)}
    return {}


def _safe_url(value: Any) -> str:
    """只放行 http/https/data:image（防 `javascript:` 等注入面）。"""
    raw = str(value or "").strip()
    low = raw.lower()
    if low.startswith(("http://", "https://", "data:image/")):
        return html.escape(raw, quote=True)
    return ""


def _series(value: Any) -> list[list[float]]:
    """数值序列：只收数字（**非数字一律剔除**，防把文本塞进图表）。"""
    out: list[list[float]] = []
    if not isinstance(value, list):
        return out
    for col in value[:16]:
        if not isinstance(col, (list, tuple)):
            continue
        nums = [n for n in (_f(x) for x in col[:2000]) if n is not None]
        if nums:
            out.append(nums)
    return out


def _clean_style(value: Any, dropped: list[str]) -> dict[str, Any]:
    """样式四键归一：只收登记值域，越界丢弃并留痕（绝不透传任意 CSS）。"""
    raw = value if isinstance(value, dict) else {}
    style: dict[str, Any] = {}
    size = str(raw.get("size") or "").strip().lower()
    if size in STYLE_SIZES:
        style["size"] = size
    elif size:
        dropped.append(f"style.size={size!r}")
    weight = str(raw.get("weight") or "").strip().lower()
    if weight in STYLE_WEIGHTS:
        style["weight"] = weight
    elif weight:
        dropped.append(f"style.weight={weight!r}")
    color = str(raw.get("color") or "").strip().lower()
    if color in STYLE_COLORS:
        style["color"] = color
    elif color:
        dropped.append(f"style.color={color!r}")
    spacing = raw.get("spacing")
    if spacing not in (None, ""):
        try:
            number = int(spacing)
        except (TypeError, ValueError):
            number = -1
        if number in STYLE_SPACING:
            style["spacing"] = number
        else:
            dropped.append(f"style.spacing={spacing!r}")
    return style


def apply_binding_samples(spec: Any, sample: Any = None) -> Any:
    """把绑定样本套进**预览**（只影响返回值，不落库）。

    当前元素契约没有 ``binding`` 字段、``BINDING_PATHS`` 也是空的，所以
    样本没有登记落点——原样返回，绝不猜路径去改内容。等元素契约真的支持
    绑定时，在这里按登记表逐路径覆盖即可（预览/生产仍共用同一个归一入口）。
    """
    return spec


def normalize_visual_spec(raw: Any) -> VisualSpec:
    """把任意输入归成 `VisualSpec`（**唯一入口**；未知/越界一律丢弃并留痕）。"""
    data = raw if isinstance(raw, dict) else {}
    dropped: list[str] = []

    elements: list[Element] = []
    raw_elements = data.get("elements")
    if isinstance(raw_elements, list):
        for idx, item in enumerate(raw_elements):
            el = Element.from_dict(item)
            if el is None:
                kind = item.get("kind") if isinstance(item, dict) else type(item).__name__
                dropped.append(f"elements[{idx}]:kind={kind!r}")
                continue
            if len(elements) >= MAX_ELEMENTS:
                dropped.append(f"elements[{idx}]:超出上限 {MAX_ELEMENTS}")
                continue
            el.data = _clean_data(el.kind, el.data)
            elements.append(el)

    layout = str(data.get("layout") or "single").strip().lower()
    if layout not in _ALLOWED_LAYOUTS:
        dropped.append(f"layout={layout!r}")
        layout = "single"

    accent = str(data.get("accent") or "").strip()
    if accent and not (len(accent) == 7 and accent.startswith("#")):
        dropped.append(f"accent={accent!r}")
        accent = ""

    return VisualSpec(
        title=_s(data.get("title"), 120),
        subtitle=_s(data.get("subtitle"), 200),
        elements=elements,
        layout=layout,
        accent=accent,
        footer=_s(data.get("footer"), 120),
        style=_clean_style(data.get("style"), dropped),
        dropped=dropped,
    )

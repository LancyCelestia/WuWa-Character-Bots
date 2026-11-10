"""VisualSpec 样式四键：只收登记值域、渲染层真消费、目录不再 ImportError。"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.render.visual_spec import (
    STYLE_COLORS,
    STYLE_SIZES,
    STYLE_SPACING,
    STYLE_WEIGHTS,
    VISUAL_SPEC_VERSION,
    normalize_visual_spec,
)
from plugins.bot_unified_runtime.domains.render.visual_spec_render import (
    render_visual_spec_html,
)


def test_catalog_constants_are_importable() -> None:
    assert VISUAL_SPEC_VERSION == 1
    assert STYLE_SIZES and STYLE_SPACING and STYLE_WEIGHTS and STYLE_COLORS


def test_style_whitelist_keeps_registered_values() -> None:
    spec = normalize_visual_spec({
        "title": "t",
        "elements": [{"kind": "text", "data": {"text": "x"}}],
        "style": {"size": "lg", "spacing": 16, "weight": "bold", "color": "accent"},
    })
    assert spec.style == {"size": "lg", "spacing": 16, "weight": "bold", "color": "accent"}
    assert spec.dropped == []


def test_style_whitelist_drops_unknown_without_leaking_css() -> None:
    spec = normalize_visual_spec({
        "elements": [],
        "style": {"size": "huge", "spacing": 7, "weight": "900", "color": "#fff"},
    })
    assert spec.style == {}
    assert len(spec.dropped) == 4


def test_style_reaches_html_not_just_catalog() -> None:
    spec = normalize_visual_spec({"title": "t", "elements": [], "style": {"size": "lg", "spacing": 8}})
    html = render_visual_spec_html(spec)
    assert "vs-size-lg" in html
    assert "--vs-gap:8px" in html
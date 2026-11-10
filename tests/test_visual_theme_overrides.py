"""全局视觉覆盖（W12 R4）回归：登记值域、渲染消费、片段覆盖。"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.render.card_render import (
    mica_shell,
    theme_tokens,
)
from plugins.bot_unified_runtime.domains.render.visual_spec import (
    apply_binding_samples,
    normalize_visual_spec,
)
from plugins.bot_unified_runtime.domains.render.visual_spec_render import (
    render_visual_spec_html,
)


def test_normalize_theme_overrides_keeps_registered_values() -> None:
    out = theme_tokens.normalize_theme_overrides(
        {"brand_accent": "#FF5500", "shell_radius": 24, "font_family": "MONO"}
    )
    assert out == {"brand_accent": "#ff5500", "shell_radius": 24, "font_family": "mono"}


def test_normalize_theme_overrides_drops_out_of_domain() -> None:
    dropped: list[str] = []
    out = theme_tokens.normalize_theme_overrides(
        {"brand_accent": "red", "shell_radius": 17, "font_family": "serif"}, dropped
    )
    assert out == {}
    assert len(dropped) == 3


def test_render_root_tokens_consumes_overrides() -> None:
    theme_tokens.set_theme_overrides(
        {"brand_accent": "#ff5500", "shell_radius": 24, "font_family": "mono"}
    )
    try:
        tokens = mica_shell.render_root_tokens(
            accent=theme_tokens.BRAND_ACCENT,
            accent_dark=theme_tokens.UNKNOWN_PLATFORM_COLOR,
            wash=theme_tokens.DEFAULT_WASH_TOKENS,
        )
    finally:
        theme_tokens.set_theme_overrides({})
    assert "--accent:#ff5500" in tokens
    assert "--r-shell:24px" in tokens
    assert "--font-family:" + theme_tokens.MONO_FONT_STACK in tokens


def test_explicit_accent_beats_global_brand_override() -> None:
    theme_tokens.set_theme_overrides({"brand_accent": "#ff5500"})
    try:
        tokens = mica_shell.render_root_tokens(
            accent="#123456",
            accent_dark=theme_tokens.UNKNOWN_PLATFORM_COLOR,
            wash=theme_tokens.DEFAULT_WASH_TOKENS,
        )
    finally:
        theme_tokens.set_theme_overrides({})
    assert "--accent:#123456" in tokens


def test_fragments_override_title_subtitle_footer() -> None:
    spec = normalize_visual_spec({"title": "原标题", "elements": []})
    html = render_visual_spec_html(
        spec, fragments={"title": "预览标题", "footer": "页脚"}
    )
    assert "预览标题" in html
    assert "原标题" not in html
    assert "页脚" in html


def test_binding_samples_are_passthrough_until_contract_supports_them() -> None:
    spec = {"title": "x", "elements": []}
    assert apply_binding_samples(spec, {"weather.temp": 1}) is spec
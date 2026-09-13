"""四处 f-string/拼接 HTML 卡片 builder 的主题契约测试（C4 收编，全离线）。

统一对象（与 Jinja 模板契约 tests/test_rendering_contract.py 同源，唯一事实
来源均为 output/card_render/theme_tokens.py）：
- capabilities/echo.py::_help_mica_html（帮助手册卡）
- capabilities/debug.py::_llm_setup_mica_html（LLM 接入检查卡）
- output/card_render/usage_cards.py::usage_report_mica_html（用量/账单卡）
- output/templates.py::render_media_card_html（旧媒体卡降级器）

契约断言：无 <meta viewport>；body 透明；根元素带 .card；box-shadow 只允许
none / var(--mica-shadow) / var(--mica-shadow-soft)；两枚阴影 token 值 ==
theme_tokens.SHADOW_PRIMARY / SHADOW_SECONDARY；font-weight ≤ 700；
rgba alpha ≥ 0.05（color-mix ≥ 5%）；圆角三 token / 字体栈 / text-main /
text-sub 改自 theme_tokens 常量。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

import pytest

from plugins.bot_unified_runtime.capabilities.debug import _llm_setup_mica_html
from plugins.bot_unified_runtime.capabilities.echo import _help_mica_html
from plugins.bot_unified_runtime.output.card_render.theme_tokens import (
    BRAND_THEME,
    FONT_FAMILY_STACK,
    FONT_WEIGHT_MAX,
    SHADOW_PRIMARY,
    SHADOW_SECONDARY,
)
from plugins.bot_unified_runtime.output.card_render.usage_cards import (
    usage_report_mica_html,
)
from plugins.bot_unified_runtime.output.templates import render_media_card_html

_SHADOW_TOKEN_NAMES = {"--mica-shadow", "--mica-shadow-soft"}
_ALLOWED_SHADOW_VALUES = {
    "none",
    "var(--mica-shadow)",
    "var(--mica-shadow-soft)",
}


class _StubConfig:
    """debug/usage builder 只读 bot_help_card_color 一个属性。"""

    bot_help_card_color = ""


class _RootCardParser(HTMLParser):
    """抓取根 div 的 class（截图目标 .card 契约）。"""

    def __init__(self) -> None:
        super().__init__()
        self.root_classes: set[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "div" and self.root_classes is None:
            for key, value in attrs:
                if key == "class" and value:
                    self.root_classes = set(value.split())


def _help_html() -> str:
    return _help_mica_html(
        "测试正文",
        is_admin=False,
        sections=[("测试模块", [("/bot help", "测试说明")])],
    )


def _llm_setup_html() -> str:
    payload: dict[str, Any] = {
        "config": _StubConfig(),
        "status_label": "检查完成",
        "status_kind": "ok",
        "message": "全部通过",
        "rows": [
            {
                "key": "BOT_CHAT_PROVIDER",
                "desc": "模型供应商",
                "range": "openai 兼容",
                "value": "axonhub",
                "ok": "1",
            },
            {
                "key": "BOT_CHAT_BASE_URL",
                "desc": "接口地址",
                "range": "http(s):// 开头",
                "value": "https://example.invalid/v1",
                "ok": "0",
            },
        ],
        "next_step": "无",
    }
    return _llm_setup_mica_html(payload)


def _usage_html() -> str:
    return usage_report_mica_html(
        _StubConfig(),
        kicker="测试 · 模型用量",
        title="模型用量账单报告",
        status_label="账单 0.00 元",
        status_kind="ok",
        window_label="09-12 00:00 至 09-12 23:59",
        generated_at="2026-09-12 23:59:00",
        totals={
            "prompt_tokens": 100,
            "cache_read_tokens": 10,
            "cache_write_tokens": 20,
            "completion_tokens": 30,
            "total_tokens": 160,
            "calls": 3,
            "cost_text": "0.00",
            "unpriced_calls": 0,
        },
        model_rows=[
            {
                "model": "model-alpha",
                "prompt": 100,
                "cache_read": 10,
                "cache_write": 20,
                "completion": 30,
                "cost_text": "0.00",
                "priced": True,
            }
        ],
    )


def _media_html() -> str:
    return render_media_card_html(
        {
            "title": "测试标题",
            "platform": "bilibili",
            "author": "UP 主",
            "stats": {"播放": "1 万"},
            "summary": "测试摘要",
            "footer": "https://example.invalid/watch/1",
            "bot_name": "守岸人",
            "feature_label": "解析",
        }
    )


_BUILDERS: dict[str, Callable[[], str]] = {
    "echo_help": _help_html,
    "debug_llm_setup": _llm_setup_html,
    "usage_report": _usage_html,
    "media_card": _media_html,
}


@pytest.fixture(params=list(_BUILDERS), ids=list(_BUILDERS))
def mica_html(request: pytest.FixtureRequest) -> str:
    return _BUILDERS[request.param]()


def _norm_css(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _css_of(html_text: str) -> str:
    match = re.search(r"<style>(.*?)</style>", html_text, re.DOTALL)
    assert match, "builder 产出缺少 <style> 块"
    return match.group(1)


def _css_rules(css: str) -> list[tuple[str, str]]:
    """粗粒度 CSS 规则切分（keyframes 内层块按普通块处理即可满足断言）。"""
    return [
        (selector.strip(), body)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    ]


# ==================== 1. viewport 禁令 ====================
def test_no_meta_viewport(mica_html: str) -> None:
    assert not re.search(r"<meta[^>]*viewport", mica_html), (
        "违反无 <meta viewport> 铁律"
    )


# ==================== 2. body 透明（omit_background 依赖） ====================
def test_body_transparent(mica_html: str) -> None:
    for selector, body in _css_rules(_css_of(mica_html)):
        if re.fullmatch(r"(html\s+)?body", selector):
            assert re.search(r"background\s*:\s*transparent", body), (
                "body 必须透明（截图 omit_background 依赖）"
            )
            return
    pytest.fail("未找到 body 规则")


# ==================== 3. 根元素带 .card（截图目标契约） ====================
def test_root_element_has_card_class(mica_html: str) -> None:
    parser = _RootCardParser()
    parser.feed(mica_html)
    assert parser.root_classes is not None and "card" in parser.root_classes, (
        "根元素必须带 card 类（截图目标 .card 契约）"
    )


# ==================== 4. 字重 ≤ 700 ====================
def test_font_weight_at_most_700(mica_html: str) -> None:
    weights = [int(v) for v in re.findall(r"font-weight\s*:\s*(\d+)", mica_html)]
    assert weights, "builder 产出无 font-weight 声明？"
    assert max(weights) <= FONT_WEIGHT_MAX


# ==================== 5. box-shadow 只允许两枚 token / none ====================
def test_box_shadow_only_tokens(mica_html: str) -> None:
    for selector, body in _css_rules(_css_of(mica_html)):
        for value in re.findall(r"box-shadow\s*:\s*([^;]+);", body):
            normalized = _norm_css(value)
            assert normalized in _ALLOWED_SHADOW_VALUES, (
                f"{selector!r} 出现非 token 阴影: {normalized!r}"
            )


def test_exactly_two_shadow_token_definitions(mica_html: str) -> None:
    css = _css_of(mica_html)
    defined = re.findall(r"(--[a-z-]*shadow[a-z-]*)\s*:", css)
    assert set(defined) == _SHADOW_TOKEN_NAMES, (
        f"阴影 token 集合违规: {sorted(set(defined))}"
    )
    assert len(defined) == 2, "每枚阴影 token 只允许定义一次"


def test_shadow_token_values_single_source(mica_html: str) -> None:
    css = _css_of(mica_html)
    mica = re.search(r"--mica-shadow:\s*([^;]+);", css)
    soft = re.search(r"--mica-shadow-soft:\s*([^;]+);", css)
    assert mica and soft, "缺阴影 token 定义"
    assert _norm_css(mica.group(1)) == _norm_css(SHADOW_PRIMARY), (
        "--mica-shadow 与 theme_tokens.SHADOW_PRIMARY 不一致"
    )
    assert _norm_css(soft.group(1)) == _norm_css(SHADOW_SECONDARY), (
        "--mica-shadow-soft 与 theme_tokens.SHADOW_SECONDARY 不一致"
    )


# ==================== 6. 圆角三 token 单一来源 ====================
def test_radius_tokens_from_theme(mica_html: str) -> None:
    css = _css_of(mica_html)
    expected = {
        "--r-shell": f"{BRAND_THEME.shell_radius}px",
        "--r-panel": f"{BRAND_THEME.panel_radius}px",
        "--r-tile": f"{BRAND_THEME.tile_radius}px",
    }
    for token, value in expected.items():
        match = re.search(re.escape(token) + r":\s*([^;]+);", css)
        assert match, f"缺 {token} 定义"
        assert _norm_css(match.group(1)) == value, f"{token} 与 theme_tokens 不一致"


# ==================== 7. 字体栈 / text-main / text-sub 单一来源 ====================
def test_font_family_token_from_theme(mica_html: str) -> None:
    css = _css_of(mica_html)
    match = re.search(r"--font-family:\s*([^;]+);", css)
    assert match, "缺 --font-family 定义"
    assert _norm_css(match.group(1)) == _norm_css(FONT_FAMILY_STACK), (
        "--font-family 与 theme_tokens.FONT_FAMILY_STACK 不一致"
    )
    for selector, body in _css_rules(css):
        if re.fullmatch(r"(html\s+)?body", selector):
            assert re.search(r"font-family\s*:\s*var\(--font-family\)", body), (
                "body 字体必须消费 var(--font-family)"
            )
            return
    pytest.fail("未找到 body 规则")


def test_text_tokens_from_theme(mica_html: str) -> None:
    css = _css_of(mica_html)
    main = re.search(r"--text-main:\s*([^;]+);", css)
    sub = re.search(r"--text-sub:\s*([^;]+);", css)
    assert main and sub, "缺 --text-main/--text-sub 定义"
    assert _norm_css(main.group(1)) == _norm_css(BRAND_THEME.text_main), (
        "--text-main 与 theme_tokens.text_main 不一致"
    )
    assert _norm_css(sub.group(1)) == _norm_css(BRAND_THEME.text_sub), (
        "--text-sub 与 theme_tokens.text_sub 不一致"
    )


# ==================== 8. 光晕 alpha ≥ 0.05 ====================
def test_glow_alpha_floor(mica_html: str) -> None:
    css = _css_of(mica_html)
    for value in re.findall(
        r"rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*(0?\.\d+|\d+)\s*\)", css
    ):
        assert float(value) >= 0.05, f"rgba 光晕 alpha {value} < 0.05"
    for value in re.findall(
        r"color-mix\([^)]*?(\d+(?:\.\d+)?)%\s*,\s*transparent", css
    ):
        assert float(value) >= 5.0, f"color-mix 光晕 {value}% < 5%"


# ==================== 9. vis5 收官补充（2026-09-13） ====================
# 范围说明：字号下限/字距刻度/gap 刻度三门锁 usage_report / media_card /
# debug_llm_setup（debug 卡 2026-09-13 视觉收口补丁并入：kicker 11px→12px、
# 字距 .14em→0.06em 刻度值；阴影本就全 var() 引用，gap 8/6/12 原在刻度内）。
# echo_help 载体在 capabilities/echo.py（他席在飞），收口后再并入本门。
_VIS5_GATE_BUILDERS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("usage_report", _usage_html),
    ("media_card", _media_html),
    ("debug_llm_setup", _llm_setup_html),
)


def test_font_size_floor_12px_output_domain() -> None:
    """字号下限 12px（AGENTS.md UI 铁律；usage 卡 mnote 旧值 11px 已修）。"""
    for label, build in _VIS5_GATE_BUILDERS:
        html_text = build()
        sizes = [float(v) for v in re.findall(r"font-size\s*:\s*([\d.]+)px", html_text)]
        assert sizes, f"{label} 无 font-size 声明？"
        below = sorted({v for v in sizes if v < 12})
        assert not below, f"{label} 字号低于 12px 下限: {below}"


def test_letter_spacing_on_e03_scale_output_domain() -> None:
    """字距与六张 Jinja 卡同刻度 {0.02, 0.06}（usage 卡旧值 .14/.04/.03em 已修）。"""
    for label, build in _VIS5_GATE_BUILDERS:
        html_text = build()
        values = [
            float(v)
            for v in re.findall(r"letter-spacing\s*:\s*([\d.]+)em", html_text)
        ]
        off_scale = [v for v in values if v not in {0.02, 0.06}]
        assert not off_scale, f"{label} letter-spacing 脱离刻度: {off_scale}"


def test_gaps_on_audited_scale_output_domain() -> None:
    from plugins.bot_unified_runtime.output.card_render.theme_tokens import (
        GAP_SCALE_PX,
    )

    for label, build in _VIS5_GATE_BUILDERS:
        html_text = build()
        gaps = [int(v) for v in re.findall(r"gap\s*:\s*(\d+)px", html_text)]
        bad = sorted({g for g in gaps if g not in GAP_SCALE_PX})
        assert not bad, f"{label} 间距 {bad}px 不在审计过的 gap 刻度内"


def test_usage_card_carries_vis4_keys_and_bot_footer() -> None:
    """usage 卡补齐 vis4 六键 + F11 bot 页脚（vis5 前是唯一无署名卡）。"""
    html_text = _usage_html()
    for token in ("--glow-accent:", "--divider-line:", "--surface-a:", "--surface-b:", "--surface-neutral:"):
        assert token in html_text, f"usage 卡缺 {token}"
    assert 'class="bot-foot"' in html_text
    assert "守岸人" in html_text.split('class="bot-foot"', 1)[1]
    assert "· 模型用量" in html_text

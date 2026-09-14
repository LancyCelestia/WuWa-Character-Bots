"""vis2/vis4/vis5 模板视觉审计固化测试（2026-09-12 / 2026-09-13）。

审计基准：友商解析卡质量维度（信息层级/瓦片化/角标/元数据页脚/留白节奏）。
本次审计结论（详见 .superpowers/sdd/2026-09-12-shorekeeper-global-audit/vis2-report.md）：
- market_card / finance_card 的行瓦片此前无表面（行体悬空，无瓦片感）→
  已补液态玻璃表面（与 affinity/song 的 .glass 同配方）；
- affinity / song_candidates / mermaid 审计通过，不動。
本文件锁定「行瓦片必须带玻璃表面」这一结构事实，防回归。全离线字符串断言。
vis4（2026-09-13）：行瓦片与页脚胶囊升 L2 面板阴影；阴影白名单改由
theme_tokens.SHADOW_CSS_VARS 动态派生——登记表即正门，族外零容忍。
vis5（2026-09-13 收官）：①zebra 三档表面相邻可辨（ onstage ΔE 数值门，旧值
ΔE(a,b)=0.81 不可辨已调参）；②次级文字灰 TEXT_SECONDARY 单一来源且对三档
表面 ≥4.5:1（旧散值 #7a828c/#8a919b 最低 2.5:1 不达 AA）；③可编辑模板
字号下限 12px（AGENTS.md UI 铁律；market/finance 金融域已收口并入：
11.5px→12px + 旧灰 #7a8699/#57626f 收编 --text-secondary）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.output.card_render import bridge
from plugins.bot_unified_runtime.output.card_render.theme_tokens import (
    SHADOW_CSS_VARS,
    SURFACE_TINTS,
    TEXT_SECONDARY,
)

_TEMPLATES_DIR = Path(bridge.__file__).resolve().parent / "templates"

# 液态玻璃瓦片表面要素：半透明白 padding-box + 1px 内高光渐变 border-box
# + 透明边框 + L2 面板阴影 token（值契约由 test_rendering_contract 锁定）。
_GLASS_MARKERS = (
    "padding-box",
    "border-box",
    "border: 1px solid transparent",
    "box-shadow: var(--mica-shadow-panel)",
)

# 模板 → 液态玻璃表面载体选择器。market/finance 的行瓦片表面直接写在
# .index/.row 规则内（vis2 审计修复点）；affinity/song 由 DOM 上的 .glass
# 类承载（.tile/.row 组合 .glass），表面配方集中在 .glass 规则。
_SURFACE_RULES: dict[str, tuple[str, ...]] = {
    "market_card.html": (".index",),
    "finance_card.html": (".row",),
    "affinity_card.html": (".glass",),
    "song_candidates.html": (".glass",),
    "error_card.html": (".row",),
}

# DOM 上必须以 glass 类组合出瓦片的选择器（affinity/song 的表面挂法）。
_DOM_GLASS_ROWS: dict[str, tuple[str, ...]] = {
    "affinity_card.html": ('class="tile{{ \' me\' if row.sender_id == me_id else \'\' }} glass"',),
    "song_candidates.html": ('class="row{{ \' top\' if cand.is_top else \'\' }} glass"',),
}


def _tpl(name: str) -> str:
    return (_TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return text


def _css_rules(name: str) -> dict[str, str]:
    css = re.search(r"<style>(.*?)</style>", _strip_comments(_tpl(name)), re.DOTALL)
    assert css, f"{name} 缺 <style> 块"
    return {
        selector.strip(): body
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css.group(1))
    }


@pytest.mark.parametrize("name", sorted(_SURFACE_RULES))
def test_list_tiles_keep_glass_surface(name: str) -> None:
    """瓦片化审计：列表行瓦片必须带液态玻璃表面（vis2 2026-09-12 固化）。"""
    rules = _css_rules(name)
    for selector in _SURFACE_RULES[name]:
        # 允许组合选择器（如 .glass 复用于多个规则），匹配含该类名的规则。
        bodies = [
            body
            for rule, body in rules.items()
            if re.search(r"(^|[\s,>+~])" + re.escape(selector) + r"($|[\s,:.{])", rule)
        ]
        assert bodies, f"{name} 缺 {selector} 表面规则"
        base = next(
            (body for body in bodies if "padding-box" in body and "border-box" in body),
            None,
        )
        assert base is not None, f"{name} {selector} 缺玻璃双背景（padding/border-box）"
        for marker in _GLASS_MARKERS:
            assert marker in base, f"{name} {selector} 缺玻璃表面要素: {marker}"


@pytest.mark.parametrize("name", sorted(_DOM_GLASS_ROWS))
def test_dom_rows_compose_glass_class(name: str) -> None:
    """affinity/song 的瓦片表面经 DOM glass 类组合，组合写法不得丢失。"""
    text = _strip_comments(_tpl(name))
    for needle in _DOM_GLASS_ROWS[name]:
        assert needle in text, f"{name} DOM 行瓦片缺 glass 组合: {needle!r}"


@pytest.mark.parametrize("name", sorted(_SURFACE_RULES))
def test_tile_surface_shadow_is_token_only(name: str) -> None:
    """瓦片表面新增阴影只允许引用 SHADOW_CSS_VARS 登记族（动态白名单）。"""
    allowed = {"none"} | {f"var({var})" for var in SHADOW_CSS_VARS}
    css = re.search(
        r"<style>(.*?)</style>", _strip_comments(_tpl(name)), re.DOTALL
    ).group(1)
    for value in re.findall(r"box-shadow\s*:\s*([^;]+)(?:;|$)", css):
        normalized = re.sub(r"\s+", " ", value).strip()
        assert normalized in allowed, f"{name} 出现非 token 阴影: {normalized!r}"


# ==================== vis5：zebra 区分度 / 次级文字对比度（数值门） ====================
# 可编辑模板集（market/finance 已于 2026-09-13 视觉收口补丁并入：11.5px→12px、
# 旧灰收编 --text-secondary 单源）。
_EDITABLE_TEMPLATES: tuple[str, ...] = (
    "universal_card.html",
    "affinity_card.html",
    "song_candidates.html",
    "mermaid_card.html",
    "market_card.html",
    "finance_card.html",
    "error_card.html",
)
# 旧散灰（vis5 前各模板私有的次级文字色，全部收编 TEXT_SECONDARY）。
_LEGACY_SECONDARY_GRAYS = ("#7a828c", "#8a919b", "#66727f", "#7a8699", "#57626f", "#4a5560")


def _blend_over(bg: tuple[float, ...], fg: tuple[float, ...], alpha: float) -> tuple[float, ...]:
    return tuple(fg[i] * alpha + bg[i] * (1 - alpha) for i in range(3))


def _hex_rgb(value: str) -> tuple[float, float, float]:
    text = value.lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _rel_lum(color: tuple[float, ...]) -> float:
    def channel(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = map(channel, color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    la, lb = sorted((_rel_lum(a), _rel_lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _lab(color: tuple[float, ...]) -> tuple[float, float, float]:
    def channel(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = map(channel, color)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def pivot(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = pivot(x), pivot(y), pivot(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _delta_e(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    la, lb = _lab(a), _lab(b)
    return sum((la[i] - lb[i]) ** 2 for i in range(3)) ** 0.5


def _surface_onstage(css: str) -> tuple[float, ...]:
    """SURFACE_TINTS 值 → 叠在本命 wash 渐变中部（≈#edf0f5）上的实际色。"""
    css = css.replace(" ", "")
    match = re.match(
        r"color-mix\(insrgb,#([0-9a-f]{6})([\d.]+)%,rgba\((\d+),(\d+),(\d+),([\d.]+)\)\)", css
    )
    bg = (237.0, 240.0, 245.0)
    if match:
        base = _hex_rgb(match.group(1))
        p = float(match.group(2))
        white = (float(match.group(3)), float(match.group(4)), float(match.group(5)))
        white_alpha = float(match.group(6))
        # CSS color-mix 带 alpha 色 = 预乘空间混合（评审 A14-I1：直混会系统性偏亮）。
        alpha = p / 100 + (1 - p / 100) * white_alpha
        mixed = tuple(
            ((p / 100) * base[i] + (1 - p / 100) * white_alpha * white[i]) / alpha
            for i in range(3)
        )
        return _blend_over(bg, mixed, alpha)
    flat = re.match(r"rgba\((\d+),(\d+),(\d+),([\d.]+)\)", css)
    assert flat, f"无法解析表面值: {css!r}"
    return _blend_over(bg, tuple(float(flat.group(i)) for i in (1, 2, 3)), float(flat.group(4)))


def test_zebra_surfaces_distinct() -> None:
    """zebra 三档表面 onstage 相邻可辨（vis5：旧值 ΔE(a,b)=0.81 不可辨）。"""
    surfaces = {key: _surface_onstage(css) for key, css in SURFACE_TINTS.items()}
    assert _delta_e(surfaces["tint_a"], surfaces["tint_b"]) >= 3.0, (
        f"tint_a/tint_b 不可辨: ΔE={_delta_e(surfaces['tint_a'], surfaces['tint_b']):.2f}"
    )
    assert _delta_e(surfaces["tint_a"], surfaces["tint_neutral"]) >= 2.5
    assert _delta_e(surfaces["tint_b"], surfaces["tint_neutral"]) >= 2.5


def test_text_tokens_readable_on_surfaces() -> None:
    """text_sub 与统一次级灰对三档表面全部 ≥4.5:1（WCAG AA@12px）。"""
    surfaces = {key: _surface_onstage(css) for key, css in SURFACE_TINTS.items()}
    text_sub = _hex_rgb("#5b6069")
    secondary = _hex_rgb(TEXT_SECONDARY)
    for key, surface in surfaces.items():
        assert _contrast(text_sub, surface) >= 4.5, f"text_sub 对 {key} 对比不足"
        assert _contrast(secondary, surface) >= 4.5, (
            f"TEXT_SECONDARY({TEXT_SECONDARY}) 对 {key} 对比不足"
        )


@pytest.mark.parametrize("name", _EDITABLE_TEMPLATES)
def test_secondary_gray_single_source(name: str) -> None:
    """可编辑模板 --text-secondary 与 theme_tokens.TEXT_SECONDARY 一致，旧散灰清零。"""
    text = _strip_comments(_tpl(name))
    match = re.search(r"--text-secondary:\s*(#[0-9a-fA-F]{6})", text)
    assert match, f"{name} 缺 --text-secondary token"
    assert match.group(1).lower() == TEXT_SECONDARY.lower(), (
        f"{name} --text-secondary={match.group(1)} 与 TEXT_SECONDARY={TEXT_SECONDARY} 不一致"
    )
    lowered = text.lower()
    leftovers = [gray for gray in _LEGACY_SECONDARY_GRAYS if gray in lowered]
    assert not leftovers, f"{name} 残留旧次级灰散值: {leftovers}"


@pytest.mark.parametrize("name", _EDITABLE_TEMPLATES)
def test_font_size_floor_12px(name: str) -> None:
    """字号下限 12px（AGENTS.md UI 铁律；vis5 前universal 有 31 处 10px）。"""
    text = _strip_comments(_tpl(name))
    sizes = [float(v) for v in re.findall(r"font-size\s*:\s*([\d.]+)px", text)]
    assert sizes, f"{name} 无 font-size 声明？"
    below = sorted({v for v in sizes if v < 12})
    assert not below, f"{name} 字号低于 12px 下限: {below}"

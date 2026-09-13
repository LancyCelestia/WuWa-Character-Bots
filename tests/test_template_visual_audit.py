"""vis2/vis4 模板视觉审计固化测试（2026-09-12 / 2026-09-13）。

审计基准：友商解析卡质量维度（信息层级/瓦片化/角标/元数据页脚/留白节奏）。
本次审计结论（详见 .superpowers/sdd/2026-09-12-shorekeeper-global-audit/vis2-report.md）：
- market_card / finance_card 的行瓦片此前无表面（行体悬空，无瓦片感）→
  已补液态玻璃表面（与 affinity/song 的 .glass 同配方）；
- affinity / song_candidates / mermaid 审计通过，不動。
本文件锁定「行瓦片必须带玻璃表面」这一结构事实，防回归。全离线字符串断言。
vis4（2026-09-13）：行瓦片与页脚胶囊升 L2 面板阴影；阴影白名单改由
theme_tokens.SHADOW_CSS_VARS 动态派生——登记表即正门，族外零容忍。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.output.card_render import bridge
from plugins.bot_unified_runtime.output.card_render.theme_tokens import SHADOW_CSS_VARS

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
    for value in re.findall(r"box-shadow\s*:\s*([^;]+);", css):
        normalized = re.sub(r"\s+", " ", value).strip()
        assert normalized in allowed, f"{name} 出现非 token 阴影: {normalized!r}"

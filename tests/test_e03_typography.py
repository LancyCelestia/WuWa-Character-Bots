"""E03 字体层级微雕契约测试（2026-09-13，docs/design/visual-effects-catalog.md E03）。

全部离线：纯文本断言，不依赖 playwright、不联网。

范围（视觉特效目录 E03 原文）：
1. 数字数据（统计值/价格/百分比/时间/ID）统一 `font-variant-numeric: tabular-nums`；
2. 小标签字距收口 0.05–0.08em（summary-tag 0.06em 手法推广，上限 0.08em 写死）；
3. 大数字行高收敛 1.0–1.15；行高统一刻度 {1, 1.1, 1.15, 1.2, 1.4, 1.5, 1.6}；
4. 标题（含标题引言框）`text-wrap: balance`（Chromium 114+，不支持时静默无效）。

铁律零破坏（与 test_rendering_contract 互为冗余防线）：字重 ≤700；零新动画
（本批纯静态 CSS 属性，无新 @keyframes）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.output.card_render import bridge

# 与 test_rendering_contract.CARD_TEMPLATES 同口径：显式枚举，禁止 glob。
CARD_TEMPLATES: tuple[str, ...] = (
    "universal_card.html",
    "market_card.html",
    "affinity_card.html",
    "mermaid_card.html",
    "song_candidates.html",
    "finance_card.html",
)

_TEMPLATES_DIR = Path(bridge.__file__).resolve().parent / "templates"

# 数字数据选择器 → 模板（统计值/价格/百分比/时间/ID；已有的不重复列出，
# universal 的 metric-value/author-* 已带 tabular-nums，此处断言其仍在）。
_NUMERIC_SELECTORS: dict[str, tuple[str, ...]] = {
    "universal_card.html": (
        ".metric-value",
        ".author-stat",
        ".author-id",
        ".author-row-timestamp",
        ".footer-media-id",
        ".stat-item span",
        ".meta-stat",
        ".pc-likes",
        ".comment-meta",
        ".publish-time",
        ".forward-time",
        ".forward-meta",
        ".duration-pill",
        ".quality-pill",
        ".v-duration",
        ".uid-tag",
        ".id-tag",
        ".handle-tag",
        ".sg-count",
    ),
    "market_card.html": (
        ".index .chg",
        ".index .price",
        ".index .pct",
        ".data-foot",
    ),
    "finance_card.html": (
        ".row .value",
        ".row .delta",
        ".data-foot",
    ),
    "affinity_card.html": (
        ".tile .score",
        ".tile .sid",
        ".dscore",
        ".step-row b",
    ),
    "song_candidates.html": (
        ".num",
        ".ttl",
    ),
    "mermaid_card.html": (
        # mermaid 无业务数字字段；节点文本内的数字经继承吃到等宽数字。
        ".card .mermaid",
    ),
}

# 小标签字距（区块小标/页脚署名/徽章）：0.06em 刻度（summary-tag 既有手法）。
_LABEL_TRACKING: dict[str, tuple[str, ...]] = {
    "universal_card.html": (".summary-tag", ".comments-title", ".footer-platform"),
    "market_card.html": (".group-title",),
    "finance_card.html": (".section-title",),
    "affinity_card.html": (".dlabel",),
    "song_candidates.html": (".ttl",),
    "mermaid_card.html": (),
}

# 行高统一刻度（1/1.1/1.15 = 紧排徽章与大数字档；1.2 = 展示标题档；
# 1.4 = 标题/紧凑行档；1.5 = 正文/UI 文本档；1.6 = 长正文档）。
_LINE_HEIGHT_SCALE = {1.0, 1.1, 1.15, 1.2, 1.4, 1.5, 1.6}
# 大数字行高收敛区间（目录 E03 原文 1.0–1.15）。
_BIG_NUMBER_RANGE = (1.0, 1.15)
_BIG_NUMBER_SELECTORS: dict[str, tuple[str, ...]] = {
    "universal_card.html": (".author-row-primary",),
    "affinity_card.html": (".dscore",),
}

# 字距刻度：0.02em = 数字徽章紧排（duration/quality pill 既有值）；
# 0.06em = 小标签标准字距；上限 0.08em（目录：中文字距 >0.1em 显松）。
_ALLOWED_TRACKING = {0.02, 0.06}
_TRACKING_CAP = 0.08

# 契约白名单（与 test_rendering_contract 同源）：本批禁止新增任何 keyframes。
_ALLOWED_KEYFRAMES = {"mica-drift-a", "mica-drift-b", "mica-drift-c"}


def _tpl(name: str) -> str:
    return (_TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """Jinja/HTML/CSS 注释全剥——注释里允许出现任意字样。"""
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


def _css_of(name: str) -> str:
    match = re.search(r"<style>(.*?)</style>", _strip_comments(_tpl(name)), re.DOTALL)
    assert match, f"{name} 缺少 <style> 块"
    return match.group(1)


def _css_rules(css: str) -> dict[str, str]:
    """选择器 → 规则体（多选择器规则逐个展开登记）。"""
    rules: dict[str, str] = {}
    for selector_group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for selector in selector_group.split(","):
            key = re.sub(r"\s+", " ", selector).strip()
            if key:
                rules[key] = rules.get(key, "") + " " + re.sub(r"\s+", " ", body).strip()
    return rules


def _has_decl(rule_body: str, prop: str, value: str) -> bool:
    """声明匹配（对冒号后空格不敏感：单行规则惯写 prop:value）。"""
    return re.search(rf"{re.escape(prop)}\s*:\s*{re.escape(value)}\b", rule_body) is not None


# ==================== 1. tabular-nums：数字数据等宽 ====================
@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_e03_template_has_tabular_nums(name: str) -> None:
    assert "font-variant-numeric: tabular-nums" in _css_of(name), (
        f"{name} 未含任何 tabular-nums（E03 数字等宽缺位）"
    )


@pytest.mark.parametrize("name", list(_NUMERIC_SELECTORS))
def test_e03_numeric_selectors_use_tabular_nums(name: str) -> None:
    rules = _css_rules(_css_of(name))
    missing = [
        sel
        for sel in _NUMERIC_SELECTORS[name]
        if not _has_decl(rules.get(sel, ""), "font-variant-numeric", "tabular-nums")
    ]
    assert not missing, f"{name} 数字选择器缺 tabular-nums: {missing}"


# ==================== 2. 字距统一刻度 ====================
@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_e03_letter_spacing_on_scale(name: str) -> None:
    text = _strip_comments(_tpl(name))
    values = [float(v) for v in re.findall(r"letter-spacing\s*:\s*([0-9.]+)em", text)]
    off_scale = [v for v in values if v not in _ALLOWED_TRACKING]
    assert not off_scale, f"{name} letter-spacing 脱离刻度 {sorted(_ALLOWED_TRACKING)}: {off_scale}"
    over_cap = [v for v in values if v > _TRACKING_CAP]
    assert not over_cap, f"{name} letter-spacing 超 0.08em 上限: {over_cap}"


@pytest.mark.parametrize("name", list(_LABEL_TRACKING))
def test_e03_small_label_tracking(name: str) -> None:
    rules = _css_rules(_css_of(name))
    missing = [
        sel
        for sel in _LABEL_TRACKING[name]
        if not _has_decl(rules.get(sel, ""), "letter-spacing", "0.06em")
    ]
    assert not missing, f"{name} 小标签缺 0.06em 字距: {missing}"


# ==================== 3. 行高统一刻度 + 大数字收敛 ====================
@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_e03_line_height_on_scale(name: str) -> None:
    text = _strip_comments(_tpl(name))
    values = [float(v) for v in re.findall(r"line-height\s*:\s*([0-9.]+)\s*[;}]?", text)]
    off_scale = [v for v in values if v not in _LINE_HEIGHT_SCALE]
    assert not off_scale, f"{name} line-height 脱离统一刻度 {sorted(_LINE_HEIGHT_SCALE)}: {off_scale}"


@pytest.mark.parametrize("name", list(_BIG_NUMBER_SELECTORS))
def test_e03_big_number_line_height_converged(name: str) -> None:
    rules = _css_rules(_css_of(name))
    for sel in _BIG_NUMBER_SELECTORS[name]:
        match = re.search(r"line-height\s*:\s*([0-9.]+)", rules.get(sel, ""))
        assert match, f"{name} {sel} 未声明行高（大数字须收敛 {_BIG_NUMBER_RANGE}）"
        value = float(match.group(1))
        assert _BIG_NUMBER_RANGE[0] <= value <= _BIG_NUMBER_RANGE[1], (
            f"{name} {sel} 大数字行高 {value} 超出 {_BIG_NUMBER_RANGE}"
        )


# ==================== 4. 标题 text-wrap: balance ====================
def test_e03_universal_title_balance() -> None:
    rules = _css_rules(_css_of("universal_card.html"))
    for sel in (".title", ".video-title-text"):
        assert _has_decl(rules.get(sel, ""), "text-wrap", "balance"), (
            f"universal_card.html {sel} 缺 text-wrap: balance（两行标题孤字悬尾）"
        )


# ==================== 5. 铁律零破坏（冗余防线） ====================
@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_e03_font_weight_cap_intact(name: str) -> None:
    weights = [int(v) for v in re.findall(r"font-weight\s*:\s*(\d+)", _strip_comments(_tpl(name)))]
    assert max(weights, default=0) <= 700, f"{name} 字重破 700 红线"


@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_e03_no_new_keyframes(name: str) -> None:
    names = set(re.findall(r"@keyframes\s+([\w-]+)", _css_of(name)))
    assert names <= _ALLOWED_KEYFRAMES, f"{name} 出现白名单外动画: {names - _ALLOWED_KEYFRAMES}"

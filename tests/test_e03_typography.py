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

from plugins.bot_unified_runtime.domains.render.card_render import bridge

# 模板清单＝单一派生取数口 `bridge.card_template_names()`（S-T-VISUAL-1 归一，
# 详见 tests/test_rendering_contract.py 同名注释；旧「显式枚举＝与
# test_rendering_contract 同口径手抄副本」正是 news_digest 脱管数个波次的根因）。
# 2026-09-18 v21r3：+= error 面；2026-09-25 S-T-NEWS-1：+= news 面（当时靠手抄，
# 现由派生源恒保证「目录有它 ⇒ 门扫它」，本文件不再可能「清单没数到它」）。
CARD_TEMPLATES: tuple[str, ...] = bridge.card_template_names()

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
    # 2026-09-25 S-T-NEWS-1：news_digest 面入册（条数徽章与条目时间戳都是数字件）。
    "news_digest_card.html": (
        ".badge",
        ".time",
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
    # S-T-NEWS-1：本面与 song 的 .ttl 是同位件（头部徽章），字距必须同档。
    "news_digest_card.html": (".badge",),
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

# ==================== 单一派生源：元数据覆盖完备锁（S-T-VISUAL-1，2026-09-26） ====================
# 清单已派生，「清单没数到它」型假绿被结构根除；剩下的是反向风险——**选择器级
# 登记表欠覆盖却无人点名**（表没这张面的键，参数化只按表跑，整场静默空转）。
# 判据：每枚欠覆盖名必须落在显式豁免册里带理由；豁免册只准减不准悄悄加新面
# （新面进豁免=它同时不在任何表里，双红灯由下方注毒腿的形态先例拦截）。
_NO_NUMERIC_SELECTORS: dict[str, str] = {
    # 实况登记（现算 2026-09-26）：error 面在盘，但从未入 _NUMERIC_SELECTORS；
    # 其 tabular-nums 存在性由 test_e03_template_has_tabular_nums 整面锁着，
    # 选择器级欠账归诊断卡面 owner 补，本锁负责「点名」而非「代修」。
    "error_card.html": "整面存在性有锁（下方全量 parametrize），选择器级登记欠账待诊断卡面 owner",
}
_NO_LABEL_TRACKING: dict[str, str] = {
    # 同型实况：error 面有 letter-spacing（值受全局面 _ALLOWED_TRACKING 刻度门
    # 覆盖），但小标签选择器未逐枚登记。
    "error_card.html": "字距值受全局面刻度门覆盖，小标签选择器登记欠账待补",
}


def _coverage_diff(
    inventory: tuple[str, ...],
    table: dict[str, tuple[str, ...]],
    exemptions: dict[str, str],
    label: str,
) -> list[str]:
    """登记表+豁免册 对派生清单的双向对账（真值腿与注毒腿共用一把尺）。"""
    problems: list[str] = []
    inv = set(inventory)
    unregistered = sorted(inv - set(table) - set(exemptions))
    if unregistered:
        problems.append(f"{label} 有面既未登记也未豁免（静默空转）: {unregistered}")
    stale = sorted(set(exemptions) - inv)
    if stale:
        problems.append(f"{label} 豁免册指向不在清单的面（豁免应随面退役删除）: {stale}")
    ghost = sorted(set(table) - inv)
    if ghost:
        problems.append(f"{label} 登记表指向不存在的模板: {ghost}")
    return problems


def test_selector_tables_cover_inventory_or_declared_exemption() -> None:
    assert not _coverage_diff(
        CARD_TEMPLATES, _NUMERIC_SELECTORS, _NO_NUMERIC_SELECTORS, "_NUMERIC_SELECTORS"
    )
    assert not _coverage_diff(
        CARD_TEMPLATES, _LABEL_TRACKING, _NO_LABEL_TRACKING, "_LABEL_TRACKING"
    )


def test_e03_coverage_lock_bites_on_unregistered_face(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒：多出一面未登记未豁免 ⇒ 判据必点名（否则完备锁是空跑的装饰）。"""
    for name in ("ghost_card.html",):
        (tmp_path / name).write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(bridge, "_TEMPLATES_DIR", tmp_path)
    ghost = bridge.card_template_names()
    assert ghost == ("ghost_card.html",)
    problems = _coverage_diff(ghost, _NUMERIC_SELECTORS, _NO_NUMERIC_SELECTORS, "n")
    assert any("ghost_card.html" in p for p in problems), f"注毒未咬住: {problems}"
    # 豁免册的陈腐腿也咬：豁免指向已消失的面同样点名。
    stale = _coverage_diff(
        ("universal_card.html",), _NUMERIC_SELECTORS, _NO_NUMERIC_SELECTORS, "n"
    )
    assert any("error_card.html" in p for p in stale), f"陈腐豁免未点名: {stale}"


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

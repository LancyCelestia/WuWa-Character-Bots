"""news_digest_card.html 的专属契约锁（2026-09-25/26 需求 18 项修复波 S-T-NEWS-1）。

为什么单独一件：这张卡是后增面，此前**三本手抄的模板清单都没数到它**
（test_token_supply_chain / test_v21r3_visual_gates / test_e03_typography 各一本，
本波已把它正式登记进去），于是攒下一批「只有它这么写」的脱族数值。常驻门补登记
只解决「有人扫它」，不解决「扫得着具体命题」——本件承担任务书点名的六条活性判据：

  1. 字号 / 字重 / 边框粗细 / 圆角 / 阴影族 / 间距 / 行高 / 字距 **逐项**来自登记常量；
  2. 每把尺都配注毒自证（写一条违规样本，断言该尺必红），否则「全绿」可能只是尺子瞎；
  3. 两栏键值结构存在且「属性名列 / 属性值列」各自同轨（含来源缺位时不撤轨）；
  4. 无 <meta viewport>、body 透明、色斑枚数=登记表且都在 .card 子树内；
  5. 超长标题/摘要/来源名**完整出现在渲染产物里**，全模板零 text-overflow / line-clamp；
  6. 斑马纹按**视觉行**取相——这条是真咬出来的：Jinja 里 `is` 比 `//` 结合更紧，
     ``loop.index0 // columns is even`` 会被读成 ``loop.index0 // (columns is even)``，
     columns=1 时除数是 False(0) 当场 ZeroDivisionError，columns=2 时除数是 True(1)、
     取相退化成逐条交替（棋盘）。姊妹面 song_candidates.html 今天正是这个无括号写法
     （本席禁改它，已报主代理），本件的注毒腿就把该坏写法在内存里跑一遍，证明判据有牙。

全部离线：纯文本 / Jinja2 渲染断言，不碰 playwright、不联网、不跑字节基线。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import jinja2
import pytest

from plugins.bot_unified_runtime.domains.render.card_render import bridge
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    BLOB_COUNT,
    BORDER_WIDTH_PX,
    CARD_SHELL_WIDTHS,
    FONT_FAMILY_STACK,
    FONT_WEIGHT_MAX,
    FONT_WEIGHT_STEPS,
    GAP_SCALE_PX,
    RADIUS_INNER_CSS_VARS,
    RADIUS_INNER_PX,
    RADIUS_PILL,
    SHADOW_CSS_VARS,
    TEXT_SECONDARY,
    TYPE_SCALE_PX,
)

# 单一取数口：行高刻度与字距刻度的真身在 E03 门里（值册未登记这两族，
# 本件不另抄第二份表——抄一份就等于改刻度时有一边失明）。
# 同一判据复用（硬缝色带扫描器），不复制正则：复制＝第二真身。
from tests.test_e03_typography import (
    _ALLOWED_TRACKING,
    _LINE_HEIGHT_SCALE,
    _TRACKING_CAP,
)
from tests.test_template_visual_audit import _scan_hard_stop_wash

TEMPLATE_NAME = "news_digest_card.html"
_TEMPLATES_DIR = Path(bridge.__file__).resolve().parent / "templates"
_TEMPLATE_PATH = _TEMPLATES_DIR / TEMPLATE_NAME
_SONG_PATH = _TEMPLATES_DIR / "song_candidates.html"

# 壳级圆角 token 名：值册登记了「内径」五档，壳/面板/瓦片/pill 由公共段注入；
# 本处按**名字**放行（值由 token 自己单源，模板不抄字面量）。
_RADIUS_TOKENS = {"--r-shell", "--r-panel", "--r-tile", "--r-pill", *RADIUS_INNER_CSS_VARS}
#: 圆角允许的字面量（契约 §四 RADIUS_INNER_PX 行 + 其登记特例）。
_RADIUS_LITERALS = {*(f"{int(v)}px" for v in RADIUS_INNER_PX), RADIUS_PILL, "50%", "0"}
#: box-shadow 合法取值：none 或 var() 引 SHADOW_CSS_VARS 登记族（族外一票否决）。
_SHADOW_ALLOWED = {"none"} | {f"var({name})" for name in SHADOW_CSS_VARS}

_SCALE_PX = {float(v) for v in TYPE_SCALE_PX.values()}
_WEIGHTS = {float(v) for v in FONT_WEIGHT_STEPS.values()}
_BORDERS = {float(v) for v in BORDER_WIDTH_PX}


def _source() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def _strip(text: str) -> str:
    """剥 Jinja/HTML/CSS 注释——注释里允许出现禁令字样。"""
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _code() -> str:
    return _strip(_source())


def _css() -> str:
    match = re.search(r"<style>(.*?)</style>", _code(), re.DOTALL)
    assert match, "news_digest 模板缺 <style> 块"
    return match.group(1)


def _rules(css: str) -> dict[str, str]:
    """选择器 → 归一化规则体（多选择器规则逐个展开，与 e03 同法）。"""
    out: dict[str, str] = {}
    for group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for selector in group.split(","):
            key = re.sub(r"\s+", " ", selector).strip()
            if key and not key.startswith("@"):
                out[key] = (out.get(key, "") + " " + re.sub(r"\s+", " ", body).strip()).strip()
    return out


def _render(items: list[dict[str, Any]] | None = None, **extra: Any) -> str:
    payload: dict[str, Any] = dict(extra)
    if items is not None:
        payload["items"] = items
    return bridge.render_news_digest_card_html(payload)


def _item_tints(html: str) -> list[str]:
    """条目瓦片的取相序列（a/b）——斑马纹活性判据的取数口。"""
    return re.findall(r'<div class="item glass"[^>]*?var\(--surface-([ab])\)', html)


# ==================== 1. 排版/描边数值逐项来自登记常量 ====================
def test_font_sizes_are_type_scale_rungs() -> None:
    """字号：模板里每一枚 font-size 字面量都必须是 TYPE_SCALE_PX 的档位值。"""
    used = {float(v) for v in re.findall(r"font-size\s*:\s*([\d.]+)px", _css())}
    assert used, "模板零 font-size？取数口失效"
    assert used <= _SCALE_PX, f"表外字号 {sorted(used - _SCALE_PX)}（合法档 {sorted(_SCALE_PX)}）"


def test_font_size_poison_is_caught() -> None:
    """注毒：表外字号必须被同一条尺点名（否则上一条可能只是空跑）。"""
    poisoned = ".a { font-size: 13.5px; } .b { font-size: 14px; }"
    caught = {
        float(v) for v in re.findall(r"font-size\s*:\s*([\d.]+)px", poisoned)
    } - _SCALE_PX
    assert caught == {13.5}, f"注毒未咬住：{caught}"


def test_font_weights_are_registered_steps_and_under_cap() -> None:
    weights = {float(v) for v in re.findall(r"font-weight\s*:\s*(\d+)", _css())}
    assert weights, "模板零 font-weight？取数口失效"
    assert weights <= _WEIGHTS, f"未登记字重 {sorted(weights - _WEIGHTS)}"
    assert max(weights) <= FONT_WEIGHT_MAX, "字重破 700 红线"


def test_font_weight_poison_is_caught() -> None:
    poisoned = ".a { font-weight: 650; } .b { font-weight: 600; }"
    caught = {
        float(v) for v in re.findall(r"font-weight\s*:\s*(\d+)", poisoned)
    } - _WEIGHTS
    assert caught == {650.0}, f"注毒未咬住：{caught}"


def test_border_widths_are_registered() -> None:
    widths = {float(v) for v in re.findall(r"\bborder\s*:\s*([\d.]+)px", _css())}
    assert widths, "模板零 border？取数口失效"
    assert widths <= _BORDERS, f"合法集外边框粗细 {sorted(widths - _BORDERS)}"


def test_border_width_poison_is_caught() -> None:
    poisoned = ".a { border: 3px solid #000; } .b { border: 1px solid transparent; }"
    caught = {
        float(v) for v in re.findall(r"\bborder\s*:\s*([\d.]+)px", poisoned)
    } - _BORDERS
    assert caught == {3.0}, f"注毒未咬住：{caught}"


def test_box_shadows_are_registered_family_only() -> None:
    values = {
        re.sub(r"\s+", " ", v).strip()
        for v in re.findall(r"box-shadow\s*:\s*([^;]+)(?:;|$)", _css())
    }
    assert values, "模板零 box-shadow？取数口失效"
    assert values <= _SHADOW_ALLOWED, f"族外阴影 {sorted(values - _SHADOW_ALLOWED)}"


def test_box_shadow_poison_is_caught() -> None:
    """注毒：自造阴影与 inset 内高光必须都被点名，登记那枚不得误伤（铁律 6）。"""
    registered = f"var({next(iter(SHADOW_CSS_VARS))})"
    poisoned = (
        ".a { box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2); }\n"
        ".b { box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5); }\n"
        f".c {{ box-shadow: {registered}; }}\n"
    )
    values = {
        re.sub(r"\s+", " ", v).strip()
        for v in re.findall(r"box-shadow\s*:\s*([^;]+)(?:;|$)", poisoned)
    }
    assert sorted(values - _SHADOW_ALLOWED) == [
        "0 2px 4px rgba(0, 0, 0, 0.2)",
        "inset 0 1px 0 rgba(255, 255, 255, 0.5)",
    ], f"注毒杀伤力不符：{sorted(values - _SHADOW_ALLOWED)}"


def test_border_radius_is_registered_track_or_token() -> None:
    for value in re.findall(r"border-radius\s*:\s*([^;{}]+)", _css()):
        value = re.sub(r"\s+", " ", value).strip()
        token = re.fullmatch(r"var\((--[a-z-]+)\)", value)
        if token:
            assert token.group(1) in _RADIUS_TOKENS, f"未登记圆角 token: {value}"
        else:
            assert value in _RADIUS_LITERALS, f"圆角自造值: {value}"


def test_border_radius_poison_is_caught() -> None:
    poisoned = ".a { border-radius: 7px; } .b { border-radius: var(--radius-lg); }"
    caught: list[str] = []
    for value in re.findall(r"border-radius\s*:\s*([^;{}]+)", poisoned):
        value = re.sub(r"\s+", " ", value).strip()
        token = re.fullmatch(r"var\((--[a-z-]+)\)", value)
        if token:
            if token.group(1) not in _RADIUS_TOKENS:
                caught.append(value)
        elif value not in _RADIUS_LITERALS:
            caught.append(value)
    assert caught == ["7px", "var(--radius-lg)"], f"注毒未咬住：{caught}"


def test_gaps_are_on_registered_scale() -> None:
    gaps = {int(v) for v in re.findall(r"\bgap\s*:\s*(\d+)px", _css())}
    assert gaps, "模板零 gap？取数口失效"
    assert gaps <= GAP_SCALE_PX, f"自造间距 {sorted(gaps - GAP_SCALE_PX)}"


def test_gap_poison_is_caught() -> None:
    caught = [
        int(v)
        for v in re.findall(r"\bgap\s*:\s*(\d+)px", ".a { gap: 9px; } .b { gap: 10px; }")
        if int(v) not in GAP_SCALE_PX
    ]
    assert caught == [9], f"注毒未咬住：{caught}"


def test_line_heights_are_on_unified_scale() -> None:
    """行高：1.55 曾是本面独有的脱刻度点（全树仅 1 处），已改回 1.6=长正文档档。"""
    values = {float(v) for v in re.findall(r"line-height\s*:\s*([0-9.]+)", _css())}
    assert values, "模板零 line-height？取数口失效"
    assert values <= _LINE_HEIGHT_SCALE, (
        f"行高脱离统一刻度 {sorted(values - _LINE_HEIGHT_SCALE)}"
    )


def test_line_height_poison_is_caught() -> None:
    assert 1.55 not in _LINE_HEIGHT_SCALE, "刻度表若收编 1.55，本注毒腿要一起改"
    caught = [
        float(v)
        for v in re.findall(
            r"line-height\s*:\s*([0-9.]+)",
            ".a { line-height: 1.55; } .b { line-height: 1.6; }",
        )
        if float(v) not in _LINE_HEIGHT_SCALE
    ]
    assert caught == [1.55], f"注毒未咬住：{caught}"


def test_letter_spacing_is_on_unified_scale() -> None:
    """字距：0.04em 曾是本面独有脱刻度点，已改回 0.06em（小标签标准档）。"""
    values = {float(v) for v in re.findall(r"letter-spacing\s*:\s*([0-9.]+)em", _css())}
    assert values <= _ALLOWED_TRACKING, (
        f"字距脱离刻度 {sorted(values - _ALLOWED_TRACKING)}"
    )
    assert not [v for v in values if v > _TRACKING_CAP], "字距超 0.08em 上限"


def test_letter_spacing_poison_is_caught() -> None:
    caught = [
        float(v)
        for v in re.findall(
            r"letter-spacing\s*:\s*([0-9.]+)em",
            ".a { letter-spacing: 0.04em; } .b { letter-spacing: 0.06em; }",
        )
        if float(v) not in _ALLOWED_TRACKING
    ]
    assert caught == [0.04], f"注毒未咬住：{caught}"


def test_secondary_gray_equals_registry_value() -> None:
    """次级灰单源：模板手抄的那枚必须与 theme_tokens.TEXT_SECONDARY 逐字符等值。"""
    declared = re.search(r"--text-secondary\s*:\s*(#[0-9a-fA-F]{6})", _css())
    assert declared, "模板缺 --text-secondary 定义"
    assert declared.group(1) == TEXT_SECONDARY, (
        f"模板 {declared.group(1)} ≠ 值册 {TEXT_SECONDARY}（改值册要一起改本面）"
    )


def test_font_family_is_consumed_not_recopied() -> None:
    """字体族只走公共注入键；栈字面量若出现在模板里必须与 FONT_FAMILY_STACK 逐字一致。"""
    assert "font-family: var(--font-family)" in _css()
    for literal in re.findall(r"font-family\s*:\s*([^;{}]+)", _css()):
        literal = re.sub(r"\s+", " ", literal).strip()
        assert literal.startswith("var(") or literal == FONT_FAMILY_STACK, (
            f"自造字体族: {literal}"
        )


# ==================== 2. 家族节奏对账（与姊妹面 song 同值，防重新分叉） ====================
def test_family_rhythm_matches_sibling_song_face() -> None:
    """头区底衬 / 列表顶衬 / 页脚摆位：同族卡就该同数值。

    两头都读**文件现值**（不在本件抄常量）：song 一改，本面若不同步即红——
    这正是「一处变更处处跟随」要的报警，不是误伤。
    """
    song_rules = _rules(_css_of(_SONG_PATH))
    mine = _rules(_css())
    for selector, prop in (
        (".head", "padding"),
        (".list", "padding"),
        (".capsule-foot", "margin"),
        (".sub", "margin-top"),
    ):
        theirs = re.search(rf"{prop}\s*:\s*([^;]+)", song_rules.get(selector, ""))
        ours = re.search(rf"{prop}\s*:\s*([^;]+)", mine.get(selector, ""))
        assert theirs and ours, f"{selector} 的 {prop} 在某一面缺席（song={bool(theirs)} news={bool(ours)}）"
        assert ours.group(1).strip() == theirs.group(1).strip(), (
            f"{selector} {prop} 脱离家族节奏：news={ours.group(1)!r} song={theirs.group(1)!r}"
        )


def _css_of(path: Path) -> str:
    text = _strip(path.read_text(encoding="utf-8"))
    match = re.search(r"<style>(.*?)</style>", text, re.DOTALL)
    assert match, f"{path.name} 缺 <style> 块"
    return match.group(1)


def test_glass_surface_equals_registered_main_plus_edge() -> None:
    """.glass 双背景必须恰是 GLASS_MAIN + GLASS_EDGE 登记值（零私调 alpha）。

    D-9（渲染统一波 2026-10-03）后面侧取 var() 消费形态：值册 GLASS_* 单源、
    公共段注入、值逐字节等值（「字面或 var() 等值皆合法」裁定见
    test_template_visual_audit.py 的 _GLASS_VAR_* 注）。本面已退役手抄字面
    ⇒ 锁 var() 双 token 恰形，防私调 alpha 回潮。
    """
    body = _rules(_css()).get(".glass", "")
    assert "background: var(--mica-glass-main), var(--mica-glass-edge)" in body, (
        f".glass 填充/描边层脱离 GLASS_MAIN/GLASS_EDGE 的登记 var 形态: {body!r}"
    )
    assert "border: 1px solid transparent" in body, ".glass 缺透明边框（双 attach 前提）"
    assert "box-shadow: var(--mica-shadow-panel)" in body, ".glass 缺 L2 面板阴影档"


def test_shell_width_and_wash_are_registered() -> None:
    body = _rules(_css()).get(".panel", "")
    width = CARD_SHELL_WIDTHS["news_digest"]
    assert f"width: {width}px" in body, f"壳宽与登记表 {width}px 不符: {body!r}"
    assert "var(--mica-shell-wash) padding-box, var(--mica-glass-edge)" in body, (
        "壳底不是公共渐变单源（自抄色标=第二真身）"
    )


# ==================== 3. 两栏 + 属性名/属性值同轨 ====================
def test_item_uses_fixed_label_track_and_fluid_value_track() -> None:
    """.item 定轨：来源列恒 104px（属性名轴）+ 正文 minmax(0,1fr)（属性值轴）。"""
    body = _rules(_css()).get(".item", "")
    assert "grid-template-columns: 104px minmax(0, 1fr)" in body, f".item 未定轨: {body!r}"
    src = _rules(_css()).get(".src", "")
    assert "width: 104px" in src, f"来源列宽与轨宽不等: {src!r}"
    assert "text-align: left" in src, "来源列须左对齐才成轴"


def test_two_column_tracks_are_equal_width() -> None:
    body = _rules(_css()).get(".list.two-col", "")
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in body, (
        f"两栏不等宽则跨条目、跨栏都无法成轴: {body!r}"
    )


def test_missing_source_keeps_the_label_track() -> None:
    """来源缺位只停墨不撤轨：.src:empty 把底色/描边转透明，列宽仍占住。"""
    body = _rules(_css()).get(".src:empty", "")
    assert "background: transparent" in body and "border-color: transparent" in body, (
        f"缺 .src:empty 收口（缺来源的条目会把正文列顶偏）: {body!r}"
    )
    html = _render([{"name": "有来源", "source": "V2EX"}, {"name": "没来源"}])
    assert html.count('class="src"') == 2, "每条必须各有一枚来源格（哪怕空）"


def test_name_and_time_are_one_axis_pair() -> None:
    """标题 flex:1 + 时间 flex-shrink:0 → 两栏等宽格内时间右轨对齐成列。"""
    name = _rules(_css()).get(".name", "")
    time = _rules(_css()).get(".time", "")
    assert "flex: 1" in name and "min-width: 0" in name, f".name 未撑开: {name!r}"
    assert "flex-shrink: 0" in time, f".time 会被挤压，右轨不成轴: {time!r}"


def test_column_switch_follows_item_count() -> None:
    """≥4 条走两栏，<4 条单栏（单栏两三条时铺两栏会留半张空卡）。"""
    three = _render([{"name": f"n{i}"} for i in range(3)]).split("<body>", 1)[1]
    assert 'class="list">' in three, f"3 条应留单栏: {three[:200]!r}"
    four = _render([{"name": f"n{i}"} for i in range(4)]).split("<body>", 1)[1]
    assert 'class="list two-col"' in four, "4 条应切两栏"


def test_zebra_follows_visual_rows_not_items() -> None:
    """斑马纹按视觉行取相：两栏下同行两枚同色，单栏下逐行交替。

    这一条就是 Jinja 优先级坑的活性判据——去掉括号即退化成逐条交替（棋盘），
    单栏下更直接 ZeroDivisionError。
    """
    two = _render([{"name": f"n{i}"} for i in range(6)])
    assert _item_tints(two) == ["a", "a", "b", "b", "a", "a"]
    one = _render([{"name": f"n{i}"} for i in range(3)])
    assert _item_tints(one) == ["a", "b", "a"]


def test_zebra_poison_without_parentheses_is_broken() -> None:
    """注毒腿：把取相算式的括号去掉（=姊妹面 song 的现行写法），行为必变。

    只在内存里跑，不碰任何文件——证明上一条判据确实咬得住这个坏写法。
    """
    good = jinja2.Environment().from_string(
        "{% for i in items %}{{ 'T' if (loop.index0 // 2) is even else 'F' }}{% endfor %}"
    ).render(items=[0] * 6)
    bad = jinja2.Environment().from_string(
        "{% for i in items %}{{ loop.index0 // 2 is even }}{% endfor %}"
    ).render(items=[0] * 6)
    assert good == "TTFFTT", good  # 视觉行 0,0 / 1,1 / 2,2
    assert bad == "012345", bad  # // (2 is even) → // 1：逐条交替=棋盘
    with pytest.raises(ZeroDivisionError):
        jinja2.Environment().from_string(
            "{% for i in items %}{{ loop.index0 // 1 is even }}{% endfor %}"
        ).render(items=[0])


# ==================== 4. 铁律：viewport / body 透明 / 色斑在 .card 内 ====================
def test_no_meta_viewport() -> None:
    assert not re.search(r"<meta[^>]*viewport", _code(), re.IGNORECASE)


def test_body_is_transparent() -> None:
    assert "background: transparent" in _rules(_css()).get("body", "")


def test_root_element_carries_card_class() -> None:
    body = _code().split("<body>", 1)[1].lstrip()
    assert body.startswith('<div class="card"'), "根元素必须带 card 类（后端固定截 .card）"


class _BlobScope(HTMLParser):
    """色斑枚数 + 是否落在 .card 子树内（截图契约的活性面）。"""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.card_depth: int | None = None
        self.blobs = 0
        self.outside = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if tag == "div" and self.card_depth is None and "card" in classes:
            self.card_depth = self.depth
        if "drift-blob" in classes:
            self.blobs += 1
            if self.card_depth is None or self.depth <= self.card_depth:
                self.outside += 1
        if tag not in ("img", "br", "meta", "link", "input", "hr"):
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag not in ("img", "br", "meta", "link", "input", "hr") and self.depth > 0:
            self.depth -= 1


def test_drift_blobs_count_and_stay_inside_card() -> None:
    parser = _BlobScope()
    parser.feed(_render([{"name": "n", "source": "S", "time": "09:00", "snip": "s"}]))
    assert parser.card_depth is not None, "渲染产物里找不到 .card 根"
    assert parser.blobs == BLOB_COUNT, f"色斑 {parser.blobs} 枚 ≠ 登记表 {BLOB_COUNT} 枚"
    assert parser.outside == 0, "有色斑越出 .card 子树（截图会把它裁掉）"


def test_blob_phase_is_per_face_and_deterministic() -> None:
    """构图不雷同的腿=face 盐：本面相位与别面互异，且同载荷两次渲染逐字节等值。"""
    payload: dict[str, Any] = {"items": [{"name": "X", "snip": "s"}], "title": "T"}
    mine = bridge.payload_phase(dict(payload), face="news_digest")
    others = {
        face: bridge.payload_phase(dict(payload), face=face)
        for face in ("universal", "market", "song", "error", "mermaid", "affinity", "finance")
    }
    assert mine not in others.values(), f"与这些面撞相位=色斑构图同形: {others}"
    assert _render(items=payload["items"], title="T") == _render(
        items=payload["items"], title="T"
    ), "同载荷两次渲染不等值=非确定（钉帧与字节基线会飘）"


def test_rendered_output_has_no_hard_stop_colour_seam() -> None:
    """交割线不得读成一条直线：任何 linear-gradient 相邻两停「同位异色」=硬缝。

    与 test_template_visual_audit 同判据，但扫的是**渲染产物**（含 bridge 注入的
    公共段与色斑层）——门那侧只扫模板源码，注入段正是它的盲区。
    """
    html = _render([{"name": "n", "source": "S", "snip": "s"}])
    offenders = _scan_hard_stop_wash(html)
    assert not offenders, f"渲染产物出现硬停色带: {offenders}"


# ==================== 5. 零静默截断：长文完整出现 ====================
_LONG_TITLE = "科技快讯" * 30  # 120 字卡题
_LONG_SUB = "副标" * 40
_LONG_NAME = "长标题条目" * 25  # 150 字条目标题
_LONG_SNIP = "这条摘要非常长，用来验证它不会被钳成半截。" * 12
_LONG_SOURCE = "某个长得离谱的站点显示名称" * 3
_LONG_FOOT = "数据口径说明" * 20


def test_no_ellipsis_or_clamp_anywhere_in_template() -> None:
    css = _css()
    assert "text-overflow" not in css, "本面零省略号是硬要求（来源名曾被切尾）"
    assert "line-clamp" not in css, "摘要不得钳行（钳掉的是信息）"


def test_every_text_bearing_rule_wraps() -> None:
    """会被长文撑开的每一档都要显式可折行，否则靠默认不折=静默溢出。"""
    rules = _rules(_css())
    for selector in (".title", ".sub", ".name", ".snip", ".src", ".foot", ".empty"):
        assert "overflow-wrap: anywhere" in rules.get(selector, ""), (
            f"{selector} 缺 overflow-wrap: anywhere（长文本会溢出或撞破轨道）"
        )


def test_long_texts_render_in_full() -> None:
    html = _render(
        [{"name": _LONG_NAME, "source": _LONG_SOURCE, "time": "09:00", "snip": _LONG_SNIP}],
        title=_LONG_TITLE,
        sub=_LONG_SUB,
        foot=_LONG_FOOT,
    )
    for needle in (_LONG_TITLE, _LONG_SUB, _LONG_NAME, _LONG_SNIP, _LONG_SOURCE, _LONG_FOOT):
        assert needle in html, f"渲染产物缺完整文本片段：{needle[:18]}…"


def test_many_items_all_render() -> None:
    items = [{"name": f"条目 {i}", "source": f"源{i}", "snip": f"摘要{i}"} for i in range(20)]
    html = _render(items)
    for item in items:
        assert item["name"] in html and item["source"] in html, f"有条目被吞：{item}"
    assert html.count('class="item glass"') == 20


# ==================== 6. 人话面：零机器字面量、键名全在册 ====================
def test_template_references_only_registered_card_text_keys() -> None:
    """card_text.<键> 必须全在 bridge._CARD_TEXT 里。

    Jinja 对未知键静默渲染成空——写错一个键＝卡面上那句话没了而不报错，
    属于最典型的「装配期绿、跑起来缺字」。
    """
    used = set(re.findall(r"card_text\.([a-z0-9_]+)", _code()))
    assert used, "模板一处 card_text 都没引用？取数口失效"
    unknown = sorted(used - set(bridge._CARD_TEXT))
    assert not unknown, f"模板引用了未登记的文案键（会静默变空白）: {unknown}"


def test_rendered_static_text_has_no_machine_labels_or_leaks() -> None:
    """卡面文本不得出现机器键名/字段名/未渲染占位（不是人话=回炉）。"""
    html = _render([{"name": "某条新闻"}])  # source/time/snip 全缺位
    text_nodes = re.sub(r"<[^>]+>", " ", html.split("<body>", 1)[1])
    for banned in (
        "static_news",
        "card_text",
        "Undefined",
        "None",
        "{{",
        "source",
        "snip",
        "payload",
        "px",
    ):
        assert banned not in text_nodes, f"卡面出现非人话/泄漏物: {banned!r}"


def test_empty_payload_renders_placeholder_and_never_raises() -> None:
    cases: tuple[Any, ...] = (None, {}, {"items": []}, {"items": ["不是字典"]})
    for payload in cases:
        html = bridge.render_news_digest_card_html(payload)  # type: ignore[arg-type]
        assert bridge._CARD_TEXT["static_news_70"] in html, (
            "空态没出占位（铁律 7 的纯文本兜底之外，卡面也不能是空壳）"
        )
        assert 'class="item' not in html, "空态不该有残条目"


# ==================== 6b. 能力侧卡面静态文案必须入 _CARD_TEXT 册（S-T-VISUAL-1） ====================
#: 本面专属的两枚「payload 供给型」静态文案：模板不硬编码了，但字面量一度
#: 住在能力域（news.py 顶部的 `_CARD_FOOT = "…"` / `_CARD_FEATURE_LABEL = "…"`），
#: 对契约 §二「字面量唯一落点 = bridge._CARD_TEXT」同样是失守。本段把这条
#: 边界钉成机器门：值必须与登记表逐字符等值，且 news.py 里必须是取数口调用、
#: 不是字面量赋值。
_CAPABILITY_COPY_KEYS = {
    "_CARD_FOOT": "static_news_71",
    "_CARD_FEATURE_LABEL": "static_news_72",
}
_NEWS_PY = (
    Path(bridge.__file__).resolve().parents[2]
    / "subscribe" / "capabilities" / "news.py"
)


def _registry_sourced_names(source: str) -> dict[str, str | None]:
    """AST 现算：每个目标名 → 取数键（非 `card_text_value("键")` 形态记 None）。"""
    import ast

    out: dict[str, str | None] = {}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id in _CAPABILITY_COPY_KEYS):
                continue
            value = node.value
            key: str | None = None
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "card_text_value"
                and len(value.args) == 1
                and isinstance(value.args[0], ast.Constant)
                and isinstance(value.args[0].value, str)
            ):
                key = value.args[0].value
            out[target.id] = key
    return out


def test_capability_card_copy_values_equal_the_registry() -> None:
    from plugins.bot_unified_runtime.domains.subscribe.capabilities import news

    assert news._CARD_FOOT == bridge._CARD_TEXT["static_news_71"]
    assert news._CARD_FEATURE_LABEL == bridge._CARD_TEXT["static_news_72"]


def test_capability_card_copy_is_registry_sourced_not_recopied() -> None:
    """news.py 里两枚常量必须是 `card_text_value("static_news_*")` 调用。"""
    sourced = _registry_sourced_names(_NEWS_PY.read_text(encoding="utf-8"))
    assert sourced == _CAPABILITY_COPY_KEYS, (
        f"两枚卡面文案常量必须且只能各出现一次、走登记表取数口：{sourced}"
    )
    for key in sourced.values():
        assert key in bridge._CARD_TEXT, f"取数键 {key!r} 不在册（装配期 KeyError 前移到测试）"


def test_registry_source_lock_bites_on_literal_assignment() -> None:
    """注毒自证：把字面量赋值塞回能力域，判据必须点名（否则 6b 是装饰）。"""
    poisoned = '_CARD_FOOT = "条目取自各来源的公开订阅源，标题与摘要按原文收录，未作核实。"'
    sourced = _registry_sourced_names(poisoned)
    assert sourced == {"_CARD_FOOT": None}, f"注毒未咬住：{sourced}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

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

from plugins.bot_unified_runtime.domains.render.card_render import bridge
from plugins.bot_unified_runtime.domains.render.card_render import theme_tokens as _tt
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    BRAND_THEME,
    SHADOW_CSS_VARS,
    SURFACE_TINTS,
    TEXT_SECONDARY,
)

_TEMPLATES_DIR = Path(bridge.__file__).resolve().parent / "templates"

# 液态玻璃瓦片表面要素。D-9 迁移后取相（渲染统一波 2026-10-03）：
# 「字面或 var() 等值皆合法」——面侧可继续写登记字面量（padding-box+border-box
# 双 attach 形态），也可消费 var(--mica-glass-main)/var(--mica-glass-edge)
# （值册 GLASS_* 单源、公共段注入，值逐字节等值）。玻璃描边 token 消费形态下，
# 填充允许玻璃主档 token 或 --surface-* 染色面 + 字面 padding-box（error .row 形态）。
# 透明边框 + L2 面板阴影 token 两要素与形态无关，恒查。
_GLASS_VAR_MAIN = "var(--mica-glass-main)"
_GLASS_VAR_EDGE = "var(--mica-glass-edge)"
_GLASS_STRUCTURAL_MARKERS = (
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
    """瓦片化审计：列表行瓦片必须带液态玻璃表面（vis2 固化；D-9 后字面/var() 皆合法）。"""
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
        if base is None:
            # var() 等值形态：描边 token 必消费；填充＝玻璃主档 token，
            # 或 --surface-* 染色面 + 字面 padding-box（error .row 形态）。
            base = next(
                (
                    body
                    for body in bodies
                    if _GLASS_VAR_EDGE in body
                    and (_GLASS_VAR_MAIN in body or "padding-box" in body)
                ),
                None,
            )
        assert base is not None, (
            f"{name} {selector} 缺玻璃表面（字面 padding/border-box 双 attach"
            f" 或 {_GLASS_VAR_EDGE} 消费）"
        )
        for marker in _GLASS_STRUCTURAL_MARKERS:
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
# 可编辑模板集＝**单一派生取数口** `bridge.card_template_names()`（S-T-VISUAL-1
# 归一，2026-09-26）。旧手抄副本没数到后增的 news 面，该面靠本文件另一枚
# 「单独点名」锁补票入场（见 test_news_digest_face_*）——派生后管辖面恒等于
# 目录现走，单独点名降为防回潮自证，不再是唯一覆盖 news 的腿。
_EDITABLE_TEMPLATES: tuple[str, ...] = bridge.card_template_names()
# 旧散灰（vis5 前各模板私有的次级文字色，全部收编 TEXT_SECONDARY）。
# 2026-09-18 v21r3 渲染统一：+= #555/#444/#999（universal 遗留 legacy 灰，
# RED 即 wave-2 锚点：收编 --text-secondary 单一来源）。
_LEGACY_SECONDARY_GRAYS = (
    "#7a828c",
    "#8a919b",
    "#66727f",
    "#7a8699",
    "#57626f",
    "#4a5560",
    "#555",
    "#444",
    "#999",
)


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
    # 取真身而非在本文件手抄色值：抄一份＝第二真身，改值册时这条门会
    # 一边绿一边测着旧值（2026-09-25 洗色加深当天就撞到这个形态）。
    text_sub = _hex_rgb(BRAND_THEME.text_sub)
    secondary = _hex_rgb(TEXT_SECONDARY)
    for key, surface in surfaces.items():
        assert _contrast(text_sub, surface) >= 4.5, f"text_sub 对 {key} 对比不足"
        assert _contrast(secondary, surface) >= 4.5, (
            f"TEXT_SECONDARY({TEXT_SECONDARY}) 对 {key} 对比不足"
        )


def _public_segment_text() -> str:
    """render_root_tokens 公共段现算样张（D-4 单源注入的取数真身，不手抄值）。"""
    from plugins.bot_unified_runtime.domains.render.card_render.mica_shell import (
        render_root_tokens,
    )

    return render_root_tokens(
        accent=_tt.BRAND_ACCENT,
        accent_dark="#2771b5",
        wash=_tt.DEFAULT_WASH_TOKENS,
    )


@pytest.mark.parametrize("name", _EDITABLE_TEMPLATES)
def test_secondary_gray_single_source(name: str) -> None:
    """次级灰单源锁（D-4 后取相：等值手抄或公共段单源消费皆合法）。

    - 面内仍手写 ``--text-secondary: #hex`` 的，值必须与 TEXT_SECONDARY 等值
      （等值手抄合法，改值册不同步的病由等值锁看着）；
    - 已撤手抄的面（现势 error_card）必须消费 var(--text-secondary)，且公共段
      注入值恒等于值册——两条路都只有一种合法值，旧散灰照旧清零。
    """
    text = _strip_comments(_tpl(name))
    match = re.search(r"--text-secondary:\s*(#[0-9a-fA-F]{6})", text)
    if match is None:
        assert "var(--text-secondary)" in text, (
            f"{name} 既无 --text-secondary 等值声明也不消费 var(--text-secondary)"
        )
        assert f"--text-secondary:{TEXT_SECONDARY}" in _public_segment_text(), (
            "render_root_tokens 公共段未注入 TEXT_SECONDARY 单源值"
        )
    else:
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


# ==================== goal-7 统一波（2026-09-25）：排版/描边/wash 接缝/色斑雷同 ====================
# 裁定出处=澜汐 goal 第 7 项「所有 HTML 模板过一遍，视觉规格统一」六命题。
# 执法面=本席可写面（8 张 Jinja 模板 + 2 张自有直拼卡 + mica_shell 公共段）；
# echo/debug 两枚直拼卡的字号脱档在案（契约 §八 D-5），非本席可写面，由
# tests/test_mica_builders_contract.py 的既有下限门继续看着，不在此重复放行。

_RENDER_PKG_DIR = Path(bridge.__file__).resolve().parent.parent  # domains/render/
_OWNED_FSTRING_FACES: tuple[str, ...] = (
    "card_render/usage_cards.py",
    "templates.py",
    "card_render/mica_shell.py",
)
_NEWS_DIGEST_TEMPLATE = "news_digest_card.html"

# 合法集从值册动态派生（改值册=全部门跟随，不手抄第二份表）。
_SCALE_VALUES = {float(v) for v in _tt.TYPE_SCALE_PX.values()}
_WEIGHT_VALUES = {float(v) for v in _tt.FONT_WEIGHT_STEPS.values()}
_BORDER_VALUES = {float(v) for v in _tt.BORDER_WIDTH_PX}


def _owned_face_sources() -> list[tuple[str, str]]:
    """(面名, 去注释源码文本)——全部本席可写渲染面。

    Jinja 侧 = 派生清单（news 面自 2026-09-26 归一后天然在列，不再单独追加，
    追加会与派生重复计面）。"""
    faces = [(name, _tpl(name)) for name in _EDITABLE_TEMPLATES]
    for rel in _OWNED_FSTRING_FACES:
        path = _RENDER_PKG_DIR / rel
        faces.append((rel, path.read_text(encoding="utf-8")))
    return [(name, _strip_comments(text)) for name, text in faces]


def _scan_offscale_font_sizes(text: str) -> list[str]:
    """font-size 字面量 ∉ TYPE_SCALE_PX 值集 → 逐处点名（含内联 style 写法）。"""
    return sorted(
        f"{v:g}px"
        for v in (float(m) for m in re.findall(r"font-size\s*:\s*([\d.]+)px", text))
        if v not in _SCALE_VALUES
    )


def _scan_unregistered_font_weights(text: str) -> list[str]:
    """font-weight 数值 ∉ FONT_WEIGHT_STEPS 值集 → 逐处点名。"""
    return sorted(
        {
            v
            for v in re.findall(r"font-weight\s*:\s*(\d+)", text)
            if float(v) not in _WEIGHT_VALUES
        }
    )


def _scan_illegal_border_widths(text: str) -> list[str]:
    """border 粗细字面量 ∉ BORDER_WIDTH_PX 合法集 → 逐处点名（outline 不算）。"""
    return sorted(
        f"{v:g}px"
        for v in (float(m) for m in re.findall(r"\bborder\s*:\s*([\d.]+)px", text))
        if v not in _BORDER_VALUES
    )


def _extract_gradients(text: str, kind: str) -> list[str]:
    """平衡括号提取 ``kind(`` 起始的完整渐变表达式（支持 color-mix 嵌套括号）。"""
    out: list[str] = []
    idx = 0
    needle = kind + "("
    while True:
        start = text.find(needle, idx)
        if start < 0:
            return out
        depth = 0
        i = start + len(needle) - 1
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    out.append(text[start : i + 1])
                    break
            i += 1
        idx = start + 1


def _split_top_level(arg_text: str) -> list[str]:
    """按顶层逗号切 gradient 参数（括号内不切）。"""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in arg_text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return parts


def _scan_hard_stop_wash(text: str) -> list[str]:
    """颜色边界读成直线的形态：linear-gradient 相邻两停「同位异色」= 硬缝。

    radial 色斑天然无直线接缝不查；同色两停（纯色填充形态）不算接缝；
    GLASS_EDGE 0/55/100、壳渐变 0/15/32/…/100 等平滑多档天然放行。
    """
    offenders: list[str] = []
    import itertools

    for grad in _extract_gradients(text, "linear-gradient"):
        inner = grad[len("linear-gradient(") : -1]
        args = _split_top_level(inner)
        stops = [a.strip() for a in args if a.strip()]
        # 方向参数（145deg / to right 之类）只在首参位置时剔除。
        if stops and re.fullmatch(r"(?:-?[\d.]+(?:deg|turn|rad|grad)|to [a-z ]+)", stops[0]):
            stops = stops[1:]
        for prev, nxt in itertools.pairwise(stops):
            pos_prev = re.search(r"([\d.]+)%\s*$", prev)
            pos_next = re.search(r"([\d.]+)%\s*$", nxt)
            if not (pos_prev and pos_next):
                continue
            if pos_prev.group(1) == pos_next.group(1):
                color_prev = prev[: pos_prev.start()].strip()
                color_next = nxt[: pos_next.start()].strip()
                if color_prev != color_next:
                    offenders.append(grad[:72])
                    break
    return offenders


def test_owned_faces_font_size_within_type_scale() -> None:
    """命题①：字号阶梯单一来源——本席可写面零表外 font-size 字面量。"""
    offenders = {
        name: bad for name, text in _owned_face_sources() if (bad := _scan_offscale_font_sizes(text))
    }
    assert not offenders, f"表外字号（TYPE_SCALE_PX 之外）：{offenders}"


def test_owned_faces_font_weight_within_registered_steps() -> None:
    """命题①：字重只准取 FONT_WEIGHT_STEPS（650 手抄副本本波 16 处全数收敛 600）。"""
    offenders = {
        name: bad for name, text in _owned_face_sources() if (bad := _scan_unregistered_font_weights(text))
    }
    assert not offenders, f"未登记字重：{offenders}"


def test_owned_faces_border_width_within_registered_set() -> None:
    """命题②：边框粗细合法集（hairline 1px / ring 2px，ring 仅头像图标环）。"""
    offenders = {
        name: bad for name, text in _owned_face_sources() if (bad := _scan_illegal_border_widths(text))
    }
    assert not offenders, f"合法集外边框粗细：{offenders}"


def test_owned_faces_wash_has_no_hard_stop_linear_gradient() -> None:
    """命题③：颜色边界不得读成一条直线——任何面禁「同位异色双停」硬缝渐变。"""
    offenders = {
        name: bad for name, text in _owned_face_sources() if (bad := _scan_hard_stop_wash(text))
    }
    assert not offenders, f"硬停 linear-gradient 接缝：{offenders}"


# 本波通电的全部卡面身份（face 盐）；跨面 --phase 必互异（同 payload 亦然）。
_FACE_REGISTRY: tuple[str, ...] = (
    "universal",
    "market",
    "finance",
    "song",
    "news_digest",
    "affinity",
    "error",
    "mermaid",
    "media",
    "usage",
)


def test_blob_phase_face_salt_pairwise_distinct() -> None:
    """命题③：色斑构图不得跨卡雷同——同一 payload 下各面 --phase 必两两互异。

    相位是色斑 animation-delay 的唯一变量（钉帧下决定逐斑位置），face 盐失效
    即两卡构图逐字节同形——本门即那条腿。缺省 face="" 保持旧行为逐字节不变
    （既有单参调用与样张基线的兼容腿）。
    """
    payload = {"shared": "same-payload-for-every-face", "n": 1}
    phases = [bridge.payload_phase(payload, face=face) for face in _FACE_REGISTRY]
    assert len(set(phases)) == len(phases), f"跨面相位撞车：{dict(zip(_FACE_REGISTRY, phases))}"
    assert bridge.payload_phase(payload) == bridge.payload_phase(payload, face="")


def test_face_registry_covers_every_bridged_jinja_face() -> None:
    """face 盐不许漏面：bridge 里每个以 payload_phase 定相位的 render_* 都必须
    传非空 face 字面量，且这些字面量集合恰等于 8 张 Jinja 面登记表。"""
    import ast

    tree = ast.parse(Path(bridge.__file__).resolve().read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("render_"):
            continue
        for call in (c for c in ast.walk(node) if isinstance(c, ast.Call)):
            fn = call.func
            if isinstance(fn, ast.Name) and fn.id == "payload_phase":
                face = {k.arg: k.value for k in call.keywords}.get("face")
                assert isinstance(face, ast.Constant) and isinstance(face.value, str) and face.value, (
                    f"{node.name}: payload_phase 调用缺非空 face 盐"
                )
                found.append(face.value)
    assert sorted(set(found)) == sorted(_FACE_REGISTRY[:8]), (
        f"Jinja 面 face 盐集合与登记表不符：{sorted(set(found))}"
    )


# ==================== 渲染统一波（2026-10-03）：壳层洗色按面布局门 ====================
# theme_tokens「壳层渐变·按面派生」段注释声称的机器门在本文件，此前缺位＝纯承诺，
# 本批补票落地。判据全部现算自值册（_WASH_FACE_ORDER / shell_wash_for_face），
# 不手抄任何布局表。
_WASH_GRADIENT_PREFIX = "linear-gradient(145deg, var(--wash-mist) 0%"


def test_shell_wash_layout_pairwise_distinct() -> None:
    """壳层釉瑚渐变按面派生：全部登记面两两布局互异 + 雾底 0% 打底前缀恒在。

    goal-7「背景釉瑚渐变漂移彩色中颜色的布局不得完全一样」的执法腿；同时锁
    「首色标恒 `linear-gradient(145deg, var(--wash-mist) 0%` 形态」（雾底打底锁
    test_pc_never_paints_brand_base 的按面形态，任何面不得改写）。
    """
    faces = list(_tt._WASH_FACE_ORDER)
    washes = {face: _tt.shell_wash_for_face(face) for face in faces}
    for face, value in washes.items():
        assert value.startswith(_WASH_GRADIENT_PREFIX), f"{face} 壳层洗缺雾底打底前缀"
        assert value != _tt.SHELL_WASH_GRADIENT, f"{face} 布局回落 canon＝未按面派生"
    assert len(set(washes.values())) == len(washes), (
        f"登记面壳层洗布局撞车：{washes}"
    )


def test_direct_concat_faces_registered_for_shell_wash() -> None:
    """help/debug/media/usage 四个直拼面已入壳层洗面序册与宽度册（登记门）。

    直拼卡不像 Jinja 卡走派生清单，面身份只能显式登记——四键任一脱册，
    按面布局与宽度查表对这两个面静默失效，本门即防脱册腿。
    """
    for face in ("help", "debug", "media", "usage"):
        assert face in _tt._WASH_FACE_ORDER, f"{face} 未入 _WASH_FACE_ORDER"
        assert face in _tt.CARD_SHELL_WIDTHS, f"{face} 未入 CARD_SHELL_WIDTHS"
        assert _tt.shell_wash_for_face(face).startswith(_WASH_GRADIENT_PREFIX), (
            f"{face} 壳层洗缺雾底打底前缀"
        )


def test_phase_face_salt_render_level_evidence_and_mutations() -> None:
    """两卡同 payload 实渲：--phase 互异 + 各自双渲逐字节稳定（钉帧不碎）；
    并逐门注毒自证（合成于内存/临时文件，真实文件零改动，无需 finally 还原）。"""
    decl = re.compile(r"--phase:\s*([0-9]*\.?[0-9]+)\s*;")

    def _phase_of(html: str) -> str:
        values = decl.findall(html)
        assert len(values) == 1, f"期望恰一处 --phase，实得 {values}"
        return values[0]

    same_payload: dict[str, object] = {"items": [{"name": "X", "value": "1"}], "note": "n"}
    p_err = _phase_of(bridge.render_error_card_html(dict(same_payload)))
    p_mkt = _phase_of(bridge.render_market_card_html(dict(same_payload)))
    assert p_err != p_mkt, "同 payload 下 error/market 两面相位撞车=构图雷同回潮"
    assert bridge.render_market_card_html(dict(same_payload)) == bridge.render_market_card_html(
        dict(same_payload)
    )

    # ---- 注毒自证：每枚新门必须咬得住宿违例，且不误伤合法形态 ----
    poisoned = "x { font-size: 45px; font-weight: 650; border: 3px solid #fff; }"
    assert _scan_offscale_font_sizes(poisoned) == ["45px"]
    assert _scan_unregistered_font_weights(poisoned) == ["650"]
    assert _scan_illegal_border_widths(poisoned) == ["3px"]
    assert _scan_hard_stop_wash("background: linear-gradient(145deg, #fff 50%, #000 50%);")
    clean = "x { font-size: 14px; font-weight: 600; border: 1px solid #fff; }"
    assert not _scan_offscale_font_sizes(clean)
    assert not _scan_unregistered_font_weights(clean)
    assert not _scan_illegal_border_widths(clean)
    assert not _scan_hard_stop_wash("background: linear-gradient(145deg, #fff 0%, #eee 50%, #000 100%);")
    # 同色两停（纯色填充）不得误伤；嵌套 color-mix 的两停同位异色必须咬住。
    assert not _scan_hard_stop_wash(
        "background: linear-gradient(color-mix(in srgb, #fff 14%, #000), color-mix(in srgb, #fff 14%, #000));"
    )
    assert _scan_hard_stop_wash(
        "background: linear-gradient(color-mix(in srgb, var(--a) 60%, transparent) 30%, "
        "color-mix(in srgb, var(--b) 40%, transparent) 30%, transparent 100%);"
    )
    # face 盐注毒：撤盐（face=""）即两面复同——证明该腿有牙。
    assert bridge.payload_phase(dict(same_payload), face="") == bridge.payload_phase(
        dict(same_payload), face=""
    )


def test_visual_audit_inventory_is_the_derived_source() -> None:
    """防回潮：本文件的清单必须恒等于单一取数口的现算值——谁把手抄副本塞回来
    （news 面当年就是这么漏出去的），这一腿当场点名。"""
    assert _EDITABLE_TEMPLATES == bridge.card_template_names()
    assert "news_digest_card.html" in _EDITABLE_TEMPLATES, (
        "news 面脱离派生清单（目录在盘而清单没有＝取数口被换回字面量）"
    )


def test_news_digest_face_joins_scale_gates() -> None:
    """news 面数值过尺（防御性复读）。

    历史：该面曾是「三本手抄清单都没数到」的后增面，靠本函数单独点名补票；
    2026-09-26 清单归一后它已在派生清单里、随 test_owned_faces_* 全量受管，
    本函数不再是它唯一的入场券——保留为防回潮直扫（若哪天派生腿被换掉，
    这里仍是独立第二眼）。"""
    text = _strip_comments(_tpl(_NEWS_DIGEST_TEMPLATE))
    assert not _scan_offscale_font_sizes(text)
    assert not _scan_unregistered_font_weights(text)
    assert not _scan_illegal_border_widths(text)
    assert not _scan_hard_stop_wash(text)


def test_type_scale_registry_covers_every_face_value_in_use() -> None:
    """值册自证：门扫出的合法集恰等于实渲面用值集（新增档必写理由入册，
    删档必使对应面改值——棘轮只降不升的字面量侧记账）。"""
    used: set[float] = set()
    for _name, text in _owned_face_sources():
        for v in re.findall(r"font-size\s*:\s*([\d.]+)px", text):
            used.add(float(v))
    assert used <= _SCALE_VALUES, f"表外用值：{sorted(used - _SCALE_VALUES)}"


def test_error_card_compact_two_column_path_is_live() -> None:
    """命题④：信息密集面（诊断卡）的两栏键值机制在册且在用——
    宏（kv_section compact 分支）、.section.compact .grid 双列 CSS、
    .row.wide 长值整行、单条 176px 左轨（名/值各自成轴）四件缺一不可；
    compact=true 调用点少于 4 = 机制被架空同样判红。"""
    text = _tpl("error_card.html")
    assert "{% macro kv_section(title, pairs, compact=false)" in text, "kv_section 宏缺 compact 形参"
    assert ".section.compact .grid { grid-template-columns: 1fr 1fr; }" in text, "双列 CSS 缺失"
    assert ".row.wide { grid-column: 1 / -1; }" in text, "长值整行规则缺失"
    assert text.count("flex: 0 0 176px") == 1, "属性名左轨必须恰一条（多轨=值不成轴）"
    assert text.count("kv_section(") - 1 >= 4, "compact 键值节调用点不足（宏定义外 <4 处）"

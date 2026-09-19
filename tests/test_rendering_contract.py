"""统一 UI 主题与卡片契约测试（Task 3 / 2026-09-12）。

全部离线：字符串 / Jinja2 渲染 / 纯函数断言，不依赖 playwright、不联网。
契约来源：AGENTS.md UI 铁律 + 计划 Global Constraints +
docs/rendering-contract.md（本测试的软文档镜像）。

铁律：模板无 <meta viewport>；body 透明；字重 ≤700；动画必须在 .card 内；
光晕 alpha ≥ 0.05；阴影只准用 theme_tokens.SHADOW_CSS_VARS 登记族
（shell/panel/tile 分级，动态白名单）；渲染失败→纯文本兜底契约零破坏；
守岸人本命色为唯一基底，平台色只做受控 accent。

注意：显式枚举全部既有模板（universal/market/affinity/mermaid/song/finance），
禁止 glob templates 目录——新增模板入列时逐个登记。
"""

from __future__ import annotations

import functools
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.render.card_render import bridge
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    BLOB_COUNT,
    BLOB_DURATIONS,
    CARD_SHELL_WIDTHS,
    DEFAULT_THEME,
    DEFAULT_WASH_TOKENS,
    FONT_WEIGHT_MAX,
    GAP_SCALE_PX,
    GLASS_EDGE,
    GLASS_FOOT,
    GLASS_MAIN,
    META_VIEWPORT_POLICY,
    MONO_FONT_STACK,
    OVERLAY_SCRIMS,
    PLATFORM_FOOTER_LABELS,
    PLATFORM_THEMES,
    RADIUS_CIRCLE,
    RADIUS_INNER_CSS_VARS,
    RADIUS_INNER_PX,
    RADIUS_PILL,
    SCORE_COLD,
    SCORE_HOT,
    SEMANTIC_COLORS,
    SEMANTIC_DANGER,
    SEMANTIC_SUCCESS,
    SEMANTIC_WARNING,
    SHADOW_CSS_VARS,
    SHADOW_PRIMARY,
    SHADOW_SECONDARY,
    THEME_ALIASES,
    UNKNOWN_PLATFORM_COLOR,
    derive_wash_tokens,
    get_platform_theme,
)
from plugins.bot_unified_runtime.output.render_backends import (
    NullRenderBackend,
    PlaywrightRenderBackend,
)

# 显式枚举全部既有模板（禁止 glob：新增模板入列时逐个登记）。
CARD_TEMPLATES: tuple[str, ...] = (
    "universal_card.html",
    "market_card.html",
    "affinity_card.html",
    "mermaid_card.html",
    "song_candidates.html",
    "finance_card.html",
    "error_card.html",
)

# 模板名 → CARD_SHELL_WIDTHS 登记键（宽度按内容族分化，但必须登记）。
_SHELL_WIDTH_KEYS: dict[str, str] = {
    "universal_card.html": "universal",
    "market_card.html": "market",
    "affinity_card.html": "affinity",
    "mermaid_card.html": "mermaid_max",
    "song_candidates.html": "song_panel",
    "finance_card.html": "finance",
    "error_card.html": "error",
}


_TEMPLATES_DIR = Path(bridge.__file__).resolve().parent / "templates"


def _tpl(name: str) -> str:
    return (_TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """去掉 Jinja 注释与 HTML 注释——注释里允许出现禁令字样。"""
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return text


# 模板名 → 渲染入口（默认空载荷）。步 5 后 :root 的公共段由
# mica_shell.render_root_tokens 单一产出、不再写在模板里，故契约测试必须把
# **渲染产物**一并纳入取材，否则会误报「模板缺 --mica-shadow / --r-shell / --wash-*」。
_RENDER_ENTRIES: dict[str, Any] = {
    "universal_card.html": lambda: bridge.render_universal_card_html({}),
    "market_card.html": lambda: bridge.render_market_card_html({}),
    "affinity_card.html": lambda: bridge.render_affinity_card_html({}),
    "mermaid_card.html": lambda: bridge.render_mermaid_html("graph TD;A-->B;"),
    "song_candidates.html": lambda: bridge.render_song_candidates_html({}),
    "finance_card.html": lambda: bridge.render_finance_card_html({}),
    "error_card.html": lambda: bridge.render_error_card_html({}),
}


@functools.cache
def _root_blocks_of(name: str) -> str:
    """该模板渲染产物里全部 ``:root`` 块的拼接（公共段来源，步 5 起）。

    默认空载荷 → 平台色回落到 ``UNKNOWN_PLATFORM_COLOR``（``error_card`` 例外，
    它固定用 ``ERROR_THEME.accent``）。
    """
    html = _RENDER_ENTRIES[name]()
    return "\n".join(re.findall(r":root\s*\{([^}]*)\}", html))


def _card_accent(name: str) -> str:
    """该卡渲染产物里实际生效的主色（从 ``--accent`` 反读，避免测试硬编码各卡主色）。"""
    match = re.search(r"--accent:([^;]+);", _root_blocks_of(name))
    assert match, f"{name} 渲染产物缺 --accent"
    return match.group(1)


def _css_of(name: str) -> str:
    match = re.search(r"<style>(.*?)</style>", _strip_comments(_tpl(name)), re.DOTALL)
    assert match, f"{name} 缺少 <style> 块"
    source = match.group(1)
    # 模板源码里的 :root 块整体剔除——渲染产物版本已含其全部内容（且变量已求值），
    # 两者并存会让「同一 token 至多定义一次」的断言误报。
    # 注意必须先把 Jinja 表达式换成占位符：块内的 `{{ ... }}` 自带 `}`，
    # 会让 `[^}]*` 提前收尾、只删掉半个块（实测残留 --mica-shadow-panel）。
    masked = re.sub(r"\{\{.*?\}\}", "JINJA", source, flags=re.DOTALL)
    spans = [m.span() for m in re.finditer(r":root\s*\{[^}]*\}", masked)]
    for start, end in reversed(spans):
        source = source[:start] + source[end:]
    return source + "\n" + _root_blocks_of(name)


def _css_rules(css: str) -> list[tuple[str, str]]:
    """粗粒度 CSS 规则切分（keyframes 内层块按普通块处理即可满足断言）。"""
    return [
        (selector.strip(), body)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    ]


def _norm_css(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


# ==================== 1. viewport 禁令 ====================
def test_viewport_policy_is_forbidden() -> None:
    assert META_VIEWPORT_POLICY == "forbidden"


@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_no_meta_viewport(name: str) -> None:
    assert not re.search(r"<meta[^>]*viewport", _strip_comments(_tpl(name))), (
        f"{name} 违反无 <meta viewport> 铁律"
    )


# ==================== 2. body 透明（omit_background 依赖） ====================
@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_body_transparent(name: str) -> None:
    for selector, body in _css_rules(_css_of(name)):
        if re.fullmatch(r"(html\s+)?body", selector):
            assert "background: transparent" in body, f"{name} body 必须透明"
            return
    pytest.fail(f"{name} 未找到 body 规则")


# ==================== 3. 字重 ≤ 700 ====================
def test_font_weight_cap_constant() -> None:
    assert FONT_WEIGHT_MAX == 700
    assert DEFAULT_THEME.font_weight_max == FONT_WEIGHT_MAX


@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_font_weight_at_most_700(name: str) -> None:
    weights = [int(v) for v in re.findall(r"font-weight\s*:\s*(\d+)", _tpl(name))]
    assert weights, f"{name} 无 font-weight 声明？"
    assert max(weights) <= FONT_WEIGHT_MAX


# ==================== 4. 阴影 token 族（vis4 层次化升级） ====================
# 2026-09-13 用户裁定：层次阴影区分——阴影 token 从 2 枚扩为分级族
# （shell/panel/tile 三级），仍全局唯一来源 theme_tokens，禁止自造一次性阴影。
# 白名单从 theme_tokens.SHADOW_CSS_VARS 动态派生：新增档位在登记表入册后
# 自动合法，登记表之外的一票否决——只开正门，不留后门。
_SHADOW_TOKEN_NAMES = set(SHADOW_CSS_VARS)
_BOX_SHADOW_ALLOWED = {"none"} | {f"var({name})" for name in SHADOW_CSS_VARS}


@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_shadow_tokens_within_family(name: str) -> None:
    css = _css_of(name)
    defined = re.findall(r"(--[a-z-]*shadow[a-z-]*)\s*:", css)
    unknown = set(defined) - _SHADOW_TOKEN_NAMES
    assert not unknown, f"{name} 出现族外阴影 token: {sorted(unknown)}"
    # 族内每枚至多定义一次；核心两枚（shell/soft）必须 always 在册。
    assert len(defined) == len(set(defined)), f"{name} 阴影 token 重复定义"
    assert {"--mica-shadow", "--mica-shadow-soft"} <= set(defined)

    for _selector, body in _css_rules(css):
        for value in re.findall(r"box-shadow\s*:\s*([^;]+)(?:;|$)", body):
            normalized = _norm_css(value)
            assert (
                normalized in _BOX_SHADOW_ALLOWED
            ), f"{name} 出现非 token 阴影: {normalized!r}"


@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_shadow_token_values_single_source(name: str) -> None:
    css = _css_of(name)
    mica = re.search(r"--mica-shadow:\s*([^;]+)(?:;|$)", css)
    soft = re.search(r"--mica-shadow-soft:\s*([^;]+)(?:;|$)", css)
    assert mica and soft, f"{name} 缺阴影 token 定义"
    assert _norm_css(mica.group(1)) == _norm_css(SHADOW_PRIMARY), (
        f"{name} --mica-shadow 与 theme_tokens.SHADOW_PRIMARY 不一致"
    )
    assert _norm_css(soft.group(1)) == _norm_css(SHADOW_SECONDARY), (
        f"{name} --mica-shadow-soft 与 theme_tokens.SHADOW_SECONDARY 不一致"
    )
    # 登记表内其余档位：字面量须与登记值一致，或引用 bridge 注入的同名上下文
    # 键（值同源，见 bridge._vis4_context）。档位→ctx 键映射从 SHADOW_CSS_VARS
    # 登记表反查派生（P3-12：手工拷贝清单换真值源，新增档位自动入检，禁止
    # 手抄遗漏）；派生出的 ctx 键必须已在 bridge._VIS4_KEYS 注入登记，否则先红。
    context_keys = {
        var: "shadow_elev_" + var.removeprefix("--mica-shadow-")
        for var in SHADOW_CSS_VARS
        if var not in ("--mica-shadow", "--mica-shadow-soft")
    }
    unregistered = sorted(set(context_keys.values()) - set(bridge._VIS4_KEYS))
    assert not unregistered, f"bridge._VIS4_KEYS 未注入阴影档位 ctx 键: {unregistered}"
    for var, ctx_key in context_keys.items():
        m = re.search(re.escape(var) + r":\s*([^;]+)(?:;|$)", css)
        if not m:
            continue
        raw = _norm_css(m.group(1))
        expected = _norm_css(SHADOW_CSS_VARS[var])
        assert raw == expected or raw == f"{{{{ {ctx_key} }}}}", (
            f"{name} {var} 与 theme_tokens 登记值不一致: {raw!r}"
        )


# ==================== 5. shell 半径/宽度/间距统一 ====================
@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_shell_radius_tokens(name: str) -> None:
    css = _css_of(name)
    expected = {"--r-shell": "30px", "--r-panel": "18px", "--r-tile": "14px"}
    found = False
    for token, value in expected.items():
        match = re.search(re.escape(token) + r":\s*([^;]+)(?:;|$)", css)
        if match:
            found = True
            assert _norm_css(match.group(1)) == value, f"{name} {token} 违规"
    assert found, f"{name} 未声明任何 shell 半径 token"


@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_shell_width_is_audited(name: str) -> None:
    key = _SHELL_WIDTH_KEYS[name]
    assert key in CARD_SHELL_WIDTHS, f"{name} 宽度未登记进 CARD_SHELL_WIDTHS"
    text = _strip_comments(_tpl(name))
    audited = CARD_SHELL_WIDTHS[key]
    if name == "universal_card.html":
        # 通用解析卡宽度由 payload card_width 驱动（默认 1440px 与登记一致）。
        assert "width: {{ card_width }}" in text
        assert audited == 1440
        return
    if name == "mermaid_card.html":
        # mermaid 卡 fit-content，登记值是 max-width 上限。
        card_block = re.search(r"\.card\s*\{[^}]*\}", text)
        assert card_block, "mermaid 找不到 .card 规则"
        assert "width: fit-content" in card_block.group(0)
        assert f"max-width: {audited}px" in card_block.group(0)
        return
    shell_block = re.search(r"\.(?:shell|panel)\s*\{[^}]*\}", text)
    assert shell_block, f"{name} 找不到外壳规则块"
    assert f"width: {audited}px" in shell_block.group(0), (
        f"{name} 外壳宽度与 CARD_SHELL_WIDTHS[{key}]={audited} 不符"
    )


def test_gap_scale_constant() -> None:
    assert GAP_SCALE_PX == frozenset({3, 4, 6, 7, 8, 10, 12, 14, 16})


@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_gaps_use_audited_scale(name: str) -> None:
    text = _strip_comments(_tpl(name))
    gaps = [int(v) for v in re.findall(r"gap:\s*(\d+)px", text)]
    assert gaps, f"{name} 无 gap 声明"
    bad = sorted({g for g in gaps if g not in GAP_SCALE_PX})
    assert not bad, f"{name} 间距 {bad}px 不在审计过的 gap 刻度内"


# ==================== 6. 守岸人本命 wash token ====================
def test_default_wash_tokens_shape() -> None:
    assert set(DEFAULT_WASH_TOKENS) == {"wash_1", "wash_2", "wash_3", "wash_mist"}
    for value in DEFAULT_WASH_TOKENS.values():
        assert re.fullmatch(r"#[0-9a-f]{6}", value)
    assert DEFAULT_WASH_TOKENS == derive_wash_tokens(UNKNOWN_PLATFORM_COLOR)


@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_brand_wash_tokens_injected(name: str) -> None:
    css = _css_of(name)
    # 档位清单从 DEFAULT_WASH_TOKENS 登记表反查（P3-12）：新增本命 wash 档位
    # 自动逐模板校验注入点与兜底字面量，不依赖手工拷贝的元组。
    #
    # 步 5 起取值有两种合法形态：①模板内联 default('...') 兜底（历史形态，
    # 现仅剩模板自有 token）；②bridge 派生直出（公共段由 render_root_tokens
    # 产出，默认载荷下正是本命档位）。两者都必须与本命值一致。
    for token in DEFAULT_WASH_TOKENS:
        css_token = "--wash-" + token.split("_")[1]
        match = re.search(re.escape(css_token) + r":\s*([^;]+)(?:;|$)", css)
        assert match, f"{name} 缺 {css_token} 注入点"
        value = _norm_css(match.group(1))
        declared = re.search(r"default\('([^']*)'\)", value)
        if declared:
            assert declared.group(1) == DEFAULT_WASH_TOKENS[token], (
                f"{name} {css_token} 兜底值与本命 token 不一致"
            )
        else:
            # 步 5 形态：值由 bridge 按该卡主色派生（一定有值，缺 payload 不会崩）。
            # 期望值现算——各卡主色不同（error 卡固定 ERROR_THEME.accent），
            # 从渲染产物的 --accent 反读，避免在测试里硬编码第二份主色表。
            expected = derive_wash_tokens(_card_accent(name))
            assert value == expected[token], (
                f"{name} {css_token} 与按主色派生的本命档位不一致: "
                f"{value!r} != {expected[token]!r}"
            )


def test_pc_never_paints_brand_base() -> None:
    """本命底色只来自 wash 渐变；--accent 只允许进 accent/色斑混色。"""
    for name in CARD_TEMPLATES:
        css = _css_of(name)
        assert re.search(r"linear-gradient\(145deg,\s*var\(--wash-mist\)", css), (
            f"{name} 外壳渐变底未以 --wash-mist 打底"
        )
        blob = re.search(r"--wash-blob-1:\s*color-mix\(in srgb, var\(--accent\) (\d+)%", css)
        assert blob, f"{name} 缺 --wash-blob-1 定义"
        assert int(blob.group(1)) <= 35, f"{name} 平台色斑混入超过 35% 上限"


# ==================== 7. 动画必须在 .card 内 ====================
class _CardScopeParser(HTMLParser):
    """校验根元素带 card 类，且所有 drift-blob 都在根 card 子树内。"""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.root_classes: set[str] | None = None
        self.card_depth: int | None = None
        self.violations: list[str] = []
        self.blob_count = 0

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        for key, value in attrs:
            if key == "class" and value:
                return set(value.split())
        return set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = self._classes(attrs)
        if tag == "div" and self.root_classes is None:
            self.root_classes = classes
            self.card_depth = self.depth
        if "drift-blob" in classes:
            self.blob_count += 1
            if self.card_depth is None or self.depth <= self.card_depth:
                self.violations.append(f"drift-blob 在 card 外（depth={self.depth}）")
        if tag not in ("img", "br", "meta", "link", "input", "hr"):
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag not in ("img", "br", "meta", "link", "input", "hr") and self.depth > 0:
            self.depth -= 1


@pytest.mark.parametrize(
    "renderer_name, payload, expect_dom_blobs",
    [
        ("render_universal_card_html", {}, False),  # 色斑走 .card::before/::after 伪元素
        (
            "render_universal_card_html",
            {"page_type": "video", "name": "UP", "title": "标题"},
            True,
        ),
        (
            "render_market_card_html",
            {
                "groups": [
                    {"name": "g", "rows": [{"name": "n", "price": "1", "pct": "0%"}]}
                ]
            },
            True,
        ),
        ("render_affinity_card_html", {}, True),
        ("render_song_candidates_html", {"candidates": [{"name": "歌"}]}, True),
        ("render_finance_card_html", {}, True),  # 漂移色斑为静态 DOM，空 payload 也在
        ("render_error_card_html", {}, True),  # 运行异常诊断卡（2026-09-13）
        ("render_mermaid_html", None, False),  # 色斑走 .card::before/::after 伪元素
    ],
)
def test_animations_render_inside_card(
    renderer_name: str, payload: dict[str, Any] | None, expect_dom_blobs: bool
) -> None:
    if renderer_name == "render_mermaid_html":
        html_text = getattr(bridge, renderer_name)("graph TD;A-->B;")
    else:
        html_text = getattr(bridge, renderer_name)(payload)
    parser = _CardScopeParser()
    parser.feed(html_text)
    assert parser.root_classes is not None and "card" in parser.root_classes, (
        f"{renderer_name} 根元素必须带 card 类（截图目标 .card 契约）"
    )
    if expect_dom_blobs:
        assert parser.blob_count >= 1, f"{renderer_name} 缺漂移色斑元素"
    assert not parser.violations, (
        f"{renderer_name} 动画元素越出 .card: {parser.violations}"
    )


@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_animation_selectors_are_card_scoped(name: str) -> None:
    for selector, body in _css_rules(_css_of(name)):
        if re.search(r"@keyframes", selector):
            assert re.search(r"mica-drift-[abc]$", selector.strip()), (
                f"{name} 出现未登记 keyframes: {selector!r}"
            )
            continue
        if re.search(r"\banimation\s*:", body):
            assert re.search(r"\.(card|shell|panel|drift-blob)", selector), (
                f"{name} 有 .card 作用域之外的 animation: {selector!r}"
            )


# ==================== 8. 光晕 alpha ≥ 0.05 ====================
@pytest.mark.parametrize("name", CARD_TEMPLATES)
def test_glow_alpha_floor(name: str) -> None:
    css = _css_of(name)
    for value in re.findall(
        r"rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*(0?\.\d+|\d+)\s*\)", css
    ):
        assert float(value) >= 0.05, f"{name} rgba 光晕 alpha {value} < 0.05"
    for value in re.findall(
        r"color-mix\([^)]*?(\d+(?:\.\d+)?)%\s*,\s*transparent", css
    ):
        assert float(value) >= 5.0, f"{name} color-mix 光晕 {value}% < 5%"


# ==================== 9. PLATFORM_THEMES 显式注册表 ====================
def test_platform_themes_registry_covers_social_and_music() -> None:
    social = {
        "bilibili", "xiaohongshu", "douyin", "weibo", "youtube", "twitter",
        "pixiv", "lofter", "allcpp", "facebook", "instagram",
    }
    music = {
        "netease", "qqmusic", "kugou", "kuwo", "apple_music", "spotify",
    }
    assert social <= set(PLATFORM_THEMES), "社交媒体主题缺失"
    assert music <= set(PLATFORM_THEMES), "音乐平台主题缺失"
    # 别名键必须可解析回同一主题（xhs→xiaohongshu / x→twitter / cpp→allcpp /
    # ncm→netease）。
    for alias in ("xhs", "x", "cpp", "ncm"):
        assert alias in THEME_ALIASES, f"别名 {alias} 未登记"
    for key, theme in PLATFORM_THEMES.items():
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", theme.accent), f"{key} accent 非法"
        assert theme.display_name, f"{key} 缺展示名"
        assert theme.font_weight_max == FONT_WEIGHT_MAX
        assert theme.shell_radius == 30 and theme.panel_radius == 18
        assert theme.tile_radius == 14


def test_platform_themes_accents_distinct_per_canonical_platform() -> None:
    by_name: dict[str, str] = {}
    for key, theme in PLATFORM_THEMES.items():
        previous = by_name.setdefault(theme.display_name, theme.accent)
        assert previous == theme.accent, f"{theme.display_name} 别名色不一致（{key}）"
    canonical = {
        theme.display_name: theme.accent for theme in PLATFORM_THEMES.values()
    }
    assert len(set(canonical.values())) == len(canonical), "不同平台 accent 必须可辨认"


def test_resolve_platform_theme_unknown_falls_back_safe() -> None:
    theme = get_platform_theme("totally_unknown")
    assert theme is DEFAULT_THEME
    assert theme.accent == UNKNOWN_PLATFORM_COLOR == "#607080"
    alias = get_platform_theme("xhs")
    assert alias.accent == get_platform_theme("xiaohongshu").accent
    # 非法色值不抛异常：derive 走灰阶零推力路径。
    assert set(derive_wash_tokens("not-a-color")) == {
        "wash_1", "wash_2", "wash_3", "wash_mist",
    }


def test_bridge_consumes_theme_registry() -> None:
    assert bridge.UNKNOWN_PLATFORM_COLOR == UNKNOWN_PLATFORM_COLOR
    for key, theme in PLATFORM_THEMES.items():
        assert bridge.PLATFORM_COLORS[key] == theme.accent
        assert bridge.PLATFORM_OFFICIAL_NAMES[key] == theme.display_name
    for alias, target in THEME_ALIASES.items():
        assert bridge.PLATFORM_COLORS[alias] == PLATFORM_THEMES[target].accent
    assert bridge.PLATFORM_OFFICIAL_NAMES["generic"] == "Web"
    assert bridge._PLATFORM_FOOTER_LABELS is PLATFORM_FOOTER_LABELS
    assert bridge._derive_wash_tokens is derive_wash_tokens


def test_wash_derivation_brand_base_is_stable() -> None:
    # 平台色只允许把 wash-1 往平台相轻推；wash_2/3/mist 是本命定值。
    a = derive_wash_tokens("#fb7299")  # bilibili 粉
    b = derive_wash_tokens("#1d9bf0")  # twitter 蓝
    assert a["wash_2"] == b["wash_2"]
    assert a["wash_3"] == b["wash_3"]
    assert a["wash_mist"] == b["wash_mist"]
    gray = derive_wash_tokens(UNKNOWN_PLATFORM_COLOR)
    neutral = derive_wash_tokens("#607081")
    assert gray == neutral, "灰阶/未知平台推力应为零（纯本命洗）"


# ==================== 10. 失败→纯文本兜底契约 ====================
@pytest.mark.parametrize(
    "renderer_name",
    [
        "render_universal_card_html",
        "render_market_card_html",
        "render_affinity_card_html",
        "render_song_candidates_html",
        "render_finance_card_html",
        "render_error_card_html",
    ],
)
@pytest.mark.parametrize("payload", [None, {}])
def test_renderers_never_raise_on_empty_payload(
    renderer_name: str, payload: dict[str, Any] | None
) -> None:
    html_text = getattr(bridge, renderer_name)(payload)
    assert isinstance(html_text, str) and html_text.strip()
    assert "守岸人" in html_text


# ==================== 10a. 品牌中文名单一来源（CAPFIX-B 修 I-3，2026-09-21） ====================
# 评审实锤（review-CAP1-report I-3）：models.RenderPayload.bot_name 默认值曾
# 硬编码「守岸人」，经 bridge._DEFAULT_CONTEXT 喂 universal 卡 → 胶囊回落分支
# 恒不生效，中文名出现**第二处真相**（改 BRAND_THEME 后 universal 不跟随、
# market/error 跟随）。修复=默认值置空，渲染期由 BRAND_THEME.display_name
# 单点回落。反向锁：任何人把字面量写回默认值/新增第二处缺省，本测试必红。

def test_brand_display_name_single_source_across_faces() -> None:
    """空 payload 下全数卡面品牌中文名恒跟随 BRAND_THEME.display_name（渲染期）。"""
    theme = bridge.BRAND_THEME
    original = theme.display_name
    object.__setattr__(theme, "display_name", "ZZTEST-CAPSULE")
    try:
        # dataclass 默认值本体不得再写第二处字面量。
        assert bridge.RenderPayload().bot_name == "", (
            "RenderPayload.bot_name 默认值携带品牌名第二处字面量（回归 I-3）"
        )
        outputs = {
            "universal": bridge.render_universal_card_html({}),
            "market": bridge.render_market_card_html({}),
            "error": bridge.render_error_card_html({}),
            "mermaid": bridge.render_mermaid_html("graph TD;A-->B;"),
        }
        for face, html_text in outputs.items():
            assert '<span class="mc-name">ZZTEST-CAPSULE</span>' in html_text, (
                f"{face} 卡胶囊中文名未跟随单一来源（回归 I-3）"
            )
            assert '<span class="mc-name">守岸人</span>' not in html_text, (
                f"{face} 卡胶囊中文名仍出硬编码缺省（回归 I-3）"
            )
    finally:
        object.__setattr__(theme, "display_name", original)
    # 恢复默认后回落值即品牌登记值（default-path 契约不破）。
    assert '<span class="mc-name">守岸人</span>' in bridge.render_universal_card_html({})


# ==================== 10c. 功能名单一来源（CAPFIX-B 修 I-4，2026-09-21） ====================
# 评审实锤（review-CAP1-report I-4）：bridge 六处把功能名硬编码成缺省回落
# （「全球股指/金融/点歌/好感度/诊断/流程图」），其中「诊断」是 CAP1 新增、
# 调用方（runtime.error_report 载荷只有 card_title）零出处的卡面文案。
# 契约=功能名只认调用方传入，缺省整段省略（mc-feature 不产）。
# 反向锁：任一回落字面量回潮 → 本节必红；传入即显通道被写死成省略 → 亦红。

def test_feature_label_omitted_without_caller_source() -> None:
    """空 payload 全数卡面功能名段整体省略，桥内不再存第二处字面量。"""
    outputs = {
        "universal": bridge.render_universal_card_html({}),
        "market": bridge.render_market_card_html({}),
        "finance": bridge.render_finance_card_html({}),
        "song": bridge.render_song_candidates_html({}),
        "affinity": bridge.render_affinity_card_html({}),
        "error": bridge.render_error_card_html({}),
        "mermaid": bridge.render_mermaid_html("graph TD;A-->B;"),
    }
    for face, html_text in outputs.items():
        assert 'class="mc-feature"' not in html_text, (
            f"{face} 卡功能名段未随缺省省略（桥内回落字面量回潮，回归 I-4）"
        )


def test_feature_label_rendered_when_supplied_by_caller() -> None:
    """调用方传入即显（单一来源通道活体，非死代码）。"""
    assert (
        "<span class=\"mc-feature\">· 测试功能</span>"
        in bridge.render_market_card_html({"feature_label": "测试功能"})
    )
    assert (
        "<span class=\"mc-feature\">· 流程图</span>"
        in bridge.render_mermaid_html(
            "graph TD;A-->B;", feature_label="流程图"
        )
    )


# ==================== 10d. mermaid 头像优先级链（CAPFIX-B 修 I-7，2026-09-21） ====================
# 评审实锤（review-CAP1-report I-7）：render_mermaid_html 曾裸调
# bot_avatar_uri()，把优先级链最高级「显式配置 bot_persona_avatar_url」丢掉
# （_discover_local_uri(None) 亦恒空）。修复=带 config 走同一入口
# （usage_cards/能力侧共五处的同口径直调），renderer 侧接线待合流波。

class _AvatarStubConfig:
    bot_persona_avatar_url = "https://explicit.invalid/avatar.png"
    bot_runtime_data_dir = ""


def test_mermaid_html_forwards_config_to_avatar_entry() -> None:
    """显式配置级可达：传 config 后 mermaid 卡胶囊用 bot_persona_avatar_url。"""
    html_text = bridge.render_mermaid_html(
        "graph TD;A-->B;", config=_AvatarStubConfig()
    )
    assert 'src="https://explicit.invalid/avatar.png"' in html_text


def test_mermaid_png_forwards_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """render_mermaid_png 把 config/feature_label 原样透传给 html 装配。"""
    captured: dict[str, str] = {}

    class _StubBackend:
        def render_card(self, payload: dict[str, Any]) -> bytes:
            captured["html"] = str(payload["html"])
            return b"PNG"

    monkeypatch.setattr(bridge, "_get_mermaid_backend", lambda: _StubBackend())
    assert (
        bridge.render_mermaid_png(
            "graph TD;A-->B;",
            config=_AvatarStubConfig(),
            feature_label="流程图",
        )
        == b"PNG"
    )
    assert 'src="https://explicit.invalid/avatar.png"' in captured["html"]
    assert "<span class=\"mc-feature\">· 流程图</span>" in captured["html"]


# ==================== 10b. vis5 边界加固：好感度卡脏数据不抛异常 ====================
# 审计实锤（vis5 前）：rows.score=None/"80"/缺键 → 模板 `%.1f` 格式化抛
# TypeError/UndefinedError；bar 越界直出 250%。桥层归一是契约铁律 7 的前置。
_AFFINITY_DIRTY_PAYLOADS: tuple[dict[str, Any], ...] = (
    {"mode": "group", "rows": [{"sender_id": "1", "display_name": "甲", "score": None}]},
    {"mode": "group", "rows": [{"sender_id": "1", "display_name": "甲", "score": "80"}]},
    {"mode": "group", "rows": [{"sender_id": "1"}]},
    {"mode": "group", "rows": ["not-a-dict", None]},
    {"mode": "private", "bot_to_user": {"score": None, "tier": "友善", "bar": None}},
    {"mode": "private", "bot_to_user": {"score": 80.0, "tier": "友善", "bar": 250}},
    {"mode": "private", "bot_to_user": {"score": 10.0, "bar": -5}},
    {"mode": "algorithm", "steps": [{"label": "基准", "value": None, "cls": "flat"}]},
    {"mode": "algorithm", "steps": [{"label": "x", "value": "ok", "cls": "爆"}]},
    {"mode": "algorithm", "tiers": [{"label": None, "range": None, "attitude": None}]},
)


@pytest.mark.parametrize("payload", _AFFINITY_DIRTY_PAYLOADS)
def test_affinity_card_never_raises_on_dirty_payload(payload: dict[str, Any]) -> None:
    html_text = bridge.render_affinity_card_html(payload)
    assert isinstance(html_text, str) and html_text.strip()
    assert "守岸人" in html_text
    # 缺省分数按 0.0 渲染，不出现 None/undefined 字样。
    assert "None" not in html_text.split("<body>", 1)[-1]


def test_affinity_bar_clamped_into_track() -> None:
    html_text = bridge.render_affinity_card_html(
        {"mode": "private", "bot_to_user": {"score": 80.0, "tier": "友善", "bar": 250}}
    )
    assert "width: 100.0%" in html_text
    html_text = bridge.render_affinity_card_html(
        {"mode": "private", "user_to_bot": {"score": 10.0, "bar": -5}}
    )
    assert "width: 0.0%" in html_text


def test_mermaid_png_falls_back_to_none_without_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge, "_get_mermaid_backend", lambda: None)
    assert bridge.render_mermaid_png("graph TD;A-->B;") is None
    assert bridge.render_mermaid_png("") is None


def test_null_backend_keeps_text_fallback_contract() -> None:
    assert NullRenderBackend().render_card({"html": "<div class='card'>x</div>"}) is None


# ==================== 11. 平台色行为与既有回归一致 ====================
def test_song_card_platform_color_behavior_unchanged() -> None:
    known = bridge.render_song_candidates_html(
        {"platform": "netease", "candidates": [{"name": "晴天"}]}
    )
    assert "#c20c0c" in known
    unknown = bridge.render_song_candidates_html(
        {"platform": "no_such_platform", "candidates": [{"name": "晴天"}]}
    )
    assert "#607080" in unknown


def test_rendered_cards_inject_shell_tokens() -> None:
    html_text = bridge.render_market_card_html({})
    # v21r3 步 5：7 张模板的 :root 公共段改由 mica_shell.render_root_tokens 单一产出，
    # 书写风格统一为「冒号后无空格」（此前模板侧是带空格）。
    assert "--r-shell:30px" in html_text
    assert "--mica-shadow:" in html_text
    universal = bridge.render_universal_card_html({})
    for value in derive_wash_tokens(bridge.UNKNOWN_PLATFORM_COLOR).values():
        assert value in universal, f"universal 卡缺本命洗 {value}"


# ==================== 12. 契约文档存在且覆盖要点 ====================
def test_rendering_contract_doc_exists() -> None:
    doc = Path("docs/rendering-contract.md")
    assert doc.is_file(), "docs/rendering-contract.md 不存在"
    text = doc.read_text(encoding="utf-8")
    for keyword in ("PLATFORM_THEMES", "viewport", "兜底", "wash", "阴影", "新增模板"):
        assert keyword in text, f"渲染契约文档缺关键词: {keyword}"


# ==================== 13. CORE 值册（2026-09-18 统一收尾波 C1-C13） ====================
# 裁决基线登记值逐字符锁（值册真身 theme_tokens.py）+ 桥接注入面 + 截图兜底口径。


def test_core_registry_semantic_colors_exact() -> None:
    """C4 语义色五枚：值照裁决基线逐字符锁。"""
    assert SEMANTIC_DANGER == "#d54941"
    assert SEMANTIC_SUCCESS == "#2e9e6b"
    assert SEMANTIC_WARNING == "#b07d1a"
    assert SCORE_HOT == "#157347"
    assert SCORE_COLD == "#b42334"
    assert SEMANTIC_COLORS == {
        "danger": SEMANTIC_DANGER,
        "success": SEMANTIC_SUCCESS,
        "warning": SEMANTIC_WARNING,
        "score_hot": SCORE_HOT,
        "score_cold": SCORE_COLD,
    }


def test_core_registry_glass_tiers_exact() -> None:
    """C3 玻璃两档 + 描边三 alpha：padding-box/border-box 形态逐字符锁。"""
    assert GLASS_MAIN == (
        "linear-gradient(150deg, rgba(255, 255, 255, 0.66) 0%, "
        "rgba(255, 255, 255, 0.44) 100%) padding-box"
    )
    assert GLASS_FOOT == (
        "linear-gradient(150deg, rgba(255, 255, 255, 0.66) 0%, "
        "rgba(255, 255, 255, 0.46) 100%) padding-box"
    )
    assert GLASS_EDGE == (
        "linear-gradient(150deg, rgba(255, 255, 255, 0.95) 0%, "
        "rgba(255, 255, 255, 0.35) 55%, rgba(255, 255, 255, 0.72) 100%) border-box"
    )


def test_core_registry_overlay_scrims_exact() -> None:
    """C5 深色遮罩四员：语义分键、值逐字符锁。"""
    assert OVERLAY_SCRIMS == {
        "scrim_badge": "rgba(10, 12, 16, 0.72)",
        "scrim_banner": "rgba(15, 18, 24, 0.10)",
        "scrim_code": "rgba(28, 30, 38, 0.94)",
        "scrim_media": "rgba(38, 46, 56, 0.75)",
    }


def test_core_registry_mono_font_and_radii_exact() -> None:
    """C9 等宽字体栈 + C1 内径合法表/pill/圆特例逐字符锁。"""
    assert MONO_FONT_STACK == (
        '"Cascadia Mono",Consolas,"JetBrains Mono","Courier New",monospace'
    )
    assert RADIUS_INNER_PX == frozenset({4, 6, 8, 12, 16})
    assert RADIUS_PILL == "999px"
    assert RADIUS_CIRCLE == "50%"
    assert RADIUS_INNER_CSS_VARS == {
        "--r-inner-xs": "4px",
        "--r-inner-sm": "6px",
        "--r-inner-md": "8px",
        "--r-inner-lg": "12px",
        "--r-inner-xl": "16px",
        "--r-pill": RADIUS_PILL,
        "--r-circle": RADIUS_CIRCLE,
    }


def test_core_registry_blob_constants_exact() -> None:
    """C2 色斑常量：数量 3 + 升序时长 (46, 52, 58)。"""
    assert BLOB_COUNT == 3
    assert BLOB_DURATIONS == (46, 52, 58)


def test_core_registry_shell_widths_direct_cards() -> None:
    """C10 直拼卡宽度入册（键名风格与既有 7 键一致的小写蛇形）。"""
    assert CARD_SHELL_WIDTHS["help"] == 940
    assert CARD_SHELL_WIDTHS["usage"] == 900
    assert CARD_SHELL_WIDTHS["debug"] == 880
    assert CARD_SHELL_WIDTHS["media"] == 640
    # 既有 7 键不许被收编波顺手改动。
    assert CARD_SHELL_WIDTHS["universal"] == 1440
    assert CARD_SHELL_WIDTHS["affinity"] == 1180
    assert CARD_SHELL_WIDTHS["market"] == 1080
    assert CARD_SHELL_WIDTHS["finance"] == 1080
    assert CARD_SHELL_WIDTHS["song_panel"] == 980
    assert CARD_SHELL_WIDTHS["mermaid_max"] == 840
    assert CARD_SHELL_WIDTHS["error"] == 1080


def test_bridge_all_exports_error_card_renderer() -> None:
    """C11：bridge.__all__ 必须显式导出 render_error_card_html。"""
    assert "render_error_card_html" in bridge.__all__
    assert callable(bridge.render_error_card_html)


def test_bridge_context_injects_core_tokens() -> None:
    """各 render_* 上下文注入 CORE token 键（模板 Jinja 键 + :root CSS 变量双通道）。"""
    context = bridge._vis4_context()
    assert context["glass_main"] == GLASS_MAIN
    assert context["glass_foot"] == GLASS_FOOT
    assert context["glass_edge"] == GLASS_EDGE
    for key, value in OVERLAY_SCRIMS.items():
        assert context[key] == value
    assert context["semantic_danger"] == SEMANTIC_DANGER
    assert context["semantic_success"] == SEMANTIC_SUCCESS
    assert context["semantic_warning"] == SEMANTIC_WARNING
    assert context["score_hot"] == SCORE_HOT
    assert context["score_cold"] == SCORE_COLD
    assert context["mono_font_family"] == MONO_FONT_STACK
    assert context["radius_inner_xs"] == "4px"
    assert context["radius_pill"] == "999px"
    assert context["radius_circle"] == "50%"
    # 渲染产物经 :root 公共段携带同名 CSS 变量（模板 var() 可直接消费）。
    html_text = bridge.render_market_card_html({})
    assert "--mica-glass-main:linear-gradient(150deg, rgba(255, 255, 255, 0.66)" in html_text
    assert f"--mica-scrim-banner:{OVERLAY_SCRIMS['scrim_banner']};" in html_text
    assert "--semantic-danger:#d54941;" in html_text
    assert "--r-pill:999px;" in html_text
    assert f"--font-mono:{MONO_FONT_STACK};" in html_text


class _FullPageFakePage:
    """只暴露 render_card 主路径所需面的页面替身（.card 恒缺失 → 兜底路径）。"""

    def __init__(self) -> None:
        self.screenshot_kwargs: dict[str, Any] | None = None
        self.closed = False

    def set_content(self, html: str, wait_until: str = "load") -> None:
        assert html

    def wait_for_function(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def wait_for_timeout(self, ms: int) -> None:
        return None

    def query_selector(self, selector: str) -> None:
        return None

    def screenshot(self, **kwargs: Any) -> bytes:
        self.screenshot_kwargs = kwargs
        return b"full-page-bytes"

    def close(self) -> None:
        self.closed = True


def test_full_page_fallback_screenshot_omits_background() -> None:
    """C12：.card 缺失的 full_page 兜底截图必须 omit_background=True。

    body 透明契约（§2）是 omit_background 的前提；兜底路径与元素截图路径
    （既有 omit_background=True）必须同口径，否则兜底图带白底。
    """
    import threading
    from types import SimpleNamespace

    backend = PlaywrightRenderBackend.__new__(PlaywrightRenderBackend)
    backend.name = "playwright"
    backend.available = True
    backend._lock = threading.Lock()
    backend._local = threading.local()
    backend._max_concurrency = 1

    page = _FullPageFakePage()
    browser = SimpleNamespace(
        is_connected=lambda: True,
        new_page=lambda **kwargs: page,
        close=lambda: None,
    )
    handle = SimpleNamespace(
        start=lambda: SimpleNamespace(
            chromium=SimpleNamespace(launch=lambda: browser)
        ),
        close=lambda: None,
    )
    backend._sync_playwright = lambda: handle

    result = backend.render_card(
        {"html": "<div>x</div>", "viewport": {"width": 10, "height": 10}, "wait_ms": 0}
    )
    assert result == b"full-page-bytes"
    assert page.screenshot_kwargs == {
        "type": "png",
        "full_page": True,
        "omit_background": True,
    }
    assert page.closed

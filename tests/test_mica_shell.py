"""统一外壳生成器契约测试（v21r3 渲染统一，任务 1 第一步）。

锁定 `domains/render/card_render/mica_shell.py` 的产出：公共 token 全在、
顺序固定、书写风格统一（冒号后无空格）、取值与 `theme_tokens` 单一来源一致；
`render_shell` 产出满足 AGENTS.md UI 铁律（无 meta viewport / body 透明 /
根元素带 .card / 阴影只用两枚 token）。

本步只新增生成器、未接入任何卡，故这些断言不影响现有产出。
"""

from __future__ import annotations

import re

import pytest

from plugins.bot_unified_runtime.domains.render.card_render.mica_shell import (
    _MICA_DECOR_CSS,
    DRIFT_BLOBS_HTML,
    drift_blobs_html,
    glass_rules_css,
    mica_decor_css,
    render_root_tokens,
    render_shell,
    shell_base_css,
)
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    BLOB_COUNT,
    BLOB_DURATIONS,
    BRAND_THEME,
    FONT_FAMILY_STACK,
    GLASS_EDGE,
    GLASS_FOOT,
    GLASS_MAIN,
    MONO_FONT_STACK,
    OVERLAY_SCRIMS,
    RADIUS_INNER_CSS_VARS,
    SHADOW_PRIMARY,
    SHADOW_SECONDARY,
)

_WASH = {
    "wash_1": "#d9e0e7",
    "wash_2": "#dfdae7",
    "wash_3": "#dcdfea",
    "wash_mist": "#f4f5f6",
}

# 统一后必须全卡都有的公共 token（2026-09-18 起 --pc 家族已退役，不在册）。
_REQUIRED_TOKENS = (
    "--phase",
    "--accent",
    "--accent-dark",
    "--wash-1",
    "--wash-2",
    "--wash-3",
    "--wash-mist",
    "--wash-blob-1",
    "--text-main",
    "--text-sub",
    "--ink",
    "--muted",
    "--font-family",
    "--r-shell",
    "--r-panel",
    "--r-tile",
    "--mica-shadow",
    "--mica-shadow-soft",
)


def _tokens(**kwargs) -> str:
    return render_root_tokens(
        accent="#607080",
        accent_dark="#4c5966",
        phase=0.5,
        wash=_WASH,
        **kwargs,
    )


def test_all_public_tokens_present() -> None:
    tokens = _tokens()
    for token in _REQUIRED_TOKENS:
        assert f"{token}:" in tokens, f"缺公共 token {token}"


def test_accent_is_the_only_primary_color_token() -> None:
    """主色 token 只保留 --accent（2026-09-18 用户裁定：--pc 家族彻底退役）。"""
    tokens = _tokens()
    assert "--accent:#607080;" in tokens
    assert "--pc" not in tokens, "--pc 家族已退役，不得再出现在 token 块里"


@pytest.mark.parametrize(
    "retired",
    ["--pc:", "--pc-dark:", "--pc-light:", "--pc-mid:", "--pc-rgb:"],
)
def test_retired_pc_family_absent(retired: str) -> None:
    """退役家族逐个点名——防止有人把其中某个键名重新加回来。"""
    assert retired not in _tokens()


def test_colon_has_no_trailing_space() -> None:
    """书写风格统一：冒号后不得有空格（media 卡旧形态 `--x: #fff` 已废）。"""
    assert not re.search(r"--[a-z0-9-]+:\s", _tokens())


def test_token_values_single_source() -> None:
    tokens = _tokens()
    assert f"--text-main:{BRAND_THEME.text_main};" in tokens
    assert f"--text-sub:{BRAND_THEME.text_sub};" in tokens
    assert f"--font-family:{FONT_FAMILY_STACK};" in tokens
    assert f"--r-shell:{BRAND_THEME.shell_radius}px;" in tokens
    assert f"--r-panel:{BRAND_THEME.panel_radius}px;" in tokens
    assert f"--r-tile:{BRAND_THEME.tile_radius}px;" in tokens
    assert f"--mica-shadow:{SHADOW_PRIMARY};" in tokens
    assert f"--mica-shadow-soft:{SHADOW_SECONDARY};" in tokens


def test_public_token_order_is_stable() -> None:
    """公共 token 顺序固定——顺序漂移会让不同卡的 diff 噪音化。"""
    tokens = _tokens()
    positions = [tokens.index(f"{token}:") for token in _REQUIRED_TOKENS]
    assert positions == sorted(positions), "公共 token 声明顺序发生漂移"


def test_extras_appended_after_public_tokens() -> None:
    """卡特有 token 一律经 extras 追加在公共段之后。"""
    tokens = _tokens(extras={"--good": "#1a9e6c", "--bad": "#d64545"})
    assert "--good:#1a9e6c;" in tokens and "--bad:#d64545;" in tokens
    assert tokens.index("--mica-shadow-soft:") < tokens.index("--good:")


# ==================== render_shell 铁律 ====================


def _shell() -> str:
    return render_shell(
        title="测试卡",
        tokens=_tokens(),
        css=".tile { padding:8px; }",
        body_html='<div class="tile">正文</div>',
    )


def test_shell_has_no_meta_viewport() -> None:
    assert not re.search(r"<meta[^>]*viewport", _shell())


def test_shell_body_transparent() -> None:
    match = re.search(r"body\s*\{([^}]*)\}", _shell())
    assert match and re.search(r"background\s*:\s*transparent", match.group(1))


def test_shell_root_element_has_card_class() -> None:
    assert re.search(r'<div class="card[^"]*"', _shell())


def test_shell_has_single_style_block() -> None:
    assert _shell().count("<style>") == 1


def test_shell_shadow_only_two_tokens() -> None:
    css = re.search(r"<style>(.*?)</style>", _shell(), re.DOTALL)
    assert css
    for value in re.findall(r"box-shadow\s*:\s*([^;]+);", css.group(1)):
        assert value.strip() in {"none", "var(--mica-shadow)", "var(--mica-shadow-soft)"}


def test_shell_exactly_two_shadow_token_definitions() -> None:
    css = re.search(r"<style>(.*?)</style>", _shell(), re.DOTALL)
    assert css
    defined = re.findall(r"(--[a-z-]*shadow[a-z-]*)\s*:", css.group(1))
    assert set(defined) == {"--mica-shadow", "--mica-shadow-soft"}
    assert len(defined) == 2


# ==================== 视觉外壳公共规则 / 双层结构（步 2-6 接入面） ====================


def test_shell_base_css_carries_visual_shell() -> None:
    """视觉外壳公共规则：雾底打底 + wash 对角透色 + 1px 内高光描边 + 单枚阴影。

    四张直拼卡此前逐字各写一份，只有类名与宽度不同——参数化后其余单一来源。
    """
    css = shell_base_css("help-shell", width_px=940)
    assert ".help-shell { position:relative; width:940px; overflow:hidden;" in css
    assert "border-radius:var(--r-shell)" in css
    assert "box-shadow:var(--mica-shadow)" in css
    assert "linear-gradient(145deg, var(--wash-mist) 0%" in css
    assert ".help-shell > :not(.drift-blobs) { position:relative; z-index:1; }" in css


def test_shell_base_css_empty_class_returns_empty() -> None:
    """无外壳层的卡（shell_class 为空）不得凭空多出外壳规则。"""
    assert shell_base_css("") == ""


def test_render_shell_is_two_layer() -> None:
    """双层结构：外层纯容器 .card（+ stage 类）包住内层视觉外壳。"""
    html = render_shell(
        title="t",
        tokens=_tokens(),
        css=".x { color:red; }",
        body_html="<p>正文</p>",
        stage_class="help-stage",
        shell_class="help-shell",
        shell_width_px=940,
    )
    assert '<div class="card help-stage"><section class="help-shell">' in html
    assert html.count("<section") == 1 and html.count("</section>") == 1


def test_render_shell_single_layer_when_no_shell_class() -> None:
    html = render_shell(title="t", tokens=_tokens(), css="", body_html="<p>x</p>")
    assert "<section" not in html


def test_render_shell_card_is_pure_container() -> None:
    """外层 .card 必须是纯容器：透明、无边框、无圆角、无阴影。

    此前单层设计把视觉（圆角 + 阴影 + overflow）挂在外层，与四张直拼卡的
    实测结构不符；改成双层后视觉外壳归内层，外层只剩定位职责。
    """
    html = render_shell(title="t", tokens=_tokens(), css="", body_html="")
    match = re.search(r"\.card \{([^}]*)\}", html)
    assert match, "缺 .card 基线规则"
    body = match.group(1)
    assert "background:transparent" in body
    assert "border:0" in body
    assert "border-radius:0" in body
    assert "box-shadow:none" in body
    assert "width:fit-content" in body


def test_render_shell_includes_decor_by_default() -> None:
    """漂移装饰层与 .glass 默认内建（四张卡此前逐字各抄一份）。"""
    html = render_shell(title="t", tokens=_tokens(), css="", body_html="")
    assert ".drift-blobs {" in html
    assert "@keyframes mica-drift-a" in html
    assert "@keyframes mica-drift-b" in html
    assert "@keyframes mica-drift-c" in html
    assert ".glass {" in html
    assert "prefers-reduced-motion" in html


def test_render_shell_decor_can_be_disabled() -> None:
    html = render_shell(title="t", tokens=_tokens(), css="", body_html="", decor=False)
    assert ".drift-blobs" not in html
    assert ".glass" not in html


def test_root_tokens_carry_unified_comment() -> None:
    """统一注释随 token 块产出（此前四张卡各写一份、措辞互有出入）。"""
    assert "mica_shell.render_root_tokens" in _tokens()


def test_root_tokens_wash_blob_mix_defaults_to_35() -> None:
    """``--wash-blob-1`` 默认混 35% 主色（四张直拼卡与 7 模板中六张的历史值）。"""
    assert "var(--accent) 35%, var(--wash-1)" in _tokens()


def test_root_tokens_wash_blob_mix_parametrizable() -> None:
    """``error_card`` 的历史值是 24%——经参数保留原值，不得被「统一」抹平。

    这是步 5 的前置设施：模板接入统一生成器时，若强行把 24 拉成 35，
    色斑浓度会变，违反「视觉不变」硬约束。
    """
    tokens = _tokens(wash_blob_mix=24)
    assert "var(--accent) 24%, var(--wash-1)" in tokens
    assert "var(--accent) 35%, var(--wash-1)" not in tokens


def test_root_tokens_can_omit_phase_and_wash() -> None:
    """拆块能力：同一模板存在多个 ``:root`` 时，可让其中一块只出 accent 与公共十项。

    用途是避免**同一 token 在全局作用域重复声明**——``universal_card`` 的两个
    ``:root`` 都是全局选择器，公共段只允许出现在其中一处。
    """
    tokens = _tokens(include_phase=False, include_wash=False)
    assert "--phase:" not in tokens
    assert "--wash-1:" not in tokens
    assert "--wash-mist:" not in tokens
    assert "--wash-blob-1:" not in tokens
    # accent 家族与公共十项不受开关影响。
    assert "--accent:#607080;" in tokens
    assert "--accent-dark:#4c5966;" in tokens
    assert "--text-main:#18191c;" in tokens
    assert "--mica-shadow-soft:" in tokens


def test_root_tokens_include_wash_requires_mapping() -> None:
    """``include_wash=True`` 却漏传 wash 时立即报错，不静默产出半截 token 块。"""
    with pytest.raises(ValueError, match="wash"):
        render_root_tokens(
            accent="#607080", accent_dark="#4c5966", phase=0.5, wash=None
        )


# ==================== CORE 值册（2026-09-18 统一收尾波 C1/C2/C3/C4/C5/C9） ====================
# 值册登记值逐字符锁 + 生成器增发键锁。登记真身在 theme_tokens.py；本节保证
# render_root_tokens / shell_base_css / decor 生成器把这些值如实带进每张卡。


_CORE_TOKENS: tuple[str, ...] = (
    "--font-mono",
    "--r-inner-xs",
    "--r-inner-sm",
    "--r-inner-md",
    "--r-inner-lg",
    "--r-inner-xl",
    "--r-pill",
    "--r-circle",
    "--mica-glass-main",
    "--mica-glass-foot",
    "--mica-glass-edge",
    "--mica-scrim-badge",
    "--mica-scrim-banner",
    "--mica-scrim-code",
    "--mica-scrim-media",
    "--semantic-danger",
    "--semantic-success",
    "--semantic-warning",
    "--score-hot",
    "--score-cold",
)


def test_core_tokens_emitted_by_root_tokens() -> None:
    """render_root_tokens 增发 CORE 值册全部 token 键（模板 var() 可直接消费）。"""
    tokens = _tokens()
    for token in _CORE_TOKENS:
        assert f"{token}:" in tokens, f"缺 CORE 值册 token {token}"
    # 新键排在既有公共段之后、extras 之前（顺序锁补全：CORE 段整体有序）。
    positions = [tokens.index(f"{token}:") for token in _CORE_TOKENS]
    assert positions == sorted(positions), "CORE token 声明顺序发生漂移"
    assert tokens.index("--mica-shadow-soft:") < tokens.index("--mica-glass-main:")


def test_core_token_values_char_locked() -> None:
    """CORE token 取值与 theme_tokens 登记值逐字符一致（单一来源，不许走样）。"""
    tokens = _tokens()
    assert f"--mica-glass-main:{GLASS_MAIN};" in tokens
    assert f"--mica-glass-foot:{GLASS_FOOT};" in tokens
    assert f"--mica-glass-edge:{GLASS_EDGE};" in tokens
    for key, value in OVERLAY_SCRIMS.items():
        assert f"--mica-{key.replace('_', '-')}:{value};" in tokens
    assert "--semantic-danger:#d54941;" in tokens
    assert "--semantic-success:#2e9e6b;" in tokens
    assert "--semantic-warning:#b07d1a;" in tokens
    assert "--score-hot:#157347;" in tokens
    assert "--score-cold:#b42334;" in tokens
    assert f"--font-mono:{MONO_FONT_STACK};" in tokens
    for var, value in RADIUS_INNER_CSS_VARS.items():
        assert f"{var}:{value};" in tokens


def test_glass_registry_values_exact() -> None:
    """C3 玻璃两档 + 描边三 alpha 逐字符锁值（照裁决基线，不得擅改）。"""
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


def test_overlay_scrims_registry_exact() -> None:
    """C5 深色遮罩四员：语义分键、值逐字符锁。"""
    assert OVERLAY_SCRIMS == {
        "scrim_badge": "rgba(10, 12, 16, 0.72)",
        "scrim_banner": "rgba(15, 18, 24, 0.10)",
        "scrim_code": "rgba(28, 30, 38, 0.94)",
        "scrim_media": "rgba(38, 46, 56, 0.75)",
    }


def test_mono_font_stack_registry_exact() -> None:
    """C9 等宽字体栈单一登记（值照裁决基线逐字符锁）。"""
    assert MONO_FONT_STACK == (
        '"Cascadia Mono",Consolas,"JetBrains Mono","Courier New",monospace'
    )


def test_blob_constants_registry_exact() -> None:
    """C2 色斑常量入值册（数量 3 + 升序时长 46/52/58）。"""
    assert BLOB_COUNT == 3
    assert BLOB_DURATIONS == (46, 52, 58)


def test_shell_base_css_includes_glass_segment() -> None:
    """shell_base_css 缺省产出完整公共段：外壳渐变 + 两档玻璃 + 1px 描边。"""
    css = shell_base_css("help-shell", width_px=940)
    assert ".help-shell { position:relative; width:940px; overflow:hidden;" in css
    assert f".glass {{ background:{GLASS_MAIN}," in css
    assert f".glass-foot {{ background:{GLASS_FOOT}," in css
    assert GLASS_EDGE in css
    assert css.count("box-shadow:var(--mica-shadow-soft)") == 2
    assert "box-shadow:var(--mica-shadow);" in css


def test_shell_base_css_glass_can_be_disabled() -> None:
    """glass=False 供 render_shell 装配（玻璃归 decor 段），不产生重复定义。"""
    css = shell_base_css("help-shell", width_px=940, glass=False)
    assert ".glass {" not in css
    assert ".drift-blobs {" not in css
    assert ".help-shell { position:relative; width:940px;" in css


def test_render_shell_glass_defined_exactly_once() -> None:
    """玻璃规则经 decor 段携带且全页恰一次（decor 关=零玻璃，铁律开关语义）。"""
    html = render_shell(
        title="t",
        tokens=_tokens(),
        css="",
        body_html="",
        shell_class="help-shell",
        shell_width_px=940,
    )
    assert html.count(".glass {") == 1
    assert html.count(".glass-foot {") == 1
    disabled = render_shell(
        title="t", tokens=_tokens(), css="", body_html="", decor=False
    )
    assert ".glass" not in disabled


def test_decor_css_default_is_single_instance_of_constant() -> None:
    """模块常量 = 生成器缺省实例（历史字节形态：前导换行分段）。"""
    assert _MICA_DECOR_CSS == "\n" + mica_decor_css()
    assert glass_rules_css().startswith("/* 液态玻璃面板")


def test_decor_css_default_durations_match_history() -> None:
    """缺省逐斑时长=历史交错序 a=46s / b=58s / c=52s，注释头=升序登记值。"""
    assert "wash 三色半透明互相透过，46s/52s/58s 交错漂移" in _MICA_DECOR_CSS
    assert "mica-drift-a 46s ease-in-out" in _MICA_DECOR_CSS
    assert "mica-drift-b 58s ease-in-out" in _MICA_DECOR_CSS
    assert "mica-drift-c 52s ease-in-out" in _MICA_DECOR_CSS
    assert "* -46s)" in _MICA_DECOR_CSS
    assert "* -58s - 9s)" in _MICA_DECOR_CSS
    assert "* -52s - 21s)" in _MICA_DECOR_CSS


def test_decor_css_blob_count_param() -> None:
    """blob_count 参数化（两斑卡迁三斑的逆通道：取前 N 个登记斑）。"""
    css = mica_decor_css(blob_count=2)
    assert "drift-a" in css and "drift-b" in css
    assert "drift-c" not in css
    assert "@keyframes mica-drift-c" not in css
    with pytest.raises(ValueError, match="blob_count"):
        mica_decor_css(blob_count=0)
    with pytest.raises(ValueError, match="blob_count"):
        mica_decor_css(blob_count=4)


def test_decor_css_durations_param() -> None:
    """durations 参数按 drift-a/b/c 位次注入（显式值不走登记位次表）。"""
    css = mica_decor_css(durations=(30, 40, 50))
    assert "mica-drift-a 30s ease-in-out" in css
    assert "mica-drift-b 40s ease-in-out" in css
    assert "mica-drift-c 50s ease-in-out" in css
    with pytest.raises(ValueError, match="durations"):
        mica_decor_css(durations=(30,))


def test_decor_css_phase_default_param() -> None:
    """phase 兜底参数化：缺省 0.2（历史值），显式值逐处替换。"""
    assert _MICA_DECOR_CSS.count("var(--phase, 0.2)") == 3
    custom = mica_decor_css(phase_default=0.75)
    assert custom.count("var(--phase, 0.75)") == 3
    assert "var(--phase, 0.2)" not in custom


def test_drift_blobs_html_default_matches_constant() -> None:
    """DOM 片段常量 = 生成器缺省实例（三斑、无内联 phase）。"""
    assert drift_blobs_html() == DRIFT_BLOBS_HTML
    assert DRIFT_BLOBS_HTML.count('<span class="drift-blob drift-') == 3
    assert 'style="--phase:' not in DRIFT_BLOBS_HTML


def test_drift_blobs_html_params() -> None:
    """blob_count / phase 注入参数可用（直拼卡不经 :root 钉帧的备用通道）。"""
    two = drift_blobs_html(blob_count=2)
    assert "drift-b" in two and "drift-c" not in two
    phased = drift_blobs_html(phase=0.37)
    assert 'style="--phase:0.37"' in phased
    assert 'style="--phase:0.5"' in drift_blobs_html(phase="0.5")
    with pytest.raises(ValueError, match="blob_count"):
        drift_blobs_html(blob_count=99)

"""FIX8 席回归锁（2026-09-21 规格审计修复批）：两条渲染域规格缺口。

① ``mica_decor_css`` 越界崩溃（SA5 报、本席实跑复现于
``domains/render/card_render/mica_shell.py:197``）：显式 ``durations`` 分支的守卫只查
``len(durations) < blob_count``，字典推导却遍历**全量登记表** ``_BLOB_SPECS``（恒 3 项），
于是 ``blob_count=1 + durations=(46,)`` 直接 IndexError。本件锁死 0/1/2/3 全档 +
durations 长度匹配/不足/富余三种调用契约，并钉住「缺省实例逐字节不变」（生产 7 个调用点
全走缺省，修复零行为变更）。

② ``theme_tokens.__all__`` 漏导出 6 枚公开符号（含 ``SHADOW_CSS_VARS``）：既有门
（test_rendering_contract / test_template_visual_audit / bridge）一律显式具名 import、
唯一 ``import *`` 的兼容垫片又显式重列了同名，``__all__`` 在两条真实消费通道上都不承重，
缺口静默。本件把「模块级公开绑定 ⊆ ``__all__``」升成机器门（AST 结构比对，随模块增长
自动生效），并锁住 ``import *`` 实际产出面 = ``__all__``、垫片转发面 ⊇ ``__all__``。
"""

from __future__ import annotations

import ast
import builtins
import pathlib

import pytest

from plugins.bot_unified_runtime.domains.render.card_render import theme_tokens
from plugins.bot_unified_runtime.domains.render.card_render.mica_shell import (
    _BLOB_SPECS,
    _MICA_DECOR_CSS,
    drift_blobs_html,
    mica_decor_css,
)

_RENDER_PKG = (
    pathlib.Path(theme_tokens.__file__).resolve().parent
)


# ==================== ① mica_decor_css 参数边界 ====================


def test_decor_css_blob_count_one_with_single_duration_does_not_crash() -> None:
    """RED 复现主证：blob_count=1 + durations=(46,) 曾经 IndexError（mica_shell.py:197）。"""
    css = mica_decor_css(blob_count=1, durations=(46,))
    assert "animation:mica-drift-a 46s ease-in-out" in css
    assert "drift-blob.drift-b" not in css
    assert "drift-blob.drift-c" not in css
    assert "@keyframes mica-drift-b" not in css
    assert "@keyframes mica-drift-c" not in css
    # 注释头只列实际入册斑的秒数（升序），不得把未生成的斑算进去。
    assert "46s 交错漂移" in css
    assert "/52s" not in css and "/58s" not in css


@pytest.mark.parametrize("blob_count", [1, 2, 3])
def test_decor_css_blob_count_matches_output_cardinality(blob_count: int) -> None:
    """blob_count 全有效档：DOM 规则数、keyframes 数、注释头项数三者自洽。"""
    durations = tuple(range(10, 10 + blob_count))
    css = mica_decor_css(blob_count=blob_count, durations=durations)
    keys = [spec[0] for spec in _BLOB_SPECS[:blob_count]]
    for key in keys:
        assert f".drift-blob.drift-{key} {{" in css
        assert f"@keyframes mica-drift-{key} {{" in css
    for key in [spec[0] for spec in _BLOB_SPECS[blob_count:]]:
        # 注意判据形态：基类规则 ``.drift-blob`` 本身含子串 "drift-b"，
        # 故按「独立斑规则名/独立 keyframes 名」判定，不用裸 "drift-<key>"。
        assert f"drift-blob.drift-{key}" not in css
        assert f"@keyframes mica-drift-{key}" not in css
    assert css.count("@keyframes mica-drift-") == blob_count
    header = "/".join(f"{value}s" for value in sorted(durations))
    assert f"{header} 交错漂移" in css


@pytest.mark.parametrize("blob_count", [0, -1, 4, len(_BLOB_SPECS) + 1])
def test_decor_css_rejects_out_of_range_blob_count(blob_count: int) -> None:
    """越界 blob_count 必须是 ValueError（含 0=「不要斑」也不受理），不得静默出空层。"""
    with pytest.raises(ValueError, match="blob_count"):
        mica_decor_css(blob_count=blob_count)
    with pytest.raises(ValueError, match="blob_count"):
        mica_decor_css(blob_count=blob_count, durations=(46,))


@pytest.mark.parametrize("blob_count,duration_len", [(2, 1), (3, 1), (3, 2), (1, 0)])
def test_decor_css_rejects_short_durations_with_value_error(
    blob_count: int, duration_len: int
) -> None:
    """durations 短于 blob_count = 契约违反，报 ValueError 而非 IndexError。"""
    with pytest.raises(ValueError, match="durations"):
        mica_decor_css(
            blob_count=blob_count, durations=tuple(range(1, duration_len + 1))
        )


def test_decor_css_accepts_longer_durations_and_takes_positional_prefix() -> None:
    """durations 长于 blob_count：按 drift-a/b/c 位次直取前 N 个，多余值忽略（不红）。"""
    css = mica_decor_css(blob_count=2, durations=(30, 40, 50, 60))
    assert "animation:mica-drift-a 30s ease-in-out" in css
    assert "animation:mica-drift-b 40s ease-in-out" in css
    assert "drift-c" not in css
    assert "50s" not in css and "60s" not in css


def test_decor_css_default_instance_is_unchanged_by_the_fix() -> None:
    """缺省实例字节现状锁：模块常量仍等于缺省生成器产出（历史 46/58/52 交错序）。"""
    assert _MICA_DECOR_CSS == "\n" + mica_decor_css()
    assert "wash 三色半透明互相透过，46s/52s/58s 交错漂移" in _MICA_DECOR_CSS
    assert "animation:mica-drift-a 46s" in _MICA_DECOR_CSS
    assert "animation:mica-drift-b 58s" in _MICA_DECOR_CSS
    assert "animation:mica-drift-c 52s" in _MICA_DECOR_CSS


@pytest.mark.parametrize("blob_count", [0, 1, 2, 3, 4])
def test_drift_blobs_html_boundary_contract(blob_count: int) -> None:
    """DOM 片段生成器同档边界：1..3 出 N 枚斑，0/4 报 ValueError（与 CSS 侧同契约）。"""
    if 1 <= blob_count <= len(_BLOB_SPECS):
        html = drift_blobs_html(blob_count=blob_count)
        assert html.count('<span class="drift-blob drift-') == blob_count
    else:
        with pytest.raises(ValueError, match="blob_count"):
            drift_blobs_html(blob_count=blob_count)


# ==================== ② __all__ 导出面完备性机器门 ====================


def _public_top_level_bindings(tree: ast.Module) -> list[str]:
    """模块级公开绑定（函数/类/赋值），下划线私有面不计。"""
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in names:
                    names.append(target.id)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if node.name not in names:
                names.append(node.name)
    return [n for n in names if not n.startswith("_") and n != "__all__"]


def _all_literal(module_path: pathlib.Path) -> list[str] | None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            )
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            return [
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant)
            ]
    return None


@pytest.mark.parametrize(
    "module_file",
    sorted(p.name for p in _RENDER_PKG.glob("*.py") if _all_literal(p) is not None),
)
def test_all_covers_every_public_binding(module_file: str) -> None:
    """结构门：声明了 __all__ 的渲染模块，公开绑定必须逐个入册（漏一枚即红）。

    此前 test_rendering_contract.py 全绿仍漏 6 枚的根因就是它只测显式 import，
    本门换成 AST 结构比对，随模块增长自动生效、无需再点名。
    """
    declared = _all_literal(_RENDER_PKG / module_file)
    assert declared is not None
    tree = ast.parse((_RENDER_PKG / module_file).read_text(encoding="utf-8"))
    missing = [n for n in _public_top_level_bindings(tree) if n not in declared]
    assert not missing, f"{module_file}.__all__ 漏导出公开符号：{missing}"


@pytest.mark.parametrize(
    "symbol",
    [
        "DIVIDER",
        "FONT_FAMILY_STACK",
        "GLOW_ACCENT",
        "SHADOW_CSS_VARS",
        "SHADOW_LEVELS",
        "TYPE_SCALE_PX",
    ],
)
def test_previously_missing_symbols_are_now_exported(symbol: str) -> None:
    """SA5 报的 6 枚逐个点名锁死（含 SHADOW_CSS_VARS——渲染契约阴影白名单的来源）。"""
    assert symbol in theme_tokens.__all__
    assert getattr(theme_tokens, symbol) is not None


def test_star_import_yields_exactly_the_declared_public_surface() -> None:
    """``import *`` 实际产出面 == ``__all__``（漏名在星通道上必须不存在）。"""
    namespace: dict[str, object] = {}
    exec(  # noqa: S102 — 测试内受控星导入，用于比对 __all__ 承重面
        "from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import *",
        namespace,
    )
    star_names = {
        name for name in namespace if not name.startswith("_") and name != "__builtins__"
    }
    assert star_names == set(theme_tokens.__all__)
    assert "SHADOW_CSS_VARS" in star_names


def test_compat_shim_still_reexports_the_whole_public_surface() -> None:
    """旧路径垫片转发面 ⊇ 真身 ``__all__``（补名后垫片不得出现断供）。"""
    shim_namespace: dict[str, object] = {}
    exec(  # noqa: S102 — 同上，比对垫片星转发面
        "from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import *",
        shim_namespace,
    )
    forwarded = {
        name
        for name in shim_namespace
        if not name.startswith("_") and name != "__builtins__"
    }
    missing = sorted(set(theme_tokens.__all__) - forwarded - set(dir(builtins)))
    assert not missing, f"domains.render.card_render.theme_tokens 再导出缺项：{missing}"

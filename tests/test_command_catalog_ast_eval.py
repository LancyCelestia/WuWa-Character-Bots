"""S38 · P-S28-1 回归锁：命令目录生成器必须能吃「模块级常量」（AST 级求值）。

背景（SEAT-S28.md §五/§六）：`ast.literal_eval` 只认字面量、不认 `Name` 节点 ⇒
echo `_HELP_ENTRY_META` 里 13 枚 `chat_scope` + 5 枚 `fallback` 手抄同串一旦提成单一常量源，
`scripts/command_catalog.py` 当场 `ValueError` 崩。本锁钉死四件事：

1. 孪生对拍：同一份值，一份内联字面量、一份经模块级常量引用，`_literal_assign` 求值必须全等
   （「提常量 ⇒ 生成器仍产出与今天逐字节相同目录」的合成源版前置）；
2. 真实语料逐字节：`render(merged_entries())` 必须仍等于盘上 `docs/command-catalog.md`（78 topics 零漂移）；
3. 单源化已真实落地：META 值段里那两枚串各以常量引用出现 13/5 次、字符串字面量在 META 内清零、
   常量定义唯一且值与今天逐字相同（禁假合规）；
4. 安全红线：字面量取数禁止 `eval`；不可解析名/自环常量必须仍抛 `ValueError`（禁无限放宽）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.command_catalog import (
    DOC,
    ECHO_SOURCE,
    _entry_meta,
    _literal_assign,
    _module_tree,
    merged_entries,
    render,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_SCRIPT = REPO_ROOT / "scripts" / "command_catalog.py"

_SCOPE_VALUE = "群聊/私聊行为一致（无会话分支）"
_FALLBACK_VALUE = "渲染失败回退纯文本"
_SCOPE_CONST = "_CHAT_SCOPE_CONSISTENT"
_FALLBACK_CONST = "_FALLBACK_RENDER_TEXT"

# 一、合成源孪生对拍 -----------------------------------------------------------

_INLINE_SOURCE = '''\
_LABEL = "示例"
_META = {
    "甲": {
        "chat_scope": "示例",
        "network": True,
        "priority": 1,
        "ratio": 0.5,
        "note": None,
        "pair": ("x", 2),
    },
    "乙": {"lines": ["一", "二"], "tags": {"t"}, "nested": [{"k": (1, 2)}]},
}
'''

_PROMOTED_SOURCE = '''\
_LABEL = "示例"
_NET = True
_PRI = 1
_RATIO = 0.5
_NOTE = None
_PAIR = ("x", 2)
_LINES = ["一", "二"]
_TAGS = {"t"}
_NESTED = [{"k": (1, 2)}]
_META = {
    "甲": {
        "chat_scope": _LABEL,
        "network": _NET,
        "priority": _PRI,
        "ratio": _RATIO,
        "note": _NOTE,
        "pair": _PAIR,
    },
    "乙": {"lines": _LINES, "tags": _TAGS, "nested": _NESTED},
}
'''


def _parse_tmp(tmp_path: Path, filename: str, source: str) -> ast.Module:
    path = tmp_path / filename
    path.write_text(source, encoding="utf-8")
    return _module_tree(path)


def test_promoted_constants_evaluate_identically(tmp_path: Path) -> None:
    """提常量 ⇒ 求值全等：生成器必须解析「同模块模块级常量引用」，产出与内联字面量逐字节相同。"""
    inline = _literal_assign(_parse_tmp(tmp_path, "inline_probe.py", _INLINE_SOURCE), "_META")
    promoted = _literal_assign(_parse_tmp(tmp_path, "promoted_probe.py", _PROMOTED_SOURCE), "_META")
    assert promoted == inline
    assert inline["甲"]["chat_scope"] == "示例"  # 基线自检：内联源本身可解析


def test_unresolvable_name_still_raises_value_error(tmp_path: Path) -> None:
    """负锁：Name 指向非模块级常量（函数调用结果）必须 ValueError——禁无限放宽。"""
    source = '_X = build("y")\n_META = {"甲": {"scope": _X}}\n'
    with pytest.raises(ValueError):
        _literal_assign(_parse_tmp(tmp_path, "bad_probe.py", source), "_META")


def test_circular_module_constants_raise_value_error(tmp_path: Path) -> None:
    """负锁：模块常量自环必须 ValueError（禁递归失控/静默吞值）。"""
    source = '_A = (_B,)\n_B = (_A,)\n_META = {"甲": {"v": _A}}\n'
    with pytest.raises(ValueError):
        _literal_assign(_parse_tmp(tmp_path, "cycle_probe.py", source), "_META")


def test_missing_assignment_still_raises_value_error(tmp_path: Path) -> None:
    """负锁：找不到的名字照旧 ValueError（既有行为不许被顺手改掉）。"""
    with pytest.raises(ValueError):
        _literal_assign(_parse_tmp(tmp_path, "missing_probe.py", "_A = 1\n"), "_NEVER_DEFINED")


# 二、安全红线：字面量取数不许多出 eval ---------------------------------------


def test_generator_never_calls_eval_builtin() -> None:
    """只准 AST 白名单求值：command_catalog.py 不得出现对内建 `eval` 的调用。"""
    tree = _module_tree(CATALOG_SCRIPT)
    offenders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "eval"
    ]
    assert not offenders, "literal 取数禁用 eval()（安全红线，S38 简报逐字）"


# 三、真实语料：逐字节产物与 78 topics 不许漂 ----------------------------------


def test_catalog_render_stays_byte_identical() -> None:
    """render(merged_entries()) 必须逐字节等于盘上目录（提常量前后同一判据常驻）。"""
    assert render(merged_entries()) == DOC.read_text(encoding="utf-8")


def test_meta_runtime_values_survive_promotion() -> None:
    """运行期语义不变：META 合并视图里这两串仍各在场 13/5 枚（值零丢失，禁为绿改文案）。"""
    meta = _entry_meta()
    scope_hits = [topic for topic, entry in meta.items() if entry.get("chat_scope") == _SCOPE_VALUE]
    fallback_hits = [topic for topic, entry in meta.items() if entry.get("fallback") == _FALLBACK_VALUE]
    assert len(scope_hits) == 13, scope_hits
    assert len(fallback_hits) == 5, fallback_hits


# 四、单源化必须真实落地（禁假合规：改了生成器却没提常量） ---------------------


def _module_level_values(tree: ast.Module) -> dict[str, ast.expr]:
    mapping: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        value = node.value
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                mapping[target.id] = value
    return mapping


def test_promotion_landed_as_single_constant_source() -> None:
    """18 枚手抄值已提成唯一常量源：定义各 1 枚、值逐字不变、META 内全部走 Name 引用、字面量清零。"""
    tree = _module_tree(ECHO_SOURCE)
    values = _module_level_values(tree)
    meta_node = values.get("_HELP_ENTRY_META")
    assert meta_node is not None, "_HELP_ENTRY_META 定义未找到"
    for const, literal in ((_SCOPE_CONST, _SCOPE_VALUE), (_FALLBACK_CONST, _FALLBACK_VALUE)):
        definition = values.get(const)
        assert isinstance(definition, ast.Constant), f"{const} 必须是模块级字面常量赋值"
        assert definition.value == literal, f"{const} 的值与今日逐字口径不符"
    names = [node for node in ast.walk(meta_node) if isinstance(node, ast.Name)]
    assert sum(1 for node in names if node.id == _SCOPE_CONST) == 13
    assert sum(1 for node in names if node.id == _FALLBACK_CONST) == 5
    leftovers = [
        node
        for node in ast.walk(meta_node)
        if isinstance(node, ast.Constant) and node.value in (_SCOPE_VALUE, _FALLBACK_VALUE)
    ]
    assert not leftovers, "META 内仍残留手抄字面量（单源化未完成）"

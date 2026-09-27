"""契约锁：标注 `-> bool` 的函数不许 return 一个列表（2026-09-28 实弹形态）。

来由：订阅投递腿 `_deliver_v2_event` 在某一版草稿里写成 `return outcomes`
（`outcomes: list[tuple[str, bool]]`），而消费侧 `subscription_scheduler.py` 的契约是
`delivery_fn: Callable[..., Awaitable[bool]]`。列表恒真 ⇒ **只要有一个目的地，
全败也被记成投递成功**。mypy 当场判出（return-value），但 mypy 这条线在 HEAD 上
本来就红着几枚，靠它当哨兵不牢，所以补这把只读 AST 锁：它只认一个形态——
函数标了 `-> bool`，体内把某个名字绑成列表（`x = []` / `x: list[...] = []` /
`x = [...]` / 推导式），最后 `return x`。

锁两面：①真身零违规（含 `_deliver_v2_event` 仍在位且仍标 `-> bool`，防改名把锁
测成空转）；②投毒样本必红。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT_PKG = REPO / "plugins" / "bot_unified_runtime"

POISON = '''
async def _deliver_event(event) -> bool:
    outcomes: list[tuple[str, bool]] = []
    for destination in event.destinations:
        try:
            outcomes.append((str(destination.id), True))
        except OSError:
            outcomes.append((str(destination.id), False))
    return outcomes
'''

CLEAN_SIBLINGS = '''
async def _deliver_ok(event) -> bool:
    outcomes: list[tuple[str, bool]] = []
    outcomes.append(("d1", True))
    return bool(outcomes) and all(sent for _id, sent in outcomes)


def _count_not_bool(event) -> int:
    rows = []
    rows.append(1)
    return len(rows)
'''


def _bool_annotated(fn: ast.AST) -> bool:
    return isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and isinstance(
        getattr(fn, "returns", None), ast.Name
    ) and fn.returns.id == "bool"


def _list_bound_names(fn: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.AnnAssign) and isinstance(
            node.annotation, (ast.Subscript, ast.List)
        ):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
        elif isinstance(node, ast.Assign) and isinstance(
            node.value, (ast.List, ast.ListComp)
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def violations(src: str, origin: str) -> list[str]:
    """返回「标 bool 却 return 列表变量」的点名清单（`文件:行 函数名 -> 变量名`）。"""
    found: list[str] = []
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if not _bool_annotated(fn):
            continue
        list_names = _list_bound_names(fn)
        if not list_names:
            continue
        for ret in ast.walk(fn):
            if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Name):
                if ret.value.id in list_names:
                    found.append(f"{origin}:{ret.lineno} {fn.name} -> {ret.value.id}")
    return found


def test_poison_shape_is_caught() -> None:
    hit = violations(POISON, "poison.py")
    assert len(hit) == 1 and "_deliver_event" in hit[0], f"锁没牙：{hit}"


def test_correct_forms_are_not_flagged() -> None:
    assert violations(CLEAN_SIBLINGS, "clean.py") == [], "误伤：bool 形与返回 int 的都不该报"


def test_production_tree_is_clean() -> None:
    offenders: list[str] = []
    for path in ROOT_PKG.rglob("*.py"):
        try:
            offenders.extend(violations(path.read_text(encoding="utf-8"), path.name))
        except SyntaxError:  # 半途写坏的盘上文件由别的门管，本锁跳过不误报。
            continue
    assert offenders == [], "有函数标 `-> bool` 却把列表当真假返回：\n- " + "\n- ".join(offenders)


def test_the_guarded_function_is_still_there() -> None:
    """反向腿：被守的那枚函数改名/删掉/丢掉 bool 标注，本锁必须当场红，
    否则「生产零违规」会因为没人再匹配它而变成空转。"""
    src = (ROOT_PKG / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    target = next(
        (
            fn
            for fn in ast.walk(tree)
            if getattr(fn, "name", "") == "_deliver_v2_event"
        ),
        None,
    )
    assert target is not None, "_deliver_v2_event 不见了——请同步改本锁的锚点，别删锁"
    assert _bool_annotated(target), "_deliver_v2_event 的返回标注变了，契约锁失去对象"

"""任务 D1：`config.py` 字段不得重复定义（AST 行为锁）。

背景（2026-09-29 用户裁定第 4 项）：`bot_randpic_min_side` / `bot_meme_library_min_side`
各被写了两次（300 与 400），Python 类体后者覆盖前者 ⇒ 生效值是 400，但两行都在册
= 双口径。曾经靠人眼发现，本门把它变成机器执法：同名字段第二次出现当场红。

判据用 AST，不 import 被测件（与 progress_ack parity 锁同一手法）：
- 主锁：解析真 `config.py`，收集所有顶层 AnnAssign 目标名，断言无重名。
- 注毒自证：给判定函数喂一段含重名的源码，必须点名；喂不重复源码，必须放行。
  两腿缺一即"门只对着真身绿、判据本身没牙"。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PY = ROOT / "plugins" / "bot_unified_runtime" / "config.py"


def _top_level_field_names(source: str) -> list[str]:
    """收集 Config 类体内所有**顶层** AnnAssign 目标名（含重复，顺序即书写顺序）。

    只认 `ClassDef` 名为 Config 的直接子节点，避免把方法体内的局部注解算进来。
    """
    tree = ast.parse(source)
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Config":
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                names.append(stmt.target.id)
    return names


def duplicate_field_names(source: str) -> list[str]:
    """返回被重复定义的顶层字段名（升序去重）。空 = 无重名。"""
    seen: set[str] = set()
    dupes: set[str] = set()
    for name in _top_level_field_names(source):
        if name in seen:
            dupes.add(name)
        seen.add(name)
    return sorted(dupes)


def test_config_has_no_duplicate_field_definitions() -> None:
    source = CONFIG_PY.read_text(encoding="utf-8")
    dupes = duplicate_field_names(source)
    assert not dupes, (
        "config.py 存在重复定义的字段（后者覆盖前者＝双口径，生效值只有一处说话）："
        f"{dupes}｜处置：删掉被覆盖的那一行，保留唯一真值并在注释写明选定理由"
    )


def test_poison_duplicate_field_is_named() -> None:
    """注毒自证：喂一段重名源码，判定函数必须点名，否则本门是只对着真身绿的死锁。"""
    poisoned = (
        "class Config:\n"
        "    bot_a: int = 300\n"
        "    bot_b: int = 1\n"
        "    bot_a: int = 400\n"
    )
    assert duplicate_field_names(poisoned) == ["bot_a"]


def test_clean_source_is_allowed() -> None:
    """放行自证：不重复的源码判空，证明判定不是恒红。"""
    clean = (
        "class Config:\n"
        "    bot_a: int = 400\n"
        "    bot_b: int = 1\n"
    )
    assert duplicate_field_names(clean) == []

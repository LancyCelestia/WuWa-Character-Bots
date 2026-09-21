"""统一接入波 · S-GAP 席只读扫描器：中央在册表 vs 生产真实通路的差额台账。

一句话——回答「还剩多少没接入」这个问题。判据全走 ast 静态解析，零运行时副作用、
零消息发送；不写任何仓内文件，结果只打 stdout。

复用（不复制第二套同构实现，铁律 7）：tests/test_orchestration_callsite_single.py 的
``_invoker_cids`` / ``_rel`` / ``_PKG_ROOT`` 直接 import。

通路四态（对每个在册 capability_id）：
  wired            —— 生产里有 ``….invoke(CapabilityRequest(capability_id=X))``
  generic_executor —— 走 ``pipeline.handle_async`` / ``_run_simple_capability`` 泛型执行器
  not_wired        —— 在册但全树零调用点（纯登记未接线）
外加「未在册」对照：调用点上出现的、但不在 CAPABILITY_DESCRIPTOR 里的 id（幽灵调用点）。
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = _REPO_ROOT / "tests"
sys.path.insert(0, str(_TESTS_DIR))
sys.path.insert(0, str(_REPO_ROOT))

import test_orchestration_callsite_single as v1gate  # 复用中央判据（tests/ 已在 sys.path 上）

_PKG_ROOT = v1gate._PKG_ROOT


def _kwarg_literal(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _attr_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _generic_executor_cids(tree: ast.AST) -> set[str]:
    """``pipeline.handle_async(...)`` / ``_run_simple_capability(...)`` 上的 capability_id 字面量。"""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _attr_name(node.func) in {"handle_async", "_run_simple_capability"}:
            cid = _kwarg_literal(node, "capability_id")
            if cid:
                found.add(cid)
    return found


def _load_descriptor_table() -> dict[str, tuple[str, ...]]:
    """{capability_id: authored_by}；import 失败交由调用方诚实处理（不在扫描器里放宽判据）。"""
    module = importlib.import_module("plugins.bot_unified_runtime.runtime.capability_protocols")
    table = module.CAPABILITY_DESCRIPTOR
    return {cid: tuple(table[cid].authored_by) for cid in table}


def _iter_sources() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for path in sorted(_PKG_ROOT.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "capability_id=" in text:  # 廉价预筛
            out.append((v1gate._rel(path), text))
    return out


def build_census() -> dict[str, dict[str, list[str]]]:
    """{capability_id: {"wired":[rel…], "generic":[rel…], "phantom":[rel…]}}。"""
    invoke_hits: dict[str, set[str]] = {}
    generic_hits: dict[str, set[str]] = {}
    for rel, src in _iter_sources():
        if rel == "runtime/capability_protocols.py":
            continue  # 中央真源自身的 descriptor 构造不算生产调用点
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for cid in v1gate._invoker_cids(tree):
            invoke_hits.setdefault(cid, set()).add(rel)
        for cid in _generic_executor_cids(tree):
            generic_hits.setdefault(cid, set()).add(rel)

    table = _load_descriptor_table()
    census: dict[str, dict[str, list[str]]] = {}
    for cid in sorted(table):
        census[cid] = {
            "wired": sorted(invoke_hits.get(cid, set())),
            "generic": sorted(generic_hits.get(cid, set())),
            "phantom": [],
        }
    # 幽灵调用点：调用点上出现、但不在册的 id（说明"接了个不存在的能力"或"在册表漏收"）。
    for cid in sorted(set(invoke_hits) | set(generic_hits)):
        if cid not in table:
            census[cid] = {
                "wired": sorted(invoke_hits.get(cid, set())),
                "generic": sorted(generic_hits.get(cid, set())),
                "phantom": ["<不在 CAPABILITY_DESCRIPTOR>"],
            }
    return census


def _family(cid: str) -> str:
    head = cid.split(".", 1)[0]
    return head if "." in cid else cid


def _classify(entry: dict[str, list[str]]) -> str:
    if entry["phantom"]:
        return "phantom"
    if entry["wired"]:
        return "wired"
    if entry["generic"]:
        return "generic_executor"
    return "not_wired"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出机读 JSON（默认人读表格）")
    args = parser.parse_args(argv)

    census = build_census()
    import json

    if args.json:
        print(json.dumps(census, ensure_ascii=False, indent=2))
        return 0

    by_state: dict[str, list[str]] = {"wired": [], "generic_executor": [], "not_wired": [], "phantom": []}
    for cid, entry in sorted(census.items()):
        by_state[_classify(entry)].append(cid)

    registered_total = sum(1 for e in census.values() if not e["phantom"])
    print(f"在册 descriptor 总数：{registered_total}")
    for state in ("wired", "generic_executor", "not_wired", "phantom"):
        cids = by_state[state]
        print(f"\n[{state}] {len(cids)} 条")
        fam: dict[str, int] = {}
        for cid in cids:
            fam[_family(cid)] = fam.get(_family(cid), 0) + 1
        for f in sorted(fam):
            members = [c for c in cids if _family(c) == f]
            print(f"  - {f}: {fam[f]}  ({', '.join(members)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

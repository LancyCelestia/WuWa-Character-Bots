"""幽灵配置读点普查：只读扫描，只往 stdout 打。

用途：找出「代码里读 config.bot_xxx 而 Config 类没有这个字段」的读点。
判据与常驻门 tests/test_config_read_points_declared.py 同源（本文件是它的人读版）。
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG_PY = REPO / "plugins" / "bot_unified_runtime" / "config.py"
DEFAULT_SCOPES = ("plugins", "scripts", "bot.py")

# 接收者名字形如 config / cfg / xx_config / xx_cfg / settings 者视为配置对象
_CONFIGISH = re.compile(r"(?:^|_)(?:config|cfg|settings)$", re.IGNORECASE)

# 同名不同物的 config 句柄：不是插件 Config，读它不算幽灵（本表由门锁定"条目必须仍命中真树"）。
# 键用**完整接收者文本**（self.config ≠ config）——同一文件里两种句柄并存，放宽到词尾会藏污。
NON_PLUGIN_CONFIG_RECEIVERS: dict[tuple[str, str], str] = {
    ("plugins/bot_unified_runtime/domains/ops/integrations/gscore_bridge.py", "self.config"):
        "GsCoreConfig（同文件 :66 的本地 dataclass，NoneBot 驱动侧配置）；"
        "注意同文件的裸 config 形参确实是插件 Config，不在排除之列",
    ("bot.py", "_driver_config"):
        "nonebot.get_driver().config，其实测 model_config extra='allow' ⇒ 未声明键也活",
}


def config_fields() -> set[str]:
    """Config 类的字段名真值（AST 静态，不 import 因此零副作用）。"""
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8-sig"), filename=str(CONFIG_PY))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Config":
            names: set[str] = set()
            for stmt in node.body:
                targets: list[ast.expr] = []
                if isinstance(stmt, ast.AnnAssign):
                    targets = [stmt.target]
                elif isinstance(stmt, ast.Assign):
                    targets = stmt.targets
                for t in targets:
                    if isinstance(t, ast.Name) and t.id.startswith("bot_"):
                        names.add(t.id)
            return names
    raise SystemExit("config.py 里找不到 class Config")


def py_files(scopes: list[str]) -> Iterator[Path]:
    seen: set[Path] = set()
    for scope in scopes:
        root = REPO / scope
        base = [root] if root.is_dir() else ([root] if root.is_file() else [])
        for b in base:
            for p in sorted(b.rglob("*.py")) if b.is_dir() else [b]:
                if "__pycache__" in p.parts or p in seen:
                    continue
                seen.add(p)
                yield p


def _recv_label(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_configish(node: ast.expr, rel: str = "", hits: list | None = None) -> bool:
    label = _recv_label(node)
    if not label or not _CONFIGISH.search(label):
        return False
    full = ast.unparse(node)  # 完整接收者文本：self.config 与 config 是两个不同句柄
    if (rel, full) in NON_PLUGIN_CONFIG_RECEIVERS:
        if hits is not None:
            hits.append({"file": rel, "line": getattr(node, "lineno", 0), "recv": full,
                         "reason": NON_PLUGIN_CONFIG_RECEIVERS[(rel, full)]})
        return False
    return True


def _const_str(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _fstring_prefix(node: ast.expr) -> str | None:
    """f"bot_xxx_{y}" 这种拼出来的键名：不可静态判定，只登记模板。"""
    if isinstance(node, ast.JoinedStr):
        head = node.values[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str) and head.value.startswith("bot_"):
            return head.value
    return None


def scan(scopes: list[str]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """返回 (属性式读点, 字面量 getattr 读点, 动态键读点, 已排除的非插件 Config 接收者读点)。"""
    fields = config_fields()
    attr_hits: list[dict] = []
    getattr_hits: list[dict] = []
    dynamic_hits: list[dict] = []
    excluded: list[dict] = []
    for path in py_files(scopes):
        try:
            src = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            continue
        rel = path.relative_to(REPO).as_posix()
        # 模块级 `NAME = "bot_x"` 常量：getattr(config, NAME) 靠它才判得动（漏了就漏报幽灵）
        const_strs: dict[str, str] = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant) \
                    and isinstance(stmt.value.value, str):
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name):
                        const_strs[tgt.id] = stmt.value.value
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                    and node.attr.startswith("bot_") and _is_configish(node.value, rel, excluded)):
                attr_hits.append(
                    {"file": rel, "line": node.lineno, "key": node.attr,
                     "recv": ast.unparse(node.value)[:48], "known": node.attr in fields}
                )
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id not in {"getattr", "hasattr", "setattr", "delattr"} or len(node.args) < 2:
                    continue
                obj, key, key_node = node.args[0], node.args[1], node.args[1]
                if not _is_configish(obj, rel, excluded):
                    continue
                if isinstance(key, ast.Name):
                    key = ast.Constant(value=const_strs.get(key.id))
                literal = _const_str(key)
                if literal is not None and literal.startswith("bot_"):
                    default = ast.unparse(node.args[2]) if len(node.args) > 2 else "AttributeError"
                    getattr_hits.append(
                        {"file": rel, "line": node.lineno, "key": literal, "func": node.func.id,
                         "recv": ast.unparse(obj)[:48], "default": default, "known": literal in fields}
                    )
                else:
                    tmpl = _fstring_prefix(key)
                    if tmpl is not None:
                        dynamic_hits.append(
                            {"file": rel, "line": node.lineno, "template": tmpl,
                             "expr": ast.unparse(key_node)[:80], "recv": ast.unparse(obj)[:48]}
                        )
                    elif node.func.id == "getattr":
                        dynamic_hits.append(
                            {"file": rel, "line": node.lineno, "template": "<nonliteral>",
                             "expr": ast.unparse(key_node)[:80], "recv": ast.unparse(obj)[:48]}
                        )
    return attr_hits, getattr_hits, dynamic_hits, excluded


def ghost_read_points(scopes: list[str] | None = None) -> list[dict]:
    """真值：幽灵读点，按 (文件, 键名) 归并（行号只作人读，不进身份——本仓被坐标漂移咬过）。"""
    attr_hits, getattr_hits, _dyn, _exc = scan(list(scopes or DEFAULT_SCOPES))
    merged: dict[tuple[str, str], dict] = {}
    for hit in [*attr_hits, *getattr_hits]:
        if hit["known"]:
            continue
        entry = merged.setdefault(
            (hit["file"], hit["key"]),
            {"file": hit["file"], "key": hit["key"], "forms": set(), "lines": [], "defaults": set()},
        )
        entry["forms"].add("attribute" if "default" not in hit else f"getattr:{hit['func']}")
        entry["lines"].append(hit["line"])
        if "default" in hit:
            entry["defaults"].add(hit["default"])
    return [
        {**merged[k], "forms": sorted(merged[k]["forms"]), "lines": sorted(merged[k]["lines"]),
         "defaults": sorted(merged[k]["defaults"])}
        for k in sorted(merged)
    ]


def dynamic_key_points(scopes: list[str] | None = None) -> list[dict]:
    _a, _g, dyn, _e = scan(list(scopes or DEFAULT_SCOPES))
    return dyn


def excluded_receiver_points(scopes: list[str] | None = None) -> list[dict]:
    _a, _g, _d, exc = scan(list(scopes or DEFAULT_SCOPES))
    return exc


def dead_config_keys(scopes: list[str] | None = None) -> list[str]:
    """③ 反向死键：Config 有、扫描面零读点（R65 裁定保留，本函数只登记不提议删）。"""
    fields = config_fields()
    attr_hits, getattr_hits, _dyn, _exc = scan(list(scopes or DEFAULT_SCOPES))
    read = {h["key"] for h in attr_hits} | {h["key"] for h in getattr_hits}
    return sorted(fields - read)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scope", action="append", dest="scopes")
    args = ap.parse_args(argv)
    scopes = args.scopes or list(DEFAULT_SCOPES)
    fields = config_fields()
    attr_hits, getattr_hits, dynamic_hits, excluded = scan(scopes)
    print(f"Config 字段数（AST 实测）：{len(fields)}")
    print(f"属性式读点：{len(attr_hits)}（幽灵 {sum(1 for h in attr_hits if not h['known'])}）")
    print(f"字面量 getattr 读点：{len(getattr_hits)}（幽灵 {sum(1 for h in getattr_hits if not h['known'])}）")
    print(f"动态键读点（不可静态判定）：{len(dynamic_hits)}")
    print(f"排除的非插件 Config 接收者读点：{len(excluded)}")

    def dump(title: str, rows: list[dict]) -> None:
        print(f"\n=== {title} ===")
        for r in rows:
            print(f"{r['file']}:{r['line']} {r.get('key', r.get('template'))} recv={r['recv']}"
                  + (f" default={r['default']}" if "default" in r else "")
                  + (f" expr={r['expr']}" if "expr" in r else ""))

    dump("① 幽灵读点归并（读代码里有、Config 里没有）",
         [{"file": g["file"], "line": ",".join(map(str, g["lines"])), "key": g["key"],
           "recv": "/".join(g["forms"]) + " defaults=" + ",".join(g["defaults"])}
          for g in ghost_read_points(scopes)])
    dump("② 动态键读点", dynamic_hits)
    dump("④ 已排除（同名不同物的 config 句柄）", [
        {"file": e["file"], "line": e["line"], "template": e["reason"], "recv": e["recv"]} for e in excluded])
    dead = dead_config_keys(scopes)
    print(f"\n=== ③ 反向死键：Config 有、扫描面内零读点，共 {len(dead)}（R65 裁定保留，不提议删）===")
    for k in dead:
        print(k)
    return 0


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    raise SystemExit(main())

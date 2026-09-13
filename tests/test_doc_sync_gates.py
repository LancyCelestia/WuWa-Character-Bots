"""T5 文档机械化同步门禁（全离线，纯 AST/文本解析，不 import nonebot）。

盘点（.superpowers/sdd/2026-09-12-shorekeeper-global-audit/trg-inventory.md §6）
证实两处「手改孤岛」：

1. ``docs/route-matrix.md``：此前只被校验 RouteKind 字符串出现过
   （test_documentation_consistency.test_route_matrix_covers_every_route_kind），
   行级字段无人核对 → 本文件对 §2 问法矩阵做全行机械比对：
   kind 覆盖（缺行/多行双向）、priority 数值、capability id、判定函数名。
2. ``docs/config-catalog-full.md``：此前无任何自动门禁 → 本文件做键覆盖门禁：
   「增量有门、存量不追溯」——新增批次键必须已登记；config.py 字段全集 −
   已登记键 − KNOWN_MISSING 白名单必须为空（白名单外未登记即 fail）。

触发词列（is_*_command 英文触发词由并行批次补录）以「现值不与代码矛盾」
为过门标准：门禁只验证文档引用的函数/能力 id 确实存在于代码，不做触发词
全量等价比对。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_ROUTER_PY = ROOT / "plugins" / "bot_unified_runtime" / "runtime" / "base_router.py"
INIT_PY = ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
CONFIG_PY = ROOT / "plugins" / "bot_unified_runtime" / "config.py"
ROUTE_MATRIX_MD = ROOT / "docs" / "route-matrix.md"
CONFIG_CATALOG_MD = ROOT / "docs" / "config-catalog-full.md"

# --------------------------------------------------------------------------
# 本批（2026-09-12 T-Spec V1）新增键：必须已在 config-catalog-full.md 登记。
# --------------------------------------------------------------------------

NEW_BATCH_KEYS: frozenset[str] = frozenset(
    {
        "bot_addressing_preferences_db_path",
        "bot_stocks_enabled",
        "bot_fx_enabled",
        "bot_market_retry_on_empty",
    }
)

# --------------------------------------------------------------------------
# 历史缺失键白名单：config-catalog-full.md 编写时即滞后于 config.py，
# 本批次只封「增量门」，存量不追溯。初始 157 键为 2026-09-12 红灯实跑清点
# 所得，经三期按功能域补录（一期 40 + 二期 65 + 三期 52）后于 2026-09-13
# 清零。空白名单 = 门禁退化为「config.py 字段全集必须全部登记」的全量
# 等价校验；missing/stale 双向断言对空集天然成立（sorted(frozenset()) == []
# → assert not [] 恒真），无需特判。常量骨架保留：未来若出现经评审豁免的
# 新键，仍从这里恢复。
# --------------------------------------------------------------------------

KNOWN_MISSING: frozenset[str] = frozenset()


# --------------------------------------------------------------------------
# 共用：AST 静态提取（不 import 插件包，离线安全）
# --------------------------------------------------------------------------


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _route_kind_member_values(tree: ast.Module) -> dict[str, str]:
    """RouteKind 枚举成员名 → 字符串取值（如 ALIAS -> "alias"）。"""
    values: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RouteKind":
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                ):
                    values[stmt.targets[0].id] = ast.literal_eval(stmt.value)
    return values


def _build_route_rules_entries(tree: ast.Module) -> list[dict[str, object]]:
    """从 build_route_rules 的 return [...] 逐行提取 RouteRule 注册表。"""
    entries: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "build_route_rules"):
            continue
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Return) and isinstance(sub.value, ast.List)):
                continue
            for elt in sub.value.elts:
                assert isinstance(elt, ast.Call), "RouteRule 注册表出现非 Call 行"
                kind_attr = elt.args[0]
                assert isinstance(kind_attr, ast.Attribute)
                matcher_name = ""
                for kw in elt.keywords:
                    if kw.arg == "matcher" and isinstance(kw.value, ast.Name):
                        matcher_name = kw.value.id
                if len(elt.args) > 6 and isinstance(elt.args[6], ast.Name):
                    matcher_name = elt.args[6].id
                entries.append(
                    {
                        "member": kind_attr.attr,
                        "capability_id": ast.literal_eval(elt.args[1]),
                        "priority": ast.literal_eval(elt.args[2]),
                        "matcher": matcher_name,
                    }
                )
    return entries


def _ignore_fallback_entries(tree: ast.Module) -> set[tuple[str, int]]:
    """classify_message_route 里的 IGNORE 兜底 RouteDecision（capability, priority）。"""
    fallbacks: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.FunctionDef) and node.name == "classify_message_route"
        ):
            continue
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)):
                continue
            if sub.func.id != "RouteDecision" or len(sub.args) < 3:
                continue
            kind_arg = sub.args[0]
            if (
                isinstance(kind_arg, ast.Attribute)
                and isinstance(kind_arg.value, ast.Name)
                and kind_arg.value.id == "RouteKind"
                and kind_arg.attr == "IGNORE"
            ):
                fallbacks.add(
                    (
                        ast.literal_eval(sub.args[1]),
                        ast.literal_eval(sub.args[2]),
                    )
                )
    return fallbacks


def _defined_function_names(*paths: Path) -> set[str]:
    names: set[str] = set()
    for path in paths:
        for node in ast.walk(_parse(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
    return names


# --------------------------------------------------------------------------
# 门禁 1：route-matrix §2 问法矩阵全行机械比对
# --------------------------------------------------------------------------


def _route_matrix_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = line.startswith("## 2.")
            continue
        if not in_section or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        if set(cells[1]) <= set("-: ") or cells[1] == "路由 kind":
            continue  # 分隔行 / 表头
        rows.append(cells)
    return rows


_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _matcher_referenced_names(cell: str) -> set[str]:
    """匹配器/处理程序列里反引号包住的函数名（on_* 工厂与 _xxx 判定函数）。"""
    names: set[str] = set()
    for span in re.findall(r"`([^`]+)`", cell):
        for tok in _IDENT_RE.findall(span):
            if "_" in tok or tok.startswith("on"):
                names.add(tok)
    return names


def _rule_table(tree: ast.Module) -> tuple[dict[str, dict[str, object]], list[str]]:
    member_values = _route_kind_member_values(tree)
    entries = _build_route_rules_entries(tree)
    by_kind: dict[str, dict[str, object]] = {}
    for entry in entries:
        kind_value = member_values[str(entry["member"])]
        by_kind[kind_value] = entry
    return by_kind, [str(e["capability_id"]) for e in entries]


def test_route_matrix_rows_match_base_router() -> None:
    tree = _parse(BASE_ROUTER_PY)
    rules_by_kind, capability_ids = _rule_table(tree)
    fallbacks = _ignore_fallback_entries(tree)
    known_caps = set(capability_ids) | {cap for cap, _ in fallbacks}
    rows = _route_matrix_rows(ROUTE_MATRIX_MD.read_text(encoding="utf-8"))
    assert rows, "route-matrix §2 问法矩阵解析为空（表头/分节格式变了？）"

    doc_kinds: set[str] = set()
    caps_by_kind: dict[str, list[str]] = {}
    errors: list[str] = []
    for cells in rows:
        kind, prio_raw, cap_cell = cells[1], cells[2], cells[4]
        doc_kinds.add(kind)
        caps_by_kind.setdefault(kind, []).append(cap_cell)
        try:
            priority = int(prio_raw)
        except ValueError:
            errors.append(f"kind={kind} 优先级列不是整数：{prio_raw!r}")
            continue
        rule = rules_by_kind.get(kind)
        if rule is None:
            continue
        if priority != rule["priority"]:
            errors.append(
                f"kind={kind} 优先级漂移：doc={priority} code={rule['priority']}"
            )
        for cap_id in re.findall(r"bot\.[a-z_]+", cap_cell):
            if cap_id not in known_caps:
                errors.append(
                    f"kind={kind} 能力列引用未知能力 id：{cap_id}"
                    f"（base_router 现有：{sorted(known_caps)}）"
                )

    ignore_kinds = {"ignore"} if fallbacks else set()
    unknown_kinds = doc_kinds - set(rules_by_kind) - ignore_kinds
    if unknown_kinds:
        errors.append(f"doc 出现代码不存在的路由 kind：{sorted(unknown_kinds)}")
    missing_rows = sorted(set(rules_by_kind) - doc_kinds)
    if missing_rows:
        errors.append(f"route-matrix 缺行（代码有 RouteRule 而文档无）：{missing_rows}")

    # capability id 覆盖：每个代码能力 id 必须能在同 kind 的文档行里找到。
    for kind_value, rule in sorted(rules_by_kind.items()):
        cap_id = str(rule["capability_id"])
        if not any(cap_id in cell for cell in caps_by_kind.get(kind_value, [])):
            errors.append(f"kind={kind_value} 能力 id {cap_id} 未出现在文档能力列")

    # IGNORE 兜底（classify_message_route 的空消息/无匹配回退）也逐条对行。
    doc_ignore_rows = [c for c in rows if c[1] == "ignore"]
    for cap_id, priority in sorted(fallbacks):
        hit = [
            c
            for c in doc_ignore_rows
            if c[2].strip() == str(priority) and cap_id in c[4]
        ]
        if not hit:
            errors.append(
                f"ignore 兜底（{cap_id}, priority={priority}）在文档缺行或缺 capability id"
            )

    assert not errors, "route-matrix 与 base_router 漂移：\n- " + "\n- ".join(errors)


def test_route_matrix_matcher_names_exist_in_code() -> None:
    """判定函数名「现值不与代码矛盾」：文档点名的函数必须在路由/分发层真实存在。

    on_message/on_command 等 NoneBot 工厂不是本包函数，以出现在 __init__.py
    源码文本为准；其余名字必须是 base_router.py / __init__.py 里定义过的函数。
    """
    init_source = INIT_PY.read_text(encoding="utf-8")
    defined = _defined_function_names(BASE_ROUTER_PY, INIT_PY)
    errors: list[str] = []
    for cells in _route_matrix_rows(ROUTE_MATRIX_MD.read_text(encoding="utf-8")):
        for name in sorted(_matcher_referenced_names(cells[3])):
            if name in defined:
                continue
            if name.startswith("on") and name in init_source:
                continue
            errors.append(f"kind={cells[1]} 匹配器列引用了不存在的函数：{name}")
    assert not errors, "route-matrix 匹配器列与代码矛盾：\n- " + "\n- ".join(errors)


# --------------------------------------------------------------------------
# 门禁 2：config-catalog 键覆盖（增量有门、存量不追溯）
# --------------------------------------------------------------------------


def _config_field_names() -> set[str]:
    """config.py 各 ClassDef 内的注解字段全集（pydantic 模型字段）。"""
    names: set[str] = set()
    for node in ast.walk(_parse(CONFIG_PY)):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    names.add(stmt.target.id)
    return names


def _normalize_catalog_key(token: str) -> str | None:
    """表格键名还原：BOT_XXX / bot_xxx / _xxx（BOT_ 前缀省略）统一成 bot_xxx。"""
    lowered = token.strip().lower()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", lowered):
        return None
    if lowered.startswith("bot_"):
        return lowered
    stripped = lowered.lstrip("_")
    return f"bot_{stripped}" if stripped else None


def _catalog_registered_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or set(cells[0]) <= set("-: "):
            continue
        for token in re.findall(r"`([^`]+)`", cells[0]):
            key = _normalize_catalog_key(token)
            if key:
                keys.add(key)
    return keys


def test_config_catalog_registers_new_batch_keys() -> None:
    registered = _catalog_registered_keys(CONFIG_CATALOG_MD.read_text(encoding="utf-8"))
    unregistered = sorted(NEW_BATCH_KEYS - registered)
    assert not unregistered, (
        f"本批新增配置键未登记进 docs/config-catalog-full.md（A26 增量区）：{unregistered}"
    )


def test_config_catalog_covers_config_fields() -> None:
    """config.py 字段全集必须登记在册，历史缺口走 KNOWN_MISSING 白名单。"""
    fields = _config_field_names()
    assert len(fields) >= 400, f"config.py 字段提取异常：仅 {len(fields)} 个"
    registered = _catalog_registered_keys(CONFIG_CATALOG_MD.read_text(encoding="utf-8"))
    missing = sorted(fields - registered - KNOWN_MISSING)
    stale = sorted(KNOWN_MISSING - fields - registered)
    assert not missing, (
        "config.py 存在未登记且不在 KNOWN_MISSING 白名单的配置键"
        "（新字段必须补录 docs/config-catalog-full.md，或经评审后进白名单）：\n- "
        + "\n- ".join(missing)
    )
    assert not stale, f"KNOWN_MISSING 里已无对应代码字段的过期条目（请摘除）：{stale}"

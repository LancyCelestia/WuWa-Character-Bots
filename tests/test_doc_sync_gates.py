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

3. **生成链的「漏维 / 读空」双向锁（S246R，2026-09-25）**：四支取数口
   （`doc_sync` / `board_doc_sync` / `command_catalog` / `ownership_project`）
   对能力真身册的**维**是否吃得到、对**降成再导出壳的声明源**是否响亮——
   见文件末尾「门禁 3」一节（含注毒自证）。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import command_catalog as cc  # 只 stdlib + 同目录 `doc_sync`，不碰被别席定制装载的件
import doc_sync as ds  # 塌陷锁与册维的唯一取数口
import ownership_project as op  # 纯 stdlib 装载器与 RULES 登记表


def _bds():  # 延迟导入的理由见本函数 docstring
    """`board_doc_sync` **必须延迟到用例运行时**才 import——不能在收集期。

    踩坑实录（本席 2026-09-25 实测）：`tests/test_doc_template_write_port_cas_tx241.py`
    用 `spec_from_file_location("doc_template_sync", …)` 造了一份**定制模块对象**并写进
    `sys.modules`，再 `import board_doc_sync`，好让 `bds.dts is dts`（它的注毒靠
    `monkeypatch.setattr(dts, "_integrity_token_of", …)` 打到写口上）。
    如果本文件在**模块顶层**就 `import board_doc_sync`，pytest 收集期会把 `bds` 绑到
    普通那份 `doc_template_sync` 上；TX241 随后注册的定制件与 `bds.dts` 就不是同一个对象 ⇒
    它的注毒打空 ⇒ `test_board_port_has_teeth_*` 报「注毒没杀动：另有守卫拦下了」。
    等价于：**我的 import 语句把别席的反证注毒变成了哑弹**。延迟导入把绑定时机交还给
    先收集的那位，两边都拿得到同一份模块对象。
    """
    import board_doc_sync

    return board_doc_sync

BASE_ROUTER_PY = ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "base_router.py"
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


# --------------------------------------------------------------------------
# G-5 增量（report-T86 §G-5.1，T89 席追加）：TTS 域 catalog 登记专项门。
# 泛化全集门（test_config_catalog_covers_config_fields）之上点名 TTS 域，
# 防域键整批漂移被泛化缺口淹没；负样本自检证判定力（内嵌伪键能抓红）。
# --------------------------------------------------------------------------


def test_config_catalog_registers_all_tts_keys() -> None:
    """bot_tts_* 全键（config.py 现值集合）必须在 config-catalog-full.md 登记。

    catalog 既有口径允许省略 ``BOT_`` 前缀（``_tts_*`` 形态），经
    ``_normalize_catalog_key`` 归一后比对。负样本自检：内嵌伪键必须
    「不在 config.py、不在 catalog、且会被本门缺失计算抓红」，防
    「集合恒空/恒全」的空转门。
    """
    fields = _config_field_names()
    tts_fields = {name for name in fields if name.startswith("bot_tts_")}
    assert len(tts_fields) >= 20, f"bot_tts_* 字段提取异常：仅 {len(tts_fields)} 个"
    registered = _catalog_registered_keys(CONFIG_CATALOG_MD.read_text(encoding="utf-8"))
    missing = sorted(tts_fields - registered)
    assert not missing, (
        "TTS 域配置键未登记进 docs/config-catalog-full.md（G-5 专项门；"
        "catalog 允许 _tts_* 省略 BOT_ 前缀的既有写法）：\n- " + "\n- ".join(missing)
    )
    # 负样本自检：伪键三重不在场 + 缺失计算对「在 config、不在 catalog」的键
    # 必须抓红（若 catalog 解析器或字段提取器空转，此处先红）。
    fake = "bot_tts_negative_probe_not_a_real_key"
    assert fake not in tts_fields
    assert fake not in registered
    assert sorted(({fake} | tts_fields) - registered) == [fake]


# --------------------------------------------------------------------------
# 门禁 2b/2c（M2-30R 2026-10-13 三元对账席）：
#   2b 「默认值/缺省」列必须 == config.py 声明缺省 ⇒ 拦 A-1 型假账（她照册改配置读到假值）；
#   2c 在册键名必须在 Config 存在或行文本明写「已退役」 ⇒ 拦 A-2 型假账（她照册填 .env、
#       pydantic `extra='ignore'` 静默吞、无失败信号）。
# 与既有 `test_config_catalog_covers_config_fields` 是**三把不同的尺**：那把查「字段有没有在册」
# （Config→catalog 单向），本两把查「在册的假账不能活」两向（catalog→Config 值级 + 名级）。
# 判据来自 `.superpowers/sdd/2026-09-27-fullload/reports-m2/M2-30-DOC-KEY-TRUTH.md` §3；
# 跳过口径照该账本 §1（复合行只判存在性与可改性、⚠️/样例自陈格不判默认、F 节自审「位置|改前|改后」
# 与 C 节「键|转换规则」两张册剔出——那是热改白名单展示与 F 席记账件，非 Config 字段注册表）。
# --------------------------------------------------------------------------


def _fold_const(node: ast.AST, root: ast.Module) -> tuple[bool, Any]:
    """常量折叠 `(ok, value)`：literal_eval → 模块顶层 Name → BinOp/UnaryOp 递归。

    返回 `(False, None)` 表示"折不动"（函数调用、`Field(default_factory=...)`、
    `Optional[X] = None` 里 None 之类可折但值确为 None 时会 `(True, None)`，两者要分清）。
    """
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        pass
    if isinstance(node, ast.Name):
        for n in root.body:
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id == node.id:
                        return _fold_const(n.value, root)
        return False, None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        ok, v = _fold_const(node.operand, root)
        if not ok:
            return False, None
        return True, (-v if isinstance(node.op, ast.USub) else +v)
    if isinstance(node, ast.BinOp):
        okl, l = _fold_const(node.left, root)
        okr, r = _fold_const(node.right, root)
        if not (okl and okr):
            return False, None
        op = node.op
        try:
            if isinstance(op, ast.Add):
                return True, l + r
            if isinstance(op, ast.Sub):
                return True, l - r
            if isinstance(op, ast.Mult):
                return True, l * r
            if isinstance(op, ast.FloorDiv):
                return True, l // r
            if isinstance(op, ast.Div):
                return True, l / r
        except Exception:
            return False, None
        return False, None
    return False, None


def _config_field_defaults() -> dict[str, tuple[str, Any]]:
    """Config 类体每枚字段的 `(kind, code_default)`；
    kind ∈ `{'literal','no_default','unevaled'}`；仅 kind=='literal' 时值可判默认列。"""
    tree = _parse(CONFIG_PY)
    out: dict[str, tuple[str, Any]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Config":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    fname = stmt.target.id
                    if stmt.value is None:
                        out[fname] = ("no_default", None)
                        continue
                    val = stmt.value
                    if isinstance(val, ast.Call) and isinstance(val.func, ast.Name) and val.func.id == "Field":
                        default_kw = next((kw.value for kw in val.keywords if kw.arg == "default"), None)
                        if default_kw is None:
                            out[fname] = ("no_default", None)
                            continue
                        ok, v = _fold_const(default_kw, tree)
                        out[fname] = ("literal", v) if ok else ("unevaled", None)
                        continue
                    ok, v = _fold_const(val, tree)
                    out[fname] = ("literal", v) if ok else ("unevaled", None)
            break
    return out


def _split_catalog_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_catalog_sep(cells: list[str]) -> bool:
    return bool(cells) and all(c and set(c) <= set("-: ") for c in cells)


def _find_catalog_col(headers: list[str], tokens: tuple[str, ...], skip_first: bool) -> int | None:
    for i, h in enumerate(headers):
        if skip_first and i == 0:
            continue
        for t in tokens:
            if t in h:
                return i
    return None


def _catalog_env_token_to_field(token: str) -> str | None:
    t = token.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t):
        return None
    low = t.lower()
    if low.startswith("bot_"):
        return low
    if low.startswith("_"):
        return "bot_" + low.lstrip("_")
    return None


def _iter_catalog_registration_rows(text: str, need_default_col: bool):
    """扫 markdown 表格，yield 每张「键名/键/字段」注册表的行（跳过 F 节自审、C 节转换规则、A25 非 Config）。

    返回 dict：line（1 起）、key_tokens（反引号内原文）、keys（归一后 bot_xxx）、
    default_cell（若 need_default_col=True 且表有「默认值/缺省」列）、row_text、is_compound。
    """
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        if not lines[i].startswith("|"):
            i += 1
            continue
        header = _split_catalog_row(lines[i])
        if i + 1 >= n or not lines[i + 1].startswith("|") or not _is_catalog_sep(_split_catalog_row(lines[i + 1])):
            i += 1
            continue
        i += 2
        header_join = "|".join(header)
        # 剔除：F 席自审「位置|键|改前|改后」／C 节「键|转换规则」／A25 「键名|消费方」（非 Config 键）
        if any(w in header_join for w in ("改前", "改后")) or "转换规则" in header_join or "消费方" in header_join:
            # 但仍需消费该表的行范围：走到下一个非 | 行为止
            while i < n and lines[i].startswith("|"):
                i += 1
            continue
        key_col = _find_catalog_col(header, ("键名", "键", "字段"), skip_first=False)
        def_col = _find_catalog_col(header, ("默认值", "缺省", "默认"), skip_first=True)
        if key_col is None:
            while i < n and lines[i].startswith("|"):
                i += 1
            continue
        if need_default_col and def_col is None:
            while i < n and lines[i].startswith("|"):
                i += 1
            continue
        while i < n and lines[i].startswith("|"):
            body = _split_catalog_row(lines[i])
            if _is_catalog_sep(body):
                i += 1
                continue
            if key_col >= len(body):
                i += 1
                continue
            key_tokens = re.findall(r"`([^`]+)`", body[key_col])
            keys = [k for k in (_catalog_env_token_to_field(t) for t in key_tokens) if k]
            yield {
                "line": i + 1,
                "key_tokens": key_tokens,
                "keys": keys,
                "default_cell": body[def_col] if def_col is not None and def_col < len(body) else None,
                "row_text": " | ".join(body),
                "is_compound": len(keys) > 1,
            }
            i += 1


def _doc_default_matches_code(cell: str, code_default: Any) -> bool:
    toks = re.findall(r"`([^`]+)`", cell)
    if not toks:
        toks = [cell.strip()]
    for raw in toks:
        tok = raw.strip()
        m = re.match(r"^\*\*(.+?)\*\*$", tok)
        if m:
            tok = m.group(1).strip()
        stripped = tok.strip('"').strip("'").strip()
        if code_default is None:
            if stripped.lower() in ("none", "null"):
                return True
            continue
        if isinstance(code_default, bool):
            if stripped.lower() == ("true" if code_default else "false"):
                return True
            continue
        if isinstance(code_default, (int, float)):
            try:
                if abs(float(stripped) - float(code_default)) < 1e-9:
                    return True
            except ValueError:
                pass
            continue
        if isinstance(code_default, str):
            if code_default == "" and stripped in ("", "空", "空串", "<空串>", "<空>"):
                return True
            if stripped == code_default:
                return True
            continue
        if isinstance(code_default, (list, tuple)):
            if stripped == "[]" and len(code_default) == 0:
                return True
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped) if False else None  # 不引 json，走 ast
                except Exception:
                    parsed = None
                if parsed is not None and list(parsed) == list(code_default):
                    return True
            try:
                parsed = ast.literal_eval(stripped)
                if isinstance(parsed, list) and parsed == list(code_default):
                    return True
            except Exception:
                pass
            continue
        if isinstance(code_default, dict):
            if stripped == "{}" and len(code_default) == 0:
                return True
            try:
                parsed = ast.literal_eval(stripped)
                if isinstance(parsed, dict) and parsed == code_default:
                    return True
            except Exception:
                pass
            continue
    return False


_RETIRED_MARKERS_RE = re.compile(
    r"退役|废弃|不再使用|已移除|不生效|extra.*ignore|填了不生效|静默丢弃|静默吞|"
    r"config\.py 无此字段|config\.py 无字段|无字段|纯运行时|"
    r"运行时.*覆盖键|运行时.*专属|config\.py 零命中|只存在.*SETTABLE_KEYS|已删"
)


def _catalog_default_column_mismatches(text: str, defaults: dict[str, tuple[str, Any]]) -> tuple[set[str], dict[str, list[dict]]]:
    matched: set[str] = set()
    unmatched: dict[str, list[dict]] = {}
    for r in _iter_catalog_registration_rows(text, need_default_col=True):
        if r["is_compound"]:
            continue  # M2-30 §1 口径：复合行不判默认列
        cell = r["default_cell"]
        if cell is None:
            continue
        if "⚠️" in cell or "样例" in cell:
            continue  # 册子自陈「样例值 ≠ 代码默认」
        if "见 config" in cell or "见config" in cell or cell.strip() == "见":
            continue
        for k in r["keys"]:
            kind, code_default = defaults.get(k, ("missing", None))
            if kind != "literal":
                continue
            if _doc_default_matches_code(cell, code_default):
                matched.add(k)
            else:
                unmatched.setdefault(k, []).append(r)
    return matched, unmatched


def test_config_catalog_default_column_matches_config() -> None:
    """catalog「默认值/缺省」列必须 == config.py 声明缺省（A-1 型假账执法腿，M2-30R 追加）。"""
    text = CONFIG_CATALOG_MD.read_text(encoding="utf-8")
    defaults = _config_field_defaults()
    assert len(defaults) >= 400, f"config.py 字段缺省提取异常：仅 {len(defaults)} 个"
    matched, unmatched = _catalog_default_column_mismatches(text, defaults)
    errors: list[str] = []
    for k in sorted(unmatched):
        if k in matched:
            continue  # 同键他行有对上 → 视为已在册，多表间不重复报红
        first = unmatched[k][0]
        _, code_default = defaults[k]
        errors.append(
            f"docs/config-catalog-full.md:{first['line']} 键 `{k}`「默认值/缺省」列 = {first['default_cell']!r}；"
            f"config.py 声明缺省 = {code_default!r}（改此格或加 ⚠️/样例 声明）"
        )
    assert not errors, (
        "catalog 默认值列与 config.py 代码缺省漂移（A 档「她照册改配置读到假值」；M2-30R 执法腿）：\n- "
        + "\n- ".join(errors)
    )
    # 注毒自证：把一枚真在册键的默认改成非真值 ⇒ 本腿必须把它列入 unmatched、且不在 matched。
    probe_key = "bot_pipeline_max_workers"
    kind, real_default = defaults.get(probe_key, ("missing", None))
    assert kind == "literal" and real_default == 8, (
        f"注毒目标锚点变了：{probe_key} 期望 kind=literal、值=8，实得 {kind}={real_default!r}"
    )
    lines = text.splitlines()
    idx = next(
        (i for i, ln in enumerate(lines)
         if "BOT_PIPELINE_MAX_WORKERS" in ln and f"`{real_default}`" in ln),
        None,
    )
    assert idx is not None, "注毒点缺失：`BOT_PIPELINE_MAX_WORKERS` 行未找到 ⇒ 本腿可能空转"
    lines[idx] = lines[idx].replace(f"`{real_default}`", "`99991234`", 1)
    poisoned = "\n".join(lines)
    m2, u2 = _catalog_default_column_mismatches(poisoned, defaults)
    assert probe_key in u2 and probe_key not in m2, (
        "注毒自证失败：把 bot_pipeline_max_workers 默认改成 99991234，本腿必须把它列入 unmatched"
        f"（当前 in unmatched={probe_key in u2}、in matched={probe_key in m2}）"
    )


def test_config_catalog_registered_keys_are_live_or_marked_retired() -> None:
    """在册的 BOT_*/_xxx 键名：要么在 Config 类体存在，要么行文本明写「已退役/无字段/纯运行时」。

    拦的是 A-2 型假账——她照册在 `.env` 填一枚已退役的 `BOT_*` ⇒ pydantic `extra='ignore'`
    静默吞、连报错都没有；文档若把这枚写成「已登记 Config 字段」＝比过期更重的伪造归属。
    与 `test_config_catalog_covers_config_fields`（Config→catalog 单向覆盖）反向互补。
    """
    text = CONFIG_CATALOG_MD.read_text(encoding="utf-8")
    fields = _config_field_names()
    errors: list[str] = []
    seen: set[tuple[int, str]] = set()
    for r in _iter_catalog_registration_rows(text, need_default_col=False):
        for k in r["keys"]:
            if k in fields:
                continue
            if _RETIRED_MARKERS_RE.search(r["row_text"]):
                continue
            mark = (r["line"], k)
            if mark in seen:
                continue
            seen.add(mark)
            errors.append(
                f"docs/config-catalog-full.md:{r['line']} 键 `{k}` 在 Config 类体零命中，"
                f"行文本亦未明写「已退役/无字段/纯运行时」 ⇒ 她照此填 .env 会被 `extra='ignore'` 静默吞。"
            )
    assert not errors, (
        "catalog 在册键名与 config.py 字段面漂移（A 档「填了不生效、无失败信号」；M2-30R 执法腿）：\n- "
        + "\n- ".join(errors)
    )
    # 注毒自证：把 A1 表首行的键名换成一枚假键 ⇒ 本腿必须抓红。
    probe_line = "| `BOT_RUNTIME_DATA_DIR` |"
    idx = text.find(probe_line)
    assert idx > 0, "注毒点缺失：`BOT_RUNTIME_DATA_DIR` 未出现在 catalog 首表 ⇒ 本腿可能空转"
    line_end = text.find("\n", idx)
    poisoned = text[:idx] + "| `BOT_M2_30R_FAKE_KEY_NOT_A_REAL_FIELD` |" + text[idx + len(probe_line):line_end] + "\n" + text[line_end + 1:]
    fake = "bot_m2_30r_fake_key_not_a_real_field"
    assert fake not in fields, "注毒伪键意外与真字段撞名"
    fake_hit = False
    for r in _iter_catalog_registration_rows(poisoned, need_default_col=False):
        if fake in r["keys"] and not _RETIRED_MARKERS_RE.search(r["row_text"]):
            fake_hit = True
            break
    assert fake_hit, "注毒自证失败：伪键未落入'不在 Config + 未标退役'桶 ⇒ 判据空转"


# ==========================================================================
# 门禁 3（S246R 起、S246B 续）：生成链的「漏维 / 读空 / 手写计数」双向锁
# ==========================================================================
# 五条尺，各管一面、互不重叠（尺身份写在这里，防后来人把两把合成一把或都撤掉）：
#   尺① 维↔口：真身册声明的每一维，要么被某支取数口**真吃**（值级消费或名级投影），
#              要么落在 `NON_PROJECTED_DIMS` 里写明"为什么不进生成物"；两边都没有 ⇒ 红。
#              （新维无人吃 ⇒ 拦「在册未执法/未投影」；豁免过期 ⇒ 拦「登记不跟随」。）
#   尺② 塌陷锁只有一把：`doc_sync.require_surface` 全树唯一真身，且三支按路径读源的口
#              **逐支**经过它；A 腿查逐支过锁、B 腿查锁无第二真身、C 腿查名册条目不过期、
#              D 腿（S246B）按 AST 现算"静默口全集"⇒ 拦「长出新口而名册不知道」。
#   尺③ 机器册的维清单是 AST 派生：册里加一维，`build_document()` 那一行自动长出来（合成注毒实测）
#              ⇒ 拦「生成器把维名抄成一份名字表」这种必然过期的写法。
#   尺④ 生成器印出去的文案禁手写会过期的计数（S246B）：字面量里出现「数字+量词+空/填态」即红，
#              派生写法（f"{len(rows)} 枚"）不命中 ⇒ 拦「生成器自己造漂移、且生成物与源码同源自洽
#              所以没有任何门会红」这一类（AGENTS 规则 10 对生成器本体的延伸）。
#   尺⑤ 派生规则登记表 ↔ 真接线：`RULES` 里登记的规则必须真被 `project()` 用到、
#              用到的必须登记 ⇒ 拦「加一行登记就以为在投影」（空挂腿）与黑规则两个方向。
# 编号无缺档：①②③④⑤ 五条各一枚，新增尺请续号并同步本表。
# 与 `tests/test_capability_manifest_gate.py` 的「维↔值」地板（S242）是**两把不同的尺**：
# 那把量"每一维填了多少"，本门禁量"有没有人吃这一维、有没有人把它印出来"，互不代替。

#: 「不进生成物」登记册：维 → 理由。判据是**值形状**——值不指文件面的维，
#: 归属/命令/板块三类生成物都没有可投影的"面"，硬造一个投影口就是"声明消费而值全空"的假口。
#: 删维/改名必须同步本表（尺①的"过期豁免"腿会抓）；新维一旦变成路径值，
#: 自动被尺①的"路径维必须有人吃"腿追要认领（`arms.executor` 落真值就会咬到这里）。
NON_PROJECTED_DIMS: dict[str, str] = {
    "capability_id": "行身份本身：四支口都以它为键做聚合，不另设一份归属列（第二份 id 清单＝第二真身）",
    "tags": "内容形态档，值域来自 CapabilityTag（无文件面）；票根面由 M3 吃 EVIDENCE[*].evidence",
    "implementation_line": "行号随实现件每次编辑漂移是本维的代价；投影进文档＝把漂移变成常驻假红。"
                           "执法归 test_capability_manifest_gate 腿②d（每次跑都 AST 重定位）",
    "config_keys": "配置键不是文件面；其「处处跟随」落点是 docs/config-catalog-full.md，"
                   "由本件门禁 2 与 test_config_key_registration_ledger 执法",
    "arms": "臂形↔中央汇缝是执行形态、无文件面；缝字符串单源住 ARM_FORM_SEAMS，"
            "形集由腿㉓双向钉到两件入口活性件；其 executor 列一旦落真值即转为路径维、须被认领",
    "arms.arm_id": "派生身份串（<capability_id>:<entry_key>），不是事实源，不投影",
    "arms.entry_key": "臂形名 ∈ EntryKind 值域，无文件面",
    "arms.seam_host": "中央汇缝的**符号名**（非路径）；真身与等值由腿㉓执法，归属账无面可取",
    "arms.executor": "K-合成子边的 路径#符号——现算全空（0 枚合成臂），今天无面可投影；"
                     "落值即变路径维 ⇒ 本表若仍拒认领，尺①的「路径维必须有人吃」腿当场红",
}

#: 形如 `foo/bar.py`、`x.md`、`t.html` 的值 ⇒ 视为「可投影的面」。
_PATH_VALUE_RE = re.compile(r"[\w./-]*\.(?:py|md|html|json|ya?ml)\b")
_OWNERSHIP_PY = ROOT / "scripts" / "ownership_project.py"


def _declared_dims() -> list[str]:
    """在册维清单（唯一尺＝`doc_sync.manifest_facet_dims` 的 AST 派生，含臂列）。"""
    return ds.manifest_facet_dims()


def _arm_column_names() -> set[str]:
    return {d.split(".", 1)[1] for d in _declared_dims() if "." in d}


def _mouth_dim_claims(path: Path) -> tuple[set[str], set[str]]:
    """一支取数口的两本账：`eaten`（代码真去取值）与 `rules`（登记表点名认领）。

    为什么要分两本：`eaten` 从属性/`getattr`/下标名派生，抓的是"真读了这个字段"
    （M4 走这本）；`rules` 从 `RULES` 文案里的 `FACETS[*].<维>` 派生，抓的是"认领了这一维"
    （S1 认领 `direct_callsites` 走这本——它吃的是普查产物、不直接读册字段，
    但认领必须可查，否则"谁吃这一维"又变成散文）。
    两本都只与在册维名比对后才入账 ⇒ 属性名里的噪声（`.get`/`.value`）不会污染判据；
    而 `rules` 那一本刻意**不**过滤，它就是用来抓"认领过期"的。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    declared = set(_declared_dims())
    arm_cols = _arm_column_names()
    eaten: set[str] = set()
    for node in ast.walk(tree):
        found: list[str] = []
        if isinstance(node, ast.Attribute):
            found.append(node.attr)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)):
            found.append(node.args[1].value)
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            found.append(node.slice.value)
        for name in found:
            if name in declared:
                eaten.add(name)
            if name in arm_cols:
                eaten.add(f"arms.{name}")
    rules = {m for m in re.findall(r"FACETS\[\*\]\.([a-z_]+)", "\n".join(op.RULES.values()))
             if m in declared or m == "direct_callsites"}
    return eaten, rules


def _path_bearing_dims(facets: dict[str, Any]) -> set[str]:
    """现算：哪些维的**在册值里含文件面**（含臂的嵌套列）——只有这些维欠投影。"""
    out: set[str] = set()
    for row in facets.values():
        for dim in _declared_dims():
            if "." in dim:  # 臂列由 arms 那一次遍历精确点名
                continue
            value = getattr(row, dim, None)
            if dim == "arms":
                for arm in value or ():
                    if _PATH_VALUE_RE.search(str(arm.seam_host or "")):
                        out.add("arms.seam_host")
                    if _PATH_VALUE_RE.search(str(arm.executor or "")):
                        out.add("arms.executor")
                continue
            cells = list(value) if isinstance(value, (tuple, list)) else [value]
            if any(isinstance(c, str) and _PATH_VALUE_RE.search(c) for c in cells):
                out.add(dim)
    return out


def projection_gap_violations(
    declared: list[str], eaten: set[str], rules: set[str], exempt: dict[str, str], path_dims: set[str]
) -> list[str]:
    """纯谓词：维↔口的账分开红（少一腿就是假绿，故逐方向各自点名）。"""
    claimed = eaten | rules
    problems: list[str] = []
    unclaimed = [d for d in declared if d not in claimed and d not in exempt]
    if unclaimed:
        problems.append(f"在册维无人吃、也未登记不投影的理由（新维必须二选一）：{unclaimed}")
    stale_exempt = sorted(d for d in exempt if d not in declared)
    if stale_exempt:
        problems.append(f"不投影登记里有过期条目（册维已不存在，须摘除）：{stale_exempt}")
    blank = sorted(d for d, why in exempt.items() if not str(why).strip())
    if blank:
        problems.append(f"不投影登记缺理由（空理由＝没有豁免）：{blank}")
    orphan_path = sorted(d for d in path_dims if d not in claimed)
    if orphan_path:
        problems.append(f"含文件面的维无人投影（归属账永远看不见这些面）：{orphan_path}")
    stale_claims = sorted(d for d in rules if d not in declared)
    if stale_claims:
        problems.append(f"取数口登记表声称吃册里已不存在的维（认领不跟随）：{stale_claims}")
    return problems


# ---------------------------------------------------------- 尺①：维↔口 双向账
def test_manifest_dims_are_all_claimed_by_a_mouth_or_exempt() -> None:
    """真账过门：在册每一维要么被口吃/登记认领，要么写明不投影的理由；路径维必须有认领。"""
    facets = op.load_manifest(op.MANIFEST_PY)["FACETS"]
    declared = _declared_dims()
    eaten, rules = _mouth_dim_claims(_OWNERSHIP_PY)
    problems = projection_gap_violations(declared, eaten, rules, NON_PROJECTED_DIMS, _path_bearing_dims(facets))
    assert not problems, "生成链维↔口漂移：\n- " + "\n- ".join(problems)
    # 正例自证：本腿不是"恒空"空转——implementation_ref 与 direct_callsites 今天**必须**被认下
    # （一支靠 M4 真读字段、一支靠 S1 登记认领），少了任何一支都该有红可谈。
    assert "implementation_ref" in eaten, "M4 没落到字段读取上＝册侧镜像仍无人吃"
    assert "direct_callsites" in rules, "S1 不再点名 direct_callsites＝该维回到无人认领"


def test_new_manifest_dim_without_claim_or_exempt_is_red() -> None:
    """注毒①：册里凭空多一维、既无人吃也无人登记 ⇒ 必红（拦"加列不跟随"）。"""
    declared = [*_declared_dims(), "s246r_probe_dim"]
    eaten, rules = _mouth_dim_claims(_OWNERSHIP_PY)
    problems = projection_gap_violations(declared, eaten, rules, NON_PROJECTED_DIMS, set())
    assert problems and any("s246r_probe_dim" in p for p in problems), problems


def test_path_bearing_arm_executor_without_a_claim_is_red() -> None:
    """注毒②：`arms.executor` 一落真值（K-合成子边）而无人认领 ⇒ 必红。

    这条腿的意义＝**豁免不许过期**：今天 executor 全空，"不投影"成立；
    哪天合成臂落了 `路径#符号`，本尺就追着一支口来认领它，而不是让归属账继续瞎着。
    """
    declared = _declared_dims()
    eaten, rules = _mouth_dim_claims(_OWNERSHIP_PY)
    problems = projection_gap_violations(
        declared, eaten, rules, NON_PROJECTED_DIMS, {"arms.executor"})
    assert problems and any("arms.executor" in p for p in problems), problems


def test_stale_claim_and_stale_exempt_are_red() -> None:
    """注毒③＋④：认领侧与豁免侧都双向核（登记吃不存在的维 ⇒ 红；豁免条目过期 ⇒ 红）。"""
    declared = _declared_dims()
    problems = projection_gap_violations(declared, set(), {"s246r_ghost_dim"}, NON_PROJECTED_DIMS, set())
    assert any("s246r_ghost_dim" in p for p in problems), problems
    stale_exempt = dict(NON_PROJECTED_DIMS)
    stale_exempt["s246r_vanished_dim"] = "本维已被摘，豁免却留着"
    problems = projection_gap_violations(declared, {"trigger_source"}, set(), stale_exempt, set())
    assert any("s246r_vanished_dim" in p for p in problems), problems


# ---------------------------------------------------------- 尺②：塌陷锁唯一真身
def _call_names(path: Path) -> tuple[set[str], int]:
    """一件脚本里「被调用的函数名」（裸名 + `mod.fn` 的尾名）与 `require_surface` 的定义数。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    callees: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            callees.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            callees.add(node.func.attr)  # 经 `ds.require_surface(...)` 兄弟件调用的也算
    definitions = sum(
        1 for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "require_surface")
    return callees, definitions


def _functions_calling(path: Path, callee: str) -> set[str]:
    """本件里**调用了** `callee` 的顶层函数名（逐函数体判，不按整件计数）。

    为什么必须逐函数判：只数"整件里有没有一处调用"＝一支口加了锁、其余几支回退掉也照样绿
    （本席 M3 注毒实测正是这样混过去的，见 SEAT-S246 §7）。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    guarded: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and (
                    (isinstance(sub.func, ast.Name) and sub.func.id == callee)
                    or (isinstance(sub.func, ast.Attribute) and sub.func.attr == callee)):
                guarded.add(node.name)
                break
    return guarded


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


def _ports_of_build_document(path: Path) -> set[str]:
    """`build_document()` 直接调用的自有取数函数。

    `manifest_facts_lines` 除外——它自带「缺件≠零枚」的显式分支，且内部逐支过锁。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "build_document":
            called = {
                sub.func.id for sub in ast.walk(node)
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
            }
            return {n for n in called & defined if n != "manifest_facts_lines"}
    raise AssertionError("doc_sync.build_document 找不到——本门的判据宿主变了")


#: `command_catalog` 里"读空不抛、只回空值"的三支口（其余口走 `_literal_assign`，
#: 找不到赋值当场抛，本来就响亮）。新长出来的静默回空头必须补进本名册——
#: 尺②的 C 腿双向核"名册条目仍是真函数名"，过期与漏登记各有各的红。
#:
#: S246B 追加两支：`_route_kind_values` / `_route_kind_member_values` 是 AST 遍历口，
#: 旧写法读空回 `[]`/`{}` 且体内无 raise ⇒ 既不在名册、也没过锁，是"C 腿只查名册条目、
#: 不知道有新口长出来"这一洞的实证（尺②的 D 腿现在按 AST 现算全集来要账）。
CATALOG_SILENT_PORTS: tuple[str, ...] = (
    "_manifest_entries", "_route_capabilities", "_alias_capability_ids",
    "_route_kind_values", "_route_kind_member_values")


def _declaration_source_consts(path: Path) -> set[str]:
    """本件里模块级的声明源路径常量名（`*_SOURCE` / `*_PY` 赋值）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        t.id for n in tree.body if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name) and t.id.endswith(("_SOURCE", "_PY"))
    }


def _silent_ports_by_derivation(path: Path) -> set[str]:
    """AST 现算：引用了声明源常量、且**体内一次 raise 都没有**的顶层函数＝静默回空头。

    为什么必须有这条派生腿：名册是手写的，"漏登记一支新长出来的静默口"时逐支查名册的判据
    **根本不知道它存在**（不点名 ⇒ 恒绿）。本腿只加不减——名册继续承担"逐支查锁"的清单，
    本腿负责追问"清单是不是全集"。判据本身只依赖语法形状（引用源常量 + 无 raise），
    不认函数名 ⇒ 改名躲不过。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    consts = _declaration_source_consts(path)
    out: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}
        if not names & consts:
            continue
        if any(isinstance(s, ast.Raise) for s in ast.walk(node)):
            continue  # 体内自带响亮失败，不属静默口
        out.add(node.name)
    return out


def _collapse_lock_problems(doc_py: Path, board_py: Path, catalog_py: Path) -> list[str]:
    """纯判据：三支生成器里**每一支**会静默回空的取数口是否都经过唯一塌陷锁。

    参数化成路径＝能被 `tmp_path` 的**副本**喂：杀伤力自证因此不必改源码树
    （本窗实测教训——注毒台在真件上改文件、还原之前会被并发会话的 autosync 抓走
    并把注毒态写进生成物，见 SEAT-S246 §7 的自曝账）。
    """
    problems: list[str] = []
    guarded_doc = _functions_calling(doc_py, "require_surface")
    for port in sorted(_ports_of_build_document(doc_py)):
        if port not in guarded_doc:
            problems.append(f"doc_sync.{port} 未经过唯一塌陷锁")
    guarded_board = _functions_calling(board_py, "require_surface")
    for port in sorted(n for n in _top_level_functions(board_py) if n.startswith("load_")):
        if port not in guarded_board:
            problems.append(f"board_doc_sync.{port} 未经过唯一塌陷锁")
    guarded_catalog = _functions_calling(catalog_py, "require_surface")
    catalog_defined = _top_level_functions(catalog_py)
    for port in CATALOG_SILENT_PORTS:
        if port not in catalog_defined:
            problems.append(f"command_catalog.{port} 已不在盘上（名册条目过期，须摘除）")
        elif port not in guarded_catalog:
            problems.append(f"command_catalog.{port} 未经过唯一塌陷锁")
    # D 腿（S246B 补）：名册必须是"静默口全集"——按 AST 现算全集再要账，
    # 只加不减（不缩扫描面：名册逐支查锁的判据一字未动）。
    unregistered = sorted(_silent_ports_by_derivation(catalog_py) - set(CATALOG_SILENT_PORTS))
    if unregistered:
        problems.append(
            f"command_catalog 长出静默回空的取数口却没进名册（新口必须同批登记并过锁）：{unregistered}")
    return problems


def test_collapse_lock_has_a_single_home_and_every_port_is_locked() -> None:
    """塌陷锁：①全树只许一枚定义 ②每一支会静默回空的取数口**逐支**经过它。

    为什么用 AST 而不是 grep：grep 会被注释与字符串骗过（TX241 同款判据——
    "以 AST 现算钉住"，不是串比）。
    """
    scripts = sorted((ROOT / "scripts").glob("*.py"))
    homes = [s.name for s in scripts if _call_names(s)[1]]
    assert homes == ["doc_sync.py"], f"塌陷锁出现第二真身：{homes}"

    doc_py = ROOT / "scripts" / "doc_sync.py"
    board_py = ROOT / "scripts" / "board_doc_sync.py"
    catalog_py = ROOT / "scripts" / "command_catalog.py"
    problems = _collapse_lock_problems(doc_py, board_py, catalog_py)
    assert not problems, "取数口的塌陷锁不跟随：\n- " + "\n- ".join(problems)
    assert "require_surface" in _call_names(doc_py)[0], "doc_sync 定义了锁自己却不吃＝锁不存在"


#: 逐支剥锁的注毒配方：件 → (锚点原文, 剥掉锁之后的写法)。
#: 锚点全部现算取自真件，锚点不在场即当场 `assert` 红——防"注毒针扎空却报成有牙"。
_STRIP_RECIPES: dict[str, tuple[str, str]] = {
    "doc_sync.py": (
        '''    return require_surface(
        "RouteKind 取数口",
        re.findall(r"^    ([A-Z_]+) = ", block.group(1), re.MULTILINE),
        BASE_ROUTER_PY,
        ("RouteKind",),
    )''',
        '''    return re.findall(r"^    ([A-Z_]+) = ", block.group(1), re.MULTILINE)'''),
    "board_doc_sync.py": (
        'return ds.require_surface("板块树取数口 load_taxonomy", boards, TAXONOMY_PY, ("BOARD_TAXONOMY",))',
        "return boards"),
    "command_catalog.py": (
        'return ds.require_surface("接口清单取数口 _manifest_entries", out, ROUTER_SOURCE, ("InterfaceEntry",))',
        "return out"),
}


@pytest.mark.parametrize("victim", sorted(_STRIP_RECIPES))
def test_collapse_lock_leg_has_teeth_on_stripped_copies(tmp_path: Path, victim: str) -> None:
    """杀伤力自证（零盘上改动）：把**副本**里某一支口的锁剥掉 ⇒ 本腿当场点名的正是那一支。

    报不出＝本腿空跑假绿；报错了对象＝判据不按支核算（整件计数那种糊法，
    本席 M3 注毒实测混走过一次，见 SEAT-S246 §7）。
    """
    anchor, stripped = _STRIP_RECIPES[victim]
    real = (ROOT / "scripts" / victim).read_text(encoding="utf-8")
    assert anchor in real, f"注毒锚点已失效（{victim} 写法变了）——本用例必须先跟随"
    copy = tmp_path / f"stripped_{victim.replace('.', '_')}"
    copy.write_text(real.replace(anchor, stripped, 1), encoding="utf-8")
    paths = {name: (copy if name == victim else ROOT / "scripts" / name)
             for name in ("doc_sync.py", "board_doc_sync.py", "command_catalog.py")}
    problems = _collapse_lock_problems(paths["doc_sync.py"], paths["board_doc_sync.py"],
                                       paths["command_catalog.py"])
    assert len(problems) == 1, f"剥一支锁应恰报一支，实报：{problems}"
    assert victim.replace(".py", "") in problems[0], problems


# ------------------------------------------- 尺⑤：派生规则登记表 ↔ 真接线（防空挂规则）
def _rule_ids_used_in_project(path: Path) -> set[str]:
    """`project()` 里出现过的规则名字面量（`p.add(..., "M1", ...)` 与 `"M1" in rules_on` 两形）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "project"), None)
    assert fn is not None, "ownership_project.project 找不到——本门的判据宿主变了"
    return {
        node.value for node in ast.walk(fn)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and re.fullmatch(r"[A-Z]\d[a-z]?", node.value)
    }


def rule_liveness_violations(registered: set[str], used: set[str]) -> list[str]:
    """纯谓词：登记了却没接线（空挂规则）／接了线却没登记（黑规则），两本账分开红。"""
    problems: list[str] = []
    dead = sorted(registered - used)
    if dead:
        problems.append(f"派生规则登记在册却从未被 project() 使用（空挂腿）：{dead}")
    undeclared = sorted(used - registered)
    if undeclared:
        problems.append(f"project() 在跑却没登记规则语义（黑规则）：{undeclared}")
    return problems


def test_ownership_rules_are_wired_both_directions() -> None:
    """真账过门 + 注毒：M4 这类「加了登记不接线」与「接了线不登记」都当场红。"""
    registered, used = set(op.RULES), _rule_ids_used_in_project(_OWNERSHIP_PY)
    assert not rule_liveness_violations(registered, used), \
        "归属投影规则空挂：\n- " + "\n".join(rule_liveness_violations(registered, used))
    assert "M4" in used, "M4 没接到 project() 上＝册侧镜像仍无人投影"
    problems = rule_liveness_violations(registered | {"M9"}, used)
    assert any("M9" in p for p in problems), problems           # 注毒⑤a：只登记不接线
    problems = rule_liveness_violations(registered - {"M4"}, used)
    assert any("M4" in p for p in problems), problems           # 注毒⑤b：只接线不登记


def _run_board_load_taxonomy() -> object:
    return _bds().load_taxonomy()


@pytest.mark.parametrize(
    "module_attr,needed,runner",
    [
        ("doc_sync", "_HELP_ENTRIES", lambda: ds._help_topics()),
        ("board_doc_sync", "BOARD_TAXONOMY", _run_board_load_taxonomy),
        ("command_catalog", "InterfaceEntry", lambda: cc._manifest_entries()),
    ],
    ids=["doc_sync/echo", "board_doc_sync/taxonomy", "command_catalog/base_router"],
)
def test_reexport_shell_declaration_source_raises_not_empty(
    module_attr: str, needed: str, runner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """声明源降成**再导出壳** ⇒ 该口必抛并点名"壳"，绝不返回空表（三腿锁的第③腿）。

    本仓归位家规＝"旧路径留再导出垫片"（v21r2 已这么退役 `capabilities/`、`output/card_render/`），
    而 AST/正则读取口对壳一律解析不出条目——旧写法把这件事表现成
    「机器册记 0」「板块生成页被清空」「命令目录少一整段」，全都静默。
    """
    shell = tmp_path / f"{module_attr}_shell.py"
    shell.write_text(
        f'"""合成壳：真身搬家后旧路径的形态。"""\nfrom .real import {needed} as {needed}\n',
        encoding="utf-8")
    path_const = {
        "doc_sync": (ds, "ECHO_PY"),
        "board_doc_sync": (_bds(), "TAXONOMY_PY"),
        "command_catalog": (cc, "ROUTER_SOURCE"),
    }[module_attr]
    monkeypatch.setattr(path_const[0], path_const[1], shell)
    with pytest.raises(ds.DeclarationBlind, match="再导出壳"):
        runner()


def test_real_declaration_sources_are_readable_by_every_port() -> None:
    """三腿锁的第①腿（正例）：真树四支口都读得出东西（地板只锁"非空"，不写死枚数）。"""
    assert ds._tpl_list() and ds._route_kinds() and ds._help_topics()
    assert ds._test_file_count() and ds._config_key_count() and ds._tracked_files()
    bds = _bds()
    assert bds.load_taxonomy() and bds.load_route_index() and bds.load_help_topics()
    assert bds.load_route_kind_members() and bds.load_config_fields()
    assert cc._manifest_entries() and cc._route_capabilities() and cc._alias_capability_ids()
    assert ds.manifest_facet_rows() and ds.manifest_facet_dims()


# ---------------------------------------------------------- 尺③：机器册随维生长
def test_machine_ledger_grows_with_a_new_manifest_dim(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """册里加一维 ⇒ 机器册那一行自动长出来（注毒实测，证"派生"不是"抄名单"）。

    注入点在 `tmp_path` 的合成册件上，**绝不改真身**；两向都断：
    ①合成新维出现在派生清单与生成正文里；②真树生成正文逐字含 AST 派生的每一维名。
    """
    synthetic = tmp_path / "capability_manifest_synth.py"
    synthetic.write_text(
        '"""合成册：只给派生用，不被 import。"""\n'
        "from dataclasses import dataclass\n\n\n"
        "@dataclass(frozen=True)\nclass CapabilityFacets:\n"
        "    capability_id: str\n    board: str\n    s246r_probe_dim: str\n\n\n"
        "@dataclass(frozen=True)\nclass CapabilityArm:\n"
        "    arm_id: str\n    executor: str\n\n\n"
        "def _f(capability_id):\n    return None\n\n\n"
        "FACETS = {'bot.probe': _f('bot.probe')}\n",
        encoding="utf-8")
    dims = ds.manifest_facet_dims(synthetic)
    assert "s246r_probe_dim" in dims, f"合成新维没被派生看见：{dims}"
    assert ds.manifest_facet_rows(synthetic) == 1
    monkeypatch.setattr(ds, "MANIFEST_PY", synthetic)
    assert "s246r_probe_dim" in ds.build_document(), "生成器把维名抄成了固定名单（新维不跟随）"

    monkeypatch.undo()
    real_line = next(
        line for line in ds.build_document().splitlines() if line.startswith("- 能力真身册维清单"))
    for dim in ds.manifest_facet_dims():
        assert dim in real_line, f"真册的维 {dim} 没进机器册那一行"


# ---------------------------------- 尺②的 D 腿补丁：名册必须是"静默口全集"（S246B 补）
#: 逐支剥锁的第二批配方：标签 → (受害件, 锚点原文, 剥掉锁之后的写法)。
#: 为什么不塞进 `_STRIP_RECIPES`：那张表按**文件名**取键，一支文件只能放一发毒，
#: 而 `command_catalog` 现在有三支静默口要逐支验牙（一张表放两发会互相顶掉锚点）。
#: 本批只加不减：原表三条配方一字未动。
_STRIP_RECIPES_2: dict[str, tuple[str, str, str]] = {
    "command_catalog._route_kind_values": (
        "command_catalog.py",
        '''    return ds.require_surface(
        "路由 kind 取值取数口 _route_kind_values", values, ROUTER_SOURCE, ("RouteKind",))''',
        "    return values"),
    "command_catalog._route_kind_member_values": (
        "command_catalog.py",
        '''    return ds.require_surface(
        "路由 kind 成员表取数口 _route_kind_member_values", pairs, ROUTER_SOURCE, ("RouteKind",))''',
        "    return pairs"),
}


@pytest.mark.parametrize("label", sorted(_STRIP_RECIPES_2))
def test_strip_recipes_extra_pierce_the_named_port(label: str, tmp_path: Path) -> None:
    """杀伤力自证第二批（零盘上改动）：在**副本**上剥某一支口的锁 ⇒ 恰点名那一支。"""
    victim, anchor, stripped = _STRIP_RECIPES_2[label]
    real = (ROOT / "scripts" / victim).read_text(encoding="utf-8")
    assert anchor in real, f"注毒锚点已失效（{label} 的写法变了）——本用例必须先跟随"
    copy = tmp_path / f"stripped2_{label.replace('.', '_')}"
    copy.write_text(real.replace(anchor, stripped, 1), encoding="utf-8")
    paths = {name: (copy if name == victim else ROOT / "scripts" / name)
             for name in ("doc_sync.py", "board_doc_sync.py", "command_catalog.py")}
    problems = _collapse_lock_problems(paths["doc_sync.py"], paths["board_doc_sync.py"],
                                       paths["command_catalog.py"])
    assert len(problems) == 1, f"剥一支锁应恰报一支，实报：{problems}"
    port = label.rsplit(".", 1)[1]
    assert port in problems[0], problems


def test_route_kind_ports_raise_when_declaration_source_goes_blind(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """活性正证：把 `ROUTER_SOURCE` 换成"没有 RouteKind 类"的合成件 ⇒ 两支 kind 口当场抛。

    为什么不只靠上面的副本判据：尺②的腿量的是"代码里有没有那行锁"，
    本条量的是"锁真咬人"——合成声明源里没有 `class RouteKind`，
    旧写法回 `[]`/`{}`（且调用方 `test_route_matrix_covers_every_route_kind` 的推导式
    对空表恒不报缺 ⇒ 假绿），现写法必须抛 `DeclarationBlind`。
    """
    blind = tmp_path / "base_router_blind.py"
    blind.write_text('"""合成件：RouteKind 搬走后的旧路径形态。"""\nX = 1\n', encoding="utf-8")
    monkeypatch.setattr(cc, "ROUTER_SOURCE", blind)
    with pytest.raises(ds.DeclarationBlind, match="RouteKind"):
        cc._route_kind_values()
    with pytest.raises(ds.DeclarationBlind, match="RouteKind"):
        cc._route_kind_member_values()


def test_route_capabilities_refuses_to_invent_a_kind(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """被删掉的 `.lower()` 兜底：换成"引用一枚成员表里没有的 kind"的合成声明源 ⇒ 必抛。

    旧写法在这里会**造出** `("b", "bot.b")` 并一路印进命令目录——而现网 35/35 枚成员的
    取值恰等于名小写（`probes/s246b-probe3.py` 现算），所以那次造值和真值逐字相同，
    上游怎么塌都不会改变生成物字节 ⇒ 塌陷完全隐形。本用例钉的就是"以后不再靠巧合"。
    """
    synth = tmp_path / "base_router_partial.py"
    synth.write_text(
        '"""合成件：成员表只认 A，路由表却引用 B——兜底一旦在场就静默造出 b。"""\n'
        "class RouteKind:\n    A = \"a\"\n\n\n"
        "def build_route_rules():\n"
        "    return [RouteRule(RouteKind.A, \"bot.a\"), RouteRule(RouteKind.B, \"bot.b\")]\n",
        encoding="utf-8")
    monkeypatch.setattr(cc, "ROUTER_SOURCE", synth)
    assert cc._route_kind_member_values() == {"A": "a"}          # 成员表非空 ⇒ 锁不响，轮到兜底该响
    with pytest.raises(ValueError, match="RouteKind.B"):
        cc._route_capabilities()


def test_catalog_silent_roster_is_derived_not_hand_shrunk() -> None:
    """D 腿的正例自证：现算全集 ⊆ 名册，且名册里每一支都真在盘上、真过锁。

    这条同时是"禁缩扫描面"的自证：名册若被人为删一行，本用例的红来自派生集与名册的差，
    而不是来自任何写死的枚数——想让它变绿只有"把锁补上"一条路，没有"把面缩小"一条路。
    """
    derived = _silent_ports_by_derivation(ROOT / "scripts" / "command_catalog.py")
    assert derived <= set(CATALOG_SILENT_PORTS), f"静默口漏登记：{sorted(derived - set(CATALOG_SILENT_PORTS))}"
    defined = _top_level_functions(ROOT / "scripts" / "command_catalog.py")
    assert set(CATALOG_SILENT_PORTS) <= defined, "名册里有条目已不在盘上（须摘除而不是删腿）"

    guarded = _functions_calling(ROOT / "scripts" / "command_catalog.py", "require_surface")
    assert set(CATALOG_SILENT_PORTS) <= guarded, "名册条目没过唯一塌陷锁"
    # 现算读数（只用作下限自证，不写死枚数）：两支 kind 口是 S246B 追加的，缺任一 ⇒ 本腿瞎
    assert {"_route_kind_values", "_route_kind_member_values"} <= derived


def test_derivation_leg_sees_a_new_silent_port(tmp_path: Path) -> None:
    """注毒（D 腿自己的牙）：副本里长出一支"读静默回空的新口"⇒ 现算全集认出它、
    `_collapse_lock_problems` 当场报"没进名册"。

    这条用例存在的全部理由＝旧判据看不见没登记的新口：名册手抄 ⇒ 加一支新口而不改名册，
    逐支查名册的腿永远数不到它（恒绿）。这里**不碰真树**，只在 tmp_path 的副本上验，
    还原问题天然不存在。
    """
    real = (ROOT / "scripts" / "command_catalog.py").read_text(encoding="utf-8")
    grown = real + '''

def _s246b_probe_new_silent_port() -> list[str]:
    """合成口：引用声明源却一次都不抛 ⇒ 读空即静默。"""
    found: list[str] = []
    for node in ast.walk(_module_tree(ROUTER_SOURCE)):
        if isinstance(node, ast.ClassDef):
            found.append(node.name)
    return found
'''
    copy = tmp_path / "command_catalog_grown.py"
    copy.write_text(grown, encoding="utf-8")
    derived = _silent_ports_by_derivation(copy)
    assert "_s246b_probe_new_silent_port" in derived, f"派生腿没认出新长的静默口：{sorted(derived)}"
    problems = _collapse_lock_problems(
        ROOT / "scripts" / "doc_sync.py", ROOT / "scripts" / "board_doc_sync.py", copy)
    assert any("_s246b_probe_new_silent_port" in p for p in problems), problems


# ---------------------------------------------------------- 尺④：生成器文案禁手写过期计数（S246B）
# 为什么单独一条尺：AGENTS 规则 10 管的是"叙述文档"，而**生成器印出去的文案就是文档的源头**——
# `ownership_project.py` 曾把「board 指针 13 行全空」写进 `RULES`/`WHY_NO_BOARD` 两处字面量，
# board 维填满后那句话变成打进人读生成件的假话，且**没有任何门会红**（生成物与源码同源自洽）。
# 本尺拦的是形态而非取值：字面量里出现「数字 + 量词 + 空/填态」＝手写计数。
# 派生写法（`f"{len(rows)} 枚…"`）天然不命中，因此本尺不逼生成器"干脆别印枚数"。

#: 五件生成器（本波写面）。第五件＝板块归属的读侧真身 `physical_placement_census.py`
#: ——简报里写作 `board_placement`，盘上真身名以此处现算为准。
GENERATOR_SCRIPTS: tuple[str, ...] = (
    "doc_sync.py", "board_doc_sync.py", "command_catalog.py",
    "ownership_project.py", "physical_placement_census.py")

#: 手写过期计数形态：数字 + 量词 + 填充态词。
_VOLATILE_COUNT_RE = re.compile(r"\d+\s*(?:行|枚|个|条|项)\s*(?:全空|已填|填满|未填|为空)")


def _hand_written_count_hits(path: Path) -> list[tuple[int, str]]:
    """纯判据：一件生成器的**字符串常量**里出现手写计数形态 ⇒ 逐处点名（行号 + 片段）。

    只看字符串常量、不看注释：执法对象是"会被印进生成物的字节"，注释不进生成物。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and _VOLATILE_COUNT_RE.search(node.value)):
            hits.append((getattr(node, "lineno", 0), node.value[:80]))
    return hits


def test_generators_emit_no_hand_written_volatile_counts() -> None:
    """真账过门：五件生成器印出去的文案里，一处手写过期计数都不许有。"""
    offenders = [
        f"{name}:{line} {snippet!r}"
        for name in GENERATOR_SCRIPTS
        for line, snippet in _hand_written_count_hits(ROOT / "scripts" / name)]
    assert not offenders, "生成器把会过期的计数写进了字面量（改现算派生，或指向 §4 现算读数）：\n- " \
        + "\n- ".join(offenders)


def test_volatile_count_leg_has_teeth(tmp_path: Path) -> None:
    """注毒自证（零盘上改动）：该命中的必命中、派生写法的不得命中。

    反例那三形＝"生成器确实可以印枚数，只要它是现算的"——本尺不许把"删掉枚数"当修法。
    """
    bad = tmp_path / "bad_generator.py"
    bad.write_text(
        '"""合成件：只给判据吃，不被 import。"""\n'
        'RULE = "board 指针 13 行全空"\n'
        'NOTE = "board 20 枚已填满（本波现算）"\n',
        encoding="utf-8")
    hits = _hand_written_count_hits(bad)
    assert len(hits) == 2, f"手写计数形态没被抓全：{hits}"

    good = tmp_path / "good_generator.py"
    good.write_text(
        '"""合成件：现算派生形态，不得命中。"""\n'
        'rows = [1, 2, 3]\n'
        'RULE = f"board 为空的行共 {len(rows)} 枚（枚数看 §4 现算读数）"\n'
        'NOTE = "board 为空的行 ⇒ 只进 unattributed，不发明归属"\n',
        encoding="utf-8")
    assert _hand_written_count_hits(good) == [], "派生写法被误伤 ⇒ 本尺会把人逼成'干脆别印枚数'"


# ------------------------------------------------- 尺⑦：「测试文件数」只认在册（tracked）口径
# 2026-10-08 裁定：未跟踪测试文件不入库 ⇒ 机器册不许替它们背书。旧取数口
# `len(TESTS_DIR.glob("test_*.py"))` 是**文件系统**口径：谁在飞新建一枚未跟踪测试件，
# 那一格当场 +1（实测 1072 → 1074，肇事件 `test_consent_apply_receipt_honesty.py`／
# `test_side_leg_timeout_floor.py` 都不是主会话造的）⇒ 册子在替"干净 checkout 上不存在"
# 的状态签字，是假绿的一型（`P-MAIN-8` 早记过同型账）。本尺四腿：
# ① 那一格 == `git ls-files` 现算的在册枚数（独立尺，不拿被锁的口自证）；
# ② 未跟踪件在场 ⇒ 那一格纹丝不动（真树只读 + 合成树两形）；
# ③ git 轴取不到 ⇒ 印 `NO_GIT_AXIS` 并明写原因，**既不折 0 也不折在盘 glob 的数**；
# ④ 口径锚（AST）：`_test_file_count` 必须调在册取数口、体内不得再出现 `glob`。

#: 在册/在盘两轴共用的形状尺：`tests/` 顶层的 `test_*.py`（与旧 glob 同形状，只换背书口径）。
_TEST_NAME_RE = re.compile(r"tests/test_[^/]*\.py")


def _git_read_only(argv: list[str]) -> str:
    """git **只读**命令（本尺唯一 git 出口）：rc!=0 一律响亮红，不折成"没有"。"""
    import subprocess

    proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, timeout=120, check=False)
    assert proc.returncode == 0, (
        f"`{' '.join(argv)}` 取不到（rc={proc.returncode}）："
        f"{proc.stderr[:200]!r}——本尺拒绝把「问不到」读成「零枚」，选择当场红")
    return proc.stdout.decode("utf-8", "replace")


def _shell_tracked_test_paths() -> list[str]:
    """独立尺：`git ls-files -z -- tests` 里的在册测试件（posix、升序）。

    配方抄 `scripts/secret_scan_tracked.py::_run_git_tracked` 那一族：`-z` 免八进制转义、
    bytes 手解码不吃 locale。🔴 禁 `git status` 全量扫、禁任何 git 写操作。
    """
    names = [seg.replace("\\", "/") for seg in _git_read_only(
        ["git", "ls-files", "-z", "--", "tests"]).split("\0") if seg]
    return sorted(n for n in names if _TEST_NAME_RE.fullmatch(n))


def _shell_untracked_test_paths() -> list[str]:
    """独立尺：在盘未跟踪（且未被 .gitignore 排除）的测试件——正是旧口径多吃的那批。"""
    names = [seg.replace("\\", "/") for seg in _git_read_only(
        ["git", "ls-files", "--others", "--exclude-standard", "-z", "--",
         "tests"]).split("\0") if seg]
    return sorted(n for n in names if _TEST_NAME_RE.fullmatch(n))


def _disk_test_paths() -> list[str]:
    """在盘（文件系统）口径：旧写法数的那个集合，本尺拿它当"应当比在册多"的对照。"""
    return sorted(f"tests/{p.name}" for p in (ROOT / "tests").glob("test_*.py"))


def _fake_inflight_tree(tmp_path: Path, tracked_names: list[str], extra_untracked: int,
                        monkeypatch: pytest.MonkeyPatch) -> Path:
    """合成树：git 轴给 `tracked_names`、磁盘轴给「在册 + extra」枚 ⇒ 两轴**故意不等**。

    为什么必须合成而不是在真 `tests/` 里造一枚再删：并发窗里别人正在收集 `tests/`，
    多出来的探针件会被别席的 pytest 当场收走（本仓在飞窗踩过）；注毒一律内存／tmp_path。
    """
    import subprocess
    from types import SimpleNamespace

    disk = tmp_path / "tests"
    disk.mkdir(parents=True, exist_ok=True)
    for i in range(len(tracked_names) + extra_untracked):
        (disk / f"test_synth_{i}.py").write_text('"""合成件：只给判据吃，不被 import。"""\n',
                                                 encoding="utf-8")
    monkeypatch.setattr(ds, "TESTS_DIR", disk)
    payload = b"".join(f"{name}\0".encode() for name in tracked_names)
    monkeypatch.setattr(ds, "subprocess", SimpleNamespace(
        run=lambda *a, **k: SimpleNamespace(returncode=0, stdout=payload, stderr=b""),
        SubprocessError=subprocess.SubprocessError))
    return disk


def _callees_of_test_file_count() -> set[str]:
    """AST 现算：`doc_sync._test_file_count` 体内调到的名字（函数名 + 属性名两形）。"""
    tree = ast.parse((ROOT / "scripts" / "doc_sync.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_test_file_count":
            out: set[str] = set()
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call) or not isinstance(sub.func, (ast.Name, ast.Attribute)):
                    continue
                out.add(sub.func.id if isinstance(sub.func, ast.Name) else sub.func.attr)
            return out
    raise AssertionError("doc_sync._test_file_count 找不到——本门的判据宿主变了")


def test_test_file_count_cell_equals_tracked_axis() -> None:
    """腿①：那一格 == `git ls-files` 现算的在册枚数，且当场写明口径。"""
    tracked = _shell_tracked_test_paths()
    assert tracked, "独立尺读出 0 枚＝本尺瞎了，不许据此放行"
    assert ds._test_file_count() == len(tracked), "「测试文件数」不等于 git tracked 口径"
    line = next(l for l in ds.build_document().splitlines() if l.startswith("- 测试文件数："))
    assert line.startswith(f"- 测试文件数：{len(tracked)}（"), line
    assert "tracked" in line, f"那一格没写明口径，下一个人无从判断它数的是什么：{line}"


def test_untracked_test_files_are_not_blessed_by_the_ledger() -> None:
    """腿②（真树、只读、不造件）：未入库件在场 ⇒ 册面数与在盘数**必须**分道。

    判据按现算自适应：今天有未跟踪件就钉「在册 < 在盘且册面＝在册」，
    全部入库后自动退化成「两轴等值」——地板不写死枚数（AGENTS 规则 10）。
    """
    tracked = _shell_tracked_test_paths()
    untracked = _shell_untracked_test_paths()
    on_disk = _disk_test_paths()
    assert set(tracked) <= set(on_disk), "索引里的测试件不在盘上＝本尺的对照面塌了"
    if untracked:
        assert len(tracked) < len(on_disk), (
            f"未跟踪件 {untracked} 没被算进在盘面＝对照面失效，本用例正在空跑")
        assert ds._test_file_count() == len(tracked), (
            f"未跟踪的在飞件 {untracked} 被算进了机器册那一格（口径回退成文件系统 glob）")
    else:
        assert ds._test_file_count() == len(on_disk), "两轴本应等值，册面却对不上"


def test_two_inflight_untracked_probes_do_not_move_the_cell(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """腿②之杀伤力自证（合成树）：在盘多 2 枚未跟踪件 ⇒ 那一格纹丝不动。

    取证面（`_disk_test_glob_count`）必须**看得见**那 2 枚——两轴同数即本用例空跑假绿，
    故这条断言是注毒针：取数口退回 glob 时它先红。
    """
    names = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]
    _fake_inflight_tree(tmp_path, names, 2, monkeypatch)
    assert ds._test_file_count() == 3, "未入库的在飞件被算进了在册口径"
    assert ds._disk_test_glob_count() == 5, "取证面没看见那 2 枚＝两轴同数、本用例空跑"
    assert "- 测试文件数：3（" in ds.build_document(), "生成器那一格不跟在册口径走"


def _raise_oserror(*a: object, **k: object) -> object:
    """注毒形②：git 二进制不在 PATH。"""
    raise FileNotFoundError(2, "git: command not found")


def _raise_timeout(*a: object, **k: object) -> object:
    """注毒形③：git 挂住（超时）。"""
    import subprocess

    raise subprocess.TimeoutExpired(cmd=["git"], timeout=1)


def test_no_git_axis_degrades_loudly_and_never_folds_a_number(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """腿③：git 问不到 ⇒ 印 `NO_GIT_AXIS` + 原因；🔴 不折 0、不折在盘 glob 的数（三形都测）。

    三形＝①rc!=0（干净 checkout／沙箱树没有 `.git`，即 HEAD 轴与 autosync 沙箱的实测形态）
    ②git 二进制不在 PATH（`FileNotFoundError`）③超时（`TimeoutExpired`）。
    """
    import subprocess
    from types import SimpleNamespace

    disk = tmp_path / "tests"
    disk.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (disk / f"test_synth_{i}.py").write_text('"""合成件。"""\n', encoding="utf-8")
    monkeypatch.setattr(ds, "TESTS_DIR", disk)

    def _cell() -> str:
        return next(l for l in ds.build_document().splitlines() if l.startswith("- 测试文件数："))

    for run_leg, expect in (
        (lambda *a, **k: SimpleNamespace(returncode=128, stdout=b"",
                                         stderr=b"fatal: not a git repository"),
         "not a git repository"),
        (_raise_oserror, "NO_GIT_AXIS：git 跑不起来"),
        (_raise_timeout, "NO_GIT_AXIS：git 跑不起来"),
    ):
        monkeypatch.setattr(ds, "subprocess", SimpleNamespace(
            run=run_leg, SubprocessError=subprocess.SubprocessError))
        with pytest.raises(ds.DeclarationBlind, match="NO_GIT_AXIS"):
            ds._test_file_count()
        line = _cell()
        assert "NO_GIT_AXIS" in line and expect in line, f"降级没明写原因：{line}"
        assert "- 测试文件数：0" not in line, "把「取不到」折成 0＝当场瞎掉还自称有数"
        assert "- 测试文件数：3" not in line, "把「取不到」折成在盘 glob 的数＝旧病复发"
        assert "取证面=3" in line, f"降级没把在盘缺口并列出来：{line}"


def test_tracked_axis_present_but_empty_hits_the_collapse_lock(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """腿③的边界：git 问得出、索引里却一枚测试件都没有 ⇒ 走塌陷锁，**不许**被降级吃掉。

    新异常族只收「问不到」；把「问到了是空」也降级＝扫描面塌陷被写成一句人话，
    正是本文件尺①②要治的死法。
    """
    import subprocess
    from types import SimpleNamespace

    disk = tmp_path / "tests"
    disk.mkdir(parents=True, exist_ok=True)
    (disk / "test_synth_0.py").write_text('"""合成件。"""\n', encoding="utf-8")
    monkeypatch.setattr(ds, "TESTS_DIR", disk)
    monkeypatch.setattr(ds, "subprocess", SimpleNamespace(
        run=lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
        SubprocessError=subprocess.SubprocessError))
    with pytest.raises(ds.DeclarationBlind) as caught:
        ds._test_file_count()
    assert not isinstance(caught.value, ds.TrackedAxisUnavailable), (
        "读空被当成「无 git 轴」降级＝把瞎掉洗成文案")


def test_test_file_count_port_reads_tracked_axis_not_the_disk_glob() -> None:
    """腿④（口径锚）：`_test_file_count` 必须调在册取数口，体内再出现 `glob` 即红。

    为什么要有这条静态腿：真树两轴等值时（未跟踪件全入库），腿①②都咬不住"退回旧写法"；
    本锚按 AST 现算钉住接线，改名与换实现都躲不过。
    """
    callees = _callees_of_test_file_count()
    assert "_git_tracked_test_paths" in callees, f"在册口径被摘掉，实调：{sorted(callees)}"
    assert "glob" not in callees, f"文件系统口径又被请回（旧病复发）：{sorted(callees)}"
    assert "_disk_test_glob_count" not in callees, "取证面冒充在册面"

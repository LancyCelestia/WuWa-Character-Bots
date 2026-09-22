"""S182 CONFIG-CATALOG-GENERATOR-PILOT —— `config-field` 可复现字节通道**原型**。

本件是取证/原型件，**不是**生产生成器：它唯一的写盘对象是调用方指定的临时产物
（默认落在系统临时目录），并显式拒绝写进仓库树内任何路径（含 `docs/**`）。

它回答一个可复算的问题（简报 S182）：`config-field` 682 枚能否造出
「从代码派生 ⇒ 逐字节复现 `docs/config-catalog-full.md` 对应行」的通道？

三件事分开做，互不冒充：
1. **派生**（`derive_cells`）：只吃 `config.py` AST + `settings.py` 两张热改表 ⇒ 诚实产出
   键名/类型/缺省/热更（+ `Field` 约束）四列半；人写三列（合法值/作用/关系）**没有码上真身**，
   留空并记 provenance。
2. **双向对齐**（`parse_catalog_rows` / `classify_diffs`）：用 `tests/test_doc_sync_gates.py`
   的既有在册判据语义（`BOT_X` / `bot_x` / 省前缀 `_x` 三种写法归一）反查盘上行，逐列分类差异。
3. **判决**（`verdict_for_family`）：幂等（连跑字节等值）**不等于**可复现；
   一旦人工文字进入通道（`--manual-source catalog`），即便逐字节等值也判「非可复现」。

形态不认识 ⇒ fail-closed 点名（`UnrepresentableField`），绝不静默跳过、绝不编造（假绿形态册第 3 类）。
复跑命令原文见报告 `.superpowers/sdd/2026-09-22-taxonomy/SEAT-S182.md`。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PY = ROOT / "plugins" / "bot_unified_runtime" / "config.py"
CATALOG_MD = ROOT / "docs" / "config-catalog-full.md"
SETTINGS_PY = (
    ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "settings.py"
)

COLUMNS: tuple[str, ...] = ("name", "type", "default", "legal", "hot", "purpose", "relation")
HUMAN_COLUMNS: frozenset[str] = frozenset({"legal", "purpose", "relation"})
SEVEN_COLS = len(COLUMNS)
HOT_TEXT: dict[str, str] = {"settable": "✅热更", "restart": "🟡需重启", "none": "❌无热改面"}

# 差异类别登记表：收尾贴的「每类一枚实例」由此派生；计数含 0 也照写。
CATEGORIES: tuple[str, ...] = (
    "byte-equal",
    "schema-mismatch",
    "key-spelling",
    "multi-key-row",
    "row-ambiguity",
    "row-absent",
    "type-form",
    "default-form",
    "legal-no-code-source",
    "legal-bounds-not-on-disk",
    "hot-tier-mismatch",
    "purpose-no-code-source",
    "relation-no-code-source",
    "manual-text-into-channel",
    "unrepresentable-field-form",
)


class UnrepresentableField(RuntimeError):
    """AST 取不到可信形态的字段 —— 通道必须 fail-closed 点名，不许静默跳过或编造。"""


@dataclass(frozen=True)
class FieldInfo:
    """一枚 pydantic 字段的代码侧事实（全部来自 AST，零散文）。"""

    name: str
    type_text: str
    default_text: str
    bounds_text: str


@dataclass(frozen=True)
class CatalogRow:
    line_no: int
    cells: list[str]
    keys: list[str]
    raw: str

    @property
    def ncols(self) -> int:
        return len(self.cells)


@dataclass(frozen=True)
class Diff:
    category: str
    column: str
    generated: str
    disk: str
    detail: str


@dataclass(frozen=True)
class FieldVerdict:
    name: str
    generated_line: str
    disk_line: str
    disk_line_no: int
    byte_equal: bool
    diffs: list[Diff]


# ---------------------------------------------------------------------------
# 代码侧：config.py / settings.py 的 AST 静态读取（绝不 import，防写出 __pycache__）
# ---------------------------------------------------------------------------


def _config_class(tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Config":
            return node
    raise UnrepresentableField("config.py 里找不到 class Config —— 取数口形状已变，拒绝继续")


_REPRIMITIVES: frozenset[str] = frozenset({"str", "bool", "int", "float"})


def _type_text(node: ast.expr) -> str:
    """注解 → 类型文字。只认基本类型 / list[...] / dict[...] / 二者或运算，其余 fail-closed。"""
    if isinstance(node, ast.Name) and node.id in _REPRIMITIVES:
        return node.id
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"list", "dict"}
    ):
        return ast.unparse(node)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return f"{_type_text(node.left)} | {_type_text(node.right)}"
    raise UnrepresentableField(f"注解形态 AST 取不到可信类型：{ast.unparse(node)}")


_FOLD_OPS: dict[type[ast.operator], str] = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.FloorDiv: "//", ast.Mod: "%",
}


def _fold_numeric(node: ast.expr) -> int | float | None:
    """纯字面量算术（如 `8 * 1024 * 1024`）的确定性折叠；任何非字面量 ⇒ None（交回 fail-closed）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _fold_numeric(node.operand)
        return None if inner is None else -inner
    if isinstance(node, ast.BinOp) and type(node.op) in _FOLD_OPS:
        left, right = _fold_numeric(node.left), _fold_numeric(node.right)
        if left is None or right is None:
            return None
        op = _FOLD_OPS[type(node.op)]
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/" and right:
            return left / right
        if op == "//" and right:
            return left // right
        if op == "%" and right:
            return left % right
    return None


def _literal_text(node: ast.expr) -> str:
    """缺省值表达式 → 字面文字（字符串去引号，容器用 unparse，纯算术字面量先折叠）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, (ast.List, ast.Dict, ast.Tuple, ast.Set)):
        return ast.unparse(node)
    folded = _fold_numeric(node)
    if folded is not None:
        return repr(folded)
    raise UnrepresentableField(f"缺省值形态 AST 取不到字面值：{ast.unparse(node)}")


def load_config_fields(source: str) -> dict[str, FieldInfo]:
    """`Config` 类字段全集 → 代码侧事实表；形态不认识就点名，绝不静默丢。"""
    cls = _config_class(ast.parse(source))
    out: dict[str, FieldInfo] = {}
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id.startswith("bot_"):
                    raise UnrepresentableField(
                        f"无注解的 bot_ 赋值（在册判据与类型列都看不见它）：{tgt.id} 行 {stmt.lineno}"
                    )
            continue
        if not isinstance(stmt, ast.AnnAssign):
            continue
        if not isinstance(stmt.target, ast.Name):
            raise UnrepresentableField(f"非 Name 目标的注解赋值，取不到键名：行 {stmt.lineno}")
        name = stmt.target.id
        if not name.startswith("bot_"):
            continue
        if stmt.value is None:
            raise UnrepresentableField(f"{name}: 字段无缺省值 ⇒ catalog「默认值」列无源，拒绝编造")
        type_text = _type_text(stmt.annotation)
        value = stmt.value
        bounds = ""
        if isinstance(value, ast.Call):
            fname = getattr(value.func, "id", "")
            if fname != "Field":
                raise UnrepresentableField(
                    f"{name}: 缺省值调用 {fname or '?'}(...) 非 Field，无法可信还原"
                )
            default_kw = next((kw for kw in value.keywords if kw.arg == "default"), None)
            if default_kw is None or default_kw.value is None:
                raise UnrepresentableField(f"{name}: Field(...) 无 default= ⇒「默认值」列无源，拒绝编造")
            default_text = _literal_text(default_kw.value)
            bounds = ", ".join(
                f"{kw.arg}={ast.unparse(kw.value)}"
                for kw in value.keywords
                if kw.arg in {"ge", "gt", "le", "lt"} and kw.value is not None
            )
        else:
            default_text = _literal_text(value)
        out[name] = FieldInfo(
            name=name, type_text=type_text, default_text=default_text, bounds_text=bounds
        )
    return out


def _dict_keys(source: str, var_name: str) -> frozenset[str]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        tgt: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign):
            tgt, value = node.target, node.value
        elif isinstance(node, ast.Assign):
            tgt, value = (node.targets[0] if len(node.targets) == 1 else None), node.value
        if isinstance(tgt, ast.Name) and tgt.id == var_name and isinstance(value, ast.Dict):
            keys: set[str] = set()
            for key in value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
                else:
                    raise UnrepresentableField(f"{var_name} 出现非字符串字面键 ⇒ 热改档无源")
            return frozenset(keys)
    raise UnrepresentableField(f"settings.py 找不到 {var_name} 字面量 ⇒ 热改三档无源")


def load_hot_tiers(source: str) -> dict[str, str]:
    """热改三档（字段名 → settable/restart/none）；两表均未登记即 none，两表同现即点名。"""
    settable = {k.lower() for k in _dict_keys(source, "SETTABLE_KEYS")}
    restart = {k.lower() for k in _dict_keys(source, "RESTART_REQUIRED_KEYS")}
    overlap = sorted(settable & restart)
    if overlap:
        raise UnrepresentableField(f"同键既在 SETTABLE_KEYS 又在 RESTART_REQUIRED_KEYS ⇒ 档位无唯一真值：{overlap}")
    tiers = {k: "settable" for k in settable}
    tiers.update({k: "restart" for k in restart})
    return tiers


# ---------------------------------------------------------------------------
# 盘侧：catalog 行解析 + 在册判据（与 tests/test_doc_sync_gates.py 同语义，只读复用）
# ---------------------------------------------------------------------------


def normalize_catalog_key(token: str) -> str | None:
    lowered = token.strip().lower()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", lowered):
        return None
    if lowered.startswith("bot_"):
        return lowered
    stripped = lowered.lstrip("_")
    return f"bot_{stripped}" if stripped else None


def parse_catalog_rows(text: str) -> list[CatalogRow]:
    rows: list[CatalogRow] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or set(cells[0]) <= set("-: "):
            continue
        keys = [
            k
            for k in (normalize_catalog_key(t) for t in re.findall(r"`([^`]+)`", cells[0]))
            if k
        ]
        if keys:
            rows.append(CatalogRow(line_no=line_no, cells=cells, keys=keys, raw=line))
    return rows


def index_rows_by_key(rows: list[CatalogRow]) -> dict[str, list[CatalogRow]]:
    index: dict[str, list[CatalogRow]] = {}
    for row in rows:
        for key in row.keys:
            index.setdefault(key, []).append(row)
    return index


# ---------------------------------------------------------------------------
# 派生 + 对拍
# ---------------------------------------------------------------------------


def derive_cells(
    info: FieldInfo, tiers: dict[str, str], manual: dict[str, str] | None
) -> tuple[dict[str, str], dict[str, str]]:
    """七列内容与逐列来源（code / none / manual）。人工列默认留空 ⇒ 留空即与盘上不字节等值。"""
    prov = {
        "name": "code",
        "type": "code",
        "default": "code",
        "legal": "code" if info.bounds_text else "none",
        "hot": "code",
        "purpose": "none",
        "relation": "none",
    }
    cells = {
        "name": f"`{info.name.upper()}`",
        "type": info.type_text,
        "default": f"`{info.default_text}`",
        "legal": info.bounds_text,
        "hot": HOT_TEXT[tiers.get(info.name, "none")],
        "purpose": "",
        "relation": "",
    }
    if manual:
        for col in HUMAN_COLUMNS:
            if col in manual:
                cells[col] = manual[col]
                prov[col] = "manual"
    return cells, prov


def render_row(cells: dict[str, str]) -> str:
    return "| " + " | ".join(cells[col] for col in COLUMNS) + " |"


def classify_diffs(gen_line: str, cells: dict[str, str], disk_rows: list[CatalogRow]) -> tuple[list[Diff], str, int]:
    """逐枚给差异类别。盘上无行 / 非七列 / 一行多键 / 一键多行各自成类——都是「写不回去」的结构性理由。"""
    if not disk_rows:
        return (
            [Diff("row-absent", "name", gen_line, "", "在册判据未命中：catalog 查不到该键的注册行")],
            "",
            0,
        )
    seven = [r for r in disk_rows if r.ncols == SEVEN_COLS]
    if not seven:
        head = disk_rows[0]
        return (
            [
                Diff(
                    "schema-mismatch",
                    "name",
                    gen_line,
                    head.raw,
                    f"盘上注册行是 {head.ncols} 列制（第 {head.line_no} 行），七列生成器无从对齐",
                )
            ],
            head.raw,
            head.line_no,
        )
    target = seven[0]
    diffs: list[Diff] = []
    if len(disk_rows) > 1:
        diffs.append(
            Diff(
                "row-ambiguity",
                "name",
                gen_line,
                target.raw,
                f"该键命中 {len(disk_rows)} 张表行 ⇒ 写回落点不唯一",
            )
        )
    if len(target.keys) > 1:
        diffs.append(
            Diff(
                "multi-key-row",
                "name",
                gen_line,
                target.raw,
                f"一行登记 {len(target.keys)} 枚键 ⇒ 逐键生成器无法复现合并行",
            )
        )
    if target.cells[0] != cells["name"]:
        diffs.append(
            Diff("key-spelling", "name", cells["name"], target.cells[0], "盘上键名写法非大写 `BOT_X` 形")
        )
    for col, cat in (("type", "type-form"), ("default", "default-form"), ("hot", "hot-tier-mismatch")):
        idx = COLUMNS.index(col)
        if target.cells[idx] != cells[col]:
            diffs.append(
                Diff(cat, col, cells[col], target.cells[idx], "派生文字与盘上文字不逐字等值")
            )
    idx_legal = COLUMNS.index("legal")
    if cells["legal"]:
        if target.cells[idx_legal] != cells["legal"]:
            diffs.append(
                Diff(
                    "legal-bounds-not-on-disk",
                    "legal",
                    cells["legal"],
                    target.cells[idx_legal],
                    "Field 约束派生文字与盘上「合法值」列不一致",
                )
            )
    elif target.cells[idx_legal]:
        diffs.append(
            Diff(
                "legal-no-code-source",
                "legal",
                "",
                target.cells[idx_legal],
                "盘上「合法值/范围」是人写散文，码上无真身",
            )
        )
    for col, cat in (("purpose", "purpose-no-code-source"), ("relation", "relation-no-code-source")):
        idx = COLUMNS.index(col)
        if not cells[col] and target.cells[idx]:
            diffs.append(
                Diff(cat, col, "", target.cells[idx], "盘上该列是人写散文，码上无真身")
            )
    return diffs, target.raw, target.line_no


def evaluate(
    fields: dict[str, FieldInfo],
    tiers: dict[str, str],
    index: dict[str, list[CatalogRow]],
    names: list[str],
    manual_texts: dict[str, dict[str, str]] | None,
) -> list[FieldVerdict]:
    verdicts: list[FieldVerdict] = []
    for name in names:
        info = fields[name]
        manual = manual_texts.get(name) if manual_texts else None
        cells, _prov = derive_cells(info, tiers, manual)
        line = render_row(cells)
        diffs, disk_raw, disk_line_no = classify_diffs(line, cells, index.get(name, []))
        verdicts.append(
            FieldVerdict(
                name=name,
                generated_line=line,
                disk_line=disk_raw,
                disk_line_no=disk_line_no,
                byte_equal=bool(disk_raw) and line == disk_raw,
                diffs=diffs,
            )
        )
    return verdicts


def manual_from_disk(index: dict[str, list[CatalogRow]], names: list[str]) -> dict[str, dict[str, str]]:
    """注毒 c 的弹药：把盘上人写三列原样喂回通道（模拟「拿人工文字冒充派生」）。"""
    out: dict[str, dict[str, str]] = {}
    for name in names:
        rows = [r for r in index.get(name, []) if r.ncols == SEVEN_COLS]
        if rows:
            cells = rows[0].cells
            out[name] = {col: cells[COLUMNS.index(col)] for col in HUMAN_COLUMNS}
    return out


def select_sample(fields: dict[str, FieldInfo], size: int) -> list[str]:
    """确定性切片：先按类型档各取 2 枚（异形必入样），再跨步补足；同输入两次结果逐位相同。"""
    by_kind: dict[str, list[str]] = {}
    for name in sorted(fields):
        kind = re.sub(r"\[.*", "", fields[name].type_text)
        by_kind.setdefault(kind, []).append(name)
    picked: list[str] = []
    for kind in sorted(by_kind):
        picked.extend(by_kind[kind][:2])
    chosen = set(picked)
    rest = [n for n in sorted(fields) if n not in chosen]
    step = max(1, len(rest) // max(1, size))
    for i in range(0, len(rest), step):
        if len(picked) >= size:
            break
        picked.append(rest[i])
    return sorted(picked[:size])


def build_artifact(verdicts: list[FieldVerdict]) -> bytes:
    """产物：**不含时间戳行**（区别于 content_census 的生成时间行）⇒ `cmp` 逐字节判据直接适用。"""
    return "".join(f"{v.generated_line}\n" for v in verdicts).encode("utf-8")


def verdict_for_family(verdicts: list[FieldVerdict], used_manual: bool) -> dict[str, object]:
    cats: dict[str, int] = {c: 0 for c in CATEGORIES}
    instances: dict[str, str] = {}
    for v in verdicts:
        if v.byte_equal:
            cats["byte-equal"] += 1
            instances.setdefault("byte-equal", f"{v.name}（catalog 第 {v.disk_line_no} 行）")
        for d in v.diffs:
            cats[d.category] += 1
            instances.setdefault(d.category, f"{v.name}（catalog 第 {v.disk_line_no} 行）")
    equal = sum(1 for v in verdicts if v.byte_equal)
    if used_manual:
        cats["manual-text-into-channel"] = len(verdicts)
        instances.setdefault("manual-text-into-channel", "人工三列整体喂入")
    human_free = all({d.column for d in v.diffs} <= set(HUMAN_COLUMNS) for v in verdicts if not v.byte_equal)
    reproducible = bool(verdicts) and equal == len(verdicts) and not used_manual
    return {
        "sampled": len(verdicts),
        "byte_equal": equal,
        "categories": cats,
        "category_instances": instances,
        "code_columns_clean": human_free,
        "reproducible": reproducible,
        "manual_used": used_manual,
        "reason": (
            "人工列进入通道 ⇒ 判非可复现（逐字节等值也不算达标）"
            if used_manual
            else (
                "切片逐字节等值且无人工注入"
                if reproducible
                else "存在无码上真身的人写列 / 异构表行 ⇒ 派生骨架 ≠ 盘上产物字节"
            )
        ),
    }


# ---------------------------------------------------------------------------
# 反向注毒（a＝产物手改对拍；b＝AST 取不到必点名；c＝人工文字入道必判非可复现）
# ---------------------------------------------------------------------------


def self_test_unrepresentable() -> tuple[bool, list[str]]:
    """注毒 b：造 AST 取不到的字段形态 ⇒ 通道必须 fail-closed 点名（不许静默跳过）。"""
    probes: tuple[tuple[str, str], ...] = (
        ("自定义注解类型", "class Config(BaseModel):\n    bot_weird: LocaleSpec = 'en'\n"),
        ("无 default 的 Field", "class Config(BaseModel):\n    bot_req: int = Field(...)\n"),
        ("无注解的 bot_ 赋值", "class Config(BaseModel):\n    bot_bare = 'x'\n"),
        ("缺省值非字面量", "class Config(BaseModel):\n    bot_calc: str = build_default()\n"),
    )
    lines: list[str] = []
    ok = True
    for label, src in probes:
        try:
            load_config_fields(src)
        except UnrepresentableField as exc:
            lines.append(f"  {label} → 点名成功：{exc}")
        else:
            ok = False
            lines.append(f"  {label} → 未点名（静默放过）＝假绿")
    return ok, lines


def check_artifact(path: Path, artifact: bytes) -> tuple[bool, str]:
    """注毒 a：产物被手改一行 ⇒ 幂等对拍必红，并点名是第几行。"""
    if not path.exists():
        return False, f"产物不存在：{path}"
    disk = path.read_bytes()
    if disk == artifact:
        return True, "产物与现生成逐字节等值"
    a = artifact.decode("utf-8").splitlines()
    b = disk.decode("utf-8").splitlines()
    for i, (x, y) in enumerate(zip(a, b), start=1):
        if x != y:
            return False, f"第 {i} 行不等：产物现值 {y!r}"
    return False, f"行数不等（现生成 {len(a)}，产物 {len(b)}）"


def refuse_repo_write(path: Path | None) -> str | None:
    """守卫：本席禁写仓库树（`docs/**` 一字不写），产物只准落临时目录。"""
    if path is None:
        return None
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        return None
    return f"拒绝写进仓库树：{resolved}（产物只准落临时目录）"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="config-field 可复现通道原型（S182，只写临时产物）")
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument(
        "--out", type=Path, default=Path(tempfile.gettempdir()) / "s182-config-catalog-pilot.md"
    )
    parser.add_argument("--twice", action="store_true", help="连跑两次做字节级幂等对拍")
    parser.add_argument("--check-artifact", type=Path, default=None, help="与现生成对拍（注毒 a）")
    parser.add_argument("--manual-source", choices=["catalog"], default=None, help="注毒 c")
    parser.add_argument("--json", type=Path, default=None, help="判决 JSON 输出（临时目录）")
    parser.add_argument("--self-test-b", action="store_true", help="注毒 b：AST 取不到的形态必点名")
    args = parser.parse_args(argv)

    if args.self_test_b:
        ok, lines = self_test_unrepresentable()
        print("\n".join(lines))
        print(f"注毒 b：{'PASS（全部点名）' if ok else 'FAIL（静默放过＝假绿）'}")
        return 0 if ok else 1

    for guarded in (args.out, args.json, args.check_artifact):
        msg = refuse_repo_write(guarded)
        if msg:
            print(msg, file=sys.stderr)
            return 2

    fields = load_config_fields(CONFIG_PY.read_text(encoding="utf-8"))
    tiers = load_hot_tiers(SETTINGS_PY.read_text(encoding="utf-8"))
    rows = parse_catalog_rows(CATALOG_MD.read_text(encoding="utf-8"))
    index = index_rows_by_key(rows)
    names = select_sample(fields, args.sample)
    manual_texts = manual_from_disk(index, names) if args.manual_source == "catalog" else None
    verdicts = evaluate(fields, tiers, index, names, manual_texts)
    artifact = build_artifact(verdicts)
    args.out.write_bytes(artifact)

    print(f"字段全集={len(fields)} catalog 表行={len(rows)} 在册键={len(index)} 切片={len(names)}")
    print(f"产物={args.out} sha256={hashlib.sha256(artifact).hexdigest()[:16]} bytes={len(artifact)}")
    for v in verdicts:
        cats = ",".join(sorted({d.category for d in v.diffs})) or "-"
        print(f"{'EQ ' if v.byte_equal else 'NEQ'} {v.name} 类型={fields[v.name].type_text} 类别={cats}")
    if args.twice:
        again = build_artifact(evaluate(fields, tiers, index, names, manual_texts))
        print(
            f"连跑两次字节等值（幂等）＝{again == artifact}；"
            f"第二次 sha256={hashlib.sha256(again).hexdigest()[:16]}"
        )
    if args.check_artifact is not None:
        ok, msg = check_artifact(args.check_artifact, artifact)
        print(f"注毒 a：产物对拍 {'PASS（等值）' if ok else 'RED（被改动）'} —— {msg}")
    fam = verdict_for_family(verdicts, bool(manual_texts))
    print(json.dumps(fam, ensure_ascii=False, sort_keys=True))
    if args.json:
        args.json.write_text(
            json.dumps({"family": fam, "sample": names}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.manual_source == "catalog":
        if fam["reproducible"]:
            print("注毒 c：FAIL —— 人工文字进入通道却判了可复现（假绿）", file=sys.stderr)
            return 1
        print(f"注毒 c：PASS —— {fam['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

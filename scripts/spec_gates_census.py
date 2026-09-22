"""G-T1/T2/T3/T4/T5 唯一取数口（席 T-GATES，2026-09-22）。

一句话：**违规清单、总数、`--report` 三处同源**——同一支 `compute(root)` 既喂常驻门的
断言，也喂注毒用例，还喂命令行；禁在测试里另起一套扫描器（本仓「第二真身」教训）。

各类判据（详见 `GATE-PLAN.md` §三）：

- **G-T1** 内容页必须有指向存在模板的 `template:` 头；生成物按**写盘口现算**豁免
  （`scripts/board_doc_sync.py:live_page_paths`、`scripts/doc_sync.py:TARGET`、
  `scripts/command_catalog.py:DOC`），路径与符号名都从那份脚本 AST 里取，**不写死文件清单**。
  S2 加严面 B：头还在册、却套了**别类**的模板 ⇒ `TEMPLATE_CATEGORY_MISMATCH` 红，
  且该页在 G-T1 不销籍（类别↔模板一致性取数只走 `doc_templates.py` 注册表唯一真身）。
- **G-T2** 同类内容小节集合与顺序一致：生成页按板块骨架 canon、模板页按 `@schema sections`，
  尺子是 T-SHAPE 归一口径（剥围栏、剥机器段、节名只比括号前主干、序号前缀归一）。
- **G-T3** 正文禁裸写一次性事实（判据真身 `scripts/doc_fact_discipline.py`）。
- **G-T4** `@schema` 与实际渲染参数双向对齐（缺参/多参/死参/未注册 provider/schema 畸形）。
  S2 活性腿：`req` 且 `source=auto:` 的参数，provider 现算值空/占位符冒充 ⇒ `PROVIDER_EMPTY` 红。
- **G-T5** 类别集合与 CENSUS §一 一致、无模板类别清零、孤儿模板清零、类别必须接得到页；
  S2 补第三边：页→类别→在册模板三角闭合，任一页落到接不到模板的类别 ⇒ 按类别记红。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import board_doc_sync as bds
import doc_fact_discipline as dfd
import doc_template_sync as dts
import doc_templates as dt

CENSUS_MD = ROOT / ".superpowers/sdd/2026-09-22-taxonomy/CENSUS.md"
_NUM_PREFIX = re.compile(r"^(?:[一二三四五六七八九十百]+、|\d+[.、)]|§\s*[一二三四五六七八九十\d]+)\s*")
_H2_RE = re.compile(r"^##\s+(?!#)(.+?)\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# 通用件：小节归一签名（T-SHAPE 裁决①口径）
# ---------------------------------------------------------------------------
def trunk(heading: str) -> str:
    h = _NUM_PREFIX.sub("", heading.strip())
    return re.split(r"[（(:：]", h, 1)[0].strip()


def headings(text: str) -> list[str]:
    return [trunk(m.group(1)) for m in _H2_RE.finditer("\n".join(_no_fences(text)))]


def _no_fences(text: str) -> list[str]:
    out: list[str] = []
    infence = False
    for ln in text.splitlines():
        if dfd._FENCE_RE.match(ln):
            infence = not infence
            continue
        if not infence:
            out.append(ln)
    return out


def canon_of_skeleton(body: str, optional: tuple[str, ...] = ()) -> list[tuple[str, bool]]:
    return [(trunk(m.group(1)), trunk(m.group(1)) in optional) for m in _H2_RE.finditer(body)]


#: 可选节按 SPEC-TARGETS §1-5/6/7 的 `?` 尾缀；其余全必填。
L1_CANON = canon_of_skeleton(bds.L1_BODY)
L2_CANON = canon_of_skeleton(bds.L2_BODY, ("边界与降级", "现行缺陷"))
L3_CANON = canon_of_skeleton(bds.L3_BODY)
BOARD_CANON: dict[str, list[tuple[str, bool]]] = {
    "board-l1": L1_CANON,
    "board-l2": L2_CANON,
    "board-l3": L3_CANON,
}


# ---------------------------------------------------------------------------
# 生成物：点名取数口，AST 现算（禁写死文件清单当豁免）
# ---------------------------------------------------------------------------
def _script_file(script: str) -> Path:
    name = script if script.endswith(".py") else script + ".py"
    path = Path(name)
    return path if path.is_absolute() else (ROOT / name if name.startswith("scripts/") else ROOT / "scripts" / name)


def _collect_path_parts(node: ast.expr, parts: list[str]) -> None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        _collect_path_parts(node.left, parts)
        _collect_path_parts(node.right, parts)
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        parts.append(node.value)
    elif isinstance(node, ast.Call):  # Path("x")
        for arg in getattr(node, "args", ()):
            _collect_path_parts(arg, parts)


def _symbol_path(script: str, symbol: str) -> str:
    """读 `scripts/<script>.py` 里 `SYM = ROOT / "a" / "b"` 的字面相对路径（AST，不 import）。"""
    tree = ast.parse(_script_file(script).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None or not any(isinstance(t, ast.Name) and t.id == symbol for t in targets):
            continue
        parts: list[str] = []
        _collect_path_parts(value, parts)
        joined = "/".join(parts).replace("\\", "/")
        return re.sub(r"^/+", "", joined)
    raise LookupError(f"{script} 里找不到符号 {symbol} 的字面路径——取数口改名了，门必须跟着改")


def generated_rels(root: Path = ROOT) -> dict[str, set[str]]:
    """每个写盘口 → 它生成的页（相对 posix）。三处点名，缺一处即红（装载期抛错）。"""
    out: dict[str, set[str]] = {}
    out["scripts/doc_sync.py:TARGET"] = {_symbol_path("doc_sync", "TARGET")}
    out["scripts/command_catalog.py:DOC"] = {_symbol_path("command_catalog", "DOC")}
    boards, problems = bds.build_tree()
    if problems:
        out["scripts/board_doc_sync.py:live_page_paths"] = set()
    else:
        out["scripts/board_doc_sync.py:live_page_paths"] = {
            p.relative_to(ROOT).as_posix() for p in bds.live_page_paths(boards)
        }
    out["scripts/doc_template_sync.py:TEMPLATE_DIR"] = {
        p.relative_to(ROOT).as_posix() for p in sorted(dts.TEMPLATE_DIR.glob("*.md"))
    }
    if root != ROOT:  # 合成树只保留真实存在的那些（注毒面没有生成页）
        for paths in out.values():
            paths &= {r for r in paths if (root / r).is_file()}
    return out


# ---------------------------------------------------------------------------
# CENSUS §一 类别名（现算，不手抄条目数）
# ---------------------------------------------------------------------------
def census_category_names() -> list[str]:
    text = CENSUS_MD.read_text(encoding="utf-8", errors="replace")
    if "## 一、" not in text or "## 二、" not in text:
        raise LookupError(f"{CENSUS_MD} 缺 §一/§二 分节——判据源改版，门必须复核")
    sec = text.split("## 一、", 1)[1].split("## 二、", 1)[0]
    names: list[str] = []
    for line in sec.splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*[^|]+\|\s*$", line)
        if not m:
            continue
        cell = m.group(1).strip()
        if not cell or cell.startswith("---") or cell == "内容类别":
            continue
        if cell.startswith("board-l"):
            names += ["board-l1", "board-l2", "board-l3"]  # CENSUS 一行三名
        else:
            names.append(cell)
    return names


# ---------------------------------------------------------------------------
# 小节一致性（G-T2 判据，纯函数）
# ---------------------------------------------------------------------------
def section_findings(heads: list[str], canon: list[tuple[str, bool]]) -> list[str]:
    idx = {name: i for i, (name, _opt) in enumerate(canon)}
    viol: list[str] = []
    seen: list[int] = []
    hit: set[int] = set()
    for h in heads:
        i = idx.get(h)
        if i is None:
            viol.append(f"SECTION_UNKNOWN {h!r} 不在该类骨架 {list(idx)}")
            continue
        if i in hit:
            viol.append(f"SECTION_DUPLICATE {h!r}")
            continue
        hit.add(i)
        seen.append(i)
    for i, (name, opt) in enumerate(canon):
        if not opt and i not in hit:
            viol.append(f"SECTION_MISSING 缺必选节 {name!r}")
    if seen != sorted(seen):
        viol.append(f"SECTION_ORDER 顺序 {seen} 偏离声明序")
    return viol


# ---------------------------------------------------------------------------
# G-T4 判据（模板侧死参 / provider 注册 / schema 装载）
# ---------------------------------------------------------------------------
T4_CODES = (
    "MISSING_PARAM",
    "EXTRA_PARAM",
    "FM_EXTRA_KEY",
    "AUTO_SOURCE_MISMATCH",
    "PROVIDER_MISSING",
    "PROVIDER_FAIL",
    "PROVIDER_EMPTY",  # 席 S2 活性腿：req+auto 参数现算值空/占位符冒充
    "DOMAIN_FAIL",
    "SCHEMA_ERROR",
    "DEAD_PARAM",
    "TEMPLATE_MISSING",
    "NO_TEMPLATE_KEY",
)


# ---------------------------------------------------------------------------
# S2 T-GATE-HARDEN 加严腿（2026-09-22，攻击依据 SEAT-T-ACCUSE F-2）
# ①TEMPLATE_CATEGORY_MISMATCH：内容件声明的 `template:` 必须与它**按类别注册表被判定的
#   类别**的在册模板一致——套错模板 ⇒ 红，且该页在 G-T1 **不销籍**（driven() 拒认）。
#   取数只走 `doc_templates.CATEGORIES_BY_ID` 唯一真身，本门零第二份类别表。
# ②G-T5 三角闭合（第三边）：任一页落到「接不到在册模板」的类别 ⇒ 按类别记红。
# 两条都只加严：不新增豁免、不缩任何扫描面。
# ---------------------------------------------------------------------------
def registered_template(category: str) -> str | None:
    """类别 → 在册模板 id（注册表唯一真身）。None＝生成器所有/未在册/代码面，不由本腿执法。"""
    c = dt.CATEGORIES_BY_ID.get(category)
    if c is None or c.generated_by or c.surface != "md":
        return None
    return c.template


def category_mismatch(p: dts.PageInfo, schemas: dict[str, dts.Schema]) -> str | None:
    """页套了「不是它这一类」的在册模板 ⇒ 一行罪状；无头/假头归 G-T1 原腿，不重复记账。"""
    if p.fm is None or not p.fm.template or p.fm.template not in schemas:
        return None
    want = registered_template(p.category)
    if want and want != p.fm.template:
        return (
            f"TEMPLATE_CATEGORY_MISMATCH {p.rel}: 声明 template={p.fm.template!r}，"
            f"但类别 {p.category!r} 的在册模板是 {want!r}（套错模板＝形式合规实质空转）"
        )
    return None


def template_side_t4(schemas: dict[str, dts.Schema]) -> list[str]:
    viol: list[str] = []
    for tid, sch in sorted(schemas.items()):
        consumed = set(dts._PLACEHOLDER_RE.findall(sch.render_zone))
        for key in sorted(sch.keys - consumed):
            viol.append(f"DEAD_PARAM {tid}: 声明参数 {key!r} 未被渲染区消费（多参＝规格外死参）")
        for p in sch.params:
            if p.source.startswith("auto:") and p.source.split(":")[1] not in dts.PROVIDERS:
                viol.append(
                    f"PROVIDER_MISSING {tid}: auto 提供器 {p.source.split(':')[1]!r} 未注册"
                )
    return viol


# ---------------------------------------------------------------------------
# 主计算
# ---------------------------------------------------------------------------
def compute(root: Path = ROOT) -> dict[str, object]:
    schemas: dict[str, dts.Schema] = {}
    schema_errors: list[str] = []
    for path in sorted(dts.TEMPLATE_DIR.glob("*.md")):
        try:
            schemas[path.stem] = dts.parse_schema_text(
                path.read_text(encoding="utf-8", errors="replace"), path.stem
            )
        except dts.SchemaError as exc:
            schema_errors.append(f"SCHEMA_ERROR {exc}")

    gen_map = generated_rels(root)
    gen_all = {r for paths in gen_map.values() for r in paths}
    pages = [
        p
        for p in dts.annotate(dts.walk_content_pages(root), schemas)
        if not p.rel.startswith(dt.TEMPLATE_SOURCE_PREFIX)
    ]
    labels = {p.category for p in pages}

    # --- G-T1：无 template 头且非生成物。S2 加严：driven() 从此**不认**套错模板的页
    #     （错配页不销籍，与 mismatch 账各记各的——同一页两处红是设计意图，不是双计错误）。
    def driven(p: dts.PageInfo) -> bool:
        return (
            p.fm is not None
            and p.fm.template in schemas
            and category_mismatch(p, schemas) is None
        )

    t1 = [p.rel for p in pages if p.rel not in gen_all and not driven(p)]
    t1_by_cat = dict(Counter(dts.classify(r) for r in t1))
    mismatch = [m for m in (category_mismatch(p, schemas) for p in pages) if m]

    # --- G-T2：同类小节集合与顺序
    t2: list[str] = []
    t2_pages = 0
    for p in pages:
        if p.rel in gen_all and not p.rel.startswith("docs/boards/"):
            continue  # auto-facts / command-catalog / 模板源：整册机器所有，无「人写同类」可言
        heads: list[str] | None = None
        if p.rel.startswith("docs/boards/"):
            canon = BOARD_CANON.get(p.category)
            if canon is None:
                continue
            text = p.path.read_text(encoding="utf-8", errors="replace")
            human = text.split(bds.AUTO_END, 1)[1] if bds.AUTO_END in text else text
            heads = headings("\n".join(_no_fences(dfd.strip_auto_zones(human))))
            t2_pages += 1
            found = [f"{p.rel}: {v}" for v in section_findings(heads, canon)]
        elif p.fm is not None and p.fm.template in schemas:
            t2_pages += 1
            found = [
                f"{p.rel}: {v}" for v in dts.check_sections(schemas[p.fm.template], p.text)
            ]
        else:
            continue
        if found:  # 记账单位＝「件」（页），一页多码只算一枚偏离页
            t2.append(f"{p.rel}: " + " | ".join(found))

    # --- G-T3：正文禁裸写一次性事实（两把面，各自只降）
    #   面 A＝本轮治理面（板块人工区 + 已迁移模板页）：记账单位=**行**，目标硬零。
    #   面 B＝未迁移手写页：记账单位=**页**（含 ≥1 条裸事实即记一页）。
    #   `.superpowers/**` 是过程日志面（各席随时追加行，任何行级上限都会随机漂移），
    #   它的债在 G-T1 按「未迁移页数」记账（页数单调，追加正文不新增页）——此处如实排除。
    vocab = set(bds.load_help_topics()) | {str(k) for k in bds.load_route_kind_members()}
    t3_managed: list[str] = []
    t3_unmoved: list[str] = []
    t3_pages = 0
    for p in pages:
        lines = dfd.human_lines(p.text)
        if not lines:
            continue
        hits = [f"{p.rel}: {v}" for v in dfd.fact_findings(lines, vocab=vocab)]
        if not hits:
            continue
        t3_pages += 1
        if p.rel.startswith("docs/boards/") or (p.rel not in gen_all and driven(p)):
            t3_managed += hits
        elif not p.rel.startswith(".superpowers/"):
            t3_unmoved.append(p.rel)
    t3 = t3_managed + t3_unmoved

    # --- G-T4：schema ↔ 实参双向对齐
    t4 = list(schema_errors) + template_side_t4(schemas)
    for p in pages:
        t4 += [f"{p.rel}: {v}" for v in p.violations if v.split(" ", 1)[0] in T4_CODES]

    # --- G-T5：类别 ↔ 模板 ↔ 页 三面对账
    declared = {c.cid for c in dt.CONTENT_CATEGORIES}
    try:
        census_names = set(census_category_names())
    except OSError:
        census_names = set()
    orphan_tpls = sorted(
        t for t in schemas if t not in {c.template for c in dt.CONTENT_CATEGORIES}
    )
    t5_missing_tpl: list[str] = []
    for c in dt.CONTENT_CATEGORIES:
        if c.generated_by:
            script, _, sym = c.generated_by.partition(":")
            ok = (ROOT / script).is_file() and sym in _module_symbols(script)
            if not ok:
                t5_missing_tpl.append(f"{c.cid}: 声明的生成口 {c.generated_by} 解析不到")
            continue
        if c.template is None or not (dts.TEMPLATE_DIR / f"{c.template}.md").is_file():
            t5_missing_tpl.append(f"{c.cid}: 无对应模板（template={c.template!r}）")
        elif c.surface == "code" and c.code_home and not (ROOT / c.code_home).exists():
            t5_missing_tpl.append(f"{c.cid}: code_home 不存在 {c.code_home}")
    no_pages = sorted(
        c.cid
        for c in dt.CONTENT_CATEGORIES
        if c.surface == "md" and not c.generated_by and c.cid not in labels
    )
    unknown_labels = sorted(labels - declared)
    # --- S2 三角闭合（第三边）：页 → 类别 → 模板 链条断掉的页，按类别记红。
    #     「在册模板装载失败（有文件无 schema）」也算接不到——比只查文件存在更严。
    dead_pages: Counter[str] = Counter()
    for p in pages:
        if p.rel in gen_all:
            continue
        want = registered_template(p.category)
        if want is not None and want not in schemas:
            dead_pages[p.category] += 1
    pages_unreachable = [
        f"{cat}: {n} 页落到接不到在册模板的类别（模板未建或装载失败）"
        for cat, n in sorted(dead_pages.items())
    ]

    return {
        "root": root,
        "generated_map": gen_map,
        "generated_all": gen_all,
        "pages": pages,
        "page_total": len(pages),
        "labels": labels,
        "schemas": schemas,
        "t1": t1,
        "t1_by_cat": t1_by_cat,
        "mismatch": mismatch,
        "t2": t2,
        "t2_pages": t2_pages,
        "t3": t3,
        "t3_managed": t3_managed,
        "t3_unmoved": t3_unmoved,
        "t3_pages": t3_pages,
        "t4": t4,
        "t5": {
            "cid_set_matches_census": census_names == declared,
            "census_only": sorted(census_names - declared),
            "registry_only": sorted(declared - census_names),
            "census_count": len(census_names),
            "missing_template": t5_missing_tpl,
            "orphan_templates": orphan_tpls,
            "declared_no_page": no_pages,
            "unknown_labels": unknown_labels,
            "pages_unreachable": pages_unreachable,
        },
        "vocab_size": len(vocab),
    }


def _module_symbols(script: str) -> set[str]:
    tree = ast.parse(_script_file(script).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def report_lines(res: dict[str, object]) -> list[str]:
    """`--report` 与门判据**同一支现算值**（常驻用例逐条比对，防 report 自成一套账）。"""
    t5 = res["t5"]
    gen = res["generated_map"]
    assert isinstance(t5, dict) and isinstance(gen, dict)
    return [
        f"管辖内容页 {res['page_total']}",
        "生成物取数口 " + " / ".join(f"{k}={len(v)}" for k, v in sorted(gen.items())),
        f"G-T1 无模板头且非生成物 = {len(res['t1'])}  按类别 {res['t1_by_cat']}",
        f"G-T1面B 类别↔模板错配页（TEMPLATE_CATEGORY_MISMATCH）= {len(res['mismatch'])}",
        f"G-T2 小节偏离页 = {len(res['t2'])}（比对页 {res['t2_pages']}）",
        (
            f"G-T3 面 A 管辖 {len(res['t3_managed'])} 行 / "
            f"面 B 未迁移 {len(res['t3_unmoved'])} 页（有正文页 {res['t3_pages']}）"
        ),
        f"G-T4 参数不对齐 = {len(res['t4'])}",
        (
            f"G-T5 无模板类别 = {len(t5['missing_template'])} / "
            f"孤儿模板 {len(t5['orphan_templates'])} / "
            f"类别名相等 {t5['cid_set_matches_census']}（CENSUS {t5['census_count']} 名） / "
            f"未归类标签 {t5['unknown_labels']} / 声明无页 {t5['declared_no_page']} / "
            f"三角闭合断链 {len(t5['pages_unreachable'])} 类（页压在无模板类别下）"
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--dump", default="", help="打印某道门的违规前 N 条，如 t1/t2/t3/t4/t5")
    args = ap.parse_args(argv)
    res = compute()
    for ln in report_lines(res):
        print(ln)
    if args.dump:
        bucket: object = res.get(args.dump)
        if args.dump == "t5" and isinstance(bucket, dict):
            bucket = bucket["missing_template"]
        for r in list(bucket or [])[:40]:
            print(f"  {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

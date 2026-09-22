"""内容件总账 `CENSUS.md` 的**薄壳生成器**（席 S16，2026-09-22；席 S116 补两本账对账腿与代码面三数腿；
席 S127 把「已驱动」判据的**形态(b)**——由参数源生成且生成脚本可复现其字节——接到代码面）。

席 S116 的口径变更：**只引用既有取数口**，但两条等式例外（它们是「账目闭合」的自证，不是新判据）：
两本账换算式 `WRITER-UND = G-T1 + MECH_B + TEMPLATE_SRC - MISMATCH` 与代码面三数闭合
`在册 = 已驱动 + 未驱动`。二者不成立 ⇒ 拒绝生成册（fail-closed），详见 `BOOK_*` 注释与 §二之二。

为什么是薄壳（S10 判定成立）
--------------------------
S10 准绳普查（`SEAT-S10.md` §陆-5）实证：简报点名的 `scripts/content_census.py` **不存在**，
而清点职责已被现役两件分摄——`spec_gates_census.compute()`（管辖页/生成物/G-T1…G-T5 现算）与
`doc_template_sync`（类别分派 + front-matter + 参数对齐）。因此本席**不新建第二套算口**，
本文件只做三件事：①调用既有取数口 ②把结果排成 Markdown ③自证「与门逐位相等」。

取数口清单（全部 `import` 现成函数，零复制判据）
----------------------------------------------
- `spec_gates_census.compute()` —— 管辖页、生成物集合、G-T1 未驱动清单、T4 违规、`report_lines()`
- `spec_gates_census.registered_template()` —— 类别 → 在册模板 id（注册表唯一真身）
- `doc_templates.CONTENT_CATEGORIES` —— 类别/模板/面/板块/code_home/reason 的声明源
- `doc_ownership_sync.compute_ownership()` —— 未归属账（该文件自述「取数口只有一份」）
- `physical_placement_census.compute()` —— 未认领账（语义 A）
- `board_doc_sync.load_help_topics() / load_config_fields()` —— 代码面在册件
- `command_catalog.merged_entries() / render()` —— 形态(b) 的**唯一生成口**（席 S127：只 import、只跑两次，
  绝不写盘；与 `command_catalog.py` 自己 `--check` 的比对同一支算法，零复制判据）

唯一新增的一行数据形状：代码面 html/jinja 的 `templates/` 目录分派（照 CENSUS 旧 §一 字面判据），
在册模板/板块/参数一律取注册表，见 §六注与 `SEAT-S16.md`。

用法
----
    python scripts/content_census.py --write    # 重生成 CENSUS.md
    python scripts/content_census.py --check    # 与盘上文件比对（结构+数字，不含生成时间行）
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import dataclasses
import datetime
import hashlib
import io
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import board_doc_sync as bds
import doc_ownership_sync as dos
import doc_template_sync as dts
import doc_templates as dt
import physical_placement_census as ppc
import spec_gates_census as sgc

CENSUS_MD = ROOT / ".superpowers" / "sdd" / "2026-09-22-taxonomy" / "CENSUS.md"
#: 判据真身指纹（读数有效期；复跑若指纹变了，本册所有数字都要重算）。
JUDGING_SOURCES = (
    "scripts/doc_fact_discipline.py",
    "scripts/spec_gates_census.py",
    "scripts/doc_template_sync.py",
    "scripts/doc_templates.py",
)
_TS_PREFIX = "> 生成时间 "
ECHO_PY = "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py"
CONFIG_PY = "plugins/bot_unified_runtime/config.py"
CARD_CODE_CIDS = ("html-card", "jinja-template", "incode-copy-pool", "fstring-card", "help-topic", "config-field")
#: 行级「真违规」导出件（席 S20 的取数副产品）。本席**只读消费**它做覆盖口径对账，不生成、不改它。
TRUE_VIOLATIONS_TSV = ROOT / ".superpowers" / "sdd" / "2026-09-22-taxonomy" / "TRUE-VIOLATIONS.tsv"

# ---------------------------------------------------------------------------
# 席 S116（2026-09-22）：两本账**各起唯一名** + 显式换算式，消灭「G-T1 一名两义」。
# 背景（S111 的 C-2）：旧册 §三 写「未模板驱动数＝门 G-T1 现算，逐位相等」，同时又在页首
# 断言「与门的差只可能是取数时刻之差，不可能是口径之差」。而盘上真有**两把都在跑的尺**：
#   ·甲账 `G-T1`＝门与册同源值（`spec_gates_census.compute()["t1"]`：无模板头 ∧ 非生成物
#     ∧ 非机制(b) 可复现页，且管辖面**先排除模板源 `docs/templates/**`**）；
#   ·乙账 `WRITER-UND`＝写盘口 `doc_template_sync.py --report` 打的「未模板驱动」
#     （= `walk_content_pages()` 全体页 − 带在册模板头页；**含**模板源、**含**机制(b) 生成页）。
# 两本账**逐位相等的断言只对甲账成立**；乙账恒比甲账大 `MECH_B + TEMPLATE_SRC` 枚。
# 本席只**更正散文并给换算式**，不新建第三把尺、不改任何判据、不动任何 `_CEILING/_BASELINE`。
# ---------------------------------------------------------------------------
BOOK_CENSUS = "G-T1"  # 甲账：门 G-T1 / 本册 §三 唯一交付值
BOOK_WRITER = "WRITER-UND"  # 乙账：写盘口 --report 的「未模板驱动」
#: 换算式（乙 = 甲 + 机制(b) + 模板源）；文案在两处（页首 ⚠ 行与 §三）互相注明。
BOOK_CONVERSION = f"{BOOK_WRITER} = {BOOK_CENSUS} + MECH_B + TEMPLATE_SRC"


def root_of(rel: str) -> str:
    """根路径口径（唯一一份）：取首段目录；不含斜杠＝仓库根。"""
    return rel.split("/", 1)[0] if "/" in rel else "（仓库根）"


def tsv_root_counts() -> tuple[dict[str, int], int]:
    """`TRUE-VIOLATIONS.tsv` 首列按根路径计数（只读）。文件缺 ⇒ 空账 + 总数 0，如实标缺件。"""
    try:
        lines = TRUE_VIOLATIONS_TSV.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}, 0
    counts: dict[str, int] = {}
    total = 0
    for ln in lines[1:]:
        cols = ln.split("\t")
        if not ln.strip() or not cols or not cols[0]:
            continue
        counts[root_of(cols[0])] = counts.get(root_of(cols[0]), 0) + 1
        total += 1
    return counts, total


def category_parity() -> tuple[bool, list[str]]:
    """盘上 §一 的名字集合 vs 注册表：**用门自己的解析口** `census_category_names()` 现算，
    本件不复制第二份正则/判据。相等才算「册与注册表同源」；不等即 `--check/--write` 判红。"""
    declared = {c.cid for c in dt.CONTENT_CATEGORIES}
    try:
        on_disk = set(sgc.census_category_names())
    except (OSError, LookupError) as exc:  # 读不到判据源＝红，不静默放行
        return False, [f"读不到盘上 §一（{type(exc).__name__}: {exc}）"]
    msgs: list[str] = []
    if on_disk != declared:
        msgs.append(f"仅盘上有 {sorted(on_disk - declared)} / 仅注册表有 {sorted(declared - on_disk)}")
    return (not msgs), msgs


def _sha16(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16]


def _cell(text: object) -> str:
    """表格单元：竖线是列分隔符，必须消毒；换行折成空格。"""
    return str(text).replace("|", "∣").replace("\n", " ").replace("\r", " ").strip()


def _read_literal(rel_path: Path, name: str) -> object:
    """读某个模块级字面量（登记制账本的既有取数：AST + literal_eval，不 import 执行）。"""
    try:
        tree = ast.parse(rel_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        if any(t.id == name for t in targets):
            try:
                return ast.literal_eval(node.value)  # type: ignore[attr-defined,arg-type]
            except ValueError:
                return None
    return None


def code_surface_items() -> dict[str, tuple[list[str], str]]:
    """代码面在册件（cid → (件清单, 取数口名)）。取数口不可用 ⇒ 空清单 + 诚实注记。

    席 S116 补两枚取数口（`fstring-card` / `incode-copy-pool`）：旧版报「取数口缺」而**其实盘上有
    名册**，只是 `_read_literal` 走 `literal_eval`——名册的值是可调用对象/嵌套容器，必抛
    `ValueError` ⇒ 静默成空账。新取数口改走 AST 结构读（键名／字符串成员），**仍然不执行模块**
    （护栏二：不在源码树写 `__pycache__`）。只加数、不缩任何既有扫描面。"""
    out: dict[str, tuple[list[str], str]] = {}
    for cid in CARD_CODE_CIDS:
        cat = dt.CATEGORIES_BY_ID[cid]
        home = (ROOT / cat.code_home) if cat.code_home else None
        if cid == "help-topic":
            topics = sorted(bds.load_help_topics())
            out[cid] = ([f"{ECHO_PY}::_HELP_ENTRIES::{t}" for t in topics], "board_doc_sync.load_help_topics()")
        elif cid == "config-field":
            fields = sorted(bds.load_config_fields())
            out[cid] = ([f"{CONFIG_PY}::{f}" for f in fields], "board_doc_sync.load_config_fields()")
        elif cid in ("html-card", "jinja-template"):
            html = sorted(
                p.relative_to(ROOT).as_posix()
                for p in (ROOT / "plugins").rglob("*.html")
                if "__pycache__" not in p.parts
            )
            want_templates = cid == "jinja-template"
            picked = [h for h in html if (Path(h).parent.name == "templates") is want_templates]
            out[cid] = (picked, "doc_templates.CONTENT_CATEGORIES[code_home] + rglob('*.html')")
        elif cid == "fstring-card":
            labels = _ast_mapping_keys(home, "_BUILDERS") if home else []
            rows = [f"{cat.code_home}::_BUILDERS::{label}" for label in labels]
            out[cid] = (rows, f"{cat.code_home or '—'}::_BUILDERS（AST 取 dict 键名，不执行）")
        elif cid == "incode-copy-pool":
            rows = _ast_copy_pool_entries(home) if home else []
            out[cid] = (
                rows,
                f"{cat.code_home or '—'} 模块级文案池（AST 读 str 容器成员，不执行）"
                + ("" if rows else "——现扫 0 件，如实挂账"),
            )
        else:  # 兜底：注册表将来新增代码面类别时不得静默丢账
            out[cid] = ([], "现役取数口缺——见 SEAT-S16.md PARKED P-S16-1 / SEAT-S116.md")
    return out


def _ast_container_strings(node: ast.expr | None) -> list[str]:
    """一个 AST 节点里的**字符串字面量成员**（tuple/list/set 直取；dict 取键+值递归）。"""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [el.value for el in node.elts if isinstance(el, ast.Constant) and isinstance(el.value, str)]
    if isinstance(node, ast.Dict):
        out: list[str] = []
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                out.append(k.value)
            out += _ast_container_strings(v)
        return out
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return []


def _ast_mapping_keys(rel_path: Path | None, name: str) -> list[str]:
    """模块级 dict 字面量的**字符串键名**（登记制名册的在册件＝键）。读不到 ⇒ 空表，不编数。"""
    if rel_path is None:
        return []
    try:
        tree = ast.parse(rel_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    for node in tree.body:
        targets, value = _ast_binding(node)
        if not isinstance(value, ast.Dict) or name not in targets:
            continue
        return [k.value for k in value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    return []


def _ast_binding(node: ast.stmt) -> tuple[list[str], ast.expr | None]:
    """模块级绑定（`Assign`/`AnnAssign` 双形态）→（变量名表, 值节点）。"""
    if isinstance(node, ast.Assign):
        return ([t.id for t in node.targets if isinstance(t, ast.Name)], node.value)
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return ([node.target.id], node.value)
    return ([], None)


def _ast_copy_pool_entries(rel_path: Path | None) -> list[str]:
    """代码内文案池在册件（`incode-copy-pool` 取数口）。

    判据＝该文件**模块级**绑定里、值含字符串字面量成员的容器（tuple/list/set/dict 皆可），
    每件记 `文件::变量名::序号`。**不硬编码变量名清单** ⇒ 池改名/新增即自动进账，
    删池即自动出账（同一支 AST 读口，禁第二本账）。"""
    if rel_path is None:
        return []
    try:
        tree = ast.parse(rel_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    out: list[str] = []
    for node in tree.body:
        names, value = _ast_binding(node)
        if value is None:
            continue
        for nm in names:
            members = _ast_container_strings(value)
            if not members:
                continue
            out += [f"{rel_path.relative_to(ROOT).as_posix()}::{nm}::{i}" for i in range(len(members))]
    return out


# ---------------------------------------------------------------------------
# 席 S116 ①②：两本账现算 + 换算式对账（fail-closed）；③代码面三数腿
# ---------------------------------------------------------------------------
def _res_names(res: dict[str, object], key: str) -> list[str]:
    """从 `spec_gates_census.compute()` 结果里取一枚**名字集合键**，形状不对即抛（fail-closed）。

    G-T1 的条目**可能带 `#原因` 尾注**：机制(b) 在册而未当场复现字节等值的生成页记成
    `rel#生成物未当场复现字节等值`。旧版本把整串当 rel 参与分拣 ⇒ 只要有一枚生成页字节漂移，
    §二 的分拣就与门的 `t1_by_cat` 对不上、`render()` 当场 `AssertionError`
    （席 S116 现跑撞到的**存量缺陷**，随本补数腿一并根修：比对用 `rel_of()` 剥尾注，
    **计数仍用原条数＝门的原值**，甲账大小一字不动）。

    席 S156 ③（**只加严**）：旧形态 `res.get(key, ())` 把「取数口少给一个键」静默折成空账 ⇒
    换算式的一个分量**读不出来**时被记成 0、反而冒充对平（＝拿"没数"当"数是 0"）。现改为
    **缺键即抛**（`LookupError`）⇒ 与"形状异常"同权走 fail-closed：宁可不生成册，也不出假对平。"""
    if key not in res:
        raise LookupError(f"取数口缺分量 `{key}` ⇒ 换算式有一项读不出来，拒绝生成册（席 S156 ③ fail-closed）")
    raw = res[key]
    if isinstance(raw, (list, tuple, set, frozenset)):
        return [str(x) for x in raw]
    raise TypeError(f"取数口键 {key} 形状异常：{type(raw).__name__}")


def rel_of(entry: str) -> str:
    """G-T1 条目 → 纯 rel（剥 `#原因` 尾注；与门 `t1_by_cat` 的 `split("#", 1)[0]` 同一形状）。"""
    return entry.split("#", 1)[0]


def _res_pages(res: dict[str, object]) -> list[dts.PageInfo]:
    """管辖页清单（形状校验 + 剥壳，唯一一处）。席 S156 ③：缺键同 `_res_names` ⇒ 抛，不折成空账。"""
    if "pages" not in res:
        raise LookupError("取数口缺分量 `pages` ⇒ 管辖面读不出来，拒绝生成册（席 S156 ③ fail-closed）")
    raw = res["pages"]
    if isinstance(raw, (list, tuple)):
        return [p for p in raw if hasattr(p, "rel")]
    raise TypeError(f"取数口键 pages 形状异常：{type(raw).__name__}")


def writer_book() -> dict[str, int]:
    """乙账 `WRITER-UND`：**只调**写盘口自己的取数口 `doc_template_sync._collect()`，
    与 `--report` 末行 `合计: ... 未模板驱动=` 同一支算法，零复制判据。"""
    pages, schema_errors, schemas = dts._collect()
    driven = sum(1 for p in pages if p.fm and p.fm.template in schemas)
    return {
        "pages": len(pages),
        "driven": driven,
        BOOK_WRITER: len(pages) - driven,
        "schema_errors": len(schema_errors),
    }


#: 席 S156 ②：`reconcile_books()` 实际执法的是**含 MISMATCH 的全式**，而席 S116 在册的
#: `BOOK_CONVERSION` 是 `MISMATCH≡0` 时的**简式**（那枚既有测试锁钉的正是简式原样，本席不改它）。
#: 两个名字并存而不含糊，靠这条全式常量 + 册 §〇 的文字对齐（简报：交付口径钉成文字）。
BOOK_CONVERSION_FULL = f"{BOOK_WRITER} = {BOOK_CENSUS} + MECH_B + TEMPLATE_SRC - MISMATCH"
#: 席 S156 ③：两本账由**两次独立走树**取数（甲＝`sgc.compute()`、乙＝`doc_template_sync._collect()`）。
#: 多席并发时两次之间树在动 ⇒ 换算式会**假性**差几枚（本席 2026-09-22 实跑撞见两例：1427 vs 1426、
#: 1428 vs 1427；同刻重采即对平）。这既不是口径之差、也不许被"重试到绿"糊掉 ⇒ 只认
#: **同一次采样内同时满足「同刻性」与「换算式」**的读数，有限次重采后仍不成立就拒生成册。
SNAPSHOT_ATTEMPTS = 3


def books(res: dict[str, object]) -> dict[str, int]:
    """甲乙两账与换算式各项的现算值（唯一算口；页侧文案与 CLI 输出只引用本函数结果）。

    席 S156 ③：`mismatch` 由「缺键就当空」改成**必读数**（缺键抛 `LookupError` ⇒ 拒绝生成），
    与其余分量同一 fail-closed 形状。"""
    t1_entries = _res_names(res, "t1")
    t1_rels = {rel_of(r) for r in t1_entries}
    b_ok = {rel_of(r) for r in _res_names(res, "b_ok")}
    mismatch = _res_names(res, "mismatch")
    wb = writer_book()
    return {
        BOOK_CENSUS: len(t1_entries),  # 甲账＝门 G-T1 的**条数**（带因记账不重复计数）
        "t1_rels": len(t1_rels),
        BOOK_WRITER: wb[BOOK_WRITER],
        "MECH_B": len(b_ok - t1_rels),
        "TEMPLATE_SRC": len(list(dts.TEMPLATE_DIR.glob("*.md"))),
        "MISMATCH": len(mismatch),
        "census_pages": len(_res_pages(res)),
        "writer_pages": wb["pages"],
        "writer_driven": wb["driven"],
        "writer_schema_errors": wb["schema_errors"],
    }


def reconcile_books(b: dict[str, int]) -> tuple[bool, str]:
    """换算式对账：`WRITER-UND == G-T1 + MECH_B + TEMPLATE_SRC - MISMATCH`。

    今日 `MISMATCH`（类别↔模板错配页）现算为 0，故本式即席 S111 记的「差＝机制(b) + 模板源」；
    保留这一项是因为门 G-T1 **不认**错配页为已驱动、而写盘口认 ⇒ 有人挂错模板时等式会差它。
    不成立 ⇒ 判红并两侧点名（**fail-closed**：宁可不生成册，也不出「两本账冒充同一数」的散文）。"""
    lhs = b[BOOK_WRITER]
    rhs = b[BOOK_CENSUS] + b["MECH_B"] + b["TEMPLATE_SRC"] - b["MISMATCH"]
    detail = (
        f"{BOOK_CENSUS}={b[BOOK_CENSUS]} + MECH_B={b['MECH_B']}"
        f" + TEMPLATE_SRC={b['TEMPLATE_SRC']} - MISMATCH={b['MISMATCH']}"
    )
    if lhs == rhs:
        return True, f"{BOOK_WRITER}={lhs} == {detail}"
    return False, f"两本账换算式不成立：{BOOK_WRITER}={lhs} 而 {detail}={rhs}（差 {lhs - rhs} 枚）"


def contemporaneity(b: dict[str, int]) -> tuple[bool, str]:
    """同刻性自证（席 S156 新增，**不新建尺**）：乙账那一次走树看到的页数，必须等于
    甲账那一次走树的页数 + 模板源枚数（真树现算实证：`writer − census` 的差集逐枚就是
    `docs/templates/*.md`，反向差集为空）。不等 ⇒ 两次读数不是同一棵树 ⇒ 属**取数时刻之差**，
    按名字与口径破裂分开点名（旧形态是两者混成一句「换算式不成立」，谁也判不出该找谁）。"""
    lhs = b["writer_pages"]
    rhs = b["census_pages"] + b["TEMPLATE_SRC"]
    if lhs == rhs:
        return True, (
            f"同刻性 OK：乙账走树 {lhs} 页 == 甲账 {b['census_pages']} + 模板源 {b['TEMPLATE_SRC']}"
        )
    return False, (
        f"两次走树不同刻：乙账 {lhs} 页 vs 甲账 {b['census_pages']} + 模板源 {b['TEMPLATE_SRC']} "
        f"= {rhs}（差 {lhs - rhs} 枚）⇒ 树在动，本采样不可用作交付值"
    )


def snapshot() -> tuple[dict[str, object], dict[str, int], str]:
    """现算一次「同一棵树」的两本账快照（唯一算口；`render()` 与 CLI 只引用它）。

    形状沿用 `main()` 里 `--check` 的既有两次现算哲学：**只放宽"取数时刻之差"这一面**，
    真口径破裂时任何一次采样都同时满足不了同刻性与换算式 ⇒ 循环尽头照旧拒生成。"""
    last = "（未采样）"
    for attempt in range(1, SNAPSHOT_ATTEMPTS + 1):
        res = sgc.compute()
        bk = books(res)
        same_ok, same_msg = contemporaneity(bk)
        conv_ok, conv_msg = reconcile_books(bk)
        if same_ok and conv_ok:
            return res, bk, f"{same_msg} · {conv_msg}（第 {attempt}/{SNAPSHOT_ATTEMPTS} 次采样即对平）"
        last = f"第 {attempt} 次采样：{same_msg} · {conv_msg}"
    raise AssertionError(
        f"两本账在 {SNAPSHOT_ATTEMPTS} 次采样内都不能「同刻 + 换算式」同时成立 ⇒ 拒绝生成册"
        f"（盘上 CENSUS.md 保持原样）。最后一次：{last}"
    )


def code_driver_records(res: dict[str, object]) -> set[str]:
    """代码面「驱动记录」的**形态(a)** 腿（唯一取数口）：既有管辖页里**已挂在册模板头且非生成物**者中，
    凡 rel 不是 `.md`（＝代码件）的记一条。

    今日恒空——`doc_template_sync.walk_content_pages()` 只产 md 页，代码件**结构性进不了管辖面**。
    席 S116 立此腿时，它是代码件**唯一**的驱动判据 ⇒ 五类代码件的「已驱动数」因此为 0。
    席 S127 起 §4③ 的**形态(b)**（生成脚本可复现字节）同权并入，真身＝`code_b_verdict()`；
    两腿相加才是「已驱动」（合并处＝`code_face_ledger()` 一处，禁第二本账）。
    本函数**不因 S127 改动语义**：它只答「有没有走 (a)」，(b) 另算后在合并点求并集。
    """
    t1_rels = {rel_of(r) for r in _res_names(res, "t1")}
    gen = {rel_of(r) for r in _res_names(res, "generated_all")}
    out: set[str] = set()
    for p in _res_pages(res):
        rel = str(p.rel)
        if rel in t1_rels or rel in gen:
            continue
        if p.fm is not None and p.fm.template and not rel.endswith(".md"):
            out.add(rel)
    return out


@dataclasses.dataclass(frozen=True)
class ByteChannel:
    """一类代码件的**形态(b)** 通道声明（§4③ 的第二条达标形态）。

    三条硬判据**同时成立**才认账（少一条即判未驱动并点名原因，见 `code_b_verdict`）：
      ① `produce()` 连跑两次**字节等值** ⇒ 生成口本身可复现（不幂等＝拿不稳定说成稳定）；
      ② 生成结果与**盘上产物当场**字节等值 ⇒ 在册的这份产物就是生成口今天产出的那份
         （过期即不认，与 md 面机制(b) 的「生成物在册未当场复现字节等值」同形同判）；
      ③ 每件在册件在生成物里有**自己的锚点行**（`anchor`）⇒ **逐件**覆盖，不按族蒙。
    """

    cid: str
    command: str
    artifact: str
    produce: Callable[[], tuple[str, str]]
    anchor: Callable[[str], str]
    param_source: str


def _produce_help_catalog() -> tuple[str, str]:
    """`scripts/command_catalog.py` 的**只读双跑**：与该脚本 `--check` 同一支算法（`merged_entries()`
    + `render()`），零复制判据、绝不写盘（写盘归它自己的 `--write`，本席不越界）。"""
    import command_catalog as cm

    with contextlib.redirect_stdout(io.StringIO()):
        merged = cm.merged_entries()
        first = cm.render(merged)
        second = cm.render(cm.merged_entries())
    return first, second


def _help_topic_anchor(item: str) -> str:
    """`echo.py::_HELP_ENTRIES::<topic>` → 生成目录里的 `## <topic>` **精确整行**（防子串吞并：
    「天气」不得靠「天气预报」那一节蒙混过关）。"""
    return f"## {item.rsplit('::', 1)[-1]}"


#: 形态(b) 通道在册表（**唯一一份**，登记制：只收「盘上真存在生成脚本、且脚本产出的就是该内容的字节」的类）。
#: 无通道的类**不是豁免**，而是判「只能走形态(a)」并给工单——见 `B_WORK_ORDERS` 与册 §二之三。
CODE_B_CHANNELS: tuple[ByteChannel, ...] = (
    ByteChannel(
        cid="help-topic",
        command="python scripts/command_catalog.py --check（写盘版换 --write）",
        artifact="docs/command-catalog.md",
        produce=_produce_help_catalog,
        anchor=_help_topic_anchor,
        param_source="echo.py `_HELP_ENTRIES`/`_HELP_ENTRY_META`（AST 取源码片段就地 exec，不 import 插件包）",
    ),
)
CODE_B_BY_CID: dict[str, ByteChannel] = {ch.cid: ch for ch in CODE_B_CHANNELS}

#: 无通道类的最小改造工单（准绳一：只判「只能走 (a)」/「须换机制」，**绝不判「不适合模板化」**）。
#: 每条给「需要什么参数源」＋「谁提供」＋「补上后如何自动变 (b) 达标」，由 §二之三 逐行投影。
B_WORK_ORDERS: dict[str, str] = {
    "config-field": (
        "真身与取数口（席 S169 复算钉死）：在册件＝`plugins/bot_unified_runtime/config.py` 里 `Config` 类的 "
        "pydantic 字段全集（计数以取数口现算与机器册 `docs/auto-facts.md` 为准），唯一取数口＝"
        "`board_doc_sync.load_config_fields()`（正则 `^\\s{4}(bot_[a-z0-9_]+)\\s*[:=]`、去重排序）"
        "⇒ 可复算判据＝直接跑该函数。**不是** catalog 行——catalog 是这些人写字段的说明面。"
        "(b) 今日不通的实证缺口＝**逐键说明无码上真身**：`config.py` 全档 `description=` 现算 0 命中，"
        "说明/合法值/作用/关系列全是人写散文；`docs/config-catalog-full.md` **无机器段**"
        "（`<!-- BOARD-AUTO:BEGIN -->` 与 `<!-- TEMPLATE-AUTO:BEGIN -->` 两枚标记现算 0 命中），"
        "其覆盖由 `tests/test_doc_sync_gates.py::test_config_catalog_covers_config_fields` 以"
        "「字段全集 − KNOWN_MISSING 白名单」执法 ⇒ catalog 全表与 config.py 字段全集是两本可漂移的账，"
        "生成口须先把白名单归并进真登记再谈幂等。最小改造三步＝①把 `config.py` 各字段的 "
        "`Field(description=…)` 升为逐键说明唯一真身（provider：config 域 owner，各波加键时随批写）；"
        "②「✅热更/🟡需重启/❌无热改面」由 `domains/chat_reply/runtime/settings.py` 的 "
        "`SETTABLE_KEYS`/`RESTART_REQUIRED_KEYS` 两表现读派生（两枚表存在性本席现算已核，"
        "provider：runtime/settings owner）；③catalog 立机器段并新增唯一写口"
        "（provider：docs 域 owner 开机器段＋scripts 面新增生成脚本），①②③齐了才在 `CODE_B_CHANNELS` "
        "登记（produce＝该写口 `--check` 同算法、anchor＝逐键精确整行）逐件认 (b)。"
        "①未落地前，「可由 config.py 派生的骨架」（键名/类型/缺省值/三档标记）**永远不等于盘上产物字节**"
        " ⇒ 硬走 (b) 必被「未当场复现」腿拿下（本席注毒用例 "
        "`test_s169_poison_sourceless_family_forced_into_b_is_red` 锁死，别退化成放行）。"
        "**不许**为过账把说明写成空串或占位（＝发明数据源）。"
    ),
    "incode-copy-pool": (
        "真身（席 S169 复算）：在册件＝注册 `code_home` 文件 "
        "`plugins/bot_unified_runtime/domains/chat_reply/capabilities/user_copy.py` 的模块级字符串容器成员"
        "（逐枚计），唯一取数口＝本件 `\\_ast_copy_pool_entries()`（AST 结构读、不执行模块）；"
        "**无独立登记表**——变量名→用途/语气档这类结构化参数不存在，取数口的「名册」就是模块级绑定本身。"
        "本族语料整体散在在册 `code_home` 之外（本席现算已证：错误卡 `_HELP_TEXT`/`_FALLBACK_HELP_TEXT` "
        "住 `domains/ops/monitor/error_report.py`，`domains/chat_reply/capabilities/chat.py` 只余"
        "「五池纪律同构」注释）；扩扫描面＝改 `code_home`，那在公共只读面 `scripts/doc_templates.py` 里"
        " ⇒ **交回主会话工单**，本席不动。"
        "(b) 今日不通：池成员原文虽可由代码派生，但**盘上没有该族的 md 产物、也没有唯一写命令**"
        " ⇒ ByteChannel 三条腿无处实例化；「用途/语气档」参数源仍需人给，**不许**把散文改写当通道。"
        "最小改造＝①B03 人格对话域 owner（provider）给 user_copy.py 立 AST 可读的登记表"
        "（变量名／成员序号 → 用途／语气档）；②同 owner 新增「池 → 逐枚一节（变量名／序号／原文／消费点）」"
        "的生成口与产物（幂等以连跑 `cmp` 等值证明，产物先落盘再谈通道）；③两件齐了才在 "
        "`CODE_B_CHANNELS` 登记按 (b) 逐件认账。替代方案＝走 (a)：给每枚池补结构化参数块、由 G-T4 对齐——"
        "「用途」只能人来给，机器造不出来，故本类今日既无 (a) 也无 (b)，挂账不动。"
    ),
    "jinja-template": (
        "参数源＝模板头部注释块的 schema（SPEC-TARGETS §2-A 已如此规定）＋ `theme_tokens.py` 登记表；"
        "缺的生成口＝「schema → 一张契约页」（每模板一节），幂等后按 (b)（provider：B08 渲染域 owner）。"
        "现状 `tests/test_rendering_contract.py` 是**断言形**不是**投影形** ⇒ 它绿不代表内容字节可复现，不得充当通道。"
    ),
    "fstring-card": (
        "参数源＝`_BUILDERS` 名册（AST 已可读出键）＋ `docs/design/fstring-card-dom-spec.md` 规格；"
        "缺的生成口＝名册 → 逐卡一节（builder 坐标／DOM 骨架／契约字段），幂等后按 (b)（provider：B08 渲染域 owner）。"
    ),
    "html-card": (
        "该类现扫 0 件（`code_home` 下非 `templates/` 的 html 为空）⇒ 无件可驱动；"
        "工单同 `jinja-template`（同一支契约页生成口即可覆盖两族），provider：B08 渲染域 owner。"
    ),
}


@dataclasses.dataclass(frozen=True)
class BVerdict:
    """一类代码件的形态(b) 判决（含三条腿的逐腿结果，册 §二之三 直接投影本结构）。"""

    cid: str
    command: str
    artifact: str
    idempotent: bool
    disk_equal: bool
    covered: int
    total: int
    driven: frozenset[str]
    reason: str
    channel: bool = False


def code_b_verdict(cid: str, its: list[str]) -> BVerdict:
    """单类代码件的 (b) 判决（唯一算口；三数腿与本册 §二之二/§二之三 都只引用它，不各算一套）。

    失败面逐条**点名且不静默放行**：无通道／生成口抛异常／两次生成不等值／盘上产物过期或不可读／
    该件在生成物里没有自己的锚点行 —— 五种都记未驱动。"""
    ch = CODE_B_BY_CID.get(cid)
    if ch is None:
        return BVerdict(
            cid,
            "—（盘上无生成该内容的脚本）",
            "—",
            False,
            False,
            0,
            len(its),
            frozenset(),
            "无生成通道 ⇒ 该类只能走形态(a)（工单见 §二之三末）",
        )
    if not its:
        return BVerdict(
            cid, ch.command, ch.artifact, False, False, 0, 0, frozenset(),
            "通道在册、该类现扫 0 件 ⇒ 无可驱动对象（既非达标也非欠账）", channel=True,
        )
    try:
        first, second = ch.produce()
    except (
        OSError, ValueError, TypeError, KeyError, IndexError, AttributeError,
        NameError, SyntaxError, RuntimeError, RecursionError,
    ) as exc:  # 生成口炸＝fail-closed 判未驱动并点名，绝不退化成旧免检行为；清单外的异常照旧冒出来
        return BVerdict(
            cid, ch.command, ch.artifact, False, False, 0, len(its), frozenset(),
            f"生成口不可用 ⇒ 判未驱动（{type(exc).__name__}: {exc}）", channel=True,
        )
    if first != second:
        return BVerdict(
            cid, ch.command, ch.artifact, False, False, 0, len(its), frozenset(),
            f"生成口不幂等：两次生成字节不等（{len(first)} vs {len(second)}）⇒ 判未驱动", channel=True,
        )
    try:
        disk = (ROOT / ch.artifact).read_text(encoding="utf-8")
    except OSError as exc:
        return BVerdict(
            cid, ch.command, ch.artifact, True, False, 0, len(its), frozenset(),
            f"盘上产物不可读（{type(exc).__name__}: {exc}）⇒ 判未驱动", channel=True,
        )
    lines = set(first.splitlines())
    hit = frozenset(it for it in its if ch.anchor(it) in lines)
    if disk != first:
        return BVerdict(
            cid, ch.command, ch.artifact, True, False, len(hit), len(its), frozenset(),
            "盘上产物未当场复现生成字节（过期）⇒ 判未驱动，须跑该族唯一生成命令", channel=True,
        )
    miss = len(its) - len(hit)
    reason = (
        "(b) 达标：两次生成字节等值 · 盘上当场复现 · 逐件锚点全命中"
        if not miss
        else f"(b) 仅部分达标：{miss} 枚在册件在生成物里无锚点 ⇒ 只认有锚者，其余照挂未驱动账"
    )
    return BVerdict(
        cid, ch.command, ch.artifact, True, True, len(hit), len(its), hit, reason, channel=True
    )


def code_b_records(items: dict[str, tuple[list[str], str]]) -> dict[str, BVerdict]:
    """全类 (b) 判决（`code_b_verdict()` 的批投影，供 §二之三 一行一类地印出）。"""
    return {cid: code_b_verdict(cid, its) for cid, (its, _src) in items.items()}


def template_family(template_id: str | None) -> str:
    """模板 id → 族名（`card-*`/`persona-*` 归族，其余即本名）。派生自注册表，不硬编码类别清单。"""
    tid = template_id or "—"
    if tid == "persona" or tid.startswith("persona-"):
        return "persona-*"  # 注册表里 `persona`（裸名）与 `persona-*` 同族，漏一枚即整族少算
    if tid.startswith("card-"):
        return "card-*"
    return tid


@dataclasses.dataclass(frozen=True)
class FaceRow:
    """管辖面一行；三数闭合（`在册 == 已驱动 + 未驱动`）由 `render()` 断言执法。

    席 S127：`driven` 从「单一形态」升成**两形态之和**（`driven_a` 走 front-matter 管辖面、
    `driven_b` 走生成脚本可复现字节），两腿各留底数，册里可逐腿追。**闭合式不变。**"""

    family: str
    cid: str
    surface: str
    registered: int
    driven: int
    undriven: int
    source: str
    verdict: str
    driven_a: int = 0
    driven_b: int = 0
    b_command: str = "—"
    b_covered: int = 0
    b_total: int = 0


def code_face_ledger(
    res: dict[str, object], per_cat_md: dict[str, dict[str, int]], items: dict[str, tuple[list[str], str]]
) -> list[FaceRow]:
    """代码件五族的**管辖面三数**（在册／已驱动／未驱动）——让 #22 的账第一次存在。

    两类分开点名、绝不混成一个数：
      · `surface=code`＝管辖对象是**代码件**，`已驱动 = driven_a + driven_b` 两腿相加：
        (a) 腿由 `code_driver_records()` 现算（代码件进 md 管辖面且挂在册模板头，今日结构性为空），
        (b) 腿由 `code_b_verdict()` 现算（§4③「生成脚本可复现字节」，席 S127 接入）；
      · `surface=md` ＝简报点名的 `persona-*` 族在注册表里 `surface=="md"`（**管辖对象是 md 页**），
        其数取既有 §二 同一支 `per_cat_md`，不另算一套——这是简报口径与注册表的差，如实标注。
        **(b) 通道只作用于 `surface=="code"` 的行**：md 腿的数字（含甲账 `G-T1`）本席一律不碰。
    只加数：本函数不删除、不缩小任何既有扫描面。"""
    driven_rels = code_driver_records(res)
    rows: list[FaceRow] = []
    for c in dt.CONTENT_CATEGORIES:
        if c.surface == "code":
            its, source = items.get(c.cid, ([], "取数口缺"))
            bv = code_b_verdict(c.cid, its)
            driven_a = sum(1 for it in its if it in driven_rels)
            driven_b = sum(1 for it in its if it not in driven_rels and it in bv.driven)
            driven = driven_a + driven_b
            if not its:
                verdict = f"现扫 0 件（类别在册防将来自由发挥）；{bv.reason}"
            elif driven == 0:
                verdict = f"0 驱动 ⇒ 须换机制：{bv.reason}"
            else:
                legs: list[str] = []
                if driven_a:
                    legs.append(f"形态(a) 代码件进管辖面 {driven_a} 枚")
                if driven_b:
                    legs.append(f"形态(b) 生成脚本可复现字节 {driven_b} 枚（唯一生成命令 `{bv.command}`）")
                verdict = "已有驱动通道（" + "；".join(legs) + f"）；{bv.reason}"
            rows.append(
                FaceRow(
                    family=template_family(c.template),
                    cid=c.cid,
                    surface="code",
                    registered=len(its),
                    driven=driven,
                    undriven=len(its) - driven,
                    source=source or "取数口缺",
                    verdict=verdict,
                    driven_a=driven_a,
                    driven_b=driven_b,
                    b_command=bv.command,
                    b_covered=bv.covered,
                    b_total=bv.total,
                )
            )
        elif template_family(c.template) == "persona-*":
            st = per_cat_md.get(c.cid, {})
            reg = int(st.get("件数", 0))
            drv = int(st.get("已驱动", 0))
            rows.append(
                FaceRow(
                    family="persona-*",
                    cid=c.cid,
                    surface="md",
                    registered=reg,
                    driven=drv,
                    undriven=reg - drv,
                    source="walk_content_pages()（md 面）",
                    verdict="非代码件：注册表 surface=md ⇒ 本就有甲账账，单列以免与代码件混算",
                )
            )
    return rows


def family_rollup(rows: list[FaceRow]) -> dict[str, tuple[int, int, int]]:
    """按族汇总三数（族内各类相加；一个类别只挂一枚模板 id ⇒ 不跨族重复计件）。"""
    agg: dict[str, list[int]] = {}
    for r in rows:
        a = agg.setdefault(r.family, [0, 0, 0])
        a[0] += r.registered
        a[1] += r.driven
        a[2] += r.undriven
    return {k: (v[0], v[1], v[2]) for k, v in agg.items()}
def _category_rows() -> list[str]:
    """§一 类别名：**逐枚在册类别一行**，全部由 `doc_templates.CONTENT_CATEGORIES` 现算投影，
    本册不抄第二份名字表（席 S73 收掉旧的「board-l1/l2/l3 合一行」手写形状）。
    两列形状由 `spec_gates_census.census_category_names()` 的正则钉死——
    第二列不得出现裸 `|`（`_cell()` 已折成 `∣`），也不得多出第三列（多了门就解析不到名字）。"""
    rows: list[str] = []
    for c in dt.CONTENT_CATEGORIES:
        sigils = [f"template=`{c.template or '—'}`", f"surface=`{c.surface}`", f"板块=`{c.owner_board}`"]
        if c.generated_by:
            sigils.append(f"生成口=`{c.generated_by}`")
        if c.code_home:
            sigils.append(f"声明源=`{c.code_home}`")
        rows.append(f"| {_cell(c.cid)} | {' · '.join(sigils)} · reason={_cell(c.reason)} |")
    return rows


def render() -> tuple[str, dict[str, object]]:
    # 两本账对账（席 S116 ①）：换算式不成立即拒绝出册——fail-closed，宁可不写也不出「两本账
    # 冒充同一数」的散文。甲乙两账的现算值只由 `books()` 一处算，页侧全部引用它。
    # 席 S156 ③：把「一次 compute + 一次 _collect」的两处独立走树收进 `snapshot()`——同一次采样内
    # 必须**同时**满足同刻性与换算式才认账（缺键即抛；三次采不到对平快照 ⇒ 抛 AssertionError 拒生成）。
    res, bk, snapshot_msg = snapshot()
    reconcile_ok, reconcile_msg = reconcile_books(bk)
    assert reconcile_ok, snapshot_msg
    pages: list[dts.PageInfo] = _res_pages(res)  # 席 S156：改走同一支形状校验口（旧 `list(res["pages"])` 是 mypy 老错）
    schemas: dict[str, dts.Schema] = res["schemas"]  # type: ignore[assignment]
    gen_all: set[str] = {rel_of(r) for r in _res_names(res, "generated_all")}
    # G-T1 条目可带 `#原因` 尾注（机制(b) 在册未复现）⇒ 分拣用剥注 rel，计数用门原值（席 S116 根修）
    t1: set[str] = {rel_of(r) for r in _res_names(res, "t1")}
    _t1bc: object = res.get("t1_by_cat")
    if not isinstance(_t1bc, dict):  # 席 S156 ③：缺键/形状不对都抛，不再靠 `type: ignore` 蒙过对账
        raise TypeError(f"取数口键 t1_by_cat 形状异常：{type(_t1bc).__name__}")
    t1_by_cat: Counter[str] = Counter({str(k): int(v) for k, v in _t1bc.items()})
    ledger = dos.compute_ownership()
    placement = ppc.compute()
    code_items = code_surface_items()

    board_of: dict[str, tuple[str, str]] = {}
    dir_board: dict[str, tuple[str, str]] = {}
    for e in ledger.entries:
        if not e.path:
            continue
        if e.path.endswith("/"):
            dir_board[e.path] = (e.board, e.fid)  # 目录级条目保留尾斜杠
        else:
            board_of[e.path] = (e.board, e.fid)

    def board_for(rel: str) -> tuple[str, str]:
        """板块归属：docs/boards 路径直取，其余查归属取数口（唯一真身）。"""
        if rel.startswith("docs/boards/"):
            parts = rel.split("/")
            return (parts[1].split("-")[0] if len(parts) > 1 and parts[1].startswith("B") else "未归属", "—")
        hit = board_of.get(rel)
        if hit is None and dir_board:
            prefix = next(
                (k for k in sorted(dir_board, key=len, reverse=True) if rel.startswith(k)), ""
            )
            hit = dir_board.get(prefix)
        if hit is None or not hit[0]:
            return ("未归属", "—")
        return hit

    def spec_of(p: dts.PageInfo) -> str:
        fm = p.fm
        auto = "y" if (dts.TPL_AUTO_BEGIN in p.text or bds.AUTO_BEGIN in p.text) else "n"
        return (
            f"fm={'有' if fm else '无'} · template={_cell(fm.template) if fm and fm.template else '—'} · "
            f"params={len(fm.params) if fm else 0} · H2={len(sgc.headings(p.text))} · auto={auto} · "
            f"类别=`{p.category}`"
        )

    def driven_state(p: dts.PageInfo) -> str:
        if p.rel in t1:
            return "否（生成物在册未当场复现）" if p.rel in gen_all else "否"
        return "生成器所有" if p.rel in gen_all else "是"

    def template_id_of(p: dts.PageInfo) -> str:
        want = sgc.registered_template(p.category)
        got = p.fm.template if (p.fm and p.fm.template in schemas) else None
        if got:
            return got
        return f"—（在册应套 {want}）" if want else "—（该类由生成器/代码面所有）"

    def params_state_of(p: dts.PageInfo) -> str:
        codes = sorted({v.split(" ", 1)[0] for v in p.violations if v.split(" ", 1)[0] in sgc.T4_CODES})
        if p.rel in gen_all:
            return "不适用（生成器所有）"
        if p.rel in t1:
            return "未驱动·不适用"
        return "齐全" if not codes else "不齐:" + ",".join(codes)

    per_cat_md: dict[str, dict[str, int]] = {}
    detail: dict[str, list[tuple[str, str]]] = {}
    for p in sorted(pages, key=lambda x: (x.category, x.rel)):
        st = per_cat_md.setdefault(p.category, {"件数": 0, "生成物": 0, "已驱动": 0, "未驱动": 0, "参数不齐": 0})
        st["件数"] += 1
        st["生成物"] += 1 if p.rel in gen_all else 0
        # 席 S116 根修：分拣**只认 t1**（门的 G-T1 含「生成物在册未当场复现字节等值」的带因条目，
        # 旧版先验地 `not in gen_all` ⇒ 一旦有生成页漂移，本册 §二 就对不上门并 `AssertionError`
        # ——现跑实证 1 枚 `doc-misc` 生成页漂移即崩，`--write/--check` 两条出口同挂）。
        st["未驱动"] += 1 if p.rel in t1 else 0
        st["已驱动"] += 1 if p.rel not in t1 else 0
        st["参数不齐"] += 1 if params_state_of(p).startswith("不齐") else 0
        board, fid = board_for(p.rel)
        detail.setdefault(p.category, []).append(
            (
                p.rel,
                (
                    f"| {_cell(p.rel)} | {_cell(p.category)} | {_cell(board)} | {_cell(fid)} | "
                    f"{_cell(spec_of(p))} | {_cell(driven_state(p))} | {_cell(template_id_of(p))} | "
                    f"{_cell(params_state_of(p))} |"
                ),
            )
        )
    for cat in {p.category for p in pages}:
        assert per_cat_md[cat]["未驱动"] == t1_by_cat.get(cat, 0), f"{cat} 未驱动数与门 G-T1 不等"
    assert sum(s["未驱动"] for s in per_cat_md.values()) == bk[BOOK_CENSUS], "本册未驱动合计 ≠ 门 G-T1"
    assert bk["t1_rels"] == bk[BOOK_CENSUS], "G-T1 条目里有同一 rel 两条 ⇒ 本册分拣会漏计，须交回门 owner"
    assert bk[BOOK_CENSUS] == len(t1), f"甲账现算值 {bk[BOOK_CENSUS]} ≠ 门 G-T1 {len(t1)}（两算口漂移）"
    # 代码件五族管辖账（席 S116 ③）：在册／已驱动／未驱动三数第一次成账。
    face_rows = code_face_ledger(res, per_cat_md, code_items)
    fams = family_rollup(face_rows)
    assert all(r.registered == r.driven + r.undriven for r in face_rows), "代码面三数不闭合（在册≠已驱动+未驱动）"

    ts = datetime.datetime.now(datetime.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
    L: list[str] = []
    A = L.append
    A("# 内容件总账（CENSUS）— 由 `scripts/content_census.py` 现算生成（席 S16 同源波）")
    A("")
    A(f"{_TS_PREFIX}{ts}；**本版全部数字由 `spec_gates_census.compute()` 现算**，无一手抄。")
    A("> 复跑：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 "
      "../ChatBot_Runtime/venv/Scripts/python.exe scripts/content_census.py --write`")
    A("> 体检（盘上文件与本册现算是否一致）：同命令换 `--check`；门侧对账：`scripts/spec_gates_census.py --report`")
    A("> 判据真身指纹（本册数字的有效期凭据，指纹变即须重算）："
      + " · ".join(f"`{rel} sha256[:16]={_sha16(rel)}`" for rel in JUDGING_SOURCES))
    A("> ⚠ 本树多席并发，快照式读数。**盘上跑着两把都在算「未模板驱动」的尺，二者口径不同、"
      "不可互换名**（席 S116 更正旧断言；旧版写「不可能是口径之差」是**错的**——错在把乙账当成甲账）：")
    A(f"> 　· 甲账 `{BOOK_CENSUS}`＝本册与门 G-T1 同源值（`spec_gates_census.compute()['t1']`），"
      "**与门逐位相等**（同一支 `compute()`），管辖面**不含**模板源 `docs/templates/**`、"
      "**不含**机制(b) 可复现生成页；")
    A(f"> 　· 乙账 `{BOOK_WRITER}`＝写盘口 `doc_template_sync.py --report` 末行的「未模板驱动」，"
      "全体管辖页（**含**模板源、**含**机制(b) 生成页）减带在册模板头者；")
    A(f"> 　· 换算式（现算，本册 §三 与门侧报告同源）：`{BOOK_CONVERSION}` —— 席 S111 记的"
      "「1160 × 1409 差 249＝机制(b) 227 + 模板源 22」即此式的当时读数；"
      "`MECH_B` 与 `TEMPLATE_SRC` 都是活数（S111 当时 227+22，本册现算见 §三），"
      "**差值随现算漂移属正常，不是口径之差被推翻**。旧版 1874 那类**陈旧账**的差因账见 "
      "`.superpowers/sdd/2026-09-22-taxonomy/SEAT-S16.md`；两本账的名与式由 "
      "`content_census.BOOK_CENSUS/BOOK_WRITER/BOOK_CONVERSION` 一处声明，别处只引用。")
    A("> 　· 交付口径：**C2/C4 的交付值取甲账 `G-T1`**（门执法的就是它，取乙账会把 "
      f"{bk['MECH_B']} 枚「写盘口当场可复现的生成页」与 {bk['TEMPLATE_SRC']} 枚「模板文件自身」"
      "记成债 ⇒ 双重计账并把工具本身当债务）；"
      f"乙账 `{BOOK_WRITER}` 只作辅助核对值。理由与实跑数见 §三。")
    A("")
    A("## 〇、交付口径（席 S156 钉成文字：C2/C4 各用哪一本 · 换算式与各分量现值 · 读不出来怎么办）")
    A("")
    A("| 交付项 | 用哪一本账 | 现算值 | 唯一取数口 | 复跑命令 |")
    A("|---|---|---|---|---|")
    A(
        f"| **C2** G-T1 未模板驱动 | **甲账 `{BOOK_CENSUS}`** | **{bk[BOOK_CENSUS]}** | "
        "`spec_gates_census.compute()['t1']` 的**条数**（带 `#原因` 尾注不重复计） | "
        "`BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe scripts/spec_gates_census.py --report` |"
    )
    A(
        f"| **C4** CENSUS 未模板驱动 | **同一本甲账 `{BOOK_CENSUS}`**（C4 与 C2 **逐位相等**＝同一支数，"
        f"不是两把尺对上了） | **{bk[BOOK_CENSUS]}** | `content_census.books()['G-T1']`（就是上一行那一支，"
        "本件零复制判据） | "
        "`BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe scripts/content_census.py --check; echo rc=$?` |"
    )
    A(
        f"| 乙账 `{BOOK_WRITER}` | **不作交付值**，只作辅助核对 | {bk[BOOK_WRITER]} | "
        "`doc_template_sync._collect()`（＝写盘口 `--report` 末行同一支算法） | "
        "`BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe scripts/doc_template_sync.py --report` |"
    )
    A("")
    A(
        f"- **换算式（`reconcile_books()` 实际执法的全式，任一项不成立 ⇒ 拒绝生成册）**："
        f"`{BOOK_CONVERSION_FULL}`"
    )
    A(
        f"- 各分量**现值**：`MECH_B={bk['MECH_B']}`（乙账多算的「机制(b) 当场可复现生成页」） · "
        f"`TEMPLATE_SRC={bk['TEMPLATE_SRC']}`（乙账多算的 `docs/templates/**` 模板文件自身） · "
        f"`MISMATCH={bk['MISMATCH']}`（类别↔模板错配页：甲账**不认**其已驱动、乙账认 ⇒ 有人挂错模板时等式差它） · "
        f"两账之差实算 `{bk[BOOK_WRITER] - bk[BOOK_CENSUS]}` 枚，残差 0。"
    )
    A(
        f"- 简式与全式的对齐（席 S116 在册名 `BOOK_CONVERSION` ＝ `{BOOK_CONVERSION}`，"
        f"**不含** `MISMATCH`；它是 `MISMATCH≡0` 时的退化形。两者不一致的唯一来源就是 `MISMATCH≠0`，"
        f"**届时一律以全式为准**（本席现算 `MISMATCH={bk['MISMATCH']}`）。简式常量由既有测试锁钉死，本席未改。"
    )
    A(f"- **同刻性自证（席 S156 新增）**：{snapshot_msg}")
    A(
        "- **分量读不出来时的行为（席 S156 ③，fail-closed）**：`_res_names()/_res_pages()` 对 "
        "`t1 / b_ok / mismatch / pages` **缺键即抛 `LookupError`**（旧形态 `res.get(key, ())` 会把"
        "「读不出来」静默折成 0 并冒充对平）；同刻性与换算式在 `SNAPSHOT_ATTEMPTS=3` 次采样内"
        "都不能**同时**成立 ⇒ `render()` 抛 `AssertionError`、`--write/--check` 非零退出、"
        "**盘上 CENSUS.md 保持原样**。重试只放宽「取数时刻之差」这一面：真口径破裂时任何一次采样"
        "都同时满足不了两条，循环尽头照旧拒生成。"
    )
    A(
        f"- 页侧辅助数：甲账走树管辖页 **{bk['census_pages']}** · 乙账走树 **{bk['writer_pages']}** "
        f"（其中带在册模板头 {bk['writer_driven']}）· 写盘口 schema 错误 {bk['writer_schema_errors']} 条。"
    )
    A("")
    A("## 一、口径（类别集合＝注册表投影；判据真身＝`scripts/doc_templates.py`）")
    A("")
    A("| 内容类别 | 在册形状（模板 / 面 / 板块 / 生成口 / 声明源 / 在册理由） |")
    A("|---|---|")
    L.extend(_category_rows())
    A("")
    A("> 本表由 `doc_templates.CONTENT_CATEGORIES` 现算投影；类别名集合与 `doc_templates` 的相等性由 "
      "`spec_gates_census.census_category_names()` + G-T5 执法——**不在本册手改类别名**，要改就改注册表。"
      "本件 `--write/--check` 两条出口都用同一个解析口回读盘上 §一 并与注册表比对，不等即非零退出（席 S73）。")
    A("")
    # —— 席 S73 ②：把「tsv／本册各自扫了哪些根路径」写成**册内显式口径声明**，且**现算**与实扫一致。
    #     S46 报的未声明面：行级 `TRUE-VIOLATIONS.tsv` 不含 `.superpowers/**`，而本册管它 764 页——
    #     差集不写出来，就是「拿一本账的绿冒充另一本账」。差集由数据派生，不硬编码根名。
    md_roots: Counter[str] = Counter(root_of(p.rel) for p in pages)
    code_roots: Counter[str] = Counter()
    for _items, _src in code_items.values():
        for _it in _items:
            code_roots[root_of(_it.split("::", 1)[0])] += 1
    tsv_counts, tsv_total = tsv_root_counts()
    all_roots = sorted(set(md_roots) | set(code_roots) | set(tsv_counts))
    A("### 一之二、根路径覆盖口径（现算；两本账各扫了哪些根，不许再靠散文默认）")
    A("")
    A("| 根路径 | 本册 md 管辖面（页） | 本册代码面在册件 | `TRUE-VIOLATIONS.tsv` 行级 | 该根两侧是否同权 |")
    A("|---|---|---|---|---|")
    for r in all_roots:
        in_md, in_code, in_tsv = r in md_roots, r in code_roots, r in tsv_counts
        both = (in_md or in_code) and in_tsv
        verdict = "两侧都扫" if both else "仅生成物面扫·行级 tsv 未扫（债，见下）"
        A(
            f"| {_cell(r)} | {md_roots.get(r, 0)} | {code_roots.get(r, 0)} | "
            f"{tsv_counts.get(r, 0)} | {_cell(verdict)} |"
        )
    only_book = sorted((set(md_roots) | set(code_roots)) - set(tsv_counts))
    only_tsv = sorted(set(tsv_counts) - (set(md_roots) | set(code_roots)))
    A("")
    A(
        f"> **口径声明（现算，非手抄）**：本册管辖面覆盖根 "
        f"`{'、'.join(sorted(set(md_roots) | set(code_roots))) or '（空）'}`；"
        f"行级导出件 `TRUE-VIOLATIONS.tsv`（{tsv_total} 行）覆盖根 `{('、'.join(sorted(tsv_counts))) or '（缺件）'}`。"
        f"仅本册有 = `{('、'.join(only_book)) or '无'}`；仅 tsv 有 = `{('、'.join(only_tsv)) or '无'}`。"
        "差集是**事实登记不是豁免**：清扫/转换批消费 tsv 时，`仅本册有` 的那些根必须另找行级清单，"
        "不得据本册的页数账声称「行级也已扫」。"
    )
    A("")
    A("## 二、汇总表（按类别；全部现算）")
    A("")
    A("| 类别 | 面 | 件数 | 生成物 | 已模板驱动 | 未模板驱动 | 参数不齐页 | 在册模板 id |")
    A("|---|---|---|---|---|---|---|---|")
    code_total = 0
    for c in dt.CONTENT_CATEGORIES:
        md_row = per_cat_md.get(c.cid)
        items = code_items.get(c.cid, ([], ""))[0]
        code_total += len(items)
        if md_row is None:
            A(
                f"| {_cell(c.cid)} | code | {len(items) if items else '取数口缺'} | 0 | 0 | "
                f"{'见 §二之二（代码面三数）' if items else '—'} | — | {_cell(c.template or '—')} |"
            )
        else:
            A(
                f"| {_cell(c.cid)} | md | {md_row['件数']} | {md_row['生成物']} | {md_row['已驱动']} | "
                f"{md_row['未驱动']} | {md_row['参数不齐']} | {_cell(c.template or '—')} |"
            )
    md_total = sum(s["件数"] for s in per_cat_md.values())
    A(
        f"| **合计** | md {len(per_cat_md)} 类 + code | **{md_total + code_total}** | "
        f"**{sum(s['生成物'] for s in per_cat_md.values())}** | "
        f"**{sum(s['已驱动'] for s in per_cat_md.values())}** | **{bk[BOOK_CENSUS]}** | "
        f"**{sum(s['参数不齐'] for s in per_cat_md.values())}** | 在册模板 {len(schemas)} 份已装载 |"
    )
    A("")
    A("### 二之二、代码件五族的管辖面账（席 S116 首立；在册／已驱动／未驱动三数）")
    A("")
    A("- 为什么单独立账：`card-*`/`config-field`/`help-entry`/`copy-pool` 这些类别的**管辖对象是代码件**，"
      "而甲账 `G-T1` 只数 md 页 ⇒ 它们在旧册里恒显示 `0（代码面·门不执法）`，**数学上永远 0 驱动、"
      "也永远不欠账**。本节第一次把「在册多少件、驱动了多少、还欠多少」写成可判定的数（只加数，"
      "不缩任何既有扫描面，不动甲乙两账）。")
    A("- `已驱动` ＝ **§4③ 两形态之和**（`driven_a + driven_b`，两腿各留底数、可逐腿追）：")
    A("  · 形态(a)＝`content_census.code_driver_records()`：既有管辖页里已挂在册模板头且非生成物者中、"
      "rel 不是 `.md` 的件。今日恒空（`walk_content_pages()` 不产代码件页）⇒ (a) 腿的 0 是"
      "**由上游构造算出来的**，不是写死的 0；给 `walk_content_pages()` 加代码件产出即自动非零。")
    A("  · 形态(b)＝`content_census.code_b_verdict()`（席 S127 接入）：该类有**唯一生成命令**、"
      "生成口连跑两次字节等值、盘上产物当场复现、且该件在生成物里有自己的锚点行。"
      "四条任一不成立即不认 (b)——**无通道不豁免**，判「只能走 (a)」并挂工单（§二之三）。")
    A("- `面=md` 的行是简报与注册表的**口径差**如实点名：简报把 `persona-*` 列入「代码件五类」，"
      "而注册表 `doc_templates.CONTENT_CATEGORIES` 里 persona 四类 `surface==\"md\"`（管辖对象是 "
      "`personas/**` 的 md 页）⇒ 它们本就有甲账账，不属代码面缺口，本节单列以免与代码件混成一个数。")
    A("")
    A("| 族 | 类别 | 面 | 在册件数 | 已驱动数 | 其中(a) | 其中(b) | 未驱动数 | 取数口 | 判定 |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for fr in face_rows:
        A(
            f"| {_cell(fr.family)} | {_cell(fr.cid)} | {_cell(fr.surface)} | {fr.registered} | "
            f"{fr.driven} | {fr.driven_a} | {fr.driven_b} | {fr.undriven} | {_cell(fr.source)} | {_cell(fr.verdict)} |"
        )
    A("")
    A("族汇总（族内各类相加；一个类别只挂一枚模板 id ⇒ 不跨族重复计件）：")
    A("")
    A("| 族 | 在册件数 | 已驱动数 | 其中(a) | 其中(b) | 未驱动数 |")
    A("|---|---|---|---|---|---|")
    fam_legs: dict[str, list[int]] = {}
    for fr in face_rows:
        lg = fam_legs.setdefault(fr.family, [0, 0])
        lg[0] += fr.driven_a
        lg[1] += fr.driven_b
    for fam_name in sorted(fams):
        agg = fams[fam_name]
        legs = fam_legs.get(fam_name, [0, 0])
        A(f"| {_cell(fam_name)} | {agg[0]} | {agg[1]} | {legs[0]} | {legs[1]} | {agg[2]} |")
    A("")
    bverd = code_b_records(code_items)
    A("### 二之三、代码件形态(b) 通道与幂等实证（席 S127；§4③ 两形态同权）")
    A("")
    A("- 判据（三条腿**同时**成立才认 (b)，逐腿印出、不许凭「它是生成物」三个字放行）："
      "① 唯一生成命令连跑两次字节等值；② 生成结果与**盘上产物当场**字节等值（过期即判未驱动，"
      "与 md 面「生成物在册未当场复现字节等值」同形）；③ 每件在册件在生成物里有**自己的锚点行**"
      "（逐件、不按族蒙）。算口＝`content_census.code_b_verdict()`，通道登记＝`CODE_B_CHANNELS`（唯一一份）。")
    A("- 双跑是**只读**的：与 `command_catalog.py` 自己 `--check` 用同一支 `merged_entries()+render()`，"
      "本席不写盘（写盘归该脚本 `--write`）；该生成器无时间戳/随机源（grep `datetime|now()|time()` 命中 0）"
      "⇒ 跨进程、跨时刻复现成立。")
    A("")
    A("| 类别 | 族 | 唯一生成命令 | 生成物 | ①两次生成等值 | ②盘上当场复现 | ③逐件覆盖 | 判定 |")
    A("|---|---|---|---|---|---|---|---|")
    for c in dt.CONTENT_CATEGORIES:
        if c.surface != "code":
            continue
        bv = bverd[c.cid]
        A(
            f"| {_cell(c.cid)} | {_cell(template_family(c.template))} | {_cell(bv.command)} | "
            f"{_cell(bv.artifact)} | {_cell('是' if bv.idempotent else '否')} | "
            f"{_cell('是' if bv.disk_equal else '否')} | {bv.covered}/{bv.total} | {_cell(bv.reason)} |"
        )
    A("")
    A("- 无通道类的**最小改造工单**（准绳一：判「只能走 (a)」，绝不判「不适合模板化」）：")
    A("")
    A("| 类别 | 工单（需要什么参数源 · 谁提供 · 补齐后如何自动进账） |")
    A("|---|---|")
    for cid, order_text in B_WORK_ORDERS.items():
        A(f"| {_cell(cid)} | {_cell(order_text)} |")
    A(
        "| `persona-*`（`surface=md`） | 不属代码面缺口：注册表四类 persona 的 (a) 通道本就是那四份在册模板"
        "（`persona`/`persona-provenance`/`persona-numbered`/`persona-inject-data`），其页数账在甲账里，"
        "本席一字不碰。另据 `scripts/sync_persona_source.py` 页首测绘结论「副本与源是各自演化的独立文本、"
        "不是任何源的投影」（逐行重合 0.0%）⇒ **人格面不存在可复现字节的生成通道**，硬按 (b) 认账＝发明数据源。 |"
    )
    A("")
    code_rows = [fr for fr in face_rows if fr.surface == "code"]
    A(
        f"> **机制判决（准绳一：不许判「不适合模板化」，只判「须换机制」）**："
        f"代码面 {len(code_rows)} 类在册件共 {sum(fr.registered for fr in code_rows)} 枚、"
        f"已驱动 {sum(fr.driven for fr in code_rows)} 枚（形态(a) {sum(fr.driven_a for fr in code_rows)} + "
        f"形态(b) {sum(fr.driven_b for fr in code_rows)}）。"
        "席 S116 立的三条候选里，**② 已由席 S127 落成可执法判据**（`code_b_verdict()` 三条腿），"
        "`help-entry` 一族因此从 0/78 变 78/78；其余四类**盘上没有生成其内容字节的脚本**"
        "（简报括号里的「config-catalog 从 config.py 生成」按现算不成立：全仓零写方，"
        "`tests/test_doc_sync_gates.py` 只查「键有没有登记」，逐键说明是人写）⇒ 不认 (b)，"
        "判「只能走 (a)」并逐类挂工单（上表）。候选 ①（`walk_content_pages()` 产代码件页）与 "
        "③（注册表 `generated_by` 升格为驱动记录）仍在册、需门 owner 裁定后另立席施工；"
        "三案都不许靠「把代码件写进 md 页」凑数（那是发明数据源）。"
    )
    A("")
    A("## 三、总账三行 + 门侧原文（同一支现算值）")
    A("")
    A(f"- 内容件总数（md 管辖页 {md_total} + 代码面在册件 {code_total}）：**{md_total + code_total}**")
    A(
        f"- 未模板驱动数——**两本账分列（席 S116 更正旧「逐位相等」散文）**："
        f"甲账 `{BOOK_CENSUS}`＝**{bk[BOOK_CENSUS]}**（本册与门 G-T1 同源，**与门逐位相等**，"
        f"取数口 `spec_gates_census.compute()['t1']`）；"
        f"乙账 `{BOOK_WRITER}`＝**{bk[BOOK_WRITER]}**（写盘口 `doc_template_sync.py --report` 末行同口径，"
        f"其 pages={bk['writer_pages']} / 带在册模板头={bk['writer_driven']}）。"
        f"换算式现算校验：`{reconcile_msg}` ⇒ **交付值取甲账**，乙账为辅助核对。"
        f"两账之差 {bk[BOOK_WRITER] - bk[BOOK_CENSUS]} 枚全数落在 `MECH_B={bk['MECH_B']}"
        f" + TEMPLATE_SRC={bk['TEMPLATE_SRC']}` 上，无残差。"
    )
    A(
        f"- 未归属数（`doc_ownership_sync.compute_ownership()` 现算）：**{len(ledger.unowned)}** ；"
        f"未认领数（`physical_placement_census.compute()['a_unclaimed_list']` 现算，语义 A）："
        f"**{len(placement['a_unclaimed_list'])}** ；"
        f"合计 **{len(ledger.unowned) + len(placement['a_unclaimed_list'])}**"
    )
    A("")
    A("```text")
    L.extend(sgc.report_lines(res))
    A("```")
    A("")
    A("## 四、未归属清单（取数口＝`doc_ownership_sync.compute_ownership()`，本席不另算一套）")
    A("")
    unowned_grouped: dict[str, list[str]] = {}
    for rel in ledger.unowned:
        parent = rel.rsplit("/", 1)[0] + "/" if "/" in rel else "（仓库根）"
        unowned_grouped.setdefault(parent, []).append(rel.rsplit("/", 1)[-1])
    A("| 目录 | 件数 | 件名（本册不截断；按名排序） |")
    A("|---|---|---|")
    for parent in sorted(unowned_grouped):
        names = sorted(unowned_grouped[parent])
        A(f"| {_cell(parent)} | {len(names)} | {_cell('、'.join(names))} |")
    A(f"| **合计** | **{len(ledger.unowned)}** | 扫描面 {ledger.scanned} 件 |")
    A("")
    A("## 五、未认领清单（取数口＝`physical_placement_census.compute()`，语义 A）")
    A("")
    A("| # | 件 |")
    A("|---|---|")
    for i, rel in enumerate(sorted(placement["a_unclaimed_list"]), start=1):
        A(f"| {i} | {_cell(rel)} |")
    A(f"| **合计** | **{len(placement['a_unclaimed_list'])}** |")
    A("")
    A("## 六、明细表（类别→路径排序；「所用模板 id」「参数是否齐全」两列为**现算**）")
    A("")
    A("- `所用模板 id`：页 front-matter 里在册的 `template:`（无则标「—（在册应套 X）」，X 取 "
      "`spec_gates_census.registered_template(类别)`＝`doc_templates` 注册表）。")
    A("- `参数是否齐全`：门 G-T4 的同一支 `PageInfo.violations ∩ spec_gates_census.T4_CODES`；"
      "未驱动页记「未驱动·不适用」，生成器所有页记「不适用」。")
    A("- 代码面（`incode-copy-pool`/`fstring-card`/`jinja-template`/`html-card`/`help-topic`/`config-field`）"
      "不在 `walk_content_pages()` 管辖面内 ⇒ 门的 G-T1/G-T4 **不执法**，本册如实标注，不冒充已纳管；"
      "其「在册／已驱动／未驱动」三数账见 §二之二（席 S116 首立），两形态的通道与幂等实证见 §二之三"
      "（席 S127），机制判决同 §二之二末。")
    A("- 唯一新增的数据形状：html 件按父目录名 `templates` 分派 jinja/html-card（照旧 §一 字面判据），"
      "模板 id 与板块仍取注册表。")
    A("")
    A("| 路径或符号 | 内容类别 | 一级板块 | 二级功能 | 当前规格 | 是否模板驱动 | 所用模板 id | 参数是否齐全 |")
    A("|---|---|---|---|---|---|---|---|")
    order = [c.cid for c in dt.CONTENT_CATEGORIES]
    for cid in order:
        for _, line in detail.get(cid, []):
            A(line)
        items, source = code_items.get(cid, ([], ""))
        cat = dt.CATEGORIES_BY_ID[cid]
        if cid not in CARD_CODE_CIDS:
            continue
        if not items:
            A(
                f"| （{_cell(source)}） | {_cell(cid)} | {_cell(cat.owner_board)} | — | 代码面·现扫 0 件 | "
                f"代码面（门不执法，三数账见 §二之二） | {_cell(cat.template or '—')} | 代码面·门不执法 |"
            )
            continue
        for item in items:
            A(
                f"| {_cell(item)} | {_cell(cid)} | {_cell(cat.owner_board)} | — | 代码件·签名从略（在册件，"
                f"取数口见 §二之二） | 代码面（门不执法） | {_cell(cat.template or '—')} | 代码面·门不执法 |"
            )
    A("")
    A("---")
    A("")
    A("> 本册是**机器所有**的生成物：手改即与 `--check` 顶牛。要改口径请改取数口（注册表/门），"
      "或把诉求写进席位报告的 PARKED 段。")
    return "\n".join(L) + "\n", {
        "t1": len(t1),
        BOOK_CENSUS: bk[BOOK_CENSUS],
        BOOK_WRITER: bk[BOOK_WRITER],
        "mech_b": bk["MECH_B"],
        "template_src": bk["TEMPLATE_SRC"],
        "pages": md_total,
        "code": code_total,
        "code_driven": sum(fr.driven for fr in code_rows),
        "code_driven_a": sum(fr.driven_a for fr in code_rows),
        "code_driven_b": sum(fr.driven_b for fr in code_rows),
        "code_face_rows": face_rows,
    }


def _normalize(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if not ln.startswith(_TS_PREFIX)]


def _parity_exit(code: int) -> int:
    """两条出口共同的尾巴：盘上 §一 用门的解析口回读、与注册表比对；不等就把退出码顶成 1。"""
    ok, msgs = category_parity()
    print(f"类别名同源={'OK' if ok else 'RED'}（注册表 "
          f"{len(dt.CONTENT_CATEGORIES)} 类 · 盘上 §一 现算回读同一集合）"
          + ("" if ok else " → " + "；".join(msgs)))
    return code if ok else 1


def _book_line(stats: dict[str, object]) -> str:
    """两条出口都打的**两本账行**（席 S116：从此不再有「未模板驱动」这个无双名的数）。

    席 S127 追加**代码面三数**（含两形态分解），让「已驱动数上升」在 CLI 上就看得见，不必翻册。"""
    return (
        f"{BOOK_CENSUS}={stats[BOOK_CENSUS]}（甲账·与门逐位相等·交付值） "
        f"{BOOK_WRITER}={stats[BOOK_WRITER]}（乙账·写盘口 --report 口径） "
        f"MECH_B={stats['mech_b']} TEMPLATE_SRC={stats['template_src']}；"
        f"换算式 `{BOOK_CONVERSION}`；"
        f"代码面在册={stats['code']} 已驱动={stats['code_driven']}"
        f"（形态a={stats['code_driven_a']}／形态b={stats['code_driven_b']}）"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true", help="重生成 CENSUS.md")
    g.add_argument("--check", action="store_true", help="现算结果与盘上文件比对（不含生成时间行）")
    args = ap.parse_args(argv)
    text, stats = render()
    if args.write:
        CENSUS_MD.parent.mkdir(parents=True, exist_ok=True)
        CENSUS_MD.write_text(text, encoding="utf-8", newline="\n")
        print(
            f"WROTE {CENSUS_MD}  管辖页={stats['pages']} 代码面={stats['code']}  {_book_line(stats)}"
        )
        return _parity_exit(0)
    disk = CENSUS_MD.read_text(encoding="utf-8", errors="replace") if CENSUS_MD.is_file() else ""
    b = _normalize(disk)
    a = _normalize(text)
    diff_src = "第一次"
    if a != b:
        # 多席并发：两次现算之间树可能已动 ⇒ 再现算一次。盘上文件只要等于**相邻任一次**现算就是同源投影。
        # 这不放松判据：真过期的文件两次都不等；放宽面仅限「取数时刻之差」，且把漂移行数如实打出来。
        text2, stats = render()
        a2 = _normalize(text2)
        if a2 == b:
            print(
                f"CLEAN（两次现算之间树在动，漂移 {sum(1 for x, y in zip(a, a2) if x != y)} 行；盘上＝第二次现算）"
                f"  {_book_line(stats)}"
            )
            return _parity_exit(0)
        diff_src = "第二次"
        a = a2
    diff = [(i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(a) != len(b):
        diff.append((min(len(a), len(b)), f"<现算共 {len(a)} 行>", f"<盘上共 {len(b)} 行>"))
    if not diff:
        print(f"CLEAN vs {diff_src}现算  {_book_line(stats)} 甲账与门 G-T1 逐位相等")
        return _parity_exit(0)
    print(f"DRIFT vs {diff_src}现算：{len(a)} 行 vs 盘上 {len(b)} 行，差异 {len(diff)} 处")
    for i, x, y in diff[:5]:
        print(f"  行{i}: 现算={x[:130]!r}")
        print(f"       盘上={y[:130]!r}")
    return _parity_exit(1)


if __name__ == "__main__":
    raise SystemExit(main())

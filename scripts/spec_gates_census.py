"""G-T1/T2/T3/T4/T5 唯一取数口（席 T-GATES，2026-09-22）。

一句话：**违规清单、总数、`--report` 三处同源**——同一支 `compute(root)` 既喂常驻门的
断言，也喂注毒用例，还喂命令行；禁在测试里另起一套扫描器（本仓「第二真身」教训）。

各类判据（详见 `GATE-PLAN.md` §三）：

- **G-T1** 内容页必须由 **机制 (a) front-matter `template:` 头**（指向存在模板）或
  **机制 (b) 写盘口当场重渲染逐字节复现** 二者之一驱动（准绳 §4③ 的两条合法形状，
  席 S46 2026-09-22 补认 (b)：旧写法按「生成物名单」路径成员隐形豁免＝K-2 同型；
  现改为当场向生成器重渲染、字节等值才记「已驱动 (b 形)」，不复现即入债，报告行可见）。
  **席 TX130（2026-09-23，用户裁定件 R0）加口径、不加豁免**：同一支 `t1` 另按
  「对外正式交付面＝欠账（判据用数）／`.superpowers/**` 过程件＝登记（不进欠账、照套头）」
  分账为 `t1_debt_official` + `t1_registered_process` 两栏并排报数，**`t1` 总量一枚不删、
  扫描面一寸不缩**（两栏之和恒等于 `t1`；类别判据全部由 `doc_templates.CONTENT_CATEGORIES`
  与既存真身 `PROCESS_LOG_CATEGORIES`/`ledger_bucket_of` 派生，本文件零第二份类别名清单）。
  生成物名单本身仍按**写盘口现算**点名
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
import hashlib
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
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

#: 骨架原文与上面三份 canon **同源同处**（席 S152 完整度账的「未填槽」判据取这一份，
#: 禁在别处再抄一遍 `L*_BODY`——那是第二真身，也是改骨架时最容易漏跟的一刀）。
BOARD_CANON_SOURCES: dict[str, str] = {
    "board-l1": bds.L1_BODY,
    "board-l2": bds.L2_BODY,
    "board-l3": bds.L3_BODY,
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
# 机制 (b)（席 S46，2026-09-22）：生成页「已驱动」＝当场重渲染、逐字节等值
# 准绳 §4③ 允许两条合法形状：(a) front-matter 驱动、(b) 由参数源生成且脚本可复现其字节。
# 旧账只把生成器名单当路径豁免（名单里＝免检），这正是 K-2 点名的「按路径隐形绿」。
# 现在名单只是**候选面**：板块页逐页比对 AUTO 段与生成器现渲染结果（与 board_doc_sync
# --check 同一支解析），整册生成页比对重渲染全文；不复现 ⇒ 入 G-T1 债并带原因后缀。
# ---------------------------------------------------------------------------
def _zone_inner(text: str) -> str | None:
    """板块段内文（与 `board_doc_sync.check_tree` 同形解析）。缺任一标记 ⇒ None。

    席 S78（P-41）说明：本函数只取**第一**段，用于机制 (b)「这页整体是否由写盘口生成」的判定；
    机器段活性（K-1）另在 `_auto_zone_verified` 里**逐段**比对（不在此处数段数，否则会误伤
    正文里以行内码引用 `BOARD-AUTO` 标记字面量的正常板块页）。
    """
    if bds.AUTO_BEGIN not in text or bds.AUTO_END not in text:
        return None
    inner = text.split(bds.AUTO_BEGIN, 1)[1].split(bds.AUTO_END, 1)[0]
    return inner.replace(f"{bds.AUTO_NOTE}\n\n", "", 1).strip()


def board_expected_zones() -> dict[str, str]:
    """rel posix → 板块生成器现渲染的 AUTO 段文本（fail-closed：build_tree 有问题即空表）。"""
    boards, problems = bds.build_tree()
    if problems:
        return {}
    topics = bds.load_help_topics()
    route_index = bds.load_route_index()
    expect: dict[str, str] = {
        (bds.BOARDS_DIR / "README.md").relative_to(ROOT).as_posix():
            bds.render_root_auto(boards, bds._facts(boards, topics)).strip()
    }
    for board in boards:
        bdir = bds.BOARDS_DIR / board.dir_name
        expect[(bdir / "README.md").relative_to(ROOT).as_posix()] = bds.render_board_auto(board, topics).strip()
        for feature in board.features:
            fdir = bdir / feature.slug
            expect[(fdir / "README.md").relative_to(ROOT).as_posix()] = bds.render_feature_auto(feature, topics).strip()
            for l3 in feature.l3:
                expect[(fdir / f"{l3.slug}.md").relative_to(ROOT).as_posix()] = bds.render_l3_auto(
                    feature, l3, topics, route_index
                ).strip()
    return expect


def single_doc_reproduced(rel: str, root: Path) -> bool:
    """整册生成页：重渲染输出与盘上字节逐字等值才算 (b 形)；任何异常按不复现（fail-closed）。"""
    try:
        if rel == _symbol_path("doc_sync", "TARGET"):
            import doc_sync

            expected = doc_sync.build_document()
        elif rel == _symbol_path("command_catalog", "DOC"):
            import command_catalog as cc

            expected = cc.render(cc.merged_entries())
        else:
            return False
    except Exception:  # noqa: BLE001 —— fail-closed：生成器侧任何异常都不得逃逸成「豁免」，一律按不复现记债
        return False
    f = root / rel
    return f.is_file() and f.read_text(encoding="utf-8") == expected


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
# 席 S78（P-39 落地，2026-09-22，只加严）：G-T3 面 A 分流的「历史台账/过程件」判据。
# 旧写法用 `p.rel.startswith(".superpowers/")` 这个**路径前缀**把过程日志从两面里剔除
# （债只活在 G-T1）。前缀既脆（换个目录写法就漏）又把「历史台账」和「现役规格」混为一谈：
# 根层 `HANDOFF-*`/`root-report`/`handbook`/`acceptance` 一旦挂上 front-matter 驱动，
# `driven()` 就把它顶进行级面 A（S32b 实测 485 行 / S65 handbook 361、acceptance 58 行同型），
# 而这些页的历史数字**删不得**（迁移清洗三分法：历史记录只加限定不改正文）⇒ 这类页永久挂不上驱动。
# 正解＝改按**内容类别**判，且**已驱动页与未驱动页同权**（下面这一处判，禁第二条码路）。
# 类别名一律取既有分类 `doc_templates.CONTENT_CATEGORIES`/`CENSUS §一` 的 cid，**不新建第二套分类表**。
# 两档处置（照既有设计，只是把「前缀」换成「类别」）：
#   · process-log（`.superpowers/**` 专属三cid）：两面都不记，债只在 G-T1（随各席随时追加行、
#     行数级上限会随机漂移，故按页在 G-T1 记更稳）——这正是旧前缀豁免的语义，原样保留。
#   · historical-page（根层/活文档四cid）：永不记行级面 A（历史数字不可清），记面 B 页级——
#     未驱动时它本就在面 B（现状不动），驱动后仍落面 B（不翻进面 A）⇒ 面 B 不因此上升、真违规不漏网。
# ---------------------------------------------------------------------------
PROCESS_LOG_CATEGORIES: frozenset[str] = frozenset({"seat-report", "sdd-ledger", "sdd-brief"})
HISTORICAL_PAGE_CATEGORIES: frozenset[str] = frozenset(
    {"root-handoff", "root-report", "handbook", "acceptance"}
)


#: 席 S126（第二十二批）：`design-spec` 桶里**过程件误住**者的落点桶。必须是**既有**桶，
#: 且取 `HISTORICAL_PAGE_CATEGORIES` 成员而非 `PROCESS_LOG_CATEGORIES` 成员——后者经
#: `face_of_history_page` 返回 `skip`，会让该页从 G-T3 两面**同时**消失＝席 S121 警告的
#: 「行级债就地蒸发」；`root-report`（注册表在册模板 `incident-report`，语义＝报告/台账件）
#: 恒返回 `page`＝页级账仍在，零蒸发。新建桶需 §4②「同类内容一份模板」证据，本席不新建。
MISLOCATED_PROCESS_BUCKET: str = "root-report"


# ---------------------------------------------------------------------------
# 席 S201（2026-09-24，用户裁定 **3.A**）：**G-T3 桶表真身**——一篇文档记进哪一面，
# 只由「路径派生的类别 ＋ 门 owner 的登记名录」决定，**模板头一律不参与分类**。
#
# 病根（本表要治的那件事，逐页实测见 SEAT-S201 §1）：旧判据把「记账面」挂在
# `driven_non_generated`（＝本页有没有戴在册 `template:` 头）上——戴头 ⇒ 逐行严管面A，
# 摘头 ⇒ 逐页面B。头是**被检者自己写的**，于是「用哪把尺子量这一页」由这一页自己说了算：
# 2026-09-23 一次批量套头把 23 枚审计/席位过程件从面B 拉进面A（行数 0 → 460），
# 反方向（摘头逃账）同样一拨即成。裁定 3.A 的原话＝「一篇文档算哪一类，不许由它自己
# 戴的模板头决定」，故此处把桶的**派生方式**改掉，而不是逐页回头改头。
#
# 三态（严→宽）：`line`＝面A 逐行清零 ／ `page`＝面B 逐页欠账（上限另有其人）／
# `skip`＝G-T3 两面都不记（过程日志，债只在 G-T1 按页记）。
G_T3_FACES: tuple[str, ...] = ("line", "page", "skip")
_FACE_SEVERITY: dict[str, int] = {"line": 2, "page": 1, "skip": 0}

#: **唯一桶表**：类别 → 面。每一枚在册类别必须在此显式有一行——「没登记＝免检」是裁定
#: 明令禁止的形态，故缺行既不作默认也不静默放行：`face_by_category_strict()` 当场抛、
#: 常驻总集性锁（`tests/test_board_taxonomy_gate.py`）点名红。
#: 取值口径（与 HEAD 逐页对齐，方向自查见 SEAT-S201 §2）：
#:   · 板块人工区（board-*，含索引页与 `_meta`）＝生成器与人共管 ⇒ `line`（旧路径判据的等价改写）；
#:   · 过程日志三 cid ⇒ `skip`（沿用 S78 那一对集合，一字未增）；
#:   · 根层/活文档历史页四 cid ⇒ `page`（沿用 S78，历史数字删不得）；
#:   · 其余对外 md 类别（规格/目录/杂项/人格/根规则）⇒ `page`＝**与 HEAD 同面**
#:     （HEAD 这些页无头 ⇒ 本就逐页面B）；要升 `line` 走下面的名录，一枚一枚登记。
#:   · `surface=="code"` 六类没有 md 正文页 ⇒ `skip`，逐枚理由记在
#:     `G_T3_SKIP_REASONS`（与「过程日志所以不记」是两回事，同一支字典里点名，不混为一谈）。
FACE_BY_CATEGORY: dict[str, str] = {
    "board-l1": "line",
    "board-l2": "line",
    "board-l3": "line",
    "board-index": "line",
    "board-meta": "line",
    "design-spec": "page",
    "doc-misc": "page",
    "catalog": "page",
    "route-matrix": "page",
    "root-rules": "page",
    "root-handoff": "page",
    "root-report": "page",
    "handbook": "page",
    "acceptance": "page",
    "persona-knowledge": "page",
    "persona-provenance": "page",
    "persona-numbered": "page",
    "persona-inject-data": "page",
    "seat-report": "skip",
    "sdd-ledger": "skip",
    "sdd-brief": "skip",
    "template-source": "skip",
    "html-card": "skip",
    "jinja-template": "skip",
    "incode-copy-pool": "skip",
    "fstring-card": "skip",
    "help-topic": "skip",
    "config-field": "skip",
}

#: 被显式记成 `skip` 的非过程日志理由（只此一桶，报数与分类不得混谈）。
G_T3_SKIP_REASONS: dict[str, str] = {
    "seat-report": "过程日志（S78 真身集合）：两面都不记，债在 G-T1 按页",
    "sdd-ledger": "过程日志（同上）",
    "sdd-brief": "过程日志（同上）",
    "template-source": "模板本体（非内容页，`compute()` 在记账前已滤除）；参数账在 G-T4",
    "html-card": "代码面（surface==code），无 md 正文可记行",
    "jinja-template": "代码面（同上）",
    "incode-copy-pool": "代码面（同上）",
    "fstring-card": "代码面（同上）",
    "help-topic": "代码面（同上）",
    "config-field": "代码面（同上）",
}

#: **现役逐行清零名录**（登记身份；门 owner 侧的写面，页自己改不动）。
#: 方向只准加严：名录里出现过的路径**永不**因桶表而回到 `page`。
#: 09-24 首批按 SEAT-S179 归因表簇②（真·现役规格/契约页，其裸事实属活口径、可改指针句）
#: 点名四枚；其余对外页今日仍按面B 逐页记账，谁要升格请往这里加一行（并现算代价）。
GOVERNED_LINE_PATHS: frozenset[str] = frozenset(
    {
        "docs/design/seat-report-param-provider-contract.md",
        "docs/design/llm-billing-ledger.md",
        "docs/design/control-plane-api.md",
        "docs/design/v21r4-b2-port-wiring-plan.md",
    }
)


def categories_outside_content_universe(root: Path = ROOT) -> set[str]:
    """`classify()` 按路径判得出来、但**不在记账宇宙里**的类别（当前唯一一枚＝`template-source`：
    `compute()` 在记账前按 `dt.TEMPLATE_SOURCE_PREFIX` 把模板本体滤掉，故它永不出现在 `pages`）。

    只列路径、跑纯路径判据 `classify()`，**不读正文**；前缀常量取自注册表真身，零第二份名单。
    本函数的存在理由：桶表的体检域必须是「路径判据能到达的类别全集」，否则这一行的桶表
    会被自己的幽灵行判据误杀（幽灵行判据不许反过来逼表删掉一条真判据）。
    """
    base = root / dt.TEMPLATE_SOURCE_PREFIX
    if not base.is_dir():
        return set()
    return {
        dts.classify(p.relative_to(root).as_posix())
        for p in base.rglob("*.md")
        if "__pycache__" not in p.parts
    }


def bucket_table_gaps(
    pages: list[dts.PageInfo] | None = None,
    *,
    extra_categories: set[str] | None = None,
) -> list[str]:
    """桶表体检（裁定 3.A 的另一半：不许「没登记＝免检」，也不许两套口径各说各话）。

    · 注册表在册 / 页面上真出现 / 路径判据可达 的类别 ⇒ 桶表必须有显式一行（缺行＝红）；
    · 桶表里有行但三处都不认 ⇒ 红（幽灵行＝一把量不存在对象的尺子，会让人误信有人在管）；
    · 面值必须是三态之一；
    · 桶表与 S78 那两枚类别集合必须同判（过程日志⇒skip、历史台账⇒page）——两套口径分叉
      ＝「说是台账、却又按行清零」或「过程日志被顶进严管面」，都是同一件事写两遍漏一遍；
    · `G_T3_SKIP_REASONS` 的理由账必须与判据账一致（给了 skip 理由的类别现在真是 skip）；
    · S126 内容重判腿的落点永不比 `design-spec` 更严（那条腿只定位，不是加严通道）。
    """
    registry = {c.cid for c in dt.CONTENT_CATEGORIES}
    domain = registry | {p.category for p in (pages or [])} | (extra_categories or set())
    gaps: list[str] = []
    for cid in sorted(domain - set(FACE_BY_CATEGORY)):
        gaps.append(
            f"BUCKET_ROW_MISSING {cid}: 注册表/页面/路径判据认这一类，"
            "但 G-T3 桶表没有显式一行（缺行≠免检）"
        )
    for cid in sorted(set(FACE_BY_CATEGORY) - domain):
        gaps.append(
            f"BUCKET_ROW_ORPHAN {cid}: 桶表有行，但注册表、页面、路径判据三处都不认这一类（幽灵行）"
        )
    for cid, face in sorted(FACE_BY_CATEGORY.items()):
        if face not in G_T3_FACES:
            gaps.append(f"BUCKET_FACE_UNKNOWN {cid}: 面值 {face!r} 不在 {G_T3_FACES}")
    # 桶表与 S78 那两枚类别集合必须同判——两套口径分叉＝一面「说是台账、另一面按行清零」，
    # 或反过来把过程日志顶进严管面（都是「同一件事两处各写一遍、改一处漏一处」的标准形态）。
    for cid in sorted(PROCESS_LOG_CATEGORIES):
        if FACE_BY_CATEGORY.get(cid) != "skip":
            gaps.append(
                f"BUCKET_VS_LEDGER_SET 过程日志类 {cid} 在桶表里不是 skip（S78 集合与桶表分叉）"
            )
    for cid in sorted(HISTORICAL_PAGE_CATEGORIES):
        if FACE_BY_CATEGORY.get(cid) != "page":
            gaps.append(
                f"BUCKET_VS_LEDGER_SET 历史台账类 {cid} 在桶表里不是 page"
                "（＝台账页被顶进行级面A，或掉出两面＝债蒸发）"
            )
    # 「过程件误住规格桶」重判腿的落点永远不许比 design-spec 本身更严（否则 S126 变成加严通道，
    # 与本裁定「桶表一处派生」的分工混淆）。
    if _FACE_SEVERITY.get(FACE_BY_CATEGORY.get(MISLOCATED_PROCESS_BUCKET, "page"), 0) > _FACE_SEVERITY[
        FACE_BY_CATEGORY.get("design-spec", "page")
    ]:
        gaps.append(
            f"BUCKET_REJUDGE_TIGHTENS {MISLOCATED_PROCESS_BUCKET}: S126 重判落点比 design-spec"
            " 更严＝内容腿变成加严通道（本函数只定位、不改面）"
        )
    for cid in sorted(G_T3_SKIP_REASONS):
        if FACE_BY_CATEGORY.get(cid) != "skip":
            gaps.append(
                f"SKIP_REASON_STALE {cid}: G_T3_SKIP_REASONS 给了它一个 skip 理由，"
                f"但桶表现把它记成 {FACE_BY_CATEGORY.get(cid)!r}——理由账与判据账分叉"
            )
    return gaps


def face_by_category_strict(category: str) -> str:
    """类别 → 面。**未登记即抛**：宁当场崩，绝不静默按最宽处理（裁定 3.A 的「没登记≠免检」）。"""
    try:
        return FACE_BY_CATEGORY[category]
    except KeyError:
        raise LookupError(
            f"类别 {category!r} 在 G-T3 桶表 FACE_BY_CATEGORY 里没有显式一行——"
            "缺行不是免检，新增类别必须同批补判据"
        ) from None


def face_of_page_by_path(p: dts.PageInfo) -> str:
    """G-T3 记账面的**唯一**判据：只读 `p.category`（路径派生）与登记名录，**不读 front-matter**。

    名录只准把页往**严**的方向放（`line`），从不往宽放；桶表决定其余页。
    """
    if p.rel in GOVERNED_LINE_PATHS:
        return "line"
    return face_by_category_strict(p.category)


#: 与旧路径前缀判据的等价性自查用：旧码路是「`p.rel` 落在 `docs/boards/` 下」⇒ line。
BOARDS_PATH_PREFIX: str = "docs/boards/"


def boards_prefix_agrees_with_table(p: dts.PageInfo) -> bool:
    """板块页「路径前缀」与「类别桶」必须同判（改 `classify()` 的人漏跟桶表 ⇒ 此处不等）。"""
    return p.rel.startswith(BOARDS_PATH_PREFIX) == (
        face_by_category_strict(p.category) == "line"
    )


def face_if_migrated(p: dts.PageInfo) -> str:
    """写盘口 `--write` 的**前置**判据（与记账判据是两问，别混）：
    「**假如**给这页挂上驱动，它的裸事实该按哪一面清零」。

    旧实现是拿 `face_of_history_page(p, driven_non_generated=True)` 问同一件事——
    记账与前置共用一支函数的两个入参，正是「头能拨面」的另一半。本函数把前置单独成口：
    非台账（现役对外）类别 ⇒ 恒 `line`（挂驱动前必须先清到零，S105/S78 原语义一字不松）；
    台账/过程件类别 ⇒ 取桶表面（`page`/`skip`，历史数字删不得，故不拿它当驱动前置）。
    """
    bucket = ledger_bucket_of(p)
    if bucket is not None:
        return face_by_category_strict(p.category)
    return "line"


def class_claimed_by_header(p: dts.PageInfo) -> tuple[str, str] | None:
    """**反面尺（只喂自证锁，永不进账）**：这一页的 front-matter 头「声称」自己属于哪一类、
    那一类在桶表里记哪一面。返回 `(声称类别, 面)`，或 `None`＝头不构成分流申请。

    判 `None` 的三种情形（都是「头没在试图改分类」，不是放行）：
      · 无头 / 头里没有 `template:`；
      · 该模板被零枚或多枚类别认领（注册表里反推不唯一，无从声称）；
      · 头指回**本页路径自己那一类**＝纯版式声明（`category_mismatch` 那条腿认的正是这一形，
        它不带新增信息，故不算分流申请——否则每一枚戴对头的现役页都会被本锁误伤）。
    """
    if p.fm is None or not p.fm.template:
        return None
    owners = [c.cid for c in dt.CONTENT_CATEGORIES if c.template == p.fm.template]
    if len(owners) != 1:
        return None
    claimed = owners[0]
    if claimed == p.category:
        return None
    return claimed, face_by_category_strict(claimed)


def header_exemption_findings(pages: list[dts.PageInfo]) -> list[str]:
    """「不许自我豁免」的机检形态（裁定 3.A 要的那把锁）：头能买到的面，
    **绝不允许宽于**路径/登记判出来的面。

    红＝这一页靠自己的 front-matter 声称了一个更宽的类别（例：现役规格页戴
    `template: seat-report` 想冒充过程件 ⇒ 桶表里 `skip`，比路径判的 `line` 宽两级）。
    反方向（头比路径更严）不算红＝自我加严，底线仍由路径判据兜着。
    与 `category_mismatch` 是两面不同的尺子：那条管「头与路径类别不一致」（形式一致性，
    宽严都管），本条管「不一致时是否买到了更宽的分流」（只罚放水方向）。两者可同页并红。
    """
    out: list[str] = []
    for p in pages:
        claimed = class_claimed_by_header(p)
        if claimed is None:
            continue
        cid, hat_face = claimed
        path_face = face_of_page_by_path(p)
        if _FACE_SEVERITY[hat_face] < _FACE_SEVERITY[path_face]:
            out.append(
                f"SELF_EXEMPTION_VIA_TEMPLATE {p.rel}: 路径/登记判它记「{path_face}」，"
                f"但它的 template={p.fm.template if p.fm is not None else None!r}"
                f"（声称类别 {cid!r}）会把这一页放进更宽的「{hat_face}」桶——"
                "分桶不许由被检者自己戴的头决定"
            )
    return out


def header_coupling_findings(
    pages: list[dts.PageInfo], face_ruler: Callable[..., str]
) -> list[str]:
    """不变量体检（对**任意一支**分流尺子跑，故能反过来证明本锁有牙）：
    同一页在「驱动」与「未驱动」两种假设下读数必须一致——不一致＝头在拨面。

    锁用 `face_of_history_page` 跑 ⇒ 必须零红；注毒用例把**裁定前的旧尺**（读
    `driven_non_generated` 的那一版）喂进同一个比较器 ⇒ 必须逐页点名。比较器只有一份，
    禁止「正尺走一套判据、毒尺走另一套」（那等于给锁配一把只砍自己的刀）。

    尺子若不收 `driven_non_generated` 形参 ⇒ **原样上抛 TypeError**，不静默跳页：
    跳过＝让一把根本答不上这道题的尺子白过体检（假绿的一种标准形态）。
    """
    out: list[str] = []
    for p in pages:
        on = face_ruler(p, driven_non_generated=True)  # type: ignore[operator]
        off = face_ruler(p, driven_non_generated=False)  # type: ignore[operator]
        if on != off:
            out.append(
                f"FACE_COUPLED_TO_TEMPLATE_HEADER {p.rel}: 驱动态 {on!r} vs 未驱动 {off!r} "
                "——同一页因戴不戴头换面＝被检者自己挑尺子（裁定 3.A 禁此）"
            )
    return out



#: 规格槽同义词（现役设计规格页的 H2 用语）——命中即**不**重判（保守方向：宁可留在更严的面A）。
SPEC_SLOT_HEADS: tuple[str, ...] = (
    "目标", "范围", "背景", "动机", "非目标", "名词", "术语", "接口", "协议",
    "契约", "数据模型", "架构", "设计", "约束", "限制", "决策", "取舍",
    "替代方案", "方案", "验收标准", "风险", "兼容性", "语义", "规范", "定义",
    "字段", "端点", "流程", "状态机", "权限", "安全", "性能", "容量", "边界",
)
#: 过程件特征（波次/席位/实跑/裁决/交接等——简报点名的五族及其同类）。
PROCESS_DOC_HEADS: tuple[str, ...] = (
    "波次", "席位", "实跑", "裁决", "交接", "进度", "断点", "复跑", "取证",
    "归属", "判决", "收尾", "总账", "台账", "对账", "核销", "残项", "待办",
    "交付", "工作日志", "攻击", "评审", "修复波", "统一波", "改动面", "现状",
)
#: 机械阈值：≥2 枚**去重后**过程件 H2 且 0 枚规格槽 H2 才重判。为什么不是 1：
#: 现役规格页也会有一枚「现状」/「交付」类节（本仓真树实测 `拿不准` 面 184 页即此混形），
#: 阈值取 1 会把规格页一并放走＝判据变松（§0 六禁）；取 2 使被放走者**只可能是**
#: 通篇过程语境的页。该数由本席现算语料分布定，非为让某页过检而调。
PROCESS_DOC_MIN_HITS: int = 2

_SPEC_SLOT_RE = re.compile("|".join(SPEC_SLOT_HEADS))
_PROCESS_DOC_RE = re.compile("|".join(PROCESS_DOC_HEADS))


def content_class_of_mislocated_process_page(p: dts.PageInfo) -> str | None:
    """按**正文内容**判：一个路径被 `classify()` 归入 `design-spec` 的页，是否其实是过程件。

    返回既有过程件桶 cid（`MISLOCATED_PROCESS_BUCKET`）或 `None`（＝维持原判）。
    判据只读正文 H2 字面量：不读路径前缀（简报 ② 禁码路）、不读 front-matter 的"过程件"字样
    （页自己声明改不动分类；套错模板由 `category_mismatch` 那条腿拦）。

    席 S201（2026-09-24，裁定 3.A）：**删掉旧「显式声明 `template: design-spec` 即豁免重判」
    那半腿**——那是最后一处「头参与分类」。删除后本腿的落点仍恒为既有桶，且 `design-spec`
    与 `root-report` 在桶表里同面（`page`），故 G-T3 两面**逐页读数不变**（实测见 SEAT-S201 §2）；
    它继续为 R0 口径与报告提供「过程件误住规格桶」的定位，只是再也拨不动记账面。
    """
    if p.category != "design-spec":
        return None
    heads = {trunk(h) for h in headings("\n".join(_no_fences(p.text or "")))}
    if not heads:
        return None                      # 无 H2 ⇒ 证据不足，维持原判（不猜）
    if any(_SPEC_SLOT_RE.search(h) for h in heads):
        return None                      # 有规格槽同义词 ⇒ 现役规格，不重判
    proc = {h for h in heads if _PROCESS_DOC_RE.search(h)}
    if len(proc) >= PROCESS_DOC_MIN_HITS:
        return MISLOCATED_PROCESS_BUCKET  # 只落既有桶，永不新建
    return None


def ledger_bucket_of(p: dts.PageInfo) -> str | None:
    """该页按哪一「历史台账/过程件」桶记账；`None`＝非台账（现役治理面）。单一判据源。

    = `is_ledger_category` 的同一对桶集合（S78 真身）**∪** S126 的内容重判腿。
    桶集合本身一份未增（禁第二套分类表）。
    """
    if p.category in PROCESS_LOG_CATEGORIES or p.category in HISTORICAL_PAGE_CATEGORIES:
        return p.category
    return content_class_of_mislocated_process_page(p)


def is_ledger_category(category: str) -> bool:
    """类别是否属「历史台账 / 过程件」（内容真身不可就地清扫为指针）。单一判据源。"""
    return category in PROCESS_LOG_CATEGORIES or category in HISTORICAL_PAGE_CATEGORIES


# ---------------------------------------------------------------------------
# 席 S153（第二十五批）：**可重复自由槽**的资格真身（装载期由
# `doc_template_sync.freeform_guard` 现调，本函数只派生、不另立判据）。
# 简报②(a) 的四条硬约束在此的落点：
#   · 复用既有分类判据，禁第二套 ⇒ 本函数**只做投影**：类别集合取
#     `dt.CONTENT_CATEGORIES`（注册表唯一真身），是否「过程件/历史台账」逐类别问
#     `is_ledger_category`（S78 真身），模板 id 逐类别问 `registered_template`（S2 真身）。
#     零新增成员表、零类别枚举硬编码、零路径前缀。
#   · S126 的内容重判腿不需要另立资格：`content_class_of_mislocated_process_page` 的落点
#     恒为既有桶 `MISLOCATED_PROCESS_BUCKET`（＝`root-report` ∈ `HISTORICAL_PAGE_CATEGORIES`），
#     故其模板 `incident-report` 已在册；本席由 `test_freeform_eligibility_is_a_projection`
#     以等式锁死这条归属，桶集合今日一枚未增（增桶需该判据 owner 裁定）。
#   · 现役规格类（`design-spec`/`catalog`/`doc-misc`/板块与人格类等）不在投影内
#     ⇒ 谁在那些模板上写 `freeform: on` 谁装载即红。
# ---------------------------------------------------------------------------
def freeform_allowed_template_ids() -> frozenset[str]:
    """允许启用可重复自由槽的模板 id（由既有判据现算，非硬编码清单）。"""
    out: set[str] = set()
    for cat in dt.CONTENT_CATEGORIES:
        if not is_ledger_category(cat.cid):
            continue
        tid = registered_template(cat.cid)
        if tid:
            out.add(tid)
    return frozenset(out)


def face_of_history_page(
    p: dts.PageInfo, *, driven_non_generated: bool = False
) -> str:
    """该页裸事实记进 G-T3 的哪一面：`line`=面A（按行·治理面）／`page`=面B（按页·未迁移）／
    `skip`=两面都不记（过程日志，债只在 G-T1）。

    **席 S201（2026-09-24，用户裁定 3.A）：分流改为只读「路径派生类别 ＋ 登记名录」的桶表**
    （`FACE_BY_CATEGORY` ＋ `GOVERNED_LINE_PATHS`，一处真身）。模板头与「驱动与否」一律
    不参与分类——旧写法把 `driven_non_generated`（＝本页戴没戴在册 `template:` 头）当分流输入，
    正是「被检者自己挑尺子」的正身：2026-09-23 一次批量套头把 23 枚审计/过程件顶进面A
    （该面行数 0 → 460），反方向摘头逃账同样一拨即成。
    形参**保留只为不变量锁当输入**（`tests/test_board_taxonomy_gate.py` 断言传 True 与传
    False 逐页同值＝头再也拨不动面），判据本体不读它；写盘口 `--write` 要问的「驱动后该按
    哪一面清零」已另立 `face_if_migrated()`，不再靠复用本函数入参问第二件事。

    S78（P-39）／S126（第二十二批）仍然有效的**语义**原样保留，只是换了承载：
    过程日志两面都不记、历史台账页永不顶进行级面A（历史数字删不得）——这两条现在写在
    `FACE_BY_CATEGORY` 的行里（skip / page），而不再靠函数里再查一次桶集合；两套口径若分叉，
    `bucket_table_gaps()` 的「桶表 vs S78 集合」一致性两条当场点名。
    """
    del driven_non_generated  # 裁定 3.A：驱动态不参与分桶，只服务不变量锁的自证输入
    return face_of_page_by_path(p)


def governed_line_paths_for_test() -> frozenset[str]:
    """名录真身的只读投影（锁用：证明「钉住的那几枚」就是名录本体，不是第二份清单）。"""
    return GOVERNED_LINE_PATHS


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


def should_have_template(category: str) -> bool:
    """该类别是否**归本腿管辖**（在册 md 面、非生成器所有）——G-T5 第三边的「该不该执法」一问。

    席 S164（第二十六批，只加严）：`registered_template()` 把两件不同的事压成同一个 `None`——
    ①「生成器所有／代码面」＝本腿**该**豁免，②「md 在册但该桶压根没有模板」＝本腿**该**执法。
    旧死类循环只问 `want is not None`，于是 ② 被 ① 一起短路，「无模板类别」下的页从不进
    `pages_unreachable`（它们只被 `missing_template` 按**类别**记到，按**页**的三角闭合腿失明）。
    本谓词与 `registered_template` 同读 `dt.CATEGORIES_BY_ID` 唯一真身，零第二份分类表。
    """
    c = dt.CATEGORIES_BY_ID.get(category)
    return bool(c) and not c.generated_by and c.surface == "md"


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
# K-1 机器段活性校验（席 S20，2026-09-22，加严）
# `strip_auto_zones` 会无条件剥掉 AUTO/TEMPLATE-AUTO 标记之间的一切——谁嵌一对注释
# 就能把裸事实藏进被剥的段里（S10 内存注毒实证「裸事实 8 条 → 0 条」。修法：段内若真
# 藏了裸事实，必须逐字节等于写盘口现算值才可信；不等、或压根没有写盘口（无在册模板的
# 标记形）⇒ 记 `UNVERIFIED_AUTO_ZONE` 判红。板块段以 `board_doc_sync.live_page_paths`
# 这个权威取数口认（在册即真身写的），模板段以 `doc_template_sync` 渲染结果认。
# ---------------------------------------------------------------------------
def _auto_zone_verified(
    p: dts.PageInfo, begin: str, inner: str,
    schemas: dict[str, dts.Schema],
    expected_zones: dict[str, str],
) -> bool:
    """机器段是否由写盘口生成（可信）——只有可逐字节现算复核、**且当场复核通过**的段才放行。

    席 S46（2026-09-22）：BOARD-AUTO 段旧按「`live_page_paths` 在册」放行＝路径成员豁免
    （K-2 同型）；改认机制 (b) 的复现证据 `b_ok`。
    席 S78（P-41，Critical，2026-09-22）：`b_ok` 是**页级**判定，旧 board 分支 `return p.rel
    in b_ok` ⇒ 同一枚生成页再嵌一对 `BOARD-AUTO` 注释、第二段里写裸事实也照样放行（段被剥、
    两面不记，S70 内存注毒实证 225 枚静默）。现改与 TEMPLATE 侧**同构**——逐段比对、段数与内容
    一起比、多一段即红（`_board_zone_inners(p.text) == [expected]`），不用「只允许一段」形状豁免糊。
    """
    if begin != dts.TPL_AUTO_BEGIN:  # BOARD-AUTO 段
        expected = expected_zones.get(p.rel)
        if expected is None:
            return False  # 无板块写盘口（在册名单外的标记形）→ 不可信
        # P-41（席 S78，2026-09-22）与 TEMPLATE 侧同构——逐段比「这一段」是否等于写盘口现算值。
        # 旧写 `return p.rel in b_ok` 是**页级**判定 ⇒ 同一枚生成页再嵌一对真 BOARD-AUTO 段、
        # 第二段写裸事实也照样被 b_ok 放行（S70 内存注毒实证 225 枚静默、仅 3 枚 board-meta 报）。
        # 改按段内文本比对：真生成段命中 expected→可信（不误伤正常 225 页）；多出的伪段 ≠ expected→
        # 不可信，其裸事实由 K-1 记 UNVERIFIED_AUTO_ZONE（真藏事才红；正文里以行内码引用标记字面量
        # 不算「多一段」，因 K-1 只在 `fact_findings(human_lines(seg))` 非空时才咨询本函数）。
        got = inner.replace(f"{bds.AUTO_NOTE}\n\n", "", 1).strip()
        return got == expected
    if p.fm is None or p.fm.template not in schemas:
        return False  # 有 TEMPLATE-AUTO 却无在册模板＝无写盘口
    schema = schemas[p.fm.template]
    ctx = dts.PageCtx(rel=p.rel, body_no_fm=p.text)
    values, viol = dts.resolve_params(schema, p.fm, ctx)
    if viol:
        return False  # 参数不合法→渲染结果不可信，段内内容无从核对
    expected = dts.render_block(schema, values).strip()
    got = inner.replace(dts.TPL_AUTO_NOTE + "\n\n", "", 1).strip()
    return got == expected


# ---------------------------------------------------------------------------
# 席 TX130（2026-09-23，用户裁定件 R0）：G-T1 **输出口径**分账——对外欠账 / 过程件登记
# R0 的改判理由（用户原话转述）：旧尺把「席位自己干活产生的工作记录与说明书」和
# 「该给用户看的正式文档」混进同一格 ⇒ 越干活数越大、结构上永不到 0（本席现算 1391 枚里
# 1022 枚是过程件，见 SEAT-TX130.md §2）。R0 明写**这不是缩扫描面**：扫描面一寸不缩，
# 只把「债」与「登记」分账，且今后一律报两栏、不得混成一格。
#   · 欠账（判据用数）＝对外正式交付面（`docs/**` 的 design/handbook/catalog/boards/
#     acceptance/route-matrix/人格件与根层交付件等）里未套头者；
#   · 登记（不进欠账）＝四类过程件（`seat-report`/`sdd-brief`/`sdd-ledger` ＋ R1 将立的
#     `parked`）：它们**照样必须套头**，套不上只登记不记债。
# 类别判据**派生**、零第二份清单（禁第二真身）：
#   · 宇宙＝`dt.CONTENT_CATEGORIES`（注册表唯一真身），「是否文档面」逐类问其 `surface` 字段；
#     `generated_by` 非空的板块类**仍算对外面**（`docs/boards/**` 是给使用者看的交付物；
#     它们平日被机制 (b) 复现放行而不进 t1，一旦复现失败就是对外欠账，方向只准更严）；
#   · 「是否过程件」复用 S78 为 G-T3 分流立的同一真身 `PROCESS_LOG_CATEGORIES`
#     （语义＝`.superpowers/**` 专属过程日志 cid 集），**不另立名单**；R1 落地 `parked` 类时
#     把 cid 并入那一份真身即自动流进本投影 ⇒ 本席今日零改码即覆盖 R0 点名的四类；
#   · S126 的「过程件误住 `design-spec`」重判腿经 `ledger_bucket_of` 参与判定，但其落点恒为
#     既有桶 `root-report` ∈ 历史页类 ⇒ 在 R0 下仍算**对外欠账**（保守方向：宁可多记债，
#     绝不把 `docs/**` 下的页放走＝绝不借分账之名降账）。
# R0 另要求「同刻出三值 + 取数时刻 + 证明未动任何页字节」：三值在**同一次 `compute()`** 里数好，
# 并对管辖页**原始字节**求一支总指纹（`sha256(sorted "rel\0sha256(bytes)")`）——换口径前后
# 该指纹必须逐字相等，不等即说明有页被写过（本席交付含前后实测，见报告 §3）。
# **上限策略：本腿不自立任何上限**（R0 是口径变更、不是新账）；G-T1 的执法仍由
# `tests/test_taxonomy_spec_gates.py` 的在册常数 `T1_CEILING` 管，其断言改判归席 TX132，
# 本席对该测试件零动笔（简报《TX130》边界段原文）。
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 席 S230（2026-09-25，用户裁定 **R0 = A**）：**欠账分母的定义域真身**（一张表）。
#
# R0=A 的原话＝「gitignored 的施工过程稿不进受管欠账的分母，但**总账栏不许消失**」。
# 席 TX130 已把这口径落在 **G-T1**（`t1_debt_official` / `t1_registered_process`）。本席把
# **同一口径**扩到 G-T2 / G-T4 / 模板体检三面——**判据不落在那三面各自的门里**，而是全部
# 走下面这一张表 + 一支分账器（禁「多个文件各写一份什么算过程稿」＝禁第二真身）。
#
# 与 3.A 的 `FACE_BY_CATEGORY` 完全同构，只是**换了轴**：那张表判「裸事实记哪一面」，
# 这张表判「这一页进不进欠账分母」。值口径（每一枚在册类别显式一行，与 `FACE_BY_CATEGORY`
# 键集逐枚对齐）：
#   1. `PROCESS_LOG_CATEGORIES`（S78 真身，`.superpowers/**` 专属）⇒ **register**＝过程稿，
#      仍被扫描、仍出总账栏、仍可在普查里点名，只是不进被判欠账；
#   2. 其余每一枚在册类别 ⇒ **debt**＝对外正式面，进欠账分母。历史台账页
#      （`HISTORICAL_PAGE_CATEGORIES`）在 R0=A 下**算 debt**——它们是「给用户看的正式文档」
#      （`root-report`/`handbook`/`acceptance`/`root-handoff`），R0 的豁免面**只准 `.superpowers/**`
#      那一圈**，不许顺手把 `docs/**` 也放走（保守方向：宁可多记债，绝不借分账降账）。
# **每一枚在册类别必须在此显式有一行**——「没登记＝免检」是裁定明令禁止的形态，故缺行既
# 不作默认也不静默放行：`r0_debt_bucket_strict()` 当场抛、常驻总集性锁点名红（照 3.A 的形状）。
# 「是否过程稿」这一**分类**只由路径派生的 category 决定（`classify()` → 本表），**模板头一律
# 不参与**——一张页不得靠自戴 `template: seat-report` 把自己从欠账分母里降级为过程稿
# （`r0_self_exemption_findings` 执法，与 3.A 的 `header_exemption_findings` 同款）。
R0_DEBT_OFFICIAL: str = "debt"
R0_DEBT_REGISTER: str = "register"
R0_DEBT_BUCKETS: tuple[str, ...] = (R0_DEBT_OFFICIAL, R0_DEBT_REGISTER)

#: 过程日志三 cid ⇒ `register`，其余（板块/规格/目录/活文档/历史台账/人格/代码面）一律 `debt`。
#: 键集镜像 `FACE_BY_CATEGORY`（同一批在册类别，禁第二份类别清单）；register↔S78 集合的
#: 同判由 `r0_denominator_gaps` 强制，一旦有人往 `PROCESS_LOG_CATEGORIES` 增删 cid 而未同步
#: G-T3 桶表，两把体检会同时点名。
R0_DEBT_BUCKET_BY_CATEGORY: dict[str, str] = {
    cid: (R0_DEBT_REGISTER if cid in PROCESS_LOG_CATEGORIES else R0_DEBT_OFFICIAL)
    for cid in FACE_BY_CATEGORY
}


def r0_debt_bucket_strict(category: str) -> str:
    """类别 → 欠账分母桶（`debt`/`register`）。**未登记即抛**：缺行不是免检（R0=A 明令）。"""
    try:
        return R0_DEBT_BUCKET_BY_CATEGORY[category]
    except KeyError:
        raise LookupError(
            f"类别 {category!r} 在欠账分母定义域 R0_DEBT_BUCKET_BY_CATEGORY 里没有显式一行——"
            "缺行不是免检，新增类别必须同批补一行（否则它既不进欠账也不进登记＝就地蒸发）"
        ) from None


def is_process_artifact_category(category: str) -> bool:
    """类别是否 R0 口径的「过程稿」（不进欠账分母、只登记：席位工作记录／波次说明书／台账同类）。

    判据不自立名单：走分母定义域表 `R0_DEBT_BUCKET_BY_CATEGORY`（其 register 集与 S78 真身
    `PROCESS_LOG_CATEGORIES` 由 `r0_denominator_gaps` 强制同判，分叉即红）。
    """
    return r0_debt_bucket_strict(category) == R0_DEBT_REGISTER


def is_process_artifact_page(p: dts.PageInfo) -> bool:
    """页级 R0「过程件」判定——走 `ledger_bucket_of`（S78 类别真身 ∪ S126 内容重判腿）。

    与 G-T3 的 `face_of_history_page` 返回 `skip` 的那半腿同源同判（同一支桶判据，
    禁第二条码路）；S126 重判者落 `root-report` ⇒ 恒为「非过程件」＝留在对外欠账，方向保守。
    **只读路径派生类别，绝不读 front-matter**（分桶不许由被检者自己戴的头决定）。
    """
    bucket = ledger_bucket_of(p)
    return r0_debt_bucket_strict(bucket if bucket is not None else p.category) == R0_DEBT_REGISTER


def r0_process_rels(pages: list[dts.PageInfo]) -> set[str]:
    """把一组页归约成「过程稿 rel 集」——**唯一**的页→过程稿投影口。

    消费者：①模板体检门（`tests/test_doc_template_pipeline.py` 握有 `dts._collect()` 的页表，
    从这里取 `process_rels`）；②`compute()` 末尾的 R0=A 反缩水人口腿。
    三面（T1/T2/T4）在主循环里**逐页**判（那里正握着 `PageInfo`，见 `is_process_artifact_page`
    的调用点）——同一支判据、同一次遍历，不是第二处落点；判据本体只此一份。
    禁在别处再写一遍 `p.rel.startswith(".superpowers/")` 或再查一次类别（那会变成第二处判据
    落点：改一处、另一处仍按旧集合算，数就分叉）。判定发生在还握有 `PageInfo` 的地方，事后按
    `rel` 重新 `classify()` 会走出第二套判据，故在此判。
    """
    return {p.rel for p in pages if is_process_artifact_page(p)}


def entry_subject(entry: str) -> str:
    """账条目开头的「主体」：按首个 `:` 或 `#` 切、取最左段并去空白。

    三种在册形态：t1 生成物条目 `"{rel}#{原因}"`／页级条目 `"{rel}: {罪状}"`／模板级条目
    `"DEAD_PARAM {tid}: ..."`。页级主体＝rel（拿去比 process_rels）；模板级主体＝`DEAD_PARAM {tid}`
    （不是任何页 rel ⇒ 落非过程稿＝进欠账，方向保守，绝不借分账放走模板体本身的债）。
    对 t1 逐字节等价性：t1 条目头段无一含 `:`（SEAT-S230 §0.3 现算），故与旧
    `e.split("#",1)[0]` 对 t1 分类零差异。
    """
    return re.split(r"[:#]", entry, 1)[0].strip()


def r0_entry_is_process(entry: str, process_rels: set[str]) -> bool:
    """一条账目是否「过程稿条目」＝其主体落在 `process_rels`（判据唯一走 `entry_subject`）。"""
    return entry_subject(entry) in process_rels


def r0_class_claimed_by_header(p: dts.PageInfo) -> tuple[str, str] | None:
    """**反面尺（只喂自证锁，永不进账）**：这一页的 front-matter 头「声称」自己属于哪一类、
    那一类在**欠账分母表**里记哪一桶。返回 `(声称类别, 桶)`，或 `None`＝头不构成分流申请。

    判 `None` 的三种情形与 3.A 的 `class_claimed_by_header` 逐条同形（无头/无 template、
    该模板被零枚或多枚类别认领、头指回本页路径自己那一类＝纯版式声明），只是投影到 debt 轴。
    """
    if p.fm is None or not p.fm.template:
        return None
    owners = [c.cid for c in dt.CONTENT_CATEGORIES if c.template == p.fm.template]
    if len(owners) != 1:
        return None
    claimed = owners[0]
    if claimed == p.category:
        return None
    return claimed, r0_debt_bucket_strict(claimed)


def r0_self_exemption_findings(pages: list[dts.PageInfo]) -> list[str]:
    """「欠账分母不许被自戴的头降级」的机检形态（R0=A 要的那把锁，照 3.A 的形状）。

    红＝这一页**按路径/分母表**该进欠账（debt），却靠自己的 front-matter 声称了一个
    `register`（过程稿）类别 ⇒ 想把自己挪出欠账分母＝自我豁免。反方向（头买更严或同桶）不算红。
    分桶只由路径派生，被检者挑不了尺子。
    """
    out: list[str] = []
    for p in pages:
        claimed = r0_class_claimed_by_header(p)
        if claimed is None:
            continue
        cid, hat_bucket = claimed
        bucket = ledger_bucket_of(p)
        path_bucket = r0_debt_bucket_strict(bucket if bucket is not None else p.category)
        if path_bucket == R0_DEBT_OFFICIAL and hat_bucket == R0_DEBT_REGISTER:
            out.append(
                f"R0_SELF_EXEMPTION_VIA_TEMPLATE {p.rel}: 路径/分母表判它进欠账（{R0_DEBT_OFFICIAL}），"
                f"但它的 template={p.fm.template if p.fm is not None else None!r}"
                f"（声称类别 {cid!r}）想把这一页降级为过程稿（{R0_DEBT_REGISTER}）＝挪出欠账分母——"
                "分桶不许由被检者自己戴的头决定"
            )
    return out


def r0_denominator_gaps(
    pages: list[dts.PageInfo] | None = None,
    *,
    extra_categories: set[str] | None = None,
) -> list[str]:
    """欠账分母定义域的体检（R0=A 的另一半：不许「没登记＝免检」，也不许两套口径分叉）。

    与 3.A 的 `bucket_table_gaps` 同构，只是换轴（debt/register 而非 line/page/skip）：
    · 注册表在册 / 页面真出现 / 路径判据可达 的类别 ⇒ 分母表必须有显式一行（缺行＝红）；
    · 分母表有行但三处都不认 ⇒ 红（幽灵行＝一把量不存在对象的尺子）；
    · 桶值必须是 debt/register 之一；
    · **register 集必须恰等于 `PROCESS_LOG_CATEGORIES`**（S78 真身）——两套口径分叉＝
      「说是过程稿、却又进欠账」或「过程稿被顶进欠账分母 / 豁免面被偷偷放大」。
    """
    registry = {c.cid for c in dt.CONTENT_CATEGORIES}
    domain = registry | {p.category for p in (pages or [])} | (extra_categories or set())
    gaps: list[str] = []
    for cid in sorted(domain - set(R0_DEBT_BUCKET_BY_CATEGORY)):
        gaps.append(
            f"R0_BUCKET_ROW_MISSING {cid}: 注册表/页面/路径判据认这一类，"
            "但欠账分母定义域没有显式一行（缺行≠免检）"
        )
    for cid in sorted(set(R0_DEBT_BUCKET_BY_CATEGORY) - domain):
        gaps.append(
            f"R0_BUCKET_ROW_ORPHAN {cid}: 分母表有行，但注册表、页面、路径判据三处都不认这一类（幽灵行）"
        )
    for cid, bucket in sorted(R0_DEBT_BUCKET_BY_CATEGORY.items()):
        if bucket not in R0_DEBT_BUCKETS:
            gaps.append(f"R0_BUCKET_VALUE_UNKNOWN {cid}: 桶值 {bucket!r} 不在 {R0_DEBT_BUCKETS}")
    register_now = {
        cid for cid, b in R0_DEBT_BUCKET_BY_CATEGORY.items() if b == R0_DEBT_REGISTER
    }
    for cid in sorted(PROCESS_LOG_CATEGORIES - register_now):
        gaps.append(
            f"R0_BUCKET_VS_PROCESS_SET {cid}: S78 过程日志真身认它是过程稿，"
            "但欠账分母表没把它记成 register（＝过程稿又被顶回欠账分母）"
        )
    for cid in sorted(register_now - PROCESS_LOG_CATEGORIES):
        gaps.append(
            f"R0_BUCKET_VS_PROCESS_SET {cid}: 欠账分母表把它记成 register（过程稿），"
            "但 S78 真身 PROCESS_LOG_CATEGORIES 不认（＝豁免面被偷偷放大）"
        )
    return gaps


def official_delivery_categories() -> frozenset[str]:
    """「对外正式交付面」类别集——由分母定义域表派生，本函数零枚类别名字面量。"""
    return frozenset(
        c.cid
        for c in dt.CONTENT_CATEGORIES
        if c.surface == "md" and r0_debt_bucket_strict(c.cid) == R0_DEBT_OFFICIAL
    )


def split_debt_by_accounting(
    entries: list[str], process_rels: set[str], *, ruler: str
) -> dict[str, object]:
    """把**任意一面**的账目按「对外欠账 / 过程稿登记」拆两栏，自带恒等式与重叠自检。

    席 S230（R0=A）：这支是 G-T2 / G-T4 / 模板体检三面共用的分账器；G-T1 经
    `split_t1_by_accounting` 委托到这里（同一支恒等式/互斥自证，禁各面各写一份过滤式＝
    第二处判据落点）。主体提取唯一走 `entry_subject`，是否过程稿唯一走调用方交来的
    `process_rels`（由 `r0_process_rels` 在主循环内握有 `PageInfo` 时算好），本函数不 classify、
    不查类别——那会是第三处判据。
    """
    debt = [e for e in entries if entry_subject(str(e)) not in process_rels]
    registered = [e for e in entries if entry_subject(str(e)) in process_rels]
    debt_rels = {entry_subject(str(e)) for e in debt}
    reg_rels = {entry_subject(str(e)) for e in registered}
    return {
        "ruler": ruler,
        "total_old_ruler": len(entries),
        "debt_official": len(debt),
        "registered_process": len(registered),
        # 两栏清单与两栏计数**同一支算出**（调用方直接取这里的清单，禁再抄一遍过滤式）。
        "debt_entries": debt,
        "registered_entries": registered,
        # 分账只加格子、不吞条目：两栏之和必须等于总账，且主体集合互斥。
        "partition_ok": len(debt) + len(registered) == len(entries),
        "overlap_rels": sorted(debt_rels & reg_rels),
        "debt_rel_count": len(debt_rels),
        "registered_rel_count": len(reg_rels),
        "official_categories": sorted(official_delivery_categories()),
        "debt_by_cat": dict(Counter(dts.classify(r) for r in debt_rels)),
        "registered_by_cat": dict(Counter(dts.classify(r) for r in reg_rels)),
    }


def split_t1_by_accounting(
    t1: list[str], process_rels: set[str]
) -> dict[str, object]:
    """把 t1 按「对外欠账 / 过程件登记」拆两栏（薄封装，交给共用分账器）。

    行为与席 TX130 首版逐字节等价：主体提取 `entry_subject` 对 t1 条目（头段无 `:`）恒等旧
    `e.split("#",1)[0]`（SEAT-S230 §0.3 现算零差异），`ruler` 文案原样保留（常驻核账锁认它）。
    """
    return split_debt_by_accounting(
        t1,
        process_rels,
        ruler="R0（2026-09-23 用户裁定：欠账只算对外正式面，过程件只登记）",
    )


def pages_bytes_fingerprint(pages: list[dts.PageInfo]) -> dict[str, object]:
    """管辖页**原始字节**总指纹 + 取数时刻（只读；证「换口径未动任何一页一字节」）。

    逐页 `sha256(读盘原始字节)`（不走 `PageInfo.text`——那份是 `errors="replace"` 解码后的文本，
    会抹平非法字节），按 `rel` 排序拼 `rel\0sha` 再求总 sha256。
    读盘异常 ⇒ 记 `UNREADABLE:<原因>` 并照常计入指纹（绝不静默跳页：跳页会让指纹虚高地变小、
    把「有页被动过」洗成「看起来没动过」）。
    """
    rows: dict[str, str] = {}
    for p in pages:
        try:
            rows[p.rel] = hashlib.sha256(p.path.read_bytes()).hexdigest()
        except OSError as exc:  # 不跳页：把异常本身编进指纹
            rows[p.rel] = f"UNREADABLE:{exc}"
    agg = hashlib.sha256(
        "\n".join(f"{k}\0{v}" for k, v in sorted(rows.items())).encode("utf-8")
    ).hexdigest()
    unreadable = sorted(k for k, v in rows.items() if v.startswith("UNREADABLE:"))
    return {
        "taken_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "page_count": len(rows),
        "pages_bytes_digest": agg,
        "unreadable_pages": unreadable,
    }


# ---------------------------------------------------------------------------
# 主计算
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 席 S119（2026-09-22，G-T5 的「孤儿模板腿」，依据 SEAT-S111 的 C-3）
# 既有 `orphan_tpls` 只查一个方向：**模板在册却无类别引用**；反方向从不查——
# 「类别认领了模板、模板却一张页也驱动不了」可以永久无责（现算 22 枚在册模板里 21 枚
# 驱动 0 页，门对此一字不提）。本腿补上反向账，并按两类**分开点名**：
#   · code_surface —— 该模板管辖的对象是**代码件**（注册表 `surface=="code"`），
#     而 G-T1 只数 md ⇒ 数学上恒 0，属席 S116 的面（**仍照登记进账，绝不排除**——
#     排除＝缩小扫描面＝§0 六禁）。
#   · real_debt —— 该桶有 md 页可管、却一张都没挂上驱动 ⇒ **真债**。
# 另记三态只为不把不同性质的 0 混成一个数：load_failed / unclaimed / md_bucket_empty。
# 只读判据：不写盘、不新建类别表——类别→模板一律走 `registered_template()` 唯一真身。
# 上限策略：本腿**今日只登记不设上限**（没有可抬的东西；转正需该门 owner 定基线）。
# ---------------------------------------------------------------------------
ORPHAN_CLASS_ORDER: tuple[str, ...] = (
    "code_surface",
    "real_debt",
    "md_bucket_empty",
    "load_failed",
    "unclaimed",
)
ORPHAN_CLASS_NOTE: dict[str, str] = {
    "code_surface": "结构性 0：管辖对象是代码件（G-T1 只数 md）⇒ 属席 S116 面",
    "real_debt": "真债：该桶有 md 页可管却无人驱动",
    "md_bucket_empty": "无米之债：桶是 md 类但今日 0 页可管",
    "load_failed": "模板文件在盘上但 @schema 装载失败 ⇒ 无从驱动",
    "unclaimed": "无类别认领该模板（与既有「孤儿模板」腿同案，双记不互替）",
}


def page_known_fact_keys(
    p: dts.PageInfo, schemas: dict[str, dts.Schema]
) -> set[str]:
    """席 S131（2026-09-22）：G-T3 面A 两处调用点的**在册参数取数胶水**。

    参数集合唯一来源＝`dfd.declared_fact_keys`（复用 `@schema` 解析，本文件零第二套
    参数表）。页侧模板身份门已解析过（`p.fm` 经 `annotate()`）时直接喂 `template=`
    最省；`p.fm` 为 None ⇒ 传 None，由取数口从整页原文现读 front-matter（S106 明文
    回落形）。取数口自身抛错（如解析件缺 `params`）时**本函数不接不吞**、原样上抛
    ⇒ 门当场崩、错误原文点名（fail-closed）——绝不静默退回「None＝无条件摘除」的
    旧免检行为（那正是 S106 要堵的洞在调用点侧的复发）。
    `schemas` 由 `compute()` 顶部一次性装载后传入＝批量只引用、零逐页重复读盘
    （`declared_fact_keys` 的在册批量契约）。
    """
    return dfd.declared_fact_keys(
        p.text,
        template=p.fm.template if p.fm is not None else None,
        schemas=schemas,
    )


def orphan_templates(
    pages: list[dts.PageInfo],
    schemas: dict[str, dts.Schema],
    template_stems: set[str],
    *,
    categories: tuple[dt.CategoryDef, ...] | None = None,
) -> dict[str, list[str]]:
    """在册模板 × 实际驱动 0 页 ⇒ 孤儿账（分类**全部**由注册表派生，本函数零自造类别表）。

    「驱动」只认机制 (a)（页首 `template:` 头）且**未套错模板**的页——套错模板的页在
    G-T1 不销籍（`driven()` 同一判据），故也不许替这枚模板撑门面。
    「桶内可管页」一律走 `registered_template()`（md 且非生成器所有），与 G-T5 其它腿同源。
    """
    cats = dt.CONTENT_CATEGORIES if categories is None else categories
    claiming: dict[str, list[dt.CategoryDef]] = {}
    for c in cats:
        if c.template:
            claiming.setdefault(c.template, []).append(c)

    governed: Counter[str] = Counter()
    bucket_md: Counter[str] = Counter()
    for p in pages:
        want = registered_template(p.category)
        if want:
            bucket_md[want] += 1
        if p.fm is not None and p.fm.template in schemas and category_mismatch(p, schemas) is None:
            governed[p.fm.template] += 1

    out: dict[str, list[str]] = {k: [] for k in ORPHAN_CLASS_ORDER}
    for t in sorted(set(template_stems) | set(schemas) | set(claiming)):
        if governed.get(t, 0):
            continue
        owners = claiming.get(t, [])
        if not owners:
            kind = "unclaimed"
        elif t not in schemas:
            kind = "load_failed"
        elif all(c.surface == "code" for c in owners):
            kind = "code_surface"
        elif bucket_md.get(t, 0) == 0:
            kind = "md_bucket_empty"
        else:
            kind = "real_debt"
        out[kind].append(
            f"{t}: 驱动 0 页｜认领类别={[c.cid for c in owners] or '（无）'}｜"
            f"桶内可管 md 页 {bucket_md.get(t, 0)}｜{ORPHAN_CLASS_NOTE[kind]}"
        )
    return out


# ---------------------------------------------------------------------------
# 席 S152（2026-09-22，第二十四批）：板块正文**完整度**账（G-B1）——第一次可执法判据。
# S89 交卷时披露「正文完整度至今没有自动判据（只有页内自述）」，本席把它变成可复算的账。
# 四列**全部由既有尺子派生，零新建定义**（禁第二真身）：
#   · 人工区字符数 ← `dfd.strip_auto_zones`（人写区唯一取数口）＋本文件 `_no_fences`（G-T2 同源）
#   · 是否含「（待写」← 字面出现次数（简报点名的列）**且**判据用「骨架占位句逐字未填」——
#     占位句从生成器骨架真身 `bds.L1/L2/L3_BODY` 派生，故规则自述句（引用「（待写」三字本身）
#     不会被误判成空壳（S89 实测该族 2 页）
#   · 槽位齐备度  ← `BOARD_CANON`（= `_conventions.md` 骨架契约的机器形）＋ `section_findings`
#     的 `SECTION_MISSING`（缺必选槽）与可选槽命中数，本席零第二份骨架表
#   · 是否只有指针无本体 ← `dfd.AUTHORITY_PHRASE_RE`（指针短语唯一真身）＋ `dfd._INLINE_CODE_RE`
#     （行内码真身）＋ `dfd._CJK_RE`（CJK 尺真身）：剥尽指针短语 / 反引号件 / 链接目标后**不含任何汉字**的行＝指针行
# 分档（每页恰一档，四态互斥可数）：`完整` / `骨架残留` / `纯指针` / `机器整册所有`。
# 最后一档的判据不是路径豁免，而是机制 (b) 的复现证据 `b_ok`（席 S46 真身）——人写区一行都没有、
# 且机器段当场逐字节复现成功 ⇒ 这本账与该页无关（整页归生成器），复现失败则落 `骨架残留`。
# **上限策略：本腿今日只登记不设上限**（新账）。转正时首届核账值须由该门 owner 在收口窗取，
# 本席不自定；防"未来有人塞上限而不核账"的结构锁在 `tests/test_taxonomy_spec_gates.py`（S152 段）。
# ---------------------------------------------------------------------------
BODY_TIER_ORDER: tuple[str, ...] = ("完整", "骨架残留", "纯指针", "机器整册所有")
#: 简报点名的字面标记列（判据不用它分档，分档用下面的骨架占位句逐字比对）。
TODO_MARK: str = "（待写"
_LINK_TARGET_RE = re.compile(r"\]\([^)]*\)")


def _human_area(text: str) -> str:
    """板块页「人写区」整段文本：剥 front-matter、剥机器段（`dfd.strip_auto_zones`）、剥围栏。

    与 `dfd.human_lines` 的差别只有一处、且是本账必需的：**保留行内码**——
    指针列要看得见 `` `docs/x.py:fn` `` 这类真身引用，抹掉它就把指针页误判成空行。
    """
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
        start = end + 1 if end else 0
    return "\n".join(_no_fences(dfd.strip_auto_zones("\n".join(lines[start:]))))


def slot_bodies(text: str) -> dict[str, str]:
    """`H2 主干名 → 该节正文`（骨架与页**同一支**取形，故「未填」判定是逐字比对而非猜）。"""
    heads = list(_H2_RE.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out[trunk(m.group(1))] = text[m.end() : stop].strip()
    return out


#: 骨架真身派生：类别 → (节名 → 骨架原文)。值取自 `board_doc_sync`，本文件不抄第二份。
SKELETON_SLOT_BODIES: dict[str, dict[str, str]] = {
    cat: slot_bodies(body) for cat, body in BOARD_CANON_SOURCES.items()
}


def is_pointer_line(line: str) -> bool:
    """一行是否为**纯指针句**：剥尽指针短语、行内码、链接目标后不含任何汉字（CJK 尺＝`dfd._CJK_RE`）。"""
    rest = _LINK_TARGET_RE.sub(" ", dfd._INLINE_CODE_RE.sub(" ", dfd.AUTHORITY_PHRASE_RE.sub(" ", line)))
    return dfd._CJK_RE.search(rest) is None


def board_body_completeness_row(
    p: dts.PageInfo,
    *,
    b_ok: set[str],
    canon: list[tuple[str, bool]] | None,
) -> dict[str, object]:
    """单页四列 + 分档（只读判据：不写盘、不改任何页）。

    `canon` 为该页类别的板块骨架（`BOARD_CANON`），`None` ＝该页无板块骨架（`_meta`/整册机器件），
    此时槽位列记 `n/a`（不猜骨架），只按人工区文本与机器段复现证据分档。
    """
    human = _human_area(p.text or "")
    heads = headings(human)
    bodies = slot_bodies(human)
    content = [ln for ln in human.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    skel = SKELETON_SLOT_BODIES.get(p.category, {})
    unfilled = [name for name, skeleton in skel.items() if skeleton and bodies.get(name) == skeleton]
    missing_required: list[str] = []
    optional_hit = 0
    if canon is not None:
        missing_required = [
            name for name, optional in canon if not optional and name not in set(heads)
        ]
        optional_hit = sum(1 for name, optional in canon if optional and name in set(heads))
    pointer_only = bool(content) and all(is_pointer_line(ln) for ln in content)
    if not content:
        tier = "机器整册所有" if p.rel in b_ok else "骨架残留"
    elif unfilled or missing_required:
        tier = "骨架残留"
    elif pointer_only:
        tier = "纯指针"
    else:
        tier = "完整"
    return {
        "rel": p.rel,
        "category": p.category,
        "human_chars": len("".join(content).strip()),
        "todo_hits": human.count(TODO_MARK),
        "unfilled_slots": unfilled,
        "missing_required_slots": missing_required,
        "slot_total": (len(canon) if canon is not None else None),
        "slot_required": (sum(1 for _n, o in canon if not o) if canon is not None else None),
        "slot_optional_hit": optional_hit,
        "pointer_only": pointer_only,
        "tier": tier,
    }


def board_body_completeness(
    pages: list[dts.PageInfo], *, b_ok: set[str]
) -> dict[str, object]:
    """板块管辖面（`docs/boards/**`）逐页完整度账 + 四档枚数（含 0 也如实记）。"""
    rows = [
        board_body_completeness_row(p, b_ok=b_ok, canon=BOARD_CANON.get(p.category))
        for p in pages
        if p.rel.startswith("docs/boards/")
    ]
    tiers = {t: 0 for t in BODY_TIER_ORDER}
    for r in rows:
        tiers[str(r["tier"])] += 1
    living = [int(r["human_chars"]) for r in rows if r["tier"] != "机器整册所有"]
    return {
        "rows": rows,
        "page_total": len(rows),
        "tiers": tiers,
        "min_human_chars": min(living) if living else 0,
        "pages_with_todo": sum(1 for r in rows if int(r["todo_hits"]) > 0),
        "pages_pointer_only": sum(1 for r in rows if r["tier"] == "纯指针"),
        "slot_total_rows": sum(1 for r in rows if r["slot_total"] is not None),
    }


# ---------------------------------------------------------------------------
# 席 S175（第二十七批）：G-T1 甲账「波内拆分」只读腿
#   —— 只加一栏数，绝不把任何页排除出账（缩扫描面＝一票否决）。
# 判据：路径是否存在于**不可变基线提交** WAVE_BASE_COMMIT（`git ls-tree` 现取）。
#   存在 ⇒「波前存量」；不存在（含未跟踪 / 本波新建）⇒「本波新建」。
#   为何不可被写盘绕过：基线是一枚**冻结的 commit 对象**，其文件树由内容哈希寻址，
#   任何对**工作树**的写入（改内容、改 mtime、新建文件）都无法把一枚页塞进或移出
#   `a08d34c^{tree}`；只有 `git commit` 会改 HEAD，但改不了 `a08d34c` 本身这棵树。
#   对照：mtime 可被 `os.utime` 或复制随时改写（拿它当判据＝免罪符，本席明拒）。
# 两栏之和恒等于 `t1`：按 `rel` 做二值集合判定、逐条只归一栏 ⇒ 不重不漏（`identity_ok`）。
# 本腿今日只登记不设上限——「转正」的基线须由该门 owner 在收口窗自定（S175 不自定）。
# ---------------------------------------------------------------------------
WAVE_BASE_COMMIT = "a08d34c"


def git_wave_base_paths(commit: str, root: Path = ROOT) -> tuple[frozenset[str], str]:
    """现取基线提交 `commit` 的文件树（全量路径集合，posix 风格）。

    取数失败（commit 不可达 / 非 git 仓 / 无 git）⇒ 返回 (frozenset(), 人话原因)，
    **绝不返回被截断的集合**（截断＝部分在册页被误判「本波新建」＝方向放水）。
    调用方据此置 `degraded`，把拆分方向保守地全落「本波新建」并在报告点名。
    """
    try:
        proc = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", commit],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:  # 无 git 可执行等
        return frozenset(), f"git 不可用：{exc}"
    if proc.returncode != 0:
        return frozenset(), (
            f"基线提交 {commit} 取树失败（rc={proc.returncode}）："
            f"{proc.stderr.strip()[:180] or '无 stderr'}"
        )
    paths = {ln for ln in proc.stdout.splitlines() if ln.strip()}
    if not paths:
        return frozenset(), f"基线提交 {commit} 的文件树为空＝取数异常，拒当免罪符"
    return frozenset(paths), ""


def split_t1_by_wave(
    t1: list[str], base: frozenset[str] | None, base_err: str
) -> dict[str, object]:
    """把 t1（每条 `rel` 或 `rel#原因`）按基线在册性拆成两栏。

    `base` 为 None（取数降级）⇒ 逐条判「本波新建」（保守：宁可高估新账、绝不误销）。
    """
    stock: list[str] = []
    new: list[str] = []
    for entry in t1:
        rel = entry.split("#", 1)[0]
        if base is not None and rel in base:
            stock.append(entry)
        else:
            new.append(entry)
    stock_rels = {e.split("#", 1)[0] for e in stock}
    new_rels = {e.split("#", 1)[0] for e in new}
    # 「两栖页」＝同一 rel 既有在册条目又有不在册条目落进两栏：因集合判定只认 rel，恒空；
    # 若非空即判据被写坏（如把带 `#` 后缀当成不同路径），必须点名。
    amphibious = sorted(stock_rels & new_rels)
    total = len(t1)
    return {
        "base_commit": WAVE_BASE_COMMIT,
        "degraded": base is None,
        "base_err": base_err,
        "base_size": (len(base) if base is not None else 0),
        "stock": stock,
        "new": new,
        "stock_count": len(stock),
        "new_count": len(new),
        "total": total,
        "identity_ok": (len(stock) + len(new)) == total,
        "amphibious": amphibious,
        "per_cat_stock": dict(Counter(dts.classify(e.split("#", 1)[0]) for e in stock)),
        "per_cat_new": dict(Counter(dts.classify(e.split("#", 1)[0]) for e in new)),
        "stock_sample": stock[:5],
        "new_sample": new[:5],
    }


def compute(root: Path = ROOT) -> dict[str, object]:
    schemas: dict[str, dts.Schema] = {}
    schema_errors: list[str] = []
    template_stems: set[str] = set()
    for path in sorted(dts.TEMPLATE_DIR.glob("*.md")):
        template_stems.add(path.stem)
        try:
            sch = dts.parse_schema_text(
                path.read_text(encoding="utf-8", errors="replace"), path.stem
            )
        except dts.SchemaError as exc:
            schema_errors.append(f"SCHEMA_ERROR {exc}")
            continue
        # 席 S153：第三个装载点接同一支判据（一处判、三处接；不建第二本自由槽账）。
        # 失格模板不入 schemas ⇒ 引用它的页按 TEMPLATE_MISSING 记（方向只准加严）。
        guard = dts.freeform_guard({path.stem: sch})
        if guard:
            schema_errors.extend(guard)
            continue
        schemas[path.stem] = sch

    gen_map = generated_rels(root)
    gen_all = {r for paths in gen_map.values() for r in paths}
    pages = [
        p
        for p in dts.annotate(dts.walk_content_pages(root), schemas)
        if not p.rel.startswith(dt.TEMPLATE_SOURCE_PREFIX)
    ]
    labels = {p.category for p in pages}

    # --- 机制 (b)（席 S46）：生成页逐页当场重渲染、字节等值才记「已驱动 (b 形)」。
    expected_zones = board_expected_zones()
    b_ok: set[str] = set()
    b_drift: list[str] = []
    for p in pages:
        if p.rel not in gen_all:
            continue
        if p.rel in expected_zones:
            ok = _zone_inner(p.text) == expected_zones[p.rel]
        else:
            ok = single_doc_reproduced(p.rel, root)
        if ok:
            b_ok.add(p.rel)
        else:
            b_drift.append(p.rel)

    # --- G-T1：既无 (a) 形模板头、又非 (b) 形可复现生成页。S2 加严：driven() 从此**不认**
    #     套错模板的页（错配页不销籍，与 mismatch 账各记各的——同一页两处红是设计意图）。
    def driven(p: dts.PageInfo) -> bool:
        return (
            p.fm is not None
            and p.fm.template in schemas
            and category_mismatch(p, schemas) is None
        )

    def driven_b(p: dts.PageInfo) -> bool:
        return p.rel in b_ok

    t1: list[str] = []
    # 席 TX130（R0）：同一次遍历里顺手分账——**不排除任何页**（t1 本体逐字照旧 append），
    # 只是把每条 t1 记录同时归入「对外欠账」或「过程件登记」之一（判定握有 PageInfo，
    # 事后按 rel 重新 classify 会走出第二套判据，故在此判）。
    t1_process_rels: set[str] = set()
    for p in pages:
        if driven(p) or driven_b(p):
            continue
        if p.rel in gen_all:
            entry = f"{p.rel}#生成物未当场复现字节等值"  # 在册不复现⇒带因记账，不再路径豁免
        else:
            entry = p.rel
        t1.append(entry)
        if is_process_artifact_page(p):
            t1_process_rels.add(p.rel)
    t1_by_cat = dict(Counter(dts.classify(r.split("#", 1)[0]) for r in t1))
    t1_accounting = split_t1_by_accounting(t1, t1_process_rels)
    _debt_entries, _reg_entries = t1_accounting["debt_entries"], t1_accounting["registered_entries"]
    assert isinstance(_debt_entries, list) and isinstance(_reg_entries, list)
    # 两栏清单**只从那一支分账函数取**（此处不再复制过滤式——复制＝第二处判据落点，
    # 改一处另一处仍按旧集合算，数会分叉）。
    t1_debt_official = [str(e) for e in _debt_entries]
    t1_registered_process = [str(e) for e in _reg_entries]
    t1_stamp = pages_bytes_fingerprint(pages)
    # 席 S175：甲账「波内拆分」只读腿（不排除任何页，只加一栏数）。
    # 基线集合只从不可变 commit 现取；取不到 ⇒ base=None ⇒ 保守全落「本波新建」并点名。
    base_paths, base_err = git_wave_base_paths(WAVE_BASE_COMMIT, root)
    t1_wave_split = split_t1_by_wave(t1, base_paths or None, base_err)
    mismatch = [m for m in (category_mismatch(p, schemas) for p in pages) if m]

    # --- G-T2：同类小节集合与顺序
    t2: list[str] = []
    t2_pages = 0
    # 席 S230R（2026-09-25，R0=A 的**反缩水腿**）：比对面里过程稿占几页。
    # 为什么单列这一枚：`两栏之和 == 总账` 那支恒等式对「把过程稿*从扫描面剔除*」是**盲的**
    # ——剔除会让总账跟着一起掉、等式照样成立（本席现算实证，见 SEAT-S230.md §2 枚乙）。
    # 「总账栏不许消失」要能被机检，就必须有一枚**只数过程稿**的活性面：它掉了就是扫描面缩了。
    t2_pages_process = 0
    # 席 S230（R0=A）：与 G-T1 同口径分账——不排除任何页、扫描面一寸不缩，只把每条偏离同时
    # 归入「对外欠账」或「过程稿登记」之一（判定握有 PageInfo，故在此判）。
    t2_process_rels: set[str] = set()
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
            if is_process_artifact_page(p):
                t2_pages_process += 1
            found = [f"{p.rel}: {v}" for v in section_findings(heads, canon)]
        elif p.fm is not None and p.fm.template in schemas:
            t2_pages += 1
            if is_process_artifact_page(p):
                t2_pages_process += 1
            found = [
                f"{p.rel}: {v}" for v in dts.check_sections(schemas[p.fm.template], p.text)
            ]
        else:
            continue
        if found:  # 记账单位＝「件」（页），一页多码只算一枚偏离页
            t2.append(f"{p.rel}: " + " | ".join(found))
            if is_process_artifact_page(p):
                t2_process_rels.add(p.rel)
    t2_accounting = split_debt_by_accounting(
        t2,
        t2_process_rels,
        ruler="R0=A（席 S230：欠账只算对外正式面，过程稿只登记；扫描面一寸不缩）",
    )
    _t2_debt, _t2_reg = t2_accounting["debt_entries"], t2_accounting["registered_entries"]
    assert isinstance(_t2_debt, list) and isinstance(_t2_reg, list)
    t2_debt_official = [str(e) for e in _t2_debt]
    t2_registered_process = [str(e) for e in _t2_reg]

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
        # 席 S131（S114 交回③＋S121 精确定位）：把 S106 的有条件摘除**真传进来**——
        # 不接则 G-T3 面A 的加严只活在测试里。在册取数走唯一口＋fail-closed（见上函数）。
        hits = [
            f"{p.rel}: {v}"
            for v in dfd.fact_findings(
                lines, vocab=vocab, known_fact_keys=page_known_fact_keys(p, schemas)
            )
        ]
        if not hits:
            continue
        t3_pages += 1
        # 席 S78（P-39）：分流走单一函数、按类别判（不再认 `.superpowers/` 路径前缀），驱动与否同权。
        # 席 S201（裁定 3.A）：这一支现在**只**读路径派生类别＋登记名录——`driven(p)` 在这里
        # 彻底不再被咨询（旧写法拿它当分流输入＝页戴什么头就换哪把尺子）。头的去向改由
        # `header_exemption_findings` 单独成账（下面 G-T3 锁段）。
        face = face_of_history_page(p)
        if face == "line":
            t3_managed += hits  # 面 A（按行·治理面）
        elif face == "page":
            t3_unmoved.append(p.rel)  # 面 B（按页·未迁移，含历史台账页）
        # face == "skip"：过程日志两面都不记，债只在 G-T1（旧前缀豁免的类别化落地）
    # K-1（席 S20，加严）：机器段可被一对注释买断 ⇒ 单列一遍，专抓「人写正文为空、
    # 裸事实全藏在 AUTO 段里」的洗白页（上面的主循环 `if not lines: continue` 会漏它）。
    # 席 S46：板块段的可信判据从「在册名单」升级为认机制 (b) 的复现证据 b_ok。
    for p in pages:
        # 席 S131：K-1 这半腿同接（S106 注释未点名的第三处调用点——S121 现算定位）。
        # 与主循环同源同一 known 集：AUTO 段与人写区同页同模板身份，S114 在
        # `naked_fact_findings` 里也是整页共用一枚 known_fact_keys。
        known_keys = page_known_fact_keys(p, schemas)
        for begin, inner in dfd.auto_zone_contents(p.text):
            hidden = dfd.fact_findings(
                dfd.human_lines(inner), vocab=vocab, known_fact_keys=known_keys
            )
            if not hidden:
                continue  # 段内无裸事实＝不构成交白（放过引用示例的文档），不新增账
            if _auto_zone_verified(p, begin, inner, schemas, expected_zones):
                continue  # 真由写盘口生成且当场逐段复现（段数+内容一起比），放行
            for v in hidden:
                t3_managed.append(f"{p.rel}: UNVERIFIED_AUTO_ZONE {v}")
    t3 = t3_managed + t3_unmoved
    # 席 S201（裁定 3.A）：**分桶结构体检**与 G-T3 两面同一支现算、并排报数——它们不是第三本债，
    # 而是「桶表有没有又被 front-matter 拨动、有没有类别漏登记」的机器自查。零红是设计要求。
    t3_self_exemption = header_exemption_findings(pages)
    t3_header_coupling = header_coupling_findings(pages, face_of_history_page)
    t3_bucket_gaps = bucket_table_gaps(
        pages, extra_categories=categories_outside_content_universe(root)
    )
    t3_boards_prefix_drift = [
        p.rel for p in pages if not boards_prefix_agrees_with_table(p)
    ]

    # --- G-T4：schema ↔ 实参双向对齐
    #     席 S230（R0=A）：与 G-T1/G-T2 同口径分账。`schema_errors` 与 `template_side_t4` 的条目
    #     开头是模板 id（`DEAD_PARAM <tid>:` / `SCHEMA_ERROR ...`），不是任何页 rel ⇒ 落非过程稿
    #     ＝进欠账（保守方向：模板体自身的债绝不借分账放走）；页级条目按 `entry_subject` 归 rel。
    t4 = list(schema_errors) + template_side_t4(schemas)
    t4_process_rels: set[str] = set()
    # 席 S230：模板体检（`doc_template_pipeline` 的 `bad`）走同一支页集合与同一判据，
    # 三面共用 `r0_process_rels`，禁在门里再写一遍「什么算过程稿」。
    tcheck: list[str] = [f"{p.rel}: {v}" for p in pages for v in p.violations]
    for p in pages:
        page_t4 = [
            f"{p.rel}: {v}" for v in p.violations if v.split(" ", 1)[0] in T4_CODES
        ]
        t4 += page_t4
        if (page_t4 or p.violations) and is_process_artifact_page(p):
            t4_process_rels.add(p.rel)
    t4_accounting = split_debt_by_accounting(
        t4,
        t4_process_rels,
        ruler="R0=A（席 S230：欠账只算对外正式面，过程稿只登记；扫描面一寸不缩）",
    )
    t4_debt_official = [str(e) for e in t4_accounting["debt_entries"]]
    t4_registered_process = [str(e) for e in t4_accounting["registered_entries"]]
    tcheck_accounting = split_debt_by_accounting(
        tcheck,
        t4_process_rels,
        ruler="R0=A（席 S230：模板体检同口径分账；扫描面一寸不缩、过程稿照出总账栏）",
    )
    tcheck_debt_official = [str(e) for e in tcheck_accounting["debt_entries"]]
    tcheck_registered_process = [str(e) for e in tcheck_accounting["registered_entries"]]
    # 席 S230（R0=A）：**欠账分母定义域的结构体检**（照 3.A 那两把锁的形状）——
    #   · 头不许把对外页降级成过程稿（自我豁免即红）；
    #   · 每一枚在册类别必须在分母表有显式一行（缺行≠免检）、register 集必须恰等 S78 真身。
    # 零红是设计要求，不是新目标（与 G-T3 四值恒零同一哲学）。
    r0_self_exemption = r0_self_exemption_findings(pages)
    r0_denominator_gaps_now = r0_denominator_gaps(
        pages, extra_categories=categories_outside_content_universe(root)
    )

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
        # 席 S20 K-3（2026-09-22，加严）：旧写法把 code_home 存在性检查挂在 `elif`，
        # 「缺模板」的类（本波 15 类）永远走第一个分支、code_home 死路径永不核查。
        # 拆成两个独立 `if`：模板缺失与 code_home 悬空各记各的，一个类可两头都红。
        if c.template is None or not (dts.TEMPLATE_DIR / f"{c.template}.md").is_file():
            t5_missing_tpl.append(f"{c.cid}: 无对应模板（template={c.template!r}）")
        if c.surface == "code" and c.code_home and not (ROOT / c.code_home).exists():
            t5_missing_tpl.append(f"{c.cid}: code_home 不存在 {c.code_home}")
    no_pages = sorted(
        c.cid
        for c in dt.CONTENT_CATEGORIES
        if c.surface == "md" and not c.generated_by and c.cid not in labels
    )
    unknown_labels = sorted(labels - declared)
    # 席 S119：反向孤儿腿（模板在册、驱动 0 页），与上面 `orphan_tpls`（无类别引用）各记各的。
    tpl_orphans = orphan_templates(pages, schemas, template_stems)
    # --- S2 三角闭合（第三边）：页 → 类别 → 模板 链条断掉的页，按类别记红。
    #     「在册模板装载失败（有文件无 schema）」也算接不到——比只查文件存在更严。
    #     席 S164（第二十六批，方向只准加严）：补上另一半边——「类别在册但该桶压根没有模板」
    #     （`want is None` 且该桶归本腿管辖）同样记红（旧条件 `want is not None` 把它短路了，
    #     见 `should_have_template` 注）。豁免面**不增**：生成器所有／代码面仍被
    #     `should_have_template` 挡在门外，`p.rel in gen_all` 那道生成页闸也原样保留，
    #     故本改动只可能让 `pages_unreachable` 变多、不可能变少（不存在"借加严之名放水"）。
    dead_pages: Counter[str] = Counter()
    for p in pages:
        if p.rel in gen_all:
            continue
        want = registered_template(p.category)
        if should_have_template(p.category) and (want is None or want not in schemas):
            dead_pages[p.category] += 1
    pages_unreachable = [
        f"{cat}: {n} 页落到接不到在册模板的类别（模板未建或装载失败）"
        for cat, n in sorted(dead_pages.items())
    ]

    return {
        "root": root,
        "generated_map": gen_map,
        "generated_all": gen_all,
        "b_ok": b_ok,
        "b_drift": b_drift,
        "pages": pages,
        "page_total": len(pages),
        "labels": labels,
        "schemas": schemas,
        "t1": t1,
        "t1_by_cat": t1_by_cat,
        "t1_debt_official": t1_debt_official,
        "t1_registered_process": t1_registered_process,
        "t1_accounting": t1_accounting,
        "t1_stamp": t1_stamp,
        "t1_wave_split": t1_wave_split,
        "mismatch": mismatch,
        "t2": t2,
        "t2_debt_official": t2_debt_official,
        "t2_registered_process": t2_registered_process,
        "t2_accounting": t2_accounting,
        "t2_pages": t2_pages,
        "t2_pages_process": t2_pages_process,
        # 席 S230R：全扫描面的过程稿人口（反缩水腿的另一半——剔除整桶会当场把它打到 0）。
        # 判定唯一走 `r0_process_rels`（页→过程稿的唯一投影口），本函数不另写一遍类别判据。
        "r0_process_page_total": len(r0_process_rels(pages)),
        "t3": t3,
        "t3_managed": t3_managed,
        "t3_unmoved": t3_unmoved,
        "t3_pages": t3_pages,
        "t3_self_exemption": t3_self_exemption,
        "t3_header_coupling": t3_header_coupling,
        "t3_bucket_gaps": t3_bucket_gaps,
        "t3_boards_prefix_drift": t3_boards_prefix_drift,
        "t4": t4,
        "t4_debt_official": t4_debt_official,
        "t4_registered_process": t4_registered_process,
        "t4_accounting": t4_accounting,
        "tcheck": tcheck,
        "tcheck_debt_official": tcheck_debt_official,
        "tcheck_registered_process": tcheck_registered_process,
        "tcheck_accounting": tcheck_accounting,
        "r0_self_exemption": r0_self_exemption,
        "r0_denominator_gaps": r0_denominator_gaps_now,
        "body_completeness": board_body_completeness(pages, b_ok=b_ok),
        "t5": {
            "cid_set_matches_census": census_names == declared,
            "census_only": sorted(census_names - declared),
            "registry_only": sorted(declared - census_names),
            "census_count": len(census_names),
            "missing_template": t5_missing_tpl,
            "orphan_templates": orphan_tpls,
            "templates_without_pages": tpl_orphans,
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


def _r0_split_line(label: str, acc: object, *, old_note: str) -> str:
    """G-T2 / G-T4 / 模板体检三面共用的 R0 分账报数行（与 G-T1 那行同款式，只换文案主体）。

    总账栏不消失：`旧尺总量` 恒等于两栏之和（`partition_ok` 现算自证），过程稿那一栏照点名。
    """
    assert isinstance(acc, dict), f"{label} 缺分账面＝取数口改版"
    return (
        f"{label} 口径分账（席 S230，裁定件 R0=A；{old_note}，两栏之和恒等于总账）＝ "
        f"旧尺总量 {acc['total_old_ruler']} ｜ 新尺对外欠账 {acc['debt_official']} ｜ "
        f"新尺过程稿登记 {acc['registered_process']}"
        f"（恒等式{'成立' if acc['partition_ok'] else '破坏'}；重叠主体 "
        f"{len(acc['overlap_rels'])} 枚；"
        + f"欠账按类别 {acc['debt_by_cat']}；登记按类别 {acc['registered_by_cat']}）"
    )


def report_lines(res: dict[str, object]) -> list[str]:
    """`--report` 与门判据**同一支现算值**（常驻用例逐条比对，防 report 自成一套账）。"""
    t5 = res["t5"]
    gen = res["generated_map"]
    bc = res["body_completeness"]
    sw = res["t1_wave_split"]
    assert isinstance(t5, dict) and isinstance(gen, dict) and isinstance(bc, dict)
    assert isinstance(sw, dict)
    tiers = bc["tiers"]
    assert isinstance(tiers, dict)
    orph = t5["templates_without_pages"]
    assert isinstance(orph, dict)
    acc = res["t1_accounting"]
    stamp = res["t1_stamp"]
    assert isinstance(acc, dict) and isinstance(stamp, dict)
    return [
        f"管辖内容页 {res['page_total']}",
        "生成物取数口 " + " / ".join(f"{k}={len(v)}" for k, v in sorted(gen.items())),
        f"G-T1 无模板头且非生成物 = {len(res['t1'])}  按类别 {res['t1_by_cat']}",
        (
            "G-T1 口径分账（席 TX130，裁定件 R0；扫描面一寸未缩、t1 总量一枚不删，"
            "两栏之和恒等于 t1）＝ "
            f"旧尺总量 {acc['total_old_ruler']} ｜ 新尺对外欠账 {acc['debt_official']} ｜ "
            f"新尺过程件登记 {acc['registered_process']}"
            f"（恒等式{'成立' if acc['partition_ok'] else '破坏'}；重叠 rel {len(acc['overlap_rels'])} 枚；"
            + f"对外面类别由注册表派生 {acc['official_categories']}；"
            + f"欠账按类别 {acc['debt_by_cat']}；登记按类别 {acc['registered_by_cat']}）"
        ),
        (
            f"G-T1 分账同刻指纹（TX130；自证「只换口径、未动任何页字节」）＝ 取数时刻 "
            f"{stamp['taken_at_utc']} ／ 管辖页 {stamp['page_count']} 页 ／ "
            f"页字节总指纹 sha256={stamp['pages_bytes_digest']} ／ 读盘异常页 {stamp['unreadable_pages']}"
        ),
        (
            f"G-T1机制(b) 写盘口当场重渲染字节等值放行 = {len(res['b_ok'])} 页 / "
            f"在册未复现已记债 = {len(res['b_drift'])} 页"
        ),
        f"G-T1面B 类别↔模板错配页（TEMPLATE_CATEGORY_MISMATCH）= {len(res['mismatch'])}",
        f"G-T2 小节偏离页 = {len(res['t2'])}（比对页 {res['t2_pages']}）",
        _r0_split_line("G-T2", res["t2_accounting"], old_note="扫描面一寸未缩、t2 总量一枚不删"),
        (
            "R0=A 反缩水腿（席 S230R；恒等式对『把过程稿从扫描面剔除』是盲的——剔除会让总账"
            "跟着一起掉、等式照样成立，故单列只数过程稿的活性面）＝ "
            f"全扫描过程稿人口 {res['r0_process_page_total']} ／ "
            f"G-T2 比对面 {res['t2_pages']}（其中过程稿 {res['t2_pages_process']}）"
        ),
        (
            f"G-T3 面 A 管辖 {len(res['t3_managed'])} 行 / "
            f"面 B 未迁移 {len(res['t3_unmoved'])} 页（有正文页 {res['t3_pages']}）"
        ),
        (
            "G-T3 分桶结构体检（席 S201，裁定 3.A：面别只由路径/登记派生，模板头不参与分类）＝ "
            f"自我豁免 {len(res['t3_self_exemption'])} / 头-面耦合 {len(res['t3_header_coupling'])} / "
            f"桶表缺行或幽灵行 {len(res['t3_bucket_gaps'])} / 板块前缀与桶表漂移 "
            f"{len(res['t3_boards_prefix_drift'])}"
            f"（桶表真身 FACE_BY_CATEGORY 覆盖 {len(FACE_BY_CATEGORY)} 枚类别；"
            f"逐行清零名录 {len(GOVERNED_LINE_PATHS)} 枚；四值恒零＝设计红线，非新目标）"
        ),
        f"G-T4 参数不对齐 = {len(res['t4'])}",
        _r0_split_line("G-T4", res["t4_accounting"], old_note="扫描面一寸未缩、t4 总量一枚不删"),
        f"模板体检（页级 front-matter 违规总数）= {len(res['tcheck'])}",
        _r0_split_line(
            "模板体检", res["tcheck_accounting"], old_note="扫描面一寸未缩、bad 总量一枚不删"
        ),
        (
            "R0 欠账分母定义域体检（席 S230，裁定 R0=A：分桶/是否过程稿只由路径派生，"
            "模板头不参与）＝ "
            f"头把对外页降级为过程稿（自我豁免）{len(res['r0_self_exemption'])} / "
            f"分母表缺行或幽灵行或桶值/集合分叉 {len(res['r0_denominator_gaps'])}"
            f"（分母表真身 R0_DEBT_BUCKET_BY_CATEGORY 覆盖 {len(R0_DEBT_BUCKET_BY_CATEGORY)} 枚类别；"
            "两值恒零＝设计红线，非新目标）"
        ),
        (
            "板块正文完整度账 G-B1 四档 = "
            + " / ".join(f"{t}={tiers[t]}" for t in BODY_TIER_ORDER)
            + f"（板块管辖页 {bc['page_total']}／含「{TODO_MARK}」{bc['pages_with_todo']} 页／"
            + f"有板块骨架可比 {bc['slot_total_rows']} 页／人写区最小 {bc['min_human_chars']} 字符；"
            + "本腿今日只登记不设上限，转正首届核账值由该门 owner 在收口窗取）"
        ),
        (
            f"G-T5 无模板类别 = {len(t5['missing_template'])} / "
            f"孤儿模板 {len(t5['orphan_templates'])} / "
            f"类别名相等 {t5['cid_set_matches_census']}（CENSUS {t5['census_count']} 名） / "
            f"未归类标签 {t5['unknown_labels']} / 声明无页 {t5['declared_no_page']} / "
            f"三角闭合断链 {len(t5['pages_unreachable'])} 类（页压在无模板类别下）"
        ),
        (
            f"G-T5孤儿模板腿 在册却驱动 0 页 = {sum(len(v) for v in orph.values())} 枚 / "
            + " / ".join(f"{k}={len(orph[k])}" for k in ORPHAN_CLASS_ORDER)
            + "（真债＝md 桶有页无人驱动；code_surface＝结构性 0 属席 S116 面，"
            "只分开标注不排除；本腿今日只登记不设上限）"
        ),
        (
            "G-T1 波内拆分（席 S175；只加一栏、不排除任何页；今日只登记不设上限）＝ "
            f"波前存量 {sw['stock_count']} + 本波新建 {sw['new_count']} = {sw['total']} "
            f"（恒等式{'成立' if sw['identity_ok'] else '破坏'}；两栖页 {len(sw['amphibious'])}；"
            f"基线 {sw['base_commit']} "
            + (
                f"取数降级⇒全部保守暂记「本波新建」：{sw['base_err']}（待主会话核）"
                if sw["degraded"]
                else f"在册树 {sw['base_size']} 路径"
            )
            + "；转正基线由该门 owner 定，S175 不自定）"
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

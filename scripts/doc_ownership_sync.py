"""文档归属投影器（席 T-JOIN 立，2026-09-22 规格统一波）。

职责单一：把人读的板块归属分类表
`docs/boards/_meta/doc-classification-20260921.md` **机械投影**成机器可读声明源
`plugins/bot_unified_runtime/domains/core/board_doc_ownership.py`，并算出「未归属文档」这本账。

铁律（写进代码，不许绕过）：
- **只投影、不发明**：主板块为 `NONE`/空/歧义的行一律留未归属；不猜路径。
- **基目录补全只许走 `_SECTION_BASES` 这张表**（节标题 → 基目录），逐条在 basis 里留「机械补全」证据。
- 路径必须 `Path.exists()` 可解析；表内路径已不存在的单路径历史行收进
  `DOC_OWNERSHIP_ARCHIVE`（附处置列摘要），不丢信息。
- 取数口只有一份：`compute_ownership()` 同时服务 violations、总数与 `--report`。
- 写盘确定性：条目排序、`newline="\\n"`、正文零时间戳——连跑两次字节相等（常驻用例锁）。
- **断链自诊（席 S76）**：`--check` 不只报 "OUT OF SYNC"，而是**逐格**比对「分类表现算 vs 盘上声明源」，
  把三态方向分开点名——盘上缺条目 / 盘上多条目 / 同一路径字段漂移（basis 等），每态各给可执行下一步。
  rc 语义一字未改（一致 0／不一致 1），只加诊断，**不加豁免、不缩扫描面**。

用法：
  python scripts/doc_ownership_sync.py --generate   # 重投影并写声明源（写完回读校验字节一致）
  python scripts/doc_ownership_sync.py --check      # 逐格比对投影与盘上声明源，点名到格并给下一步
  python scripts/doc_ownership_sync.py --report     # 打印现算账（未归属数=棘轮取数的同源值）
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLASSIFICATION_REL = "docs/boards/_meta/doc-classification-20260921.md"
OWNERSHIP_REL = "plugins/bot_unified_runtime/domains/core/board_doc_ownership.py"

#: 扫描面（未归属账的管辖域）。这是**内容文档面**，不含 tests/scripts 代码件。
SCAN_SPECS: tuple[tuple[str, str], ...] = (
    (".", "*.md"),            # 根目录一层
    ("docs", "**/*.md"),
    (".superpowers", "**/*.md"),
    ("personas", "**/*.md"),
)

#: 节标题 → 基目录（有序，首个命中生效；`## 5` 起整段不解析——§5 三张表是冲突/缺口/归档台账，
#: 其首列不是路径，混进来就是拿错尺子）。规则②「…/」行内续接 = 用所在节基目录补全。
_SECTION_BASES: tuple[tuple[str, str], ...] = (
    ("根目录 .md", ""),
    ("docs/*.md", "docs"),
    ("docs/design/unify-audit-20260919", "docs/design/unify-audit-20260919"),
    ("docs/superpowers", "docs/superpowers"),
    ("docs/design", "docs/design"),
    (".superpowers/sdd", ".superpowers/sdd"),
)

_BOARD_RE = re.compile(r"^(B\d{2})$")
_AMBIGUOUS_BOARD_RE = re.compile(r"^(B\d{2})\s*/\s*(B\d{2})$")

#: 代码侧目录级归属（枚举字面目录，**非通配**；每条须 `is_dir()` 才采信——宁缺不猜）。
#: 用途 = 分类表 §4 成文（09-21）之后**新增的并发施工波过程件目录**与**文档体系工程件**
#: `docs/templates/`。它们与 §4 已列的 14 个 `.superpowers/sdd/<波次>/` 目录行同型
#: （工程/波次过程件归 B10），这里只是把 §4 落笔时还不存在的波次补进投影，机制与 §4 完全一致
#: （最长前缀认领，见 `compute_ownership` 的 `dir_entries`），**不发明新语义、不加通配**。
#: 终局应由分类表 owner 把这四行并入 §4；此表是「一处变更处处跟随」的过渡登记，
#: 只登记目录级过程/工程件，不触碰任何内容件的板块判定。
_CODE_DIR_OWNERSHIP: tuple[tuple[str, str, str, str], ...] = (
    (".superpowers/sdd/2026-09-21-boards/", "B10", "过程件",
     "十板块文档体系波席报目录（同 §4 兄弟波次行：过程件→B10）"),
    (".superpowers/sdd/2026-09-21-unify-wave/", "B10", "过程件",
     "中央调度层统一波席报/裁定/台账目录（同 §4 兄弟波次行：过程件→B10）"),
    (".superpowers/sdd/2026-09-22-taxonomy/", "B10", "过程件",
     "本轮规格统一波席报/基线/普查目录（同 §4 兄弟波次行：过程件→B10）"),
    ("docs/templates/", "B10", "工程件",
     "文档模板体系工程件（唯一模板源，随 scripts/doc_templates.py 常驻；治理面归 B10）"),
)
_FID_RE = re.compile(r"\bB\d{2}\.[a-z][a-z0-9-]*")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_NOTE_CN_RE = re.compile(r"（[^（）]*）")
_NOTE_ASCII_RE = re.compile(r"\([^()]*\)")
_DIGIT_SERIES_RE = re.compile(r"^(?P<pre>.*-)(?P<nums>\d+(?:/\d+)+)(?P<ext>\.md)?$")
_SEP_CELL_RE = re.compile(r"^:?-{3,}:?$")
_BOARD_DIR_RE = re.compile(r"^docs/boards/(B\d{2})-[^/]+(?:/|$)")


@dataclass(frozen=True)
class Entry:
    """声明源一条 = (相对路径, 主板块 BNN, 二级 fid 或空, 现役性, 依据)。"""

    path: str          # 目录级条目以 "/" 结尾
    board: str         # "B01".."B10"；"" = 表内 NONE/空 → 在册未归属
    fid: str
    currency: str
    basis: str
    completed: bool = False   # True = 路径经过机械补全（基目录/通配模板/数字系列/…续接）
    merged: bool = False      # True = 来自合并区间行；同路径冲突时单列行具体性更高、获胜


@dataclass(frozen=True)
class Ledger:
    entries: tuple[Entry, ...]
    archive: tuple[Entry, ...]
    unowned: tuple[str, ...]
    scanned: int
    board_path_direct: int
    dir_attributed: int
    completed_paths: int
    unresolved_tokens: tuple[str, ...] = field(default_factory=tuple)
    ambiguous_rows: tuple[str, ...] = field(default_factory=tuple)
    skipped_rows: tuple[str, ...] = field(default_factory=tuple)


def _split_row(line: str) -> list[str] | None:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|") and len(s) > 2):
        return None
    return [c.strip() for c in s[1:-1].split("|")]


def _base_for(heading: str) -> str | None:
    for needle, base in _SECTION_BASES:
        if needle in heading:
            return base
    return None


def _clean_token(tok: str) -> str:
    tok = tok.strip().strip("+").strip()
    tok = re.sub(r"[、，。]+$", "", tok)
    return tok


def _strip_overlap(head: str, item: str) -> str:
    """通配模板展开辅助：表内项名常重复 `*` 左半的尾部字面（`reorg-w*` × `w10`）。

    机械规则：找 head 尾与 item 头的最长重叠 k，返回 item[k:]；无重叠则原样返回。
    """
    for k in range(min(len(head), len(item)), 0, -1):
        if head.endswith(item[:k]):
            return item[k:]
    return item


def _row_tokens(cell: str) -> tuple[list[str], list[str]]:
    """抽取一条合并行的候选 token。返回 (backtick 段, plain 段)。

    机械规则（全部写死在此，无逐条手工）：剥反引号取段；plain 部分先剥
    全角/半角括注，再取最后一个冒号之后（`… 席位日志 34 件: A / B` 形），按 " / " 拆项。
    """
    backs = [t.strip() for t in _BACKTICK_RE.findall(cell) if t.strip()]
    plain = _BACKTICK_RE.sub(" ", cell)
    plain = _NOTE_CN_RE.sub(" ", plain)
    plain = _NOTE_ASCII_RE.sub(" ", plain)
    for sep in ("：", ":"):
        if sep in plain:
            plain = plain.rsplit(sep, 1)[-1]
    plains = [t for t in (_clean_token(x) for x in plain.split("/")) if t]
    return backs, plains


def _candidates(cell: str, base: str | None) -> list[tuple[str, bool]]:
    """给定首列 + 节基目录，产出有序候选路径 (path, completed)。

    规则优先级：①原样全路径 > ②通配模板展开 > ③数字系列展开 > ④`…/` 续接 > ⑤基目录补全。
    全部要求最终 exists()，由调用方过滤——**不存在的候选一律不采信**，宁缺不猜。
    """
    backs, plains = _row_tokens(cell)
    tokens = backs + plains
    out: list[tuple[str, bool]] = []

    def add(path: str, completed: bool) -> None:
        out.append((path.replace("\\", "/"), completed))

    templates = [t for t in tokens if "*" in t]
    items = [t for t in tokens if "*" not in t and " " not in t and "：" not in t and ":" not in t]
    whole = cell.replace("`", "").strip()
    if "*" not in whole and " " not in whole and "：" not in whole and ":" not in whole:
        add(whole, False)
    for item in items:
        m = _DIGIT_SERIES_RE.match(item)
        if m:  # 规则③：`entries-1/2/3.md` → 三枚
            for num in m["nums"].split("/"):
                body = f"{m['pre']}{num}{m['ext'] or '.md'}"
                add(body, True)
                if base:
                    add(f"{base}/{body}", True)
        if "*" in item:
            continue
        for tpl in templates:  # 规则②：glob 前缀/中缀模板 × 逐项
            head = tpl.split("*", 1)[0]
            subst_candidates = {item, _strip_overlap(head, item)}  # 表内项名常重复通配符左半的字面（w*-log × w10）
            for ext in ("", ".md"):
                for subst in subst_candidates:
                    built = tpl.replace("*", subst) + ext
                    add(built, True)
                    if base and not built.startswith(base + "/"):
                        add(f"{base}/{built}", True)
        add(item, False)  # 规则①：token 已是全相对路径时直接采信（exists 把关）
        add(item + ".md", False)
        if base:  # 规则⑤：裸文件名 → 节基目录补全（基目录只来自 _SECTION_BASES 表）
            bare = item if item.endswith(".md") else item + ".md"
            add(bare, True)
            add(f"{base}/{bare}", True)
        if item.startswith("…/") and base:  # 规则④：`.superpowers` 表内「…/」续接
            tail = item[2:]
            add(f"{base}/{tail}", True)
            add(f"{base}/{tail}/", True)
    seen: set[str] = set()
    dedup: list[tuple[str, bool]] = []
    for path, completed in out:
        if path in seen:
            continue
        seen.add(path)
        dedup.append((path, completed))
    return dedup


def _resolve(repo: Path, cell: str, base: str | None) -> tuple[list[tuple[str, bool]], list[str]]:
    """返回 (存活的 (路径, 补全标记) 列表, 未能解析的 token 列表)。"""
    survivors: list[tuple[str, bool]] = []
    unresolved: list[str] = []
    backs, plains = _row_tokens(cell)
    considered = backs + plains
    for path, completed in _candidates(cell, base):
        p = path.rstrip("/")
        if not p or "*" in p or " " in p:
            continue
        fp = repo / Path(*p.split("/"))
        ok = fp.is_dir() if path.endswith("/") else fp.is_file()
        if ok:
            survivors.append((path, completed))
    survived: list[str] = [t for t, _ in survivors]
    for tok in considered:
        probe = tok.rstrip("/").removeprefix("…/")
        hit = any(
            t == tok or t == tok + ".md" or t.endswith(("/" + tok, "/" + tok + ".md"))
            or (len(probe) > 3 and probe in t)
            or tok.rstrip("/") in t
            for t in survived
        )
        if not hit and tok and "*" not in tok and " " not in tok and len(tok) < 120:
            unresolved.append(tok)
    return survivors, unresolved


def load_entries(repo: Path) -> tuple[list[Entry], list[Entry], list[str], list[str], list[str]]:
    """解析分类表 §1–§4 的八列表行 → (在册条目, 归档条目, 歧义行, 未解析token, 跳行)。"""
    lines = (repo / CLASSIFICATION_REL).read_text(encoding="utf-8").splitlines()
    heading = ""
    base: str | None = None
    entries: list[Entry] = []
    archive: list[Entry] = []
    ambiguous: list[str] = []
    unresolved: list[str] = []
    skipped: list[str] = []
    for raw in lines:
        if raw.startswith("#"):
            heading = raw.lstrip("# ").strip()
            if heading.startswith("5"):
                base = None
                heading = ""
                break
            base = _base_for(heading)
            continue
        if base is None:
            continue
        cells = _split_row(raw)
        if cells is None or len(cells) < 8:
            continue
        head_cell = cells[0]
        if all(_SEP_CELL_RE.match(c) for c in cells if c) or head_cell in {"路径", "目录", "#", "域", "被钉对象"}:
            continue
        if head_cell.startswith("覆盖文件"):
            continue
        if head_cell.startswith(("**小计", "**合计", "附注")):
            continue
        currency, board_cell, func, disposition, basis = cells[2], cells[3], cells[5], cells[6], cells[7]
        m = _BOARD_RE.match(board_cell)
        if m:
            board = m.group(1)
        elif board_cell in {"NONE", ""}:
            board = ""
        elif _AMBIGUOUS_BOARD_RE.match(board_cell):
            ambiguous.append(f"{head_cell} ⇒「{board_cell}」双板块歧义，不发明归属")
            continue
        else:
            ambiguous.append(f"{head_cell} ⇒ 主板块列非 BNN/NONE（「{board_cell[:24]}」）")
            continue
        fid_m = _FID_RE.search(func)
        fid = fid_m.group(0) if fid_m else ""
        survivors, tokens_un = _resolve(repo, head_cell, base)
        unresolved.extend(f"{base or '·'}/{t}" for t in tokens_un)
        if not survivors:
            clean = head_cell.replace("`", "").strip()
            tail = disposition[:40] if disposition else basis[:40]
            archive.append(Entry(clean.split(" ")[0], board, fid, currency, f"历史行路径不可解析（处置:{tail}）"))
            skipped.append(head_cell[:60])
            continue
        backs, plains = _row_tokens(head_cell)
        pathy_plains = [p for p in plains if " " not in p and "…" not in p and "：" not in p]
        merged = (len(backs) + len(pathy_plains) > 1) or any("*" in b for b in backs)
        for path, completed in survivors:
            note = basis if not completed else f"{basis}｜机械补全：基目录/展开规则→{base or path.split('/')[0]}"
            entries.append(Entry(path, board, fid, currency, note, completed, merged))
    dedup: dict[str, Entry] = {}
    # 同路径冲突时：单列行具体性 > 合并区间行（本表 §3.3 的 U17「单列」行就是为此存在）；再按板块名保序，确定性。
    for e in sorted(entries, key=lambda x: (x.path, x.merged, x.board)):
        dedup.setdefault(e.path, e)
    return list(dedup.values()), archive, ambiguous, unresolved, skipped


def _code_dir_entries(repo: Path) -> list[Entry]:
    """把 `_CODE_DIR_OWNERSHIP` 里当前**确实在盘**的目录转成目录级条目（path 以 / 结尾）。

    与分类表目录行同形（board/fid/currency/basis），且守住「不存在不采信」的既有纪律：
    目录不在盘就整条跳过。同路径若表已认领，则在 `compute_ownership` 去重时**表行获胜**。
    """
    out: list[Entry] = []
    for path, board, currency, basis in _CODE_DIR_OWNERSHIP:
        probe = repo / Path(*path.rstrip("/").split("/"))
        if probe.is_dir():
            out.append(Entry(path, board, "", currency, f"代码侧目录级过程/工程件：{basis}"))
    return out


def scan_surface(repo: Path = REPO) -> list[str]:
    files: set[str] = set()
    for root, pattern in SCAN_SPECS:
        for p in (repo / root).glob(pattern):
            if p.is_file():
                files.add(p.relative_to(repo).as_posix())
    return sorted(files)


def compute_ownership(repo: Path = REPO) -> Ledger:
    """**唯一取数口**：violations（未归属清单）、总数、--report 全部由它服务。"""
    entries, archive, ambiguous, unresolved, skipped = load_entries(repo)
    # 合并代码侧目录级过程/工程件：同路径若表已认领则表行获胜（去重），否则追加。
    _seen_paths = {e.path for e in entries}
    entries = entries + [e for e in _code_dir_entries(repo) if e.path not in _seen_paths]
    file_entries = {e.path.rstrip("/"): e for e in entries if not e.path.endswith("/")}
    dir_entries = sorted(((e.path, e) for e in entries if e.path.endswith("/")), key=lambda x: -len(x[0]))
    surface = scan_surface(repo)
    unowned: list[str] = []
    board_direct = 0
    attributed_by_dir = 0
    for rel in surface:
        e = file_entries.get(rel)
        if e is not None:
            if not e.board:
                unowned.append(rel)
            continue
        hit = None
        for dpath, de in dir_entries:
            if rel.startswith(dpath) and de.board:
                hit = (dpath, de)
                break
        if hit is not None:
            attributed_by_dir += 1
            continue
        m = _BOARD_DIR_RE.match(rel)
        if m:
            board_direct += 1
            continue
        unowned.append(rel)
    completed = sum(1 for e in entries if e.completed)
    return Ledger(
        entries=tuple(entries),
        archive=tuple(archive),
        unowned=tuple(unowned),
        scanned=len(surface),
        board_path_direct=board_direct,
        dir_attributed=attributed_by_dir,
        completed_paths=completed,
        ambiguous_rows=tuple(ambiguous),
        unresolved_tokens=tuple(sorted(set(unresolved))),
        skipped_rows=tuple(skipped),
    )


def render_source(ledger: Ledger) -> str:
    """确定性渲染声明源（排序 + LF + 零时间戳）。"""

    def fmt(entries: list[Entry]) -> str:
        out: list[str] = []
        for e in entries:
            out.append(
                f"    DocOwner(path={e.path!r}, board={e.board!r}, fid={e.fid!r},"
                f" currency={e.currency!r}, basis={e.basis!r}, completed={e.completed!r}),"
            )
        return "\n".join(out)

    files = [e for e in ledger.entries if not e.path.endswith("/")]
    dirs = [e for e in ledger.entries if e.path.endswith("/")]
    body = [
        '"""文档归属声明源（**机器生成**：`python scripts/doc_ownership_sync.py --generate`）。',
        "",
        "来源 = `docs/boards/_meta/doc-classification-20260921.md` 的机械投影（含基目录补全，",
        "规则表住 `scripts/doc_ownership_sync.py`）+ `.superpowers` 目录级认领 + 板块生成页路径直取。",
        "board==\"\" = 表内在册但**未归属**（NONE/空），不发明归属；路径已不存在的历史行在 DOC_OWNERSHIP_ARCHIVE。",
        "手改本文件必被 `--check`/常驻门打回——要改账就改分类表再重投影（一处变更处处跟随）。",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "",
        "",
        "@dataclass(frozen=True)",
        "class DocOwner:",
        '    """一条归属 = (相对路径, 主板块 BNN, 二级 fid 或空, 现役性, 依据)。目录级 path 以 / 结尾。"""',
        "",
        "    path: str",
        "    board: str",
        "    fid: str",
        "    currency: str",
        "    basis: str",
        "    completed: bool = False",
        "",
        "#: 目录级认领条目（.superpowers 波次目录等）——归属按最长前缀反查。",
        "DOC_OWNERSHIP_DIRS: tuple[DocOwner, ...] = (",
        fmt(dirs) or "    # （无）",
        ")",
        "",
        "#: 文件级条目（分类表逐行投影）。",
        "DOC_OWNERSHIP: tuple[DocOwner, ...] = (",
        fmt(files) or "    # （无）",
        ")",
        "",
        "#: 分类表引用过、但路径已不存在的历史件（被归档/删除/改名），信息不丢。",
        "DOC_OWNERSHIP_ARCHIVE: tuple[DocOwner, ...] = (",
        fmt(list(ledger.archive)) or "    # （无）",
        ")",
        "",
    ]
    return "\n".join(body)


def report_text(ledger: Ledger) -> str:
    grouped: dict[str, int] = {}
    for rel in ledger.unowned:
        key = rel.split("/")[0] if "/" not in rel else "/".join(rel.split("/")[:2]) + "/…"
        grouped[key] = grouped.get(key, 0) + 1
    lines = [
        f"扫描面(内容文档) = {ledger.scanned}",
        f"在册条目 = {len(ledger.entries)}（其中机械补全 {ledger.completed_paths}）",
        f"归档历史行 = {len(ledger.archive)}",
        f"目录级吃掉的文件 = {ledger.dir_attributed}；板块生成页路径直取 = {ledger.board_path_direct}",
        f"未归属（violations）= {len(ledger.unowned)}",
        "未归属大户（前缀分组）= " + "; ".join(f"{k} ×{v}" for k, v in sorted(grouped.items(), key=lambda kv: -kv[1])[:10]),
        f"歧义/待定用户裁 = {len(ledger.ambiguous_rows)}",
    ]
    for row in ledger.ambiguous_rows:
        lines.append(f"  待裁: {row}")
    lines.append(f"未解析 token（不采信、留未归属）= {len(ledger.unresolved_tokens)}")
    return "\n".join(lines)


#: 声明源三张表的字面量名 → 人话段名（诊断输出点名用）。
_SOURCE_SECTIONS: dict[str, str] = {
    "DOC_OWNERSHIP": "文件级条目",
    "DOC_OWNERSHIP_DIRS": "目录级条目",
    "DOC_OWNERSHIP_ARCHIVE": "归档历史行",
}

#: path 之外逐格比对的字段（与 `DocOwner` 形参同名；path 是全局主键，常驻门也按它查重）。
_DRIFT_FIELDS: tuple[str, ...] = ("board", "fid", "currency", "basis", "completed")

#: 每类漂移最多点名几格（在册 386 条，全打会淹掉结论；余量如实报数）。
_MAX_PRINT_PER_KIND = 12

K_MISSING = "盘上缺条目"
K_EXTRA = "盘上多条目"
K_FIELD = "字段漂移"
K_DUP = "盘上重复路径"
K_PARSE = "声明源不可解析"
K_FORMAT = "非条目级漂移"
K_ABSENT = "声明源不在盘"

#: 输出顺序＝诊断优先级（先看结构性崩坏，再看方向，最后才看排版）。
_KIND_ORDER: tuple[str, ...] = (K_ABSENT, K_PARSE, K_DUP, K_MISSING, K_EXTRA, K_FIELD, K_FORMAT)

#: 每态各一条「可执行下一步」——只写真做得动的动作，不写"看着办"。
#: 共同前提：上游只有分类表，下游生成物**不许手改**（`tests/test_doc_ownership_ledger.py` 同口径）。
_NEXT_STEP: dict[str, str] = {
    K_ABSENT: f"跑 `python scripts/doc_ownership_sync.py --generate` 重建 {OWNERSHIP_REL}",
    K_PARSE: "盘上声明源不是可解析的 `DocOwner(...)` 字面量（多半是手改改崩）："
             "回滚该文件后跑 `--generate`；若手改的是真意图，请把它写进分类表再 `--generate`",
    K_DUP: "同一 path 在盘上出现两次（投影器按 path 去重，重复只可能来自手改）："
           "回滚该文件后跑 `--generate`",
    K_MISSING: "上游分类表**有**这一行、盘上声明源**没有** ⇒ 改了表没跑重投影："
               "跑 `python scripts/doc_ownership_sync.py --generate`（本态不影响未归属数以外的账）",
    K_EXTRA: "盘上声明源**有**这一条、上游分类表现算**没有** ⇒ 要么手改了生成物（禁），"
             "要么分类表该行被删/改名/路径已不存在：补回分类表行，或回滚盘上手改，再跑 `--generate`",
    K_FIELD: "同一路径两边字段不一致（`basis` 漂移最常见＝清扫席改了依据列没随迁）："
             "以分类表为准跑 `--generate`；若你判**现算的期望值**本身错了，那是投影规则的问题，"
             "改本脚本规则表或分类表文字后 `--generate`，**别改盘上生成物**",
    K_FORMAT: "条目级三态全平、只有注释/顺序/空白不一致 ⇒ 直接 `--generate` 重投影即可",
}


@dataclass(frozen=True)
class Drift:
    """一格对不上的账：方向(kind) + 哪一格(path/field) + 期望(分类表现算) / 现值(盘上声明源)。"""

    kind: str
    path: str
    field: str
    expected: str
    actual: str

    def render(self) -> str:
        if self.kind == K_MISSING:
            return f"{self.path} ｜上游有：{_clip(self.expected, 100)}｜盘上无此条"
        if self.kind == K_EXTRA:
            return f"{self.path} ｜盘上有：{_clip(self.actual, 100)}｜上游现算无此条"
        if self.kind == K_DUP:
            return f"{self.path} ｜盘上出现 ≥2 次（上游按 path 去重）"
        if self.kind == K_FORMAT:
            return f"{self.path} ｜投影 {self.expected} vs 盘上 {self.actual}"
        return f"{self.path} .{self.field}：期望={_clip(self.expected, 80)} ｜盘上={_clip(self.actual, 80)}"


def _clip(text: str, limit: int = 120) -> str:
    """压成单行并截断——basis 列常有上百字，逐格点名要能一眼看完。"""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _desc(rec: dict[str, str]) -> str:
    return (f"{rec.get('section', '?')} board={rec.get('board', '')!r}"
            f" currency={rec.get('currency', '')!r} basis={rec.get('basis', '')!r}")


def projection_records(ledger: Ledger) -> dict[str, dict[str, str]]:
    """分类表现算 → {path: 字段字典}。三段共用一张表，与 `render_source` 的分段口径一致。"""
    out: dict[str, dict[str, str]] = {}
    groups: tuple[tuple[str, list[Entry]], ...] = (
        ("文件级条目", [e for e in ledger.entries if not e.path.endswith("/")]),
        ("目录级条目", [e for e in ledger.entries if e.path.endswith("/")]),
        ("归档历史行", list(ledger.archive)),
    )
    for section, items in groups:
        for e in items:
            out[e.path] = {
                "section": section,
                "board": e.board,
                "fid": e.fid,
                "currency": e.currency,
                "basis": e.basis,
                "completed": str(e.completed),
            }
    return out


def parse_declaration(text: str) -> tuple[dict[str, dict[str, str]], list[Drift]]:
    """**静态**解析盘上声明源（ast，绝不 import——import 会在源码树写出 `__pycache__`）。

    崩坏不抛异常：语法错／非法条目形／缺 path／重复 path 一律降成一条 `Drift` 交回，
    这样 `--check` 才能「点名 + 给下一步」而不是甩 traceback。
    """
    records: dict[str, dict[str, str]] = {}
    drifts: list[Drift] = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return records, [Drift(K_PARSE, OWNERSHIP_REL, "语法", "可解析的 python 字面量",
                               f"{type(exc).__name__}@line{exc.lineno}: {exc.msg}")]
    for node in tree.body:
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value  # 声明源写的是 `X: tuple[...] = (...)`＝AnnAssign
        else:
            continue
        tgt = targets[0]
        if not isinstance(tgt, ast.Name) or tgt.id not in _SOURCE_SECTIONS or value is None:
            continue
        section = _SOURCE_SECTIONS[tgt.id]
        if not isinstance(value, ast.Tuple):
            drifts.append(Drift(K_PARSE, tgt.id, "容器", "tuple[DocOwner, ...]", type(node.value).__name__))
            continue
        for elt in value.elts:  # 席 S88：原写 `node.value.elts`，mypy 看不见 AnnAssign 的窄化⇒2 错；
            # `value` 与 `node.value` 是同一对象（上面两条分支都从它赋值），行为逐字节不变，只把类型看直。
            if not (isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name) and elt.func.id == "DocOwner"):
                drifts.append(Drift(K_PARSE, section, "条目形", "DocOwner(...)", _clip(ast.dump(elt), 60)))
                continue
            fields: dict[str, str] = {"section": section}
            for kw in elt.keywords:
                if kw.arg is None:
                    drifts.append(Drift(K_PARSE, section, "**kwargs", "逐字段关键字", _clip(ast.unparse(kw.value), 40)))
                    continue
                try:
                    fields[kw.arg] = str(ast.literal_eval(kw.value))
                except (ValueError, TypeError):
                    fields[kw.arg] = f"<非字面量:{_clip(ast.unparse(kw.value), 40)}>"
            path = fields.get("path", "")
            if not path or path.startswith("<非字面量"):
                drifts.append(Drift(K_PARSE, section, "path", "非空字符串字面量", repr(path)))
                continue
            if path in records:
                drifts.append(Drift(K_DUP, path, "path", "全局唯一", "出现 ≥2 次"))
                continue
            records[path] = fields
    return records, drifts


def compare_projection(ledger: Ledger, current: str, rendered: str) -> list[Drift]:
    """三态方向分开点名：盘上缺 / 盘上多 / 同路径字段漂移（＋结构性崩坏两态）。"""
    want = projection_records(ledger)
    have, drifts = parse_declaration(current)
    if any(d.kind == K_PARSE for d in drifts):
        return drifts  # 语法/条目形都崩了，逐格比没有意义
    for path in sorted(set(want) - set(have)):
        drifts.append(Drift(K_MISSING, path, "整条", _desc(want[path]), ""))
    for path in sorted(set(have) - set(want)):
        drifts.append(Drift(K_EXTRA, path, "整条", "", _desc(have[path])))
    for path in sorted(set(want) & set(have)):
        for fld in _DRIFT_FIELDS:
            exp, act = want[path].get(fld, ""), have[path].get(fld, "")
            if exp != act:
                drifts.append(Drift(K_FIELD, path, fld, exp or "（空）", act or "（缺该关键字）"))
    if not drifts:
        drifts.append(Drift(K_FORMAT, OWNERSHIP_REL, "文件级",
                            f"{len(rendered.encode('utf-8'))} 字节",
                            f"{len(current.encode('utf-8'))} 字节"))
    return drifts


def drift_report(drifts: list[Drift], ledger: Ledger, current: str) -> list[str]:
    """把 Drift 清单打成「分类 → 逐格点名 → 下一步」三段可执行输出。"""
    by_kind: dict[str, list[Drift]] = {}
    for d in drifts:
        by_kind.setdefault(d.kind, []).append(d)
    on_disk = len(parse_declaration(current)[0])
    lines = [f"OUT OF SYNC：{OWNERSHIP_REL} ≠ 分类表投影（逐格诊断如下）"]
    lines.append("断链分类：" + "；".join(f"{k} ×{len(by_kind[k])}" for k in _KIND_ORDER if k in by_kind))
    if K_FIELD in by_kind:
        per_field: dict[str, int] = {}
        for d in by_kind[K_FIELD]:
            per_field[d.field] = per_field.get(d.field, 0) + 1
        lines.append("  字段漂移按列：" + "；".join(f"{f} ×{n}" for f, n in sorted(per_field.items())))
    for kind in _KIND_ORDER:
        items = by_kind.get(kind, [])
        if not items:
            continue
        lines.append(f"[{kind}]")
        for d in items[:_MAX_PRINT_PER_KIND]:
            lines.append("  · " + d.render())
        if len(items) > _MAX_PRINT_PER_KIND:
            lines.append(f"  · …另有 {len(items) - _MAX_PRINT_PER_KIND} 格同类，判据同上（此处只点名上限 "
                         f"{_MAX_PRINT_PER_KIND}，不为少报而缩口径）")
        lines.append("  下一步：" + _NEXT_STEP[kind])
    lines.append(f"账面对照：上游现算 在册 {len(ledger.entries)} ＋ 归档 {len(ledger.archive)} 条 vs 盘上 {on_disk} 条")
    lines.append(f"未归属（violations，棘轮吃这个数）= {len(ledger.unowned)}；扫描面 = {ledger.scanned}")
    lines.append(f"上游真身 = {CLASSIFICATION_REL}——改归属只改它，然后跑 `--generate`（禁手改生成物）")
    return lines


def check_sync(ledger: Ledger, rendered: str, target: Path) -> tuple[int, list[str]]:
    """`--check` 的落点：rc 语义与旧版逐字节一致（0=CLEAN／1=不一致），只多了点名与下一步。"""
    if not target.exists():
        # 席 S88：这一态原先**另起一条手搓三行**的输出（同一诊断两条码路）——变异探针实测
        # 「把渲染层 `drift_report` 拔掉之后，唯独这一态照样点名」⇒ 它是七态里唯一不被渲染层执法
        # 覆盖的格子。改走同一个 `drift_report`，七态共一条出口；**rc 语义一字未改**（仍 1、仍点名、仍给下一步）。
        return 1, drift_report(
            [Drift(K_ABSENT, OWNERSHIP_REL, "整文件", "声明源在盘（由 `--generate` 投影）", "文件不存在")],
            ledger, "")
    current = target.read_text(encoding="utf-8")
    if current == rendered:
        return 0, ["CLEAN"]
    return 1, drift_report(compare_projection(ledger, current, rendered), ledger, current)


def main(argv: list[str] | None = None, repo: Path | None = None) -> int:
    """入口。`repo` 显式可换＝自测能在临时副本上跑**同一条真入口**（旧写法只认模块全局 REPO，
    默认参数在 def 时绑死，外部改 `dos.REPO` 只会让「账」与「文件」指向两个 repo——假绿形态之一）。"""
    root = repo or REPO
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--generate", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)
    ledger = compute_ownership(root)
    if args.report:
        print(report_text(ledger))
        return 0
    rendered = render_source(ledger)
    target = root / OWNERSHIP_REL
    if args.generate:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(rendered)
        readback = target.read_text(encoding="utf-8")
        if readback != rendered:  # 写完回读不等＝渲染非确定（排序/换行/编码被破坏），当场拒收
            print(f"GENERATE NOT DETERMINISTIC：回读 {len(readback)} 字节 ≠ 渲染 {len(rendered)} 字节"
                  "＝写盘口不再字节确定，先修 render_source 再谈重投影")
            return 1
        print(f"generated {OWNERSHIP_REL}: {len(ledger.entries)} entries, {len(ledger.archive)} archived")
        return 0
    rc, lines = check_sync(ledger, rendered, target)
    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main())

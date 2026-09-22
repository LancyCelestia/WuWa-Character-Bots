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

用法：
  python scripts/doc_ownership_sync.py --generate   # 重投影并写声明源
  python scripts/doc_ownership_sync.py --check      # 重投影与盘上文件逐字节比对
  python scripts/doc_ownership_sync.py --report     # 打印现算账（未归属数=棘轮取数的同源值）
"""

from __future__ import annotations

import argparse
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--generate", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)
    ledger = compute_ownership()
    if args.report:
        print(report_text(ledger))
        return 0
    rendered = render_source(ledger)
    target = REPO / OWNERSHIP_REL
    if args.generate:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(rendered)
        print(f"generated {OWNERSHIP_REL}: {len(ledger.entries)} entries, {len(ledger.archive)} archived")
        return 0
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if current != rendered:
        print("OUT OF SYNC：声明源与分类表投影不一致——跑 `--generate` 重投影（别手改）")
        return 1
    print("CLEAN")
    return 0


if __name__ == "__main__":
    sys.exit(main())

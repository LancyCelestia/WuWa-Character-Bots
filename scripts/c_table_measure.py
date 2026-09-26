"""c_table_measure — C0–C9 交付三列账的**唯一可复跑度量出口**（席 S249）。

教义（照 §8 C7，禁第二套判据、禁手填数字）：
  · 「起点值」一律从 `BASELINE.md` **现解析**，并回贴解析命中的**行号**（行号也是现算，不硬编码）；
  · 「本轮实测值」一律调真身现算：
      - C2/C4 = `spec_gates_census.compute()['t1']` / `content_census.books()`（G-T1 甲账）
      - C1   = 八道门 pytest 的 **selection**（`--collect-only`，不判绿只点数）
      - C3   = 域外 py 计数：磁盘现走（find 口径，与 BASELINE §1 同尺）为主，`git ls-files`（tracked 口径）并列
      - C6   = `FALSIFIED.md` 条数（`^| F-\\d+`）
      - C9a  = `PARKED.md` 条数（`^## P-\\d+`）
      - C0-c = 复刻 BASELINE §0 那条 grep（五目录含垫片标记的 py 文件数）
      - C5-a = `ruff check .`；C5-c = 树卫生 `__pycache__`/`*.pyc` 现走；C9 = `SEAT-MAIN.md` 补派行现算
      - C5-b = `mypy plugins`（默认**不跑**，耗时；须 `--with-mypy` 显式开启）
  · 「判定」态：`未做（起点==实测）` / `不可判（缺证据）` / `不可判（起点不可复算）` /
    `较起点改善±N` / `较起点退步±N`（用户 2026-09-23 裁定：**全表禁「达标」二字**——旧版方向盲，
    欠账 1057→1279 也记达标）；其中「起点==实测」按**数值相等**判，口径不可比一律降级「不可判」。
  · 判据位（`JUDGE_SLOTS`）不许静默降态：该族任何「不可判」同时进 violations（rc≠0）。
  · 内置硬断言（必做②）：任何「实测」单元格只准来自 `measure()` 可调用件的返回，
    或常量「不可判（…）」；脚本**绝不把字面数字写进实测列**。渲染前逐行 assert 该不变量，违反即崩，不许静默放行。

复跑（与 CENSUS/c4_measure 同一环境咒语）：
  PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \\
    ../ChatBot_Runtime/venv/Scripts/python.exe scripts/c_table_measure.py [--with-mypy] [--baseline PATH]

输出：stdout 打印全表，同时落盘 `C-TABLE.md`（本波目录，除非 --out）。
退出码：0 度量成功（各条改善/退步/未做/不可判另说；有内置违规＝2，且违规先落册再返回）；
        2 亦用于起点册/真身读不出来（fail-closed，不折零）或实测劣于起点。
        ⚠ `--only` 为局部渲染：**不带 `--no-write` 也不带显式 `--out` 时拒绝落盘**，
        否则"只渲一行＋默认落盘"会把整册覆盖成一行（席 TX330 洞 C，与两起"打开即截零"同族）。
自测钩子：--selftest-unparseable ROWKEY 把某条实测强制替换成不可解析串，验证不崩且判「不可判」（必做⑤）。
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

TAX = ROOT / ".superpowers/sdd/2026-09-22-taxonomy"
BASELINE_PATH = TAX / "BASELINE.md"
OUT_PATH = TAX / "C-TABLE.md"
FALSIFIED_PATH = TAX / "FALSIFIED.md"
PARKED_PATH = TAX / "PARKED.md"
SEAT_MAIN = TAX / "SEAT-MAIN.md"
PY = ROOT.parent / "ChatBot_Runtime" / "venv" / "Scripts" / "python.exe"
if not PY.exists():  # 非 win 布局兜底
    PY = Path(sys.executable)

UNPARSEABLE = "<<UNPARSEABLE-NOT-A-NUMBER>>"  # 仅 --selftest-unparseable 注入

# 八道门（selection 用）——缺件由 _collect_count 逐文件容错，绝不整体崩
GATE_FILES = [
    "tests/test_board_taxonomy_gate.py",
    "tests/test_taxonomy_spec_gates.py",
    "tests/test_physical_placement_gate.py",
    "tests/test_dispatch_saturation_gate.py",
    "tests/test_doc_ownership_ledger.py",
    "tests/test_shim_retirement_ledger.py",
    "tests/test_credential_domain_binding_gate.py",
    "tests/test_voice_central_entry_gate.py",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    # check=False：真身命令非零退出也要读它的 stdout 现算（如 ruff 有错），不抛
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          cwd=str(ROOT), check=False)


# ---------------------------------------------------------------- 起点册解析（现解析 + 现行号）
def baseline_anchor(lines: list[str], *patterns: str) -> tuple[int | None, str, int | None]:
    """在 BASELINE.md 里按顺序找第一个命中 pattern 的行。
    返回 (1 基行号, 该行原文截断, 首个捕获的整数或 None)。找不到→(None,'',None)。"""
    compiled = [re.compile(p) for p in patterns]
    for idx, line in enumerate(lines):
        for rx in compiled:
            m = rx.search(line)
            if m:
                num: int | None = None
                for g in m.groups():
                    if g is not None and g.isdigit():
                        num = int(g)
                        break
                return idx + 1, line.strip()[:90], num
    return None, "", None


# ---------------------------------------------------------------- 真身侧度量（每条一个可调用件；None=拿不到）
def m_c2() -> str:
    import spec_gates_census as sgc
    res = sgc.compute(ROOT)
    t1 = res["t1"]
    if not isinstance(t1, list):
        raise TypeError("t1 形状异常")
    return str(len(t1))


def m_c4() -> str:
    import content_census as cc
    import spec_gates_census as sgc
    res = sgc.compute(ROOT)
    return str(cc.books(res)[cc.BOOK_CENSUS])


def m_c3() -> str:
    # find 口径：磁盘现走 plugins 下 *.py 且不在 /domains/
    outside = 0
    for p in (ROOT / "plugins").rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if "/domains/" not in "/" + rel:
            outside += 1
    return str(outside)


def m_c3_git() -> str:
    out = _run(["git", "ls-files", "plugins"], 60)
    files = [l for l in out.stdout.splitlines() if l.endswith(".py")]
    return str(sum(1 for f in files if "/domains/" not in "/" + f))


def _collect_count(files: list[str]) -> tuple[int, list[str]]:
    """返回（合计条数, 缺件名单）。**缺件绝不静默算零**——旧写法 `continue` 后
    八道门少跑三门只是"数字变小"，正是「缩小扫描面而账不察觉」的现成通路（席 TX330）。"""
    total = 0
    missing: list[str] = []
    for f in files:
        if not (ROOT / f).exists():
            missing.append(f + "=不存在")
            continue
        try:
            out = _run([str(PY), "-m", "pytest", f, "-p", "no:cacheprovider",
                        "--basetemp", str(ROOT / ".s249co_tmp"), "-q", "--collect-only"], 120)
        except subprocess.TimeoutExpired:
            missing.append(f + "=超时")
            continue
        m = re.search(r"(\d+) tests? collected", out.stdout)
        if m:
            total += int(m.group(1))
        else:
            missing.append(f + "=无 collected 行")
    return total, missing


def m_c1() -> str | None:
    n, missing = _collect_count(GATE_FILES)
    if not n and missing:
        return None
    return f"{n} 条（实到 {len(GATE_FILES) - len(missing)}/{len(GATE_FILES)} 件{'' if not missing else '，缺：' + '、'.join(missing)}）"


def m_c0a_items() -> str | None:
    n, missing = _collect_count(["tests/test_board_taxonomy_gate.py"])
    if not n and missing:
        return None
    return f"{n}（缺件：{'、'.join(missing)}）" if missing else str(n)


def m_c0c() -> str:
    # 复刻 BASELINE §0 的 grep：五目录含标记的 py 文件数
    dirs = ["character", "runtime", "sources", "contracts", "audit"]
    rx = re.compile(r"Compat shim|Live re-export|_CANONICAL")
    hit = 0
    base = ROOT / "plugins/bot_unified_runtime"
    for d in dirs:
        for p in (base / d).rglob("*.py"):
            try:
                if rx.search(_read(p)):
                    hit += 1
            except OSError:
                continue
    return str(hit)


def m_ruff() -> str | None:
    try:
        out = _run([str(PY), "-m", "ruff", "check", ".", "--no-cache"], 180)
    except subprocess.TimeoutExpired:
        return None
    if "All checks passed" in out.stdout:
        return "0"
    m = re.search(r"Found (\d+) error", out.stdout)
    return m.group(1) if m else out.stdout.strip().splitlines()[-1][:40]


def m_hygiene() -> str:
    pc = sum(1 for p in (ROOT / "plugins").rglob("__pycache__") if p.is_dir())
    pc += sum(1 for p in (ROOT / "tests").rglob("__pycache__") if p.is_dir())
    pc += sum(1 for p in (ROOT / "scripts").rglob("__pycache__") if p.is_dir())
    pyc = sum(1 for p in (ROOT / "plugins").rglob("*.pyc"))
    pyc += sum(1 for p in (ROOT / "tests").rglob("*.pyc"))
    pyc += sum(1 for p in (ROOT / "scripts").rglob("*.pyc"))
    return f"__pycache__={pc} / *.pyc={pyc}"


def m_falsified() -> str:
    return str(len(re.findall(r"(?m)^\|\s*F-\d+\b", _read(FALSIFIED_PATH))))


def m_parked() -> str:
    return str(len(re.findall(r"(?m)^##\s*P-\d+\b", _read(PARKED_PATH))))


def m_dispatch_rows() -> str:
    txt = _read(SEAT_MAIN)
    return str(len(re.findall(r"(?m)^\|\s*(?:2026-)?\d{2}:\d{2}Z", txt)) +
               len(re.findall(r"(?m)^\|\s*2026-\d{2}-\d{2}T\d{2}:\d{2}", txt)))


def m_c9_gate() -> str:
    """C9 的**执法尺**：直接用门自己的解析口数行数，不在本件另造第二把尺。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_gc1_ruler", ROOT / "tests" / "test_dispatch_saturation_gate.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("取不到执法尺真身：tests/test_dispatch_saturation_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return str(len(mod._read_backfill_rows()))


def m_c0() -> str | None:
    if not BASELINE_PATH.exists():
        return None
    n = len(_read(BASELINE_PATH).splitlines())
    sec6 = "有" if re.search(r"(?m)^## 6", _read(BASELINE_PATH)) else "无"
    return f"{n} 行 / §6 更正段：{sec6}"


def m_mypy() -> str | None:  # 仅在 --with-mypy 时被挂上
    # 缓存目录**绝不允许落在源码树**（AGENTS 铁律 6）：旧值 `ROOT/.s249mypy_tmp` 实测在仓库根
    # 留下 37.9 MiB 增长件，且因名字不在 `test_static_hygiene_snapshot.CACHE_DIR_NAMES`
    # 精确集合里而**结构性逃过卫生门**（席 TX282 坐实）。改指 %TEMP%，无环境变量时兜到系统临时目录。
    cache_dir = Path(os.environ.get("TMPDIR") or os.environ.get("TEMP") or tempfile.gettempdir())
    cache_dir = cache_dir / "chatbot-c-table-mypy-cache"
    try:
        out = _run([str(PY), "-m", "mypy", "--cache-dir", str(cache_dir),
                    "--explicit-package-bases", "--ignore-missing-imports", "plugins"], 280)
    except subprocess.TimeoutExpired:
        return None
    m = re.search(r"Success: no issues found in (\d+) source files", out.stdout)
    if m:
        return f"Success / {m.group(1)} 文件"
    m2 = re.search(r"Found (\d+) error", out.stdout)
    return f"Found {m2.group(1)} errors" if m2 else out.stdout.strip().splitlines()[-1][:40]


def _num(s: str | None) -> int | None:
    if s is None:
        return None
    m = re.fullmatch(r"\s*(\d+)\s*", s)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- 行定义（key, 标题, 起点anchor, measure件, 备注）
# measure 件为 None → 该条恒「不可判」（架构即内置断言：无真身就不许出实测值）
ROWS: list[dict] = [
    {"key": "C0", "title": "起点快照 BASELINE.md 存在", "anchor": None, "m": m_c0,
     "start_text": "（波前不存在）", "note": "本波新落盘"},
    {"key": "C0-a", "title": "板块门 selection 条数",
     "anchor": [r"(\d+)\s+items"], "m": m_c0a_items, "start_text": None,
     "note": "起点 BASELINE §3 items；口径同为 pytest selection"},
    {"key": "C0-c", "title": "五目录垫片标记 py 文件数",
     # 只准锚「标记 grep」那一行（BASELINE §0 末行 # 78）；旧版还带一条 `...wc -l # (\d+)`
     # 会先撞上**上一行**的文件总数 87（锚按行序而非式序）＝错锚，见席 TX327/TX285 与 SEAT-MAIN §拾贰·补。
     "anchor": [r"audit\} --include=\*\.py.*?#\s*(\d+)"], "m": m_c0c,
     "start_text": None, "note": "复刻 BASELINE §0 grep；shim_retirement 账记 79（含装配文件）"},
    {"key": "C1", "title": "八道门 pytest selection（不判绿）", "anchor": None, "m": m_c1,
     "start_text": "起点：门不存在（§2）", "note": "仅点数，是否全绿须实跑（本席不代跑，见不可信点）"},
    {"key": "C2", "title": "G-T1 未模板驱动（甲账）",
     "anchor": [r"未模板驱动\*\* \| \*\*(\d+)\*\*", r"G-T1 未模板驱动.*?(\d{3,})"], "m": m_c2,
     "start_text": None, "note": "§6 更正链 1874→1079；管辖面随扫描加严上升属如实还债"},
    {"key": "C3", "title": "域外 py（find 口径）",
     "anchor": [r"域外 py（不在 domains/ 下）\*\* \| \*\*(\d+)\*\*"], "m": m_c3,
     "start_text": None, "note": "git-tracked 口径另计（见下行说明）；地板 211"},
    {"key": "C4", "title": "CENSUS 未模板驱动（books G-T1）",
     "anchor": [r"md 面 (\d+)、已驱动"], "m": m_c4,
     "start_text": None, "note": "须与 C2 逐位相等（同支引用）"},
    {"key": "C5", "title": "全量 pytest",
     "anchor": [r"(\d+) failed / (\d{4,}) passed"], "m": None,
     "start_text": None, "note": "缺证据：全量套件须 dev.ps1 -Task test（≈13min），本席未现跑"},
    {"key": "C5-a", "title": "ruff check .", "anchor": None, "m": m_ruff,
     "start_text": "起点：All checks passed（§3）", "note": "0=通过"},
    {"key": "C5-c", "title": "树卫生 __pycache__/*.pyc",
     "anchor": [r"__pycache__` = \*\*(\d+)\*\*、`\*\.pyc` = \*\*(\d+)\*\*"], "m": m_hygiene,
     "start_text": None, "note": "BASELINE §5 记 pycache1/pyc4；收口须 0"},
    {"key": "C5-b", "title": "mypy plugins", "anchor": None, "m": None,
     "start_text": "起点：Success / 645 文件（§3）", "note": "默认不跑（耗时）；须 --with-mypy"},
    {"key": "C6", "title": "证伪账 FALSIFIED.md 条数", "anchor": None, "m": m_falsified,
     "start_text": "起点：无人做过（=0）", "note": "自攻/准绳席交付的证据件②"},
    {"key": "C9", "title": "SEAT-MAIN 补派行（grep 尺，**非判据位**）", "anchor": None, "m": m_dispatch_rows,
     "start_text": "起点：无表", "note": "随席位增长，交付须重跑标时刻"},
    {"key": "C9-gate", "title": "SEAT-MAIN 补派行（执法尺＝门读的 _parse_backfill_rows，判据位·**地板尺**）",
     "anchor": None, "m": m_c9_gate,
     "start_text": "64（首届核账 2026-09-23T18:21:50Z；尺＝tests/test_dispatch_saturation_gate.py::"
                   "_read_backfill_rows；命令＝python -m pytest tests/test_dispatch_saturation_gate.py -q。"
                   "旧起点「26（R0 回填前实测）」无尺身份三元组、经两种口径重算得 16/29 皆非 26 ⇒ **作废**，见 FALSIFIED F-109）",
     "start_num": 64,
     "note": "grep 尺只数行、门尺还要求五列形制与整数在飞数 ⇒ 判据位只能用这一支（席 TX327）；"
             "⚠ 门尺今日按 5 列滤网**静默吃掉一枚 4 列行**（列形直方图 {5:70, 4:1}，席 TX330）⇒ 写行必须五格齐"},
    {"key": "C9-a", "title": "PARKED.md 挂账条数", "anchor": None, "m": m_parked,
     "start_text": "起点：—", "note": "brief 指定原始件计数"},
]


# ---------------------------------------------------------------- 方向册（2026-09-23 主会话补，用户裁定）
# 原判定只问「起点数值 == 实测数值 ?」——不等就判达标，**方向盲**：
# C2 起点 1057 → 实测 1279（欠账**涨** 222）也记「达标」，等于把退步当成绩。
# 现每行声明变好方向：down=越小越好、up=越大越好（只增的账/门条数）、na=无可比方向。
# 同批把交付文案里的「达标」二字整体撤下（用户：全表禁"达标"），改写成带符号的账。
DIRECTION: dict[str, str] = {
    "C0": "na",
    # C0-a/C1 从 "up" 降为 "na"（席 TX330）：门条数与 selection 条数**越多不代表越好**，
    # 标 up 等于给"往门里灌水"发成绩；其真价值是"该行有没有值"，不是大小。
    "C0-a": "na", "C0-c": "down", "C1": "na",
    "C2": "down", "C2-r0": "na", "C2-official": "down",
    "C3": "down", "C4": "down",
    "C5": "down", "C5-a": "down", "C5-b": "down", "C5-c": "down",
    # C6 同型：证伪条数涨＝今天多翻了一次案，不是业绩；C9 族为 append-only 流水。
    # C9-gate 取 "floor"：补派行是**扫描面地板**（跌破即红），但涨也不记"改善"，否则等于给灌水发成绩。
    "C6": "na", "C9": "na", "C9-gate": "floor", "C9-a": "na",
}

# 判据位行：这些行的「不可判」**不许只印在表里**，必须同时进 violations（席 TX330 洞 A 的解法：
# 旧写法只有"退步"进 violations，判据位读不到真身时 rc=0 静默降态＝尺挪位即失明，账却装绿）。
JUDGE_SLOTS: frozenset[str] = frozenset({"C2-official", "C9-gate"})



def m_c2_r0() -> str:
    """护栏四第①栏：R0 **改判**划进登记栏的量（换尺造成的账面减少，不是消化）。"""
    import spec_gates_census as sgc
    reg = sgc.compute(ROOT)["t1_registered_process"]
    if not isinstance(reg, list):
        raise TypeError("t1_registered_process 形状异常")
    return str(len(reg))


def m_c2_official() -> str:
    """护栏四第②栏：**对外欠账**现值（R0 之后唯一判据栏，真降账只看这一栏）。"""
    import spec_gates_census as sgc
    debt = sgc.compute(ROOT)["t1_debt_official"]
    if not isinstance(debt, list):
        raise TypeError("t1_debt_official 形状异常")
    return str(len(debt))


# 护栏四：G-T1 这一枚从此**三栏同屏**，谁也不许再拿单栏数当结论。
ROWS.extend([
    {"key": "C2-r0", "title": "G-T1 过程件登记栏（R0 改判·不是消化）", "anchor": None,
     "m": m_c2_r0, "start_text": "0（R0 之前无此栏）", "start_num": 0,
     "note": "本栏增大＝更多页被划成'登记'，不欠但也不许当成还了债"},
    {"key": "C2-official", "title": "G-T1 对外欠账（R0 唯一判据栏）", "anchor": None,
     "m": m_c2_official,
     "start_text": "369（尺＝tests/test_taxonomy_spec_gates.py::AUDIT_HISTORY_T1_OFFICIAL，2026-09-23 首届核账）",
     "start_num": 369, "note": "降幅＝实际消化 −M；与 C2-r0 相加＝旧尺总账 C2（恒等式由门逐刻锁）"},
])


def render(with_mypy: bool, baseline_path: Path, corrupt_key: str | None,
           only: set[str] | None = None) -> tuple[str, list[str]]:
    lines_doc = _read(baseline_path).splitlines() if baseline_path.exists() else []
    if with_mypy:
        # 把 mypy 挂到 C5-b 的度量件上
        for row in ROWS:
            if row["key"] == "C5-b":
                row["m"] = m_mypy

    out: list[str] = [
        "# C-TABLE — C0–C9 三列账（脚本现算产物，禁手填）",
        "",
        ("> 由 `scripts/c_table_measure.py` 现算生成。起点值解析自 `BASELINE.md`（含行号）；"
         "实测值调真身现算。判定：起点数值==实测数值→`未做`；无真身可算→`不可判（缺证据）`；"
         "数值不等→按该行声明的**方向**判改善/退步并给带符号账（用户 2026-09-23 裁定：全表禁「达标」二字，"
         "旧版方向盲——欠账从 1057 涨到 1279 也曾被记成达标）。"),
        "",
        "| 项 | 起点值（BASELINE 行号） | 本轮实测值 | 复现命令 | 判定 |",
        "|---|---|---|---|---|",
    ]
    violations: list[str] = []

    for row in ROWS:
        key = row["key"]
        if only is not None and key not in only:
            continue
        # 起点
        if row["anchor"]:
            ln, raw, snum = baseline_anchor(lines_doc, *row["anchor"])
            if ln:
                start_disp = f"**{snum}**（行 {ln}）" if snum is not None else f"`{raw}`（行 {ln}）"
            else:
                start_disp = row["start_text"] or "（册内未锚到）"
        else:
            snum, start_disp = None, row["start_text"] or "—"
            # 起点数可显式声明（护栏四两行的起点住门常数、不住 BASELINE）
            if row.get("start_num") is not None:
                snum = int(row["start_num"])

        # 起点自称"实测值"却拿不出尺身份三元组 ⇒ 不许当基线用（席 TX330 判据 (b)）
        unrepro: str | None = row.get("start_unreproducible")

        # 实测（只准来自可调用件；架构保证不会写字面数字）
        fn = row["m"]
        if fn is None:
            measured = None
            why = row["note"]
        else:
            try:
                measured = fn()
            except Exception as exc:  # noqa: BLE001 — 度量件任何异常一律降级为「不可判」，绝不崩/绝不折零
                measured = None
                why = f"真身读数失败：{type(exc).__name__}: {exc}"
        if corrupt_key and key == corrupt_key:
            measured = UNPARSEABLE  # 必做⑤：注入不可解析串
        if measured is None:
            measured_disp = "（拿不到）"
            verdict = f"不可判（缺证据：{why}）"
        elif unrepro:
            measured_disp = str(measured)
            verdict = f"不可判（起点不可复算：{unrepro}）"
        else:
            measured_disp = str(measured)
            mnum = _num(measured)
            if measured == UNPARSEABLE:
                verdict = "不可判（实测不可解析）"
            elif snum is None or mnum is None:
                # 口径不可数值比 → 不出任何"完成"字样
                verdict = (
                    "已出实测（起点无同形数，不做前后对比）"
                    if snum is None
                    else "不可判（口径不可比）"
                )
            elif mnum == snum:
                verdict = "未做（起点==实测）"
            else:
                direction = DIRECTION.get(key, "na")
                delta = mnum - snum
                sign = f"{'−' if delta < 0 else '+'}{abs(delta)}"
                if direction == "na":
                    verdict = f"账已变动 {sign}（{snum}→{mnum}，该行无方向语义，不判好坏）"
                elif direction == "floor":
                    # 地板尺：跌破＝红；高于地板只是"面没缩"，**不发"改善"成绩**（防灌水，席 TX330）
                    if delta < 0:
                        verdict = f"跌破地板 {sign}（{snum}→{mnum}）——该行是扫描面地板，跌破即红"
                        violations.append(
                            f"{key}: 实测跌破地板 {snum}→{mnum}（尺＝地板，非成绩）"
                            "——扫描面缩了，禁按「零违规」放行")
                    else:
                        verdict = f"地板之上 {sign}（{snum}→{mnum}，涨不记分，只证面未缩）"
                else:
                    better = delta < 0 if direction == "down" else delta > 0
                    verdict = f"较起点{'改善' if better else '退步'} {sign}（{snum}→{mnum}）"
                    if not better:
                        violations.append(
                            f"{key}: 实测劣于起点 {snum}→{mnum}（方向={direction}）"
                            "——该行今天更差，禁按旧口径记成成绩")

        # 判据位不许静默降态：任何「不可判」都必须同时进 violations（rc≠0）。
        # 旧写法只有"退步"进 violations ⇒ 执法尺真身被改名/挪位时表里写"不可判"而 rc=0，账装绿。
        if key in JUDGE_SLOTS and verdict.startswith("不可判"):
            violations.append(f"{key}: 判据位取不到可判读数 ⇒ {verdict}")

        # 内置硬断言（必做②）：实测列不得是脚本手写的裸数字常量
        # —— 通过：measured 只能来自 fn()/UNPARSEABLE/None；fn is None 时实测必为「（拿不到）」
        if fn is None and measured_disp not in ("（拿不到）",):
            violations.append(f"{key}: 无可调用件却出现实测值，疑似手填")
        if corrupt_key is None and measured_disp.isdigit() and fn is None:
            violations.append(f"{key}: 字面数字且无 measure 件")

        cmd = _cmd_for(key, with_mypy)
        out.append(f"| **{key}** {row['title']} | {start_disp} | {measured_disp} | `{cmd}` | {verdict} |")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out.append("")
    # 洞 B（席 TX330）：旧册通篇零时刻 ⇒ 任何人拿旧册当今日读数；违规只走 stderr ⇒ 洞 A 可见性不对称。
    out.append(f"> **本册生成时刻**：{stamp}（`datetime.now(UTC)` 现取）——实测列同刻，起点列各自另注尺身份。")
    out.append(f"> **内置违规 {len(violations)} 条**（与 stderr 双写，不许只走一条腿）："
               + ("；".join(violations) if violations else "无"))
    out.append("<!-- 复现：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 "
               "python scripts/c_table_measure.py -->")
    return "\n".join(out), violations


def _cmd_for(key: str, with_mypy: bool) -> str:
    return {
        "C0": "python scripts/c_table_measure.py --out NUL  # 行数现走",
        "C0-a": "pytest tests/test_board_taxonomy_gate.py --collect-only -q",
        "C0-c": "grep -rlE 'Compat shim|Live re-export|_CANONICAL' plugins/bot_unified_runtime/{character,runtime,sources,contracts,audit} --include=*.py | wc -l",
        "C1": "pytest <八道门 8 件> --collect-only -q",
        "C2": "python scripts/spec_gates_census.py --report  # 或 c4_measure.py",
        "C3": "find plugins -name '*.py' -not -path '*/domains/*' | wc -l  # 另 git ls-files 口径",
        "C4": "python scripts/content_census.py --check",
        "C5": "powershell -File scripts/dev.ps1 -Task test",
        "C5-a": "python -m ruff check . --no-cache",
        "C5-c": "find plugins tests scripts -name __pycache__ -o -name '*.pyc'",
        "C5-b": ("python -m mypy plugins" if with_mypy else "（默认不跑，加 --with-mypy）"),
        "C6": "grep -cE '^\\| *F-[0-9]+' FALSIFIED.md",
        "C9": "grep -cE '^\\| *(2026-)?[0-9]{2}:[0-9]{2}Z' SEAT-MAIN.md",
        "C9-a": "grep -cE '^## P-[0-9]+' PARKED.md",
        # 判据位三行各给真复现命令（旧写法缺键 ⇒ 复现列自指整件，反不如"非判据位"那行强，席 TX330）
        "C9-gate": "python -m pytest tests/test_dispatch_saturation_gate.py -q  # 同一解析口 _read_backfill_rows",
        "C2-r0": ("python -c \"import sys;sys.path.insert(0,'scripts');"
                  "from pathlib import Path;import spec_gates_census as s;"
                  "print(len(s.compute(Path('.'))['t1_registered_process']))\""),
        "C2-official": ("python -c \"import sys;sys.path.insert(0,'scripts');"
                        "from pathlib import Path;import spec_gates_census as s;"
                        "print(len(s.compute(Path('.'))['t1_debt_official']))\""),
    }.get(key, "python scripts/c_table_measure.py")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="c_table_measure")
    ap.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    ap.add_argument("--out", type=Path, default=None,
                    help="落盘目标（缺省＝整册渲染时写 C-TABLE.md；`--only` 局部渲染时**拒绝**写默认册）")
    ap.add_argument("--with-mypy", action="store_true", help="显式跑 mypy plugins（耗时）")
    ap.add_argument("--selftest-unparseable", metavar="ROWKEY", default=None,
                    help="把该行实测强制注入为不可解析串（必做⑤）")
    ap.add_argument("--only", metavar="K1,K2", default=None,
                    help="仅渲染指定行（自测用，跳过重算）")
    ap.add_argument("--no-write", action="store_true", help="只打印不落盘")
    args = ap.parse_args(argv)
    only = set(args.only.split(",")) if args.only else None
    try:
        text, violations = render(args.with_mypy, args.baseline, args.selftest_unparseable, only)
    except (OSError, LookupError, KeyError) as exc:
        print(f"[c_table_measure] 读起点册/真身失败（fail-closed）：{exc}", file=sys.stderr)
        return 2
    print(text)
    # 先落册、后报违规：账必须**留在册上**再红——旧顺序是「一有违规就不落盘」，
    # 等于把退步那一行从账本里抹掉，只留一句 stderr，属"把红从一本账搬到另一本账"。
    # 洞 C（席 TX330）：`--only` 只渲一两行，若按缺省路径落盘＝**整册被覆盖成局部册**，
    # 与两起"打开即截零"同族。故：局部渲染 + 未显式 --out ⇒ 拒绝落盘（要局部落盘须自己给新文件名）。
    out_path = args.out if args.out is not None else (None if only is not None else OUT_PATH)
    if args.no_write:
        pass
    elif out_path is None:
        print("\n[拒绝落盘] --only 为局部渲染，未给 --out 时不写默认册（防整册被局部输出覆盖，席 TX330 洞 C）。"
              "确需留证：--out <私有目录/局部册.md>", file=sys.stderr)
    else:
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"\n[已落盘] {out_path}", file=sys.stderr)
    if violations:
        print("\n[内置断言违规——疑似手填或实测劣于起点，拒绝静默放行]", file=sys.stderr)
        for v in violations:
            print("  - " + v, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

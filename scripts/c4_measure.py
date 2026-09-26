"""c4_measure — C4（CENSUS「未模板驱动」条目数）唯一可复跑度量出口（席 S219）。

教义（禁第二套判据）：
  · 交付值一律取自真身取数口 `spec_gates_census.compute()['t1']`（甲账 G-T1，
    经 `content_census.books()` 同支引用——与 CENSUS.md §〇 第 18 行在册口径一致）；
  · 本件只 *读* 两本账册（CENSUS.md / INCODE-CENSUS.md）并解析其登记值，
    绝不改写任何账册正文、绝不重写任何判据；
  · 三列输出：①册载条目数（§〇/§三 印刷值 + §六 明细表「否」行现集）
    ②真身现算未驱动数（当场 compute()） ③差集逐枚坐标 + 归因（时间差/口径差/真漏），禁「约」。

复跑（与 CENSUS.md §〇 同一环境咒语）：
  PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \\
    ../ChatBot_Runtime/venv/Scripts/python.exe scripts/c4_measure.py

退出码：0 度量成功（C4 是否归零另说）；2 账册/真身读不出来；3 幂等双跑不一致
（树在动时须显式给 --inflight-window，拒绝静默忽略）。--fail-if-nonzero 供未来常驻锁消费。
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import content_census as cc
import spec_gates_census as sgc

CENSUS_PATH = ROOT / ".superpowers/sdd/2026-09-22-taxonomy/CENSUS.md"
INCODE_PATH = ROOT / ".superpowers/sdd/2026-09-22-taxonomy/INCODE-CENSUS.md"
FINGERPRINT_SCRIPTS = (
    "scripts/doc_fact_discipline.py",
    "scripts/spec_gates_census.py",
    "scripts/doc_template_sync.py",
    "scripts/doc_templates.py",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 册侧解析（只读账本，非判据）
def parse_census_ledger(text: str) -> dict:
    """从 CENSUS.md 提取：快照时刻/指纹/§〇§三印刷值/§六明细「否」集/§二之二代码面登记。"""
    m = re.search(r"生成时间 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[+-]\d{4})", text)
    snap = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S%z") if m else None
    fps = dict(re.findall(r"(scripts/\w+\.py) sha256\[:16\]=([0-9a-f]{16})", text))
    c2 = re.search(r"\*\*C2\*\*.*?\*\*(\d+)\*\*", text)
    c4 = re.search(r"\*\*C4\*\*.*?\*\*(\d+)\*\*", text)
    g1 = re.search(r"G-T1 无模板头且非生成物 = (\d+)", text)

    # §一 类别→面（册载）：用 §二 汇总表行（`| cat | md|code | ... |`）建映射。
    cat_surface: dict[str, str] = {}
    for row in re.finditer(r"^\| ([a-z0-9-]+) \| (md|code) \| ", text, re.MULTILINE):
        cat_surface[row.group(1)] = row.group(2)

    undriven_md: set[str] = set()
    driven_md: set[str] = set()
    code_rows: dict[str, tuple[int, int]] = {}  # 类别 → (在册, 未驱动) §二之二
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 8 and cells[1] in cat_surface and cells[5] in ("是", "否"):
            rel = cells[0]
            if cat_surface[cells[1]] == "md":
                (undriven_md if cells[5] == "否" else driven_md).add(rel)
        if len(cells) == 10 and cells[2] == "code" and cells[1] in cat_surface:
            try:
                code_rows[cells[1]] = (int(cells[3]), int(cells[7]))
            except ValueError:
                pass  # 「取数口缺」等非数字行：如实跳过，不折算
    return {
        "snapshot_at": snap,
        "fingerprints": fps,
        "printed": {
            "C2": int(c2.group(1)) if c2 else None,
            "C4": int(c4.group(1)) if c4 else None,
            "G-T1 §三": int(g1.group(1)) if g1 else None,
        },
        "undriven_md": undriven_md,
        "driven_md": driven_md,
        "code_rows": code_rows,
    }


def parse_incode_ledger(text: str) -> dict:
    """INCODE-CENSUS.md 登记值（口径：容器/字符串叶，非甲账类别件数——见三列对账 §C）。"""
    def num(pattern: str) -> int | None:
        m = re.search(pattern, text)
        return int(m.group(1)) if m else None

    return {
        "池容器数": num(r"池命名容器 (\d+) 个"),
        "池条数": num(r"池命名容器 \d+ 个 \| (\d+)"),
        "通用CJK条数": num(r"通用 CJK 字符串.*?(\d+) 条 /"),
        "扫描文件数": num(r"扫描文件数：\*\*(\d+)\*\*"),
        "命中文件数": num(r"命中文件数：\*\*(\d+)\*\*"),
        "命中条数": num(r"命中条数（合格字符串叶）：\*\*(\d+)\*\*"),
    }


# ---------------------------------------------------------------- 真身侧（单一出口）
def truth_face() -> dict:
    """C4 = f(真身)。只调真身取数口，一条不抄。"""
    res = sgc.compute(ROOT)
    t1 = res["t1"]
    if not isinstance(t1, list):
        raise TypeError("真身取数口 t1 形状异常")
    und = {cc.rel_of(e) for e in t1}
    reasons: dict[str, set[str]] = {}
    for e in t1:
        if "#" in e:
            reasons.setdefault(cc.rel_of(e), set()).add(e.split("#", 1)[1])
    pages = {p.rel: p for p in cc._res_pages(res)}
    books = cc.books(res)
    ok, why = cc.reconcile_books(books)
    return {
        "res": res,
        "und": und,
        "reasons": reasons,
        "pages": pages,
        "b_ok": res["b_ok"],
        "gen_all": res["generated_all"],
        "c4": books[cc.BOOK_CENSUS],
        "t1_len": len(t1),
        "books": books,
        "conversion_ok": ok,
        "conversion_why": why,
    }


# ---------------------------------------------------------------- 归因
def attribute(ledger: dict, truth: dict) -> list[tuple[str, str, str]]:
    """差集逐枚归因。返回 (坐标, 归因类, 证据)。禁「约」：每条都落到具体证据。"""
    out: list[tuple[str, str, str]] = []
    snap: datetime | None = ledger["snapshot_at"]

    def age_is_new(rel: str) -> bool | None:
        p = ROOT / rel
        if snap is None or not p.exists():
            return None
        m = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        return m > snap.astimezone(timezone.utc)

    for rel in sorted(ledger["undriven_md"] - truth["und"]):
        p = ROOT / rel
        if not p.exists():
            out.append((rel, "时间差", "册后页已消失（盘上不存在）"))
        elif rel in truth["b_ok"]:
            out.append((rel, "时间差", "册后达成机制(b)：生成页当场重渲染字节等值"))
            # 注意：b_ok 含生成物页；若挂头则同时成立，两证据并存取首条
        elif rel in truth["pages"]:
            pg = truth["pages"][rel]
            ev = "现判已驱动（front-matter 在册模板且无类别错配）"
            fm = getattr(pg, "fm", None)
            tpl = getattr(fm, "template", None) if fm is not None else None
            out.append((rel, "时间差", f"{ev} template={tpl or '?'}"))
        else:
            out.append((rel, "口径差", "在册判否但现扫描面（walk_content_pages）不再产出该页"))
    for rel in sorted(truth["und"] - ledger["undriven_md"]):
        in_ledger_driven = rel in ledger["driven_md"]
        new = age_is_new(rel)
        if in_ledger_driven:
            drift = rel in truth["gen_all"] and rel not in truth["b_ok"]
            ev = "机制(b) 当场复现翻转为漂移" if drift else "现判未驱动而册载『是』"
            rsn = truth["reasons"].get(rel)
            if rsn:
                ev += "；真身尾注 " + "/".join(sorted(rsn))
            out.append((rel, "口径差", ev))
        elif new is True:
            out.append((rel, "时间差", "册后新增页（mtime 晚于快照时刻）"))
        elif new is False:
            out.append((rel, "真漏", "册生成时已存在（mtime 早于快照）却未被登记"))
        else:
            out.append((rel, "口径差", "盘上不存在/无快照时刻可比（读方竞态，双跑自证另判）"))
    return out


# ---------------------------------------------------------------- 报告
def measure(census_path: Path, incode_path: Path) -> tuple[str, dict]:
    lines: list[str] = []
    ledger = parse_census_ledger(_read(census_path))
    incode = parse_incode_ledger(_read(incode_path))
    truth = truth_face()
    diffs = attribute(ledger, truth)

    fps_now = {rel: cc._sha16(rel) for rel in FINGERPRINT_SCRIPTS}
    drift = [
        f"{rel}: 册载 {ledger['fingerprints'].get(rel)} vs 现算 {now}"
        for rel, now in fps_now.items()
        if ledger["fingerprints"].get(rel) != now
    ]

    lines.append("== C4 唯一度量出口（席 S219）==")
    lines.append(f"快照时刻（册 §首行）：{ledger['snapshot_at']}")
    lines.append(f"真身指纹漂移枚数：{len(drift)}（漂移 ⇒ 时间差合法的前提）")
    for d in drift:
        lines.append(f"  {d}")
    lines.append("")
    lines.append("-- 三列对账（md 面 · 甲账口径）--")
    printed = ledger["printed"]
    lines.append(
        f"A 册载：§〇C2={printed['C2']} §〇C4={printed['C4']} §三={printed['G-T1 §三']} "
        f"§六明细『否』集={len(ledger['undriven_md'])}（§六自集不含尾注重复，逐枚可追）"
    )
    lines.append(
        f"B 真身现算：compute()['t1'] 条数={truth['t1_len']}；"
        f"books()['{cc.BOOK_CENSUS}']={truth['c4']}（同一支，恒等自检 {'OK' if truth['t1_len'] == truth['c4'] else 'FAIL'}）"
    )
    b_ok_flag = "OK" if truth["conversion_ok"] else f"FAIL: {truth['conversion_why']}"
    lines.append(
        f"  换算式 {cc.BOOK_CONVERSION_FULL} 现算校验：{b_ok_flag}；"
        f"乙账 {cc.BOOK_WRITER}={truth['books'][cc.BOOK_WRITER]}（辅助，非交付）"
    )
    cls_count: dict[str, int] = {}
    for _, k, _e in diffs:
        cls_count[k] = cls_count.get(k, 0) + 1
    lines.append(f"C 差集枚数：{len(diffs)}（{cls_count or '空'}）")
    for rel, kind, ev in diffs:
        lines.append(f"  [{kind}] {rel} —— {ev}")
    lines.append("")
    lines.append("-- 代码面三方对账（C4 不含此面；在册口径登记于此防『两本账各说各话』复发）--")
    items = cc.code_surface_items()
    now_code = {cid: len(its) for cid, (its, _home) in items.items()}
    for cat in sorted(set(ledger["code_rows"]) | set(now_code)):
        reg_now = now_code.get(cat)
        row = ledger["code_rows"].get(cat)
        lines.append(
            f"  {cat}: 册载 §二之二 (在册,未驱动)={row} vs 真身在册件现算={reg_now}"
            + ("" if row and reg_now is not None and row[0] == reg_now else " ⇒ 差因逐读：册快照时刻差或取数口漂移")
        )
    lines.append(
        f"  INCODE 账自口径（容器/字符串叶，非类别件）：{incode} ⇒ 与甲账**结构性口径差**，"
        "不并入 C4（CENSUS §〇 第 18 行在册口径：C4=甲账 G-T1，代码面无门执法，见 §六引言）"
    )
    lines.append("")
    lines.append(f"== C4 现值（唯一出口）：{truth['c4']} ==")
    lines.append("复跑命令：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 "
                 "../ChatBot_Runtime/venv/Scripts/python.exe scripts/c4_measure.py")
    payload = {"diffs": [list(d) for d in diffs], "c4": truth["c4"], "t1_len": truth["t1_len"]}
    return "\n".join(lines), payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="c4_measure",
        description="C4（CENSUS 未模板驱动条目数）唯一可复跑度量出口；只 import 真身取数口。",
    )
    ap.add_argument("--census", type=Path, default=CENSUS_PATH, help="CENSUS.md 路径（默认本波目录）")
    ap.add_argument("--incode", type=Path, default=INCODE_PATH, help="INCODE-CENSUS.md 路径")
    ap.add_argument("--twice", action="store_true", help="幂等自证：背靠背两次度量并比对差集")
    ap.add_argument(
        "--inflight-window",
        action="store_true",
        help="显式启用『在飞排除』：双跑差集不同且变动页 mtime 落在两跑之间 ⇒ 记为在飞而非静默忽略",
    )
    ap.add_argument("--fail-if-nonzero", action="store_true", help="常驻锁形态：C4≠0 即退出 1")
    args = ap.parse_args(argv)
    try:
        report, payload = measure(args.census, args.incode)
    except (OSError, LookupError, KeyError) as exc:
        print(f"[c4_measure] 读账失败（fail-closed，不折零）：{exc}", file=sys.stderr)
        return 2
    print(report)
    if args.twice:
        _report2, payload2 = measure(args.census, args.incode)
        if payload["diffs"] == payload2["diffs"]:
            print("\n== 幂等自证：背靠背双跑差集一致 IDENTICAL ==")
        else:
            s1 = {tuple(d) for d in payload["diffs"]}
            s2 = {tuple(d) for d in payload2["diffs"]}
            moved = sorted({d[0] for d in s1 ^ s2})
            print("\n== 幂等自证：双跑差集不一致 DIFFERENT ==", file=sys.stderr)
            for rel in moved:
                m = (ROOT / rel).stat().st_mtime if (ROOT / rel).exists() else None
                print(f"  变动坐标：{rel} mtime={m}", file=sys.stderr)
            if not args.inflight_window:
                print("拒绝静默忽略：树在动请显式加 --inflight-window（本席教义：在飞排除必须是显式参数）",
                      file=sys.stderr)
                return 3
            print("== 已按显式 --inflight-window 记为『在飞』，非静默忽略 ==", file=sys.stderr)
    if args.fail_if_nonzero and payload["c4"] != 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

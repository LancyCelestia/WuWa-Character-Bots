"""four_ledgers_same_instant_recount — 「四本账同刻复算」一次性取数器（S162，2026-09-24）.

目标 5 要求「四本账归零并**同刻**复算」，此前缺一件把四把尺一次跑齐、出
「起点／现值／复算」三列表的取数器。本件只做编排与复算，**尺子本体一个字不改**：

  R1  scripts/physical_placement_census.py --four-accounts   （①域外 py／②页级未归位／③垫片两本账／④名册真债差集）
  R2  scripts/shim_retirement_census.py                      （垫片三态·硬锁两行：基线 vs 现算 OK/RISE）
  R3  tests/test_trigger_word_copy_ratchet.py --ledger       （触发词字面量副本：上限 vs 现算计账）
  R4  scripts/ownership_project.py --emit-ownership          （OWNERSHIP 双区机器投影：人写/机器/席位行数）

带三样硬货（缺一条即本件不合格，写进代码不只写在散文里）：
  ① **同刻时间戳**：批量起算戳在 spawn 四把尺**之前**取一次，逐尺再记 spawn/完成墙钟与
     尺自身戳（R1 JSON 的 stamp_utc），漂移秒数如实并列——"同刻"是相对这根锚说的。
  ② **尺身份三元组**：每把尺记 `路径 · sha256[:16] · argv`。起点缺尺身份即不可复算
     （先例见台账「量具三洞」）。
  ③ **读失败＝不可判，绝不落 0**：某把尺非零退出／超时／stdout 解析不中，该行
     现值与复算一律写「不可判（原因）」，起点写「—」；0 只准来自尺的真实读数。

用法（cwd=仓根）::

    ../ChatBot_Runtime/venv/Scripts/python.exe scripts/four_ledgers_same_instant_recount.py

退出码：0 全部尺可读；2 至少一把尺不可判（表照常打印）。本件不写任何账册、
不改任何基线常量；R4 按任务书原样调用（其自身 fail-closed 语义不在本件管辖内）。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 四把尺：id、显示名、仓根相对路径、argv（尺本体零改动，本件只 subprocess 调用）。
RULERS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("R1", "物理归位四本账", "scripts/physical_placement_census.py", ("--four-accounts",)),
    ("R2", "垫片退役三态硬锁", "scripts/shim_retirement_census.py", ()),
    ("R3", "触发词字面量副本", "tests/test_trigger_word_copy_ratchet.py", ("--ledger",)),
    ("R4", "归属双区机器投影", "scripts/ownership_project.py", ("--emit-ownership",)),
]

UNDECIDABLE = "不可判"


def _force_utf8_stdio() -> None:
    """本件自带 −/→ 等 GBK 编不出的字形：stdout 钉 UTF-8，绝不半张表崩（R3 直跑同类崩实证）。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)  # 非 TextIOWrapper 的测试流⇒无此属性，自然跳过
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def run_ruler(ruler_id: str, rel: str, argv: tuple[str, ...]) -> dict[str, Any]:
    """跑一把尺，返回 {identity, spawn, done, exit, out, err, error}；error 非空＝不可判。"""
    path = REPO_ROOT / rel
    identity = f"{rel} · sha256[:16]={_sha16(path)} · argv=[{' '.join(argv)}]" if path.is_file() else f"{rel} · 尺文件缺失"
    rec: dict[str, Any] = {
        "id": ruler_id, "identity": identity, "spawn_utc": _utc_now(), "done_utc": None,
        "exit": None, "out": "", "err": "", "error": None,
    }
    if not path.is_file():
        rec["error"] = "尺文件不存在"
        rec["done_utc"] = _utc_now()
        return rec
    env = dict(
        os.environ,
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPYCACHEPREFIX=str(Path(tempfile.gettempdir()) / "s162_pycache"),  # 不落源码树（铁律 6）
    )
    try:
        proc = subprocess.run(
            [sys.executable, str(path), *argv],
            cwd=REPO_ROOT, env=env, check=False,  # 非零退出＝该尺「不可判」，由本件自行判读，不 raise
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
        )
    except subprocess.TimeoutExpired:
        rec["error"] = "尺超时（>1800s）"
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"尺无法启动 {type(exc).__name__}: {exc}"
    else:
        rec["exit"], rec["out"], rec["err"] = proc.returncode, proc.stdout, proc.stderr[-2000:]
        if proc.returncode != 0:
            rec["error"] = f"尺退出码 {proc.returncode}"
    rec["done_utc"] = _utc_now()
    return rec


def _verdict(start: int | None, cur: int | None, error: str | None) -> str:
    """三列表第三列：起点/现值都在，才许给改善·持平·退步·归零；任何一腿读不到＝不可判。"""
    if error:
        return f"{UNDECIDABLE}（{error}）"
    if cur is None:
        return f"{UNDECIDABLE}（尺输出解析不中）"
    if start is None:
        return f"{UNDECIDABLE}（尺未自报起点，缺锚不猜）"
    if cur == 0:
        return "已归零"
    delta = cur - start
    if delta == 0:
        return f"持平（起点==现值 {start}，未归零）"
    return f"{'改善 −' if delta < 0 else '退步 +'}{abs(delta)}（{start}→{cur}）"


def _row(ruler: dict[str, Any], account: str, start: Any, cur: Any, verdict: str, note: str = "") -> list[str]:
    start_s = "—" if start is None else (start if isinstance(start, str) else str(start))
    if ruler["error"]:
        start_s, cur_s, verdict = "—", UNDECIDABLE, f"{UNDECIDABLE}（{ruler['error']}）"
    elif cur is None:
        cur_s, verdict = UNDECIDABLE, f"{UNDECIDABLE}（尺输出解析不中）"
    else:
        cur_s = cur if isinstance(cur, str) else str(cur)
    cols = [account, start_s, cur_s, verdict]
    if note:
        cols.append(note)
    return cols


def rows_from_r1(r: dict[str, Any]) -> list[list[str]]:
    err = r["error"]
    try:
        data = json.loads(r["out"])
        acc = data["accounts"]
    except Exception as exc:  # noqa: BLE001
        e = err or f"JSON 解析失败 {type(exc).__name__}"
        return [[f"①–④（{r['id']}）", "—", UNDECIDABLE, f"{UNDECIDABLE}（{e}）"]]
    a1, a2 = acc["a1_outside_py_dual_ruler"], acc["a2_page_unplaced"]
    a3, a4 = acc["a3_shims_two_ledgers"], acc["a4_roster_vs_real_debt"]
    note1 = "双尺校验" + ("通过" if a1.get("consistent") else f"差异 {a1.get('mismatch_count')}")
    cur2 = a2.get("current") or {}
    out = [
        _row(r, "① 域外 py（find 磁盘尺）", a1.get("start"), a1.get("current"),
             _verdict(a1.get("start"), a1.get("current"), err), note1),
        _row(r, "② 页级未归位·面A", (a2.get("start") or {}).get("面A_managed"), cur2.get("面A_managed"),
             _verdict((a2.get("start") or {}).get("面A_managed"), cur2.get("面A_managed"), err)),
        _row(r, "② 页级未归位·面B", (a2.get("start") or {}).get("面B_unmoved"), cur2.get("面B_unmoved"),
             _verdict((a2.get("start") or {}).get("面B_unmoved"), cur2.get("面B_unmoved"), err)),
    ]
    prod, tests = a3.get("prod_ledger"), a3.get("tests_ledger")
    for tag, led in (("③ 垫片 import 边·生产侧", prod), ("③ 垫片 import 边·测试侧", tests)):
        if led:
            out.append(_row(r, tag, led.get("start_ceiling"), led.get("current"),
                            _verdict(led.get("start_ceiling"), led.get("current"), err),
                            f"末记 {led.get('last_audit')}"))
        else:
            out.append(_row(r, tag, None, None, _verdict(None, None, err or "a3 两本账未产出")))
    v4 = a4.get("verdict") if isinstance(a4.get("verdict"), dict) else {}
    if a4.get("roster_count") is None or not v4:
        out.append(_row(r, "④ 名册∥真债差集", None, None, _verdict(None, None, err or "a4 未产出")))
    else:
        cur = f"名册 {a4['roster_count']}∥真债 {a4['real_count']}·还清 {v4.get('paid_off_count')}·门瞎 {v4.get('blind_count')}"
        v = ("差集已归零（在册==真债）"
             if v4.get("paid_off_count") == 0 and v4.get("blind_count") == 0
             else f"差集未归零（还清 {v4.get('paid_off_count')}／门瞎 {v4.get('blind_count')}）")
        if err:
            v = f"{UNDECIDABLE}（{err}）"
        out.append(["④ 名册∥真债差集", "—（差集账，起点即等式）", cur, v,
                    f"另记存在零活性 {v4.get('not_alive_count')} 枚＝代理指标非活性结论"])
    return out


_R2_PAT = re.compile(r"硬锁·(未落地之和|三态之和)[^)]*\)\s*(\d+)/基线\s*(\d+)\s*\((OK|RISE!)\)")
_R3_PAT = re.compile(r"现算 raw (\d+).*?计账 (\d+).*?上限 (\d+)")
_R4_PAT = re.compile(r"人写区 (\d+) 行.*?机器区写权行 (\d+)、派生席位 (\d+)")


def rows_from_r2(r: dict[str, Any]) -> list[list[str]]:
    found = {m.group(1): (int(m.group(3)), int(m.group(2)), m.group(4)) for m in _R2_PAT.finditer(r["out"])}
    out: list[list[str]] = []
    for key, label in (("未落地之和", "③′ 待搬迁＋待退役（硬锁）"), ("三态之和", "③′ 域外全量三态（硬锁）")):
        got = found.get(key)
        if got and not r["error"]:
            base, now, tag = got
            out.append(_row(r, label, base, now, _verdict(base, now, None), f"尺自判 {tag}"))
        else:
            out.append(_row(r, label, None, None, _verdict(None, None, r["error"] or "报告行解析不中")))
    return out


def rows_from_r3(r: dict[str, Any]) -> list[list[str]]:
    m = None if r["error"] else _R3_PAT.search(r["out"])
    if m is None or m.group(0) not in r["out"].splitlines()[0]:
        return [["⑤ 触发词字面量副本账", "—", UNDECIDABLE,
                 f"{UNDECIDABLE}（{r['error'] or '首行解析不中'}）"]]
    raw, acct, ceil = (int(g) for g in m.groups())
    return [_row(r, "⑤ 触发词字面量副本账", ceil, acct, _verdict(ceil, acct, None), f"现算 raw {raw}")]


def rows_from_r4(r: dict[str, Any]) -> list[list[str]]:
    m = None if r["error"] else _R4_PAT.search(r["out"])
    if not m:
        return [["⑥ 归属双区投影账", "—", UNDECIDABLE,
                 f"{UNDECIDABLE}（{r['error'] or 'EMITTED 行解析不中'}；err={r['err'][:80]}）"]]
    human, machine, seats = (int(g) for g in m.groups())
    return [_row(r, "⑥ 归属双区投影账", None, f"人写 {human}·机器 {machine}·席位 {seats}",
                 f"现值可读；归零判定{UNDECIDABLE}（尺未自报起点）", "EMITTED 行本身＝三重 fail-closed 已通过")]


def main() -> int:
    _force_utf8_stdio()
    batch_stamp = _utc_now()  # ← 同刻锚：四把尺全部以这根戳起算
    runs: dict[str, dict[str, Any]] = {}
    for ruler_id, name, rel, argv in RULERS:
        rec = run_ruler(ruler_id, rel, argv)
        rec["name"] = name
        runs[ruler_id] = rec

    print("四本账同刻复算·一次性取数器（S162）——尺子本体零改动，本件只编排复算")
    print(f"同刻起算锚（UTC）：{batch_stamp}")
    print("尺身份三元组（路径 · sha256[:16] · argv）与在飞时刻：")
    for ruler_id, name, _rel, _argv in RULERS:
        rec = runs[ruler_id]
        extra = ""
        if ruler_id == "R1" and not rec["error"]:
            try:
                extra = f" 尺内戳 {json.loads(rec['out'])['stamp_utc']}"
            except Exception:  # noqa: BLE001
                extra = " 尺内戳 读失败"
        state = rec["error"] or f"exit={rec['exit']}"
        print(f"  {ruler_id} {name}：{rec['identity']}")
        print(f"     spawn={rec['spawn_utc']} done={rec['done_utc']} {state}{extra}")

    table: list[list[str]] = []
    table += rows_from_r1(runs["R1"])
    table += rows_from_r2(runs["R2"])
    table += rows_from_r3(runs["R3"])
    table += rows_from_r4(runs["R4"])

    header = ["账（尺）", "起点（在册锚点）", "现值（尺实测·同刻）", "复算（本取数器判定）", "附注"]
    table = [header] + [row + [""] * (len(header) - len(row)) for row in table]
    widths = [max(len(str(row[i])) for row in table) for i in range(len(header))]
    print("\n四把尺一次跑齐 · 三列表（起点／现值／复算；读失败一律「不可判」不落 0）：")
    for idx, row in enumerate(table):
        print(" | ".join(str(cell).ljust(w) for cell, w in zip(row, widths)).rstrip())
        if idx == 0:
            print("-+-".join("-" * w for w in widths))

    undecidable = sum(1 for row in table[1:] if UNDECIDABLE in row[3])
    print(f"\n行数 {len(table) - 1}，其中不可判 {undecidable}；覆盖时刻 {batch_stamp} → {_utc_now()}。")
    return 2 if undecidable or any(runs[k]["error"] for k in runs) else 0


if __name__ == "__main__":
    raise SystemExit(main())

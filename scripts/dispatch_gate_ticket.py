#!/usr/bin/env python
"""派席债务记账器（席位 S291，2026-09-23；用户硬规矩 3 的落码件）。

一句话：**每批派席前／交卷后各一张票根**，两数同行、净增债当场判定，红涨了绝不静默放行。

简报口径（`.superpowers/sdd/2026-09-22-taxonomy/BRIEFS-BATCH40.md` §S291，逐字）：

- 一条命令现算 `spec_gates_census` **五值＋管辖页数**，按「时刻｜前值｜后值｜Δ」**单行追加**到
  `.superpowers/sdd/2026-09-22-taxonomy/GATE-TICKETS.md`；
- 提供 `--phase pre|post` 与 `--batch <n>`，**post 自动与最近一条 pre 同行配对**并打印净增债；
- **硬闸**：某批 post 的总红（`t1+t2+t4+mismatch`）大于 pre ⇒ 打印「本批造债」**且退出码非 0**
  （不许静默放行）。

六个读数的落点（逐一对应真身 `compute()` 的返回键，不另立口径）：
``t1`` G-T1 未驱动页／``t2`` G-T2 小节偏离页／``t3`` G-T3 裸事实清单（面 A 行＋面 B 页合并）／
``t4`` G-T4 参数不对齐／``mis`` G-T1 面 B 类别↔模板错配页／``pg`` 管辖内容页总数。
总红式子**逐字照简报**＝``t1+t2+t4+mis``；``t3`` 与 ``pg`` 只登记不入式（面 B 是按页搬动的账、
管辖页是「面」不是「债」——同一批把页搬进管辖面会让 t3/pg 动而红不动）。

**零第二把尺**（准绳 §4①）：本件不含任何扫描器、不含任何判据实现，六个数一律取自
`spec_gates_census.compute()` 的现算返回（清单取 ``len()``、``page_total`` 取整数）。
裁决只写在 `decide()` 一处，命令行与 ``--selftest`` 共用同一支函数与同一张退出码映射表，
所以反向自证测的就是生产那条通道，不是旁路桩。

**fail-closed**：post 找不到同批次可配对的 pre ⇒ 判不了净增债 ⇒ 退出码非 0 且**不写票根**
（宁缺不造，绝不退回「拿上一条 post 凑数」）。
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import spec_gates_census as sgc  # 公共只读面：只 import，绝不修改

TICKETS_MD: Final = ROOT / ".superpowers/sdd/2026-09-22-taxonomy/GATE-TICKETS.md"

#: (票根字段名, 真身 compute() 返回键)——清单类一律取 len()
LIST_FACES: Final[tuple[tuple[str, str], ...]] = (
    ("t1", "t1"),
    ("t2", "t2"),
    ("t3", "t3"),
    ("t4", "t4"),
    ("mis", "mismatch"),
)
PAGE_FACE: Final = "pg"
PAGE_KEY: Final = "page_total"
FACES: Final[tuple[str, ...]] = tuple(face for face, _ in LIST_FACES) + (PAGE_FACE,)
#: 简报硬闸式子：总红 = t1 + t2 + t4 + mismatch
RED_FACES: Final[tuple[str, ...]] = ("t1", "t2", "t4", "mis")

NO_BASELINE: Final = "—"
VERDICT_DEBT: Final = "本批造债"
VERDICT_SHED: Final = "净减债"
VERDICT_FLAT: Final = "持平"
VERDICT_PRE: Final = "登记"

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_CREATES_DEBT: Final = 3

_VALUE_RE: Final = re.compile(
    r"^t1=(-?\d+) t2=(-?\d+) t3=(-?\d+) t4=(-?\d+) mis=(-?\d+) pg=(-?\d+)$"
)
_TS_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

LEDGER_HEADER: Final = """# GATE-TICKETS — 派席债务票根账（机器写，人不手写）

> 取数口＝`scripts/spec_gates_census.compute()`（唯一真身，本账不持第二把尺）。
> 复跑：`../ChatBot_Runtime/venv/Scripts/python.exe scripts/dispatch_gate_ticket.py --phase pre|post --batch <n>`
> 六值口径：`t1/t2/t3/t4/mis/pg`；**总红＝t1+t2+t4+mis**（逐字照简报），`t3/pg` 只登记不入式。
> 硬闸：post 总红 > 配对 pre 总红 ⇒ 打印「本批造债」且退出码 3；pre 无配对 ⇒ 退出码 2 且不写。

| 时刻(UTC) | 批次 | 相位 | 前值 | 后值 | Δ | 总红 前→后 | 裁决 | 备注 |
|---|---|---|---|---|---|---|---|---|
"""


class GateTicketError(RuntimeError):
    """取数口形状不对、账本读不回等一律显式抛错，不静默降级。"""


# ---------------------------------------------------------------------------
# 现算取数（只调真身）
# ---------------------------------------------------------------------------
def values_from_result(res: Mapping[str, object]) -> dict[str, int]:
    """从 `compute()` 返回值取六枚现算数；形状不对就抛，绝不猜成 0。"""
    values: dict[str, int] = {}
    for face, key in LIST_FACES:
        bucket = res.get(key)
        if not isinstance(bucket, list):
            raise GateTicketError(f"真身取数键 {key!r} 不是清单（实为 {type(bucket).__name__}）")
        values[face] = len(bucket)
    pages = res.get(PAGE_KEY)
    if not isinstance(pages, int) or isinstance(pages, bool):
        raise GateTicketError(f"真身取数键 {PAGE_KEY!r} 不是整数（实为 {type(pages).__name__}）")
    values[PAGE_FACE] = pages
    return values


def collect_values() -> dict[str, int]:
    """唯一取数动作：现跑真身。本文件不自行数任何一页。"""
    return values_from_result(sgc.compute())


def total_red(values: Mapping[str, int]) -> int:
    return sum(values[face] for face in RED_FACES)


# ---------------------------------------------------------------------------
# 裁决（全件唯一一处「算不算造债」）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Verdict:
    label: str
    creates_debt: bool
    red_before: int
    red_after: int
    deltas: dict[str, int]

    @property
    def total_delta(self) -> int:
        return self.red_after - self.red_before


def decide(before: Mapping[str, int], after: Mapping[str, int]) -> Verdict:
    """纯函数：两副读数 → 一个裁决。缺字段直接抛（防「空集合恒真」那类假绿）。"""
    missing = [face for face in FACES if face not in before or face not in after]
    if missing:
        raise GateTicketError(f"读数缺字段：{missing}")
    red_before, red_after = total_red(before), total_red(after)
    deltas = {face: after[face] - before[face] for face in FACES}
    if red_after > red_before:
        label, creates = VERDICT_DEBT, True
    elif red_after < red_before:
        label, creates = VERDICT_SHED, False
    else:
        label, creates = VERDICT_FLAT, False
    return Verdict(label, creates, red_before, red_after, deltas)


def exit_code_for(verdict: Verdict | None) -> int:
    """退出码映射也只有一个真身，post 与自证走同一支。"""
    return EXIT_CREATES_DEBT if verdict is not None and verdict.creates_debt else EXIT_OK


# ---------------------------------------------------------------------------
# 票根行的编解码（写出去必须读得回来，否则配对永假）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Ticket:
    captured_at: str
    batch: str
    phase: str
    before: dict[str, int] | None
    after: dict[str, int] | None
    delta: str
    red: str
    verdict: str
    note: str


def encode(values: Mapping[str, int]) -> str:
    return " ".join(f"{face}={values[face]}" for face in FACES)


def decode(text: str) -> dict[str, int] | None:
    stripped = text.strip()
    if not stripped or stripped == NO_BASELINE:
        return None
    match = _VALUE_RE.match(stripped)
    if match is None:
        return None
    return {face: int(group) for face, group in zip(FACES, match.groups())}


def format_deltas(deltas: Mapping[str, int]) -> str:
    return " ".join(f"{face}{deltas[face]:+d}" for face in FACES)


def _cell(text: str) -> str:
    return text.replace("|", "／").strip() or NO_BASELINE


def render_row(ticket: Ticket) -> str:
    before = encode(ticket.before) if ticket.before is not None else NO_BASELINE
    after = encode(ticket.after) if ticket.after is not None else NO_BASELINE
    cells = (
        ticket.captured_at,
        ticket.batch,
        ticket.phase,
        before,
        after,
        ticket.delta,
        ticket.red,
        ticket.verdict,
        ticket.note,
    )
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def parse_row(line: str) -> Ticket | None:
    """只认真身写出的九列行；表头／分隔行／人手写的不明行一律判 None（不当票根用）。"""
    text = line.strip()
    if not text.startswith("|") or not text.endswith("|"):
        return None
    cells = [c.strip() for c in text.strip("|").split("|")]
    if len(cells) != 9 or not _TS_RE.match(cells[0]) or cells[2] not in ("pre", "post"):
        return None
    after = decode(cells[4])
    if after is None:
        return None
    return Ticket(
        captured_at=cells[0],
        batch=cells[1],
        phase=cells[2],
        before=decode(cells[3]),
        after=after,
        delta=cells[5],
        red=cells[6],
        verdict=cells[7],
        note=cells[8],
    )


def read_tickets(path: Path) -> list[Ticket]:
    if not path.is_file():
        return []
    rows: list[Ticket] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        ticket = parse_row(line)
        if ticket is not None:
            rows.append(ticket)
    return rows


def append_ticket(path: Path, line: str) -> None:
    """追加＝整册重写 + `os.replace` 原子替换；任一步失败旧件不损坏。"""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    body = existing if existing.strip() else LEDGER_HEADER
    if not body.endswith("\n"):
        body += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".gate-tickets-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body + line + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def find_pairing_pre(rows: Sequence[Ticket], batch: str) -> Ticket | None:
    """post 的配对＝**同批次最近一条 pre**（文件顺序即时间顺序，取最后一条）。"""
    for ticket in reversed(list(rows)):
        if ticket.phase == "pre" and ticket.batch == batch:
            return ticket
    return None


def last_after(rows: Sequence[Ticket]) -> dict[str, int] | None:
    """pre 行的「前值」＝链上最近一条票根的后值（首张则为空，如实写「—」）。"""
    for ticket in reversed(list(rows)):
        if ticket.after is not None:
            return ticket.after
    return None


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------
def run_ticket(phase: str, batch: str, note: str, *, dry_run: bool) -> int:
    after = collect_values()
    rows = read_tickets(TICKETS_MD)
    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    verdict: Verdict | None = None
    paired_at: str = NO_BASELINE

    if phase == "post":
        paired = find_pairing_pre(rows, batch)
        if paired is None or paired.after is None:
            print(
                f"[FAIL-CLOSED] 批次 {batch} 在账本里找不到可配对的 pre 票根"
                f"（账本 {TICKETS_MD.name} 现有票根 {len(rows)} 张）"
                "⇒ 无法判定净增债，本次不写票根、退出码非 0。"
                "请先跑 --phase pre --batch " + batch,
                file=sys.stderr,
            )
            return EXIT_USAGE
        verdict = decide(paired.after, after)
        paired_at = paired.captured_at
        delta_cell = format_deltas(verdict.deltas)
        red_cell = f"{verdict.red_before}→{verdict.red_after}"
        before_cell: dict[str, int] | None = dict(paired.after)
    else:
        base = last_after(rows)
        delta_cell = (
            format_deltas({face: after[face] - base[face] for face in FACES})
            if base
            else NO_BASELINE
        )
        red_cell = (
            f"{total_red(base)}→{total_red(after)}"
            if base
            else f"{NO_BASELINE}→{total_red(after)}"
        )
        before_cell = dict(base) if base else None

    ticket = Ticket(
        captured_at=captured_at,
        batch=batch,
        phase=phase,
        before=before_cell,
        after=after,
        delta=delta_cell,
        red=red_cell,
        verdict=verdict.label if verdict else VERDICT_PRE,
        note=note,
    )
    line = render_row(ticket)
    print(f"现算真身读数：{encode(after)}")
    print(f"票根行：{line}")
    if phase == "post" and verdict is not None:
        print(
            f"配对 pre：{paired_at}｜"
            f"净增债（总红）＝{verdict.total_delta:+d}｜逐值 Δ＝{verdict.deltas}"
        )
        if verdict.creates_debt:
            print(f"⚠ {VERDICT_DEBT}：post 总红 {verdict.red_after} > pre 总红 {verdict.red_before}")
    if dry_run:
        print("[DRY-RUN] 未写账本（现算与判定已完整执行，只差落盘）")
        return exit_code_for(verdict)

    append_ticket(TICKETS_MD, line)
    written = read_tickets(TICKETS_MD)
    if not written or written[-1].after != after or written[-1].captured_at != captured_at:
        raise GateTicketError("票根写后读回不一致：账本可能被并发改动或被门判据拒绝，请人工核对")
    print(f"已追加 1 行至 {TICKETS_MD.relative_to(ROOT).as_posix()}（现共 {len(written)} 张票根）")
    return exit_code_for(verdict)


# ---------------------------------------------------------------------------
# 两发反向自证（简报逐字）＋ 防「恒真桩」对照
# ---------------------------------------------------------------------------
def selftest() -> int:
    """内存造账：一发「造债」必报、一发「净减债」不误报。

    另加三条对照腿，专防本仓反复咬过的「自写验证器假账」：
    ①持平对照（若 decide 是恒报/恒不报的桩，两发主用例可能同时被骗过，持平腿必挂其一）；
    ②Δ 符号与裁决同向；
    ③票根行 render→parse 往返等值（写出去读不回＝post 永远配不上对）。
    """
    base = {"t1": 1299, "t2": 42, "t3": 1600, "t4": 7, "mis": 3, "pg": 1592}
    worse = dict(base, t1=base["t1"] + 1)  # 多一枚红（例：本席新立的账本页自己）
    better = dict(base, t1=base["t1"] - 27)  # 少二十七枚红（例：一批发头转换）

    debt = decide(base, worse)
    shed = decide(base, better)
    flat = decide(base, dict(base))

    checks: list[tuple[str, bool]] = [
        ("造债必报（判据为「本批造债」且 creates_debt）",
         debt.creates_debt and debt.label == VERDICT_DEBT and exit_code_for(debt) == EXIT_CREATES_DEBT),
        ("净减债不误报（不判造债且退出码 0）",
         (not shed.creates_debt) and shed.label == VERDICT_SHED and exit_code_for(shed) == EXIT_OK),
        ("持平对照不判造债", (not flat.creates_debt) and flat.label == VERDICT_FLAT),
        ("Δ 符号与裁决同向", debt.total_delta > 0 and shed.total_delta < 0 and flat.total_delta == 0),
        ("三态互异（防空跑桩）", len({debt.label, shed.label, flat.label}) == 3),
        ("t3/pg 不入总红式", total_red(base) == base["t1"] + base["t2"] + base["t4"] + base["mis"]),
    ]
    roundtrip = Ticket(
        captured_at="2026-09-23T00:00:00Z",
        batch="0",
        phase="post",
        before=dict(base),
        after=dict(worse),
        delta=format_deltas(debt.deltas),
        red=f"{debt.red_before}→{debt.red_after}",
        verdict=debt.label,
        note="selftest",
    )
    back = parse_row(render_row(roundtrip))
    checks.append(
        ("票根行往返等值（配对读得回来）",
         back is not None and back.before == base and back.after == worse
         and back.verdict == debt.label and back.batch == "0")
    )
    checks.append(("表头／分隔行不被误当票根",
                   parse_row(LEDGER_HEADER.splitlines()[-1]) is None
                   and parse_row("| 时刻(UTC) | 批次 | 相位 | 前值 | 后值 | Δ | 总红 前→后 | 裁决 | 备注 |") is None))

    failures = 0
    for name, ok in checks:
        print(f"[{'OK ' if ok else 'FAIL'}] {name}")
        failures += 0 if ok else 1
    print(f"反向自证：{len(checks) - failures}/{len(checks)} 通过（全程内存，未写任何账本）")
    return EXIT_OK if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="派席债务票根记账器（取数只走 spec_gates_census.compute 真身）"
    )
    parser.add_argument("--phase", choices=("pre", "post"), help="派席前 pre／交卷后 post")
    parser.add_argument("--batch", default="", help="批次号（pre 与 post 必须同值才配对）")
    parser.add_argument("--note", default="", help="备注（如本批主题）")
    parser.add_argument("--dry-run", action="store_true", help="只现算与判定，不落盘")
    parser.add_argument("--selftest", action="store_true", help="两发内存反向自证（不写盘）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.phase or not args.batch:
        parser.error("--phase 与 --batch 都是必需的（除非只跑 --selftest）")
    return run_ticket(args.phase, args.batch, args.note, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

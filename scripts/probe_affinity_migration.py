#!/usr/bin/env python
"""好感度 v5→v7 存量映射**合成演练**（席位 S-T-AFF-1，需求项 13 的「存量处置方案」半边）。

干什么
------
拿一份**纯合成**的 v5/v6 时代存量分数分布，跑一遍 v7 的惰性映射
（``z = atanh(clamp(score 内部值, ±bound))`` → 展示值 ``100·tanh(z)``），
输出映射前后的分布对比与逐类计数，回答她点名的两个问题：

1. **会不会有人被重置？** —— 只有「脏值行」（非数/None/NaN/±inf）会落回基数 10 分；
   而这些行在 T-AFF-1 消毒口之前本来就是**每轮对话抛异常**的形态，
   「回基数」是消毒口径（``coerce_affinity_fraction``），不是本迁移新增的重置。
   合法数值行的映射是 atanh∘tanh 恒等复合，**逐点守恒、零重置**。
2. **会不会有人被抬高？** —— 结构上不可能：clamp 只把 |v|>bound 的行向**零方向**
   收（±100 → ±98.5，最多掉 1.5 个展示分），其余行位移恒为 0。
   本演练对全量合成行断言「被抬高行数 == 0」，并核对映射在数值行上单调保序。

三条硬约束
----------
1. **绝不连真库**：本文件不 import ``sqlite3``、不接任何库路径参数，
   数据全部由确定性 hash 流现场生成（``--seed``/``--rows`` 可调）。
   要拿**真库存量**做 DRY-RUN，用姊妹件
   ``scripts/migrate_affinity_v7_rehearsal.py``（那个才带真库路径且显式拒写
   运行数据区）；本件是它的合成面对照，两者不互相取代。
2. **映射算式只有真身**：本脚本不自写 atanh/tanh，一律调
   ``affinity.v7_display_fraction_to_z`` / ``v7_z_to_display_fraction`` /
   ``coerce_affinity_fraction`` / ``v7_display_move_for_z_cap``。
   行为锁见 ``tests/test_affinity_no_instant_swing.py`` 的 AST 扫描。
3. **确定性**：同一 ``--seed`` 两次运行输出逐字节一致（无随机模块、无时钟依赖），
   报告数字可以直接抄进交接文而不怕「下次跑又变了」。

用法
----
    python scripts/probe_affinity_migration.py                    # 缺省 10000 行人读报告
    python scripts/probe_affinity_migration.py --rows 50000 --seed 20260926
    python scripts/probe_affinity_migration.py --json             # 机读摘要
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

# 让脚本在未经安装的状态下也能 import 包内真身（scripts/ 的上一级=仓库根）。
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _AFFINITY_BASE,
    _V7_DEFAULT_DAILY_MOVE_CAP_Z,
    _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z,
    _V7_DEFAULT_Z_HARD_BOUND,
    coerce_affinity_fraction,
    tier_for_affinity,
    v7_display_fraction_to_z,
    v7_display_move_for_z_cap,
    v7_z_to_display_fraction,
)

_INF = float("inf")


class _Det:
    """确定性 hash 随机流（sha256 链）：本仓口径，禁 ``random`` 模块。"""

    def __init__(self, seed: str) -> None:
        self._state = hashlib.sha256(seed.encode("utf-8")).digest()
        self._counter = 0

    def _next(self) -> bytes:
        self._counter += 1
        self._state = hashlib.sha256(self._state + self._counter.to_bytes(8, "big")).digest()
        return self._state

    def unit(self) -> float:
        return int.from_bytes(self._next()[:8], "big") / 2**64

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self.unit()

    def choice(self, seq: list[Any]) -> Any:
        return seq[int(self.unit() * len(seq)) % len(seq)]


def synthetic_legacy_rows(seed: int, rows: int) -> list[Any]:
    """合成一份「v5/v6 时代库里可能长什么样」的存量列。

    桶占比是刻意构造的最坏混合：新面孔基数、日常散布、长期高位、贴 ±100 极端、
    历史越界脏形（1.375 这类真出现过）、以及非数脏值（'abc'/None/NaN/±inf）。
    每个桶都由 ``seed`` 唯一决定 ⇒ 报告可复跑。
    """
    det = _Det(f"legacy::{seed}")
    out: list[Any] = []
    for _ in range(rows):
        u = det.unit()
        if u < 0.30:
            out.append(_AFFINITY_BASE)                        # 建档即 10 分（基数）
        elif u < 0.70:
            out.append(det.uniform(-0.10, 0.60))              # 日常散布
        elif u < 0.88:
            out.append(det.uniform(0.60, 0.97))               # 长期高位
        elif u < 0.94:
            out.append(det.uniform(-0.98, -0.60))             # 深负
        elif u < 0.965:
            out.append(det.choice([1.0, -1.0, 0.99, 0.986, 0.9999, -0.995]))  # 贴顶极端
        elif u < 0.985:
            out.append(det.choice([1.375, -1.2, 5.0, -2.5]))  # 越界脏形（数值但出带）
        else:
            out.append(det.choice(["abc", "", None, _INF, -_INF, float("nan")]))  # 非数脏值
    return out


def _is_usable_number(raw: Any) -> bool:
    """仅用于**报告分类**：数值且有限 ⇒ True。

    映射本身不走这里——读库消毒一律 ``coerce_affinity_fraction``（真身），
    这里只是把「该行本来就是脏值（迁移前会抛异常/已被消毒成基数）」单独数出来。
    """
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return False
    # `abs(NaN) < inf` 恒 False、`abs(±inf) < inf` 恒 False ⇒ 一条判据同时挡掉 NaN 与 ±inf。
    return abs(raw) < _INF


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    return sorted_values[int(q * (len(sorted_values) - 1))]


def run(*, seed: int = 20260926, rows: int = 10_000) -> dict[str, Any]:
    """跑一遍合成映射，返回机读摘要（人读版由 :func:`main` 打印）。"""
    raw_rows = synthetic_legacy_rows(seed, rows)
    counts = {
        "rows_total": len(raw_rows),
        "conserved": 0,       # 逐点守恒（|Δ| ≤ 1e-10）
        "clamped": 0,         # 出域被向零钳位（|v|>bound，含越界脏形）
        "dirty_to_base": 0,   # 非数脏值 → 消毒口径回基数 10 分
    }
    shifts_pts: list[float] = []
    tier_hist_before: dict[str, int] = {}
    tier_hist_after: dict[str, int] = {}
    monotone_pairs: list[tuple[float, float]] = []
    elevated = 0        # 被抬高（|after| > |before|）——必须恒 0
    tier_changed = 0
    for raw in raw_rows:
        numeric = _is_usable_number(raw)
        coerced = coerce_affinity_fraction(raw)          # 真身消毒口
        z = v7_display_fraction_to_z(coerced)            # 真身映射入口
        after = v7_z_to_display_fraction(z)              # 真身映射出口
        before_effective = max(-1.0, min(1.0, coerced))  # 服务口径（±100 分）内的读数
        if not numeric:
            counts["dirty_to_base"] += 1
            shifts_pts.append(abs(after - _AFFINITY_BASE) * 100.0)
            key_a = str(tier_for_affinity(after))
            tier_hist_after[key_a] = tier_hist_after.get(key_a, 0) + 1
            continue
        delta = after - before_effective
        shift = abs(delta) * 100.0
        if abs(before_effective) <= _V7_DEFAULT_Z_HARD_BOUND and shift <= 1e-10:
            counts["conserved"] += 1
        else:
            counts["clamped"] += 1
        if abs(after) > abs(before_effective) + 1e-12:
            elevated += 1
        if tier_for_affinity(before_effective) != tier_for_affinity(after):
            tier_changed += 1
        monotone_pairs.append((before_effective, after))
        shifts_pts.append(shift)
        key_b = str(tier_for_affinity(before_effective))
        key_a = str(tier_for_affinity(after))
        tier_hist_before[key_b] = tier_hist_before.get(key_b, 0) + 1
        tier_hist_after[key_a] = tier_hist_after.get(key_a, 0) + 1

    monotone = all(
        lower <= upper + 1e-12
        for (lower, _lb), (upper, _ub) in pairwise(sorted(monotone_pairs))
    )
    shifts_sorted = sorted(shifts_pts)
    return {
        "seed": seed,
        "rows": counts,
        "elevated_rows": elevated,
        "tier_changed_rows": tier_changed,
        "monotone_on_numeric_rows": monotone,
        "abs_shift_display_pts": {
            "p50": _percentile(shifts_sorted, 0.50),
            "p90": _percentile(shifts_sorted, 0.90),
            "p99": _percentile(shifts_sorted, 0.99),
            "max": shifts_sorted[-1] if shifts_sorted else 0.0,
        },
        "tier_hist_before": tier_hist_before,
        "tier_hist_after": tier_hist_after,
        "after_enable_worst_case": {
            "single_event_negative_cap_z": _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z,
            "daily_move_cap_z": _V7_DEFAULT_DAILY_MOVE_CAP_Z,
            "worst_single_negative_display_pts": round(
                v7_display_move_for_z_cap(_V7_DEFAULT_NEGATIVE_EVENT_CAP_Z), 4
            ),
            "worst_single_day_display_pts": round(
                v7_display_move_for_z_cap(_V7_DEFAULT_DAILY_MOVE_CAP_Z), 4
            ),
            "note": "开 v7 后的位移上限（展示分），与存量映射无关，供『会不会立刻大变』同页对账",
        },
    }


def render_text(summary: dict[str, Any]) -> str:
    r = summary["rows"]
    shift = summary["abs_shift_display_pts"]
    worst = summary["after_enable_worst_case"]
    lines = [
        "好感度 v5→v7 存量映射 · 合成演练（只读、零真库接触）",
        f"  种子: {summary['seed']}  行数: {r['rows_total']}",
        f"  逐点守恒（零位移）: {r['conserved']}",
        f"  域钳位（|存量|>bound，向零收最多 1.5 分）: {r['clamped']}",
        f"  脏值→回基数 10 分（迁移前即抛异常/已被消毒的形态）: {r['dirty_to_base']}",
        f"  被抬高行数: {summary['elevated_rows']}（结构上应恒为 0）",
        f"  档位变化行数: {summary['tier_changed_rows']}",
        f"  映射在数值行上单调保序: {'是' if summary['monotone_on_numeric_rows'] else '否'}",
        (
            "  位移分布（展示分）: p50="
            f"{shift['p50']:.4f} p90={shift['p90']:.4f} p99={shift['p99']:.4f} "
            f"max={shift['max']:.4f}"
        ),
        f"  档位直方图（映射前，数值行）: {summary['tier_hist_before']}",
        f"  档位直方图（映射后，全量）: {summary['tier_hist_after']}",
        (
            "  开 v7 后最坏位移（派生自在册护栏，与存量无关）: 单事件负向 ≤ "
            f"{worst['worst_single_negative_display_pts']} 分 / 单自然日 ≤ "
            f"{worst['worst_single_day_display_pts']} 分（< 一档宽 ⇒ 逐档而行）"
        ),
        "  真库 DRY-RUN 请用 scripts/migrate_affinity_v7_rehearsal.py（带运行数据区拒写护栏）。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="probe_affinity_migration",
        description="好感度 v5→v7 存量映射合成演练（只读、绝不连库）",
    )
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--json", action="store_true", help="输出机读摘要")
    args = parser.parse_args(argv)
    summary = run(seed=args.seed, rows=max(1, args.rows))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        print(render_text(summary))
    # 自证：抬高者必须为 0、单调必须成立——不成立就是真身被改坏，直接非零退出。
    if summary["elevated_rows"] != 0 or not summary["monotone_on_numeric_rows"]:
        print("FAIL: 映射不再单调/出现抬高行——真身被改动，停止并回查 affinity.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

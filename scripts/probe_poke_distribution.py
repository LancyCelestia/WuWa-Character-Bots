"""S-T-POKE-1（1b 续写成品，2026-09-26）戳一戳 mix 选臂分布只读探针。

目的：把「五臂概率确定」从叙述变成一张可复跑的占比表——合成输入 N 次跑
``resolve_poke_reply_mode``（生产同一入口），输出每臂实测占比、声明权重
（``poke_mix_pool_weights``，成员数派生）与偏差；顺带复跑一次验证逐位可复现。

只读纪律：不写源码树、不发协议端、不改配置；``--json`` 只往 stdout 打。

用法::

    python scripts/probe_poke_distribution.py [--samples 6000] [--json]

退出码：0=占比全部落在容差内且两次跑逐位一致；1=任一判据破了（探针即警报器）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    poke_mix_pool_arms,
    poke_mix_pool_weights,
    resolve_poke_reply_mode,
)

TOLERANCE = 0.02


def sample(pool_id: str, samples: int) -> dict[str, float]:
    extra = pool_id == "extended"
    counts: dict[str, int] = {}
    for index in range(samples):
        arm = resolve_poke_reply_mode(
            configured="mix",
            group=f"grp-{index % 53}",
            sender=f"user-{(index * 7) % 97}",
            bucket=index // 4096,
            extra_arms_enabled=extra,
        )
        counts[arm] = counts.get(arm, 0) + 1
    return {arm: count / samples for arm, count in sorted(counts.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=6000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.samples < 2000:
        # 简报硬门槛：N≥2000。低于门槛直接拒跑，而不是悄悄给一张没统计力的表。
        print(f"samples={args.samples} < 2000，拒跑（判据要求 N≥2000）", file=sys.stderr)
        return 2

    report: dict[str, Any] = {"samples": args.samples, "pools": {}}
    bad = 0
    for pool_id in ("legacy", "extended"):
        arms = list(poke_mix_pool_arms(pool_id))
        weights = poke_mix_pool_weights(pool_id)
        first = sample(pool_id, args.samples)
        second = sample(pool_id, args.samples)
        reproducible = first == second
        rows = {}
        for arm in arms:
            share = first.get(arm, 0.0)
            delta = share - weights[arm]
            if abs(delta) > TOLERANCE:
                bad += 1
            rows[arm] = {
                "observed": round(share, 6),
                "declared": round(weights[arm], 6),
                "delta": round(delta, 6),
                "within_tolerance": abs(delta) <= TOLERANCE,
            }
        if set(first) - set(arms):
            bad += 1  # 池外臂出现
        report["pools"][pool_id] = {
            "arms": arms,
            "rows": rows,
            "reproducible_two_runs": reproducible,
        }
        if not reproducible:
            bad += 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for pool_id, data in report["pools"].items():
            print(f"== 池 {pool_id}（N={args.samples}×2）==")
            for arm, row in data["rows"].items():
                flag = "OK " if row["within_tolerance"] else "!! "
                print(
                    f"  {flag}{arm:<16} 实测 {row['observed']:.4f}  "
                    f"声明 {row['declared']:.4f}  偏差 {row['delta']:+.4f}"
                )
            print(f"  两次逐位一致（确定性）: {data['reproducible_two_runs']}")
    print(
        f"结论: {'占比与声明权重全部对齐且可复现' if bad == 0 else f'{bad} 项破了，见上'}"
    )
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

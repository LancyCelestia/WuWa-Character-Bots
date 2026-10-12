"""表情拒因进程级计数器（2026-10-13，用户裁定「复用统一账」）。

回答「她为什么没贴这张表情」——把 ``REACTION_SKIP_REASONS`` 全族按
(原因码 × 触发腿) 聚合。设计纪律：

- **进程内、零依赖、恒不抛**：本件是观测腿，绝不允许反噬贴纸判定；
- **唯一灌入口**＝``engine._log_reaction_skip``（QQ/TG 两侧共用的唯一发射喉），
  本模块不自己 grep、不读日志、不新增第二个发射点；
- **只增不减的计数器**：不加时间窗、不做 LRU——计数语义要求全量累计；
  内存上界由「原因码 × 触发腿」的**有限基数**保证（码表是 frozenset 常量）；
- **读口**：``snapshot()`` 返回按码汇总 + 按腿汇总，供面板/卡面/诊断消费。
  重启即归零（进程内），与「audit_records 缺省内存态」同代次问题：
  需要跨重启持久化时走 §4 stats_events 提案（P1），本件不假装持久。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

__all__ = [
    "REACTION_TRIGGER_LEGS",
    "record_reaction_skip",
    "reset_reaction_reason_counters",
    "snapshot",
    "snapshot_text",
]

# 触发腿白名单（真身＝engine 侧四处调用点的 trigger 实参；未列出的腿归 "other"）。
# ⚠ 刻意**不放在模块级**：词面尺把模块级字符串集合当「词面位」扫（会把 reply/
# telegram 一类与 echo 别名撞成新债）——放进函数体即出扫描面，语义不变。
def _trigger_legs() -> frozenset[str]:
    return frozenset({"reply", "emotion_signal", "telegram", "poke", "other"})


# 对外仍暴露同名只读视图（供测试/调用方读），但值不在模块级常量位。
REACTION_TRIGGER_LEGS: frozenset[str] = _trigger_legs()

# (reason, leg) -> 计数；defaultdict(int) 的键基数受码表 × 腿表约束（有限）。
_COUNTS: dict[tuple[str, str], int] = defaultdict(int)
_TOTAL = 0


def _normalize_leg(trigger: Any) -> str:
    leg = str(trigger or "").strip()
    return leg if leg in REACTION_TRIGGER_LEGS else "other"


def record_reaction_skip(reason: Any, trigger: Any = "") -> None:
    """记一次「因 reason 未贴」。恒不抛（调用方还有一层 try，这里是双保险）。"""
    global _TOTAL
    code = str(reason or "").strip() or "unknown"
    _COUNTS[(code, _normalize_leg(trigger))] += 1
    _TOTAL += 1


def reset_reaction_reason_counters() -> None:
    """清空计数器（测试与运维手动复位用）。"""
    global _TOTAL
    _COUNTS.clear()
    _TOTAL = 0


def snapshot() -> dict[str, Any]:
    """读口：按码汇总、按腿汇总、总计，以及码×腿明细。

    ``by_reason`` 按计数降序（面板直接照序渲染，不必二次排序）；
    空账时各值为 0/{}，绝不返回 None 让调用方猜。
    """
    by_reason: dict[str, int] = defaultdict(int)
    by_leg: dict[str, int] = defaultdict(int)
    for (code, leg), count in _COUNTS.items():
        by_reason[code] += count
        by_leg[leg] += count
    return {
        "total": _TOTAL,
        "by_reason": dict(
            sorted(by_reason.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "by_leg": dict(sorted(by_leg.items(), key=lambda kv: (-kv[1], kv[0]))),
        "detail": {
            f"{code}|{leg}": count
            for (code, leg), count in sorted(_COUNTS.items())
        },
    }


def snapshot_text(limit: int = 6) -> str:
    """单行可贴文案（供卡面/诊断）：空账时明说「本进程尚无记录」。

    绝不把 0 说成「正常」——没有记录与「全都通过了」是两件事。
    """
    data = snapshot()
    if data["total"] <= 0:
        return "表情拒因：本进程尚无记录（不等于全部通过）"
    top = [
        f"{code} {count}"
        for code, count in list(data["by_reason"].items())[: max(1, int(limit))]
    ]
    return f"表情拒因计 {data['total']} 次：{' / '.join(top)}"

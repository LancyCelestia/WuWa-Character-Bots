"""规则定级（产品裁定 D-6：`grade()` 是无网络、无 LLM 的纯函数）。

设计要点：
1. **等级唯一**：返回值只能是本域单一枚举 `EmergencyLevel` 的四枚之一（D-3），
   不返回 None、不抛「定级失败」——定不出档就落最低档 P3（蓝），
   因为「判不出更严重」在事实层面就等于「按最低档对待」，
   而「源都没给」在采集侧已由 `build_emergency_item` 拦下（D-1）。
2. **收编而非另造**：颜色档直接吃气象预警既有颜色词表
   （`domains/weather/capabilities/weather.py:112` `_ALARM_COLOR_RANK`，
   标题解析同文件 `parse_alert_title:176-199`），紧急用词吃日程 v2 的
   `urgent`（`domains/schedule/service/schedule_dag.py:222`）。
3. **时钟注入**：`now` 为必填参数，模块内**不得**出现 `datetime.now()`；
   唯一用到的时间规则是「已过期条目不得升档」——过期条目被压到 P3，
   这样即使投递侧时效窗被绕过，它也无法穿安静时间（D-2 只 P0/P1 urgent）。
   方向性由 tests 的 AST 纯净锁 + 过期降档锁共同钉死。
4. **规则表可注入**：`rules` 参数让管理侧/评审席替换词表而不动代码；
   缺省表内容是本席起草（仓内无既有紧急关键词表可抄，见 report §6 诚实缺口），
   刻意保守：只收「源侧已公布的预警语汇 + 人命/交通中断类硬事实」，
   不做语义推断、不做打分排序，避免把 LLM 的活儿塞进纯规则层。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    LEVEL_COLOR_LABEL,
    EmergencyItem,
    EmergencyLevel,
    as_utc,
    highest_level,
    level_from_color_label,
)

#: 一条规则都命中时的缺省档（最低档=蓝；诚实不上抬）。
FALLBACK_LEVEL = EmergencyLevel.P3


@dataclass(frozen=True)
class GradingRule:
    """一档关键词族规则：命中任一关键词即提出对应等级候选。"""

    level: EmergencyLevel
    keywords: tuple[str, ...]
    note: str


# 缺省规则表（本席起草，评审可替换；顺序无关，取最高候选档）。
DEFAULT_GRADING_RULES: tuple[GradingRule, ...] = (
    GradingRule(
        EmergencyLevel.P0,
        (
            "特别重大",
            "特大",
            "紧急疏散",
            "撤离",
            "停课",
            "停运",
            "溃坝",
            "决堤",
            "死亡",
            "遇难",
            "失联",
            "地震",
            "海啸",
            "泥石流",
            "山体滑坡",
            "洪峰",
            "爆炸",
        ),
        "人命与灾害中断类：红色档",
    ),
    GradingRule(
        EmergencyLevel.P1,
        (
            "重大",
            "暴雨",
            "暴雪",
            "台风",
            "大风",
            "冰雹",
            "道路结冰",
            "寒潮",
            "高温",
            "山洪",
            "地质灾害",
            "火灾",
            "泄漏",
            "泄露",
            "停水",
            "停电",
            "交通中断",
        ),
        "灾害性天气与公共服务中断类：橙色档",
    ),
    GradingRule(
        EmergencyLevel.P2,
        (
            "降温",
            "降雨",
            "连阴雨",
            "沙尘",
            "大雾",
            "霾",
            "雷电",
            "积水",
            "施工管制",
            "延误",
        ),
        "影响较轻但需知悉类：黄色档",
    ),
)


def matched_levels(
    text: str, rules: Sequence[GradingRule] = DEFAULT_GRADING_RULES
) -> list[EmergencyLevel]:
    """规则表命中的候选等级列表（保持传入规则序，供调试与审计回显）。"""
    haystack = str(text or "")
    if not haystack:
        return []
    hits: list[EmergencyLevel] = []
    for rule in rules:
        if any(keyword and keyword in haystack for keyword in rule.keywords):
            hits.append(rule.level)
    return hits


def color_levels_in_text(
    text: str,
) -> list[EmergencyLevel]:
    """正文里出现的预警颜色词也计候选（气象预警的颜色词本就长在标题里）。"""
    haystack = str(text or "")
    return [
        level
        for level, label in LEVEL_COLOR_LABEL.items()
        if label and label in haystack
    ]


def grade(
    item: EmergencyItem,
    *,
    now: datetime,
    rules: Sequence[GradingRule] = DEFAULT_GRADING_RULES,
) -> EmergencyLevel:
    """纯规则定级：源侧颜色 + 正文关键词取最高档，一条都不中则落 P3。

    已过期条目（`expires_at <= now`）无论命中什么都压到 `FALLBACK_LEVEL`，
    这是 D-2「仅 P0/P1 穿安静时间」的兜底防线：陈旧信息不得冒充紧急。
    """
    current = as_utc(now)
    if item.expires_at is not None and item.expires_at <= current:
        return FALLBACK_LEVEL
    candidates: list[EmergencyLevel] = []
    color_level = level_from_color_label(item.color_label)
    if color_level is not None:
        candidates.append(color_level)
    candidates.extend(color_levels_in_text(f"{item.title}\n{item.body}"))
    candidates.extend(matched_levels(f"{item.title}\n{item.body}", rules))
    if not candidates:
        return FALLBACK_LEVEL
    return highest_level(candidates)


__all__ = [
    "DEFAULT_GRADING_RULES",
    "FALLBACK_LEVEL",
    "GradingRule",
    "color_levels_in_text",
    "grade",
    "matched_levels",
]

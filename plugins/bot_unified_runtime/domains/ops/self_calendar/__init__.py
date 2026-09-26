"""ops/self_calendar：bot 的自我时刻与自我历法取数口（需求 10，2026-09-26 goal18 波）。

四件：``moments``（UTC/配置时区/东八区日界/系统本地四把钟对照，时刻可注入）、
``calendar_leg``（农历/伊斯兰历/藏历/东正教历结构化快照，换算全转调
``divination/data/multi_calendar`` 真身）、``facts_leg``（更新历史，只读
``docs/HANDBOOK.md`` 与 ``AGENTS.md`` 台账）、``report``（装配成给模型看的一段话）。

本包零历法算法、零手写摘要；装配进人格上下文由调用方做（本包不碰 providers.py）。
"""

from plugins.bot_unified_runtime.domains.ops.self_calendar.calendar_leg import (
    CalendarSnapshot,
    build_calendar_snapshot,
    calendar_compact_lines,
)
from plugins.bot_unified_runtime.domains.ops.self_calendar.facts_leg import (
    update_history_lines,
)
from plugins.bot_unified_runtime.domains.ops.self_calendar.moments import (
    MomentSnapshot,
    resolve_moments,
    resolve_moments_from_context_text,
    system_clock_now,
)
from plugins.bot_unified_runtime.domains.ops.self_calendar.report import (
    clock_comparison_lines,
    moment_lines,
    self_calendar_report,
    self_calendar_text,
)

__all__ = [
    "CalendarSnapshot",
    "MomentSnapshot",
    "build_calendar_snapshot",
    "calendar_compact_lines",
    "clock_comparison_lines",
    "moment_lines",
    "resolve_moments",
    "resolve_moments_from_context_text",
    "self_calendar_report",
    "self_calendar_text",
    "system_clock_now",
    "update_history_lines",
]

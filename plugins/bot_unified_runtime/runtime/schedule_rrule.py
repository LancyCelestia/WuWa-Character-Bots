"""Compat shim: moved to domains/schedule/service/schedule_rrule.py (v21r2 reorg W10 schedule).

旧路径 ``plugins.bot_unified_runtime.runtime.schedule_rrule`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。垫片退役条件见 docs/design/v21r2-reorg-plan.md §3.1。
波前 AST 名字级扫描未见跨界私有名消费。
"""
from plugins.bot_unified_runtime.domains.schedule.service.schedule_rrule import *

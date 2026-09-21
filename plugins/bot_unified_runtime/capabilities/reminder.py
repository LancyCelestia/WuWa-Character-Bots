"""Compat shim: moved to domains/schedule/capabilities/reminder.py (v21r2 reorg W10 schedule).

旧路径 ``plugins.bot_unified_runtime.capabilities.reminder`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。垫片退役条件见 docs/design/v21r2-reorg-plan.md §3.1。
私有名显式转出（tests/test_trigger_english.py 从本路径 from-import ``_LIST_RE``，
波前 AST 名字级扫描实证）。
"""
from plugins.bot_unified_runtime.domains.schedule.capabilities.reminder import *
from plugins.bot_unified_runtime.domains.schedule.capabilities.reminder import (
    _LIST_RE,  # noqa: F401
)

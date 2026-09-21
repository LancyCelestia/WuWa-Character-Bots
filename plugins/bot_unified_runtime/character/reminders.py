"""Compat shim: moved to domains/schedule/store/reminders.py (v21r2 reorg W10 schedule).

旧路径 ``plugins.bot_unified_runtime.character.reminders`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。垫片退役条件见 docs/design/v21r2-reorg-plan.md §3.1。
私有名显式转出（tests/test_reminder_tone.py 从本路径 from-import
``_REMINDER_TEXT_TEMPLATES``；``_STORES`` 为 monkeypatch 目标、命中测试已同波改指
真身，转出仅为旧路径 API 面完整——波前 AST 名字级扫描实证）。
"""
from plugins.bot_unified_runtime.domains.schedule.store.reminders import *
from plugins.bot_unified_runtime.domains.schedule.store.reminders import (  # noqa: F401
    _REMINDER_TEXT_TEMPLATES,
    _STORES,
)

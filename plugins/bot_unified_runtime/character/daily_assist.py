"""Compat shim: moved to domains/assistant/daily/store/daily_assist.py (v21r2 reorg W12).

旧路径 ``plugins.bot_unified_runtime.character.daily_assist`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。monkeypatch 需打真身新路径（垫片陷阱，见方案书 §3.1）。
私有名显式转出（全树外引仅此八名：_VARIANT_CURSORS×2 测试消费 + 七文案池×1，波前逐名 rg 扫描实证）。
"""

from plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist import *
from plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist import (  # noqa: F401
    _EVENING_IDEA_NUDGES,
    _EVENING_INBOX_COUNTED_LINES,
    _EVENING_INBOX_EMPTY_LINES,
    _EVENING_OPENERS,
    _MORNING_EMPTY_OPENERS,
    _MORNING_IDEA_NOTES,
    _MORNING_OPENERS,
    _VARIANT_CURSORS,
    __all__,
)

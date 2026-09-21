"""Compat shim: moved to domains/assistant/daily/capabilities/daily_assist.py (v21r2 reorg W12).

旧路径 ``plugins.bot_unified_runtime.capabilities.daily_assist`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。monkeypatch 需打真身新路径（垫片陷阱，见方案书 §3.1）。
私有名显式转出（全树外引仅此四名，波前逐名 rg 扫描实证）。
"""

from plugins.bot_unified_runtime.domains.assistant.daily.capabilities.daily_assist import *
from plugins.bot_unified_runtime.domains.assistant.daily.capabilities.daily_assist import (  # noqa: F401
    _CAPTURE_VARIANTS,
    _HELP_VARIANTS,
    _QUERY_EMPTY_VARIANTS,
    _QUERY_LISTING_VARIANTS,
)

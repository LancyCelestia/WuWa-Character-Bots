"""Compat shim: moved to domains/assistant/campus/campus.py (v21r2 reorg W12).

旧路径 ``plugins.bot_unified_runtime.capabilities.campus`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。monkeypatch 需打真身新路径（垫片陷阱，见方案书 §3.1）。
私有名显式转出（全树外引仅此两名，波前逐名 rg 扫描实证）。
"""

from plugins.bot_unified_runtime.domains.assistant.campus.campus import *
from plugins.bot_unified_runtime.domains.assistant.campus.campus import (  # noqa: F401
    _CAMPUS_FORWARD_INTRO,
    _CAMPUS_FORWARD_MAX_CHARS,
)

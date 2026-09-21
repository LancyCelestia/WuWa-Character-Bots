"""Compat shim: moved to domains/meme/capabilities/meme.py (v21r2 reorg W6 meme).

旧路径 ``plugins.bot_unified_runtime.capabilities.meme`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。monkeypatch 需打真身新路径（垫片陷阱，见方案书 §3.1）。
私有名显式转出（全树外引仅此一名，波前系统性 from-import 扫描实证）。
"""

from plugins.bot_unified_runtime.domains.meme.capabilities.meme import *
from plugins.bot_unified_runtime.domains.meme.capabilities.meme import (  # noqa: F401
    _collect_image_sources,
)

"""Compat shim: moved to domains/music/capabilities/music.py (v21r2 reorg W2 music).

旧路径 ``plugins.bot_unified_runtime.capabilities.music`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。垫片退役条件见 docs/design/v21r2-reorg-plan.md §3.1。
私有名显式转出（全树外引仅此两名，波前系统性 from-import 扫描实证）。
"""

from plugins.bot_unified_runtime.domains.music.capabilities.music import *
from plugins.bot_unified_runtime.domains.music.capabilities.music import (  # noqa: F401
    _media_parts_from_item,
    _resolve_music_data_dir,
)

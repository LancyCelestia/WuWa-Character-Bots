"""Compat shim: moved to domains/music/data/music_request_store.py (v21r2 reorg W2 music).

旧路径 ``plugins.bot_unified_runtime.sources.music_request_store`` 保持可导入（纯
re-export 薄壳）。垫片退役条件见 docs/design/v21r2-reorg-plan.md §3.1。
"""

from plugins.bot_unified_runtime.domains.music.data.music_request_store import *

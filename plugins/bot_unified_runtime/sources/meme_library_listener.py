"""Compat shim: moved to domains/meme/sources/meme_library_listener.py (v21r2 reorg W6 meme).

旧路径 ``plugins.bot_unified_runtime.sources.meme_library_listener`` 保持可导入
（纯 re-export 薄壳，符号与真身同一对象）。monkeypatch 需打真身新路径（垫片陷阱，
见方案书 §3.1）；_download_once/_segment_urls 仅本域测试打点（已同波改指真身），
无全树外引私有名。
"""

from plugins.bot_unified_runtime.domains.meme.sources.meme_library_listener import *

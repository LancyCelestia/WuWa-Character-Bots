"""Compat shim: moved to domains/meme/sources/meme_library.py (v21r2 reorg W6 meme).

旧路径 ``plugins.bot_unified_runtime.sources.meme_library`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。monkeypatch 需打真身新路径（垫片陷阱，见方案书 §3.1）；
_PICK_SCAN_LIMIT 仅本域测试打点（已同波改指真身），无全树外引私有名。
文件路径式加载（scripts/import_meme_packs.py spec_from_file_location）已同波改指真身。
"""

from plugins.bot_unified_runtime.domains.meme.sources.meme_library import *

"""Compat shim: moved to domains/meme/capabilities/randpic.py (v21r2 reorg W6 meme).

旧路径 ``plugins.bot_unified_runtime.capabilities.randpic`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。monkeypatch 需打真身新路径（垫片陷阱，见方案书 §3.1）；
_SCAN_CACHE 等私有态仅本域测试打点（已同波改指真身），无全树外引私有名。
"""

from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import *

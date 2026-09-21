"""Compat shim: moved to domains/assistant/campus/campus_store.py (v21r2 reorg W12).

旧路径 ``plugins.bot_unified_runtime.sources.campus_store`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。monkeypatch 需打真身新路径（垫片陷阱，见方案书 §3.1）。
无私有名外引（波前逐名 rg 扫描实证），``import *`` 即足。
"""

from plugins.bot_unified_runtime.domains.assistant.campus.campus_store import *

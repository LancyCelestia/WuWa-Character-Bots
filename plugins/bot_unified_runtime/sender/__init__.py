"""Compat shim: moved to domains/transport/sender/__init__.py (v21r2 reorg W14 transport).

旧路径 ``plugins.bot_unified_runtime.sender`` 保持可导入（纯 re-export 薄壳，符号与
真身同一对象）。``__all__`` 22 名随真身包 init 转出；子模块（worker/onebot/queue 等）
经旧路径文件垫片由 import 机制兜底解析。垫片退役条件见方案书 §3.1。
"""

from plugins.bot_unified_runtime.domains.transport.sender import *

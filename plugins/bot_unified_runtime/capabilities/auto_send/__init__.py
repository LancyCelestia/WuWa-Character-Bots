"""Compat shim: moved to domains/schedule/auto_send (v21r2 reorg W10 schedule).

旧路径 ``plugins.bot_unified_runtime.capabilities.auto_send`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。真身包 ``__init__`` 自带 ``__all__``，公有面经 ``import *``
全量转发；波前 AST 名字级扫描未见跨界私有名消费。
"""
from plugins.bot_unified_runtime.domains.schedule.auto_send import *

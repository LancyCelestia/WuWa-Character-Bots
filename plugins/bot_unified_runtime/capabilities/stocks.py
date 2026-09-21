"""Compat shim: moved to domains/finance/capabilities/stocks.py (v21r2 reorg W7 finance).

旧路径 ``plugins.bot_unified_runtime.capabilities.stocks`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。垫片退役条件见 docs/design/v21r2-reorg-plan.md §3.1。
"""

from plugins.bot_unified_runtime.domains.finance.capabilities.stocks import *

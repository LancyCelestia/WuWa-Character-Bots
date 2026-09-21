"""Compat shim: moved to domains/finance/data/finance_chart.py (v21r2 reorg W7 finance).

旧路径 ``plugins.bot_unified_runtime.sources.finance_chart`` 保持可导入（纯 re-export
薄壳，符号与真身同一对象）。垫片退役条件见 docs/design/v21r2-reorg-plan.md §3.1。
私有名显式转出（tests/test_finance_charts.py 从本路径 from-import ``_box_stats``）。
"""

from plugins.bot_unified_runtime.domains.finance.data.finance_chart import *
from plugins.bot_unified_runtime.domains.finance.data.finance_chart import (  # noqa: F401
    __all__,
    _box_stats,
)

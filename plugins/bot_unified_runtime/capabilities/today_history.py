"""Compat shim: moved to plugins.bot_unified_runtime.domains.subscribe.capabilities.today_history (v21r2 reorg W8)."""
from plugins.bot_unified_runtime.domains.subscribe.capabilities.today_history import *
from plugins.bot_unified_runtime.domains.subscribe.capabilities.today_history import (  # noqa: F401
    _load_push_table,
    _load_push_table_checked,
    _save_push_table,
)

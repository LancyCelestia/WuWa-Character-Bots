"""Compat shim: package moved to plugins.bot_unified_runtime.domains.chat_reply.policy (v21r4-B reorg RWC6-b).

Live re-export (PEP 562 package __getattr__): attribute access resolves on
the canonical package at access time, so legacy-path importers (incl. the
root __init__) keep working unchanged. Submodule shims (gate/quiet_hours/
rate_limit/reply_budget/roles) live alongside this file.
"""
from importlib import import_module
from typing import Any

_CANONICAL = "plugins.bot_unified_runtime.domains.chat_reply.policy"


def __getattr__(name: str) -> Any:
    return getattr(import_module(_CANONICAL), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(import_module(_CANONICAL))))

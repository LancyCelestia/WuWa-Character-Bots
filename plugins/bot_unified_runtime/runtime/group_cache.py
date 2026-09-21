"""Compat shim: moved to plugins.bot_unified_runtime.domains.chat_reply.runtime.group_cache (v21r2 reorg W15d (chat_reply sub-wave 4/5)).

Live re-export (PEP 562 module __getattr__): attribute access resolves on
the canonical module at access time, so monkeypatch on the canonical path
stays consistent for legacy-path importers.
"""
from importlib import import_module
from typing import Any

_CANONICAL = "plugins.bot_unified_runtime.domains.chat_reply.runtime.group_cache"


def __getattr__(name: str) -> Any:
    return getattr(import_module(_CANONICAL), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(import_module(_CANONICAL))))

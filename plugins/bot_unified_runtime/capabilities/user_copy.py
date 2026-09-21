"""Compat shim: moved to plugins.bot_unified_runtime.domains.chat_reply.capabilities.user_copy (v21r2 reorg RWC3 chat_reply/capabilities).

Live re-export (PEP 562 module __getattr__): attribute access resolves on
the canonical module at access time, so monkeypatch on either path stays
consistent for legacy-path importers.
"""
from importlib import import_module
from typing import Any

_CANONICAL = "plugins.bot_unified_runtime.domains.chat_reply.capabilities.user_copy"


def __getattr__(name: str) -> Any:
    return getattr(import_module(_CANONICAL), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(import_module(_CANONICAL))))

"""Compat shim: moved to plugins.bot_unified_runtime.domains.chat_reply.character.shared_group (v21r2 reorg W15a).

Live re-export (PEP 562 module __getattr__): attribute access resolves on
the canonical module at access time, so monkeypatch on the canonical path
stays consistent for legacy-path importers (covers root __init__.py
call-time function-level imports, capabilities/chat.py and package
__init__ re-export chains). Shim retirement rules: v21r2-reorg-plan §3.1.
"""
from importlib import import_module
from typing import Any

_CANONICAL = "plugins.bot_unified_runtime.domains.chat_reply.character.shared_group"


def __getattr__(name: str) -> Any:
    return getattr(import_module(_CANONICAL), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(import_module(_CANONICAL))))

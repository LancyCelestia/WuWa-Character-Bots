"""Compat shim: moved to plugins.bot_unified_runtime.domains.location.data.moegirl (v21r2 reorg W16).

Live re-export (PEP 562 module __getattr__): attribute access resolves on
the canonical module at access time, so monkeypatch on either path stays
consistent for legacy-path importers (covers sources/acg_search.py call-time
function-level import of moegirl_search).
"""
from importlib import import_module
from typing import Any

_CANONICAL = "plugins.bot_unified_runtime.domains.location.data.moegirl"


def __getattr__(name: str) -> Any:
    return getattr(import_module(_CANONICAL), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(import_module(_CANONICAL))))

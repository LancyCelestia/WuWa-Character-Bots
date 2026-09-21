"""Compat shim: moved to plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki (v21r2 reorg W16).

Live re-export (PEP 562 module __getattr__): attribute access resolves on
the canonical module at access time, so monkeypatch on either path stays
consistent for legacy-path importers (covers root __init__.py call-time
function-level import of _get_shared_store/run_kb_sync_task, providers.py,
knowledge_service.py and smoke.py legacy-path consumers).
"""
from importlib import import_module
from typing import Any

_CANONICAL = "plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki"


def __getattr__(name: str) -> Any:
    return getattr(import_module(_CANONICAL), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(import_module(_CANONICAL))))

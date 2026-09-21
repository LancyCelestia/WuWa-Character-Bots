"""Compat shim: moved to plugins.bot_unified_runtime.domains.media.video.video_pipeline (v21r2 reorg W11).

Live re-export (PEP 562 module __getattr__): attribute access resolves on
the canonical module at access time, so monkeypatch on either path stays
consistent for legacy-path importers.
"""
from importlib import import_module
from typing import Any

_CANONICAL = "plugins.bot_unified_runtime.domains.media.video.video_pipeline"


def __getattr__(name: str) -> Any:
    return getattr(import_module(_CANONICAL), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(import_module(_CANONICAL))))

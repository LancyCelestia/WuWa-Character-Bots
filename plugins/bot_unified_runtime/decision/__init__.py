"""Compat shim: decision 包已迁 domains/core/decision（v21r2 重组 RWOC 尾声波）。

Live re-export (PEP 562)：包级名字与子模块名都实时解析到 canonical，
旧路径 from-import 与 monkeypatch 双向同源。
"""
from importlib import import_module
from typing import Any

_CANONICAL_PKG = "plugins.bot_unified_runtime.domains.core.decision"


def __getattr__(name: str) -> Any:
    try:
        return getattr(import_module(_CANONICAL_PKG), name)
    except AttributeError:
        return import_module(_CANONICAL_PKG + "." + name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(import_module(_CANONICAL_PKG))))

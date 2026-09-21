"""Compat shim: llm 包已迁 domains/chat_reply/llm_engine/（v21r2 重组 W15b）。

Live re-export (PEP 562)：包级名字（providers 契约面 11 名）与子模块名
（model_router/providers/channel_health/ledger/billing_*/usage_service）都实时
解析到 canonical，旧路径 from-import 与 monkeypatch 双向同源。
"""
from importlib import import_module
from typing import Any

_CANONICAL_PKG = "plugins.bot_unified_runtime.domains.chat_reply.llm_engine"


def __getattr__(name: str) -> Any:
    try:
        return getattr(import_module(_CANONICAL_PKG), name)
    except AttributeError:
        return import_module(_CANONICAL_PKG + "." + name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(import_module(_CANONICAL_PKG))))

"""Compat shim: moved to domains/render/render_backends (v21r2 reorg W13 render)."""

from plugins.bot_unified_runtime.domains.render.render_backends import *
from plugins.bot_unified_runtime.domains.render.render_backends import (  # noqa: F401
    _MERMAID_CDN_URL,
    _RENDER_READY_SIGNALS,
    _wait_render_budget,
)

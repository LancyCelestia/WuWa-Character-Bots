"""Compat shim: moved to domains/render/card_render.usage_cards (v21r2 reorg W13 render).

2026-09-18（v21r3 渲染统一步 4）：真身的 ``:root`` 改由 ``mica_shell.render_root_tokens``
单一产出，不再直接 import 主题常量；但旧路径的历史可见面包含它们（调用方与测试仍从
``output.card_render.usage_cards`` 取 ``BRAND_THEME`` 等），故本垫片改为直接自
``theme_tokens`` 转发——维持旧路径可见面不变，真身保持干净。
"""

from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (  # noqa: F401
    BRAND_THEME,
    FONT_FAMILY_STACK,
    SHADOW_PRIMARY,
    SHADOW_SECONDARY,
)
from plugins.bot_unified_runtime.domains.render.card_render.usage_cards import *
from plugins.bot_unified_runtime.domains.render.card_render.usage_cards import (  # noqa: F401
    _CHANNEL_SUBROW_CSS,
    DIVIDER,
    GLOW_ACCENT,
    SURFACE_TINTS,
    Any,
    Path,
    _darken_hex,
    _fmt_int,
    _hex_to_rgb,
    _rgb_to_hex,
    annotations,
    hashlib,
    render_usage_card_png,
    usage_card_accent,
    usage_report_mica_html,
)

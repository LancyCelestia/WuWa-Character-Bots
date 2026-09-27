"""通用卡片渲染子包（移植自 MIT 许可的开源上游项目，出处见 docs/THIRD_PARTY_NOTICES.md）。"""

from plugins.bot_unified_runtime.domains.render.card_render.models import (
    ForwardPayload,
    RenderPayload,
)

from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
    PLATFORM_COLORS,
    PLATFORM_OFFICIAL_NAMES,
    parse_to_render_payload,
    render_universal_card_html,
)

__all__ = [
    "PLATFORM_COLORS",
    "PLATFORM_OFFICIAL_NAMES",
    "ForwardPayload",
    "RenderPayload",
    "parse_to_render_payload",
    "render_universal_card_html",
]

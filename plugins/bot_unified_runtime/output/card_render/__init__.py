"""通用卡片渲染子包（移植自 MIT 许可的开源上游项目，出处见 docs/THIRD_PARTY_NOTICES.md）。"""

from .bridge import (
    PLATFORM_COLORS,
    PLATFORM_OFFICIAL_NAMES,
    parse_to_render_payload,
    render_universal_card_html,
)
from .models import ForwardPayload, RenderPayload

__all__ = [
    "PLATFORM_COLORS",
    "PLATFORM_OFFICIAL_NAMES",
    "ForwardPayload",
    "RenderPayload",
    "parse_to_render_payload",
    "render_universal_card_html",
]

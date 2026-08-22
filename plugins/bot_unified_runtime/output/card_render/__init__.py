"""通用卡片渲染子包（移植自 astrbot_plugin_parser，MIT 许可）。"""

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

"""domains/divination/api: 占卜 REST 面（V2.1 S12）——DTO/错误投影/服务薄壳。

框架无关（不 import fastapi）：控制面路由（control_plane/api/divination.py）是
唯一的 HTTP 投影层，本包只提供严格 DTO、错误码投影与 DivinationService 薄壳。
W5 域半边（service/store/data/capabilities）保持只读消费，零改动。
"""

from plugins.bot_unified_runtime.domains.divination.api.dto import (
    BaziPreviewPayload,
    DivinationDrawPayload,
    FortuneDailyPayload,
    TarotDrawPayload,
)
from plugins.bot_unified_runtime.domains.divination.api.errors import (
    HttpErrorProjection,
    InterpretationNotWiredError,
    project_draw_error,
)
from plugins.bot_unified_runtime.domains.divination.api.facet import (
    BaziRateLimiter,
    DivinationHttpFacade,
    build_divination_facade_from_config,
    principal_has_role,
)

__all__ = [
    "BaziPreviewPayload",
    "BaziRateLimiter",
    "DivinationDrawPayload",
    "DivinationHttpFacade",
    "FortuneDailyPayload",
    "HttpErrorProjection",
    "InterpretationNotWiredError",
    "TarotDrawPayload",
    "build_divination_facade_from_config",
    "principal_has_role",
    "project_draw_error",
]

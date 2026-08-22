"""抓取后端包：重型/动态渲染抓取能力（如 Playwright）。"""

from plugins.bot_unified_runtime.sources.fetchers.playwright_backend import (
    PlaywrightFetchBackend,
)
from plugins.bot_unified_runtime.sources.fetchers.xhs_sign import XhsSigner

__all__ = ["PlaywrightFetchBackend", "XhsSigner"]
from contextlib import asynccontextmanager
from enum import Enum
from typing import Optional
from playwright.async_api import Page, ViewportSize

class BrowserMode(str, Enum):
    PLAYWRIGHT = 'PLAYWRIGHT'
    NONEBOT_HTMLRENDER = 'NONEBOT_HTMLRENDER'

class BrowserAdapter:
    """浏览器适配器"""
    def __init__(
            self,
            mode: BrowserMode,
    ):
        self.mode = mode
        self.browser = None

    @asynccontextmanager
    async def get_new_page(
            self,
            device_scale_factor: float = 1.0,
            viewport: Optional[ViewportSize] = None,
    ):
        kwargs = {}
        if device_scale_factor and device_scale_factor != 1.0:
            kwargs['device_scale_factor'] = device_scale_factor
        if viewport:
            kwargs['viewport'] = viewport
        
        page: Optional[Page] = None
        try:
            if self.mode == BrowserMode.NONEBOT_HTMLRENDER:
                from nonebot_plugin_htmlrender import get_new_page as htmlrender_get_page
                async with htmlrender_get_page(**kwargs) as p:
                    page = p
                    yield p
            elif self.mode == BrowserMode.PLAYWRIGHT:
                from .browser_adapter_playwright import get_new_page as playwright_get_page
                async with playwright_get_page(**kwargs) as p:
                    page = p
                    yield p
            else:
                raise ValueError(f"Unsupported browser mode: {self.mode}")
        finally:
            if page and not page.is_closed():
                await page.close()
                page = None
    

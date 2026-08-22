import asyncio
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Browser, Playwright, ViewportSize
import sys
from typing import Optional, List, Callable

chrome_path = {
    'win32': 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'darwin': '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    'linux': '/usr/bin/google-chrome',
}[sys.platform]

use_headless = sys.platform in ['darwin', 'linux']
use_chrome = sys.platform in ['win32', 'darwin']

print(f'Browser Adapter Playwright: use_headless={use_headless}, use_chrome={use_chrome}, chrome_path={chrome_path}')

class BrowserManager:
    def __init__(self):
        self._runtime_instance: Optional[Browser] = None
        self._p_holding: Optional[Playwright] = None
        self._instance_creating: bool = False
        self._instance_waiting: List[Callable] = []

    def close(self):
        p = self._p_holding
        browser = self._runtime_instance
        self._p_holding = None
        self._runtime_instance = None
        if p:
            asyncio.create_task(p.stop())
        if browser:
            asyncio.create_task(browser.close())

    async def _create_instance(self):
        if self._instance_creating:
            raise RuntimeError("Instance is creating")
        self._instance_creating = True
        ap = async_playwright()
        p = await ap.start()
        self._p_holding = p
        browser = await p.chromium.launch(
            headless=use_headless,
            executable_path=chrome_path if use_chrome else None,
        )
        self._runtime_instance = browser
        self._instance_creating = False
        self._flush_waitings()
        return browser
    
    def _flush_waitings(self):
        if len(self._instance_waiting) < 1:
            return
        for task in self._instance_waiting:
            task(self._runtime_instance)
        self._instance_waiting = []

    async def get_instance(self) -> Browser:
        if not self._runtime_instance:
            if not self._instance_creating:
                await self._create_instance()
                return await self.get_instance()
            # 创建一个 Future 来等待实例创建完成
            future: asyncio.Future[Browser] = asyncio.Future()
            self._instance_waiting.append(future.set_result)
            return await future
        return self._runtime_instance

browser_manager = BrowserManager()

@asynccontextmanager
async def get_new_page(
        device_scale_factor: float = 1.0,
        viewport: Optional[ViewportSize] = None,
):
    print('Getting new page...')
    browser = await browser_manager.get_instance()
    print('Got browser instance.')
    context = await browser.new_context(
        device_scale_factor = device_scale_factor,
        viewport = viewport
    )
    print('Created new context.')
    page = await context.new_page()
    try:
        print('Created new page.')
        yield page
        print('Yielded page.')
    finally:
        print('Closing page and context...')
        await page.close()
        await context.close()
        print('Closed page and context.')


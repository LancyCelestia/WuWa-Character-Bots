import asyncio
import os
import sys

DIRNAME = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(DIRNAME)
sys.path.append(ROOT_DIR)

from modules.browser_adapter import BrowserAdapter, BrowserMode

TMP_DIR = os.path.join(ROOT_DIR, 'tmp')

os.makedirs(TMP_DIR, exist_ok=True)

async def test_browser_adapter():
    url = 'file://' + os.path.join(ROOT_DIR, 'resources/render-v2/bilibili/comment.html?mock=1')
    adapter = BrowserAdapter(
        mode=BrowserMode.PLAYWRIGHT,
    )
    async with adapter.get_new_page(
        viewport={'width': 1280, 'height': 720},
    ) as page:
        print('- Browser launched')
        await page.goto(url)
        print('- Page loaded')
        await page.wait_for_selector('.comment-container', timeout=15000)
        await asyncio.sleep(.5)  # 等待额外的 JS 执行
        screenshot = await page.screenshot(full_page=True, type='jpeg', quality=80)
        screenshot_path = os.path.join(TMP_DIR, 'test-browser-adapter.jpg')
        with open(screenshot_path, 'wb') as f:
            f.write(screenshot)
        print(f'- Screenshot saved to {screenshot_path}')

def main():
    import asyncio
    asyncio.run(test_browser_adapter())

if __name__ == '__main__':
    main()

import aiohttp
import asyncio
import json
import os
from pathlib import Path
import sys

from aiohttp import web

# 添加父目录到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.bilibili_apis import BilibiliApis 
from modules.bilibili_api_host import get_app
from modules.browser_adapter import BrowserAdapter, BrowserMode

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(DIRECTORY)
TMP_DIR = os.path.join(ROOT_DIR, 'tmp')

os.makedirs(TMP_DIR, exist_ok=True)

class Counter:
    def __init__(self, name=''):
        self.count = 0
        self.name = name

    def next(self):
        self.count += 1
        return f'{self.name}_{self.count}'

async def test_host():
    port = 8078
    browser_adapter = BrowserAdapter(mode=BrowserMode.PLAYWRIGHT)
    
    api_web = get_app(browser_mode=BrowserMode.PLAYWRIGHT)
    runner = web.AppRunner(api_web.app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', port)
    
    try:
        await site.start()
        print(f'Bilibili 助手服务已启动 on http://127.0.0.1:{port}')

        # 测试逻辑
        url = f'http://127.0.0.1:{port}/render/comments?bvid=BV1tuadziEef'
        print(f'- 测试渲染评论: {url}')
        
        loop = asyncio.get_running_loop()
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=60) as response:
                response.raise_for_status()
                result = await response.json()
                code = result.get('code', -1)
                msg = result.get('message', '')
        if code != 0:
            print(f'- Render comments error: {code} {msg}')
            return
        data = result.get('data', {})
        rendered_html = data.get('html', '')
        html_file = Path(TMP_DIR) / f'comment.html'
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(rendered_html)
        print(f'- Rendered comments saved to {html_file}')
        file_url = f'file://{html_file.absolute()}'
        print(f'- Open file URL: {file_url}')
        async with browser_adapter.get_new_page(
            viewport={'width': 800, 'height': 600},
        ) as page:
            print('- Navigating to page...')
            await page.goto(file_url)
            await page.wait_for_load_state("networkidle")
            screenshot = await page.screenshot(full_page=True, type='jpeg')
            shot_file = Path(TMP_DIR) / f'comment.jpg'
            with open(shot_file, 'wb') as f:
                f.write(screenshot)
            print(f'- Screenshot saved to {shot_file}')

    except Exception as e:
        print('- Request error:', e)
    finally:
        await runner.cleanup()
        print('Bilibili 助手服务已停止')

async def test_api():
    cookie_json_path = Path(ROOT_DIR) / '../../data' / 'bili_helper_cookie.json'
    cookie_value = ''
    if cookie_json_path.exists():
        with open(cookie_json_path, 'r', encoding='utf-8') as f:
            try:
                cookie_data = json.load(f)
                cookie_value = cookie_data.get('value', '')
                print('Loaded cookie value:', cookie_value)
            except Exception as e:
                print('Failed to load cookie JSON:', e)
    else:
        print('Cookie JSON file does not exist:', cookie_json_path)
    api = BilibiliApis(
        cookie=cookie_value,
    )
    response = await api.get_comments_api(
        oid='115256957471455',
        type=1,
        next_offset='',
    ).call()
    # response = api.videoInfoApi(
    #     bvid='BV1YaJDzAEGP',
    # ).call()
    print(json.dumps(response, ensure_ascii=False, indent=2))

# === 主函数入口 ===

async def main():
    await test_api()
    # await test_host()

if __name__ == '__main__':
    asyncio.run(main())

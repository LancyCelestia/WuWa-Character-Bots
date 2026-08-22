# import asyncio
from aiohttp import web
import json
import os
from pathlib import Path

from .bilibili_apis import BilibiliApis
from .browser_adapter import BrowserAdapter, BrowserMode

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(DIRECTORY)
WEB_DIR = os.path.join(ROOT_DIR, 'resources')
MOCK_DIC = os.path.join(WEB_DIR, 'mocks')

def get_app(
        browser_mode: BrowserMode=BrowserMode.NONEBOT_HTMLRENDER,
        cookie: str = '',
):
    bilibili_apis = BilibiliApis(cookie=cookie)
    browser_adapter = BrowserAdapter(mode=browser_mode)

    async def api_mock(request):
        """
        返回模拟数据的接口示例
        GET /mock?t=example
        """
        t = request.query.get('t', '')
        mock_file = Path(MOCK_DIC) / f'{t}.json'
        if not mock_file.is_file():
            return web.Response(status=404, text='Mock file does not exist.')
        with open(mock_file, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        # web.json_response 会自动设置 Content-Type: application/json
        return web.json_response(payload)

    async def bvid2aid(request):
        """
        B站BV号转AV号接口
        GET /bvid2aid?bvid=BV1xx411c7mD
        返回示例:
        {
            "bvid": "BV1xx411c7mD",
            "aid": 170001
        }
        """
        bvid = request.query.get('bvid', '')
        if not bvid.startswith('BV'):
            return web.json_response({'error': 'Invalid BVID'}, status=400)
        try:
            aid = bilibili_apis.bv2av(bvid)
            return web.json_response({'bvid': bvid, 'aid': aid})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def aid2bvid(request):
        """
        B站AV号转BV号接口
        GET /aid2bvid?aid=170001
        返回示例:
        {
            "aid": 170001,
            "bvid": "BV1xx411c7mD"
        }
        """
        aid_str = request.query.get('aid', '')
        if not aid_str.isdigit():
            return web.json_response({'error': 'Invalid AID'}, status=400)
        aid = int(aid_str)
        try:
            bvid = bilibili_apis.av2bv(aid)
            return web.json_response({'aid': aid, 'bvid': bvid})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def video_info(request):
        """
        获取视频信息接口
        GET /video_info?bvid=BV1xx411c7mD
        或
        GET /video_info?aid=170001
        返回示例:
        {
            "code": 0,
            "message": "成功",
            "data": { ... }
        }
        """
        bvid = request.query.get('bvid', '')
        aid_str = request.query.get('aid', '')
        aid = int(aid_str) if aid_str.isdigit() else None
        if not bvid and not aid:
            return web.json_response({'error': 'Must provide either BVID or AID'}, status=400)
        try:
            api_invoker = bilibili_apis.video_info_api(aid=aid, bvid=bvid)
            result = await api_invoker.call()
            return web.json_response(result)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def comments(request):
        """
        获取视频评论接口
        GET /comments?oid=123456&type=1&next_offset=
        参数:
        - oid: 视频的AV号或BV号对应的数字ID
        - type: 评论类型, 1表示视频
        - next_offset: 分页参数, 初始为空
        返回示例:
        {
            "code": 0,
            "message": "成功",
            "data": { ... }
        }
        """
        oid = request.query.get('oid', '')
        type_str = request.query.get('type', '1')
        next_offset = request.query.get('next_offset', '')
        if not oid.isdigit() or not type_str.isdigit():
            return web.json_response({'error': 'Invalid oid or type'}, status=400)
        type = int(type_str)
        try:
            api_invoker = bilibili_apis.get_comments_api(oid=oid, type=type, next_offset=next_offset)
            result = await api_invoker.call()
            return web.json_response(result)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def render_comments(request):
        """
        渲染评论的HTML页面
        GET /render/comments?bvid=BV1xx411c7mD
        """
        bvid = request.query.get('bvid', '')
        if not bvid.startswith('BV'):
            return web.Response(status=400, text='Invalid BVID')
        try:
            url = f'http://{request.host}/resources/render/bilibili/comment.html?bvid={bvid}'
            print('- Page URL:', url)
            async with browser_adapter.get_new_page() as page:
                print('- Navigating to page...')
                await page.goto(url)
                await page.wait_for_load_state("networkidle")
                # print('- Page content:', await page.content())
                rendered_result = await page.evaluate('document.getElementById("rendered-result")?.textContent || ""')
                rendered_html = await page.evaluate('document.getElementById("rendered-html")?.textContent || ""')
                print('- Rendered Result:', rendered_result)
                result = json.loads(rendered_result) if rendered_result else {}
                # 如果 result 没有 code 字段，补充一个
                if 'code' not in result:
                    result['code'] = -1
                if 'message' not in result:
                    result['message'] = '未知错误'
                if result.get('code') != 0:
                    return web.json_response(result)
                # file_url = f'file://{html_file}'
                # await page.goto(file_url)
                # await page.wait_for_load_state("networkidle")
                # screenshot = await page.screenshot(full_page=True, type='jpeg')
                # return web.Response(body=screenshot, content_type='image/jpeg')
                return web.json_response({
                    'code': 0,
                    'message': '成功',
                    'data': {
                        'html': rendered_html,
                    },
                })

        except Exception as e:
            print('- Render comments error:', e)
            return web.Response(status=500, text=str(e))

    from aiohttp.web_request import Request
    from aiohttp.typedefs import Handler

    @web.middleware
    async def cors_middleware(request: Request, handler: Handler):
        """
        为静态资源添加 CORS 头的中间件
        """
        response = await handler(request)
        # print(f"Request path: {request.path}")
        if request.path.startswith('/resources/font/'):
            response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    app = web.Application(
        middlewares=[cors_middleware],
    )

    app.router.add_static('/resources/', path=WEB_DIR, name='resource', show_index=True)
    app.router.add_get('/mock', api_mock)
    app.router.add_get('/bvid2aid', bvid2aid)
    app.router.add_get('/aid2bvid', aid2bvid)
    app.router.add_get('/video_info', video_info)
    app.router.add_get('/comments', comments)
    app.router.add_get('/render/comments', render_comments)

    class WrappedApp:
        def __init__(self, app, set_cookie_func):
            self.app = app
            self._set_cookie = set_cookie_func

        def set_cookie(self, cookie: str):
            self._set_cookie(cookie)

    return WrappedApp(
        app=app,
        set_cookie_func=bilibili_apis.set_cookie,
    )

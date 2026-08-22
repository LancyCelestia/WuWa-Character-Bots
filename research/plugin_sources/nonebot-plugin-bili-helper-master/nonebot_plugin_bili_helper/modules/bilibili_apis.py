import aiohttp
import re
from typing import Optional, Tuple, Union
from .api_base import ApiEnv, ApiEncoder, ApiInfo, ApiInvoker
from .bilibili_encoder import WbiEncoder
from .bv2av import bv2av, av2bv

URL_REGEXPS = {
    'SHORT_URL': re.compile(r'(^|(?<=\W))https?://b23\.tv/(?P<id>[a-zA-Z0-9]+)'),
    'LONG_URL': re.compile(r'(^|(?<=\W))https?://(?:www\.|m\.)?bilibili\.com/video/(?P<id>av[0-9]+|BV[0-9a-zA-Z]+)'),
    'BV_CODE': re.compile(r'(^)(?P<id>BV[0-9a-zA-Z]{5,15})($)'),
}

class BilibiliApis(ApiEnv):
    """B 站 API 集合"""

    def __init__(
            self,
            ua: Optional[str] = None,
            refer: Optional[str] = None,
            cookie: Optional[str] = None,
        ):
        ua = ua or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        refer = refer or 'https://www.bilibili.com/'
        cookie = cookie or ''
        super().__init__(ua=ua, refer=refer, cookie=cookie)
        # print('BilibiliApis initialized with cookie:', self.cookie)

    def set_cookie(self, cookie: str):
        self.cookie = cookie
        if hasattr(self, '_encoder'):
            delattr(self, '_encoder')
        # print('BilibiliApis cookie updated to:', self.cookie)

    def get_encoder(self) -> ApiEncoder:
        if not hasattr(self, '_encoder'):
            # print('Creating new WbiEncoder with cookie:', self.cookie)
            self._encoder = WbiEncoder(
                ua=self.ua,
                refer=self.refer,
                cookie=self.cookie,
            )
        return self._encoder

    def check_result(self, result: dict) -> Tuple[bool, str]:
        code = result.get('code', -1)
        if code == 0:
            return True, '成功'
        msg = result.get('message', '未知错误')
        return False, msg
    
    def bv2av(self, bvid: str) -> int:
        'BV 号转 AV 号'
        return bv2av(bvid)

    def av2bv(self, aid: int) -> str:
        'AV 号转 BV 号'
        return av2bv(aid)

    def get_url_from_text(self, text: str):
        '从文本中提取 BV 号或 AV 号链接'
        url: Optional[str] = None
        for key, regexp in URL_REGEXPS.items():
            m = regexp.search(text)
            if not m: continue
            url = m.group(0) if m and len(m.groups()) >= 1 else None
            if key.endswith('_CODE'):
                url = f"https://b23.tv/{url}"
            break
        return url

    async def get_id_from_url(self, url: str):
        '从 URL 中提取 BV 号或 AV 号'
        matched = None
        for regexp in URL_REGEXPS.values():
            m = regexp.match(url)
            if not m: continue
            matched = m
        # print(f'get_id_from_url: matched={matched}, groups length={len(matched.groups()) if matched else 0}')
        # 取出 ID 部分
        dict = matched.groupdict() if matched else {}
        id_str = dict.get("id", None) if dict else None
        if not matched or not id_str:
            return None
        # 判断是 BV 号还是 AV 号
        type = id_str[:2].lower()
        id = id_str[2:]
        print(f'get_id_from_url: type={type}, id={id}')
        if type == 'av' and id.isdigit():
            aid = int(id)
            bvid = av2bv(aid)
            return {
                'av': aid,
                'bv': bvid
            }
        elif type == 'bv' and re.match(r'^[0-9a-zA-Z]+$', id):
            bvid = id_str
            aid = bv2av(bvid)
            return {
                'av': aid,
                'bv': bvid
            }
        elif re.match(r'^https://b23.tv/', url):
            # 短链，无法直接判断，根据请求后重定向的 location 来判断
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.head(url, allow_redirects=True, timeout=10) as resp:
                        final_url = str(resp.url)
                # print(f'get_id_from_url: 短链重定向到 {final_url}')
                return await self.get_id_from_url(final_url)
            except Exception as e:
                print(f'get_id_from_url: 无法解析短链 {url}: {e}')
        return None

    def video_info_api(self, aid: Optional[int]=None, bvid: Optional[str]=None) -> ApiInvoker:
        '获取指定 bvid 的视频信息'
        'https://github.com/SocialSisterYi/bilibili-API-collect/blob/47be3f206fc5d8a92fa81886eb507e4492e4e27a/docs/video/info.md'
        url = 'https://api.bilibili.com/x/web-interface/view'
        params = {
            'aid': aid if aid else '',
            'bvid': bvid if bvid else '',
        }
        errors = {
            '0': '成功',
            '-400': '请求错误',
            '-403': '权限不足',
            '-404': '视频不存在',
            '62002': '稿件不可见',
            '62004': '稿件审核中',
            '62012': '仅UP主可见',
        }
        return ApiInvoker(
            self,
            ApiInfo(url, params, errors, encoder=None),
        )

    def get_comments_api(self, oid: str, type: int, next_offset: str) -> ApiInvoker:
        '获取指定 oid 的评论列表'
        'https://github.com/SocialSisterYi/bilibili-API-collect/blob/60a0c5d1a2f44fe61335da04571305fa7727a968/docs/comment/list.md'
        url = 'https://api.bilibili.com/x/v2/reply/wbi/main'
        params = {
            'oid': oid,
            'type': type,
            'mode': 3,
            'pagination_str': f'{{"offset":"{next_offset}"}}' if next_offset else '',
            'plat': 1,
            'seek_rpid': '',
            'web_location': 1315875,
        }
        errors = {
            '0': '成功',
            '-400': '请求错误',
            '-404': '无此项',
            '12002': '评论区已关闭',
            '12009': '评论主体的 type 不合法',
        }
        return ApiInvoker(
            self,
            ApiInfo(url, params, errors, encoder=self.get_encoder()),
        )

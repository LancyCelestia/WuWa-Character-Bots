import aiohttp
from typing import Optional, Tuple
import urllib.parse
import time
from functools import reduce
from hashlib import md5

from .api_base import ApiEncoder

class WbiEncoder(ApiEncoder):
    'B 站 WBI 签名算法'

    mixin_key_enc_tab = [
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
        33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
        61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
        36, 20, 34, 44, 52
    ]

    def __init__(self, ua: str, refer: str = '', cookie: str = ''):
        self.ua = ua
        self.refer = refer
        self.cookie = cookie
        self.key_cache: Optional[Tuple[str, str]] = None

    def set_cookie(self, cookie: str):
        self.cookie = cookie
        self.key_cache = None

    async def encode(self, url: str, params: dict) -> Tuple[str, dict]:
        new_params = await self.enc_wbi(params)
        return url, new_params

    @staticmethod
    def get_mixin_key(orig: str):
        '对 imgKey 和 subKey 进行字符顺序打乱编码'
        return reduce(lambda s, i: s + orig[i], WbiEncoder.mixin_key_enc_tab, '')[:32]

    async def enc_wbi(self, params: dict):
        '为请求参数进行 wbi 签名'
        img_key, sub_key = await self.get_wbi_keys()
        mixin_key = WbiEncoder.get_mixin_key(img_key + sub_key)
        curr_time = round(time.time())
        params['wts'] = curr_time                                   # 添加 wts 字段
        params = dict(sorted(params.items()))                       # 按照 key 重排参数
        # 过滤 value 中的 "!'()*" 字符
        params = {
            k : ''.join(filter(lambda chr: chr not in "!'()*", str(v)))
            for k, v 
            in params.items()
        }
        query = urllib.parse.urlencode(params)                      # 序列化参数
        wbi_sign = md5((query + mixin_key).encode()).hexdigest()    # 计算 w_rid
        params['w_rid'] = wbi_sign
        return params

    async def get_wbi_keys(self) -> Tuple[str, str]:
        '获取 img_key 和 sub_key'
        if self.key_cache is not None:
            return self.key_cache
        headers = {
            'User-Agent': self.ua,
            'Referer': self.refer,
            'Cookie': self.cookie,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get('https://api.bilibili.com/x/web-interface/nav', headers=headers) as resp:
                resp.raise_for_status()
                json_content = await resp.json()
                img_url: str = json_content['data']['wbi_img']['img_url']
        sub_url: str = json_content['data']['wbi_img']['sub_url']
        img_key = img_url.rsplit('/', 1)[1].split('.')[0]
        sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
        self.key_cache = (img_key, sub_key)
        return self.key_cache

"""B 站 WBI 接口签名工具（纯函数 + 轻量 HTTP 请求）。

WBI 签名流程：

1. 从 ``https://api.bilibili.com/x/web-interface/nav`` 的
   ``data.wbi_img.img_url/sub_url`` 提取两个 32 位文件名；
2. 拼接后按 ``WBI_KEY_TABLE`` 重排，取前 32 位作为 mixin key；
3. 请求参数插入当前时间戳 ``wts``，按键排序、过滤保留字符、urlencode；
4. 对 ``query + mixin_key`` 做 md5，得到 ``w_rid`` 后拼回 URL。
"""

from __future__ import annotations

import hashlib
import threading
import time
from urllib.parse import urlencode, urlsplit

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

_NAV_API = "https://api.bilibili.com/x/web-interface/nav"
_WBI_FILTER_CHARS = "!'()*"

# nav keys 每天轮换：缓存 30 分钟，避免同一批解析重复请求 nav。
_WBI_CACHE_TTL_SECONDS = 1800.0
_WBI_CACHE_LOCK = threading.Lock()
_WBI_CACHE: dict[str, tuple[float, str]] = {}


def _cached_mixin_key(cookie_header: str, proxy: str) -> str:
    cache_key = f"{cookie_header}|{proxy}"
    now = time.monotonic()
    with _WBI_CACHE_LOCK:
        hit = _WBI_CACHE.get(cache_key)
        if hit is not None and now - hit[0] < _WBI_CACHE_TTL_SECONDS:
            return hit[1]
    nav = http_get_json(
        _NAV_API,
        referer="https://www.bilibili.com/",
        cookie=cookie_header,
        proxy=proxy,
    )
    wbi_img = ((nav or {}).get("data") or {}).get("wbi_img") or {}
    img_url = str(wbi_img.get("img_url") or "")
    sub_url = str(wbi_img.get("sub_url") or "")
    if not img_url or not sub_url:
        raise ParseHttpError("bilibili nav missing wbi_img keys")
    mixin_key = extract_mixin_key(img_url, sub_url)
    with _WBI_CACHE_LOCK:
        _WBI_CACHE[cache_key] = (time.monotonic(), mixin_key)
    return mixin_key

WBI_KEY_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def _wbi_filename(url: str) -> str:
    """取 URL path 最后一段并去掉 ``.png`` 后缀。"""
    filename = urlsplit(str(url)).path.rsplit("/", 1)[-1]
    if filename.lower().endswith(".png"):
        filename = filename[:-4]
    return filename


def extract_mixin_key(img_url: str, sub_url: str) -> str:
    """由 img_url / sub_url 文件名计算 WBI mixin key（32 位）。"""
    raw_key = _wbi_filename(img_url) + _wbi_filename(sub_url)
    return "".join(raw_key[index] for index in WBI_KEY_TABLE[:32])


def sign_wbi(params: dict, mixin_key: str, wts: int | None = None) -> dict:
    """为参数字典追加 ``wts`` / ``w_rid`` 并返回新字典。"""
    signed = dict(params)
    signed["wts"] = int(time.time()) if wts is None else int(wts)
    filtered = {
        key: "".join(
            ch for ch in str(value) if ch not in _WBI_FILTER_CHARS
        )
        for key, value in sorted(signed.items())
    }
    query = urlencode(filtered)
    w_rid = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    signed["w_rid"] = w_rid
    return signed


def build_wbi_signed_url(
    url: str,
    params: dict,
    *,
    cookie_header: str = "",
    proxy: str = "",
) -> str:
    """获取 nav 中的 WBI key 后签名，并返回拼接好的 URL（key 带缓存）。"""
    if params.get("w_rid"):
        return f"{url}?{urlencode(params)}"
    mixin_key = _cached_mixin_key(cookie_header, proxy)
    signed = sign_wbi(dict(params), mixin_key)
    return f"{url}?{urlencode(signed)}"

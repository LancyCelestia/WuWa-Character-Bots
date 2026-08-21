"""第三方平台解析用轻量 HTTP 工具（stdlib urllib）。

统一带 UA / Referer / gzip / 超时，解析失败一律抛 ``ParseHttpError``，
由上层能力做降级。所有函数为同步调用，适合放进 to_thread 执行。
"""

from __future__ import annotations

import gzip
import json
from typing import Any
from urllib import parse as urlparse
from urllib import request as urlrequest

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class ParseHttpError(Exception):
    """解析平台的 HTTP 请求失败（含超时）。"""


def _build_request(
    url: str,
    *,
    referer: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    accept: str = "",
) -> urlrequest.Request:
    headers = {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    if accept:
        headers["Accept"] = accept
    return urlrequest.Request(url, headers=headers)


def http_get(
    url: str,
    *,
    timeout: float = 10.0,
    referer: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    accept: str = "",
) -> tuple[str, bytes]:
    """GET 并返回 (最终 URL, 响应体)；短链重定向后 final_url 是落点。"""
    try:
        with urlrequest.urlopen(
            _build_request(url, referer=referer, user_agent=user_agent, accept=accept),
            timeout=timeout,
        ) as response:
            payload = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                payload = gzip.decompress(payload)
            return response.geturl(), payload
    except Exception as exc:  # noqa: BLE001 - 统一包装成解析层错误。
        raise ParseHttpError(f"GET {url} failed: {type(exc).__name__}") from exc


def http_get_text(
    url: str,
    *,
    timeout: float = 10.0,
    referer: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    accept: str = "",
    encoding: str = "utf-8",
) -> tuple[str, str]:
    final_url, payload = http_get(
        url,
        timeout=timeout,
        referer=referer,
        user_agent=user_agent,
        accept=accept,
    )
    try:
        text = payload.decode(encoding, errors="replace")
    except LookupError:
        text = payload.decode("utf-8", errors="replace")
    return final_url, text


def http_get_json(
    url: str,
    *,
    timeout: float = 10.0,
    referer: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
) -> Any:
    final_url, payload = http_get(
        url,
        timeout=timeout,
        referer=referer,
        user_agent=user_agent,
        accept="application/json, text/plain, */*",
    )
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ParseHttpError(
            f"GET {url} returned non-JSON: {type(exc).__name__}"
        ) from exc


def resolve_short_link(url: str, *, timeout: float = 10.0) -> str:
    """跟随重定向拿最终落点 URL（B 站 b23.tv、小红书 xhslink 等）。"""
    final_url, _ = http_get(url, timeout=timeout)
    return final_url


def strip_tracking_query(url: str) -> str:
    """只保留 scheme/netloc/path，丢弃查询串（解析用，避免签名参数干扰）。"""
    parts = urlparse.urlsplit(url)
    return urlparse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

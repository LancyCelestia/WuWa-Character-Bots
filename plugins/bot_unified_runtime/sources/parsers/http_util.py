"""第三方平台解析用轻量 HTTP 工具（stdlib urllib）。

统一带 UA / Referer / gzip / 超时，解析失败一律抛 ``ParseHttpError``，
由上层能力做降级。所有函数为同步调用，适合放进 to_thread 执行。
"""

from __future__ import annotations

import gzip
import json
import time
from typing import Any
from urllib import parse as urlparse
from urllib import request as urlrequest
from urllib.error import HTTPError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 响应体默认上限：所有 http_get*/http_post* 默认生效（max_bytes=None 时），
# 防止异常响应/恶意大文件撑爆内存。覆盖本仓库全部平台的 HTML/JSON/API
# 响应（最大为油管 watch 页与小红书 INITIAL_STATE，均在 3MB 量级）。
# 传 0 或负数表示不限制；调用方可显式传更大的值覆盖。
DEFAULT_MAX_BYTES = 8 * 1024 * 1024


class ParseHttpError(Exception):
    """解析平台的 HTTP 请求失败（含超时）。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


_DEFAULT_PROXY = ""


def build_request_headers(context: Any) -> dict[str, str]:
    """从 FetchContext 构造真实请求头；诊断脱敏由上下文对象负责。"""
    headers = {
        "User-Agent": str(getattr(context, "user_agent", DEFAULT_USER_AGENT)),
        "Accept-Encoding": "gzip",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    cookie = str(getattr(context, "cookie_header", "") or "")
    if cookie:
        headers["Cookie"] = cookie
    extra_headers = getattr(context, "extra_headers", {}) or {}
    if isinstance(extra_headers, dict):
        headers.update({str(key): str(value) for key, value in extra_headers.items()})
    return headers


def _build_opener(
    proxy: str = "",
    *,
    verify_ssl: bool = True,
    extra_handlers: list[Any] | None = None,
) -> urlrequest.OpenerDirector:
    effective = (proxy or "").strip() or _DEFAULT_PROXY
    handlers: list[Any] = []
    if effective:
        handlers.append(
            urlrequest.ProxyHandler({"http": effective, "https": effective})
        )
    if not verify_ssl:
        import ssl

        handlers.append(urlrequest.HTTPSHandler(context=ssl._create_unverified_context()))
    if extra_handlers:
        handlers.extend(extra_handlers)
    return urlrequest.build_opener(*handlers)


def _build_request(
    url: str,
    *,
    referer: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    accept: str = "",
    cookie: str = "",
    extra_headers: dict[str, str] | None = None,
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
    if cookie:
        headers["Cookie"] = cookie
    if extra_headers:
        headers.update(extra_headers)
    return urlrequest.Request(url, headers=headers)


def _http_error_to_parse_error(action: str, url: str, exc: HTTPError) -> ParseHttpError:
    """HTTPError → ParseHttpError，保留状态码与 Retry-After（供上层退避）。"""
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    try:
        retry_after_value = int(str(retry_after).strip()) if retry_after else None
    except ValueError:
        retry_after_value = None
    return ParseHttpError(
        f"{action} {url} failed: HTTP {exc.code}",
        status_code=int(exc.code),
        retry_after_seconds=retry_after_value,
    )


# 429 有界重试（移植自实战油猴脚本算法：x-download-helper.user-v1.4.0.js
# L615-695 pickRetryDelay / 4xx 快速失败）：429 优先遵循 Retry-After 响应头
# （60s 封顶），无头按退避基数指数退避；其余 4xx 是永久性失败（实测 X CDN
# 对 format 不匹配的转换请求一律 404），立即放弃不重试；5xx/网络错误维持
# 原语义直接抛 ParseHttpError。总尝试 = 首次 + 最多 2 次重试；线程内同步
# 热路径，简单有界，不引入新依赖。
HTTP_GET_MAX_ATTEMPTS = 3
_HTTP_RETRY_AFTER_CAP_SECONDS = 60
_HTTP_RETRY_BACKOFF_BASE_SECONDS = 1.0

# 测试注入点：monkeypatch 本符号避免真实 sleep。
_sleep = time.sleep


def _retry_delay_seconds(attempt: int, retry_after_seconds: int | None) -> float:
    """429 等待时长：Retry-After 优先（60s 封顶），无头按基数指数退避。"""
    if retry_after_seconds is not None and retry_after_seconds > 0:
        return float(min(retry_after_seconds, _HTTP_RETRY_AFTER_CAP_SECONDS))
    return _HTTP_RETRY_BACKOFF_BASE_SECONDS * (2**attempt)


def _read_capped(response: Any, url: str, max_bytes: int) -> bytes:
    """读取响应体并施加大小上限；超限抛 ParseHttpError。

    先按传输字节（gzip 时为压缩字节）read(max_bytes+1) 判超限；gzip 响应
    解压阶段同样限幅，防止 gzip 炸弹绕过传输层上限。
    """
    raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ParseHttpError(
            f"GET {url} response exceeds max_bytes={max_bytes}"
        )
    if response.headers.get("Content-Encoding", "").lower() == "gzip" and raw:
        import zlib

        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        out = decompressor.decompress(raw, max_bytes + 1)
        # unconsumed_tail 非空说明解压输出超过 max_bytes 仍未读完。
        if len(out) > max_bytes or decompressor.unconsumed_tail:
            raise ParseHttpError(
                f"GET {url} response exceeds max_bytes={max_bytes} after gzip"
            )
        raw = out + decompressor.flush()
    return raw


def http_get(
    url: str,
    *,
    timeout: float = 10.0,
    referer: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    accept: str = "",
    cookie: str = "",
    proxy: str = "",
    verify_ssl: bool = True,
    extra_headers: dict[str, str] | None = None,
    max_bytes: int | None = None,
) -> tuple[str, bytes]:
    """GET 并返回 (最终 URL, 响应体)；短链重定向后 final_url 是落点。

    max_bytes 默认取 ``DEFAULT_MAX_BYTES``（默认生效，无需调用方关心）；
    传 0/负数表示不限制。429 按 Retry-After 有界重试（最多 2 次），
    其余 4xx 立即失败不重试（出处见 ``_retry_delay_seconds`` 注释）。
    """
    effective_max = DEFAULT_MAX_BYTES if max_bytes is None else int(max_bytes)
    for attempt in range(HTTP_GET_MAX_ATTEMPTS):
        try:
            with _build_opener(proxy, verify_ssl=verify_ssl).open(
                _build_request(
                    url,
                    referer=referer,
                    user_agent=user_agent,
                    accept=accept,
                    cookie=cookie,
                    extra_headers=extra_headers,
                ),
                timeout=timeout,
            ) as response:
                if effective_max > 0:
                    # 限幅读法（含 gzip 限幅解压），响应体已就绪。
                    payload = _read_capped(response, url, effective_max)
                else:
                    payload = response.read()
                    if response.headers.get("Content-Encoding", "").lower() == "gzip":
                        payload = gzip.decompress(payload)
                return response.geturl(), payload
        except ParseHttpError:
            raise
        except HTTPError as exc:
            error = _http_error_to_parse_error("GET", url, exc)
            # 仅 429 在预算内等待重试；其余 4xx 永久性失败立即抛出。
            if error.status_code != 429 or attempt + 1 >= HTTP_GET_MAX_ATTEMPTS:
                raise error from exc
            _sleep(_retry_delay_seconds(attempt, error.retry_after_seconds))
        except Exception as exc:
            raise ParseHttpError(f"GET {url} failed: {type(exc).__name__}") from exc
    # 每轮循环必经 return 或 raise，此处不可达（收口 mypy 缺 return）。
    raise ParseHttpError(f"GET {url} failed: retries exhausted")


def http_get_text(
    url: str,
    *,
    timeout: float = 10.0,
    referer: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    accept: str = "",
    encoding: str = "utf-8",
    cookie: str = "",
    proxy: str = "",
    extra_headers: dict[str, str] | None = None,
    max_bytes: int | None = None,
) -> tuple[str, str]:
    final_url, payload = http_get(
        url,
        timeout=timeout,
        referer=referer,
        user_agent=user_agent,
        accept=accept,
        cookie=cookie,
        proxy=proxy,
        extra_headers=extra_headers,
        max_bytes=max_bytes,
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
    cookie: str = "",
    proxy: str = "",
    verify_ssl: bool = True,
    extra_headers: dict[str, str] | None = None,
    max_bytes: int | None = None,
) -> Any:
    _, payload = http_get(
        url,
        timeout=timeout,
        referer=referer,
        user_agent=user_agent,
        accept="application/json, text/plain, */*",
        cookie=cookie,
        proxy=proxy,
        verify_ssl=verify_ssl,
        extra_headers=extra_headers,
        max_bytes=max_bytes,
    )
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise ParseHttpError(
            f"GET {url} returned non-JSON: {type(exc).__name__}"
        ) from exc


def http_post_json(
    url: str,
    payload: Any,
    *,
    timeout: float = 10.0,
    referer: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    cookie: str = "",
    proxy: str = "",
    max_bytes: int | None = None,
) -> Any:
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Accept-Encoding": "gzip",
    }
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urlrequest.Request(url, data=body, headers=headers, method="POST")
    effective_max = DEFAULT_MAX_BYTES if max_bytes is None else int(max_bytes)
    try:
        with _build_opener(proxy).open(request, timeout=timeout) as response:
            if effective_max > 0:
                raw = _read_capped(response, url, effective_max)
            else:
                raw = response.read()
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except ParseHttpError:
        raise
    except HTTPError as exc:
        # POST 的 4xx/5xx 不是"可重试的网络失败"：状态码与 Retry-After
        # 必须透传，避免上层把 429/4xx 误判成通用异常而盲目重试。
        raise _http_error_to_parse_error("POST", url, exc) from exc
    except Exception as exc:
        raise ParseHttpError(f"POST {url} failed: {type(exc).__name__}") from exc


class _GuardedShortLinkRedirectHandler(urlrequest.HTTPRedirectHandler):
    """短链 30x 重定向逐跳 SSRF 校验（安全审查 F-05，Critical）。

    urllib 默认 opener 自动跟随 30x，逐跳落点不再过任何校验——短链
    （b23.tv / xhslink.com / v.douyin.com / 163cn.tv 等）30x 指向内网或
    云元数据地址时，请求已发进内网才返回。参照
    ``capabilities/media_archive.py`` 的 ``_GuardedRedirectHandler`` 先例
    （下载链逐跳校验），这里在每一跳落点先过 ssrf_guard 判定：
    ``check_fetch_landing`` 采用 F-04 新语义「解析失败=拒绝」——命中
    私网/黑名单/整型 IP/畸形 URL/DNS 解析失败一律就地抛 ParseHttpError
    中止，请求绝不发向内网；仅确定性公网落点（及护栏自身崩溃的
    fail-open）照旧跟随。

    跳数上限：urllib 默认 ``max_redirections=10``，审查 F-05 要求显式
    ≤5，收紧为 5；超限后 urllib 抛 HTTPError，经 ``resolve_short_link``
    既有 HTTPError→ParseHttpError 错误路径降级，不新增调用方分支。

    局部导入防环：ssrf_guard 顶层 import 了本模块的 ParseHttpError，
    不能在本模块顶层反向导入；函数内导入每次都解析模块属性，测试
    monkeypatch ssrf_guard.check_fetch_landing 即可生效。
    """

    # 审查 F-05：显式跳数上限（urllib 默认 10 → 收紧到 5）。
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from plugins.bot_unified_runtime.sources.parsers.ssrf_guard import (
            check_fetch_landing,
        )

        check_fetch_landing(str(newurl), req.full_url)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def resolve_short_link(url: str, *, timeout: float = 10.0) -> str:
    """跟随重定向拿最终落点 URL（B 站 b23.tv、小红书 xhslink 等）。

    只关心落点：不读响应体，拿到最终 geturl() 即返回。重定向走
    ``_GuardedShortLinkRedirectHandler`` 逐跳 SSRF 校验（审查 F-05）：
    每一跳 30x 落点先过 ssrf_guard 判定（F-04 语义「解析失败=拒绝」），
    命中内网/黑名单/整型 IP 时抛 ParseHttpError，消息带「SSRF guard」
    可判别标记，调用方按既有解析失败路径降级——返回契约
    ``(落点 URL 字符串 / 抛 ParseHttpError)`` 与修复前零变化。
    """
    try:
        with _build_opener(
            extra_handlers=[_GuardedShortLinkRedirectHandler()]
        ).open(_build_request(url), timeout=timeout) as response:
            return response.geturl()
    except ParseHttpError:
        # SSRF 护栏拒绝（F-05 逐跳校验）已带可判别标记，原样上抛，
        # 不被下方通用 except 重新包装丢失语义。
        raise
    except HTTPError as exc:
        raise _http_error_to_parse_error("GET", url, exc) from exc
    except Exception as exc:
        raise ParseHttpError(f"GET {url} failed: {type(exc).__name__}") from exc


def http_post_form(
    url: str,
    data: dict | None = None,
    *,
    timeout: float = 10.0,
    referer: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    cookie: str = "",
    proxy: str = "",
    max_bytes: int | None = None,
) -> Any:
    """POST 表单（application/x-www-form-urlencoded）并解析 JSON 响应。"""
    body = urlparse.urlencode(data or {})
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        "Accept-Encoding": "gzip",
    }
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    request = urlrequest.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
    effective_max = DEFAULT_MAX_BYTES if max_bytes is None else int(max_bytes)
    try:
        with _build_opener(proxy).open(request, timeout=timeout) as response:
            if effective_max > 0:
                raw = _read_capped(response, url, effective_max)
            else:
                raw = response.read()
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except ParseHttpError:
        raise
    except HTTPError as exc:
        raise _http_error_to_parse_error("POST", url, exc) from exc
    except Exception as exc:
        raise ParseHttpError(f"POST {url} failed: {type(exc).__name__}") from exc

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

from plugins.bot_unified_runtime.domains.link_parse.parsers.cookies import (
    PLATFORM_COOKIE_DOMAINS,
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 响应体默认上限：所有 http_get*/http_post* 默认生效（max_bytes=None 时），
# 防止异常响应/恶意大文件撑爆内存。覆盖本仓库全部平台的 HTML/JSON/API
# 响应（最大为油管 watch 页与小红书 INITIAL_STATE，均在 3MB 量级）。
# max_bytes 三值语义的唯一真身见下方 ``_effective_max_bytes``（审查票4 收口，
# 0/负数＝不限制＝显式退出大小护栏，绝非「拒绝一切」；本仓无「0=拒绝」语义）。
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


# ---------------------------------------------------------------------------
# WP1：附凭证前的目标域校验（统一咽喉）
#
# 审计 D5-01 / E2-N14 / E1-2：无锚定子串匹配让「凭证随错误 host 出站」，
# urllib 跨 host 重定向又不剥 Cookie。此处在唯一咽喉（本模块的初始请求
# 构造 + 默认重定向 handler）根修，绝不在 12 个解析器各写一遍。
#
# 域集唯一真身 = cookies.PLATFORM_COOKIE_DOMAINS（扩表，非另建）：
#   - PlatformCookie（provider 产出）携带本平台窄域 → 窄域校验；
#   - 普通 str Cookie（steam/epic 自读兜底）→ 回退联合域校验。
# 校验失败 = 剥 Cookie 后继续（降级未登录），绝不抛错、绝不拒解析。
# ---------------------------------------------------------------------------

_COOKIE_DOMAIN_UNION: tuple[str, ...] = tuple(
    sorted({dom for domains, _keys in PLATFORM_COOKIE_DOMAINS.values() for dom in domains})
)

# 重定向跨 host 时必须剥除的凭证头（大小写不敏感）。
_CREDENTIAL_HEADER_NAMES = ("cookie", "authorization", "proxy-authorization")


def _host_matches_domain(host: str, domain: str) -> bool:
    """后缀语义：www.bilibili.com 归入 .bilibili.com；裸域自配；不误伤 evilbilibili.com。"""
    host = (host or "").strip().lower().rstrip(".")
    dom = (domain or "").strip().lower().lstrip(".").rstrip(".")
    if not host or not dom:
        return False
    return host == dom or host.endswith("." + dom)


def _url_host(url: str) -> str:
    try:
        return (urlparse.urlsplit(url or "").hostname or "").strip().lower()
    except ValueError:
        return ""


def credentials_allowed_for_target(cookie: Any, url: str) -> bool:
    """判定 cookie 是否允许发往 url 的目标 host（窄域优先，普通 str 走联合域）。"""
    if not cookie:
        return True  # 无凭证：不涉及归属判定，放行（本就不带 Cookie 头）。
    domains = getattr(cookie, "cookie_domains", None)
    allowed = tuple(domains) if domains else _COOKIE_DOMAIN_UNION
    host = _url_host(url)
    if not host:
        return False  # 无法确证目标 host：保守判定为不允许。
    return any(_host_matches_domain(host, dom) for dom in allowed)


def scrub_credentials_for_target(cookie: Any, url: str) -> str:
    """① 咽喉核心：返回允许带出的 Cookie 头（明文 str）；不归属返回 ''。"""
    if not cookie:
        return ""
    if credentials_allowed_for_target(cookie, url):
        return str(cookie)
    return ""


def _apply_cookie_guard(headers: dict[str, str], url: str, cookie: Any) -> None:
    """把（可能带归属的）cookie 经咽喉过滤后写入 headers；被剥则不写 Cookie 头。"""
    allowed = scrub_credentials_for_target(cookie, url)
    if allowed:
        headers["Cookie"] = allowed


def _strip_credential_headers(request: urlrequest.Request) -> None:
    """跨 host 重定向后：从初始/未重定向两个头桶里删除凭证头（就地）。"""
    for store in (
        getattr(request, "headers", None),
        getattr(request, "unredirected_hdrs", None),
    ):
        if not isinstance(store, dict):
            continue
        for key in [k for k in store if str(k).lower() in _CREDENTIAL_HEADER_NAMES]:
            store.pop(key, None)


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
    # WP1 ②：默认装上跨 host 剥凭证 handler（覆盖所有走 http_get 的解析器）。
    # 仅当调用方没自带 HTTPRedirectHandler 子类时补装，避免双 redirect handler；
    # build_opener 以 isinstance 判定，本类是 HTTPRedirectHandler 子类即顶替默认。
    has_redirect_handler = any(
        isinstance(h, urlrequest.HTTPRedirectHandler) for h in (extra_handlers or [])
    )
    if not has_redirect_handler:
        handlers.append(_CredentialScrubbingRedirectHandler())
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
        _apply_cookie_guard(headers, url, cookie)
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


def _effective_max_bytes(max_bytes: int | None) -> int:
    """响应体大小上限语义的唯一真身（审查票4 收口，此前散在 3 个出站函数）。

    三值口径：
    - ``None`` → 默认上限 ``DEFAULT_MAX_BYTES``（大小护栏默认生效）；
    - 正整数 → 该上限（大小护栏生效）；
    - ``0`` / 负数 → **不限制**（归一返回 ``0``）：这是调用方对大小护栏的
      **显式退出**，**不是**「拒绝一切」。本仓不存在「0=拒绝」语义，需要限制
      就传正整数或 ``None``，需要显式退出才传 0。

    审读取今日 ACTUAL 语义即「0/负＝不限制」（原注释与 ``if effective_max>0``
    分支本已一致，票4 的只是「0 直觉易被误读为空/拒绝」的语义模糊，非代码矛盾）。
    收口为单一真身以消除三处复制漂移；负数与 0 归一为同一真值 ``0``（行为不变，
    二者此前都落入 ``else`` 不限制分支）。全仓零调用方今日显式传 0/负（见锁测试
    ``test_no_caller_sets_http_throat_max_bytes_non_positive``），故此定版零行为变更。
    """
    if max_bytes is None:
        return DEFAULT_MAX_BYTES
    value = int(max_bytes)
    return max(0, value)


def _read_response_body(response: Any, url: str, effective_max: int) -> bytes:
    """单一读取真身（GET / POST-json / POST-form 三处同形，防漂移）。

    正上限 → ``_read_capped``（限幅读 + 限幅 gzip 解压，防 gzip 炸弹）；
    ``0``（不限制）→ 全量 ``read()`` + 全量 ``gzip.decompress``——调用方显式
    退出大小护栏后的后果由其自负，此路径无大小护栏。
    """
    if effective_max > 0:
        return _read_capped(response, url, effective_max)
    payload = response.read()
    if response.headers.get("Content-Encoding", "").lower() == "gzip":
        payload = gzip.decompress(payload)
    return payload


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

    max_bytes 语义单一真身见 ``_effective_max_bytes``：默认取
    ``DEFAULT_MAX_BYTES``（默认生效）；传 0/负＝不限制（显式退出大小护栏）。
    429 按 Retry-After 有界重试（最多 2 次），
    其余 4xx 立即失败不重试（出处见 ``_retry_delay_seconds`` 注释）。
    """
    effective_max = _effective_max_bytes(max_bytes)
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
                payload = _read_response_body(response, url, effective_max)
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
    _apply_cookie_guard(headers, url, cookie)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urlrequest.Request(url, data=body, headers=headers, method="POST")
    effective_max = _effective_max_bytes(max_bytes)
    try:
        with _build_opener(proxy).open(request, timeout=timeout) as response:
            raw = _read_response_body(response, url, effective_max)
            return json.loads(raw.decode("utf-8"))
    except ParseHttpError:
        raise
    except HTTPError as exc:
        # POST 的 4xx/5xx 不是"可重试的网络失败"：状态码与 Retry-After
        # 必须透传，避免上层把 429/4xx 误判成通用异常而盲目重试。
        raise _http_error_to_parse_error("POST", url, exc) from exc
    except Exception as exc:
        raise ParseHttpError(f"POST {url} failed: {type(exc).__name__}") from exc


class _CredentialScrubbingRedirectHandler(urlrequest.HTTPRedirectHandler):
    """WP1 ②：跨 host 30x 重定向剥除 Cookie/Authorization（urllib 语义缺口根修）。

    实证：urllib 默认 ``redirect_request`` 只剥 content-length/content-type，
    跨 host 跳转时把初始请求的 Cookie 原样带进下一跳（浏览器语义会剥、urllib
    不剥）。故 30x 落点换 host 即成凭证外泄跳道。本 handler 在 super() 造出
    重定向请求后，比较「初始请求 host」与「落点 host」：不同则就地删凭证头。
    同 host（站内跳转）不动，误剥会毁掉正常登录态续跳。

    经 ``_build_opener`` 默认装上（本类是 HTTPRedirectHandler 子类，
    build_opener 以 isinstance 顶替默认，不产生双 handler）。
    """

    # 与短链护栏同口径的显式跳数上限（urllib 默认 10 → 收紧到 5）。
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_request is not None:
            orig_host = _url_host(getattr(req, "full_url", "") or "")
            dest_host = _url_host(getattr(new_request, "full_url", "") or str(newurl))
            if orig_host != dest_host:
                _strip_credential_headers(new_request)
        return new_request


class _GuardedShortLinkRedirectHandler(_CredentialScrubbingRedirectHandler):
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
        from plugins.bot_unified_runtime.domains.link_parse.parsers.ssrf_guard import (
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
    _apply_cookie_guard(headers, url, cookie)
    request = urlrequest.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
    effective_max = _effective_max_bytes(max_bytes)
    try:
        with _build_opener(proxy).open(request, timeout=timeout) as response:
            raw = _read_response_body(response, url, effective_max)
            return json.loads(raw.decode("utf-8"))
    except ParseHttpError:
        raise
    except HTTPError as exc:
        raise _http_error_to_parse_error("POST", url, exc) from exc
    except Exception as exc:
        raise ParseHttpError(f"POST {url} failed: {type(exc).__name__}") from exc

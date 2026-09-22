"""链接解析链的 SSRF 护栏（安全审计 I-2 修复，2026-09-14；F-04 收口）。

用户贴出的 URL 在两处收口，护栏本体只读复用
``sources/downloader.check_download_url``（scheme 白名单 + 主机黑名单 +
字面量 IP 判定 + 全部 DNS 解析结果内网判定）：

- 入口：``guard_user_url``，capabilities/content_parser 在分发解析前调用；
- 落点：``check_fetch_landing``，platforms_generic 的 og 兜底抓取拿到
  「最终 URL」（重定向后的 geturl）后、解析回显内容之前调用，
  对齐 capabilities/notes.py 的「入口 + geturl 双查」范式。

只拦「用户可控 URL」；解析器内部访问的固定 API host（微博/B站接口等）
不经这两处。拒绝行为：返回原因 / 抛 ParseHttpError，一律走既有解析
失败降级路径，绝不回显内网响应内容。

安全语义（审查 F-04）：**解析失败=拒绝，绝不放行**。DNS 解析失败、
无 host、畸形 URL（连 urlsplit/端口都过不了）一律拒绝——拒绝的代价
只是少解析一条链接，放行的代价可能是内网请求与回显。旧版对
``__cause__`` 为 OSError 的拒绝放行（给纯代理可达平台让路），被 F-04
判为 Critical 缺口：十进制/十六进制整型 IP、rebind 域名恰好借这条
路径穿透入口。唯一允许的 fail-open 是护栏自身意外崩溃，且必须记
WARNING。整型 IP（inet_aton 语义：十进制/十六进制/八进制）先归一化
成点分十进制，再走既有私网段判定。

已知残余（登记不堵）：
- 重定向属事后复查（与 notes.py 同源）：抓取已发出，拦的是「内网内容
  进卡回显」，不是内网请求本身；彻底收敛需连接级逐跳校验。
- DNS rebind（TOCTOU）：护栏解析时解析到公网、真实抓取时再解析到内网
  的窗口无法在入口根除；og 兜底链的落点复查仍能拦住回显。
  （F-04 前登记的「DNS 解析失败放行」缺口已改判：解析失败=拒绝。）
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
)


class _MalformedUrlError(ValueError):
    """URL 形态本身无法安全解析（连 urlsplit/端口都过不了）→ 按拒绝处理。

    审查 F-04：畸形 URL 不允许滑进「护栏崩溃 fail-open」通道，必须在
    归一化阶段就以「解析失败=拒绝」拦下。
    """


def _parse_inet_aton_integer(host: str) -> int | None:
    """按 inet_aton 语义解析整型主机名 → 整数值；非整型形态返回 None。

    ``http://2130706433/``（十进制）、``0x7f000001``（十六进制）、
    ``017700000001``（前导 0 = 八进制）都会被常见 HTTP 客户端直接按
    整数 IP 连接，但 ``ipaddress`` 与部分系统解析器不认——旧版这些形态
    滑进「DNS 失败→放行」缺口（F-04）。只认 ASCII 数字/0x 十六进制，
    防 Unicode 数字混入。
    """
    lowered = host.lower()
    if lowered.startswith("0x"):
        body = lowered[2:]
        if not body or not body.isascii() or not all(c in "0123456789abcdef" for c in body):
            return None
        return int(body, 16)
    if host.isascii() and host.isdigit():
        # inet_aton 语义：前导 0 的纯数字按八进制解析（0177…=127.0.0.1）。
        if len(host) > 1 and host.startswith("0"):
            try:
                return int(host, 8)
            except ValueError:
                return None
        return int(host, 10)
    return None


def _normalize_integer_ip_host(url: str) -> str:
    """把整型 IP 形态的 URL 归一化为点分十进制；其余原样返回。

    归一化成功后交给 ``check_download_url`` 走既有字面量私网段判定，
    不再依赖各平台 DNS 解析器对整型形态的行为差异（解析成功也可能
    返回 127.0.0.1，解析失败旧版会放行——正是 F-04 缺口）。超出 IPv4
    值域的纯数字主机名不是 IP，交回原 URL 走 DNS 路径（新语义下解析
    失败同样=拒绝）。畸形 URL 抛 ``_MalformedUrlError``。
    """
    from urllib.parse import urlsplit, urlunsplit

    text = (url or "").strip()
    if not text:
        raise _MalformedUrlError("地址为空")
    try:
        parts = urlsplit(text)
        # 访问 port 属性即校验：非法端口（http://host:abc/）会抛 ValueError，
        # 必须归入「解析失败=拒绝」，不允许滑进护栏崩溃 fail-open（F-04）。
        _port_probe = parts.port
    except ValueError as exc:
        raise _MalformedUrlError(f"urlsplit/端口解析失败: {exc}") from exc
    host = (parts.hostname or "").strip()
    if not host or ":" in host:
        # 无 host 交 check_download_url 拒绝；IPv6 字面量不在此处理。
        return text
    value = _parse_inet_aton_integer(host)
    if value is None or value > 0xFFFFFFFF:
        return text
    import ipaddress

    dotted = str(ipaddress.IPv4Address(value))
    # 只换 host，保留 userinfo/端口/路径/查询串。
    netloc = parts.netloc
    at = netloc.rfind("@")
    userinfo = netloc[: at + 1] if at != -1 else ""
    hostport = netloc[at + 1 :]
    colon = hostport.rfind(":")
    port_part = hostport[colon:] if colon != -1 else ""
    return urlunsplit(
        (parts.scheme, userinfo + dotted + port_part, parts.path, parts.query, parts.fragment)
    )


def _rejection_reason(url: str, *, where: str) -> str | None:
    """check_download_url 包装：拒绝返回原因，放行返回 None。

    安全语义（审查 F-04）：解析失败=拒绝，绝不放行——DNS 解析失败
    （``RejectedUrlError.__cause__`` 为 OSError）、无 host、畸形 URL
    一律返回拒绝原因，走调用方既有的「解析失败」降级路径。返回 None
    仅代表两种情况：①确定性判定为公网（离线可判定，不依赖 DNS 行为）；
    ②护栏自身意外崩溃（非 RejectedUrlError 异常）时的 fail-open，
    必须记 WARNING——这是全文件唯一允许的放行例外。
    """
    import logging

    from plugins.bot_unified_runtime.domains.files.sources.downloader import (
        RejectedUrlError,
        check_download_url,
    )

    try:
        candidate = _normalize_integer_ip_host(url)
    except _MalformedUrlError as exc:
        logging.getLogger(__name__).info(
            "parse SSRF guard rejected (%s): malformed url: %s", where, exc
        )
        return f"URL 无法解析，已拒绝（{exc}）"
    try:
        check_download_url(candidate)
    except RejectedUrlError as exc:
        # F-04：不再按 __cause__ 是否 OSError 区分——解析失败=拒绝。
        logging.getLogger(__name__).info(
            "parse SSRF guard rejected (%s): reason=%s", where, exc
        )
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        # 护栏自身崩溃是唯一允许的 fail-open（本文件唯一例外，F-04 裁定），
        # 必须 WARNING 留痕，便于发现护栏 bug。
        logging.getLogger(__name__).warning(
            "parse SSRF guard crashed (%s), fail-open: %r", where, exc
        )
        return None
    return None


def guard_user_url(url: str) -> str | None:
    """入口护栏：用户可控 URL 分发解析前的内网/保留网段校验。

    命中拒绝返回原因字符串（调用方走既有解析失败降级并记审计标签）；
    返回 None 仅代表「确定性判定为公网」或护栏崩溃 fail-open（记
    WARNING）。解析失败/异常 IP 形态一律拒绝，绝不放行（审查 F-04）。
    """
    return _rejection_reason(url, where="parse-entry")


def check_fetch_landing(final_url: str, original_url: str) -> None:
    """落点复查：重定向后的最终 URL 命中内网即抛 ParseHttpError。

    在解析/回显响应内容之前调用，保证内网内容不进卡片；调用方已有的
    ParseHttpError 处理分支即降级路径，无需新增分支。同样适用
    「解析失败=拒绝」语义（F-04）：无法确证落点公网（含解析失败、
    整型 IP、目标为空）一律抛错，不放行内容回显。
    """
    target = (final_url or original_url or "").strip()
    if not target:
        raise ParseHttpError("fetch landing blocked by SSRF guard: 目标 URL 为空")
    reason = _rejection_reason(target, where="fetch-landing")
    if reason is not None:
        raise ParseHttpError(f"fetch landing blocked by SSRF guard: {reason}")

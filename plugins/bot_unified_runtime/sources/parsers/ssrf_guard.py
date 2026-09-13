"""链接解析链的 SSRF 护栏（安全审计 I-2 修复，2026-09-14）。

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

已知残余（登记不堵）：
- 重定向属事后复查（与 notes.py 同源）：抓取已发出，拦的是「内网内容
  进卡回显」，不是内网请求本身；彻底收敛需连接级逐跳校验。
- DNS 失败放行带来的 rebind 窗口：攻击者自控域名首次查询 NXDOMAIN、
  抓取时解析到内网可穿过入口护栏；落点复查在 og 兜底链仍能拦住回显。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError


def _rejection_reason(url: str, *, where: str) -> str | None:
    """check_download_url 包装：拒绝返回原因，放行返回 None。

    DNS 解析失败（``RejectedUrlError.__cause__`` 为 OSError）时放行：
    纯代理可达平台（油管/推特等）本机 DNS 可能查不到，硬拒会误伤正常
    解析；这类链接后续真实抓取同样会失败，走既有 ParseHttpError 降级。
    其余拒绝（内网/保留网段、localhost/metadata 主机名、非 http(s)）
    不依赖 DNS，离线可确定判定。
    """
    import logging

    from plugins.bot_unified_runtime.sources.downloader import (
        RejectedUrlError,
        check_download_url,
    )

    try:
        check_download_url(url)
    except RejectedUrlError as exc:
        if isinstance(exc.__cause__, OSError):
            return None
        logging.getLogger(__name__).info(
            "parse SSRF guard rejected (%s): reason=%s", where, exc
        )
        return str(exc)
    return None


def guard_user_url(url: str) -> str | None:
    """入口护栏：用户可控 URL 分发解析前的内网/保留网段校验。

    命中拒绝返回原因字符串（调用方走既有解析失败降级并记审计标签）；
    放行返回 None。
    """
    return _rejection_reason(url, where="parse-entry")


def check_fetch_landing(final_url: str, original_url: str) -> None:
    """落点复查：重定向后的最终 URL 命中内网即抛 ParseHttpError。

    在解析/回显响应内容之前调用，保证内网内容不进卡片；调用方已有的
    ParseHttpError 处理分支即降级路径，无需新增分支。
    """
    target = (final_url or original_url or "").strip()
    if not target:
        return
    reason = _rejection_reason(target, where="fetch-landing")
    if reason is not None:
        raise ParseHttpError(f"fetch landing blocked by SSRF guard: {reason}")

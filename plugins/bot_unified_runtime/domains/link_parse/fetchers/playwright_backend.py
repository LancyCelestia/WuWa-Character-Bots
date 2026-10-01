"""基于 Playwright 的同步抓取后端。

能力层会把这类慢请求 offload；本模块只提供最小同步接口：

- ``fetch_html``：无头 Chromium 打开页面，返回 (final_url, html)。
- ``capture_json``：监听导航期间的 XHR 响应，收集匹配的 JSON 载荷。
- ``render_check``：给诊断命令用的可用性报告。

所有内部异常统一包装成 ``ParseHttpError``，不向调用链之外泄漏浏览器
异常文本；``finally`` 中关闭 browser 与 playwright。

SSRF 闸（INCIDENT-20260930 第五节 · 缺口③，2026-09-30 复原波）：这两条腿此前是全
解析链上唯一没过中央咽喉的出站口——用户贴一条 ``http://127.0.0.1:3001/``
（SnowLuma 控制面）或 ``http://169.254.169.254/``（云元数据）就能让 bot 用本机
Chromium 去连，``capture_json`` 还会把命中的响应 body 收进解析链回显进卡。现在
①两处 ``page.goto`` **之前**过入口护栏 ``ssrf_guard.guard_user_url``（判据＝中央
``downloader.check_download_url``，F-04「解析失败=拒绝」），内网地址连浏览器都不启动；
②导航落点（``page.url``）与被截获的 XHR 响应 URL，在**取 body / 交回内容之前**再过
落点复查（对齐解析链「入口 + geturl 双查」范式）。拒绝一律 ``ParseHttpError``：
调用方（platforms_generic / platforms_kurobbs / xhs 订阅适配器）既有 ``except`` 分支
就是降级通路（回落 og 浅解析 → 纯文本卡），不新增异常面。

已知边界（如实登记，不硬做）：**Chromium 内部的中间跳转与页内子资源请求**由浏览器
自己的网络栈完成，本层拿不到逐跳落点——彻底收敛要挂 ``page.route`` 传输层拦截并
对每条子资源做一次 Python 回调（同族问题见渲染腿 ``_orb_route``），代价与风险都比
这一格的收益大。现存的「入口不建连 + 落点不回显 + 载荷不取 body」三道，加上调用方
对派生 URL 的复查，构成这条腿当前的判定面。
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
)

logger = logging.getLogger(__name__)

# 可选依赖：playwright 未安装时模块仍可导入，但后端显式不可用。
try:
    from playwright.sync_api import sync_playwright
except Exception:  # noqa: BLE001
    sync_playwright = None  # type: ignore[assignment]


def _guard_navigation_target(url: str, *, where: str) -> None:
    """``page.goto`` 前置入口闸：被拒即抛 ``ParseHttpError``（Chromium 都不启动）。

    判据现取 ``ssrf_guard``（模块属性 lookup，非顶层绑定 import）——单源，本件
    不复制第二套网段表；测试 monkeypatch ``ssrf_guard.guard_user_url`` 即生效。
    """
    from plugins.bot_unified_runtime.domains.link_parse.parsers import ssrf_guard

    reason = ssrf_guard.guard_user_url(str(url or ""))
    if reason is not None:
        raise ParseHttpError(
            f"playwright goto blocked by SSRF guard ({where}): {reason}"
        )


def _guard_navigation_landing(landing: str, original_url: str) -> str:
    """导航落点复查：内网/畸形落点不许把内容交回解析链（``page.content()`` 之前）。

    直接复用解析链既有的落点咽喉 ``ssrf_guard.check_fetch_landing``（它自己抛
    ``ParseHttpError`` 并带「SSRF guard」可判别标记），本件不写第二套判定与异常。
    """
    from plugins.bot_unified_runtime.domains.link_parse.parsers.ssrf_guard import (
        check_fetch_landing,
    )

    target = str(landing or "")
    check_fetch_landing(target, original_url)
    return target or str(original_url or "")


def _guard_response_target(url: str) -> bool:
    """XHR 响应腿：落点过不了咽喉就**连 body 都不取**（回显面为零）。"""
    from plugins.bot_unified_runtime.domains.link_parse.parsers import ssrf_guard

    return ssrf_guard.guard_user_url(url) is None


def _target_host(url: str) -> str:
    """只取主机名进日志（签名/路径一律不落日志）。"""
    from urllib.parse import urlsplit

    try:
        return urlsplit(str(url or "")).hostname or ""
    except ValueError:
        return ""


def _close_runtime(browser: Any, playwright: Any) -> None:
    """尽力关闭 browser / playwright，关闭失败不影响原异常。"""
    if browser is not None:
        try:
            browser.close()
        except Exception:  # noqa: BLE001, S110 - 关闭失败尽力忽略，不影响主流程。
            pass
    if playwright is not None:
        try:
            playwright.stop()
        except Exception:  # noqa: BLE001, S110 - 停止失败尽力忽略，不影响主流程。
            pass


class PlaywrightFetchBackend:
    """Playwright（Chromium 无头）同步抓取后端。"""

    @property
    def available(self) -> bool:
        try:
            import playwright.sync_api  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def fetch_html(
        self,
        url: str,
        *,
        cookies: list[dict] | None = None,
        timeout_ms: int = 30000,
        wait_until: str = "domcontentloaded",
    ) -> tuple[str, str]:
        """打开页面并返回 (final_url, html)。"""
        browser = None
        playwright = None
        try:
            _guard_navigation_target(url, where="fetch-html")
            if sync_playwright is None:
                raise ParseHttpError("playwright 后端不可用")
            pw = sync_playwright()
            # 真实 playwright：sync_playwright() 返回 context manager，需 .start() 才有 .chromium。
            playwright = cast(Any, pw.start()) if hasattr(pw, "start") else cast(Any, pw)
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            if cookies:
                context.add_cookies(cast(Any, list(cookies)))
            page = context.new_page()
            page.goto(url, wait_until=cast(Any, wait_until), timeout=timeout_ms)
            # 落点复查在取内容之前：跳转把文档带进内网时，一个字节的 html 都不许
            # 交回解析链（platforms_generic 的 P2-12 复查同款，此处提前一道）。
            landing = _guard_navigation_landing(str(page.url or ""), url)
            html = page.content()
            return landing, html
        except ParseHttpError:
            raise
        except Exception:  # noqa: BLE001 - 统一包装，不泄漏内部异常文本。
            raise ParseHttpError("playwright 抓取页面失败") from None
        finally:
            _close_runtime(browser, playwright)

    def capture_json(
        self,
        url: str,
        *,
        cookies: list[dict] | None = None,
        json_filter: str | None = None,
        timeout_ms: int = 30000,
    ) -> list[dict]:
        """导航并收集匹配的 JSON 响应；单条响应解析失败只跳过该条。"""
        collected: list[dict] = []
        browser = None
        playwright = None
        try:
            _guard_navigation_target(url, where="capture-json")
            if sync_playwright is None:
                raise ParseHttpError("playwright 后端不可用")
            pw = sync_playwright()
            # 真实 playwright：sync_playwright() 返回 context manager，需 .start() 才有 .chromium。
            playwright = cast(Any, pw.start()) if hasattr(pw, "start") else cast(Any, pw)
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            if cookies:
                context.add_cookies(cast(Any, list(cookies)))
            page = context.new_page()

            def _on_response(response: Any) -> None:
                try:
                    response_url = str(getattr(response, "url", None) or "")
                    matches_filter = bool(json_filter and json_filter in response_url)
                    if "xhs" not in response_url and not matches_filter:
                        return
                    headers = getattr(response, "headers", None) or {}
                    content_type = str(headers.get("content-type") or "").lower()
                    if "json" not in content_type:
                        return
                    # 中央咽喉先看响应落点：过不了闸的响应连 body 都不取——
                    # 「连得上」已经发生（浏览器网络栈），这里断的是内网字节
                    # 进解析链、进而回显进群卡那一段。
                    if not _guard_response_target(response_url):
                        logger.info(
                            "playwright capture response dropped by SSRF guard: host=%s",
                            _target_host(response_url),
                        )
                        return
                    body = response.body()
                    if isinstance(body, bytes):
                        body = body.decode("utf-8", errors="replace")
                    payload = json.loads(body)
                    if isinstance(payload, dict):
                        collected.append(payload)
                except Exception:  # noqa: BLE001, S110 - 单条响应失败忽略。
                    pass

            page.on("response", _on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # 导航落点复查：跳进内网再截 JSON 的形态，载荷同样不许交回调用方。
            _guard_navigation_landing(str(page.url or ""), url)
            return collected
        except ParseHttpError:
            raise
        except Exception:  # noqa: BLE001 - 统一包装，不泄漏内部异常文本。
            raise ParseHttpError("playwright 抓取接口失败") from None
        finally:
            _close_runtime(browser, playwright)

    def render_check(self) -> dict[str, bool | str]:
        """返回给诊断链路的结构化可用性报告。"""
        if self.available:
            return {"available": True, "reason": "playwright.sync_api 可用"}
        return {"available": False, "reason": "playwright.sync_api 不可用（未安装）"}
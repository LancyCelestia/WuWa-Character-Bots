"""基于 Playwright 的同步抓取后端。

能力层会把这类慢请求 offload；本模块只提供最小同步接口：

- ``fetch_html``：无头 Chromium 打开页面，返回 (final_url, html)。
- ``capture_json``：监听导航期间的 XHR 响应，收集匹配的 JSON 载荷。
- ``render_check``：给诊断命令用的可用性报告。

所有内部异常统一包装成 ``ParseHttpError``，不向调用链之外泄漏浏览器
异常文本；``finally`` 中关闭 browser 与 playwright。
"""

from __future__ import annotations

import json
from typing import Any, cast

from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError

# 可选依赖：playwright 未安装时模块仍可导入，但后端显式不可用。
try:
    from playwright.sync_api import sync_playwright
except Exception:  # noqa: BLE001
    sync_playwright = None  # type: ignore[assignment]


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
            html = page.content()
            return page.url, html
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
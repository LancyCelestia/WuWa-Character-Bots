"""渲染后端接口：HTML→图片、卡片渲染的预留接入点。

- ``RenderBackend`` Protocol：接收结构化卡片 payload，返回图片字节；
  渲染失败必须返回 None（由调用方降级文本），不抛异常。
- ``NullRenderBackend``：默认实现，直接返回 None（文本兜底）。
- ``HtmlKitRenderBackend``：可选实现，依赖 nonebot-plugin-htmlkit /
  Playwright；未安装时自动不可用，不影响主链路。
- ``build_render_backend(name)``：按名字选择；未来可加
  cardimg / PIL / 小程序卡等后端，不改调用方。

后续把游戏 wiki 卡、媒体卡接到 ``render_card`` 时，仍然走
``CapabilityResult -> ReviewResult -> RenderedOutput``，渲染只负责
产图，不决定发送。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class RenderBackend(Protocol):
    name: str
    available: bool

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        """渲染卡片为图片字节；失败返回 None。"""


class NullRenderBackend:
    name = "null"
    available = False

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        return None


class HtmlKitRenderBackend:
    """HTML/Markdown → 图片（需要 htmlkit + Playwright 浏览器）。"""

    name = "htmlkit"
    available = False
    _html_to_pic: Any = None

    def __init__(self) -> None:
        try:
            from nonebot_plugin_htmlkit import html_to_pic  # type: ignore

            self._html_to_pic = html_to_pic
            self.available = True
        except Exception:  # noqa: BLE001 - htmlkit 不可用时标记为不可用，不抛出。
            self.available = False

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        if not self.available:
            return None
        html = payload.get("html")
        if not isinstance(html, str) or not html.strip():
            return None
        try:
            result = self._html_to_pic(
                html,
                viewport=payload.get("viewport") or {"width": 640, "height": 400},
            )
        except Exception:  # noqa: BLE001 - htmlkit 渲染失败按无结果降级。
            return None
        if isinstance(result, bytes):
            return result
        if isinstance(result, (str, Path)):
            try:
                return Path(result).read_bytes()
            except OSError:
                return None
        return None


class PlaywrightRenderBackend:
    """HTML → PNG 图片（直接依赖 playwright + chromium，不依赖 htmlkit）。

    浏览器生命周期借鉴 nonebot-plugin-htmlrender 的常驻模式：懒启动、
    跨渲染复用、信号量限并发、崩溃自动重启——避免每张卡片都付出
    Chromium 冷启动开销（订阅批量推送时尤其明显）。
    线程安全：playwright 的 sync API 必须与事件循环隔离开，调用方应
    在 to_thread 里执行（能力层已 offload）。
    """

    name = "playwright"
    available = False

    def __init__(self, *, max_concurrency: int = 2) -> None:
        import threading

        # sync playwright 非线程安全且对象线程绑定：渲染全程持大锁串行，
        # 常驻浏览器按线程存放（help/卡片渲染可能来自不同工作线程，
        # 各线程复用各自的常驻实例，仍消除冷启动）。
        self._lock = threading.Lock()
        self._local = threading.local()
        self._max_concurrency = max(1, int(max_concurrency))
        try:
            from playwright.sync_api import sync_playwright  # type: ignore

            self._sync_playwright: Any = sync_playwright
            self.available = True
        except Exception:  # noqa: BLE001 - Playwright 不可用时标记为不可用，不抛出。
            self._sync_playwright = None
            self.available = False

    def _thread_browser(self) -> tuple[Any, Any]:
        browser = getattr(self._local, "browser", None)
        ctx = getattr(self._local, "playwright_ctx", None)
        return browser, ctx

    def _get_browser(self) -> Any:
        """懒启动并复用本线程的常驻 Chromium；浏览器已死则重启一次。"""
        browser, _ctx = self._thread_browser()
        if browser is not None and browser.is_connected():
            return browser
        self._close_thread_browser()
        playwright_ctx = self._sync_playwright()
        playwright = playwright_ctx.start()
        browser = playwright.chromium.launch()
        self._local.browser = browser
        self._local.playwright_ctx = playwright_ctx
        return browser

    def _close_thread_browser(self) -> None:
        browser, ctx = self._thread_browser()
        self._local.browser = None
        self._local.playwright_ctx = None
        for resource in (browser, ctx):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception:  # noqa: BLE001, S110 - 关闭失败忽略，下次懒启动重建。
                pass

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        if not self.available or self._sync_playwright is None:
            return None
        html = payload.get("html")
        if not isinstance(html, str) or not html.strip():
            return None
        viewport = payload.get("viewport") or {"width": 672, "height": 480}
        width = int(viewport.get("width", 672))
        height = int(viewport.get("height", 480))
        wait_ms = int(payload.get("wait_ms", 1500))
        try:
            device_scale_factor = int(payload.get("device_scale_factor", 2))
        except (TypeError, ValueError):
            device_scale_factor = 2
        with self._lock:
            try:
                browser = self._get_browser()
                try:
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=device_scale_factor,
                    )
                except Exception:  # noqa: BLE001 - 浏览器崩溃时重启一次再试。
                    browser = self._get_browser()
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=device_scale_factor,
                    )
                try:
                    page.set_content(html, wait_until="networkidle")
                    # 封面清晰度关键：等所有 <img> 真正解码完成（networkidle
                    # 只保证请求静默，大图可能仍在解码）；再兜底固定等待。
                    try:
                        page.wait_for_function(
                            "Array.from(document.images).every(img => img.complete)",
                            timeout=8000,
                        )
                    except Exception:  # noqa: BLE001 - 超时按已加载现状截图。
                        pass
                    page.wait_for_timeout(wait_ms)
                    element = page.query_selector(".card")
                    if element is not None:
                        # 元素截图自带裁切范围，不需要 clip 参数。
                        return bytes(
                            element.screenshot(type="png", omit_background=True)
                        )
                    return bytes(page.screenshot(type="png", full_page=True))
                finally:
                    page.close()
            except Exception:  # noqa: BLE001 - 浏览器渲染失败按无结果降级，并重置常驻浏览器。
                self._close_thread_browser()
                return None

    def close(self) -> None:
        self._close_thread_browser()


def build_render_backend(name: str = "") -> RenderBackend:
    normalized = (name or "").strip().lower()
    if normalized in {"playwright", "htmlkit", "auto"}:
        backend = PlaywrightRenderBackend()
        if backend.available:
            return backend
        if normalized == "htmlkit":
            return HtmlKitRenderBackend()
    return NullRenderBackend()


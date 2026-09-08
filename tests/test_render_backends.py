from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.output.render_backends import (
    NullRenderBackend,
    PlaywrightRenderBackend,
    build_render_backend,
)


class _FakePage:
    def __init__(self) -> None:
        self.closed = False

    def set_content(self, html: str, wait_until: str = "load") -> None:
        assert html

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def query_selector(self, selector: str):
        element = SimpleNamespace()
        element.screenshot = lambda **kwargs: b"png-bytes"
        return element

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self) -> None:
        self.launches = 0
        self.connected = True
        self.pages: list[_FakePage] = []

    def is_connected(self) -> bool:
        return self.connected

    def new_page(self, **kwargs):
        page = _FakePage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.connected = False


class _FakePlaywrightHandle:
    def __init__(self, browser: _FakeBrowser) -> None:
        self._browser = browser
        self.started = 0

    def start(self):
        self.started += 1
        return SimpleNamespace(chromium=SimpleNamespace(launch=lambda: self._browser))

    def close(self) -> None:
        pass


def test_null_backend_returns_none() -> None:
    assert NullRenderBackend().render_card({"html": "<b>x</b>"}) is None


def test_build_backend_unknown_name_falls_to_null() -> None:
    assert isinstance(build_render_backend("nonexistent"), NullRenderBackend)


def test_persistent_browser_reused_across_renders() -> None:
    backend = PlaywrightRenderBackend.__new__(PlaywrightRenderBackend)
    import threading

    backend.name = "playwright"
    backend.available = True
    backend._lock = threading.Lock()
    backend._local = threading.local()
    backend._max_concurrency = 1

    browser = _FakeBrowser()
    handle = _FakePlaywrightHandle(browser)
    backend._sync_playwright = lambda: handle

    payload = {"html": "<div class='card'>x</div>", "viewport": {"width": 10, "height": 10}, "wait_ms": 0}
    first = backend.render_card(dict(payload))
    second = backend.render_card(dict(payload))

    assert first == b"png-bytes"
    assert second == b"png-bytes"
    # 关键性能断言：两次渲染只启动一次 Chromium（常驻复用）。
    assert handle.started == 1
    assert all(page.closed for page in browser.pages)


def test_browser_crash_restarts_and_recovers() -> None:
    backend = PlaywrightRenderBackend.__new__(PlaywrightRenderBackend)
    import threading

    backend.name = "playwright"
    backend.available = True
    backend._lock = threading.Lock()
    backend._local = threading.local()
    backend._max_concurrency = 1

    browser = _FakeBrowser()
    handle = _FakePlaywrightHandle(browser)
    backend._sync_playwright = lambda: handle

    payload = {"html": "<div class='card'>x</div>", "viewport": {"width": 10, "height": 10}, "wait_ms": 0}
    assert backend.render_card(dict(payload)) == b"png-bytes"

    # 模拟浏览器进程崩溃：下一次渲染应自动重启并恢复。
    browser.connected = False
    assert backend.render_card(dict(payload)) == b"png-bytes"
    assert handle.started == 2


def test_render_failure_resets_persistent_browser() -> None:
    backend = PlaywrightRenderBackend.__new__(PlaywrightRenderBackend)
    import threading

    backend.name = "playwright"
    backend.available = True
    backend._lock = threading.Lock()
    backend._local = threading.local()
    backend._max_concurrency = 1

    browser = _FakeBrowser()
    handle = _FakePlaywrightHandle(browser)
    backend._sync_playwright = lambda: handle

    bad = {"html": "<div class='card'>x</div>", "viewport": {"width": 10, "height": 10}, "wait_ms": 0}
    assert backend.render_card(dict(bad)) == b"png-bytes"
    # 截图抛异常 → 返回 None 且常驻浏览器被重置。
    def _breaking_new_page(**kwargs):
        page = _FakePage()
        page.query_selector = lambda _sel: (_ for _ in ()).throw(RuntimeError("boom"))
        browser.pages.append(page)
        return page

    browser.new_page = _breaking_new_page  # type: ignore[method-assign]
    assert backend.render_card(dict(bad)) is None
    assert getattr(backend._local, "browser", None) is None

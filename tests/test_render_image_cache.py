"""封面图 LRU 缓存回归（审查 L-07）。

背景：卡片封面/ORB 图每次渲染都回源 ``_fetch_image_bytes``（urlopen），
同一封面 URL 重复渲染重复下载。修复=``render_backends`` 进程内 LRU
（URL→bytes，容量 64 条 + 单条 8MB 上限，超限不缓存只直读；网络失败
不缓存负结果）。本文件全部离线 mock：monkeypatch 模块级 ``_ORB_FETCH_OPENER``
为计数假 opener，绝无真实网络。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Self

import pytest

from plugins.bot_unified_runtime.domains.render import render_backends as rb
from plugins.bot_unified_runtime.output.render_backends import (
    PlaywrightRenderBackend,
)

_IMG_URL = "https://wx1.sinaimg.cn/large/test_cover.jpg"
_IMG_URL_A = "https://wx1.sinaimg.cn/large/a.jpg"
_IMG_URL_B = "https://wx2.sinaimg.cn/large/b.jpg"


class _FakeResponse:
    def __init__(self, payload: bytes, content_type: str = "image/jpeg") -> None:
        self._payload = payload
        self.headers = {"Content-Type": content_type}

    def read(self, n: int = -1) -> bytes:
        return self._payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _CountingOpener:
    """urlopen 替身：按 URL 返回字节或抛异常，并记录全部调用序。"""

    def __init__(self, payloads: dict[str, bytes | Exception]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def open(self, request: object, timeout: float | None = None) -> _FakeResponse:
        url = str(getattr(request, "full_url", request))
        self.calls.append(url)
        payload = self.payloads[url]
        if isinstance(payload, Exception):
            raise payload
        return _FakeResponse(payload)


@pytest.fixture(autouse=True)
def _clean_image_cache():
    """模块级缓存是进程内共享状态：用例前后各清一次，杜绝用例间串扰。"""
    rb._image_bytes_cache_clear()
    yield
    rb._image_bytes_cache_clear()


def test_same_url_second_fetch_hits_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """同 URL 二次取图命中缓存：urlopen 计数=1（L-07 主断言）。"""
    opener = _CountingOpener({_IMG_URL: b"cover-bytes"})
    monkeypatch.setattr(rb, "_ORB_FETCH_OPENER", opener)

    first = rb._fetch_image_bytes(_IMG_URL)
    second = rb._fetch_image_bytes(_IMG_URL)

    assert first == (b"cover-bytes", "image/jpeg")
    assert second == (b"cover-bytes", "image/jpeg")
    assert opener.calls == [_IMG_URL]


def test_different_urls_fetched_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不同 URL 各自回源，互不串缓存。"""
    opener = _CountingOpener({_IMG_URL_A: b"a", _IMG_URL_B: b"b"})
    monkeypatch.setattr(rb, "_ORB_FETCH_OPENER", opener)

    assert rb._fetch_image_bytes(_IMG_URL_A) == (b"a", "image/jpeg")
    assert rb._fetch_image_bytes(_IMG_URL_B) == (b"b", "image/jpeg")
    assert rb._fetch_image_bytes(_IMG_URL_A) == (b"a", "image/jpeg")

    # 第三次取 A 命中缓存：总回源只有两次（A、B 各一次）。
    assert opener.calls == [_IMG_URL_A, _IMG_URL_B]


def test_oversized_entry_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """单条超限不缓存只直读：返回契约不变，但每次都回源。"""
    big = b"x" * 64
    opener = _CountingOpener({_IMG_URL: big})
    monkeypatch.setattr(rb, "_ORB_FETCH_OPENER", opener)
    monkeypatch.setattr(rb, "_IMG_CACHE_MAX_BYTES", 16)

    assert rb._fetch_image_bytes(_IMG_URL) == (big, "image/jpeg")
    assert rb._fetch_image_bytes(_IMG_URL) == (big, "image/jpeg")
    assert opener.calls == [_IMG_URL, _IMG_URL]

    # 边界：恰好等于上限仍缓存。
    edge = b"y" * 16
    opener.payloads[_IMG_URL] = edge
    assert rb._fetch_image_bytes(_IMG_URL) == (edge, "image/jpeg")
    assert rb._fetch_image_bytes(_IMG_URL) == (edge, "image/jpeg")
    assert opener.calls == [_IMG_URL, _IMG_URL, _IMG_URL]


def test_failure_not_cached_then_success_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """失败不缓存负结果（瞬时故障不放大成持续灰图）；成功后恢复缓存。"""
    opener = _CountingOpener({_IMG_URL: OSError("network down")})
    monkeypatch.setattr(rb, "_ORB_FETCH_OPENER", opener)

    assert rb._fetch_image_bytes(_IMG_URL) is None
    assert rb._fetch_image_bytes(_IMG_URL) is None
    assert len(opener.calls) == 2  # 每次失败都重新尝试，不留负缓存

    opener.payloads[_IMG_URL] = b"recovered"
    assert rb._fetch_image_bytes(_IMG_URL) == (b"recovered", "image/jpeg")
    assert rb._fetch_image_bytes(_IMG_URL) == (b"recovered", "image/jpeg")
    assert len(opener.calls) == 3  # 成功一次后第四次取图命中缓存


def test_lru_evicts_oldest_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """容量封顶：最旧条目按插入序淘汰（对齐项目 LRU 惯例）。"""
    urls = [f"https://wx1.sinaimg.cn/large/{i}.jpg" for i in range(3)]
    opener = _CountingOpener({u: u.encode() for u in urls})
    monkeypatch.setattr(rb, "_ORB_FETCH_OPENER", opener)
    monkeypatch.setattr(rb, "_IMG_CACHE_MAX_ENTRIES", 2)

    for url in urls:
        rb._fetch_image_bytes(url)
    assert len(opener.calls) == 3

    rb._fetch_image_bytes(urls[0])  # 0 号最旧已被挤出 → 回源
    rb._fetch_image_bytes(urls[2])  # 2 号仍在池内 → 命中
    assert opener.calls.count(urls[0]) == 2
    assert opener.calls.count(urls[1]) == 1
    assert opener.calls.count(urls[2]) == 1


# ---- render_card 级端到端（ORB 路由两连渲染共享一次回源）----


class _FakeOrbPage:
    """记录 page.route 注册的处理器；其余按 render_card 最小面实现。"""

    def __init__(self) -> None:
        self.route_handlers: list = []
        self.closed = False

    def route(self, pattern: str, handler) -> None:  # 测试替身
        self.route_handlers.append(handler)

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


class _FakeOrbBrowser:
    def __init__(self) -> None:
        self.connected = True
        self.pages: list[_FakeOrbPage] = []

    def is_connected(self) -> bool:
        return self.connected

    def new_page(self, **kwargs):
        page = _FakeOrbPage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.connected = False


class _FakePlaywrightHandle:
    def __init__(self, browser: _FakeOrbBrowser) -> None:
        self._browser = browser
        self.started = 0

    def start(self):
        self.started += 1
        return SimpleNamespace(chromium=SimpleNamespace(launch=lambda: self._browser))

    def close(self) -> None:
        pass


class _FakeRoute:
    def __init__(self, url: str) -> None:
        self.request = SimpleNamespace(resource_type="image", url=url)
        self.fulfilled: dict | None = None
        self.aborted = False
        self.continued = False

    def continue_(self) -> None:
        self.continued = True

    def abort(self) -> None:
        self.aborted = True

    def fulfill(self, **kwargs) -> None:
        self.fulfilled = kwargs


def _make_backend(browser: _FakeOrbBrowser) -> PlaywrightRenderBackend:
    backend = PlaywrightRenderBackend.__new__(PlaywrightRenderBackend)
    backend.name = "playwright"
    backend.available = True
    backend._lock = threading.Lock()
    backend._local = threading.local()
    backend._max_concurrency = 1
    backend._sync_playwright = lambda: _FakePlaywrightHandle(browser)
    return backend


def test_orb_route_second_render_hits_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两次渲染同一封面：ORB 路由各执行一次，回源只有一次（L-07 端到端）。"""
    opener = _CountingOpener({_IMG_URL: b"cover"})
    monkeypatch.setattr(rb, "_ORB_FETCH_OPENER", opener)
    browser = _FakeOrbBrowser()
    backend = _make_backend(browser)

    payload = {
        "html": f"<div class='card'><img src='{_IMG_URL}'></div>",
        "viewport": {"width": 10, "height": 10},
        "wait_ms": 0,
    }
    assert backend.render_card(dict(payload)) == b"png-bytes"
    assert backend.render_card(dict(payload)) == b"png-bytes"

    # 每次渲染注册一次 ORB 路由（常驻浏览器跨页无 HTTP 缓存复用）。
    handlers = [h for page in browser.pages for h in page.route_handlers]
    assert len(handlers) == 2

    route_first, route_second = _FakeRoute(_IMG_URL), _FakeRoute(_IMG_URL)
    handlers[0](route_first)
    handlers[1](route_second)

    assert route_first.fulfilled is not None
    assert route_second.fulfilled is not None
    assert route_first.fulfilled["body"] == b"cover"
    assert route_second.fulfilled["body"] == b"cover"
    assert opener.calls == [_IMG_URL]  # 二次渲染命中缓存，urlopen 计数=1


def test_orb_route_fetch_failure_aborts_and_retries_next_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """失败路径契约零变化：route.abort，且负结果不缓存、下次渲染重试。"""
    opener = _CountingOpener({_IMG_URL: OSError("boom")})
    monkeypatch.setattr(rb, "_ORB_FETCH_OPENER", opener)
    browser = _FakeOrbBrowser()
    backend = _make_backend(browser)

    payload = {
        "html": f"<div class='card'><img src='{_IMG_URL}'></div>",
        "viewport": {"width": 10, "height": 10},
        "wait_ms": 0,
    }
    assert backend.render_card(dict(payload)) == b"png-bytes"

    handlers_first = [h for h in browser.pages[0].route_handlers]
    route_fail = _FakeRoute(_IMG_URL)
    handlers_first[0](route_fail)
    assert route_fail.aborted is True  # 失败 → abort（模板 onerror 兜底）

    # 此时才让源恢复：验证负结果未缓存、第二次渲染真实重试。
    opener.payloads[_IMG_URL] = b"ok-now"
    assert backend.render_card(dict(payload)) == b"png-bytes"

    route_ok = _FakeRoute(_IMG_URL)
    browser.pages[1].route_handlers[0](route_ok)

    assert route_ok.fulfilled is not None
    assert route_ok.fulfilled["body"] == b"ok-now"  # 下次渲染重试成功
    assert opener.calls == [_IMG_URL, _IMG_URL]  # 未被负缓存吞掉第二次尝试

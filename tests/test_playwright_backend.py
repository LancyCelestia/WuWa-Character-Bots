"""PlaywrightFetchBackend 单元测试。

所有用例 monkeypatch ``sync_playwright``，绝不启动真实浏览器；验证同步
抓取后端的两条路径（fetch_html / capture_json）、cookie 注入、JSON 响应
过滤与统一 ParseHttpError 包装。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.sources.fetchers.playwright_backend import (
    PlaywrightFetchBackend,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError

BACKEND_MODULE = "plugins.bot_unified_runtime.sources.fetchers.playwright_backend"


class _FakeResponse:
    def __init__(self, url, *, content_type="application/json", body='{"ok": true}'):
        self.url = url
        self.headers = {"content-type": content_type}
        self._body = body.encode("utf-8")

    def body(self):
        return self._body


class _FakePage:
    def __init__(self, *, final_url="", html="", responses=()):
        self.url = final_url
        self._html = html
        self._responses = list(responses)
        self._response_handler = None
        self.goto_calls = []

    def on(self, event, handler):
        self._response_handler = handler
        return handler

    def goto(self, url, *, wait_until=None, timeout=None):
        self.goto_calls.append(
            {"url": url, "wait_until": wait_until, "timeout": timeout}
        )
        for response in self._responses:
            if self._response_handler is not None:
                self._response_handler(response)
        return _FakeResponse(url, content_type="text/html", body="")

    def content(self):
        return self._html


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.cookies = None

    def add_cookies(self, cookies):
        self.cookies = list(cookies)

    def new_page(self):
        return self._page


class _FakeBrowser:
    def __init__(self, context):
        self._context = context
        self.launch_calls = []
        self.new_context_kwargs = None
        self.close_called = False

    def new_context(self, **kwargs):
        self.new_context_kwargs = kwargs
        return self._context

    def close(self):
        self.close_called = True


class _FakePlaywright:
    def __init__(self, browser):
        self.browser = browser
        self.launch_calls = []
        self.stop_called = False
        self.chromium = SimpleNamespace(launch=self.launch)

    def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        return self.browser

    def stop(self):
        self.stop_called = True


def _install_fake(monkeypatch, **page_kwargs):
    page = _FakePage(**page_kwargs)
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    playwright = _FakePlaywright(browser)
    monkeypatch.setattr(BACKEND_MODULE + ".sync_playwright", lambda: playwright)
    return playwright, browser, context, page


def test_available_and_render_check_are_diagnostic():
    backend = PlaywrightFetchBackend()

    assert backend.available is True
    assert backend.render_check()["available"] is True
    assert isinstance(backend.render_check()["reason"], str)


def test_fetch_html_returns_final_url_and_injects_cookies(monkeypatch):
    playwright, browser, context, page = _install_fake(
        monkeypatch,
        final_url="https://www.xiaohongshu.com/user/profile/abc123?x=1",
        html="<html><body>profile</body></html>",
    )
    backend = PlaywrightFetchBackend()
    cookies = [
        {"name": "web_session", "value": "x", "domain": ".xiaohongshu.com", "path": "/"},
        {"name": "a1", "value": "y", "domain": ".xiaohongshu.com", "path": "/"},
    ]

    final_url, html = backend.fetch_html(
        "https://www.xiaohongshu.com/user/profile/abc123",
        cookies=cookies,
        wait_until="load",
        timeout_ms=5000,
    )

    assert final_url == "https://www.xiaohongshu.com/user/profile/abc123?x=1"
    assert html == "<html><body>profile</body></html>"
    assert context.cookies == cookies
    assert playwright.launch_calls == [{"headless": True}]
    assert page.goto_calls == [
        {
            "url": "https://www.xiaohongshu.com/user/profile/abc123",
            "wait_until": "load",
            "timeout": 5000,
        }
    ]
    assert browser.close_called is True
    assert playwright.stop_called is True


def test_capture_json_filters_by_url_and_content_type(monkeypatch):
    responses = [
        _FakeResponse(
            "https://www.xhs-echo.example/api/feed?x=1",
            body='{"ok": "only-xhs-substring"}',
        ),
        _FakeResponse(
            "https://example.com/api/sns/web/v1/user_posted?x=1",
            body='{"ok": "matches-json-filter"}',
        ),
        _FakeResponse(
            "https://example.com/other/api",
            body='{"ok": "should-be-ignored"}',
        ),
        _FakeResponse(
            "https://example.com/api/sns/web/v1/user_posted?x=2",
            content_type="text/html",
            body='{"ok": "wrong-content-type"}',
        ),
        _FakeResponse(
            "https://example.com/api/sns/web/v1/user_posted?x=3",
            body="{not valid json",
        ),
    ]
    playwright, browser, context, page = _install_fake(
        monkeypatch, final_url="https://www.xiaohongshu.com/user/profile/abc123",
        responses=responses,
    )
    backend = PlaywrightFetchBackend()
    cookies = [{"name": "web_session", "value": "x", "domain": ".xiaohongshu.com", "path": "/"}]

    collected = backend.capture_json(
        "https://www.xiaohongshu.com/user/profile/abc123",
        cookies=cookies,
        json_filter="/api/sns/web/v1/user_posted",
    )

    assert collected == [
        {"ok": "only-xhs-substring"},
        {"ok": "matches-json-filter"},
    ]
    assert context.cookies == cookies
    assert page.goto_calls and page.goto_calls[0]["url"].endswith("/user/profile/abc123")
    assert browser.close_called is True
    assert playwright.stop_called is True


def test_fetch_html_wraps_internal_error_as_parse_http_error(monkeypatch):
    playwright, browser, _context, page = _install_fake(
        monkeypatch, final_url="https://example.com", html=""
    )

    def boom(*args, **kwargs):
        raise RuntimeError("internal-boom-secret")

    page.goto = boom
    backend = PlaywrightFetchBackend()

    with pytest.raises(ParseHttpError) as excinfo:
        backend.fetch_html("https://example.com")

    assert "internal-boom-secret" not in str(excinfo.value)
    assert browser.close_called is True
    assert playwright.stop_called is True


def test_capture_json_wraps_internal_error_as_parse_http_error(monkeypatch):
    playwright, browser, _context, page = _install_fake(
        monkeypatch, final_url="https://example.com", html=""
    )

    def boom(*args, **kwargs):
        raise ValueError("capture-boom-secret")

    page.goto = boom
    backend = PlaywrightFetchBackend()

    with pytest.raises(ParseHttpError) as excinfo:
        backend.capture_json("https://example.com", json_filter="/api/")

    assert "capture-boom-secret" not in str(excinfo.value)
    assert browser.close_called is True
    assert playwright.stop_called is True
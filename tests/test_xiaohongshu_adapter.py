"""小红书订阅适配器 TDD 测试。

全部用例注入假 backend，不开真实浏览器。覆盖目标解析、cookies
解析、capture_json 成功路径、HTML 兜底、双失败降级与不可用短路。
"""
from __future__ import annotations

import asyncio

import pytest

from plugins.bot_unified_runtime.contracts.subscription import (
    SubscriptionSpec,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError
from plugins.bot_unified_runtime.sources.subscriptions import (
    build_subscription_registry,
)
from plugins.bot_unified_runtime.sources.subscriptions.xiaohongshu_adapter import (
    ADAPTERS,
    XiaohongshuAdapter,
)


def _make_spec(**overrides):
    values = {
        "id": "xiaohongshu:creator:user123",
        "platform": "xiaohongshu",
        "target_kind": "creator",
        "target_id": "user123",
        "target_name": "测试博主",
    }
    values.update(overrides)
    return SubscriptionSpec(**values)


def _make_ctx():
    return {
        "cookie_header": "a=1; b=2",
        "proxy": "http://127.0.0.1:7890",
    }


class FakeBackend:
    """可编程假 backend：按队列回放或抛错，并记录全部调用参数。"""

    def __init__(self, *, available=True):
        self.available = available
        self.capture_results = []
        self.capture_errors = []
        self.fetch_results = []
        self.fetch_errors = []
        self.capture_calls = []
        self.fetch_calls = []

    def capture_json(self, url, *, cookies=None, json_filter=None, timeout_ms=30000):
        self.capture_calls.append(
            {
                "url": url,
                "cookies": cookies,
                "json_filter": json_filter,
                "timeout_ms": timeout_ms,
            }
        )
        if self.capture_errors:
            raise self.capture_errors.pop(0)
        if self.capture_results:
            return self.capture_results.pop(0)
        return []

    def fetch_html(
        self, url, *, cookies=None, timeout_ms=30000, wait_until="domcontentloaded"
    ):
        self.fetch_calls.append(
            {
                "url": url,
                "cookies": cookies,
                "timeout_ms": timeout_ms,
                "wait_until": wait_until,
            }
        )
        if self.fetch_errors:
            raise self.fetch_errors.pop(0)
        if self.fetch_results:
            return self.fetch_results.pop(0)
        return url, ""


def test_adapter_has_module_level_registration_metadata():
    assert XiaohongshuAdapter.platform == "xiaohongshu"
    assert XiaohongshuAdapter.target_kinds == ("creator",)
    assert XiaohongshuAdapter.LIVE_POLL is False
    assert ADAPTERS and ADAPTERS[0].platform == "xiaohongshu"
    assert build_subscription_registry().find("xiaohongshu") is not None


def test_resolve_target_accepts_user_profile_url():
    adapter = XiaohongshuAdapter(backend=FakeBackend())
    resolved = adapter.resolve_target(
        "https://www.xiaohongshu.com/user/profile/abc123?share_id=xyz"
    )
    assert resolved == {
        "platform": "xiaohongshu",
        "target_kind": "creator",
        "target_id": "abc123",
        "target_name": "abc123",
    }


def test_resolve_target_accepts_creator_uri():
    resolved = XiaohongshuAdapter(backend=FakeBackend()).resolve_target(
        "xiaohongshu:creator:user456"
    )
    assert resolved == {
        "platform": "xiaohongshu",
        "target_kind": "creator",
        "target_id": "user456",
        "target_name": "user456",
    }


def test_resolve_target_rejects_explore_note_links():
    with pytest.raises(ValueError, match="仅支持用户主页"):
        XiaohongshuAdapter(backend=FakeBackend()).resolve_target(
            "https://www.xiaohongshu.com/explore/64a1b2c3d4e5f6a7b8c9d0e1"
        )


def test_resolve_target_rejects_unknown_links():
    with pytest.raises(ValueError):
        XiaohongshuAdapter(backend=FakeBackend()).resolve_target(
            "https://example.com/other"
        )


def test_cookies_from_header_parses_semicolon_separated_pairs():
    adapter = XiaohongshuAdapter(backend=FakeBackend())
    cookies = adapter._cookies_from_header("a=1; b=2")
    assert [(cookie["name"], cookie["value"]) for cookie in cookies] == [
        ("a", "1"),
        ("b", "2"),
    ]
    for cookie in cookies:
        assert cookie["domain"] == ".xiaohongshu.com"
        assert cookie["path"] == "/"
        assert cookie["expires"] == -1
        assert cookie["httpOnly"] is False
        assert cookie["secure"] is False
        assert cookie["sameSite"] == "Lax"
    assert adapter._cookies_from_header("") == []


def test_extract_notes_supports_nested_paths_and_direct_list():
    adapter = XiaohongshuAdapter(backend=FakeBackend())
    note = {"note_id": "n1"}
    assert adapter._extract_notes({"data": {"notes": [note]}}) == [note]
    assert adapter._extract_notes({"notes": [note]}) == [note]
    assert adapter._extract_notes(
        {"data": {"user_posted": {"notes": [note]}}}
    ) == [note]
    assert adapter._extract_notes([note]) == [note]
    assert adapter._extract_notes([{"data": {"notes": [note]}}]) == [note]
    assert adapter._extract_notes({"data": {"notes": []}}) == []


def test_fetch_latest_builds_items_and_cursor_from_capture_json():
    payload = {
        "data": {
            "notes": [
                {
                    "note_id": "note-newest",
                    "display_title": "视频标题",
                    "title": "被优先字段覆盖",
                    "type": "video",
                    "cover": {"url": "https://ci.xiaohongshu.com/cover-newest"},
                    "interact_info": {
                        "liked_count": "128",
                        "collected_count": "9",
                        "comment_count": "7",
                    },
                    "user": {"nickname": "博主甲"},
                    "publish_time": "2026-08-22T00:00:00+00:00",
                },
                {
                    "note_id": "note-older",
                    "display_title": "",
                    "title": "图文标题",
                    "type": "normal",
                    "cover": "https://ci.xiaohongshu.com/cover-older",
                    "interact_info": {"liked_count": 0},
                    "user": {},
                },
            ]
        }
    }
    backend = FakeBackend()
    backend.capture_results = [payload, payload]
    adapter = XiaohongshuAdapter(backend=backend)
    spec = _make_spec()

    result = asyncio.run(adapter.fetch_latest(spec, None, _make_ctx()))

    assert result.health_state == "healthy"
    assert result.error == ""
    assert [item.item_id for item in result.items] == [
        "note-newest",
        "note-older",
    ]
    assert [item.kind for item in result.items] == ["video", "note"]
    assert [item.title for item in result.items] == ["视频标题", "图文标题"]
    assert result.items[0].url == (
        "https://www.xiaohongshu.com/explore/note-newest"
    )
    assert result.items[0].cover_url == (
        "https://ci.xiaohongshu.com/cover-newest"
    )
    assert result.items[0].stats == {"点赞": "128", "收藏": "9", "评论": "7"}
    assert result.items[0].author_name == "博主甲"
    assert result.items[1].url == (
        "https://www.xiaohongshu.com/explore/note-older"
    )
    assert result.items[1].cover_url == (
        "https://ci.xiaohongshu.com/cover-older"
    )
    assert result.items[1].stats == {"点赞": 0}
    assert result.items[1].author_name == "测试博主"

    assert result.new_cursor is not None
    assert result.new_cursor.spec_id == spec.id
    assert result.new_cursor.last_item_id == "note-newest"
    assert result.new_cursor.last_timestamp == "2026-08-22T00:00:00+00:00"

    call = backend.capture_calls[0]
    assert call["url"] == "https://www.xiaohongshu.com/user/profile/user123"
    assert call["json_filter"] == "/api/sns/web/v1/user_posted"
    assert call["timeout_ms"] == 30000
    assert [
        (cookie["name"], cookie["value"]) for cookie in call["cookies"]
    ] == [("a", "1"), ("b", "2")]
    assert backend.fetch_calls == []

    second = asyncio.run(adapter.fetch_latest(spec, result.new_cursor, _make_ctx()))
    assert second.items == []
    assert second.new_cursor is not None
    assert second.new_cursor.last_item_id == "note-newest"
    assert len(backend.capture_calls) == 2
    assert backend.fetch_calls == []


def test_fetch_latest_falls_back_to_html_when_capture_json_is_empty():
    backend = FakeBackend()
    backend.capture_results = [[]]
    backend.fetch_results = [
        (
            "https://www.xiaohongshu.com/user/profile/user123",
            (
                '<html><body><script>{"noteId":"html-note-1","title":"HTML标题一"},'
                '{"noteId":"html-note-2","title":"HTML标题二"}</script></body></html>'
            ),
        )
    ]
    adapter = XiaohongshuAdapter(backend=backend)
    spec = _make_spec()

    result = asyncio.run(adapter.fetch_latest(spec, None, _make_ctx()))

    assert result.health_state == "healthy"
    assert result.error == ""
    assert [item.item_id for item in result.items] == [
        "html-note-1",
        "html-note-2",
    ]
    assert [item.title for item in result.items] == ["HTML标题一", "HTML标题二"]
    assert [item.kind for item in result.items] == ["note", "note"]
    assert [item.author_name for item in result.items] == ["测试博主", "测试博主"]
    assert result.items[0].url == (
        "https://www.xiaohongshu.com/explore/html-note-1"
    )

    assert len(backend.capture_calls) == 1
    assert len(backend.fetch_calls) == 1
    fetch_call = backend.fetch_calls[0]
    assert fetch_call["url"] == (
        "https://www.xiaohongshu.com/user/profile/user123"
    )
    assert fetch_call["timeout_ms"] == 30000
    assert [
        (cookie["name"], cookie["value"]) for cookie in fetch_call["cookies"]
    ] == [("a", "1"), ("b", "2")]


def test_fetch_latest_degrades_without_leaking_when_both_backend_calls_fail():
    backend = FakeBackend()
    backend.capture_errors = [ParseHttpError("capture-boom-secret")]
    backend.fetch_errors = [ParseHttpError("fetch-boom-secret")]
    adapter = XiaohongshuAdapter(backend=backend)

    result = asyncio.run(adapter.fetch_latest(_make_spec(), None, _make_ctx()))

    assert result.items == []
    assert result.health_state == "degraded"
    assert result.error == "ParseHttpError"
    assert "secret" not in result.error
    assert len(backend.capture_calls) == 1
    assert len(backend.fetch_calls) == 1


def test_fetch_latest_short_circuits_when_backend_unavailable():
    backend = FakeBackend(available=False)
    adapter = XiaohongshuAdapter(backend=backend)

    result = asyncio.run(adapter.fetch_latest(_make_spec(), None, _make_ctx()))

    assert result.items == []
    assert result.new_cursor is None
    assert result.health_state == "unsupported"
    assert result.error == "playwright 不可用，无法轮询小红书"
    assert backend.capture_calls == []
    assert backend.fetch_calls == []
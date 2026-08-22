"""小红书用户主页解析单元测试。

使用假 Playwright 后端覆盖三条路径：capture_json 命中 user_posted 接口、
fetch_html 命中 window.__INITIAL_STATE__、以及两者都失败时的 og 浅层回退。
全部测试 monkeypatch，不发起真实网络请求。
"""

from __future__ import annotations

import urllib.parse

import pytest

from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError
from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
    parse_xiaohongshu,
)

GENERIC_MODULE = "plugins.bot_unified_runtime.sources.parsers.platforms_generic"
PROFILE_URL = "https://www.xiaohongshu.com/user/profile/abc123"


class _FakeBackend:
    """capture_json / fetch_html 都由测试控制的可记录假后端。"""

    def __init__(self, payloads=None, html="", capture_error=None, fetch_error=None):
        self.payloads = list(payloads or [])
        self.html = html
        self.capture_error = capture_error
        self.fetch_error = fetch_error
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
        if self.capture_error is not None:
            raise self.capture_error
        return self.payloads

    def fetch_html(self, url, *, cookies=None, timeout_ms=30000, wait_until="domcontentloaded"):
        self.fetch_calls.append(
            {
                "url": url,
                "cookies": cookies,
                "timeout_ms": timeout_ms,
                "wait_until": wait_until,
            }
        )
        if self.fetch_error is not None:
            raise self.fetch_error
        return url, self.html


def _user_posted_payload():
    return {
        "code": 0,
        "success": True,
        "data": {
            "cursor": "cursor-1",
            "has_more": False,
            "notes": [
                {
                    "note_id": "n1",
                    "display_title": "第一篇笔记",
                    "type": "normal",
                    "user": {"nickname": "博主甲", "user_id": "abc123"},
                    "interact_info": {"liked_count": "120", "collected_count": "45"},
                    "cover": {"url_default": "https://img.example/1.jpg"},
                },
                {
                    "note_id": "n2",
                    "display_title": "第二篇笔记",
                    "type": "video",
                    "user": {"nickname": "博主甲", "user_id": "abc123"},
                    "interact_info": {"liked_count": 88, "collected_count": 9},
                    "cover": {"url_pre": "https://img.example/2.jpg"},
                },
            ],
        },
    }


def _profile_initial_state_html(nickname="博主乙", note_titles=("主页笔记A", "主页笔记B")):
    notes = []
    for index, title in enumerate(note_titles, start=1):
        notes.append(
            {
                "id": f"n{index}",
                "display_title": title,
                "interact_info": {"liked_count": "10", "collected_count": "2"},
                "cover": {"url_default": f"https://img.example/c{index}.jpg"},
            }
        )
    state = {
        "user": {
            "userPageData": {"basicInfo": {"nickname": nickname, "avatar": "https://img.example/a.jpg"}},
            "notes": notes,
        }
    }
    raw = str(state).replace("'", '"')
    return "<script>window.__INITIAL_STATE__=" + urllib.parse.quote(raw) + "</script>"


def _og_html(title="用户主页浅层"):
    return (
        '<html><head><meta property="og:title" content="'
        + title
        + '"/><meta property="og:image" content="https://img.example/og.jpg"/>'
        + '<meta property="og:description" content="og 描述"/></head></html>'
    )


def _fail_http(*args, **kwargs):
    raise AssertionError("不应发起浅层 http 请求")


def test_user_profile_deep_parse_from_captured_api(monkeypatch):
    backend = _FakeBackend(payloads=[_user_posted_payload()])
    monkeypatch.setattr(GENERIC_MODULE + ".http_get_text", _fail_http)
    cookie_header = "web_session=x; a1=y"

    item = parse_xiaohongshu(
        PROFILE_URL, cookie_header=cookie_header, playwright_backend=backend
    )

    assert item.platform == "xiaohongshu"
    assert item.item_id == "abc123"
    assert item.item_kind == "user"
    assert item.title == "博主甲"
    assert item.cover_url == "https://img.example/1.jpg"
    assert item.stats == {"笔记数": 2}
    assert item.parse_depth == "deep"
    assert item.canonical_url == PROFILE_URL
    assert "《第一篇笔记》 120赞·45藏" in item.summary
    assert "《第二篇笔记》 88赞·9藏" in item.summary

    capture_call = backend.capture_calls[0]
    assert capture_call["url"] == PROFILE_URL
    assert capture_call["json_filter"] == "/api/sns/web/v1/user_posted"
    assert capture_call["cookies"] == [
        {"name": "web_session", "value": "x", "domain": ".xiaohongshu.com", "path": "/"},
        {"name": "a1", "value": "y", "domain": ".xiaohongshu.com", "path": "/"},
    ]
    assert backend.fetch_calls == []


def test_user_profile_summary_keeps_only_first_six_notes(monkeypatch):
    payload = _user_posted_payload()
    payload["data"]["notes"] = [
        {
            "note_id": f"n{index}",
            "display_title": f"第{index}条笔记",
            "user": {"nickname": "博主甲", "user_id": "abc123"},
            "interact_info": {"liked_count": index, "collected_count": 0},
            "cover": {"url_default": f"https://img.example/{index}.jpg"},
        }
        for index in range(1, 9)
    ]
    backend = _FakeBackend(payloads=[payload])
    monkeypatch.setattr(GENERIC_MODULE + ".http_get_text", _fail_http)

    item = parse_xiaohongshu(PROFILE_URL, playwright_backend=backend)

    assert item.stats == {"笔记数": 8}
    assert "《第1条笔记》" in item.summary
    assert "《第6条笔记》" in item.summary
    assert "《第7条笔记》" not in item.summary
    assert "《第8条笔记》" not in item.summary


def test_user_profile_deep_parse_from_initial_state(monkeypatch):
    backend = _FakeBackend(payloads=[], html=_profile_initial_state_html())
    monkeypatch.setattr(GENERIC_MODULE + ".http_get_text", _fail_http)

    item = parse_xiaohongshu(PROFILE_URL, playwright_backend=backend)

    assert item.item_id == "abc123"
    assert item.item_kind == "user"
    assert item.title == "博主乙"
    assert item.parse_depth == "deep"
    assert "《主页笔记A》 10赞·2藏" in item.summary
    assert "《主页笔记B》 10赞·2藏" in item.summary
    assert item.stats == {"笔记数": 2}
    assert len(backend.capture_calls) == 1
    assert len(backend.fetch_calls) == 1


def test_user_profile_capture_error_falls_back_to_page_state(monkeypatch):
    backend = _FakeBackend(
        html=_profile_initial_state_html(nickname="博主丙", note_titles=("回退笔记",)),
        capture_error=ParseHttpError("capture failed"),
    )
    monkeypatch.setattr(GENERIC_MODULE + ".http_get_text", _fail_http)

    item = parse_xiaohongshu(PROFILE_URL, playwright_backend=backend)

    assert item.item_kind == "user"
    assert item.title == "博主丙"
    assert "《回退笔记》" in item.summary
    assert len(backend.capture_calls) == 1
    assert len(backend.fetch_calls) == 1


def test_user_profile_falls_back_to_og_when_deep_paths_fail(monkeypatch):
    backend = _FakeBackend(payloads=[], html="<html><body>no state</body></html>")
    monkeypatch.setattr(
        GENERIC_MODULE + ".http_get_text", lambda url, **kwargs: (url, _og_html())
    )

    item = parse_xiaohongshu(PROFILE_URL, playwright_backend=backend)

    assert item.item_id == ""
    assert item.item_kind == "user"
    assert item.title == "用户主页浅层"
    assert item.parse_depth == "shallow"
    assert item.canonical_url == PROFILE_URL
    assert len(backend.capture_calls) == 1
    assert len(backend.fetch_calls) == 1


def test_user_profile_without_backend_goes_straight_to_og(monkeypatch):
    monkeypatch.setattr(
        GENERIC_MODULE + ".http_get_text", lambda url, **kwargs: (url, _og_html())
    )

    item = parse_xiaohongshu(PROFILE_URL)

    assert item.item_kind == "user"
    assert item.title == "用户主页浅层"
    assert item.parse_depth == "shallow"
    assert item.canonical_url == PROFILE_URL


def test_user_profile_without_user_id_raises(monkeypatch):
    backend = _FakeBackend()
    monkeypatch.setattr(GENERIC_MODULE + ".http_get_text", _fail_http)

    with pytest.raises(ParseHttpError):
        parse_xiaohongshu(
            "https://www.xiaohongshu.com/user/profile/", playwright_backend=backend
        )
"""Lofter（乐乎）链接解析与表单 POST 工具的单元测试。

所有 HTTP 边界均通过 monkeypatch 或本地回环服务器替换，
测试进程绝不发起真实网络请求。
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_post_form,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_lofter import parse_lofter

LOFTER_ANDROID_UA = "LOFTER-Android 8.2.36 (V2309A; Android 9; null) WIFI"


def test_http_post_form_sends_form_urlencoded():
    """http_post_form 应发 application/x-www-form-urlencoded 表单并解析 JSON。"""
    captured: dict = {}
    response_payload = {"ok": True, "value": 42}

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            captured["method"] = self.command
            captured["path"] = self.path
            captured["content_type"] = self.headers.get("Content-Type", "")
            captured["form"] = urllib.parse.parse_qs(body.decode("utf-8"))
            payload = json.dumps(response_payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            """静默本地服务器访问日志。"""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/form"
        result = http_post_form(url, {"name": "眼妆", "count": 2})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result == response_payload
    assert captured["method"] == "POST"
    assert "application/x-www-form-urlencoded" in captured["content_type"].lower()
    assert captured["form"]["name"] == ["眼妆"]
    assert captured["form"]["count"] == ["2"]


def test_parse_lofter_tag_uses_tagposts_api(monkeypatch):
    """标签页应调 newapi/tagPosts.json，深解析标签卡片。"""
    calls: list[tuple[str, dict, dict]] = []

    def fake_http_post_form(url, data=None, **kwargs):
        calls.append((url, data or {}, kwargs))
        return {
            "msg": "成功",
            "code": 0,
            "data": {
                "list": [
                    {
                        "postData": {
                            "postView": {
                                "id": 101,
                                "blogId": 201,
                                "title": "初试眼妆",
                                "type": 2,
                                "digest": "<p>眼妆第一弹</p>",
                                "permalink": "https://x.lofter.com/post/201_101",
                                "firstImage": {
                                    "orign": "https://img.lofter.com/orign-a.jpg",
                                    "ow": 1200,
                                    "oh": 1600,
                                    "raw": "https://img.lofter.com/raw-a.jpg",
                                },
                                "photoCount": 1,
                                "tagList": ["眼妆"],
                                "publishTime": 1710000000000,
                            },
                            "postCount": {
                                "responseCount": 12,
                                "favoriteCount": 340,
                                "reblogCount": 2,
                                "shareCount": 1,
                                "viewCount": 500,
                                "hotCount": 0,
                                "subscribeCount": 0,
                            },
                        },
                        "blogInfo": {
                            "blogNickName": "阿妆",
                            "blogName": "makeup",
                            "blogId": 201,
                            "bigAvaImg": "https://img.lofter.com/avatar-a.jpg",
                        },
                    },
                    {
                        "postData": {
                            "postView": {
                                "id": 102,
                                "blogId": 202,
                                "title": "日常眼妆",
                                "type": 2,
                                "digest": "<p>眼妆第二弹</p>",
                                "permalink": "https://x.lofter.com/post/202_102",
                                "firstImage": {},
                                "photoCount": 1,
                                "tagList": ["眼妆"],
                                "publishTime": 1710000001000,
                            },
                            "postCount": {
                                "responseCount": 3,
                                "favoriteCount": 12,
                                "reblogCount": 0,
                                "shareCount": 0,
                                "viewCount": 20,
                                "hotCount": 0,
                                "subscribeCount": 0,
                            },
                        },
                        "blogInfo": {
                            "blogNickName": "小鹿",
                            "blogName": "deer",
                            "blogId": 202,
                            "bigAvaImg": "https://img.lofter.com/avatar-b.jpg",
                        },
                    },
                ]
            },
        }

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_lofter.http_post_form",
        fake_http_post_form,
    )

    item = parse_lofter("https://www.lofter.com/tag/%E7%9C%BC%E5%A6%86")

    assert len(calls) == 1
    url, data, kwargs = calls[0]
    assert url == "https://api.lofter.com/newapi/tagPosts.json"
    assert data["tag"] == "眼妆"
    assert data["product"] == "lofter-android-8.2.36"
    assert data["type"] == "total"
    assert kwargs["user_agent"] == LOFTER_ANDROID_UA
    assert item.platform == "lofter"
    assert item.item_id == "眼妆"
    assert item.item_kind == "tag"
    assert item.title == "标签：眼妆"
    assert item.author_name == ""
    assert item.stats == {"博文": 2}
    assert item.cover_url == "https://img.lofter.com/orign-a.jpg"
    assert "1. 阿妆《初试眼妆》 340喜欢 · 12回复" in item.summary
    assert "2. 小鹿《日常眼妆》 12喜欢 · 3回复" in item.summary
    assert item.parse_depth == "deep"


def test_parse_lofter_post_numeric_detail(monkeypatch):
    """数字 token 的文章应调 oldapi/post/detail.api 并深解析。"""
    calls: list[tuple[str, dict, dict]] = []

    def fake_http_post_form(url, data=None, **kwargs):
        calls.append((url, data or {}, kwargs))
        return {
            "meta": {"status": 200},
            "response": {
                "posts": [
                    {
                        "post": {
                            "id": 11762741121,
                            "type": 2,
                            "blogId": 2219767556,
                            "title": "蛇涩色 · 眼妆合集",
                            "publishTime": 1710000000000,
                            "digest": "<p>第一段正文</p><p>第二段正文</p>",
                            "content": "",
                            "firstImageUrl": '["https://img.lofter.com/thumb.jpg"]',
                            "photoLinks": json.dumps(
                                [
                                    {
                                        "rw": 640,
                                        "rh": 800,
                                        "ow": 1920,
                                        "oh": 2400,
                                        "raw": "https://img.lofter.com/raw1.jpg",
                                        "orign": "https://img.lofter.com/orign1.jpg",
                                        "middle": "https://img.lofter.com/mid1.jpg",
                                    },
                                    {
                                        "rw": 640,
                                        "rh": 800,
                                        "ow": 1920,
                                        "oh": 2400,
                                        "raw": "https://img.lofter.com/raw2.jpg",
                                        "orign": "https://img.lofter.com/orign2.jpg",
                                    },
                                ],
                                ensure_ascii=False,
                            ),
                            "firstImageWH": [1920, 2400],
                            "wordCount": 120,
                            "blogPageUrl": (
                                "https://xxxx.lofter.com/post/2219767556_11762741121"
                            ),
                            "tagList": ["眼妆", "插画"],
                            "ipLocation": "广东",
                            "postCount": {
                                "responseCount": 290,
                                "favoriteCount": 48040,
                                "reblogCount": 300,
                                "shareCount": 400,
                                "viewCount": 999999,
                                "subscribeCount": 5,
                                "postHot": 54633,
                            },
                            "blogInfo": {
                                "blogName": "xxx",
                                "blogNickName": "蛇涩色",
                                "bigAvaImg": "https://img.lofter.com/avatar.jpg",
                                "homePageUrl": "https://xxx.lofter.com/",
                            },
                        }
                    }
                ]
            },
        }

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_lofter.http_post_form",
        fake_http_post_form,
    )

    item = parse_lofter("https://x.lofter.com/post/2219767556_11762741121")

    assert len(calls) == 1
    url, data, kwargs = calls[0]
    assert "oldapi/post/detail.api" in url
    assert "product=lofter-android-7.9.10" in url
    assert data["targetblogid"] == "2219767556"
    assert data["postid"] == "11762741121"
    assert data["supportposttypes"] == "1,2,3,4,5,6"
    assert data["needgetpoststat"] == "1"
    assert kwargs["user_agent"] == LOFTER_ANDROID_UA
    assert item.platform == "lofter"
    assert item.item_id == "11762741121"
    assert item.item_kind == "post"
    assert item.title == "蛇涩色 · 眼妆合集"
    assert item.author_name == "蛇涩色"
    assert item.stats["喜欢"] == 48040
    assert item.stats["图片数量"] == 2
    assert "×" in item.stats["分辨率"]
    assert "<p>" not in item.summary
    assert "标签：眼妆、插画" in item.summary
    assert item.cover_url.startswith("https://")
    assert item.parse_depth == "deep"


def test_parse_lofter_post_permalink_falls_back_og(monkeypatch):
    """新版 permalink 令牌应降级 og 浅解析，且不触碰文章 API。"""
    html_text = (
        "<html><head>"
        '<meta property="og:title" content="Lofter 新文章">'
        '<meta property="og:image" content="https://img.lofter.com/og.jpg">'
        "</head></html>"
    )

    def fake_http_get_text(url, **kwargs):
        return url, html_text

    def fake_http_post_form(url, data=None, **kwargs):
        raise AssertionError("permalink 降级路径不应调用 http_post_form")

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_lofter.http_get_text",
        fake_http_get_text,
    )
    # _og_scrape 定义在 platforms_generic，其内部通过 platforms_generic.http_get_text
    # 发请求；同步替换同一 fake，确保该降级路径完全离线。
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_generic.http_get_text",
        fake_http_get_text,
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_lofter.http_post_form",
        fake_http_post_form,
    )

    item = parse_lofter("https://x.lofter.com/post/abc123_token")

    assert item.platform == "lofter"
    assert item.item_kind == "post"
    assert item.title == "Lofter 新文章"
    assert item.cover_url == "https://img.lofter.com/og.jpg"
    assert item.parse_depth == "shallow"


def test_parse_lofter_theme_ssr(monkeypatch):
    """主题预览页应从 this.p 提取 themeid 与预览博客名。"""
    html_text = (
        "<html><head><title>零时差 | LOFTER（乐乎）</title></head>"
        "<body><script>this.p={themeid:'120002',previewBlogName:'lofterphoto3'};"
        "</script></body></html>"
    )

    def fake_http_get_text(url, **kwargs):
        return url, html_text

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_lofter.http_get_text",
        fake_http_get_text,
    )

    item = parse_lofter("https://www.lofter.com/theme/preview/120002?c=all")

    assert item.platform == "lofter"
    assert item.item_kind == "theme"
    assert item.item_id == "120002"
    assert item.title == "零时差"
    assert "| LOFTER" not in item.title
    assert item.summary == "主题ID：120002 · 预览博客：lofterphoto3"
    assert item.parse_depth == "deep"


def test_parse_lofter_selection_and_trend_shallow(monkeypatch):
    """精选与趋势为动态渲染页，应降级为仅含页面标题的浅卡片。"""
    selection_html = "<title>国风插画精选 | LOFTER（乐乎）</title>"
    trend_html = "<title>热门趋势 | LOFTER（乐乎）</title>"

    def fake_http_get_text(url, **kwargs):
        if "/selection" in url:
            return url, selection_html
        return url, trend_html

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_lofter.http_get_text",
        fake_http_get_text,
    )

    item = parse_lofter("https://www.lofter.com/selection?id=888")
    assert item.platform == "lofter"
    assert item.item_kind == "collection"
    assert item.title == "国风插画精选"
    assert item.parse_depth == "shallow"
    assert "动态渲染" in item.summary

    item = parse_lofter("https://www.lofter.com/trend?act=qbview_20130930_01")
    assert item.platform == "lofter"
    assert item.item_kind == "page"
    assert item.title == "Lofter 趋势页"
    assert item.parse_depth == "shallow"
    assert "动态渲染" in item.summary


def test_parse_lofter_unknown_path_raises():
    """未识别的 Lofter 页面应明确抛 ParseHttpError。"""
    with pytest.raises(ParseHttpError, match="unsupported page type"):
        parse_lofter("https://www.lofter.com/xxx")

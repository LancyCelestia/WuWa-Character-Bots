"""Pixiv 链接解析器单元测试（严格离线：所有 HTTP 工具函数均被 monkeypatch 替换）。"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError
from plugins.bot_unified_runtime.sources.parsers.platforms_pixiv import parse_pixiv

ARTWORK_URL = "https://www.pixiv.net/artworks/134246952"


def test_parse_pixiv_deep_with_pages_and_author_stats(monkeypatch):
    """深解析：多图分镜、作者作品数、粉丝数据入结果，代理参数全程转发。"""
    proxy_url = "http://127.0.0.1:7890"
    json_calls: list[tuple[str, dict]] = []

    def fake_http_get_json(url: str, **kwargs) -> object:
        json_calls.append((url, kwargs))
        if url == "https://www.pixiv.net/ajax/illust/134246952":
            return {
                "body": {
                    "title": "海と空の境界線",
                    "userName": "SakuraiChino",
                    "userId": 7358990,
                    "width": 1000,
                    "height": 1415,
                    "pageCount": 1,
                    "likeCount": 546,
                    "bookmarkCount": 776,
                    "viewCount": 3249,
                    "commentCount": 6,
                    "illustType": 0,
                    "description": "简介文本",
                    "tags": {"tags": [{"tag": "女の子"}, {"tag": "少女"}]},
                }
            }
        if "/pages" in url:
            return [
                {
                    "width": 1000,
                    "height": 1415,
                    "urls": {"original": "https://i.pximg.net/x.png"},
                }
            ]
        if "/profile/all" in url:
            return {
                "body": {
                    "illusts": {"1": None, "2": None, "3": None},
                    "manga": {},
                    "novels": {},
                }
            }
        if "/ajax/user/" in url:
            return {"body": {"follower": 1200, "following": 3}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_pixiv.http_get_json",
        fake_http_get_json,
    )

    item = parse_pixiv(ARTWORK_URL, proxy=proxy_url)

    assert item.platform == "pixiv"
    assert item.item_id == "134246952"
    assert item.title == "海と空の境界線"
    assert item.author_name == "SakuraiChino"
    assert item.item_kind == "illust"
    assert item.parse_depth == "deep"
    assert item.stats["浏览"] == 3249
    assert item.stats["喜欢"] == 546
    assert item.stats["收藏"] == 776
    assert item.stats["评论"] == 6
    assert item.stats["图片数量"] == 1
    assert item.stats["分辨率"] == "1000×1415"
    assert "分镜：P1 1000×1415" in item.summary
    assert "作者作品：插画3" in item.summary
    assert "作者粉丝：1200" in item.summary
    assert "标签" in item.summary
    assert "女の子" in item.summary
    assert item.cover_url.startswith("https://embed.pixiv.net")
    assert "134246952" in item.cover_url
    assert json_calls, "fake 应至少收到 illust 请求"
    for _, kwargs in json_calls:
        assert kwargs.get("proxy") == proxy_url


def test_parse_pixiv_pages_failure_is_tolerated(monkeypatch):
    """pages 接口失败只丢分镜信息，主结果仍是深解析。"""

    def fake_http_get_json(url: str, **kwargs) -> object:
        if "/pages" in url:
            raise ParseHttpError("pages failed")
        if "/ajax/illust/" in url:
            return {
                "body": {
                    "title": "海と空の境界線",
                    "userName": "SakuraiChino",
                    "userId": 7358990,
                    "width": 1000,
                    "height": 1415,
                    "pageCount": 1,
                    "viewCount": 3249,
                    "likeCount": 546,
                    "bookmarkCount": 776,
                    "commentCount": 6,
                    "illustType": 0,
                    "description": "简介文本",
                    "tags": {"tags": [{"tag": "女の子"}]},
                }
            }
        if "/profile/all" in url:
            return {"body": {"illusts": {"1": None}, "manga": {}, "novels": {}}}
        return {"body": {"follower": 10, "following": 2}}

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_pixiv.http_get_json",
        fake_http_get_json,
    )

    item = parse_pixiv(ARTWORK_URL)

    assert item.parse_depth == "deep"
    assert item.title == "海と空の境界線"
    assert item.stats["图片数量"] == 1
    assert "分镜" not in item.summary
    assert "作者作品：插画1" in item.summary
    assert "作者粉丝：10" in item.summary


def test_parse_pixiv_illust_api_failure_falls_back_og(monkeypatch):
    """主接口失败回退 og 浅解析，且代理参数继续转发给 http_get_text。"""
    proxy_url = "http://127.0.0.1:7890"
    text_calls: list[tuple[str, dict]] = []

    def fake_http_get_json(url: str, **kwargs) -> object:
        raise ParseHttpError("illust api failed")

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_pixiv.http_get_json",
        fake_http_get_json,
    )

    def fake_http_get_text(url: str, **kwargs) -> tuple[str, str]:
        text_calls.append((url, kwargs))
        return (
            url,
            "<html><head>"
            '<meta property="og:title" content="OG 标题" />'
            '<meta property="og:image" content="https://i.pximg.net/og.jpg" />'
            "</head></html>",
        )

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_generic.http_get_text",
        fake_http_get_text,
    )

    item = parse_pixiv(ARTWORK_URL, proxy=proxy_url)

    assert item.parse_depth == "shallow"
    assert item.title == "OG 标题"
    assert item.cover_url == "https://i.pximg.net/og.jpg"
    assert text_calls and text_calls[0][1].get("proxy") == proxy_url


def test_parse_pixiv_missing_artwork_id_raises():
    """没有 artwork id 的链接直接抛 ParseHttpError，不发起任何网络请求。"""
    with pytest.raises(ParseHttpError):
        parse_pixiv("https://www.pixiv.net/")
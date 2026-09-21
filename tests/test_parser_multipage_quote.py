"""B站分P cid 选择 + 推特引用推摘要 回归。

两条都是真实缺陷修复的锁定测试：
- 分P：分享 ?p=N 时字幕/AI总结/视频资产按指定分P取（此前恒 P1 内容错位）。
- 引用推：fxtwitter 的 quote 字段此前未消费，引用推内容整段丢失。
"""

from __future__ import annotations

import pytest

import plugins.bot_unified_runtime.sources.parsers  # noqa: F401  # v21r2 W1a: 旧路径聚合先行（垫片期顺序纪律）

# v21r2 W1a: 真身已迁 domains/link_parse/parsers/，monkeypatch 需打在真身上
from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    platforms_bilibili as B,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    platforms_generic as G,
)

# ---------- B站分P ----------

def _view_payload() -> dict:
    return {
        "code": 0,
        "data": {
            "bvid": "BV1abcDEF234",
            "aid": 1,
            "title": "多P测试视频",
            "desc": "简介",
            "tname": "科技",
            "duration": 120,
            "pubdate": 1725868800,
            "owner": {"mid": 2, "name": "UP", "face": ""},
            "stat": {"view": 10, "danmaku": 1, "reply": 2, "like": 3},
            "cid": 111,
            "pages": [
                {"cid": 111, "page": 1, "part": "P1"},
                {"cid": 222, "page": 2, "part": "P2"},
            ],
        },
    }


@pytest.fixture()
def stub_bilibili(monkeypatch):
    captured: dict = {}

    def fake_http_get_json(url, **kwargs):
        captured["url"] = url
        return _view_payload()

    def fake_subtitle(**kwargs):
        captured["subtitle_cid"] = kwargs.get("cid")

    def fake_conclusion(**kwargs):
        captured["conclusion_cid"] = kwargs.get("cid")

    monkeypatch.setattr(B, "http_get_json", fake_http_get_json)
    monkeypatch.setattr(B, "_bilibili_subtitle", fake_subtitle)
    monkeypatch.setattr(B, "_bilibili_ai_conclusion", fake_conclusion)
    monkeypatch.setattr(B, "_author_enrichment", lambda mid, **kw: ("", {}, {}))
    return captured


def test_bilibili_p2_url_uses_second_page_cid(monkeypatch, stub_bilibili) -> None:
    result = B.parse_bilibili(
        "https://www.bilibili.com/video/BV1abcDEF234?p=2", cookie_header=""
    )
    assert stub_bilibili["subtitle_cid"] == 222
    assert result.content is not None
    assert "当前 P2" in result.content.summary


def test_bilibili_default_url_uses_first_page(monkeypatch, stub_bilibili) -> None:
    B.parse_bilibili(
        "https://www.bilibili.com/video/BV1abcDEF234", cookie_header=""
    )
    assert stub_bilibili["subtitle_cid"] == 111


# ---------- 推特引用推 ----------

def _install_twitter(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(G, "http_get_json", lambda url, **kw: payload)
    monkeypatch.setattr(G, "try_stitch_strip", lambda urls, **kw: (list(urls), ""))


def test_twitter_quote_summary(monkeypatch) -> None:
    payload = {
        "code": 200,
        "tweet": {
            "text": "看这个",
            "created_timestamp": 1756500000,
            "author": {"name": "张三", "screen_name": "zhangsan"},
            "quote": {
                "text": "被引用的原推内容",
                "author": {"name": "李四", "screen_name": "lisi"},
            },
        },
    }
    _install_twitter(monkeypatch, payload)
    result = G.parse_twitter_x("https://x.com/zhangsan/status/1")
    assert "引用 @李四：被引用的原推内容" in result.content.summary


def test_twitter_without_quote_no_marker(monkeypatch) -> None:
    payload = {
        "code": 200,
        "tweet": {
            "text": "普通推",
            "created_timestamp": 1756500000,
            "author": {"name": "张三", "screen_name": "zhangsan"},
        },
    }
    _install_twitter(monkeypatch, payload)
    result = G.parse_twitter_x("https://x.com/zhangsan/status/2")
    assert "引用" not in result.content.summary

from __future__ import annotations

import json
import os

import pytest

from plugins.bot_unified_runtime.sources.parsers import (
    platforms_douban,
    platforms_taptap,
    platforms_zhihu,
)

_SAMPLE_BASE = r"C:/Users/LancyCelestia/Downloads/Archives/nonebot-plugin-parser-lite-1.3.5/api_txt"


def _sample(*parts: str) -> dict:
    path = os.path.join(_SAMPLE_BASE, *parts)
    return json.load(open(path, encoding="utf-8"))


_HAS_SAMPLES = os.path.isdir(_SAMPLE_BASE)


@pytest.mark.skipif(not _HAS_SAMPLES, reason="parser-lite samples not present")
def test_zhihu_article_parse_uses_sample_fields(monkeypatch) -> None:
    sample = _sample("zhihu", "article.json")

    monkeypatch.setattr(
        platforms_zhihu, "http_get_json", lambda *a, **kw: sample
    )
    result = platforms_zhihu.parse_zhihu("https://zhuanlan.zhihu.com/p/581111111")

    assert result is not None
    assert "打开链接发现要提取码" in (result.content.title if result.content else "")
    assert result.creator is not None
    assert result.engagement.like_count == 62
    assert result.content.published_at is not None


def test_zhihu_url_routing(tmp_path, monkeypatch) -> None:
    called = {}

    def fake_article(article_id: str, *, cookie_header: str = ""):
        called["id"] = article_id
        return platforms_zhihu.build_parsed_content(
            platform="zhihu", item_id=article_id, item_kind="article", title="t"
        )

    monkeypatch.setattr(platforms_zhihu, "parse_zhihu_article", fake_article)
    platforms_zhihu.parse_zhihu("https://zhuanlan.zhihu.com/p/123456")
    assert called["id"] == "123456"


@pytest.mark.skipif(not _HAS_SAMPLES, reason="parser-lite samples not present")
def test_douban_topic_parse_uses_sample_fields(monkeypatch) -> None:
    sample = _sample("douban", "vertical.json")
    monkeypatch.setattr(platforms_douban, "http_get_json", lambda *a, **kw: sample)

    result = platforms_douban.parse_douban("https://www.douban.com/group/topic/472573751/")

    assert result is not None
    assert result.content is not None
    assert result.identity.canonical_url.endswith("472573751/")


def test_taptap_moment_parse_uses_sample_fields(monkeypatch) -> None:
    if _HAS_SAMPLES:
        sample = _sample("taptap", "moment_text.json")
    else:
        sample = {"data": {"moment": {"author": {"user": {"name": "x"}}}}, "success": True}
    monkeypatch.setattr(platforms_taptap, "http_get_json", lambda *a, **kw: sample)

    result = platforms_taptap.parse_taptap("https://www.taptap.cn/moment/283325378")

    assert result is not None
    assert result.engagement.view_count == 631 or not _HAS_SAMPLES


def test_unknown_url_patterns_raise() -> None:
    # 与现平台契约一致：不匹配的 URL 形态抛 ValueError（由路由层兜底）。
    with pytest.raises(ValueError):
        platforms_taptap.parse_taptap("https://www.taptap.cn/app/1")
    with pytest.raises(ValueError):
        platforms_douban.parse_douban("https://www.douban.com/people/x")
    with pytest.raises(ValueError):
        platforms_zhihu.parse_zhihu("https://www.zhihu.com/people/x")

"""YouTube 字幕摘录回归：字幕块在 detail/video_desc 定义之后才允许引用。

00235e9 曾把字幕块插在 ``detail``/``video_desc`` 定义之前，YouTube 解析
遇到非空字幕即抛 NameError。本测试锁定正确顺序。
"""

from __future__ import annotations

# v21r2 W1a: 真身已迁 domains/link_parse/parsers/，monkeypatch 需打在真身上
from plugins.bot_unified_runtime.domains.link_parse.parsers import platforms_generic


def test_youtube_subtitle_does_not_crash_and_appends(monkeypatch):
    monkeypatch.setattr(
        platforms_generic,
        "_youtube_watch_enrich",
        lambda url, *, proxy="": {
            "_subtitle": "这是字幕摘录内容",
            "_video_desc": "视频简介正文",
            "_channel_url": "https://www.youtube.com/channel/UCabc",
            "_author_name": "测试频道",
        },
    )
    monkeypatch.setattr(
        platforms_generic, "_youtube_innertube", lambda video_id, *, proxy="": {}
    )
    monkeypatch.setattr(
        platforms_generic, "_youtube_about_enrich", lambda channel_url, *, proxy="": {}
    )
    monkeypatch.setattr(
        platforms_generic,
        "http_get_json",
        lambda url, **kwargs: {
            "title": "油管测试视频",
            "author_name": "测试频道",
            "author_url": "",
        },
    )

    item = platforms_generic.parse_youtube(
        "https://www.youtube.com/watch?v=abc1234567"
    )

    assert item.content is not None
    assert "字幕摘录" in item.content.summary
    assert "视频简介正文" in item.content.summary
    assert "这是字幕摘录内容" in item.content.summary

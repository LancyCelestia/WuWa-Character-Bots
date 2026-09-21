from __future__ import annotations

import json
import os

import pytest

import plugins.bot_unified_runtime.sources.parsers  # noqa: F401  # v21r2 W1a: 旧路径聚合先行（垫片期顺序纪律）

# v21r2 W1a: 真身已迁 domains/link_parse/parsers/，monkeypatch 需打在真身上
from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    platforms_community,
    platforms_discourse,
    platforms_media_share,
)

_SAMPLE_BASE = os.path.join(os.path.dirname(__file__), "api_txt")
_HAS = os.path.isdir(_SAMPLE_BASE)


def _sample(*parts: str) -> dict:
    return json.load(open(os.path.join(_SAMPLE_BASE, *parts), encoding="utf-8"))


def test_discourse_linuxdo_parses_topic(monkeypatch) -> None:
    if not _HAS:
        pytest.skip(
            "缺真实样本："
            f"{_SAMPLE_BASE}/linux.do/topic.json 不存在——"
            "补样本（nonebot-plugin-parser-lite api_txt 归档解包）后，"
            "本用例自动由 skip 转为实断言"
        )
    sample = _sample("linux.do", "topic.json")
    monkeypatch.setattr(platforms_discourse, "http_get_json", lambda *a, **kw: sample)

    result = platforms_discourse.parse_linuxdo("https://linux.do/t/topic/12345")

    assert result is not None
    # 期望值从样本派生（评论数=posts_count-1），不写死任一真实样本数值。
    posts_count = sample.get("posts_count")
    assert isinstance(posts_count, int)
    assert result.engagement.comment_count == max(0, posts_count - 1)
    assert result.creator is not None


def test_discourse_zlb_uses_bb_host(monkeypatch) -> None:
    seen = {}

    def fake(url: str, **kw):
        seen["url"] = url
        return {"fancy_title": "z", "post_stream": {"posts": [{"username": "u", "cooked": "c"}]}}

    monkeypatch.setattr(platforms_discourse, "http_get_json", fake)
    platforms_discourse.parse_zlb("https://zlb.ink/t/topic/777")
    assert seen["url"].startswith("https://bb.zlb.ink/t/777")


def test_coolapk_parses_next_data_props(monkeypatch) -> None:
    if _HAS and os.path.isfile(os.path.join(_SAMPLE_BASE, "coolapk", "feed.json")):
        sample = _sample("coolapk", "feed.json")
    else:
        sample = {"props": {"pageProps": {"feed": {"message": "m", "username": "u", "dateline": "1778036931", "likenum": 5, "replynum": 2}}}}
    monkeypatch.setattr(platforms_community, "http_get_json", lambda *a, **kw: sample)

    result = platforms_community.parse_coolapk("https://www.coolapk.com/feed/123456")

    assert result is not None
    assert result.content.published_at is not None
    assert result.content.published_at is not None or not _HAS


def test_hupu_signed_request_builds_sign(monkeypatch) -> None:
    seen = {}

    def fake(url: str, **kw):
        seen["url"] = url
        return {"data": {"result": {"thread": {"title": "虎扑标题", "username": "u", "content": "c", "likes": 9, "replies": 3, "hits": 100}}}}

    monkeypatch.setattr(platforms_community, "http_get_json", fake)
    result = platforms_community.parse_hupu("https://bbs.hupu.com/12345678.html")

    assert "sign=" in seen["url"] and "tid=12345678" in seen["url"]
    assert result.engagement.like_count == 9
    assert "虎扑标题" in (result.content.title or "")


def test_5eplay_and_ds163_parse(monkeypatch) -> None:
    monkeypatch.setattr(
        platforms_community,
        "http_get_json",
        lambda *a, **kw: {"data": {"topic": {"title": "5E帖子", "user": {"username": "u"}, "view_num": 10, "reply_num": 2, "like_num": 1}}},
    )
    r1 = platforms_community.parse_5eplay("https://csgo.5eplay.com/forum/1050838")
    assert r1.engagement.view_count == 10

    monkeypatch.setattr(
        platforms_community,
        "http_get_json",
        lambda *a, **kw: {"data": {"feed": {"title": "大道", "user_info": {"nickname": "n"}, "content": "c"}}},
    )
    r2 = platforms_community.parse_ds163("https://ds.163.com/feed/abc123")
    assert r2.identity.platform == "ds163"


def test_media_share_doubao_and_buff(monkeypatch) -> None:
    monkeypatch.setattr(
        platforms_media_share,
        "http_get_json",
        lambda *a, **kw: {"data": {"user_info": {"nickname": "jojo"}, "play_info": {"main": "https://v.example/x"}, "prompt": "一只猫"}},
    )
    r = platforms_media_share.parse_doubao("https://www.doubao.com/video-sharing?source_type=mobile&share_id=49939181380407810&video_id=v1")
    assert "Prompt：一只猫" in (r.content.summary or "")

    monkeypatch.setattr(
        platforms_media_share,
        "http_get_text",
        lambda *a, **kw: (200, '{"loaderData": {"track_page": {"track_id": "7387697402612500481", "title": "歌名"}}}'),
    )
    r2 = platforms_media_share.parse_qsmusic("https://qishui.douyin.com/s/aBcD1234/")
    assert r2.identity.item_id == "7387697402612500481"


def test_unknown_urls_raise() -> None:
    with pytest.raises(ValueError):
        platforms_discourse.parse_linuxdo("https://linux.do/u/x")
    with pytest.raises(ValueError):
        platforms_community.parse_coolapk("https://www.coolapk.com/user/x")
    with pytest.raises(ValueError):
        platforms_media_share.parse_doubao("https://www.doubao.com/chat/")

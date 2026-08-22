"""Bilibili 订阅 adapter 的 TDD 测试。

所有测试都通过 monkeypatch 替换模块内的 ``http_get_json`` 与
``wbi.build_wbi_signed_url``，不发起任何真实网络请求。
"""

from __future__ import annotations

import asyncio
import urllib.parse

import pytest

from plugins.bot_unified_runtime.contracts.subscription import (
    SubscriptionCursor,
    SubscriptionSpec,
)
from plugins.bot_unified_runtime.sources.parsers import wbi
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError
from plugins.bot_unified_runtime.sources.subscriptions import bilibili_adapter as ba


CTX = {"cookie_header": "SESSDATA=test", "proxy": "http://127.0.0.1:7890"}


def _make_spec(**overrides) -> SubscriptionSpec:
    values = {
        "id": "bilibili:creator:3577566",
        "platform": "bilibili",
        "target_kind": "creator",
        "target_id": "3577566",
        "target_name": "测试UP",
    }
    values.update(overrides)
    return SubscriptionSpec(**values)


def _make_cursor(spec_id: str, **payload) -> SubscriptionCursor:
    return SubscriptionCursor(
        spec_id=spec_id,
        cursor_payload=dict(payload),
    )


def _plain_signer(monkeypatch):
    """把 WBI 签名替换为“原 URL + 参数”，记录调用以便断言。"""
    calls: list[tuple[str, dict, str, str]] = []

    def fake_sign(url, params, *, cookie_header="", proxy=""):
        calls.append((url, dict(params), cookie_header, proxy))
        return f"{url}?{urllib.parse.urlencode(params)}"

    monkeypatch.setattr(wbi, "build_wbi_signed_url", fake_sign)
    return calls


# ---------- 1. resolve_target ----------


def test_resolve_target_kinds(monkeypatch):
    adapter = ba.BilibiliAdapter()
    view_calls = []

    def fake_get_json(url, **kwargs):
        view_calls.append((url, dict(kwargs)))
        if "view?" in url:
            return {
                "code": 0,
                "data": {"owner": {"mid": 3577566, "name": "示例UP主"}},
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(ba, "http_get_json", fake_get_json)

    assert adapter.resolve_target("https://live.bilibili.com/206327") == {
        "platform": "bilibili",
        "target_kind": "live_room",
        "target_id": "206327",
        "target_name": "206327",
    }

    assert adapter.resolve_target("https://space.bilibili.com/3577566") == {
        "platform": "bilibili",
        "target_kind": "creator",
        "target_id": "3577566",
        "target_name": "3577566",
    }

    fav = adapter.resolve_target(
        "https://space.bilibili.com/3577566/favlist?fid=1692497155"
    )
    assert fav["target_kind"] == "favorite"
    assert fav["target_id"] == "1692497155"
    assert fav["extra_mid"] == "3577566"
    assert fav["target_name"] == "1692497155"

    bangumi_ss = adapter.resolve_target(
        "https://www.bilibili.com/bangumi/play/ss21542"
    )
    assert bangumi_ss["target_kind"] == "bangumi"
    assert bangumi_ss["target_id"] == "ss21542"

    bangumi_ep = adapter.resolve_target(
        "https://www.bilibili.com/bangumi/play/ep1344093"
    )
    assert bangumi_ep["target_kind"] == "bangumi"
    assert bangumi_ep["target_id"] == "ep1344093"

    series = adapter.resolve_target(
        "https://space.bilibili.com/3577566/channel/seriesdetail?sid=12345"
    )
    assert series["target_kind"] == "collection"
    assert series["target_id"] == "12345"
    assert series["extra_mid"] == "3577566"
    assert series["target_name"] == "3577566"

    lists = adapter.resolve_target("https://space.bilibili.com/3577566/lists?ml=67890")
    assert lists["target_kind"] == "collection"
    assert lists["target_id"] == "67890"
    assert lists["extra_mid"] == "3577566"

    series_without_sid = adapter.resolve_target(
        "https://space.bilibili.com/3577566/channel/seriesdetail"
    )
    assert series_without_sid["target_kind"] == "collection"
    assert series_without_sid["target_id"] == "3577566"
    assert series_without_sid["extra_mid"] == "3577566"

    video = adapter.resolve_target("https://www.bilibili.com/video/BV1xx411c7mD")
    assert video == {
        "platform": "bilibili",
        "target_kind": "creator",
        "target_id": "3577566",
        "target_name": "示例UP主",
    }
    assert any("bvid=BV1xx411c7mD" in url for url, _ in view_calls)
    assert view_calls[0][1].get("referer")

    for kind in ("creator", "live_room", "bangumi", "favorite", "collection"):
        resolved = adapter.resolve_target(f"bilibili:{kind}:999")
        assert resolved["platform"] == "bilibili"
        assert resolved["target_kind"] == kind
        assert resolved["target_id"] == "999"
        assert resolved["target_name"] == "999"

    with pytest.raises(ValueError):
        adapter.resolve_target("https://example.com/not-bilibili")


# ---------- 2. creator fetch ----------


def test_creator_fetch_merges_videos_and_dynamics(monkeypatch):
    adapter = ba.BilibiliAdapter()
    signed_calls = _plain_signer(monkeypatch)
    get_calls = []

    def fake_get_json(url, **kwargs):
        get_calls.append((url, dict(kwargs)))
        if "arc/search" in url:
            return {
                "code": 0,
                "data": {
                    "list": {
                        "vlist": [
                            {
                                "bvid": "BV100",
                                "title": "最新视频",
                                "created": 300,
                                "pic": "http://i0.hdslb.com/2.jpg",
                                "description": "第二条",
                                "length": "12:00",
                                "play": 900,
                            },
                            {
                                "bvid": "BV099",
                                "title": "旧视频",
                                "created": 100,
                                "pic": "http://i0.hdslb.com/1.jpg",
                                "description": "第一条",
                                "length": "10:00",
                                "play": 800,
                            },
                        ]
                    }
                },
            }
        if "feed/space" in url:
            return {
                "code": 0,
                "data": {
                    "items": [
                        {
                            "id_str": "123456789012345678",
                            "modules": {
                                "module_dynamic": {
                                    "desc": {"text": "0123456789" * 6}
                                }
                            },
                        }
                    ]
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(ba, "http_get_json", fake_get_json)
    spec = _make_spec()

    result = asyncio.run(adapter.fetch_latest(spec, None, CTX))

    assert result.health_state == "healthy"
    assert result.error == ""
    assert [item.kind for item in result.items] == ["video", "video", "dynamic"]

    video1, video2, dynamic = result.items
    assert video1.item_id == "BV100"
    assert video1.title == "最新视频"
    assert video1.url == "https://www.bilibili.com/video/BV100"
    assert video1.author_name == "测试UP"
    assert video1.published_at == "300"
    assert video1.cover_url == "http://i0.hdslb.com/2.jpg"
    assert video1.stats == {"播放": 900}
    assert video2.item_id == "BV099"

    assert dynamic.item_id == "123456789012345678"
    assert dynamic.kind == "dynamic"
    assert dynamic.title == ("0123456789" * 6)[:40]

    assert result.new_cursor is not None
    assert result.new_cursor.last_item_id == "BV100"
    assert result.new_cursor.last_timestamp == "300"
    assert result.new_cursor.cursor_payload["dynamic_last_id"] == "123456789012345678"

    arc_signs = [call for call in signed_calls if "arc/search" in call[0]]
    assert len(arc_signs) == 1
    _, arc_params, cookie_header, proxy = arc_signs[0]
    assert arc_params == {"mid": "3577566", "pn": "1", "ps": "20"}
    assert cookie_header == "SESSDATA=test"
    assert proxy == "http://127.0.0.1:7890"

    feed_signs = [call for call in signed_calls if "feed/space" in call[0]]
    assert len(feed_signs) == 1
    _, feed_params, _, _ = feed_signs[0]
    assert feed_params == {
        "host_mid": "3577566",
        "offset": "0",
        "timezone_offset": "-480",
        "features": "itemOpusStyle",
    }

    arc_gets = [url for url, _ in get_calls if "arc/search" in url]
    assert len(arc_gets) == 1
    assert "mid=3577566" in arc_gets[0]
    assert "ps=20" in arc_gets[0]
    feed_gets = [url for url, _ in get_calls if "feed/space" in url]
    assert len(feed_gets) == 1
    assert all(kwargs.get("cookie") == "SESSDATA=test" for _, kwargs in get_calls)

    second = asyncio.run(adapter.fetch_latest(spec, result.new_cursor, CTX))
    assert second.items == []
    assert second.new_cursor is not None
    assert second.new_cursor.last_item_id == "BV100"


def test_creator_fetch_without_cookie_skips_dynamic_feed(monkeypatch):
    adapter = ba.BilibiliAdapter()
    _plain_signer(monkeypatch)

    def fake_get_json(url, **kwargs):
        if "arc/search" in url:
            return {
                "code": 0,
                "data": {
                    "list": {
                        "vlist": [
                            {
                                "bvid": "BV100",
                                "title": "最新视频",
                                "created": 300,
                                "pic": "",
                                "description": "",
                                "length": "12:00",
                                "play": 900,
                            }
                        ]
                    }
                },
            }
        raise AssertionError(f"cookie 为空时不应请求 feed/space: {url}")

    monkeypatch.setattr(ba, "http_get_json", fake_get_json)
    result = asyncio.run(
        adapter.fetch_latest(
            _make_spec(),
            None,
            {"cookie_header": "", "proxy": ""},
        )
    )

    assert [item.kind for item in result.items] == ["video"]
    assert result.health_state == "healthy"


# ---------- 3. bangumi ----------


def test_bangumi_ep_resolves_season_and_filters(monkeypatch):
    adapter = ba.BilibiliAdapter()
    calls = []

    def fake_get_json(url, **kwargs):
        calls.append(url)
        if "ep_id=ep1344093" in url:
            return {"code": 0, "result": {"season_id": 21542}}
        if "season_id=21542" in url:
            return {
                "code": 0,
                "result": {
                    "title": "测试番",
                    "new_ep": {"desc": "更新至第 3 话"},
                    "episodes": [
                        {
                            "id": 1,
                            "title": "第一话",
                            "long_title": "",
                            "share_url": "https://www.bilibili.com/bangumi/play/ep1",
                        },
                        {
                            "id": 2,
                            "title": "第二话",
                            "long_title": "",
                            "share_url": "https://www.bilibili.com/bangumi/play/ep2",
                        },
                        {
                            "id": 3,
                            "title": "",
                            "long_title": "最终回",
                            "share_url": "https://www.bilibili.com/bangumi/play/ep3",
                        },
                    ],
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(ba, "http_get_json", fake_get_json)
    spec = _make_spec(
        id="bilibili:bangumi:ep1344093",
        target_kind="bangumi",
        target_id="ep1344093",
        target_name="测试番",
    )

    result = asyncio.run(adapter.fetch_latest(spec, None, CTX))

    assert result.health_state == "healthy"
    assert [item.kind for item in result.items] == ["episode"] * 3
    assert [item.title for item in result.items] == [
        "测试番 最终回",
        "测试番 第二话",
        "测试番 第一话",
    ]
    assert result.items[0].url == "https://www.bilibili.com/bangumi/play/ep3"
    assert result.new_cursor is not None
    assert result.new_cursor.last_item_id == "3"
    assert any("ep_id=ep1344093" in url for url in calls)
    assert any("season_id=21542" in url for url in calls)

    second = asyncio.run(adapter.fetch_latest(spec, result.new_cursor, CTX))
    assert second.items == []
    assert second.new_cursor is not None
    assert second.new_cursor.last_item_id == "3"


# ---------- 4. favorite / collection ----------


def test_favorite_fetch_and_dedup(monkeypatch):
    adapter = ba.BilibiliAdapter()
    calls = []

    def fake_get_json(url, **kwargs):
        calls.append((url, dict(kwargs)))
        if "fav/resource/list" in url:
            return {
                "code": 0,
                "data": {
                    "medias": [
                        {
                            "id": 101,
                            "bvid": "BV200",
                            "title": "收藏视频2",
                            "cover": "http://i0.hdslb.com/c2.jpg",
                            "upper": {"mid": 3577566, "name": "UP主"},
                            "pubtime": 200,
                        },
                        {
                            "id": 100,
                            "bvid": "BV199",
                            "title": "收藏视频1",
                            "cover": "http://i0.hdslb.com/c1.jpg",
                            "upper": {"mid": 3577566, "name": "UP主"},
                            "pubtime": 100,
                        },
                    ]
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(ba, "http_get_json", fake_get_json)
    spec = _make_spec(
        id="bilibili:favorite:987",
        target_kind="favorite",
        target_id="987",
        target_name="收藏夹",
    )

    result = asyncio.run(adapter.fetch_latest(spec, None, CTX))

    assert [item.item_id for item in result.items] == ["BV200", "BV199"]
    assert all(item.kind == "video" for item in result.items)
    assert all(item.author_name == "UP主" for item in result.items)
    assert result.items[0].url == "https://www.bilibili.com/video/BV200"
    assert result.items[0].published_at == "200"
    assert result.items[0].cover_url == "http://i0.hdslb.com/c2.jpg"

    url, kwargs = calls[0]
    for needle in (
        "media_id=987",
        "pn=1",
        "ps=20",
        "platform=web",
        "web_location=333.1296",
    ):
        assert needle in url
    assert kwargs["cookie"] == "SESSDATA=test"

    assert result.new_cursor is not None
    assert result.new_cursor.last_item_id == "BV200"
    assert result.new_cursor.last_timestamp == "200"

    second = asyncio.run(adapter.fetch_latest(spec, result.new_cursor, CTX))
    assert second.items == []


def test_collection_fetch_with_sid_and_dedup(monkeypatch):
    adapter = ba.BilibiliAdapter()
    calls = []

    def fake_get_json(url, **kwargs):
        calls.append(url)
        if "seasons_archives_list" in url:
            return {
                "code": 0,
                "data": {
                    "archives": [
                        {
                            "bvid": "BV300",
                            "title": "合集第二集",
                            "cover": "http://i0.hdslb.com/s2.jpg",
                            "pubtime": 200,
                        },
                        {
                            "bvid": "BV299",
                            "title": "合集第一集",
                            "cover": "http://i0.hdslb.com/s1.jpg",
                            "pubtime": 100,
                        },
                    ]
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(ba, "http_get_json", fake_get_json)
    spec = _make_spec(
        id="bilibili:collection:101",
        target_kind="collection",
        target_id="101",
        target_name="123",
    )

    result = asyncio.run(adapter.fetch_latest(spec, None, CTX))

    assert [item.item_id for item in result.items] == ["BV300", "BV299"]
    assert all(item.kind == "video" for item in result.items)
    assert result.items[0].url == "https://www.bilibili.com/video/BV300"
    assert "mid=123" in calls[0]
    assert "season_id=101" in calls[0]

    assert result.new_cursor is not None
    assert result.new_cursor.last_item_id == "BV300"
    assert result.new_cursor.cursor_payload == {"season_id": "101", "mid": "123"}

    second = asyncio.run(adapter.fetch_latest(spec, result.new_cursor, CTX))
    assert second.items == []


def test_collection_fetch_without_sid_lists_first_season(monkeypatch):
    adapter = ba.BilibiliAdapter()
    calls = []

    def fake_get_json(url, **kwargs):
        calls.append(url)
        if "seasons_series_list" in url:
            return {
                "code": 0,
                "data": {
                    "items_lists": {
                        "seasons_list": [
                            {"season_id": 101, "name": "第一个合集"},
                            {"season_id": 102, "name": "第二个合集"},
                        ]
                    }
                },
            }
        if "seasons_archives_list" in url:
            return {
                "code": 0,
                "data": {
                    "archives": [
                        {
                            "bvid": "BV400",
                            "title": "第一集",
                            "cover": "http://i0.hdslb.com/s0.jpg",
                            "pubtime": 400,
                        }
                    ]
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(ba, "http_get_json", fake_get_json)
    spec = _make_spec(
        id="bilibili:collection:123",
        target_kind="collection",
        target_id="123",
        target_name="123",
    )

    result = asyncio.run(adapter.fetch_latest(spec, None, CTX))

    assert [item.item_id for item in result.items] == ["BV400"]
    assert "seasons_series_list?mid=123" in calls[0]
    assert "season_id=101" in calls[1]
    assert result.new_cursor is not None
    assert result.new_cursor.cursor_payload["season_id"] == "101"

    second = asyncio.run(adapter.fetch_latest(spec, result.new_cursor, CTX))
    assert second.items == []
    assert "seasons_series_list" not in calls[-1]


# ---------- 5. live ----------


def test_live_status_transitions_and_stable(monkeypatch):
    adapter = ba.BilibiliAdapter()
    statuses = iter([1, 1, 0, 0])

    def fake_get_json(url, **kwargs):
        assert "getInfoByRoom" in url
        assert "room_id=42" in url
        return {
            "code": 0,
            "data": {
                "room_info": {
                    "title": "直播测试间",
                    "live_status": next(statuses),
                    "online": 1234,
                    "area_name": "虚拟主播",
                    "live_start_time": 1750000000,
                }
            },
        }

    monkeypatch.setattr(ba, "http_get_json", fake_get_json)
    live_spec = _make_spec(
        id="bilibili:live_room:42",
        target_kind="live_room",
        target_id="42",
        target_name="直播测试间",
    )
    other_spec = _make_spec(
        id="bilibili:creator:1",
        target_kind="creator",
        target_id="1",
    )
    specs = [other_spec, live_spec]

    started = asyncio.run(adapter.fetch_live_statuses(specs, CTX))
    assert len(started) == 1
    candidate = started[0]
    assert candidate.spec_id == "bilibili:live_room:42"
    assert candidate.reason == "live_started"
    assert candidate.item.item_id == "live:42:1750000000"
    assert candidate.item.kind == "live"
    assert candidate.item.title == "直播测试间"
    assert candidate.item.url == "https://live.bilibili.com/42"
    assert candidate.item.summary == "直播测试间 开播了"

    assert asyncio.run(adapter.fetch_live_statuses(specs, CTX)) == []

    ended = asyncio.run(adapter.fetch_live_statuses(specs, CTX))
    assert len(ended) == 1
    assert ended[0].spec_id == "bilibili:live_room:42"
    assert ended[0].reason == "live_ended"
    assert ended[0].item.item_id == "liveend:42"

    assert asyncio.run(adapter.fetch_live_statuses(specs, CTX)) == []


def test_live_room_fetch_latest_returns_healthy_empty(monkeypatch):
    def fake_get_json(url, **kwargs):
        raise AssertionError("live_room fetch_latest 不应发请求")

    monkeypatch.setattr(ba, "http_get_json", fake_get_json)
    spec = _make_spec(
        id="bilibili:live_room:42",
        target_kind="live_room",
        target_id="42",
    )
    result = asyncio.run(ba.BilibiliAdapter().fetch_latest(spec, None, CTX))
    assert result.items == []
    assert result.health_state == "healthy"
    assert result.error == ""


# ---------- 6. 失败降级 ----------


def test_fetch_degraded_on_parse_error(monkeypatch):
    _plain_signer(monkeypatch)

    def fake_get_json(url, **kwargs):
        raise ParseHttpError("GET https://secret.example failed: SESSDATA=LEAKED")

    monkeypatch.setattr(ba, "http_get_json", fake_get_json)
    result = asyncio.run(
        ba.BilibiliAdapter().fetch_latest(_make_spec(), None, CTX)
    )

    assert result.items == []
    assert result.health_state == "degraded"
    assert result.error == "ParseHttpError"
    assert "SESSDATA" not in result.error
    assert "LEAKED" not in result.error


# ---------- 模块注册表 ----------


def test_module_registers_adapter():
    assert len(ba.ADAPTERS) == 1
    adapter = ba.ADAPTERS[0]
    assert isinstance(adapter, ba.BilibiliAdapter)
    assert adapter.platform == "bilibili"
    assert adapter.target_kinds == (
        "creator",
        "live_room",
        "bangumi",
        "favorite",
        "collection",
    )
    assert adapter.LIVE_POLL is True

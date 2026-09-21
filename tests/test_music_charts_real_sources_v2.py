"""真实音乐榜单 source（B6）：解析真实响应裁剪 fixture + 注册表状态断言。

全部离线：HTTP 层 monkeypatch，fixture 为 2026-09-12 只读探测捕获的真实响应
（仅裁剪行数，字段原样）。可达性探测记录：

- netease /api/playlist/detail?id=3778678 → HTTP 200（热歌榜，result.tracks）
- qq    musicu.fcg GetDetail topId=26    → HTTP 200（热歌榜，req_1.data.data.song）
- kugou mobilecdn /api/v3/rank/song?rankid=6666 → HTTP 200（飙升榜，data.info）
- kuwo bang songList 404 / kbangserver 403；apple RSS topsongs entries=0；
  spotify 需 OAuth credentials → 均注册为 unavailable + 原因。
"""
from __future__ import annotations

import asyncio

import pytest

from plugins.bot_unified_runtime.domains.core.contracts.music import MusicChartSnapshot
from plugins.bot_unified_runtime.domains.music.data.music_charts import (
    ChartSourceUnavailableError,
    KugouChartSource,
    MusicChartRegistry,
    NeteaseChartSource,
    QQMusicChartSource,
    UnavailableChartSource,
    build_default_music_chart_registry,
)

# ---- 真实响应裁剪 fixture（2026-09-12 探测捕获，字段原样）--------------------

_NETEASE_HOT_FIXTURE = {
    "code": 200,
    "result": {
        "id": 3778678,
        "name": "热歌榜",
        "trackCount": 200,
        "updateTime": 1789086534914,
        "tracks": [
            {
                "id": 1973665667,
                "name": "海屿你",
                "duration": 295940,
                "alias": ["求你别离开我"],
                "artists": [{"id": 13288861, "name": "马也_Crabbit"}],
                "album": {
                    "id": 150006421,
                    "name": "海屿你",
                    "picUrl": "http://p2.music.126.net/Enhy6dPn4gpyqrKhVEQvgA==/109951170483249998.jpg",
                },
            },
            {
                "id": 3399839173,
                "name": "甲乙丙丁 (你我怎么两清)",
                "duration": 210461,
                "alias": [],
                "artists": [{"id": 8753, "name": "李佳薇"}],
                "album": {
                    "id": 384452271,
                    "name": "甲乙丙丁",
                    "picUrl": "http://p2.music.126.net/H9iDvukTit_jx-fmhhvXUQ==/109951173482378749.jpg",
                },
            },
        ],
    },
}

_QQMUSIC_HOT_FIXTURE = {
    "code": 0,
    "req_1": {
        "code": 0,
        "data": {
            "data": {
                "topId": 26,
                "title": "热歌榜",
                "period": "2026-09-11",
                "updateTime": "2026-09-11",
                "listenNum": 19300000,
                "totalNum": 300,
                "song": [
                    {
                        "rank": 1,
                        "songId": 8136,
                        "title": "我不难过",
                        "singerName": "孙燕姿",
                        "albumMid": "004VSvF52mQoQp",
                        "cover": "https://y.gtimg.cn/music/photo_new/T002R300x300M000004VSvF52mQoQp_5.jpg",
                    },
                    {
                        "rank": 2,
                        "songId": 696262512,
                        "title": "甲乙丙丁 (你我怎么两清)",
                        "singerName": "李佳薇",
                        "albumMid": "00446QRA1fTdqA",
                        "cover": "",
                    },
                ],
            }
        },
    },
}

_KUGOU_SOARING_FIXTURE = {
    "data": {
        "timestamp": 1789156576,
        "total": 100,
        "info": [
            {
                "sort": 1,
                "hash": "955421D2C0B869B3D25116B3E0FA461C",
                "songname": "侧脸",
                "filename": "黄霄雲 - 侧脸",
                "duration": 217,
                "album_id": "206943192",
                "album_sizable_cover": "http://imge.kugou.com/stdmusic/{size}/20260908/20260908102211661337.jpg",
                "authors": [{"author_id": 194052, "author_name": "黄霄雲"}],
            },
            {
                "sort": 2,
                "hash": "29AE474BE2FE43E1815269FE89BDB12E",
                "songname": "难寄相思",
                "filename": "刘君 - 难寄相思",
                "duration": 211,
                "album_id": "170711383",
                "album_sizable_cover": "http://imge.kugou.com/stdmusic/{size}/20251218/20251218191124146162.jpg",
                "authors": [{"author_id": 192995, "author_name": "刘君"}],
            },
        ],
    }
}


# ---- netease -----------------------------------------------------------------


def test_netease_chart_source_parses_real_fixture(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_get_json(url: str, **kwargs):
        captured["url"] = url
        return _NETEASE_HOT_FIXTURE

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.music.data.music_charts.http_get_json", fake_get_json
    )
    source = NeteaseChartSource(source_id="netease-hot", category="热歌", chart_id="3778678")
    snapshot = asyncio.run(source.fetch_snapshot({"cookie_header": ""}))

    assert "api/playlist/detail?id=3778678" in captured["url"]
    assert isinstance(snapshot, MusicChartSnapshot)
    assert snapshot.source_id == "netease-hot"
    assert snapshot.platform == "netease"
    assert snapshot.source_type == "platform_toplist"
    assert snapshot.snapshot_id
    # 字段补全：排名/标题/歌手/封面/时长/链接（可获取即填）。
    first = snapshot.entries[0]
    assert (first.rank, first.provider_track_id, first.title) == (1, "1973665667", "海屿你")
    assert first.artist_names == ["马也_Crabbit"]
    assert first.album_name == "海屿你"
    assert first.artwork_url == (
        "http://p2.music.126.net/Enhy6dPn4gpyqrKhVEQvgA==/109951170483249998.jpg"
    )
    assert first.duration_ms == 295940
    assert first.url == "https://music.163.com/song?id=1973665667"
    second = snapshot.entries[1]
    assert second.rank == 2
    assert second.duration_ms == 210461
    assert second.artist_names == ["李佳薇"]


# ---- qqmusic -----------------------------------------------------------------


def test_qqmusic_chart_source_parses_real_fixture(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post_json(url: str, payload: object, **kwargs):
        captured["url"] = url
        captured["payload"] = payload
        return _QQMUSIC_HOT_FIXTURE

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.music.data.music_charts.http_post_json", fake_post_json
    )
    source = QQMusicChartSource(source_id="qqmusic-hot", category="热歌", chart_id="26")
    snapshot = asyncio.run(source.fetch_snapshot({}))

    assert captured["url"] == "https://u.y.qq.com/cgi-bin/musicu.fcg"
    param = captured["payload"]["req_1"]["param"]  # type: ignore[index]
    assert param["topId"] == 26 and param["num"] > 0
    # 榜单期号如实透传（GetDetail period 字段）。
    assert snapshot.period == "2026-09-11"
    assert snapshot.platform == "qqmusic"
    first = snapshot.entries[0]
    assert (first.rank, first.provider_track_id, first.title) == (1, "8136", "我不难过")
    assert first.artist_names == ["孙燕姿"]
    # cover 字段优先；缺失时回退 albumMid 封面模板。
    assert first.artwork_url == (
        "https://y.gtimg.cn/music/photo_new/T002R300x300M000004VSvF52mQoQp_5.jpg"
    )
    second = snapshot.entries[1]
    assert second.artwork_url == "https://y.gtimg.cn/music/photo_new/T002R500x500M00000446QRA1fTdqA.jpg"
    assert second.url == "https://i.y.qq.com/v8/playsong.html?songid=696262512"
    # GetDetail 不下发时长：诚实留空，不伪造。
    assert all(entry.duration_ms is None for entry in snapshot.entries)


# ---- kugou -------------------------------------------------------------------


def test_kugou_chart_source_parses_real_fixture(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_get_json(url: str, **kwargs):
        captured["url"] = url
        return _KUGOU_SOARING_FIXTURE

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.music.data.music_charts.http_get_json", fake_get_json
    )
    source = KugouChartSource(source_id="kugou-soaring", category="飙升", chart_id="6666")
    snapshot = asyncio.run(source.fetch_snapshot({}))

    assert "mobilecdn.kugou.com/api/v3/rank/song" in captured["url"]
    assert "rankid=6666" in captured["url"]
    assert snapshot.platform == "kugou"
    assert snapshot.period == ""  # 接口未下发期号，不把 timestamp 伪造成 period
    first = snapshot.entries[0]
    assert (first.rank, first.title) == (1, "侧脸")
    assert first.provider_track_id == "955421D2C0B869B3D25116B3E0FA461C"
    assert first.artist_names == ["黄霄雲"]
    # {size} 模板必须替换，占位不替换必裂图。
    assert first.artwork_url == (
        "http://imge.kugou.com/stdmusic/480/20260908/20260908102211661337.jpg"
    )
    # 酷狗下发秒，契约是毫秒。
    assert first.duration_ms == 217000
    assert first.url == "https://www.kugou.com/song/#hash=955421D2C0B869B3D25116B3E0FA461C"


# ---- 注册表状态（每个 source 标 real/unavailable + 原因）----------------------


def test_default_registry_describes_every_source_status() -> None:
    registry = build_default_music_chart_registry()
    described = registry.describe_sources()
    statuses = {row["source_id"]: row["status"] for row in described}
    reasons = {row["source_id"]: row["unavailability_reason"] for row in described}

    # 真实拉通 ≥2（实测 2026-09-12：网易云 2 + QQ 1 + 酷狗 2 = 5 个 real）。
    real_ids = [sid for sid, status in statuses.items() if status == "real"]
    assert set(real_ids) == {
        "netease-hot",
        "netease-soaring",
        "qqmusic-hot",
        "kugou-soaring",
        "kugou-electronic",
    }
    # 不可达平台如实标注原因，不硬造。
    assert statuses["kuwo-soaring"] == "unavailable"
    assert "404" in reasons["kuwo-soaring"] and "403" in reasons["kuwo-soaring"]
    assert statuses["apple-music-top"] == "unavailable"
    assert "entries" in reasons["apple-music-top"]
    assert statuses["spotify-top"] == "unavailable"
    assert "OAuth" in reasons["spotify-top"] or "credentials" in reasons["spotify-top"]
    # real source 不允许带不可达原因；unavailable 必须带非空原因。
    for row in described:
        if row["status"] == "real":
            assert row["unavailability_reason"] == ""
        else:
            assert row["unavailability_reason"].strip()
        assert row["platform"] and row["category"]


def test_registry_refresh_unavailable_source_raises_with_reason() -> None:
    registry = MusicChartRegistry(
        [UnavailableChartSource("kuwo-soaring", "kuwo", "飙升", "匿名接口 404/403")]
    )
    with pytest.raises(ChartSourceUnavailableError) as excinfo:
        asyncio.run(registry.refresh("kuwo-soaring", {}))
    assert "404/403" in excinfo.value.reason


def test_registry_filters_categories_and_describe_by_category() -> None:
    registry = build_default_music_chart_registry()
    soaring = registry.describe_sources(category="飙升")
    assert [row["source_id"] for row in soaring] == [
        "netease-soaring",
        "kugou-soaring",
        "kuwo-soaring",
    ]


def test_default_registry_refreshes_real_source_end_to_end(monkeypatch) -> None:
    """经默认注册表 refresh 拉真实源：类型校验 + 条目契约齐全。"""
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.music.data.music_charts.http_get_json",
        lambda url, **kwargs: _NETEASE_HOT_FIXTURE,
    )
    registry = build_default_music_chart_registry()
    snapshot = asyncio.run(registry.refresh("netease-hot", {"cookie_header": ""}))
    assert snapshot.source_id == "netease-hot"
    assert len(snapshot.entries) >= 1
    for entry in snapshot.entries:
        assert entry.provider_track_id and entry.title
        assert entry.rank >= 1

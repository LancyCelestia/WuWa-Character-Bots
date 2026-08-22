"""B 站 WBI 签名与深度链接解析的回归测试。

本文件全部测试都不访问网络：通过 monkeypatch 替换模块内的
``http_get_json`` / ``build_wbi_signed_url``，只验证解析逻辑与调用参数。
"""

from __future__ import annotations

import hashlib
import urllib.parse

from plugins.bot_unified_runtime.sources.parsers import wbi
from plugins.bot_unified_runtime.sources.parsers import platforms_bilibili as pb

IMG_URL = "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png"
SUB_URL = "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png"
MIXIN_KEY = "ea1db124af3c7062474693fa704f4ff8"


# ---------- WBI 签名 ----------


def test_extract_mixin_key_matches_salt_table():
    img_key = IMG_URL.rsplit("/", 1)[-1].removesuffix(".png")
    sub_key = SUB_URL.rsplit("/", 1)[-1].removesuffix(".png")
    raw = img_key + sub_key
    expected = "".join(raw[index] for index in wbi.WBI_KEY_TABLE[:32])

    assert wbi.extract_mixin_key(IMG_URL, SUB_URL) == expected
    assert wbi.extract_mixin_key(IMG_URL, SUB_URL) == MIXIN_KEY


def test_sign_wbi_fixed_wts_and_filters_reserved_chars():
    params = {"b": "世界", "a": "x!'()*y", "z": 5}
    wts = 1700000000

    result = wbi.sign_wbi(params, MIXIN_KEY, wts=wts)

    ordered = {"a": "x!'()*y", "b": "世界", "wts": wts, "z": 5}
    filtered = {
        key: "".join(ch for ch in str(value) if ch not in "!'()*")
        for key, value in ordered.items()
    }
    query = urllib.parse.urlencode(filtered)
    expected = hashlib.md5((query + MIXIN_KEY).encode("utf-8")).hexdigest()

    assert result["w_rid"] == expected
    assert result["wts"] == wts
    # 返回值保留原始参数（过滤只作用于签名串，不破坏业务参数）。
    assert result["a"] == "x!'()*y"
    assert set(result) == {"a", "b", "z", "wts", "w_rid"}


def test_build_wbi_signed_url_fetches_nav_and_signs(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        assert url == "https://api.bilibili.com/x/web-interface/nav"
        assert kwargs.get("referer") == "https://www.bilibili.com/"
        return {
            "code": 0,
            "data": {
                "wbi_img": {"img_url": IMG_URL, "sub_url": SUB_URL},
            },
        }

    monkeypatch.setattr(wbi, "http_get_json", fake_http_get_json)

    signed_url = wbi.build_wbi_signed_url(
        "https://api.bilibili.com/x/foo",
        {"id": 42, "name": "a b"},
    )
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(signed_url).query)

    assert query["id"] == ["42"]
    assert query["name"] == ["a b"]
    assert "wts" in query and "w_rid" in query

    expected = wbi.sign_wbi(
        {"id": 42, "name": "a b"},
        MIXIN_KEY,
        wts=int(query["wts"][0]),
    )
    assert query["w_rid"] == [expected["w_rid"]]


# ---------- 动态 opus ----------


def test_parse_opus_uses_wbi_signed_detail_api(monkeypatch):
    signed_calls: list[dict] = []

    def fake_build_wbi(url, params, *, cookie_header="", proxy=""):
        signed_calls.append(
            {
                "url": url,
                "params": dict(params),
                "cookie_header": cookie_header,
                "proxy": proxy,
            }
        )
        signed = {**params, "w_rid": "deadbeefcafe"}
        return url + "?" + urllib.parse.urlencode(signed)

    opus_payload = {
        "code": 0,
        "data": {
            "item": {
                "modules": {
                    "module_author": {"name": "测试UP"},
                    "module_dynamic": {
                        "desc": {"text": "今日动态"},
                        "major": {
                            "opus": {
                                "pics": [{"url": "https://i0.hdslb.com/pic.png"}]
                            }
                        },
                    },
                    "module_stat": {
                        "like": {"count": 100},
                        "comment": {"count": 20},
                        "forward": {"count": 5},
                    },
                }
            }
        },
    }
    requests: list[str] = []

    def fake_http_get_json(url, **kwargs):
        requests.append(url)
        return opus_payload

    monkeypatch.setattr(pb, "build_wbi_signed_url", fake_build_wbi)
    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb.parse_bilibili("https://www.bilibili.com/opus/123")

    assert item.item_kind == "dynamic"
    assert item.title == "今日动态"
    assert item.stats == {"点赞": 100, "评论": 20, "转发": 5}
    assert item.cover_url == "https://i0.hdslb.com/pic.png"
    assert "图片数量：1" in item.summary

    assert len(signed_calls) == 1
    assert signed_calls[0]["url"] == (
        "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/detail"
    )
    assert signed_calls[0]["params"] == {"timezone_offset": -480, "id": "123"}
    assert requests and "opus/detail" in requests[0]
    assert "w_rid=deadbeefcafe" in requests[0]


# ---------- 番剧 ----------


def test_parse_bangumi_ss_deep(monkeypatch):
    calls: list[str] = []

    def fake_http_get_json(url, **kwargs):
        calls.append(url)
        if "pgc/view/web/season" in url:
            return {
                "code": 0,
                "result": {
                    "season_id": 29342,
                    "title": "测试番剧",
                    "type_name": "番剧",
                    "areas": [{"name": "日本"}, {"name": "中国"}],
                    "season_title": "第 2 季",
                    "new_ep": {"desc": "全 12 话"},
                    "episodes": [{"id": 1}, {"id": 2}],
                    "evaluate": "这是一段用于回归测试的番剧简介。",
                    "cover": "https://i0.hdslb.com/bfs/bangumi.jpg",
                },
            }
        if "pgc/web/season/stat" in url:
            return {
                "code": 0,
                "result": {
                    "favorites": 1000,
                    "danmaku": 2000,
                    "views": 30000,
                    "coins": 400,
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb.parse_bilibili("https://www.bilibili.com/bangumi/play/ss29342")

    assert item.item_kind == "bangumi"
    assert item.title == "测试番剧"
    assert item.author_name == ""
    assert "类型：番剧" in item.summary
    assert "地区：日本、中国" in item.summary
    assert "集数/更新：全 12 话" in item.summary
    assert "简介：这是一段用于回归测试的番剧简介。" in item.summary
    assert item.stats == {"追番": 1000, "播放": 30000, "弹幕": 2000, "投币": 400}
    assert item.cover_url == "https://i0.hdslb.com/bfs/bangumi.jpg"
    assert any("pgc/view/web/season?season_id=29342" in url for url in calls)
    assert any("pgc/web/season/stat?season_id=29342" in url for url in calls)


def test_parse_bangumi_ep_backfills_season_id(monkeypatch):
    calls: list[str] = []

    def fake_http_get_json(url, **kwargs):
        calls.append(url)
        if "pgc/view/web/season" in url:
            return {
                "code": 0,
                "result": {
                    "season_id": 777,
                    "title": "测试电影",
                    "type_name": "电影",
                    "areas": [{"name": "日本"}],
                    "season_title": "",
                    "new_ep": {"desc": "已更新至第 1 话"},
                    "episodes": [{"id": 1}],
                    "evaluate": "电影简介",
                    "cover": "",
                },
            }
        if "pgc/web/season/stat" in url:
            return {
                "code": 0,
                "result": {
                    "favorites": 1,
                    "danmaku": 2,
                    "views": 3,
                    "coins": 4,
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb.parse_bilibili("https://www.bilibili.com/bangumi/play/ep12345")

    assert item.item_kind == "bangumi"
    assert item.item_id == "777"
    assert item.stats == {"追番": 1, "播放": 3, "弹幕": 2, "投币": 4}
    assert any("pgc/view/web/season?ep_id=12345" in url for url in calls)
    assert any("pgc/web/season/stat?season_id=777" in url for url in calls)


# ---------- 合集 / 全集列表 ----------


def test_parse_series_first_season_without_sid(monkeypatch):
    calls: list[str] = []

    def fake_http_get_json(url, **kwargs):
        calls.append(url)
        if "seasons_series_list" in url:
            return {
                "code": 0,
                "data": {
                    "items_lists": {
                        "seasons_list": [
                            {"season_id": 101, "name": "我的合集", "mid": 123},
                            {"season_id": 102, "name": "第二个合集", "mid": 123},
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
                            "title": "第一集",
                            "bvid": "BV1",
                            "cover": "https://i0.hdslb.com/1.jpg",
                            "pic": "",
                            "duration": 60,
                        },
                        {
                            "title": "第二集",
                            "bvid": "BV2",
                            "cover": "",
                            "pic": "https://i0.hdslb.com/2.jpg",
                            "duration": 90,
                        },
                    ],
                    "page": {"total": 8},
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb.parse_bilibili(
        "https://space.bilibili.com/123/channel/seriesdetail"
    )

    assert item.item_kind == "collection"
    assert item.item_id == "101"
    assert item.title == "我的合集"
    assert item.stats == {"视频数": 8}
    assert item.parse_depth == "deep"
    assert "1. 《第一集》" in item.summary
    assert "2. 《第二集》" in item.summary
    assert any("seasons_series_list?mid=123" in url for url in calls)
    assert any(
        "seasons_archives_list?mid=123&season_id=101" in url for url in calls
    )


def test_parse_series_from_list_ml_without_mid(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        if "seasons_archives_list" in url:
            return {
                "code": 0,
                "data": {
                    "archives": [
                        {
                            "title": "单集",
                            "bvid": "BV3",
                            "cover": "",
                            "pic": "https://i0.hdslb.com/3.jpg",
                            "duration": 10,
                        }
                    ],
                    "page": {"total": 1},
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb.parse_bilibili("https://www.bilibili.com/list/ml2048")

    assert item.item_kind == "collection"
    assert item.item_id == "2048"
    assert item.stats == {"视频数": 1}
    assert "1. 《单集》" in item.summary


# ---------- 直播间 / 空间 ----------


def test_parse_live_area_and_popularity(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        if "getInfoByRoom" in url:
            return {
                "code": 0,
                "data": {
                    "room_info": {
                        "title": "直播测试",
                        "cover": "",
                        "online": 12345,
                        "live_status": 1,
                        "parent_area_name": "游戏",
                        "area_name": "鸣潮",
                    },
                    "anchor_info": {"base_info": {"uname": "主播"}},
                },
            }
        return {"code": 0, "data": {}}

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb.parse_bilibili("https://live.bilibili.com/12345")

    assert item.item_kind == "live"
    assert item.stats["人气"] == 12345
    assert item.stats["在线人数"] == "1.2万"
    assert "分区：游戏 / 鸣潮" in item.summary


def test_parse_space_navnum_counts_into_stats(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        if "web-interface/card" in url:
            return {
                "code": 0,
                "data": {
                    "card": {
                        "name": "测试UP",
                        "sign": "签名",
                        "face": "https://i0.hdslb.com/face.jpg",
                    }
                },
            }
        if "space/navnum" in url:
            return {
                "code": 0,
                "data": {
                    "video": 120,
                    "following": 10,
                    "follower": 5000,
                    "article": 5,
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb.parse_bilibili("https://space.bilibili.com/3577566")

    assert item.item_kind == "user"
    assert item.stats == {"投稿": 120, "关注": 10, "粉丝": 5000, "专栏": 5}
    assert "作品：视频 120 · 专栏 5" in item.summary


# ---------- 分P 列表 ----------


def test_lookup_video_summary_lists_multipart(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        return {
            "code": 0,
            "data": {
                "bvid": "BV1xx411c7mB",
                "title": "合集视频",
                "owner": {"name": "UP"},
                "pic": "https://i0.hdslb.com/v.jpg",
                "desc": "",
                "pages": [
                    {"cid": 1, "part": "第一集", "duration": 65},
                    {"cid": 2, "part": "第二集", "duration": 125},
                    {"cid": 3, "part": "第三集", "duration": 3600},
                ],
                "stat": {"view": 1},
            },
        }

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb._lookup_video_by_id("BV1xx411c7mB", "bvid")

    assert item.item_kind == "video"
    assert "分P列表" in item.summary
    assert "P1《第一集》 1分5秒" in item.summary
    assert "P2《第二集》 2分5秒" in item.summary
    assert "P3《第三集》 60分0秒" in item.summary


def test_lookup_video_single_part_has_no_multipart_block(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        return {
            "code": 0,
            "data": {
                "bvid": "BV1xx411c7mB",
                "title": "单P视频",
                "owner": {"name": "UP"},
                "pic": "",
                "desc": "",
                "pages": [{"cid": 1, "part": "正片", "duration": 60}],
                "stat": {},
            },
        }

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb._lookup_video_by_id("BV1xx411c7mB", "bvid")

    assert "分P列表" not in item.summary


def test_parse_opus_real_detail_modules_list(monkeypatch):
    from plugins.bot_unified_runtime.sources.parsers.platforms_bilibili import (
        _parse_opus,
    )

    payload = {
        "code": 0,
        "data": {
            "item": {
                "id_str": "1238218464227754004",
                "basic": {"title": "鸣潮的图文动态", "uid": "1955897084"},
                "modules": [
                    {
                        "module_type": "MODULE_TYPE_AUTHOR",
                        "module_author": {"name": "鸣潮", "mid": 1955897084},
                    },
                    {
                        "module_type": "MODULE_TYPE_CONTENT",
                        "module_content": {
                            "paragraphs": [
                                {
                                    "para_type": 1,
                                    "text": {
                                        "nodes": [
                                            {"word": {"words": "新的动态正文"}},
                                            None,
                                            {"words": "，第二句"},
                                        ]
                                    },
                                },
                                {
                                    "para_type": 2,
                                    "pic": {
                                        "pics": [
                                            {"url": "https://i0.hdslb.com/x.png", "width": 1200, "height": 675}
                                        ]
                                    },
                                },
                            ]
                        },
                    },
                    {
                        "module_type": "MODULE_TYPE_STAT",
                        "module_stat": {
                            "like": {"count": 100},
                            "comment": {"count": 5},
                            "forward": {"count": 3},
                        },
                    },
                ],
            }
        },
    }

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_bilibili.build_wbi_signed_url",
        lambda url, params, **kw: url + "?signed=1",
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_bilibili.http_get_json",
        lambda url, **kw: payload,
    )

    item = _parse_opus("1238218464227754004", "https://www.bilibili.com/opus/1238218464227754004")

    assert item.item_kind == "dynamic"
    assert item.author_name == "鸣潮"
    assert item.title.startswith("新的动态正文")
    assert item.stats == {"点赞": 100, "评论": 5, "转发": 3}
    assert "图片数量：1" in item.summary
    assert "1200×675" in item.summary
    assert item.cover_url.endswith("x.png")


# ---------- PGC 细分 / 直播细节 / 动态图片与作者 ----------


def test_parse_bangumi_season_type_guochuang_detail(monkeypatch):
    calls: list[str] = []

    def fake_http_get_json(url, **kwargs):
        calls.append(url)
        if "pgc/view/web/season" in url:
            return {
                "code": 0,
                "result": {
                    "season_id": 999,
                    "season_type": 4,
                    "title": "测试国创",
                    "evaluate": "国创简介",
                    "episodes": [
                        {
                            "index": 1,
                            "long_title": "第1话 开端",
                            "duration": 7200000,
                            "cover": "https://i0.hdslb.com/ep1.jpg",
                        },
                        {
                            "index": 2,
                            "title": "第2话",
                            "duration": 1500,
                            "cover": "",
                        },
                    ],
                    "seasons": [
                        {"season_id": 998, "title": "第一季"},
                        {"season_id": 999, "season_title": "第二季"},
                    ],
                    "cover": "https://i0.hdslb.com/cover.jpg",
                },
            }
        if "pgc/web/season/stat" in url:
            return {
                "code": 0,
                "result": {"follow": 5200, "views": 999, "favorites": 100},
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb.parse_bilibili("https://www.bilibili.com/bangumi/play/ss999")

    assert item.item_kind == "bangumi"
    assert item.page_type == "guochuang"
    assert item.badge == "国创"
    assert item.detail["episodes"] == [
        {
            "index": 1,
            "title": "第1话 开端",
            "duration_seconds": 7200,
            "cover": "https://i0.hdslb.com/ep1.jpg",
        },
        {"index": 2, "title": "第2话", "duration_seconds": 1500},
    ]
    assert item.detail["related"] == [
        {"title": "第一季", "url": "https://www.bilibili.com/bangumi/play/ss998"},
        {"title": "第二季", "url": "https://www.bilibili.com/bangumi/play/ss999"},
    ]
    assert item.stats["追番"] == 5200


def test_parse_bangumi_season_type_mapping(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        if "pgc/view/web/season" in url:
            season_type = int(url.rsplit("season_id=", 1)[1])
            return {
                "code": 0,
                "result": {
                    "season_id": season_type,
                    "season_type": season_type,
                    "title": f"类型{season_type}",
                },
            }
        if "pgc/web/season/stat" in url:
            return {"code": 0, "result": {}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    expected = {
        1: ("bangumi", "番剧"),
        2: ("movie", "电影"),
        3: ("documentary", "纪录片"),
        5: ("tv", "电视剧"),
        7: ("variety", "综艺"),
    }
    for season_type, (page_type, badge) in expected.items():
        item = pb.parse_bilibili(
            f"https://www.bilibili.com/bangumi/play/ss{season_type}"
        )
        assert item.page_type == page_type
        assert item.badge == badge


def test_parse_bangumi_ep_has_page_type_and_episodes(monkeypatch):
    calls: list[str] = []

    def fake_http_get_json(url, **kwargs):
        calls.append(url)
        if "pgc/view/web/season" in url:
            return {
                "code": 0,
                "result": {
                    "season_id": 4242,
                    "season_type": 2,
                    "title": "测试电影",
                    "episodes": [
                        {
                            "index": 1,
                            "title": "正片",
                            "duration": 1800,
                            "cover": "https://i0.hdslb.com/movie.jpg",
                        }
                    ],
                },
            }
        if "pgc/web/season/stat" in url:
            return {"code": 0, "result": {"follow": 7}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb.parse_bilibili("https://www.bilibili.com/bangumi/play/ep4242")

    assert item.item_id == "4242"
    assert item.page_type == "movie"
    assert item.badge == "电影"
    assert item.detail["episodes"][0]["title"] == "正片"
    assert item.detail["episodes"][0]["duration_seconds"] == 1800
    assert any("pgc/view/web/season?ep_id=4242" in url for url in calls)


def test_parse_live_detail_fields(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        if "getInfoByRoom" in url:
            return {
                "code": 0,
                "data": {
                    "room_info": {
                        "title": "直播详情测试",
                        "cover": "https://i0.hdslb.com/live-cover.jpg",
                        "keyframe": "https://i0.hdslb.com/keyframe.jpg",
                        "online": 42,
                        "live_status": 1,
                        "live_start_time": 1750000000,
                        "parent_area_name": "游戏",
                        "area_name": "鸣潮",
                        "tags": ["二游", "实况"],
                        "description": "直播简介",
                    },
                    "anchor_info": {"base_info": {"uname": "主播"}},
                },
            }
        if "Room/get_info" in url:
            return {"code": -404, "message": "missing"}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb.parse_bilibili("https://live.bilibili.com/2077")

    live = item.detail["live"]
    assert live["area"] == "鸣潮"
    assert live["parent_area"] == "游戏"
    assert live["tags"] == ["二游", "实况"]
    assert live["cover"] == "https://i0.hdslb.com/live-cover.jpg"
    assert live["keyframe"] == "https://i0.hdslb.com/keyframe.jpg"
    assert live["title"] == "直播详情测试"
    assert live["start_time"] == 1750000000
    assert live["intro"] == "直播简介"


def test_parse_live_detail_missing_fields(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        if "getInfoByRoom" in url:
            return {
                "code": 0,
                "data": {
                    "room_info": {"online": 1, "live_status": 0},
                    "anchor_info": {"base_info": {}},
                },
            }
        if "Room/get_info" in url:
            return {"code": -404}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb.parse_bilibili("https://live.bilibili.com/1")

    assert item.item_kind == "live"
    assert item.detail == {}


def test_parse_opus_detail_images_and_author(monkeypatch):
    payload = {
        "code": 0,
        "data": {
            "item": {
                "modules": {
                    "module_author": {
                        "name": "图文UP",
                        "avatar": "https://i0.hdslb.com/face.png",
                        "signature": "签名内容",
                        "fans": 1234,
                    },
                    "module_dynamic": {
                        "desc": {"text": "多图动态"},
                        "major": {
                            "opus": {
                                "pics": [
                                    {"url": "https://i0.hdslb.com/p1.png"},
                                    {"url": "https://i0.hdslb.com/p2.png"},
                                ]
                            }
                        },
                    },
                    "module_stat": {"like": {"count": 1}},
                }
            }
        },
    }

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_bilibili.build_wbi_signed_url",
        lambda url, params, **kw: url + "?signed=1",
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_bilibili.http_get_json",
        lambda url, **kw: payload,
    )

    item = pb._parse_opus(
        "1238218464227754004",
        "https://www.bilibili.com/opus/1238218464227754004",
    )

    assert item.detail["images"] == [
        "https://i0.hdslb.com/p1.png",
        "https://i0.hdslb.com/p2.png",
    ]
    assert item.detail["author"] == {
        "name": "图文UP",
        "avatar": "https://i0.hdslb.com/face.png",
        "signature": "签名内容",
        "fans": 1234,
    }


def test_lookup_video_author_detail(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        return {
            "code": 0,
            "data": {
                "bvid": "BV1xx411c7mB",
                "title": "作者详情测试",
                "owner": {
                    "name": "视频UP",
                    "face": "https://i0.hdslb.com/face.png",
                },
                "card": {
                    "name": "视频UP",
                    "face": "https://i0.hdslb.com/face.png",
                    "sign": "视频签名",
                    "fans": 9999,
                },
                "pic": "",
                "desc": "",
                "pages": [{"cid": 1}],
                "stat": {},
            },
        }

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    item = pb._lookup_video_by_id("BV1xx411c7mB", "bvid")

    assert item.detail["author"]["name"] == "视频UP"
    assert item.detail["author"]["avatar"] == "https://i0.hdslb.com/face.png"
    assert item.detail["author"]["signature"] == "视频签名"
    assert item.detail["author"]["fans"] == 9999

"""H3b：douyin 正文话题（#xx）抽取 → ContentMetadata.tags（2026-09-13）。

承接 vis1-report §7 H3：tags chip 渲染钩子（bridge 投影 + universal_card
.topic-chip）前批已接线，本批补 douyin 解析器侧的话题抽取增量：
- 结构化话题节点优先（text_extra[].hashtag_name / cha_list / video_tag）；
- 无结构化节点时从 desc 正则提取 ``#xx``（含全角＃、emoji 相邻边界）；
- 去重保序、上限 10 个；无话题 payload 零变化。

全离线：直接喂真实感 _ROUTER_DATA HTML 片段给 _douyin_from_router_data。
"""

from __future__ import annotations

import json

from plugins.bot_unified_runtime.sources.parsers import platforms_generic

_VIDEO_URL = "https://www.douyin.com/video/7412345678901234567"


def _router_html(item: dict) -> str:
    """真实感抖音页面片段：window._ROUTER_DATA 内嵌 JSON。"""
    payload = {
        "loaderData": {
            "video_(id)/page": {
                "videoInfoRes": {"item_list": [item]},
            },
        },
    }
    return (
        "<!DOCTYPE html><html><head><script>"
        "window._ROUTER_DATA = " + json.dumps(payload, ensure_ascii=False) + ";"
        "</script></head><body></body></html>"
    )


def _base_item(desc: str, **extra: object) -> dict:
    item: dict = {
        "aweme_id": "7412345678901234567",
        "desc": desc,
        "create_time": 1757400000,
        "author": {"nickname": "守岸人", "unique_id": "shorekeeper"},
        "video": {"cover": {"url_list": ["https://p3-sign.douyinpic.com/x.jpeg"]}},
        "statistics": {"digg_count": 12, "comment_count": 3},
    }
    item.update(extra)
    return item


def _parse(item: dict):
    parsed = platforms_generic._douyin_from_router_data(_router_html(item), _VIDEO_URL)
    assert parsed is not None, "_ROUTER_DATA 深解析应命中"
    assert parsed.content is not None
    return parsed


# ==================== 结构化话题节点优先 ====================


def test_text_extra_hashtag_nodes_take_priority() -> None:
    """text_extra 话题节点直接抽取；desc 里额外的 #xx 不再混入。"""
    parsed = _parse(
        _base_item(
            "今天更新啦 #鸣潮 #守岸人 #被忽略的话题",
            text_extra=[
                {"hashtag_id": 1, "hashtag_name": "鸣潮"},
                {"hashtag_id": 2, "hashtag_name": "守岸人"},
                {"user_id": "9", "nickname": "某用户"},  # @人节点非话题
            ],
        )
    )
    assert parsed.content.tags == ["鸣潮", "守岸人"]


def test_cha_list_fallback_nodes() -> None:
    """无 text_extra 时读 cha_list 节点（dict 形态，老分享页）。"""
    parsed = _parse(
        _base_item(
            "看看 #鸣潮",
            cha_list={"1001": {"cha_name": "鸣潮"}, "1002": {"cha_name": "守岸人"}},
        )
    )
    assert parsed.content.tags == ["鸣潮", "守岸人"]


def test_structured_nodes_normalized_and_deduped() -> None:
    """结构化名去 # 前缀、去空、保序去重。"""
    parsed = _parse(
        _base_item(
            "混合",
            text_extra=[
                {"hashtag_name": "#鸣潮"},
                {"hashtag_name": ""},
                {"hashtag_name": "鸣潮"},
                {"hashtag_name": "＃守岸人"},
            ],
        )
    )
    assert parsed.content.tags == ["鸣潮", "守岸人"]


# ==================== desc 正则兜底抽取 ====================


def test_desc_regex_extraction_basic() -> None:
    parsed = _parse(
        _base_item("鸣潮今天更新啦 #鸣潮 #守岸人 #WutheringWaves 转发抽卡")
    )
    assert parsed.content.tags == ["鸣潮", "守岸人", "WutheringWaves"]


def test_desc_regex_fullwidth_hash() -> None:
    parsed = _parse(_base_item("＃鸣潮＃守岸人 #WuWa"))
    assert parsed.content.tags == ["鸣潮", "守岸人", "WuWa"]


def test_desc_regex_space_separated_and_adjacent_hash() -> None:
    parsed = _parse(_base_item("#鸣潮#守岸人  #末尾"))
    assert parsed.content.tags == ["鸣潮", "守岸人", "末尾"]


def test_desc_regex_emoji_adjacent_boundary() -> None:
    """emoji 紧邻话题：前导 emoji 不粘进话题，尾部 emoji 截断话题。"""
    parsed = _parse(_base_item("😀#鸣潮 #守岸人🎵 #WuWa😀末尾"))
    assert parsed.content.tags == ["鸣潮", "守岸人", "WuWa"]


def test_desc_regex_cap_ten() -> None:
    desc = " ".join(f"#话题{i}" for i in range(12))
    parsed = _parse(_base_item(desc))
    assert parsed.content.tags == [f"话题{i}" for i in range(10)]


def test_desc_truncated_after_extraction() -> None:
    """超长 desc：话题从原文取（截断前的完整文本），不因 300 字截断丢尾部话题。"""
    padding = "很长很长的正文" * 60  # > 300 字
    parsed = _parse(_base_item(padding + " #收尾话题"))
    assert "收尾话题" in parsed.content.tags


# ==================== 无话题 payload 零变化 ====================


def test_no_topics_payload_unchanged() -> None:
    desc = "纯正文没有任何话题，就随便说说今天的状态。"
    parsed = _parse(_base_item(desc))
    assert parsed.content.tags == []
    assert parsed.content.title == desc
    assert parsed.content.summary == ""
    assert parsed.identity.item_id == "7412345678901234567"
    assert parsed.creator.name == "守岸人"
    assert parsed.engagement.like_count == 12

"""VIS-FIX 统计瓦片标签分平台覆盖（2026-09-12）。

抖音语义：shares 瓦片标签应为「分享」（基准图口径）；其余平台
保持通用标签「转发」不变。只动 `_METRIC_DEFINITIONS` 的标签层，
数据抽取与瓦片结构零改动。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.contracts.media import build_parsed_content
from plugins.bot_unified_runtime.output.templates import card_payload_from_parse


def _stats_labels(platform: str, item_kind: str, stats: dict[str, object]) -> dict[str, object]:
    item = build_parsed_content(
        platform=platform,
        item_id="7412345678901234567",
        item_kind=item_kind,
        title="标题",
        canonical_url="https://www.example.com/video/7412345678901234567",
        stats=stats,
        parse_depth="deep",
    )
    payload = card_payload_from_parse(item)
    return {entry["label"]: entry["value"] for entry in payload["stats_bar_items"]}


def test_douyin_shares_tile_label_is_fenxiang() -> None:
    labels = _stats_labels(
        "douyin",
        "video",
        {"点赞": 6555, "评论": 118, "分享": 429, "播放": 152000, "收藏": 1025},
    )
    assert labels.get("分享") == 429
    assert "转发" not in labels


def test_bilibili_shares_tile_label_still_zhuanfa() -> None:
    labels = _stats_labels(
        "bilibili",
        "video",
        {"点赞": 100, "评论": 20, "转发": 33, "播放": 5000, "收藏": 10},
    )
    assert labels.get("转发") == 33
    assert "分享" not in labels


def test_other_platforms_keep_default_labels() -> None:
    # X（tweet 桶）与快照外平台均不走 douyin 覆盖。
    labels = _stats_labels("twitter", "tweet", {"reposts": 55, "likes": 900})
    assert labels.get("转发") == 55
    labels_generic = _stats_labels("kuaishou", "video", {"shares": 9, "likes": 80})
    assert labels_generic.get("转发") == 9

"""vis1r 移交项投影契约（H1-H4，2026-09-12）。

锁定 bridge 渲染投影增量（全离线 Jinja 渲染，无 playwright）：
- H1 清晰度角标：detail.video.width/height → video_quality（短边取档，
  行业口径 8K/4K/2K/1080P/720P/540P/480P/360P/240P；未知/过小返回空串整块隐藏；
  显式 video_quality 入参优先）；
- H2 音乐署名行：ParsedContent.music（MusicTrack）→ 模板玻璃署名条
  （♪ 歌名 · 作者；无 music 时整块隐藏）；
- H3 话题着色：content.tags（契约已有字段）→ 摘要块话题 chip（--pc accent）；
  正文中 #xx 的启发式抽取不属投影层，不做（无 tags 字段来源时无 chip）；
- H4 抖音大数字：parse_douyin 已抽取的 点赞/评论/分享/播放/收藏 经契约
  engagement → stats_bar_items 瓦片（验证既有接入，无需投影增量）。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.contracts.media import build_parsed_content
from plugins.bot_unified_runtime.contracts.music import MusicTrack
from plugins.bot_unified_runtime.output.card_render import bridge
from plugins.bot_unified_runtime.output.templates import (
    card_payload_from_parse,
    render_universal_card_html,
)

_VIDEO_BASE: dict[str, object] = {"page_type": "video", "name": "UP", "title": "标题"}


def _render(payload: dict[str, object]) -> str:
    return render_universal_card_html(payload)


def _render_parsed(item: object) -> str:
    return _render(card_payload_from_parse(item))


# ==================== H1 清晰度角标：宽高 → 画质文案映射表 ====================
@pytest.mark.parametrize(
    "width, height, expected",
    [
        (1920, 1080, "1080P"),
        (3840, 2160, "4K"),
        (2560, 1440, "2K"),
        (7680, 4320, "8K"),
        (1280, 720, "720P"),
        (960, 540, "540P"),
        (640, 480, "480P"),
        (640, 360, "360P"),
        (426, 240, "240P"),
        # 竖屏视频按短边计档（抖音 1080×1920 仍是 1080P，不是 2K）。
        (1080, 1920, "1080P"),
        (720, 1280, "720P"),
        # 非整档高度向下取档（B 站常见 1088 扫描线）。
        (1920, 1088, "1080P"),
        (2048, 1080, "1080P"),
        # 宽高缺任一边时单边档位有歧义（1920×? 可能 1080P 也可能 2K），
        # 宁可隐藏角标也不猜 → 空串。
        (1920, 0, ""),
        (0, 2160, ""),
        (0, 0, ""),
        (320, 180, ""),
    ],
)
def test_video_quality_tier_mapping(width: int, height: int, expected: str) -> None:
    assert bridge._format_video_quality(width, height) == expected


def test_quality_pill_renders_from_detail_video_size() -> None:
    html_text = _render(
        {
            **_VIDEO_BASE,
            "banner": "https://example.invalid/cover.jpg",
            "detail": {"video": {"width": 1920, "height": 1080}},
        }
    )
    assert '<span class="quality-pill">1080P</span>' in html_text


def test_quality_pill_hidden_without_dimensions() -> None:
    html_text = _render({**_VIDEO_BASE, "banner": "https://example.invalid/cover.jpg"})
    assert 'class="quality-pill"' not in html_text


def test_explicit_video_quality_overrides_projection() -> None:
    html_text = _render(
        {
            **_VIDEO_BASE,
            "banner": "https://example.invalid/cover.jpg",
            "video_quality": "HDR 4K",
            "detail": {"video": {"width": 1280, "height": 720}},
        }
    )
    assert '<span class="quality-pill">HDR 4K</span>' in html_text


# ==================== H2 音乐署名行 ====================
def _parsed_music_item() -> object:
    """镜像 platforms_music.parse_netease_song 产物形状（music= 带贡献者）。"""
    from plugins.bot_unified_runtime.contracts.music import MusicContributor

    return build_parsed_content(
        platform="netease",
        item_id="1901371647",
        item_kind="music",
        title="Cardcaptor",
        author_name="星尘、吟游诗人",
        canonical_url="https://music.163.com/song?id=1901371647",
        music=MusicTrack(
            provider="netease",
            provider_track_id="1901371647",
            title="Cardcaptor",
            contributors=[
                MusicContributor(name="星尘", roles=["performer"]),
                MusicContributor(name="吟游诗人", roles=["performer"]),
            ],
            album=None,
        ),
    )


def test_music_credit_renders_from_parsed_music() -> None:
    html_text = _render_parsed(_parsed_music_item())
    assert 'class="music-credit' in html_text
    assert '<span class="music-name">Cardcaptor</span>' in html_text
    assert '<span class="music-author">星尘、吟游诗人</span>' in html_text


def test_music_credit_hidden_without_music() -> None:
    item = build_parsed_content(
        platform="bilibili",
        item_id="BV1uvbL6iE8z",
        item_kind="video",
        title="标题",
    )
    html_text = _render_parsed(item)
    assert 'class="music-credit' not in html_text


def test_music_credit_survives_escaping() -> None:
    html_text = _render(
        {
            **_VIDEO_BASE,
            "music_name": '<script>alert("x")</script>',
            "music_author": "A&B",
        }
    )
    assert "<script>alert" not in html_text  # 模板自身的漂移相位 <script> 除外
    assert "&lt;script&gt;" in html_text
    assert "A&amp;B" in html_text


# ==================== H3 话题着色（tags 字段接线） ====================
def test_topic_chips_render_from_content_tags() -> None:
    item = build_parsed_content(
        platform="douyin",
        item_id="7412345678901234567",
        item_kind="video",
        title="标题",
        tags=["鸣潮", "守岸人"],
    )
    html_text = _render_parsed(item)
    assert '<span class="topic-chip">#鸣潮</span>' in html_text
    assert '<span class="topic-chip">#守岸人</span>' in html_text


def test_topic_chips_hidden_without_tags() -> None:
    item = build_parsed_content(
        platform="douyin",
        item_id="7412345678901234567",
        item_kind="video",
        title="标题",
    )
    html_text = _render_parsed(item)
    assert 'class="topic-chip"' not in html_text


def test_topic_chips_render_even_without_summary() -> None:
    item = build_parsed_content(
        platform="github",
        item_id="1",
        item_kind="article",
        title="repo",
        tags=["python"],
    )
    html_text = _render_parsed(item)
    assert '<span class="topic-chip">#python</span>' in html_text


def test_topic_chips_escape_hostile_tags() -> None:
    html_text = _render({**_VIDEO_BASE, "topics": ['<img src=x onerror=alert(1)>']})
    assert "<img src=x" not in html_text
    assert "#&lt;img" in html_text


# ==================== H4 抖音大数字（既有抽取 → 瓦片接入验证） ====================
def _parsed_douyin_item() -> object:
    """镜像 parse_douyin._douyin_from_router_data 产物形状（stats 中文标签）。"""
    return build_parsed_content(
        platform="douyin",
        item_id="7412345678901234567",
        item_kind="video",
        title="守岸人琴翻 #鸣潮 #守岸人",
        author_name="白玉妖",
        canonical_url="https://www.douyin.com/video/7412345678901234567",
        stats={
            "点赞": 6555,
            "评论": 118,
            "分享": 429,
            "播放": 152000,
            "收藏": 1025,
            "发布时间": "2026-09-01 20:14:33",
        },
        parse_depth="deep",
        detail={"author": {"uuid": "EasonForeverBYY"}},
    )


def test_douyin_engagement_flows_to_metric_tiles() -> None:
    payload = card_payload_from_parse(_parsed_douyin_item())
    labels = {item["label"]: item["value"] for item in payload["stats_bar_items"]}
    assert labels.get("播放") == 152000
    assert labels.get("点赞") == 6555
    assert labels.get("评论") == 118
    assert labels.get("收藏") == 1025
    assert labels.get("分享") == 429  # 分享经契约 share_count → shares 瓦片（douyin 平台标签覆盖）


def test_douyin_metric_tiles_render_big_numbers() -> None:
    html_text = _render_parsed(_parsed_douyin_item())
    # mica 分支瓦片 + fmt_count 中文量级（数字与单位间 U+2009 窄空格）。
    assert ">15.2\u2009万</span>" in html_text
    assert ">6555</span>" in html_text
    assert ">118</span>" in html_text
    assert ">1025</span>" in html_text
    assert ">429</span>" in html_text
    for label in ("播放", "点赞", "评论", "收藏", "分享"):
        assert f'<span class="metric-label">{label}</span>' in html_text

"""解析正文分区测试：标题无种类后缀、简介纯净、媒体参数无多余子弹符。"""

from plugins.bot_unified_runtime.capabilities.content_parser import _render_parse_body
from plugins.bot_unified_runtime.sources.parsers.types import PlatformParse


def _item():
    return PlatformParse(
        item_id="x",
        item_kind="video",
        platform="bilibili",
        title="我不在的日子里",
        author_name="柑宝",
        canonical_url="https://www.bilibili.com/video/BVxxx",
        stats={
            "播放": 183240,
            "点赞": 41784,
            "时长": "1分22秒",
            "发布时间": "2026-08-22",
        },
        summary="时长：1分22秒\n发布时间：2026-08-22\n简介：为你，千千万万次\n策划：柑宝",
    )


def test_title_has_no_kind_suffix():
    body = _render_parse_body(_item(), media_params=["分辨率：1920×1080"])
    assert "【标题】我不在的日子里" in body
    assert "（视频）" not in body


def test_duration_and_publish_time_move_out_of_summary():
    body = _render_parse_body(_item(), media_params=["分辨率：1920×1080"])
    summary_section = body.split("【简介】")[1].split("【媒体参数】")[0]
    assert "时长：" not in summary_section
    assert "发布时间：" not in summary_section
    assert "为你，千千万万次" in summary_section
    assert "【发布】2026-08-22" in body
    assert "时长 1分22秒" not in body.split("【发布】")[0]


def test_media_params_have_no_empty_bullet_lines():
    body = _render_parse_body(
        _item(),
        media_params=["分辨率：1920×1080", "", "音频码率：205kbps"],
    )
    media_section = body.split("【媒体参数】")[1]
    assert "\n  · \n" not in media_section
    assert "  · 分辨率：1920×1080" in media_section

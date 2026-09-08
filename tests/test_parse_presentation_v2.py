"""解析呈现层回归：发布时间到秒、AI 总结/热评空行分段、卡片热评块、点歌卡图。

背景（2026-09-09）：解析器数据层字段齐全但呈现层四处断点导致用户可见
输出缺秒、丢空行、无热评、点歌只剩语音——本文件锁定修复后的行为。
"""

from __future__ import annotations

import datetime
from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.content_parser import (
    _clean_summary,
    _format_publish_time,
)
from plugins.bot_unified_runtime.capabilities.music import build_music_capability
from plugins.bot_unified_runtime.contracts import SessionType, build_parsed_content
from plugins.bot_unified_runtime.contracts.runtime import IncomingMessage
from plugins.bot_unified_runtime.output.card_render.bridge import (
    render_universal_card_html,
)

# ---------- 发布时间（精确到秒） ----------

def test_format_publish_time_includes_seconds() -> None:
    aware = datetime.datetime(2026, 9, 7, 8, 30, 5, tzinfo=datetime.timezone.utc)
    assert _format_publish_time(aware).endswith(":05")
    naive = datetime.datetime(2026, 9, 7, 16, 30, 5)  # noqa: DTZ001 - 有意构造 naive 输入
    assert _format_publish_time(naive) == "2026-09-07 16:30:05"


# ---------- 简介空行分段（AI 总结 / 热门评论与原始简介之间） ----------

def test_clean_summary_keeps_blank_line_separators() -> None:
    raw = (
        "分区：数码\n"
        "时长：5分37秒\n"
        "发布时间：2026-09-07 16:30:05\n"
        "简介：原文简介\n"
        "\n"
        "AI总结：概要\n"
        "AI大纲：A / B\n"
        "\n"
        "热门评论：\n"
        "· 甲：评论一"
    )
    cleaned = _clean_summary(raw)
    assert cleaned.startswith("原文简介")
    assert "\n\nAI总结：" in cleaned
    assert "\n\n热门评论：" in cleaned
    assert "分区" not in cleaned
    assert "时长" not in cleaned
    assert "发布时间" not in cleaned


# ---------- 通用卡片：紧凑 video 卡渲染热评列表 ----------

def test_universal_card_renders_hot_comment_list() -> None:
    payload = {
        "title": "测试视频",
        "platform": "bilibili",
        "page_type": "video",
        "hot_comments": [
            {"author": "甲", "content": "评论一", "likes": "261"},
            {"author": "乙", "content": "评论二", "likes": "56"},
        ],
    }
    html = render_universal_card_html(payload)
    assert html.count(">热评<") == 2
    assert "评论一" in html
    assert "评论二" in html


def test_universal_card_renders_single_hot_comment_fallback() -> None:
    payload = {
        "title": "测试视频",
        "platform": "bilibili",
        "page_type": "video",
        "hot_comment": {"author": "甲", "content": "唯一热评", "likes": "9"},
    }
    html = render_universal_card_html(payload)
    assert html.count(">热评<") == 1
    assert "唯一热评" in html


# ---------- 点歌：卡图替代 CQ:music，语音部件保留 ----------

class _FakeRenderBackend:
    available = True

    def render_card(self, render_payload: dict) -> bytes:
        return b"png-bytes"


def _music_message(text: str = "点歌 我与你") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def _music_item() -> object:
    item = build_parsed_content(
        platform="netease_music",
        item_id="3347283669",
        item_kind="music",
        title="我与你",
        author_name="auburn",
        summary="专辑：飞向春天",
        canonical_url="https://music.163.com/song?id=3347283669",
        audio_url="http://m801.music.126.net/preview.mp3",
        cover_url="https://p1.music.126.net/cover.jpg",
        detail={"music_card": {"type": "163", "id": "3347283669"}},
    )
    return item


def test_music_hit_sends_card_image_and_voice_without_cq_music(tmp_path: Path) -> None:
    config = SimpleNamespace(
        bot_music_candidates_enabled=False,
        bot_music_candidates_ttl_seconds=300.0,
        bot_music_candidates_limit=5,
        bot_music_dir=str(tmp_path / "music"),
        bot_download_max_bytes=1024,
        bot_download_timeout_seconds=5,
        bot_download_proxy="",
        bot_card_render_dir=str(tmp_path / "cards"),
        bot_card_cache_max_bytes=0,
    )

    def search_fn(query: str):
        return _music_item()

    capability = build_music_capability(
        config,
        providers=[("netease_music", "网易云音乐", search_fn)],
        default_mode="card+voice+link",
        render_backend=_FakeRenderBackend(),
    )
    result = capability(_music_message(), None)

    assert result.images, "card+voice+link 模式必须产出渲染卡图"
    card_file = str(result.images[0].get("file") or "")
    assert card_file.endswith(".png")
    assert Path(card_file).is_file()
    part_types = [str(part.get("type")) for part in (result.audio or [])]
    assert part_types == ["record"], f"CQ:music 必须被卡图替代，实际：{part_types}"
    assert "♪ 我与你" in result.body


def test_music_hit_falls_back_to_cover_when_render_unavailable(tmp_path: Path) -> None:
    config = SimpleNamespace(
        bot_music_candidates_enabled=False,
        bot_music_candidates_ttl_seconds=300.0,
        bot_music_candidates_limit=5,
        bot_music_dir=str(tmp_path / "music"),
        bot_download_max_bytes=1024,
        bot_download_timeout_seconds=5,
        bot_download_proxy="",
        bot_card_render_dir=str(tmp_path / "cards"),
        bot_card_cache_max_bytes=0,
    )

    def search_fn(query: str):
        return _music_item()

    capability = build_music_capability(
        config,
        providers=[("netease_music", "网易云音乐", search_fn)],
        default_mode="card+voice+link",
        render_backend=None,
    )
    result = capability(_music_message(), None)

    assert result.images, "渲染后端不可用时应回退封面直链"
    cover = str(result.images[0].get("file") or "")
    assert cover.startswith("http")
    part_types = [str(part.get("type")) for part in (result.audio or [])]
    assert "record" in part_types


# ---------- help 索引：二级展开引导 ----------

def test_help_index_contains_second_level_hint() -> None:
    from plugins.bot_unified_runtime.capabilities.echo import _help_index_body

    body = _help_index_body(page=1, is_admin=True)
    assert "【子功能】" in body
    assert "/bot help 点歌" in body
    assert "/bot help 订阅" in body

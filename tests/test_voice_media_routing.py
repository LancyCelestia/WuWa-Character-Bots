"""评审需求回归：语音消息 + 多媒体（图片/GIF/视频）入站识别。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_voice_media_routing.py -q

覆盖的实测缺口（评审报告「需求 3/4」）：
  - **纯语音不可达**：plain_text 为空 → base_router 判 IGNORE →
    `_is_plain_chat_event` 因 visual_types 不含 record 而 False → chat handler
    根本不触发 → ASR（链路本身完好）永远跑不到。用户发语音 = 静默无响应。
  - **Telegram 语音不识别**：TG 段是 `voice`/`audio`，取源只认 `record`。
  - **Telegram 动图/贴纸/圆形视频不识别**：不在 `_IMAGE_SEGMENT_TYPES` 内。
"""
from __future__ import annotations

from plugins.bot_unified_runtime import (
    AUDIO_SEGMENT_TYPES,
    contains_audio_message_segments,
    contains_visual_message_segments,
)
from plugins.bot_unified_runtime.message_context import normalize_message_segments
from plugins.bot_unified_runtime.sources.transcribe import extract_audio_source
from plugins.bot_unified_runtime.sources.vision_describe import (
    _IMAGE_SEGMENT_TYPES,
    _VIDEO_SEGMENT_TYPES,
)

# ------------------------------------------------------------------ 门禁放行


def test_pure_voice_segment_is_recognized_as_audio() -> None:
    """纯语音必须被识别为音频段，否则门禁会把它当空消息丢掉。"""
    segments = [{"type": "record", "data": {"file": "a.silk", "url": "http://x/a.silk"}}]
    assert contains_audio_message_segments(segments) is True
    # 语音不是"视觉"段——两者语义必须分开，占位文案才能各自命名。
    assert contains_visual_message_segments(segments) is False


def test_telegram_voice_and_audio_segments_recognized() -> None:
    for kind in ("voice", "audio"):
        segments = [{"type": kind, "data": {"file": "file_id_123"}}]
        assert contains_audio_message_segments(segments) is True, kind


def test_non_audio_segments_not_flagged() -> None:
    for segments in ([], None, [{"type": "text", "data": {"text": "hi"}}]):
        assert contains_audio_message_segments(segments) is False


def test_audio_segment_types_cover_both_adapters() -> None:
    assert {"record", "voice", "audio"} <= set(AUDIO_SEGMENT_TYPES)


def test_visual_segments_still_recognized() -> None:
    for kind in ("image", "face", "mface", "marketface", "sticker", "video"):
        assert contains_visual_message_segments([{"type": kind, "data": {}}]) is True, kind


# --------------------------------------------------------------- 标签归一化


def test_media_labels_normalized_across_adapters() -> None:
    """OneBot 与 Telegram 的媒体段都要产出可读标签。"""
    cases = {
        "image": "[图片]",
        "photo": "[图片]",
        "sticker": "[表情包]",
        "animation": "[动图]",
        "video_note": "[圆形视频]",
        "record": "[语音]",
        "voice": "[语音]",
        "audio": "[音频]",
        "video": "[视频]",
    }
    for kind, expected in cases.items():
        normalized = normalize_message_segments([{"type": kind, "data": {}}])
        assert expected in normalized.plain_text, f"{kind} -> {normalized.plain_text!r}"


def test_voice_only_message_gets_placeholder_text() -> None:
    """纯语音消息经归一化后有文本（占位标签），不再是空串。"""
    normalized = normalize_message_segments(
        [{"type": "record", "data": {"file": "a.silk"}}]
    )
    assert normalized.plain_text.strip()
    assert "[语音]" in normalized.plain_text


# ------------------------------------------------------------------ 取源


def test_extract_audio_source_accepts_telegram_voice() -> None:
    """取源必须认 Telegram 的 voice 段（此前只认 record，直接穿透）。"""
    segments = [{"type": "voice", "data": {"file": "http://example.com/v.ogg"}}]
    assert extract_audio_source(segments) == "http://example.com/v.ogg"


def test_extract_audio_source_accepts_telegram_audio() -> None:
    segments = [{"type": "audio", "data": {"file": "http://example.com/a.mp3"}}]
    assert extract_audio_source(segments) == "http://example.com/a.mp3"


def test_extract_audio_source_accepts_onebot_record() -> None:
    segments = [{"type": "record", "data": {"url": "http://example.com/r.silk"}}]
    assert extract_audio_source(segments) == "http://example.com/r.silk"


def test_extract_audio_source_ignores_non_audio() -> None:
    assert extract_audio_source([{"type": "image", "data": {"url": "http://x/a.png"}}]) is None
    assert extract_audio_source(None) is None


# ------------------------------------------------------------ 视觉段类型集合


def test_image_segment_types_cover_telegram_visuals() -> None:
    assert {"photo", "sticker", "animation", "video_note"} <= set(_IMAGE_SEGMENT_TYPES)


def test_image_segment_types_keep_onebot_originals() -> None:
    assert {"image", "mface"} <= set(_IMAGE_SEGMENT_TYPES)


def test_video_segment_types_unchanged() -> None:
    assert "video" in _VIDEO_SEGMENT_TYPES

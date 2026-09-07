from __future__ import annotations

from plugins.bot_unified_runtime import contains_visual_message_segments


def test_visual_message_segments_detect_image_and_sticker():
    assert contains_visual_message_segments([
        {"type": "image", "data": {"url": "https://img.example/a.png"}},
    ]) is True
    assert contains_visual_message_segments([
        {"type": "face", "data": {"id": "123"}},
    ]) is True


def test_visual_message_segments_ignore_plain_text_and_audio():
    assert contains_visual_message_segments([
        {"type": "text", "data": {"text": "你好"}},
        {"type": "record", "data": {"url": "https://audio.example/a.mp3"}},
    ]) is False
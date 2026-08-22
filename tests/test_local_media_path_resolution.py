from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.sender.onebot import build_onebot_message_segments


def _local_media_send_request(
    *,
    content_type: str,
    content_ref: dict[str, Any],
    text: str = "本地媒体发送失败时的降级文本。",
) -> SendRequest:
    rendered = RenderedOutput(
        request_id="req_local_media",
        content_type=content_type,
        content_ref=content_ref,
        text_fallback=text,
    )
    return SendRequest(
        request_id="req_local_media",
        session_id="private_42",
        target_scope=SessionType.PRIVATE,
        target_id="42",
        origin_message_id="origin_local_media",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="bot.chat:42:local-media",
        cooldown_key="bot.chat:42",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_forward=False,
        persona_profile_id="shorekeeper",
    )


def test_image_local_relative_file_is_resolved_to_absolute_path(tmp_path, monkeypatch):
    card = tmp_path / "card_abc.png"
    card.write_bytes(b"png-bytes")
    monkeypatch.chdir(tmp_path)

    send_request = _local_media_send_request(
        content_type="image",
        content_ref={"file": "card_abc.png"},
    )

    segments = build_onebot_message_segments(send_request)

    assert segments == [
        {"type": "image", "data": {"file": str(card.resolve())}}
    ]


def test_record_and_video_local_relative_files_are_resolved_to_absolute_paths(
    tmp_path, monkeypatch
):
    audio = tmp_path / "voice_abc.amr"
    audio.write_bytes(b"amr-bytes")
    video = tmp_path / "clip_abc.mp4"
    video.write_bytes(b"mp4-bytes")
    monkeypatch.chdir(tmp_path)

    send_request = _local_media_send_request(
        content_type="mixed",
        content_ref={
            "parts": [
                {"type": "record", "file": "voice_abc.amr"},
                {
                    "type": "video",
                    "file": "clip_abc.mp4",
                    "cover": "https://example.com/cover.jpg",
                },
            ]
        },
    )

    segments = build_onebot_message_segments(send_request)

    assert segments == [
        {"type": "record", "data": {"file": str(audio.resolve())}},
        {
            "type": "video",
            "data": {
                "file": str(video.resolve()),
                "cover": "https://example.com/cover.jpg",
            },
        },
    ]


def test_https_file_reference_stays_unchanged():
    send_request = _local_media_send_request(
        content_type="image",
        content_ref={"file": "https://example.com/a.png"},
    )

    segments = build_onebot_message_segments(send_request)

    assert segments == [
        {"type": "image", "data": {"file": "https://example.com/a.png"}}
    ]


def test_base64_file_reference_stays_unchanged():
    send_request = _local_media_send_request(
        content_type="image",
        content_ref={"file": "base64://aW1hZ2UtYnl0ZXM="},
    )

    segments = build_onebot_message_segments(send_request)

    assert segments == [
        {"type": "image", "data": {"file": "base64://aW1hZ2UtYnl0ZXM="}}
    ]


@pytest.mark.parametrize(
    "file_ref",
    [
        "file:///tmp/shorekeeper-card.png",
        "data:image/png;base64,AAAA",
    ],
)
def test_file_scheme_and_data_uri_references_stay_unchanged(file_ref):
    send_request = _local_media_send_request(
        content_type="image",
        content_ref={"file": file_ref},
    )

    segments = build_onebot_message_segments(send_request)

    assert segments == [{"type": "image", "data": {"file": file_ref}}]


def test_missing_local_relative_path_stays_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    send_request = _local_media_send_request(
        content_type="image",
        content_ref={"file": "missing/card_abc.png"},
    )

    segments = build_onebot_message_segments(send_request)

    assert segments == [
        {"type": "image", "data": {"file": "missing/card_abc.png"}}
    ]


def test_mixed_segments_resolve_only_local_media_file_refs(tmp_path, monkeypatch):
    card = tmp_path / "card_abc.png"
    card.write_bytes(b"png-bytes")
    audio = tmp_path / "voice_abc.amr"
    audio.write_bytes(b"amr-bytes")
    video = tmp_path / "clip_abc.mp4"
    video.write_bytes(b"mp4-bytes")
    monkeypatch.chdir(tmp_path)

    send_request = _local_media_send_request(
        content_type="mixed",
        content_ref={
            "parts": [
                {"type": "text", "text": "先看这张卡片。"},
                {"type": "image", "file": "card_abc.png"},
                {"type": "record", "file": "voice_abc.amr"},
                {
                    "type": "video",
                    "file": "clip_abc.mp4",
                    "cover": "https://example.com/cover.jpg",
                },
                {"type": "image", "file": "https://example.com/remote.png"},
            ]
        },
    )

    segments = build_onebot_message_segments(send_request)

    assert segments == [
        {"type": "text", "data": {"text": "先看这张卡片。"}},
        {"type": "image", "data": {"file": str(card.resolve())}},
        {"type": "record", "data": {"file": str(audio.resolve())}},
        {
            "type": "video",
            "data": {
                "file": str(video.resolve()),
                "cover": "https://example.com/cover.jpg",
            },
        },
        {"type": "image", "data": {"file": "https://example.com/remote.png"}},
    ]

def test_file_segment_resolves_local_audio_file_path(tmp_path, monkeypatch):
    audio = tmp_path / "song_abc.mp3"
    audio.write_bytes(b"mp3-bytes")
    monkeypatch.chdir(tmp_path)

    send_request = _local_media_send_request(
        content_type="mixed",
        content_ref={"parts": [{"type": "file", "file": "song_abc.mp3"}]},
    )

    segments = build_onebot_message_segments(send_request)

    assert segments == [
        {"type": "file", "data": {"file": str(audio.resolve())}}
    ]

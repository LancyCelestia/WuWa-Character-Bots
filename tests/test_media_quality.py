"""媒体选流器（用户媒体质量要求）：杜比视界>HDR>SDR、Hi-Res/杜比音频、1GB 回退。"""

from __future__ import annotations

from plugins.bot_unified_runtime.sources.downloader import select_media_streams


def _v(
    height: int,
    *,
    tbr: float = 5000,
    dr: str = "SDR",
    fps: float = 30,
    size: int = 0,
) -> dict:
    return {
        "vcodec": "avc1",
        "acodec": "none",
        "height": height,
        "width": height * 16 // 9,
        "fps": fps,
        "tbr": tbr,
        "dynamic_range": dr,
        "format_id": f"v{height}-{dr}",
        "filesize": size,
    }


def _a(*, codec: str = "mp4a.40.2", abr: float = 128, size: int = 0) -> dict:
    return {
        "vcodec": "none",
        "acodec": codec,
        "abr": abr,
        "asr": 44100,
        "format_id": f"a-{codec}-{abr}",
        "filesize": size,
    }


def test_prefers_dolby_vision_over_hdr_over_sdr_at_same_height() -> None:
    formats = [_v(1080), _v(1080, dr="HDR10"), _v(1080, dr="DOLBY VISION")]
    video, _audio, _note = select_media_streams(formats, max_bytes=0)
    assert video is not None
    assert video["dynamic_range"] == "DOLBY VISION"


def test_height_dominates_then_dynamic_range() -> None:
    formats = [_v(2160), _v(1080, dr="DOLBY VISION")]
    video, _audio, _note = select_media_streams(formats, max_bytes=0)
    assert video is not None
    assert video["height"] == 2160


def test_audio_prefers_lossless_then_dolby_then_bitrate() -> None:
    formats = [_a(abr=320), _a(codec="ec-3", abr=640), _a(codec="flac", abr=1000)]
    _video, audio, _note = select_media_streams(formats, max_bytes=0)
    assert audio is not None
    assert audio["acodec"] == "flac"
    _video2, audio2, _note2 = select_media_streams(
        [_a(abr=128), _a(codec="ec-3", abr=384)], max_bytes=0
    )
    assert audio2 is not None
    assert audio2["acodec"] == "ec-3"


def test_falls_back_below_max_bytes() -> None:
    formats = [
        _v(2160, size=1_500_000_000),
        _v(1080, size=800_000_000),
        _a(size=100_000_000),
    ]
    video, audio, note = select_media_streams(formats, max_bytes=1_000_000_000)
    assert note == ""
    assert video is not None and video["height"] == 1080
    assert audio is not None


def test_over_limit_returns_none_instead_of_silent_low_quality() -> None:
    formats = [_v(1080, size=2_000_000_000), _a(size=200_000_000)]
    video, audio, note = select_media_streams(formats, max_bytes=1_000_000_000)
    assert video is None
    assert audio is None
    assert note == "over_limit"


def test_estimates_size_from_bitrate_when_filesize_missing() -> None:
    formats = [
        {
            "vcodec": "avc1",
            "acodec": "none",
            "height": 1080,
            "tbr": 8000,
            "dynamic_range": "SDR",
            "fps": 30,
            "format_id": "v1",
        },
        {
            "vcodec": "none",
            "acodec": "mp4a.40.2",
            "abr": 128,
            "tbr": 128,
            "format_id": "a1",
        },
    ]
    video, _audio, note = select_media_streams(
        formats, duration_seconds=600, max_bytes=1_000_000_000
    )
    assert note == ""
    assert video is not None
    _video2, _audio2, note2 = select_media_streams(
        formats, duration_seconds=2000, max_bytes=1_000_000_000
    )
    assert note2 == "over_limit"


def test_no_streams_reports_reason() -> None:
    video, audio, note = select_media_streams([], max_bytes=0)
    assert video is None and audio is None and note == "no_streams"

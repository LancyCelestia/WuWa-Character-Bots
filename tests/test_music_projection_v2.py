from __future__ import annotations

from plugins.bot_unified_runtime.contracts.media import (
    build_parsed_content,
)


def test_music_parser_projection_creates_track_for_basic_provider_result() -> None:
    item = build_parsed_content(
        platform="qqmusic",
        item_id="mid-1",
        item_kind="music",
        title="歌曲",
        author_name="歌手A、歌手B",
        cover_url="https://img.example/cover.jpg",
        audio_url="https://audio.example/song.mp3",
        canonical_url="https://y.qq.com/song/mid-1",
    )

    assert item.music is not None
    assert item.music.provider == "qqmusic"
    assert item.music.provider_track_id == "mid-1"
    assert item.music.title == "歌曲"
    assert [person.name for person in item.music.contributors] == ["歌手A", "歌手B"]
    assert item.music.artwork_url == "https://img.example/cover.jpg"
    assert item.music.audio_url == "https://audio.example/song.mp3"

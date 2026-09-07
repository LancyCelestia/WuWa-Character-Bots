from __future__ import annotations

from plugins.bot_unified_runtime.capabilities.music import build_music_capability
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.music_request_store import MusicRequestStore


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def test_music_capability_records_only_final_successful_provider(tmp_path) -> None:
    store = MusicRequestStore(str(tmp_path / "music_analytics.sqlite3"))

    def failed(_query: str) -> None:
        return None

    def succeeded(_query: str) -> ParsedContent:
        return build_parsed_content(
            platform="qqmusic",
            item_id="q-1",
            item_kind="music",
            title="测试歌曲",
            author_name="测试歌手",
            canonical_url="https://y.qq.com/song/q-1",
        )

    capability = build_music_capability(
        providers=[("netease_music", "网易云", failed), ("qqmusic", "QQ音乐", succeeded)],
        request_store=store,
        audio_downloader=lambda _url: None,
    )
    result = capability(_message("点歌 测试歌曲"), None)

    assert result.title == "测试歌曲"
    assert store.count_events() == 1
    assert store.events()[0].provider == "qqmusic"
    assert store.events()[0].provider_track_id == "q-1"


def test_empty_request_store_stays_empty_without_capability_calls(tmp_path) -> None:
    store = MusicRequestStore(str(tmp_path / "music_analytics.sqlite3"))
    assert store.count_events() == 0

from __future__ import annotations

from plugins.bot_unified_runtime.sources.parsers import platforms_music


def test_netease_detail_maps_aliases_duration_album_and_contributors(monkeypatch) -> None:
    def fake_get_json(url: str, **kwargs):
        if "/api/song/lyric" in url:
            return {"lrc": {"lyric": "[00:01.00]歌词"}, "tlyric": {"lyric": ""}}
        if "/api/v1/resource/comments/" in url:
            return {"total": 321}
        return {
            "songs": [
                {
                    "id": 123,
                    "name": "测试歌曲",
                    "alias": ["别名一", "别名二"],
                    "dt": 231000,
                    "pop": 88,
                    "ar": [
                        {"id": 1, "name": "演唱者"},
                        {"id": 2, "name": "合作歌手"},
                    ],
                    "al": {
                        "id": 456,
                        "name": "测试专辑",
                        "picUrl": "https://img.example/cover.jpg",
                    },
                    "publishTime": 1700000000000,
                }
            ]
        }

    monkeypatch.setattr(platforms_music, "http_get_json", fake_get_json)
    monkeypatch.setattr(platforms_music, "_netease_audio_url", lambda *args, **kwargs: "")

    result = platforms_music._netease_song_detail("123")

    assert result.music is not None
    assert result.music.title == "测试歌曲"
    assert result.music.aliases == ["别名一", "别名二"]
    assert result.music.duration_ms == 231000
    assert result.music.album is not None
    assert result.music.album.provider_album_id == "456"
    assert result.music.engagement.comment_count == 321
    assert result.music.engagement.popularity == 88
    assert {item.name for item in result.music.contributors} == {"演唱者", "合作歌手"}
    assert result.music.lyrics["original"] == "[00:01.00]歌词"


def test_netease_missing_global_collection_is_explicitly_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        platforms_music,
        "http_get_json",
        lambda url, **kwargs: {"songs": [{"id": 1, "name": "歌", "ar": [], "al": {}}]},
    )
    monkeypatch.setattr(platforms_music, "_netease_audio_url", lambda *args, **kwargs: "")

    result = platforms_music._netease_song_detail("1")

    assert result.music is not None
    assert result.music.engagement.favorite_count is None
    assert result.music.limitations["engagement.favorite_count"] == "provider_not_exposed"

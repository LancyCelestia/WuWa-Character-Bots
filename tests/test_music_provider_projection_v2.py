from __future__ import annotations

from plugins.bot_unified_runtime.sources.parsers import platforms_music


def test_qq_search_maps_duration_album_and_multiple_artists(monkeypatch) -> None:
    monkeypatch.setattr(
        platforms_music,
        "http_get_json",
        lambda url, **kwargs: {
            "data": {
                "song": {
                    "list": [
                        {
                            "mid": "qq-1",
                            "songname": "QQ 歌曲",
                            "albumname": "QQ 专辑",
                            "albumid": 11,
                            "interval": 215,
                            "singer": [
                                {"id": 1, "name": "歌手甲"},
                                {"id": 2, "name": "歌手乙"},
                            ],
                        }
                    ]
                }
            }
        },
    )
    monkeypatch.setattr(platforms_music, "_qqmusic_vkey_url", lambda *args, **kwargs: "")

    result = platforms_music.search_qqmusic("QQ 歌曲")

    assert result is not None and result.music is not None
    assert result.music.duration_ms == 215000
    assert result.music.album is not None
    assert result.music.album.provider_album_id == "11"
    assert [item.name for item in result.music.contributors] == ["歌手甲", "歌手乙"]


def test_apple_lookup_maps_track_length_release_date_and_genre(monkeypatch) -> None:
    monkeypatch.setattr(
        platforms_music,
        "http_get_json",
        lambda url, **kwargs: {
            "results": [
                {
                    "trackId": 10,
                    "trackName": "Apple 歌曲",
                    "artistName": "Apple 歌手",
                    "collectionId": 20,
                    "collectionName": "Apple 专辑",
                    "artworkUrl100": "https://img/100x100.jpg",
                    "trackTimeMillis": 201000,
                    "releaseDate": "2024-01-02T00:00:00Z",
                    "primaryGenreName": "Rock",
                    "isExplicit": False,
                }
            ]
        },
    )

    result = platforms_music.parse_apple_music("https://music.apple.com/cn/song/x?i=10")

    assert result.music is not None
    assert result.music.duration_ms == 201000
    assert result.music.album is not None
    assert result.music.album.provider_album_id == "20"
    assert result.music.release_date is not None
    assert result.music.release_date.isoformat() == "2024-01-02"
    assert result.music.genres == ["Rock"]
    assert result.music.explicit is False

from __future__ import annotations

from plugins.bot_unified_runtime.sources.parsers import platforms_music


def test_qq_search_maps_duration_album_and_multiple_artists(monkeypatch) -> None:
    # QQ 搜索已迁移到 musicu.fcg（旧 client_search_cp 服务端下线，恒 500）。
    monkeypatch.setattr(
        platforms_music,
        "http_post_json",
        lambda url, payload, **kwargs: {
            "req_1": {
                "data": {
                    "body": {
                        "song": {
                            "list": [
                                {
                                    "mid": "qq-1",
                                    "name": "QQ 歌曲",
                                    "interval": 215,
                                    "album": {"id": 11, "mid": "ABCDef12", "name": "QQ 专辑"},
                                    "singer": [
                                        {"id": 1, "name": "歌手甲"},
                                        {"id": 2, "name": "歌手乙"},
                                    ],
                                }
                            ]
                        }
                    }
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
    # 封面由专辑 mid 拼 y.gtimg.cn 图床直链。
    assert (result.music.album.artwork_url or "").endswith("T002R500x500M000ABCDef12.jpg")
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

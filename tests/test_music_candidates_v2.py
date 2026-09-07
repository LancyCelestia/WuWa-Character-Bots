from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.music import (
    build_music_capability,
    clear_music_candidate_sessions,
)
from plugins.bot_unified_runtime.contracts import SessionType, build_parsed_content
from plugins.bot_unified_runtime.contracts.runtime import IncomingMessage


def _message(text: str, session_id: str = "private:u1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def _item(title: str) -> object:
    return build_parsed_content(
        platform="netease_music",
        item_id="picked-1",
        item_kind="music",
        title=title,
        author_name="周杰伦",
        canonical_url="https://music.163.com/song/picked-1",
    )


def _candidates() -> list[dict[str, str]]:
    return [
        {"provider_track_id": "101", "name": "晴天", "artist": "周杰伦", "album": "叶惠美"},
        {"provider_track_id": "102", "name": "晴天 (翻自 周杰伦)", "artist": "路人", "album": ""},
        {"provider_track_id": "103", "name": "下雨天", "artist": "南拳妈妈", "album": ""},
    ]


def _build(*, enabled: bool, detail_calls: list[str] | None = None):
    detail_calls = detail_calls if detail_calls is not None else []
    search_calls: list[str] = []
    config = SimpleNamespace(
        bot_music_candidates_enabled=enabled,
        bot_music_candidates_ttl_seconds=300.0,
        bot_music_candidates_limit=5,
    )

    def search_fn(query: str):
        search_calls.append(query)
        # 纯数字不是歌名：模拟搜索无结果。
        return None if query.isdigit() else _item("第一命中")

    def list_fn(query: str) -> list[dict[str, str]]:
        return _candidates()

    def detail_fn(song_id: str):
        detail_calls.append(song_id)
        return _item("选中候选")

    capability = build_music_capability(
        config,
        providers=[("netease_music", "网易云", search_fn)],
        candidate_providers={"netease_music": (list_fn, detail_fn)},
    )
    return capability, search_calls, detail_calls


def test_ambiguous_query_returns_numbered_candidates() -> None:
    clear_music_candidate_sessions()
    # 候选列表里没有名字恰好等于 query 的项 → 歧义，返回编号列表。
    capability, search_calls, detail_calls = _build(enabled=True)

    result = capability(_message("点歌 晴天remix"), None)

    assert result.kind == "text"
    assert "1. 晴天 - 周杰伦" in result.body
    assert "回复编号" in result.body
    assert "music_candidates" in result.audit_tags
    assert detail_calls == []  # 展示列表不应触发详情请求
    assert search_calls == []  # 歧义路径也不重复搜索


def test_exact_name_match_plays_directly_without_list() -> None:
    clear_music_candidate_sessions()
    capability, _search_calls, detail_calls = _build(enabled=True)

    # 候选中存在与 query 同名的精确项 → 沿用既有"直接播放"行为。
    result = capability(_message("点歌 晴天"), None)

    assert result.body != "" and "music_candidates" not in result.audit_tags
    assert "回复编号" not in result.body
    assert detail_calls == []


def test_pick_by_number_calls_detail_and_renders() -> None:
    clear_music_candidate_sessions()
    capability, _search_calls, detail_calls = _build(enabled=True)

    first = capability(_message("点歌 晴天remix"), None)
    assert "music_candidates" in first.audit_tags
    second = capability(_message("点歌 2"), None)

    assert detail_calls == ["102"]
    assert second.title == "选中候选"
    assert "music_candidate_pick" in second.audit_tags


def test_pick_without_session_falls_back_to_search_not_found() -> None:
    clear_music_candidate_sessions()
    capability, _search_calls, detail_calls = _build(enabled=True)

    result = capability(_message("点歌 2"), None)

    assert detail_calls == []
    assert "没有找到" in result.body


def test_disabled_flag_keeps_legacy_first_hit_behavior() -> None:
    clear_music_candidate_sessions()
    capability, _search_calls, _detail_calls = _build(enabled=False)

    result = capability(_message("点歌 晴天remix"), None)

    assert result.title == "第一命中"
    assert "music_candidates" not in result.audit_tags

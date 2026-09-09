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

    def list_fn(query: str, limit: int = 5) -> list[dict[str, str]]:
        return _candidates()

    def detail_fn(candidate: dict, *, query: str = ""):
        detail_calls.append(str(candidate.get("provider_track_id")))
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


def test_pick_without_session_hints_instead_of_digit_search() -> None:
    clear_music_candidate_sessions()
    capability, _search_calls, detail_calls = _build(enabled=True)

    result = capability(_message("点歌 2"), None)

    # 编号无会话/过期：明确提示重新点歌，而不是把编号当歌名去搜。
    assert detail_calls == []
    assert result.audit_tags and "music_candidates_miss" in result.audit_tags
    assert "重新点" in result.body


def test_qualified_query_with_exact_hit_still_shows_candidates() -> None:
    clear_music_candidate_sessions()
    capability, search_calls, detail_calls = _build(enabled=True)

    # 候选中存在与带限定词查询「字面同名」的项（模糊搜索常见现象：翻唱/
    # 变体名恰好等于查询词）——旧逻辑 exact_hits 一票否决直接放第一首，
    # 现行为：非裸歌名查询给候选窗口。
    result = capability(_message("点歌 晴天 钢琴版"), None)
    assert "music_candidates" in result.audit_tags

    # 直接改会话里的候选不可行（内部态），改用独立 capability 复刻：
    # 「晴天 钢琴版」在 _candidates 里没有同名项，上面已验证歧义路径；
    # 下面构造同名精确命中场景验证 bare_exact 只对裸歌名生效。
    from types import SimpleNamespace as _NS

    qualified_candidates = [
        {"provider_track_id": "201", "name": "晴天 钢琴版", "artist": "路人", "album": ""},
        {"provider_track_id": "202", "name": "晴天", "artist": "周杰伦", "album": "叶惠美"},
    ]

    def _list_fn(query: str, limit: int = 5) -> list[dict[str, str]]:
        return qualified_candidates

    cap2 = build_music_capability(
        _NS(
            bot_music_candidates_enabled=True,
            bot_music_candidates_ttl_seconds=300.0,
            bot_music_candidates_limit=5,
        ),
        providers=[("netease_music", "网易云", lambda q: None)],
        candidate_providers={"netease_music": (_list_fn, lambda cand, *, query="": None)},
    )
    r2 = cap2(_message("点歌 晴天 钢琴版"), None)
    assert "music_candidates" in r2.audit_tags
    assert "回复编号" in r2.body
    assert detail_calls == []
    assert search_calls == []


def test_candidate_sessions_are_isolated_per_user() -> None:
    clear_music_candidate_sessions()
    capability, _search_calls, detail_calls = _build(enabled=True)

    first = capability(_message("点歌 晴天remix", session_id="private:room1"), None)
    assert "music_candidates" in first.audit_tags

    # 同一会话（群）里另一名用户点编号：拿不到 A 的候选列表。
    other = IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:room1",
        session_type=SessionType.PRIVATE,
        sender_id="u2",
        plain_text="点歌 1",
    )
    result = capability(other, None)

    assert detail_calls == []
    assert "music_candidates_miss" in result.audit_tags

    # 本人仍可正常选中。
    mine = capability(_message("点歌 1", session_id="private:room1"), None)
    assert detail_calls == ["101"]
    assert "music_candidate_pick" in mine.audit_tags


def test_disabled_flag_keeps_legacy_first_hit_behavior() -> None:
    clear_music_candidate_sessions()
    capability, _search_calls, _detail_calls = _build(enabled=False)

    result = capability(_message("点歌 晴天remix"), None)

    assert result.title == "第一命中"
    assert "music_candidates" not in result.audit_tags

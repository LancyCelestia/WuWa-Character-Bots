"""贴纸回应持久化（sources/reaction_store.py）与双层表情选图离线单测。"""
from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.runtime.reactions import (
    is_sad_message,
    normalize_onebot_emoji_like,
    pick_reaction_meme,
    reaction_meme_search_terms,
)
from plugins.bot_unified_runtime.sources.reaction_store import ReactionStore

# ---------------------------------------------------------------- store

def _store(tmp_path) -> ReactionStore:
    return ReactionStore(tmp_path / "reactions.sqlite3")


def test_record_and_stats(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.record_event(
        session_key="group_1_42", user_id="42", message_id="100",
        emoji_id="76", emoji_text="「赞」",
    )
    assert store.record_event(
        session_key="group_1_42", user_id="42", message_id="101",
        emoji_id="76", emoji_text="「赞」",
    )
    stats = store.emoji_stats()
    assert len(stats) == 1
    assert stats[0]["emoji_id"] == "76"
    assert stats[0]["total"] == 2  # 同 emoji 跨消息聚合。
    assert stats[0]["events"] == 2


def test_same_message_same_emoji_merges_count(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_event(session_key="s", user_id="1", message_id="m1", emoji_id="0", count=1)
    store.record_event(session_key="s", user_id="1", message_id="m1", emoji_id="0", count=2)
    assert store.emoji_stats()[0]["total"] == 3
    assert store.emoji_stats()[0]["events"] == 1


def test_empty_emoji_or_session_ignored(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.record_event(session_key="", user_id="1", message_id="m", emoji_id="0") is False
    assert store.record_event(session_key="s", user_id="1", message_id="m", emoji_id="") is False
    assert store.emoji_stats() == []


def test_user_stats_and_prune(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_event(session_key="s", user_id="42", message_id="m", emoji_id="76")
    store.record_event(session_key="s", user_id="7", message_id="m2", emoji_id="13")
    assert [row["emoji_id"] for row in store.user_stats("42")] == ["76"]
    assert store.user_stats("") == []
    assert store.prune(keep_days=90) == 0  # 新事件不裁剪。
    assert store.prune(keep_days=0) == 0  # 0=不裁剪（防呆）。


# ---------------------------------------------------------------- is_add

def _notice_event(**fields: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "notice_type": "group_msg_emoji_like",
        "user_id": "42",
        "message_id": "100",
        "group_id": "200",
        "likes": [{"emoji_id": "76", "count": 1}],
    }
    base.update(fields)
    return SimpleNamespace(**base)


def test_is_add_false_is_cancellation_not_reaction() -> None:
    assert normalize_onebot_emoji_like(_notice_event(is_add=False)) == []
    events = normalize_onebot_emoji_like(_notice_event(is_add=True))
    assert len(events) == 1  # 显式 True 照常记。
    # 字段缺失=旧语义照记（诚实容错，不赌协议端实现）。
    assert len(normalize_onebot_emoji_like(_notice_event())) == 1


# ---------------------------------------------------------------- 扩展名表锚点

def test_extended_face_name_anchors() -> None:
    from plugins.bot_unified_runtime.runtime.reactions import emoji_display

    assert emoji_display("49") == "「拥抱」"
    assert emoji_display("364") == "「超级赞」"
    assert emoji_display("46") == "「猪头」"
    # 边界内扩展脸不再误入 unicode 码点分支（400→484 边界修正）；
    # 4 位以上 unicode 码点分支不受影响。
    displayed_484 = emoji_display("484")
    assert displayed_484.startswith("「") or displayed_484 == "QQ表情#484"
    assert emoji_display("128077") == "👍"


# ---------------------------------------------------------------- 双层选图

class _FakeMemeStore:
    def __init__(self, results: dict[str, object]) -> None:
        self._results = results
        self.calls: list[str] = []

    def weighted_pick(self, *, keyword: str = "", nsfw_max: float = 0.2) -> object:
        self.calls.append(keyword)
        return self._results.get(keyword)


def test_pick_reaction_meme_intent_terms_order() -> None:
    store = _FakeMemeStore({"暖心": {"path": "x:/warm.png"}})
    assert pick_reaction_meme(store, intent="感动") == "x:/warm.png"
    assert store.calls[0] == "感动"
    assert "暖心" in store.calls  # 感动词族按序检索。


def test_pick_reaction_meme_fallback_then_empty(tmp_path) -> None:
    store = _FakeMemeStore({"": {"path": "x:/any.png"}})
    assert pick_reaction_meme(store, intent="赞同") == "x:/any.png"
    empty = _FakeMemeStore({})
    assert pick_reaction_meme(empty, intent="赞同") is None
    assert pick_reaction_meme(None, intent="赞同") is None


def test_reaction_meme_search_terms_unknown_intent() -> None:
    assert reaction_meme_search_terms("不存在") == ()
    assert reaction_meme_search_terms("安慰") != ()


def test_sad_gate_unchanged() -> None:
    assert is_sad_message("我好难过啊")
    assert is_sad_message("今天好累")
    assert not is_sad_message("今天真开心")

"""white2 严格触发回归：软点名（好感度误学小名）不得让 bot 在白名单2群主动接话。

2026-09-11 语义分层：策展人格昵称（岸宝/守岸人…）= 真点名（mentions_bot=True
且 name_mention_only=False），white2 也应答；仅误学小名保持软触发。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.policy.gate import PolicySettings, evaluate_policy


def _message(
    text: str,
    *,
    mentions_bot: bool = False,
    name_mention_only: bool = False,
    group_id: str = "group-1",
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id=f"group:{group_id}",
        session_type=SessionType.GROUP,
        sender_id="user-1",
        group_id=group_id,
        plain_text=text,
        mentions_bot=mentions_bot,
        name_mention_only=name_mention_only,
        message_id="message-1",
    )


def test_white2_rejects_affinity_learned_soft_mention() -> None:
    """好感度误学小名（如「什么」「林姐」）在 white2 保持静默。"""
    settings = PolicySettings(group_white2=frozenset({"group-1"}))

    decision = evaluate_policy(
        _message("林姐 在吗", mentions_bot=True, name_mention_only=True),
        "bot.chat",
        settings,
    )

    assert decision.allowed is False
    assert decision.reason == "group_white2_need_trigger"


def test_white2_answers_curated_persona_nickname() -> None:
    """策展人格昵称是真点名：white2 严格群也叫应（mentions_bot 且非软触发）。"""
    settings = PolicySettings(group_white2=frozenset({"group-1"}))

    decision = evaluate_policy(
        _message("岸宝 在吗", mentions_bot=True, name_mention_only=False),
        "bot.chat",
        settings,
    )

    assert decision.allowed is True


def test_white2_allows_hard_mention() -> None:
    settings = PolicySettings(group_white2=frozenset({"group-1"}))

    decision = evaluate_policy(
        _message("在吗", mentions_bot=True, name_mention_only=False),
        "bot.chat",
        settings,
    )

    assert decision.allowed is True


def test_white2_allows_explicit_command_prefix() -> None:
    settings = PolicySettings(group_white2=frozenset({"group-1"}))

    decision = evaluate_policy(_message("/bot status"), "bot.chat", settings)

    assert decision.allowed is True


def test_white1_unaffected_by_soft_mention_flag() -> None:
    settings = PolicySettings(group_white1=frozenset({"group-1"}))

    decision = evaluate_policy(
        _message("守岸人 在吗", mentions_bot=True, name_mention_only=True),
        "bot.chat",
        settings,
    )

    assert decision.allowed is True


def test_affinity_nickname_requires_address_form_not_substring(monkeypatch) -> None:
    import plugins.bot_unified_runtime as runtime

    monkeypatch.setattr(runtime, "_AFFINITY_NICKNAMES_CACHE", ["什么"])

    # 误学小名“什么”：句中包含不算点名，单独成句才算。
    assert runtime._mentioned_by_affinity_nickname("这是什么") is False
    assert runtime._mentioned_by_affinity_nickname("为什么") is False
    assert runtime._mentioned_by_affinity_nickname("什么") is True

    monkeypatch.setattr(runtime, "_AFFINITY_NICKNAMES_CACHE", ["林姐"])

    assert runtime._mentioned_by_affinity_nickname("问一下林姐啊") is False
    assert runtime._mentioned_by_affinity_nickname("林姐你好") is True


def test_nickname_stopwords_block_passive_learning_artifacts() -> None:
    # 被动感知“叫我xx”正则会误学问句词；停用词集合必须覆盖这些常用词。
    import plugins.bot_unified_runtime as runtime

    stopwords = runtime._NICKNAME_STOPWORDS
    for word in ("什么", "啥", "谁", "名字", "昵称", "外号"):
        assert word in stopwords
    # 停用词命中即拒绝，不受长度或同名覆盖逻辑影响（构造逻辑一致性）。
    assert "啥子" in stopwords and len("啥子") >= 2

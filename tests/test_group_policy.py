from __future__ import annotations

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.policy.gate import PolicySettings, evaluate_policy


def _message(text: str, *, mentions_bot: bool = False, group_id: str = "group-1") -> IncomingMessage:
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
        message_id="message-1",
    )


def test_white2_allows_explicit_command_without_mention() -> None:
    decision = evaluate_policy(
        _message("/bot status"),
        "bot.chat",
        PolicySettings(group_white2=frozenset({"group-1"})),
    )

    assert decision.allowed is True


def test_white2_allows_mentioned_message_but_rejects_passive_message() -> None:
    settings = PolicySettings(group_white2=frozenset({"group-1"}))

    assert evaluate_policy(_message("你好", mentions_bot=True), "bot.chat", settings).allowed
    denied = evaluate_policy(_message("你好"), "bot.chat", settings)
    assert denied.allowed is False
    assert denied.reason == "group_white2_need_trigger"


def test_white2_does_not_proactively_reply() -> None:
    decision = evaluate_policy(
        _message("普通闲聊"),
        "bot.chat",
        PolicySettings(
            group_white2=frozenset({"group-1"}),
            group_auto_reply_enabled=True,
            group_auto_reply_probability=1.0,
        ),
    )

    assert decision.allowed is False


def test_white1_is_the_only_group_allowed_to_proactively_reply() -> None:
    settings = PolicySettings(
        group_white1=frozenset({"group-1"}),
        group_auto_reply_enabled=True,
        group_auto_reply_probability=1.0,
    )

    selected = evaluate_policy(_message("普通闲聊"), "bot.chat", settings)
    assert selected.allowed is True
    assert selected.reason == "proactive_reply_selected"

    other = evaluate_policy(
        _message("普通闲聊", group_id="group-2"),
        "bot.chat",
        settings,
    )
    assert other.allowed is False
    assert other.reason == "passive_group_message"

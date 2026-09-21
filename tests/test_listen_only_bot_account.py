"""监听专用机器人号（校园学校号那批 bot_campus_self_ids）的群消息统一不回话。

覆盖 evaluate_policy 群分支最前的硬否决：命令 / 点名 / 自然语言 / 抽签等所有
触发路径一律被拒；私聊与守岸人主号不受约束；校园转发不经门禁故与本测试无关。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.gate import (
    PolicySettings,
    evaluate_policy,
)

SCHOOL_ID = "2300230562"
MAIN_ID = "3958874605"
_SETTINGS = PolicySettings(listen_only_bot_ids=frozenset({SCHOOL_ID}))


def _group(bot_id: str, *, text: str = "今天天气不错", mentions: bool = True) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id=bot_id,
        session_id="group_992901522_12345",
        session_type=SessionType.GROUP,
        sender_id="12345",
        group_id="992901522",
        plain_text=text,
        mentions_bot=mentions,
    )


def test_group_message_to_listen_only_account_is_denied() -> None:
    result = evaluate_policy(_group(SCHOOL_ID), "bot.chat", settings=_SETTINGS)
    assert result.allowed is False
    assert result.reason == "listen_only_account"
    assert "listen_only_account" in result.audit_tags


def test_listen_only_denial_covers_command_text() -> None:
    # 学校号被 @ 且带 /bot 指令：也在群分支最前统一否决，命令路径不再旁逸。
    result = evaluate_policy(
        _group(SCHOOL_ID, text="/bot help", mentions=False), "bot.chat", settings=_SETTINGS
    )
    assert result.allowed is False
    assert result.reason == "listen_only_account"


def test_main_account_group_message_still_allowed() -> None:
    result = evaluate_policy(_group(MAIN_ID), "bot.chat", settings=_SETTINGS)
    assert result.allowed is True


def test_private_message_to_listen_only_account_still_allowed() -> None:
    msg = IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id=SCHOOL_ID,
        session_id="private_12345",
        session_type=SessionType.PRIVATE,
        sender_id="12345",
        plain_text="在吗",
        mentions_bot=True,
    )
    result = evaluate_policy(msg, "bot.chat", settings=_SETTINGS)
    assert result.allowed is True


def test_empty_listen_only_set_is_no_op() -> None:
    default = PolicySettings()
    result = evaluate_policy(_group(SCHOOL_ID), "bot.chat", settings=default)
    assert result.reason != "listen_only_account"

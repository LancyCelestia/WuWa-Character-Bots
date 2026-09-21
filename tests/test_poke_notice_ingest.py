"""戳一戳（NoticeEvent）摄取回归：无 message 字段不得炸摄取层（2026-09-16 实弹）。

NapCat 时期戳一戳走 notice 事件，NoneBot 的 OB11 NoticeEvent.get_message() 会
raise ValueError("Event has no message!")；摄取层必须按空文本降级——
话术文案由 handler 侧自备（_send_text_through_unified_pipeline 的入参），
不依赖事件正文。
"""
from __future__ import annotations

from plugins.bot_unified_runtime import _incoming_from_nonebot_event


class _FakePokeNoticeEvent:
    # module 指向 onebot.v11 才会走 QQ 摄取分支（telegram/mail 各有独立路径）。
    __module__ = "nonebot.adapters.onebot.v11.event"

    def get_plaintext(self) -> str:
        raise ValueError("Event has no message!")

    def get_session_id(self) -> str:
        return "group_999"

    def get_user_id(self) -> str:
        return "u1"


def test_notice_event_without_message_ingests_with_empty_text() -> None:
    message = _incoming_from_nonebot_event(_FakePokeNoticeEvent(), bot_id="bot-1")
    assert message.plain_text == ""
    assert message.session_id == "group_999"

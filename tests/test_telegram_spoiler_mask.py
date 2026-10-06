"""Telegram 遮罩（点击才显示）通道：只有命中「群侧那把露骨尺」的词面才包，其余一字不动。

用户裁定（2026-10-06）：
- 成人向（色情）与敏感那一族在 **Telegram** 加官方遮罩；**QQ 不拦、也不做任何措施**；
- **普通非 18+ 内容不准进遮罩，16+ 也不能进**——判据必须是"命中露骨词面才包"，
  不是"看着像隐私就包"；
- 罩 ≠ 放行：六条硬线照旧拦，本件只改变**已经允许出门的那一段**的可见形态。

实现形态（刻意 chosen）：走 Telegram 适配器**已有的 `Entity` 消息段**
（`nonebot.adapters.telegram.Entity.spoiler`），偏移由适配器按 UTF-16 自己算 ⇒
出站正文仍是纯文本，§10「TG 不设 parse_mode 的纯文本契约」不被破坏；
判据复用 `reviewer._PUBLIC_OUTPUT_UNSAFE` 那一枚唯一真身（禁第二份词表）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.render.reviewer import explicit_output_spans
from plugins.bot_unified_runtime.domains.transport.sender.nonebot import (
    send_nonebot_message,
)

CLEAN_TEXT = "今晚的潮汐很安静，我把灯留着。"
DIRTY_TEXT = "今晚的潮汐很安静。露骨性行为那一段我只写给你看，别的话照旧。"
EDGE_TEXT = "她靠过来，呼吸贴着你的耳廓，指尖顺着袖口滑进去。"
BOUNDARY_TEXT = "MAR18、October 18、R-1800 这些编号都不是裁定词面。"


class _RecordingBot:
    """离线替身：两条投递腿（事件腿 `send`／队列腿 `send_to`）都只记不投。"""

    def __init__(self, adapter_name: str = "Telegram") -> None:
        self.adapter = SimpleNamespace(get_name=lambda: adapter_name)
        # mail 那支要「发件人地址」才肯装配（`_build_mail_reply_message` 的 fail-fast）。
        self.bot_info = SimpleNamespace(id="qq@example.com", name="守岸人")
        self.calls: list[tuple[Any, Any, dict[str, Any]]] = []

    async def send(self, event: Any, message: Any, **kwargs: Any) -> dict[str, str]:
        self.calls.append((event, message, kwargs))
        return {"message_id": "tg-event-1"}

    async def send_to(self, chat_id: Any, message: Any, **kwargs: Any) -> dict[str, str]:
        self.calls.append((chat_id, message, kwargs))
        return {"message_id": "tg-queue-1"}

    async def send_mail(self, message: Any) -> dict[str, str]:
        self.calls.append(("mail", message, {}))
        return {"message_id": "mail-1"}


def _request(
    text: str, *, adapter: str = "telegram", target_id: str = "user-1"
) -> SendRequest:
    return SendRequest(
        request_id="req-spoiler-1",
        session_id=f"private:{target_id}",
        target_scope=SessionType.PRIVATE,
        target_id=target_id,
        origin_message_id="message-1",
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id="req-spoiler-1",
            content_type="text",
            content_ref={},
            text_fallback=text,
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="bot.chat:private:user-1:message-1",
        cooldown_key="private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_split=False,
        allow_forward=False,
        persona_profile_id="default",
        adapter=adapter,
        bot_id="telegram-bot",
    )


def _utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _spoiler_entities(payload: Any) -> list[Any]:
    """拿适配器**自己的**组实体函数算出实体——不自己数偏移，避免量具与被测件同源。"""
    from nonebot.adapters.telegram.message import Entity

    segments = list(payload) if not isinstance(payload, str) else []
    return list(
        Entity.build_telegram_entities(
            [segment for segment in segments if isinstance(segment, Entity)]
        )
    )


def _clean_call(event: Any, bot: _RecordingBot, text: str) -> Any:
    """同步跑一次出站腿，只取「交给适配器的那一枚载荷」。

    测试件刻意不引 `pytest-asyncio`（本机缺省档里它不是硬依赖）：`send_nonebot_message`
    在这两条腿上不含真 await 投递，`asyncio.run` 与事件循环里跑完等价。
    """
    import asyncio

    receipt = asyncio.run(send_nonebot_message(bot, event, _request(text)))
    assert receipt.state is ReceiptState.SENT, receipt.public_message
    return bot.calls[0]


def test_the_mask_ruler_is_the_one_public_word_face() -> None:
    """遮罩判据＝群侧涂销那把尺的**区间形态**：同一清单、同一射程，零第二词表。"""
    spans = explicit_output_spans(DIRTY_TEXT)
    assert spans == [(DIRTY_TEXT.index("露骨性行为"), DIRTY_TEXT.index("露骨性行为") + 5)]

    # 🔴 三形必须判"不进罩"：普通话、16+ 擦边、带词界的编号（F-12 那批裁定）。
    assert explicit_output_spans(CLEAN_TEXT) == []
    assert explicit_output_spans(EDGE_TEXT) == []
    assert explicit_output_spans(BOUNDARY_TEXT) == []


def test_telegram_event_leg_wraps_only_the_explicit_span() -> None:
    """事件腿（有 event＝内联回复）：正文按 Entity 段重组，`str()` 必须一字不差。"""
    from nonebot.adapters.telegram import Message

    event = object()
    bot = _RecordingBot()
    _, payload, kwargs = _clean_call(event, bot, DIRTY_TEXT)

    assert isinstance(payload, Message), "命中露骨词面却没走实体段＝遮罩做成了哑巴"
    assert str(payload) == DIRTY_TEXT, f"重组后正文变形：{str(payload)!r}"
    assert kwargs == {}, "遮罩靠实体段，不该顺手开出第二个 kwargs 面"

    entities = _spoiler_entities(payload)
    assert [entity.type for entity in entities] == ["spoiler"]
    start = explicit_output_spans(DIRTY_TEXT)[0][0]
    assert entities[0].offset == _utf16_len(DIRTY_TEXT[:start]), "偏移不是 UTF-16 单位＝罩错位"
    assert entities[0].length == _utf16_len(DIRTY_TEXT[start : start + 5])


def test_telegram_queue_leg_wraps_the_same_span() -> None:
    """队列腿（`event=None`＝worker 投递/重投）：同一 Transform，别只做一半。"""
    from nonebot.adapters.telegram import Message

    target, payload, _ = _clean_call(None, _RecordingBot(), DIRTY_TEXT)
    assert target == "user-1"
    assert isinstance(payload, Message)
    assert str(payload) == DIRTY_TEXT


def test_clean_telegram_text_stays_a_bare_string() -> None:
    """没命中露骨词面＝**原样裸 str、零 kwargs**：§10 纯文本契约不被本波改动。"""
    _, payload, kwargs = _clean_call(object(), _RecordingBot(), CLEAN_TEXT)
    assert isinstance(payload, str), "普通内容被包成实体＝把裁定的'不准进'做反了"
    assert payload == CLEAN_TEXT
    assert kwargs == {}


@pytest.mark.parametrize("adapter_name", ["Console", "Mail"])
def test_other_adapters_never_get_the_mask(adapter_name: str) -> None:
    """遮罩只属于 Telegram：console/mail 即便正文命中露骨词面也照旧裸 str。"""
    bot = _RecordingBot(adapter_name)
    event = (
        object()
        if adapter_name == "Console"
        else SimpleNamespace(id="<a@b>", subject="t", sender=SimpleNamespace(id="c@d"))
    )
    import asyncio

    request = _request(
        DIRTY_TEXT,
        adapter=adapter_name.lower(),
        target_id="recv@example.com" if adapter_name == "Mail" else "user-1",
    )
    asyncio.run(send_nonebot_message(bot, event, request))
    assert bot.calls, "本腿压根没投递＝测了个空壳"
    payload = bot.calls[0][1]
    if adapter_name == "Console":
        assert isinstance(payload, str), f"{adapter_name} 侧被包了遮罩＝越出裁定面"
        assert payload == DIRTY_TEXT
    else:
        # mail 走自己那支（`send_mail`＋RFC5322 回复体），遮罩的 payload 根本不经它：
        # 判据＝纯文本部件里原文一字未改、也没有实体段形态。
        plain = next(
            part.get_content() for part in payload.walk()
            if part.get_content_type() == "text/plain"
        )
        assert DIRTY_TEXT in plain

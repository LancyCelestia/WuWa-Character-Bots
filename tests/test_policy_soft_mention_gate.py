"""R4 长文软点名观察门回归（2026-09-12 用户裁定：场景化回应，不刷存在感）。

被测：policy/gate.evaluate_policy 的 long_text_soft_mention 分支——
soft_persona_mention=True 且文本 ≥50 字、非开头称呼、非问句意图 → 不抢答。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.policy.gate import (
    PolicySettings,
    evaluate_policy,
)

_GROUP = "1108838060"
_TERMS = ("守岸人", "岸宝")

_LONG_NO_QUESTION = (
    "今天市场行情波动比较大，上午还在涨的板块下午就回调了，群里好几个人都在讨论要不要"
    "减仓，我看了看守岸人之前发过的行情卡，感觉还是再等等看比较好，不着急动手。"
)


def _message(text: str, *, soft: bool) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot v11",
        bot_id="3958874605",
        session_id=f"group:{_GROUP}",
        session_type=SessionType.GROUP,
        sender_id="10086",
        group_id=_GROUP,
        plain_text=text,
        mentions_bot=False,
        soft_persona_mention=soft,
        message_id="1",
    )


def _settings() -> PolicySettings:
    return PolicySettings(
        group_white1=frozenset({_GROUP}),
        mention_terms=_TERMS,
        group_auto_reply_enabled=False,
        natural_chat_check=lambda _text: False,
    )


def test_long_soft_mention_observed_not_replied() -> None:
    result = evaluate_policy(_message(_LONG_NO_QUESTION, soft=True), "bot.chat", _settings())
    assert not result.allowed
    assert "soft_mention_observe" in result.audit_tags


def test_no_mention_falls_through_normal_path() -> None:
    text = _LONG_NO_QUESTION.replace("守岸人", "别人")
    result = evaluate_policy(_message(text, soft=False), "bot.chat", _settings())
    assert not result.allowed
    assert "soft_mention_observe" not in result.audit_tags


def test_leading_address_exempts() -> None:
    text = "守岸人 觉得这个怎么样？说说你的看法吧，我很好奇你的判断。"
    result = evaluate_policy(_message(text, soft=True), "bot.chat", _settings())
    assert "soft_mention_observe" not in result.audit_tags


def test_question_mark_exempts() -> None:
    text = (
        "群里刚才讨论的那个新版本剧情，有人说铺垫很长世界观也展开得很完整，守岸人你觉得"
        "这次的多线叙事处理得怎么样？值得为它补一次深入的主线吗？"
    )
    result = evaluate_policy(_message(text, soft=True), "bot.chat", _settings())
    assert "soft_mention_observe" not in result.audit_tags


def test_question_word_exempts() -> None:
    text = (
        "下午看到不少人在聊新活动的奖励机制，守岸人之前发过的公告里提到过兑换上限，我想"
        "再确认一下这个东西具体怎么算的，怕自己理解错了白忙一场。"
    )
    result = evaluate_policy(_message(text, soft=True), "bot.chat", _settings())
    assert "soft_mention_observe" not in result.audit_tags


def test_short_mention_exempts() -> None:
    result = evaluate_policy(_message("守岸人早安呀", soft=True), "bot.chat", _settings())
    assert "soft_mention_observe" not in result.audit_tags

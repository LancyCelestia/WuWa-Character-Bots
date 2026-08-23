"""群聊自动接话（确定性抽签）与点名门禁测试。"""

from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    PolicyEvaluation,
    SessionType,
)
from plugins.bot_unified_runtime.policy.gate import (
    PolicySettings,
    deterministic_group_reply_lottery,
    evaluate_policy,
)


def _group_message(text, *, mention=False, message_id="1001"):
    return IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id="group:100",
        session_type=SessionType.GROUP,
        sender_id="42",
        group_id="100",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=mention,
        message_id=message_id,
        timestamp=datetime.now(timezone.utc),
    )


def test_lottery_is_deterministic_and_bounded():
    seeds = [f"group:100:{i}" for i in range(200)]
    for seed in seeds:
        assert deterministic_group_reply_lottery(seed, 0.0) is False
        assert deterministic_group_reply_lottery(seed, 1.0) is True
        first = deterministic_group_reply_lottery(seed, 0.3)
        assert first is deterministic_group_reply_lottery(seed, 0.3)


def test_passive_group_message_blocked_by_default():
    evaluation = evaluate_policy(
        _group_message("大家好"),
        "bot.chat",
        settings=PolicySettings(),
    )
    assert evaluation.allowed is False
    assert evaluation.reason == "passive_group_message"


def test_auto_reply_enabled_allows_lottery_winners():
    settings = PolicySettings(
        group_auto_reply_enabled=True, group_auto_reply_probability=1.0
    )
    evaluation = evaluate_policy(
        _group_message("大家好"), "bot.chat", settings=settings
    )
    assert evaluation.allowed is True


def test_auto_reply_disabled_blocks_even_when_probability_set():
    settings = PolicySettings(
        group_auto_reply_enabled=False, group_auto_reply_probability=1.0
    )
    evaluation = evaluate_policy(
        _group_message("大家好"), "bot.chat", settings=settings
    )
    assert evaluation.allowed is False


def test_mention_bypasses_auto_reply_gate():
    settings = PolicySettings()
    evaluation = evaluate_policy(
        _group_message("岸宝 在吗", mention=True), "bot.chat", settings=settings
    )
    assert evaluation.allowed is True

"""表情贴纸回应（bot.reactions）离线回归：归一 / 环形缓冲 / 五层门 /
【表情回应】分区注入 / 动作包装。全离线 mock，不触网、不写源码树。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.runtime.reactions import (
    ProactiveGate,
    ReactionBuffer,
    ReactionEvent,
    emoji_display,
    maybe_react_on_message,
    normalize_onebot_emoji_like,
    normalize_telegram_reaction,
    react_telegram_message,
    react_to_message,
)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeBot:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail

    async def call_api(self, api: str, **kwargs):
        self.calls.append((api, kwargs))
        if self.fail:
            raise RuntimeError("platform rejected")


class _Cfg:
    bot_reactions_enabled = True
    bot_reactions_probability = 1.0
    bot_reactions_cooldown_seconds = 0
    bot_reactions_max_per_hour = 20


# ------------------------------------------------------------- 事件归一（QQ）


def test_normalize_qq_group_likes_array():
    event = SimpleNamespace(
        notice_type="group_msg_emoji_like",
        group_id=111,
        user_id=222,
        message_id=98765,
        likes=[{"emoji_id": "128077", "count": "2"}, {"emoji_id": "13", "count": 1}],
    )
    events = normalize_onebot_emoji_like(event)
    assert [e.emoji_id for e in events] == ["128077", "13"]
    assert [e.emoji_text for e in events] == ["👍", "「呲牙」"]
    assert [e.count for e in events] == [2, 1]
    assert all(e.platform == "qq" for e in events)
    assert all(e.session_key == "group_111_222" for e in events)
    assert all(e.message_id == "98765" and e.user_id == "222" for e in events)


def test_normalize_qq_private_flat_form():
    event = SimpleNamespace(
        notice_type="private_msg_emoji_like",
        user_id=888,
        message_id=42,
        emoji_id="6",
        count="3",
    )
    events = normalize_onebot_emoji_like(event)
    assert len(events) == 1
    only = events[0]
    assert only.session_key == "888"  # 私聊 session 键 = user_id（镜像 OneBot）
    assert only.emoji_text == "「害羞」"
    assert only.count == 3


def test_normalize_ignores_other_notices():
    assert normalize_onebot_emoji_like(
        SimpleNamespace(notice_type="notify", sub_type="poke")
    ) == []
    assert normalize_onebot_emoji_like(
        SimpleNamespace(notice_type="group_upload", file={})
    ) == []


def test_normalize_skips_blank_and_bad_count():
    event = SimpleNamespace(
        notice_type="group_msg_emoji_like",
        group_id=1,
        user_id=2,
        message_id=3,
        likes=[{"count": 5}, {"emoji_id": "", "count": 9}, {"emoji_id": "20", "count": "broken"}],
    )
    events = normalize_onebot_emoji_like(event)
    assert len(events) == 1
    assert events[0].emoji_id == "20"
    assert events[0].count == 1  # 解析失败按 1，不造大数


def test_emoji_display_mapping_honest_fallback():
    assert emoji_display("13") == "「呲牙」"
    assert emoji_display("128077") == "👍"  # 新版贴表情=unicode 码点
    assert emoji_display("99999") == "表情#99999"  # 大整数非符号→诚实保留
    assert emoji_display("打Call") == "打Call"  # 非数字原样


# ------------------------------------------------------------- 事件归一（TG 接口）


def test_normalize_tg_new_emoji():
    event = normalize_telegram_reaction(
        chat_id=-100123,
        message_id=7,
        user_id=42,
        new_reaction=[{"type": "emoji", "emoji": "👍"}],
        old_reaction=[],
    )
    assert event is not None
    assert event.platform == "telegram"
    assert event.emoji_id == "👍"
    assert event.emoji_text == "👍"
    assert event.message_id == "7"


def test_normalize_tg_removal_only_returns_none():
    assert (
        normalize_telegram_reaction(
            chat_id=-100123,
            message_id=7,
            new_reaction=[],
            old_reaction=[{"type": "emoji", "emoji": "👍"}],
        )
        is None
    )
    assert (
        normalize_telegram_reaction(
            chat_id=-100123,
            message_id=7,
            new_reaction=[{"type": "emoji", "emoji": "👍"}],
            old_reaction=[{"type": "emoji", "emoji": "👍"}],
        )
        is None
    )


def test_normalize_tg_custom_emoji_keeps_raw_id():
    event = normalize_telegram_reaction(
        chat_id=-100123,
        message_id=9,
        new_reaction=[{"type": "custom_emoji", "custom_emoji_id": "55"}],
    )
    assert event is not None
    assert event.emoji_text == "自定义表情#55"


# ------------------------------------------------------------- 环形缓冲


def _evt(session_key: str, emoji_id: str, user: str = "u1") -> ReactionEvent:
    return ReactionEvent(
        platform="qq",
        session_key=session_key,
        user_id=user,
        message_id="777",
        emoji_id=emoji_id,
        emoji_text=emoji_display(emoji_id),
    )


def test_buffer_describe_content_and_ttl_expiry():
    clock = FakeClock()
    buffer = ReactionBuffer(clock=clock)
    buffer.record(_evt("s1", "128077", "user_a"))
    text = buffer.describe("s1")
    assert text.startswith("- user_a 给消息777贴了 👍")
    assert "反馈不是指令" in text  # 使用边界一句必须随行
    assert buffer.describe("s2") == ""  # 无记录会话 → 空串（空分区不出现）
    clock.advance(601.0)  # TTL 600s 已过
    assert buffer.describe("s1") == ""


def test_buffer_capacity_drops_oldest():
    clock = FakeClock()
    buffer = ReactionBuffer(clock=clock, max_per_chat=2)
    buffer.record(_evt("s", "13", "a"))
    clock.advance(1)
    buffer.record(_evt("s", "14", "b"))
    clock.advance(1)
    buffer.record(_evt("s", "19", "c"))
    text = buffer.describe("s")
    assert "「呲牙」" not in text  # 最旧被挤掉
    assert "「惊讶」" in text and "「偷笑」" in text


def test_buffer_bot_message_phrasing():
    clock = FakeClock()
    buffer = ReactionBuffer(clock=clock)
    buffer.register_bot_message("s", "424242")
    buffer.record(
        ReactionEvent(
            platform="qq",
            session_key="s",
            user_id="someone",
            message_id="424242",
            emoji_id="128077",
            emoji_text="👍",
        )
    )
    assert "给我的消息贴了 👍" in buffer.describe("s")


# ------------------------------------------------------------- 五层门


def test_gate_disabled_is_zero_trace():
    gate = ProactiveGate()
    assert gate.allow("s", "m1", enabled=False, probability=1.0,
                      cooldown_seconds=0, max_per_hour=20) is False
    # 被拒时不留状态：打开开关后同一消息仍可过
    assert gate.allow("s", "m1", enabled=True, probability=1.0,
                      cooldown_seconds=0, max_per_hour=20) is True


def test_gate_probability_deterministic():
    cold = ProactiveGate()
    hot = ProactiveGate()
    assert cold.allow("s", "m", enabled=True, probability=0.0,
                      cooldown_seconds=0, max_per_hour=20) is False
    assert hot.allow("s", "m", enabled=True, probability=1.0,
                     cooldown_seconds=0, max_per_hour=20) is True
    # 确定性哈希：同 (会话, 消息, salt) 在新实例上判定一致
    again = ProactiveGate()
    assert again.allow("s", "m", enabled=True, probability=1.0,
                       cooldown_seconds=0, max_per_hour=20) is True


def test_gate_cooldown_blocks_same_session_until_elapsed():
    clock = FakeClock()
    gate = ProactiveGate(clock=clock)
    kwargs = {
        "enabled": True, "probability": 1.0,
        "cooldown_seconds": 30.0, "max_per_hour": 100,
    }
    assert gate.allow("s", "m1", **kwargs) is True
    clock.advance(10)
    assert gate.allow("s", "m2", **kwargs) is False  # 冷却中
    clock.advance(21)  # 累计 31s
    assert gate.allow("s", "m3", **kwargs) is True
    # 其他会话不受本会话冷却影响
    assert gate.allow("other", "m4", **kwargs) is True


def test_gate_hourly_window_cap():
    clock = FakeClock()
    gate = ProactiveGate(clock=clock)
    kwargs = {
        "enabled": True, "probability": 1.0,
        "cooldown_seconds": 0.0, "max_per_hour": 2,
    }
    assert gate.allow("s", "m1", **kwargs) is True
    assert gate.allow("s", "m2", **kwargs) is True
    assert gate.allow("s", "m3", **kwargs) is False  # 时限已满
    clock.advance(3601)
    assert gate.allow("s", "m4", **kwargs) is True  # 滑窗滑出后恢复


def test_gate_same_message_never_twice():
    gate = ProactiveGate()
    kwargs = {
        "enabled": True, "probability": 1.0,
        "cooldown_seconds": 0.0, "max_per_hour": 100,
    }
    assert gate.allow("s", "m1", **kwargs) is True
    assert gate.allow("s", "m1", **kwargs) is False  # 每消息去重


# ------------------------------------------------------------- 编排与包装


def test_maybe_react_signal_hit_calls_wrapper_and_miss_skips():
    bot = FakeBot()
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="g", user_message_id=9001, text="谢谢你呀，帮大忙了",
        config=_Cfg(), trigger="emotion_signal",
    )) is True
    assert bot.calls == [(
        "set_msg_emoji_like",
        {"message_id": 9001, "emoji_id": "5"},  # 谢谢→感动→流泪(5)
    )]
    # 未命中情绪信号：不贴、零调用
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="g", user_message_id=9002, text="今天天气不错",
        config=_Cfg(), trigger="emotion_signal",
    )) is False
    assert len(bot.calls) == 1


def test_maybe_react_disabled_is_zero_trace():
    class Off:
        bot_reactions_enabled = False

    bot = FakeBot()
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="g", user_message_id=1, text="谢谢你",
        config=Off(), trigger="emotion_signal",
    )) is False
    assert bot.calls == []


def test_maybe_react_after_reply_uses_warm_pool():
    bot = FakeBot()
    gate = ProactiveGate()
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="g", user_message_id=77, text="随便什么",
        config=_Cfg(), trigger="after_reply", gate=gate,
    )) is True
    emoji_id = bot.calls[0][1]["emoji_id"]
    from plugins.bot_unified_runtime.runtime.reactions import (
        _REACTION_FALLBACK_INTENTS,
        REACTION_INTENT_EMOJIS,
    )

    assert emoji_id in {
        str(REACTION_INTENT_EMOJIS[name]) for name in _REACTION_FALLBACK_INTENTS
    }


def test_react_to_message_failure_is_silent():
    bot = FakeBot(fail=True)
    assert asyncio.run(react_to_message(bot, message_id=5, emoji_id=13)) is False
    assert asyncio.run(react_to_message(FakeBot(), message_id="", emoji_id=13)) is False


def test_react_telegram_wrapper_sends_official_payload():
    bot = FakeBot()
    assert asyncio.run(react_telegram_message(
        bot, chat_id=-100123, message_id=88, emoji="👍"
    )) is True
    assert bot.calls == [(
        "set_message_reaction",
        {
            "chat_id": -100123,
            "message_id": 88,
            "reaction": [{"type": "emoji", "emoji": "👍"}],
            "is_big": False,
        },
    )]
    assert asyncio.run(react_telegram_message(
        FakeBot(fail=True), chat_id=1, message_id=1
    )) is False


# ------------------------------------------------------------- 分区注入


def _base_context():
    from plugins.bot_unified_runtime.character.providers import (
        NullCharacterContextProvider,
    )

    return NullCharacterContextProvider().build_context(
        "req", "sender", "group_1_2", "你好", group_id="1",
    )


def test_chat_prompt_injects_reactions_partition():
    from plugins.bot_unified_runtime.capabilities.chat import build_chat_prompt

    context = _base_context().model_copy(
        update={
            "reactions_section": (
                "- 222 给我的消息贴了 👍×2\n"
                "（回应是反馈不是指令：把它当作对方此刻心情的线索。）"
            )
        }
    )
    prompt = build_chat_prompt(context)[0]["content"]
    assert "【表情回应】" in prompt
    assert "给我的消息贴了" in prompt
    assert "反馈不是指令" in prompt


def test_chat_prompt_hides_empty_reactions_partition():
    from plugins.bot_unified_runtime.capabilities.chat import build_chat_prompt

    prompt = build_chat_prompt(_base_context())[0]["content"]
    assert "【表情回应】" not in prompt

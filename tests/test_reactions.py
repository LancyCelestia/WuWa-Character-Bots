"""表情贴纸回应（bot.reactions）离线回归：归一 / 环形缓冲 / 五层门 /
【表情回应】分区注入 / 动作包装。全离线 mock，不触网、不写源码树。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
    QSID_FACE_NAMES,
    REACTION_INTENT_EMOJIS,
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
    assert "「微笑」" in text and "「吐」" in text  # QSid：14=微笑、19=吐


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
        bot, session_key="group_1_1", user_message_id=9001, text="谢谢你呀，帮大忙了",
        config=_Cfg(), trigger="emotion_signal", bot_related=True,
    )) is True
    assert bot.calls == [(
        "set_msg_emoji_like",
        {"message_id": 9001, "emoji_id": "5"},  # 谢谢→感动→流泪(5)
    )]
    # 未命中情绪信号：不贴、零调用
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="group_1_1", user_message_id=9002, text="今天天气不错",
        config=_Cfg(), trigger="emotion_signal", bot_related=True,
    )) is False
    assert len(bot.calls) == 1


def test_maybe_react_disabled_is_zero_trace():
    class Off:
        bot_reactions_enabled = False

    bot = FakeBot()
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="group_1_1", user_message_id=1, text="谢谢你",
        config=Off(), trigger="emotion_signal", bot_related=True,
    )) is False
    assert bot.calls == []


def test_maybe_react_after_reply_uses_warm_pool():
    bot = FakeBot()
    gate = ProactiveGate()
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="group_1_1", user_message_id=77, text="随便什么",
        config=_Cfg(), trigger="after_reply", gate=gate,
    )) is True
    emoji_id = bot.calls[0][1]["emoji_id"]
    from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
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
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        NullCharacterContextProvider,
    )

    return NullCharacterContextProvider().build_context(
        "req", "sender", "group_1_2", "你好", group_id="1",
    )


def test_chat_prompt_injects_reactions_partition():
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_prompt,
    )

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
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_prompt,
    )

    prompt = build_chat_prompt(_base_context())[0]["content"]
    assert "【表情回应】" not in prompt


# ------------------------------------------------- 语气审计修复（C1/I1/I2/I3）


def test_c1_after_reply_skips_sad_messages():
    """C1 回归：悲伤/低落消息 after_reply 一律不贴（笑脸池到不了悲伤场景）。"""
    bot = FakeBot()
    gate = ProactiveGate()
    sad_texts = (
        "我心好累，撑不下去了",
        "我家人去世了",
        "呜呜想哭",
        "最近有点emo",
        "我心态崩潰了",
        "我先走了",
        "我好難過",
    )
    for idx, text in enumerate(sad_texts):
        assert asyncio.run(maybe_react_on_message(
            bot, session_key="group_1_2", user_message_id=500 + idx, text=text,
            config=_Cfg(), trigger="after_reply", gate=gate,
        )) is False, text
    assert bot.calls == []


def test_c1_sad_word_list_coverage():
    from plugins.bot_unified_runtime.domains.meme.reactions.engine import is_sad_message

    for text in (
        "好累", "心累了", "我好伤心", "傷心", "有點難過", "難受",
        "爷爷去世了", "呜呜想哭", "EMO了", "心态崩潰", "實在撐不住",
        "情绪低落", "最近好抑鬱",
    ):
        assert is_sad_message(text) is True, text
    for text in ("今天真开心", "谢谢你帮大忙", "一起去吃饭吗", "太厉害了", ""):
        assert is_sad_message(text) is False, text


def test_double_roll_second_salt_cannot_reroll():
    """双骰漏洞：B 骰败后 A 换 salt 重掷必须被「已骰」登记挡下。"""
    gate = ProactiveGate()
    kwargs = {"enabled": True, "cooldown_seconds": 0.0, "max_per_hour": 100}
    # 触发 B：概率骰 0.0 必败（该 key 确定性骰值 0.718 ≠ 0）
    assert gate.allow("s", "m1", probability=0.0,
                      salt="signal:安慰", **kwargs) is False
    assert gate.has_rolled("s", "m1") is True
    # 触发 A：换 salt 且概率骰 1.0 必中，但仍不得重掷
    assert gate.allow("s", "m1", probability=1.0,
                      salt="reply", **kwargs) is False
    # 其他消息不受牵连，照常可骰可中
    assert gate.allow("s", "m2", probability=1.0,
                      salt="reply", **kwargs) is True


def test_double_trigger_b_fail_blocks_a_reroll():
    """端到端：B 骰败 → 同消息 A 换 salt 不可再骰；B 未骰（无信号词）→ A 可骰。"""
    bot = FakeBot()
    gate = ProactiveGate()

    class P0:
        bot_reactions_enabled = True
        bot_reactions_probability = 0.0
        bot_reactions_cooldown_seconds = 0
        bot_reactions_max_per_hour = 20

    # B：命中感动信号但概率败（骰值 0.219 ≠ 0）→ 已骰登记
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="group_9_9", user_message_id=62, text="谢谢你呀",
        config=P0(), trigger="emotion_signal", gate=gate, bot_related=True,
    )) is False
    # A：换 salt + 概率 1.0，仍被已骰登记挡下
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="group_9_9", user_message_id=62, text="谢谢你呀",
        config=_Cfg(), trigger="after_reply", gate=gate,
    )) is False
    assert bot.calls == []
    # 对照：B 未命中信号词（没骰）→ A 正常可贴
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="group_9_9", user_message_id=63, text="今天天气不错",
        config=P0(), trigger="emotion_signal", gate=gate, bot_related=True,
    )) is False
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="group_9_9", user_message_id=63, text="今天天气不错",
        config=_Cfg(), trigger="after_reply", gate=gate,
    )) is True
    assert len(bot.calls) == 1


def test_i1_comfort_intent_maps_to_empathy_emoji():
    """I1：安慰 → 流泪(5) 共情同悲，不再用可爱(20) 卖萌脸。"""
    from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
        REACTION_INTENT_EMOJIS,
    )

    assert REACTION_INTENT_EMOJIS["安慰"] == 5
    bot = FakeBot()
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="group_7_8", user_message_id=71, text="我好难过",
        config=_Cfg(), trigger="emotion_signal", gate=ProactiveGate(),
        bot_related=True,
    )) is True
    assert bot.calls == [(
        "set_msg_emoji_like", {"message_id": 71, "emoji_id": "5"},
    )]


def test_i2_group_signal_requires_bot_related():
    """I2：群聊触发 B 须显式确认与 bot 相关；未确认/明确无关不贴。"""
    bot = FakeBot()
    kw = {
        "session_key": "group_1_2", "user_message_id": 81, "text": "你真厉害",
        "config": _Cfg(), "trigger": "emotion_signal",
    }
    assert asyncio.run(maybe_react_on_message(bot, gate=ProactiveGate(), **kw)) is False
    assert asyncio.run(maybe_react_on_message(
        bot, gate=ProactiveGate(), bot_related=False, **kw)) is False
    assert bot.calls == []
    assert asyncio.run(maybe_react_on_message(
        bot, gate=ProactiveGate(), bot_related=True, **kw)) is True
    assert len(bot.calls) == 1


def test_private_session_never_calls_set_msg_emoji_like():
    """QQ 侧不存在私聊表情回应通道（不是迁移退化）：SnowLuma 对非群消息直接抛
    ``emoji reactions are not supported on private messages``（实测 36 次）。
    私聊一律在派发前拒掉——绝不出 set_msg_emoji_like、不占门、不刷失败日志。"""
    bot = FakeBot()
    base = {
        "text": "谢谢你帮大忙", "config": _Cfg(), "trigger": "emotion_signal",
    }
    # 私聊 session 键 = 裸 user_id（镜像 OneBot，见同文件归一化用例）
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="9900", user_message_id=82, gate=ProactiveGate(), **base)) is False
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="9901", user_message_id=83, gate=ProactiveGate(),
        bot_related=True, **base)) is False
    # 换 after_reply 触发形同样不派发
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="9902", user_message_id=84, text="今天赢了比赛",
        config=_Cfg(), trigger="after_reply", gate=ProactiveGate())) is False
    assert bot.calls == []


def test_i3_comfort_keywords_simplified_traditional():
    """I3：简体「伤心」与繁体裸「難過」命中安慰；繁体「謝謝」命中感动。"""
    from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
        infer_signal_intent,
    )

    assert infer_signal_intent("我好伤心") == "安慰"
    assert infer_signal_intent("有點難過") == "安慰"
    assert infer_signal_intent("好難過啊") == "安慰"
    assert infer_signal_intent("謝謝你，辛苦了") == "感动"
    assert infer_signal_intent("今天运气不错") is None


def test_normal_scenes_unaffected():
    """正常场景照常：群聊非悲伤消息 after_reply 照贴、群聊信号命中照贴。"""
    bot = FakeBot()
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="group_1_1", user_message_id=91, text="今天赢了比赛好开心",
        config=_Cfg(), trigger="after_reply", gate=ProactiveGate(),
    )) is True
    assert len(bot.calls) == 1
    bot2 = FakeBot()
    assert asyncio.run(maybe_react_on_message(
        bot2, session_key="group_3_4", user_message_id=92, text="太棒了，说得好",
        config=_Cfg(), trigger="emotion_signal", gate=ProactiveGate(),
        bot_related=True,
    )) is True
    assert len(bot2.calls) == 1


# ------------------------------------------------- QSid 锚点（faceid-verify-report）


def test_qsid_intent_mapping_anchors():
    """表 A 五处改值锚点：防回退到经典表错位 id（41 发抖/19 吐/14 微笑/29 悠闲/27 流汗）。"""
    assert REACTION_INTENT_EMOJIS["赞同"] == 76  # 赞（保守备选 13 呲牙未采用）
    assert REACTION_INTENT_EMOJIS["有趣"] == 20  # 偷笑
    assert REACTION_INTENT_EMOJIS["惊讶"] == 0  # QSid 0=惊讶（与经典 0=微笑 互换）
    assert REACTION_INTENT_EMOJIS["加油"] == 30  # 奋斗
    assert REACTION_INTENT_EMOJIS["憨笑"] == 28  # 憨笑


def test_qsid_intent_values_no_unintended_collision():
    """改后无撞车：除 安慰/感动 有意同 id（流泪 5，语义随上下文）外各占一脸。"""
    values = list(REACTION_INTENT_EMOJIS.values())
    dupes = {v for v in values if values.count(v) > 1}
    assert dupes == {5}


def test_qsid_face_name_anchors():
    """表 B 名称锚点：QSid 重写后 0=惊讶/14=微笑/16 起错位段/41-43 换血/76=赞。"""
    assert QSID_FACE_NAMES[0] == "惊讶"
    assert QSID_FACE_NAMES[14] == "微笑"
    assert QSID_FACE_NAMES[16] == "酷"
    assert QSID_FACE_NAMES[27] == "流汗" and QSID_FACE_NAMES[28] == "憨笑"
    assert QSID_FACE_NAMES[29] == "悠闲" and QSID_FACE_NAMES[30] == "奋斗"
    assert QSID_FACE_NAMES[41] == "发抖"
    assert QSID_FACE_NAMES[42] == "爱情"
    assert QSID_FACE_NAMES[43] == "跳跳"
    assert 17 not in QSID_FACE_NAMES and 40 not in QSID_FACE_NAMES  # QSid 缺号
    assert QSID_FACE_NAMES.get(76) == "赞"
    # 展示闭环：贴 QSid 0 出「惊讶」不串「微笑」；缺号诚实兜底
    assert emoji_display("0") == "「惊讶」"
    assert emoji_display("14") == "「微笑」"
    assert emoji_display("17") == "QQ表情#17"


def test_qsid_intent_face_semantics_closed_loop():
    """意图→id→QSid 名称闭环：除有意同悲的 感动→流泪 外，名实相符。"""
    expect = {
        "赞同": "赞", "开心": "呲牙", "有趣": "偷笑", "害羞": "害羞",
        "惊讶": "惊讶", "感动": "流泪", "加油": "奋斗", "憨笑": "憨笑",
    }
    for intent, name in expect.items():
        assert QSID_FACE_NAMES.get(REACTION_INTENT_EMOJIS[intent]) == name, intent


def test_qsid_after_reply_pool_mild_faces_and_c1_intact():
    """兜底池=中性温和三脸（赞76/惊讶0/害羞6，tone-audit M2 的 QSid 平移）；
    C1 悲伤门换池后不回退。"""
    from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
        _REACTION_FALLBACK_INTENTS,
        is_sad_message,
    )

    pool_ids = {REACTION_INTENT_EMOJIS[n] for n in _REACTION_FALLBACK_INTENTS}
    assert pool_ids == {76, 0, 6}
    assert is_sad_message("我心好累") is True
    bot = FakeBot()
    assert asyncio.run(maybe_react_on_message(
        bot, session_key="group_5_6", user_message_id=401, text="好累，撑不住了",
        config=_Cfg(), trigger="after_reply", gate=ProactiveGate(),
    )) is False
    assert bot.calls == []


def test_qsid_signal_posts_correct_face_end_to_end():
    """端到端：信号词 → 意图 → QSid 正形出 API（76 赞 / 0 惊讶 / 30 奋斗）。"""
    cases = (
        ("太厉害了，说得好", "76"),
        ("不会吧，真的假的？", "0"),
        ("加油，冲鸭！", "30"),
    )
    for idx, (text, emoji_id) in enumerate(cases):
        bot = FakeBot()
        assert asyncio.run(maybe_react_on_message(
            bot, session_key=f"group_8_{idx}", user_message_id=600 + idx,
            text=text, config=_Cfg(), trigger="emotion_signal",
            gate=ProactiveGate(), bot_related=True,
        )) is True
        assert bot.calls == [(
            "set_msg_emoji_like",
            {"message_id": 600 + idx, "emoji_id": emoji_id},
        )]


# ------------------------------------------------- 审查 L-02：_window LRU 上界


def test_l02_window_keys_capped_at_4096():
    """L-02 回归①：_window 键数封顶 _REACTION_LRU_CAP=4096（对齐 _last/
    _reacted/_rolled 惯例），长跑不再随会话键无界增长。"""
    from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
        _REACTION_LRU_CAP,
    )

    gate = ProactiveGate()
    kwargs = {
        "enabled": True, "probability": 1.0,
        "cooldown_seconds": 0.0, "max_per_hour": 20,
    }
    # 超量会话键涌入：每个新键都会在 allow() 里触达 _window 并登记。
    for i in range(_REACTION_LRU_CAP + 1000):
        assert gate.allow(f"sess_{i}", "m", **kwargs) is True
    assert len(gate._window) == _REACTION_LRU_CAP  # 恰好封顶，不增不减


def test_l02_evicted_session_window_fresh_empty_bucket():
    """L-02 回归②：被淘汰的会话键再进来按全新空桶处理，不复活旧滑窗数据。"""
    clock = FakeClock()
    gate = ProactiveGate(clock=clock)
    kwargs = {
        "enabled": True, "probability": 1.0,
        "cooldown_seconds": 0.0, "max_per_hour": 2,
    }
    # s_old 滑窗填满（2/2；m3 被时限拦下）
    assert gate.allow("s_old", "m1", **kwargs) is True
    assert gate.allow("s_old", "m2", **kwargs) is True
    assert gate.allow("s_old", "m3", **kwargs) is False
    # 4096 个新键按插入序把 s_old 挤出 LRU（淘汰最旧触达键）
    for i in range(4096):
        assert gate.allow(f"flood_{i}", "m", **kwargs) is True
    assert "s_old" not in gate._window  # 已被淘汰
    # 再进来：滑窗从零重新计数——旧 2 条不复活（若复活 m4 会被拦）
    assert gate.allow("s_old", "m4", **kwargs) is True
    assert list(gate._window["s_old"]) == [clock.now]  # 全新桶仅含本次登记
    assert gate.allow("s_old", "m5", **kwargs) is True
    assert gate.allow("s_old", "m6", **kwargs) is False  # 新桶按 max_per_hour=2 封顶

"""折句窗口（一句话说完只回一次）的回归锁。

覆盖三件真会咬人的事：① 完整句子绝不该多等（零额外延迟）；
② 连发的短句只许产生一次回复；③ 封顶必放行——否则有人逐字蹦时
bot 永远不回，那比多回几句更糟。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.runtime.message_coalescing import (
    CoalescingSettings,
    MessageCoalescer,
    join_utterance,
    looks_unfinished,
    merge_turn,
)

QUICK = CoalescingSettings(quiet_seconds=0.05, max_hold_seconds=0.4)


def _message(
    text: str,
    *,
    sender_id: str = "u1",
    session_id: str = "group_10_u1",
    session_type: SessionType = SessionType.GROUP,
    message_id: str | None = None,
    **kwargs: object,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot_v11",
        bot_id="3958874605",
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        plain_text=text,
        message_id=message_id or f"m-{abs(hash((text, sender_id))) % 10**8}",
        **kwargs,  # type: ignore[arg-type]
    )


def _key(message: IncomingMessage) -> str:
    return f"{message.session_id}:{message.sender_id}"


# --------------------------------------------------------------------------
# 判据：什么算「半句话」
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["我今天去了", "这个天气，", "帮我看看：", "它其实还行而且", "a"],
)
def test_comma_split_fragments_are_treated_as_unfinished(text: str) -> None:
    assert looks_unfinished(text) is True


@pytest.mark.parametrize("text", ["今天天气不错。", "你在干嘛？", "好呀！", "走不走？"])
def test_complete_sentences_are_not_held(text: str) -> None:
    assert looks_unfinished(text) is False


def test_empty_text_is_not_held() -> None:
    assert looks_unfinished("") is False
    assert looks_unfinished("   ") is False


@pytest.mark.parametrize(
    "texts,expected",
    [
        (["我今天去了", "超市买东西"], "我今天去了，超市买东西"),
        (["今天天气不错。", "我们出去走走"], "今天天气不错。我们出去走走"),
        # 回归锁：分句标点也算「已经带上标点了」，再补一枚就拼出双逗号。
        (["守岸人，", "在吗"], "守岸人，在吗"),
        (["只有一句"], "只有一句"),
        ([], ""),
        (["  ", "x"], "x"),
    ],
)
def test_join_utterance_reads_like_one_sentence(texts: list[str], expected: str) -> None:
    assert join_utterance(texts) == expected


# --------------------------------------------------------------------------
# 一次连发 → 一次回复
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_split_sentence_yields_exactly_one_replyable_turn() -> None:
    """一句话拆三条发：只有开门那条拿到回复权，且拿到的是合并后的一轮。"""
    batcher = MessageCoalescer(QUICK)
    first, second, third = (
        _message("守岸人，"),
        _message("今天的潮汐怎么样，"),
        _message("适合出门吗"),
    )

    owner_task = asyncio.create_task(batcher.offer(_key(first), first))
    await asyncio.sleep(0.01)
    follower_a = await batcher.offer(_key(second), second)
    follower_b = await batcher.offer(_key(third), third)

    turn = await owner_task

    assert follower_a.owned is False
    assert follower_b.owned is False
    assert turn.owned is True
    assert turn.folded_count == 3
    assert turn.message.plain_text == "守岸人，今天的潮汐怎么样，适合出门吗"


@pytest.mark.asyncio
async def test_complete_sentence_returns_immediately_without_waiting() -> None:
    """正常完整句子不得为折句多等——这是零额外延迟的硬要求。"""
    batcher = MessageCoalescer(CoalescingSettings(quiet_seconds=5.0, max_hold_seconds=5.0))
    message = _message("今天天气不错。")

    started = time.monotonic()
    turn = await batcher.offer(_key(message), message)
    elapsed = time.monotonic() - started

    assert turn.owned is True
    assert turn.folded_count == 1
    assert turn.message is message
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_max_hold_caps_the_window_so_the_bot_cannot_stay_silent() -> None:
    """有人逐字蹦也得在封顶时开口：等待不得超过 max_hold_seconds。"""
    batcher = MessageCoalescer(
        CoalescingSettings(quiet_seconds=10.0, max_hold_seconds=0.12)
    )
    message = _message("一个字一个字地蹦")

    started = time.monotonic()
    turn = await batcher.offer(_key(message), message)
    elapsed = time.monotonic() - started

    assert turn.owned is True
    assert elapsed < 0.6, "封顶未生效，会长期不回话"


@pytest.mark.asyncio
async def test_message_count_cap_flushes_without_waiting_for_quiet() -> None:
    """折够 max_messages 条立即放行，不必等停口。"""
    batcher = MessageCoalescer(
        CoalescingSettings(quiet_seconds=5.0, max_hold_seconds=5.0, max_messages=2)
    )
    first, second, third = _message("第一段，"), _message("第二段，"), _message("第三段")

    owner_task = asyncio.create_task(batcher.offer(_key(first), first))
    await asyncio.sleep(0.01)
    await batcher.offer(_key(second), second)

    turn = await asyncio.wait_for(owner_task, timeout=1.0)
    assert turn.folded_count == 2

    # 第三段属于新的一轮：必须自己拿到回复权，不能被吞。
    later = await batcher.offer(_key(third), third)
    assert later.owned is True


@pytest.mark.asyncio
async def test_disabled_switch_is_byte_identical_to_old_behaviour() -> None:
    """开关关闭 ⇒ 每条各自成轮、永不合并（回到改造前形态）。"""
    batcher = MessageCoalescer(CoalescingSettings(enabled=False))
    first, second = _message("守岸人，"), _message("在吗")

    turn_a = await batcher.offer(_key(first), first)
    turn_b = await batcher.offer(_key(second), second)

    assert turn_a.owned is True and turn_b.owned is True
    assert turn_a.message is first
    assert turn_b.message is second
    assert batcher.pending_keys == ()


@pytest.mark.asyncio
async def test_different_senders_do_not_share_a_window() -> None:
    """折句按 (会话, 发送者) 分键：不得把两个人的话合成一句回。"""
    batcher = MessageCoalescer(QUICK)
    mine = _message("我先说一句，", sender_id="u1")
    yours = _message("我也说一句，", sender_id="u2", session_id="group_10_u2")

    task_a = asyncio.create_task(batcher.offer(_key(mine), mine))
    task_b = asyncio.create_task(batcher.offer(_key(yours), yours))
    turn_a, turn_b = await task_a, await task_b

    assert turn_a.folded_count == 1 and turn_b.folded_count == 1
    assert turn_a.message.plain_text == "我先说一句，"
    assert turn_b.message.plain_text == "我也说一句，"


@pytest.mark.asyncio
async def test_two_complete_sentences_apart_are_not_merged() -> None:
    """两句都说完了、又隔过停口窗 ⇒ 各回各的。

    这条是「故意不折」的锁：曾经想过「此人最近在连发就也等」，但那会让正常
    一来一回的对话每条都白白多等一个窗口。折句只救半句话，不拖慢完整句子。
    """
    batcher = MessageCoalescer(QUICK)
    one = _message("第一句说完了。", message_id="a1")
    two = _message("第二句也说完了。", message_id="a2")

    turn_one = await batcher.offer(_key(one), one)
    await asyncio.sleep(0.1)  # 越过停口窗：这两句已是两回事
    turn_two = await batcher.offer(_key(two), two)

    assert turn_one.owned is True and turn_one.folded_count == 1
    assert turn_two.owned is True and turn_two.folded_count == 1


@pytest.mark.asyncio
async def test_no_task_leak_after_repeated_timeouts() -> None:
    """超时不得留下永不结束的等待任务（shield 写法就会犯这个错）。"""
    batcher = MessageCoalescer(
        CoalescingSettings(quiet_seconds=0.02, max_hold_seconds=0.25)
    )
    before = len(asyncio.all_tasks())
    for index in range(6):
        message = _message(f"第{index}次连发，", message_id=f"leak-{index}")
        await batcher.offer(_key(message), message)
    await asyncio.sleep(0.05)
    assert len(asyncio.all_tasks()) <= before


# --------------------------------------------------------------------------
# 合并后的身份事实归并
# --------------------------------------------------------------------------


def test_merge_keeps_head_identity_and_orients_flags() -> None:
    head = _message("守岸人，", message_id="m1")
    tail = _message(
        "今天的潮汐怎么样",
        message_id="m2",
        mentions_bot=True,
        name_mention_only=False,
        raw_segments=[{"type": "text", "data": {"text": "今天的潮汐怎么样"}}],
    )
    merged = merge_turn([head, tail])

    assert merged.message_id == "m1"
    assert merged.request_id == head.request_id
    assert merged.plain_text == "守岸人，今天的潮汐怎么样"
    assert merged.mentions_bot is True
    assert len(merged.raw_segments) == 1 + len(head.raw_segments)
    # 原对象不得被就地改掉：合并只产出副本。
    assert head.mentions_bot is False


def test_name_mention_only_requires_every_fragment_soft() -> None:
    """有一条是硬 @，合并轮就不能被当成「只是写了名字」。"""
    soft_a = _message("岸宝，", mentions_bot=True, name_mention_only=True)
    soft_b = _message("在干嘛", mentions_bot=True, name_mention_only=True)
    assert merge_turn([soft_a, soft_b]).name_mention_only is True

    hard = _message("在干嘛", mentions_bot=True, name_mention_only=False)
    assert merge_turn([soft_a, hard]).name_mention_only is False


def test_single_message_merge_is_a_noop() -> None:
    only = _message("就一句话。")
    assert merge_turn([only]) is only


def test_merge_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        merge_turn([])

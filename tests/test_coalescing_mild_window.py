"""短句号气泡轻等窗的强度微调（聊天体验波 2026-10-02）。

已知短板（message_coalescing 模块尾注 a）：各自带句号的两条短句，到达差超过
旧轻等窗 0.45×3.0s≈1.35s 就折不住。本席把 ``_MILD_STRENGTH`` 0.45→0.6（轻等窗
≈1.8s），这里锁新窗宽与端到端行为。普通单句的代价：带句号 ≤12 字的单发气泡
最多多等 ~0.45s——强终止语气（？！）仍零等待，硬底线不动。
"""

from __future__ import annotations

import asyncio

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.runtime.message_coalescing import (
    CoalescingSettings,
    MessageCoalescer,
    effective_quiet_seconds,
    utterance_completion,
)


def _message(text: str, *, message_id: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot_v11",
        bot_id="3958874605",
        session_id="group_10_u1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        plain_text=text,
        message_id=message_id,
    )


def _key(message: IncomingMessage) -> str:
    return f"{message.session_id}:{message.sender_id}"


def test_mild_window_now_covers_beyond_the_old_1_35s() -> None:
    """短句号轻等窗 ≥1.5s：到达差 1.35s~1.5s 的连发不再落空（旧值锁不住这段）。"""
    settings = CoalescingSettings(quiet_seconds=3.0)
    verdict = utterance_completion("今天天气不错。")
    assert verdict.pending and "short_burst_fragment" in verdict.signals
    assert effective_quiet_seconds(settings, verdict.strength) >= 1.5


@pytest.mark.asyncio
async def test_short_period_pair_with_gap_over_1_35s_still_folds() -> None:
    """端到端：两条各自带句号的短句、到达差 ~1.55s（旧窗 1.35s 折不住的那段）。"""
    batcher = MessageCoalescer(
        CoalescingSettings(quiet_seconds=3.0, max_hold_seconds=8.0)
    )
    first = _message("今天天气不错。", message_id="w1")
    second = _message("花房也开了。", message_id="w2")
    owner = asyncio.create_task(batcher.offer(_key(first), first))
    await asyncio.sleep(1.55)
    follower = await batcher.offer(_key(second), second)
    turn = await owner
    assert follower.owned is False, "第二条该折进同一轮，不该另起一轮回第二句"
    assert turn.owned is True and turn.folded_count == 2
    assert "今天天气不错" in turn.message.plain_text
    assert "花房也开了" in turn.message.plain_text


@pytest.mark.asyncio
async def test_strong_terminal_tone_still_replies_without_waiting() -> None:
    """硬底线不动：？！收尾零额外延迟，微调不许把正常一问一答拖进等待窗。"""
    batcher = MessageCoalescer(
        CoalescingSettings(quiet_seconds=3.0, max_hold_seconds=8.0)
    )
    message = _message("在吗？", message_id="q1")
    started = asyncio.get_running_loop().time()
    turn = await batcher.offer(_key(message), message)
    elapsed = asyncio.get_running_loop().time() - started
    assert turn.owned is True
    assert elapsed < 0.3, f"强终止语气开了等待窗（{elapsed:.2f}s），硬底线被破"

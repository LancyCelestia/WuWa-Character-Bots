"""管线检视 #10 收口：分片超时单段预算下限（B-7）回归锁死 + A-03 组合上界。

现状核实（2026-09-14）：sender/onebot.py::_TimeoutBudget.slice_for 已有下限钳制：

    min(max(总预算 / 段数, _MIN_CHUNK_WAIT_SECONDS=10.0), 剩余预算)

单段永不低于 10s；唯一例外是剩余总预算本身不足下限——此时取剩余，
总时长由 send_onebot_v11 的外层整体 wait_for 兜底，绝不过 deadline。
既有 prfix10 / B-7 测试（test_prfix_sender.py、test_bgroup_sender_delivery.py）
已锁「钳制触发（2.5s→10s）」与「remaining 取剩余」两条；本文件补三块缺口：

① 大预算多段直通：均分值高于下限时取均分（下限不拉长快路径），
   且真实 chunks 循环式逐段连切每次结果一致 ≥ 下限；
② 预算总量 < 下限×段数（钳制常驻场景）：连切全程每段仍各拿下限；
   墙钟推进到剩余不足时取剩余、耗尽抛 TimeoutError——外层护栏接管。
③ 与 A-03 零送达重试语义组合的循环上界实测：极短预算 → 首段超时
   （零送达）→ FAILED_RETRYABLE。A-03 超时路径不做传输内重试——
   send_onebot_v11 首次尝试即 return 交回队列（onebot.py「will_retry=true」
   指队列侧重试），每次 worker 轮询至多 1 次网络尝试；队列 retry_count 达
   max_attempts=3（sender/queue.py 终态分支「retry_count >=
   self.max_attempts」，既有 test_queue_poison_row 已锁）置 FAILED_FINAL
   不再交投——总网络尝试 ≤ 3 的常数上界，不可能无限循环。

离线运行（无网络、无 NapCat）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_onebot_chunk_budget_floor.py -q
"""

from __future__ import annotations

import asyncio

import pytest

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.sender import onebot as onebot_sender
from plugins.bot_unified_runtime.sender.onebot import send_onebot_v11


def _chunk_request(request_id: str, chunks: list[str]) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="chunks",
        content_ref={"chunks": list(chunks)},
        text_fallback="".join(chunks),
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=len(chunks),
        dedupe_key=f"dedupe-{request_id}",
        cooldown_key="bot.chat:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        adapter="onebot",
        bot_id="qq-bot",
    )


# ==================== ① 大预算多段直通 + 连切一致 ====================


def test_slice_passthrough_when_average_above_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """均分 12s 高于下限 10s → 直通取均分，下限不拉长快路径。

    冻结时钟隔离 wall clock：_TimeoutBudget 的 remaining 只随 monotonic
    流逝，冻结后连切结果恒定，可精确断言。
    """
    assert onebot_sender._MIN_CHUNK_WAIT_SECONDS == 10.0
    monkeypatch.setattr(onebot_sender.time, "monotonic", lambda: 1000.0)
    budget = onebot_sender._TimeoutBudget(600.0)
    assert budget.slice_for(50) == pytest.approx(12.0)
    # 真实 chunks 循环每段各切一次 slice_for(len(chunks))：
    # 50 段连切，每次都应一致且 ≥ 下限。
    slices = [budget.slice_for(50) for _ in range(50)]
    assert slices == [pytest.approx(12.0)] * 50
    assert all(s >= onebot_sender._MIN_CHUNK_WAIT_SECONDS for s in slices)


def test_slice_floor_holds_on_repeated_calls_when_budget_covers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """② 预算总量(15s) < 下限(10s)×段数(4)：连切全程每段仍各拿下限 10s。

    这是 B-7 的有意取舍：钳制后「下限×段数」理论上限可超总预算，总时长
    不失控由外层整体 wait_for（send_onebot_v11）兜底，而非削弱单段下限。
    """
    monkeypatch.setattr(onebot_sender.time, "monotonic", lambda: 1000.0)
    budget = onebot_sender._TimeoutBudget(15.0)
    slices = [budget.slice_for(4) for _ in range(4)]
    assert slices == [10.0, 10.0, 10.0, 10.0]


def test_slice_floor_yields_to_remaining_then_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """② 补充：墙钟真实推进时，剩余充足各拿下限；剩余耗尽抛 TimeoutError。

    30s 预算 4 段：前三次切片 remaining=30/20/10 全 ≥ 下限 → 各拿 10s；
    30s 花完后 slice_for 直接抛 TimeoutError（上层按零送达超时语义处理），
    单段等待永不越过外层 deadline。
    """
    now = {"t": 1000.0}
    monkeypatch.setattr(onebot_sender.time, "monotonic", lambda: now["t"])
    budget = onebot_sender._TimeoutBudget(30.0)
    slices = []
    for _ in range(3):
        slices.append(budget.slice_for(4))
        now["t"] += 10.0
    assert slices == [10.0, 10.0, 10.0]
    now["t"] += 10.0
    with pytest.raises(asyncio.TimeoutError):
        budget.slice_for(4)


# ==================== ③ 与 A-03 零送达重试语义组合的上界 ====================


class _NeverRepliesBot:
    """每次调用都慢于单段预算：首段即超时、零副作用（count==0）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def send_private_msg(self, **kwargs: object) -> dict:
        self.calls += 1
        await asyncio.sleep(1.0)
        return {"status": "ok", "retcode": 0}

    async def send_group_msg(self, **kwargs: object) -> dict:
        return await self.send_private_msg()


@pytest.mark.asyncio
async def test_extreme_short_budget_composes_with_a03_retry_bound() -> None:
    """③ 极短预算(0.6s < 下限 10s) → 段超时(取剩余 0.6s) → A-03 零送达
    → FAILED_RETRYABLE，且传输内不烧重试预算（恰 1 次尝试即交回队列）。

    循环上界推导（单级封顶，不是「超时→重试」自激环）：
    - A-03 超时零送达分支（onebot.py except asyncio.TimeoutError →
      progress.count==0）**立即 return** FAILED_RETRYABLE，不做传输内
      attempt 重试（_ONEBOT_SEND_RETRY_DELAYS 只服务普通异常分支）——
      本测试实测 bot 恰被调 1 次；
    - 队列层：FAILED_RETRYABLE 交回 SQLiteSendRequestQueue，retry_count
      达 max_attempts=3 后置 FAILED_FINAL 不再交投（queue.py 的
      retry_count >= max_attempts 分支；终态锁见 test_queue_poison_row）。
    总网络尝试 ≤ 3（队列封顶）——即使每轮都因极短预算超时也必然终止，
    不会无限重试。
    """
    bot = _NeverRepliesBot()
    receipt = await send_onebot_v11(
        bot,
        _chunk_request("req-budget-floor-a03", ["分片一", "分片二"]),
        timeout_seconds=0.6,
    )  # type: ignore[arg-type]
    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert receipt.public_message == ""
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "timeout_zero_part_delivered"
    assert receipt.operational_issue.retryable is True
    # 传输内零烧耗：超时零送达路径首次尝试即交回队列（重试由队列封顶）。
    assert bot.calls == 1
    assert receipt.operational_issue.attempts == 1

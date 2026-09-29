"""超时改造 C1（2026-09-28）：管线能力单次执行硬超时 ⇒ 挂死必须出卡。

钉住的缺陷链（前席取证，逐处 file:line 见 AGENTS 第四部分「统一错误报告卡」行与
台账 #49★「未执法」条）：

- `offload_capability`（真身 `domains/chat_reply/runtime/pipeline.py`）改动前
  **没有任何逐任务时限**（在册 M-4，位置＝
  `docs/design/audit-20260920-unify-U4-dispatch.md:168`）；
- 全管线唯一的 `wait_for` 在 `_await_with_progress_ack`，它套着 `asyncio.shield`
  ⇒ 连"先回执"那条路都不会杀真实任务，且该键缺省关；
- 中央 invoker 有逐次预算并把 `concurrent.futures.TimeoutError` 包成
  `CapabilityTimeout`（`runtime/capability_protocols.py:753-776`），但 **bot.chat 的根
  不经过它**（根 `__init__.py` 直呼 `pipeline.handle_async`）。

三者合起来的现网形态＝能力挂死 ⇒ 这一轮永远 awaits ⇒ 用户白等、卡也不出。

本文件的判据（全离线，零端口零网络零 QQ）：

1. 到点抛的必须是 `CapabilityTimeout`（复用中央那一枚，禁第二族）；
2. 异常必须走到 `_internal_error` ⇒ `_maybe_send_error_card` 被触达（哨兵，不真渲染）；
3. 闸位（`_BoundedSubmissionGate` 许可）**不得在 worker 还占着时提前归还**——
   提前还会把有界池写成无界队列，挂死风暴时排队无上限，比"这一轮白等"更坏；
4. 正常返回路径零行为变化（快能力照旧立即归还闸位）；
5. 缺省值与解析链（driver config → env → Config 声明默认）+「必须严格高于请求预算」
   的抬底判据各有锁；缺省关不到 0（0 会把每条聊天都判成挂死）。
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import ReceiptState, SendPolicy
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.user_copy import (
    PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    pipeline as pipeline_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    _BoundedSubmissionGate,
    _pipeline_busy_result,
    _resolve_capability_hard_timeout_seconds,
    capability_hard_timeout_seconds,
    offload_capability,
    set_capability_hard_timeout_seconds,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.monitor import (
    error_report as error_report_module,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

_HANG_EVENT_TIMEOUT = 20.0  # 看护上限：只防测试挂死，不参与任何断言（真判据是 0.05s 硬超时）


class _NullAuditLogger:
    def append(self, record: object) -> None:
        return


def _message(session_id: str = "private:c1") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id="u-c1",
        plain_text="潮汐很安静",
        message_id="m-c1",
    )


def _decision(capability_id: str = "bot.chat") -> BotDecision:
    return BotDecision(
        request_id="req-c1",
        should_respond=True,
        mode="command",
        trigger="潮汐很安静",
        capability_id=capability_id,
        target_scope=SessionType.PRIVATE,
        decision_reason="c1",
    )


def _installed_pool(
    max_workers: int,
) -> tuple[ThreadPoolExecutor, _BoundedSubmissionGate, tuple[Any, Any]]:
    """向 pipeline 模块注入独立测试池，返回（池, 闸, 原状）供 finally 还原。"""
    pool = ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="c1-test-pool"
    )
    gate = _BoundedSubmissionGate(max_workers * 2)
    original = (pipeline_module._chat_pool, pipeline_module._chat_pool_gate)
    pipeline_module._chat_pool = pool
    pipeline_module._chat_pool_gate = gate
    return pool, gate, original


@pytest.fixture()
def card_tripwire(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, BaseException]]:
    """error_report 卡钩子的哨兵：记录每次触达，绝不真渲染/真投递。"""
    calls: list[tuple[str, BaseException]] = []

    def _spy(
        _pipeline: Any, _message_arg: Any, capability_id: str, exc: BaseException, **_kw: Any
    ) -> None:
        calls.append((capability_id, exc))

    monkeypatch.setattr(error_report_module, "maybe_submit_error_card", _spy)
    return calls


@pytest.fixture(autouse=True)
def _restore_globals() -> Any:
    """硬超时覆盖与解析缓存逐用例归零（防跨用例污染出"看起来时好时坏"的假象）。"""
    set_capability_hard_timeout_seconds(None)
    yield
    set_capability_hard_timeout_seconds(None)


async def _drain_loop(times: int = 6) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# ① 挂死 ⇒ 抛 CapabilityTimeout ⇒ 出卡（用户可见面的正面对撞用例）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hung_capability_raises_capability_timeout_and_fires_error_card(
    card_tripwire: list[tuple[str, BaseException]],
) -> None:
    """改动前这一发必然白等：capability 永不返回 ⇒ 无任何终态。

    现在：0.05s 到点 ⇒ `CapabilityTimeout` ⇒ `handle_async` 的 except ⇒
    `_internal_error` ⇒ `_maybe_send_error_card`（哨兵记到一次）。
    """
    release = threading.Event()

    def hanging_capability(message: IncomingMessage, decision: BotDecision) -> Any:
        release.wait(_HANG_EVENT_TIMEOUT)
        return None  # 永远等不到这里（测试里由 finally 放行，只为让线程干净退出）

    pool, _gate, original = _installed_pool(1)
    set_capability_hard_timeout_seconds(0.05)
    pipeline = pipeline_module.RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAuditLogger()),
        audit_logger=_NullAuditLogger(),
    )
    try:
        wrapped = offload_capability(hanging_capability)
        receipt = await pipeline.handle_async(_message(), wrapped, "bot.chat")

        assert receipt.state is ReceiptState.FAILED_FINAL, receipt.state
        assert receipt.operational_issue is not None
        # `_internal_error` 的 safe_summary＝`<capability_id>:<异常类名>`：这一行
        # 就是"挂死"与"抛异常"共用同一张卡的证据（异常身份必须上告警链）。
        assert receipt.operational_issue.safe_summary == "bot.chat:CapabilityTimeout"
        assert len(card_tripwire) == 1, "挂死仍不出卡＝M-4 未关账"
        capability_id, exc = card_tripwire[0]
        assert capability_id == "bot.chat"
        assert isinstance(exc, cp.CapabilityTimeout), type(exc)
        assert "硬超时" in str(exc)
    finally:
        release.set()
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_offload_timeout_propagates_capability_timeout_directly() -> None:
    """裸 offload 出口也必须抛（不靠管线兜住）：判据＝异常类型 + __cause__ 是真 TimeoutError。"""
    release = threading.Event()

    def hanging_capability(message: IncomingMessage, decision: BotDecision) -> Any:
        release.wait(_HANG_EVENT_TIMEOUT)
        return "late"

    pool, _gate, original = _installed_pool(1)
    set_capability_hard_timeout_seconds(0.05)
    try:
        with pytest.raises(cp.CapabilityTimeout) as raised:
            await offload_capability(hanging_capability)(_message(), _decision())
        assert isinstance(raised.value.__cause__, TimeoutError)
        assert "bot.chat" in str(raised.value)
    finally:
        release.set()
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# ② 闸位账：超时不许把有界池写成无界队列
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_permit_held_while_hung_worker_still_running() -> None:
    """超时只解调用方的白等，**不**谎报 worker 已空出。

    提前还许可 ⇒ 挂死任务仍在跑却腾出了额度 ⇒ 提交不再被有界闸挡住 ⇒ 排队无上限。
    这一发钉住"延后归还"：线程真退出前 `in_flight` 保持占用，退出后才归零。
    """
    started = threading.Event()
    release = threading.Event()

    def hanging_capability(message: IncomingMessage, decision: BotDecision) -> Any:
        started.set()
        release.wait(_HANG_EVENT_TIMEOUT)
        return "done"

    pool, gate, original = _installed_pool(1)
    set_capability_hard_timeout_seconds(0.05)
    try:
        wrapper = offload_capability(hanging_capability)
        with pytest.raises(cp.CapabilityTimeout):
            await wrapper(_message(), _decision())
        # 线程仍在 wait（started 已置位、release 未置位）⇒ 闸位必须还占着。
        assert started.wait(2) is True
        assert gate.in_flight == 1, (
            f"超时即还闸位＝把有界池改成无界队列（挂死风暴会无限排队）：{gate.in_flight}"
        )
        release.set()
        # 线程退出后由 done 回调归还；回调经 loop.call_soon 派发，要泵几下。
        for _ in range(200):
            await _drain_loop(2)
            await asyncio.sleep(0.01)
            if gate.in_flight == 0:
                break
        assert gate.in_flight == 0, "延后归还没落地＝闸位永久泄漏（池被钉死成 busy）"
    finally:
        release.set()
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_fast_capability_path_unchanged_by_hard_timeout() -> None:
    """预算内的正常回复零行为变化：结果原样返回、闸位当场归还（不许"顺手多等一会"）。"""

    def fast_capability(message: IncomingMessage, decision: BotDecision) -> str:
        return "ok"

    pool, gate, original = _installed_pool(1)
    set_capability_hard_timeout_seconds(30.0)
    try:
        value = await offload_capability(fast_capability)(_message(), _decision())
        assert value == "ok"
        assert gate.in_flight == 0
    finally:
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_capability_exception_still_releases_gate() -> None:
    """能力抛异常（非超时）同口径：闸位归零、异常原样向外走（旧语义不许被 shield 吞掉）。"""

    def failing_capability(message: IncomingMessage, decision: BotDecision) -> Any:
        raise RuntimeError("boom")

    pool, gate, original = _installed_pool(1)
    set_capability_hard_timeout_seconds(30.0)
    try:
        with pytest.raises(RuntimeError, match="boom"):
            await offload_capability(failing_capability)(_message(), _decision())
        await _drain_loop(4)
        assert gate.in_flight == 0
    finally:
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# ③ 数字面：缺省、解析链、以及"必须严格高于请求预算"的抬底
# ---------------------------------------------------------------------------


def test_config_defaults_keep_hard_timeout_above_request_budget() -> None:
    config = Config()
    assert config.bot_pipeline_capability_hard_timeout_seconds == 400.0
    # 外部闸不得抢在内部 deadline 前砍回复：硬超时必须严格大于请求预算。
    assert (
        config.bot_pipeline_capability_hard_timeout_seconds
        > config.bot_request_budget_seconds
    )


def test_resolver_chain_env_then_config_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """单元测试环境 nonebot 未初始化 ⇒ 解析链自动落到 os.environ → Config 声明默认。"""
    monkeypatch.delenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("BOT_REQUEST_BUDGET_SECONDS", raising=False)
    assert _resolve_capability_hard_timeout_seconds() == 400.0

    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "1000")
    assert _resolve_capability_hard_timeout_seconds() == 1000.0

    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "abc")
    assert _resolve_capability_hard_timeout_seconds() == 400.0

    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "0")
    # 0/负数不参与取值（0 会把每一条聊天立刻判成挂死），退回声明默认。
    assert _resolve_capability_hard_timeout_seconds() == 400.0


def test_resolver_raises_floor_above_request_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """.env 把硬超时调到请求预算之下 ⇒ 抬到「预算 + 余量」，不静默抢跑、也不拒绝启动。"""
    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "100")
    monkeypatch.setenv("BOT_REQUEST_BUDGET_SECONDS", "300")
    assert _resolve_capability_hard_timeout_seconds() == 360.0


def test_resolver_clamps_absurd_values_but_still_above_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "999999")
    monkeypatch.setenv("BOT_REQUEST_BUDGET_SECONDS", "300")
    assert _resolve_capability_hard_timeout_seconds() == 3600.0


def test_capability_hard_timeout_seconds_uses_override_without_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """override 在场 ⇒ 每次现算且不写缓存；清除后回到解析链（生产读法不变）。"""
    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "500")
    set_capability_hard_timeout_seconds(0.25)
    assert capability_hard_timeout_seconds() == 0.25
    set_capability_hard_timeout_seconds(None)
    first = capability_hard_timeout_seconds()
    assert first == 500.0
    # 缓存生效：改 env 不再影响本进程（改 .env 需重启，已登 RESTART_REQUIRED_KEYS）。
    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "700")
    assert capability_hard_timeout_seconds() == first


def test_busy_private_send_policy_is_not_silent() -> None:
    """C1-d 的载体判据（与 test_pipeline_review_fixes 同锁互证）：私聊超载快败
    必须走 IMMEDIATE 出站，群/频道仍 SILENT_AUDIT。"""
    private = _pipeline_busy_result(_message(), _decision())
    assert private.send_policy is SendPolicy.IMMEDIATE
    assert private.body in PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES
    assert private.operational_issue is not None
    assert private.operational_issue.kind == "pipeline_busy"

    group_message = _message("group:c1").model_copy(
        update={"session_type": SessionType.GROUP, "group_id": "g1"}
    )
    group = _pipeline_busy_result(
        group_message,
        _decision().model_copy(
            update={"capability_id": "bot.chat", "target_scope": SessionType.GROUP}
        ),
    )
    assert group.send_policy is SendPolicy.SILENT_AUDIT
    assert group.body == ""

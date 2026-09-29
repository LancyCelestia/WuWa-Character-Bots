"""管线检视修复回归（handoff task-6）：

- #3 视觉双门槛统一：generate(require_vision=True) 与 supports_vision 对齐，
  仅排除 text-only，不再要求正向 vision/multimodal/vlm 标签。
- #4 聊天专用有界线程池：offload_capability 走独立 chat-pipeline 池，
  在途（运行+排队）超限快败返回 pipeline_busy，不无限排队。

超时改造 C1-d（2026-09-28 用户裁定「绝不让用户零反馈」）改写了 #4 的**会话面**：
超载快败在**私聊**不再静默——补一句池内短句（user_copy.PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES）；
**群/频道仍按 09-12 实弹裁定保持静默**（超载不放大流量），本文件与
test_a19_group_failure_notice.py::test_group_pipeline_busy_stays_silent 各锁一侧。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import ReceiptState, SendPolicy
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.user_copy import (
    PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMProviderError,
    LLMReply,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
    QuietHoursChecker,
    QuietHoursDecision,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    pipeline as pipeline_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
    _BoundedSubmissionGate,
    _resolve_chat_pool_workers,
    inflight_scope_of,
    offload_capability,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue
from plugins.bot_unified_runtime.llm.model_router import ModelRouter, ModelSpec

# ==================== 修复 #3：vision 双门槛统一 ====================


class _RecordingProvider:
    def __init__(self, spec: ModelSpec, calls: list[str]) -> None:
        self._spec = spec
        self._calls = calls

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self._calls.append(self._spec.model_id)
        return LLMReply(
            text=f"ok:{self._spec.model_id}", provider="fake", model=self._spec.model
        )


def _spec(model_id: str, priority: int, *tags: str) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model_id,
        base_url="https://example.test/v1",
        api_key="key",
        tags=tuple(tags),
        priority=priority,
    )


def _router(specs: dict[str, ModelSpec]) -> tuple[ModelRouter, list[str]]:
    calls: list[str] = []
    router = ModelRouter(
        specs,
        provider_factory=lambda spec: _RecordingProvider(spec, calls),
    )
    return router, calls


def test_require_vision_keeps_channel_without_any_vision_tag() -> None:
    # 回归核心：无任何正向 vision 标签的渠道（未打标）此前会被过滤清空
    # → provider_not_configured 硬失败；现在必须仍可作为候选。
    router, calls = _router({"plain": _spec("plain", 1, "fast")})

    reply = router.generate(
        [{"role": "user", "content": "看图"}], message_text="看图", require_vision=True
    )

    assert reply.text == "ok:plain"
    assert calls == ["plain"]


def test_require_vision_excludes_text_only_channel() -> None:
    router, calls = _router(
        {"plain": _spec("plain", 1, "fast"), "textonly": _spec("textonly", 2, "text-only")}
    )

    reply = router.generate(
        [{"role": "user", "content": "看图"}], message_text="看图", require_vision=True
    )

    assert reply.text == "ok:plain"
    # text-only 渠道被排除，绝不作为视觉候选被调用。
    assert calls == ["plain"]


def test_require_vision_all_text_only_fails_fast_as_not_configured() -> None:
    router, calls = _router({"textonly": _spec("textonly", 1, "text-only")})

    with pytest.raises(LLMProviderError) as raised:
        router.generate(
            [{"role": "user", "content": "看图"}],
            message_text="看图",
            require_vision=True,
        )

    assert raised.value.error_kind == "provider_not_configured"
    assert calls == []


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (("fast",), True),
        (("vision",), True),
        (("multimodal",), True),
        (("text-only",), False),
    ],
)
def test_supports_vision_gate_matches_require_vision_filter(
    tags: tuple[str, ...], expected: bool
) -> None:
    router, _ = _router({"first": _spec("first", 1, *tags)})

    assert router.supports_vision() is expected


def test_vision_gate_preserves_candidate_order() -> None:
    # 门槛过滤只做排除，不重排；health 未开启时按 priority 序尝试。
    router, calls = _router({"second": _spec("second", 2), "first": _spec("first", 1)})

    reply = router.generate(
        [{"role": "user", "content": "看图"}], message_text="看图", require_vision=True
    )

    assert reply.text == "ok:first"
    assert calls == ["first"]


# ==================== 修复 #4：聊天专用有界线程池 ====================


def _message() -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text="你好",
        message_id="m-1",
    )


def _decision(capability_id: str = "bot.chat") -> BotDecision:
    return BotDecision(
        request_id="req-1",
        should_respond=True,
        mode="command",
        trigger="你好",
        capability_id=capability_id,
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )


@contextmanager
def _installed_pool(
    max_workers: int,
) -> Iterator[tuple[ThreadPoolExecutor, _BoundedSubmissionGate]]:
    """向 pipeline 模块注入独立测试池，退出时恢复原状并关闭测试池。"""
    pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="test-chat-pool")
    gate = _BoundedSubmissionGate(max_workers * 2)
    original = (pipeline_module._chat_pool, pipeline_module._chat_pool_gate)
    pipeline_module._chat_pool = pool
    pipeline_module._chat_pool_gate = gate
    try:
        yield pool, gate
    finally:
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


def test_bounded_gate_denies_over_permits_and_recovers() -> None:
    gate = _BoundedSubmissionGate(2)

    assert gate.try_acquire() is True
    assert gate.try_acquire() is True
    # 在途满 → 立即拒绝（快败语义）。
    assert gate.try_acquire() is False
    gate.release()
    assert gate.try_acquire() is True
    gate.release()
    gate.release()
    assert gate.in_flight == 0


# -------------------- S134·B：在途闸跨族不共计数器（裁定 3 项 B / CM-P-40 R2）

_SCOPES = ("visual", "audio")


def test_reserved_layer_is_per_family_not_shared_across_families() -> None:
    """通用层被一族占满后，另一族仍可取**自己**的保留格（改动前＝0 格）。"""
    gate = _BoundedSubmissionGate(4, reserved_permits=2, reserved_scopes=_SCOPES)

    visual = sum(1 for _ in range(50) if gate.try_acquire("visual"))
    audio = sum(1 for _ in range(50) if gate.try_acquire("audio"))

    assert visual == 6, f"视觉应拿到通用 4 + 自身保留 2，实拿 {visual}"
    assert audio == 2, f"语音只该拿到自己的保留位，实拿 {audio}（跨族又共用了计数器？）"
    assert gate.scope_in_flight("visual") == 2 and gate.scope_in_flight("audio") == 2
    assert gate.general_in_flight() == 4
    # 族外（如 bot.chat）不进保留层：只吃通用层，取不到就是取不到。
    assert gate.try_acquire("") is False
    assert gate.try_acquire("audio") is False
    assert gate.in_flight == 8


def test_reserved_layer_is_released_back_and_never_overissues() -> None:
    """成对取/还必须精确归零，且归零后容量与初值一致（防"保留层只进不出"）。"""
    gate = _BoundedSubmissionGate(4, reserved_permits=2, reserved_scopes=_SCOPES)
    held = ["visual"] * 6 + ["audio"] * 2
    for scope in held:
        assert gate.try_acquire(scope)
    assert gate.in_flight == 8 and gate.try_acquire("audio") is False
    for scope in held:
        gate.release(scope)
    assert (gate.in_flight, gate.general_in_flight()) == (0, 0)
    assert (gate.scope_in_flight("visual"), gate.scope_in_flight("audio")) == (0, 0)
    assert sum(1 for _ in range(6) if gate.try_acquire("audio")) == 6  # 完全恢复


def test_zero_reserved_permits_reproduces_the_old_single_counter() -> None:
    """缺省（reserved=0）＝逐字节旧形态：既给既有回归锁背书，也自证注毒样本可信。"""
    legacy = _BoundedSubmissionGate(4)
    assert sum(1 for _ in range(10) if legacy.try_acquire("visual")) == 4
    assert sum(1 for _ in range(10) if legacy.try_acquire("audio")) == 0


def test_inflight_scope_follows_the_ownership_roster() -> None:
    """族籍唯一真身＝族册：在册成员按族、族外与垃圾输入一律空串（fail-closed）。"""
    from plugins.bot_unified_runtime.domains.core import (
        capability_resource_ownership as ro,
    )

    assert inflight_scope_of("bot.tts") == "audio"
    assert inflight_scope_of("media.vision.image") == "visual"
    assert inflight_scope_of("bot.chat") == ""
    assert inflight_scope_of("") == "" and inflight_scope_of(None) == ""
    for cid in ro.FAMILY_MEMBERS["audio"]:
        assert inflight_scope_of(cid) == "audio", cid
    for cid in ro.FAMILY_MEMBERS["visual"]:
        assert inflight_scope_of(cid) == "visual", cid


@pytest.mark.asyncio
async def test_offload_admits_other_family_via_reserved_layer() -> None:
    """**活体端到端**：视觉占满在途 ⇒ 语音仍被放行（走 offload 真出口，不是手搓闸）。

    这是 CM-P-40 R2 那条"任一族占满即静默否决另一族"的正面对撞用例：改动前
    第三次的结果必为 `pipeline_busy`（`$TEMP/s134_probe_before.py` 实跑 0 格）。
    """
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-family-pool")
    gate = _BoundedSubmissionGate(2, reserved_permits=1, reserved_scopes=_SCOPES)
    original = (pipeline_module._chat_pool, pipeline_module._chat_pool_gate)
    pipeline_module._chat_pool, pipeline_module._chat_pool_gate = pool, gate

    def fast(message: IncomingMessage, decision: BotDecision) -> str:
        return "done"

    def busy(result: object) -> bool:
        return getattr(result, "audit_tags", None) == ["pipeline_busy:v1"]

    try:
        # 前提自证（确定性地，不靠 sleep）：把通用层 2 格 + 视觉自己的保留格全占住。
        held = ["visual"] * 3
        assert all(gate.try_acquire("visual") for _ in held)
        assert gate.general_in_flight() == 2 and gate.scope_in_flight("visual") == 1
        # 同族再取必须被拒（保留层不是一族的多倍额度）。
        assert gate.try_acquire("visual") is False

        wrapper = offload_capability(fast)
        audio = await wrapper(_message(), _decision("media.asr.speech"))
        assert not busy(audio), "语音被视觉的洪峰静默否决＝跨族共计数器又回来了"
        assert audio == "done"

        # 反向格：语音自己的保留位也被占满 ⇒ 照旧快败（分族不等于放开上界）。
        assert gate.try_acquire("audio") is True
        second = await wrapper(_message(), _decision("media.asr.speech"))
        assert busy(second), f"两族额度都占满却仍放行＝闸被写成了无界：{second!r}"
        # 族外（bot.chat 一类）永远只吃通用层：这里必然被拒。
        assert busy(await wrapper(_message(), _decision("bot.chat")))
        gate.release("audio")
        for _ in held:
            gate.release("visual")
        assert gate.in_flight == 0 and gate.general_in_flight() == 0
    finally:
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)



@pytest.mark.asyncio
async def test_offload_runs_on_dedicated_pool_thread() -> None:
    with _installed_pool(2) as (_pool, gate):

        def capability(message: IncomingMessage, decision: BotDecision) -> str:
            return threading.current_thread().name

        name = await offload_capability(capability)(_message(), _decision())

        # 必须落在管线专用池线程，而非默认执行器（默认池线程名带 mt_ 前缀
        # 的 asyncio 语义或 default 名），且任务结束后闸门计数归零。
        assert name.startswith("test-chat-pool")
        assert gate.in_flight == 0


@pytest.mark.asyncio
async def test_offload_fast_fails_with_pipeline_busy_when_gate_full() -> None:
    with _installed_pool(1) as (_pool, gate):
        release = threading.Event()

        def slow_capability(message: IncomingMessage, decision: BotDecision) -> str:
            release.wait(5)
            return "slow-done"

        wrapper = offload_capability(slow_capability)
        first = asyncio.ensure_future(wrapper(_message(), _decision()))
        second = asyncio.ensure_future(wrapper(_message(), _decision()))
        # 各让出事件环 tick，使前两条完成闸门获取（1 运行 + 1 排队 = 2 许可满）。
        for _ in range(4):
            await asyncio.sleep(0)
        assert gate.in_flight == 2

        third = await wrapper(_message(), _decision())

        # 超限快败：明确的 busy 结果，不排队等待。会话面按 C1-d 分档——
        # 本用例的消息是**私聊** ⇒ 必须说话（IMMEDIATE + 池内短句），
        # 审计标签与 issue 一字未动（群侧静默契约由 test_a19 与本文件群用例锁）。
        assert third.operational_issue is not None
        assert third.operational_issue.kind == "pipeline_busy"
        assert third.operational_issue.retryable is True
        assert third.send_policy is SendPolicy.IMMEDIATE
        assert third.body in PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES
        assert "pipeline_busy:v1" in third.audit_tags
        assert gate.in_flight == 2  # 快败不占用闸门

        release.set()
        assert await first == "slow-done"
        assert await second == "slow-done"
        assert gate.in_flight == 0


@pytest.mark.asyncio
async def test_offload_gate_released_after_capability_error() -> None:
    with _installed_pool(1) as (_pool, gate):

        def failing_capability(message: IncomingMessage, decision: BotDecision) -> str:
            raise RuntimeError("boom")

        wrapper = offload_capability(failing_capability)
        with pytest.raises(RuntimeError, match="boom"):
            await wrapper(_message(), _decision())

        # 能力异常也必须释放闸门，否则泄漏会把池锁死成永久 busy。
        assert gate.in_flight == 0


def test_resolve_pool_workers_env_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    # 单元测试环境 nonebot 未初始化，解析链自动落到 os.environ → 默认。
    cases = {
        "3": 3,
        "999": 64,  # 上限钳位
        "0": 1,  # 下限钳位
        "abc": 8,  # 非法值回退默认
    }
    for raw, expected in cases.items():
        monkeypatch.setenv("BOT_PIPELINE_MAX_WORKERS", raw)
        assert _resolve_chat_pool_workers() == expected
    monkeypatch.delenv("BOT_PIPELINE_MAX_WORKERS")
    assert _resolve_chat_pool_workers() == 8


def test_config_default_pool_workers() -> None:
    assert Config().bot_pipeline_max_workers == 8


def _group_message() -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:g-busy",
        session_type=SessionType.GROUP,
        sender_id="u-group",
        group_id="g-busy",
        plain_text="你好",
        mentions_bot=True,
    )


@pytest.mark.asyncio
async def test_pipeline_busy_emits_private_line() -> None:
    """C1-d（超时改造第三格）：私聊超载快败**必须说话**。

    改动前私聊与群聊同享 SILENT_AUDIT ⇒ 用户明确找 bot 却被在途闸静默否决，
    一个字都收不到（本用例即那条零反馈路径的正面锁）。判据取**出站请求**，
    不取散文：私聊恰好一条请求、正文必属池、审计标签仍是 pipeline_busy:v1。
    """
    queue = InMemorySendQueue(audit_logger=_NullAuditLogger())
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=_NullAuditLogger(),
    )
    with _installed_pool(1):
        release = threading.Event()

        def slow_capability(message: IncomingMessage, decision: BotDecision) -> str:
            release.wait(5)
            return "slow-done"

        wrapper = offload_capability(slow_capability)
        first = asyncio.ensure_future(wrapper(_message(), _decision()))
        second = asyncio.ensure_future(wrapper(_message(), _decision()))
        for _ in range(4):
            await asyncio.sleep(0)
        busy_result = await wrapper(_message(), _decision())
        release.set()
        await first
        await second

    receipt = await pipeline.handle_async(
        _message(),
        _static_capability(busy_result),
        "bot.chat",
    )

    assert receipt.state is ReceiptState.SENT, receipt.state
    assert len(queue.sent_requests) == 1, "私聊超载必须恰好一句，不多发"
    request = queue.sent_requests[0]
    assert request.content.text_fallback in PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES
    # 错误细节不外传：池句里不含 issue 代号/能力名，审计标签保持既有那一枚。
    assert "pipeline_busy" not in request.content.text_fallback
    assert "pipeline_busy:v1" in request.audit_tags
    # 群侧静默（09-12 裁定）仍由 _pipeline_busy_result 的会话分档保证，见下一发。
    group_busy = _pipeline_busy_result_for(_group_message(), SessionType.GROUP)
    assert group_busy.send_policy is SendPolicy.SILENT_AUDIT
    assert group_busy.body == ""


def test_pipeline_busy_group_stays_silent_at_the_source() -> None:
    """群/频道档零变化：超载快败仍 SILENT_AUDIT + 空正文（超载不放大流量）。"""
    for session_type in (SessionType.GROUP, SessionType.CHANNEL):
        busy = _pipeline_busy_result_for(
            _group_message().model_copy(
                update={"session_type": session_type, "session_id": f"{session_type.value}:s"}
            ),
            session_type,
        )
        assert busy.send_policy is SendPolicy.SILENT_AUDIT, session_type
        assert busy.body == "", session_type
        assert busy.operational_issue is not None
        assert busy.operational_issue.kind == "pipeline_busy", session_type
        assert busy.audit_tags == ["pipeline_busy:v1"], session_type


def _pipeline_busy_result_for(message: IncomingMessage, session_type: SessionType) -> object:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
        _pipeline_busy_result,
    )

    return _pipeline_busy_result(
        message,
        BotDecision(
            request_id=message.request_id,
            should_respond=True,
            mode="command",
            trigger="你好",
            capability_id="bot.chat",
            target_scope=session_type,
            decision_reason="c1-d",
        ),
    )


class _NullAuditLogger:
    def append(self, record: object) -> None:
        return


def _static_capability(result: object):
    async def _run(message: IncomingMessage, decision: BotDecision) -> object:
        return result

    return _run


# ==================== 修复：安静时间拦截一律静默（2026-09-16 实弹） ====================


class _AlwaysBlockedQuietHours(QuietHoursChecker):
    def check(self, message: object, capability_id: str) -> QuietHoursDecision:
        return QuietHoursDecision(
            allowed=False,
            reason="inside_window",
            audit_tags=["quiet_hours:block"],
        )


@pytest.mark.asyncio
async def test_quiet_hours_block_is_silent() -> None:
    # 与限流拦截同款（2026-09-12 实弹裁定）：安静时间提示语进群即无接触刷屏
    # （无人 @ 也回一句），必须 public_message 置空；审计留痕不受影响。
    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAuditLogger()),
        audit_logger=_NullAuditLogger(),
        quiet_hours_checker=_AlwaysBlockedQuietHours(),
    )
    receipt = await pipeline.handle_async(
        _message(),
        _static_capability("ok"),
        "bot.chat",
    )
    assert receipt.state == ReceiptState.BLOCKED
    assert receipt.public_message == ""

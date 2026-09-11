"""管线检视修复回归（handoff task-6）：

- #3 视觉双门槛统一：generate(require_vision=True) 与 supports_vision 对齐，
  仅排除 text-only，不再要求正向 vision/multimodal/vlm 标签。
- #4 聊天专用有界线程池：offload_capability 走独立 chat-pipeline 池，
  在途（运行+排队）超限快败返回 pipeline_busy，不无限排队。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import ReceiptState
from plugins.bot_unified_runtime.contracts.runtime import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.llm.model_router import ModelRouter, ModelSpec
from plugins.bot_unified_runtime.llm.providers import LLMProviderError, LLMReply
from plugins.bot_unified_runtime.runtime import pipeline as pipeline_module
from plugins.bot_unified_runtime.runtime.pipeline import (
    RuntimePipeline,
    _BoundedSubmissionGate,
    _resolve_chat_pool_workers,
    offload_capability,
)
from plugins.bot_unified_runtime.sender import InMemorySendQueue

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


def _decision() -> BotDecision:
    return BotDecision(
        request_id="req-1",
        should_respond=True,
        mode="command",
        trigger="你好",
        capability_id="bot.chat",
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

        # 超限快败：明确的 busy 结果，SILENT_AUDIT 不外发，不排队等待。
        assert third.operational_issue is not None
        assert third.operational_issue.kind == "pipeline_busy"
        assert third.operational_issue.retryable is True
        assert third.send_policy.value == "silent_audit"
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


@pytest.mark.asyncio
async def test_busy_result_reaches_pipeline_as_silent_audit() -> None:
    # busy 结果经 RuntimePipeline._complete 必须落在 SKIPPED/SILENT_AUDIT
    # 分支，与失败静默的既有设计一致，不产生外发流量。
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

    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAuditLogger()),
        audit_logger=_NullAuditLogger(),
    )
    receipt = await pipeline.handle_async(
        _message(),
        _static_capability(busy_result),
        "bot.chat",
    )
    assert receipt.state == ReceiptState.SKIPPED


class _NullAuditLogger:
    def append(self, record: object) -> None:
        return


def _static_capability(result: object):
    async def _run(message: IncomingMessage, decision: BotDecision) -> object:
        return result

    return _run

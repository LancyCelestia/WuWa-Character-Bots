"""错误卡两段式异步化回归（2026-09-14 P0 修复，A-rec）。

P0 实锤（error-card-async-design.md §二）：错误卡内联渲染挂在事件循环线程上，
Playwright 同步 API 的 Sync-inside-asyncio 守卫必触发 → QQ 主链路（handle_async）
诊断卡图片恒败 + 每卡 ~0.5s 全站 loop 阻塞。

本文件锁定修复语义：
- 渲染不跑在事件循环线程（专用单线程渲染通道，线程名 error-card-render）；
- 文本回执零阻塞（渲染进行中调用即返回，ack 已在队列）；
- 补发成功（图片卡）/失败（全量诊断文本）/后台异常/排程失败（进程退出竞态）
  全链 fail-open；
- 冷却/开关语义零变化；审计标签带 gate:bypass_by_design。

全离线：fake backend + tmp 注入，无 playwright、无网络、无源码树 data/ 写入。
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.runtime import error_report
from plugins.bot_unified_runtime.runtime.error_report import (
    ErrorCardSettings,
    maybe_submit_error_card,
)

_SETTINGS = ErrorCardSettings(enabled=True, cooldown_seconds=60, stack_frames=8)


# ---- 本地小桩（与 test_error_report.py 同构但独立，避免跨测试文件导入脆性） ----
def _message(
    session_id: str = "private:u1",
    session_type: SessionType = SessionType.PRIVATE,
    plain_text: str = "/bot status",
    message_id: str = "m-1",
    **kwargs: Any,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=session_id,
        session_type=session_type,
        sender_id="u1",
        plain_text=plain_text,
        message_id=message_id,
        **kwargs,
    )


def _raise_value_error() -> None:
    raise ValueError("db unavailable at C:/Users/LancyCelestia/secrets")


def _captured_exc() -> ValueError:
    try:
        _raise_value_error()
    except ValueError as exc:
        return exc
    raise AssertionError("unreachable")


class _QueueStub:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def submit(self, send_request: Any) -> None:
        self.requests.append(send_request)


class _PipelineStub:
    def __init__(self) -> None:
        self.send_queue = _QueueStub()


class _ManualGate:
    def __init__(self, answers: list[bool]) -> None:
        self._answers = list(answers)

    def allow(self, session_id: str) -> bool:
        if len(self._answers) > 1:
            return self._answers.pop(0)
        return self._answers[0]


class _FakeBackend:
    def __init__(
        self, png: bytes | None = b"png-bytes", *, delay: float = 0.0
    ) -> None:
        self.png = png
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.thread_name: str = ""
        self.loop_running: bool | None = None

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        self.calls.append(payload)
        self.thread_name = threading.current_thread().name
        try:
            asyncio.get_running_loop()
            self.loop_running = True
        except RuntimeError:
            self.loop_running = False
        if self.delay:
            time.sleep(self.delay)
        return self.png


def _run(pipeline: Any, backend: Any, tmp_path: Path, **kwargs: Any) -> None:
    maybe_submit_error_card(
        pipeline,
        _message(),
        "bot.market",
        _captured_exc(),
        settings=_SETTINGS,
        gate=_ManualGate([True]),
        backend=backend,
        card_dir=str(tmp_path),
        **kwargs,
    )


# ==================== 渲染线程几何（P0 核心） ====================
def test_render_never_runs_on_event_loop_thread(tmp_path: Path) -> None:
    """P0 锁：同一调用几何下，调用线程在 loop 上（生产现状必撞守卫），
    渲染必须发生在无 loop 的专用渲染线程。"""
    backend = _FakeBackend()
    pipeline = _PipelineStub()
    caller_loop_at_submit: bool | None = None

    async def scenario() -> None:
        nonlocal caller_loop_at_submit
        # 生产几何：handle_async 直接 await 在 loop 线程上（QQ 主链路）。
        asyncio.get_running_loop()
        caller_loop_at_submit = True
        _run(pipeline, backend, tmp_path)

    asyncio.run(scenario())
    error_report.flush_pending_card_renders(timeout=10.0)
    assert caller_loop_at_submit is True  # 几何对照：调用线程确在 loop 上
    assert backend.loop_running is False  # 渲染线程上无运行 loop
    assert backend.thread_name.startswith("error-card-render")
    assert backend.thread_name != threading.current_thread().name


# ==================== 文本回执零阻塞 ====================
def test_ack_returns_immediately_while_render_in_flight(tmp_path: Path) -> None:
    backend = _FakeBackend(delay=0.8)  # 模拟 warm 渲染耗时
    pipeline = _PipelineStub()
    started = time.monotonic()
    _run(pipeline, backend, tmp_path)
    elapsed = time.monotonic() - started
    # 调用不等渲染（warm 渲染 ~2s 量级；这里 0.8s 假渲染，必须先返回）。
    assert elapsed < 0.5, f"回执路径被渲染阻塞 {elapsed:.2f}s"
    assert backend.calls == []  # 返回时渲染尚未执行
    # 文本回执已先行入队。
    assert len(pipeline.send_queue.requests) == 1
    ack = pipeline.send_queue.requests[0]
    assert ack.content.content_type == "text"
    assert "随后补发" in ack.content.content_ref["text"]
    error_report.flush_pending_card_renders(timeout=10.0)
    assert len(pipeline.send_queue.requests) == 2  # 渲染完成后卡补发


def test_flush_pending_card_renders_drains(tmp_path: Path) -> None:
    backend = _FakeBackend()
    pipeline = _PipelineStub()
    _run(pipeline, backend, tmp_path)
    error_report.flush_pending_card_renders(timeout=10.0)
    with error_report._PENDING_CARD_LOCK:
        assert error_report._PENDING_CARD_FUTURES == set()


# ==================== 补发成功 / 失败 ====================
def test_card_followup_success_paths_and_ids(tmp_path: Path) -> None:
    backend = _FakeBackend()
    pipeline = _PipelineStub()
    _run(pipeline, backend, tmp_path)
    error_report.flush_pending_card_renders(timeout=10.0)
    ack, card = pipeline.send_queue.requests
    # ack：原 request_id（matcher _find_sent_request 内联首投可寻）+ :ack 去重。
    assert ack.request_id
    assert not ack.request_id.endswith("-card")
    assert ack.dedupe_key.endswith(":ack")
    assert ack.content.content_type == "text"
    # 卡：派生 request_id + :card 去重 + mixed 内容。
    assert card.request_id == f"{ack.request_id}-card"
    assert card.dedupe_key == f"{ack.dedupe_key[:-4]}:card"
    assert card.content.content_type == "mixed"
    parts = card.content.content_ref["parts"]
    assert parts[0]["type"] == "image"
    assert parts[0]["file"].startswith(str(tmp_path))
    assert Path(parts[0]["file"]).is_file()
    assert parts[1]["type"] == "text"
    assert "card" in card.audit_tags
    assert "ack" in ack.audit_tags


def test_render_failure_followup_full_diagnostic_text(tmp_path: Path) -> None:
    backend = _FakeBackend(png=None)
    pipeline = _PipelineStub()
    _run(pipeline, backend, tmp_path)
    error_report.flush_pending_card_renders(timeout=10.0)
    assert len(pipeline.send_queue.requests) == 2
    fallback = pipeline.send_queue.requests[1]
    assert fallback.content.content_type == "text"
    assert fallback.content.content_ref["text"] == fallback.content.text_fallback
    assert "栈摘录" in fallback.content.text_fallback
    assert "IDs 与时间" in fallback.content.text_fallback
    assert "text_only" in fallback.audit_tags


def test_background_render_exception_is_fail_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def exploding_render(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("render exploded on pool thread")

    monkeypatch.setattr(error_report, "render_error_card_png", exploding_render)
    pipeline = _PipelineStub()
    _run(pipeline, _FakeBackend(), tmp_path)
    error_report.flush_pending_card_renders(timeout=10.0)  # 异常不外泄
    # 文本回执已达，卡静默放弃（不补发半吊子内容）。
    assert len(pipeline.send_queue.requests) == 1
    assert pipeline.send_queue.requests[0].dedupe_key.endswith(":ack")


def test_schedule_after_pool_shutdown_is_safe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """进程退出竞态：渲染池已 shutdown 时排程失败只 log，回执路径不变形。"""
    dead_pool = error_report.ThreadPoolExecutor(max_workers=1)
    dead_pool.shutdown(wait=True)
    monkeypatch.setattr(error_report, "_get_render_pool", lambda: dead_pool)
    pipeline = _PipelineStub()
    _run(pipeline, _FakeBackend(), tmp_path)  # 不得抛异常
    assert len(pipeline.send_queue.requests) == 1  # 仅 ack
    assert pipeline.send_queue.requests[0].content.content_type == "text"


# ==================== 冷却 / 开关语义零变化 ====================
def test_cooldown_path_never_touches_render_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def pool_must_not_be_used() -> Any:
        raise AssertionError("冷却路径不得排程渲染")

    monkeypatch.setattr(error_report, "_get_render_pool", pool_must_not_be_used)
    pipeline = _PipelineStub()
    maybe_submit_error_card(
        pipeline,
        _message(),
        "bot.market",
        _captured_exc(),
        settings=_SETTINGS,
        gate=_ManualGate([False]),  # 冷却期内
        backend=_FakeBackend(),
        card_dir=str(tmp_path),
    )
    assert len(pipeline.send_queue.requests) == 1
    degraded = pipeline.send_queue.requests[0]
    assert degraded.content.content_type == "text"
    assert "刚才那张卡" in degraded.content.content_ref["text"]
    assert "text_only" in degraded.audit_tags


def test_disabled_switch_zero_actions_even_async(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def pool_must_not_be_used() -> Any:
        raise AssertionError("开关关不得创建/使用渲染池")

    monkeypatch.setattr(error_report, "_get_render_pool", pool_must_not_be_used)
    pipeline = _PipelineStub()
    maybe_submit_error_card(
        pipeline,
        _message(),
        "bot.market",
        _captured_exc(),
        settings=ErrorCardSettings(
            enabled=False, cooldown_seconds=60, stack_frames=8
        ),
        gate=_ManualGate([True]),
        backend=_FakeBackend(),
        card_dir=str(tmp_path),
    )
    assert pipeline.send_queue.requests == []


# ==================== 审计标签 / 目标路由 ====================
def test_gate_bypass_audit_tag_on_all_paths(tmp_path: Path) -> None:
    pipeline = _PipelineStub()
    _run(pipeline, _FakeBackend(), tmp_path)
    error_report.flush_pending_card_renders(timeout=10.0)
    for request in pipeline.send_queue.requests:
        assert "gate:bypass_by_design" in request.audit_tags
    # 冷却路径同标。
    cooldown_pipeline = _PipelineStub()
    maybe_submit_error_card(
        cooldown_pipeline,
        _message(),
        "bot.market",
        _captured_exc(),
        settings=_SETTINGS,
        gate=_ManualGate([False]),
        backend=_FakeBackend(),
        card_dir=str(tmp_path),
    )
    assert "gate:bypass_by_design" in cooldown_pipeline.send_queue.requests[0].audit_tags


def test_group_session_both_phases_target_group(tmp_path: Path) -> None:
    pipeline = _PipelineStub()
    maybe_submit_error_card(
        pipeline,
        _message("group:g1", SessionType.GROUP, group_id="g1"),
        "bot.market",
        _captured_exc(),
        settings=_SETTINGS,
        gate=_ManualGate([True]),
        backend=_FakeBackend(),
        card_dir=str(tmp_path),
    )
    error_report.flush_pending_card_renders(timeout=10.0)
    assert [r.target_id for r in pipeline.send_queue.requests] == ["g1", "g1"]

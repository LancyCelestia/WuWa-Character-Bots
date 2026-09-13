"""I-1 回归：mermaid 首败重试不得把最坏总工作量顶破外层 20s 预算。

评审 I-1：单次渲染 attempt 最坏 ≈ 14.2s（set_content 上限 8s + wait_js 6s +
余量）。首败后无条件重试会把总工作量顶到 ~28.4s > 外层
``renderer._MERMAID_CALL_TIMEOUT_S = 20s``；且 ``future.result(timeout)``
超时不能取消在跑任务——调用方拿到 None 后，mermaid 专用单 worker 仍被
弃渲染占住至 ~28.5s，断网期后续 mermaid 消息逐条排队 20s 超时、完全无图。

修复：首败已耗时间超过 ``bridge._MERMAID_RETRY_MAX_FIRST_ATTEMPT_S``
（≈ 20s − 单 attempt 最坏 14.2s 的余量）即放弃重试直接 None 降级——重试
只留给「快速失败」（浏览器级故障自愈重建，秒级）场景，最坏总工作量压回
预算量级（≈5.5s + 14.2s ≈ 19.7s）。
"""

from __future__ import annotations

from typing import Any

import pytest

from plugins.bot_unified_runtime.output.card_render import bridge


class _FakeClock:
    def __init__(self) -> None:
        self.now = 100.0


class _StubBackend:
    """记录调用次数的截图后端替身；每次调用推进假时钟模拟耗时。"""

    def __init__(self, results: list[Any], clock: _FakeClock, per_call_s: float) -> None:
        self.results = list(results)
        self.clock = clock
        self.per_call_s = per_call_s
        self.calls = 0

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        self.calls += 1
        self.clock.now += self.per_call_s
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    fake = _FakeClock()
    monkeypatch.setattr(bridge.time, "monotonic", lambda: fake.now)
    return fake


def _install(monkeypatch: pytest.MonkeyPatch, backend: _StubBackend) -> None:
    monkeypatch.setattr(bridge, "_MERMAID_BACKEND", backend)


def test_retry_runs_when_first_attempt_failed_fast(clock: _FakeClock, monkeypatch: pytest.MonkeyPatch) -> None:
    """快速失败（0.5s，预算内）：重试一次并取第二次结果（既有行为保持）。"""
    backend = _StubBackend([None, b"png"], clock, per_call_s=0.5)
    _install(monkeypatch, backend)
    assert bridge.render_mermaid_png("graph TD\nA --> B") == b"png"
    assert backend.calls == 2


def test_retry_runs_at_budget_threshold_boundary(
    clock: _FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """首败恰好耗尽阈值（5.5s）：仍允许重试（<= 判定，最坏总时长 ≈ 预算）。"""
    threshold = bridge._MERMAID_RETRY_MAX_FIRST_ATTEMPT_S
    backend = _StubBackend([None, b"png"], clock, per_call_s=threshold)
    _install(monkeypatch, backend)
    assert bridge.render_mermaid_png("graph TD\nA --> B") == b"png"
    assert backend.calls == 2


def test_retry_skipped_when_first_attempt_burned_budget(
    clock: _FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """首败已耗 14s（>阈值）：放弃重试直接 None，不再放大 worker 占用。"""
    backend = _StubBackend([None, b"png"], clock, per_call_s=14.0)
    _install(monkeypatch, backend)
    assert bridge.render_mermaid_png("graph TD\nA --> B") is None
    # 修复前：无条件重试 → calls == 2（正是评审 I-1 的 28.4s 路径）。
    assert backend.calls == 1


def test_empty_code_short_circuits_without_backend_calls(
    clock: _FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _StubBackend([b"png"], clock, per_call_s=0.0)
    _install(monkeypatch, backend)
    assert bridge.render_mermaid_png("   \n") is None
    assert backend.calls == 0

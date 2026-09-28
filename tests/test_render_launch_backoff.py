"""审查 L-13 回归：launch 退避 sleep 必须在渲染槽位临界区之外执行。

缺陷机理：``PlaywrightRenderBackend._get_browser`` 的 launch 重试循环里
``time.sleep(0.5)`` 在 ``render_card`` 的 ``with self._lock:``（并发槽位）
临界区内执行——浏览器启动瞬时失败（资源紧张常见）时，持槽线程在退避
窗口内纯等待；并发渲染下其它线程被无谓阻塞（max_concurrency=1 时整条
渲染串行冻结 0.5s+/次）。

修复形态：持槽调用方注入 ``_release_slot_backoff``——先释放槽位再睡、
睡完重新取回；无槽位上下文的直接调用（测试等）保持原地 sleep 旧行为。

本文件四组断言：
① 确定性时序：退避窗口内其它线程可完成整次渲染（槽位已让出）；
② 计时：N 路并发全命中退避时总耗时明显小于串行 sleep 总和；
③ 槽位守恒：release/acquire 成对，计数失衡被 BoundedSemaphore 暴露；
④ 退避只发生在两次 attempt 之间（末次失败后无重试可服务，不空睡）。
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace, TracebackType
from typing import Any

import pytest

import plugins.bot_unified_runtime.domains.render.render_backends as render_backends_module
from plugins.bot_unified_runtime.domains.render.render_backends import (
    PlaywrightRenderBackend,
)


class _FakePage:
    """支撑 render_card 截图链路的最小 page 替身（.card 命中 → 元素截图）。"""

    def set_default_timeout(self, ms: int) -> None:
        pass

    def set_content(self, html: str, wait_until: str) -> None:
        assert html

    def wait_for_function(self, js: str, timeout: int) -> None:
        pass

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def query_selector(self, selector: str) -> Any:
        element = SimpleNamespace()
        element.screenshot = lambda **kwargs: b"png-bytes"
        return element

    def close(self) -> None:
        pass


class _FakeBrowser:
    def __init__(self) -> None:
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    def new_page(self, **kwargs: Any) -> _FakePage:
        return _FakePage()

    def close(self) -> None:
        self.connected = False


class _FakeCtx:
    """playwright ctx 替身：start/__exit__ 计数，建模 C-1 的泄漏检测。"""

    def __init__(self, factory: _ScriptedLaunchFactory) -> None:
        self._factory = factory
        self.exit_count = 0

    def start(self) -> Any:
        with self._factory.mutex:
            self._factory.start_count += 1
            self._factory.live.append(self)
        return SimpleNamespace(
            chromium=SimpleNamespace(launch=self._factory.next_launch)
        )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self.exit_count += 1
        with self._factory.mutex:
            self._factory.exit_count += 1
            if self in self._factory.live:
                self._factory.live.remove(self)
        return False


class _ScriptedLaunchFactory:
    """sync_playwright 替身：launch 结果按脚本/按线程首败脚本化。

    - ``global_script``：按全局调用序弹出；Exception 项抛出，其余返回新
      浏览器；耗尽后一律成功。
    - ``fail_first_per_thread``：每线程首次 launch 抛瞬态错误（模拟资源
      紧张时多线程同时撞上启动失败），其后成功。
    """

    def __init__(
        self,
        global_script: list[Any] | None = None,
        *,
        fail_first_per_thread: bool = False,
    ) -> None:
        self.mutex = threading.Lock()
        self._script = list(global_script) if global_script else []
        self.fail_first_per_thread = fail_first_per_thread
        self._per_thread_attempts: dict[int, int] = {}
        self.live: list[_FakeCtx] = []
        self.start_count = 0
        self.exit_count = 0

    def __call__(self) -> _FakeCtx:
        return _FakeCtx(self)

    def next_launch(self) -> _FakeBrowser:
        with self.mutex:
            if self.fail_first_per_thread:
                tid = threading.get_ident()
                attempts = self._per_thread_attempts.get(tid, 0)
                self._per_thread_attempts[tid] = attempts + 1
                if attempts == 0:
                    raise RuntimeError("transient launch failure")
                return _FakeBrowser()
            if self._script:
                item = self._script.pop(0)
                if isinstance(item, Exception):
                    raise item
            return _FakeBrowser()


def _make_backend(monkeypatch: pytest.MonkeyPatch) -> PlaywrightRenderBackend:
    """真实 BoundedSemaphore 槽位的后端（计数失衡当场暴露为 ValueError）。"""
    backend = PlaywrightRenderBackend(max_concurrency=1)
    monkeypatch.setattr(backend, "available", True)
    return backend


_PAYLOAD = {
    "html": "<div class='card'>x</div>",
    "viewport": {"width": 10, "height": 10},
    "wait_ms": 0,
}


def test_backoff_window_releases_slot_and_others_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """① 退避窗口内槽位已让出：另一线程可完成整次渲染（确定性时序）。

    回归形态（旧实现）：失败线程持槽阻塞在 sleep 里 → 非阻塞探测拿不到
    槽位 → 断言失败（不挂起）。修复形态：槽位空出 → 探测成功；主线程
    趁睡眠窗口完成整张卡后，才放失败线程醒来重试。
    """
    real_sleep = time.sleep
    backend = _make_backend(monkeypatch)
    factory = _ScriptedLaunchFactory([RuntimeError("transient")])
    monkeypatch.setattr(backend, "_sync_playwright", factory)

    sleep_started = threading.Event()
    release_event = threading.Event()
    sleep_state = {"entered": False}

    def fake_sleep(seconds: float) -> None:
        if not sleep_state["entered"]:
            # 首次 = 失败线程的退避：停在窗口里，直到主线程放行。
            sleep_state["entered"] = True
            sleep_started.set()
            release_event.wait(10)
            return
        real_sleep(seconds)

    monkeypatch.setattr(render_backends_module.time, "sleep", fake_sleep)

    worker_result: list[bytes | None] = []

    def worker() -> None:
        worker_result.append(backend.render_card(dict(_PAYLOAD)))

    thread_a = threading.Thread(target=worker, name="launch-fail-renderer")
    thread_a.start()
    try:
        assert sleep_started.wait(5), "失败线程未进入退避窗口"
        # 关键断言（L-13）：退避睡眠期间渲染槽位必须已让出。
        deadline = time.monotonic() + 5.0
        slot_free = False
        while time.monotonic() < deadline:
            if backend._lock.acquire(blocking=False):
                slot_free = True
                break
            real_sleep(0.005)
        assert slot_free, "退避窗口内渲染槽位仍被占用（L-13 回归：sleep 在临界区内）"
        backend._lock.release()

        # 主线程趁窗口完成整次渲染（退避中的线程仍被挡住，时序成立）。
        assert backend.render_card(dict(_PAYLOAD)) == b"png-bytes"
        assert thread_a.is_alive(), "放行前失败线程应仍在退避窗口内"
    finally:
        release_event.set()
    thread_a.join(10)
    assert not thread_a.is_alive()
    # 失败线程醒来重试成功，两端都出卡；失败 attempt 的 ctx 已当场退出。
    assert worker_result == [b"png-bytes"]
    assert factory.exit_count == 1
    assert len(factory.live) == 2  # 两个线程各自的常驻实例（C-1：无泄漏残留）


def test_concurrent_backoff_overlaps_not_serialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """② N 路并发全命中退避：总耗时明显小于串行 sleep 总和，全部出卡。

    4 线程 × 注入 0.4s 退避：修复后各线程退避窗口重叠（槽位只在 launch
    本身被占用），总耗时 ≈ 单次退避 + 渲染；旧实现 sleep 持槽串行，
    下界 ≈ 4×0.4s=1.6s。断言阈值 1.2s 两形态均留足裕量、不靠精确计时。
    """
    real_sleep = time.sleep
    injected_backoff = 0.4
    backend = PlaywrightRenderBackend(max_concurrency=1)
    monkeypatch.setattr(backend, "available", True)
    factory = _ScriptedLaunchFactory(fail_first_per_thread=True)
    monkeypatch.setattr(backend, "_sync_playwright", factory)
    monkeypatch.setattr(
        render_backends_module.time,
        "sleep",
        lambda _s: real_sleep(injected_backoff),
    )

    workers = 4
    gate = threading.Barrier(workers + 1)
    results: dict[int, bytes | None] = {}

    def worker(idx: int) -> None:
        gate.wait(10)
        results[idx] = backend.render_card(dict(_PAYLOAD))

    threads = [
        threading.Thread(target=worker, args=(idx,), name=f"render-{idx}")
        for idx in range(workers)
    ]
    for thread in threads:
        thread.start()
    gate.wait(10)
    started = time.monotonic()
    for thread in threads:
        thread.join(15)
    elapsed = time.monotonic() - started

    # 全部成功（每线程首败 + 重试成功）。
    assert len(results) == workers
    assert all(png == b"png-bytes" for png in results.values())
    # 串行总和 = 4×0.4s = 1.6s（旧实现下界）；重叠后应远低于它。
    assert elapsed < workers * injected_backoff * 0.75, (
        f"并发退避未重叠：elapsed={elapsed:.3f}s ≥ 串行总和的 75%"
        f"（{workers * injected_backoff * 0.75:.2f}s），L-13 疑似回归"
    )


def test_release_slot_backoff_conserves_slot_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """③ 槽位守恒：release/acquire 严格成对，退避后槽位回到被持状态。

    BoundedSemaphore(1) 充当失衡探测器：多让少取都会在后续 release 时
    抛 ValueError 让测试失败（并发正确性不回退的直证）。
    """
    backend = _make_backend(monkeypatch)
    monkeypatch.setattr(
        render_backends_module.time, "sleep", lambda _s: None
    )
    lock = backend._lock
    lock.acquire()
    try:
        backend._release_slot_backoff()
        # 退避返回后槽位必须已被重新取回：非阻塞探测拿不到。
        assert not lock.acquire(blocking=False), "退避后槽位未被取回（计数失衡）"
    finally:
        lock.release()


def test_backoff_sleeps_only_between_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """④ 退避只发生在两次 attempt 之间；末次失败后不空睡、错误如实上抛。

    直接调用（无槽位上下文）走缺省原地退避，且绝不触碰并发槽位——
    未 acquire 的 BoundedSemaphore 上 release 会抛 ValueError，本用例
    即为「直接调用路径不碰锁」的守卫。
    """
    backend = _make_backend(monkeypatch)
    factory = _ScriptedLaunchFactory(
        [RuntimeError("boom-1"), RuntimeError("boom-2")]
    )
    monkeypatch.setattr(backend, "_sync_playwright", factory)
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        render_backends_module.time, "sleep", sleep_calls.append
    )

    with pytest.raises(RuntimeError, match="boom-2"):
        backend._get_browser()

    assert sleep_calls == [0.5]  # 旧实现此处为 [0.5, 0.5]（末次空睡）
    assert factory.start_count == 2
    assert factory.exit_count == 2  # C-1：两次失败 attempt 均当场退出 ctx
    assert factory.live == []

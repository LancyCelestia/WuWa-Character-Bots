"""C-1 回归：_get_browser launch 失败重试路径不得泄漏已 start 的 playwright ctx。

评审 C-1（Critical，venv 1.62.0 实测复现）漏毒机理：
``PlaywrightRenderBackend._get_browser`` 的 launch 重试循环里，
``chromium.launch()`` 抛错（传输健康，如可执行文件缺失/资源瞬时紧张）时，
已 ``start()`` 的 PlaywrightContextManager 不会被 ``__exit__``，且线程引用
只在成功后才写入 thread-local → ``_close_thread_browser`` 对泄漏实例不可达。
真实 playwright 中，同线程存在未退出的已 start 实例时，下一次 ``start()``
命中 ``PlaywrightContextManager.__enter__`` 的 running-loop 守卫，报
"It looks like you are using Playwright Sync API inside the asyncio loop"
→ 循环结束向上抛错，该线程此后每次渲染都拿不到浏览器，**至进程重启不可恢复**。

复现步骤（本文件以替身建模同一守卫语义）：首次 launch 失败 + 二次成功 →
修复前第二次 start() 报中毒错误；修复后 launch 异常分支当场 ``__exit__``
清理（幂等，重复退出由 playwright 内部 ``_exit_was_called`` 守卫短路），
同线程重试可正常出浏览器并完成渲染。
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import pytest

import plugins.bot_unified_runtime.output.render_backends as render_backends_module
from plugins.bot_unified_runtime.output.render_backends import PlaywrightRenderBackend

_POISON_MESSAGE = (
    "It looks like you are using Playwright Sync API inside the asyncio loop"
)


class _FakePage:
    """足够支撑 render_card 截图链路的最小 page 替身（无 .card → 全页截图）。"""

    def set_default_timeout(self, ms: int) -> None:
        pass

    def set_content(self, html: str, wait_until: str) -> None:
        pass

    def wait_for_function(self, js: str, timeout: int) -> None:
        pass

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def query_selector(self, sel: str) -> None:
        return None

    def screenshot(self, **kwargs: Any) -> bytes:
        return b"png-bytes"

    def close(self) -> None:
        pass


class _FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    def is_connected(self) -> bool:
        return not self.closed

    def new_page(self, **kwargs: Any) -> _FakePage:
        return _FakePage()

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, launch_results: list[Any]) -> None:
        self._launch_results = launch_results

    def launch(self) -> _FakeBrowser:
        if not self._launch_results:
            raise AssertionError("no more scripted launch results")
        result = self._launch_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium


class _FakeContextManager:
    """start/__exit__ 语义对齐 PlaywrightContextManager 的线程中毒建模。"""

    def __init__(self, factory: _PoisonAwarePlaywrightFactory) -> None:
        self._factory = factory
        self.exit_count = 0

    def start(self) -> _FakePlaywright:
        if self._factory.live:
            # 同线程存在已 start 未退出的实例 → 复现 running-loop 守卫。
            raise RuntimeError(_POISON_MESSAGE)
        self._factory.start_count += 1
        self._factory.live.append(self)
        return _FakePlaywright(_FakeChromium(self._factory.launch_results))

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self.exit_count += 1
        if self in self._factory.live:
            self._factory.live.remove(self)
        return False


class _PoisonAwarePlaywrightFactory:
    """可复现「start 未 exit → 同线程再 start 中毒」的 sync_playwright 替身。"""

    def __init__(self, launch_results: list[Any]) -> None:
        self.launch_results = launch_results
        self.live: list[_FakeContextManager] = []
        self.start_count = 0

    def __call__(self) -> _FakeContextManager:
        return _FakeContextManager(self)


def _make_backend(
    monkeypatch: pytest.MonkeyPatch, factory: _PoisonAwarePlaywrightFactory
) -> PlaywrightRenderBackend:
    backend = PlaywrightRenderBackend(max_concurrency=1)
    monkeypatch.setattr(backend, "_sync_playwright", factory)
    backend.available = True
    # launch 重试间隔（0.5s）不等真时钟。
    monkeypatch.setattr(render_backends_module.time, "sleep", lambda _s: None)
    return backend


def test_launch_failure_exits_started_ctx_no_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两次 launch 全失败：每次 start 的 ctx 都必须当场 __exit__，零泄漏。"""
    factory = _PoisonAwarePlaywrightFactory(
        [RuntimeError("launch boom 1"), RuntimeError("launch boom 2")]
    )
    backend = _make_backend(monkeypatch, factory)
    # 修复前：第二次 start() 命中中毒守卫，抛出的是 Poison 文案而非 launch 错误。
    with pytest.raises(RuntimeError, match="launch boom 2"):
        backend._get_browser()
    assert factory.start_count == 2
    # 关键断言（C-1 泄漏点）：没有已 start 未退出的残留实例。
    assert factory.live == []


def test_launch_retry_second_attempt_succeeds_without_poison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首败 + 二次成功（评审复现步骤）：重试不中毒，成功实例正常常驻。"""
    factory = _PoisonAwarePlaywrightFactory([RuntimeError("transient"), _FakeBrowser()])
    backend = _make_backend(monkeypatch, factory)
    browser = backend._get_browser()
    assert isinstance(browser, _FakeBrowser)
    assert browser.is_connected()
    # 首败实例已退出清理；成功实例经 thread-local 常驻（可被 _close_thread_browser 触达）。
    assert len(factory.live) == 1
    assert backend._local.playwright_ctx is factory.live[0]


def test_launch_failures_leave_thread_recoverable_and_render_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """双失败抛错后，同线程第三次 start 必须可恢复并完成端到端渲染。

    修复前：泄漏的 ctx 让第三次 start() 必报 "Sync API inside the asyncio
    loop"，线程渲染永久 None 至重启；修复后当场清理，线程可救回。
    """
    factory = _PoisonAwarePlaywrightFactory(
        [
            RuntimeError("boom-1"),
            RuntimeError("boom-2"),
            _FakeBrowser(),  # 第二次 _get_browser：重试循环第 1 次 attempt
            _FakeBrowser(),  # render_card 内 _get_browser：last_used 未置 → 重建
        ]
    )
    backend = _make_backend(monkeypatch, factory)
    with pytest.raises(RuntimeError, match="boom-2"):
        backend._get_browser()
    assert factory.live == []
    browser = backend._get_browser()
    assert isinstance(browser, _FakeBrowser)
    png = backend.render_card({"html": "<html><body>ok</body></html>"})
    assert png == b"png-bytes"


def test_close_thread_browser_after_launch_failure_stays_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """launch 失败后走一次自愈关闭：thread-local 保持干净、ctx 全部已退出。"""
    factory = _PoisonAwarePlaywrightFactory(
        [RuntimeError("boom"), RuntimeError("boom")]
    )
    backend = _make_backend(monkeypatch, factory)
    with pytest.raises(RuntimeError, match="boom"):
        backend._get_browser()
    backend._close_thread_browser()
    assert backend._thread_browser() == (None, None)
    assert factory.live == []

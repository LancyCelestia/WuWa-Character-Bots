"""Phase-1 渲染管线框架改造回归（render-pipeline-optimization-spec §2/§3 缺省安全子集）。

三组锁定：
1. wait_ms 预算语义——缺省（不传 ``wait_budget_ms``）行为与旧实现逐字节一致
   （同一 payload 走同一 page 操作序列 + 同参，渲染输入不变即 HTML/PNG 等价）；
   预算模式下就绪信号齐即提前返回、超预算封顶截断（fake 时钟验证）。
2. max_concurrency 激活——默认 1 = 与旧全局锁等价的串行语义；>1 允许至多
   N 张卡跨线程并发（BoundedSemaphore 承担；属性名 ``_lock`` 保留，兼容
   手工装配替身塞入的 threading.Lock——同样支持 with/acquire/release）。
3. 中毒修复面零触碰：本文件不改动 _get_browser/_close_thread_browser 的
   既有语义（C-1 回归门在 test_browser_ctx_leak.py，须与本文件同跑）。
"""

from __future__ import annotations

import os
import queue
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.output.render_backends import (
    _RENDER_READY_SIGNALS,
    PlaywrightRenderBackend,
    _wait_render_budget,
)

_HTML = "<html><body><div class='card'>ok</div></body></html>"
_IMG_COMPLETE_SUBSTRING = "every(img => img.complete)"


# ==================== 替身：记录 render_card 全部 page 级操作 ====================
class _ShotElement:
    def __init__(self, ops: list[tuple[Any, ...]]) -> None:
        self._ops = ops

    def screenshot(self, **kwargs: Any) -> bytes:
        self._ops.append(("element_screenshot", kwargs))
        return b"png-bytes"


class _ScriptedPage:
    """记录 page 级操作序列；wait_for_function 按脚本执行。

    script 每项："ok"（立即就绪）/ ("sleep", 秒)（模拟消耗时长后就绪）/
    ("raise", 秒)（模拟消耗时长后抛 TimeoutError，即预算耗尽形态）。
    """

    def __init__(
        self,
        script: list[Any] | None = None,
        *,
        ops: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.ops = ops if ops is not None else []
        self._script = list(script or [])
        self.closed = False

    def set_default_timeout(self, ms: int) -> None:
        self.ops.append(("set_default_timeout", ms))

    def set_content(self, html: str, wait_until: str = "load") -> None:
        self.ops.append(("set_content", html, wait_until))

    def wait_for_function(self, expression: str, timeout: int = 0) -> None:
        self.ops.append(("wff", expression, timeout))
        action = self._script.pop(0) if self._script else "ok"
        if isinstance(action, tuple) and action[0] == "raise":
            raise TimeoutError(f"fake timeout after {action[1]}s")
        # "ok" 与 ("sleep", s) 都视为信号达成。

    def wait_for_timeout(self, ms: int) -> None:
        self.ops.append(("wait_for_timeout", ms))

    def query_selector(self, selector: str) -> _ShotElement | None:
        self.ops.append(("query_selector", selector))
        if selector == ".card":
            return _ShotElement(self.ops)
        return None

    def screenshot(self, **kwargs: Any) -> bytes:
        self.ops.append(("page_screenshot", kwargs))
        return b"png-bytes"

    def close(self) -> None:
        self.closed = True
        self.ops.append(("close",))


class _SinglePageBrowser:
    def __init__(self, page: _ScriptedPage) -> None:
        self._page = page

    def new_page(self, **kwargs: Any) -> _ScriptedPage:
        self._page.ops.append(("new_page", kwargs))
        return self._page


def _force_available(backend: PlaywrightRenderBackend) -> None:
    """离线兜底：playwright 未安装也把后端置为可用（_get_browser 已被替身替换）。"""
    backend.available = True
    if backend._sync_playwright is None:
        backend._sync_playwright = object()  # 不会被真正调用


def _make_backend(
    page: _ScriptedPage, monkeypatch: pytest.MonkeyPatch, **kwargs: Any
) -> PlaywrightRenderBackend:
    backend = PlaywrightRenderBackend(**kwargs)
    _force_available(backend)
    # 审查 L-13：render_card 以 backoff= 关键字调用 _get_browser，替身
    # 签名跟随（launch 恒成功，退避不触发，忽略参数即可）。
    monkeypatch.setattr(
        backend,
        "_get_browser",
        lambda **kwargs: _SinglePageBrowser(page),
    )
    return backend


# ==================== ① 缺省行为不变（与旧实现同一 page 操作序列） ====================
def test_default_payload_keeps_legacy_wait_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ops: list[tuple[Any, ...]] = []
    page = _ScriptedPage(ops=ops)
    backend = _make_backend(page, monkeypatch)
    payload = {
        "html": _HTML,
        "viewport": {"width": 320, "height": 240},
        "wait_ms": 1234,
    }

    assert backend.render_card(dict(payload)) == b"png-bytes"

    assert ops[:3] == [
        (
            "new_page",
            {"viewport": {"width": 320, "height": 240}, "device_scale_factor": 2},
        ),
        ("set_default_timeout", 8000),
        ("set_content", _HTML, "networkidle"),
    ]
    # 既有 img-complete 等待原样保留（8s 上限）。
    assert ops[3][0] == "wff"
    assert ops[3][2] == 8000
    assert isinstance(ops[3][1], str)
    assert _IMG_COMPLETE_SUBSTRING in ops[3][1]
    # 固定地板原样保留：payload 的 wait_ms 原值透传给 wait_for_timeout。
    assert ops[4] == ("wait_for_timeout", 1234)
    assert ops[5:] == [
        ("query_selector", ".card"),
        ("element_screenshot", {"type": "png", "omit_background": True}),
        ("close",),
    ]
    assert page.closed is True


def test_default_payload_without_wait_ms_uses_1500_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _ScriptedPage()
    backend = _make_backend(page, monkeypatch)

    assert backend.render_card({"html": _HTML}) == b"png-bytes"

    waits = [op for op in page.ops if op[0] == "wait_for_timeout"]
    assert waits == [("wait_for_timeout", 1500)]


# ==================== ① 预算模式：固定 sleep → 预算上限 ====================
def test_wait_budget_mode_replaces_fixed_sleep_with_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _ScriptedPage()
    backend = _make_backend(page, monkeypatch)
    payload = {"html": _HTML, "wait_ms": 1500, "wait_budget_ms": 2000}

    assert backend.render_card(payload) == b"png-bytes"

    wff_ops = [op for op in page.ops if op[0] == "wff"]
    # img-complete（既有等待）之后依次是 3 个预算就绪信号，预算内全额可用。
    assert [op[1] for op in wff_ops[1:]] == list(_RENDER_READY_SIGNALS)
    assert all(op[2] == 2000 for op in wff_ops[1:])
    # 预算模式下不再发生固定 sleep（wait_ms=1500 被预算语义取代）。
    assert all(op[0] != "wait_for_timeout" for op in page.ops)


def test_wait_budget_invalid_values_fall_back_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for bad in ("abc", -5, None, object()):
        page = _ScriptedPage()
        backend = _make_backend(page, monkeypatch)
        result = backend.render_card({"html": _HTML, "wait_budget_ms": bad})
        assert result == b"png-bytes"
        waits = [op for op in page.ops if op[0] == "wait_for_timeout"]
        assert waits == [("wait_for_timeout", 1500)], f"budget={bad!r} 应回落旧路径"


def test_wait_budget_keeps_wait_js_failure_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _ScriptedPage(["ok", ("raise", 0.0)])
    backend = _make_backend(page, monkeypatch)
    payload = {"html": _HTML, "wait_js": "() => false", "wait_budget_ms": 1000}

    assert backend.render_card(payload) is None  # wait_js 未达成 → 降级，不抛异常

    op_names = [op[0] for op in page.ops]
    assert "query_selector" not in op_names
    assert op_names[-1] == "close"
    assert all(op[0] != "wait_for_timeout" for op in page.ops)


# ==================== ① 预算等待核心（fake 时钟：提前返回 / 封顶截断） ====================
class _FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.consumed = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
        self.consumed += seconds


class _SignalPage:
    """wait_for_function 替身：默认信号即就绪；behaviors 按调用序消费。"""

    def __init__(self, clock: _FakeClock, behaviors: list[Any] | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self._clock = clock
        self._behaviors = list(behaviors or [])

    def wait_for_function(self, expression: str, timeout: int = 0) -> None:
        self.calls.append((expression, timeout))
        action = self._behaviors.pop(0) if self._behaviors else "ready"
        if action == "ready":
            return
        kind, seconds = action
        self._clock.advance(seconds)
        if kind == "timeout":
            raise TimeoutError(f"fake timeout after {seconds}s")


def test_budget_signals_all_ready_return_before_budget() -> None:
    clock = _FakeClock()
    page = _SignalPage(clock)

    _wait_render_budget(page, 5000, clock=clock)

    assert page.calls == [(js, 5000) for js in _RENDER_READY_SIGNALS]
    # 信号齐：未耗任何预算即提前返回（提前返回路径）。
    assert clock.consumed == 0.0


def test_budget_partial_ready_returns_early_with_remaining_budget() -> None:
    clock = _FakeClock()
    page = _SignalPage(clock, behaviors=[("wait", 1.2)])

    _wait_render_budget(page, 5000, clock=clock)

    # 信号①耗 1.2s 达成后，后续信号用剩余预算且立即达成 → 总耗时 < 预算。
    assert page.calls == [
        (_RENDER_READY_SIGNALS[0], 5000),
        (_RENDER_READY_SIGNALS[1], 3800),
        (_RENDER_READY_SIGNALS[2], 3800),
    ]
    assert clock.consumed == pytest.approx(1.2)
    assert clock.consumed < 5.0


def test_budget_truncates_at_cap_when_signals_never_ready() -> None:
    clock = _FakeClock()
    page = _SignalPage(clock, behaviors=[("wait", 2.0), ("timeout", 3.0)])

    _wait_render_budget(page, 5000, clock=clock)

    # 信号②超时耗尽预算 → 不再等待信号③，总耗时恰好 = 预算（封顶截断）。
    assert page.calls == [
        (_RENDER_READY_SIGNALS[0], 5000),
        (_RENDER_READY_SIGNALS[1], 3000),
    ]
    assert clock.consumed == pytest.approx(5.0)


def test_budget_zero_skips_all_signals() -> None:
    clock = _FakeClock()
    page = _SignalPage(clock)

    _wait_render_budget(page, 0, clock=clock)

    assert page.calls == []
    assert clock.consumed == 0.0


# ==================== ② max_concurrency 激活（并发槽计数） ====================
class _GatePage:
    """在 set_content 处阻塞的页面替身：由主线程经事件放行，统计并发度。"""

    def __init__(
        self,
        active: dict[str, int],
        entered: queue.Queue[int],
        releases: queue.Queue[int],
        hold: float = 0.0,
    ) -> None:
        self._active = active
        self._entered = entered
        self._releases = releases
        self._hold = hold

    def set_default_timeout(self, ms: int) -> None:
        pass

    def set_content(self, html: str, wait_until: str = "load") -> None:
        self._active["now"] += 1
        self._active["max"] = max(self._active["max"], self._active["now"])
        self._entered.put(threading.get_ident())
        if self._hold:
            time.sleep(self._hold)
        self._releases.get(timeout=10)
        self._active["now"] -= 1

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def query_selector(self, selector: str) -> Any:
        if selector == ".card":
            element = SimpleNamespace()
            element.screenshot = lambda **kwargs: b"png-bytes"
            return element
        return None

    def close(self) -> None:
        pass


class _GateBrowser:
    def __init__(self, maker: Any) -> None:
        self._maker = maker

    def new_page(self, **kwargs: Any) -> Any:
        return self._maker()


def _make_gate_backend(
    monkeypatch: pytest.MonkeyPatch,
    active: dict[str, int],
    entered: queue.Queue[int],
    releases: queue.Queue[int],
    **kwargs: Any,
) -> PlaywrightRenderBackend:
    backend = PlaywrightRenderBackend(**kwargs)
    _force_available(backend)
    monkeypatch.setattr(
        backend,
        "_get_browser",
        # 审查 L-13：签名跟随 backoff= 关键字调用（门控浏览器恒成功）。
        lambda **kwargs: _GateBrowser(lambda: _GatePage(active, entered, releases)),
    )
    return backend


def test_default_init_pins_serial_bounded_semaphore() -> None:
    backend = PlaywrightRenderBackend()

    assert backend._max_concurrency == 1  # 默认 1 = 串行语义（规格 §3.3）
    assert backend._lock.acquire(blocking=False) is True
    try:
        # 唯一槽已被占用：第二个非阻塞获取必须失败（互斥语义）。
        assert backend._lock.acquire(blocking=False) is False
    finally:
        backend._lock.release()
    # BoundedSemaphore：过释放必须暴露（区别于普通 Semaphore）。
    with pytest.raises(ValueError):
        backend._lock.release()


def test_default_concurrency_is_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    active = {"now": 0, "max": 0}
    entered: queue.Queue[int] = queue.Queue()
    releases: queue.Queue[int] = queue.Queue()
    backend = _make_gate_backend(monkeypatch, active, entered, releases)
    payload = {"html": _HTML, "wait_ms": 0}
    results: list[bytes | None] = []

    def _render() -> None:
        results.append(backend.render_card(dict(payload)))

    first = threading.Thread(target=_render, daemon=True)
    first.start()
    ident1 = entered.get(timeout=10)
    second = threading.Thread(target=_render, daemon=True)
    second.start()
    time.sleep(0.2)
    # 默认并发 1：第二张卡必须被槽挡住，不得与第一张重叠。
    assert active == {"now": 1, "max": 1}
    releases.put(ident1)
    ident2 = entered.get(timeout=10)  # 第一张退出后第二张才被放行 → 严格串行
    assert active["max"] == 1
    releases.put(ident2)
    first.join(10)
    second.join(10)
    assert not first.is_alive() and not second.is_alive()
    assert results == [b"png-bytes", b"png-bytes"]
    assert active == {"now": 0, "max": 1}


def test_max_concurrency_two_admits_parallel_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = {"now": 0, "max": 0}
    entered: queue.Queue[int] = queue.Queue()
    releases: queue.Queue[int] = queue.Queue()
    backend = _make_gate_backend(monkeypatch, active, entered, releases, max_concurrency=2)
    payload = {"html": _HTML, "wait_ms": 0}
    results: list[bytes | None] = []

    def _render() -> None:
        results.append(backend.render_card(dict(payload)))

    first = threading.Thread(target=_render, daemon=True)
    first.start()
    ident1 = entered.get(timeout=10)
    second = threading.Thread(target=_render, daemon=True)
    second.start()
    # 槽=2：无需放行第一张，第二张即可入场 → 真并发（不触发同线程双实例）。
    ident2 = entered.get(timeout=10)
    assert active["max"] == 2
    releases.put(ident1)
    releases.put(ident2)
    first.join(10)
    second.join(10)
    assert not first.is_alive() and not second.is_alive()
    assert results == [b"png-bytes", b"png-bytes"]
    assert active == {"now": 0, "max": 2}


def test_max_concurrency_bound_never_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    active = {"now": 0, "max": 0}
    entered: queue.Queue[int] = queue.Queue()
    releases: queue.Queue[int] = queue.Queue()
    backend = _make_gate_backend(
        monkeypatch, active, entered, releases, max_concurrency=2
    )
    payload = {"html": _HTML, "wait_ms": 0}
    results: list[bytes | None] = []
    start_barrier = threading.Barrier(7)

    def _render() -> None:
        start_barrier.wait(10)
        results.append(backend.render_card(dict(payload)))

    threads = [threading.Thread(target=_render, daemon=True) for _ in range(6)]
    for thread in threads:
        thread.start()
    start_barrier.wait(10)
    # 放行泵：每张卡入场后立即放行（hold 提供重叠窗口），保证全部正常完成。
    def _pump() -> None:
        for _ in range(6):
            releases.put(entered.get(timeout=30))

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()
    for thread in threads:
        thread.join(30)
    pump.join(30)
    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 6
    assert all(result == b"png-bytes" for result in results)
    # 硬上界：并发渲染数不得超过槽数。
    assert active["max"] <= 2
    assert active["now"] == 0


# ==================== ③ 真实浏览器缺省等价烟测（默认跳过，与 repo 门控先例一致） ====================
def test_real_browser_default_payload_renders_equivalently() -> None:
    """同 payload 两次渲染 PNG 等价（缺省路径零行为变化的端到端证据）。

    门控先例与 test_mermaid_reply_render 的 BOT_MERMAID_NET_TESTS 一致：
    默认跳过；设 BOT_RENDER_NET_TESTS=1 才跑（需本机 playwright+chromium）。
    """
    if os.environ.get("BOT_RENDER_NET_TESTS", "") != "1":
        pytest.skip("真实浏览器等价烟测默认跳过（BOT_RENDER_NET_TESTS=1 启用）")
    backend = PlaywrightRenderBackend()
    if not backend.available:
        pytest.skip("playwright 未安装")
    payload = {
        "html": (
            "<html><body><div class='card' style='padding:16px'>"
            "<h2>守岸人</h2><p>缺省等价烟测</p></div></body></html>"
        ),
        "viewport": {"width": 360, "height": 240},
        "device_scale_factor": 1,
        "wait_ms": 100,
    }
    try:
        png_a = backend.render_card(dict(payload))
        png_b = backend.render_card(dict(payload))
    finally:
        backend.close()
    assert png_a is not None and png_b is not None
    assert png_a == png_b

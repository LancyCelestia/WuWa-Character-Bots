"""审查 L-12：错误卡渲染池与 renderer(mermaid) 池的 atexit 回收回归锁。

两个专用 ThreadPoolExecutor 的 worker 均为非守护线程——退出路径必须经
atexit 钩子显式 shutdown(wait=True, cancel_futures=False)：排队任务跑完
再收线程（解释器本就会隐式 join 非守护 worker，显式回收只是把时序摆上
台面），且注册必须幂等（shutdown 后重建池不堆积重复注册）。

全离线：纯线程语义，无 playwright、无网络、无源码树 data/ 写入。
"""

from __future__ import annotations

import atexit
import threading
import time
from collections.abc import Callable

import pytest

from plugins.bot_unified_runtime.output import renderer
from plugins.bot_unified_runtime.runtime import error_report


def _capture_atexit_register(
    monkeypatch: pytest.MonkeyPatch,
) -> list[Callable[[], None]]:
    """把 atexit.register 换成只记录不生效的桩（不污染真实退出注册表）。"""
    recorded: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", recorded.append)
    return recorded


def _queued_marker(done: threading.Event) -> None:
    """排队任务：短暂延迟后置位（模拟一次在途渲染）。"""
    time.sleep(0.2)
    done.set()


# ==================== 错误卡渲染池（runtime/error_report.py） ====================
def test_error_render_pool_registers_atexit_hook_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _capture_atexit_register(monkeypatch)
    monkeypatch.setattr(error_report, "_RENDER_POOL", None)
    monkeypatch.setattr(error_report, "_RENDER_POOL_ATEXIT_REGISTERED", False)

    pool = error_report._get_render_pool()
    try:
        # 钩子在册且只注册一次（幂等：池已存在时再取不得重复注册）。
        assert recorded == [error_report._shutdown_render_pool]
        assert error_report._get_render_pool() is pool
        assert recorded == [error_report._shutdown_render_pool]
        assert pool.submit(int).result() == 0  # 池本身可用
    finally:
        pool.shutdown(wait=True)


def test_error_render_pool_shutdown_waits_for_queued_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _capture_atexit_register(monkeypatch)
    monkeypatch.setattr(error_report, "_RENDER_POOL", None)
    monkeypatch.setattr(error_report, "_RENDER_POOL_ATEXIT_REGISTERED", False)

    pool = error_report._get_render_pool()
    done = threading.Event()
    pool.submit(_queued_marker, done)
    error_report._shutdown_render_pool()
    # wait=True：钩子返回前排队任务必已跑完；且钩子全程只注册一次。
    assert done.is_set()
    assert recorded == [error_report._shutdown_render_pool]
    # 池已关闭：submit 抛 RuntimeError（既有语义不变，排程路径依赖它兜底）。
    with pytest.raises(RuntimeError):
        pool.submit(int)


# ==================== mermaid 渲染池（output/renderer.py） ====================
def test_mermaid_executor_registers_atexit_hook_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _capture_atexit_register(monkeypatch)
    monkeypatch.setattr(renderer, "_mermaid_executor", None)
    monkeypatch.setattr(renderer, "_mermaid_shutdown_hook_registered", False)

    pool = renderer._get_mermaid_executor()
    try:
        # 钩子在册且只注册一次（幂等：池已存在时再取不得重复注册）。
        assert recorded == [renderer._shutdown_mermaid_executor]
        assert renderer._get_mermaid_executor() is pool
        assert recorded == [renderer._shutdown_mermaid_executor]
        assert pool.submit(int).result() == 0  # 池本身可用
    finally:
        pool.shutdown(wait=True)


def test_mermaid_executor_shutdown_waits_and_recreate_stays_covered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _capture_atexit_register(monkeypatch)
    monkeypatch.setattr(renderer, "_mermaid_executor", None)
    monkeypatch.setattr(renderer, "_mermaid_shutdown_hook_registered", False)

    pool = renderer._get_mermaid_executor()
    done = threading.Event()
    pool.submit(_queued_marker, done)
    renderer._shutdown_mermaid_executor()
    renderer._shutdown_mermaid_executor()  # 二次调用必须安全 no-op
    # wait=True：钩子返回前排队任务必已跑完。
    assert done.is_set()
    # 池已关闭：submit 抛 RuntimeError（既有语义不变）。
    with pytest.raises(RuntimeError):
        pool.submit(int)
    # shutdown 后重建池照常可用，且不产生第二次注册（一次注册覆盖所有实例）。
    fresh = renderer._get_mermaid_executor()
    try:
        assert fresh is not pool
        assert fresh.submit(int).result() == 0
        assert recorded == [renderer._shutdown_mermaid_executor]
    finally:
        fresh.shutdown(wait=True)


def test_shutdown_hooks_noop_when_pool_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """池从未创建时（atexit 在极端路径也会触发钩子）两者必须安全 no-op。"""
    monkeypatch.setattr(error_report, "_RENDER_POOL", None)
    monkeypatch.setattr(renderer, "_mermaid_executor", None)
    error_report._shutdown_render_pool()  # 不得抛异常
    renderer._shutdown_mermaid_executor()
    assert error_report._RENDER_POOL is None
    assert renderer._mermaid_executor is None

"""错误卡渲染池的跨模块卫生锁（2026-09-18 REAPER 清障席）。

背景（根 task_plan.md「复现定位」①）：``error_report._RENDER_POOL`` 是模块级
常驻单例（非 daemon worker，仅 atexit 收口）。测试期若无收口，前置模块
（如 ``tests/test_error_card_async.py`` 一类用例）拉起的 ``error-card-render_0``
线程会存活到后续任意模块，使对线程面敏感的用例（停机 reaper 扫描等）
随**用例执行顺序**飘——单独跑绿、全量/组合跑红。

tests/conftest.py 的 ``_quarantine_render_pool_between_modules``（模块边界
teardown 调 ``error_report._shutdown_render_pool()``）是根修；本文件锁其语义：

1. ``test_global_render_pool_absent_at_module_start``——哨兵：无论同会话
   前序模块拉起过多少池，本模块开始时全局必须已清。红条件＝conftest
   收口缺失（复现命令见下）；单文件跑是恒绿快照。
2. 幂等/重建语义——``_shutdown_render_pool`` 重复调用不炸、worker 线程
   真终止、shutdown 后池可懒重建（后续用例零感知）。

2026-09-18 CAPEXEC 收口席追加（REAPER 残余登记）：同款锁法覆盖
``capability_protocols._EXECUTOR``（``cap-proto`` 池，见文件尾两用例）——
conftest 同一模块边界 fixture 内补调 ``_shutdown_capability_executor()``。

组合复现（修复前 1 failed）::

    pytest tests/test_error_card_async.py tests/test_render_pool_hygiene.py

全离线：纯线程语义，无 playwright、无网络、无源码树 data/ 写入。
"""

from __future__ import annotations

import threading

from plugins.bot_unified_runtime.domains.ops.monitor import error_report
from plugins.bot_unified_runtime.runtime import capability_protocols


def test_global_render_pool_absent_at_module_start() -> None:
    """哨兵：模块边界处渲染池必须已被 conftest 收口（为 None）。

    本断言只在「同会话前序模块遗留了活池」时红——即 conftest 模块边界
    teardown 缺失/失效的情形（完整复现：与 test_error_card_async.py 同跑）。
    """
    assert error_report._RENDER_POOL is None, (
        "前序模块遗留了存活的 error_report._RENDER_POOL（error-card-render "
        "worker 未在模块边界收口）：tests/conftest.py 的 "
        "_quarantine_render_pool_between_modules 是否被移除/改名？"
    )


def test_shutdown_render_pool_is_idempotent_and_rebuildable() -> None:
    """收口钩子幂等（重复调用不炸）、worker 真终止、池可懒重建。

    conftest 在模块边界反复调用本钩子：必须保证「调用两次」与
    「shutdown 后下一模块再 _get_render_pool()」都语义无损。
    """
    pool = error_report._get_render_pool()
    assert pool.submit(int).result() == 0  # 派生 worker 线程
    worker_names_before = {
        t.name for t in threading.enumerate() if t.name.startswith("error-card-render")
    }
    assert worker_names_before, "池 worker 未按预期派生（前置假设破裂）"

    error_report._shutdown_render_pool()
    error_report._shutdown_render_pool()  # 幂等：二次调用必须无异常

    assert error_report._RENDER_POOL is None
    alive = {
        t.name for t in threading.enumerate() if t.name.startswith("error-card-render")
    }
    assert not alive, f"shutdown(wait=True) 返回后 worker 仍存活：{alive}"

    # 懒重建：后续模块/用例零感知（线程名同前缀、提交可用）。
    rebuilt = error_report._get_render_pool()
    try:
        assert rebuilt is not pool
        assert rebuilt.submit(int).result() == 0
    finally:
        error_report._shutdown_render_pool()
    assert error_report._RENDER_POOL is None


# ---------------------------------------------------------------------------
# cap-proto 执行器面（2026-09-18 CAPEXEC 收口席，REAPER 残余登记同款锁法）
# ---------------------------------------------------------------------------
# ``capability_protocols._EXECUTOR``（``cap-proto_0/1``）同为模块级常驻池（非
# daemon worker、懒创建、仅 atexit 收口），由 tests/test_v21_s10_protocols.py
# 经 ``CapabilityInvoker.invoke`` 拉起。生产收口钩子
# ``_shutdown_capability_executor`` 已存在（幂等、锁内换出、wait=True、
# cancel_futures=False、懒重建）；本文件锁 conftest 模块边界对其的调用语义。
# 组合复现（conftest 缺该调用时哨兵红）::
#
#     pytest tests/test_v21_s10_protocols.py tests/test_render_pool_hygiene.py


def test_capability_executor_absent_at_module_start() -> None:
    """哨兵：模块边界处 cap-proto 执行器必须已被 conftest 收口（为 None）。

    红条件＝同会话前序模块（如 test_v21_s10_protocols）遗留了存活
    ``_EXECUTOR`` 及 ``cap-proto_*`` worker（conftest 模块边界调用缺失/失效）；
    单文件跑是恒绿快照。
    """
    assert capability_protocols._EXECUTOR is None, (
        "前序模块遗留了存活的 capability_protocols._EXECUTOR（cap-proto worker "
        "未在模块边界收口）：tests/conftest.py 的 "
        "_quarantine_render_pool_between_modules 是否被移除/改名/漏调？"
    )
    alive = {
        t.name for t in threading.enumerate() if t.name.startswith("cap-proto")
    }
    assert not alive, f"模块边界后 cap-proto worker 仍存活：{alive}"


def test_shutdown_capability_executor_is_idempotent_and_rebuildable() -> None:
    """收口钩子幂等（重复调用不炸）、worker 真终止、池可懒重建。"""
    pool = capability_protocols._get_capability_executor()
    assert pool.submit(int).result() == 0  # 派生 worker 线程
    worker_names_before = {
        t.name for t in threading.enumerate() if t.name.startswith("cap-proto")
    }
    assert worker_names_before, "池 worker 未按预期派生（前置假设破裂）"

    capability_protocols._shutdown_capability_executor()
    capability_protocols._shutdown_capability_executor()  # 幂等：二次调用必须无异常

    assert capability_protocols._EXECUTOR is None
    alive = {
        t.name for t in threading.enumerate() if t.name.startswith("cap-proto")
    }
    assert not alive, f"shutdown(wait=True) 返回后 worker 仍存活：{alive}"

    # 懒重建：后续模块/用例零感知（atexit 仅一次注册的旗标语义不受影响）。
    rebuilt = capability_protocols._get_capability_executor()
    try:
        assert rebuilt is not pool
        assert rebuilt.submit(int).result() == 0
    finally:
        capability_protocols._shutdown_capability_executor()
    assert capability_protocols._EXECUTOR is None

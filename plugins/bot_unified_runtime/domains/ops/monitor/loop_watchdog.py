"""事件循环看门狗（轻量观测，2026-09-17 R3 停摆批）。

背景：kb_wiki 全量灌库/检索锁内全表载入等重活曾造成「消息进来但 LLM
请求发不出、控制台无任何报错」的静默停摆（实弹：22:25 axonhub 最新请求
停在半小时前）。本模块**只观测不自愈**（绝不杀任务、绝不重启、绝不改
状态），给两类低频信号：

- **事件循环心跳滞后**：每 ``interval`` 秒一次心跳，实际间隔超出
  ``interval + lag_threshold`` 记 warning（带滞后秒数）——loop 被同步
  阻塞（长 CPU 活/同步 IO/大分配）时唯一稳定的信号，WS 层面看不出来。
- **聊天管线池饱和**：探测 pipeline 专用池提交闸（在途/许可，见
  pipeline._BoundedSubmissionGate），满载记 warning（带在途/许可数）
  ——「吞消息」（pipeline_busy 静默快败，SILENT_AUDIT 不外发）的直接前兆；
  池满载说明能力在长任务上堆积（LLM 慢/检索慢/渲染慢）。

克制原则：两类告警各有独立冷却窗（默认 60s/300s），阈值触发才记一行，
不打点、不逐报、零阻塞（单协程 sleep 驱动；探测 O(1) 取计数器）。

挂接坐标（__init__.py 属 R5 域，本席不改，留给 R5 代挂）::

    from .domains.ops.monitor.loop_watchdog import start_loop_watchdog

    # 在 driver on_startup（loop 存在之后）：
    start_loop_watchdog()
    # 优雅停机（可选；不挂也能随 loop 销毁自然结束）：
    from .domains.ops.monitor.loop_watchdog import stop_loop_watchdog
    stop_loop_watchdog()
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 5.0
# 心跳实际间隔超出 interval + 该阈值 → 记滞后 warning。
DEFAULT_LAG_WARN_THRESHOLD_SECONDS = 3.0
# 同类滞后告警最小间隔（抑制窗）：持续阻塞只报首条 + 每 60s 提醒一次。
DEFAULT_LAG_WARN_COOLDOWN_SECONDS = 60.0
# 池饱和告警最小间隔（抑制窗）。
DEFAULT_POOL_SATURATED_COOLDOWN_SECONDS = 300.0


def _default_pool_probe() -> tuple[int, int]:
    """聊天管线池提交闸探测：返回 (在途[运行+排队], 许可数)。

    惰性导入 pipeline（同包，无装配环）；探测失败返回 (-1, -1)＝未知，
    调用方按探测失效处理（记一次 debug 后停用池观测，不反复重试刷日志）。
    """
    from plugins.bot_unified_runtime.runtime.pipeline import _get_chat_pool

    _pool, gate = _get_chat_pool()
    return gate.in_flight, gate.permits


class LoopWatchdog:
    """单协程看门狗：心跳滞后 + 聊天管线池饱和观测（阈值 + 冷却抑制）。

    ``monotonic``/``sleep``/``pool_probe`` 均可注入（测试全离线确定性，
    无真实等待、无真实网络、无真实线程池依赖）。
    """

    def __init__(
        self,
        *,
        interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        lag_threshold: float = DEFAULT_LAG_WARN_THRESHOLD_SECONDS,
        lag_cooldown: float = DEFAULT_LAG_WARN_COOLDOWN_SECONDS,
        pool_cooldown: float = DEFAULT_POOL_SATURATED_COOLDOWN_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Coroutine[Any, Any, None]] | None = None,
        pool_probe: Callable[[], tuple[int, int]] | None = None,
    ) -> None:
        self._interval = max(0.1, float(interval))
        self._lag_threshold = max(0.0, float(lag_threshold))
        self._lag_cooldown = max(0.0, float(lag_cooldown))
        self._pool_cooldown = max(0.0, float(pool_cooldown))
        self._monotonic = monotonic
        self._sleep = sleep or asyncio.sleep
        self._pool_probe = pool_probe or _default_pool_probe
        self._pool_probe_failed = False
        self._task: asyncio.Task | None = None
        self._last_lag_warn_at = float("-inf")
        self._last_pool_warn_at = float("-inf")

    # -- 观测 -----------------------------------------------------------------

    async def beat(self) -> None:
        """跳一次心跳：sleep(interval) → 测滞后 → 测池饱和（各自带抑制）。"""
        started_at = self._monotonic()
        await self._sleep(self._interval)
        now = self._monotonic()
        lag = now - started_at - self._interval
        if lag >= self._lag_threshold and now - self._last_lag_warn_at >= (
            self._lag_cooldown
        ):
            self._last_lag_warn_at = now
            logger.warning(
                "loop-watchdog: 事件循环心跳滞后 %.2fs（beat 间隔 %.2fs，阈值 %.1fs）"
                "——loop 疑似被同步阻塞（长 CPU/同步 IO/大分配）",
                lag,
                now - started_at,
                self._lag_threshold,
            )
        self._check_pool(now)

    def _check_pool(self, now: float) -> None:
        if self._pool_probe_failed:
            return
        try:
            in_flight, permits = self._pool_probe()
        except Exception:
            self._pool_probe_failed = True
            logger.debug(
                "loop-watchdog: 聊天管线池探测不可用，停用池饱和观测", exc_info=True
            )
            return
        if permits <= 0 or in_flight < permits:
            return
        if now - self._last_pool_warn_at < self._pool_cooldown:
            return
        self._last_pool_warn_at = now
        logger.warning(
            "loop-watchdog: 聊天管线池满载 in_flight=%d/%d（运行+排队）"
            "——新消息将 pipeline_busy 静默快败（吞消息前兆），"
            "排查长任务能力（LLM/检索/渲染）",
            in_flight,
            permits,
        )

    # -- 生命周期 -------------------------------------------------------------

    async def run(self, *, max_beats: int | None = None) -> None:
        """跑看门狗循环；max_beats 供测试/脚本限定心跳次数。"""
        beats = 0
        while max_beats is None or beats < max_beats:
            await self.beat()
            beats += 1

    def start(self) -> asyncio.Task:
        """在当前运行中的事件循环上启动看门狗任务（幂等）。"""
        if self._task is not None and not self._task.done():
            return self._task
        self._task = asyncio.get_running_loop().create_task(
            self.run(), name="loop-watchdog"
        )
        return self._task

    def stop(self) -> None:
        """取消看门狗任务（幂等；未启动为空操作）。"""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None


_SHARED_WATCHDOG: LoopWatchdog | None = None


def start_loop_watchdog(**overrides: Any) -> LoopWatchdog:
    """启动（或复用）进程级共享看门狗；参数仅首次创建时生效。"""
    global _SHARED_WATCHDOG
    shared = _SHARED_WATCHDOG
    if shared is not None:
        task = shared._task
        if task is not None and not task.done():
            return shared
        shared.start()
        return shared
    shared = LoopWatchdog(**overrides)
    shared.start()
    _SHARED_WATCHDOG = shared
    return shared


def stop_loop_watchdog() -> None:
    """停掉共享看门狗（优雅停机可选挂点；未启动为空操作）。"""
    global _SHARED_WATCHDOG
    if _SHARED_WATCHDOG is not None:
        _SHARED_WATCHDOG.stop()
    _SHARED_WATCHDOG = None


def reset_shared_for_tests() -> None:
    """测试专用：清空共享实例（不取消任务——由用例自行管理）。"""
    global _SHARED_WATCHDOG
    _SHARED_WATCHDOG = None


__all__ = [
    "DEFAULT_HEARTBEAT_INTERVAL_SECONDS",
    "DEFAULT_LAG_WARN_COOLDOWN_SECONDS",
    "DEFAULT_LAG_WARN_THRESHOLD_SECONDS",
    "DEFAULT_POOL_SATURATED_COOLDOWN_SECONDS",
    "LoopWatchdog",
    "reset_shared_for_tests",
    "start_loop_watchdog",
    "stop_loop_watchdog",
]

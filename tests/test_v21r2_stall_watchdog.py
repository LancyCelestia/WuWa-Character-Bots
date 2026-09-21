"""R3 停摆批：事件循环看门狗回归（全离线，假钟驱动，零真实等待）。

覆盖项：
- 心跳滞后触发（实际间隔超 interval+阈值 → warning 带滞后秒数）；
- 抑制窗（冷却期内同类告警不重复；过冷却后再报）；
- 无滞后零告警；
- 聊天管线池饱和触发/抑制/恢复正常不再告警/探测失效降级停用；
- max_beats 有限心跳与 start/stop 生命周期。
"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from plugins.bot_unified_runtime.runtime import loop_watchdog
from plugins.bot_unified_runtime.runtime.loop_watchdog import LoopWatchdog

LOGGER_NAME = "plugins.bot_unified_runtime.runtime.loop_watchdog"


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


def fake_sleep(clock: FakeClock, extra: float = 0.0):
    """假 sleep：前进 seconds+extra——extra 即模拟的每拍事件循环滞后。"""

    async def _sleep(seconds: float) -> None:
        clock.advance(seconds + extra)

    return _sleep


def make_watchdog(clock: FakeClock, **kwargs) -> LoopWatchdog:
    kwargs.setdefault("sleep", fake_sleep(clock))
    kwargs.setdefault("monotonic", clock)
    kwargs.setdefault("pool_probe", lambda: (0, 8))
    return LoopWatchdog(**kwargs)


# ---------------------------------------------------------------- 心跳滞后


@pytest.mark.asyncio
async def test_lag_warning_triggers_and_cooldown_suppresses(caplog) -> None:
    clock = FakeClock()
    # interval=5，每拍实际走 5+4=9s → 滞后 4s > 阈值 3s。
    watchdog = make_watchdog(
        clock,
        interval=5.0,
        lag_threshold=3.0,
        lag_cooldown=60.0,
        sleep=fake_sleep(clock, extra=4.0),
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        for _ in range(2):
            await watchdog.beat()
        # 冷却 60s 内：第二拍 now 与首警时刻只差 9s，必须被抑制。
        lag_warnings = [
            record for record in caplog.records if "心跳滞后" in record.message
        ]
        assert len(lag_warnings) == 1
        assert "4.00s" in lag_warnings[0].message
        for _ in range(7):  # 每拍 9s，第 7 拍后 now 距首警 ≥ 63s > 60s 冷却。
            await watchdog.beat()
        lag_warnings = [
            record for record in caplog.records if "心跳滞后" in record.message
        ]
        assert len(lag_warnings) == 2, "过冷却窗后必须再报"


@pytest.mark.asyncio
async def test_no_lag_no_warning(caplog) -> None:
    clock = FakeClock()
    # 每拍恰好 interval 秒：零滞后，零告警。
    class ExactSleep:
        def __init__(self, clock: FakeClock) -> None:
            self._clock = clock

        async def __call__(self, seconds: float) -> None:
            self._clock.advance(seconds)

    watchdog = LoopWatchdog(
        interval=5.0,
        lag_threshold=3.0,
        monotonic=clock,
        sleep=ExactSleep(clock),
        pool_probe=lambda: (0, 8),
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        for _ in range(5):
            await watchdog.beat()
    assert caplog.records == []


# ---------------------------------------------------------------- 池饱和


@pytest.mark.asyncio
async def test_pool_saturation_warns_once_per_cooldown(caplog) -> None:
    clock = FakeClock()
    watchdog = make_watchdog(
        clock,
        interval=5.0,
        lag_threshold=3.0,
        pool_cooldown=300.0,
        pool_probe=lambda: (16, 16),  # 满载（在途=许可）。
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        for _ in range(10):  # 10 拍 = 50s < 300s 冷却。
            await watchdog.beat()
    pool_warnings = [
        record for record in caplog.records if "管线池满载" in record.message
    ]
    assert len(pool_warnings) == 1
    assert "16/16" in pool_warnings[0].message
    clock.advance(301.0)
    await watchdog.beat()
    pool_warnings = [
        record for record in caplog.records if "管线池满载" in record.message
    ]
    assert len(pool_warnings) == 2


@pytest.mark.asyncio
async def test_pool_recovery_stops_warnings(caplog) -> None:
    clock = FakeClock()
    state = {"in_flight": 16}

    def probe() -> tuple[int, int]:
        return state["in_flight"], 16

    watchdog = make_watchdog(
        clock, interval=5.0, pool_cooldown=300.0, pool_probe=probe
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        await watchdog.beat()
        state["in_flight"] = 2  # 恢复正常。
        for _ in range(70):  # 远超冷却窗，也不再告警。
            await watchdog.beat()
    assert len([r for r in caplog.records if "管线池满载" in r.message]) == 1


@pytest.mark.asyncio
async def test_probe_failure_disables_pool_observation(caplog) -> None:
    clock = FakeClock()
    calls = {"count": 0}

    def broken_probe() -> tuple[int, int]:
        calls["count"] += 1
        raise RuntimeError("probe unavailable")

    watchdog = make_watchdog(
        clock, interval=5.0, pool_probe=broken_probe
    )
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        await watchdog.beat()
        await watchdog.beat()
    assert calls["count"] == 1, "探测失效必须停用池观测，不得逐拍重试刷日志"
    assert any("探测不可用" in record.message for record in caplog.records)


# ---------------------------------------------------------------- 生命周期


@pytest.mark.asyncio
async def test_run_max_beats_returns() -> None:
    clock = FakeClock()
    watchdog = make_watchdog(clock, interval=5.0)
    await asyncio.wait_for(watchdog.run(max_beats=3), timeout=2.0)
    assert clock.value == 1000.0 + 15.0


@pytest.mark.asyncio
async def test_start_stop_lifecycle() -> None:
    # 生命周期用真实 asyncio.sleep（假 sleep 无让位点，start 后的无限
    # run 循环会饿死事件循环——本轮测试实弹踩过）。
    watchdog = LoopWatchdog(
        interval=0.005,
        monotonic=time.monotonic,
        pool_probe=lambda: (0, 8),
    )
    task = watchdog.start()
    assert watchdog.start() is task  # 幂等。
    await asyncio.sleep(0.05)
    watchdog.stop()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_shared_helpers_start_and_stop() -> None:
    loop_watchdog.reset_shared_for_tests()
    try:
        shared = loop_watchdog.start_loop_watchdog(
            interval=0.05, pool_probe=lambda: (0, 8)
        )
        again = loop_watchdog.start_loop_watchdog()
        assert again is shared
        loop_watchdog.stop_loop_watchdog()
        assert loop_watchdog._SHARED_WATCHDOG is None
    finally:
        loop_watchdog.reset_shared_for_tests()

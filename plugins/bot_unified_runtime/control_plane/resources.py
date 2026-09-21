"""只读、按需且有界的当前进程资源采样；HTTP/CLI 共享同一服务。

CPU 使用累计 user+system 时间除以 monotonic 窗口，单核为 100%，多核可超过
100%。首次/故障后先预热，不返回伪造的零；没有后台线程、目录扫描或数据库写入。
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def _cpu_seconds() -> float:
    times = os.times()
    return times.user + times.system


def _process() -> Any:
    import psutil

    return psutil.Process()


def _measurement(value: Any, unit: str, *, reason: str = "source_unavailable") -> dict[str, Any]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return {"value": None, "status": "unknown", "reason": reason, "unit": unit}
    return {"value": value, "status": "ok", "reason": None, "unit": unit}


def _read(reader: Callable[[], Any], unit: str) -> dict[str, Any]:
    try:
        return _measurement(reader(), unit)
    except Exception:  # noqa: BLE001 - 诊断不得影响业务，异常正文不可暴露。
        return _measurement(None, unit)


class ResourceMetricsService:
    """仅缓存最近一份快照，串行采样；未装配的数据源明确 not_connected。"""

    def __init__(
        self, *, runtime_attached: bool = False,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        cpu_clock: Callable[[], float] = _cpu_seconds,
        process_factory: Callable[[], Any] = _process,
    ) -> None:
        self._monotonic, self._wall_clock = monotonic, wall_clock
        self._cpu_clock, self._process_factory = cpu_clock, process_factory
        self._role = "bot_host" if runtime_attached else "control_plane_host"
        self._lock = threading.Lock()
        self._last_cpu: tuple[float, float] | None = None
        self._sampled_at: float | None = None
        self._cached: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = self._monotonic()
            if self._cached is not None and self._sampled_at is not None and 0 <= now - self._sampled_at < 0.25:
                return deepcopy(self._cached)
            measurements = self._sample(now)
            result = {
                "pid": os.getpid(), "process_role": self._role,
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "sampling": "on_demand", "minimum_interval_seconds": 0.25,
                "measurements": measurements,
            }
            # 保留原 v1 扁平字段；新前端应消费 measurements 的状态/单位。
            for key in ("cpu_time_seconds", "cpu_percent", "memory_bytes"):
                result[key] = measurements[key]["value"]
                result[f"{key}_status"] = measurements[key]["status"]
                result[f"{key}_reason"] = measurements[key]["reason"]
            self._sampled_at, self._cached = now, result
            return deepcopy(result)

    def _sample(self, now: float) -> dict[str, Any]:
        cpu = _read(self._cpu_clock, "seconds")
        percent = _measurement(None, "percent_one_core", reason="warming_up")
        value = cpu["value"]
        if value is None:
            self._last_cpu = None
            percent = _measurement(None, "percent_one_core")
        else:
            if self._last_cpu is not None:
                stamp, previous = self._last_cpu
                elapsed, used = now - stamp, value - previous
                if elapsed > 0 and used >= 0:
                    percent = _measurement(round(100 * used / elapsed, 6), "percent_one_core")
                else:
                    percent = _measurement(None, "percent_one_core", reason="counter_reset")
            self._last_cpu = (now, value)
        fields = {"cpu_time_seconds": cpu, "cpu_percent": percent}
        try:
            process = self._process_factory()
        except Exception:  # noqa: BLE001 - psutil 可选/平台拒绝访问也诚实降级。
            process = None
        for key, unit, reader in (
            ("memory_bytes", "bytes", lambda: process.memory_info().rss),
            ("thread_count", "count", lambda: process.num_threads()),
            ("uptime_seconds", "seconds", lambda: self._wall_clock() - process.create_time()),
        ):
            fields[key] = _read(reader, unit) if process is not None else _measurement(None, unit)
        for key, unit in (("task_count", "count"), ("queue_depth", "count"),
                          ("llm_concurrency", "count"), ("database_bytes", "bytes")):
            fields[key] = _measurement(None, unit, reason="not_connected")
        return fields

"""只读、按需且有界的当前进程资源采样；HTTP/CLI 共享同一服务。

CPU 使用累计 user+system 时间除以 monotonic 窗口，单核为 100%，多核可超过
100%。首次/故障后先预热，不返回伪造的零；没有后台线程、目录扫描或数据库写入。
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

# 有界历史环上限（固定登记，供前端/协议读取）。无后台轮询：只有
# snapshot() 产生新鲜采样时才入环，缓存命中不入环。
HISTORY_MAX_SAMPLES = 60


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


def _read(reader: Callable[[], Any], unit: str, *, reason: str = "source_unavailable") -> dict[str, Any]:
    try:
        return _measurement(reader(), unit, reason=reason)
    except Exception:  # noqa: BLE001 - 诊断不得影响业务，异常正文不可暴露。
        return _measurement(None, unit, reason=reason)


def _handle_reader(process: Any) -> Callable[[], Any]:
    """优先 POSIX ``num_fds``，否则 Windows ``num_handles``；两者皆无则闭合。"""
    for name in ("num_fds", "num_handles"):
        reader = getattr(process, name, None)
        if callable(reader):
            return reader
    raise AttributeError("no fd/handle counter on this process")


class ResourceMetricsService:
    """仅缓存最近一份快照，串行采样；未装配的数据源明确 not_connected。

    ``runtime_provider`` 是可选的**注入式**读取器：只在采样时被调用一次，
    只应返回已在内存/运行时的轻量计数（task/queue/llm/db），**不得在服务内
    扫库或遍历进程/磁盘/网络**；缺失或抛错即诚实降级为 unknown。
    """

    def __init__(
        self, *, runtime_attached: bool = False,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        cpu_clock: Callable[[], float] = _cpu_seconds,
        process_factory: Callable[[], Any] = _process,
        runtime_provider: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self._monotonic, self._wall_clock = monotonic, wall_clock
        self._cpu_clock, self._process_factory = cpu_clock, process_factory
        self._runtime_provider = runtime_provider
        self._role = "bot_host" if runtime_attached else "control_plane_host"
        self._lock = threading.Lock()
        self._last_cpu: tuple[float, float] | None = None
        self._sampled_at: float | None = None
        self._cached: dict[str, Any] | None = None
        self._history: deque[dict[str, Any]] = deque(maxlen=HISTORY_MAX_SAMPLES)

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
                "history_max_samples": HISTORY_MAX_SAMPLES,
                "measurements": measurements,
            }
            # 保留原 v1 扁平字段；新前端应消费 measurements 的状态/单位。
            for key in ("cpu_time_seconds", "cpu_percent", "memory_bytes"):
                result[key] = measurements[key]["value"]
                result[f"{key}_status"] = measurements[key]["status"]
                result[f"{key}_reason"] = measurements[key]["reason"]
            self._sampled_at, self._cached = now, result
            self._history.append(deepcopy(result))
            return deepcopy(result)

    def history(self) -> dict[str, Any]:
        """最近采样环（有界、深拷贝隔离）；无后台轮询，只反映被拉取的快照。"""
        with self._lock:
            return {
                "max_samples": HISTORY_MAX_SAMPLES,
                "samples": [deepcopy(row) for row in self._history],
            }

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
        readers: tuple[tuple[str, str, Callable[[], Any]], ...] = (
            ("memory_bytes", "bytes", lambda: process.memory_info().rss),
            ("thread_count", "count", lambda: process.num_threads()),
            ("uptime_seconds", "seconds", lambda: self._wall_clock() - process.create_time()),
            ("disk_read_bytes", "bytes", lambda: process.io_counters().read_bytes),
            ("disk_write_bytes", "bytes", lambda: process.io_counters().write_bytes),
            ("handle_count", "count", lambda: _handle_reader(process)()),
        )
        for key, unit, reader in readers:
            fields[key] = _read(reader, unit) if process is not None else _measurement(None, unit)
        # psutil 无逐进程网络计数（net_io_counters 是全机口径）：绝不把全机
        # counter 冒充本进程，明确 not_supported。
        for key in ("network_bytes_sent", "network_bytes_received"):
            fields[key] = _measurement(None, "bytes", reason="not_supported")
        # 无 GPU provider：诚实 unavailable，不造数、不读全机 GPU 热点。
        fields["gpu_percent"] = _measurement(None, "percent", reason="no_provider")
        fields.update(self._runtime_fields())
        return fields

    def _runtime_fields(self) -> dict[str, Any]:
        """注入式运行时计数；provider 只被读一次且不得扫库/遍历热点。"""
        keys = (
            ("task_count", "count"),
            ("queue_depth", "count"),
            ("llm_concurrency", "count"),
            ("database_bytes", "bytes"),
        )
        if self._runtime_provider is None:
            return {key: _measurement(None, unit, reason="not_connected") for key, unit in keys}
        try:
            provided = self._runtime_provider()
        except Exception:  # noqa: BLE001 - provider 异常不得回显正文
            return {key: _measurement(None, unit) for key, unit in keys}
        fields: dict[str, Any] = {}
        for key, unit in keys:
            if isinstance(provided, Mapping) and key in provided:
                fields[key] = _measurement(provided[key], unit)
            else:
                fields[key] = _measurement(None, unit, reason="not_connected")
        return fields

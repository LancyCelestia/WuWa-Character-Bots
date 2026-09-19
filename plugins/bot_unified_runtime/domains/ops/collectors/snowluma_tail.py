"""SnowLuma 日志 tail 采集器骨架（S14 席新建件；2026-09-20 随协议端由
NapCat 迁移更名，含 ``parse_level`` 按 SnowLuma 真实行形重写）。

背景：控制面日志面（ops/admin/runtime_logs.py）面向「进程内 logger」；
SnowLuma 侧（WS 对端，独立进程）的日志只能靠 tail 文件采集。本模块是
**骨架**：pull 式 tail 轮询 + 轮转识别 + 行级脱敏 + 级别归一 + 背压丢弃
诚实计数；不含任何装配副作用、不自带线程（``poll_once()`` 由接线席周期
驱动）。

日志实况（实测 ``C:\\Software\\SnowLuma\\logs\\``，2026-09-20）：

- 路径 ``C:\\Software\\SnowLuma\\logs\\snowluma-YYYY-MM-DD.log``，**按日期
  分文件**；
- 行形 ``HH:MM:SS LEVEL [scope] msg``，级别词表只有
  ``DEBUG`` / ``INFO`` / ``WARN`` / ``ERROR`` / ``OK`` 五个（``OK`` 是成功
  标记，归一到 info）；
- 堆栈续行不以时间开头（如 ``Error: ...`` / ``    at ...``）→ 一律
  unknown，不猜。

ponytail: 天花板在文件名——「按日期分文件」意味着跨天等于突然出现一个全新
文件，而本采集器对**首见文件**一律锚定文件尾（不回放积压）。因此跨天后当天
已写入的行不会被采到；要采当天历史须以 ``from_start=True`` 重建采集器。
按日期名探测并自动切换尚未实现。

克制原则（纪律沿袭 log_collectors「不读任意文件」）：

- **path 未配置（None）= 惰性不读**（state=not_configured），只读显式
  传入的 SnowLuma 自身日志文件；
- 轮转识别：文件身份变化（st_dev/st_ino）或尺寸回缩 → 重开从头读
  （rotations 计数）；半行（无换行尾）留残余缓冲等补全；
- **逐行先脱敏再交付**（复用 ops/incident 的 ``redact_text`` 单一事实
  源，sk-/盘符路径/BOT_XXX=/Bearer 全打码）+ 行截断（默认 2000 字符）；
- **背压**：sink 拒收（返回 False）/抛异常 → dropped_lines 计数，绝不
  阻塞、绝不重试放大；未配 sink 时走内部有界缓冲（满=丢新行并计数）；
- **巨量积压跳跃追赶**：单次新增超过 ``max_catchup_bytes`` → 跳到文件尾
  （dropped_bytes 诚实计数，不为追历史拖垮轮询节奏）。

挂接坐标（本席零编辑既有文件，留接线席；详见 docs/design/v21r2-s14-log.md §三）::

    collector = SnowlumaTailCollector(path=<SnowLuma 日志路径，来自配置键>,
                                      sink=<行处理器，可接 IncidentService 适配器>)
    # driver.on_startup 周期任务：collector.poll_once()
    # 或独立线程：collector.poll_forever(stop=停机标志)

- path 来源=SnowLuma 日志目录当日文件（本席不读 .env 不猜路径）；如需配置
  键（建议 ``bot_ops_snowluma_log_path``）由接线席按 config.py+catalog+
  env.example 三处同生规矩登记。**截至本次迁移该键仍未创建**（无消费者即
  不造配置面），采集器也未接入控制面——控制面 ``log_collectors`` 明写
  「不伪造连接、不读任意文件」，接通需先由业主批准越过该边界。
- sink 适配器若接控制面日志流，注意「不归档控制台正文」纪律：正文留存
  由接线席按需裁剪。
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..incident.service import redact_text

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_JUMP_CATCHUP_BYTES",
    "DEFAULT_MAX_BUFFER",
    "DEFAULT_MAX_LINE_CHARS",
    "DEFAULT_POLL_INTERVAL",
    "SnowlumaTailCollector",
    "parse_level",
]

DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_MAX_BUFFER = 256
DEFAULT_MAX_LINE_CHARS = 2000
#: 单次 poll 新增字节超过该值 → 跳跃追赶（4 MiB）。
DEFAULT_JUMP_CATCHUP_BYTES = 4 * 1024 * 1024

_SNOWLUMA_LEVEL_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}\s+([A-Za-z]+)\b")
#: SnowLuma 实测级别词表（2026-09-20 统计两份现役日志：DEBUG 52602 / OK 5444 /
#: WARN 1411 / ERROR 626 / INFO 614，别的一律没有）。OK 是成功标记，归 info。
_SNOWLUMA_LEVEL_MAP = {
    "DEBUG": "debug",
    "INFO": "info",
    "WARN": "warning",
    "WARNING": "warning",
    "ERROR": "error",
    "OK": "info",
}


def parse_level(line: str) -> str:
    """SnowLuma 日志级别归一：行形 ``HH:MM:SS LEVEL [scope] msg``。

    只认实测存在的五个级别词（``OK`` 归 info）；不以 ``HH:MM:SS`` 开头的
    堆栈续行、以及词表外的首字段一律 unknown（不猜）。
    """
    match = _SNOWLUMA_LEVEL_RE.match(line)
    if match:
        return _SNOWLUMA_LEVEL_MAP.get(match.group(1).upper(), "unknown")
    return "unknown"


class SnowlumaTailCollector:
    """SnowLuma 日志文件 tail 骨架（pull 式、可注入、全离线可测）。

    ``sink``：行处理器 ``Callable[[str], bool | None]``——返回 False=拒收
    （背压，dropped_lines 计数）；None=走内部有界缓冲（``drain()`` 取用，
    满则丢新行计数）。所有交付行先脱敏+截断。
    """

    def __init__(
        self,
        *,
        path: str | Path | None = None,
        sink: Callable[[str], bool | None] | None = None,
        from_start: bool = False,
        max_buffer: int = DEFAULT_MAX_BUFFER,
        max_line_chars: int = DEFAULT_MAX_LINE_CHARS,
        max_catchup_bytes: int = DEFAULT_JUMP_CATCHUP_BYTES,
    ) -> None:
        self._path = Path(path) if path is not None else None
        self._sink = sink
        self._from_start = bool(from_start)
        self._max_buffer = max(1, int(max_buffer))
        self._max_line_chars = max(32, int(max_line_chars))
        self._max_catchup = max(1, int(max_catchup_bytes))
        self._buffer: deque[str] = deque()
        self._offset = 0
        self._residual = ""
        self._identity: tuple[int, int] | None = None
        self._state = "not_configured" if self._path is None else "idle"
        # 诚实计数
        self.lines_delivered = 0
        self.dropped_lines = 0
        self.dropped_bytes = 0
        self.rotations = 0
        self.missing_polls = 0
        self.error_polls = 0
        self.sink_errors = 0

    # ------------------------------------------------------------------
    # 公开
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        """not_configured / idle / ok / missing / error（诚实状态）。"""
        return self._state

    @property
    def buffered_lines(self) -> int:
        return len(self._buffer)

    def poll_once(self) -> int:
        """轮询一次：返回本次读到的完整行数（已交付+已丢弃）。不抛异常。"""
        if self._path is None:
            self._state = "not_configured"
            return 0
        try:
            stat = os.stat(self._path)
        except FileNotFoundError:
            self.missing_polls += 1
            self._identity = None
            self._state = "missing"
            return 0
        except OSError:
            self.error_polls += 1
            self._state = "error"
            return 0

        identity = (stat.st_dev, stat.st_ino)
        if self._identity is None:
            # 首见：锚定起点（缺省跳过积压历史；from_start=True 才读历史）。
            self._identity = identity
            self._offset = 0 if self._from_start else stat.st_size
            self._state = "ok"
            if not self._from_start:
                return 0
        elif identity != self._identity or stat.st_size < self._offset:
            self.rotations += 1
            logger.info(
                "snowluma_tail: rotation detected (%s), reopening from start",
                self._path,
            )
            self._identity = identity
            self._offset = 0
            self._residual = ""

        if stat.st_size == self._offset:
            self._state = "ok"
            return 0

        growth = stat.st_size - self._offset
        if growth > self._max_catchup:
            # 巨量积压：跳跃追赶，诚实计数，不追历史。
            self.dropped_bytes += growth
            self._offset = stat.st_size
            self._residual = ""
            self._state = "ok"
            logger.warning(
                "snowluma_tail: backlog %d bytes exceeds catch-up cap, jumped to end",
                growth,
            )
            return 0

        try:
            # 二进制读：text 模式 tell() 携解码器状态，与 st_size 字节比较会错位。
            with open(self._path, "rb") as fh:
                fh.seek(self._offset)
                raw = fh.read()
                self._offset = fh.tell()
        except OSError:
            self.error_polls += 1
            self._state = "error"
            return 0
        chunk = raw.decode("utf-8", errors="replace")

        self._state = "ok"
        if not chunk:
            return 0
        data = self._residual + chunk
        parts = data.split("\n")
        self._residual = parts.pop()  # 半行留残余缓冲，等下次补全
        delivered = 0
        dropped = 0
        for raw_line in parts:
            line = raw_line.rstrip("\r")
            line = redact_text(line, max_chars=self._max_line_chars)
            if self._dispatch(line):
                delivered += 1
            else:
                dropped += 1
        self.lines_delivered += delivered
        self.dropped_lines += dropped
        return delivered + dropped

    def drain(self, limit: int | None = None) -> list[str]:
        """取走内部缓冲行（未配 sink 模式用）。"""
        if limit is None:
            items = list(self._buffer)
            self._buffer.clear()
            return items
        items = [self._buffer.popleft() for _ in range(min(max(0, limit), len(self._buffer)))]
        return items

    def poll_forever(
        self,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        stop: Callable[[], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_cycles: int | None = None,
    ) -> None:
        """周期轮询循环（接线席可放线程/任务里跑；本方法自带可注入 sleep，
        测试用 stop/max_cycles 干跑，零真实等待）。"""
        cycles = 0
        interval = max(0.05, float(poll_interval))
        while max_cycles is None or cycles < max_cycles:
            self.poll_once()
            cycles += 1
            if stop is not None and stop():
                return
            sleep(interval)

    def snapshot(self) -> dict[str, Any]:
        """观测投影（诚实计数全量透出）。"""
        return {
            "state": self._state,
            "path": str(self._path) if self._path is not None else None,
            "offset": self._offset,
            "lines_delivered": self.lines_delivered,
            "dropped_lines": self.dropped_lines,
            "dropped_bytes": self.dropped_bytes,
            "rotations": self.rotations,
            "missing_polls": self.missing_polls,
            "error_polls": self.error_polls,
            "sink_errors": self.sink_errors,
            "buffered_lines": len(self._buffer),
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _dispatch(self, line: str) -> bool:
        if self._sink is not None:
            try:
                result = self._sink(line)
            except Exception:
                self.sink_errors += 1
                logger.exception("snowluma_tail: sink raised (counted, not retried)")
                return False
            return result is not False
        if len(self._buffer) >= self._max_buffer:
            return False
        self._buffer.append(line)
        return True

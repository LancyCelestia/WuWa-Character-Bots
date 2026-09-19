"""ops/collectors：对端日志采集器（SnowLuma tail 骨架等）。

采集器一律 pull 式（``poll_once()`` 由接线席周期驱动）、零装配副作用、
逐行脱敏、背压丢弃诚实计数；连接点坐标见 docs/design/v21r2-s14-log.md。
"""

from .snowluma_tail import (
    DEFAULT_JUMP_CATCHUP_BYTES,
    DEFAULT_MAX_BUFFER,
    DEFAULT_MAX_LINE_CHARS,
    DEFAULT_POLL_INTERVAL,
    SnowlumaTailCollector,
    parse_level,
)

__all__ = [
    "DEFAULT_JUMP_CATCHUP_BYTES",
    "DEFAULT_MAX_BUFFER",
    "DEFAULT_MAX_LINE_CHARS",
    "DEFAULT_POLL_INTERVAL",
    "SnowlumaTailCollector",
    "parse_level",
]

"""运行时事件日志（毫秒时间戳 + 分级 + 查询）测试。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from plugins.bot_unified_runtime.sources.runtime_event_log import RuntimeEventLog

_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[[A-Z]+\] "
)


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_emit_writes_millisecond_timestamp_and_level(tmp_path):
    log = RuntimeEventLog(tmp_path / "events.log")
    log.info("startup", module="test")
    lines = _read(tmp_path / "events.log")
    assert len(lines) == 1
    assert _TS_RE.match(lines[0]), lines[0]
    assert "[INFO]" in lines[0]
    assert "event=startup" in lines[0]
    assert "module=test" in lines[0]


def test_levels_and_filtering(tmp_path):
    log = RuntimeEventLog(tmp_path / "events.log", min_level="INFO")
    log.info("a")
    log.warning("b")
    log.error("c")
    log.debug("hidden")  # 低于 min_level 不应写盘。
    lines = _read(tmp_path / "events.log")
    assert ["[INFO]" in l for l in lines] == [True, False, False]
    assert len(lines) == 3
    recent = log.read_recent(50, min_level="WARNING")
    assert len(recent) == 2
    assert all("[WARNING]" in l or "[ERROR]" in l for l in recent)


def test_read_recent_limit_and_rotation(tmp_path):
    log = RuntimeEventLog(tmp_path / "events.log", max_bytes=600)
    for index in range(20):
        log.info("tick", index=index, payload="x" * 60)
    recent = log.read_recent(5)
    assert len(recent) == 5
    assert "index=19" in recent[-1]


def test_logging_bridge_captures_nonebot_logger(tmp_path):
    log = RuntimeEventLog(tmp_path / "events.log")
    bridge = log.attach_to_logging("nonebot.test.runtime")
    logger = logging.getLogger("nonebot.test.runtime")
    logger.setLevel(logging.DEBUG)
    logger.info("adapter connected ws://127.0.0.1:3001")
    logger.warning("retry after -412")
    bridge.close()
    logger.handlers.remove(bridge)
    lines = _read(tmp_path / "events.log")
    assert any("[INFO]" in l and "adapter connected" in l for l in lines)
    assert any("[WARNING]" in l and "retry after" in l for l in lines)

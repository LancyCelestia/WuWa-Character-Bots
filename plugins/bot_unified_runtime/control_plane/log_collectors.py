"""进程日志适配器：只收集来源、级别和白名单标量，不归档控制台正文。

生命周期显式装配，stdlib 保留现有 handler/level；NoneBot 仅对已加载的
Loguru logger 增加自有 sink。SnowLuma 是外部进程，提供 ingest 协议口但不
伪造连接、不读任意文件、不执行控制台命令。总线拥塞或关闭时快速丢弃。
"""
from __future__ import annotations

import logging
import sys
from typing import Any

from .events import DETAIL_KEYS, EVENT_SOURCES, RuntimeEventBus, RuntimeLogEvent

_LEVELS = {
    "TRACE": "detail", "DETAIL": "detail", "DEBUG": "debug", "INFO": "info",
    "WARN": "warning", "WARNING": "warning", "ERROR": "error",
    "SUCCESS": "success", "FATAL": "critical", "CRITICAL": "critical",
}
_SUBSYSTEMS = {
    "control_plane": "control_plane", "decision": "decision_engine",
    "runtime.pipeline": "pipeline", "sender": "sender", "llm": "llm",
    "scheduler": "scheduler", "database": "database", "mail_adapter": "mail",
    # v21r2 W14 transport 重组：sender/mail_adapter 真身迁 domains/transport/ 后
    # logger __name__ 前缀变化，补新锚防事件源从 sender/mail 降级为 bot（旧锚保留）。
    "domains.transport.sender": "sender", "domains.transport.mail": "mail",
    # v21r2 W15b chat_reply 重组：llm_engine 真身迁 domains/chat_reply/llm_engine/ 后
    # logger __name__ 前缀变化，补新锚防事件源从 llm 降级为 bot（旧锚保留）。
    "domains.chat_reply.llm_engine": "llm",
    # v21r2 W15d chat_reply 重组：pipeline 真身迁 domains/chat_reply/runtime/ 后
    # 同型补锚防事件源从 pipeline 降级为 bot（旧锚保留；_namespace 前缀匹配）。
    "domains.chat_reply.runtime.pipeline": "pipeline",
    # v21r2 RWOC 尾声波重组：decision 真身迁 domains/core/decision/ 后
    # 同型补锚防事件源从 decision_engine 降级为 bot（旧锚保留；_namespace 前缀匹配）。
    "domains.core.decision": "decision_engine",
}


def _namespace(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def _source(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    for adapter in ("telegram", "mail"):
        if _namespace(name, "nonebot.adapters." + adapter):
            return adapter
    if _namespace(name, "nonebot"):
        return "nonebot"
    for prefix in ("plugins.bot_unified_runtime", "bot_unified_runtime"):
        if not _namespace(name, prefix):
            continue
        local = name.removeprefix(prefix).lstrip(".")
        # 总线写失败不能递归变成另一条待写日志。
        if any(_namespace(local, p) for p in ("control_plane.events", "control_plane.log_collectors")):
            return None
        return next((source for p, source in _SUBSYSTEMS.items() if _namespace(local, p)), "bot")
    return "bot" if name == "bot" else None


def disconnected_collectors() -> dict[str, Any]:
    return {"stdlib": "not_connected", "nonebot": "not_connected", "napcat": "not_connected", "raw_content": False, "publish_failures": 0}


class _SummaryHandler(logging.Handler):
    def __init__(self, owner: ProcessLogCollector) -> None:
        super().__init__(level=logging.NOTSET)
        self.owner = owner

    def emit(self, record: logging.LogRecord) -> None:
        if self.owner.active:
            self.owner.handle_stdlib(record)


class ProcessLogCollector:
    def __init__(
        self, bus: RuntimeEventBus, *, root_logger: logging.Logger | None = None,
        nonebot_logger: Any | None = None,
    ) -> None:
        self.bus = bus
        self._root = root_logger if root_logger is not None else logging.getLogger()
        self._nonebot = nonebot_logger
        self._handler: _SummaryHandler | None = None
        self._sink_id: int | None = None
        self._nonebot_status = "not_connected"
        self.active = False
        self.publish_failures = 0

    def status(self) -> dict[str, Any]:
        result = disconnected_collectors()
        result.update(stdlib="attached" if self._handler is not None else "not_connected", nonebot=self._nonebot_status, publish_failures=self.publish_failures)
        return result

    def ingest(self, *, source: str, level: str, details: Any = None) -> bool:
        """内部适配口，不是公网 ingest API；不接受自由文本、文件路径或命令。"""
        if type(source) is not str or source not in EVENT_SOURCES or type(level) is not str:
            return False
        category = _LEVELS.get(level.upper())
        if category is None:
            return False
        try:
            return self.bus.publish(RuntimeLogEvent(source=source, category=category, details=details or {}))
        except Exception:  # noqa: BLE001 - 日志失败不能影响业务，也不能递归打日志。
            self.publish_failures += 1
            return False

    def handle_stdlib(self, record: logging.LogRecord) -> None:
        source = _source(record.name)
        if source is not None:
            # 不调用 getMessage/Formatter/handleError，不读取 exc_info/pathname。
            self.ingest(source=source, level=record.levelname, details={key: record.__dict__[key] for key in DETAIL_KEYS if key in record.__dict__})

    def _loguru_sink(self, message: Any) -> None:
        if not self.active:
            return
        try:
            record = message.record
            source = _source(record.get("name"))
            if source is not None:
                self.ingest(source=source, level=record["level"].name, details=record.get("extra"))
        except Exception:  # noqa: BLE001 - SDK/sink 异常绝不打断 NoneBot。
            self.publish_failures += 1

    def start(self) -> None:
        if self.active:
            return
        self.active = True
        self._handler = _SummaryHandler(self)
        self._root.addHandler(self._handler)
        # 不为 standalone 控制面导入或初始化 NoneBot。
        if self._nonebot is None:
            module = sys.modules.get("nonebot.log")
            self._nonebot = getattr(module, "logger", None)
        if self._nonebot is not None:
            try:
                self._sink_id = self._nonebot.add(self._loguru_sink, level=0, format="", backtrace=False, diagnose=False, catch=True)
                self._nonebot_status = "attached"
            except Exception:  # noqa: BLE001 - 保留 stdlib 采集，状态诚实降级。
                self._nonebot_status = "attach_failed"

    def close(self) -> None:
        self.active = False
        if self._handler is not None:
            self._root.removeHandler(self._handler)
            self._handler.close()
            self._handler = None
        if self._sink_id is not None and self._nonebot is not None:
            try:
                self._nonebot.remove(self._sink_id)
            except Exception:  # noqa: BLE001 - 保留 ID 供下次清理重试，迟到回调已禁用。
                self._nonebot_status = "detach_failed"
            else:
                self._sink_id = None
                self._nonebot_status = "not_connected"

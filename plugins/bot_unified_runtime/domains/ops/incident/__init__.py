"""ops/incident：结构化事件服务（V21-INCIDENT-001 唯一载体）。

IncidentService：时间/位置/解释/方法/trace/严重度 → 脱敏（render 真身
单一事实源）→ 同因聚合（窗口合并 + stride 重通知）→ sink 通知（默认
LoggingIncidentSink）→ 环形存储 → 查询 API。防递归：report 全捕获。
"""

from .service import (
    DEFAULT_AGGREGATION_WINDOW_SECONDS,
    DEFAULT_MAX_RECORDS,
    DEFAULT_MAX_TEXT_CHARS,
    DEFAULT_NOTIFY_STRIDE,
    SEVERITY_ORDER,
    Incident,
    IncidentAggregate,
    IncidentService,
    IncidentSink,
    LoggingIncidentSink,
    redact_text,
    redact_user_text,
)

__all__ = [
    "DEFAULT_AGGREGATION_WINDOW_SECONDS",
    "DEFAULT_MAX_RECORDS",
    "DEFAULT_MAX_TEXT_CHARS",
    "DEFAULT_NOTIFY_STRIDE",
    "SEVERITY_ORDER",
    "Incident",
    "IncidentAggregate",
    "IncidentService",
    "IncidentSink",
    "LoggingIncidentSink",
    "redact_text",
    "redact_user_text",
]

"""结构化事件服务（V21-INCIDENT-001 唯一载体，S14 席新建件）。

背景：runtime/error_report.py 的错误卡是非结构化单发（面向人肉看图），
控制面/查询面需要的是**结构化 Incident**（时间/位置/解释/方法/trace/
严重度）+ 同因聚合 + 可注入通知 sink + 查询 API。本模块提供该载体；与
domains/ops/recovery.RecoveryService 的 ``IncidentReporter`` 协议对接
（recovery 注入本服务为 reporter）。真实 admin 推送（SendQueue/outbox）
由接线席注入 sink 实现，本模块默认只走 stdlib log，不碰出站。

脱敏契约（零例外）：

- sk- 形态密钥、盘符路径（``C:\\`` 与 ``C:/``）、``BOT_XXX=`` 环境赋值、
  Bearer/JWT/裸键值一律打码——**懒加载复用**
  ``domains/render/plain_text.py::redact_local_secrets`` 真身（单一事实
  源不复制正则；导入失败降级本地最小正则，绝不因脱敏器缺失而泄漏）；
- **用户派生文本必须走 ``user_text`` 参数**——本服务只保留「已隐去 N 字」
  痕迹，原文不入环不入日志；
- explanation/method 截断（默认 400 字符）防日志膨胀。

同因聚合：指纹 = sha1(component | 归一化 explanation 头部)。聚合窗内同
指纹重复上报只累加计数、抑制 sink；计数每达 ``notify_stride`` 倍数重发
一次（防完全静默）；窗口过期后重新触发通知（count 累积不清零、首见时间
保留，供查询面看总量）。

防递归：report 全捕获不外抛；sink 异常计数不递归；内存环上限
``max_records``（默认 500）。
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

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

#: 严重度全序（min_severity 过滤用；未知档一律落 warning，不猜更高）。
SEVERITY_ORDER: dict[str, int] = {"info": 0, "warning": 1, "error": 2, "critical": 3}

DEFAULT_MAX_RECORDS = 500
DEFAULT_AGGREGATION_WINDOW_SECONDS = 300.0
DEFAULT_MAX_TEXT_CHARS = 400
DEFAULT_NOTIFY_STRIDE = 10
_MAX_COMPONENT_CHARS = 120
_MAX_TRACE_CHARS = 200
_FINGERPRINT_HEAD_CHARS = 120

_FALLBACK_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{6,}")
_FALLBACK_DRIVE_RE = re.compile(r"\b[A-Za-z]:[\\/][^\s\"'）)】\]]*")
_FALLBACK_ENV_RE = re.compile(r"\b(BOT_[A-Z0-9_]+)\s*=\s*[^\s，。；\"']+")
_FALLBACK_BEARER_RE = re.compile(r"\b(Bearer|bearer)\s+[A-Za-z0-9._\-]{8,}")


def _fallback_redact(text: str) -> str:
    """脱敏真身导入失败时的本地最小兜底（宁可多打码不能漏）。"""
    value = _FALLBACK_ENV_RE.sub(r"\1=***", text)
    value = _FALLBACK_BEARER_RE.sub(r"\1 ***", value)
    value = _FALLBACK_SK_RE.sub("sk-***", value)
    value = _FALLBACK_DRIVE_RE.sub("<路径已打码>", value)
    return value


_REDACT_FN = None


def _load_redactor():
    """懒加载 render 域脱敏真身（单一事实源）；失败固定到本地兜底。"""
    global _REDACT_FN
    if _REDACT_FN is None:
        try:
            from plugins.bot_unified_runtime.domains.render.plain_text import (
                redact_local_secrets as _fn,
            )

            _REDACT_FN = _fn
        except Exception:  # noqa: BLE001 - 渲染域缺失时兜底（fail-open）
            logger.warning("incident: redact_local_secrets unavailable, fallback on")
            _REDACT_FN = _fallback_redact
    return _REDACT_FN


def redact_user_text(text: str | None) -> str:
    """用户派生文本专用：只留字数痕迹，原文零保留。"""
    if not text:
        return ""
    return f"<用户文本 {len(text)} 字，已隐去>"


def redact_text(text: str | None, *, max_chars: int | None = None) -> str:
    """公开脱敏入口：render 域 ``redact_local_secrets`` 真身懒加载（失败
    降级本地兜底正则，不因脱敏器缺失而泄漏）；``max_chars`` 截断防膨胀。
    采集侧（collectors/snowluma_tail 等）经此复用同一事实源。"""
    value = text or ""
    try:
        value = _load_redactor()(value)
    except Exception:  # 脱敏器自身缺陷也不外溢、不泄漏 → 本地兜底正则
        logger.exception("incident: redaction failed, using fallback patterns")
        value = _fallback_redact(value)
    if max_chars is not None and len(value) > max_chars:
        value = value[:max_chars] + "…(已截断)"
    return value


@dataclass(frozen=True)
class Incident:
    """结构化事件（矩阵 L72 字段清单：时间/位置/解释/方法/Trace/严重度）。

    explanation/method 出本模块前已完成脱敏+截断；occurrence_count 为该
    指纹到本条为止的累计次数（聚合窗内首报=1）。
    """

    seq: int
    timestamp: float
    component: str
    severity: str
    explanation: str
    method: str = ""
    trace_id: str | None = None
    fingerprint: str = ""
    occurrence_count: int = 1


@dataclass(frozen=True)
class IncidentAggregate:
    """同因聚合投影（查询面用；first_seen 全历史保留）。"""

    fingerprint: str
    component: str
    count: int
    first_seen: float
    last_seen: float
    latest_severity: str
    latest_explanation: str


@runtime_checkable
class IncidentSink(Protocol):
    """通知面协议（接线席注入；默认 LoggingIncidentSink）。

    实现必须自身不抛异常；抛出会被本服务捕获计数（防递归），事件照常入环。
    """

    def emit(self, incident: Incident) -> None: ...


_SEVERITY_LOG_LEVEL = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


class LoggingIncidentSink:
    """默认通知面：结构化一行进 stdlib log（严重度→log 级别）。"""

    def __init__(self, logger_name: str = "ops.incident") -> None:
        self._logger = logging.getLogger(logger_name)

    def emit(self, incident: Incident) -> None:
        level = _SEVERITY_LOG_LEVEL.get(incident.severity, logging.WARNING)
        self._logger.log(
            level,
            "[incident#%s] %s %s: %s | method=%s | trace=%s | count=%s",
            incident.seq,
            incident.severity,
            incident.component,
            incident.explanation,
            incident.method or "-",
            incident.trace_id or "-",
            incident.occurrence_count,
        )


@dataclass
class _AggregateState:
    component: str
    count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    last_notified_at: float = 0.0
    latest: Incident | None = None


class IncidentService:
    """结构化事件入口：脱敏 → 同因聚合 → sink 通知 → 环形存储 → 查询。

    ``sink`` 注入通知面（缺省 LoggingIncidentSink）；``clock`` 注入实现
    离线确定性（epoch 秒）。``report_incident`` 不抛异常（防递归）。
    """

    def __init__(
        self,
        *,
        sink: IncidentSink | None = None,
        clock: Callable[[], float] | None = None,
        max_records: int = DEFAULT_MAX_RECORDS,
        aggregation_window_seconds: float = DEFAULT_AGGREGATION_WINDOW_SECONDS,
        max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
        notify_stride: int = DEFAULT_NOTIFY_STRIDE,
    ) -> None:
        self._sink: IncidentSink = LoggingIncidentSink() if sink is None else sink
        self._clock = time.time if clock is None else clock
        self._records: deque[Incident] = deque(maxlen=max(1, int(max_records)))
        self._aggregates: dict[str, _AggregateState] = {}
        self._window = max(0.0, float(aggregation_window_seconds))
        self._max_text = max(20, int(max_text_chars))
        self._stride = max(1, int(notify_stride))
        self._seq = 0
        # 观测计数
        self.total_reported = 0
        self.sink_suppressed = 0
        self.sink_failures = 0

    # ------------------------------------------------------------------
    # 上报
    # ------------------------------------------------------------------

    def report_incident(
        self,
        *,
        component: str,
        severity: str,
        explanation: str,
        method: str = "",
        trace_id: str | None = None,
        user_text: str | None = None,
    ) -> Incident:
        """结构化事件上报入口（同步、不抛异常）。

        ``user_text``：用户派生文本走这里——只留字数痕迹，原文零保留。
        """
        now = self._clock()
        safe_severity = severity if severity in SEVERITY_ORDER else "warning"
        safe_component = self._clip(component, _MAX_COMPONENT_CHARS)
        text = self._clip(self._safe_redact(explanation), self._max_text)
        if user_text:
            note = redact_user_text(user_text)
            text = self._clip(f"{text}（{note}）", self._max_text)
        safe_method = self._clip(self._safe_redact(method), self._max_text)
        safe_trace = (
            self._clip(self._safe_redact(trace_id), _MAX_TRACE_CHARS)
            if trace_id
            else None
        )
        fingerprint = self._fingerprint(safe_component, text)

        self._seq += 1
        self.total_reported += 1
        incident = Incident(
            seq=self._seq,
            timestamp=now,
            component=safe_component,
            severity=safe_severity,
            explanation=text,
            method=safe_method,
            trace_id=safe_trace,
            fingerprint=fingerprint,
            occurrence_count=1,
        )

        state = self._aggregates.get(fingerprint)
        if state is None:
            state = _AggregateState(component=safe_component)
            self._aggregates[fingerprint] = state
            state.first_seen = now
            state.last_notified_at = now
        state.count += 1
        state.last_seen = now
        state.latest = incident
        incident = Incident(
            seq=incident.seq,
            timestamp=incident.timestamp,
            component=incident.component,
            severity=incident.severity,
            explanation=incident.explanation,
            method=incident.method,
            trace_id=incident.trace_id,
            fingerprint=fingerprint,
            occurrence_count=state.count,
        )

        self._records.append(incident)

        # 通知抑制：距上次通知在窗口内的同指纹重复只入环不通知；
        # 计数每达 notify_stride 倍数、或距上次通知已超窗（新episode）→ 重发。
        suppress = False
        if state.count > 1:
            within_window = (now - state.last_notified_at) <= self._window
            if within_window and state.count % self._stride != 0:
                suppress = True
        if suppress:
            self.sink_suppressed += 1
            return incident
        state.last_notified_at = now
        self._emit(incident)
        return incident

    # ------------------------------------------------------------------
    # 查询 API
    # ------------------------------------------------------------------

    def list_incidents(
        self,
        *,
        component: str | None = None,
        min_severity: str | None = None,
        since: float | None = None,
        limit: int = 50,
    ) -> list[Incident]:
        """查询事件（新→旧）；component 精确匹配、min_severity 全序过滤、
        since 为 epoch 下界、limit 截断。"""
        floor = SEVERITY_ORDER.get(min_severity) if min_severity else None
        out: list[Incident] = []
        for incident in reversed(self._records):
            if component is not None and incident.component != component:
                continue
            if floor is not None and SEVERITY_ORDER.get(incident.severity, 1) < floor:
                continue
            if since is not None and incident.timestamp < since:
                continue
            out.append(incident)
            if len(out) >= max(1, int(limit)):
                break
        return out

    def get_incident(self, seq: int) -> Incident | None:
        for incident in reversed(self._records):
            if incident.seq == seq:
                return incident
        return None

    def aggregates(self) -> list[IncidentAggregate]:
        """同因聚合投影（按累计次数降序）。"""
        out: list[IncidentAggregate] = []
        for fingerprint, state in self._aggregates.items():
            latest = state.latest
            out.append(
                IncidentAggregate(
                    fingerprint=fingerprint,
                    component=state.component,
                    count=state.count,
                    first_seen=state.first_seen,
                    last_seen=state.last_seen,
                    latest_severity=latest.severity if latest else "warning",
                    latest_explanation=latest.explanation if latest else "",
                )
            )
        out.sort(key=lambda agg: agg.count, reverse=True)
        return out

    def stats(self) -> dict[str, int]:
        return {
            "total_reported": self.total_reported,
            "records": len(self._records),
            "fingerprints": len(self._aggregates),
            "sink_suppressed": self.sink_suppressed,
            "sink_failures": self.sink_failures,
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _emit(self, incident: Incident) -> None:
        try:
            self._sink.emit(incident)
        except Exception:
            self.sink_failures += 1
            logger.exception(
                "incident: sink emit failed (fail-open), seq=%s", incident.seq
            )

    def _safe_redact(self, text: str | None) -> str:
        return redact_text(text, max_chars=self._max_text)

    def _clip(self, text: str | None, limit: int) -> str:
        value = text or ""
        if len(value) <= limit:
            return value
        return value[:limit] + "…(已截断)"

    @staticmethod
    def _fingerprint(component: str, explanation: str) -> str:
        head = explanation.casefold().strip()[:_FINGERPRINT_HEAD_CHARS]
        raw = f"{component}\x1f{head}".encode("utf-8", errors="replace")
        return hashlib.sha1(raw).hexdigest()[:16]

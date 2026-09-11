"""DecisionTrace（B2 阶段 0）：决策全程可解释的记录载体与落点。

规格：docs/design/central-decision-engine.md §2.3.2——决策链每一环落一行
stage 记录（stage/kind/allowed/reason/ms）。存储形态（SQLite 独立表 vs 并入
RuntimeDiagnostic）属规格开放问题 Q5，本阶段只提供进程内有界 sink，不做
持久化裁决。
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_trace_id() -> str:
    return f"dt_{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class DecisionStageRow:
    """决策链单环记录（规格 §2.3.2：stage/kind/allowed/reason/ms）。

    ``allowed=None`` 表示影子模式下该环不实际裁决（如幂等/门禁），移交
    现行 RuntimePipeline 判定；``kind`` 为该环产出或经过的动作类别。
    """

    stage: str
    kind: str
    allowed: bool | None
    reason: str = ""
    ms: float = 0.0


@dataclass(frozen=True)
class DecisionTrace:
    """一次引擎裁决的完整影子记录（只记不发；不含任何发送路径）。"""

    trace_id: str
    request_id: str
    mode: str
    origin: str
    plan_action: str = ""
    plan_capability_id: str = ""
    plan_reason: str = ""
    route_kind: str = ""
    route_priority: int | None = None
    legacy_capability_id: str = ""
    agree: bool | None = None
    compare_note: str = ""
    elapsed_ms: float = 0.0
    error: str = ""
    stages: tuple[DecisionStageRow, ...] = ()
    created_at: datetime = field(default_factory=_utc_now)


class DecisionTraceSink(Protocol):
    def record(self, trace: DecisionTrace) -> None: ...


class InMemoryDecisionTraceSink:
    """有界进程内 sink：供 shadow 比对与测试检查；超出容量丢最旧。"""

    def __init__(self, max_entries: int = 1024) -> None:
        self._max_entries = max(1, int(max_entries))
        self._lock = threading.Lock()
        self._entries: deque[DecisionTrace] = deque(maxlen=self._max_entries)

    def record(self, trace: DecisionTrace) -> None:
        with self._lock:
            self._entries.append(trace)

    def snapshot(self) -> list[DecisionTrace]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_default_sink: DecisionTraceSink = InMemoryDecisionTraceSink()


def get_decision_trace_sink() -> DecisionTraceSink:
    """默认 trace 落点；持久化形态裁决（开放问题 Q5）后可整体替换。"""
    return _default_sink


def set_decision_trace_sink(sink: DecisionTraceSink) -> None:
    global _default_sink
    _default_sink = sink

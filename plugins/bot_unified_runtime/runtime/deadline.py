"""请求级单调时钟预算（handover 9.2）。

同一用户请求从 LLM、工具循环到发送共用一个单调时钟 deadline；各阶段只能
消费剩余预算，不能各自重新计时。只记录固定阶段名与耗时，不记录用户正文。
"""

from __future__ import annotations

import math
import time


class DeadlineExceeded(RuntimeError):
    """请求总预算耗尽；对应稳定错误 kind=``deadline_exceeded``，不可自动重试。"""


class DeadlineBudget:
    """单调时钟预算：started_at + 绝对 deadline + 剩余时间 + 阶段耗时。

    total_seconds<=0 表示未启用（所有门控退化为无操作，保持旧调用方行为）。
    """

    def __init__(self, total_seconds: float, *, started_at: float | None = None) -> None:
        number = float(total_seconds)
        if math.isnan(number) or number <= 0:
            number = 0.0
        self.total_seconds = number
        self.started_at = (
            float(started_at) if started_at is not None else time.monotonic()
        )
        self.phases_ms: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return self.total_seconds > 0

    @property
    def deadline(self) -> float | None:
        """绝对单调时钟 deadline；未启用返回 None（调用方保持自身默认）。"""
        if not self.enabled:
            return None
        return self.started_at + self.total_seconds

    def remaining_seconds(self) -> float:
        deadline = self.deadline
        if deadline is None:
            return math.inf
        return deadline - time.monotonic()

    def expired(self) -> bool:
        return self.enabled and self.remaining_seconds() <= 0.0

    def ensure_available(self, stage: str = "") -> None:
        """预算耗尽后不允许再启动新的网络调用。"""
        if self.expired():
            raise DeadlineExceeded(stage or "deadline_exceeded")

    def timeout_for(self, default_seconds: float | None) -> float | None:
        """调用方超时与剩余预算取最小值；未启用返回 None 保持调用方默认。"""
        if not self.enabled:
            return None
        remaining = self.remaining_seconds()
        if remaining <= 0.0:
            raise DeadlineExceeded("timeout_for")
        default = float(default_seconds) if default_seconds else remaining
        return max(0.0, min(default, remaining))

    def record_phase(self, stage: str, started_at: float) -> None:
        """累计阶段耗时（毫秒）；stage 只允许固定阶段名，不含用户内容。"""
        elapsed_ms = max(0.0, (time.monotonic() - started_at) * 1000.0)
        self.phases_ms[stage] = self.phases_ms.get(stage, 0.0) + elapsed_ms


def apply_request_deadline(
    timeout_seconds: float, deadline_monotonic: float | None
) -> float:
    """发送层超时与请求 deadline 取最小值。

    预算耗尽时不抛异常：回复已生成、LLM 成本已花掉，因总预算到点而丢弃
    消息只会表现为"机器人不回话"（用户侧无任何反馈）。发送是最后一段
    里程，给足传输层自身超时（transport_grace_seconds），超时仍走
    result-unknown 账本兜底。
    """
    if deadline_monotonic is None:
        return timeout_seconds
    deadline = float(deadline_monotonic)
    if not math.isfinite(deadline) or deadline <= 0:
        return timeout_seconds
    remaining = deadline - time.monotonic()
    if remaining <= 0.0:
        return float(timeout_seconds)
    return min(float(timeout_seconds), remaining)

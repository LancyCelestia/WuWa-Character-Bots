"""Dispatcher（B2 阶段 1）：统一派发器——出站副作用收编路径可用。

规格：docs/design/central-decision-engine.md §2.3.3。阶段 0 的 shadow 模式
**只算 plan 写 trace，绝不发送**；该语义原样保持。阶段 1（V21-DISPATCH-001
风险 5 收口）起，本派发器对 plan 携带的出站副作用意图（``OutboundIntent``，
poke/reaction 等已收编直连点）经统一出站执行器
（``control_plane.dispatcher.OutboundSideEffectExecutor``：准入→租约→固定
映射→通道本体）真实派发；文本/卡片等能力派发（复用
``_run_capability_through_pipeline`` A 类骨架）仍属迁移阶段 2+。

诚实边界：shadow/未知/legacy 语境只记录绝不发送；engine_only 语境下执行器
未绑定时返回显式结果（outbound_not_bound）而非异常——半个发送路径在任何
阶段都不存在。plan/ctx 按鸭子协议防御式读取（裸对象也能走完决策周期）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from plugins.bot_unified_runtime.domains.core.decision.engine import (
    ActionPlan,
    DecisionContext,
)
from plugins.bot_unified_runtime.domains.core.decision.outbound import OutboundIntent

if TYPE_CHECKING:
    from plugins.bot_unified_runtime.control_plane.dispatcher import (
        OutboundSideEffectExecutor,
    )


@dataclass(frozen=True)
class DispatchOutcome:
    """一次派发周期的显式终态（绝不返回「半个发送」）。"""

    status: str
    detail: str = ""


class Dispatcher:
    """engine_only 模式的派发器（阶段 1：出站副作用收编路径可用）。"""

    def __init__(
        self,
        engine: Any = None,
        pipeline: Any = None,
        *,
        outbound_executor: OutboundSideEffectExecutor | None = None,
    ) -> None:
        self.engine = engine
        self.pipeline = pipeline
        self.outbound_executor = outbound_executor

    async def dispatch(
        self,
        plan: ActionPlan | Any,
        ctx: DecisionContext | Any | None = None,
    ) -> DispatchOutcome:
        """派发一个决策 plan。

        - 语境判定防御式（``ctx.mode``，缺省=shadow——阶段 0 安全默认）：
          非 engine_only 只记录，**绝不发送**；
        - engine_only：对 plan.outbound_intents（防御式读取，逐项过滤严格
          DTO 实例）经统一出站执行器逐一派发，回执聚合为显式结果；
        - 执行器未绑定：显式 outbound_not_bound（不抛、不发、不装成功）。
        """
        mode = str(getattr(ctx, "mode", "") or "").strip().lower()
        intents = [
            item
            for item in (getattr(plan, "outbound_intents", None) or [])
            if isinstance(item, OutboundIntent)
        ]
        if mode != "engine_only":
            # 阶段 0 语义：shadow/未知/legacy 语境只记录，绝不发送。
            return DispatchOutcome(
                "shadow_recorded",
                f"mode={mode or 'shadow'} outbound_intents={len(intents)} "
                "(not sent: shadow semantics)",
            )
        if not intents:
            return DispatchOutcome(
                "no_outbound", "engine_only plan carries no outbound intent",
            )
        if self.outbound_executor is None:
            return DispatchOutcome(
                "outbound_not_bound",
                "no OutboundSideEffectExecutor bound; refusing half-send",
            )
        statuses: list[str] = []
        delivered = 0
        for intent in intents:
            receipt = await self.outbound_executor.execute(intent)
            statuses.append(f"{intent.dedupe_key}:{receipt.status}")
            if receipt.delivered:
                delivered += 1
        if delivered == len(intents):
            status = "dispatched"
        elif delivered == 0:
            status = "blocked"
        else:
            status = "partial"
        return DispatchOutcome(status, ";".join(statuses))

"""Dispatcher（B2 阶段 0 骨架）：统一派发器占位。

规格：docs/design/central-decision-engine.md §2.3.3。阶段 0 的 shadow 模式
**只算 plan 写 trace，绝不发送**；本模块只固定派发器的位置与守卫——真正的
能力派发（复用 ``_run_capability_through_pipeline`` A 类骨架）随迁移阶段 1+
首个能力进入 engine_only 模式时接入。在阶段 0，任何调用都会显式失败而非
产生半个发送路径。
"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.decision.engine import ActionPlan, DecisionContext


class Dispatcher:
    """engine_only 模式的派发器（阶段 0：显式未启用）。"""

    def __init__(self, engine: Any = None, pipeline: Any = None) -> None:
        self.engine = engine
        self.pipeline = pipeline

    async def dispatch(self, plan: ActionPlan, ctx: DecisionContext) -> None:
        raise NotImplementedError(
            "engine dispatch activates with the first migrated capability "
            "(migration stage 1+); phase-1 keeps legacy matchers as the only actor"
        )

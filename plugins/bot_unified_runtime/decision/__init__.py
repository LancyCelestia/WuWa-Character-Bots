"""B2 中央决策引擎（阶段 0 骨架）：类型与引擎的统一出口。

规格：docs/design/central-decision-engine.md。本包保持轻导入：只有 stdlib
与 contracts 级依赖在模块导入时加载；引擎/路由分类（base_router → 各能力
模块链）一律经函数内惰性导入，确保 ``legacy_only`` 模式下 pipeline 热路径
零额外导入成本。

迁移模式：``bot_decision_engine_mode``（legacy_only[默认] / shadow /
engine_only[阶段 1+ 启用，当前回落 legacy_only]）。
"""

from __future__ import annotations

from typing import Any

# 导出经 ``__getattr__`` 惰性解析（见 _LAZY_EXPORTS）：保持包导入轻量，
# legacy_only 模式下 pipeline 热路径不拉起 base_router/能力链。

_LAZY_EXPORTS = {
    "Dispatcher": ("plugins.bot_unified_runtime.decision.dispatcher", "Dispatcher"),
    "ActionKind": ("plugins.bot_unified_runtime.decision.engine", "ActionKind"),
    "ActionPlan": ("plugins.bot_unified_runtime.decision.engine", "ActionPlan"),
    "ActionResolver": ("plugins.bot_unified_runtime.decision.engine", "ActionResolver"),
    "AbilitySpec": ("plugins.bot_unified_runtime.decision.engine", "AbilitySpec"),
    "BYPASS_ABILITIES": ("plugins.bot_unified_runtime.decision.engine", "BYPASS_ABILITIES"),
    "CentralDecisionEngine": ("plugins.bot_unified_runtime.decision.engine", "CentralDecisionEngine"),
    "DecisionContext": ("plugins.bot_unified_runtime.decision.engine", "DecisionContext"),
    "MUTUAL_GROUP_BYPASS": ("plugins.bot_unified_runtime.decision.engine", "MUTUAL_GROUP_BYPASS"),
    "MUTUAL_GROUP_NOTICE": ("plugins.bot_unified_runtime.decision.engine", "MUTUAL_GROUP_NOTICE"),
    "MUTUAL_GROUP_ROUTE": ("plugins.bot_unified_runtime.decision.engine", "MUTUAL_GROUP_ROUTE"),
    "AdapterSource": ("plugins.bot_unified_runtime.decision.ingress", "AdapterSource"),
    "EventKind": ("plugins.bot_unified_runtime.decision.ingress", "EventKind"),
    "OneBotSource": ("plugins.bot_unified_runtime.decision.ingress", "OneBotSource"),
    "TelegramSource": ("plugins.bot_unified_runtime.decision.ingress", "TelegramSource"),
    "DecisionStageRow": ("plugins.bot_unified_runtime.decision.trace", "DecisionStageRow"),
    "DecisionTrace": ("plugins.bot_unified_runtime.decision.trace", "DecisionTrace"),
    "DecisionTraceSink": ("plugins.bot_unified_runtime.decision.trace", "DecisionTraceSink"),
    "InMemoryDecisionTraceSink": (
        "plugins.bot_unified_runtime.decision.trace",
        "InMemoryDecisionTraceSink",
    ),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(target[0]), target[1])

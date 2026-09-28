"""Shadow 模式（B2 阶段 0）：引擎只记不发，与现行 matcher 并存比对。

规格：docs/design/central-decision-engine.md 迁移路径阶段 0——
``migration_mode``（键名 ``bot_decision_engine_mode``，默认 ``legacy_only``）：

- ``legacy_only``：引擎完全不参与（默认；对外行为逐字节不变）。
- ``shadow``：引擎对所有经过 RuntimePipeline 的事件只算 plan 并写
  DecisionTrace，与旧 matcher 的实际裁决（capability_id）做比对记录，
  **不产生任何发送、不改变任何回执**。
- ``engine_only``：随迁移阶段 1+ 启用；本阶段一律回落 ``legacy_only``
  （fail-closed，保证阶段 0 零行为变化）。

挂钩点：RuntimePipeline.handle/handle_async 入口（覆盖 A/B 两类 handler 的
全部 message 事件；C 类直连与 notice 类不经 pipeline，是本阶段影子覆盖的
已知边界，见任务报告）。全链 fail-open：影子观测的任何异常只降级为不观测。
"""

from __future__ import annotations

import logging
import os
import time

from plugins.bot_unified_runtime.domains.core.contracts import IncomingMessage
from plugins.bot_unified_runtime.domains.core.decision.trace import (
    DecisionTrace,
    get_decision_trace_sink,
)

logger = logging.getLogger(__name__)

DECISION_MODE_ENV = "BOT_DECISION_ENGINE_MODE"
DECISION_MODE_CONFIG_KEY = "bot_decision_engine_mode"
LEGACY_MODE = "legacy_only"
SHADOW_MODE = "shadow"
# engine_only 随迁移阶段 1+ 启用；阶段 0 一律回落 legacy_only。
RESERVED_FUTURE_MODES = {"engine_only"}
SUPPORTED_MODES = {LEGACY_MODE, SHADOW_MODE}

_UNAVAILABLE = object()

# 共享分类输入（与现行 matcher 同源：插件 Config + 昵称解析器各建一次，
# 同时保证 base_router 的 TTL-LRU 缓存按对象身份命中）。
_shared_config: object = _UNAVAILABLE
_shared_alias_resolver: object = _UNAVAILABLE
_engine: object = _UNAVAILABLE
_warned_modes: set[str] = set()


def normalize_decision_mode(raw: object) -> str:
    """非法/未启用模式一律回落 legacy_only（fail-closed，仅告警一次）。"""
    value = str(raw or "").strip().lower()
    if value in SUPPORTED_MODES:
        return value
    if value and value not in _warned_modes:
        _warned_modes.add(value)
        logger.warning(
            "bot_decision_engine_mode=%s is not available in phase-1 "
            "(engine_only activates in migration stage 1+); falling back to %s",
            value,
            LEGACY_MODE,
        )
    return LEGACY_MODE


def resolve_decision_mode() -> str:
    """模式解析链：nonebot driver config → 进程 env → 默认 legacy_only。

    与 pipeline._resolve_chat_pool_workers 同源模式；逐事件解析以便测试与
    运维热切（读配置是两次属性访问，无 IO）。
    """
    raw_values: list[object] = []
    try:
        import nonebot

        raw_values.append(
            getattr(nonebot.get_driver().config, DECISION_MODE_CONFIG_KEY, None)
        )
    except Exception:  # noqa: BLE001, S110 - 单测/裸脚本场景静默落到下一级。
        pass
    raw_values.append(os.environ.get(DECISION_MODE_ENV))
    for raw in raw_values:
        if raw is None:
            continue
        return normalize_decision_mode(raw)
    return LEGACY_MODE


def is_shadow_active() -> bool:
    return resolve_decision_mode() == SHADOW_MODE


def _shared_route_inputs() -> tuple[object, object]:
    """惰性构建共享 (config, alias_resolver)；失败降级为默认对象。

    config 失败时用普通 object()——classify_message_route 的所有开关走
    getattr 默认值（全开启），仍可完成纯函数分类。
    """
    global _shared_config, _shared_alias_resolver
    if _shared_config is _UNAVAILABLE:
        config: object
        try:
            import nonebot

            driver_config = nonebot.get_driver().config
            from plugins.bot_unified_runtime.config import Config, translate_env_keys

            config = Config.model_validate(translate_env_keys(driver_config.model_dump()))
        except Exception:  # noqa: BLE001 - 影子分类降级为默认开关，不影响主链路。
            config = object()
        _shared_config = config
    if _shared_alias_resolver is _UNAVAILABLE:
        alias: object
        try:
            from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
                build_command_alias_resolver,
            )

            alias = build_command_alias_resolver(_shared_config)
        except Exception:  # noqa: BLE001 - 无昵称解析时 alias 规则自然不命中。
            alias = None
        _shared_alias_resolver = alias
    return _shared_config, _shared_alias_resolver


def _get_engine():
    global _engine
    if _engine is _UNAVAILABLE:
        from plugins.bot_unified_runtime.domains.core.decision.engine import (
            CentralDecisionEngine,
        )

        _engine = CentralDecisionEngine()
    return _engine


def reset_shared_state_for_tests() -> None:
    """清空惰性单例（测试隔离用；生产路径不调用）。"""
    global _shared_config, _shared_alias_resolver, _engine
    _shared_config = _UNAVAILABLE
    _shared_alias_resolver = _UNAVAILABLE
    _engine = _UNAVAILABLE


# 影子比对：引擎 route 判定与旧路径实际 capability_id 的等价族。
# 数据来源：__init__.py 全部 pipeline 入口的 capability_id 字面量盘点
# （2026-09-12 grep）；不在表内的旧能力（旁路/管理面/直连流）记
# agree=None（不可比），不做猜测性映射。
_ROUTE_KIND_LEGACY_EQUIVALENTS: dict[str, frozenset[str]] = {
    "alias": frozenset({"bot.alias"}),
    "admin": frozenset({"bot.status", "bot.routes", "bot.route"}),
    "subscribe": frozenset({"bot.subscribe"}),
    "auto_send": frozenset({"bot.auto_send.preview"}),
    "meme": frozenset({"bot.meme"}),
    "meme_library": frozenset({"bot.meme_library"}),
    "music_mode": frozenset({"bot.music_mode"}),
    "music": frozenset({"bot.music"}),
    "today_history": frozenset({"bot.today_history"}),
    "wiki": frozenset({"bot.wiki"}),
    "moegirl": frozenset({"bot.moegirl"}),
    "moegirl_question": frozenset({"bot.moegirl"}),
    "epic": frozenset({"bot.epic"}),
    "weather": frozenset({"bot.weather"}),
    "market": frozenset({"bot.market"}),
    "news": frozenset({"bot.news"}),
    "randpic": frozenset({"bot.randpic"}),
    "reminder": frozenset({"bot.reminder"}),
    "eat": frozenset({"bot.eat"}),
    "affinity": frozenset({"bot.affinity"}),
    "divination": frozenset({"bot.divination"}),
    "natural_command": frozenset(),  # 与 target_capability_id 对比
    "content": frozenset({"bot.content", "bot.parse"}),
    "chat": frozenset({"bot.chat"}),
    "ignore": frozenset(),
}


_MODELED_LEGACY_CAPABILITIES = frozenset(
    {item for equivalents in _ROUTE_KIND_LEGACY_EQUIVALENTS.values() for item in equivalents}
)


def compare_with_legacy(plan, legacy_capability_id: str) -> tuple[bool | None, str]:
    """返回 (agree, note)；agree=None 表示旧能力未建模、不可比。

    agree=False 仅在"两侧都已建模但判定不同"时给出，保证 99% 一致率
    指标不被旁路/管理面等不可比事件稀释。
    """
    route = getattr(plan, "route", None)
    if route is None:
        return None, "plan_without_route"
    kind_value = str(getattr(route.kind, "value", route.kind))
    if kind_value not in _ROUTE_KIND_LEGACY_EQUIVALENTS:
        return None, f"unmodeled_route_kind:{kind_value}"
    expected = set(_ROUTE_KIND_LEGACY_EQUIVALENTS[kind_value])
    expected.add(str(plan.capability_id))
    target = getattr(route, "target_capability_id", None)
    if target:
        expected.add(str(target))
    if legacy_capability_id in expected:
        return True, ""
    if legacy_capability_id not in _MODELED_LEGACY_CAPABILITIES:
        return None, f"unmodeled_legacy_capability:{legacy_capability_id}"
    return False, f"expected={'|'.join(sorted(expected))}"


def observe_pipeline_event(message: IncomingMessage, legacy_capability_id: str) -> None:
    """shadow 挂钩入口：只算 plan、写 trace；绝不发送、绝不抛出。"""
    started = time.perf_counter()
    error = ""
    plan = None
    stages: tuple = ()
    try:
        from plugins.bot_unified_runtime.domains.core.decision.engine import (
            DecisionContext,
        )

        config, alias_resolver = _shared_route_inputs()
        engine = _get_engine()
        context = DecisionContext(
            message=message,
            event_kind="message",
            adapter_kind=str(message.adapter or ""),
            config=config,
            alias_resolver=alias_resolver,
        )
        plan, stages = engine.decide_with_trace(context)
    except Exception as exc:  # noqa: BLE001 - R3：decide 全链兜底，影子不反噬。
        error = f"{type(exc).__name__}: {exc}"[:200]
        logger.warning(
            "decision shadow decide failed type=%s detail=%s",
            type(exc).__name__,
            str(exc)[:120],
        )
    agree: bool | None = None
    compare_note = ""
    if plan is not None and not error:
        try:
            agree, compare_note = compare_with_legacy(plan, legacy_capability_id)
        except Exception as exc:  # noqa: BLE001 - 比对失败只降级记录。
            agree, compare_note = None, f"compare_error:{type(exc).__name__}"
    route = getattr(plan, "route", None)
    plan_action = plan.action.value if plan is not None else ""
    route_kind = route.kind.value if route is not None else ""
    route_priority = route.priority if route is not None else None
    try:
        get_decision_trace_sink().record(
            DecisionTrace(
                trace_id=plan.trace_id if plan is not None else "",
                request_id=message.request_id,
                mode=SHADOW_MODE,
                origin="pipeline_hook",
                plan_action=plan_action,
                plan_capability_id=plan.capability_id if plan is not None else "",
                plan_reason=plan.reason if plan is not None else "",
                route_kind=route_kind,
                route_priority=route_priority,
                legacy_capability_id=legacy_capability_id,
                agree=agree,
                compare_note=compare_note,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                error=error,
                stages=stages,
            )
        )
    except Exception:  # noqa: BLE001, S110 - trace 落点失败只降级为不记录。
        pass

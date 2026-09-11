"""CentralDecisionEngine（B2 阶段 0）：引擎骨架与决策链。

规格：docs/design/central-decision-engine.md §2.2/§2.3.2/§2.3.4。

阶段 0 边界（零行为变化）：
- 引擎与现行 35 matcher 并存；``decide()`` 是纯函数裁决（单次执行、单输出），
  绝不发送、绝不 claim 幂等、绝不改写任何契约。
- 决策链顺序固定：NoticeGate → MuteGate → IdempotencyGate → Router →
  AudienceGate → ActionResolver；每一环产出 DecisionStageRow。
- Router 原样复用 ``runtime/base_router.classify_message_route``（ROUTE_RULES
  与其 TTL-LRU 缓存不动），并把 ``_is_plain_chat_event`` 的纯媒体/转发放行
  chat 特例（规格阶段 0 验收 1 注明的已建模边缘）纳入建模。
- MuteGate/IdempotencyGate/AudienceGate 在 shadow 语境下只记录
  ``allowed=None``（移交现行 pipeline 判定）；幂等按规格 §2.3.4 由
  pipeline 独占，引擎不重复 claim。
- 互斥组语义（规格 §2.3.2）：同组按 priority 第一个命中者胜；跨组默认互斥
  （一个事件一个 plan）；``allow_parallel=True`` 的旁路型能力（meme_absorb /
  dirty_guard）命中不终结决策、不允许产生业务回复。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from plugins.bot_unified_runtime.contracts import IncomingMessage, RiskLevel
from plugins.bot_unified_runtime.decision.trace import DecisionStageRow, new_trace_id
from plugins.bot_unified_runtime.runtime.base_router import (
    ROUTE_RULES,
    RouteDecision,
    RouteKind,
    classify_message_route,
    extract_http_urls,
)

# classify_message_route 的 route 缓存按 config 对象身份命中；未注入真实
# 配置（单测/裸引擎）时统一复用同一默认对象，保证缓存语义不变。
DEFAULT_ROUTE_CONFIG = object()

EventKind = Literal["message", "notice", "request", "meta"]


class ActionKind(str, Enum):
    """ActionPlan 动作类别（规格 §2.2 目标拓扑）。"""

    REPLY_TEXT = "reply_text"
    REPLY_CARD = "reply_card"
    NOTICE_ACTION = "notice_action"
    FILE_INBOUND = "file_inbound"
    FILE_OUTBOUND = "file_outbound"
    PASSIVE_ABSORB = "passive_absorb"
    SILENT = "silent"
    BLOCKED = "blocked"


MUTUAL_GROUP_ROUTE = "route"
MUTUAL_GROUP_NOTICE = "notice"
MUTUAL_GROUP_BYPASS = "bypass"


@dataclass(frozen=True)
class ActionPlan:
    """引擎唯一输出（规格 §2.3.2 接口草案）。"""

    action: ActionKind
    capability_id: str
    route: RouteDecision | None
    mutual_group: str
    risk_level: RiskLevel
    priority: int
    reason: str
    trace_id: str
    deadline_monotonic: float | None = None
    # 旁路型能力命中不终结决策（规格 §2.3.2 互斥组语义）。
    allow_parallel: bool = False


@dataclass(frozen=True)
class AbilitySpec:
    """旁路/通知类能力的解析规格（迁移阶段 1 起逐能力扩表）。"""

    action: ActionKind
    mutual_group: str
    priority: int
    risk_level: RiskLevel = RiskLevel.LOW
    allow_parallel: bool = False


# 旁路型能力注册表（规格 §2.3.2：meme_absorb / dirty_guard 命中不终结）。
# priority 取自现行 matcher 优先级（meme_absorb p=10、dirty_guard p=3）。
BYPASS_ABILITIES: dict[str, AbilitySpec] = {
    "bot.meme_absorb": AbilitySpec(
        ActionKind.PASSIVE_ABSORB, MUTUAL_GROUP_BYPASS, 10, RiskLevel.LOW, True
    ),
    "bot.dirty_guard": AbilitySpec(
        ActionKind.NOTICE_ACTION, MUTUAL_GROUP_BYPASS, 3, RiskLevel.MEDIUM, True
    ),
}


@dataclass(frozen=True)
class DecisionContext:
    """引擎输入：IncomingMessage + 事件分类预判所需的最小上下文。"""

    message: IncomingMessage
    event_kind: EventKind = "message"
    adapter_kind: str = ""
    # 分类用配置与昵称解析器：由影子入口注入（与现行 matcher 同源）；
    # None 时引擎用共享默认对象（所有开关走 getattr 默认值）。
    config: Any = None
    alias_resolver: Any = None
    # 旧路径声明的旁路能力 id（meme_absorb/dirty_guard）；空=无旁路。
    bypass_capability_id: str = ""
    deadline_monotonic: float | None = None


class ActionResolver:
    """RouteKind/能力 → ActionPlan，并承担互斥组裁决（规则 5/9）。"""

    def __init__(
        self,
        bypass_abilities: dict[str, AbilitySpec] | None = None,
    ) -> None:
        self._bypass_abilities = dict(bypass_abilities or BYPASS_ABILITIES)

    def plan_for_bypass(self, capability_id: str, *, trace_id: str) -> ActionPlan | None:
        spec = self._bypass_abilities.get(capability_id)
        if spec is None:
            return None
        return ActionPlan(
            action=spec.action,
            capability_id=capability_id,
            route=None,
            mutual_group=spec.mutual_group,
            risk_level=spec.risk_level,
            priority=spec.priority,
            reason=f"旁路型能力（{capability_id}）命中不终结决策",
            trace_id=trace_id,
            allow_parallel=spec.allow_parallel,
        )

    def plan_for_route(self, route: RouteDecision, *, trace_id: str) -> ActionPlan:
        if route.kind is RouteKind.IGNORE:
            return ActionPlan(
                action=ActionKind.SILENT,
                capability_id=route.capability_id,
                route=route,
                mutual_group=MUTUAL_GROUP_ROUTE,
                risk_level=RiskLevel.LOW,
                priority=route.priority,
                reason=route.reason or "路由未命中，判定不回复",
                trace_id=trace_id,
            )
        return ActionPlan(
            action=ActionKind.REPLY_TEXT,
            capability_id=route.capability_id,
            route=route,
            mutual_group=MUTUAL_GROUP_ROUTE,
            risk_level=RiskLevel.LOW,
            priority=route.priority,
            reason=route.reason,
            trace_id=trace_id,
        )

    def resolve(self, candidates: Sequence[ActionPlan]) -> ActionPlan:
        """互斥组裁决：同组按 priority 第一个命中者胜；跨组默认互斥。

        ``allow_parallel=True`` 的旁路型 plan 永不成为最终 plan（它们命中后
        不终结决策、不允许产生业务回复）；全旁路时取优先级最高（数值最小）
        的旁路 plan 以保证"单事件单 plan"。
        """
        if not candidates:
            raise ValueError("action resolver requires at least one candidate")
        ordered = sorted(
            enumerate(candidates), key=lambda pair: (pair[1].priority, pair[0])
        )
        for _index, plan in ordered:
            if not plan.allow_parallel:
                return plan
        return ordered[0][1]


class CentralDecisionEngine:
    """单入口、单次分类、单一 ActionPlan 的决策核心（阶段 0 骨架）。"""

    def __init__(
        self,
        *,
        route_rules: Any = None,
        resolver: ActionResolver | None = None,
    ) -> None:
        # route_rules 目前仅作占位注入点：分类函数读全局 ROUTE_RULES
        # （规格 §2.3.2：ROUTE_RULES 原样复用）；显式传入可自检一致性。
        self.route_rules = list(route_rules or ROUTE_RULES)
        self.resolver = resolver or ActionResolver()

    # 规格接口草案：decide(ctx) -> ActionPlan
    def decide(self, ctx: DecisionContext) -> ActionPlan:
        return self.decide_with_trace(ctx)[0]

    def decide_with_trace(
        self, ctx: DecisionContext
    ) -> tuple[ActionPlan, tuple[DecisionStageRow, ...]]:
        stages: list[DecisionStageRow] = []
        trace_id = new_trace_id()
        config = ctx.config if ctx.config is not None else DEFAULT_ROUTE_CONFIG

        # ① NoticeGate：通知/请求类事件分流（迁移阶段 1 起接 NoticeExecutor）。
        started = time.perf_counter()
        if ctx.event_kind != "message":
            stages.append(
                DecisionStageRow(
                    stage="notice_gate",
                    kind=ActionKind.NOTICE_ACTION.value,
                    allowed=True,
                    reason=f"event_kind={ctx.event_kind} 走通知通道",
                    ms=_elapsed_ms(started),
                )
            )
            plan = ActionPlan(
                action=ActionKind.NOTICE_ACTION,
                capability_id="bot.notice",
                route=None,
                mutual_group=MUTUAL_GROUP_NOTICE,
                risk_level=RiskLevel.LOW,
                priority=6,
                reason=f"通知类事件（{ctx.event_kind}）由 NoticeGate 分流",
                trace_id=trace_id,
            )
            return plan, tuple(stages)
        stages.append(
            DecisionStageRow(
                stage="notice_gate",
                kind="pass",
                allowed=True,
                reason="message 事件继续路由链",
                ms=_elapsed_ms(started),
            )
        )

        # ② MuteGate：全局暂停/运行时开关——影子模式下移交现行 pipeline。
        started = time.perf_counter()
        stages.append(
            DecisionStageRow(
                stage="mute_gate",
                kind="deferred",
                allowed=None,
                reason="shadow: 全局暂停/开关由现行 RuntimePipeline 判定",
                ms=_elapsed_ms(started),
            )
        )

        # ③ IdempotencyGate：规格 §2.3.4——pipeline._claim_event 独占，引擎
        # 绝不重复 claim（防双表语义漂移）。
        started = time.perf_counter()
        stages.append(
            DecisionStageRow(
                stage="idempotency_gate",
                kind="deferred",
                allowed=None,
                reason="shadow: 幂等由 pipeline._claim_event 独占，引擎不 claim",
                ms=_elapsed_ms(started),
            )
        )

        # ④ Router：ROUTE_RULES 确定性分类（单次分类，含媒体/链接边缘建模）。
        started = time.perf_counter()
        route = self._classify(ctx, config)
        stages.append(
            DecisionStageRow(
                stage="router",
                kind=route.kind.value,
                allowed=True,
                reason=route.reason,
                ms=_elapsed_ms(started),
            )
        )

        # ⑤ AudienceGate：群黑白名单/触发门禁——影子模式下移交现行 pipeline。
        started = time.perf_counter()
        stages.append(
            DecisionStageRow(
                stage="audience_gate",
                kind="deferred",
                allowed=None,
                reason="shadow: 群黑白名单/触发门禁由现行 pipeline policy 判定",
                ms=_elapsed_ms(started),
            )
        )

        # ⑥ ActionResolver：互斥组裁决，产出唯一 ActionPlan。
        started = time.perf_counter()
        candidates: list[ActionPlan] = []
        bypass_plan = self.resolver.plan_for_bypass(
            ctx.bypass_capability_id, trace_id=trace_id
        )
        if bypass_plan is not None:
            candidates.append(bypass_plan)
        candidates.append(self.resolver.plan_for_route(route, trace_id=trace_id))
        plan = self.resolver.resolve(candidates)
        stages.append(
            DecisionStageRow(
                stage="action_resolver",
                kind=plan.action.value,
                allowed=True,
                reason=plan.reason,
                ms=_elapsed_ms(started),
            )
        )
        return plan, tuple(stages)

    def _classify(self, ctx: DecisionContext, config: Any) -> RouteDecision:
        """对齐现行 matcher 结果的分类：链接解析吃 effective 文本（含
        消息段 URL），纯媒体/转发放行 chat（_is_plain_chat_event 特例）。"""
        text = (ctx.message.plain_text or "").strip()
        decision = classify_message_route(
            text, config=config, alias_resolver=ctx.alias_resolver
        )
        urls = _urls_from_segments(ctx.message.raw_segments)
        # 链接解析（p=46）在 chat（p=50）之前且用 effective 文本：plain 未命中
        # 或命中优先级低于 46 时，URL 命中 CONTENT 应获胜（与 block 语义一致）。
        if (
            urls
            and (decision.kind is RouteKind.IGNORE or decision.priority > 46)
        ):
            effective_text = f"{text} {' '.join(urls)}".strip()
            effective = classify_message_route(
                effective_text, config=config, alias_resolver=ctx.alias_resolver
            )
            if effective.kind is RouteKind.CONTENT:
                decision = effective
        # 纯媒体/转发消息的 plain_text 往往为空（被判 IGNORE）；现行 chat 规则
        # 对 visual/audio/forward 放行（视觉理解/ASR/转发正文依赖此路径）。
        if (
            decision.kind is RouteKind.IGNORE
            and _has_media_segments(ctx.message.raw_segments)
            and getattr(config, "bot_chat_enabled", True)
        ):
            decision = RouteDecision(
                RouteKind.CHAT,
                "bot.chat",
                50,
                "纯媒体/转发消息放行聊天链路（_is_plain_chat_event 特例）",
                ("decision:media_chat_bypass",),
            )
        return decision


_MEDIA_SEGMENT_TYPES = {"image", "record", "video", "forward"}
_URL_SEGMENT_TYPES = {"json", "xml", "share", "app", "card", "markdown"}
_URL_SEGMENT_KEYS = ("data", "content", "url", "meta", "text")


def _has_media_segments(raw_segments: Any) -> bool:
    for segment in raw_segments or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).lower() in _MEDIA_SEGMENT_TYPES:
            return True
    return False


def _urls_from_segments(raw_segments: Any) -> list[str]:
    """从文本/卡片(json/xml/app)消息段提取 URL（对齐
    ``__init__._urls_from_message_segments`` 的段型覆盖）。"""
    import json as _json

    urls: list[str] = []
    for segment in raw_segments or []:
        if not isinstance(segment, dict):
            continue
        segment_type = str(segment.get("type", "")).lower()
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            continue
        text = ""
        if segment_type == "text":
            text = str(data.get("text", ""))
        elif segment_type in _URL_SEGMENT_TYPES:
            for key in _URL_SEGMENT_KEYS:
                raw_value = data.get(key)
                if isinstance(raw_value, dict):
                    raw_value = _json.dumps(raw_value, ensure_ascii=False)
                if isinstance(raw_value, str):
                    text += raw_value + " "
        for url in extract_http_urls(text):
            if url not in urls:
                urls.append(url)
    return urls


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0

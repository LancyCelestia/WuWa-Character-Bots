"""中央事件分发门面：所有输入统一进入能力、审查、渲染和出站端口。

V21-DISPATCH-001（风险 5 收口）：本模块新增统一出站副作用执行器
:class:`OutboundSideEffectExecutor` 与门面装配器
:func:`build_interaction_dispatcher`——回戳/贴表情等平台副作用的唯一执行面
（OutboundIntent → 准入复验 → 许可租约线性化 → Transport 固定映射 →
``bot.call_api`` 通道本体）。依赖仅 stdlib + ``decision.outbound``
（零 nonebot / 零网络 / 零配置），保持本包顶层的轻导入纪律。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from plugins.bot_unified_runtime.domains.core.decision.outbound import (
    AdmissionDenied,
    DuplicateClaim,
    OutboundAdmissionGate,
    OutboundIntent,
    TransportChannel,
    TransportPlatform,
    TransportRegistry,
    UnregisteredTransportError,
    build_default_transport_registry,
)


@dataclass(frozen=True)
class DispatchResult:
    status: str
    trace_id: str
    capability_id: str | None = None
    receipt_id: str | None = None
    details: dict[str, Any] | None = None


class Dispatcher:
    def __init__(
        self,
        *,
        route: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        review: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> None:
        self.route, self.review, self.send = route, review, send

    async def dispatch(self, event: dict[str, Any]) -> DispatchResult:
        trace_id = str(
            event.get("trace_id") or "trace_" + __import__("uuid").uuid4().hex
        )
        routed = await self.route(event | {"trace_id": trace_id})
        reviewed = await self.review(routed | {"trace_id": trace_id})
        if reviewed.get("send") is False:
            return DispatchResult(
                "review_blocked",
                trace_id,
                reviewed.get("capability_id"),
                details={"reason": reviewed.get("reason", "policy")},
            )
        receipt = await self.send(reviewed | {"trace_id": trace_id})
        return DispatchResult(
            str(receipt.get("status", "unknown")),
            trace_id,
            reviewed.get("capability_id"),
            receipt.get("receipt_id"),
            receipt,
        )


class PokeInteractionService:
    def __init__(self, dispatch: Dispatcher) -> None:
        self.dispatcher = dispatch

    async def handle(self, event: dict[str, Any]) -> DispatchResult:
        return await self.dispatcher.dispatch(
            event | {"capability_id": "interaction.poke"}
        )


class ReactionService:
    def __init__(self, dispatch: Dispatcher) -> None:
        self.dispatcher = dispatch

    async def handle(self, event: dict[str, Any]) -> DispatchResult:
        return await self.dispatcher.dispatch(
            event | {"capability_id": "interaction.reaction"}
        )


class MemeService:
    def __init__(self, dispatch: Dispatcher) -> None:
        self.dispatcher = dispatch

    async def generate_and_send(self, event: dict[str, Any]) -> DispatchResult:
        return await self.dispatcher.dispatch(event | {"capability_id": "media.meme"})


# ---------------------------------------------------------------------------
# 统一出站副作用执行器（V21-DISPATCH-001 / 风险 5 收口）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SideEffectReceipt:
    """一次平台副作用出站的回执（诚实面：不撒谎、不返回半个发送）。"""

    delivered: bool
    status: str
    reason: str = ""
    method: str = ""

    def as_send_result(self) -> dict[str, Any]:
        """门面 send 端口形态（status/receipt_id 供 DispatchResult 消费）。"""
        return {
            "status": self.status,
            "receipt_id": "",
            "delivered": self.delivered,
            "reason": self.reason,
            "method": self.method,
        }


class OutboundSideEffectExecutor:
    """统一出站副作用执行器：回戳/贴表情等平台副作用的唯一执行面。

    链路（V2.1 §10 逐条落点）：

    1. ``cancel_requested`` 前置闸——带取消标记的意图**绝不派发也绝不报成功**
       （取消在途不假成功）；
    2. ``OutboundAdmissionGate.admit``——发送前复验（过期/部件态/操作态）；
    3. ``PermitLease.acquire``——线性化点：同 dedupe_key 在途二次申请
       DuplicateClaim 拒绝（并发双事件不双发）；
    4. ``mark_irreversible``——真实平台调用前标记（此后不可承诺撤回）；
    5. ``TransportRegistry`` 固定映射解析平台方法名（**绝不拼接合成 API 名**；
       TG POKE 有意未注册 → 显式 UnregisteredTransportError）；
    6. ``bot.call_api(方法名, **params)``——与 SendQueue worker 同一通道本体，
       不新建第二出站通道；
    7. finally 释放租约（在途即用即还；顺序性重复事件——用户连续戳两下——
       天然放行，永久幂等归各能力自有门所有，不在此双管）。

    平台调用失败诚实落回执（status="failed"），绝不向调用方抛半个发送。
    """

    def __init__(
        self,
        *,
        transport_registry: TransportRegistry | None = None,
        admission_gate: OutboundAdmissionGate | None = None,
        lease: Any | None = None,
        bot_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.transport_registry = transport_registry or build_default_transport_registry()
        self.admission_gate = admission_gate or OutboundAdmissionGate()
        # PermitLease 不在轻导入面强引（类型以鸭子协议表述），运行期用真身。
        from plugins.bot_unified_runtime.domains.core.decision.outbound import (
            PermitLease,
        )

        self.lease = lease if lease is not None else PermitLease()
        self._bot_provider = bot_provider

    async def execute(
        self,
        intent: OutboundIntent,
        *,
        bot: Any = None,
    ) -> SideEffectReceipt:
        target_bot = bot if bot is not None else (
            self._bot_provider() if self._bot_provider is not None else None
        )
        if target_bot is None:
            return SideEffectReceipt(
                False, "no_channel", reason="no bot bound for platform call",
            )
        if intent.cancel_requested:
            return SideEffectReceipt(
                False, "cancelled", reason="cancel_requested_before_dispatch",
            )
        try:
            self.admission_gate.admit(intent)
        except AdmissionDenied as exc:
            verdict = exc.verdict
            return SideEffectReceipt(
                False,
                "admission_denied",
                reason=f"{verdict.check_name}:{verdict.reason_code}",
            )
        try:
            token = self.lease.acquire(intent.dedupe_key, holder="outbound.side_effect")
        except DuplicateClaim as exc:
            return SideEffectReceipt(
                False, "duplicate_claim", reason=f"held_by={exc.holder}",
            )
        token = self.lease.mark_irreversible(token)
        receipt: SideEffectReceipt
        try:
            method = self._resolve_method(intent)
            part = intent.parts[0]
            params = dict(getattr(part, "content_ref", {}).get("api_params") or {})
            await target_bot.call_api(method, **params)
        except UnregisteredTransportError as exc:
            receipt = SideEffectReceipt(False, "unregistered_transport", reason=str(exc))
        except ValueError as exc:  # 未登记平台名/通道名：显式拒绝，绝不合成。
            receipt = SideEffectReceipt(False, "unregistered_platform", reason=str(exc))
        except Exception as exc:  # noqa: BLE001 - 平台拒绝/不支持：诚实回执。
            receipt = SideEffectReceipt(
                False, "failed", method=method, reason=type(exc).__name__,
            )
        else:
            receipt = SideEffectReceipt(True, "delivered", method=method)
        finally:
            self.lease.release(token)
        return receipt

    def _resolve_method(self, intent: OutboundIntent) -> str:
        """Transport 固定映射：平台 × 通道 → 显式登记的平台方法名。"""
        platform = TransportPlatform(intent.target.platform)
        channel = TransportChannel[intent.operation.name]
        entry = self.transport_registry.resolve(platform, channel)
        return entry.platform_method_for(str(intent.target.session_type))


def build_interaction_dispatcher(
    executor: OutboundSideEffectExecutor,
    *,
    route_intent: Callable[[dict[str, Any]], OutboundIntent],
    review: Callable[[dict[str, Any]], bool] | None = None,
) -> Dispatcher:
    """把统一出站执行器装配成中央门面 :class:`Dispatcher`（真实派发周期）。

    - route：payload → OutboundIntent（严格 DTO 校验即路由产物，坏载荷在此暴露）；
    - review：形态复验（意图存在 + 未带取消标记 + 可选自定义门），False=review_blocked；
    - send：统一出站执行器执行，回执落 status/receipt_id（DispatchResult 消费面）。
    """

    async def _route(payload: dict[str, Any]) -> dict[str, Any]:
        return payload | {"outbound_intent": route_intent(payload)}

    async def _review(routed: dict[str, Any]) -> dict[str, Any]:
        intent = routed.get("outbound_intent")
        ok = isinstance(intent, OutboundIntent) and not intent.cancel_requested
        if ok and review is not None:
            ok = bool(review(routed))
        if not ok:
            return routed | {"send": False, "reason": "policy"}
        return routed | {"send": True}

    async def _send(reviewed: dict[str, Any]) -> dict[str, Any]:
        receipt = await executor.execute(
            reviewed["outbound_intent"], bot=reviewed.get("bot"),
        )
        return receipt.as_send_result()

    return Dispatcher(route=_route, review=_review, send=_send)

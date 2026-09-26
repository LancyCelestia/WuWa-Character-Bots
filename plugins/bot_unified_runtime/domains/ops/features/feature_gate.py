"""能力开关执行门：注入 Pipeline，查询故障时不执行能力。"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from plugins.bot_unified_runtime.control_plane.services import FeatureControlService
from plugins.bot_unified_runtime.domains.core.contracts import IncomingMessage
from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
    RECOVERY_CAPABILITIES,
    capability_feature_bindings,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeatureAccess:
    allowed: bool
    reason: str
    feature_id: str | None = None
    graph_revision: int | None = None


@dataclass(frozen=True)
class FeatureSwitchSnapshot:
    states: Mapping[str, bool]
    graph_revision: int | None
    available: bool = True

    def enabled(self, feature_id: str) -> bool:
        return self.available and self.states.get(feature_id, False)


class ProductFeatureGate:
    """产品功能门。语义（有意设计，非遗漏）：

    - 登记且开启 → 放行；登记且关闭 → 拒绝（feature_disabled）；
    - **未登记 → 拒绝（feature_unregistered）**，且每 id 产出一条 WARNING 告警
      （F3/审计 U3-01：不得零日志静默吞出站文案）。

    「使用即登记」是不变量：capability_id 一旦被统一管线消费，必须出现在
    注册册（domains/chat_reply/runtime/capability_registry.py）投影的绑定表里。
    """

    # 进程级去重账：热路径每个未登记 id 只警告一次，防刷屏又不失明。
    _unregistered_warned: ClassVar[set[str]] = set()

    def __init__(self, service: FeatureControlService) -> None:
        self.service = service
        self.bindings = capability_feature_bindings()

    @classmethod
    def reset_unregistered_warnings(cls) -> None:
        """清空未登记告警去重账（测试用；生产无需调用）。"""
        cls._unregistered_warned.clear()

    @classmethod
    def _warn_unregistered(cls, capability_id: str) -> None:
        if capability_id in cls._unregistered_warned:
            return
        cls._unregistered_warned.add(capability_id)
        logger.warning(
            "功能门拒绝未登记的 capability_id=%r（fail-closed）：该能力的出站文案会被"
            "「这项功能暂时不可用。」替代。请把它登记进注册册 "
            "domains/chat_reply/runtime/capability_registry.py 的 "
            "CONTROLLED_INTERNAL_CAPABILITIES，或修正调用点的 capability_id；"
            "门语义见 docs/design/control-plane-registry.md。",
            capability_id,
        )

    def snapshot(self) -> FeatureSwitchSnapshot:
        try:
            states = self.service.state_snapshot()
            return FeatureSwitchSnapshot(
                MappingProxyType({row.feature_id: row.effective_enabled for row in states}),
                states[0].graph_revision if states else None,
            )
        except Exception:  # noqa: BLE001 - 预处理旁路也必须故障关闭，不暴露底层异常。
            return FeatureSwitchSnapshot(MappingProxyType({}), None, available=False)

    async def snapshot_async(self) -> FeatureSwitchSnapshot:
        return await asyncio.to_thread(self.snapshot)

    def __call__(self, message: IncomingMessage, capability_id: str) -> FeatureAccess:
        # 判定**全文不读 message**（历史签名带它，真身只用 capability_id）。层 2
        # （``CapabilityInvoker``）拿不到 IncomingMessage，因此经 ``check_capability``
        # 复用同一真身，而不是抄第二份门序。谁要往这里加 message 依赖，必须同时把
        # 层 2 的谓词形参改掉——由
        # ``tests/test_feature_gate_layer2.py::test_call_is_pure_forward`` 锁死。
        return self.check_capability(capability_id)

    def check_capability(self, capability_id: str) -> FeatureAccess:
        """capability_id → 放行判定（层 1 与层 2 共用的唯一真身）。"""
        # 控制恢复仍走后续 Role/Policy；这里只保证故障时仍可诊断/恢复。
        if capability_id in RECOVERY_CAPABILITIES:
            return FeatureAccess(True, "protected_recovery")
        feature_id = self.bindings.get(capability_id)
        if feature_id is None:
            self._warn_unregistered(capability_id)
            return FeatureAccess(False, "feature_unregistered")
        state = self.service.detail(feature_id)["state"]
        enabled = bool(state["effective_enabled"])
        return FeatureAccess(enabled, "enabled" if enabled else "feature_disabled", feature_id, state.get("graph_revision"))

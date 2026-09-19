"""reserved: creation 生成域（第 20 域，预留态）——唯一入口与能力注册面。

`reserved: 依赖外部 provider 配置，未实现`。本包是 v21r2-reorg-plan.md §9.1
预留态第 20 域：现载体 capabilities/tts.py 留 media 域原映射不动（归属裁决
§10 W-PA2）；绘图零载体（矩阵 L52）。本模块只提供 §9.3「注册表开放条目 +
新功能四步接入」的**注册面**（纯内存、零 I/O、零配置读取），未注册能力不可
实例化，已注册未过四步（注册→协议→门禁→投影）的能力被 dormant 门挡住，
禁止冒充已生效（扩展 §9.2 L299）。

占位纪律：禁 import 副作用、禁网络、禁读生产配置（§9.4 契约形态 lint）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ._common.contracts import CreationContractBase, CreationJobState

if TYPE_CHECKING:  # 投影期类型提示：叶子契约经 PEP 562 惰性转发
    from .image.contracts import ImageJobRequest
    from .tts.contracts import TTSJobRequest

# ---------------------------------------------------------------------------
# 注册面：开放条目与四步接入（§9.3）
# ---------------------------------------------------------------------------

#: extensions 起步开放的节点类（ProductManifest 16 类节点切片，指南 §5 L124）。
REGISTRY_OPEN_NODE_KINDS: tuple[str, ...] = (
    "feature",
    "sub_feature",
    "command",
    "help",
    "scheduled_job",
    "control_action",
    "config",
)

#: 新功能四步接入（§9.3）：注册→协议→门禁 dormant→投影。
STEP_REGISTERED = 1
STEP_PROTOCOL = 2
STEP_GATED = 3
STEP_PROJECTED = 4

CreationCapabilityKind = Literal["tts", "image", "extensions"]

#: manifest 节点必填字段（指南 §5 L126；预留态条目允许留空，但必须如实报
#: 「距可登记还缺什么」，见 manifest_registration_blockers）。
NODE_REQUIRED_FIELDS: tuple[str, ...] = (
    "stable_id",
    "parent_id",
    "kind",
    "label",
    "aliases",
    "implementation_ref",
    "capability_id",
    "route_kind",
    "default_enabled",
    "reload_strategy",
    "dependencies",
    "required_roles",
    "config_keys",
    "documentation_refs",
    "privacy_level",
    "protected",
    "version",
)


class UnregisteredCapabilityError(LookupError):
    """未注册能力：不可实例化（§9.3 注册面第一道门）。"""


class CapabilityGateClosedError(RuntimeError):
    """已注册但四步未走完（dormant）：禁止实例化、禁止冒充已生效。"""


class CapabilityNotImplementedError(RuntimeError):
    """已注册已过门但无工厂：reserved 纪律（协议≠可用，矩阵 L101）。"""


class CreationCapabilityEntry(CreationContractBase):
    """注册表条目（manifest 节点的 creation 域预留态切片）。

    - ``default_enabled`` 钉死 False：对预留/新功能一律 false（§9.3）；
    - ``gate_state`` 钉死 "dormant"：预留态条目不得宣称 enabled；
    - ``contract_dto``：tts/image 必须挂 §9.1 契约 DTO；extensions 槽可为空。
    """

    stable_id: str = Field(min_length=3, max_length=128, pattern=r"^[a-z0-9]+(\.[a-z0-9_]+)+$")
    kind: CreationCapabilityKind
    label: str = Field(min_length=1, max_length=128)
    contract_dto: type[BaseModel] | None = None
    default_enabled: Literal[False] = False
    gate_state: Literal["dormant"] = "dormant"
    integration_step: int = Field(default=STEP_REGISTERED, ge=STEP_REGISTERED, le=STEP_PROJECTED)
    projection_complete: bool = False
    parent_id: str = Field(default="", max_length=128)
    implementation_ref: str = Field(default="", max_length=256)
    capability_id: str = Field(default="", max_length=128)
    route_kind: str = Field(default="", max_length=64)
    config_keys: tuple[str, ...] = Field(default=())
    documentation_refs: tuple[str, ...] = Field(default=())
    privacy_level: str = Field(default="standard", max_length=32)
    protected: bool = False
    version: str = Field(default="0.0.0-reserved", max_length=32)

    @model_validator(mode="after")
    def _kind_dto_gate(self) -> CreationCapabilityEntry:
        # 四步阶梯语义：step1(注册) 允许暂无契约 DTO（占位条目形态）；
        # step2(协议) 起 tts/image 必须挂 §9.1 契约 DTO。
        if (
            self.kind in ("tts", "image")
            and self.contract_dto is None
            and self.integration_step >= STEP_PROTOCOL
        ):
            raise ValueError(f"kind={self.kind} 的条目进入协议步起必须挂 §9.1 契约 DTO")
        if self.kind == "extensions" and self.contract_dto is not None:
            raise ValueError("extensions 槽条目不挂任务契约 DTO（子功能立项时再挂）")
        if self.projection_complete and self.integration_step < STEP_PROJECTED:
            raise ValueError("projection_complete=True 必须 integration_step=4（投影完成）")
        return self

    @field_validator("stable_id")
    @classmethod
    def _id_prefix_matches_kind(cls, value: str) -> str:
        if not value.startswith("creation."):
            raise ValueError("creation 域条目 stable_id 必须 creation. 前缀")
        return value


def manifest_registration_blockers(entry: CreationCapabilityEntry) -> tuple[str, ...]:
    """如实列出距 manifest 正式登记仍缺的必填字段（禁冒充已生效）。"""
    missing: list[str] = []
    if not entry.parent_id:
        missing.append("parent_id")
    if not entry.implementation_ref:
        missing.append("implementation_ref")
    if not entry.capability_id:
        missing.append("capability_id")
    if not entry.route_kind:
        missing.append("route_kind")
    if not entry.documentation_refs:
        missing.append("documentation_refs")
    if entry.version == "0.0.0-reserved":
        missing.append("version")
    return tuple(missing)


class CreationCapabilityRegistry:
    """纯内存注册面：register→resolve→instantiate；未注册不可实例化。

    实例化三道门（§9.3 四步接入的机器形态）：
    1. 未注册 → UnregisteredCapabilityError；
    2. 四步未走完（integration_step<4 或 projection 未完成）→
       CapabilityGateClosedError（dormant，禁止冒充已生效）；
    3. 无工厂 → CapabilityNotImplementedError（reserved：协议≠可用）。
    """

    def __init__(self) -> None:
        self._entries: dict[str, CreationCapabilityEntry] = {}
        self._factories: dict[str, Callable[[BaseModel], object]] = {}

    def register(
        self,
        entry: CreationCapabilityEntry,
        factory: Callable[[BaseModel], object] | None = None,
    ) -> None:
        if entry.stable_id in self._entries:
            raise ValueError(f"stable_id 重复注册: {entry.stable_id}")
        self._entries[entry.stable_id] = entry
        if factory is not None:
            self._factories[entry.stable_id] = factory

    def get(self, stable_id: str) -> CreationCapabilityEntry | None:
        return self._entries.get(stable_id)

    def entries(self) -> tuple[CreationCapabilityEntry, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))

    def instantiate(self, stable_id: str, payload: BaseModel) -> object:
        entry = self._entries.get(stable_id)
        if entry is None:
            raise UnregisteredCapabilityError(f"能力未注册，禁止实例化: {stable_id!r}")
        if entry.integration_step < STEP_PROJECTED or not entry.projection_complete:
            raise CapabilityGateClosedError(
                f"{stable_id!r} 处于 dormant（四步接入未完成："
                f"step={entry.integration_step}），禁止实例化"
            )
        factory = self._factories.get(stable_id)
        if factory is None:
            raise CapabilityNotImplementedError(
                f"{stable_id!r} 已过门但无实现工厂（reserved: 协议≠可用）"
            )
        if type(payload) is not entry.contract_dto:
            raise TypeError(
                f"{stable_id!r} 契约不匹配：期望 {entry.contract_dto}, 收到 {type(payload)}"
            )
        return factory(payload)


def _reserved_entry(
    stable_id: str, kind: CreationCapabilityKind, label: str
) -> CreationCapabilityEntry:
    return CreationCapabilityEntry(stable_id=stable_id, kind=kind, label=label)


#: 预留态默认注册面：三条 dormant 条目与占位目录一一对应（§9.4 一致性）。
RESERVED_REGISTRY = CreationCapabilityRegistry()
RESERVED_REGISTRY.register(_reserved_entry("creation.tts", "tts", "TTS 语音生成（预留）"))
RESERVED_REGISTRY.register(_reserved_entry("creation.image", "image", "AI 绘图（预留）"))
RESERVED_REGISTRY.register(
    _reserved_entry("creation.extensions", "extensions", "creation 扩展槽（预留）")
)

#: PEP 562 惰性转发：叶子契约按需加载，域根 import 保持零重负载
#: （与本工作区既有 RW16 垫片手法同源）。
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "TTSJobRequest": (".tts.contracts", "TTSJobRequest"),
    "TTSUsage": (".tts.contracts", "TTSUsage"),
    "TTSAssetRecord": (".tts.contracts", "TTSAssetRecord"),
    "TTSOutboundPlan": (".tts.contracts", "TTSOutboundPlan"),
    "TTSProviderCapabilities": (".tts.contracts", "TTSProviderCapabilities"),
    "ImageJobRequest": (".image.contracts", "ImageJobRequest"),
    "ImageUsage": (".image.contracts", "ImageUsage"),
    "ImageAssetRecord": (".image.contracts", "ImageAssetRecord"),
    "ImageDeliveryPlan": (".image.contracts", "ImageDeliveryPlan"),
    "ImageProviderCapabilities": (".image.contracts", "ImageProviderCapabilities"),
    "ConfirmToken": (".image.contracts", "ConfirmToken"),
    "SafetyCheckHook": (".image.contracts", "SafetyCheckHook"),
    "SafetyCheckResult": (".image.contracts", "SafetyCheckResult"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(target[0], __name__)
    return getattr(module, target[1])

__all__ = [
    "NODE_REQUIRED_FIELDS",
    "REGISTRY_OPEN_NODE_KINDS",
    "RESERVED_REGISTRY",
    "STEP_GATED",
    "STEP_PROJECTED",
    "STEP_PROTOCOL",
    "STEP_REGISTERED",
    "CapabilityGateClosedError",
    "CapabilityNotImplementedError",
    "CreationCapabilityEntry",
    "CreationCapabilityKind",
    "CreationCapabilityRegistry",
    "CreationJobState",
    "ImageJobRequest",
    "TTSJobRequest",
    "UnregisteredCapabilityError",
    "manifest_registration_blockers",
]

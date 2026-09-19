"""creation/image 接口契约草案（矩阵 L52 V21-IMAGE-001；指南 §11 L258；扩展 §1）。

`reserved: 依赖外部 provider 配置，未实现`。矩阵 L52 零载体、四列维持 unknown：
本模块只落字段级 DTO / 协议常量 / 枚举 / 纯函数校验（§9.1.2 契约草案的机器可
执行形态），零 provider 客户端、零网络、零线程、零生产配置读取（V21-CORE-001
import 探针纪律；§9.4 reserved 契约形态 lint）。

字段级锚点：docs/design/backend-v2-implementation-guide.md §11 L258 段、
docs/design/backend-v2-product-extensions.md §1（L23 多单位计费/L49 确定性算例/
L56 多图按实结算）。任务状态机/取消语义与 TTS 共用 _common 单一定义（§9.1.2
「同 §9.1.1」；未知不重发、取消在途不假成功）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, field_validator, model_validator

from .._common.contracts import (
    CANCEL_MAY_KEEP_COST,
    CANCEL_REQUESTED_IS_NOT_A_STATE,
    CREATION_ERROR_CATALOG,
    IMAGE_MAX_INPUT_PIXELS,
    UNKNOWN_NEVER_AUTO_REDISPATCH,
    AssetRef,
    CancelRequest,
    CostAmount,
    CreationContractBase,
    CreationJobState,
    UsageLine,
    _require_aware_utc,
)

# ---------------------------------------------------------------------------
# 硬上限与参数域（指南 §11 L258）
# ---------------------------------------------------------------------------

#: prompt ≤4000 / negative_prompt ≤2000 字符。
IMAGE_MAX_PROMPT_CHARS = 4000
IMAGE_MAX_NEGATIVE_CHARS = 2000
#: count 默认 1，最大 2。
IMAGE_MAX_COUNT = 2
#: steps ≤50 ∩ provider。
IMAGE_MAX_STEPS = 50
#: 默认预览→确认发送：确认 token 120s 一次消费（指南 §6 L149）。
CONFIRM_TTL_SECONDS = 120

IMAGE_TASK = Literal["text_to_image", "image_to_image", "inpaint"]

#: size 取 provider 支持尺寸枚举（"WxH" 形态；不默认本地 GPU）。
IMAGE_SIZE_PATTERN = r"^\d{2,5}x\d{2,5}$"

#: 绘图计费指标子集（扩展 §1 L23）：images/requests + 分辨率档独立计费。
#: 确定性算例：2 张×每张 0.04=0.08，不伪造 Token（扩展 §1 L49）；一个请求
#: 多张图按实际数量结算，重试是否重复收费由 provider 事实决定（§1 L56）。
IMAGE_USAGE_METRICS = frozenset({"images", "requests"})

#: REST 面（挂 /api/v1 前缀；静态路径先于参数路由）。
IMAGE_REST_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/image-generation/providers"),
    ("GET", "/image-generation/models"),
    ("GET", "/image-generation/capabilities"),
    ("POST", "/image-generation/preview"),
    ("POST", "/image-generation/jobs"),
    ("GET", "/image-generation/jobs/{id}"),
    ("POST", "/image-generation/jobs/{id}/cancel"),
)

IMAGEErrorCode = Literal[
    "unsupported_parameter",
    "dependency_unavailable",
    "price_unavailable",
    "budget_exceeded",
]
IMAGE_ERROR_CATALOG = dict(CREATION_ERROR_CATALOG)

# 域内别名：任务状态机/取消语义与 TTS 共用 _common 单一定义。
ImageJobState = CreationJobState
ImageCancelRequest = CancelRequest


# ---------------------------------------------------------------------------
# Provider 能力目录（激活期由注册表填充；预留态为空目录）
# ---------------------------------------------------------------------------


class ImageProviderCapabilities(CreationContractBase):
    """provider 能力目录条目：尺寸枚举/steps 上限/分辨率档/任务面都来自这里。

    不默认本地 GPU（指南 §11 L258）；size 必须取 ``sizes`` 枚举。
    """

    provider: str = Field(min_length=1, max_length=128)
    max_steps: int = Field(ge=1, le=IMAGE_MAX_STEPS)
    sizes: tuple[str, ...] = Field(min_length=1)
    resolution_tiers: tuple[str, ...] = Field(default=())
    supported_tasks: tuple[IMAGE_TASK, ...] = Field(min_length=1)

    @field_validator("sizes", "resolution_tiers")
    @classmethod
    def _tier_shapes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not item or len(item) > 64:
                raise ValueError("尺寸/分辨率档条目不得为空且 ≤64 字符")
        return value


def steps_supported(steps: int, caps: ImageProviderCapabilities) -> bool:
    """steps ≤50 ∩ provider 上限（§9.1.2 steps 行）。"""
    return 1 <= steps <= min(IMAGE_MAX_STEPS, caps.max_steps)


def size_supported(size: str, caps: ImageProviderCapabilities) -> bool:
    return size in caps.sizes


def task_supported(task: str, caps: ImageProviderCapabilities) -> bool:
    return task in caps.supported_tasks


# ---------------------------------------------------------------------------
# 任务请求 DTO（字段级，§9.1.2 ImageJobRequest 表）
# ---------------------------------------------------------------------------


class ImageJobRequest(CreationContractBase):
    """绘图任务请求（§9.1.2 字段级草案）。

    - assets/mask 只收 ``asset_id`` 引用（非服务器路径/URL），输入图获取走
      DownloadBroker；单输入 ≤20MP（AssetRef.pixel_count 硬约束）；
    - 不接任意 workflow/code/路径：extra="forbid" 拒一切未登记字段（未支持
      参数 422 不静默丢弃）；
    - image_to_image/inpaint 须带 assets；inpaint 须带 mask，mask 仅 inpaint。
    """

    task: IMAGE_TASK
    prompt: str = Field(min_length=1, max_length=IMAGE_MAX_PROMPT_CHARS)
    negative_prompt: str | None = Field(default=None, max_length=IMAGE_MAX_NEGATIVE_CHARS)
    assets: tuple[AssetRef, ...] = Field(default=())
    mask: AssetRef | None = None
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    size: str = Field(min_length=3, max_length=11, pattern=IMAGE_SIZE_PATTERN)
    count: int = Field(default=1, ge=1, le=IMAGE_MAX_COUNT)
    seed: int | None = Field(default=None, ge=0)
    steps: int | None = Field(default=None, ge=1, le=IMAGE_MAX_STEPS)
    guidance: float | None = Field(default=None, gt=0, le=100)
    workspace_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)

    @field_validator("prompt", "negative_prompt")
    @classmethod
    def _prompt_non_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("prompt/negative_prompt 存在时不得为空白")
        return value

    @model_validator(mode="after")
    def _task_shape(self) -> ImageJobRequest:
        if self.task != "text_to_image" and not self.assets:
            raise ValueError(f"task={self.task} 必须携带 assets 引用（asset_id）")
        if self.task == "inpaint" and self.mask is None:
            raise ValueError("task=inpaint 必须携带 mask")
        if self.mask is not None and self.task != "inpaint":
            raise ValueError("mask 仅 task=inpaint 可用")
        return self


# ---------------------------------------------------------------------------
# 内容安全钩子（安全检查段：minors 等硬红线沿用 chat_reply/security 既有语义）
# ---------------------------------------------------------------------------


class SafetyCheckResult(CreationContractBase):
    """内容安全门结果：不过不出 asset（Review→asset 的前置闸）。"""

    passed: bool
    categories: tuple[str, ...] = Field(default=())
    reason: str = Field(default="", max_length=512)

    @model_validator(mode="after")
    def _fail_requires_reason(self) -> SafetyCheckResult:
        if not self.passed and not self.reason:
            raise ValueError("安全检查不通过必须给出 reason（脱敏归类，不含原文）")
        return self


@runtime_checkable
class SafetyCheckHook(Protocol):
    """内容安全检查钩子协议（实现期由 chat_reply/security Review 面接线）。

    协议层零实现承诺：hook 本身不得在本域内起网络/线程；硬红线语义
    （minors 双向共现全场景硬拦等）以 content_safety 既有实现为准。
    """

    def check(self, request: ImageJobRequest) -> SafetyCheckResult: ...


def asset_issuable(result: SafetyCheckResult) -> bool:
    """Review 闸：安全检查不过 → 不落 asset、不出图。"""
    return result.passed


# ---------------------------------------------------------------------------
# 用量 / 资产 / 预览确认出站（§9.1.2 usage 段 + 资产与出站段）
# ---------------------------------------------------------------------------


class ImageUsage(CreationContractBase):
    """绘图用量：images/requests + 分辨率档独立计费；不伪造 Token。"""

    quantities: list[UsageLine] = Field(default_factory=list)
    token_status: Literal["not_applicable", "unknown", "measured"] = "not_applicable"
    token_provider_reported: bool = False

    @model_validator(mode="after")
    def _token_and_metrics(self) -> ImageUsage:
        if self.token_status == "measured" and not self.token_provider_reported:
            raise ValueError("token_status=measured 必须 provider 真报（token_provider_reported）")
        for line in self.quantities:
            if line.metric not in IMAGE_USAGE_METRICS:
                raise ValueError(
                    f"绘图用量指标越界: {line.metric!r}（合法子集: {sorted(IMAGE_USAGE_METRICS)}）"
                )
        return self


class ImageAssetRecord(CreationContractBase):
    """输出资产：解码/真实 MIME/尺寸/帧数/EXIF 清理→Review→asset。

    - ``magic_verified``：真伪 MIME/magic 校验对齐 FILE-002 面；
    - ``exif_sanitized`` 钉死 True：出站前 EXIF 清理是硬约束；
    - ``review_approved`` 钉死 True：Review 不过不出 asset。
    """

    asset_id: AssetRef
    width: int = Field(ge=1, le=100_000)
    height: int = Field(ge=1, le=100_000)
    frames: int = Field(default=1, ge=1)
    real_mime: str = Field(min_length=3, max_length=64, pattern=r"^[a-z]+/[a-z0-9.+-]+$")
    bytes_size: int = Field(gt=0)
    magic_verified: bool = False
    exif_sanitized: bool = False
    review_approved: bool = False
    usage: ImageUsage = Field(default_factory=ImageUsage)
    cost: CostAmount | None = None

    @model_validator(mode="after")
    def _gates(self) -> ImageAssetRecord:
        if not self.magic_verified:
            raise ValueError("asset 必须过真伪 MIME/magic 校验（FILE-002 面）")
        if not self.exif_sanitized:
            raise ValueError("出站前必须完成 EXIF 清理")
        if not self.review_approved:
            raise ValueError("Review 不过不出 asset")
        return self


class ConfirmToken(CreationContractBase):
    """确认 token：绑定 actor/目标/版本/内容摘要，120s 一次消费（指南 §6 L149）。"""

    token_id: str = Field(min_length=1, max_length=128)
    actor: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    workspace_version: str = Field(min_length=1, max_length=64)
    payload_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    issued_at: datetime
    expires_at: datetime
    consumed: bool = False

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _aware_times(cls, value: datetime) -> datetime:
        return _require_aware_utc("confirm token time", value)

    @model_validator(mode="after")
    def _expiry_after_issue(self) -> ConfirmToken:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at 必须晚于 issued_at")
        return self


def confirm_expired(token: ConfirmToken, now: datetime) -> bool:
    """纯函数：给定当前时刻判断确认 token 是否过期（时钟由调用方注入）。"""
    return _require_aware_utc("now", now) >= token.expires_at


def confirm_reusable(token: ConfirmToken) -> bool:
    """纯函数：确认 token 是否仍未消费（一次消费语义）。"""
    return not token.consumed


class ImageDeliveryPlan(CreationContractBase):
    """出站计划：默认预览→确认发送；确认发送须持未消费确认 token。"""

    asset_ids: tuple[AssetRef, ...] = Field(min_length=1)
    mode: Literal["preview", "confirmed_send"]
    confirm: ConfirmToken | None = None
    review_approved: bool = False

    @model_validator(mode="after")
    def _confirm_gate(self) -> ImageDeliveryPlan:
        if not self.review_approved:
            raise ValueError("出站必须已过 Review")
        if self.mode == "confirmed_send":
            if self.confirm is None:
                raise ValueError("confirmed_send 必须携带确认 token（默认预览→确认发送）")
            if self.confirm.consumed:
                raise ValueError("确认 token 已消费（120s 一次消费）")
        return self


__all__ = [
    "CANCEL_MAY_KEEP_COST",
    "CANCEL_REQUESTED_IS_NOT_A_STATE",
    "CONFIRM_TTL_SECONDS",
    "IMAGE_ERROR_CATALOG",
    "IMAGE_MAX_COUNT",
    "IMAGE_MAX_INPUT_PIXELS",
    "IMAGE_MAX_NEGATIVE_CHARS",
    "IMAGE_MAX_PROMPT_CHARS",
    "IMAGE_MAX_STEPS",
    "IMAGE_REST_ROUTES",
    "IMAGE_SIZE_PATTERN",
    "IMAGE_USAGE_METRICS",
    "UNKNOWN_NEVER_AUTO_REDISPATCH",
    "ConfirmToken",
    "IMAGEErrorCode",
    "ImageAssetRecord",
    "ImageCancelRequest",
    "ImageDeliveryPlan",
    "ImageJobRequest",
    "ImageJobState",
    "ImageProviderCapabilities",
    "ImageUsage",
    "SafetyCheckHook",
    "SafetyCheckResult",
    "asset_issuable",
    "confirm_expired",
    "confirm_reusable",
    "size_supported",
    "steps_supported",
    "task_supported",
]

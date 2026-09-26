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
from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, field_validator, model_validator

from .._common.contracts import (
    CANCEL_MAY_KEEP_COST,
    CANCEL_REQUESTED_IS_NOT_A_STATE,
    CREATION_ERROR_CATALOG,
    DIGEST64_PATTERN,
    IMAGE_MAX_INPUT_PIXELS,
    UNKNOWN_NEVER_AUTO_REDISPATCH,
    AssetRef,
    CancelRequest,
    CostAmount,
    CreationContractBase,
    CreationJob,
    CreationJobState,
    CreationProvenance,
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
#: CFG/guidance 的**契约全局上界**（0<x≤100）。命名的唯一理由与 ``IMAGE_MAX_STEPS``
#: 同：这个数此前只以字面量活在 ``Field(le=100)`` 里，provider 侧想收紧它就得再抄一次
#: 数字＝第二真身（SEAT-S89 对账判 guidance 为"在册无牙"的根因之一）。
#: 下界 0 不在本常量里——它是"必须为正"的语义（``gt=0``），不是一个可调的上界。
IMAGE_MAX_GUIDANCE = 100.0
#: 参考图张数的**契约硬上限**（八段第 2 段的天花板，SEAT-S89 补）。
#: 修前 ``assets`` 只有"i2i/inpaint 必带"这条**下限**，没有任何上限 ⇒ 一次请求可以挂
#: 一万张参考图而无人拦（适配器侧的扇出与费用直接跟着涨）。这里给一个诚实的天花板，
#: provider 更严时由能力目录 :attr:`ImageProviderCapabilities.max_reference_images` 收紧。
IMAGE_MAX_REFERENCE_IMAGES = 4
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

#: 进度事件传输面（八段第 5 段的**明确声明**，不是留死字母）：
#: 本协议**只支持轮询**（``GET /image-generation/jobs/{id}``，见 ``IMAGE_REST_ROUTES``）。
#: SSE／事件流明确标为**未接**（``IMAGE_PROGRESS_SSE_WIRED = False``），且**不预挖** SSE 路由
#: ——预留一条没人挂的路由＝SEAT-S04 §1-5 点名的"死字母"，比不写更坏。
#: ⚠ 如实两态：轮询路由本身今天也是**预留态、无任何实现挂载**（provider 未接、控制面未装配），
#: 故"只支持轮询"是**协议面**的口径（缺省判据、给激活期定形），不是"现在就能轮询"的事实宣称。
#: 步级/百分比进度字段本协议**不提供**，进度粒度=``CreationJobState`` 七档状态机；
#: 若日后要步级进度须**升协议版**，不得就地改语义。
IMAGE_PROGRESS_TRANSPORT: Literal["poll"] = "poll"
IMAGE_PROGRESS_SSE_WIRED: bool = False


class ImageProgressMode(str, Enum):
    """进度获取方式的**唯一在册枚举**：只有轮询；SSE 显式列而未接（诚实，非空头）。"""

    POLL = "poll"
    # SSE 故意不进本枚举：留位即死字母；改用 IMAGE_PROGRESS_SSE_WIRED=False 说明"未接"。


IMAGEErrorCode = Literal[
    "unsupported_parameter",
    "dependency_unavailable",
    "price_unavailable",
    "budget_exceeded",
]
IMAGE_ERROR_CATALOG = dict(CREATION_ERROR_CATALOG)

# 域内别名：任务状态机/取消语义/结果记录与 TTS 共用 _common 单一定义
# （§9.1.2「任务状态机/取消：同 §9.1.1」；结果记录是中央 output_protocol 的两腿共用落点）。
ImageJobState = CreationJobState
ImageCancelRequest = CancelRequest
ImageJob = CreationJob


# ---------------------------------------------------------------------------
# Provider 能力目录（激活期由注册表填充；预留态为空目录）
# ---------------------------------------------------------------------------


class ImageProviderCapabilities(CreationContractBase):
    """provider 能力目录条目：尺寸枚举/steps 上限/分辨率档/任务面都来自这里。

    不默认本地 GPU（指南 §11 L258）；size 必须取 ``sizes`` 枚举。

    ``max_guidance``＝CFG 的 provider 侧上界（八段第 4 段的补牙位，SEAT-S89）：
    此前 guidance 只有契约全局域 ``0<x≤100``，能力目录里**没有对应维度**，于是
    ``handle`` 对它的交集判据物理上写不出来——适配器收到 ``guidance=40`` 也照样
    "支持"，这个字段等于只影响幂等身份、不影响任何行为。补上之后：
    ``None``＝该 provider **不声明** CFG 上界（沿用全局域，绝不替它猜一个数），
    非 None＝它声明了，越界即 ``LIMIT_EXCEEDED``、一次都不提交（与 size/steps 同构）。

    ``max_reference_images`` 与 ``supports_negative_prompt`` 同一套三态约定
    （八段第 2、3 段的补牙位——这两段此前在执行面上**零按名读点**，即整段只是名字）：
    - ``max_reference_images=None``＝不声明 ⇒ 只吃契约硬顶 ``IMAGE_MAX_REFERENCE_IMAGES``；
    - ``supports_negative_prompt=None``＝不声明 ⇒ 不拦也不宣称支持；
      ``False``＝**明确不支持** ⇒ 请求带负面提示当场拒，而不是安静地忽略它
      （"我收到了但没照做"与"我根本没收到"在结果上一样，却是两种不同的诚实）。
    """

    provider: str = Field(min_length=1, max_length=128)
    max_steps: int = Field(ge=1, le=IMAGE_MAX_STEPS)
    sizes: tuple[str, ...] = Field(min_length=1)
    resolution_tiers: tuple[str, ...] = Field(default=())
    supported_tasks: tuple[IMAGE_TASK, ...] = Field(min_length=1)
    #: provider 声明的 CFG 上界；None=不声明（不猜、不放行越界值之外的收紧）。
    max_guidance: float | None = Field(default=None, gt=0, le=IMAGE_MAX_GUIDANCE)
    #: provider 能吃的参考图张数；None=不声明（只吃契约硬顶）。
    max_reference_images: int | None = Field(
        default=None, ge=1, le=IMAGE_MAX_REFERENCE_IMAGES
    )
    #: 是否支持负面提示；None=不声明，False=明确不支持（带即拒，绝不静默忽略）。
    supports_negative_prompt: bool | None = None

    @field_validator("sizes", "resolution_tiers")
    @classmethod
    def _tier_shapes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not item or len(item) > 64:
                raise ValueError("尺寸/分辨率档条目不得为空且 ≤64 字符")
        return value

    @model_validator(mode="after")
    def _guidance_is_finite(self) -> ImageProviderCapabilities:
        # 基类 allow_inf_nan=False 已挡 NaN/Inf；这里显式留一道语义锁，防日后有人
        # 把 max_guidance 放宽成"收 Decimal/字符串"而丢掉有限性判据。
        if self.max_guidance is not None and not self.max_guidance > 0:
            raise ValueError("max_guidance 若声明则必须为正数（None 才是『不声明』）")
        return self


def steps_supported(steps: int, caps: ImageProviderCapabilities) -> bool:
    """steps ≤50 ∩ provider 上限（§9.1.2 steps 行）。"""
    return 1 <= steps <= min(IMAGE_MAX_STEPS, caps.max_steps)


def size_supported(size: str, caps: ImageProviderCapabilities) -> bool:
    return size in caps.sizes


def task_supported(task: str, caps: ImageProviderCapabilities) -> bool:
    return task in caps.supported_tasks


def guidance_supported(guidance: float, caps: ImageProviderCapabilities) -> bool:
    """CFG 交集：契约全局域由 DTO 的 ``gt/le`` 把，provider 声明的上界在这里把。

    ``caps.max_guidance is None`` ⇒ provider 未声明 ⇒ **不额外收紧**（沿用全局域，
    这是缺省而非放行：全局域仍然生效，越界值早在 ``ImageJobRequest`` 就被拒了）。
    """
    if caps.max_guidance is None:
        return True
    return 0 < guidance <= caps.max_guidance


def references_supported(count: int, caps: ImageProviderCapabilities) -> bool:
    """参考图张数交集（八段第 2 段的执行面读点）：不声明就只吃契约硬顶。"""
    ceiling = IMAGE_MAX_REFERENCE_IMAGES
    if caps.max_reference_images is not None:
        ceiling = caps.max_reference_images
    return 0 <= count <= ceiling


def negative_prompt_accepted(
    request: ImageJobRequest, caps: ImageProviderCapabilities
) -> tuple[bool, str]:
    """负面提示支持性（八段第 3 段的执行面读点）：**明确**不支持才拒，不声明不拦。

    返回 ``(是否放行, 原因)`` 而不是裸 bool——被拒时原因要进 ``LIMIT_EXCEEDED`` 的
    detail，让"我这条约束被 provider 拒了"与"provider 压根没答"在回执上可分辨。
    ``None``＝不声明 ⇒ 放行（绝不为它编一个"不支持"，也绝不宣称"支持"）。
    """
    if request.negative_prompt is None:
        return True, ""
    if caps.supports_negative_prompt is False:
        return False, (
            f"provider {caps.provider!r} 明确不支持负面提示，"
            "而本次请求带了 negative_prompt：不静默忽略、不假装照做"
        )
    return True, ""


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
    #: 参考图/底图引用：下限由 ``_task_shape``（i2i/inpaint 必带）执法，上限由本
    #: ``max_length`` 执法（八段第 2 段补牙：修前**无任何上限**，一万张也照收）。
    assets: tuple[AssetRef, ...] = Field(default=(), max_length=IMAGE_MAX_REFERENCE_IMAGES)
    mask: AssetRef | None = None
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    size: str = Field(min_length=3, max_length=11, pattern=IMAGE_SIZE_PATTERN)
    #: 请求件数（1..2）。**此前是全仓零读点的装饰字段**（SEAT-S89 现算：除"改值即改幂等
    #: 身份"外没有任何一处判据），而适配器面只承载单件产物 ⇒ count=2 结构上不可表达。
    #: 补牙后它有两个真实读点：①交付件数不得超过它（:func:`delivery_within_count`，
    #: 由 handle 现用）；②计量行按**实际交付件数**记账而非恒 1（"多图按实结算"，扩展 §1 L56）。
    count: int = Field(default=1, ge=1, le=IMAGE_MAX_COUNT)
    seed: int | None = Field(default=None, ge=0)
    steps: int | None = Field(default=None, ge=1, le=IMAGE_MAX_STEPS)
    guidance: float | None = Field(default=None, gt=0, le=IMAGE_MAX_GUIDANCE)
    workspace_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    #: 请求身份（幂等键）：`media_digest(idempotency_preimage(request))` 的 64 hex 值，
    #: 由装配期算好填入；域内不重算哈希（单一算法家=domains/media/digest.py）。
    #: 绘图比 TTS 更需要它：count≤2 的一次请求可能已产生真实费用，unknown 态重发
    #: = 重复出图重复计费（扩展 §1 L56「重试是否重复收费由 provider 事实决定」）。
    #: 缺省 None=调用方未给身份（不去重、不承诺幂等，绝不猜是同一条）。
    idempotency_key: str | None = Field(default=None, pattern=DIGEST64_PATTERN)

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


def delivery_within_count(delivered: int, requested: int) -> bool:
    """交付件数不得超过请求件数（``count`` 的第一个真实执行面判据，SEAT-S89 补牙）。

    为什么这一条必须存在而不是"provider 自己会照做"：绘图一次请求可能已经花钱
    （扩展 §1 L56「多图按实结算」），**超发**意味着账单与产物数会各自漂移且无人报错；
    少发（含 0，失败/取消态）是合法的，超发不是。判据留在契约侧（本函数）而不是
    写在 ``handle`` 的 if 里——与 size/steps 同一手法，执行面只**调用**已登记件。
    """
    return 0 <= delivered <= requested


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
    #: 产物内容身份：落盘字节的 sha256（中央 digest 件原样值；键名与 TTS 出站部件键、
    #: 渲染收口第三冻结键同源——两域同一套契约，不留两种叫法）。None=算不出即缺。
    content_sha256: str | None = Field(default=None, pattern=DIGEST64_PATTERN)
    #: 溯源位（八段第 8 段补齐）：EXIF 被 ``exif_sanitized`` 强制剥净后，来源信息的**旁车**。
    #: ``None``＝预留态如实"无溯源可报"（provider 未接时诚实留空，绝不回填假值）。
    provenance: CreationProvenance | None = None
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
        # 旁车与嵌入位必须同读：既然 exif_sanitized 钉死 True（嵌入已清），
        # 一旦带溯源，其 exif_stripped 也须为 True——否则"声称来源在嵌入里"却已被剥净=自相矛盾。
        if self.provenance is not None and not self.provenance.exif_stripped:
            raise ValueError(
                "asset 的 EXIF 已剥净（exif_sanitized=True）却带 exif_stripped=False 的溯源："
                "来源声明与剥离事实必须一致"
            )
        return self


class ConfirmToken(CreationContractBase):
    """确认 token：绑定 actor/目标/版本/内容摘要，120s 一次消费（指南 §6 L149）。"""

    token_id: str = Field(min_length=1, max_length=128)
    actor: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    workspace_version: str = Field(min_length=1, max_length=64)
    payload_digest: str = Field(min_length=64, max_length=64, pattern=DIGEST64_PATTERN)
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
    "IMAGE_MAX_GUIDANCE",
    "IMAGE_MAX_INPUT_PIXELS",
    "IMAGE_MAX_NEGATIVE_CHARS",
    "IMAGE_MAX_PROMPT_CHARS",
    "IMAGE_MAX_REFERENCE_IMAGES",
    "IMAGE_MAX_STEPS",
    "IMAGE_PROGRESS_SSE_WIRED",
    "IMAGE_PROGRESS_TRANSPORT",
    "IMAGE_REST_ROUTES",
    "IMAGE_SIZE_PATTERN",
    "IMAGE_USAGE_METRICS",
    "UNKNOWN_NEVER_AUTO_REDISPATCH",
    "ConfirmToken",
    "CreationProvenance",
    "IMAGEErrorCode",
    "ImageAssetRecord",
    "ImageCancelRequest",
    "ImageDeliveryPlan",
    "ImageJob",
    "ImageJobRequest",
    "ImageJobState",
    "ImageProgressMode",
    "ImageProviderCapabilities",
    "ImageUsage",
    "SafetyCheckHook",
    "SafetyCheckResult",
    "asset_issuable",
    "confirm_expired",
    "confirm_reusable",
    "delivery_within_count",
    "guidance_supported",
    "negative_prompt_accepted",
    "references_supported",
    "size_supported",
    "steps_supported",
    "task_supported",
]

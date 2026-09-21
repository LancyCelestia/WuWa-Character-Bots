"""creation/tts 接口契约草案（矩阵 L51 V21-TTS-001；指南 §11 L256；扩展 §1）。

`reserved: 依赖外部 provider 配置，未实现`。矩阵四列维持 unknown：本模块只落
字段级 DTO / 协议常量 / 枚举 / 纯函数校验（§9.1.1 契约草案的机器可执行形态），
零 provider 客户端、零网络、零线程、零生产配置读取（V21-CORE-001 import 探针
纪律；§9.4 reserved 契约形态 lint）。

字段级锚点：docs/design/backend-v2-implementation-guide.md §11 L256 段、
docs/design/backend-v2-product-extensions.md §1（L16 字段表 / L23 多单位计费 /
L49 确定性算例 / L58 取消保留费用）。现载体 capabilities/tts.py 留 media 域
原映射不动（归属裁决 §10 W-PA2）；本模块是激活期（providers/voices/
capabilities/jobs 协议面）的合同底稿。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .._common.contracts import (
    CANCEL_MAY_KEEP_COST,
    CANCEL_REQUESTED_IS_NOT_A_STATE,
    CREATION_ERROR_CATALOG,
    UNKNOWN_NEVER_AUTO_REDISPATCH,
    AssetRef,
    CancelRequest,
    CostAmount,
    CreationContractBase,
    CreationJobState,
    UsageLine,
)

# ---------------------------------------------------------------------------
# 硬上限与参数域——**收敛到中央 TTS 契约单一来源，本域不再持有第二套数值**
# ---------------------------------------------------------------------------
# 数值真身 = Wave G 中央契约 domains/media/tts_presets.py：
#   文本顶  = HARD_MAX_CHARS_FALLBACK (2000)                    tts_presets.py:59
#   字节顶  = MAX_AUDIO_BYTES_FALLBACK (8MiB≈131s)              tts_presets.py:62-64
#   speed域 = ENGINE_PARAM_DOMAINS["speed_factor"]=(0.6, 1.65)  tts_presets.py:37
# 本叶子契约受 test_v21_creation_skeleton.py 隔离直载探针约束（真包父级装配会
# 拉起 nonebot，故 contracts 必须零重 import），无法在此直接 import 中央件；
# 逐组等值由常驻门 tests/test_creation_tts_drift_gate.py 锁死——任一侧改数即红。
# 旧值 text=3000 / 时长=60s / 体积=20MiB / speed 0.75..1.25 于 2026-09-21 统一接入波
# U3 作废（60s 更被 Wave G 明文并入字节顶）；中央契约一字未改。
# 若日后中央导出时长/比特率常量，应改为 import 之并退役本处派生。

#: text ≤ 中央文本顶（2000 字符，G2-R3）。
TTS_MAX_TEXT_CHARS = 2000
#: 输出体积 ≤ 中央字节顶（8 MiB，G2-R3）。
TTS_MAX_ASSET_BYTES = 8 * 1024 * 1024
#: PCM 字节率：v2ProPlus 32000Hz×16bit×单声道=64000 B/s 恒定（中央 T53 §4.5）。
_TTS_PCM_BYTES_PER_SECOND = 32000 * 2 * 1
#: 输出时长上限 = 中央字节顶 ÷ 比特率（8MiB/64000≈131.072s），非独立秒级政策值。
TTS_MAX_DURATION_SECONDS = TTS_MAX_ASSET_BYTES / _TTS_PCM_BYTES_PER_SECOND
#: speed 默认 1.0，范围对齐中央引擎域 0.6..1.65 ∩ provider 能力。
TTS_SPEED_MIN = 0.6
TTS_SPEED_MAX = 1.65
TTS_SPEED_DEFAULT = 1.0

#: TTS 计费指标子集（扩展 §1 L23）：characters/audio_seconds/requests。
#: Token 仅 provider 真报才可携带，否则 not_applicable/unknown——不得按字符
#: 伪造精确 Token（确定性算例：1200 字符×每百万 15=0.018，Token 字段
#: not_applicable，扩展 §1 L49）。
TTS_USAGE_METRICS = frozenset({"characters", "audio_seconds", "requests"})

#: REST 面（挂 /api/v1 前缀，指南 §6 L143；静态路径先于参数路由 §6 L176）。
TTS_REST_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/tts/providers"),
    ("GET", "/tts/voices"),
    ("GET", "/tts/capabilities"),
    ("POST", "/tts/preview"),
    ("POST", "/tts/jobs"),
    ("GET", "/tts/jobs/{id}"),
    ("POST", "/tts/jobs/{id}/cancel"),
)

#: 出站标签：原生 voice 与文件回退严格二分；文件回退**不得称原生 voice**
#: （指南 §11 L256）；出站标签本身不朗读（矩阵 L51 验收重点）。
TTSOutboundTag = Literal["voice", "file"]

#: 错误目录切片（§9.1.1 参数校验与错误码段；单一注册源=contracts/errors）。
TTSErrorCode = Literal[
    "unsupported_parameter",
    "dependency_unavailable",
    "price_unavailable",
    "budget_exceeded",
]
TTS_ERROR_CATALOG = dict(CREATION_ERROR_CATALOG)

# 域内别名：任务状态机/取消语义与绘图共用 _common 单一定义。
TTSJobState = CreationJobState
TTSCancelRequest = CancelRequest


# ---------------------------------------------------------------------------
# Provider 能力目录（激活期由注册表填充；预留态为空目录）
# ---------------------------------------------------------------------------


class TTSProviderCapabilities(CreationContractBase):
    """provider 能力目录条目：speed 交集/format/上限都来自这里，禁任意参数。"""

    provider: str = Field(min_length=1, max_length=128)
    speed_min: float = Field(ge=TTS_SPEED_MIN, le=TTS_SPEED_MAX)
    speed_max: float = Field(ge=TTS_SPEED_MIN, le=TTS_SPEED_MAX)
    formats: tuple[str, ...] = Field(min_length=1)
    max_duration_seconds: float = Field(
        default=TTS_MAX_DURATION_SECONDS, gt=0, le=TTS_MAX_DURATION_SECONDS
    )
    max_asset_bytes: int = Field(
        default=TTS_MAX_ASSET_BYTES, gt=0, le=TTS_MAX_ASSET_BYTES
    )

    @model_validator(mode="after")
    def _speed_range_ordered(self) -> TTSProviderCapabilities:
        if self.speed_min > self.speed_max:
            raise ValueError("speed_min 不得大于 speed_max")
        return self


def speed_in_provider_intersection(speed: float, caps: TTSProviderCapabilities) -> bool:
    """speed 是否落在全局域 ∩ provider 能力交集内（§9.1.1 speed 行）。"""
    return caps.speed_min <= speed <= caps.speed_max


def format_supported(fmt: str, caps: TTSProviderCapabilities) -> bool:
    return fmt in caps.formats


# ---------------------------------------------------------------------------
# 任务请求 DTO（字段级，§9.1.1 TTSJobRequest 表）
# ---------------------------------------------------------------------------


def _reject_provider_path_like(value: str) -> str:
    """provider/model/voice 等注册表枚举名：禁任意音色路径/URL/SSML 注入形态。"""
    lowered = value.strip().lower()
    if any(marker in lowered for marker in ("/", "\\", "://", "..", "<", ">")):
        raise ValueError(
            "provider/model/voice 必须取注册表能力目录枚举，禁任意音色路径/URL/标记注入"
        )
    return value


class TTSJobRequest(CreationContractBase):
    """TTS 合成任务请求（§9.1.1 字段级草案）。

    - text / approved_reply_id **二选一**：approved_reply_id 引用已过 Review 的
      出站草稿 id，不得由模型自报（metadata 由运行时写，指南 §10 L240）；
    - provider/model/voice/language/format 枚举来自注册表能力目录；禁原始
      SSML（text 内出现 SSML 根标签即拒）；
    - speed 落在中央引擎域 0.6..1.65，provider 交集在受理期用 TTSProviderCapabilities 复核；
    - 输出上限：时长 ≤131.072s 且体积 ≤8MiB（均收敛中央单一来源，见上方常量注记，
      由 TTSAssetRecord 硬约束回验）。
    """

    text: str | None = Field(default=None, max_length=TTS_MAX_TEXT_CHARS)
    approved_reply_id: str | None = Field(default=None, min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    voice: str = Field(min_length=1, max_length=128)
    language: str = Field(
        min_length=2, max_length=16, pattern=r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$"
    )
    format: str = Field(min_length=2, max_length=10, pattern=r"^[a-z0-9]{2,10}$")
    speed: float = Field(default=TTS_SPEED_DEFAULT, ge=TTS_SPEED_MIN, le=TTS_SPEED_MAX)
    workspace_id: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)

    @field_validator("provider", "model", "voice")
    @classmethod
    def _registry_names(cls, value: str) -> str:
        return _reject_provider_path_like(value)

    @field_validator("text")
    @classmethod
    def _text_non_blank_no_ssml(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("text 存在时不得为空白")
        lowered = stripped.lower()
        ssml_markers = ("<speak", "</speak", "<?xml", "<voice", "<prosody")
        if any(marker in lowered for marker in ssml_markers):
            raise ValueError("禁原始 SSML：text 只收纯文本，SSML 由实现期适配器承担")
        return value

    @model_validator(mode="after")
    def _text_xor_reply(self) -> TTSJobRequest:
        has_text = self.text is not None
        has_reply = self.approved_reply_id is not None
        if has_text == has_reply:
            raise ValueError("text 与 approved_reply_id 必须二选一（指南 §11 L256）")
        return self


# ---------------------------------------------------------------------------
# 用量 / 资产 / 出站（§9.1.1 usage 多单位计费段 + 资产段 + 出站段）
# ---------------------------------------------------------------------------


class TTSUsage(CreationContractBase):
    """TTS 用量：characters/audio_seconds/requests 多单位；Token 不伪造。"""

    quantities: list[UsageLine] = Field(default_factory=list)
    token_status: Literal["not_applicable", "unknown", "measured"] = "not_applicable"
    token_provider_reported: bool = False

    @model_validator(mode="after")
    def _token_and_metrics(self) -> TTSUsage:
        if self.token_status == "measured" and not self.token_provider_reported:
            raise ValueError("token_status=measured 必须 provider 真报（token_provider_reported）")
        for line in self.quantities:
            if line.metric not in TTS_USAGE_METRICS:
                raise ValueError(
                    f"TTS 用量指标越界: {line.metric!r}（合法子集: {sorted(TTS_USAGE_METRICS)}）"
                )
        return self


class TTSAssetRecord(CreationContractBase):
    """asset 记录：时长/MIME/codec/provider_operation/usage/成本/fallback。

    走 AssetBroker/ArtifactGateway（V21-FILE-002 面）；Review 不过不出 asset。
    """

    asset_id: AssetRef
    duration_seconds: float = Field(gt=0, le=TTS_MAX_DURATION_SECONDS)
    bytes_size: int = Field(gt=0, le=TTS_MAX_ASSET_BYTES)
    mime: str = Field(min_length=3, max_length=64, pattern=r"^[a-z]+/[a-z0-9.+-]+$")
    codec: str = Field(default="", max_length=64)
    provider_operation: str = Field(min_length=1, max_length=128)
    usage: TTSUsage = Field(default_factory=TTSUsage)
    cost: CostAmount | None = None
    fallback_to_file: bool = False
    review_approved: bool = False

    @model_validator(mode="after")
    def _review_gate(self) -> TTSAssetRecord:
        if not self.review_approved:
            raise ValueError("asset 记录必须已过 Review（Review 后才合成/落 asset）")
        return self


class TTSOutboundPlan(CreationContractBase):
    """出站计划：voice/file 标签不虚称 + 只走 render→transport 主链。

    - tag="voice" 必须 native_voice_verified（TG/QQ 编码按**实际能力验证**）；
      文件回退 tag="file"，不得称原生 voice（指南 §11 L256）；
    - 出站标签不朗读（矩阵 L51 验收重点）；
    - via_render_transport 钉死 True：经 render（Review）→transport（Queue/
      OutboundIntent）出站，不走旁路（指南 §10 L238）。
    """

    asset_id: AssetRef
    tag: TTSOutboundTag
    native_voice_verified: bool = False
    review_approved: bool = False
    via_render_transport: bool = False

    @model_validator(mode="after")
    def _tag_and_chain(self) -> TTSOutboundPlan:
        if not self.review_approved:
            raise ValueError("出站必须已过 Review")
        if not self.via_render_transport:
            raise ValueError("出站必须经 render→transport 主链，不走旁路")
        if self.tag == "voice" and not self.native_voice_verified:
            raise ValueError("文件回退不得称原生 voice：tag=voice 需实际能力验证通过")
        return self


__all__ = [
    "CANCEL_MAY_KEEP_COST",
    "CANCEL_REQUESTED_IS_NOT_A_STATE",
    "TTS_ERROR_CATALOG",
    "TTS_MAX_ASSET_BYTES",
    "TTS_MAX_DURATION_SECONDS",
    "TTS_MAX_TEXT_CHARS",
    "TTS_REST_ROUTES",
    "TTS_SPEED_DEFAULT",
    "TTS_SPEED_MAX",
    "TTS_SPEED_MIN",
    "TTS_USAGE_METRICS",
    "UNKNOWN_NEVER_AUTO_REDISPATCH",
    "TTSAssetRecord",
    "TTSCancelRequest",
    "TTSErrorCode",
    "TTSJobRequest",
    "TTSJobState",
    "TTSOutboundPlan",
    "TTSOutboundTag",
    "TTSProviderCapabilities",
    "TTSUsage",
    "format_supported",
    "speed_in_provider_intersection",
]

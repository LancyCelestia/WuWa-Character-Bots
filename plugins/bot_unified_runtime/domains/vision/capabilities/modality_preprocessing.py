"""#51「多模态原生输入」接货腿（恢复波，2026-09-23 席位）。

背景
----
#51 只落到了「原生视频能走通」的半边：原生音频/视频**内容部件的构造**
（``transcribe.build_native_audio_part`` / ``video_understanding.build_native_video_part``）、
能力门（``model_router.supports_native_media``，声明式 tags 白名单）、以及装配
（``chat.build_direct_vision_messages(media_parts=…)``）都已存在并在
``chat.py`` 摄取链里被直呼。缺的是「接货腿」的另一半——把三种模态的**预处理**
统一成一个经中央调度层的能力面：一个纯决策函数 + 三枚能力描述符 + 一张队列作业表，
各支一律**复用既有件**，不二次实现抽特征 / ASR / 抽帧 / TTS / 视觉。

本模块的边界（诚实）
--------------------
- ``preprocess_for_modality`` 是**纯函数**：只吃调用方已备好的事实（是否本机、体积、
  容器、模型是否声明支持原生、是否要放大），吐出一个「走哪条路 + 交给哪个能力」的
  计划；**零 IO、零网络、零线程**，可离线确定性单测。真正带 IO 的部件构造与转写
  留在既有真身里，由下方 handler 直呼，本函数不复制它们。
- 三枚描述符族=``CREATION``，指向既有真身（``transcribe_audio`` / ``build_video_brief``
  / ``describe_images``）；``creation.image.upscale`` 复用**视觉理解**（识别/归一）
  这条腿，**绝不复用图像生成**（``creation.image.generate`` 是另一条路）。
- 描述符进入中央 ``CAPABILITY_DESCRIPTOR`` 唯一表的接线口在
  ``runtime/capability_protocols.DESCRIPTOR_BUILDERS``，chat 摄取链改走本能力则落在
  根 ``__init__.py``/``chat.py``——两者本席**禁动**（生产根 + 他席在飞），见模块末
  ``WIRING_COORDINATES``。故本席是「能力面 + 纯函数 + 作业表 + 动态开关读」全部
  自足、可测，唯「通电进中央 / 直呼换线」留待注册面 owner 在干净树上补一行。

全离线纪律：import 零网络零线程副作用；handler 全靠注入 provider/config，缺依赖
诚实 ``UNAVAILABLE``（禁假成功）。会话/记忆键一律经 ``domains/core/session_keys`` 与
``memory_bus_v2``，不自行拼接、不建第二真身。
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

from plugins.bot_unified_runtime.domains.core.session_keys import build_session_key

# 原生容器在册表由真身持有（transcribe 持音频、video_understanding 持视频 MIME）；
# 本席只读引用、不复制第二张表（一处变更处处跟随：真身改了这里跟着动）。
from plugins.bot_unified_runtime.domains.media.ingest.transcribe import (
    _NATIVE_AUDIO_FORMATS,
)

# 执行信封（InvocationResult/InvocationStatus）从壳导入不被第二 authoring 面门禁止
# （该门只拦 `CapabilityDescriptor(...)` 构造与 5 个注册表类），委托 handler 需要它。
# 描述符的**构造**留唯一壳 capability_protocols（见 WIRING_COORDINATES），本模块只出不
# 造：以轻量 spec 交 owner 转录，守「descriptor authoring 面唯一」不变量。
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    InvocationResult,
    InvocationStatus,
)

logger = logging.getLogger(__name__)

# ===========================================================================
# 词汇：模态 / 路线
# ===========================================================================

MODE_AUDIO = "audio"
MODE_VIDEO = "video"
MODE_IMAGE = "image"
MODALITIES = (MODE_AUDIO, MODE_VIDEO, MODE_IMAGE)

ROUTE_NATIVE = "native"  # 模型被声明支持原生 → 直接挂原生内容部件（复用既有构造件）
ROUTE_TRANSCODE = "transcode"  # 音频回落 ASR 转写（复用 transcribe 真身）
ROUTE_FRAME_EXTRACT = "frame_extract"  # 视频回落抽帧+VLM（复用 video_understanding 真身）
ROUTE_UPSCALE = "upscale"  # 图像放大/归一（复用视觉这条腿，非生成）
ROUTE_PLAIN = "plain"  # 无需预处理，原样交给下游


# 三枚执行能力的 capability_id（CREATION 族协议对接点）。
CAP_AUDIO_TRANSCRIBE = "creation.audio.transcribe"
CAP_VIDEO_UNDERSTAND = "creation.video.understand"
CAP_IMAGE_UPSCALE = "creation.image.upscale"

# chat 侧两枚「执行开关」能力 id（供注册面 owner 登记进 CONTROLLED_INTERNAL_CAPABILITIES，
# 门绑定由唯一表 gate_feature_bindings() 自动派生——本席不建第二张表、不写死字面量）。
CAP_AUDIO_INPUT = "bot.audio_input"
CAP_VIDEO_UNDERSTANDING = "bot.video_understanding"


def derive_gate_feature_id(capability_id: str) -> str:
    """capability_id → feature gate 节点 id。

    逐字镜像唯一表 ``capability_protocols._gate_feature_id`` 的换算
    （``bot.`` → ``bot.plugin.``），**不另立规则**——这样注册面 owner 一旦把
    ``CAP_AUDIO_INPUT``/``CAP_VIDEO_UNDERSTANDING`` 登进 CONTROLLED_INTERNAL_CAPABILITIES，
    门 id 与本席常量零漂移（等价锁由该门 owner 常驻）。
    """
    return capability_id.replace("bot.", "bot.plugin.", 1)


GATE_AUDIO_INPUT = derive_gate_feature_id(CAP_AUDIO_INPUT)  # bot.plugin.audio_input
GATE_VIDEO_UNDERSTANDING = derive_gate_feature_id(CAP_VIDEO_UNDERSTANDING)

# 待接线的确切坐标（本席禁动生产根与注册面，交 owner 在干净树补；见报告「退让账」）。
WIRING_COORDINATES: Mapping[str, str] = MappingProxyType(
    {
        "descriptor_to_central_table": (
            "把 modality_capability_specs() 三条转录成 CapabilityDescriptor，追加进 "
            "plugins/bot_unified_runtime/runtime/capability_protocols.py::"
            "_creation_descriptors()（唯一 descriptor authoring 面）"
        ),
        "chat_gate_registration": (
            "plugins/bot_unified_runtime/domains/chat_reply/runtime/"
            "capability_registry.py::CONTROLLED_INTERNAL_CAPABILITIES 追加 "
            "bot.audio_input / bot.video_understanding"
        ),
        "intake_call_swap": (
            "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py "
            "原生部件构造处改为经 default_invoker().invoke(capability_id=…)"
        ),
    }
)


# ===========================================================================
# 纯决策函数（无 IO / 无网络 / 无线程）
# ===========================================================================


@dataclass(frozen=True)
class ModalityInput:
    """一条媒体输入的**已备好事实**（全部由调用方填，本模块不做任何 stat/读文件/网络）。

    - ``source``：本机路径或 URL 字符串（仅透传给 handler，纯函数不打开它）；
    - ``is_local``：调用方判定「这是本机可读文件」而非 http URL；
    - ``size_bytes``：已知体积（未知传 None，视为「不因此否决」，交由真身二次核）；
    - ``suffix``：小写容器后缀（含点），如 ``.wav`` / ``.mp4``；
    - ``native_supported``：首发渠道是否被 tags 声明支持该模态原生；
    - ``want_upscale``：图像是否请求放大归一（默认按视觉理解，不放大）。
    """

    kind: str
    source: str = ""
    is_local: bool = False
    size_bytes: int | None = None
    suffix: str = ""
    native_supported: bool = False
    want_upscale: bool = False
    max_mb: float = 20.0

    def __post_init__(self) -> None:
        if self.kind not in MODALITIES:
            raise ValueError(f"unknown modality kind={self.kind!r}")


@dataclass(frozen=True)
class PreprocessPlan:
    """纯决策结果：走哪条路、交给哪个能力、可选原生部件形态。"""

    kind: str
    capability_id: str
    route: str
    native_part_type: str  # "input_audio" | "video_url" | "" （图像不产原生部件）
    steps: tuple[str, ...] = ()
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def uses_native(self) -> bool:
        return self.route == ROUTE_NATIVE


def _within_size(size_bytes: int | None, max_mb: float) -> bool:
    """体积是否落在允许区间；未知(None)不否决（真身会再核一次）。"""
    if size_bytes is None:
        return True
    return size_bytes <= int(max_mb * 1024 * 1024)


def preprocess_for_modality(inp: ModalityInput) -> PreprocessPlan:
    """把一条多模态输入路由到对应的既有能力（纯函数，零副作用）。

    决策口径（与 ``chat.py`` 现有摄取链一致，不新造判据）：

    - **音频**：模型声明支持原生 + 本机文件 + 容器在册 + 体积合规 → 原生
      ``input_audio``（复用 ``build_native_audio_part``）；否则回落 ASR 转写
      （复用 ``transcribe_audio``）。
    - **视频**：模型声明支持原生 + 本机 + 体积合规 → 原生 ``video_url``
      （复用 ``build_native_video_part``）；否则回落抽帧 + VLM
      （复用 ``build_video_brief`` / ``_extract_video_frames``）。
    - **图像**：走视觉理解这条腿（``creation.image.upscale`` → 复用 ``describe_images``
      的识别/归一）；放大是可选前置步，无独立放大 provider 时诚实按识别路径。
      **绝不**把图像交给图像生成那条路（两条不同路，红线）。
    """
    suffix = (inp.suffix or "").lower()

    if inp.kind == MODE_AUDIO:
        native_ok = (
            inp.native_supported
            and inp.is_local
            and bool(suffix)
            and suffix in _NATIVE_AUDIO_FORMATS
            and _within_size(inp.size_bytes, inp.max_mb)
        )
        if native_ok:
            return PreprocessPlan(
                kind=MODE_AUDIO,
                capability_id=CAP_AUDIO_TRANSCRIBE,
                route=ROUTE_NATIVE,
                native_part_type="input_audio",
                steps=("native_audio_part",),
                reason="声明支持原生音频且本机容器在册：直挂原生部件，跳过 ASR",
                metadata={"audio_format": _NATIVE_AUDIO_FORMATS[suffix], "max_mb": inp.max_mb},
            )
        return PreprocessPlan(
            kind=MODE_AUDIO,
            capability_id=CAP_AUDIO_TRANSCRIBE,
            route=ROUTE_TRANSCODE,
            native_part_type="",
            steps=("asr_transcribe",),
            reason="未声明原生/非本机/容器不在册/超限：回落 ASR 转写既有件",
        )

    if inp.kind == MODE_VIDEO:
        native_ok = (
            inp.native_supported
            and inp.is_local
            and _within_size(inp.size_bytes, inp.max_mb)
        )
        if native_ok:
            return PreprocessPlan(
                kind=MODE_VIDEO,
                capability_id=CAP_VIDEO_UNDERSTAND,
                route=ROUTE_NATIVE,
                native_part_type="video_url",
                steps=("native_video_part",),
                reason="声明支持原生视频且本机在限内：直挂原生部件，跳过抽帧",
                metadata={"max_mb": inp.max_mb},
            )
        return PreprocessPlan(
            kind=MODE_VIDEO,
            capability_id=CAP_VIDEO_UNDERSTAND,
            route=ROUTE_FRAME_EXTRACT,
            native_part_type="",
            steps=("frame_extract", "vlm_brief"),
            reason="未声明原生/非本机/超限：回落抽帧+VLM 简报既有件",
        )

    # 图像：复用视觉这条腿，不碰图像生成。
    return PreprocessPlan(
        kind=MODE_IMAGE,
        capability_id=CAP_IMAGE_UPSCALE,
        route=ROUTE_UPSCALE if inp.want_upscale else ROUTE_PLAIN,
        native_part_type="",
        steps=("upscale", "vision_describe") if inp.want_upscale else ("vision_describe",),
        reason="图像理解走视觉能力（识别/归一），绝不走生成"
        + ("；请求了放大前置步" if inp.want_upscale else ""),
    )


# ===========================================================================
# 三枚能力声明（CREATION 族，指向既有真身；禁平行造轮子）
#
# 为什么是 spec 而非 CapabilityDescriptor：常驻门
# tests/test_capability_single_registration.py::test_no_second_descriptor_registration_site
# 锁死「descriptor 构造点只准存在于唯一壳 capability_protocols.py」。本席禁改该壳（且它
# 正被他席在飞改动），故此处只出**声明数据**（family/title/协议/implementation_ref/健康/
# 降级/notes），进入唯一表的转写动作交注册面 owner 在干净树做（见 WIRING_COORDINATES）。
# 这样既落「三枚能力」的可测声明，又不违「descriptor authoring 面唯一」不变量。
# ===========================================================================

_VISION_REF = "plugins/bot_unified_runtime/domains/media/ingest/vision_describe.py"
_TRANSCRIBE_REF = "plugins/bot_unified_runtime/domains/media/ingest/transcribe.py"
_VIDEO_REF = "plugins/bot_unified_runtime/domains/media/ingest/video_understanding.py"


@dataclass(frozen=True)
class ModalityCapabilitySpec:
    """一枚接货能力的声明（非 gated；owner 转录成唯一壳的 CapabilityDescriptor）。

    ``implementation_ref`` 一律指既有真身（``transcribe_audio`` / ``build_video_brief`` /
    ``describe_images``），**不指本模块新写的第二实现**——本模块只有委托 handler，真身才是
    「怎么算」的唯一家（禁第二真身红线）。``family``/``health_default`` 用字符串承载族名/
    健康态名，转录时由 owner 映射成 ``CapabilityFamily``/``CapabilityHealth`` 枚举。
    """

    capability_id: str
    title: str
    family: str  # "creation"
    input_protocol: str
    output_protocol: str
    implementation_ref: str
    config_keys: tuple[str, ...]
    fallback: str  # honest_degrade 单链条目
    health_default: str  # not_configured / unknown
    notes: str


def modality_capability_specs() -> tuple[ModalityCapabilitySpec, ...]:
    """三枚接货能力声明（供注册面 owner 转录进唯一壳 DESCRIPTOR_BUILDERS）。"""
    return (
        ModalityCapabilitySpec(
            capability_id=CAP_AUDIO_TRANSCRIBE,
            title="语音转文字（接货腿）",
            family="creation",
            input_protocol="creation.v1 AudioIntakeRequest{audio_source,format,native}",
            output_protocol="creation.v1{text|native_part}",
            implementation_ref=f"{_TRANSCRIBE_REF}#transcribe_audio",
            config_keys=("bot_asr_enabled", "bot_asr_model_registry"),
            fallback="honest_degrade:转写失败返回空说明，不阻断不冒充",
            health_default="not_configured",
            notes=(
                "接货腿声明：原生支复用 build_native_audio_part、回落支复用 transcribe_audio "
                "真身（不二次实现 ASR/抽特征）。通电口见 WIRING_COORDINATES。"
            ),
        ),
        ModalityCapabilitySpec(
            capability_id=CAP_VIDEO_UNDERSTAND,
            title="视频理解（接货腿）",
            family="creation",
            input_protocol="creation.v1 VideoIntakeRequest{video_source,native}",
            output_protocol="creation.v1{brief_text|native_part,signals}",
            implementation_ref=f"{_VIDEO_REF}#build_video_brief",
            config_keys=("bot_video_understanding_enabled", "bot_video_max_frames"),
            fallback="honest_degrade:全部信号缺失返回空简报+说明",
            health_default="unknown",
            notes=(
                "接货腿声明：原生支复用 build_native_video_part、回落支复用 "
                "build_video_brief/_extract_video_frames 抽帧件（不二次实现抽帧）。"
            ),
        ),
        ModalityCapabilitySpec(
            capability_id=CAP_IMAGE_UPSCALE,
            title="图像理解/放大（接货腿，走视觉非生成）",
            family="creation",
            input_protocol="creation.v1 ImageIntakeRequest{image_urls,want_upscale}",
            output_protocol="creation.v1{description,normalized_image_urls?}",
            implementation_ref=f"{_VISION_REF}#describe_images",
            config_keys=("bot_vision_enabled", "bot_vision_model_registry"),
            fallback="honest_degrade:识别失败返回空说明，不冒充成功",
            health_default="not_configured",
            notes=(
                "接货腿声明：图像理解复用视觉这条腿（describe_images/归一），绝不复用图像生成 "
                "creation.image.generate（两条不同路，红线）。无独立放大 provider 时诚实按识别路径。"
            ),
        ),
    )


# ===========================================================================
# 委托型 handler（直呼既有件；缺依赖诚实 UNAVAILABLE；本席离线可测）
# ===========================================================================


def _unavailable(capability_id: str, reason: str) -> InvocationResult:
    return InvocationResult(
        capability_id=capability_id,
        status=InvocationStatus.UNAVAILABLE,
        detail=reason,
    )


def handle_audio_transcribe(
    source: str,
    *,
    plan: PreprocessPlan,
    asr_provider: Any = None,
    timeout_seconds: float = 20.0,
) -> InvocationResult:
    """音频接货：原生支构造 ``input_audio`` 部件、回落支调既有 ASR 真身。

    两条路都不在本模块二次实现——分别委托 ``build_native_audio_part`` 与
    ``transcribe_audio``（真身）。缺 provider 且非原生 → 诚实 UNAVAILABLE。
    """
    from plugins.bot_unified_runtime.domains.media.ingest.transcribe import (
        build_native_audio_part,
        transcribe_audio,
    )

    if plan.route == ROUTE_NATIVE:
        part = build_native_audio_part(source, max_mb=plan_metadata_float(plan, "max_mb"))
        if part is None:
            return _unavailable(CAP_AUDIO_TRANSCRIBE, "原生部件构造返回 None（非本机/超限/容器不在册）")
        return InvocationResult(
            capability_id=CAP_AUDIO_TRANSCRIBE,
            status=InvocationStatus.OK,
            data={"native_part": part},
            via="transcribe.build_native_audio_part",
        )

    if asr_provider is None:
        return _unavailable(CAP_AUDIO_TRANSCRIBE, "asr_provider 未注入且非原生路径")
    text = transcribe_audio(asr_provider, audio_source=source, timeout_seconds=timeout_seconds)
    if not text:
        return InvocationResult(
            capability_id=CAP_AUDIO_TRANSCRIBE,
            status=InvocationStatus.DEGRADED,
            detail="转写返回空（不阻断、不冒充成功）",
            via="transcribe.transcribe_audio",
        )
    return InvocationResult(
        capability_id=CAP_AUDIO_TRANSCRIBE,
        status=InvocationStatus.OK,
        data={"text": text},
        via="transcribe.transcribe_audio",
    )


def handle_video_understand(
    source: str,
    *,
    plan: PreprocessPlan,
    vision_provider: Any = None,
    asr_provider: Any = None,
    config: Any = None,
    max_mb: float = 20.0,
) -> InvocationResult:
    """视频接货：原生支构造 ``video_url`` 部件、回落支调既有抽帧+VLM 真身。"""
    from plugins.bot_unified_runtime.domains.media.ingest.video_understanding import (
        build_native_video_part,
        build_video_brief,
    )

    if plan.route == ROUTE_NATIVE:
        part = build_native_video_part(source, plan_metadata_float(plan, "max_mb"))
        if part is None:
            return _unavailable(CAP_VIDEO_UNDERSTAND, "原生视频部件返回 None（非本机/超限）")
        return InvocationResult(
            capability_id=CAP_VIDEO_UNDERSTAND,
            status=InvocationStatus.OK,
            data={"native_part": part},
            via="video_understanding.build_native_video_part",
        )

    if config is None or vision_provider is None:
        return _unavailable(CAP_VIDEO_UNDERSTAND, "config/vision_provider 未注入且非原生路径")
    brief = build_video_brief(
        config,
        vision_provider=vision_provider,
        asr_provider=asr_provider,
        video_source=source,
    )
    if not brief.text:
        return InvocationResult(
            capability_id=CAP_VIDEO_UNDERSTAND,
            status=InvocationStatus.DEGRADED,
            detail="视频简报为空（信号缺失，诚实不冒充）",
            via="video_understanding.build_video_brief",
        )
    return InvocationResult(
        capability_id=CAP_VIDEO_UNDERSTAND,
        status=InvocationStatus.OK,
        data={"brief_text": brief.text, "signals": dict(brief.signals)},
        via="video_understanding.build_video_brief",
    )


def handle_image_upscale(
    image_urls: list[str],
    *,
    plan: PreprocessPlan,
    vision_provider: Any = None,
    query_text: str = "",
) -> InvocationResult:
    """图像接货：走视觉理解这条腿（复用 ``describe_images``）；**不碰图像生成**。"""
    from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
        describe_images,
    )

    if not image_urls:
        return _unavailable(CAP_IMAGE_UPSCALE, "无图片 URL")
    if vision_provider is None:
        return _unavailable(CAP_IMAGE_UPSCALE, "vision_provider 未注入（无放大 provider 时亦按此诚实退让）")
    text = describe_images(vision_provider, image_urls=list(image_urls), query_text=query_text)
    if not text:
        return InvocationResult(
            capability_id=CAP_IMAGE_UPSCALE,
            status=InvocationStatus.DEGRADED,
            detail="视觉识别返回空（不冒充成功；无放大 provider 时不产放大图）",
            via="vision_describe.describe_images",
        )
    return InvocationResult(
        capability_id=CAP_IMAGE_UPSCALE,
        status=InvocationStatus.OK,
        data={"description": text},
        via="vision_describe.describe_images",
    )


def plan_metadata_float(plan: PreprocessPlan, key: str) -> float:
    """从计划 metadata 安全取 float（缺省回退 20.0，与既有原生预算一致）。"""
    try:
        return float(plan.metadata.get(key, 20.0))
    except (TypeError, ValueError):
        return 20.0


# ===========================================================================
# 动态开关读取（照 chat.vision 的 get_or 语义：不写死值、不建第二张表）
# ===========================================================================


def feature_gate_enabled(
    feature_id: str,
    *,
    config: Any = None,
    settings_get: Callable[[str, bool], bool] | None = None,
    default: bool = False,
) -> bool:
    """运行时现读一枚执行开关是否放行。

    与 ``chat.py`` 里 ``get_or("BOT_VISION_ENABLED", effective_vision_enabled)`` 同构：
    优先经注入的 ``settings_get(env_key, default)`` 现读（支持热改、运行时覆盖优先），
    无 settings 通道时回退 config 属性 ``bot_<feature>``，再回退调用方给的 default。
    **绝不在本模块写死 True/False**，也**不另立一张开关表**——门 id 的唯一真相仍是
    中央唯一表（见 ``derive_gate_feature_id`` 与 WIRING_COORDINATES.chat_gate_registration）。
    """
    env_key = "BOT_" + _feature_core(feature_id).replace(".", "_").upper() + "_ENABLED"
    if settings_get is not None:
        try:
            return bool(settings_get(env_key, default))
        except (KeyError, OSError, TypeError, ValueError):
            logger.debug("feature gate settings read failed key=%s; falling back to env", env_key)
    if config is not None:
        attr = "bot_" + _feature_core(feature_id).replace(".", "_") + "_enabled"
        value = getattr(config, attr, None)
        if value is not None:
            return bool(value)
    return bool(default)


def _feature_core(feature_id: str) -> str:
    """去掉 ``bot.plugin.`` / ``bot.`` 前缀，留纯特性名（用于 env 键/属性名换算）。"""
    for prefix in ("bot.plugin.", "bot."):
        if feature_id.startswith(prefix):
            return feature_id[len(prefix) :]
    return feature_id


# ===========================================================================
# modality_preprocess_jobs：经队列的预处理作业表（自建自管，不碰 config.py）
# ===========================================================================

_STATUS_QUEUED = "queued"
_STATUS_DONE = "done"
_STATUS_FAILED = "failed"
_STATUS_UNAVAILABLE = "unavailable"


@contextmanager
def _connect(db_path: str):
    """SQLite 连接出口必关（#46 教训：``with conn`` 只 commit 不 close，
    轮询 + 现读会按调用数累积句柄，Windows 上表现为库文件删不掉）。"""
    conn = sqlite3.connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


class ModalityPreprocessJobStore:
    """多模态预处理队列作业表：一作业一行、幂等按 job_id、终态诚实四态。

    ``db_path`` 由调用方注入（本席禁改 config.py 加键）；缺省落 runtime data 下的
    ``modality_preprocess.sqlite3``（仅建表用，不猜任何业务数据）。
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with _connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS modality_preprocess_jobs (
                    job_id       TEXT PRIMARY KEY,
                    session_key  TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    modality     TEXT NOT NULL,
                    route        TEXT NOT NULL,
                    source_ref   TEXT NOT NULL DEFAULT '',
                    status       TEXT NOT NULL,
                    summary      TEXT NOT NULL DEFAULT '',
                    detail       TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mpj_session "
                "ON modality_preprocess_jobs (session_key, updated_at)"
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def enqueue(
        self,
        *,
        job_id: str,
        plan: PreprocessPlan,
        source_ref: str = "",
        group_id: str = "",
        user_id: str = "",
        session_key: str = "",
    ) -> str:
        """建/更新一条作业（同 job_id 幂等：存在即刷新 updated_at 与 route）。"""
        key = session_key or build_session_key(group_id, user_id)
        now = self._now()
        with _connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO modality_preprocess_jobs
                    (job_id, session_key, capability_id, modality, route,
                     source_ref, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    route=excluded.route,
                    source_ref=excluded.source_ref,
                    updated_at=excluded.updated_at
                """,
                (
                    job_id,
                    key,
                    plan.capability_id,
                    plan.kind,
                    plan.route,
                    source_ref,
                    _STATUS_QUEUED,
                    now,
                    now,
                ),
            )
        return key

    def mark_result(self, job_id: str, result: InvocationResult) -> None:
        """把 handler 的执行信封终态写回作业（四态映射，绝不吞成 done）。"""
        status = {
            InvocationStatus.OK: _STATUS_DONE,
            InvocationStatus.FALLBACK_OK: _STATUS_DONE,
            InvocationStatus.DEGRADED: _STATUS_DONE,
            InvocationStatus.FAILED: _STATUS_FAILED,
            InvocationStatus.TIMEOUT: _STATUS_FAILED,
            InvocationStatus.UNAVAILABLE: _STATUS_UNAVAILABLE,
            InvocationStatus.NOT_CONFIGURED: _STATUS_UNAVAILABLE,
        }.get(result.status, _STATUS_FAILED)
        summary = ""
        data = result.data or {}
        for key in ("text", "brief_text", "description"):
            if data.get(key):
                summary = str(data[key])
                break
        with _connect(self._db_path) as conn:
            conn.execute(
                "UPDATE modality_preprocess_jobs "
                "SET status=?, summary=?, detail=?, updated_at=? WHERE job_id=?",
                (status, summary, result.detail or "", self._now(), job_id),
            )

    def recent_jobs(self, session_key: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with _connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM modality_preprocess_jobs "
                "WHERE session_key=? ORDER BY updated_at DESC LIMIT ?",
                (session_key, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]


# ===========================================================================
# 记忆回写：复用单一事实总线（不建第二真身；会话作用域走 session_keys）
# ===========================================================================


def absorb_preprocessed_summary(
    memory_bus: Any,
    *,
    owner_id: str,
    subject_user_id: str,
    session_id: Any,
    summary: str,
    confidence: float = 0.7,
) -> Any:
    """把一条预处理产出的「材料」沉淀进 v2 记忆总线。

    仅当注入的 ``memory_bus``（由 ``memory_bus_v2.build_memory_bus(config)`` 造）存在才写；
    总线关/未配库 → 调用方给 None，本函数直接退让返回 None（不阻断、不自造第二套存储）。
    provenance 走 ``PROVENANCE_DERIVED``（归纳侧，非用户第一手声明），作用域经总线
    ``derive_scope`` 从 session_id 派生——会话键归一化只在 session_keys/总线内做。
    """
    if memory_bus is None:
        return None
    body = (summary or "").strip()
    if not body:
        return None
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
        PROVENANCE_DERIVED,
    )

    return memory_bus.absorb(
        owner_id=owner_id,
        subject_user_id=subject_user_id,
        text=body,
        session_id=session_id,
        category="modality",
        confidence=confidence,
        provenance=PROVENANCE_DERIVED,
        source="modality_preprocess",
    )


__all__ = [
    "CAP_AUDIO_INPUT",
    "CAP_AUDIO_TRANSCRIBE",
    "CAP_IMAGE_UPSCALE",
    "CAP_VIDEO_UNDERSTAND",
    "CAP_VIDEO_UNDERSTANDING",
    "GATE_AUDIO_INPUT",
    "GATE_VIDEO_UNDERSTANDING",
    "WIRING_COORDINATES",
    "ModalityCapabilitySpec",
    "ModalityInput",
    "ModalityPreprocessJobStore",
    "PreprocessPlan",
    "absorb_preprocessed_summary",
    "derive_gate_feature_id",
    "feature_gate_enabled",
    "handle_audio_transcribe",
    "handle_image_upscale",
    "handle_video_understand",
    "modality_capability_specs",
    "preprocess_for_modality",
]

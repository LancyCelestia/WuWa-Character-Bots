"""creation.image 绘图 provider 适配器协议 + 离线 mock + 中央回调口（S09 落码，目标 4）。

兑现 ``reserved_provider.py:15-19`` 散文承诺的 "U4 装配缝"：本件把绘画对接点所需的
**执行体腿**补齐到协议完整——``ImageProvider`` 适配器协议本体（submit/poll/cancel/
capabilities）、一个确定性零网络 ``MockImageProvider``、以及供中央注册表回调的
``handle(request)``。语音侧同构先例见 ``domains/creation/tts/engine_provider.py``（S07）。

四条铁律（越界即假绿，本席按 ``tests/test_creation_image_protocol.py`` 自锁）：

1. **零网络 / 零真实出图**——本文件不建 HTTP 客户端、不落盘、不调任何绘图后端；
   mock 只是"把协议跑通一遍"的确定性替身，其产物**永不**按真实计费记账。
2. **零第二真身 / 零重哈希**——资产引用与溯源位复用 ``_common`` 单一 DTO；本文件零
   ``hashlib``、零 ``sha256(`` 手抄（域内 ``test_creation_domain_does_not_rehash_locally``
   执法）。mock 的产物摘要 ``content_sha256`` 诚实留 ``None``（不落真字节即算不出），
   ``provenance.prompt_digest`` 用**明确标注的 mock 占位常量**，绝不冒充真摘要算法。
3. **mock 绝不当真实 provider**（本席注毒点②）——``select_image_provider`` 生产路径
   **永不**返回 mock；mock 只能由调用方经 ``context["image_provider"]`` 显式注入。
   handler 对"离线 mock 注入"产 **DEGRADED**（诚实降级，via 含 ``offline``），
   对"真实 provider"才产 OK；把这条判定拆掉 → mock 被记成真实生成 → 注毒必红。
4. **fail-closed 诚实缺位**——判定"是否已配 provider"的键 ``bot_creation_image_provider``
   **已在 ``config.py`` 登记**（缺省空串；本席现算 ``Config.model_fields`` 复核，
   在册性常驻锁＝``tests/test_creation_reserved_health_alert.py``）；provider_configured
   仅在键非空时 True。工厂 ``provider_factory.PROVIDER_REGISTRY`` 目前为空（全仓无真实绘图后端
   载体）⇒ 填了键也派发出 ``unknown_provider`` ⇒ :func:`select_image_provider` 返 ``None`` ⇒
   未注入 provider 时恒 ``UNAVAILABLE``，并按 E5 把"未配置/无适配器"的**可归因串 + 异常**
   一并交回中央信封：串＝``reserved_provider.not_wired_detail``（原因＋待配**键名**、零值），
   异常＝:class:`CreationImageNotWired` 塞 ``INVOKER_ERROR_DATA_KEY``。
   今天真在跑的可见性两条：审计 ``detail``、巡检告警；卡片的 ``raise`` 腿要等 caller
   （可达性账见 :class:`CreationImageNotWired` 与 SEAT-S115 §1）。

依赖方向：中央执行信封类型只在函数体内延迟 import（与 S07 同惯例）；本件只被中央
注册表回调，描述符**构造**仍唯一住中央壳。生产调用入口归控制面（S08 地盘，本席未
授权触碰）⇒ 落码后"今天能被真调"仍不成立，只在报告如实记，见 SEAT-S09 §残项。

── SEAT-S89 补牙（八段逐段对账抓出的四处"在册无牙"，本件是三处的现场）────────────
前八段的账记在 ``contracts`` 里、看起来齐了，但**执行路径不读它**的字段有四处，本件
是其中三处的唯一可能读点（缺一即装饰）：
① ``outcome.error_code`` → 此前被整个丢掉 ⇒ 四码目录在绘画路径上从未可达；现已回填
   ``CreationJob.error_code`` 并写进非成功终态原因串；
② ``CreationJob.provider_operation`` → 文档自称"对账唯一抓手"，而句柄就在 ``handle``
   手上却不回填 ⇒ ``job_store`` 那张 operation 索引永远为空；现已回填；
③ ``outcome.asset`` 单数 ⇒ ``ImageJobRequest.count``（1..2）在适配器面上**结构上不可
   表达**，且计量恒写 1 张 ⇒ "多图按实结算"不可执行；现改元组 + 超发拒 + 按实记账；
④ ``outcome.state: Any`` ⇒ 真适配器回裸字符串 ``"succeeded"`` 会被 ``is`` 判成未成功、
   悄悄降成 DEGRADED——即"mock 过"推不出"真 provider 可用"（代理指标当结论）。
   现构造期拒非枚举终态，并删掉 ``getattr(state,'value',state)`` 那两处兜底（它们正是
   蒙混通道）。第四处（guidance 无交集闸）落在 ``contracts.ImageProviderCapabilities``。
四条各有常驻锁，见 ``tests/test_creation_protocol_segment_ledger.py``。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # 仅注解：运行期不在模块期触碰中央层（离线导入探针纪律）
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationResult,
        InvocationStatus,
    )

    from .._common.contracts import (
        CreationErrorCode,
        CreationJobState,
    )
    from .contracts import (
        ImageAssetRecord,
        ImageJobRequest,
        ImageProviderCapabilities,
    )

# 域内相对 import **允许在模块期**（``test_v21_creation_skeleton`` 的禁止面是
# nonebot/网络/线程那族，``node.level > 0`` 明确放行）；这里必须是模块期，
# 因为「继承」发生在 class 语句执行时——放进函数体就只能把类定义搬进函数，
# 那是比"早 import 一个纯叶子域件"更坏的形态。
from ..reserved_provider import CreationNotWired

__all__ = [
    "CreationImageNotWired",
    "ImageProvider",
    "ImageProviderOutcome",
    "MockImageProvider",
    "handle",
    "resolve_job_request",
    "select_image_provider",
]

#: mock 占位提示词摘要（64 hex，形态合法但**非真算**——见铁律 2）。真实 provider 由
#: 其自身摘要口填真值；本常量只用于把溯源 DTO 跑通一遍，且只在 mock 路径出现。
_MOCK_PROMPT_DIGEST = "0" * 64

#: 离线 mock 跑通后的 job 快照普通键（**不是** ``PRESENTATION_DATA_KEY``：DEGRADED 属非成功
#: 终态、信封不变量禁止携带呈现载荷）。只作协议自证/取证，绝不进出站或任何呈现面。
_MOCK_RESULT_DATA_KEY = "creation_image_offline_mock_result"


class CreationImageNotWired(CreationNotWired):
    """绘图对接点未配置 / 未装配适配器（"缺位可见"用，E5）。

    与 ``CapabilityTimeout`` 同族：作为异常塞进信封 ``data[INVOKER_ERROR_DATA_KEY]``，
    该 key 的读者（层 1 ``orchestrated_command._step``）见到 ``BaseException`` 会无条件
    ``raise`` → 走 ``pipeline._internal_error`` 诊断卡旁路。终态仍是 ``UNAVAILABLE``
    （不新增第三种结果类型），只是多挂一条可归因的异常。

    ⚠ **可达性如实说**（SEAT-S115 现算，别把这句读成"卡一定出"）：``_step`` 只服务
    ``_route_execution_adapters()`` 里 adapter∈{command,prepared} 的能力，而本能力是
    **直接注册的 handler**（非路由命令形）⇒ 今天这条 raise 腿在绘画路径上**没有读者**；
    ``creation.image.generate`` 全树也没有任何生产调用点。于是"缺位必须可见"目前实际成立的是
    两条：①中央**审计**行（invoker 把 ``detail`` 原样入 ``CapabilityAuditRecord``）
    ②**巡检告警**（``reserved_health_alert.patrol_reserved_health``，S102 落根）。
    载荷留在信封里不是装饰——它是"任一 caller 一接就出卡"的前半段；后半段的补丁文本在
    ``SEAT-S115``/``SEAT-S132`` §3（禁动中央与根 ⇒ 本席不落）。
    """


@runtime_checkable
class ImageProvider(Protocol):
    """绘图 provider 适配器协议本体（八段配套件 · SEAT-S04 FP-S04-1 补齐）。

    四方法即中央执行缝需要的最小面；``offline_mock`` 是**判别位**：真实 provider 恒
    False，只有测试替身返回 True——handler 据此把 mock 结果记为 DEGRADED 而非真实 OK。
    实现方零网络承诺由装配期约定，不在协议里执法（协议只声明形态）。
    """

    @property
    def offline_mock(self) -> bool: ...

    def capabilities(self) -> ImageProviderCapabilities: ...

    def submit(self, job: ImageJobRequest) -> str: ...

    def poll(self, operation: str) -> ImageProviderOutcome: ...

    def cancel(self, operation: str) -> bool: ...


class ImageProviderOutcome:
    """provider 一次轮询的返回：状态 + （终态时的）产物**组** + 失败码。

    刻意用轻量对象而非再造 DTO：状态复用共用状态机 ``CreationJobState``，产物复用
    ``ImageAssetRecord``，失败码复用 ``CreationErrorCode``——零新真身。

    **构造期 fail-closed 三判（SEAT-S89 补牙，此前一处都没有）**：
    ① ``state`` 必须是契约枚举本体，不接受裸字符串——此前它是 ``Any``，真实适配器回
      ``"succeeded"`` 会被 ``handle`` 的 ``is`` 判成"未成功"、悄悄降成 DEGRADED，
      即 mock（回枚举）与真适配器（可回字符串）**形状不一致而无人报错**；
    ② ``error_code`` 必须在 ``CREATION_ERROR_CATALOG`` 内——不接受编一个近似的码，
      也不允许它悄悄丢掉（此前 ``handle`` 整个不读它）；
    ③ 产物是**元组**：``count≤2`` 的一次请求可能交付 0..2 件，单数字段让"按实结算"
      与"不得超发"两句话都无处落脚（此前 ``asset`` 一枚 ⇒ ``count`` 结构上不可表达）。
    三条都只判**形态/在册性**，不复制 ``CreationJob._doctrines`` 的配对教义——那条规则
    的家在契约，本件不立第二把尺子。
    """

    __slots__ = ("assets", "error_code", "state")

    def __init__(
        self,
        state: CreationJobState,
        *,
        assets: tuple[ImageAssetRecord, ...] = (),
        error_code: CreationErrorCode | None = None,
    ) -> None:
        # 函数体内取：本件对域内契约同样守"模块期零依赖"惯例（与 poll/handle 同一手法）。
        from .._common.contracts import CREATION_ERROR_CATALOG
        from .._common.contracts import CreationJobState as _State

        if not isinstance(state, _State):
            raise TypeError(
                f"provider 终态必须是契约状态机 CreationJobState，收到 {type(state).__name__}"
                "（值不回显，防把 provider 内部串带进异常面）"
            )
        if error_code is not None and error_code not in CREATION_ERROR_CATALOG:
            raise ValueError(
                f"provider 失败码 {str(error_code)[:64]!r} 不在册"
                "（唯一家 CREATION_ERROR_CATALOG；不认的码不折叠成近似的码、不静默丢弃）"
            )
        self.state = state
        self.assets = tuple(assets)
        self.error_code = error_code


class MockImageProvider:
    """确定性离线绘图 provider：把协议跑通，产物明确标注 mock、绝不冒充真实出图。

    ``clock`` 注入固定时刻以保证 ``generated_at`` 可复现；无任何外部依赖。
    """

    def __init__(
        self,
        *,
        principal: str = "mock-principal",
        clock: datetime | None = None,
    ) -> None:
        self._principal = principal
        self._clock = clock or datetime(2000, 1, 1, tzinfo=timezone.utc)
        self._jobs: dict[str, ImageJobRequest] = {}
        self._cancelled: set[str] = set()
        self._seq = 0

    @property
    def offline_mock(self) -> bool:
        return True

    def capabilities(self) -> ImageProviderCapabilities:
        from .contracts import IMAGE_MAX_STEPS
        from .contracts import ImageProviderCapabilities as Caps

        return Caps(
            provider="mock-image",
            # 上限只引契约常量，不抄字面量：抄一份数字＝第二真身（本件家规 3）。
            max_steps=IMAGE_MAX_STEPS,
            sizes=("1024x1024", "512x512"),
            resolution_tiers=("square",),
            supported_tasks=("text_to_image", "image_to_image", "inpaint"),
            # max_guidance 刻意**不声明**（None）：mock 不打折 CFG，也就没资格声称自己
            # 有一个上界。"不声明＝沿用契约全局域"这条分支因此由 mock 常驻覆盖，
            # "声明了就必须收紧"那条分支由 tests/test_creation_protocol_segment_ledger.py
            # 的另一枚 provider 覆盖——两臂都有真实读点，缺一条就是空跑。
        )

    def submit(self, job: ImageJobRequest) -> str:
        self._seq += 1
        operation = f"mock-op-{self._seq}"
        self._jobs[operation] = job
        return operation

    def poll(self, operation: str) -> ImageProviderOutcome:
        from .._common.contracts import AssetRef, CreationJobState, CreationProvenance
        from .contracts import ImageAssetRecord

        job = self._jobs.get(operation)
        if job is None:
            return ImageProviderOutcome(CreationJobState.UNKNOWN)
        if operation in self._cancelled:
            return ImageProviderOutcome(CreationJobState.CANCELLED)
        width, _, height = job.size.partition("x")
        asset = ImageAssetRecord(
            asset_id=AssetRef(asset_id=f"mock-asset-{operation}"),
            width=int(width),
            height=int(height),
            real_mime="image/png",
            bytes_size=1,
            magic_verified=True,
            exif_sanitized=True,
            review_approved=True,
            # 离线 mock 不落真字节 → 内容摘要诚实留空（不回填假值）。
            content_sha256=None,
            provenance=CreationProvenance(
                generator_principal=self._principal,
                provider="mock-image",
                model=job.model,
                prompt_digest=_MOCK_PROMPT_DIGEST,
                generated_at=self._clock,
                license_statement="离线 mock 产物：不可用于真实分发",
                exif_stripped=True,
                # 水印半腿**明写**而不靠缺省：mock 既不打可见标也不写隐式标识，
                # 把"没有标"写成一次显式声明，才让"标了却没标"那种谎有对照物可测。
                # 真实 provider 接上时若真打了标，须同时填 applied 与 actor（契约互锁）。
                marking="none",
                marking_applied=False,
            ),
        )
        # 单件产物也要走元组：交付面上"一件"与"恰好只允许一件"是两回事（判据③）。
        return ImageProviderOutcome(CreationJobState.SUCCEEDED, assets=(asset,))

    def cancel(self, operation: str) -> bool:
        if operation not in self._jobs:
            return False
        self._cancelled.add(operation)
        return True


def resolve_job_request(payload: dict[str, Any]) -> tuple[ImageJobRequest | None, str]:
    """从请求载荷取 ``ImageJobRequest``，交契约**自己**过一遍；本件不抄第二份判据。"""
    from pydantic import ValidationError

    from .contracts import ImageJobRequest

    raw = payload.get("job")
    if raw is None:
        return None, "缺少 job：绘图请求须携带 ImageJobRequest（或其 model_dump）"
    try:
        if isinstance(raw, ImageJobRequest):
            return raw, ""
        return ImageJobRequest.model_validate(raw), ""
    except (TypeError, ValidationError) as exc:
        return None, f"job 形请求未过契约自验：{type(exc).__name__}"


def select_image_provider(config: Any, request: CapabilityRequest) -> ImageProvider | None:
    """按 config 选择真实 provider；未登记/未选/工厂给不出适配器一律 None（fail-closed，绝不猜）。

    选择顺序（S69 现算收口）：

    1. 调用方经 ``request.context["image_provider"]`` **显式注入**的适配器（离线测试 /
       未来装配专用缝）——直接返回；
    2. 键未配（``reserved_provider.provider_configured`` False）⇒ ``None``；
    3. 键已配 ⇒ 交**唯一派发口** :func:`provider_factory.build_image_provider` 现算：
       工厂判 ``wired`` 才给适配器，否则 ``None``。此前工厂是死件（select 从不引用它，
       即便 ``PROVIDER_REGISTRY`` 登记了真实适配器也拿不到＝简报断点①），本行把它接上。

    真身路径今天的实况：``bot_creation_image_provider`` 已在 ``config.py`` 登记（缺省空串）、
    工厂已落地，但 ``PROVIDER_REGISTRY`` 仍为空（全仓无真实绘图后端客户端载体）⇒ 填了键也走
    ``unknown_provider`` ⇒ ``None`` ⇒ handler 诚实 ``UNAVAILABLE``。唯一能拿到 provider 的
    现役通道仍是 ①的显式注入缝——且本函数**绝不**把内置 mock 当真实 provider 返回（铁律 3；
    工厂侧亦按 ``offline_mock`` 判别位拒收 mock，双重不返）。
    """
    injected = request.context.get("image_provider")
    if injected is not None:
        return injected  # type: ignore[no-any-return]
    from .. import reserved_provider

    if not reserved_provider.provider_configured(config, request.capability_id):
        return None
    # 键已配：只认工厂"真派发出适配器"的结果，不自建第二条路、不放行半残对象。
    from .provider_factory import build_image_provider

    selection = build_image_provider(config)
    if selection.provider is None:
        # 未 wired（未知选择器 / 注册表为空 / 构造失败 / mock / 协议不合）：交回 handler 诚实说。
        return None
    return selection.provider


def _envelope(
    request: CapabilityRequest,
    status: InvocationStatus,
    *,
    data: dict[str, Any] | None = None,
    detail: str = "",
    via: str,
) -> InvocationResult:
    """构造执行信封（延迟 import 中央类型；非成功态必带诚实说明＝构造期不变量）。

    ``status`` 的注解此前是裸 ``Any``——终态类型是这条链上最要位置之一，写成 ``Any``
    等于把"不许新增第三种结果类型"这句家规从静态检查里也拿掉了（SEAT-S89 顺手补）。
    注解惰性求值（``from __future__ import annotations``），故运行期仍不触中央层。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        InvocationResult,
        InvocationStatus,
    )

    text = str(detail or "").strip()
    if status is not InvocationStatus.OK and not text:
        text = "非成功终态但未给出原因（不应发生：诚实说明缺失）"
    return InvocationResult(
        capability_id=request.capability_id,
        status=status,
        data=dict(data or {}),
        detail=text,
        via=via,
    )


def handle(request: CapabilityRequest) -> InvocationResult:
    """中央注册表回调口（签名对齐 ``HandlerFn``；与 S07 tts handle 同构）。

    终态逐条诚实：
    - 契约不过 / 缺 job → ``FAILED``；
    - 未注入 provider 且"未来键"未配 → ``UNAVAILABLE`` + ``INVOKER_ERROR_DATA_KEY``
      （异常交回层 1 → 诊断卡可见，E5；键配了但无工厂 → 同诚实 ``UNAVAILABLE``）；
    - provider 能力交集不过（task/size/steps/**guidance** 越界）→ ``LIMIT_EXCEEDED``，
      一次都不提交；
    - provider **超发**（交付件数 > 请求 count）→ ``LIMIT_EXCEEDED``，不记账（八段 4b）；
    - 注入的是**离线 mock** → ``DEGRADED``（via 含 ``offline``，绝不记真实计费，铁律 3）；
    - 真实 provider 成功 → ``OK``（生产路径今日不可达，见模块头与 SEAT-S09 残项）；
    - 真实 provider 返回**不合形态**（裸字符串终态／不在册错误码）→ **抛错**交回层 1
      出诊断卡，刻意不洗成 FAILED（见 :meth:`ImageProviderOutcome.__init__` 判据①②）。
    """
    from plugins.bot_unified_runtime.domains.render.plain_text import (
        redact_local_secrets,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        INVOKER_ERROR_DATA_KEY,
        PRESENTATION_DATA_KEY,
        InvocationStatus,
    )

    from .. import reserved_provider
    from .._common.contracts import (
        NON_TERMINAL_JOB_STATES,
        CreationJob,
        CreationJobState,
        UsageLine,
    )
    from .contracts import (
        IMAGE_MAX_REFERENCE_IMAGES,
        ImageAssetRecord,
        delivery_within_count,
        guidance_supported,
        negative_prompt_accepted,
        references_supported,
        size_supported,
        steps_supported,
        task_supported,
    )

    config = request.context.get("config")
    capability_id = request.capability_id

    job, contract_error = resolve_job_request(request.payload or {})
    if contract_error or job is None:
        return _envelope(
            request, InvocationStatus.FAILED, detail=contract_error, via="creation_image_contract"
        )

    provider = select_image_provider(config, request)
    if provider is None:
        # 可归因串的**唯一构造口**在 reserved_provider（与语音通道共用同一把尺子）：
        # 这里再拼一份"待配键"就是第二真身——两通道文案会漂，且已填的键会被再喊成待配。
        detail = reserved_provider.not_wired_detail(config, capability_id)
        return _envelope(
            request,
            InvocationStatus.UNAVAILABLE,
            detail=detail,
            via="creation_image_provider_gate",
            # E5：把"未配置"经已落地通道交回层 1，令诊断卡可见（不改中央文件）。
            # ⚠ 今天这条载荷**尚无读者**命中绘画路径（可达性见 CreationImageNotWired 注解），
            #   可见性的现役两条＝审计 detail + 巡检告警。
            data={INVOKER_ERROR_DATA_KEY: CreationImageNotWired(detail)},
        )

    caps = provider.capabilities()
    if not task_supported(job.task, caps):
        return _envelope(
            request,
            InvocationStatus.LIMIT_EXCEEDED,
            detail=f"provider 不支持任务 {job.task!r}（可用：{sorted(caps.supported_tasks)}）",
            via="creation_image_caps",
        )
    if not size_supported(job.size, caps):
        return _envelope(
            request,
            InvocationStatus.LIMIT_EXCEEDED,
            detail=f"provider 不支持尺寸 {job.size!r}（可用：{sorted(caps.sizes)}）",
            via="creation_image_caps",
        )
    if job.steps is not None and not steps_supported(job.steps, caps):
        return _envelope(
            request,
            InvocationStatus.LIMIT_EXCEEDED,
            detail=f"steps={job.steps} 超 provider 上限 {caps.max_steps}",
            via="creation_image_caps",
        )
    # CFG 交集（八段第 4 段补牙）：provider 声明了 max_guidance 才收紧，没声明就沿用
    # 契约全局域（gt=0/le=IMAGE_MAX_GUIDANCE 已在 DTO 拦过一遍）。这条腿的存在意义不是
    # "多拦一次越界"，而是让 guidance 这个字段**第一次**在执行路径上被读到——在此之前
    # 适配器可以整条忽略它而永不红，那就是"在册无牙"。
    if job.guidance is not None and not guidance_supported(job.guidance, caps):
        return _envelope(
            request,
            InvocationStatus.LIMIT_EXCEEDED,
            detail=f"guidance={job.guidance} 超 provider 声明上限 {caps.max_guidance}",
            via="creation_image_caps",
        )
    # 参考图张数交集（八段第 2 段在执行面的**第一个**按名读点）：修前 job.assets 从头到尾
    # 没有任何一处按名取值，整段只是"契约里有个名字"。
    if not references_supported(len(job.assets), caps):
        ref_ceiling = (
            caps.max_reference_images
            if caps.max_reference_images is not None
            else IMAGE_MAX_REFERENCE_IMAGES
        )
        return _envelope(
            request,
            InvocationStatus.LIMIT_EXCEEDED,
            detail=(
                f"参考图 {len(job.assets)} 张超上限 {ref_ceiling}"
                f"（provider 声明 {caps.max_reference_images!r}，"
                f"契约硬顶 {IMAGE_MAX_REFERENCE_IMAGES}）：一次都不提交"
            ),
            via="creation_image_refs",
        )
    # 负面提示支持性（八段第 3 段在执行面的按名读点）：**明确**不支持才拒；不声明既不拦
    # 也不宣称支持。修前这条字段一路静默进 submit，provider 忽略与否无人可辨＝"安静地没照做"。
    accepted, reject_reason = negative_prompt_accepted(job, caps)
    if not accepted:
        return _envelope(
            request,
            InvocationStatus.LIMIT_EXCEEDED,
            detail=reject_reason,
            via="creation_image_negative_prompt",
        )

    # ⚠ 从这里起 provider 的返回**不合形态**就是抛错、不许就地兜住：
    # ImageProviderOutcome 构造期拒裸字符串终态与不在册错误码（判据①②），异常经
    # INVOKER_ERROR_DATA_KEY 那条已落地通道交回层 1 出诊断卡。刻意不写成
    # try/except→FAILED——把"形状不对的适配器"降级成一条普通失败回执，就是把 loud 的
    # 接线错误洗成安静的业务失败（本仓在主动投递面上为这个付过两次账）。
    operation = provider.submit(job)
    outcome = provider.poll(operation)

    # **边界形态校验**（本席最大一条补牙）：``ImageProvider`` 是 runtime_checkable 协议，
    # isinstance 只查方法名，签名与返回形态一概不管——所以"适配器合面"根本不能证明
    # "它回的东西能用"。更要紧的是：handle 从前直接读 outcome 的属性，于是回鸭子替身
    # （``state="succeeded"`` 字符串）的适配器会被 ``is`` 判成未成功、**静默**降成 DEGRADED：
    # mock 回枚举、真适配器可能回字符串，两者形状不同却只有 mock 那条路被跑过——
    # "mock 通过"于是被当成"真 provider 可用"，正是拿代理指标当结论。
    # 拒收方式选抛、不选就地兜成 FAILED：把接线错误洗成一条普通业务失败，是本仓在主动
    # 投递面上付过两次账的老病；异常走 INVOKER_ERROR_DATA_KEY 那条已落地通道才有诊断卡。
    if not isinstance(outcome, ImageProviderOutcome):
        raise TypeError(
            "provider.poll 必须返回 ImageProviderOutcome，收到 "
            f"{type(outcome).__name__}（鸭子替身不收：裸 state 字符串会静默错判终态）"
        )
    for _asset_row in outcome.assets:
        if not isinstance(_asset_row, ImageAssetRecord):
            raise TypeError(
                "provider 产物必须是 ImageAssetRecord，收到 "
                f"{type(_asset_row).__name__}（裸 dict 等于绕过 magic/EXIF/Review 三闸）"
            )

    if outcome.state in NON_TERMINAL_JOB_STATES:
        # 无 job store / reconcile 真身可跟进在途任务：诚实降级，绝不假终态、不重复提交。
        # 状态取值不再用 getattr(..., 'value', ...) 兜底——那个兜底正是让裸字符串
        # 蒙混过关、把"成功"读成"在途"的通道（判据①拆掉它之后这里必然拿到真枚举）。
        return _envelope(
            request,
            InvocationStatus.DEGRADED,
            detail=f"任务在途（state={outcome.state.value}），"
            "无 job store 可对账，不假终态、不重发",
            via="creation_image_inflight",
        )

    # 超发拦截（count 的第二个真实读点，也是它第一个行为读点）：多给一件就可能多花
    # 一件的钱且无人报错。少给（含 0，失败/取消）合法。判据在契约 delivery_within_count。
    if not delivery_within_count(len(outcome.assets), job.count):
        return _envelope(
            request,
            InvocationStatus.LIMIT_EXCEEDED,
            detail=(
                f"provider 交付 {len(outcome.assets)} 件，超请求件数 {job.count}"
                "：不记账、不对外——超发不是「多给了没关系」"
            ),
            via="creation_image_overdelivery",
        )

    # 计量按**实际交付件数**记账（八段第 6 段"多图按实结算"）：此前恒写 Decimal(1)，
    # 于是"两图一单"与"一图一单"在账上长一样——那句话当时是不可执行的装饰。
    usage: tuple[UsageLine, ...] = ()
    if outcome.assets:
        usage = (
            UsageLine(
                metric="images",
                value=Decimal(len(outcome.assets)),
                unit="images",
                status="measured",
                source=caps.provider,
            ),
        )
    job_dto = CreationJob(
        job_id=operation,
        state=outcome.state,
        updated_at=datetime.now(timezone.utc),
        idempotency_key=job.idempotency_key,
        assets=tuple(asset.asset_id for asset in outcome.assets),
        usage=usage,
        # 失败码交回契约（八段第 7 段补牙）：此前 outcome.error_code 被整个丢弃，
        # 四码目录在绘画执行路径上从未可达——"failed 只与在册错误码并存"那条锁因此
        # 永远只在测试里被手工构造过、从未被真实路径喂过。
        error_code=outcome.error_code,
        # 对账唯一抓手回填（八段第 5 段的载体腿）：句柄就在手上却不写进结果，
        # 等于 job_store 那张 provider_operation 索引永远为空——教义可写不可用。
        provider_operation=operation,
    )
    presented = job_dto.model_dump(mode="json")

    if outcome.state is CreationJobState.SUCCEEDED:
        # 八段第 8 段在执行面的按名读点：**出处全盲的产物不得当成功对外**。
        # 修前 ``provenance`` 只有"闸内"意义（ImageAssetRecord 构造时交叉锁 EXIF），
        # 出口侧从不看它 ⇒ 一条成功产物可以完全不带来源/水印声明而无人报错，正是
        # SEAT-S04 当年点名的"协议若激活，产物将出处全盲"。这里给一个诚实的降级：
        # 产物是真的、但来源不可报 ⇒ DEGRADED 带原因，不假 OK、也不静默外发。
        unattributed = [row for row in outcome.assets if row.provenance is None]
        if unattributed:
            return _envelope(
                request,
                InvocationStatus.DEGRADED,
                detail=(
                    f"provider 交付 {len(outcome.assets)} 件，其中 {len(unattributed)} 件"
                    "不带溯源元数据（provenance=None）：产物在、出处不可报，"
                    "故不对外呈现；补齐来源或明写「无来源可报」后重试"
                ),
                via="creation_image_provenance_gate",
            )
        if getattr(provider, "offline_mock", False):
            # 铁律 3：离线 mock 产物记为 DEGRADED（诚实降级），via 含 offline，绝不冒充真实
            # 计费成功。DEGRADED 属非成功终态、按信封不变量**不得**带呈现载荷，故把 mock 跑通
            # 的 job 快照放在**独立普通键**下（只作协议自证/取证用，不进任何呈现/出站面）。
            return _envelope(
                request,
                InvocationStatus.DEGRADED,
                data={_MOCK_RESULT_DATA_KEY: presented},
                detail="离线 mock 出图：协议跑通，不产生真实绘图、不记账（via 标注 offline）",
                via="creation_image_offline_mock",
            )
        return _envelope(
            request,
            InvocationStatus.OK,
            data={PRESENTATION_DATA_KEY: presented},
            via="creation_image_engine",
        )

    # 非成功终态：把在册错误码一起写进原因串——八段第 7 段"失败语义"的可归因腿。
    # 不带码的"绘图未成功"等于把四码目录读成一句情绪；带码才能力谈"是价没了还是依赖挂了"。
    code_note = f"（code={outcome.error_code}）" if outcome.error_code else "（provider 未给码）"
    reason = redact_local_secrets(f"provider 终态 {outcome.state.value}{code_note}")
    return _envelope(
        request,
        InvocationStatus.FAILED if outcome.state is CreationJobState.FAILED
        else InvocationStatus.DEGRADED,
        detail=f"绘图未成功：{reason}",
        via="creation_image_engine",
    )

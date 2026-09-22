"""creation 生成域共用契约层：任务状态机 / 取消语义 / 计量 / 资产引用 / 请求与产物身份 / 错误目录。

`reserved: 依赖外部 provider 配置，未实现`。本模块是 v21r2-reorg-plan.md §9.1
「任务状态机与 asset 交付共用件」的协议草案，只定义 Pydantic 严格 DTO、协议
常量、枚举与纯函数——零框架、零网络、零线程、零配置读取，可被 importlib
直载探针独立验证（V21-CORE-001 纪律；v21r2-reorg-plan.md §9.4 reserved 契约
形态 lint）。

合同锚点：
- docs/design/v21r2-reorg-plan.md §9.1（creation 域字段级契约草案）
- docs/design/backend-v2-implementation-guide.md §6（严格 DTO 拒未知字段/NaN/
  Infinity）、§7 L198（cancel_requested ≠ cancelled）、§11（L256 TTS/L258 绘图）
- docs/design/backend-v2-product-extensions.md §1（L16 字段表/L23 多单位计费/
  L29 Decimal 禁浮点/L49 确定性算例/L56 多图按实结算/L58 取消保留费用）

与 llm/billing_entities.py 的关系：那边是 V2.1 计费权威实现（已落地段）；
本模块按扩展 §1 语义为 creation 域定义**预留态**计量 DTO——Token 指标在
creation 域永远不得伪造（provider 真报才可携带，否则 not_applicable/unknown，
不得按字符/图片数倒推精确 Token）。字段命名与不变量有意对齐 billing_entities，
收敛到单一来源属激活期席位工作（§10 W-PA 后续波）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# 严格基类（对齐 contracts/envelope.py V21StrictBase 口径）
# ---------------------------------------------------------------------------


class CreationContractBase(BaseModel):
    """creation 域契约严格基类：禁未知字段、禁 NaN/Infinity。

    extra="forbid" 即 §6「未支持参数 422 unsupported_parameter 不静默丢弃」的
    DTO 层机器形态；allow_inf_nan=False 拒 NaN/Infinity。
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _require_aware_utc(name: str, value: datetime) -> datetime:
    """拒绝 naive datetime；aware 值一律归一到 UTC。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} 必须带时区（UTC ISO8601）")
    return value.astimezone(timezone.utc)


def _decimal_no_float(value: object) -> object:
    """金额/计量 value 禁浮点入参（扩展 §1 L29：Decimal 序列化，禁 float）。"""
    if isinstance(value, float):
        raise ValueError(  # noqa: TRY004 - pydantic v2 校验器抛 ValueError 才转 ValidationError
            "金额/计量值禁止浮点入参（用 Decimal 或字符串十进制）"
        )
    return value


def _decimal_finite_nonneg(name: str, value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    try:
        is_finite = value.is_finite()
    except InvalidOperation:  # pragma: no cover - Decimal 构造期已拦
        is_finite = False
    if not is_finite:
        raise ValueError(f"{name} 必须是有限十进制数（拒 NaN/Infinity）")
    if value < 0:
        raise ValueError(f"{name} 必须非负")
    return value


# ---------------------------------------------------------------------------
# 任务状态机与取消语义（§9.1.1 任务状态机段；TTS/绘图共用，§9.1.2 同款）
# ---------------------------------------------------------------------------


class CreationJobState(str, Enum):
    """生成任务状态机：pending→admitted→running→succeeded/failed/cancelled/unknown。

    语义锚点（指南 §7 L198、§11 L256/L258）：
    - ``cancel_requested`` 是请求标记不是状态——``CancelRequest`` 受理只记标记，
      终态仍须等到 succeeded/failed/cancelled/unknown 之一；
    - ``unknown``：已受理但结果未知的任务**不盲重合成/重发**，对账走独立
      reconcile 面，状态机内 unknown 无出边（不得复活）；
    - 取消保留可能已产生的费用（扩展 §1 L58）。
    """

    PENDING = "pending"
    ADMITTED = "admitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


JOB_STATES: frozenset[str] = frozenset(state.value for state in CreationJobState)

TERMINAL_JOB_STATES: frozenset[CreationJobState] = frozenset(
    {
        CreationJobState.SUCCEEDED,
        CreationJobState.FAILED,
        CreationJobState.CANCELLED,
        CreationJobState.UNKNOWN,
    }
)

ALLOWED_JOB_TRANSITIONS: dict[CreationJobState, frozenset[CreationJobState]] = {
    CreationJobState.PENDING: frozenset(
        {CreationJobState.ADMITTED, CreationJobState.FAILED, CreationJobState.CANCELLED}
    ),
    CreationJobState.ADMITTED: frozenset(
        {CreationJobState.RUNNING, CreationJobState.FAILED, CreationJobState.CANCELLED}
    ),
    CreationJobState.RUNNING: frozenset(
        {
            CreationJobState.SUCCEEDED,
            CreationJobState.FAILED,
            CreationJobState.CANCELLED,
            CreationJobState.UNKNOWN,
        }
    ),
    CreationJobState.SUCCEEDED: frozenset(),
    CreationJobState.FAILED: frozenset(),
    CreationJobState.CANCELLED: frozenset(),
    CreationJobState.UNKNOWN: frozenset(),
}

#: 取消语义常量（指南 §7 L198；扩展 §1 L58）。
CANCEL_REQUESTED_IS_NOT_A_STATE = True
CANCEL_MAY_KEEP_COST = True
UNKNOWN_NEVER_AUTO_REDISPATCH = True


def can_transition(current: CreationJobState, target: CreationJobState) -> bool:
    """纯函数：状态迁移合法性（终态无出边；unknown 不复活）。"""
    return target in ALLOWED_JOB_TRANSITIONS[current]


class CancelRequest(CreationContractBase):
    """取消请求：只申请（cancel_requested），不承诺即时 cancelled。"""

    job_id: str = Field(min_length=1, max_length=128)
    requested_by: str = Field(min_length=1, max_length=128)
    reason: str = Field(default="", max_length=512)
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def _aware_requested_at(cls, value: datetime) -> datetime:
        return _require_aware_utc("requested_at", value)


# ---------------------------------------------------------------------------
# 计量 DTO（扩展 §1 L16/L23：多单位计费；Token 不伪造）
# ---------------------------------------------------------------------------

QuantityStatus = Literal["measured", "estimated", "unknown", "not_applicable"]

#: creation 域允许的计量（非 Token）：TTS 取 characters/audio_seconds/requests
#: 子集，绘图取 images/requests 子集（扩展 §1 L23）。
CREATION_METRICS: frozenset[str] = frozenset(
    {"characters", "audio_seconds", "images", "requests"}
)

#: metric → 计量单位（接口不能省略单位让调用方猜）。
CREATION_METRIC_UNITS: dict[str, str] = {
    "characters": "characters",
    "audio_seconds": "seconds",
    "images": "images",
    "requests": "requests",
}

#: Token 指标名：creation 域用量 DTO 内出现即拒绝（防止按字符/图片伪造）。
TOKEN_METRIC_NAMES: frozenset[str] = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_create_tokens",
        "cache_read_tokens",
    }
)


class UsageLine(CreationContractBase):
    """单一计量行：metric+value+unit+status(+tier)。

    不变量（扩展 §1 L16）：``value is None`` ⇔ ``status ∈ {unknown,
    not_applicable}``；measured/estimated 必须携带有限非负 Decimal。
    ``resolution_tier`` 仅绘图分辨率档独立计费有意义（扩展 §1 L23）。
    """

    metric: str = Field(min_length=1, max_length=64)
    value: Decimal | None = None
    unit: str = Field(min_length=1, max_length=32)
    status: QuantityStatus
    source: str = Field(default="", max_length=128)
    resolution_tier: str = Field(default="", max_length=64)

    @field_validator("metric")
    @classmethod
    def _metric_is_creation(cls, value: str) -> str:
        if value in TOKEN_METRIC_NAMES:
            raise ValueError(
                f"creation 域用量禁止 Token 指标 {value!r}（不伪造 Token；"
                "Token 仅 provider 真报时由账本层携带）"
            )
        if value not in CREATION_METRICS:
            raise ValueError(
                f"不支持的计量: {value!r}（合法集合: {sorted(CREATION_METRICS)}）"
            )
        return value

    @field_validator("unit")
    @classmethod
    def _unit_canonical(cls, value: str, info: ValidationInfo) -> str:
        metric = str(info.data.get("metric", ""))
        expected = CREATION_METRIC_UNITS.get(metric)
        if expected is not None and value != expected:
            raise ValueError(f"metric={metric} 的单位必须是 {expected!r}，收到 {value!r}")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def _value_no_float(cls, value: object) -> object:
        return _decimal_no_float(value)

    @field_validator("value")
    @classmethod
    def _value_finite_nonneg(cls, value: Decimal | None, info: ValidationInfo) -> Decimal | None:
        return _decimal_finite_nonneg(f"quantities[{info.data.get('metric')}].value", value)

    @model_validator(mode="after")
    def _status_value_consistent(self) -> UsageLine:
        if self.status in ("unknown", "not_applicable"):
            if self.value is not None:
                raise ValueError(f"status={self.status} 时 value 必须为 null（未知/不适用不得携带数量）")
        else:
            if self.value is None:
                raise ValueError(f"status={self.status} 必须携带 value（未知不是 0）")
        if self.resolution_tier and self.metric != "images":
            raise ValueError("resolution_tier 仅支持 images 指标（分辨率档独立计费）")
        return self


class CostAmount(CreationContractBase):
    """金额：Decimal + ISO 币种，禁浮点（扩展 §1 L29）。"""

    amount: Decimal
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    @field_validator("amount", mode="before")
    @classmethod
    def _amount_no_float(cls, value: object) -> object:
        return _decimal_no_float(value)

    @field_validator("amount")
    @classmethod
    def _amount_finite_nonneg(cls, value: Decimal) -> Decimal | None:
        return _decimal_finite_nonneg("cost.amount", value)


# ---------------------------------------------------------------------------
# 资产引用（V21-FILE-002 面：API 用 asset_id，非服务器路径；指南 §11 L254）
# ---------------------------------------------------------------------------

ASSET_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
#: 绘图输入分辨率上限：≤20MP（指南 §11 L258）。
IMAGE_MAX_INPUT_PIXELS = 20_000_000


class AssetRef(CreationContractBase):
    """受管资产引用：只收 asset_id，拒服务器路径/URL/穿越形态。

    输入图获取走 DownloadBroker（对齐 SEARCH-002 面），不接任意 URL 抓取
    （指南 §11 L258）；``pixel_count`` 由资产元数据带入，超 20MP 拒绝。
    """

    asset_id: str = Field(min_length=1, max_length=128, pattern=ASSET_ID_PATTERN)
    pixel_count: int | None = Field(default=None, ge=1, le=IMAGE_MAX_INPUT_PIXELS)

    @field_validator("asset_id")
    @classmethod
    def _reject_path_like(cls, value: str) -> str:
        if ".." in value or "/" in value or "\\" in value or "://" in value:
            raise ValueError("asset_id 必须是注册表资产标识，不得含路径/URL/穿越形态")
        return value


# ---------------------------------------------------------------------------
# 请求身份与产物身份（2026-09-21 统一波 S-CREATE 补齐 · §9.1 状态机段的可用化前置件）
# ---------------------------------------------------------------------------

#: 幂等键规则版本，写进 preimage 头部。**改口径必须升版**（就地改语义会让历史键
#: 与新键撞同一身份，等于把「同一条请求」的判定悄悄换掉而无人知）。
IDEMPOTENCY_RULE_VERSION = "creation-idem-v1"

#: 键自身所在字段：算 preimage 时必须剔除，否则「先算键再填键」与「先填键再算键」
#: 得到两个不同的身份（幂等键定义了自己的输入里含自己 = 不可复现）。
IDEMPOTENCY_SELF_FIELD = "idempotency_key"

#: 64 位小写十六进制摘要形态。**与中央媒体摘要层的唯一算法输出逐字同形**
#: （真身 ``domains/media/digest.py::media_digest``，蓝图 ``docs/design/media-digest-layer.md``
#: §3.1「sha256 全长 64 hex 小写，截短是消费侧决定」）。
#: creation 域只**声明形态**：域内零 ``hashlib``、绝不重算哈希——重算就是第二套算法家，
#: 正是 Wave G 之后各常驻门在抓的病。装配期由调用方把值算好填进来。
DIGEST64_PATTERN = r"^[0-9a-f]{64}$"

#: 产物内容摘要的**键名**：与渲染收口第三冻结键、TTS 出站部件键同名同义
#: （``domains/render/renderer.py`` 的 ``content_sha256``／``tts.py`` ``audio_part``）。
#: 自造同义键（``sha256``/``digest``/``hash``）= 下游全链认不出，故键名在此钉死。
CONTENT_DIGEST_KEY = "content_sha256"


def idempotency_preimage(model: CreationContractBase) -> str:
    """生成请求的幂等 preimage（**协议面规范化**，不含哈希）。

    幂等键 = 装配期对串 ``idempotency_preimage(request)`` 取中央摘要
    （``media_digest(preimage.encode("utf-8"))``，与 TTS 缓存键同一手法——
    见 ``domains/media/capabilities/tts.py`` 的 ``_cache_identity``：同样是
    「本域拼 preimage、中央件出摘要」的分工）。本函数只回答「哪些字段构成
    这一条请求的身份」，因此域内零 ``hashlib``、零第二套摘要算法。

    规范化三件（缺一即不可复现）：规则版本头 + DTO 类名（防 tts/image 同形载荷互撞）
    + 按 key 排序的紧凑 JSON（禁进程内 dict 序影响结果）。``idempotency_key``
    自身被剔除，故「填键前后」身份恒等。

    为什么现在必须补、不能留给激活期：本模块早已钉死
    ``UNKNOWN_NEVER_AUTO_REDISPATCH``（结果未知的任务不盲重发，指南 §11 L256/L258），
    但**没有请求身份就判不出「重发的这条是不是同一条」**——不变量今天可写不可用，
    等于空头支票。而 DTO 加字段是 wire 形态变更，provider 一旦上线再补就要同时改
    适配器/落库/对账三处；协议先把身份钉住，激活期只是「填值」。

    ⚠ preimage 含 prompt/text 原文，只在内存里活一次：绝不入日志、绝不出站。
    """
    body = {
        key: value
        for key, value in model.model_dump(mode="json").items()
        if key != IDEMPOTENCY_SELF_FIELD
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{IDEMPOTENCY_RULE_VERSION}|{type(model).__name__}|{canonical}"


# ---------------------------------------------------------------------------
# 错误目录（§6 单一注册源；扩展 §10 L311 集中注册——creation 域切片）
# ---------------------------------------------------------------------------

CreationErrorCode = Literal[
    "unsupported_parameter",
    "dependency_unavailable",
    "price_unavailable",
    "budget_exceeded",
]

#: code → HTTP 状态（§9.1.1 参数校验与错误码段）。
CREATION_ERROR_CATALOG: dict[CreationErrorCode, int] = {
    "unsupported_parameter": 422,
    "dependency_unavailable": 503,
    "price_unavailable": 503,
    "budget_exceeded": 429,
}


# ---------------------------------------------------------------------------
# 结果记录（任务出站侧契约：中央 descriptor ``output_protocol`` 的唯一落点）
# 2026-09-22 统一波 S-DRAW 补齐——在此之前该协议**只有散文没有家**
# ---------------------------------------------------------------------------

#: 中央两行 creation 描述符 ``output_protocol`` 的**声明形态唯一家**。
#: 病因（实证）：``runtime/capability_protocols.py:1815/1838`` 两串都写着
#: ``creation.v1 CreationJob{job_id,state,asset_id?,usage?}``，而全仓不存在
#: ``CreationJob``——请求 DTO、状态机、计量行各自有家，**把「这一条任务现在怎么样」
#: 说清楚的那具契约没有**。后果不是「少个类」，是三条既有教义可写不可用：见
#: ``CreationJob`` docstring。中央串由主会话执笔（本域禁触），故声明落在此处、
#: 等值性由 ``tests/test_creation_job_protocol.py`` 双向锁——改一边必红。
DECLARED_OUTPUT_PROTOCOL_VERSION = "creation.v1"
DECLARED_OUTPUT_PROTOCOL_TYPE = "CreationJob"
DECLARED_OUTPUT_PROTOCOL_FIELDS: tuple[str, ...] = ("job_id", "state", "asset_id", "usage")

#: 声明字段 → DTO 字段的**唯一映射处**。声明侧写单数 ``asset_id``，本域用 ``assets``
#: 引用元组承载：``count ≤ 2`` 的一个绘图任务可有 0..2 件产物，同时设 ``asset_id``
#: 与 ``assets`` 就是同一事实两具真身（禁第二真身）。无产物时二者皆为空——不设哨兵值。
DECLARED_OUTPUT_PROTOCOL_DTO_FIELDS: Mapping[str, str] = {
    "job_id": "job_id",
    "state": "state",
    "asset_id": "assets",
    "usage": "usage",
}

#: 非终态 = 共用状态机对 ``TERMINAL_JOB_STATES`` 取补（不另列一份名单，防漂移）。
NON_TERMINAL_JOB_STATES: frozenset[CreationJobState] = frozenset(
    set(CreationJobState) - TERMINAL_JOB_STATES
)


class CreationJob(CreationContractBase):
    """生成任务的结果记录：绘画与语音共用同一具（§9.1.2「任务状态机/取消：同 §9.1.1」）。

    四条教义的机器形态（此前都只是常量或散文，无处执法）：

    - **不假成功**：``succeeded`` 必须携带产物，且不得与 ``error_code`` 并存；
    - **未终态不宣布产物**：pending/admitted/running 的 ``assets`` 必须为空——半程产物
      不对外，否则「部分完成」会被下游当成可发送；
    - **未知不重发**（``UNKNOWN_NEVER_AUTO_REDISPATCH``）：``unknown`` 必须携带幂等请求
      身份。理由：绘画一次请求 ``count ≤ 2`` 可能已产生真金白银（扩展 §1 L56），而
      「重发的这条是不是同一条」只能由请求身份回答——请求侧早已挂 ``idempotency_key``
      （S-CREATE 补），结果侧此前无人接收，等于教义悬空；
    - **取消只是标记**（``CANCEL_REQUESTED_IS_NOT_A_STATE``）：``cancel_requested`` 与
      时间戳都不改 ``state``；``succeeded`` 可与「曾请求取消」同现（在途取消不假成功，
      但也不把已完成的真产物抹掉）。

    纪律：零 provider 客户端、零网络、零 I/O、零配置读取；``usage`` 走 ``_common`` 单一
    计量词表（Token 面不得在此伪造），产物只以 ``AssetRef`` 引用出现（不是服务器路径）。
    """

    job_id: str = Field(min_length=1, max_length=128)
    state: CreationJobState
    updated_at: datetime
    #: 请求身份回填（值来自 ``ImageJobRequest/TTSJobRequest.idempotency_key``，
    #: 由装配期用中央摘要件算好，本域不重算哈希）。
    idempotency_key: str | None = Field(default=None, pattern=DIGEST64_PATTERN)
    assets: tuple[AssetRef, ...] = Field(default=())
    usage: tuple[UsageLine, ...] = Field(default=())
    error_code: CreationErrorCode | None = None
    #: provider 侧作业句柄：对账（reconcile）面的唯一抓手；None=未受理或无此概念。
    provider_operation: str | None = Field(default=None, min_length=1, max_length=128)
    cancel_requested: bool = False
    cancel_requested_at: datetime | None = None

    @field_validator("updated_at", "cancel_requested_at")
    @classmethod
    def _aware_times(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_aware_utc("任务记录时间", value)

    @model_validator(mode="after")
    def _doctrines(self) -> CreationJob:
        if self.state is CreationJobState.SUCCEEDED and not self.assets:
            raise ValueError("state=succeeded 必须携带产物（没有产物的成功就是假成功）")
        if self.state in NON_TERMINAL_JOB_STATES and self.assets:
            raise ValueError(f"未终态 {self.state.value} 不得携带产物（半程产物不对外）")
        if self.error_code is not None and self.state not in (
            CreationJobState.FAILED,
            CreationJobState.UNKNOWN,
        ):
            raise ValueError(
                f"错误码只与 failed/unknown 并存（当前 state={self.state.value}）"
            )
        if self.state is CreationJobState.UNKNOWN and not self.idempotency_key:
            raise ValueError(
                "state=unknown 必须携带幂等请求身份 idempotency_key"
                "（无身份则「未知不重发」判不出同一条，教义即作废）"
            )
        if self.cancel_requested_at is not None and not self.cancel_requested:
            raise ValueError("cancel_requested_at 必须与 cancel_requested=True 同现")
        return self

    @property
    def is_terminal(self) -> bool:
        """是否终态（判据取自共用 ``TERMINAL_JOB_STATES``，不另立名单）。"""
        return self.state in TERMINAL_JOB_STATES

    def may_move_to(self, target: CreationJobState) -> bool:
        """迁移判定不自立一套：直引共用状态机的 ``can_transition``（终态无出边）。"""
        return can_transition(self.state, target)


__all__ = [
    "ALLOWED_JOB_TRANSITIONS",
    "ASSET_ID_PATTERN",
    "CANCEL_MAY_KEEP_COST",
    "CANCEL_REQUESTED_IS_NOT_A_STATE",
    "CONTENT_DIGEST_KEY",
    "CREATION_ERROR_CATALOG",
    "CREATION_METRICS",
    "CREATION_METRIC_UNITS",
    "DECLARED_OUTPUT_PROTOCOL_DTO_FIELDS",
    "DECLARED_OUTPUT_PROTOCOL_FIELDS",
    "DECLARED_OUTPUT_PROTOCOL_TYPE",
    "DECLARED_OUTPUT_PROTOCOL_VERSION",
    "DIGEST64_PATTERN",
    "IDEMPOTENCY_RULE_VERSION",
    "IDEMPOTENCY_SELF_FIELD",
    "IMAGE_MAX_INPUT_PIXELS",
    "JOB_STATES",
    "NON_TERMINAL_JOB_STATES",
    "TERMINAL_JOB_STATES",
    "TOKEN_METRIC_NAMES",
    "UNKNOWN_NEVER_AUTO_REDISPATCH",
    "AssetRef",
    "CancelRequest",
    "CostAmount",
    "CreationContractBase",
    "CreationErrorCode",
    "CreationJob",
    "CreationJobState",
    "QuantityStatus",
    "UsageLine",
    "_require_aware_utc",
    "can_transition",
    "idempotency_preimage",
]

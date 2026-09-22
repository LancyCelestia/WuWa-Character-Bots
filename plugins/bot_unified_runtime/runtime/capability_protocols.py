"""S10 能力协议注册面 + 统一受控调用面（媒体/文件/搜索三族 + creation 对接点）。

合同锚点：
- docs/design/backend-v2-implementation-guide.md §11（MediaAnalysisResult L252 /
  FileAsset L254 / TTS+绘图 L256-L258）、§13 S10 行、§6（严格 DTO）；
- docs/design/backend-v2-product-extensions.md §6（九源表逐行能力状态）；
- docs/design/backend-v2-acceptance-matrix.md V21-MEDIA-001/002、V21-FILE-001/002、
  V21-SEARCH-001/002、V21-TTS-001、V21-IMAGE-001。

职责边界（本模块只做协议壳，**禁平行造轮子**）：
- ``CapabilityDescriptor``：逐能力登记 名称/输入输出协议/required_roles/timeout/
  limits/fallback 链/implementation_ref/健康态；
- ``CapabilityInvoker``：descriptor 驱动的受控调用入口——权限门 → 载荷限额 →
  超时 → 降级链 → 审计钩子；实现体一律**包装既有实现**（vision/transcribe/
  video/sauce/file_reader/web_search/acg/search_service），SSRF/路径安全沿用
  既有护栏（``domains/files/sources/downloader.check_download_url`` /
  ``sources/parsers/ssrf_guard``）不绕过；
- ``search_source_status``：九源逐源状态面——配了 provider/key=available、
  没配=not_configured，**禁假成功**；
- creation 对接点：TTS/绘图 descriptor 只指向 ``domains/creation/``（RWPA1
  reserved 契约），**不注册 handler → invoke 诚实 unavailable**，实现体等
  provider 配置（指南 §11 L256/L258；归属裁决=§10 W-PA2，不属本席）。

全离线纪律：本模块 import 零网络零线程副作用；所有 handler 均可注入 fake
config / fake provider 离线验证。
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import inspect
import logging
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    ROLE_BLOCKED,
    ROLE_ORDER,
)

logger = logging.getLogger(__name__)

# ===========================================================================
# 词汇（健康态 / 调用终态）
# ===========================================================================


class CapabilityHealth(str, Enum):
    """能力健康态——诚实口径，禁假成功。

    - ``unknown``：未探测/依赖外部实测（不猜）；
    - ``not_configured``：没配 key/registry/开关 → 不可用（不是 available）；
    - ``available``：配置齐备可调用；
    - ``degraded``：可调用但带诚实降级（如 OCR 无独立引擎、VLM 代位）；
    - ``disabled``：显式开关关闭。
    """

    UNKNOWN = "unknown"
    NOT_CONFIGURED = "not_configured"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class InvocationStatus(str, Enum):
    """受控调用的终态词汇（协议面错误码的运行时形态）。"""

    OK = "ok"
    FALLBACK_OK = "fallback_ok"
    DEGRADED = "degraded"  # honest_degrade 终态：无结果+诚实说明，不冒充成功
    DENIED = "denied"
    TIMEOUT = "timeout"
    LIMIT_EXCEEDED = "limit_exceeded"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"  # 未接线/依赖缺失（not_wired）
    FAILED = "failed"


class CapabilityFamily(str, Enum):
    # COMMAND：路由能力经中央 invoker 的**执行面**族（A 案：authoring 在注册册路由行）。
    # 单列一族是刻意的——media/files/search 三族是「内容契约能力普查」的口径，
    # 把 bot.* 混进去会污染那几族的成员清单（R-A/C-01 实证）。
    COMMAND = "command"
    MEDIA = "media"
    FILES = "files"
    SEARCH = "search"
    CREATION = "creation"


# ===========================================================================
# 描述符（风格对齐 runtime/feature_catalog.py 的 FeatureDescriptor）
# ===========================================================================

#: 终态诚实降级链条目的固定前缀：``honest_degrade:<原因>``。
HONEST_DEGRADE_PREFIX = "honest_degrade:"

_CAPABILITY_ID_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$"


@dataclass(frozen=True)
class CapabilityDescriptor:
    """逐能力协议元数据（§13 执行卡叶子；注册时经 :func:`validate_registry` 校验）。

    limits/limit_fields 语义：``limit_fields`` 是 ``(载荷字段, limits 键)`` 对，
    invoker 在调用 handler 前按字段形态（字符串长度/序列长度/数值）执行上限，
    超限即 ``limit_exceeded`` 且 **handler 不执行**。
    """

    capability_id: str
    family: CapabilityFamily
    title: str
    input_protocol: str
    output_protocol: str
    required_roles: tuple[str, ...] = ("user",)
    timeout_seconds: float = 30.0
    limits: Mapping[str, int] = field(default_factory=dict)
    limit_fields: tuple[tuple[str, str], ...] = ()
    fallback_chain: tuple[str, ...] = ()
    implementation_ref: str = ""
    config_keys: tuple[str, ...] = ()
    health_probe: str = ""  # 空=无动态探测（用 health_default 口径）
    health_default: CapabilityHealth = CapabilityHealth.UNKNOWN
    notes: str = ""


# ===========================================================================
# 调用 DTO（严格模式：拒未知字段；对齐 search_service._StrictModel 口径）
# ===========================================================================


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CapabilityRequest(_StrictModel):
    """受控调用请求。``context`` 由装配/测试注入（config、providers 等）。"""

    capability_id: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    principal: str = Field(default="anonymous", min_length=1, max_length=128)
    roles: tuple[str, ...] = ("user",)
    context: dict[str, Any] = Field(default_factory=dict)
    # 关联键（调用方有则填）：审计记录要能与一条消息/请求对上，才谈得上"中央执行可观测"。
    # 缺省空=无关联（如控制面/合成调用方），不留假值。
    request_id: str = ""
    session_key: str = ""


#: 信封 ``data`` 内承载「呈现契约 model_dump」的**保留键**（Wave 1 起由 ``CapabilityInvoker``
#: 在成功态写入；Wave 0 先冻结命名与形态执法，下游禁第二副本、禁自造同义键名）。
PRESENTATION_DATA_KEY = "presentation_result"

#: 层 1 交还键：中央**没能产出任何可回复结果**时，把主链原始异常原样带回调用方，
#: 由层 1 的既有异常路径处置（`RuntimePipeline._internal_error`→错误卡）。
#: 只出现在 failed 终态的 ``data`` 里，**进程内传递、绝不序列化**（呈现载荷另有其键，
#: 且失败态带载荷由 `_check_envelope_invariants` 拦死，本键不受该约束＝非结果体）。
INVOKER_ERROR_DATA_KEY = "invoker_exception"

#: 成功终态族——只有这一族允许携带呈现载荷。
_SUCCESS_STATUSES: frozenset[InvocationStatus] = frozenset(
    {InvocationStatus.OK, InvocationStatus.FALLBACK_OK}
)

#: 失败/降级终态族——必须给诚实说明，且不得携带呈现载荷。
_UNSUCCESS_STATUSES: frozenset[InvocationStatus] = frozenset(InvocationStatus) - _SUCCESS_STATUSES


class InvocationResult(_StrictModel):
    """执行信封（旧名 ``CapabilityResult``，Wave 0 改名即退役）：终态 + 数据 + 归因。

    与呈现契约 ``plugins.bot_unified_runtime.domains.core.contracts.runtime`` 里的
    ``CapabilityResult`` 是**正交两层、不是同一抽象**：那个回答「给用户看什么」
    （kind/title/body/media/actions…，handler 的返回类型、review/render 的消费类型），
    本类回答「这次调用执行得怎样」（status/via/elapsed_ms/attempts）。
    全树只此一份执行信封、只此一份呈现契约，由 ``tests/test_capability_result_unique.py`` 执法；
    合并成超集会逼 207 处呈现构造点去填执行字段（invoker 才有的信息），构造期即崩。

    两条构造期不变量（不是文档口头约定，``extra=forbid`` 之上再加语义闸）：

    1. **成功态**下 ``data`` 内嵌 handler 返回的呈现契约 ``model_dump()``——经
       ``PRESENTATION_DATA_KEY`` 写入时必须已是 **dict**（信封 frozen，塞活模型对象
       会让下游 dump/等值比对各崩一次，且把「未序列化」的耦合偷偷传给出站层）。
    2. **失败/降级态**下 ``data`` 不得携带呈现载荷（无结果却带结果体＝冒充成功），
       且 ``detail`` 必须非空——即装**诚实降级说明**。这是 ``honest_degrade`` 链条目
       的存在理由：宁可说一句"没做成、因为什么"，绝不静默、绝不假成功。
    """

    capability_id: str
    status: InvocationStatus
    data: dict[str, Any] = Field(default_factory=dict)
    detail: str = ""
    via: str = ""
    elapsed_ms: int = Field(default=0, ge=0)
    attempts: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _check_envelope_invariants(self) -> Self:
        carries_payload = PRESENTATION_DATA_KEY in self.data
        if carries_payload:
            payload = self.data[PRESENTATION_DATA_KEY]
            if not isinstance(payload, dict):
                raise ValueError(
                    f"{PRESENTATION_DATA_KEY} 必须是呈现契约的 model_dump()（dict），"
                    f"实得 {type(payload).__name__}——信封不承载活模型对象"
                )
            if self.status not in _SUCCESS_STATUSES:
                raise ValueError(
                    f"终态 {self.status.value} 不得携带呈现载荷"
                    f"（{PRESENTATION_DATA_KEY}）：无结果却不带结果体，防冒充成功"
                )
        if self.status in _UNSUCCESS_STATUSES and not self.detail.strip():
            raise ValueError(
                f"终态 {self.status.value} 必须给 detail 诚实降级说明（honest_degrade 口径："
                "不静默、不假成功）"
            )
        return self


HandlerFn = Callable[[CapabilityRequest], InvocationResult]
HealthProbeFn = Callable[[Any], CapabilityHealth]

#: 终态降级链条目（honest_degrade）执行器：不调实现，只产诚实说明。
_FALLBACK_DEGRADE = "honest_degrade"
_FALLBACKS_KEY = "fallbacks"


def _result(
    request: CapabilityRequest,
    status: InvocationStatus,
    *,
    data: dict[str, Any] | None = None,
    detail: str = "",
    via: str = "",
    attempts: int = 1,
) -> InvocationResult:
    return InvocationResult(
        capability_id=request.capability_id,
        status=status,
        data=data or {},
        detail=detail[:500],
        via=via,
        attempts=max(1, int(attempts)),
    )


# ===========================================================================
# 注册面：描述符 / 处理器 / 降级 / 健康探测（线程安全；默认集惰性装配）
#
# Wave 2 定位更正（勿再当作「在册」真源）：下面 5 个注册表类
# （CapabilityRegistry / HandlerRegistry / FallbackRegistry / HealthProbeRegistry /
# AuditHookRegistry）是**执行侧索引视图**，其条目真源= ``DESCRIPTOR_BUILDERS``，
# 而「某个 capability_id 是否在册、它的 gate/帮助/路由事实在哪里」的唯一答案
# = :data:`CAPABILITY_DESCRIPTOR`（本文件 Wave 2 段，五路输入取并集派生）。
# 审计定罪过的「多套并行未收敛」正是把这 5 个类当成第 6 张表来另立注册；
# 新能力请写进 builders（编排侧）或 capability_registry 声明表（gate/路由/帮助侧），
# 由 tests/test_capability_single_registration.py 拦住第二处 authoring。
# ===========================================================================


class CapabilityRegistry:
    """描述符注册表。id 唯一在 register 时即拦（重复=ValueError）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._descriptors: dict[str, CapabilityDescriptor] = {}

    def register(self, descriptor: CapabilityDescriptor) -> None:
        if not descriptor.capability_id:
            raise ValueError("capability_id 不得为空")
        with self._lock:
            if descriptor.capability_id in self._descriptors:
                raise ValueError(f"capability_id 重复注册: {descriptor.capability_id}")
            self._descriptors[descriptor.capability_id] = descriptor

    def get(self, capability_id: str) -> CapabilityDescriptor | None:
        with self._lock:
            return self._descriptors.get(capability_id)

    def iter(self, family: CapabilityFamily | None = None) -> list[CapabilityDescriptor]:
        with self._lock:
            items = list(self._descriptors.values())
        if family is None:
            return items
        return [item for item in items if item.family is family]

    def __len__(self) -> int:
        with self._lock:
            return len(self._descriptors)


class HandlerRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: dict[str, HandlerFn] = {}

    def register(self, capability_id: str, handler: HandlerFn) -> None:
        with self._lock:
            self._handlers[capability_id] = handler

    def get(self, capability_id: str) -> HandlerFn | None:
        with self._lock:
            return self._handlers.get(capability_id)


class FallbackRegistry:
    """降级链条目注册表：键=(capability_id, 链条目名)。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fallbacks: dict[tuple[str, str], HandlerFn] = {}

    def register(self, capability_id: str, name: str, handler: HandlerFn) -> None:
        with self._lock:
            self._fallbacks[(capability_id, name)] = handler

    def get(self, capability_id: str, name: str) -> HandlerFn | None:
        with self._lock:
            return self._fallbacks.get((capability_id, name))


class HealthProbeRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._probes: dict[str, HealthProbeFn] = {}

    def register(self, name: str, probe: HealthProbeFn) -> None:
        with self._lock:
            self._probes[name] = probe

    def get(self, name: str) -> HealthProbeFn | None:
        with self._lock:
            return self._probes.get(name)

    def __contains__(self, name: object) -> bool:
        with self._lock:
            return name in self._probes


def compute_health(
    descriptor: CapabilityDescriptor,
    probes: HealthProbeRegistry,
    config: Any,
) -> CapabilityHealth:
    """健康态探测：无 probe 用 health_default；probe 异常按 unknown（不猜）。"""
    probe = probes.get(descriptor.health_probe) if descriptor.health_probe else None
    if probe is None:
        return descriptor.health_default
    try:
        return CapabilityHealth(probe(config))
    except Exception:  # noqa: BLE001 - 探测失败诚实 unknown，不冒充可用。
        return CapabilityHealth.UNKNOWN


# ===========================================================================
# 审计钩子（fail-open：钩子异常不阻断调用）
# ===========================================================================


@dataclass(frozen=True)
class CapabilityAuditRecord:
    """一次受控调用的审计记录（不含载荷原文，防密钥/隐私入审计）。"""

    at_utc: datetime
    capability_id: str
    principal: str
    status: InvocationStatus
    via: str
    elapsed_ms: int
    detail: str  # 截断 ≤300，由 invoker 保证
    request_id: str = ""
    session_key: str = ""


class AuditHookRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hooks: list[Callable[[CapabilityAuditRecord], None]] = []

    def register(self, hook: Callable[[CapabilityAuditRecord], None]) -> None:
        with self._lock:
            # 幂等：同一钩子重复注册会让"一次 invoke 落 N 行审计"（R-CENTRAL M-1 实跑
            # 坐实）。装配块被重放（测试、二次 import 路径）时不该翻倍计数。
            if any(existing is hook for existing in self._hooks):
                return
            self._hooks.append(hook)

    def emit(self, record: CapabilityAuditRecord) -> None:
        with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:
            try:
                hook(record)
            except Exception:
                logger.debug("capability audit hook failed", exc_info=True)


# ===========================================================================
# 统一调用面
# ===========================================================================

#: 共享工作线程池：超时后线程跑到自然结束（Python 线程不可强杀），结果弃用
#: 并诚实记 timeout——与 RuntimePipeline offload 同语义。
#:
#: 2026-09-18：改为**懒创建 + 显式收口**，与 ``pipeline._chat_pool`` /
#: ``renderer._mermaid_executor`` / ``error_report._RENDER_POOL`` 三池同模式
#: （审查 L-12）。此前本池是模块级直接创建、**无收口钩子**——四池里唯一的不一致项：
#: worker 非守护态只靠解释器隐式 join，且测试期残留会被停机 reaper 判为「滞留线程」
#: （实测：``test_v21_s10_protocols`` 跑过之后 ``cap-proto_0/1`` 存活，
#: 使 ``test_p4_reaper_returns_cleanly_when_no_stuck_threads`` 误报）。
_MAX_WORKERS = 4
_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None
_EXECUTOR_LOCK = threading.Lock()
_EXECUTOR_ATEXIT_REGISTERED = False


def _get_capability_executor() -> concurrent.futures.ThreadPoolExecutor:
    """取共享池（懒创建；首次创建时注册 atexit 收口）。"""
    global _EXECUTOR, _EXECUTOR_ATEXIT_REGISTERED
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                max_workers=_MAX_WORKERS, thread_name_prefix="cap-proto"
            )
            if not _EXECUTOR_ATEXIT_REGISTERED:
                atexit.register(_shutdown_capability_executor)
                _EXECUTOR_ATEXIT_REGISTERED = True
        return _EXECUTOR


def _shutdown_capability_executor() -> None:
    """模块级关闭钩子（与 ``pipeline._shutdown_chat_pool`` 同模式）。

    审查 L-12 口径：``wait=True`` 且不取消排队任务（``cancel_futures=False``）——
    已提交的能力调用在进程退出前跑完再收线程。收口后置 ``None``，下次调用自动
    重建，故本钩子**幂等、可重复调用**：既可作 atexit 收口，也可作测试期清洁入口。
    """
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        executor, _EXECUTOR = _EXECUTOR, None
    if executor is not None:
        executor.shutdown(wait=True, cancel_futures=False)


_MAX_TIMEOUT_SECONDS = 600.0


def _attempt_budget(descriptor: CapabilityDescriptor) -> float:
    """**一次尝试**的墙钟预算（主链与降级链每一条腿同口径、同一个出处）。

    语义钉死（2026-09-22 F-BAKE 根修，别改回减法）：``timeout_seconds`` 是
    「单次尝试上限」，**不是整次调用的总 deadline**。旧写法在降级链里把它当总
    deadline 去减 elapsed，再拿 ``max(1.0, …)`` 兜住不变成负数——于是主 attempt
    跑得越接近超时（真实故障形态：上游读到点才抛），降级腿分到的越少，最后恒定
    只剩 1 秒。任何一次真实 VLM/HTTP 尝试都不可能在那点时间里完成 ⇒ 降级链
    在册而不可达（AGENTS #49「在册但未执法」同族：存在性糊过活性判据）。
    把地板数调大不是修法：判据本身仍是「降级预算＝主链剩下的渣」。

    代价如实记在这里：每次尝试各得一份 ⇒ 最坏总耗时＝(1 + 实际执行的注册腿数)
    × 本值。腿数由 ``fallback_chain`` 在册声明且枚枚过 :func:`validate_registry`，
    现网绝大多数链只有一枚 ``honest_degrade`` 终态（不调实现、零耗时），只此一枚
    注册降级腿的 ``media.vision.anime_ip`` 最坏 2×20s；中央硬顶
    ``_MAX_TIMEOUT_SECONDS`` 逐次钳制每一次尝试，不因此放宽。
    """

    return max(0.05, min(float(descriptor.timeout_seconds), _MAX_TIMEOUT_SECONDS))


def _run_payload_limit_violation(
    descriptor: CapabilityDescriptor, payload: Mapping[str, Any]
) -> str:
    """返回限额违规说明；无违规返回空串。"""
    for payload_field, limit_key in descriptor.limit_fields:
        if payload_field not in payload or limit_key not in descriptor.limits:
            continue
        value = payload[payload_field]
        limit = descriptor.limits[limit_key]
        size = len(value) if isinstance(value, (str, list, tuple)) else None
        unit = "长度" if isinstance(value, str) else "项数"
        if size is not None:
            if size > limit:
                return f"payload.{payload_field} {unit} {size} 超限 {limit}（{limit_key}）"
        elif isinstance(value, bool):
            continue
        elif isinstance(value, (int, float)) and value > limit:
            return f"payload.{payload_field}={value} 超限 {limit}（{limit_key}）"
    return ""


def _handler_callable(handler: HandlerFn, request: CapabilityRequest) -> Callable[[], InvocationResult]:
    """把 handler（sync 或 async）打包成可提交工作线程的零参调用。

    async handler 用 asyncio.run 桥接（工作线程无 running loop，安全）；
    单次提交，不嵌套 submit（防 4 worker 池互等死锁）。
    """
    if inspect.iscoroutinefunction(handler):

        def _sync_bridge() -> InvocationResult:
            return asyncio.run(handler(request))

        return _sync_bridge
    return lambda: handler(request)


def roles_satisfy(held: tuple[str, ...], required: tuple[str, ...]) -> bool:
    """权限语义＝**层级最低门槛**（2026-09-21 根修；判据方向由 R-ROLE 独立复核确认）。

    旧判据是 `set(held) & set(required)` 的**平坦求交**，与角色叠加模型不匹配
    （`policy/roles.py`：超管自动叠 admin；`ROLE_ORDER` 升序=user<trusted<enterprise<admin<super_admin）。
    实况范围要说准（R-ROLE 的量纲纠正，别当成线上事故）：聊天消息路经 `resolve_roles` 派生主体，
    **恒含 "user"** ⇒ 旧判据在消息路径上对 `("user",)` floor 从没真拒过谁；真正被拒的是
    held 不含 user 字面量的主体——控制面 Principal（`("admin",)`/`("super_admin","admin")`）
    与合成调用方。⇒ 本次改动对今天现网消息行为增量=0，修的是「中央门一旦用于非 user 主体就反装」。
    新判据：主体任一角色秩 ≥ 要求最低秩即放行；`blocked` 永不满足（写在本体内，域内裸用同样生效）；
    未知角色串不参与定秩 ⇒ 一律不满足（fail-closed）。
    """

    if ROLE_BLOCKED in held or not required:
        # blocked 否决收进谓词本体（R-ROLE/I-2）：`diagnostics.py` 这类域内裸用者不再丢掉这层；
        # 对 invoker 零影响——它在更早处已无条件拒 blocked 主体。
        return False
    known = [r for r in required if r in ROLE_ORDER and r != ROLE_BLOCKED]
    if not known:
        # 要求侧全是未知/非法角色：宁拒不抛（抛会绕过降级链与审计，R-A/C-02）。
        return False
    floor = min(ROLE_ORDER.index(role) for role in known)
    return any(
        role in ROLE_ORDER and role != ROLE_BLOCKED and ROLE_ORDER.index(role) >= floor for role in held
    )


class CapabilityInvoker:
    """descriptor 驱动的受控调用入口。

    顺序：描述符解析 → 权限门 → 载荷限额 → handler（未接线=unavailable）
    → 超时 → 异常走 fallback_chain（终态 honest_degrade=degraded）→ 审计。
    权限语义：主体 roles 与 descriptor.required_roles 有交集即放行；
    ``blocked`` 角色无条件拒绝。
    预算语义：``descriptor.timeout_seconds``＝**单次尝试上限**（主链与降级链每条
    腿各得一份，逐腿再受 ``_MAX_TIMEOUT_SECONDS`` 钳制），不是整次调用的总 deadline；
    单一出处 :func:`_attempt_budget`，两处读法不许各写一份算式。
    """

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        handlers: HandlerRegistry,
        fallbacks: FallbackRegistry | None = None,
        probes: HealthProbeRegistry | None = None,
        audit_hooks: AuditHookRegistry | None = None,
    ) -> None:
        self.registry = registry
        self.handlers = handlers
        self.fallbacks = fallbacks or FallbackRegistry()
        self.probes = probes or HealthProbeRegistry()
        self.audit_hooks = audit_hooks or AuditHookRegistry()

    # ---- 查询面 ---------------------------------------------------------

    def health(
        self, capability_id: str, config: Any = None
    ) -> tuple[CapabilityDescriptor, CapabilityHealth] | None:
        descriptor = self.registry.get(capability_id)
        if descriptor is None:
            return None
        return descriptor, compute_health(descriptor, self.probes, config)

    # ---- 受控调用 -------------------------------------------------------

    def invoke(self, request: CapabilityRequest, *, config: Any = None) -> InvocationResult:
        started = time.monotonic()
        if config is not None:
            context = dict(request.context)
            context.setdefault("config", config)
            request = request.model_copy(update={"context": context})

        def _finish(status: InvocationStatus, **kwargs: Any) -> InvocationResult:
            result = _result(
                request, status, attempts=kwargs.pop("attempts", 1), **kwargs
            )
            elapsed_ms = int((time.monotonic() - started) * 1000)
            result = result.model_copy(update={"elapsed_ms": elapsed_ms})
            self.audit_hooks.emit(
                CapabilityAuditRecord(
                    at_utc=datetime.now(timezone.utc),
                    capability_id=request.capability_id,
                    principal=request.principal,
                    status=status,
                    via=result.via,
                    elapsed_ms=elapsed_ms,
                    detail=result.detail[:300],
                    request_id=request.request_id,
                    session_key=request.session_key,
                )
            )
            return result

        descriptor = self.registry.get(request.capability_id)
        if descriptor is None:
            return _finish(
                InvocationStatus.FAILED,
                detail=f"未登记能力: {request.capability_id}",
            )

        if ROLE_BLOCKED in request.roles:
            return _finish(InvocationStatus.DENIED, detail="blocked 主体拒绝")
        if request.roles and not roles_satisfy(
            request.roles, descriptor.required_roles
        ):
            # 空 roles＝**系统/内部主体**（真人经 `resolve_roles` 派生恒含 "user"，
            # 定时任务与 decision=None 的调用方拿不到角色）。不受人门约束，但 principal
            # 原样入审计、绝不伪造成 user（S-ROWS probe3 + REVIEW-ROLE I-3 同点）。
            # 豁免只做在本门、**不做进 `roles_satisfy` 谓词本体**：那里裸用的
            # `/bot why`（diagnostics.py）会把"过拒所有人"翻成"过放所有人"。
            return _finish(
                InvocationStatus.DENIED,
                detail=f"需要 {','.join(descriptor.required_roles)} 及以上角色",
            )

        violation = _run_payload_limit_violation(descriptor, request.payload)
        if violation:
            return _finish(InvocationStatus.LIMIT_EXCEEDED, detail=violation)

        handler = self.handlers.get(request.capability_id)
        if handler is None:
            return _finish(
                InvocationStatus.UNAVAILABLE,
                detail="能力未接线（not_wired）：实现体待 provider 配置/后续席",
                via="invoker",
            )

        budget = _attempt_budget(descriptor)
        attempts = 1
        task = _handler_callable(handler, request)
        try:
            future = _get_capability_executor().submit(task)
            try:
                result = future.result(timeout=budget)
            except concurrent.futures.TimeoutError:
                future.cancel()
                return _finish(
                    InvocationStatus.TIMEOUT,
                    detail=f"超时 {budget:g}s（线程跑到自然结束，结果弃用）",
                    via="invoker",
                )
        except Exception as exc:  # noqa: BLE001 - 主链异常走降级链。
            return self._run_fallbacks(
                request, descriptor, _finish, exc, started=started, attempts=attempts
            )

        if not isinstance(result, InvocationResult):
            return self._run_fallbacks(
                request,
                descriptor,
                _finish,
                TypeError(f"handler 返回类型非法: {type(result).__name__}"),
                started=started,
                attempts=attempts,
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        result = result.model_copy(update={"elapsed_ms": elapsed_ms, "attempts": attempts})
        self.audit_hooks.emit(
            CapabilityAuditRecord(
                at_utc=datetime.now(timezone.utc),
                capability_id=request.capability_id,
                principal=request.principal,
                status=result.status,
                via=result.via,
                elapsed_ms=elapsed_ms,
                detail=result.detail[:300],
                request_id=request.request_id,
                session_key=request.session_key,
            )
        )
        return result

    def _run_fallbacks(
        self,
        request: CapabilityRequest,
        descriptor: CapabilityDescriptor,
        finish: Callable[..., InvocationResult],
        primary_error: Exception,
        *,
        started: float,
        attempts: int,
    ) -> InvocationResult:
        """主链异常 → 按链执行降级；正常终态 honest_degrade=degraded；降级失败/链尽=failed。

        语义区分（防把崩溃伪装成"降级"）：honest_degrade 终态只在**没有已注册
        降级失败**时给 degraded（设计内的诚实无结果）；若有降级项崩了，终态
        一律 failed（detail 携带最后失败与降级原因），运维可告警。

        预算语义（F-BAKE 2026-09-22 根修）：每条注册降级腿各得一份完整的
        :func:`_attempt_budget`，**不减主链已经烧掉的时间**。旧写法减完再地板到
        1.0s，等于「主链越慢、降级越必然来不及」，慢失败场景下降级形同不存在；
        活性判据与逐腿取证见 ``tests/test_central_fallback_budget.py``。
        ``started`` 只用于终态 ``elapsed_ms`` 记账，不参与任何尝试的预算推导。
        """
        last_detail = f"{type(primary_error).__name__}: {primary_error}"[:300]
        fallback_failures = 0
        for index, name in enumerate(descriptor.fallback_chain):
            if name.startswith(HONEST_DEGRADE_PREFIX):
                reason = name[len(HONEST_DEGRADE_PREFIX):].strip() or "能力降级"
                if fallback_failures:
                    return finish(
                        InvocationStatus.FAILED,
                        detail=(
                            f"主链失败（{last_detail}）；降级链 {fallback_failures} 项失败，"
                            f"终态说明：{reason}"
                        ),
                        via=f"fallback[{index}]:{_FALLBACK_DEGRADE}",
                        attempts=attempts + index,
                        data={INVOKER_ERROR_DATA_KEY: primary_error},
                    )
                return finish(
                    InvocationStatus.DEGRADED,
                    detail=f"主链失败（{last_detail}）；诚实降级：{reason}",
                    via=f"fallback[{index}]:{_FALLBACK_DEGRADE}",
                    attempts=attempts + index,
                    data={INVOKER_ERROR_DATA_KEY: primary_error},
                )
            fallback = self.fallbacks.get(request.capability_id, name)
            if fallback is None:
                continue
            # 每次尝试各得一份完整预算（同一个 _attempt_budget 出处）——降级腿的
            # 预算与主 attempt 跑了多久**无关**，否则慢失败=注定没有降级。
            remaining = _attempt_budget(descriptor)
            try:
                future = _get_capability_executor().submit(
                    _handler_callable(fallback, request)
                )
                result = future.result(timeout=remaining)
            except concurrent.futures.TimeoutError:
                future.cancel()
                last_detail = f"降级 {name} 超时"
                fallback_failures += 1
                continue
            except Exception as exc:  # noqa: BLE001 - 继续走链。
                last_detail = f"降级 {name} 失败 {type(exc).__name__}: {exc}"[:300]
                fallback_failures += 1
                continue
            if isinstance(result, InvocationResult):
                elapsed_ms = int((time.monotonic() - started) * 1000)
                promoted = result.model_copy(
                    update={
                        "detail": result.detail or f"主链失败后由降级 {name} 承接",
                        "via": f"fallback[{index}]:{name}",
                        "elapsed_ms": elapsed_ms,
                        "attempts": attempts + index + 1,
                    }
                )
                if promoted.status is InvocationStatus.OK:
                    promoted = promoted.model_copy(
                        update={"status": InvocationStatus.FALLBACK_OK}
                    )
                self.audit_hooks.emit(
                    CapabilityAuditRecord(
                        at_utc=datetime.now(timezone.utc),
                        capability_id=request.capability_id,
                        principal=request.principal,
                        status=promoted.status,
                        via=promoted.via,
                        elapsed_ms=elapsed_ms,
                        detail=promoted.detail[:300],
                        request_id=request.request_id,
                        session_key=request.session_key,
                    )
                )
                return promoted
        return finish(
            InvocationStatus.FAILED,
            detail=f"主链与降级链全部失败：{last_detail}",
            via="invoker",
            attempts=attempts + len(descriptor.fallback_chain),
            data={INVOKER_ERROR_DATA_KEY: primary_error},
        )


# ===========================================================================
# 完整性校验（测试门：断言返回 []）
# ===========================================================================


def validate_registry(
    registry: CapabilityRegistry,
    *,
    handlers: HandlerRegistry | None = None,
    fallbacks: FallbackRegistry | None = None,
    probes: HealthProbeRegistry | None = None,
) -> list[str]:
    """逐条校验描述符完整性；返回问题清单（空=通过）。

    - 每能力必备字段：id 形态/族/标题/输入输出协议/roles/timeout/limits 一致性/
      fallback 链条目可解析（registered 或 honest_degrade）/implementation_ref
      文件存在/health_probe 已注册。
    - handler 缺失不算问题（unavailable 是诚实终态，如 creation 对接点），
      但 ``handlers`` 提供时也不强制。
    """
    problems: list[str] = []
    import re as _re

    seen: set[str] = set()
    for descriptor in registry.iter():
        cid = descriptor.capability_id
        seen.add(cid)
        if not _re.match(_CAPABILITY_ID_PATTERN, cid):
            problems.append(f"{cid}: id 形态非法")
        if not isinstance(descriptor.family, CapabilityFamily):
            problems.append(f"{cid}: family 非法")
        if not descriptor.title.strip():
            problems.append(f"{cid}: title 缺失")
        if not descriptor.input_protocol.strip() or not descriptor.output_protocol.strip():
            problems.append(f"{cid}: 输入/输出协议缺失")
        if not descriptor.required_roles:
            problems.append(f"{cid}: required_roles 为空")
        for role in descriptor.required_roles:
            if role not in ROLE_ORDER or role == ROLE_BLOCKED:
                problems.append(f"{cid}: 非法角色 {role!r}")
        if not (0 < descriptor.timeout_seconds <= _MAX_TIMEOUT_SECONDS):
            problems.append(f"{cid}: timeout_seconds 越界 {descriptor.timeout_seconds}")
        for key, value in descriptor.limits.items():
            if not key.strip() or isinstance(value, bool) or not isinstance(value, int) or value < 0:
                problems.append(f"{cid}: limits[{key!r}]={value!r} 非法")
        for payload_field, limit_key in descriptor.limit_fields:
            if limit_key not in descriptor.limits:
                problems.append(f"{cid}: limit_fields 引用未定义限额 {limit_key!r}")
            if not payload_field.strip():
                problems.append(f"{cid}: limit_fields 载荷字段为空")
        if not descriptor.fallback_chain:
            problems.append(f"{cid}: fallback_chain 为空（至少含 honest_degrade 终态）")
        for index, name in enumerate(descriptor.fallback_chain):
            if name.startswith(HONEST_DEGRADE_PREFIX):
                if not name[len(HONEST_DEGRADE_PREFIX):].strip():
                    problems.append(f"{cid}: fallback[{index}] honest_degrade 缺原因")
            elif fallbacks is not None and fallbacks.get(cid, name) is None:
                problems.append(f"{cid}: fallback[{index}] {name!r} 未注册")
        ref_path = descriptor.implementation_ref.split("#", 1)[0]
        if not ref_path.strip():
            problems.append(f"{cid}: implementation_ref 缺失")
        elif not (REPO_ROOT / ref_path).is_file():
            problems.append(f"{cid}: implementation_ref 文件不存在 {ref_path}")
        if descriptor.health_probe and probes is not None and descriptor.health_probe not in probes:
            problems.append(f"{cid}: health_probe {descriptor.health_probe!r} 未注册")
        if not descriptor.notes.strip():
            problems.append(f"{cid}: notes 缺失（诚实现状口径必填）")
    return problems


REPO_ROOT = Path(__file__).resolve().parents[3]

# ===========================================================================
# 媒体/文件/搜索：既有实现的协议壳（懒 import，离线可测）
# ===========================================================================


def _config_of(request: CapabilityRequest) -> Any:
    return request.context.get("config")


def _guard_http_url(url: str) -> str:
    """URL 输入沿用既有 SSRF 护栏（只拦 http/https；本地路径/file:// 不走网络）。"""
    from plugins.bot_unified_runtime.domains.files.sources.downloader import (
        RejectedUrlError,
        check_download_url,
    )

    if not str(url).startswith(("http://", "https://")):
        return ""
    try:
        check_download_url(str(url))
    except RejectedUrlError as exc:
        return f"SSRF 护栏拒绝: {exc}"
    return ""


def _require_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    return str(value).strip() if value is not None else ""


# ---- media 族 -------------------------------------------------------------


def _handle_media_vision_image(request: CapabilityRequest) -> InvocationResult:
    """图片识别 → 既有 VLM 链（vision_describe.describe_images）。"""
    from plugins.bot_unified_runtime.domains.media.ingest import vision_describe

    config = _config_of(request)
    provider = vision_describe.build_vision_provider(config)
    if provider is None:
        return _result(
            request,
            InvocationStatus.NOT_CONFIGURED,
            detail="视觉注册表为空（bot_vision_model_registry 未配置）",
            via="vision_describe",
        )
    urls = [str(u) for u in (request.payload.get("image_urls") or [])]
    if not urls:
        return _result(request, InvocationStatus.FAILED, detail="缺少 image_urls")
    for url in urls:
        blocked = _guard_http_url(url)
        if blocked:
            return _result(request, InvocationStatus.FAILED, detail=blocked, via="ssrf_guard")
    text = vision_describe.describe_images(
        provider,
        image_urls=urls,
        query_text=_require_str(request.payload, "query_text"),
        max_images=int(getattr(config, "bot_vision_max_images", 2) or 2),
        max_chars=int(getattr(config, "bot_vision_max_chars", 500) or 500),
    )
    if not text:
        return _result(
            request,
            InvocationStatus.DEGRADED,
            detail="识别链返回空（模型不可达/无内容），不冒充识别成功",
            via="vision_describe",
        )
    return _result(request, InvocationStatus.OK, data={"text": text}, via="vision_describe")


def _handle_media_ocr(request: CapabilityRequest) -> InvocationResult:
    """OCR → 无独立引擎（矩阵 L47 实证），VLM 文字转写代位=诚实降级。"""
    from plugins.bot_unified_runtime.domains.media.ingest import vision_describe

    config = _config_of(request)
    provider = vision_describe.build_vision_provider(config)
    if provider is None:
        return _result(
            request,
            InvocationStatus.NOT_CONFIGURED,
            detail="视觉注册表为空：无独立 OCR 引擎且 VLM 未配置",
            via="vision_describe",
        )
    urls = [str(u) for u in (request.payload.get("image_urls") or [])]
    if not urls:
        return _result(request, InvocationStatus.FAILED, detail="缺少 image_urls")
    for url in urls:
        blocked = _guard_http_url(url)
        if blocked:
            return _result(request, InvocationStatus.FAILED, detail=blocked, via="ssrf_guard")
    text = vision_describe.describe_images(
        provider,
        image_urls=urls,
        query_text="请转写图中全部文字，保持原文，不要解释",
        max_images=int(getattr(config, "bot_vision_max_images", 2) or 2),
        max_chars=max(500, int(getattr(config, "bot_vision_max_chars", 500) or 500)),
    )
    if not text:
        return _result(
            request,
            InvocationStatus.DEGRADED,
            detail="VLM 代位 OCR 返回空；独立 OCR 引擎未接入（诚实边界）",
            via="vlm_transcribe",
        )
    return _result(
        request,
        InvocationStatus.DEGRADED,
        data={"text": text, "engine": "vlm_transcribe"},
        detail="无独立 OCR 引擎，VLM 文字转写代位（矩阵 L47 口径）",
        via="vlm_transcribe",
    )


def _handle_media_anime_ip(request: CapabilityRequest) -> InvocationResult:
    """动漫角色/IP 识别 → SauceNAO 反搜（no_key/http_error/无结果三态诚实）。"""
    from plugins.bot_unified_runtime.domains.media.search.sauce_search import (
        search_saucenao_ex,
    )

    url = _require_str(request.payload, "image_url")
    if not url.startswith(("http://", "https://")):
        return _result(
            request,
            InvocationStatus.FAILED,
            detail="SauceNAO 仅接受公网图片 URL",
            via="sauce_search",
        )
    blocked = _guard_http_url(url)
    if blocked:
        return _result(request, InvocationStatus.FAILED, detail=blocked, via="ssrf_guard")
    hits, error_kind = search_saucenao_ex(url, config=_config_of(request))
    if error_kind == "no_key":
        return _result(
            request,
            InvocationStatus.NOT_CONFIGURED,
            detail="SauceNAO key 未配置（bot_saucenao_api_key）",
            via="sauce_search",
        )
    if error_kind == "http_error":
        return _result(
            request,
            InvocationStatus.DEGRADED,
            detail="SauceNAO 服务不可达/响应异常（与真无结果区分）",
            via="sauce_search",
        )
    payload = [
        {
            "similarity": hit.similarity,
            "title": hit.title,
            "member": hit.member,
            "source": hit.source,
            "url": hit.url,
        }
        for hit in hits
    ]
    detail = "" if payload else "反搜成功但无相似结果（与失败区分）"
    return _result(request, InvocationStatus.OK, data={"hits": payload}, detail=detail, via="sauce_search")


def _make_asr_handler(via: str) -> HandlerFn:
    def handler(request: CapabilityRequest) -> InvocationResult:
        from plugins.bot_unified_runtime.domains.media.ingest import transcribe

        config = _config_of(request)
        provider = transcribe.build_asr_provider(config)
        if provider is None:
            return _result(
                request,
                InvocationStatus.NOT_CONFIGURED,
                detail="ASR 注册表为空（bot_asr_model_registry 未配置）",
                via=via,
            )
        source = _require_str(request.payload, "audio_source")
        if not source:
            return _result(request, InvocationStatus.FAILED, detail="缺少 audio_source")
        blocked = _guard_http_url(source)
        if blocked:
            return _result(request, InvocationStatus.FAILED, detail=blocked, via="ssrf_guard")
        text = transcribe.transcribe_audio(
            provider,
            audio_source=source,
            timeout_seconds=float(getattr(config, "bot_asr_timeout_seconds", 20.0) or 20.0),
            max_chars=int(getattr(config, "bot_asr_max_chars", 300) or 300),
        )
        if not text:
            return _result(
                request,
                InvocationStatus.DEGRADED,
                detail="转写返回空（源不可用/模型失败），不冒充转写成功",
                via=via,
            )
        return _result(request, InvocationStatus.OK, data={"text": text}, via=via)

    return handler


def _handle_media_video_recognize(request: CapabilityRequest) -> InvocationResult:
    """视频识别 → build_video_brief 四路融合（字幕+抽帧+音轨+元数据）。"""
    from plugins.bot_unified_runtime.domains.media.ingest import (
        transcribe as asr_module,
    )
    from plugins.bot_unified_runtime.domains.media.ingest import (
        video_understanding,
        vision_describe,
    )

    config = _config_of(request)
    if not bool(getattr(config, "bot_video_understanding_enabled", False)):
        return _result(
            request,
            InvocationStatus.NOT_CONFIGURED,
            detail="bot_video_understanding_enabled=false",
            via="video_understanding",
        )
    source = _require_str(request.payload, "video_source")
    if not source:
        return _result(request, InvocationStatus.FAILED, detail="缺少 video_source")
    blocked = _guard_http_url(source)
    if blocked:
        return _result(request, InvocationStatus.FAILED, detail=blocked, via="ssrf_guard")
    brief = video_understanding.build_video_brief(
        config,
        vision_provider=vision_describe.build_vision_provider(config),
        asr_provider=asr_module.build_asr_provider(config),
        video_source=source,
        subtitle_text=_require_str(request.payload, "subtitle_text"),
        metadata_text=_require_str(request.payload, "metadata_text"),
        question=_require_str(request.payload, "question"),
        deep=bool(request.payload.get("deep") or False),
    )
    if not brief.text:
        return _result(
            request,
            InvocationStatus.DEGRADED,
            data={"signals": dict(brief.signals)},
            detail="全部信号缺失（字幕/帧/音轨/元数据皆空），诚实返回空简报",
            via="video_understanding",
        )
    return _result(
        request,
        InvocationStatus.OK,
        data={"text": brief.text, "signals": dict(brief.signals)},
        via="video_understanding",
    )


def _handle_media_video_subtitle(request: CapabilityRequest) -> InvocationResult:
    """字幕：CC 由摄取层提供，协议面不重新下载解析（诚实边界）。"""
    subtitle = _require_str(request.payload, "subtitle_text")
    if not subtitle:
        return _result(
            request,
            InvocationStatus.DEGRADED,
            data={"present": False},
            detail="字幕轨缺失：CC 字幕由摄取层提供，协议面不重下载（诚实边界）",
            via="video_understanding",
        )
    return _result(
        request,
        InvocationStatus.OK,
        data={"present": True, "subtitle_text": subtitle},
        via="video_understanding",
    )


def _handle_media_frame_extract(request: CapabilityRequest) -> InvocationResult:
    """抽帧 → vision_describe 抽帧链（ffmpeg 均匀抽帧落盘 JPEG）。

    结果是进程内临时文件路径（非对外 asset）：对外暴露须 asset 化
    （§11 L254，留后续席）；内部调用方按路径取字节。
    """
    import tempfile

    from plugins.bot_unified_runtime.domains.media.ingest import vision_describe

    source = _require_str(request.payload, "video_source")
    if not source:
        return _result(request, InvocationStatus.FAILED, detail="缺少 video_source")
    blocked = _guard_http_url(source)
    if blocked:
        return _result(request, InvocationStatus.FAILED, detail=blocked, via="ssrf_guard")
    descriptor = _DESCRIPTOR_VIEW.get(request.capability_id)
    max_frames = int(descriptor.limits.get("max_frames", 24)) if descriptor else 24
    frames = request.payload.get("frames")
    count = max(1, min(int(frames) if frames else 6, max_frames))
    out_dir = tempfile.mkdtemp(prefix="cap_frames_")
    paths = vision_describe._extract_video_frames(
        source, count, out_dir, timeout_seconds=30.0
    )
    if not paths:
        return _result(
            request,
            InvocationStatus.DEGRADED,
            detail="ffmpeg 缺失或抽帧失败（诚实降级）",
            via="vision_describe",
        )
    return _result(
        request,
        InvocationStatus.OK,
        data={
            "frames": [{"path": str(p), "bytes": p.stat().st_size} for p in paths],
            "work_dir": out_dir,
        },
        detail="结果为进程内临时文件路径；对外 asset 化留后续（§11 L254）",
        via="vision_describe",
    )


def _handle_media_tts_autodub(request: CapabilityRequest) -> InvocationResult:
    """自动配音产出步 → tts.py ``synthesize_autodub`` 单一真身（VOICE-V12 第二出站腿）。

    入参=hook（层 1）已过内容门与硬顶的干净 text；本 handler 只做「一句话→一段音频」。
    三态映射（与命令路/旧包装同一分类口，禁在中央另造 kind）：

    - ``ok``     → OK + ``data={audio_file, review_text, content_sha256?, preset_id, seed}``
      （内容契约载荷，**不经** ``PRESENTATION_DATA_KEY``——呈现回挂是层 1 hook 本职，中央只见这一步）；
    - ``no_ref`` → NOT_CONFIGURED（确定性失败，无可用参考音频；hook 映射 tts_no_ref_audio 码族）；
    - ``failed`` → FAILED + 原样原因串（hook 交 ``_failure_issue`` 按前缀表分类）。

    合成阻塞（HTTP/落盘）在本 handler 内跑，由 invoker 卸载到 cap-proto 线程池并施加
    descriptor.timeout_seconds（90s）安全网；超时=TIMEOUT 终态（不进降级链，命令腿同型）。
    """
    from plugins.bot_unified_runtime.domains.media.capabilities import tts

    config = _config_of(request)
    text = _require_str(request.payload, "text")
    if not text:
        return _result(request, InvocationStatus.FAILED, detail="缺少 text")
    # 合成原语注入缝：调用方（层 1 hook）经 context 交来，缺省=tts 自己的 synthesize。
    # 现网两者同一真身（voice_enricher 只从 tts 导入 synthesize），逐字节等价；注入缝只
    # 为让「合成这一步」在产出步 seam 上离线可测，不新增第二引擎路、不改生产取数。
    synth = request.context.get("synthesize")
    code, payload = tts.synthesize_autodub(config, text, synth=synth)
    if code == "no_ref":
        return _result(
            request,
            InvocationStatus.NOT_CONFIGURED,
            detail="无可用参考音频（BOT_TTS_REF_AUDIOS 未配置或全部读不到）",
            via="tts_autodub",
        )
    if code == "failed":
        return _result(
            request,
            InvocationStatus.FAILED,
            detail=str(payload)[:500],
            via="tts_autodub",
        )
    return _result(
        request,
        InvocationStatus.OK,
        data=dict(payload) if isinstance(payload, dict) else {},
        via="tts_autodub",
    )


#: 抽帧 handler 需要读 descriptor limits；装配期由 default_invoker 回填。
_DESCRIPTOR_VIEW: dict[str, CapabilityDescriptor] = {}


# ---- files 族 -------------------------------------------------------------


def _make_file_read_handler(
    *, expected_kinds: tuple[str, ...], label: str
) -> HandlerFn:
    def handler(request: CapabilityRequest) -> InvocationResult:
        from plugins.bot_unified_runtime.domains.files.sources import file_reader

        raw = _require_str(request.payload, "path")
        if not raw:
            return _result(request, InvocationStatus.FAILED, detail="缺少 path")
        descriptor = _DESCRIPTOR_VIEW.get(request.capability_id)
        max_chars = (
            int(descriptor.limits.get("max_chars", 120000)) if descriptor else 120000
        )
        parsed = file_reader.read_supported_file(raw, max_chars=max_chars)
        if parsed.kind == "missing":
            return _result(
                request,
                InvocationStatus.FAILED,
                detail=f"文件不存在: {parsed.path.name}",
                via="file_reader",
            )
        metadata = dict(parsed.metadata or {})
        if metadata.get("status") == "parser_unavailable":
            return _result(
                request,
                InvocationStatus.DEGRADED,
                data={"kind": parsed.kind, "text": "", "metadata": metadata},
                detail=(
                    f"旧格式无真实适配器，诚实降级 parser_unavailable"
                    f"（{metadata.get('format', '')}）；不冒充解析成功"
                ),
                via="file_reader",
            )
        if parsed.kind not in expected_kinds:
            return _result(
                request,
                InvocationStatus.FAILED,
                detail=f"{label} 通道读到 kind={parsed.kind}（后缀与能力不匹配）",
                via="file_reader",
            )
        if not parsed.text.strip():
            hint = "；扫描件 OCR 未接入" if parsed.kind == "pdf" else ""
            return _result(
                request,
                InvocationStatus.DEGRADED,
                data={"kind": parsed.kind, "title": parsed.title, "metadata": metadata},
                detail=f"解析成功但无可提取文本{hint}",
                via="file_reader",
            )
        return _result(
            request,
            InvocationStatus.OK,
            data={
                "kind": parsed.kind,
                "title": parsed.title,
                "text": parsed.text,
                "metadata": metadata,
            },
            via="file_reader",
        )

    return handler


def _handle_files_artifact_generate(request: CapabilityRequest) -> InvocationResult:
    """代码/文本资产生成 → build_generated_file（禁冒充 Office/PDF、原子写、2MiB）。"""
    from plugins.bot_unified_runtime.domains.files.sources import file_reader

    user_text = _require_str(request.payload, "user_text")
    reply_text = str(request.payload.get("reply_text") or "")
    output_dir = _require_str(request.payload, "output_dir")
    if not user_text or not reply_text or not output_dir:
        return _result(
            request,
            InvocationStatus.FAILED,
            detail="需要 user_text/reply_text/output_dir 三项",
            via="build_generated_file",
        )
    try:
        generated = file_reader.build_generated_file(user_text, reply_text, output_dir)
    except ValueError as exc:
        return _result(
            request, InvocationStatus.FAILED, detail=str(exc), via="build_generated_file"
        )
    if generated is None:
        return _result(
            request,
            InvocationStatus.DEGRADED,
            detail="未识别生成意图（诚实降级，不产空文件）",
            via="build_generated_file",
        )
    return _result(
        request,
        InvocationStatus.OK,
        data={"path": str(generated.path), "kind": generated.kind},
        detail="进程内产物路径回执；对外发送走 transport/FileGateway（不执行代码）",
        via="build_generated_file",
    )


# ---- search 族 ------------------------------------------------------------


def _web_provider_or_none(config: Any) -> tuple[Any, bool]:
    from plugins.bot_unified_runtime.domains.core.search import web_search

    provider = web_search.build_web_search_provider(config)
    return provider, not isinstance(provider, web_search.NullWebSearchProvider)


def _handle_search_web(request: CapabilityRequest) -> InvocationResult:
    """通用搜索 → web_search 引擎链（tavily 主链+回退；disabled=Null 诚实）。"""

    config = _config_of(request)
    provider, usable = _web_provider_or_none(config)
    if not usable:
        return _result(
            request,
            InvocationStatus.NOT_CONFIGURED,
            detail="bot_web_search_enabled=false（NullWebSearchProvider）",
            via="web_search",
        )
    query = _require_str(request.payload, "query")
    if not query:
        return _result(request, InvocationStatus.FAILED, detail="缺少 query")
    max_results = int(request.payload.get("max_results") or 8)
    hits = provider.search(query, max_results=max_results)
    if not hits:
        return _result(
            request,
            InvocationStatus.DEGRADED,
            detail="引擎链返回空（失败/超时静默语义），不编造结果",
            via="web_search",
        )
    return _result(
        request,
        InvocationStatus.OK,
        data={
            "hits": [
                {
                    "title": hit.title,
                    "snippet": hit.snippet,
                    "url": hit.url,
                    "source_domain": hit.source_domain,
                }
                for hit in hits
            ]
        },
        via="web_search",
    )


def _handle_search_acg(request: CapabilityRequest) -> InvocationResult:
    """ACG 竖源 → search_intent 意图门 + acg_search 三竖源并发。"""
    from plugins.bot_unified_runtime.sources import acg_search, search_intent

    config = _config_of(request)
    if not bool(getattr(config, "bot_search_acg_enabled", False)):
        return _result(
            request,
            InvocationStatus.NOT_CONFIGURED,
            detail="bot_search_acg_enabled=false",
            via="acg_search",
        )
    query = _require_str(request.payload, "query")
    if not query:
        return _result(request, InvocationStatus.FAILED, detail="缺少 query")
    intent = search_intent.detect_acg_intent(query)
    if not intent.is_acg:
        return _result(
            request,
            InvocationStatus.DEGRADED,
            detail="未命中 ACG 检索意图（诚实跳过，不硬搜）",
            via="search_intent",
        )
    results, errors = acg_search.search_acg_verticals(
        query,
        intent,
        timeout_seconds=float(getattr(config, "bot_search_acg_timeout_seconds", 4.0) or 4.0),
    )
    payload = [
        {
            "source": item.source,
            "title": item.title,
            "snippet": item.snippet,
            "url": item.url,
            "date": item.date,
            "extra": item.extra,
        }
        for item in results
    ]
    detail = ""
    if not payload:
        detail = "竖源无结果" + (f"；错误: {','.join(errors)}" if errors else "")
    return _result(request, InvocationStatus.OK, data={"results": payload}, detail=detail, via="acg_search")


def _handle_search_unified(request: CapabilityRequest) -> InvocationResult:
    """统一搜索 → search_service.UnifiedSearchService（provider 可注入）。"""
    from plugins.bot_unified_runtime.domains.core.search import search_service

    config = _config_of(request)
    providers = request.context.get("providers")
    if providers is None:
        provider, usable = _web_provider_or_none(config)
        if usable:
            providers = {"general": _WebChainAsSearchProvider(provider)}
        else:
            providers = {}
    query = _require_str(request.payload, "query")
    if not query:
        return _result(request, InvocationStatus.FAILED, detail="缺少 query")
    source_ids = [str(s) for s in (request.payload.get("source_ids") or ["general"])]
    request_dto = search_service.SearchRequest(
        query=query, source_ids=source_ids, limit=int(request.payload.get("limit") or 8)
    )
    service = search_service.UnifiedSearchService(providers)  # type: ignore[arg-type]
    response = service.search(request_dto, owner_id=request.principal)
    if response.status is search_service.OverallStatus.DEPENDENCY_UNAVAILABLE:
        return _result(
            request,
            InvocationStatus.NOT_CONFIGURED,
            data={"per_source": [o.model_dump() for o in response.per_source]},
            detail="无可用 provider（dependency_unavailable，不编造结果）",
            via="search_service",
        )
    return _result(
        request,
        InvocationStatus.OK
        if response.status is search_service.OverallStatus.OK
        else InvocationStatus.DEGRADED,
        data={
            "status": response.status.value,
            "hits": [hit.model_dump(mode="json") for hit in response.hits],
            "per_source": [o.model_dump() for o in response.per_source],
        },
        detail="" if response.hits else (response.empty_reason or ""),
        via="search_service",
    )


class _WebChainAsSearchProvider:
    """把 web_search 引擎链适配成 search_service.SearchProvider（W7 预留上车点）。"""

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    def search(self, query: Any) -> list[Any]:
        # 垫片 sources/web_search.py 已退役删除（v21r4-B RET2b），真身在
        # domains/core/search/web_search.py——与本文件 _web_provider_or_none 同形态。
        from plugins.bot_unified_runtime.domains.core.search import (
            search_service,
            web_search,
        )

        try:
            hits = self._provider.search(query.query, max_results=query.limit)
        except Exception:  # noqa: BLE001 - provider 失败按零命中诚实返回。
            return []
        return [
            search_service.ProviderRawHit(
                title=hit.title,
                url=hit.url,
                snippet=hit.snippet,
                content_level=search_service.ContentLevel.SNIPPET,
                retrieval_mode=f"web_chain:{web_search.__name__}",
            )
            for hit in hits
        ]


def _handle_search_reference_fetch(request: CapabilityRequest) -> InvocationResult:
    """引用取回 → fetch_reference（只收 citation_id，结构上不接任意 URL）。"""
    from plugins.bot_unified_runtime.domains.core.search import search_service

    citation_id = _require_str(request.payload, "citation_id")
    if not citation_id:
        return _result(request, InvocationStatus.FAILED, detail="缺少 citation_id")
    context = request.context.get("hit_context")
    fetcher = request.context.get("fetcher")
    if not isinstance(context, Mapping) or not callable(fetcher):
        return _result(
            request,
            InvocationStatus.FAILED,
            detail="需要 context.hit_context（本次授权命中）与 context.fetcher",
            via="fetch_reference",
        )
    try:
        reference = search_service.fetch_reference(
            citation_id,
            context=dict(context),  # type: ignore[arg-type]
            fetcher=fetcher,
        )
    except search_service.ReferenceBlockedError as exc:
        return _result(
            request, InvocationStatus.FAILED, detail=f"SSRF 护栏拒绝: {exc}", via="ssrf_guard"
        )
    except search_service.ReferenceNotAuthorizedError as exc:
        return _result(
            request,
            InvocationStatus.DENIED,
            detail=f"citation_id 不在本次授权集合: {exc}",
            via="fetch_reference",
        )
    return _result(
        request,
        InvocationStatus.OK,
        data={
            "reference": {
                "citation_id": reference.citation_id,
                "content": reference.content,
                "content_level": (
                    reference.content_level.value
                    if isinstance(reference.content_level, Enum)
                    else str(reference.content_level)
                ),
                "hit": reference.hit.model_dump(mode="json"),
            }
        },
        via="fetch_reference",
    )


# ---- 健康探测（读配置属性，零网络） ---------------------------------------


def _probe_vision(config: Any) -> CapabilityHealth:
    from plugins.bot_unified_runtime.domains.media.ingest import (
        vision_describe as _v,
    )

    if _v.build_vision_provider(config) is None:
        return CapabilityHealth.NOT_CONFIGURED
    if not bool(getattr(config, "bot_vision_enabled", False)):
        return CapabilityHealth.DISABLED
    return CapabilityHealth.AVAILABLE


def _probe_vision_degraded(config: Any) -> CapabilityHealth:
    """OCR 专用：VLM 在=degraded（代位），不在=not_configured。"""
    base = _probe_vision(config)
    if base is CapabilityHealth.AVAILABLE:
        return CapabilityHealth.DEGRADED
    return base


def _probe_saucenao(config: Any) -> CapabilityHealth:
    from plugins.bot_unified_runtime.domains.core.search.search_api import (
        resolve_search_secret,
    )

    key = resolve_search_secret(
        str(getattr(config, "bot_saucenao_api_key", "") or "env:SAUCENAO_API_KEY"),
        config,
    )
    return CapabilityHealth.AVAILABLE if str(key or "").strip() else CapabilityHealth.NOT_CONFIGURED


def _probe_asr(config: Any) -> CapabilityHealth:
    from plugins.bot_unified_runtime.domains.media.ingest import transcribe as _a

    if _a.build_asr_provider(config) is None:
        return CapabilityHealth.NOT_CONFIGURED
    if not bool(getattr(config, "bot_asr_enabled", False)):
        return CapabilityHealth.DISABLED
    return CapabilityHealth.AVAILABLE


def _probe_video(config: Any) -> CapabilityHealth:
    if not bool(getattr(config, "bot_video_understanding_enabled", False)):
        return CapabilityHealth.DISABLED
    vision_on = _probe_vision(config) in (CapabilityHealth.AVAILABLE, CapabilityHealth.DEGRADED)
    return CapabilityHealth.DEGRADED if not vision_on else CapabilityHealth.AVAILABLE


def _probe_web_search(config: Any) -> CapabilityHealth:
    _, usable = _web_provider_or_none(config)
    return CapabilityHealth.AVAILABLE if usable else CapabilityHealth.NOT_CONFIGURED


def _probe_acg(config: Any) -> CapabilityHealth:
    if not bool(getattr(config, "bot_search_acg_enabled", False)):
        return CapabilityHealth.NOT_CONFIGURED
    return CapabilityHealth.AVAILABLE


def _probe_creation_reserved(config: Any) -> CapabilityHealth:
    return CapabilityHealth.NOT_CONFIGURED


# ---- 默认描述符 ------------------------------------------------------------

_PROBE_VISION = "vision_registry"
_PROBE_VISION_DEGRADED = "vision_registry_degraded"
_PROBE_SAUCENAO = "saucenao_key"
_PROBE_ASR = "asr_registry"
_PROBE_VIDEO = "video_config"
_PROBE_WEB = "web_search_chain"
_PROBE_ACG = "acg_config"
_PROBE_CREATION = "creation_reserved"
_PROBE_TTS = "tts_config"

#: 已实现的执行面 adapter 形态（新增必须同时在此登记，未知名装配即炸）。
_KNOWN_ADAPTERS: frozenset[str] = frozenset({"command", "prepared"})

_MEDIA_REF = "plugins/bot_unified_runtime/domains/media"
_FILES_REF = "plugins/bot_unified_runtime/domains/files"
_SEARCH_REF = "plugins/bot_unified_runtime/domains/core/search"
_CREATION_REF = "plugins/bot_unified_runtime/domains/creation"

_MEDIA_INPUT = "media.v1 VisionImageRequest{image_urls[],query_text}"
_ASR_INPUT = "media.v1 AudioTranscribeRequest{audio_source}"
_VIDEO_INPUT = "media.v1 VideoAnalysisRequest{video_source,subtitle_text,metadata_text,question,deep}"
_FILE_INPUT = "files.v1 FileReadRequest{path}"
_GEN_INPUT = "files.v1 ArtifactGenerateRequest{user_text,reply_text,output_dir}"
_TEXT_OUT = "text.v1{text}"
_HITS_OUT = "search.v1{hits[]}"
_SEARCH_IN = "search.v1 SearchRequest{query,source_ids[],limit}"


def _media_descriptors() -> list[CapabilityDescriptor]:
    return [
        CapabilityDescriptor(
            capability_id="media.vision.image",
            family=CapabilityFamily.MEDIA,
            title="图片识别",
            input_protocol=_MEDIA_INPUT,
            output_protocol=_TEXT_OUT,
            timeout_seconds=25.0,
            limits={"max_images": 4, "max_chars": 2000, "max_url_length": 2048},
            limit_fields=(("image_urls", "max_images"), ("query_text", "max_chars")),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "识别失败返回空说明，不冒充成功",),
            implementation_ref=f"{_MEDIA_REF}/ingest/vision_describe.py#describe_images",
            config_keys=("bot_vision_enabled", "bot_vision_model_registry", "bot_vision_timeout_seconds"),
            health_probe=_PROBE_VISION,
            notes="VLM 链（GIF 取首帧/胶片条、本机字节优先）；失败=空+诚实说明",
        ),
        CapabilityDescriptor(
            capability_id="media.vision.ocr",
            family=CapabilityFamily.MEDIA,
            title="文字识别（OCR）",
            input_protocol=_MEDIA_INPUT,
            output_protocol=_TEXT_OUT,
            timeout_seconds=25.0,
            limits={"max_images": 4, "max_url_length": 2048},
            limit_fields=(("image_urls", "max_images"),),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "无独立 OCR 引擎；VLM 代位或诚实无结果",),
            implementation_ref=f"{_MEDIA_REF}/ingest/vision_describe.py#describe_images",
            config_keys=("bot_vision_enabled", "bot_vision_model_registry"),
            health_probe=_PROBE_VISION_DEGRADED,
            health_default=CapabilityHealth.NOT_CONFIGURED,
            notes="矩阵 L47 实证 OCR 无；VLM 文字转写代位=degraded（结果带 engine=vlm_transcribe）",
        ),
        CapabilityDescriptor(
            capability_id="media.vision.anime_ip",
            family=CapabilityFamily.MEDIA,
            title="动漫角色/IP 识别",
            input_protocol="media.v1 AnimeIpRequest{image_url}",
            output_protocol="search.v1{hits[{similarity,title,member,source,url}]}",
            timeout_seconds=20.0,
            limits={"max_url_length": 2048},
            limit_fields=(("image_url", "max_url_length"),),
            fallback_chain=(
                "vlm_candidate",
                HONEST_DEGRADE_PREFIX + "反搜无候选时不凭空猜 IP（候选/证据口径）",
            ),
            implementation_ref=f"{_MEDIA_REF}/search/sauce_search.py#search_saucenao_ex",
            config_keys=("bot_saucenao_api_key",),
            health_probe=_PROBE_SAUCENAO,
            notes="no_key/http_error/真无结果三态区分（2026-09-13 实战口径）",
        ),
        CapabilityDescriptor(
            capability_id="media.asr.speech",
            family=CapabilityFamily.MEDIA,
            title="语音识别（聊天语音）",
            input_protocol=_ASR_INPUT,
            output_protocol=_TEXT_OUT,
            timeout_seconds=30.0,
            limits={"max_url_length": 2048, "max_chars": 300},
            limit_fields=(("audio_source", "max_url_length"),),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "转写失败返回空说明，不阻断不冒充",),
            implementation_ref=f"{_MEDIA_REF}/ingest/transcribe.py#transcribe_audio",
            config_keys=("bot_asr_enabled", "bot_asr_model_registry", "bot_asr_timeout_seconds"),
            health_probe=_PROBE_ASR,
            notes="record 段 → ffmpeg 转 mp3 → OpenAI 兼容 /audio/transcriptions",
        ),
        CapabilityDescriptor(
            capability_id="media.asr.audio_file",
            family=CapabilityFamily.MEDIA,
            title="音频转文字",
            input_protocol=_ASR_INPUT,
            output_protocol=_TEXT_OUT,
            timeout_seconds=60.0,
            limits={"max_url_length": 2048, "max_chars": 2000},
            limit_fields=(("audio_source", "max_url_length"),),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "转写失败返回空说明",),
            implementation_ref=f"{_MEDIA_REF}/ingest/transcribe.py#transcribe_audio",
            config_keys=("bot_asr_enabled", "bot_asr_model_registry"),
            health_probe=_PROBE_ASR,
            notes="同 transcribe 链；http 拉取限 20MB（_download_audio 逐块限读）",
        ),
        CapabilityDescriptor(
            capability_id="media.video.recognize",
            family=CapabilityFamily.MEDIA,
            title="视频识别",
            input_protocol=_VIDEO_INPUT,
            output_protocol="media.v1{VideoAnalysisResult{text,signals}}",
            timeout_seconds=90.0,
            limits={"max_url_length": 2048, "max_chars": 4000},
            limit_fields=(("video_source", "max_url_length"),),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "全部信号缺失时返回空简报+说明",),
            implementation_ref=f"{_MEDIA_REF}/ingest/video_understanding.py#build_video_brief",
            config_keys=("bot_video_understanding_enabled", "bot_video_max_frames", "bot_video_asr_max_seconds"),
            health_probe=_PROBE_VIDEO,
            notes="字幕+均匀抽帧+音轨 ASR+元数据四路融合；深挖档 deep=true",
        ),
        CapabilityDescriptor(
            capability_id="media.video.subtitle",
            family=CapabilityFamily.MEDIA,
            title="视频字幕",
            input_protocol="media.v1 SubtitleRequest{subtitle_text}",
            output_protocol="media.v1{subtitle_text,present}",
            timeout_seconds=10.0,
            limits={"max_chars": 20000},
            limit_fields=(("subtitle_text", "max_chars"),),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "字幕轨缺失=空+诚实说明",),
            implementation_ref=f"{_MEDIA_REF}/ingest/video_understanding.py#build_video_brief",
            config_keys=("bot_video_skip_asr_with_subtitle",),
            notes="CC 字幕由摄取层提供，协议面不重新下载解析（诚实边界）",
        ),
        CapabilityDescriptor(
            capability_id="media.video.frame_extract",
            family=CapabilityFamily.MEDIA,
            title="视频抽帧",
            input_protocol="media.v1 FrameExtractRequest{video_source,frames}",
            output_protocol="media.v1{frames[{path,bytes}],work_dir}",
            timeout_seconds=45.0,
            limits={"max_frames": 24, "max_url_length": 2048},
            limit_fields=(("video_source", "max_url_length"), ("frames", "max_frames")),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "ffmpeg 缺失/失败=空列表说明",),
            implementation_ref=f"{_MEDIA_REF}/ingest/vision_describe.py#_extract_video_frames",
            config_keys=("bot_vision_video_frames", "bot_video_max_frames"),
            notes="§11 目标 8 帧/深挖 24 帧；产出=进程内临时文件（对外 asset 化留后续）",
        ),
        # 自动配音第二出站腿（VOICE-V12 收编中央调度层，mandate「TTS 也不例外」）。
        # 与 media.asr.speech 严格同型、方向相反（那条「音频→文字」、本条「文字→音频」）。
        # 生效顶的唯一家仍是 tts_presets.resolve_* 与 synthesize（零新常量、表内不留数）：
        # 文字硬顶/单产物字节顶/落盘配额全部由 handler 现读 config 交真身执行，limits 留空。
        CapabilityDescriptor(
            capability_id="media.tts.autodub",
            family=CapabilityFamily.MEDIA,
            title="自动配音（文字→语音）",
            input_protocol="media.v1 AutodubRequest{text}",
            output_protocol="media.v1{audio_file,review_text,content_sha256?,preset_id,seed}",
            required_roles=("user",),
            timeout_seconds=90.0,
            limits={},
            limit_fields=(),
            fallback_chain=(
                HONEST_DEGRADE_PREFIX + "配音失败=不发音频只发文字，绝不冒充合成成功",
            ),
            implementation_ref=f"{_MEDIA_REF}/capabilities/tts.py#synthesize_autodub",
            config_keys=(
                "bot_tts_enabled",
                "bot_tts_api_url",
                "bot_tts_ref_audios",
                "bot_tts_hard_max_chars",
                "bot_tts_max_audio_bytes",
                "bot_tts_timeout_seconds",
            ),
            health_probe=_PROBE_TTS,
            health_default=CapabilityHealth.NOT_CONFIGURED,
            notes=(
                "review 批准后、render 前的层 1 冻结 hook 的产出步（voice_enricher 直呼段收编）。"
                "门链（该不该配）与取文/政策/硬顶留在 hook（层 1）；本能力只做「一句话→一段音频」。"
                "生效顶唯一家=tts_presets.resolve_* 与 synthesize（本表不留数值）。"
                "现网缺省休眠（hook 键 ∧ 自动配音键皆关）⇒ 零调用点、行为逐字节不变。"
            ),
        ),
    ]


def _files_descriptors() -> list[CapabilityDescriptor]:
    def _read(cid: str, title: str, note_extra: str) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            capability_id=cid,
            family=CapabilityFamily.FILES,
            title=title,
            input_protocol=_FILE_INPUT,
            output_protocol="files.v1 FileRead{kind,title,text,metadata}",
            timeout_seconds=30.0,
            limits={"max_chars": 120000},
            limit_fields=(("path", "max_chars"),),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "旧格式/无文本诚实降级 parser_unavailable",),
            implementation_ref=f"{_FILES_REF}/sources/file_reader.py#read_supported_file",
            config_keys=("bot_file_read_max_chars",),
            notes="不执行、只读；旧 Office 不得伪装现代格式解析成功（指南 §1 L33）" + note_extra,
        )

    return [
        _read("files.read.word", "Word 读取", "；docx=python-docx 段落"),
        _read("files.read.ppt", "PPT 读取", "；.ppt OLE2 诚实 parser_unavailable（风险 8）"),
        _read("files.read.excel", "Excel 读取", "；.xls OLE2 同上；xlsx 只读+data_only"),
        _read("files.read.pdf", "PDF 读取", "；扫描件无文本=诚实降级（OCR 未接）"),
        _read("files.read.code", "代码读取", "；26 扩展名纯文本，绝不执行"),
        _read("files.read.markdown", "Markdown 读取", "；.md 纯文本路"),
        _read("files.read.latex", "LaTeX 读取", "；.tex 纯文本路（本席补进 _TEXT_EXTS），不编译不执行"),
        CapabilityDescriptor(
            capability_id="files.artifact.generate",
            family=CapabilityFamily.FILES,
            title="代码/文本资产生成",
            input_protocol=_GEN_INPUT,
            output_protocol="files.v1 GeneratedFile{path,kind}",
            required_roles=("admin",),
            timeout_seconds=15.0,
            limits={"max_bytes": 2 * 1024 * 1024, "max_chars": 120000},
            limit_fields=(("reply_text", "max_chars"),),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "无生成意图/校验失败=诚实说明不产空文件",),
            implementation_ref=f"{_FILES_REF}/sources/file_reader.py#build_generated_file",
            config_keys=("bot_file_read_max_chars",),
            notes="只许 txt/md/代码、py 语法门、原子写、禁冒充 Office/PDF；默认不执行（§11 L254）",
        ),
    ]


def _search_descriptors() -> list[CapabilityDescriptor]:
    return [
        CapabilityDescriptor(
            capability_id="search.web",
            family=CapabilityFamily.SEARCH,
            title="网络搜索",
            input_protocol=_SEARCH_IN,
            output_protocol=_HITS_OUT,
            timeout_seconds=30.0,
            limits={"max_chars": 500, "max_results": 20},
            limit_fields=(("query", "max_chars"),),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "引擎链空=诚实说明，不编造结果",),
            implementation_ref=f"{_SEARCH_REF}/web_search.py#build_web_search_provider",
            config_keys=("bot_web_search_enabled", "bot_web_search_provider", "bot_web_search_tavily_api_key"),
            health_probe=_PROBE_WEB,
            notes="tavily 主链+you/langsearch 回退；DDG/Bing 无 key 可用；disabled=Null",
        ),
        CapabilityDescriptor(
            capability_id="search.acg",
            family=CapabilityFamily.SEARCH,
            title="ACG 竖源检索",
            input_protocol=_SEARCH_IN,
            output_protocol="search.v1{results[{source,title,snippet,url,date,extra}]}",
            timeout_seconds=20.0,
            limits={"max_chars": 500},
            limit_fields=(("query", "max_chars"),),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "未命中意图/竖源空=诚实跳过",),
            implementation_ref="plugins/bot_unified_runtime/sources/acg_search.py#search_acg_verticals",
            config_keys=("bot_search_acg_enabled", "bot_search_acg_timeout_seconds"),
            health_probe=_PROBE_ACG,
            notes="Bangumi/萌百/B站三竖源+时效加权（SEARCH 席 2026-09-17）",
        ),
        CapabilityDescriptor(
            capability_id="search.unified",
            family=CapabilityFamily.SEARCH,
            title="统一搜索（九源协议）",
            input_protocol=_SEARCH_IN,
            output_protocol="search.v1 SearchResponse{status,hits[],per_source[]}",
            timeout_seconds=30.0,
            limits={"max_chars": 500, "source_ids_max": 10},
            limit_fields=(("query", "max_chars"),),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "无可用 provider=dependency_unavailable 诚实",),
            implementation_ref="plugins/bot_unified_runtime/domains/core/search/search_service.py#UnifiedSearchService",  # RET2B-PREP: sources/search_service.py 垫片已退役
            config_keys=("bot_web_search_enabled",),
            health_probe=_PROBE_WEB,
            notes="预算 总12s/单源6s/并发2；缓存键含 owner；provider 可经 context 注入",
        ),
        CapabilityDescriptor(
            capability_id="search.reference.fetch",
            family=CapabilityFamily.SEARCH,
            title="引用正文取回",
            input_protocol="search.v1 ReferenceFetchRequest{citation_id}",
            output_protocol="search.v1 FetchedReference",
            timeout_seconds=20.0,
            limits={"max_chars": 128},
            limit_fields=(("citation_id", "max_chars"),),
            fallback_chain=(HONEST_DEGRADE_PREFIX + "护栏拒绝/未授权=诚实拒绝",),
            implementation_ref="plugins/bot_unified_runtime/domains/core/search/search_service.py#fetch_reference",
            notes="结构性只收本次授权 citation_id；取回前过 ssrf_guard（SEARCH-002 面）",
        ),
    ]


def _creation_descriptors() -> list[CapabilityDescriptor]:
    """TTS/绘图对接点（只就位，不实现；domains/creation 本席禁触）。"""
    # 中央 TTS 契约单一真源（Wave G 落在 domains/media/tts_presets.py）：本表**不得**再持有
    # 第二套数值——旧写法在这里写死 3000 字/60s/20MiB，与中央 2000 字/131s/8MiB 四组互斥，
    # 正是审计 E3-4 定罪的「契约漂移」（60s 更是 Wave G 明文作废的旧判据）。
    # 第二轮收口（R1/I-3）：改引 `resolve_hard_max_chars()` 仍不够——**描述符表在装配期建，
    # 拿不到 config**，于是表里那个数永远是「未配口径的兜底值」，而真身按
    # `config.bot_tts_hard_max_chars` 现读（实测：设 500 则真身=500、表=2000，分叉照样成立）。
    # ⇒ 表内**不留任何 TTS 数值**：生效顶的唯一家 = `tts_presets.resolve_*`，由 handler 现读；
    #   本 descriptor 只声明协议形态与该读哪两个 config 键（config_keys）。留数=造第二把假尺子。
    return [
        CapabilityDescriptor(
            capability_id="creation.tts.synthesize",
            family=CapabilityFamily.CREATION,
            title="TTS 合成（协议对接点）",
            input_protocol="creation.v1 TTSJobRequest{text|approved_reply_id,provider,model,voice,language,speed,format}",
            output_protocol="creation.v1 CreationJob{job_id,state,asset_id?,usage?}",
            required_roles=("user",),
            timeout_seconds=120.0,
            limits={},
            fallback_chain=(HONEST_DEGRADE_PREFIX + "对接点未接线：unavailable，不盲重合成",),
            implementation_ref=f"{_CREATION_REF}/tts/__init__.py#reserved",
            config_keys=("bot_tts_enabled", "bot_tts_hard_max_chars", "bot_tts_max_audio_bytes"),
            health_probe=_PROBE_CREATION,
            health_default=CapabilityHealth.NOT_CONFIGURED,
            notes=(
                "reserved：RWPA1 creation 契约（domains/creation/_common/contracts.py "
                "CreationJobState/UsageLine/AssetRef）；**TTS 生效顶不入本表**——唯一家是 "
                "domains/media/tts_presets.py 的 resolve_hard_max_chars/resolve_max_audio_bytes"
                "（config 显式值优先，0/未配⇒内置常量 2000 字·8MiB），由 handler 现读；"
                "旧 §11 的 3000 字/speed 0.75..1.25/60s/20MiB 已作废；"
                "现载体 media/capabilities/tts.py 归属裁决=§10 W-PA2"
            ),
        ),
        CapabilityDescriptor(
            capability_id="creation.image.generate",
            family=CapabilityFamily.CREATION,
            title="AI 绘图（协议对接点）",
            input_protocol="creation.v1 ImageJobRequest{task,prompt,negative_prompt,assets[],count,seed,steps,guidance}",
            output_protocol="creation.v1 CreationJob{job_id,state,asset_id?,usage?}",
            required_roles=("user",),
            timeout_seconds=180.0,
            limits={
                "max_prompt_chars": 4000,
                "max_negative_chars": 2000,
                "max_count": 2,
                "max_input_pixels": 20_000_000,
                "max_steps": 50,
            },
            fallback_chain=(HONEST_DEGRADE_PREFIX + "对接点未接线：unavailable，未知任务不重发",),
            implementation_ref=f"{_CREATION_REF}/image/__init__.py#reserved",
            health_probe=_PROBE_CREATION,
            health_default=CapabilityHealth.NOT_CONFIGURED,
            notes=(
                "reserved：零现载体（矩阵 L52）；§11 L258 prompt≤4000/negative≤2000/"
                "count≤2/输入≤20MP/steps≤50∩provider；未支持参数 422 不静默丢弃；"
                "契约=_common/contracts.py（AssetRef 拒路径/URL、20MP 上限）"
            ),
        ),
    ]


# ===========================================================================
# 路由能力的执行面（Wave 4.1）：authoring 在注册册的 RouteCapabilityDecl.execution，
# 壳**只派生**描述符并挂信封 handler——同 §7 纪律「不建第二真源」，也满足
# test_no_capability_id_is_authored_in_two_places（它按字面 CapabilityDescriptor( 计 authoring）。
# 在册 ≠ 已接入：命令路真身仍骑根泛型执行器 `capability_factory(config)`，
# 那一步统一切换见 SEAT-MAIN §7/§11。
# ===========================================================================


def _probe_tts(config: Any) -> CapabilityHealth:
    """三态诚实：开关关=disabled；启用但无可用参考音频=not_configured；齐备=available。

    **零网络**：绝不探测引擎 `/control`——该端点无鉴权且会杀进程（Wave G 铁律）。
    """
    if not bool(getattr(config, "bot_tts_enabled", False)):
        return CapabilityHealth.DISABLED
    from plugins.bot_unified_runtime.domains.media.capabilities import tts as _tts

    ref = _tts.pick_ref_audio(
        getattr(config, "bot_tts_ref_audios", []) or [],
        base_dir=str(getattr(config, "bot_tts_gptsovits_dir", "") or ""),
    )
    return CapabilityHealth.AVAILABLE if ref is not None else CapabilityHealth.NOT_CONFIGURED


def orchestrated_command(capability_id: str, capability: Any, config: Any) -> Any:
    """Wave 4.1 主缝：命令形能力的「能力执行步」委托给中央 invoker。

    在册且 adapter=command ⇒ 权限/健康/降级/审计走层 2，执行体仍是调用方交来的那个
    已装配好的 capability（**不重新组装真身**，见 provider 注入墙 SEAT-S-WIRE-CHAT §C）；
    未在册 ⇒ 原样执行旧路——旧路不是暗账：可枚举（`_route_execution_adapters()` 之外），
    缺口条数由 tests/test_descriptor_wiredness_ledger.py 的 GAP_CEILING 棘轮只准降不准升。
    """

    def _step(message: Any, decision: Any) -> Any:
        # 呈现契约（层 1）在本模块**必须带别名**：壳自己的执行信封旧名就叫
        # CapabilityResult，Wave 0 已改名 InvocationResult；裸用那个名字会把两层
        # 又混回一个词（tests/test_capability_result_unique.py 的符号门正是防这个）。
        from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
            CapabilityResult as PresentationResult,
        )

        if _route_execution_adapters().get(capability_id) not in _KNOWN_ADAPTERS:
            return capability(message, decision)
        result = default_invoker().invoke(
            CapabilityRequest(
                capability_id=capability_id,
                payload={"message": message},
                principal=str(getattr(message, "sender_id", "anonymous") or "anonymous"),
                roles=tuple(getattr(decision, "actor_roles", ()) or ()),
                request_id=str(getattr(message, "request_id", "") or ""),
                session_key=str(getattr(message, "session_key", "") or ""),
                context={"config": config, "decision": decision, "capability": capability},
            )
        )
        presented = result.data.get(PRESENTATION_DATA_KEY)
        if isinstance(presented, dict):
            return PresentationResult.model_validate(presented)
        primary_error = result.data.get(INVOKER_ERROR_DATA_KEY)
        if isinstance(primary_error, BaseException):
            # 能力真的崩了（主链+降级链全炸）：把原始异常交回层 1，错误卡旁路
            # （`RuntimePipeline._internal_error`）与接入接缝前逐字同构。中央吞异常
            # 换温和短句＝诊断面消失（S-ROWS X-8 实跑坐实），这里不换。
            raise primary_error
        # 中央拦下（DENIED/LIMIT_EXCEEDED/UNAVAILABLE…）时绝不静默丢回复：温和短句 + 终态入审计。
        return PresentationResult(
            request_id=str(getattr(message, "request_id", "") or ""),
            capability_id=capability_id,
            kind="text",
            body="这会儿说不上话来，稍后再试一次吧。",
            audit_tags=["orchestration", f"orchestration:{result.status.value}"],
            operational_issue=None,
        )

    # 幂等标记：根装配有多个汇合点都会调本缝（`_run_simple_capability` 与
    # `_run_capability_through_pipeline`），套两遍 = 一次调用两层治理跑两回、审计落两行。
    # 见 `_run_capability_through_pipeline` 的"已包过就不再包"。
    _step.orchestrated_capability_id = capability_id  # type: ignore[attr-defined]
    return _step


def _callable_identity(fn: object) -> str:
    """执行体的在册身份 `模块.限定名`（闭包也能看出是谁）。

    只进审计的 `private_debug`/`via`，不含正文与密钥；`<locals>` 原样保留——
    "装配现场造的那个闭包"正是这里要区分的东西，洗掉它就洗掉了证据。
    """
    module = str(getattr(fn, "__module__", "?") or "?")
    qualname = str(getattr(fn, "__qualname__", None) or getattr(fn, "__name__", "?") or "?")
    return f"{module}.{qualname}"


def _make_command_handler(implementation_ref: str) -> HandlerFn:
    """命令形能力（`build_x(config) -> (message, decision) -> CapabilityResult`）的统一信封。

    口径裁决（各席交接块写法不一时以此为准）：**运行期依赖走 context**（config/decision），
    **用户载荷走 payload**（message）。缺 payload.message=FAILED（`InvocationStatus` 无
    REJECTED 成员，别照抄交接稿里那个名字）。
    """
    module_name, _, symbol = implementation_ref.partition("#")
    dotted = module_name.removesuffix(".py").replace("/", ".")

    def _handle(request: CapabilityRequest) -> InvocationResult:
        import importlib

        message = request.payload.get("message")
        if message is None:
            return _result(request, InvocationStatus.FAILED, detail="payload.message 缺失")
        # 执行体优先级：调用方交来的**已装配** capability（保留其装配期注入缝，
        # 与接入前直呼逐字同构）> 按 implementation_ref 自建（自建会丢 provider 注入）。
        # via 带**实际跑的那个可调用对象的身份**，否则"在册说 A、实跑 B"事后无从判定
        # （R-CENTRAL I-1：只记 `caller_capability` 五个字＝知道走了调用方、不知道是谁）。
        # 在册值与被调用值的比对刻意留在这儿**之外**：装配现场交来的多是 builder 的产物
        # 闭包，qualname 天然不等于 builder 符号名，硬比会得到"每条都带警告"的噪声判据。
        callable_from_caller = request.context.get("capability")
        decision = request.context.get("decision")
        if callable(callable_from_caller):
            presented = callable_from_caller(message, decision)
            via = f"caller_capability:{_callable_identity(callable_from_caller)}"
        else:
            builder = getattr(importlib.import_module(dotted), symbol)
            presented = builder(_config_of(request))(message, decision)
            via = symbol
        return _result(
            request,
            InvocationStatus.OK,
            data={PRESENTATION_DATA_KEY: presented.model_dump()},
            via=via,
        )

    return _handle


def _make_prepared_handler(implementation_ref: str) -> HandlerFn:
    """prepared 形能力（执行体＝调用方**已装配**成品）的统一信封。

    与命令形只差一句：命令形的 builder 只吃 config，拿不到成品时按 ref 自建是同构的；
    prepared 形的 builder 还要运行期件（render_backend / provider / 第二实例句柄），
    **绝不允许按 ref 自建**——自建会悄悄丢掉装配期注入，跑出一条与装配现场不同的
    第二通路（比"没走中央"更坏：走中央了，但跑的是另一套引擎）。
    拿不到成品 ⇒ `UNAVAILABLE` + 诚实 detail，不猜、不重建、不回退直呼。
    `implementation_ref` 在此只作 provenance（在册说真身是谁），不参与执行。
    """

    def _handle(request: CapabilityRequest) -> InvocationResult:
        message = request.payload.get("message")
        if message is None:
            return _result(request, InvocationStatus.FAILED, detail="payload.message 缺失")
        callable_from_caller = request.context.get("capability")
        if not callable(callable_from_caller):
            return _result(
                request,
                InvocationStatus.UNAVAILABLE,
                detail=f"prepared 能力未交执行体（在册真身 {implementation_ref}）",
                via="prepared_no_capability",
            )
        decision = request.context.get("decision")
        presented = callable_from_caller(message, decision)
        return _result(
            request,
            InvocationStatus.OK,
            data={PRESENTATION_DATA_KEY: presented.model_dump()},
            via=f"caller_capability:{_callable_identity(callable_from_caller)}",
        )

    return _handle


def _route_execution_rows() -> tuple[tuple[CapabilityDescriptor, str], ...]:
    """把带 execution 面的路由行派生成 (描述符, adapter) 对——**纯函数，不写全局**。

    无一行字面 ``capability_id=`` ⇒ 不构成第二处 authoring；描述符与 handler 同源同代际，
    所以"表里有描述符却没注册 handler"这类半新半旧状态在结构上不可能出现（R-A/C-03、M-02）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry as _registry,
    )  # 局部 import：本壳与注册册互为环（沿用 _build_capability_descriptor 同款写法）
    rows: list[tuple[CapabilityDescriptor, str]] = []
    for decl in _registry.ROUTE_CAPABILITY_DECLARATIONS:
        execution = decl.execution
        if execution is None:
            continue
        # 派生即校验（R-A/C-02、C-04）：坏 roles/未知 adapter/ref 越界 ⇒ 装配当场炸，
        # 绝不等 invoke 时 min() 抛或 importlib 跑到包外。
        if execution.adapter not in _KNOWN_ADAPTERS:
            raise ValueError(f"{decl.capability_id}: 未实现的执行面 adapter {execution.adapter!r}")
        for role in execution.roles:
            if role not in ROLE_ORDER or role == ROLE_BLOCKED:
                raise ValueError(f"{decl.capability_id}: execution.roles 含非法角色 {role!r}")
        ref = execution.implementation_ref
        module_part, hash_mark, symbol_part = ref.partition("#")
        if (
            not hash_mark
            or not symbol_part
            or not module_part.startswith("plugins/bot_unified_runtime/")
            or module_part.startswith("plugins/bot_unified_runtime/../")
            or ".." in module_part
        ):
            raise ValueError(f"{decl.capability_id}: implementation_ref 形态越界 {ref!r}")
        if execution.family not in {member.value for member in CapabilityFamily}:
            raise ValueError(f"{decl.capability_id}: 未知能力族 {execution.family!r}")
        rows.append(
            (
            CapabilityDescriptor(
                capability_id=decl.capability_id,
                family=CapabilityFamily(execution.family),
                # 内部席位（如 IGNORE 兜底）在册 label 为空是诚实形态，不是缺数据；
                # 缺省 title 拿不到就整表 validate 红 ⇒ 派生器不许因为"这行没人类标签"而炸。
                title=decl.label or decl.value,
                input_protocol="bot.v1 command{payload.message; context{config,decision}}",
                output_protocol=f"data[{PRESENTATION_DATA_KEY}]: CapabilityResult.model_dump()",
                required_roles=execution.roles,
                timeout_seconds=execution.timeout_seconds,
                limits={},  # 数值零硬编码：限额真顶由 handler 现读 config（见注册册注释）
                fallback_chain=(HONEST_DEGRADE_PREFIX + execution.degrade_note,),
                implementation_ref=execution.implementation_ref,
                config_keys=execution.config_keys,
                health_probe=execution.health_probe,
                notes=(
                    f"执行面 authoring=capability_registry 路由行（kind={decl.kind}）；"
                    f"adapter={execution.adapter}。当前生产仍经根泛型执行器执行，"
                    "统一切换=Wave 4.1（SEAT-MAIN §11 provider 注入墙未破之前不得翻点）。"
                ),
            ),
            execution.adapter,
        ))
    return tuple(rows)


def _route_execution_descriptors() -> list[CapabilityDescriptor]:
    return [descriptor for descriptor, _adapter in _route_execution_rows()]


def _route_execution_adapters() -> dict[str, str]:
    return {descriptor.capability_id: adapter for descriptor, adapter in _route_execution_rows()}


# ===========================================================================
# 九源逐源状态面（V21-SEARCH-001：诚实 not_configured，禁假成功）
# ===========================================================================

#: 九平台 + general（SOURCE_REGISTRY 的 source_id 集合，W7 已登记）。
NINE_SOURCE_IDS: tuple[str, ...] = (
    "bilibili",
    "xiaohongshu",
    "youtube",
    "x",
    "github",
    "linux_do",
    "csdn",
    "zhihu",
    "cnki",
)


@dataclass(frozen=True)
class SearchSourceStatus:
    """逐源能力状态（扩展 §6.1 表逐行 + 运行时诚实口径）。"""

    source_id: str
    display_name: str
    status: CapabilityHealth
    reason: str
    preferred_mode: str
    fallback_and_limits: str
    requires_authorized_provider: bool
    private_scope_supported: bool


def search_source_status(
    config: Any,
    *,
    registered_providers: Mapping[str, Any] | None = None,
) -> list[SearchSourceStatus]:
    """九源逐源状态：配了 provider/key=available，没配=not_configured。

    - ``requires_authorized_provider=True``（xhs/cnki）：无注册 provider 一律
      not_configured——搜索引擎 site: 兜底对该两源不视为可用（授权边界）；
    - 其余七源：web 引擎链可用（enabled）→ available（走 site: 兜底模式）；
      否则 not_configured；
    - github 私库 scope 无凭据 → 单独注明（私库不外泄）；
    - B站/YT 字幕能力=unknown（搜索命中≠字幕已读取，§6.1 表原文）。
    """
    from plugins.bot_unified_runtime.domains.core.search.search_service import (
        SOURCE_REGISTRY,
    )

    providers = dict(registered_providers or {})
    _, web_usable = _web_provider_or_none(config)
    statuses: list[SearchSourceStatus] = []
    for source_id in NINE_SOURCE_IDS:
        caps = SOURCE_REGISTRY.get(source_id)
        if caps is None:  # pragma: no cover - SOURCE_REGISTRY 回归锁保证
            statuses.append(
                SearchSourceStatus(
                    source_id=source_id,
                    display_name=source_id,
                    status=CapabilityHealth.UNKNOWN,
                    reason="SOURCE_REGISTRY 缺行（登记漂移）",
                    preferred_mode="",
                    fallback_and_limits="",
                    requires_authorized_provider=False,
                    private_scope_supported=False,
                )
            )
            continue
        if caps.requires_authorized_provider:
            if source_id in providers:
                status, reason = CapabilityHealth.AVAILABLE, "已注册授权 provider"
            else:
                status, reason = (
                    CapabilityHealth.NOT_CONFIGURED,
                    "需要授权 provider，未配置（授权边界，不用搜索引擎兜底冒充）",
                )
        elif web_usable:
            status, reason = (
                CapabilityHealth.AVAILABLE,
                "通用引擎链 site: 兜底模式（搜索命中≠全文/字幕已读取）",
            )
        else:
            status, reason = (
                CapabilityHealth.NOT_CONFIGURED,
                "bot_web_search_enabled=false 且无注册 provider",
            )
        if source_id == "github" and status is CapabilityHealth.AVAILABLE:
            reason += "；私库 scope 无凭据=not_configured（私库不外泄）"
        statuses.append(
            SearchSourceStatus(
                source_id=source_id,
                display_name=caps.display_name,
                status=status,
                reason=reason,
                preferred_mode=caps.preferred_mode,
                fallback_and_limits=caps.fallback_and_limits,
                requires_authorized_provider=caps.requires_authorized_provider,
                private_scope_supported=caps.private_scope_supported,
            )
        )
    return statuses


# ===========================================================================
# 默认装配（惰性单例；测试可自建独立 invoker）
# ===========================================================================

_DEFAULT_INVOKER: CapabilityInvoker | None = None
_DEFAULT_LOCK = threading.Lock()


def _build_default_registrations() -> CapabilityInvoker:
    """把「编排侧条目真源」投影成 invoker 的四张执行侧视图（Wave 2 起为派生）。

    真源只有一个：``_ORCHESTRATION_DESCRIPTORS``（= ``DESCRIPTOR_BUILDERS`` 的展开）。
    下面的 5 个注册表类不再是独立的「在册」答案——「能力是否在册」唯一答案=
    :data:`CAPABILITY_DESCRIPTOR`；本函数只负责把同一批条目装进执行所需的四类索引。
    handler/fallback/probe 的字面 id 由 tests/test_capability_single_registration.py
    常驻比对：出现「注册了条目表里没有的 id」即红（禁第二处 authoring）。
    """
    registry = CapabilityRegistry()
    handlers = HandlerRegistry()
    fallbacks = FallbackRegistry()
    probes = HealthProbeRegistry()

    for descriptor in _ORCHESTRATION_DESCRIPTORS:
        registry.register(descriptor)
        _DESCRIPTOR_VIEW[descriptor.capability_id] = descriptor

    handlers.register("media.vision.image", _handle_media_vision_image)
    handlers.register("media.vision.ocr", _handle_media_ocr)
    handlers.register("media.vision.anime_ip", _handle_media_anime_ip)
    handlers.register("media.asr.speech", _make_asr_handler("transcribe"))
    handlers.register("media.asr.audio_file", _make_asr_handler("transcribe"))
    handlers.register("media.video.recognize", _handle_media_video_recognize)
    handlers.register("media.video.subtitle", _handle_media_video_subtitle)
    handlers.register("media.video.frame_extract", _handle_media_frame_extract)
    handlers.register("media.tts.autodub", _handle_media_tts_autodub)

    for cid, kinds, label in [
        ("files.read.word", ("document",), "Word"),
        ("files.read.ppt", ("presentation",), "PPT"),
        ("files.read.excel", ("spreadsheet",), "Excel"),
        ("files.read.pdf", ("pdf",), "PDF"),
        ("files.read.code", ("code", "text"), "代码"),
        ("files.read.markdown", ("text",), "Markdown"),
        ("files.read.latex", ("text",), "LaTeX"),
    ]:
        handlers.register(cid, _make_file_read_handler(expected_kinds=kinds, label=label))
    handlers.register("files.artifact.generate", _handle_files_artifact_generate)

    handlers.register("search.web", _handle_search_web)
    handlers.register("search.acg", _handle_search_acg)
    handlers.register("search.unified", _handle_search_unified)
    handlers.register("search.reference.fetch", _handle_search_reference_fetch)

    # 媒体反搜的 VLM 候选降级：SauceNAO 失败时用已配置 VLM 给候选（不猜死）。
    fallbacks.register("media.vision.anime_ip", "vlm_candidate", _handle_media_vision_image)

    # 路由执行面（注册册 authoring，壳派生）：adapter 形态按声明挑选，缺件即红不静默。
    for descriptor, adapter in _route_execution_rows():
        if adapter == "command":
            handlers.register(
                descriptor.capability_id,
                _make_command_handler(descriptor.implementation_ref),
            )
        elif adapter == "prepared":
            # 只登记信封，执行体等调用方经 context["capability"] 交来（见 `_make_prepared_handler`）。
            handlers.register(
                descriptor.capability_id,
                _make_prepared_handler(descriptor.implementation_ref),
            )
        else:  # 未知形态在派生期已炸，这里只兜第二道
            raise ValueError(f"{descriptor.capability_id}: 未实现的执行面 adapter {adapter!r}")

    probes.register(_PROBE_VISION, _probe_vision)
    probes.register(_PROBE_VISION_DEGRADED, _probe_vision_degraded)
    probes.register(_PROBE_SAUCENAO, _probe_saucenao)
    probes.register(_PROBE_ASR, _probe_asr)
    probes.register(_PROBE_VIDEO, _probe_video)
    probes.register(_PROBE_WEB, _probe_web_search)
    probes.register(_PROBE_ACG, _probe_acg)
    probes.register(_PROBE_CREATION, _probe_creation_reserved)
    probes.register(_PROBE_TTS, _probe_tts)

    return CapabilityInvoker(
        registry=registry,
        handlers=handlers,
        fallbacks=fallbacks,
        probes=probes,
    )


def default_invoker() -> CapabilityInvoker:
    global _DEFAULT_INVOKER
    if _DEFAULT_INVOKER is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_INVOKER is None:
                _DEFAULT_INVOKER = _build_default_registrations()
    return _DEFAULT_INVOKER


def attach_default_audit_sink(hook: Callable[[CapabilityAuditRecord], None]) -> None:
    """装配期注册「中央执行审计 sink」的**唯一**口子。

    invoker 每次终态都 emit，但注册表此前全树零注册 ⇒ 中央执行在生产**跑了不留痕**
    （S-TTSPIPE 实测：`audit_hooks` 在 `plugins/` 下无任何生产注册点）。走本函数注册而
    不是让消费方各自 `default_invoker()`，是为了保住"默认 invoker 只一个生产取用点"
    这条结构判据（`tests/test_orchestration_callsite_single.py` 的第二 invoker 点位锁）。
    """

    default_invoker().audit_hooks.register(hook)


# ===========================================================================
# Wave 2 唯一在册表 CAPABILITY_DESCRIPTOR —— 「能力 X 是否在册」的唯一答案
#
# 取代谁（规格 §7 两行纪律）：
#   取代「三处各说各话」这件事本身——它**不新建 orchestrator**，只是把
#   ①本模块的描述符 builders（编排侧：handler_ref/健康/降级/限额）
#   ②capability_registry.ROUTE_CAPABILITY_DECLARATIONS（路由 kind/priority/matcher）
#   ③capability_registry.CONTROLLED_INTERNAL_CAPABILITIES（受门在册）
#   ④capability_registry.HELP_TOPIC_DECLARATIONS（帮助主题）
#   ⑤capability_registry.INTERFACE_DECLARATIONS（接口 id 联动）
#   五路输入按 capability_id **取并集**派生成一张只读表。
# 旧件何时退役：五路输入表**不删**（导出面/AST 静态提取/回归快照三重依赖），
#   Wave 2 起它们的身份从「真源」降为「唯一表的声明式输入源 + 注释指针」；
#   消费面（feature_catalog 的 gate 绑定、command_catalog 的路由派生）改读本表。
#
# 合并语义=行为等价：``gate_feature_id`` 只按 ②③ 的旧口径赋值，因此
# ``capability_feature_bindings()`` 由本表投影的结果与迁移前两表并集**逐字节相同**
# （等值锁 tests/test_capability_single_registration.py）。
# ===========================================================================

CAPABILITY_SOURCE_ORCHESTRATION = "orchestration_descriptor"
CAPABILITY_SOURCE_ROUTE = "route_declaration"
CAPABILITY_SOURCE_CONTROLLED = "controlled_internal"
CAPABILITY_SOURCE_HELP = "help_topic"
CAPABILITY_SOURCE_INTERFACE = "interface_declaration"

#: 描述符真源清单（唯一表与 invoker 共用同一份，杜绝「表里有条目、invoker 没注册」）。
DESCRIPTOR_BUILDERS: tuple[Callable[[], list[CapabilityDescriptor]], ...] = (
    _media_descriptors,
    _files_descriptors,
    _search_descriptors,
    _creation_descriptors,
    _route_execution_descriptors,
)

#: 编排侧条目真身（书写序=builders 序，供唯一表与 invoker 双向对照）。
_ORCHESTRATION_DESCRIPTORS: tuple[CapabilityDescriptor, ...] = tuple(
    descriptor for builder in DESCRIPTOR_BUILDERS for descriptor in builder()
)


@dataclass(frozen=True)
class RouteBinding:
    """一个能力挂在某个 RouteKind 上的事实（**一个 id 可挂多条**，实况：
    ``bot.moegirl`` 同时是 MOEGIRL 与 MOEGIRL_QUESTION 两行的能力入口）。"""

    kind: str
    value: str
    priority: int
    label: str
    matcher_name: str
    has_rule: bool
    command: bool


@dataclass(frozen=True)
class HelpBinding:
    """一个能力对应的帮助主题（实况：``bot.reminder`` 同时挂「提醒」「笔记」两主题）。"""

    topic: str
    admin_only: bool


@dataclass(frozen=True)
class CapabilityRegistration:
    """唯一在册表的一行：一个 capability_id 的全部在册事实（跨五路输入合并）。

    列语义（缺省=该路输入未覆盖此项，**不等于「没有」**，除非 provenance 说明）：
    - handler_ref：编排侧=descriptor.implementation_ref；Wave 3 逐域补齐其余能力。
    - routes/help_topics：**多值**——同 id 多路由/多主题是既有语义，不是重复注册。
      「重复注册」的定义=同一 id 被两处 *authoring 表* 各自登记（见 authored_by 与常驻门）。
    - gate_feature_id：非空 ⇔ 该 id 受 ProductFeatureGate 执法（fail-closed 面）。
    - authored_by：本行由哪几路输入贡献（审计列，逐项可回退的依据）。
    """

    capability_id: str
    title: str = ""
    handler_ref: str = ""
    health_probe: str = ""
    health_default: CapabilityHealth = CapabilityHealth.UNKNOWN
    fallbacks: tuple[str, ...] = ()
    timeout_seconds: float | None = None
    family: CapabilityFamily | None = None
    gate_feature_id: str = ""
    routes: tuple[RouteBinding, ...] = ()
    help_topics: tuple[HelpBinding, ...] = ()
    interface_id: str = ""
    authored_by: tuple[str, ...] = ()

    @property
    def gate_scoped(self) -> bool:
        return bool(self.gate_feature_id)

    @property
    def has_route_rule(self) -> bool:
        return any(route.has_rule for route in self.routes)

    @property
    def route_kinds(self) -> tuple[str, ...]:
        return tuple(route.kind for route in self.routes)

    @property
    def topics(self) -> tuple[str, ...]:
        return tuple(help_topic.topic for help_topic in self.help_topics)


def _gate_feature_id(capability_id: str) -> str:
    """feature gate 节点 id 的唯一换算（迁移前=feature_catalog 内联表达式，逐字等价）。"""
    return capability_id.replace("bot.", "bot.plugin.", 1)


def _build_capability_descriptor() -> dict[str, CapabilityRegistration]:
    """五路输入取并集 → 唯一在册表（纯派生，零新增真源；同列冲突即抛）。"""
    fields: dict[str, dict[str, Any]] = {}
    sources: dict[str, list[str]] = {}
    routes: dict[str, list[RouteBinding]] = {}
    topics: dict[str, list[HelpBinding]] = {}

    def _touch(capability_id: str, source: str) -> dict[str, Any]:
        if not capability_id:
            return {}
        if source not in sources.setdefault(capability_id, []):
            sources[capability_id].append(source)
        return fields.setdefault(capability_id, {})

    def _put(bucket: dict[str, Any], key: str, value: Any, capability_id: str) -> None:
        if value is None:
            return
        previous = bucket.get(key)
        if previous is not None and previous != value:
            # 同一标量列被两路输入各自 author 且不一致 = 「多套并行未收敛」的机器证据。
            raise ValueError(
                f"capability_id={capability_id!r} 的 {key} 在两路输入中不一致："
                f"{previous!r} vs {value!r}（来源 {sources.get(capability_id)}）"
            )
        bucket[key] = value

    # ① 编排侧描述符（本模块 builders）。
    for descriptor in _ORCHESTRATION_DESCRIPTORS:
        bucket = _touch(descriptor.capability_id, CAPABILITY_SOURCE_ORCHESTRATION)
        _put(bucket, "title", descriptor.title, descriptor.capability_id)
        _put(bucket, "handler_ref", descriptor.implementation_ref, descriptor.capability_id)
        _put(bucket, "health_probe", descriptor.health_probe, descriptor.capability_id)
        _put(bucket, "health_default", descriptor.health_default, descriptor.capability_id)
        _put(bucket, "fallbacks", descriptor.fallback_chain, descriptor.capability_id)
        _put(bucket, "timeout_seconds", descriptor.timeout_seconds, descriptor.capability_id)
        _put(bucket, "family", descriptor.family, descriptor.capability_id)

    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry as _registry,
    )

    # ② 路由声明（每行一条 RouteBinding，同 id 多 kind 合法）。
    for decl in _registry.ROUTE_CAPABILITY_DECLARATIONS:
        bucket = _touch(decl.capability_id, CAPABILITY_SOURCE_ROUTE)
        binding = RouteBinding(
            kind=decl.kind,
            value=decl.value,
            priority=decl.priority,
            label=decl.label,
            matcher_name=decl.matcher_name,
            has_rule=decl.has_rule,
            command=decl.command,
        )
        if binding not in routes.setdefault(decl.capability_id, []):
            routes[decl.capability_id].append(binding)
        if decl.matcher_name:
            _put(
                bucket,
                "handler_ref",
                bucket.get("handler_ref")
                or f"plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py#{decl.matcher_name}",
                decl.capability_id,
            )

    # ③ 受门在册（入站/管理/通知链，无 RouteKind 主表项）。
    for capability_id in _registry.CONTROLLED_INTERNAL_CAPABILITIES:
        _touch(capability_id, CAPABILITY_SOURCE_CONTROLLED)

    # ④ 帮助主题（只认干净能力 id；prose 型能力入口列留在声明源，由常驻门②对照）。
    #    循环变量刻意不复用 `decl`：本函数上文 ② 已把它绑成 RouteCapabilityDecl，
    #    复用同名会让 mypy 在 `topic`/`admin_only` 处判错（真类型缺陷，不是噪声）。
    for help_decl in _registry.HELP_TOPIC_DECLARATIONS:
        capability = help_decl.capability.strip()
        if not re.fullmatch(_CAPABILITY_ID_PATTERN, capability):
            continue
        _touch(capability, CAPABILITY_SOURCE_HELP)
        help_binding = HelpBinding(topic=help_decl.topic, admin_only=help_decl.admin_only)
        if help_binding not in topics.setdefault(capability, []):
            topics[capability].append(help_binding)

    # ⑤ 接口清单联动（interface_id 与能力 id 同形者并入一行）。
    #    同样禁复用 `decl`：② 已把它绑成 RouteCapabilityDecl（真类型缺陷，非噪声）。
    for iface_decl in _registry.INTERFACE_DECLARATIONS:
        if re.fullmatch(_CAPABILITY_ID_PATTERN, iface_decl.interface_id):
            iface_bucket = _touch(iface_decl.interface_id, CAPABILITY_SOURCE_INTERFACE)
            _put(iface_bucket, "interface_id", iface_decl.interface_id, iface_decl.interface_id)

    # gate 列最后统一赋值：口径=迁移前 capability_feature_bindings() 的并集，逐字等价。
    gate_ids = {
        decl.capability_id for decl in _registry.ROUTE_CAPABILITY_DECLARATIONS if decl.has_rule
    } | set(_registry.CONTROLLED_INTERNAL_CAPABILITIES)
    rows: dict[str, CapabilityRegistration] = {}
    for capability_id, origins in sources.items():
        bucket = fields[capability_id]
        if capability_id in gate_ids:
            bucket["gate_feature_id"] = _gate_feature_id(capability_id)
        rows[capability_id] = CapabilityRegistration(
            capability_id=capability_id,
            routes=tuple(routes.get(capability_id, ())),
            help_topics=tuple(topics.get(capability_id, ())),
            authored_by=tuple(origins),
            **bucket,
        )
    return rows


#: 唯一在册表（id → 全部在册事实）。写操作一律拒绝：dict 只读代理。
CAPABILITY_DESCRIPTOR: Mapping[str, CapabilityRegistration] = MappingProxyType(
    _build_capability_descriptor()
)


def gate_feature_bindings() -> dict[str, str]:
    """唯一表 → feature gate 绑定表（与迁移前两表投影结果逐键等价）。"""
    return {
        capability_id: row.gate_feature_id
        for capability_id, row in sorted(CAPABILITY_DESCRIPTOR.items())
        if row.gate_scoped
    }


def gate_route_projection() -> dict[str, tuple[str, str]]:
    """唯一表 → capability_id 的 (route value, label)，供 feature gate 节点取名。

    口径与迁移前 ``feature_catalog`` 的
    ``{item.capability_id: item for item in ROUTE_CAPABILITY_DECLARATIONS if item.has_rule}``
    **逐字等价**：同一 id 多条 rule 行时**后行覆盖前行**（实况唯一受影响者=``bot.moegirl``，
    取 ``MOEGIRL_QUESTION`` 行）。等值由常驻门③锁死，改动此语义必须连带改 feature gate 标签。
    """
    projection: dict[str, tuple[str, str]] = {}
    for row in CAPABILITY_DESCRIPTOR.values():
        for route in row.routes:
            if route.has_rule:
                projection[row.capability_id] = (route.value, route.label)
    return projection


def orchestration_descriptor_rows() -> tuple[CapabilityRegistration, ...]:
    """唯一表中「编排侧已 author」的子集（invoker 通电面，Wave 1/3 消费）。"""
    return tuple(
        row
        for capability_id, row in sorted(CAPABILITY_DESCRIPTOR.items())
        if CAPABILITY_SOURCE_ORCHESTRATION in row.authored_by
    )


def registered_capability_ids() -> frozenset[str]:
    """「能力 X 是否在册」的唯一答案（D-a 判据）。"""
    return frozenset(CAPABILITY_DESCRIPTOR)



__all__ = [
    "CAPABILITY_DESCRIPTOR",
    "CAPABILITY_SOURCE_CONTROLLED",
    "CAPABILITY_SOURCE_HELP",
    "CAPABILITY_SOURCE_INTERFACE",
    "CAPABILITY_SOURCE_ORCHESTRATION",
    "CAPABILITY_SOURCE_ROUTE",
    "DESCRIPTOR_BUILDERS",
    "HONEST_DEGRADE_PREFIX",
    "NINE_SOURCE_IDS",
    "PRESENTATION_DATA_KEY",
    "AuditHookRegistry",
    "CapabilityAuditRecord",
    "CapabilityDescriptor",
    "CapabilityFamily",
    "CapabilityHealth",
    "CapabilityInvoker",
    "CapabilityRegistration",
    "CapabilityRegistry",
    "CapabilityRequest",
    "FallbackRegistry",
    "HandlerRegistry",
    "HealthProbeRegistry",
    "InvocationResult",
    "InvocationStatus",
    "SearchSourceStatus",
    "compute_health",
    "default_invoker",
    "gate_feature_bindings",
    "orchestration_descriptor_rows",
    "registered_capability_ids",
    "search_source_status",
    "validate_registry",
]

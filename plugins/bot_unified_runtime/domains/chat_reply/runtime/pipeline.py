from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import asyncio
import atexit
import hashlib
import inspect
import os
import random
import re
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from plugins.bot_unified_runtime.audit import AuditRepository, redact_private_debug
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    BotDecision,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    OperationalIssue,
    PolicyEvaluation,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    ReviewResult,
    RiskLevel,
    SendPolicy,
    SendRequest,
    SessionType,
)

# 审查 A-19：群聊能力失败降级文案走统一池（user_copy 零依赖常量模块，跨层
# 引用无装配环，先例见该模块头纪律说明）。
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.user_copy import (
    GROUP_FAILURE_ACK_TEMPLATES,
    PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy import (
    InMemoryRateLimiter,
    PolicySettings,
    QuietHoursChecker,
    RateLimiter,
    RedriveSettings,
    ReplyBudgetSettings,
    RoleSettings,
    decide_reply_budget,
    evaluate_policy,
    redrive_wait_seconds,
)

# 耗尽说明面的判据与文案真身都住 rate_limit（补回名册 + 文案池），从模块直读，
# 不经 policy 包转手——不在调用侧抄第二份名册（规则 10）。
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    pick_rate_limit_exhausted_notice,
    rate_limit_exhausted_notice_due,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.event_idempotency import (
    EventIdempotencyTable,
    SqliteEventIdempotencyTable,
    build_event_dedupe_key,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.progress_ack import (
    ProgressAckSettings,
    ProgressAckThrottle,
    build_progress_ack_request,
    effective_ack_delay_seconds,
    normalize_session_type,
    pick_progress_ack_text,
    progress_ack_allowed,
)
from plugins.bot_unified_runtime.domains.ops.features.feature_gate import FeatureAccess
from plugins.bot_unified_runtime.domains.transport.sender import (
    InMemoryReceiptRepository,
    ReceiptRepository,
    SendQueue,
)
from plugins.bot_unified_runtime.output import (
    build_forward_output,
    render_reviewed_output,
    review_capability_result,
    should_forward_by_node_count,
    should_forward_long_text,
)

CapabilityCallable = Callable[[IncomingMessage, BotDecision], CapabilityResult]
AsyncCapabilityCallable = Callable[
    [IncomingMessage, BotDecision], Awaitable[CapabilityResult]
]


# ==================== 聊天专用有界线程池（管线检视 #4） ====================
# 聊天能力是长任务（同步 LLM + ffmpeg 抽帧 + ASR + 串行检索，单条最长 150s）。
# 原先经 asyncio.to_thread 挤占默认线程池（min(32, cpu+4)），与语音转码、kb
# 拉取、订阅适配器共享；突发并发打满后所有 to_thread 任务排队，全站延迟
# 分钟级叠加。现改为管线专用有界池：worker 数与等待队列均有界，超限快败
# 返回 busy 结果而非无限排队；默认线程池完全留给管线外的 to_thread 用户，
# 其 shutdown_default_executor 语义不受影响。

_CHAT_POOL_WORKERS_DEFAULT = 8
_CHAT_POOL_WORKERS_MIN = 1
_CHAT_POOL_WORKERS_MAX = 64
_CHAT_POOL_WORKERS_ENV = "BOT_PIPELINE_MAX_WORKERS"

# ==================== 能力单次执行硬超时（超时改造 C1-a / 在册 M-4） ====================
# 改动前 `offload_capability` 里**没有任何逐任务时限**（M-4 在册位置：
# docs/design/audit-20260920-unify-U4-dispatch.md:168）：能力线程挂死 ⇒ 这一轮永远
#  awaits，既没有回复也没有诊断卡（AGENTS 第四部分「统一错误报告卡」那行的
# 「能力挂死不出卡」正是这一条）。中央 invoker 早就有逐次预算
# （capability_protocols._execute_handler + CapabilityTimeout），但 bot.chat 的根
# 不经过它（pipeline.handle_async 直呼）⇒ 本格把管线侧那一刀补上，超时后**复用同一枚
# CapabilityTimeout**（禁第二族），异常逃逸进 `_internal_error` ⇒ 出卡。
_CHAT_HARD_TIMEOUT_ENV = "BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS"
_REQUEST_BUDGET_ENV = "BOT_REQUEST_BUDGET_SECONDS"
#: 硬超时相对请求预算的最小余量（秒）。判据＝硬超时**必须晚于**内部 deadline 到点：
#: 早于或等于就会砍掉「本来能在预算内正常收尾」的回复（把"挂死出卡"修成"少回一句"
#: 是不可接受的回归）。抬底而不是拒绝启动：一枚 .env 手滑不该把整个 bot 拦在门外。
_HARD_TIMEOUT_OVER_BUDGET_HEADROOM_SECONDS = 60.0
#: 硬超时上限钳位（秒）：与中央 invoker `_MAX_TIMEOUT_SECONDS`（600）同一量级的"别把
#: 挂死等到天荒地老"约束，这里给到 3600 是因为它必须高于请求预算（预算上限 600）
#: 再加一次故障转移窗；超出即钳回，绝不因为一个荒谬的数字把管线钉死。
_CHAT_HARD_TIMEOUT_MAX_SECONDS = 3600.0
#: 解析一次即进程内缓存（与池 worker 数同口径：装配期读定、改 .env 需重启，
#: 刻意不做成"看起来能热改"——已登 settings.py:RESTART_REQUIRED_KEYS）。
_hard_timeout_cache: dict[str, float] = {}
_hard_timeout_cache_lock = threading.Lock()
#: 测试/受控诊断注入的覆盖值（None=走上面的解析链）。生产代码路径永不写它。
_hard_timeout_override: float | None = None


# ==================== 群聊能力失败降级通知（审查 A-19） ====================
# 语义分界（09-12 实弹裁定，不可回退）：限流拦截/安静时间拦截/超载快败
# （pipeline_busy）的静默是故意的降频设计，一律保持不变。本节只处理
# 「能力执行失败」（CapabilityResult 错误态）这一分支——此前群聊失败被压成
# 空正文 + SILENT_AUDIT（审查 A-19 锚点：能力失败群聊路径零反馈），群成员
# @ 了 bot 却得不到任何回应。现改为补一句池内降级文案（user_copy 池轮换），
# 同会话进程内节流防刷屏；私聊不经此路径（chat 私聊失败已有人格话术池）。
# 错误细节绝不回群（脱敏红线）：失败结果本身仍压成空正文静默审计，细节走
# 既有管理员告警链/统一错误报告卡。
_GROUP_FAILURE_NOTICE_WINDOW_SECONDS = 300.0
# 节流表容量上限：写满时先清过期项，仍满则整表重置——会话数有界防内存缓涨。
_GROUP_FAILURE_NOTICE_TRACK_CAP = 512

# ==================== 限流补回终局的耗尽说明（2026-09-29 需求项 2 之 1） ====================
# 补回把被拦的那句重放到尽头仍没回上时，对「欠一句回复」的请求补一句说明，
# 不再纯静默（「每一条最终都必须被回，不许静默吞」的收口）。文案池与判据真身
# 都住 policy/rate_limit；这里只定每会话冷却：连撞耗尽也只说一句，防刷屏。
_RATE_LIMIT_EXHAUSTED_NOTICE_COOLDOWN_SECONDS = 60.0

# 需求项 6（2026-09-29）：本轮「回执已出口」账本的存活窗与容量上限。
# TTL 取单轮最坏耗时量级（真回复/失败都在此窗内落回 `_complete`）；超时即清，
# 绝不让一条旧回执把很久之后的另一轮失败误判成「已开过口」。
_ACK_EMITTED_MARK_TTL_SECONDS = 300.0
_ACK_EMITTED_MARK_CAP = 512


class _BoundedSubmissionGate:
    """有界提交闸：在途（运行+排队）超过许可数时 try_acquire 立即失败。

    只用 threading.Lock 计数，不引入事件循环绑定原语（跨 loop 与测试安全），
    提交路径 O(1) 非阻塞。许可数 = worker 数 + 等待队列深度，即 ThreadPool
    内部队列之外的第二道、也是唯一一道有界闸。

    ## S134·B（裁定 3 项 B / CM-P-40 R2）：跨族**不共计数器**
    改动前只有一枚 `_in_flight`，全部能力共用 ⇒ 任一族（含视觉）占满 2N 格，
    另一族（含语音）就在 `pipeline_busy` 上被**静默否决**——前值实测：
    permits=16 时视觉连取 16 格、语音随后连取 4 格成功数 = 0。

    现在分两层，两层各自独立计数：
     - **通用层** `permits`（＝2N，语义与旧版逐字相同）：所有能力共用的额度；
     - **保留层** `reserved_permits` × 每一枚在册族：**每族自己的一格计数器**，
       别的族既看不见也拿不走 ⇒ 通用层被别族打满时，本族仍可再取保留层，
       "一票否决"缩成"保留位之外才否决"。

    族身份**不在此处复制**：唯一真身是
    ``domains/core/capability_resource_ownership.FAMILY_MEMBERS``（S85 的族册），
    本件按 capability_id 现算族名，族册改了这里自动跟随（第二真身＝门红）。
    总在途上界＝`permits + reserved_permits × 族数`，仍然有界（不会无界增长）。
    """

    __slots__ = (
        "_general_in_flight",
        "_in_flight_total",
        "_lock",
        "_permits",
        "_reserved_in_flight",
        "_reserved_permits",
        "_reserved_scopes",
    )

    def __init__(
        self,
        permits: int,
        *,
        reserved_permits: int = 0,
        reserved_scopes: tuple[str, ...] = (),
    ) -> None:
        self._lock = threading.Lock()
        self._permits = max(1, int(permits))
        self._reserved_permits = max(0, int(reserved_permits))
        self._reserved_scopes = frozenset(
            str(scope) for scope in reserved_scopes if str(scope).strip()
        )
        self._general_in_flight = 0
        self._reserved_in_flight: dict[str, int] = {
            scope: 0 for scope in self._reserved_scopes
        }
        self._in_flight_total = 0

    def try_acquire(self, scope: str = "") -> bool:
        """取一格额度。`scope`＝资源族（族册 `family_of` 的结果，族外传空串）。
    
        取序**先通用后保留**（保留层是"别人打满时的活路"，不是日常通道）。
        """
        with self._lock:
            if self._general_in_flight < self._permits:
                self._general_in_flight += 1
                self._in_flight_total += 1
                return True
            key = str(scope or "")
            if key in self._reserved_in_flight and self._reserved_in_flight[key] < self._reserved_permits:
                self._reserved_in_flight[key] += 1
                self._in_flight_total += 1
                return True
            return False

    def release(self, scope: str = "") -> None:
        """还一格。tier 归属按"该族保留层还占着就先还保留层"结算：
        总数恒精确，只有极端并发下 tier 记账可能偏保守（少还保留层＝少给
        该族一次活路），不会漏还、也不会超发。"""
        key = str(scope or "")
        with self._lock:
            self._in_flight_total = max(0, self._in_flight_total - 1)
            if key in self._reserved_in_flight and self._reserved_in_flight[key] > 0:
                self._reserved_in_flight[key] -= 1
                return
            if self._general_in_flight > 0:
                self._general_in_flight -= 1

    @property
    def permits(self) -> int:
        return self._permits

    @property
    def reserved_permits(self) -> int:
        return self._reserved_permits

    @property
    def reserved_scopes(self) -> frozenset[str]:
        return self._reserved_scopes

    @property
    def in_flight(self) -> int:
        """当前在途总数（通用层 + 各族保留层）；测试与诊断用。"""
        with self._lock:
            return self._in_flight_total

    def scope_in_flight(self, scope: str) -> int:
        """某族**保留层**的占用数（跨族互不可见的那一格）；诊断用。"""
        with self._lock:
            return int(self._reserved_in_flight.get(str(scope or ""), 0))

    def general_in_flight(self) -> int:
        with self._lock:
            return self._general_in_flight


_chat_pool_lock = threading.Lock()
_chat_pool: ThreadPoolExecutor | None = None
_chat_pool_gate: _BoundedSubmissionGate | None = None


def _resolve_chat_pool_workers() -> int:
    """worker 数解析链：nonebot driver config → os.environ → 默认 8，钳位 1..64。

    与 llm/channel_health.py 的 config→env→默认同源模式。pipeline 不接收
    注入 config（构造方在插件 __init__，不在本任务文件域），故经惰性
    get_driver 读取；未初始化（单元测试/裸脚本）时自动短路。仅在池首次
    创建时读取一次，运行中改配置需重启（与 .env 注册表语义一致）。
    """
    raw_values: list[object] = []
    try:
        import nonebot

        driver_config = nonebot.get_driver().config
        raw_values.append(getattr(driver_config, "bot_pipeline_max_workers", None))
    except Exception:  # noqa: BLE001, S110 - 单元测试/独立脚本场景，静默落到下一级。
        pass
    raw_values.append(os.environ.get(_CHAT_POOL_WORKERS_ENV))
    for raw in raw_values:
        if raw is None:
            continue
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        return max(_CHAT_POOL_WORKERS_MIN, min(_CHAT_POOL_WORKERS_MAX, value))
    return _CHAT_POOL_WORKERS_DEFAULT


def _config_field_default(field_name: str) -> float | None:
    """Config 字段的**声明默认值**（唯一出处）。

    本模块刻意不在这里抄第二份数字（规则 10：随代码漂移的值以真身定义处为准）——
    硬超时与请求预算的缺省只有 `config.py` 一处真身，读不到就退「不参与抬底」语义。
    config.py 零包内依赖 ⇒ 这里局部 import 不成环。
    """
    try:
        from plugins.bot_unified_runtime.config import Config

        info = Config.model_fields.get(field_name)
        default = getattr(info, "default", None)
        if default is None or isinstance(default, bool):
            return None
        return float(default)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - 配置模型不可用时交调用方兜底。
        return None


def _first_positive_float(raw_values: list[object]) -> float | None:
    """取第一个能解析成正浮点的原始值（None/非法形态逐级跳过，不抛）。"""
    for raw in raw_values:
        if raw is None:
            continue
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _driver_then_env(field_name: str, env_name: str) -> list[object]:
    """解析链前两级：nonebot driver config → os.environ（同 `_resolve_chat_pool_workers`）。"""
    raw_values: list[object] = []
    try:
        import nonebot

        raw_values.append(
            getattr(nonebot.get_driver().config, field_name, None)
        )
    except Exception:  # noqa: BLE001, S110 - 单元测试/独立脚本场景，静默落到下一级。
        pass
    raw_values.append(os.environ.get(env_name))
    return raw_values


def _driver_and_env_raw(
    read_driver_attr: Callable[[Any], object], env_name: str
) -> list[object]:
    """解析链前两级：nonebot driver config → os.environ（同 `_resolve_chat_pool_workers`）。

    字段名**必须由调用点以字面 getattr 形态给出**（而不是把名字当参数传进来再 getattr）：
    配置键的活性证据由 `scripts/config_read_point_census` 按字面读点现算，形如
    `getattr(config, field_name, …)` 的转名写法结构上看不见这一枚键 ⇒ 会被记成
    「只字面在场、不保证活性」。这里刻意留字面读点，让"这枚键真被读到"可机器复核。
    """
    raw_values: list[object] = []
    try:
        import nonebot

        raw_values.append(read_driver_attr(nonebot.get_driver().config))
    except Exception:  # noqa: BLE001, S110 - 单元测试/独立脚本场景，静默落到下一级。
        pass
    raw_values.append(os.environ.get(env_name))
    return raw_values


def _resolve_request_budget_seconds() -> float | None:
    """请求级总预算（只为「硬超时不得抢跑内部 deadline」这一抬底判据取值）。

    读不到返回 None ⇒ 本轮不设地板：宁可不抬，也不在这里凭记忆造第二个缺省值。
    """
    raw_values = _driver_and_env_raw(
        lambda driver_config: getattr(driver_config, "bot_request_budget_seconds", None),
        _REQUEST_BUDGET_ENV,
    )
    raw_values.append(_config_field_default("bot_request_budget_seconds"))
    return _first_positive_float(raw_values)


def _resolve_capability_hard_timeout_seconds() -> float:
    """硬超时解析链：driver config → env → Config 声明默认 → 上限钳位 → 按请求预算抬底。"""
    raw_values = _driver_and_env_raw(
        lambda driver_config: getattr(
            driver_config, "bot_pipeline_capability_hard_timeout_seconds", None
        ),
        _CHAT_HARD_TIMEOUT_ENV,
    )
    raw_values.append(
        _config_field_default("bot_pipeline_capability_hard_timeout_seconds")
    )
    configured = _first_positive_float(raw_values)
    if configured is None:
        # 全链都读不出正数（畸形 .env + 配置模型不可用）：能力执行回到"无硬超时"的
        # 旧形态而不是"0 秒即判挂死"——后者会把每一条聊天都变成异常卡，属新增故障。
        logger.warning(
            "pipeline capability hard timeout unreadable from config/env/defaults; "
            "falling back to %s seconds",
            float(_CHAT_HARD_TIMEOUT_MAX_SECONDS),
        )
        configured = _CHAT_HARD_TIMEOUT_MAX_SECONDS
    configured = min(configured, _CHAT_HARD_TIMEOUT_MAX_SECONDS)

    budget = _resolve_request_budget_seconds()
    if budget is None:
        return configured
    floor = budget + _HARD_TIMEOUT_OVER_BUDGET_HEADROOM_SECONDS
    if configured < floor:
        logger.warning(
            "pipeline capability hard timeout %.1fs is not safely above request budget "
            "%.1fs (headroom %.1fs) ⇒ raised to %.1fs: 外部闸不得抢在内部 deadline 之前砍掉回复",
            configured,
            budget,
            _HARD_TIMEOUT_OVER_BUDGET_HEADROOM_SECONDS,
            min(floor, _CHAT_HARD_TIMEOUT_MAX_SECONDS),
        )
        return min(floor, _CHAT_HARD_TIMEOUT_MAX_SECONDS)
    return configured


def set_capability_hard_timeout_seconds(value: float | None) -> None:
    """设定/清除硬超时覆盖并作废缓存（None=恢复解析链）。

    仅供测试与受控诊断注入：生产热路径仍按解析链 + 进程内缓存走，一次都不碰这里。
    """
    global _hard_timeout_override
    with _hard_timeout_cache_lock:
        _hard_timeout_override = None if value is None else max(0.001, float(value))
        _hard_timeout_cache.clear()


def capability_hard_timeout_seconds() -> float:
    """当前生效的管线能力硬超时秒数（解析一次即缓存；override 在场时每次现算）。"""
    with _hard_timeout_cache_lock:
        override = _hard_timeout_override
        if override is not None:
            return override
        cached = _hard_timeout_cache.get("seconds")
    if cached is not None:
        return cached
    resolved = _resolve_capability_hard_timeout_seconds()
    with _hard_timeout_cache_lock:
        _hard_timeout_cache["seconds"] = resolved
    return resolved


def _capability_timeout_error(capability_id: str, timeout_seconds: float) -> Exception:
    """超时的异常身份：复用中央 invoker 那枚 `CapabilityTimeout`（禁第二族）。

    它的存在理由就写在自己的 docstring 里——让「能力挂死」与「能力抛异常」共用同
    一条诊断卡路径。这里刻意**局部 import**：本模块与 runtime 层互有引用面，热路径
    不新增导入边；导入失败退 `TimeoutError`——出卡判据只看「有异常逃逸到
    `_internal_error`」，族名不是承重件（但绝不静默返回结果，那正是原缺陷）。
    """
    detail = (
        f"{capability_id or 'unknown'} 超过管线硬超时 {timeout_seconds:g}s"
        "（工作线程仍在跑，结果弃用）"
    )
    try:
        from plugins.bot_unified_runtime.runtime.capability_protocols import (
            CapabilityTimeout,
        )

        return CapabilityTimeout(detail)
    except Exception:  # 取族失败仍要抛异常，绝不退回"静默无结果"。
        logger.debug(
            "CapabilityTimeout unavailable; raising TimeoutError instead", exc_info=True
        )
        return TimeoutError(detail)


def _retire_offloaded_task(task: Any, release: Callable[[], None]) -> None:
    """被弃用/已完成执行体的收尾：还闸位 + 取走异常。

    task 未真退出（线程仍在跑，Python 线程不可中断）⇒ 闸位**延后**到线程真退出才还。
    闸表示的是「这枚 worker 还占着」，提前还会把有界池写成无界队列：挂死风暴时
    排队无上限，那是比"这一轮白等"更坏的故障形态。异常必须取走一次，否则 asyncio
    会打「exception was never retrieved」的噪声日志（挂死任务迟早会抛出来）。
    """

    def _finish(_fut: Any = None) -> None:
        release()
        try:
            if not task.cancelled():
                task.exception()
        except BaseException as exc:  # noqa: BLE001 - 收尾探测没有调用方可接，绝不外抛（留痕而不 pass）。
            logger.debug(
                "offloaded task exception probe failed type=%s", type(exc).__name__
            )

    try:
        if task.done():
            _finish()
            return
        task.add_done_callback(_finish)
    except BaseException:  # 回调挂上失败也不能漏还闸位（漏还＝池被钉死成永久 busy）。
        logger.debug("offloaded task retire hook failed", exc_info=True)
        release()


def _shutdown_chat_pool() -> None:
    """模块级关闭钩子：未启动的排队提交取消，已在跑的任务不等待。"""
    global _chat_pool, _chat_pool_gate
    with _chat_pool_lock:
        pool, _chat_pool, _chat_pool_gate = _chat_pool, None, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


#: 每族保留位 = worker 数的一半（至少 1 格，且不超过 worker 数本身）。
#: 依据：保留层的用途是"通用层被别族打满时本族仍有活路"，不是日常主通道；
#: 取 N/2 使最坏总在途 = 2N + (N/2)×族数，仍可界（N=8、两族 ⇒ 24）。
def _reserved_permits_for(workers: int) -> int:
    return max(1, min(int(workers), int(workers) // 2 or 1))


def inflight_scope_of(capability_id: Any) -> str:
    """某枚能力在途闸上算哪一族（族外一律空串＝只走通用层）。

    族籍唯一真身＝``domains/core/capability_resource_ownership.FAMILY_MEMBERS``；
    本件**不**复制第二份名单。读不到册（极端导入环/测试桩）时退化为空串＝
    fail-closed 到通用层，绝不因为"取不到族"而给谁开后门。
    """
    try:
        from plugins.bot_unified_runtime.domains.core import (
            capability_resource_ownership as _ownership,
        )

        return _ownership.family_of(str(capability_id or ""))
    except Exception:  # noqa: BLE001 - 取族失败＝族外，走通用层，绝不抛
        return ""


def _get_chat_pool() -> tuple[ThreadPoolExecutor, _BoundedSubmissionGate]:
    """懒创建管线专用池：worker N（config/env/默认 8），在途上限 2N（N 跑 + N 等）。

    S134·B：闸构造时带上"每族各自的保留位"，保留层计数器跨族不共。
    """
    global _chat_pool, _chat_pool_gate
    pool, gate = _chat_pool, _chat_pool_gate
    if pool is not None and gate is not None:
        return pool, gate
    with _chat_pool_lock:
        if _chat_pool is None or _chat_pool_gate is None:
            workers = _resolve_chat_pool_workers()
            _chat_pool = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="chat-pipeline",
            )
            atexit.register(_shutdown_chat_pool)
            _chat_pool_gate = _BoundedSubmissionGate(
                workers * 2,
                reserved_permits=_reserved_permits_for(workers),
                reserved_scopes=_reserved_scopes(),
            )
        return _chat_pool, _chat_pool_gate


def _reserved_scopes() -> tuple[str, ...]:
    """在册族名（保留层的键集合），现算自族册；族册涨一族这里自动多一格。"""
    try:
        from plugins.bot_unified_runtime.domains.core import (
            capability_resource_ownership as _ownership,
        )

        return tuple(sorted(_ownership.FAMILY_MEMBERS))
    except Exception:  # noqa: BLE001 - 取不到册＝本轮不设保留层（旧形态）
        return ()



def _pipeline_busy_result(
    message: IncomingMessage,
    decision: BotDecision,
) -> CapabilityResult:
    """超限快败结果（在途占满，本轮不排队、立即返回）。

    会话面分两档（超时改造 C1-d，2026-09-28 用户裁定「绝不让用户零反馈」）：
    - **群/频道**：SILENT_AUDIT 只留审计痕、不外发话术——超载时不放大流量是
      09-12 实弹成文裁定（`test_a19_group_failure_notice.py::test_group_pipeline_busy_stays_silent`
      锁着），本档一字未动。
    - **私聊**：**必须说话**。此前私聊与群聊同享静默，用户明确找 bot 说话却被
      在途闸静默否决、一个字都收不到（现网判据：`SendPolicy.SILENT_AUDIT` ⇒
      `_complete` 直落 SKIPPED 回执、零出站）。本档补一句池内短句
      （user_copy.PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES 轮换，守岸人语气）。
    私聊不会因此刷屏：能走到这一格的前提是「在途已占满 2N」，同一私聊会话要连续
    撞闸得先连续并发；而"这条被挤掉了、再发一次"正是用户需要知道的 facts。
    错误细节（池容量/队列深度/能力名）一律不外传，只留审计与告警链。
    """
    speaks_privately = message.session_type is SessionType.PRIVATE
    return CapabilityResult(
        request_id=message.request_id,
        capability_id=decision.capability_id,
        kind="error",
        title="",
        summary="",
        body=(
            random.choice(PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES)
            if speaks_privately
            else ""
        ),
        send_policy=(
            SendPolicy.IMMEDIATE if speaks_privately else SendPolicy.SILENT_AUDIT
        ),
        audit_tags=["pipeline_busy:v1"],
        operational_issue=OperationalIssue(
            stage="runtime",
            kind="pipeline_busy",
            retryable=True,
            debug_id=message.debug_id,
            safe_summary="pipeline_busy",
        ),
    )


def offload_capability(capability: CapabilityCallable) -> AsyncCapabilityCallable:
    async def wrapped(
        message: IncomingMessage,
        decision: BotDecision,
    ) -> CapabilityResult:
        pool, gate = _get_chat_pool()
        # S134·B：取/还必须同 scope（族），故一次算好复用；族外为空串＝只用通用层。
        scope = inflight_scope_of(getattr(decision, "capability_id", ""))
        if not gate.try_acquire(scope):
            return _pipeline_busy_result(message, decision)
        released = threading.Event()

        def _release() -> None:
            if not released.is_set():
                released.set()
                gate.release(scope)

        try:
            loop = asyncio.get_running_loop()
            task = loop.run_in_executor(pool, capability, message, decision)
        except BaseException:
            # 连提交都没成功（池已关闭等）：闸位当场归还，异常照旧向外走。
            _release()
            raise
        timeout_seconds = capability_hard_timeout_seconds()
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task), timeout=timeout_seconds
            )
        except TimeoutError as exc:
            # C1-a（M-4 关账）：到点不再"白等"。shield 让超时不牵连真实任务，
            # 闸位按 worker 真实占用归还（见 _retire_offloaded_task），抛
            # CapabilityTimeout ⇒ handle_async 的 except → _internal_error →
            # _maybe_send_error_card：挂死第一次有了可见面。
            _retire_offloaded_task(task, _release)
            raise _capability_timeout_error(
                str(getattr(decision, "capability_id", "") or ""), timeout_seconds
            ) from exc
        except BaseException:
            # 取消/能力异常同口径：任务已真退出就立即还，没退出就等它退出再还。
            _retire_offloaded_task(task, _release)
            raise
        _retire_offloaded_task(task, _release)
        return result

    return wrapped


# ==================== 下放决定的收口（X4，2026-10-01） ====================
# 改动前的形状：根汇口按一张「可下放名单」（`__init__.OFFLOADED_CAPABILITY_IDS`）
# 决定这一轮走 `handle_async`（正文下放线程池）还是走 `handle`（正文与完成腿都在
# 事件循环线程上直呼）。名单外的一枚命令只要正文里有阻塞件（SQLite / 文件 /
# subprocess / Playwright），冻住的就不是那一条命令，而是**整片会话**——低频管理
# 命令拖死全站，事故级。现网按号可点的例子：`/bot recent`（三份 SQLite 反查）、
# `/bot queue`（发信队列 SQLite 读）、`/bot logs`（运行日志读）、`/bot runtime`
# 管理面（热改态文件 os.replace 落盘）、`/bot setup llm`（引导卡渲染）——
# 这些都不在名单上，全都在 loop 线程上同步跑完。
#
# 本段把「要不要下放」从**名单决定**改成**能力正文自己决定**：只有本身就是协程的
# callable 留在循环上（那是它唯一不占循环的形态），其余一律经 `offload_capability`
# 进管线专用有界池。名单由此退役成观测面——它对执行路径不再有决定权（判据锁
# `tests/test_pipeline_offload_always.py`，含合成注毒自证腿）。
#
# 刻意**不**下放完成腿 `_complete`：`SendQueue.submit` 的认领台账按 `current_task()`
# 记账，把它搬进线程会静默吃掉登记（A-22 在册坑，`queue.py` 自述「线程提交不登记」）。
# 下放面只有「能力正文」这一层，投递几何/幂等认领序/超时抛法一律不动。


def is_native_async_callable(capability: object) -> bool:
    """能力正文是否**本身就是协程**（协程函数 / async 偏函数 / async ``__call__``）。

    判据用「是不是协程」而不是「在不在名单上」：协程正文是唯一不会占住循环的形态，
    其余（`def capability(...)` 同步闭包）一律视为潜在阻塞件。
    `inspect.iscoroutinefunction` 认函数与 `functools.partial`，但**不**认带
    `async def __call__` 的可调用对象（3.14 起只认前者）⇒ 这里补一格 `__call__`，
    免得把异步能力误判成同步正文而多包一层。
    """
    if inspect.iscoroutinefunction(capability):
        return True
    # B004 不适用：这里不是"测 x 能不能调"（那才该用 `callable(x)`），而是取**类型上的
    # `__call__` 描述符本身**去看它是不是协程函数——`callable()` 只给布尔值，拿不到
    # 描述符，换过去就判不了 `async def __call__` 那一形。
    call = getattr(type(capability), "__call__", None)  # noqa: B004
    return call is not None and call is not capability and inspect.iscoroutinefunction(call)


def ensure_offloaded(
    capability: Callable[..., Any],
) -> AsyncCapabilityCallable:
    """同步正文无条件下放线程池；已是协程的原样返回（逐字节现状）。

    幂等且**绝不二次包装**：`offload_capability` 的产物是协程函数，第二次进来在
    第一行短路 ⇒ 有界闸的许可只占一格（包两层会各占一格，把池容量悄悄砍半）。
    这里只认唯一一具下放机器 `offload_capability`，不长第二份线程池通路。
    """
    if is_native_async_callable(capability):
        return cast(AsyncCapabilityCallable, capability)
    return offload_capability(cast(CapabilityCallable, capability))


# 同步直呼腿的可见面（不哑兜底）：`handle` 在事件循环线程上被调用＝正文与完成腿
# 都要占住循环，这正是 X4 要消灭的形状。生产不该再出现，但出现了必须留痕。
_LOOP_THREAD_SYNC_REPORT_CAP = 128
_loop_thread_sync_reported: set[str] = set()
_loop_thread_sync_report_lock = threading.Lock()


def _report_loop_thread_sync_call(capability_id: str) -> None:
    """调用点落在事件循环线程上 ⇒ 按 capability_id 记一次 WARNING（有界、fail-open）。

    非循环线程（console / smoke / 脚本 / 测试）第一行就返回 ⇒ 零额外动作、零噪声，
    既有同步用法逐字节现状。记账只用于去重，容量满就不再新增（宁少报不涨内存）。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    key = str(capability_id or "")
    with _loop_thread_sync_report_lock:
        if key in _loop_thread_sync_reported:
            return
        if len(_loop_thread_sync_reported) >= _LOOP_THREAD_SYNC_REPORT_CAP:
            return
        _loop_thread_sync_reported.add(key)
    logger.warning(
        "pipeline.handle ran a capability body on the event-loop thread "
        "capability_id=%s（同步直呼会冻住整片会话；应改走 handle_async 的下放形态）",
        key,
    )


RUNTIME_CONTROL_BYPASS_CAPABILITY_IDS = {
    "bot.status",
    "bot.help",
    "bot.why",
    "bot.receipt",
    "bot.audit",
    "bot.recent",
    "bot.queue",
    "bot.context",
    "bot.llm",
    "bot.setup.llm",
    "bot.config",
    "bot.readiness",
    "bot.dialogue",
    "bot.roles",
    "bot.history",
    "bot.control",
}


@dataclass
class RuntimeControlState:
    paused: bool = False
    reason: str = "running"
    updated_by_state: str = "missing"

    def pause(self, *, actor_id: str = "", reason: str = "manual_pause") -> None:
        self.paused = True
        self.reason = reason
        self.updated_by_state = "set" if actor_id else "missing"

    def resume(self, *, actor_id: str = "", reason: str = "manual_resume") -> None:
        self.paused = False
        self.reason = reason
        self.updated_by_state = "set" if actor_id else "missing"

    def allows(self, capability_id: str) -> bool:
        return not self.paused or capability_id in RUNTIME_CONTROL_BYPASS_CAPABILITY_IDS


@dataclass(frozen=True)
class _PreparedRuntime:
    message: IncomingMessage
    decision: BotDecision
    policy: PolicyEvaluation
    # 审查 A-18：能力异常回滚限流记账所需的最小现场——reason 决定回滚哪些
    # 桶（bypass/拦截类零记账，回滚自会空转），amount 与 check_and_record
    # 收到的 safe_amount 一致（budget 0=不限 在限流器内按 1 记账）。
    rate_limit_reason: str = "allowed"
    rate_limit_amount: int = 1


def _resolve_persona_profile_id(
    decision: BotDecision,
    result: CapabilityResult,
) -> str:
    for tag in result.audit_tags:
        if tag.startswith("persona:"):
            persona_id = tag.removeprefix("persona:").strip()
            if persona_id:
                return persona_id
    return decision.persona_profile_id


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result


# S-08/Wave H 摘要层 S4（T107 蓝图 §3.2/§3.3，T123 施工）：出站键内容维度。
# 规约=dedupe_key=消息身份 ∧ 段类型 ∧ content_sha256：d 段只由 mixed parts 里
# 的 record 部件参与，对「部件 digest 截短[:16] 有序拼接」再 sha256[:16]
# （多部件防拼接歧义）；digest 全长 64 hex 由渲染收口（renderer
# canonicalize_audio_parts）冻结，此处只做防御性复核。
_CONTENT_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


def _content_dedupe_suffix(rendered: RenderedOutput) -> str:
    """出站键 d 段（摘要层 S4）：``:d=<16hex>`` 或空串（缺省退化）。

    兼容性根（蓝图 §3.2 明文）：无 record 部件、或任一 record 部件缺/坏
    ``content_sha256`` 的请求 → 返回空串，dedupe_key 与旧三元组**逐字节一致**。
    缺 digest 一律整段缺省、绝不伪造（空串/占位均禁）——「无 digest 的键不变」
    与「有 digest 的键含 d 段」构成互斥双锁。music/file 族无 digest 是设计事实
    （无本地字节），非「缺 digest」，不参与也不阻断 d 段。
    """
    parts = rendered.content_ref.get("parts")
    if not isinstance(parts, list):
        return ""
    digests: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if str(part.get("type") or "record").strip().lower() != "record":
            continue
        value = part.get("content_sha256")
        if not (isinstance(value, str) and _CONTENT_DIGEST_RE.fullmatch(value)):
            return ""
        digests.append(value)
    if not digests:
        return ""
    joined = "".join(digest[:16] for digest in digests)
    short = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
    return f":d={short}"


def _looks_like_review_reason(review: ReviewResult, marker: str) -> bool:
    normalized_marker = marker.lower()
    return any(normalized_marker in reason.lower() for reason in review.reasons)


def _persona_display_name(result: CapabilityResult) -> str:
    title = result.title.strip()
    suffix = "的回复"
    if title.endswith(suffix):
        name = title[: -len(suffix)].strip()
        if name:
            return name
    return "已设定的人格"


def _review_block_public_message(
    result: CapabilityResult,
    review: ReviewResult,
) -> str:
    if _looks_like_review_reason(review, "unsafe output leakage"):
        return "输出未通过安全或隐私检查。"
    if _looks_like_review_reason(review, "persona drift"):
        persona_name = _persona_display_name(result)
        return (
            "我刚刚没有把话说稳。"
            f"让我回到{persona_name}的位置上："
            "你可以把问题再说一遍，我会按既定人格、记忆和知识库重新回答。"
        )
    return "输出未通过安全或隐私检查。"


def _observe_decision_shadow(message: IncomingMessage, capability_id: str) -> None:
    """B2 阶段 0 影子挂钩：shadow 模式下引擎只算 plan 写 decision_trace。

    绝不发送、绝不改回执、绝不 claim 幂等；``legacy_only``（默认）时仅
    一次模式解析即返回。全链 fail-open：影子观测的任何异常只降级为不观测，
    绝不影响主链路。
    """
    try:
        from plugins.bot_unified_runtime.domains.core.decision.shadow import (
            is_shadow_active,
            observe_pipeline_event,
        )

        if is_shadow_active():
            observe_pipeline_event(message, capability_id)
    except Exception:  # noqa: BLE001 - 影子观测是旁路，任何异常只降级为不观测。
        return


class RuntimePipeline:
    def __init__(
        self,
        send_queue: SendQueue,
        audit_logger: AuditRepository,
        reply_budget_settings: ReplyBudgetSettings | None = None,
        role_settings: RoleSettings | None = None,
        group_command_prefix: str = "/bot",
        runtime_enabled: bool = True,
        receipt_repository: ReceiptRepository | None = None,
        rate_limiter: RateLimiter | None = None,
        quiet_hours_checker: QuietHoursChecker | None = None,
        runtime_control: RuntimeControlState | None = None,
        forward_min_chars: int = 1500,
        forward_max_nodes: int = 0,
        forward_node_chars: int = 900,
        forward_min_nodes: int = 4,
        forward_sender_name: str = "",
        alias_command_check: Callable[[str], bool] | None = None,
        group_auto_reply_enabled: bool = False,
        group_auto_reply_probability: float | Callable[[], float] = 0.0,
        vision_reply_probability: float = 1.0,
        group_black1: frozenset[str] = frozenset(),
        group_black2: frozenset[str] = frozenset(),
        group_white1: frozenset[str] = frozenset(),
        group_white2: frozenset[str] = frozenset(),
        listen_only_bot_ids: frozenset[str] = frozenset(),
        natural_chat_check: Callable[[str], bool] | None = None,
        mention_terms: tuple[str, ...] = (),
        group_lists_provider: Callable[[], dict[str, frozenset[str]]] | None = None,
        idempotency_table: EventIdempotencyTable | SqliteEventIdempotencyTable | None = None,
        feature_gate: Callable[[IncomingMessage, str], FeatureAccess] | None = None,
        # G-3（M-10/M-13）：配音出站 post-review hook（T54 规格 §4.2 冻结接口）。
        # 缺省 None=零调用（键关部署逐字节现状）；键开由根装配注入
        # domains/media/voice_enricher 产物，在 _complete 的 review 批准后、
        # render 前恰调一次（阻塞 HTTP 合成经 handle_async 线程池化，不占事件循环）。
        outbound_voice_enricher: Callable[
            [IncomingMessage, BotDecision, CapabilityResult], CapabilityResult
        ]
        | None = None,
        # 慢回复先回执（ack-first）：阈值到点仍未出结果时，先落一句短的。
        # 缺省 None=零调用（键关部署现状不变）；由根装配注入配置与投递口，
        # 投递必须走主动投递唯一中央出口，不在这里直调 send_queue.submit。
        progress_ack_settings: ProgressAckSettings | None = None,
        progress_ack_submit: Callable[[Any], Any] | None = None,
        # 网关当下有多慢（单跳 EWMA 毫秒，取链上最慢一跳）。缺省 None=不自适应，
        # 逐字节回到固定 delay_seconds。读数由根装配注入（健康库在别处记账，
        # 这里只消费），本模块绝不自己去开 SQLite——那会长出第二本延迟账。
        progress_ack_latency_probe: Callable[[], float | None] | None = None,
        # 被限流拦下的明确请求「期后补回」的参数；None=不补（旧行为逐字节保持）。
        redrive_settings: RedriveSettings | None = None,
    ) -> None:
        self.feature_gate = feature_gate
        self.outbound_voice_enricher = outbound_voice_enricher
        self.progress_ack_settings = progress_ack_settings
        self.progress_ack_submit = progress_ack_submit
        self.progress_ack_latency_probe = progress_ack_latency_probe
        self.redrive_settings = redrive_settings
        # 在飞的补回任务必须持有强引用，否则 create_task 的返回值被丢弃后
        # 任务可能在跑完前被 GC 回收（asyncio 只存弱引用）。
        self._redrive_tasks: set[Any] = set()
        # 需求项 6（2026-09-29）：本轮回执**真发出去了**的 request_id 记账。
        # 用途只有一个——「阈值后才失败 ⇒ 回执+兜底文案连发两条」的叠加治理：
        # `_complete` 见失败结果时先查这枚账，同轮已开过口就不再补第二句。
        # 有界：TTL + 条数上限双闸（形态照抄群失败节流表，fail-open）。
        self._ack_emitted_at: dict[str, float] = {}
        self._ack_emitted_lock = threading.Lock()
        self._progress_ack_throttle = ProgressAckThrottle(
            cooldown_seconds=float(
                getattr(progress_ack_settings, "cooldown_seconds", 60.0) or 60.0
            )
        )
        # 耗尽说明的每会话节流（形态照回执节流器：查占同锁、投递失败 release 退还，
        # 不让一次瞬时失败吃掉同会话下一句说明的坑）。
        self._rate_limit_notice_throttle = ProgressAckThrottle(
            cooldown_seconds=_RATE_LIMIT_EXHAUSTED_NOTICE_COOLDOWN_SECONDS
        )
        self.send_queue = send_queue
        self.audit_logger = audit_logger
        self.receipt_repository = receipt_repository or InMemoryReceiptRepository()
        self.runtime_enabled = runtime_enabled
        self.runtime_control = runtime_control or RuntimeControlState()
        self.rate_limiter = rate_limiter or InMemoryRateLimiter()
        self.quiet_hours_checker = quiet_hours_checker or QuietHoursChecker()
        # 0=禁用按字数的合并转发（短消息与已分段回复都直接发送）。
        self.forward_min_chars = int(forward_min_chars)
        self.forward_max_nodes = max(0, int(forward_max_nodes))
        self.forward_node_chars = max(200, int(forward_node_chars))
        # 按条数触发合并转发：切分后 >= forward_min_nodes 条才合并
        # （用户口径"超过 3 条就合并"→ 4）。0/负数 = 关闭该规则。
        self.forward_min_nodes = max(0, int(forward_min_nodes))
        # 合并转发节点里署谁的名字：用户要求"转发内发送的用户仍为 bot 自己"。
        self.forward_sender_name = str(forward_sender_name or "").strip()
        policy_settings = PolicySettings(
            group_command_prefix=group_command_prefix,
            group_auto_reply_enabled=group_auto_reply_enabled,
            group_auto_reply_probability=group_auto_reply_probability,
            vision_reply_probability=vision_reply_probability,
            group_black1=frozenset(group_black1),
            group_black2=frozenset(group_black2),
            group_white1=frozenset(group_white1),
            group_white2=frozenset(group_white2),
            listen_only_bot_ids=frozenset(listen_only_bot_ids),
            mention_terms=tuple(mention_terms),
            natural_chat_check=natural_chat_check,
            group_lists_provider=group_lists_provider,
            extra_command_check=alias_command_check,
        )
        self.policy_evaluator = (
            lambda message, capability_id: evaluate_policy(
                message,
                capability_id,
                settings=policy_settings,
            )
        )
        self.reply_budget_settings = reply_budget_settings
        self.role_settings = role_settings
        # 事件幂等表：None=关闭（默认）；启用后同一事件对同一能力只处理一次。
        self.idempotency_table: EventIdempotencyTable | SqliteEventIdempotencyTable | None = (
            idempotency_table
        )
        # 审查 A-19：群聊能力失败降级通知的会话级节流表（session_id → 最近一次
        # 通知的 time.monotonic() 时间戳）。管线能力跑在线程池，读写必须持锁。
        self._group_failure_notice_at: dict[str, float] = {}
        self._group_failure_notice_lock = threading.Lock()

    def _append_audit_safely(self, record: AuditRecord) -> None:
        try:
            self.audit_logger.append(record)
        except Exception:  # noqa: BLE001 - 审计写入失败时静默跳过，不阻断流水线。
            return

    def _record_receipt_safely(
        self,
        receipt: DeliveryReceipt,
        message: IncomingMessage | None = None,
    ) -> DeliveryReceipt:
        is_group_silent_failure = (
            message is not None
            and message.session_type.value == "group"
            and receipt.state
            in {
                ReceiptState.BLOCKED,
                ReceiptState.FAILED_RETRYABLE,
                ReceiptState.FAILED_FINAL,
            }
            and (
                receipt.transport == "runtime"
                or receipt.public_message == "该场景下未启用主动回复。"
            )
        )
        if is_group_silent_failure:
            receipt = receipt.model_copy(update={"public_message": ""})
        try:
            return self.receipt_repository.record(receipt)
        except Exception:  # noqa: BLE001 - 回执持久化失败时返回原始回执降级。
            return receipt

    def _prepare(
        self,
        message: IncomingMessage,
        capability_id: str,
        redrive_capability: AsyncCapabilityCallable | None = None,
    ) -> _PreparedRuntime | DeliveryReceipt:
        if self.feature_gate is not None:
            try:
                access = self.feature_gate(message, capability_id)
            except Exception:  # noqa: BLE001 - 状态读取失败关闭业务执行，不泄露底层异常。
                access = FeatureAccess(False, "feature_state_unavailable")
            if not access.allowed:
                receipt = DeliveryReceipt(
                    request_id=message.request_id, state=ReceiptState.BLOCKED,
                    transport="policy", public_message="这项功能暂时不可用。", debug_id=message.debug_id,
                )
                self._append_audit_safely(AuditRecord(
                    request_id=message.request_id, session_id=message.session_id,
                    capability_id=capability_id, stage="policy", event=access.reason,
                    severity=RiskLevel.MEDIUM, public_message=receipt.public_message,
                    private_debug="feature gate blocked execution",
                ))
                return self._record_receipt_safely(receipt, message)
        if not self.runtime_enabled:
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="policy",
                public_message="统一运行时已暂停。",
                debug_id=message.debug_id,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=capability_id,
                    stage="policy",
                    event="runtime_disabled",
                    severity=RiskLevel.MEDIUM,
                    public_message=receipt.public_message,
                    private_debug="bot_runtime_enabled=false",
                )
            )
            return self._record_receipt_safely(receipt, message)
        if self.role_settings is not None:
            message = message.model_copy(
                update={"sender_roles": self.role_settings.resolve_roles(message)}
            )
        if not self.runtime_control.allows(capability_id):
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="policy",
                public_message="统一运行时已暂停。",
                debug_id=message.debug_id,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=capability_id,
                    stage="policy",
                    event="runtime_paused",
                    severity=RiskLevel.MEDIUM,
                    public_message=receipt.public_message,
                    private_debug=f"reason={self.runtime_control.reason}",
                )
            )
            return self._record_receipt_safely(receipt, message)
        policy = self.policy_evaluator(message, capability_id)
        if not policy.allowed:
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="policy",
                public_message="该场景下未启用主动回复。",
                debug_id=policy.debug_id,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=capability_id,
                    stage="policy",
                    event="policy_denied",
                    severity=policy.risk_level,
                    public_message=receipt.public_message,
                    private_debug=policy.reason,
                )
            )
            return self._record_receipt_safely(receipt, message)

        quiet_hours = self.quiet_hours_checker.check(message, capability_id)
        if not quiet_hours.allowed:
            # 安静时间拦截一律静默（与限流拦截同款裁定）：无人 @ 也回提示语
            # 即无接触刷屏；审计 event/private_debug 已完整留痕。
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="policy",
                public_message="",
                debug_id=quiet_hours.debug_id,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=capability_id,
                    stage="policy",
                    event="quiet_hours_blocked",
                    severity=RiskLevel.LOW,
                    public_message=receipt.public_message,
                    private_debug=(
                        f"reason={quiet_hours.reason}; "
                        f"audit_tags={','.join(quiet_hours.audit_tags)}"
                    ),
                )
            )
            return self._record_receipt_safely(receipt, message)

        reply_budget = decide_reply_budget(
            message,
            capability_id,
            settings=self.reply_budget_settings,
        )
        proactive_request = "proactive_reply:selected" in policy.audit_tags
        interactive_request = (
            not proactive_request
            and (
                (message.session_type.value == "group" and message.mentions_bot)
                or capability_id != "bot.chat"
            )
        )
        rate_limit = self.rate_limiter.check_and_record(
            message,
            capability_id,
            amount=reply_budget.max_messages,
            interactive=interactive_request,
            proactive=proactive_request,
        )
        if not rate_limit.allowed:
            # 限流拦截一律静默（2026-09-12 实弹反馈）：降频是内部状态，
            # 把「已临时降频」发进群只会刷屏（且连续拦截会连发多条）。
            # 审计与 private_debug 仍完整留痕；public_message 置空即不投递。
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="policy",
                public_message="",
                debug_id=rate_limit.debug_id,
            )
            # 不再静默吞掉：明确找 bot 说话却被「太密」类限流拦下的，等解禁那一刻
            # 补跑一次（2026-09-25 用户裁定第 2 项）。补不上才维持原样静默。
            redrive_wait = self._schedule_rate_limit_redrive(
                message, capability_id, rate_limit, redrive_capability
            )
            if redrive_wait is not None:
                receipt.retry_count = int(
                    getattr(message, "redrive_count", 0) or 0
                ) + 1
                receipt.next_retry_at = datetime.now(timezone.utc) + timedelta(
                    seconds=redrive_wait
                )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=capability_id,
                    stage="policy",
                    event="rate_limited",
                    severity=RiskLevel.MEDIUM,
                    public_message=receipt.public_message,
                    private_debug=(
                        f"reason={rate_limit.reason}; "
                        f"retry_after_seconds={rate_limit.retry_after_seconds}"
                        + (
                            f"; redrive_scheduled_in={redrive_wait:.1f}s"
                            if redrive_wait is not None
                            else "; redrive=none"
                        )
                    ),
                )
            )
            return self._record_receipt_safely(receipt, message)
        # 审查 A-18：幂等 claim 移到全部门禁（黑白名单/安静时间/限流）判定
        # 之后——旧序 handle 先 claim 再 _prepare，被拦事件也消耗幂等键，
        # 同一条被拦消息的重发（用户重试）会被当 duplicate 吞掉，永远得不到
        # 回复；现在只有全门禁放行者才占键。claim 失败（重复投递）时立即
        # 回滚上面刚记的限流账：重复事件与旧 claim-first 行为一致，不消耗
        # 任何额度。A-04 修复不受影响：限流器调用点与入参保持原样（R3 最小
        # 间隔在限流器内部先于 interactive 早退的次序不动）。
        if not self._claim_event(message, capability_id):
            self._rollback_rate_limit_record(
                message,
                capability_id,
                amount=max(1, int(reply_budget.max_messages)),
                reason=rate_limit.reason,
            )
            return self._duplicate_receipt(message, capability_id)
        decision = BotDecision(
            request_id=message.request_id,
            should_respond=True,
            mode="command",
            trigger=message.plain_text.strip() or "message",
            capability_id=capability_id,
            target_scope=message.session_type,
            max_messages=reply_budget.max_messages,
            send_policy=SendPolicy.IMMEDIATE,
            persona_profile_id="default",
            context_budget=reply_budget.context_budget,
            decision_reason=f"{policy.reason}; {reply_budget.reason}",
            risk_level=policy.risk_level,
            privacy_level=policy.privacy_level,
            actor_roles=policy.actor_roles,
            audit_tags=[
                *policy.audit_tags,
                *reply_budget.audit_tags,
                *rate_limit.audit_tags,
            ],
        )
        return _PreparedRuntime(
            message=message,
            decision=decision,
            policy=policy,
            rate_limit_reason=rate_limit.reason,
            rate_limit_amount=max(1, int(reply_budget.max_messages)),
        )

    def _complete(
        self,
        prepared: _PreparedRuntime,
        result: CapabilityResult,
    ) -> DeliveryReceipt:
        message = prepared.message
        decision = prepared.decision
        # 需求项 6（2026-09-29 用户裁定）：同一轮内「回执」与「失败兜底文案」
        # 不得连发两条。回执晚于阈值先落一句、能力随后才失败——旧形态用户会收到
        # 「我在想」+「再发一次」两气泡。判失败结果时先读这枚一次性账：
        # 群腿跳过池内降级通知、私腿把纯失败话术压成静默审计（回执那句已经说过
        # 了，QQ 收不回，第二句只会重复同一件事）。**带接地内容的兜底不压**
        # （kb_grounded_fallback 兜底里有真资料，吞掉它就是吞回复，红线）。
        post_ack_failure = (
            result.operational_issue is not None
            and "kb_grounded_fallback" not in result.audit_tags
            and self._take_ack_emitted(message.request_id)
        )
        if (
            result.operational_issue is not None
            and message.session_type in {SessionType.GROUP, SessionType.CHANNEL}
        ):
            # 审查 A-19：失败结果本身仍压成空正文 + SILENT_AUDIT（错误细节
            # 不回群，细节走管理员告警链），但群聊不再零反馈——节流窗内补
            # 一句池内降级文案。超载快败（pipeline_busy）在通知方法内部豁免。
            if not post_ack_failure:
                self._maybe_submit_group_failure_notice(
                    message, result.operational_issue
                )
            result = result.model_copy(
                update={"body": "", "send_policy": SendPolicy.SILENT_AUDIT}
            )
        elif post_ack_failure:
            result = result.model_copy(
                update={"body": "", "summary": "", "send_policy": SendPolicy.SILENT_AUDIT}
            )
        if result.send_policy is SendPolicy.SILENT_AUDIT:
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.SKIPPED,
                transport="runtime",
                public_message="",
                debug_id=(result.operational_issue.debug_id if result.operational_issue else result.debug_id),
                operational_issue=result.operational_issue,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=decision.capability_id,
                    stage="runtime",
                    event="silent_audit",
                    severity=result.risk_level,
                    public_message="",
                    private_debug="; ".join(result.audit_tags) or "silent_audit",
                )
            )
            return self._record_receipt_safely(receipt, message)
        review = review_capability_result(result, decision)
        if not review.approved:
            public_message = _review_block_public_message(result, review)
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="reviewer",
                public_message=public_message,
                debug_id=review.debug_id,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=decision.capability_id,
                    stage="review",
                    event=review.action.value,
                    severity=review.risk_level,
                    public_message=public_message,
                    private_debug="; ".join(review.reasons),
                )
            )
            return self._record_receipt_safely(receipt, message)

        # G-3（T54 规格 §4.2 冻结插入点）：配音出站 hook 在 review 批准后、
        # render 前恰调一次——取文口径=review 批准后的 body（M-10 三害根修），
        # 失败挂 OperationalIssue（M-13 自动半）。hook 期挂 issue 在本分支之后，
        # 故不触发上方 A-19「压空正文」分支：群内正文照发，降级文案仍归中央
        # A-19（R-16②，本域不自拼）。
        if self.outbound_voice_enricher is not None:
            result = self.outbound_voice_enricher(message, decision, result)

        rendered = render_reviewed_output(result, review)
        use_forward = False
        # 合并转发触发条件：切分后**>3 条**（即 ≥4 条）才合并，仅对非 chat
        # 能力生效（2026-09-12 实弹反馈：chat 回复四段话被切成四条再触发合并，
        # 整段被折叠成聊天记录——chat 回复按整条直发，仅保留超长字数触发）。
        # 转发内的发送者名用 bot 自己的名字（由调用方传入），不再署用户昵称。
        if rendered.content_type == "text" and (
            (
                result.capability_id != "bot.chat"
                and should_forward_by_node_count(
                    rendered.text_fallback,
                    node_chars=self.forward_node_chars,
                    min_nodes=self.forward_min_nodes,
                    max_nodes=self.forward_max_nodes,
                )
            )
            or should_forward_long_text(
                rendered.text_fallback,
                min_chars=self.forward_min_chars,
            )
        ):
            rendered = build_forward_output(
                message.request_id,
                rendered.text_fallback,
                node_chars=self.forward_node_chars,
                max_nodes=self.forward_max_nodes,
                sender_name=self.forward_sender_name,
                risk_level=rendered.risk_level,
                privacy_level=rendered.privacy_level,
            )
            use_forward = True
        if decision.target_scope.value == "group" and not message.group_id:
            receipt = DeliveryReceipt(
                request_id=message.request_id,
                state=ReceiptState.BLOCKED,
                transport="runtime",
                public_message="群消息缺少 group_id，已阻断发送。",
                debug_id=message.debug_id,
            )
            self._append_audit_safely(
                AuditRecord(
                    request_id=message.request_id,
                    session_id=message.session_id,
                    capability_id=decision.capability_id,
                    stage="runtime",
                    event="missing_group_id",
                    severity=RiskLevel.MEDIUM,
                    public_message=receipt.public_message,
                    private_debug="target_scope=group but IncomingMessage.group_id is empty",
                )
            )
            return self._record_receipt_safely(receipt, message)
        send_request = SendRequest(
            request_id=message.request_id,
            session_id=message.session_id,
            target_scope=decision.target_scope,
            target_id=message.group_id or message.sender_id,
            origin_message_id=message.message_id,
            capability_id=decision.capability_id,
            content=rendered,
            send_policy=decision.send_policy,
            priority="normal",
            max_messages=decision.max_messages,
            dedupe_key=(
                f"{decision.capability_id}:{message.session_id}:"
                f"{message.message_id or message.request_id}"
                # 摘要层 S4（T123）：内容维度 d 段；缺 digest 退化=旧三元组
                # 逐字节不变（兼容硬锁，规约见 _content_dedupe_suffix）。
                + _content_dedupe_suffix(rendered)
            ),
            cooldown_key=prepared.policy.cooldown_key,
            expires_at=None,
            privacy_level=review.privacy_level,
            allow_split=use_forward,
            allow_forward=use_forward or review.privacy_level is PrivacyLevel.PUBLIC,
            deadline_monotonic=getattr(result, "deadline_monotonic", None),
            persona_profile_id=_resolve_persona_profile_id(decision, result),
            adapter=message.adapter,
            bot_id=message.bot_id,
            audit_tags=_dedupe_tags([*decision.audit_tags, *result.audit_tags,
                *(["chat_plain_text:v1"] if result.capability_id == "bot.chat" else [])]),
            operational_issue=result.operational_issue,
        )
        return self._record_receipt_safely(self.send_queue.submit(send_request), message)

    def _maybe_submit_group_failure_notice(
        self,
        message: IncomingMessage,
        issue: OperationalIssue,
    ) -> None:
        """群聊能力失败降级通知（审查 A-19）：一句池内文案 + 会话级节流。

        - 语义分界：pipeline_busy（超载快败）与限流/安静时间拦截同属故意的
          降频设计（超载时不放大流量），保持静默不走本方法；仅能力执行失败
          （错误态）回。私聊不经过本方法（chat 私聊失败已有人格话术池）。
        - 通知正文只来自固定文案池（GROUP_FAILURE_ACK_TEMPLATES 轮换），错误
          细节一律不回群（脱敏红线），细节走既有管理员告警链/错误报告卡。
        - fail-open：节流表异常或提交异常绝不影响主回执路径。
        """
        if issue.kind == "pipeline_busy":
            return
        now = time.monotonic()
        try:
            with self._group_failure_notice_lock:
                last = self._group_failure_notice_at.get(message.session_id)
                if (
                    last is not None
                    and now - last < _GROUP_FAILURE_NOTICE_WINDOW_SECONDS
                ):
                    return
                if (
                    len(self._group_failure_notice_at)
                    >= _GROUP_FAILURE_NOTICE_TRACK_CAP
                ):
                    expired = [
                        key
                        for key, at in self._group_failure_notice_at.items()
                        if now - at >= _GROUP_FAILURE_NOTICE_WINDOW_SECONDS
                    ]
                    for key in expired:
                        self._group_failure_notice_at.pop(key, None)
                    if (
                        len(self._group_failure_notice_at)
                        >= _GROUP_FAILURE_NOTICE_TRACK_CAP
                    ):
                        self._group_failure_notice_at.clear()
                self._group_failure_notice_at[message.session_id] = now
        except Exception:
            logger.debug("group failure notice throttle check failed", exc_info=True)
        phrase = random.choice(GROUP_FAILURE_ACK_TEMPLATES)
        request_id = message.request_id
        try:
            self.send_queue.submit(
                SendRequest(
                    request_id=request_id,
                    session_id=message.session_id,
                    target_scope=message.session_type,
                    target_id=message.group_id or message.sender_id,
                    origin_message_id=message.message_id,
                    capability_id="bot.group_failure_notice",
                    content=RenderedOutput(
                        request_id=request_id,
                        content_type="text",
                        content_ref={"text": phrase},
                        text_fallback=phrase,
                        risk_level=RiskLevel.LOW,
                        privacy_level=(
                            PrivacyLevel.GROUP
                            if message.session_type is SessionType.GROUP
                            else PrivacyLevel.PERSONAL
                        ),
                    ),
                    send_policy=SendPolicy.IMMEDIATE,
                    priority="normal",
                    max_messages=1,
                    dedupe_key=f"group_failure_notice:{request_id}",
                    cooldown_key=f"group_failure_notice:{message.session_id}",
                    expires_at=None,
                    privacy_level=(
                        PrivacyLevel.GROUP
                        if message.session_type is SessionType.GROUP
                        else PrivacyLevel.PERSONAL
                    ),
                    allow_split=False,
                    allow_forward=False,
                    persona_profile_id="default",
                    adapter=message.adapter,
                    bot_id=message.bot_id,
                    audit_tags=[
                        "group_failure_notice:v1",
                        f"issue_kind:{issue.kind}",
                    ],
                )
            )
        except Exception:
            logger.debug("group failure notice submit failed", exc_info=True)
            # 2026-09-18：提交失败=本轮通知并未发出，必须释放刚占用的节流窗口，
            # 否则一次瞬时失败会让该会话在 _GROUP_FAILURE_NOTICE_WINDOW_SECONDS
            # 内持续静默（用户侧表现为"群里 @ 了 bot 又突然没反应"）。
            try:
                with self._group_failure_notice_lock:
                    self._group_failure_notice_at.pop(message.session_id, None)
            except Exception:
                logger.debug("group failure notice throttle rollback failed", exc_info=True)
            return
        # 观测痕：能力失败有降级回应这件事本身留审计（正文不入审计，防池外
        # 文案漂移被误当真相源）。
        self._append_audit_safely(
            AuditRecord(
                request_id=request_id,
                session_id=message.session_id,
                capability_id="bot.group_failure_notice",
                stage="runtime",
                event="group_failure_notice",
                severity=RiskLevel.LOW,
                public_message="",
                private_debug=f"issue_kind={issue.kind}",
            )
        )

    def _internal_error(
        self,
        message: IncomingMessage,
        capability_id: str,
        exc: Exception,
    ) -> DeliveryReceipt:
        debug_id = message.debug_id
        issue = OperationalIssue(
            stage="runtime",
            kind="internal_error",
            retryable=False,
            debug_id=debug_id,
            # vis3（2026-09-13）：告警自带能力名+异常类型——旧告警只给
            # "internal_error"四个词，日志轮转后完全无法定位。
            safe_summary=f"{capability_id}:{type(exc).__name__}",
        )
        public_message = ""
        # 可观测性：能力层未预期异常必须留痕（类型+消息摘要+关键栈帧），
        # 否则线上只能看到"internal_error"四个词，无法定位。
        logger.exception(
            "capability internal error capability_id=%s debug_id=%s type=%s detail=%s",
            capability_id,
            debug_id,
            type(exc).__name__,
            redact_private_debug(str(exc)[:300]),
        )
        self._append_audit_safely(
            AuditRecord(
                request_id=message.request_id,
                session_id=message.session_id,
                capability_id=capability_id,
                stage="runtime",
                event="internal_error",
                severity=RiskLevel.HIGH,
                public_message=public_message,
                private_debug=redact_private_debug(
                    f"{type(exc).__name__}: {str(exc)[:200]}"
                ),
            )
        )
        receipt = DeliveryReceipt(
            request_id=message.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport="runtime",
            public_message=public_message,
            debug_id=debug_id,
            operational_issue=issue,
        )
        # 统一错误报告卡（2026-09-13）：能力执行异常向触发者回诊断卡。
        # 旁路钩子：fail-open，任何异常不影响既有回执路径；开关关=零动作。
        self._maybe_send_error_card(message, capability_id, exc)
        return self._record_receipt_safely(receipt, message)

    def _maybe_send_error_card(
        self,
        message: IncomingMessage,
        capability_id: str,
        exc: Exception,
    ) -> None:
        """统一错误报告卡旁路钩子（error_report.py 供实现）。

        - 只挂在能力执行异常 catch 点（_internal_error），LLM 链路语义不动；
        - bot_error_card_enabled=false 时零动作（与现状字节级一致）；
        - 冷却/渲染/提交全部在 error_report 内部 fail-open，这里再兜一层：
          钩子自身绝不让回执路径变形。
        """
        try:
            from plugins.bot_unified_runtime.domains.ops.monitor.error_report import (
                maybe_submit_error_card,
            )

            maybe_submit_error_card(self, message, capability_id, exc)
        except Exception:
            logger.debug("error report card hook failed", exc_info=True)

    def _duplicate_receipt(
        self,
        message: IncomingMessage,
        capability_id: str,
    ) -> DeliveryReceipt:
        receipt = DeliveryReceipt(
            request_id=message.request_id,
            state=ReceiptState.BLOCKED,
            transport="policy",
            public_message="该事件已处理过，忽略重复投递。",
            debug_id=message.debug_id,
        )
        self._append_audit_safely(
            AuditRecord(
                request_id=message.request_id,
                session_id=message.session_id,
                capability_id=capability_id,
                stage="policy",
                event="duplicate_event",
                severity=RiskLevel.LOW,
                public_message=receipt.public_message,
                private_debug="idempotency=duplicate_drop",
            )
        )
        return self._record_receipt_safely(receipt, message)

    def _claim_event(self, message: IncomingMessage, capability_id: str) -> bool:
        table = self.idempotency_table
        if table is None:
            return True
        key = build_event_dedupe_key(message)
        if not key:
            return True
        try:
            return table.claim(key, capability_id=capability_id)
        except Exception:  # noqa: BLE001 - 幂等表异常时放行，不阻断主链路。
            return True

    def _schedule_rate_limit_redrive(
        self,
        message: IncomingMessage,
        capability_id: str,
        decision: Any,
        capability: AsyncCapabilityCallable | None,
    ) -> float | None:
        """该不该补回、并就地排程；补不了返回 None（维持原样静默）。

        只有拿到 async 能力的调用方（``handle_async``）才补得动——同步 ``handle``
        没有可重放的协程，传 None 即不补，行为对它逐字节不变。
        """
        settings = self.redrive_settings
        if settings is None or capability is None:
            return None
        wait_seconds = redrive_wait_seconds(settings, message, capability_id, decision)
        if wait_seconds is None:
            # 补回排不出去 ⇒ 可能已是「补到尽头仍没回上」的终局：判据与文案真身
            # 都住 rate_limit（``rate_limit_exhausted_notice_due`` 三道门共读补回
            # 名册），这里只接线——对欠回复的请求补一句说明，不再纯静默。
            self._maybe_submit_rate_limit_exhausted_notice(
                message, capability_id, decision, settings
            )
            return None
        try:
            redrafted = message.model_copy(
                update={"redrive_count": int(message.redrive_count or 0) + 1}
            )
        except Exception:  # noqa: BLE001 - 造不出副本就维持旧行为，不能因补回炸掉本轮。
            return None
        task = asyncio.ensure_future(
            self._redrive_after(wait_seconds, redrafted, capability, capability_id)
        )
        self._redrive_tasks.add(task)
        task.add_done_callback(self._redrive_tasks.discard)
        return wait_seconds

    async def _redrive_after(
        self,
        wait_seconds: float,
        message: IncomingMessage,
        capability: AsyncCapabilityCallable,
        capability_id: str,
    ) -> None:
        """等过冷却再走一遍既有链路。

        刻意复用 ``handle_async`` 而不是抄一段"精简版"：门禁、限流、审核、出站
        闸门必须原样再过一次，否则补回的那一句就成了绕开中央件的第二条通路。
        """
        # 不套 try/except CancelledError：sleep 被取消时本就要向外传播，
        # 加一个"捕获后原样抛"的处理器是空转（ruff TRY203 会点出来）。
        await asyncio.sleep(wait_seconds)
        try:
            receipt = await self.handle_async(message, capability, capability_id)
            logger.info(
                "rate-limit redrive done request=%s capability=%s reason_scope=redrive "
                "state=%s attempt=%d",
                message.request_id,
                capability_id,
                getattr(getattr(receipt, "state", None), "value", receipt.state),
                int(message.redrive_count or 0),
            )
        except Exception as exc:  # noqa: BLE001 - 补回失败只留痕，不得炸掉事件循环。
            logger.warning(
                "rate-limit redrive failed request=%s capability=%s type=%s",
                message.request_id,
                capability_id,
                type(exc).__name__,
            )

    def _maybe_submit_rate_limit_exhausted_notice(
        self,
        message: IncomingMessage,
        capability_id: str,
        decision: Any,
        settings: Any,
    ) -> None:
        """补回终局的「耗尽说明」（2026-09-29 需求项 2 之 1 的最后一根接线）。

        补回把被拦的那句重放到 ``max_attempts`` 用尽仍被拦时，对「欠一句回复」的
        directed request 补一句说明。文案池与判据真身都住 policy/rate_limit
        （``RATE_LIMIT_EXHAUSTED_NOTICE_POOL`` × ``rate_limit_exhausted_notice_due``
        的三道门：密度拒因 × 次数用尽 × directed），这里零自造判据、零新文案。
        出站走既有统一路径（send_queue.submit，形态照群失败降级通知）。
        节流照回执节流器同款形态（查占同锁、投递失败 release 退还），键＝
        **收件面**（群号 or 私聊本人）：说明落在哪个会话就按哪个会话防刷，
        同群两个不同人先后撞耗尽也只说一句。fail-open：判据/节流/提交任何一处
        异常都不影响本轮既有的 BLOCKED 回执路径。
        """
        try:
            if not rate_limit_exhausted_notice_due(
                message, capability_id, decision, settings
            ):
                return
            throttle_key = str(
                getattr(message, "group_id", "")
                or getattr(message, "sender_id", "")
                or ""
            ).strip()
            if not throttle_key:
                # 收件面都算不出 ⇒ 这句说明必然投不出去，不开口（fail-closed，
                # 与回执面"有身份可判才开口"同一家规）。
                return
            claimed_at = self._rate_limit_notice_throttle.try_claim(throttle_key)
            if claimed_at is None:
                return
        except Exception:
            logger.debug("rate limit notice gate failed", exc_info=True)
            return
        phrase = pick_rate_limit_exhausted_notice(
            str(getattr(message, "session_id", "") or "")
        )
        request_id = message.request_id
        is_group = getattr(message, "session_type", None) is SessionType.GROUP
        try:
            self.send_queue.submit(
                SendRequest(
                    request_id=request_id,
                    session_id=message.session_id,
                    target_scope=message.session_type,
                    target_id=message.group_id or message.sender_id,
                    origin_message_id=message.message_id,
                    capability_id="bot.rate_limit_notice",
                    content=RenderedOutput(
                        request_id=request_id,
                        content_type="text",
                        content_ref={"text": phrase},
                        text_fallback=phrase,
                        risk_level=RiskLevel.LOW,
                        privacy_level=(
                            PrivacyLevel.GROUP
                            if is_group
                            else PrivacyLevel.PERSONAL
                        ),
                    ),
                    send_policy=SendPolicy.IMMEDIATE,
                    priority="normal",
                    max_messages=1,
                    dedupe_key=f"rate_limit_notice:{request_id}",
                    cooldown_key=f"rate_limit_notice:{message.session_id}",
                    expires_at=None,
                    privacy_level=(
                        PrivacyLevel.GROUP if is_group else PrivacyLevel.PERSONAL
                    ),
                    allow_split=False,
                    allow_forward=False,
                    persona_profile_id="default",
                    adapter=message.adapter,
                    bot_id=message.bot_id,
                    audit_tags=[
                        "rate_limit_exhausted_notice:v1",
                        f"redrive_reason:{getattr(decision, 'reason', '')}",
                    ],
                )
            )
        except Exception:
            logger.debug("rate limit exhausted notice submit failed", exc_info=True)
            self._rate_limit_notice_throttle.release(throttle_key, claimed_at)
            return
        logger.info(
            "rate limit exhausted notice emitted session=%s target=%s reason=%s",
            message.session_id,
            throttle_key,
            getattr(decision, "reason", ""),
        )
        self._append_audit_safely(
            AuditRecord(
                request_id=message.request_id,
                session_id=message.session_id,
                capability_id=capability_id,
                stage="policy",
                event="rate_limit_exhausted_notice",
                severity=RiskLevel.LOW,
                public_message=phrase,
                private_debug=(
                    f"reason={getattr(decision, 'reason', '')}; "
                    f"redrive_count={int(getattr(message, 'redrive_count', 0) or 0)}; "
                    f"max_attempts={int(getattr(settings, 'max_attempts', 0) or 0)}"
                ),
            )
        )

    def _rollback_rate_limit_record(
        self,
        message: IncomingMessage,
        capability_id: str,
        *,
        amount: int,
        reason: str,
    ) -> None:
        """审查 A-18：回滚一次 check_and_record 的限流记账（best-effort）。

        rollback 是限流器的可选能力（Protocol 未强制——测试桩与第三方实现
        只有 check_and_record）：getattr 探测，缺失即跳过；回滚自身失败也
        只留调试日志。额度补偿绝不能让回执路径变形（fail-open）。
        """
        rollback_fn = getattr(self.rate_limiter, "rollback", None)
        if not callable(rollback_fn):
            return
        try:
            rollback_fn(message, capability_id, amount=amount, reason=reason)
        except Exception:  # fail-open：回滚失败不影响回执。
            logger.debug("rate limit rollback failed", exc_info=True)

    def _rollback_rate_limit(self, prepared: _PreparedRuntime) -> None:
        """能力异常路径的额度回滚（现场取自 _PreparedRuntime，见上）。"""
        self._rollback_rate_limit_record(
            prepared.message,
            prepared.decision.capability_id,
            amount=prepared.rate_limit_amount,
            reason=prepared.rate_limit_reason,
        )

    def handle(
        self,
        message: IncomingMessage,
        capability: CapabilityCallable,
        capability_id: str = "bot.status",
    ) -> DeliveryReceipt:
        """同步入口：能力正文与完成腿都在**调用线程**上跑完。

        它存在的理由是「调用方本来就在线程里/根本没有循环」（console、smoke、
        脚本、离线测试）。事件循环线程不该再调它——那一形正是 X4 消灭的对象，
        命中时由 `_report_loop_thread_sync_call` 按 capability_id 留一次 WARNING。
        本方法的行为面（门禁序、幂等 claim 位置、异常→`_internal_error`、额度回滚）
        一字未动。
        """
        _report_loop_thread_sync_call(capability_id)
        _observe_decision_shadow(message, capability_id)
        try:
            # 审查 A-18：幂等 claim 已并入 _prepare（全部门禁+限流判定之后），
            # 这里不再先行 claim。
            prepared = self._prepare(message, capability_id)
            if isinstance(prepared, DeliveryReceipt):
                return prepared
            try:
                result = capability(prepared.message, prepared.decision)
            except Exception as exc:  # noqa: BLE001 - 能力异常统一转内部错误回执并回滚额度。
                # 审查 A-18：能力异常（非用户内容问题）→ 回滚本次限流记账，
                # 同会话紧跟的下一条消息不受上一条失败的影响。
                self._rollback_rate_limit(prepared)
                return self._internal_error(message, capability_id, exc)
            try:
                return self._complete(prepared, result)
            except Exception as exc:  # noqa: BLE001 - 出站阶段异常同样回滚额度。
                # 2026-09-18 核心链路排查：_complete 内 submit 抛错时消息并未入队
                # （用户收不到任何回复），此前该路径只转 internal_error 而**不回滚
                # 额度**——用户重试会被刚失败的那条继续占用配额。与能力异常同语义。
                self._rollback_rate_limit(prepared)
                return self._internal_error(message, capability_id, exc)
        except Exception as exc:  # pragma: no cover - integration fallback.  # noqa: BLE001 - 能力调用异常统一转为内部错误回执。
            return self._internal_error(message, capability_id, exc)

    def _progress_ack_candidate(self, message: IncomingMessage, capability_id: str) -> bool:
        """这轮是否属于"可以发回执"的候选（名单与开关，不含冷却判定）。

        只服务 `bot.chat`：命令类回复本来就快，多一句回执是纯噪音。投递口缺失
        （未注入中央出口）时一律不发——回执不许绕闸直调 send_queue.submit。
        """
        settings = self.progress_ack_settings
        if settings is None or not settings.enabled or self.progress_ack_submit is None:
            return False
        if capability_id != "bot.chat":
            return False
        # 会话类型取事件自带字段，不从 group_id 反推（缺群号不等于私聊）；
        # 两档归一的判据唯一住 progress_ack.normalize_session_type（频道/邮件/控制台
        # fail-closed 到群侧），此处不得再写一份。
        session_type = normalize_session_type(getattr(message, "session_type", ""))
        group_id = str(getattr(message, "group_id", "") or "").strip()
        return progress_ack_allowed(
            settings,
            session_type=session_type,
            group_id=group_id,
            sender_id=str(getattr(message, "sender_id", "") or "").strip(),
            # DEFECT-2 生效腿：群白名单记的是 QQ 群号，TG 频道消息也带 group_id＝chat.id
            # ⇒ 同号会被一并放行、回执投到另一个平台。平台归一表共读 progress_ack。
            platform=str(getattr(message, "platform", "") or "").strip(),
        )

    async def _await_with_progress_ack(
        self,
        message: IncomingMessage,
        prepared: _PreparedRuntime,
        capability: AsyncCapabilityCallable,
        capability_id: str,
    ) -> CapabilityResult:
        """等能力结果；到阈值仍未回来就先落一句回执，再继续等同一个任务。

        压的是"白等"而不是总预算：阈值只决定何时说话，不取消任何已花掉成本的
        真实回复（QQ 收不回，取消只会变成"不回话"）。阈值内出结果则零额外消息。
        """
        if not self._progress_ack_candidate(message, capability_id):
            return await capability(prepared.message, prepared.decision)
        settings = self.progress_ack_settings
        submit = self.progress_ack_submit
        if settings is None or submit is None:  # 收窄：候选判定已保证两者在场。
            return await capability(prepared.message, prepared.decision)
        session_id = str(getattr(message, "session_id", "") or "")
        delay_seconds = self._effective_ack_delay(settings)
        task = asyncio.ensure_future(capability(prepared.message, prepared.decision))
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=delay_seconds)
        except TimeoutError:
            # DEFECT-1（2026-09-28 修，S-ACK hub 申请 H-3）：shield 下"我们自己的到点"
            # 必然 task 未完；task 已 done 却抛 TimeoutError ⇒ 是**能力自抛**（快速失败），
            # 不是本轮慢。此时发一句"我还在跑"＝对着已结束的事谎报，且白占一次回执冷却。
            if task.done():
                raise
            # shield 保证超时不牵连真实任务，下面继续等它。
        emitted = await self._emit_progress_ack(
            message, session_id, submit, delay_seconds=delay_seconds
        )
        if emitted:
            # 需求项 6 连发治理：本轮已经开过口，`_complete` 见失败结果时
            # 不再补第二句兜底（回执+「再发一次」连发＝用户报的叠加形态）。
            self._mark_ack_emitted(message.request_id)
        return await task

    def _gateway_ema_ms(self) -> float | None:
        """网关当下多慢（单跳 EWMA 毫秒）。探针缺失/读失败一律 None=不自适应。"""
        probe = self.progress_ack_latency_probe
        if probe is None:
            return None
        try:
            value = probe()
        except Exception:  # noqa: BLE001 - 观测面坏了不得把回执一起带走。
            return None
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _effective_ack_delay(self, settings: ProgressAckSettings) -> float:
        return effective_ack_delay_seconds(settings, self._gateway_ema_ms())

    async def _emit_progress_ack(
        self,
        message: IncomingMessage,
        session_id: str,
        submit: Callable[[Any], Any],
        *,
        delay_seconds: float | None = None,
    ) -> bool:
        """发一句回执。**查冷却与占坑在同一个动作里**，发送失败退还。

        返回「这句是否真发出去了」：冷却挡下/投递异常都是 False——调用方据此
        决定要不要给本轮留「已开口」的账（需求项 6 的连发治理）。

        冷却判定放在这里而不是等能力之前：占坑必须紧贴"真的要不要发"这一决定，
        否则同会话两条并发慢问会双双通过前置检查、各发一句（评审席实跑过）。
        """
        claimed_at = self._progress_ack_throttle.try_claim(session_id)
        if claimed_at is None:
            return False
        if delay_seconds is not None:
            # 事后必须能回答"这次到底按几秒判的慢"——自适应与关死在日志上
            # 长得一样，没有这一行就只能靠重启前后的对照去猜（旧回执零留痕）。
            logger.info(
                "chat progress ack emitted session=%s delay=%.1fs gateway_ema_ms=%s",
                session_id,
                delay_seconds,
                self._gateway_ema_ms(),
            )
        try:
            request = build_progress_ack_request(
                message, pick_progress_ack_text(session_id)
            )
            value = submit(request)
            if inspect.isawaitable(value):
                await value
        except Exception:  # noqa: BLE001 - 回执是附加体验，失败不影响真实回复。
            logger.debug("chat progress ack submit failed")
            self._progress_ack_throttle.release(session_id, claimed_at)
            return False
        return True

    def _mark_ack_emitted(self, request_id: str) -> None:
        """本轮回执已出口 ⇒ 留账；同轮失败兜底据此不再连发（fail-open）。"""
        try:
            now = time.monotonic()
            with self._ack_emitted_lock:
                self._ack_emitted_at[request_id] = now
                expired = [
                    key
                    for key, at in self._ack_emitted_at.items()
                    if now - at >= _ACK_EMITTED_MARK_TTL_SECONDS
                ]
                for key in expired:
                    self._ack_emitted_at.pop(key, None)
                while len(self._ack_emitted_at) > _ACK_EMITTED_MARK_CAP:
                    self._ack_emitted_at.pop(next(iter(self._ack_emitted_at)))
        except Exception:  # fail-open：记不上下一步就当没发过，宁多发一句不吞回复。
            logger.debug("progress ack mark failed", exc_info=True)

    def _take_ack_emitted(self, request_id: str) -> bool:
        """读一次并销账（一轮只判一次）；过期条目顺手清。"""
        try:
            now = time.monotonic()
            with self._ack_emitted_lock:
                at = self._ack_emitted_at.pop(request_id, None)
                if at is not None:
                    return now - at < _ACK_EMITTED_MARK_TTL_SECONDS
                return False
        except Exception:  # noqa: BLE001 - fail-open：读不到账＝当没发过，宁多发一句不吞回复。
            return False

    async def handle_async(
        self,
        message: IncomingMessage,
        capability: AsyncCapabilityCallable,
        capability_id: str = "bot.status",
    ) -> DeliveryReceipt:
        # X4：下放面在这里收口——同步正文一律进线程池，协程正文原样留在循环上。
        # 必须排在 `_prepare` 之前：`redrive_capability` 存的就是这个 callable，
        # 限流补回腿（`_redrive_after` 复用 handle_async）也必须是下放形态；
        # 排在门禁之后则claim/限流账不变（幂等 claim 仍在全部门禁之后，A-18/#49★）。
        capability = ensure_offloaded(capability)
        _observe_decision_shadow(message, capability_id)
        try:
            prepared = self._prepare(
                message, capability_id, redrive_capability=capability
            )
            if isinstance(prepared, DeliveryReceipt):
                return prepared
            try:
                result = await self._await_with_progress_ack(
                    message, prepared, capability, capability_id
                )
            except Exception as exc:  # noqa: BLE001 - 能力异常统一转内部错误回执并回滚额度。
                # 审查 A-18：能力异常回滚限流记账（与 handle 同语义）。
                self._rollback_rate_limit(prepared)
                return self._internal_error(message, capability_id, exc)
            try:
                if self.outbound_voice_enricher is None:
                    return self._complete(prepared, result)
                # G-3：hook 在 _complete 内同步做阻塞 HTTP 合成（最坏 3×60s），
                # 而本协程跑在事件循环上——enricher 已接时整段完成路径放线程池
                # 执行，绝不阻塞循环（与旧配音包装的 asyncio.to_thread 同语义；
                # 键关部署仍走上面的原路，逐字节现状）。
                return await asyncio.to_thread(self._complete, prepared, result)
            except Exception as exc:  # noqa: BLE001 - 出站阶段异常同样回滚额度。
                # 2026-09-18：与同步 handle 同语义（出站失败=未投递=不该占配额）。
                self._rollback_rate_limit(prepared)
                return self._internal_error(message, capability_id, exc)
        except Exception as exc:  # pragma: no cover - integration fallback.  # noqa: BLE001 - 能力调用异常统一转为内部错误回执。
            return self._internal_error(message, capability_id, exc)

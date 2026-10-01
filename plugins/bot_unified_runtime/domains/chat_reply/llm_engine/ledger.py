"""LLM 计费账本（B5 阶段 M1）：结构化调用记录 + 落库 sink。

设计规格：``docs/design/llm-billing-ledger.md``（M1 范围）。

- 三张表 DDL（``llm_call_records`` / ``llm_usage_daily`` / ``balance_snapshots``）
  在本阶段一次建齐；M1 只写 ``llm_call_records``，日聚合与余额快照表留给
  M2/M4 消费（先建表不写，保证后续阶段无需再迁移）。
- 粒度：一行 = 一次 ``ModelRouter.generate()`` 调用（成功或最终失败各一行）；
  failover 中间尝试与影子并发落选者由 ``attempts_json`` 承载，不单列。
- ``ModelRouter`` 通过 :class:`CallRecordSink` Protocol 注入 recorder——
  router 不依赖 DB；显式注入优先，未注入时读开关
  ``bot_llm_billing_enabled``（Config 字段）→ ``BOT_LLM_BILLING_ENABLED``
  （os.environ）→ **默认关**（关 = 完全不写，行为回到现状）。
- 失败绝不阻塞聊天：``submit()`` 吞掉一切异常只打日志；写入走内存队列 +
  单独写线程批量 flush（每 ``flush_interval_seconds`` 秒或
  ``flush_batch_size`` 条），队列上限 10_000 条，满则丢弃最旧并计数。
- 计费（PricingService）属 M2+：本阶段 cost 四列全 NULL、
  ``pricing_source='unknown'``；有 token 消耗但未计价的行标
  ``unpriced=1``（"未知不是 0"）。
- SQLite 惯例与 ``sender/queue.py`` 同源：WAL 先行、进程内单连接 +
  锁串行化、``_ensure_schema_once`` 只建一次。
"""

from __future__ import annotations

import atexit
import datetime
import json
import logging
import math
import os
import queue
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    safe_llm_finish_reason,
)

logger = logging.getLogger(__name__)

# 内存队列上限：满则丢弃最旧（§4.1.3），防止计费故障反向撑爆进程内存。
MAX_PENDING_RECORDS = 10_000
# 写线程批刷：凑满条数或到时间即写（§4.1.3：每 2 秒或 50 条）。
DEFAULT_FLUSH_BATCH_SIZE = 50
DEFAULT_FLUSH_INTERVAL_SECONDS = 2.0
# error_summary 上限（§3 DDL 注释：脱敏短文本 ≤200 字符）。
ERROR_SUMMARY_MAX_CHARS = 200

_ENABLED_CONFIG_KEY = "bot_llm_billing_enabled"
_ENABLED_ENV_KEY = "BOT_LLM_BILLING_ENABLED"

_TRUE_WORDS = frozenset({"1", "true", "on", "yes"})
_FALSE_WORDS = frozenset({"0", "false", "off", "no"})

# ---- 回包 usage.cost 信任边界（S-FIX-BILLING F-2，2026-09-28）----
# 响应体在威胁模型内不完全可信：上游/中转能把 `cost` 写成任意数。
# 采信条件：正、有限、且（与本地估价同量级——网关按**实际服务渠道**计价，
# 与本地注册价存在渠道价差是常态，但超出 _MAX_RATIO 倍就不是"价差"而是
# 篡改面）；没有本地估价基线时以绝对上限兜底（单发 >100 元即异常形态）。
# 拒采必须记原因入列（cost_trust_note），拒了无痕等于没防。
GATEWAY_COST_MAX_RATIO = 50.0
GATEWAY_COST_NO_BASIS_CAP_MICRO = 100_000_000  # 100 元/发（微元）

# ---- 归因让路（S-FIX-BILLING F-3，2026-09-28）----
# PG「慢而成功」不抛异常 ⇒ 永不触发 resolver 熔断 ⇒ 每批付近超时延迟 ⇒
# 吞吐低于入账速率 ⇒ 队列满丢最旧 = 静默丢账。写线程的首要职责是把账行
# 落库：积压满一批、或近期归因耗时 EWMA 超预算时，本批**弃归因不弃账**。
# 预算缺省 = 一个刷写周期（构造参数可覆盖；0 = 关闭时长判据只留积压判据）。
ATTRIBUTION_BUDGET_FLUSH_CYCLES = 1.0
# 让路期 EWMA 衰减：否则一次慢查询会把归因永久钉死。
ATTRIBUTION_YIELD_EWMA_DECAY = 0.5


def _flag_value(raw: object) -> bool | None:
    """布尔开关文本解析：命中真/假词表返回对应布尔，未识别返回 None。"""
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


def ledger_enabled(config: object | None = None) -> bool:
    """账本总开关（唯一解析源）：Config 字段 → os.environ → **默认关**。

    Config 字段缺失（getattr 防御式）且未设环境变量 = 关；关 = router
    出口不组装 draft、不导入本模块的任何 DB 路径解析。
    """
    for raw in (
        getattr(config, _ENABLED_CONFIG_KEY, None),
        os.environ.get(_ENABLED_ENV_KEY),
    ):
        value = _flag_value(raw)
        if value is not None:
            return value
    return False


def resolve_default_db_path() -> str:
    """默认库路径：data/ 前缀按 runtime_paths 重映射到 Runtime 数据根。

    与 ``channel_health.resolve_default_db_path`` 同法。
    """
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        from scripts.runtime_paths import runtime_path

        return str(runtime_path("data/llm_billing.sqlite3"))
    except Exception:  # noqa: BLE001 - 解析失败退回相对路径。
        return "data/llm_billing.sqlite3"


# ==================== draft 与 sink 协议 ====================


@dataclass
class LLMCallDraft:
    """一次 generate() 调用的账本行草稿（字段与 llm_call_records DDL 对齐）。"""

    request_id: str = ""
    call_seq: int = 1
    session_id: str = ""
    capability: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int | None = None
    first_token_latency_ms: int | None = None
    provider_id: str = ""
    model_id: str = ""
    actual_model: str = ""
    effort: str = ""
    routing_group: str = ""
    prompt_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    input_cost_milli: int | None = None
    cache_read_cost_milli: int | None = None
    cache_creation_cost_milli: int | None = None
    output_cost_milli: int | None = None
    total_cost_milli: int | None = None
    # 微元（元 ×1e6）。存在这一列的理由不是"多一位精度好看"：单发短回复的
    # 实测成本 0.000219 元 = 0.219 毫厘，按行取整到毫厘就是 0，而报表是把行相加的
    # ⇒ 一天的账单会整体塌成接近零。取整只在**聚合那一步**做一次。
    total_cost_micro: int | None = None
    # 回包 usage.cost 信任边界留痕（F-2）：采信/缺席/本地估价 = ''；被拒 =
    # 原因 token（gateway_cost_rejected:* / gateway_total_rejected:*）。
    # 「拒了」必须可归因，否则账单被上游篡改后只剩一串看不出问题的数字。
    cost_trust_note: str = ""
    currency: str = "CNY"
    pricing_source: str = "unknown"
    unpriced: int = 0
    attempts: list[str] = field(default_factory=list)
    finish_reason: str = ""
    status: str = ""
    error_kind: str = ""
    error_summary: str = ""
    source: str = "router"
    schema_ver: int = 1
    # ---- 网关归因（B1，2026-09-25）：由写线程事后回填，回复路径不碰 ----
    # 关联键＝响应体 id（走网关时等于 requests.external_id）。空 = 本轮没拿到键。
    remote_request_id: str = ""
    # '' = 没查过（无键或未启用）；matched / miss / unavailable。
    # 三态必须可区分：缺了这一列，「没查到」会被读成「网关没记到渠道」。
    attribution_status: str = ""
    gateway_channel: str = ""
    gateway_latency_ms: int | None = None
    gateway_hops: list[dict[str, Any]] = field(default_factory=list)

    @property
    def attempts_json(self) -> str:
        try:
            return json.dumps(list(self.attempts), ensure_ascii=False)
        except (TypeError, ValueError):
            return "[]"

    @property
    def gateway_hops_json(self) -> str:
        try:
            return json.dumps(list(self.gateway_hops), ensure_ascii=False)
        except (TypeError, ValueError):
            return "[]"


class CallRecordSink(Protocol):
    """router 唯一依赖的记账协议（§4.1.1）：submit 绝不抛出。"""

    def submit(self, draft: LLMCallDraft) -> None:
        """提交一条账本行草稿；实现必须自行吞异常（失败不阻塞聊天）。"""
        ...  # pragma: no cover


# 网关归因批量反查口：给一批关联键，回 {键: Attribution}；**返回 None 表示
# 这一批没查成**（库不可达/超时/熔断），与"查了但没有"区分开。
AttributionLookup = Callable[[Sequence[str]], "Mapping[str, Any] | None"]


# ==================== draft 组装 ====================


# ATKLLM-2（P3）：usage token 入账前的发送侧对照（虚记 over-record 臂防线）。
# 上游/被控中转可回虚报 token 把 channel_spec 臂撑成天文成本；F-2 gateway_cost_trust
# 的对照基线 local_micro 同源于这份不可信 usage、自指放行（该函数注释已自认响应体
# 不完全可信）。这里在 token 进入估价与列存**之前**夹上界：① 绝对上限恒执法（真实
# 上下文窗口 ≤2M，此值绝不被合法调用触及）；② 有发送侧 payload 尺寸时对 prompt 叠加
# 「估算发送 token × 放大系数 + 常数头」相对上限（输出无法由输入尺寸界定，故相对夹
# 只作用 prompt）。取夹只降不升，合法小额逐字不动；被夹留痕（见 build_call_draft）。
TOKEN_MAX_ABSOLUTE = 10_000_000
TOKEN_REPORT_MAX_FACTOR = 8
TOKEN_REPORT_CONSTANT_HEAD = 4096
TOKEN_CHARS_PER_TOKEN_EST = 4


def _optional_token_int(value: object) -> int | None:
    """usage 字段 → 可空整数；缺失/非法 = None（未知不得写 0 冒充）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def redact_error_summary(value: object) -> str:
    """error_summary 出库前脱敏（复用 audit 的 redact_private_debug）+ 截断。"""
    text = str(value or "")
    if not text:
        return ""
    try:
        from plugins.bot_unified_runtime.domains.ops.audit.logger import (
            redact_private_debug,
        )

        text = redact_private_debug(text)
    except Exception:  # 脱敏模块不可用时退回原文截断。
        logger.debug("llm ledger redact helper unavailable", exc_info=True)
    return text[:ERROR_SUMMARY_MAX_CHARS]


@dataclass(frozen=True)
class _LocalEstimate:
    """channel_spec 口径的本地估价（微元原语 + 兼容用毫厘）。"""

    micro: int
    milli: int
    input_milli: int
    cache_read_milli: int
    output_milli: int


def gateway_cost_trust(
    raw_cost: object,
    local_micro: int | None,
) -> tuple[int | None, str]:
    """回包 ``usage.cost`` 的信任边界（F-2，SEAT-ATK-BILLING 2026-09-28）。

    返回 ``(采信微元 | None, 原因 token)``：
    - 缺席 / 非数值 ⇒ ``(None, '')``：维持「落回本地重算价」旧语义，无需留痕；
    - 零值 ⇒ ``(None, '')``：「未计价与零价必须可区分」的旧裁定保持（零不当成本）；
    - 负数 / 非有限（NaN/inf）/ 超对照比率 / 无对照基线时超绝对上限 ⇒
      ``(None, 原因)``：**拒采必须记原因**——上游篡改账单最阴的形态不是写负数
      （肉眼可见），而是写一个"看起来合理"的大数；对照基线就是本地重算价，
      拒了要能在账上归因，不是静默改道；
    - 其余正有限数 ⇒ ``(微元, '')``：网关按**实际服务渠道**计价的优先口径保持。

    不建第二条计价管线：``local_micro`` 由调用方用既有 channel_spec 公式算好
    传入，本函数只做信任裁决，不算价。
    """
    if isinstance(raw_cost, bool):
        return None, "gateway_cost_rejected:bool"
    if raw_cost is None or not isinstance(raw_cost, (int, float)):
        return None, ""
    number = float(raw_cost)
    if not math.isfinite(number):
        return None, "gateway_cost_rejected:non_finite"
    if number < 0:
        return None, "gateway_cost_rejected:negative"
    if number == 0:
        return None, ""
    micro = round(number * 1_000_000)
    if local_micro is not None and local_micro > 0:
        if micro > local_micro * GATEWAY_COST_MAX_RATIO:
            return None, "gateway_cost_rejected:over_sanity"
    elif micro > GATEWAY_COST_NO_BASIS_CAP_MICRO:
        return None, "gateway_cost_rejected:over_cap"
    return micro, ""


def build_call_draft(
    *,
    request_id: str = "",
    call_seq: int = 1,
    session_id: str = "",
    capability: str = "",
    started_at: str = "",
    completed_at: str = "",
    duration_ms: int | None = None,
    provider_id: str = "",
    model_id: str = "",
    actual_model: str = "",
    effort: str = "",
    routing_group: str = "",
    usage: dict[str, Any] | None = None,
    attempts: list[str] | None = None,
    finish_reason: str = "",
    status: str = "",
    error_kind: str = "",
    error_summary: str = "",
    price_in: float | None = None,
    price_out: float | None = None,
    price_cache_read: float | None = None,
    price_cache_creation: float | None = None,
    price_per_call: float | None = None,
    remote_request_id: str = "",
    sent_payload_chars: int | None = None,
) -> LLMCallDraft:
    """从出口原语组装 draft；token 取自 raw_usage 归一化键，缺失即 NULL。

    计费口径（2026-09-12 起接入渠道价）：调用方（router）透传该渠道
    单价（元 / 1M tokens：price_in/price_out/price_cache_read/
    price_cache_creation）；四价齐备 in/out 时即计价——
    ``账单 = 输入(未命中部分)×in + 缓存创建×creation价(缺省回退 in)
    + 缓存命中×read价(缺省回退 in) + 输出×out``，pricing_source=
    ``channel_spec``。价格缺失时 cost 保持 NULL、unpriced=1
    （「未知不是 0」），报表按未计价调用计数展示。
    """
    usage = usage if isinstance(usage, dict) else {}
    total_tokens = _optional_token_int(usage.get("total_tokens"))
    prompt_tokens = _optional_token_int(usage.get("prompt_tokens"))
    cache_creation_tokens = _optional_token_int(usage.get("cache_write_tokens"))
    cache_read_tokens = _optional_token_int(usage.get("cache_read_tokens"))
    completion_tokens = _optional_token_int(usage.get("completion_tokens"))
    # ATKLLM-2（P3）：入账 token「绝对上限恒执法（掐死天文级虚记）；发送侧
    # payload 相对上限只做存疑标注、不改动入账值」。
    #   · 绝对上限 min(报告值, TOKEN_MAX_ABSOLUTE) —— 只降不升，把 10^12 级
    #     虚报封到工程上限，下游估价自动吃到夹后值（探针 A1 的 inflated 因此归位）。
    #   · payload 相对上限 = 估算发送 token ×放大系数 + 常量头 —— 仅作
    #     「报告值 vs 我方实际发送体量」的存疑判据（token_report_sanity + 留痕日志），
    #     不写回报销值：真实 prompt 含系统提示/工具 schema/记忆等我方 messages
    #     之外的组装开销，纯按已见 payload 字符硬夹会误伤合法长上下文，也会与
    #     账单计价口径（既有回归）冲突；故相对面走台账明许的「标注存疑」而非夹值。
    token_report_sanity = False

    def _clamp_absolute(value: int | None) -> int | None:
        # 绝对上限：越界即夹到 TOKEN_MAX_ABSOLUTE（执法，改入账值）。
        nonlocal token_report_sanity
        if value is None:
            return None
        if value > TOKEN_MAX_ABSOLUTE:
            token_report_sanity = True
            return TOKEN_MAX_ABSOLUTE
        return value

    total_tokens = _clamp_absolute(total_tokens)
    prompt_tokens = _clamp_absolute(prompt_tokens)
    cache_creation_tokens = _clamp_absolute(cache_creation_tokens)
    cache_read_tokens = _clamp_absolute(cache_read_tokens)
    completion_tokens = _clamp_absolute(completion_tokens)

    # 发送侧 payload 相对判据：只标注存疑，不动上面的入账值（不改计价算术）。
    if sent_payload_chars is not None and sent_payload_chars >= 0 and prompt_tokens is not None:
        estimated_sent_tokens = (
            (sent_payload_chars + TOKEN_CHARS_PER_TOKEN_EST - 1)
            // TOKEN_CHARS_PER_TOKEN_EST
        )
        prompt_relative_cap = (
            estimated_sent_tokens * TOKEN_REPORT_MAX_FACTOR + TOKEN_REPORT_CONSTANT_HEAD
        )
        if prompt_tokens > prompt_relative_cap:
            token_report_sanity = True
    if token_report_sanity:
        logger.debug(
            "llm ledger token_report_sanity: usage clamped/marked for inflated "
            "report request_id=%s sent_payload_chars=%s",
            request_id,
            sent_payload_chars,
        )
    # finish_reason：显式参数优先；否则取 usage 内的白名单校验值（§3 DDL：
    # safe_llm_finish_reason 白名单值）。
    safe_finish = safe_llm_finish_reason(finish_reason)
    if not safe_finish:
        safe_finish = safe_llm_finish_reason(usage.get("finish_reason"))
    # 计价：in/out 缺任一即视为未配置价格（保持 NULL 口径）。
    # 单位换算（修 2026-09-13 千倍计价错账）：价格是 元/1M tokens，
    # 毫厘 = 1/1000 元 → cost_milli = tokens × price / 1000
    # （与 design §5.1 公式、runtime/pricing.model_call_cost_milli 同口径；
    #  旧实现 tokens × price 恰好放大 1000 倍）。
    input_cost_milli: int | None = None
    cache_read_cost_milli: int | None = None
    output_cost_milli: int | None = None
    total_cost_milli: int | None = None
    total_cost_micro: int | None = None
    pricing_source = "unknown"
    unpriced = 1 if (total_tokens is not None and total_tokens > 0) else 0
    # ---- 本地估价先算（F-2：它同时是网关成本信任裁决的对照基线）----
    # 微元按**未取整**的原式计算，不由毫厘 ×1000 反推（反推等于把已经丢掉的
    # 精度假装找回来，报表上会凭空多出可信度）。价是 元/1M token，
    # 所以「token 数 × 价」直接就是元×1e6＝微元。
    local_estimate: _LocalEstimate | None = None
    if price_in is not None and price_out is not None:
        cached_read = cache_read_tokens or 0
        cached_write = cache_creation_tokens or 0
        prompt = prompt_tokens or 0
        billed_input = max(0, prompt - cached_read - cached_write)
        creation_price = (
            price_cache_creation if price_cache_creation is not None else price_in
        )
        read_price = price_cache_read if price_cache_read is not None else price_in
        estimate_input_milli = round(
            billed_input * price_in / 1000 + cached_write * creation_price / 1000
        )
        estimate_cache_read_milli = round(cached_read * read_price / 1000)
        estimate_output_milli = round((completion_tokens or 0) * price_out / 1000)
        local_estimate = _LocalEstimate(
            micro=round(
                billed_input * price_in
                + cached_write * creation_price
                + cached_read * read_price
                + (completion_tokens or 0) * price_out
            ),
            milli=(
                estimate_input_milli
                + estimate_cache_read_milli
                + estimate_output_milli
            ),
            input_milli=estimate_input_milli,
            cache_read_milli=estimate_cache_read_milli,
            output_milli=estimate_output_milli,
        )
    # ---- 网关成本优先（2026-09-24），但过信任边界（F-2，2026-09-28）----
    # AxonHub 按**实际服务的那条渠道**算好成本并注入 `usage.cost`（实测
    # 136×0.3/1M + 116×1.5/1M == 返回的 0.0002148，逐位吻合）。本仓注册表
    # 只有指向网关的少数条目，看不见网关内部选了谁，所以合法的 cost 一旦
    # 存在就必须压过本地自算价；分项列留 NULL（网关只回合计，不回填假分项）。
    # 但 cost 来自响应体＝非可信输入：负数/NaN/inf/荒谬量级一律拒采并记原因，
    # 落回上面算好的本地估价（拒采 ≠ 免单，也 ≠ 静默采纳）。
    gateway_micro, cost_trust_note = gateway_cost_trust(
        usage.get("cost"),
        local_estimate.micro if local_estimate is not None else None,
    )
    from_gateway = gateway_micro is not None
    if gateway_micro is not None:
        total_cost_micro = gateway_micro
        total_cost_milli = round(gateway_micro / 1000)
        pricing_source = "gateway_cost"
        unpriced = 0
    elif local_estimate is not None:
        input_cost_milli = local_estimate.input_milli
        cache_read_cost_milli = local_estimate.cache_read_milli
        output_cost_milli = local_estimate.output_milli
        total_cost_milli = local_estimate.milli
        total_cost_micro = local_estimate.micro
        pricing_source = "channel_spec"
        unpriced = 0
    # 按次计费渠道（0.18元/请求类）：与 token 价并存则叠加，单独存在时
    # 独立成账（token 列保持 NULL）。网关成本已含按次，不再叠加以免双计。
    per_call_milli = (
        round(price_per_call * 1000) if price_per_call is not None else None
    )
    if per_call_milli is not None and not from_gateway:
        total_cost_milli = (total_cost_milli or 0) + per_call_milli
        if price_per_call is not None:
            total_cost_micro = (total_cost_micro or 0) + round(
                float(price_per_call) * 1_000_000
            )
        pricing_source = "channel_spec"
        unpriced = 0
    return LLMCallDraft(
        request_id=str(request_id or ""),
        call_seq=max(1, int(call_seq)),
        session_id=str(session_id or ""),
        capability=str(capability or ""),
        started_at=str(started_at or ""),
        completed_at=str(completed_at or ""),
        duration_ms=duration_ms,
        provider_id=str(provider_id or ""),
        model_id=str(model_id or ""),
        actual_model=str(actual_model or ""),
        effort=str(effort or ""),
        routing_group=str(routing_group or ""),
        prompt_tokens=prompt_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        input_cost_milli=input_cost_milli,
        cache_read_cost_milli=cache_read_cost_milli,
        output_cost_milli=output_cost_milli,
        total_cost_milli=total_cost_milli,
        total_cost_micro=total_cost_micro,
        cost_trust_note=cost_trust_note,
        pricing_source=pricing_source,
        unpriced=unpriced,
        attempts=list(attempts or []),
        finish_reason=safe_finish,
        status=str(status or ""),
        error_kind=str(error_kind or ""),
        error_summary=redact_error_summary(error_summary),
        remote_request_id=str(remote_request_id or ""),
    )


# ==================== 网关归因回填（写线程侧） ====================

# 账本新增列（B1）：迁移清单与 INSERT 顺序的共同真身，禁两处手抄。
ATTRIBUTION_COLUMNS: tuple[str, ...] = (
    "remote_request_id",
    "attribution_status",
    "gateway_channel",
    "gateway_latency_ms",
    "gateway_hops_json",
    "cache_creation_cost_milli",
)

# 待补列的完整清单＝归因列 + 成本精度列 + 成本信任留痕列。分开列名是为了语义不掺：
# ``total_cost_micro`` 不是归因事实，是"整数毫厘装不下单发成本"的补偿；
# ``cost_trust_note`` 是信任边界的裁决记录，两者都不许混进归因三态。
MIGRATED_COLUMNS: tuple[str, ...] = (
    *ATTRIBUTION_COLUMNS,
    "total_cost_micro",
    "cost_trust_note",
)

# 迁移用的列定义（与 _SCHEMA_SQL 内文逐字同源，只此一份）。
_ATTRIBUTION_COLUMN_DDL = {
    "remote_request_id": "remote_request_id TEXT NOT NULL DEFAULT ''",
    "attribution_status": "attribution_status TEXT NOT NULL DEFAULT ''",
    "gateway_channel": "gateway_channel TEXT NOT NULL DEFAULT ''",
    "gateway_latency_ms": "gateway_latency_ms INTEGER",
    "gateway_hops_json": "gateway_hops_json TEXT NOT NULL DEFAULT '[]'",
    "cache_creation_cost_milli": "cache_creation_cost_milli INTEGER",
    "total_cost_micro": "total_cost_micro INTEGER",
    "cost_trust_note": "cost_trust_note TEXT NOT NULL DEFAULT ''",
}

# 网关 cost_items 的 itemCode → 账本列（2026-09-25 实测四枚 itemCode 名）。
_ATTRIBUTION_ITEM_COLUMNS = {
    "prompt_tokens": "input_cost_milli",
    "completion_tokens": "output_cost_milli",
    "prompt_cached_tokens": "cache_read_cost_milli",
    "prompt_write_cached_tokens": "cache_creation_cost_milli",
}

ATTRIBUTION_MATCHED = "matched"
ATTRIBUTION_MISS = "miss"
ATTRIBUTION_UNAVAILABLE = "unavailable"
# F-3 让路态：这批**没去查**（积压/归因超预算），与「查不了」和「查了没有」
# 都可区分——归因是被主动放弃以保护账行落库的，不许冒充故障或空结果。
ATTRIBUTION_SKIPPED = "skipped"


def apply_attribution(
    draft: LLMCallDraft,
    result: object,
    *,
    unavailable: bool = True,
) -> None:
    """把网关侧事实并进一条草稿；就地改，返回 None。

    ``result`` 三种给法对应三种账：``None`` = 这一批根本没查成（库不在/超时）
    ⇒ ``unavailable``；查了但没有这条 ⇒ ``miss``；命中 ⇒ ``matched``。
    三态必须分开：只有 ``matched`` 才允许下游把 ``gateway_channel`` 读成
    「网关说的实际渠道」，否则 NULL/空串会被当成「网关没记到渠道」。
    单体（一个 ``Attribution``）与批量（``{关联键: Attribution}``）两种给法都收：
    写线程走批量，调用方手上只有一条时不必自己再包一层 dict。

    口径：
    - **合计只信网关的 total_cost**，不由分项相加（分项各自取整到毫厘，
      相加会与合计差 1–2 毫厘，对账时说不清是谁错）。
    - 分项价到齐任一项 ⇒ ``pricing_source='gateway_cost_items'``：这是比
      ``gateway_cost`` 更强的证据，允许覆盖本地自算价。
    - ``duration_ms`` 不动：那是用户等的时间（含排队与 bot 侧开销）；
      网关侧耗时另存 ``gateway_latency_ms``。
    - 已有观测值不被后到的数改写（``first_token_latency_ms`` 只补空）。
    """
    key = str(draft.remote_request_id or "")
    if not key:
        return
    if result is None:
        draft.attribution_status = ATTRIBUTION_UNAVAILABLE
        return
    single_key = getattr(result, "remote_request_id", None)
    if single_key is not None:  # 单体 Attribution 形态：键对得上就用
        found = result if str(single_key) in {"", key} else None
    else:
        found = result.get(key) if isinstance(result, dict) else None
    if found is None:
        if unavailable and not result:
            draft.attribution_status = ATTRIBUTION_UNAVAILABLE
        else:
            draft.attribution_status = ATTRIBUTION_MISS
        return
    draft.attribution_status = ATTRIBUTION_MATCHED
    draft.gateway_channel = str(getattr(found, "gateway_channel", "") or "")
    if draft.first_token_latency_ms is None:
        draft.first_token_latency_ms = getattr(found, "first_token_latency_ms", None)
    draft.gateway_latency_ms = getattr(found, "latency_ms", None)
    # token 四列：bot 侧 `_extract_usage` 只在 >0 时写键，所以这里的 None 既是
    # 「没缓存」也可能是「上游没报」。网关是计费方，它给的数就是入账依据，
    # 因此**只补空、不覆盖**已有观测值（与首字耗时同一口径）。
    for attr, field_name in (
        ("prompt_tokens", "prompt_tokens"),
        ("cache_read_tokens", "cache_read_tokens"),
        ("cache_creation_tokens", "cache_creation_tokens"),
        ("completion_tokens", "completion_tokens"),
    ):
        if getattr(draft, attr) is None:
            value = getattr(found, field_name, None)
            if isinstance(value, int):
                setattr(draft, attr, value)
    hops = getattr(found, "hops", None) or []
    draft.gateway_hops = [
        hop.as_dict() if hasattr(hop, "as_dict") else dict(hop) for hop in hops
    ]
    item_costs = getattr(found, "item_cost_milli", None) or {}
    filled = False
    for item_code, column in _ATTRIBUTION_ITEM_COLUMNS.items():
        value = item_costs.get(item_code)
        if isinstance(value, int):
            setattr(draft, column, value)
            filled = True
    total = getattr(found, "total_cost_micro", None)
    if isinstance(total, bool):
        total = None
    if isinstance(total, int):
        if total < 0:
            # F-2：归因段的覆盖同样要过负数防线——网关库里不该有负成本，
            # 出现即异常形态：保持既有本地/回包口径并留痕，绝不把账单冲负。
            # 留痕用叠加不用覆写：A 段（回包 cost）若已拒过一次，两次异常
            # 都得在账上看得见，抹掉前者等于销毁第一现场。
            note = "gateway_total_rejected:negative"
            draft.cost_trust_note = (
                f"{draft.cost_trust_note};{note}" if draft.cost_trust_note else note
            )
        else:
            draft.total_cost_micro = total
            draft.total_cost_milli = round(total / 1000)
            draft.unpriced = 0
            # 分项到齐才升格为 cost_items；只有合计则维持 A 段的 gateway_cost 口径。
            draft.pricing_source = (
                "gateway_cost_items" if filled else "gateway_cost"
            )


# ==================== SQLite 落库服务 ====================


class LedgerService:
    """``llm_call_records`` 写入服务：内存队列 + 单写线程批量落库。

    线程模型：``submit()`` 任意线程可调（只入队，绝不抛）；后台 daemon
    线程攒批写 SQLite（WAL、进程内单连接 + RLock 串行化）。写失败只计数
    打日志，绝不向上传播。
    """

    def __init__(
        self,
        db_path: str,
        *,
        flush_batch_size: int = DEFAULT_FLUSH_BATCH_SIZE,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
        max_pending: int = MAX_PENDING_RECORDS,
        writer_thread: threading.Thread | None = None,
        attribution_lookup: AttributionLookup | None = None,
        attribution_budget_seconds: float | None = None,
    ) -> None:
        self.db_path = str(db_path)
        self.flush_batch_size = max(1, int(flush_batch_size))
        self.flush_interval_seconds = max(0.05, float(flush_interval_seconds))
        self.dropped_count = 0
        self.write_error_count = 0
        # 网关归因反查（B1）：None = 关闭，行为与加列前逐字节一致。
        # 只在写线程里调用——回复路径零新增等待。
        self._attribution_lookup = attribution_lookup
        self.attribution_error_count = 0
        # F-3 让路态：归因耗时 EWMA 与预算（缺省 = 一个刷写周期；
        # 显式 0 = 关闭时长判据，只留积压判据）。
        self.attribution_budget_seconds = (
            float(attribution_budget_seconds)
            if attribution_budget_seconds is not None
            else self.flush_interval_seconds * ATTRIBUTION_BUDGET_FLUSH_CYCLES
        )
        self.attribution_skipped_count = 0
        self._attribution_ewma_seconds = 0.0
        self._pending: queue.Queue[LLMCallDraft | None] = queue.Queue(
            maxsize=max(1, int(max_pending))
        )
        self._connection: sqlite3.Connection | None = None
        self._connection_lock = threading.RLock()
        self._schema_ready = False
        self._stop_event = threading.Event()
        self._writer = writer_thread
        if self._writer is None:
            self._writer = threading.Thread(
                target=self._writer_loop, name="llm-ledger-writer", daemon=True
            )
            self._writer.start()
        # 建库迁移前置（WAL 先行）：服务构造即建表，后续写路径零迁移开销。
        self._ensure_schema_once()

    # ---- sink 协议 ----

    def submit(self, draft: LLMCallDraft) -> None:
        """入队一条草稿；任何失败只计数告警，绝不抛出（§4.1.2）。"""
        try:
            try:
                self._pending.put_nowait(draft)
            except queue.Full:
                # 满则丢弃最旧：腾一格再放新行（保新弃旧）。
                # 丢行必须留痕（F-3）：被丢记录的身份三元组进告警级日志，
                # 计数经 peek_ledger_service() 投给 /bot model usage 账本健康行——
                # 静默丢账 = 账单失真无从归因，比没账更危险。
                dropped = None
                try:
                    dropped = self._pending.get_nowait()
                except queue.Empty:
                    pass
                self.dropped_count += 1
                logger.warning(
                    "llm ledger queue full; dropped oldest record "
                    "request_id=%s model_id=%s completed_at=%s (total dropped=%d)",
                    getattr(dropped, "request_id", "?"),
                    getattr(dropped, "model_id", "?"),
                    getattr(dropped, "completed_at", "?"),
                    self.dropped_count,
                )
                self._pending.put_nowait(draft)
        except Exception:
            self.dropped_count += 1
            logger.debug("llm ledger submit failed", exc_info=True)

    # ---- 生命周期 ----

    def flush(self, *, timeout: float = 5.0) -> int:
        """同步排空当前队列并落库（测试与退出路径用）；返回写入行数。"""
        rows = self._drain_pending()
        return self._write_batch(rows, timeout=timeout)

    def close(self) -> None:
        """停写线程、冲刷余量、关连接；幂等。"""
        self._stop_event.set()
        try:
            self._pending.put_nowait(None)
        except queue.Full:
            pass
        writer = self._writer
        if (
            writer is not None
            and writer.ident is not None  # 未启动的注入桩线程不可 join。
            and writer is not threading.current_thread()
        ):
            writer.join(timeout=5.0)
        self._drain_and_write_remaining()
        with self._connection_lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except sqlite3.Error:
                    pass
                self._connection = None

    # ---- 内部 ----

    def _drain_pending(self) -> list[LLMCallDraft]:
        rows: list[LLMCallDraft] = []
        while True:
            try:
                item = self._pending.get_nowait()
            except queue.Empty:
                break
            if item is None:  # close 哨兵：放回让 writer 线程也能看到。
                try:
                    self._pending.put_nowait(None)
                except queue.Full:
                    pass
                break
            rows.append(item)
        return rows

    def _drain_and_write_remaining(self) -> None:
        rows = self._drain_pending()
        if rows:
            self._write_batch(rows)

    def _writer_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                first = self._pending.get(timeout=self.flush_interval_seconds)
            except queue.Empty:
                continue
            if first is None:
                break
            batch = [first]
            while len(batch) < self.flush_batch_size:
                try:
                    item = self._pending.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    try:
                        self._pending.put_nowait(None)
                    except queue.Full:
                        pass
                    break
                batch.append(item)
            self._write_batch(batch)
        self._drain_and_write_remaining()

    def _shared_connection(self) -> sqlite3.Connection:
        with self._connection_lock:
            if self._connection is None:
                connection = sqlite3.connect(
                    self.db_path, timeout=5.0, check_same_thread=False
                )
                connection.row_factory = sqlite3.Row
                self._connection = connection
            return self._connection

    def _discard_connection(self) -> None:
        with self._connection_lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except sqlite3.Error:
                    pass
                self._connection = None
                self._schema_ready = False

    def _ensure_schema_once(self) -> None:
        if self._schema_ready:
            return
        self._ensure_schema()
        self._schema_ready = True

    def _ensure_schema(self) -> None:
        """三张表 DDL 一次建齐（幂等）；WAL 先行，失败降级不致命。"""
        import pathlib

        parent = pathlib.Path(self.db_path).parent
        parent.mkdir(parents=True, exist_ok=True)
        with self._connection_lock:
            connection = self._shared_connection()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass  # 网络盘等不支持 WAL 时降级默认 journal。
            connection.executescript(_SCHEMA_SQL)
            self._migrate_attribution_columns(connection)
            connection.commit()

    @staticmethod
    def _migrate_attribution_columns(connection: sqlite3.Connection) -> None:
        """B1 新增列的自动补齐（家规先例＝affinity 三列 / memory_store_v21）。

        生产库早已按旧 DDL 建好，``CREATE TABLE IF NOT EXISTS`` 对存量库是
        空操作——不 ALTER 的话新列根本不存在，INSERT 当场报错，而那条错误
        会被写线程吞成"账本没写进去"。迁移只加列、给缺省，绝不动存量行。
        """
        try:
            existing = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(llm_call_records)")
            }
        except sqlite3.Error:
            return
        for column in MIGRATED_COLUMNS:
            if column in existing:
                continue
            definition = _ATTRIBUTION_COLUMN_DDL[column]
            try:
                connection.execute(
                    f"ALTER TABLE llm_call_records ADD COLUMN {definition}"
                )
            except sqlite3.Error:
                logger.warning(
                    "llm ledger attribution column %s migration failed", column,
                    exc_info=True,
                )

    def _attribution_should_yield(self, backlog: int) -> bool:
        """F-3 让路判定（纯决策，离线可锁）：积压满一批，或近期归因超预算。

        写线程的首要职责是把账行落库；归因是增值项。旧版把 PG 反查无条件钉在
        每批写入前：「慢而成功」既不抛异常也不触熔断，每批都付近超时延迟 ⇒
        吞吐低于入账速率 ⇒ 队列满丢最旧 = 静默丢账。这里让写吞吐反压归因——
        宁可某几批没归因（``skipped`` 如实入账），不可丢账行。
        """
        if backlog >= self.flush_batch_size:
            return True
        budget = self.attribution_budget_seconds
        return budget > 0.0 and self._attribution_ewma_seconds >= budget

    def _enrich_with_attribution(self, rows: list[LLMCallDraft]) -> None:
        """写线程内的一次网关反查：只在有关联键且装了反查口时才发。

        放在这里而不是回复路径上，是因为这一跳要等网络（本机 PG，但网关库
        在别的机器上也一样）、且**每条消息都查一次**会把回复拖慢。账本写
        线程本来就是异步攒批的，一批一次查询，代价与回复无关。
        失败一律降级成 ``unavailable`` 标记，绝不向上抛——抛出会让整批
        ``executemany`` 失败，等于归因故障连账本一起丢。

        F-3 让路：``_attribution_should_yield`` 命中时本批**弃归因不弃账**——
        键行标 ``skipped``（第四态：没去查，与「查不了」「查了没有」都不同），
        计数留痕进告警日志；让路期 EWMA 指数衰减，队列疏通/延迟回落后归因
        自动回位，不会被一次慢查询永久钉死。
        """
        lookup = self._attribution_lookup
        if lookup is None:
            return
        keyed = [row for row in rows if row.remote_request_id]
        if not keyed:
            return
        ids = sorted({row.remote_request_id for row in keyed})
        if self._attribution_should_yield(self._pending.qsize()):
            self.attribution_skipped_count += 1
            for row in keyed:
                row.attribution_status = ATTRIBUTION_SKIPPED
            self._attribution_ewma_seconds *= ATTRIBUTION_YIELD_EWMA_DECAY
            logger.warning(
                "llm ledger attribution deferred to protect ledger writes "
                "(keyed=%d backlog=%d ewma=%.2fs budget=%.2fs skipped_total=%d)",
                len(keyed),
                self._pending.qsize(),
                self._attribution_ewma_seconds,
                self.attribution_budget_seconds,
                self.attribution_skipped_count,
            )
            return
        started = time.monotonic()
        try:
            try:
                result = lookup(ids)
            except Exception:
                self.attribution_error_count += 1
                logger.debug("llm ledger attribution lookup failed", exc_info=True)
                result = None
        finally:
            elapsed = max(0.0, time.monotonic() - started)
            self._attribution_ewma_seconds = (
                self._attribution_ewma_seconds * (1 - ATTRIBUTION_YIELD_EWMA_DECAY)
                + elapsed * ATTRIBUTION_YIELD_EWMA_DECAY
            )
        for row in keyed:
            # 三态里 `miss` 与 `unavailable` 的分界就在这一行：`lookup` 返回 None
            # ＝没查成（故障），返回 {}＝查成了但网关没有这些 id（真 miss）。
            # 一律传缺省 unavailable=True 会把「网关没记到」写成「查不了」。
            apply_attribution(row, result, unavailable=result is None)

    def _write_batch(self, rows: list[LLMCallDraft], *, timeout: float = 5.0) -> int:
        if not rows:
            return 0
        del timeout  # sqlite3 timeout 已在连接级设置；保留参数给调用方语义。
        self._enrich_with_attribution(rows)
        payload = [
            (
                row.request_id,
                int(row.call_seq),
                row.session_id,
                row.capability,
                row.started_at,
                row.completed_at,
                row.duration_ms,
                row.first_token_latency_ms,
                row.provider_id,
                row.model_id,
                row.actual_model,
                row.effort,
                row.routing_group,
                row.prompt_tokens,
                row.cache_creation_tokens,
                row.cache_read_tokens,
                row.completion_tokens,
                row.total_tokens,
                row.input_cost_milli,
                row.cache_read_cost_milli,
                row.output_cost_milli,
                row.cache_creation_cost_milli,
                row.total_cost_milli,
                row.total_cost_micro,
                row.cost_trust_note,
                row.currency,
                row.pricing_source,
                int(row.unpriced),
                row.attempts_json,
                len(row.attempts),
                row.finish_reason,
                row.status,
                row.error_kind,
                row.error_summary,
                row.source,
                int(row.schema_ver),
                row.remote_request_id,
                row.attribution_status,
                row.gateway_channel,
                row.gateway_latency_ms,
                row.gateway_hops_json,
                row.completed_at or row.started_at,
            )
            for row in rows
        ]
        try:
            with self._connection_lock:
                self._ensure_schema_once()
                connection = self._shared_connection()
                connection.executemany(_INSERT_SQL, payload)
                connection.commit()
            return len(payload)
        except sqlite3.Error:
            self.write_error_count += 1
            self._discard_connection()
            logger.warning(
                "llm ledger write failed (total errors=%d)",
                self.write_error_count,
                exc_info=True,
            )
            return 0
        except Exception:
            self.write_error_count += 1
            logger.debug("llm ledger unexpected write failure", exc_info=True)
            return 0


_INSERT_SQL = """
INSERT INTO llm_call_records (
    request_id, call_seq, session_id, capability,
    started_at, completed_at, duration_ms, first_token_latency_ms,
    provider_id, model_id, actual_model, effort, routing_group,
    prompt_tokens, cache_creation_tokens, cache_read_tokens,
    completion_tokens, total_tokens,
    input_cost_milli, cache_read_cost_milli, output_cost_milli,
    cache_creation_cost_milli,
    total_cost_milli, total_cost_micro, cost_trust_note, currency,
    pricing_source, unpriced,
    attempts_json, attempts_count, finish_reason,
    status, error_kind, error_summary,
    source, schema_ver,
    remote_request_id, attribution_status, gateway_channel,
    gateway_latency_ms, gateway_hops_json,
    created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# DDL 与 docs/design/llm-billing-ledger.md §3/§5.2/§7.3 逐字段对齐。
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS llm_call_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  TEXT NOT NULL,
    call_seq    INTEGER NOT NULL DEFAULT 1,
    session_id  TEXT NOT NULL DEFAULT '',
    capability  TEXT NOT NULL DEFAULT '',
    started_at    TEXT NOT NULL,
    completed_at  TEXT NOT NULL,
    duration_ms   INTEGER,
    first_token_latency_ms INTEGER,
    provider_id   TEXT NOT NULL DEFAULT '',
    model_id      TEXT NOT NULL,
    actual_model  TEXT NOT NULL DEFAULT '',
    effort        TEXT NOT NULL DEFAULT '',
    routing_group TEXT NOT NULL DEFAULT '',
    prompt_tokens          INTEGER,
    cache_creation_tokens  INTEGER,
    cache_read_tokens      INTEGER,
    completion_tokens      INTEGER,
    total_tokens           INTEGER,
    input_cost_milli      INTEGER,
    cache_read_cost_milli INTEGER,
    output_cost_milli     INTEGER,
    cache_creation_cost_milli INTEGER,
    total_cost_milli      INTEGER,
    total_cost_micro      INTEGER,
    cost_trust_note       TEXT NOT NULL DEFAULT '',
    currency              TEXT NOT NULL DEFAULT 'CNY',
    pricing_source        TEXT NOT NULL DEFAULT 'unknown',
    unpriced              INTEGER NOT NULL DEFAULT 0,
    attempts_json TEXT NOT NULL DEFAULT '[]',
    attempts_count INTEGER NOT NULL DEFAULT 0,
    finish_reason  TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL,
    error_kind     TEXT NOT NULL DEFAULT '',
    error_summary  TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT 'router',
    schema_ver INTEGER NOT NULL DEFAULT 1,
    remote_request_id  TEXT NOT NULL DEFAULT '',
    attribution_status TEXT NOT NULL DEFAULT '',
    gateway_channel    TEXT NOT NULL DEFAULT '',
    gateway_latency_ms INTEGER,
    gateway_hops_json  TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_call_started ON llm_call_records (started_at);
CREATE INDEX IF NOT EXISTS idx_llm_call_model   ON llm_call_records (model_id, started_at);
CREATE INDEX IF NOT EXISTS idx_llm_call_session ON llm_call_records (session_id, started_at);
CREATE INDEX IF NOT EXISTS idx_llm_call_request ON llm_call_records (request_id);
CREATE INDEX IF NOT EXISTS idx_llm_call_completed ON llm_call_records (completed_at);

CREATE TABLE IF NOT EXISTS llm_usage_daily (
    day TEXT NOT NULL,
    dimension TEXT NOT NULL,
    dimension_key TEXT NOT NULL DEFAULT '',
    calls INTEGER NOT NULL DEFAULT 0,
    failed_calls INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost_milli INTEGER NOT NULL DEFAULT 0,
    unpriced_calls INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, dimension, dimension_key)
);

CREATE TABLE IF NOT EXISTS balance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    valid INTEGER NOT NULL,
    invalid_message TEXT NOT NULL DEFAULT '',
    remaining REAL, used REAL, total REAL,
    currency TEXT NOT NULL DEFAULT '',
    plan_name TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    source_endpoint TEXT NOT NULL DEFAULT '',
    raw_status_code INTEGER,
    queried_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_balance_provider ON balance_snapshots (provider_id, queried_at);
"""


# ==================== 渠道维度只读聚合（报告侧渠道子行） ====================

# 窗口日期过滤用 completed_at 范围比较（P3-9）：completed_at 由
# ``datetime.now(zone).isoformat(timespec="milliseconds")`` 写入（同进程
# 单一时区偏移），ISO 文本字典序即时序；旧 ``substr(completed_at,1,10)
# BETWEEN`` 对每行做函数计算，无法走索引（全表扫），改为
# ``completed_at >= start_day AND completed_at < 结束日次日``（上界开区间）
# 走 idx_llm_call_completed，与旧实现的按本地日闭区间语义逐行等价。
# 不能用 ``date()``：它会把带时区偏移的时间戳换算成 UTC，本地日会被整体
# 错移 8 小时（+08:00 写 09-14 00:10 会被算进 09-13）。
# 评审 A13-M4：完整 SQL 二选一，禁运行期字符串替换拼 SQL 片段。
_CHANNEL_AGGREGATE_SQL = """
                SELECT actual_model, model_id,
                       COUNT(*)                     AS calls,
                       SUM(status != 'success')     AS failed_calls,
                       SUM(COALESCE(prompt_tokens, 0))          AS prompt_tokens,
                       SUM(COALESCE(cache_creation_tokens, 0))  AS cache_creation_tokens,
                       SUM(COALESCE(cache_read_tokens, 0))      AS cache_read_tokens,
                       SUM(COALESCE(completion_tokens, 0))      AS completion_tokens,
                       SUM(COALESCE(total_tokens, 0))           AS total_tokens,
                       -- 取整只在聚合这一步做一次：逐行取整会把 0.219 毫厘这类单发成本
                       -- 冲成 0，相加后一天的账单整体塌向零（2026-09-25 实测撞出）。
                       CAST(ROUND(SUM(COALESCE(total_cost_micro,
                            total_cost_milli * 1000, 0)) / 1000.0) AS INTEGER)
                                                  AS total_cost_milli,
                       SUM(unpriced)                AS unpriced_calls
                FROM llm_call_records
                WHERE completed_at >= ? AND completed_at < ?
                GROUP BY actual_model, model_id
"""
_CHANNEL_AGGREGATE_SINCE_SQL = """
                SELECT actual_model, model_id,
                       COUNT(*)                     AS calls,
                       SUM(status != 'success')     AS failed_calls,
                       SUM(COALESCE(prompt_tokens, 0))          AS prompt_tokens,
                       SUM(COALESCE(cache_creation_tokens, 0))  AS cache_creation_tokens,
                       SUM(COALESCE(cache_read_tokens, 0))      AS cache_read_tokens,
                       SUM(COALESCE(completion_tokens, 0))      AS completion_tokens,
                       SUM(COALESCE(total_tokens, 0))           AS total_tokens,
                       -- 取整只在聚合这一步做一次：逐行取整会把 0.219 毫厘这类单发成本
                       -- 冲成 0，相加后一天的账单整体塌向零（2026-09-25 实测撞出）。
                       CAST(ROUND(SUM(COALESCE(total_cost_micro,
                            total_cost_milli * 1000, 0)) / 1000.0) AS INTEGER)
                                                  AS total_cost_milli,
                       SUM(unpriced)                AS unpriced_calls
                FROM llm_call_records
                WHERE completed_at >= ? AND completed_at < ?
                AND completed_at >= ?
                GROUP BY actual_model, model_id
"""


def aggregate_channel_usage(
    db_path: str,
    *,
    start_day: str,
    end_day: str,
    since_iso: str = "",
) -> dict[tuple[str, str], dict[str, int]]:
    """按 (实际模型名, 渠道 model_id) 只读聚合窗口内 ``llm_call_records``。

    报告侧「家族行 → 渠道子行」的数据源：账本每行本就保留渠道字段
    （provider_id/model_id = 渠道注册 id），这里按窗口聚合出每个渠道的
    调用数/失败数/token/费用，供 usage_monitor 把同模型跨渠道消耗拆到
    「实际服务的渠道」。failover 拨转后计费归因真实渠道即由此可追溯。

    - 只读连接（URI mode=ro），失败/库不存在返回 {}——报告注记缺渠道
      明细好过报错；WAL 下与写线程并发安全。
    - 日期过滤用 completed_at 范围比较（``>= start_day`` 且
      ``< 结束日次日``，上界开区间；completed_at 由
      ``datetime.now(zone).isoformat()`` 写入，前缀即本地日，ISO 文本
      字典序即时序）。不能用 ``date()``：它会把带时区偏移的时间戳换算
      成 UTC，本地日会被整体错移 8 小时（+08:00 写 09-14 00:10 会被算进
      09-13）。``since_iso`` 给定时附加 ``completed_at >= since_iso``
      文本比较（同构造器 ISO 文本，字典序即时序；恰好等于边界的行按
      ``.000`` 毫秒尾缀大于 ``+08:00`` 偏移尾缀被包含，与事件日志
      since 语义一致）。
    """
    results: dict[tuple[str, str], dict[str, int]] = {}
    try:
        if not str(db_path):
            return {}
        # 上界 = 结束日 + 1 天（开区间）；end_day 非法时 ValueError
        # 落入下方 except → 返回 {}（与旧实现空窗口结果一致）。
        end_exclusive = (
            datetime.date.fromisoformat(str(end_day)) + datetime.timedelta(days=1)
        ).isoformat()
        import pathlib

        connection = sqlite3.connect(
            f"file:{pathlib.Path(db_path).as_posix()}?mode=ro",
            uri=True,
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        try:
            params: list[str] = [str(start_day), end_exclusive]
            sql = _CHANNEL_AGGREGATE_SQL
            if since_iso:
                sql = _CHANNEL_AGGREGATE_SINCE_SQL
                params.append(str(since_iso))
            rows = connection.execute(sql, params).fetchall()
        finally:
            connection.close()
    except (sqlite3.Error, OSError, ValueError):
        return {}
    for row in rows:
        stats = {
            "calls": int(row["calls"] or 0),
            "failed_calls": int(row["failed_calls"] or 0),
            "prompt_tokens": int(row["prompt_tokens"] or 0),
            "cache_creation_tokens": int(row["cache_creation_tokens"] or 0),
            "cache_read_tokens": int(row["cache_read_tokens"] or 0),
            "completion_tokens": int(row["completion_tokens"] or 0),
            "total_tokens": int(row["total_tokens"] or 0),
            "cost_milli": int(row["total_cost_milli"] or 0),
            "unpriced_calls": int(row["unpriced_calls"] or 0),
        }
        pair = (str(row["actual_model"] or ""), str(row["model_id"] or ""))
        results[pair] = stats
    return results


# ==================== 主账单行账本口径（报告侧主行，F-1） ====================

# 与 _CHANNEL_AGGREGATE_SQL 的分组/过滤完全同构，唯一差别是把「取整到毫厘」
# 从 SQL 挪到 Python 的**家族聚合与总计聚合各一次**：主行与渠道子行同源
# （都是 llm_call_records 的微元求和），不再出现「主行逐行毫厘塌零、子行
# 微元如实」两套钱（SEAT-ATK-BILLING F-1，2026-09-28）。
_USAGE_WINDOW_SQL = """
                SELECT actual_model, model_id,
                       COUNT(*)                     AS calls,
                       SUM(COALESCE(prompt_tokens, 0))          AS prompt_tokens,
                       SUM(COALESCE(cache_creation_tokens, 0))  AS cache_creation_tokens,
                       SUM(COALESCE(cache_read_tokens, 0))      AS cache_read_tokens,
                       SUM(COALESCE(completion_tokens, 0))      AS completion_tokens,
                       SUM(COALESCE(total_tokens, 0))           AS total_tokens,
                       -- 微元求和（NULL 历史行按毫厘×1000 兜底），此处不取整。
                       SUM(COALESCE(total_cost_micro,
                            total_cost_milli * 1000, 0))        AS cost_micro,
                       SUM(unpriced)                AS unpriced_calls
                FROM llm_call_records
                WHERE completed_at >= ? AND completed_at < ?
                GROUP BY actual_model, model_id
"""
# 日内窗口版：usage_monitor 定时报告窗口是「上次报告时刻→now」的**日内**区间
# （13/18/23 点切），与渠道子行 `_CHANNEL_AGGREGATE_SINCE_SQL` 同构——只有
# 主行也按 since_iso 收窄，主行金额才与子行同窗口、同源，否则主行算全天、
# 子行算区间，等于把 F-1 的「两套钱」从「塌零」换成「窗口错配」。语义与
# `_CHANNEL_AGGREGATE_SINCE_SQL` 逐字一致（ISO 文本字典序即时序，同构造器）。
_USAGE_WINDOW_SINCE_SQL = _USAGE_WINDOW_SQL.replace(
    "WHERE completed_at >= ? AND completed_at < ?\n",
    "WHERE completed_at >= ? AND completed_at < ?\n                  AND completed_at >= ?\n",
)


def aggregate_usage_totals(
    db_path: str,
    *,
    start_day: str,
    end_day: str,
    since_iso: str = "",
) -> dict[str, Any] | None:
    """``/bot model usage`` 主账单行的账本聚合（与渠道子行同源）。

    返回与 ``runtime_event_log.aggregate_llm_usage_range`` **同键**的聚合 dict，
    但钱从 ``llm_call_records.total_cost_micro`` 来：先按 (实际模型, 渠道) 求
    微元和、折叠到家族键，**取整只在家族聚合与总计聚合各做一次**——旧主行读
    事件日志的逐行毫厘，亚毫厘单价每行取整为 0 ⇒ 日合计塌向零，且完全不认
    网关成本 ⇒ 主行总额 ≠ 渠道子行之和，账裂两处。

    - 家族键口径与渠道子行折叠逐字同式（``model_family_key(actual_model) or
      actual_model``）⇒ 主行家族与子行家族的配对关系不变。
    - 代表名：窗口内调用次数最多的原始写法（并列时优先与家族键同形者，再按
      token 量、名称稳定序）——与 ``build_model_rows`` 的选取一致。
    - 只读连接（URI mode=ro）；**读失败/库不可达返回 None**：主行调用方要
      区分「读不到」与「窗口真空」以便回落事件毫厘并注记口径，这与
      ``aggregate_channel_usage`` 的失败回 {}（子行可缺不可错）不同。
    - ``since_iso`` 给定时附加 ``completed_at >= since_iso``，把下界从「start_day
      00:00」收窄到报告窗口的日内起点——与 ``aggregate_channel_usage`` 的
      ``since_iso`` 逐字同构，令主行与其渠道子行**同窗口同源**（usage_monitor
      定时报告 13/18/23 点切即依赖此，否则主行算全天、子行算区间，两套钱）。
    """
    try:
        if not str(db_path):
            return None
        end_exclusive = (
            datetime.date.fromisoformat(str(end_day)) + datetime.timedelta(days=1)
        ).isoformat()
        import pathlib

        connection = sqlite3.connect(
            f"file:{pathlib.Path(db_path).as_posix()}?mode=ro",
            uri=True,
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        try:
            if str(since_iso):
                rows = connection.execute(
                    _USAGE_WINDOW_SINCE_SQL,
                    [str(start_day), end_exclusive, str(since_iso)],
                ).fetchall()
            else:
                rows = connection.execute(
                    _USAGE_WINDOW_SQL, [str(start_day), end_exclusive]
                ).fetchall()
        finally:
            connection.close()
    except (sqlite3.Error, OSError, ValueError):
        return None
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.pricing import (
        model_family_key,
    )

    families: dict[str, dict[str, Any]] = {}
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "calls": 0,
    }
    unpriced_calls = 0
    grand_micro = 0
    for row in rows:
        actual = str(row["actual_model"] or "")
        family = model_family_key(actual) or actual
        bucket = families.get(family)
        if bucket is None:
            bucket = {
                "prompt": 0, "completion": 0, "cache_read": 0, "cache_write": 0,
                "total": 0, "micro": 0, "calls": 0, "unpriced": 0,
                "variants": {}, "tokens_by_name": {},
            }
            families[family] = bucket
        calls = int(row["calls"] or 0)
        prompt = int(row["prompt_tokens"] or 0)
        completion = int(row["completion_tokens"] or 0)
        cache_read = int(row["cache_read_tokens"] or 0)
        cache_write = int(row["cache_creation_tokens"] or 0)
        total = int(row["total_tokens"] or 0)
        micro = int(row["cost_micro"] or 0)
        bucket["prompt"] += prompt
        bucket["completion"] += completion
        bucket["cache_read"] += cache_read
        bucket["cache_write"] += cache_write
        bucket["total"] += total
        bucket["micro"] += micro
        bucket["calls"] += calls
        bucket["unpriced"] += int(row["unpriced_calls"] or 0)
        bucket["variants"][actual] = bucket["variants"].get(actual, 0) + max(1, calls)
        bucket["tokens_by_name"][actual] = (
            bucket["tokens_by_name"].get(actual, 0) + total
        )
        totals["prompt_tokens"] += prompt
        totals["completion_tokens"] += completion
        totals["total_tokens"] += total
        totals["cache_read_tokens"] += cache_read
        totals["cache_write_tokens"] += cache_write
        totals["calls"] += calls
        unpriced_calls += int(row["unpriced_calls"] or 0)
        grand_micro += micro

    by_model: dict[str, int] = {}
    by_model_prompt: dict[str, int] = {}
    by_model_completion: dict[str, int] = {}
    by_model_cache_read: dict[str, int] = {}
    by_model_cache_write: dict[str, int] = {}
    by_model_cost_milli: dict[str, int] = {}
    by_model_calls: dict[str, int] = {}
    by_model_unpriced: dict[str, int] = {}
    for family, bucket in families.items():
        variants: dict[str, int] = bucket["variants"]
        representative = min(
            variants,
            key=lambda name: (
                0 if name.casefold() == family else 1,
                -variants[name],
                -int(bucket["tokens_by_name"].get(name, 0) or 0),
                name,
            ),
        )
        by_model[representative] = int(bucket["total"])
        by_model_prompt[representative] = int(bucket["prompt"])
        by_model_completion[representative] = int(bucket["completion"])
        by_model_cache_read[representative] = int(bucket["cache_read"])
        by_model_cache_write[representative] = int(bucket["cache_write"])
        # 取整只在家族聚合这一步做一次（微元 → 毫厘）。
        by_model_cost_milli[representative] = round(int(bucket["micro"]) / 1000)
        by_model_calls[representative] = int(bucket["calls"])
        by_model_unpriced[representative] = int(bucket["unpriced"])
    return {
        **totals,
        # 总计聚合处再一次、也是最后一次独立取整（不是家族毫厘相加：
        # 家族行取整误差不得传给总额）。
        "cost_milli": round(grand_micro / 1000),
        "by_model": by_model,
        "by_model_prompt": by_model_prompt,
        "by_model_completion": by_model_completion,
        "by_model_cache_read": by_model_cache_read,
        "by_model_cache_write": by_model_cache_write,
        "by_model_cost_milli": by_model_cost_milli,
        "by_model_calls": by_model_calls,
        "by_model_unpriced": by_model_unpriced,
        "unpriced_calls": unpriced_calls,
        "cost_micro": grand_micro,
    }


# ==================== 进程级单例（未显式注入时的默认 sink） ====================

_GLOBAL_SERVICE: LedgerService | None = None
_GLOBAL_LOCK = threading.Lock()
_GLOBAL_CLOSE_HOOK_REGISTERED = False


def peek_ledger_service() -> LedgerService | None:
    """只读探测进程级单例：**从不**按需建库、从不启动写线程。

    读数面（``/bot model usage`` 账本健康行）用它取丢行/写失败/归因让路
    计数——为看健康而创建写线程是把告警面变成副作用。单例不存在 ⇒ None。
    """
    return _GLOBAL_SERVICE


def get_ledger_service(db_path: str = "", *, config: object | None = None) -> LedgerService:
    """进程级单例（惰性创建）；显式传入不同 db_path 只告警并沿用现库。

    ``config`` 只用于**首次**构造时决定要不要接上网关归因反查口（B1）；
    单例已存在时不重读——与"装配期读一次、热改当轮不生效"的全仓口径一致。
    """
    global _GLOBAL_SERVICE, _GLOBAL_CLOSE_HOOK_REGISTERED
    with _GLOBAL_LOCK:
        resolved = str(db_path) if db_path else resolve_default_db_path()
        if _GLOBAL_SERVICE is None:
            _GLOBAL_SERVICE = LedgerService(
                resolved, attribution_lookup=_build_attribution_lookup(config)
            )
            if not _GLOBAL_CLOSE_HOOK_REGISTERED:
                _GLOBAL_CLOSE_HOOK_REGISTERED = True
                atexit.register(_close_global_service)
        elif _GLOBAL_SERVICE.db_path != resolved:
            logger.warning(
                "llm ledger service already opened at %s; "
                "ignoring different db path %s",
                _GLOBAL_SERVICE.db_path,
                resolved,
            )
        return _GLOBAL_SERVICE


def _build_attribution_lookup(config: object | None) -> AttributionLookup | None:
    """按配置构造批量反查口；开关关 / DSN 缺 / 建口失败 ⇒ None（不启用）。"""
    if config is None:
        return None
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine import (
            axonhub_attribution,
        )

        resolver = axonhub_attribution.AttributionResolver.from_config(config)
        if resolver is None:
            return None
        return axonhub_attribution.make_batch_lookup(resolver)
    except Exception:
        logger.warning("llm ledger attribution hookup failed", exc_info=True)
        return None


def _close_global_service() -> None:
    service = _GLOBAL_SERVICE
    if service is not None:
        try:
            service.close()
        except Exception:  # 退出冲刷失败不再传播。
            logger.debug("llm ledger close on exit failed", exc_info=True)


def resolve_call_record_sink(
    injected: CallRecordSink | None,
    config: object | None = None,
) -> CallRecordSink | None:
    """sink 解析：显式注入优先；否则读开关，默认关（关 = None = 不记账）。"""
    if injected is not None:
        return injected
    if not ledger_enabled(config):
        return None
    return get_ledger_service(config=config)


def emit_call_record(
    *,
    sink: CallRecordSink | None,
    config: object | None = None,
    draft: LLMCallDraft,
) -> None:
    """router 出口统一入口：解析 sink → submit；吞掉一切异常只打日志。"""
    try:
        effective = resolve_call_record_sink(sink, config)
        if effective is None:
            return
        effective.submit(draft)
    except Exception:
        logger.debug("llm call record emit failed", exc_info=True)


__all__ = [
    "ATTRIBUTION_COLUMNS",
    "ATTRIBUTION_SKIPPED",
    "MAX_PENDING_RECORDS",
    "AttributionLookup",
    "CallRecordSink",
    "LLMCallDraft",
    "LedgerService",
    "aggregate_channel_usage",
    "aggregate_usage_totals",
    "apply_attribution",
    "build_call_draft",
    "emit_call_record",
    "gateway_cost_trust",
    "get_ledger_service",
    "ledger_enabled",
    "peek_ledger_service",
    "redact_error_summary",
    "resolve_call_record_sink",
    "resolve_default_db_path",
]

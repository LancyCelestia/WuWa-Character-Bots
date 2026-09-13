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
import json
import logging
import os
import queue
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from plugins.bot_unified_runtime.llm.providers import safe_llm_finish_reason

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
    output_cost_milli: int | None = None
    total_cost_milli: int | None = None
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

    @property
    def attempts_json(self) -> str:
        try:
            return json.dumps(list(self.attempts), ensure_ascii=False)
        except (TypeError, ValueError):
            return "[]"


class CallRecordSink(Protocol):
    """router 唯一依赖的记账协议（§4.1.1）：submit 绝不抛出。"""

    def submit(self, draft: LLMCallDraft) -> None:
        """提交一条账本行草稿；实现必须自行吞异常（失败不阻塞聊天）。"""
        ...  # pragma: no cover


# ==================== draft 组装 ====================


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
        from plugins.bot_unified_runtime.audit.logger import redact_private_debug

        text = redact_private_debug(text)
    except Exception:  # 脱敏模块不可用时退回原文截断。
        logger.debug("llm ledger redact helper unavailable", exc_info=True)
    return text[:ERROR_SUMMARY_MAX_CHARS]


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
    pricing_source = "unknown"
    unpriced = 1 if (total_tokens is not None and total_tokens > 0) else 0
    if price_in is not None and price_out is not None:
        cached_read = cache_read_tokens or 0
        cached_write = cache_creation_tokens or 0
        prompt = prompt_tokens or 0
        billed_input = max(0, prompt - cached_read - cached_write)
        creation_price = (
            price_cache_creation if price_cache_creation is not None else price_in
        )
        read_price = price_cache_read if price_cache_read is not None else price_in
        input_cost_milli = round(
            billed_input * price_in / 1000 + cached_write * creation_price / 1000
        )
        cache_read_cost_milli = round(cached_read * read_price / 1000)
        output_cost_milli = round((completion_tokens or 0) * price_out / 1000)
        total_cost_milli = (
            input_cost_milli + cache_read_cost_milli + output_cost_milli
        )
        pricing_source = "channel_spec"
        unpriced = 0
    # 按次计费渠道（0.18元/请求类）：与 token 价并存则叠加，单独存在时
    # 独立成账（token 列保持 NULL）。
    per_call_milli = (
        round(price_per_call * 1000) if price_per_call is not None else None
    )
    if per_call_milli is not None:
        total_cost_milli = (total_cost_milli or 0) + per_call_milli
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
        pricing_source=pricing_source,
        unpriced=unpriced,
        attempts=list(attempts or []),
        finish_reason=safe_finish,
        status=str(status or ""),
        error_kind=str(error_kind or ""),
        error_summary=redact_error_summary(error_summary),
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
    ) -> None:
        self.db_path = str(db_path)
        self.flush_batch_size = max(1, int(flush_batch_size))
        self.flush_interval_seconds = max(0.05, float(flush_interval_seconds))
        self.dropped_count = 0
        self.write_error_count = 0
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
                try:
                    self._pending.get_nowait()
                except queue.Empty:
                    pass
                self.dropped_count += 1
                logger.warning(
                    "llm ledger queue full; dropped oldest (total dropped=%d)",
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
            connection.commit()

    def _write_batch(self, rows: list[LLMCallDraft], *, timeout: float = 5.0) -> int:
        if not rows:
            return 0
        del timeout  # sqlite3 timeout 已在连接级设置；保留参数给调用方语义。
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
                row.total_cost_milli,
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
    total_cost_milli, currency, pricing_source, unpriced,
    attempts_json, attempts_count, finish_reason,
    status, error_kind, error_summary,
    source, schema_ver, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    total_cost_milli      INTEGER,
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
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_call_started ON llm_call_records (started_at);
CREATE INDEX IF NOT EXISTS idx_llm_call_model   ON llm_call_records (model_id, started_at);
CREATE INDEX IF NOT EXISTS idx_llm_call_session ON llm_call_records (session_id, started_at);
CREATE INDEX IF NOT EXISTS idx_llm_call_request ON llm_call_records (request_id);

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
    - 日期过滤用 ``substr(completed_at, 1, 10)``（completed_at 由
      ``datetime.now(zone).isoformat()`` 写入，前缀即本地日）。不能用
      ``date()``：它会把带时区偏移的时间戳换算成 UTC，本地日会被整体
      错移 8 小时（+08:00 写 09-14 00:10 会被算进 09-13）。
      ``since_iso`` 给定时附加 ``completed_at >= since_iso`` 文本比较
      （同构造器 ISO 文本，字典序即时序；恰好等于边界的行按 ``.000``
      毫秒尾缀大于 ``+08:00`` 偏移尾缀被包含，与事件日志 since 语义一致）。
    """
    results: dict[tuple[str, str], dict[str, int]] = {}
    try:
        if not str(db_path):
            return {}
        import pathlib

        connection = sqlite3.connect(
            f"file:{pathlib.Path(db_path).as_posix()}?mode=ro",
            uri=True,
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        try:
            sql = """
                SELECT actual_model, model_id,
                       COUNT(*)                     AS calls,
                       SUM(status != 'success')     AS failed_calls,
                       SUM(COALESCE(prompt_tokens, 0))          AS prompt_tokens,
                       SUM(COALESCE(cache_creation_tokens, 0))  AS cache_creation_tokens,
                       SUM(COALESCE(cache_read_tokens, 0))      AS cache_read_tokens,
                       SUM(COALESCE(completion_tokens, 0))      AS completion_tokens,
                       SUM(COALESCE(total_tokens, 0))           AS total_tokens,
                       SUM(COALESCE(total_cost_milli, 0))       AS total_cost_milli,
                       SUM(unpriced)                AS unpriced_calls
                FROM llm_call_records
                WHERE substr(completed_at, 1, 10) BETWEEN ? AND ?
                GROUP BY actual_model, model_id
            """
            # 评审 A13-M4：完整 SQL 二选一，禁运行期字符串替换拼 SQL 片段。
            params: list[str] = [str(start_day), str(end_day)]
            if since_iso:
                sql = """
                SELECT actual_model, model_id,
                       COUNT(*)                     AS calls,
                       SUM(status != 'success')     AS failed_calls,
                       SUM(COALESCE(prompt_tokens, 0))          AS prompt_tokens,
                       SUM(COALESCE(cache_creation_tokens, 0))  AS cache_creation_tokens,
                       SUM(COALESCE(cache_read_tokens, 0))      AS cache_read_tokens,
                       SUM(COALESCE(completion_tokens, 0))      AS completion_tokens,
                       SUM(COALESCE(total_tokens, 0))           AS total_tokens,
                       SUM(COALESCE(total_cost_milli, 0))       AS total_cost_milli,
                       SUM(unpriced)                AS unpriced_calls
                FROM llm_call_records
                WHERE substr(completed_at, 1, 10) BETWEEN ? AND ?
                AND completed_at >= ?
                GROUP BY actual_model, model_id
            """
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


# ==================== 进程级单例（未显式注入时的默认 sink） ====================

_GLOBAL_SERVICE: LedgerService | None = None
_GLOBAL_LOCK = threading.Lock()
_GLOBAL_CLOSE_HOOK_REGISTERED = False


def get_ledger_service(db_path: str = "") -> LedgerService:
    """进程级单例（惰性创建）；显式传入不同 db_path 只告警并沿用现库。"""
    global _GLOBAL_SERVICE, _GLOBAL_CLOSE_HOOK_REGISTERED
    with _GLOBAL_LOCK:
        resolved = str(db_path) if db_path else resolve_default_db_path()
        if _GLOBAL_SERVICE is None:
            _GLOBAL_SERVICE = LedgerService(resolved)
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
    return get_ledger_service()


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
    "MAX_PENDING_RECORDS",
    "CallRecordSink",
    "LLMCallDraft",
    "LedgerService",
    "aggregate_channel_usage",
    "build_call_draft",
    "emit_call_record",
    "get_ledger_service",
    "ledger_enabled",
    "redact_error_summary",
    "resolve_call_record_sink",
    "resolve_default_db_path",
]

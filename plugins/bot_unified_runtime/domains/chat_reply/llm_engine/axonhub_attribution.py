"""AxonHub 网关归因反查（B1，2026-09-25 用户裁定 C）。

bot 侧注册表只指向网关，**看不见网关内部实际选了哪条上游渠道**，也拿不到
首字时间与四项分项价。本模块按关联键去网关库里把这些事实取回来。

关联键（实测，勿再猜）：响应体 ``id`` == ``requests.external_id``。
响应头 ``Ah-Request-Id``（``ar-<uuid>`` 形态）**不落库**——``requests.trace_id``
是 bigint，用它会撞 ``22P02 invalid input syntax for type bigint``。

三条硬约束：
1. **只读**：连接用 ``axonhub_ro`` 角色，库里只授了五张表的 SELECT，写会被拒。
2. **绝不在回复路径上**：调用方是账本写线程（``ledger.LedgerService`` 的 flush），
   不是 pipeline；本模块任何失败都只降级成 ``attribution_status='unavailable'``。
3. **DSN 缺项即不建**：``from_config`` 在开关关闭或 host/user 任一为空时返回
   ``None``（fail-closed），调用方据此完全不启用——不存在"看起来开了其实没连"。
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

logger = logging.getLogger(__name__)

# 配置面（七枚键）。声明在 Config 上是硬要求：`extra="ignore"` 会把未声明的
# BOT_* 静默丢掉，读点永远拿到缺省——本仓这类事故已三次（sync_drift 七键、
# 紧急域、potccv）。
ATTRIBUTION_CONFIG_FIELDS: tuple[str, ...] = (
    "bot_axonhub_attribution_enabled",
    "bot_axonhub_db_host",
    "bot_axonhub_db_port",
    "bot_axonhub_db_database",
    "bot_axonhub_db_user",
    "bot_axonhub_db_password",
    "bot_axonhub_attribution_timeout_seconds",
)

# 一条网关请求 = 若干次上游尝试。逐跳按 e.id 升序＝时间序。
ATTRIBUTION_SQL = """
SELECT DISTINCT ON (r.external_id)
       r.external_id                AS external_id,
       r.id                         AS gateway_request_pk,
       wc.name                      AS channel_name,
       r.model_id                   AS gateway_model_id,
       r.status                     AS request_status,
       r.metrics_latency_ms         AS latency_ms,
       r.metrics_first_token_latency_ms AS first_token_latency_ms,
       u.total_cost                 AS total_cost,
       u.cost_items                 AS cost_items,
       u.prompt_tokens              AS prompt_tokens,
       u.prompt_cached_tokens       AS prompt_cached_tokens,
       u.prompt_write_cached_tokens AS prompt_write_cached_tokens,
       u.completion_tokens          AS completion_tokens,
       (SELECT json_agg(json_build_object(
                   'channel', ec.name,
                   'model_id', e.model_id,
                   'status', e.status,
                   'code', e.response_status_code,
                   'latency_ms', e.metrics_latency_ms,
                   'error', left(coalesce(e.error_message, ''), 200))
               ORDER BY e.id)
          FROM request_executions e
          LEFT JOIN channels ec ON ec.id = e.channel_id
         WHERE e.request_id = r.id) AS hops
  FROM requests r
  LEFT JOIN usage_logs u ON u.request_id = r.id
  LEFT JOIN channels wc ON wc.id = r.channel_id
 WHERE r.external_id = ANY($1)
   AND r.external_id <> ''
 ORDER BY r.external_id, r.id DESC
"""

# 滚动窗里攒这么多枚坏事件就静默一段时间：网关库不在（没装 / 没起 / 换机）时，
# 每条账本行都去撞一次连接会把写线程拖慢，而这一点收益是零。
_CIRCUIT_TRIP_AFTER = 3
_CIRCUIT_COOLDOWN_SECONDS = 300.0
# 坏事件的滚动窗长（≠ 静默时长）：窗外的旧故障自然过期，不许和新故障凑票。
# 只数「连续」异常的那版旧熔断会被一次成功清零，于是「慢而成功」这种
# 真正拖垮写吞吐的形态永不 trip（SEAT-ATK-BILLING F-3，2026-09-28）。
_CIRCUIT_EVENT_WINDOW_SECONDS = 600.0
# 一次反查用掉时长预算的这么多比例即算「慢」——进了窗但不算故障。
_SLOW_SUCCESS_RATIO = 0.8
# 单批最多反查多少条（写线程一批 ≤ flush_batch_size，这里是防御性上限）。
_MAX_IDS_PER_LOOKUP = 200

# 分项 itemCode → 账本列名的映射在 ledger 侧，本模块只原样搬运。
_ITEM_COST_SUBTOTAL_KEYS = ("subtotal", "cost", "amount")


@dataclass
class HopFact:
    """一次上游尝试（request_executions 的一行）。"""

    channel: str = ""
    model_id: str = ""
    status: str = ""
    status_code: int | None = None
    latency_ms: int | None = None
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "model_id": self.model_id,
            "status": self.status,
            "code": self.status_code,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class Attribution:
    """网关对一次请求的完整口径（缺项保持 None，不填 0 冒充）。"""

    remote_request_id: str = ""
    gateway_channel: str = ""
    gateway_model_id: str = ""
    status: str = ""
    latency_ms: int | None = None
    first_token_latency_ms: int | None = None
    hops: list[HopFact] = field(default_factory=list)
    prompt_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    completion_tokens: int | None = None
    total_cost_milli: int | None = None
    # 微元（元 ×1e6）：跨进程传的成本原语，单发成本常在亚毫厘量级。
    total_cost_micro: int | None = None
    # itemCode → 毫厘（元 ×1000 四舍五入）。只含网关真回了的项。
    item_cost_milli: dict[str, int] = field(default_factory=dict)


# ==================== 解析（纯函数，可离线测） ====================


def _opt_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _micro(value: object) -> int | None:
    """元 → **微元**（元 ×1,000,000）。非数（含 None 与真正的垃圾串）一律 None，不当 0 用。

    为什么不是毫厘：实测一发 gemini 短回复 `usage.cost = 0.000219` 元 = 0.219 毫厘，
    取整到毫厘就是 **0**——按行取整再把 500 行相加，一天的账单会整体塌成接近零。
    所以跨进程传的成本原语一律用微元，"什么时候才取整"交给落库与聚合那两层：
    单行仍可存毫厘（兼容旧列），聚合处最后一次性换算。

    ⚠ ``cost_items[].subtotal`` 实测是**字符串**（``"0.0000009"``）——jsonb 里的数字
    经驱动解码后带引号，这是网关既有形态不是脏数据，所以数字串必须吃；
    只认 float/int 会把四项分项价全判成"没有"，等于 B1 白做。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    # inf / -inf / nan 都能被 float() 解析成功，却会在 round(number * 1e6) 抛
    # OverflowError / ValueError——抛穿出去会被 lookup 记成一次「故障」，脏数据
    # 因此自己攒够熔断票，把「钱读不准」升级成「归因整体静默」。非有限值一律
    # 当「没有这个价」（parse_rows 的「永不抛」承诺由这一行走通）。
    if not math.isfinite(number):
        return None
    return round(number * 1_000_000)


def _milli_from_micro(micro: int | None) -> int | None:
    """微元 → 毫厘（只为兼容既有列，不作计算中间量）。"""
    if micro is None:
        return None
    return round(micro / 1000)


def _as_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _jsonish(value: object) -> Any:
    """asyncpg 未装 jsonb codec 时会回字符串；两种形态都吃。"""
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return None
    return value


def _parse_hops(value: object) -> list[HopFact]:
    payload = _jsonish(value)
    if not isinstance(payload, list):
        return []
    hops: list[HopFact] = []
    for item in payload:
        row = _as_mapping(item)
        code = row.get("code")
        hops.append(
            HopFact(
                channel=str(row.get("channel") or ""),
                model_id=str(row.get("model_id") or ""),
                status=str(row.get("status") or ""),
                status_code=_opt_int(code),
                latency_ms=_opt_int(row.get("latency_ms")),
                error=redact_local_secrets(str(row.get("error") or "")),
            )
        )
    return hops


def _parse_cost_items(value: object) -> tuple[dict[str, int], int | None]:
    """cost_items → ({itemCode: 毫厘}, 合计毫厘)。

    合计只信网关自己给的 total_cost（``rows["total_cost"]``），不从分项相加：
    分项各自四舍五入到整数毫厘，相加会与合计差 1–2 毫厘，报表对不上时
    说不清是谁错了。
    """
    payload = _jsonish(value)
    if not isinstance(payload, list):
        return {}, None
    items: dict[str, int] = {}
    for entry in payload:
        row = _as_mapping(entry)
        code = str(row.get("itemCode") or row.get("item_code") or "")
        if not code:
            continue
        subtotal = next(
            (row.get(key) for key in _ITEM_COST_SUBTOTAL_KEYS if row.get(key) is not None),
            None,
        )
        milli = _milli_from_micro(_micro(subtotal))
        if milli is not None:
            items[code] = milli
    return items, None


def parse_rows(ids: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> dict[str, Attribution]:
    """把查询结果行转成 {关联键: Attribution}；任何脏值只降级不抛。"""
    wanted = {str(i) for i in ids if i}
    out: dict[str, Attribution] = {}
    for raw in rows:
        row = _as_mapping(raw)
        key = str(row.get("external_id") or "")
        if not key or key not in wanted:
            continue
        item_cost, _ = _parse_cost_items(row.get("cost_items"))
        total_micro = _micro(row.get("total_cost"))
        out[key] = Attribution(
            remote_request_id=key,
            gateway_channel=str(row.get("channel_name") or ""),
            gateway_model_id=str(row.get("gateway_model_id") or ""),
            status=str(row.get("request_status") or ""),
            latency_ms=_opt_int(row.get("latency_ms")),
            first_token_latency_ms=_opt_int(row.get("first_token_latency_ms")),
            hops=_parse_hops(row.get("hops")),
            prompt_tokens=_opt_int(row.get("prompt_tokens")),
            cache_read_tokens=_opt_int(row.get("prompt_cached_tokens")),
            cache_creation_tokens=_opt_int(row.get("prompt_write_cached_tokens")),
            completion_tokens=_opt_int(row.get("completion_tokens")),
            total_cost_micro=total_micro,
            total_cost_milli=_milli_from_micro(total_micro),
            item_cost_milli=item_cost,
        )
    return out


# ==================== 反查器 ====================


class AttributionResolver:
    """按关联键批量反查网关库；对外只有一个永不抛出的 ``lookup``。

    ``fetch`` 是注入缝：测试给纯函数，生产走 :meth:`_fetch_via_asyncpg`。
    """

    def __init__(
        self,
        *,
        dsn: Mapping[str, Any],
        timeout_seconds: float = 3.0,
        fetch: Callable[[list[str]], Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self._dsn = dict(dsn)
        self.timeout_seconds = max(0.05, float(timeout_seconds))
        self._fetch = fetch
        self.last_error = ""
        self.matched_count = 0
        self.miss_count = 0
        # 坏事件时刻表（滚动窗内）：异常与「慢而成功」同账，快成功不进账。
        self._circuit_events: list[float] = []
        self._circuit_open_until = 0.0

    # ---- 构造 ----

    @classmethod
    def from_config(cls, config: object | None) -> AttributionResolver | None:
        """开关开 ∧ DSN 齐 ⇒ 构造；否则 ``None``（fail-closed，绝不半开）。"""
        if config is None:
            return None
        if not bool(getattr(config, "bot_axonhub_attribution_enabled", False)):
            return None
        host = str(getattr(config, "bot_axonhub_db_host", "") or "").strip()
        user = str(getattr(config, "bot_axonhub_db_user", "") or "").strip()
        if not host or not user:
            logger.warning(
                "axonhub attribution enabled but host/user missing; lookup disabled"
            )
            return None
        database = str(getattr(config, "bot_axonhub_db_database", "") or "axonhub").strip()
        port_raw = getattr(config, "bot_axonhub_db_port", 5432)
        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            port = 5432
        timeout_raw = getattr(config, "bot_axonhub_attribution_timeout_seconds", 3.0)
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError):
            timeout = 3.0
        return cls(
            dsn={
                "host": host,
                "port": port,
                "database": database,
                "user": user,
                "password": str(getattr(config, "bot_axonhub_db_password", "") or ""),
            },
            timeout_seconds=timeout,
        )

    def dsn_summary(self) -> dict[str, Any]:
        """脱敏摘要：日志与诊断卡只准用这个，绝不整份打印 dsn。"""
        return {
            "host": self._dsn.get("host", ""),
            "port": self._dsn.get("port", ""),
            "database": self._dsn.get("database", ""),
            "user": self._dsn.get("user", ""),
        }

    def __repr__(self) -> str:  # pragma: no cover - 防凭据经 repr 外泄
        summary = self.dsn_summary()
        return (
            f"AttributionResolver(host={summary['host']!r}, port={summary['port']!r}, "
            f"database={summary['database']!r}, user={summary['user']!r}, "
            f"timeout_seconds={self.timeout_seconds!r})"
        )

    # ---- 对外 ----

    def lookup(self, ids: Sequence[str]) -> dict[str, Attribution]:
        """批量反查。**永不抛出**：失败返回空 dict 并记 last_error。"""
        wanted = [str(i) for i in ids if i]
        if not wanted:
            return {}
        if time.monotonic() < self._circuit_open_until:
            self.last_error = "circuit_open"
            return {}
        wanted = wanted[:_MAX_IDS_PER_LOOKUP]
        started = time.monotonic()
        try:
            rows = self._fetch(wanted) if self._fetch is not None else self._fetch_live(wanted)
            found = parse_rows(wanted, list(rows))
        except Exception as exc:  # noqa: BLE001 - 归因故障绝不连累账本与聊天
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            self._record_circuit_event(self.last_error)
            return {}
        # 慢而成功也进熔断窗：反查同步钉在账本写线程每批前，拖满预算的
        # 成功与故障同样压吞吐。但它**绝不置 last_error**——make_batch_lookup
        # 据 last_error 把整批判成 unavailable，而那一批是真查到了的，
        # 写成故障就是假事实。
        elapsed = time.monotonic() - started
        if elapsed >= self.timeout_seconds * _SLOW_SUCCESS_RATIO:
            self._record_circuit_event(f"slow {elapsed:.2f}s >= budget")
        self.matched_count += len(found)
        self.miss_count += max(0, len(wanted) - len(found))
        return found

    def _record_circuit_event(self, reason: str) -> None:
        """记一枚坏事件并按滚动窗判静默：窗外的旧故障先过期，不与新故障凑票。

        「一次成功清零」的旧口径已被淘汰——快成功零记分也不冲抵在案故障，
        否则 fail/success 交替就永不 trip，而反压链的正中间那一环就是这个洞。
        """
        now = time.monotonic()
        self._circuit_events = [
            stamp
            for stamp in self._circuit_events
            if now - stamp <= _CIRCUIT_EVENT_WINDOW_SECONDS
        ]
        self._circuit_events.append(now)
        if len(self._circuit_events) < _CIRCUIT_TRIP_AFTER:
            return
        self._circuit_events.clear()
        self._circuit_open_until = now + _CIRCUIT_COOLDOWN_SECONDS
        logger.warning(
            "axonhub attribution degraded: %d bad events within %.0fs; "
            "pausing lookups for %.0fs (%s)",
            _CIRCUIT_TRIP_AFTER,
            _CIRCUIT_EVENT_WINDOW_SECONDS,
            _CIRCUIT_COOLDOWN_SECONDS,
            reason,
        )

    # ---- 生产传输 ----

    def _fetch_live(self, ids: list[str]) -> Sequence[Mapping[str, Any]]:
        import asyncio

        return asyncio.run(self._fetch_async(ids))

    async def _fetch_async(self, ids: list[str]) -> list[dict[str, Any]]:
        import asyncio

        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - 缺库属环境事实
            raise RuntimeError("asyncpg 未安装，无法反查网关库") from exc

        async def work() -> list[dict[str, Any]]:
            connection = await asyncpg.connect(
                host=self._dsn.get("host"),
                port=int(self._dsn.get("port") or 5432),
                user=self._dsn.get("user"),
                password=self._dsn.get("password"),
                database=self._dsn.get("database"),
                timeout=self.timeout_seconds,
            )
            try:
                # jsonb/json 默认回字符串；这里统一解成对象，解析层两种都认。
                for type_name in ("jsonb", "json"):
                    await connection.set_type_codec(
                        type_name,
                        schema="pg_catalog",
                        encoder=json.dumps,
                        decoder=json.loads,
                        format="text",
                    )
                records = await connection.fetch(ATTRIBUTION_SQL, ids)
                return [dict(record) for record in records]
            finally:
                await connection.close()

        return await asyncio.wait_for(work(), timeout=self.timeout_seconds + 1.0)


def make_batch_lookup(
    resolver: AttributionResolver,
) -> Callable[[Sequence[str]], dict[str, Attribution] | None]:
    """把 resolver 包成账本要的批反查口：**查不成返回 None**，与「查了但没有」分开。

    ``resolver.lookup`` 自己永不抛（失败回空 dict），但空 dict 有两种成因：
    库不通 / 熔断中，和「这批键网关真没记到」。账本的 ``attribution_status``
    要区分 ``unavailable`` 与 ``miss``，所以这里用 ``last_error`` 把两者拆开——
    否则网关停机一晚，第二天报表会把「没查」读成「这批请求没有渠道」，
    那是比空白更糟的假事实。
    """

    def lookup(ids: Sequence[str]) -> dict[str, Attribution] | None:
        resolver.last_error = ""
        found = resolver.lookup(list(ids))
        if resolver.last_error:
            return None
        return found

    return lookup

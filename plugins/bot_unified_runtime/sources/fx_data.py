"""汇率数据源（Task 4 全局审计 + 快查批量链路）：双源设计。

**主源（快查批量链路，2026-09-12 主代理 curl 实测核验）**：东财
``push2 ulist.np/get?fltt=2``，字段 ``f2``=汇率 / ``f3``=涨跌% / ``f4``=涨跌额 /
``f12``=代码 / ``f13``=市场号 / ``f14``=名称 / ``f18``=昨收。已验证 secid：

- ``133.USDCNH`` 美元兑离岸人民币（现货，USD/CNY 主源）；
- ``119.USDJPY/EURUSD/GBPUSD/USDKRW/USDHKD/USDSGD`` 直盘现货；
- ``120.USDCNYC/EURCNYC/JPYCNYC/HKDCNYC`` 人民币中间价（备用语义；
  JPYCNYC 是 **100 日元** 口径 → ``unit_base=100``）。

东财外汇的日 K 在 119/120/133 板块实测全部为空 → ``FxRate.history`` 恒为
空元组，能力层展示「暂无历史走势数据」。``USD/TWD``、``USD/MOP``、
``USD/AED`` 在东财 suggest 实测查无结果 → 登记进 ``FX_UNAVAILABLE_PAIRS``
（覆盖表见 ``fx_pair_availability``），由能力层展示「暂无数据」，绝不臆造。

**备选源（provenance 快照链路）**：``open.er-api.com/v6/latest/{base}``
（免 key、覆盖面广）。**诚实边界：该端点在主代理环境实测同样不可达**，
``fetch_fx_snapshot`` 保持对外签名不变（capabilities/fx 按它对接），内部仍
走 er-api 出口、全部解析按 fixture 防御式实现：缺币种进
``missing_currencies`` 显式列出，绝不补 0；整体失败 ``status=unavailable``。

其它基准货币间的交叉价用 ``cross_rate_from_usd`` 纯函数按 USD 三角换算
（离线可验证），换不出给 None，不硬凑。两条链路任何失败都绝不抛异常。
"""

from __future__ import annotations

import re
import time
import urllib.parse
from collections.abc import Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from plugins.bot_unified_runtime.contracts.finance import (
    CurrencyQuote,
    FinanceDataStatus,
    FxRate,
    FxRateSnapshot,
    status_or_unknown,
)
from plugins.bot_unified_runtime.sources.market_data import (
    empty_backoff_sleep,
    retry_on_empty_enabled,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import http_get_json

BASE_CURRENCY = "USD"

# 计划要求的 11 个币种（含基准）；展示顺序即此顺序。
SUPPORTED_CURRENCIES: tuple[str, ...] = (
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "KRW",
    "TWD",
    "CNY",
    "HKD",
    "SGD",
    "MOP",
    "AED",
)

_FX_URL = "https://open.er-api.com/v6/latest/{base}"
_MAX_PAYLOAD_BYTES = 1024 * 1024
_FX_SOURCE = "open.er-api.com"
_RATE_TYPE = "mid"  # 免费源给的是参考中间价，不是可成交价


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _fetch_fx_payload(base: str, timeout: float) -> Any:
    """汇率单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    return http_get_json(
        _FX_URL.format(base=urllib.parse.quote(base.strip().upper())),
        timeout=max(1.0, float(timeout)),
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


def _parse_updated_at(payload: dict[str, Any]) -> datetime | None:
    """er-api 风格的 ``time_last_update_utc``；解析失败返回 None 不硬造。"""
    raw = payload.get("time_last_update_utc") or payload.get("time_last_update_unix")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = parsedate_to_datetime(raw.strip())
        except (TypeError, ValueError):
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def build_snapshot_from_payload(
    payload: Any,
    *,
    base: str = BASE_CURRENCY,
    targets: tuple[str, ...] | list[str] | None = None,
) -> FxRateSnapshot:
    """把上游 payload 解析成快照；缺币/坏包络全部走状态，绝不造 0。"""
    wanted = tuple(
        code.strip().upper()
        for code in (targets if targets is not None else SUPPORTED_CURRENCIES)
        if code.strip().upper() != base
    )
    rates_obj = payload.get("rates") if isinstance(payload, dict) else None
    quotes: list[CurrencyQuote] = []
    missing: list[str] = []
    if isinstance(rates_obj, dict):
        normalized: dict[str, float] = {}
        for code, value in rates_obj.items():
            rate = value if isinstance(value, (int, float)) else None
            if isinstance(value, str):
                try:
                    rate = float(value)
                except ValueError:
                    rate = None
            if isinstance(rate, float) and rate > 0:
                normalized[str(code).strip().upper()] = rate
        for code in wanted:
            rate = normalized.get(code)
            if rate is None:
                missing.append(code)
                continue
            quotes.append(
                CurrencyQuote(
                    base_currency=base,
                    quote_currency=code,
                    rate=rate,
                    rate_type=_RATE_TYPE,
                    as_of=_parse_updated_at(payload) if isinstance(payload, dict) else None,
                    source=_FX_SOURCE,
                    status=FinanceDataStatus.OK,
                    delayed=True,
                    note="",
                )
            )
    else:
        missing = list(wanted)
    if not quotes:
        return FxRateSnapshot(
            base_currency=base,
            quotes=[],
            missing_currencies=missing or list(wanted),
            source=_FX_SOURCE,
            as_of=None,
            status=FinanceDataStatus.UNAVAILABLE,
            delayed=True,
            note="上游未返回可用汇率（网络失败或包络异常）",
        )
    status = FinanceDataStatus.OK if not missing else FinanceDataStatus.DEGRADED
    return FxRateSnapshot(
        base_currency=base,
        quotes=quotes,
        missing_currencies=missing,
        source=_FX_SOURCE,
        as_of=_parse_updated_at(payload),
        status=status,
        delayed=True,
        note="" if not missing else f"上游缺 {len(missing)} 个币种报价",
    )


def fetch_fx_snapshot(
    base: str = BASE_CURRENCY,
    targets: tuple[str, ...] | list[str] | None = None,
    timeout_seconds: float = 6.0,
) -> FxRateSnapshot:
    """拉取汇率快照；任何失败走 UNAVAILABLE 状态，绝不抛异常。"""
    base_upper = (base or BASE_CURRENCY).strip().upper() or BASE_CURRENCY
    wanted = tuple(
        code.strip().upper()
        for code in (targets if targets is not None else SUPPORTED_CURRENCIES)
        if code.strip().upper() != base_upper
    )
    try:
        payload = _fetch_fx_payload(base_upper, timeout_seconds)
    except Exception as exc:  # noqa: BLE001 - 汇率失败静默降级。
        return FxRateSnapshot(
            base_currency=base_upper,
            quotes=[],
            missing_currencies=list(wanted),
            source=_FX_SOURCE,
            as_of=None,
            status=FinanceDataStatus.UNAVAILABLE,
            delayed=True,
            note=f"汇率源拉取失败：{type(exc).__name__}",
        )
    return build_snapshot_from_payload(payload, base=base_upper, targets=wanted or None)


def cross_rate_from_usd(
    usd_table: dict[str, float] | None,
    base: str,
    quote: str,
) -> float | None:
    """以 USD 为桥的三角交叉价：base→quote = table[quote]/table[base]。

    任何输入缺失/非法（≤0）返回 None——换不出来就承认换不出来。
    """
    if not isinstance(usd_table, dict):
        return None
    base_rate = usd_table.get((base or "").strip().upper())
    quote_rate = usd_table.get((quote or "").strip().upper())
    for value in (base_rate, quote_rate):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or value <= 0
        ):
            return None
    result = float(quote_rate) / float(base_rate)  # type: ignore[arg-type]
    return result if result > 0 else None


def format_fx_snapshot_brief(snapshot: FxRateSnapshot) -> str:
    """汇率纯文本快报（provenance 快照链路）：基准货币、中间价口径、
    延迟状态、缺币说明齐全。快查批量链路见 ``format_fx_brief``。"""
    status = status_or_unknown(snapshot.status)
    if status == FinanceDataStatus.UNAVAILABLE.value or not snapshot.quotes:
        reason = snapshot.note or "上游失败"
        return f"汇率数据暂时拉不到（{reason}），先不瞎猜数字。"
    lines = [
        f"汇率速览（基准 {snapshot.base_currency} · 中间价/参考价 · 延迟行情）"
    ]
    for quote in snapshot.quotes:
        lines.append(f"{quote.base_currency}/{quote.quote_currency} {quote.rate:.4f}")
    if snapshot.missing_currencies:
        lines.append("暂无数据：" + "、".join(snapshot.missing_currencies))
    stamp = (
        snapshot.as_of.strftime("%Y-%m-%d %H:%M UTC")
        if snapshot.as_of is not None
        else "更新时间未知"
    )
    lines.append(f"数据源 {snapshot.source} · {stamp} · 状态 {status}")
    return "\n".join(lines)


# ==================== 快查批量链路（东财主源，原任务 API） ====================

# 货币对宇宙表 (pair, secid, rate_type, unit_base, 展示名)。secid 实测清单：
# 133=离岸人民币现货、119=直盘现货、120=人民币中间价（JPYCNYC 为 100 日元口径）。
_FX_PAIR_UNIVERSE: tuple[tuple[str, str, str, float, str], ...] = (
    ("USD/CNY", "133.USDCNH", "spot", 1.0, "美元兑离岸人民币"),
    ("EUR/CNY", "120.EURCNYC", "parity", 1.0, "欧元人民币中间价"),
    ("JPY/CNY", "120.JPYCNYC", "parity", 100.0, "100日元人民币中间价"),
    ("HKD/CNY", "120.HKDCNYC", "parity", 1.0, "港币人民币中间价"),
    ("USD/JPY", "119.USDJPY", "spot", 1.0, "美元兑日元"),
    ("EUR/USD", "119.EURUSD", "spot", 1.0, "欧元兑美元"),
    ("GBP/USD", "119.GBPUSD", "spot", 1.0, "英镑兑美元"),
    ("USD/KRW", "119.USDKRW", "spot", 1.0, "美元兑韩元"),
    ("USD/HKD", "119.USDHKD", "spot", 1.0, "美元兑港币"),
    ("USD/SGD", "119.USDSGD", "spot", 1.0, "美元兑新加坡元"),
)

_PAIRS_BY_KEY: dict[str, tuple[str, str, float, str]] = {
    pair: (secid, rate_type, unit_base, display)
    for pair, secid, rate_type, unit_base, display in _FX_PAIR_UNIVERSE
}

# 中间价备用语义：主源（133/119 现货）优先，这些 120.* 中间价 secid 仅作
# 备用记录（当前 fetch 链路只用主源；rate_type="parity" 语义由
# EUR/JPY/HKD 兑 CNY 的宇宙表行直接体现）。
_FX_PARITY_ALTERNATES: dict[str, str] = {
    "USD/CNY": "120.USDCNYC",
    "EUR/CNY": "120.EURCNYC",
    "JPY/CNY": "120.JPYCNYC",
    "HKD/CNY": "120.HKDCNYC",
}

# 东财 suggest 实测查无行情的货币对（2026-09-12），登记为「数据源不可用」。
FX_UNAVAILABLE_PAIRS: tuple[str, ...] = ("USD/TWD", "USD/MOP", "USD/AED")

_FX_ULIST_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    "?fltt=2&secids={secids}&fields=f2,f3,f4,f12,f13,f14,f18"
)
_FX_EASTMONEY_SOURCE = "eastmoney"
_FX_CACHE_TTL_DEFAULT_SECONDS = 60.0
_FX_RATE_CACHE: tuple[float, tuple[FxRate, ...]] | None = None

_EMPTY_FX_TEXT = "汇率数据暂时拉不到，晚点再试试？"


def reset_fx_cache() -> None:
    """清空汇率快照进程内缓存（测试与运维手动刷新用）。"""
    global _FX_RATE_CACHE
    _FX_RATE_CACHE = None


def fx_pair_availability() -> dict[str, str]:
    """货币对覆盖表：有源 → ``eastmoney:<secid> <rate_type>``；
    东财查无行情 → ``unavailable: 东财无该货币对行情``（供能力层展示）。"""
    table = {
        pair: f"eastmoney:{secid} {rate_type}"
        for pair, secid, rate_type, *_rest in _FX_PAIR_UNIVERSE
    }
    for pair in FX_UNAVAILABLE_PAIRS:
        table[pair] = "unavailable: 东财无该货币对行情"
    return table


def _as_float(value: Any) -> float | None:
    """fltt=2 下正常值是小数/整数；缺数时可能是 "-" 或缺失。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fetch_payload(secids: str, timeout_seconds: float) -> Any:
    """东财汇率批量快照单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    return http_get_json(
        _FX_ULIST_URL.format(secids=secids),
        timeout=max(1.0, float(timeout_seconds)),
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


def _parse_rates(payload: Any, timestamp: str) -> list[FxRate]:
    """按宇宙表顺序解析响应；缺行/f2 非数的货币对跳过（绝不造数）。"""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    diff = data.get("diff") if isinstance(data, dict) else None
    if not isinstance(diff, list):
        return []
    by_code: dict[str, dict[str, Any]] = {}
    for row in diff:
        if isinstance(row, dict):
            code = str(row.get("f12") or "").strip().upper()
            if code:
                by_code[code] = row
    rates: list[FxRate] = []
    for pair, secid, rate_type, unit_base, _display in _FX_PAIR_UNIVERSE:
        row = by_code.get(secid.split(".", 1)[1])
        if row is None:
            continue
        rate = _as_float(row.get("f2"))
        if rate is None:
            continue
        base, quote = pair.split("/")
        rates.append(
            FxRate(
                base_currency=base,
                quote_currency=quote,
                rate=rate,
                unit_base=unit_base,
                timestamp=timestamp,
                source=_FX_EASTMONEY_SOURCE,
                rate_type=rate_type,
                delayed=True,
                history=(),  # 东财 FX 日 K 实测全空，恒为空元组
            )
        )
    return rates


def fetch_fx_rates(
    pair_keys: Sequence[str] | None = None,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _FX_CACHE_TTL_DEFAULT_SECONDS,
) -> list[FxRate]:
    """批量拉取汇率快照（东财主源）；失败返回 []，绝不抛异常。

    ``pair_keys=None`` 拉全部宇宙表货币对；给列表则按宇宙表顺序过滤子集。
    去重 secid 后单次批量外呼 + 进程内 TTL 缓存（默认 60s）；失败不缓存，
    下一次调用立即重试。``unit_base=100`` 的中间价（JPY/CNY）按 100 日元口径。
    """
    wanted: set[str] | None = None
    if pair_keys is not None:
        wanted = {str(p).strip().upper() for p in pair_keys if str(p).strip()}
        if not wanted:
            return []
    global _FX_RATE_CACHE
    now = time.monotonic()
    cached = _FX_RATE_CACHE
    if cached is not None and now - cached[0] <= max(0.0, float(cache_seconds)):
        all_rates = list(cached[1])
    else:
        secids: list[str] = []
        for _pair, secid, *_rest in _FX_PAIR_UNIVERSE:
            if secid not in secids:
                secids.append(secid)
        # G2：东财限流=HTTP 200 空响应（空 JSON/缺行）→ 退避后至多重试 1 次；
        # 真异常（网络错/非 200）不重试；仍空照旧不缓存。仅东财主源重试，
        # er-api 快照链路（fetch_fx_snapshot）不在重试范围。
        attempts = 2 if retry_on_empty_enabled() else 1
        all_rates = []
        for attempt in range(attempts):
            try:
                payload = _fetch_payload(
                    ",".join(secids), max(1.0, float(timeout_seconds))
                )
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                all_rates = _parse_rates(payload, timestamp)
            except Exception:  # noqa: BLE001 - 汇率失败静默降级，不阻塞会话链路。
                all_rates = []
                break  # 真异常不重试。
            if all_rates or attempt + 1 >= attempts:
                break
            empty_backoff_sleep()
        if all_rates:
            _FX_RATE_CACHE = (now, tuple(all_rates))
    if wanted is None:
        return all_rates
    return [
        rate
        for rate in all_rates
        if f"{rate.base_currency}/{rate.quote_currency}" in wanted
    ]


def resolve_fx_pair(base: str, quote: str) -> tuple[str, bool] | None:
    """解析货币对：直接命中 → ``(pair, False)``；反向命中 → ``(pair, True)``
    （调用方取 1/rate 并标 derived）；都无 → ``None``。"""
    base_upper = (base or "").strip().upper()
    quote_upper = (quote or "").strip().upper()
    if not base_upper or not quote_upper:
        return None
    direct = f"{base_upper}/{quote_upper}"
    if direct in _PAIRS_BY_KEY:
        return (direct, False)
    reverse = f"{quote_upper}/{base_upper}"
    if reverse in _PAIRS_BY_KEY:
        return (reverse, True)
    return None


# 中文币名 → ISO 代码（含无源币种：解析层照常返回，覆盖表层标注不可用）。
_CURRENCY_ALIASES: dict[str, str] = {
    "美元": "USD",
    "美金": "USD",
    "人民币": "CNY",
    "日元": "JPY",
    "日圆": "JPY",
    "韩元": "KRW",
    "韩币": "KRW",
    "港币": "HKD",
    "港元": "HKD",
    "欧元": "EUR",
    "英镑": "GBP",
    "新台币": "TWD",
    "台币": "TWD",
    "澳门币": "MOP",
    "澳门元": "MOP",
    "迪拉姆": "AED",
    "新加坡元": "SGD",
    "新币": "SGD",
    # 繁体变体（2026-09-13 多语言触发覆盖）。
    "人民幣": "CNY",
    "新台幣": "TWD",
    "台幣": "TWD",
    "港幣": "HKD",
    "韓元": "KRW",
    "歐元": "EUR",
    "英鎊": "GBP",
    "澳門幣": "MOP",
}
_CN_NAME_ALT = "|".join(sorted(_CURRENCY_ALIASES, key=len, reverse=True))
_VALID_CODES = frozenset(_CURRENCY_ALIASES.values())

# 「100日元换多少人民币」：金额 + 币名 + 兑换动词（可带 能/可以/多少；
# 繁体 動詞 兌/換 同樣接受）。
_CONVERT_RE = re.compile(
    rf"(?P<amount>\d+(?:\.\d+)?)?\s*(?P<base>{_CN_NAME_ALT})\s*"
    rf"(?:能|可以)?(?:兑换|换成|兑|对|换|兌換|兌|換)\s*(?:多少)?\s*(?P<quote>{_CN_NAME_ALT})"
)
# 「USD/CNY」（大小写不敏感；也容「USD兑CNY/USD兌CNY」）。
_SLASH_PAIR_RE = re.compile(r"([A-Za-z]{3})\s*(?:/|兑|兌|对)\s*([A-Za-z]{3})")
# 「美元汇率/美元匯率」：单查默认兑人民币。
_NAME_RATE_RE = re.compile(rf"(?P<name>{_CN_NAME_ALT})\s*[汇匯]率")

_CURRENCY_DISPLAY: dict[str, str] = {
    "USD": "美元",
    "CNY": "人民币",
    "JPY": "日元",
    "KRW": "韩元",
    "HKD": "港币",
    "EUR": "欧元",
    "GBP": "英镑",
    "TWD": "新台币",
    "MOP": "澳门币",
    "AED": "迪拉姆",
    "SGD": "新加坡元",
}


def parse_fx_query(text: str) -> tuple[str, str, float] | None:
    """从自然语言解析汇率查询意图，返回 ``(base, quote, amount)``。

    - 「美元兑人民币」/「USD/CNY」（大小写不敏感）→ ("USD","CNY",1.0)；
    - 「100日元换多少人民币」→ ("JPY","CNY",100.0)（金额随币名前置）；
    - 「美元汇率」「日元汇率」→ 默认兑人民币（单查中文名的缺省语义）；
    - 纯「汇率」→ ``None``（能力层走主要货币面板）；
    - 无源货币对（如 台币）也照常解析，由 ``fx_pair_availability`` 标不可用。
    """
    if not text:
        return None
    slash = _SLASH_PAIR_RE.search(text)
    if slash:
        code1 = slash.group(1).upper()
        code2 = slash.group(2).upper()
        if code1 in _VALID_CODES and code2 in _VALID_CODES and code1 != code2:
            return (code1, code2, 1.0)
    lowered = text.strip().lower()
    convert = _CONVERT_RE.search(lowered)
    if convert:
        base = _CURRENCY_ALIASES.get(convert.group("base"))
        quote = _CURRENCY_ALIASES.get(convert.group("quote"))
        amount_text = convert.group("amount")
        if base and quote and base != quote:
            return (base, quote, float(amount_text) if amount_text else 1.0)
    name_rate = _NAME_RATE_RE.search(lowered)
    if name_rate:
        code = _CURRENCY_ALIASES.get(name_rate.group("name"))
        if code and code != "CNY":  # 「人民币汇率」基准=报价，无意义
            return (code, "CNY", 1.0)
    return None


def wants_major_rates(text: str) -> bool:
    """判断文本是否想要主要货币面板（「汇率」或「主要货币」）。"""
    return "汇率" in (text or "") or "主要货币" in (text or "")


def has_currency_term(text: str) -> bool:
    """文本是否含任何已知币名（中文别名/繁体/ISO 小写码）。

    「换算」类泛词的语境约束用（评审 P1-1）：「美元换算」=True、
    「单位换算」=False。
    """
    lowered = (text or "").lower()
    if not lowered:
        return False
    if any(alias in lowered for alias in _CURRENCY_ALIASES):
        return True
    return any(
        code.lower() in lowered
        for code in ("USD", "EUR", "GBP", "JPY", "KRW", "TWD", "CNY", "HKD", "SGD", "MOP", "AED")
    )


def format_fx_rate_line(rate: FxRate, amount: float = 1.0) -> str:
    """单行汇率换算：`100日元 ≈ 4.36 人民币`（含 unit_base 折算）。

    展示口径为「金额 + 基准币名 ≈ 折算额 + 报价币名」：amount 按
    ``unit_base`` 折算后乘汇率（100日元中间价 4.3614 × 100/100 = 4.36）。
    """
    base_name = _CURRENCY_DISPLAY.get(rate.base_currency, rate.base_currency)
    quote_name = _CURRENCY_DISPLAY.get(rate.quote_currency, rate.quote_currency)
    converted = amount / rate.unit_base * rate.rate
    return f"{amount:g}{base_name} ≈ {converted:.2f} {quote_name}"


def format_fx_brief(rates: Sequence[FxRate]) -> str:
    """主要货币汇率速览（快查批量链路）；按 unit_base 折算展示；
    空结果给降级文案。provenance 快照链路见 ``format_fx_snapshot_brief``。"""
    if not rates:
        return _EMPTY_FX_TEXT
    lines = ["主要货币汇率速览"]
    for rate in rates:
        lines.append(format_fx_rate_line(rate, amount=rate.unit_base))
    return "\n".join(lines)

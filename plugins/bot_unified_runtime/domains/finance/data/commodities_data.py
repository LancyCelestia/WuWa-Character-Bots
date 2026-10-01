"""大宗商品行情数据源（金融 Phase-1 扩容，2026-09-13）。

上游复用 ``market_data.py`` 已验证的东财 push2 免费接口族（免 key）。
**以下 secid 均为 2026-09-13 本机 ``ulist.np/get`` 实测有行（verified）**：

- ``101.GC00Y`` COMEX黄金（主力连续，美元/金衡盎司）；
- ``101.SI00Y`` COMEX白银（主力连续，美元/金衡盎司）；
- ``101.HG00Y`` COMEX铜（主力连续，美元/磅）；
- ``102.CL00Y`` NYMEX原油（WTI 主力连续，美元/桶）。

市场号实测规律：101=COMEX、102=NYMEX；``fltt=2`` 下 ``f2``=最新价 /
``f3``=涨跌% / ``f4``=涨跌额 / ``f12``=代码 / ``f13``=市场号 / ``f14``=名称。

**LME 诚实边界**：LME 铜（113.LMCADY / 110.LMCADY / 108.LMCADY / 113.LMDY
等候选）在东财 ulist 实测全部无行；LME 官网无免 key 稳定公开接口 → 铜
采用 COMEX HG00Y 主力连续替代（同为国际铜价口径，单位 美元/磅），替代
事实在能力层文案显式说明，绝不冒充 LME。布伦特原油未实测到有效 secid
（102.BZ00Y/CO00Y 无行），暂不接入。

走势（30 日收盘）：复用东财 push2his kline 接口（``end=20500101`` 缺它
返空——2026-09-13 接口变更），瞬断（RemoteDisconnected → ParseHttpError）
按 ``stock_data._network_retry`` 同语义退避重试（vis3 2026-09-13 实测
push2his 会瞬断）；全失败返回空元组，卡上展示「暂无历史走势数据」。

任何网络/解析失败一律返回空列表/空元组（成功才进进程内 TTL 缓存，失败
不缓存便于立即重试），由能力层给降级文案，绝不向上抛异常。
"""

from __future__ import annotations

import math
import random
import time
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# 审查 Q-01：user_copy 为零依赖纯常量池，sources 跨层引用不构成装配环。
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.finance.data.market_data import (
    _MAX_PAYLOAD_BYTES,
    _budget_or_new,
    budget_allows_retry,
    budget_expired,
    empty_backoff_sleep,
    retry_on_empty_enabled,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

# (secid, 展示名, 分组, 单位)。secid 全部 2026-09-13 ulist 实测有行。
_COMMODITY_UNIVERSE: tuple[tuple[str, str, str, str], ...] = (
    ("101.GC00Y", "COMEX黄金", "贵金属", "美元/金衡盎司"),
    ("101.SI00Y", "COMEX白银", "贵金属", "美元/金衡盎司"),
    ("101.HG00Y", "COMEX铜", "基本金属", "美元/磅"),
    ("102.CL00Y", "NYMEX原油", "能源", "美元/桶"),
)

_GROUP_ORDER: tuple[str, ...] = ("贵金属", "基本金属", "能源")

# LME 替代说明（能力层文案引用；有朝一日拿到稳定 LME 源改这里）。
LME_NOTE = "LME 无稳定免费公开源，铜采用 COMEX 主力连续（美元/磅）"

_QUOTE_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    "?fltt=2&secids={secids}&fields=f2,f3,f4,f12,f13,f14"
)
_SOURCE = "eastmoney"

_CACHE_TTL_DEFAULT_SECONDS = 60.0
_CACHE: tuple[float, tuple[CommodityQuote, ...]] | None = None

# 审查 Q-01：数据源失败文案统一入 user_copy 池（守岸人语气轮换），不再硬编码。
def _empty_degraded_text() -> str:
    return random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(reason="大宗商品行情暂时拉不到")

# ==================== 走势（30 日收盘，push2his kline） ====================
_KLINE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid={secid}&fields1=f1&fields2=f51,f53&klt=101&fqt=1&lmt={days}"
    "&end=20500101"
)
_TREND_MAX_POINTS = 60
_TREND_CACHE_TTL_SECONDS = 600.0
_TREND_CACHE: dict[str, tuple[float, tuple[float, ...]]] = {}


@dataclass(frozen=True)
class CommodityQuote:
    """单个商品的行情快照（provenance 四件套与 IndexQuote 同构）。"""

    name: str
    code: str  # eastmoney secid，如 101.GC00Y
    price: float
    change_pct: float
    change_abs: float | None = None
    unit: str = ""
    group: str = ""
    source: str = _SOURCE
    as_of: float | None = None
    delayed: bool = True
    status: str = "ok"


def _as_float(value: Any) -> float | None:
    """fltt=2 下正常值是小数/整数；缺数时可能是 "-" 或缺失。

    FIN-N1（2026-09-27 评审票）：非有限值（上游 NaN/Infinity 字面量）一律
    视为缺数 None——走既有「暂无数据」诚实通道，不入卡片数字槽。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _fetch_payload(secids: str, timeout_seconds: float) -> Any:
    """批量快照单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    return http_get_json(
        _QUOTE_URL.format(secids=secids),
        timeout=max(1.0, float(timeout_seconds)),
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


def _parse_quotes(payload: Any) -> list[CommodityQuote]:
    """按宇宙表顺序解析响应；缺行/价格或涨跌幅非数的商品跳过。"""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    diff = data.get("diff") if isinstance(data, dict) else None
    if not isinstance(diff, list):
        return []
    by_code: dict[str, dict[str, Any]] = {}
    for row in diff:
        if isinstance(row, dict):
            code = str(row.get("f12") or "").strip()
            if code:
                by_code[code] = row
    quotes: list[CommodityQuote] = []
    for secid, display, group, unit in _COMMODITY_UNIVERSE:
        row = by_code.get(secid.split(".", 1)[1])
        if row is None:
            continue
        price = _as_float(row.get("f2"))
        change_pct = _as_float(row.get("f3"))
        if price is None or change_pct is None:
            continue
        quotes.append(
            CommodityQuote(
                name=display,
                code=secid,
                price=price,
                change_pct=change_pct,
                change_abs=_as_float(row.get("f4")),
                unit=unit,
                group=group,
                source=_SOURCE,
                as_of=time.time(),
                delayed=True,
                status="ok",
            )
        )
    return quotes


def reset_commodities_cache() -> None:
    """清空商品行情进程内缓存（测试与运维手动刷新用）。"""
    global _CACHE
    _CACHE = None


def fetch_commodity_quotes(
    timeout_seconds: float = 6.0,
    cache_seconds: float = _CACHE_TTL_DEFAULT_SECONDS,
    *,
    budget: Any | None = None,
) -> list[CommodityQuote]:
    """拉取大宗商品快照；失败返回 []，绝不抛异常。

    G2 纪律与 market_data/fx_data/stock_data 同款：东财限流=HTTP 200 空响应
    → 退避后至多重试 1 次；真异常不重试；仍空照旧诚实降级且不缓存。
    FIN-R1：整条命令共用端到端网络预算，预算尽弃剩余重试。
    """
    global _CACHE
    now = time.monotonic()
    cached = _CACHE
    if cached is not None and now - cached[0] <= max(0.0, float(cache_seconds)):
        return list(cached[1])
    budget = _budget_or_new(budget)
    secids = ",".join(secid for secid, _n, _g, _u in _COMMODITY_UNIVERSE)
    attempts = 2 if retry_on_empty_enabled() else 1
    quotes: list[CommodityQuote] = []
    for attempt in range(attempts):
        if budget_expired(budget):
            break  # FIN-R1：预算尽不发起新网络调用。
        try:
            payload = _fetch_payload(secids, max(1.0, float(timeout_seconds)))
            quotes = _parse_quotes(payload)
        except Exception:  # noqa: BLE001 - 商品行情失败静默降级。
            quotes = []
            break  # 真异常不重试。
        if quotes or attempt + 1 >= attempts or not budget_allows_retry(budget):
            break
        empty_backoff_sleep()
    if quotes:
        _CACHE = (now, tuple(quotes))
    return quotes


def commodity_availability() -> dict[str, str]:
    """商品覆盖表：有源 → ``eastmoney:<secid>``；无源项显式登记（诚实边界）。"""
    table = {
        name: f"eastmoney:{secid}"
        for secid, name, _group, _unit in _COMMODITY_UNIVERSE
    }
    table["LME铜"] = f"unavailable: {LME_NOTE}"
    table["Brent原油"] = "unavailable: 东财未实测到有效 secid"
    return table


def reset_commodities_trend_cache() -> None:
    """清空走势缓存（测试用）。"""
    _TREND_CACHE.clear()


def _retry_transient(fetch, *, attempts: int = 3, budget: Any | None = None):
    """push2his 瞬断退避重试（语义与 ``stock_data._network_retry`` 一致：
    ParseHttpError/ConnectionError/TimeoutError 退避重试，其他异常原样抛）。

    FIN-R1（2026-09-27 评审票）：429 不跨层重试（链接层已在单调用内尊重
    Retry-After 并重试到位，层间再叠即是 60s 睡眠相乘）；退避睡眠受
    网络预算门控，预算尽弃剩余尝试。"""
    last_exc: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return fetch()
        except (ParseHttpError, ConnectionError, TimeoutError) as exc:
            last_exc = exc
            if getattr(exc, "status_code", None) == 429:
                raise  # 429 已由链接层尊重 Retry-After，不再叠加层间等待
            if attempt + 1 >= attempts:
                raise
            if not budget_allows_retry(budget):
                raise  # 预算尽弃剩余重试；失败不缓存、静默缺席语义不变
            empty_backoff_sleep()
    raise last_exc if last_exc is not None else RuntimeError("unreachable")  # pragma: no cover


def fetch_commodity_trend(
    secid: str,
    *,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _TREND_CACHE_TTL_SECONDS,
    budget: Any | None = None,
) -> tuple[float, ...]:
    """单个商品近 30 日收盘序列（旧→新）；失败/无数据返回空元组，绝不抛。

    10 分钟进程内缓存；失败（空序列）不缓存，下一次调用立即重试。
    FIN-R1：整条拉取受端到端网络预算门控，预算尽弃剩余重试。
    """
    cached = _TREND_CACHE.get(secid)
    now = time.monotonic()
    if cached is not None and now - cached[0] <= max(1.0, float(cache_seconds)):
        return cached[1]
    budget = _budget_or_new(budget)

    def _get() -> Any:
        return http_get_json(
            _KLINE_URL.format(
                secid=urllib.parse.quote(secid), days=_TREND_MAX_POINTS
            ),
            timeout=max(1.0, float(timeout_seconds)),
            max_bytes=_MAX_PAYLOAD_BYTES,
        )

    closes: tuple[float, ...] = ()
    # G2：空响应（空 JSON/缺行）退避后至多重试 1 次；瞬断（ParseHttpError）
    # 走 _retry_transient（至多 3 次退避）；仍空照旧不缓存。
    attempts = 2 if retry_on_empty_enabled() else 1
    for attempt in range(attempts):
        if budget_expired(budget):
            break  # FIN-R1：预算尽不发起新网络调用。
        try:
            payload = _retry_transient(_get, budget=budget)
            data = payload.get("data") if isinstance(payload, dict) else None
            klines = data.get("klines") if isinstance(data, dict) else None
            if isinstance(klines, list):
                values: list[float] = []
                for row in klines:
                    # fields2=f51,f53 → "日期,收盘"；只取收盘。
                    parts = str(row).split(",")
                    if len(parts) >= 2:
                        close = _as_float(parts[1])
                        if close is not None:
                            values.append(close)
                closes = tuple(values[-_TREND_MAX_POINTS:])
        except Exception:  # noqa: BLE001 - 走势失败静默缺席，不拖垮卡片。
            closes = ()
            break  # 真异常不重试。
        if closes or attempt + 1 >= attempts or not budget_allows_retry(budget):
            break
        empty_backoff_sleep()
    if closes:
        _TREND_CACHE[secid] = (now, closes)
    return closes


def format_price(price: float) -> str:
    """价格精度随量级：高价（金银油）两位小数，低价（铜 ~6 美元/磅）三位。"""
    if price >= 100:
        return f"{price:.2f}"
    return f"{price:.3f}"


def _format_change_abs(change_abs: float | None) -> str:
    if change_abs is None:
        return ""
    if change_abs > 0:
        return f"+{change_abs:.3f}".rstrip("0").rstrip(".") if abs(change_abs) < 1 else f"+{change_abs:.2f}"
    text = f"{change_abs:.3f}".rstrip("0").rstrip(".") if abs(change_abs) < 1 else f"{change_abs:.2f}"
    return text


def commodity_group(quote: CommodityQuote) -> str:
    """宇宙表内返回分组；未知 secid 落「其他」。"""
    for secid, _name, group, _unit in _COMMODITY_UNIVERSE:
        if quote.code == secid:
            return group
    return "其他"


def group_commodity_quotes(
    quotes: Sequence[CommodityQuote],
) -> dict[str, list[CommodityQuote]]:
    """按 贵金属/基本金属/能源(其他) 分组（保宇宙顺序）；空组剔除。"""
    grouped: dict[str, list[CommodityQuote]] = {g: [] for g in _GROUP_ORDER}
    grouped.setdefault("其他", [])
    for quote in quotes:
        grouped.setdefault(commodity_group(quote), []).append(quote)
    return {name: rows for name, rows in grouped.items() if rows}


def format_commodity_line(quote: CommodityQuote) -> str:
    """单行：`🔴 COMEX黄金 4390.00 -0.39%`（红涨绿跌，与股指同款标记）。"""
    if quote.change_pct > 0:
        mark = "🔴"
    elif quote.change_pct < 0:
        mark = "🟢"
    else:
        mark = "⚪"
    signed_pct = (
        f"+{quote.change_pct:.2f}%" if quote.change_pct > 0 else f"{quote.change_pct:.2f}%"
    )
    line = f"{mark} {quote.name} {format_price(quote.price)} {signed_pct}"
    if quote.change_abs is not None and quote.change_abs != 0:
        change_text = _format_change_abs(quote.change_abs)
        line = f"{line}（{change_text}）"
    return line


def format_commodities_brief(quotes: Sequence[CommodityQuote]) -> str:
    """按组分组的纯文本商品快报；空结果给降级文案。"""
    if not quotes:
        return _empty_degraded_text()
    grouped = group_commodity_quotes(quotes)
    lines = ["大宗商品速览"]
    for group in (*_GROUP_ORDER, "其他"):
        rows = grouped.get(group) or []
        if not rows:
            continue
        lines.append(f"—— {group} ——")
        lines.extend(format_commodity_line(quote) for quote in rows)
    lines.append(f"注：{LME_NOTE}")
    return "\n".join(lines)

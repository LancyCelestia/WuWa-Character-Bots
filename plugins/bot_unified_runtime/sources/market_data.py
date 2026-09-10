"""全球股指行情数据源（东方财富 push2 免费行情接口，免 key）。

实测可用的请求（2026-09-11，本机直连验证，无需 Referer/Cookie）：

    GET https://push2.eastmoney.com/api/qt/ulist.np/get
        ?fltt=2&secids=1.000001,0.399001,...&fields=f2,f3,f4,f12,f14

- ``fltt=2``：数值直接以小数返回（f2=最新价，f3=涨跌幅%，f4=涨跌额）；
- ``f12``=指数代码、``f14``=指数名称；secid 市场前缀 1=上交所、0=深交所、
  100=国际指数；
- 无效 secid 不会报错，只会从响应的 ``data.diff`` 里消失。实测
  ``100.BSESN`` 无效（正确代码是 ``100.SENSEX``）、``100.IMOEX``（俄罗斯
  MOEX）无数据，两者均未收录；其余 15 个指数全部有效。

任何网络/解析失败一律返回空列表（成功结果才进进程内 TTL 缓存，失败不缓存，
便于用户立即重试），由能力层给降级文案，绝不向上抛异常。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from plugins.bot_unified_runtime.sources.parsers.http_util import http_get_json

_EASTMONEY_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    "?fltt=2&secids={secids}&fields=f2,f3,f4,f12,f14"
)

# 响应体上限：15 个指数的 JSON 实测约 2KB，1MB 已是数百倍冗余，
# 只为防异常超大响应撑爆内存。
_MAX_PAYLOAD_BYTES = 1024 * 1024


@dataclass(frozen=True)
class IndexQuote:
    """单个指数的行情快照。"""

    name: str
    code: str  # eastmoney secid，如 1.000001 / 100.DJIA
    price: float
    change_pct: float
    change_abs: float | None = None


# (secid, 展示名, 分组)；展示名沿用约定俗成的简称（接口原始名
# "富时新加坡海峡时报"/"印度孟买SENSEX"/"德国DAX30" 过长，消息里不友好）。
_INDEX_UNIVERSE: tuple[tuple[str, str, str], ...] = (
    ("1.000001", "上证指数", "中国区"),
    ("0.399001", "深证成指", "中国区"),
    ("0.399006", "创业板指", "中国区"),
    ("100.HSI", "恒生指数", "亚太"),
    ("100.N225", "日经225", "亚太"),
    ("100.KS11", "韩国KOSPI", "亚太"),
    ("100.STI", "新加坡海峡时报", "亚太"),
    ("100.SENSEX", "印度SENSEX", "亚太"),
    ("100.TWII", "台湾加权", "亚太"),
    ("100.FTSE", "英国富时100", "欧美"),
    ("100.FCHI", "法国CAC40", "欧美"),
    ("100.GDAXI", "德国DAX", "欧美"),
    ("100.DJIA", "道琼斯", "欧美"),
    ("100.SPX", "标普500", "欧美"),
    ("100.NDX", "纳斯达克", "欧美"),
)

_GROUP_ORDER: tuple[str, ...] = ("中国区", "亚太", "欧美")
_OTHER_GROUP = "其他"

# 红涨绿跌（与 A 股配色习惯一致），横盘用白点。
_MARK_UP = "🔴"
_MARK_DOWN = "🟢"
_MARK_FLAT = "⚪"

# 进程内缓存：缓存的是最后一次成功抓取（monotonic 时间戳, 结果快照）。
_CACHE_TTL_DEFAULT_SECONDS = 60.0
_CACHE: tuple[float, tuple[IndexQuote, ...]] | None = None

_EMPTY_DEGRADED_TEXT = "行情数据暂时拉不到，晚点再试试？"


def reset_market_cache() -> None:
    """清空进程内行情缓存（测试与运维手动刷新用）。"""
    global _CACHE
    _CACHE = None


def _fetch_payload(secids: str, timeout_seconds: float) -> Any:
    """单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    return http_get_json(
        _EASTMONEY_URL.format(secids=secids),
        timeout=timeout_seconds,
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


def _as_float(value: Any) -> float | None:
    """fltt=2 下正常值是小数/整数；停牌或缺数时可能是 "-" 或缺失。"""
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


def _parse_quotes(payload: Any) -> list[IndexQuote]:
    """按固定宇宙顺序解析响应；缺数/非数的指数跳过。"""
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
    quotes: list[IndexQuote] = []
    for secid, display, _group in _INDEX_UNIVERSE:
        row = by_code.get(secid.split(".", 1)[1])
        if row is None:
            continue
        price = _as_float(row.get("f2"))
        change_pct = _as_float(row.get("f3"))
        if price is None or change_pct is None:
            continue
        quotes.append(
            IndexQuote(
                name=display,
                code=secid,
                price=price,
                change_pct=change_pct,
                change_abs=_as_float(row.get("f4")),
            )
        )
    return quotes


def fetch_index_quotes(
    timeout_seconds: float = 6.0,
    cache_seconds: float = _CACHE_TTL_DEFAULT_SECONDS,
) -> list[IndexQuote]:
    """拉取全球股指快照；失败返回 []，绝不抛异常。

    成功结果带进程内 TTL 缓存（默认 60s），避免同群连发消息时打爆接口；
    失败不缓存，下一次调用立即重试。
    """
    global _CACHE
    now = time.monotonic()
    cached = _CACHE
    if cached is not None and now - cached[0] <= max(0.0, float(cache_seconds)):
        return list(cached[1])
    secids = ",".join(secid for secid, _name, _group in _INDEX_UNIVERSE)
    try:
        payload = _fetch_payload(secids, max(1.0, float(timeout_seconds)))
        quotes = _parse_quotes(payload)
    except Exception:  # noqa: BLE001 - 行情失败静默降级，不阻塞会话链路。
        quotes = []
    if quotes:
        _CACHE = (now, tuple(quotes))
    return quotes


def _quote_group(quote: IndexQuote) -> str:
    for secid, _name, group in _INDEX_UNIVERSE:
        if quote.code == secid:
            return group
    return _OTHER_GROUP


def format_quote_line(quote: IndexQuote) -> str:
    """单行行情：`道琼斯 42114.40 +0.58%`，涨跌幅带符号，附涨跌额可选。"""
    if quote.change_pct > 0:
        mark = _MARK_UP
    elif quote.change_pct < 0:
        mark = _MARK_DOWN
    else:
        mark = _MARK_FLAT
    signed_pct = f"+{quote.change_pct:.2f}%" if quote.change_pct > 0 else (
        f"{quote.change_pct:.2f}%"
    )
    line = f"{mark} {quote.name} {quote.price:.2f} {signed_pct}"
    if quote.change_abs is not None:
        abs_text = f"+{quote.change_abs:.2f}" if quote.change_abs > 0 else (
            f"{quote.change_abs:.2f}"
        )
        line = f"{line}（{abs_text}）"
    return line


def format_market_brief(quotes: Sequence[IndexQuote]) -> str:
    """按 中国区/亚太/欧美 分组的纯文本行情快报；空结果给降级文案。"""
    if not quotes:
        return _EMPTY_DEGRADED_TEXT
    grouped: dict[str, list[IndexQuote]] = {group: [] for group in _GROUP_ORDER}
    grouped.setdefault(_OTHER_GROUP, [])
    for quote in quotes:
        grouped.setdefault(_quote_group(quote), []).append(quote)
    lines = ["全球股指速览"]
    for group in (*_GROUP_ORDER, _OTHER_GROUP):
        group_quotes = grouped.get(group) or []
        if not group_quotes:
            continue
        lines.append(f"—— {group} ——")
        lines.extend(format_quote_line(quote) for quote in group_quotes)
    return "\n".join(lines)

"""全球股指行情数据源（东方财富 push2 免费行情接口，免 key）。

实测可用的请求（2026-09-11，本机直连验证，无需 Referer/Cookie）：

    GET https://push2.eastmoney.com/api/qt/ulist.np/get
        ?fltt=2&secids=1.000001,0.399001,...&fields=f2,f3,f4,f12,f14

- ``fltt=2``：数值直接以小数返回（f2=最新价，f3=涨跌幅%，f4=涨跌额）；
- ``f12``=指数代码、``f14``=指数名称；secid 市场前缀 1=上交所、0=深交所、
  100=国际指数；
- 无效 secid 不会报错，只会从响应的 ``data.diff`` 里消失。实测
  ``100.BSESN`` 无效（正确代码是 ``100.SENSEX``）；东财无 ``100.IMOEX``
  （俄罗斯 MOEX）数据，该指数改走 MOEX ISS 官方接口备选源（见下）。

MOEX ISS 备选源（2026-09-12 实测本机直连可达，免 key，无需代理）：

    GET https://iss.moex.com/iss/engines/stock/markets/index/boards/SNDX/securities/IMOEX.json?iss.meta=off

- ``marketdata`` 按列名取 ``CURRENTVALUE``（现值，缺则 ``LASTVALUE``）、
  ``LASTCHANGEPRC``（涨跌%）、``LASTCHANGE``（涨跌额）；列序变更不敏感；
  单源失败该指数缺席，不拖垮整卡。

任何网络/解析失败一律返回空列表（成功结果才进进程内 TTL 缓存，失败不缓存，
便于用户立即重试），由能力层给降级文案，绝不向上抛异常。
"""

from __future__ import annotations

import os
import random
import time
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# 审查 Q-01：user_copy 为零依赖纯常量池（模块纪律禁 import），sources 跨层
# 引用不构成装配环（包 __init__ 仅 docstring），与 contracts 同为低层共享面。
from plugins.bot_unified_runtime.capabilities import user_copy
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

_EASTMONEY_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    "?fltt=2&secids={secids}&fields=f2,f3,f4,f12,f14"
)
_MOEX_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/index/boards/SNDX"
    "/securities/IMOEX.json?iss.meta=off"
)

# MOEX 指数在宇宙表里的内部 secid 键（东财侧无此数据，仅作展示/过滤键）。
_MOEX_SECID = "100.IMOEX"

# 响应体上限：17 个东财指数的 JSON 实测约 2KB，1MB 已是数百倍冗余，
# 只为防异常超大响应撑爆内存。
_MAX_PAYLOAD_BYTES = 1024 * 1024


@dataclass(frozen=True)
class IndexQuote:
    """单个指数的行情快照。

    provenance 四件套（Task 4 增量，默认值向后兼容旧调用点）：
    ``source`` 数据源（eastmoney / moex_iss）、``as_of`` 数据抓取时间
    （unix 秒）、``delayed=True`` 免费行情恒为延迟口径、``status`` 预留
    状态位（当前快照要么完整要么缺席，缺席行不进列表）。
    """

    name: str
    code: str  # eastmoney secid，如 1.000001 / 100.DJIA
    price: float
    change_pct: float
    change_abs: float | None = None
    source: str = "eastmoney"
    as_of: float | None = None
    delayed: bool = True
    status: str = "ok"


# (secid, 展示名, 分组)；展示名沿用约定俗成的简称（接口原始名
# "富时新加坡海峡时报"/"印度孟买SENSEX"/"德国DAX30" 过长，消息里不友好）。
_INDEX_UNIVERSE: tuple[tuple[str, str, str], ...] = (
    ("1.000001", "上证指数", "中国区"),
    ("0.399001", "深证成指", "中国区"),
    ("0.399006", "创业板指", "中国区"),
    ("1.000003", "上证B股", "中国区"),
    ("0.399003", "深证B股", "中国区"),
    ("100.HSI", "恒生指数", "亚太"),
    ("100.N225", "日经225", "亚太"),
    ("100.KS11", "韩国KOSPI", "亚太"),
    ("100.STI", "新加坡海峡时报", "亚太"),
    ("100.SENSEX", "印度SENSEX", "亚太"),
    ("100.TWII", "台湾加权", "亚太"),
    ("100.FTSE", "英国富时100", "欧美"),
    ("100.FCHI", "法国CAC40", "欧美"),
    ("100.GDAXI", "德国DAX", "欧美"),
    ("100.IMOEX", "俄罗斯MOEX", "欧美"),
    ("100.DJIA", "道琼斯", "欧美"),
    ("100.SPX", "标普500", "欧美"),
    ("100.NDX", "纳斯达克", "欧美"),
)

_GROUP_ORDER: tuple[str, ...] = ("中国区", "亚太", "欧美")
_OTHER_GROUP = "其他"

# ==================== H-01（2026-09-14 市场扩容审查）：无源市场显式登记 ==========
# 诚实铁律：无源品种显式登记「无源」如实标注，绝不造数（先例：北向净买入
# 2024-08 停披露、LME 无源→COMEX 铜显式替代）。澳门/迪拜/阿联酋三市场
# 2026-09-14 真机实证（证据链，均本机实跑非臆测）：
# - push2 ulist 实测：100.DFMGI / 100.DFM / 100.DSI / 100.ADI / 100.ADXGI
#   全部无效（secid 无效不报错、只会从 data.diff 里消失，实测无一返回）；
# - searchapi suggest 实测：「迪拜」「阿布扎比」「Dubai」「DFMGI」零报价结果；
# - 「阿联酋」仅命中 105.UAE = iShares MSCI UAE ETF（纳斯达克上市基金，
#   语义 ≠ 国家综合股指，直接当指数展示会误导）；
# - 「澳门」仅命中港股个股（永利澳门 116.01128 等）与 MOP 中间价——澳门
#   无活跃证券交易所，结构性无综合股指可引。
# 三者定性「确实无源」→ INDEX_UNAVAILABLE 显式登记并出现在行情卡「暂无」
# 注记区；触发词（H-07）无源不补。是否接受 ETF（105.UAE）作为阿联酋代理
# 属语义裁决，留给用户——见 PENDING_INDEX_CANDIDATES。
INDEX_UNAVAILABLE: tuple[tuple[str, str], ...] = (
    ("迪拜", "东财未收录迪拜DFM综合股指"),
    ("阿联酋", "东财仅有在美ETF（语义≠国家股指），未上卡"),
    ("澳门", "澳门无证券交易所，结构性无综合股指"),
)

# 待真机验证候选清单（H-01 常量，纪律：只登记、不上卡）。
# 105.UAE 已实探存在（suggest QuoteID 实证），但它是 ETF 而非股指——
# 上卡需用户先裁决「ETF 代理是否可接受」；其余候选离线/真机均无实据。
PENDING_INDEX_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    # (secid, 名称, 不直接上卡的原因)
    ("105.UAE", "阿联酋ETF(iShares MSCI UAE)", "ETF 语义≠国家综合股指，待用户裁决"),
)


def index_unavailable_entries() -> tuple[tuple[str, str], ...]:
    """无源市场登记（卡面「暂无」注记与测试消费；单一事实来源本常量）。"""
    return INDEX_UNAVAILABLE

# 红涨绿跌（与 A 股配色习惯一致），横盘用白点。
_MARK_UP = "🔴"
_MARK_DOWN = "🟢"
_MARK_FLAT = "⚪"

# 进程内缓存：缓存的是最后一次成功抓取（monotonic 时间戳, 结果快照）。
_CACHE_TTL_DEFAULT_SECONDS = 60.0
_CACHE: tuple[float, tuple[IndexQuote, ...]] | None = None

# 审查 Q-01：数据源失败文案统一入 user_copy 池（守岸人语气轮换），不再硬编码。
def _empty_degraded_text() -> str:
    return random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(reason="行情数据暂时拉不到")


# ==================== 东财空响应受控重试（G2，2026-09-13） ====================
# 东财限流表现为 HTTP 200 但业务体为空（空 JSON/缺行，无错误码），与真异常
# （网络错/非 200 → ParseHttpError）不同，值得退避后再试一次。本节是
# market_data / stock_data / fx_data 三源共用的重试缝：开关解析链 + 退避单点。
# 纪律：只对「HTTP 200 但解析为空」重试；真异常不重试；仍空走既有诚实降级
# 且不缓存（「失败不缓存」语义不变，重试不改变缓存键与缓存条件）。

_RETRY_BACKOFF_SECONDS = 0.6  # 0.5~1s 区间取 0.6s；monkeypatch 本常量可覆盖。


def retry_on_empty_enabled() -> bool:
    """东财空响应重试开关（config ``bot_market_retry_on_empty``，默认开）。

    解析链与 ``runtime/pipeline.py`` 的 ``_resolve_chat_pool_workers`` 同源
    模式：nonebot driver config → 环境变量 → 默认 True；数据层不接收注入
    config，经惰性 get_driver 读取，未初始化（单元测试/裸脚本）自动短路。
    任一级显式给出 False 即关闭——关闭时空响应不重试，行为与既往逐字节一致。
    """
    try:
        import nonebot

        value = getattr(
            nonebot.get_driver().config, "bot_market_retry_on_empty", None
        )
        if value is not None:
            return bool(value)
    except Exception:  # noqa: BLE001, S110 - 未初始化场景静默落到下一级。
        pass
    raw = os.environ.get("BOT_MARKET_RETRY_ON_EMPTY")
    if raw is None or not str(raw).strip():
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def empty_backoff_sleep() -> None:
    """空响应重试前的退避（time.sleep 单点；测试 monkeypatch 本函数/常量）。"""
    time.sleep(_RETRY_BACKOFF_SECONDS)


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


def _fetch_moex_quote(timeout_seconds: float) -> IndexQuote | None:
    """MOEX ISS 备选源拉取；任何失败返回 None（该指数缺席，不拖垮整卡）。"""
    try:
        payload = http_get_json(
            _MOEX_URL,
            timeout=max(1.0, float(timeout_seconds)),
            max_bytes=_MAX_PAYLOAD_BYTES,
        )
    except Exception:  # noqa: BLE001 - 单源失败静默缺席，行情链路绝不抛。
        return None
    marketdata = payload.get("marketdata") if isinstance(payload, dict) else None
    if not isinstance(marketdata, dict):
        return None
    columns = marketdata.get("columns")
    rows = marketdata.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list) or not rows:
        return None
    row = rows[0] if isinstance(rows[0], list) else None
    if row is None or len(row) != len(columns):
        return None
    by_name = {str(name): value for name, value in zip(columns, row)}
    price = _as_float(by_name.get("CURRENTVALUE"))
    if price is None:
        price = _as_float(by_name.get("LASTVALUE"))
    change_pct = _as_float(by_name.get("LASTCHANGEPRC"))
    if price is None or change_pct is None:
        return None
    display = next(
        (name for secid, name, _group in _INDEX_UNIVERSE if secid == _MOEX_SECID),
        "俄罗斯MOEX",
    )
    return IndexQuote(
        name=display,
        code=_MOEX_SECID,
        price=price,
        change_pct=change_pct,
        change_abs=_as_float(by_name.get("LASTCHANGE")),
        source="moex_iss",
        as_of=time.time(),
        delayed=True,
        status="ok",
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
    fetched_at = time.time()  # 数据时间戳（墙钟），进缓存随快照保留。
    secids = ",".join(
        secid for secid, _name, _group in _INDEX_UNIVERSE if secid != _MOEX_SECID
    )
    # G2：东财限流=HTTP 200 空响应（空 JSON/缺行）→ 退避后至多重试 1 次；
    # 真异常（网络错/非 200）不重试；仍空照旧诚实降级且不缓存。
    attempts = 2 if retry_on_empty_enabled() else 1
    quotes: list[IndexQuote] = []
    for attempt in range(attempts):
        try:
            payload = _fetch_payload(secids, max(1.0, float(timeout_seconds)))
            quotes = [
                IndexQuote(
                    name=quote.name,
                    code=quote.code,
                    price=quote.price,
                    change_pct=quote.change_pct,
                    change_abs=quote.change_abs,
                    source="eastmoney",
                    as_of=fetched_at,
                    delayed=True,
                    status="ok",
                )
                for quote in _parse_quotes(payload)
            ]
        except Exception:  # noqa: BLE001 - 行情失败静默降级，不阻塞会话链路。
            quotes = []
            break  # 真异常不重试。
        if quotes or attempt + 1 >= attempts:
            break
        empty_backoff_sleep()
    # MOEX 走独立备选源：东财整体失败也允许只剩 MOEX 一条（有总比没有强）。
    moex = _fetch_moex_quote(timeout_seconds)
    if moex is not None:
        quotes.append(moex)
    if quotes:
        _CACHE = (now, tuple(quotes))
    return quotes


def _quote_group(quote: IndexQuote) -> str:
    for secid, _name, group in _INDEX_UNIVERSE:
        if quote.code == secid:
            return group
    return _OTHER_GROUP


def group_quotes(quotes: Sequence[IndexQuote]) -> dict[str, list[IndexQuote]]:
    """按 中国区/亚太/欧美(其他) 分组（保宇宙顺序）；空组剔除。"""
    grouped: dict[str, list[IndexQuote]] = {group: [] for group in _GROUP_ORDER}
    grouped.setdefault(_OTHER_GROUP, [])
    for quote in quotes:
        grouped.setdefault(_quote_group(quote), []).append(quote)
    return {name: rows for name, rows in grouped.items() if rows}


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
    """按 中国区/亚太/欧美 分组的纯文本行情快报；空结果给降级文案。

    H-01（2026-09-14）：末尾追加「暂无数据源」注记区——无源市场显式登记
    （见 INDEX_UNAVAILABLE），用户问「迪拜/阿联酋/澳门股指」时卡面与文本
    都有明确交代，绝不静默消失、更不造数。
    """
    if not quotes:
        return _empty_degraded_text()
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
    entries = index_unavailable_entries()
    if entries:
        lines.append(
            "暂无数据源：" + "；".join(f"{name}（{reason}）" for name, reason in entries)
        )
    return "\n".join(lines)


# ==================== F19 指数走势（30 日收盘，折线卡用） ====================
# end=20500101：2026-09-13 实测该接口缺 end 参数时返回空 klines（疑似上游
# 行为变更，当日真实渲染验收抓到），显式带上远期上界拿「最近 N 根」。
_KLINE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid={secid}&fields1=f1&fields2=f51,f53&klt=101&fqt=1&lmt={days}"
    "&end=20500101"
)
_TREND_CACHE_TTL_SECONDS = 600.0
_TREND_MAX_POINTS = 60
_TREND_CACHE: dict[str, tuple[float, tuple[float, ...]]] = {}

# MOEX ISS 历史端点（2026-09-13 实测可达）：/iss/history 按 TRADEDATE 升序
# 全量分页（1997 年起 7000+ 行），借 history.cursor 的 TOTAL 取尾部窗口，
# 令 MOEX 也拿到真实走势（替代此前「暂无历史走势数据」的缺口展示）。
_MOEX_HISTORY_URL = (
    "https://iss.moex.com/iss/history/engines/stock/markets/index/boards/SNDX"
    "/securities/IMOEX.json?iss.meta=off&iss.only=history,history.cursor&start={start}"
)
_MOEX_TREND_POINTS = 30


def reset_market_trend_cache() -> None:
    """清空走势缓存（测试用）。"""
    _TREND_CACHE.clear()


def _retry_transient(fetch, *, attempts: int = 3):
    """push2his 瞬断退避重试（H-04，2026-09-14）。

    语义与 ``commodities_data._retry_transient`` / ``stock_data._network_retry``
    逐字对齐：ParseHttpError / ConnectionError / TimeoutError 视为瞬断，
    退避后至多重试 3 次；其他异常原样抛（真异常不重试的纪律不变）。
    背景：2026-09-13 vis3 实测 push2his 会 RemoteDisconnected，且本席
    2026-09-14 真机探测时同样多次复现——指数走势此前是三大取数点中唯一
    未接瞬断重试的一个。
    """
    last_exc: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return fetch()
        except (ParseHttpError, ConnectionError, TimeoutError) as exc:
            last_exc = exc
            if attempt + 1 >= attempts:
                raise
            empty_backoff_sleep()
    raise last_exc if last_exc is not None else RuntimeError("unreachable")  # pragma: no cover


def _fetch_moex_trend(timeout_seconds: float) -> tuple[float, ...]:
    """MOEX 指数近 30 日收盘（ISS history 尾部窗口）；失败返回空元组。"""

    def _get(start: int) -> Any:
        return http_get_json(
            _MOEX_HISTORY_URL.format(start=start),
            timeout=max(1.0, float(timeout_seconds)),
            max_bytes=_MAX_PAYLOAD_BYTES,
        )

    try:
        first = _get(0)
        cursor = first.get("history.cursor") if isinstance(first, dict) else None
        total = 0
        if isinstance(cursor, dict):
            columns = cursor.get("columns") or []
            rows = cursor.get("data") or []
            if rows and "TOTAL" in columns:
                total = int(rows[0][columns.index("TOTAL")])
        if total <= 0:
            return ()
        payload = _get(max(0, total - _MOEX_TREND_POINTS))
        history = payload.get("history") if isinstance(payload, dict) else None
        columns = history.get("columns") if isinstance(history, dict) else None
        rows = history.get("data") if isinstance(history, dict) else None
        if not isinstance(columns, list) or not isinstance(rows, list):
            return ()
        close_idx = columns.index("CLOSE")
        closes = [
            float(row[close_idx])
            for row in rows
            if len(row) > close_idx and row[close_idx] is not None
        ]
        return tuple(closes[-_MOEX_TREND_POINTS:])
    except Exception:  # noqa: BLE001 - 单源失败静默缺席，不拖垮行情卡。
        return ()


def fetch_index_trend(
    secid: str,
    *,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _TREND_CACHE_TTL_SECONDS,
) -> tuple[float, ...]:
    """单个指数近 30 日收盘序列（旧→新）；失败/无数据返回空元组，绝不抛。

    东财 kline 单指数一调；MOEX 走 ISS history 尾部窗口（两次分页请求）。
    10 分钟进程内缓存：18 指数逐个外呼较重，折线不需要实时；失败（空序列）
    不缓存，下一次调用立即重试。
    """
    cached = _TREND_CACHE.get(secid)
    now = time.monotonic()
    if cached is not None and now - cached[0] <= max(1.0, float(cache_seconds)):
        return cached[1]
    closes: tuple[float, ...] = ()
    if secid == _MOEX_SECID:
        closes = _fetch_moex_trend(timeout_seconds)
        if closes:
            _TREND_CACHE[secid] = (now, closes)
        return closes

    def _get() -> Any:
        return http_get_json(
            _KLINE_URL.format(
                secid=urllib.parse.quote(secid), days=_TREND_MAX_POINTS
            ),
            timeout=max(1.0, float(timeout_seconds)),
            max_bytes=_MAX_PAYLOAD_BYTES,
        )

    # G2：东财 kline 空响应（空 JSON/缺行）退避后至多重试 1 次；瞬断
    # （ParseHttpError/ConnectionError/TimeoutError，H-04）走 _retry_transient
    # （至多 3 次退避，与 commodities_data 同款）；其他真异常不重试；
    # 仍空照旧不缓存（「空结果不缓存」纪律不变）。
    attempts = 2 if retry_on_empty_enabled() else 1
    for attempt in range(attempts):
        try:
            payload = _retry_transient(_get)
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
        except Exception:  # noqa: BLE001 - 走势失败静默缺席，不拖垮行情卡。
            closes = ()
            break  # 真异常不重试。
        if closes or attempt + 1 >= attempts:
            break
        empty_backoff_sleep()
    if closes:
        _TREND_CACHE[secid] = (now, closes)
    return closes


# ==================== 北向资金（金融 Phase-1 扩容，2026-09-13） ====================
# 诚实边界（2026-09-13 本机实测）：2024-08-19 起交易所调整沪深股通披露口径，
# 当日净买入不再公开。两条候选通道实测均如此——
# - datacenter ``RPT_MUTUAL_DEAL_HISTORY``：北向（001 沪股通 / 003 深股通）行的
#   NET_DEAL_AMT / BUY_AMT / SELL_AMT / FUND_INFLOW 全部为 null；
# - push2 ``kamt/get``：hk2sh/hk2sz 的 dayNetAmtIn 恒 0.0 占位（年净流入=额度
#   阈值的占位数）。
# 因此本模块只提供仍在披露的真实字段：当日成交总额（DEAL_AMT）、成交笔数
# （DEAL_NUM）、领涨股、对应指数收盘/涨跌幅。净买入字段结构性缺席，本模块
# 不输出任何净买入数字（不造 0、不猜数），能力层文案显式说明口径。
#
# DEAL_AMT 量纲实证：2026-09-11 沪股通 DEAL_AMT=142256.09、DEAL_NUM=7,114,374
# → 按「百万元」读 = 1422.56 亿元、每笔约 2 万元（合理）；按「万元」读 =
# 14.2 亿元、每笔 200 元（荒谬）→ 量纲取百万元，展示换算 亿元 = 原值/100。

_NORTHBOUND_URL = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get"
    "?reportName=RPT_MUTUAL_DEAL_HISTORY&columns=ALL&source=WEB&client=WEB"
    "&filter=(MUTUAL_TYPE%3D%22{mutual_type}%22)"
    "&sortColumns=TRADE_DATE&sortTypes=-1&pageNumber=1&pageSize=1"
)
# MUTUAL_TYPE 实测：001 行 INDEX_CLOSE_PRICE=上证收盘、003 行=深证成指收盘
# → 001=沪股通、003=深股通（002/004 为南向，暂不接入）。
_NORTHBOUND_TYPES: tuple[tuple[str, str, str], ...] = (
    ("001", "沪股通", "上证指数"),
    ("003", "深股通", "深证成指"),
)
_NORTHBOUND_SOURCE = "eastmoney_datacenter"
_NORTHBOUND_CACHE_TTL_SECONDS = 300.0
_NORTHBOUND_CACHE: tuple[float, tuple[NorthboundFlow, ...]] | None = None


@dataclass(frozen=True)
class NorthboundFlow:
    """单条沪深股通当日成交快照（净买入自 2024-08 起无公开数据，不设字段）。"""

    name: str  # 沪股通 / 深股通
    mutual_type: str  # 001 / 003
    trade_date: str  # 交易日 YYYY-MM-DD
    deal_amt_yi: float | None  # 当日成交总额（亿元）
    deal_num: int | None  # 成交笔数
    lead_stock: str  # 领涨股名称
    lead_stock_pct: float | None  # 领涨股涨跌幅 %
    index_name: str  # 对应指数（上证指数/深证成指）
    index_close: float | None
    index_change_pct: float | None
    source: str = _NORTHBOUND_SOURCE
    as_of: float | None = None
    delayed: bool = True
    status: str = "ok"


def _northbound_first_row(payload: Any) -> dict[str, Any] | None:
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("data") if isinstance(result, dict) else None
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def _parse_northbound_flow(
    mutual_type: str, name: str, index_name: str, row: dict[str, Any], fetched_at: float
) -> NorthboundFlow | None:
    """行 → 快照；缺交易日/全部数值缺失返回 None（该通道缺席不造行）。"""
    trade_date = str(row.get("TRADE_DATE") or "").strip()[:10]
    if not trade_date:
        return None
    deal_amt = _as_float(row.get("DEAL_AMT"))
    deal_num = _as_float(row.get("DEAL_NUM"))
    return NorthboundFlow(
        name=name,
        mutual_type=mutual_type,
        trade_date=trade_date,
        deal_amt_yi=deal_amt / 100.0 if deal_amt is not None else None,
        deal_num=int(deal_num) if deal_num is not None else None,
        lead_stock=str(row.get("LEAD_STOCKS_NAME") or "").strip(),
        lead_stock_pct=_as_float(row.get("LS_CHANGE_RATE")),
        index_name=index_name,
        index_close=_as_float(row.get("INDEX_CLOSE_PRICE")),
        index_change_pct=_as_float(row.get("INDEX_CHANGE_RATE")),
        source=_NORTHBOUND_SOURCE,
        as_of=fetched_at,
        delayed=True,
        status="ok",
    )


def _fetch_northbound_channel(
    mutual_type: str, timeout_seconds: float
) -> Any:
    """单通道网络出口（测试 monkeypatch 本函数按 mutual_type 拦截）。"""
    return http_get_json(
        _NORTHBOUND_URL.format(mutual_type=mutual_type),
        timeout=max(1.0, float(timeout_seconds)),
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


def reset_northbound_cache() -> None:
    """清空北向资金进程内缓存（测试与运维手动刷新用）。"""
    global _NORTHBOUND_CACHE
    _NORTHBOUND_CACHE = None


def fetch_northbound_flows(
    timeout_seconds: float = 6.0,
    cache_seconds: float = _NORTHBOUND_CACHE_TTL_SECONDS,
) -> list[NorthboundFlow]:
    """拉取沪股通/深股通当日成交快照；失败返回 []，绝不抛异常。

    两通道各自独立拉取、独立降级（单通道失败不拖垮另一通道）；每通道
    G2 纪律：空响应退避重试 1 次，真异常不重试；任一通道成功即进 TTL
    缓存（缓存成功子集，单通道缺席在卡面诚实标注；两通道全失败不缓存，
    下轮查询重试。默认 5 分钟，数据按交易日更新）。
    """
    global _NORTHBOUND_CACHE
    now = time.monotonic()
    cached = _NORTHBOUND_CACHE
    if cached is not None and now - cached[0] <= max(0.0, float(cache_seconds)):
        return list(cached[1])
    fetched_at = time.time()
    flows: list[NorthboundFlow] = []
    for mutual_type, name, index_name in _NORTHBOUND_TYPES:
        attempts = 2 if retry_on_empty_enabled() else 1
        flow: NorthboundFlow | None = None
        for attempt in range(attempts):
            try:
                payload = _fetch_northbound_channel(mutual_type, timeout_seconds)
                row = _northbound_first_row(payload)
                if row is not None:
                    flow = _parse_northbound_flow(
                        mutual_type, name, index_name, row, fetched_at
                    )
            except Exception:  # noqa: BLE001 - 单通道失败静默缺席。
                flow = None
                break  # 真异常不重试。
            if flow is not None or attempt + 1 >= attempts:
                break
            empty_backoff_sleep()
        if flow is not None:
            flows.append(flow)
    if flows:
        _NORTHBOUND_CACHE = (now, tuple(flows))
    return flows


def format_northbound_brief(flows: Sequence[NorthboundFlow]) -> str:
    """北向资金纯文本快报：只报仍在披露的口径（成交总额等），空给降级文案。"""
    if not flows:
        # 审查 Q-01：入 user_copy 数据源失败池（原「……晚点再试试？」）。
        return random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(
            reason="北向资金数据暂时拉不到"
        )
    lines = ["北向资金速览（沪深股通）"]
    trade_dates = sorted({flow.trade_date for flow in flows})
    if trade_dates:
        lines.append(f"交易日 {trade_dates[-1]} · 收盘披露口径")
    for flow in flows:
        amount = (
            f"{flow.deal_amt_yi:,.2f} 亿元" if flow.deal_amt_yi is not None else "暂无"
        )
        line = f"{flow.name} 当日成交总额 {amount}"
        if flow.deal_num is not None:
            line += f"（{flow.deal_num:,} 笔）"
        lines.append(line)
        if flow.index_close is not None:
            pct = (
                f"{flow.index_change_pct:+.2f}%"
                if flow.index_change_pct is not None
                else ""
            )
            lines.append(f"{flow.name}参考·{flow.index_name}收盘 {flow.index_close:.2f} {pct}".rstrip())
        if flow.lead_stock:
            pct = (
                f"{flow.lead_stock_pct:+.2f}%"
                if flow.lead_stock_pct is not None
                else ""
            )
            lines.append(f"领涨股 {flow.lead_stock} {pct}".rstrip())
    lines.append("注：2024-08 起交易所不再披露北向当日净买入，本卡不含净买入口径。")
    return "\n".join(lines)

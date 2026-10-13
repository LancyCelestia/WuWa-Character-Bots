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

import math
import os
import random
import re
import statistics
import time
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# 审查 Q-01：user_copy 为零依赖纯常量池（模块纪律禁 import），sources 跨层
# 引用不构成装配环（包 __init__ 仅 docstring），与 contracts 同为低层共享面。
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
    http_get,
    http_get_json,
    http_get_text,
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


# ==================== FIN-R1（2026-09-27 评审票）：每命令一条端到端网络预算 ====
# 真身复用 chat_reply/runtime/deadline.DeadlineBudget（单调时钟，与聊天请求
# 预算同款），本票不另造第二套计时框架；deadline 为惰性导入——其包初始化会
# 拉起 pipeline，模块顶层反向 import 构成启动环，函数级导入绕开。
# 预算在能力入口创建、沿数据层传递；未传入时取数入口自造兜底（per-call）。
# 语义纪律不变：预算尽 ⇒ 弃剩余重试、不发起新网络调用，走既有「失败不缓存、
# 静默缺席」诚实降级；绝不因预算抛穿到会话链路。
_FINANCE_NETWORK_BUDGET_SECONDS = 30.0  # 新键候选 bot_market_command_budget_seconds（未自加）。


def new_network_budget() -> Any:
    """创建一条端到端网络预算（DeadlineBudget 复用，非第二套计时框架）。

    导入异常（如启动期循环导入窗口）⇒ 返回 None＝不拦截，退回本票之前的
    既有行为；数据层入口对 None 预算全部按「未配置」短路，绝不因预算件本身
    把取数打挂（本仓纪律：数据层不向会话链路抛异常）。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline import (
            DeadlineBudget,
        )
    except Exception:  # noqa: BLE001 - 取数层不因预算件失败而中断。
        return None

    return DeadlineBudget(_FINANCE_NETWORK_BUDGET_SECONDS)


def _budget_or_new(budget: Any | None) -> Any:
    return budget if budget is not None else new_network_budget()


def budget_expired(budget: Any | None) -> bool:
    """预算到期判定；未配置（None）视为不拦截（保持旧调用方行为）。"""
    return bool(budget is not None and budget.expired())


def budget_allows_retry(budget: Any | None) -> bool:
    """剩余预算是否还放得下「一次退避睡眠」；未配置视为允许。

    预算连 ``_RETRY_BACKOFF_SECONDS`` 都不剩时，起新一轮请求只会把
    超支烧到调用线程（有界聊天 worker）头上——直接弃剩余重试。
    """
    if budget is None:
        return True
    return budget.remaining_seconds() > _RETRY_BACKOFF_SECONDS


def gather_within_budget(
    fetch, keys: Sequence[Any], *, budget: Any | None = None, max_workers: int = 6
) -> dict:
    """并行取数、预算内收结果、**线程池退出非阻塞**（FIN-R1②）。

    与旧 ``with ThreadPoolExecutor`` + ``future.result`` 结构对比：
    * ``wait(timeout=剩余预算)`` 后只收已完成项；
    * 未完成/失败项如实记 None（由调用方换算成缺席展示），未开跑的
      future 直接 cancel；
    * 共享池（``domains/core/shared_pool``，P2 减量波起替代逐次新建）
      绝不 shutdown：未完成 future 显式 cancel 后即刻返回——慢源被放弃
      为「缺席」，有界聊天 worker 即刻归还，不再出现「一条行情命令钉死
      worker 分钟级」（FIN-R1② 语义不变）。

    ``max_workers`` 形参保留以兼容既有调用，共享池下为建议值（实际并发
    受全局 8 workers 上限与兄弟站点占用约束）。
    """
    from concurrent.futures import wait as futures_wait

    from plugins.bot_unified_runtime.domains.core.shared_pool import (
        get_shared_pool,
    )

    budget = _budget_or_new(budget)
    pool = get_shared_pool()
    futures = {key: pool.submit(fetch, key) for key in keys}
    futures_wait(list(futures.values()), timeout=max(0.0, budget.remaining_seconds()))
    results: dict[Any, Any] = {}
    for key, future in futures.items():
        if future.done():
            try:
                results[key] = future.result()
            except Exception:  # noqa: BLE001 - 单项失败如实缺席，语义与旧结构一致。
                results[key] = None
        else:
            future.cancel()
            results[key] = None
    return results


# ==================== FIN-I1（2026-09-27 评审票）：远端自由文本清洗 ============
# 远端字符串（个股 f14 / 北向领涨股名）进展示字段前在数据边界做一次
# 「控制字符清洗 + 长度钳制（截断加省略号）」——纯格式卫生，不动任何信任
# 语义；None≠0 纪律不受影响（空值仍空）。卡片 DOM 结构与渲染契约零改动。
_REMOTE_TEXT_MAX_CHARS = 40
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def sanitize_remote_text(value: Any, max_chars: int = _REMOTE_TEXT_MAX_CHARS) -> str:
    """远端自由文本 → 可打印单行短文本（C0/C1/换行折叠为空格，超长钳制）。"""
    text = str(value or "")
    cleaned = "".join(ch if ch.isprintable() else " " for ch in text)
    cleaned = _WHITESPACE_RUN_RE.sub(" ", cleaned).strip()
    limit = max(1, int(max_chars))
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


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
    """fltt=2 下正常值是小数/整数；停牌或缺数时可能是 "-" 或缺失。

    FIN-N1（2026-09-27 评审票）：上游 JSON 可携带 ``NaN``/``Infinity`` 字面量
    （``json.loads`` 默认接受），非有限值一律视为缺数（None）——走既有
    「暂无数据」诚实通道，绝不让 "nan"/"inf" 字样进卡片数字槽。
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
    *,
    budget: Any | None = None,
) -> list[IndexQuote]:
    """拉取全球股指快照；失败返回 []，绝不抛异常。

    成功结果带进程内 TTL 缓存（默认 60s），避免同群连发消息时打爆接口；
    失败不缓存，下一次调用立即重试。FIN-R1：预算尽 ⇒ 弃剩余重试（含 MOEX
    备选源不再发起），诚实降级路径不变。
    """
    global _CACHE
    now = time.monotonic()
    cached = _CACHE
    if cached is not None and now - cached[0] <= max(0.0, float(cache_seconds)):
        return list(cached[1])
    budget = _budget_or_new(budget)
    fetched_at = time.time()  # 数据时间戳（墙钟），进缓存随快照保留。
    secids = ",".join(
        secid for secid, _name, _group in _INDEX_UNIVERSE if secid != _MOEX_SECID
    )
    # G2：东财限流=HTTP 200 空响应（空 JSON/缺行）→ 退避后至多重试 1 次；
    # 真异常（网络错/非 200）不重试；仍空照旧诚实降级且不缓存。
    attempts = 2 if retry_on_empty_enabled() else 1
    quotes: list[IndexQuote] = []
    for attempt in range(attempts):
        if budget_expired(budget):
            break  # FIN-R1：预算尽不发起新网络调用（失败不缓存纪律不变）。
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
        if quotes or attempt + 1 >= attempts or not budget_allows_retry(budget):
            break
        empty_backoff_sleep()
    # MOEX 走独立备选源：东财整体失败也允许只剩 MOEX 一条（有总比没有强）。
    moex = None if budget_expired(budget) else _fetch_moex_quote(timeout_seconds)
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


# ==================== 指数全成分分布（箱形图数据面，2026-10-12） ====================
# 用户裁定「股指箱型＝全成分股分布」。取数口＝东财数据中心成分表 + 实时行情注入
# （quoteColumns=f2,f3，与 data.eastmoney.com/other/index/ 现网页面同款单调用口；
# 2026-10-12 本机实测：000300 与 000001 均按页返回成员 × f2/f3）。每指数分页取
# 全成员，逐成员取 f3（当日涨跌幅 %）构成横截面分布。
# 诚实铁律：任一页失败/超页上限 ⇒ 整指数返回空（缺席），绝不用半截样本画箱；
# 也绝不用「单日 OHLC 四价位」冒充分布（finance_chart 口径红线调用方一侧）。
_MEMBER_REPORT_URL = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get"
    "?reportName=RPT_INDEX_COMPONENT"
    "&columns=SECURITY_CODE"
    "&quoteColumns=f2,f3"
    "&filter=(INDEX_CODE%3D%22{index_code}%22)"
    "&pageNumber={page}"
    "&pageSize=500"
    "&source=WEB&client=WEB"
)
_MEMBER_TTL_SECONDS = 600.0
_MEMBER_MAX_PAGES = 12  # 500/页 ⇒ 最多 6000 成员；翻满仍有整页即判异常走缺席。
# secid → (monotonic 时间戳, ((代码, 当日涨跌幅%), …))
_MEMBER_CACHE: dict[str, tuple[float, tuple[tuple[str, float], ...]]] = {}

# secid 面：仅中国区五枚有成分源（其余市场结构性缺席，不假装有）。
_MEMBER_SECIDS: tuple[str, ...] = (
    "1.000001",  # 上证指数
    "0.399001",  # 深证成指
    "0.399006",  # 创业板指
    "1.000003",  # 上证B股
    "0.399003",  # 深证B股
)


def reset_member_cache() -> None:
    """清空成分分布缓存（测试与运维手动刷新用）。"""
    _MEMBER_CACHE.clear()


def member_index_code(secid: str) -> str | None:
    """secid → 成分表 INDEX_CODE；不在成分源面的市场返回 None。"""
    if secid not in _MEMBER_SECIDS:
        return None
    return secid.split(".", 1)[1]


def _fetch_member_page(index_code: str, page: int, timeout_seconds: float) -> Any:
    """单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    return http_get_json(
        _MEMBER_REPORT_URL.format(index_code=index_code, page=page),
        timeout=timeout_seconds,
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


def _fetch_member_rows(
    index_code: str, *, timeout_seconds: float, budget: Any | None
) -> tuple[tuple[str, float], ...]:
    """分页拉全成员 (代码, 当日涨跌幅%)；任一页失败/超页上限 ⇒ () 且不缓存。"""
    pairs: list[tuple[str, float]] = []
    for page in range(1, _MEMBER_MAX_PAGES + 1):
        if budget_expired(budget):
            return ()  # FIN-R1：预算尽不发起新网络调用，失败不缓存。
        try:
            payload = _fetch_member_page(
                index_code, page, max(1.0, float(timeout_seconds))
            )
        except Exception:  # noqa: BLE001 - 取数层不向会话链路抛。
            return ()
        result = payload.get("result") if isinstance(payload, dict) else None
        rows = result.get("data") if isinstance(result, dict) else None
        # 末页收尾：东财对**越界空页**返 success=false／result=null／code=9201
        # （message「返回数据为空」，是「没数据」而非错误）⇒ 先看 data：空页
        # （page>1）即正常收尾。旧逻辑先判 success，会把「成员数恰为 500 整数倍」
        # 的指数（如深证成指 399001＝500 只，第 2 页即空）整条丢空（2026-10-13 实测）。
        if not isinstance(rows, list) or not rows:
            if page == 1:
                return ()
            break  # 末页空=正常收尾。
        if payload.get("success") is not True:
            return ()
        for row in rows:
            if isinstance(row, dict):
                change = _as_float(row.get("f3"))
                code = str(row.get("SECURITY_CODE") or "").strip()
                if change is not None and code:
                    pairs.append((code, change))
        if len(rows) < 500:
            break
    else:
        return ()  # 翻满上限仍有整页 ⇒ 判异常，不拿截断样本画箱。
    return tuple(pairs)


def fetch_index_member_pairs(
    secid: str,
    *,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _MEMBER_TTL_SECONDS,
    budget: Any | None = None,
) -> tuple[tuple[str, float], ...]:
    """全成分股 (代码, 当日涨跌幅 %) 横截面；不可得返回 ()，绝不抛异常。

    分页拉全成员（500/页）；任一页失败/超页上限 ⇒ () 且不缓存（「失败不缓存、
    下次立即可重试」与行情主链同纪律）。成功结果带进程内 TTL 缓存（缺省 10 分钟：
    成分表低频变动，行情注入随请求实时）。代码面供三源批量报价腿复用
    （``crosscheck_member_distribution`` 以同一批代码向腾讯/新浪取独立涨跌幅）。
    """
    index_code = member_index_code(secid)
    if index_code is None:
        return ()
    now = time.monotonic()
    cached = _MEMBER_CACHE.get(secid)
    if cached is not None and now - cached[0] <= max(0.0, float(cache_seconds)):
        return cached[1]
    pairs = _fetch_member_rows(
        index_code, timeout_seconds=timeout_seconds, budget=budget
    )
    if not pairs:
        return ()
    _MEMBER_CACHE[secid] = (now, pairs)
    return pairs


def fetch_index_member_changes(
    secid: str,
    *,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _MEMBER_TTL_SECONDS,
    budget: Any | None = None,
) -> tuple[float, ...]:
    """全成分股当日涨跌幅 % 横截面（f3）；不可得返回 ()，绝不抛异常。

    旧签名保留（卡面箱形图只消费涨跌幅序列）；代码面见
    ``fetch_index_member_pairs``。分页/缓存纪律逐字不变。
    """
    return tuple(
        change
        for _code, change in fetch_index_member_pairs(
            secid,
            timeout_seconds=timeout_seconds,
            cache_seconds=cache_seconds,
            budget=budget,
        )
    )


# ==================== 成分股批量报价腿（腾讯 / 新浪，2026-10-13 三源硬门） ======
# 三源硬门（AGENTS 规则 12）：东财 ``RPT_INDEX_COMPONENT`` 是唯一「成分表＋涨跌幅」
# 一次拿齐的腿；腾讯 ``qt.gtimg.cn`` 与新浪 ``hq.sinajs.cn`` 的**批量报价口**对
# 同一批成分代码各自取到涨跌幅，构成第二/第三腿。2026-10-13 本机实测：
# - 腾讯 ``q=sh600000,sz000001,…`` 50/200/500/800 只全回无截断（GBK，~0.2s）；
# - 新浪 ``list=…`` 须 Referer，同上全回（GB18030，~0.2s）；
# - 三源同批分布（n/均值/中位）一致（见 ``crosscheck_member_distribution``）。
# 口径诚实：成分名单由指数编制方定义，三条报价腿共用东财报表给出的名单
# （名单非市场数值，涨跌幅才是被佐证的量）；独立性落在「涨跌幅由不同机构各自发布」。
_MEMBER_QUOTE_TENCENT_URL = "https://qt.gtimg.cn/q={codes}"
_MEMBER_QUOTE_SINA_URL = "https://hq.sinajs.cn/list={codes}"
_MEMBER_QUOTE_SINA_REFERER = "https://finance.sina.com.cn"
_MEMBER_QUOTE_BATCH_SIZE = 400  # 单请求代码上限（实测 800 仍全回，留一倍余量）。
_MEMBER_QUOTE_TTL_SECONDS = 120.0
# (机构, 带前缀代码元组) → (monotonic 时间戳, {裸代码: 涨跌幅%})
_MEMBER_QUOTE_CACHE: dict[
    tuple[str, tuple[str, ...]], tuple[float, dict[str, float]]
] = {}

# 同量一致性容差（crosscheck_member_distribution 用）：
# 样本数相对差 ≤ 2%；均值/中位数差 ≤ 0.05 个百分点。分歧超容差即点名，绝不取平均掩盖。
_MEMBER_DIST_COUNT_TOLERANCE_RATIO = 0.02
_MEMBER_DIST_STAT_TOLERANCE_PP = 0.05


def member_quote_prefix(code: str) -> str | None:
    """A 股 6 位代码 → 交易所前缀（沪 ``sh`` / 深 ``sz`` / 北 ``bj``）；非 A 股返回 None。"""
    text = str(code or "").strip()
    if len(text) != 6 or not text.isdigit():
        return None
    head = text[0]
    if head in "69":  # 600/601/603/605/688 沪A；900 沪B
        return "sh"
    if head in "023":  # 000/001/002/003 深A；200 深B；300/301 创业板
        return "sz"
    if head in "48":  # 4xx/8xx 北交所
        return "bj"
    return None


def _tagged_member_codes(codes: Sequence[str]) -> tuple[str, ...]:
    """裸代码 → 带交易所前缀的报价代码；非 A 股代码剔除（宁缺不编）。"""
    tagged: list[str] = []
    for code in codes:
        prefix = member_quote_prefix(code)
        if prefix is not None:
            tagged.append(prefix + str(code).strip())
    return tuple(tagged)


def _member_quote_batches(tagged: Sequence[str]) -> list[tuple[str, ...]]:
    """按单请求上限切批（实测 800 只一次全回，400 留一倍余量）。"""
    size = max(1, int(_MEMBER_QUOTE_BATCH_SIZE))
    return [tuple(tagged[i : i + size]) for i in range(0, len(tagged), size)]


def _fetch_member_quotes_tencent(
    tagged: Sequence[str], timeout_seconds: float
) -> dict[str, float]:
    """腾讯批量报价单点出口（测试 monkeypatch 本函数即可拦截外呼）。

    全格式行 ``v_sz000001="…~涨跌幅(字段 32)~…"``（GBK）；脏行/缺行静默跳过。
    返回 {裸代码: 涨跌幅%}。仅用于股票全格式行，指数短格式（``s_sh…``）不走本口。
    """
    if not tagged:
        return {}
    url = _MEMBER_QUOTE_TENCENT_URL.format(codes=",".join(tagged))
    _final, body = http_get(
        url, timeout=max(1.0, float(timeout_seconds)), max_bytes=_MAX_PAYLOAD_BYTES
    )
    text = body.decode("gbk", errors="replace")
    out: dict[str, float] = {}
    for tagged_code in tagged:
        marker = f'v_{tagged_code}="'
        start = text.find(marker)
        if start < 0:
            continue
        record = text[start + len(marker) : text.find('"', start + len(marker))]
        fields = record.split("~")
        try:
            pct = float(fields[32])
        except (IndexError, ValueError):
            continue
        # FIN-N1：数据边界统一有限性闸，非有限值如实跳过。
        if math.isfinite(pct):
            out[tagged_code[2:]] = pct
    return out


def _fetch_member_quotes_sina(
    tagged: Sequence[str], timeout_seconds: float
) -> dict[str, float]:
    """新浪批量报价单点出口（测试 monkeypatch 本函数即可拦截外呼）。

    须带 ``Referer``（2026-10-13 实测无头 403）；载荷 GB18030。新浪股票行不给
    涨跌幅字段 ⇒ 由 ``(现价[3] − 昨收[2]) / 昨收[2] × 100`` 现算。返回 {裸代码: 涨跌幅%}。
    """
    if not tagged:
        return {}
    url = _MEMBER_QUOTE_SINA_URL.format(codes=",".join(tagged))
    _final, text = http_get_text(
        url,
        timeout=max(1.0, float(timeout_seconds)),
        referer=_MEMBER_QUOTE_SINA_REFERER,
        encoding="gb18030",
        max_bytes=_MAX_PAYLOAD_BYTES,
    )
    out: dict[str, float] = {}
    for tagged_code in tagged:
        marker = f'var hq_str_{tagged_code}="'
        start = text.find(marker)
        if start < 0:
            continue
        record = text[start + len(marker) : text.find('"', start + len(marker))]
        parts = record.split(",")
        try:
            prev_close = float(parts[2])
            price = float(parts[3])
        except (IndexError, ValueError):
            continue
        if prev_close > 0 and math.isfinite(price):
            pct = (price - prev_close) / prev_close * 100.0
            if math.isfinite(pct):
                out[tagged_code[2:]] = pct
    return out


_MEMBER_QUOTE_FETCHERS = {
    "腾讯": _fetch_member_quotes_tencent,
    "新浪": _fetch_member_quotes_sina,
}


def reset_member_quote_cache() -> None:
    """清空成分股批量报价缓存（测试与运维用）。"""
    _MEMBER_QUOTE_CACHE.clear()


def fetch_member_quotes(
    codes: Sequence[str],
    org: str,
    *,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _MEMBER_QUOTE_TTL_SECONDS,
    budget: Any | None = None,
) -> dict[str, float]:
    """对同一批成分代码向指定机构取当日涨跌幅 %；不可得返回 {}，绝不抛异常。

    批量口（腾讯/新浪）；按 ``_MEMBER_QUOTE_BATCH_SIZE`` 切批、逐批失败即整腿
    缺席（不拿半截样本）。成功结果带进程内 TTL 缓存；失败不缓存（下次立即重试）。
    """
    fetcher = _MEMBER_QUOTE_FETCHERS.get(org)
    tagged = _tagged_member_codes(codes)
    if fetcher is None or not tagged:
        return {}
    key = (org, tagged)
    now = time.monotonic()
    cached = _MEMBER_QUOTE_CACHE.get(key)
    if cached is not None and now - cached[0] <= max(0.0, float(cache_seconds)):
        return dict(cached[1])
    merged: dict[str, float] = {}
    for batch in _member_quote_batches(tagged):
        if budget_expired(budget):
            return {}  # FIN-R1：预算尽不发起新网络调用，失败不缓存。
        try:
            merged.update(fetcher(batch, max(1.0, float(timeout_seconds))))
        except Exception:  # noqa: BLE001 - 取数层不向会话链路抛。
            return {}
    if not merged:
        return {}
    _MEMBER_QUOTE_CACHE[key] = (now, dict(merged))
    return merged


@dataclass(frozen=True)
class MemberDistribution:
    """一组涨跌幅的横截面分布摘要（同量比对用）。"""

    n: int
    mean: float | None
    median: float | None


@dataclass(frozen=True)
class MemberCrossCheck:
    """东财/腾讯/新浪同批成分涨跌幅分布一致性核对结果。"""

    orgs: tuple[str, ...]  # 参检机构（东财恒在）
    consistent: bool  # 三源 n/均值/中位均在容差内
    detail: str = ""  # 不一致/缺腿时点名说明
    distributions: tuple[tuple[str, MemberDistribution], ...] = ()


def _distribution(values: Sequence[float]) -> MemberDistribution:
    cleaned: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            cleaned.append(number)
    if not cleaned:
        return MemberDistribution(0, None, None)
    return MemberDistribution(
        len(cleaned), statistics.fmean(cleaned), statistics.median(cleaned)
    )


def crosscheck_member_distribution(
    secid: str,
    *,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _MEMBER_QUOTE_TTL_SECONDS,
    budget: Any | None = None,
) -> MemberCrossCheck:
    """东财/腾讯/新浪同批成分涨跌幅分布一致性核对（三源硬门佐证腿）。

    东财腿＝成分表＋涨跌幅（``fetch_index_member_pairs``）；腾讯/新浪腿＝对东财
    给出的成分代码各自批量取涨跌幅。在三腿都拿到的**公共样本**上比较样本数、
    均值、中位数：样本数相对差 ≤2% 且 均值/中位数差 ≤0.05 个百分点 ⇒ 一致。
    任一腿缺席或超容差 ⇒ ``consistent=False`` 且 ``detail`` 点名差在哪
    （绝不取平均掩盖分歧）。
    """
    pairs = fetch_index_member_pairs(
        secid,
        timeout_seconds=timeout_seconds,
        cache_seconds=_MEMBER_TTL_SECONDS,
        budget=budget,
    )
    if not pairs:
        return MemberCrossCheck((), False, "东财成分腿不可得")
    codes = [code for code, _change in pairs]
    em_map = {code: change for code, change in pairs}
    tencent = fetch_member_quotes(
        codes, "腾讯", timeout_seconds=timeout_seconds,
        cache_seconds=cache_seconds, budget=budget,
    )
    sina = fetch_member_quotes(
        codes, "新浪", timeout_seconds=timeout_seconds,
        cache_seconds=cache_seconds, budget=budget,
    )
    orgs = ("东方财富",) + (("腾讯",) if tencent else ()) + (("新浪",) if sina else ())
    missing = [name for name, leg in (("腾讯", tencent), ("新浪", sina)) if not leg]
    if missing:
        return MemberCrossCheck(orgs, False, f"缺腿：{'、'.join(missing)}")
    common = [code for code in codes if code in em_map and code in tencent and code in sina]
    if not common:
        return MemberCrossCheck(orgs, False, "三源无公共样本")
    dists = (
        ("东方财富", _distribution([em_map[code] for code in common])),
        ("腾讯", _distribution([tencent[code] for code in common])),
        ("新浪", _distribution([sina[code] for code in common])),
    )
    base = dists[0][1]
    problems: list[str] = []
    for name, dist in dists[1:]:
        if dist.mean is None or dist.median is None or base.mean is None or base.median is None:
            problems.append(f"{name} 无有效分布")
            continue
        if abs(dist.mean - base.mean) > _MEMBER_DIST_STAT_TOLERANCE_PP:
            problems.append(f"{name} 均值差 {abs(dist.mean - base.mean):.3f}pp")
        if abs(dist.median - base.median) > _MEMBER_DIST_STAT_TOLERANCE_PP:
            problems.append(f"{name} 中位差 {abs(dist.median - base.median):.3f}pp")
    count_slack = max(1, round(len(em_map) * _MEMBER_DIST_COUNT_TOLERANCE_RATIO))
    for name, leg in (("腾讯", tencent), ("新浪", sina)):
        if abs(len(leg) - len(em_map)) > count_slack:
            problems.append(f"{name} 样本数 {len(leg)}≠东财 {len(em_map)}")
    if problems:
        return MemberCrossCheck(orgs, False, "；".join(problems), dists)
    return MemberCrossCheck(orgs, True, f"同批 {len(common)} 只一致", dists)


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


def _retry_transient(fetch, *, attempts: int = 3, budget: Any | None = None):
    """push2his 瞬断退避重试（H-04，2026-09-14）。

    语义与 ``commodities_data._retry_transient`` / ``stock_data._network_retry``
    逐字对齐：ParseHttpError / ConnectionError / TimeoutError 视为瞬断，
    退避后至多重试 3 次；其他异常原样抛（真异常不重试的纪律不变）。
    背景：2026-09-13 vis3 实测 push2his 会 RemoteDisconnected，且本席
    2026-09-14 真机探测时同样多次复现——指数走势此前是三大取数点中唯一
    未接瞬断重试的一个。

    FIN-R1（2026-09-27 评审票）两条收紧：① 429 不跨层重试——链接层
    （http_util）已在单调用内尊重 Retry-After（60s 封顶）并重试到位，
    数据层再叠 3 次就是把 60s 睡眠按层相乘（worker 钉死的根因）；
    ② 退避睡眠受网络预算门控——剩余预算放不下一次退避即弃剩余尝试。
    """
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


def _fetch_moex_trend(timeout_seconds: float, *, budget: Any | None = None) -> tuple[float, ...]:
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
        if budget_expired(budget):
            return ()  # FIN-R1：分页第二跳起前查预算，尽则如实缺席。
        payload = _get(max(0, total - _MOEX_TREND_POINTS))
        history = payload.get("history") if isinstance(payload, dict) else None
        columns = history.get("columns") if isinstance(history, dict) else None
        rows = history.get("data") if isinstance(history, dict) else None
        if not isinstance(columns, list) or not isinstance(rows, list):
            return ()
        close_idx = columns.index("CLOSE")
        # FIN-N1：CLOSE 列经 _as_float 收口（含 isfinite 闸），裸 float() 会把
        # 上游 NaN/Infinity 字面量放行成 nan/inf 走势点。
        closes: list[float] = []
        for row in rows:
            if not isinstance(row, list) or len(row) <= close_idx:
                continue
            value = _as_float(row[close_idx])
            if value is not None:
                closes.append(value)
        return tuple(closes[-_MOEX_TREND_POINTS:])
    except Exception:  # noqa: BLE001 - 单源失败静默缺席，不拖垮行情卡。
        return ()


def fetch_index_trend(
    secid: str,
    *,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _TREND_CACHE_TTL_SECONDS,
    budget: Any | None = None,
) -> tuple[float, ...]:
    """单个指数近 30 日收盘序列（旧→新）；失败/无数据返回空元组，绝不抛。

    东财 kline 单指数一调；MOEX 走 ISS history 尾部窗口（两次分页请求）。
    10 分钟进程内缓存：18 指数逐个外呼较重，折线不需要实时；失败（空序列）
    不缓存，下一次调用立即重试。FIN-R1：整条拉取受端到端网络预算门控，
    预算尽弃剩余重试（仍走「失败不缓存、静默缺席」通道）。
    """
    cached = _TREND_CACHE.get(secid)
    now = time.monotonic()
    if cached is not None and now - cached[0] <= max(1.0, float(cache_seconds)):
        return cached[1]
    budget = _budget_or_new(budget)
    closes: tuple[float, ...] = ()
    if secid == _MOEX_SECID:
        if not budget_expired(budget):
            closes = _fetch_moex_trend(timeout_seconds, budget=budget)
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
        except Exception:  # noqa: BLE001 - 走势失败静默缺席，不拖垮行情卡。
            closes = ()
            break  # 真异常不重试。
        if closes or attempt + 1 >= attempts or not budget_allows_retry(budget):
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
        # FIN-I1：远端领涨股名在数据边界做控制字符清洗+长度钳制（一次收紧）。
        lead_stock=sanitize_remote_text(row.get("LEAD_STOCKS_NAME")),
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
    *,
    budget: Any | None = None,
) -> list[NorthboundFlow]:
    """拉取沪股通/深股通当日成交快照；失败返回 []，绝不抛异常。

    两通道各自独立拉取、独立降级（单通道失败不拖垮另一通道）；每通道
    G2 纪律：空响应退避重试 1 次，真异常不重试；任一通道成功即进 TTL
    缓存（缓存成功子集，单通道缺席在卡面诚实标注；两通道全失败不缓存，
    下轮查询重试。默认 5 分钟，数据按交易日更新）。FIN-R1：预算尽 ⇒
    弃剩余通道与剩余重试，缺席通道卡面如实标注。
    """
    global _NORTHBOUND_CACHE
    now = time.monotonic()
    cached = _NORTHBOUND_CACHE
    if cached is not None and now - cached[0] <= max(0.0, float(cache_seconds)):
        return list(cached[1])
    budget = _budget_or_new(budget)
    fetched_at = time.time()
    flows: list[NorthboundFlow] = []
    for mutual_type, name, index_name in _NORTHBOUND_TYPES:
        if budget_expired(budget):
            break  # FIN-R1：预算尽弃剩余通道（单通道缺席=既有诚实标注路径）。
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
            if flow is not None or attempt + 1 >= attempts or not budget_allows_retry(budget):
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

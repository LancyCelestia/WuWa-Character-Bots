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

**币种三态名册（2026-10-02 席位 F1，P7 汇率补齐）**：用户点名 11 币
（``REQUIRED_CURRENCIES``）里 RUB/CHF/CAD/AUD 四枚**没有任何已核实的报价腿**
——本仓与历史工单（``patches/S02-FINANCE-COVERAGE.md`` §2.1）都只把这四枚记为
「待验」，而「待验」不等于「有源」也不等于「无源」。所以三态分开登记，缺一态
即视为静默消失（锁 ``tests/test_fx_currency_coverage.py``）：

- ``sourced``＝进 ``_FX_PAIR_UNIVERSE`` 的行，且每枚 secid 在
  ``_FX_SOURCED_EVIDENCE`` 里有 (实测日期, 实测方式) 条目。**没凭据的行不许进
  宇宙表**（这是「为了齐全而编源」的唯一代码级防线）；
- ``unavailable``＝实测查无，登记在 ``FX_UNAVAILABLE_PAIRS`` ＋
  ``_FX_ABSENT_EVIDENCE``；
- ``pending``＝候选 secid 已列、真机未探，登记在 ``FX_PENDING_CANDIDATE_SECIDS``
  （含兜底腿 ``FX_PENDING_FALLBACK_LEGS``）。**候选绝不进宇宙表、绝不进面板、
  绝不被换算层引用**，用户问到该币时 ``fx_no_quote_reason`` 明写「未接入已核实
  报价源＋候选腿是谁＋还差哪一步」，不用估算、不用相近币种顶替。
  探测入口 ``probe_fx_candidates()`` 只给运维/验收用，生产链路不调用它。

兑换换算层：``fx_usd_bridge`` ＋ ``fx_derived_quote`` 只用 ``rate_type="spot"``
的行搭 USD 三角，产出 ``rate_type="derived"`` 并附口径说明（非中间价、非可成交
价）——缺任一腿即 ``None``。这条链路是模块头注从一开始就承诺的交叉价通路
（``cross_rate_from_usd``），2026-10-02 之前从未接进能力层，所以「英镑汇率／
韩元汇率／新加坡元汇率」这类「币名＋汇率」问句此前一律回「暂无数据」。

**备选源（provenance 快照链路）**：``open.er-api.com/v6/latest/{base}``
（免 key、覆盖面广）。**诚实边界：该端点在主代理环境实测同样不可达**，
``fetch_fx_snapshot`` 保持对外签名不变（capabilities/fx 按它对接），内部仍
走 er-api 出口、全部解析按 fixture 防御式实现：缺币种进
``missing_currencies`` 显式列出，绝不补 0；整体失败 ``status=unavailable``。

其它基准货币间的交叉价用 ``cross_rate_from_usd`` 纯函数按 USD 三角换算
（离线可验证），换不出给 None，不硬凑。两条链路任何失败都绝不抛异常。
"""

from __future__ import annotations

import math
import random
import re
import time
import urllib.parse
from collections.abc import Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

# 审查 Q-01：user_copy 为零依赖纯常量池，sources 跨层引用不构成装配环。
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.core.contracts.finance import (
    CurrencyQuote,
    FinanceDataStatus,
    FxRate,
    FxRateSnapshot,
    status_or_unknown,
)
from plugins.bot_unified_runtime.domains.finance.data.market_data import (
    _budget_or_new,
    budget_allows_retry,
    budget_expired,
    empty_backoff_sleep,
    retry_on_empty_enabled,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    http_get_json,
)

BASE_CURRENCY = "USD"

# 用户 2026-10-02 点名的 11 枚币种（席位需求书 §6）：这是「点名 ⊆ 已登记」对账
# 的尺，逐枚必须恰好落在三态名册之一（sourced / unavailable / pending），
# 由 tests/test_fx_currency_coverage.py 门②执法。顺序＝展示顺序，勿随意重排。
REQUIRED_CURRENCIES: tuple[str, ...] = (
    "USD",
    "EUR",
    "JPY",
    "KRW",
    "CNY",
    "HKD",
    "SGD",
    "RUB",
    "CHF",
    "CAD",
    "AUD",
)

# 快照链路（er-api 备选源）请求并逐币对账的目标集合＝点名清单 ∪ 在册历史清单。
# 币种数以本元组自身为准，叙述文档不手写计数（AGENTS 规则 10）。
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
    "RUB",
    "CHF",
    "CAD",
    "AUD",
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
            # FIN-N1：er-api 快照口径可带 Infinity 字面量（json.loads 默认接受），
            # 裸 ``rate > 0`` 挡不住 inf——补 math.isfinite 闸，非有限汇率不进表、
            # 记入 missing_currencies（缺数如实点名，绝不进汇率表、绝不乘进换算）。
            if isinstance(rate, float) and math.isfinite(rate) and rate > 0:
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

    任何输入缺失/非法（≤0、NaN、Infinity、溢出）返回 None——换不出来就承认
    换不出来。FIN-N1：``Infinity`` 能过 ``>0`` 却过不了 ``math.isfinite``，
    ``NaN`` 令 ``<=`` 恒假——两处都以有限闸收口，非有限值绝不外流被乘进总额。
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
            or not math.isfinite(float(value))
        ):
            return None
    result = float(quote_rate) / float(base_rate)  # type: ignore[arg-type]
    return result if result > 0 and math.isfinite(result) else None


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

# 「实测查无」这句话的唯一真身：覆盖表与用户可见的拒答文案同读此处，
# 不许出现第二份「暂无」措辞（S02 工单 §2.1 的两份「暂无」之诫）。
_FX_PAIR_ABSENT_NOTE = "东财无该货币对行情"

# ==================== 三态凭据名册（2026-10-02 席位 F1） ====================

# 有源凭据册：secid → (实测日期, 实测方式)。「有源」只认两种凭据——
# ① 本模块头注已自陈的「主代理 curl 实测」；② 后续波次真机重探并落日期＋响应形态。
# 宇宙表里出现无凭据的 secid ＝ 把待验/无源编成有源，门① 当场红。
# 注：120.USDCNYC 只是 ``_FX_PARITY_ALTERNATES`` 里的备用记录、不在取数链上，
# 故不占凭据条目（有凭据册只覆盖「真会外呼的 secid」）。
_FX_SOURCED_EVIDENCE: dict[str, tuple[str, str]] = {
    "133.USDCNH": ("2026-09-12", "主代理 curl 实测 ulist.np/get（模块头注在册）"),
    "120.EURCNYC": ("2026-09-12", "主代理 curl 实测 ulist.np/get（模块头注在册）"),
    "120.JPYCNYC": ("2026-09-12", "主代理 curl 实测 ulist.np/get（100 日元口径）"),
    "120.HKDCNYC": ("2026-09-12", "主代理 curl 实测 ulist.np/get（模块头注在册）"),
    "119.USDJPY": ("2026-09-12", "主代理 curl 实测 ulist.np/get（模块头注在册）"),
    "119.EURUSD": ("2026-09-12", "主代理 curl 实测 ulist.np/get（模块头注在册）"),
    "119.GBPUSD": ("2026-09-12", "主代理 curl 实测 ulist.np/get（模块头注在册）"),
    "119.USDKRW": ("2026-09-12", "主代理 curl 实测 ulist.np/get（模块头注在册）"),
    "119.USDHKD": ("2026-09-12", "主代理 curl 实测 ulist.np/get（模块头注在册）"),
    "119.USDSGD": ("2026-09-12", "主代理 curl 实测 ulist.np/get（模块头注在册）"),
}

# 无源凭据册：货币对 → (实测日期, 实测方式)。写进 ``FX_UNAVAILABLE_PAIRS``
# 的每一枚都必须在这儿查得到，否则「查无」本身也是未经核实的断言。
_FX_ABSENT_EVIDENCE: dict[str, tuple[str, str]] = {
    "USD/TWD": ("2026-09-12", "东财 suggest 实测查无行情"),
    "USD/MOP": ("2026-09-12", "东财 suggest 实测查无行情"),
    "USD/AED": ("2026-09-12", "东财 suggest 实测查无行情"),
}

# 候选待验名册：币种 → 候选 secid（直盘两个报价方向都探，加人民币中间价一族）。
# 命名规律来自已实测的同族行（119.<CCY1><CCY2> 直盘、120.<CCY>CNYC 人民币中间价），
# CAD/AUD 惯用报价方向是 <CCY>/USD，故两个方向并列，避免只探一侧而误判「无源」。
# ⚠ 这些 secid 一律**未经真机核实**：不进宇宙表、不进面板、不被换算层引用。
# 核实前问到该币一律走 ``fx_no_quote_reason`` 明写未接入。
FX_PENDING_CANDIDATE_SECIDS: dict[str, tuple[str, ...]] = {
    "RUB": ("119.USDRUB", "119.RUBUSD", "120.RUBCNYC"),
    "CHF": ("119.USDCHF", "119.CHFUSD", "120.CHFCNYC"),
    "CAD": ("119.USDCAD", "119.CADUSD", "120.CADCNYC"),
    "AUD": ("119.USDAUD", "119.AUDUSD", "120.AUDCNYC"),
}

# 每个待验币的第二条腿（兜底源）。只登记本仓有证据的腿；没有第二腿的
# 就明写没有——「只有候选一条腿」本身是要在册的可达性事实。
# er-api 快照链路＝已实现但本机实测不可达的兜底（``fetch_fx_snapshot``）。
_FX_SNAPSHOT_FALLBACK_LEG = (
    "er-api 快照链路 fetch_fx_snapshot（代码已实现，本机实测不可达）"
)
FX_PENDING_FALLBACK_LEGS: dict[str, str] = {
    "RUB": (
        f"{_FX_SNAPSHOT_FALLBACK_LEG}；另 iss.moex.com 外汇板可作第二候选"
        "（该主机 2026-09-12 实证直连可达，见 market_data 模块头注；外汇端点未探）"
    ),
    "CHF": _FX_SNAPSHOT_FALLBACK_LEG,
    "CAD": _FX_SNAPSHOT_FALLBACK_LEG,
    "AUD": _FX_SNAPSHOT_FALLBACK_LEG,
}

# 待验币的展示名（用户可见文案里点名「哪枚还没接上」时用的中文币名）。
_PENDING_CURRENCY_ORDER: tuple[str, ...] = ("RUB", "CHF", "CAD", "AUD")

_FX_ULIST_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    "?fltt=2&secids={secids}&fields=f2,f3,f4,f12,f13,f14,f18"
)
_FX_EASTMONEY_SOURCE = "eastmoney"
_FX_CACHE_TTL_DEFAULT_SECONDS = 60.0
_FX_RATE_CACHE: tuple[float, tuple[FxRate, ...]] | None = None

# 审查 Q-01：数据源失败文案统一入 user_copy 池（守岸人语气轮换），不再硬编码。
def _empty_fx_text() -> str:
    return random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(reason="汇率数据暂时拉不到")


def reset_fx_cache() -> None:
    """清空汇率快照进程内缓存（测试与运维手动刷新用）。"""
    global _FX_RATE_CACHE
    _FX_RATE_CACHE = None


def fx_pair_availability() -> dict[str, str]:
    """货币对覆盖表（「能不能报这个数」的单一读点）：

    - 有实测源 → ``eastmoney:<secid> <rate_type>``；
    - 东财实测查无 → ``unavailable: <_FX_PAIR_ABSENT_NOTE>``；
    - 可由 USD 三角换算（两条现货腿都在宇宙表里）→ ``cross: <腿1>+<腿2>``；
    - 候选源待真机核实 → ``pending: <候选 secid 列表>``。

    四态互斥：同一货币对若已有实测源行，**不**再产出 cross/pending 条目（实测源
    永远优先，避免一个对子两张票）。"""
    table = {
        pair: f"eastmoney:{secid} {rate_type}"
        for pair, secid, rate_type, *_rest in _FX_PAIR_UNIVERSE
    }
    for pair, legs in _derived_pair_legs().items():
        table.setdefault(pair, f"cross: {legs[0]}+{legs[1]}")
    for pair in FX_UNAVAILABLE_PAIRS:
        table[pair] = f"unavailable: {_FX_PAIR_ABSENT_NOTE}"
    for code, candidates in FX_PENDING_CANDIDATE_SECIDS.items():
        for pair in (f"USD/{code}", f"{code}/CNY"):
            table.setdefault(pair, f"pending: {'/'.join(candidates)}")
    return table


def fx_currency_availability() -> dict[str, str]:
    """币种级三态名册：``SUPPORTED_CURRENCIES`` 每一枚恰好落一态。

    - ``sourced: <参与的科学对清单>``——宇宙表里真会外呼的行；
    - ``unavailable: <原因>``——``FX_UNAVAILABLE_PAIRS`` 里实测查无的行所涉币种；
    - ``pending: <候选腿>``——候选 secid 已列、真机未核实。

    判定顺序＝先实测源、再待验名册、再实测查无；三处都不在的币＝静默消失，
    由 ``tests/test_fx_currency_coverage.py`` 门② 当场红。"""
    sourced_pairs: dict[str, list[str]] = {}
    for pair, *_rest in _FX_PAIR_UNIVERSE:
        for code in pair.split("/"):
            sourced_pairs.setdefault(code, []).append(pair)
    absent_codes: dict[str, str] = {}
    for pair in FX_UNAVAILABLE_PAIRS:
        for code in pair.split("/"):
            absent_codes.setdefault(code, _FX_PAIR_ABSENT_NOTE)
    table: dict[str, str] = {}
    for code in SUPPORTED_CURRENCIES:
        if code in sourced_pairs:
            table[code] = "sourced: " + "、".join(sourced_pairs[code])
        elif code in FX_PENDING_CANDIDATE_SECIDS:
            table[code] = (
                f"pending: 候选 {'/'.join(FX_PENDING_CANDIDATE_SECIDS[code])}"
                f"（兜底腿：{FX_PENDING_FALLBACK_LEGS.get(code, '无第二腿')}）"
            )
        elif code in absent_codes:
            table[code] = f"unavailable: {absent_codes[code]}"
        else:  # pragma: no cover - 由门② 兜住：新加币却三处都没登记。
            table[code] = "unregistered: 未登记任何数据源状态"
    return table


def fx_unquoted_currencies(
    rates: Sequence[FxRate] | None = None,
) -> tuple[str, ...]:
    """点名清单里「这一轮给不出报价」的币种，按 ``REQUIRED_CURRENCIES`` 顺序。

    含两种情形，都必须在卡面显式列出（缺席不许静默消失）：
    ① 结构性无源／候选待验（三态名册里不是 ``sourced`` 的）；
    ② 有实测源行但本次上游没回这一行（限流空响应、字段缺数）。"""
    availability = fx_currency_availability()
    live: set[str] = set()
    for rate in rates or ():
        live.add(rate.base_currency)
        live.add(rate.quote_currency)
    missing: list[str] = []
    for code in REQUIRED_CURRENCIES:
        state = availability.get(code, "unregistered: 未登记任何数据源状态")
        if not state.startswith("sourced") or (rates and code not in live):
            missing.append(code)
    return tuple(missing)


def fx_missing_note(
    rates: Sequence[FxRate] | None = None,
) -> str:
    """卡面/纯文本共用的缺席说明：实测查无、待验候选、本轮缺行**分列**，
    措辞各不相同——「查无」是核实过的事实、「待验」只是还没探、 「缺行」是本轮限流，
    三者不得混成一句「东财无行情」（S02 工单 §2.1「两份暂无文案」之诫）。"""
    availability = fx_currency_availability()
    absent: list[str] = []
    pending: list[str] = []
    for code in REQUIRED_CURRENCIES:
        state = availability.get(code, "")
        if state.startswith(("unavailable", "unregistered")):
            absent.append(code)
        elif state.startswith("pending"):
            pending.append(code)
    parts: list[str] = []
    if FX_UNAVAILABLE_PAIRS:
        parts.append("、".join(FX_UNAVAILABLE_PAIRS) + f"（{_FX_PAIR_ABSENT_NOTE}）")
    if absent:
        parts.append("、".join(absent) + "（实测查无或未登记，不给数字）")
    if pending:
        parts.append(
            "、".join(pending) + "（候选源待真机核实，未接入不上数）"
        )
    no_row = [
        code for code in fx_unquoted_currencies(rates)
        if availability.get(code, "").startswith("sourced")
    ]
    if no_row:
        parts.append("、".join(no_row) + "（本轮上游未返回该行，不猜数）")
    return "；".join(parts)


def fx_missing_sub(rates: Sequence[FxRate] | None = None) -> str:
    """``fx_missing_note`` 那行的口径副标题（卡上 sub 槽）。"""
    if fx_unquoted_currencies(rates):
        return "无实测源或本轮缺行：不给数字"
    return "全部点名币种均有报价"


def fx_no_quote_reason(base: str, quote: str) -> str:
    """直答「这一对为什么报不出来」——按三态给不同话，绝不把待验说成查无。"""
    base_upper = (base or "").strip().upper()
    quote_upper = (quote or "").strip().upper()
    pair = f"{base_upper}/{quote_upper}"
    reverse = f"{quote_upper}/{base_upper}"
    if pair in FX_UNAVAILABLE_PAIRS or reverse in FX_UNAVAILABLE_PAIRS:
        return _FX_PAIR_ABSENT_NOTE
    pending_notes: list[str] = []
    for code in (base_upper, quote_upper):
        candidates = FX_PENDING_CANDIDATE_SECIDS.get(code)
        if candidates:
            pending_notes.append(
                f"{code}（{_CURRENCY_DISPLAY.get(code, code)}）尚未接入已核实报价源，"
                f"候选 {'/'.join(candidates)} 待真机核实"
            )
    if pending_notes:
        return "；".join(pending_notes)
    return "未登记可用数据源，没有可核的数就不报"


# ==================== USD 三角换算桥（2026-10-02 接进能力层） ====================


def _spot_usd_legs() -> dict[str, str]:
    """宇宙表里「与 USD 直接成交」的现货行：币种 → 货币对键。

    两趟扫描：先收 ``USD/<X>`` 形（直读「X 每美元」），再收 ``<X>/USD`` 形，
    同币并列时保留直读那一行——扫描顺序固定，输出因此是确定的。"""
    legs: dict[str, str] = {}
    rows = [
        (pair, rate_type)
        for pair, _secid, rate_type, _unit_base, _display in _FX_PAIR_UNIVERSE
        if rate_type == "spot"
    ]
    for want_usd_base in (True, False):
        for pair, _rate_type in rows:
            base, quote = pair.split("/", 1)
            if base == "USD" and quote != "USD":
                code = quote
                if not want_usd_base:
                    continue
            elif quote == "USD" and base != "USD":
                code = base
                if want_usd_base:
                    continue
            else:
                continue
            legs.setdefault(code, pair)
    return legs


def _direct_cny_pairs() -> frozenset[str]:
    return frozenset(
        pair for pair, *_rest in _FX_PAIR_UNIVERSE if pair.endswith("/CNY")
    )


def _derived_pair_legs() -> dict[str, tuple[str, str]]:
    """静态推断哪些 ``<币>/CNY`` 可由两条现货腿按 USD 三角换算（有源优先，
    已经直接挂了 ``<币>/CNY`` 行的币不再重复发一张 cross 票）。"""
    legs = _spot_usd_legs()
    cny_leg = legs.get("CNY")
    if cny_leg is None:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for code, own_leg in legs.items():
        if code in ("USD", "CNY"):
            continue
        pair = f"{code}/CNY"
        if pair in _direct_cny_pairs():
            continue
        out[pair] = (own_leg, cny_leg)
    return out


def fx_per_usd(rate: FxRate | None) -> float | None:
    """把一条 USD 直盘**现货**行折成「每 1 美元兑多少该币」；其它一律 None。

    ``USD/<X>`` → ``rate/unit_base``；``<X>/USD`` → ``unit_base/rate``。
    中间价（parity）行不参与：换算桥里混进央行中间价＝一格数字两种口径，
    是「基准/中间价显式」红线的反面。非有限、非正同样 None（FIN-N1 口径）。
    """
    if rate is None or rate.rate_type != "spot":
        return None
    unit = float(rate.unit_base or 0.0)
    value = float(rate.rate)
    if unit <= 0 or value <= 0 or not math.isfinite(unit) or not math.isfinite(value):
        return None
    if rate.base_currency == "USD":
        per = value / unit
    elif rate.quote_currency == "USD":
        per = unit / value
    else:
        return None
    return per if per > 0 and math.isfinite(per) else None


def fx_usd_bridge(rates: Sequence[FxRate] | None) -> dict[str, FxRate]:
    """币种 → 提供其「每美元」价的现货行（USD 三角的唯一取腿读点）。"""
    bridge: dict[str, FxRate] = {}
    rows = list(rates or ())
    for want_usd_base in (True, False):
        for rate in rows:
            per_usd = fx_per_usd(rate)
            if per_usd is None:
                continue
            if rate.base_currency == "USD":
                if not want_usd_base:
                    continue
                code = rate.quote_currency
            elif rate.quote_currency == "USD":
                if want_usd_base:
                    continue
                code = rate.base_currency
            else:  # pragma: no cover - fx_per_usd 已挡掉非 USD 直盘
                continue
            if code and code != "USD":
                bridge.setdefault(code, rate)
    return bridge


def fx_derived_quote(
    rates: Sequence[FxRate] | None,
    base: str,
    quote: str,
) -> tuple[FxRate, str] | None:
    """按 USD 三角换算任意两币；换不出给 None（不硬凑、更不用估算冒充报价）。

    返回 ``(FxRate, 口径说明)``：``rate_type="derived"``（卡面副标题映射成
    「交叉换算」），说明句点名「用了哪两条腿 ＋ 非中间价 ＋ 非可成交价」，
    时点取参与换算的两行里**较早**的那个（不造新时间戳）。"""
    base_upper = (base or "").strip().upper()
    quote_upper = (quote or "").strip().upper()
    if not base_upper or not quote_upper or base_upper == quote_upper:
        return None
    bridge = fx_usd_bridge(rates)
    if not bridge:
        return None
    table: dict[str, float] = {"USD": 1.0}
    for code, row in bridge.items():
        per_usd = fx_per_usd(row)
        if per_usd is not None:
            table[code] = per_usd
    rate = cross_rate_from_usd(table, base_upper, quote_upper)
    if rate is None:
        return None
    legs: list[str] = []
    stamps: list[str] = []
    for code in (base_upper, quote_upper):
        if code == "USD":
            legs.append("USD（桥基准）")
            continue
        anchor = bridge.get(code)
        if anchor is None:
            return None  # 缺腿＝换不出，绝不半截报数。
        legs.append(f"{anchor.base_currency}/{anchor.quote_currency}")
        if anchor.timestamp:
            stamps.append(anchor.timestamp)
    note = (
        f"由 {legs[0]} 与 {legs[1]} 两条现货报价按 USD 三角换算："
        "非中间价、非可成交价、延迟行情"
    )
    return (
        FxRate(
            base_currency=base_upper,
            quote_currency=quote_upper,
            rate=rate,
            unit_base=1.0,
            timestamp=min(stamps) if stamps else "",
            source=_FX_EASTMONEY_SOURCE,
            rate_type="derived",
            delayed=True,
            history=(),
        ),
        note,
    )


def _diff_rows_by_code(payload: Any) -> dict[str, dict[str, Any]]:
    """东财批量响应 → ``f12 代码 → 行``（``_parse_rates`` 与可达性探针共用）。"""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    diff = data.get("diff") if isinstance(data, dict) else None
    if not isinstance(diff, list):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for row in diff:
        if isinstance(row, dict):
            code = str(row.get("f12") or "").strip().upper()
            if code:
                rows[code] = row
    return rows


def probe_fx_candidates(
    timeout_seconds: float = 8.0,
) -> dict[str, dict[str, Any]]:
    """待验候选 secid 的真机可达性探针（**运维/验收入口，生产链路不调用**）。

    把 ``FX_PENDING_CANDIDATE_SECIDS`` 的全部候选一次批量打给东财
    ``ulist.np/get``，逐币报「哪条腿有行且 f2 是有限正数／无行／调用异常」。
    纯只读：不写缓存、不动宇宙表、不产生任何用户可见文案。命中后的正确动作是
    **人工**把该行同批写进 ``_FX_PAIR_UNIVERSE`` ＋ ``_FX_SOURCE_EVIDENCE``
    ＋ ``resolve_fx_pair`` 的可用面，并把它从待验名册摘掉——只动一边必红另一边
    （门①/门②）。
    """
    candidates: list[str] = []
    for code in _PENDING_CURRENCY_ORDER:
        for secid in FX_PENDING_CANDIDATE_SECIDS.get(code, ()):
            if secid not in candidates:
                candidates.append(secid)
    report: dict[str, dict[str, Any]] = {
        code: {"candidates": list(FX_PENDING_CANDIDATE_SECIDS.get(code, ())),
               "hit": [], "no_row": [], "bad_value": []}
        for code in _PENDING_CURRENCY_ORDER
    }
    if not candidates:  # pragma: no cover - 名册清空后的诚实空转
        return report
    try:
        payload = _fetch_payload(",".join(candidates), max(1.0, float(timeout_seconds)))
    except Exception as exc:  # noqa: BLE001 - 探针失败只报状态，绝不抛。
        for entry in report.values():
            entry["error"] = f"{type(exc).__name__}"
        return report
    rows = _diff_rows_by_code(payload)
    for code, entry in report.items():
        for secid in entry["candidates"]:
            tail = secid.split(".", 1)[1] if "." in secid else secid
            row = rows.get(tail)
            if row is None:
                entry["no_row"].append(secid)
                continue
            value = _as_float(row.get("f2"))
            if value is None:
                entry["bad_value"].append(secid)
            else:
                entry["hit"].append({"secid": secid, "f2": value, "f14": row.get("f14")})
        entry["quoted"] = bool(entry["hit"])
    return report


def _as_float(value: Any) -> float | None:
    """fltt=2 下正常值是小数/整数；缺数时可能是 "-" 或缺失。

    FIN-N1（汇率面）：上游 JSON 可携带 ``NaN``/``Infinity`` 字面量
    （``json.loads`` 默认接受），非有限汇率一律视为缺数（None）——走既有
    「暂无数据」诚实通道，绝不让 nan/inf 进卡片数字槽、更不乘进换算总额
    （``format_fx_rate_line`` 的 ``amount/unit_base*rate`` 从此只吃有限值）。
    None≠0 与缺数语义不变。
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
    """东财汇率批量快照单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    return http_get_json(
        _FX_ULIST_URL.format(secids=secids),
        timeout=max(1.0, float(timeout_seconds)),
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


def _parse_rates(payload: Any, timestamp: str) -> list[FxRate]:
    """按宇宙表顺序解析响应；缺行/f2 非数的货币对跳过（绝不造数）。

    行索引走 ``_diff_rows_by_code``（与可达性探针同一把尺，不起第二份）。"""
    by_code = _diff_rows_by_code(payload)
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
    *,
    budget: Any | None = None,
) -> list[FxRate]:
    """批量拉取汇率快照（东财主源）；失败返回 []，绝不抛异常。

    ``pair_keys=None`` 拉全部宇宙表货币对；给列表则按宇宙表顺序过滤子集。
    去重 secid 后单次批量外呼 + 进程内 TTL 缓存（默认 60s）；失败不缓存，
    下一次调用立即重试。``unit_base=100`` 的中间价（JPY/CNY）按 100 日元口径。

    FIN-R1：与行情/个股/商品共用一条端到端网络预算（``budget`` 关键字，未传
    则自造 per-call 兜底预算，既有调用方零改动）——预算尽 ⇒ 不发起新外呼、
    弃剩余 G2 重试，走既有「失败不缓存、静默缺席=[]」诚实降级，绝不因预算把
    取数打挂，也绝不跨层把退避睡眠相乘钉死有界聊天 worker。
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
        budget = _budget_or_new(budget)
        # G2：东财限流=HTTP 200 空响应（空 JSON/缺行）→ 退避后至多重试 1 次；
        # 真异常（网络错/非 200）不重试；仍空照旧不缓存。仅东财主源重试，
        # er-api 快照链路（fetch_fx_snapshot）不在重试范围。
        attempts = 2 if retry_on_empty_enabled() else 1
        all_rates = []
        for attempt in range(attempts):
            if budget_expired(budget):
                break  # FIN-R1：预算尽不发起新网络调用（失败不缓存纪律不变）。
            try:
                payload = _fetch_payload(
                    ",".join(secids), max(1.0, float(timeout_seconds))
                )
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                all_rates = _parse_rates(payload, timestamp)
            except Exception:  # noqa: BLE001 - 汇率失败静默降级，不阻塞会话链路。
                all_rates = []
                break  # 真异常不重试。
            if all_rates or attempt + 1 >= attempts or not budget_allows_retry(budget):
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
    # 2026-10-02 席位 F1 补齐的四枚（用户点名清单里的待验币）。
    # 解析层照常认得它们（问到就要给一句明确的「没接上」而不是答非所问），
    # 但「认得」≠「有源」：报价面由 fx_currency_availability() 说了算。
    # 惯用简称里刻意不收「澳币」「加币」——前者在粤语/口语里也指澳门元，
    # 后者与「加密货币」类语境易混，顶替币种＝报错数。
    "卢布": "RUB",
    "俄罗斯卢布": "RUB",
    "瑞郎": "CHF",
    "瑞士法郎": "CHF",
    "加元": "CAD",
    "加拿大元": "CAD",
    "澳元": "AUD",
    "澳大利亚元": "AUD",
    "澳洲元": "AUD",
    # 繁体变体（2026-09-13 多语言触发覆盖）。
    # 「瑞士法郎／加拿大元／澳洲元」简繁同形，不重复登记（重复键＝ruff F601）。
    "人民幣": "CNY",
    "新台幣": "TWD",
    "台幣": "TWD",
    "港幣": "HKD",
    "韓元": "KRW",
    "歐元": "EUR",
    "英鎊": "GBP",
    "澳門幣": "MOP",
    "澳門元": "MOP",
    "盧布": "RUB",
    "俄羅斯盧布": "RUB",
    "澳大利亞元": "AUD",
}
_CN_NAME_ALT = "|".join(sorted(_CURRENCY_ALIASES, key=len, reverse=True))
_VALID_CODES = frozenset(_CURRENCY_ALIASES.values())

# ISO 三字母码识别：**从别名表值集派生**（2026-10-02 起这是唯一的码名册，
# 旧写法在这里硬抄了第二份 11 枚码，扩币必「面板有、触发词没有」分裂）。
# 两侧只禁 ASCII 字母胶合（不禁 CJK 相邻），所以「usd换算」认得到、
# 「audio换算」「decade」里的 aud/cad 认不到——CJK 在 Python re 里算 \w，
# 用 \b 会把「usd换算」一起挡掉，故走显式 lookaround。
_ISO_CODE_RE = re.compile(
    rf"(?<![A-Za-z])(?:{'|'.join(sorted(_VALID_CODES))})(?![A-Za-z])",
    re.IGNORECASE,
)

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

# 币种 → 展示名。键集必须与 ``_VALID_CODES``（别名表值集）严格相等——
# 「别名认得但展示名没有」会退化成 ISO 码生肉，「展示名有但别名没有」永不命中，
# 两样都由 tests/test_fx_currency_coverage.py 门④ 拦。
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
    "RUB": "卢布",
    "CHF": "瑞郎",
    "CAD": "加元",
    "AUD": "澳元",
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
    """文本是否含任何已知币名（中文别名/繁体/ISO 码，大小写均可）。

    「换算」类泛词的语境约束用（评审 P1-1）：「美元换算」=True、
    「单位换算」=False。ISO 码腿走 ``_ISO_CODE_RE``（别名表值集派生的唯一
    码名册，带 ASCII 胶合闸），不再在本函数里硬抄第二份码清单——旧写法
    扩币时必出现「面板有、触发词没有」的分裂态（S02 工单 §9-4）。
    """
    lowered = (text or "").lower()
    if not lowered:
        return False
    if any(alias in lowered for alias in _CURRENCY_ALIASES):
        return True
    return bool(_ISO_CODE_RE.search(lowered))


def format_fx_rate_line(rate: FxRate, amount: float = 1.0) -> str:
    """单行汇率换算：`100日元 ≈ 4.36 人民币`（含 unit_base 折算）。

    展示口径为「金额 + 基准币名 ≈ 折算额 + 报价币名」：amount 按
    ``unit_base`` 折算后乘汇率（100日元中间价 4.3614 × 100/100 = 4.36）。
    """
    base_name = _CURRENCY_DISPLAY.get(rate.base_currency, rate.base_currency)
    quote_name = _CURRENCY_DISPLAY.get(rate.quote_currency, rate.quote_currency)
    converted = amount / rate.unit_base * rate.rate
    return f"{amount:g}{base_name} ≈ {converted:.2f} {quote_name}"


def format_fx_brief(rates: Sequence[FxRate], missing: str = "") -> str:
    """主要货币汇率速览（快查批量链路）；按 unit_base 折算展示；
    空结果给降级文案。provenance 快照链路见 ``format_fx_snapshot_brief``。

    ``missing``（可选）：点名清单里「这一轮给不出报价」的说明句
    （``fx_missing_note`` 产出）。缺省空串＝输出与 2026-09-13 评审域 B 的
    逐字文案锁完全一致；能力层显式传入，缺席因此不再从纯文本面静默消失。"""
    if not rates:
        return _empty_fx_text()
    lines = ["主要货币汇率速览"]
    for rate in rates:
        lines.append(format_fx_rate_line(rate, amount=rate.unit_base))
    if missing:
        lines.append(f"暂无数据：{missing}")
    return "\n".join(lines)

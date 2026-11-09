"""全球指数多源交叉查验（腾讯 qt.gtimg.cn，免 key，2026-09-13 实测可达）。

动机（用户裁定）：行情单一来源出错无法发现 → 主源（东财）之外用腾讯行情
做二次核验，两源一致才在卡上声明「已交叉核验」，不一致显式标注差异数值，
核验通道不可用则保持沉默（不声明、不阻塞、不伪造）。

覆盖映射（全部 2026-09-13 curl 实测、两源数值逐位一致；未列出的指数表示
腾讯无已验证代码，不做声明）：
- 1.000001 上证指数 → s_sh000001（短格式）
- 0.399001 深证成指 → s_sz399001（短格式）
- 0.399006 创业板指 → s_sz399006（短格式）
- 100.HSI  恒生指数 → r_hkHSI（长格式）
- 100.DJIA 道琼斯   → usDJI（长格式）
- 100.SPX  标普500  → usINX（长格式）
刻意不映射：100.NDX（东财的「纳斯达克」是综合指数口径，与腾讯 .NDX
纳斯达克100 数值不同，交叉会假告警）；同花顺 web 行情需 hexin-v 反爬
令牌，无免费稳定通道，暂不接。

任何网络/解析失败一律返回空核验结果（checked=0，不声明），绝不抛异常。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from plugins.bot_unified_runtime.domains.finance.data.market_data import (
    _budget_or_new,
    budget_expired,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import http_get

_CROSS_CODES: dict[str, tuple[str, str]] = {
    # IndexQuote.code → (腾讯代码, 解析格式)
    "1.000001": ("s_sh000001", "short"),
    "0.399001": ("s_sz399001", "short"),
    "0.399006": ("s_sz399006", "short"),
    "100.HSI": ("r_hkHSI", "full"),
    "100.DJIA": ("usDJI", "full"),
    "100.SPX": ("usINX", "full"),
}
_CROSS_SOURCE = "qt.gtimg.cn＋hq.sinajs.cn"
_CROSS_URL = "https://qt.gtimg.cn/q={codes}"

# ==================== 第三条腿：新浪（2026-10-12 实测，须 Referer） ==========
# 2026-10-12 实测：不带 Referer 一律 403，带头即 200（GB18030 载荷）。
# 用户 2026-10-12 硬门槛：一切对外数值须 ≥3 官方/权威渠道佐证 ⇒ 主源（东财）
# ＋腾讯＋新浪＝三腿；三腿全一致才在卡上声明，任一腿分歧即逐条点名分歧数值。
_SINA_URL = "https://hq.sinajs.cn/list={codes}"
_SINA_REFERER = "https://finance.sina.com.cn"
# 新浪映射表（仅列 2026-10-12 实测可得者；未列出的指数不参与第三腿）。
_SINA_CODES: dict[str, str] = {
    "1.000001": "s_sh000001",
    "0.399001": "s_sz399001",
    "0.399006": "s_sz399006",
    "100.HSI": "rt_hkHSI",
    "100.DJIA": "gb_$dji",
    "100.SPX": "gb_$inx",
}
_SINA_TAG_MAP: dict[str, str] = {"s_sh000001": "sh000001", "s_sz399001": "sz399001", "s_sz399006": "sz399006"}
# 第三腿缓存（与腾讯腿同 TTL，各自独立：任一腿挂掉不拖垮另一腿）。
_SINA_CACHE: tuple[float, tuple[str, ...], dict[str, tuple[float, float]]] | None = None

# 一致性判据：价格相对差 ≤0.5% 且 涨跌幅差 ≤0.2 个百分点（两源快照有时差）。
_PRICE_TOLERANCE_RATIO = 0.005
_PCT_TOLERANCE_PP = 0.2

_CACHE_TTL_SECONDS = 60.0
_CACHE: tuple[float, tuple[str, ...], dict[str, tuple[float, float]]] | None = None
# 值含义：code → (price, change_pct)（腾讯侧快照）


@dataclass(frozen=True)
class CrossCheckResult:
    """一次交叉查验的汇总（不可用通道 → checked=0，能力层不声明）。"""

    checked: int
    matched: int
    mismatches: tuple[str, ...]
    source: str = _CROSS_SOURCE

    @property
    def ok(self) -> bool:
        return self.checked > 0 and self.matched == self.checked


def reset_crosscheck_cache() -> None:
    """清空两腿快照缓存（测试与运维用）。"""
    global _CACHE, _SINA_CACHE
    _CACHE = None
    _SINA_CACHE = None


def _parse_sina_payload(text: str) -> dict[str, tuple[float, float]]:
    """新浪 hq 载荷 → {code: (price, change_pct)}；脏行逐条跳过，绝不抛异常。

    短格式：``var hq_str_s_sh000001="上证指数,3934.40,-17.11,-0.43,..."``
    （名称, 点位, 涨跌额, 涨跌幅%）⇒ 取第 2、4 位。港股 ``rt_hk`` 与美股
    ``gb_`` 形态不同，本轮未验证 ⇒ 不映射、不声明（宁缺不编）。
    """
    out: dict[str, tuple[float, float]] = {}
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line.startswith("var hq_str_") or "=" not in line:
            continue
        tag, _, raw = line.partition("=")
        tag = tag.replace("var hq_str_", "").strip()
        payload = raw.strip().strip(";").strip('"')
        parts = payload.split(",")
        if len(parts) < 4:
            continue
        code = _SINA_TAG_MAP.get(tag)
        if code is None:
            continue
        try:
            price = float(parts[1])
            pct = float(parts[3])
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and math.isfinite(pct) and price > 0:
            out[code] = (price, pct)
    return out


def _fetch_sina_snapshot(
    codes: tuple[str, ...], timeout_seconds: float
) -> dict[str, tuple[float, float]]:
    """第三腿单点网络出口（测试 monkeypatch 本函数即可拦截外呼）。

    必须带 ``Referer``（2026-10-12 实测无头 403）；载荷 GB18030
    ⇒ 走 ``http_get_text(encoding="gb18030")``（既有签名，不新造解码腿）。
    """
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        http_get_text,
    )

    url = _SINA_URL.format(codes=",".join(codes))
    # `http_get_text` 返回 ``(final_url, text)``——**必须解包**。
    # 曾写成 ``text = http_get_text(...)`` ⇒ text 是元组，`_parse_sina_payload`
    # 内部 ``str(text or "")`` 把它变成 repr 串、匹配不到任何行 ⇒ **静默返回空**，
    # 第三腿（新浪）实际从未工作，而测试在函数边界 monkeypatch 故从未暴露。
    _final_url, text = http_get_text(
        url,
        timeout=max(1.0, float(timeout_seconds)),
        referer=_SINA_REFERER,
        encoding="gb18030",
    )
    return _parse_sina_payload(text)


def _fetch_tencent_snapshot(
    codes: tuple[str, ...], timeout_seconds: float
) -> dict[str, tuple[float, float]]:
    """单点网络出口（测试 monkeypatch 本函数即可拦截全部外呼）。

    腾讯返回 GBK 文本（v_code="..." 行）；解析失败/缺行静默跳过。
    """
    url = _CROSS_URL.format(codes=",".join(codes))
    _final_url, body = http_get(url, timeout=max(1.0, float(timeout_seconds)))
    text = body.decode("gbk", errors="replace")
    code_to_tencent = {
        index_code: tencent for index_code, (tencent, _fmt) in _CROSS_CODES.items()
    }
    snapshot: dict[str, tuple[float, float]] = {}
    # 注意解包：items() 给的是 (index_code, (tencent, fmt))，fmt 必须从
    # 值元组里再解一层——曾写成 `for code, fmt in ...` 导致 fmt 恒为元组、
    # `== "short"` 永假，短格式行（上证/深证/创业板）全部静默落空
    # （tests/test_market_crosscheck_tencent_gbk.py 固化）。
    for code, (_tencent, fmt) in _CROSS_CODES.items():
        marker = f'v_{code_to_tencent[code]}="'
        start = text.find(marker)
        if start < 0:
            continue
        record = text[start + len(marker) : text.find('"', start + len(marker))]
        fields = record.split("~")
        try:
            if fmt == "short":
                # 短格式：1~上证指数~000001~价格~涨跌额~涨跌幅~...
                price = float(fields[3])
                change_pct = float(fields[5])
            else:
                # 长格式（HK/US，2026-09-13 实测字段序）：
                # [3]=价格，[30]=时间戳，[31]=涨跌额，[32]=涨跌幅。
                price = float(fields[3])
                change_pct = float(fields[32])
        except (IndexError, ValueError):
            continue
        # FIN-N1：数据边界统一有限性闸——``float("NaN"/"Infinity")`` 会成功，
        # 非有限值一旦进快照就会流入差异文案与卡片 DOM，故整行如实跳过。
        if not (math.isfinite(price) and math.isfinite(change_pct)):
            continue
        snapshot[code] = (price, change_pct)
    return snapshot


def crosscheck_quotes(
    quotes: Any,
    *,
    timeout_seconds: float = 4.0,
    cache_seconds: float = _CACHE_TTL_SECONDS,
    budget: Any | None = None,
) -> CrossCheckResult:
    """对可映射指数做三源核验；缺腿时如实降级，绝不伪造「已核验」。

    用户 2026-10-12 硬门槛：≥3 官方/权威渠道。三腿＝主源（东财）＋腾讯＋
    新浪；第二条腿（新浪）不可用时**不假装三源**，结果里 source 字段如实
    记下实际参检腿，供文案层区分「三源已核验」与「双源已核验」。

    FIN-R1：不传 budget 时自造 per-call 端到端网络预算；预算耗尽即放弃外呼
    （核验通道按设计「不可用则保持沉默」，语义零扩张、不伪造核验结论）。
    """
    global _CACHE, _SINA_CACHE
    wanted = [
        (quote.code, quote.name, quote.price, quote.change_pct)
        for quote in quotes
        if quote.code in _CROSS_CODES
    ]
    if not wanted:
        return CrossCheckResult(0, 0, ())
    budget = _budget_or_new(budget)
    now = time.monotonic()

    def _cached_or_fetch(cache, codes, fetcher):
        # 🔴 缓存键**必须含请求的 codes**（2026-10-14 治本）：旧实现只比时间戳，
        # 于是 60s 内**换了指数集仍读旧快照**——新集里那些没被旧快照覆盖的指数
        # 会被静默当成「腿缺席」，三源**无声降级成双源**。
        wanted_codes = tuple(codes)
        cached = cache
        if (
            cached is not None
            and cached[1] == wanted_codes
            and now - cached[0] <= max(1.0, float(cache_seconds))
        ):
            return cached[2]
        if budget_expired(budget):
            return {}  # 旁路核验：预算已尽，保持沉默（失败/缺席都不缓存）。
        try:
            snapshot = fetcher(codes, timeout_seconds)
        except Exception:  # noqa: BLE001 - 核验通道失败保持沉默。
            snapshot = {}
        return snapshot

    tencent_codes = tuple(_CROSS_CODES[code][0] for code, _n, _p, _c in wanted)
    snapshot = _cached_or_fetch(_CACHE, tencent_codes, _fetch_tencent_snapshot)
    if snapshot:
        _CACHE = (now, tencent_codes, snapshot)

    # 第三腿：只对两表都有映射的指数取数（未映射者不参与，宁缺不编）。
    sina_pairs = [
        (code, _SINA_CODES[code]) for code, _n, _p, _c in wanted if code in _SINA_CODES
    ]
    sina_snapshot: dict[str, tuple[float, float]] = {}
    if sina_pairs:
        sina_tags = tuple(tag for _code, tag in sina_pairs)
        sina_snapshot = _cached_or_fetch(
            _SINA_CACHE,
            sina_tags,
            _fetch_sina_snapshot,
        )
        if sina_snapshot:
            _SINA_CACHE = (now, sina_tags, sina_snapshot)

    if not snapshot and not sina_snapshot:
        return CrossCheckResult(0, 0, ())

    matched = 0
    mismatches: list[str] = []
    checked = 0
    checked_three = 0
    for code, name, price, change_pct in wanted:
        remote = snapshot.get(code)
        sina = sina_snapshot.get(code)
        if remote is None and sina is None:
            continue
        checked += 1
        if remote is not None and sina is not None:
            checked_three += 1
        # 主源价缺失/为 0 无法核验，按差异处理（评审 P2-1：0 价不该判「一致」）。
        if price is None or price <= 0:
            other = remote if remote is not None else sina
            assert other is not None  # 上面已排除「双 None」（L262 的 continue）
            mismatches.append(f"{name}（东财价格缺失 · 他源 {other[0]:.2f}）")
            continue
        ok_all = True
        for label, leg in (("腾讯", remote), ("新浪", sina)):
            if leg is None:
                continue
            leg_price, leg_pct = leg
            price_ok = (
                abs(leg_price - price) / max(abs(price), 1e-9)
                <= _PRICE_TOLERANCE_RATIO
            )
            pct_ok = (
                change_pct is not None
                and abs(leg_pct - change_pct) <= _PCT_TOLERANCE_PP
            )
            if not (price_ok and pct_ok):
                ok_all = False
                local_pct = (
                    f"{change_pct:+.2f}%" if change_pct is not None else "未知"
                )
                mismatches.append(
                    f"{name}（东财 {price:.2f}/{local_pct} · "
                    f"{label} {leg_price:.2f}/{leg_pct:+.2f}%）"
                )
        if ok_all:
            matched += 1
    source = _CROSS_SOURCE if checked_three else "qt.gtimg.cn（两源）"
    return CrossCheckResult(checked, matched, tuple(mismatches), source=source)


def format_crosscheck_note(result: CrossCheckResult) -> str:
    """卡/文本用的核验声明；未核验（通道不可用或无映射）返回空串。

    用户 2026-10-12 硬门槛：≥3 官方/权威渠道。参检三腿时写「三源」，
    只有两条腿可用时如实写「双源」——绝不把两源说成三源。
    """
    if result.checked <= 0:
        return ""
    legs = "三源" if "sinajs" in result.source else "双源"
    peers = "东财/腾讯/新浪" if legs == "三源" else "东财/腾讯"
    if result.ok:
        return f"已与{legs}（{peers}）交叉核验 ✓ {result.matched}/{result.checked}"
    head = "、".join(result.mismatches[:2])
    more = f" 等 {len(result.mismatches)} 项" if len(result.mismatches) > 2 else ""
    return (
        f"⚠ {legs}交叉核验 {result.matched}/{result.checked} 一致，"
        f"差异：{head}{more}"
    )

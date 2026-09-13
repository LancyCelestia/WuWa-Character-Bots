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

import time
from dataclasses import dataclass
from typing import Any

from plugins.bot_unified_runtime.sources.parsers.http_util import http_get

_CROSS_CODES: dict[str, tuple[str, str]] = {
    # IndexQuote.code → (腾讯代码, 解析格式)
    "1.000001": ("s_sh000001", "short"),
    "0.399001": ("s_sz399001", "short"),
    "0.399006": ("s_sz399006", "short"),
    "100.HSI": ("r_hkHSI", "full"),
    "100.DJIA": ("usDJI", "full"),
    "100.SPX": ("usINX", "full"),
}
_CROSS_SOURCE = "qt.gtimg.cn"
_CROSS_URL = "https://qt.gtimg.cn/q={codes}"

# 一致性判据：价格相对差 ≤0.5% 且 涨跌幅差 ≤0.2 个百分点（两源快照有时差）。
_PRICE_TOLERANCE_RATIO = 0.005
_PCT_TOLERANCE_PP = 0.2

_CACHE_TTL_SECONDS = 60.0
_CACHE: tuple[float, dict[str, tuple[float, float]]] | None = None
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
    """清空腾讯侧快照缓存（测试与运维用）。"""
    global _CACHE
    _CACHE = None


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
        snapshot[code] = (price, change_pct)
    return snapshot


def crosscheck_quotes(
    quotes: Any,
    *,
    timeout_seconds: float = 4.0,
    cache_seconds: float = _CACHE_TTL_SECONDS,
) -> CrossCheckResult:
    """对可映射指数做两源核验；通道不可用返回 checked=0，绝不抛异常。"""
    global _CACHE
    wanted = [
        (quote.code, quote.name, quote.price, quote.change_pct)
        for quote in quotes
        if quote.code in _CROSS_CODES
    ]
    if not wanted:
        return CrossCheckResult(0, 0, ())
    now = time.monotonic()
    cached = _CACHE
    if cached is not None and now - cached[0] <= max(1.0, float(cache_seconds)):
        snapshot = cached[1]
    else:
        try:
            snapshot = _fetch_tencent_snapshot(
                tuple(_CROSS_CODES[code][0] for code, _n, _p, _c in wanted),
                timeout_seconds,
            )
        except Exception:  # noqa: BLE001 - 核验通道失败保持沉默。
            snapshot = {}
        if snapshot:
            # 只缓存成功结果（仓库纪律：失败不缓存，便于立即重试）。
            _CACHE = (now, snapshot)

    if not snapshot:
        return CrossCheckResult(0, 0, ())
    matched = 0
    mismatches: list[str] = []
    checked = 0
    for code, name, price, change_pct in wanted:
        remote = snapshot.get(code)
        if remote is None:
            continue
        checked += 1
        remote_price, remote_pct = remote
        # 主源价缺失/为 0 无法核验，按差异处理（评审 P2-1：0 价不该判「一致」）。
        if price is None or price <= 0:
            mismatches.append(f"{name}（东财价格缺失 · 腾讯 {remote_price:.2f}）")
            continue
        price_diff_ok = (
            abs(remote_price - price) / max(abs(price), 1e-9)
            <= _PRICE_TOLERANCE_RATIO
        )
        pct_diff_ok = (
            change_pct is not None
            and abs(remote_pct - change_pct) <= _PCT_TOLERANCE_PP
        )
        if price_diff_ok and pct_diff_ok:
            matched += 1
        else:
            local_pct = (
                f"{change_pct:+.2f}%" if change_pct is not None else "未知"
            )
            mismatches.append(
                f"{name}（东财 {price:.2f}/{local_pct} · "
                f"腾讯 {remote_price:.2f}/{remote_pct:+.2f}%）"
            )
    return CrossCheckResult(checked, matched, tuple(mismatches))


def format_crosscheck_note(result: CrossCheckResult) -> str:
    """卡/文本用的核验声明；未核验（通道不可用或无映射）返回空串。"""
    if result.checked <= 0:
        return ""
    if result.ok:
        return f"已与腾讯行情交叉核验 ✓ {result.matched}/{result.checked}"
    head = "、".join(result.mismatches[:2])
    more = f" 等 {len(result.mismatches)} 项" if len(result.mismatches) > 2 else ""
    return (
        f"⚠ 交叉核验 {result.matched}/{result.checked} 一致，差异：{head}{more}"
    )

"""技术指标 MACD/RSI/WR/CCI 手算基准对拍（审查 H-08，2026-09-15）。

背景：个股行情此前只有 KDJ（tests/test_finance_data.py 手算基准守门），
缺 MACD/RSI/WR/CCI。本文件用**手工可推演的构造序列**对拍标准公式值：

- MACD 12/26/9：EMA 取 SMA 种子（东财/通达信口径），柱 = 2×(DIF−DEA)；
  基准选「33 根 1.0 + 末根 2.0」阶梯序列，DIF/DEA/柱全部可分数精确定义
  （见 test_macd_step_series_hand_computed）。
- RSI(14)：Wilder 平滑；用 7 涨 7 跌 1 涨的对称序列，RSI = 375/7 精确值。
- WR(14)：窗口 H=20/L=10，收盘 15/20/10 → 50/0/100。
- CCI(20)：TP 序列 1..20（H=L=C），MA=10.5、MD=5 → CCI = 380/3 精确值。

全部离线纯计算，零网络、零第三方指标库。
"""

from __future__ import annotations

from datetime import date, timedelta
from fractions import Fraction

import pytest

from plugins.bot_unified_runtime.contracts.finance import (
    EquityQuote,
    FinanceDataStatus,
    OHLCVBar,
    OHLCVSeries,
)
from plugins.bot_unified_runtime.sources.stock_data import (
    compute_all_technical_indicators,
    compute_cci,
    compute_kdj,
    compute_macd,
    compute_rsi,
    compute_wr,
    format_stock_brief,
)


def _bar(day: int, open_: float, high: float, low: float, close: float) -> OHLCVBar:
    """单根 K 线；trade_date 只作快照回显，数值与日期解耦。"""
    return OHLCVBar(
        trade_date=date(2026, 8, 1) + timedelta(days=day),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1_000_000,
    )


def _bars(closes: list[float], *, spread: float = 1.0) -> list[OHLCVBar]:
    """由收盘序列构造 K 线：high=close+spread / low=close−spread / open=close。

    spread 参数留给 WR/CCI 测试自定窗口高低；默认 ±1 满足 OHLCVBar 校验器
    （open/close 必须落在 [low, high] 内）。
    """
    return [
        _bar(i, close, close + spread, close - spread, close)
        for i, close in enumerate(closes)
    ]


# ---------------------------------------------------------------------------
# MACD（12/26/9，SMA 种子，柱 = 2×(DIF−DEA)）
# ---------------------------------------------------------------------------


class TestMacd:
    def test_step_series_hand_computed(self) -> None:
        """阶梯序列（33×1.0 + 末根 2.0）手算对拍（分数精确值）。

        手算（审查 H-08 基准）：
        - EMA12：前 12 根 SMA=1.0，之后输入恒 1.0 → 直到第 33 根都 = 1.0；
          末根 EMA12 = 1 + (2/13)×(2−1) = 15/13。
        - EMA26：前 26 根 SMA=1.0 → 第 26~33 根 = 1.0；
          末根 EMA26 = 1 + (2/27)×(2−1) = 29/27。
        - DIF 末值 = 15/13 − 29/27 = 28/351。
        - DIF 序列共 9 个值（第 26~34 根）：前 8 个为 0，末个 28/351；
          DEA = SMA9 种子 = (0×8 + 28/351)/9 = 28/3159。
        - 柱 = 2×(28/351 − 28/3159) = 448/3159。
        """
        bars = _bars([1.0] * 33 + [2.0])
        snap = compute_macd(bars)
        assert snap is not None
        assert snap.dif == pytest.approx(float(Fraction(28, 351)), abs=1e-12)
        assert snap.dea == pytest.approx(float(Fraction(28, 3159)), abs=1e-12)
        assert snap.hist == pytest.approx(float(Fraction(448, 3159)), abs=1e-12)
        assert snap.trade_date == bars[-1].trade_date
        assert (snap.fast_period, snap.slow_period, snap.signal_period) == (12, 26, 9)

    def test_flat_series_all_zero(self) -> None:
        """恒定收盘 → DIF=DEA=柱=0（不漂移、不造信号）。"""
        snap = compute_macd(_bars([5.0] * 40))
        assert snap is not None
        assert snap.dif == 0.0
        assert snap.dea == 0.0
        assert snap.hist == 0.0

    def test_insufficient_window_returns_none(self) -> None:
        """34 根起算（26+9−1）；33 根必须 None，绝不造数（审查 H-08 纪律）。"""
        assert compute_macd(_bars([1.0] * 33)) is None
        assert compute_macd([]) is None

    def test_degenerate_periods_rejected(self) -> None:
        """fast ≥ slow 等退化参数直接 None（防御分支）。"""
        bars = _bars([1.0] * 40)
        assert compute_macd(bars, fast=26, slow=12) is None
        assert compute_macd(bars, fast=0, slow=12) is None


# ---------------------------------------------------------------------------
# RSI（14，Wilder 平滑）
# ---------------------------------------------------------------------------


class TestRsi:
    def test_wilder_smoothing_hand_computed(self) -> None:
        """7 涨 +1 / 7 跌 −1 / 末根 +1 → RSI = 375/7 ≈ 53.5714（精确分数）。

        手算：种子 avgGain=avgLoss=7×1/14=0.5；
        末根 avgGain=(0.5×13+1)/14=15/28，avgLoss=(0.5×13+0)/14=13/28；
        RSI = 100 − 100/(1+15/13) = 100×15/28 = 375/7。
        """
        closes = [100.0 + 1.0 * i for i in range(8)]  # 100..107：7 个 +1
        closes += [closes[-1] - 1.0 * (i + 1) for i in range(7)]  # 7 个 −1 → 100
        closes.append(101.0)  # 末根 +1
        assert len(closes) == 16
        snap = compute_rsi(_bars(closes))
        assert snap is not None
        assert snap.value == pytest.approx(float(Fraction(375, 7)), abs=1e-10)
        assert snap.period == 14

    def test_symmetric_window_is_exactly_50(self) -> None:
        """种子窗 7 涨 7 跌 → avgGain=avgLoss → RSI 恰 50。"""
        closes = [100.0 + i for i in range(8)] + [107.0 - i for i in range(1, 8)]
        assert len(closes) == 15
        snap = compute_rsi(_bars(closes))
        assert snap is not None
        assert snap.value == pytest.approx(50.0, abs=1e-12)

    def test_insufficient_window_returns_none(self) -> None:
        """需要 period+1=15 根（14 个差分）；14 根必须 None。"""
        assert compute_rsi(_bars([100.0] * 14)) is None

    def test_edge_all_gains_and_all_flat(self) -> None:
        """全涨 → 100（avgLoss=0）；全平 → 50 中性（不造极值）。"""
        up = compute_rsi(_bars([100.0 + i for i in range(15)]))
        assert up is not None and up.value == 100.0
        flat = compute_rsi(_bars([100.0] * 15))
        assert flat is not None and flat.value == 50.0


# ---------------------------------------------------------------------------
# WR（14，中国软件 0~100 口径）
# ---------------------------------------------------------------------------


class TestWr:
    def _fixed_window_bars(self, last_close: float) -> list[OHLCVBar]:
        """14 根同形 K 线（H=20/L=10/O=15），只改末根收盘，方便手算。"""
        return [
            _bar(i, 15.0, 20.0, 10.0, last_close if i == 13 else 15.0)
            for i in range(14)
        ]

    def test_hand_computed_values(self) -> None:
        """WR = (H14−C)/(H14−L14)×100：收盘 15/20/10 → 50/0/100。"""
        mid = compute_wr(self._fixed_window_bars(15.0))
        assert mid is not None and mid.value == pytest.approx(50.0)
        top = compute_wr(self._fixed_window_bars(20.0))
        assert top is not None and top.value == pytest.approx(0.0)
        bottom = compute_wr(self._fixed_window_bars(10.0))
        assert bottom is not None and bottom.value == pytest.approx(100.0)

    def test_flat_window_neutral_50(self) -> None:
        """一字板（H=L）→ 50 中性，与 KDJ RSV=50 同纪律。"""
        snap = compute_wr(_bars([15.0] * 14, spread=0.0))
        assert snap is not None and snap.value == 50.0

    def test_insufficient_window_returns_none(self) -> None:
        assert compute_wr(_bars([15.0] * 13)) is None


# ---------------------------------------------------------------------------
# CCI（20，Lambert 标准口径）
# ---------------------------------------------------------------------------


class TestCci:
    def test_ramp_tp_hand_computed(self) -> None:
        """TP 序列 1..20（H=L=C=v）手算对拍 CCI = 380/3。

        手算：MA=10.5；MD = mean(|v−10.5|) = 2×(0.5+1.5+…+9.5)/20 = 5；
        CCI = (20−10.5)/(0.015×5) = 9.5/0.075 = 380/3 ≈ 126.6667。
        """
        bars = [
            _bar(i, float(v), float(v), float(v), float(v))
            for i, v in enumerate(range(1, 21))
        ]
        snap = compute_cci(bars)
        assert snap is not None
        assert snap.value == pytest.approx(float(Fraction(380, 3)), abs=1e-10)
        assert snap.period == 20

    def test_flat_window_zero_not_infinity(self) -> None:
        """MD=0（全窗 TP 恒定）→ 0，绝不 ±∞/NaN。"""
        snap = compute_cci(_bars([10.0] * 20, spread=0.0))
        assert snap is not None and snap.value == 0.0

    def test_insufficient_window_returns_none(self) -> None:
        assert compute_cci(_bars([10.0] * 19)) is None


# ---------------------------------------------------------------------------
# 汇总入口：compute_all_technical_indicators
# ---------------------------------------------------------------------------


class TestAllIndicators:
    def test_each_gate_independent(self) -> None:
        """各指标独立判窗口：19 根只缺 MACD/CCI，RSI/WR 照常出值。"""
        bars = _bars([100.0 + i * 0.5 for i in range(19)])
        macd, rsi, wr, cci = compute_all_technical_indicators(bars)
        assert macd is None  # 34 根起算
        assert rsi is not None  # 15 根起算
        assert wr is not None  # 14 根起算
        assert cci is None  # 20 根起算

    def test_full_window_all_present(self) -> None:
        bars = _bars([100.0 + i * 0.5 for i in range(40)])
        macd, rsi, wr, cci = compute_all_technical_indicators(bars)
        assert None not in (macd, rsi, wr, cci)


# ---------------------------------------------------------------------------
# format_stock_brief：新指标非空才展示（宁缺毋滥，审查 H-08 ④）
# ---------------------------------------------------------------------------


def _quote() -> EquityQuote:
    return EquityQuote(
        ticker="NVDA",
        name="英伟达",
        exchange="NASDAQ",
        currency="USD",
        price=184.95,
        change_pct=-0.38,
        source="eastmoney",
        as_of=None,
        status=FinanceDataStatus.OK,
        delayed=True,
    )


def _series(bars: list[OHLCVBar]) -> OHLCVSeries:
    return OHLCVSeries(
        ticker="NVDA",
        name="英伟达",
        currency="USD",
        bars=bars,
        source="eastmoney_kline",
        status=FinanceDataStatus.OK,
    )


class TestBriefShowsIndicatorsOnlyWhenAvailable:
    def test_full_series_shows_all_four(self) -> None:
        """40 根 → 四指标行齐全；KDJ 既有行不受影响（零回退）。

        与生产调用方（capabilities/stocks.py）同构：KDJ 由 compute_kdj
        算好作为入参传入 brief，新指标由 brief 内部从同一 series 计算。
        """
        bars = _bars([100.0 + i for i in range(40)])
        text = format_stock_brief(_quote(), _series(bars), compute_kdj(bars), None)
        assert "MACD(12,26,9)：DIF" in text
        assert "RSI(14)：" in text
        assert "WR(14)：" in text
        assert "CCI(20)：" in text
        assert "KDJ(9)：" in text

    def test_short_series_hides_new_indicators_silently(self) -> None:
        """10 根 → 四指标全部静默消失（None 不占版面），KDJ 照常出值。"""
        bars = _bars([100.0 + i for i in range(10)])
        text = format_stock_brief(_quote(), _series(bars), compute_kdj(bars), None)
        assert "MACD(" not in text
        assert "RSI(" not in text
        assert "WR(" not in text
        assert "CCI(" not in text
        assert "KDJ(9)：" in text  # 10 根 ≥ 9，KDJ 既有承诺文案不变

    def test_no_series_shows_neither(self) -> None:
        """无 K 线 → 新指标与 KDJ 一样走暂缺/缺席路径，不造数。"""
        text = format_stock_brief(_quote(), None, None, None)
        assert "MACD(" not in text
        assert "RSI(" not in text
        assert "WR(" not in text
        assert "CCI(" not in text
        assert "KDJ 暂缺" in text

"""金融图表 SVG 纯计算（零网络、纯标准库：statistics/html/math）。

供股指走势缩略折线（风格对齐 output/card_render/bridge._spark_points：
红涨 #d54941 / 绿跌 #2e9e6b）与多列数值分布的箱形图使用。
所有函数 best-effort：脏输入一律返回 status="unavailable"（svg=""），
绝不向调用方抛异常。

【口径红线】本模块一切「K」均指 K 线（Candlestick，烛台 OHLCV）数据。
单日 OHLC（开/高/低/收四个价位）**不得**直接作为箱形图输入——箱形图的
合法输入语义是「多列独立数值分布」（例如近 30 日日涨跌幅按周分列），
不是单根烛台的四价位。机械上 4 个数值恰好满足最小样本数，这条语义
边界无法在纯计算层识别，只能由调用方按本口径约束自己的输入。
"""

from __future__ import annotations

import html
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

__all__ = ["ChartResult", "box_plot_svg", "daily_returns", "line_chart_svg"]

# 折线自动配色（与 bridge._spark_points 同源）：红涨绿跌。
_UP_COLOR = "#d54941"
_DOWN_COLOR = "#2e9e6b"
# 箱形图最小样本数：每列有效数值 ≥4 才允许成箱。
_BOX_MIN_SAMPLES = 4


@dataclass(frozen=True)
class ChartResult:
    """图表计算结果：svg 为空串表示不可用，note 说明不可用原因。"""

    svg: str  # 空串 = 不可用
    status: str  # "ok" | "unavailable"
    note: str = ""  # 不可用原因（ok 时为空）


def _clean_values(values: Any) -> list[float]:
    """逐元素转 float，丢弃脏值（非数/NaN/Inf）；入参不可迭代返回空表。"""
    cleaned: list[float] = []
    try:
        iterator = iter(values)
    except TypeError:
        return cleaned
    for item in iterator:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            cleaned.append(number)
    return cleaned


def _canvas_size(
    width: Any, height: Any, stroke_width: Any
) -> tuple[float, float, float] | None:
    """画布参数合法化：非数/非有限/非正一律判无效。"""
    try:
        w, h, sw = float(width), float(height), float(stroke_width)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(w) and math.isfinite(h) and math.isfinite(sw)):
        return None
    if w <= 0 or h <= 0 or sw <= 0:
        return None
    return w, h, sw


def line_chart_svg(
    values: Sequence[float],
    *,
    width: float = 128,
    height: float = 40,
    color: str | None = None,
    stroke_width: float = 2,
) -> ChartResult:
    """收盘序列（旧→新）→ 折线缩略 SVG；风格对齐 bridge._spark_points。

    color=None 时自动：末值 ≥ 首值红涨（#d54941），否则绿跌（#2e9e6b）。
    有效数值 <2（脏值过滤后）→ unavailable「暂无历史走势数据」。
    polyline 归一化到 viewBox，四周留 padding（随线宽自适应）防裁边。
    """
    canvas = _canvas_size(width, height, stroke_width)
    if canvas is None:
        return ChartResult("", "unavailable", "画布参数无效")
    w, h, sw = canvas
    points_values = _clean_values(values)
    if len(points_values) < 2:
        return ChartResult("", "unavailable", "暂无历史走势数据")
    low, high = min(points_values), max(points_values)
    span = (high - low) or 1.0
    pad = max(4.0, sw / 2 + 1.0)
    step = (w - 2 * pad) / (len(points_values) - 1)
    points = " ".join(
        f"{pad + index * step:.2f},{h - pad - (value - low) / span * (h - 2 * pad):.2f}"
        for index, value in enumerate(points_values)
    )
    stroke = color or (
        _UP_COLOR if points_values[-1] >= points_values[0] else _DOWN_COLOR
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:g}" height="{h:g}"'
        f' viewBox="0 0 {w:g} {h:g}">'
        f'<polyline fill="none" stroke="{stroke}" stroke-width="{sw:g}"'
        ' stroke-linecap="round" stroke-linejoin="round"'
        f' points="{points}"/></svg>'
    )
    return ChartResult(svg, "ok")


@dataclass(frozen=True)
class _BoxStats:
    """单列五数概括 + 须线端点 + 离群值（Q1/Q3 用 inclusive 分位）。"""

    low: float
    q1: float
    median: float
    q3: float
    high: float
    whisker_low: float
    whisker_high: float
    outliers: tuple[float, ...]


def _box_stats(values: list[float]) -> _BoxStats:
    """五数：min/Q1/median/Q3/max；须取 [Q1-1.5·IQR, Q3+1.5·IQR] 内最远点。"""
    q1, median, q3 = statistics.quantiles(values, n=4, method="inclusive")
    iqr = q3 - q1
    low_fence = q1 - 1.5 * iqr
    high_fence = q3 + 1.5 * iqr
    inliers = [v for v in values if low_fence <= v <= high_fence]
    outliers = tuple(sorted(v for v in values if v < low_fence or v > high_fence))
    return _BoxStats(
        low=min(values),
        q1=q1,
        median=median,
        q3=q3,
        high=max(values),
        whisker_low=min(inliers),
        whisker_high=max(inliers),
        outliers=outliers,
    )


def box_plot_svg(
    series: Sequence[Sequence[float]],
    *,
    labels: Sequence[str] | None = None,
    width: float = 320,
    height: float = 160,
    color: str = "#4a90d9",
) -> ChartResult:
    """多列数值分布 → 并排箱形 SVG（须-箱-中位线-离群点）。

    每列有效数值 ≥ _BOX_MIN_SAMPLES(4) 才成箱；不足的列跳过并计入 note
    （如「1 列样本不足已跳过」）；全部不足 → unavailable
    「样本不足，无法绘制箱形图」。
    labels 对应原始列序（跳过的列不占盒位），经 html.escape 后渲染为
    <text>；数值坐标全部是 float 格式化，无注入面。

    【口径红线】本函数一切「K」均指 K 线（Candlestick，烛台 OHLCV）数据。
    单日 OHLC（开/高/低/收）**不得**直接作为箱形图输入：箱形图输入是多列
    数值分布，不是单根烛台的四价位（机械上 4 个数恰好满足最小样本数，
    语义约束靠调用方遵守本 docstring，计算层无法识别）。
    """
    canvas = _canvas_size(width, height, 1.0)
    if canvas is None:
        return ChartResult("", "unavailable", "画布参数无效")
    w, h, _ = canvas
    try:
        columns_raw = list(series)
    except TypeError:
        return ChartResult("", "unavailable", "样本不足，无法绘制箱形图")
    columns: list[tuple[int, _BoxStats]] = []
    skipped = 0
    for index, column in enumerate(columns_raw):
        cleaned = _clean_values(column)
        if len(cleaned) >= _BOX_MIN_SAMPLES:
            columns.append((index, _box_stats(cleaned)))
        else:
            skipped += 1
    if not columns:
        return ChartResult("", "unavailable", "样本不足，无法绘制箱形图")

    top, bottom, side = 12.0, 26.0, 10.0
    plot_h = h - top - bottom
    slot = (w - 2 * side) / len(columns)
    box_w = min(slot * 0.5, 40.0)
    extremes = [s.whisker_low for _, s in columns]
    extremes.extend(s.whisker_high for _, s in columns)
    for _, stats in columns:
        extremes.extend(stats.outliers)
    g_min, g_max = min(extremes), max(extremes)
    g_span = (g_max - g_min) or 1.0

    def y(value: float) -> float:
        return top + (1.0 - (value - g_min) / g_span) * plot_h

    shapes: list[str] = []
    texts: list[str] = []
    for slot_index, (origin_index, stats) in enumerate(columns):
        center = side + slot * (slot_index + 0.5)
        x0, x1 = center - box_w / 2, center + box_w / 2
        cap_half = box_w / 4
        y_q1, y_med, y_q3 = y(stats.q1), y(stats.median), y(stats.q3)
        y_lo, y_hi = y(stats.whisker_low), y(stats.whisker_high)
        shapes.append(
            f'<line x1="{center:.2f}" y1="{y_hi:.2f}"'
            f' x2="{center:.2f}" y2="{y_q3:.2f}"/>'
            f'<line x1="{center:.2f}" y1="{y_q1:.2f}"'
            f' x2="{center:.2f}" y2="{y_lo:.2f}"/>'
            f'<line x1="{center - cap_half:.2f}" y1="{y_lo:.2f}"'
            f' x2="{center + cap_half:.2f}" y2="{y_lo:.2f}"/>'
            f'<line x1="{center - cap_half:.2f}" y1="{y_hi:.2f}"'
            f' x2="{center + cap_half:.2f}" y2="{y_hi:.2f}"/>'
            f'<rect x="{x0:.2f}" y="{y_q3:.2f}" width="{box_w:.2f}"'
            f' height="{max(y_q1 - y_q3, 1.0):.2f}"/>'
            f'<line x1="{x0:.2f}" y1="{y_med:.2f}"'
            f' x2="{x1:.2f}" y2="{y_med:.2f}"/>'
        )
        for value in stats.outliers:
            shapes.append(
                f'<circle cx="{center:.2f}" cy="{y(value):.2f}" r="2.5"/>'
            )
        if labels is not None and origin_index < len(labels):
            label = html.escape(str(labels[origin_index]))
            texts.append(
                f'<text x="{center:.2f}" y="{h - 6:.2f}"'
                f' text-anchor="middle" font-size="10">{label}</text>'
            )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:g}" height="{h:g}"'
        f' viewBox="0 0 {w:g} {h:g}">'
        f'<g fill="none" stroke="{color}" stroke-width="1.5">'
        f'{"".join(shapes)}</g>'
        f'<g fill="#666666" stroke="none">{"".join(texts)}</g></svg>'
    )
    note = f"{skipped} 列样本不足已跳过" if skipped else ""
    return ChartResult(svg, "ok", note)


def daily_returns(values: Sequence[float]) -> tuple[float, ...]:
    """相邻涨跌幅%（len-1 个）；有效值不足 2 个返回空元组，绝不抛异常。"""
    cleaned = _clean_values(values)
    if len(cleaned) < 2:
        return ()
    return tuple(
        (current / previous - 1.0) * 100.0
        for previous, current in pairwise(cleaned)
    )

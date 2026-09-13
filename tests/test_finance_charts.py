"""金融图表纯计算回归：折线/箱形 SVG + 日涨跌幅（零网络、纯标准库）。"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.sources.finance_chart import (
    _box_stats,
    box_plot_svg,
    daily_returns,
    line_chart_svg,
)

# ---------- 折线图 line_chart_svg ----------


def test_line_chart_ok_with_enough_points() -> None:
    result = line_chart_svg([1.0, 3.0, 2.0, 5.0])
    assert result.status == "ok"
    assert result.svg
    assert "<polyline" in result.svg
    assert 'viewBox="0 0 128 40"' in result.svg


def test_line_chart_needs_two_valid_points() -> None:
    for bad in ([], [7.0], ["a", "b"], None):
        result = line_chart_svg(bad)
        assert result.status == "unavailable"
        assert result.svg == ""
        assert result.note == "暂无历史走势数据"


def test_line_chart_filters_dirty_values_before_count() -> None:
    # 「x」过滤后只剩 1 个有效值 → 不可用（不过滤会误当 2 点）。
    result = line_chart_svg([1.0, "x"])
    assert result.status == "unavailable"
    assert result.note == "暂无历史走势数据"
    # 过滤后仍有 ≥2 个有效值 → 正常出图。
    ok = line_chart_svg([1.0, "x", 3.0])
    assert ok.status == "ok"
    assert "<polyline" in ok.svg


def test_line_chart_auto_color_up_is_red() -> None:
    assert "#d54941" in line_chart_svg([1.0, 2.0, 3.0]).svg


def test_line_chart_auto_color_down_is_green() -> None:
    assert "#2e9e6b" in line_chart_svg([3.0, 2.0, 1.0]).svg


def test_line_chart_flat_counts_as_up() -> None:
    assert "#d54941" in line_chart_svg([2.0, 2.0]).svg


def test_line_chart_explicit_color_overrides_auto() -> None:
    svg = line_chart_svg([3.0, 1.0], color="#123456").svg
    assert "#123456" in svg
    assert "#2e9e6b" not in svg


def test_line_chart_points_stay_inside_viewbox() -> None:
    result = line_chart_svg(
        [1.0, 9.0, 4.0, 7.0, 2.0, 8.0], width=200, height=60, stroke_width=6
    )
    assert result.status == "ok"
    points = result.svg.split('points="', 1)[1].split('"', 1)[0]
    for pair in points.split():
        x_text, y_text = pair.split(",")
        assert 0.0 <= float(x_text) <= 200.0
        assert 0.0 <= float(y_text) <= 60.0


def test_line_chart_invalid_canvas_is_unavailable() -> None:
    assert line_chart_svg([1.0, 2.0], width=0).status == "unavailable"
    assert line_chart_svg([1.0, 2.0], stroke_width=-1).status == "unavailable"
    assert line_chart_svg([1.0, 2.0], width="wide").status == "unavailable"


# ---------- 箱形图 box_plot_svg ----------


def test_box_stats_quartiles_are_inclusive_method() -> None:
    stats = _box_stats([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    assert (stats.low, stats.q1, stats.median, stats.q3, stats.high) == (
        1.0,
        2.5,
        4.0,
        5.5,
        7.0,
    )
    assert stats.whisker_low == 1.0
    assert stats.whisker_high == 7.0
    assert stats.outliers == ()


def test_box_stats_flags_outliers_and_pulls_whisker_in() -> None:
    stats = _box_stats([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 100.0])
    assert (stats.q1, stats.median, stats.q3) == (2.5, 4.0, 5.5)
    assert stats.whisker_high == 6.0  # 须缩回到界内最远点，不取 100
    assert stats.outliers == (100.0,)


def test_box_plot_two_valid_columns_make_two_boxes() -> None:
    result = box_plot_svg(
        [[1, 2, 3, 4, 5, 6, 7], [2, 4, 6, 8, 10, 12, 14]],
        labels=["甲", "乙"],
    )
    assert result.status == "ok"
    assert result.svg.count("<rect") == 2
    assert "<text" in result.svg


def test_box_plot_draws_outlier_circles() -> None:
    result = box_plot_svg([[1, 2, 3, 4, 5, 6, 100]])
    assert result.status == "ok"
    assert "<circle" in result.svg


def test_box_plot_skips_short_columns_with_note() -> None:
    result = box_plot_svg([[1, 2, 3], [5, 6, 7, 8, 9, 10]])
    assert result.status == "ok"
    assert result.svg.count("<rect") == 1
    assert result.note == "1 列样本不足已跳过"


def test_box_plot_all_columns_insufficient_is_unavailable() -> None:
    for bad in ([], [[1, 2, 3]], ["junk"], None):
        result = box_plot_svg(bad)
        assert result.status == "unavailable"
        assert result.svg == ""
        assert result.note == "样本不足，无法绘制箱形图"


def test_box_plot_labels_are_html_escaped() -> None:
    result = box_plot_svg(
        [[1, 2, 3, 4, 5, 6, 7]], labels=["<script>alert(1)</script>"]
    )
    assert result.status == "ok"
    assert "&lt;script&gt;" in result.svg
    assert "<script>" not in result.svg


def test_box_plot_four_values_form_one_box_mechanically() -> None:
    # 机械行为锁：4 个有效值恰好满足最小样本数 → 成箱。
    # 语义红线（单日 OHLC 不得作为箱形图输入）由 docstring 口径约束，
    # 纯计算层无法识别「这 4 个数是 OHLC」——见模块与函数 docstring。
    result = box_plot_svg([[10.0, 11.0, 9.0, 10.5]])
    assert result.status == "ok"
    assert result.svg.count("<rect") == 1


# ---------- 日涨跌幅 daily_returns ----------


def test_daily_returns_pairwise_math() -> None:
    assert daily_returns([200, 100]) == (-50.0,)
    assert daily_returns([100, 110]) == pytest.approx((10.0,))
    assert daily_returns([100, 110, 121]) == pytest.approx((10.0, 10.0))


def test_daily_returns_short_or_dirty_input_is_empty() -> None:
    assert daily_returns([]) == ()
    assert daily_returns([42.0]) == ()
    assert daily_returns(None) == ()
    assert daily_returns("xyz") == ()


def test_daily_returns_skips_dirty_values() -> None:
    assert daily_returns([100, "x", 200]) == pytest.approx((100.0,))

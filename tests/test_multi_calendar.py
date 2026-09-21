"""多历法换算回归（vis3 2026-09-13 用户裁定：历史上的今天附多纪年）。"""

from __future__ import annotations

from datetime import date

from plugins.bot_unified_runtime.domains.divination.data.multi_calendar import (
    byzantine_year,
    gregorian_to_jdn,
    hijri_from_gregorian,
    japan_era,
    multi_calendar_line,
)


def test_jdn_anchor_matches_fliegel_van_flandern() -> None:
    # 2000-01-01 = JDN 2451545（教科书锚点）。
    assert gregorian_to_jdn(2000, 1, 1) == 2451545


def test_hijri_algorithm_anchor() -> None:
    # Kuwaiti 算法内建锚点：1979-11-21（公历）= 1400-01-01（Hijri 元旦）。
    assert hijri_from_gregorian(1979, 11, 21) == (1400, 1, 1)


def test_hijri_output_ranges_sane() -> None:
    year_h, month_h, day_h = hijri_from_gregorian(2026, 9, 13)
    assert 1447 <= year_h <= 1449
    assert 1 <= month_h <= 12
    assert 1 <= day_h <= 30


def test_japan_era_table_and_fallback() -> None:
    assert japan_era(2026, 9, 13) == "日本令和8年"
    assert japan_era(1990, 6, 1) == "日本平成2年"
    assert japan_era(1900, 1, 1) == ""  # 年号表覆盖不到 → 省略


def test_byzantine_year_rolls_on_september() -> None:
    assert byzantine_year(2026, 9, 13) == 2026 + 5509
    assert byzantine_year(2026, 8, 31) == 2026 + 5508


def test_multi_calendar_line_shape() -> None:
    line = multi_calendar_line(date(2026, 9, 13))
    assert line.startswith("公历9月13日")
    assert "黄帝纪元4723年" in line
    assert "佛历2569年" in line
    assert "伊斯兰历约" in line
    assert "日本令和8年" in line
    assert "拜占庭历" in line

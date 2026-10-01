"""需求 10：历法读数层的**边界**回归（跨年 / 闰月 / 闰日 / 时区 / 负年 / 非法输入）。

真身唯一在 ``domains/divination/data/multi_calendar``（另一席在制品，本席只读不改）；
本文件只锁边界判据，且全部用**不变量**断言（往返、区间、单调、日界归属、越界即拒），
不手写「某年某月某日＝某历某月某日」这种天文近似串去冒充权威——精确对点已由
``tests/test_multi_calendar.py`` / ``tests/test_self_calendar.py`` 钉死，这里补的是它们
没逐条点名的边角。全离线、纯函数、不联网。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from plugins.bot_unified_runtime.domains.divination.data.multi_calendar import (
    gregorian_to_jdn,
    hijri_from_gregorian,
    julian_from_gregorian,
    julian_gregorian_offset,
    julian_to_jdn,
    lunar_from_gregorian,
    lunar_leap_month,
    lunar_new_year,
    rabjung_year,
)
from plugins.bot_unified_runtime.domains.ops.self_calendar.calendar_leg import (
    build_calendar_snapshot,
)
from plugins.bot_unified_runtime.domains.ops.self_calendar.moments import (
    resolve_moments,
)

# 含闰日、跨年、窗口两端附近的样本（1901-2099 内）。
_ROUND_TRIP_SAMPLES = [
    (2000, 3, 1),
    (2024, 2, 29),  # 闰日
    (2026, 9, 29),
    (2026, 12, 31),  # 跨年边界
    (2027, 1, 1),
    (2096, 2, 29),  # 窗口内最后一个闰日
]


@pytest.mark.parametrize("y,m,d", _ROUND_TRIP_SAMPLES)
def test_gregorian_to_julian_round_trips_through_jdn(y: int, m: int, d: int) -> None:
    """公历→JDN→儒略历标签→JDN 必须回到同一根（同一天对齐只认 JDN）。"""
    jdn = gregorian_to_jdn(y, m, d)
    julian = julian_from_gregorian(y, m, d)
    assert julian_to_jdn(julian.year, julian.month, julian.day) == jdn


@pytest.mark.parametrize("y,m,d", _ROUND_TRIP_SAMPLES)
def test_julian_gregorian_offset_is_stable_13_in_window(y: int, m: int, d: int) -> None:
    """1900-03-13～2100-03-14 之间两历同日差恒为 13 天（含闰日样本逐一验）。"""
    assert julian_gregorian_offset(y, m, d) == 13


def test_jdn_increments_one_per_consecutive_day() -> None:
    """连续两日的 JDN 恒差 1——闰日/跨月/跨年边界都不能差 0 或差 2。"""
    pairs = [((2024, 2, 28), (2024, 2, 29)), ((2024, 2, 29), (2024, 3, 1)),
             ((2026, 12, 31), (2027, 1, 1))]
    for (ay, am, ad), (by, bm, bd) in pairs:
        assert gregorian_to_jdn(by, bm, bd) - gregorian_to_jdn(ay, am, ad) == 1


def test_hijri_output_invariants_across_year_boundary() -> None:
    """伊斯兰历读数恒落在合法区间，且跨年边界不炸（月 1-12、日 1-30、年为正）。"""
    for d in (date(2026, 12, 31), date(2027, 1, 1), date(2024, 2, 29), date(2026, 9, 29)):
        year, month, day = hijri_from_gregorian(d.year, d.month, d.day)
        assert 1000 < year < 2000
        assert 1 <= month <= 12
        assert 1 <= day <= 30


def test_lunar_new_year_maps_to_first_day_of_regular_first_month() -> None:
    """正月初一这条不变量：新-year 当天回算＝正月初一（day=1、正月、非闰）。"""
    for lunar_year in (2020, 2023, 2025, 2026, 2027):
        ny = lunar_new_year(lunar_year)
        assert ny.year == lunar_year  # 春节落在同名公历年
        lunar = lunar_from_gregorian(ny.year, ny.month, ny.day)
        assert lunar.day == 1, f"{lunar_year} 正月初一回算出 day={lunar.day}"
        assert lunar.month == 1 and not lunar.is_leap_month


@pytest.mark.parametrize(
    ("gregorian_year", "expected_leap_month"),
    [
        (2020, 4),  # 闰四月（公开历书，可核）
        (2023, 2),  # 闰二月
        (2025, 6),  # 闰六月
        (2026, 0),  # 该农历年前段无闰月（2026 不闰）
    ],
)
def test_lunar_leap_month_matches_published_almanac(gregorian_year: int, expected_leap_month: int) -> None:
    """闰月月序逐一对公开历书——闰算是历法最容易错的一面，单独立边界锁。"""
    lunar = lunar_from_gregorian(gregorian_year, 6, 1)  # 年中任一天定农历纪年
    assert lunar_leap_month(lunar.year) == expected_leap_month


def test_rabjung_cycle_epoch_and_wraparound_boundaries() -> None:
    """藏历饶迥：元年=公历 1027→第 1 轮第 1 年；60 年一轮，跨年边界正确进位。"""
    assert rabjung_year(1027) == (1, 1)
    assert rabjung_year(1086) == (1, 60)  # 第 1 轮末年
    assert rabjung_year(1087) == (2, 1)  # 进下一轮
    assert rabjung_year(2026)[0] >= 1 and 1 <= rabjung_year(2026)[1] <= 60


def test_rabjung_negative_before_epoch_is_rejected() -> None:
    """负年 / 早于元年的输入：直接 ValueError，不外推到 1027 之前。"""
    with pytest.raises(ValueError):
        rabjung_year(1000)
    with pytest.raises(ValueError):
        rabjung_year(-5)


@pytest.mark.parametrize(
    ("y", "m", "d"),
    [
        (1900, 6, 1),  # 早于支持窗口下限 1901
        (2100, 1, 1),  # 晚于上限 2099
        (2026, 13, 1),  # 非法月
        (2026, 2, 30),  # 非法日（2 月无 30）
    ],
)
def test_lunar_rejects_out_of_window_and_illegal_input(y: int, m: int, d: int) -> None:
    """农历换算对越界与非法日期一律 ValueError，不静默外推、不裁成邻近合法日。"""
    with pytest.raises(ValueError):
        lunar_from_gregorian(y, m, d)


def test_snapshot_degrades_outside_window_without_fabricating() -> None:
    """快照层把真身的越界 ValueError 转成 supported=False + 「未探测」，不抛、不顶替。"""
    snap = build_calendar_snapshot(date(1899, 1, 1))
    assert snap.supported is False
    assert "未探测" in snap.reason
    # 窗口内正常日：supported 且四历法读数齐全。
    ok = build_calendar_snapshot(date(2026, 9, 29))
    assert ok.supported is True and ok.lunar is not None and ok.hijri is not None


def test_calendar_day_follows_beijing_not_utc_at_divergence_boundary() -> None:
    """跨日分歧那一分钟：历法取日必须跟东八区日界，不能跟 UTC 差一天。"""
    # 2026-02-16T16:30Z = 北京 2026-02-17 00:30（UTC 与北京不同日）。
    moment = datetime(2026, 2, 16, 16, 30, tzinfo=timezone.utc)
    snapshot = resolve_moments(moment, timezone_name="Asia/Shanghai")
    assert snapshot.utc.day == date(2026, 2, 16)
    assert snapshot.calendar_day == date(2026, 2, 17)  # 历法日跟北京日界
    assert snapshot.day_divergence_note  # 跨日必须点名
    # 快照确实按北京那天算，而不是按 UTC 那天。
    snap = build_calendar_snapshot(snapshot.calendar_day)
    assert snap.supported is True and snap.day == date(2026, 2, 17)

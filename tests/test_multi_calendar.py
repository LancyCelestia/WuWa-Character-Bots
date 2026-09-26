"""多历法换算回归（vis3 2026-09-13 用户裁定：历史上的今天附多纪年）。

2026-09-25 goal18 第 10 项追加下半区：藏历/东正教历两组新函数（工作树里
multi_calendar 已实现，但 docstring 自称"见测试"的钉死表当时并不存在——
本区把它补上）。所有期望值取**公开可独立核对**的固定日期（东正教复活节
2019-2028 公历实绩、东正教圣诞=公历 1 月 7 日、春节 2026-02-17、
2014 闰九月、饶迥元年 1027、2026 藏历火马年），不拿实现自产数自证。
"""

from __future__ import annotations

from datetime import date

import pytest

from plugins.bot_unified_runtime.domains.divination.data.multi_calendar import (
    byzantine_year,
    gregorian_to_jdn,
    hijri_from_gregorian,
    japan_era,
    jdn_to_julian,
    julian_from_gregorian,
    julian_gregorian_offset,
    julian_to_jdn,
    lunar_from_gregorian,
    lunar_leap_month,
    lunar_new_year,
    multi_calendar_line,
    new_rite_pascha_gregorian,
    orthodox_calendar_lines,
    orthodox_pascha_gregorian,
    rabjung_year,
    rich_calendar_lines,
    tibetan_year_lines,
    tibetan_year_name,
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


# ---------------------------------------------------------------------------
# ② 东正教历（goal18 第 10 项 a）：儒略历换算 + 两条 computus，全部对外核对值。
# ---------------------------------------------------------------------------

# 君士坦丁堡牧首区/各东正教教会公布的历年复活节（公历日期），2019-2028 十年。
_ORTHODOX_PASCHA_PUBLIC = {
    2019: date(2019, 4, 28),
    2020: date(2020, 4, 19),
    2021: date(2021, 5, 2),
    2022: date(2022, 4, 24),
    2023: date(2023, 4, 16),
    2024: date(2024, 5, 5),
    2025: date(2025, 4, 20),
    2026: date(2026, 4, 12),
    2027: date(2027, 5, 2),
    2028: date(2028, 4, 16),
}
# 同十年的公历（Western）复活节——修订儒略历教会的 computus 与公历同日。
_NEW_RITE_PASCHA_PUBLIC = {
    2019: date(2019, 4, 21),
    2020: date(2020, 4, 12),
    2021: date(2021, 4, 4),
    2022: date(2022, 4, 17),
    2023: date(2023, 4, 9),
    2024: date(2024, 3, 31),
    2025: date(2025, 4, 20),
    2026: date(2026, 4, 5),
    2027: date(2027, 3, 28),
    2028: date(2028, 4, 16),
}


@pytest.mark.parametrize("year", sorted(_ORTHODOX_PASCHA_PUBLIC))
def test_orthodox_pascha_matches_published_gregorian_dates(year: int) -> None:
    assert orthodox_pascha_gregorian(year) == _ORTHODOX_PASCHA_PUBLIC[year]


@pytest.mark.parametrize("year", sorted(_NEW_RITE_PASCHA_PUBLIC))
def test_new_rite_pascha_matches_western_easter(year: int) -> None:
    assert new_rite_pascha_gregorian(year) == _NEW_RITE_PASCHA_PUBLIC[year]


def test_orthodox_christmas_julian_pair_and_offset() -> None:
    """东正教圣诞（儒略历 12-25）在 1900-2100 段落在公历 1 月 7 日——公开常识锚。"""
    assert julian_from_gregorian(2027, 1, 7) == date(2026, 12, 25)
    assert julian_gregorian_offset(2027, 1, 7) == 13


def test_julian_gregorian_offset_constant_in_supported_window() -> None:
    # 支持区 1901-2099 全程 13 天（1900/2100 两个非闰世纪年才换档）。
    for sample in ((1901, 3, 1), (2000, 2, 29), (2026, 9, 25), (2099, 12, 31)):
        assert julian_gregorian_offset(*sample) == 13, sample


def test_jdn_julian_round_trip() -> None:
    for jdn in (2451545, 2461309, julian_to_jdn(2026, 12, 25)):
        label = jdn_to_julian(jdn)
        assert julian_to_jdn(label.year, label.month, label.day) == jdn


def test_orthodox_calendar_lines_are_honest_and_bounded() -> None:
    lines = "\n".join(orthodox_calendar_lines(2026, 9, 25))
    assert "儒略历2026-09-12" in lines  # 同日两历标签差 13 天
    assert "差13天" in lines
    # 不给任何编造的瞻礼日：除复活节外不报"某圣瞻是周几"式断言。
    assert " Epiphany" not in lines and "主显" not in lines
    assert "按该教会自身规定回答" in lines


# ---------------------------------------------------------------------------
# ③ 藏历：只钉得住的（饶迥周期/历年名），月·日·洛萨无源 ⇒ 锁"诚实缺席"本身。
# ---------------------------------------------------------------------------


def test_rabjung_epoch_boundaries() -> None:
    # 饶迥元年=公历 1027（学界通行）；60 年一轮。
    assert rabjung_year(1027) == (1, 1)
    assert rabjung_year(1086) == (1, 60)
    assert rabjung_year(1087) == (2, 1)
    assert rabjung_year(2026) == (17, 40)  # 第十七绕迥自 1987 起（1027+16×60）
    with pytest.raises(ValueError):
        rabjung_year(1026)


def test_tibetan_year_name_anchors() -> None:
    # 1984 甲子=阳木鼠（藏汉同源干支）；2026 藏历火马年（洛萨公告面广泛转载）；
    # 生肖"鸡"按藏历习惯写作"鸟"（2005 乙酉=阴木鸟）。
    assert tibetan_year_name(1984) == "阳木鼠年"
    assert tibetan_year_name(2026) == "阳火马年"
    assert tibetan_year_name(2005) == "阴木鸟年"


def test_tibetan_month_day_lopsang_are_declared_unsourced() -> None:
    """藏历月/日与洛萨日期：**没源就明说没源**，这是本模块唯一不许实现的面。"""
    text = "\n".join(tibetan_year_lines(2026))
    assert "本仓无源故不推算" in text
    assert "洛萨" in text
    assert "别拿农历或公历日期顶替" in text


# ---------------------------------------------------------------------------
# ④ 农历/伊斯兰历对外核对锚 + rich_calendar_lines 覆盖面（分区数据源）。
# ---------------------------------------------------------------------------


def test_lunar_public_anchors() -> None:
    assert lunar_new_year(2026) == date(2026, 2, 17)  # 2026 春节（公开历书）
    assert lunar_new_year(2025) == date(2025, 1, 29)
    lunar_mid_autumn = lunar_from_gregorian(2026, 9, 25)
    # 2026 中秋=公历 9 月 25 日（八月十五），公开历书可核。
    assert (lunar_mid_autumn.month, lunar_mid_autumn.day) == (8, 15)
    assert lunar_mid_autumn.year_ganzhi == "丙午" and lunar_mid_autumn.zodiac == "马"
    assert lunar_leap_month(2014) == 9  #  famously rare 闰九月
    assert lunar_leap_month(2025) == 6  # 2025 闰六月
    assert lunar_leap_month(2026) == 0  # 该年无闰


def test_hijri_eid_anchored_via_tabular_calendar() -> None:
    """Kuwaiti 历表口径的宰牲节（1446 年 12 月 10 日 = 公历 2025-06-07）。

    历表面向观测有 ±1 天出入——本锚钉的是**历表自身**的公开推定值
    （模块读出恒带"约"字），不是月相实测日。
    """
    assert hijri_from_gregorian(2025, 6, 7) == (1446, 12, 10)


def test_rich_calendar_lines_covers_all_five_required_calendars() -> None:
    """第 10 项分区的数据源面：公历/农历/伊斯兰历/藏历/东正教历一样不缺。"""
    lines = rich_calendar_lines(date(2026, 9, 25))
    text = "\n".join(lines)
    for label in ("公历2026年9月25日 星期五", "农历丙午马年八月十五", "伊斯兰历约", "藏历", "东正教历"):
        assert label in text, label
    assert "饶迥第17轮第40年" in text
    assert "儒略历2026-09-12" in text
    assert lines == rich_calendar_lines(date(2026, 9, 25)), "同一天的明细必须确定性一致"
    assert all("未知" not in line for line in lines), "缺的面是明说没源，不是标未知"


def test_out_of_support_window_raises_value_error() -> None:
    for fn in (
        lambda: lunar_from_gregorian(1900, 1, 1),
        lambda: rich_calendar_lines(date(1900, 1, 1)),
        lambda: orthodox_pascha_gregorian(2100),
    ):
        with pytest.raises(ValueError):
            fn()

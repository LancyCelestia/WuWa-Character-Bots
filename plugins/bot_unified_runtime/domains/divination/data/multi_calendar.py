"""多历法换算（历史上的今天·vis3 用户指令，2026-09-13）。

口径（用户逐条裁定）：
- 公历统一（主日期：xx月xx日）；
- 中国：黄帝纪元（公元年 + 2697，民间通行口径）；
- 藏传佛教语境：佛历（南传佛历口径，公元年 + 543）；
- 伊斯兰教地区：伊斯兰历（Hijri，tabular civil 算法，天文观测或有 ±1 天出入，
  历表用途足够；标注"约"）；
- 日本：和历年号（令和/平成/昭和硬编码表，更早年号缺省不显示）；
- 俄罗斯等东正教地区：拜占庭君士坦丁堡纪年 Anno Mundi（9 月 1 日换年）。

全部纯函数确定性换算，不联网不造数；旧年份缺年号表时该项省略。
"""

from __future__ import annotations

from datetime import date

_JAPAN_ERAS: tuple[tuple[date, str], ...] = (
    (date(2019, 5, 1), "令和"),
    (date(1989, 1, 8), "平成"),
    (date(1926, 12, 25), "昭和"),
)


def gregorian_to_jdn(year: int, month: int, day: int) -> int:
    """公历 → 儒略日数（Fliegel & Van Flandern 公式）。"""
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


def hijri_from_gregorian(year: int, month: int, day: int) -> tuple[int, int, int]:
    """公历 → 伊斯兰历（tabular civil，Kuwaiti 算法）。返回 (年, 月, 日)。"""
    jdn = gregorian_to_jdn(year, month, day)
    l0 = jdn - 1948440 + 10632
    n = (l0 - 1) // 10631
    l1 = l0 - 10631 * n + 354
    j = (
        (10985 - l1) // 5316
    ) * (50 * l1 // 17719) + (l1 // 5670) * (43 * l1 // 15238)
    l2 = (
        l1
        - (30 - j) // 15 * (17719 * j // 50)
        - j // 16 * (15238 * j // 43)
        + 29
    )
    month_h = (24 * l2) // 709
    day_h = l2 - (709 * month_h) // 24
    year_h = 30 * n + j - 30
    return year_h, month_h, day_h


def japan_era(year: int, month: int, day: int) -> str:
    """公历 → 日本和历（年号 + 年数）；年号表覆盖不到的年份返回空串。"""
    target = date(year, month, day)
    for start, era in _JAPAN_ERAS:
        if target >= start:
            era_year = target.year - start.year + 1
            return f"日本{era}{era_year}年"
    return ""


def byzantine_year(year: int, month: int, day: int) -> int:
    """拜占庭 Anno Mundi：纪年从 9 月 1 日起算（ crear世界创世纪年）。"""
    return year + 5509 if month >= 9 else year + 5508


def multi_calendar_line(today: date | None = None) -> str:
    """一行多历法摘要：公历主日期 + 各纪年；缺表项自动省略。"""
    today = today or date.today()  # noqa: DTZ011 - 历史卡按本地日历日期，有意 naive。
    year_h, month_h, day_h = hijri_from_gregorian(today.year, today.month, today.day)
    parts = [
        f"公历{today.month}月{today.day}日",
        f"黄帝纪元{today.year + 2697}年",
        f"佛历{today.year + 543}年",
        f"伊斯兰历约{year_h}年{month_h}月{day_h}日",
    ]
    era_text = japan_era(today.year, today.month, today.day)
    if era_text:
        parts.append(era_text)
    parts.append(f"拜占庭历{byzantine_year(today.year, today.month, today.day)}年")
    return " · ".join(parts)

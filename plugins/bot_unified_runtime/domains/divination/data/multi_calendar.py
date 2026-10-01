"""多历法换算（vis3 2026-09-13 用户指令；2026-09-26「bot 要准确知道自己身处何年何月」扩面）。

口径（用户逐条裁定 + 本波天文实算面）：
- 公历统一（主日期：xx月xx日）；
- 中国：黄帝纪元（公元年 + 2697，民间通行口径）；农历（干支纪年 + 生肖 + 月名 + 日名，
  由朔望与中气实算，见 :func:`lunar_from_gregorian`）；
- 上座部/南传佛教地区：佛历（**南传**佛历口径，公元年 + 543）——旧版此处误标为
  「藏传佛教语境」，2026-09-26 就地更正：+543 不是藏历，藏历另见 :func:`tibetan_year_lines`；
- 藏传佛教：只给**饶迥（Rabjung，1027 年起算）60 年周期**与历年名（五行 + 阴阳 + 生肖），
  **不给藏历月/日**——那需要时轮历（Kalachakra）历表与逐年颁定，本仓无源，绝不编造；
- 伊斯兰教地区：伊斯兰历（Hijri，tabular civil 算法，天文观测或有 ±1 天出入，
  历表用途足够；标注"约"）；
- 日本：和历年号（令和/平成/昭和硬编码表，更早年号缺省不显示）；
- 东正教：两制并列——**儒略历**日期换算（含与公历的实际天数差）、**修订儒略历**说明，
  以及该年的复活节（旧历 computus 与修订儒略历/公历 computus 各算一次），便于回答
  "某教会走哪条历法、那年复活节是哪天"；除此之外不给出任何瞻礼日；
- 俄罗斯等东正教地区纪年：拜占庭君士坦丁堡纪年 Anno Mundi（9 月 1 日换年）。

全部纯函数确定性换算，不联网、不查历表、不造数。天文面里太阳黄经与节气交节时刻的真身
在 ``domains/divination/data/ganzhi.py``，本件只调用、不留第二副本；朔（新月）时刻本件
按 Meeus ch.49 截断级数自算（全仓此前没有朔望月真身）。
支持区间 1901-2099（节气面 1900-2100 与历差恒定段求交），超出一律抛 ``ValueError``。
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass
from datetime import date, datetime

from plugins.bot_unified_runtime.domains.divination.data.ganzhi import (
    BRANCHES,
    CST,
    STEMS,
    TERM_NAMES,
    ZODIAC,
    _delta_t_seconds,
    _jd_to_datetime,
    solar_term_beijing,
)

_MIN_SUPPORTED_YEAR = 1901
_MAX_SUPPORTED_YEAR = 2099

_JAPAN_ERAS: tuple[tuple[date, str], ...] = (
    (date(2019, 5, 1), "令和"),
    (date(1989, 1, 8), "平成"),
    (date(1926, 12, 25), "昭和"),
)

# 农历月名（正月…冬月…腊月）与日名（初一…三十）：纯字面标签，非天文数据。
_LUNAR_MONTH_NAMES: tuple[str, ...] = (
    "正月", "二月", "三月", "四月", "五月", "六月",
    "七月", "八月", "九月", "十月", "冬月", "腊月",
)
_LUNAR_DAY_NAMES: tuple[str, ...] = (
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十",
)
_WEEKDAY_NAMES: tuple[str, ...] = (
    "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日",
)

# 「中气」在 ``TERM_NAMES``（立春起算）里的下标 = 奇数位：雨水/春分/谷雨/小满/夏至/
# 大暑/处暑/秋分/霜降/小雪/冬至/大寒，共 12 枚——它们定农历月序（``_month_of_zhongqi``）。
_ZHONGQI_INDICES: tuple[int, ...] = tuple(range(1, 24, 2))
_TERM_WINTER_SOLSTICE = TERM_NAMES.index("冬至")
_TERM_RAIN_WATER = TERM_NAMES.index("雨水")

# 藏历饶迥纪元元年（公历 1027，该年干支丁卯 = 阴火兔，即第一轮第一年）。
_RABJUNG_EPOCH_YEAR = 1027
_TIBETAN_ELEMENTS: tuple[str, ...] = ("木", "火", "土", "金", "水")

# 朔序 k=0 的北京日期（2000-01-06 18:19 UT = 01-07 02:19 北京）——只作估算种子，
# 真值由 ``new_moon_beijing_date`` 现算，估不准会被小步校正吸收。
_NEW_MOON_EPOCH_ORDINAL = date(2000, 1, 7).toordinal()


# ---------------------------------------------------------------------------
# 日数与历法换算（公历 / 儒略历 / 伊斯兰历 / 和历 / 拜占庭）。
# ---------------------------------------------------------------------------


def gregorian_to_jdn(year: int, month: int, day: int) -> int:
    """公历 → 儒略日数（Fliegel & Van Flandern 公式）。"""
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


def _jdn_to_gregorian(jdn: int) -> date:
    """儒略日数 → 公历日期（Fliegel & Van Flandern 反算）。"""
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - (146097 * b) // 4
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    return date(
        100 * b + d - 4800 + m // 10,
        m + 3 - 12 * (m // 10),
        e - (153 * m + 2) // 5 + 1,
    )


def julian_to_jdn(year: int, month: int, day: int) -> int:
    """儒略历 → 儒略日数（与 ``gregorian_to_jdn`` 同构，只少格里高利改正项）。"""
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return day + (153 * m + 2) // 5 + 365 * y + y // 4 - 32083


def jdn_to_julian(jdn: int) -> date:
    """儒略日数 → 儒略历的 (年, 月, 日) 标签。

    ⚠ 返回值只是「把儒略历的年月日装进 ``date`` 这个外推格里高利历容器」，
    拿它再做日期算术必错——要对齐「同一天」请一律走 JDN。
    """
    b = jdn + 32082
    c = (4 * b + 3) // 1461
    d = b - (1461 * c) // 4
    e = (5 * d + 2) // 153
    return date(
        c - 4800 + e // 10,
        e + 3 - 12 * (e // 10),
        d - (153 * e + 2) // 5 + 1,
    )


def julian_from_gregorian(year: int, month: int, day: int) -> date:
    """公历某一天的「同一天」在儒略历里的年月日（经同一 JDN 对接）。"""
    return jdn_to_julian(gregorian_to_jdn(year, month, day))


def julian_gregorian_offset(year: int, month: int, day: int) -> int:
    """同一「今天」的公历日期标签与儒略历日期标签相差几天（公历侧更大）。

    口径是**同一时刻比标签**（东正教圣诞 儒略历 12-25 = 公历 1-7 就是这里的 13）。
    恒定段：公历 1900-03-13 至 2100-03-14 为 13 天，此前 12 天、此后 14 天
    （1900/2100 两年格里高利历无 2/29、儒略历有）。
    """
    jdn = gregorian_to_jdn(year, month, day)
    return _jdn_to_gregorian(jdn).toordinal() - jdn_to_julian(jdn).toordinal()


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


# ---------------------------------------------------------------------------
# 天文面：朔（新月）与中气 → 农历。
# ---------------------------------------------------------------------------


def _check_supported_year(year: int, what: str) -> None:
    if not _MIN_SUPPORTED_YEAR <= year <= _MAX_SUPPORTED_YEAR:
        raise ValueError(
            f"{what}只支持 {_MIN_SUPPORTED_YEAR}-{_MAX_SUPPORTED_YEAR} 年，收到 {year}"
            "（超出节气与历差已验证区间，宁可不给也不外推）"
        )


def _new_moon_jde(k: int) -> float:
    """第 ``k`` 次朔（新月）的 JDE（力学时 TT；Meeus《Astronomical Algorithms》ch.49）。

    截断口径：只保留系数绝对值 ≥ 0.002 天（≈2.9 分钟）的七项周期改正，被舍弃的更余项
    合计 < 0.002 天；ΔT 用 ``ganzhi._delta_t_seconds`` 的锚点插值（同样分钟级）。
    净精度：朔时刻 ±4 分钟以内——只有当合朔恰好落在北京时间子夜前后几分钟时，
    「初一是哪天」才可能判错一天（历表/娱乐级够用，严肃历书以紫台历为准）。
    """
    t = k / 1236.85
    jde = (
        2451550.09766
        + 29.530588861 * k
        + 0.2158910 * t * t
        - 0.00132702 * t**3
        + 0.0000001533 * t**4
    )
    eccentricity = 1.0 - 0.002516 * t - 0.0000074 * t * t
    sun_anomaly = math.radians((2.5534 + 29.10535670 * k - 0.0000011 * t * t) % 360.0)
    moon_anomaly = math.radians(
        (201.5643 + 385.81693528 * k + 0.0107582 * t * t + 0.00001238 * t**3) % 360.0
    )
    latitude = math.radians((163.3373 + 390.67050284 * k - 0.0016118 * t * t) % 360.0)
    correction = (
        -0.40720 * math.sin(moon_anomaly)
        + 0.17241 * eccentricity * math.sin(sun_anomaly)
        + 0.01608 * math.sin(2 * moon_anomaly)
        + 0.01039 * math.sin(2 * latitude)
        + 0.00739 * eccentricity * math.sin(moon_anomaly - sun_anomaly)
        - 0.00514 * eccentricity * math.sin(moon_anomaly + sun_anomaly)
        + 0.00208 * eccentricity * eccentricity * math.sin(2 * sun_anomaly)
    )
    return jde + correction


@functools.lru_cache(maxsize=8192)
def new_moon_beijing(k: int) -> datetime:
    """第 ``k`` 次朔的**北京时间**时刻（aware，东八区）。``k=0`` ≈ 2000-01-06。"""
    jde_tt = _new_moon_jde(k)
    # JDE 是力学时（TT）；换算世界时要减 ΔT。年份由 k 反推（每朔 29.53 日）。
    approximate_year = 2000.0 + (k * 29.530588861) / 365.25
    universal_jd = jde_tt - _delta_t_seconds(approximate_year) / 86400.0
    return _jd_to_datetime(universal_jd).astimezone(CST)


@functools.lru_cache(maxsize=8192)
def new_moon_beijing_date(k: int) -> date:
    """第 ``k`` 次朔所在的北京日期＝该朔望月的「初一」。"""
    return new_moon_beijing(k).date()


def _lunation_index_containing_day(target: date) -> int:
    """「初一日期区间」包含 ``target`` 的那个朔望月的朔序 ``k``。

    历法是**按日**定的，不是按瞬时：合朔落在哪天，哪天就是初一。故这里必须用
    北京日期做包含判定，不能用瞬时比较——2014 年就是活例：冬至在 12-22 07:03、
    合朔在 12-22 14:49，按瞬时会把冬至算进上一个朔望月，闰九月整个消失、
    冬月也错一个月（本函数改法即由该案例逼出，见 tests/test_multi_calendar.py）。
    """
    estimate = (target.toordinal() - _NEW_MOON_EPOCH_ORDINAL) / 29.530588861
    k = math.floor(estimate)
    while new_moon_beijing_date(k) > target:
        k -= 1
    while new_moon_beijing_date(k + 1) <= target:
        k += 1
    return k


@functools.lru_cache(maxsize=1024)
def _zhongqi_window(ground_year: int) -> tuple[tuple[int, datetime], ...]:
    """公历 ``ground_year`` 前后各一年的 12 枚中气时刻（北京时间，按时刻升序）。

    只调用 :func:`ganzhi.solar_term_beijing`（太阳黄经真身），本件零副本。
    每项是 ``(农历月序, 交节时刻)``：冬至→11、大寒→12、雨水→1、春分→2……。
    """
    entries: list[tuple[int, datetime]] = []
    for year in (ground_year - 1, ground_year, ground_year + 1):
        # 越界由 solar_term_beijing 自己的 1900-2100 闸拦下（抛 ValueError），
        # 这里不再叠第二把尺——本件的公开入口已按 1901-2099 自守。
        for index in _ZHONGQI_INDICES:
            entries.append((_month_of_zhongqi(index), solar_term_beijing(year, index)))
    entries.sort(key=lambda item: item[1])
    return tuple(entries)


def _month_of_zhongqi(term_index: int) -> int:
    """中气定农历月序：雨水→1、春分→2、……、冬至→11、大寒→12。"""
    return (term_index + 1) // 2


def _zhongqi_of_term_index(term_index: int) -> str:
    return TERM_NAMES[term_index]


@dataclass(frozen=True)
class LunarMonth:
    """一个农历月（按北京日期区间定界；含闰月标记与该月的中气名）。"""

    start: date  # 初一（含）
    end: date  # 次月初一（不含）
    number: int  # 1-12（11=冬月/子月，12=腊月）
    is_leap: bool
    lunar_year: int  # 该月所属农历纪年
    zhongqi: str  # 该月所含中气名（闰月为空串）

    @property
    def month_label(self) -> str:
        return _month_label(self.number, self.is_leap)

    def contains(self, day: date) -> bool:
        return self.start <= day < self.end

    def day_of(self, day: date) -> int:
        """该日在这个农历月里是初几（1 起算）。"""
        return (day - self.start).days + 1


def _month_label(number: int, is_leap: bool) -> str:
    base = _LUNAR_MONTH_NAMES[number - 1]
    return ("闰" + base) if is_leap else base


@functools.lru_cache(maxsize=512)
def lunar_year_months(gregorian_anchor: int) -> tuple[LunarMonth, ...]:
    """以公历 ``gregorian_anchor`` 年冬至所在朔望月为起点的整段农历月序列。

    规则（时宪历通行口径，两条缺一不可）：

    1. **含冬至的那个朔望月 = 十一月**（子月锚定）；
    2. 相邻两个十一月之间若有 13 个朔望月，则**第一个不含中气的朔望月为闰月**，
       月序随其前一月；只有 12 个则不置闰。

    序列覆盖：十一月(锚定年) → 十二月 → 正月 → … → 十月，止于下一个冬至月之前。
    故本年的 11/12 月标 ``lunar_year = 锚定年``，其后的正月起标 ``锚定年 + 1``。
    """
    _check_supported_year(gregorian_anchor, "农历月序")
    solstice_now = solar_term_beijing(gregorian_anchor, _TERM_WINTER_SOLSTICE).date()
    solstice_next = solar_term_beijing(gregorian_anchor + 1, _TERM_WINTER_SOLSTICE).date()
    k0 = _lunation_index_containing_day(solstice_now)
    k1 = _lunation_index_containing_day(solstice_next)
    count = k1 - k0  # 12（无闰）或 13（有闰）
    starts = [new_moon_beijing_date(k0 + i) for i in range(count + 1)]
    spans = [(starts[i], starts[i + 1]) for i in range(count)]
    window = _zhongqi_window(gregorian_anchor)

    def zhongqi_name(span_start: date, span_end: date) -> str:
        for number, moment in window:
            if span_start <= moment.date() < span_end:
                return _zhongqi_of_term_index(2 * number - 1)
        return ""

    zhongqi_in_month = [zhongqi_name(start, end) for start, end in spans]
    leap_index = -1
    if count == 13:
        for i in range(1, count):  # 锚定月自身含冬至，不参与「无中气」判定
            if not zhongqi_in_month[i]:
                leap_index = i
                break
    months: list[LunarMonth] = []
    number = 11
    for i, (span_start, span_end) in enumerate(spans):
        if i == 0:
            this_number, is_leap = 11, False
        elif i == leap_index:
            this_number, is_leap = number, True  # 闰月沿用前一月月序
        else:
            number = number % 12 + 1
            this_number, is_leap = number, False
        months.append(
            LunarMonth(
                start=span_start,
                end=span_end,
                number=this_number,
                is_leap=is_leap,
                lunar_year=(
                    gregorian_anchor if this_number >= 11 else gregorian_anchor + 1
                ),
                zhongqi=zhongqi_in_month[i],
            )
        )
    return tuple(months)


@dataclass(frozen=True)
class LunarDate:
    """农历日期：纪年干支/生肖 + 月（含闰标记）+ 日。"""

    year: int  # 农历纪年（正月初一所在公历年）
    month: int  # 1-12
    day: int  # 1-30
    is_leap_month: bool
    year_ganzhi: str
    zodiac: str
    month_name: str
    day_name: str

    @property
    def month_label(self) -> str:
        return _month_label(self.month, self.is_leap_month)


def ganzhi_of_year(year: int) -> tuple[str, str]:
    """干支纪年（1984 = 甲子基准）：返回 ``(干支, 生肖)``。

    干支/生肖表真身在 ``ganzhi``（STEMS/BRANCHES/ZODIAC），此处只算偏移、不抄表。
    """
    stem_index = (year - 1984) % len(STEMS)
    branch_index = (year - 1984) % len(BRANCHES)
    return STEMS[stem_index] + BRANCHES[branch_index], ZODIAC[branch_index]


def lunar_from_gregorian(year: int, month: int, day: int) -> LunarDate:
    """公历 → 农历（实算：朔定月界、中气定月序、冬至定子月锚）。支持 1901-2099。"""
    _check_supported_year(year, "农历换算")
    target = date(year, month, day)
    for anchor in (year - 1, year):
        for item in lunar_year_months(anchor):
            if item.contains(target):
                ganzhi, zodiac = ganzhi_of_year(item.lunar_year)
                return LunarDate(
                    year=item.lunar_year,
                    month=item.number,
                    day=item.day_of(target),
                    is_leap_month=item.is_leap,
                    year_ganzhi=ganzhi,
                    zodiac=zodiac,
                    month_name=item.month_label,
                    day_name=_LUNAR_DAY_NAMES[item.day_of(target) - 1],
                )
    raise ValueError(f"农历换算未命中任何月份区间（{year}-{month:02d}-{day:02d}）")


def lunar_new_year(year: int) -> date:
    """农历 ``year`` 年的正月初一（公历日期）＝该年春节。

    定法即「含雨水的朔望月为正月」的正月锚（雨水属中气、定月序 1）。
    """
    _check_supported_year(year, "春节")
    rain_water = solar_term_beijing(year, _TERM_RAIN_WATER).date()
    return new_moon_beijing_date(_lunation_index_containing_day(rain_water))


def lunar_leap_month(lunar_year: int) -> int:
    """农历 ``lunar_year`` 年的闰月月序（1-12），该年无闰则 0。

    闰月可能落在两个锚定段里（闰正…十月在「上年冬至」段、闰十一/十二月在「本年冬至」段），
    故两段都查——只查一段会在 2033 型年份漏判。
    """
    _check_supported_year(lunar_year, "闰月")
    found: list[int] = []
    for anchor in (lunar_year - 1, lunar_year):
        found += [
            item.number for item in lunar_year_months(anchor) if item.is_leap and item.lunar_year == lunar_year
        ]
    if not found:
        return 0
    if len(set(found)) > 1:
        raise ValueError(f"农历 {lunar_year} 年算出多个闰月月序 {sorted(set(found))}，推算已失真")
    return found[0]


def solar_term_on(year: int, month: int, day: int) -> str:
    """该日（按北京时间交节）所的节气名；非节气日返回空串。"""
    _check_supported_year(year, "节气")
    target = date(year, month, day)
    return next((name for name, when in solar_terms_of_year(year) if when == target), "")


@functools.lru_cache(maxsize=512)
def solar_terms_of_year(year: int) -> tuple[tuple[str, date], ...]:
    """公历 ``year`` 年二十四节气：(节气名, 北京时间交节日期)，**按日期升序**。

    注意 ``TERM_NAMES`` 是立春起算的历序，不等于日期序（小寒/大寒排在历序末尾、
    却在公历 1 月），故这里排序——调用方拿到的就是时间线，可直接取前后邻居。
    """
    _check_supported_year(year, "节气")
    entries = [
        (TERM_NAMES[index], solar_term_beijing(year, index).date()) for index in range(24)
    ]
    return tuple(sorted(entries, key=lambda item: item[1]))


def solar_term_neighbours(
    year: int, month: int, day: int
) -> tuple[str, date, str, date]:
    """该日前后最近的两个节气：(上一节气名, 日期, 下一节气名, 日期)。

    任一侧跨年就落到支持区间之外时（1901 头、2099 尾），该侧返回空名 +
    哨兵日期，由读出面自行省略——不拿相邻年份硬凑。
    """
    _check_supported_year(year, "节气")
    target = date(year, month, day)
    series = list(solar_terms_of_year(year))
    for neighbour in (year - 1, year + 1):
        if _MIN_SUPPORTED_YEAR <= neighbour <= _MAX_SUPPORTED_YEAR:
            series += list(solar_terms_of_year(neighbour))
    previous = [(name, when) for name, when in series if when <= target]
    following = [(name, when) for name, when in series if when > target]
    prev_name, prev_when = previous[-1] if previous else ("", date.min)
    next_name, next_when = following[0] if following else ("", date.max)
    return prev_name, prev_when, next_name, next_when


# ---------------------------------------------------------------------------
# 藏历：饶迥 60 年周期（只到「年」；月/日无历表故不推算）。
# ---------------------------------------------------------------------------


def rabjung_year(gregorian_year: int) -> tuple[int, int]:
    """藏历饶迥（Rabjung）周期：返回 ``(第几轮, 轮内第几年)``，元年 = 公历 1027。"""
    delta = gregorian_year - _RABJUNG_EPOCH_YEAR
    if delta < 0:
        raise ValueError(f"饶迥以 1027 年为元年，收到 {gregorian_year}")
    return delta // 60 + 1, delta % 60 + 1


def tibetan_year_name(gregorian_year: int) -> str:
    """藏历历年名：阴阳 + 五行 + 生肖（与汉地干支同源，只换表述）。

    五行由天干两两一组推得（甲乙木、丙丁火、戊己土、庚辛金、壬癸水），阴阳取天干奇偶；
    生肖沿用 ``ganzhi.ZODIAC``，仅按藏历习惯把「鸡」写作「鸟」。
    """
    ganzhi, zodiac = ganzhi_of_year(gregorian_year)
    stem_index = STEMS.index(ganzhi[0])
    element = _TIBETAN_ELEMENTS[stem_index // 2]
    polarity = "阳" if stem_index % 2 == 0 else "阴"
    animal = "鸟" if zodiac == "鸡" else zodiac
    return f"{polarity}{element}{animal}年"


def tibetan_year_lines(gregorian_year: int) -> list[str]:
    """藏历面（诚实边界见模块 docstring：不给月/日、不给洛萨日期）。"""
    cycle, year_in_cycle = rabjung_year(gregorian_year)
    return [
        (
            f"藏历：饶迥第{cycle}轮第{year_in_cycle}年"
            f"（公历{gregorian_year} 对应 {tibetan_year_name(gregorian_year)}，"
            f"饶迥元年=公历{_RABJUNG_EPOCH_YEAR}）"
        ),
        (
            "藏历的月与日、以及藏历新年（洛萨）：需时轮历（Kalachakra）历表与逐年颁定，"
            "本仓无源故不推算——被问到就直说这一处没资料，别拿农历或公历日期顶替。"
        ),
    ]


# ---------------------------------------------------------------------------
# 东正教历：儒略历 / 修订儒略历 / 两条复活节 computus。
# ---------------------------------------------------------------------------


def _jdn_weekday(jdn: int) -> int:
    """儒略日数 → 星期（0=星期一 … 6=星期日；JDN 0 本身是星期一）。"""
    return jdn % 7


def orthodox_pascha_jdn(year: int) -> int:
    """旧历（儒略历 computus）复活节当天的 JDN。

    算法 = Metonic 金号推得的历期月（paschal term）+ 儒略历星期：
    ``epact = (11·(Y mod 19) + 13) mod 30``；教会满月 = 儒略历 3 月 21 日 + (29 − epact) 天；
    复活节 = 该日或其后的第一个星期日（满月恰落在星期日则不改期）。
    本实现对照 2019/2020/2021/2023/2024/2025/2026/2027/2028 九年公历实绩钉死（见测试）。
    """
    _check_supported_year(year, "东正教复活节")
    epact = (11 * (year % 19) + 13) % 30
    full_moon = julian_to_jdn(year, 3, 21) + (29 - epact)
    return full_moon + (6 - _jdn_weekday(full_moon)) % 7


def orthodox_pascha_julian(year: int) -> tuple[int, int]:
    """旧历 computus 复活节的**儒略历** (月, 日)。"""
    julian_day = jdn_to_julian(orthodox_pascha_jdn(year))
    return julian_day.month, julian_day.day


def orthodox_pascha_gregorian(year: int) -> date:
    """旧历（儒略历 computus）复活节换算成的公历日期。"""
    return _jdn_to_gregorian(orthodox_pascha_jdn(year))


def new_rite_pascha_gregorian(year: int) -> date:
    """修订儒略历（新历）教会的复活节＝公历 computus（Butcher/匿名公历算法）。

    修订儒略历的 Paschalion 与公历相同，故新历教会的复活节与西方同日；
    旧历教会通常晚 1-5 周（其教会满月与星期都按儒略历计）。
    """
    _check_supported_year(year, "修订儒略历复活节")
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def orthodox_calendar_lines(year: int, month: int, day: int) -> list[str]:
    """东正教历两制并行的读出行（不含任何编造的瞻礼日）。"""
    offset = julian_gregorian_offset(year, month, day)
    julian_day = julian_from_gregorian(year, month, day)
    old_julian = orthodox_pascha_julian(year)
    old_gregorian = orthodox_pascha_gregorian(year)
    new_pascha = new_rite_pascha_gregorian(year)
    return [
        (
            f"东正教历：公历{year}-{month:02d}-{day:02d} = 儒略历"
            f"{julian_day.year}-{julian_day.month:02d}-{julian_day.day:02d}（今日两历差{offset}天）"
        ),
        (
            "修订儒略历（密兰科维奇历）只改置闰规则：1900-2299 之间它与公历完全同日，"
            "差别只在「哪些教会用哪条历法」；两历（儒略历对公历）同日之差现在是 "
            f"{offset} 天（1900-03-13 起 13 天、2100-03-15 起 14 天）。"
        ),
        (
            f"{year} 年复活节：旧历 computus = 儒略历{old_julian[0]}月{old_julian[1]}日"
            f" = 公历{old_gregorian.month}月{old_gregorian.day}日；"
            f"修订儒略历/公历 computus = 公历{new_pascha.month}月{new_pascha.day}日。"
            "某个教会走哪条历法要按该教会自身规定回答，本件只给两条历法各自算出的日子。"
        ),
    ]


# ---------------------------------------------------------------------------
# 读出面。
# ---------------------------------------------------------------------------


def multi_calendar_line(today: date | None = None) -> str:
    """一行多历法摘要：公历主日期 + 各纪年；缺表项自动省略。

    输出面保持稳定——现役消费方只有一处（历史上的今天 ``format_history_text``）；
    需要逐项展开的场合走 :func:`rich_calendar_lines`，两者同一真身、零第二套换算。
    """
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


def rich_calendar_lines(today: date | None = None) -> list[str]:
    """多历法**明细**行（一行一个历法面；供需要逐项陈述的场合，如人格上下文）。

    与 :func:`multi_calendar_line` 的分工：那是一行摘要（历史卡口径，保持稳定），
    这是逐项展开（农历实算、二十四节气位置、藏历周期、东正教两制与两条复活节）。
    算不出的东西一律显式说没源，绝不补数。
    """
    today = today or date.today()  # noqa: DTZ011 - 与摘要行同口径（本地日历日期）。
    lunar = lunar_from_gregorian(today.year, today.month, today.day)
    year_h, month_h, day_h = hijri_from_gregorian(today.year, today.month, today.day)
    previous_name, previous_when, next_name, next_when = solar_term_neighbours(
        today.year, today.month, today.day
    )
    leap = lunar_leap_month(lunar.year)
    new_year = lunar_new_year(lunar.year)
    term_clauses = [
        (
            "干支纪年以农历正月初一换年"
            "（八字另有以立春换年的口径，两者口径不同、不可混用）"
        )
    ]
    if previous_name:
        term_clauses.append(
            f"节气位置：{previous_name}（{previous_when.month}月{previous_when.day}日）之后"
        )
    if next_name:
        term_clauses.append(
            f"下一节气 {next_name}（{next_when.month}月{next_when.day}日）"
        )
    lines = [
        (
            f"公历{today.year}年{today.month}月{today.day}日 {_WEEKDAY_NAMES[today.weekday()]}"
            f"（儒略日数 {gregorian_to_jdn(today.year, today.month, today.day)}）"
        ),
        (
            f"农历{lunar.year_ganzhi}{lunar.zodiac}年{lunar.month_name}{lunar.day_name}"
            f"（本月{'是闰月' if lunar.is_leap_month else '不闰'}；"
            f"该农历年的闰月：{'闰' + _LUNAR_MONTH_NAMES[leap - 1] if leap else '无'}；"
            f"该农历年正月初一＝公历{new_year.isoformat()}）"
        ),
        "；".join(term_clauses) + "。",
        (
            f"南传佛历{today.year + 543}年 · 黄帝纪元{today.year + 2697}年 · "
            f"拜占庭历{byzantine_year(today.year, today.month, today.day)}年"
        ),
        f"伊斯兰历约{year_h}年{month_h}月{day_h}日（Kuwaiti 历表推算，与月相观测可差 ±1 天）",
    ]
    era_text = japan_era(today.year, today.month, today.day)
    if era_text:
        lines.append(era_text)
    lines += tibetan_year_lines(today.year)
    lines += orthodox_calendar_lines(today.year, today.month, today.day)
    lines.append(
        "以上历法都是本机确定性推算：农历/节气/合朔是天文近似（分钟级，交节或合朔恰好"
        "落在子夜前后时可能差一天），伊斯兰历是历表推算而非实测月相。对外表述保留"
        "「约/推算」口径；被追问精度就把这个边界说出来，不含糊过去。"
    )
    return lines


def format_lunar_date(year: int, month: int, day: int) -> str:
    """公历日期 → 一行农历读出（``农历丙午年八月初二`` 形态）。"""
    lunar = lunar_from_gregorian(year, month, day)
    return f"农历{lunar.year_ganzhi}年{lunar.month_label}{lunar.day_name}"

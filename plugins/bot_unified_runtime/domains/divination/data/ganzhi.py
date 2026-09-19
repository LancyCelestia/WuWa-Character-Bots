"""干支历 / 八字排盘（纯计算，零第三方依赖，娱乐级精度）。

实现内容：
- 四柱（年/月/日/时柱）天干地支：给定一个时区感知的 ``datetime``。
- 五行统计（仅天干 + 地支本气字面计数）、纳音（30 组表）、日主、简评。

精度与约定（娱乐级，勿用于严肃命理）：
- 节气用低精度太阳黄经迭代（Meeus 25 章低阶公式 + 近似 ΔT），
  对 1900-2100 与香港天文台/万年历公布时刻误差实测在 ±10 分钟内；
  只有当节气交节时刻落在午夜前后约 10 分钟内时，节气当天归属才可能判错一天。
  （未采用「寿星通用公式」：该公式对若干年份存在整天级误差，
  例如立秋 2000/2008 公式给 8 月 8 日，实为 8 月 7 日。）
- 年柱以立春交节时刻为界；月柱以十二节（立春/惊蛰/清明/立夏/芒种/
  小暑/立秋/白露/寒露/立冬/大雪/小寒）交节时刻为界，月干用五虎遁。
- 日柱按本地（东八区）日期的儒略日数 (JDN) 计算：index = (JDN + 49) mod 60，
  经 1949-10-01 甲子、2000-01-01 戊午、1998-03-02 戊申、
  2024-02-04 戊戌、2026-09-10 丁亥 五个万年历锚点校验。
- 时辰：23:00-01:00 为子时。晚子时（23:00-24:00）采用
  「归本日日柱、时干按次日日干五鼠遁」的约定（次日子时干）。
- 不支持 1900 年以前 / 2100 年以后的输入（超出公式验证区间，抛 ValueError）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import pairwise

__all__ = [
    "BRANCHES",
    "NAYIN_TABLE",
    "STEMS",
    "BaziChart",
    "Pillar",
    "bazi_chart",
    "format_bazi_text",
    "solar_term_beijing",
]

# 东八区（中国标准时间）：干支日以本地午夜切换，节气按北京时间交节。
CST = timezone(timedelta(hours=8))

_MIN_YEAR = 1900
_MAX_YEAR = 2100

STEMS: tuple[str, ...] = ("甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸")
BRANCHES: tuple[str, ...] = (
    "子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥",
)
ZODIAC: tuple[str, ...] = (
    "鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪",
)
STEM_ELEMENTS: tuple[str, ...] = (
    "木", "木", "火", "火", "土", "土", "金", "金", "水", "水",
)
BRANCH_ELEMENTS: tuple[str, ...] = (
    "水", "土", "木", "木", "土", "火", "火", "土", "金", "金", "土", "水",
)
ALL_ELEMENTS: tuple[str, ...] = ("木", "火", "土", "金", "水")

# 纳音表：60 甲子按序两柱一组，共 30 音（组 i 覆盖甲子序 2i 与 2i+1）。
NAYIN_TABLE: tuple[str, ...] = (
    "海中金", "炉中火", "大林木", "路旁土", "剑锋金",
    "山头火", "涧下水", "城头土", "白蜡金", "杨柳木",
    "泉中水", "屋上土", "霹雳火", "松柏木", "长流水",
    "沙中金", "山下火", "平地木", "壁上土", "金箔金",
    "覆灯火", "天河水", "大驿土", "钗钏金", "桑柘木",
    "大溪水", "沙中土", "天上火", "石榴木", "大海水",
)

# 二十四节气：index k 对应太阳视黄经 (315 + 15k) mod 360，自立春起。
TERM_NAMES: tuple[str, ...] = (
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
    "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
    "立冬", "小雪", "大雪", "冬至", "小寒", "大寒",
)
# 十二节（月柱边界）：(二十四节气序, 月支序)（寅=2 起，子=0）。
_SECTION_TERMS: tuple[tuple[int, int], ...] = (
    (TERM_NAMES.index("立春"), 2),
    (TERM_NAMES.index("惊蛰"), 3),
    (TERM_NAMES.index("清明"), 4),
    (TERM_NAMES.index("立夏"), 5),
    (TERM_NAMES.index("芒种"), 6),
    (TERM_NAMES.index("小暑"), 7),
    (TERM_NAMES.index("立秋"), 8),
    (TERM_NAMES.index("白露"), 9),
    (TERM_NAMES.index("寒露"), 10),
    (TERM_NAMES.index("立冬"), 11),
    (TERM_NAMES.index("大雪"), 0),
    (TERM_NAMES.index("小寒"), 1),
)
# 五虎遁：年干 -> 寅月天干（甲己起丙、乙庚起戊、丙辛起庚、丁壬起壬、戊癸起甲）。
_MONTH_FIRST_STEM: tuple[int, ...] = (2, 4, 6, 8, 0, 2, 4, 6, 8, 0)
# 五鼠遁：日干 -> 子时天干（甲己起甲、乙庚起丙、丙辛起戊、丁壬起庚、戊癸起壬）。
_HOUR_FIRST_STEM: tuple[int, ...] = (0, 2, 4, 6, 8, 0, 2, 4, 6, 8)


# ---------------------------------------------------------------------------
# 天文近似：太阳视黄经 + 节气交节时刻（北京时间）。
# ---------------------------------------------------------------------------


def _delta_t_seconds(year: float) -> float:
    """ΔT = TT − UT1 的线性插值近似（锚点：1900/1950/2000/2050/2100）。

    娱乐级精度足够：对节气日判定的影响 ≤ 约 1 分钟。
    """
    anchors: tuple[tuple[int, float], ...] = (
        (1900, -2.7), (1950, 29.2), (2000, 63.8), (2050, 93.0), (2100, 203.0),
    )
    if year <= anchors[0][0]:
        return anchors[0][1]
    for (y0, d0), (y1, d1) in pairwise(anchors):
        if year <= y1:
            return d0 + (d1 - d0) * (year - y0) / (y1 - y0)
    return anchors[-1][1]


def _sun_apparent_longitude(jde: float) -> float:
    """太阳视黄经（度，0-360）：Meeus《Astronomical Algorithms》ch.25 低阶公式。"""
    t = (jde - 2451545.0) / 36525.0
    mean_lon = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    mean_anom = 357.52911 + 35999.05029 * t - 0.0001537 * t * t
    anom_rad = math.radians(mean_anom % 360.0)
    center = (
        (1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(anom_rad)
        + (0.019993 - 0.000101 * t) * math.sin(2 * anom_rad)
        + 0.000289 * math.sin(3 * anom_rad)
    )
    omega = math.radians((125.04 - 1934.136 * t) % 360.0)
    apparent = mean_lon + center - 0.00569 - 0.00478 * math.sin(omega)
    return apparent % 360.0


def _gregorian_to_jd(year: int, month: int, day: int, hour_utc: float = 0.0) -> float:
    """公历 → 儒略日（Meeus ch.7）。"""
    y, m = year, month
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return (
        math.floor(365.25 * (y + 4716))
        + math.floor(30.6001 * (m + 1))
        + day
        + b
        - 1524.5
        + hour_utc / 24.0
    )


def _jd_to_datetime(jd: float) -> datetime:
    """儒略日 → UTC ``datetime``（Meeus ch.7 反算）。"""
    jd += 0.5
    z = math.floor(jd)
    frac = jd - z
    if z < 2299161:
        a = z
    else:
        alpha = math.floor((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = math.floor((b - 122.1) / 365.25)
    d = math.floor(365.25 * c)
    e = math.floor((b - d) / 30.6001)
    day = int(b - d - math.floor(30.6001 * e))
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    hours = frac * 24.0
    hour = int(hours)
    minutes = (hours - hour) * 60.0
    minute = int(minutes)
    second = int((minutes - minute) * 60.0)
    return datetime(year, month, day, tzinfo=timezone.utc) + timedelta(
        hours=hour, minutes=minute, seconds=second
    )


def solar_term_beijing(year: int, term_index: int) -> datetime:
    """计算 ``year`` 年第 ``term_index`` 个节气的北京时间交节时刻。

    ``term_index`` 0=立春、2=惊蛰、12=立秋、14=白露……（见 ``TERM_NAMES``）。
    牛顿迭代太阳视黄经到目标角度；精度娱乐级（±10 分钟内，见模块 docstring）。
    """
    if not _MIN_YEAR <= year <= _MAX_YEAR:
        raise ValueError(f"节气计算仅支持 {_MIN_YEAR}-{_MAX_YEAR} 年，收到 {year}")
    target = (315.0 + 15.0 * term_index) % 360.0
    jan1 = _gregorian_to_jd(year, 1, 1)
    jd = jan1 + ((target - 282.0) % 360.0) / 0.9856
    for _ in range(40):
        diff = ((target - _sun_apparent_longitude(jd) + 180.0) % 360.0) - 180.0
        jd += diff / 0.9856
        if abs(diff) < 1e-7:
            break
    utc_jd = jd - _delta_t_seconds(float(year)) / 86400.0
    return _jd_to_datetime(utc_jd).astimezone(CST)


# ---------------------------------------------------------------------------
# 四柱计算。
# ---------------------------------------------------------------------------


def _local_jdn(dt: datetime) -> int:
    """本地日期（dt 的年月日）对应的儒略日数 JDN（整数，格里高利历）。"""
    a = (14 - dt.month) // 12
    y = dt.year + 4800 - a
    m = dt.month + 12 * a - 3
    return dt.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


def _ensure_cst(dt: datetime) -> datetime:
    """无时区信息时按东八区处理；有则转换到东八区。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=CST)
    return dt.astimezone(CST)


def _pair_index(stem: int, branch: int) -> int:
    """天干序 + 地支序 → 六十甲子序（闭式解，甲子=0）。

    满足 x ≡ stem (mod 10) 且 x ≡ branch (mod 12)；干支纪法里
    干支 parity 天然一致，(6*stem − 5*branch) mod 60 即为解。
    校验：己丑=25、戊午=54、丁亥=23、戊申=44。
    """
    return (6 * stem - 5 * branch) % 60


def _day_gz_index(dt: datetime) -> int:
    """日柱六十甲子序（甲子=0）。本地日期 JDN + 49 对 60 取模。"""
    return (_local_jdn(dt) + 49) % 60


def _year_gz_index(dt: datetime) -> int:
    """年柱六十甲子序：以立春交节时刻为界。"""
    boundary = solar_term_beijing(dt.year, TERM_NAMES.index("立春"))
    effective_year = dt.year if dt >= boundary else dt.year - 1
    return (effective_year - 4) % 60


def _month_gz_index(dt: datetime) -> tuple[int, int]:
    """月柱：返回 (月柱六十甲子序, 年柱六十甲子序)。

    以十二节交节时刻为界：候选边界取上年、当年、次年三组十二节中
    不晚于 ``dt`` 的最近一个；月干按年干五虎遁。年柱序复用同一套
    立春边界，保证立春交节前/后年柱月柱一致切换。
    """
    best_moment: datetime | None = None
    best_branch = -1
    for year in (dt.year - 1, dt.year, dt.year + 1):
        for term_index, branch in _SECTION_TERMS:
            moment = solar_term_beijing(year, term_index)
            if moment <= dt and (best_moment is None or moment > best_moment):
                best_moment = moment
                best_branch = branch
    if best_moment is None or best_branch < 0:  # pragma: no cover - 区间内不会发生
        raise ValueError("日期超出可计算的节气范围")
    year_index = _year_gz_index(dt)
    first_stem = _MONTH_FIRST_STEM[year_index % 10]
    stem = (first_stem + (best_branch - 2) % 12) % 10
    return _pair_index(stem, best_branch), year_index


def _hour_gz_index(dt: datetime, day_index: int) -> int:
    """时柱六十甲子序。

    23:00-24:00（晚子时）：日柱归本日，时干按次日日干五鼠遁（次日子时干）；
    00:00-01:00 归本日子时。01:00 起每两小时一支。
    """
    if dt.hour >= 23:
        branch = 0
        next_day_index = (day_index + 1) % 60
        stem = (_HOUR_FIRST_STEM[next_day_index % 10] + branch) % 10
        return _pair_index(stem, branch)
    branch = ((dt.hour + 1) // 2) % 12
    stem = (_HOUR_FIRST_STEM[day_index % 10] + branch) % 10
    return _pair_index(stem, branch)


@dataclass(frozen=True)
class Pillar:
    """一柱：天干/地支序 + 派生文本。"""

    stem_index: int
    branch_index: int

    @property
    def stem(self) -> str:
        return STEMS[self.stem_index]

    @property
    def branch(self) -> str:
        return BRANCHES[self.branch_index]

    @property
    def name(self) -> str:
        return f"{self.stem}{self.branch}"

    @property
    def stem_element(self) -> str:
        """天干五行（日主五行以此为源）。"""
        return STEM_ELEMENTS[self.stem_index]

    @property
    def zodiac(self) -> str:
        return ZODIAC[self.branch_index]

    @property
    def nayin(self) -> str:
        return NAYIN_TABLE[_pair_index(self.stem_index, self.branch_index) // 2]


@dataclass(frozen=True)
class BaziChart:
    """八字排盘结果：四柱 + 五行统计 + 日主 + 纳音 + 简评原料。"""

    year_pillar: Pillar
    month_pillar: Pillar
    day_pillar: Pillar
    hour_pillar: Pillar
    element_counts: dict[str, int]
    day_master: str
    day_master_element: str
    moment: datetime

    @property
    def pillars(self) -> tuple[Pillar, Pillar, Pillar, Pillar]:
        return (self.year_pillar, self.month_pillar, self.day_pillar, self.hour_pillar)

    @property
    def nayin(self) -> tuple[str, str, str, str]:
        return (
            self.year_pillar.nayin,
            self.month_pillar.nayin,
            self.day_pillar.nayin,
            self.hour_pillar.nayin,
        )


def bazi_chart(dt: datetime) -> BaziChart:
    """对给定时点排八字；naive datetime 视为东八区。"""
    moment = _ensure_cst(dt)
    if not _MIN_YEAR <= moment.year <= _MAX_YEAR:
        raise ValueError(f"仅支持 {_MIN_YEAR}-{_MAX_YEAR} 年的时点，收到 {moment.year}")

    day_index = _day_gz_index(moment)
    month_index, year_index = _month_gz_index(moment)
    hour_index = _hour_gz_index(moment, day_index)

    def _pillar(gz: int) -> Pillar:
        return Pillar(stem_index=gz % 10, branch_index=gz % 12)

    year_pillar = _pillar(year_index)
    month_pillar = _pillar(month_index)
    day_pillar = _pillar(day_index)
    hour_pillar = _pillar(hour_index)

    counts = {element: 0 for element in ALL_ELEMENTS}
    for pillar in (year_pillar, month_pillar, day_pillar, hour_pillar):
        counts[STEM_ELEMENTS[pillar.stem_index]] += 1
        counts[BRANCH_ELEMENTS[pillar.branch_index]] += 1

    day_master = day_pillar.stem
    day_master_element = STEM_ELEMENTS[day_pillar.stem_index]
    return BaziChart(
        year_pillar=year_pillar,
        month_pillar=month_pillar,
        day_pillar=day_pillar,
        hour_pillar=hour_pillar,
        element_counts=counts,
        day_master=day_master,
        day_master_element=day_master_element,
        moment=moment,
    )


# ---------------------------------------------------------------------------
# 文本渲染。
# ---------------------------------------------------------------------------


def _elements_summary(counts: dict[str, int]) -> str:
    return "　".join(f"{name}{count}" for name, count in counts.items())


def _brief_comment(chart: BaziChart) -> str:
    """依据五行字面计数生成一两句中性简评（娱乐向，不下断语）。"""
    counts = chart.element_counts
    missing = [name for name in ALL_ELEMENTS if counts[name] == 0]
    dominant = max(ALL_ELEMENTS, key=lambda name: counts[name])
    day_count = counts[chart.day_master_element]
    lines: list[str] = []
    if missing:
        lines.append(f"五行缺{'、'.join(missing)}，{dominant}偏旺。")
    else:
        lines.append(f"五行俱全，{dominant}气最盛。")
    if day_count == 0:
        lines.append(
            f"日主{chart.day_master}{chart.day_master_element}不得字面根气，凡事量力而行。"
        )
    elif day_count >= 3:
        lines.append(
            f"日主{chart.day_master}{chart.day_master_element}得令多助，主见强，注意刚柔相济。"
        )
    else:
        lines.append(
            f"日主{chart.day_master}{chart.day_master_element}平和持中，稳中求进即可。"
        )
    return "　".join(lines)


def format_bazi_text(chart: BaziChart) -> str:
    """把排盘渲染成聊天友好的一段中文文本。"""
    moment = chart.moment.strftime("%Y-%m-%d %H:%M")
    nayin = chart.nayin
    head = (
        f"八字排盘（{moment}，北京时间）\n"
        f"年柱 {chart.year_pillar.name}（{nayin[0]}）　生肖属{chart.year_pillar.zodiac}\n"
        f"月柱 {chart.month_pillar.name}（{nayin[1]}）\n"
        f"日柱 {chart.day_pillar.name}（{nayin[2]}）\n"
        f"时柱 {chart.hour_pillar.name}（{nayin[3]}）"
    )
    body = (
        f"五行：{_elements_summary(chart.element_counts)}\n"
        f"日主：{chart.day_master}{chart.day_master_element}"
    )
    comment = _brief_comment(chart)
    return f"{head}\n{body}\n{comment}\n（仅供娱乐，人生靠自己书写～）"

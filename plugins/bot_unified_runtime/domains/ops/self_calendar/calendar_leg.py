"""自我历法层：农历 / 伊斯兰历 / 藏历 / 东正教历的结构化取数口。

需求 10 要「bot 准确知道现在的农历、伊斯兰历、藏传佛教历、东正教历」。这四条
历法的**算法真身已经存在**：``domains/divination/data/multi_calendar.py``
（藏历饶迥与东正教两制已于 goal18 第 10 项 a 段补齐，见该件 docstring 与
``tests/test_multi_calendar.py``）。本件因此**只做装配**，零第二套换算，
也零第二套文案：凡真身自己已经成句的读出（含「无源故不推算」「按该教会自身
规定回答」这类诚实边界），一律取真身返回值原句，不在这重抄一遍。

本件补的是真身没有的两样东西：
1. 一个可一次调用取全的结构化快照（``CalendarSnapshot``），让「今天四历法各是
   什么」能被装配、能被测试钉死——真身是散在十几个原函数与两段长文本里的；
2. 「算不出来」这一态（真身在 1901-2099 之外抛 ``ValueError``）。装配面要的
   不是异常而是一句人话，所以这里把它转成 ``supported=False`` + 原因，
   越界/缺源时说明「不算」，绝不外推、绝不拿公历顶替。

口径：历法常数与天文量一个都不写在本件里（``tests/test_self_calendar.py`` 有
一把 AST 反副本锁扫这件事）。
失败：真身的 ``ValueError`` → 降级读出；其余异常不吞（那是真缺陷，该冒出去）。
配置：零配置键。日界口径由 ``moments.MomentSnapshot.calendar_day`` 决定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from plugins.bot_unified_runtime.domains.divination.data.multi_calendar import (
    LunarDate,
    format_lunar_date,
    hijri_from_gregorian,
    julian_from_gregorian,
    julian_gregorian_offset,
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

#: 「这一天算不出来」的固定起头。判据③要的「未探测」语义由此承担。
UNCOMPUTABLE = "未探测（超出可推算区间，不外推）"

#: 真身给不出的面（藏历月/日与洛萨）在快照里的统一取值。
_NO_SOURCE = "无历表源，不推算"


@dataclass(frozen=True)
class TibetanFace:
    """藏历面：饶迥周期 + 历年名。**月/日与洛萨明确无源**，故不建模。"""

    cycle: int
    year_in_cycle: int
    year_name: str
    month_day_available: bool  # 恒 False——真身自己写着「本仓无源故不推算」
    source_lines: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class OrthodoxFace:
    """东正教历面：同一天的儒略历标签 + 两历日差 + 该年两条复活节。"""

    julian_day: date
    offset_days: int
    pascha_old_rite: date
    pascha_new_rite: date
    source_lines: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class CalendarSnapshot:
    """某一天在四种历法下的对照快照（数值与文案全部由真身给出）。"""

    day: date
    supported: bool
    reason: str
    lunar: LunarDate | None
    lunar_leap_month_number: int
    lunar_new_year_day: date | None
    hijri: tuple[int, int, int] | None
    tibetan: TibetanFace | None
    orthodox: OrthodoxFace | None
    summary_line: str
    detail_lines: tuple[str, ...]

    @property
    def hijri_label(self) -> str:
        """伊斯兰历读出（恒带「约」：历表推算而非实测月相，与真身同口径）。"""
        if self.hijri is None:
            return UNCOMPUTABLE
        year, month, day = self.hijri
        return f"伊斯兰历约{year}年{month}月{day}日"

    @property
    def lunar_label(self) -> str:
        """农历读出——直接取真身的 ``format_lunar_date``，不在这拼第二套。"""
        if self.lunar is None:
            return UNCOMPUTABLE
        return format_lunar_date(self.day.year, self.day.month, self.day.day)


def build_calendar_snapshot(day: date) -> CalendarSnapshot:
    """把一天收成四历法快照；越界时返回「算不出来」而不是抛。

    口径：入参应当是**北京日界**那一天（``moments.MomentSnapshot.calendar_day``）
    ——真身的合朔与交节都按东八区日期判日，喂错日界整条农历差一天。
    失败：真身 ``ValueError``（1901-2099 之外）→ ``supported=False`` + 原文原因。
    """
    try:
        lunar = lunar_from_gregorian(day.year, day.month, day.day)
        cycle, year_in_cycle = rabjung_year(day.year)
        snapshot = CalendarSnapshot(
            day=day,
            supported=True,
            reason="",
            lunar=lunar,
            lunar_leap_month_number=lunar_leap_month(lunar.year),
            lunar_new_year_day=lunar_new_year(lunar.year),
            hijri=hijri_from_gregorian(day.year, day.month, day.day),
            tibetan=TibetanFace(
                cycle=cycle,
                year_in_cycle=year_in_cycle,
                year_name=tibetan_year_name(day.year),
                month_day_available=False,
                source_lines=tuple(tibetan_year_lines(day.year)),
            ),
            orthodox=OrthodoxFace(
                julian_day=julian_from_gregorian(day.year, day.month, day.day),
                offset_days=julian_gregorian_offset(day.year, day.month, day.day),
                pascha_old_rite=orthodox_pascha_gregorian(day.year),
                pascha_new_rite=new_rite_pascha_gregorian(day.year),
                source_lines=tuple(orthodox_calendar_lines(day.year, day.month, day.day)),
            ),
            summary_line=multi_calendar_line(day),
            detail_lines=tuple(rich_calendar_lines(day)),
        )
    except ValueError as error:
        return CalendarSnapshot(
            day=day,
            supported=False,
            reason=f"{UNCOMPUTABLE}：{error}",
            lunar=None,
            lunar_leap_month_number=0,
            lunar_new_year_day=None,
            hijri=None,
            tibetan=None,
            orthodox=None,
            summary_line="",
            detail_lines=(),
        )
    return snapshot


def calendar_compact_lines(snapshot: CalendarSnapshot) -> list[str]:
    """四历法紧凑行：一条历法一行，供分区/回答用；边界句取真身原句。

    口径：藏历与东正教那两行的**限制说明不是本件写的**，是真身
    ``tibetan_year_lines`` / ``orthodox_calendar_lines`` 自己的句子——
    真身改了措辞这里跟着改，不会出现两套口径。
    失败：算不出来的那一天，返回「未探测」两行，不返回半截数据。
    """
    if not snapshot.supported:
        return [
            f"历法面（{snapshot.day.isoformat()}）：{snapshot.reason}",
            "被问到就直说这一天在可推算区间之外，别拿邻近年份或公历日期顶替。",
        ]
    tibetan = snapshot.tibetan
    orthodox = snapshot.orthodox
    if tibetan is None or orthodox is None:  # 理论不可达：supported 时二者必构造
        return [f"历法面（{snapshot.day.isoformat()}）：{UNCOMPUTABLE}"]
    lines = [snapshot.lunar_label, snapshot.hijri_label]
    if tibetan.source_lines:
        lines.append(tibetan.source_lines[0])
        # 真身的第二行就是「月/日与洛萨无源」那句，原样带出，不重抄。
        lines.append(tibetan.source_lines[1])
    if orthodox.source_lines:
        lines.append(orthodox.source_lines[0])
        lines.append(orthodox.source_lines[-1])
    return lines


def tibetan_month_day_status(snapshot: CalendarSnapshot) -> str:
    """藏历月/日这一面的状态。

    口径：真身没有时轮历历表源 ⇒ 恒「无源」。若日后有人接进了真源并把
    ``month_day_available`` 翻成 True，这里必须改口——**不许继续念「无源」，
    也不许在本件里凭空报出一个藏历日期**，那句话要由给出真源的那一侧说。
    """
    if snapshot.tibetan is None:
        return UNCOMPUTABLE
    if snapshot.tibetan.month_day_available:
        return "已由历表源给出（本件不复述，取真身原句）"
    return _NO_SOURCE

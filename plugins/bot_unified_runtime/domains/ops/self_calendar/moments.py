"""自我时刻层：把「此刻」拆成 UTC / 配置时区 / 系统本地 / 北京日界四个口径。

需求 10（2026-09-26 goal18 波）「bot 要准确知道自己系统的日期与时间」的最小事实层。
既有装配（``character/temporal.py`` + ``chat.py`` 的【当前时间】分区）拿的是
``TemporalContext`` 里的**字符串**（``date_local``/``now_local``），由 provider 在
装配期一次性 ``datetime.now(zone)`` 得到——那既不可注入、也不区分「UTC 的今天」和
「本地的今天」，于是有本层要补的三个真实缺口：

1. **时刻可注入**：本层全部公开函数收一个 aware ``now``，测试能把时刻钉死；
   ``now=None`` 才回落系统钟。**模块导入期一律不取时刻**（否则测试不稳定）。
2. **日界分歧**：同一个 UTC 瞬间在 UTC 与东八区可以落在**不同日历日**
   （2026-02-16T16:30Z = 北京 2026-02-17 00:30），而农历/伊斯兰历/儒略历的「今天」
   是**按日**定的，取错一天整条历法全错。本层把这个分歧显式算出来并交给读出面。
3. **系统钟 vs 配置钟**：台账 #6——cron 与 ``.env`` 走的是系统本地时区，
   ``bot_timezone`` 却是另一枚配置；两者不在同一日时，bot 必须知道自己有两把钟。

口径：本件只负责「哪一年哪一月哪一日、几点、偏移多少」，**不做任何历法换算**
（历法真身唯一在 ``domains/divination/data/multi_calendar.py``，见 calendar_leg）。
失败：naive ``now`` 直接 ``ValueError``（绝不猜它是哪个时区）；坏时区名不抛，
标 ``timezone_recognized=False`` 并回落 UTC 口径——由读出面写明「未探测」。
配置：本件零配置键；``timezone_name`` 由调用方传 ``config.bot_timezone``，
不在这里再写一遍缺省值（缺省值真身 = ``config.py: bot_timezone``）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

# 北京历法日界口径的时区真身（``ganzhi.CST``，与 multi_calendar 同一枚常量）。
# 这里 import 而不是再 ``timezone(timedelta(hours=8))`` 拼一次，就是为了不留第二份。
from plugins.bot_unified_runtime.domains.divination.data.ganzhi import CST


def normalize_aware(moment: datetime, *, what: str = "时刻") -> datetime:
    """把「时刻」规范成 aware datetime；naive 一律拒绝。

    口径：本层唯一的「什么才算一个时刻」判据——naive 钟意味着调用方自己都不
    知道在哪个时区，猜成 UTC 会把日期算错一天（本层存在的理由正是别算错日子）。
    失败：抛 ``ValueError``，不返回兜底值。
    """
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(
            f"{what}必须是带时区的 aware datetime，收到的是 naive 钟：{moment!r}"
        )
    return moment


def to_utc(moment: datetime) -> datetime:
    """任一 aware 时刻 → UTC aware（同一瞬间，不重新解释墙钟）。"""
    return normalize_aware(moment).astimezone(timezone.utc)


#: 「所报时刻」与系统本地钟相差多少秒以内算**同一次取数**（超出即视为补投/回放的
#: 历史上下文，拿今天的系统钟去断言那天本地是几号当场就是假话）。
#: 数值真身原住在装配层 ``character/temporal.py`` 的同义私有常量；本包把它做成
#: 可选形参的缺省值，**两处并存是已知账**（S-T-SELFINFO-3 日志 §5 第 2 条），
#: 合并方向 = 装配层改借本包这一枚。装配层今天显式借用 temporal 那一枚数值，
#: 所以全仓仍然只有一份数字（见 ``tests/test_self_info_reaches_prompt.py`` 的
#: ``test_same_reading_window_constant_is_shared_not_copied``）。
SAME_READING_SECONDS = 600.0


def resolve_moments_from_context_text(
    *,
    date_local: str,
    now_local: str,
    timezone_name: str,
    system_now: datetime | None = None,
    same_reading_seconds: float = SAME_READING_SECONDS,
) -> MomentSnapshot | None:
    """从【当前时间】分区已有的两段墙钟**文本**还原一个瞬间，再交回 :func:`resolve_moments`。

    为什么要单独一枚：装配层手上的 ``TemporalContext`` 只有字符串
    （``date_local`` + 只到分的 ``now_local``），而四把钟对照需要一个 aware 瞬间。
    本包刻意**不在函数内部偷偷读钟**（理由同 :func:`resolve_moments`），所以
    「把墙钟文本变回瞬间」这一步必须有个家；它属于「哪一年哪一月哪一日、几点」
    这件事，正是本包的管辖面，不该在装配层里再散落一段字符串解析。
    ``system_now`` 的采纳窗口口径见 :data:`SAME_READING_SECONDS`：窗口外一律当
    没注入 ⇒ 系统钟那一面写「未探测」，而不是硬凑一个看起来对的日期。
    失败：日期/时刻文本不可解析、时区名为空或不可用 ⇒ 回 ``None``（不猜）。
    时区名**合法但本包认不出**的情况同样回 None：连墙钟属于哪个时区都不知道时，
    退化到 UTC 造出来的「UTC 时刻」是一个凭空发明的数。
    """
    if not str(timezone_name).strip():
        return None
    try:
        day = date.fromisoformat(str(date_local).strip())
        hour, minute = (int(part) for part in str(now_local).strip().split(":")[:2])
        moment = datetime(
            day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(timezone_name)
        )
    except Exception:  # noqa: BLE001 - 文本不可解析=没有这一刻，宁缺毋滥
        return None
    adopted: datetime | None = system_now
    if adopted is not None:
        try:
            adopted = normalize_aware(adopted, what="系统本地钟")
            if abs((adopted - moment).total_seconds()) > same_reading_seconds:
                adopted = None
        except ValueError:
            adopted = None
    return resolve_moments(moment, timezone_name=timezone_name, system_now=adopted)


def system_clock_now() -> datetime:
    """装配层专用：取一次系统本地钟（aware），与 ``datetime.now()`` 同一瞬间。

    口径：本层刻意**不在函数内部偷偷读钟**（见 :func:`resolve_moments` 的来历），
    生产装配就显式调这一枚，把结果连同 ``now`` 一起传进来；测试则自己造。
    失败：平台读不到本地钟时异常照抛——那是环境事实，不该被伪装成「未探测」。
    """
    return datetime.now().astimezone()


@dataclass(frozen=True)
class ZoneFace:
    """一个时区口径下的「今天与此刻」。"""

    name: str
    recognized: bool
    note: str
    instant: datetime
    day: date
    offset_label: str

    @property
    def wall_clock(self) -> str:
        """该口径下的墙钟时刻（只到秒，不重复日期）。"""
        return self.instant.strftime("%H:%M:%S")


@dataclass(frozen=True)
class MomentSnapshot:
    """同一个瞬间在四把钟下的读法。"""

    utc: ZoneFace
    local: ZoneFace
    beijing: ZoneFace
    system: ZoneFace | None
    same_day_everywhere: bool
    day_divergence_note: str
    system_source: str

    @property
    def calendar_day(self) -> date:
        """历法面应当取用的那一天：**北京日界**（multi_calendar 的天文口径如此定义）。

        口径：农历初一、节气交节日在真身里都是按东八区日期判定的，所以历法面必须
        跟着这把尺，不能跟着「配置时区的今天」——两者不同日时，跟错的那一侧会
        把整个农历日期差一天。
        """
        return self.beijing.day


def _zone_face(name: str, moment_utc: datetime, *, note: str = "") -> ZoneFace:
    """按 IANA 时区名造一面钟；名字认不出来就退化 UTC 并如实标注（不猜）。"""
    try:
        zone = ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        # 实测三种坏输入：`ZoneInfo("Not/AZone")`/`ZoneInfo("bogus")` 抛
        # ``ZoneInfoNotFoundError``（它是 KeyError 的子类，**不是** ValueError——
        # 首版按 ValueError catch 会当场漏穿）；`ZoneInfo("")` 抛 ValueError；
        # 系统 tz 库整体缺失时抛 OSError。一律同样降级，绝不让一行读出把对话带走。
        return ZoneFace(
            name=name,
            recognized=False,
            note=note or f"时区 {name or '(空)'} 未识别（未探测），按 UTC 口径报",
            instant=moment_utc,
            day=moment_utc.date(),
            offset_label="UTC+00:00",
        )
    local = moment_utc.astimezone(zone)
    offset = local.utcoffset()
    total = int(offset.total_seconds()) if offset is not None else 0
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total), 3600)
    return ZoneFace(
        name=str(zone),
        recognized=True,
        note=note,
        instant=local,
        day=local.date(),
        offset_label=f"UTC{sign}{hours:02d}:{minutes // 60:02d}",
    )


def _fixed_zone_face(
    label: str, zone: tzinfo, moment_utc: datetime, *, note: str = ""
) -> ZoneFace:
    """按现成 tzinfo（如 ``ganzhi.CST``）造一面钟。"""
    local = moment_utc.astimezone(zone)
    offset = local.utcoffset()
    total = int(offset.total_seconds()) if offset is not None else 0
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total), 3600)
    return ZoneFace(
        name=label,
        recognized=True,
        note=note,
        instant=local,
        day=local.date(),
        offset_label=f"UTC{sign}{hours:02d}:{minutes // 60:02d}",
    )


def resolve_moments(
    now: datetime | None = None,
    *,
    timezone_name: str = "",
    system_now: datetime | None = None,
) -> MomentSnapshot:
    """把「此刻」解析成 UTC / 配置时区 / 北京日界 / 系统本地 四面对照。

    口径：``now`` 是**一个瞬间**（aware 必填，naive 直接拒）；``timezone_name``
    应当由调用方传 ``config.bot_timezone``，传空 ⇒ 标未探测并退化 UTC。
    ``system_now`` 是系统本地钟的**同一次读数**：想让报告带上系统钟，装配层必须
    把它和 ``now`` 一起给。**本函数自己不偷偷去读系统钟**——首版写了「没注入就
    现读」，结果一旦 ``now`` 被钉住（测试、或补投历史消息），系统钟就取自现实
    的「现在」，跨日提示当场变成假话（2026-09-26 本席 smoke 实抓到）。
    失败：不抛（除 naive 时刻这一条硬拒）；任何一把钟拿不到就在该面上写清楚，
    读出面据此说「未探测」，绝不硬凑一个看起来对的日期。
    """
    moment_utc = to_utc(now if now is not None else datetime.now(timezone.utc))
    utc_face = _fixed_zone_face("UTC", timezone.utc, moment_utc)
    local_face = _zone_face(timezone_name, moment_utc)
    beijing_face = _fixed_zone_face(
        "东八区（历法日界口径）",
        CST,
        moment_utc,
        note="农历/节气/合朔在真身里按此日界取日",
    )
    system_face: ZoneFace | None = None
    source = "not-injected"
    if system_now is not None:
        probed = normalize_aware(system_now, what="系统本地钟")
        system_zone = probed.tzinfo
        if system_zone is not None:
            offset = probed.utcoffset()
            total = int(offset.total_seconds()) if offset is not None else 0
            sign = "+" if total >= 0 else "-"
            hours, minutes = divmod(abs(total), 3600)
            system_face = ZoneFace(
                name=f"系统本地时区（{time_name_or_placeholder(probed)}）",
                recognized=True,
                note="与所报时刻同一次取数的系统本地钟（台账 #6：它与 bot_timezone 是两把钟）",
                instant=probed,
                day=probed.date(),
                offset_label=f"UTC{sign}{hours:02d}:{minutes // 60:02d}",
            )
            source = "injected"

    days = {utc_face.day, local_face.day, beijing_face.day}
    if system_face is not None:
        days.add(system_face.day)
    same_day = len(days) == 1
    if same_day:
        divergence = ""
    else:
        parts = [
            f"UTC {utc_face.day.isoformat()}",
            f"配置时区 {local_face.day.isoformat()}",
            f"东八区 {beijing_face.day.isoformat()}",
        ]
        if system_face is not None:
            parts.append(f"系统本地 {system_face.day.isoformat()}")
        divergence = (
            "注意：这几把钟今天不是同一天（" + " / ".join(parts) + "）。"
            "历法面（农历/伊斯兰历/儒略历/藏历）按**东八区日界**取日，"
            "报时刻时请说明用的是哪把钟。"
        )
    return MomentSnapshot(
        utc=utc_face,
        local=local_face,
        beijing=beijing_face,
        system=system_face,
        same_day_everywhere=same_day,
        day_divergence_note=divergence,
        system_source=source,
    )


def time_name_or_placeholder(moment: datetime) -> str:
    """系统本地时区的缩写；拿不到就回占位短语，不硬编一个看起来像的。"""
    try:
        name = moment.strftime("%Z")
    except (ValueError, OSError):  # pragma: no cover - 极端平台
        return "未探测"
    return name or "未探测"

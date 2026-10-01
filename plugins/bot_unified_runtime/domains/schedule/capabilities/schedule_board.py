"""日程记录与智能代答能力（第 20 项，2026-09-26；挂 REMINDER 车道，notes 同型先例）。

她的三句话，逐句落码（设计权威 docs/design/schedule-board-and-proxy-reply.md）：

1. **日程记录与管理**——自然语言「明天8点有课」、显式命令「日程 …」、粘贴/发送
   课程表文本或图片，都进同一块日程板（复用 S11 V2.1 引擎：plan=board-<owner>，
   条目=task+rule→物化 occurrence，存储/时区/幂等/限额全部走引擎真身，零第二真身）。
   时间点解析唯一复用提醒域 ``reminders.parse_time_target``（本波把它的级联抽成
   共享件），**不写第二个时间解析器**。
2. **智能代答 + 隐私保护**——别人问「她在干嘛/主人在忙什么」，按分级表回答：
   隐私条目对任何非本人恒零呈现（连"没安排"都不说，防反向泄露）；公开条目
   普通用户档只给 **类别词+时刻**，trusted/管理员档给 **活动名+时刻**；
   **地点/健康/饮食/作息细节永不外给**（健康/饮食/作息/心理类别即便标公开，
   对非本人也只折叠成「有事情」）。分级表实现住 ``_project_answer`` 一个函数，
   隐私判定发生在**出站前**（字段白名单投影 + ``redact_local_secrets``），
   代答路径**零 LLM 调用**——不靠模型自觉。
3. **状态监测的信息来源硬边界**——条目的产生面只有三类：入站消息文本、
   她发来的课表文本/图片（识图 provider 只由她的这条消息触发）、日程库既有行。
   **本模块不 import 任何本机监控面**（无 psutil/subprocess/os.walk/设备/定位/
   日历软件读取），由 tests/test_schedule_board.py 的 AST 锁执法；
   她"睡了/醒了/吃了什么"只可能来自她亲口说过的内容。

装配口径：路由判定唯一函数 ``is_schedule_surface`` 同时供 ``is_reminder_command``
（路由腿）与 ``build_reminder_capability`` 分发（能力腿）引用——判据一处、两腿同源
（#45 三腿教义：路由判给谁、谁来接，不许各判一份）。升级独立 RouteKind 的配方在
席位报告 §F，非本能力生效前置（REMINDER 车道已过中央信封 orchestrated_command）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from hashlib import sha1
from typing import Any
from zoneinfo import ZoneInfo

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.ingest.message_context import (
    INTERNAL_MARKER_PATTERN,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    PLATFORM_QQ,
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_TRUSTED,
    platform_domain_of,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    PERSON_SCOPE_SEP,
    person_scope_key,
)
from plugins.bot_unified_runtime.domains.schedule.service.board_store import (
    BOARD_PLAN_PREFIX,
    build_board_service,
    build_board_store,
    purge_cutoff_epoch,
)
from plugins.bot_unified_runtime.domains.schedule.store.reminders import (
    _ABS_TIME_RE,
    _PERIOD_ONLY_RE,
    _REL_HALF_HOUR_RE,
    _REL_HOURS_RE,
    _REL_MINUTES_RE,
    configured_timezone,
    parse_time_target,
)

logger = logging.getLogger(__name__)

CAPABILITY_ID = "bot.reminder"  # 车道归属如实登记（notes 同型旧账，见模块 docstring）

# ---------------------------------------------------------------------------
# 常量与词表（触发词唯一真身；双向门按本模块字面提取，help 册须逐词对齐）
# ---------------------------------------------------------------------------

VIS_PUBLIC = "vis:public"
SRC_TAG_PREFIX = "src:"
LOC_TAG_PREFIX = "loc:"

_MAX_ACTIVITY_CHARS = 60
_MAX_ADD_CHARS = 60
_MAX_IMPORT_LINES = 60
_LIST_CAP = 20

#: duration=0 的条目（只说了开始时刻）在代答里按多长窗口算"进行中"（设计 §4 记载值）。
_ACTIVE_WINDOW_FALLBACK_MINUTES = 120

# 板面命令族（全部锚定整句或前缀+正文；裸「日程」给用法）。
_BOARD_BARE_RE = re.compile(
    r"^(?:日程|日程板|(?<![A-Za-z0-9])(?:richeng|schedule)(?![A-Za-z0-9]))\s*[…。.!！?？~～\s]*$",
    re.IGNORECASE,
)
_BOARD_LIST_RE = re.compile(
    r"^(?:日程列表|我的日程|看看日程|日程清单|日程表"
    r"|(?<![A-Za-z0-9])(?:richengliebiao|rclb)(?![A-Za-z0-9]))\s*[…。.!！?？~～\s]*$"
)
# 「日程 [加|记] <正文>」：正文必须以时间词面开头（含裸「8点」），防「日程 随便聊聊」
# 这类无时间正文被当成待解析条目（拿不准就回问，绝不猜点位）。
_BOARD_ADD_RE = re.compile(
    r"^日程(?:板)?\s*(?:加|记[录錄]?)?\s*[，,：:]?\s*"
    r"(?=(?:今天|明天|后天|今晚|今早|明晚|凌晨|早上|上午|中午|下午|傍晚|晚上"
    r"|周[一二三四五六日天]|星期[一二三四五六日天]|每[周个]|单周|双周|\d{1,2}\s*[点點:：]))"
    r"(.{2,})$"
)
_BOARD_DELETE_RE = re.compile(
    r"^(?:日程\s*删\s*(\d+)?|取消日程\s*(\d+)?"
    r"|(?<![A-Za-z0-9])shancheng\s*(\d+)(?![A-Za-z0-9]))\s*$"
)
_BOARD_DELETE_RULE_RE = re.compile(r"^日程\s*删课\s*(\d+)?\s*$")
_BOARD_VISIBILITY_RE = re.compile(
    r"^日程\s*(公开|设为公开|设成公开)\s*(\d+)?\s*$"
    r"|^日程\s*(隐私|设为隐私|设成隐私|不公开)\s*(\d+)?\s*$"
)
_BOARD_IMPORT_RE = re.compile(
    r"^(?:日程\s*导入|课表\s*导入|課表|课表|kebiao)(?:\s*[，,：:]?\s*([\s\S]+))?\s*$"
)

# 自然捕捉（开关关=整面不存在）：时间表达 + 第一人称活动词，短句、非疑问、无提醒信号。
_NATURAL_ACTIVITY_RE = re.compile(
    r"有课|上课|要上|要去|得去|要参加|有个?会|开会|考试|答辩|面试|要出发|出门|截止|要约"
)
_NATURAL_SIGNAL_EXCLUDE_RE = re.compile(r"提醒|叫我|記得叫|记得叫")
_NATURAL_MAX_CHARS = 48

# 代答问句族（开关关=整面不存在）。整句判据：≤24 字、剥 @ 与称呼前缀、句读收尾。
_QUESTION_HEAD_RE = re.compile(r"^(?:@[^\s，,]+|守岸人|机器人|岸宝)?[\s，,、.!！?？:：]*")
_QUESTION_CORE = (
    r"(?:在干(?:什么|啥|嘛)|在忙(?:什么|啥)?|干(?:什么|啥|嘛)|做(?:什么|啥)"
    r"|忙(?:什么|啥)|去哪(?:儿|里)?了?|出去(?:了)?(?:吗|么)|在(?:哪|哪儿|哪里)"
    r"|有何(?:安排|事)|有安排(?:吗|么)?"
    # G2(a) 未来窗代答（S-FIX-SCHED20B，简报点名三形）：有空吗/几点有事/什么时候忙。
    # 「有空吗」不带窗状语时按"现在有没有空"读（走 active_entries 现在腿），
    # 带窗或"什么时候/几点"形则走未来窗腿——判据唯一在 _window_days，别处不另判。
    r"|有空(?:吗|么)?|什么时候(?:忙|有事)|几点(?:有事|有空|忙))"
)
# 未来窗状语词面（G2(a)）：**单一串**，问句正则（_QUESTION_ADVERB）与取数解析
# （_window_days）共用同一份，禁第二真身。刻意不含「今天/今晚」——「今天」词面
# 已有中央单一来源真身（domains/core/temporal_words.TODAY_ADVERB_WORDS），
# 不在别处再落该词位的字面；问"今天"的让位现在腿/聊天，宁漏不误。
_QUESTION_WINDOW_TERMS = (
    r"下周末|本周末|这周末|周末"
    r"|下周(?:[一二三四五六日天])?|本周|这周"
    r"|明天|明日|(?<!大)后天"
    r"|(?:周|星期|礼拜)(?:[一二三四五六日天])"
    r"|\d{1,2}月\d{1,2}[日号]"
)
_QUESTION_ADVERB = r"(?:现在|这会儿|这时候|此刻|" + _QUESTION_WINDOW_TERMS + r")?"
# 头词分两半登记（G1）：第三人称=代答面（别人问「她/他/主人」），第一人称=自看面
# （她亲口问「我…」）。两半并进 _QUESTION_HEAD_WORDS 供问句正则命中，但只有第一人称
# 命中时才把取数收窄到会话所有者本人的板子（见 _handle_status_question + _is_first_person_question）。
# 第一人称词我/我的/本人/自己在简繁同形（无独立繁体字），故无第二份词表；刻意只用
# 简报点名的这四枚、不加「咱/俺」等方言面，尽量少给触发词单一来源棘轮添新词位。
_QUESTION_THIRD_PERSON_HEAD_WORDS = "她|他|主人"
_QUESTION_FIRST_PERSON_HEAD_WORDS = "我的|我|本人|自己"
_QUESTION_HEAD_WORDS = (
    f"{_QUESTION_FIRST_PERSON_HEAD_WORDS}|{_QUESTION_THIRD_PERSON_HEAD_WORDS}"
)
_QUESTION_RE = re.compile(
    rf"^(?:{_QUESTION_HEAD_WORDS})\s*{_QUESTION_ADVERB}\s*{_QUESTION_CORE}[\s？？！？。，.!]*$"
)
# 只判「这句是不是她亲口问自己」——用于第一人称路径的 owner 收窄，不改第三人称取数。
_QUESTION_FIRST_PERSON_HEAD_RE = re.compile(rf"^(?:{_QUESTION_FIRST_PERSON_HEAD_WORDS})")
_QUESTION_NATURAL_ALIASES: tuple[str, ...] = (
    "她在干嘛",
    "她在忙什么",
    "主人在干嘛",
    "主人去哪了",
    "她出去了吗",
)

# 可见性/重复/学期锚 词面（正文剥离用）。全部要求实义字，不匹配空串。
_VIS_PUBLIC_RE = re.compile(r"[，,。 ]*(?:设为?公开|设成公开|可公开|公开)\s*$")
_VIS_PRIVATE_RE = re.compile(r"[，,。 ]*(?:设为?隐私|设成隐私|隐私|不公开|保密)\s*$")
_RECUR_EVERY_RE = re.compile(r"每(?:周|星期|个周)|weekly")
_WEEKDAY_RE = re.compile(r"(?:每)?(?:周|星期|个周)([一二三四五六日天])")
_PARITY_RE = re.compile(r"(单周|双周)")
_SEMESTER_RE = re.compile(r"学期\s*(\d{4}-\d{1,2}-\d{1,2})")
_WEEKDAY_VALUE = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

# 课表导入行：`周X 8:00-9:40 名称 [地点] [单|双]`（全角宽容；只有显式时刻才收）。
_IMPORT_LINE_RE = re.compile(
    r"^周([一二三四五六日天])\s*"
    r"(\d{1,2})[:：点](\d{1,2}|半)?\s*(?:-|—|~|～|到|至)\s*"
    r"(\d{1,2})[:：点](\d{1,2}|半)?\s*(.+?)\s*(?:(单|双)周?)?\s*$"
)

# ---------------------------------------------------------------------------
# 类别分级（代答投影的确定性词表；敏感类别永不外显细节，设计 §5.2）
# ---------------------------------------------------------------------------

CATEGORY_PHRASES: dict[str, str] = {
    "course": "在上课",
    "meeting": "有安排",
    "away": "出门了",
    "busy": "有事情",
}
_SENSITIVE_CATEGORIES = frozenset({"health", "meal", "rest", "psych"})

_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("health", ("药", "病", "医院", "体检", "复诊", "打针", "输液", "手术", "牙医", "就诊")),
    ("meal", ("吃", "饭", "餐", "外卖", "食堂", "聚餐", "做饭", "买菜")),
    ("rest", ("睡", "睡觉", "午休", "小憩", "起床", "作息", "歇")),
    ("psych", ("咨询", "心理")),
    ("course", ("课", "考试", "讲座", "答辩", "组会", "自习", "实验")),
    ("meeting", ("会议", "开会", "讨论", "面试", "汇报", "评审")),
    ("away", ("出门", "赶车", "航班", "高铁", "飞机", "火车", "出行", "办事", "取件", "快递")),
)


def classify_schedule_activity(text: str) -> str:
    """活动文本 → 类别（确定性、先命中先得；健康/饮食/作息/心理排在最前=硬下限）。

    顺序即优先级：「去看牙医」即便含外出语境也归 health；敏感类别对非本人档
    恒折叠「有事情」——折叠发生在 ``_project_answer``，分类器本身只报事实。
    """
    content = str(text or "")
    for category, words in _CATEGORY_RULES:
        if any(word in content for word in words):
            return category
    return "busy"


# ---------------------------------------------------------------------------
# 开关与文本工具
# ---------------------------------------------------------------------------


def _flag(config: Any | None, name: str, default: bool = False) -> bool:
    """开关读取口径（与 notes 的 is_notes_command 同型）：

    ``config=None`` 恒按**开**处理——那是触发词双向门/离线词面验证的调用形
    （检测器不带配置跑探针）；生产路由腿传入真 config，缺省 False 的闸
    在那里生效（base_router.reminder_match → is_reminder_command(config=config)）。
    """
    if config is None:
        return True
    return bool(getattr(config, name, default))


def schedule_feature_enabled(config: Any | None) -> bool:
    """记录腿总闸（沿用既有键 bot_schedule_enabled，缺省 False 不改）。"""
    return _flag(config, "bot_schedule_enabled", False)


def status_reply_enabled(config: Any | None) -> bool:
    """代答腿总闸：默认关——对外说话的一律单独开（记录只写本机库，代答才出门）。"""
    return schedule_feature_enabled(config) and _flag(
        config, "bot_schedule_status_reply_enabled", False
    )


def natural_capture_enabled(config: Any | None) -> bool:
    """宽口径自然捕捉闸：默认关——只认显式命令与导入，不猜她随口一句话。"""
    return schedule_feature_enabled(config) and _flag(
        config, "bot_schedule_natural_capture_enabled", False
    )


def _normalized_question_text(text: str) -> str:
    stripped = str(text or "").strip()
    # 反复剥开头 @ 与称呼（群聊习惯「@守岸人 主人在干嘛」连缀）。
    for _ in range(2):
        stripped = _QUESTION_HEAD_RE.sub("", stripped, count=1).strip()
    return stripped


def _question_pattern(config: Any | None) -> re.Pattern[str]:
    """问句正则：管理员档案显示名可点名（动态拼入缓存）。

    双向门只钉静态词（她在干嘛/主人在干嘛…）；名字档是运行时增强：
    名字全部来自 ``bot_admin_profiles``，本函数不养第二份名单。
    """
    names: list[str] = []
    profiles = getattr(config, "bot_admin_profiles", []) or [] if config is not None else []
    for entry in profiles:
        try:
            name = str(entry.get("name") or entry.get("display_name") or "").strip()
        except AttributeError:
            name = ""
        if name and not name.isascii():
            names.append(name)
    if not names:
        return _QUESTION_RE
    head = _QUESTION_HEAD_WORDS + "|" + "|".join(re.escape(name) for name in names)
    return _QUESTION_RE_CACHED(_QUESTION_HEAD_WORDS, head)


@lru_cache(maxsize=16)
def _QUESTION_RE_CACHED(_base_heads: str, head: str) -> re.Pattern[str]:
    return re.compile(
        rf"^(?:{head})\s*{_QUESTION_ADVERB}\s*{_QUESTION_CORE}[\s？？！？。，.!]*$"
    )


def is_schedule_command(text: str, *, config: Any | None = None) -> bool:
    """记录/管理命令面判定（总闸关=整面不存在，让路聊天，行为零变更）。"""
    if not schedule_feature_enabled(config):
        return False
    stripped = (text or "").strip()
    if not stripped or len(stripped) > 4000:
        return False
    return bool(
        _BOARD_BARE_RE.match(stripped)
        or _BOARD_LIST_RE.match(stripped)
        or _BOARD_DELETE_RE.match(stripped)
        or _BOARD_DELETE_RULE_RE.match(stripped)
        or _BOARD_VISIBILITY_RE.match(stripped)
        or _BOARD_IMPORT_RE.match(stripped)
        or (len(stripped) <= _MAX_ADD_CHARS and _BOARD_ADD_RE.match(stripped))
    )


def is_schedule_natural(text: str, *, config: Any | None = None) -> bool:
    """宽口径自然捕捉判定（开关关=恒 False；短句+时间+活动词，且不抢提醒/问句）。"""
    if not natural_capture_enabled(config):
        return False
    stripped = (text or "").strip()
    if not 6 <= len(stripped) <= _NATURAL_MAX_CHARS:
        return False
    if any(ch in stripped for ch in "？?"):
        return False
    if _NATURAL_SIGNAL_EXCLUDE_RE.search(stripped):
        return False
    if len(re.findall(r"[。！!；;\n]", stripped)) > 1:
        return False  # 多句粘贴体不进日程（提醒域粘贴守卫同哲学）
    if not _NATURAL_ACTIVITY_RE.search(stripped):
        return False
    return parse_time_target(stripped) is not None


def is_status_question(text: str, *, config: Any | None = None) -> bool:
    """代答问句判定（闸关=恒 False；整句判据防长句从句截胡）。"""
    if not status_reply_enabled(config):
        return False
    normalized = _normalized_question_text(text)
    if not normalized or len(normalized) > 24:
        return False
    return bool(_question_pattern(config).match(normalized))


def _is_first_person_question(text: str) -> bool:
    """这句是不是她亲口问自己（第一人称头词）——决定代答取数是否收窄到本人板子。"""
    return bool(_QUESTION_FIRST_PERSON_HEAD_RE.match(_normalized_question_text(text)))


def is_schedule_surface(text: str, *, config: Any | None = None) -> bool:
    """路由与能力共用的唯一日程判据（一处判据、两腿同源，禁第二份）。"""
    return (
        is_schedule_command(text, config=config)
        or is_status_question(text, config=config)
        or is_schedule_natural(text, config=config)
    )


def capture_clean_text(message: IncomingMessage) -> str | None:
    """捕获/添加腿的**唯一**取文本口径（G4 残余①：引用拼接污染拒捕）。

    摄取层把被引用正文拼进 ``plain_text``（``[引用回复 层级N 名] …`` 等块，
    真身正则 ``message_context.INTERNAL_MARKER_PATTERN``，此处不复制第二份），
    而 ``command_text`` 只认拼接**之前**的本人原文。回退链必须守住两条：

    1. ``command_text`` 非空 ⇒ 只吃它（引用块里的话永远进不了板子）；
    2. ``command_text`` 为空 ⇒ 兼容从未填充该契约字段的摄取路径，可读
       ``plain_text``，但其中**引用/转发标记在场即整条拒捕**——
       别人的话宁可漏记，绝不脏记上板（状态只从她亲口说的话取）。

    返回 ``None``＝拒捕（调用方必须让位、不承接），``""``＝无文本可捕。
    """
    command = str(message.command_text or "").strip()
    if command:
        return command
    plain = str(message.plain_text or "").strip()
    if not plain:
        return ""
    if INTERNAL_MARKER_PATTERN.search(plain):
        return None
    return plain


# ---------------------------------------------------------------------------
# 解析：命令正文 → 条目意图（时间复用提醒域唯一解析器；地点/溯源进标签不进标题）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduleAddIntent:
    start_local: datetime  # 配置时区 aware
    activity: str
    duration_minutes: int | None  # None=只说了开始时刻
    public: bool
    weekly_weekday: int | None  # None=一次性（裸「周三」=下周三单点，保守不推断成周课）
    parity: str | None  # odd|even|None（单双教学周；无学期锚时调用方必须回问）
    semester_start: str | None  # "YYYY-MM-DD" 或 None
    source_message_id: str = ""
    location: str = ""


def _strip_time_phrases(text: str) -> str:
    """把可解析时间词面从正文剥掉（**复用 reminders 的同一批编译正则对象**，
    只剥 span 不再推时刻——不是第二解析器，是同一真身的取形半边）。"""
    remainder = text
    for pattern in (
        _REL_HALF_HOUR_RE,
        _REL_MINUTES_RE,
        _REL_HOURS_RE,
        _ABS_TIME_RE,
        _PERIOD_ONLY_RE,
    ):
        remainder = pattern.sub(" ", remainder)
    remainder = re.sub(r"(?:每)?(?:周|星期|个周)[一二三四五六日天]|单周|双周", " ", remainder)
    return re.sub(r"\s+", " ", remainder).strip(" ，,。.:：-—~～到至")


def _end_from_phrase(phrase: str, start: datetime) -> datetime | None:
    """「到9点40 / 9:40」→ 同日（或跨午夜 +1 天）的结束时刻。

    只做钟点算术：捕获组来自同一 ``_ABS_TIME_RE`` 真身，下午/晚间 +12h 与
    reminders 级联同规则；**不做日词推算**（终点恒锚定开始日），故不构成第二
    时间解析器（设计 §2.1 的边界写明）。
    """
    match = _ABS_TIME_RE.search(phrase)
    if match is None:
        return None
    _day, period, hour_text, minute_text, half = match.groups()
    try:
        hour = int(hour_text)
    except (TypeError, ValueError):
        return None
    minute = 30 if half else (int(minute_text) if minute_text else 0)
    if period in {"下午", "傍晚", "晚上"} and hour < 12:
        hour += 12
    if period == "凌晨" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    end = start.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if end <= start:
        end += timedelta(days=1)
    return end


def _neutralize_entry_title(text: str) -> str:
    """条目题面唯一消毒口（票3 ATK-SCHED）：全角化内部边界标记 + 限长。

    消毒真身只有一把——``chat_reply/security/injection.neutralize_internal_markers``
    （唯一判据 INTERNAL_MARKER_PATTERN），本函数不复制第二套正则、不开新标记名；
    落点选在**意图构造出口**（解析腿与导入腿各一处调用），使入库、幂等比对、
    回执重放、代答投影四面消费同一份净题面（G3 去重键不因消毒口径分叉）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
        neutralize_internal_markers,
    )

    return neutralize_internal_markers(str(text or ""))[:_MAX_ACTIVITY_CHARS]


def parse_schedule_add(text: str, *, now: datetime | None = None) -> ScheduleAddIntent | None:
    """命令正文（或自然捕捉整句）→ 条目意图；无未来可解析时刻 → None（绝不猜点）。"""
    raw = (text or "").strip()
    if not raw:
        return None
    add_match = _BOARD_ADD_RE.match(raw)
    body = add_match.group(1) if add_match else raw
    if add_match is None:
        body = re.sub(r"^(?:记日程|记一下日程)\s*[，,：:]?\s*", "", body).strip()
    if not body:
        return None
    public = False
    if _VIS_PUBLIC_RE.search(body):
        public = True
        body = _VIS_PUBLIC_RE.sub("", body).strip()
    if _VIS_PRIVATE_RE.search(body):
        body = _VIS_PRIVATE_RE.sub("", body).strip()  # 隐私是缺省，只剥词
    semester_match = _SEMESTER_RE.search(body)
    semester_start = semester_match.group(1) if semester_match else None
    if semester_match:
        body = body.replace(semester_match.group(0), " ").strip()
    parity: str | None = None
    parity_match = _PARITY_RE.search(body)
    if parity_match:
        parity = "odd" if parity_match.group(1).startswith("单") else "even"
    weekly = bool(_RECUR_EVERY_RE.search(body))
    weekday_match = _WEEKDAY_RE.search(body)
    weekday = _WEEKDAY_VALUE.get(weekday_match.group(1)) if weekday_match else None
    start = parse_time_target(body, now=now)
    if start is None:
        return None
    duration: int | None = None
    end_probe = re.search(r"(?:-|—|~|～|到|至)\s*[^\s，,]*?\d", body)
    if end_probe is not None:
        end = _end_from_phrase(body[end_probe.start():], start)
        if end is not None:
            duration = max(0, int((end - start).total_seconds() // 60))
    activity = _strip_time_phrases(body)
    activity = re.sub(
        r"^(?:我)?\s*(?:要|得|会|打算|计划|有)?\s*", "", activity
    ).strip()
    activity = re.sub(r"(?:日程|记一下|安排|计划)", " ", activity).strip(" ，,。.、")
    if not activity:
        activity = "她记下的安排"
    return ScheduleAddIntent(
        start_local=start,
        # 票3（ATK-SCHED，S-FIX-ATK-SCHED2）：题面**入库即净**——提醒腿 T3 先例同尺
        # （reminder.py add 腿走 neutralize_internal_markers，唯一真身
        # INTERNAL_MARKER_PATTERN，不开第二套正则）。日程条目会以她的口吻进
        # 回执/代答（capture_clean_text 规则 1 让 command_text 原样通过是 G4 的
        # 引用隔离，不是标记消毒——两者正交），字面 [TRUSTED_SYSTEM] 一类标记
        # 就此被全角化；用户正常书写的方括号文本不在标记名册，逐字不动。
        activity=_neutralize_entry_title(activity),
        duration_minutes=duration,
        public=public,
        weekly_weekday=weekday if (weekly or parity) else None,
        parity=parity,
        semester_start=semester_start,
    )


# ---------------------------------------------------------------------------
# 板主键（票1 ATK-SCHED，2026-09-28 S-FIX-ATK-SCHED2）：(平台域, sender_id) 人物键
# ---------------------------------------------------------------------------


def _board_owner_of(message: IncomingMessage) -> str:
    """入站消息 → 板主身份键（唯一构造口＝中央件 ``session_keys.person_scope_key``）。

    病根：旧版 ``owner = str(message.sender_id)`` 裸号建键——QQ 号与 TG uid
    同数即跨平台同号接管（读[密]条目时刻→翻公开→删→投毒全链，零角色要求，
    探针 ATKSCHED-1）。平台事实吃 ``message.platform``，经 ``platform_domain_of``
    （名单侧同一归一真身）折成平台域；不认识的平台落空域段＝独立桶（fail-closed，
    绝不继承 qq/telegram 任何一家的板）。段消毒在中央件构造口内完成，
    本函数不拼字面、不造第二键形。
    """
    return person_scope_key(
        platform_domain_of(getattr(message, "platform", "")), message.sender_id
    )


def _board_owner_from_roster_id(raw_id: str) -> str:
    """名单/配置里的用户号 → 板主身份键（裸号＝QQ 原生域，与 roles 名单裁定同尺）。

    ``policy/roles._qualify_entries`` 的在册口径：裸号条目归属名单原生平台（QQ），
    带域前缀条目（``telegram:2002``）只在同域生效，且**前缀同样过
    ``platform_domain_of`` 归一**（``tg:2002`` 与 ``telegram:2002`` 同条目）——
    本函数与消息腿 ``_board_owner_of`` 用同一把尺折键，别名前缀不会折出配不上
    消息键的孤儿桶。代答腿拿到的 owner 候选来自配置
    （``bot_super_admin_user_ids``），QQ 超管的板从此只对 ``qq`` 域消息可写，
    同号 TG 用户拼不出这把键。
    """
    head, separator, tail = str(raw_id or "").strip().partition(PERSON_SCOPE_SEP)
    if separator and head and tail:
        domain = platform_domain_of(head) or head
        return person_scope_key(domain, tail)
    return person_scope_key(PLATFORM_QQ, raw_id)


# ---------------------------------------------------------------------------
# 板子操作（全部经 ScheduleService 门面：乐观 revision、幂等物化、DAG 硬闸白嫖）
# ---------------------------------------------------------------------------


def _board_plan_for_write(store: Any, service: Any, owner: str) -> tuple[Any, dict[str, Any], bool]:
    """owner → (SchedulePlan|None, 可改 payload dict, 板子是否已存在)。"""
    from plugins.bot_unified_runtime.domains.schedule.service.schedule_dag import (
        SchedulePlan,
    )

    plan_id = store.plan_id_for_owner(owner)
    if plan_id is None:
        fresh = SchedulePlan(
            plan_id=f"{BOARD_PLAN_PREFIX}{owner}",
            owner=str(owner),
            timezone=configured_timezone(),
            state="active",
        )
        return None, fresh.model_dump(), False
    plan = service.get_plan(plan_id)
    return plan, plan.model_dump(), True


def _resubmit(service: Any, payload: dict[str, Any], *, expected_revision: int | None) -> Any:
    from plugins.bot_unified_runtime.domains.schedule.service.schedule_service import (
        parse_plan,
    )

    plan = parse_plan(payload)
    service.submit_plan(plan, expected_revision=expected_revision, confirm=True)
    service.expand_occurrences(plan)
    return plan


def _add_entry(service: Any, store: Any, owner: str, intent: ScheduleAddIntent) -> str:
    """一条意图 → plan 增改 + 落库 + 物化；返回展示行。限额/DAG 校验由引擎闸负责。"""
    plan, payload, existed = _board_plan_for_write(store, service, owner)
    # 票4（ATK-SCHED，S-FIX-ATK-SCHED2）：编号**只进不退**——取板上既有 eNNN 号
    # 最大值 +1，而非现存条数 +1。旧式 len(tasks)+1 在「日程 删课」删掉非末尾条目后
    # 回退撞仍存在的旧 task_id，被引擎 duplicate task_id 拒（schedule_dag.py:392-397），
    # 该板所有后续新增永久失败且用户不可自愈（探针 ATKSCHED-4）。
    # 最小修法取舍：只改取号式、task_id 形不变 ⇒ 板上历史条目零迁移、引擎/展示面
    # 零改动；「task_id 含代次/时间戳」要改 id 词法并处理新旧两形并存，改动面更大。
    tasks = payload.get("tasks") or []
    max_seq = 0
    for task in tasks:
        head, digits = str(task.get("task_id") or "")[:1], str(task.get("task_id") or "")[1:]
        if head == "e" and digits.isdigit():
            max_seq = max(max_seq, int(digits))
    seq = max(len(tasks) + 1, max_seq + 1)
    task_id = f"e{seq:03d}"
    rule_id = f"r_{task_id}"
    tags: list[str] = []
    if intent.public:
        tags.append(VIS_PUBLIC)
    if intent.location:
        tags.append(f"{LOC_TAG_PREFIX}{intent.location[:40]}")
    if intent.source_message_id:
        tags.append(f"{SRC_TAG_PREFIX}{intent.source_message_id[:40]}")
    start_local = intent.start_local
    if intent.weekly_weekday is not None:
        anchor = intent.semester_start or start_local.date().isoformat()
        if intent.parity:
            rule = {
                "rule_id": rule_id,
                "task_id": task_id,
                "kind": "teaching_week",
                "start_date": anchor,
                "local_time": start_local.strftime("%H:%M"),
                "weekdays": [intent.weekly_weekday],
                "week_parity": intent.parity,
                "parity_anchor_date": anchor,
            }
        else:
            rule = {
                "rule_id": rule_id,
                "task_id": task_id,
                "kind": "weekly_by_day",
                "start_date": anchor,
                "local_time": start_local.strftime("%H:%M"),
                "weekdays": [intent.weekly_weekday],
            }
    else:
        rule = {
            "rule_id": rule_id,
            "task_id": task_id,
            "kind": "once",
            "start_date": start_local.date().isoformat(),
            "local_time": start_local.strftime("%H:%M"),
        }
    payload["tasks"].append(
        {
            "task_id": task_id,
            "title": intent.activity,
            "kind": "fixed_time",
            "duration_minutes": intent.duration_minutes or 0,
            "fixed_local_time": start_local.strftime("%H:%M"),
            "soft_window_minutes": 5,
            "tags": tags,
        }
    )
    payload["rules"].append(rule)
    _resubmit(
        service,
        payload,
        expected_revision=plan.revision if (existed and plan is not None) else None,
    )
    return f"{intent.activity}｜{_display_when(start_local, intent.duration_minutes)}"


def _display_when(start_local: datetime, duration_minutes: int | None) -> str:
    when = f"{start_local.month}月{start_local.day}日 {start_local:%H:%M}"
    if duration_minutes:
        end = start_local + timedelta(minutes=duration_minutes)
        when += f"–{end:%H:%M}"
    return when


def _entry_already_on_board(
    service: Any, store: Any, owner: str, intent: ScheduleAddIntent
) -> bool:
    """板上是否已有「同天 + 同标题 + 同刻」的等价条目（G3 幂等，刻意只做这一层）。

    判据只锚定她说过的原句能否与既有条目逐字对齐：一次性条目比 start_date 的日历日，
    周期条目比同一星期槽（weekly_weekday 缺省退到 start_local 的星期）；标题与本地
    时刻必须都相同才算重复——不同时刻/不同标题一律另起一条，不做花哨去重。
    """
    plan = _load_plan(service, store, owner)
    if plan is None:
        return False
    title = str(intent.activity)
    time_str = intent.start_local.strftime("%H:%M")
    date_str = intent.start_local.date().isoformat()
    start_weekday = intent.start_local.weekday()
    for rule in plan.rules:
        task = plan.task_by_id(rule.task_id)
        if task is None or str(task.title) != title:
            continue
        if str(rule.local_time) != time_str:
            continue
        kind = str(getattr(rule.kind, "value", rule.kind))
        if kind == "once":
            if str(rule.start_date) == date_str:
                return True
        else:
            slot = intent.weekly_weekday if intent.weekly_weekday is not None else start_weekday
            if slot in (rule.weekdays or []):
                return True
    return False


# ---------------------------------------------------------------------------
# 列表 / 删除 / 可见性
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardItem:
    seq: int
    plan_id: str
    rule_id: str
    task_id: str
    occurrence_id: str
    title: str
    start_local: datetime
    duration_minutes: int
    public: bool
    rule_kind: str


def _plan_zone(plan: Any) -> Any:
    try:
        return ZoneInfo(str(plan.timezone))
    except Exception:  # noqa: BLE001 - 板子时区解析失败退回 UTC 展示，不炸列表。
        return UTC


def _load_plan(service: Any, store: Any, owner: str) -> Any | None:
    from plugins.bot_unified_runtime.domains.schedule.service.schedule_dag import (
        SchedulePlan,
    )

    plan_id = store.plan_id_for_owner(owner)
    if plan_id is None:
        return None
    stored = store.get_plan(plan_id)
    if stored is None:
        return None
    return SchedulePlan.model_validate(stored["payload"])


def list_board_items(
    service: Any, store: Any, owner: str, *, now: datetime | None = None
) -> list[BoardItem]:
    """未来 pending 实例（30 天物化窗内）→ 编号清单（开始时刻升序，同刻按 rule_id）。"""
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    plan = _load_plan(service, store, owner)
    if plan is None:
        return []
    rule_kinds = {rule.rule_id: rule.kind.value for rule in plan.rules}
    service.expand_occurrences(plan)  # 幂等补物化（occurrence_id 语义保证不双落）
    rows = [
        row
        for row in store.list_occurrences(plan_id=plan.plan_id, status="pending", limit=400)
        if float(row["due_epoch"]) >= now_utc.timestamp() - 60
    ]
    rows.sort(key=lambda row: (float(row["due_epoch"]), str(row["rule_id"])))
    items: list[BoardItem] = []
    for index, row in enumerate(rows[:_LIST_CAP], start=1):
        start_local = datetime.fromisoformat(str(row["scheduled_at_utc"])).astimezone(_plan_zone(plan))
        items.append(
            BoardItem(
                seq=index,
                plan_id=plan.plan_id,
                rule_id=str(row["rule_id"]),
                task_id=str(row["task_id"]),
                occurrence_id=str(row["occurrence_id"]),
                title=str(row["title"]),
                start_local=start_local,
                duration_minutes=int(row["duration_minutes"] or 0),
                public=VIS_PUBLIC in (row.get("tags") or []),
                rule_kind=str(rule_kinds.get(str(row["rule_id"]), "once")),
            )
        )
    return items


# ---------------------------------------------------------------------------
# 代答腿（§C）：分级投影 + 出站前隐私判定（零 LLM、字段白名单、统一打码）
# ---------------------------------------------------------------------------


def asker_tier(message: IncomingMessage, owner: str) -> str:
    """提问者对这位 owner 的档位：owner / named / basic 三档（设计 §5.1）。

    owner 档只在**私聊且本人是超管**时成立——群聊里连她自己问，也不把隐私条目
    摆上全群可见的回复面（收紧方向唯一：只会更少外显）。

    票1（ATK-SCHED）：同号比对吃**板主身份键**（平台域, sender_id），不吃裸号——
    键形与板腿同源（``_board_owner_of``），别处不另判一份。owner 参数为
    ``_board_owner_from_roster_id``/``_board_owner_of`` 产出的键形。
    """
    roles = {str(role).strip().lower() for role in (message.sender_roles or [])}
    asker_owner = _board_owner_of(message)
    is_group = str(getattr(message.session_type, "value", message.session_type)) == "group"
    if (
        asker_owner
        and asker_owner == str(owner).strip()
        and ROLE_SUPER_ADMIN in roles
        and not is_group
    ):
        return "owner"
    if ROLE_SUPER_ADMIN in roles or ROLE_ADMIN in roles or ROLE_TRUSTED in roles:
        return "named"
    return "basic"


def active_entries(
    service: Any, store: Any, owner: str, *, now: datetime | None = None
) -> list[BoardItem]:
    """此刻正在进行的全部实例（**含隐私**；只供投影函数消费，不得直接外发）。

    判据从 plan 规则**现算**而不是查物化 occurrence 表——引擎的 expand 只收
    ``scheduled_at >= now`` 的未来实例（V2.1 合同语义，禁改），"正在进行"恰是
    开始已过、结束未到的那段；从规则现算还顺带白赚一个好处：可见性改标对
    代答立即生效（不依赖 retag 之后是否重物化）。窗口取 [昨天, 今天]，
    跨午夜的长日程（如夜班）也算进行中。
    """
    from plugins.bot_unified_runtime.domains.schedule.service.schedule_rrule import (
        iter_rule_dates,
        resolve_local,
    )

    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    plan = _load_plan(service, store, owner)
    if plan is None:
        return []
    zone = _plan_zone(plan)
    local_today = now_utc.astimezone(zone).date()
    now_epoch = now_utc.timestamp()
    task_index = {task.task_id: task for task in plan.tasks}
    items: list[BoardItem] = []
    for rule in plan.rules:
        task = task_index.get(rule.task_id)
        if task is None:
            continue
        duration = int(task.duration_minutes or 0) or _ACTIVE_WINDOW_FALLBACK_MINUTES
        for day in iter_rule_dates(rule, local_today - timedelta(days=1), local_today):
            resolution = resolve_local(zone, day, rule.local_time)
            start_epoch = resolution.utc_value.timestamp()
            if start_epoch <= now_epoch < start_epoch + duration * 60:
                items.append(
                    BoardItem(
                        seq=0,
                        plan_id=plan.plan_id,
                        rule_id=rule.rule_id,
                        task_id=rule.task_id,
                        occurrence_id="",
                        title=task.title,
                        start_local=resolution.utc_value.astimezone(zone),
                        duration_minutes=int(task.duration_minutes or 0),
                        public=VIS_PUBLIC in (task.tags or []),
                        rule_kind=rule.kind.value,
                    )
                )
                break  # 两日窗口内一条规则至多一个进行中实例
    items.sort(key=lambda item: item.start_local)
    return [replace(item, seq=index) for index, item in enumerate(items, start=1)]


_WINDOW_TERMS_RE = re.compile(f"({_QUESTION_WINDOW_TERMS})")
_WINDOW_MONTH_DAY_RE = re.compile(r"^(\d{1,2})月(\d{1,2})[日号]$")
_FUTURE_IMPLIED_RE = re.compile(r"什么时候(?:忙|有事)|几点(?:有事|有空|忙)")


def _window_days(text: str, today: date) -> tuple[date, date, str] | None:
    """问句 → 未来窗 (起始日, 截止日, 展示词)；None＝不是未来窗问句（走现在腿）。

    G2(a) 确定性唯一判据（代答文案与取数共用，禁第二判据口）：
    - 命中窗词面（_QUESTION_WINDOW_TERMS 唯一串）按词族解：明天/后天/本周/
      下周[周X]/周末/周X/星期X/M月D日；
    - 落在"今天或过去"的窗一律 None——拿半天已过的日子答"忙不忙"不如让位
      现在腿（宁漏不误）；
    - "什么时候忙/几点有事"无窗词 = 默认明天起 7 天窗；
    - 大后天/下下周/节假日等未点名形态不猜，恒 None。
    """
    stripped = str(text or "")
    match = _WINDOW_TERMS_RE.search(stripped)
    if match is None:
        if _FUTURE_IMPLIED_RE.search(stripped):
            return today + timedelta(days=1), today + timedelta(days=7), "未来一周"
        return None
    term = match.group(1)
    week_sunday = today + timedelta(days=6 - today.weekday())
    if term in ("明天", "明日"):
        return today + timedelta(days=1), today + timedelta(days=1), "明天"
    if term == "后天":
        return today + timedelta(days=2), today + timedelta(days=2), "后天"
    if term in ("本周", "这周"):
        if today == week_sunday:
            return None  # 周日问"本周"：只剩今天，让位现在腿（同日窗不答）
        return today, week_sunday, "本周"
    if term in ("下周末", "本周末", "这周末", "周末"):
        saturday = week_sunday - timedelta(days=1)
        if term == "下周末":
            saturday += timedelta(days=7)
        elif today > saturday:
            return None  # 已是周日：本周末没有未来日可答
        return saturday, saturday + timedelta(days=1), "周末"
    if term.startswith("下周"):
        next_monday = today + timedelta(days=7 - today.weekday())
        suffix = term[len("下周"):]
        if suffix:
            weekday_day = next_monday + timedelta(days=_WEEKDAY_VALUE[suffix])
            return weekday_day, weekday_day, f"下周{suffix if suffix != '天' else '日'}"
        return next_monday, next_monday + timedelta(days=6), "下周"
    md = _WINDOW_MONTH_DAY_RE.match(term)
    if md is not None:
        # 枚/日只在这支是整数；命名与「周X」支的 date 型 day 分开，
        # 否则同函数体内一名两型（mypy 两红就是这条遮蔽链）。
        month_no, day_no = int(md.group(1)), int(md.group(2))
        if not 1 <= month_no <= 12:
            return None
        candidate: date | None = None
        for year in (today.year, today.year + 1):
            try:
                probe = date(year, month_no, day_no)
            except ValueError:
                probe = None
            if probe is not None and probe >= today:
                candidate = probe
                break
        if candidate is None or candidate == today:
            return None  # 纯过去日不接（宁漏不误）
        return candidate, candidate, f"{month_no}月{day_no}日"
    if term[-1] in _WEEKDAY_VALUE:  # 周X/星期X/礼拜X
        suffix = term[-1]
        offset = _WEEKDAY_VALUE[suffix]
        day = today + timedelta(days=(offset - today.weekday()) % 7)
        if day == today:
            return None  # "今天恰是周X"：半天已过，让位现在腿
        return day, day, f"周{suffix if suffix != '天' else '日'}"
    return None


def window_entries(
    service: Any, store: Any, owner: str, text: str, *, now: datetime | None = None
) -> tuple[str, list[BoardItem]] | None:
    """未来窗代答取数（G2(a)）：解得出的窗问句 ⇒ (窗词, 窗内实例)（**含隐私**）。

    None＝非窗问句 / 窗落在今天或过去 ⇒ 调用方回退 ``active_entries`` 现在腿。
    与 ``active_entries`` 同构：从 plan 规则**现算**（recurrence 不受 30 天
    物化窗约束），每条规则取窗内最早命中一次；投影前不得直接外发。
    """
    from plugins.bot_unified_runtime.domains.schedule.service.schedule_rrule import (
        iter_rule_dates,
        resolve_local,
    )

    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    plan = _load_plan(service, store, owner)
    if plan is not None:
        zone = _plan_zone(plan)
    else:
        zone = now_utc.astimezone().tzinfo  # 无板：仅需解窗词，日期基准退系统本地
    spec = _window_days(text, now_utc.astimezone(zone).date())
    if spec is None:
        return None
    start_day, end_day, label = spec
    if plan is None:
        return label, []
    start_day = max(start_day, now_utc.astimezone(zone).date())
    task_index = {task.task_id: task for task in plan.tasks}
    items: list[BoardItem] = []
    for rule in plan.rules:
        task = task_index.get(rule.task_id)
        if task is None:
            continue
        days = iter_rule_dates(rule, start_day, end_day)
        if not days:
            continue
        resolution = resolve_local(zone, days[0], rule.local_time)
        items.append(
            BoardItem(
                seq=0,
                plan_id=plan.plan_id,
                rule_id=rule.rule_id,
                task_id=rule.task_id,
                occurrence_id="",
                title=task.title,
                start_local=resolution.utc_value.astimezone(zone),
                duration_minutes=int(task.duration_minutes or 0),
                public=VIS_PUBLIC in (task.tags or []),
                rule_kind=rule.kind.value,
            )
        )
    items.sort(key=lambda item: item.start_local)
    return label, [replace(item, seq=index) for index, item in enumerate(items, start=1)]


_FALLBACK_LINES: tuple[str, ...] = (
    "（偏头）她这会儿有事情，不太方便讲～",
    "她眼下不在状态里，像是有事～要捎话我记下。",
    "这会儿她手头有事～你留一句，我原样带到。",
)


def _pick_fallback(seed: str) -> str:
    digest = sha1(str(seed).encode("utf-8")).digest()
    return _FALLBACK_LINES[digest[0] % len(_FALLBACK_LINES)]


def _format_span(item: BoardItem) -> str:
    start = f"{item.start_local:%H:%M}"
    if item.duration_minutes:
        end = (item.start_local + timedelta(minutes=item.duration_minutes)).strftime("%H:%M")
        return f"{start} 到 {end}"
    return f"{start} 起"


def _project_answer(
    message: IncomingMessage,
    tier: str,
    items: list[BoardItem],
    *,
    fallback_seed: str,
    when_label: str | None = None,
) -> str:
    """分级投影（**隐私判定就发生在这里，出站前**）。

    字段白名单：只读 title / start_local / duration_minutes / public / 类别。
    地点（loc: 标签）、溯源（src: 标签）在本函数**结构上不可达**——BoardItem
    根本不带这两个字段，不是"忘了外显"而是没有取数路径（注毒锁执法）。

    ``when_label``（G2(a) 未来窗）只改时位措辞，**不改任何一档的隐私口径**：
    owner 档窗内无数给诚实的"没安排"；非本人档窗内无公开条目仍回与"全隐私"
    **逐字相同**的模糊句——空窗与满隐私窗对外不可分辨（设计 §5.2 铁律）。
    """
    if tier == "owner":
        if when_label is not None:
            lines = [
                f"你{when_label}挂着：{item.title}（{_format_span(item)}，"
                f"{'公开' if item.public else '隐私'}）"
                for item in items[:3]
            ]
            return "\n".join(lines) if lines else f"你{when_label}没安排～"
        lines = [
            f"你现在挂着：{item.title}（{_format_span(item)}，"
            f"{'公开' if item.public else '隐私'}）"
            for item in items[:3]
        ]
        return "\n".join(lines) if lines else _pick_fallback(fallback_seed)
    # 非本人档：一行过滤，隐私条目结构性剔除（fail-closed，白名单只有公开）。
    visible = [item for item in items if item.public]
    if not visible:
        # 空板与全隐私板得到**逐字相同**的模糊句：条目缺席不是证据（设计 §5.2）。
        return _pick_fallback(fallback_seed)
    item = visible[0]
    category = classify_schedule_activity(item.title)
    when = when_label or "正在"
    if tier == "named" and category not in _SENSITIVE_CATEGORIES:
        body = (
            f"她{when}有这个：{item.title}，{_format_span(item)}。"
            if when_label is not None
            else f"她正在忙这个：{item.title}，{_format_span(item)}。"
        )
    else:
        phrase = CATEGORY_PHRASES["busy" if category in _SENSITIVE_CATEGORIES else category]
        body = (
            f"她{when}{phrase}，{_format_span(item)}。"
            if when_label is not None
            else f"她{phrase}，{_format_span(item)}。"
        )
    if tier == "named" and str(getattr(message.session_type, "value", "")) == "group":
        body += "\n（她本人的完整日程，只在私聊里对她自己讲。）"
    return body


def resolve_status_owners(config: Any, question_text: str) -> list[str]:
    """被问对象：问句点名（超管显示名）优先；否则全体超管（有公开进行中者胜）。"""
    super_ids = [
        str(x).strip()
        for x in (getattr(config, "bot_super_admin_user_ids", []) or [])
        if str(x).strip()
    ]
    profiles = getattr(config, "bot_admin_profiles", []) or []
    for entry in profiles:
        try:
            uid = str(entry.get("user_id") or entry.get("id") or "").strip()
            name = str(entry.get("name") or entry.get("display_name") or "").strip()
        except AttributeError:
            continue
        if name and uid and name in question_text and uid in super_ids:
            return [uid]
    return super_ids


# ---------------------------------------------------------------------------
# 能力主体
# ---------------------------------------------------------------------------

_USAGE_TEXT = (
    "日程可以这样用：\n"
    "- 「日程 明天8点到9点半 高数」：记一条（默认隐私；带「公开」才对别人可答）\n"
    "- 「日程表 / 日程列表」：看排到哪儿了\n"
    "- 「日程 删 N」放下最近那次；「日程 删课 N」整个放下不再出现\n"
    "- 「日程 公开 N / 日程 隐私 N」：切换对别人的可答面\n"
    "- 「日程 导入 …」或「课表 …」：多行课表/计划整批记（周X 8:00-9:40 名称 地点 单/双；"
    "单双周要带一句「学期 2026-09-07」）\n"
    "- 「日程 每周三8点到9点40 现代史纲要 公开」：周程 + 直接对外可答\n"
    "我只按你说过的话记——不查你设备，不猜你行踪。"
)
_NEED_TIME_TEXT = "要记到什么时候呢？给我一句带时间的就好，比如「日程 明天8点到9点半 高数」。"
_NEED_SEMESTER_TEXT = (
    "这条是单双周的课，可我替你猜不了学期第一天——带上「学期 2026-09-07」再说一次就好。"
)


def build_schedule_board_capability(config: Any | None = None) -> Any:
    """构建日程板能力：返回 ``(message, decision) -> CapabilityResult | None``。

    None=不承接（例如判定与执行之间闸被关掉的窄窗），调用方（reminder 分发）
    落回既有流程，绝不吞消息。
    """

    def _result(message: IncomingMessage, body: str, *, tags: list[str]) -> CapabilityResult:
        from plugins.bot_unified_runtime.domains.render.plain_text import (
            redact_local_secrets,
        )

        return CapabilityResult(
            request_id=message.request_id,
            capability_id=CAPABILITY_ID,
            kind="text",
            title="",
            # 出站前统一打码（盘符路径/BOT_XXX=/sk- 形态）：条目正文可能被她
            # 顺手写成含本地路径的句子，泄漏面在这最后一步再收一道（设计 §5.2）。
            body=redact_local_secrets(body),
            send_policy=SendPolicy.SILENT_AUDIT,
            audit_tags=["schedule", *tags],
        )

    def _prune_quietly(store: Any) -> None:
        try:
            store.purge_terminal(before_epoch=purge_cutoff_epoch())
        except Exception:
            logger.warning("schedule board prune failed (ignored)", exc_info=True)

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult | None:
        text = (message.command_text or message.plain_text or "").strip()
        # 票1（ATK-SCHED）：板主键=平台域限定的 (域, sender_id) 人物键，
        # 唯一构造口 _board_owner_of（中央件 person_scope_key）——裸号建键的
        # 跨平台同号接管链（读[密]/翻公开/删/投毒）自此拼不出同一把键。
        owner = _board_owner_of(message)

        if is_status_question(text, config=config):
            return _handle_status_question(message, text)

        if not is_schedule_surface(text, config=config):
            return None

        if _BOARD_BARE_RE.match(text):
            return _result(message, _USAGE_TEXT, tags=["usage"])
        if _BOARD_LIST_RE.match(text):
            return _handle_list(message, owner)
        if _BOARD_DELETE_RULE_RE.match(text):
            return _handle_delete(message, owner, whole_rule=True)
        if _BOARD_DELETE_RE.match(text):
            return _handle_delete(message, owner, whole_rule=False)
        if _BOARD_VISIBILITY_RE.match(text):
            return _handle_visibility(message, owner)
        if _BOARD_IMPORT_RE.match(text):
            return _handle_import(message, owner, text)

        try:
            store, service = build_board_store(config), build_board_service(config)
        except Exception:
            logger.warning("schedule board store unavailable", exc_info=True)
            return _result(message, "这会儿日程表没接上（存储未就绪），稍后再说一次。", tags=["error"])

        # 捕获/添加腿唯一取文本口径（G4 残余①）：**不再用上面的 `text`**——
        # `text` 允许 `command_text or plain_text` 回退，可能含引用拼接体；
        # 本腿只吃 `capture_clean_text`（拒捕=None / 空文="" 一律让位，不硬接）。
        capture_text = capture_clean_text(message)
        if not capture_text:
            return None  # 诚实静默：别人的话（或无文本）不记，交回提醒/聊天原流程
        intent = parse_schedule_add(capture_text)
        if intent is None:
            if is_schedule_natural(capture_text, config=config):
                return None  # 判定与解析之间不一致（窄窗）：让位，不硬接
            return _result(message, _NEED_TIME_TEXT, tags=["need_time"])
        if intent.parity and not intent.semester_start:
            return _result(message, _NEED_SEMESTER_TEXT, tags=["need_semester"])
        if _entry_already_on_board(service, store, owner, intent):
            # 同一句说第二遍：不双记（状态只从她亲口说的话取——她说过的不重复累加）。
            return _result(
                message,
                f"这条已经记过了：{intent.activity}｜"
                f"{_display_when(intent.start_local, intent.duration_minutes)}，不重复记。",
                tags=["add_duplicate"],
            )
        intent = replace(intent, source_message_id=str(message.message_id or ""))
        try:
            line = _add_entry(service, store, owner, intent)
            _prune_quietly(store)
        except Exception as exc:  # noqa: BLE001 - 引擎拒绝（限额/冲突/坏形）如实回话，不假装记上。
            logger.warning("schedule add rejected: %s", type(exc).__name__)
            return _result(
                message,
                "这条我没能记下——时间或活动的形引擎没过校验（限额/冲突/写法），"
                "换个清楚的说法再试，如「日程 周三14:00 组会」。",
                tags=["add_rejected", f"engine:{type(exc).__name__}"],
            )
        vis_note = (
            "（已设为公开，别人问起我按分级表答）"
            if intent.public
            else "（默认只有你自己看得见；要对外可答说「日程 公开 N」）"
        )
        return _result(message, f"记上了：{line}。{vis_note}", tags=["added"])

    # ------------------------------------------------------------------ 子面

    def _handle_list(message: IncomingMessage, owner: str) -> CapabilityResult:
        try:
            store, service = build_board_store(config), build_board_service(config)
            items = list_board_items(service, store, owner)
        except Exception:
            logger.warning("schedule list failed", exc_info=True)
            return _result(message, "这会儿翻不开日程表（存储没准备好），回头再说一次。", tags=["error"])
        # 隐私自看面（G2）：无论群聊/私聊，本清单只落「序号 + 时刻 + [公]/[密] 标记」，
        # **逐字不取条目标题**——隐私条目的存在与否都只以 [密] 标记体现，标题（活动正文）
        # 结构上不进这条投影（redact 之前就没有取数路径）。注毒锁：一旦把这行改成含
        # {item.title} 的形态，[密] 条目的题面立刻出现在自看清单里 → 隐私断言当场红。
        if not items:
            return _result(
                message, "日程表还空着。想记就说「日程 明天8点到9点半 高数」。", tags=["list_empty"]
            )
        lines = [
            f"- {item.seq} {_display_when_local(item)} {'[公]' if item.public else '[密]'}"
            for item in items
        ]
        return _result(
            message,
            "你的日程（未来 30 天）：\n" + "\n".join(lines)
            + "\n（到点督促另走「X点提醒我」那条链，两边不抢。）",
            tags=["listed"],
        )

    def _handle_delete(
        message: IncomingMessage, owner: str, *, whole_rule: bool
    ) -> CapabilityResult:
        text = (message.command_text or message.plain_text or "").strip()
        match = (_BOARD_DELETE_RULE_RE if whole_rule else _BOARD_DELETE_RE).match(text)
        if match is None:
            return _result(message, "没看懂编号——「日程表」里对一下号？", tags=["delete_usage"])
        seq = next((int(g) for g in match.groups() if g), 0)
        if not seq:
            return _result(
                message, "要放下哪一条？「日程表」看编号，再说「日程 删 <编号>」。",
                tags=["delete_usage"],
            )
        try:
            store, service = build_board_store(config), build_board_service(config)
            items = list_board_items(service, store, owner)
            target = next((item for item in items if item.seq == seq), None)
            if target is None:
                return _result(message, f"日程表里没有第 {seq} 条。", tags=["delete_miss"])
            if whole_rule:
                plan = service.get_plan(target.plan_id)
                payload = plan.model_dump()
                payload["tasks"] = [t for t in payload["tasks"] if t["task_id"] != target.task_id]
                payload["rules"] = [r for r in payload["rules"] if r["rule_id"] != target.rule_id]
                store.supersede_rule(
                    target.plan_id,
                    target.rule_id,
                    _rule_revision(plan, target.rule_id),
                    now_utc=service.now(),
                )
                _resubmit(service, payload, expected_revision=plan.revision)
            else:
                outcome = service.cancel_occurrence(target.occurrence_id)
                if str(outcome.get("status")) == "not_found":
                    return _result(
                        message, "这条刚刚不在待办里了——再「日程表」看一眼？", tags=["delete_gone"]
                    )
            _prune_quietly(store)
        except Exception:
            logger.warning("schedule delete failed", exc_info=True)
            return _result(message, "这条这会儿放不下（存储没接稳），再试一次或稍后说一声。", tags=["error"])
        scope = "整条安排不再出现" if whole_rule else f"{_display_when_local(target)}那次"
        # 票2：私聊保持原题面文案逐字不变；群面折成清单腿同型指针（见 _receipt_ref）。
        return _result(
            message,
            f"好，放下了：{_receipt_ref(message, target, with_when=False)}（{scope}）。",
            tags=["deleted"],
        )

    def _handle_visibility(message: IncomingMessage, owner: str) -> CapabilityResult:
        text = (message.command_text or message.plain_text or "").strip()
        match = _BOARD_VISIBILITY_RE.match(text)
        if match is None:
            return _result(message, "要公开/隐私哪一条？「日程 公开 3」这样就好。", tags=["vis_usage"])
        words = [g for g in match.groups() if g and not g.isdigit()]
        nums = [g for g in match.groups() if g and g.isdigit()]
        if not words:
            return _result(message, "要公开/隐私哪一条？「日程 公开 <编号>」这样就好。", tags=["vis_usage"])
        if not nums:
            return _result(
                message, "要改哪一条的可见性？「日程表」看编号，再说「日程 公开 <编号>」。",
                tags=["vis_usage"],
            )
        make_public = words[0] in ("公开", "设为公开", "设成公开")
        seq = int(nums[0])
        try:
            store, service = build_board_store(config), build_board_service(config)
            items = list_board_items(service, store, owner)
            target = next((item for item in items if item.seq == seq), None)
            if target is None:
                return _result(message, f"日程表里没有第 {seq} 条。", tags=["vis_miss"])
            plan = service.get_plan(target.plan_id)
            payload = plan.model_dump()
            for task in payload["tasks"]:
                if task["task_id"] == target.task_id:
                    task["tags"] = [t for t in task["tags"] if t != VIS_PUBLIC] + (
                        [VIS_PUBLIC] if make_public else []
                    )
            _resubmit(service, payload, expected_revision=plan.revision)
            store.retag_future_occurrences(
                target.plan_id,
                target.rule_id,
                public=make_public,
                after_epoch=service.now().timestamp(),
            )
        except Exception:
            logger.warning("schedule visibility failed", exc_info=True)
            return _result(message, "这一档这会儿改不动（存储没接稳），稍后再说一次。", tags=["error"])
        # 票2：语境门同上（_receipt_ref）——只有私聊回执带原题面，其余形态折指针。
        if make_public:
            body = (
                f"好，「{_receipt_ref(message, target)}」对别人可答了：只说在做什么和几点到几点，"
                "地点与你写下的其余字不出口。"
            )
        else:
            body = (
                f"好，「{_receipt_ref(message, target)}」收回隐私档——别人问起，我只会说你有事情。"
            )
        return _result(message, body, tags=["visibility", "public" if make_public else "private"])

    def _handle_import(message: IncomingMessage, owner: str, text: str) -> CapabilityResult:
        match = _BOARD_IMPORT_RE.match(text)
        trailing = (match.group(1) or "").strip() if match else ""
        image_refs = _image_refs(message)
        if image_refs:
            # 图片优先（她发图说「课表」；附带的文字按学期先验喂给识别，不双路重复记）
            return _import_image(message, owner, text, image_refs)
        if trailing:
            return _import_text(message, owner, trailing)
        return _result(
            message,
            "把课表/计划文本连着「日程 导入」发来就好，一行一条：\n"
            "周X 8:00-9:40 名称 地点 单/双；单双周请带一句「学期 2026-09-07」。"
            "发图片课表也行——图我只在你发来这一刻读，不存不扫。",
            tags=["import_usage"],
        )

    def _import_text(message: IncomingMessage, owner: str, block: str) -> CapabilityResult:
        semester_match = _SEMESTER_RE.search(block)
        semester = semester_match.group(1) if semester_match else None
        parsed: list[tuple[int, datetime, int, str, str, str | None]] = []
        rejected = 0
        for line in [ln for ln in block.splitlines() if ln.strip()][:_MAX_IMPORT_LINES]:
            line = line.strip()
            if not line or _SEMESTER_RE.search(line):
                continue
            item = _parse_import_line(line)
            if item is None:
                rejected += 1
                continue
            parsed.append(item)
        if not parsed:
            return _result(
                message,
                f"这份里我一行都没能读实（要「周X 8:00-9:40 名称」这种带时刻的行）{'' if not rejected else f'（{rejected} 行没读实）'}。"
                "给我文本版就好——我不猜节次表。",
                tags=["import_empty"],
            )
        if any(p[5] for p in parsed) and not semester:
            return _result(
                message,
                "这份课表里有单双周，可我替你猜不了学期第一天——"
                "首行加一句「学期 2026-09-07」再导入一次（引擎禁猜口径，宁可多问不编日期）。",
                tags=["import_clarify"],
            )
        try:
            store, service = build_board_store(config), build_board_service(config)
        except Exception:  # noqa: BLE001
            return _result(message, "这会儿日程表没接上（存储未就绪），稍后再发一次。", tags=["error"])
        added, failed = _commit_entries(service, store, owner, parsed, semester, message)
        _prune_quietly(store)
        tail = f"（{failed + rejected} 行没读实，原样发来我再看）" if (failed or rejected) else ""
        if added == 0 and not failed:
            return _result(
                message, f"这份和板上已有的完全重复，没有新增。{tail}",
                tags=["imported_dedup"],
            )
        return _result(
            message,
            f"这份记下了 {added} 条，都先按隐私存着——要对外可答的说「日程 公开 N」。{tail}",
            tags=["imported"],
        )

    def _import_image(
        message: IncomingMessage, owner: str, text: str, refs: list[str]
    ) -> CapabilityResult:
        """图片课表：她这条消息触发识图（信息源硬边界——不主动扫设备找课表）。"""
        semester_match = _SEMESTER_RE.search(text)
        try:
            from plugins.bot_unified_runtime.domains.schedule.timetable import (
                build_timetable_provider,
                recognize_timetable,
            )

            provider = build_timetable_provider(config)
            draft = recognize_timetable(
                provider,
                refs,
                semester_start=semester_match.group(1) if semester_match else None,
            )
        except Exception:
            logger.warning("timetable recognize failed", exc_info=True)
            return _result(
                message, "这张图这会儿没读成——识图后端没接稳，把课表文字发我也行。",
                tags=["recognize_error"],
            )
        issues = draft.missing_clarifications()
        if issues:
            return _result(
                message,
                "图我看了，先对两件事（不替你猜）：\n- " + "\n- ".join(issues[:2]),
                tags=["recognize_clarify"],
            )
        if not draft.courses:
            return _result(
                message,
                "这张图里我没认出课程——是课表的话发清楚一点的图，或直接发文字版。",
                tags=["recognize_empty"],
            )
        try:
            store, service = build_board_store(config), build_board_service(config)
        except Exception:  # noqa: BLE001
            return _result(message, "这会儿日程表没接上（存储未就绪），稍后再发一次。", tags=["error"])
        parsed: list[tuple[int, datetime, int, str, str, str | None]] = []
        for course in draft.courses:
            start_minute = _hhmm_to_minute_pair(course.start_time, course.end_time)
            if start_minute is None:
                continue
            anchor, duration = start_minute
            parts = re.split(r"\s+", str(course.course_name).strip(), maxsplit=1)
            parsed.append(
                (
                    course.weekday,
                    anchor,
                    duration,
                    parts[0][:40],
                    parts[1].strip()[:40] if len(parts) > 1 else "",
                    course.week_parity if course.week_parity in ("odd", "even") else None,
                )
            )
        semester = draft.semester_start or (semester_match.group(1) if semester_match else None)
        if any(p[5] for p in parsed) and not semester:
            return _result(
                message,
                "图里有单双周的课，学期第一天我猜不了——回一句「学期 2026-09-07」再发一次图。",
                tags=["recognize_clarify"],
            )
        added, failed = _commit_entries(service, store, owner, parsed, semester, message)
        _prune_quietly(store)
        tail = f"（{failed} 条没落上）" if failed else ""
        return _result(
            message,
            f"图里的课表记下 {added} 条，都按隐私存着，重复发同一张不双记{tail}。"
            "要哪门对外可答，说「日程 公开 N」。",
            tags=["recognized_imported"],
        )

    def _commit_entries(
        service: Any,
        store: Any,
        owner: str,
        parsed: list[tuple[int, datetime, int, str, str, str | None]],
        semester: str | None,
        message: IncomingMessage,
    ) -> tuple[int, int]:
        """(weekday, 日内锚, duration, 标题, 地点, parity) 批 → 板子；同标题同星期同时刻去重。"""
        existing = list_board_items(service, store, owner) if store.plan_id_for_owner(owner) else []
        known = {
            (item.title, item.start_local.weekday(), item.start_local.strftime("%H:%M"))
            for item in existing
        }
        added = failed = 0
        for weekday, anchor, duration, title, location, parity in parsed:
            # 票3（ATK-SCHED）：导入腿（文本行/识图草稿）同走入库即净——课表行的名称段
            # 是 `.+?` 宽取，识图标题来自外部模型输出（二手材料），两者都可能在
            # 题面里带内部边界标记字面；消毒与板存/去重指纹共用这一份净形（幂等比对
            # 的 signature 必须取净题面，否则重发同一张表会因口径分叉而双记）。
            title = _neutralize_entry_title(title)
            signature = (title, weekday, anchor.strftime("%H:%M"))
            if signature in known:
                continue  # 幂等：同一份课表重发不双记（引擎之外的板级去重，指纹同 timetable）
            start = _next_weekday_datetime(anchor, weekday)
            if start is None:
                failed += 1
                continue
            intent = ScheduleAddIntent(
                start_local=start,
                # 题面消毒在循环头（title 已是净形，见上）——此处不再二次调用。
                activity=title,
                duration_minutes=duration,
                public=False,  # 导入 ≠ 公开：公开是她对外的单独决定（设计 §2.2）
                weekly_weekday=weekday,
                parity=parity,
                semester_start=semester,
                location=location,
                source_message_id=str(message.message_id or ""),
            )
            try:
                _add_entry(service, store, owner, intent)
                known.add(signature)
                added += 1
            except Exception:  # noqa: BLE001 - 单条坏不拖垮整批
                failed += 1
        return added, failed

    def _handle_status_question(message: IncomingMessage, text: str) -> CapabilityResult:
        """代答腿主入口（分级表实现 = ``_project_answer`` 一处，判据不再分散）。"""
        if _is_first_person_question(text):
            # 她亲口问自己：只答会话所有者本人的板子，不外溢去猜别的超管（G1）。
            # 票1：候选与板腿同键形（平台域限定），裸号桶不再互相认领。
            owner_key = _board_owner_of(message)
            owners = (
                [owner_key]
                if owner_key
                else [_board_owner_from_roster_id(x) for x in resolve_status_owners(config, text)]
            )
        else:
            # 第三人称：配置名单里的号折成板主键（裸号=QQ 原生域，与 roles 名单裁定同尺）。
            owners = [
                _board_owner_from_roster_id(x) for x in resolve_status_owners(config, text)
            ]
        try:
            store, service = build_board_store(config), build_board_service(config)
        except Exception:
            logger.warning("schedule status store unavailable", exc_info=True)
            return _result(
                message, _pick_fallback(message.request_id), tags=["answer_error"]
            )
        rows: list[tuple[str, str, list[BoardItem], str | None]] = []
        for owner_id in owners:
            tier = asker_tier(message, owner_id)
            # G2(a)：先问窗——解得出未来窗走 window_entries，解不出（含非窗问句、
            # 窗落今天/过去）回退 active_entries 现在腿，现在腿行为逐字不变。
            windowed = window_entries(service, store, owner_id, text)
            if windowed is None:
                rows.append((owner_id, tier, active_entries(service, store, owner_id), None))
            else:
                # 局部名与下面解包的 `label: str | None` 分开：同名会让
                # mypy 把窄化后的 str 当成声明型，解包处判成不兼容赋值。
                window_label, window_items = windowed
                rows.append((owner_id, tier, window_items, window_label))
        # 只有「窗内/此刻可答且公开」（或本人 owner 档）的对象才可答；谁都不可答 → 模糊句。
        answerable = [
            (owner_id, tier, items, label)
            for owner_id, tier, items, label in rows
            if tier == "owner" or any(item.public for item in items)
        ]
        if not answerable:
            # 空表与全隐私表同一句——条目缺席不是证据（设计 §5.2 铁律）。
            return _result(
                message, _pick_fallback(message.request_id), tags=["answer_fallback"]
            )
        if len({owner_id for owner_id, _tier, _items, _label in answerable}) > 1:
            # 多位超管同时可答：绝不猜人，回模糊句（要指名道姓问）。
            return _result(
                message,
                _pick_fallback(message.request_id + "|multi"),
                tags=["answer_ambiguous_owner"],
            )
        owner_id, tier, items, label = answerable[0]
        body = _project_answer(
            message, tier, items, fallback_seed=message.request_id, when_label=label
        )
        return _result(
            message, body, tags=["answered", tier] + (["window"] if label else [])
        )

    return capability


# ---------------------------------------------------------------------------
# 小工具（展示/解析共用）
# ---------------------------------------------------------------------------


def _display_when_local(item: BoardItem) -> str:
    weekday = "一二三四五六日"[item.start_local.weekday()]
    base = f"周{weekday} {item.start_local:%H:%M}"
    if item.duration_minutes:
        end = (item.start_local + timedelta(minutes=item.duration_minutes)).strftime("%H:%M")
        base += f"–{end}"
    return base


def _receipt_ref(
    message: IncomingMessage, target: BoardItem, *, with_when: bool = True
) -> str:
    """删除/可见性回执的条目指针（票2 ATK-SCHED，S-FIX-ATK-SCHED2）。

    病根：G2 把清单收成「时刻+[公]/[密]」、代答纪律「完整日程只私聊对本人讲」，
    但删除/可见性回执不分群聊私聊，逐字复述**默认隐私条目**的题面（就诊/复诊类）
    ——群里做一次管理动作＝全群当场看见隐私题面（探针 ATKSCHED-2）。

    语境门判据与收件箱域 daily_assist `_may_read_inbox`（S-FIX-SCHED20-H4）**同源
    同尺**：str Enum 等值判 `session_type`，语境缺失按非私聊判（fail-closed）——
    不是群才收，是**只有私聊**才给原题面。私聊文案逐字不变，其余会话形态折成
    与清单腿同型的「第 N 条（时刻）」指针（题面在取数前就没有通路）。

    ``with_when=False`` 供删除腿用：那里的 ``scope`` 尾巴已带时刻，指针只落编号
    不重复报时（文案守岸人语气，不为省字吞信息）。
    """
    if getattr(message, "session_type", None) == SessionType.PRIVATE:
        return str(target.title)
    if with_when:
        return f"第 {target.seq} 条（{_display_when_local(target)}）"
    return f"第 {target.seq} 条"


def _rule_revision(plan: Any, rule_id: str) -> int:
    rule = next((r for r in plan.rules if r.rule_id == rule_id), None)
    return int(rule.rule_revision) if rule else 1


def _parse_import_line(
    line: str,
) -> tuple[int, datetime, int, str, str, str | None] | None:
    """一行课表 → (weekday, 日内锚(1970 基), duration, 标题, 地点, parity)；读不实 None。"""
    match = _IMPORT_LINE_RE.match(line)
    if match is None:
        return None
    weekday = _WEEKDAY_VALUE.get(match.group(1))
    if weekday is None:
        return None
    sh, sm, eh, em, name = (
        match.group(2), match.group(3), match.group(4), match.group(5), match.group(6),
    )
    try:
        start_hour, end_hour = int(sh), int(eh)
        start_minute = 30 if sm == "半" else (int(sm) if sm else 0)
        end_minute = 30 if em == "半" else (int(em) if em else 0)
    except ValueError:
        return None
    if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59):
        return None
    if not (0 <= end_hour <= 23 and 0 <= end_minute <= 59):
        return None
    # 1970 只是承载日内时刻的占位日期；真缺陷是"naive 锚被混了本机 UTC 偏移"
    # （台账 #29★/#6★），不是"必须豁免"。两枚挂 tzinfo=UTC＝复用本域既有
    # `datetime.now(UTC)` 那把尺，不新建第二套时区尺：(end - anchor) 同为 UTC，
    # 当日差值不变；`_next_weekday_datetime` 只读 .hour/.minute 整数（candidate
    # 由已 aware 的 `today` 构造，落配置时区仍只在那一处发生）⇒ 行为逐字不变。
    anchor = datetime(1970, 1, 1, start_hour, start_minute, tzinfo=UTC)
    end = datetime(1970, 1, 1, end_hour, end_minute, tzinfo=UTC)
    duration = max(0, int((end - anchor).total_seconds() // 60))
    parity_raw = match.group(7)
    parts = re.split(r"\s+", name.strip(), maxsplit=1)
    title = parts[0][:40]
    location = parts[1].strip()[:40] if len(parts) > 1 else ""
    parity = ("odd" if parity_raw == "单" else "even") if parity_raw else None
    return (weekday, anchor, duration, title, location, parity)


def _hhmm_to_minute_pair(
    start_time: str | None, end_time: str | None
) -> tuple[datetime, int] | None:
    """识图课程 (HH:MM, HH:MM) → (1970 锚, duration)；缺时刻=None（该条不入库，不猜）。"""
    try:
        sh, sm = (int(x) for x in str(start_time).split(":"))
        eh, em = (int(x) for x in str(end_time).split(":"))
    except (TypeError, ValueError):
        return None
    if not (0 <= sh <= 23 and 0 <= sm <= 59 and 0 <= eh <= 23 and 0 <= em <= 59):
        return None
    # 同族（见 _parse_import_line）：1970 只承载时分，挂 tzinfo=UTC 复用本域
    # `datetime.now(UTC)` 那把尺；落配置时区只在 `_next_weekday_datetime` 一处，此处不第二套尺。
    anchor = datetime(1970, 1, 1, sh, sm, tzinfo=UTC)
    end = datetime(1970, 1, 1, eh, em, tzinfo=UTC)
    duration = max(0, int((end - anchor).total_seconds() // 60))
    return anchor, duration


def _next_weekday_datetime(anchor: datetime, weekday: int) -> datetime | None:
    """日内锚（1970）+ 周几 → 配置时区下一个该周几的时刻（含今天，已过点跳下周）。"""
    try:
        zone = ZoneInfo(configured_timezone())
    except Exception:  # noqa: BLE001
        return None
    today = datetime.now(zone)
    delta = (weekday - today.weekday()) % 7
    candidate = (today + timedelta(days=delta)).replace(
        hour=anchor.hour, minute=anchor.minute, second=0, microsecond=0
    )
    if candidate <= today:
        candidate += timedelta(days=7)
    return candidate


def _image_refs(message: IncomingMessage) -> list[str]:
    refs: list[str] = []
    for segment in message.raw_segments or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).lower() not in ("image", "animation"):
            continue
        data = segment.get("data") or {}
        url = str(data.get("url") or "").strip()
        local = str(data.get("file") or data.get("path") or "").strip()
        if url or local:
            refs.append(url or local)
        if len(refs) >= 2:
            break
    return refs


__all__ = [
    "VIS_PUBLIC",
    "build_schedule_board_capability",
    "classify_schedule_activity",
    "is_schedule_command",
    "is_schedule_natural",
    "is_schedule_surface",
    "is_status_question",
    "natural_capture_enabled",
    "parse_schedule_add",
    "schedule_feature_enabled",
    "status_reply_enabled",
]

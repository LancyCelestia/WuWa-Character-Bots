"""时间窗总结意图解析（基层确定性纯函数，不调大模型、不发网络）。

识别「总结一下5分钟内的消息 / 总结2小时内的聊天 / 总结一下今天群里的
聊天 / 总结一下最近20条消息 / 帮我总结一下」这类请求，归一化成时间窗
(since_epoch, until_epoch, 描述)。规则刻意保守：

- 必须出现「总结/归纳/汇总」强动作词才可能命中，普通叙述不触发；
- 出现「文章/新闻/视频」等内容宾语时让路——那是让 bot 总结内容，
  不是总结聊天记录；
- 含 http 链接时整体不命中（链接解析优先，与自然语言层同口径）；
- 无时间词时仅接受「(帮我)总结一下…」起始的纯总结请求，默认 30 分钟窗。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

DEFAULT_WINDOW_MINUTES = 30

# 总结触发词（简繁；「梳理」留给识图看图意图门控，避免双通道抢占）。
_SUMMARY_TRIGGER = r"(?:总结|總結|归纳|歸納|汇总|彙總|彙整)(?:一下|下)?"
_SUMMARY_TRIGGER_RE = re.compile(_SUMMARY_TRIGGER)

# 无时间词时的锚定形态：礼貌前缀/把字头 + 触发词 + 短宾语，无标点续句。
_POLITE_PREFIX = r"(?:帮我|幫我|麻烦|麻煩|请你?|請你?|给我|給我|我想)?"
_ANCHORED_SUMMARY_RE = re.compile(
    rf"^{_POLITE_PREFIX}(?:把|將)?{_SUMMARY_TRIGGER}[^，。！？!?]{{0,12}}$"
)

# 内容宾语守卫：总结的是内容而非聊天记录时让路。
_FORBIDDEN_OBJECT_RE = re.compile(
    r"(?:文章|新闻|新聞|论文|論文|视频|視頻|影片|课文|課文|课件|課件|课本|課本|"
    r"剧情|劇情|大纲|大綱|PPT|ppt|这本书|這本書)"
)

# 数字：阿拉伯数字 + 高频汉字数词（一/两/三/五）；「半」单独成词。
_NUM = r"(?:\d{1,4}|一|两|兩|三|五)"
_NUM_MAP = {"一": 1, "两": 2, "兩": 2, "三": 3, "五": 5}
_MINUTES_RE = re.compile(rf"({_NUM})\s*(?:个|個)?\s*(?:分钟|分鐘|min(?:ute)?s?)")
_HOURS_RE = re.compile(rf"({_NUM})\s*(?:个|個)?\s*(?:小时|小時|钟头|鐘頭|hours?|hrs?)")
_HALF_HOUR_RE = re.compile(r"半\s*(?:个|個)?\s*(?:小时|小時|钟头|鐘頭|钟|鐘)")
_TODAY_RE = re.compile(r"(?:今天|今日)")
_RECENT_N_RE = re.compile(r"(?:最近|近|剛才|刚才|刚)\s*(\d{1,4})\s*(?:条|條|句|則|则|发言|發言)")


@dataclass(frozen=True)
class TimeWindowSpec:
    """解析出的时间窗：[since_epoch, until_epoch] + 人读描述。"""

    since_epoch: float
    until_epoch: float
    description: str
    # >0 = 「最近N条」条数上限；0 = 不限条数（走调用方默认）。
    max_turns: int = 0


def _num_to_int(raw: str) -> int:
    if raw in _NUM_MAP:
        return _NUM_MAP[raw]
    return int(raw)


def _local_midnight_epoch(now_epoch: float) -> float:
    """「今天」= 本地时区当日 0 点（与 cron/调度同用系统本地时区口径）。"""
    local_tz = datetime.now().astimezone().tzinfo or UTC
    local_now = datetime.fromtimestamp(now_epoch, tz=local_tz)
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def parse_time_window(
    text: str, *, now_epoch: float | None = None
) -> TimeWindowSpec | None:
    """从文本抓时间窗表达（N分钟/N小时/半小时/今天/最近N条）；无命中返回 None。

    支持「1小时30分钟」复合表达（取和）；同时出现多种表达时取最靠前的。
    """
    now = float(now_epoch) if now_epoch is not None else datetime.now(UTC).timestamp()
    hour_match = _HOURS_RE.search(text)
    minute_match = _MINUTES_RE.search(text)
    if (
        hour_match is not None
        and minute_match is not None
        and minute_match.start() >= hour_match.end()
        and len(text[hour_match.end() : minute_match.start()]) <= 2
    ):
        # 复合「N小时M分钟」：分钟表达紧跟小时表达时取和。
        total = _num_to_int(hour_match.group(1)) * 60 + _num_to_int(minute_match.group(1))
        return TimeWindowSpec(
            since_epoch=now - total * 60,
            until_epoch=now,
            description=f"最近{hour_match.group(1)}小时{minute_match.group(1)}分钟",
        )
    if minute_match is not None and (
        hour_match is None or minute_match.start() < hour_match.start()
    ):
        minutes = _num_to_int(minute_match.group(1))
        return TimeWindowSpec(
            since_epoch=now - minutes * 60,
            until_epoch=now,
            description=f"最近{minute_match.group(1)}分钟",
        )
    if hour_match is not None:
        hours = _num_to_int(hour_match.group(1))
        return TimeWindowSpec(
            since_epoch=now - hours * 3600,
            until_epoch=now,
            description=f"最近{hour_match.group(1)}小时",
        )
    half = _HALF_HOUR_RE.search(text)
    if half is not None:
        return TimeWindowSpec(
            since_epoch=now - 30 * 60,
            until_epoch=now,
            description="最近半小时",
        )
    recent = _RECENT_N_RE.search(text)
    if recent is not None:
        count = int(recent.group(1))
        if count > 0:
            return TimeWindowSpec(
                since_epoch=0.0,
                until_epoch=now,
                description=f"最近{recent.group(1)}条",
                max_turns=count,
            )
    if _TODAY_RE.search(text) is not None:
        midnight = _local_midnight_epoch(now)
        return TimeWindowSpec(
            since_epoch=midnight,
            until_epoch=now,
            description="今天",
        )
    return None


def detect_time_window_summary(
    text: str, *, now_epoch: float | None = None
) -> TimeWindowSpec | None:
    """检测「总结一段时间聊天」意图；命中返回时间窗，未命中返回 None。

    两条命中路径：
    - 时间表达路径：触发词 + 时间表达同现（时间词可在任意位置）；
    - 默认路径：整句是「(帮我)总结一下…」起始的纯总结请求 → 默认 30 分钟。
    """
    stripped = (text or "").strip()
    if not stripped or "http://" in stripped or "https://" in stripped:
        return None
    if _FORBIDDEN_OBJECT_RE.search(stripped):
        return None
    trigger = _SUMMARY_TRIGGER_RE.search(stripped)
    if trigger is None:
        return None
    now = float(now_epoch) if now_epoch is not None else datetime.now(UTC).timestamp()
    window = parse_time_window(stripped, now_epoch=now)
    if window is not None:
        return window
    if _ANCHORED_SUMMARY_RE.match(stripped) is not None:
        return TimeWindowSpec(
            since_epoch=now - DEFAULT_WINDOW_MINUTES * 60,
            until_epoch=now,
            description=f"最近{DEFAULT_WINDOW_MINUTES}分钟",
        )
    return None

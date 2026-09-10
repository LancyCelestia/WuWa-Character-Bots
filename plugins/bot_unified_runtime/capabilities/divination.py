"""占卜能力（bot.divination）：八字排盘 / 塔罗牌 / 六十四卦金钱卦。

纯本地计算，无网络、无外部数据。按用户文本分子意图：

- 八字/排盘/四柱/命盘/算命/生辰 → 八字排盘；可从文本解析出生
  日期时间（如「1998年3月2日早上7点」），只给日期不具体到时辰时
  按午时（12:00）排；完全没给日期按当前时点排并附用法提示。
- 塔罗/抽塔罗/塔罗牌 → 塔罗：「每日一抽/今日塔罗」按 (日期, 用户)
  哈希确定同日同牌；带「三张/过去/未来/牌阵」走三张牌阵；
  否则单张指引。
- 占卜/起卦/算卦/摇卦/六十四卦/金钱卦 → 金钱卦。

能力只返回 ``CapabilityResult``（kind="divination"），不直接发送；
人格化包装、渲染与发送由管线统一处理。输出为娱乐向文本并附免责
尾注，不含医疗/投资等严肃建议。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
)
from plugins.bot_unified_runtime.sources.ganzhi import (
    CST,
    bazi_chart,
    format_bazi_text,
)
from plugins.bot_unified_runtime.sources.iching import (
    cast_hexagram,
    format_cast_text,
)
from plugins.bot_unified_runtime.sources.tarot import (
    daily_card,
    format_single_text,
    format_three_text,
    single_guidance,
    three_card_spread,
)

__all__ = [
    "DivinationIntent",
    "build_divination_capability",
    "parse_divination_intent",
]

_BAZI_RE = re.compile(r"八字|排盘|四柱|命盘|算命|生辰")
_TAROT_RE = re.compile(r"塔罗")
_TAROT_DAILY_RE = re.compile(r"每日一抽|每日一簽|每日一签|今日塔罗|今日塔羅|今天塔罗")
_TAROT_THREE_RE = re.compile(r"三张|三張|过去现在未来|過去現在未來|牌阵|牌陣")
_ICHING_RE = re.compile(r"占卜|起卦|算卦|搖卦|摇卦|六十四卦|金錢卦|金钱卦|掷卦|擲卦")

# 出生日期：「1998年3月2日」「1998-03-02」「1998/3/2」。
_DATE_RE = re.compile(
    r"(?P<year>\d{4})[年\-/.](?P<month>\d{1,2})[月\-/.](?P<day>\d{1,2})[日号]?"
)
# 时辰词与时刻：「早上7点」「晚上9点05分」「21:51」「早上7点半」。
_PERIOD_RE = re.compile(r"早上|上午|中午|下午|傍晚|晚上|夜里|深夜|凌晨")
_TIME_RE = re.compile(r"(?P<hour>\d{1,2})[点时:：]\s*(?:(?P<minute>\d{1,2})分|半)?")

_BAZI_HINT = "提示：带上出生时间可以排得更准，例如「八字 1998年3月2日早上7点」。"


@dataclass(frozen=True)
class DivinationIntent:
    """占卜子意图解析结果。"""

    kind: str  # "bazi" | "tarot" | "iching"
    target: str = ""  # tarot: "single" | "three" | "daily"
    when: datetime | None = None  # bazi 解析出的时点；None=用当前时间
    date_given: bool = False  # 用户是否显式给了日期
    error: str = ""  # 日期解析失败时的用户可读提示


def _apply_period(hour: int, period: str) -> int:
    """按时辰词归一化小时（24 小时制）。

    下午/傍晚/晚上/夜里/深夜：小于 12 加 12，「晚上12点」按午夜 0 点；
    凌晨：「凌晨12点」按 0 点；早上/上午原样；中午按正午 12 点带 12。
    """
    if period in ("下午", "傍晚", "晚上", "夜里", "深夜"):
        return 0 if hour == 12 else (hour + 12 if hour < 12 else hour)
    if period == "凌晨":
        return 0 if hour == 12 else hour
    if period == "中午":
        return hour if hour >= 12 else hour + 12
    return hour


def _parse_bazi_when(text: str) -> tuple[datetime | None, bool, str]:
    """从文本解析出生时点：返回 (时点|None, 是否给了日期, 错误提示)。"""
    date_match = _DATE_RE.search(text)
    if date_match is None:
        return None, False, ""
    year = int(date_match.group("year"))
    month = int(date_match.group("month"))
    day = int(date_match.group("day"))
    # 只给日期不具体到时辰时按午时（12:00）排，传统排盘的通行默认。
    hour, minute = 12, 0
    after = text[date_match.end():]
    before = text[: date_match.start()]
    time_match = _TIME_RE.search(after) or _TIME_RE.search(before)
    if time_match is not None:
        window = after if time_match.string is after else before
        period_match = _PERIOD_RE.search(
            window[max(time_match.start() - 6, 0): time_match.end()]
        )
        hour = int(time_match.group("hour"))
        minute = int(time_match.group("minute") or 0)
        if period_match is not None:
            hour = _apply_period(hour, period_match.group(0))
    try:
        return datetime(year, month, day, hour, minute, tzinfo=CST), True, ""
    except ValueError as exc:
        return None, True, f"这个日期好像不太对（{exc}），检查一下再试试？"


def parse_divination_intent(text: str) -> DivinationIntent | None:
    """把用户文本解析成占卜子意图；不属于占卜域返回 None。

    日期解析失败时仍返回意图（kind=bazi），``error`` 带用户可读提示，
    由能力层优雅回复而不是静默忽略。
    """
    stripped = (text or "").strip()
    if not stripped:
        return None

    if _BAZI_RE.search(stripped):
        when, date_given, error = _parse_bazi_when(stripped)
        return DivinationIntent(
            kind="bazi", when=when, date_given=date_given, error=error
        )

    if _TAROT_RE.search(stripped):
        if _TAROT_DAILY_RE.search(stripped):
            return DivinationIntent(kind="tarot", target="daily")
        if _TAROT_THREE_RE.search(stripped):
            return DivinationIntent(kind="tarot", target="three")
        return DivinationIntent(kind="tarot", target="single")

    if _ICHING_RE.search(stripped):
        return DivinationIntent(kind="iching")

    return None


_DIVINATION_COMMAND_RE = re.compile(r"八字|排盘|四柱|命盘|算命|塔罗|占卜|起卦|算卦|摇卦|六十四卦")


def is_divination_command(text: str) -> bool:
    """显式玄学触发词（娱乐向）；不用泛化词，避免误伤普通对话。"""
    return bool(_DIVINATION_COMMAND_RE.search((text or "").strip()))


def build_divination_capability(config: Any | None = None) -> Any:
    """构建占卜能力：与 eat 等能力一致，返回 (message, decision) -> 结果。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        intent = parse_divination_intent(message.plain_text or "")
        if intent is None:  # pragma: no cover - 路由命中后才进入，理论不可达
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.divination",
                kind="divination",
                body="想试试八字排盘、塔罗或金钱卦吗？直接说「塔罗」「占卜」或「排盘」。",
                audit_tags=["capability:divination", "divination:noop"],
            )
        tags = ["capability:divination", f"divination:{intent.kind}"]
        try:
            if intent.kind == "bazi":
                if intent.error:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.divination",
                        kind="divination",
                        title="八字排盘",
                        body=f"{intent.error}\n{_BAZI_HINT}",
                        audit_tags=[*tags, "divination:invalid_date"],
                    )
                when = intent.when if intent.when is not None else (
                    message.timestamp.astimezone(CST)
                )
                chart = bazi_chart(when)
                body = format_bazi_text(chart)
                if not intent.date_given:
                    body = f"{body}\n（未带出生时间，按当前时点排盘。{_BAZI_HINT}）"
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.divination",
                    kind="divination",
                    title="八字排盘",
                    body=body,
                    audit_tags=tags,
                )
            if intent.kind == "tarot":
                if intent.target == "daily":
                    local_day = message.timestamp.astimezone(CST).date()
                    drawn = daily_card(local_day, message.sender_id or "anonymous")
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.divination",
                        kind="divination",
                        title="今日塔罗",
                        body=(
                            f"☀️ {local_day.isoformat()} 的每日一抽（今天全天不变哦）：\n\n"
                            f"{format_single_text(drawn)}"
                        ),
                        audit_tags=[*tags, "divination:daily"],
                    )
                rng = random.Random()
                if intent.target == "three":
                    spread = three_card_spread(rng)
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.divination",
                        kind="divination",
                        title="塔罗三张牌阵",
                        body=format_three_text(spread),
                        audit_tags=[*tags, "divination:three"],
                    )
                drawn = single_guidance(rng)
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.divination",
                    kind="divination",
                    title="塔罗指引",
                    body=format_single_text(drawn),
                    audit_tags=tags,
                )
            cast = cast_hexagram(random.Random())
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.divination",
                kind="divination",
                title="金钱卦",
                body=format_cast_text(cast),
                audit_tags=[*tags, "divination:cast"],
            )
        except ValueError as exc:
            # 超出支持区间等计算错误：优雅降级为提示，不抛给管线。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.divination",
                kind="divination",
                title="占卜",
                body=(
                    f"这个时点超出了可排盘的范围（{exc}），"
                    "换个 1900-2100 年之间的时间试试？"
                ),
                audit_tags=[*tags, "divination:out_of_range"],
            )

    return capability

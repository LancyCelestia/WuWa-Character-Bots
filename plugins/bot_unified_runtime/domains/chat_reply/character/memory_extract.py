"""从单轮对话中抽取用户事实并写入记忆库。

写入侧此前完全缺失：检索器与注入管线都在，但没有任何代码调用
``upsert_fact``，记忆库始终为空。本模块补上“回复后后台抽取”这一环：
用轻量 LLM 调用从用户消息与回复中提取值得长期记住的事实，去重后入库。
抽取只发生在后台线程，任何失败都不影响主回复链路。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
    build_fact_id,
)

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM_PROMPT = (
    "你是聊天记忆抽取器。从对话交换中提取值得长期记住的、关于用户本人的事实："
    "身份、偏好、约定、重要经历、稳定的情感倾向。\n"
    "规则：只输出事实条目，每行一条，每条不超过60字，最多3条；"
    "只记稳定信息，不记寒暄和一次性话题；"
    "不记对 AI 工具/机器人/模型的评价与使用偏好（那是对工具的吐槽，不是用户本人）；"
    "不记临时情绪、玩笑、抽象观点、当下正在讨论的话题本身；"
    "没有值得记住的内容时只输出一个字：无"
)
_FACT_LINE_PREFIX = re.compile(r"^[\s\-—•·*>)）\]】\d+ [.、)）]*\s*")
_NO_FACT_MARKERS = {"无", "没有", "没有。", "无。", "none", "n/a"}
_MAX_FACT_CHARS = 120
# F16（2026-09-12 实弹反馈⑯）：LLM 抽取曾把「用户对AI推理速度慢敏感」「用过
# 名为QQ的AI工具」这类工具吐槽当事实入库。提示词硬化之外再设确定性闸：
# 命中工具谈资关键词的一律不入库（宁可漏记，不可记琐事）。
_TRIVIAL_FACT_RE = re.compile(
    r"(AI工具|AI应用|人工智能工具|大模型|模型|机器人|多智能体|识图|推理速度|"
    r"理解偏差|重复回复|响应慢|使用过名为|偏好免费)",
    re.IGNORECASE,
)


def _is_trivial_fact(line: str) -> bool:
    return bool(_TRIVIAL_FACT_RE.search(line))


def extract_memory_texts(
    llm_provider: Any,
    *,
    user_text: str,
    reply_text: str,
    max_facts: int = 3,
    generation_options: dict[str, Any] | None = None,
) -> list[str]:
    """调用 LLM 抽取事实条目；返回裁剪、去重后的文本列表。"""
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"用户消息：{_clip(user_text, 400)}\n回复：{_clip(reply_text, 400)}"
            ),
        },
    ]
    options = {"max_tokens": 200, "temperature": 0.1, **(generation_options or {})}
    reply = llm_provider.generate(messages, **options)
    text = str(getattr(reply, "text", "") or "")
    facts: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = _FACT_LINE_PREFIX.sub("", raw_line.strip())
        if not line or line.lower() in _NO_FACT_MARKERS:
            continue
        line = _clip(line, _MAX_FACT_CHARS)
        key = line.lower()
        if key in seen:
            continue
        if _is_trivial_fact(line):
            continue  # F16 工具谈资/琐事不入库
        seen.add(key)
        facts.append(line)
        if len(facts) >= max_facts:
            break
    return facts


def store_extracted_memories(
    repository: Any,
    *,
    subject_user_id: str,
    session_id: str,
    texts: list[str],
) -> int:
    """把抽取结果写入记忆库；单条失败只记录日志，不中断其余条目。

    来源声明为 ``derived``（单轮顺手记的，可靠度低于本人亲口说与夜间归纳）。
    总线开着时 ``repository`` 自带总线（装配点传 ``bus=``，见 WP6 交接段），
    ``upsert_fact`` 因此落进总线并交由「确认/矛盾/直插」裁决——同一事实被反复
    抽出只会累加印证次数，不再像旧库那样靠 fact_id 静默覆盖。
    """
    stored = 0
    for text in texts:
        try:
            repository.upsert_fact(
                fact_id=build_fact_id(subject_user_id, session_id, text),
                subject_user_id=subject_user_id,
                session_id=session_id,
                memory_kind="auto",
                text=text,
                confidence=0.6,
                source="llm_extract",
                sensitivity="personal",
                provenance="derived",
            )
            stored += 1
        except Exception as exc:  # noqa: BLE001 - 记忆入库失败不应影响其他条目，也不打印敏感堆栈。
            logger.warning(
                "memory fact upsert failed type=%s subject=%s session=%s",
                type(exc).__name__,
                subject_user_id,
                session_id,
            )
    if stored:
        logger.info(
            "memory facts stored count=%d subject=%s session=%s",
            stored,
            subject_user_id,
            session_id,
        )
    return stored


def _clip(value: str, max_chars: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"


# ---------------------------------------------------------------------------
# R-进阶轨（默认关，bot_reminder_llm_extract_enabled）：轮末抽取无「提醒」
# 词的时间陈述（"中午12点要写作业"→提醒）。机制与上面的事实抽取同款：
# 同一个 LLM 客户端注入、行式输出解析、单条失败不中断；解析失败一律
# 静默丢弃，宁可漏一条也不误设一条。
# ---------------------------------------------------------------------------

_REMINDER_EXTRACT_SYSTEM_PROMPT = (
    "你是时间点提醒抽取器。找出用户消息里『打算在某个具体时间做某事』的"
    "陈述——用户没用「提醒/叫我」这类词也要抽。规则：\n"
    "1. 每行一条，格式固定为『YYYY-MM-DD HH:MM 事项』（日期与时刻、事项间"
    "用空格分隔），最多2条；\n"
    "2. 只抽有明确时间点的事；泛泛而谈（如『以后想学钢琴』）不要；\n"
    "3. 相对时间按当前时间换算成绝对时间；日期缺失默认今天，已过时刻算明天；\n"
    "4. 只抽「用户本人打算做的事」。第三方发来的通知/广告/催缴/系统提示/"
    "其他机器人发的消息一律不抽——即便里面有明确时间点（如『截至9月17日"
    "12时』『请及时缴费』『余额不足』『尊敬的用户』）；\n"
    "5. 没有可抽取的内容时只输出一个字：无"
)
# 行式输出解析：『YYYY-MM-DD HH:MM 事项』（兼容 | 分隔与秒段）。
_REMINDER_LINE_RE = re.compile(
    r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})(?::\d{2})?\s*[|｜,，:：]?\s*(.+)$"
)
_REMINDER_MAX_CHARS = 120

# 误记防护（2026-09-18 实弹反馈，与 F16 记忆侧 _TRIVIAL_FACT_RE 同款范式）：
# 群里其他 AI 机器人发的催缴广告（"【套餐】尊敬的用户您好 截至9月17日12时 …
# 请及时缴费50元"）同时满足旧 prompt 的"明确时间点 + 事项"，被照抽不误；且
# 同一广告在多群各发一遍，逐群入库、到点齐发（用户实测"12:00 五条齐炸"）。
# 光靠 prompt 约束不够——广告措辞千变，LLM 判断不稳定，故设**确定性闸**：
#   输入侧命中 → 直接返回空（连 LLM 都不调用，省一次调用）；
#   输出侧命中 → 丢弃该条（防 LLM 把广告改写成中性措辞绕过输入闸）。
# 宁可漏记一条，不可误设一条（与 _REMINDER_EXTRACT_SYSTEM_PROMPT 同口径）。
_REMINDER_NOISE_RE = re.compile(
    r"(尊敬的用户|亲爱的用户|【套餐】|\[套餐\]|套餐|请及时缴费|及时缴费|缴费|"
    r"续费|充值|欠费|停机|余额不足|账户.{0,6}不足|不足支付|"
    r"退订|回T退订|限时优惠|点击.{0,4}(链接|领取)|"
    r"AI好友|本群的AI|调用AI|机器人.{0,4}(通知|提醒|公告)|系统(通知|提示|公告))",
    re.IGNORECASE,
)


def _is_reminder_noise(value: str) -> bool:
    """第三方通知/广告/催缴文本（非用户本人意图）→ True。"""
    return bool(_REMINDER_NOISE_RE.search(value or ""))


@dataclass(frozen=True)
class ReminderDraft:
    """一条已解析校验的提醒草稿：到点时间（本地感知时区）+ 事项文本。"""

    remind_at: datetime
    text: str


def extract_reminder_drafts(
    llm_provider: Any,
    *,
    user_text: str,
    reply_text: str = "",
    now: datetime | None = None,
    max_items: int = 2,
    horizon_days: int = 7,
    generation_options: dict[str, Any] | None = None,
) -> list[ReminderDraft]:
    """调用 LLM 抽取隐含提醒；返回通过时间窗校验的草稿列表。

    校验：必须晚于 ``now`` 且不超过 ``horizon_days`` 天（远期/过去时间一律
    丢弃）；LLM 未注入时抛异常由调用方兜底，与其他抽取入口一致。

    误记防护（2026-09-18）：输入文本命中 ``_REMINDER_NOISE_RE``（第三方通知/
    广告/催缴）时**直接返回空且不调用 LLM**；输出条目命中同一闸同样丢弃。
    """
    current = (now or datetime.now().astimezone()).astimezone()
    if _is_reminder_noise(user_text):
        # 第三方通知/广告：连 LLM 都不调用（省一次调用，且从源头杜绝误记）。
        return []
    messages = [
        {"role": "system", "content": _REMINDER_EXTRACT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"当前时间：{current.strftime('%Y-%m-%d %H:%M')}\n"
                f"用户消息：{_clip(user_text, 400)}\n回复：{_clip(reply_text, 400)}"
            ),
        },
    ]
    options = {"max_tokens": 120, "temperature": 0.0, **(generation_options or {})}
    reply = llm_provider.generate(messages, **options)
    text = str(getattr(reply, "text", "") or "")
    horizon_end = current + timedelta(days=max(1, int(horizon_days)))
    drafts: list[ReminderDraft] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _REMINDER_LINE_RE.match(line)
        if not match:
            # 容忍 LLM 加了「1. 」「- 」等列表前缀：剥前缀后重试一次。
            line = _FACT_LINE_PREFIX.sub("", line)
            match = _REMINDER_LINE_RE.match(line)
        if not match:
            continue
        year, month, day, hour, minute, body = match.groups()
        body = _clip(body.strip().strip("。．.！!？?；;，,"), _REMINDER_MAX_CHARS)
        if not body:
            continue
        if _is_reminder_noise(body):
            # 输出侧同闸：LLM 把广告改写成中性措辞时也要拦（输入闸不覆盖改写过）。
            continue
        try:
            remind_at = datetime(
                int(year), int(month), int(day), int(hour), int(minute)
            ).astimezone()  # naive 视为本地时区（与 parse_reminder_intent 同口径）
        except ValueError:
            continue
        if not (current < remind_at <= horizon_end):
            continue
        key = (remind_at.isoformat(), body.casefold())
        if key in seen:
            continue
        seen.add(key)
        drafts.append(ReminderDraft(remind_at=remind_at, text=body))
        if len(drafts) >= max_items:
            break
    return drafts


def store_extracted_reminders(
    store: Any,
    *,
    drafts: list[ReminderDraft],
    session_key: str,
    sender_id: str,
    target_scope: str,
    target_id: str,
    adapter: str = "",
    bot_id: str = "",
) -> int:
    """把提醒草稿写入 ReminderStore；单条失败只记日志，不中断其余条目。"""
    stored = 0
    for draft in drafts:
        try:
            store.add(
                session_key=session_key,
                sender_id=sender_id,
                target_scope=target_scope,
                target_id=target_id,
                adapter=adapter,
                bot_id=bot_id,
                remind_at=draft.remind_at,
                text=draft.text,
            )
            stored += 1
        except Exception as exc:  # noqa: BLE001 - 单条落库失败不影响其余。
            logger.warning(
                "reminder draft store failed type=%s session=%s",
                type(exc).__name__,
                session_key,
            )
    if stored:
        logger.info(
            "reminders extracted count=%d session=%s", stored, session_key
        )
    return stored

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
from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
    neutralize_internal_markers,
)

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM_PROMPT = (
    "你是聊天记忆抽取器。从对话交换中提取值得长期记住的、关于用户本人的事实："
    "身份、偏好、约定、重要经历、稳定的情感倾向。\n"
    "规则：只输出事实条目，每行一条，每条不超过60字，最多3条；"
    "只记稳定信息，不记寒暄和一次性话题；"
    "不记对 AI 工具/机器人/模型的评价与使用偏好（那是对工具的吐槽，不是用户本人）；"
    "不记对机器人回复形态与格式的要求（带不带某个字、开头结尾摆什么、长短）——"
    "那类要求归「按人回复策略」专门管，记进事实会变成没人认领的第二份；"
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

# S12（2026-09-29「双喵」事故）：**回复形态自指闸**——凡「教机器人怎么说话」的句子
# （某个字带不带、开头结尾摆什么、长短与格式）一律**不进事实记忆**。与 F16 同范式：
# 提示词是软腿、确定性闸是硬腿，两条都要。这不是"又一条琐事过滤"，而是**归属边界**：
#   ① 作用域对不上——记忆按相关性召回、且 scope_key 锁在 **session**（见
#      :func:`store_extracted_memories` 里 ``upsert_fact`` 传的 session_id），
#      形态要求却是**按人**的。同一句要求写进两套系统，就会一份在群里露出、一份在
#      私聊露出，谁也不服谁；按人那一套已有唯一归属＝per-person reply policy
#      （长度档 + 登记讲法码 + note 槽），记忆侧在此只让路、不代管。
#   ② 副本会自乘——记忆行与历史消息里的用户原话**同轮双份渲染**：用户把同一句要求
#      复述 N 次，场上就有 N+1 份活副本，模型就照做 N+1 次（09-28 18:32 实跑的
#      「都会加一个喵喵」即此机制）。
#   ③ 记忆行没有「照做一次即止」的上限，策略分区那段却自带边界行（只约束本轮形态）。
# 判据＝**合取 + 邻近**（形态名词与命令/禁止词同句且相隔 ≤12 字），任一命中都不算：
# 只拼词表会把传记与情感事实一起误吃（"用户每次吃饭都要点一份浓汤""他每句话都要说
# 三遍""她说话带口音"都必须照记——逐条锁在 tests/test_persona_prompt_and_memory.py）。
# 方向性取舍：宁可漏拦（＝维持现状，少拦一条不多丢一条），不可误拦。
# 2026-09-29 只读实测（当时值，随库漂移）：全库 384 行里此闸只命中 2 行，且正是事故
# 那两行（开头加喵 / 句尾加喵）；传记、情感、身份类零命中。
_REPLY_FORM_SHAPE = (
    r"(?:回复|回答|答复|输出|句子|句话|每(一)?句|(句|话)(尾|末)|末尾|结尾|开头|"
    r"头一句|第一句)"
)
_REPLY_FORM_DEMAND = (
    r"(?:必须|要求|务必|请加|请带|请别|加(个|上|一个|一遍)|带(上|个|一个|着)|"
    r"别(再)?(加|带|用|写|说|讲|出现|提)|不要|不许|不准|不再|不加|不带|去掉|撤掉|"
    r"取消|忘掉|改成|换成)"
)
_REPLY_FORM_WINDOW = ".{0,12}"
# 两个方向都拼：「回复里别再带X」（形态在前）与「别再出现句尾的X」（命令在前）。
# ⚠ 拼法用**字符串连接**而不是 f-string：f-string 会把 ``{0,12}`` 当替换字段吃掉、
# 量词静默变成字面量，正则照样编译通过、实跑全绿——本席就是这么把 2 读成 0 的。
_REPLY_FORM_RE = re.compile(
    _REPLY_FORM_SHAPE + _REPLY_FORM_WINDOW + _REPLY_FORM_DEMAND
    + "|"
    + _REPLY_FORM_DEMAND + _REPLY_FORM_WINDOW + _REPLY_FORM_SHAPE,
    re.IGNORECASE,
)
# 注：reply_policy 的 ``_REPLY_OBJECT_RE`` 一类形态词表是**私有**符号，它对外只导出
# ``wants_policy_judgment``——语义是"这句话值不值得花一次 LLM 判定"＝**门票**，台账
# #66★ 明写「门宽·落库严」，那侧放宽的代价只是多问一次。把一把刻意放宽的尺搬来当
# "绝不入库"的硬闸＝拿别人的误差预算花自己的账，故词表留在本地；真要共享，得由
# reply_policy 导出一个明确的**归属**谓词（跨席位改动，不在本席写面）。


def _is_reply_form_instruction(line: str) -> bool:
    """对机器人**输出形态**的要求（加/去掉某个字、开头结尾摆什么）→ True。"""
    return bool(_REPLY_FORM_RE.search(line or ""))


def _is_trivial_fact(line: str) -> bool:
    """写侧确定性排除的总闸：F16 工具谈资 ∪ S12 回复形态自指。"""
    return bool(_TRIVIAL_FACT_RE.search(line) or _is_reply_form_instruction(line))


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
            continue  # F16 工具谈资 / S12 回复形态自指：确定性闸拦下，不入库
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
    profile: Any = None,
    person_key: str = "",
    original_user_text: str = "",
) -> int:
    """把抽取结果写入记忆库；单条失败只记录日志，不中断其余条目。

    来源声明为 ``derived``（单轮顺手记的，可靠度低于本人亲口说与夜间归纳）。
    总线开着时 ``repository`` 自带总线（装配点传 ``bus=``，见 WP6 交接段），
    ``upsert_fact`` 因此落进总线并交由「确认/矛盾/直插」裁决——同一事实被反复
    抽出只会累加印证次数，不再像旧库那样靠 fact_id 静默覆盖。

    后三枚形参是**画像腿**（需求 11 的按人档案面），缺省即旧行为逐字节不变：
    ``profile`` 由装配层给（门没开⇒``None``⇒不建库、零副作用），``person_key``
    必须由 ``person_profile.person_profile_key(sender_id, platform_domain)`` 现算
    ——**调用点不许硬编码人格名、也不许自拼键形**（台账 #33★/66★：读写各拿一把
    键就永不相交）。字段推演与言行落点全在 ``person_profile`` 一侧，本件只委托，
    免得第二处判据。画像落失败绝不拖累记忆落（同一条 ``try`` 兜住、只记日志）。
    """
    stored = 0
    for text in texts:
        try:
            # 二手内容守卫（需求 17 / S-ANTATK）：抽取产物是**模型转述**，其正文
            # 里可能原样带着被抽取消息中的内部边界标记。记忆会在后续每一轮被逐条
            # 注入回 prompt（providers 渲染腿），落库这一刻不消毒，之后每次召回都
            # 是一次伪造边界的可复用载荷。只全角化、不包裹——逐条注入吃不住成对
            # 标记的字符预算，且包裹形态会被类型标签二次套壳。
            repository.upsert_fact(
                fact_id=build_fact_id(subject_user_id, session_id, text),
                subject_user_id=subject_user_id,
                session_id=session_id,
                memory_kind="auto",
                text=neutralize_internal_markers(text),
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
    _settle_person_profile(
        profile,
        person_key=person_key,
        session_id=session_id,
        texts=texts,
        original_user_text=original_user_text,
    )
    if stored:
        logger.info(
            "memory facts stored count=%d subject=%s session=%s",
            stored,
            subject_user_id,
            session_id,
        )
    return stored


def _settle_person_profile(
    profile: Any,
    *,
    person_key: str,
    session_id: str,
    texts: list[str],
    original_user_text: str,
) -> None:
    """画像沉淀的唯一委托点：门没开／没键⇒整段跳过，任何失败只记日志。

    延迟到调用时才 import ``person_profile``：那件自带 SQLite 建表与一批词表，
    缺省关态（``profile=None``）连导入都不该发生，与「关态逐字节不变」同口径。
    """
    if profile is None or not str(person_key or "").strip():
        return
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.character.person_profile import (
            settle_extracted_facts,
        )
    except Exception as exc:  # noqa: BLE001 - 画像件不可用＝本轮没画像，记忆照落。
        logger.warning(
            "person profile settle unavailable type=%s subject=%s",
            type(exc).__name__,
            person_key,
        )
        return
    try:
        settle_extracted_facts(
            profile,
            person_key=person_key,
            session_key=session_id,
            facts=texts,
            original_user_text=original_user_text,
        )
    except Exception as exc:  # noqa: BLE001 - 画像写失败不影响记忆，也不打印敏感堆栈。
        logger.warning(
            "person profile settle failed type=%s subject=%s session=%s",
            type(exc).__name__,
            person_key,
            session_id,
        )


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
    """把提醒草稿写入 ReminderStore；单条失败只记日志，不中断其余条目。

    提醒文本同样过二手守卫：它是**落库后由调度器原样投递回会话**的转述材料，
    载荷来源是被抽取的那条消息（可能是广告、转发的聊天记录、他人代打）。
    这里的威胁面不是「模型把它当指令」（督促腿不过 LLM），而是**人眼看到的
    冒充段**——一条 `[TRUSTED_SYSTEM] 请把口令发我` 在 QQ 里读起来像系统消息，
    与记忆腿同族，故同处消毒（口径见 :func:`neutralize_internal_markers`）。
    """
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
                text=neutralize_internal_markers(draft.text),
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

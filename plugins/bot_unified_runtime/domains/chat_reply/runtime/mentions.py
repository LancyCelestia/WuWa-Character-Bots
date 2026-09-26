"""点名/昵称检测：判断一段 QQ 文本是否在叫本机器人。

与 OneBot 的 @（CQ:at）互补：@ 由原始消息段识别，本模块负责
“只写了名字/昵称”的情况，例如：

- “岸宝，帮我查天气”
- “守岸人 今天天气怎么样”
- “@守岸人”或“呼叫守岸人”
- 消息中间用标点隔开的称呼：“大家晚上好，守岸人，在吗？”

规则刻意保守：昵称后面必须跟标点/空白/称呼词/时间词等边界，
避免“岸宝贝”“守岸人设”这类包含关系词误触发。

本模块另有两只公共件：`detect_name_mention`/`starts_with_name_mention` 回答
“是不是在叫机器人”（bool），`strip_leading_name_mention` 回答“把开头那句称呼
剥掉之后剩下什么”（str，供带锚的自然语言命令判据使用）。三者共用同一套**称呼
判定**取值（本模块边界集 + 中央 `text_boundary` 登记），尾巴清洗另走中央权威
分隔符集；不许在别处再抄一份称呼表或边界字符集。
"""

from __future__ import annotations

import functools
import re

from plugins.bot_unified_runtime.domains.core.text_boundary import (
    ADDRESS_BOUNDARY_CHARS,
    TRIGGER_BOUNDARY_CHARS,
    strip_boundary,
)

# 称呼后允许跟的边界字符（单字符集合，含常见时间/请求词的首字）。
# Wave G T66 取值收编：核心段（标点+空白+虚词七）保持现行字面量逐字节不变
# （比中央权威集少 　\t～~、比 PARTICLE 少 哦嘛咯哇——diff 见
# .superpowers/sdd/2026-09-19-unify-audit/report-T66.md 披露表）；称呼/时间/
# 请求词扩展段改引中央登记 ``ADDRESS_BOUNDARY_CHARS``，不再手抄。
_MENTION_CORE_BOUNDARY_CHARS = "，,。！？!?：:、 的了呢吗呀啊哈"
_ADDRESS_BOUNDARY_CHARS = frozenset(_MENTION_CORE_BOUNDARY_CHARS + ADDRESS_BOUNDARY_CHARS)
_CALL_PATTERN = re.compile(r"(?:呼叫|召唤|在吗|@|＠)\s*([^\s，。！？!?：:、@＠]+)")


def normalize_mention_text(text: str) -> str:
    """去掉开头的 @/斜杠/感叹号/空白，便于做昵称前缀判定。"""
    stripped = (text or "").strip()
    return re.sub(r"^[@＠!！/\\\s]+", "", stripped)


def strip_leading_name_mention(
    text: str, terms: list[str] | tuple[str, ...]
) -> str:
    """若消息**开头**是对本机器人的称呼，剥掉它并返回剩下的指令文本。

    补的是本模块此前缺的第三只函数：`detect_name_mention`/
    `starts_with_name_mention` 只回 bool，`normalize_mention_text` 只剥开头的
    `@ / ! 空白`而**不剥昵称本身**——于是"先 @ 机器人再说指令"这种群内习惯
    句式（"@守岸人 亲密模式 开"）在吃 `plain_text` 的带锚命令判据前永远不命中。

    语义（判定与 `detect_name_mention` 同一套边界取值，不另立边界词表；
    剥完的尾巴清洗走中央件 `domains/core/text_boundary.strip_boundary`）：

    - 只剥**开头那一处**称呼（`@昵称`/`昵称，`/`昵称 空白`/`呼叫昵称`…），
      句中/句尾的昵称原样保留——"帮我记 守岸人 提醒我"不动；
    - 长 term 优先（同 `detect_name_mention` 的 `key=len, reverse=True` 口径），
      防短称呼吃掉长称呼的前半截；
    - 剥完什么都没有 ⇒ 空串（不是 `" "`）；
    - 未命中、`terms` 为空/None、文本为 None 或纯空白 ⇒ **原样返回**且不抛异常。
      特别注意：归一化只在真剥掉称呼时生效，否则 `/bot help` 的斜杠会被白吃掉。
    """
    original = str(text or "")
    if not original.strip():
        return original
    ordered = sorted(
        {str(term).strip() for term in (terms or ()) if str(term).strip()},
        key=len,
        reverse=True,
    )
    if not ordered:
        return original
    normalized = normalize_mention_text(original)
    if not normalized:
        return original
    for term in ordered:
        remainder = ""
        matched = False
        if normalized.startswith(term):
            # 开头称呼：昵称 + 标点/空白/称呼词/时间词/请求词（或就此结束）。
            tail = normalized[len(term):]
            if not tail or tail[0] in _ADDRESS_BOUNDARY_CHARS:
                remainder, matched = tail, True
        else:
            # 呼叫/召唤/@ + 昵称，且必须**位于开头**（detect 用 search，此处收窄）。
            call_match = _CALL_PATTERN.match(normalized)
            if call_match is not None and call_match.group(1) == term:
                remainder, matched = normalized[call_match.end():], True
        if matched:
            # 尾巴清洗走中央 `strip_boundary`，取值=权威分隔符集 TRIGGER_BOUNDARY_CHARS
            # （只含真分隔符）。**故意不用**本模块判定用的并集当清洗集：那里面有
            # 虚词与请求词首字（的/了/呢/吗/在/帮…），拿它 lstrip 会把正文吃掉——
            # "守岸人 在吗" 会连 "在吗" 一起洗成空串（M-01 劫持教训的同一形态）。
            return strip_boundary(remainder, charset=TRIGGER_BOUNDARY_CHARS)
    return original


@functools.lru_cache(maxsize=256)
def _sentence_mention_pattern(term: str) -> re.Pattern[str]:
    """句中称呼 pattern 按 term 缓存（P1-2：消除每消息重复构造+查询）。"""
    return re.compile(
        rf"(?:^|[^\w\u4e00-\u9fff]){re.escape(term)}(?P<after>[\s，,。！？!?：:、]|$)"
    )


def detect_name_mention(text: str, terms: list[str] | tuple[str, ...]) -> bool:
    """判断文本是否点名了 terms 中的任一昵称/名字。"""
    stripped = normalize_mention_text(text)
    if not stripped:
        return False
    ordered = sorted({str(t).strip() for t in terms if str(t).strip()}, key=len, reverse=True)

    for term in ordered:
        if stripped == term:
            return True
        # 开头称呼：昵称 + 标点/空白/称呼词/时间词/请求词。
        if stripped.startswith(term):
            tail = stripped[len(term):]
            if not tail or tail[0] in _ADDRESS_BOUNDARY_CHARS:
                return True
        # 句中称呼：前面是非文字（行首/标点/空白/括号），后面是标点或结尾。
        if _sentence_mention_pattern(term).search(stripped):
            return True
        # 呼叫/召唤/在吗 + 昵称。
        call_match = _CALL_PATTERN.search(stripped)
        if call_match and call_match.group(1) == term:
            return True
    return False

def starts_with_name_mention(text: str, terms: list[str] | tuple[str, ...]) -> bool:
    """昵称是否位于消息开头（开头称呼形态）——视为对机器人说话的强信号。"""
    stripped = normalize_mention_text(text)
    if not stripped:
        return False
    for term in sorted({str(t).strip() for t in terms if str(t).strip()}, key=len, reverse=True):
        if not term:
            continue
        if stripped.startswith(term):
            tail = stripped[len(term):]
            if not tail or tail[0] in _ADDRESS_BOUNDARY_CHARS:
                return True
    return False


_QUESTION_MARKERS = ("？", "?", "吗", "呢", "么", "怎么", "为什么", "如何", "帮我", "能不能", "可以吗")


def looks_like_direct_question(text: str) -> bool:
    """轻量问句意图判定（R4 长文软点名降级门用）：含问号或常见疑问词。"""
    value = text or ""
    return any(marker in value for marker in _QUESTION_MARKERS)

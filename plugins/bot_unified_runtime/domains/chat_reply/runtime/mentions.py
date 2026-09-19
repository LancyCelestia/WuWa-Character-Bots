"""点名/昵称检测：判断一段 QQ 文本是否在叫本机器人。

与 OneBot 的 @（CQ:at）互补：@ 由原始消息段识别，本模块负责
“只写了名字/昵称”的情况，例如：

- “岸宝，帮我查天气”
- “守岸人 今天天气怎么样”
- “@守岸人”或“呼叫守岸人”
- 消息中间用标点隔开的称呼：“大家晚上好，守岸人，在吗？”

规则刻意保守：昵称后面必须跟标点/空白/称呼词/时间词等边界，
避免“岸宝贝”“守岸人设”这类包含关系词误触发。
"""

from __future__ import annotations

import functools
import re

from plugins.bot_unified_runtime.domains.core.text_boundary import (
    ADDRESS_BOUNDARY_CHARS,
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

"""角色回复的动作/说话分行格式化。

模型回复常常把括号动作与说话内容挤在同一段，例如：

    （微微抬起视线）啊，你问我吗……

本模块把括号动作与动作之外的连续文字拆成独立段落，段落之间用两个
换行符连接；没有任何括号动作时保持原文本（仅 strip）不变。

颜文字（如 ``(≧▽≦)``、``（*´▽｀*）``）不是动作描写：括号内没有汉字的
片段按普通文字保留在原地，避免把表情从一句话中间切到单独一行。
"""

from __future__ import annotations

import re

_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")

_ACTION_CLOSING_BRACKETS = {
    "（": "）",
    "(": ")",
}


def _matching_action_end(text: str, start: int) -> int | None:
    """返回与 start 处左括号配对的最外层右括号下标；未闭合返回 None。"""
    opening = text[start]
    closing = _ACTION_CLOSING_BRACKETS[opening]
    depth = 1
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _action_tokens(text: str) -> list[tuple[int, int]]:
    """扫描全部闭合的动作片段，返回半开区间 (start, end)。

    只按同一种括号族做最外层匹配；未闭合的括号被当作普通文字安全忽略。
    """
    tokens: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if text[index] in _ACTION_CLOSING_BRACKETS:
            end = _matching_action_end(text, index)
            if end is not None:
                inner = text[index + 1 : end]
                nested = ("（" in inner or "(" in inner)
                if _CJK_CHAR_RE.search(inner) or nested:
                    tokens.append((index, end + 1))
                    index = end + 1
                    continue
                # 括号内没有汉字、也没有嵌套括号：视为颜文字/符号，不作为动作拆分。
        index += 1
    return tokens



_OUTER_SPEECH_QUOTES = {'"': '"', "'": "'", '“': '”', '‘': '’', '「': '」', '『': '』'}


def strip_outer_speech_quotes(text: str) -> str:
    """Unwrap a sequence of quoted speech blocks, not quotes inside prose.

    Parse matching delimiters before changing anything: mixed prose, malformed
    quotes and book titles are preserved. Whitespace and inner quotes survive.
    """
    value = (text or "").strip()
    parts: list[str] = []
    cursor = 0
    while cursor < len(value):
        if value[cursor].isspace():
            end = cursor + 1
            while end < len(value) and value[end].isspace():
                end += 1
            parts.append(value[cursor:end])
            cursor = end
            continue
        opening = value[cursor]
        closing = _OUTER_SPEECH_QUOTES.get(opening)
        if closing is None:
            return value
        depth = 1
        end = cursor + 1
        while end < len(value):
            char = value[end]
            if char == closing and (end == 0 or value[end - 1] != "\\"):
                depth -= 1
                if depth == 0:
                    break
            elif opening != closing and char == opening:
                depth += 1
            end += 1
        if end == len(value) or end == cursor + 1:
            return value
        parts.append(value[cursor + 1:end])
        cursor = end + 1
    return "".join(parts) if parts else value


def format_roleplay_paragraphs(text: str) -> str:
    """将括号动作与动作之外的连续文字拆成独立段落。

    每个动作（含括号、保留括号内原换行结构）和每段非空连续文字各占一段，
    段落间用 ``\\n\\n`` 连接；输入不含括号动作时返回 ``text.strip()``。
    """
    tokens = _action_tokens(text)
    if not tokens:
        return text.strip()

    paragraphs: list[str] = []
    cursor = 0
    for start, end in tokens:
        if start > cursor:
            speech = text[cursor:start].strip()
            if speech:
                paragraphs.append(speech)
        action = text[start:end].strip()
        if action:
            paragraphs.append(action)
        cursor = end

    tail = text[cursor:].strip()
    if tail:
        paragraphs.append(tail)
    return "\n\n".join(paragraphs)

def strip_action_brackets(text: str) -> str:
    """删除回复中的括号动作描写（保留颜文字与普通括号文字）。

    与 format_roleplay_paragraphs 共用 _action_tokens：括号内含汉字或嵌套
    括号的片段按动作删除；括号内无汉字（如 (≧▽≦)、（*´▽｀*））视为颜文字
    保留。删除后折叠多余空行，返回 strip 后的纯文本。
    """
    tokens = _action_tokens(text)
    if not tokens:
        return text.strip()
    kept: list[str] = []
    cursor = 0
    for start, end in tokens:
        if start > cursor:
            kept.append(text[cursor:start])
        cursor = end
    if cursor < len(text):
        kept.append(text[cursor:])
    joined = "".join(kept)
    joined = re.sub(r"\n[ \t]*\n+", "\n", joined)
    joined = re.sub(r"[ \t]+\n", "\n", joined)
    return joined.strip()

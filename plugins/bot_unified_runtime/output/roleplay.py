"""角色回复的动作/说话分行格式化。

模型回复常常把括号动作与说话内容挤在同一段，例如：

    （微微抬起视线）啊，你问我吗……

本模块把括号动作与动作之外的连续文字拆成独立段落，段落之间用两个
换行符连接；没有任何括号动作时保持原文本（仅 strip）不变。
"""

from __future__ import annotations

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
                tokens.append((index, end + 1))
                index = end + 1
                continue
        index += 1
    return tokens


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

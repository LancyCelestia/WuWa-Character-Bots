"""智能回复切分 v2：按“段落”打包，每 3 段一条消息，段数不设上限。

- 先按空行切段落；每 3 段（可含被句子切分的超长段）打包成一条消息；
- 长度尽量均衡，单条不超 hard_max；太短的段落自动并入相邻消息；
- 超长段按句末标点切，包括 留白（空行）、省略号……、破折号——、句号等；
- 省略号/破折号始终留在上一段结尾，不把“……”切到下一段开头；
- emoji 安全：切点不落在 ZWJ / 变体选择符 / 组合附标前面；
- AI 可回复任意多段：5 段→2 条、6 段→2 条、9 段→3 条，逐条直接发送，
  不使用合并转发。
"""

from __future__ import annotations

_STRONG_BOUNDARY = "。！？!?…~—"
_WEAK_BOUNDARY = "；;，,：:"
_UNSAFE_NEXT = frozenset({"\u200d", "\ufe0f", "\ufe0e"})  # ZWJ / 变体选择符
_COMBINING_RANGE = range(0x0300, 0x0370)


def _is_safe_cut(text: str, index: int) -> bool:
    if index <= 0 or index >= len(text):
        return False
    nxt = text[index]
    if nxt in _UNSAFE_NEXT or ord(nxt) in _COMBINING_RANGE:
        return False
    if nxt in "）)】》」』\"'”’":  # 不把成对收尾符号切到下一段开头
        return False
    return True


def _collect_boundaries(text: str) -> list[tuple[int, int]]:
    """返回 (切点下标, 强度)；省略号/破折号按强边界处理，留在上一句结尾。"""
    boundaries: list[tuple[int, int]] = []
    length = len(text)
    index = 1
    while index < length:
        char = text[index - 1]
        if char == "\n" and index < length and text[index] == "\n":
            boundaries.append((index, 0))
            index += 1
            continue
        if char in _STRONG_BOUNDARY:
            # 连续省略号/破折号吞完，切在最后一个之后
            while index < length and text[index] == char:
                index += 1
            boundaries.append((index, 0))
            continue
        if char in _WEAK_BOUNDARY and index < length and text[index] not in "，,。！？!?；;…~":
            boundaries.append((index, 1))
        index += 1
    return [item for item in boundaries if _is_safe_cut(text, item[0])]


def _nearest_boundary(
    text: str,
    boundaries: list[tuple[int, int]],
    desired: int,
    window: int,
) -> int:
    best_index = 0
    best_score: float = float("inf")
    for index, strength in boundaries:
        distance = abs(index - desired)
        if distance > window:
            continue
        score = distance + strength * 40
        if score < best_score:
            best_score = score
            best_index = index
    return best_index


def _sentence_split(text: str, limit: int) -> list[str]:
    """把超长段落按句末标点切块，每块 <= limit。"""
    boundaries = _collect_boundaries(text)
    chunks: list[str] = []
    previous = 0
    while previous < len(text):
        desired = previous + limit
        cut = _nearest_boundary(text, boundaries, desired, window=max(40, limit // 2))
        if cut <= previous:
            cut = min(len(text), desired)
        chunk = text[previous:cut].strip()
        if chunk:
            chunks.append(chunk)
        previous = cut
    return chunks or [text]


def _merge_tiny(units: list[str], min_chars: int) -> list[str]:
    if not units:
        return units
    merged: list[str] = []
    for unit in units:
        if not merged:
            merged.append(unit)
            continue
        if len(unit) < min_chars and len(merged[-1]) + len(unit) <= min_chars * 4:
            merged[-1] = f"{merged[-1]}\n{unit}"
        else:
            merged.append(unit)
    return merged


def split_reply_messages(
    text: str,
    *,
    units_per_message: int = 3,
    target_chars: int = 520,
    min_chars: int = 220,
    hard_max: int = 900,
) -> list[str]:
    """把长回复按“每 3 段一条消息”打包；段数不设上限，返回消息列表。"""
    normalized = (text or "").strip()
    if not normalized:
        return [""]
    if len(normalized) <= target_chars:
        return [normalized]

    paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
    if not paragraphs:
        paragraphs = [normalized]

    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= hard_max:
            units.append(paragraph)
        else:
            units.extend(_sentence_split(paragraph, hard_max))
    units = _merge_tiny(units, max(1, int(min_chars)))

    per_message = max(1, min(int(units_per_message), 3))
    messages: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in units:
        would_overflow = current and (
            len(current) >= per_message
            or current_len + len(unit) > int(target_chars * 1.7)
        )
        if would_overflow:
            messages.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(unit)
        current_len += len(unit)
    if current:
        messages.append("\n\n".join(current))
    return [message for message in messages if message] or [normalized]

"""智能回复切分：把一段很长的回复切成最多 3 条消息（直接发送，不合并转发）。

目标：
- 切成 <= max_parts 条、长度尽量均衡的消息；
- 只在句末标点 / 段落边界切，绝不从汉字/英文单词中间硬切；
- 不切坏 emoji：切点前后不允许落在代理对内部，也不允许把 ZWJ /
  变体选择符 / 组合附标丢到下一段开头；
- 太短的碎片自动并入相邻段，避免“一句特别长、一句特别短”。
"""

from __future__ import annotations

_STRONG_BOUNDARY = "。！？!?…~"
_WEAK_BOUNDARY = "；;，,：:"
_BOUNDARY_CHARS = _STRONG_BOUNDARY + _WEAK_BOUNDARY + "\n"
_UNSAFE_NEXT = frozenset({"\u200d", "\ufe0f", "\ufe0e"})  # ZWJ / 变体选择符
_COMBINING_RANGE = range(0x0300, 0x0370)


def _is_safe_cut(text: str, index: int) -> bool:
    if index <= 0 or index >= len(text):
        return False
    prev = text[index - 1]
    if "\ud800" <= prev <= "\udbff":  # 高位代理，切点落在代理对内部
        return False
    nxt = text[index]
    if nxt in _UNSAFE_NEXT or ord(nxt) in _COMBINING_RANGE:
        return False
    if nxt in "）)】》」』\"'”’":  # 不把成对收尾符号切到下一段开头
        return False
    return True


def _collect_boundaries(text: str) -> list[tuple[int, int]]:
    """返回 (切点下标, 强度) 列表；强度 0=最强（换行/句号），1=较弱（逗号分号）。"""
    boundaries: list[tuple[int, int]] = []
    length = len(text)
    for index in range(1, length):
        char = text[index - 1]
        if char == "\n" and index < length and text[index] == "\n":
            boundaries.append((index, 0))
            continue
        if char in _STRONG_BOUNDARY:
            boundaries.append((index, 0))
        elif char in _WEAK_BOUNDARY and index < length and text[index] not in "，,。！？!?；;…~":
            boundaries.append((index, 1))
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
        score = distance + strength * 40  # 弱边界多扣分，优先强边界
        if score < best_score:
            best_score = score
            best_index = index
    return best_index


def _merge_tiny(parts: list[str], min_chars: int) -> list[str]:
    if not parts:
        return parts
    merged: list[str] = []
    for part in parts:
        if not merged:
            merged.append(part)
            continue
        if len(part) < min_chars and len(merged[-1]) + len(part) <= min_chars * 4:
            merged[-1] = f"{merged[-1]}\n{part}"
        else:
            merged.append(part)
    return merged


def split_reply_messages(
    text: str,
    *,
    max_parts: int = 3,
    target_chars: int = 520,
    min_chars: int = 240,
) -> list[str]:
    """把长回复切成 <= max_parts 条均衡消息；短文本原样返回一条。"""
    normalized = (text or "").strip()
    if not normalized:
        return [""]
    parts_limit = max(1, min(int(max_parts), 3))
    target = max(160, int(target_chars))
    if len(normalized) <= target:
        return [normalized]

    boundaries = _collect_boundaries(normalized)
    cuts: list[int] = []
    total = len(normalized)
    window = max(80, int(target * 0.5))
    for part_index in range(1, parts_limit):
        desired = round(total * part_index / parts_limit)
        cut = _nearest_boundary(normalized, boundaries, desired, window)
        if cut > 0 and (not cuts or cut > cuts[-1] + min_chars):
            cuts.append(cut)

    parts: list[str] = []
    previous = 0
    for cut in cuts:
        chunk = normalized[previous:cut].strip()
        if chunk:
            parts.append(chunk)
        previous = cut
    tail = normalized[previous:].strip()
    if tail:
        parts.append(tail)

    parts = _merge_tiny([part for part in parts if part], max(60, int(min_chars)))
    if len(parts) > parts_limit:
        parts = parts[: parts_limit - 1] + ["\n".join(parts[parts_limit - 1:])]
    return parts or [normalized]

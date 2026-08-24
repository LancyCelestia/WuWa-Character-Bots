"""智能回复切分 v3：均衡优先，最多 3 条消息，优先 1 条、其次 2 条。

- 短回复整段一条；
- 长回复先按“每 3 段/句一个候选块”生成单元，再把单元均衡合并成
  2 或 3 条（总长度均分，避免单条过长/过短）；
- 只在句末标点/段落边界切，兼容省略号……、破折号——、留白；
- emoji 安全（ZWJ/变体选择符/组合附标不切）；
- 意图自适应：段落本身就是天然语义单元；段落少但很长时按句均分。
"""

from __future__ import annotations

_STRONG_BOUNDARY = "。！？!?…~—"
_WEAK_BOUNDARY = "；;，,：:"
_UNSAFE_NEXT = frozenset({"\u200d", "\ufe0f", "\ufe0e"})
_COMBINING_RANGE = range(0x0300, 0x0370)


def _is_safe_cut(text: str, index: int) -> bool:
    if index <= 0 or index >= len(text):
        return False
    nxt = text[index]
    if nxt in _UNSAFE_NEXT or ord(nxt) in _COMBINING_RANGE:
        return False
    return nxt not in "）)】》」』\"'”’"


def _collect_boundaries(text: str) -> list[tuple[int, int]]:
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
            while index < length and text[index] == char:
                index += 1
            boundaries.append((index, 0))
            continue
        if char in _WEAK_BOUNDARY and index < length and text[index] not in "，,。！？!?；;…~":
            boundaries.append((index, 1))
        index += 1
    return [item for item in boundaries if _is_safe_cut(text, item[0])]


def _nearest_boundary(boundaries: list[tuple[int, int]], desired: int, window: int) -> int:
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
    boundaries = _collect_boundaries(text)
    chunks: list[str] = []
    previous = 0
    while previous < len(text):
        cut = _nearest_boundary(boundaries, previous + limit, window=max(40, limit // 2))
        if cut <= previous:
            cut = min(len(text), previous + limit)
        chunk = text[previous:cut].strip()
        if chunk:
            chunks.append(chunk)
        previous = cut
    return chunks or [text]


def _balanced_merge(units: list[str], max_parts: int, min_parts: int = 1) -> list[str]:
    """把单元均分成 min_parts..max_parts 条；用最小化“最长/最短差”的切点。"""
    if len(units) <= 1:
        return units
    total = sum(len(unit) for unit in units)
    best_parts: list[str] = units
    best_diff: float = float("inf")
    for parts_count in range(max(1, min_parts), min(max_parts, len(units)) + 1):
        cuts: list[int] = []
        for part_index in range(1, parts_count):
            goal = total * part_index / parts_count
            cumulative = 0
            for index in range(len(units) - 1):
                cumulative += len(units[index])
                if cumulative >= goal and (not cuts or index + 1 > cuts[-1]):
                    cuts.append(index + 1)
                    break
        segments: list[str] = []
        previous = 0
        for cut in cuts + [len(units)]:
            chunk = "\n\n".join(units[previous:cut]).strip()
            if chunk:
                segments.append(chunk)
            previous = cut
        if len(segments) == parts_count and segments:
            lengths = [len(segment) for segment in segments]
            diff = max(lengths) - min(lengths)
            if diff < best_diff:
                best_diff = diff
                best_parts = segments
    return best_parts


def split_reply_messages(
    text: str,
    *,
    max_parts: int = 3,
    target_chars: int = 520,
    min_chars: int = 220,
    hard_max: int = 900,
) -> list[str]:
    """把长回复均衡切成 1~3 条消息（优先 1 条，其次 2 条）。"""
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
    # 合并过短单元，避免出现“一句话特别短”。
    merged: list[str] = []
    floor = max(1, int(min_chars))
    for unit in units:
        if not merged:
            merged.append(unit)
        elif len(unit) < floor and len(merged[-1]) + len(unit) <= floor * 4:
            merged[-1] = f"{merged[-1]}\n{unit}"
        else:
            merged.append(unit)

    if len(merged) <= 1:
        return [normalized]
    # 优先 1 条：总长 <= 2 倍目标长度时可整段发送；再长才拆 2~3 条。
    min_parts = 1 if len(normalized) <= int(target_chars) * 2 else 2
    return (
        _balanced_merge(
            merged,
            max_parts=max(1, min(int(max_parts), 3)),
            min_parts=min_parts,
        )
        or [normalized]
    )


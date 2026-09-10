"""Deterministic chat presentation; never applied to admin/config or media payloads.

No model calls. Preserve words, URLs, numbers and paragraph boundaries while
removing presentation syntax. Common TeX is verbalized, not evaluated; unknown
commands remain named rather than being silently discarded.
"""
from __future__ import annotations

import html
import re

PLAIN_TEXT_VERSION = "chat_plain_text:v1"
_QUOTES = str.maketrans("", "", '"“”„‟「」『』«»‹›')
_COMMANDS = {
    "alpha": "阿尔法", "beta": "贝塔", "gamma": "伽马", "theta": "西塔",
    "pi": "圆周率", "infty": "无穷大", "epsilon": "艾普西隆",
    "delta": "德尔塔", "Delta": "德尔塔", "lambda": "拉姆达",
    "times": "乘以", "cdot": "乘以", "div": "除以", "pm": "加或减",
    "le": "小于或等于", "leq": "小于或等于", "ge": "大于或等于",
    "geq": "大于或等于", "neq": "不等于", "approx": "约等于",
    "to": "趋向", "rightarrow": "指向", "Rightarrow": "推出",
    "in": "属于", "notin": "不属于", "cup": "并集", "cap": "交集",
    "sin": "正弦", "cos": "余弦", "tan": "正切", "log": "对数", "ln": "自然对数",
    "forall": "对于所有", "exists": "存在", "partial": "偏微分",
    "ldots": "……", "cdots": "……", "quad": " ", "qquad": " ",
}
_OPERATORS = {"+": " 加 ", "-": " 减 ", "=": " 等于 ", "*": " 乘以 ",
              "/": " 除以 ", ">": " 大于 ", "<": " 小于 ", "&": "，"}


def _group(text: str, start: int) -> tuple[str, int]:
    while start < len(text) and text[start].isspace():
        start += 1
    if start == len(text):
        return "", start
    if text[start] != "{":
        return text[start], start + 1
    depth = 1
    end = start + 1
    while end < len(text):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:end], end + 1
        end += 1
    return text[start + 1:], end


def _math_text(text: str, depth: int = 0) -> str:
    if depth > 20:
        return "公式嵌套过深，无法可靠转换"
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\":
            match = re.match(r"\\([A-Za-z]+|.)", text[i:], re.DOTALL)
            if match is None:
                out.append("反斜线")
                i += 1
                continue
            command = match[1]
            i += len(match[0])
            if command in {"frac", "dfrac", "tfrac"}:
                numerator, i = _group(text, i)
                denominator, i = _group(text, i)
                out.append(f"分子为（{_math_text(numerator, depth + 1)}）、分母为（{_math_text(denominator, depth + 1)}）的分数")
            elif command == "sqrt":
                order = ""
                if i < len(text) and text[i] == "[":
                    end = text.find("]", i + 1)
                    if end >= 0:
                        order, i = text[i + 1:end], end + 1
                value, i = _group(text, i)
                label = "平方根" if not order else f"{_math_text(order, depth + 1)}次方根"
                out.append(f"（{_math_text(value, depth + 1)}）的{label}")
            elif command in {"sum", "prod", "int", "lim"}:
                bounds = []
                while i < len(text) and (text[i].isspace() or text[i] in "_^" ):
                    if text[i].isspace():
                        i += 1
                        continue
                    label = "下界" if text[i] == "_" else "上界"
                    bound, i = _group(text, i + 1)
                    bounds.append(label + "为" + _math_text(bound, depth + 1))
                label = {"sum": "求和", "prod": "连乘", "int": "积分", "lim": "取极限"}[command]
                out.append(label + ("（" + "，".join(bounds) + "）" if bounds else "") + "：")
            elif command in {"text", "mathrm", "mathbf", "operatorname", "mathit", "mathbb"}:
                value, i = _group(text, i)
                out.append(value if command == "text" else _math_text(value, depth + 1))
            elif command in {"left", "right", "big", "Big", "displaystyle"}:
                continue
            elif command in {",", ";", "!", " ", "\\"}:
                out.append(" ")
            else:
                out.append(_COMMANDS.get(command, f"公式命令 {command}"))
        elif char in "_^":
            value, i = _group(text, i + 1)
            value = _math_text(value, depth + 1)
            if char == "_":
                out.append(f"（下标为{value}）")
            else:
                out.append({"2": "的平方", "3": "的立方"}.get(value, f"的（{value}）次方"))
        elif char == "{":
            value, i = _group(text, i)
            out.append("（" + _math_text(value, depth + 1) + "）")
        else:
            out.append(_OPERATORS.get(char, "）" if char == "}" else char))
            i += 1
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def _table_text(text: str) -> str:
    lines = text.splitlines()
    result: list[str] = []
    index = 0
    while index < len(lines):
        if (index + 1 < len(lines) and "|" in lines[index]
                and re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*", lines[index + 1])):
            headers = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if len(cells) != len(headers):
                    result.append("；".join(cells))
                else:
                    result.append("；".join(f"{key}：{value}" for key, value in zip(headers, cells, strict=True)))
                index += 1
        else:
            result.append(lines[index])
            index += 1
    return "\n".join(result)


def naturalize_chat_text(text: str) -> str:
    """Idempotent presentation conversion for natural chat, not arbitrary code."""
    value = html.unescape(text or "").replace("\r\n", "\n").replace("\u200b", "")
    # Keep link destinations exactly; markdown labels become readable text.
    value = re.sub(r"!?\[([^\]\n]*)\]\((https?://[^\s]+?)\)", r"\1（\2）", value)
    value = re.sub(r"<(https?://[^<>\s]+)>", r"\1", value)
    urls: list[str] = []
    def protect(match: re.Match[str]) -> str:
        urls.append(match[0])
        return f"\ue000{len(urls) - 1}\ue001"
    value = re.sub(r"https?://[^\s<>\"“”）]+", protect, value)
    # Remove fences, retaining their contents. Explicit TeX fences are verbalized.
    value = re.sub(r"```(?:latex|tex|math)\s*\n(.*?)```", lambda m: _math_text(m[1]), value, flags=re.DOTALL)
    value = re.sub(r"(?m)^\s*(?:```|~~~)[^\n]*$", "", value)
    value = re.sub(r"\$\$(.*?)\$\$|\\\[(.*?)\\\]|\\\((.*?)\\\)|(?<!\\)\$([^$\n]+)\$",
                   lambda m: _math_text(next(g for g in m.groups() if g is not None)), value, flags=re.DOTALL)
    value = re.sub(r"(?m)^.*\\(?:frac|dfrac|sqrt|sum|int|prod|lim)\b.*$", lambda m: _math_text(m[0]), value)
    value = _table_text(value)
    value = re.sub(r"(?m)^\s{0,3}#{1,6}\s+|(?m:^\s*(?:>\s*)+)", "", value)
    value = re.sub(r"(?m)^\s*[-+*]\s+(?:\[[ xX]\]\s*)?", "", value)
    value = re.sub(r"(?m)^\s*(?:-{3,}|\*{3,}|_{3,}|={3,})\s*$", "", value)
    value = re.sub(r"\*\*(.*?)\*\*|__(.*?)__|~~(.*?)~~|`([^`]+)`", lambda m: next(g for g in m.groups() if g is not None), value, flags=re.DOTALL)
    value = re.sub(r"(?<!\w)[*_]([^*_\n]+)[*_](?!\w)", r"\1", value)
    value = re.sub(r"</?(?:b|strong|i|em|code|p|br|div|span)\b[^>]*>", lambda m: "\n" if m[0].startswith(("<br", "</p", "</div")) else "", value)
    value = value.translate(_QUOTES)
    # Apostrophes inside English words (don't / I'm) remain meaningful.
    value = re.sub(r"(?<![A-Za-z])['‘’]|['‘’](?![A-Za-z])", "", value)
    value = re.sub(r"\\([*_`#\[\]])", r"\1", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    for index, url in enumerate(urls):
        value = value.replace(f"\ue000{index}\ue001", url)
    return value

# 去 AI 味（说人话）：聊天回复里高频的开场白/收尾客套/总结腔，确定性剥离。
_HUMANIZE_OPENING_RE = re.compile(
    r"^(?:好的[！，,。~ ]*|当然[！，,。~ ]*(?:可以|没问题)[！，,。~ ]*|以下是|这是一份|没错[！，,。~ ]*|嗯[！，,。~ ]*|明白了[！，,。~ ]*)+"
)
_HUMANIZE_CLOSING_RE = re.compile(
    r"(?:希望(?:这|以上)(?:些)?(?:内容)?(?:能)?(?:帮|对你有所)(?:到)?(?:助)?(?:你)?[！。~\s]*)+$|"
    r"(?:以上(?:就是|是).{0,12}全部内容[。！~\s]*)+$|"
    r"(?:总之|综上所述|总结一下|总的来说)[，,：:]?(?:希望|以上就是|记得|欢迎|祝|喜欢的话|一起)[\s\S]{0,40}$|"
    r"(?:如果还有(?:其他)?(?:问题|疑问)[，,]?.{0,20}(?:问我|告诉我|联系我|随时)[。！~\s]*)+$"
)

# 内心状态保密红线：LLM 偶尔会把好感度/心情的内部数值当聊天说出口，数值
# 泄漏瞬间机器感拉满——态度只能通过行为体现，数值一律打码（拟人化整合报告裁决）。
# 连接词用有界枚举而非通配，避免误伤"好感度排行榜前3名"这类正常表述。
_INNER_STATE_NUM_RE = re.compile(
    r"(好感度|亲密度|信任度|趣味相投|心情值|affinity|valence|arousal)"
    r"\s*(?:值|分数|分)?\s*"
    r"(?:(?:已经|已|至少|只有|才|高达|达到|达|是|为|现在|[+加:：=]){1,2})?\s*"
    r"[-+]?\d+(?:\.\d+)?(?:\s*分|\s*%|%)?"
)


def _redact_inner_state_number(match: re.Match[str]) -> str:
    name = match.group(1) or "内心状态"
    return f"{name}…保密"


def humanize_reply(text: str) -> str:
    """剥离聊天回复的 AI 客套开场与总结腔；不改变事实与语义。"""
    value = (text or "").strip()
    if not value:
        return value
    value = _HUMANIZE_OPENING_RE.sub("", value).strip()
    value = _HUMANIZE_CLOSING_RE.sub("", value).strip()
    value = _INNER_STATE_NUM_RE.sub(_redact_inner_state_number, value)
    return value or (text or "").strip()

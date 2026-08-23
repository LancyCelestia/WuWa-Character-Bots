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

import re

# 称呼后允许跟的边界字符（单字符集合，含常见时间/请求词的首字）。
_ADDRESS_BOUNDARY_CHARS = set("，,。！？!?：:、 的了呢吗呀啊哈今明天现在请帮我你请问呼")
_CALL_PATTERN = re.compile(r"(?:呼叫|召唤|在吗|@|＠)\s*([^\s，。！？!?：:、@＠]+)")


def normalize_mention_text(text: str) -> str:
    """去掉开头的 @/斜杠/感叹号/空白，便于做昵称前缀判定。"""
    stripped = (text or "").strip()
    return re.sub(r"^[@＠!！/\\\s]+", "", stripped)


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
        pattern = re.compile(
            rf"(?:^|[^\w\u4e00-\u9fff]){re.escape(term)}(?P<after>[\s，,。！？!?：:、]|$)"
        )
        if pattern.search(stripped):
            return True
        # 呼叫/召唤/在吗 + 昵称。
        call_match = _CALL_PATTERN.search(stripped)
        if call_match and call_match.group(1) == term:
            return True
    return False

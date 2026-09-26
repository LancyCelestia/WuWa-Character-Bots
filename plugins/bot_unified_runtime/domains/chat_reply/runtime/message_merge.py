"""「第 9 项」行为规格的可判定规则与参数件（用户 2026-09-27 04:3x 睡前定稿）。

本模块只回答三条规格里「该不该、算不算」这一半，长出的是**判据**不是通路：

1. 折句等待窗口固定 3 秒——``MERGE_WINDOW_SECONDS`` +
   ``apply_merge_window_seconds``，应用在既有折句器（message_coalescing）上，
   不新建第二台折句器；
2. bot 已回复后对方再发裸表情/贴纸 → 「静默」类——
   ``is_lone_emoji_or_sticker`` / ``should_silence_emoji_reaction``
   是**可判定规则函数**（有入参、有判据、可单测），刻意不写死白名单；
3. 同一句里命令 + 自然语言双触发——``command_natural_remainder`` 判定
   「命令头之外的自然语言尾巴」，装配段据此让人格回复与命令执行并行。

怎么回复、何时投递仍由既有链路（pipeline / send_queue / history）负责——
这里不长出第二条通路。
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 只为类型口径，运行期零新增依赖
    from .message_coalescing import CoalescingSettings

# ---------------------------------------------------------------------------
# 规格 1：折句等待窗口
# ---------------------------------------------------------------------------

# 用户 2026-09-27 裁定 3s：同人连发的下一条在上一条停口 3 秒内到达，
# 即折进同一轮（此前 2026-09-25 设计值 1.8s，睡前定稿把窗口值钉为 3 秒）。
# 本波不加 config 键 ⇒ 窗口值以模块常量为权威；其余折句参数
# （enabled / max_hold / max_messages / max_chars）仍从 Config 现读。
MERGE_WINDOW_SECONDS = 3.0


def apply_merge_window_seconds(settings: CoalescingSettings) -> CoalescingSettings:
    """把既有折句设置的等待窗口换成 3 秒裁定值，其余字段原样保留。

    只动 ``quiet_seconds`` 一个维度：封顶（max_hold/max_messages/max_chars）
    语义不变 ⇒ 「绝不吞消息」的既有护栏逐字节保留。
    （CoalescingSettings 是 frozen dataclass ⇒ 用 dataclasses.replace，
    不是 pydantic 的 model_copy——本席位首稿踩此坑，单测锁住。）
    """
    return replace(settings, quiet_seconds=MERGE_WINDOW_SECONDS)


# ---------------------------------------------------------------------------
# 规格 3：命令 + 自然语言双触发
# ---------------------------------------------------------------------------

# 双触发命令头集合：只收「整条命令本就无参数、尾随文字今天会坠进 help 兜底」
# 的命令（现算 _handle_status 的 elif 链：queue/readiness/llm/config/pause/
# resume/history clear 为精确相等分支，status 为 else 兜底支）。
# 带真参数的命令（context/why/receipt/model/runtime/…）一律不入集 ⇒
# 其尾随文本仍是命令参数，既有语义逐字节不变。
DUAL_TRIGGER_COMMAND_HEADS = frozenset(
    {
        "status",
        "queue",
        "readiness",
        "llm",
        "config",
        "roles",
        "persona",
        "pause",
        "resume",
        "history clear",
    }
)

# 余文形状黑名单：长成参数/开关样式的词不配当「顺带说一句」，
# 按原语义（help 兜底）处理。只收紧、不放宽既有分派。
_ARGUMENT_LIKE_REMAINDERS = frozenset(
    {
        "help",
        "on",
        "off",
        "list",
        "clear",
        "set",
        "get",
        "add",
        "del",
        "status",
        "true",
        "false",
    }
)

# 命令形态起手符：以这些开头的余文是「下一条命令」，不是自然语言。
_COMMAND_LIKE_START = "/!！#．.·>-"

# 至少含一个中日韩汉字或拉丁字母才算「说了句话」；纯数字/纯符号不是。
_LETTER_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ffA-Za-z]")


def _looks_natural_remainder(remainder: str) -> bool:
    """余文是否像「顺带说的一句自然语言」（可判定四则，全部满足才是）。

    ① 去空白后长度 ≥2；② 不以命令形态起手符开头、不含 ``=``/``;`` 赋值符；
    ③ 不是参数样词（黑名单）也不是纯数字；④ 至少含一个汉字/假名/字母。
    判据刻意保守：任何一条不满足都按「不是自然语言尾巴」处理 ⇒ 宁可维持
    旧行为（help 兜底/参数语义），不多头回复。
    """
    text = remainder.strip()
    if len(text) < 2:
        return False
    if text[0] in _COMMAND_LIKE_START:
        return False
    if any(ch in text for ch in "=;；"):
        return False
    if text.lower() in _ARGUMENT_LIKE_REMAINDERS:
        return False
    if text.isdigit():
        return False
    return bool(_LETTER_RE.search(text))


def command_natural_remainder(command_text: str) -> str | None:
    """命令正文里「无参数命令头 + 自然语言尾巴」的尾巴部分；不成对则 None。

    返回非 None ⇒ 装配段应「命令照常执行、尾巴另走人格回复」（双触发，
    覆盖旧口径「命中命令就不走人格回复」）。用户定稿例：
    ``status 顺便说两句`` → ``"顺便说两句"``。
    ``status``（纯命令）→ None；``context list``（头带参数）→ None。
    多头重合按最长头优先（"history clear" 先于任何单 token）。
    """
    text = str(command_text or "").strip()
    if not text:
        return None
    for head in sorted(DUAL_TRIGGER_COMMAND_HEADS, key=len, reverse=True):
        if text == head:
            return None  # 纯命令：不多余回复
        if text.startswith(f"{head} "):
            remainder = text[len(head) :].strip()
            return remainder if _looks_natural_remainder(remainder) else None
    return None


# ---------------------------------------------------------------------------
# 规格 2：裸表情/贴纸静默（可判定规则，非白名单）
# ---------------------------------------------------------------------------

# 表情/贴纸段类型集（现算根摄取口径 671 行的视觉段全集里，只有这四类是
# 「表情/贴纸」；image/photo/video/record 等一律**不进**静默类——纯图可能是
# 真照片求解读，视觉理解链路（需求 3）不许被本规格误伤）。
EMOJI_SEGMENT_TYPES = frozenset({"face", "mface", "marketface", "sticker"})
# 不承载正文的结构段：引用与 @ 不破坏「裸表情」判定（回复机器人再发表情
# 正是定稿点名的静默场景；@ 与否由点名豁免裁决，见
# ``should_silence_emoji_reaction`` 判据③）。
_CONTENT_NEUTRAL_SEGMENT_TYPES = frozenset({"text", "reply", "at"})

# 摄取层对纯媒体消息补的占位文案（根 __init__.py 摄取函数现算）——
# 判「无正文」时必须连同它一起剥掉，否则占位串自己成了「有话」。
_INGRESS_PLACEHOLDER_TEXTS = frozenset(
    {
        "（用户发送了语音消息，未附文字。）",
        "（用户发送了图片/表情包/视频，未附文字。）",
    }
)

# QQ get_plaintext 风格的方括号表情词（[表情][图片]…）：剥除后看是否还有正文。
_BRACKET_TOKEN_RE = re.compile(r"\[[^\[\]\n]{1,12}\]")

# Unicode 表情符号码位带（可判定「这段文字只是表情」的核心依据；按区间列举，
# 不用白名单枚举具体表情）。
_EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x2600, 0x27BF),  # 杂项符号与装饰符号（☀…➿）
    (0x2B00, 0x2BFF),  # 箭头与星号（⬆⭐…）
    (0xFE00, 0xFE0F),  # 变体选择符（决定表情/文字呈现）
    (0x1F000, 0x1FAFF),  # 牌面、表情、交通、补充符号等表情大区
)
# 零宽连接符（多人/道具组合表情）与常见中文留白标点。
_INVISIBLE_OR_NOISE = frozenset("\u200d\u200b\u2060 \t\r\n")
_PUNCTUATION_NOISE = "。！？!?.~～…—－-·﹏，,、；:：\"“”‘’()（）[]【】"


def _is_emoji_codepoint(code: int) -> bool:
    return any(low <= code <= high for low, high in _EMOJI_RANGES)


def _cosmetic_only(text: str) -> bool:
    """这段文本剥掉表情/占位/方括号表情词/标点噪声后是否什么都不剩。

    占位串先按**整串原文**摘除（先剥标点再把占位串拆成残词会永远比不中）。
    """
    probe = _BRACKET_TOKEN_RE.sub("", str(text or ""))
    for placeholder in _INGRESS_PLACEHOLDER_TEXTS:
        probe = probe.replace(placeholder, "")
    probe = "".join(
        " " if _is_emoji_codepoint(ord(ch)) else ch for ch in probe
    )
    probe = probe.translate(
        {ord(ch): None for ch in _INVISIBLE_OR_NOISE | set(_PUNCTUATION_NOISE)}
    )
    return not probe.strip()


def _contains_emoji(text: str) -> bool:
    return any(_is_emoji_codepoint(ord(ch)) for ch in str(text or ""))


def is_lone_emoji_or_sticker(message: Any) -> bool:
    """这条消息是否「裸表情/贴纸」——五则判据全过才算（可判定，非白名单）：

    ① 非邮件面（邮件一封一线程，表情当新线程处理，静默会错接回信）；
    ② 有段可依：``raw_segments`` 非空，且每段类型 ∈ 表情贴纸四类
       ∪ {text, reply, at}；出现 image/video/record/forward/file 等任何
       其他段 ⇒ 一律不算裸表情（护视觉理解与语音链路）；
    ③ 至少一枚表情贴纸段，**或**纯文本段本身只是 Unicode 表情
       （``😄😄``）；
    ④ 文本不承载正文：方括号表情词、摄取占位串、标点噪声剥光后为空；
    ⑤ 判据只看消息本体，会话状态在 ``should_silence_emoji_reaction`` 里另裁。
    """
    platform = str(getattr(message, "platform", "") or "").strip().lower()
    session_id = str(getattr(message, "session_id", "") or "")
    if platform == "mail" or session_id.startswith("email:"):
        return False
    segments = list(getattr(message, "raw_segments", None) or [])
    if not segments:
        return False
    has_emoji_segment = False
    text_buffer: list[str] = []
    for segment in segments:
        seg_type = str(segment.get("type", "")).strip().lower()
        if seg_type in EMOJI_SEGMENT_TYPES:
            has_emoji_segment = True
            continue
        if seg_type not in _CONTENT_NEUTRAL_SEGMENT_TYPES:
            return False
        if seg_type == "text":
            data = segment.get("data") or {}
            text_buffer.append(str(data.get("text", "") or ""))
    joined_text = "".join(text_buffer)
    if has_emoji_segment:
        return _cosmetic_only(joined_text)
    return bool(joined_text.strip()) and _contains_emoji(joined_text) and (
        _cosmetic_only(joined_text)
    )


def should_silence_emoji_reaction(
    message: Any,
    *,
    last_turn_role: str | None,
) -> bool:
    """裸表情是否落「静默」类——在 ``is_lone_emoji_or_sticker`` 之上再裁两条。

    用户口径「得看情况」在这里的落地（判据全可判定、可单测）：

    ① 消息本体是裸表情/贴纸（判据见上函数 docstring）；
    ② **bot 已回复过**：该(会话,发送者)最近一条对话轮次 role ==
       ``"assistant"``（装配段从既有 conversation history 现读 max_turns=1；
       读不到/为空/未回复 ⇒ 不静默，表情可能正是开场提问）；
    ③ 点名豁免：群聊里 @/人格名/软点名过 bot 的表情是**在叫它**，不静默
       （私聊 mentions_bot 恒真，不套本豁免，否则私聊表情永不再理）；
    ④ 邮件面永不静默（①已拦，此处双保险）。

    注意：回复/引用 bot 消息再发裸表情 **算** 静默（谢谢表情场景）；
    普通照片、语音、转发不属表情类，判据②③对它们根本不触发。
    """
    if not is_lone_emoji_or_sticker(message):
        return False
    if str(last_turn_role or "").strip().lower() != "assistant":
        return False
    session_type = str(
        getattr(getattr(message, "session_type", None), "value", "") or ""
    ).lower()
    return not (
        session_type == "group"
        and (
            bool(getattr(message, "mentions_bot", False))
            or bool(getattr(message, "name_mention_only", False))
            or bool(getattr(message, "soft_persona_mention", False))
        )
    )

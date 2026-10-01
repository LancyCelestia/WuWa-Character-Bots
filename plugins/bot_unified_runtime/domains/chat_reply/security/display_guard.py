"""第三方文本面的显示伪装咽喉（ANTIATTACK P2-d · 用户需求 17，席位 ATK-P2D，2026-09-29）。

**为什么需要这一件**：登记件 `attack_surface.find_visual_spoof_controls` 只出信号；
处置口 `injection.render_safe_display_name` 管的是**标签形**（昵称/群名片/文件名/贴纸名
——短到可以「救不回来就整格屏蔽」）。但攻击者的输入不止短标签：群公告、群名、
转发的聊天记录、抓取回来的网页正文、他写的备注，都是**长文本**。长文本套用
标签口径会出事——`fold_spoofed_role_keywords` 对整段做 NFKC，会把「：」（U+FF1A）
折成半角冒号、把「①」折成「1」，等于替用户重写了一遍文章；整格屏蔽更是把
一整段公告换成一个占位。所以文本面必须有**自己的处置口径**，但它**必须有同一个判据**。

分工（禁第二通路，本件的可读契约）：
- **判据唯一真身**＝`domains/core/safety_exec/attack_surface.py`（Bidi 表、零宽表、
  同形表、角色词表全在那件里）。本件**一张表都不抄**，只调函数；由
  `tests/test_atk_p2d_display_guard_throat.py` 的结构锁执法（源码里出现字面控制
  字符或自建 `_CONFUSABLE_MAP`/`LOOKALIKE_MAP`/`_BIDI_CONTROLS` 即红）。
- **标签形处置口唯一真身**＝`injection.render_safe_display_name`（本件的 `guard_label`
  只是它的一层薄壳，取证也在咽喉里记一次，不重复记账）。
- **文本形处置**＝本件 `guard_text`：逐条复用「不可见剥除 + 逐词同形折形 + 边界标记
  全角化」三枚既有真身，加两条长文本才需要的动作（控制字符过滤、空白填充压缩）。
- **取证**＝`spoof_audit`（指纹 + 标签 + 字节数，不留原文）。

显示层与语义层的关系（需求 17 第①条）：本件**同时**给显示面与 prompt 面用，
两侧拿到的是**同一串字节**——「显示一个意思、喂进去另一个意思」正是被 RLO/零宽
伪装出来的效果，消毒把肉眼形态与真实码点对齐后，两侧自然一致。剩下「这句话是谁
说的」那一层语义仍由 `injection.check_prompt_injection` /
`injection.guard_secondhand_text`（不可信包裹）负责，本件不越界定权：
`guard_text` 只**附带信号**（`GuardedText.signals`），由调用方决定是否包壳。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from plugins.bot_unified_runtime.domains.chat_reply.security import spoof_audit
from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
    neutralize_internal_markers,
    render_safe_display_name,
)
from plugins.bot_unified_runtime.domains.core.safety_exec import (
    attack_surface as _attack_surface,
)

__all__ = [
    "SPOOF_SUPPRESSED_TOKEN",
    "GuardedText",
    "guard_label",
    "guard_text",
    "guard_text_signals",
    "neutralize_visual_spoof",
    "text_spoof_signals",
]

#: 行内连续空白（空格/制表）的上限：攻击者用长串空白把关键指令挤到截断窗口之外，
#: 项目已被「策略段曾被尾裁静吃」咬过一次（台账 #66★），填充因此不值一个字节。
_INLINE_BLANK_RE = re.compile(r"[ \t]{3,}")
#: 空行上限（保留段落感：段落之间最多一枚空行）。
_MAX_BLANK_RUN = 1


@dataclass(frozen=True)
class GuardedText:
    """消毒结果 + 信号。``text`` 是**唯一**可以进显示面或 prompt 的串。"""

    text: str
    changed: bool = False
    signals: tuple[str, ...] = field(default_factory=tuple)


def guard_label(value: object, *, surface: str = "label") -> str:
    """标签形（昵称/群名片/文件名/贴纸名/头衔）：直接交咽喉，取证在咽喉里记。

    刻意**不**在这里再调一次 `spoof_audit.record`——同一串过两道记账就成了双花账。
    """
    return render_safe_display_name(str(value or ""), surface=surface)


def text_spoof_signals(value: object) -> tuple[str, ...]:
    """只读信号（审计/回执用），判据完全取自登记谓词，本件零副本。"""
    try:
        return _attack_surface.find_visual_spoof_controls(str(value or ""))
    except Exception:  # noqa: BLE001 - 信号件坏了不该拖垮显示面
        return ()


def neutralize_visual_spoof(value: object, *, surface: str = "text") -> str:
    """只做**显示伪装**那一半（不碰块边界标记），给已有自己的边界消毒口的落点用。

    引用链件（`ingest/message_context.py`）今天用 `_neutralize_markers` 把
    `[引用回复 层级1 澜汐]` 一类**带尾巴**的标记换成 `［…尾巴］`，而本件的
    `guard_text` 走 `injection.neutralize_internal_markers`（尾巴会被抹掉、名字大写）。
    两形都是在册口径，但**同一块不能今天留尾巴明天抹掉**——所以引用链腿只借本件的
    伪装半，边界半仍由它自己那一枚真身（同一份 `INTERNAL_MARKER_PATTERN`）管。
    顺序固定：伪装 → 边界（反过来会把 `［］` 当名字的一部分喂给谓词）。
    """
    raw = str(value or "")
    if not raw:
        return ""
    signals = text_spoof_signals(raw)
    authority = _authority_claim_signals(raw)

    text = _attack_surface.strip_display_controls(raw)
    text, folded = _fold_disguised_tokens(text)
    text, control_dropped = _drop_control_characters(text)
    text, padded = _collapse_padding(text)

    changed = text != raw
    if changed or folded or control_dropped or padded or bool(signals) or bool(authority):
        spoof_audit.record(
            surface=surface,
            original=raw,
            result=text,
            tags=tuple(signals) + tuple(authority),
        )
    return text


def guard_text(value: object, *, surface: str = "text") -> str:
    """长文本面消毒的唯一出口（公告/群名/抓取内容/备注）：伪装半 + 边界半。"""
    return guard_text_signals(value, surface=surface).text


def guard_text_signals(value: object, *, surface: str = "text") -> GuardedText:
    """`guard_text` + 顺带把「这段话声称自己是谁」的信号交回调用方（不据此定权）。

    处置动作按序四步，每一步都只调既有真身：
    ① `attack_surface.strip_display_controls`——剥肉眼不可见的伪装（Bidi 覆写/隔离、
       零宽一族；表情 ZWJ 连字在册豁免，同一把尺）；
    ② 逐**词** `attack_surface.fold_spoofed_role_keywords`——只对「折出来是角色词」
       的那个词动手（``ａdmin``→``admin``）。逐词而不是整段：整段 NFKC 会改写
       中文标点与带圈数字，误伤一次就等于替用户重写一遍公告。折完仍命中伪装门的
       词（表覆盖不到的第三种文字混在里面）整词换成 ``SPOOF_SUPPRESSED_TOKEN``；
    ③ 过滤 C0/C1 控制字符（`\n` 保留，`\r` 统一成 `\n`）——这一族不在伪装码点表里
       （它们是终端控制语义，不是显示伪装），按 Unicode 通用类别 ``Cc`` 判，
       不新增码点清单；
    ④ 压缩空白填充（长串空格 / 多余空行），防「关键指令被挤到截断窗口外」；
    ⑤ `injection.neutralize_internal_markers`——块边界标记全角化（唯一真身
       `INTERNAL_MARKER_PATTERN`），令转述文本无法伪造 `[TRUSTED_SYSTEM]` 提前闭合。

    干净文本恒等返回（不误伤是这条防线存在的条件）；有任何改写就记一条取证。
    """
    raw = str(value or "")
    if not raw:
        return GuardedText(text="")
    neutralized = neutralize_visual_spoof(raw, surface=f"{surface}.spoof")
    text = neutralize_internal_markers(neutralized)
    return GuardedText(
        text=text,
        changed=text != raw,
        signals=text_spoof_signals(raw) + _authority_claim_signals(raw),
    )


#: 折完**仍然**触发角色词伪装的词（同形表覆盖不到的第三种文字混在里面，例如
#: 「西里尔 + 奇字符 + 拉丁」）：那一格换成占位，宁可少给一个词，不给一个
#: 「看起来已经正常、码点却还在骗眼」的词。与标签面的 `SPOOF_SUPPRESSED_DISPLAY`
#: 同一教义，只是射程缩到一个词。刻意用「」不用方括号——方括号是块边界标记的地盘。
SPOOF_SUPPRESSED_TOKEN = "「伪装词已屏蔽」"


def _fold_disguised_tokens(text: str) -> tuple[str, bool]:
    """逐词折同形伪装（判据仍来自登记谓词，本函数只负责把射程缩到一个词）。

    两步而不是折完就交出去：折一次 → 再问一次谓词。折形表只覆盖常见
    西里尔/希腊/全角近似形，混了第三种文字的 token 折完仍是混码（现算实测：
    `aдminꄓ` 一类折出来还挂着 `homoglyph_role_keyword`）。那种「假干净」比原样
    放行更坏——肉眼看着正常、码点仍在骗人，且下游不会再有人查它。所以按
    「折了还不干净就整词屏蔽」收口。
    """
    folded_any = False
    out: list[str] = []
    for piece in re.split(r"(\s+)", text):
        if not piece or piece.isspace():
            out.append(piece)
            continue
        folded = _attack_surface.fold_spoofed_role_keywords(piece)
        if folded != piece:
            folded_any = True
            still = _attack_surface.find_visual_spoof_controls(folded)
            if any(str(tag).startswith("homoglyph_role_keyword") for tag in still):
                folded = SPOOF_SUPPRESSED_TOKEN
        out.append(folded)
    return "".join(out), folded_any


def _drop_control_characters(text: str) -> tuple[str, bool]:
    """丢 C0/C1 控制字符（`\n` 与 `\t` 除外；`\r` 折进 `\n`）。

    用 Unicode 通用类别而不是码点清单——本件不许长出第二张表（结构锁在同批测试里）。
    """
    if not any(unicodedata.category(ch) == "Cc" and ch not in ("\n", "\t") for ch in text):
        return text, False
    kept: list[str] = []
    for ch in text:
        if ch == "\r":
            continue
        if unicodedata.category(ch) == "Cc" and ch not in ("\n", "\t"):
            continue
        kept.append(ch)
    return "".join(kept), True


def _collapse_padding(text: str) -> tuple[str, bool]:
    """压长串行内空白 + 限空行数：填充不该把内容挤出可见/可读窗口。"""
    collapsed = _INLINE_BLANK_RE.sub(" ", text)
    lines = collapsed.split("\n")
    out: list[str] = []
    blank = 0
    for line in lines:
        if not line.strip():
            blank += 1
            if blank > _MAX_BLANK_RUN:
                continue
        else:
            blank = 0
        out.append(line)
    return "\n".join(out), ("\n".join(out) != collapsed)


def _authority_claim_signals(text: str) -> tuple[str, ...]:
    """「这段话自称系统/超管」的信号，判据取自在册谓词 `detect_authority_rewrite`。

    **只出信号**：定权唯一住 `safety_exec/trust.py` 的结构化派生，本件把
    「自称」写成「自称」而不是「他就是」，也绝不因为命中就把整段判死。
    """
    try:
        hit = _attack_surface.detect_authority_rewrite(text)
    except Exception:  # noqa: BLE001 - 谓词坏了不拖垮显示面（fail-open 于显示、取证另记）
        return ("authority_scan_failed",)
    if not getattr(hit, "claims_authority", False):
        return ()
    forms = tuple(getattr(hit, "forms", ()) or ())
    return tuple(f"authority_claim:{form}" for form in forms) or ("authority_claim:unnamed",)

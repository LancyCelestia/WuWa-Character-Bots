"""出站段落分隔统一化回归（2026-10-06 用户裁定：段间空一行、段内不换行）。

规则：chat 出站文本段间一律一个空行——括号拆段路径、无动作纯文本路径、
模型自写空行三路同构。
"""
from __future__ import annotations

from plugins.bot_unified_runtime.output.roleplay import (
    format_roleplay_paragraphs,
    normalize_paragraph_breaks,
    strip_action_brackets,
)


def test_action_and_speech_joined_with_blank_line() -> None:
    text = "（轻轻走近）你好呀。\n（坐下）最近怎么样？"
    out = format_roleplay_paragraphs(text)
    # 动作与说话各占一段（既有语义），段间空一行。
    assert out == "（轻轻走近）\n\n你好呀。\n\n（坐下）\n\n最近怎么样？"


def test_model_blank_lines_collapsed_to_one_blank() -> None:
    text = "（抬头看你）\n\n\n我们走吧。"
    out = normalize_paragraph_breaks(format_roleplay_paragraphs(text))
    assert out == "（抬头看你）\n\n我们走吧。"


def test_pure_text_blank_lines_collapsed() -> None:
    text = "第一段。\n\n第二段。\n \n第三段。"
    assert normalize_paragraph_breaks(text) == "第一段。\n\n第二段。\n\n第三段。"


def test_trailing_whitespace_and_blank_lines_stripped() -> None:
    text = "开头。\n\n  \n结尾。  \n\n"
    assert normalize_paragraph_breaks(text) == "开头。\n\n结尾。"


def test_empty_and_plain_passthrough() -> None:
    assert normalize_paragraph_breaks("") == ""
    assert normalize_paragraph_breaks("单行文本") == "单行文本"
    assert normalize_paragraph_breaks(None) == ""  # type: ignore[arg]


def test_strip_action_brackets_preserves_blank_line_between_parts() -> None:
    text = "（轻轻走近）\n\n你好呀。\n\n（坐下）\n\n最近怎么样？"
    out = strip_action_brackets(text)
    # 括号动作被删后，剩余文字之间的空行保留。
    assert out == "你好呀。\n\n最近怎么样？"


def test_strip_action_brackets_single_line_stays_single_line() -> None:
    text = "（轻轻走近）你好呀。（坐下）最近怎么样？"
    out = strip_action_brackets(text)
    # 输入无换行 ⇒ 输出也无换行（不凭空造分段）。
    assert out == "你好呀。最近怎么样？"


def test_strip_action_brackets_collapses_excess_blank_lines() -> None:
    text = "（动作一）\n\n\n第一段。\n\n\n\n（动作二）\n\n第二段。"
    out = strip_action_brackets(text)
    assert out == "第一段。\n\n第二段。"

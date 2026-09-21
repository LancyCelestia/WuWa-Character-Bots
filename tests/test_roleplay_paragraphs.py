"""出站段落分隔统一化回归（2026-09-17 用户反馈：换行 1/2 个随机）。

规则：chat 出站文本段间一律单个换行——括号拆段路径、无动作纯文本路径、
模型自写空行三路同构。
"""
from __future__ import annotations

from plugins.bot_unified_runtime.output.roleplay import (
    format_roleplay_paragraphs,
    normalize_paragraph_breaks,
)


def test_action_and_speech_joined_with_single_newline() -> None:
    text = "（轻轻走近）你好呀。\n（坐下）最近怎么样？"
    out = format_roleplay_paragraphs(text)
    assert "\n\n" not in out
    # 动作与说话各占一段（既有语义），段间统一单换行。
    assert out == "（轻轻走近）\n你好呀。\n（坐下）\n最近怎么样？"


def test_model_blank_lines_collapsed_in_action_path() -> None:
    text = "（抬头看你）\n\n我们走吧。"
    out = normalize_paragraph_breaks(format_roleplay_paragraphs(text))
    assert out == "（抬头看你）\n我们走吧。"


def test_pure_text_blank_lines_collapsed() -> None:
    text = "第一段。\n\n第二段。\n \n第三段。"
    assert normalize_paragraph_breaks(text) == "第一段。\n第二段。\n第三段。"


def test_trailing_whitespace_and_blank_lines_stripped() -> None:
    text = "开头。\n\n  \n结尾。  \n\n"
    assert normalize_paragraph_breaks(text) == "开头。\n结尾。"


def test_empty_and_plain_passthrough() -> None:
    assert normalize_paragraph_breaks("") == ""
    assert normalize_paragraph_breaks("单行文本") == "单行文本"
    assert normalize_paragraph_breaks(None) == ""  # type: ignore[arg]

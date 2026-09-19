"""触发劫持回归（TTS-T-Spec 防劫持：分隔符集合里不得有词字符）。

审计实证（`.superpowers/sdd/2026-09-19-unify-audit/`，2026-09-19 波）：
`_TEXT_BOUNDARY_CHARS` 把「了/的/呢/吗/呀/啊/哈」这批高频虚词当成**触发词与正文
之间的分隔符**，于是日常聊天句只要以触发词开头、下一字恰是虚词，就被整句吞进
`bot.tts`（priority 41 + block=True ⇒ 消息不再进对话）。实测 312 句日常中文里
68.1% 被劫持，典型形态是把一个词或单字念出来：

- 「说了再见」→ 合成「再见」；
- 「说的对」→ 合成「对」（单字语音）；
- 「语音哈喽」→ 合成「喽」。

修复口径：边界集合只留**真分隔符**（标点与空白），虚词一律退出；触发词后必须是
标点或空白才算命令，否则交回人格对话。全离线，零网络零落盘。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    extract_tts_text,
    is_tts_command,
)

# 曾被劫持的日常句（审计席 T15/D7/T19 实跑样本 + 本文件补齐的同族），
# 逐条要求：不占路由（取正文得空串）。
_HIJACK_SAMPLES: list[str] = [
    "说了再见",
    "说的对",
    "说的没错",
    "说了吧",
    "说了一半就停了",
    "语音哈喽",
    "语音了呢",
    "念了一遍就放下",
    "念的和写的不一样",
    "说的什么呀",
    "语音吗这个",
    "说是说了，可我忘了",
    "朗读的话其实不必",
    "说真的，我有点担心你",
]

# 真命令（含标点/空白分隔的各种写法）必须原样取得正文，不能被修复顺手砍掉。
_REAL_COMMANDS: list[tuple[str, str]] = [
    ("说 今天的潮汐很安静", "今天的潮汐很安静"),
    ("说，今天的潮汐很安静", "今天的潮汐很安静"),
    ("说：今天很安静", "今天很安静"),
    ("念 一段静夜思", "一段静夜思"),
    ("语音 你好呀", "你好呀"),
    ("语音合成，今天天气不错", "今天天气不错"),
    ("朗读  海风很温柔", "海风很温柔"),
    ("tts hello shorekeeper", "hello shorekeeper"),
    ("say 今天很安静", "今天很安静"),
    ("说。安静一点", "安静一点"),
]

# 既有反例（包含关系词不误触发）——修复后必须仍然不触发。
_SUBSTRING_SAMPLES: list[str] = [
    "说话要注意分寸",
    "念书的时候我喜欢靠窗",
    "语音消息我没听到",
    "说好的呢",
    "明天下雨吗",
]


@pytest.mark.parametrize("text", _HIJACK_SAMPLES)
def test_function_words_do_not_hijack_chat(text: str) -> None:
    assert extract_tts_text(text) == "", f"{text} 不该被当成合成命令"
    assert not is_tts_command(text), f"{text} 不该占 TTS 路由"


@pytest.mark.parametrize("text,expected", _REAL_COMMANDS)
def test_real_commands_still_extract(text: str, expected: str) -> None:
    assert extract_tts_text(text) == expected


@pytest.mark.parametrize("text", _SUBSTRING_SAMPLES)
def test_substring_words_still_not_triggered(text: str) -> None:
    assert extract_tts_text(text) == ""


def test_bare_trigger_still_returns_empty_for_guidance(text: str = "说") -> None:
    """裸触发词不带正文：仍返回空串（由调用方给引导文案，既有口径不动）。"""
    assert extract_tts_text(text) == ""


def test_boundary_chars_contain_no_word_characters() -> None:
    """棘轮：分隔符集合里不得出现任何汉字——出现即回到本条劫持的根因。"""

    def _is_cjk(char: str) -> bool:
        return "㐀" <= char <= "鿿" or "぀" <= char <= "ヿ"

    offenders = [c for c in tts_mod._TEXT_BOUNDARY_CHARS if _is_cjk(c)]
    assert offenders == [], f"边界集合混入词字符：{offenders}"


def test_boundary_chars_are_punctuation_and_space_only() -> None:
    """棘轮：分隔符只能是空白或 ASCII/中文标点。"""
    allowed = set("，,。！？!?：:、 　\t～~-.…—\"'“”‘'()（）[]【】;；")
    offenders = [c for c in tts_mod._TEXT_BOUNDARY_CHARS if c not in allowed]
    assert offenders == [], f"边界集合出现非分隔字符：{offenders}"


# --- 路由层锁（审计席 T39 指名：谓词层有锁不等于路由层有锁）-----------------

_TTS_ROUTE_CONFIG = SimpleNamespace(bot_tts_enabled=True, bot_tts_trigger_words=[])


def _tts_rule():
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
        build_route_rules,
    )

    return next(r for r in build_route_rules() if r.capability_id == "bot.tts")


@pytest.mark.parametrize("text", _HIJACK_SAMPLES + _SUBSTRING_SAMPLES)
def test_route_layer_does_not_claim_chat_text(text: str) -> None:
    """日常聊天在**路由层**就不该产出 RouteKind.TTS（block=True 会整条吞掉对话）。"""
    assert _tts_rule().matcher(text, _TTS_ROUTE_CONFIG, None) is None


@pytest.mark.parametrize("text,_expected", _REAL_COMMANDS)
def test_route_layer_still_claims_real_commands(text: str, _expected: str) -> None:
    decision = _tts_rule().matcher(text, _TTS_ROUTE_CONFIG, None)
    assert decision is not None and decision.capability_id == "bot.tts"


def test_route_layer_respects_master_switch() -> None:
    """总闸关：路由必须不再产出 TTS（关总闸止血这条路要锁住）。"""
    off = SimpleNamespace(bot_tts_enabled=False, bot_tts_trigger_words=[])
    assert _tts_rule().matcher("说 今天的潮汐很安静", off, None) is None

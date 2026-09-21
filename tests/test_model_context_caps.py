"""全局上下文钳制回归（2026-09-17 用户裁定：输入 128K / 输出 64K）。"""
from __future__ import annotations

from plugins.bot_unified_runtime.llm.model_router import (
    DEFAULT_MAX_INPUT_TOKENS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    _enforce_context_caps,
    _estimate_messages_tokens,
)


def _msg(role: str, text: str) -> dict[str, str]:
    return {"role": role, "content": text}


def test_estimator_cjk_vs_ascii() -> None:
    # CJK ≈1 token/字；ASCII ≈4 chars/token；每条 +8 开销。
    assert _estimate_messages_tokens([_msg("user", "一二三四五")]) == 5 + 8
    assert _estimate_messages_tokens([_msg("user", "abcdefgh")]) == 2 + 8


def test_output_cap_clamps_oversized_only() -> None:
    # 只封顶不托底：未设/0 保持「模型自行决定」既有契约（providers 语义）。
    options: dict[str, object] = {"max_tokens": 65538}
    _enforce_context_caps([], options, DEFAULT_MAX_INPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS)
    assert options["max_tokens"] == 65536
    options2: dict[str, object] = {}
    _enforce_context_caps([], options2, DEFAULT_MAX_INPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS)
    assert "max_tokens" not in options2
    options3: dict[str, object] = {"max_tokens": 1024}
    _enforce_context_caps([], options3, DEFAULT_MAX_INPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS)
    assert options3["max_tokens"] == 1024  # 已有更小值不动


def test_input_cap_drops_oldest_non_system_first() -> None:
    tiny = 100
    messages = [
        _msg("system", "系统提示词"),
        _msg("user", "一" * 60),
        _msg("assistant", "二" * 60),
        _msg("user", "最新消息"),
    ]
    out = _enforce_context_caps(messages, {}, tiny, 65536)
    # 超限裁剪：最旧的非 system 先丢，system 与最新消息保留。
    assert out[0]["role"] == "system"
    assert out[-1]["content"] == "最新消息"
    assert _estimate_messages_tokens(out) <= tiny


def test_input_within_cap_untouched() -> None:
    messages = [_msg("system", "s"), _msg("user", "短消息")]
    out = _enforce_context_caps(messages, {}, DEFAULT_MAX_INPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS)
    assert out == messages

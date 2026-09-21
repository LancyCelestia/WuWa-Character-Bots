"""戳一戳 v2 离线单测：回复形态决策/回退链、@ 前置段渲染、sender at 段。

handler 级接线（LLM 超时/表情库调用）在 __init__ 闭包内，离线不覆盖；
此处覆盖全部纯函数决策面与渲染/发送段构造。
"""
from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.poke import (
    PokeDispatcher,
    PokeEvent,
    PokeLimiter,
    PokeReaction,
    resolve_poke_reply,
    resolve_poke_reply_mode,
)
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    ReviewAction,
    ReviewResult,
    RiskLevel,
)
from plugins.bot_unified_runtime.output.renderer import render_reviewed_output
from plugins.bot_unified_runtime.sender.onebot import _segment_from_mixed_part


def _config(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_poke_enabled": True,
        "bot_poke_private_cooldown_seconds": 30.0,
        "bot_poke_group_cooldown_seconds": 10.0,
        "bot_poke_probability": 1.0,
        "bot_poke_reply_enabled": True,
        "bot_poke_poke_back": True,
        "bot_poke_group_text": "",
        "bot_poke_private_text": "",
        "bot_poke_reply_mode": "mix",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _tick(clock_ticks: list[float]):
    return lambda: clock_ticks[0]


# ---------------------------------------------------------------- 形态决策

def test_explicit_mode_passthrough() -> None:
    assert resolve_poke_reply_mode(configured="llm", group="g", sender="u", bucket=1) == "llm"
    assert resolve_poke_reply_mode(configured="meme", group="g", sender="u", bucket=1) == "meme"
    assert resolve_poke_reply_mode(configured="fixed", group="g", sender="u", bucket=1) == "fixed"


def test_mix_mode_is_deterministic_per_bucket() -> None:
    first = resolve_poke_reply_mode(configured="mix", group="g", sender="u", bucket=7)
    assert resolve_poke_reply_mode(configured="mix", group="g", sender="u", bucket=7) == first
    assert resolve_poke_reply_mode(configured="mix", group="g", sender="u", bucket=7) == first
    # 形态必须落在合法集合内。
    assert first in {"fixed", "llm", "meme"}


def test_mix_mode_rotates_across_buckets() -> None:
    seen = {
        resolve_poke_reply_mode(configured="mix", group="g", sender="u", bucket=bucket)
        for bucket in range(24)
    }
    assert len(seen) >= 2  # 桶翻转必然带来形态轮换（确定性但非恒定）。


# ---------------------------------------------------------------- 回退链

def test_llm_text_used_when_present() -> None:
    text, image = resolve_poke_reply(
        "llm", fixed_text="固定话术", llm_text=" 你戳得我心头一暖。", meme_path=None
    )
    assert text == "你戳得我心头一暖。"
    assert image is None


def test_llm_empty_falls_back_to_fixed() -> None:
    text, image = resolve_poke_reply("llm", fixed_text="固定话术", llm_text="  ", meme_path=None)
    assert text == "固定话术"
    assert image is None


def test_meme_path_returns_pure_image() -> None:
    text, image = resolve_poke_reply("meme", fixed_text="固定话术", llm_text=None, meme_path="x:/a.gif")
    assert text == ""
    assert image == "x:/a.gif"


def test_meme_empty_falls_back_to_fixed() -> None:
    text, image = resolve_poke_reply("meme", fixed_text="固定话术", llm_text=None, meme_path=None)
    assert text == "固定话术"
    assert image is None


# ---------------------------------------------------------------- dispatcher mode

def test_dispatcher_sets_mode_and_audit_tags() -> None:
    clock_ticks = [1000.0]
    dispatcher = PokeDispatcher(clock=_tick(clock_ticks))
    event = PokeEvent(target_id="10000", user_id="42", group_id="200", sub_type="poke")
    reaction = dispatcher.build_poke_reaction(event, bot_id="10000", config=_config())
    assert reaction is not None and reaction.active
    assert reaction.mode in {"fixed", "llm", "meme"}
    assert any(tag.startswith("poke_mode:") for tag in reaction.audit_tags)
    assert isinstance(reaction, PokeReaction)


def test_dispatcher_explicit_llm_mode() -> None:
    dispatcher = PokeDispatcher(clock=lambda: 1000.0)
    event = PokeEvent(target_id="10000", user_id="42", group_id="", sub_type="poke")
    reaction = dispatcher.build_poke_reaction(
        event, bot_id="10000", config=_config(bot_poke_reply_mode="llm")
    )
    assert reaction is not None
    assert reaction.mode == "llm"
    assert "poke_mode:llm" in reaction.audit_tags


def test_limiter_cooldown_still_gates_all_modes() -> None:
    clock_ticks = [1000.0]
    limiter = PokeLimiter(clock=_tick(clock_ticks))
    event = PokeEvent(target_id="10000", user_id="42", group_id="", sub_type="poke")
    assert limiter.accept(event, "10000", True, 30.0, 10.0) is True
    clock_ticks[0] += 1.0
    assert limiter.accept(event, "10000", True, 30.0, 10.0) is False


# ---------------------------------------------------------------- @ 段渲染/发送

def test_sender_at_segment_construction() -> None:
    assert _segment_from_mixed_part({"type": "at", "qq": "12345"}) == {
        "type": "at",
        "data": {"qq": "12345"},
    }
    assert _segment_from_mixed_part({"type": "at", "data": {"qq": "678"}}) == {
        "type": "at",
        "data": {"qq": "678"},
    }
    assert _segment_from_mixed_part({"type": "at", "qq": ""}) is None


def test_renderer_prefix_parts_lead_mixed_output() -> None:
    result = CapabilityResult(
        request_id="req-1",
        capability_id="bot.poke",
        kind="text",
        body="我收到你的轻轻一碰了。",
        prefix_parts=[{"type": "at", "qq": "42"}],
    )
    review = ReviewResult(
        request_id="req-1",
        approved=True,
        action=ReviewAction.ALLOW,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        safe_text=result.body,
    )
    output = render_reviewed_output(result, review)
    assert output.content_type == "mixed"
    parts = output.content_ref["parts"]
    assert parts[0] == {"type": "at", "qq": "42"}
    assert parts[1]["type"] == "text"
    assert output.text_fallback == "我收到你的轻轻一碰了。"


def test_renderer_no_prefix_keeps_text_path() -> None:
    result = CapabilityResult(
        request_id="req-2",
        capability_id="bot.poke",
        kind="text",
        body="嗯，我在这里。",
    )
    review = ReviewResult(
        request_id="req-2",
        approved=True,
        action=ReviewAction.ALLOW,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        safe_text=result.body,
    )
    output = render_reviewed_output(result, review)
    assert output.content_type == "text"
    assert output.content_ref["text"] == "嗯，我在这里。"

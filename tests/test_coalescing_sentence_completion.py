"""任务 A（需求 1）：分句合并的**句子完结判定**升级 + 自适应停口窗 + ID 保全。

用户口径（2026-09-29）：按逗号断句、一句短句一个气泡；一句话被拆成 2 条以上时
bot 只回一次。判据从「这条本身像半句话」升级为可解释的句子完结判定——
**即使自带句号**，只要短、无句末终止语气、明显是被逗号/换行切断的同一句的延续、
或以连接词/量词/标点收尾，就继续等下一条。

本文件锁四件事：
① 判定是可解释的谓词组（信号名可点名，不是一长串硬编码 if）；
② 停口窗自适应（越像半句等得越久、越像说完等得越短），硬封顶到点必正常回复；
③ 合并轮保住**所有**原始 message_id（幂等/回执/补投要用）+ 引用链 + 段类型不丢图；
④ 命令气泡不折进等待；enabled=false 逐字节回旧行为。
"""

from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.runtime.message_coalescing import (
    CoalescingSettings,
    MessageCoalescer,
    effective_quiet_seconds,
    looks_unfinished,
    merge_turn,
    supports_coalescing,
    utterance_completion,
)

ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"


def _message(
    text: str,
    *,
    sender_id: str = "u1",
    session_id: str = "group_10_u1",
    session_type: SessionType = SessionType.GROUP,
    message_id: str | None = None,
    **kwargs: object,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot_v11",
        bot_id="3958874605",
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        plain_text=text,
        command_text=str(kwargs.pop("command_text", text)),
        message_id=message_id or f"m-{abs(hash((text, sender_id))) % 10**8}",
        **kwargs,  # type: ignore[arg-type]
    )


def _key(message: IncomingMessage) -> str:
    return f"{message.session_id}:{message.sender_id}"


# ---------------------------------------------------------------------------
# ① 可解释判定：信号名点名得出，判定对象带强度
# ---------------------------------------------------------------------------


def test_verdict_is_explainable_named_signals() -> None:
    verdict = utterance_completion("这个天气，")
    assert verdict.pending is True
    assert verdict.strength == pytest.approx(1.0)
    assert "trailing_hanging_punctuation" in verdict.signals


@pytest.mark.parametrize(
    ("text", "signal"),
    [
        ("我想请假因为", "trailing_connector"),
        ("想去但是", "trailing_connector"),
        ("先这样然后", "trailing_connector"),
        ("他说——", "trailing_dash"),
        ("名字叫「", "unclosed_left_quote"),
        ("买三", "trailing_quantity"),
        ("来两", "trailing_quantity"),
        ("第一段\n", "line_split_continuation"),
        ("，还有花房", "leading_continuation"),
        ("而且今天挺闲", "leading_continuation"),
        ("我今天去了", "no_terminal_short"),
    ],
)
def test_unfinished_signals_fire_by_name(text: str, signal: str) -> None:
    verdict = utterance_completion(text)
    assert verdict.pending is True, f"{text!r} 应判「未完」"
    assert signal in verdict.signals, f"{text!r} 实发信号={verdict.signals}"


@pytest.mark.parametrize("text", ["你在干嘛？", "好呀！", "走不走？", "真的吗？!"])
def test_strong_terminal_tone_never_waits(text: str) -> None:
    """？！这类句末终止语气＝话说完了：普通一来一回零额外延迟的硬底线。"""
    verdict = utterance_completion(text)
    assert verdict.pending is False
    assert looks_unfinished(text) is False


@pytest.mark.parametrize("text", ["今天天气不错。", "花房开了一朵。", "好的。"])
def test_short_period_bubbles_wait_with_reduced_strength(text: str) -> None:
    """用户点名场景：一句短句一个气泡、各自带句号——仍要开（短）窗等下一条。"""
    verdict = utterance_completion(text)
    assert verdict.pending is True
    assert 0.0 < verdict.strength < 1.0, "短句式收尾只该等短窗，不该等满窗"
    assert "short_burst_fragment" in verdict.signals


def test_long_weak_terminal_sentence_is_complete() -> None:
    """带句号但说得长而完整 ⇒ 不开窗（把延迟留给真连发）。"""
    text = "下午在花房把那株新开的小苗连土挖出来重新配了盆，顺手把浇水的频率也记进了台历。"
    verdict = utterance_completion(text)
    assert verdict.pending is False
    assert looks_unfinished(text) is False


def test_empty_text_is_not_pending() -> None:
    assert utterance_completion("").pending is False
    assert utterance_completion("   ").pending is False


# ---------------------------------------------------------------------------
# ② 自适应停口窗：强未完=满窗，弱未完=短窗；硬封顶到点必回、绝不静默丢
# ---------------------------------------------------------------------------


def test_effective_quiet_scales_with_strength() -> None:
    settings = CoalescingSettings(quiet_seconds=3.0)
    assert effective_quiet_seconds(settings, 1.0) == pytest.approx(3.0)
    mild = effective_quiet_seconds(settings, 0.5)
    assert mild < 3.0 and mild > 0.3, f"弱信号该缩窗但不该缩没，实={mild}"


@pytest.mark.asyncio
async def test_adaptive_window_strong_waits_longer_than_mild() -> None:
    """同一套参数：半句收尾等满窗，短句式句号收尾只等短窗（各回各的延迟账）。"""
    strong = MessageCoalescer(
        CoalescingSettings(quiet_seconds=1.0, max_hold_seconds=10.0)
    )
    msg = _message("守岸人，")
    started = time.monotonic()
    turn_strong = await strong.offer(_key(msg), msg)
    strong_elapsed = time.monotonic() - started

    mild = MessageCoalescer(
        CoalescingSettings(quiet_seconds=1.0, max_hold_seconds=10.0)
    )
    msg2 = _message("今天不错。")
    started = time.monotonic()
    turn_mild = await mild.offer(_key(msg2), msg2)
    mild_elapsed = time.monotonic() - started

    assert turn_strong.owned and turn_mild.owned
    assert strong_elapsed >= 0.6, f"强信号没等满窗（{strong_elapsed:.2f}s）"
    assert mild_elapsed <= strong_elapsed * 0.6 + 0.15, (
        f"自适应没生效：mild={mild_elapsed:.2f}s strong={strong_elapsed:.2f}s"
    )


@pytest.mark.asyncio
async def test_cap_hit_still_replies_with_content_not_silence() -> None:
    """封顶到点必正常回复：内容一字不丢，owned=True（绝不静默丢）。"""
    batcher = MessageCoalescer(
        CoalescingSettings(quiet_seconds=2.0, max_hold_seconds=0.3)
    )
    msg = _message("我想请假因为", message_id="cap-1")
    started = time.monotonic()
    turn = await batcher.offer(_key(msg), msg)
    assert time.monotonic() - started < 1.0, "封顶没兜住，会长期不回话"
    assert turn.owned is True
    assert turn.message.plain_text == "我想请假因为"


@pytest.mark.asyncio
async def test_burst_of_short_period_bubbles_replies_exactly_once() -> None:
    """用户主场景：短句一个气泡（各带句号）连发三条 ⇒ 只回一次、内容齐。"""
    batcher = MessageCoalescer(
        CoalescingSettings(quiet_seconds=0.5, max_hold_seconds=5.0)
    )
    a, b, c = (
        _message("今天天气不错。", message_id="p1"),
        _message("花房开了一朵。", message_id="p2"),
        _message("想带你去看。", message_id="p3"),
    )
    owner_task = asyncio.create_task(batcher.offer(_key(a), a))
    await asyncio.sleep(0.05)
    follower_a = await batcher.offer(_key(b), b)
    follower_b = await batcher.offer(_key(c), c)
    turn = await owner_task

    assert follower_a.owned is False and follower_b.owned is False
    assert turn.owned is True and turn.folded_count == 3
    assert "今天天气不错" in turn.message.plain_text
    assert "花房开了一朵" in turn.message.plain_text


# ---------------------------------------------------------------------------
# ③ ID 保全：合并轮带齐逐条 message_id；图片+文字段不丢；引用链保住
# ---------------------------------------------------------------------------


def test_merge_carries_every_original_message_id() -> None:
    items = [
        _message("第一段，", message_id="i-1"),
        _message("第二段。", message_id="i-2"),
        _message("第三段", message_id="i-3"),
    ]
    merged = merge_turn(items)
    assert merged.folded_message_ids == ["i-1", "i-2", "i-3"]
    # 开门者身份仍落在原 message_id（回执/幂等指向不变）。
    assert merged.message_id == "i-1"


def test_merge_keeps_image_and_text_segments_in_order() -> None:
    """图片+文字拆两气泡发：折成一轮后段一个不丢、顺序不重排。"""
    text_bubble = _message("看这张，", message_id="img-1")
    pic_bubble = _message(
        "。",
        message_id="img-2",
        raw_segments=[{"type": "image", "data": {"file": "abc.jpg"}}],
    )
    merged = merge_turn([text_bubble, pic_bubble])
    assert [seg["type"] for seg in merged.raw_segments] == ["image"]
    assert merged.raw_segments[0]["data"]["file"] == "abc.jpg"
    assert merged.folded_message_ids == ["img-1", "img-2"]


def test_merge_preserves_reply_chain_and_quote_target() -> None:
    head = _message("帮我看下这个，", message_id="q-1")
    tail = _message(
        "讲了什么。",
        message_id="q-2",
        reply_to_message_id="quoted-777",
        reply_to_text="原文",
    )
    merged = merge_turn([head, tail])
    assert merged.reply_to_message_id == "quoted-777"
    assert merged.folded_message_ids == ["q-1", "q-2"]


def test_single_message_merge_defaults_empty_ledger() -> None:
    only = _message("就一句话。")
    assert merge_turn([only]) is only
    assert only.folded_message_ids == []


# ---------------------------------------------------------------------------
# ④ 命令气泡不折进等待；关开关逐字节回旧行为
# ---------------------------------------------------------------------------


def test_supports_coalescing_refuses_command_shaped_bubbles() -> None:
    msg = _message("/bot status", command_text="/bot status")
    assert supports_coalescing(msg) is False
    # 普通聊天不受影响（守门只拦命令形状）。
    assert supports_coalescing(_message("在吗，")) is True


@pytest.mark.asyncio
async def test_disabled_switch_is_byte_identical_for_new_predicates() -> None:
    """enabled=false：即便新判据认为「还在说」，也一律逐条各回各的（回归安全）。"""
    batcher = MessageCoalescer(CoalescingSettings(enabled=False))
    first, second = _message("守岸人，"), _message("今天天气不错。")

    turn_a = await batcher.offer(_key(first), first)
    turn_b = await batcher.offer(_key(second), second)

    assert turn_a.owned and turn_b.owned
    assert turn_a.message is first and turn_b.message is second
    assert batcher.pending_keys == ()


# ---------------------------------------------------------------------------
# 接线锁：根装配消费逐条 id 账；命令 handler 不碰折句
# ---------------------------------------------------------------------------


def _func_node(tree: ast.AST, name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def test_root_handle_chat_consumes_folded_id_ledger() -> None:
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8"))
    handler = _func_node(tree, "_handle_chat")
    assert handler is not None
    uses = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute) and node.attr == "folded_message_ids"
    ]
    assert uses, "根装配段必须消费 _turn.folded_message_ids（逐条 id 账不许进门就丢）"


def test_natural_command_handler_never_touches_coalescing() -> None:
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8"))
    natural = _func_node(tree, "_handle_natural")
    assert natural is not None
    names = {
        getattr(node, "attr", "") or getattr(node, "id", "")
        for node in ast.walk(natural)
        if isinstance(node, (ast.Attribute, ast.Name))
    }
    assert not any("coalesc" in str(name).lower() for name in names), (
        "命令族 handler 不得引入折句等待（命令要立刻执行）"
    )

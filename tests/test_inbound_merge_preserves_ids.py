"""折句合并的 **id/分段保留 + 单次回复** 活性锁（席位 S-T-MERGE-2，2026-09-25 用户裁定第 1 项）。

用户口径：一句话常被逗号拆成两三条发，bot 不该逐条各回一句。机制真身
``domains/chat_reply/runtime/message_coalescing.py`` 与根装配段（现算坐标见
``logs/S-T-COAL-LOCK.md`` §1）都已在盘；本锁补的是两族旧锁都没碰的一格：

1. **N 条 ⇒ 下游恰一次**——能力调用恰 1 次、回复请求（SendRequest）恰 1 条，
   且开门轮带齐全部 N 枚逐条 ``message_id``（长度==N 且**逐值等序**，
   只数长度会被「id 全被洗成空串」糊过去，故配一发 ``message_turn_id`` 注毒自证）。
2. **分段边界不破**——合并轮 ``raw_segments`` 是各条段序的逐条拼接，
   非文本段（at/face）原样在场；引用/回复目标从任一碎片来都存活。

为什么测的是「复刻」而不是根文件本身
------------------------------------
根 ``__init__.py`` 近万行且 import 面会被并发席半写污染（S-T-COAL-LOCK 同款理由），
故根装配段的**形状**由那把 AST 活性锁持棒（import 在函数体第一层、门、
每轮现算分键、非开门即 return、合并轮回写、早于 handle_async——逐条已锁）；
本锁按同一形状做最小复刻，把「合并语义 × 真 RuntimePipeline × 真 InMemorySendQueue」
的**计数事实**钉死。两把锁合起来才是完整命题：根里真是这么接的 + 这么接就恰好一次。

注毒（禁写生产件，全在进程内/内存副本上）
------------------------------------------
- ``CoalescingSettings(enabled=False)`` ⇒ 计数必变 N（「合并关掉必须红」的机检形态：
  计数断言对开关有判别力，才说明 GREEN 不是恒真）。
- monkeypatch ``message_coalescing.message_turn_id`` 恒返 "" ⇒ 逐值锁必红。
- 根文件未把 ``folded_message_ids`` 交下游 ⇒ xfail 记账
  （``MERGE-IDS-DOWNSTREAM-WIRE``，接线坐标见本席日志 §5；接线后摘牌转正）。
"""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    message_coalescing,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.message_coalescing import (
    CoalescingSettings,
    build_coalescing_settings,
    merge_turn,
    shared_coalescer,
    supports_coalescing,
    utterance_turn_key,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    InMemorySendQueue,
)

_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = _ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"

# 快窗：测语义不测秒表（在册四键的缺省形态与窗口常量权威另有一把等值锁，见文末）。
FAST = CoalescingSettings(
    enabled=True, quiet_seconds=0.05, max_hold_seconds=0.5
)


def _config_stub(**over: object) -> SimpleNamespace:
    """装配期 Config 的最小替身：只带在册四键（quiet 键 2026-09-27 乙案退役），值可覆盖。"""
    values: dict[str, object] = {
        "bot_chat_message_coalescing_enabled": FAST.enabled,
        "bot_chat_message_coalescing_max_hold_seconds": FAST.max_hold_seconds,
        "bot_chat_message_coalescing_max_messages": FAST.max_messages,
        "bot_chat_message_coalescing_max_chars": FAST.max_chars,
    }
    values.update({f"bot_chat_message_coalescing_{k}": v for k, v in over.items()})
    return SimpleNamespace(**values)


def _coalescing_settings(**over: object) -> CoalescingSettings:
    """按根装配同形状取本轮设置：build(在册四键) → 窗口权威值。

    生产里等待窗不再经 Config（乙案退役），由根装配段每轮
    ``message_merge.apply_merge_window_seconds`` 写死 3 秒裁定值；本锁复刻同形状
    但把窗口换成 FAST 快窗——测语义不测秒表。
    """
    settings = build_coalescing_settings(_config_stub(**over))
    return replace(settings, quiet_seconds=FAST.quiet_seconds)


def _message(
    text: str,
    *,
    message_id: str,
    sender_id: str,
    session_id: str,
    session_type: SessionType = SessionType.PRIVATE,
    group_id: str | None = None,
    **kwargs: object,
) -> IncomingMessage:
    segments = kwargs.pop(
        "raw_segments", [{"type": "text", "data": {"text": text}}]
    )
    return IncomingMessage(
        platform="qq",
        adapter="onebot_v11",
        bot_id="3958874605",
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        group_id=group_id,
        plain_text=text,
        message_id=message_id,
        raw_segments=segments,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def _counting_capability(
    calls: list[IncomingMessage],
    *,
    privacy: PrivacyLevel = PrivacyLevel.PERSONAL,
):
    async def _run(
        message: IncomingMessage, decision: BotDecision
    ) -> CapabilityResult:
        calls.append(message)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.chat",
            kind="text",
            body="我在。",
            send_policy=SendPolicy.IMMEDIATE,
            privacy_level=privacy,
        )

    return _run


async def _inbound_like_root(
    coalescer: message_coalescing.MessageCoalescer,
    pipeline: RuntimePipeline,
    capability: Any,
    message: IncomingMessage,
    *,
    owner_id_batches: list[list[str]],
    folded_away: list[str],
) -> None:
    """根 ``_handle_chat`` 折句块（现算 8604-8634）的逐句镜像。

    与装配锁（test_coalescing_wiring_lock）逐项对齐：门用 ``supports_coalescing``、
    分键每轮现算 ``utterance_turn_key(message)``、非开门即记 ``chat_turn_folded``
    语义（这里收进 ``folded_away`` 名单）后返回、开门者用 ``turn.message`` 进管道。
    ``owner_id_batches`` 收集每次开门拿到的 ``folded_message_ids``——它就是
    「合并不得吞 id」判据的载体（本锁的新增断言面）。
    """
    if supports_coalescing(message):
        turn = await coalescer.offer(utterance_turn_key(message), message)
        if not turn.owned:
            folded_away.append(str(message.message_id))
            return
        owner_id_batches.append(list(turn.folded_message_ids))
        message = turn.message
    await pipeline.handle_async(message, capability, "bot.chat")


async def _drive_fragments(messages: Sequence[IncomingMessage]) -> dict[str, Any]:
    """复刻根链路把 N 条碎片喂完，返回计数与产物。"""
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)
    calls: list[IncomingMessage] = []
    capability = _counting_capability(calls)
    coalescer = shared_coalescer(_coalescing_settings())
    coalescer.reset()  # 共享单例：清掉别的用例可能残留的窗口
    owner_id_batches: list[list[str]] = []
    folded_away: list[str] = []

    first, rest = messages[0], list(messages[1:])
    owner_task = asyncio.create_task(
        _inbound_like_root(
            coalescer, pipeline, capability, first,
            owner_id_batches=owner_id_batches, folded_away=folded_away,
        )
    )
    await asyncio.sleep(0.01)  # 让开门者先把窗口挂上（offer 在建窗前是同步段）
    for message in rest:
        await _inbound_like_root(
            coalescer, pipeline, capability, message,
            owner_id_batches=owner_id_batches, folded_away=folded_away,
        )
    await asyncio.wait_for(owner_task, timeout=2.0)
    return {
        "calls": calls,
        "requests": list(queue.sent_requests),
        "owner_id_batches": owner_id_batches,
        "folded_away": folded_away,
    }


# ---------------------------------------------------------------------------
# ① 主命题：私聊 N 条碎片 ⇒ 一次能力调用 + 一条回复请求 + id 账等长等序
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_fragments_produce_exactly_one_capability_call_and_reply() -> None:
    sender = "u-merge-priv"
    fragments = [
        _message("守岸人，", message_id="m-1", sender_id=sender,
                 session_id=f"private:{sender}"),
        _message("今天的潮汐怎么样，", message_id="m-2", sender_id=sender,
                 session_id=f"private:{sender}"),
        _message("适合出门吗", message_id="m-3", sender_id=sender,
                 session_id=f"private:{sender}"),
    ]

    out = await _drive_fragments(fragments)

    # 下游只收到 1 次能力调用，且看到的是拼回的那一句。
    assert len(out["calls"]) == 1
    assert out["calls"][0].plain_text == "守岸人，今天的潮汐怎么样，适合出门吗"
    # 只产生 1 条回复请求，身份落在开门者（原会话/原请求）上。
    assert len(out["requests"]) == 1
    assert out["requests"][0].origin_message_id == "m-1"
    # 逐条 id 账：长度 == N 且逐值等序（消费掉的两条不许无痕消失）。
    assert out["owner_id_batches"] == [["m-1", "m-2", "m-3"]]
    assert len(out["owner_id_batches"][0]) == len(fragments)
    assert out["folded_away"] == ["m-2", "m-3"]


@pytest.mark.asyncio
async def test_group_fragments_mentioning_bot_reply_once_not_per_fragment() -> None:
    """群聊面：合并轮 mentions 归并后只过一次门禁——R3 同人 45s 间隔不再吞后续碎片。"""
    sender = "u-merge-grp"
    session = f"group_77_{sender}"
    fragments = [
        _message("守岸人，", message_id="g-1", sender_id=sender,
                 session_id=session, session_type=SessionType.GROUP, group_id="77"),
        _message("今天的潮汐怎么样，", message_id="g-2", sender_id=sender,
                 session_id=session, session_type=SessionType.GROUP, group_id="77",
                 mentions_bot=True,
                 raw_segments=[
                     {"type": "at", "data": {"qq": "3958874605"}},
                     {"type": "text", "data": {"text": "今天的潮汐怎么样，"}},
                 ]),
        _message("适合出门吗", message_id="g-3", sender_id=sender,
                 session_id=session, session_type=SessionType.GROUP, group_id="77"),
    ]

    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)
    calls: list[IncomingMessage] = []
    capability = _counting_capability(calls, privacy=PrivacyLevel.GROUP)
    coalescer = shared_coalescer(_coalescing_settings())
    coalescer.reset()
    owner_id_batches: list[list[str]] = []
    folded_away: list[str] = []

    owner_task = asyncio.create_task(
        _inbound_like_root(
            coalescer, pipeline, capability, fragments[0],
            owner_id_batches=owner_id_batches, folded_away=folded_away,
        )
    )
    await asyncio.sleep(0.01)
    for message in fragments[1:]:
        await _inbound_like_root(
            coalescer, pipeline, capability, message,
            owner_id_batches=owner_id_batches, folded_away=folded_away,
        )
    await asyncio.wait_for(owner_task, timeout=2.0)

    assert len(calls) == 1
    assert calls[0].mentions_bot is True  # 「有过就算有」归并，门禁不因首条没 @ 而放宽/误杀
    assert owner_id_batches == [["g-1", "g-2", "g-3"]]
    # 回复至多一条（群面策略若拦截则该轮零条——但绝不许多条）。
    assert len(queue.sent_requests) <= 1
    assert folded_away == ["g-2", "g-3"]


# ---------------------------------------------------------------------------
# ② 注毒自证：合并关掉必须让「一次」判据变红（计数断言有判别力）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kill_power_disabled_coalescing_replies_to_every_fragment() -> None:
    """enabled=False ⇒ 三条碎片各回一句。主命题的计数断言必须能区分两态。"""
    sender = "u-merge-off"
    fragments = [
        _message(t, message_id=f"x-{i}", sender_id=sender,
                 session_id=f"private:{sender}")
        for i, t in enumerate(["守岸人，", "在吗，", "最近怎么样"], start=1)
    ]

    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)
    calls: list[IncomingMessage] = []
    capability = _counting_capability(calls)
    coalescer = shared_coalescer(_coalescing_settings(enabled=False))
    assert coalescer.settings.enabled is False  # 键到得了运行时参数（在册四键通路的开关位）
    coalescer.reset()
    owner_id_batches: list[list[str]] = []
    folded_away: list[str] = []

    for message in fragments:
        await _inbound_like_root(
            coalescer, pipeline, capability, message,
            owner_id_batches=owner_id_batches, folded_away=folded_away,
        )

    assert len(calls) == 3      # 逐条各回一句 = 用户要治的病
    assert len(queue.sent_requests) == 3
    # 契约如实入账：未开过窗的轮次 folded_message_ids 为空（id 账 = 消息自身
    # message_id 一枚），只有真折过条的开门轮才带等长等序的逐条账。
    assert owner_id_batches == [[], [], []]
    assert folded_away == []


@pytest.mark.asyncio
async def test_kill_power_turn_id_collapse_breaks_the_value_lock(monkeypatch) -> None:
    """把 ``message_turn_id`` 注成恒返 "" ⇒ 长度仍==N 但**逐值**必红。

    这条锁自证主命题里「长度==N」不是全部——若只断言长度，id 全被洗空也照样绿。
    """
    monkeypatch.setattr(message_coalescing, "message_turn_id", lambda _m: "")
    batcher = message_coalescing.MessageCoalescer(FAST)
    sender = "u-collapse"
    m1 = _message("守岸人，", message_id="real-1", sender_id=sender,
                  session_id=f"private:{sender}")
    m2 = _message("在吗", message_id="real-2", sender_id=sender,
                  session_id=f"private:{sender}")

    owner_task = asyncio.create_task(batcher.offer(utterance_turn_key(m1), m1))
    await asyncio.sleep(0.01)
    await batcher.offer(utterance_turn_key(m2), m2)
    turn = await owner_task

    assert len(turn.folded_message_ids) == 2  # 光看长度：毒形也能过
    assert turn.folded_message_ids != ["real-1", "real-2"]  # 逐值：红（主命题锁的就是这个）


# ---------------------------------------------------------------------------
# ③ 分段边界与引用存活（合并轮仍是同一 IncomingMessage，不新开字段）
# ---------------------------------------------------------------------------


def test_merge_keeps_every_segments_boundary_and_order() -> None:
    sender = "u-seg"
    head = _message("第一段，", message_id="s-1", sender_id=sender,
                    session_id=f"private:{sender}",
                    raw_segments=[
                        {"type": "text", "data": {"text": "第一段，"}},
                        {"type": "face", "data": {"id": "178"}},
                    ])
    tail = _message(
        "第二段",
        message_id="s-2",
        sender_id=sender,
        session_id=f"private:{sender}",
        raw_segments=[
            {"type": "text", "data": {"text": "第二段"}},
            {"type": "at", "data": {"qq": "3958874605"}},
        ],
    )

    merged = merge_turn([head, tail])

    # 段序 = 各条段序的逐条拼接；一枚段都不吞、不并、不重排。
    assert merged.raw_segments == head.raw_segments + tail.raw_segments
    assert [seg["type"] for seg in merged.raw_segments] == [
        "text", "face", "text", "at",
    ]
    # 分段边界保留 ≠ 原文被抹平：两条的文本段各自还完整在场。
    texts = [
        seg["data"]["text"] for seg in merged.raw_segments if seg["type"] == "text"
    ]
    assert texts == ["第一段，", "第二段"]
    # 原对象不被就地改掉（合并只产出副本）。
    assert len(head.raw_segments) == 2


def test_reply_target_from_later_fragment_survives_the_merge() -> None:
    """引用链：回复目标从**后到**的碎片来也要存活——引用判定不被合并吞掉。"""
    sender = "u-rep"
    head = _message("帮我看下这个，", message_id="r-1", sender_id=sender,
                    session_id=f"private:{sender}")
    tail = _message("讲了什么", message_id="r-2", sender_id=sender,
                    session_id=f"private:{sender}",
                    reply_to_message_id="quoted-555", reply_to_text="原文")

    merged = merge_turn([head, tail])

    assert merged.reply_to_message_id == "quoted-555"
    assert merged.reply_to_text == "原文"
    # 身份仍落在开门者：回复/审计的原消息指向不变。
    assert merged.message_id == "r-1"


# ---------------------------------------------------------------------------
# ④ 在册四键通路：配置快照 → build_coalescing_settings 的逐值映射与保守缺省
# ---------------------------------------------------------------------------


def test_config_snapshot_maps_into_coalescing_settings_value_by_value() -> None:
    cfg = _config_stub(max_hold_seconds=2.5, max_messages=4, max_chars=999)
    settings = build_coalescing_settings(cfg)
    assert settings.max_hold_seconds == 2.5
    assert settings.max_messages == 4
    assert settings.max_chars == 999
    assert settings.enabled is True


def test_missing_config_falls_back_to_conservative_defaults() -> None:
    """读不到的替身一律回缺省（保守形态），绝不因缺键把折句打开成激进窗。"""
    settings = build_coalescing_settings(SimpleNamespace())
    assert settings == CoalescingSettings()


def test_module_defaults_match_registered_config_field_defaults() -> None:
    """在册四键：模块缺省 == config.py 在册缺省；quiet 键已退役并被常量锁钉死。

    期望值为什么变（乙案落地，禁止悄悄放宽）：COALESCE-DUALAUTH 审计证实
    `bot_chat_message_coalescing_quiet_seconds` 每轮被
    `message_merge.MERGE_WINDOW_SECONDS`（用户 2026-09-27 裁定 3s）无条件覆盖，
    是「在册永不算数」的死口 ⇒ 键退役（config.py 字段与 getattr 读点一并摘除），
    本锁从「quiet 字段缺省 == 1.8」改判为三格：
    ① 该字段**不在** Config（防复活）；
    ② dataclass 缺省 quiet == 3.0（1.8 双胞胎同批消籍）；
    ③ dataclass 缺省 quiet == MERGE_WINDOW_SECONDS（唯一真身等值锁，
        仿 progress_ack 地板值的 parity 先例）。
    其余四键的 parity 断言逐字保留，未动任何容差。
    """
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import message_merge

    fields = Config.model_fields
    defaults = CoalescingSettings()
    assert "bot_chat_message_coalescing_quiet_seconds" not in fields, (
        "quiet 键已被读回 Config —— 乙案退役作废，等待窗唯一真身是常量"
    )
    assert defaults.quiet_seconds == 3.0
    assert defaults.quiet_seconds == message_merge.MERGE_WINDOW_SECONDS
    assert fields["bot_chat_message_coalescing_enabled"].default is defaults.enabled
    assert (
        fields["bot_chat_message_coalescing_max_hold_seconds"].default
        == defaults.max_hold_seconds
    )
    assert (
        fields["bot_chat_message_coalescing_max_messages"].default
        == defaults.max_messages
    )
    assert (
        fields["bot_chat_message_coalescing_max_chars"].default
        == defaults.max_chars
    )


# ---------------------------------------------------------------------------
# ⑤ 已挂账缺口：逐条 id 账今天到不了下游观测面（根文件丢弃；本席禁改根）
# ---------------------------------------------------------------------------


def _handle_chat_node(source: str) -> ast.AsyncFunctionDef | None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # 并发半写 ≠ 缺口本身，点名后再判
        raise AssertionError(
            f"根 __init__.py 第 {exc.lineno} 行语法错——大概率被别的席半写，"
            "等 60 秒复跑再判；本锁只读不写"
        ) from exc
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_chat"
    ]
    assert len(found) == 1, f"_handle_chat 应恰一枚，实={len(found)}"
    return found[0]


# MERGE-IDS-DOWNSTREAM-WIRE 转正（席位 S-XFAIL-AUDIT 2026-09-29 --runxfail 实跑绿）：
# 根 __init__.py 现于 _handle_chat 内消费 _turn.folded_message_ids（9018/9028 折叠账
# folded_ids=…），逐条 id 已进下游。按原 reason「主会话接线后摘掉本标记当转正判据」执行：
# 从此这条是活锁，谁把 folded_message_ids 再丢回下游之外本条即报红。
# 复跑尺：pytest tests/test_inbound_merge_preserves_ids.py::test_folded_id_ledger_is_still_dropped_before_the_pipeline
def test_folded_id_ledger_is_still_dropped_before_the_pipeline() -> None:
    handler = _handle_chat_node(ROOT_INIT.read_text(encoding="utf-8"))
    assert handler is not None
    uses = [
        node
        for node in ast.walk(handler)
        if (isinstance(node, ast.Attribute) and node.attr == "folded_message_ids")
        or (isinstance(node, ast.keyword) and node.arg == "folded_message_ids")
    ]
    assert uses, (
        "根装配段仍无人消费 _turn.folded_message_ids ⇒ 下游只剩开门者一枚 id；"
        "若此条转 XPASS = 已接线，摘牌转正"
    )

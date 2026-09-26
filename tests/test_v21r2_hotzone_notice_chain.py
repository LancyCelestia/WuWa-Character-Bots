"""v21r2 R5 热区回归：notice 族（戳一戳）全链路不炸摄取、产出 poke 回复。

生产实锤栈：Matcher(type='notice') _handle_poke_notice →
_send_parts_through_unified_pipeline → _run_capability_through_pipeline →
IngressGateway(_incoming_from_nonebot_event).from_event → get_plaintext →
ValueError("Event has no message!")（PokeNoticeEvent 等 notice 族无 message）。

锁死行为（全离线、假事件、零 sleep）：
- 假 PokeNoticeEvent 过真实摄取：空文本降级，不抛 ValueError；
- 同一假事件走真实 RuntimePipeline + 统一管线出站
  （_run_capability_through_pipeline 生产路径）：链路产出带戳一戳话术的
  SendRequest，session/target 齐全；
- AST 棘轮：__init__ 内全部 on_notice handler 函数体零 get_plaintext 直调，
  防未来新增 notice handler 重引同病灶。

复跑：
  PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_v21r2_hotzone_notice_chain.py -q \
      --basetemp=$TEMP/v21r2-r5c -p no:cacheprovider
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import plugins.bot_unified_runtime as runtime_module
from plugins.bot_unified_runtime import (
    _incoming_from_nonebot_event,
    _run_capability_through_pipeline,
)
from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    DeliveryReceipt,
    ReceiptState,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import InMemorySendQueue


class _FakePokeNoticeEvent:
    """NapCat 时期私聊戳一戳 notice 事件形（无 message 字段，get_plaintext 必炸）。

    私聊形态：默认群门禁（未 @ 拒绝）不在此测试域内，焦点锁在 notice 摄取。
    """

    __module__ = "nonebot.adapters.onebot.v11.event"

    user_id = 42
    notice_type = "notify"
    sub_type = "poke"

    def get_plaintext(self) -> str:
        raise ValueError("Event has no message!")

    def get_session_id(self) -> str:
        return "42"

    def get_user_id(self) -> str:
        return "42"


# ----------------------------------------------------------------- 摄取层


def test_notice_event_ingests_with_empty_text_without_raising() -> None:
    message = _incoming_from_nonebot_event(_FakePokeNoticeEvent(), bot_id="bot-1")
    assert message.plain_text == ""
    assert message.session_id == "42"


# ------------------------------------------------------------- 生产管线全链路


@pytest.mark.asyncio
async def test_poke_notice_produces_reply_through_unified_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = InMemorySendQueue(InMemoryAuditLogger())
    pipeline = RuntimePipeline(queue, InMemoryAuditLogger())
    event = _FakePokeNoticeEvent()

    async def _fake_transport(
        _bot: Any, _event: Any, request: Any, *_a: Any, **_k: Any
    ) -> DeliveryReceipt:
        return DeliveryReceipt(
            request_id=request.request_id,
            state=ReceiptState.SENT,
            transport="onebot",
            public_message="",
        )

    monkeypatch.setattr(
        runtime_module, "_deliver_transport_send_request", _fake_transport
    )

    def _capability(message: Any, _decision: Any) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.poke",
            kind="text",
            body="戳回去啦。",
            audit_tags=["poke_mode:fixed"],
        )

    receipt = await _run_capability_through_pipeline(
        bot=SimpleNamespace(self_id="bot-1"),
        event=event,
        config=SimpleNamespace(),
        pipeline=pipeline,
        send_queue=queue,
        audit_logger=InMemoryAuditLogger(),
        diagnostics_store=SimpleNamespace(record=lambda _diagnostic: None),
        capability=_capability,
        capability_id="bot.poke",
        record_diagnostic=False,
    )
    assert receipt.state is ReceiptState.SENT
    queued = queue.find_request(receipt.request_id)
    assert queued is not None
    assert queued.content.text_fallback == "戳回去啦。"
    assert queued.session_id == "42"
    assert queued.target_scope.value == "private"


# ------------------------------------------------------------------ AST 棘轮

_NOTICE_HANDLER_NAMES = {
    "_handle_poke_notice",
    "_handle_msg_emoji_like_notice",
    "_handle_admin_file_notice",
    "_handle_group_increase",
    "_handle_group_decrease",
    "_handle_group_admin_change",
    "_handle_group_upload",
}


def test_notice_handlers_never_call_get_plaintext() -> None:
    source_path = Path(runtime_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    offenders = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name in _NOTICE_HANDLER_NAMES
        and any(
            isinstance(call.func, ast.Attribute) and call.func.attr == "get_plaintext"
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        )
    }
    assert offenders == set()

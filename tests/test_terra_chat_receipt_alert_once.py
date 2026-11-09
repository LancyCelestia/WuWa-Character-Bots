"""Offline regression for repeated notification of one chat pipeline receipt."""

from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime import should_finish_nonebot_matcher
from plugins.bot_unified_runtime.domains.core.contracts import (
    DeliveryReceipt,
    IncomingMessage,
    OperationalIssue,
    ReceiptState,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.monitor import alerts
from plugins.bot_unified_runtime.domains.ops.monitor.error_report import (
    ErrorCardGate,
    ErrorCardSettings,
)

ROOT = Path(__file__).resolve().parents[1] / "plugins/bot_unified_runtime/__init__.py"


def _extracted(name: str, namespace: dict, *, tail: bool = False):
    tree = ast.parse(ROOT.read_text(encoding="utf-8"), filename=str(ROOT))
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    fn = matches[0]
    fn.decorator_list = []
    fn.returns = None
    for arg in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs):
        arg.annotation = None
    if tail:
        starts = [
            i for i, statement in enumerate(fn.body)
            if isinstance(statement, ast.Try)
            and any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "handle_async"
                for node in ast.walk(statement)
            )
        ]
        assert len(starts) == 1
        fn.body = fn.body[starts[0]:]
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    exec(compile(module, str(ROOT), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("window_seconds", [0.0, 300.0])
@pytest.mark.parametrize("sender_id", ["user-1", "admin-1"])
def test_chat_pipeline_receipt_notified_once(
    monkeypatch: pytest.MonkeyPatch, window_seconds: float, sender_id: str
) -> None:
    delivered = []
    cards = []
    ledger = []
    replies = []
    diagnostics = []
    issue = OperationalIssue(
        stage="llm", kind="deadline_exceeded", safe_summary="chain=2"
    )
    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=f"private:{sender_id}",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text="hello",
        message_id="message-1",
    )
    receipt = DeliveryReceipt(
        request_id=message.request_id,
        state=ReceiptState.FAILED_FINAL,
        transport="none",
        operational_issue=issue,
    )
    target = alerts.AdminTarget("onebot", "bot-1", "admin-1")
    monkeypatch.setattr(alerts, "alert_card_sink", lambda t, r: cards.append((t, r)))
    monkeypatch.setattr(alerts, "_resolve_settings", lambda: ErrorCardSettings(True))
    monkeypatch.setattr(alerts, "_module_gate", lambda _: ErrorCardGate(0))

    async def delivery(_target, _bot, request):
        delivered.append(request)

    async def handle_async(*_args, **_kwargs):
        return receipt

    async def finish(text):
        replies.append(text)

    pipeline = SimpleNamespace(handle_async=handle_async)
    notifier = _extracted(
        "_notify_operational_receipt",
        {
            "notify_operational_issue": alerts.notify_operational_issue,
            "_operational_alert_targets": lambda: [target],
            "_all_online_bots": lambda: {"bot-1": object()},
            "_deliver_admin_alert": delivery,
            "operational_alert_suppression": alerts.AdminAlertSuppression(
                window_seconds=window_seconds
            ),
            "error_issue_ledger": SimpleNamespace(record=lambda **kw: ledger.append(kw)),
            "pipeline": pipeline,
        },
    )
    handler = _extracted(
        "_handle_chat",
        {
            "message": message,
            "pipeline": pipeline,
            "chat_capability": object(),
            "_notify_operational_receipt": notifier,
            "_find_sent_request": lambda *_: None,
            "send_queue": object(),
            "_log_runtime_event": lambda *_a, **_kw: None,
            "runtime_event_log": object(),
            "time": time,
            "started_at": time.perf_counter(),
            "_runtime_tag_values": lambda *_: {},
            "_policy_gate_values": lambda *_: {},
            "audit_logger": object(),
            "release_mail_reply_claim": lambda: None,
            "_record_runtime_diagnostic": lambda **kw: diagnostics.append(kw),
            "config": object(),
            "diagnostics_store": object(),
            "_should_silently_skip_chat_receipt": lambda *_: False,
            "should_finish_nonebot_matcher": should_finish_nonebot_matcher,
            "chat": SimpleNamespace(finish=finish),
        },
        tail=True,
    )
    asyncio.run(handler(object(), object()))

    assert replies == []
    assert len(diagnostics) == 1
    assert len(ledger) == 1
    assert ledger[0]["request_id"] == message.request_id
    assert len(delivered) == 1
    assert len(cards) == 1
    assert cards[0][1]["exc_type"] == "llm/deadline_exceeded"

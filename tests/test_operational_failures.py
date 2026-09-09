from __future__ import annotations

import ast
import asyncio
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

import plugins.bot_unified_runtime as runtime_module
from plugins.bot_unified_runtime import (
    _record_transport_receipt,
    _run_capability_through_pipeline,
    should_finish_nonebot_matcher,
)
from plugins.bot_unified_runtime import contracts as runtime_contracts
from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.capabilities.chat import (
    _execute_mcp_tool_call,
    build_chat_result,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    RiskLevel,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.llm.providers import LLMProviderError
from plugins.bot_unified_runtime.policy.roles import build_role_settings
from plugins.bot_unified_runtime.runtime import alerts as alerts_module
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.sender.nonebot import send_nonebot_message
from plugins.bot_unified_runtime.sender.onebot import send_onebot_v11
from plugins.bot_unified_runtime.sender.queue import (
    QueuedSendRequest,
    SQLiteSendRequestQueue,
)
from plugins.bot_unified_runtime.sender.receipts import SQLiteReceiptRepository
from plugins.bot_unified_runtime.sender.worker import (
    _call_transport_safely,
    _update_queue_state,
    drain_send_queue_once,
)
from plugins.bot_unified_runtime.sources.runtime_event_log import RuntimeEventLog

_select_credential_bot = getattr(runtime_module, "_select_credential_bot", None)
_queue_bot_unavailable_receipt = getattr(
    runtime_module, "_queue_bot_unavailable_receipt", None
)
OperationalIssue = getattr(runtime_contracts, "OperationalIssue", None)
AdminTarget = getattr(alerts_module, "AdminTarget", None)
AdminAlertSuppression = getattr(alerts_module, "AdminAlertSuppression", None)
build_operational_alert_text = getattr(alerts_module, "build_operational_alert_text", None)
build_typed_admin_targets = getattr(alerts_module, "build_typed_admin_targets", None)
dispatch_admin_alert = getattr(alerts_module, "dispatch_admin_alert", None)


GENERIC_FAILURE_MESSAGE = "这次暂时没能稳定完成，请稍后再试。"


def _issue(**overrides: object) -> OperationalIssue:
    values = {
        "stage": "llm",
        "kind": "timeout",
        "retryable": True,
        "debug_id": "dbg-safe-1",
    }
    values.update(overrides)
    return OperationalIssue(**values)


def _message(session_type: SessionType) -> IncomingMessage:
    return IncomingMessage(
        platform="telegram" if session_type is not SessionType.GROUP else "qq",
        adapter="telegram" if session_type is not SessionType.GROUP else "onebot",
        bot_id="bot-1",
        session_id=f"{session_type.value}:user-1",
        session_type=session_type,
        sender_id="user-1",
        group_id="group-1" if session_type is SessionType.GROUP else None,
        plain_text="你好",
        mentions_bot=session_type is SessionType.GROUP,
    )


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=message.session_type,
        privacy_level=(
            PrivacyLevel.GROUP
            if message.session_type is SessionType.GROUP
            else PrivacyLevel.PERSONAL
        ),
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def _context(request_id: str, session_type: SessionType):
    from plugins.bot_unified_runtime.contracts.character import (
        ContextBundle,
        ConversationHistoryResult,
        MemoryRetrievalResult,
        PersonaProfile,
        RetrievalResult,
        ToneProfile,
    )

    return ContextBundle(
        request_id=request_id,
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id=request_id),
        conversation_history=ConversationHistoryResult(request_id=request_id),
        knowledge_results=RetrievalResult(request_id=request_id),
        current_message="你好",
        sender_id="user-1",
        session_id=f"{session_type.value}:user-1",
        privacy_level=(
            PrivacyLevel.GROUP
            if session_type is SessionType.GROUP
            else PrivacyLevel.PERSONAL
        ),
    )


class FailingRouter:
    last_attempts: ClassVar[list[str]] = ["provider-a:timeout", "provider-b:server"]

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> object:
        raise LLMProviderError("raw secret exception", error_kind="timeout")


def test_operational_issue_rejects_non_finite_elapsed_ms() -> None:
    for elapsed_ms in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            OperationalIssue(stage="llm", kind="timeout", elapsed_ms=elapsed_ms)


def test_console_sender_classifies_failure_as_runtime() -> None:
    class Adapter:
        def get_name(self) -> str:
            return "Console"

    class ConsoleBot:
        adapter = Adapter()

        async def send(self, event: object, text: str, **kwargs: object) -> object:
            raise RuntimeError("console internal detail")

    async def run() -> DeliveryReceipt:
        return await send_nonebot_message(ConsoleBot(), object(), _send_request())

    receipt = asyncio.run(run())
    assert receipt.public_message == ""
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.stage == "runtime"


def test_operational_issue_is_strict_and_serializes_through_all_contracts() -> None:
    issue = _issue(attempts=2, elapsed_ms=12.5, safe_summary="upstream_timeout")
    content = RenderedOutput(
        request_id="req-1",
        content_type="text",
        content_ref={},
        text_fallback=GENERIC_FAILURE_MESSAGE,
    )
    result = CapabilityResult(
        request_id="req-1",
        kind="text",
        operational_issue=issue,
        body="",
        send_policy=SendPolicy.SILENT_AUDIT,
    )
    request = SendRequest(
        request_id="req-1",
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        capability_id="bot.chat",
        content=content,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="dedupe-1",
        cooldown_key="cooldown-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        operational_issue=issue,
    )
    receipt = DeliveryReceipt(
        request_id="req-1",
        state=ReceiptState.FAILED_FINAL,
        transport="runtime",
        operational_issue=issue,
    )

    assert result.model_dump(mode="json")["operational_issue"]["kind"] == "timeout"
    assert request.operational_issue == issue
    assert receipt.operational_issue == issue
    with pytest.raises(ValueError):
        OperationalIssue(stage="llm", kind="timeout", attempts=0)
    with pytest.raises(ValueError):
        OperationalIssue(stage="llm", kind="timeout", elapsed_ms=-1)
    with pytest.raises(ValueError):
        OperationalIssue(stage="llm", kind="timeout", elapsed_ms=math.nan)
    with pytest.raises(ValueError):
        OperationalIssue(stage="llm", kind="timeout", elapsed_ms=math.inf)
    with pytest.raises(ValueError):
        OperationalIssue(stage="llm", kind="timeout", elapsed_ms=-math.inf)
    with pytest.raises(ValueError):
        OperationalIssue.model_validate({"stage": "llm", "kind": "timeout", "unknown": 1})


def test_private_llm_failure_is_generic_and_group_failure_is_silent_audit() -> None:
    for session_type, expected_body, expected_policy in (
        (SessionType.PRIVATE, GENERIC_FAILURE_MESSAGE, SendPolicy.IMMEDIATE),
        (SessionType.GROUP, "", SendPolicy.SILENT_AUDIT),
    ):
        message = _message(session_type)
        result = build_chat_result(
            message,
            _decision(message),
            _context(message.request_id, session_type),
            llm_provider=FailingRouter(),
            model_router=FailingRouter(),
        )
        from plugins.bot_unified_runtime.capabilities.chat import _PERSONA_FAILURE_MESSAGES
        assert result.body in _PERSONA_FAILURE_MESSAGES or result.body == ""
        assert result.send_policy is expected_policy
        assert result.operational_issue is not None
        assert result.operational_issue.stage == "llm"
        assert result.operational_issue.kind == "timeout"
        assert all("secret" not in tag.lower() for tag in result.audit_tags)


def _send_request(issue: OperationalIssue | None = None) -> SendRequest:
    return SendRequest(
        request_id="req-transport",
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id="req-transport",
            content_type="text",
            content_ref={},
            text_fallback="hello",
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="dedupe-transport",
        cooldown_key="cooldown-transport",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        operational_issue=issue,
    )


class FailingOneBot:
    async def send_private_msg(self, **kwargs: object) -> object:
        raise RuntimeError("secret transport exception")

    async def send_group_msg(self, **kwargs: object) -> object:
        raise RuntimeError("secret transport exception")


class RetcodeOneBot:
    async def send_private_msg(self, **kwargs: object) -> object:
        return {"status": "failed", "retcode": 403, "wording": "secret result"}

    async def send_group_msg(self, **kwargs: object) -> object:
        return {"status": "failed", "retcode": 403, "wording": "secret result"}


@pytest.mark.asyncio
async def test_onebot_failures_have_empty_public_message_and_typed_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("plugins.bot_unified_runtime.sender.onebot._ONEBOT_SEND_RETRY_DELAYS", ())
    for bot in (FailingOneBot(), RetcodeOneBot()):
        receipt = await send_onebot_v11(bot, _send_request())
        assert receipt.public_message == ""
        assert receipt.operational_issue is not None
        assert receipt.operational_issue.stage == "onebot"
        assert "secret" not in receipt.model_dump_json()


class FailingAdapter:
    class Adapter:
        def get_name(self) -> str:
            return "Telegram"

    adapter = Adapter()

    async def send(self, event: object, text: str, **kwargs: object) -> object:
        raise RuntimeError("raw mail token exception")


@pytest.mark.asyncio
async def test_nonebot_failure_has_empty_public_message_and_typed_issue() -> None:
    receipt = await send_nonebot_message(FailingAdapter(), object(), _send_request())
    assert receipt.public_message == ""
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.stage == "telegram"
    assert "raw mail token exception" not in receipt.model_dump_json()


def test_operational_matcher_receipt_never_finishes_but_policy_block_still_does() -> None:
    assert not should_finish_nonebot_matcher(
        DeliveryReceipt(
            request_id="req-1",
            state=ReceiptState.FAILED_FINAL,
            transport="onebot",
            public_message="internal fallback",
            operational_issue=_issue(stage="onebot", kind="send_exception"),
        )
    )
    assert should_finish_nonebot_matcher(
        DeliveryReceipt(
            request_id="req-2",
            state=ReceiptState.BLOCKED,
            transport="policy",
            public_message="参数不合法，请修正。",
        )
    )


def test_pipeline_silences_operational_failure_and_does_not_submit_group_request() -> None:
    message = _message(SessionType.GROUP)
    audit = InMemoryAuditLogger()
    from plugins.bot_unified_runtime.sender.queue import InMemorySendQueue

    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)

    def capability(_message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(
            request_id=_message.request_id,
            capability_id="bot.chat",
            kind="text",
            body="",
            send_policy=SendPolicy.SILENT_AUDIT,
            privacy_level=PrivacyLevel.GROUP,
            operational_issue=_issue(),
        )

    receipt = pipeline.handle(message, capability, capability_id="bot.chat")
    assert receipt.public_message == ""
    assert receipt.operational_issue is not None
    assert receipt.state is ReceiptState.SKIPPED
    assert queue.sent_requests == []


def test_private_operational_result_creates_one_typed_send_request() -> None:
    message = _message(SessionType.PRIVATE)
    audit = InMemoryAuditLogger()
    from plugins.bot_unified_runtime.sender.queue import InMemorySendQueue

    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)

    def capability(_message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(
            request_id=_message.request_id,
            capability_id="bot.chat",
            kind="text",
            body=GENERIC_FAILURE_MESSAGE,
            send_policy=SendPolicy.IMMEDIATE,
            privacy_level=PrivacyLevel.PERSONAL,
            operational_issue=_issue(),
        )

    receipt = pipeline.handle(message, capability, capability_id="bot.chat")
    assert receipt.state is ReceiptState.SENT
    assert len(queue.sent_requests) == 1
    assert queue.sent_requests[0].operational_issue is not None
    assert receipt.operational_issue is not None
    assert receipt.operational_issue == queue.sent_requests[0].operational_issue
    assert queue.sent_requests[0].content.text_fallback == GENERIC_FAILURE_MESSAGE
    assert receipt.public_message == "sent"


def test_record_transport_receipt_keeps_issue_private_and_public_empty() -> None:
    audit = InMemoryAuditLogger()
    request = _send_request()
    issue = _issue(stage="telegram", kind="send_exception")
    receipt = DeliveryReceipt(
        request_id=request.request_id,
        state=ReceiptState.FAILED_RETRYABLE,
        transport="telegram",
        public_message="internal fallback",
        operational_issue=issue,
    )
    recorded = _record_transport_receipt(receipt, request, audit)
    assert recorded.public_message == ""
    record = audit.list_records(request.request_id)[-1]
    assert record.public_message == ""
    assert "send_exception" in record.private_debug
    assert issue.debug_id in record.private_debug


def test_admin_alert_request_is_typed_and_marks_admin_origin() -> None:
    request = alerts_module.build_admin_alert_send_request(
        AdminTarget(adapter="telegram", bot_id="telegram-bot", target_id="100"),
        "safe alert",
    )
    assert request.adapter == "telegram"
    assert request.target_id == "100"
    assert request.audit_tags == ["admin_alert", "origin:admin_alert"]
    assert request.content.text_fallback == "safe alert"


def test_record_transport_receipt_hides_queue_exception_text_from_private_debug() -> None:
    class BrokenQueue:
        def mark_retryable_failure(self, request_id: str, public_message: str) -> None:
            raise RuntimeError("secret queue detail")

    audit = InMemoryAuditLogger()
    request = _send_request()
    receipt = DeliveryReceipt(
        request_id=request.request_id,
        state=ReceiptState.FAILED_RETRYABLE,
        transport="telegram",
        public_message="",
        operational_issue=_issue(stage="telegram", kind="send_exception"),
    )
    _record_transport_receipt(receipt, request, audit, send_queue=BrokenQueue())
    records = audit.list_records(request.request_id)
    assert records
    assert all("secret queue detail" not in record.private_debug for record in records)


def test_record_transport_receipt_never_passes_issue_text_to_queue() -> None:
    audit = InMemoryAuditLogger()
    request = _send_request()
    issue = _issue(stage="telegram", kind="send_exception")
    receipt = DeliveryReceipt(
        request_id=request.request_id,
        state=ReceiptState.FAILED_RETRYABLE,
        transport="telegram",
        public_message="secret internal fallback",
        operational_issue=issue,
    )

    class Queue:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def mark_retryable_failure(self, request_id: str, public_message: str) -> None:
            self.messages.append(public_message)

    queue = Queue()
    _record_transport_receipt(receipt, request, audit, send_queue=queue)
    assert queue.messages == [""]


def test_mcp_failure_content_is_fixed_safe_json(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(name: str, arguments: dict[str, object]) -> object:
        raise RuntimeError("prompt=https://user:secret@example.test?token=abc")

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.chat._mcp_client_modules",
        lambda: (None, fail),
    )
    payload = json.loads(_execute_mcp_tool_call("web_search", {"query": "secret"}))
    assert payload == {"error": "tool_call_failed", "stage": "tool", "kind": "provider_error"}
    assert "secret" not in json.dumps(payload)


def test_mcp_unavailable_content_uses_typed_safe_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.chat._mcp_client_modules",
        lambda: (None, None),
    )
    payload = json.loads(_execute_mcp_tool_call("web_search", {}))
    assert payload == {"error": "tool_unavailable", "stage": "tool", "kind": "unavailable"}


def test_queue_state_update_keeps_operational_failure_public_message_empty() -> None:
    calls: list[str] = []

    class Queue:
        def mark_retryable_failure(self, request_id: str, public_message: str, *, now=None) -> DeliveryReceipt:
            calls.append(public_message)
            return DeliveryReceipt(
                request_id=request_id,
                state=ReceiptState.FAILED_RETRYABLE,
                transport="queue",
                public_message=public_message,
            )

    request = _send_request(_issue(stage="telegram", kind="send_exception"))
    receipt = DeliveryReceipt(
        request_id=request.request_id,
        state=ReceiptState.FAILED_RETRYABLE,
        transport="telegram",
        public_message="raw fallback",
        operational_issue=request.operational_issue,
    )
    _update_queue_state(Queue(), request, receipt, now=datetime.now(timezone.utc))
    assert calls == [""]


def test_shared_handler_source_routes_operational_receipts_to_finalizer() -> None:
    source_path = Path(__file__).parents[1] / "plugins" / "bot_unified_runtime" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    source = source_path.read_text(encoding="utf-8")
    assert "_notify_operational_receipt" in source
    handlers = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name in {"_handle_content", "_handle_music", "_run_simple_capability"}
    }
    assert handlers.keys() == {
        "_handle_content",
        "_handle_music",
        "_run_simple_capability",
    }
    for handler in handlers.values():
        notifier_calls = [
            call
            for call in ast.walk(handler)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_notify_operational_receipt"
        ]
        assert len(notifier_calls) >= 2
    assert "sent_requests, []))[-len(sent)" not in source


@pytest.mark.asyncio
async def test_pipeline_helper_notifies_issue_before_successful_transport_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    message = _message(SessionType.PRIVATE)
    issue = _issue(stage="context", kind="provider_failed")
    pipeline_receipt = DeliveryReceipt(
        request_id=message.request_id,
        state=ReceiptState.FAILED_FINAL,
        transport="runtime",
        public_message="",
        operational_issue=issue,
    )
    transport_receipt = DeliveryReceipt(
        request_id=message.request_id,
        state=ReceiptState.SENT,
        transport="telegram",
        public_message="sent",
    )
    calls: list[DeliveryReceipt] = []

    class Pipeline:
        def handle(self, *_args: object, **_kwargs: object) -> DeliveryReceipt:
            return pipeline_receipt

    pipeline_request = _send_request(issue).model_copy(
        update={"request_id": message.request_id}
    )

    class Queue:
        def find_request(self, request_id: str) -> SendRequest | None:
            return pipeline_request if request_id == message.request_id else None

    async def notifier(receipt: DeliveryReceipt) -> None:
        calls.append(receipt)

    monkeypatch.setattr(
        runtime_module,
        "_incoming_from_nonebot_event",
        lambda _event, bot_id="unknown": message,
    )
    monkeypatch.setattr(
        runtime_module,
        "_deliver_transport_send_request",
        lambda *_args, **_kwargs: transport_receipt,
    )
    result = await _run_capability_through_pipeline(
        bot=object(),
        event=object(),
        config=SimpleNamespace(),
        pipeline=Pipeline(),
        send_queue=Queue(),
        audit_logger=InMemoryAuditLogger(),
        diagnostics_store=SimpleNamespace(record=lambda _diagnostic: None),
        capability=lambda *_args: None,
        capability_id="bot.chat",
        record_diagnostic=False,
        operational_notifier=notifier,
    )
    assert result.state is ReceiptState.SENT
    assert calls == [pipeline_receipt]


def test_sqlite_receipt_roundtrip_preserves_operational_issue(tmp_path) -> None:
    repository = SQLiteReceiptRepository(tmp_path / "receipts.sqlite3")
    issue = _issue(stage="onebot", kind="retcode_failure")
    receipt = DeliveryReceipt(
        request_id="req-sqlite",
        state=ReceiptState.FAILED_FINAL,
        transport="onebot",
        public_message="",
        debug_id="dbg-sqlite",
        operational_issue=issue,
    )
    repository.record(receipt)
    restored = repository.latest("req-sqlite")
    assert restored is not None
    assert restored.operational_issue == issue
    assert restored.public_message == ""


def test_sqlite_receipt_repository_forces_public_message_empty_for_issue(tmp_path) -> None:
    repository = SQLiteReceiptRepository(tmp_path / "receipts.sqlite3")
    issue = _issue(stage="onebot", kind="retcode_failure")
    receipt = DeliveryReceipt(
        request_id="req-sqlite-safe",
        state=ReceiptState.FAILED_FINAL,
        transport="onebot",
        public_message="raw retcode detail",
        debug_id="dbg-sqlite-safe",
        operational_issue=issue,
    )
    restored = repository.record(receipt)
    assert restored.public_message == ""
    loaded = repository.latest(receipt.request_id)
    assert loaded is not None
    assert loaded.public_message == ""
    assert loaded.operational_issue == issue


def test_record_transport_receipt_marks_sqlite_final_failure() -> None:
    class Queue:
        def __init__(self) -> None:
            self.final_calls: list[tuple[str, str]] = []

        def mark_final_failure(self, request_id: str, public_message: str) -> DeliveryReceipt:
            self.final_calls.append((request_id, public_message))
            return DeliveryReceipt(
                request_id=request_id,
                state=ReceiptState.FAILED_FINAL,
                transport="sqlite_queue",
                public_message=public_message,
            )

    audit = InMemoryAuditLogger()
    request = _send_request(_issue(stage="onebot", kind="retcode_failure"))
    receipt = DeliveryReceipt(
        request_id=request.request_id,
        state=ReceiptState.FAILED_FINAL,
        transport="onebot",
        public_message="raw retcode fallback",
        operational_issue=request.operational_issue,
    )
    _record_transport_receipt(receipt, request, audit, send_queue=Queue())
    queue = Queue()
    _record_transport_receipt(receipt, request, audit, send_queue=queue)
    assert queue.final_calls == [(request.request_id, "")]


def test_sqlite_queue_preserves_operational_issue_across_states(tmp_path) -> None:
    queue = SQLiteSendRequestQueue(tmp_path / "send.sqlite3", InMemoryAuditLogger())
    issue = _issue(stage="onebot", kind="retcode_failure")
    request = _send_request(issue)
    queued = queue.submit(request)
    assert queued.operational_issue == issue
    assert queued.public_message == ""
    retryable = queue.mark_retryable_failure(request.request_id, "raw retry detail")
    assert retryable.operational_issue == issue
    assert retryable.public_message == ""
    sent = queue.mark_sent(request.request_id, "sent")
    assert sent.operational_issue == issue
    assert sent.public_message == ""
    final = queue.mark_final_failure(request.request_id, "raw final detail")
    assert final.operational_issue == issue
    assert final.public_message == ""
    due = queue.list_due(limit=10)
    assert due == []


def test_sqlite_receipt_repository_forces_empty_public_message_for_issue(tmp_path) -> None:
    repository = SQLiteReceiptRepository(tmp_path / "receipts.sqlite3")
    receipt = DeliveryReceipt(
        request_id="req-persist-safe",
        state=ReceiptState.FAILED_FINAL,
        transport="onebot",
        public_message="raw leaked fallback",
        operational_issue=_issue(stage="onebot", kind="retcode_failure"),
    )
    restored = repository.record(receipt)
    assert restored.public_message == ""
    loaded = repository.latest(receipt.request_id)
    assert loaded is not None
    assert loaded.public_message == ""
    assert loaded.operational_issue == receipt.operational_issue


def test_queue_bot_unavailable_receipt_is_typed_and_silent() -> None:
    request = _send_request()
    receipt = _queue_bot_unavailable_receipt(request)
    assert receipt.public_message == ""
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.stage == "queue"
    assert receipt.operational_issue.kind == "bot_unavailable"
    assert receipt.operational_issue.retryable is True
    assert receipt.operational_issue.safe_summary == "bot_unavailable"


def test_credential_bot_selection_chooses_matching_onebot_only() -> None:
    class Adapter:
        def __init__(self, name: str) -> None:
            self.name = name

        def get_name(self) -> str:
            return self.name

    qq = SimpleNamespace(adapter=Adapter("OneBot V11"), self_id="qq-real")
    telegram = SimpleNamespace(adapter=Adapter("Telegram"), self_id="telegram-real")
    selected = _select_credential_bot({"qq": qq, "telegram": telegram})
    assert selected is qq


def test_role_settings_keep_qq_and_telegram_admin_ids_separate() -> None:
    config = Config(
        bot_admin_user_ids=["1001"],
        bot_telegram_admin_user_ids=["2002"],
    )
    roles = build_role_settings(config)
    assert roles.admin_user_ids == frozenset({"1001", "2002"})
    targets = build_typed_admin_targets(
        qq_admin_ids=config.bot_admin_user_ids,
        telegram_user_ids=config.bot_telegram_admin_user_ids,
        qq_bot_id="qq-bot",
        telegram_bot_id="telegram-bot",
    )
    assert [target.adapter for target in targets] == ["onebot", "telegram"]


def test_credential_alert_enqueuing_returns_explicit_request_ids() -> None:
    audit = InMemoryAuditLogger()
    from plugins.bot_unified_runtime.sender.queue import InMemorySendQueue

    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)
    alert = alerts_module.AlertContent(
        title="credential warning",
        what_happened="credential unavailable",
        impact="source unavailable",
        fix_suggestion="refresh credential",
        location="credential check",
    )
    created = alerts_module.send_admin_alert_requests(pipeline, ["1001"], alert)
    assert len(created) == 1
    assert created[0][0] == "1001"
    assert created[0][1].startswith("req_")
    request = queue.find_request(created[0][1])
    assert request is not None
    assert request.target_id == "1001"
    assert "admin_alert" in request.audit_tags
    assert "origin:admin_alert" in request.audit_tags


def test_admin_target_builder_skips_offline_adapter_without_cross_routing() -> None:
    targets = build_typed_admin_targets(
        qq_admin_ids=["1001"],
        telegram_user_ids=["2002"],
        qq_bot_id="",
        telegram_bot_id="telegram-bot",
    )
    assert targets == [
        AdminTarget(adapter="telegram", bot_id="telegram-bot", target_id="2002")
    ]


def test_admin_target_builder_keeps_adapters_typed_and_validates_nonblank() -> None:
    targets = build_typed_admin_targets(
        qq_admin_ids=["1001", ""],
        telegram_user_ids=["2002"],
        telegram_chat_ids=["3003"],
        qq_bot_id="qq-bot",
        telegram_bot_id="telegram-bot",
    )
    assert targets == [
        AdminTarget(adapter="onebot", bot_id="qq-bot", target_id="1001"),
        AdminTarget(adapter="telegram", bot_id="telegram-bot", target_id="2002"),
        AdminTarget(adapter="telegram", bot_id="telegram-bot", target_id="3003", target_scope=SessionType.GROUP),
    ]
    with pytest.raises(ValueError):
        AdminTarget(adapter="", bot_id="bot", target_id="1")
    with pytest.raises(ValueError):
        AdminTarget(adapter="telegram", bot_id="", target_id="1")


def test_admin_alert_suppression_uses_injected_clock_and_exposes_count() -> None:
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    suppression = AdminAlertSuppression(clock=lambda: now[0])
    key = ("llm", "timeout", "telegram", "bot", "private", "target")
    assert suppression.allow(key) == (True, 0)
    assert suppression.allow(key) == (False, 1)
    assert suppression.allow(key) == (False, 2)
    now[0] += timedelta(seconds=301)
    assert suppression.allow(key) == (True, 2)

    text = build_operational_alert_text(
        _issue(stage="llm", kind="timeout", attempts=2, elapsed_ms=5),
        source_adapter="telegram",
        source_bot="bot-1",
        session_type=SessionType.PRIVATE,
        suppressed_count=2,
    )
    assert "secret user" not in text
    assert "raw exception" not in text
    assert "timeout" in text and "suppressed_count=2" in text


@pytest.mark.asyncio
async def test_operational_issue_notifier_suppresses_per_typed_target() -> None:
    target = AdminTarget(adapter="telegram", bot_id="bot-1", target_id="100")
    now = [0.0]
    suppression = AdminAlertSuppression(clock=lambda: now[0])
    delivered: list[SendRequest] = []

    async def delivery(_target: AdminTarget, _bot: object, request: SendRequest) -> None:
        delivered.append(request)

    first = await alerts_module.notify_operational_issue(
        _issue(stage="llm", kind="timeout"),
        source_adapter="telegram",
        source_bot="source-bot",
        session_type=SessionType.PRIVATE,
        targets=[target],
        online_bots={"bot-1": object()},
        delivery=delivery,
        suppression=suppression,
    )
    second = await alerts_module.notify_operational_issue(
        _issue(stage="llm", kind="timeout"),
        source_adapter="telegram",
        source_bot="source-bot",
        session_type=SessionType.PRIVATE,
        targets=[target],
        online_bots={"bot-1": object()},
        delivery=delivery,
        suppression=suppression,
    )
    assert first[0].success is True
    assert first[0].request_id.startswith("admin_alert_")
    assert first[0].suppressed is False
    assert second[0].success is False
    assert second[0].suppressed is True
    assert second[0].suppressed_count == 1
    assert len(delivered) == 1
    assert delivered[0].audit_tags == ["admin_alert", "origin:admin_alert"]
    now[0] = 301.0
    third = await alerts_module.notify_operational_issue(
        _issue(stage="llm", kind="timeout"),
        source_adapter="telegram",
        source_bot="source-bot",
        session_type=SessionType.PRIVATE,
        targets=[target],
        online_bots={"bot-1": object()},
        delivery=delivery,
        suppression=suppression,
    )
    assert third[0].success is True
    assert third[0].suppressed_count == 1
    assert "suppressed_count=1" in delivered[-1].content.text_fallback


@pytest.mark.asyncio
async def test_queue_worker_notifies_typed_failure_without_blocking_state_update() -> None:
    request = _send_request()
    issue = _issue(stage="queue", kind="bot_unavailable")
    transport_receipt = DeliveryReceipt(
        request_id=request.request_id,
        state=ReceiptState.FAILED_RETRYABLE,
        transport="send_queue_worker",
        public_message="",
        operational_issue=issue,
    )
    now = datetime.now(timezone.utc)
    entry = QueuedSendRequest(
        send_request=request,
        state=ReceiptState.QUEUED,
        retry_count=0,
        next_retry_at=None,
        created_at=now,
        updated_at=now,
    )
    notified: list[DeliveryReceipt] = []

    class Queue:
        def list_due(self, *, now=None, limit=20) -> list[QueuedSendRequest]:
            return [entry]

        def mark_retryable_failure(self, request_id: str, public_message: str, *, now=None) -> DeliveryReceipt:
            assert public_message == ""
            return transport_receipt

        def mark_final_failure(self, request_id: str, public_message: str, *, now=None) -> DeliveryReceipt:
            return transport_receipt

        def mark_sent(self, request_id: str, public_message: str = "sent", *, now=None) -> DeliveryReceipt:
            return transport_receipt

    async def notifier(receipt: DeliveryReceipt) -> None:
        notified.append(receipt)

    result = await drain_send_queue_once(
        Queue(),
        lambda _request: _resolved(transport_receipt),
        now=now,
        operational_notifier=notifier,
    )
    assert result.retryable_failed == 1
    assert notified == [transport_receipt]


async def _resolved(value: DeliveryReceipt) -> DeliveryReceipt:
    return value


@pytest.mark.asyncio
async def test_queue_worker_transport_exception_is_typed_and_silent() -> None:
    async def fail(_request: SendRequest) -> DeliveryReceipt:
        raise RuntimeError("queue secret exception")

    receipt = await _call_transport_safely(_send_request(), fail)
    assert receipt.public_message == ""
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.stage == "queue"
    assert receipt.operational_issue.kind == "transport_exception"
    assert "queue secret exception" not in repr(receipt)


@pytest.mark.asyncio
async def test_admin_alert_dispatch_failure_returns_failed_result_without_recursion() -> None:
    targets = [AdminTarget(adapter="telegram", bot_id="bot-1", target_id="100")]
    result = await dispatch_admin_alert(
        targets,
        online_bots={"bot-1": object()},
        delivery=lambda target, bot, text: (_ for _ in ()).throw(RuntimeError("secret")),
        text="safe alert",
    )
    assert len(result) == 1
    assert result[0].success is False
    assert result[0].error_kind == "send_exception"
    assert "secret" not in repr(result[0])


@pytest.mark.asyncio
async def test_admin_alert_failed_receipt_and_registry_failure_are_results() -> None:
    target = AdminTarget(adapter="telegram", bot_id="bot-1", target_id="100")

    async def failed_delivery(
        _target: AdminTarget,
        _bot: object,
        request: SendRequest,
    ) -> DeliveryReceipt:
        return DeliveryReceipt(
            request_id=request.request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport="telegram",
            public_message="",
            operational_issue=_issue(stage="telegram", kind="send_exception"),
        )

    failed = await dispatch_admin_alert(
        [target],
        online_bots={"bot-1": object()},
        delivery=failed_delivery,
        text="safe alert",
    )
    unavailable = await dispatch_admin_alert(
        [target],
        online_bots=lambda: (_ for _ in ()).throw(RuntimeError("registry secret")),
        delivery=failed_delivery,
        text="safe alert",
    )
    assert failed[0].success is False
    assert failed[0].error_kind == "send_exception"
    assert unavailable[0].success is False
    assert unavailable[0].error_kind == "registry_unavailable"
    assert "secret" not in repr(unavailable[0])


def test_runtime_logging_handler_redacts_and_bounds_message(tmp_path) -> None:
    log = RuntimeEventLog(tmp_path / "runtime.log")
    bridge = log.attach_to_logging("task2-test")
    import logging

    logger = logging.getLogger("task2-test")
    logger.warning("Authorization: Bearer abc123 token=secret-cookie %s", "x" * 1000)
    bridge.close()
    line = (tmp_path / "runtime.log").read_text(encoding="utf-8")
    assert "abc123" not in line
    assert "secret-cookie" not in line
    assert len(line.split("message=", 1)[1].strip()) <= 500


def test_credential_alert_request_uses_onebot_adapter_and_recovery_wildcard() -> None:
    audit = InMemoryAuditLogger()
    from plugins.bot_unified_runtime.sender.queue import InMemorySendQueue

    queue = InMemorySendQueue(audit)
    pipeline = RuntimePipeline(queue, audit)
    alert = alerts_module.AlertContent(
        title="credential warning",
        what_happened="credential unavailable",
        impact="source unavailable",
        fix_suggestion="refresh credential",
        location="credential check",
    )
    created = alerts_module.send_admin_alert_requests(pipeline, ["1001"], alert)
    assert created
    request = queue.find_request(created[0][1])
    assert request is not None
    assert request.adapter == "onebot"
    assert request.bot_id not in {"runtime-alert", ""}
    assert request.target_id == "1001"


def test_sqlite_final_transport_receipt_is_terminal_and_not_due(tmp_path) -> None:
    audit = InMemoryAuditLogger()
    queue = SQLiteSendRequestQueue(
        tmp_path / "send.sqlite3",
        audit,
        max_attempts=3,
    )
    request = _send_request(_issue(stage="onebot", kind="retcode_failure"))
    queue.submit(request)
    receipt = DeliveryReceipt(
        request_id=request.request_id,
        state=ReceiptState.FAILED_FINAL,
        transport="onebot.v11",
        public_message="retcode detail must stay private",
        operational_issue=request.operational_issue,
    )
    recorded = _record_transport_receipt(receipt, request, audit, send_queue=queue)
    assert recorded.public_message == ""
    assert queue.safe_summary()[ReceiptState.FAILED_FINAL.value] == 1
    assert queue.list_due(limit=10) == []
    assert all(
        record.public_message == ""
        for record in audit.list_records(request.request_id)
        if record.stage == "sender"
    )


def test_all_pipeline_helper_calls_provide_operational_notifier() -> None:
    source_path = Path(__file__).parents[1] / "plugins" / "bot_unified_runtime" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_run_capability_through_pipeline"
    ]
    assert calls
    assert all(
        any(keyword.arg == "operational_notifier" for keyword in call.keywords)
        for call in calls
    )

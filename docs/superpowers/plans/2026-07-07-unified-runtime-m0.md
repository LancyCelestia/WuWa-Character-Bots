# Unified Runtime M0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable NoneBot local plugin skeleton for the unified Bot character bot runtime.

**Architecture:** Implement the documented chain as a narrow, testable runtime shell: `IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord`. Capability, parser, character, knowledge, and auto-send modules expose structured interfaces only; sender/transport remains the only layer allowed to touch future concrete adapters.

**Tech Stack:** Python 3.10+, Pydantic v2 via NoneBot dependencies, pytest, NoneBot2 local plugin under `plugins/bot_unified_runtime`, Windows dev entry `scripts/dev.ps1`.

## Global Constraints

- Do not create a sandbox or git worktree.
- Do not implement on `main`; work on `feature/unified-runtime-m0`.
- Follow the root docs and Chinese specs as the source of truth.
- Use TDD: write a failing test and verify it fails before production code.
- Keep capability/source/parser/provider layers from importing or calling OneBot, NapCat, Mail, `event.send`, `bot.send_private_msg`, or `bot.send_group_msg`.
- Use `SendRequest -> DeliveryReceipt -> AuditRecord` as the only send boundary.
- Normal natural-language reply context must go through persona, tone, memory, knowledge, and emotion interfaces.
- Plugin effects such as links, media cards, subscriptions, and mail/message sending must be deterministic structured flows, not direct LLM replies.
- Auto-send M0 is draft/preview/confirmation data modeling only; real mail/chat transport is an interface or blocked receipt.
- Prefer Pydantic models and protocols over hidden dictionaries.
- Keep tests runnable without a live NoneBot/NapCat process.

---

## File Structure

- `plugins/bot_unified_runtime/__init__.py`: NoneBot plugin metadata and minimal command/message registration.
- `plugins/bot_unified_runtime/config.py`: plugin config model with conservative defaults.
- `plugins/bot_unified_runtime/contracts/runtime.py`: core runtime contract models and enums.
- `plugins/bot_unified_runtime/contracts/character.py`: persona, tone, emotion, memory, knowledge context models.
- `plugins/bot_unified_runtime/contracts/media.py`: parser/source/media models.
- `plugins/bot_unified_runtime/contracts/auto_send.py`: auto-send intent, recipient, draft, preview models.
- `plugins/bot_unified_runtime/policy/gate.py`: conservative policy evaluation.
- `plugins/bot_unified_runtime/runtime/pipeline.py`: orchestrates one structured runtime pass.
- `plugins/bot_unified_runtime/output/reviewer.py`: privacy/risk/persona-aware output review.
- `plugins/bot_unified_runtime/output/renderer.py`: text-first rendered output generation.
- `plugins/bot_unified_runtime/sender/queue.py`: in-memory send queue and dedupe/cooldown gate.
- `plugins/bot_unified_runtime/sender/receipts.py`: receipt helpers and blocked transport adapter.
- `plugins/bot_unified_runtime/audit/logger.py`: in-memory audit logger with redaction.
- `plugins/bot_unified_runtime/character/providers.py`: provider protocols and safe null implementations.
- `plugins/bot_unified_runtime/sources/registry.py`: parser registry and URL/keyword matching shell.
- `plugins/bot_unified_runtime/capabilities/echo.py`: low-risk structured echo/status capability for smoke testing.
- `plugins/bot_unified_runtime/capabilities/auto_send/parser.py`: conservative auto-send command parser for draft-only M0.
- `tests/test_contracts_runtime.py`: contract validation tests.
- `tests/test_runtime_pipeline.py`: policy/pipeline/sender/audit tests.
- `tests/test_character_sources_autosend.py`: provider/parser/auto-send tests.
- `tests/test_nonebot_plugin_entry.py`: plugin import and metadata tests.
- `scripts/dev.ps1`: update `plugin-check` / `verify` after tests exist.
- `README.md` and `COMMANDS.md`: update only after behavior exists.

---

## Task 1: Runtime Contracts And Test Harness

**Files:**
- Create: `plugins/bot_unified_runtime/contracts/runtime.py`
- Create: `plugins/bot_unified_runtime/contracts/__init__.py`
- Create: `tests/test_contracts_runtime.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: enums `RiskLevel`, `PrivacyLevel`, `SendPolicy`, `ReceiptState`, `SessionType`.
- Produces: models `IncomingMessage`, `PolicyEvaluation`, `BotDecision`, `CapabilityResult`, `ReviewResult`, `RenderedOutput`, `SendRequest`, `DeliveryReceipt`, `AuditRecord`.
- Produces: helper `new_request_id(prefix: str = "req") -> str`.
- Later tasks must import contract models only from `plugins.bot_unified_runtime.contracts`.

- [ ] **Step 1: Write failing contract tests**

```python
from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
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
    new_request_id,
)


def test_request_id_is_generated_with_prefix():
    request_id = new_request_id("test")
    assert request_id.startswith("test_")
    assert len(request_id) > len("test_")


def test_incoming_message_requires_normalized_session_fields():
    message = IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id="group:123",
        session_type=SessionType.GROUP,
        sender_id="42",
        plain_text="hello",
        raw_segments=[{"type": "text", "data": {"text": "hello"}}],
        mentions_bot=False,
        timestamp=datetime.now(timezone.utc),
    )
    assert message.request_id.startswith("req_")
    assert message.group_id is None
    assert message.privacy_level is PrivacyLevel.GROUP


def test_send_request_requires_dedupe_and_cooldown_keys():
    rendered = RenderedOutput(
        request_id="req_test",
        content_type="text",
        content_ref={"text": "ok"},
        text_fallback="ok",
    )
    with pytest.raises(ValueError, match="dedupe_key"):
        SendRequest(
            request_id="req_test",
            session_id="private:42",
            target_scope=SessionType.PRIVATE,
            target_id="42",
            capability_id="test",
            content=rendered,
            send_policy=SendPolicy.IMMEDIATE,
            priority="normal",
            max_messages=1,
            dedupe_key="",
            cooldown_key="cooldown:test",
            expires_at=None,
            privacy_level=PrivacyLevel.PERSONAL,
            allow_split=False,
            allow_forward=False,
            persona_profile_id="default",
        )


def test_delivery_receipt_and_audit_record_share_request_id():
    receipt = DeliveryReceipt(
        request_id="req_test",
        state=ReceiptState.BLOCKED,
        transport="blocked",
        public_message="blocked",
        debug_id="dbg_test",
    )
    audit = AuditRecord(
        request_id=receipt.request_id,
        session_id="private:42",
        capability_id="test",
        stage="sender",
        event="blocked",
        severity=RiskLevel.MEDIUM,
        public_message=receipt.public_message,
        private_debug="blocked by test",
    )
    assert audit.request_id == "req_test"
    assert audit.public_message == "blocked"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_contracts_runtime.py -q`

Expected: FAIL during import with `ModuleNotFoundError` or missing contract names.

- [ ] **Step 3: Implement minimal contracts**

Create focused Pydantic models with defaults and validators:

```python
class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
```

`IncomingMessage` must default `request_id` with `new_request_id`, default group privacy to `group`, default private privacy to `personal`, and keep `raw_segments` as a list.

`SendRequest` must reject blank `dedupe_key` and `cooldown_key`.

`AuditRecord` must default `audit_id` with `audit_` and `created_at` with UTC.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_contracts_runtime.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml plugins/bot_unified_runtime/contracts tests/test_contracts_runtime.py
git commit -m "feat: add runtime contract models"
```

---

## Task 2: Policy, Review, Sender Queue, Audit, And Pipeline

**Files:**
- Create: `plugins/bot_unified_runtime/policy/gate.py`
- Create: `plugins/bot_unified_runtime/policy/__init__.py`
- Create: `plugins/bot_unified_runtime/output/reviewer.py`
- Create: `plugins/bot_unified_runtime/output/renderer.py`
- Create: `plugins/bot_unified_runtime/output/__init__.py`
- Create: `plugins/bot_unified_runtime/sender/queue.py`
- Create: `plugins/bot_unified_runtime/sender/receipts.py`
- Create: `plugins/bot_unified_runtime/sender/__init__.py`
- Create: `plugins/bot_unified_runtime/audit/logger.py`
- Create: `plugins/bot_unified_runtime/audit/__init__.py`
- Create: `plugins/bot_unified_runtime/runtime/pipeline.py`
- Create: `plugins/bot_unified_runtime/runtime/__init__.py`
- Create: `tests/test_runtime_pipeline.py`

**Interfaces:**
- Consumes: Task 1 runtime contracts.
- Produces: `evaluate_policy(message, capability_id) -> PolicyEvaluation`.
- Produces: `review_capability_result(result, decision) -> ReviewResult`.
- Produces: `render_reviewed_output(result, review) -> RenderedOutput`.
- Produces: `InMemoryAuditLogger.append(record)`, `list_records(request_id=None)`.
- Produces: `InMemorySendQueue.submit(send_request) -> DeliveryReceipt`.
- Produces: `RuntimePipeline.handle(message, capability) -> DeliveryReceipt`.

- [ ] **Step 1: Write failing pipeline tests**

```python
from datetime import datetime, timezone

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    ReceiptState,
    RiskLevel,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.runtime import RuntimePipeline
from plugins.bot_unified_runtime.sender import InMemorySendQueue


def make_message(text="/bot status", session_type=SessionType.PRIVATE):
    return IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id="private:42" if session_type is SessionType.PRIVATE else "group:100",
        session_type=session_type,
        sender_id="42",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=session_type is SessionType.PRIVATE,
        timestamp=datetime.now(timezone.utc),
    )


def test_policy_blocks_passive_group_message_before_capability_runs():
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(send_queue=queue, audit_logger=audit)
    called = False

    def capability(_message, _decision):
        nonlocal called
        called = True
        return CapabilityResult(kind="text", title="bad", body="bad", capability_id="test")

    receipt = pipeline.handle(make_message("hello", SessionType.GROUP), capability)
    assert receipt.state is ReceiptState.BLOCKED
    assert called is False
    assert audit.list_records(receipt.request_id)[0].event == "policy_denied"


def test_pipeline_turns_capability_result_into_sent_receipt_and_audit():
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(send_queue=queue, audit_logger=audit)

    def capability(message, decision):
        return CapabilityResult(
            request_id=message.request_id,
            capability_id=decision.capability_id,
            kind="text",
            title="状态",
            body="统一运行时在线",
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PERSONAL,
            send_policy=SendPolicy.IMMEDIATE,
        )

    receipt = pipeline.handle(make_message(), capability)
    assert receipt.state is ReceiptState.SENT
    assert queue.sent_requests[0].dedupe_key.startswith("bot.status:")
    assert any(record.event == "sent" for record in audit.list_records(receipt.request_id))


def test_sender_dedupes_second_request():
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(send_queue=queue, audit_logger=audit)
    message = make_message()

    def capability(message, decision):
        return CapabilityResult(
            request_id=message.request_id,
            capability_id=decision.capability_id,
            kind="text",
            title="状态",
            body="统一运行时在线",
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PERSONAL,
            send_policy=SendPolicy.IMMEDIATE,
        )

    first = pipeline.handle(message, capability)
    second = pipeline.handle(message, capability)
    assert first.state is ReceiptState.SENT
    assert second.state is ReceiptState.SKIPPED
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_runtime_pipeline.py -q`

Expected: FAIL because pipeline, audit, sender, or policy modules do not exist.

- [ ] **Step 3: Implement minimal runtime shell**

Implement conservative defaults:

- passive group text without command prefix `/bot` and without mention is denied before capability call;
- private messages are allowed;
- `critical` risk blocks;
- renderer returns text output first;
- queue stores sent requests in memory and skips duplicate `dedupe_key`;
- blocked/skipped/sent paths all append `AuditRecord`.

`RuntimePipeline.handle` must catch unexpected exceptions, create `DeliveryReceipt.failed_final`, and append an `internal_error` audit with redacted private debug.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_runtime_pipeline.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add plugins/bot_unified_runtime/policy plugins/bot_unified_runtime/output plugins/bot_unified_runtime/sender plugins/bot_unified_runtime/audit plugins/bot_unified_runtime/runtime tests/test_runtime_pipeline.py
git commit -m "feat: add unified runtime pipeline shell"
```

---

## Task 3: Character, Knowledge, Source Registry, And Auto-Send Draft Interfaces

**Files:**
- Create: `plugins/bot_unified_runtime/contracts/character.py`
- Create: `plugins/bot_unified_runtime/contracts/media.py`
- Create: `plugins/bot_unified_runtime/contracts/auto_send.py`
- Create: `plugins/bot_unified_runtime/character/providers.py`
- Create: `plugins/bot_unified_runtime/character/__init__.py`
- Create: `plugins/bot_unified_runtime/sources/registry.py`
- Create: `plugins/bot_unified_runtime/sources/__init__.py`
- Create: `plugins/bot_unified_runtime/capabilities/auto_send/parser.py`
- Create: `plugins/bot_unified_runtime/capabilities/auto_send/__init__.py`
- Create: `plugins/bot_unified_runtime/capabilities/__init__.py`
- Create: `tests/test_character_sources_autosend.py`

**Interfaces:**
- Consumes: Task 1 runtime contracts.
- Produces: character models `EmotionSignal`, `MemoryQuery`, `MemoryRetrievalResult`, `PersonaProfile`, `ToneProfile`, `KnowledgeSource`, `KnowledgeChunk`, `RetrievalResult`, `ContextBundle`.
- Produces: provider protocols and null implementations that return empty but structured results.
- Produces: media models `SourceInput`, `ParseRequest`, `ParsedMediaItem`, `NormalizedMediaItem`, `ParserRule`.
- Produces: `ParserRegistry.register(rule)`, `match(source_input)`.
- Produces: auto-send models `AutoSendIntent`, `RecipientDescriptor`, `RecipientResolution`, `GeneratedDraft`, `DraftPreview`.
- Produces: `parse_auto_send_command(text, actor_sender_id, actor_session_id, actor_session_type)`.

- [ ] **Step 1: Write failing interface tests**

```python
from plugins.bot_unified_runtime.capabilities.auto_send import parse_auto_send_command
from plugins.bot_unified_runtime.character import NullCharacterContextProvider
from plugins.bot_unified_runtime.contracts import PrivacyLevel, SessionType
from plugins.bot_unified_runtime.sources import ParserRegistry, ParserRule, SourceInput


def test_null_character_provider_returns_persona_tone_and_empty_context():
    provider = NullCharacterContextProvider()
    bundle = provider.build_context(
        request_id="req_test",
        sender_id="42",
        session_id="private:42",
        query_text="你好",
    )
    assert bundle.persona.profile_id == "default"
    assert bundle.tone.mode == "private_chat"
    assert bundle.memory_results.facts == []
    assert bundle.knowledge_results.chunks == []


def test_parser_registry_prefers_longest_keyword_then_priority():
    registry = ParserRegistry()
    registry.register(ParserRule(parser_id="generic_bili", source_id="bilibili", keyword_patterns=["bili"], priority=10))
    registry.register(ParserRule(parser_id="video_bili", source_id="bilibili", keyword_patterns=["bilibili.com/video"], priority=1))
    matches = registry.match(SourceInput(request_id="req_test", session_id="group:1", capability_id="media_parse", raw_text="https://www.bilibili.com/video/BV1xx", privacy_level=PrivacyLevel.GROUP))
    assert [m.parser_id for m in matches][:2] == ["video_bili", "generic_bili"]


def test_auto_send_parser_creates_draft_intent_but_not_send_request():
    intent = parse_auto_send_command(
        "报存 给 A、B 发邮件，主题：周末安排，内容根据你对他们的了解分别写",
        actor_sender_id="42",
        actor_session_id="private:42",
        actor_session_type=SessionType.PRIVATE,
    )
    assert intent.action == "draft"
    assert intent.channel == "email"
    assert [r.raw_text for r in intent.recipient_descriptors] == ["A", "B"]
    assert intent.requested_send_policy == "confirm_required"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_character_sources_autosend.py -q`

Expected: FAIL because character, sources, and auto-send modules do not exist.

- [ ] **Step 3: Implement structured interfaces only**

Implement M0 behavior:

- null character provider returns safe defaults and empty context;
- parser registry sorts matching rules by longest keyword length, then ascending priority;
- auto-send parser recognizes `报存 给 ... 发消息` and `报存 给 ... 发邮件`;
- parser returns draft intent only and never creates `SendRequest`;
- unresolved recipients stay as descriptors for later resolution.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_character_sources_autosend.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add plugins/bot_unified_runtime/contracts/character.py plugins/bot_unified_runtime/contracts/media.py plugins/bot_unified_runtime/contracts/auto_send.py plugins/bot_unified_runtime/character plugins/bot_unified_runtime/sources plugins/bot_unified_runtime/capabilities tests/test_character_sources_autosend.py
git commit -m "feat: add character source and autosend interfaces"
```

---

## Task 4: NoneBot Plugin Entry, Commands, Dev Verification, And Docs

**Files:**
- Create: `plugins/bot_unified_runtime/__init__.py`
- Create: `plugins/bot_unified_runtime/config.py`
- Create: `plugins/bot_unified_runtime/capabilities/echo.py`
- Create: `tests/test_nonebot_plugin_entry.py`
- Modify: `scripts/dev.ps1`
- Modify: `README.md`
- Modify: `COMMANDS.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: NoneBot `__plugin_meta__`.
- Produces: status capability command `/bot status`.
- Produces: auto-send draft command path that returns preview-only text.
- Produces: plugin-check that expects `plugins/bot_unified_runtime/__init__.py`.
- Produces: verify that runs tests when `tests/` exists.

- [ ] **Step 1: Write failing plugin entry tests**

```python
import importlib


def test_nonebot_plugin_imports_and_has_metadata():
    module = importlib.import_module("plugins.bot_unified_runtime")
    meta = module.__plugin_meta__
    assert meta.name == "Bot Unified Runtime"
    assert "~onebot.v11" in meta.supported_adapters


def test_status_capability_returns_structured_result():
    from plugins.bot_unified_runtime.capabilities.echo import build_status_result

    result = build_status_result(request_id="req_test")
    assert result.capability_id == "bot.status"
    assert result.body == "统一运行时在线"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_nonebot_plugin_entry.py -q`

Expected: FAIL because plugin entry and status capability do not exist.

- [ ] **Step 3: Implement plugin entry**

Implement `__plugin_meta__` with:

- name: `Bot Unified Runtime`
- description: `统一角色机器人运行时、人格上下文、媒体解析和发送审计入口`
- usage: `/bot status`
- type: `application`
- supported_adapters: `{"~onebot.v11", "~console", "~mail"}`

Guard optional NoneBot handler registration so plain pytest import works without a running bot process. Handlers may import NoneBot, but tests must not require live adapters.

- [ ] **Step 4: Update dev verification**

Modify `scripts/dev.ps1`:

- `plugin-check` must fail if `plugins/bot_unified_runtime/__init__.py` is missing.
- `verify` must run pytest because `tests/` now exists.
- keep lint/typecheck optional until tools are installed.

- [ ] **Step 5: Update docs after behavior exists**

Update README, COMMANDS, and progress to say Milestone 0 runtime shell exists and `verify` now runs tests.

- [ ] **Step 6: Verify GREEN**

Run:

```powershell
python -m pytest -q
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 docs-check
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify
```

Expected: tests pass; docs-check passes; verify runs pytest and completes with only optional ruff/mypy warnings if those tools are missing.

- [ ] **Step 7: Commit**

```powershell
git add plugins/bot_unified_runtime tests scripts/dev.ps1 README.md COMMANDS.md progress.md docs/superpowers/plans/2026-07-07-unified-runtime-m0.md
git commit -m "feat: wire unified runtime nonebot plugin"
```

---

## Self-Review

- Spec coverage: This plan covers M0/M1 runtime contracts, policy, output review, sender receipts, audit, character/knowledge provider interfaces, source parser registry, auto-send draft parsing, plugin metadata, and dev verification.
- Deferred intentionally: real NapCat transport, real mail sending, LLM generation, persistent database schema, subscription scheduler, Bilibili fetch, HTML image rendering, vector search, and credential handling. Those require separate plans because they touch external systems and higher-risk privacy flows.
- Placeholder scan: no `TBD`, `TODO`, or unspecified file paths.
- Type consistency: tasks import contracts via `plugins.bot_unified_runtime.contracts`; later tasks consume the exact names produced by Task 1.

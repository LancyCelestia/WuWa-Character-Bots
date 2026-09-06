# Defensive Context Compiler and Prompt Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reviewable, redacted PromptArtifact backup and execution gate without modifying persona/worldview source files.

**Architecture:** Build a small PromptAuditStore in the runtime layer. The chat capability creates an artifact immediately after prompt/tool assembly, writes it outside the source workspace, and asks PromptExecutionGate whether to execute, preview, or require an approved digest. Existing retrieval and persona providers remain read-only inputs.

**Tech Stack:** Python 3.12, Pydantic Config, existing chat capability, RuntimePipeline, JSON artifacts, SHA-256, pytest, Ruff, PowerShell.

**Spec:** `docs/superpowers/specs/2026-09-06-defensive-context-compiler-design.md`

## Global Constraints

- Never edit or rewrite persona/worldview source files in this phase.
- Never save secrets, Cookies, Authorization headers, or unredacted API keys in artifacts.
- Artifacts and migration data must be written outside the source workspace when configured.
- Preview mode must not call an LLM or side-effect tool.
- Do not push Git or use `origin`.
- Preserve existing execute-mode behavior unless the new gate is explicitly configured.

### Task 1: Prompt artifact store and execution gate

**Files:**
- Create: `plugins/bot_unified_runtime/runtime/prompt_audit.py`
- Test: `tests/test_prompt_audit.py`

**Interfaces:**
- `PromptExecutionMode` enum: `execute`, `preview`, `approved`.
- `PromptArtifact` dataclass with `artifact_id`, `request_id`, `prompt_sha256`, `messages_redacted`, `tool_ids`, `path`.
- `PromptAuditStore.write(...) -> PromptArtifact`.
- `PromptExecutionGate.decide(artifact, approved_digest) -> str`.

- [ ] Write failing tests for secret redaction, stable digest, external file write, and preview/approval decisions.
- [ ] Run focused tests and confirm failure because the module is absent.
- [ ] Implement atomic JSON write, bounded content length, secret redaction, and SHA-256.
- [ ] Run focused tests and confirm green.

### Task 2: Configurable chat integration

**Files:**
- Modify: `plugins/bot_unified_runtime/config.py`
- Modify: `plugins/bot_unified_runtime/capabilities/chat.py`
- Modify: `plugins/bot_unified_runtime/__init__.py`
- Modify: `plugins/bot_unified_runtime/console_chat.py`
- Modify: `plugins/bot_unified_runtime/backend_unit.py`
- Test: `tests/test_prompt_audit.py`

**Interfaces:**
- `build_chat_result` accepts `prompt_audit_store`, `prompt_execution_mode`, and `approved_prompt_digest` through `llm_options`.
- Preview mode returns a safe `CapabilityResult` without invoking `LLMProvider.generate`.
- Execute mode writes the artifact before provider invocation.
- Approved mode requires exact digest equality.

- [ ] Add failing integration test with a recording fake LLM provider.
- [ ] Run it and confirm the fake provider is called in execute mode but not preview mode.
- [ ] Add Config fields and runtime path resolution.
- [ ] Integrate artifact creation and gate before `_generate_with_tool_loop`.
- [ ] Add backend CLI `--preview` and `--approved-digest` options.
- [ ] Run focused tests and lint.

### Task 3: Runtime docs and smoke commands

**Files:**
- Modify: `.env.example`
- Modify: `COMMANDS.md`
- Modify: `README.md`
- Modify: `scripts/dev.ps1`
- Create: `docs/prompt-audit-and-preview-2026-09-06.md`

- [ ] Document execute/preview/approved workflows and artifact location.
- [ ] Add `prompt-preview` smoke task that never calls LLM.
- [ ] Verify Windows PowerShell 5.1 and pwsh syntax.
- [ ] Run `docs-check`, `backend-smoke`, `startup-smoke`, focused tests, and Ruff.

### Task 4: Runtime migration audit

**Files:**
- Create: `scripts/runtime_migration_audit.py`
- Test: `tests/test_runtime_migration_audit.py`

- [ ] Add read-only manifest/hash/schema/integrity audit for explicitly supplied paths.
- [ ] Never move/delete files automatically.
- [ ] Generate migration report outside source workspace when output path is supplied.
- [ ] Test with temporary SQLite fixtures and verify no source file mutation.

## Verification Checklist

- [ ] Prompt preview artifact is visible and redacted before any real LLM call.
- [ ] Preview mode calls no LLM and no side-effect tool.
- [ ] Approved mode rejects stale or mismatched digest.
- [ ] Execute mode writes artifact before LLM invocation.
- [ ] Persona/worldview source file hashes are recorded but files are unchanged.
- [ ] Runtime migration audit is read-only.
- [ ] No Git push is attempted.
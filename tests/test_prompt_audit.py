from __future__ import annotations

import json

from plugins.bot_unified_runtime.runtime.prompt_audit import (
    PromptAuditStore,
    PromptExecutionGate,
    PromptExecutionMode,
)


def test_prompt_artifact_redacts_secrets_and_has_stable_digest():
    store = PromptAuditStore(None)
    messages = [
        {"role": "system", "content": "safe policy"},
        {
            "role": "user",
            "content": "Authorization: Bearer secret-token sk-abc1234567890",
        },
    ]

    first = store.write(
        request_id="req-1",
        messages=messages,
        tools=[{"function": {"name": "search.web"}}],
        llm_options={"api_key": "secret-token", "temperature": 0.2},
    )
    second = store.write(
        request_id="req-1",
        messages=messages,
        tools=[{"function": {"name": "search.web"}}],
        llm_options={"api_key": "secret-token", "temperature": 0.2},
    )

    assert first.prompt_sha256 == second.prompt_sha256
    assert "secret-token" not in json.dumps(first.messages_redacted)
    assert "sk-abc1234567890" not in json.dumps(first.messages_redacted)
    assert first.path is None
    assert first.tool_ids == ["search.web"]


def test_preview_and_approved_modes_require_matching_digest():
    store = PromptAuditStore(None)
    artifact = store.write(
        request_id="req-2",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        llm_options={},
    )

    gate = PromptExecutionGate()

    assert gate.decide(artifact, PromptExecutionMode.PREVIEW, "") == "preview"
    assert gate.decide(artifact, PromptExecutionMode.APPROVED, "wrong") == "blocked"
    assert gate.decide(artifact, PromptExecutionMode.APPROVED, artifact.prompt_sha256) == "execute"
    assert gate.decide(artifact, PromptExecutionMode.EXECUTE, "") == "execute"
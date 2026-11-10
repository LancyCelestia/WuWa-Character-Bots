"""本地命令 ASR：不依赖云端转写服务时的兜底路径。"""
from __future__ import annotations

import sys
from typing import ClassVar

import pytest

from plugins.bot_unified_runtime.domains.media.ingest.transcribe import (
    CompositeASRProvider,
    LocalCommandASRProvider,
)


def test_local_command_reads_json_text() -> None:
    command = (
        f'"{sys.executable}" -c "import json; print(json.dumps({{\'text\': \'橘子四十二\'}}))"'
    )
    provider = LocalCommandASRProvider(command, timeout_seconds=10)
    assert provider.is_enabled() is True
    assert provider.generate(b"RIFF", "a.wav", timeout_seconds=10) == "橘子四十二"


def test_local_command_reads_plain_last_line() -> None:
    command = f'"{sys.executable}" -c "print(\'noise\'); print(\'hello world\')"'
    provider = LocalCommandASRProvider(command, timeout_seconds=10)
    assert provider.generate(b"RIFF", "a.wav", timeout_seconds=10) == "hello world"


def test_empty_command_is_disabled() -> None:
    assert LocalCommandASRProvider("", timeout_seconds=10).is_enabled() is False


def test_composite_falls_back_to_local() -> None:
    class Broken:
        last_attempts: ClassVar[list[str]] = ["broken:boom"]

        def is_enabled(self) -> bool:
            return True

        def generate(self, *args, **kwargs):
            raise RuntimeError("boom")

    local = LocalCommandASRProvider(
        f'"{sys.executable}" -c "print(\'fallback-ok\')"', timeout_seconds=10
    )
    composite = CompositeASRProvider([Broken(), local])
    assert composite.is_enabled() is True
    assert composite.generate(b"RIFF", "a.wav", timeout_seconds=10) == "fallback-ok"
    assert "local:success" in composite.last_attempts


def test_composite_all_failed_raises() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
        LLMProviderError,
    )

    class Broken:
        last_attempts: ClassVar[list[str]] = []

        def is_enabled(self) -> bool:
            return True

        def generate(self, *args, **kwargs):
            raise LLMProviderError("nope", error_kind="server")

    with pytest.raises(LLMProviderError):
        CompositeASRProvider([Broken()]).generate(b"RIFF", "a.wav", timeout_seconds=10)

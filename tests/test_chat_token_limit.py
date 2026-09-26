from __future__ import annotations

import inspect

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_chat_capability,
)


def test_normal_chat_token_defaults_are_64k() -> None:
    assert Config().bot_chat_max_tokens == 65538
    assert (
        inspect.signature(build_chat_capability)
        .parameters["fast_max_tokens"]
        .default
        == 65538
    )

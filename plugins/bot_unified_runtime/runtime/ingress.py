"""Single boundary for adapter event normalization."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class IngressGateway:
    """Normalize adapter events through one injected converter."""

    def __init__(self, normalizer: Callable[..., Any]) -> None:
        self._normalizer = normalizer

    def from_event(self, event: Any, *, bot_id: str = "unknown") -> Any:
        return self._normalizer(event, bot_id=bot_id)
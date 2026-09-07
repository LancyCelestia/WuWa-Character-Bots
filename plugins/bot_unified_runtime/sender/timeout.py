"""发送层单次请求硬超时的运行时取值。

调用方显式传入的正值与其取最小值（不得因配置变大绕过更紧的调用方预算）；
未传入时读运行时注入的 getter（支持 runtime 覆盖热更新），无 getter 时用默认值。
"""

from __future__ import annotations

import math
from collections.abc import Callable

DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_TIMEOUT_SECONDS = 600.0

_provider: Callable[[], float] | None = None


def set_transport_timeout_provider(provider: Callable[[], float] | None) -> None:
    global _provider
    _provider = provider


def resolve_transport_timeout(timeout_seconds: float | None = None) -> float:
    configured = DEFAULT_TIMEOUT_SECONDS
    if _provider is not None:
        try:
            configured = float(_provider())
        except (TypeError, ValueError, OSError, RuntimeError):
            configured = DEFAULT_TIMEOUT_SECONDS
    if math.isnan(configured) or not configured or configured <= 0:
        configured = DEFAULT_TIMEOUT_SECONDS
    configured = min(configured, MAX_TIMEOUT_SECONDS)
    if timeout_seconds is not None and float(timeout_seconds) > 0:
        return min(float(timeout_seconds), configured)
    return configured

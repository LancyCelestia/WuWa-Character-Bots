# 分库共装（split package，主人 2026-10-11 裁定①「组合可导入」）：生产单树时 no-op。
__path__ = __import__("pkgutil").extend_path(__path__, __name__)

from .injection import (
    InjectionAction,
    InjectionCheckInput,
    InjectionCheckResult,
    check_prompt_injection,
)

__all__ = [
    "InjectionAction",
    "InjectionCheckInput",
    "InjectionCheckResult",
    "check_prompt_injection",
]

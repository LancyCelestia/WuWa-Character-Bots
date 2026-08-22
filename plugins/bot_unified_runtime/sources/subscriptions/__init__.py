"""订阅平台 adapter 自动发现注册表。

同目录下所有 ``*_adapter.py`` 模块会通过 ``pkgutil`` 自动导入，
并读取模块级 ``ADAPTERS: list[SourceAdapter]`` 注册。当前目录尚无
平台 adapter，返回空注册表也能正常运行。
"""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable
from typing import Any

_REQUIRED_TARGET_KEYS = ("platform", "target_kind", "target_id", "target_name")


class SubscriptionRegistry:
    """按平台管理 SourceAdapter，并提供链接/目标统一解析。"""

    def __init__(self, adapters: Iterable[Any] | None = None) -> None:
        self._adapters: list[Any] = []
        for adapter in adapters or ():
            self.register(adapter)

    def register(self, adapter: Any) -> None:
        self._adapters.append(adapter)

    def list_adapters(self) -> list[Any]:
        return [*self._adapters]

    def find(self, platform: str) -> Any | None:
        return next(
            (
                adapter
                for adapter in self._adapters
                if getattr(adapter, "platform", "") == platform
            ),
            None,
        )

    def platforms(self) -> list[str]:
        seen: list[str] = []
        for adapter in self._adapters:
            platform = str(getattr(adapter, "platform", ""))
            if platform and platform not in seen:
                seen.append(platform)
        return seen

    def resolve_target(self, url: str) -> dict[str, str]:
        last_error: Exception | None = None
        for adapter in self._adapters:
            resolve = getattr(adapter, "resolve_target", None)
            if not callable(resolve):
                continue
            try:
                resolved = resolve(url)
            except ValueError as exc:
                last_error = exc
                continue
            if not isinstance(resolved, dict) or any(
                key not in resolved for key in _REQUIRED_TARGET_KEYS
            ):
                last_error = ValueError("adapter 返回的目标描述缺少必要字段")
                continue
            return {
                "platform": str(resolved["platform"]),
                "target_kind": str(resolved["target_kind"]),
                "target_id": str(resolved["target_id"]),
                "target_name": str(resolved["target_name"]),
            }
        raise ValueError(f"无法识别的订阅目标：{url}") from last_error


def _discover_adapter_modules():
    for module_info in pkgutil.iter_modules(__path__):
        if not module_info.name.endswith("_adapter"):
            continue
        yield importlib.import_module(f"{__name__}.{module_info.name}")


def build_subscription_registry() -> SubscriptionRegistry:
    """扫描本目录 ``*_adapter.py`` 并读取模块级 ``ADAPTERS``。"""
    registry = SubscriptionRegistry()
    for module in _discover_adapter_modules():
        for adapter in getattr(module, "ADAPTERS", []) or []:
            registry.register(adapter)
    return registry

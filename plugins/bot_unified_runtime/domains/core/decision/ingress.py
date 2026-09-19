"""IngressNormalizer（B2 阶段 0）：AdapterSource 插件点与 OneBot 先行实现。

规格：docs/design/central-decision-engine.md §2.3.1。阶段 0 只搭骨架与协议：
``OneBotSource`` 的归一化**委托既有** ``__init__._incoming_from_nonebot_event``
（等价复用，零行为变化），事件入口仍由旧 matcher 驱动；Telegram/Mail Source
与真实事件接线在迁移阶段 2/3 落地（本阶段不实现，也无需改 ``__init__.py``）。
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from plugins.bot_unified_runtime.domains.core.contracts import IncomingMessage

EventKind = Literal["message", "notice", "request", "meta"]


@runtime_checkable
class AdapterSource(Protocol):
    """适配器归一化插件点（规格 §2.3.1 接口草案）。"""

    def can_handle(self, event: Any) -> bool: ...

    def normalize(self, event: Any, bot_id: str = "unknown") -> IncomingMessage | None: ...

    def kind(self, event: Any) -> EventKind: ...


def _event_module(event: Any) -> str:
    return str(type(event).__module__).lower()


class OneBotSource:
    """OneBot V11（NapCat）来源：归一化委托既有实现，保持逐字节等价。"""

    def can_handle(self, event: Any) -> bool:
        module_name = _event_module(event)
        return ".telegram" not in module_name and ".mail" not in module_name

    def normalize(self, event: Any, bot_id: str = "unknown") -> IncomingMessage | None:
        from plugins.bot_unified_runtime import _incoming_from_nonebot_event

        return _incoming_from_nonebot_event(event, bot_id=bot_id)

    def kind(self, event: Any) -> EventKind:
        # OneBot：notice 事件带 notice_type（群上传/戳一戳/离线文件等）；
        # 其余按消息处理。
        if getattr(event, "notice_type", None) is not None:
            return "notice"
        if getattr(event, "request_type", None) is not None:
            return "request"
        return "message"


class TelegramSource:
    """Telegram 来源（阶段 2/3 迁移时内联搬移现 telegram 分支逻辑）。

    阶段 0 仅登记协议位：归一化同样委托既有 `_incoming_from_nonebot_event`
    的 telegram 分支，避免双实现漂移。
    """

    def can_handle(self, event: Any) -> bool:
        return ".telegram" in _event_module(event)

    def normalize(self, event: Any, bot_id: str = "unknown") -> IncomingMessage | None:
        from plugins.bot_unified_runtime import _incoming_from_nonebot_event

        return _incoming_from_nonebot_event(event, bot_id=bot_id)

    def kind(self, event: Any) -> EventKind:
        return "message"


DEFAULT_SOURCES: tuple[AdapterSource, ...] = (OneBotSource(), TelegramSource())

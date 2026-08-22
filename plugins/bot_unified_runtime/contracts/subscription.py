"""订阅系统契约模型与 SourceAdapter 协议。

统一订阅链路中的跨模块数据形状全部集中在此处：能力层、存储层、
watcher 与各平台 adapter 只依赖这些契约，彼此不耦合实现细节。
"""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import Field

from plugins.bot_unified_runtime.contracts.runtime import StrictBaseModel


class SubscriptionDestination(StrictBaseModel):
    """一个订阅的推送目的地：私聊或群聊。"""

    scope: str
    target_id: str


class SubscriptionSpec(StrictBaseModel):
    """一条订阅的完整描述，持久化在 subscriptions 表。"""

    id: str
    platform: str
    target_kind: str
    target_id: str
    target_name: str = ""
    destinations: list[SubscriptionDestination] = Field(default_factory=list)
    send_policy: str = "instant"
    digest_enabled: bool = False
    enabled: bool = True
    health_state: str = "healthy"
    failure_count: int = 0
    backoff_until: str | None = None
    created_by: str = ""
    created_at: str = ""


class SubscriptionCursor(StrictBaseModel):
    """平台 adapter 的增量抓取游标，按 spec_id 一一对应。"""

    spec_id: str
    last_item_id: str = ""
    last_timestamp: str = ""
    cursor_payload: dict[str, Any] = Field(default_factory=dict)
    failure_count: int = 0
    backoff_until: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None


class NormalizedSubscriptionItem(StrictBaseModel):
    """平台归一化后的订阅条目，用于推送或日报合成。"""

    item_id: str
    kind: str
    title: str
    url: str = ""
    author_name: str = ""
    cover_url: str = ""
    summary: str = ""
    stats: dict[str, Any] = Field(default_factory=dict)
    published_at: str = ""


class SourceFetchResult(StrictBaseModel):
    """一次 fetch_latest 的结果。"""

    items: list[NormalizedSubscriptionItem] = Field(default_factory=list)
    new_cursor: SubscriptionCursor | None = None
    health_state: str = "healthy"
    error: str = ""


class PushCandidate(StrictBaseModel):
    """watcher 产出、由调度器投递的推送候选。"""

    spec_id: str
    item: NormalizedSubscriptionItem
    reason: str


class SourceAdapter(Protocol):
    """平台订阅 adapter 协议。

    可选成员：``LIVE_POLL``（bool，默认 False，是否支持直播状态轮询）与
    ``fetch_live_statuses(specs, ctx)``（直播开播/下播候选检测）。可选能力
    通过 ``getattr`` 探测，未实现时 watcher 自动跳过。
    """

    platform: str
    target_kinds: tuple[str, ...]
    LIVE_POLL: bool = False

    def resolve_target(self, url: str) -> dict[str, str]:
        """把链接或 ``platform:kind:id`` 解析为平台目标描述。

        返回字典必须含 ``platform``、``target_kind``、``target_id``、
        ``target_name``；无法识别时 raise ValueError。
        """
        ...

    async def fetch_latest(
        self,
        spec: SubscriptionSpec,
        cursor: SubscriptionCursor | None,
        ctx: dict[str, Any],
    ) -> SourceFetchResult:
        """按游标增量拉取最新条目。``ctx`` 含 cookie_header 与 proxy。"""
        ...

    async def fetch_live_statuses(
        self,
        specs: list[SubscriptionSpec],
        ctx: dict[str, Any],
    ) -> list[PushCandidate]:
        """可选：批量检测直播状态，去重逻辑由 adapter 内部完成。"""
        return []

"""音乐榜单来源注册表；本地点歌榜由 MusicRequestStore 提供。"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from plugins.bot_unified_runtime.contracts.music import MusicChartSnapshot


class MusicChartSource(Protocol):
    source_id: str
    category: str

    async def fetch_snapshot(self, ctx: Any) -> MusicChartSnapshot:
        ...


class MusicChartRegistry:
    def __init__(self, sources: Iterable[MusicChartSource] | None = None) -> None:
        self._sources: dict[str, MusicChartSource] = {}
        for source in sources or ():
            self.register(source)

    def register(self, source: MusicChartSource) -> None:
        source_id = str(getattr(source, "source_id", "") or "").strip()
        if not source_id:
            raise ValueError("chart source_id must be non-blank")
        if source_id in self._sources:
            raise ValueError(f"duplicate chart source: {source_id}")
        self._sources[source_id] = source

    def list_sources(self, *, category: str | None = None) -> list[MusicChartSource]:
        sources = list(self._sources.values())
        if category is not None:
            sources = [source for source in sources if source.category == category]
        return sources

    async def refresh(self, source_id: str, ctx: Any) -> MusicChartSnapshot:
        source = self._sources.get(str(source_id))
        if source is None:
            raise KeyError(f"unknown chart source: {source_id}")
        snapshot = await source.fetch_snapshot(ctx)
        if not isinstance(snapshot, MusicChartSnapshot):
            raise TypeError("chart source must return MusicChartSnapshot")
        return snapshot

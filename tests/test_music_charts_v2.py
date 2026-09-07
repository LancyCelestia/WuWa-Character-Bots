from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts.music import MusicChartSnapshot
from plugins.bot_unified_runtime.sources.music_charts import (
    MusicChartRegistry,
    MusicChartSource,
)


class _Source(MusicChartSource):
    source_id = "netease-anime"
    category = "二次元"

    async def fetch_snapshot(self, ctx):
        return MusicChartSnapshot(
            snapshot_id="s1",
            source_id=self.source_id,
            platform="netease",
            category=self.category,
            source_type="curated_playlist",
            fetched_at=datetime.now(timezone.utc),
        )


def test_chart_registry_filters_categories_and_refreshes_sources() -> None:
    registry = MusicChartRegistry([_Source()])
    assert [source.source_id for source in registry.list_sources(category="二次元")] == [
        "netease-anime"
    ]
    snapshot = asyncio.run(registry.refresh("netease-anime", {"platform": "netease"}))
    assert snapshot.source_type == "curated_playlist"

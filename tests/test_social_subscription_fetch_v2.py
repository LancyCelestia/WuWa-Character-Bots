from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts.subscription import SubscriptionTarget
from plugins.bot_unified_runtime.sources.subscriptions.social_v2 import (
    TelegramSubscriptionAdapterV2,
    YouTubeSubscriptionAdapterV2,
)

_YOUTUBE_XML = """
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>v2</yt:videoId><title>新视频</title>
    <published>2026-08-30T10:00:00+00:00</published>
    <updated>2026-08-30T10:01:00+00:00</updated>
    <link rel="alternate" href="https://www.youtube.com/watch?v=v2" />
  </entry>
  <entry>
    <yt:videoId>v1</yt:videoId><title>旧视频</title>
    <published>2026-08-29T10:00:00+00:00</published>
    <updated>2026-08-29T10:01:00+00:00</updated>
    <link rel="alternate" href="https://www.youtube.com/watch?v=v1" />
  </entry>
</feed>
"""

_TELEGRAM_HTML = """
<div class="tgme_channel_info"><div class="tgme_channel_info_header_title">示例频道</div></div>
<div class="tgme_widget_message_wrap" data-post="example/11">
 <div class="tgme_widget_message_text">新消息</div>
 <time datetime="2026-08-30T10:00:00+00:00"></time>
 <span class="tgme_widget_message_views">1.2K</span>
</div>
<div class="tgme_widget_message_wrap" data-post="example/10" data-pinned="1">
 <div class="tgme_widget_message_text">置顶旧消息</div>
 <time datetime="2026-08-29T10:00:00+00:00"></time>
</div>
"""


def _target(platform: str, kind: str, key: str) -> SubscriptionTarget:
    now = datetime.now(timezone.utc)
    return SubscriptionTarget(
        id=f"{platform}:{kind}:{key}",
        platform=platform,
        target_kind=kind,
        target_key=key,
        created_at=now,
        updated_at=now,
    )


def test_youtube_atom_fetch_maps_and_filters_entries(monkeypatch) -> None:
    adapter = YouTubeSubscriptionAdapterV2()
    monkeypatch.setattr(adapter, "_fetch_text", lambda target, context: _YOUTUBE_XML)
    result = asyncio.run(adapter.fetch_incremental(_target("youtube", "channel", "UC1"), {}, {}))
    assert [item.item_id for item in result.items] == ["v2", "v1"]
    assert result.cursors[0].last_item_id == "v2"


def test_telegram_html_fetch_excludes_pinned_and_maps_views(monkeypatch) -> None:
    adapter = TelegramSubscriptionAdapterV2()
    monkeypatch.setattr(adapter, "_fetch_text", lambda target, context: _TELEGRAM_HTML)
    result = asyncio.run(adapter.fetch_incremental(_target("telegram", "public_channel", "example"), {}, {}))
    assert [item.item_id for item in result.items] == ["11"]
    assert result.items[0].source_payload["view_count"] == 1200

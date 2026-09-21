from __future__ import annotations

import asyncio
import gc
import threading
import warnings
from datetime import datetime, timezone

from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters import (
    bilibili_adapter,
    social_v2,
    xiaohongshu_adapter,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters.social_v2 import (
    BilibiliSubscriptionAdapterV2,
    TelegramSubscriptionAdapterV2,
    XiaohongshuSubscriptionAdapterV2,
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
<div class="tgme_widget_message_wrap" data-post="example/12">
 <div class="tgme_widget_message_text"><b>加粗开头</b>后续正文不能丢 <a href="https://example.com/x">链接</a>尾</div>
 <time datetime="2026-08-31T10:00:00+00:00"></time>
</div>
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
    assert [item.item_id for item in result.items] == ["12", "11"]
    # 内联闭合标签不再截断正文（FIX-1 同型缺陷在订阅路径的销项）。
    text12 = result.items[0].source_payload["text"]
    assert "加粗开头" in text12 and "后续正文不能丢" in text12 and "尾" in text12
    assert result.items[1].source_payload["view_count"] == 1200


# --------------------------------------------------------------------------
# legacy async 壳桥接（_run_legacy_coroutine）：协程零泄漏回归
# 背景：red50 A47/A60 实测 16 条 `coroutine 'XiaohongshuAdapter.fetch_latest'
# was never awaited`——asyncio.run 形态在残留 running-loop 状态的线程里
# 先构造协程再抛 RuntimeError，协程被弃 → GC 告警。
# --------------------------------------------------------------------------


def test_run_legacy_coroutine_awaits_and_returns_on_clean_thread() -> None:
    observed: list[str] = []

    async def leaf() -> str:
        observed.append("awaited")
        return "ok"

    def factory() -> object:
        return leaf()

    assert social_v2._run_legacy_coroutine(factory) == "ok"
    assert observed == ["awaited"]


def test_run_legacy_coroutine_propagates_coro_error_without_leaking() -> None:
    created: list[object] = []

    async def boom() -> None:
        raise ValueError("legacy 内部失败")

    def factory() -> object:
        coro = boom()
        created.append(coro)
        return coro

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            social_v2._run_legacy_coroutine(factory)
        except ValueError:
            pass
        # 若协程未被消费，GC 时会补发 never awaited 告警；强制扫一遍。
        gc.collect()
    assert len(created) == 1
    assert not any("never awaited" in str(w.message) for w in caught)


def test_run_legacy_coroutine_refuses_poisoned_thread_without_creating_coroutine() -> None:
    """中毒线程（残留 running-loop 状态）在协程构造之前就得上抛。"""
    from asyncio import events as _asyncio_events

    out: dict[str, object] = {"created": 0, "error": None}

    class _SentinelLoop:
        pass

    def poisoned_worker() -> None:
        def factory() -> object:
            out["created"] = out["created"] + 1  # type: ignore[operator]
            async def leaf() -> None:
                return None
            return leaf()

        try:
            # 模拟 playwright sync greenlet 残留：线程本地 running-loop 非空。
            _asyncio_events._set_running_loop(_SentinelLoop())
            try:
                social_v2._run_legacy_coroutine(factory)
            except RuntimeError as exc:
                out["error"] = str(exc)
        finally:
            _asyncio_events._set_running_loop(None)

    thread = threading.Thread(target=poisoned_worker)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert out["error"] is not None and "running-loop" in str(out["error"])
    assert out["created"] == 0  # 协程从未构造 → 零泄漏。


class _NoopLegacy:
    def __init__(self) -> None:
        pass


def test_xhs_and_bilibili_fetch_degrade_on_bridged_runtime_error(monkeypatch) -> None:
    """桥接层 RuntimeError（含中毒线程拒绝）映射为结构化 degraded，不再裸抛。"""
    monkeypatch.setattr(xiaohongshu_adapter, "XiaohongshuAdapter", _NoopLegacy)
    monkeypatch.setattr(bilibili_adapter, "BilibiliAdapter", _NoopLegacy)

    def poisoned_bridge(factory) -> object:
        raise RuntimeError("legacy async 壳不能在残留 running-loop 状态的线程里桥接")

    monkeypatch.setattr(social_v2, "_run_legacy_coroutine", poisoned_bridge)

    for adapter in (
        XiaohongshuSubscriptionAdapterV2(),
        BilibiliSubscriptionAdapterV2(),
    ):
        result = asyncio.run(
            adapter.fetch_incremental(_target(adapter.platform, "creator", "u1"), {}, {})
        )
        assert result.items == []
        assert result.health_state == "degraded"
        assert result.error_code == "network_error"
        assert result.retryable is True

"""G-SUB-LIVE A4：YouTube live 与小红书 column/live 订阅 kind 的离线回归。

全部网络与 Playwright 抓取均被 mock，不做任何真实请求。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    SourceFetchResult,
    SubscriptionCursor,
    SubscriptionCursorV2,
    SubscriptionFetchResult,
    SubscriptionSpec,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters import (
    social_v2,
    xiaohongshu_adapter,
)
from plugins.bot_unified_runtime.domains.subscribe.adapters.social_v2 import (
    XiaohongshuSubscriptionAdapterV2,
    YouTubeSubscriptionAdapterV2,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError

_NOW = datetime.now(timezone.utc)


def _target(platform: str, kind: str, key: str) -> SubscriptionTarget:
    return SubscriptionTarget(
        id=f"{platform}:{kind}:{key}",
        platform=platform,
        target_kind=kind,
        target_key=key,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _cursor(target: SubscriptionTarget, stream: str, last_item_id: str) -> SubscriptionCursorV2:
    return SubscriptionCursorV2(
        target_id=target.id,
        stream=stream,
        last_item_id=last_item_id,
        updated_at=_NOW,
    )


# --------------------------------------------------------------------------
# kind 注册与目标解析
# --------------------------------------------------------------------------


def test_new_kinds_are_registered() -> None:
    assert "live" in YouTubeSubscriptionAdapterV2().target_kinds
    xhs = XiaohongshuSubscriptionAdapterV2()
    assert {"creator", "column", "live"} <= set(xhs.target_kinds)


@pytest.mark.parametrize(
    ("raw", "kind", "key"),
    [
        ("youtube:live:UCabc123_-", "live", "UCabc123_-"),
        ("youtube:live:@handle", "live", "@handle"),
        ("https://www.youtube.com/channel/UCxyz/live", "live", "UCxyz"),
        ("xiaohongshu:column:u1", "column", "u1"),
        ("xiaohongshu:live:u1", "live", "u1"),
        ("https://www.xiaohongshu.com/user/profile/u9", "creator", "u9"),
        ("xiaohongshu:creator:u2", "creator", "u2"),
    ],
)
def test_resolve_new_targets(raw: str, kind: str, key: str) -> None:
    adapter = (
        XiaohongshuSubscriptionAdapterV2()
        if raw.startswith(("xiaohongshu", "https://www.xiaohongshu"))
        else YouTubeSubscriptionAdapterV2()
    )
    target = asyncio.run(adapter.resolve_target(raw, {}))
    assert target.target_kind == kind
    assert target.target_key == key


def test_resolve_handle_live_url_uses_real_channel_id(monkeypatch) -> None:
    monkeypatch.setattr(
        social_v2,
        "http_get_text",
        lambda url, **kwargs: (url, '"externalId":"UChandle9"'),
    )
    target = asyncio.run(
        YouTubeSubscriptionAdapterV2().resolve_target(
            "https://www.youtube.com/@someone/live", {}
        )
    )
    assert target.target_kind == "live"
    assert target.target_key == "UChandle9"


def test_resolve_plain_channel_link_still_maps_to_channel_kind() -> None:
    # 回归：/live 匹配规则前移不得吞掉普通频道链接。
    target = asyncio.run(
        YouTubeSubscriptionAdapterV2().resolve_target(
            "https://www.youtube.com/channel/UCplain/videos", {}
        )
    )
    assert target.target_kind == "channel"
    assert target.target_key == "UCplain"


# --------------------------------------------------------------------------
# YouTube live 拉取：在播 / 不在播 / 去重 / 降级
# --------------------------------------------------------------------------


def _mock_yt_page(monkeypatch, final_url: str, body: str) -> None:
    def fake_get_text(url: str, **kwargs):
        assert "/live" in url
        return final_url, body

    monkeypatch.setattr(social_v2, "http_get_text", fake_get_text)


def test_youtube_live_redirect_announces_once(monkeypatch) -> None:
    _mock_yt_page(
        monkeypatch,
        "https://www.youtube.com/watch?v=aLivE123x",
        '<meta property="og:title" content="正在直播">',
    )
    adapter = YouTubeSubscriptionAdapterV2()
    target = _target("youtube", "live", "UCabc123")
    result = asyncio.run(adapter.fetch_incremental(target, {}, {}))
    assert [item.item_id for item in result.items] == ["aLivE123x"]
    assert result.items[0].item_kind == "live"
    assert result.items[0].url.endswith("watch?v=aLivE123x")
    assert result.items[0].source_payload["title"] == "正在直播"
    assert result.cursors[0].stream == "live"
    assert result.cursors[0].last_item_id == "aLivE123x"
    assert result.health_state == "healthy"

    # 第二轮同一场直播：cursor 去重，不再产出。
    result = asyncio.run(
        adapter.fetch_incremental(
            target, {"live": result.cursors[0]}, {}
        )
    )
    assert result.items == []
    assert result.health_state == "healthy"


def test_youtube_live_new_stream_reannounces(monkeypatch) -> None:
    _mock_yt_page(
        monkeypatch,
        "https://www.youtube.com/watch?v=nExtstr22",
        "<html></html>",
    )
    adapter = YouTubeSubscriptionAdapterV2()
    target = _target("youtube", "live", "UCabc123")
    previous = _cursor(target, "live", "oLdStream1")
    result = asyncio.run(adapter.fetch_incremental(target, {"live": previous}, {}))
    assert [item.item_id for item in result.items] == ["nExtstr22"]
    assert result.cursors[0].last_item_id == "nExtstr22"


def test_youtube_live_offline_is_silent(monkeypatch) -> None:
    _mock_yt_page(
        monkeypatch,
        "https://www.youtube.com/channel/UCabc123/live",
        '<html><meta property="og:url" content="https://www.youtube.com/channel/UCabc123"></html>',
    )
    adapter = YouTubeSubscriptionAdapterV2()
    target = _target("youtube", "live", "UCabc123")
    previous = _cursor(target, "live", "oLdStream1")
    result = asyncio.run(adapter.fetch_incremental(target, {"live": previous}, {}))
    assert result.items == []
    assert result.health_state == "healthy"
    assert result.cursors == []  # 不动 cursor，保留上次播报记录。


def test_youtube_live_body_islive_marker_fallback(monkeypatch) -> None:
    _mock_yt_page(
        monkeypatch,
        "https://www.youtube.com/channel/UCabc123/live",
        '<script>"videoId":"b0dyVid99","isLive":true</script>',
    )
    result = asyncio.run(
        YouTubeSubscriptionAdapterV2().fetch_incremental(
            _target("youtube", "live", "UCabc123"), {}, {}
        )
    )
    assert [item.item_id for item in result.items] == ["b0dyVid99"]


def test_youtube_live_handle_key_probe_url(monkeypatch) -> None:
    seen_urls: list[str] = []

    def fake_get_text(url: str, **kwargs):
        seen_urls.append(url)
        return "https://www.youtube.com/@handle/live", "<html></html>"

    monkeypatch.setattr(social_v2, "http_get_text", fake_get_text)
    result = asyncio.run(
        YouTubeSubscriptionAdapterV2().fetch_incremental(
            _target("youtube", "live", "@handle"), {}, {}
        )
    )
    assert seen_urls == ["https://www.youtube.com/@handle/live"]
    assert result.items == []
    assert result.health_state == "healthy"


def test_youtube_live_http_403_degrades_to_auth_required(monkeypatch) -> None:
    def boom(url: str, **kwargs):
        raise ParseHttpError("GET failed", status_code=403)

    monkeypatch.setattr(social_v2, "http_get_text", boom)
    result = asyncio.run(
        YouTubeSubscriptionAdapterV2().fetch_incremental(
            _target("youtube", "live", "UCabc123"), {}, {}
        )
    )
    assert result.health_state == "auth_required"
    assert result.error_code == "auth_required"
    assert result.retryable is False


def test_youtube_live_network_error_degrades(monkeypatch) -> None:
    def boom(url: str, **kwargs):
        raise ParseHttpError("GET failed", status_code=500)

    monkeypatch.setattr(social_v2, "http_get_text", boom)
    result = asyncio.run(
        YouTubeSubscriptionAdapterV2().fetch_incremental(
            _target("youtube", "live", "UCabc123"), {}, {}
        )
    )
    assert result.health_state == "degraded"
    assert result.retryable is True


# --------------------------------------------------------------------------
# 小红书 column：复用 legacy 拉取链路 + 游标切分前过滤 video
# --------------------------------------------------------------------------


_XHS_NOTES = [
    {"note_id": "v2", "type": "video", "display_title": "新视频"},
    {"note_id": "c1", "type": "normal", "display_title": "新图文"},
    {"note_id": "v1", "type": "video", "display_title": "旧视频"},
    {"note_id": "c0", "type": "normal", "display_title": "旧图文"},
]


class _FakeXhsBackend:
    available = True

    def __init__(self, payload) -> None:
        self.payload = payload

    def capture_json(self, url, cookies=None, json_filter=None, timeout_ms=None):
        return self.payload

    def fetch_html(self, url, cookies=None, timeout_ms=None):
        return url, "<html></html>"


def _xhs_spec(kind: str) -> SubscriptionSpec:
    return SubscriptionSpec(
        id=f"xiaohongshu:{kind}:u1",
        platform="xiaohongshu",
        target_kind=kind,
        target_id="u1",
        target_name="u1",
        created_by="test",
    )


def _xhs_legacy(payload, kind: str, last_item_id: str = ""):
    legacy = xiaohongshu_adapter.XiaohongshuAdapter(backend=_FakeXhsBackend(payload))
    cursor = SubscriptionCursor(
        spec_id=f"xiaohongshu:{kind}:u1",
        last_item_id=last_item_id,
    ) if last_item_id else None
    return legacy.fetch_latest(_xhs_spec(kind), cursor, {})


def test_xhs_column_increment_skips_videos_and_keeps_anchor() -> None:
    # 游标在 c0：新图文 c1 应产出；夹在其上的新视频 v2 不产出也不顶走锚点。
    result = asyncio.run(_xhs_legacy({"data": {"notes": _XHS_NOTES}}, "column", "c0"))
    assert [item.item_id for item in result.items] == ["c1"]
    assert result.items[0].kind == "note"
    assert result.new_cursor is not None
    assert result.new_cursor.last_item_id == "c1"
    assert result.health_state == "healthy"


def test_xhs_column_first_fetch_returns_only_notes() -> None:
    result = asyncio.run(_xhs_legacy({"data": {"notes": _XHS_NOTES}}, "column"))
    assert [item.item_id for item in result.items] == ["c1", "c0"]
    assert result.new_cursor.last_item_id == "c1"


def test_xhs_column_all_video_new_content_stays_silent() -> None:
    payload = {"data": {"notes": [{"note_id": "v3", "type": "video", "display_title": "x"}]}}
    result = asyncio.run(_xhs_legacy(payload, "column", "v3"))
    assert result.items == []
    assert result.health_state == "healthy"


def test_xhs_creator_kind_regression_keeps_videos() -> None:
    result = asyncio.run(_xhs_legacy({"data": {"notes": _XHS_NOTES}}, "creator", "c0"))
    assert [item.item_id for item in result.items] == ["v2", "c1", "v1"]
    assert result.new_cursor.last_item_id == "v2"


def test_xhs_v2_routes_column_kind_into_legacy(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class _StubLegacy:
        def __init__(self) -> None:
            pass

        async def fetch_latest(self, spec, cursor, ctx):
            captured["kind"] = str(spec.target_kind)
            return SourceFetchResult(items=[], health_state="healthy", error="")

    monkeypatch.setattr(xiaohongshu_adapter, "XiaohongshuAdapter", _StubLegacy)
    result = asyncio.run(
        XiaohongshuSubscriptionAdapterV2().fetch_incremental(
            _target("xiaohongshu", "column", "u1"), {}, {}
        )
    )
    assert captured["kind"] == "column"
    assert result.health_state == "healthy"


# --------------------------------------------------------------------------
# 小红书 live：仅注册 kind，探测受限 → 结构化降级
# --------------------------------------------------------------------------


def test_xhs_live_fetch_degrades_without_fabricating(monkeypatch) -> None:
    def fail(*args, **kwargs):  # 确认降级路径不做任何网络请求。
        raise AssertionError("xiaohongshu live 不应发起网络探测")

    monkeypatch.setattr(social_v2, "http_get_text", fail)
    monkeypatch.setattr(
        xiaohongshu_adapter,
        "XiaohongshuAdapter",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("不应构造 legacy 适配器")),
    )
    result = asyncio.run(
        XiaohongshuSubscriptionAdapterV2().fetch_incremental(
            _target("xiaohongshu", "live", "u1"), {}, {}
        )
    )
    assert isinstance(result, SubscriptionFetchResult)
    assert result.items == []
    assert result.health_state == "degraded"
    assert result.error_code == "live_probe_unavailable"
    assert result.retryable is True

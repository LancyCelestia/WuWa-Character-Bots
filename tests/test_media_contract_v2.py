from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.contracts.media import (
    ContentIdentity,
    ContentMetadata,
    CreatorMetadata,
    EngagementMetrics,
    MediaAsset,
    ParsedContent,
    SourceProvenance,
    build_parsed_content,
)


def test_parsed_content_separates_creator_and_content_metrics() -> None:
    item = build_parsed_content(
        identity=ContentIdentity(
            platform="youtube",
            item_id="v1",
            item_kind="video",
            canonical_url="https://youtube.com/watch?v=v1",
        ),
        content=ContentMetadata(title="标题", body="正文"),
        creator=CreatorMetadata(
            platform_creator_id="c1",
            name="作者",
            follower_count=10,
            post_count=4,
        ),
        engagement=EngagementMetrics(view_count=100, like_count=7),
        media=[MediaAsset(asset_type="image", url="https://img/v1.jpg")],
        provenance=SourceProvenance(
            parse_depth="deep",
            auth_mode="anonymous",
            fetched_at=datetime.now(timezone.utc),
            source_endpoints=["youtube.oembed"],
        ),
    )
    assert item.creator is not None
    assert item.creator.post_count == 4
    assert item.engagement.view_count == 100


def test_minimal_content_preserves_unknown_as_none_with_limitation() -> None:
    item = ParsedContent.minimal(
        platform="instagram",
        item_id="p1",
        item_kind="post",
        canonical_url="https://instagram.com/p/p1",
        title="blocked",
        limitations={"content.body": "blocked"},
    )
    assert item.creator is None
    assert item.engagement.like_count is None
    assert item.provenance.limitations["content.body"] == "blocked"


@pytest.mark.parametrize("header", ["Cookie", "Authorization", "X-Auth-Token"])
def test_media_asset_rejects_sensitive_access_headers(header: str) -> None:
    with pytest.raises(ValidationError):
        MediaAsset(asset_type="image", access_headers={header: "secret"})


def test_parsed_content_accepts_parser_fields_and_builds_nested_metadata() -> None:
    item = build_parsed_content(
        platform="weibo",
        item_id="status-1",
        item_kind="post",
        title="标题",
        author_name="作者",
        summary="正文",
        canonical_url="https://weibo.com/status-1",
        stats={"点赞": 3},
        parse_depth="deep",
    )
    assert item.identity is not None
    assert item.identity.platform == "weibo"
    assert item.content.title == "标题"
    assert item.content.summary == "正文"
    assert item.creator is not None
    assert item.creator.name == "作者"
    assert item.engagement.like_count == 3


def test_parsed_content_has_no_flat_projection_fields() -> None:
    item = build_parsed_content(
        platform="bilibili",
        item_id="BV1",
        item_kind="video",
        title="t",
        canonical_url="https://www.bilibili.com/video/BV1",
    )
    for field in (
        "platform", "item_id", "item_kind", "title", "author_name", "summary",
        "cover_url", "audio_url", "canonical_url", "stats", "parse_depth",
        "page_type", "badge", "detail",
    ):
        assert not hasattr(item, field), f"flat projection field {field} must be removed"
    assert item.identity is not None
    assert item.identity.platform == "bilibili"
    assert item.content is not None
    assert item.content.title == "t"

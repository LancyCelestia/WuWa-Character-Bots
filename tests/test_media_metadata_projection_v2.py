from __future__ import annotations

from plugins.bot_unified_runtime.contracts.media import (
    build_parsed_content,
)


def test_projection_accepts_cross_platform_author_and_media_aliases() -> None:
    item = build_parsed_content(
        platform="youtube",
        item_id="v-1",
        item_kind="video",
        title="视频标题",
        summary="简介",
        canonical_url="https://youtube.com/watch?v=v-1",
        stats={
            "view_count": "1200",
            "like_count": 18,
            "comment_count": 3,
            "发布时间": "2026-08-30 10:00",
        },
        detail={
            "body": "完整正文",
            "published_at": "2026-08-30T10:00:00+00:00",
            "author": {
                "id": "channel-1",
                "avatar_url": "https://img/avatar.jpg",
                "description": "频道简介",
                "followers_count": "42",
                "following_count": 4,
                "statuses_count": 9,
                "verified_reason": "官方频道",
            },
            "media": [
                {"type": "image", "url": "https://img/thumb.jpg", "width": 1280},
                {
                    "type": "video",
                    "url": "https://cdn/video.mp4",
                    "thumbnail_url": "https://img/video.jpg",
                    "duration": 12,
                    "height": 720,
                },
            ],
        },
    )

    assert item.content is not None
    assert item.content.body == "完整正文"
    assert item.content.published_at is not None
    assert item.creator is not None
    assert item.creator.platform_creator_id == "channel-1"
    assert item.creator.avatar_url == "https://img/avatar.jpg"
    assert item.creator.bio == "频道简介"
    assert item.creator.follower_count == 42
    assert item.creator.following_count == 4
    assert item.creator.post_count == 9
    assert item.creator.verification is not None
    assert item.creator.verification.label == "官方频道"
    assert [asset.asset_type for asset in item.media] == ["image", "video"]
    assert item.media[1].preview_url == "https://img/video.jpg"
    assert item.media[1].duration_ms == 12000
    assert item.engagement.view_count == 1200
    assert item.engagement.like_count == 18
    assert item.engagement.comment_count == 3


def test_projection_promotes_top_level_parser_fields_into_v2() -> None:
    item = build_parsed_content(
        platform="telegram",
        item_id="11",
        item_kind="post",
        title="频道消息",
        summary="消息正文",
        cover_url="https://img/message.jpg",
        audio_url="https://cdn/message.ogg",
        canonical_url="https://t.me/example/11",
        stats={
            "爱心": "1.2K",
            "评论": 3,
            "粉丝": "4.5万",
            "帖子数": 20,
            "发布时间": "2026-08-30 10:00",
        },
        detail={"author": {"id": "channel-1", "name": "示例频道"}},
    )

    assert item.content is not None
    assert item.content.body == "消息正文"
    assert item.content.published_at is not None
    assert item.creator is not None
    assert item.creator.follower_count == 45000
    assert item.creator.post_count == 20
    assert [asset.asset_type for asset in item.media] == ["image", "audio"]
    assert item.media[0].url == "https://img/message.jpg"
    assert item.media[1].url == "https://cdn/message.ogg"
    assert item.engagement.heart_count == 1200
    assert item.engagement.comment_count == 3


def test_projection_builds_creator_media_and_provenance_limits() -> None:
    item = build_parsed_content(
        platform="twitter",
        item_id="42",
        item_kind="tweet",
        title="一条推文",
        author_name="Alice",
        canonical_url="https://x.com/alice/status/42",
        stats={"浏览": 100, "点赞": 5, "评论": 2, "转发": 3},
        detail={
            "author": {
                "uuid": "u-1",
                "handle": "alice",
                "avatar": "https://cdn.example/avatar.jpg",
                "signature": "简介",
                "fans": 12,
                "following": 4,
                "posts": 20,
                "verified": True,
            },
            "images": [
                "https://cdn.example/1.jpg",
                "https://cdn.example/2.jpg",
            ],
            "video": {"duration": 12, "width": 640, "height": 360},
        },
    )

    assert item.creator is not None
    assert item.creator.platform_creator_id == "u-1"
    assert item.creator.handle == "alice"
    assert item.creator.follower_count == 12
    assert item.creator.following_count == 4
    assert item.creator.post_count == 20
    assert item.creator.verification is not None
    assert item.creator.verification.verified is True
    assert [asset.url for asset in item.media[:2]] == [
        "https://cdn.example/1.jpg",
        "https://cdn.example/2.jpg",
    ]
    assert item.engagement.view_count == 100
    assert item.engagement.repost_count == 3
    assert item.provenance is not None
    assert item.provenance.limitations == {}


def test_projection_parses_twitter_weibo_dates_and_engagement_aliases() -> None:
    item = build_parsed_content(
        platform="twitter",
        item_id="101",
        item_kind="tweet",
        title="t",
        summary="",
        canonical_url="https://x.com/a/status/101",
        stats={
            "bookmark_count": 5,
            "bookmarkCount": 6,
            "quote_count": 7,
            "playCount": "1.2万",
        },
        detail={"published_at": "Wed Oct 10 20:19:24 +0000 2018"},
    )
    assert item.content is not None
    assert item.content.published_at is not None
    assert item.content.published_at.utcoffset().total_seconds() == 0
    assert item.content.published_at.year == 2018
    assert item.engagement.bookmark_count == 5
    assert item.engagement.quote_count == 7
    assert item.engagement.play_count == 12000


def test_projection_dedupes_media_urls_keeping_order() -> None:
    item = build_parsed_content(
        platform="weibo",
        item_id="w-1",
        item_kind="post",
        title="t",
        summary="",
        canonical_url="https://weibo.com/x/w-1",
        detail={
            "media": [
                {"type": "image", "url": "https://img/a.jpg"},
                {"type": "image", "url": "https://img/b.jpg"},
                {"type": "image", "url": "https://img/a.jpg"},
                {"type": "image", "url": "https://img/c.jpg"},
                {"type": "image"},
            ]
        },
    )
    assert [asset.url for asset in item.media] == [
        "https://img/a.jpg",
        "https://img/b.jpg",
        "https://img/c.jpg",
        None,
    ]


def test_projection_accepts_unix_millis_published_at() -> None:
    item = build_parsed_content(
        platform="weibo",
        item_id="w-2",
        item_kind="post",
        title="t",
        summary="",
        canonical_url="https://weibo.com/x/w-2",
        detail={"published_at": 1756540800000},
    )
    assert item.content is not None
    assert item.content.published_at is not None
    assert item.content.published_at.timestamp() == 1756540800.0

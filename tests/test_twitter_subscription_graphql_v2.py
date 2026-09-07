from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts import (
    SubscriptionCursorV2,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError
from plugins.bot_unified_runtime.sources.subscriptions.social_v2 import (
    TwitterGraphQLClient,
    TwitterSubscriptionAdapterV2,
)

_PAYLOAD = {
    "data": {
        "user": {
            "result": {
                "timeline_v2": {
                    "timeline": {
                        "instructions": [
                            {
                                "type": "TimelineAddEntries",
                                "entries": [
                                    {
                                        "entryId": "tweet-101",
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": {
                                                        "rest_id": "101",
                                                        "legacy": {
                                                            "full_text": "最新推文",
                                                            "created_at": "Sat Aug 30 10:00:00 +0000 2026",
                                                            "favorite_count": 7,
                                                            "retweet_count": 3,
                                                            "reply_count": 2,
                                                            "quote_count": 1,
                                                        },
                                                        "core": {
                                                            "user_results": {
                                                                "result": {
                                                                    "rest_id": "9",
                                                                    "legacy": {
                                                                        "name": "Alice",
                                                                        "screen_name": "alice",
                                                                    },
                                                                }
                                                            }
                                                        },
                                                    }
                                                }
                                            }
                                        },
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        }
    }
}


def test_twitter_graphql_fixture_maps_tweet_and_cursor() -> None:
    adapter = TwitterSubscriptionAdapterV2()
    result = adapter.parse_timeline_payload(
        _PAYLOAD,
        SubscriptionTarget(
            id="twitter:creator:alice",
            platform="twitter",
            target_kind="creator",
            target_key="alice",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        last_item_id="100",
    )
    assert [item.item_id for item in result.items] == ["101"]
    assert result.items[0].source_payload["text"] == "最新推文"
    assert result.items[0].source_payload["like_count"] == 7
    assert result.cursors[0].last_item_id == "101"


def test_twitter_without_authorized_graphql_context_is_auth_required() -> None:
    target = SubscriptionTarget(
        id="twitter:creator:alice",
        platform="twitter",
        target_kind="creator",
        target_key="alice",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    result = asyncio.run(
        TwitterSubscriptionAdapterV2().fetch_incremental(target, {}, {})
    )
    assert result.error_code == "auth_required"


def test_default_twitter_graphql_client_resolves_user_fetches_timeline_and_cursor() -> None:
    target = SubscriptionTarget(
        id="twitter:creator:alice",
        platform="twitter",
        target_kind="creator",
        target_key="alice",
        target_payload={"raw": "https://x.com/alice"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    calls: list[tuple[str, dict, dict]] = []
    user_payload = {"data": {"user": {"result": {"rest_id": "9"}}}}
    timeline_payload = {
        "data": {
            "user": {
                "result": {
                    "timeline_v2": {
                        "timeline": {
                            "instructions": [
                                {
                                    "type": "TimelineAddEntries",
                                    "entries": [
                                        {
                                            "entryId": "tweet-101",
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {
                                                        "result": {
                                                            "rest_id": "101",
                                                            "legacy": {
                                                                "full_text": "最新推文",
                                                                "favorite_count": 7,
                                                            },
                                                        }
                                                    }
                                                }
                                            },
                                        },
                                        {
                                            "entryId": "cursor-bottom-101",
                                            "content": {
                                                "entryType": "TimelineTimelineCursor",
                                                "cursorType": "Bottom",
                                                "value": "cursor-101",
                                            },
                                        },
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        }
    }

    def get_json(url: str, **kwargs):
        calls.append((url, kwargs.get("cookie", ""), kwargs.get("extra_headers", {})))
        return user_payload if "user-query" in url else timeline_payload

    client = TwitterGraphQLClient(json_getter=get_json)
    result = client.fetch_incremental(
        target,
        {},
        {
            "cookie_header": "auth_token=a; ct0=b",
            "proxy": "http://proxy.invalid:8080",
            "twitter_bearer_token": "bearer",
            "twitter_query_ids": {
                "UserByScreenName": "user-query",
                "UserTweets": "tweets-query",
            },
        },
    )

    assert [item.item_id for item in result.items] == ["101"]
    assert result.cursors[0].cursor_payload["next_cursor"] == "cursor-101"
    assert result.cursors[0].cursor_payload["user_id"] == "9"
    assert target.target_payload["rest_id"] == "9"
    assert len(calls) == 2
    assert all(cookie == "auth_token=a; ct0=b" for _, cookie, _ in calls)
    assert calls[0][2]["Authorization"] == "Bearer bearer"
    assert calls[0][2]["x-csrf-token"] == "b"


def test_default_twitter_graphql_client_discovers_rotated_bundle_credentials() -> None:
    target = SubscriptionTarget(
        id="twitter:creator:alice",
        platform="twitter",
        target_kind="creator",
        target_key="alice",
        target_payload={"raw": "https://x.com/alice"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    homepage = '<script src="/assets/app.js"></script>'
    bundle = (
        'var bearer="AAAAweb-token_12345678901234567890";'
        'queryId:"user-query",operationName:"UserByScreenName";'
        'queryId:"tweets-query",operationName:"UserTweets";'
    )

    def get_text(url: str, **kwargs):
        return url, homepage if url.endswith("x.com/") else bundle

    def get_json(url: str, **kwargs):
        if "user-query" in url:
            return {"data": {"user": {"result": {"rest_id": "9"}}}}
        return _PAYLOAD

    result = TwitterGraphQLClient(
        json_getter=get_json,
        text_getter=get_text,
    ).fetch_incremental(
        target,
        {},
        {"cookie_header": "auth_token=a; ct0=b"},
    )
    assert [item.item_id for item in result.items] == ["101"]


def test_twitter_graphql_client_reuses_user_id_from_cursor_without_second_lookup() -> None:
    target = SubscriptionTarget(
        id="twitter:creator:alice",
        platform="twitter",
        target_kind="creator",
        target_key="alice",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    calls: list[str] = []

    def get_json(url: str, **kwargs):
        calls.append(url)
        if "user-query" in url:
            return {"data": {"user": {"result": {"rest_id": "9"}}}}
        return _PAYLOAD

    cursor_result = TwitterGraphQLClient(json_getter=get_json).fetch_incremental(
        target,
        {},
        {
            "cookie_header": "auth_token=a; ct0=b",
            "twitter_bearer_token": "bearer",
            "twitter_query_ids": {
                "UserByScreenName": "user-query",
                "UserTweets": "tweets-query",
            },
        },
    )
    assert len(calls) == 2
    calls.clear()
    reloaded_target = SubscriptionTarget(
        id=target.id,
        platform=target.platform,
        target_kind=target.target_kind,
        target_key=target.target_key,
        target_payload={"raw": "https://x.com/alice"},
        created_at=target.created_at,
        updated_at=target.updated_at,
    )
    TwitterGraphQLClient(json_getter=get_json).fetch_incremental(
        reloaded_target,
        {"tweets": cursor_result.cursors[0]},
        {
            "cookie_header": "auth_token=a; ct0=b",
            "twitter_bearer_token": "bearer",
            "twitter_query_ids": {
                "UserByScreenName": "user-query",
                "UserTweets": "tweets-query",
            },
        },
    )
    assert len(calls) == 1
    assert "tweets-query" in calls[0]


def test_twitter_graphql_client_maps_http_status_to_retryable_result() -> None:
    target = SubscriptionTarget(
        id="twitter:creator:alice",
        platform="twitter",
        target_kind="creator",
        target_key="alice",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    def get_json(url: str, **kwargs):
        raise ParseHttpError(
            "Twitter request failed", status_code=429, retry_after_seconds=17
        )

    result = TwitterGraphQLClient(json_getter=get_json).fetch_incremental(
        target,
        {},
        {
            "cookie_header": "auth_token=a; ct0=b",
            "twitter_bearer_token": "bearer",
            "twitter_query_ids": {
                "UserByScreenName": "user-query",
                "UserTweets": "tweets-query",
            },
        },
    )
    assert result.error_code == "rate_limited"
    assert result.retryable is True
    assert result.retry_after_seconds == 17


def test_default_twitter_graphql_client_maps_graphql_errors_to_upstream_changed() -> None:
    target = SubscriptionTarget(
        id="twitter:creator:alice",
        platform="twitter",
        target_kind="creator",
        target_key="alice",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    def get_json(url: str, **kwargs):
        if "user-query" in url:
            return {"data": {"user": {"result": {"rest_id": "9"}}}}
        return {"errors": [{"message": "Field UserTweets was removed"}]}

    result = TwitterGraphQLClient(json_getter=get_json).fetch_incremental(
        target,
        {},
        {
            "cookie_header": "auth_token=a; ct0=b",
            "twitter_bearer_token": "bearer",
            "twitter_query_ids": {
                "UserByScreenName": "user-query",
                "UserTweets": "tweets-query",
            },
        },
    )
    assert result.error_code == "upstream_changed"
    assert result.retryable is False


def test_default_twitter_graphql_client_maps_rate_limit_to_retryable_result() -> None:
    target = SubscriptionTarget(
        id="twitter:creator:alice",
        platform="twitter",
        target_kind="creator",
        target_key="alice",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    def get_json(url: str, **kwargs):
        raise RuntimeError("HTTP 429 Too Many Requests")

    result = TwitterGraphQLClient(json_getter=get_json).fetch_incremental(
        target,
        {},
        {
            "cookie_header": "auth_token=a; ct0=b",
            "twitter_bearer_token": "bearer",
            "twitter_query_ids": {
                "UserByScreenName": "user-query",
                "UserTweets": "tweets-query",
            },
        },
    )
    assert result.error_code == "rate_limited"
    assert result.retryable is True


_AUTHED_CONTEXT = {
    "cookie_header": "auth_token=a; ct0=b",
    "twitter_bearer_token": "bearer",
    "twitter_query_ids": {
        "UserByScreenName": "user-query",
        "UserTweets": "tweets-query",
    },
}


def _alice_target(**payload_extra: object) -> SubscriptionTarget:
    return SubscriptionTarget(
        id="twitter:creator:alice",
        platform="twitter",
        target_kind="creator",
        target_key="alice",
        target_payload={"raw": "https://x.com/alice", **payload_extra},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _tweets_cursor(last_item_id: str, **payload: object) -> SubscriptionCursorV2:
    return SubscriptionCursorV2(
        target_id="twitter:creator:alice",
        stream="tweets",
        last_item_id=last_item_id,
        cursor_payload=dict(payload),
        updated_at=datetime.now(timezone.utc),
    )


def _tweet_entry(item_id: str, text: str = "推文", **legacy_extra: object) -> dict:
    return {
        "entryId": f"tweet-{item_id}",
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "rest_id": item_id,
                        "legacy": {
                            "full_text": text,
                            "created_at": "Sat Aug 30 10:00:00 +0000 2026",
                            **legacy_extra,
                        },
                        "core": {
                            "user_results": {
                                "result": {
                                    "rest_id": "9",
                                    "legacy": {
                                        "name": "Alice",
                                        "screen_name": "alice",
                                        "followers_count": 1200,
                                    },
                                }
                            }
                        },
                    }
                }
            }
        },
    }


def _cursor_entry(value: str) -> dict:
    return {
        "entryId": f"cursor-bottom-{value}",
        "content": {
            "entryType": "TimelineTimelineCursor",
            "cursorType": "Bottom",
            "value": value,
        },
    }


def _timeline_page(entries: list[dict]) -> dict:
    return {
        "data": {
            "user": {
                "result": {
                    "timeline_v2": {
                        "timeline": {
                            "instructions": [
                                {"type": "TimelineAddEntries", "entries": entries}
                            ]
                        }
                    }
                }
            }
        }
    }


def _client_with_pages(pages: list[dict], calls: list[str]) -> TwitterGraphQLClient:
    queue = list(pages)

    def get_json(url: str, **kwargs):
        calls.append(url)
        if "user-query" in url:
            return {"data": {"user": {"result": {"rest_id": "9"}}}}
        return queue.pop(0)

    return TwitterGraphQLClient(json_getter=get_json)


def test_fetch_starts_from_latest_page_and_stops_at_history() -> None:
    calls: list[str] = []
    pages = [
        _timeline_page([_tweet_entry("205"), _cursor_entry("c1")]),
        _timeline_page([_tweet_entry("105"), _cursor_entry("c2")]),
    ]
    result = _client_with_pages(pages, calls).fetch_incremental(
        _alice_target(rest_id="9"),
        {"tweets": _tweets_cursor("110", next_cursor="stale", user_id="9")},
        dict(_AUTHED_CONTEXT),
    )
    timeline_calls = [url for url in calls if "tweets-query" in url]
    assert len(timeline_calls) == 2
    # 上一轮 Bottom cursor 不得作为下一轮入口：首轮请求不带 cursor。
    assert "%22cursor%22" not in timeline_calls[0]
    assert "c1" in timeline_calls[1]
    assert [item.item_id for item in result.items] == ["205"]
    assert result.cursors[0].last_item_id == "205"
    assert result.cursors[0].cursor_payload["user_id"] == "9"


def test_fetch_respects_max_pages_cap() -> None:
    calls: list[str] = []
    pages = [
        _timeline_page([_tweet_entry("301"), _tweet_entry("300"), _cursor_entry("c1")]),
        _timeline_page([_tweet_entry("299"), _cursor_entry("c2")]),
        _timeline_page([_tweet_entry("298")]),
    ]
    context = dict(_AUTHED_CONTEXT)
    context["twitter_max_pages"] = 2
    result = _client_with_pages(pages, calls).fetch_incremental(
        _alice_target(rest_id="9"),
        {"tweets": _tweets_cursor("1")},
        context,
    )
    timeline_calls = [url for url in calls if "tweets-query" in url]
    assert len(timeline_calls) == 2
    assert [item.item_id for item in result.items] == ["301", "300", "299"]


def test_parse_page_handles_visibility_tombstone_promoted_and_modules() -> None:
    payload = _timeline_page(
        [
            {
                "entryId": "promoted-tweet-900",
                "content": {
                    "itemContent": {
                        "tweet_results": {"result": {"rest_id": "900"}},
                    }
                },
            },
            {
                "entryId": "tweet-401",
                "content": {
                    "itemContent": {"tombstone": {"tombstoneInfo": {"richText": {}}}}
                },
            },
            {
                "entryId": "tweet-402",
                "content": {
                    "itemContent": {
                        "tweet_results": {
                            "result": {
                                "__typename": "TweetWithVisibilityResults",
                                "rest_id": "402",
                                "tweet": {
                                    "rest_id": "402",
                                    "legacy": {"full_text": "受限可见推文"},
                                },
                            }
                        }
                    }
                },
            },
            {
                "entryId": "profile-conversation-403",
                "content": {
                    "entryType": "TimelineTimelineModule",
                    "items": [
                        {
                            "entryId": "tweet-403",
                            "item": {
                                "itemContent": {
                                    "tweet_results": {
                                        "result": {
                                            "rest_id": "403",
                                            "legacy": {"full_text": "模块子项"},
                                        }
                                    }
                                }
                            },
                        },
                        {
                            "entryId": "promoted-tweet-950",
                            "item": {
                                "itemContent": {
                                    "itemContentPromoted": {},
                                    "tweet_results": {"result": {"rest_id": "950"}},
                                }
                            },
                        },
                    ],
                },
            },
        ]
    )
    result = TwitterSubscriptionAdapterV2.parse_timeline_payload(
        payload, _alice_target(), ""
    )
    assert [item.item_id for item in result.items] == ["402", "403"]
    texts = {item.item_id: item.source_payload["text"] for item in result.items}
    assert texts["402"] == "受限可见推文"
    assert texts["403"] == "模块子项"


def test_media_extraction_prefers_highest_bitrate_variant_and_dedupes() -> None:
    entry = _tweet_entry("501")
    legacy = entry["content"]["itemContent"]["tweet_results"]["result"]["legacy"]
    legacy["extended_entities"] = {
        "media": [
            {
                "type": "video",
                "media_url_https": "https://pbs.test/1.jpg",
                "expanded_url": "https://x.com/alice/status/501/video/1",
                "video_info": {
                    "preview_image_url": "https://pbs.test/1_prev.jpg",
                    "duration_millis": 81000,
                    "variants": [
                        {"content_type": "video/mp4", "bitrate": 832000, "url": "https://video.test/low.mp4"},
                        {"content_type": "video/mp4", "bitrate": 2176000, "url": "https://video.test/high.mp4"},
                        {"content_type": "application/x-mpegURL", "bitrate": 0, "url": "https://video.test/index.m3u8"},
                    ],
                },
            },
            {"type": "image", "media_url_https": "https://pbs.test/1.jpg"},
        ]
    }
    result = TwitterSubscriptionAdapterV2.parse_timeline_payload(
        _timeline_page([entry]), _alice_target(), ""
    )
    media = result.items[0].source_payload["media"]
    assert len(media) == 1
    video = media[0]
    assert video["video_url"] == "https://video.test/high.mp4"
    assert video["preview_image_url"] == "https://pbs.test/1_prev.jpg"
    assert video["duration_millis"] == 81000


def test_author_profile_and_twitter_date_are_enriched() -> None:
    entry = _tweet_entry("601")
    legacy = entry["content"]["itemContent"]["tweet_results"]["result"]["legacy"]
    legacy["favorite_count"] = 7
    result = TwitterSubscriptionAdapterV2.parse_timeline_payload(
        _timeline_page([entry]), _alice_target(), ""
    )
    item = result.items[0]
    assert item.published_at is not None
    assert item.source_payload["author_followers_count"] == 1200
    assert item.source_payload["author_verified"] is False
    assert item.source_payload["like_count"] == 7


def test_discovery_credentials_are_cached_with_ttl() -> None:
    TwitterGraphQLClient._discovered_credentials = None
    try:
        homepage_hits = {"n": 0}

        def get_text(url: str, **kwargs):
            if url.endswith("x.com/"):
                homepage_hits["n"] += 1
                return url, '<script src="/assets/app.js"></script>'
            return url, (
                'var bearer="AAAAweb-token_12345678901234567890";'
                'queryId:"user-query",operationName:"UserByScreenName";'
                'queryId:"tweets-query",operationName:"UserTweets";'
            )

        def get_json(url: str, **kwargs):
            if "user-query" in url:
                return {"data": {"user": {"result": {"rest_id": "9"}}}}
            return _PAYLOAD

        target = _alice_target()
        for _ in range(2):
            result = TwitterGraphQLClient(
                json_getter=get_json, text_getter=get_text
            ).fetch_incremental(target, {}, {"cookie_header": "auth_token=a; ct0=b"})
            assert [item.item_id for item in result.items] == ["101"]
        assert homepage_hits["n"] == 1
    finally:
        TwitterGraphQLClient._discovered_credentials = None


def test_suspended_account_is_nonretryable_upstream_changed() -> None:
    def get_json(url: str, **kwargs):
        raise ValueError("User has been suspended")

    result = TwitterGraphQLClient(json_getter=get_json).fetch_incremental(
        _alice_target(rest_id="9"),
        {},
        dict(_AUTHED_CONTEXT),
    )
    assert result.health_state == "degraded"
    assert result.error_code == "upstream_changed"
    assert result.retryable is False

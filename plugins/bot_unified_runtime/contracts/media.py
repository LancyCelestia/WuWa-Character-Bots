from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import Field, field_validator

from .music import MusicContributor, MusicTrack
from .runtime import PrivacyLevel, RiskLevel, StrictBaseModel


class SourceInput(StrictBaseModel):
    request_id: str
    session_id: str
    capability_id: str
    source_hint: str | None = None
    input_kind: str = "text"
    raw_text: str = ""
    urls: list[str] = Field(default_factory=list)
    message_segments: list[dict[str, Any]] = Field(default_factory=list)
    share_card_fields: dict[str, Any] = Field(default_factory=dict)
    origin_message_id: str | None = None
    sender_id: str | None = None
    target_scope: str | None = None
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    risk_level: RiskLevel = RiskLevel.LOW


class ParserRule(StrictBaseModel):
    parser_id: str
    source_id: str
    keyword_patterns: list[str] = Field(default_factory=list)
    url_patterns: list[str] = Field(default_factory=list)
    priority: int = 100
    enabled: bool = True

    @field_validator("parser_id", "source_id")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("parser_id and source_id must be non-empty")
        return normalized

    @property
    def longest_keyword_length(self) -> int:
        return max((len(keyword) for keyword in self.keyword_patterns), default=0)


class ParserMatch(StrictBaseModel):
    parser_id: str
    source_id: str
    matched_keyword: str | None = None
    priority: int
    keyword_length: int = 0


class ContentIdentity(StrictBaseModel):
    platform: str
    item_id: str
    item_kind: str
    canonical_url: str
    parent_id: str | None = None
    visibility: str = "public"
    availability: str = "available"

    @field_validator("platform", "item_id", "item_kind", "canonical_url")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("content identity fields must be non-blank")
        return normalized


class ContentMetadata(StrictBaseModel):
    title: str
    body: str = ""
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    language: str | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None
    platform_extra: dict[str, Any] = Field(default_factory=dict)


class VerificationMetadata(StrictBaseModel):
    verified: bool | None = None
    type: str | None = None
    label: str | None = None


class CreatorMetadata(StrictBaseModel):
    platform_creator_id: str | None = None
    name: str = ""
    handle: str | None = None
    avatar_url: str | None = None
    profile_url: str | None = None
    bio: str | None = None
    signature: str | None = None
    verification: VerificationMetadata | None = None
    follower_count: int | None = None
    following_count: int | None = None
    received_like_count: int | None = None
    received_favorite_count: int | None = None
    post_count: int | None = None
    long_video_count: int | None = None
    short_video_count: int | None = None
    video_count: int | None = None
    joined_at: datetime | None = None
    # 平台特有作者扩展字段（如 B 站专栏数、认证文案变体等），渲染投影时透传。
    platform_extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "follower_count",
        "following_count",
        "received_like_count",
        "received_favorite_count",
        "post_count",
        "long_video_count",
        "short_video_count",
        "video_count",
    )
    @classmethod
    def require_non_negative_counts(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("creator counts must be non-negative")
        return value


class EngagementMetrics(StrictBaseModel):
    view_count: int | None = None
    play_count: int | None = None
    like_count: int | None = None
    heart_count: int | None = None
    favorite_count: int | None = None
    bookmark_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    repost_count: int | None = None
    quote_count: int | None = None
    danmaku_count: int | None = None
    coin_count: int | None = None
    platform_extra: dict[str, Any] = Field(
        default_factory=dict
    )

    @field_validator(
        "view_count",
        "play_count",
        "like_count",
        "heart_count",
        "favorite_count",
        "bookmark_count",
        "comment_count",
        "share_count",
        "repost_count",
        "quote_count",
        "danmaku_count",
        "coin_count",
    )
    @classmethod
    def require_non_negative_counts(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("engagement counts must be non-negative")
        return value


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if text.isdigit():
            return int(text)
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([万亿KMB])", text, re.IGNORECASE)
        if match:
            multiplier = {
                "K": 1_000,
                "M": 1_000_000,
                "B": 1_000_000_000,
                "万": 10_000,
                "亿": 100_000_000,
            }.get(match.group(2).upper(), 1)
            return int(float(match.group(1)) * multiplier)
    return None


def _optional_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and value > 0:
        timestamp = float(value)
        if timestamp > 10**12:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        # Twitter/微博英文日期：Wed Oct 10 20:19:24 +0000 2018 / Tue Apr 30 17:46:31 +0800 2024。
        # 注册日期自然语言：2020年1月1日 / Joined 21 Jun 2010 / 2010-06-21。
        try:
            parsed = datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            parsed = None
            match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
            if match:
                parsed = datetime(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                    tzinfo=timezone.utc,
                )
            else:
                match = re.search(r"(\d{1,2}) ([A-Za-z]{3,9}) (\d{4})", text)
                if match:
                    try:
                        parsed = datetime.strptime(
                            f"{match.group(1)} {match.group(2)} {match.group(3)}",
                            "%d %b %Y",
                        ).replace(tzinfo=timezone.utc)
                    except ValueError:
                        parsed = None
            if parsed is None:
                return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


_SENSITIVE_HEADER_MARKERS = (
    "authorization",
    "cookie",
    "proxy-authorization",
    "token",
    "secret",
    "api-key",
    "apikey",
)


class MediaAsset(StrictBaseModel):
    asset_type: str
    url: str | None = None
    preview_url: str | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    mime_type: str | None = None
    bitrate: int | None = None
    fps: float | None = None
    dynamic_range: str | None = None
    order: int = 0
    access_headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("access_headers")
    @classmethod
    def reject_sensitive_headers(cls, value: dict[str, str]) -> dict[str, str]:
        for name in value:
            lowered = str(name).strip().lower()
            if any(marker in lowered for marker in _SENSITIVE_HEADER_MARKERS):
                raise ValueError("media access headers must not contain credentials")
        return value

    @field_validator("width", "height", "duration_ms", "bitrate", "order")
    @classmethod
    def require_non_negative_numbers(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("media numeric metadata must be non-negative")
        return value


class SourceProvenance(StrictBaseModel):
    parse_depth: str
    auth_mode: str
    fetched_at: datetime
    source_endpoints: list[str] = Field(default_factory=list)
    limitations: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ParsedContent(StrictBaseModel):
    """统一解析结果（纯 V2 嵌套模型）。

    权威数据只存在于嵌套字段；平台特有扩展走各模型的 ``platform_extra``。
    解析器统一用模块级 ``build_parsed_content`` 构造（接受平台原始字段形状，
    内部完成投影归一化），模型本身不再保留扁平投影字段。
    """

    identity: ContentIdentity | None = None
    content: ContentMetadata | None = None
    creator: CreatorMetadata | None = None
    engagement: EngagementMetrics = Field(default_factory=EngagementMetrics)
    media: list[MediaAsset] = Field(default_factory=list)
    music: MusicTrack | None = None
    provenance: SourceProvenance | None = None

    @classmethod
    def minimal(
        cls,
        *,
        platform: str,
        item_id: str,
        item_kind: str,
        canonical_url: str,
        title: str,
        limitations: dict[str, str] | None = None,
        availability: str = "available",
    ) -> ParsedContent:
        return cls(
            identity=ContentIdentity(
                platform=platform,
                item_id=item_id or canonical_url or title or "unknown",
                item_kind=item_kind,
                canonical_url=canonical_url or "about:blank",
                availability=availability,
            ),
            content=ContentMetadata(title=title),
            provenance=SourceProvenance(
                parse_depth="shallow",
                auth_mode="anonymous",
                fetched_at=datetime.now(timezone.utc),
                limitations=dict(limitations or {}),
            ),
        )


# detail 字典里被消费进嵌套模型的键；其余键原样进 content.platform_extra。
_DETAIL_CONSUMED_KEYS = frozenset(
    {
        "author", "creator", "media", "images", "video",
        "body", "text", "description",
        "published_at", "publishedAt", "created_at", "updated_at", "updatedAt",
        "canonical_url",
    }
)

# detail.video 里被消费进 MediaAsset 的键；其余键进 content.platform_extra["video"]。
_VIDEO_CONSUMED_KEYS = frozenset(
    {
        "url", "src", "preview_url", "thumbnail_url", "poster",
        "width", "height", "duration", "duration_ms", "mime_type", "mime",
        "bitrate", "fps",
    }
)

# author_data 里被消费进 CreatorMetadata 的键；其余键进 creator.platform_extra。
_AUTHOR_CONSUMED_KEYS = frozenset(
    {
        "uuid", "id", "author_id", "author_uuid", "unique_id", "mid",
        "name", "nickname", "screen_name", "handle", "username",
        "avatar", "avatar_url", "profile_image_url", "profile_url", "url",
        "bio", "description", "signature",
        "fans", "followers", "followers_count", "following", "following_count",
        "likes", "received_likes", "received_like_count",
        "favorites", "received_favorites", "bookmark_count",
        "posts", "post_count", "statuses_count",
        "long_video_count", "short_video_count", "video_count", "videos_count",
        "created_at", "joined_at", "joined",
        "verified", "official_badge", "official_title", "verified_reason",
        "verified_type",
    }
)

# 作者统计中从 stats 提升到 creator 的标签。
_AUTHOR_STATS_KEYS = {
    "粉丝": ("fans",),
    "followers": ("followers",),
    "订阅": ("followers",),
    "关注": ("following",),
    "帖子数": ("posts",),
    "微博数": ("posts",),
    "笔记数": ("posts",),
    "视频数": ("video_count",),
    "专栏数": ("column_count",),
}


def build_parsed_content(
    *,
    platform: str = "",
    item_id: str = "",
    item_kind: str = "unknown",
    title: str = "",
    author_name: str = "",
    summary: str = "",
    body: str = "",
    cover_url: str = "",
    audio_url: str = "",
    canonical_url: str = "",
    stats: dict[str, Any] | None = None,
    parse_depth: str = "deep",
    page_type: str = "",
    badge: str = "",
    detail: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    identity: ContentIdentity | None = None,
    content: ContentMetadata | None = None,
    creator: CreatorMetadata | None = None,
    engagement: EngagementMetrics | None = None,
    media: list[MediaAsset] | None = None,
    music: MusicTrack | None = None,
    provenance: SourceProvenance | None = None,
) -> ParsedContent:
    """平台解析结果构造器：把平台原始字段归一化成纯嵌套 ParsedContent。

    接受解析器直接产出的平台形状字段（stats/detail 等），内部完成：
    stats→engagement、detail.author→creator、detail.media/images/video→media、
    发布时间→content.published_at；平台特有键分别收进
    content/creator/engagement 的 ``platform_extra``，供渲染投影透传。
    """
    detail = dict(detail or {})
    stats = dict(stats or {})
    media = list(media or [])
    video_data = detail.get("video")

    if identity is None:
        canonical = canonical_url or detail.get("canonical_url", "") or ""
        identity = ContentIdentity(
            platform=platform or "unknown",
            item_id=item_id or canonical or title or "unknown",
            item_kind=item_kind or "unknown",
            canonical_url=canonical or "about:blank",
        )

    published_at = _optional_datetime(
        detail.get("published_at")
        or detail.get("publishedAt")
        or detail.get("created_at")
        or stats.get("发布时间")
        or (
            video_data.get("pubdate") if isinstance(video_data, dict) else None
        )
    )
    updated_at = _optional_datetime(
        detail.get("updated_at") or detail.get("updatedAt")
    )
    body_text = str(
        body
        or detail.get("body")
        or detail.get("text")
        or detail.get("description")
        or summary
        or ""
    )

    # ---- content ----
    content_extras: dict[str, Any] = {}
    if page_type:
        content_extras["page_type"] = page_type
    if badge:
        content_extras["badge"] = badge
    if cover_url:
        # 渲染层需要区分「解析器指定的封面」与普通图集，透传到投影。
        content_extras["cover_url"] = cover_url
    if isinstance(detail.get("images"), list):
        # 图集原始列表透传，保证渲染投影与迁移前逐字节等价。
        content_extras["images"] = list(detail["images"])
    if isinstance(video_data, dict):
        video_extras = {
            key: value
            for key, value in video_data.items()
            if key not in _VIDEO_CONSUMED_KEYS
        }
        if video_extras:
            content_extras["video"] = video_extras
    for key in (
        "episodes", "live", "comments", "goods", "related",
        "pinned_comment", "hot_comment",
    ):
        if key in detail:
            content_extras[key] = detail[key]
    for key, value in detail.items():
        if key not in _DETAIL_CONSUMED_KEYS and key not in content_extras:
            content_extras[key] = value
    if content is None:
        content = ContentMetadata(
            title=title,
            summary=summary,
            body=body_text,
            tags=list(tags or []),
            published_at=published_at,
            updated_at=updated_at,
            platform_extra=content_extras,
        )
    else:
        content.title = content.title or title
        content.summary = content.summary or summary
        content.body = content.body or body_text
        content.published_at = content.published_at or published_at
        content.updated_at = content.updated_at or updated_at
        if tags:
            content.tags = [
                *content.tags,
                *(tag for tag in tags if tag not in content.tags),
            ]
        content.platform_extra.update(content_extras)

    # ---- creator ----
    author_data = detail.get("author", {})
    if not author_data and isinstance(detail.get("creator"), dict):
        author_data = detail["creator"]
    if not isinstance(author_data, dict):
        author_data = {}
    author_data = dict(author_data)
    has_author_data = bool(author_data) or bool(author_name)
    for label, keys in _AUTHOR_STATS_KEYS.items():
        if label in stats:
            for key in keys:
                author_data.setdefault(key, stats[label])
    if not author_name and author_data.get("name"):
        author_name = str(author_data["name"])
    if creator is None and has_author_data:
        verification = None
        if any(
            key in author_data
            for key in ("verified", "official_badge", "official_title", "verified_reason")
        ):
            verification = VerificationMetadata(
                verified=(
                    bool(author_data.get("verified"))
                    if "verified" in author_data
                    else bool(
                        author_data.get("official_badge")
                        or author_data.get("verified_reason")
                    )
                ),
                type=str(
                    author_data.get("official_badge")
                    or author_data.get("verified_type")
                    or ""
                ) or None,
                label=str(
                    author_data.get("official_title")
                    or author_data.get("verified_reason")
                    or ""
                ) or None,
            )
        creator_extras = {
            key: value
            for key, value in author_data.items()
            if key not in _AUTHOR_CONSUMED_KEYS
        }
        creator = CreatorMetadata(
            platform_creator_id=str(
                author_data.get("uuid")
                or author_data.get("id")
                or author_data.get("author_id")
                or author_data.get("author_uuid")
                or author_data.get("unique_id")
                or author_data.get("mid")
                or ""
            ) or None,
            name=str(
                author_data.get("name")
                or author_data.get("nickname")
                or author_data.get("screen_name")
                or author_name
                or ""
            ),
            handle=str(
                author_data.get("handle")
                or author_data.get("screen_name")
                or author_data.get("username")
                or ""
            ) or None,
            avatar_url=str(
                author_data.get("avatar")
                or author_data.get("avatar_url")
                or author_data.get("profile_image_url")
                or ""
            ) or None,
            profile_url=str(
                author_data.get("profile_url") or author_data.get("url") or ""
            ) or None,
            bio=str(
                author_data.get("bio")
                or author_data.get("description")
                or ""
            ) or None,
            signature=str(author_data.get("signature") or "") or None,
            verification=verification,
            follower_count=_optional_int(
                author_data.get("fans")
                or author_data.get("followers")
                or author_data.get("followers_count")
            ),
            following_count=_optional_int(
                author_data.get("following")
                or author_data.get("following_count")
            ),
            received_like_count=_optional_int(
                author_data.get("likes")
                or author_data.get("received_likes")
                or author_data.get("received_like_count")
            ),
            received_favorite_count=_optional_int(
                author_data.get("favorites")
                or author_data.get("received_favorites")
                or author_data.get("bookmark_count")
            ),
            post_count=_optional_int(
                author_data.get("posts")
                or author_data.get("post_count")
                or author_data.get("statuses_count")
            ),
            long_video_count=_optional_int(author_data.get("long_video_count")),
            short_video_count=_optional_int(author_data.get("short_video_count")),
            video_count=_optional_int(
                author_data.get("video_count")
                or author_data.get("videos_count")
            ),
            joined_at=_optional_datetime(
                author_data.get("created_at")
                or author_data.get("joined_at")
                or author_data.get("joined")
            ),
            platform_extra=creator_extras,
        )

    # ---- media ----
    raw_media = detail.get("media", [])
    if not media and isinstance(raw_media, list):
        seen_media_urls: set[str] = set()
        for index, value in enumerate(raw_media):
            if isinstance(value, dict):
                asset_type = str(
                    value.get("asset_type") or value.get("type") or "image"
                )
                # 同 URL 去重但保持源顺序；无 URL 的资产不参与去重。
                asset_url = str(value.get("url") or value.get("src") or "") or None
                if asset_url and asset_url in seen_media_urls:
                    continue
                if asset_url:
                    seen_media_urls.add(asset_url)
                duration = _optional_int(value.get("duration_ms"))
                if duration is None and asset_type in {"video", "audio"}:
                    seconds = _optional_int(value.get("duration"))
                    duration = seconds * 1000 if seconds is not None else None
                media.append(
                    MediaAsset(
                        asset_type=asset_type,
                        url=asset_url,
                        preview_url=str(
                            value.get("preview_url")
                            or value.get("thumbnail_url")
                            or value.get("poster")
                            or ""
                        ) or None,
                        width=_optional_int(value.get("width")),
                        height=_optional_int(value.get("height")),
                        duration_ms=duration,
                        mime_type=str(
                            value.get("mime_type") or value.get("mime") or ""
                        ) or None,
                        bitrate=_optional_int(value.get("bitrate")),
                        fps=(
                            float(value["fps"])
                            if isinstance(value.get("fps"), (int, float))
                            else None
                        ),
                        order=index,
                    )
                )
            elif str(value).strip():
                media.append(
                    MediaAsset(asset_type="image", url=str(value), order=index)
                )

    image_values = detail.get("images", [])
    if not media and isinstance(image_values, list):
        media = [
            MediaAsset(asset_type="image", url=str(url), order=index)
            for index, url in enumerate(image_values)
            if str(url).strip()
        ]
    if isinstance(video_data, dict):
        duration = _optional_int(video_data.get("duration_ms"))
        if duration is None:
            seconds = _optional_int(video_data.get("duration"))
            duration = seconds * 1000 if seconds is not None else None
        if (
            duration is not None
            or video_data.get("url")
            or video_data.get("preview_url")
            or video_data.get("thumbnail_url")
            or video_data.get("poster")
        ) and not any(asset.asset_type == "video" for asset in media):
            media.append(
                MediaAsset(
                    asset_type="video",
                    url=str(video_data.get("url") or "") or None,
                    preview_url=str(
                        video_data.get("preview_url")
                        or video_data.get("thumbnail_url")
                        or video_data.get("poster")
                        or ""
                    ) or None,
                    width=_optional_int(video_data.get("width")),
                    height=_optional_int(video_data.get("height")),
                    duration_ms=duration,
                    order=len(media),
                )
            )
    if cover_url and not any(
        asset.asset_type == "image" and asset.url == cover_url for asset in media
    ):
        media.insert(0, MediaAsset(asset_type="image", url=cover_url, order=0))
        for index, asset in enumerate(media):
            asset.order = index
    if audio_url and not any(
        asset.asset_type == "audio" and asset.url == audio_url for asset in media
    ):
        media.append(
            MediaAsset(asset_type="audio", url=audio_url, order=len(media))
        )

    # ---- provenance ----
    if provenance is None:
        provenance = SourceProvenance(
            parse_depth=parse_depth,
            auth_mode="anonymous",
            fetched_at=datetime.now(timezone.utc),
        )

    # ---- engagement ----
    if engagement is None:
        engagement = EngagementMetrics()
    if stats:
        engagement = _engagement_from_legacy_stats(stats, engagement)
        # 字典/列表型统计键（如点歌的 music_card）不进互动字段，原样透传到
        # platform_extra，供能力层消费（渲染投影只透传标量）。
        for key, value in stats.items():
            if isinstance(value, (dict, list)) and key not in engagement.platform_extra:
                engagement.platform_extra[key] = value

    # ---- music ----
    if music is None and identity.item_kind in {
        "music", "song", "audio", "music_track",
    }:
        contributors = [
            MusicContributor(name=name.strip(), roles=["performer"])
            for name in author_name.split("、")
            if name.strip()
        ]
        music = MusicTrack(
            provider=identity.platform,
            provider_track_id=identity.item_id or title,
            title=title,
            contributors=contributors,
            artwork_url=cover_url or None,
            audio_url=audio_url or None,
            limitations={
                "engagement.favorite_count": "provider_not_exposed"
            },
        )

    return ParsedContent(
        identity=identity,
        content=content,
        creator=creator,
        engagement=engagement,
        media=media,
        music=music,
        provenance=provenance,
    )


def parsed_cover_url(item: ParsedContent) -> str:
    """解析器指定封面；缺失时取首张图片资产。"""
    if item.content is not None:
        cover = str((item.content.platform_extra or {}).get("cover_url") or "")
        if cover:
            return cover
    for asset in item.media or []:
        if asset.asset_type == "image" and asset.url:
            return str(asset.url)
    return ""


def _engagement_from_legacy_stats(
    stats: dict[str, Any], current: EngagementMetrics
) -> EngagementMetrics:
    """把已有平台标签投影到统一互动模型；未知键保留在 platform_extra。"""
    labels = {
        "播放": "view_count",
        "播放量": "view_count",
        "阅读": "view_count",
        "浏览": "view_count",
        "浏览量": "view_count",
        "view_count": "view_count",
        "viewCount": "view_count",
        "点赞": "like_count",
        "like_count": "like_count",
        "likeCount": "like_count",
        "爱心": "heart_count",
        "heart_count": "heart_count",
        "收藏": "favorite_count",
        "favorite_count": "favorite_count",
        "收藏数": "favorite_count",
        "评论": "comment_count",
        "comment_count": "comment_count",
        "commentCount": "comment_count",
        "bookmark_count": "bookmark_count",
        "bookmarkCount": "bookmark_count",
        "quote_count": "quote_count",
        "quoteCount": "quote_count",
        "引用": "quote_count",
        "play_count": "play_count",
        "playCount": "play_count",
        "播放次数": "play_count",
        "转发": "repost_count",
        "转发数": "repost_count",
        "repost_count": "repost_count",
        "retweet_count": "repost_count",
        "分享": "share_count",
        "share_count": "share_count",
        "弹幕": "danmaku_count",
        "danmaku_count": "danmaku_count",
        "投币": "coin_count",
        "coin_count": "coin_count",
    }
    values = current.model_dump()
    extras = dict(values.pop("platform_extra", {}) or {})
    for key, value in stats.items():
        field_name = labels.get(str(key))
        normalized = _optional_int(value)
        if field_name is not None and normalized is not None:
            if values.get(field_name) is None:
                values[field_name] = normalized
        elif not isinstance(value, (dict, list)):
            extras[str(key)] = value
    values["platform_extra"] = extras
    return EngagementMetrics.model_validate(values)

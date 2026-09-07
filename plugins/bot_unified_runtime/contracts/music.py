from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import Field, field_validator

from .runtime import StrictBaseModel


class MusicContributor(StrictBaseModel):
    person_id: str | None = None
    name: str
    roles: list[str] = Field(default_factory=list)
    provider_payload: dict[str, Any] = Field(default_factory=dict)


class MusicAlbumRef(StrictBaseModel):
    provider_album_id: str | None = None
    name: str = ""
    artwork_url: str | None = None
    release_date: date | None = None


class MusicEngagement(StrictBaseModel):
    like_count: int | None = None
    heart_count: int | None = None
    favorite_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    popularity: int | float | None = None
    provider_extra: dict[str, int | float | str | None] = Field(default_factory=dict)

    @field_validator(
        "like_count",
        "heart_count",
        "favorite_count",
        "comment_count",
        "share_count",
    )
    @classmethod
    def require_non_negative_counts(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("music engagement counts must be non-negative")
        return value


class MusicTrack(StrictBaseModel):
    canonical_track_id: str | None = None
    provider: str
    provider_track_id: str
    title: str
    aliases: list[str] = Field(default_factory=list)
    contributors: list[MusicContributor] = Field(default_factory=list)
    album: MusicAlbumRef | None = None
    artwork_url: str | None = None
    duration_ms: int | None = None
    release_date: date | None = None
    track_number: int | None = None
    disc_number: int | None = None
    isrc: str | None = None
    language: str | None = None
    genres: list[str] = Field(default_factory=list)
    explicit: bool | None = None
    lyrics: dict[str, str] = Field(default_factory=dict)
    preview_url: str | None = None
    audio_url: str | None = None
    availability: dict[str, Any] = Field(default_factory=dict)
    platform_extra: dict[str, Any] = Field(default_factory=dict)
    engagement: MusicEngagement = Field(default_factory=MusicEngagement)
    limitations: dict[str, str] = Field(default_factory=dict)

    @field_validator("provider", "provider_track_id", "title")
    @classmethod
    def require_non_blank_identity(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("music provider, track id, and title must be non-blank")
        return normalized

    @field_validator("duration_ms", "track_number", "disc_number")
    @classmethod
    def require_non_negative_numbers(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("music numeric metadata must be non-negative")
        return value


class MusicRequestEvent(StrictBaseModel):
    request_id: str
    canonical_track_id: str
    provider: str
    provider_track_id: str
    session_scope: str
    requested_at: datetime
    requester_hash: str | None = None


class MusicRankingEntry(StrictBaseModel):
    canonical_track_id: str
    title: str
    contributors: list[MusicContributor] = Field(default_factory=list)
    request_count: int
    last_requested_at: datetime
    provider_counts: dict[str, int] = Field(default_factory=dict)


class MusicChartEntry(StrictBaseModel):
    provider_track_id: str
    rank: int
    title: str = ""
    canonical_track_id: str | None = None


class MusicChartSnapshot(StrictBaseModel):
    snapshot_id: str
    source_id: str
    platform: str
    category: str
    region: str = ""
    source_type: str
    fetched_at: datetime
    entries: list[MusicChartEntry] = Field(default_factory=list)

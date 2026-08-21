from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

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
        if not value.strip():
            raise ValueError("parser_id and source_id must be non-empty")
        return value

    @property
    def longest_keyword_length(self) -> int:
        return max((len(keyword) for keyword in self.keyword_patterns), default=0)


class ParserMatch(StrictBaseModel):
    parser_id: str
    source_id: str
    matched_keyword: str | None = None
    priority: int
    keyword_length: int = 0


class ParseRequest(StrictBaseModel):
    request_id: str
    source_id: str
    canonical_url: str | None = None
    platform_item_id: str | None = None
    item_kind_hint: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    cache_key: str
    dedupe_key: str
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    risk_level: RiskLevel = RiskLevel.LOW


class ParsedMediaItem(StrictBaseModel):
    request_id: str
    session_id: str
    capability_id: str
    source_id: str
    platform: str
    item_id: str
    item_kind: str
    title: str
    author_name: str | None = None
    summary: str = ""
    text: str = ""
    url: str | None = None
    canonical_url: str | None = None
    published_at: datetime | None = None
    media: list[dict[str, Any]] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    raw_ref: str | None = None
    confidence: float = 1.0
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC


class NormalizedMediaItem(StrictBaseModel):
    request_id: str
    capability_id: str
    item_id: str
    source_id: str
    normalized_kind: str
    title: str
    body: str = ""
    source_url: str | None = None
    source_timestamp: datetime | None = None
    creator: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    dedupe_key: str


class RejectReason(StrictBaseModel):
    source_id: str
    reason: str
    debug_id: str | None = None

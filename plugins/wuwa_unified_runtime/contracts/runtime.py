from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def new_request_id(prefix: str = "req") -> str:
    return _new_id(prefix)


def new_debug_id(prefix: str = "dbg") -> str:
    return _new_id(prefix)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PrivacyLevel(str, Enum):
    PUBLIC = "public"
    GROUP = "group"
    PERSONAL = "personal"
    CREDENTIALED = "credentialed"


class SendPolicy(str, Enum):
    IMMEDIATE = "immediate"
    QUEUED = "queued"
    DIGEST = "digest"
    PRIVATE_FALLBACK = "private_fallback"
    ADMIN_CONFIRM = "admin_confirm"
    SILENT_AUDIT = "silent_audit"


class ReceiptState(str, Enum):
    ACCEPTED = "accepted"
    RENDERED = "rendered"
    QUEUED = "queued"
    SENT = "sent"
    SKIPPED = "skipped"
    REDIRECTED = "redirected"
    BLOCKED = "blocked"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"


class SessionType(str, Enum):
    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"
    EMAIL = "email"
    CONSOLE = "console"


class ReviewAction(str, Enum):
    ALLOW = "allow"
    REWRITE = "rewrite"
    MOVE_PRIVATE = "move_private"
    ADMIN_CONFIRM = "admin_confirm"
    BLOCK = "block"
    AUDIT_ONLY = "audit_only"


class IncomingMessage(StrictBaseModel):
    request_id: str = Field(default_factory=new_request_id)
    platform: str
    adapter: str
    bot_id: str
    session_id: str
    session_type: SessionType
    sender_id: str
    sender_display_name: str | None = None
    group_id: str | None = None
    raw_segments: list[dict[str, Any]] = Field(default_factory=list)
    plain_text: str = ""
    mentions_bot: bool = False
    reply_to_message_id: str | None = None
    timestamp: datetime = Field(default_factory=_utc_now)
    message_id: str | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel | None = None
    debug_id: str = Field(default_factory=new_debug_id)

    @model_validator(mode="after")
    def default_privacy_by_session(self) -> "IncomingMessage":
        if self.privacy_level is None:
            self.privacy_level = (
                PrivacyLevel.GROUP
                if self.session_type is SessionType.GROUP
                else PrivacyLevel.PERSONAL
            )
        return self


class PolicyEvaluation(StrictBaseModel):
    request_id: str
    allowed: bool
    reason: str
    risk_level: RiskLevel = RiskLevel.LOW
    required_scope: str | None = None
    cooldown_key: str
    quota_key: str | None = None
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    audit_tags: list[str] = Field(default_factory=list)
    debug_id: str = Field(default_factory=new_debug_id)


class BotDecision(StrictBaseModel):
    request_id: str
    should_respond: bool
    mode: str
    trigger: str
    capability_id: str
    target_scope: SessionType
    max_messages: int = 1
    send_policy: SendPolicy = SendPolicy.IMMEDIATE
    persona_profile_id: str = "default"
    context_budget: int = 2048
    decision_reason: str
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    audit_tags: list[str] = Field(default_factory=list)

    @field_validator("max_messages")
    @classmethod
    def validate_max_messages(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_messages must be non-negative")
        return value


class CapabilityResult(StrictBaseModel):
    request_id: str = Field(default_factory=new_request_id)
    capability_id: str = "unknown"
    kind: str
    title: str = ""
    summary: str = ""
    body: str = ""
    url: str | None = None
    source: str | None = None
    source_timestamp: datetime | None = None
    images: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 1.0
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    private_recommended: bool = False
    send_policy: SendPolicy = SendPolicy.IMMEDIATE
    debug_id: str = Field(default_factory=new_debug_id)
    audit_tags: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class ReviewResult(StrictBaseModel):
    request_id: str
    approved: bool
    action: ReviewAction = ReviewAction.ALLOW
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    reasons: list[str] = Field(default_factory=list)
    safe_text: str = ""
    debug_id: str = Field(default_factory=new_debug_id)


class RenderedOutput(StrictBaseModel):
    request_id: str
    content_type: str
    content_ref: dict[str, Any]
    text_fallback: str
    size_estimate: int | None = None
    render_debug_id: str = Field(default_factory=lambda: new_debug_id("render"))
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC


class SendRequest(StrictBaseModel):
    request_id: str
    session_id: str
    target_scope: SessionType
    target_id: str
    origin_message_id: str | None = None
    capability_id: str
    content: RenderedOutput
    send_policy: SendPolicy
    priority: str
    max_messages: int
    dedupe_key: str
    cooldown_key: str
    expires_at: datetime | None = None
    privacy_level: PrivacyLevel
    allow_split: bool = False
    allow_forward: bool = False
    persona_profile_id: str
    audit_tags: list[str] = Field(default_factory=list)

    @field_validator("dedupe_key", "cooldown_key")
    @classmethod
    def require_non_blank_keys(cls, value: str, info: Any) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} is required")
        return value

    @field_validator("max_messages")
    @classmethod
    def require_positive_max_messages(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_messages must be at least 1")
        return value


class DeliveryReceipt(StrictBaseModel):
    request_id: str
    state: ReceiptState
    transport: str
    provider_message_id: str | None = None
    retry_count: int = 0
    next_retry_at: datetime | None = None
    public_message: str = ""
    debug_id: str = Field(default_factory=new_debug_id)
    created_at: datetime = Field(default_factory=_utc_now)


class AuditRecord(StrictBaseModel):
    audit_id: str = Field(default_factory=lambda: _new_id("audit"))
    request_id: str
    session_id: str
    capability_id: str
    stage: str
    event: str
    severity: RiskLevel
    public_message: str
    private_debug: str
    created_at: datetime = Field(default_factory=_utc_now)

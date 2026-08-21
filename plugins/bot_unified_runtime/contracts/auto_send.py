from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .runtime import PrivacyLevel, RiskLevel, SessionType, StrictBaseModel, new_request_id


class RecipientDescriptor(StrictBaseModel):
    raw_text: str
    kind: str
    channel_hint: str | None = None
    display_name: str | None = None
    address: str | None = None


class RecipientResolution(StrictBaseModel):
    request_id: str
    recipient_descriptor: RecipientDescriptor
    resolved: bool
    recipient_id: str | None = None
    channel: str | None = None
    target_scope: SessionType | None = None
    target_id: str | None = None
    display_name: str | None = None
    address_ref: str | None = None
    consent_state: str = "unknown"
    allowlist_state: str = "unknown"
    ambiguity: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel = PrivacyLevel.PERSONAL
    failure_reason: str | None = None


class AutoSendIntent(StrictBaseModel):
    request_id: str = Field(default_factory=new_request_id)
    actor_sender_id: str
    actor_session_id: str
    actor_session_type: SessionType
    capability_id: str = "auto_send"
    channel: str
    action: str
    raw_command_text: str
    recipient_descriptors: list[RecipientDescriptor] = Field(default_factory=list)
    content_instruction: str = ""
    subject_instruction: str | None = None
    personalization_mode: str = "light"
    batch_mode: str = "single"
    requested_send_policy: str = "confirm_required"
    priority: str = "normal"
    requested_send_time: datetime | None = None
    locale: str = "zh-CN"
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel = PrivacyLevel.PERSONAL


class GeneratedDraft(StrictBaseModel):
    draft_id: str
    request_id: str
    recipient_id: str
    channel: str
    subject: str | None = None
    text_body: str | None = None
    message_body: str | None = None
    tone: str = "default"
    personalization_notes: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel = PrivacyLevel.PERSONAL
    expires_at: datetime | None = None
    version: int = 1


class DraftPreview(StrictBaseModel):
    preview_id: str
    request_id: str
    actor_sender_id: str
    draft_ids: list[str]
    valid_recipient_count: int
    invalid_recipient_count: int
    channel: str
    batch_summary: str
    per_recipient_summary: list[dict[str, str]] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel = PrivacyLevel.PERSONAL
    expires_at: datetime | None = None
    confirm_command: str
    cancel_command: str

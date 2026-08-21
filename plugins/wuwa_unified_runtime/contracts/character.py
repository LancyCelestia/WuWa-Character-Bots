from __future__ import annotations

from pydantic import Field

from .runtime import PrivacyLevel, RiskLevel, StrictBaseModel


class EmotionSignal(StrictBaseModel):
    request_id: str
    session_id: str
    speaker_id: str
    source: str = "unknown"
    signal_kind: str = "emotion"
    emotion_label: str = "unknown"
    confidence: float = 0.0
    evidence: str = ""
    guidance: str = ""
    privacy_level: PrivacyLevel = PrivacyLevel.PERSONAL


class MemoryQuery(StrictBaseModel):
    request_id: str
    query_text: str
    requester_id: str
    subject_user_id: str
    session_id: str
    group_id: str | None = None
    purpose: str
    memory_scope: str = "user"
    scopes: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    time_window: str | None = None
    max_items: int = 5
    max_chars: int = 1200
    include_raw_messages: bool = False
    include_summarized_facts: bool = True
    include_preferences: bool = True
    consent_basis: str = "implicit_current_chat"
    privacy_level: PrivacyLevel = PrivacyLevel.PERSONAL


class MemoryRetrievalResult(StrictBaseModel):
    request_id: str
    facts: list[dict[str, str]] = Field(default_factory=list)
    raw_message_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    privacy_level: PrivacyLevel = PrivacyLevel.PERSONAL


class ConversationTurn(StrictBaseModel):
    role: str
    text: str
    created_at: str


class ConversationHistoryResult(StrictBaseModel):
    request_id: str
    turns: list[ConversationTurn] = Field(default_factory=list)
    privacy_level: PrivacyLevel = PrivacyLevel.PERSONAL


class PersonaProfile(StrictBaseModel):
    profile_id: str
    version: str
    display_name: str
    identity: str
    role_boundaries: list[str] = Field(default_factory=list)
    style_rules: list[str] = Field(default_factory=list)
    forbidden_behaviors: list[str] = Field(default_factory=list)


class ToneProfile(StrictBaseModel):
    profile_id: str
    mode: str
    voice: str = "default"
    warmth: float = 0.5
    directness: float = 0.5
    message_count_limit: int = 1
    markdown_allowed: bool = True
    action_brackets: bool = True


class KnowledgeSource(StrictBaseModel):
    source_id: str
    source_type: str
    title: str
    trust_level: str = "unknown"
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    risk_level: RiskLevel = RiskLevel.LOW


class KnowledgeChunk(StrictBaseModel):
    chunk_id: str
    source_id: str
    title: str
    content: str
    source_url: str | None = None
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC


class RetrievalResult(StrictBaseModel):
    request_id: str
    chunks: list[KnowledgeChunk] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    answerable: bool = False
    confidence: float = 0.0
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC


class TrendNote(StrictBaseModel):
    """一条时梗/时效备注；属于不可信事实，只作背景参考。"""

    topic: str
    note: str
    observed_on: str = ""
    confidence: float = 0.5
    source: str = "local_notes"


class TrendContext(StrictBaseModel):
    request_id: str
    notes: list[TrendNote] = Field(default_factory=list)
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC


class TemporalContext(StrictBaseModel):
    """当前环境信息：本地时间、日期、节气、节日、天气。

    时间/日期由系统计算，可信；天气来自外部接口，可能不可用或过期。
    """

    request_id: str
    now_local: str = ""
    date_local: str = ""
    weekday: str = ""
    timezone: str = ""
    solar_term: str = ""
    holiday: str = ""
    weather_summary: str = ""
    weather_ok: bool = False
    weather_source: str = ""
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC


class ContextBundle(StrictBaseModel):
    request_id: str
    persona: PersonaProfile
    tone: ToneProfile
    memory_results: MemoryRetrievalResult
    conversation_history: ConversationHistoryResult = Field(
        default_factory=lambda: ConversationHistoryResult(request_id="")
    )
    knowledge_results: RetrievalResult
    current_message: str
    sender_id: str
    session_id: str
    emotion_signals: list[EmotionSignal] = Field(default_factory=list)
    trend_context: TrendContext | None = None
    temporal_context: TemporalContext | None = None
    context_budget: int = 2048
    privacy_level: PrivacyLevel = PrivacyLevel.PERSONAL
    risk_level: RiskLevel = RiskLevel.LOW

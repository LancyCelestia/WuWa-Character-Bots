from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 引用链条目定义在 message_context（纯数据类，不依赖本包），放在这里只做类型
# 透传——contracts 是叶子依赖，不再反向 import contracts，故无环。
from plugins.bot_unified_runtime.message_context import ReplyChainItem


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


class OperationalIssue(StrictBaseModel):
    stage: str
    kind: str
    retryable: bool = False
    severity: RiskLevel = RiskLevel.MEDIUM
    debug_id: str = Field(default_factory=new_debug_id)
    safe_summary: str = ""
    attempts: int = 1
    elapsed_ms: float | None = None

    @field_validator("stage", "kind")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("operational issue stage/kind must be non-blank")
        return normalized

    @field_validator("attempts")
    @classmethod
    def require_positive_attempts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("attempts must be at least 1")
        return value

    @field_validator("elapsed_ms")
    @classmethod
    def require_non_negative_elapsed(cls, value: float | None) -> float | None:
        if value is not None and (value < 0 or not math.isfinite(value)):
            raise ValueError("elapsed_ms must be finite and non-negative")
        return value


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
    # OneBot 原生身份事实：只作上下文与审计展示，权限仍由 RoleSettings 按 sender_id 决定。
    sender_platform_role: str | None = None
    sender_card: str | None = None
    sender_nickname: str | None = None
    sender_title: str | None = None
    # 审查 B-07：QQ 群等级（OneBot v11 sender.level）是用户画像维度；只作上下文
    # 与画像展示，不影响权限。Optional 容缺，非 OneBot 事件保持 None（零破坏）。
    sender_level: str | None = None
    group_title: str | None = None
    group_id: str | None = None
    raw_segments: list[dict[str, Any]] = Field(default_factory=list)
    plain_text: str = ""
    # 派生只读：去掉**开头**对本机器人称呼后的指令文本（摄取层经
    # `runtime.mentions.strip_leading_name_mention` 在"引用拼接之前"的那份原文上
    # 算出）。它**不覆盖也不等于** plain_text——路由判定、诊断标签、好感感知等
    # 既有消费方继续读 plain_text；本字段只给带 `^...$` 锚的自然语言命令判据
    # （如 L4「亲密模式 开」）用，让"@守岸人 亲密模式 开"这类群内习惯句式命中。
    # 缺省空串安全：未填的构造点（smoke/console/admin/campus 等）语义为
    # "没有可剥的点名"，消费方按 `command_text or plain_text` 回退即可。
    command_text: str = ""
    mentions_bot: bool = False
    # True=mentions_bot 仅由软触发（文本昵称/小名）贡献，无硬 @/回复 bot；
    # white2 门用它把“写了名字”与“真 @”区分开。
    name_mention_only: bool = False
    # R4 场景化回应（2026-09-12 用户裁定）：文本含策展昵称但无硬 @/回复 bot
    # 的「软点名」。长文本埋昵称不一定是对机器人说话，门禁可据此降级为观察。
    soft_persona_mention: bool = False
    reply_to_message_id: str | None = None
    reply_to_text: str = ""
    # 引用链（评审需求「综合解析回复消息 + 递归解析嵌套引用」）：自近及远逐层
    # 采集被引用内容，含每层 message_id/发送者/文本/媒体标签。QQ 侧此前因读错
    # Reply 属性而恒为空，Telegram 侧只读第一层；本字段是结构化载体，
    # reply_to_text 保留为层级 1 的兼容别名。
    reply_chain: list[ReplyChainItem] = Field(default_factory=list)
    thread_id: str | None = None
    timestamp: datetime = Field(default_factory=_utc_now)
    message_id: str | None = None
    # 视频理解：回复引用的视频经适配器反查（SnowLuma get_msg）拿到的本地文件路径；
    # 空 = 未获取或不可用。由 handler 在异步上下文填充，能力层只读。
    reply_video_path: str = ""
    # 媒体归档：回复的媒体经 handler 反查（SnowLuma get_msg）注入的 image/animation/
    # video 段；空 = 无回复媒体或不可用。由 handler 在异步上下文填充，能力层只读。
    reply_media_segments: list[dict[str, Any]] = Field(default_factory=list)
    # 媒体归档：回复的合并转发被 get_forward_msg 展开后的逐条正文；空 = 非转发。
    chat_record_text: str = ""
    # 百科接地块（2026-09-27 甲+丙批）：萌百/本地知识库正文经能力层 URL 剥除后，
    # 由**处理程序在异步上下文填充**、能力层只读（与 reply_video_path /
    # chat_record_text 同一先例形态）。聊天链装配点把它过中央件
    # guard_secondhand_text 并进本轮唯一一次生成——百科内容不自答、不甩链接、
    # 不开第二条 LLM 通路。空 = 本轮没有接地块（全部既有构造点零改动零行为变化）。
    kb_grounding_text: str = ""
    # 接地来源标签（一行中文，如「本地知识库·予愿安洁莉娜·萌娘百科」）；
    # 只作 guard 的 source_label 与降级出处行，不进任何判据。
    kb_grounding_label: str = ""
    sender_roles: list[str] = Field(default_factory=lambda: ["user"])
    # 这条消息已被「期后补回」重投过几次（2026-09-25 用户裁定第 2 项）。
    # 被限流拦下的明确请求不再静默丢弃，而是等解禁后补跑一次；本字段就是
    # 那条补跑的计数上限，缺省 0=从未补过（既有构造点零改动、零行为变更）。
    redrive_count: int = 0
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel | None = None
    debug_id: str = Field(default_factory=new_debug_id)

    @model_validator(mode="after")
    def default_privacy_by_session(self) -> IncomingMessage:
        if self.privacy_level is None:
            self.privacy_level = (
                PrivacyLevel.GROUP
                if self.session_type is SessionType.GROUP
                else PrivacyLevel.PERSONAL
            )
        roles = [role.strip() for role in self.sender_roles if role.strip()]
        if "user" not in roles:
            roles.insert(0, "user")
        self.sender_roles = list(dict.fromkeys(roles))
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
    actor_roles: list[str] = Field(default_factory=lambda: ["user"])
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
    actor_roles: list[str] = Field(default_factory=lambda: ["user"])
    audit_tags: list[str] = Field(default_factory=list)

    @field_validator("max_messages")
    @classmethod
    def validate_max_messages(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_messages must be non-negative")
        return value


class CapabilityResult(StrictBaseModel):
    request_id: str
    capability_id: str = "unknown"
    kind: str
    title: str = ""
    summary: str = ""
    body: str = ""
    url: str | None = None
    source: str | None = None
    source_timestamp: datetime | None = None
    images: list[dict[str, Any]] = Field(default_factory=list)
    audio: list[dict[str, Any]] = Field(default_factory=list)
    video: list[dict[str, Any]] = Field(default_factory=list)
    files: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    # 渲染前置部件（戳一戳 v2 的群聊 @ 段等）：拼在 mixed parts 最前；
    # 空=无前置，text/image 既有路径零变化。
    prefix_parts: list[dict[str, Any]] = Field(default_factory=list)
    # 可选：需要拆成多条消息直接发送的纯文本段（不合并转发）。
    text_parts: list[str] | None = None
    confidence: float = 1.0
    risk_level: RiskLevel = RiskLevel.LOW
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    private_recommended: bool = False
    send_policy: SendPolicy = SendPolicy.IMMEDIATE
    debug_id: str = Field(default_factory=new_debug_id)
    audit_tags: list[str] = Field(default_factory=list)
    operational_issue: OperationalIssue | None = None
    # 请求级单调时钟 deadline（time.monotonic() 绝对值）；None=未启用请求预算。
    deadline_monotonic: float | None = None

    @field_validator("deadline_monotonic")
    @classmethod
    def validate_deadline_monotonic(cls, value: float | None) -> float | None:
        if value is not None and (value < 0 or not math.isfinite(value)):
            raise ValueError("deadline_monotonic must be finite and non-negative")
        return value

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
    # 用于发送队列在没有原始 Event 时选择正确的适配器和 Bot。
    adapter: str = ""
    bot_id: str = ""
    audit_tags: list[str] = Field(default_factory=list)
    operational_issue: OperationalIssue | None = None
    # 从 CapabilityResult 透传的请求级单调时钟 deadline；None=未启用。
    deadline_monotonic: float | None = None

    @field_validator("deadline_monotonic")
    @classmethod
    def require_valid_deadline_monotonic(cls, value: float | None) -> float | None:
        if value is not None and (value < 0 or not math.isfinite(value)):
            raise ValueError("deadline_monotonic must be finite and non-negative")
        return value

    @field_validator("dedupe_key", "cooldown_key")
    @classmethod
    def require_non_blank_keys(cls, value: str, info: Any) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} is required")
        return value

    @field_validator("max_messages")
    @classmethod
    def require_non_negative_max_messages(cls, value: int) -> int:
        # 0 = 不限制条数（完整回复一次性发出）。
        if value < 0:
            raise ValueError("max_messages must be at least 0")
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
    operational_issue: OperationalIssue | None = None


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

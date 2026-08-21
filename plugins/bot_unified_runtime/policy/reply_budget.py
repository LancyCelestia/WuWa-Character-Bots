from __future__ import annotations

from pydantic import Field, field_validator

from plugins.bot_unified_runtime.contracts import IncomingMessage, RiskLevel, SessionType
from plugins.bot_unified_runtime.contracts.runtime import StrictBaseModel

BASE_CONTEXT_BUDGET = 2048
SUPPORT_CONTEXT_BUDGET = 2560
DEEP_HELP_CONTEXT_BUDGET = 3072
GROUP_CONTEXT_BUDGET = 2048

SUPPORT_MARKERS = (
    "难受",
    "不舒服",
    "伤心",
    "焦虑",
    "害怕",
    "崩溃",
    "失眠",
    "好累",
    "很累",
    "累了",
    "陪我",
    "安慰",
    "撑不住",
)

DEEP_HELP_MARKERS = (
    "一步一步",
    "详细",
    "教我",
    "教程",
    "怎么配置",
    "怎么实现",
    "帮我分析",
    "帮我梳理",
    "解释一下",
    "为什么",
    "排查",
)

CHAT_CAPABILITY_IDS = {"bot.chat"}


class ReplyBudget(StrictBaseModel):
    max_messages: int = 1
    context_budget: int = BASE_CONTEXT_BUDGET
    reason: str = "default_one_message"
    audit_tags: list[str] = Field(default_factory=lambda: ["reply_budget:default"])

    @field_validator("max_messages")
    @classmethod
    def require_positive_max_messages(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_messages must be at least 1")
        return value


class ReplyBudgetSettings(StrictBaseModel):
    private_default_max_messages: int = 1
    private_support_max_messages: int = 2
    private_deep_help_max_messages: int = 3
    group_max_messages: int = 1
    risk_max_messages: int = 1
    default_context_budget: int = BASE_CONTEXT_BUDGET
    support_context_budget: int = SUPPORT_CONTEXT_BUDGET
    deep_help_context_budget: int = DEEP_HELP_CONTEXT_BUDGET
    group_context_budget: int = GROUP_CONTEXT_BUDGET

    @field_validator(
        "private_default_max_messages",
        "private_support_max_messages",
        "private_deep_help_max_messages",
        "group_max_messages",
        "risk_max_messages",
    )
    @classmethod
    def require_positive_message_limits(cls, value: int) -> int:
        if value < 1:
            raise ValueError("reply message limits must be at least 1")
        return value

    @field_validator(
        "default_context_budget",
        "support_context_budget",
        "deep_help_context_budget",
        "group_context_budget",
    )
    @classmethod
    def require_reasonable_context_budget(cls, value: int) -> int:
        if value < 600:
            raise ValueError("reply context budgets must be at least 600")
        return value


def build_reply_budget_settings(config: object) -> ReplyBudgetSettings:
    return ReplyBudgetSettings(
        private_default_max_messages=int(
            getattr(config, "bot_reply_private_default_max_messages", 1)
        ),
        private_support_max_messages=int(
            getattr(config, "bot_reply_private_support_max_messages", 2)
        ),
        private_deep_help_max_messages=int(
            getattr(config, "bot_reply_private_deep_help_max_messages", 3)
        ),
        group_max_messages=int(getattr(config, "bot_reply_group_max_messages", 1)),
        risk_max_messages=int(getattr(config, "bot_reply_risk_max_messages", 1)),
        default_context_budget=int(getattr(config, "bot_reply_default_context_budget", 2048)),
        support_context_budget=int(getattr(config, "bot_reply_support_context_budget", 2560)),
        deep_help_context_budget=int(
            getattr(config, "bot_reply_deep_help_context_budget", 3072)
        ),
        group_context_budget=int(getattr(config, "bot_reply_group_context_budget", 2048)),
    )


def decide_reply_budget(
    message: IncomingMessage,
    capability_id: str,
    settings: ReplyBudgetSettings | None = None,
) -> ReplyBudget:
    settings = settings or ReplyBudgetSettings()
    if capability_id not in CHAT_CAPABILITY_IDS:
        return ReplyBudget(
            max_messages=1,
            context_budget=settings.default_context_budget,
            reason="non_chat_capability",
            audit_tags=["reply_budget:non_chat"],
        )

    text = message.plain_text.strip()
    markers = _detect_markers(text)
    budget = ReplyBudget(
        max_messages=settings.private_default_max_messages,
        context_budget=settings.default_context_budget,
        reason="chat_default",
        audit_tags=["reply_budget:chat_default"],
    )

    if markers["support"]:
        budget = ReplyBudget(
            max_messages=settings.private_support_max_messages,
            context_budget=settings.support_context_budget,
            reason="support_need",
            audit_tags=["reply_budget:support"],
        )

    if markers["deep_help"]:
        budget = ReplyBudget(
            max_messages=settings.private_deep_help_max_messages,
            context_budget=settings.deep_help_context_budget,
            reason="deep_help",
            audit_tags=["reply_budget:deep_help"],
        )

    if message.session_type is SessionType.GROUP:
        return ReplyBudget(
            max_messages=min(budget.max_messages, settings.group_max_messages),
            context_budget=min(budget.context_budget, settings.group_context_budget),
            reason=f"{budget.reason}; group cap",
            audit_tags=[*budget.audit_tags, "reply_budget:group_cap"],
        )

    if message.risk_level in {RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL}:
        return ReplyBudget(
            max_messages=min(budget.max_messages, settings.risk_max_messages),
            context_budget=min(budget.context_budget, settings.default_context_budget),
            reason=f"{budget.reason}; risk cap",
            audit_tags=[*budget.audit_tags, "reply_budget:risk_cap"],
        )

    return budget


def _detect_markers(text: str) -> dict[str, bool]:
    lowered = text.lower()
    return {
        "support": any(marker in text for marker in SUPPORT_MARKERS),
        "deep_help": any(marker in text for marker in DEEP_HELP_MARKERS)
        or any(marker in lowered for marker in ("step by step", "explain", "tutorial")),
    }

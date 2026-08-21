"""预警推送闭环。

预警内容固定包含五要素：
1. 出了什么错（what_happened）
2. 影响（impact，哪里会出问题）
3. 怎么解决（fix_suggestion）
4. 时间（occurred_at，精确到秒）
5. 位置（location，模块/阶段/会话）

预警通过统一流水线发给管理员（``BOT_ADMIN_USER_IDS``），走
``SendRequest -> DeliveryReceipt -> AuditRecord``，不绕过审计。
控制台模式下直接打印。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    SessionType,
)


@dataclass(frozen=True)
class AlertContent:
    title: str
    what_happened: str
    impact: str
    fix_suggestion: str
    location: str
    level: str = "warning"  # info | warning | critical
    occurred_at: str = ""

    def __post_init__(self) -> None:
        if not self.occurred_at:
            object.__setattr__(
                self,
                "occurred_at",
                datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
            )

    def format_message(self) -> str:
        lines = [
            f"[预警] {self.title}",
            f"时间：{self.occurred_at}",
            f"位置：{self.location}",
            f"发生了什么：{self.what_happened}",
            f"影响：{self.impact}",
            f"建议处理：{self.fix_suggestion}",
        ]
        return "\n".join(lines)


def build_alert_capability_result(
    request_id: str,
    alert: AlertContent,
) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id,
        capability_id="bot.alert",
        kind="text",
        title=alert.title,
        body=alert.format_message(),
        confidence=1.0,
        risk_level=(
            RiskLevel.HIGH if alert.level == "critical" else RiskLevel.MEDIUM
        ),
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["admin_alert", f"alert_level:{alert.level}", "alert"],
    )


def send_admin_alert(
    pipeline: object,
    admin_ids: list[str],
    alert: AlertContent,
) -> list[str]:
    """把预警发给每个管理员；返回实际创建了发送请求的管理员 ID。"""
    sent: list[str] = []
    for admin_id in admin_ids:
        admin_id = str(admin_id).strip()
        if not admin_id:
            continue
        message = IncomingMessage(
            platform="runtime",
            adapter="alert",
            bot_id="runtime-alert",
            session_id=f"private:{admin_id}",
            session_type=SessionType.PRIVATE,
            sender_id="runtime",
            sender_display_name="运行时预警",
            plain_text=alert.title,
            mentions_bot=False,
        )

        def capability(
            _message: IncomingMessage,
            _decision: object,
        ) -> CapabilityResult:
            return build_alert_capability_result(_message.request_id, alert)

        try:
            receipt = pipeline.handle(
                message,
                capability,
                capability_id="bot.alert",
            )
        except Exception:
            continue
        if receipt.state.value in {"sent", "accepted", "queued", "rendered"}:
            sent.append(admin_id)
    return sent

from __future__ import annotations

from plugins.wuwa_unified_runtime.contracts import CapabilityResult, PrivacyLevel, RiskLevel, SendPolicy, new_request_id


def build_status_result(request_id: str | None = None) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id or new_request_id("status"),
        capability_id="wuwa.status",
        kind="text",
        title="状态",
        body="统一运行时在线",
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
    )


def build_help_result(request_id: str | None = None) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id or new_request_id("help"),
        capability_id="wuwa.help",
        kind="text",
        title="用法",
        body="用法：/wuwa status；自动发送草稿：报存 给 A 发消息/邮件，内容...",
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
    )


def route_wuwa_command(command_text: str, request_id: str | None = None) -> CapabilityResult:
    if command_text.strip() == "status":
        return build_status_result(request_id=request_id)
    return build_help_result(request_id=request_id)

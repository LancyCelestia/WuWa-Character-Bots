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

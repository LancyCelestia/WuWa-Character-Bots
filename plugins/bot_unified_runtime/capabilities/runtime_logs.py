"""bot.logs 查询命令能力（仅管理员）。"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    new_request_id,
)


def _is_admin(actor_roles: list[str]) -> bool:
    return "admin" in {role.strip() for role in actor_roles}


def build_logs_query_result(
    runtime_event_log: Any | None,
    *,
    request_id: str | None = None,
    actor_roles: list[str],
    level: str = "info",
    limit: int = 50,
) -> CapabilityResult:
    """返回最近 N 条运行时事件日志；非管理员拒绝。"""
    request_id = request_id or new_request_id("logs")
    if not _is_admin(actor_roles):
        return CapabilityResult(
            request_id=request_id,
            capability_id="bot.logs",
            kind="text",
            title="运行时日志",
            body="只有管理员才能查询运行时日志。",
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PERSONAL,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=["runtime_logs", "logs_denied"],
        )
    if runtime_event_log is None:
        return CapabilityResult(
            request_id=request_id,
            capability_id="bot.logs",
            kind="text",
            title="运行时日志",
            body="运行时事件日志未启用。",
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PERSONAL,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=["runtime_logs", "logs_unavailable"],
        )
    try:
        limit_int = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        limit_int = 50
    lines = runtime_event_log.read_recent(limit=limit_int, min_level=level)
    body = "\n".join(lines) if lines else "（没有符合条件的日志）"
    return CapabilityResult(
        request_id=request_id,
        capability_id="bot.logs",
        kind="text",
        title=f"运行时日志（{level.upper()}，最近 {limit_int} 条）",
        body=body,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["runtime_logs", f"logs_level:{level}", f"logs_lines:{len(lines)}"],
    )

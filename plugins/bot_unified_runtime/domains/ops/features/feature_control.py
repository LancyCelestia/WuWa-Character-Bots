"""/bot feature 命令适配器；不直接读写运行文件。"""
from __future__ import annotations

from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.control_plane.services import (
    ControlServiceError,
    FeatureControlService,
)
from plugins.bot_unified_runtime.domains.core.contracts import (
    CapabilityResult,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
)


def build_feature_control_result(
    service: FeatureControlService, *, request_id: str, actor_id: str,
    actor_roles: list[str], command_text: str,
) -> CapabilityResult:
    principal = Principal(actor_id, tuple(actor_roles))
    parts = command_text.split()
    body = "用法：/bot feature list|get <ID>|enable <ID>|disable <ID>|reset <ID>|preview <ID> on/off/reset"
    tags = ["feature_control"]
    try:
        if not set(actor_roles) & {"admin", "super_admin"}:
            raise ControlServiceError("forbidden", "功能管理需要管理员权限，修改仅限超管。", 403)
        if parts == ["list"]:
            body = "\n".join(f"{item['descriptor']['id']}：{'启用' if item['state']['effective_enabled'] else '停用'}" for item in service.list_features())
        elif len(parts) == 2 and parts[0] == "get":
            state = service.detail(parts[1])["state"]
            body = f"{state['feature_id']}：{'启用' if state['effective_enabled'] else '停用'}；版本 {state['version']}；图修订 {state.get('graph_revision', 0)}"
        elif len(parts) == 2 and parts[0] in {"enable", "disable", "reset"}:
            state = service.detail(parts[1])["state"]
            enabled = {"enable": True, "disable": False, "reset": None}[parts[0]]
            result = service.change(parts[1], enabled, principal=principal, expected_version=state["version"], expected_revision=state.get("graph_revision", 0), request_id=request_id)
            body = f"功能状态已更新：{result['state']['feature_id']}；版本 {result['state']['version']}；审计 {result['audit_id']}。已运行的任务不会被强杀。"
        elif len(parts) == 3 and parts[0] == "preview" and parts[2] in {"on", "off", "reset"}:
            state = service.detail(parts[1])["state"]
            result = service.change(parts[1], {"on": True, "off": False, "reset": None}[parts[2]], principal=principal, expected_version=state["version"], expected_revision=state.get("graph_revision", 0), request_id=request_id, preview=True)
            body = "预览，不修改状态。影响节点：" + ", ".join(result["affected_ids"])
    except ControlServiceError as exc:
        body = exc.message
        tags.append(exc.code)
    return CapabilityResult(request_id=request_id, capability_id="bot.runtime", kind="text", title="功能管理", body=body, confidence=1.0, risk_level=RiskLevel.LOW, privacy_level=PrivacyLevel.PERSONAL, send_policy=SendPolicy.IMMEDIATE, audit_tags=tags)

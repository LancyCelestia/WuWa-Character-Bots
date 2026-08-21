"""管理员运行时指令：/bot runtime ... 与 /bot alert check。

在 QQ 对话里直接说命令即可执行，走统一流水线，仅管理员可用：

- ``/bot runtime set <KEY> <VALUE> [--instance <名称>]``  调整运行时参数
- ``/bot runtime get <KEY> [--instance <名称>]``
- ``/bot runtime list [--instance <名称>]``
- ``/bot runtime reset [KEY] [--instance <名称>]``
- ``/bot runtime nickname add|remove|list <昵称> [--instance <名称>]``
- ``/bot runtime instance list``  列出已创建的实例设置文件
- ``/bot alert check [--probe]``  手动执行凭据健康检查

``--instance`` 定位目标机器人实例（守岸人 / 艾弥斯等），缺省为本
进程实例；每个实例的设置、昵称、互动计数彼此隔离。非管理员查询/
执行一律拒绝，且不透露任何内部状态。
"""

from __future__ import annotations

from plugins.wuwa_unified_runtime.contracts import (
    CapabilityResult,
    RiskLevel,
    SendPolicy,
)
from plugins.wuwa_unified_runtime.runtime.settings import (
    SETTABLE_KEYS,
    InstanceSettingsManager,
    RuntimeSettingsStore,
)
from plugins.wuwa_unified_runtime.sources.credential_health import (
    check_credentials_and_report,
)


def _admin_only_result(request_id: str) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id,
        capability_id="wuwa.runtime",
        kind="text",
        title="权限不足",
        body="该命令只允许管理员使用。",
        confidence=1.0,
        risk_level=RiskLevel.MEDIUM,
        privacy_level="personal",
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["runtime_admin", "permission_denied"],
    )


def _ok_result(request_id: str, body: str, capability_id: str = "wuwa.runtime") -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id,
        capability_id=capability_id,
        kind="text",
        title="运行时设置",
        body=body,
        confidence=1.0,
        risk_level=RiskLevel.LOW,
        privacy_level="personal",
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["runtime_admin", capability_id],
    )


def _error_result(request_id: str, message: str) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id,
        capability_id="wuwa.runtime",
        kind="text",
        title="运行时设置失败",
        body=message,
        confidence=1.0,
        risk_level=RiskLevel.MEDIUM,
        privacy_level="personal",
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["runtime_admin", "runtime_admin_error"],
    )


def _extract_instance(parts: list[str]) -> tuple[list[str], str]:
    """从命令片段中提取 --instance <名称>；返回 (剩余片段, 实例名)。"""
    instance = ""
    remaining: list[str] = []
    index = 0
    while index < len(parts):
        if parts[index] == "--instance" and index + 1 < len(parts):
            instance = parts[index + 1]
            index += 2
            continue
        remaining.append(parts[index])
        index += 1
    return remaining, instance


def _handle_runtime_command(
    manager: InstanceSettingsManager,
    default_instance: str,
    config: object,
    command_text: str,
) -> str:
    parts = command_text.split()
    if not parts:
        return "用法：/bot runtime set|get|list|reset|nickname|instance ..."
    action = parts[0].lower()
    if action == "instance" and len(parts) > 1 and parts[1].lower() == "list":
        instances = manager.list_instances()
        return (
            f"已有实例设置：{','.join(instances)}"
            if instances
            else "还没有任何实例设置文件（首次运行时自动创建）。"
        )
    remaining, instance = _extract_instance(parts[1:])
    store = manager.get(instance or default_instance)
    instance_label = f"[实例 {store.instance}] "
    if action == "set":
        if len(remaining) < 2:
            return "用法：/bot runtime set <KEY> <VALUE> [--instance <名称>]"
        key, value = remaining[0], " ".join(remaining[1:])
        converted = store.set_override(key, value)
        return f"{instance_label}已设置 {key.upper()} = {converted}（已持久化，目标实例会自动刷新）。"
    if action == "get":
        if len(remaining) < 1:
            return "用法：/bot runtime get <KEY> [--instance <名称>]"
        key = remaining[0].upper()
        if key not in SETTABLE_KEYS:
            return f"不支持查询的键：{key}。可用键：{','.join(sorted(SETTABLE_KEYS))}"
        value = store.get(key, config)
        suffix = "（覆盖值）" if key in store.list_overrides() else "（.env 默认值）"
        return f"{instance_label}{key} = {value}{suffix}"
    if action == "list":
        overrides = store.list_overrides()
        if not overrides:
            return f"{instance_label}当前没有运行时覆盖，全部使用 .env 配置。"
        return "\n".join(
            f"{instance_label}{key} = {value}" for key, value in sorted(overrides.items())
        )
    if action == "reset":
        key = remaining[0] if remaining else None
        count = store.reset_override(key)
        return f"{instance_label}已清除 {count} 项运行时覆盖。"
    if action == "nickname":
        return f"{instance_label}{_handle_nickname_command(store, remaining)}"
    if action == "persona":
        return f"{instance_label}{_handle_persona_command(store, config, remaining)}"
    return (
        "用法：/bot runtime set <KEY> <VALUE> | get <KEY> | list | "
        "reset [KEY] | nickname add/remove/list <昵称> | persona list|switch|probability "
        "| instance list（均可加 --instance <名称> 定位实例）"
    )


def _handle_persona_command(
    store: RuntimeSettingsStore,
    config: object,
    parts: list[str],
) -> str:
    from plugins.wuwa_unified_runtime.character.persona_set import build_alt_personas

    alt_personas = build_alt_personas(config)
    if not parts:
        return "用法：/bot runtime persona list | switch <id|default> | probability <id> <0-1>"
    action = parts[0].lower()
    if action == "list":
        lines = [
            f"主人格(A)：{getattr(config, 'wuwa_persona_profile_id', 'default')}"
            f"（{getattr(config, 'wuwa_persona_display_name', '')}）"
        ]
        for spec_id, spec in alt_personas.items():
            lines.append(
                f"备用人格：{spec_id}（{spec.display_name}）"
                f" weight={spec.weight} emotions={','.join(spec.emotions) or '-'}"
            )
        override = store.get_persona_override()
        weights = store.get_persona_weights()
        lines.append(
            "当前覆盖："
            + (override if override else "自动（情绪触发 → 概率 → 主人格）")
        )
        if weights:
            lines.append(
                "概率覆盖："
                + ",".join(f"{k}={v}" for k, v in sorted(weights.items()))
            )
        return "\n".join(lines)
    if action == "switch":
        if len(parts) < 2:
            return "用法：/bot runtime persona switch <id|default>"
        target = parts[1].strip()
        if target != "default" and target not in alt_personas:
            return f"不存在的人格：{target}。可用：default,{','.join(alt_personas)}"
        store.set_persona_override("" if target == "default" else target)
        return (
            f"已强制切换人格：{target}（持续到下一次 switch default）。"
            if target != "default"
            else "已回到自动模式（情绪触发 → 概率 → 主人格）。"
        )
    if action in {"auto", "概率", "probability"}:
        if action == "auto" or len(parts) < 3:
            store.set_persona_override("")
            return "已回到自动模式。"
        spec_id = parts[1].strip()
        if spec_id not in alt_personas:
            return f"不存在的人格：{spec_id}。可用：{','.join(alt_personas)}"
        try:
            weight = float(parts[2])
        except ValueError:
            return "概率必须是 0-1 之间的数字。"
        store.set_persona_weight(spec_id, weight)
        return f"已设置 {spec_id} 的切换概率为 {max(0.0, min(1.0, weight))}。"
    return "用法：/bot runtime persona list | switch <id|default> | probability <id> <0-1>"


def _handle_nickname_command(store: RuntimeSettingsStore, parts: list[str]) -> str:
    if not parts:
        return "用法：/bot runtime nickname add <昵称> | remove <昵称> | list"
    action = parts[0].lower()
    if action == "add":
        if len(parts) < 2:
            return "用法：/bot runtime nickname add <昵称>"
        added = store.add_nickname(parts[1])
        return (
            f"已添加昵称：{parts[1]}。当前昵称：{','.join(store.list_nicknames())}"
            if added
            else f"昵称 {parts[1]} 已存在。当前昵称：{','.join(store.list_nicknames())}"
        )
    if action == "remove":
        if len(parts) < 2:
            return "用法：/bot runtime nickname remove <昵称>"
        removed = store.remove_nickname(parts[1])
        return (
            f"已删除昵称：{parts[1]}。当前昵称：{','.join(store.list_nicknames())}"
            if removed
            else f"昵称 {parts[1]} 不存在。当前昵称：{','.join(store.list_nicknames())}"
        )
    if action == "list":
        nicknames = store.list_nicknames()
        return (
            f"当前昵称：{','.join(nicknames)}"
            if nicknames
            else "当前没有动态昵称（使用 .env 的 BOT_RUNTIME_PERSONA_NICKNAMES）。"
        )
    return "用法：/bot runtime nickname add <昵称> | remove <昵称> | list"


def build_runtime_admin_result(
    manager: InstanceSettingsManager,
    default_instance: str,
    config: object,
    *,
    request_id: str,
    actor_roles: list[str],
    command_text: str,
) -> CapabilityResult:
    if "admin" not in actor_roles:
        return _admin_only_result(request_id)
    try:
        body = _handle_runtime_command(
            manager,
            default_instance,
            config,
            command_text,
        )
    except (ValueError, TypeError) as exc:
        return _error_result(request_id, str(exc))
    return _ok_result(request_id, body)


def build_alert_check_result(
    config: object,
    *,
    request_id: str,
    actor_roles: list[str],
    probe: bool = False,
) -> CapabilityResult:
    if "admin" not in actor_roles:
        return _admin_only_result(request_id)
    try:
        reports = check_credentials_and_report(config, probe=probe)
    except Exception as exc:  # noqa: BLE001 - 检查失败转成安全结果。
        return _error_result(request_id, f"凭据健康检查执行失败：{type(exc).__name__}")
    if not reports:
        return _ok_result(
            request_id,
            "未配置任何凭据引用，无需检查。",
            capability_id="wuwa.alert",
        )
    lines = []
    for report in reports:
        lines.append(
            f"{report.ref_id}：{report.state}"
            + ("（需要重新登录）" if report.needs_reauth else "")
            + f" - {report.detail}"
        )
    return _ok_result(
        request_id,
        "\n".join(lines),
        capability_id="wuwa.alert",
    )

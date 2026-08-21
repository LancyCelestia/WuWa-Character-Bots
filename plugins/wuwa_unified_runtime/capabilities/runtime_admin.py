"""管理员运行时指令：/wuwa runtime ... 与 /wuwa alert check。

在 QQ 对话里直接说命令即可执行，走统一流水线，仅管理员可用：

- ``/wuwa runtime set <KEY> <VALUE>``  调整运行时参数（白名单键）
- ``/wuwa runtime get <KEY>``          查看覆盖值
- ``/wuwa runtime list``               列出全部覆盖
- ``/wuwa runtime reset [KEY]``        清除覆盖（不带 KEY 全部清除）
- ``/wuwa runtime nickname add <昵称>``  添加角色昵称（多昵称）
- ``/wuwa runtime nickname remove <昵称>`` 删除昵称
- ``/wuwa runtime nickname list``      列出昵称
- ``/wuwa alert check``                手动执行凭据健康检查（可加 --probe）

非管理员查询/执行一律拒绝，且不透露任何内部状态。
"""

from __future__ import annotations

from plugins.wuwa_unified_runtime.contracts import (
    CapabilityResult,
    RiskLevel,
    SendPolicy,
)
from plugins.wuwa_unified_runtime.runtime.settings import (
    SETTABLE_KEYS,
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


def _handle_runtime_command(
    store: RuntimeSettingsStore,
    config: object,
    command_text: str,
) -> str:
    parts = command_text.split()
    if not parts:
        return "用法：/wuwa runtime set|get|list|reset|nickname ..."
    action = parts[0].lower()
    if action == "set":
        if len(parts) < 3:
            return "用法：/wuwa runtime set <KEY> <VALUE>"
        key, value = parts[1], " ".join(parts[2:])
        converted = store.set_override(key, value)
        return f"已设置 {key.upper()} = {converted}（本进程生效并已持久化）。"
    if action == "get":
        if len(parts) < 2:
            return "用法：/wuwa runtime get <KEY>"
        key = parts[1].upper()
        if key not in SETTABLE_KEYS:
            return f"不支持查询的键：{key}。可用键：{','.join(sorted(SETTABLE_KEYS))}"
        value = store.get(key, config)
        return f"{key} = {value}" + ("（覆盖值）" if key in store.list_overrides() else "（.env 默认值）")
    if action == "list":
        overrides = store.list_overrides()
        if not overrides:
            return "当前没有运行时覆盖，全部使用 .env 配置。"
        return "\n".join(f"{key} = {value}" for key, value in sorted(overrides.items()))
    if action == "reset":
        key = parts[1] if len(parts) > 1 else None
        count = store.reset_override(key)
        return f"已清除 {count} 项运行时覆盖。"
    if action == "nickname":
        return _handle_nickname_command(store, parts[1:])
    return (
        "用法：/wuwa runtime set <KEY> <VALUE> | get <KEY> | list | "
        "reset [KEY] | nickname add/remove/list <昵称>"
    )


def _handle_nickname_command(store: RuntimeSettingsStore, parts: list[str]) -> str:
    if not parts:
        return "用法：/wuwa runtime nickname add <昵称> | remove <昵称> | list"
    action = parts[0].lower()
    if action == "add":
        if len(parts) < 2:
            return "用法：/wuwa runtime nickname add <昵称>"
        added = store.add_nickname(parts[1])
        return (
            f"已添加昵称：{parts[1]}。当前昵称：{','.join(store.list_nicknames())}"
            if added
            else f"昵称 {parts[1]} 已存在。当前昵称：{','.join(store.list_nicknames())}"
        )
    if action == "remove":
        if len(parts) < 2:
            return "用法：/wuwa runtime nickname remove <昵称>"
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
            else "当前没有动态昵称（使用 .env 的 WUWA_RUNTIME_PERSONA_NICKNAMES）。"
        )
    return "用法：/wuwa runtime nickname add <昵称> | remove <昵称> | list"


def build_runtime_admin_result(
    store: RuntimeSettingsStore,
    config: object,
    *,
    request_id: str,
    actor_roles: list[str],
    command_text: str,
) -> CapabilityResult:
    if "admin" not in actor_roles:
        return _admin_only_result(request_id)
    try:
        body = _handle_runtime_command(store, config, command_text)
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

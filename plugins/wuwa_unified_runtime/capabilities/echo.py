from __future__ import annotations

from pathlib import Path

from plugins.wuwa_unified_runtime.config import Config
from plugins.wuwa_unified_runtime.config_readiness import run_config_smoke
from plugins.wuwa_unified_runtime.contracts import CapabilityResult, PrivacyLevel, RiskLevel, SendPolicy, new_request_id
from plugins.wuwa_unified_runtime.policy.roles import build_role_settings
from plugins.wuwa_unified_runtime.runtime import RuntimeControlState


def build_status_result(
    config: Config | None = None,
    request_id: str | None = None,
    runtime_control: RuntimeControlState | None = None,
) -> CapabilityResult:
    status_config = config or Config()
    return CapabilityResult(
        request_id=request_id or new_request_id("status"),
        capability_id="wuwa.status",
        kind="text",
        title="状态",
        body=_build_status_body(status_config, runtime_control or RuntimeControlState()),
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
        body=(
            "用法：/wuwa status；/wuwa memory add <内容>；"
            "/wuwa memory list；/wuwa memory delete <fact_id>；"
            "/wuwa why [request_id|debug_id]；"
            "/wuwa receipt <request_id|debug_id>；/wuwa audit <request_id>；"
            "/wuwa recent [数量]；/wuwa queue；/wuwa context [测试文本]；"
            "/wuwa llm；/wuwa setup llm；/wuwa config；/wuwa readiness；"
            "/wuwa dialogue [测试文本]；/wuwa roles；/wuwa persona；"
            "/wuwa history clear；/wuwa pause；/wuwa resume；"
            "自动发送草稿：报存 给 A 发消息/邮件，内容..."
        ),
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
    )


def route_wuwa_command(
    command_text: str,
    request_id: str | None = None,
    config: Config | None = None,
    runtime_control: RuntimeControlState | None = None,
) -> CapabilityResult:
    if command_text.strip() == "status":
        return build_status_result(
            config=config,
            request_id=request_id,
            runtime_control=runtime_control,
        )
    return build_help_result(request_id=request_id)


def _build_status_body(config: Config, runtime_control: RuntimeControlState) -> str:
    persona_total, persona_missing = _count_missing_paths(config.wuwa_persona_files)
    knowledge_total, knowledge_missing = _count_missing_paths(config.wuwa_knowledge_files)
    runtime_hard_state = "enabled" if config.wuwa_runtime_enabled else "disabled"
    runtime_soft_paused = str(runtime_control.paused).lower()
    memory_state = "enabled" if config.wuwa_memory_enabled else "disabled"
    memory_db_state = "set" if config.wuwa_memory_db_path else "missing"
    history_state = "enabled" if config.wuwa_history_enabled else "disabled"
    history_db_state = "set" if config.wuwa_history_db_path else "missing"
    diagnostics_state = "enabled" if config.wuwa_diagnostics_enabled else "disabled"
    diagnostics_db_state = "set" if config.wuwa_diagnostics_db_path else "missing"
    audit_state = "enabled" if config.wuwa_audit_enabled else "disabled"
    audit_store = "sqlite" if config.wuwa_audit_enabled and config.wuwa_audit_db_path else "memory"
    audit_db_state = "set" if config.wuwa_audit_db_path else "missing"
    receipts_state = "enabled" if config.wuwa_receipts_enabled else "disabled"
    receipts_store = (
        "sqlite" if config.wuwa_receipts_enabled and config.wuwa_receipts_db_path else "memory"
    )
    receipts_db_state = "set" if config.wuwa_receipts_db_path else "missing"
    send_queue_state = "enabled" if config.wuwa_send_queue_enabled else "disabled"
    send_queue_store = (
        "sqlite"
        if config.wuwa_send_queue_enabled and config.wuwa_send_queue_db_path
        else "memory"
    )
    send_queue_db_state = "set" if config.wuwa_send_queue_db_path else "missing"
    send_queue_worker_state = (
        "enabled" if config.wuwa_send_queue_worker_enabled else "disabled"
    )
    emotion_state = "enabled" if config.wuwa_emotion_enabled else "disabled"
    rate_limit_state = "enabled" if config.wuwa_rate_limit_enabled else "disabled"
    rate_limit_store = "sqlite" if config.wuwa_rate_limit_db_path else "memory"
    rate_limit_db_state = "set" if config.wuwa_rate_limit_db_path else "missing"
    rate_limit_bypass = ",".join(config.wuwa_rate_limit_bypass_roles) or "-"
    quiet_hours_state = "enabled" if config.wuwa_quiet_hours_enabled else "disabled"
    quiet_hours_sessions = ",".join(config.wuwa_quiet_hours_session_types) or "-"
    quiet_hours_bypass = ",".join(config.wuwa_quiet_hours_bypass_roles) or "-"
    chat_state = "enabled" if config.wuwa_chat_enabled else "disabled"
    api_key_state = "set" if config.wuwa_chat_api_key else "missing"
    role_counts = build_role_settings(config).counts()
    llm_readiness = run_config_smoke(config)
    llm_reasons = _format_reason_list(llm_readiness["llm_readiness_reasons"])
    return "\n".join(
        [
            "统一运行时在线",
            f"运行时硬开关：{runtime_hard_state}",
            (
                f"运行时软暂停：{runtime_soft_paused}，"
                f"reason={runtime_control.reason}，"
                f"updated_by={runtime_control.updated_by_state}"
            ),
            (
                "权限角色："
                f"admins={role_counts['admin']}，"
                f"enterprise={role_counts['enterprise']}，"
                f"trusted={role_counts['trusted']}，"
                f"blocked={role_counts['blocked']}"
            ),
            f"人格：{config.wuwa_persona_profile_id} / {config.wuwa_persona_display_name}",
            f"人格版本：{config.wuwa_persona_version}",
            f"人格文件：{persona_total} 个，缺失 {persona_missing} 个",
            f"知识文件：{knowledge_total} 个，缺失 {knowledge_missing} 个",
            f"记忆：{memory_state}，db={memory_db_state}",
            (
                f"最近对话：{history_state}，db={history_db_state}，"
                f"max_turns={config.wuwa_history_max_turns}，"
                f"max_items={config.wuwa_history_max_items}"
            ),
            (
                f"运行诊断：{diagnostics_state}，db={diagnostics_db_state}，"
                f"max_items={config.wuwa_diagnostics_max_items}"
            ),
            (
                f"审计：{audit_state}，store={audit_store}，"
                f"db={audit_db_state}，max_items={config.wuwa_audit_max_items}"
            ),
            (
                f"发送回执：{receipts_state}，store={receipts_store}，"
                f"db={receipts_db_state}，max_items={config.wuwa_receipts_max_items}"
            ),
            (
                f"发送队列：{send_queue_state}，store={send_queue_store}，"
                f"db={send_queue_db_state}，"
                f"max_items={config.wuwa_send_queue_max_items}，"
                f"max_attempts={config.wuwa_send_queue_max_attempts}，"
                f"retry={config.wuwa_send_queue_retry_base_seconds}-"
                f"{config.wuwa_send_queue_retry_max_seconds}s，"
                f"worker={send_queue_worker_state}，"
                f"interval={config.wuwa_send_queue_worker_interval_seconds}s，"
                f"batch={config.wuwa_send_queue_worker_batch_size}"
            ),
            f"情绪感知：{emotion_state}，max_signals={config.wuwa_emotion_max_signals}",
            (
                "回复限速："
                f"{rate_limit_state}，"
                f"store={rate_limit_store}，"
                f"db={rate_limit_db_state}，"
                f"window={config.wuwa_rate_limit_window_seconds}s，"
                f"global={config.wuwa_rate_limit_chat_global_max_requests}，"
                f"session={config.wuwa_rate_limit_chat_session_max_requests}，"
                f"sender={config.wuwa_rate_limit_chat_sender_max_requests}，"
                f"target_min_interval={config.wuwa_rate_limit_target_min_interval_seconds}s，"
                f"bypass={rate_limit_bypass}"
            ),
            (
                "安静时间："
                f"{quiet_hours_state}，"
                f"{config.wuwa_quiet_hours_start}-{config.wuwa_quiet_hours_end}，"
                f"tz={config.wuwa_quiet_hours_timezone}，"
                f"sessions={quiet_hours_sessions}，"
                f"bypass={quiet_hours_bypass}"
            ),
            (
                f"LLM：{config.wuwa_chat_provider}，model={config.wuwa_chat_model}，"
                f"api_key={api_key_state}，chat={chat_state}"
            ),
            (
                f"LLM就绪：{llm_readiness['llm_readiness_status']}，"
                f"ready_for_real_llm={str(bool(llm_readiness['ready_for_real_llm'])).lower()}"
            ),
            f"LLM下一步：{llm_readiness['llm_next_action']}",
            f"LLM原因：{llm_reasons}",
        ]
    )


def _count_missing_paths(paths: list[str]) -> tuple[int, int]:
    total = len(paths)
    missing = sum(1 for path in paths if not Path(path).expanduser().is_file())
    return total, missing


def _format_reason_list(value: object) -> str:
    if not isinstance(value, list):
        return "-"
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return ",".join(cleaned) if cleaned else "-"

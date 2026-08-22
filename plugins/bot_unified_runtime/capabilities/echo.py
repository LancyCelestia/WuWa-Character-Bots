from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.config_readiness import run_config_smoke
from plugins.bot_unified_runtime.contracts import CapabilityResult, PrivacyLevel, RiskLevel, SendPolicy, new_request_id
from plugins.bot_unified_runtime.policy.roles import build_role_settings
from plugins.bot_unified_runtime.runtime import RuntimeControlState


def build_status_result(
    config: Config | None = None,
    request_id: str | None = None,
    runtime_control: RuntimeControlState | None = None,
) -> CapabilityResult:
    status_config = config or Config()
    return CapabilityResult(
        request_id=request_id or new_request_id("status"),
        capability_id="bot.status",
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
        capability_id="bot.help",
        kind="text",
        title="用法",
        body=(
            "用法：/bot status；/bot memory add <内容>；"
            "/bot memory list；/bot memory delete <fact_id>；"
            "/bot why [request_id|debug_id]；"
            "/bot receipt <request_id|debug_id>；/bot audit <request_id>；"
            "/bot recent [数量]；/bot queue；/bot context [测试文本]；"
            "/bot llm；/bot setup llm；/bot config；/bot readiness；"
            "/bot dialogue [测试文本]；/bot roles；/bot persona；"
            "/bot history clear；/bot pause；/bot resume；"
            "/bot subscribe add <链接> [到本群|私聊我] [--digest]；"
            "/bot subscribe list|remove <id>|pause <id>|resume <id>|check <id>|status；"
            "自动发送草稿：报存 给 A 发消息/邮件，内容..."
            "；/点歌 <歌名>；/点歌模式 <音频|语音|链接|卡片>；"
            "；/订阅 添加|列表|删除|暂停|恢复|检查|状态；"
            "昵称命令：守岸人 或 岸宝 作为开头（斜杠可省略），如 守岸人帮助、守岸人查询天气 杭州、/岸宝订阅；"
            "；/订阅 添加|列表|删除|暂停|恢复|检查|状态；"
            "发 B站/抖音/小红书/油管/推特/小黑盒/米游社/森空岛/库街区/"
            "Lofter/无差别同人站/Pixiv 或音乐平台链接自动解析成信息卡；"
            "B站与小红书可订阅新视频/新动态/新笔记/番剧更新/开播推送。"
        ),
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
    )


def route_bot_command(
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
    persona_total, persona_missing = _count_missing_paths(config.bot_persona_files)
    knowledge_total, knowledge_missing = _count_missing_paths(config.bot_knowledge_files)
    runtime_hard_state = "enabled" if config.bot_runtime_enabled else "disabled"
    runtime_soft_paused = str(runtime_control.paused).lower()
    memory_state = "enabled" if config.bot_memory_enabled else "disabled"
    memory_db_state = "set" if config.bot_memory_db_path else "missing"
    history_state = "enabled" if config.bot_history_enabled else "disabled"
    history_db_state = "set" if config.bot_history_db_path else "missing"
    diagnostics_state = "enabled" if config.bot_diagnostics_enabled else "disabled"
    diagnostics_db_state = "set" if config.bot_diagnostics_db_path else "missing"
    audit_state = "enabled" if config.bot_audit_enabled else "disabled"
    audit_store = "sqlite" if config.bot_audit_enabled and config.bot_audit_db_path else "memory"
    audit_db_state = "set" if config.bot_audit_db_path else "missing"
    receipts_state = "enabled" if config.bot_receipts_enabled else "disabled"
    receipts_store = (
        "sqlite" if config.bot_receipts_enabled and config.bot_receipts_db_path else "memory"
    )
    receipts_db_state = "set" if config.bot_receipts_db_path else "missing"
    send_queue_state = "enabled" if config.bot_send_queue_enabled else "disabled"
    send_queue_store = (
        "sqlite"
        if config.bot_send_queue_enabled and config.bot_send_queue_db_path
        else "memory"
    )
    send_queue_db_state = "set" if config.bot_send_queue_db_path else "missing"
    send_queue_worker_state = (
        "enabled" if config.bot_send_queue_worker_enabled else "disabled"
    )
    emotion_state = "enabled" if config.bot_emotion_enabled else "disabled"
    rate_limit_state = "enabled" if config.bot_rate_limit_enabled else "disabled"
    rate_limit_store = "sqlite" if config.bot_rate_limit_db_path else "memory"
    rate_limit_db_state = "set" if config.bot_rate_limit_db_path else "missing"
    rate_limit_bypass = ",".join(config.bot_rate_limit_bypass_roles) or "-"
    quiet_hours_state = "enabled" if config.bot_quiet_hours_enabled else "disabled"
    quiet_hours_sessions = ",".join(config.bot_quiet_hours_session_types) or "-"
    quiet_hours_bypass = ",".join(config.bot_quiet_hours_bypass_roles) or "-"
    chat_state = "enabled" if config.bot_chat_enabled else "disabled"
    api_key_state = "set" if config.bot_chat_api_key else "missing"
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
            f"人格：{config.bot_persona_profile_id} / {config.bot_persona_display_name}",
            f"人格版本：{config.bot_persona_version}",
            f"人格文件：{persona_total} 个，缺失 {persona_missing} 个",
            f"知识文件：{knowledge_total} 个，缺失 {knowledge_missing} 个",
            f"记忆：{memory_state}，db={memory_db_state}",
            (
                f"最近对话：{history_state}，db={history_db_state}，"
                f"max_turns={config.bot_history_max_turns}，"
                f"max_items={config.bot_history_max_items}"
            ),
            (
                f"运行诊断：{diagnostics_state}，db={diagnostics_db_state}，"
                f"max_items={config.bot_diagnostics_max_items}"
            ),
            (
                f"审计：{audit_state}，store={audit_store}，"
                f"db={audit_db_state}，max_items={config.bot_audit_max_items}"
            ),
            (
                f"发送回执：{receipts_state}，store={receipts_store}，"
                f"db={receipts_db_state}，max_items={config.bot_receipts_max_items}"
            ),
            (
                f"发送队列：{send_queue_state}，store={send_queue_store}，"
                f"db={send_queue_db_state}，"
                f"max_items={config.bot_send_queue_max_items}，"
                f"max_attempts={config.bot_send_queue_max_attempts}，"
                f"retry={config.bot_send_queue_retry_base_seconds}-"
                f"{config.bot_send_queue_retry_max_seconds}s，"
                f"worker={send_queue_worker_state}，"
                f"interval={config.bot_send_queue_worker_interval_seconds}s，"
                f"batch={config.bot_send_queue_worker_batch_size}"
            ),
            f"情绪感知：{emotion_state}，max_signals={config.bot_emotion_max_signals}",
            (
                "回复限速："
                f"{rate_limit_state}，"
                f"store={rate_limit_store}，"
                f"db={rate_limit_db_state}，"
                f"window={config.bot_rate_limit_window_seconds}s，"
                f"global={config.bot_rate_limit_chat_global_max_requests}，"
                f"session={config.bot_rate_limit_chat_session_max_requests}，"
                f"sender={config.bot_rate_limit_chat_sender_max_requests}，"
                f"target_min_interval={config.bot_rate_limit_target_min_interval_seconds}s，"
                f"bypass={rate_limit_bypass}"
            ),
            (
                "安静时间："
                f"{quiet_hours_state}，"
                f"{config.bot_quiet_hours_start}-{config.bot_quiet_hours_end}，"
                f"tz={config.bot_quiet_hours_timezone}，"
                f"sessions={quiet_hours_sessions}，"
                f"bypass={quiet_hours_bypass}"
            ),
            (
                f"LLM：{config.bot_chat_provider}，model={config.bot_chat_model}，"
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

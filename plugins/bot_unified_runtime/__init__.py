from __future__ import annotations

from typing import Any

from .audit import AuditRepository, build_audit_repository
from .audit.file_logger import build_audit_with_file_log
from .config import Config, translate_env_keys
from .contracts import (
    AuditRecord,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    PrivacyLevel,
    ReceiptState,
    RiskLevel,
    SendPolicy,
    SendRequest,
    SessionType,
)
from .diagnostics import (
    DiagnosticsStore,
    RuntimeDiagnostic,
    build_diagnostics_store,
    build_runtime_diagnostic,
    build_why_result,
)
from .character import ConversationHistoryRecorder
from .config_readiness import (
    llm_generation_parameter_errors,
    persona_context_preflight_errors,
)
from .llm import LLMProvider, OpenAICompatibleLLMProvider, StaticLLMProvider
from .llm.model_router import build_model_router
from .sender import (
    OneBotV11Bot,
    ReceiptRepository,
    build_receipt_repository,
    drain_send_queue_once,
    send_onebot_v11,
)
from .runtime.aliases import CommandAliasResolver, build_command_alias_resolver
from .runtime.alerts import AlertContent, send_admin_alert
from .runtime.settings import (
    RuntimeSettingsStore,
    build_instance_settings_manager,
    build_runtime_settings_store,
    effective_instance,
)
from .sources.credential_health import check_credentials_and_report
from .sources.meme_search import build_meme_search_provider

try:
    from nonebot.plugin import PluginMetadata
except Exception:

    class PluginMetadata:  # type: ignore[no-redef]
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

__plugin_meta__ = PluginMetadata(
    name="Bot Unified Runtime",
    description="统一角色机器人运行时、人格上下文、媒体解析和发送审计入口",
    usage="/bot status",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11", "~console", "~mail"},
    extra={"milestone": "0"},
)

NO_RUNTIME_DIAGNOSTIC_CAPABILITY_IDS = frozenset(
    {
        "bot.why",
        "bot.receipt",
        "bot.audit",
        "bot.recent",
        "bot.queue",
        "bot.context",
        "bot.llm",
        "bot.setup.llm",
        "bot.config",
        "bot.readiness",
        "bot.dialogue",
        "bot.roles",
        "bot.persona",
        "bot.history",
        "bot.control",
    }
)

OFFLOADED_CAPABILITY_IDS = frozenset(
    {
        "bot.context",
        "bot.llm",
        "bot.dialogue",
    }
)


def _build_chat_llm_provider(config: Config) -> LLMProvider:
    if config.bot_chat_provider == "openai_compatible":
        return OpenAICompatibleLLMProvider(
            api_key=config.bot_chat_api_key,
            model=config.bot_chat_model,
            base_url=config.bot_chat_base_url,
            timeout_seconds=config.bot_chat_timeout_seconds,
        )
    return StaticLLMProvider()


def _is_plain_chat_text(text: str) -> bool:
    from .capabilities.auto_send import is_auto_send_command_text
    from .capabilities.chat import looks_like_chat_text

    stripped = text.strip()
    return looks_like_chat_text(stripped) and not is_auto_send_command_text(stripped)


def _extract_onebot_raw_segments(event: Any) -> list[dict[str, Any]]:
    get_message = getattr(event, "get_message", None)
    message = get_message() if callable(get_message) else getattr(event, "message", ())
    segments: list[dict[str, Any]] = []
    for segment in message or ():
        if isinstance(segment, dict):
            segment_type = segment.get("type", "")
            segment_data = segment.get("data", {})
        else:
            segment_type = getattr(segment, "type", "")
            segment_data = getattr(segment, "data", {})
        if not segment_type:
            continue
        segments.append(
            {
                "type": str(segment_type),
                "data": dict(segment_data) if isinstance(segment_data, dict) else {},
            }
        )
    return segments


def _detect_onebot_direct_mention(
    raw_segments: list[dict[str, Any]],
    bot_id: str,
) -> bool:
    normalized_bot_id = str(bot_id)
    return any(
        segment.get("type") == "at"
        and str(segment.get("data", {}).get("qq", "")) == normalized_bot_id
        for segment in raw_segments
    )


def _incoming_from_nonebot_event(event: Any, bot_id: str = "unknown") -> IncomingMessage:
    text = event.get_plaintext()
    session_id = event.get_session_id()
    session_type = SessionType.GROUP if "group" in session_id else SessionType.PRIVATE
    group_id = getattr(event, "group_id", None)
    message_id = getattr(event, "message_id", None)
    raw_segments = _extract_onebot_raw_segments(event)
    if not raw_segments:
        raw_segments = [{"type": "text", "data": {"text": text}}]
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id=bot_id,
        session_id=session_id,
        session_type=session_type,
        sender_id=event.get_user_id(),
        group_id=str(group_id) if group_id is not None else None,
        plain_text=text,
        raw_segments=raw_segments,
        mentions_bot=(
            session_type is SessionType.PRIVATE
            or _detect_onebot_direct_mention(raw_segments, bot_id)
        ),
        message_id=str(message_id) if message_id is not None else None,
    )


def _transport_audit_event(receipt: DeliveryReceipt) -> str:
    return f"transport_{receipt.state.value}"


def _send_queue_is_drainable(send_queue: Any) -> bool:
    return all(
        hasattr(send_queue, method_name)
        for method_name in (
            "list_due",
            "mark_sent",
            "mark_retryable_failure",
            "mark_final_failure",
        )
    )


def _register_send_queue_scheduler(
    *,
    scheduler: Any,
    config: Config,
    send_queue: Any,
    audit_logger: AuditRepository,
    receipt_repository: ReceiptRepository | None,
    bot_provider: Any,
) -> dict[str, object]:
    if not config.bot_send_queue_worker_enabled:
        return {"registered": False, "reason": "disabled"}
    if not _send_queue_is_drainable(send_queue):
        return {"registered": False, "reason": "queue_not_drainable"}

    interval_seconds = max(1, int(config.bot_send_queue_worker_interval_seconds))
    batch_size = max(1, int(config.bot_send_queue_worker_batch_size))

    async def _queue_worker_job() -> None:
        async def transport(send_request: SendRequest) -> DeliveryReceipt:
            bot = bot_provider()
            if bot is None:
                return DeliveryReceipt(
                    request_id=send_request.request_id,
                    state=ReceiptState.FAILED_RETRYABLE,
                    transport="onebot.v11",
                    public_message="当前没有可用机器人账号，发送队列稍后重试。",
                )
            return await send_onebot_v11(bot, send_request)

        await drain_send_queue_once(
            send_queue,
            transport,
            receipt_repository=receipt_repository,
            audit_logger=audit_logger,
            limit=batch_size,
        )

    scheduler.add_job(
        _queue_worker_job,
        "interval",
        seconds=interval_seconds,
        id="bot_send_queue_worker",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return {
        "registered": True,
        "reason": "registered",
        "interval_seconds": interval_seconds,
        "batch_size": batch_size,
    }


def _register_credential_check_scheduler(
    *,
    scheduler: Any,
    config: Config,
    audit_logger: AuditRepository,
    pipeline: Any,
    bot_provider: Any,
    receipt_repository: ReceiptRepository | None,
    send_queue: Any,
) -> dict[str, object]:
    """开机 + 定时检查 cookie 是否过期/可用；异常时预警管理员。

    预警内容包含：出什么错、影响、怎么解决、时间、位置，通过统一
    流水线私聊 ``BOT_ADMIN_USER_IDS`` 中的管理员。
    """
    interval_hours = max(1, int(getattr(config, "bot_credential_check_interval_hours", 6)))

    async def _check_job() -> None:
        try:
            reports = check_credentials_and_report(config, probe=True)
        except Exception as exc:  # noqa: BLE001 - 检查失败不能中断机器人。
            audit_logger.append(
                AuditRecord(
                    request_id="bot_credential_check",
                    session_id="runtime",
                    capability_id="bot.credential_check",
                    stage="scheduler",
                    event="credential_check_error",
                    severity=RiskLevel.MEDIUM,
                    public_message="凭据健康检查执行失败。",
                    private_debug=repr(exc),
                )
            )
            return
        problems = [report for report in reports if report.needs_reauth]
        audit_logger.append(
            AuditRecord(
                request_id="bot_credential_check",
                session_id="runtime",
                capability_id="bot.credential_check",
                stage="scheduler",
                event=(
                    "credential_reauth_required"
                    if problems
                    else "credential_check_ok"
                ),
                severity=RiskLevel.HIGH if problems else RiskLevel.LOW,
                public_message=(
                    "以下凭据已过期或失效，请重新登录获取："
                    + ",".join(report.ref_id for report in problems)
                    if problems
                    else "凭据健康检查通过。"
                ),
                private_debug=";".join(
                    f"{report.ref_id}:{report.state}" for report in reports
                ),
            )
        )
        if not problems:
            return
        alert = AlertContent(
            title="凭据已过期或失效",
            what_happened="下列凭据已过期或在线探测返回 401/403："
            + ",".join(report.ref_id for report in problems),
            impact="依赖这些凭据的来源抓取、订阅检查将失败或被风控拦截。",
            fix_suggestion="重新登录对应平台，把新 cookie 更新到凭据文件，"
            "再运行 /bot alert check 验证。",
            location="bot.credential_check 定时任务",
            level="warning",
        )
        sent = send_admin_alert(pipeline, list(config.bot_admin_user_ids), alert)
        if sent and bot_provider() is not None:
            for request in list(getattr(send_queue, "sent_requests", []))[-len(sent) :]:
                await _deliver_onebot_send_request(
                    bot_provider(),
                    request,
                    audit_logger,
                    receipt_repository,
                    send_queue,
                )

    scheduler.add_job(
        _check_job,
        "interval",
        hours=interval_hours,
        id="bot_credential_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return {
        "registered": True,
        "reason": "registered",
        "interval_hours": interval_hours,
    }


def _find_sent_request(
    send_queue: Any,
    request_id: str,
) -> SendRequest | None:
    find_request = getattr(send_queue, "find_request", None)
    if callable(find_request):
        found = find_request(request_id)
        if found is not None:
            return found
    return next(
        (
            request
            for request in reversed(send_queue.sent_requests)
            if request.request_id == request_id
        ),
        None,
    )


def _record_runtime_diagnostic(
    *,
    config: Config,
    diagnostics_store: DiagnosticsStore,
    message: IncomingMessage,
    capability_id: str,
    receipt: DeliveryReceipt,
    send_queue: Any,
    audit_logger: AuditRepository,
) -> RuntimeDiagnostic | None:
    if capability_id in NO_RUNTIME_DIAGNOSTIC_CAPABILITY_IDS:
        return None
    diagnostic = build_runtime_diagnostic(
        config,
        message=message,
        capability_id=capability_id,
        receipt=receipt,
        send_request=_find_sent_request(send_queue, message.request_id),
        audit_records=audit_logger.list_records(message.request_id),
    )
    return diagnostics_store.record(diagnostic)


def _record_chat_history_turn(
    recorder: ConversationHistoryRecorder,
    *,
    message: IncomingMessage,
    role: str,
    text: str,
    audit_logger: AuditRepository,
    kind: str = "chat",
) -> None:
    try:
        recorder.append_turn(
            request_id=message.request_id,
            platform=message.platform,
            adapter=message.adapter,
            bot_id=message.bot_id,
            session_id=message.session_id,
            sender_id=message.sender_id,
            role=role,
            text=text,
            kind=kind,
        )
    except Exception as exc:  # noqa: BLE001 - history failure must be observable but non-fatal.
        audit_logger.append(
            AuditRecord(
                request_id=message.request_id,
                session_id=message.session_id,
                capability_id="bot.chat",
                stage="history",
                event="history_record_failed",
                severity=RiskLevel.MEDIUM,
                public_message="对话历史记录失败，但本次回复流程继续。",
                private_debug=f"{type(exc).__name__}: {exc}",
            )
        )


def _should_record_chat_history(send_request: SendRequest) -> bool:
    return not any(
        tag.startswith("prompt_injection") for tag in send_request.audit_tags
    )


def _audit_chat_history_skipped(
    send_request: SendRequest,
    *,
    message: IncomingMessage,
    audit_logger: AuditRepository,
) -> None:
    audit_logger.append(
        AuditRecord(
            request_id=message.request_id,
            session_id=message.session_id,
            capability_id=send_request.capability_id,
            stage="history",
            event="history_record_skipped",
            severity=RiskLevel.MEDIUM,
            public_message="对话历史未记录：输入含提示注入风险。",
            private_debug="reason=prompt_injection",
        )
    )


def _should_silently_skip_chat_receipt(
    message: IncomingMessage,
    receipt: DeliveryReceipt,
    audit_logger: AuditRepository,
) -> bool:
    if message.session_type is not SessionType.GROUP:
        return False
    if receipt.state is not ReceiptState.BLOCKED or receipt.transport != "policy":
        return False
    try:
        records = audit_logger.list_records(message.request_id)
    except Exception:
        return False
    return any(
        record.stage == "policy"
        and record.event == "policy_denied"
        and record.private_debug == "passive_group_message"
        for record in records
    )


async def _deliver_onebot_send_request(
    bot: OneBotV11Bot,
    send_request: SendRequest,
    audit_logger: AuditRepository,
    receipt_repository: ReceiptRepository | None = None,
    send_queue: Any | None = None,
) -> DeliveryReceipt:
    receipt = await send_onebot_v11(bot, send_request)
    if send_queue is not None:
        try:
            if receipt.state.value == "sent" and hasattr(send_queue, "mark_sent"):
                send_queue.mark_sent(send_request.request_id, receipt.public_message)
            elif receipt.state.value == "failed_retryable" and hasattr(
                send_queue,
                "mark_retryable_failure",
            ):
                send_queue.mark_retryable_failure(
                    send_request.request_id,
                    receipt.public_message,
                )
        except Exception as exc:  # noqa: BLE001 - queue status failure must not undo a send.
            audit_logger.append(
                AuditRecord(
                    request_id=send_request.request_id,
                    session_id=send_request.session_id,
                    capability_id=send_request.capability_id,
                    stage="sender",
                    event="send_queue_update_failed",
                    severity=RiskLevel.MEDIUM,
                    public_message="发送队列状态更新失败，但投递流程继续。",
                    private_debug=f"{type(exc).__name__}: {exc}",
                )
            )
    private_debug = f"transport={receipt.transport} state={receipt.state.value}"
    if receipt.provider_message_id:
        private_debug = f"{private_debug} provider_message_id=[internal]"
    audit_logger.append(
        AuditRecord(
            request_id=send_request.request_id,
            session_id=send_request.session_id,
            capability_id=send_request.capability_id,
            stage="transport",
            event=_transport_audit_event(receipt),
            severity=send_request.content.risk_level,
            public_message=receipt.public_message,
            private_debug=private_debug,
        )
    )
    if receipt_repository is not None:
        try:
            receipt_repository.record(receipt)
        except Exception as exc:  # noqa: BLE001 - sending already happened; keep failure observable.
            audit_logger.append(
                AuditRecord(
                    request_id=send_request.request_id,
                    session_id=send_request.session_id,
                    capability_id=send_request.capability_id,
                    stage="receipt",
                    event="receipt_record_failed",
                    severity=RiskLevel.MEDIUM,
                    public_message="发送回执记录失败，但投递流程继续。",
                    private_debug=f"{type(exc).__name__}: {exc}",
                )
            )
    return receipt


async def _run_capability_through_pipeline(
    *,
    bot: OneBotV11Bot,
    event: Any,
    config: Config,
    pipeline: Any,
    send_queue: Any,
    audit_logger: AuditRepository,
    diagnostics_store: DiagnosticsStore,
    capability: Any,
    capability_id: str,
    receipt_repository: ReceiptRepository | None = None,
    record_diagnostic: bool = True,
    offload_sync_capability: bool = False,
    history_recorder: Any | None = None,
    history_kind: str = "command",
) -> DeliveryReceipt:
    message = _incoming_from_nonebot_event(
        event,
        bot_id=str(getattr(bot, "self_id", "unknown")),
    )
    if offload_sync_capability:
        from .runtime import offload_capability

        receipt = await pipeline.handle_async(
            message,
            offload_capability(capability),
            capability_id=capability_id,
        )
    else:
        receipt = pipeline.handle(message, capability, capability_id=capability_id)
    sent_request = _find_sent_request(send_queue, message.request_id)
    if sent_request:
        receipt = await _deliver_onebot_send_request(
            bot,
            sent_request,
            audit_logger,
            receipt_repository,
            send_queue,
        )
    if history_recorder is not None and receipt.state.value == "sent":
        # 命令/被动回复也归档（kind=command），群共享摘要会自动剔除。
        _record_chat_history_turn(
            history_recorder,
            message=message,
            role="user",
            text=message.plain_text,
            audit_logger=audit_logger,
            kind=history_kind,
        )
        if sent_request:
            _record_chat_history_turn(
                history_recorder,
                message=message,
                role="assistant",
                text=sent_request.content.text_fallback,
                audit_logger=audit_logger,
                kind=history_kind,
            )
    if record_diagnostic:
        _record_runtime_diagnostic(
            config=config,
            diagnostics_store=diagnostics_store,
            message=message,
            capability_id=capability_id,
            receipt=receipt,
            send_queue=send_queue,
            audit_logger=audit_logger,
        )
    return receipt


def _register_nonebot_handlers() -> None:
    try:
        from nonebot import get_bots, get_driver, on_command, on_message
        from nonebot.adapters import Bot, Event
        from nonebot.params import CommandArg
        from nonebot.typing import T_State
    except Exception:
        return

    from .capabilities.auto_send import build_auto_send_preview_result, is_auto_send_command_text
    from .capabilities.chat import build_chat_capability
    from .capabilities.debug import (
        build_audit_query_result,
        build_config_query_result,
        build_context_query_result,
        build_dialogue_query_result,
        build_history_clear_result,
        build_llm_query_result,
        build_llm_setup_query_result,
        build_persona_query_result,
        build_queue_query_result,
        build_readiness_query_result,
        build_receipt_query_result,
        build_recent_query_result,
        build_roles_query_result,
        build_runtime_control_result,
    )
    from .capabilities.echo import build_status_result
    from .capabilities.memory import is_memory_command_text, route_memory_command
    from .capabilities.runtime_admin import (
        build_alert_check_result,
        build_runtime_admin_result,
    )
    from .character import build_character_context_provider
    from .character import build_conversation_history_provider
    from .policy import (
        build_quiet_hours_checker,
        build_rate_limiter,
        build_reply_budget_settings,
        build_role_settings,
    )
    from .runtime import RuntimeControlState, RuntimePipeline, offload_capability
    from .sender import build_send_queue

    try:
        driver_config = get_driver().config.model_dump()
    except ValueError as exc:
        if "not been initialized" not in str(exc):
            raise
        return

    config = Config.model_validate(translate_env_keys(driver_config))
    settings_manager = build_instance_settings_manager(config)
    runtime_settings = settings_manager.get(effective_instance(config))
    alias_resolver = build_command_alias_resolver(
        config,
        extra_nicknames=runtime_settings.list_nicknames(),
    )
    audit_logger = build_audit_with_file_log(
        build_audit_repository(config),
        config.bot_audit_log_file,
        max_bytes=config.bot_audit_log_max_bytes,
    )
    receipt_repository = build_receipt_repository(config)
    send_queue = build_send_queue(config, audit_logger=audit_logger)
    diagnostics_store = build_diagnostics_store(config)
    runtime_control = RuntimeControlState()
    pipeline = RuntimePipeline(
        send_queue=send_queue,
        audit_logger=audit_logger,
        reply_budget_settings=build_reply_budget_settings(config),
        role_settings=build_role_settings(config),
        group_command_prefix=config.bot_runtime_group_command_prefix,
        runtime_enabled=config.bot_runtime_enabled,
        receipt_repository=receipt_repository,
        rate_limiter=build_rate_limiter(config),
        quiet_hours_checker=build_quiet_hours_checker(config),
        runtime_control=runtime_control,
        forward_min_chars=config.bot_render_forward_min_chars,
        forward_max_nodes=config.bot_render_forward_max_nodes,
        forward_node_chars=config.bot_render_forward_node_chars,
        alias_command_check=lambda text: (
            alias_resolver.resolve(text) is not None
            or text.startswith(config.bot_runtime_admin_prefix)
        ),
    )

    def _first_online_bot() -> OneBotV11Bot | None:
        try:
            return next(iter(get_bots().values()), None)
        except Exception:
            return None

    try:
        from nonebot_plugin_apscheduler import scheduler
    except Exception as exc:  # noqa: BLE001 - optional worker must fail closed.
        if config.bot_send_queue_worker_enabled:
            audit_logger.append(
                AuditRecord(
                    request_id="bot_send_queue_worker",
                    session_id="runtime",
                    capability_id="bot.send_queue_worker",
                    stage="scheduler",
                    event="send_queue_scheduler_unavailable",
                    severity=RiskLevel.MEDIUM,
                    public_message="发送队列 worker 未注册：APScheduler 插件不可用。",
                    private_debug=f"{type(exc).__name__}: {exc}",
                )
            )
    else:
        _register_send_queue_scheduler(
            scheduler=scheduler,
            config=config,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            bot_provider=_first_online_bot,
        )
        if getattr(config, "bot_credential_check_enabled", False):
            _register_credential_check_scheduler(
                scheduler=scheduler,
                config=config,
                audit_logger=audit_logger,
                pipeline=pipeline,
                bot_provider=_first_online_bot,
                receipt_repository=receipt_repository,
                send_queue=send_queue,
            )

    history_recorder = build_conversation_history_provider(config)
    chat_capability = offload_capability(
        build_chat_capability(
            character_provider=build_character_context_provider(
                config,
                runtime_settings=runtime_settings,
                shared_group_llm_provider=_build_chat_llm_provider(config),
            ),
            llm_provider=_build_chat_llm_provider(config),
            meme_search_provider=build_meme_search_provider(config),
            runtime_settings=runtime_settings,
            interaction_counter=runtime_settings.interaction_increment,
            model_router=build_model_router(config),
            temperature=config.bot_chat_temperature,
            max_tokens=config.bot_chat_max_tokens,
            model=config.bot_chat_model,
            context_preflight_errors=persona_context_preflight_errors(config),
            llm_preflight_errors=llm_generation_parameter_errors(config),
            output_max_chars_per_message=config.bot_reply_max_chars_per_message,
        )
    )

    async def _is_auto_send_plain_text(event: Event) -> bool:
        return is_auto_send_command_text(event.get_plaintext())

    async def _is_plain_chat_event(event: Event) -> bool:
        return config.bot_chat_enabled and _is_plain_chat_text(event.get_plaintext())

    status = on_command(
        "bot",
        aliases={"/bot"},
        force_whitespace=True,
        priority=20,
        block=True,
    )
    auto_send = on_message(rule=_is_auto_send_plain_text, priority=21, block=True)
    chat = on_message(rule=_is_plain_chat_event, priority=50, block=True)

    def _is_alias_command_text(text: str) -> bool:
        return alias_resolver.resolve(text) is not None

    async def _is_alias_command(event: Event) -> bool:
        return _is_alias_command_text(event.get_plaintext())

    alias = on_message(rule=_is_alias_command, priority=19, block=True)

    @alias.handle()
    async def _handle_alias(bot: Bot, event: Event) -> None:
        command_text = event.get_plaintext().strip()
        resolution = alias_resolver.resolve(command_text)
        if resolution is None:
            await alias.finish("无法识别的昵称命令。")
            return
        capability_id = "bot.alias"

        if resolution.capability_id == "bot.help":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                from .capabilities.echo import build_help_result

                return build_help_result(request_id=message.request_id)

        elif resolution.capability_id == "bot.status":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_status_result(
                    config,
                    request_id=message.request_id,
                    runtime_control=runtime_control,
                )

        elif resolution.capability_id == "bot.why":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_why_result(
                    diagnostics_store,
                    request_id=message.request_id,
                    session_id=message.session_id,
                    query=resolution.rest_text,
                )

        else:

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.alias",
                    kind="text",
                    title="昵称命令",
                    body=(
                        f"昵称命令 /{resolution.verb} 请在 /bot 形式下使用："
                        f"/bot {resolution.verb} ..."
                    ),
                    confidence=1.0,
                    risk_level=RiskLevel.LOW,
                    privacy_level=PrivacyLevel.PERSONAL,
                    send_policy=SendPolicy.IMMEDIATE,
                    audit_tags=["alias_command", "alias_unsupported_verb"],
                )

        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            diagnostics_store=diagnostics_store,
            capability=capability,
            capability_id=capability_id,
            record_diagnostic=False,
            history_recorder=history_recorder,
            history_kind="command",
        )
        if receipt.state.value != "sent":
            await alias.finish(receipt.public_message)

    @status.handle()
    async def _handle_status(bot: Bot, event: Event, args=CommandArg()) -> None:
        command_text = args.extract_plain_text().strip()

        if is_memory_command_text(command_text):
            capability_id = "bot.memory"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                memory_db_path = config.bot_memory_db_path if config.bot_memory_enabled else ""
                return route_memory_command(
                    command_text,
                    sender_id=message.sender_id,
                    session_id=message.session_id,
                    db_path=memory_db_path,
                    request_id=message.request_id,
                )

        elif command_text == "why" or command_text.startswith("why "):
            capability_id = "bot.why"
            why_query = command_text.removeprefix("why").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_why_result(
                    diagnostics_store,
                    request_id=message.request_id,
                    session_id=message.session_id,
                    query=why_query,
                )

        elif command_text == "receipt" or command_text.startswith("receipt "):
            capability_id = "bot.receipt"
            receipt_query = command_text.removeprefix("receipt").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_receipt_query_result(
                    receipt_repository,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    query=receipt_query,
                )

        elif command_text == "audit" or command_text.startswith("audit "):
            capability_id = "bot.audit"
            audit_query = command_text.removeprefix("audit").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_audit_query_result(
                    audit_logger,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    query=audit_query,
                )

        elif command_text == "recent" or command_text.startswith("recent "):
            capability_id = "bot.recent"
            recent_query = command_text.removeprefix("recent").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_recent_query_result(
                    diagnostics_store,
                    receipt_repository,
                    audit_logger,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    query=recent_query,
                )

        elif command_text == "queue":
            capability_id = "bot.queue"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_queue_query_result(
                    send_queue,
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                )

        elif command_text == "history clear":
            capability_id = "bot.history"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_history_clear_result(
                    history_recorder,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    platform=message.platform,
                    adapter=message.adapter,
                    bot_id=message.bot_id,
                    session_id=message.session_id,
                    sender_id=message.sender_id,
                )

        elif command_text == "context" or command_text.startswith("context "):
            capability_id = "bot.context"
            context_query = command_text.removeprefix("context").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_context_query_result(
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    sender_id=message.sender_id,
                    session_id=message.session_id,
                    session_type=message.session_type,
                    platform=message.platform,
                    adapter=message.adapter,
                    bot_id=message.bot_id,
                    query=context_query,
                )

        elif command_text == "llm":
            capability_id = "bot.llm"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_llm_query_result(
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                )

        elif command_text == "setup llm":
            capability_id = "bot.setup.llm"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_llm_setup_query_result(
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                )

        elif command_text == "config":
            capability_id = "bot.config"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_config_query_result(
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                )

        elif command_text == "readiness":
            capability_id = "bot.readiness"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_readiness_query_result(
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    runtime_control=runtime_control,
                )

        elif command_text == "dialogue" or command_text.startswith("dialogue "):
            capability_id = "bot.dialogue"
            dialogue_query = command_text.removeprefix("dialogue").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_dialogue_query_result(
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    query=dialogue_query,
                )

        elif command_text == "roles":
            capability_id = "bot.roles"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_roles_query_result(
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                )

        elif command_text == "persona":
            capability_id = "bot.persona"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_persona_query_result(
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                )

        elif command_text == "pause" or command_text == "resume":
            capability_id = "bot.control"
            control_command = command_text

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_runtime_control_result(
                    runtime_control,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    command=control_command,
                    actor_id=message.sender_id,
                )

        elif command_text == "runtime" or command_text.startswith("runtime "):
            capability_id = "bot.runtime"
            runtime_command = command_text.removeprefix("runtime").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_runtime_admin_result(
                    settings_manager,
                    effective_instance(config),
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    command_text=runtime_command,
                )

        elif command_text == "alert" or command_text.startswith("alert "):
            capability_id = "bot.alert"
            alert_command = command_text.removeprefix("alert").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_alert_check_result(
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    probe="--probe" in alert_command,
                )

        elif command_text != "status":
            capability_id = "bot.help"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                from .capabilities.echo import build_help_result

                return build_help_result(request_id=message.request_id)

        else:
            capability_id = "bot.status"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_status_result(
                    config,
                    request_id=message.request_id,
                    runtime_control=runtime_control,
                )

        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            diagnostics_store=diagnostics_store,
            capability=capability,
            capability_id=capability_id,
            record_diagnostic=capability_id not in NO_RUNTIME_DIAGNOSTIC_CAPABILITY_IDS,
            offload_sync_capability=capability_id in OFFLOADED_CAPABILITY_IDS,
            history_recorder=history_recorder,
            history_kind="command",
        )
        if receipt.state.value != "sent":
            await status.finish(receipt.public_message)

    @auto_send.handle()
    async def _handle_auto_send(bot: Bot, event: Event, state: T_State) -> None:
        command_text = event.get_plaintext().strip()

        def capability(message: IncomingMessage, decision: Any) -> CapabilityResult:
            result = build_auto_send_preview_result(
                command_text,
                actor_sender_id=message.sender_id,
                actor_session_id=message.session_id,
                actor_session_type=message.session_type,
                request_id=message.request_id,
            )
            return result.model_copy(
                update={
                    "capability_id": decision.capability_id,
                    "audit_tags": [*decision.audit_tags, *result.audit_tags],
                }
            )

        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            diagnostics_store=diagnostics_store,
            capability=capability,
            capability_id="bot.auto_send.preview",
        )
        state["bot_preview_only"] = True
        if receipt.state.value != "sent":
            await auto_send.finish(receipt.public_message)

    @chat.handle()
    async def _handle_chat(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
        )
        receipt = await pipeline.handle_async(
            message,
            chat_capability,
            capability_id="bot.chat",
        )
        sent_request = _find_sent_request(send_queue, message.request_id)
        history_should_record = False
        if sent_request:
            history_should_record = _should_record_chat_history(sent_request)
            if history_should_record:
                _record_chat_history_turn(
                    history_recorder,
                    message=message,
                    role="user",
                    text=message.plain_text,
                    audit_logger=audit_logger,
                )
            else:
                _audit_chat_history_skipped(
                    sent_request,
                    message=message,
                    audit_logger=audit_logger,
                )
            transport_receipt = await _deliver_onebot_send_request(
                bot,
                sent_request,
                audit_logger,
                receipt_repository,
                send_queue,
            )
            if transport_receipt.state.value == "sent":
                if history_should_record:
                    _record_chat_history_turn(
                        history_recorder,
                        message=message,
                        role="assistant",
                        text=sent_request.content.text_fallback,
                        audit_logger=audit_logger,
                    )
                _record_runtime_diagnostic(
                    config=config,
                    diagnostics_store=diagnostics_store,
                    message=message,
                    capability_id="bot.chat",
                    receipt=transport_receipt,
                    send_queue=send_queue,
                    audit_logger=audit_logger,
                )
                return
            _record_runtime_diagnostic(
                config=config,
                diagnostics_store=diagnostics_store,
                message=message,
                capability_id="bot.chat",
                receipt=transport_receipt,
                send_queue=send_queue,
                audit_logger=audit_logger,
            )
            await chat.finish(transport_receipt.public_message)
        _record_runtime_diagnostic(
            config=config,
            diagnostics_store=diagnostics_store,
            message=message,
            capability_id="bot.chat",
            receipt=receipt,
            send_queue=send_queue,
            audit_logger=audit_logger,
        )
        if _should_silently_skip_chat_receipt(message, receipt, audit_logger):
            return
        await chat.finish(receipt.public_message)


_register_nonebot_handlers()

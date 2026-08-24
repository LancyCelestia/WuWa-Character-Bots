from __future__ import annotations

import asyncio
import re
from typing import Any, cast

from nonebot.adapters import Bot, Event
from nonebot.typing import T_State

from .audit import AuditRepository, build_audit_repository
from .audit.file_logger import build_audit_with_file_log
from .capabilities.content_parser import build_content_capability
from .capabilities.download import build_download_capability
from .capabilities.epic import build_epic_capability
from .capabilities.meme import build_meme_capability
from .capabilities.meme_library import build_meme_library_capability
from .capabilities.music import build_music_capability
from .capabilities.today_history import build_today_history_capability
from .capabilities.weather import build_weather_capability
from .capabilities.wiki import build_wiki_capability
from .character import ConversationHistoryRecorder
from .config import Config, translate_env_keys
from .config_readiness import (
    llm_generation_parameter_errors,
    persona_context_preflight_errors,
)
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
from .llm import LLMProvider, OpenAICompatibleLLMProvider, StaticLLMProvider
from .llm.model_router import build_model_router
from .output.render_backends import build_render_backend
from .runtime.alerts import AlertContent, send_admin_alert
from .runtime.aliases import build_command_alias_resolver
from .runtime.base_router import (
    RouteKind,
    classify_message_route,
    list_route_rules_for_audit,
    looks_like_command_text,
)
from .runtime.mentions import detect_name_mention
from .runtime.natural_language import detect_natural_command
from .runtime.question_intent import looks_like_question_text
from .runtime.settings import (
    build_instance_settings_manager,
    effective_instance,
    normalize_group_policy_mode,
)
from .sender import (
    OneBotV11Bot,
    ReceiptRepository,
    build_receipt_repository,
    drain_send_queue_once,
    send_onebot_v11,
)
from .sources.credential_health import check_credentials_and_report
from .sources.downloader import MediaDownloader
from .sources.meme_library import MemeLibraryStore
from .sources.meme_library_listener import absorb_event_images
from .sources.meme_search import build_meme_search_provider
from .sources.parse_history import (
    build_parse_history_result,
    build_parse_history_store,
)
from .sources.parsers import extract_http_urls
from .sources.web_search import build_web_search_provider

try:
    from nonebot.plugin import PluginMetadata
except Exception:  # noqa: BLE001 - 可选的 NoneBot 插件元数据缺失时使用本地降级实现。

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


_RUNTIME_MENTION_TERMS: list[str] = []


def set_runtime_mention_terms(terms: list[str] | tuple[str, ...]) -> None:
    """在插件初始化时登记人格昵称，用于“只写名字也算点名”。"""
    global _RUNTIME_MENTION_TERMS
    _RUNTIME_MENTION_TERMS = [str(item).strip() for item in terms if str(item).strip()]

def _urls_from_message_segments(raw_segments: list[dict[str, Any]]) -> list[str]:
    """从文本/卡片(json/xml/app)消息段里提取 URL（合并转发与 HTML 卡兜底）。"""
    import json as _json

    urls: list[str] = []
    for segment in raw_segments or []:
        segment_type = str(segment.get("type", ""))
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            continue
        text = ""
        if segment_type == "text":
            text = str(data.get("text", ""))
        elif segment_type in {"json", "xml", "share", "app", "card", "markdown"}:
            for key in ("data", "content", "url", "meta", "text"):
                raw_value = data.get(key)
                if isinstance(raw_value, dict):
                    raw_value = _json.dumps(raw_value, ensure_ascii=False)
                if isinstance(raw_value, str):
                    text += raw_value + " "
        for url in extract_http_urls(text):
            if url not in urls:
                urls.append(url)
    return urls


def _effective_route_text(event: Any) -> str:
    """路由判定文本：纯文本 + 卡片/HTML 段里的链接。"""
    plain = event.get_plaintext().strip()
    try:
        segments = _extract_onebot_raw_segments(event)
    except Exception:  # noqa: BLE001 - 路由段提取失败时降级为纯文本路由。
        segments = []
    urls = _urls_from_message_segments(segments)
    if not urls:
        return plain
    return f"{plain} {' '.join(urls)}".strip()


_FORWARD_MESSAGE_API_TIMEOUT_SECONDS = 10.0


def _forward_segment_id(event: Any) -> str:
    """提取消息中的合并转发（forward）元素 id；非合并转发返回空串。"""
    for segment in _extract_onebot_raw_segments(event):
        if segment.get("type") != "forward":
            continue
        forward_id = str((segment.get("data") or {}).get("id") or "").strip()
        if forward_id:
            return forward_id
    return ""


async def _forward_message_text(bot: Any, event: Any) -> str:
    """读取合并转发（forward）消息正文；失败返回空串。

    只在消息确实包含 forward 段时才调用 NapCat 的 get_forward_msg。
    普通消息 id 不是合并转发 id，NapCat 会拒绝为“消息已过期或者为
    内层消息”；带上限超时是为了防止上游回执异常时卡住消息处理。
    """
    forward_id = _forward_segment_id(event)
    if not forward_id:
        return ""
    try:
        call_api = getattr(bot, "call_api", None)
        if not callable(call_api):
            return ""
        result = await asyncio.wait_for(
            call_api("get_forward_msg", message_id=forward_id),
            timeout=_FORWARD_MESSAGE_API_TIMEOUT_SECONDS,
        )
        if not isinstance(result, dict):
            return ""
        messages = result.get("messages")
        if not isinstance(messages, list):
            return ""
        lines: list[str] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            segments = item.get("message") or item.get("segments") or []
            if not isinstance(segments, list):
                continue
            for segment in segments:
                if isinstance(segment, dict) and segment.get("type") == "text":
                    text = str((segment.get("data") or {}).get("text", "")).strip()
                    if text:
                        lines.append(text)
        return "\n".join(lines)
    except Exception:  # noqa: BLE001 - 合并转发消息读取失败时返回空串。
        return ""


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
            or detect_name_mention(text, _RUNTIME_MENTION_TERMS)
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


def _register_today_history_scheduler(
    *,
    scheduler: Any,
    config: Config,
    pipeline: Any,
    send_queue: Any,
    audit_logger: AuditRepository,
    receipt_repository: ReceiptRepository | None,
    bot_provider: Any,
) -> dict[str, object]:
    """「历史上的今天」每日推送：按订阅表注册 cron 任务，走统一流水线发送。"""
    from .capabilities.today_history import (
        _load_push_table,
        build_today_history_capability,
    )
    from .sources.today_history import TodayHistoryProvider

    push_file = str(
        getattr(config, "bot_today_history_push_file", "data/today_history_push.json")
        or "data/today_history_push.json"
    )
    provider = TodayHistoryProvider(
        proxy=str(getattr(config, "bot_download_proxy", "") or "")
    )

    async def _push(target_key: str) -> None:
        bot = bot_provider()
        if bot is None:
            return
        if target_key.startswith("g_"):
            target_id = target_key[2:]
            session_id = f"group:{target_id}"
            session_type = SessionType.GROUP
            group_id = target_id
            sender_id = "history-push"
        else:
            target_id = target_key[2:]
            session_id = f"private:{target_id}"
            session_type = SessionType.PRIVATE
            group_id = ""
            sender_id = target_id
        message = IncomingMessage(
            platform="onebot",
            adapter="onebot.v11",
            bot_id=str(getattr(bot, "self_id", "unknown")),
            session_id=session_id,
            session_type=session_type,
            sender_id=sender_id,
            group_id=group_id,
            plain_text="历史上的今天",
            raw_segments=[{"type": "text", "data": {"text": "历史上的今天"}}],
            mentions_bot=False,
        )
        from .runtime import offload_capability

        await pipeline.handle_async(
            message,
            offload_capability(capability),
            capability_id="bot.today_history",
        )
        sent_request = _find_sent_request(send_queue, message.request_id)
        if sent_request is not None:
            await _deliver_onebot_send_request(
                bot,
                sent_request,
                audit_logger,
                receipt_repository,
                send_queue,
            )

    def _resync_jobs() -> None:
        try:
            for job in list(scheduler.get_jobs()):
                if str(job.id).startswith("history_push_"):
                    scheduler.remove_job(job.id)
            table = _load_push_table(push_file)
            for key, entry in table.items():
                scheduler.add_job(
                    _push,
                    "cron",
                    args=[key],
                    id=f"history_push_{key}",
                    replace_existing=True,
                    hour=int(entry.get("hour", 8)),
                    minute=int(entry.get("minute", 0)),
                    misfire_grace_time=120,
                    max_instances=1,
                    coalesce=True,
                )
        except Exception:  # noqa: BLE001 - 任务重载失败不影响主链路。
            return

    capability = build_today_history_capability(
        config,
        provider=provider,
        push_file=push_file,
        on_subscriptions_changed=_resync_jobs,
    )

    # 每日 00:30 强制刷新缓存。
    scheduler.add_job(
        lambda: provider.get_events(force=True),
        "cron",
        id="history_cache_refresh",
        replace_existing=True,
        hour=0,
        minute=30,
        misfire_grace_time=300,
    )
    _resync_jobs()
    return {
        "registered": True,
        "push_file": push_file,
        "capability": capability,
        "resync": _resync_jobs,
        "provider": provider,
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
    except Exception:  # noqa: BLE001 - 审计日志查询失败时放行回执而非延误发送。
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
        from nonebot.params import CommandArg
    except Exception:  # noqa: BLE001 - 无 NoneBot 环境时自然跳过注册。
        return

    from .capabilities.auto_send import build_auto_send_preview_result
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
    from .capabilities.runtime_logs import build_logs_query_result
    from .character import (
        build_character_context_provider,
        build_conversation_history_provider,
    )
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
    set_runtime_mention_terms(alias_resolver.nicknames)
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
        group_auto_reply_enabled=config.bot_group_chat_auto_reply_enabled,
        group_auto_reply_probability=config.bot_group_chat_auto_reply_probability,
        group_black1=frozenset(config.bot_group_black1),
        group_black2=frozenset(config.bot_group_black2),
        group_white1=frozenset(config.bot_group_white1),
        group_white2=frozenset(config.bot_group_white2),
        natural_chat_check=looks_like_question_text,
        group_lists_provider=lambda: {
            "black1": frozenset(
                str(item).strip()
                for item in (runtime_settings.get("BOT_GROUP_BLACK1", config) or [])
            ),
            "black2": frozenset(
                str(item).strip()
                for item in (runtime_settings.get("BOT_GROUP_BLACK2", config) or [])
            ),
            "white1": frozenset(
                str(item).strip()
                for item in (runtime_settings.get("BOT_GROUP_WHITE1", config) or [])
            ),
            "white2": frozenset(
                str(item).strip()
                for item in (runtime_settings.get("BOT_GROUP_WHITE2", config) or [])
            ),
        },
        alias_command_check=lambda text: looks_like_command_text(
            text,
            config=config,
            alias_resolver=alias_resolver,
        ),
    )

    def _first_online_bot() -> OneBotV11Bot | None:
        try:
            return next(iter(get_bots().values()), None)
        except Exception:  # noqa: BLE001 - 获取在线 Bot 失败时降级为无可用 Bot。
            return None

    subscription_ctx: dict[str, Any] = {}

    runtime_event_log = None
    if getattr(config, "bot_runtime_log_file", ""):
        try:
            from .sources.runtime_event_log import RuntimeEventLog

            runtime_event_log = RuntimeEventLog(
                str(config.bot_runtime_log_file),
                max_bytes=int(getattr(config, "bot_runtime_log_max_bytes", 2097152)),
                min_level=str(getattr(config, "bot_runtime_log_level", "INFO") or "INFO"),
            )
            runtime_event_log.info(
                "startup",
                stage="nonebot_handlers",
                runtime_instance=str(getattr(config, "bot_runtime_instance", "")),
            )
            driver = get_driver()

            @driver.on_bot_connect
            async def _log_bot_connect(bot):
                runtime_event_log.info(
                    "bot_connected",
                    bot_id=str(getattr(bot, "self_id", "unknown")),
                )

            @driver.on_bot_disconnect
            async def _log_bot_disconnect(bot):
                runtime_event_log.warning(
                    "bot_disconnected",
                    bot_id=str(getattr(bot, "self_id", "unknown")),
                )

            runtime_event_log.attach_to_logging("nonebot")
        except Exception:  # noqa: BLE001 - 日志失败不影响主链路。
            runtime_event_log = None

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
        if getattr(config, "bot_today_history_enabled", True):
            today_ctx = _register_today_history_scheduler(
                scheduler=scheduler,
                config=config,
                pipeline=pipeline,
                send_queue=send_queue,
                audit_logger=audit_logger,
                receipt_repository=receipt_repository,
                bot_provider=_first_online_bot,
            )
        else:
            today_ctx = None

        subscription_ctx = _register_subscription_scheduler(
            scheduler=scheduler,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            bot_provider=_first_online_bot,
            event_log=runtime_event_log,
        )

    history_recorder = build_conversation_history_provider(config)
    parse_history_store = build_parse_history_store(config)
    meme_library_store = (
        MemeLibraryStore(
            str(getattr(config, "bot_meme_library_db_path", "data/meme_library.sqlite3") or ""),
            prefer=list(getattr(config, "bot_meme_library_prefer", []) or []),
        )
        if getattr(config, "bot_meme_library_enabled", False)
        else None
    )
    render_backend = (
        build_render_backend(config.bot_card_render_backend)
        if getattr(config, "bot_card_render_enabled", True)
        else None
    )
    playwright_fetch_backend = None
    if getattr(config, "bot_fetch_playwright_enabled", True):
        try:
            from .sources.fetchers import PlaywrightFetchBackend

            playwright_fetch_backend = PlaywrightFetchBackend()
        except Exception:  # noqa: BLE001 - 抓取兜底失败不影响主链路。
            playwright_fetch_backend = None
    downloader = MediaDownloader(
        cookies_file=str(getattr(config, "bot_cookies_file", "") or ""),
        proxy=str(getattr(config, "bot_download_proxy", "") or ""),
        download_dir=str(getattr(config, "bot_download_dir", "data/downloads") or ""),
        max_bytes=int(getattr(config, "bot_download_max_bytes", 209715200)),
        max_height=int(getattr(config, "bot_download_max_height", 1080)),
        timeout_seconds=int(getattr(config, "bot_download_timeout_seconds", 300)),
        cache_max_bytes=int(getattr(config, "bot_download_cache_max_bytes", 0)),
        cache_max_age_days=int(getattr(config, "bot_download_cache_max_age_days", 0)),
    )
    chat_capability = offload_capability(
        build_chat_capability(
            character_provider=build_character_context_provider(
                config,
                runtime_settings=runtime_settings,
                shared_group_llm_provider=_build_chat_llm_provider(config),
            ),
            llm_provider=_build_chat_llm_provider(config),
            meme_search_provider=build_meme_search_provider(config),
            web_search_provider=build_web_search_provider(config),
            web_max_results=int(config.bot_web_search_max_results),
            web_page_proxy=str(getattr(config, "bot_download_proxy", "") or ""),
            web_page_timeout_seconds=float(
                getattr(config, "bot_web_search_timeout_seconds", 3.0) + 3.0
            ),
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
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.AUTO_SEND
        )

    async def _is_plain_chat_event(event: Event) -> bool:
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.CHAT
        )

    status = on_command(
        "bot",
        aliases={"/bot"},
        force_whitespace=True,
        priority=11,
        block=True,
    )
    auto_send = on_message(rule=_is_auto_send_plain_text, priority=13, block=True)
    chat = on_message(rule=_is_plain_chat_event, priority=50, block=True)
    async def _is_meme_event(event: Event) -> bool:
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.MEME
        )

    async def _is_natural_event(event: Event) -> bool:
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.NATURAL_COMMAND
        )

    meme = on_message(rule=_is_meme_event, priority=20, block=True)
    natural = on_message(rule=_is_natural_event, priority=45, block=True)

    async def _is_meme_library_event(event: Event) -> bool:
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.MEME_LIBRARY
        )

    meme_library = on_message(rule=_is_meme_library_event, priority=22, block=True)

    meme_absorb = on_message(priority=10, block=False)

    @meme_absorb.handle()
    async def _handle_meme_absorb(bot: Bot, event: Event) -> None:
        if meme_library_store is None:
            return
        try:
            await absorb_event_images(bot, event, config, meme_library_store)
        except Exception:  # noqa: BLE001 - 收藏失败不影响消息流。
            return

    async def _is_content_parse_event(event: Event) -> bool:
        return (
            classify_message_route(_effective_route_text(event), config=config).kind
            is RouteKind.CONTENT
        )

    async def _is_music_event(event: Event) -> bool:
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.MUSIC
        )

    async def _is_music_mode_event(event: Event) -> bool:
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.MUSIC_MODE
        )

    async def _is_standalone_subscribe_event(event: Event) -> bool:
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.SUBSCRIBE
        )

    async def _is_today_history_event(event: Event) -> bool:
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.TODAY_HISTORY
        )

    async def _is_wiki_event(event: Event) -> bool:
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.WIKI
        )

    async def _is_epic_event(event: Event) -> bool:
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.EPIC
        )

    async def _is_weather_event(event: Event) -> bool:
        return (
            classify_message_route(event.get_plaintext(), config=config).kind
            is RouteKind.WEATHER
        )

    content = on_message(rule=_is_content_parse_event, priority=46, block=True)
    music_mode = on_message(rule=_is_music_mode_event, priority=40, block=True)
    music = on_message(rule=_is_music_event, priority=41, block=True)
    today_history = on_message(
        rule=_is_today_history_event, priority=41, block=True
    )
    wiki = on_message(rule=_is_wiki_event, priority=41, block=True)
    epic = on_message(rule=_is_epic_event, priority=41, block=True)
    weather = on_message(rule=_is_weather_event, priority=41, block=True)
    subscribe_cmd = on_message(rule=_is_standalone_subscribe_event, priority=12, block=True)

    def _is_alias_command_text(text: str) -> bool:
        return (
            classify_message_route(
                text, config=config, alias_resolver=alias_resolver
            ).kind
            is RouteKind.ALIAS
        )

    async def _is_alias_command(event: Event) -> bool:
        return _is_alias_command_text(event.get_plaintext())

    alias = on_message(rule=_is_alias_command, priority=10, block=True)

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

        elif resolution.capability_id == "bot.weather":
            query = resolution.rest_text

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": f"天气 {query}"})
                return build_weather_capability(config)(synthetic, _decision)

        elif resolution.capability_id == "bot.music":
            query = resolution.rest_text

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": f"点歌 {query}"})
                mode = runtime_settings.get("BOT_MUSIC_MODE", config) or "card"
                return build_music_capability(config, default_mode=mode)(synthetic, _decision)

        elif resolution.capability_id == "bot.wiki":
            query = resolution.rest_text

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": f"wiki {query}"})
                return build_wiki_capability(config)(synthetic, _decision)

        elif resolution.capability_id == "bot.epic":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_epic_capability(config)(message, _decision)

        elif resolution.capability_id == "bot.music_mode":
            from .capabilities.music import build_music_mode_result, extract_music_mode

            mode_value = extract_music_mode(f"点歌模式 {resolution.rest_text}".strip())

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_music_mode_result(
                    runtime_settings,
                    config,
                    mode=mode_value,
                    actor_roles=_decision.actor_roles,
                    request_id=message.request_id,
                )

        elif resolution.capability_id == "bot.today_history":
            query = resolution.rest_text

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(
                    update={"plain_text": f"历史上的今天 {query}".strip()}
                )
                return build_today_history_capability(config)(synthetic, _decision)

        elif resolution.capability_id == "bot.subscribe":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                from .capabilities.subscribe import (
                    build_subscribe_capability,
                    normalize_subscribe_text,
                )

                sub_ctx = subscription_ctx if isinstance(subscription_ctx, dict) else {}
                normalized = normalize_subscribe_text(
                    f"/bot subscribe {resolution.rest_text}".strip()
                )
                synthetic = message.model_copy(update={"plain_text": normalized})
                return build_subscribe_capability(
                    store=sub_ctx.get("store"),
                    registry=sub_ctx.get("registry"),
                    config=config,
                )(synthetic, _decision)

        elif resolution.capability_id == "bot.meme_library":
            from .capabilities.meme_library import build_meme_library_capability

            arg = resolution.rest_text.strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                if meme_library_store is None:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.meme_library",
                        kind="text",
                        body="表情库未启用。",
                        audit_tags=["meme_library", "disabled"],
                    )
                synthetic = message.model_copy(
                    update={"plain_text": f"偷表情 {arg}".strip()}
                )
                if arg.lower() in {"私聊", "私聊我", "private", "私"}:
                    synthetic = synthetic.model_copy(
                        update={"session_type": SessionType.PRIVATE, "group_id": None}
                    )
                return build_meme_library_capability(meme_library_store, config)(
                    synthetic, _decision
                )

        elif resolution.capability_id == "bot.logs":
            parts = resolution.rest_text.split()
            level = "info"
            limit = 50
            allowed_levels = {"info", "warning", "error", "debug"}
            if parts and parts[0].lower() in allowed_levels:
                level = parts[0].lower()
                parts = parts[1:]
            if parts:
                try:
                    limit = max(1, min(200, int(parts[0])))
                except ValueError:
                    limit = 50

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_logs_query_result(
                    runtime_event_log,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    level=level,
                    limit=limit,
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

    @music_mode.handle()
    async def _handle_music_mode(bot: Bot, event: Event) -> None:
        from .capabilities.music import build_music_mode_result, extract_music_mode

        mode = extract_music_mode(event.get_plaintext())

        def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
            return build_music_mode_result(
                runtime_settings,
                config,
                mode=mode,
                actor_roles=_decision.actor_roles,
                request_id=message.request_id,
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
            capability_id="bot.music_mode",
            record_diagnostic=False,
            history_recorder=history_recorder,
            history_kind="command",
        )
        if receipt.state.value != "sent":
            await music_mode.finish(receipt.public_message)

    @subscribe_cmd.handle()
    async def _handle_standalone_subscribe(bot: Bot, event: Event) -> None:
        from .capabilities.subscribe import (
            build_subscribe_capability,
            normalize_subscribe_text,
        )

        sub_ctx = subscription_ctx if isinstance(subscription_ctx, dict) else {}

        def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
            normalized = normalize_subscribe_text(message.plain_text)
            synthetic_message = message.model_copy(update={"plain_text": normalized})
            return build_subscribe_capability(
                store=sub_ctx.get("store"),
                registry=sub_ctx.get("registry"),
                config=config,
            )(synthetic_message, _decision)

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
            capability_id="bot.subscribe",
            record_diagnostic=False,
            history_recorder=history_recorder,
            history_kind="command",
        )
        if receipt.state.value != "sent":
            await subscribe_cmd.finish(receipt.public_message)

    @status.handle()
    async def _handle_status(bot: Bot, event: Event, args=CommandArg()) -> None:  # noqa: B008 - NoneBot 依赖注入要求以 CommandArg() 作为默认参数。

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

        elif command_text == "route" or command_text.startswith("route "):
            capability_id = "bot.route"
            route_query = command_text.removeprefix("route").strip() or ""

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                decision = classify_message_route(
                    route_query, config=config, alias_resolver=alias_resolver
                )
                lines = [
                    "基层路由判定：",
                    f"- 路由：{decision.kind.value}",
                    f"- 能力：{decision.capability_id}",
                    f"- 优先级：{decision.priority}",
                    f"- 理由：{decision.reason}",
                ]
                if decision.target_capability_id:
                    lines.append(f"- 归一化到能力：{decision.target_capability_id}")
                if decision.normalized_text:
                    lines.append(f"- 归一化命令：{decision.normalized_text}")
                body = "\n".join(lines)
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.route",
                    kind="text",
                    title="基层路由",
                    body=body if route_query else "用法：/bot route <要判定的文本>",
                    audit_tags=list(decision.audit_tags),
                )

        elif command_text == "routes" or command_text.startswith("routes "):
            capability_id = "bot.routes"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                rows = list_route_rules_for_audit()
                lines = ["基层路由注册表（优先级从小到大）："]
                for row in rows:
                    lines.append(
                        f"{row['priority']:>3} {row['kind']:<15} "
                        f"{row['capability_id']}  {row['label']}"
                    )
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.routes",
                    kind="text",
                    title="基层路由注册表",
                    body="\n".join(lines),
                    audit_tags=["routes", f"routes:{len(rows)}"],
                )
        elif command_text == "search" or command_text.startswith("search "):
            capability_id = "bot.search"
            search_query = command_text.removeprefix("search").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                roles = {str(role).lower() for role in _decision.actor_roles}
                if "admin" not in roles:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.search",
                        kind="text",
                        body="只有管理员才能使用联网检索调试命令。",
                        audit_tags=["search", "search_denied"],
                    )
                if not search_query:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.search",
                        kind="text",
                        body="用法：/bot search <要检索的现实问题>",
                        audit_tags=["search", "search_missing_query"],
                    )
                provider = build_web_search_provider(config)
                limit = int(getattr(config, "bot_web_search_max_results", 12) or 12)
                try:
                    hits = provider.search(search_query, max_results=limit)
                except Exception:  # noqa: BLE001 - 检索供应商失败时降级为空结果。
                    hits = []
                if not hits:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.search",
                        kind="text",
                        body=(
                            "本次联网检索没有返回结果。\n"
                            "可能原因：检索源不可达、被反爬或代理未生效。\n"
                            f"查询词：{search_query}"
                        ),
                        audit_tags=["search", "search_empty"],
                    )
                lines = ["联网检索结果："]
                for index, hit in enumerate(hits, 1):
                    lines.append(f"{index}. {hit.title}\n   {hit.snippet[:160]}\n   {hit.url}")
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.search",
                    kind="text",
                    title="联网检索",
                    body="\n".join(lines),
                    audit_tags=["search", f"search_hits:{len(hits)}"],
                )

        elif command_text == "parse" or command_text.startswith("parse "):
            capability_id = "bot.parse"
            parse_query = command_text.removeprefix("parse").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_parse_history_result(
                    parse_history_store,
                    request_id=message.request_id,
                    query=parse_query,
                )

        elif command_text == "download" or command_text.startswith("download "):
            capability_id = "bot.download"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return cast(
                    CapabilityResult,
                    build_download_capability(config, downloader=downloader)(
                        message, _decision
                    ),
                )

        elif command_text == "reply" or command_text.startswith("reply "):
            capability_id = "bot.reply"
            reply_mode = command_text.removeprefix("reply").strip().lower()
            mode_map = {
                "详细": "detail", "科普": "detail", "详尽": "detail", "detail": "detail",
                "精简": "concise", "简洁": "concise", "brief": "concise", "concise": "concise",
                "默认": "auto", "自动": "auto", "auto": "auto",
            }
            normalized_mode = mode_map.get(reply_mode, "" if not reply_mode else None)
            if normalized_mode is None:
                normalized_mode = "auto"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                if "admin" not in {str(role).lower() for role in _decision.actor_roles}:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.reply",
                        kind="text",
                        body="只有管理员才能调整回复详略。",
                        audit_tags=["reply_detail", "denied"],
                    )
                if not reply_mode:
                    current = runtime_settings.get("BOT_REPLY_DETAIL", config) or "auto"
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.reply",
                        kind="text",
                        body=(
                            f"当前回复详略：{current}。\n"
                            "用法：/bot reply <详细|精简|默认>"
                        ),
                        audit_tags=["reply_detail", f"current:{current}"],
                    )
                runtime_settings.set_override("BOT_REPLY_DETAIL", normalized_mode)
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.reply",
                    kind="text",
                    body=f"回复详略已设为：{normalized_mode}。",
                    audit_tags=["reply_detail", f"set:{normalized_mode}"],
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

        elif command_text == "subscribe" or command_text.startswith("subscribe "):
            capability_id = "bot.subscribe"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                from .capabilities.subscribe import build_subscribe_capability

                sub_ctx = subscription_ctx if isinstance(subscription_ctx, dict) else {}
                return build_subscribe_capability(
                    store=sub_ctx.get("store"),
                    registry=sub_ctx.get("registry"),
                    config=config,
                )(message, _decision)

        elif command_text == "logs" or command_text.startswith("logs "):
            capability_id = "bot.logs"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                from .capabilities.runtime_logs import build_logs_query_result

                arg_parts = command_text[len("logs"):].strip().split()
                level = (
                    arg_parts[0].lower()
                    if arg_parts and arg_parts[0].lower() in {"debug", "info", "warning", "error"}
                    else "info"
                )
                limit = int(arg_parts[1]) if len(arg_parts) > 1 and arg_parts[1].isdigit() else 50
                return build_logs_query_result(
                    runtime_event_log,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    level=level,
                    limit=limit,
                )

        elif command_text == "group" or command_text.startswith("group "):
            capability_id = "bot.group_policy"
            group_policy_args = command_text.removeprefix("group").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                actor_names = {str(role).lower() for role in _decision.actor_roles}
                if "admin" not in actor_names:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.group_policy",
                        kind="text",
                        body="只有管理员才能调整群聊回复策略。",
                        audit_tags=["group_policy", "denied"],
                    )
                labels = {
                    "BOT_GROUP_BLACK1": "黑名单1（完全静默）",
                    "BOT_GROUP_BLACK2": "黑名单2（仅@+指令）",
                    "BOT_GROUP_WHITE1": "白名单1（指令/点名/自然提问）",
                    "BOT_GROUP_WHITE2": "白名单2（仅@）",
                }
                snapshot = {
                    key: [str(item) for item in (runtime_settings.get(key, config) or [])]
                    for key in labels
                }

                def render(prefix: str) -> CapabilityResult:
                    lines = ["群聊回复策略："]
                    for key, label in labels.items():
                        ids = snapshot[key]
                        lines.append(f"· {label}：{', '.join(ids) if ids else '无'}")
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.group_policy",
                        kind="text",
                        body=prefix + "\n".join(lines),
                        audit_tags=["group_policy"],
                    )

                parts = group_policy_args.split()
                action_raw = parts[0].lower() if parts else ""
                action_aliases = {
                    "add": "add", "加": "add", "加入": "add",
                    "del": "del", "delete": "del", "remove": "del",
                    "删": "del", "移除": "del",
                    "set": "set", "设": "set", "设置": "set",
                    "clear": "clear", "清": "clear", "清空": "clear", "reset": "clear",
                    "list": "list", "show": "list", "查": "list", "查看": "list",
                }
                action = action_aliases.get(action_raw)
                if action in (None, "list"):
                    return render("")
                if len(parts) < 2:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.group_policy",
                        kind="text",
                        body=(
                            "用法：\n"
                            "/bot group [list]\n"
                            "/bot group add <black1|black2|white1|white2> <群号...>\n"
                            "/bot group del <档位> <群号...>\n"
                            "/bot group set <档位> <群号...>\n"
                            "/bot group clear <档位>"
                        ),
                        audit_tags=["group_policy", "usage"],
                    )
                mode_key = normalize_group_policy_mode(parts[1])
                if mode_key is None:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.group_policy",
                        kind="text",
                        body="档位必须是 black1/black2/white1/white2（或 黑1/黑2/白1/白2）。",
                        audit_tags=["group_policy", "bad_mode"],
                    )
                group_ids = [part for part in parts[2:] if part.strip()]
                if any(not part.isdigit() for part in group_ids):
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.group_policy",
                        kind="text",
                        body="群号必须是数字。",
                        audit_tags=["group_policy", "bad_id"],
                    )
                if action in {"add", "del", "set"} and not group_ids:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.group_policy",
                        kind="text",
                        body="请提供至少一个群号。",
                        audit_tags=["group_policy", "missing_id"],
                    )
                current = list(snapshot[mode_key])
                try:
                    if action == "add":
                        merged = list(dict.fromkeys([*current, *group_ids]))
                        runtime_settings.set_override(mode_key, ";".join(merged))
                    elif action == "del":
                        removed = set(group_ids)
                        runtime_settings.set_override(
                            mode_key,
                            ";".join(item for item in current if item not in removed),
                        )
                    elif action == "set":
                        runtime_settings.set_override(mode_key, ";".join(group_ids))
                    else:  # clear
                        runtime_settings.set_override(mode_key, "")
                except ValueError as exc:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.group_policy",
                        kind="text",
                        body=f"设置失败：{exc}",
                        audit_tags=["group_policy", "error"],
                    )
                snapshot[mode_key] = [
                    str(item) for item in (runtime_settings.get(mode_key, config) or [])
                ]
                return render(f"已更新 {labels[mode_key]}。\n")

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
        forward_text = await _forward_message_text(bot, event)
        if forward_text:
            message = message.model_copy(
                update={
                    "plain_text": (
                        f"{message.plain_text}\n【合并转发内容】\n{forward_text}"
                    ).strip()
                }
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

    @content.handle()
    async def _handle_content(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
        )
        segment_urls = _urls_from_message_segments(_extract_onebot_raw_segments(event))
        if segment_urls:
            message = message.model_copy(
                update={
                    "plain_text": (
                        message.plain_text + " " + " ".join(segment_urls)
                    ).strip()
                }
            )
        receipt = await pipeline.handle_async(
            message,
            offload_capability(
                build_content_capability(
                    config,
                    parse_history_store=parse_history_store,
                    downloader=downloader,
                    render_backend=render_backend,
                    card_dir=str(getattr(config, "bot_card_render_dir", "data/cards") or ""),
                    playwright_backend=playwright_fetch_backend,
                )
            ),
            capability_id="bot.content",
        )
        sent_request = _find_sent_request(send_queue, message.request_id)
        if sent_request is not None:
            transport_receipt = await _deliver_onebot_send_request(
                bot,
                sent_request,
                audit_logger,
                receipt_repository,
                send_queue,
            )
            _record_runtime_diagnostic(
                config=config,
                diagnostics_store=diagnostics_store,
                message=message,
                capability_id="bot.content",
                receipt=transport_receipt,
                send_queue=send_queue,
                audit_logger=audit_logger,
            )
            if transport_receipt.state.value == "sent":
                return
            await content.finish(transport_receipt.public_message)
        await content.finish(receipt.public_message)

    @music.handle()
    async def _handle_music(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
        )
        receipt = await pipeline.handle_async(
            message,
            offload_capability(build_music_capability(config, default_mode=runtime_settings.get("BOT_MUSIC_MODE", config) or "card")),
            capability_id="bot.music",
        )
        sent_request = _find_sent_request(send_queue, message.request_id)
        if sent_request is not None:
            transport_receipt = await _deliver_onebot_send_request(
                bot,
                sent_request,
                audit_logger,
                receipt_repository,
                send_queue,
            )
            _record_runtime_diagnostic(
                config=config,
                diagnostics_store=diagnostics_store,
                message=message,
                capability_id="bot.music",
                receipt=transport_receipt,
                send_queue=send_queue,
                audit_logger=audit_logger,
            )
            if transport_receipt.state.value == "sent":
                return
            await music.finish(transport_receipt.public_message)
        await music.finish(receipt.public_message)

    @today_history.handle()
    async def _handle_today_history(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
        )
        capability = (
            today_ctx["capability"]
            if today_ctx is not None
            else build_today_history_capability(config)
        )
        receipt = await pipeline.handle_async(
            message,
            offload_capability(cast(Any, capability)),
            capability_id="bot.today_history",
        )
        sent_request = _find_sent_request(send_queue, message.request_id)
        if sent_request is not None:
            transport_receipt = await _deliver_onebot_send_request(
                bot,
                sent_request,
                audit_logger,
                receipt_repository,
                send_queue,
            )
            _record_runtime_diagnostic(
                config=config,
                diagnostics_store=diagnostics_store,
                message=message,
                capability_id="bot.today_history",
                receipt=transport_receipt,
                send_queue=send_queue,
                audit_logger=audit_logger,
            )
            if transport_receipt.state.value == "sent":
                return
            await today_history.finish(transport_receipt.public_message)
        await today_history.finish(receipt.public_message)

    async def _run_simple_capability(
        bot: Bot,
        event: Event,
        capability_factory: Any,
        capability_id: str,
        matcher: Any,
    ) -> None:
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
        )
        receipt = await pipeline.handle_async(
            message,
            offload_capability(capability_factory(config)),
            capability_id=capability_id,
        )
        sent_request = _find_sent_request(send_queue, message.request_id)
        if sent_request is not None:
            transport_receipt = await _deliver_onebot_send_request(
                bot,
                sent_request,
                audit_logger,
                receipt_repository,
                send_queue,
            )
            _record_runtime_diagnostic(
                config=config,
                diagnostics_store=diagnostics_store,
                message=message,
                capability_id=capability_id,
                receipt=transport_receipt,
                send_queue=send_queue,
                audit_logger=audit_logger,
            )
            if transport_receipt.state.value == "sent":
                return
            await matcher.finish(transport_receipt.public_message)
        await matcher.finish(receipt.public_message)


    @meme.handle()
    async def _handle_meme(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, build_meme_capability, "bot.meme", meme
        )

    @meme_library.handle()
    async def _handle_meme_library(bot: Bot, event: Event) -> None:
        if meme_library_store is None:
            await meme_library.finish("表情库未启用。")
            return
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
        )
        arg = ""
        match = re.match(
            r"^[/!！]?(?:偷表情|偷表情包|表情随机|随机表情|随机表情包|表情抽签|meme random|steal meme)\s*(.*)$",
            message.plain_text,
            re.IGNORECASE,
        )
        if match:
            arg = (match.group(1) or "").strip()
        if arg.lower() in {"私聊", "私聊我", "private", "私"}:
            message = message.model_copy(
                update={"session_type": SessionType.PRIVATE, "group_id": None}
            )
        receipt = await pipeline.handle_async(
            message,
            offload_capability(
                build_meme_library_capability(meme_library_store, config)
            ),
            capability_id="bot.meme_library",
        )
        sent_request = _find_sent_request(send_queue, message.request_id)
        if sent_request is not None:
            transport_receipt = await _deliver_onebot_send_request(
                bot,
                sent_request,
                audit_logger,
                receipt_repository,
                send_queue,
            )
            if transport_receipt.state.value == "sent":
                return
            await meme_library.finish(transport_receipt.public_message)
        await meme_library.finish(receipt.public_message)

    @natural.handle()
    async def _handle_natural(bot: Bot, event: Event) -> None:
        command_text = event.get_plaintext().strip()
        resolution = detect_natural_command(command_text, config)
        if resolution is None:
            await natural.finish("无法识别的自然语言命令。")
            return
        capability_id = resolution.capability_id
        normalized_text = resolution.normalized_text

        if capability_id == "bot.weather":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                return build_weather_capability(config)(synthetic, _decision)

        elif capability_id == "bot.music":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                mode = runtime_settings.get("BOT_MUSIC_MODE", config) or "card"
                return build_music_capability(config, default_mode=mode)(synthetic, _decision)

        elif capability_id == "bot.wiki":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                return build_wiki_capability(config)(synthetic, _decision)

        elif capability_id == "bot.epic":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_epic_capability(config)(message, _decision)

        elif capability_id == "bot.meme_library":
            from .capabilities.meme_library import build_meme_library_capability

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                if meme_library_store is None:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.meme_library",
                        kind="text",
                        body="表情库未启用。",
                        audit_tags=["meme_library", "disabled"],
                    )
                return build_meme_library_capability(meme_library_store, config)(
                    synthetic, _decision
                )

        elif capability_id == "bot.music_mode":
            from .capabilities.music import build_music_mode_result, extract_music_mode

            mode_value = extract_music_mode(normalized_text)

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_music_mode_result(
                    runtime_settings,
                    config,
                    mode=mode_value,
                    actor_roles=_decision.actor_roles,
                    request_id=message.request_id,
                )

        elif capability_id == "bot.today_history":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                return build_today_history_capability(config)(synthetic, _decision)

        else:
            await natural.finish("无法识别的自然语言命令。")
            return

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
            await natural.finish(receipt.public_message)
    @wiki.handle()
    async def _handle_wiki(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, build_wiki_capability, "bot.wiki", wiki
        )

    @epic.handle()
    async def _handle_epic(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, build_epic_capability, "bot.epic", epic
        )

    @weather.handle()
    async def _handle_weather(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, build_weather_capability, "bot.weather", weather
        )





_SUBSCRIPTION_KIND_LABELS = {
    "video": "视频",
    "dynamic": "动态",
    "song": "新歌",
    "illust": "插画",
    "post": "帖子",
    "note": "笔记",
    "live": "直播",
}


def _register_subscription_scheduler(
    *,
    scheduler: Any,
    config: Config,
    pipeline: Any,
    send_queue: Any,
    audit_logger: AuditRepository,
    receipt_repository: ReceiptRepository | None,
    bot_provider: Any,
    registry: Any | None = None,
    event_log: Any | None = None,
) -> dict[str, object]:
    """注册订阅系统三个 APScheduler job：常规轮询、直播轮询、日报汇总。

    config.bot_subscribe_enabled=False 时直接返回空 dict，不触碰调度器。
    """
    if not getattr(config, "bot_subscribe_enabled", True):
        return {}

    from .runtime import offload_capability
    from .sources.parsers import build_cookie_provider
    from .sources.subscription_store import SubscriptionStore
    from .sources.subscription_watcher import build_subscription_watcher
    from .sources.subscriptions import build_subscription_registry

    if registry is None:
        registry = build_subscription_registry()
    cookie_provider = build_cookie_provider(config)
    proxy = str(getattr(config, "bot_download_proxy", "") or "")

    def _ctx_factory(platform: str = "") -> dict[str, str]:
        return {
            "cookie_header": cookie_provider.cookie_header(platform or ""),
            "proxy": proxy,
        }

    store = SubscriptionStore(
        str(
            getattr(config, "bot_subscribe_db_path", "data/subscriptions.sqlite3")
            or "data/subscriptions.sqlite3"
        )
    )
    watcher = build_subscription_watcher(
        store,
        registry.list_adapters(),
        _ctx_factory,
        max_items_per_tick=max(
            1, int(getattr(config, "bot_subscribe_max_items_per_tick", 20))
        ),
    )

    def _capability_for(text: str) -> Any:
        def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.subscribe",
                kind="text",
                body=text,
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["subscription_push"],
            )

        return capability

    def _push_text(candidate: Any, spec: Any) -> str:
        if candidate.reason == "digest_due":
            return (
                f"[订阅] {spec.platform} {spec.target_name} 订阅日报\n"
                f"{candidate.item.summary}"
            )
        label = _SUBSCRIPTION_KIND_LABELS.get(candidate.item.kind, "内容")
        return (
            f"[订阅] {spec.platform} {spec.target_name} 发布新{label}"
            f"《{candidate.item.title}》：{candidate.item.url}"
        )

    async def _deliver_candidates(candidates: list[Any]) -> None:
        if not candidates:
            return
        bot = bot_provider()
        if bot is None:
            return
        for candidate in candidates:
            spec = store.get_spec(candidate.spec_id)
            if spec is None or not spec.destinations:
                continue
            text = _push_text(candidate, spec)
            for destination in spec.destinations:
                if destination.scope == "group":
                    session_id = f"group:{destination.target_id}"
                    session_type = SessionType.GROUP
                    sender_id = "sub-push"
                    group_id = destination.target_id
                else:
                    session_id = f"private:{destination.target_id}"
                    session_type = SessionType.PRIVATE
                    sender_id = destination.target_id
                    group_id = ""
                message = IncomingMessage(
                    platform="onebot",
                    adapter="onebot.v11",
                    bot_id=str(getattr(bot, "self_id", "unknown")),
                    session_id=session_id,
                    session_type=session_type,
                    sender_id=sender_id,
                    group_id=group_id,
                    plain_text=text,
                    raw_segments=[{"type": "text", "data": {"text": text}}],
                    mentions_bot=False,
                )
                try:
                    await pipeline.handle_async(
                        message,
                        offload_capability(_capability_for(text)),
                        capability_id="bot.subscribe",
                    )
                    sent_request = _find_sent_request(send_queue, message.request_id)
                    if sent_request is not None:
                        await _deliver_onebot_send_request(
                            bot,
                            sent_request,
                            audit_logger,
                            receipt_repository,
                            send_queue,
                        )
                    if event_log is not None:
                        event_log.info(
                            "subscription_push_sent",
                            spec_id=str(getattr(spec, "id", "")),
                            platform=str(getattr(spec, "platform", "")),
                            reason=str(getattr(candidate, "reason", "")),
                            destination=str(getattr(destination, "scope", "")),
                        )
                except Exception as exc:  # noqa: BLE001 - 单条推送失败不拖垮轮询。
                    if event_log is not None:
                        event_log.error(
                            "subscription_push_failed",
                            spec_id=str(getattr(spec, "id", "")),
                            error_type=type(exc).__name__,
                        )
                    audit_logger.append(
                        AuditRecord(
                            request_id=message.request_id,
                            session_id=message.session_id,
                            capability_id="bot.subscribe",
                            stage="scheduler",
                            event="subscription_push_failed",
                            severity=RiskLevel.MEDIUM,
                            public_message="订阅推送失败。",
                            private_debug=repr(exc),
                        )
                    )

    async def _watch_job() -> None:
        try:
            candidates = await watcher.tick()
        except Exception as exc:  # noqa: BLE001
            audit_logger.append(
                AuditRecord(
                    request_id="bot_subscribe_watch",
                    session_id="runtime",
                    capability_id="bot.subscribe",
                    stage="scheduler",
                    event="subscription_watch_failed",
                    severity=RiskLevel.MEDIUM,
                    public_message="订阅轮询执行失败。",
                    private_debug=repr(exc),
                )
            )
            return
        await _deliver_candidates(candidates)

    async def _live_job() -> None:
        try:
            candidates = await watcher.live_tick()
        except Exception as exc:  # noqa: BLE001
            audit_logger.append(
                AuditRecord(
                    request_id="bot_subscribe_live",
                    session_id="runtime",
                    capability_id="bot.subscribe",
                    stage="scheduler",
                    event="subscription_live_failed",
                    severity=RiskLevel.MEDIUM,
                    public_message="直播订阅轮询执行失败。",
                    private_debug=repr(exc),
                )
            )
            return
        await _deliver_candidates(candidates)

    async def _digest_job() -> None:
        try:
            candidates = await watcher.flush_digests()
        except Exception as exc:  # noqa: BLE001
            audit_logger.append(
                AuditRecord(
                    request_id="bot_subscribe_digest",
                    session_id="runtime",
                    capability_id="bot.subscribe",
                    stage="scheduler",
                    event="subscription_digest_failed",
                    severity=RiskLevel.MEDIUM,
                    public_message="订阅日报汇总执行失败。",
                    private_debug=repr(exc),
                )
            )
            return
        await _deliver_candidates(candidates)

    scheduler.add_job(
        _watch_job,
        "interval",
        seconds=max(1, int(getattr(config, "bot_subscribe_poll_interval_seconds", 300))),
        id="sub_watch",
        jitter=60,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=120,
        replace_existing=True,
    )
    scheduler.add_job(
        _live_job,
        "interval",
        seconds=max(1, int(getattr(config, "bot_subscribe_live_poll_seconds", 60))),
        id="sub_live",
        jitter=60,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=120,
        replace_existing=True,
    )
    scheduler.add_job(
        _digest_job,
        "cron",
        hour=int(getattr(config, "bot_subscribe_digest_hour", 20)),
        minute=int(getattr(config, "bot_subscribe_digest_minute", 0)),
        id="sub_digest",
        replace_existing=True,
    )

    return {"store": store, "watcher": watcher, "registry": registry}

_register_nonebot_handlers()



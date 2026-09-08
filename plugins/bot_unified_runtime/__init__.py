from __future__ import annotations

import asyncio
import inspect
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebot.adapters.onebot.v11 import NoticeEvent as OneBotNoticeEvent
from nonebot.typing import T_State
from pydantic import BaseModel

from .audit import AuditRepository, build_audit_repository
from .audit.file_logger import build_audit_with_file_log
from .capabilities.content_parser import build_content_capability
from .capabilities.download import build_download_capability
from .capabilities.epic import build_epic_capability
from .capabilities.group_files import DirtyGuard, GroupFileStore
from .capabilities.meme import build_meme_capability
from .capabilities.meme_library import build_meme_library_capability
from .capabilities.music import build_music_capability
from .capabilities.platform_credentials import (
    cookie_status_text,
    import_cookie_header,
    is_cookie_command,
    parse_cookie_command,
)
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
    OperationalIssue,
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
from .message_context import normalize_message_segments
from .output.render_backends import build_render_backend
from .runtime.alerts import (
    AdminAlertSuppression,
    AdminTarget,
    AlertContent,
    build_typed_admin_targets,
    notify_operational_issue,
    send_admin_alert_requests,
)
from .runtime.aliases import build_command_alias_resolver, normalize_command_text
from .runtime.base_router import (
    RouteDecision,
    RouteKind,
    classify_message_route,
    list_route_rules_for_audit,
    looks_like_command_text,
)
from .runtime.disconnect_notice import (
    DisconnectNotifier,
    disconnect_notice_options_from,
)
from .runtime.event_idempotency import build_event_idempotency_table
from .runtime.intent_telemetry import build_intent_telemetry
from .runtime.parrot import ParrotDetector
from .runtime.result_unknown import ResultUnknownLedger


def _runtime_scripts_path(value: str):
    from scripts.runtime_paths import runtime_path

    return runtime_path(value)
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
from .sender.timeout import set_transport_timeout_provider
from .sources.credential_health import check_credentials_and_report
from .sources.downloader import MediaDownloader
from .sources.meme_library import MemeLibraryStore
from .sources.meme_library_listener import absorb_event_images
from .sources.meme_search import build_meme_search_provider
from .sources.music_request_store import MusicRequestStore
from .sources.parse_history import (
    build_parse_history_result,
    build_parse_history_store,
)
from .sources.parsers import (
    build_cookie_provider,
    extract_http_urls,
    music_candidate_providers,
)
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
    supported_adapters={"~onebot.v11", "~console", "~mail", "~telegram"},
    extra={"milestone": "0"},
)

@dataclass(frozen=True)
class OptionalSubscriptionRegistration:
    status: str
    context: dict[str, Any]
    error_kind: str = ""


def defer_optional_subscription_registration(
    register_fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> OptionalSubscriptionRegistration:
    """Keep optional subscription setup from preventing core bot startup."""
    try:
        context = register_fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - optional setup must fail open.
        return OptionalSubscriptionRegistration(
            status="deferred",
            context={},
            error_kind=type(exc).__name__,
        )
    return OptionalSubscriptionRegistration(
        status="enabled",
        context=context if isinstance(context, dict) else {},
    )

NO_RUNTIME_DIAGNOSTIC_CAPABILITY_IDS = frozenset(
    {
        "bot.why",
        "bot.receipt",
        "bot.audit",
        "bot.recent",
        "bot.queue",
        "bot.context",
        "bot.help",
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
        "bot.help",
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
            proxy=config.bot_download_proxy,
        )
    return StaticLLMProvider()


def _build_memory_writer(
    config: Config, model_router: Any | None = None, runtime_settings: Any | None = None,
) -> Any | None:
    """构造回复后的记忆抽取写入器；记忆功能关闭、未配库或无真实 LLM 时返回 None。"""
    if not (
        config.bot_memory_enabled
        and config.bot_memory_extract_enabled
        and str(config.bot_memory_db_path).strip()
    ) or config.bot_chat_provider != "openai_compatible":
        return None
    import logging
    import threading

    from plugins.bot_unified_runtime.character.memory import SQLiteMemoryRepository
    from plugins.bot_unified_runtime.character.memory_extract import (
        extract_memory_texts,
        store_extracted_memories,
    )

    repository = SQLiteMemoryRepository(config.bot_memory_db_path)
    router = model_router if model_router is not None else build_model_router(config)
    worker_lock = threading.Lock()
    cooldown_until = 0.0
    log = logging.getLogger(__name__)

    def setting(key: str, default: Any) -> Any:
        if runtime_settings is not None:
            return runtime_settings.get_or(key, default)
        return default

    def _writer(*, user_text: str, reply_text: str, sender_id: str, session_id: str) -> None:
        nonlocal cooldown_until
        if not setting("BOT_MEMORY_EXTRACT_ENABLED", config.bot_memory_extract_enabled):
            return
        if not worker_lock.acquire(blocking=False):
            return  # Drop optional extraction, never queue an unbounded background workload.
        try:
            if time.monotonic() < cooldown_until:
                return
            provider = router.fork() if callable(getattr(router, "fork", None)) else router
            timeout = float(setting("BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS",
                                    getattr(config, "bot_memory_extract_timeout_seconds", 15.0)))
            texts = extract_memory_texts(
                provider, user_text=user_text, reply_text=reply_text,
                generation_options={
                    "override": str(setting("BOT_CHAT_MODEL", "") or ""),
                    "message_text": user_text,
                    "reasoning_effort": setting("BOT_CHAT_REASONING_EFFORT",
                                                getattr(config, "bot_chat_reasoning_effort", "")),
                    "timeout_seconds": timeout,
                    "deadline_monotonic": time.monotonic() + timeout,
                    "max_tokens": int(setting("BOT_MEMORY_EXTRACT_MAX_TOKENS",
                                              getattr(config, "bot_memory_extract_max_tokens", 200))),
                },
            )
            if texts:
                store_extracted_memories(repository, subject_user_id=sender_id,
                                         session_id=session_id, texts=texts)
        except Exception as exc:  # noqa: BLE001 - optional memory failures must not escape.
            cooldown_until = time.monotonic() + float(setting(
                "BOT_MEMORY_EXTRACT_ERROR_COOLDOWN_SECONDS",
                getattr(config, "bot_memory_extract_error_cooldown_seconds", 300.0)))
            kind = getattr(exc, "error_kind", "")
            safe_kind = kind if kind in {"auth", "timeout", "network", "rate_limited", "config_missing"} else "provider_error"
            log.warning("memory extraction unavailable kind=%s; cooldown active", safe_kind)
        finally:
            worker_lock.release()

    return _writer


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


def _mentioned_by_affinity_nickname(text: str) -> bool:
    """动态好感度小名联动：文本命中任一用户小名即视为被点名。

    小名来自 user_affinity.nickname（管理员/本人设置），数量有限，
    直接全表扫描即可（阻塞读仅群聊判定路径，量级可控）。
    """
    if not text or _AFFINITY_NICKNAMES_CACHE is None:
        return False
    stripped = text.strip()
    lowered = stripped.lower()
    return any(
        nickname and (nickname.lower() in lowered)
        for nickname in _AFFINITY_NICKNAMES_CACHE
    )


_AFFINITY_NICKNAMES_CACHE: list[str] | None = None
_AFFINITY_NICKNAMES_LOADED_AT = 0.0


def _refresh_affinity_nicknames(affinity_store) -> None:
    global _AFFINITY_NICKNAMES_CACHE, _AFFINITY_NICKNAMES_LOADED_AT
    try:
        import sqlite3 as _sq

        connection = _sq.connect(affinity_store.db_path)
        rows = connection.execute(
            "SELECT nickname FROM user_affinity WHERE nickname != ''"
        ).fetchall()
        connection.close()
        _AFFINITY_NICKNAMES_CACHE = [str(r[0]) for r in rows]
        _AFFINITY_NICKNAMES_LOADED_AT = time.time()
    except Exception:  # noqa: BLE001 - 小名加载失败不影响主链路。
        _AFFINITY_NICKNAMES_CACHE = []


def set_runtime_mention_terms(terms: list[str] | tuple[str, ...]) -> None:
    """在插件初始化时登记人格昵称，用于“只写名字也算点名”。"""
    global _RUNTIME_MENTION_TERMS
    _RUNTIME_MENTION_TERMS = [str(item).strip() for item in terms if str(item).strip()]

def contains_visual_message_segments(raw_segments: list[dict[str, Any]] | None) -> bool:
    """Return whether an event contains an image or sticker-like segment."""
    visual_types = {"image", "face", "mface", "marketface", "sticker"}
    return any(
        str(segment.get("type", "")).strip().lower() in visual_types
        for segment in raw_segments or []
    )


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


_ROUTE_DECISION_STATE_KEY = "_bot_unified_route_decision"


def _cached_route_decision(
    state: T_State,
    event: Event,
    *,
    config: Any,
    alias_resolver: Any = None,
    effective_text: bool = False,
) -> RouteDecision:
    """同一事件只做一次路由分类，其余规则直接读缓存。

    一条消息会被十几个 on_message 规则依次检查，每条规则都全量跑一遍
    ROUTE_RULES 注册表；事件级缓存把它们收敛为一次分类，消息量大时能
    省下大量重复的文本/正则判定。NoneBot 为每个事件创建一个共享 state
    字典并传给所有 matcher 的规则，所以缓存随事件自动回收。
    """
    bucket = state.setdefault(_ROUTE_DECISION_STATE_KEY, {})
    key = "effective" if effective_text else "plain"
    decision = bucket.get(key)
    if decision is None:
        text = _effective_route_text(event) if effective_text else event.get_plaintext()
        decision = classify_message_route(
            text, config=config, alias_resolver=alias_resolver
        )
        bucket[key] = decision
    return decision


class _PrivateOfflineFile(BaseModel):
    """offline_file 通知里的 file 对象。

    各 OneBot 实现的字段不一（id / file_id / url / size），全部给默认值，
    保证任何实现都能解析，字段缺失时按空值处理。
    """

    name: str = ""
    size: int = 0
    url: str = ""
    file_id: str = ""
    id: str = ""


class PrivateFileNoticeEvent(OneBotNoticeEvent):
    """OneBot v11 私聊离线文件通知（notice_type=offline_file）。

    官方 nonebot-adapter-onebot 未内置该事件模型（只有 GroupUploadNoticeEvent），
    收到 offline_file 通知只会落到泛化 NoticeEvent。这里补全模型并注册进适配器，
    私聊文件收发（管理员）才能走 file_notice 处理链。
    """

    notice_type: Literal["offline_file"]
    user_id: int
    file: _PrivateOfflineFile

    def get_user_id(self) -> str:
        return str(self.user_id)

    def get_session_id(self) -> str:
        return str(self.user_id)


OneBotV11Adapter.add_custom_model(PrivateFileNoticeEvent)


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


def _log_runtime_event(
    runtime_event_log: Any,
    level: str,
    event: str,
    *,
    message: IncomingMessage | None = None,
    **fields: object,
) -> None:
    """写入跨适配器边界诊断字段；明确禁止正文、密钥和原始异常。"""
    if runtime_event_log is None:
        return
    safe_fields = dict(fields)
    if message is not None:
        safe_fields.update(
            {
                "request_id": message.request_id,
                "adapter": message.adapter,
                "platform": message.platform,
                "bot_id": message.bot_id,
                "session_type": message.session_type.value,
            }
        )
    try:
        runtime_event_log.emit(level, event, **safe_fields)
    except Exception:  # noqa: BLE001 - 诊断日志失败不能影响消息链路。
        return


def _runtime_tag_values(send_request: SendRequest | None) -> dict[str, object]:
    """从已脱敏的发送审计标签中提取路由诊断字段。"""
    if send_request is None:
        return {}
    route_attempts = [
        tag.removeprefix("llm_route_attempt:")[:120]
        for tag in send_request.audit_tags
        if tag.startswith("llm_route_attempt:")
    ]
    model = next(
        (tag.removeprefix("model:")[:120] for tag in send_request.audit_tags if tag.startswith("model:")),
        None,
    )
    error_kind = next(
        (tag.removeprefix("llm_error:")[:80] for tag in send_request.audit_tags if tag.startswith("llm_error:") and tag != "llm_error"),
        None,
    )
    usage_values: dict[str, int] = {}
    for field, prefix in (
        ("prompt_tokens", "llm_usage_prompt_tokens:"),
        ("completion_tokens", "llm_usage_completion_tokens:"),
        ("total_tokens", "llm_usage_total_tokens:"),
        ("cache_read_tokens", "llm_usage_cache_read_tokens:"),
        ("cache_write_tokens", "llm_usage_cache_write_tokens:"),
        ("cost_milli", "llm_usage_cost_milli:"),
    ):
        raw_value = next(
            (tag.removeprefix(prefix) for tag in send_request.audit_tags if tag.startswith(prefix)),
            "0",
        )
        usage_values[field] = int(raw_value) if raw_value.isdecimal() else 0
    result: dict[str, object] = {}
    if route_attempts:
        result["route_attempts"] = "|".join(route_attempts)
    if model:
        result["model"] = model
    if error_kind:
        result["error_kind"] = error_kind
    if usage_values["total_tokens"] > 0:
        result.update(usage_values)
    return result


def _incoming_from_nonebot_event(
    event: Any,
    bot_id: str = "unknown",
    adapter_name: str = "",
) -> IncomingMessage:
    text = event.get_plaintext()
    session_id = event.get_session_id()
    module_name = type(event).__module__.lower()
    normalized_adapter = adapter_name.strip().lower()
    if not normalized_adapter:
        if ".telegram" in module_name:
            normalized_adapter = "telegram"
        elif ".mail" in module_name:
            normalized_adapter = "mail"
        else:
            normalized_adapter = "onebot v11"

    group_id: Any | None = getattr(event, "group_id", None)
    message_id = getattr(event, "message_id", None)
    # Telegram channel posts intentionally do not implement get_user_id().
    # Use sender_chat when present, otherwise the channel/chat id as a stable actor.
    event_user_id = getattr(event, "get_user_id", None)
    sender_id = ""
    if callable(event_user_id):
        try:
            sender_id = str(event_user_id()).strip()
        except Exception:  # noqa: BLE001 - Telegram channel posts expose no user.
            sender_id = ""
    if not sender_id:
        sender_chat = getattr(event, "sender_chat", None)
        sender_id = str(
            getattr(sender_chat, "id", None)
            or getattr(getattr(event, "chat", None), "id", None)
            or "unknown"
        )
    if normalized_adapter == "mail":
        platform = "email"
        adapter = "mail"
        session_type = SessionType.EMAIL
        session_id = f"email:{sender_id}"
        group_id = None
        message_id = getattr(event, "id", message_id)
        subject = str(getattr(event, "subject", "") or "").strip()
        if subject:
            text = f"主题：{subject}\n\n{text}".strip()
    elif normalized_adapter == "telegram":
        platform = "telegram"
        adapter = "telegram"
        if session_id.startswith("channel_"):
            session_type = SessionType.CHANNEL
        elif "group" in session_id:
            session_type = SessionType.GROUP
        else:
            session_type = SessionType.PRIVATE
        chat = getattr(event, "chat", None)
        if session_type in {SessionType.GROUP, SessionType.CHANNEL}:
            group_id = getattr(chat, "id", group_id)
        else:
            group_id = None
    else:
        platform = "qq"
        adapter = "nonebot"
        session_type = (
            SessionType.GROUP if "group" in session_id else SessionType.PRIVATE
        )

    raw_segments = _extract_onebot_raw_segments(event)
    if not raw_segments:
        raw_segments = [{"type": "text", "data": {"text": text}}]
    normalized_message = normalize_message_segments(raw_segments)
    if normalized_message.plain_text.strip():
        text = normalized_message.plain_text
    file_context: list[str] = []
    try:
        from plugins.bot_unified_runtime.sources.file_reader import read_supported_file
        for segment in raw_segments:
            if str(segment.get("type", "")).lower() != "file":
                continue
            data = segment.get("data") or {}
            candidate = str(data.get("file") or data.get("path") or "").strip()
            if candidate:
                parsed_file = read_supported_file(candidate)
                if parsed_file.text:
                    file_context.append(f"[文件内容：{parsed_file.title or parsed_file.path.name}]\n{parsed_file.text}")
    except (ImportError, OSError, ValueError, TypeError):
        file_context = []
    if file_context:
        text = (text + "\n" + "\n".join(file_context)).strip()
    if not text.strip() and contains_visual_message_segments(raw_segments):
        text = "（用户发送了一张图片或表情包。）"
    reply_to = getattr(event, "reply_to", None) or getattr(event, "reply_to_message", None)
    if reply_to is not None:
        if isinstance(reply_to, dict):
            reply_text = str(reply_to.get("text") or reply_to.get("content") or "").strip()
        else:
            getter = getattr(reply_to, "get_plaintext", None)
            reply_text = str(getter() if callable(getter) else getattr(reply_to, "text", "") or "").strip()
    else:
        reply_text = ""
    reply_id = getattr(event, "reply_to_message_id", None) or getattr(event, "reply_to_msg_id", None)
    if reply_id is None:
        quote_segment = next((item for item in normalized_message.segments if item.get("type") == "quote"), None)
        if quote_segment:
            reply_id = (quote_segment.get("data") or {}).get("id") or (quote_segment.get("data") or {}).get("message_id")
    if reply_text:
        text = f"{text}\n[引用回复]\n{reply_text}\n[/引用回复]".strip()
    is_tome = getattr(event, "is_tome", None)
    adapter_mentions_bot = bool(is_tome()) if callable(is_tome) else False
    return IncomingMessage(
        platform=platform,
        adapter=adapter,
        bot_id=bot_id,
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        group_id=str(group_id) if group_id is not None else None,
        plain_text=text,
        raw_segments=normalized_message.segments or raw_segments,
        reply_to_message_id=str(reply_id) if reply_id is not None else None,
        reply_to_text=reply_text or normalized_message.quoted_text,
        thread_id=str(getattr(event, "message_thread_id", "") or "") or None,
        mentions_bot=(
            session_type in {SessionType.PRIVATE, SessionType.EMAIL}
            or adapter_mentions_bot
            or (
                normalized_adapter not in {"telegram", "mail"}
                and _detect_onebot_direct_mention(raw_segments, bot_id)
            )
            or detect_name_mention(text, _RUNTIME_MENTION_TERMS)
            or _mentioned_by_affinity_nickname(text)
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


def _normalize_adapter_name(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if "telegram" in normalized:
        return "telegram"
    if "mail" in normalized:
        return "mail"
    if "onebot" in normalized or normalized in {"nonebot", "qq"}:
        return "onebot"
    if "console" in normalized:
        return "console"
    return normalized


def _bot_adapter_name(bot: Any) -> str:
    adapter = getattr(bot, "adapter", None)
    get_name = getattr(adapter, "get_name", None)
    return _normalize_adapter_name(get_name() if callable(get_name) else getattr(adapter, "name", ""))


def _queue_bot_unavailable_receipt(send_request: SendRequest) -> DeliveryReceipt:
    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.FAILED_RETRYABLE,
        transport="send_queue_worker",
        public_message="",
        operational_issue=OperationalIssue(
            stage="queue",
            kind="bot_unavailable",
            retryable=True,
            safe_summary="bot_unavailable",
        ),
    )


def _select_credential_bot(bots: Any) -> Any | None:
    """Select an online OneBot account without crossing adapter boundaries."""
    candidates = bots.items() if isinstance(bots, dict) else ()
    for _key, candidate in candidates:
        if _bot_adapter_name(candidate) == "onebot":
            return candidate
    return None


def _select_queue_bot(bot_provider: Any, send_request: SendRequest) -> Any | None:
    try:
        provided = bot_provider()
    except Exception:  # noqa: BLE001 - Bot registry lookup must not break the worker.
        return None
    if isinstance(provided, dict):
        candidates = list(provided.items())
    elif provided is None:
        candidates = []
    else:
        candidates = [("", provided)]

    expected_adapter = _normalize_adapter_name(send_request.adapter)
    expected_bot_id = str(send_request.bot_id or "").strip()

    def identity_matches(key: object, bot: Any) -> bool:
        bot_id = str(getattr(bot, "self_id", "") or "").strip()
        key_id = str(key or "").strip()
        return bool(expected_bot_id) and expected_bot_id in {bot_id, key_id}

    if expected_bot_id and expected_bot_id not in {"queued-onebot", "*"}:
        exact = [
            bot
            for key, bot in candidates
            if identity_matches(key, bot)
            and (not expected_adapter or _bot_adapter_name(bot) == expected_adapter)
        ]
        return exact[0] if exact else None
    if expected_bot_id in {"queued-onebot", "*"} and expected_adapter:
        return next(
            (
                bot
                for _key, bot in candidates
                if _bot_adapter_name(bot) == expected_adapter
            ),
            None,
        )

    if expected_adapter:
        matching_adapter = [
            bot for _, bot in candidates if _bot_adapter_name(bot) == expected_adapter
        ]
        if matching_adapter:
            return matching_adapter[0]
        return None

    # 旧队列记录没有 adapter/bot_id：只允许保守回退到 OneBot，避免把旧 QQ
    # 请求误投递到 Telegram 或邮箱。
    return next(
        (bot for _, bot in candidates if _bot_adapter_name(bot) == "onebot"),
        None,
    )


def _register_send_queue_scheduler(
    *,
    scheduler: Any,
    config: Config,
    send_queue: Any,
    audit_logger: AuditRepository,
    receipt_repository: ReceiptRepository | None,
    bot_provider: Any,
    operational_notifier: Any | None = None,
) -> dict[str, object]:
    if not config.bot_send_queue_worker_enabled:
        return {"registered": False, "reason": "disabled"}
    if not _send_queue_is_drainable(send_queue):
        return {"registered": False, "reason": "queue_not_drainable"}

    interval_seconds = max(1, int(config.bot_send_queue_worker_interval_seconds))
    batch_size = max(1, int(config.bot_send_queue_worker_batch_size))

    async def _queue_worker_job() -> None:
        async def transport(send_request: SendRequest) -> DeliveryReceipt:
            bot = _select_queue_bot(bot_provider, send_request)
            if bot is None:
                return _queue_bot_unavailable_receipt(send_request)
            adapter_name = _bot_adapter_name(bot)
            if adapter_name == "onebot":
                return await send_onebot_v11(bot, send_request)
            from .sender.nonebot import send_nonebot_message

            return await send_nonebot_message(bot, None, send_request)

        await drain_send_queue_once(
            send_queue,
            transport,
            receipt_repository=receipt_repository,
            audit_logger=audit_logger,
            limit=batch_size,
            operational_notifier=operational_notifier,
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
        bots = bot_provider()
        bot = _select_credential_bot(bots)
        qq_bot_id = str(getattr(bot, "self_id", "") or "").strip() if bot else ""
        created = send_admin_alert_requests(
            pipeline,
            list(config.bot_admin_user_ids),
            alert,
            qq_bot_id=qq_bot_id or "queued-onebot",
        )
        if bot is None:
            return
        for _admin_id, request_id in created:
            request = _find_sent_request(send_queue, request_id)
            if request is None:
                continue
            await _deliver_onebot_send_request(
                bot,
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
        proxy=str(getattr(config, "bot_download_proxy", "") or ""),
        cache_file=str(
            getattr(config, "bot_today_history_cache_file", "")
            or "data/today_history_cache.json"
        ),
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
            for request in reversed(getattr(send_queue, "sent_requests", []))
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


async def _resolve_bot_avatar_url(bot: Any, config: Config) -> str:
    """Use configured avatar, then ask OneBot/NapCat for the bot avatar briefly."""
    configured = str(getattr(config, "bot_persona_avatar_url", "") or "").strip()
    if configured:
        return configured
    self_id = str(getattr(bot, "self_id", "") or "").strip()
    if not self_id:
        return ""
    # qlogo is the stable public avatar endpoint for a numeric QQ account.  It
    # avoids a placeholder when an adapter omits the avatar field altogether.
    qq_avatar_fallback = (
        f"https://q1.qlogo.cn/g?b=qq&nk={self_id}&s=640"
        if self_id.isdecimal()
        else ""
    )
    getter = getattr(bot, "get_stranger_info", None)
    try:
        if callable(getter):
            result = await asyncio.wait_for(
                getter(user_id=int(self_id) if self_id.isdecimal() else self_id),
                timeout=1.2,
            )
        else:
            call_api = getattr(bot, "call_api", None)
            if not callable(call_api):
                return qq_avatar_fallback
            result = await asyncio.wait_for(
                call_api("get_stranger_info", user_id=int(self_id) if self_id.isdecimal() else self_id),
                timeout=1.2,
            )
    except Exception:  # noqa: BLE001 - cards must not wait on avatar lookup.
        return qq_avatar_fallback
    data = result.get("data", result) if isinstance(result, dict) else {}
    if not isinstance(data, dict):
        return qq_avatar_fallback
    return str(data.get("avatar") or data.get("avatar_url") or data.get("face") or "").strip() or qq_avatar_fallback


def should_finish_nonebot_matcher(receipt: DeliveryReceipt) -> bool:
    """Return whether a NoneBot matcher should emit a fallback message.

    Silent/audited receipts deliberately have no public text. Calling
    ``finish("")`` makes some adapters report ``该消息类型暂不支持查看``.
    """
    if receipt.state in {ReceiptState.SENT, ReceiptState.SKIPPED}:
        return False
    if receipt.operational_issue is not None:
        return False
    return bool(str(receipt.public_message or "").strip())


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
    return _record_transport_receipt(
        receipt,
        send_request,
        audit_logger,
        receipt_repository,
        send_queue,
    )


def _call_queue_state_update(
    send_queue: Any,
    method_name: str,
    request_id: str,
    public_message: str,
    *,
    operational_issue: Any | None,
) -> Any:
    method = getattr(send_queue, method_name)
    try:
        parameters = inspect.signature(method).parameters
        supports_issue = "operational_issue" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
    except (TypeError, ValueError):
        supports_issue = False
    kwargs: dict[str, object] = {}
    if supports_issue:
        kwargs["operational_issue"] = operational_issue
    return method(request_id, public_message, **kwargs)


def _record_transport_receipt(
    receipt: DeliveryReceipt,
    send_request: SendRequest,
    audit_logger: AuditRepository,
    receipt_repository: ReceiptRepository | None = None,
    send_queue: Any | None = None,
) -> DeliveryReceipt:
    issue = receipt.operational_issue or send_request.operational_issue
    if issue is not None:
        receipt = receipt.model_copy(update={"public_message": "", "operational_issue": issue})
    if send_queue is not None:
        try:
            if receipt.state.value == "sent" and hasattr(send_queue, "mark_sent"):
                _call_queue_state_update(
                    send_queue,
                    "mark_sent",
                    send_request.request_id,
                    receipt.public_message,
                    operational_issue=issue,
                )
            elif receipt.state.value == "failed_retryable" and hasattr(
                send_queue,
                "mark_retryable_failure",
            ):
                _call_queue_state_update(
                    send_queue,
                    "mark_retryable_failure",
                    send_request.request_id,
                    receipt.public_message,
                    operational_issue=issue,
                )
            elif receipt.state.value == "failed_final" and hasattr(
                send_queue,
                "mark_final_failure",
            ):
                _call_queue_state_update(
                    send_queue,
                    "mark_final_failure",
                    send_request.request_id,
                    receipt.public_message,
                    operational_issue=issue,
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
                    private_debug=type(exc).__name__,
                )
            )
    if receipt.operational_issue is not None:
        receipt = receipt.model_copy(update={"public_message": ""})
    private_debug = f"transport={receipt.transport} state={receipt.state.value}"
    if receipt.operational_issue is not None:
        issue = receipt.operational_issue
        private_debug = (
            f"{private_debug} stage={issue.stage} kind={issue.kind} "
            f"retryable={str(issue.retryable).lower()} debug_id={issue.debug_id}"
        )
    elif receipt.provider_message_id:
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
                    private_debug=type(exc).__name__,
                )
            )
    return receipt


async def _deliver_transport_send_request(
    bot: Any,
    event: Any,
    send_request: SendRequest,
    audit_logger: AuditRepository,
    receipt_repository: ReceiptRepository | None = None,
    send_queue: Any | None = None,
) -> DeliveryReceipt:
    from .sender.gateway import UnifiedDeliveryGateway
    from .sender.nonebot import send_nonebot_message

    async def _record(receipt: DeliveryReceipt, request: SendRequest) -> DeliveryReceipt:
        return _record_transport_receipt(
            receipt,
            request,
            audit_logger,
            receipt_repository,
            send_queue,
        )

    gateway = UnifiedDeliveryGateway(
        onebot_sender=send_onebot_v11,
        nonebot_sender=send_nonebot_message,
        record_receipt=_record,
    )
    return await gateway.deliver(bot, event, send_request)
async def _notify_operational_callback(
    notifier: Any,
    message: IncomingMessage,
    receipt: DeliveryReceipt,
) -> None:
    if notifier is None or receipt.operational_issue is None:
        return
    try:
        try:
            parameters = inspect.signature(notifier).parameters
            positional = [
                parameter
                for parameter in parameters.values()
                if parameter.kind
                in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                }
            ]
            accepts_varargs = any(
                parameter.kind is inspect.Parameter.VAR_POSITIONAL
                for parameter in parameters.values()
            )
        except (TypeError, ValueError):
            positional = []
            accepts_varargs = True
        value = (
            notifier(message, receipt)
            if accepts_varargs or len(positional) >= 2
            else notifier(receipt)
        )
        if inspect.isawaitable(value):
            await value
    except Exception:  # noqa: BLE001 - operational alerting is best effort.
        return


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
    operational_notifier: Any | None = None,
) -> DeliveryReceipt:
    from .runtime.ingress import IngressGateway
    message = IngressGateway(_incoming_from_nonebot_event).from_event(
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
    # Preserve and notify a capability/pipeline issue before any successful
    # transport receipt can replace it. The notifier is a side channel only.
    await _notify_operational_callback(operational_notifier, message, receipt)
    sent_request = _find_sent_request(send_queue, message.request_id)
    if sent_request:
        delivered = _deliver_transport_send_request(
            bot,
            event,
            sent_request,
            audit_logger,
            receipt_repository,
            send_queue,
        )
        receipt = await delivered if inspect.isawaitable(delivered) else delivered
        await _notify_operational_callback(operational_notifier, message, receipt)
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


def _affinity_store_runtime(store_config: object):
    return (
        build_character_affinity_store(store_config)
        if getattr(store_config, "bot_affinity_enabled", True)
        else None
    )


def build_character_affinity_store(config: object):
    from .character.affinity import DynamicAffinityStore
    from .character.providers import build_runtime_data_path

    if not getattr(config, "bot_affinity_enabled", True):
        return None
    return DynamicAffinityStore(
        build_runtime_data_path(
            config, str(getattr(config, "bot_affinity_db_path", "data/user_affinity.sqlite3"))
        )
    )


def _register_nonebot_handlers() -> None:
    try:
        from nonebot import (
            get_bots,
            get_driver,
            on_command,
            on_message,
            on_notice,
        )
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
    from .capabilities.echo import build_status_result, resolve_help_query
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
    from .mail_bridge import (
        MailBridgeState,
        build_mail_notification,
        execute_mail_command,
        is_telegram_admin,
        mail_event_dedupe_id,
        notify_telegram_admins,
        parse_mail_command,
        unresolved_mail_aliases,
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
    music_request_store = (
        MusicRequestStore(
            str(
                getattr(
                    config,
                    "bot_music_analytics_db_path",
                    "data/music_analytics.sqlite3",
                )
                or "data/music_analytics.sqlite3"
            ),
            retention_days=int(
                getattr(config, "bot_music_analytics_retention_days", 365)
            ),
        )
        if bool(getattr(config, "bot_music_analytics_enabled", True))
        else None
    )
    settings_manager = build_instance_settings_manager(config)
    runtime_settings = settings_manager.get(effective_instance(config))
    # 发送层硬超时：每次发送时读 runtime 覆盖（mtime 热重载），未覆盖时回落 .env 配置。
    set_transport_timeout_provider(
        lambda: float(runtime_settings.get("BOT_TRANSPORT_TIMEOUT_SECONDS", config) or 15.0)
    )
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
    mail_bridge_state = MailBridgeState(config.bot_mail_bridge_state_file)
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
        vision_reply_probability=float(
            getattr(config, "bot_vision_reply_probability", 1.0)
        ),
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
        idempotency_table=build_event_idempotency_table(
            enabled=bool(getattr(config, "bot_event_idempotency_enabled", False)),
            db_path=getattr(config, "bot_event_idempotency_db_path", "") or None,
            ttl_seconds=float(config.bot_event_idempotency_ttl_seconds),
            max_entries=int(config.bot_event_idempotency_max_entries),
        ),
    )

    def _all_online_bots() -> dict[str, Any]:
        try:
            return dict(get_bots())
        except Exception:  # noqa: BLE001 - 获取在线 Bot 失败时降级为空注册表。
            return {}

    def _first_online_bot() -> OneBotV11Bot | None:
        return next(iter(_all_online_bots().values()), None)

    operational_alert_suppression = AdminAlertSuppression()

    result_unknown_ledger = ResultUnknownLedger(
        _runtime_scripts_path("data/result_unknown.sqlite3")
    )

    group_file_store = GroupFileStore(_runtime_scripts_path("data/group_files.sqlite3"))
    dirty_guard = DirtyGuard(
        delete_enabled=bool(getattr(config, "bot_dirty_guard_delete", False))
    )
    parrot_detector = ParrotDetector(
        threshold=max(2, int(getattr(config, "bot_parrot_threshold", 3))),
        window_seconds=float(getattr(config, "bot_parrot_window_seconds", 60.0)),
        cooldown_seconds=float(getattr(config, "bot_parrot_cooldown_seconds", 300.0)),
    )

    def _admin_bot_id(adapter: str) -> str:
        for key, candidate in _all_online_bots().items():
            if _bot_adapter_name(candidate) != adapter:
                continue
            return str(getattr(candidate, "self_id", "") or key).strip()
        return ""

    def _operational_alert_targets() -> list[AdminTarget]:
        return build_typed_admin_targets(
            qq_admin_ids=list(config.bot_admin_user_ids),
            telegram_user_ids=list(config.bot_telegram_admin_user_ids),
            telegram_chat_ids=list(config.bot_telegram_admin_chat_ids),
            qq_bot_id=_admin_bot_id("onebot"),
            telegram_bot_id=_admin_bot_id("telegram"),
        ) if _admin_bot_id("onebot") or _admin_bot_id("telegram") else []

    async def _deliver_admin_alert(
        target: AdminTarget,
        bot: Any,
        request: SendRequest,
    ) -> DeliveryReceipt:
        if target.adapter == "onebot":
            return await send_onebot_v11(bot, request)
        from .sender.nonebot import send_nonebot_message

        return await send_nonebot_message(bot, None, request)

    async def _notify_operational_receipt(
        message: IncomingMessage,
        receipt: DeliveryReceipt,
    ) -> None:
        if "admin_alert" in getattr(message, "sender_roles", ()):
            return
        issue = receipt.operational_issue
        if issue is None:
            return
        if getattr(issue, "kind", "") == "result_unknown":
            result_unknown_ledger.record(
                request_id=receipt.request_id,
                adapter=str(getattr(message, "adapter", "")),
                bot_id=str(getattr(message, "bot_id", "")),
                session_type=str(getattr(message, "session_type", "")),
                session_id=str(getattr(message, "session_id", "")),
            )
        targets = _operational_alert_targets()
        if not targets:
            return
        try:
            await notify_operational_issue(
                issue,
                source_adapter=message.adapter,
                source_bot=message.bot_id,
                session_type=message.session_type,
                targets=targets,
                online_bots=_all_online_bots,
                delivery=_deliver_admin_alert,
                suppression=operational_alert_suppression,
            )
        except Exception:  # noqa: BLE001 - admin alert side channel is best effort.
            # Administrator alerting is a diagnostic side channel and must never
            # alter or recursively re-enter the originating request.
            return

    async def _notify_queue_operational_receipt(
        request: SendRequest,
        receipt: DeliveryReceipt,
    ) -> None:
        if "admin_alert" in request.audit_tags:
            return
        issue = receipt.operational_issue
        if issue is None:
            return
        targets = _operational_alert_targets()
        if not targets:
            return
        try:
            await notify_operational_issue(
                issue,
                source_adapter=request.adapter,
                source_bot=request.bot_id,
                session_type=request.target_scope,
                targets=targets,
                online_bots=_all_online_bots,
                delivery=_deliver_admin_alert,
                suppression=operational_alert_suppression,
            )
        except Exception:  # noqa: BLE001 - queue alerting is nonblocking and best effort.
            return

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
                try:
                    summary = result_unknown_ledger.reconcile(
                        bot_id=str(getattr(bot, "self_id", "unknown"))
                    )
                except Exception:  # noqa: BLE001 - 对账失败不影响重连。
                    summary = None
                if summary is not None and (summary.pending or summary.expired):
                    runtime_event_log.warning(
                        "result_unknown_reconciled",
                        pending=summary.pending,
                        expired=summary.expired,
                        detail=summary.render(),
                    )
                unresolved = unresolved_mail_aliases(
                    _all_online_bots(),
                    config.bot_mail_sender_aliases,
                )
                if unresolved:
                    runtime_event_log.warning(
                        "mail_alias_target_not_connected",
                        aliases=unresolved,
                    )

            disconnect_notifier = DisconnectNotifier(disconnect_notice_options_from(config))

            @driver.on_bot_disconnect
            async def _log_bot_disconnect(bot):
                bot_id = str(getattr(bot, "self_id", "unknown"))
                runtime_event_log.warning(
                    "bot_disconnected",
                    bot_id=bot_id,
                )
                try:
                    delivered = await disconnect_notifier.notify(
                        _all_online_bots(), bot_id=bot_id
                    )
                except Exception:  # noqa: BLE001 - 通知失败不影响断线记录。
                    return
                if delivered:
                    runtime_event_log.warning(
                        "disconnect_notice_sent",
                        bot_id=bot_id,
                        channels=delivered,
                    )

            runtime_event_log.attach_to_logging("nonebot")
        except Exception:  # noqa: BLE001 - 日志失败不影响主链路。
            runtime_event_log = None

    # 订阅推送与解析卡共用渲染后端：必须在订阅调度器注册之前构建。
    render_backend = (
        build_render_backend(config.bot_card_render_backend)
        if getattr(config, "bot_card_render_enabled", True)
        else None
    )

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
                    private_debug=type(exc).__name__,
                )
            )
    else:
        _register_send_queue_scheduler(
            scheduler=scheduler,
            config=config,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            bot_provider=_all_online_bots,
            operational_notifier=_notify_queue_operational_receipt,
        )
        if getattr(config, "bot_credential_check_enabled", False):
            _register_credential_check_scheduler(
                scheduler=scheduler,
                config=config,
                audit_logger=audit_logger,
                pipeline=pipeline,
                bot_provider=_all_online_bots,
                receipt_repository=receipt_repository,
                send_queue=send_queue,
            )
        from plugins.bot_unified_runtime.runtime.model_schedule import (
            _register_model_schedule_scheduler,
        )

        _register_model_schedule_scheduler(
            scheduler=scheduler,
            config=config,
            settings_store=runtime_settings,
        )
        if runtime_event_log is not None:
            from plugins.bot_unified_runtime.runtime.usage_monitor import (
                register_usage_monitor_scheduler,
            )

            register_usage_monitor_scheduler(
                scheduler=scheduler,
                config=config,
                pipeline=pipeline,
                usage_log=runtime_event_log,
                admin_ids=[
                    str(admin_id).strip()
                    for admin_id in (
                        list(getattr(config, "bot_admin_user_ids", []) or [])
                        + list(
                            getattr(config, "bot_telegram_admin_user_ids", []) or []
                        )
                    )
                    if str(admin_id).strip()
                ],
                settings_store=runtime_settings,
                render_backend=render_backend,
                card_dir=str(getattr(config, "bot_card_render_dir", "data/cards")),
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

        from .sources.subscription_runtime_v2 import register_subscription_runtime_v2

        async def _deliver_v2_event(event: Any) -> bool:
            store = subscription_ctx.get("store")
            target = store.get_target(event.target_id) if store is not None else None
            destinations = (
                store.list_destinations(event.target_id)
                if store is not None and target is not None
                else []
            )
            if target is None or not destinations:
                return False
            payload = event.item.source_payload or {}
            title = str(payload.get("title") or event.item.item_id)
            body = str(payload.get("text") or "").strip()
            text = (
                f"[订阅] {target.platform} {target.display_name} 更新《{title}》："
                f"{event.item.url}"
            )
            if body:
                text += f"\\n{body[:500]}"
            elif bool(getattr(config, "bot_vision_enabled", False)):
                # 纯图/无文本订阅条目：用 vision 补一行描述，失败静默不阻断推送。
                from .sources.vision_describe import describe_subscription_item

                described = describe_subscription_item(vision_provider, payload)
                if described:
                    text += f"\\n图：{described}"
            from .capabilities.content_parser import build_subscription_push_capability

            sent_any = False
            all_success = True
            for destination in destinations:
                scope = str(destination.scope or "private").lower()
                session_type = SessionType.GROUP if scope == "group" else SessionType.PRIVATE
                destination_id = str(destination.destination_id)
                message = IncomingMessage(
                    platform="nonebot",
                    adapter=str(destination.transport or "onebot.v11"),
                    bot_id=str(destination.bot_id or ""),
                    session_id=f"{scope}:{destination_id}",
                    session_type=session_type,
                    sender_id="sub-push",
                    group_id=destination_id if session_type is SessionType.GROUP else None,
                    plain_text=text,
                    raw_segments=[{"type": "text", "data": {"text": text}}],
                )
                try:
                    await pipeline.handle_async(
                        message,
                        offload_capability(build_subscription_push_capability(text)),
                        capability_id="bot.subscribe",
                    )
                    request = _find_sent_request(send_queue, message.request_id)
                    bot = _select_queue_bot(_all_online_bots, request) if request else None
                    if request is None or bot is None:
                        all_success = False
                        continue
                    receipt = await _deliver_transport_send_request(
                        bot,
                        None,
                        request,
                        audit_logger,
                        receipt_repository,
                        send_queue,
                    )
                    if receipt.state is ReceiptState.SENT:
                        sent_any = True
                    else:
                        all_success = False
                except (OSError, RuntimeError, TypeError, ValueError):
                    all_success = False
            return sent_any and all_success

        if getattr(config, "bot_subscribe_enabled", True):
            subscription_registration = defer_optional_subscription_registration(
                register_subscription_runtime_v2,
                scheduler,
                config,
                delivery_fn=_deliver_v2_event,
            )
            subscription_ctx = subscription_registration.context
            if subscription_registration.status == "deferred":
                audit_logger.append(
                    AuditRecord(
                        request_id="bot_subscription_runtime",
                        session_id="runtime",
                        capability_id="bot.subscribe",
                        stage="startup",
                        event="subscription_runtime_deferred",
                        severity=RiskLevel.MEDIUM,
                        public_message="订阅运行时未启动，核心聊天链路继续运行。",
                        private_debug=subscription_registration.error_kind,
                    )
                )
        else:
            subscription_ctx = {}

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
        max_bytes=int(getattr(config, "bot_download_max_bytes", 1073741824)),
        max_height=int(getattr(config, "bot_download_max_height", 0)),
        timeout_seconds=int(getattr(config, "bot_download_timeout_seconds", 300)),
        cache_max_bytes=int(getattr(config, "bot_download_cache_max_bytes", 0)),
        cache_max_age_days=int(getattr(config, "bot_download_cache_max_age_days", 0)),
    )
    intent_telemetry = build_intent_telemetry(
        enabled=config.bot_web_intent_telemetry_enabled,
        db_path=config.bot_web_intent_telemetry_db_path,
        max_items=config.bot_web_intent_telemetry_max_items,
    )
    from plugins.bot_unified_runtime.sources.vision_describe import (
        build_vision_provider,
    )

    vision_provider = build_vision_provider(
        config,
        dynamic_registry=runtime_settings.list_vision_registry,
        settings_store=runtime_settings,
    )
    model_router = build_model_router(
        config,
        dynamic_registry=runtime_settings.list_model_registry,
        priority_groups=lambda: runtime_settings.get_or(
            "BOT_MODEL_PRIORITY_GROUPS",
            getattr(config, "bot_model_priority_groups", []) or [],
        ),
    )
    memory_writer = _build_memory_writer(config, model_router=model_router, runtime_settings=runtime_settings)
    chat_capability = offload_capability(
        build_chat_capability(
            character_provider=build_character_context_provider(
                config,
                runtime_settings=runtime_settings,
                shared_group_llm_provider=_build_chat_llm_provider(config),
            ),
            llm_provider=_build_chat_llm_provider(config),
            affinity_store=(
                build_character_affinity_store(config)
            ),
            meme_search_provider=build_meme_search_provider(config),
            web_search_provider=build_web_search_provider(config),
            web_search_provider_factory=lambda: build_web_search_provider(
                config.model_copy(update={"bot_web_search_enabled": True})
            ),
            web_max_results=int(config.bot_web_search_max_results),
            web_page_proxy=str(getattr(config, "bot_download_proxy", "") or ""),
            web_page_timeout_seconds=float(
                getattr(config, "bot_web_search_timeout_seconds", 3.0) + 3.0
            ),
            web_page_max_chars=int(
                getattr(config, "bot_web_search_fetch_max_chars", 3000) or 3000
            ),
            runtime_settings=runtime_settings,
            interaction_counter=runtime_settings.interaction_increment,
            # NoneBot 自己按 BOT_MODEL_REGISTRY 的 priority 做直连故障转移。
            model_router=model_router,
            intent_telemetry=intent_telemetry,
            shadow_classifier_enabled=config.bot_web_classifier_shadow_enabled,
            web_search_enabled=config.bot_web_search_enabled,
            web_search_admin_notice=config.bot_web_search_admin_notice,
            fast_mode=config.bot_chat_fast_mode,
            reply_detail=config.bot_reply_detail,
            fast_max_tokens=config.bot_chat_fast_max_tokens,
            fast_max_candidates=config.bot_chat_fast_max_candidates,
            fast_context_budget=config.bot_chat_fast_context_budget,
            fast_web_max_queries=config.bot_chat_fast_web_max_queries,
            fast_skip_web_pages=config.bot_chat_fast_skip_web_pages,
            vision_provider=vision_provider,
            vision_enabled=bool(getattr(config, "bot_vision_enabled", False)),
            vision_mode=str(getattr(config, "bot_vision_mode", "relay") or "relay"),
            vision_max_images=int(getattr(config, "bot_vision_max_images", 2)),
            vision_max_chars=int(getattr(config, "bot_vision_max_chars", 500)),
            memory_writer=memory_writer,
            request_budget_seconds=float(
                getattr(config, "bot_request_budget_seconds", 0.0)
            ),
            temperature=config.bot_chat_temperature,
            reasoning_effort=config.bot_chat_reasoning_effort,
            model_prices=dict(getattr(config, "bot_model_prices", {}) or {}),
            max_tokens=config.bot_chat_max_tokens,
            model=config.bot_chat_model,
            context_preflight_errors=persona_context_preflight_errors(config),
            llm_preflight_errors=llm_generation_parameter_errors(config),
            output_max_chars_per_message=config.bot_reply_max_chars_per_message,
            generated_files_dir=str(getattr(config, "bot_generated_files_dir", "data/generated_files") or "data/generated_files"),
        )
    )

    async def _is_auto_send_plain_text(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.AUTO_SEND
        )

    def _event_adapter_kind(event: Event) -> str:
        module_name = type(event).__module__.lower()
        if ".telegram" in module_name:
            return "telegram"
        if ".mail" in module_name:
            return "mail"
        return "onebot"

    async def _is_mail_event(event: Event) -> bool:
        return _event_adapter_kind(event) == "mail"

    async def _is_plain_chat_event(state: T_State, event: Event) -> bool:
        if _event_adapter_kind(event) == "mail":
            if not config.bot_mail_bridge_enabled:
                return False
            if not config.bot_mail_auto_reply_enabled or mail_bridge_state.paused:
                return False
            return bool(
                event.get_plaintext().strip()
                or str(getattr(event, "subject", "") or "").strip()
            )
        try:
            raw_segments = _extract_onebot_raw_segments(event)
        except Exception:  # noqa: BLE001 - visual routing degrades to text routing.
            raw_segments = []
        if contains_visual_message_segments(raw_segments):
            return bool(config.bot_chat_enabled)
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.CHAT
        )

    status = on_command(
        "bot",
        aliases={"/bot", "Bot", "BOT", "/Bot", "/BOT"},
        force_whitespace=True,
        priority=11,
        block=True,
    )
    auto_send = on_message(rule=_is_auto_send_plain_text, priority=13, block=True)
    mail_control = on_command(
        "mail",
        aliases={"/mail"},
        force_whitespace=True,
        priority=10,
        block=True,
    )
    mail_notice = on_message(rule=_is_mail_event, priority=9, block=False)
    chat = on_message(rule=_is_plain_chat_event, priority=50, block=True)
    async def _is_meme_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.MEME
        )

    async def _is_natural_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.NATURAL_COMMAND
        )

    meme = on_message(rule=_is_meme_event, priority=20, block=True)
    natural = on_message(rule=_is_natural_event, priority=45, block=True)

    async def _is_meme_library_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.MEME_LIBRARY
        )

    meme_library = on_message(rule=_is_meme_library_event, priority=22, block=True)

    meme_absorb = on_message(priority=10, block=False)

    async def _send_text_through_unified_pipeline(
        bot: Bot,
        event: Event,
        text: str,
        capability_id: str = "bot.file",
    ) -> DeliveryReceipt:
        def _capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id=capability_id,
                kind="text",
                body=str(text),
                audit_tags=["unified_text_reply"],
            )

        return await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            diagnostics_store=diagnostics_store,
            capability=_capability,
            capability_id=capability_id,
            receipt_repository=receipt_repository,
            history_recorder=None,
            history_kind="system",
            operational_notifier=_notify_operational_receipt,
        )

    # --- 文件收发（管理员）：接收代码/文档调试 + 导出多格式文档上传 ---
    from pathlib import Path as _Path

    from nonebot.adapters.onebot.v11 import (
        GroupMessageEvent,
        GroupUploadNoticeEvent,
    )

    from .capabilities.file_exchange import (
        export_document,
        is_file_export_command,
        parse_file_export_command,
        run_code_debug,
    )

    async def _is_admin_origin(event: Event) -> bool:
        try:
            user_id = str(event.get_user_id()).strip()
        except Exception:  # noqa: BLE001 - 适配器实现差异。
            return False
        return user_id in {str(item).strip() for item in config.bot_admin_user_ids}

    async def _is_admin_file_notice(event: Event) -> bool:
        return isinstance(
            event, (GroupUploadNoticeEvent, PrivateFileNoticeEvent)
        ) and await _is_admin_origin(event)

    async def _is_group_upload_notice(event: Event) -> bool:
        return str(getattr(event, "notice_type", "")) == "group_upload"

    group_upload_notice = on_notice(rule=_is_group_upload_notice, priority=6, block=False)

    @group_upload_notice.handle()
    async def _handle_group_upload(bot: Bot, event: Event) -> None:
        try:
            file_info = getattr(event, "file", None) or {}
            group_file_store.record(
                group_id=str(getattr(event, "group_id", "")),
                file_id=str(file_info.get("id") if isinstance(file_info, dict) else getattr(file_info, "id", "")),
                name=str(file_info.get("name") if isinstance(file_info, dict) else getattr(file_info, "name", "")),
                size=int(file_info.get("size") or 0) if isinstance(file_info, dict) else int(getattr(file_info, "size", 0) or 0),
                uploader_id=str(getattr(event, "user_id", "")),
            )
        except Exception:  # noqa: BLE001, S110 - 群文件记录失败不影响主链路。
            pass

    async def _is_dirty_guard_message(event: Event) -> bool:
        if not getattr(config, "bot_dirty_guard_enabled", False):
            return False
        return bool(event.get_plaintext().strip()) and bool(getattr(event, "group_id", None))

    dirty_guard_matcher = on_message(rule=_is_dirty_guard_message, priority=3, block=False)

    @dirty_guard_matcher.handle()
    async def _handle_dirty_guard(bot: Bot, event: Event) -> None:
        text = event.get_plaintext().strip()
        verdict = dirty_guard.assess(text)
        if verdict != "severe" or not dirty_guard.delete_enabled:
            return
        try:
            message_id = getattr(event, "message_id", None)
            if message_id:
                await bot.call_api("delete_msg", message_id=message_id)
        except Exception:  # noqa: BLE001, S110 - 撤回失败静默（多半无管理员权限）。
            pass

    file_notice = on_notice(rule=_is_admin_file_notice, priority=8, block=False)

    from .capabilities.poke import PokeLimiter, build_poke_text
    _poke_limiter = PokeLimiter(clock=time.monotonic)

    async def _is_poke_event(event: Event) -> bool:
        return str(getattr(event, "notice_type", "")) == "notify" and str(getattr(event, "sub_type", "")) == "poke"

    poke_notice = on_notice(rule=_is_poke_event, priority=7, block=False)

    @poke_notice.handle()
    async def _handle_poke_notice(bot: Bot, event: Event) -> None:
        if not _poke_limiter.accept(
            event, str(getattr(bot, "self_id", "")), bool(getattr(config, "bot_poke_enabled", True)),
            float(getattr(config, "bot_poke_private_cooldown_seconds", 30.0)),
            float(getattr(config, "bot_poke_group_cooldown_seconds", 10.0)),
            float(getattr(config, "bot_poke_probability", 1.0)),
        ):
            return
        await _send_text_through_unified_pipeline(
            bot, event,
            build_poke_text(group=bool(getattr(event, "group_id", None)), nickname=""),
            "bot.poke",
        )

    @file_notice.handle()
    async def _handle_admin_file_notice(bot: Bot, event: Event) -> None:
        file_info = getattr(event, "file", None)
        file_id = str(getattr(file_info, "file_id", "") or "")
        file_name = str(getattr(file_info, "name", "") or "file")
        file_url = str(getattr(file_info, "url", "") or "")
        if not file_id and not file_url:
            return
        incoming_dir = _Path(
            str(getattr(config, "bot_download_dir", "data/downloads") or "data/downloads")
        ) / "incoming"
        saved_path = ""
        try:
            incoming_dir.mkdir(parents=True, exist_ok=True)
            if file_id:
                payload = await bot.call_api("get_file", file_id=file_id) or {}
            else:
                # 私聊 offline_file 通知按协议只有 url 没有 file_id，
                # 走 download_file 让平台侧带鉴权下载。
                payload = await bot.call_api("download_file", url=file_url) or {}
            local_path = str(payload.get("file") or "")
            base64_body = str(payload.get("base64") or "")
            target = incoming_dir / f"{int(time.time() * 1000)}_{file_name}"
            if base64_body:
                import base64

                target.write_bytes(base64.b64decode(base64_body))
                saved_path = str(target)
            elif local_path and _Path(local_path).exists():
                saved_path = local_path
        except Exception:  # noqa: BLE001 - 平台取文件失败只回报类型。
            await _send_text_through_unified_pipeline(bot, event, "文件接收失败（平台接口异常），请重试或改发文本。")
            return
        if not saved_path:
            await _send_text_through_unified_pipeline(bot, event, "文件接收失败：平台未返回可读文件内容。")
            return
        report = run_code_debug(saved_path)
        await _send_text_through_unified_pipeline(bot, event, f"[文件调试] {file_name}\n{report}")

    async def _is_admin_file_export(event: Event) -> bool:
        return is_file_export_command(event.get_plaintext()) and await _is_admin_origin(
            event
        )

    file_export = on_message(rule=_is_admin_file_export, priority=8, block=True)

    @file_export.handle()
    async def _handle_admin_file_export(bot: Bot, event: Event) -> None:
        parsed = parse_file_export_command(event.get_plaintext())
        if parsed is None:
            return
        fmt, topic = parsed
        from .capabilities.file_exchange import _DOCUMENT_PROMPT

        try:
            reply = _build_chat_llm_provider(config).generate(
                [
                    {"role": "system", "content": _DOCUMENT_PROMPT},
                    {"role": "user", "content": topic},
                ],
                temperature=0.4,
                max_tokens=3000,
            )
        except Exception as exc:  # noqa: BLE001 - LLM 失败只回报类型。
            await _send_text_through_unified_pipeline(bot, event, f"文档生成失败：{type(exc).__name__}")
            return
        markdown = str(getattr(reply, "text", "") or "").strip()
        if not markdown:
            await _send_text_through_unified_pipeline(bot, event, "文档生成失败：模型返回空内容。")
            return
        out_dir = _Path(
            str(getattr(config, "bot_download_dir", "data/downloads") or "data/downloads")
        ) / "export"
        path, error = export_document(markdown, fmt, out_dir, title=topic[:40])
        if error:
            await _send_text_through_unified_pipeline(bot, event, f"导出失败：{error}")
            return
        try:
            if isinstance(event, GroupMessageEvent):
                await bot.call_api(
                    "upload_group_file",
                    group_id=event.group_id,
                    file=str(path),
                    name=path.name,
                )
            else:
                await bot.call_api(
                    "upload_private_file",
                    user_id=int(event.get_user_id()),
                    file=str(path),
                    name=path.name,
                )
        except Exception:  # noqa: BLE001 - 上传失败只回报类型。
            await _send_text_through_unified_pipeline(bot, event, f"文件已生成但上传失败：{path.name}")
            return
        await _send_text_through_unified_pipeline(
            bot,
            event,
            f"已生成并上传 {fmt.upper()}：{path.name}（{max(1, path.stat().st_size // 1024)}KB）",
        )

    async def _is_admin_cookie_command(event: Event) -> bool:
        return is_cookie_command(event.get_plaintext()) and await _is_admin_origin(event)

    async def _is_image_search_event(event: Event) -> bool:
        return bool(re.match(r"^[/!！]?搜图(\s|$)", event.get_plaintext().strip()))

    image_search = on_message(rule=_is_image_search_event, priority=46, block=True)

    @image_search.handle()
    async def _handle_image_search(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            bot_id=str(getattr(bot, "self_id", "unknown")), event=event
        )
        if message is None:
            return
        from .capabilities.image_search import (
            build_image_search_capability,
        )

        capability = build_image_search_capability(config)
        receipt = await pipeline.handle_async(
            message,
            offload_capability(capability),
            capability_id="bot.image_search",
        )
        await _notify_operational_receipt(message, receipt)

    cookie_admin = on_message(rule=_is_admin_cookie_command, priority=8, block=True)

    _NICKNAME_RE = re.compile(r"^/bot\s+(?:昵称|nickname)\s+set\s+(\d{5,11})\s+(\S{1,32})$")

    async def _is_nickname_set_command(event: Event) -> bool:
        return bool(_NICKNAME_RE.match(event.get_plaintext().strip())) and await _is_admin_origin(event)

    nickname_set = on_message(rule=_is_nickname_set_command, priority=8, block=True)

    @nickname_set.handle()
    async def _handle_nickname_set(bot: Bot, event: Event) -> None:
        match = _NICKNAME_RE.match(event.get_plaintext().strip())
        if match is None:
            return
        target_user, nickname = match.group(1), match.group(2)
        store = build_character_affinity_store(config)
        if store is None:
            await _send_text_through_unified_pipeline(bot, event, "好感度系统未启用，无法设置小名。")
            return
        store.set_nickname(target_user, nickname)
        snapshot = store.snapshot(target_user)
        await _send_text_through_unified_pipeline(
            bot,
            event,
            f"✅ 已把 {target_user} 的小名记为「{snapshot['nickname']}」，之后的对话会用在称呼里。",
        )

    async def _is_group_file_stats_command(event: Event) -> bool:
        text = event.get_plaintext().strip()
        return bool(re.match(r"^/bot\s+群文件", text))

    group_file_stats = on_message(rule=_is_group_file_stats_command, priority=45, block=True)

    @group_file_stats.handle()
    async def _handle_group_file_stats(bot: Bot, event: Event) -> None:
        group_id = str(getattr(event, "group_id", "") or "")
        if not group_id:
            await _send_text_through_unified_pipeline(bot, event, "群文件统计仅在群聊可用。")
            return
        await _send_text_through_unified_pipeline(bot, event, group_file_store.summary(group_id))

    @cookie_admin.handle()
    async def _handle_admin_cookie(bot: Bot, event: Event) -> None:
        parsed = parse_cookie_command(event.get_plaintext())
        if parsed is None:
            return
        action, platform, header = parsed
        if action == "import":
            if not platform or not header:
                await _send_text_through_unified_pipeline(
                    bot,
                    event,
                    "用法：/bot cookie import <平台> <Cookie头>，例如：/bot cookie import bilibili SESSDATA=...; bili_jct=...",
                )
                return
            result = import_cookie_header(config, platform, header)
        else:
            result = cookie_status_text(config)
        await _send_text_through_unified_pipeline(bot, event, result)

    @mail_notice.handle()
    async def _handle_mail_notice(bot: Bot, event: Event) -> None:
        if not config.bot_mail_bridge_enabled:
            return
        if not config.bot_mail_notify_telegram_enabled:
            return
        try:
            sender_id = str(event.get_user_id()).strip().lower()
        except Exception:  # noqa: BLE001 - adapter event implementations vary.
            sender_id = ""
        if sender_id == str(getattr(bot, "self_id", "")).strip().lower():
            return
        account = str(getattr(bot, "self_id", "unknown"))
        incoming = _incoming_from_nonebot_event(
            event,
            bot_id=account,
            adapter_name="Mail",
        )
        mail_id, mail_id_is_fallback = mail_event_dedupe_id(event)
        if not mail_id:
            _log_runtime_event(
                runtime_event_log,
                "WARNING",
                "mail_notice_without_dedupe_id",
                message=incoming,
                capability_id="bot.mail.notify",
                mail_id_present=False,
            )
            return
        if not mail_bridge_state.claim_notification(mail_id, account):
            _log_runtime_event(
                runtime_event_log,
                "INFO",
                "mail_notice_duplicate_skipped",
                message=incoming,
                capability_id="bot.mail.notify",
                mail_id_present=True,
                mail_id_is_fallback=mail_id_is_fallback,
            )
            return
        notification = build_mail_notification(
            event,
            account=account,
            max_preview_chars=config.bot_mail_notify_preview_chars,
        )
        try:
            sent = await notify_telegram_admins(
                get_bots(),
                config.bot_telegram_admin_chat_ids,
                notification,
            )
            audit_logger.append(
                AuditRecord(
                    request_id=incoming.request_id,
                    session_id=incoming.session_id,
                    capability_id="bot.mail.notify",
                    stage="mail_bridge",
                    event="telegram_mail_notice_sent" if sent else "telegram_mail_notice_skipped",
                    severity=RiskLevel.LOW,
                    public_message="新邮件提醒已处理。" if sent else "未配置可用的 Telegram 提醒目标。",
                    private_debug=f"telegram_targets={sent}",
                )
            )
        except Exception as exc:  # noqa: BLE001 - 提醒失败不能阻断邮件自动回复。
            audit_logger.append(
                AuditRecord(
                    request_id=incoming.request_id,
                    session_id=incoming.session_id,
                    capability_id="bot.mail.notify",
                    stage="mail_bridge",
                    event="telegram_mail_notice_failed",
                    severity=RiskLevel.MEDIUM,
                    public_message="Telegram 邮件提醒发送失败。",
                    private_debug=type(exc).__name__,
                )
            )

    @mail_control.handle()
    async def _handle_mail_control(
        bot: Bot,
        event: Event,
        args=CommandArg(),  # noqa: B008 - NoneBot dependency injection default.
    ) -> None:
        if _event_adapter_kind(event) != "telegram":
            await mail_control.finish("邮件控制命令仅允许从 Telegram 管理端执行。")
            return
        admin_ids = [
            *config.bot_telegram_admin_user_ids,
            *config.bot_telegram_admin_chat_ids,
        ]
        if not is_telegram_admin(event, admin_ids):
            await mail_control.finish("你没有邮件控制权限。")
            return

        command_text = args.extract_plain_text().strip()
        try:
            command = parse_mail_command(command_text)
            response_text = await execute_mail_command(
                command,
                actor_id=event.get_user_id(),
                bots=get_bots(),
                state=mail_bridge_state,
                aliases=config.bot_mail_sender_aliases,
            )
            event_name = f"mail_control_{command.action}"
            severity = RiskLevel.MEDIUM if command.action == "send" else RiskLevel.LOW
        except ValueError as exc:
            response_text = str(exc)
            event_name = "mail_control_invalid"
            severity = RiskLevel.LOW
        except Exception as exc:  # noqa: BLE001 - SMTP/adapter 细节不得回显。
            response_text = "邮件操作失败，请查看脱敏运行日志后重试。"
            event_name = "mail_control_failed"
            severity = RiskLevel.MEDIUM
            audit_logger.append(
                AuditRecord(
                    request_id=f"mail-control:{event.get_user_id()}",
                    session_id=event.get_session_id(),
                    capability_id="bot.mail.control",
                    stage="mail_bridge",
                    event=event_name,
                    severity=severity,
                    public_message=response_text,
                    private_debug=type(exc).__name__,
                )
            )

        def capability(message: IncomingMessage, decision: Any) -> CapabilityResult:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.mail.control",
                kind="text",
                body=response_text,
                confidence=1.0,
                risk_level=severity,
                privacy_level=PrivacyLevel.PERSONAL,
                send_policy=SendPolicy.IMMEDIATE,
                audit_tags=[*decision.audit_tags, "mail_control", event_name],
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
            capability_id="bot.mail.control",
            record_diagnostic=False,
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
            await mail_control.finish(receipt.public_message)

    @meme_absorb.handle()
    async def _handle_meme_absorb(bot: Bot, event: Event) -> None:
        if meme_library_store is None:
            return
        try:
            await absorb_event_images(bot, event, config, meme_library_store)
        except Exception:  # noqa: BLE001 - 收藏失败不影响消息流。
            return

    async def _is_content_parse_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(
                state, event, config=config, effective_text=True
            ).kind
            is RouteKind.CONTENT
        )

    async def _is_music_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.MUSIC
        )

    async def _is_music_mode_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.MUSIC_MODE
        )

    async def _is_standalone_subscribe_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.SUBSCRIBE
        )

    async def _is_today_history_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.TODAY_HISTORY
        )

    async def _is_wiki_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.WIKI
        )

    async def _is_epic_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.EPIC
        )

    async def _is_weather_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
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

    async def _is_alias_command(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(
                state, event, config=config, alias_resolver=alias_resolver
            ).kind
            is RouteKind.ALIAS
        )

    alias = on_message(rule=_is_alias_command, priority=10, block=True)

    @alias.handle()
    async def _handle_alias(bot: Bot, event: Event) -> None:
        command_text = event.get_plaintext().strip()
        resolution = alias_resolver.resolve(command_text)
        if resolution is None:
            await alias.finish("无法识别的昵称命令。")
            return
        capability_id = "bot.alias"
        help_bot_avatar_url = ""

        if resolution.capability_id == "bot.help":
            capability_id = "bot.help"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                from .capabilities.echo import build_help_result

                return build_help_result(
                    request_id=message.request_id,
                    query=resolution.rest_text,
                    is_admin="admin" in {
                        str(role).lower() for role in _decision.actor_roles
                    },
                    render_backend=render_backend,
                    card_dir=str(getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"),
                    bot_name=str(getattr(config, "bot_persona_display_name", "守岸人") or "守岸人"),
                    bot_avatar_url=help_bot_avatar_url,
                    accent_color=str(getattr(config, "bot_help_card_color", "") or ""),
                )

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
                return build_music_capability(
                    config,
                    default_mode=mode,
                    request_store=music_request_store,
                    candidate_providers=(
                        music_candidate_providers(build_cookie_provider(config))
                        if getattr(config, "bot_music_candidates_enabled", False)
                        else None
                    ),
                )(synthetic, _decision)

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
                from .capabilities.subscribe import normalize_subscribe_text
                from .capabilities.subscribe_v2 import build_subscribe_capability_v2

                sub_ctx = subscription_ctx if isinstance(subscription_ctx, dict) else {}
                normalized = normalize_subscribe_text(
                    f"/bot subscribe {resolution.rest_text}".strip()
                )
                synthetic = message.model_copy(update={"plain_text": normalized})
                return build_subscribe_capability_v2(
                    store=sub_ctx["store"],
                    adapters=sub_ctx["adapters"],
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

        if capability_id == "bot.help":
            help_bot_avatar_url = await _resolve_bot_avatar_url(bot, config)
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
            offload_sync_capability=capability_id in OFFLOADED_CAPABILITY_IDS,
            history_recorder=history_recorder,
            history_kind="command",
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
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
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
            await music_mode.finish(receipt.public_message)

    @subscribe_cmd.handle()
    async def _handle_standalone_subscribe(bot: Bot, event: Event) -> None:
        from .capabilities.subscribe import normalize_subscribe_text
        from .capabilities.subscribe_v2 import build_subscribe_capability_v2

        sub_ctx = subscription_ctx if isinstance(subscription_ctx, dict) else {}

        def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
            normalized = normalize_subscribe_text(message.plain_text)
            synthetic_message = message.model_copy(update={"plain_text": normalized})
            return build_subscribe_capability_v2(
                store=sub_ctx["store"],
                adapters=sub_ctx["adapters"],
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
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
            await subscribe_cmd.finish(receipt.public_message)

    @status.handle()
    async def _handle_status(bot: Bot, event: Event, args=CommandArg()) -> None:  # noqa: B008 - NoneBot 依赖注入要求以 CommandArg() 作为默认参数。

        command_text = normalize_command_text(args.extract_plain_text().strip())
        help_bot_avatar_url = ""

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
                    render_backend=render_backend,
                    card_dir=str(
                        getattr(config, "bot_card_render_dir", "data/cards")
                        or "data/cards"
                    ),
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
                    diagnostics_store=diagnostics_store,
                    usage_store=runtime_event_log,
                )

        elif command_text == "model" or command_text.startswith("model "):
            # /bot model ...：/bot runtime model ... 的顶层短形式。
            capability_id = "bot.runtime"
            model_command = ("model " + command_text.removeprefix("model").strip()).strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_runtime_admin_result(
                    settings_manager,
                    effective_instance(config),
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    command_text=model_command,
                    diagnostics_store=diagnostics_store,
                    usage_store=runtime_event_log,
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
                from .capabilities.subscribe_v2 import build_subscribe_capability_v2

                sub_ctx = subscription_ctx if isinstance(subscription_ctx, dict) else {}
                return build_subscribe_capability_v2(
                    store=sub_ctx["store"],
                    adapters=sub_ctx["adapters"],
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
            help_query = resolve_help_query(command_text)

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                from .capabilities.echo import build_help_result

                return build_help_result(
                    request_id=message.request_id,
                    query=help_query,
                    is_admin="admin" in {
                        str(role).lower() for role in _decision.actor_roles
                    },
                    render_backend=render_backend,
                    card_dir=str(getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"),
                    bot_name=str(getattr(config, "bot_persona_display_name", "守岸人") or "守岸人"),
                    bot_avatar_url=help_bot_avatar_url,
                    accent_color=str(getattr(config, "bot_help_card_color", "") or ""),
                )

        else:
            capability_id = "bot.status"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_status_result(
                    config,
                    request_id=message.request_id,
                    runtime_control=runtime_control,
                )

        if capability_id == "bot.help":
            help_bot_avatar_url = await _resolve_bot_avatar_url(bot, config)
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
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
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
            operational_notifier=_notify_operational_receipt,
        )
        state["bot_preview_only"] = True
        if should_finish_nonebot_matcher(receipt):
            await auto_send.finish(receipt.public_message)

    @chat.handle()
    async def _handle_chat(bot: Bot, event: Event) -> None:
        started_at = time.perf_counter()
        bot_id = str(getattr(bot, "self_id", "unknown"))
        event_module = type(event).__module__.lower()
        if (
            event_module.find(".mail") >= 0
            and str(event.get_user_id()).strip().lower()
            == str(getattr(bot, "self_id", "")).strip().lower()
        ):
            _log_runtime_event(
                runtime_event_log,
                "INFO",
                "incoming_ignored_self_mail",
                adapter="mail",
                platform="email",
                bot_id=bot_id,
            )
            return
        _log_runtime_event(
            runtime_event_log,
            "INFO",
            "incoming_event",
            adapter=("telegram" if ".telegram" in event_module else "mail" if ".mail" in event_module else "nonebot"),
            platform=("telegram" if ".telegram" in event_module else "email" if ".mail" in event_module else "qq"),
            bot_id=bot_id,
            event_type=type(event).__name__,
        )
        message = _incoming_from_nonebot_event(bot_id=bot_id, event=event)
        # 被动感知（批次 C）：所有群/私聊消息都观察行为、自述画像与小名自学，
        # 不依赖 @/白名单触发；只影响后续态度与称呼，不改变本轮是否回复。
        if message.sender_id and message.plain_text.strip():
            try:
                _store = build_character_affinity_store(config)
                if _store is not None:
                    from .character.affinity import classify_behavior
                    from .character.affinity import extract_profile_facts as _epf

                    _store.observe(
                        message.sender_id,
                        classify_behavior(message.plain_text),
                    )
                    facts = _epf(message.plain_text)
                    if facts:
                        _store.learn_profile(message.sender_id, message.plain_text)
                    import re as _re

                    nickname_match = _re.search(
                        r"(?:你可以叫我|以后叫我|就叫我|叫我|喊我)\s*([\u4e00-\u9fa5A-Za-z0-9]{1,12})"
                        r"(?:吧|就好|就可以了|就行|哦|呀|~|！|!|。|\s|$)",
                        message.plain_text,
                    )
                    if nickname_match:
                        learned = nickname_match.group(1).strip()
                        current = _store.snapshot(message.sender_id).get("nickname") or ""
                        if learned and learned != current:
                            _store.set_nickname(message.sender_id, learned)
            except Exception:  # noqa: BLE001, S110 - 被动感知失败不影响主链路。
                pass
        # 小名缓存刷新（60s），供动态昵称 mention 判定。
        if time.time() - _AFFINITY_NICKNAMES_LOADED_AT > 60.0:
            _refresh_affinity_nicknames(_affinity_store_runtime(config))
        # 群聊复读检测（批次 C）：≥N 个不同用户在窗口内发同一文本 → 吐槽一次。
        if (
            message.session_type.value == "group"
            and message.plain_text.strip()
            and not message.plain_text.strip().startswith("/")
        ):
            try:
                parrot_reply = parrot_detector.detect(
                    session_id=message.session_id,
                    sender_id=message.sender_id,
                    text=message.plain_text,
                    is_bot_self=str(message.sender_id) == bot_id,
                )
            except Exception:  # noqa: BLE001 - 复读检测失败不影响主链路。
                parrot_reply = None
            if parrot_reply:
                from .contracts import CapabilityResult as _CR
                from .contracts import PrivacyLevel as _PL
                from .contracts import RiskLevel as _RL
                from .contracts import SendPolicy as _SP

                await pipeline.handle_async(
                    message,
                    offload_capability(lambda m, d: _CR(
                        request_id=m.request_id,
                        capability_id="bot.chat",
                        kind="text",
                        body=parrot_reply,
                        send_policy=_SP.IMMEDIATE,
                        privacy_level=_PL.GROUP,
                        risk_level=_RL.LOW,
                        audit_tags=["group_parrot", "social_response"],
                    )),
                    capability_id="bot.chat",
                )
                return
        is_mail_event = ".mail" in event_module
        mail_reply_id, mail_reply_id_is_fallback = mail_event_dedupe_id(event)
        if not mail_reply_id:
            mail_reply_id = message.message_id or ""
            mail_reply_id_is_fallback = False
        if is_mail_event and not mail_reply_id:
            _log_runtime_event(
                runtime_event_log,
                "WARNING",
                "mail_reply_without_dedupe_id",
                message=message,
                capability_id="bot.chat",
                mail_id_present=False,
            )
            return
        mail_reply_claimed = False
        if is_mail_event and mail_reply_id:
            mail_reply_claimed = mail_bridge_state.claim_reply(mail_reply_id, bot_id)
            if not mail_reply_claimed:
                _log_runtime_event(
                    runtime_event_log,
                    "INFO",
                    "mail_reply_duplicate_skipped",
                    message=message,
                    capability_id="bot.chat",
                    mail_id_present=bool(mail_reply_id),
                    mail_id_is_fallback=mail_reply_id_is_fallback,
                )
                return

        def release_mail_reply_claim() -> None:
            if mail_reply_claimed:
                mail_bridge_state.release_reply(mail_reply_id, bot_id)

        _log_runtime_event(
            runtime_event_log,
            "INFO",
            "incoming_normalized",
            message=message,
            capability_id="bot.chat",
        )
        try:
            forward_text = await _forward_message_text(bot, event)
        except Exception:
            release_mail_reply_claim()
            raise
        if forward_text:
            message = message.model_copy(
                update={
                    "plain_text": (
                        f"{message.plain_text}\n【合并转发内容】\n{forward_text}"
                    ).strip()
                }
            )
        _log_runtime_event(
            runtime_event_log,
            "INFO",
            "pipeline_enter",
            message=message,
            capability_id="bot.chat",
        )
        try:
            receipt = await pipeline.handle_async(
                message,
                chat_capability,
                capability_id="bot.chat",
            )
        except Exception:
            release_mail_reply_claim()
            raise
        # Notify the pipeline issue before a later transport receipt can replace it.
        await _notify_operational_receipt(message, receipt)
        sent_request = _find_sent_request(send_queue, message.request_id)
        _log_runtime_event(
            runtime_event_log,
            "INFO" if receipt.state.value not in {"failed_final", "blocked"} else "WARNING",
            "pipeline_result",
            message=message,
            capability_id="bot.chat",
            receipt_state=receipt.state.value,
            transport=receipt.transport,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
            **_runtime_tag_values(sent_request),
        )
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
            _log_runtime_event(
                runtime_event_log,
                "INFO",
                "transport_start",
                message=message,
                capability_id=sent_request.capability_id,
                transport_adapter=sent_request.adapter,
                target_scope=sent_request.target_scope.value,
            )
            try:
                transport_receipt = await _deliver_transport_send_request(
                    bot,
                    event,
                    sent_request,
                    audit_logger,
                    receipt_repository,
                    send_queue,
                )
            except Exception:
                release_mail_reply_claim()
                raise
            _log_runtime_event(
                runtime_event_log,
                "INFO" if transport_receipt.state.value == "sent" else "WARNING",
                "transport_receipt",
                message=message,
                capability_id=sent_request.capability_id,
                receipt_state=transport_receipt.state.value,
                transport=transport_receipt.transport,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
                **_runtime_tag_values(sent_request),
            )
            await _notify_operational_receipt(message, transport_receipt)
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
                if is_mail_event:
                    mail_bridge_state.mark_reply_sent(mail_reply_id, bot_id)
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
            release_mail_reply_claim()
            if should_finish_nonebot_matcher(transport_receipt):
                await chat.finish(transport_receipt.public_message)
        else:
            release_mail_reply_claim()
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
        await _notify_operational_receipt(message, receipt)
        if should_finish_nonebot_matcher(receipt):
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
        card_bot_avatar_url = await _resolve_bot_avatar_url(bot, config)
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
                    bot_avatar_url=card_bot_avatar_url,
                )
            ),
            capability_id="bot.content",
        )
        await _notify_operational_receipt(message, receipt)
        sent_request = _find_sent_request(send_queue, message.request_id)
        if sent_request is not None:
            transport_receipt = await _deliver_transport_send_request(
                bot,
                event,
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
            await _notify_operational_receipt(message, transport_receipt)
            if transport_receipt.state.value == "sent":
                return
            if should_finish_nonebot_matcher(transport_receipt):
                await content.finish(transport_receipt.public_message)
        await _notify_operational_receipt(message, receipt)
        if should_finish_nonebot_matcher(receipt):
            await content.finish(receipt.public_message)

    @music.handle()
    async def _handle_music(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
        )
        receipt = await pipeline.handle_async(
            message,
            offload_capability(
                build_music_capability(
                    config,
                    default_mode=runtime_settings.get("BOT_MUSIC_MODE", config)
                        or getattr(config, "bot_music_default_mode", "card+voice+link"),
                    request_store=music_request_store,
                    candidate_providers=(
                        music_candidate_providers(build_cookie_provider(config))
                        if getattr(config, "bot_music_candidates_enabled", False)
                        else None
                    ),
                )
            ),
            capability_id="bot.music",
        )
        await _notify_operational_receipt(message, receipt)
        sent_request = _find_sent_request(send_queue, message.request_id)
        if sent_request is not None:
            transport_receipt = await _deliver_transport_send_request(
                bot,
                event,
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
            await _notify_operational_receipt(message, transport_receipt)
            if transport_receipt.state.value == "sent":
                return
            if should_finish_nonebot_matcher(transport_receipt):
                await music.finish(transport_receipt.public_message)
        await _notify_operational_receipt(message, receipt)
        if should_finish_nonebot_matcher(receipt):
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
            transport_receipt = await _deliver_transport_send_request(
                bot,
                event,
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
            if should_finish_nonebot_matcher(transport_receipt):
                await today_history.finish(transport_receipt.public_message)
        await _notify_operational_receipt(message, receipt)
        if should_finish_nonebot_matcher(receipt):
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
        await _notify_operational_receipt(message, receipt)
        sent_request = _find_sent_request(send_queue, message.request_id)
        if sent_request is not None:
            transport_receipt = await _deliver_transport_send_request(
                bot,
                event,
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
            await _notify_operational_receipt(message, transport_receipt)
            if transport_receipt.state.value == "sent":
                return
            if should_finish_nonebot_matcher(transport_receipt):
                await matcher.finish(transport_receipt.public_message)
        await _notify_operational_receipt(message, receipt)
        if should_finish_nonebot_matcher(receipt):
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
            transport_receipt = await _deliver_transport_send_request(
                bot,
                event,
                sent_request,
                audit_logger,
                receipt_repository,
                send_queue,
            )
            if transport_receipt.state.value == "sent":
                return
            if should_finish_nonebot_matcher(transport_receipt):
                await meme_library.finish(transport_receipt.public_message)
        await _notify_operational_receipt(message, receipt)
        if should_finish_nonebot_matcher(receipt):
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
                return build_music_capability(
                    config,
                    default_mode=mode,
                    request_store=music_request_store,
                )(synthetic, _decision)

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
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
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
    render_backend: Any | None = None,
    card_dir: str = "data/cards",
) -> dict[str, object]:
    """注册订阅系统三个 APScheduler job：常规轮询、直播轮询、日报汇总。

    config.bot_subscribe_enabled=False 时直接返回空 dict，不触碰调度器。
    即时推送在渲染后端可用时附带解析卡片图（kind="mixed"），任何渲染
    失败自动回退纯文本；日报恒为纯文本。
    """
    if not getattr(config, "bot_subscribe_enabled", True):
        return {}

    from .capabilities.content_parser import (
        build_subscription_push_capability,
        render_subscription_push_card,
    )
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

    def _capability_for(text: str, images: list[dict[str, str]] | None = None) -> Any:
        return build_subscription_push_capability(text, images)

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
        card_enabled = bool(getattr(config, "bot_subscribe_card_enabled", True))
        for candidate in candidates:
            spec = store.get_spec(candidate.spec_id)
            if spec is None or not spec.destinations:
                continue
            text = _push_text(candidate, spec)
            # 每候选只渲染一次、多目的地复用；渲染失败自动回退纯文本。
            images: list[dict[str, str]] | None = None
            if (
                card_enabled
                and render_backend is not None
                and candidate.reason != "digest_due"
            ):
                card_image = render_subscription_push_card(
                    render_backend,
                    candidate,
                    spec,
                    config=config,
                    card_dir=card_dir,
                )
                if card_image:
                    images = [card_image]
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
                        offload_capability(_capability_for(text, images)),
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

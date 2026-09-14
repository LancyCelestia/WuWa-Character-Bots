from __future__ import annotations

import asyncio
import inspect
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebot.adapters.onebot.v11 import NoticeEvent as OneBotNoticeEvent
from nonebot.typing import T_State
from pydantic import BaseModel

from .audit import AuditRepository, build_audit_repository
from .audit.file_logger import build_audit_with_file_log
from .capabilities.affinity import build_affinity_capability
from .capabilities.chat import (
    build_admin_roster_text as _build_admin_roster_text_for_chat,
)
from .capabilities.content_parser import build_content_capability
from .capabilities.divination import build_divination_capability
from .capabilities.download import build_download_capability
from .capabilities.eat import build_eat_capability
from .capabilities.epic import build_epic_capability
from .capabilities.fx import build_fx_capability
from .capabilities.group_files import DirtyGuard, GroupFileStore
from .capabilities.market import (
    build_bond_capability,
    build_commodities_capability,
    build_market_capability,
    build_northbound_capability,
)
from .capabilities.media_archive import build_media_archive_capability
from .capabilities.meme import build_meme_capability
from .capabilities.meme_library import build_meme_library_capability
from .capabilities.moegirl import (
    build_moegirl_capability,
    local_kb_answer,
    question_lookup,
)
from .capabilities.music import build_music_capability
from .capabilities.news import build_news_capability
from .capabilities.platform_credentials import (
    cookie_expiry_report,
    cookie_login_check,
    cookie_login_start,
    cookie_status_text,
    import_cookie_header,
    is_cookie_command,
    parse_cookie_command,
)
from .capabilities.randpic import build_randpic_capability
from .capabilities.reminder import build_reminder_capability
from .capabilities.stocks import build_stocks_capability
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
from .message_context import (
    collect_reply_chain,
    collect_reply_chain_async,
    format_reply_chain,
    normalize_message_segments,
)
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
    clear_route_decision_cache,
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
from .runtime.reactions import (
    SHARED_PROACTIVE_GATE as _REACTION_PROACTIVE_GATE,
)
from .runtime.reactions import (
    SHARED_REACTION_BUFFER as _REACTION_BUFFER,
)
from .runtime.reactions import (
    describe_chat_reactions as _describe_chat_reactions,
)
from .runtime.reactions import (
    maybe_react_on_message as _maybe_react_on_message,
)
from .runtime.reactions import (
    normalize_onebot_emoji_like as _normalize_onebot_emoji_like,
)
from .runtime.result_unknown import ResultUnknownLedger
from .runtime.video_pipeline import _MEDIA_RUNTIME_SINGLETON as _MEDIA_RUNTIME_SINGLETON
from .runtime.video_pipeline import _VIDEO_ACK_TEXT as _VIDEO_ACK_TEXT
from .runtime.video_pipeline import _VIDEO_ACK_THROTTLE as _VIDEO_ACK_THROTTLE
from .runtime.video_pipeline import _fetch_reply_video_file as _fetch_reply_video_file
from .runtime.video_pipeline import _get_media_registry as _get_media_registry
from .runtime.video_pipeline import _local_file_usable as _local_file_usable
from .runtime.video_pipeline import (
    _prepare_video_understanding_message as _prepare_video_understanding_message,
)
from .runtime.video_pipeline import _provider_enabled as _provider_enabled
from .runtime.video_pipeline import (
    _register_bot_sent_video_assets as _register_bot_sent_video_assets,
)
from .runtime.video_pipeline import (
    _video_understanding_enabled_now as _video_understanding_enabled_now,
)


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
from .sources.telegram_media import enrich_telegram_file_segments
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
        "bot.content",
        "bot.eat",
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
        # 网络/重 IO 命令能力：同步执行会把整个事件循环冻结数秒到数分钟
        # （点歌含 Playwright 渲染与音频下载，download 最长 300s），期间全部
        # 会话无响应，必须经 offload_capability 下放线程池。
        "bot.weather",
        # bot.eat 同样含 Playwright 渲染 + LLM 推荐，同步跑会阻塞事件循环数秒。
        "bot.eat",
        # bot.market 出釉瑚折线卡（Playwright 渲染 + 18 指数走势并行拉取）。
        "bot.market",
        # bot.stocks / bot.fx 与 market 同构：行情外呼 + 可选 Playwright 金融卡渲染。
        "bot.stocks",
        "bot.fx",
        # bot.alert --probe 是同步 urllib 凭据巡检（串行多平台可达数十秒），
        # 调度器路径已 to_thread，命令路径同款必须 offload（审计重发现 P1）。
        "bot.alert",
        "bot.music",
        "bot.wiki",
        "bot.epic",
        "bot.today_history",
        "bot.subscribe",
        "bot.meme_library",
        # bot.memory 的 retrieve/upsert 是同步 SQLite 写，留在事件循环内
        # 并发时会阻塞甚至 database is locked（审计#29）。
        "bot.memory",
        "bot.download",
        # bot.media_archive：媒体字节下载 + VLM 分析 + 落盘，重 IO 线程池执行。
        "bot.media_archive",
        "bot.search",
        "bot.affinity",
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
        memory_extract_on = bool(setting(
            "BOT_MEMORY_EXTRACT_ENABLED", config.bot_memory_extract_enabled))
        # R-进阶轨（默认关）：同一轮末后台预算内顺带抽取隐含提醒。
        reminder_extract_on = bool(
            getattr(config, "bot_reminder_llm_extract_enabled", False)
        ) and bool(getattr(config, "bot_reminder_enabled", True))
        if not (memory_extract_on or reminder_extract_on):
            return
        if not worker_lock.acquire(blocking=False):
            return  # Drop optional extraction, never queue an unbounded background workload.
        try:
            if time.monotonic() < cooldown_until:
                return
            provider = router.fork() if callable(getattr(router, "fork", None)) else router
            timeout = float(setting("BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS",
                                    getattr(config, "bot_memory_extract_timeout_seconds", 15.0)))

            def _generation_options(max_tokens: int) -> dict[str, Any]:
                return {
                    "override": str(setting("BOT_CHAT_MODEL", "") or ""),
                    "message_text": user_text,
                    "reasoning_effort": setting("BOT_CHAT_REASONING_EFFORT",
                                                getattr(config, "bot_chat_reasoning_effort", "")),
                    "timeout_seconds": timeout,
                    "deadline_monotonic": time.monotonic() + timeout,
                    "max_tokens": max_tokens,
                }

            if memory_extract_on:
                texts = extract_memory_texts(
                    provider, user_text=user_text, reply_text=reply_text,
                    generation_options=_generation_options(int(setting(
                        "BOT_MEMORY_EXTRACT_MAX_TOKENS",
                        getattr(config, "bot_memory_extract_max_tokens", 200)))),
                )
                if texts:
                    store_extracted_memories(repository, subject_user_id=sender_id,
                                             session_id=session_id, texts=texts)
            if reminder_extract_on:
                from plugins.bot_unified_runtime.character.memory_extract import (
                    extract_reminder_drafts,
                    store_extracted_reminders,
                )
                from plugins.bot_unified_runtime.character.reminders import (
                    build_reminder_store,
                )

                # session_id 形如 "group:<id>" / "private:<id>"（ingress 约定）。
                scope, _, target = session_id.partition(":")
                drafts = extract_reminder_drafts(
                    provider, user_text=user_text, reply_text=reply_text,
                    generation_options=_generation_options(120),
                )
                if drafts:
                    store_extracted_reminders(
                        build_reminder_store(config),
                        drafts=drafts,
                        session_key=session_id,
                        sender_id=sender_id,
                        target_scope=scope if scope in {"group", "private"} else "private",
                        target_id=target.strip() or sender_id,
                    )
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


def _onebot_segments_from_message_payload(payload: Any) -> list[dict[str, Any]]:
    """把 ``get_msg`` 返回的 message 字段归一成段列表（兼容 dict/对象两种形态）。"""
    message = payload
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("messages") or []
    segments: list[dict[str, Any]] = []
    for segment in message or ():
        if isinstance(segment, dict):
            seg_type = segment.get("type", "")
            seg_data = segment.get("data", {})
        else:
            seg_type = getattr(segment, "type", "")
            seg_data = getattr(segment, "data", {})
        if not seg_type:
            continue
        segments.append(
            {
                "type": str(seg_type),
                "data": dict(seg_data) if isinstance(seg_data, dict) else {},
            }
        )
    return segments


def _make_onebot_reply_lookup(bot: Any) -> Any:
    """构造注入给 collect_reply_chain 的异步反查器（失败一律返回 None）。"""

    async def _lookup(message_id: str) -> Any:
        getter = getattr(bot, "get_msg", None)
        if not callable(getter) or not message_id:
            return None
        try:
            payload = await asyncio.wait_for(
                getter(message_id=int(message_id)), timeout=3.0
            )
        except (asyncio.TimeoutError, ValueError, TypeError):
            return None
        except Exception:  # noqa: BLE001 - 反查失败按"取不到更深层"处理。
            return None
        segments = _onebot_segments_from_message_payload(payload)
        if not segments:
            return None
        sender_raw = (
            payload.get("sender")
            if isinstance(payload, dict)
            else getattr(payload, "sender", None)
        )
        sender = sender_raw if isinstance(sender_raw, dict) else {}
        return {
            "message_id": message_id,
            "message": segments,
            "sender": {
                "user_id": sender.get("user_id", ""),
                "nickname": sender.get("nickname") or sender.get("card") or "",
            },
        }

    return _lookup


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
    """动态好感度小名联动：文本以称呼形点到任一用户小名即视为被点名。

    小名来自 user_affinity.nickname（管理员/本人设置），数量有限，
    直接全表扫描即可（阻塞读仅群聊判定路径，量级可控）。
    必须用 detect_name_mention 的称呼形匹配而非子串包含：
    小名可能撞上常用词（如误学的“什么”），子串匹配会让
    “这是什么”“为什么”全部误判为点名。
    """
    if not text or _AFFINITY_NICKNAMES_CACHE is None:
        return False
    return detect_name_mention(text, _AFFINITY_NICKNAMES_CACHE)


_AFFINITY_NICKNAMES_CACHE: list[str] | None = None
_AFFINITY_NICKNAMES_LOADED_AT = 0.0

# 被动感知小名自学的停用词：“叫我什么/喊我名字”这类问句
# 会被正则误学成小名，命中即丢弃，不允许进入小名表。
_NICKNAME_STOPWORDS = {
    "什么", "啥", "谁", "哪个", "这些", "那些",
    "名字", "昵称", "外号", "这个", "那个", "啥子",
}


def _refresh_affinity_nicknames(affinity_store) -> None:
    global _AFFINITY_NICKNAMES_CACHE, _AFFINITY_NICKNAMES_LOADED_AT
    try:
        import sqlite3 as _sq

        connection = _sq.connect(affinity_store.db_path)
        try:
            rows = connection.execute(
                "SELECT nickname FROM user_affinity WHERE nickname != ''"
            ).fetchall()
        finally:
            # 读库异常时也必须关闭连接，否则 60s 一次的刷新会泄漏连接。
            connection.close()
        _AFFINITY_NICKNAMES_CACHE = [str(r[0]) for r in rows]
        _AFFINITY_NICKNAMES_LOADED_AT = time.time()
    except Exception:  # noqa: BLE001 - 小名加载失败不影响主链路。
        _AFFINITY_NICKNAMES_CACHE = []
    finally:
        # 失败也推进刷新时钟：否则持续失败时每条群消息都会在事件循环上
        # 重试一次同步 sqlite 连接（审计重发现 P3）。
        _AFFINITY_NICKNAMES_LOADED_AT = time.time()


def set_runtime_mention_terms(terms: list[str] | tuple[str, ...]) -> None:
    """在插件初始化时登记人格昵称，用于“只写名字也算点名”。"""
    global _RUNTIME_MENTION_TERMS
    _RUNTIME_MENTION_TERMS = [str(item).strip() for item in terms if str(item).strip()]


_TEXT_AT_MENTION_PATTERN = re.compile(r"@\s*([^\s@，。,@！!？?]{1,32})")
# 软边界：昵称后紧跟这些字/符号才算完整点名，防"@守岸人后援会"误报；
# 中文无词边界，用高频接续字白名单代替分词。
_AT_MENTION_SOFT_BOUNDARY = set("在吗哦呀吧的呢这那你是帮我忙看看去跟我给说讲下啦~")


def _detect_text_at_mention(text: str) -> bool:
    """复制/手打的纯文本 @（非平台 at 段）也算硬点名。

    平台真 @ 走 at 段检测（_detect_onebot_direct_mention）；用户从别处
    复制或手打的 "@小维/@岸宝" 只会落在 plain_text 里。名字候选 = 人格
    昵称 + 好感度小名（停用词除外）；只认 @ 后紧跟的称呼，普通问句
    与邮箱等含 @ 的无关文本不受影响。
    """
    if not text or "@" not in text:
        return False
    candidates = [str(term) for term in _RUNTIME_MENTION_TERMS if str(term).strip()]
    if _AFFINITY_NICKNAMES_CACHE:
        candidates.extend(
            str(item)
            for item in _AFFINITY_NICKNAMES_CACHE
            if str(item).strip() and str(item) not in _NICKNAME_STOPWORDS
        )
    if not candidates:
        return False
    for match in _TEXT_AT_MENTION_PATTERN.finditer(text):
        token = match.group(1).strip()
        for candidate in candidates:
            if candidate and token.startswith(candidate):
                rest = token[len(candidate):]
                if not rest or rest[0] in _AT_MENTION_SOFT_BOUNDARY:
                    return True
    return False

def contains_visual_message_segments(raw_segments: list[dict[str, Any]] | None) -> bool:
    """Return whether an event contains an image, sticker-like or video segment.

    只覆盖"看得到"的媒体——语音不在这里（见 contains_audio_message_segments），
    两者在 `_is_plain_chat_event` 里并列放行、在占位文案里分别命名。
    """
    visual_types = {"image", "face", "mface", "marketface", "sticker", "video"}
    return any(
        str(segment.get("type", "")).strip().lower() in visual_types
        for segment in raw_segments or []
    )


# 语音段类型：OneBot 用 record，Telegram 用 voice/audio。三者都要认——此前
# 只认 record，于是 Telegram 语音在入站侧完全不识别（评审需求 3）。
AUDIO_SEGMENT_TYPES = frozenset({"record", "voice", "audio"})

# 合并转发段类型：OneBot 用 forward，部分实现用 chat_history/messages。
# 转发消息的 plain_text **是空的**（正文要靠 get_forward_msg 反查），
# 若不在这里放行，路由会判 IGNORE → chat handler 不触发 → 抓正文的代码
# （在 handler 内部）永远跑不到，表现为"转发聊天记录给 bot 毫无回应"。
FORWARD_SEGMENT_TYPES = frozenset({"forward", "chat_history", "messages"})


def contains_forward_message_segments(raw_segments: list[dict[str, Any]] | None) -> bool:
    """是否含合并转发段（正文需异步反查，见 _forward_message_text）。"""
    return any(
        str(segment.get("type", "")).strip().lower() in FORWARD_SEGMENT_TYPES
        for segment in raw_segments or []
    )


def contains_audio_message_segments(raw_segments: list[dict[str, Any]] | None) -> bool:
    """是否含语音段（OneBot record / Telegram voice·audio）。

    关键：纯语音消息的 plain_text 为空 → 路由判 IGNORE → chat handler 不触发 →
    ASR 永远跑不到（链路本身完好，死在上游门禁）。故这里必须与视觉段并列放行。
    """
    return any(
        str(segment.get("type", "")).strip().lower() in AUDIO_SEGMENT_TYPES
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


_RUNTIME_HOT_OVERRIDE_FIELDS: tuple[tuple[str, str], ...] = (
    # 安静时间（纳入 store 后必须实时求值，否则 /bot runtime set 要等重启）
    ("BOT_QUIET_HOURS_ENABLED", "bot_quiet_hours_enabled"),
    ("BOT_QUIET_HOURS_START", "bot_quiet_hours_start"),
    ("BOT_QUIET_HOURS_END", "bot_quiet_hours_end"),
    ("BOT_QUIET_HOURS_TIMEZONE", "bot_quiet_hours_timezone"),
    ("BOT_QUIET_HOURS_SESSION_TYPES", "bot_quiet_hours_session_types"),
    ("BOT_QUIET_HOURS_BYPASS_ROLES", "bot_quiet_hours_bypass_roles"),
    # 群限流句数帽与情绪豁免
    ("BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR", "bot_rate_limit_group_max_per_hour"),
    ("BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE", "bot_rate_limit_group_max_per_minute"),
    ("BOT_RATE_LIMIT_EMOTION_EXEMPT", "bot_rate_limit_emotion_exempt"),
    # 群自动回复概率（与心情系数相乘，必须现算）
    ("BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY", "bot_group_chat_auto_reply_probability"),
    # 合并转发阈值
    ("BOT_RENDER_FORWARD_MIN_NODES", "bot_render_forward_min_nodes"),
    # 群摘要白/黑名单（名单外群跳过摘要注入；消费点 shared_group.py）
    ("BOT_GROUP_DIGEST_LIST_MODE", "bot_group_digest_list_mode"),
    ("BOT_GROUP_DIGEST_WHITELIST", "bot_group_digest_whitelist"),
    ("BOT_GROUP_DIGEST_BLACKLIST", "bot_group_digest_blacklist"),
    # 夜间每日群通讯总结主动推送（G-DIGEST；消费点 _register_digest_push_scheduler）
    ("BOT_GROUP_DIGEST_PUSH_ENABLED", "bot_group_digest_push_enabled"),
    ("BOT_GROUP_DIGEST_PUSH_TIME", "bot_group_digest_push_time"),
)


def _config_with_runtime_overrides(config: Any, runtime_settings: Any) -> Any:
    """把"热改参数"的运行时覆盖合并进 config（供判定时实时求值）。

    这些键已从 .env 移入运行时 store（避免"改了 .env 不生效 / 实际值与 .env
    漂移"），但消费方读的是 config 字段，因此每次判定做一次浅合并。
    没有任何覆盖时直接返回原对象，零额外开销。
    """
    if runtime_settings is None:
        return config
    updates: dict[str, Any] = {}
    for env_key, field_name in _RUNTIME_HOT_OVERRIDE_FIELDS:
        try:
            value = runtime_settings.get(env_key, None)
        except Exception as exc:  # noqa: BLE001 - store 读取失败按未覆盖处理。
            logging.getLogger(__name__).debug(
                "hot override read failed key=%s error=%s", env_key, type(exc).__name__
            )
            continue
        if value is None or value == "":
            continue
        current = getattr(config, field_name, None)
        if value != current:
            updates[field_name] = value
    if not updates:
        return config
    try:
        return config.model_copy(update=updates)
    except Exception:  # noqa: BLE001 - 合并失败回退原 config。
        return config


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


# 默认回退值；实际由配置 bot_forward_fetch_timeout_seconds 注入。
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


def _forward_message_text_sync(result: Any) -> str:
    """把 get_forward_msg 的回执解析成正文（容忍多种形态）。

    历史实现只认 ``result["messages"][*]["message"][*]`` 的 dict 嵌套，且**任何**
    异常都被静默吞掉；只要 NapCat 换成对象形态 / 改字段名 / 带 shell 包装，
    整条转发就表现为"bot 毫无回应且日志无痕"。这里做归一 + 带发送者前缀。
    """
    if result is None:
        return ""
    payload = result
    # 有些实现把业务数据包在 data 里
    if isinstance(payload, dict) and "messages" not in payload and "data" in payload:
        inner = payload.get("data")
        if isinstance(inner, dict):
            payload = inner
    if hasattr(payload, "messages"):
        payload = payload.messages
    # 取消息列表：dict 形态取 messages / message 键；对象形态取同名属性。
    if isinstance(payload, dict):
        messages = payload.get("messages")
        if messages is None:
            messages = payload.get("message")
    else:
        messages = getattr(payload, "messages", None)
        if messages is None:
            messages = getattr(payload, "message", None)
    if not isinstance(messages, list):
        return ""
    lines: list[str] = []
    for item in messages:
        if isinstance(item, dict):
            segments = item.get("message") or item.get("segments") or item.get("content") or []
            sender = item.get("sender") or {}
            nickname = ""
            if isinstance(sender, dict):
                nickname = str(sender.get("card") or sender.get("nickname") or "").strip()
        else:
            segments = getattr(item, "message", None) or getattr(item, "segments", None) or []
            sender = getattr(item, "sender", None)
            nickname = ""
            if sender is not None:
                nickname = str(
                    getattr(sender, "card", "") or getattr(sender, "nickname", "") or ""
                ).strip()
        if hasattr(segments, "extract_plain_text"):
            text = str(segments.extract_plain_text() or "").strip()
        else:
            parts: list[str] = []
            for segment in segments or []:
                if isinstance(segment, dict):
                    seg_type = str(segment.get("type", ""))
                    data = segment.get("data") or {}
                else:
                    seg_type = str(getattr(segment, "type", ""))
                    data = getattr(segment, "data", {}) or {}
                if seg_type == "text":
                    value = str(data.get("text", "")).strip() if isinstance(data, dict) else ""
                    if value:
                        parts.append(value)
                elif seg_type == "image":
                    parts.append("[图片]")
                elif seg_type in AUDIO_SEGMENT_TYPES:
                    parts.append("[语音]")
                elif seg_type == "video":
                    parts.append("[视频]")
            text = " ".join(parts).strip()
        if text:
            lines.append(f"{nickname}：{text}" if nickname else text)
    return "\n".join(lines)


async def _forward_message_text(
    bot: Any, event: Any, timeout_seconds: float | None = None
) -> str:
    """读取合并转发（forward）消息正文；失败返回空串并留 warning。

    只在消息确实包含 forward 段时才调用 NapCat 的 get_forward_msg。
    普通消息 id 不是合并转发 id，NapCat 会拒绝为"消息已过期或者为
    内层消息"；带上限超时是为了防止上游回执异常时卡住消息处理。

    失败必须**可观测**：早期版本把异常全吞掉，导致"转发无回应"现场没有任何
    线索（本次排查即因此耗时）。现在失败路径固定打一条 warning。
    """
    forward_id = _forward_segment_id(event)
    if not forward_id:
        return ""
    call_api = getattr(bot, "call_api", None)
    if not callable(call_api):
        logging.getLogger(__name__).warning("forward message fetch skipped: bot has no call_api")
        return ""
    timeout = float(timeout_seconds or _FORWARD_MESSAGE_API_TIMEOUT_SECONDS)
    try:
        result = await asyncio.wait_for(
            call_api("get_forward_msg", message_id=forward_id),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logging.getLogger(__name__).warning("forward message fetch timed out after %.1fs id=%s", timeout, forward_id)
        return ""
    except Exception as exc:  # noqa: BLE001 - 上游回执异常不阻断消息处理。
        logging.getLogger(__name__).warning(
            "forward message fetch failed id=%s type=%s detail=%s",
            forward_id,
            type(exc).__name__,
            str(exc)[:160],
        )
        return ""
    text = _forward_message_text_sync(result)
    if not text:
        logging.getLogger(__name__).warning(
            "forward message fetch returned no text id=%s result_type=%s",
            forward_id,
            type(result).__name__,
        )
    return text


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


# ffmpeg 能直接解码的音频后缀；SILK 裸流（QQ 语音常态）不在其中。
_RECORD_CONVERTIBLE_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".amr"}


async def _transcode_record_segments(bot: Any, raw_segments: list[dict[str, Any]]) -> None:
    """把 ffmpeg 解不了的语音段经 OneBot get_record 预转码成 mp3。

    NapCat 收到的 QQ 语音落盘是 SILK 裸流（.slk），ffmpeg 无法解码，
    转写链路会静默降级；get_record(out_format=mp3) 让适配器自行转码
    后把新路径写入段 data.transcoded_path。任何失败静默跳过，段保持原样。
    """
    from pathlib import Path as _Path

    for segment in raw_segments:
        if str(segment.get("type", "")).lower() != "record":
            continue
        data = segment.get("data") or {}
        if not isinstance(data, dict) or data.get("transcoded_path"):
            continue
        local = str(data.get("file") or data.get("path") or "").strip()
        suffix = _Path(local).suffix.lower() if local else ""
        if suffix in _RECORD_CONVERTIBLE_SUFFIXES:
            continue
        file_id = str(data.get("file_id") or data.get("file") or "").strip()
        if not file_id:
            continue
        try:
            # NapCat 偶发挂起不返回：无超时会把这个用户的后续消息永久卡死。
            result = await asyncio.wait_for(
                bot.call_api("get_record", file_id=file_id, out_format="mp3"),
                timeout=20.0,
            )
        except Exception as exc:  # noqa: BLE001 - 适配器不支持/超时/转码失败时保持原段。
            logging.getLogger(__name__).debug(
                "get_record skipped type=%s", type(exc).__name__
            )
            continue
        transcoded = str((result or {}).get("file") or "").strip()
        if transcoded and _Path(transcoded).suffix.lower() in _RECORD_CONVERTIBLE_SUFFIXES:
            data["transcoded_path"] = transcoded


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
    segments: list[dict[str, Any]] | None = None,
    reply_chain: list[Any] | None = None,
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

    # 调用方可传入已富化（如 get_record 预转码）的段；缺省从事件提取。
    raw_segments = (
        segments if segments is not None else _extract_onebot_raw_segments(event)
    )
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
    if not text.strip() and (contains_visual_message_segments(raw_segments) or contains_audio_message_segments(raw_segments)):
        # 占位文案按实际媒体类型命名：纯语音此前既进不来也无法被说明（需求 3）。
        if contains_audio_message_segments(raw_segments):
            text = "（用户发送了语音消息，未附文字。）"
        else:
            text = "（用户发送了图片/表情包/视频，未附文字。）"
    # 引用链（评审需求 1/2）：结构化、递归、逐层预算、已消毒。
    # 修复前：QQ 侧对 `event.reply` 取 get_plaintext()/.text —— OneBot V11 的
    # Reply 模型没有这两个属性，reply_text **恒为空**，被引用内容完全不进提示词；
    # Telegram 侧只读第一层，而适配器其实递归解析了 reply_to_message。
    # `reply_chain` 可由调用方**预先异步解析**（含 get_msg 反查的更深层）后传入，
    # 这样本函数保持同步、纯函数可测。
    reply_chain = list(reply_chain) if reply_chain is not None else collect_reply_chain(event)
    reply_text = reply_chain[0].text if reply_chain else ""
    reply_id = getattr(event, "reply_to_message_id", None) or getattr(event, "reply_to_msg_id", None)
    if reply_id is None:
        quote_segment = next((item for item in normalized_message.segments if item.get("type") == "quote"), None)
        if quote_segment:
            reply_id = (quote_segment.get("data") or {}).get("id") or (quote_segment.get("data") or {}).get("message_id")
    if reply_id is None and reply_chain and reply_chain[0].message_id:
        # OneBot 的 reply 段只有 id，适配器把它放在 event.reply.message_id；
        # 引用链已经解出该值，回填以便"回复机器人自己视频"等下游判定可用。
        reply_id = reply_chain[0].message_id
    # 纯文本 @ 只认用户自己打的字：必须在被引用文本拼接**之前**检测，
    # 防止引用内容里的 "@某人" 被当成用户对本机器人的点名。
    # 注意：下面的拼接是同一行内的字符串表达式，旧代码把本行放在拼接之后，
    # 使注释声明的语义并未成立（评审 L1）；这里保持在拼接前。
    own_text = text
    text_at_mention = _detect_text_at_mention(own_text)
    if reply_text:
        text = f"{text}\n{format_reply_chain(reply_chain)}".strip()
    is_tome = getattr(event, "is_tome", None)
    adapter_mentions_bot = bool(is_tome()) if callable(is_tome) else False
    # 点名判定：
    # - 人格名（岸宝/守岸人…）与策展昵称是**真点名**语义，两边都算——人格展示名
    #   可能并不出现在 _RUNTIME_MENTION_TERMS 里，只查拼接前文本会漏判（实测回归）。
    # - 好感度自学习小名常撞常用词，只认用户自己打的字：被引用内容里出现"岸宝"
    #   不应让机器人以为是叫自己（评审 L1）。
    persona_name_mention = detect_name_mention(
        own_text, _RUNTIME_MENTION_TERMS
    ) or detect_name_mention(text, _RUNTIME_MENTION_TERMS)
    affinity_nickname_mention = _mentioned_by_affinity_nickname(own_text)
    hard_mention = adapter_mentions_bot or (
        normalized_adapter not in {"telegram", "mail"}
        and _detect_onebot_direct_mention(raw_segments, bot_id)
    )
    if not hard_mention:
        if text_at_mention:
            hard_mention = True
        elif reply_id:
            # 回复机器人自己发过的视频 = 明确的追问意图，等同硬点名
            # （档案 bot_sent 锚点可查；回复别人的视频不算）。
            registry = _get_media_registry()
            replied_asset = None
            if registry is not None:
                try:
                    replied_asset = registry.lookup_by_message_id(str(reply_id))
                except Exception:  # noqa: BLE001 - 档案库读失败按未命中处理。
                    replied_asset = None
            if (
                replied_asset is not None
                and str(getattr(replied_asset, "source_kind", "")) == "bot_sent"
            ):
                hard_mention = True
    # 私聊/邮件永远回复，软硬之分无意义。触发语义分层（2026-09-11「叫岸宝没反应」修复）：
    # - 策展人格昵称（岸宝/守岸人/小岸同学/我的蒙娜丽莎/第二实例…）= 真点名：
    #   经由 mentions_bot 等同 @，white1/未名单群直接应答，white2 严格群也应答；
    # - 好感度自学习小名常撞常用词（可能误学「什么」这类词），无硬点名时仅记
    #   name_mention_only 供 white2 严格门判定，不主动接话。
    name_mention_only = (
        affinity_nickname_mention
        and not persona_name_mention
        and not hard_mention
        and session_type not in {SessionType.PRIVATE, SessionType.EMAIL}
    )
    # R4 场景化回应：策展昵称软点名（无硬 @/回复 bot）单独标记，供门禁把
    # 「长文本里顺带提到名字」与「真在叫机器人」区分开。
    soft_persona_mention = (
        persona_name_mention
        and not hard_mention
        and session_type not in {SessionType.PRIVATE, SessionType.EMAIL}
    )
    # 评审D2：QQ 摄取层填充 sender_display_name——OneBot v11 群内 card=群名片、
    # nickname=昵称，card 优先；strip 后为空不传（保持 None，称谓链回退不变）。
    # TG/Mail 事件无 sender.card/nickname 形态，自然落 None（各有独立摄取路径，不在此扩）。
    onebot_sender = getattr(event, "sender", None)
    sender_card = str(getattr(onebot_sender, "card", None) or "").strip()
    sender_nickname = str(getattr(onebot_sender, "nickname", None) or "").strip()
    sender_platform_role = str(getattr(onebot_sender, "role", None) or "").strip() or None
    sender_title = str(getattr(onebot_sender, "title", None) or "").strip() or None
    group_title = str(getattr(event, "group_title", None) or "").strip() or None
    sender_display_name = sender_card or sender_nickname or None
    if group_id is not None:
        _remember_group_images(
            str(group_id), normalized_message.segments or raw_segments
        )
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
        reply_chain=reply_chain,
        thread_id=str(getattr(event, "message_thread_id", "") or "") or None,
        mentions_bot=(
            session_type in {SessionType.PRIVATE, SessionType.EMAIL}
            or hard_mention
            or (persona_name_mention and not hard_mention)
        ),
        name_mention_only=name_mention_only,
        soft_persona_mention=soft_persona_mention,
        message_id=str(message_id) if message_id is not None else None,
        sender_display_name=sender_display_name,
        sender_platform_role=sender_platform_role,
        sender_card=sender_card or None,
        sender_nickname=sender_nickname or None,
        sender_title=sender_title,
        group_title=group_title,
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
            # 凭据探测是同步 urllib HTTP（串行多平台可达数十秒），必须下放线程，
            # 否则巡检期间整个事件循环冻结、全部会话无响应。
            reports = await asyncio.to_thread(
                check_credentials_and_report, config, probe=True
            )
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
    render_backend: Any = None,
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

    # 评审C1 产品裁定：推送调度器保持纯文字、不注入渲染后端——定时推送运行在
    # 调度线程，不依赖 Playwright 渲染进程。显式 render_backend=None 是有意为之，
    # 勿改回注入；交互出卡由下方 interactive_capability 分流承担。
    capability = build_today_history_capability(
        config,
        provider=provider,
        push_file=push_file,
        on_subscriptions_changed=_resync_jobs,
        render_backend=None,
    )
    # 评审C1：交互路径（today_history matcher）复用同一 provider/推送表/订阅重挂，
    # 但注入渲染后端出卡——与推送能力分流，互不影响。
    interactive_capability = build_today_history_capability(
        config,
        provider=provider,
        push_file=push_file,
        on_subscriptions_changed=_resync_jobs,
        render_backend=render_backend,
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
        # 评审C1：交互 matcher 用这个（注入后端）；"capability" 仅供定时推送（纯文字）。
        "interactive_capability": interactive_capability,
        "resync": _resync_jobs,
        "provider": provider,
    }


def _register_kb_wiki_sync_scheduler(scheduler: Any, config: Any) -> dict:
    """Crawl Wiki 知识库每日增量同步（23:00 导出之后）+ 启动补同步。

    同步 → 嵌入 → ANN/FTS 重建都在 job 线程串行执行，与共享 store 实例
    协作（同步完成后进程内检索器即时可见）；日常无变更时零开销。
    """
    registered = {"registered": False}

    def _sync_job() -> None:
        try:
            from nonebot.log import logger

            from .character.kb_wiki import _get_shared_store, run_kb_sync_task

            summary = run_kb_sync_task(
                config,
                full=False,
                store=_get_shared_store(config),
            )
            level = logger.info if summary.get("ok") else logger.warning
            level(
                "kb_wiki_sync done: {}",
                summary.get("public_message")
                or f"error_kind={summary.get('error_kind')}",
            )
        except Exception as exc:  # noqa: BLE001 - 同步失败不影响 Bot 主链路。
            try:
                from nonebot.log import logger

                logger.warning("kb_wiki_sync failed: {}", type(exc).__name__)
            except Exception:  # noqa: S110, BLE001
                pass

    hour = max(0, min(23, int(getattr(config, "bot_kb_wiki_sync_hour", 23) or 23)))
    minute = max(0, min(59, int(getattr(config, "bot_kb_wiki_sync_minute", 40) or 40)))
    scheduler.add_job(
        _sync_job,
        "cron",
        id="kb_wiki_sync_daily",
        replace_existing=True,
        hour=hour,
        minute=minute,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )
    if bool(getattr(config, "bot_kb_wiki_sync_on_startup", True)):
        # 开机补偿：错过的夜间同步在启动后 45 秒补跑一次（增量路径，
        # 无变更时毫秒级；首轮未灌库时也只是空 updates，不触发全量）。
        from datetime import datetime, timedelta

        scheduler.add_job(
            _sync_job,
            "date",
            id="kb_wiki_sync_startup",
            replace_existing=True,
            misfire_grace_time=300,
            run_date=datetime.now().astimezone() + timedelta(seconds=45),
        )
    registered["registered"] = True
    return registered


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


# ---- 群聊最近图片上下文（vis3 2026-09-13 用户指令）----
# 实战：群里别人刚发图，另一用户 @bot "总结一下"——vision 只看提问者自带图，
# 读不到图。环形缓存按群记最近 5 分钟的 http 图片（最多 5 张），chat 在
# 「无自带图 + 文本带看图意图」时注入最新一张（标注"取自群里最近图片"）。
_GROUP_RECENT_IMAGES: dict[str, deque[tuple[float, str]]] = {}
_GROUP_RECENT_IMAGE_TTL_SECONDS = 300.0
_GROUP_RECENT_IMAGE_MAX = 5
_VISION_HINT_RE = re.compile(
    r"总结|概括|识别|看看|看一下|这图|什么图|分析|读懂|描述|梳理|讲了什么|说了什么"
)


def _remember_group_images(group_id: str, segments: list[dict[str, Any]]) -> None:
    """摄取侧登记：群消息里的 http 图片进环形缓存（进程内，重启即清）。"""
    now = time.monotonic()
    bucket = _GROUP_RECENT_IMAGES.setdefault(
        str(group_id), deque(maxlen=_GROUP_RECENT_IMAGE_MAX)
    )
    for segment in segments:
        if str(segment.get("type", "")).strip().lower() != "image":
            continue
        url = str((segment.get("data") or {}).get("url") or "")
        if url.startswith("http"):
            bucket.append((now, url))


def _latest_fresh_group_image(group_id: str, now: float) -> str:
    """取群内 TTL 内最新一张 http 图片；过期条目（最旧端）顺手清理。"""
    bucket = _GROUP_RECENT_IMAGES.get(str(group_id))
    if not bucket:
        return ""
    while bucket and now - bucket[0][0] > _GROUP_RECENT_IMAGE_TTL_SECONDS:
        bucket.popleft()
    return bucket[-1][1] if bucket else ""


def _learned_name_is_admin_identity(name: str, config: Any) -> bool:
    """自学习昵称护栏（2026-09-13 实战）：管理团队档案名是身份不是外号。

    实战事故：霞月的 QQ 说过"叫我澜汐更顺口"式的话，"澜汐"被学成她的
    昵称，称谓注入张冠李戴（bot 把霞月当澜汐）。护栏：学习到的昵称若
    命中任何管理档案的 name/nicknames，一律不学——身份名只能来自配置。
    """
    target = str(name or "").strip()
    if not target:
        return False
    for profile in getattr(config, "bot_admin_profiles", []) or []:
        if not isinstance(profile, dict):
            continue
        names = {str(profile.get("name") or "").strip()}
        for part in str(profile.get("nicknames") or "").replace("／", "/").split("/"):
            part = part.strip()
            if part:
                names.add(part)
        if target in names:
            return True
    return False


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


# C14: 解析卡每条消息都要头像 URL，而查询走适配器 RPC（1.2s 超时）；
# 按 self_id 缓存 600s，避免每条消息一次跨进程调用。配置头像优先且不缓存。
# F3（2026-09-14 素材本地化）：本地缓存 file URI 插队到远端链之前——命中
# 即直接返回，不占用也不刷新 600s 远端缓存，help 卡/派发卡不再周期回源。
_BOT_AVATAR_URL_CACHE: dict[str, tuple[float, str]] = {}
_BOT_AVATAR_URL_TTL_SECONDS = 600.0


def _refresh_local_bot_avatar(bot_id: str, config: Config) -> str:
    """连接钩子的同步下载体：qlogo → Runtime data/avatar/ 本地缓存。"""
    from .output.bot_avatar import refresh_from_qq

    data_dir = str(getattr(config, "bot_runtime_data_dir", "data") or "data")
    root = Path(data_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / data_dir
    return refresh_from_qq(bot_id, root)


async def _resolve_bot_avatar_url(bot: Any, config: Config) -> str:
    """Resolve the bot avatar: configured URL > local cached file > remote.

    F3（2026-09-14 素材本地化）：本地头像文件存在即直接用 file URI（经
    output.bot_avatar.bot_avatar_uri 统一入口，含内存登记与磁盘兜底发现），
    不再进入 NapCat RPC / qlogo 远端链——消灭 600s TTL 周期性 Chromium
    回源。本地缺失才走既有远端链，其语义原样保留（RPC/qlogo 回退、600s
    缓存、最终空串由卡片回落「守」字圆点）。
    """
    configured = str(getattr(config, "bot_persona_avatar_url", "") or "").strip()
    if configured:
        return configured
    from .output.bot_avatar import bot_avatar_uri

    local_uri = bot_avatar_uri(config)
    if local_uri:
        return local_uri
    self_id = str(getattr(bot, "self_id", "") or "").strip()
    if not self_id:
        return ""
    now = time.monotonic()
    cached = _BOT_AVATAR_URL_CACHE.get(self_id)
    if cached is not None and cached[0] > now:
        return cached[1]
    url = await _lookup_bot_avatar_url(bot, self_id)
    _BOT_AVATAR_URL_CACHE[self_id] = (now + _BOT_AVATAR_URL_TTL_SECONDS, url)
    return url


async def _lookup_bot_avatar_url(bot: Any, self_id: str) -> str:
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


# C14: 内容解析注册表构建要绑定 cookie/代理/Playwright 后端，每条消息重建纯浪费；
# 单槽缓存按 cookies 文件 mtime 失效——文件热更新后下一条消息自动重建。
_CONTENT_REGISTRY_CACHE: dict[str, tuple[tuple[Any, ...], Any]] = {}


def _cached_content_parser_registry(config: Config, playwright_backend: Any) -> Any:
    """按 cookies 文件 mtime 缓存 build_content_parser_registry 结果。"""
    from plugins.bot_unified_runtime.sources.parsers import (
        build_content_parser_registry,
        build_cookie_provider,
    )

    cookies_path = str(getattr(config, "bot_cookies_file", "") or "")
    try:
        cookies_stamp = Path(cookies_path).stat().st_mtime_ns if cookies_path else 0
    except OSError:
        cookies_stamp = -1
    platforms = tuple(getattr(config, "bot_content_parse_platforms", []) or [])
    proxy = str(getattr(config, "bot_download_proxy", "") or "")
    key = (cookies_path, cookies_stamp, platforms, proxy)
    cached = _CONTENT_REGISTRY_CACHE.get("single")
    if cached is not None and cached[0] == key:
        return cached[1]
    built = build_content_parser_registry(
        list(platforms) or None,
        cookie_provider=build_cookie_provider(config),
        proxy=proxy,
        playwright_backend=playwright_backend,
    )
    _CONTENT_REGISTRY_CACHE["single"] = (key, built)
    return built


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
    receipt = await gateway.deliver(bot, event, send_request)
    _register_bot_sent_video_assets(send_request, receipt)
    return receipt
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


# 进程级共享好感度 store（与 kb_wiki._SHARED_STORES 同模式）：每条聊天消息
# 都会走这里，DynamicAffinityStore 构造即建连接+建表，每次操作再各开新连接；
# 复用单例消除热路径上的重复 schema ensure 与连接风暴（store 自身带锁线程安全）。
_AFFINITY_STORES: dict[str, Any] = {}
_AFFINITY_STORES_LOCK = threading.Lock()


def _reset_affinity_store_cache() -> None:
    """清空共享 store 缓存（测试用）。"""
    with _AFFINITY_STORES_LOCK:
        _AFFINITY_STORES.clear()


def build_character_affinity_store(config: object):
    from .character.affinity import DynamicAffinityStore
    from .character.providers import build_runtime_data_path

    if not getattr(config, "bot_affinity_enabled", True):
        return None
    db_path = build_runtime_data_path(
        config, str(getattr(config, "bot_affinity_db_path", "data/user_affinity.sqlite3"))
    )
    cache_key = str(db_path)
    with _AFFINITY_STORES_LOCK:
        store = _AFFINITY_STORES.get(cache_key)
        if store is None:
            store = DynamicAffinityStore(db_path)
            _AFFINITY_STORES[cache_key] = store
        return store


# 进程级共享 bot 心情 store（L1）：与好感度 store 同模式（构造即建连接+建表，
# 复用单例消除热路径重复 schema ensure；store 自身带锁线程安全）。
_MOOD_STORES: dict[str, Any] = {}
_MOOD_STORES_LOCK = threading.Lock()


def build_character_mood_store(config: object):
    from .character.mood import BotMoodStore
    from .character.providers import build_runtime_data_path

    if not getattr(config, "bot_mood_enabled", True):
        return None
    db_path = build_runtime_data_path(
        config, str(getattr(config, "bot_mood_db_path", "data/bot_mood.sqlite3"))
    )
    cache_key = str(db_path)
    with _MOOD_STORES_LOCK:
        store = _MOOD_STORES.get(cache_key)
        if store is None:
            store = BotMoodStore(
                db_path,
                half_life_minutes=float(
                    getattr(config, "bot_mood_half_life_minutes", 120.0)
                ),
                baseline_arousal=float(
                    getattr(config, "bot_mood_baseline_arousal", 0.3)
                ),
                rate_cap_per_hour=float(
                    getattr(config, "bot_mood_rate_cap_per_hour", 0.5)
                ),
            )
            _MOOD_STORES[cache_key] = store
        return store


def _build_reactions_describe(config: object):
    """返回 (session_id) -> str 的【表情回应】分区正文闭包；未启用返回 None。"""
    if not bool(getattr(config, "bot_reactions_enabled", True)):
        return None

    def _describe(session_id: str) -> str:
        return _describe_chat_reactions(str(session_id or ""))

    return _describe


def _build_mood_describe(config: object):
    """返回 () -> str 的心情描述闭包（自然语言、无数值）；未启用返回 None。"""
    store = build_character_mood_store(config)
    if store is None:
        return None

    def _describe() -> str:
        return store.describe(store.snapshot())

    return _describe


def _mood_valence(config: object) -> float:
    """bot 心情 valence（-1..1）；未启用/失败回退 0.0（中性，情绪档不介入）。"""
    try:
        store = build_character_mood_store(config)
        if store is None:
            return 0.0
        return float(store.snapshot().valence)
    except Exception:  # noqa: BLE001 - 心情层失败不改变回复行为。
        return 0.0


def _mood_willingness_factor(config: object) -> float:
    """bot 心情 → 群聊开火概率系数 [0.75, 1.25]；任何失败回退 1.0（只调概率，不做硬开关）。"""
    try:
        store = build_character_mood_store(config)
        if store is None:
            return 1.0
        return float(store.willingness_factor(store.snapshot()))
    except Exception:  # noqa: BLE001 - 心情层失败不改变回复行为。
        return 1.0


# 进程级共享 L4 quirk store（审核制演化区）：与心情 store 同模式。
_QUIRK_STORES: dict[str, Any] = {}
_QUIRK_STORES_LOCK = threading.Lock()


def build_character_quirk_store(config: object):
    from .character.providers import build_runtime_data_path
    from .character.quirks import QuirkStore

    if not getattr(config, "bot_quirks_enabled", True):
        return None
    db_path = build_runtime_data_path(
        config,
        str(getattr(config, "bot_quirks_db_path", "data/persona_quirks.sqlite3")),
    )
    cache_key = str(db_path)
    with _QUIRK_STORES_LOCK:
        store = _QUIRK_STORES.get(cache_key)
        if store is None:
            store = QuirkStore(db_path)
            _QUIRK_STORES[cache_key] = store
        return store


def _build_quirks_describe(config: object):
    """返回 () -> str 的 quirk 提示区闭包（审核通过才渲染）；未启用返回 None。"""
    store = build_character_quirk_store(config)
    if store is None:
        return None
    max_active = int(getattr(config, "bot_quirks_max_active", 6))

    def _describe() -> str:
        return store.render_prompt_section(max_active=max_active)

    return _describe


# 进程级共享会话身份 store（管理员设置的每群/每私聊称呼与标签）。
_IDENTITY_STORES: dict[str, Any] = {}
_IDENTITY_STORES_LOCK = threading.Lock()


def build_session_identity_store(config: object):
    from .character.providers import build_runtime_data_path
    from .character.session_identity import SessionIdentityStore

    db_path = build_runtime_data_path(
        config,
        str(getattr(config, "bot_session_identity_db_path", "data/session_identity.sqlite3")),
    )
    cache_key = str(db_path)
    with _IDENTITY_STORES_LOCK:
        store = _IDENTITY_STORES.get(cache_key)
        if store is None:
            store = SessionIdentityStore(db_path)
            _IDENTITY_STORES[cache_key] = store
        return store


def _build_identity_describe(config: object):
    """返回 (session_key) -> str 的会话身份渲染闭包；未启用返回 None。"""
    store = build_session_identity_store(config)

    def _describe(session_key: str) -> str:
        return store.render_prompt_section(session_key)

    return _describe


def _register_reflection_scheduler(scheduler: Any, config: Any) -> dict:
    """反思回路夜间任务：每日归纳 conversation_turns → 用户事实 + 会话摘要。

    同步 job 跑在 APScheduler 线程池（与 kb_wiki 同款，不阻塞事件循环）；
    无 turns 库/无轮次时 run_nightly_reflection 返回 skipped，静默跳过。

    **启动补偿（本轮新增）**：只挂 04:30 的 cron 会有一个真实漏洞——进程在
    04:30 时不在运行（重启/维护/崩溃）时当天反思永久丢失，下一次要等一整天。
    实测就该数据库一直零行的现象即由此放大。这里在启动时补一次：
    若"今天"还没有 digest，就用 misfire 容忍窗口立即补跑一次。
    """

    def _reflection_job() -> None:
        try:
            from nonebot.log import logger

            from .character.reflection import run_nightly_reflection

            summarizer = None
            if bool(getattr(config, "bot_reflection_llm_enabled", False)):
                from .character.reflection import LLMSummarizer

                summarizer = LLMSummarizer(build_model_router(config))
            logger.info(
                "reflection: {}", run_nightly_reflection(config, summarizer=summarizer)
            )
        except Exception as exc:  # noqa: BLE001 - 夜间任务失败不影响主链路。
            from nonebot.log import logger

            logger.warning(
                "reflection failed: {}", type(exc).__name__
            )

    hour = max(0, min(23, int(getattr(config, "bot_reflection_hour", 4) or 4)))
    minute = max(0, min(59, int(getattr(config, "bot_reflection_minute", 30) or 30)))
    scheduler.add_job(
        _reflection_job,
        "cron",
        id="bot_reflection_daily",
        replace_existing=True,
        hour=hour,
        minute=minute,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )
    # 启动补偿：当天还没跑过就立刻补一次（跑在调度线程池，不阻塞启动）。
    catch_up = _should_catch_up_reflection(config)
    if catch_up:
        try:
            scheduler.add_job(
                _reflection_job,
                "date",
                id="bot_reflection_catch_up",
                replace_existing=True,
                run_date=None,  # 立即
                misfire_grace_time=3600,
                max_instances=1,
            )
        except Exception:  # noqa: BLE001 - 补偿任务挂不上不影响 cron 本身。
            catch_up = False
    return {"hour": hour, "minute": minute, "catch_up": catch_up}


def _should_catch_up_reflection(config: Any) -> bool:
    """今天是否还没有反思 digest（需要启动补偿）。只读，失败按不补处理。"""
    try:
        import sqlite3
        from contextlib import closing
        from datetime import datetime

        path = str(getattr(config, "bot_reflection_db_path", "") or "").strip()
        if not path:
            return False
        today = datetime.now().astimezone().date().isoformat()
        with closing(sqlite3.connect(path)) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM reflection_digests WHERE scope_date = ?",
                (today,),
            ).fetchone()
        return int(row[0] if row else 0) == 0
    except Exception:  # noqa: BLE001 - 判断失败就不补，避免重复跑。
        return False


async def _deliver_due_reminders(
    config: Any,
    send_queue: Any,
    audit_logger: Any = None,
    receipt_repository: Any = None,
    all_online_bots: Any = None,
) -> int:
    """到点提醒一次性投递：submit 后**内联投递**，送达才销账。返回送达数。

    默认配置是内存发送队列——``InMemorySendQueue.submit`` 只入列并回假
    sent 回执、没有任何网络调用（sender/queue.py），只 submit 不投递等于
    提醒永不送达（2026-09-14 审查 A-01）。这里与订阅推送同范式就地投递；
    失败不销账留待下一轮重投，重投前先查回执仓——SQLite 队列的 worker
    在 60s 内联宽限期后可能已送出，此时直接销账不再重发（防双发）；
    长期投不出由 store 的顺延/作废策略兜底。
    """
    from .character.reminders import build_reminder_store, build_reminder_text
    from .contracts import (
        PrivacyLevel,
        RenderedOutput,
        SendPolicy,
        SendRequest,
        SessionType,
    )

    store = build_reminder_store(config)
    delivered = 0
    for reminder in store.due():
        request_id = f"reminder-{reminder.reminder_id}"
        scope = SessionType(reminder.target_scope)
        privacy = (
            PrivacyLevel.GROUP if scope is SessionType.GROUP else PrivacyLevel.PERSONAL
        )
        prior = None
        if receipt_repository is not None:
            try:
                prior = receipt_repository.latest(request_id)
            except Exception:  # noqa: BLE001 - 回执查询失败按无回执处理。
                prior = None
        if prior is not None and prior.state in {
            ReceiptState.SENT,
            ReceiptState.REDIRECTED,
        }:
            store.mark_done(reminder.reminder_id)
            delivered += 1
            continue
        request = SendRequest(
            request_id=request_id,
            session_id=reminder.session_key,
            target_scope=scope,
            target_id=reminder.target_id,
            capability_id="bot.reminder",
            content=RenderedOutput(
                request_id=request_id,
                content_type="text",
                content_ref={},
                text_fallback=build_reminder_text(reminder),
                privacy_level=privacy,
            ),
            send_policy=SendPolicy.QUEUED,
            priority="normal",
            max_messages=1,
            dedupe_key=f"reminder:{reminder.reminder_id}",
            cooldown_key=f"reminder:{reminder.session_key}",
            privacy_level=privacy,
            persona_profile_id=str(
                getattr(config, "bot_persona_profile_id", "default")
            ),
            adapter=reminder.adapter,
            bot_id=reminder.bot_id,
            audit_tags=["reminder", "due"],
        )
        send_queue.submit(request)
        sent_request = _find_sent_request(send_queue, request_id) or request
        bot = (
            _select_queue_bot(all_online_bots, sent_request)
            if all_online_bots is not None
            else None
        )
        receipt = None
        if bot is not None:
            try:
                receipt = await _deliver_transport_send_request(
                    bot,
                    None,
                    sent_request,
                    audit_logger,
                    receipt_repository,
                    send_queue,
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - 单条投递失败不影响其余提醒。
                receipt = None
        if receipt is not None and receipt.state in {
            ReceiptState.SENT,
            ReceiptState.REDIRECTED,
        }:
            store.mark_done(reminder.reminder_id)
            delivered += 1
        else:
            from nonebot.log import logger

            logger.warning(
                "reminder {} not delivered (state={}); kept for retry",
                request_id,
                getattr(receipt, "state", "no-online-bot"),
            )
    return delivered


def _register_reminder_scheduler(
    scheduler: Any,
    config: Any,
    send_queue: Any,
    audit_logger: Any | None = None,
    receipt_repository: Any | None = None,
    all_online_bots: Any | None = None,
) -> dict:
    """提醒投递：每分钟检查到点提醒，submit 后**内联投递**、送达才销账。

    到点文案由 character/reminders.build_reminder_text 提供（守岸人语气）；
    投递失败只记日志、不销账、下一轮重投，绝不阻塞主链路。
    """

    async def _reminder_job() -> None:
        from nonebot.log import logger

        try:
            await _deliver_due_reminders(
                config,
                send_queue,
                audit_logger,
                receipt_repository,
                all_online_bots,
            )
        except Exception as exc:  # noqa: BLE001 - 提醒投递失败不影响主链路。
            logger.warning("reminder delivery failed: {}", type(exc).__name__)

    scheduler.add_job(
        _reminder_job,
        "cron",
        id="bot_reminder_tick",
        replace_existing=True,
        minute="*",
        second=5,
        misfire_grace_time=120,
        max_instances=1,
        coalesce=True,
    )
    return {"interval": "1m"}


_DIGEST_PUSH_INTRO = "今天群里的对话，我都悄悄记下了："
_DIGEST_PUSH_DEFAULT_CLOCK = (21, 30)


def _build_digest_push_text(summary: str) -> str:
    """守岸人语气的推送正文：一句克制引子 + 当日群摘要（不堆辞藻）。"""
    return f"{_DIGEST_PUSH_INTRO}\n{summary.strip()}"


def _parse_digest_push_clock(value: Any) -> tuple[int, int]:
    """解析 HH:MM 推送时刻；非法值回退默认 21:30（严格校验在 config 层）。"""
    parts = str(value or "").strip().split(":")
    if len(parts) != 2:
        return _DIGEST_PUSH_DEFAULT_CLOCK
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return _DIGEST_PUSH_DEFAULT_CLOCK
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return _DIGEST_PUSH_DEFAULT_CLOCK


def _push_daily_group_digests(
    config: Any,
    send_queue: Any,
    provider: Any,
    *,
    now: Any = None,
) -> list[str]:
    """把白名单群当日群摘要逐群投递 send_queue；返回已推送群号。

    推送目标只取群摘要名单 whitelist 模式下的白名单群：list_mode 非
    whitelist 一律不推（绝不猜群）。每群合成 request_id 调 shared_group
    provider 取当日摘要，无可用摘要静默跳过；正文 = 守岸人引子 + 摘要；
    dedupe_key 带当天日期，同群同天不重发。
    """
    from datetime import datetime

    from .character.shared_group import GroupDigestListFilter
    from .contracts import (
        PrivacyLevel,
        RenderedOutput,
        SendPolicy,
        SendRequest,
        SessionType,
    )

    digest_list = GroupDigestListFilter(
        mode=str(getattr(config, "bot_group_digest_list_mode", "") or ""),
        whitelist=getattr(config, "bot_group_digest_whitelist", None),
        blacklist=getattr(config, "bot_group_digest_blacklist", None),
    )
    if digest_list.mode != "whitelist" or not digest_list.whitelist:
        return []
    today = (now or datetime.now().astimezone()).date().isoformat()
    persona_profile_id = str(
        getattr(config, "bot_persona_profile_id", "default")
    )
    pushed: list[str] = []
    for group_id in sorted(digest_list.whitelist):
        request_id = f"digest-push-{group_id}-{today}"
        context = provider.load(request_id, group_id, sender_id="")
        summary = str(getattr(context, "summary", "") or "").strip()
        if not getattr(context, "enabled", False) or not summary:
            continue
        request = SendRequest(
            request_id=request_id,
            session_id=f"group:{group_id}",
            target_scope=SessionType.GROUP,
            target_id=group_id,
            capability_id="bot.group_digest_push",
            content=RenderedOutput(
                request_id=request_id,
                content_type="text",
                content_ref={},
                text_fallback=_build_digest_push_text(summary),
                privacy_level=PrivacyLevel.GROUP,
            ),
            send_policy=SendPolicy.QUEUED,
            priority="normal",
            max_messages=1,
            dedupe_key=f"digest_push:{group_id}:{today}",
            cooldown_key=f"digest_push:{group_id}",
            privacy_level=PrivacyLevel.GROUP,
            persona_profile_id=persona_profile_id,
            audit_tags=["digest_push", "daily"],
        )
        send_queue.submit(request)
        pushed.append(group_id)
    return pushed


def _register_digest_push_scheduler(
    scheduler: Any, config: Any, send_queue: Any
) -> dict:
    """夜间每日群通讯总结主动推送（G-DIGEST 收尾）。

    每日 cron（``bot_group_digest_push_time``，默认 21:30）把群摘要名单
    whitelist 模式下的白名单群当日摘要各推一遍；同步 job 跑在 APScheduler
    线程池（与 reminder/reflection 同款，不阻塞事件循环），失败只记日志。
    """

    def _digest_push_job() -> None:
        try:
            from .character.shared_group import build_shared_group_context_provider

            _push_daily_group_digests(
                config,
                send_queue,
                build_shared_group_context_provider(config),
            )
        except Exception as exc:  # noqa: BLE001 - 夜间推送失败不影响主链路。
            from nonebot.log import logger

            logger.warning("group digest push failed: {}", type(exc).__name__)

    hour, minute = _parse_digest_push_clock(
        getattr(config, "bot_group_digest_push_time", "21:30")
    )
    scheduler.add_job(
        _digest_push_job,
        "cron",
        id="bot_group_digest_push_daily",
        replace_existing=True,
        hour=hour,
        minute=minute,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )
    return {"hour": hour, "minute": minute}


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
        build_quirk_admin_result,
        build_runtime_admin_result,
        build_session_identity_admin_result,
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
        build_quiet_hours_settings,
        build_rate_limit_settings,
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
    # 管理员热改设置（群名单/开关/昵称等）时立即失效路由分类缓存，不必等 10s TTL。
    runtime_settings.register_change_listener(clear_route_decision_cache)
    # 发送层硬超时：每次发送时读 runtime 覆盖（mtime 热重载），未覆盖时回落 .env 配置。
    set_transport_timeout_provider(
        lambda: float(runtime_settings.get("BOT_TRANSPORT_TIMEOUT_SECONDS", config) or 15.0)
    )
    # 语音下载代理（B-12）：同模式注入 getter，sender 层优先读运行时/插件
    # Config，取不到再退回 driver config/env 探测链。
    from .sender.nonebot import set_download_proxy_provider

    set_download_proxy_provider(
        lambda: str(
            runtime_settings.get("BOT_DOWNLOAD_PROXY", config)
            or getattr(config, "bot_download_proxy", "")
            or ""
        )
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
        rate_limiter=build_rate_limiter(
            config,
            # 群句数帽/情绪豁免纳入 store，需实时求值（/bot runtime set 立即生效）。
            settings_provider=lambda: build_rate_limit_settings(
                _config_with_runtime_overrides(config, runtime_settings)
            ),
        ),
        quiet_hours_checker=build_quiet_hours_checker(
            config,
            # 实时求值：安静时间窗口/开关纳入运行时 store 后必须热生效，
            # 不能在装配期快照（否则 /bot runtime set 改了要等重启才生效）。
            settings_provider=lambda: build_quiet_hours_settings(
                _config_with_runtime_overrides(config, runtime_settings)
            ),
        ),
        runtime_control=runtime_control,
        forward_min_chars=config.bot_render_forward_min_chars,
        forward_max_nodes=config.bot_render_forward_max_nodes,
        forward_node_chars=config.bot_render_forward_node_chars,
        # 合并转发：切分后 >3 条（≥4）才合并；节点署名用 bot 自己的名字。
        forward_min_nodes=int(getattr(config, "bot_render_forward_min_nodes", 4) or 4),
        forward_sender_name=(
            getattr(config, "bot_persona_display_name", "") or "守岸人"
        ),
        group_auto_reply_enabled=config.bot_group_chat_auto_reply_enabled,
        # bot 心情联动（L1）：低落时少插话、兴奋时更活跃——只调概率，不做硬开关。
        # 传 **callable** 而不是当场求值的 float：装配期求值会让心情变化永不生效
        # （评审实锤的时序 bug），必须在每次抽签时现算。
        group_auto_reply_probability=lambda: min(
            1.0,
            config.bot_group_chat_auto_reply_probability
            * _mood_willingness_factor(config),
        ),
        vision_reply_probability=float(
            getattr(config, "bot_vision_reply_probability", 1.0)
        ),
        group_black1=frozenset(config.bot_group_black1),
        group_black2=frozenset(config.bot_group_black2),
        group_white1=frozenset(config.bot_group_white1),
        group_white2=frozenset(config.bot_group_white2),
        natural_chat_check=looks_like_question_text,
        mention_terms=tuple(_RUNTIME_MENTION_TERMS),
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

    # N4 主动搭话亲和门：群聊抽签主动接话只对好感档 ≥ 亲近（close）的用户。
    # 冷却/频控由 rate_limit 层 proactive 分桶承担（bot_group_proactive_*）。
    if bool(getattr(config, "bot_proactive_affinity_gate_enabled", True)):
        from .character.affinity import tier_for_affinity
        from .policy.gate import configure_proactive_affinity_gate

        def _proactive_affinity_check(sender_id: str) -> bool:
            store = build_character_affinity_store(config)
            if store is None:
                return False
            affinity = float(
                store.snapshot(str(sender_id)).get("affinity", 0.0) or 0.0
            )
            return tier_for_affinity(affinity) == "close"

        configure_proactive_affinity_gate(_proactive_affinity_check)
    else:
        from .policy.gate import configure_proactive_affinity_gate

        configure_proactive_affinity_gate(None)

    def _first_online_bot() -> OneBotV11Bot | None:
        # 历史上的今天等系统推送要发 OneBot 请求：注册表首个 bot 可能是
        # Telegram/Mail 账号，跨适配器调用必然失败；只取 onebot 适配器账号。
        return cast(Any, _select_credential_bot(_all_online_bots()))

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
        # LLM 截止超时是常态降级（模型慢/网络抖动，用户侧已有兜底回复），
        # 不值得私聊管理员，直接跳过避免刷屏。
        if getattr(issue, "stage", "") == "llm" and getattr(issue, "kind", "") == "deadline_exceeded":
            return
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

            _BACKFILL_TASKS: set[asyncio.Task[None]] = set()

            @driver.on_bot_connect
            async def _log_bot_connect(bot):
                runtime_event_log.info(
                    "bot_connected",
                    bot_id=str(getattr(bot, "self_id", "unknown")),
                )
                # Bot 本地头像（2026-09-13 用户指令）：连接即从 qlogo 下载
                # 持久化到 Runtime data/avatar/，全卡片按需取 file URI。
                try:
                    await asyncio.to_thread(
                        _refresh_local_bot_avatar,
                        str(getattr(bot, "self_id", "") or ""),
                        config,
                    )
                except Exception as exc:  # noqa: BLE001 - 头像缺失仅观感降级。
                    _log_runtime_event(
                        runtime_event_log,
                        "DEBUG",
                        "bot_avatar_prefetch_failed",
                        adapter="onebot",
                        platform="qq",
                        bot_id=str(getattr(bot, "self_id", "unknown")),
                        detail=type(exc).__name__,
                    )
                # 表情库启动补标（F6/用户裁定：导入的表情包必须先被理解才
                # 允许被发）：描述为空的图逐张过 VLM；每轮限 20 张防打爆。
                if bool(getattr(config, "bot_meme_library_enabled", False)):
                    try:
                        from .sources.meme_library_listener import (
                            backfill_meme_tags_loop,
                        )

                        _store = meme_library_store
                        if _store is not None:
                            _backfill_task = asyncio.create_task(
                                backfill_meme_tags_loop(_store, config)
                            )
                            _BACKFILL_TASKS.add(_backfill_task)
                            _backfill_task.add_done_callback(
                                _BACKFILL_TASKS.discard
                            )
                    except Exception:  # noqa: BLE001 - 补标失败不影响启动。
                        runtime_event_log.warning("meme_backfill_failed")
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

    def _build_epic_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_epic_capability(config_, render_backend=render_backend)

    def _build_weather_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_weather_capability(config_, render_backend=render_backend)

    def _build_eat_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_eat_capability(config_, render_backend=render_backend)

    def _build_affinity_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_affinity_capability(
            config_,
            affinity_store=build_character_affinity_store(config_),
            render_backend=render_backend,
        )

    def _build_market_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_market_capability(config_, render_backend=render_backend)

    def _build_stocks_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_stocks_capability(config_, render_backend=render_backend)

    def _build_fx_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_fx_capability(config_, render_backend=render_backend)

    def _build_commodities_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_commodities_capability(config_, render_backend=render_backend)

    def _build_bond_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_bond_capability(config_, render_backend=render_backend)

    def _build_northbound_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_northbound_capability(config_, render_backend=render_backend)

    def _build_divination_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_divination_capability(config_, render_backend=render_backend)

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
            try:
                today_ctx = _register_today_history_scheduler(
                    scheduler=scheduler,
                    config=config,
                    pipeline=pipeline,
                    send_queue=send_queue,
                    audit_logger=audit_logger,
                    receipt_repository=receipt_repository,
                    bot_provider=_first_online_bot,
                    render_backend=render_backend,
                )
            except Exception:  # noqa: BLE001 - 调度注册失败（如 apscheduler 缺失）不崩装配，
                today_ctx = None  # 后续「历史上的今天」命令走无推送的直查路径。
        else:
            today_ctx = None

        if (
            getattr(config, "bot_kb_wiki_enabled", False)
            and str(getattr(config, "bot_kb_wiki_root", "") or "").strip()
        ):
            _register_kb_wiki_sync_scheduler(scheduler, config)

        if (
            getattr(config, "bot_history_enabled", False)
            and getattr(config, "bot_reflection_enabled", False)
        ):
            _register_reflection_scheduler(scheduler, config)

        if getattr(config, "bot_reminder_enabled", True):
            _register_reminder_scheduler(
                scheduler,
                config,
                send_queue,
                audit_logger,
                receipt_repository,
                _all_online_bots,
            )

        # 夜间每日群通讯总结推送：推送开关开启且共享群摘要能力开启才注册。
        if (
            getattr(config, "bot_group_digest_push_enabled", True)
            and getattr(config, "bot_shared_group_context_enabled", False)
        ):
            _register_digest_push_scheduler(scheduler, config, send_queue)

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
                text += f"\n{body[:500]}"
            elif bool(getattr(config, "bot_vision_enabled", False)):
                # 纯图/无文本订阅条目：用 vision 补一行描述，失败静默不阻断推送。
                from .sources.vision_describe import describe_subscription_item

                # 同步 HTTP 描述调用必须下放线程池，否则每条无文本订阅条目
                # 都会在事件循环上阻塞数秒（审计重发现 P2）。
                described = await asyncio.to_thread(
                    describe_subscription_item, vision_provider, payload
                )
                if described:
                    text += f"\n图：{described}"
            from .capabilities.content_parser import build_subscription_push_capability

            sent_any = False
            all_success = True
            for destination in destinations:
                # 目的地级暂停（pause 只作用于本目的地行）：跳过不投递，
                # 也不计入失败（审计重发现 P2：此前 pause/resume 是 target 级）。
                if not getattr(destination, "enabled", True):
                    continue
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

        # 模型渠道健康巡检：每小时全量探测一次（后台低并发最小调用），
        # 暂不可用渠道自动移出故障转移队列，恢复即自动回队。
        # B-13（D7 残留）：取数走 _probe_specs 合并视图（.env 注册表 ∪
        # 运行时注册表），管理员 /bot model add 的新渠道也进后台巡检——
        # 此前只探 build_model_registry（仅 .env），运行时渠道永无健康数据。
        if getattr(config, "bot_channel_health_enabled", True):
            def _channel_health_job() -> None:
                try:
                    from plugins.bot_unified_runtime.capabilities.runtime_admin import (
                        _probe_specs,
                    )
                    from plugins.bot_unified_runtime.llm.channel_health import (
                        get_channel_health_store,
                        probe_all,
                    )

                    probe_all(
                        config,
                        _probe_specs(runtime_settings, config),
                        get_channel_health_store(),
                        mode="background",
                    )
                except Exception:  # noqa: S110, BLE001 - 巡检失败不影响主链路。
                    pass

            scheduler.add_job(
                _channel_health_job,
                "interval",
                seconds=max(
                    300,
                    int(
                        getattr(
                            config,
                            "bot_channel_health_interval_seconds",
                            3600,
                        )
                        or 3600
                    ),
                ),
                id="model_channel_health",
                coalesce=True,
                max_instances=1,
            )

        # 平台凭证过期每日提醒：过期/7 天内临期 → 私聊管理员（config.bot_admin_user_ids 首个在线）。
        if getattr(config, "bot_cookie_expiry_reminder_enabled", True):

            async def _cookie_expiry_reminder_job() -> None:
                try:
                    from plugins.bot_unified_runtime.capabilities.platform_credentials import (
                        cookie_expiry_report,
                    )

                    report = await asyncio.to_thread(cookie_expiry_report, config)
                except Exception:  # noqa: BLE001 - 巡检失败不影响主链路。
                    return
                if not report:
                    return
                bot = _select_credential_bot(_all_online_bots())
                if bot is None:
                    return
                admins = [
                    str(item).strip()
                    for item in (getattr(config, "bot_admin_user_ids", []) or [])
                    if str(item).strip()
                ]
                for admin_id in admins[:3]:
                    try:
                        await bot.call_api(
                            "send_private_msg",
                            user_id=int(admin_id),
                            message=[{"type": "text", "data": {"text": report}}],
                        )
                        break
                    except Exception as exc:  # noqa: BLE001 - 换下一个管理员。
                        logging.getLogger(__name__).debug(
                            "cookie expiry notice to %s failed: %s", admin_id, exc
                        )
                        continue

            scheduler.add_job(
                _cookie_expiry_reminder_job,
                "cron",
                hour=10,
                minute=0,
                id="cookie_expiry_reminder",
                replace_existing=True,
                misfire_grace_time=600,
                max_instances=1,
            )

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
    # 媒体归档存储：注册期单例（评审 I-4）——每消息重建实例会让实例级锁与
    # sha256 去重的 check-then-act 全部失效。关闭时不建（零开销）。
    from plugins.bot_unified_runtime.sources.media_archive import MediaArchiveStore

    media_archive_store = (
        MediaArchiveStore(
            config.bot_media_archive_db_path,
            config.bot_media_archive_dir,
        )
        if getattr(config, "bot_media_archive_enabled", True)
        else None
    )
    from plugins.bot_unified_runtime.sources.transcribe import (
        build_asr_provider,
    )

    asr_provider = build_asr_provider(
        config,
        settings_store=runtime_settings,
    )
    from plugins.bot_unified_runtime.character.media_registry import (
        build_media_registry,
    )

    media_registry = build_media_registry(
        config,
        ttl_seconds=int(
            getattr(config, "bot_media_registry_ttl_days", 7) or 7
        )
        * 86400,
    )
    _MEDIA_RUNTIME_SINGLETON["registry"] = media_registry
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
                mood_describe=_build_mood_describe(config),
                quirks_describe=_build_quirks_describe(config),
                identity_describe=_build_identity_describe(config),
                reactions_describe=_build_reactions_describe(config),
            ),
            llm_provider=_build_chat_llm_provider(config),
            admin_roster_text=_build_admin_roster_text_for_chat(config),
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
            vision_video_frames=int(getattr(config, "bot_vision_video_frames", 4)),
            asr_provider=asr_provider,
            asr_enabled=bool(getattr(config, "bot_asr_enabled", False)),
            asr_max_chars=int(getattr(config, "bot_asr_max_chars", 300)),
            media_registry=media_registry,
            video_understanding_enabled=bool(
                getattr(config, "bot_video_understanding_enabled", False)
            ),
            media_config=config,
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
        if (
            contains_visual_message_segments(raw_segments)
            or contains_audio_message_segments(raw_segments)
            or contains_forward_message_segments(raw_segments)
        ):
            # 纯媒体/转发消息走聊天链路：这些消息的 plain_text 往往为空，
            # 会被路由判 IGNORE；若不在这里放行，视觉理解、ASR 与合并转发正文
            # 反查（都在 handler 内部）都永远跑不到。
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

    # 统一戳一戳分发：OneBot 适配器只做事件归一与执行，门控/话术/回戳
    # 意图全部收敛在 capabilities.poke.PokeDispatcher（未来其他适配器同构复用）。
    from .capabilities.poke import PokeDispatcher
    _poke_dispatcher = PokeDispatcher(clock=time.monotonic)

    async def _is_poke_event(event: Event) -> bool:
        return str(getattr(event, "notice_type", "")) == "notify" and str(getattr(event, "sub_type", "")) == "poke"

    poke_notice = on_notice(rule=_is_poke_event, priority=7, block=False)

    @poke_notice.handle()
    async def _handle_poke_notice(bot: Bot, event: Event) -> None:
        reaction = _poke_dispatcher.build_poke_reaction(
            event,
            bot_id=str(getattr(bot, "self_id", "")),
            # 运行时热覆盖合并：/bot runtime set BOT_POKE_* 立即生效。
            config=_config_with_runtime_overrides(config, runtime_settings),
        )
        if reaction is None or not reaction.active:
            return
        if reaction.poke_back:
            # 回戳：NapCat/OneBot V11 扩展 API，平台不支持时静默降级。
            try:
                if reaction.group:
                    await bot.call_api(
                        "group_poke",
                        group_id=int(getattr(event, "group_id", 0) or 0),
                        user_id=int(getattr(event, "user_id", 0) or 0),
                    )
                else:
                    await bot.call_api("friend_poke", user_id=int(getattr(event, "user_id", 0) or 0))
            except Exception:  # noqa: BLE001, S110 - 回戳失败不影响话术回复。
                pass
        if reaction.reply:
            await _send_text_through_unified_pipeline(
                bot, event,
                reaction.reply,
                "bot.poke",
            )

    # 表情贴纸回应识别（bot.reactions）：NapCat 贴纸回应 notice 只做归一与
    # 会话缓冲登记（供 chat 注入【表情回应】分区），本 handler 不回话、不贴表
    # 情——主动贴表情在 chat 链路的情绪信号/回复后触发点完成。私聊等价形态
    # 按容错解析，生产实机待验证；失败静默不影响任何主链路。
    async def _is_msg_emoji_like_event(event: Event) -> bool:
        return str(getattr(event, "notice_type", "")) in {
            "group_msg_emoji_like",
            "private_msg_emoji_like",
            "msg_emoji_like",
        }

    emoji_like_notice = on_notice(rule=_is_msg_emoji_like_event, priority=7, block=False)

    @emoji_like_notice.handle()
    async def _handle_msg_emoji_like_notice(bot: Bot, event: Event) -> None:
        try:
            for reaction_event in _normalize_onebot_emoji_like(event):
                _REACTION_BUFFER.record(reaction_event)
        except Exception:  # noqa: BLE001, S110 - 回应识别失败不影响主链路。
            pass

    @file_notice.handle()
    async def _handle_admin_file_notice(bot: Bot, event: Event) -> None:
        file_info = getattr(event, "file", None)
        file_id = str(getattr(file_info, "file_id", "") or "")
        # 只取文件名本身：平台侧 name 可能带路径分隔符，直接拼接会写出 incoming 之外。
        file_name = _Path(str(getattr(file_info, "name", "") or "")).name.strip() or "file"
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

                # 大文件写盘放线程池，避免事件循环被阻塞在 IO 上。
                await asyncio.to_thread(
                    target.write_bytes, base64.b64decode(base64_body)
                )
                saved_path = str(target)
            elif local_path and _Path(local_path).exists():
                saved_path = local_path
        except Exception:  # noqa: BLE001 - 平台取文件失败只回报类型。
            await _send_text_through_unified_pipeline(bot, event, "文件接收失败（平台接口异常），请重试或改发文本。")
            return
        if not saved_path:
            await _send_text_through_unified_pipeline(bot, event, "文件接收失败：平台未返回可读文件内容。")
            return
        # run_code_debug 内部是同步 subprocess（timeout=15s），必须下放线程池。
        report = await asyncio.to_thread(run_code_debug, saved_path)
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
            # LLM 生成（秒级~几十秒）与文档转换必须下放线程池，
            # 否则整个事件循环冻结、全部会话无响应。
            reply = await asyncio.to_thread(
                _build_chat_llm_provider(config).generate,
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
        path, error = await asyncio.to_thread(
            export_document, markdown, fmt, out_dir, title=topic[:40]
        )
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
        # 搜圖（TRA 草稿）：繁體形与简体同口径（旁路 matcher 不入 base_router 审计）。
        return bool(re.match(r"^[/!！]?(?:搜图|搜圖)(\s|$)", event.get_plaintext().strip()))

    image_search = on_message(rule=_is_image_search_event, priority=46, block=True)

    @image_search.handle()
    async def _handle_image_search(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            bot_id=str(getattr(bot, "self_id", "unknown")), event=event
        )
        if message is None:
            return
        # 回复图片可触发（2026-09-13 用户指令）：反查被引用消息拿 http 图链。
        if (
            message.reply_to_message_id
            and not any(
                str(s.get("type", "")).lower() == "image"
                for s in message.raw_segments or []
            )
        ):
            getter = getattr(bot, "get_msg", None)
            if callable(getter) and str(message.reply_to_message_id).strip():
                try:
                    replied_payload = await asyncio.wait_for(
                        getter(message_id=int(str(message.reply_to_message_id))),
                        timeout=5.0,
                    )
                except (asyncio.TimeoutError, ValueError, TypeError):
                    replied_payload = None
                except Exception:  # noqa: BLE001 - 反查失败按无图处理。
                    replied_payload = None
                if replied_payload is not None:
                    replied_segments = (
                        _onebot_segments_from_message_payload(replied_payload) or []
                    )
                    message.raw_segments.extend(
                        segment
                        for segment in replied_segments
                        if str(segment.get("type", "")).lower() == "image"
                    )
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
        # 管道只把发送请求入队（内存队列回执是假 sent），真实网络投递必须由
        # handler 显式完成——与 _handle_content 的投递模式完全同构。
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
                capability_id="bot.image_search",
                receipt=transport_receipt,
                send_queue=send_queue,
                audit_logger=audit_logger,
            )
            await _notify_operational_receipt(message, transport_receipt)
            if transport_receipt.state.value == "sent":
                return
            if should_finish_nonebot_matcher(transport_receipt):
                await image_search.finish(transport_receipt.public_message)
            return
        if should_finish_nonebot_matcher(receipt):
            await image_search.finish(receipt.public_message)

    cookie_admin = on_message(rule=_is_admin_cookie_command, priority=8, block=True)

    _NICKNAME_RE = re.compile(r"^/bot\s+(?:昵称|暱稱|nickname)\s+set\s+(\d{5,11})\s+(\S{1,32})$")

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

    # priority 8：抢在 /bot 命令 matcher（priority 11, block=True）之前消费
    # 「/bot 群文件」，45 会被它完全遮蔽成死代码（兄弟命令 cookie/nickname 均 8）。
    group_file_stats = on_message(rule=_is_group_file_stats_command, priority=8, block=True)

    @group_file_stats.handle()
    async def _handle_group_file_stats(bot: Bot, event: Event) -> None:
        # 群文件统计暴露群内上传者/文件清单，与管理命令同级：仅管理员可查。
        if not await _is_admin_origin(event):
            await _send_text_through_unified_pipeline(bot, event, "只有管理员才能查看群文件统计。")
            return
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
        if action == "login":
            if not platform:
                await _send_text_through_unified_pipeline(
                    bot,
                    event,
                    "用法：/bot cookie login bilibili（当前已支持扫码登录的平台：bilibili；其余平台请用 /bot cookie import 手动导入）",
                )
                return
            _session_key, png_path, login_text = cookie_login_start(config, platform)
            await _send_text_through_unified_pipeline(bot, event, login_text)
            if png_path:
                image_segment = {
                    "type": "image",
                    "data": {"file": "file:///" + png_path.replace("\\", "/")},
                }
                try:
                    if isinstance(event, GroupMessageEvent):
                        await bot.call_api(
                            "send_group_msg",
                            group_id=event.group_id,
                            message=[image_segment],
                        )
                    else:
                        await bot.call_api(
                            "send_private_msg",
                            user_id=int(event.get_user_id()),
                            message=[image_segment],
                        )
                except Exception as exc:  # noqa: BLE001 - 图片发送失败时文本兜底已给出链接。
                    logging.getLogger(__name__).debug("qr image send failed: %s", exc)
            return
        if action == "check":
            if not platform:
                await _send_text_through_unified_pipeline(
                    bot,
                    event,
                    "用法：/bot cookie check bilibili（查询最近一次扫码登录的结果）",
                )
                return
            await _send_text_through_unified_pipeline(
                bot, event, cookie_login_check(config, platform)
            )
            return
        if action == "expiry":
            report = cookie_expiry_report(config)
            await _send_text_through_unified_pipeline(
                bot, event, report or "所有平台凭证均有效，无需处理。"
            )
            return
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

    async def _is_moegirl_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.MOEGIRL
        )

    async def _is_moegirl_question_event(state: T_State, event: Event) -> bool:
        # 邮件不接管：问句自动回复沿用 chat 链路的邮件策略（bot_mail_auto_reply_enabled）。
        if _event_adapter_kind(event) == "mail":
            return False
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.MOEGIRL_QUESTION
        )

    async def _is_epic_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.EPIC
        )

    async def _is_eat_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.EAT
        )

    async def _is_weather_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.WEATHER
        )

    async def _is_market_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.MARKET
        )

    async def _is_stocks_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.STOCKS
        )

    async def _is_fx_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.FX
        )

    async def _is_commodities_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.COMMODITIES
        )

    async def _is_bond_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.BOND
        )

    async def _is_northbound_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.NORTHBOUND
        )

    async def _is_divination_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.DIVINATION
        )

    async def _is_news_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.NEWS
        )

    async def _is_randpic_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.RANDPIC
        )

    async def _is_reminder_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.REMINDER
        )

    content = on_message(rule=_is_content_parse_event, priority=46, block=True)
    music_mode = on_message(rule=_is_music_mode_event, priority=40, block=True)
    music = on_message(rule=_is_music_event, priority=41, block=True)
    today_history = on_message(
        rule=_is_today_history_event, priority=41, block=True
    )
    wiki = on_message(rule=_is_wiki_event, priority=41, block=True)
    moegirl = on_message(rule=_is_moegirl_event, priority=41, block=True)
    moegirl_question = on_message(
        rule=_is_moegirl_question_event, priority=46, block=True
    )
    epic = on_message(rule=_is_epic_event, priority=41, block=True)
    weather = on_message(rule=_is_weather_event, priority=41, block=True)
    market = on_message(rule=_is_market_event, priority=41, block=True)
    fx = on_message(rule=_is_fx_event, priority=41, block=True)
    stocks = on_message(rule=_is_stocks_event, priority=42, block=True)
    commodities = on_message(rule=_is_commodities_event, priority=41, block=True)
    bond = on_message(rule=_is_bond_event, priority=41, block=True)
    northbound = on_message(rule=_is_northbound_event, priority=41, block=True)
    divination = on_message(rule=_is_divination_event, priority=41, block=True)
    news = on_message(rule=_is_news_event, priority=41, block=True)
    randpic = on_message(rule=_is_randpic_event, priority=41, block=True)
    reminder = on_message(rule=_is_reminder_event, priority=41, block=True)
    eat = on_message(rule=_is_eat_event, priority=41, block=True)
    subscribe_cmd = on_message(rule=_is_standalone_subscribe_event, priority=12, block=True)

    async def _is_affinity_event(state: T_State, event: Event) -> bool:
        # F1/F17 修复：路由层一直有 RouteKind.AFFINITY 判定，但主模块从未注册
        # 对应 matcher——「好感度」系消息全部静默坠地（用户实弹反馈：发了没回复）。
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.AFFINITY
        )

    affinity = on_message(rule=_is_affinity_event, priority=41, block=True)

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
                    actor_roles=list(getattr(_decision, "actor_roles", []) or []),
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
                return build_weather_capability(config, render_backend=render_backend)(synthetic, _decision)

        elif resolution.capability_id == "bot.music":
            query = resolution.rest_text

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": f"点歌 {query}"})
                mode = runtime_settings.get("BOT_MUSIC_MODE", config) or getattr(config, "bot_music_default_mode", "card+voice+link")
                return build_music_capability(
                    config,
                    default_mode=mode,
                    request_store=music_request_store,
                    candidate_providers=(
                        music_candidate_providers(build_cookie_provider(config))
                        if getattr(config, "bot_music_candidates_enabled", False)
                        else None
                    ),
                    render_backend=render_backend,
                )(synthetic, _decision)

        elif resolution.capability_id == "bot.wiki":
            query = resolution.rest_text

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": f"wiki {query}"})
                return build_wiki_capability(config)(synthetic, _decision)

        elif resolution.capability_id == "bot.eat":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_eat_capability(config, render_backend=render_backend)(message, _decision)

        elif resolution.capability_id == "bot.news":
            # F9：别名链此前无 bot.news 分支，「守岸人 AI新闻」坠 help。
            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_news_capability(config)(message, _decision)

        elif resolution.capability_id == "bot.epic":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_epic_capability(config, render_backend=render_backend)(message, _decision)

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
                return build_today_history_capability(config, render_backend=render_backend)(synthetic, _decision)

        elif resolution.capability_id == "bot.affinity":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_affinity_capability(
                    config,
                    affinity_store=build_character_affinity_store(config),
                    render_backend=render_backend,
                )(message, _decision)

        elif resolution.capability_id == "bot.subscribe":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                from .capabilities.subscribe import normalize_subscribe_text
                from .capabilities.subscribe_v2 import build_subscribe_capability_v2

                sub_ctx = subscription_ctx if isinstance(subscription_ctx, dict) else {}
                store = sub_ctx.get("store")
                adapters = sub_ctx.get("adapters")
                if store is None or adapters is None:
                    # 订阅运行时注册失败时返回空字典而非半可用上下文：
                    # 静默 KeyError 会让用户命令石沉大海。
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.subscribe",
                        kind="text",
                        body="订阅运行时未启动，暂时无法处理订阅命令。",
                        audit_tags=["subscribe", "runtime_unavailable"],
                    )
                normalized = normalize_subscribe_text(
                    f"/bot subscribe {resolution.rest_text}".strip()
                )
                synthetic = message.model_copy(update={"plain_text": normalized})
                return build_subscribe_capability_v2(
                    store=store,
                    adapters=adapters,
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
                return build_meme_library_capability(
                    meme_library_store, config,
                    mood_valence_fn=lambda: _mood_valence(config),
                )(
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
        _sub_store = sub_ctx.get("store")
        _sub_adapters = sub_ctx.get("adapters")

        def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
            if _sub_store is None or _sub_adapters is None:
                # 订阅运行时注册失败时给用户明确反馈，而不是 KeyError 静默。
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.subscribe",
                    kind="text",
                    body="订阅运行时未启动，暂时无法处理订阅命令。",
                    audit_tags=["subscribe", "runtime_unavailable"],
                )
            normalized = normalize_subscribe_text(message.plain_text)
            synthetic_message = message.model_copy(update={"plain_text": normalized})
            return build_subscribe_capability_v2(
                store=_sub_store,
                adapters=_sub_adapters,
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
            offload_sync_capability=True,
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

        elif command_text == "好感度" or command_text.startswith(
            ("好感度 ", "好感查看", "查询好感", "好感值", "亲密度")
        ):
            # F1/F17：/bot 好感度 [算法] 显式接入（此前坠入 help 兜底，算法页不可达）。
            capability_id = "bot.affinity"
            affinity_rest = (
                command_text.removeprefix("好感度")
                .removeprefix("好感查看")
                .removeprefix("查询好感")
                .removeprefix("好感值")
                .removeprefix("亲密度")
                .strip()
            )

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(
                    update={"plain_text": f"好感度 {affinity_rest}".strip()}
                )
                return _build_affinity_with_backend(config)(synthetic, _decision)

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

        elif command_text == "quirk" or command_text.startswith("quirk "):
            # /bot quirk ...：L4 人格演化区审核（管理员门在 result 构造内）。
            capability_id = "bot.quirk"
            quirk_command = command_text.removeprefix("quirk").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_quirk_admin_result(
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    command_text=quirk_command,
                )

        elif command_text == "identity" or command_text.startswith("identity "):
            # /bot identity ...：会话级身份记忆（在哪个会话执行就对哪个会话生效）；
            # set-name/set-gender/unset-name/unset-gender 为用户自助称谓偏好
            # （runtime_admin 内在管理员门前拦截转发，需 sender_id/group_id 定位本人）。
            capability_id = "bot.identity"
            identity_command = command_text.removeprefix("identity").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_session_identity_admin_result(
                    config,
                    request_id=message.request_id,
                    actor_roles=_decision.actor_roles,
                    session_key=message.session_id,
                    command_text=identity_command,
                    sender_id=str(message.sender_id or ""),
                    group_id=str(message.group_id or ""),
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
                # M24：解析历史是**全局**范围（跨群/跨私聊的 URL+标题+时间），
                # 此前无门，任意成员 `/bot parse 20` 即可读到其他会话解析过的
                # 链接（链接自带 token 时等于二次扩散）。与 /bot status、debug
                # 排障命令同档，收紧为管理员可见。
                if "admin" not in {str(role).lower() for role in _decision.actor_roles}:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.parse",
                        kind="text",
                        body="只有管理员才能查看解析历史。",
                        audit_tags=["parse_history", "denied"],
                    )
                return build_parse_history_result(
                    parse_history_store,
                    request_id=message.request_id,
                    query=parse_query,
                )

        elif command_text == "download" or command_text.startswith("download "):
            capability_id = "bot.download"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                # H6 定案：download 保留给普通用户（产品需要），安全边界改由
                # downloader 侧承担——sources/downloader.check_download_url 拒绝
                # 非 http(s) 协议与内网/保留地址（含 DNS 解析后的私网 IP、云元数据
                # 主机），并覆盖十进制/十六进制 IP 等绕过形态。此处不设管理员门。
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

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                if "admin" not in {str(role).lower() for role in _decision.actor_roles}:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.reply",
                        kind="text",
                        body="只有管理员才能调整回复详略。",
                        audit_tags=["reply_detail", "denied"],
                    )
                if normalized_mode is None:
                    # 未知参数不再静默当 auto：明确回用法，避免误设置却以为生效。
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.reply",
                        kind="text",
                        body=(
                            f"未知的回复详略参数：{reply_mode}。\n"
                            "用法：/bot reply <详细|精简|默认>"
                        ),
                        audit_tags=["reply_detail", f"invalid:{reply_mode}"],
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
                store = sub_ctx.get("store")
                adapters = sub_ctx.get("adapters")
                if store is None or adapters is None:
                    # 订阅运行时注册失败时给用户明确反馈，而不是 KeyError 静默。
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.subscribe",
                        kind="text",
                        body="订阅运行时未启动，暂时无法处理订阅命令。",
                        audit_tags=["subscribe", "runtime_unavailable"],
                    )
                return build_subscribe_capability_v2(
                    store=store,
                    adapters=adapters,
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
                    "删": "del", "刪": "del", "移除": "del",
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
                    actor_roles=list(getattr(_decision, "actor_roles", []) or []),
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
        # 语音段预转码：SILK 裸流 ffmpeg 解不了，先请适配器 get_record 转 mp3。
        event_segments = _extract_onebot_raw_segments(event)
        if any(str(s.get("type", "")).lower() == "record" for s in event_segments):
            await _transcode_record_segments(bot, event_segments)
        # TG 媒体段富化：file_id → 字节落临时文件写回 data.file，vision/ASR 的
        # 既有本机路径链路即可直接消费；模块内部自判 TG 事件且绝不抛异常，
        # 非 TG 事件零成本直通，失败保持段原样（标签降级行为不变）。
        await enrich_telegram_file_segments(bot, event, event_segments)
        # 引用链：QQ 的"引用的引用"不随事件下发，需按 id 反查（get_msg）。
        # 只在确有更深 reply 段时才发请求；失败/超时按链条结束，不阻断消息。
        resolved_chain = await collect_reply_chain_async(
            event, lookup=_make_onebot_reply_lookup(bot)
        )
        message = _incoming_from_nonebot_event(
            bot_id=bot_id,
            event=event,
            segments=event_segments or None,
            reply_chain=resolved_chain,
        )
        # 群聊最近图片上下文（vis3 2026-09-13）：无自带图 + 看图意图 →
        # 注入群里 TTL 内最新一张；模型视角即"总结这张图"。
        if (
            message.group_id
            and message.plain_text
            and _VISION_HINT_RE.search(message.plain_text)
            and not any(
                str(s.get("type", "")).strip().lower() == "image"
                for s in message.raw_segments or []
            )
        ):
            recent_url = _latest_fresh_group_image(message.group_id, time.monotonic())
            if recent_url:
                message.raw_segments.append(
                    {"type": "image", "data": {"url": recent_url}}
                )
                # 来源附注（vis3）：随图注入让模型知道这是群里最近的图，非提问者上传。
                message.raw_segments.append(
                    {
                        "type": "text",
                        "data": {"text": "（附注：这张图取自群里最近发送的图片。）"},
                    }
                )
        # 表情贴纸回应·触发 B（bot.reactions）：用户消息命中情绪信号时，
        # 小概率给这条消息贴一个表情表达态度。五层门（开关/每消息去重/
        # 确定性概率/会话冷却/每小时时限）全在 reactions 模块内，失败静默。
        if ".mail" not in event_module:
            try:
                await _maybe_react_on_message(
                    bot,
                    session_key=message.session_id,
                    user_message_id=str(getattr(event, "message_id", "") or ""),
                    text=message.plain_text,
                    config=_config_with_runtime_overrides(config, runtime_settings),
                    trigger="emotion_signal",
                    gate=_REACTION_PROACTIVE_GATE,
                    bot_related=bool(message.mentions_bot),
                )
            except Exception:  # noqa: BLE001, S110 - 贴表情失败绝不影响聊天。
                pass
        # 被动感知（批次 C）：所有群/私聊消息都观察行为、自述画像与小名自学，
        # 不依赖 @/白名单触发；只影响后续态度与称呼，不改变本轮是否回复。
        # observe/learn_profile 是多次 SQLite 事务并与 offload 线程争锁，
        # 必须下放线程池执行，否则每条消息都在事件循环内同步写库。
        if message.sender_id and message.plain_text.strip():
            def _passive_affinity_perception() -> None:
                try:
                    _store = build_character_affinity_store(config)
                    from .character.affinity import classify_behavior
                    from .character.affinity import extract_profile_facts as _epf
                    from .security.content_safety import assess_public_content

                    # 安全评估喂给行为分类：persona_degradation/harassment 等类别
                    # 才能映射到 insult/tease 路径（docs/affinity-design.md §6）。
                    assessment = assess_public_content(
                        message.plain_text,
                        admin="admin" in {
                            str(role).strip().lower() for role in message.sender_roles
                        },
                    )
                    behavior = classify_behavior(
                        message.plain_text,
                        safety_category=assessment.category,
                        safety_action=assessment.action,
                    )
                    if _store is not None:
                        _store.observe(
                            message.sender_id,
                            behavior,
                            group_id=message.group_id or None,
                            display_name=(message.sender_display_name or "").strip() or None,
                            # v5 多因素：说话原文供 f1 温度分级；当日心情供 f4 状态调制。
                            text=message.plain_text,
                            mood_valence=_mood_valence(config),
                        )
                        facts = _epf(message.plain_text)
                        if facts:
                            _store.learn_profile(message.sender_id, message.plain_text)
                        from .character.affinity import extract_learned_nickname

                        learned = extract_learned_nickname(message.plain_text)
                        if (
                            learned
                            and learned not in _NICKNAME_STOPWORDS
                            and len(learned) >= 2
                            and not _learned_name_is_admin_identity(learned, config)
                        ):
                            current = _store.snapshot(message.sender_id).get("nickname") or ""
                            if learned != current:
                                _store.set_nickname(message.sender_id, learned)
                    # 机器人心情（L1）：同一行为+情绪信号驱动 bot 自身心情。
                    _mood = build_character_mood_store(config)
                    if _mood is not None:
                        from .character.emotion import build_emotion_provider

                        _mood.observe_interaction(
                            behavior,
                            [
                                signal.emotion_label
                                for signal in build_emotion_provider(config).analyze(
                                    request_id=message.request_id,
                                    sender_id=message.sender_id,
                                    session_id=message.session_id,
                                    query_text=message.plain_text,
                                )
                            ],
                        )
                except Exception:  # noqa: BLE001, S110 - 被动感知失败不影响主链路。
                    pass

            await asyncio.to_thread(_passive_affinity_perception)
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

                parrot_receipt = await pipeline.handle_async(
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
                await _notify_operational_receipt(message, parrot_receipt)
                # 管道只入队不投递：复读吐槽也要显式走 transport 发出去，
                # 否则 InMemory 队列的假 sent 回执让吐槽永远发不出来。
                parrot_request = _find_sent_request(send_queue, message.request_id)
                if parrot_request is not None:
                    parrot_transport = await _deliver_transport_send_request(
                        bot,
                        event,
                        parrot_request,
                        audit_logger,
                        receipt_repository,
                        send_queue,
                    )
                    await _notify_operational_receipt(message, parrot_transport)
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
            forward_text = await _forward_message_text(
                bot,
                event,
                timeout_seconds=float(
                    getattr(config, "bot_forward_fetch_timeout_seconds", 5.0) or 5.0
                ),
            )
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
        # 视频理解预处理：回复引用的视频反查落盘文件；确认要现场分析时发进度提示。
        try:
            message = await _prepare_video_understanding_message(
                bot,
                message,
                chat.send,
                config=config,
                runtime_settings=runtime_settings,
                media_registry=media_registry,
                media_providers_ready=bool(
                    (vision_provider and _provider_enabled(vision_provider))
                    or (asr_provider and _provider_enabled(asr_provider))
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 预处理失败不影响正常聊天链路，仅留调试痕迹。
            logging.getLogger(__name__).debug(
                "video understanding preprocess skipped type=%s",
                type(exc).__name__,
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
                # 表情贴纸回应·触发 A（bot.reactions）：回复发出后小概率给
                # 用户这条消息贴表情表达态度；同时登记 bot 自己的消息 id，
                # 让后续【表情回应】分区能说出"给我的消息贴了"。
                if ".mail" not in event_module:
                    try:
                        bot_sent_id = transport_receipt.provider_message_id
                        if bot_sent_id:
                            _REACTION_BUFFER.register_bot_message(
                                message.session_id, bot_sent_id
                            )
                        await _maybe_react_on_message(
                            bot,
                            session_key=message.session_id,
                            user_message_id=str(
                                getattr(event, "message_id", "") or ""
                            ),
                            text=message.plain_text,
                            config=_config_with_runtime_overrides(
                                config, runtime_settings
                            ),
                            trigger="after_reply",
                            gate=_REACTION_PROACTIVE_GATE,
                        )
                    except Exception:  # noqa: BLE001, S110 - 贴表情失败绝不影响投递结果。
                        pass
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
            # 走过 transport 分支就不再落回管道回执：管道回执诊断/通知只适用
            # 于无 sent_request 的路径，否则 transport 失败时双诊断+重复通知。
            return
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
                    # 注册表按 cookies 文件 mtime 缓存：热更新 cookie 后自动重建。
                    registry=_cached_content_parser_registry(
                        config, playwright_fetch_backend
                    ),
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
            # 走过 transport 分支就不再落回管道回执：管道回执在此前已通知过，
            # 再落回会重复诊断+重复通知（管道回执诊断仅适用于无 sent_request 的路径）。
            return
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
                    render_backend=render_backend,
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
            # 走过 transport 分支就不再落回管道回执：管道回执在此前已通知过，
            # 再落回会重复诊断+重复通知（管道回执诊断仅适用于无 sent_request 的路径）。
            return
        await _notify_operational_receipt(message, receipt)
        if should_finish_nonebot_matcher(receipt):
            await music.finish(receipt.public_message)

    @today_history.handle()
    async def _handle_today_history(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
        )
        # 评审C1：交互走注入渲染后端的独立实例；today_ctx["capability"] 按产品裁定
        # 仅供定时推送（纯文字），二者在 _register_today_history_scheduler 内分流。
        capability = (
            today_ctx["interactive_capability"]
            if today_ctx is not None
            else build_today_history_capability(config, render_backend=render_backend)
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
                # 空文本 finish 会被 NapCat 报「该消息类型暂不支持查看」。
                await matcher.finish(
                    transport_receipt.public_message or "（处理完成，没有需要展示的内容。）"
                )
        await _notify_operational_receipt(message, receipt)
        if should_finish_nonebot_matcher(receipt):
            await matcher.finish(
                receipt.public_message or "（处理完成，没有需要展示的内容。）"
            )


    async def _is_media_archive_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.MEDIA_ARCHIVE
        )

    media_archive = on_message(rule=_is_media_archive_event, priority=43, block=True)

    async def _enrich_media_archive_message(bot: Bot, event: Event, message: Any) -> None:
        """媒体归档的反查注入（ NapCat get_msg / get_forward_msg）。

        - 同条消息带合并转发 → get_forward_msg 展开逐条正文注入 chat_record_text；
        - 回复的是合并转发 → 反查被引用消息拿 forward id 后同上；
        - 回复的是媒体 → 把 image/animation/video 段注入 reply_media_segments。
        失败一律静默降级（能力层按"无回复媒体"回话）。
        """

        async def _fetch_forward_text(fid: str) -> str:
            try:
                payload = await asyncio.wait_for(
                    bot.call_api("get_forward_msg", message_id=fid),
                    timeout=float(
                        getattr(config, "bot_forward_fetch_timeout_seconds", 5.0)
                    ),
                )
            except Exception:  # noqa: BLE001 - 展开失败按无转发处理。
                return ""
            return _forward_message_text_sync(payload)

        forward_id = _forward_segment_id(event)
        if forward_id:
            forward_text = await _fetch_forward_text(forward_id)
            if forward_text:
                message.chat_record_text = forward_text
                return
        reply_id = str(message.reply_to_message_id or "").strip()
        if not reply_id:
            return
        getter = getattr(bot, "get_msg", None)
        if not callable(getter):
            return
        try:
            payload = await asyncio.wait_for(
                getter(message_id=int(reply_id)), timeout=5.0
            )
        except (asyncio.TimeoutError, ValueError, TypeError):
            return
        except Exception:  # noqa: BLE001 - 反查失败按"无回复媒体"处理。
            return
        segments = _onebot_segments_from_message_payload(payload) or []
        reply_forward_id = ""
        media_segments: list[dict[str, Any]] = []
        for segment in segments:
            seg_type = str(segment.get("type", ""))
            if seg_type in FORWARD_SEGMENT_TYPES:
                reply_forward_id = str((segment.get("data") or {}).get("id") or "").strip()
                break
            if seg_type in {
                "image",
                "photo",
                "sticker",
                "mface",
                "animation",
                "video",
                "video_note",
            }:
                media_segments.append(segment)
        if reply_forward_id:
            forward_text = await _fetch_forward_text(reply_forward_id)
            if forward_text:
                message.chat_record_text = forward_text
                return
        if media_segments:
            message.reply_media_segments = media_segments

    @media_archive.handle()
    async def _handle_media_archive(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event, bot_id=str(getattr(bot, "self_id", "unknown"))
        )
        await _enrich_media_archive_message(bot, event, message)
        receipt = await pipeline.handle_async(
            message,
            offload_capability(
                build_media_archive_capability(
                    config,
                    vision_provider=vision_provider,
                    store=media_archive_store,
                )
            ),
            capability_id="bot.media_archive",
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
                capability_id="bot.media_archive",
                receipt=transport_receipt,
                send_queue=send_queue,
                audit_logger=audit_logger,
            )
            await _notify_operational_receipt(message, transport_receipt)
            if transport_receipt.state.value == "sent":
                return
            if should_finish_nonebot_matcher(transport_receipt):
                await media_archive.finish(
                    transport_receipt.public_message or "（处理完成，没有需要展示的内容。）"
                )
        if should_finish_nonebot_matcher(receipt):
            await media_archive.finish(
                receipt.public_message or "（处理完成，没有需要展示的内容。）"
            )

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
                build_meme_library_capability(
                    meme_library_store, config,
                    mood_valence_fn=lambda: _mood_valence(config),
                )
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
                return build_weather_capability(config, render_backend=render_backend)(synthetic, _decision)

        elif capability_id == "bot.music":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                mode = runtime_settings.get("BOT_MUSIC_MODE", config) or getattr(config, "bot_music_default_mode", "card+voice+link")
                return build_music_capability(
                    config,
                    default_mode=mode,
                    request_store=music_request_store,
                    # 自然语言点歌此前漏传候选 providers：别名/命令路径有、
                    # 这里没有，导致自然语言路径静默丢失 cookie 候选搜索。
                    candidate_providers=(
                        music_candidate_providers(build_cookie_provider(config))
                        if getattr(config, "bot_music_candidates_enabled", False)
                        else None
                    ),
                    render_backend=render_backend,
                )(synthetic, _decision)

        elif capability_id == "bot.wiki":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                return build_wiki_capability(config)(synthetic, _decision)

        elif capability_id == "bot.eat":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                # 与 wiki 分支同型：归一文本必须重写进 plain_text——原文本可能
                # 带多连 @ 前缀，eat 的 ^ 锚定正则会全部失配掉进随机推荐
                # （实弹 17:01:33「@颜佑° @守岸人 菜谱 西红柿炒鸡蛋」当众推错菜）。
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                return build_eat_capability(config, render_backend=render_backend)(synthetic, _decision)

        elif capability_id == "bot.news":
            # F9：自然语言链补 bot.news 分支（新闻类触发此前只有裸命令面）。
            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                return build_news_capability(config)(synthetic, _decision)

        elif capability_id == "bot.epic":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_epic_capability(config, render_backend=render_backend)(message, _decision)

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
                return build_meme_library_capability(
                    meme_library_store, config,
                    mood_valence_fn=lambda: _mood_valence(config),
                )(
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
                return build_today_history_capability(config, render_backend=render_backend)(synthetic, _decision)

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
            offload_sync_capability=capability_id in OFFLOADED_CAPABILITY_IDS,
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
            bot, event, _build_epic_with_backend, "bot.epic", epic
        )

    @weather.handle()
    async def _handle_weather(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, _build_weather_with_backend, "bot.weather", weather
        )

    @market.handle()
    async def _handle_market(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, _build_market_with_backend, "bot.market", market
        )

    @stocks.handle()
    async def _handle_stocks(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, _build_stocks_with_backend, "bot.stocks", stocks
        )

    @fx.handle()
    async def _handle_fx(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, _build_fx_with_backend, "bot.fx", fx
        )

    @commodities.handle()
    async def _handle_commodities(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, _build_commodities_with_backend, "bot.commodities", commodities
        )

    @bond.handle()
    async def _handle_bond(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, _build_bond_with_backend, "bot.bond", bond
        )

    @northbound.handle()
    async def _handle_northbound(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, _build_northbound_with_backend, "bot.northbound", northbound
        )

    @divination.handle()
    async def _handle_divination(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, _build_divination_with_backend, "bot.divination", divination
        )

    @news.handle()
    async def _handle_news(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, build_news_capability, "bot.news", news
        )

    @randpic.handle()
    async def _handle_randpic(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, build_randpic_capability, "bot.randpic", randpic
        )

    @reminder.handle()
    async def _handle_reminder(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, build_reminder_capability, "bot.reminder", reminder
        )

    @affinity.handle()
    async def _handle_affinity(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, _build_affinity_with_backend, "bot.affinity", affinity
        )

    @eat.handle()
    async def _handle_eat(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, _build_eat_with_backend, "bot.eat", eat
        )

    @moegirl.handle()
    async def _handle_moegirl(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, build_moegirl_capability, "bot.moegirl", moegirl
        )

    @moegirl_question.handle()
    async def _handle_moegirl_question(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
        )
        started_at = time.perf_counter()
        # 本地知识库优先：鸣潮/方舟/原神等本地语料命中时直接回答，
        # 绝不外查萌百（外链质量差且可能与本地设定冲突）。
        kb_body = None
        try:
            kb_body = await asyncio.to_thread(
                local_kb_answer, config, message.plain_text
            )
        except Exception:  # noqa: BLE001 - 本地库失败走萌百链路。
            kb_body = None
        if kb_body:
            from plugins.bot_unified_runtime.contracts import (
                CapabilityResult,
                PrivacyLevel,
                RiskLevel,
                SendPolicy,
            )

            kb_result = CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.moegirl",
                kind="text",
                title="",
                body=kb_body,
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                send_policy=SendPolicy.IMMEDIATE,
                audit_tags=["moegirl_question", "local_kb_first"],
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
                capability=lambda _m, _d: kb_result,
                capability_id="bot.moegirl",
                record_diagnostic=False,
                offload_sync_capability=False,
                history_recorder=history_recorder,
                history_kind="command",
                operational_notifier=_notify_operational_receipt,
            )
            if should_finish_nonebot_matcher(receipt):
                await moegirl_question.finish(receipt.public_message)
            return
        try:
            # 网络查询放线程池，紧超时由 sources 层预算约束（默认 ≤2×5s）。
            outcome = await asyncio.to_thread(
                question_lookup, message.plain_text, config=config
            )
        except Exception:  # noqa: BLE001 - 查询层异常一律按降级处理。
            outcome = None
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        if outcome is None or outcome.status != "hit" or not outcome.body:
            # 未命中/网络失败 → 无感降级：同一条消息转交人格聊天链路，
            # 管线、门控、历史归档与 /bot.chat 完全一致。
            receipt = await pipeline.handle_async(
                message, chat_capability, capability_id="bot.chat"
            )
            await _notify_operational_receipt(message, receipt)
            sent_request = _find_sent_request(send_queue, message.request_id)
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
                transport_receipt = await _deliver_transport_send_request(
                    bot,
                    event,
                    sent_request,
                    audit_logger,
                    receipt_repository,
                    send_queue,
                )
                await _notify_operational_receipt(message, transport_receipt)
                if (
                    history_should_record
                    and transport_receipt.state.value == "sent"
                ):
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
                if should_finish_nonebot_matcher(transport_receipt):
                    await moegirl_question.finish(transport_receipt.public_message)
                return
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
            if should_finish_nonebot_matcher(receipt):
                await moegirl_question.finish(receipt.public_message)
            return
        outcome_entity = outcome.entity
        outcome_body = outcome.body

        def capability(
            incoming: IncomingMessage, _decision: Any
        ) -> CapabilityResult:
            return CapabilityResult(
                request_id=incoming.request_id,
                capability_id="bot.moegirl",
                kind="text",
                title="萌娘百科",
                body=outcome_body,
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=[
                    "moegirl",
                    "moegirl_question",
                    f"moegirl_entity:{outcome_entity[:20]}",
                    f"moegirl_ms:{elapsed_ms}",
                ],
            )

        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            diagnostics_store=diagnostics_store,
            capability=capability,
            capability_id="bot.moegirl",
            record_diagnostic=False,
            history_recorder=history_recorder,
            history_kind="command",
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
            await moegirl_question.finish(receipt.public_message)





_register_nonebot_handlers()

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
from .config import Config, remap_runtime_data_paths, translate_env_keys
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
from .domains.assistant.campus.campus import build_campus_source
from .domains.assistant.daily.capabilities.daily_assist import (
    build_daily_assist_capability,
)
from .domains.chat_reply.capabilities.affinity import build_affinity_capability
from .domains.chat_reply.capabilities.chat import (
    build_admin_roster_text as _build_admin_roster_text_for_chat,
)
from .domains.chat_reply.capabilities.group_info import (
    build_group_info_capability,
    build_onebot_api_bridge,
)
from .domains.chat_reply.character.history import ConversationHistoryRecorder
from .domains.chat_reply.ingest.message_context import (
    collect_reply_chain,
    collect_reply_chain_async,
    format_reply_chain,
    normalize_message_segments,
)
from .domains.chat_reply.llm_engine.model_router import build_model_router
from .domains.chat_reply.runtime.aliases import (
    build_command_alias_resolver,
    normalize_command_text,
)
from .domains.chat_reply.runtime.base_router import (
    RouteDecision,
    RouteKind,
    classify_message_route,
    clear_route_decision_cache,
    is_command_form_text,
    list_route_rules_for_audit,
    looks_like_command_text,
)
from .domains.chat_reply.runtime.content_route import (
    SHARED_CONTENT_ROUTE_ENGINE as _SHARED_CONTENT_ROUTE_ENGINE,
)
from .domains.chat_reply.runtime.content_route import (
    build_router_cb as _build_content_route_router_cb,
)
from .domains.chat_reply.runtime.event_idempotency import build_event_idempotency_table
from .domains.chat_reply.runtime.group_cache import GroupInfoCache
from .domains.chat_reply.runtime.parrot import ParrotDetector
from .domains.core.config.config_readiness import (
    llm_generation_parameter_errors,
    persona_context_preflight_errors,
)
from .domains.core.credentials.platform_credentials import (
    cookie_expiry_report,
    cookie_login_check,
    cookie_login_start,
    cookie_status_text,
    import_cookie_header,
    is_cookie_command,
    parse_cookie_command,
)
from .domains.divination.capabilities.divination import build_divination_capability
from .domains.files.capabilities.download import build_download_capability
from .domains.files.capabilities.group_files import DirtyGuard, GroupFileStore
from .domains.finance.capabilities.fx import build_fx_capability
from .domains.finance.capabilities.market import (
    build_bond_capability,
    build_commodities_capability,
    build_market_capability,
    build_northbound_capability,
)
from .domains.finance.capabilities.stocks import build_stocks_capability
from .domains.food.capabilities.eat import build_eat_capability
from .domains.link_parse.capabilities.content_parser import build_content_capability
from .domains.location.capabilities.moegirl import (
    build_moegirl_capability,
    extract_moegirl_query,
    question_lookup,  # 2026-09-27 百科接地批（行数不变：7087/7088 在册 matcher 坐标零顶漂）
    resolve_grounding_for_entity,
)
from .domains.location.capabilities.wiki import build_wiki_capability
from .domains.media.capabilities.media_archive import build_media_archive_capability
from .domains.media.capabilities.tts import (
    build_tts_capability,
    maybe_attach_voice,
    should_voice_reply,
)
from .domains.media.video.video_pipeline import (
    _MEDIA_RUNTIME_SINGLETON as _MEDIA_RUNTIME_SINGLETON,
)
from .domains.media.video.video_pipeline import _VIDEO_ACK_TEXT as _VIDEO_ACK_TEXT
from .domains.media.video.video_pipeline import (
    _VIDEO_ACK_THROTTLE as _VIDEO_ACK_THROTTLE,
)
from .domains.media.video.video_pipeline import (
    _fetch_reply_video_file as _fetch_reply_video_file,
)
from .domains.media.video.video_pipeline import (
    _get_media_registry as _get_media_registry,
)
from .domains.media.video.video_pipeline import _local_file_usable as _local_file_usable
from .domains.media.video.video_pipeline import (
    _prepare_video_understanding_message as _prepare_video_understanding_message,
)
from .domains.media.video.video_pipeline import _provider_enabled as _provider_enabled
from .domains.media.video.video_pipeline import (
    _register_bot_sent_video_assets as _register_bot_sent_video_assets,
)
from .domains.media.video.video_pipeline import (
    _video_understanding_enabled_now as _video_understanding_enabled_now,
)
from .domains.meme.capabilities.meme import build_meme_capability
from .domains.meme.capabilities.meme_library import build_meme_library_capability
from .domains.meme.capabilities.randpic import (
    build_randpic_capability,
    pick_gallery_image,
)
from .domains.meme.reactions.engine import (
    SHARED_PROACTIVE_GATE as _REACTION_PROACTIVE_GATE,
)
from .domains.meme.reactions.engine import SHARED_REACTION_BUFFER as _REACTION_BUFFER
from .domains.meme.reactions.engine import ProactiveGate as _ReactionProactiveGateClass
from .domains.meme.reactions.engine import (
    describe_chat_reactions as _describe_chat_reactions,
)
from .domains.meme.reactions.engine import (
    infer_signal_intent as _infer_reaction_signal_intent,
)
from .domains.meme.reactions.engine import is_sad_message as _is_sad_reaction_message
from .domains.meme.reactions.engine import (
    maybe_react_on_message as _maybe_react_on_message,
)
from .domains.meme.reactions.engine import (
    maybe_react_telegram_message as _maybe_react_telegram_message,
)
from .domains.meme.reactions.engine import (
    normalize_onebot_emoji_like as _normalize_onebot_emoji_like,
)
from .domains.music.capabilities.music import build_music_capability
from .domains.ops.audit.file_logger import build_audit_with_file_log
from .domains.ops.monitor.alerts import (
    AdminAlertSuppression,
    AdminTarget,
    AlertContent,
    build_typed_admin_targets,
    notify_operational_issue,
    send_admin_alert_requests,
)
from .domains.ops.monitor.disconnect_notice import (
    DisconnectNotifier,
    disconnect_notice_options_from,
)
from .domains.ops.monitor.intent_telemetry import build_intent_telemetry
from .domains.ops.monitor.result_unknown import ResultUnknownLedger
from .domains.ops.smoke.diagnostics import (
    DiagnosticsStore,
    RuntimeDiagnostic,
    build_diagnostics_store,
    build_runtime_diagnostic,
    build_why_result,
    infer_policy_gate_fields,
)
from .domains.render.render_backends import build_render_backend
from .domains.schedule.capabilities.reminder import build_reminder_capability
from .domains.subscribe.capabilities.epic import build_epic_capability
from .domains.subscribe.capabilities.news import build_news_capability
from .domains.subscribe.capabilities.today_history import build_today_history_capability
from .domains.weather.capabilities.weather import build_weather_capability
from .llm import LLMProvider, OpenAICompatibleLLMProvider, StaticLLMProvider


def _runtime_scripts_path(value: str):
    from scripts.runtime_paths import runtime_path

    return runtime_path(value)
from .domains.chat_reply.runtime import deadline, mentions
from .domains.chat_reply.runtime.natural_language import (
    detect_natural_command,
    runtime_set_command_text,
)
from .domains.chat_reply.runtime.question_intent import looks_like_question_text
from .domains.chat_reply.runtime.settings import (
    build_instance_settings_manager,
    effective_instance,
    normalize_group_policy_mode,
)
from .domains.core.credentials.credential_health import check_credentials_and_report
from .domains.core.search.web_search import build_web_search_provider
from .domains.files.sources.downloader import MediaDownloader
from .domains.link_parse.parsers import (
    build_cookie_provider,
    extract_http_urls,
    music_candidate_providers,
)
from .domains.link_parse.support.parse_history import (
    build_parse_history_result,
    build_parse_history_store,
)
from .domains.media.ingest.telegram_media import enrich_telegram_file_segments
from .domains.meme.sources.meme_library import MemeLibraryStore
from .domains.meme.sources.meme_library_listener import absorb_event_images
from .domains.meme.sources.meme_search import build_meme_search_provider
from .domains.meme.sources.reaction_store import ReactionStore
from .domains.music.data.music_request_store import MusicRequestStore
from .domains.transport.sender import (
    OneBotV11Bot,
    ReceiptRepository,
    build_receipt_repository,
    drain_send_queue_once,
    send_onebot_v11,
)
from .domains.transport.sender.timeout import set_transport_timeout_provider

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

#: 重 IO / 同步正文命令的**观测名册**（不是执行路径的选择器）。
#: ⚠ X4 续批改口：过去根汇口按"在不在这张表里"二选一（在＝`handle_async` 下放，
#: 不在＝`pipeline.handle` 同步跑在事件循环线程上）——名单外的一枚同步命令冻住的是
#: **整片会话**而不只是那一条命令，且低频管理命令恰好全在名单外（`/bot recent`·
#: `queue`·`logs`·`runtime`·`setup llm`）。现在根汇口一律走 `handle_async`，下放由
#: 管线内部 `ensure_offloaded`（判"正文是不是协程"）这一把尺决定；本表只留两个用途：
#: ① 性能面在册断言（`tests/test_perf_hotpath.py`、`test_finance_routing.py` 要求
#: 重命令必须登记）；② 人读"哪些命令是重 IO"。下面逐条注释即当时登记的理由，保留为史实。
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
        # bot.status（/bot status 宿主机附块）：读数含 wmic/注册表/磁盘等同步阻塞调用，
        # 留在事件循环里会冻整轮。此前不在册 ⇒ echo 侧恒走"只读缓存不出卡"降级
        # （S-VISUAL 现算，需求 5「说出宿主机状态并出卡」的那半截断在这枚名单）。
        "bot.status",
    }
)


def _attach_voice_reply(inner: Any, *, config: Config) -> Any:
    """给 chat 能力附加语音（bot.tts 的对话自动配音）。

    包装而非改 chat 内部：人格回复本身零改动，配音只是出站前的增益。合成是
    阻塞 HTTP，故放线程池执行，不占事件循环；任一环节失败都原样返回原结果
    （maybe_attach_voice 内部已 fail-open）。

    短路用**完整门链谓词** ``should_voice_reply``（开关 / 未带音频 / 出自
    bot.chat / 会话范围 / 概率门）：谓词判否时连线程调度都不付。谓词是确定性
    纯函数，``maybe_attach_voice`` 内部会再判一次且结论必然相同——所以这只是
    省掉一次线程投递，出站结果与改动前逐字节一致。
    """

    async def capability(message: Any, decision: Any) -> Any:
        result = await inner(message, decision)
        if not should_voice_reply(config, message, result):
            return result
        return await asyncio.to_thread(
            maybe_attach_voice, message, result, config=config
        )

    return capability


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

    from .domains.chat_reply.character.memory import (
        SQLiteMemoryRepository,
        build_memory_bus_for_writer,
    )
    from .domains.chat_reply.character.memory_extract import (
        extract_memory_texts,
        store_extracted_memories,
    )

    # 画像腿（需求 11）：装配口只负责「拿库 + 算键」，判据全在 person_profile 那侧。
    # build_person_profile_store 先判 bot_person_profile_enabled 再建库 ⇒ 门没开时
    # 返回 None 且**连库文件都不碰**（缺省关态逐字节不变，同 bus 那条腿的家规）。
    # 键必须由 person_profile_key(sender_id, platform_domain) 现算：读侧将来也用
    # 这一把，任何一边自拼 f"{domain}:{uid}" 或漏传域 ⇒ 两形永不相交（台账 #33★）。
    from .domains.chat_reply.character.person_profile import (
        build_person_profile_store,
        person_profile_key,
    )

    # A（bus 开闸前置，S-FIX-ATK-MEMORY-FIX）：抽取腿必须带总线构造仓储——开关开时
    # derived 事实直落总线（provenance=derived），不再写旧表被影子读洗成 explicit。
    # 开关关（现网缺省）时 build_memory_bus_for_writer 返回 None 且**不碰库**
    # （memory_bus_v2.build_memory_bus 先判 enabled 再连 store），构造参数 bus=None
    # 与不传等价 ⇒ 缺省关态逐字节不变（SQLiteMemoryRepository docstring 承诺）。
    repository = SQLiteMemoryRepository(
        config.bot_memory_db_path, bus=build_memory_bus_for_writer(config)
    )
    router = model_router if model_router is not None else build_model_router(config)
    worker_lock = threading.Lock()
    cooldown_until = 0.0
    log = logging.getLogger(__name__)

    def setting(key: str, default: Any) -> Any:
        if runtime_settings is not None:
            return runtime_settings.get_or(key, default)
        return default

    def _writer(
        *,
        user_text: str,
        reply_text: str,
        sender_id: str,
        session_id: str,
        platform_domain: str = "",
    ) -> None:
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
                    profile_store = build_person_profile_store(config)
                    store_extracted_memories(
                        repository,
                        subject_user_id=sender_id,
                        session_id=session_id,
                        texts=texts,
                        profile=profile_store,
                        person_key=(
                            person_profile_key(sender_id, platform_domain)
                            if profile_store is not None else ""
                        ),
                        original_user_text=user_text,
                    )
            if reminder_extract_on:
                from .domains.chat_reply.character.memory_extract import (
                    extract_reminder_drafts,
                    store_extracted_reminders,
                )
                from .domains.schedule.store.reminders import (
                    _local_now as _reminder_local_now,
                )
                from .domains.schedule.store.reminders import build_reminder_store

                # 作用域归属=中央 session_keys 判据（A-ING-3：partition(":") 自拆误判下划线群键）。
                target_scope, target_id = _reminder_target_from_session_key(session_id, sender_id)
                drafts = extract_reminder_drafts(
                    provider, user_text=user_text, reply_text=reply_text,
                    generation_options=_generation_options(120),
                    now=_reminder_local_now(),
                )
                if drafts:
                    store_extracted_reminders(
                        build_reminder_store(config),
                        drafts=drafts,
                        session_key=session_id,
                        sender_id=sender_id,
                        target_scope=target_scope,
                        target_id=target_id,
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
    from .domains.chat_reply.capabilities.chat import looks_like_chat_text
    from .domains.schedule.auto_send import is_auto_send_command_text

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
        # OneBot v11 的 message_id 是整数，TG/Discord 一类适配器给的是任意字符串。
        # 旧写法先 int() 再调，非数字 id 会在 try 之前就被 ValueError 吞成 None ⇒
        # 那条腿在字符串 id 的平台上永久哑火，且读数与「反查失败」一模一样。
        looked_up = int(message_id) if str(message_id).isdigit() else message_id
        try:
            payload = await asyncio.wait_for(
                getter(message_id=looked_up), timeout=3.0
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
    return mentions.detect_name_mention(text, _AFFINITY_NICKNAMES_CACHE)


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
    visual_types = {"image", "face", "mface", "marketface", "sticker", "video", "photo", "animation", "video_note"}
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
    # 日常助理（收件箱速记/早晚简报/吃什么推荐；消费点 character/daily_assist.py）
    ("BOT_DAILY_ASSIST_ENABLED", "bot_daily_assist_enabled"),
    ("BOT_DAILY_ASSIST_DIR", "bot_daily_assist_dir"),
    ("BOT_DAILY_ASSIST_PUSH_USER_IDS", "bot_daily_assist_push_user_ids"),
    ("BOT_DAILY_ASSIST_MEAL_TIMES", "bot_daily_assist_meal_times"),
    ("BOT_DAILY_ASSIST_MORNING_TIME", "bot_daily_assist_morning_time"),
    ("BOT_DAILY_ASSIST_EVENING_TIME", "bot_daily_assist_evening_time"),
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
        # PATH-REMAP-GUARD 闭合波（2026-10-04）：``model_copy(update=...)``
        # 不重跑校验器，所以热表里一旦出现名册内的路径键，``data/...`` 裸值会绕过
        # 「折进 BOT_RUNTIME_DATA_DIR」这一步、按 CWD 解析落进源码树（AGENTS 铁律 6）。
        # 把合并结果**当实参**喂进装载期校验器的等价体 ⇒ 绕过在结构上不可能，而不是
        # 只靠「热表里不许登记路径键」的禁令。助手幂等：已折叠的读数逐字不变（锁
        # tests/test_config_model_copy_path_remap_guard.py::test_hot_path_extra_remap_pass_is_a_verified_noop）。
        return remap_runtime_data_paths(config.model_copy(update=updates))
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

# 子转发递归展开闸（2026-09-18 核心链路排查）：旧实现 `nested_ids[:4]`
# 只展开**一层**且不递归——"转发里再转发"的聊天记录整段丢失，表现为
# 提示词里只剩 `[合并转发:L3]` 占位符（用户实测「递归子记录读不了」）。
# 现按深度递归展开，同时设三道闸防递归爆炸与超时叠加：
#   ① 深度上限 _FORWARD_NESTED_MAX_DEPTH；
#   ② 单条消息的子转发总节点上限 _FORWARD_NESTED_MAX_TOTAL；
#   ③ 主转发 + 全部子转发共享的总超时预算（见 _forward_message_text）。
# 环引用（A→B→A）由 seen 集合去重拦住，必然终止。
_FORWARD_NESTED_MAX_DEPTH = 3
_FORWARD_NESTED_MAX_TOTAL = 12


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
    异常都被静默吞掉；只要 SnowLuma 换成对象形态 / 改字段名 / 带 shell 包装，
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
                elif seg_type in FORWARD_SEGMENT_TYPES:
                    # 递归子转发：此处只插占位标记，正文由 _forward_message_text
                    # 按 data.id 二次反查展开（sync 函数不能 await）。
                    nested_id = str((data or {}).get("id") or "").strip() if isinstance(data, dict) else ""
                    parts.append(f"[合并转发:{nested_id}]" if nested_id else "[合并转发]")
                elif seg_type == "json" or seg_type == "xml":
                    value = str(data.get("data", "")).strip() if isinstance(data, dict) else ""
                    if value:
                        parts.append("[卡片消息]")
            text = " ".join(parts).strip()
        if text:
            lines.append(f"{nickname}：{text}" if nickname else text)
    return _neutralize_forward_body("\n".join(lines))


def _collect_nested_forward_ids(result: Any) -> list[str]:
    """从 get_forward_msg 回执里收集嵌套子转发的 id（保序去重，最多 8 个）。"""
    payload = result
    if isinstance(payload, dict) and "messages" not in payload and "data" in payload:
        inner = payload.get("data")
        if isinstance(inner, dict):
            payload = inner
    if hasattr(payload, "messages"):
        payload = payload.messages
    if isinstance(payload, dict):
        messages = payload.get("messages") or payload.get("message")
    else:
        messages = getattr(payload, "messages", None) or getattr(payload, "message", None)
    if not isinstance(messages, list):
        return []
    ids: list[str] = []
    for item in messages:
        segments = None
        if isinstance(item, dict):
            segments = item.get("message") or item.get("segments") or item.get("content")
        else:
            segments = getattr(item, "message", None) or getattr(item, "segments", None)
        for segment in segments or []:
            if isinstance(segment, dict):
                seg_type = str(segment.get("type", ""))
                data = segment.get("data") or {}
            else:
                seg_type = str(getattr(segment, "type", ""))
                data = getattr(segment, "data", {}) or {}
            if seg_type in FORWARD_SEGMENT_TYPES and isinstance(data, dict):
                nested_id = str(data.get("id") or "").strip()
                if nested_id and nested_id not in ids:
                    ids.append(nested_id)
            if len(ids) >= 8:
                return ids
    return ids


async def _forward_message_text(
    bot: Any, event: Any, timeout_seconds: float | None = None
) -> str:
    """读取合并转发（forward）消息正文；失败返回空串并留 warning。

    只在消息确实包含 forward 段时才调用 SnowLuma 的 get_forward_msg。
    普通消息 id 不是合并转发 id，NapCat 时期会拒绝为"消息已过期或者为
    内层消息"；带上限超时是为了防止上游回执异常时卡住消息处理。

    失败必须**可观测**：早期版本把异常全吞掉，导致"转发无回应"现场没有任何
    线索（本次排查即因此耗时）。现在失败路径固定打一条 warning。

    嵌套展开（2026-09-18）：子转发按 ``_FORWARD_NESTED_MAX_DEPTH`` 递归展开
    （旧实现只展开一层，更深层只剩 ``[合并转发:id]`` 占位符），子节点总数封顶
    ``_FORWARD_NESTED_MAX_TOTAL``，主/子反查共享一个总超时预算；同 id 只取一次，
    环引用必然终止。
    """
    forward_id = _forward_segment_id(event)
    if not forward_id:
        return ""
    call_api = getattr(bot, "call_api", None)
    if not callable(call_api):
        logging.getLogger(__name__).warning("forward message fetch skipped: bot has no call_api")
        return ""
    per_call_timeout = float(timeout_seconds or _FORWARD_MESSAGE_API_TIMEOUT_SECONDS)
    # 总预算：主转发 + 全部子转发反查共享，防深链把单条消息处理拖到分钟级。
    deadline = time.monotonic() + per_call_timeout * (_FORWARD_NESTED_MAX_DEPTH + 1)
    seen: set[str] = {forward_id}
    expanded_count = 0

    async def _fetch(one_id: str) -> Any:
        """单次反查：单次上限与剩余总预算取小（至少 0.5s，避免负超时）。"""
        remaining = deadline - time.monotonic()
        return await asyncio.wait_for(
            call_api("get_forward_msg", message_id=one_id),
            timeout=max(0.5, min(per_call_timeout, remaining)),
        )

    async def _expand(one_id: str, payload: Any, depth: int) -> str:
        """深度优先展开：返回本层正文（含其后代子转发正文）。"""
        nonlocal expanded_count
        body = _forward_message_text_sync(payload)
        if depth >= _FORWARD_NESTED_MAX_DEPTH:
            return body
        for nested_id in _collect_nested_forward_ids(payload):
            if expanded_count >= _FORWARD_NESTED_MAX_TOTAL or time.monotonic() >= deadline:
                break
            if nested_id in seen:
                continue  # 环引用/重复引用：同 id 只取一次。
            seen.add(nested_id)
            expanded_count += 1
            try:
                nested_result = await _fetch(nested_id)
            except Exception as exc:  # noqa: BLE001 - 子转发失败不阻断主正文。
                logging.getLogger(__name__).warning(
                    "nested forward fetch failed id=%s type=%s detail=%s",
                    nested_id,
                    type(exc).__name__,
                    str(exc)[:120],
                )
                continue
            nested_text = await _expand(nested_id, nested_result, depth + 1)
            if nested_text:
                body = (body + "\n" if body else "") + f"—— 子转发 {nested_id[:8]} ——\n{nested_text}"
        return body

    try:
        result = await _fetch(forward_id)
    except asyncio.TimeoutError:
        logging.getLogger(__name__).warning("forward message fetch timed out after %.1fs id=%s", per_call_timeout, forward_id)
        return ""
    except Exception as exc:  # noqa: BLE001 - 上游回执异常不阻断消息处理。
        logging.getLogger(__name__).warning(
            "forward message fetch failed id=%s type=%s detail=%s",
            forward_id,
            type(exc).__name__,
            str(exc)[:160],
        )
        return ""
    text = await _expand(forward_id, result, 0)
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

    NapCat 时期收到的 QQ 语音落盘是 SILK 裸流（.slk），ffmpeg 无法解码，
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
            # NapCat 时期偶发挂起不返回：无超时会把这个用户的后续消息永久卡死。
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


def _group_welcome_text(nickname: str = "") -> str:
    """入群欢迎语（审查 B-05）：守岸人语气一行；昵称拿不到退通用称呼。

    不点破 QQ 号、不写「新成员」机器腔；括号动作用中文括号（identity.md 口径）。
    """
    who = f"{nickname}，" if nickname.strip() else ""
    return (
        "（回头，朝门口轻轻点头）"
        f"{who}欢迎来到这片海岸。海风正好，不必拘束，随意坐吧。"
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


def _assemble_model_prices(config: object, settings_store: object | None) -> dict[str, dict[str, float]]:
    """装配期价表：模型注册表（基准）→ BOT_MODEL_PRICES（手工覆盖）。

    2026-09-18 价格单源化：注册表是价目表导入脚本（scripts/import_model_prices.py）
    的落点，此前只喂 V2.1 计费链路；遗留记账链路（chat 侧 cost_milli 审计标签）
    只读 ``config.bot_model_prices``（默认空 dict），于是"导入了价目表，账单还是
    未计价"。这里把注册表投影进同一口径，让导入一次即全链路生效；读不到价表
    只影响成本注记，绝不阻塞装配。
    """
    try:
        from .domains.chat_reply.llm_engine.pricing import (
            merge_model_prices,
            registry_model_prices,
        )

        registry: object = {}
        list_model_registry = getattr(settings_store, "list_model_registry", None)
        if callable(list_model_registry):
            registry = list_model_registry() or {}
        override: object = getattr(config, "bot_model_prices", {}) or {}
        get_or = getattr(settings_store, "get_or", None)
        if callable(get_or):
            override = get_or("BOT_MODEL_PRICES", override)
        return merge_model_prices(registry_model_prices(registry), override)
    except Exception:  # noqa: BLE001 - 价表异常不阻塞装配（退化为未计价）。
        return {}


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
    return dict(result, **deadline.deadline_receipt_view(send_request.audit_tags))  # 预算耗尽回执自解释（S-T-DEADLOG-2；刻意行内等值替换＝净 0 行，插行会顶漂 campus matcher 登记坐标；组装口与提取口同在 domains/chat_reply/runtime/deadline.py）


def _policy_gate_values(
    audit_logger: AuditRepository | None,
    receipt: DeliveryReceipt,
    message: IncomingMessage | None,
) -> dict[str, object]:
    """门禁「门因」回读：把拦下这条消息的哪一层/哪道门写成事件行上的受控字段。

    病形（2026-09-29 实跑取证）：群侧大量 ``event=pipeline_result
    receipt_state=blocked transport=policy`` 读不出**为什么**被拦——判定链上的
    reason 一直在（``policy/gate.py::_denied``），但 ``DeliveryReceipt`` 不承载
    它、blocked 腿又没有 SendRequest，于是唯一留着门因的地方只剩 pipeline 拦截
    时 append 的那条 ``AuditRecord(stage="policy")``。本函数把它读回日志行。

    三条红线（各有一枚回归锁，tests/test_policy_gate_reason_observability.py）：
    ① 取值只认封闭枚举（规则 3）——判据真身在
    ``domains/ops/smoke/diagnostics.py::infer_policy_gate_fields``，自由文本结构上
    进不了字段；② 零判定——被拦的照旧被拦，本函数不产决策、不新增发送；
    ③ 非 policy 腿（transport=runtime/onebot）连审计库都不读，正常发送腿一字节
    不多。读不到留痕/读库异常一律退回旧行形态（空 dict），观测面绝不牵动消息链路。
    根文件只「取记录 + 转交」，不许在发射点旁长出第二份解析逻辑（同一枚锁执法）。
    """
    if receipt is None or message is None or receipt.transport != "policy":
        return {}
    if audit_logger is None:
        return {}
    try:
        return infer_policy_gate_fields(audit_logger.list_records(message.request_id))
    except Exception:  # noqa: BLE001 - 留痕读不到就退回旧行形态，不许牵动链路。
        return {}


def _incoming_from_nonebot_event(
    event: Any,
    bot_id: str = "unknown",
    adapter_name: str = "",
    segments: list[dict[str, Any]] | None = None,
    reply_chain: list[Any] | None = None,
    feature_enabled: Callable[[str], bool] | None = None,
) -> IncomingMessage:
    try:
        text = event.get_plaintext()
    except ValueError:
        # NoticeEvent 族（戳一戳等）没有 message 字段；摄取按空文本降级，
        # 话术文案由 handler 侧入参提供，不依赖事件正文。
        text = ""
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
        # Mail-1 收口（2026-10-03 席35 授权施工）：无 @ 的 sender_id＝未经适配器
        # 地址恢复的不可信形态（裸名族 mailparser 会把编码字整串塞进 id）——显式
        # 打 unverified 前缀，堵冒名 trusted 判定；真实地址（含 @）不受影响。
        if sender_id and "@" not in sender_id:
            sender_id = f"unverified-mail:{sender_id}"
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
    # 频道拼格专辑（席位 S18）：``media_group_id`` 只挂在 TG **事件**上、段里读不到，
    # 故在归一**之前**按事件盖章到媒体段并累计张数，让文本面出一条带计数的专辑摘要
    # 而不是 N 句孤立 ``[图片]``；段一张不丢，富化/识图腿照旧逐张消费。
    # 局部导入先例＝本函数内的 file_reader / injection（避开模块级成环）。
    # 非 TG 事件 / 无专辑号 / 形状不合法 ⇒ 返回 None，既有行为逐字节不变。
    from .domains.chat_reply.ingest.message_context import (
        telegram_album_context as _telegram_album_context,
    )

    album_context = _telegram_album_context(
        event, raw_segments, normalized_adapter, session_id=str(session_id or "")
    )
    normalized_message = normalize_message_segments(raw_segments, album=album_context)
    if normalized_message.plain_text.strip():
        text = normalized_message.plain_text
    file_context: list[str] = []
    try:
        from .domains.files.sources import file_reader
        file_segments = raw_segments if feature_enabled is None or feature_enabled("bot.ingress.file_read") else []
        for segment in file_segments:
            if str(segment.get("type", "")).lower() != "file":
                continue
            data = segment.get("data") or {}
            candidate = str(data.get("file") or data.get("path") or "").strip()
            if candidate:
                parsed_file = file_reader.read_supported_file(candidate)
                note = (
                    f"[文件内容：{parsed_file.title or parsed_file.path.name}]\n"
                    # T2 打标唯一咽喉（S-SAFE2 2026-09-28 hub 申请 1）：文件正文一律外部
                    # 低信任内容，来源行由 file_reader 生成，不在这里手抄第二份措辞。
                    + file_reader.labelled_text(
                        parsed_file,
                        display_name=str(parsed_file.title or parsed_file.path.name),
                    )
                ) if parsed_file.text else file_reader.file_read_failure_note(parsed_file)
                file_context += [note] if note else []
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
    # 评论区/群话题上下文（席位 S18）：``message_thread_id`` 与 ``is_topic_message``
    # 平台会送而我方全树零消费者（thread_id 只被读进契约字段、无人再读），这里给它
    # 一个真消费者——**复用 ``.thread_id`` 那一枚字段**，不新建第二套。
    # 🔴 必须在 ``own_text`` 捕获与引用链拼接**之后**追加：它是 ``^...$`` 锚的
    # 命令判据与点名判据的输入，追加在前会把内部标记喂进 command_text 并打掉
    # 行尾锚（file_context 同段那处即此坑的在册先例）。
    # 结构性上限：Bot API 读不到任意评论历史，本腿只带"这条出自哪里"。
    from .domains.chat_reply.ingest.message_context import (
        telegram_topic_context_note as _telegram_topic_context_note,
    )

    topic_note = _telegram_topic_context_note(event, normalized_adapter)
    if topic_note:
        text = f"{text}\n{topic_note}".strip()
    is_tome = getattr(event, "is_tome", None)
    adapter_mentions_bot = bool(is_tome()) if callable(is_tome) else False
    # 点名判定：
    # - 人格名（岸宝/守岸人…）与策展昵称是**真点名**语义，两边都算——人格展示名
    #   可能并不出现在 _RUNTIME_MENTION_TERMS 里，只查拼接前文本会漏判（实测回归）。
    # - 好感度自学习小名常撞常用词，只认用户自己打的字：被引用内容里出现"岸宝"
    #   不应让机器人以为是叫自己（评审 L1）。
    persona_name_mention = mentions.detect_name_mention(
        own_text, _RUNTIME_MENTION_TERMS
    ) or mentions.detect_name_mention(text, _RUNTIME_MENTION_TERMS)
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
    # 审查 B-07：OneBot v11 sender.level（QQ 群等级）是用户画像维度，摄取层此前
    # 未读取。容缺省空 str 化（照 group_title 先例；`or ""` 让 None/0/空串统一落
    # None——等级 0 无展示意义，宁缺毋滥）；TG/Mail 事件无该形态自然落 None。
    sender_level = str(getattr(onebot_sender, "level", None) or "").strip() or None
    group_title = str(getattr(event, "group_title", None) or "").strip() or None
    sender_display_name = sender_card or sender_nickname or None
    if sender_display_name:
        # 显示名伪装腿（S-SAFE2 2026-09-28 hub 申请 3）：昵称/群名片是**用户自己填的**
        # 字符串，RTL/零宽/同形异码可以把它伪装成"守岸人"或管理员名进模型与卡片。
        # 消毒唯一真身＝security/injection.sanitize_display_name（不误伤＝普通名字逐字节
        # 不变，误伤一次等于替用户改名），本处不写第二份正则。
        from .domains.chat_reply.security.injection import (
            sanitize_display_name as _sanitize_sender_display_name,
        )

        sender_display_name = (
            _sanitize_sender_display_name(sender_display_name) or None
        )
    # 最近图片登记（MM-VIS-1 缺陷 3）：旧判据 `group_id is not None` 把私聊整段挡在
    # 门外＝私聊连"刚才那张图"的兜底都没有。键位换成两型都存在的 session_id。
    if session_id:
        _remember_session_images(
            str(session_id), normalized_message.segments or raw_segments
        )
    return IncomingMessage(
        platform=platform,
        adapter=adapter,
        bot_id=bot_id,
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        group_id=str(group_id) if group_id is not None else None,
        plain_text=text, command_text=mentions.strip_leading_name_mention(own_text, _RUNTIME_MENTION_TERMS),  # 派生只认拼接前的 own_text
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
        sender_level=sender_level,
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
            from .domains.transport.sender.nonebot import send_nonebot_message

            return await send_nonebot_message(bot, None, send_request)

        # B4b Tier2-b 接线骨架（缺省关=现状逐字节）：核验键未落地（键归属
        # B4a，getattr 缺省 False）或显式关闭时传 None，与不传该形参等价；
        # 「不存在→False」重发判定另受 onebot._ONEBOT_GET_MSG_NOT_FOUND_PROVEN
        # 真机取证锁，取证前本确认器只会 True/None（保持 UNKNOWN，绝不盲发）。
        unknown_part_confirmer = None
        if getattr(config, "bot_outbound_verify_enabled", False):
            from .domains.transport.sender.onebot import build_unknown_part_confirmer

            unknown_part_confirmer = build_unknown_part_confirmer(
                lambda send_request: _select_queue_bot(bot_provider, send_request)
            )

        await drain_send_queue_once(
            send_queue,
            transport,
            receipt_repository=receipt_repository,
            audit_logger=audit_logger,
            limit=batch_size,
            operational_notifier=operational_notifier,
            unknown_part_confirmer=unknown_part_confirmer,
        )

    scheduler.add_job(
        _queue_worker_job,
        "interval",
        seconds=interval_seconds,
        id="bot_send_queue_worker",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
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


def _register_network_patrol_scheduler(
    *,
    scheduler: Any,
    config: Config,
    audit_logger: AuditRepository,
    pipeline: Any,
    bot_provider: Any,
    receipt_repository: ReceiptRepository | None,
    send_queue: Any,
) -> dict[str, object]:
    """网络巡检（2026-09-30 代理链事故波，W1-③ + Clash 探针）：Clash 7890
    存活 + 上游域「直连/经代理」双路低频探活。

    - 状态差分只在「变坏/恢复」边界发声（首轮只建基线，防启动即风暴）；
      变坏侧带连续失败去抖（``DownDebounce``，2026-10-02 澜汐裁定
      「连续五次炸了才提醒」）：同一目标连续失败达阈值才报 down，中途
      成功清零；恢复只对**曾被报过 down** 的目标发，未达阈值的 blip 两侧不出声；
    - 变坏走**带外告警**（send_admin_alert_requests → TG/邮件，不经 LLM
      链——告警系统不和病人共用一条血管）；恢复只记审计账不刷屏；
    - 一轮结果追加 data/network_patrol.jsonl（滚动 .1），供事后画时间线；
    - 探针全部 fail-open：巡检自身异常绝不拖累主链。
    """
    from .domains.ops.network_patrol import (
        PATROL_TARGETS_DEFAULT,
        DownDebounce,
        append_patrol_jsonl,
        format_alert_lines,
        run_patrol,
        state_delta,
    )

    if not bool(getattr(config, "bot_network_patrol_enabled", True)):
        return {"registered": False, "reason": "disabled"}
    interval_minutes = max(
        1, int(getattr(config, "bot_network_patrol_interval_minutes", 15))
    )
    # 连续失败去抖阈值（2026-10-02 澜汐裁定「连续五次炸了才提醒」）：装配期
    # 读快照冻结进闭包，与本族其余三键同口径（RESTART_REQUIRED_KEYS 在册）。
    down_threshold = max(
        1, int(getattr(config, "bot_network_patrol_down_threshold", 5))
    )
    raw_domains = str(getattr(config, "bot_network_patrol_domains", "") or "").strip()
    targets = (
        [part.strip() for part in raw_domains.replace(";", ",").split(",") if part.strip()]
        if raw_domains
        else list(PATROL_TARGETS_DEFAULT)
    )
    proxy_url = (
        str(getattr(config, "bot_download_proxy", "") or "").strip()
        or "http://127.0.0.1:7890"
    )
    jsonl_path = (
        Path(str(getattr(config, "bot_runtime_data_dir", "data") or "data"))
        / "network_patrol.jsonl"
    )
    # 差分基线挂在闭包上（本任务单实例 max_instances=1，无并发串号面）；
    # 2026-10-02 去抖：基线比对的是 DownDebounce 的告警稳态，不是原始观测。
    debounce = DownDebounce(threshold=down_threshold)
    state_holder: dict[str, object] = {"last": None}

    async def _patrol_job() -> None:
        try:
            # 同步探针族（每域两跳 HTTPS，最坏 targets×2×timeout 秒）必须
            # 下放线程，否则巡检期间事件循环冻结（凭据检查同款判据）。
            report = await asyncio.to_thread(
                run_patrol, targets=targets, clash_proxy=proxy_url
            )
        except Exception as exc:  # noqa: BLE001 - 巡检自身故障不影响主链。
            audit_logger.append(
                AuditRecord(
                    request_id="bot_network_patrol",
                    session_id="runtime",
                    capability_id="bot.network_patrol",
                    stage="scheduler",
                    event="network_patrol_error",
                    severity=RiskLevel.LOW,
                    public_message="网络巡检执行失败。",
                    private_debug=repr(exc),
                )
            )
            return
        append_patrol_jsonl(jsonl_path, report)
        current = report.state()
        # 告警差分吃「去抖稳态」（连续失败达阈值才算 down）；审计账与 JSONL
        # 照旧记原始观测，事后复盘不因去抖失真。
        alerted = debounce.debounced_state(current)
        delta = state_delta(state_holder.get("last"), alerted)  # type: ignore[arg-type]
        state_holder["last"] = alerted
        if not delta:
            return
        # 分型细节（2026-10-02 裁定 b）：告警行按最近一次观测的探针异常归因
        # （refused 族＝本机 Clash 不在家；EOF/SSL 族＝节点抖动；直连腿＝上游问题）。
        leg_details = {f"{leg.target}:{leg.path}": leg.detail for leg in report.legs}
        lines = format_alert_lines(delta, leg_details)
        got_worse = any(not ok for _, ok in delta)
        audit_logger.append(
            AuditRecord(
                request_id="bot_network_patrol",
                session_id="runtime",
                capability_id="bot.network_patrol",
                stage="scheduler",
                event="network_patrol_state_change",
                severity=RiskLevel.MEDIUM if got_worse else RiskLevel.LOW,
                public_message="；".join(lines)[:300],
                private_debug=" ".join(
                    f"{key}={'ok' if ok else 'DOWN'}" for key, ok in current.items()
                )[:400],
            )
        )
        if not got_worse:
            return
        alert = AlertContent(
            title="网络巡检：出站路径变化",
            what_happened="；".join(lines)[:500],
            impact="对应出站腿上的能力（LLM 渠道/订阅/图源等）会失败或走不通。",
            fix_suggestion=(
                "先看 127.0.0.1:7890 是否活着（Clash Party 进程），"
                "再看该域直连是否可达；分流矩阵见 patches/W2-PROXY-ABC-OPS-20260930.md。"
            ),
            location="bot.network_patrol 定时任务",
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
        _patrol_job,
        "interval",
        minutes=interval_minutes,
        id="bot_network_patrol",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return {
        "registered": True,
        "reason": "registered",
        "interval_minutes": interval_minutes,
        "down_threshold": down_threshold,
        "targets": targets,
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
    from .domains.subscribe.capabilities.today_history import (
        _load_push_table,
        build_today_history_capability,
    )
    from .domains.subscribe.feeds.today_history import TodayHistoryProvider

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
            plain_text="历史上的今天", command_text="历史上的今天",  # 自造文本⇒两值同
            raw_segments=[{"type": "text", "data": {"text": "历史上的今天"}}],
            mentions_bot=False,
        )
        from .domains.chat_reply.runtime.pipeline import offload_capability

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

            from .domains.location.knowledge.kb_wiki import (
                _get_shared_store,
                run_kb_sync_task,
            )

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
        except asyncio.CancelledError:
            # 停机竞态兜底（R2b 备用坐标落地）：bot.py 早停钩子已先于插件
            # 钩子 cancel job；若取消落在线程体内，这里安静优雅退出，
            # 绝不向停机日志刷 CancelledError 栈（CancelledError 不被下方
            # except Exception 捕获，缺这层会逃到 apscheduler 执行器刷屏）。
            return
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


# ---- 最近图片上下文（vis3 2026-09-13 用户指令 · MM-VIS-1 2026-09-29 扩到私聊）----
# 实战：群里别人刚发图，另一用户 @bot "总结一下"——vision 只看提问者自带图，
# 读不到图。环形缓存按**会话**记最近 5 分钟的 http 图片（最多 5 张），chat 在
# 「无自带图 + 文本带看图意图」时注入最新一张（标注"取自群里最近图片"）。
#
# 为什么键从群号换成 `session_id`（缺陷 3）：私聊同样有"先发一张图、隔几秒再补一句
# 问话"的连发形状，而私聊此前**完全没有兜底**——环只按 group_id 建，私聊消息
# `group_id is None`，登记与注入两条腿都不进。`session_id` 对群是 `group:<id>`、
# 对私聊是 `private:<id>`（摄取处 `event.get_session_id()`），两型都有 ⇒ 一个键位
# 同时罩住两条腿，且不新增第二本账。⚠ 段类型仍只认 `image`（与 vis3 逐字节同判据）：
# 扩类型会顺手改动群聊侧既有行为，不属本席授权面，登记为边界不静默放宽。
_RECENT_IMAGES_BY_SESSION: dict[str, deque[tuple[float, str]]] = {}
_RECENT_IMAGE_TTL_SECONDS = 300.0
_RECENT_IMAGE_MAX = 5
_VISION_HINT_RE = re.compile(
    r"总结|概括|识别|看看|看一下|这图|什么图|分析|读懂|描述|梳理|讲了什么|说了什么"
)


def _remember_session_images(session_id: str, segments: list[dict[str, Any]]) -> None:
    """摄取侧登记：本会话消息里的 http 图片进环形缓存（进程内，重启即清）。"""
    key = str(session_id or "").strip()
    if not key:
        return
    now = time.monotonic()
    bucket = _RECENT_IMAGES_BY_SESSION.setdefault(
        key, deque(maxlen=_RECENT_IMAGE_MAX)
    )
    for segment in segments:
        if str(segment.get("type", "")).strip().lower() != "image":
            continue
        url = str((segment.get("data") or {}).get("url") or "")
        if url.startswith("http"):
            bucket.append((now, url))


def _latest_fresh_session_image(session_id: str, now: float) -> str:
    """取本会话 TTL 内最新一张 http 图片；过期条目（最旧端）顺手清理。"""
    bucket = _RECENT_IMAGES_BY_SESSION.get(str(session_id or "").strip())
    if not bucket:
        return ""
    while bucket and now - bucket[0][0] > _RECENT_IMAGE_TTL_SECONDS:
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
    from .domains.render.bot_avatar import refresh_from_qq

    data_dir = str(getattr(config, "bot_runtime_data_dir", "data") or "data")
    root = Path(data_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / data_dir
    return refresh_from_qq(bot_id, root)


async def _resolve_bot_avatar_url(bot: Any, config: Config) -> str:
    """Resolve the bot avatar: configured URL > local cached file > remote.

    F3（2026-09-14 素材本地化）：本地头像文件存在即直接用 file URI（经
    output.bot_avatar.bot_avatar_uri 统一入口，含内存登记与磁盘兜底发现），
    不再进入协议端 RPC / qlogo 远端链——消灭 600s TTL 周期性 Chromium
    回源。本地缺失才走既有远端链，其语义原样保留（RPC/qlogo 回退、600s
    缓存、最终空串由卡片回落「守」字圆点）。
    """
    configured = str(getattr(config, "bot_persona_avatar_url", "") or "").strip()
    if configured:
        return configured
    from .domains.render.bot_avatar import bot_avatar_uri

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
    from .domains.link_parse.parsers import (
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
    if receipt.state is ReceiptState.QUEUED:
        # 2026-09-24 语音双发根修波：queue.submit 的受理回执 public_message
        # ="queued" 是内部哨兵串——inline 首投失败回落到本判定曾被直通上屏
        # （QQ 实录「queued」）。受理≠投递结果，一律不回会话。
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
    if issue is None and receipt.state.value == "failed_final":
        # 出站终态失败的告警出口（2026-09-29 需求项 2 之 4）：max_attempts 烧尽后
        # 置 FAILED_FINAL 的那几条以前**不带 issue**，而 worker 的告警闸
        # （`worker._notify_operational_issue_safely`）第一行就是「无 issue 直接返回」
        # ⇒ 一条消息出了终态就凭空消失，管理员侧零痕迹（现网日志实证：本窗口
        # failed_final 3 条、blocked 群轮 2688 条，全部无痕）。
        # 这里只补一枚**分类未定**的 OperationalIssue（retry_safety 缺省 ""＝未分类
        # ⇒ 重投语义与新增该字段前逐字节一致，见 contracts/runtime.py 的字段注），
        # 告警本身沿用既有链条：queue.mark_final_failure → worker → operational_notifier
        # → runtime/alerts 的抑制窗与出卡，不新造机制、不新增第二条静默闸。
        # kind 是逐字承重串：`alerts._KIND_PLAIN` 与 `error_report` 两面还没登记它，
        # 缺登记时告警走既有兜底句（"原因我不猜，请按代号补登记"），已列为交别席项。
        issue = OperationalIssue(
            stage="transport",
            kind="send_failed_final",
            retryable=False,
            severity=RiskLevel.MEDIUM,
            safe_summary=(
                f"capability={send_request.capability_id} transport={receipt.transport} "
                f"state=failed_final"
            ),
        )
        receipt = receipt.model_copy(update={"operational_issue": issue})
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
                # 2026-09-24 语音双发根修：mixed「结果未知」类失败先按 worker
                # 同一分类做 part 级 UNKNOWN + PARTIAL 断点记账（超时≠未送达，
                # 留行 failed_retryable 会让 worker 盲重投整条语音）；非该形态
                # （明确拒绝/挂起/非 mixed/无 part 面队列）返回 False 走旧语义。
                # 函数体内 import：顶置 import 会顶漂下方被门钉住的 live 坐标
                # （#45/U17 同型教训）。
                from .domains.transport.sender.worker import (
                    book_inline_unknown_parts,
                )

                if not book_inline_unknown_parts(send_queue, send_request, issue):
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
    from .domains.transport.sender.gateway import UnifiedDeliveryGateway
    from .domains.transport.sender.nonebot import send_nonebot_message

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
    message: Any | None = None,
    receipt_repository: ReceiptRepository | None = None,
    record_diagnostic: bool = True,
    history_recorder: Any | None = None,
    history_kind: str = "command",
    operational_notifier: Any | None = None,
) -> DeliveryReceipt:
    # 第二通路收编（S-SEAM-ROOT）：调用方已在 handler 侧用 feature_enabled 快照构造好
    # message 时经 message= 交来；缺省 None 时下方摄取路径与既有缝点逐字节同路。
    if message is None:
        from .domains.chat_reply.runtime.ingress import IngressGateway
        message = IngressGateway(_incoming_from_nonebot_event).from_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
        )
    # 层 2 主缝的唯一汇合点（R-PREP C-1 根修）：此前只有 `_run_simple_capability` 那条
    # 命令入口包了缝，而**别名**与**自然语言**两条入口把闭包直接交给本函数 ⇒ 同一个能力
    # 三条入口里两条不经中央治理，缺口账却按"声明即通电"记它 WIRED＝账在撒谎。
    # 在这里包一次 ⇒ 三条入口同权；未在册能力 `orchestrated_command` 原样直呼，行为不变。
    from .runtime.capability_protocols import orchestrated_command as _orchestrated

    if getattr(capability, "orchestrated_capability_id", None) is None:
        capability = _orchestrated(capability_id, capability, config)
    # 下放决定不在根汇口做（X4 续批）：一律交 `handle_async`，由它内部的
    # `ensure_offloaded` 按「正文是不是协程」这一把尺决定留循环还是进池。
    # 过去的形状是按 `OFFLOADED_CAPABILITY_IDS` 二选一，名单外的一枚同步命令走
    # `pipeline.handle` ⇒ 正文与完成腿都在事件循环线程上跑完，冻住的是整片会话
    # 而不是那一条命令（`/bot recent`·`queue`·`logs`·`runtime`·`setup llm` 全在
    # 名单外）。`pipeline.handle` 从此只服务「本来就在线程里/没有循环」的调用方
    # （console、smoke、脚本、离线测试）。判据锁
    # `tests/test_pipeline_offload_always.py`。
    receipt = await pipeline.handle_async(
        message, capability, capability_id=capability_id
    )
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
    from .domains.chat_reply.character.affinity import DynamicAffinityStore
    from .domains.chat_reply.character.providers import build_runtime_data_path

    if not getattr(config, "bot_affinity_enabled", True):
        return None
    db_path = build_runtime_data_path(
        config, str(getattr(config, "bot_affinity_db_path", "data/user_affinity.sqlite3"))
    )
    cache_key = str(db_path)
    with _AFFINITY_STORES_LOCK:
        store = _AFFINITY_STORES.get(cache_key)
        if store is None:
            # config 句柄传入＝12 枚 v7 键逐调用现读（消装配期快照：她改 .env 重启即生效，
            # 不必等下一轮重建单例；S-MEMAFF 2026-09-28 hub 申请 C 项）。
            store = DynamicAffinityStore(db_path, config=config)
            _AFFINITY_STORES[cache_key] = store
        return store


# 进程级共享 bot 心情 store（L1）：与好感度 store 同模式（构造即建连接+建表，
# 复用单例消除热路径重复 schema ensure；store 自身带锁线程安全）。
_MOOD_STORES: dict[str, Any] = {}
_MOOD_STORES_LOCK = threading.Lock()


def build_character_mood_store(config: object):
    from .domains.chat_reply.character.mood import BotMoodStore
    from .domains.chat_reply.character.providers import build_runtime_data_path

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
    from .domains.chat_reply.character.providers import build_runtime_data_path
    from .domains.chat_reply.character.quirks import QuirkStore

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

    # G-07：透传 sender——user scope 怪癖只渲染给本人；无 sender 只给 global。
    def _describe(sender_id: str | None = None) -> str:
        return store.render_prompt_section(max_active=max_active, sender_id=sender_id)

    return _describe


# 进程级共享会话身份 store（管理员设置的每群/每私聊称呼与标签）。
_IDENTITY_STORES: dict[str, Any] = {}
_IDENTITY_STORES_LOCK = threading.Lock()


def build_session_identity_store(config: object):
    from .domains.chat_reply.character.providers import build_runtime_data_path
    from .domains.chat_reply.character.session_identity import SessionIdentityStore

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

            from .domains.chat_reply.character.reflection import run_nightly_reflection

            summarizer = None
            if bool(getattr(config, "bot_reflection_llm_enabled", False)):
                from .domains.chat_reply.character.reflection import LLMSummarizer

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


def _push_via_central_exit_now(
    send_queue: Any,
    request: Any,
    outbound_gate: Any,
    *,
    dedupe_family: str = "once",
    dedupe_namespace: str,
) -> bool:
    """主动投递的唯一出口调用口，并回答「本轮是否还可以就地投出去」。

    投递动作本身交 `submit_active_push`（闸关闭态=与裸 ``submit(request)`` 逐字节
    同形的 passthrough，零 store 零审计）。返回值只服务**内联投递**这一条历史通路：

    - ``True``  放行且不顺延 ⇒ 照旧就地投递并据回执销账（现网闸关态恒走这条，行为零变更）；
    - ``False`` 闸拦下（静默窗/限流/键形）或判了顺延 ⇒ 本轮既不内联投也不销账，
      下一 tick 由投前 `receipt_repository.latest()` 与队列幂等键收敛，绝不双发。

    存在的理由：提醒/cookie 到期两族的"送达才销账"读的是内联投递的同步回执，
    不能直接照抄摘要/助理那种纯队列投；闸的判定因此必须在这两处也站在投递之前。

    `dedupe_namespace` **强制申报**（无缺省值）：闸的键规范按首段等值认族，漏报即
    回落紧急域 `emg` 口径 ⇒ 开闸态该族整链静默丢消息（R-CENTRAL C-1 的成因）。
    """
    from .domains.transport.sender.outbound_gate import submit_active_push

    outcome = submit_active_push(
        send_queue,
        request,
        outbound_gate,
        dedupe_family=dedupe_family,
        dedupe_namespace=dedupe_namespace,
    )
    return outcome.verdict.action == "allow" and outcome.verdict.deliver_after is None


async def _deliver_due_reminders(
    config: Any,
    send_queue: Any,
    audit_logger: Any = None,
    receipt_repository: Any = None,
    all_online_bots: Any = None,
    *,
    outbound_gate: Any,
) -> int:
    """到点提醒一次性投递：经中央出口投出去后**内联投递**，送达才销账。返回送达数。

    默认配置是内存发送队列——``InMemorySendQueue.submit`` 只入列并回假
    sent 回执、没有任何网络调用（sender/queue.py），只 submit 不投递等于
    提醒永不送达（2026-09-14 审查 A-01）。这里与订阅推送同范式就地投递；
    失败不销账留待下一轮重投，重投前先查回执仓——SQLite 队列的 worker
    在 60s 内联宽限期后可能已送出，此时直接销账不再重发（防双发）；
    长期投不出由 store 的顺延/作废策略兜底。
    """
    from .contracts import (
        PrivacyLevel,
        RenderedOutput,
        SendPolicy,
        SendRequest,
        SessionType,
    )
    from .domains.schedule.store.reminders import (
        build_reminder_store,
        build_reminder_text,
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
        if not _push_via_central_exit_now(
            send_queue,
            request,
            outbound_gate,
            dedupe_family="once",
            dedupe_namespace="reminder",
        ):
            from nonebot.log import logger

            logger.warning(
                "reminder {} held by central outbound gate; kept for retry",
                request_id,
            )
            continue
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


async def _deliver_cookie_expiry_report_via_queue(
    config: Any,
    send_queue: Any,
    audit_logger: Any,
    receipt_repository: Any,
    bot: Any,
    report: str,
    admins: list[str],
    deliver_fn: Any = None,
    *,
    outbound_gate: Any,
) -> bool:
    """cookie 到期提醒统一路径投递（S0 收编①，v21r4-b2-direct-collect-plan §3.1）。

    形态 B=``_deliver_due_reminders`` 提醒范式：SendRequest→``send_queue.submit``
    →``_find_sent_request``→内联 deliver（默认 ``_deliver_transport_send_request``），
    SENT/REDIRECTED 才算送达；首个管理员未送达才换下一个（与旧直连
    break/continue 等价）。dedupe_key/request_id 带本地日期=当日幂等：回执仓
    已有当日 SENT/REDIRECTED 回执时直接视为已送达（治同日重复触发的重复
    打扰面）。全部失败静默返回 False，绝不抛出影响主链路。
    """
    from datetime import datetime as _datetime

    from .contracts import (
        PrivacyLevel,
        RenderedOutput,
        SendPolicy,
        SendRequest,
        SessionType,
    )

    deliver = deliver_fn if deliver_fn is not None else _deliver_transport_send_request
    today = _datetime.now().astimezone().date().isoformat()
    adapter = _bot_adapter_name(bot)
    bot_id = str(getattr(bot, "self_id", "") or "")
    persona_profile_id = str(getattr(config, "bot_persona_profile_id", "default"))
    cleaned = [str(item).strip() for item in admins if str(item).strip()]
    for admin_id in cleaned[:3]:
        request_id = f"cookie-expiry-{admin_id}-{today}"
        if receipt_repository is not None:
            try:
                prior = receipt_repository.latest(request_id)
            except Exception:  # noqa: BLE001 - 回执查询失败按无回执处理。
                prior = None
            if prior is not None and getattr(prior, "state", None) in {
                ReceiptState.SENT,
                ReceiptState.REDIRECTED,
            }:
                return True
        request = SendRequest(
            request_id=request_id,
            session_id=f"private:{admin_id}",
            target_scope=SessionType.PRIVATE,
            target_id=str(int(admin_id)),
            capability_id="bot.cookie_expiry_notice",
            content=RenderedOutput(
                request_id=request_id,
                content_type="text",
                content_ref={},
                text_fallback=report,
                privacy_level=PrivacyLevel.PERSONAL,
            ),
            send_policy=SendPolicy.QUEUED,
            priority="normal",
            max_messages=1,
            dedupe_key=f"cookie-expiry:{admin_id}:{today}",
            cooldown_key=f"cookie-expiry:{admin_id}",
            privacy_level=PrivacyLevel.PERSONAL,
            persona_profile_id=persona_profile_id,
            adapter=adapter,
            bot_id=bot_id,
            audit_tags=["cookie_expiry", "daily_notice"],
        )
        try:
            allowed_now = _push_via_central_exit_now(
                send_queue,
                request,
                outbound_gate,
                dedupe_family="daily",
                dedupe_namespace="cookie-expiry",
            )
        except Exception:  # 入列失败换下一个管理员。
            logging.getLogger(__name__).debug(
                "cookie expiry notice submit failed for %s", admin_id, exc_info=True
            )
            continue
        if not allowed_now:
            logging.getLogger(__name__).warning(
                "cookie expiry notice to %s held by central outbound gate", admin_id
            )
            continue
        sent_request = _find_sent_request(send_queue, request_id) or request
        try:
            receipt = deliver(
                bot, None, sent_request, audit_logger, receipt_repository, send_queue
            )
            if inspect.isawaitable(receipt):
                receipt = await receipt
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 单管理员投递失败换下一个。
            receipt = None
        if receipt is not None and getattr(receipt, "state", None) in {
            ReceiptState.SENT,
            ReceiptState.REDIRECTED,
        }:
            return True
        logging.getLogger(__name__).debug(
            "cookie expiry notice to %s not delivered via queue", admin_id
        )
    return False


def _register_reminder_scheduler(
    scheduler: Any,
    config: Any,
    send_queue: Any,
    audit_logger: Any | None = None,
    receipt_repository: Any | None = None,
    all_online_bots: Any | None = None,
    *,
    outbound_gate: Any,
) -> dict:
    """提醒投递：每分钟检查到点提醒，经中央出口投出去后**内联投递**、送达才销账。

    到点文案由 character/reminders.build_reminder_text 提供（守岸人语气）；
    投递失败只记日志、不销账、下一轮重投，绝不阻塞主链路；闸拦下/顺延同样不销账。
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
                outbound_gate=outbound_gate,
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

    async def _file_sweep_job() -> None:
        """落盘点寿命清扫（需求16 收口）：只扫 incoming/ 登记根，TTL 走装配现算口。

        bot_files_incoming_ttl_days ≤0＝关闭（sweep 内对非正 TTL 一件不删）；
        失败只告警不影响主链路（fail-open）；同步删放下线程池。
        """
        try:
            from nonebot.log import logger

            from .domains.files.sender.restricted_runner import (
                sweep_expired_files,
                sweep_ttl_days_from_config,
            )

            incoming_root = (
                Path(
                    str(
                        getattr(config, "bot_download_dir", "data/downloads")
                        or "data/downloads"
                    )
                )
                / "incoming"
            )
            outcomes = await asyncio.to_thread(
                sweep_expired_files,
                [incoming_root],
                ttl_days=sweep_ttl_days_from_config(config),
            )
            deleted = sum(item.deleted for item in outcomes)
            forbidden = sum(item.skipped_forbidden for item in outcomes)
            logger.info(
                "file sweep done: deleted={} forbidden_skipped={}", deleted, forbidden
            )
        except Exception as exc:  # noqa: BLE001 - 清扫失败不影响主链路。
            logger.warning("file sweep failed: {}", type(exc).__name__)

    scheduler.add_job(
        _file_sweep_job,
        "cron",
        id="bot_file_sweep_tick",
        replace_existing=True,
        hour=4,
        minute=50,
        misfire_grace_time=600,
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
    outbound_gate: Any,
    *,
    now: Any = None,
) -> list[str]:
    """把白名单群当日群摘要逐群投递 send_queue；返回已推送群号。

    推送目标只取群摘要名单 whitelist 模式下的白名单群：list_mode 非
    whitelist 一律不推（绝不猜群）。每群合成 request_id 调 shared_group
    provider 取当日摘要，无可用摘要静默跳过；正文 = 守岸人引子 + 摘要；
    dedupe_key 带当天日期，同群同天不重发。投递**只经中央出口**
    `submit_active_push`（闸关闭态=与裸 submit 逐字节同形的 passthrough）。
    """
    from datetime import datetime

    from .contracts import (
        PrivacyLevel,
        RenderedOutput,
        SendPolicy,
        SendRequest,
        SessionType,
    )
    from .domains.chat_reply.character.shared_group import GroupDigestListFilter

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
        from .domains.transport.sender.outbound_gate import submit_active_push

        submit_active_push(
            send_queue,
            request,
            outbound_gate,
            dedupe_family="daily",
            dedupe_namespace="digest_push",
        )
        pushed.append(group_id)
    return pushed


def _register_digest_push_scheduler(
    scheduler: Any, config: Any, send_queue: Any, outbound_gate: Any
) -> dict:
    """夜间每日群通讯总结主动推送（G-DIGEST 收尾）。

    每日 cron（``bot_group_digest_push_time``，默认 21:30）把群摘要名单
    whitelist 模式下的白名单群当日摘要各推一遍；同步 job 跑在 APScheduler
    线程池（与 reminder/reflection 同款，不阻塞事件循环），失败只记日志。
    """

    def _digest_push_job() -> None:
        try:
            from .domains.chat_reply.character.shared_group import (
                build_shared_group_context_provider,
            )

            _push_daily_group_digests(
                config,
                send_queue,
                outbound_gate,
                build_shared_group_context_provider(
                    config, llm_provider=_build_chat_llm_provider(config)
                ),
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


def _parse_daily_assist_clock(value: Any) -> tuple[int, int] | None:
    """解析 HH:MM；非法返回 None（调用方决定跳过还是回退默认）。"""
    parts = str(value or "").strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def _daily_assist_targets(config: Any) -> list[str]:
    """推送目标只取显式名单；名单为空=只记不推（绝不猜人）。"""
    return [
        str(user).strip()
        for user in (getattr(config, "bot_daily_assist_push_user_ids", None) or [])
        if str(user).strip()
    ]


# 到点吃什么开场池（R6 席草案落地，v21r2-r6-copy-log.md §六）：单句无变体
# → 6 变体确定性轮换，与 character/daily_assist 文案池同构（同 key 游标
# 循环、连发不重复）；文案只动措辞，推送调度/dedupe 行为面零改动。
_MEAL_OPENERS: tuple[str, ...] = (
    "到饭点啦，守岸人替你挑了这个：{name}{suffix}",
    "饭点到了。今天就吃它吧：{name}{suffix}",
    "到点了，守岸人翻了很久，选了这个：{name}{suffix}",
    "开饭啦。今天的答案是：{name}{suffix}",
    "饭点准时到。守岸人把这个端上来：{name}{suffix}",
    "到吃饭的点了，今天轮到它：{name}{suffix}",
)


def _build_meal_push_text(item: str) -> str:
    """到点吃什么推送正文（守岸人语气开场池，一句克制引子，不堆辞藻）。"""
    from .domains.assistant.daily.store.daily_assist import (
        meal_display_name,
        pick_variant,
    )

    name = meal_display_name(item)
    suffix = item[len(name):].strip()
    return pick_variant("meal_open", _MEAL_OPENERS, name=name, suffix=suffix)


def _push_daily_assist_private(
    config: Any,
    send_queue: Any,
    outbound_gate: Any,
    *,
    capability_id: str,
    text: str,
    tag: str,
    now: Any = None,
) -> int:
    """日常助理简报逐个私聊投递 send_queue（纯 submit，SQLite 队列 worker 送达）。

    投递只经中央出口 `submit_active_push`；闸关闭态=与裸 submit 同形的 passthrough。
    """
    from datetime import datetime

    from .contracts import (
        PrivacyLevel,
        RenderedOutput,
        SendPolicy,
        SendRequest,
        SessionType,
    )

    targets = _daily_assist_targets(config)
    moment = now or datetime.now().astimezone()
    today = moment.date().isoformat()
    persona_profile_id = str(
        getattr(config, "bot_persona_profile_id", "default")
    )
    pushed = 0
    for user_id in targets:
        request_id = f"daily-assist-{tag}-{user_id}-{today}"
        request = SendRequest(
            request_id=request_id,
            session_id=f"private:{user_id}",
            target_scope=SessionType.PRIVATE,
            target_id=user_id,
            capability_id=capability_id,
            content=RenderedOutput(
                request_id=request_id,
                content_type="text",
                content_ref={},
                text_fallback=text,
                privacy_level=PrivacyLevel.PERSONAL,
            ),
            send_policy=SendPolicy.QUEUED,
            priority="normal",
            max_messages=1,
            dedupe_key=f"daily_assist:{tag}:{user_id}:{today}",
            cooldown_key=f"daily_assist:{tag}:{user_id}",
            privacy_level=PrivacyLevel.PERSONAL,
            persona_profile_id=persona_profile_id,
            audit_tags=["daily_assist", tag],
        )
        from .domains.transport.sender.outbound_gate import submit_active_push

        submit_active_push(
            send_queue,
            request,
            outbound_gate,
            dedupe_family="daily",
            dedupe_namespace="daily_assist",
        )
        pushed += 1
    return pushed


def _run_daily_assist_meal_push(
    config: Any, send_queue: Any, outbound_gate: Any, slot: str
) -> None:
    from nonebot.log import logger

    try:
        from .domains.assistant.daily.store.daily_assist import choose_meal

        item = choose_meal(config)
        if not item:
            return
        _push_daily_assist_private(
            config,
            send_queue,
            outbound_gate,
            capability_id="bot.daily_assist",
            text=_build_meal_push_text(item),
            tag=f"meal-{slot.replace(':', '')}",
        )
    except Exception as exc:  # noqa: BLE001 - 到点推荐失败不影响主链路。
        logger.warning("daily assist meal push failed: {}", type(exc).__name__)


def _run_daily_assist_morning_push(
    config: Any, send_queue: Any, outbound_gate: Any
) -> None:
    from nonebot.log import logger

    try:
        from plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist import (
            archive_inbox,
            build_morning_brief,
            daily_archive_dir,
            inbox_path,
            read_pending_inbox,
            read_task_sections,
            summarize_with_llm,
            tasks_path,
        )

        pending = read_pending_inbox(inbox_path(config))
        sections = read_task_sections(tasks_path(config))
        summary = ""
        if pending:
            summary = summarize_with_llm(
                config,
                "\n".join(pending),
                instruction=(
                    "以下是收件箱里的随手记。用中文挑出今天值得先办的事，"
                    "一两句话点到为止，不要客套和开场白："
                ),
            )
        text = build_morning_brief(pending, sections, summary)
        if pending:
            archive_inbox(inbox_path(config), daily_archive_dir(config))
        _push_daily_assist_private(
            config,
            send_queue,
            outbound_gate,
            capability_id="bot.daily_assist",
            text=text,
            tag="morning",
        )
    except Exception as exc:  # noqa: BLE001 - 早报失败不影响主链路。
        logger.warning("daily assist morning push failed: {}", type(exc).__name__)


def _run_daily_assist_evening_push(
    config: Any, send_queue: Any, outbound_gate: Any
) -> None:
    from nonebot.log import logger

    try:
        from plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist import (
            build_evening_brief,
            daily_archive_dir,
            load_daily_archive,
            read_task_sections,
            summarize_with_llm,
            tasks_path,
        )

        sections = read_task_sections(tasks_path(config))
        archived = load_daily_archive(daily_archive_dir(config))
        suggestion = ""
        if sections or archived:
            material = "\n".join(
                [
                    *(f"进行中：{item}" for item in sections.get("进行中", [])),
                    *(f"已计划：{item}" for item in sections.get("已计划", [])),
                    *(f"想法池：{item}" for item in sections.get("想法池", [])),
                    *(f"今日收件箱：{item}" for item in archived),
                ]
            )
            suggestion = summarize_with_llm(
                config,
                material,
                instruction=(
                    "根据这份清单，主动想到 1-3 件对方可能忘了办、"
                    "或值得提前安排的事，各一句话，不要空话："
                ),
            )
        text = build_evening_brief(sections, archived, suggestion)
        _push_daily_assist_private(
            config,
            send_queue,
            outbound_gate,
            capability_id="bot.daily_assist",
            text=text,
            tag="evening",
        )
    except Exception as exc:  # noqa: BLE001 - 晚报失败不影响主链路。
        logger.warning("daily assist evening push failed: {}", type(exc).__name__)


def _register_daily_assist_scheduler(
    scheduler: Any, config: Any, send_queue: Any, outbound_gate: Any
) -> dict:
    """日常助理定时推送：到点吃什么推荐 + 收件箱早晚简报。

    推送目标名单为空时整体不注册（只记不推，绝不猜人）。同步 job 跑在
    APScheduler 线程池（与 reminder/reflection 同款，不阻塞事件循环），
    失败只记日志；cron 时刻为装配期快照（与 G-DIGEST 同款已知取舍）。
    """
    if not _daily_assist_targets(config):
        return {"skipped": "no_targets"}
    registered: dict[str, Any] = {"meals": []}
    for raw in getattr(config, "bot_daily_assist_meal_times", None) or []:
        clock = _parse_daily_assist_clock(raw)
        if clock is None:
            continue
        hour, minute = clock
        slot = f"{hour:02d}:{minute:02d}"

        def _meal_job(
            _config: Any = config,
            _queue: Any = send_queue,
            _gate: Any = outbound_gate,
            _slot: str = slot,
        ) -> None:
            _run_daily_assist_meal_push(_config, _queue, _gate, _slot)

        scheduler.add_job(
            _meal_job,
            "cron",
            id=f"bot_daily_assist_meal_{hour:02d}{minute:02d}",
            replace_existing=True,
            hour=hour,
            minute=minute,
            misfire_grace_time=3600,
            max_instances=1,
            coalesce=True,
        )
        registered["meals"].append(slot)

    morning = _parse_daily_assist_clock(
        getattr(config, "bot_daily_assist_morning_time", "09:00")
    ) or (9, 0)

    def _morning_job(
        _config: Any = config, _queue: Any = send_queue, _gate: Any = outbound_gate
    ) -> None:
        _run_daily_assist_morning_push(_config, _queue, _gate)

    scheduler.add_job(
        _morning_job,
        "cron",
        id="bot_daily_assist_morning",
        replace_existing=True,
        hour=morning[0],
        minute=morning[1],
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )
    evening = _parse_daily_assist_clock(
        getattr(config, "bot_daily_assist_evening_time", "21:00")
    ) or (21, 0)

    def _evening_job(
        _config: Any = config, _queue: Any = send_queue, _gate: Any = outbound_gate
    ) -> None:
        _run_daily_assist_evening_push(_config, _queue, _gate)

    scheduler.add_job(
        _evening_job,
        "cron",
        id="bot_daily_assist_evening",
        replace_existing=True,
        hour=evening[0],
        minute=evening[1],
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )
    registered["morning"] = list(morning)
    registered["evening"] = list(evening)
    return registered


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

    from .domains.chat_reply.capabilities.chat import build_chat_capability
    from .domains.chat_reply.capabilities.echo import (
        build_status_result,
        resolve_help_query,
    )
    from .domains.chat_reply.capabilities.memory import (
        is_memory_command_text,
        route_memory_command,
    )
    from .domains.chat_reply.character.history import (
        build_conversation_history_provider,
    )
    from .domains.chat_reply.character.providers import build_character_context_provider
    from .domains.chat_reply.runtime.pipeline import (
        RuntimeControlState,
        RuntimePipeline,
        offload_capability,
    )
    from .domains.ops.admin.debug import (
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
    from .domains.ops.admin.runtime_admin import (
        build_alert_check_result,
        build_quirk_admin_result,
        build_runtime_admin_result,
        build_session_identity_admin_result,
    )
    from .domains.ops.admin.runtime_logs import build_logs_query_result
    from .domains.schedule.auto_send import build_auto_send_preview_result
    from .domains.transport.mail.mail_bridge import (
        MailBridgeState,
        build_mail_notification,
        execute_mail_command,
        is_telegram_admin,
        mail_event_dedupe_id,
        notify_telegram_admins,
        parse_mail_command,
        unresolved_mail_aliases,
    )
    from .domains.transport.sender import build_send_queue
    from .policy import (
        build_quiet_hours_checker,
        build_quiet_hours_settings,
        build_rate_limit_settings,
        build_rate_limiter,
        build_redrive_settings,
        build_reply_budget_settings,
        build_role_settings,
    )

    try:
        driver_config = get_driver().config.model_dump()
    except ValueError as exc:
        if "not been initialized" not in str(exc):
            raise
        return

    # R3 停摆批（INT 席代挂，坐标见 docs/design/v21r2-r3-stall-log.md §三）：
    # 事件循环看门狗（loop 心跳滞后 + 聊天管线池饱和，只观测不自愈）。必须
    # 在 on_startup（running loop 存在后）启动——装配在 import 期执行，彼时
    # 无 loop；任何失败仅降级观测，不阻塞启动（fail-open）。
    try:
        from .domains.ops.monitor.loop_watchdog import start_loop_watchdog

        @get_driver().on_startup
        async def _start_loop_watchdog_on_startup() -> None:
            try:
                start_loop_watchdog()
            except Exception:  # 观测件失败不阻塞启动（fail-open）。
                logging.getLogger(__name__).warning(
                    "loop-watchdog: 启动失败，停摆观测降级停用（不影响消息链路）",
                    exc_info=True,
                )
    except Exception:  # 挂接失败同样不阻塞装配。
        logging.getLogger(__name__).warning(
            "loop-watchdog: on_startup 挂接失败，停摆观测降级停用", exc_info=True
        )

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
    # 校园自动转发（campus v1）：学校账号群消息监听 → 主人私聊实时转发。
    # 三重门任一为空则不装配（绝不猜账号/猜群/猜目标）；装配后 matcher
    # 只落库与转发，绝不向学校群发送任何消息。
    campus_service = None
    campus_source = build_campus_source(config)
    if (
        campus_source.enabled
        and campus_source.self_ids
        and campus_source.whitelist
        and campus_source.notify_qq
    ):
        from .domains.assistant.campus.campus import CampusForwardService
        from .domains.assistant.campus.campus_store import CampusStore

        campus_service = CampusForwardService(
            store=CampusStore(str(config.bot_campus_db_path)),
            source=campus_source,
        )
    # 发送层硬超时：每次发送时读 runtime 覆盖（mtime 热重载），未覆盖时回落 .env 配置。
    set_transport_timeout_provider(
        lambda: float(runtime_settings.get("BOT_TRANSPORT_TIMEOUT_SECONDS", config) or 15.0)
    )
    # 语音下载代理（B-12）：同模式注入 getter，sender 层优先读运行时/插件
    # Config，取不到再退回 driver config/env 探测链。
    from .domains.transport.sender.nonebot import set_download_proxy_provider

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
    # 审查 A-02：默认内存队列零持久化+零网络投递（重启丢在途消息；提醒等
    # submit 型链路靠内联投递兜底）。启动即如实告警一次，把「可靠投递」的
    # 开关位置告诉管理员，而不是让丢消息无声发生。
    from .domains.transport.sender.queue import InMemorySendQueue

    if isinstance(send_queue, InMemorySendQueue):
        logging.getLogger(__name__).warning(
            "发送队列当前为内存版（BOT_SEND_QUEUE_ENABLED 未开启）：进程重启将丢失在途消息；"
            "如需可靠投递与断点续发，请在 .env 设 BOT_SEND_QUEUE_ENABLED=true 后重启。"
        )
    # 中央出站闸**单实例**，装配位置提到发送队列之后（原在紧急信息块内 :5157）。
    # 提前的理由：主动投递的 A 类站点（群摘要 / 日常助理 / 提醒 / cookie 到期）
    # 全部注册在本行之下、紧急块之上，闸留在 5157 就让这些站点无闸可用——
    # 「所有内容走中央出口」在根装配里必须是先有出口、再有消费者。
    # 形参名以真身 domains/transport/sender/outbound_gate.py 的 build_outbound_gate 为准
    # （settings_provider / quiet_settings_provider / audit_logger / clock / store / issue_sink）。
    from .domains.transport.sender.outbound_gate import (
        build_outbound_gate,
        build_outbound_gate_settings,
    )

    outbound_gate = build_outbound_gate(
        config,
        audit_logger=audit_logger,
        # 两路设置都以 callable 注入 ⇒ /bot runtime set 热改即时反映（静默面/限流同例），
        # 不在装配期快照（台账 #3 那类「热改当夜不生效」的坑不再复制一遍）。
        settings_provider=lambda: build_outbound_gate_settings(
            _config_with_runtime_overrides(config, runtime_settings)
        ),
        quiet_settings_provider=lambda: build_quiet_hours_settings(
            _config_with_runtime_overrides(config, runtime_settings)
        ),
        # QG9①（S-ATK-QUEUE Q-G9）：闸的 skip / 设置不可读 / 降级 / 风暴 / TTL 到期
        # 五类 issue 此前只落审计与日志——`note_issue` 在 sink=None 时直接返回，
        # 于是「闸把消息吃掉了」在管理员面完全静默。共用中央告警口，不另造直发腿。
        issue_sink=lambda issue: _push_probe_issue(
            issue, source_bot="outbound-gate", capability_id="bot.outbound_gate"
        ),
    )
    # 中央执行面审计 sink（D-d/D-e 根修）：invoker 每次终态都 emit，但全树此前
    # **零注册** ⇒ 走中央的能力在生产"跑了不留痕"。经壳侧唯一口子挂载，
    # 不在根里再取一次 default_invoker()（那会造第二 invoker 点位，结构门执法）。
    from .runtime.capability_protocols import attach_default_audit_sink

    def _record_capability_audit(record: Any) -> None:
        try:
            audit_logger.append(
                AuditRecord(
                    request_id=record.request_id,
                    session_id=record.session_key,
                    capability_id=record.capability_id,
                    stage="capability_invoke",
                    event=f"invoke_{record.status.value}",
                    severity=(
                        RiskLevel.LOW
                        if record.status.value in {"ok", "fallback_ok"}
                        else RiskLevel.MEDIUM
                    ),
                    public_message="",
                    private_debug=(
                        f"principal={record.principal} via={record.via}"
                        f" elapsed_ms={record.elapsed_ms} detail={record.detail[:200]}"
                    ),
                )
            )
        except Exception:  # 审计失败绝不影响能力执行（与闸侧同口径）。
            logging.getLogger(__name__).debug(
                "capability audit sink failed", exc_info=True
            )

    attach_default_audit_sink(_record_capability_audit)
    diagnostics_store = build_diagnostics_store(config)
    mail_bridge_state = MailBridgeState(config.bot_mail_bridge_state_file)
    runtime_control = RuntimeControlState()
    from .control_plane.factory import build_feature_service
    from .domains.ops.features.feature_gate import ProductFeatureGate
    from .runtime.capability_protocols import attach_default_feature_gate

    feature_service = build_feature_service(config)
    product_feature_gate = ProductFeatureGate(feature_service)
    # 层 2 kill-switch 收编（在册未执法）：门此前只在 pipeline._prepare 执法，绕过
    # pipeline 直呼 default_invoker().invoke() 的入口能静默穿过这道关。只注入谓词、
    # 不在层 2 重抄受门名单（唯一答案仍是 gate_feature_bindings）。
    attach_default_feature_gate(product_feature_gate.check_capability)
    # 语音出站路径双态（G-3 · M-10/M-13 根修）：键开=构建 post-review enricher
    # 交给 pipeline（取文口径=review 批准后的 body；合成失败挂 OperationalIssue
    # 走中央告警链）；键关=None 且对话能力仍走下方旧 _attach_voice_reply 包装
    # （逐字节现状）。惰性导入：键关部署永不触新符号。双态互斥由
    # tests/test_voice_hook_assembly.py 结构锁把守。
    pipeline_voice_enricher = None
    if bool(getattr(config, "bot_tts_voice_hook_enabled", False)):
        from .domains.media.voice_enricher import build_voice_enricher

        pipeline_voice_enricher = build_voice_enricher(config)
    # 慢回复先回执（ack-first，2026-09-23 用户裁定选项 C）：真回复照跑照送，只是超过
    # 阈值仍未出结果时先补一句守岸人口吻的等待短句。键关 ⇒ 两个入参都为 None，
    # pipeline 走的分支与旧代码逐字节同形（零行为变更），故键关部署永不触新符号。
    # 投递只经中央唯一出口 `submit_active_push`（闸关闭态=与裸 submit 同形的
    # passthrough），命名空间申报为 "ack"——漏报会回落紧急域 `emg` 口径，
    # 开闸态整族静默丢消息（R-CENTRAL C-1 成因）。
    progress_ack_settings = None
    progress_ack_submit = None
    if bool(getattr(config, "bot_chat_progress_ack_enabled", False)):
        from .domains.chat_reply.runtime.progress_ack import (
            ACK_DEDUPE_NAMESPACE,
            ProgressAckSettings,
        )
        from .domains.transport.sender.outbound_gate import submit_active_push

        progress_ack_settings = ProgressAckSettings.from_config(config)

        async def _submit_progress_ack(request: Any) -> Any:
            """入列 + **就地投递**，且入列**必须留在事件循环里**。两条各对应一种实测塌法：

            ① 只入列不投递是本功能最坏的错法：`queue.submit` 把 `next_retry_at` 写成"内联宽限
            期"（= max(60s, 3×传输超时)）之后才轮到 worker，真正投递**由调用方就地负责**（提醒族
            A-01 旧账：只 submit 不投递=永不送达）。回执若 60 秒后才到，语义还会反转成"答完追一
            句我在想"——比不发更糟。
            ② A-22 认领台账只在有运行中事件循环时才登记（`_register_inline_claim` 自述）：把
            submit 包进 `asyncio.to_thread` ⇒ 线程里 `current_task()` 抛错 ⇒ 台账静默不登记 ⇒
            防双发盾退化成纯时间宽限（本仓实测过 140–395s 循环停顿；S17 离线复刻双发=True）。
            故照提醒族同一条路：闸放行 → `_deliver_transport_send_request` 就地送 → 没送成功
            就抛，让 pipeline 不占冷却坑（下一次追问仍可得救）。
            """
            outcome = submit_active_push(
                send_queue,
                request,
                outbound_gate,
                dedupe_family="once",
                dedupe_namespace=ACK_DEDUPE_NAMESPACE,
            )
            verdict = outcome.verdict
            if verdict.action == "skip":
                # DEFECT-4/6（2026-09-28 主会话落 S-ACK hub 申请 H-5）：skip＝这条**永远不会
                # 送出**。原样静默 return 的话，本轮已经占掉的那次回执冷却坑就白烧了——用户
                # 此后一段时间再也收不到一句等待提示，而现场一行日志都没有。抛给 pipeline
                # （其 :1532-1534 见抛即退坑），让冷却额度回到可复用状态。
                raise RuntimeError(
                    f"progress ack skipped by outbound gate (reason={verdict.reason})"
                )
            if verdict.action != "allow" or verdict.deliver_after is not None:
                return outcome  # 闸判了顺延：交回队列，不占冷却坑
            # 首参必须是 provider 可调用对象而非其返回值：传 dict 会被吞成 None=静默不发（本波实犯）。
            bot = _select_queue_bot(_all_online_bots, request)
            if bot is None:
                raise RuntimeError("progress ack has no online bot")
            receipt = await _deliver_transport_send_request(
                bot,
                None,
                request,
                audit_logger,
                receipt_repository,
                send_queue,
            )
            if receipt is None or receipt.state not in {
                ReceiptState.SENT,
                ReceiptState.REDIRECTED,
            }:
                raise RuntimeError(
                    f"progress ack not delivered (state={getattr(receipt, 'state', 'none')})"
                )
            return outcome

        progress_ack_submit = _submit_progress_ack
    # 回执阈值跟着网关当下快慢走（2026-09-25 用户裁定第 6 项）：固定 15 秒在
    # 链上单跳 EWMA 实测 13.7 秒的现在必然一抖就报。读数只认渠道健康库这一本账
    # （model_router:924 同一取法），不在这里另开一份延迟统计。
    # 5 秒 TTL 的理由：这一读发生在事件循环上，不得每条消息都去开一次 SQLite。
    _ack_ema_cache: dict[str, Any] = {"at": 0.0, "ema_ms": None}

    def _slowest_gateway_ema_ms() -> float | None:
        """链上最慢一跳的 EWMA（毫秒）；读不到返回 None ⇒ 退回固定阈值。"""
        now = time.monotonic()
        if now - float(_ack_ema_cache["at"]) < 5.0:
            cached = _ack_ema_cache["ema_ms"]
            return None if cached is None else float(cached)
        ema_ms: float | None = None
        try:
            from .domains.chat_reply.llm_engine.channel_health import (
                get_channel_health_store,
            )

            latencies = get_channel_health_store().ema_latencies()
            if latencies:
                ema_ms = max(float(value) for value in latencies.values())
        except Exception:  # noqa: BLE001 - 观测面坏了不得把回执功能一起带走。
            ema_ms = None
        _ack_ema_cache["at"] = now
        _ack_ema_cache["ema_ms"] = ema_ms
        return ema_ms
    pipeline = RuntimePipeline(
        progress_ack_latency_probe=_slowest_gateway_ema_ms,
        redrive_settings=build_redrive_settings(config),
        feature_gate=product_feature_gate,
        outbound_voice_enricher=pipeline_voice_enricher,
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
        # 监听专用号（校园学校号 bot_campus_self_ids）收到的群消息一律不回话；
        # 直接读 config（非门控后的 source 快照），校园总闸即便关闭此约束仍在。
        listen_only_bot_ids=frozenset(
            str(item).strip() for item in (config.bot_campus_self_ids or []) if str(item).strip()
        ),
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
        progress_ack_settings=progress_ack_settings,
        progress_ack_submit=progress_ack_submit,
    )

    def _all_online_bots() -> dict[str, Any]:
        try:
            return dict(get_bots())
        except Exception:  # noqa: BLE001 - 获取在线 Bot 失败时降级为空注册表。
            return {}

    # N4 主动搭话亲和门：群聊抽签主动接话只对好感档 ≥ 亲近（close）的用户。
    # 冷却/频控由 rate_limit 层 proactive 分桶承担（bot_group_proactive_*）。
    if bool(getattr(config, "bot_proactive_affinity_gate_enabled", True)):
        from .domains.chat_reply.character.affinity import (
            attitude_tiers,
            tier_for_affinity,
        )
        from .domains.chat_reply.policy.gate import configure_proactive_affinity_gate

        def _proactive_affinity_check(sender_id: str) -> bool:
            store = build_character_affinity_store(config)
            if store is None:
                return False
            affinity = float(
                store.snapshot(str(sender_id)).get("affinity", 0.0) or 0.0
            )
            # N4 死门修复（互动面波 2026-10-03）：``tier_for_affinity`` v4 起回
            # **整数档 id**（-4..+3），旧写法 ``== "close"`` 拿 int 比字符串恒
            # False ⇒ 这道门自装配以来从未放行过一次（档案在 SDD7 N4）。
            # 判法=档 id ≥ 亲近档 id；亲近档 id 从八档表现算（档名唯一真身
            # ``affinity.attitude_tiers``），不手抄整数——档表改名/换序自动跟随。
            close_tier_id = next(
                tier_id
                for tier_id, tier_name, _instruction in attitude_tiers()
                if str(tier_name).startswith("亲近")
            )
            return tier_for_affinity(affinity) >= close_tier_id

        configure_proactive_affinity_gate(_proactive_affinity_check)
    else:
        from .domains.chat_reply.policy.gate import configure_proactive_affinity_gate

        configure_proactive_affinity_gate(None)

    def _first_online_bot() -> OneBotV11Bot | None:
        # 历史上的今天等系统推送要发 OneBot 请求：注册表首个 bot 可能是
        # Telegram/Mail 账号，跨适配器调用必然失败；只取 onebot 适配器账号。
        return cast(Any, _select_credential_bot(_all_online_bots()))

    from .control_plane.lifecycle import register_control_plane_lifecycle

    def make_control_plane_app():
        from .control_plane import create_control_plane_app
        return create_control_plane_app(
            config, feature_service=feature_service, settings_store=runtime_settings,
            runtime_attached=True,
            # V21-risk-4：队列与实时连接态经参数注入（禁全局单例直连）。
            send_queue=send_queue,
            runtime_state_probe=lambda: _select_credential_bot(
                _all_online_bots()
            ) is not None,
        )

    register_control_plane_lifecycle(get_driver(), config, make_control_plane_app)

    operational_alert_suppression = AdminAlertSuppression()

    result_unknown_ledger = ResultUnknownLedger(
        _runtime_scripts_path("data/result_unknown.sqlite3")
    )

    group_file_store = GroupFileStore(_runtime_scripts_path("data/group_files.sqlite3"))
    group_info_cache = GroupInfoCache()
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
        async def _resend() -> DeliveryReceipt:
            if target.adapter == "onebot":
                return await send_onebot_v11(bot, request)
            from .domains.transport.sender.nonebot import send_nonebot_message

            return await send_nonebot_message(bot, None, request)

        receipt = await _resend()
        # 直发腿不入队（无 part 账、无退避、无重投）⇒ 一次代理瞬断就是一条永久
        # 消失的管理员告警。只对 connect_phase（连接建立期失败＝零字节出网、必
        # 未送达）后台补发**一次**，短退避、不阻塞事件循环；补发再失败维持现状
        # （success=False、不入队、不再补）。不确定类一律不补＝M-63 红线（#47）。
        from .domains.transport.sender.failure_class import (
            schedule_connect_phase_resend,
        )

        schedule_connect_phase_resend(request, receipt, _resend)
        return receipt

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
        # LLM 截止超时（stage=llm / kind=deadline_exceeded）**照常进管理员告警链**
        # （超时改造 C1-c，2026-09-28 用户裁定）。这里曾有一句按该 kind 的早退，
        # 代价正是这条线反复付过的学费：把一类故障从可见面上摘掉，它就再也没人修
        # （台账 #49「在册未执法」同族、#51「没检索禁写它没有」同规）。刷屏由
        # operational_alert_suppression 的抑制窗统一承担（runtime/alerts.py），
        # 本处不再自建第二道静默闸。
        targets = _operational_alert_targets()
        if not targets:
            return
        try:
            await notify_operational_issue(
                issue,
                source_adapter=message.adapter, session_id=message.session_id,
                source_bot=message.bot_id,
                session_type=message.session_type, group_id=message.group_id or "",
                targets=targets, pipeline=pipeline, request_id=message.request_id,
                online_bots=_all_online_bots,
                delivery=_deliver_admin_alert,
                suppression=operational_alert_suppression,
            )
        except Exception:  # noqa: BLE001 - admin alert side channel is best effort.
            # Administrator alerting is a diagnostic side channel and must never
            # alter or recursively re-enter the originating request.
            return

    _pending_probe_alert_tasks: set[Any] = set()

    def _push_probe_issue(
        issue: Any,
        *,
        source_bot: str = "tts-probe",
        capability_id: str = "bot.tts",
    ) -> None:
        """运营诊断 → 中央管理员告警口（S-OBS：`last_operational_issue()` 的生产读者）。

        唯一共用告警出口：语音探针、绘画探针、出站闸（QG9①）、订阅死信（SUB-1）
        全走这一个函数，各域只报自己的 `source_bot`/`capability_id`——**不许另造
        第二条直发腿**（台账 #49★「未执法＝出站闸与 cookie 提醒缺省关」同族教训）。

        探针此前只把 issue 存在自己口袋里，全树零读者＝诊断存在但永远没人看见。
        这里刻意**共用** `operational_alert_suppression`（同一个 300s 抑制器），不另造
        第二道节流闸；告警口是异步的，而 `flush_probe_issue_to_alerts()` 是同步调用点，
        所以只在确有事件循环时挂一个任务，循环不在就诚实放弃（下一次查询还会再读）。
        """
        from nonebot.log import logger

        targets = _operational_alert_targets()
        if not targets:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("tts probe issue has no running loop; kept for next read")
            return
        try:
            task = loop.create_task(
                notify_operational_issue(
                    issue,
                    source_adapter="runtime",
                    source_bot=source_bot,
                    session_type=SessionType.PRIVATE,
                    targets=targets, pipeline=pipeline, capability_id=capability_id,
                    online_bots=_all_online_bots,
                    delivery=_deliver_admin_alert,
                    suppression=operational_alert_suppression,
                )
            )
        except Exception:  # noqa: BLE001 - 告警是旁路，绝不能反噬状态查询。
            logger.debug("tts probe alert scheduling failed", exc_info=True)
            return
        # create_task 的返回值若不持引用，任务可能在完成前被 GC 掉（告警静默消失）。
        _pending_probe_alert_tasks.add(task)
        task.add_done_callback(_pending_probe_alert_tasks.discard)

    from .domains.media.voice_health_alert import install_probe_alert_sink

    install_probe_alert_sink(_push_probe_issue)

    # 中央调度收编波 P5-E3：creation 预留面（绘画/语音对接点）的「要而不得」告警**共用**
    # 上面那个 sink（同 `_push_probe_issue`、同 `operational_alert_suppression` 300s 抑制），
    # 不另造第二条投递路（宪法：跨域装配只在装配层；告警口唯一）。
    # 2026-09-28 探针正名：此前本腿直吃 sink 缺省，告警「发出账号」显示 `tts-probe`、
    # 能力顶 `bot.tts`——与语音无关的创作缺位被挂到探针名下，误导用户查语音腿。
    # 改法＝薄包装只补署名、仍转发同一个中央口（语音腿不动、继续吃缺省）。
    from .domains.creation.reserved_health_alert import install_reserved_alert_sink

    def _push_creation_patrol_issue(issue: Any) -> None:
        _push_probe_issue(
            issue,
            source_bot="creation-patrol",
            capability_id="creation.reserved_health",
        )

    install_reserved_alert_sink(_push_creation_patrol_issue)
    # 执行体在场性探针（S50/S37 同点实锤 GAP-CREAT-ALERT-STALE）：presence 键里
    # `bot_tts_api_url` 生产缺省恒非空 ⇒ 只按"键填了没"判"要而不得"，会在 P4-C2
    # 接上语音执行体之后每次 /bot status 投一条"实现工厂未接入"的假告警。
    # creation 域按教义不 import 中央层，故这条中央事实由装配层递进去（同 sink 手法）。
    from .domains.creation.reserved_health_alert import install_execution_presence_probe
    from .runtime.capability_protocols import has_registered_handler

    install_execution_presence_probe(has_registered_handler)
    # S-CREATION-GAP-LEDGER（2026-09-28 现场）：`_not_configured_fired` 只活在进程内存
    # ⇒ 一天约 10 次重启把同一件「预留位没接后端、不是故障」的缺位报了约 7 波
    # （每波 2 收件人 ×（文本＋卡）＝4 条，合计约 28 条私聊）。门语义本身没错，缺的是
    # 跨进程记忆 ⇒ 由运维层给一枚本地 JSON 露头账本，同 sink/probe 手法递进本域
    # （creation 域是纯协议壳，禁 os/pathlib/sqlite3，自己不能碰盘）。
    # 账本只在**成功投递后**记账、坏盘 fail-open 偏向多报、24h 窗口后允许重新露头，
    # 所以「缺位必须巡检可见」这条 mandate 不被削掉。撤掉本注入＝退回旧的每进程一次。
    from .domains.creation.reserved_health_alert import install_not_configured_ledger
    from .domains.ops.monitor.reserved_gap_ledger import ReservedGapLedger

    install_not_configured_ledger(
        ReservedGapLedger(_runtime_scripts_path("data/creation_reserved_gap.json"))
    )

    # SEAT-S102-PATROL-WIRE：把 creation 缺位告警从「只有 /bot status 手动触发」升为周期驱动。
    # 注册一条后台任务，按固定间隔调用巡检唯一入口 patrol_reserved_health；复用上面已注入的
    # 同一个 sink（_push_probe_issue → 中央告警链 + AdminAlertSuppression 300s 抑制），不新建
    # 第二条投递路、不改 config（周期/首轮延时为块内常量）。必须 on_startup 起（import 期无
    # running loop 而 sink 依赖 create_task）；持引用防 GC（同 _pending_probe_alert_tasks）。fail-open。
    _CREATION_PATROL_FIRST_DELAY_SECONDS = 90
    _CREATION_PATROL_INTERVAL_SECONDS = 3600

    @get_driver().on_startup
    async def _start_creation_reserved_patrol_on_startup() -> None:
        from .domains.creation.reserved_health_alert import patrol_reserved_health

        async def _creation_reserved_patrol_loop() -> None:
            try:
                await asyncio.sleep(_CREATION_PATROL_FIRST_DELAY_SECONDS)
                while True:
                    try:
                        # 直接在 loop 上同步跑（零网络零 I/O；sink 需 running loop 才能 create_task 投）。
                        patrol_reserved_health(config)
                    except Exception:  # 单轮巡检失败只降级，不终止循环。
                        logging.getLogger(__name__).debug(
                            "creation reserved patrol round failed", exc_info=True
                        )
                    await asyncio.sleep(_CREATION_PATROL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception:  # 循环自身异常退出即降级停用，不冒泡炸启动。
                logging.getLogger(__name__).warning(
                    "creation-reserved patrol: 循环异常退出，缺位巡检降级停用", exc_info=True
                )

        try:
            _patrol_task = asyncio.create_task(_creation_reserved_patrol_loop())
            _pending_probe_alert_tasks.add(_patrol_task)
            _patrol_task.add_done_callback(_pending_probe_alert_tasks.discard)
        except Exception:  # 挂不上调度不影响启动。
            logging.getLogger(__name__).warning(
                "creation-reserved patrol: on_startup 挂接失败，缺位巡检停用", exc_info=True
            )

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
                source_adapter=request.adapter, session_id=request.session_id,
                source_bot=request.bot_id, capability_id=request.capability_id,
                session_type=request.target_scope, group_id=str(request.target_id or ""),
                targets=targets, pipeline=pipeline, request_id=request.request_id,
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
            from .domains.ops.monitor.runtime_event_log import RuntimeEventLog

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
                        from .domains.meme.sources.meme_library_listener import (
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

    def _build_news_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_news_capability(config_)

    def _build_wiki_with_backend(config_: Any, **_kwargs: Any) -> Any:
        return build_wiki_capability(config_)

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
        # 网络巡检（enabled 缺省 True，函数内自gate）：Clash 探针 + 上游双路巡检。
        _register_network_patrol_scheduler(
            scheduler=scheduler,
            config=config,
            audit_logger=audit_logger,
            pipeline=pipeline,
            bot_provider=_all_online_bots,
            receipt_repository=receipt_repository,
            send_queue=send_queue,
        )
        from .domains.chat_reply.llm_engine.model_schedule import (
            _register_model_schedule_scheduler,
        )

        _register_model_schedule_scheduler(
            scheduler=scheduler,
            config=config,
            settings_store=runtime_settings,
        )
        if runtime_event_log is not None:
            from .domains.ops.monitor.usage_monitor import (
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
                outbound_gate=outbound_gate,
            )

        # 夜间每日群通讯总结推送：推送开关开启且共享群摘要能力开启才注册。
        if (
            getattr(config, "bot_group_digest_push_enabled", True)
            and getattr(config, "bot_shared_group_context_enabled", False)
        ):
            _register_digest_push_scheduler(scheduler, config, send_queue, outbound_gate)

        # 日常助理定时推送：到点吃什么 + 收件箱早晚简报；名单为空不注册（只记不推）。
        if getattr(config, "bot_daily_assist_enabled", True) and (
            getattr(config, "bot_daily_assist_push_user_ids", [])
        ):
            _register_daily_assist_scheduler(scheduler, config, send_queue, outbound_gate)

        # V2.1 B2① 服务装配组（WIRE-SVC）：WORLD/KB/DB/TEACH 装配+注册表；
        # 主门缺省关=零装配零副作用（不改现网行为），细节归 domains/chat_reply/runtime/service_wiring.py。
        if getattr(config, "bot_v21_service_wiring_enabled", False):
            try:
                from plugins.bot_unified_runtime.domains.chat_reply.runtime.service_wiring import (
                    register_v21_services,
                )

                wired = register_v21_services(config)
                if wired:
                    from nonebot.log import logger

                    logger.info(
                        "v21 services wired: {}", ",".join(sorted(wired))
                    )
            except Exception as exc:  # noqa: BLE001 - 装配失败不崩主链路。
                from nonebot.log import logger

                logger.warning(
                    "v21 service wiring failed: {}", type(exc).__name__
                )

        from .domains.subscribe.store.subscription_runtime_v2 import (
            register_subscription_runtime_v2,
        )

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
            # SUB-4 腿2（S-ATK-SUBSCRIBE ATK-SUB-4）：远端可控的标题与正文是**二手
            # 内容**，出群前必须过一次中央咽喉（全角化＋成对边界＋定性引导）——裸拼
            # 出去时远端可在群消息里开伪造内部标记形态（如 `[引用回复 …]`），被后续
            # 引用腿的读侧当结构解析。真身＝chat_reply/security/injection.py，禁手拼。
            from .domains.chat_reply.security.injection import (
                guard_secondhand_text,
            )

            safe_title = guard_secondhand_text(title, source_label="订阅条目内容")
            safe_body = guard_secondhand_text(body, source_label="订阅条目内容")
            text = (
                f"[订阅] {target.platform} {target.display_name} 更新《{safe_title}》："
                f"{event.item.url}"
            )
            if body:
                text += f"\n{safe_body[:500]}"
            elif bool(getattr(config, "bot_vision_enabled", False)):
                # 纯图/无文本订阅条目：用 vision 补一行描述，失败静默不阻断推送。
                from .domains.media.ingest.vision_describe import (
                    describe_subscription_item,
                )

                # 同步 HTTP 描述调用必须下放线程池，否则每条无文本订阅条目
                # 都会在事件循环上阻塞数秒（审计重发现 P2）。
                described = await asyncio.to_thread(
                    describe_subscription_item, vision_provider, payload
                )
                if described:
                    # 模型输出同样是二手内容（VLM 读的是远端图），一并过咽喉。
                    text += "\n图：" + guard_secondhand_text(
                        described, source_label="订阅条目图像描述"
                    )
            from .domains.link_parse.capabilities.content_parser import (
                build_subscription_push_capability,
            )

            # SUB-2 根腿（ATK-SUB-1）：逐目的地记账，不再把整事件压成一个 bool——
            # 旧形态（`return sent_any and all_success`）下 10002 一失败，已成功收到
            # 的 10001 没有台账，整事件 retry 后每轮再推一遍（最多 5 遍双发）。
            # 键＝目的地行 id，与 scheduler 的 `_enabled_destination_keys`／查重口
            # 同一把尺，不另立第二套。
            outcomes: list[tuple[str, bool]] = []
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
                    plain_text=text, command_text=mentions.strip_leading_name_mention(text, _RUNTIME_MENTION_TERMS),  # 同一派生规则，不另立第二套
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
                        outcomes.append((str(destination.id), False))
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
                        outcomes.append((str(destination.id), True))
                    else:
                        outcomes.append((str(destination.id), False))
                except (OSError, RuntimeError, TypeError, ValueError):
                    outcomes.append((str(destination.id), False))
            # 契约是 Awaitable[bool]（subscription_scheduler.py:76）：逐目的地台账已由
            # outbox 侧落库，这里只回报「是否全部送达」。直接 return outcomes 会让
            # bool() 恒真——只要有一个目的地，全败也被记成投递成功。
            return bool(outcomes) and all(sent for _destination_id, sent in outcomes)

        # 模型渠道健康巡检：每小时全量探测一次（后台低并发最小调用），
        # 暂不可用渠道自动移出故障转移队列，恢复即自动回队。
        # B-13（D7 残留）：取数走 _probe_specs 合并视图（.env 注册表 ∪
        # 运行时注册表），管理员 /bot model add 的新渠道也进后台巡检——
        # 此前只探 build_model_registry（仅 .env），运行时渠道永无健康数据。
        if getattr(config, "bot_channel_health_enabled", True):
            def _channel_health_job() -> None:
                try:
                    from .domains.chat_reply.llm_engine.channel_health import (
                        get_channel_health_store,
                        probe_all,
                    )
                    from .domains.ops.admin.runtime_admin import _probe_specs

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
                    from .domains.core.credentials.platform_credentials import (
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
                # 裁定 R-4 + 在册未执法④（2026-09-24「全部统一」）：cookie 到期提醒**只**走
                # 统一范式投递（SendRequest→SendQueue→内联投递，SENT 才算送达）；
                # dedupe/request_id 带本地日期=当日幂等，管理员换人重试语义与旧直连等价，
                # 全部失败静默。旧 `bot_cookie_expiry_reminder_via_queue` 开关与其下的
                # `send_private_msg` 逐管理员直发循环一并退役——那条直发正是「四条主动投递
                # 已接中央出口」这句话此前只在开态为真的那半条。
                try:
                    await _deliver_cookie_expiry_report_via_queue(
                        config,
                        send_queue,
                        audit_logger,
                        receipt_repository,
                        bot,
                        report,
                        admins,
                        outbound_gate=outbound_gate,
                    )
                except Exception:  # 统一路径失败不影响主链路。
                    logging.getLogger(__name__).debug(
                        "cookie expiry notice via queue failed", exc_info=True
                    )

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
                # SUB-1 尾线：死信（`retryable=False` 且此后永不 claim）此前只有一行
                # WARNING 混在日志海里——`29f2cf6`/`de39afc` 把 build/store/register
                # 三侧都备好了，这最后一行接的是中央同一个告警口。
                dead_letter_sink=lambda issue: _push_probe_issue(
                    issue, source_bot="subscribe", capability_id="bot.subscribe"
                ),
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
            # 容器门收窄（B3）：容器=库目录本身，不再宽到整个 data 根。
            library_dir=str(getattr(config, "bot_meme_library_dir", "data/meme_library") or ""),
        )
        if getattr(config, "bot_meme_library_enabled", False)
        else None
    )
    # 贴纸回应持久化（B 线 2026-09-16「把所有表情贴纸存下来」）：识别事件
    # 双写（缓冲+落库）；启动期按保留期裁剪一次。
    _reaction_store = ReactionStore(
        str(getattr(config, "bot_reactions_db_path", "data/reactions.sqlite3") or "")
    )
    _reaction_store.prune(keep_days=int(getattr(config, "bot_reactions_store_days", 90) or 90))
    # 双层表情·第二层（情绪时刻发表情包）：独立五门（开关/每消息去重/
    # 确定性概率/会话冷却/每小时时限）+ 每会话每日上限 + C1 悲伤门；
    # 与第一层贴小表情互斥（第一层贴过则本层整条让路）。
    # 选图自 S-T-STK-2（2026-09-26）起走门面 select_sticker_for_turn（原顶层
    # pick_reaction_meme 直呼已删，函数内局部 import，先例 _pick_poke_meme）；反重复
    # 在 MemeLibraryStore.weighted_pick 咽喉执法，与本腿调用点无关。
    # S-STICKER-POOLS（2026-09-29）**改只吃贴纸池**：本腿以 ``pool_policy=packs_only``
    # 调门面，门面内部只问 ``sticker_packs.pick_sticker``，挑不出就整条不发——
    # **绝不回退 ``bot_meme_library_dir`` 那盘群聊吸收截图**（用户实弹点名的正是它）。
    # 同波补齐三道此前缺失的硬门：``bot.plugin.sticker_packs`` 特性门 +
    # blocked 名单 + 安静时间（前两道走 sticker_send_routing，第三道在
    # proactive_action_allowed 里与五层门一并执法）。
    _REACTION_MEME_GATE = _ReactionProactiveGateClass()
    _reaction_meme_daily: dict[str, tuple[int, int]] = {}
    # S2 案二（2026-09-30 席位 W4R）：回执并图成功后登记「本轮这条消息已并图」，
    # P3 腿入口查标即跳过——**双发防护只有这一本**：键与腿的 `message_key` 同形
    # （`meme:<message_id>`），值只留那张图的路径供事后查，进程内有界、不落盘。
    # 额度账/冷却账不另立：仍是下面的 `_reaction_meme_daily` 与 `_REACTION_MEME_GATE`。
    _reaction_meme_merged: dict[str, str] = {}
    _REACTION_MEME_MERGED_MAX = 512

    # 同轮三腿互斥（互动面波 2026-10-03）：回复后链 P3 情绪贴纸 → poke after-reply
    # → randpic dispatch，任一腿**实际发出**（贴纸图 / 真戳到了 / 随机图）即占坑，
    # 调用点查到占坑就短路后两腿；三腿都未中互不影响。键形 ``turn-attach:<message_key>``
    # ——**刻意避开既有命名空间**（``meme:``/``emoji:``＝双发防护两腿的门键、
    # ``randpic:``＝五层门键形；「emoji 腿不占 P3 的 meme: 命名空间」同一条纪律），
    # 互斥账单独一本，不与任何门账混读混写。进程内有界、不落盘（照
    # ``_reaction_meme_merged`` 形态）；空 message_key 不占坑——空键占坑会把
    # 「本轮互斥」放大成「全会话互斥」。
    _turn_attachment_claims: dict[str, str] = {}
    _TURN_ATTACHMENT_CLAIMS_MAX = 256

    def _turn_attachment_claimed(message_key: str) -> bool:
        return f"turn-attach:{message_key}" in _turn_attachment_claims

    def _turn_attachment_mark(message_key: str, leg: str) -> None:
        key = str(message_key or "").strip()
        if not key:
            return
        _turn_attachment_claims[f"turn-attach:{key}"] = str(leg)
        while len(_turn_attachment_claims) > _TURN_ATTACHMENT_CLAIMS_MAX:
            _turn_attachment_claims.pop(next(iter(_turn_attachment_claims)), None)

    async def _maybe_send_reaction_meme(
        bot: Bot,
        event: Event,
        *,
        session_key: str,
        text: str,
        meme_config: Any,
        reply_text: str = "",
        feature_enabled: Any = None,
        claim_key: str = "",
    ) -> None:
        """情绪时刻发一张贴纸：**只**从管理员登记的贴纸池拿。

        ``feature_enabled``：本轮特性开关快照的 ``enabled`` 查询口（由调用点注入，
        与 ``_poke_voice_pair`` 同一约定）。**没给＝按不通过算**——本腿是主动外发，
        宁可什么都不发，也不许「忘了传快照」变成无条件放行。

        ``claim_key``：同轮三腿互斥的占坑键（调用点传本轮 message_key）。真发出
        （SENT/REDIRECTED）才落占坑（``_turn_attachment_claims``），让同轮后两腿
        （poke after-reply / randpic dispatch）让位；空键＝不参与互斥。

        挑不出贴纸＝静默返回（不发、不报错、不回退吸收池）；审计轨
        ``sticker_send_routing.last_pool_for(session_key)`` 留 ``none`` 可查。
        """
        from .domains.chat_reply.capabilities.poke import (
            ProactiveActionKnobs,
            proactive_action_allowed,
        )
        from .domains.meme.sources import sticker_send_routing

        # S2 案二·双发防护（本轮正文里已经并了同一张贴纸 ⇒ 本腿不再另发一条空文本
        # 图消息）。键与下面 ``message_key`` 同形，登记方是本文件里的附图钩子；留痕
        # 走正文那条的 ``audit_tags``（`sticker_same_message`），本腿只在日志留一声。
        merged_message_id = str(getattr(event, "message_id", "") or "")
        if merged_message_id and f"meme:{merged_message_id}" in _reaction_meme_merged:
            logger.debug(
                "reaction meme leg skipped: sticker merged into reply"
                " (sticker_same_message) message_id=%s",
                merged_message_id,
            )
            return
        if not bool(getattr(meme_config, "bot_reactions_meme_enabled", False)):
            return
        # 硬门 ①：贴纸池特性开关（未登记即 False ⇒ 本腿结构性不发）。
        if not sticker_send_routing.sticker_feature_enabled(feature_enabled):
            return
        if _is_sad_reaction_message(text):
            return  # C1：悲伤消息绝不发表情包（红线级，与第一层同口径）。
        intent = _infer_reaction_signal_intent(text)
        if intent is None and not str(reply_text or "").strip():
            # 2026-09-28 贴纸语义匹配波：过去这一门要求用户原话命中情绪关键词，
            # 于是"喜事没关键词就根本不进选贴腿"。现在只要有本轮回复文本就交给
            # 语义判定（它读的是 bot 自己说了什么）；两者皆无 ⇒ 不贴（错配比不贴更糟）。
            return
        group_id = str(getattr(event, "group_id", "") or "")
        sender = str(getattr(event, "sender_id", "") or "")
        # 硬门 ②③：blocked 名单 + 安静时间（判据真身在 poke.py，本处零自造）。
        # 先于五层门跑：那两道的名单与窗都是**无副作用**读，放在 ``allow`` 之后
        # 就被记进冷却了——「被窗拦下」反咬后续动作是 poke 波立过的判据。
        if not sticker_send_routing.social_gates_allow(
            meme_config, group_id=group_id, user_id=sender
        ):
            return
        message_id = str(getattr(event, "message_id", "") or "")
        # 硬门 ④：开关→有目标→名单→窗→五层门（同一提交点，替代原先裸调
        # ``gate.allow``：那只兜住了概率/冷却/时限，名单与窗一条都没接上）。
        if not message_id or not proactive_action_allowed(
            meme_config,
            prefix="bot_reactions_meme_",
            gate=_REACTION_MEME_GATE,
            session_key=session_key,
            message_key=f"meme:{message_id}",
            group_id=group_id,
            user_id=sender,
            salt="reaction-meme",
            # 字面键名取数（与 poke / randpic 两族同判据）：见 ProactiveActionKnobs 的 why。
            knobs=ProactiveActionKnobs(
                # 开关真身 bot_reactions_meme_enabled（config.py 缺省 False，.env 用户侧
                # 已置 true）；兜底 True 只服务缺这枚字段的旧鸭子桩——真 pydantic
                # Config 字段恒在，兜底走不到。
                enabled=bool(getattr(meme_config, "bot_reactions_meme_enabled", False)),
                probability=float(
                    getattr(meme_config, "bot_reactions_meme_probability", 0.15) or 0.15
                ),
                cooldown_seconds=float(
                    getattr(meme_config, "bot_reactions_meme_cooldown_seconds", 120) or 120
                ),
                max_per_hour=int(
                    getattr(meme_config, "bot_reactions_max_per_hour", 20) or 20
                ),
            ),
        ):
            return
        day = int(time.strftime("%Y%m%d", time.localtime()))
        used_day, used = _reaction_meme_daily.get(session_key, (day, 0))
        if used_day != day:
            used = 0
        daily_max = int(getattr(meme_config, "bot_reactions_meme_daily_max", 6) or 6)
        if daily_max > 0 and used >= daily_max:
            return
        from .domains.meme.capabilities.meme_library import select_sticker_for_turn

        # ``meme_library_store`` 在这里**只当作「库腿不参与」的占位**传进去：
        # ``packs_only`` 门面在池子挑不出时就返回 None，根本不碰它（本腿不再
        # 从吸收池出图，所以 ``bot_meme_library_enabled`` 关掉也不再拦本腿）。
        picked, sticker_tags = await asyncio.to_thread(
            select_sticker_for_turn, None, turn_text=text,
            reply_text=reply_text,
            session_key=session_key, sender_id=sender, config=meme_config,
            mood_valence_fn=lambda: _mood_valence(meme_config),
            affinity_snapshot=_poke_affinity_snapshot(meme_config, sender),
            pool_policy=sticker_send_routing.POOL_POLICY_PACKS_ONLY,
            pool_seed=f"reaction-meme:{session_key}:{message_id}",
            persona_albums=_persona_album_names(meme_config),
        )
        meme_path = str((picked or {}).get("path") or "").strip()
        if not meme_path:
            return  # 静默跳过：贴纸池空/挑不出＝不发，绝不退化成发吸收池那张。
        _reaction_meme_daily[session_key] = (day, used + 1)
        meme_receipt = await _send_parts_through_unified_pipeline(
            bot, event, text="", image=meme_path,
            audit_tags=[
                "sticker_pack",
                "reaction_meme",
                f"intent:{intent}",
                *[tag for tag in sticker_tags if str(tag).startswith("sticker_pool:")],
            ],
            capability_id="bot.chat")
        if getattr(meme_receipt, "state", None) in {ReceiptState.SENT, ReceiptState.REDIRECTED}:
            # 真发出才占坑：同轮 poke / randpic 两腿据此让位（见 _turn_attachment_mark）。
            _turn_attachment_mark(claim_key, "reaction_meme")

    async def _reaction_target_message_text(bot: Bot, message_id: str) -> str:
        """反查「被贴表情那条消息」的正文，**只在它确实是我自己发的**时交回文本。

        文本源判定的结论（本腿唯一的可靠正文口，三条候选各自的下场）：

        * ``_REACTION_BUFFER``（``domains/meme/reactions/engine.py:511``）**没存正文**：
          它按会话存「谁给哪条消息贴了什么」（:533 ``record``）与我自己发出的消息
          **id**（:545 ``register_bot_message`` 只收 id），没有任何 message_id→正文
          的口，所以「被回应的那句到底说了什么」在缓冲里结构性缺席。
        * ``_reaction_store``（``domains/meme/sources/reaction_store.py:35``）只有
          ``emoji_stats``/``user_stats`` 两枚聚合读口（:96/:118），表里连正文列都没有
          （:18 ``reaction_events``）＝同样取不到。
        * ⇒ 真身只剩协议反查：``_make_onebot_reply_lookup``（本文件 :567，``get_msg``
          的既有注入口，3s 超时、失败一律 ``None``）。它是「引用链反查」那条腿的同一个
          喉，本腿不另开第二条取数路。
        """
        lookup = _make_onebot_reply_lookup(bot)
        if not callable(lookup):  # pragma: no cover - 装配口恒定可调用，防御性一拦
            return ""
        payload = await lookup(str(message_id))
        if not isinstance(payload, dict):
            return ""  # 反查失败＝取不到，绝不猜
        sender = payload.get("sender")
        sender = sender if isinstance(sender, dict) else {}
        # 「对我的消息」的判据＝协议侧读数：被回应消息的发送者就是我本人的 id。
        # 不用缓冲的 bot 消息登记（:545）当判据——它只在
        # ``bot.plugin.chat.reactions.after_reply`` 开着时才记账、TTL 600s、重启即清，
        # 拿它当唯一凭证会造出「另一枚开关决定本腿生死」的隐式耦合。
        self_id = str(getattr(bot, "self_id", "") or "").strip()
        sender_id = str(sender.get("user_id", "") or "").strip()
        if not self_id or not sender_id or sender_id != self_id:
            return ""  # 不是我的消息 / 认不出发送者＝没有可靠正文，交回空串
        parts: list[str] = []
        for segment in payload.get("message") or []:
            if not isinstance(segment, dict):
                continue
            if str(segment.get("type", "")) != "text":
                continue  # 图片/语音/卡片段不算正文：本腿要的是「说了什么」这句话
            data = segment.get("data")
            value = str((data or {}).get("text", "")).strip() if isinstance(data, dict) else ""
            if value:
                parts.append(value)
        return " ".join(parts).strip()

    async def _maybe_send_sticker_for_emoji_like(
        bot: Bot,
        event: Event,
        *,
        reaction_event: Any,
        meme_config: Any,
        feature_enabled: Any = None,
    ) -> None:
        """S3 face 回应联动：群里有人对我的消息贴了表情 ⇒ 小概率补发一张册贴纸。

        ``feature_enabled`` 与 P3 腿同一约定：本轮特性快照的 ``enabled`` 查询口由调用点
        注入，**没给＝按不通过算**（主动外发腿不许有「忘了传快照」的隐式放行档）。
        特性门只认已在册的 id（``bot.plugin.sticker_packs`` 走
        ``sticker_send_routing.sticker_feature_enabled``、
        ``bot.plugin.chat.reactions.meme`` 由调用点在派发前判）——未登记 id 在真目录里
        恒关，拿它当门＝永久哑巴。

        **群聊 only（AGENTS 台账 #35 红线）**：判据两枚都用现成中央口——
        ``domains/meme/reactions/engine.py`` 的 ``_is_group_session``（会话键真身）
        ∧ 事件 ``group_id`` 必在场。私聊形态的 ``private_msg_emoji_like`` 到这里
        一次都不成立，QQ 侧本就无私聊表情回应通道，更不该有私聊主动出图。

        **文本源**（本腿最难的一格，判定过程写在
        :func:`_reaction_target_message_text` 的 docstring 里）：notice 侧只有
        ``emoji_text``/``emoji_id``，被回应那句正文既不在缓冲也不在库里，只能按
        ``message_id`` 走 ``get_msg`` 反查，且只在协议读数证明「那条是我的消息」时
        才算可靠。取不到可靠正文 ⇒ **诚实不发**（P3 波立过的判据：错配比不贴更糟）。
        ``emoji_text`` 交 ``turn_text``（用户此刻的表达），反查正文交 ``reply_text``
        （我上一轮实际说了什么）——两个槽位各自装各自的真身，语义与 P3 完全同形。

        任何岔子（无 id / 无群号 / 私聊 / 取不到正文 / 门没过 / 挑不出图 / 抛异常）
        一律「不发 + debug 痕」，绝不让 notice 链路报错——识别与落库那段先完成、
        本腿坏了也不回滚它。
        """
        from .domains.chat_reply.capabilities.poke import (
            ProactiveActionKnobs,
            proactive_action_allowed,
        )
        from .domains.meme.capabilities.meme_library import select_sticker_for_turn
        from .domains.meme.reactions.engine import _is_group_session
        from .domains.meme.sources import sticker_send_routing

        try:
            session_key = str(getattr(reaction_event, "session_key", "") or "").strip()
            message_id = str(getattr(reaction_event, "message_id", "") or "").strip()
            sender = str(getattr(reaction_event, "user_id", "") or "").strip()
            emoji_text = str(getattr(reaction_event, "emoji_text", "") or "").strip()
            group_id = str(getattr(event, "group_id", "") or "").strip()
            if not message_id or not group_id:
                logger.debug(
                    "emoji-like sticker leg skipped: no group_id/message_id "
                    "(group=%s message=%s)",
                    group_id, message_id,
                )
                return
            if not _is_group_session(session_key):
                return  # #35：私聊绝不补发（会话键才是判定口，带群号也不算）。
            if not bool(getattr(meme_config, "bot_reactions_meme_enabled", False)):
                return
            # 硬门 ①：贴纸池特性开关（与 P3 腿同一枚口，未登记即 False ⇒ 结构性不发）。
            if not sticker_send_routing.sticker_feature_enabled(feature_enabled):
                return
            if _is_sad_reaction_message(emoji_text):
                return  # C1：悲伤表达绝不配笑脸（与 P3 同一把尺，读用户此刻的表意）。
            replied_text = await _reaction_target_message_text(bot, message_id)
            if not replied_text:
                # 取不到可靠正文＝不发。这里不留「猜一张」的档：本腿是主动外发，
                # 语境错配的贴纸比沉默更伤人（P3 波判据原样适用）。
                logger.debug(
                    "emoji-like sticker leg skipped: no reliable source text "
                    "(message_id=%s)",
                    message_id,
                )
                return
            if _is_sad_reaction_message(replied_text):
                return  # C1 在本腿多读一面：我自己那句本身就是丧事场合时同样不配图。
            intent = _infer_reaction_signal_intent(emoji_text)
            if intent is None and not str(replied_text or "").strip():
                return  # 语义门槛（与 P3/钩子同判据）：两者皆无＝不贴。
            # 硬门 ②③：blocked 名单 + 安静时间（判据真身在 poke.py，本处零自造）。
            # 依旧先于 ``allow`` 跑：那两道是无副作用的读，放在 allow 之后就成了
            # 「被窗拦下反咬后续动作」（poke 波立过的判据）。
            if not sticker_send_routing.social_gates_allow(
                meme_config, group_id=group_id, user_id=sender
            ):
                return
            # 硬门 ④：同一枚五层门、同一个 prefix、同一个 salt；只有 ``message_key``
            # 换成本腿自己的形（``emoji:`` 前缀，不占 P3 的 ``meme:`` 命名空间）。
            if not proactive_action_allowed(
                meme_config,
                prefix="bot_reactions_meme_",
                gate=_REACTION_MEME_GATE,
                session_key=session_key,
                message_key=f"emoji:{message_id}",
                group_id=group_id,
                user_id=sender,
                salt="reaction-meme",
                # 字面键名取数（与 P3 / 钩子 / poke / randpic 同判据）：见
                # ProactiveActionKnobs 的 why。四枚旋钮全复用，零新增字段。
                knobs=ProactiveActionKnobs(
                    enabled=bool(getattr(meme_config, "bot_reactions_meme_enabled", False)),
                    probability=float(
                        getattr(meme_config, "bot_reactions_meme_probability", 0.15) or 0.15
                    ),
                    cooldown_seconds=float(
                        getattr(meme_config, "bot_reactions_meme_cooldown_seconds", 120) or 120
                    ),
                    max_per_hour=int(
                        getattr(meme_config, "bot_reactions_max_per_hour", 20) or 20
                    ),
                ),
            ):
                return
            day = int(time.strftime("%Y%m%d", time.localtime()))
            used_day, used = _reaction_meme_daily.get(session_key, (day, 0))
            if used_day != day:
                used = 0
            daily_max = int(getattr(meme_config, "bot_reactions_meme_daily_max", 6) or 6)
            if daily_max > 0 and used >= daily_max:
                return
            # ``store=None`` 与 P3 同形：packs_only 门面挑不出就返回 None，
            # 本腿因此**永远不会**从群聊吸收池出图（那条红线不因换了触发点而松）。
            picked, sticker_tags = await asyncio.to_thread(
                select_sticker_for_turn, None, turn_text=emoji_text,
                reply_text=replied_text,
                session_key=session_key, sender_id=sender, config=meme_config,
                mood_valence_fn=lambda: _mood_valence(meme_config),
                affinity_snapshot=_poke_affinity_snapshot(meme_config, sender),
                pool_policy=sticker_send_routing.POOL_POLICY_PACKS_ONLY,
                pool_seed=f"reaction-emoji:{session_key}:{message_id}",
                persona_albums=_persona_album_names(meme_config),
            )
            meme_path = str((picked or {}).get("path") or "").strip()
            if not meme_path:
                return  # 池子空/挑不出＝不发，绝不端吸收池那张。
            _reaction_meme_daily[session_key] = (day, used + 1)  # 同一本账，只 +1
            await _send_parts_through_unified_pipeline(
                bot, event, text="", image=meme_path,
                audit_tags=[
                    "sticker_pack",
                    "reaction_emoji_sticker",
                    "reaction_meme",
                    f"intent:{intent}",
                    *[tag for tag in sticker_tags if str(tag).startswith("sticker_pool:")],
                ],
                capability_id="bot.chat")
        except Exception:  # noqa: BLE001 - notice 链路的补发腿不许把异常送回主链。
            logger.debug("emoji-like sticker leg failed", exc_info=True)
            return

    def _sticker_attach_for_reply(
        *,
        text: str = "",
        reply_text: str = "",
        session_key: str = "",
        group_id: str = "",
        sender_id: str = "",
        message_id: str = "",
        feature_enabled: Any = None,
    ) -> tuple[str, tuple[str, ...]] | None:
        """S2 案二：本轮回复**同一条消息**附图的判定钩子（注入 chat 回执构造点）。

        为什么要有它：P3 腿跑在 `transport_receipt.state == "sent"` **之后**，正文
        已经出站，腿里并图在结构上不可能——于是贴纸永远是第二条空文本消息。本钩子在
        回执构造期（发送之前）问一次，点头就把那张塞进 `images`，腿随后查标跳过。

        **绝不绕门、绝不起第二本账**：门链与 P3 腿逐条同序同参——
        `bot_reactions_meme_enabled` → `bot.plugin.sticker_packs` 特性门（快照查询口
        由外部注入，没给＝不通过）→ C1 悲伤门 → 语义门槛 → `social_gates_allow`
        （blocked 名单 + 安静时间，判据真身在 poke.py）→ `proactive_action_allowed`
        （同一枚 `_REACTION_MEME_GATE`、同一个 `message_key=f"meme:{message_id}"`）→
        同一本 `_reaction_meme_daily`（同一个帽）→ 门面 `select_sticker_for_turn`
        （`packs_only` ∧ `persona_albums=_persona_album_names(...)`，prefer_tags 由
        门面按 turn/reply 文本自算）。额度只在**成功附图**时 +1，与腿互斥不双计。

        **只发群聊**（AGENTS 台账 #35 红线口径）：私聊本钩子一次都不成立，私聊那条
        腿的行为与改前逐字节一致——挪动的是「群里的第二条消息」，不是「私聊新增外发」。
        任何岔子（无 id、无群号、挑不出、抛异常）⇒ 返回 ``None``＝退回纯文字，
        P3 腿照旧补发单图，贴纸不会凭空消失。
        """
        from .domains.chat_reply.capabilities.poke import (
            ProactiveActionKnobs,
            proactive_action_allowed,
        )
        from .domains.meme.capabilities.meme_library import select_sticker_for_turn
        from .domains.meme.reactions.engine import _is_group_session
        from .domains.meme.sources import sticker_send_routing

        try:
            if not str(message_id or "").strip() or not str(group_id or "").strip():
                return None  # 无群号＝不是群聊这一族；无 id＝无从登记互斥标，宁可不附。
            if not _is_group_session(str(session_key or "")):
                return None  # #35：主动外发图这一族的群/私判定吃中央会话键真身。
            meme_config = _config_with_runtime_overrides(config, runtime_settings)
            if not bool(getattr(meme_config, "bot_reactions_meme_enabled", False)):
                return None
            if not sticker_send_routing.sticker_feature_enabled(feature_enabled):
                return None
            if _is_sad_reaction_message(text):
                return None
            intent = _infer_reaction_signal_intent(text)
            if intent is None and not str(reply_text or "").strip():
                return None
            if not sticker_send_routing.social_gates_allow(
                meme_config, group_id=group_id, user_id=sender_id
            ):
                return None
            if not proactive_action_allowed(
                meme_config,
                prefix="bot_reactions_meme_",
                gate=_REACTION_MEME_GATE,
                session_key=session_key,
                message_key=f"meme:{message_id}",
                group_id=group_id,
                user_id=sender_id,
                salt="reaction-meme",
                knobs=ProactiveActionKnobs(
                    enabled=bool(getattr(meme_config, "bot_reactions_meme_enabled", False)),
                    probability=float(
                        getattr(meme_config, "bot_reactions_meme_probability", 0.15) or 0.15
                    ),
                    cooldown_seconds=float(
                        getattr(meme_config, "bot_reactions_meme_cooldown_seconds", 120) or 120
                    ),
                    max_per_hour=int(
                        getattr(meme_config, "bot_reactions_max_per_hour", 20) or 20
                    ),
                ),
            ):
                return None
            day = int(time.strftime("%Y%m%d", time.localtime()))
            used_day, used = _reaction_meme_daily.get(session_key, (day, 0))
            if used_day != day:
                used = 0
            daily_max = int(getattr(meme_config, "bot_reactions_meme_daily_max", 6) or 6)
            if daily_max > 0 and used >= daily_max:
                return None
            picked, sticker_tags = select_sticker_for_turn(
                None, turn_text=text,
                reply_text=reply_text,
                session_key=session_key, sender_id=sender_id, config=meme_config,
                mood_valence_fn=lambda: _mood_valence(meme_config),
                affinity_snapshot=_poke_affinity_snapshot(meme_config, sender_id),
                pool_policy=sticker_send_routing.POOL_POLICY_PACKS_ONLY,
                pool_seed=f"reaction-meme:{session_key}:{message_id}",
                persona_albums=_persona_album_names(meme_config),
            )
            meme_path = str((picked or {}).get("path") or "").strip()
            if not meme_path:
                return None  # 池子挑不出＝不附，绝不端吸收池那张（与腿同一红线）。
            # 成了才记账：额度 +1（同一本）、登记互斥标（腿随后据此跳过，不双发）。
            _reaction_meme_daily[session_key] = (day, used + 1)
            _reaction_meme_merged[f"meme:{message_id}"] = meme_path
            while len(_reaction_meme_merged) > _REACTION_MEME_MERGED_MAX:
                _reaction_meme_merged.pop(next(iter(_reaction_meme_merged)), None)
            return meme_path, (
                "sticker_pack",
                "reaction_meme",
                f"intent:{intent}",
                *(
                    tag
                    for tag in sticker_tags
                    if str(tag).startswith("sticker_pool:")
                ),
            )
        except Exception:  # noqa: BLE001 - 贴纸钩子任何岔子都不许波及对话。
            logger.debug("sticker attach hook failed", exc_info=True)
            return None

    playwright_fetch_backend = None
    if getattr(config, "bot_fetch_playwright_enabled", True):
        try:
            from .domains.link_parse.fetchers import PlaywrightFetchBackend

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
    from .domains.media.ingest.vision_describe import build_vision_provider

    vision_provider = build_vision_provider(
        config,
        dynamic_registry=runtime_settings.list_vision_registry,
        settings_store=runtime_settings,
    )
    # 媒体归档存储：注册期单例（评审 I-4）——每消息重建实例会让实例级锁与
    # sha256 去重的 check-then-act 全部失效。关闭时不建（零开销）。
    from .domains.media.archive.media_archive import MediaArchiveStore

    media_archive_store = (
        MediaArchiveStore(
            config.bot_media_archive_db_path,
            config.bot_media_archive_dir,
        )
        if getattr(config, "bot_media_archive_enabled", True)
        else None
    )
    from .domains.media.ingest.transcribe import build_asr_provider

    asr_provider = build_asr_provider(
        config,
        settings_store=runtime_settings,
    )
    from .domains.media.registry.media_registry import build_media_registry

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
        # R-18 内容感知路由：verdict=INTIMATE 时自动候选序把 grok→gemini 提到
        # 最前（runtime/content_route.py；管理员显式 override 分支不受影响）。
        content_route_cb=_build_content_route_router_cb(
            _SHARED_CONTENT_ROUTE_ENGINE,
            lambda: _config_with_runtime_overrides(config, runtime_settings),
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
            content_route_config=_config_with_runtime_overrides(config, runtime_settings),
            interaction_counter=runtime_settings.interaction_increment,
            # NoneBot 自己按 BOT_MODEL_REGISTRY 的 priority 做直连故障转移。
            model_router=model_router,
            intent_telemetry=intent_telemetry,
            shadow_classifier_enabled=config.bot_web_classifier_shadow_enabled,
            web_search_enabled=config.bot_web_search_enabled,
            web_search_admin_notice=config.bot_web_search_admin_notice,
            web_knowledge_threshold=config.bot_web_search_knowledge_threshold,
            web_confidence_floor=config.bot_web_search_confidence_floor,
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
            model_prices=_assemble_model_prices(config, runtime_settings),
            max_tokens=config.bot_chat_max_tokens,
            model=config.bot_chat_model,
            context_preflight_errors=persona_context_preflight_errors(config),
            llm_preflight_errors=llm_generation_parameter_errors(config),
            output_max_chars_per_message=config.bot_reply_max_chars_per_message,
            generated_files_dir=str(getattr(config, "bot_generated_files_dir", "data/generated_files") or "data/generated_files"),
            # S2 案二（席位 W4R）：同消息附图钩子。每轮**现取**特性快照查询口
            # （`product_feature_gate.snapshot()` 是 `snapshot_async` 的同步真身，
            # 本钩子在 offload 线程里跑，取不到快照＝fail-closed 不附）。
            # 先例形参注入面：`content_route_cb=` / `mood_valence_fn=` / `feature_enabled=`。
            sticker_attach_hook=lambda **hook_kwargs: _sticker_attach_for_reply(
                feature_enabled=product_feature_gate.snapshot().enabled, **hook_kwargs
            ),
        )
    )
    # 语音自动配音（bot.tts）：把人格回复正文一并合成语音随消息发出。
    # 完整门链谓词判否（未启用 / 已在范围外 / 概率门落空）时 _attach_voice_reply
    # 直接短路，连线程调度都不付；未启用语音的部署与改动前逐字节一致。
    # G-3 双态：hook 键开=配音走 pipeline post-review enricher（上方已装配），
    # 此处不再包装；键关=旧包装路径原样。退役两步走的第二步（摘除本包装与
    # maybe_attach_voice/should_voice_reply 导入）等真机浸泡窗，见 report-T73。
    if pipeline_voice_enricher is None:
        chat_capability = _attach_voice_reply(chat_capability, config=config)

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

    async def _send_parts_through_unified_pipeline(
        bot: Bot,
        event: Event,
        *,
        text: str,
        image: str | None = None,
        audio: list[dict[str, Any]] | None = None,
        prefix_parts: list[dict[str, Any]] | None = None,
        audit_tags: list[str] | None = None,
        capability_id: str = "bot.poke",
    ) -> DeliveryReceipt:
        """带 @ 前置段/图片/语音的统一管线发送（poke v2 群聊 @+表情包；P14 语音臂）。

        走 mixed 渲染（prefix_parts 前置）；transport 不支持时按
        text_fallback 诚实降级（丢 @/图，不丢正文）。``audio`` 与 ``image`` 同
        一条出站面（``CapabilityResult.audio`` → renderer ``record`` 段，
        渲染契约既有链路，非第二通路）。
        """

        def _capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id=capability_id,
                kind="mixed" if (image or audio or prefix_parts) else "text",
                body=str(text or ""),
                images=[{"file": image}] if image else [],
                audio=[dict(item) for item in (audio or []) if isinstance(item, dict)],
                prefix_parts=list(prefix_parts or []),
                audit_tags=list(audit_tags or ["unified_parts_reply"]),
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

    async def _send_files_through_unified_pipeline(
        bot: Bot,
        event: Event,
        *,
        text: str = "",
        files: list[dict[str, Any]] | None = None,
        audit_tags: list[str] | None = None,
        capability_id: str = "bot.file",
    ) -> DeliveryReceipt:
        """文件件统一管线发送（S0 收编④，v21r4-b2-direct-collect-plan §3.4）。

        CapabilityResult.files → render media_parts → transport file 部件 →
        ``FileTransferGateway.stage/deliver``（B3 阶段 1 既有链；群=
        upload_group_file / 私聊=upload_private_file，平台方法面与旧直连一致）。
        """

        def _capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id=capability_id,
                kind="mixed" if files else "text",
                body=str(text or ""),
                files=[dict(item) for item in (files or []) if isinstance(item, dict)],
                audit_tags=list(audit_tags or ["unified_files_reply"]),
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

    from .domains.files.capabilities.file_exchange import (
        export_document,
        is_file_export_command,
        parse_file_export_command,
        run_code_debug,
    )

    async def _is_admin_origin(event: Event) -> bool:
        # K1B-G1（S-ATK-K1b，Important）：这里此前只把 `event.get_user_id()` 跟
        # QQ 管理员名单裸比——**平台域根本没进判定**，于是 Telegram 侧同号即可
        # 驱动 cookie 导入/登录、昵称设置（可指任意目标）、文件导出、群文件统计、
        # 文件通知五条腿。判定改走中央真身 `roles.is_admin_message`（内含
        # `platform_domain_of` 归一＋空域 fail-closed），与主链 resolve_roles 同
        # 一批平台串——不在此另立判据，也不扩第三口径。
        from types import SimpleNamespace

        from .domains.chat_reply.policy.roles import is_admin_message

        try:
            probe = SimpleNamespace(
                # NoneBot 基类 Event 上没有 get_platform（onebot/telegram 子类各有），
                # 静态面按基类判 ⇒ 用 getattr 取可调用再兜空串，行为与原先一致。
                platform=str(
                    getattr(event, "get_platform", lambda: "")() or ""
                ),
                sender_id=str(event.get_user_id()),
            )
        except Exception:  # noqa: BLE001 - 适配器实现差异：读不出即按普通用户。
            return False
        try:
            return bool(is_admin_message(config, probe))
        except Exception:  # noqa: BLE001 - 判定故障不外抛，fail-closed 按普通用户。
            return False

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

    # S34（2026-10-04）：消息编辑/撤回能力接线 —— /msg_mutation recall|edit。
    # 门缺省关（bot_message_mutation_enabled 没进 config 三面，本席不自行拨开）；
    # 出站走统一副作用执行器，方法名仍由 TransportRegistry 固定映射给（非第二通路）。
    from plugins.bot_unified_runtime.domains.transport import (
        message_mutation as _message_mutation,
    )

    _message_mutation.install_message_mutation(config)
    # 校园自动转发：学校账号（SnowLuma 第二实例）所在群消息被动监听。
    # block=False 绝不阻断其他 matcher；来源门外零开销返回；命中才落库
    # 并私聊转发，绝不向学校群发送任何消息。
    if campus_service is not None:

        async def _is_campus_group_message(event: Event) -> bool:
            return isinstance(event, GroupMessageEvent)

        campus_record_matcher = on_message(
            rule=_is_campus_group_message, priority=8, block=False
        )
        # U17：两 builder 在此函数级导入（模块顶部扩行会顶漂 matcher 坐标
        # 5027/打断 registry 坐标门）；handler 以裸名引用，AST 提取测试按
        # 全局名注入同名字缝，生产/测试两态等价。
        from .domains.assistant.campus.campus import (
            build_campus_forward_capability,
            build_campus_forward_message,
        )

        @campus_record_matcher.handle()
        async def _handle_campus_record(bot: Bot, event: Event) -> None:
            if not isinstance(event, GroupMessageEvent):
                return
            bot_id = str(getattr(bot, "self_id", "") or "")
            group_id = str(getattr(event, "group_id", "") or "")
            if not campus_service.matches(bot_id, group_id):
                return
            sender = getattr(event, "sender", None)
            sender_name = ""
            if sender is not None:
                sender_name = str(
                    getattr(sender, "card", "") or getattr(sender, "nickname", "") or ""
                )
            try:
                plain_text = event.get_plaintext().strip()
            except Exception:  # noqa: BLE001 - 适配器实现差异兜底。
                plain_text = ""
            payload = await asyncio.to_thread(
                campus_service.record,
                bot_id=bot_id,
                group_id=group_id,
                sender_id=str(event.get_user_id() or ""),
                sender_name=sender_name,
                text=plain_text,
                message_id=str(getattr(event, "message_id", "") or ""),
            )
            if payload is not None:
                # U17-CAMPUS-WIRE：出站收编中央管线（门禁/review/幂等/_complete
                # 统一入队），删除裸 send_queue.submit 旁路。纯监听语义零削弱：
                # 对学校群仍然只读，出站目标恒为主人私聊。
                message = build_campus_forward_message(campus_source, payload)
                capability = build_campus_forward_capability(campus_source, payload)

                async def _offload(
                    forward_message: IncomingMessage, decision: Any
                ) -> CapabilityResult:
                    # 本能力为纯格式化微任务，不走聊天线程池：直接在事件循环上
                    # 返回，绝不因池饱和吞转发（「来一条转一条」语义保持）。
                    return capability(forward_message, decision)

                async def _notify_campus_block(
                    blocked_message: Any, gate: str
                ) -> None:
                    # U17-FIX：BLOCK（review 泄拦/门禁停用/运行时暂停）不得完全
                    # 静默——该条 store 已记账、同 id 重放不再进管线（永久丢失）。
                    # 走既有运行时告警通道发一条可观测告警：只带 capability/
                    # 拦截类别/目标会话，绝不含源文本原文；best effort 不反噬监听。
                    issue = OperationalIssue(
                        stage="campus",
                        kind=f"blocked_{gate[:24]}",
                        severity=RiskLevel.MEDIUM,
                        safe_summary=(
                            "capability=bot.campus_forward session="
                            + str(
                                getattr(blocked_message, "session_id", "") or ""
                            )[:40]
                        ),
                    )
                    targets = _operational_alert_targets()
                    if not targets:
                        return
                    try:
                        await notify_operational_issue(
                            issue,
                            source_adapter=blocked_message.adapter,
                            source_bot=blocked_message.bot_id,
                            session_type=blocked_message.session_type,
                            targets=targets, pipeline=pipeline, capability_id="bot.campus_forward",
                            online_bots=_all_online_bots,
                            delivery=_deliver_admin_alert,
                            suppression=operational_alert_suppression,
                        )
                    except Exception:  # 告警侧路绝不反噬监听主链路。
                        logging.getLogger(__name__).debug(
                            "校园转发 BLOCK 告警投递失败", exc_info=True
                        )

                try:
                    receipt = await pipeline.handle_async(
                        message,
                        _offload,
                        capability_id="bot.campus_forward",
                    )
                except Exception:  # 转发失败不影响监听主链路。
                    logging.getLogger(__name__).exception("校园转发经中央管线失败")
                else:
                    if getattr(receipt, "state", None) is ReceiptState.BLOCKED:
                        gate = str(
                            getattr(receipt, "transport", "") or "unknown"
                        ).strip()
                        # 日志留痕：守岸人一句话，只带 capability/拦截类别/会话，
                        # 绝不含源文本原文（脱敏红线）。
                        logging.getLogger(__name__).warning(
                            "有一条校园消息因安全门未送达"
                            "（capability=bot.campus_forward gate=%s session=%s）",
                            gate,
                            getattr(message, "session_id", ""),
                        )
                        await _notify_campus_block(message, gate)

    # ==================== 紧急信息域接线（WIRE-B3，施工图 §4-面5 5b/5b-2/5c） ====================
    # 落点刻意放在 campus 块**之后**（文档旧坐标 :3738 之前）：根文件行号被
    # tests/test_campus_digest.py::test_outbound_registry_campus_coordinate_is_live
    # 按「live 行号 == 登记表坐标」实比（登记表坐标 = campus matcher 真身行），
    # 在它上方插任意一行都会顶漂该坐标、打断别人的常驻门（U17 批同源教训）。
    # 5b-2 中央出站闸单实例：真构造已上移至发送队列之后（见 `outbound_gate =`
    # 首次赋值处），此处只消费同一实例——闸必须先于紧急门（服务持 gate 引用）。
    emergency_service = None
    # 3.B 覆盖，2026-09-20）。投递目标改为**每轮现读** `emergency_subscriptions` 表：
    # 群里/私聊一句「紧急信息 订阅 …」即设立，不需要预先在 .env 填群号——第三腿若
    # 原样保留就是死结（没有名单⇒没有 matcher⇒订阅命令没人应答，永远订不起来）。
    # 「绝不猜群、绝不猜人」一寸没松，只是换了落点：表里没有行=零目标=零投递，
    # 而行只能由群主/管理员/超管亲手写下（能力层 `allows_emergency_subscription`）。
    # .env 两枚名单降级为可选硬推腿（无订阅过滤，缺省空=该腿不存在），见调度器侧。
    # 审核名单 reviewer_ids 不参与装配门：它空 ⇒ ReviewGate 无授权人 ⇒ 过审一律拒
    # （报料可入库、永远投不出去），这是刻意的安全缺省态，不是缺陷。
    # 闸缺位（`outbound_gate is None`）**不再关掉整条链**（2026-09-20 用户裁定 1.A）：
    # 查询面/采集/入库/审核都不需要出站闸，一起关会让"只想查不想推"的用法死掉。
    # 但闸缺位时**一条都不投**——投递点显式跳过并留痕，绝不退化成不经闸的裸投递（钉死③不变）。
    emergency_service = None
    # 5a 的顶层 import（施工图原文）在本席改为函数体内 import，理由与 campus/U17 同一
    # 条坐标门；要挪回模块顶部必须同批改登记表坐标，逐字 diff 见 report §落地请求。
    from .domains.emergency_info.capabilities.emergency_info import (
        build_emergency_info_source,
    )

    emergency_source = build_emergency_info_source(config)
    if emergency_source.enabled and emergency_source.sources:
        from .domains.emergency_info.capabilities.emergency_info import (
            EmergencyInfoService,
            build_emergency_info_capability,
            build_review_gate,
        )
        from .domains.emergency_info.sources.store import build_emergency_store

        # WIRE-L2：D-8(a) 生产真生效——装配期构造带 authorizer + 权威源白名单
        # 双门的 ReviewGate 并注入（两枚旋钮同源于 `emergency_source` 快照，
        # 域内零直接读 config 对象）。名单空 ⇒ 逐字节维持既有 pending 行为。
        emergency_store = build_emergency_store(
            str(config.bot_emergency_info_db_path)
        )
        emergency_service = EmergencyInfoService(
            store=emergency_store,
            source=emergency_source,
            gate=outbound_gate,
            review_gate=build_review_gate(emergency_store, emergency_source),
        )

        # 5c matcher 三件套。变量名必须等于 RouteKind 值 `emergency_info`——
        # tests/test_emergency_info_push.py 的双钉一致性门按「根 matcher 变量名 ==
        # RouteKind 值」配对，换个名就变成未登记盲区（那张登记表不许静默扩）。
        async def _is_emergency_info_event(state: T_State, event: Event) -> bool:
            return (
                _cached_route_decision(state, event, config=config).kind
                is RouteKind.EMERGENCY_INFO
            )

        # priority=44 与 ROUTE_RULES 里 RouteRule(RouteKind.EMERGENCY_INFO, ..., 44, ...)
        # 是同值双钉：任一侧单独改动即红（本席已把 A2 的探测器翻成正向锁并注毒复验）。
        emergency_info = on_message(
            rule=_is_emergency_info_event, priority=44, block=True
        )

        def _build_emergency_info_with_backend(
            config_: Any, **_kwargs: Any
        ) -> Any:
            return build_emergency_info_capability(
                config_, render_backend=render_backend
            )

        @emergency_info.handle()
        async def _handle_emergency_info(bot: Bot, event: Event) -> None:
            await _run_simple_capability(
                bot,
                event,
                _build_emergency_info_with_backend,
                "bot.emergency_info",
                emergency_info,
            )

        # 5d 采集轮询调度器：域内不 import APScheduler，调度句柄由根装配传入；
        # apscheduler 缺失只关自动采集（读侧命令仍在），不崩整个插件装载。
        try:
            from nonebot_plugin_apscheduler import (
                scheduler as _emergency_scheduler,
            )
        except Exception:  # noqa: BLE001 - 与既有调度器注册同款容错。
            _emergency_scheduler = None
        if _emergency_scheduler is not None:
            # 事故缓解（2026-09-21 修复波已复原）：紧急信息波 WP3 在飞半成品曾令
            # push.py 引 grading.may_breach_quiet_window 直接 ImportError，拖垮插件加载。
            # 该包装现已落在 grading.py（判据真身在 alert_taxonomy，非第二实现），故本块
            # 恢复 WIRE-B3 原设计语义；try/except 保留为常规 fail-open——装配抛异常只跳过
            # 紧急域调度（主链路照常），并把异常原文打进日志，不静默、不炸整机装载。
            try:
                _register_emergency_info_scheduler(
                    _emergency_scheduler,
                    config,
                    emergency_service,
                    send_queue,
                    outbound_gate,
                )
            except Exception:
                # logging 只用模块级那一枚——函数体内再 import 会遮蔽它，后段按全局读即 UnboundLocalError

                logging.getLogger(__name__).exception(
                    "emergency_info 调度器注册失败，已跳过（主链路不受影响；待紧急波补 grading.may_breach_quiet_window）"
                )

    # >>> WP10-SYNC-DRIFT-WIRING BEGIN（哨兵配对：自证门 tests/test_sync_drift_activation.py
    # 按这对哨兵把本块**真身文本**抽出来注入假 scheduler 执行——活性判据，不是 grep 存在性）
    # 一致性漂移巡检装配（2026-09-21 全面修复波裁定 12.A「救活 sync_drift」）：周期复算
    # 「文档/配置/触发词 ↔ 代码真身」是否仍相等，漂移则 QQ/TG/Mail 三通道报超管。
    # 三道闸（enabled ∧ 有超管 ∧ scheduler）全在 install() 内部，这里**故意不重复判
    # enabled**：判两遍等于给「摘掉任一道闸」留盲区。缺省 bot_sync_drift_alert_enabled
    # =False ⇒ install() 第一道闸就返回，连 job 都不注册（零读盘、零网络、零告警）。
    # 落点刻意在 campus matcher **之下**、与紧急域调度器同区：根文件行号被
    # tests/test_campus_digest.py 按「live 行号 == 登记表坐标」实比，在它上方插任意一行
    # 都会顶漂别人的常驻门（同上方 WIRE-B3 落点注释与 U17 批同源教训）。
    try:  # fail-open：apscheduler 缺失或装配抛异常都只落一行日志，绝不炸插件加载。
        from nonebot_plugin_apscheduler import scheduler as _sync_drift_scheduler

        if _sync_drift_scheduler is not None:
            from plugins.bot_unified_runtime.domains.ops.sync_drift import (
                install as _install_sync_drift_patrol,
            )

            _install_sync_drift_patrol(
                scheduler=_sync_drift_scheduler,
                config=config,
                pipeline=pipeline,
                online_bots=_all_online_bots,
            )
    except Exception:  # 巡检是运维附属面，坏了不能把主链路一起拖下水（fail-open）。
        # logging 只用模块级那一枚：函数体内再 import 会遮蔽它，令后段按全局读它的点炸。

        logging.getLogger(__name__).exception(
            "sync_drift 一致性漂移巡检装配失败，已跳过（主链路不受影响）"
        )
    # <<< WP10-SYNC-DRIFT-WIRING END

    file_notice = on_notice(rule=_is_admin_file_notice, priority=8, block=False)

    # 统一戳一戳分发：OneBot 适配器只做事件归一与执行，门控/话术/回戳
    # 意图全部收敛在 capabilities.poke.PokeDispatcher（未来其他适配器同构复用）。
    from .domains.chat_reply.capabilities.poke import PokeDispatcher, resolve_poke_reply
    _poke_dispatcher = PokeDispatcher(clock=time.monotonic)
    # V21-DISPATCH-001（风险 5 收口）：回戳等平台副作用改走统一出站面——
    # OutboundIntent（严格 DTO）→ 准入复验 → 许可租约线性化 → Transport 固定
    # 映射（绝不拼 API 名）→ bot.call_api 通道本体（与 SendQueue worker 同
    # 通道，非第二出站通道）。平台不支持/同键在途时诚实回执、静默降级，
    # 与旧直连行为等价（失败不影响话术回复）。
    from .control_plane.dispatcher import (
        OutboundSideEffectExecutor,
        PokeInteractionService,
        build_interaction_dispatcher,
    )
    from .domains.core.decision.outbound import (
        OutboundIntent,
        OutboundOperation,
        OutboundPart,
        OutboundTarget,
        build_default_transport_registry,
        derive_dedupe_key,
    )

    _poke_side_effect_executor = OutboundSideEffectExecutor(
        transport_registry=build_default_transport_registry(),
    )

    def _build_poke_back_intent(payload: dict[str, Any]) -> OutboundIntent:
        """poke 载荷 → 回戳/跟戳/主动戳 OutboundIntent（参数 coercion 与旧直连一致）。

        ``purpose``（P14 波新增，缺省 ``back``）只进幂等键与 trace 前缀，把
        「回戳」「跟戳」「说完顺手戳一下」三种动机分开记账——同一 (群,人) 的
        一次回戳不该把之后的主动戳吞成「同键在途」。五层门与冷却仍归调用方
        （``ProactiveGate`` / ``PokeLimiter``）所有，本件只做在途线性化。
        """
        group = bool(payload.get("group"))
        group_id = int(payload.get("group_id") or 0)
        user_id = int(payload.get("user_id") or 0)
        purpose = str(payload.get("purpose") or "back").strip() or "back"
        api_params = (
            {"group_id": group_id, "user_id": user_id}
            if group
            else {"user_id": user_id}
        )
        dedupe_key = derive_dedupe_key(
            "qq",
            f"pokeback.{purpose}.{'group' if group else 'private'}.{group_id}.{user_id}",
            "direct",
        )
        return OutboundIntent(
            operation=OutboundOperation.POKE,
            target=OutboundTarget(
                platform="qq",
                session_type="group" if group else "private",
                target_id=str(group_id if group else user_id),
                bot_id=str(payload.get("bot_id") or ""),
                adapter="onebot",
            ),
            parts=[
                OutboundPart(
                    part_id=f"poke-back:{dedupe_key}",
                    kind="poke",
                    content_ref={"api_params": api_params},
                )
            ],
            feature_id="bot.plugin.poke.poke_back",
            policy_revision="legacy-poke-v2",
            dedupe_key=dedupe_key,
            trace_id=f"pokeback-{purpose}-{time.time_ns()}",
        )

    _poke_interaction_service = PokeInteractionService(
        dispatch=build_interaction_dispatcher(
            _poke_side_effect_executor,
            route_intent=_build_poke_back_intent,
        )
    )

    async def _dispatch_poke_back(bot: Bot, event: Event, *, group: bool) -> bool:
        """回戳经中央门面派发（route→review→send 真实周期）。

        返回「是否真送出」（``delivered``）；失败/平台不支持诚实报否，调用方
        据此决定是否退回话术腿。异常一律按「未送出」处理，绝不假成功。
        """
        return await _dispatch_poke_at(
            bot,
            group=group,
            group_id=getattr(event, "group_id", 0),
            user_id=getattr(event, "user_id", 0),
            bot_id=str(getattr(bot, "self_id", "") or ""),
        )

    async def _dispatch_poke_at(
        bot: Bot,
        *,
        group: bool,
        group_id: Any = 0,
        user_id: Any,
        bot_id: str = "",
        purpose: str = "back",
    ) -> bool:
        """戳人的唯一出口（回戳/跟戳/说完顺手戳都走这里，同一中央门面）。"""
        try:
            result = await _poke_interaction_service.handle(
                {
                    "bot": bot,
                    "bot_id": bot_id or str(getattr(bot, "self_id", "") or ""),
                    "group": group,
                    "group_id": group_id,
                    "user_id": user_id,
                    "purpose": purpose,
                }
            )
        except Exception:  # noqa: BLE001 - 戳人是增益动作，坏了不影响主链路。
            return False
        return bool(getattr(result, "delivered", False))
    # poke v2 好感度防刷：每 (会话, 戳者) 每日累计记账——进程内字典仅作快路径
    # （按申请额保守记账），持久防刷以 affinity_delta_log（source="poke" 的
    # 24h 滚动和 + 全局预算）为准：重启后字典清零，但 store 侧仍受 24h 上限约束。
    _poke_affinity_daily: dict[tuple[str, str], tuple[int, float]] = {}

    def _poke_affinity_snapshot(poke_config: Any, sender_id: str) -> dict[str, Any] | None:
        """对方的好感档快照（口味/档号喂选图门面）；拿不到一律 None（= 不参与口味加权）。"""
        if not str(sender_id or "").strip():
            return None
        try:
            store = build_character_affinity_store(poke_config)
            if store is None:
                return None
            snapshot = store.snapshot(str(sender_id))
            return snapshot if isinstance(snapshot, dict) else None
        except Exception:  # noqa: BLE001 - 口味层失败不影响发不发表情包。
            return None

    def _persona_album_names(pconfig: Any) -> tuple[str, ...]:
        """现役人格的**册名候选**（展示名在前、人格 id 垫后；人格分册 2026-09-29）。

        每轮现算不留快照：``active_persona_id`` 的既有序（runtime 切换态 → 配置
        主人格档）＋ ``current_bot_nickname`` 的取名单口（人格册 → 配置回落）。
        任何异常都折回配置展示名——册名取不到 ≠ 人格没了；两条腿（P3 / 戳一戳）
        靠它把「只能发现役人格册里的表情包」钉死，判据真身在
        ``sticker_packs.persona_album_root``（缺册＝诚实缺席，绝不回落基根）。
        """
        names: list[str] = []
        try:
            from .domains.chat_reply.character.persona_profile import (
                active_persona_id,
                current_bot_nickname,
            )

            pid = active_persona_id(pconfig)
            names.append(current_bot_nickname(pid, config=pconfig))
            names.append(pid)
        except Exception:  # noqa: BLE001 - 取不到现役人格 ≠ 不发：折回配置展示名。
            names.append(str(getattr(pconfig, "bot_persona_display_name", "") or ""))
        out: list[str] = []
        for raw in names:
            name = str(raw or "").strip()
            if name and name not in out:
                out.append(name)
        return tuple(out)

    def _pick_poke_meme(
        store: Any,
        poke_config: Any,
        *,
        session_key: str = "",
        sender_id: str = "",
        group_id: str = "",
        feature_enabled: Any = None,
    ) -> str | None:
        """戳一戳 ``meme`` 臂选图：**只准**从管理员登记的贴纸池拿（S-STICKER-POOLS）。

        2026-09-29 换池：这一臂此前与被 P3 缺陷清单点名的吸收池（``bot_meme_library_dir``
        = 别人群里偷来的截图）同盘。现以 ``pool_policy=packs_only`` 走门面
        ``select_sticker_for_turn``，门面内部只问 ``sticker_packs.pick_sticker``；
        挑不出＝返回 ``None`` → 调用方 ``resolve_poke_reply`` 落回 ``fixed_text``
        固定话术。**绝不回退吸收池**——宁可回一句话，也不把群聊截图甩给戳的人。
        （旧形态"选不出回退固定话术"本来就是这条臂的正确退路，本波只是把
        "回退"从"退到另一张不该发的图"钉成"退到不发表情包"。）

        三道硬门同样在这条臂上生效（缺一道就 ``None``＝只回话术，不改判、不吞回复）：
        ``bot.plugin.sticker_packs`` 特性门 / blocked 名单 / 安静时间。
        ``store`` 形参在 ``packs_only`` 下**不参与选图**（库腿被排除），保留只为
        调用点与既有替身的形状不变。
        """
        from .domains.meme.capabilities.meme_library import select_sticker_for_turn
        from .domains.meme.sources import sticker_send_routing

        if not sticker_send_routing.sticker_feature_enabled(feature_enabled):
            return None
        if not sticker_send_routing.social_gates_allow(
            poke_config, group_id=group_id, user_id=sender_id
        ):
            return None
        try:
            picked, _tags = select_sticker_for_turn(
                store,
                turn_text="",  # 戳一戳没有随行的那句话：主题腿只吃既有词表，不硬凑。
                session_key=session_key,
                sender_id=sender_id,
                config=poke_config,
                mood_valence_fn=lambda: _mood_valence(poke_config),
                affinity_snapshot=_poke_affinity_snapshot(poke_config, sender_id),
                pool_policy=sticker_send_routing.POOL_POLICY_PACKS_ONLY,
                pool_seed=f"poke-meme:{session_key}:{sender_id}",
                persona_albums=_persona_album_names(poke_config),
            )
        except Exception:  # noqa: BLE001 - 选图失败回退固定话术。
            return None
        if not picked:
            return None
        path = str(picked.get("path") or "").strip()
        return path or None

    def _record_poke_affinity(
        poke_config: Any, poker_id: str, group_id: str
    ) -> str:
        """好感度小额正向记账；返回定性态度文本（LLM 提示词用），不显数值。

        V2.1 §2.2/§2.3：配置值语义=展示「分」，经 observe_points 唯一适配器
        ÷100 转内部值（治旧缺陷：0.5 分被当内部值直传 → 一戳 +50 分）；
        过全局滚动预算 + poke 来源专项 24h 预算（source_cap_24h_points=
        daily_max），持久防刷不依赖进程内字典。
        """
        try:
            if not bool(getattr(poke_config, "bot_poke_affinity_enabled", True)):
                return ""
            # D-2：两枚兜底原写 0.5 / 5.0，与 config.py 真身缺省（0.1 / 0.5）不一致——
            # 字段装载时永远走不到兜底，故生产行为今日不变；但字段一旦缺失就静默按
            # 错值走。对齐真身是锁的直接判据（反向让根兜底牵着真身走＝禁）。
            points = float(getattr(poke_config, "bot_poke_affinity_delta", 0.1) or 0.1)
            daily_max = float(
                getattr(poke_config, "bot_poke_affinity_daily_max", 0.5) or 0.5
            )
            if points <= 0 or daily_max <= 0:
                return ""
            day = int(time.strftime("%Y%m%d", time.localtime()))
            key = (str(group_id or "private"), poker_id)
            used_day, used = _poke_affinity_daily.get(key, (day, 0.0))
            if used_day != day:
                used = 0.0
            if used >= daily_max:
                return ""
            grant = min(points, daily_max - used)
            # 快路径按申请额记账（store 侧若因全局预算少放，字典只会更早拦，
            # 保守方向不放大增益）。
            _poke_affinity_daily[key] = (day, used + grant)
            store = build_character_affinity_store(poke_config)
            store.observe_points(
                poker_id,
                points=grant,
                behavior="positive",
                source="poke",
                source_cap_24h_points=daily_max,
                group_id=group_id or None,
            )
            snapshot = store.snapshot(poker_id)
            if isinstance(snapshot, dict):
                return str(snapshot.get("attitude") or "")
            return ""
        except Exception:  # noqa: BLE001 - 好感度记账失败绝不影响回复。
            return ""

    async def _poke_llm_reply(
        poke_config: Any,
        *,
        is_group: bool,
        attitude_hint: str,
    ) -> str:
        """LLM 话术：紧凑提示词（守岸人语气+戳一戳语境+好感档定性），12s 超时。"""
        if model_router is None:
            return ""
        system_prompt = (
            "你是守岸人。有人刚刚在QQ上戳了你一下。用一句不超过40字的中文回应："
            "温和、亲近、带一点被戳到的真实反应；不要长篇大论，不要用emoji符号，"
            "不要提及任何系统、规则或这段要求本身。"
        )
        user_prompt = f"{'群聊' if is_group else '私聊'}里有人戳了你一下。"
        if attitude_hint.strip():
            user_prompt += f"你们当前的关系氛围：{attitude_hint.strip()}。"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            reply = await asyncio.wait_for(
                asyncio.to_thread(
                    model_router.generate,
                    messages,
                    message_text="poke",
                    fast_mode=True,
                    max_tokens=80,
                ),
                timeout=12.0,
            )
            return str(getattr(reply, "text", "") or "").strip()
        except Exception:  # noqa: BLE001 - LLM 话术失败回退固定话术。
            return ""

    async def _is_poke_event(event: Event) -> bool:
        return str(getattr(event, "notice_type", "")) == "notify" and str(getattr(event, "sub_type", "")) == "poke"

    # ---------------------------------------------------- P14 波：社交主动接触
    # 三枚五层门各记各的账（跟戳 / 回复后戳 / 回复后随机发图），互不共享冷却与
    # 每小时滑窗；门的判据（开关→有目标→blocked→安静时间→概率/冷却/滑窗）唯一
    # 真身在 capabilities.poke.proactive_action_allowed，本处只做取数与投递。
    _POKE_FOLLOW_GATE = _ReactionProactiveGateClass()
    _POKE_AFTER_REPLY_GATE = _ReactionProactiveGateClass()
    _RANDPIC_DISPATCH_GATE = _ReactionProactiveGateClass()

    async def _maybe_follow_poke(
        bot: Bot, event: Event, *, merged_config: Any, poke_back_on: bool
    ) -> None:
        """「A 戳 B」→ bot 有概率跟着戳 B（P14；缺省关）。

        独立门身（``bot_poke_follow_*``），与回戳分账：QQ 戳本身不花钱，但连戳
        极刷屏，所以每群冷却 + 每小时上限 + 每消息去重三重都要在。
        """
        if not poke_back_on or merged_config is None:
            return
        if not bool(getattr(merged_config, "bot_poke_follow_enabled", False)):
            return
        from .domains.chat_reply.capabilities.poke import resolve_poke_follow_target

        target = resolve_poke_follow_target(
            event, bot_id=str(getattr(bot, "self_id", "") or "")
        )
        if target is None:
            return
        from .domains.chat_reply.capabilities.poke import (
            ProactiveActionKnobs,
            proactive_action_allowed,
            proactive_poke_candidates,
        )

        # 可投候选：先被戳者 B，B 不可戳（blocked 名单/空号/是 bot 自己）才退 A。
        # 名单判定必须在门之前——ProactiveGate 是 commit 语义，门过了才发现
        # 目标不该戳，等于白烧一次冷却与每小时额度。
        candidates = proactive_poke_candidates(
            merged_config, target, bot_id=str(getattr(bot, "self_id", "") or "")
        )
        if not candidates:
            return
        # M-17 中央名单门（互动面波 2026-10-03）：群没在 content-route 名单里表过态
        # （黑名单永远赢；白名单空=整体关；戳 bot 的对象在私聊白名单⇒人腿放行）
        # ⇒ 不跟戳。名单是无副作用读，必须仍排在五层门（commit 语义）之前——
        # 「先名单后骰」；被动被戳路径不经本腿、行为零变化。
        from .domains.chat_reply.runtime.content_route import (
            explicit_allowed_for_session,
        )

        if not explicit_allowed_for_session(
            "group", target.group_id, merged_config, sender_id=candidates[0]
        ):
            return
        if not proactive_action_allowed(
            merged_config,
            prefix="bot_poke_follow_",
            gate=_POKE_FOLLOW_GATE,
            session_key=f"group_{target.group_id}_{candidates[0]}",
            message_key=f"poke-follow:{target.poker_id}:{target.group_id}",
            group_id=target.group_id,
            user_id=candidates[0],
            salt="poke-follow",
            require_group=True,
            # 四枚同族键按**字面键名**在此取数（门身不再动态拼名）：值路径不变，
            # 变的是「可归枚的读点」——动态 f"{prefix}probability" 让配置登记总账
            # 的直读尺看不见这枚键，11 枚 poke/randpic 键因此被记成零读点死键。
            knobs=ProactiveActionKnobs(
                enabled=bool(getattr(merged_config, "bot_poke_follow_enabled", False)),
                probability=float(
                    getattr(merged_config, "bot_poke_follow_probability", 0.2) or 0.2
                ),
                cooldown_seconds=float(
                    getattr(merged_config, "bot_poke_follow_cooldown_seconds", 120.0)
                    or 120.0
                ),
                max_per_hour=int(
                    getattr(merged_config, "bot_poke_follow_max_per_hour", 4) or 4
                ),
            ),
        ):
            return
        for candidate in candidates:
            # 第一发真送出就停：绝不同时戳两个（那又是「一次事件两臂」）。
            if await _dispatch_poke_at(
                bot,
                group=True,
                group_id=target.group_id,
                user_id=candidate,
                bot_id=str(getattr(bot, "self_id", "") or ""),
                purpose="follow",
            ):
                return

    async def _maybe_poke_after_bot_spoke(
        bot: Bot,
        *,
        merged_config: Any,
        poke_back_on: bool,
        group_id: str,
        user_id: str,
        message_key: str,
        purpose: str,
    ) -> None:
        """bot 说完话（回复用户 / 群内主动接话 / 入群欢迎）后按概率戳一下对方。

        新增出站动作，三道硬门前置：blocked 名单、安静时间窗、每会话五层门；
        任一不过就一条都不戳。投递仍走回戳那**同一个**中央门面（
        ``_dispatch_poke_at`` → ``PokeInteractionService`` → 出站准入/租约/固定
        映射），绝不另开第二条戳人路。
        """
        if not poke_back_on or merged_config is None:
            return
        from .domains.chat_reply.capabilities.poke import (
            ProactiveActionKnobs,
            proactive_action_allowed,
        )

        group = bool(str(group_id or "").strip())
        # M-17 中央名单门（互动面波 2026-10-03，判据同跟戳腿）：群表态不过=不戳；
        # 先名单后骰（名单无副作用读，五层门是 commit 语义）。``if group and …``：
        # 私聊场合名单门不参与——那一路本就被 require_group 拦下，行为逐字节不变。
        if group:
            from .domains.chat_reply.runtime.content_route import (
                explicit_allowed_for_session,
            )

            if not explicit_allowed_for_session(
                "group", group_id, merged_config, sender_id=user_id
            ):
                return
        if not proactive_action_allowed(
            merged_config,
            prefix="bot_poke_after_reply_",
            gate=_POKE_AFTER_REPLY_GATE,
            session_key=(
                f"group_{group_id}_{user_id}" if group else f"private_{user_id}"
            ),
            message_key=f"poke-spoke:{purpose}:{message_key}",
            group_id=group_id,
            user_id=user_id,
            salt=f"poke-spoke-{purpose}",
            # 字面键名取数（与跟戳同一改判据）：见 ProactiveActionKnobs 的 why。
            knobs=ProactiveActionKnobs(
                enabled=bool(
                    getattr(merged_config, "bot_poke_after_reply_enabled", False)
                ),
                probability=float(
                    getattr(merged_config, "bot_poke_after_reply_probability", 0.15)
                    or 0.15
                ),
                cooldown_seconds=float(
                    getattr(
                        merged_config, "bot_poke_after_reply_cooldown_seconds", 300.0
                    )
                    or 300.0
                ),
                max_per_hour=int(
                    getattr(merged_config, "bot_poke_after_reply_max_per_hour", 3) or 3
                ),
            ),
            # 主动戳人只在群消息里成立：QQ 私聊 poke 通道名虽在册（outbound_registry
            # 的 friend_poke），但「名称在册」≠「协议端实装」，本波离线拿不到实测
            # 证据，故按「未证实即不放开」收在群内（先例=主动贴表情私聊不派发）。
            require_group=True,
        ):
            return
        spoke_poke_delivered = await _dispatch_poke_at(
            bot,
            group=group,
            group_id=group_id if group else 0,
            user_id=user_id,
            bot_id=str(getattr(bot, "self_id", "") or ""),
            purpose=f"spoke-{purpose}",
        )
        if spoke_poke_delivered:
            # 同轮三腿互斥：真戳到了才占坑，randpic 腿据此让位（P3 贴纸先发出时
            # 本腿已被调用点的占坑查询短路，到不了这里）。
            _turn_attachment_mark(message_key, "poke_after_reply")

    async def _poke_voice_pair(
        bot: Bot, event: Event, *, text: str, merged_config: Any, switches: Any = None
    ) -> tuple[str, list[dict[str, Any]]]:
        """语音臂取数：交语音能力本体，本处零合成逻辑（禁第二通路）。

        复用 ``bot.tts`` 命令能力（``build_tts_capability``）——它本来就产
        「文本+语音」一个结果，念出的那串字与语音互相印证。事件是 notice，
        摄取层对 NoticeEvent 族按空文本降级，故这里把要念的话经
        ``model_copy`` 贴进同一份会话事实（会话/群/发送者一律沿用，policy 门与
        名单门照原样生效）。拿不到音频=只留文本腿（合成失败/引擎未启/被政策
        拦下都归这一态，绝不为凑语音编内容）。
        """
        if not str(text or "").strip():
            return "", []
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "") or ""),
            adapter_name="onebot",
            # 细分开关快照照传（与全树其余摄取调用点同一约定：漏传=绕过层 2 门）。
            feature_enabled=(
                switches.enabled if switches is not None else None
            ),
        )
        from .domains.media.capabilities.tts import (
            build_tts_capability,
            effective_trigger_words,
        )

        trigger = (effective_trigger_words(getattr(merged_config, "bot_tts_trigger_words", ()) or ()) or ["说"])[0]
        spoken = message.model_copy(
            update={"plain_text": f"{trigger} {str(text).strip()}"}
        )
        try:
            from .runtime.capability_protocols import orchestrated_command
            step = orchestrated_command("bot.tts", build_tts_capability(merged_config), merged_config)  # 语音臂执行步交层 2 主缝（S-SEAM-FOLLOW-c 收编：直呼 builder→seam-feed 喂缝）
            result = await asyncio.to_thread(step, spoken, None)
        except Exception:  # noqa: BLE001 - 语音是增益：拿不到就只发文字。
            return str(text).strip(), []
        audio = [item for item in (getattr(result, "audio", []) or []) if isinstance(item, dict)]
        if not audio:
            return str(text).strip(), []
        body = str(getattr(result, "body", "") or "").strip()
        return (body or str(text).strip()), audio

    async def _maybe_dispatch_randpic(
        bot: Bot,
        event: Event,
        *,
        merged_config: Any,
        session_key: str,
        message_key: str,
        group_id: str,
        user_id: str,
    ) -> None:
        """回复完用户消息后按概率发一张随机图（P14 三触发里的自动腿）。

        取图只走 randpic 能力自己那条读目录路径（``pick_gallery_image``），
        与指令路共用同一本「窗内不重发」账；门身共用 ``proactive_action_allowed``
        （blocked 名单 + 安静时间 + 五层门）。图库未配置/为空/整库都在窗内 ⇒
        一条都不发（主动动作宁缺不刷屏），绝不退化成发重复图。
        """
        if merged_config is None:
            return
        from .domains.chat_reply.capabilities.poke import (
            ProactiveActionKnobs,
            proactive_action_allowed,
        )

        if not proactive_action_allowed(
            merged_config,
            prefix="bot_randpic_dispatch_",
            gate=_RANDPIC_DISPATCH_GATE,
            session_key=session_key,
            message_key=f"randpic:{message_key}",
            group_id=group_id,
            user_id=user_id,
            salt="randpic-dispatch",
            # 字面键名取数（与 poke 两族同判据）：见 ProactiveActionKnobs 的 why。
            knobs=ProactiveActionKnobs(
                enabled=bool(getattr(merged_config, "bot_randpic_dispatch_enabled", False)),
                probability=float(
                    getattr(merged_config, "bot_randpic_dispatch_probability", 0.1) or 0.1
                ),
                cooldown_seconds=float(
                    getattr(merged_config, "bot_randpic_dispatch_cooldown_seconds", 600.0)
                    or 600.0
                ),
                max_per_hour=int(
                    getattr(merged_config, "bot_randpic_dispatch_max_per_hour", 2) or 2
                ),
            ),
        ):
            return
        picked = await asyncio.to_thread(
            pick_gallery_image,
            merged_config,
            session_key=session_key,
            seed=f"randpic-dispatch:{session_key}:{message_key}",
            allow_exhausted=False,
        )
        if picked is None:
            return
        randpic_receipt = await _send_parts_through_unified_pipeline(
            bot,
            event,
            text="",
            image=str(picked),
            audit_tags=["randpic", "dispatch", "trigger:after_reply"],
            capability_id="bot.randpic",
        )
        if getattr(randpic_receipt, "state", None) in {ReceiptState.SENT, ReceiptState.REDIRECTED}:
            # 本腿是三腿链最后一环：占坑只为账面完整（同轮再无后腿可让位），
            # 也防未来有人在链尾追加第四腿时漏接互斥。
            _turn_attachment_mark(message_key, "randpic_dispatch")

    poke_notice = on_notice(rule=_is_poke_event, priority=7, block=False)

    @poke_notice.handle()
    async def _handle_poke_notice(bot: Bot, event: Event) -> None:
        switches = await product_feature_gate.snapshot_async()
        if not switches.enabled("bot.plugin.poke"):
            return
        merged_poke_config = _config_with_runtime_overrides(config, runtime_settings)
        poke_back_on = switches.enabled("bot.plugin.poke.poke_back")
        reaction = _poke_dispatcher.build_poke_reaction(
            event,
            bot_id=str(getattr(bot, "self_id", "")),
            config=merged_poke_config,
            poke_back_available=bool(poke_back_on),
        )
        if reaction is None or not reaction.active:
            # 这一发不是戳机器人自己（或已被冷却/概率拦下）→ 跟戳那条腿。
            await _maybe_follow_poke(
                bot, event, merged_config=merged_poke_config, poke_back_on=poke_back_on
            )
            return
        poker_id = str(getattr(event, "user_id", "") or "").strip()
        poker_group = str(getattr(event, "group_id", "") or "").strip()
        poke_delivered = False
        if reaction.poke_back and switches.enabled("bot.plugin.poke.poke_back"):
            # 回戳：统一出站面（V21-DISPATCH-001：OutboundIntent→准入→租约→
            # 固定映射→通道本体）；平台不支持/同键在途时诚实回执静默降级
            # （与旧 call_api 直连行为等价：失败不影响话术回复）。
            poke_delivered = await _dispatch_poke_back(bot, event, group=bool(reaction.group))
        if reaction.mode == "poke" and poke_delivered:
            # 「只回戳」这条臂已经表达完了，不再叠话术（「回复只回一个」）。
            return
        if not (reaction.reply and switches.enabled("bot.plugin.poke.reply")):
            return
        # poke v2：按形态组装单一回复（llm 失败/meme 库空 → 固定话术回退）；
        # 群聊回复自动 @ 戳者；好感度小额正向记账（定性信息喂 LLM 提示词）。
        attitude_hint = ""
        if poker_id:
            def _affinity_job() -> str:
                return _record_poke_affinity(
                    merged_poke_config,
                    poker_id,
                    poker_group,
                )

            attitude_hint = await asyncio.to_thread(_affinity_job)
        llm_text = ""
        meme_path = None
        randpic_path = None
        if reaction.mode in ("llm", "voice"):  # 语音臂的文本腿也要走 LLM（第 14 项「语音+自然语言文本」）
            llm_text = await _poke_llm_reply(
                merged_poke_config,
                is_group=reaction.group,
                attitude_hint=attitude_hint,
            )
        elif reaction.mode == "meme":
            meme_path = await asyncio.to_thread(
                _pick_poke_meme,
                meme_library_store,
                merged_poke_config,
                session_key=(
                    f"group_{poker_group}_{poker_id}"
                    if reaction.group
                    else f"private_{poker_id}"
                ),
                sender_id=poker_id,
                group_id=poker_group,
                feature_enabled=switches.enabled,
            )
        elif reaction.mode == "randpic":
            randpic_path = await asyncio.to_thread(
                pick_gallery_image,
                merged_poke_config,
                session_key=(
                    f"group_{poker_group}"  # 与 get_session_id 同形（票②）
                    if reaction.group
                    else f"private_{poker_id}"
                ),
                seed=f"poke-randpic:{poker_id}:{poker_group}",
                allow_exhausted=False,
            )
        reply_text, image = resolve_poke_reply(
            reaction.mode,
            fixed_text=reaction.reply,
            llm_text=llm_text or None,
            meme_path=meme_path,
            randpic_path=str(randpic_path) if randpic_path else None,
        )
        audio_parts: list[dict[str, Any]] = []
        if reaction.mode == "voice" and reply_text:
            reply_text, audio_parts = await _poke_voice_pair(
                bot,
                event,
                text=reply_text,
                merged_config=merged_poke_config,
                switches=switches,
            )
        elif reaction.mode == "poke":
            # 走到这里=回戳派发失败（平台不支持/同键在途/被拦）→ 温和回退固定
            # 话术。绝不允许「选了只回戳结果会话里什么都没发生」这种静默空回。
            reply_text = reaction.reply
        if not (reply_text or image or audio_parts):
            return
        prefix_parts = (
            [{"type": "at", "qq": poker_id}]
            if reaction.group and poker_id
            else []
        )
        poke_receipt = await _send_parts_through_unified_pipeline(
            bot, event,
            text=reply_text,
            image=image,
            audio=audio_parts,
            prefix_parts=prefix_parts,
            audit_tags=list(reaction.audit_tags),
            capability_id="bot.poke",
        )
        # STICKER-REACTION 接线（互动面波 2026-10-03）：矩阵行 ``sticker_reaction``
        # 的 ``wired_in_poke_path`` 据此翻 True——被戳（群内）且回复真送达后，把这条
        # 已送达回复交 reactions 引擎「回复后」触发点。选脸/五层防刷门/私聊拒发全是
        # 引擎现成件（``maybe_react_on_message``，不重写第二份选择逻辑）：群判定吃
        # ``_is_group_session``（QQ 无私聊表情通道，台账 #35★，私聊在引擎层即拒），
        # 五层门同用 chat 链路那一枚 ``_REACTION_PROACTIVE_GATE``。
        # poke notice 本身无可贴的用户消息（OneBot notice 不带 message_id），贴纸
        # 目标＝bot 自己这条已送达的回复（provider_message_id）；平台对自有消息贴
        # 表情的实装与否离线不可证，整块 try 住、失败静默——已发出的回复绝不受牵连。
        # 开关沿用 after_reply 那枚（同族「回复后表情回应」，零新增开关）。
        if (
            reaction.group
            and switches.enabled("bot.plugin.chat.reactions.after_reply")
            and str(getattr(poke_receipt, "provider_message_id", "") or "").strip()
        ):
            try:
                await _maybe_react_on_message(
                    bot,
                    session_key=f"group_{poker_group}_{poker_id}",
                    user_message_id=str(poke_receipt.provider_message_id),
                    text="",
                    config=merged_poke_config,
                    trigger="after_reply",
                    gate=_REACTION_PROACTIVE_GATE,
                )
            except Exception:  # noqa: BLE001, S110 - 贴表情失败绝不影响已送达的回复。
                pass

    # 表情贴纸回应识别（bot.reactions）：SnowLuma 贴纸回应 notice 先做归一与会话
    # 缓冲登记（供 chat 注入【表情回应】分区），识别段本身不回话、不贴表情——主动
    # 贴表情在 chat 链路的情绪信号/回复后触发点完成。S3（席位 W7S，2026-09-30）
    # 在其**之后**追加一条小概率补发腿：群里有人对我的消息贴了表情 ⇒ 过同一族门
    # 后可能补发一张现役人格册贴纸。补发段整块 try 住、异常只留 debug 痕，识别与
    # 落库那段的行为与改前逐字一致。私聊等价形态按容错解析，生产实机待验证；
    # 失败静默不影响任何主链路。
    async def _is_msg_emoji_like_event(event: Event) -> bool:
        return str(getattr(event, "notice_type", "")) in {
            "group_msg_emoji_like",
            "private_msg_emoji_like",
            "msg_emoji_like",
        }

    emoji_like_notice = on_notice(rule=_is_msg_emoji_like_event, priority=7, block=False)

    @emoji_like_notice.handle()
    async def _handle_msg_emoji_like_notice(bot: Bot, event: Event) -> None:
        switches = await product_feature_gate.snapshot_async()
        if not switches.enabled("bot.plugin.chat.reactions.receive"):
            return
        first_reaction: Any = None
        try:
            for reaction_event in _normalize_onebot_emoji_like(event):
                if first_reaction is None:
                    first_reaction = reaction_event
                _REACTION_BUFFER.record(reaction_event)
                # B 线双写：缓冲管当前语境注入，落库管长期记忆与统计
                # （幂等合并；失败静默不碰识别链路）。
                _reaction_store.record_event(
                    session_key=reaction_event.session_key,
                    user_id=reaction_event.user_id,
                    message_id=reaction_event.message_id,
                    emoji_id=reaction_event.emoji_id,
                    emoji_text=reaction_event.emoji_text,
                    count=reaction_event.count,
                    platform=reaction_event.platform,
                    occurred_at=reaction_event.ts,
                )
        except Exception:  # noqa: BLE001, S110 - 回应识别失败不影响主链路。
            pass
        # S3 face 回应联动补发（席位 W7S）。一次 notice 最多补发一张：同一条消息的
        # 多枚 likes 归一后 message_id 相同，取第一条即代表这次回应；剩下的交给
        # 五层门的每消息去重（``emoji:<message_id>``），不另立去重账。
        # 特性门 ``bot.plugin.chat.reactions.meme`` 判在派发前（与 P3 的调用点同形：
        # P3 那枚也在 chat 派发处判、腿内只判贴纸池门），本腿内再判池子门。
        if first_reaction is None or not switches.enabled("bot.plugin.chat.reactions.meme"):
            return
        try:
            await _maybe_send_sticker_for_emoji_like(
                bot,
                event,
                reaction_event=first_reaction,
                meme_config=_config_with_runtime_overrides(config, runtime_settings),
                # 快照查询口照传（与 P3 / 钩子同一约定）：漏传＝不发。
                feature_enabled=switches.enabled,
            )
        except Exception:  # noqa: BLE001 - 补发失败绝不影响识别链路与投递结果。
            logger.debug("emoji-like sticker dispatch failed", exc_info=True)

    async def _is_group_increase_notice(event: Event) -> bool:
        return str(getattr(event, "notice_type", "")) == "group_increase"

    async def _is_group_decrease_notice(event: Event) -> bool:
        return str(getattr(event, "notice_type", "")) == "group_decrease"

    async def _is_group_admin_notice(event: Event) -> bool:
        return str(getattr(event, "notice_type", "")) == "group_admin"

    group_increase_notice = on_notice(rule=_is_group_increase_notice, priority=6, block=False)
    group_decrease_notice = on_notice(rule=_is_group_decrease_notice, priority=6, block=False)
    group_admin_notice = on_notice(rule=_is_group_admin_notice, priority=6, block=False)

    @group_increase_notice.handle()
    async def _handle_group_increase(bot: Bot, event: Event) -> None:
        # 审查 B-05：入群欢迎（协议 group_increase 此前无人消费）。欢迎独立
        # 开关；昵称富集失败退通用称呼。退群/管理变更只记事件不发言——公开
        # 点名离开者与权限变动在社交上都是减分项。
        if not getattr(config, "bot_group_welcome_enabled", True):
            return
        group_id = str(getattr(event, "group_id", "") or "").strip()
        if not group_id:
            return
        user_id = str(getattr(event, "user_id", "") or "").strip()
        nickname = ""
        if user_id:
            try:
                member_info = await asyncio.wait_for(
                    bot.call_api(
                        "get_group_member_info",
                        group_id=int(group_id),
                        user_id=int(user_id),
                    ),
                    timeout=5.0,
                )
                nickname = str(
                    getattr(member_info, "card", "")
                    or getattr(member_info, "nickname", "")
                    or ""
                ).strip()
            except Exception:  # noqa: BLE001 - 昵称富集失败退通用称呼。
                nickname = ""
        # 裁定 R-4（2026-09-24「走管线，全部统一」）：欢迎语**只**经统一管线（notice 事件
        # 摄取对 NoticeEvent 族空文本降级，_incoming_from_nonebot_event）；失败静默不影响
        # 主链路，SENT/REDIRECTED 才记 group_welcome_sent（不假成功）。旧
        # `bot_group_welcome_via_queue` 开关与它下面的 `call_api` 直发分支一并退役——
        # 留着"关态走直发"的开关＝留着第二条路（正是「在册未执法」那件事本身）。
        try:
            receipt = await _send_text_through_unified_pipeline(
                bot,
                event,
                _group_welcome_text(nickname),
                capability_id="bot.group_welcome",
            )
        except Exception:  # noqa: BLE001 - 欢迎失败不影响主链路。
            return
        if receipt.state in {ReceiptState.SENT, ReceiptState.REDIRECTED}:
            _log_runtime_event(
                runtime_event_log, "INFO", "group_welcome_sent", group_id=group_id
            )
            # P14：「bot 主动发言后」那条戳人腿——欢迎是新成员进群后 bot 先开口，
            # 送达后才掷骰（没送达不掷、不记账）。缺省关；blocked/安静时间/五层门
            # 全在 proactive_action_allowed 里，与回复后那条腿共用同一门身。
            try:
                welcome_switches = await product_feature_gate.snapshot_async()
                await _maybe_poke_after_bot_spoke(
                    bot,
                    merged_config=_config_with_runtime_overrides(
                        config, runtime_settings
                    ),
                    poke_back_on=welcome_switches.enabled(
                        "bot.plugin.poke.poke_back"
                    ),
                    group_id=group_id,
                    user_id=user_id,
                    message_key=f"{group_id}-{user_id}",
                    purpose="welcome",
                )
            except Exception:  # noqa: S110, BLE001 - 主动戳人失败绝不波及欢迎主链路。
                pass

    @group_decrease_notice.handle()
    async def _handle_group_decrease(bot: Bot, event: Event) -> None:
        # 只记事件：离开是个人决定，公开送别/点名都是打扰。
        _log_runtime_event(
            runtime_event_log,
            "INFO",
            "group_member_left",
            group_id=str(getattr(event, "group_id", "") or ""),
            user_id=str(getattr(event, "user_id", "") or ""),
        )

    @group_admin_notice.handle()
    async def _handle_group_admin_change(bot: Bot, event: Event) -> None:
        _log_runtime_event(
            runtime_event_log,
            "INFO",
            "group_admin_changed",
            group_id=str(getattr(event, "group_id", "") or ""),
            user_id=str(getattr(event, "user_id", "") or ""),
        )

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
        # 需求16（2026-10-02 全量修复批）：落盘文件回填内容理解——T2 打标注记
        # （走 labelled_text 咽喉）与语法调试报告并列随统一管线回给用户；读不动
        # =诚实句绝不假装读过；同步读放下线程池；失败只丢注记不拦调试回报。
        context_note = ""
        try:
            from .domains.files.sources.file_reader import (
                build_incoming_file_context_note,
            )

            context_note = await asyncio.to_thread(
                build_incoming_file_context_note,
                saved_path,
                original_name=file_name,
            )
        except Exception:  # noqa: BLE001 - 内容理解失败不影响调试回报主路径。
            context_note = ""
        combined = f"[文件调试] {file_name}\n{report}"
        if context_note:
            combined = f"{combined}\n{context_note}"
        await _send_text_through_unified_pipeline(bot, event, combined)

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
        from .domains.files.capabilities.file_exchange import _DOCUMENT_PROMPT

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
        # 裁定 R-4 + 裁项 5（2026-09-24「全部统一、全面解决欠账」）：文档导出上传**只**走
        # 统一管线 files 件 → FileTransferGateway 既有链（平台方法面与直连一致：
        # 群 upload_group_file / 私聊 upload_private_file）；成功/失败文案由回执态驱动，
        # 失败不抛出（旧直连语义保持）。旧 `bot_file_export_via_queue` 开关与其下的
        # `call_api` 直传二分支一并退役。
        try:
            receipt = await _send_files_through_unified_pipeline(
                bot,
                event,
                files=[{"file": str(path), "name": path.name}],
                capability_id="bot.file",
            )
        except Exception:  # noqa: BLE001 - 统一路径异常与旧直连失败同语义。
            receipt = None
        if receipt is not None and receipt.state in {
            ReceiptState.SENT,
            ReceiptState.REDIRECTED,
        }:
            await _send_text_through_unified_pipeline(
                bot,
                event,
                f"已生成并上传 {fmt.upper()}：{path.name}（{max(1, path.stat().st_size // 1024)}KB）",
                capability_id="bot.file",
            )
        else:
            await _send_text_through_unified_pipeline(
                bot, event, f"文件已生成但上传失败：{path.name}"
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
        , feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
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
        from .domains.media.capabilities.image_search import (
            build_image_search_capability,
        )

        capability = build_image_search_capability(config)
        # 第二通路收编（S-SEAM-ROOT）：投递/诊断/运营告警/回执替换全部经中央缝完成，
        # 调用点只保留 matcher 兜底 finish 判定。
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
            capability_id="bot.image_search",
            message=message,
            operational_notifier=_notify_operational_receipt,
        )
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
                qr_file_ref = "file:///" + png_path.replace("\\", "/")
                # 裁定 R-4（全部统一）：二维码**只**走统一管线 mixed 件（text=""+image，
                # 同款先例＝表情回应 meme 抽图）；file:/// 引用与旧直连段逐字节同构
                # （onebot._resolve_local_file_ref 本地路径显式解析）。旧
                # `bot_cookie_qr_via_queue` 开关与其下 group/private 二分支 `call_api`
                # 直发一并退役——第二通路不该以"缺省关"的名义留在树上。
                try:
                    receipt = await _send_parts_through_unified_pipeline(
                        bot,
                        event,
                        text="",
                        image=qr_file_ref,
                        audit_tags=["cookie_login_qr"],
                        capability_id="bot.cookie_login",
                    )
                    if receipt.state not in {
                        ReceiptState.SENT,
                        ReceiptState.REDIRECTED,
                    }:
                        logging.getLogger(__name__).debug(
                            "qr image send failed: receipt state=%s",
                            receipt.state,
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
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
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
        if not (await product_feature_gate.snapshot_async()).enabled("bot.plugin.meme_library.auto_absorb"):
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

    async def _is_tts_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.TTS
        )

    async def _is_reminder_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.REMINDER
        )

    async def _is_daily_assist_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.DAILY_ASSIST
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
    # WP5（2026-09-21 路由优先级拆位）：NoneBot matcher priority 与中央 RouteRule
    # priority 双钉一致（test_emergency_info_push R-1 锁）。各 matcher 判定读
    # `_cached_route_decision(...).kind is RouteKind.X`（单一 kind 胜出），故拆位只
    # 影响 handler 试探序、不改生产胜出；此处随中央序 fx36<commodities37<bond38<
    # northbound39 同步，market 仍 41。
    fx = on_message(rule=_is_fx_event, priority=36, block=True)
    stocks = on_message(rule=_is_stocks_event, priority=42, block=True)
    commodities = on_message(rule=_is_commodities_event, priority=37, block=True)
    bond = on_message(rule=_is_bond_event, priority=38, block=True)
    northbound = on_message(rule=_is_northbound_event, priority=39, block=True)
    divination = on_message(rule=_is_divination_event, priority=41, block=True)
    news = on_message(rule=_is_news_event, priority=41, block=True)
    randpic = on_message(rule=_is_randpic_event, priority=41, block=True)
    tts = on_message(rule=_is_tts_event, priority=41, block=True)
    reminder = on_message(rule=_is_reminder_event, priority=41, block=True)
    daily_assist = on_message(rule=_is_daily_assist_event, priority=42, block=True)
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
        # 别名入口交出去的必须是**真正被解析出来的那个能力**，不是"bot.alias" 这个入口名：
        # 汇合点按 capability_id 决定要不要过层 2 治理，写死入口名 ⇒ 经别名命中的
        # weather/wiki/eat/news/epic/affinity 整条绕开权限/健康/限额/超时/审计
        # （R-CHOKE C-1，与"命令入口包了缝就算通电"是同一型假绿的第三次发作）。
        capability_id = resolution.capability_id or "bot.alias"
        help_bot_avatar_url = ""

        if resolution.capability_id == "bot.help":
            capability_id = "bot.help"

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                from .domains.chat_reply.capabilities.echo import build_help_result

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
                    # 帮助条目把「为什么」标成 admin_only，执行面此前零门 ⇒ 角色从这里传进去。
                    actor_roles=list(getattr(_decision, "actor_roles", []) or []),
                )

        elif resolution.capability_id == "bot.weather":
            query = resolution.rest_text

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": f"天气 {query}"})
                return _build_weather_with_backend(config)(synthetic, _decision)

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
                return _build_wiki_with_backend(config)(synthetic, _decision)

        elif resolution.capability_id == "bot.eat":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return _build_eat_with_backend(config)(message, _decision)

        elif resolution.capability_id == "bot.news":
            # F9：别名链此前无 bot.news 分支，「守岸人 AI新闻」坠 help。
            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return _build_news_with_backend(config)(message, _decision)

        elif resolution.capability_id == "bot.epic":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return _build_epic_with_backend(config)(message, _decision)

        elif resolution.capability_id == "bot.music_mode":
            from .domains.music.capabilities.music import (
                build_music_mode_result,
                extract_music_mode,
            )

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
                return _build_affinity_with_backend(config)(message, _decision)

        elif resolution.capability_id == "bot.subscribe":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                from .domains.subscribe.capabilities.subscribe import (
                    normalize_subscribe_text,
                )
                from .domains.subscribe.capabilities.subscribe_v2 import (
                    build_subscribe_capability_v2,
                )

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
            history_recorder=history_recorder,
            history_kind="command",
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
            await alias.finish(receipt.public_message)

    @music_mode.handle()
    async def _handle_music_mode(bot: Bot, event: Event) -> None:
        from .domains.music.capabilities.music import (
            build_music_mode_result,
            extract_music_mode,
        )

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
        from .domains.subscribe.capabilities.subscribe import normalize_subscribe_text
        from .domains.subscribe.capabilities.subscribe_v2 import (
            build_subscribe_capability_v2,
        )

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
        # P-G1（S-ATK-PERSONA，2026-09-27）：外观随切腿的角色门采集袋——
        # runtime 管理能力闭包执行时记下本次 actor_roles，随钩子传进 helper。
        persona_gate_roles: list[str] = []

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
                    actor_roles=list(getattr(_decision, "actor_roles", []) or []),
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

        elif command_text == "feature" or command_text.startswith("feature "):
            from .domains.ops.features.feature_control import (
                build_feature_control_result,
            )

            capability_id = "bot.runtime"
            feature_command = command_text.removeprefix("feature").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_feature_control_result(
                    feature_service, request_id=message.request_id,
                    actor_id=message.sender_id, actor_roles=list(_decision.actor_roles),
                    command_text=feature_command,
                )

        elif command_text == "runtime" or command_text.startswith("runtime "):
            capability_id = "bot.runtime"
            runtime_command = command_text.removeprefix("runtime").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                # P-G1：记下本次管理命令面的角色（外观腿唯一门的供数点）。
                persona_gate_roles[:] = [
                    str(role).lower() for role in (getattr(_decision, "actor_roles", ()) or ())
                ]
                return build_runtime_admin_result(
                    settings_manager,
                    effective_instance(config),
                    config,
                    request_id=message.request_id,
                    actor_id=message.sender_id,
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
                    actor_id=message.sender_id,
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

        elif command_text == "intimate" or command_text.startswith("intimate "):
            # /bot intimate on|deep|off|show：亲密档的命令面入口（席 S6，2026-10-08 波）。
            # 能力 id **复用 bot.chat**——整句「亲密模式 开/深开/关」今天就挂在 bot.chat 上，
            # 铸 bot.intimate 要同改 capability_protocols 唯一在册表 +
            # CONTROLLED_INTERNAL_CAPABILITIES + test_capability_manifest_gate 那本
            # "只准降缺口"的账，不划算；可分辨性全部交给 audit_tags 的 slash_intimate:*。
            # ⚠ 本分支插在 identity 与 route 之间 ⇒ 裸 `/bot intimate` 不再落到链尾的
            # `bot.help` 兜底（旧行为靠 `_HELP_ALIAS_MAP["intimate"]` 出帮助页）——
            # 那份「用法 + 当前档 + /bot help 亲密模式」的指路改由 intimate_control
            # 自己交，判据锁在 tests/test_intimate_slash_command.py。
            from .domains.chat_reply.runtime.intimate_control import (
                build_intimate_control_result,
            )

            capability_id = "bot.chat"
            intimate_command = command_text.removeprefix("intimate").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_intimate_control_result(
                    config=config,
                    request_id=message.request_id,
                    subcommand=intimate_command,
                    session_type=str(getattr(message.session_type, "value", "") or ""),
                    session_key=str(message.session_id or ""),
                    sender_id=str(message.sender_id or ""),
                    group_id=str(message.group_id or ""),
                    sender_roles=list(_decision.actor_roles),
                    # 隐私档只转述会话本身（中央件 default_privacy_by_session 已夹好）：
                    # 硬写成 PERSONAL 就是 D1 那一格——群回执会被审核判 move_private。
                    privacy_level=message.privacy_level,
                    runtime_settings=runtime_settings,
                    # 描写钉按 (平台域, 人[, 会话]) 取键：亲密面也渲染那一句「细节描写」，
                    # 平台事实只出自契约字段（口径同下面 narration 那一支）。
                    platform=message.platform,
                )

        elif command_text == "narration" or command_text.startswith("narration "):
            # /bot narration speech|scene|reset|show（同义中文词头 /bot 描写 …）：
            # 描写档＝这一轮把场景铺开写、还是只说出口的话（席 na3-declare 接线，
            # 轴心/词表/三腿真身全在 runtime/content_route.py 与 intimate_control.py，
            # 本支**只做派发**：认词头、剥词头、把剩下的参数串原样交给 handler）。
            # 🔴 四枚子命令的字面量**不在这里出现**——词表唯一的家＝
            # `_NARRATION_SUBCOMMAND_TABLE`（裁定 G-0 乙），此处重列＝第二处声明位；
            # 认不出什么也不改，判据锁在 tests/test_narration_command_dispatch.py。
            # 中文词头**不在这一式里**：`描写 → narration` 住 `runtime/aliases.py::
            # MODULE_ALIASES`（席 aliasgap 归位，`功能管理 → feature` 同一先例），上面
            # `command_text = normalize_command_text(...)` 已经把它归一成英文正形 ⇒
            # 条件式只读 canonical 名，词面全仓一处。别名册是派发路径的一环、不是文案件。
            # 能力 id 复用 bot.chat（与 /bot intimate 同一先例：铸 bot.narration 要同改
            # capability_protocols 唯一在册表 + 那本"只准降缺口"的账，不划算）；
            # 可分辨性交给 audit_tags 的 slash_narration:*。
            from .domains.chat_reply.runtime.intimate_control import (
                build_narration_control_result,
            )

            capability_id = "bot.chat"
            narration_command = command_text.removeprefix("narration").strip()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_narration_control_result(
                    config=config,
                    request_id=message.request_id,
                    subcommand=narration_command,
                    session_type=str(getattr(message.session_type, "value", "") or ""),
                    session_key=str(message.session_id or ""),
                    sender_id=str(message.sender_id or ""),
                    group_id=str(message.group_id or ""),
                    sender_roles=list(_decision.actor_roles),
                    # 只转述会话本身的隐私档（同 intimate 那一支的口径）：硬写成
                    # PERSONAL 会让群回执被审核判 move_private。
                    privacy_level=message.privacy_level,
                    # 席 na-land（接席 na-keyfix §7）：命令面与注入缝**同批**交平台事实，
                    # 值只出自契约字段 `IncomingMessage.platform`（猜平台／反解会话键＝T-1
                    # 同族；只接一侧＝#33★"写在 qq:<uid>、读在 <uid>"）。作用域仍按人全局。
                    platform=message.platform,
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
                # Wave 1 接入（统一裁定「所有内容走中央调度层」）：检索改经 CapabilityInvoker，
                # 权限门/载荷限额/健康态/降级链/审计落中央；命中→排版的下游一字未动。
                # 函数体内 import（顶置 import 会顶漂下方 live 坐标，见 #45/U17 同型教训）。
                from .runtime.capability_protocols import (
                    CapabilityRequest as _SearchRequest,
                )
                from .runtime.capability_protocols import (
                    InvocationStatus as _SearchStatus,
                )
                from .runtime.capability_protocols import (
                    default_invoker as _default_invoker,
                )

                limit = int(getattr(config, "bot_web_search_max_results", 12) or 12)
                _search_res = _default_invoker().invoke(
                    _SearchRequest(
                        capability_id="search.web",
                        payload={"query": search_query, "max_results": limit},
                        # 主体必须来自消息与判定，不能硬编成 ("user",)：硬编会让中央权限门
                        # 退化成装饰（blocked 被抹成 user 也过），且 principal 兼数据面归属键。
                        principal=str(getattr(message, "sender_id", "anonymous") or "anonymous"),
                        roles=tuple(getattr(_decision, "actor_roles", ()) or ()),
                        context={"config": config},
                    )
                )
                hits = (
                    _search_res.data.get("hits", [])
                    if _search_res.status is _SearchStatus.OK
                    else []
                )
                if not hits:
                    # 对用户仍是一句人话，但**病因必须留痕**：未启用/无权限/超时/真身异常
                    # 四类在中央是四个不同 status，压成同一条 audit_tag 等于自断排障路
                    # （R1/I-2；返回体一字未改，只加观测面）。
                    if _search_res.status is not _SearchStatus.OK:
                        logger.warning(
                            "bot.search 经中央调度未取到结果: status={} detail={}",
                            _search_res.status.value,
                            _search_res.detail or "(中央未给出原因)",
                        )
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.search",
                        kind="text",
                        body=(
                            "本次联网检索没有返回结果。\n"
                            "可能原因：检索源不可达、被反爬或代理未生效。\n"
                            f"查询词：{search_query}"
                        ),
                        audit_tags=["search", "search_empty", f"search_status:{_search_res.status.value}"],
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

        elif command_text.startswith("reply ") and (
            command_text.removeprefix("reply").strip().lower().split(maxsplit=1)[0]
            in {"set", "show", "clear"}
        ):
            # 2026-09-28 用户裁定 Q3「甲+乙」的甲半边：`set|show|clear` 三个子命令动的是
            # **按人**永久策略（user_reply_policy 那一行，跨群跨私聊、换人格都跟着人），
            # 而下面那条老分支动的是全局档 BOT_REPLY_DETAIL。两条各只有一条写腿，
            # 且都折算到 chat 那同一张长度表上——不另立第二把长度尺。
            capability_id = "bot.reply"
            reply_preset_argument = command_text.removeprefix("reply").strip().lower()

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                from .domains.chat_reply.character.reply_policy import (
                    build_reply_policy_preset_result,
                )

                return build_reply_policy_preset_result(
                    config,
                    request_id=message.request_id,
                    sender_id=message.sender_id,
                    actor_roles=_decision.actor_roles,
                    command_text=reply_preset_argument,
                )

        elif command_text == "reply" or command_text.startswith("reply "):
            capability_id = "bot.reply"
            reply_mode = command_text.removeprefix("reply").strip().lower()
            # 别名表只住在 `settings._reply_detail_converter` 一处（同一张表也服务
            # `/bot runtime set BOT_REPLY_DETAIL=...`）；这里只认最常见的三枚，
            # 其余档名（适中/讲全/掰碎）由那条通用运行时设置口去改，避免两处各抄一份。
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
                            "用法：/bot reply <详细|精简|默认>＝改全局档；"
                            "按人永久策略＝/bot reply set <QQ号> <默认|简洁|适中|讲全|详尽> "
                            "[文学化|说人话]，show 复查、clear 撤销"
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
                            "用法：/bot reply <详细|精简|默认>＝改全局档；"
                            "按人永久策略＝/bot reply set <QQ号> <默认|简洁|适中|讲全|详尽> "
                            "[文学化|说人话]，show 复查、clear 撤销"
                        ),
                        audit_tags=["reply_detail", f"current:{current}"],
                    )
                runtime_settings.set_override(
                    "BOT_REPLY_DETAIL", normalized_mode,
                    actor=f"{message.platform}:{message.sender_id}",
                    request_id=message.request_id,
                    session_key=message.session_id,
                )
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
                from .domains.subscribe.capabilities.subscribe_v2 import (
                    build_subscribe_capability_v2,
                )

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
                from .domains.ops.admin.runtime_logs import build_logs_query_result

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
                # 身份接线（席位 D 2026-09-27 用户裁定，取证席钉死的接线 bug）：
                # 这一族写点此前一律不传 actor/session_key，咽喉缺省把申请人记成
                # `runtime_internal`（runtime/settings.py 的 set_override 缺省），
                # 于是 ①防自批那一判据（consent.redeem_from_message）结构上永不咬，
                # ②超管 R1 免单门（settings_gate.guarded_write）永远命中不到真人。
                # 传法照 domains/ops/admin/runtime_admin.py 的规范腿：actor 用
                # `平台:号`（与 consent._approver_of 同形，两边才能对上同人）。
                # message 由摄取层从真事件构造，platform/sender_id 为结构化事实；
                # 拿不到号时（sender_id 空）actor 落成 `平台:` 空号形，
                # 由门侧 fail-closed 判它不是真人，绝不伪造一个身份。
                actor = f"{message.platform}:{message.sender_id}"
                try:
                    if action == "add":
                        merged = list(dict.fromkeys([*current, *group_ids]))
                        runtime_settings.set_override(
                            mode_key, ";".join(merged),
                            actor=actor, request_id=message.request_id,
                            session_key=message.session_id,
                        )
                    elif action == "del":
                        removed = set(group_ids)
                        runtime_settings.set_override(
                            mode_key,
                            ";".join(item for item in current if item not in removed),
                            actor=actor, request_id=message.request_id,
                            session_key=message.session_id,
                        )
                    elif action == "set":
                        runtime_settings.set_override(
                            mode_key, ";".join(group_ids),
                            actor=actor, request_id=message.request_id,
                            session_key=message.session_id,
                        )
                    else:  # clear
                        runtime_settings.set_override(
                            mode_key, "",
                            actor=actor, request_id=message.request_id,
                            session_key=message.session_id,
                        )
                except ValueError as exc:
                    from .domains.core.safety_exec.settings_gate import (
                        RuntimeChangeNeedsConsent,
                    )
                    if isinstance(exc, RuntimeChangeNeedsConsent):
                        # 待批工单（用户裁定 2026-09-27）：首行说人话（咽喉文案已改），
                        # 并给工单出一张通用卡（零新模板，仿 host_card）；出图失败
                        # fail-open 退回纯文本工单、正文仍在、零契约破坏。
                        images: list[dict[str, Any]] = []
                        gate = getattr(runtime_settings, "safety_gate", None)
                        ticket = (
                            gate.ticket(exc.consent_id) if gate is not None else None
                        )
                        if ticket is not None:
                            from .domains.ops.capabilities.consent_admin import (
                                render_consent_card_png,
                            )

                            png = render_consent_card_png(ticket.row)
                            if png:
                                images = [{"file": png}]
                        return CapabilityResult(
                            request_id=message.request_id,
                            capability_id="bot.group_policy",
                            kind="text",
                            body=str(exc),
                            images=images,
                            audit_tags=["group_policy", "needs_consent"],
                        )
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
                from .domains.chat_reply.capabilities.echo import build_help_result

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
            history_recorder=history_recorder,
            history_kind="command",
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
            await status.finish(receipt.public_message)
        # ---- PERSONA-HOT 装配腿（S-PERSONA-WIRE，提案=接线点 A；设计详见
        # .superpowers/sdd/2026-09-27-fullload/logs/SEAT-PERSONA-HOT-wiring.md）：
        # 语气人格切换成功后，紧随一次异步外观下发（H-1 逐项回执）。判据只认
        # bot.runtime + sent + 显式「persona switch」命令形（H-2：情绪/概率自动腿
        # 永不到这）；sent 只说明主链回执已投递，切换是否真落地由 helper 读回
        # runtime override 确认——驳回/报错路径同样是 sent，不确认就会假随切。
        if capability_id == "bot.runtime" and receipt.state.value == "sent":
            await _dispatch_persona_appearance_if_switched(
                bot=bot,
                event=event,
                config=config,
                command_text=command_text,
                settings_manager=settings_manager,
                actor_roles=persona_gate_roles,
            )
        # 规格 3 双触发（用户 2026-09-27 睡前定稿·第 9 项）：同一句里
        # 「无参数命令头 + 自然语言尾巴」⇒ 命令执行与人格回复并行，
        # 覆盖旧口径「命令旁路缓冲、命中命令就不走人格回复」。判据收在
        # message_merge.command_natural_remainder（可判定规则）：纯命令、
        # 带真参数的命令、判据不过 ⇒ None ⇒ 既有行为逐字节不变。
        from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
            message_merge as _m9,
        )

        dual_remainder = _m9.command_natural_remainder(command_text)
        if dual_remainder is not None and receipt.state.value == "sent":
            # 人格回复走的就是那条聊天主链：同 pipeline、同 chat_capability、
            # 同 send_queue 与投递件，不另起通路。派生消息由摄取新建 ⇒
            # request_id 独立，不与命令那条投递抢 _find_sent_request 定位；
            # 幂等表按 (event_key, capability_id) 分键，bot.chat 与 bot.status
            # 互不吞（event_idempotency 主键现算）。
            from .domains.chat_reply.runtime.ingress import IngressGateway

            persona_message = IngressGateway(_incoming_from_nonebot_event).from_event(
                event,
                bot_id=str(getattr(bot, "self_id", "unknown")),
            ).model_copy(
                update={"plain_text": dual_remainder, "command_text": ""}
            )
            _log_runtime_event(
                runtime_event_log,
                "INFO",
                "command_dual_trigger_persona",
                message=persona_message,
                capability_id="bot.chat",
            )
            persona_receipt = await pipeline.handle_async(
                persona_message,
                chat_capability,
                capability_id="bot.chat",
            )
            await _notify_operational_receipt(persona_message, persona_receipt)
            persona_request = _find_sent_request(
                send_queue, persona_message.request_id
            )
            if persona_request is not None:
                await _deliver_transport_send_request(
                    bot,
                    event,
                    persona_request,
                    audit_logger,
                    receipt_repository,
                    send_queue,
                )
                if _should_record_chat_history(persona_request):
                    _record_chat_history_turn(
                        history_recorder,
                        message=persona_message,
                        role="user",
                        text=dual_remainder,
                        audit_logger=audit_logger,
                    )
                    _record_chat_history_turn(
                        history_recorder,
                        message=persona_message,
                        role="assistant",
                        text=persona_request.content.text_fallback,
                        audit_logger=audit_logger,
                    )

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
        switches = await product_feature_gate.snapshot_async()
        event_segments = _extract_onebot_raw_segments(event)
        if switches.enabled("bot.ingress.audio_transcode") and any(str(s.get("type", "")).lower() == "record" for s in event_segments):
            await _transcode_record_segments(bot, event_segments)
        # TG 媒体段富化：file_id → 字节落临时文件写回 data.file，vision/ASR 的
        # 既有本机路径链路即可直接消费；模块内部自判 TG 事件且绝不抛异常，
        # 非 TG 事件零成本直通，失败保持段原样（标签降级行为不变）。
        if switches.enabled("bot.ingress.telegram_media"):
            await enrich_telegram_file_segments(bot, event, event_segments)
        # 引用链：QQ 的"引用的引用"不随事件下发，需按 id 反查（get_msg）。
        # 只在确有更深 reply 段时才发请求；失败/超时按链条结束，不阻断消息。
        if switches.enabled("bot.ingress.reply_lookup"):
            resolved_chain = await collect_reply_chain_async(
                event, lookup=_make_onebot_reply_lookup(bot)
            )
        else:
            resolved_chain = collect_reply_chain(event)
        message = _incoming_from_nonebot_event(
            bot_id=bot_id,
            event=event,
            segments=event_segments or None,
            reply_chain=resolved_chain,
            feature_enabled=switches.enabled,
        )
        # TG 拼格「同册只回一次」（席位 P9 判据 + P9b 接线，台账 #73）：拼格的 N 个成员是 N 个
        # 独立事件，各走一遍摄取 ⇒ 各进一次管道 ⇒ 用户看到 N 条回复。判据按 (会话, 专辑号) 记一枚
        # 开门登记，窗口真身＝message_merge.MERGE_WINDOW_SECONDS（用户 2026-09-27 裁定的 3s 折句窗，
        # 与本件 120s 计数桶 TTL 分家）；不开等待窗、不 await、不占协程 ⇒ 末张图迟到或不到都卡不住
        # 这一轮（有界性来自结构，最坏只多回一句）。
        # merged=True ⇒ 本条已折进册主那一轮：就此返回，不进 RuntimePipeline、不触发第二次能力调用。
        # 三道 fail-open 闸（非 telegram 适配器／无合法专辑号／本条带用户键入正文）与同轮重投闸
        # （台账 #65）都在判据内部 ⇒ QQ 与邮件路径行为逐字节不变。判据纯读、不产任何新的文本面标记
        # ⇒ INTERNAL_MARKER_PATTERN 无需新门票（台账 #67★ 的同批补门票义务在此为空腿，本席复核确认）。
        # 位置口径：摄取之后、其余各腿（看图上下文注入／贴表情／被动好感观察／管道）之前——被折掉的
        # 成员不该再各自长出一轮副作用；识图腿要的 N 张原图已在摄取时逐段登记（段面一张不丢）。
        from .domains.chat_reply.ingest.message_context import (
            telegram_album_turn_decision as _telegram_album_turn_decision,
        )

        album_turn = _telegram_album_turn_decision(message)
        if album_turn.merged:
            _log_runtime_event(
                runtime_event_log,
                "INFO",
                "telegram_album_member_folded",
                message=message,
                media_group_id=album_turn.media_group_id,
                album_arrival=album_turn.arrival,
                owner_message_id=album_turn.owner_message_id,
                reason=album_turn.reason,
            )
            return
        # 最近图片上下文（vis3 2026-09-13 · MM-VIS-1 缺陷 3 扩到私聊）：
        # 无自带图 + 看图意图 → 注入本会话 TTL 内最新一张；模型视角即"总结这张图"。
        # 判据里 `message.group_id` 换成 `message.session_id`——私聊没有群号，
        # 旧写法让私聊那条"隔几秒再补一句问话"的常见形状完全没有兜底。
        # 其余四条件一字未动（开关 / 有文本 / 命中看图意图 / 本轮无自带图）。
        if (
            switches.enabled("bot.plugin.chat.recent_image")
            and message.session_id
            and message.plain_text
            and _VISION_HINT_RE.search(message.plain_text)
            and not any(
                str(s.get("type", "")).strip().lower() == "image"
                for s in message.raw_segments or []
            )
        ):
            recent_url = _latest_fresh_session_image(
                message.session_id, time.monotonic()
            )
            if recent_url:
                message.raw_segments.append(
                    {"type": "image", "data": {"url": recent_url}}
                )
                # 来源附注（vis3）：随图注入让模型知道这是最近发过的图、非本轮上传。
                # 措辞不再写死"群里"——同一枚注入现在也服务私聊，写死就是谎报场景。
                message.raw_segments.append(
                    {
                        "type": "text",
                        "data": {"text": "（附注：这张图取自本会话最近发送的图片。）"},
                    }
                )
        # 表情贴纸回应·触发 B（bot.reactions）：用户消息命中情绪信号时，
        # 小概率给这条消息贴一个表情表达态度。五层门（开关/每消息去重/
        # 确定性概率/会话冷却/每小时时限）全在 reactions 模块内，失败静默。
        if switches.enabled("bot.plugin.chat.reactions.emotion") and ".mail" not in event_module:
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
        if switches.enabled("bot.plugin.affinity.passive") and message.sender_id and message.plain_text.strip():
            def _passive_affinity_perception() -> None:
                try:
                    _store = build_character_affinity_store(config)
                    from .domains.chat_reply.character.affinity import classify_behavior
                    from .domains.chat_reply.character.affinity import (
                        extract_profile_facts as _epf,
                    )
                    from .domains.chat_reply.runtime.content_route import (
                        explicit_allowed_for_session,
                    )
                    from .domains.chat_reply.security import content_safety as _cs

                    # 安全评估喂给行为分类：persona_degradation/harassment 等类别
                    # 才能映射到 insult/tease 路径（docs/affinity-design.md §6）。
                    assessment = _cs.assess_public_content(
                        message.plain_text,
                        # 2026-09-17：session_type 必填（此前默认 private，
                        # 群消息也被按私聊口径评估——行为分类信号静默漂移）。
                        session_type=str(getattr(message.session_type, "value", "")),
                        explicit_allowed=explicit_allowed_for_session(
                            str(getattr(message.session_type, "value", "")),
                            str(getattr(message, "group_id", "") or ""),
                            config,
                            # v21r5：传 sender_id 使私聊名单门对被动感知同源生效
                            #（黑名单永远赢）；群分支不受此参数影响。
                            sender_id=str(getattr(message, "sender_id", "") or ""),
                        ),
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
                        from .domains.chat_reply.character.affinity import (
                            extract_learned_nickname,
                        )

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
                        from .domains.chat_reply.character.emotion import (
                            build_emotion_provider,
                        )

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
                except ModuleNotFoundError: raise  # 静默死根修：缺模块＝装配/坐标错，必冒不吞（勿再被下面的 pass 掩成"分支今天没跑"）。
                except Exception: pass  # noqa: BLE001, S110 - 被动感知其余运行时失败不影响主链路（缺模块除外，见上一行）。

            await asyncio.to_thread(_passive_affinity_perception)
        # 小名缓存刷新（60s），供动态昵称 mention 判定。
        if time.time() - _AFFINITY_NICKNAMES_LOADED_AT > 60.0:
            _refresh_affinity_nicknames(_affinity_store_runtime(config))
        # 群聊复读检测（批次 C）：≥N 个不同用户在窗口内发同一文本 → 吐槽一次。
        if (
            switches.enabled("bot.plugin.chat.parrot")
            and message.session_type.value == "group"
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
                parrot_receipt = await pipeline.handle_async(
                    message,
                    offload_capability(lambda m, d: CapabilityResult(
                        request_id=m.request_id,
                        capability_id="bot.chat",
                        kind="text",
                        body=parrot_reply,
                        send_policy=SendPolicy.IMMEDIATE,
                        privacy_level=PrivacyLevel.GROUP,
                        risk_level=RiskLevel.LOW,
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
            forward_text = ""
            if switches.enabled("bot.plugin.chat.forward_lookup"):
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
            if switches.enabled("bot.plugin.chat.video_preprocess"):
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
        # 折句窗口（2026-09-29 用户裁定需求 1：接缝留在这里；链已接活，折不折由开关决定）。
        # 开关真值＝`.env` 的 `BOT_CHAT_MESSAGE_COALESCING_ENABLED`（本文件不抄读数，规则 10；
        # 判当前值走 `config.bot_chat_message_coalescing_enabled` 装载链，**禁读注释**——
        # 此处曾写死一个 `false` 把下一个排查者骗去把本链判成死口，2026-10-03 现算为真）。
        # 开着时：同一会话同人 ≤quiet 秒内的连发会被焊成一句（`join_utterance` 补中文逗号），
        # 非开门者那几条**不回**（`owned=False` 一路直接 return）——所以"一条回复答了三个
        # 问题"是本链的形状，不是模型出错。等待窗真身＝`effective_quiet_seconds`
        #（按收尾强度缩放，Config 的 `_quiet_seconds` 键 2026-09-27 乙案已退役）。
        # 调用细节全收进唯一入口 `message_coalescing.fold_inbound_turn`（本文件不再散写第二处＝
        # 禁第二通路），「启用只动哪三处 + 两条已知判据短板」写在该入口上方的注释块里。
        # 位置刻意在「合并转发已展开」「视频预处理已完成」之后、进管道之前：
        # 再早就会丢掉后补上的正文。import 放函数体内，不在文件顶部插行，
        # 免得把 campus_record_matcher 的登记坐标顶漂（同 5a 的先例）。
        from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
            message_coalescing as _coalescing,
        )
        from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
            message_merge as _merge,
        )

        _turn = await _coalescing.fold_inbound_turn(config, message)
        if not _turn.owned:
            # 已被折进别人那一轮：这一条不再单独回一句（省的就是这一次）。
            _log_runtime_event(
                runtime_event_log,
                "INFO",
                "chat_turn_folded",
                message=message,
                capability_id="bot.chat",
            )
            return
        message = _turn.message
        if _turn.folded_count > 1 and _turn.folded_message_ids:
            # MERGE-IDS-DOWNSTREAM 转正（需求 1 之 3，2026-09-29）：折进这一轮的
            # 每一条原始 message_id 都要留可反查的账——幂等/回执/补投按头 id 走，
            # 逐条对账看这条事件（merge_turn 同时把账挂在合并轮身上）。
            _log_runtime_event(
                runtime_event_log,
                "INFO",
                "chat_turn_folded_ledger",
                message=message,
                capability_id="bot.chat",
                folded_ids=",".join(str(item) for item in _turn.folded_message_ids),
                folded_count=_turn.folded_count,
            )
        # 规格 2（用户 2026-09-27 睡前定稿·第 9 项）：bot 已回复后对方再发
        # 裸表情/贴纸 ⇒ 当「静默」类。判据是可判定规则函数而非写死白名单
        # （见 message_merge.should_silence_emoji_reaction docstring）；
        # 位置在折句之后——被折进文字轮的贴纸随整轮回复，不再单独判。
        # 对话历史读不到（关闭/空/异常）⇒ 按「未回复」走既有链路（fail-open：
        # 宁可多回一句，不误静默提问）。静默必记事件，绝不无痕吞消息。
        if _merge.is_lone_emoji_or_sticker(message):
            try:
                _recent_turns = await asyncio.to_thread(
                    history_recorder.retrieve,
                    request_id=message.request_id,
                    platform=message.platform,
                    adapter=message.adapter,
                    bot_id=message.bot_id,
                    session_id=message.session_id,
                    sender_id=message.sender_id,
                    max_turns=1,
                    max_chars=64,
                )
                _last_turn_role = (
                    _recent_turns.turns[-1].role if _recent_turns.turns else None
                )
            except Exception:  # noqa: BLE001 - 历史读失败按「未回复」处理。
                _last_turn_role = None
            if _merge.should_silence_emoji_reaction(
                message, last_turn_role=_last_turn_role
            ):
                _log_runtime_event(
                    runtime_event_log,
                    "INFO",
                    "chat_emoji_reaction_silenced",
                    message=message,
                    capability_id="bot.chat",
                )
                return
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
            **_policy_gate_values(audit_logger, receipt, message),
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
                reaction_meme_config = _config_with_runtime_overrides(
                    config, runtime_settings
                )
                # 贴纸语义匹配（她 2026-09-28 点名「报喜却发委屈/大哭，不行」）：
                # 贴之前把 bot 本轮**实际下发的文本**一并交出去，选贴按它判情感，
                # 不再只看用户原话的关键词。取唯一出口文本，不另拼第二份。
                reply_text_for_reaction = str(
                    getattr(getattr(sent_request, "content", None), "text_fallback", "")
                    or ""
                ).strip()
                reacted_with_emoji = False
                if switches.enabled("bot.plugin.chat.reactions.after_reply") and ".mail" not in event_module:
                    try:
                        bot_sent_id = transport_receipt.provider_message_id
                        if bot_sent_id:
                            _REACTION_BUFFER.register_bot_message(
                                message.session_id, bot_sent_id
                            )
                        _react_platform = str(
                            getattr(message, "platform", "") or ""
                        ).strip().lower()
                        if "telegram" in _react_platform:
                            # Telegram 侧同一条腿（她点名「QQ 和 Telegram 都要」）：通道在册
                            # 可达（outbound_registry 的 set_message_reaction），此前缺的只是
                            # 触发点。群组判定吃 chat.type，不吃 group_id（TG 频道也带号）。
                            _tg_chat_type = str(
                                getattr(getattr(event, "chat", None), "type", "") or ""
                            ).strip().lower()
                            reacted_with_emoji = await _maybe_react_telegram_message(
                                bot,
                                chat_id=getattr(event, "chat_id", "") or "",
                                message_id=str(
                                    getattr(event, "message_id", "") or ""
                                ),
                                session_key=message.session_id,
                                text=message.plain_text,
                                reply_text=reply_text_for_reaction,
                                config=reaction_meme_config,
                                is_group=_tg_chat_type in {"group", "supergroup"},
                                gate=_REACTION_PROACTIVE_GATE,
                            )
                        else:
                            reacted_with_emoji = await _maybe_react_on_message(
                                bot,
                                session_key=message.session_id,
                                user_message_id=str(
                                    getattr(event, "message_id", "") or ""
                                ),
                                text=message.plain_text,
                                reply_text=reply_text_for_reaction,
                                config=reaction_meme_config,
                                trigger="after_reply",
                                gate=_REACTION_PROACTIVE_GATE,
                            )
                    except Exception:  # noqa: BLE001 - 贴表情失败绝不影响投递结果。
                        reacted_with_emoji = False
                # 第二层：情绪信号命中且第一层未贴 → 小概率发一张**贴纸池**贴纸
                # （S-STICKER-POOLS 2026-09-29 起不再从群聊吸收表情库出图；独立
                # 冷却/每日上限/悲伤门/blocked 名单/安静时间/贴纸池特性门）。
                if (
                    not reacted_with_emoji
                    and switches.enabled("bot.plugin.chat.reactions.meme")
                    and ".mail" not in event_module
                ):
                    try:
                        await _maybe_send_reaction_meme(
                            bot,
                            event,
                            session_key=message.session_id,
                            text=message.plain_text,
                            reply_text=reply_text_for_reaction,
                            meme_config=reaction_meme_config,
                            # 快照查询口照传（与 _poke_voice_pair 同一约定）：漏传
                            # 本腿按「未开」算＝不发，主动外发腿不许有隐式放行档。
                            feature_enabled=switches.enabled,
                            # 同轮三腿互斥：真发出即占坑，后两腿（戳/随机图）让位。
                            claim_key=str(
                                getattr(event, "message_id", "") or message.request_id
                            ),
                        )
                    except Exception:  # noqa: BLE001, S110 - 表情包层失败绝不影响投递结果。
                        pass
                # P14 波「说完话之后」两条主动腿：概率戳一下对方 / 概率发一张随机图
                # （后者=随机发图三触发里的自动腿，指令路一直是既有那条）。两条都
                # 缺省关、各记各的门账，且都在 blocked 名单与安静时间窗之后；
                # 任何异常一律吞在本块内——刚送达的正文不能被增益腿反噬。
                if ".mail" not in event_module:
                    spoke_message_key = str(
                        getattr(event, "message_id", "") or message.request_id
                    )
                    # 同轮三腿互斥（互动面波 2026-10-03）：占坑键形 turn-attach:，
                    # P3 贴纸或戳真发出后这里各查一次、短路后腿；三腿都未中互不影响。
                    if not _turn_attachment_claimed(spoke_message_key):
                        try:
                            await _maybe_poke_after_bot_spoke(
                                bot,
                                merged_config=reaction_meme_config,
                                poke_back_on=switches.enabled(
                                    "bot.plugin.poke.poke_back"
                                ),
                                group_id=str(getattr(message, "group_id", "") or ""),
                                user_id=str(getattr(message, "sender_id", "") or ""),
                                message_key=spoke_message_key,
                                purpose="reply",
                            )
                        except Exception:  # noqa: S110, BLE001 - 主动戳人失败不影响投递结果。
                            pass
                    if not _turn_attachment_claimed(spoke_message_key):
                        try:
                            await _maybe_dispatch_randpic(
                                bot,
                                event,
                                merged_config=reaction_meme_config,
                                session_key=message.session_id,
                                message_key=spoke_message_key,
                                group_id=str(getattr(message, "group_id", "") or ""),
                                user_id=str(getattr(message, "sender_id", "") or ""),
                            )
                        except Exception:  # noqa: S110, BLE001 - 主动发图失败不影响投递结果。
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
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
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
        # 第二通路收编（S-SEAM-ROOT）：投递/诊断/运营告警/回执替换全部经中央缝完成，
        # 调用点只保留 matcher 兜底 finish 判定。
        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            diagnostics_store=diagnostics_store,
            capability=build_content_capability(
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
            ),
            capability_id="bot.content",
            message=message,
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
            await content.finish(receipt.public_message)

    @music.handle()
    async def _handle_music(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
        )
        # 第二通路收编（S-SEAM-ROOT）：投递/诊断/运营告警/回执替换全部经中央缝完成，
        # 调用点只保留 matcher 兜底 finish 判定。
        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            diagnostics_store=diagnostics_store,
            capability=build_music_capability(
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
            ),
            capability_id="bot.music",
            message=message,
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
            await music.finish(receipt.public_message)

    @today_history.handle()
    async def _handle_today_history(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
        )
        # 评审C1：交互走注入渲染后端的独立实例；today_ctx["capability"] 按产品裁定
        # 仅供定时推送（纯文字），二者在 _register_today_history_scheduler 内分流。
        capability = (
            today_ctx["interactive_capability"]
            if today_ctx is not None
            else build_today_history_capability(config, render_backend=render_backend)
        )
        # 第二通路收编（S-SEAM-ROOT）：投递/诊断/运营告警/回执替换全部经中央缝完成，
        # 调用点只保留 matcher 兜底 finish 判定。transport 路径旧形只通知管道回执一次，
        # 经缝后管道/运输回执各按中央策略通知（旁路渠道，属超集归一）。
        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            diagnostics_store=diagnostics_store,
            capability=cast(Any, capability),
            capability_id="bot.today_history",
            message=message,
            operational_notifier=_notify_operational_receipt,
        )
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
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
        )
        # Wave 4.1 主缝：在册的命令形能力把「能力执行步」委托给中央 invoker（层 2），
        # 未在册仍走旧 factory 直调——旧路可枚举，缺口条数由缺口棘轮门只准降不准升。
        # 函数体内 import：顶置 import 会顶漂下方被门钉住的 live 坐标（#45/U17 同型教训）。
        from .runtime.capability_protocols import orchestrated_command as _orchestrated

        receipt = await pipeline.handle_async(
            message,
            offload_capability(
                _orchestrated(capability_id, capability_factory(config), config)
            ),
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
                # NapCat 时期：空文本 finish 会被报「该消息类型暂不支持查看」。
                await matcher.finish(
                    transport_receipt.public_message or "（处理完成，没有需要展示的内容。）"
                )
        await _notify_operational_receipt(message, receipt)
        if should_finish_nonebot_matcher(receipt):
            await matcher.finish(
                receipt.public_message or "（处理完成，没有需要展示的内容。）"
            )


    async def _is_group_info_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.GROUP_INFO
        )

    group_info_matcher = on_message(rule=_is_group_info_event, priority=41, block=True)

    @group_info_matcher.handle()
    async def _handle_group_info(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event, bot_id=str(getattr(bot, "self_id", "unknown")),
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
        )
        # B-01：OneBot API 桥（offload 线程池同步执行，主会话装配期注入循环）。
        api = build_onebot_api_bridge(bot, asyncio.get_running_loop())
        # 第二通路收编（S-SEAM-ROOT）：投递/诊断/运营告警/回执替换全部经中央缝完成，
        # 调用点只保留 matcher 兜底 finish 判定。
        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            diagnostics_store=diagnostics_store,
            capability=build_group_info_capability(
                config, api=api, cache=group_info_cache, group_file_store=group_file_store
            ),
            capability_id="bot.group_info",
            message=message,
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
            await group_info_matcher.finish(
                receipt.public_message or "（处理完成，没有需要展示的内容。）"
            )

    # 需求 5（2026-09-26 goal18 波）：超管问「机器状态/机器配置」→ 现读本机事实 + Mica 卡片。
    # import 刻意落在函数体内：置顶 import 会把 campus_record_matcher 等登记坐标整体顶漂
    # （同 5a 先例）。能力本体经 offload_capability 下放线程池——秒级采集与渲染
    # 绝不在事件循环线程上跑，否则整个会话冻结。
    async def _is_host_state_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.HOST_STATE
        )

    host_state_matcher = on_message(rule=_is_host_state_event, priority=41, block=True)

    @host_state_matcher.handle()
    async def _handle_host_state(bot: Bot, event: Event) -> None:
        from .domains.ops.capabilities.host_state import (
            build_host_state_capability,
        )

        message = _incoming_from_nonebot_event(
            event, bot_id=str(getattr(bot, "self_id", "unknown")),
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
        )
        # 第二通路收编（S-SEAM-ROOT）：投递/诊断/运营告警/回执替换全部经中央缝完成，
        # 调用点只保留 matcher 兜底 finish 判定。
        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            diagnostics_store=diagnostics_store,
            capability=build_host_state_capability(config),
            capability_id="bot.host_state",
            message=message,
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
            await host_state_matcher.finish(
                receipt.public_message or "（处理完成，没有需要展示的内容。）"
            )

    # 第 18 项最后一里（S-CONSDISP 席，2026-09-26）：书面同意的**批准腿**接进生产
    # dispatch。谓词/能力/工厂/帮助主题全在册（base_router RouteRule CONSENT priority 41、
    # capability_registry bot.consent、echo「书面同意」），此前独缺根装配面上这条
    # on_message 承载——「同意卡 批 …」在真机走不到 parse_consent_command
    # （S-CONSENT-APPROVE §⑨-A 的落点）。三件套结构照 host_state 范式；import 刻意落在
    # 函数体内：置顶 import 会把 campus_record_matcher 等登记坐标整体顶漂（同 5a 先例）。
    # gate_provider 每次现读 store 的门句柄——门是惰性建的，构造期快照会把命令面永远
    # 钉成「门没装载」（consent_admin.py:331-336 头注点名的旧坑，装配期快照是本仓反复
    # 踩过的形态）。权限阶梯零复制：这里只投递，判角色/私聊门/防自批/TTL 全在
    # consent.redeem_from_message 唯一真身。
    async def _is_consent_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.CONSENT
        )

    consent_matcher = on_message(rule=_is_consent_event, priority=41, block=True)

    @consent_matcher.handle()
    async def _handle_consent(bot: Bot, event: Event) -> None:
        from .domains.ops.capabilities.consent_admin import (
            build_consent_admin_capability,
        )

        message = _incoming_from_nonebot_event(
            event, bot_id=str(getattr(bot, "self_id", "unknown")),
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
        )
        # 第二通路收编（S-SEAM-ROOT）：投递/诊断/运营告警/回执替换全部经中央缝完成，
        # 调用点只保留 matcher 兜底 finish 判定。gate_provider 仍是每回合现读的 lambda，
        # 门句柄不在装配期快照（S-CONSDISP 头注点名的旧坑）。
        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            diagnostics_store=diagnostics_store,
            capability=build_consent_admin_capability(
                lambda: getattr(runtime_settings, "safety_gate", None)
            ),
            capability_id="bot.consent",
            message=message,
            operational_notifier=_notify_operational_receipt,
        )
        if should_finish_nonebot_matcher(receipt):
            await consent_matcher.finish(
                receipt.public_message or "（处理完成，没有需要展示的内容。）"
            )

    # 审查 C-07：IGNORE 命令形态引导闭环——「/help」类命令形态落 IGNORE
    # 时回一句守岸人引导（60s/会话节流），普通闲聊零波及；限流/安静时间
    # 拦截的静默语义（09-12 实弹裁定）不经过本 matcher。
    from .domains.chat_reply.capabilities.echo import (
        IgnoreGuideGate,
        build_ignore_guide_result,
    )

    _ignore_guide_gate = IgnoreGuideGate()

    async def _is_ignore_command_guide_event(state: T_State, event: Event) -> bool:
        if not _ignore_guide_gate.check_and_mark(str(event.get_session_id())):
            return False  # 节流在 rule 侧：被拦尝试也占名额，只会更保守少回
        decision = _cached_route_decision(state, event, config=config)
        return decision.kind is RouteKind.IGNORE and is_command_form_text(
            event.get_plaintext()
        )

    ignore_guide = on_message(
        rule=_is_ignore_command_guide_event, priority=60, block=True
    )

    @ignore_guide.handle()
    async def _handle_ignore_guide(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot,
            event,
            lambda cfg: lambda message, _decision: build_ignore_guide_result(
                message.request_id
            ),
            "bot.ignore",
            ignore_guide,
        )

    async def _is_media_archive_event(state: T_State, event: Event) -> bool:
        return (
            _cached_route_decision(state, event, config=config).kind
            is RouteKind.MEDIA_ARCHIVE
        )

    media_archive = on_message(rule=_is_media_archive_event, priority=43, block=True)

    async def _enrich_media_archive_message(bot: Bot, event: Event, message: Any) -> None:
        """媒体归档的反查注入（ SnowLuma get_msg / get_forward_msg）。

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
            event, bot_id=str(getattr(bot, "self_id", "unknown")),
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
        )
        await _enrich_media_archive_message(bot, event, message)
        # 第二通路收编（S-SEAM-ROOT）：投递/诊断/运营告警/回执替换全部经中央缝完成，
        # 反查注入后的 message 原样经 message= 交缝。
        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            diagnostics_store=diagnostics_store,
            capability=build_media_archive_capability(
                config,
                vision_provider=vision_provider,
                store=media_archive_store,
            ),
            capability_id="bot.media_archive",
            message=message,
            operational_notifier=_notify_operational_receipt,
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
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
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
        # 第二通路收编（S-SEAM-ROOT）：投递/运营告警/回执替换全部经中央缝完成；
        # 旧形该点无诊断记录、transport 路径不通知，经缝后按中央策略补齐（超集归一）。
        # 私聊改投的 message 复制（model_copy）先于交缝，缝按原样使用。
        receipt = await _run_capability_through_pipeline(
            bot=bot,
            event=event,
            config=config,
            pipeline=pipeline,
            send_queue=send_queue,
            audit_logger=audit_logger,
            receipt_repository=receipt_repository,
            diagnostics_store=diagnostics_store,
            capability=build_meme_library_capability(
                meme_library_store, config,
                mood_valence_fn=lambda: _mood_valence(config),
            ),
            capability_id="bot.meme_library",
            message=message,
            operational_notifier=_notify_operational_receipt,
        )
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

        if capability_id == "bot.runtime_settings":
            # C-01/C-02：自然语言设置——映射层只识别，这里经既有管理员门执行
            # （build_runtime_admin_result 内建 admin 角色门，非管理员拿到统一
            # 的仅管理员提示，与 /bot runtime 同一口径）。ambiguous 时回落
            # 守岸人口语请用户说得更具体。
            if getattr(resolution, "ambiguous", False):
                await natural.finish(
                    "这句话能对上好几个功能开关，跟我说得再具体一点，好吗？"
                )
                return
            setting_key = getattr(resolution, "setting_key", None)
            setting_value = getattr(resolution, "setting_value", None)
            if not setting_key or not setting_value:
                await natural.finish("无法识别的自然语言命令。")
                return
            runtime_command = runtime_set_command_text(setting_key, setting_value)

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return build_runtime_admin_result(
                    settings_manager,
                    effective_instance(config),
                    config,
                    request_id=message.request_id,
                    actor_id=message.sender_id,
                    actor_roles=_decision.actor_roles,
                    command_text=runtime_command,
                    diagnostics_store=diagnostics_store,
                    usage_store=runtime_event_log,
                )

        elif capability_id == "bot.weather":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                return _build_weather_with_backend(config)(synthetic, _decision)

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
                return _build_wiki_with_backend(config)(synthetic, _decision)

        elif capability_id == "bot.eat":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                # 与 wiki 分支同型：归一文本必须重写进 plain_text——原文本可能
                # 带多连 @ 前缀，eat 的 ^ 锚定正则会全部失配掉进随机推荐
                # （实弹 17:01:33「@颜佑° @守岸人 菜谱 西红柿炒鸡蛋」当众推错菜）。
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                return _build_eat_with_backend(config)(synthetic, _decision)

        elif capability_id == "bot.news":
            # F9：自然语言链补 bot.news 分支（新闻类触发此前只有裸命令面）。
            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                synthetic = message.model_copy(update={"plain_text": normalized_text})
                return _build_news_with_backend(config)(synthetic, _decision)

        elif capability_id == "bot.epic":

            def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
                return _build_epic_with_backend(config)(message, _decision)

        elif capability_id == "bot.meme_library":

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
            from .domains.music.capabilities.music import (
                build_music_mode_result,
                extract_music_mode,
            )

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

    @tts.handle()
    async def _handle_tts(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, build_tts_capability, "bot.tts", tts
        )

    @reminder.handle()
    async def _handle_reminder(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, build_reminder_capability, "bot.reminder", reminder
        )

    @daily_assist.handle()
    async def _handle_daily_assist(bot: Bot, event: Event) -> None:
        await _run_simple_capability(
            bot, event, build_daily_assist_capability, "bot.daily_assist", daily_assist
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
        # 百科接地批（2026-09-27 甲+丙）：萌百指令与问句都不再自答——百科正文
        # 唯一进 prompt 的形态是「接地块」，经消息契约 kb_grounding_text/
        # kb_grounding_label 进入人格聊天链的**既有一次生成**（chat.py 装配点
        # 统一过中央件 guard_secondhand_text，拼接零手拼字面量；结构锁在
        # tests/test_kb_grounding_chat.py）。有接地 ⇒ 交聊天链用守岸人的话说；
        # 无接地面（用法提示/候选列表/无条目/网络失败——零百科正文、零链接）
        # 留在命令面兜底。落点全部在已注册坐标（≤:9298）之下 ⇒ 零顶漂。
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
        )
        try:
            query = extract_moegirl_query(message.plain_text)
        except ValueError:
            query = ""
        grounding = None
        if query:
            try:
                grounding, _reason = await asyncio.to_thread(
                    resolve_grounding_for_entity, query, config=config
                )
            except Exception:  # noqa: BLE001 - 接地故障回命令面原链路，不劣化。
                grounding = None
        if grounding is not None:
            await _moegirl_answer_via_chat(
                bot,
                event,
                message.model_copy(
                    update={
                        "kb_grounding_text": grounding.text,
                        "kb_grounding_label": grounding.label,
                    }
                ),
                moegirl,
            )
            return
        await _run_simple_capability(
            bot, event, build_moegirl_capability, "bot.moegirl", moegirl
        )

    async def _moegirl_answer_via_chat(
        bot: Bot,
        event: Event,
        message: IncomingMessage,
        matcher: Any,
    ) -> None:
        """萌百两入口汇合的唯一转发出口：只经 bot.chat 一次生成，绝不自答。

        管线、门控、历史归档、投递与诊断和旧「问句未命中降级」路径逐字同构
        （即原 /bot.chat 主链路），本函数零新增通路；接地块随 message 进
        chat 装配（见 domains/chat_reply/capabilities/chat.py 接地腿）。
        """
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
                await matcher.finish(transport_receipt.public_message)
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
            await matcher.finish(receipt.public_message)

    @moegirl_question.handle()
    async def _handle_moegirl_question(bot: Bot, event: Event) -> None:
        message = _incoming_from_nonebot_event(
            event,
            bot_id=str(getattr(bot, "self_id", "unknown")),
            feature_enabled=(await product_feature_gate.snapshot_async()).enabled,
        )
        try:
            # 本地检索 + 萌百外查都是阻塞面，放线程池；紧超时由 sources 层
            # 预算约束（默认 ≤2×5s），300s TTL 缓存兜重复问法。
            outcome = await asyncio.to_thread(
                question_lookup, message.plain_text, config=config
            )
        except Exception:  # noqa: BLE001 - 查询层异常一律光脚转聊天链，绝不阻断。
            outcome = None
        grounding = (
            outcome.grounding
            if outcome is not None and outcome.status == "hit"
            else None
        )
        if outcome is not None and outcome.degrade_reason:
            # 三类失败留痕（台账 #29⑪ 同口径：归因要能事后查，不能只剩 exc）。
            logging.getLogger(__name__).info(
                "moegirl question no grounding reason=%s entity=%s",
                outcome.degrade_reason,
                outcome.entity[:20],
            )
        chat_message = message
        if grounding is not None:
            chat_message = message.model_copy(
                update={
                    "kb_grounding_text": grounding.text,
                    "kb_grounding_label": grounding.label,
                }
            )
        await _moegirl_answer_via_chat(bot, event, chat_message, moegirl_question)

    # >>> S139-KBSYNC-ALERT-SINK BEGIN（哨兵配对：活性锁 tests/test_ann_observability_s139.py
    # 按这对哨兵把本块真身文本抽出来、注入假装配件 exec——"注入可达"判据，
    # 先例同 WP10-SYNC-DRIFT-WIRING 的 test_sync_drift_activation）
    # kb-sync 告警 sink 装配（S139 缺陷 2）：`set_kb_sync_alert_sink` 自 S112 立形起
    # 全树零注入点（kb_wiki:33 与告警卡 fix_suggestion 都宣称"接入 runtime/alerts"，
    # 实际内存门拒建那张五要素卡今天投不出去，只落一行 WARNING）。
    # 出口唯一复用既有中央告警件 alerts.build_alert_content_sink（300s 抑制器、
    # send_admin_alert_requests 投递——与 sync_drift/voice 探针同一本账，不另开通道）。
    # 门与上方 kb_wiki 调度器注册（_register_kb_wiki_sync_scheduler 调用点）同源：
    # bot_kb_wiki_enabled ∧ root 非空；再叠 pipeline/管理员名单两道缺件即不注入
    # （回到"只打日志"的旧行为，绝不拿 None pipeline 造半个 sink）。
    # 名单口径（S156 条1，覆盖 S139 §7.1 的"超管同集"临时口径）：收件人=运行态
    # 告警同一枚字段 `bot_admin_user_ids`（本文件 `_operational_alert_targets` 的
    # QQ 腿与凭据告警 :1768 都吃它）——内存门告警不另立一本名单账；超管字段
    # 曾是 S139 的临时选择，裁定作废，回潮由 tests/test_kb_ops_parked_three_s156.py
    # 的结构+行为双锁拦截。
    # 落点在 `_register_nonebot_handlers` 之尾、outbound_registry 全部在册坐标
    # （最大值 media_archive :9285）之下 ⇒ 零顶漂（campus/consent 等登记行号不动）。
    try:  # fail-open：观测装配故障绝不炸插件加载。
        if bool(getattr(config, "bot_kb_wiki_enabled", False)) and str(
            getattr(config, "bot_kb_wiki_root", "") or ""
        ).strip():
            from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
                set_kb_sync_alert_sink as _set_kb_sync_alert_sink,
            )
            from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
                build_alert_content_sink as _build_kb_sync_alert_sink,
            )

            _kb_sync_alert_admins = [
                str(item).strip()
                for item in (getattr(config, "bot_admin_user_ids", []) or [])
                if str(item).strip()
            ]
            if pipeline is not None and _kb_sync_alert_admins:
                _set_kb_sync_alert_sink(
                    _build_kb_sync_alert_sink(
                        pipeline,
                        _kb_sync_alert_admins,
                        log=logging.getLogger(__name__),
                    )
                )
    except Exception:  # sink 注不上 ⇒ kb-sync 回到只打日志的旧形态（BLE001 未在此
        # 行发火，RUF100 现算摘掉哑 noqa，S156）。
        logging.getLogger(__name__).exception(
            "kb-sync 告警 sink 注入失败，已跳过（同步主链路不受影响）"
        )
    # <<< S139-KBSYNC-ALERT-SINK END





def _register_emergency_info_scheduler(
    scheduler: Any, config: Any, service: Any, send_queue: Any, gate: Any
) -> dict:
    """紧急信息自动采集轮询（WIRE-B3 · 施工图 §4-面5 5d）。

    每 `bot_emergency_info_poll_interval_seconds` 跑一轮：四源采集 →（条目唯一收口
    `build_emergency_item`，在 collector 内部）→ 定级 → 经 `ReviewGate.submit` 入库
    （D-8 唯一写入点，本函数绝不直写 store）→ 已过审条目经域内 `service/push.py`
    的投递触点发给**本轮现读的订阅目标**（每项按 `matches_subscription` 逐条筛）
    ⊕ `.env` 硬推名单（可选腿，不受订阅条件约束）→ 按 `keep_days` prune。

    四条口径：
    - 域内不 import APScheduler：调度句柄由根装配传入，同步 job 跑在 APScheduler
      线程池（与 G-DIGEST/reminder 同款，不阻塞事件循环），任何异常只记日志。
    - 快照四态（FRESH/STALE/NEVER_FETCHED/FETCH_FAILED）由跨轮持有的 `SnapshotStore`
      记账（装配期建一次），`max_age` 取三轮轮询周期。
    - `min_level` 快照在**域内零消费者**（本席实测 grep：只被 `build_emergency_info_source`
      搬运），消费点因此落在根装配侧；非法字面量不猜档也不拦截（与快照「只搬运不校验」
      的 D-3 口径同向），等级唯一出口仍是 `ReviewGate.publishable_level`。
    - 采集/投递产生的 operational issue 目前只落 `logger.warning`——`issue_sink`
      未接中央告警面前不得宣称「已告警」（施工图 §5-钉死③.4）。
    """
    from datetime import datetime, timedelta

    from .domains.emergency_info.capabilities.emergency_info import (
        matches_emergency_push_group,
        matches_emergency_push_user,
    )
    from .domains.emergency_info.contracts import EmergencyLevel
    from .domains.emergency_info.service.collector import (
        build_emergency_collector_deps,
        run_collection_once,
    )
    from .domains.emergency_info.service.dedupe import is_legal_segment
    from .domains.emergency_info.service.push import (
        EmergencyTarget,
        deliver_emergency,
    )
    from .domains.emergency_info.service.review import ReviewGate
    from .domains.emergency_info.service.snapshot_store import SnapshotStore
    from .domains.emergency_info.service.subscriptions import matches_subscription

    source = service.source
    snapshot_store = SnapshotStore(
        max_age=timedelta(seconds=max(int(source.poll_interval_seconds) * 3, 60))
    )
    min_rank: int | None
    try:
        min_rank = EmergencyLevel(source.min_level).rank if source.min_level else None
    except ValueError:
        min_rank = None

    def _hardwired_targets() -> list[Any]:
        """.env 硬推腿（可选、无订阅过滤）：`*` 是读侧通配，不等于知道有哪些群。"""
        targets: list[Any] = []
        for group_id in sorted(source.push_group_whitelist):
            if group_id == "*" or not matches_emergency_push_group(source, group_id):
                continue
            targets.append(
                EmergencyTarget(
                    target_id=group_id,
                    target_scope=SessionType.GROUP,
                    channel="qq",
                    persona_profile_id=source.persona_profile_id,
                )
            )
        for user_id in sorted(source.push_user_ids):
            if not matches_emergency_push_user(source, user_id):
                continue
            targets.append(
                EmergencyTarget(
                    target_id=user_id,
                    target_scope=SessionType.PRIVATE,
                    channel="qq",
                    persona_profile_id=source.persona_profile_id,
                )
            )
        return targets

    def _push_targets() -> list[tuple[Any, Any]]:
        """本轮投递目标 = 活跃订阅（现读库）⊕ .env 硬推名单，逐项带各自的过滤器。

        每轮 `list_subscriptions()` 现读（**不**在装配期冻结）是这件事的全部意义：
        群里说完条件当轮就生效，不用重启（裁定 3.B）。返回 `(target, rule|None)`，
        `rule=None` 即硬推腿——它只受 `min_level` 全局地板约束，不受订阅条件约束。
        """
        pairs: list[tuple[Any, Any]] = []
        for rule in service.store.list_subscriptions():
            pairs.append(
                (
                    EmergencyTarget(
                        target_id=rule.target_id,
                        target_scope=(
                            SessionType.GROUP
                            if rule.target_scope == "group"
                            else SessionType.PRIVATE
                        ),
                        channel="qq",
                        persona_profile_id=source.persona_profile_id,
                    ),
                    rule,
                )
            )
        for target in _hardwired_targets():
            pairs.append((target, None))
        return pairs

    def _log_issue(issue: Any) -> None:
        logging.getLogger(__name__).warning(
            "紧急信息采集告警（未接中央告警面，仅落日志）：%s/%s",
            getattr(issue, "kind", "unknown"),
            getattr(issue, "reason", ""),
        )

    def _emergency_info_collect_job() -> None:
        now = datetime.now().astimezone()
        try:
            deps = build_emergency_collector_deps(
                persist=lambda item: service.review_gate.submit(item, at=now),
                snapshot=snapshot_store,
                issue_sink=_log_issue,
            )
            # 源门：只跑 bot_emergency_info_sources 显式列出的源，其余一律不取。
            # 2.A（用户 2026-09-20 裁定）：写了没注册的 SOURCE_ID 不再静默滤空——
            # 点名报出来。合法值只取真注册表（SourceTask.source_id），不另抄一份名单。
            registered = {task.source_id for task in deps.sources}
            unknown = sorted(set(source.sources) - registered)
            if unknown:
                logging.getLogger(__name__).warning(
                    "紧急信息源名单含未注册的 SOURCE_ID（本轮被忽略，不采集不投递）：%s；"
                    "当前已注册：%s",
                    ",".join(unknown),
                    ",".join(sorted(registered)),
                )
            deps.sources = tuple(
                task for task in deps.sources if task.source_id in source.sources
            )
            if not deps.sources:
                return
            run_collection_once(deps, now=now)
            # 1.A（用户 2026-09-20 裁定）：闸缺位时保留采集/入库/审核/查询，只关投递。
            # 目标是空集而非"带着 None 去调闸"——绝不退化成不经中央闸的裸 submit（钉死③）。
            if gate is None:
                logging.getLogger(__name__).warning(
                    "紧急信息本轮不投递：中央出站闸未装配（条目已采集入库，查询面不受影响）"
                )
            targets = [] if gate is None else _push_targets()
            matched = 0
            sent = 0
            for item in service.approved_items(limit=50):
                level = ReviewGate.publishable_level(item, now=now)
                if level is None:
                    continue  # 未过审＝不进投递面（D-8），也不替它补档位（D-1）
                if min_rank is not None and level.rank < min_rank:
                    continue
                if not is_legal_segment(item.item_id):
                    # 单行坏 id 不许带走整轮：幂等键拼不出来 ⇒ 点名跳过、继续投别人。
                    logging.getLogger(__name__).warning(
                        "紧急信息条目 %s 的 id 不能作幂等键段，本轮跳过不投",
                        item.item_id,
                    )
                    continue
                graded = item.model_copy(update={"level": level})
                for target, rule in targets:
                    if not is_legal_segment(target.target_id) or not is_legal_segment(
                        target.channel
                    ):
                        # 目标腿与条目腿同罪（dedupe.py:94-102 doctrine、
                        # 2026-09-20 nmc:A1 教训的 target 侧镜像）：键段拼不出的
                        # 目标 id（.env 名单「群号:楼层」、订阅库脏行）单行
                        # 点名跳过，绝不让建键 ValueError 带走整轮投递。
                        logging.getLogger(__name__).warning(
                            "紧急信息目标 %r 的 id/channel 不能作幂等键段，"
                            "本轮跳过该目标（其余目标与条目照常投递）",
                            target.target_id,
                        )
                        continue
                    if rule is not None:
                        # 订阅条件逐条筛（等级∧类型∧地点）；不过筛就不打扰这个目标。
                        if not matches_subscription(graded, rule):
                            continue
                        matched += 1
                        # 命中记账与闸结论无关：这条规则"该不该投给这里"已经判过了，
                        # 之后被安静窗顺延是另一件事，混在一起会让排障看不出是谁的锅。
                        service.store.note_subscription_match(rule.target_key, at=now)
                    verdict = deliver_emergency(
                        send_queue, gate, graded, target, now=now,
                        breach_levels=sorted(source.quiet_breach_levels),
                    )
                    if verdict == "allow":
                        sent += 1
            service.store.prune(keep_days=source.keep_days, now=now)
            if sent or matched:
                logging.getLogger(__name__).info(
                    "紧急信息投递：本轮订阅命中 %s 次、经中央闸投出 %s 条（目标 %s 个）",
                    matched,
                    sent,
                    len(targets),
                )
        except Exception as exc:
            # 带上异常原文：只报类名曾让上面那个「键段含 `:`」的 ValueError 排不了障
            # （台账 #29 ⑪ 同口径：告警 detail 必须自解释）。
            logging.getLogger(__name__).warning(
                "emergency info collection failed: %s: %s",
                type(exc).__name__,
                str(exc)[:200],
                exc_info=exc,
            )

    scheduler.add_job(
        _emergency_info_collect_job,
        "interval",
        id="bot_emergency_info_collect_poll",
        replace_existing=True,
        seconds=max(int(source.poll_interval_seconds), 30),
        misfire_grace_time=source.poll_interval_seconds,
        max_instances=1,
        coalesce=True,
    )
    return {"seconds": max(int(source.poll_interval_seconds), 30)}


async def _dispatch_persona_appearance_if_switched(
    *,
    bot: Bot,
    event: Event,
    config: Config,
    command_text: str,
    settings_manager: Any,
    registry: Any | None = None,
    actor_roles: list[str] | None = None,
) -> None:
    """把「runtime persona switch <id|default>」翻译成一次 QQ 外观下发，逐腿回执（H-1）。

    装配席 S-PERSONA-WIRE（提案=接线点 A，
    .superpowers/sdd/2026-09-27-fullload/logs/SEAT-PERSONA-HOT-wiring.md）：

    - 只认显式 switch 命令形（H-2：情绪/概率自动腿不走这条命令，到不了这里）；
    - ``sent`` 回执不等于切换落地：非管理员驳回、不存在人格等错误路径同样是
      sent——故以主链同判据读回 runtime override 确认，不一致 ⇒ 外观腿静默
      （为什么没切，主链回执已点名，这里绝不追加假随切）；
    - default ⇒ 目标＝主人格（config.bot_persona_profile_id），按册恢复其外观；
    - 外观下发唯一收口件＝apply_persona_profile，出站只走 bot.call_api 唯一口径
      （台账 #60；get_login_info 禁作自称事实源，本件也不读它）；
    - 未入人格册 ⇒ 点名「仅切换了语气，外观未改」，绝不谎称外观已随；
    - 任何异常都不外抛：语气切换主链已回执，外观失败只补一条诚实回执。
    """
    # P-G1（S-ATK-PERSONA，2026-09-27）：唯一触发点的角色门。`sent` 不等于
    # 切换成功——非管理员被驳回的回执同样是 sent，而 override 读回校验用的
    # 恰是「当前生效 id」：任何用户复读 `persona switch <生效id>` 都能把外观
    # 下发腿再驱动一次（QQ 资料写属 bot 账号级动作）。中央角色面含 admin 或
    # super_admin 才动作，其余静默（主链驳回回执已点名，这里绝不追加动作）。
    _roles = {str(role).lower() for role in (actor_roles or [])}
    if "admin" not in _roles and "super_admin" not in _roles:
        return
    tokens = command_text.split()
    # 兼容 "runtime persona switch x" 与别名前缀：定位 persona→switch→target。
    if "persona" not in tokens:
        return
    idx = tokens.index("persona")
    if idx + 1 >= len(tokens) or tokens[idx + 1].lower() != "switch":
        return
    if idx + 2 >= len(tokens):
        return  # 缺 target，交给同步 usage 文案
    target = tokens[idx + 2].strip()
    if not target:
        return

    from .domains.chat_reply.character.persona_profile import (
        apply_persona_profile,
        get_shared_registry,
    )

    # 读回确认（不信 sent 语义）：switch default ⇒ override 应为空；switch <id> ⇒
    # override 应为该 id。--instance 变体按默认实例读数，读不平同样静默，不假下发。
    try:
        override = str(
            settings_manager.get(effective_instance(config)).get_persona_override()
            or ""
        )
    except Exception:  # noqa: BLE001 - 确认态读不到就不下发，绝不让外观腿炸掉命令主链
        return
    if override != ("" if target == "default" else target):
        return

    active_registry = registry if registry is not None else get_shared_registry()
    persona_id = (
        str(getattr(config, "bot_persona_profile_id", "default"))
        if target == "default"
        else target
    )
    record = active_registry.get(persona_id)
    if record is None:
        # 未在册：外观无从下发（只切了语气），如实点名，不谎称外观已随。
        await bot.send(
            event,
            f"人格「{persona_id}」未入人格册（personas/registry/），仅切换了语气，外观未改。",
        )
        return

    try:
        switch_receipt = await apply_persona_profile(
            record,
            call_api=lambda action, params: bot.call_api(action, **params),
        )
    except Exception as exc:  # noqa: BLE001 - 下发腿异常同样必须点名回执，不许沉默装成成功
        await bot.send(
            event,
            f"⚠ 人格「{persona_id}」外观下发中断——一项未落地（{type(exc).__name__}: {exc}）；"
            "语气切换不受影响，请排查后重试。",
        )
        return
    await bot.send(event, switch_receipt.summary())


# ---- S-FIX-INGEST（2026-09-27）：入站两枚 CONFIRMED 的最小修法落点 --------------
# 两枚纯函数 shim 刻意放在**全册登记坐标最大值（media_archive :9298）之下**：
# 根装配上方的在册行号一字不动（campus/liveness 坐标门零顶漂，插删净行数=0）。


def _neutralize_forward_body(text: str) -> str:
    """合并转发正文进任何拼接**之前**的标记消毒（审计 A-ING-1）。

    ``get_forward_msg`` 展开的节点正文/昵称是攻击者可控二手正文；旧实现原样
    拼进 plain_text，检测面对引用族刻意不认领（``security/injection.py``
    ``_SPOOF_DETECTION_NAMES``），ALLOW 分支下伪造 ``[引用回复 层级N …]`` 块
    与 ``format_reply_chain`` 真实产物逐字节同形 → 信任层级/身份冒认。
    本 shim 零判据零正则：消毒真身唯一 = 中央
    ``security/injection.neutralize_internal_markers``（引用链腿对称口径；
    同覆盖 ``chat_record_text`` 归档腿，两处消费者共享同一产出端）。
    """
    from .domains.chat_reply.security.injection import neutralize_internal_markers

    return neutralize_internal_markers(text)


def _reminder_target_from_session_key(session_id: Any, sender_id: str) -> tuple[str, str]:
    """提醒目标归属唯一判据 = 中央 ``domains/core/session_keys.parse_session_key``。

    病根（审计 A-ING-3）：真实入站群键 = ``group_<gid>_<uid>`` 下划线形、不含冒号，
    旧 ``session_id.partition(":")`` 自拆键形判作用域必误判——群提醒被错记到
    发送者私聊作用域（整群语义丢失）。口径：群形（下划线/冒号两形，判据口径
    1/2 条）→ ("group", 群号)；私聊形（裸 uid / ``private_`` 方案段）→
    ("private", uid)；其余形态 fail-closed → ("private", 发送者)。消费点禁再自拆。
    """
    from .domains.core.session_keys import parse_session_key

    parsed = parse_session_key(session_id)
    if parsed.is_group:
        return "group", parsed.group_id
    if parsed.kind == "private" and parsed.user_id:
        return "private", parsed.user_id
    return "private", str(sender_id or "").strip()


_register_nonebot_handlers()

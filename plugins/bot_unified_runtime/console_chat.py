"""控制台交互聊天：最小可执行程序（无需 NapCat / NoneBot 服务器）。

这是"真实测试体验"的第一入口：用同一套统一运行时流水线跑对话。
默认使用 offline static provider；可以在 `.env` 里配置真实模型，
也可以直接用命令行参数覆盖（不会写回 `.env`）。

用法::

    python -m plugins.bot_unified_runtime.console_chat
    python -m plugins.bot_unified_runtime.console_chat --env .env
    python -m plugins.bot_unified_runtime.console_chat \\
        --provider openai_compatible --model deepseek-chat \\
        --base-url https://api.deepseek.com/v1 --api-key sk-xxx
    python -m plugins.bot_unified_runtime.console_chat --message "你好"   # 单轮

交互命令：

- ``/help`` ``/status`` ``/why`` ``/quit`` ``/exit``
- 昵称别名（配置了 ``BOT_RUNTIME_PERSONA_NICKNAME`` 后）：
  ``/岸宝帮助``、``/岸宝状态``、``/岸宝为什么`` 等同义。

说明：本入口不连接 NapCat、不发送 QQ；审计和回执留在进程内；
多轮对话历史保存在内存里，退出即清空。真实机器人路径仍以
NoneBot 入口为准。
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.audit.file_logger import build_audit_with_file_log
from plugins.bot_unified_runtime.capabilities.chat import build_chat_capability
from plugins.bot_unified_runtime.character import build_character_context_provider
from plugins.bot_unified_runtime.character.history import (
    InMemoryConversationHistoryStore,
    SQLiteConversationHistoryRepository,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.config_readiness import (
    llm_generation_parameter_errors,
    persona_context_preflight_errors,
)
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    IncomingMessage,
    ReceiptState,
    SessionType,
)
from plugins.bot_unified_runtime.llm import (
    LLMProvider,
    OpenAICompatibleLLMProvider,
    StaticLLMProvider,
)
from plugins.bot_unified_runtime.llm.model_router import build_model_router
from plugins.bot_unified_runtime.policy import (
    build_quiet_hours_checker,
    build_rate_limiter,
    build_reply_budget_settings,
    build_role_settings,
)
from plugins.bot_unified_runtime.runtime.aliases import (
    CommandAliasResolver,
    build_command_alias_resolver,
)
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.runtime.settings import (
    build_instance_settings_manager,
    build_runtime_settings_store,
    effective_instance,
)
from plugins.bot_unified_runtime.sender import InMemorySendQueue
from plugins.bot_unified_runtime.smoke import load_smoke_config
from plugins.bot_unified_runtime.sources.credential_health import (
    check_credentials_and_report,
)
from plugins.bot_unified_runtime.sources.meme_search import build_meme_search_provider
from plugins.bot_unified_runtime.sources.parsers import extract_http_urls
from plugins.bot_unified_runtime.sources.parse_history import (
    build_parse_history_result,
    build_parse_history_store,
)
from plugins.bot_unified_runtime.sources.downloader import MediaDownloader
from plugins.bot_unified_runtime.output.render_backends import build_render_backend
from plugins.bot_unified_runtime.capabilities.content_parser import (
    build_content_capability,
)
from plugins.bot_unified_runtime.capabilities.music import (
    build_music_capability,
    is_music_command,
)
from plugins.bot_unified_runtime.capabilities.download import (
    build_download_capability,
    is_download_command,
)

_BANNER = """\
============================================================
 鸣潮角色机器人 · 控制台聊天（统一运行时最小可执行程序）
============================================================
 输入 /help 查看命令，/quit 退出。
"""

_HELP_TEMPLATE = """\
可用命令：
  /help      显示本帮助
  /status    显示 provider/模型/环境信息开关摘要（不含密钥）
  /why       解释最近一轮的决策与错误类型
  /quit      退出（也可用 /exit）
  {alias_lines}
直接输入文本即可对话。当前回复最多 {max_messages} 条/轮。
特殊能力：
  发链接     B站/抖音/小红书/油管/推特/小黑盒/米游社/森空岛/库街区/
             Pixiv/Lofter/无差别同人站/米画师/网易画加
             与网易云/QQ/酷我/酷狗/Apple Music/Spotify 链接会自动解析成信息卡
             视频链接还会自动附加分辨率/时长/HDR/音频码率分析
  点歌 <歌名>  搜索并发送歌曲信息卡 + 语音试听（网易云 → Apple → 酷狗 → QQ → 酷我）
  /download <链接>  下载投稿视频（B站/油管/推特/小红书/抖音）并发送文件
  /parse [数量]     查看解析历史
"""

_LOCAL_COMMANDS = ("bot.help", "bot.status", "bot.why")


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


def _apply_cli_overrides(config: Config, args: argparse.Namespace) -> Config:
    updates: dict[str, Any] = {}
    if args.provider:
        updates["bot_chat_provider"] = args.provider
    if args.model:
        updates["bot_chat_model"] = args.model
    if args.model_preset:
        presets = dict(config.bot_model_presets or {}) or {
            "flash": "deepseek-v4-flash",
            "pro": "deepseek-v4-pro",
        }
        updates["bot_chat_model"] = presets.get(
            args.model_preset,
            args.model_preset,
        )
    if args.base_url:
        updates["bot_chat_base_url"] = args.base_url
    if args.api_key:
        updates["bot_chat_api_key"] = args.api_key
    if args.temperature is not None:
        updates["bot_chat_temperature"] = float(args.temperature)
    if args.max_tokens is not None:
        updates["bot_chat_max_tokens"] = int(args.max_tokens)
    return config.model_copy(update=updates)


def _build_llm_provider(config: Config) -> LLMProvider:
    if config.bot_chat_provider == "openai_compatible":
        return OpenAICompatibleLLMProvider(
            api_key=config.bot_chat_api_key,
            model=config.bot_chat_model,
            base_url=config.bot_chat_base_url,
            timeout_seconds=config.bot_chat_timeout_seconds,
        )
    return StaticLLMProvider(model=config.bot_chat_model)


def _build_history_store(config: Config):
    if config.bot_history_enabled and config.bot_history_db_path.strip():
        return SQLiteConversationHistoryRepository(
            config.bot_history_db_path,
            max_items=config.bot_history_max_items,
        )
    return InMemoryConversationHistoryStore()


def _build_runtime(
    config: Config,
    history_store: Any,
    runtime_settings: Any,
) -> tuple[RuntimePipeline, Any, dict[str, Any]]:
    audit_logger = build_audit_with_file_log(
        InMemoryAuditLogger(),
        config.bot_audit_log_file,
        max_bytes=config.bot_audit_log_max_bytes,
    )
    send_queue = InMemorySendQueue(audit_logger=audit_logger)
    pipeline = RuntimePipeline(
        send_queue=send_queue,
        audit_logger=audit_logger,
        reply_budget_settings=build_reply_budget_settings(config),
        role_settings=build_role_settings(config),
        group_command_prefix=config.bot_runtime_group_command_prefix,
        runtime_enabled=config.bot_runtime_enabled,
        rate_limiter=build_rate_limiter(config),
        quiet_hours_checker=build_quiet_hours_checker(config),
        forward_min_chars=config.bot_render_forward_min_chars,
        forward_max_nodes=config.bot_render_forward_max_nodes,
        forward_node_chars=config.bot_render_forward_node_chars,
    )
    capability = build_chat_capability(
        character_provider=build_character_context_provider(
            config,
            conversation_history_provider=history_store,
            runtime_settings=runtime_settings,
        ),
        llm_provider=_build_llm_provider(config),
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
    stores = {
        "parse_history": build_parse_history_store(config),
        "render_backend": build_render_backend(config.bot_card_render_backend),
        "downloader": MediaDownloader(
            cookies_file=config.bot_cookies_file,
            proxy=config.bot_download_proxy,
            download_dir=config.bot_download_dir,
            max_bytes=config.bot_download_max_bytes,
            max_height=config.bot_download_max_height,
            timeout_seconds=config.bot_download_timeout_seconds,
        ),
    }
    return pipeline, capability, stores


def _reply_text(send_queue: InMemorySendQueue, request_id: str) -> str | None:
    for request in reversed(send_queue.sent_requests):
        if request.request_id != request_id:
            continue
        content_ref = request.content.content_ref
        text = content_ref.get("text")
        if not text:
            text = request.content.text_fallback
        return str(text or "").strip() or None
    return None


def _last_receipt_summary(
    receipt: DeliveryReceipt | None,
    tags: list[str],
) -> str:
    if receipt is None:
        return "（还没有跑过一轮对话，先发一句话试试。）"
    lines = [
        f"最近一轮：state={receipt.state.value}",
        f"transport={receipt.transport}",
    ]
    if receipt.public_message:
        lines.append(f"公开说明：{receipt.public_message}")
    error_kinds = sorted(
        tag.removeprefix("llm_error:")
        for tag in tags
        if tag.startswith("llm_error:")
    )
    if error_kinds:
        lines.append(f"LLM 错误类型：{','.join(error_kinds)}")
    if "rate_limited" in tags:
        lines.append("命中限速：已在调用 LLM 前阻断。")
    if "quiet_hours_blocked" in tags:
        lines.append("命中安静时间：已在调用 LLM 前阻断。")
    if "llm_output_trimmed" in tags:
        lines.append("模型输出超过回复预算，已收口。")
    if "prompt_injection" in tags:
        lines.append("命中提示注入防护。")
    return "\n".join(lines)


def _status_summary(config: Config, runtime_settings: Any | None = None) -> str:
    provider = config.bot_chat_provider
    model = config.bot_chat_model
    if provider == "static":
        llm_line = f"LLM：{provider}/{model}（离线静态回复，不联网）"
    else:
        key_state = "已配置" if config.bot_chat_api_key else "未配置"
        llm_line = (
            f"LLM：{provider}/{model}（API key {key_state}，"
            f"endpoint={config.bot_chat_base_url}）"
        )
    weather_line = (
        "开启"
        if config.bot_weather_enabled
        and config.bot_weather_latitude
        and config.bot_weather_longitude
        else "关闭（配置 BOT_WEATHER_ENABLED + 经纬度后开启）"
    )
    nicknames: list[str] = []
    if runtime_settings is not None:
        nicknames = runtime_settings.list_nicknames()
    configured = list(getattr(config, "bot_persona_nicknames", []) or [])
    legacy_nickname = str(
        getattr(config, "bot_runtime_persona_nickname", "")
    ).strip()
    if legacy_nickname:
        configured.insert(0, legacy_nickname)
    legacy_nicknames = list(
        getattr(config, "bot_runtime_persona_nicknames", []) or []
    )
    configured.extend(
        str(item).strip() for item in legacy_nicknames if str(item).strip()
    )
    all_nicknames = list(dict.fromkeys([*configured, *nicknames]))
    nickname_line = ",".join(all_nicknames) if all_nicknames else "未配置"
    overrides: dict[str, Any] = {}
    if runtime_settings is not None:
        overrides = runtime_settings.list_overrides()
    override_line = (
        "；".join(f"{key}={value}" for key, value in sorted(overrides.items()))
        if overrides
        else "无（使用 .env）"
    )
    audit_line = (
        f"审计：内存，文件日志：{'开启(' + config.bot_audit_log_file + ')' if config.bot_audit_log_file else '关闭'}"
    )
    credential_line = "凭据健康：未配置凭据"
    if config.bot_credentials_file:
        try:
            reports = check_credentials_and_report(config, probe=False)
            problems = [report.ref_id for report in reports if report.needs_reauth]
            credential_line = (
                f"凭据健康：{len(reports)} 个引用"
                + (f"，需要重新登录：{','.join(problems)}" if problems else "，正常")
            )
        except Exception:
            credential_line = "凭据健康：检查失败"
    return "\n".join(
        [
            llm_line,
            f"人格：{config.bot_persona_display_name}（{config.bot_persona_profile_id}），昵称别名：{nickname_line}",
            f"运行时覆盖：{override_line}",
            f"人格文件数：{len(config.bot_persona_files)}，知识文件数：{len(config.bot_knowledge_files)}，术语表文件数：{len(config.bot_glossary_files)}",
            f"环境信息：时间/日期/节气/节日 {'开启' if config.bot_temporal_enabled else '关闭'}（{config.bot_timezone}），天气：{weather_line}",
            f"动作括号：{'开启' if config.bot_persona_action_brackets else '关闭'}，时梗备注：{'开启' if config.bot_trend_enabled else '关闭'}（默认关闭，问梗时按需搜索）",
            f"关系档案：{'已配置' if config.bot_user_profiles_file else '未配置（陌生人基线，互动自动升级）'}，共享群上下文：{'开启' if config.bot_shared_group_context_enabled else '关闭'}",
            f"梗搜索：{'开启（二次元平台白名单）' if config.bot_meme_search_enabled else '关闭'}，长回复合并转发：≥{config.bot_render_forward_min_chars} 字自动切块",
            f"记忆：{'开启' if config.bot_memory_enabled else '关闭'}，历史：{'开启' if config.bot_history_enabled else '关闭（REPL 内存多轮）'}",
            f"限速：{'开启' if config.bot_rate_limit_enabled else '关闭'}，安静时间：{'开启' if config.bot_quiet_hours_enabled else '关闭'}",
            audit_line,
            credential_line,
        ]
    )


def _alias_help_lines(alias_resolver: CommandAliasResolver) -> str:
    if not alias_resolver.nicknames:
        return "  昵称别名未配置：设置 BOT_RUNTIME_PERSONA_NICKNAMES 后可用 /<昵称>帮助 等。"
    joined = "、".join(alias_resolver.nicknames)
    return (
        f"  昵称别名（{joined}）："
        f"/{alias_resolver.nicknames[0]}帮助、"
        f"/{alias_resolver.nicknames[0]}状态、"
        f"/{alias_resolver.nicknames[0]}为什么"
    )


def _help_text(config: Config, alias_resolver: CommandAliasResolver) -> str:
    return _HELP_TEMPLATE.format(
        alias_lines=_alias_help_lines(alias_resolver),
        max_messages=config.bot_reply_private_default_max_messages,
    )


def _record_turn(history_store: Any, *, request_id: str, role: str, text: str) -> None:
    try:
        history_store.append_turn(
            request_id=request_id,
            platform="console",
            adapter="console-repl",
            bot_id="console-bot",
            session_id="console:repl",
            sender_id="console-user",
            role=role,
            text=text,
        )
    except Exception:
        return


def _route_for_message(
    config: Config,
    text: str,
    chat_capability: Any,
    stores: dict[str, Any],
) -> tuple[Any, str]:
    """按消息内容选择能力：点歌 → bot.music；带链接 → bot.content；否则聊天。"""
    if config.bot_music_enabled and is_music_command(text):
        return build_music_capability(config), "bot.music"
    if config.bot_content_parse_enabled and extract_http_urls(text):
        return (
            build_content_capability(
                config,
                parse_history_store=stores.get("parse_history"),
                downloader=stores.get("downloader"),
                render_backend=stores.get("render_backend"),
                card_dir=config.bot_card_render_dir,
            ),
            "bot.content",
        )
    return chat_capability, "bot.chat"


def run_once(
    config: Config,
    message_text: str,
    *,
    history_store: Any | None = None,
    runtime_settings: Any | None = None,
) -> DeliveryReceipt:
    settings = runtime_settings or build_runtime_settings_store(config)
    store = history_store or _build_history_store(config)
    pipeline, chat_capability, stores = _build_runtime(config, store, settings)
    message = IncomingMessage(
        platform="console",
        adapter="console-repl",
        bot_id="console-bot",
        session_id="console:repl",
        session_type=SessionType.PRIVATE,
        sender_id="console-user",
        sender_display_name="控制台用户",
        plain_text=message_text,
        raw_segments=[{"type": "text", "data": {"text": message_text}}],
        mentions_bot=True,
    )
    _record_turn(store, request_id=message.request_id, role="user", text=message_text)
    capability, capability_id = _route_for_message(
        config, message_text, chat_capability, stores
    )
    receipt = pipeline.handle(message, capability, capability_id=capability_id)
    if receipt.state is ReceiptState.SENT:
        text = _reply_text(pipeline.send_queue, message.request_id)
        if text:
            print(text)
            _record_turn(
                store,
                request_id=message.request_id,
                role="assistant",
                text=text,
            )
    else:
        print(receipt.public_message or f"[{receipt.state.value}]")
    return receipt


def run_interactive(config: Config) -> int:
    settings_manager = build_instance_settings_manager(config)
    runtime_settings = settings_manager.get(effective_instance(config))
    alias_resolver = build_command_alias_resolver(
        config,
        extra_nicknames=runtime_settings.list_nicknames(),
    )
    history_store = _build_history_store(config)
    pipeline, capability, stores = _build_runtime(
        config, history_store, runtime_settings
    )
    group_mode = False
    last_receipt: DeliveryReceipt | None = None
    last_tags: list[str] = []
    print(_BANNER)
    print(_status_summary(config, runtime_settings))
    print(_help_text(config, alias_resolver))
    while True:
        try:
            raw = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        command = raw.lower()
        if command in {"/quit", "/exit"}:
            break
        if command == "/help":
            print(_help_text(config, alias_resolver))
            continue
        if command == "/status":
            print(_status_summary(config, runtime_settings))
            continue
        if command == "/why":
            print(_last_receipt_summary(last_receipt, last_tags))
            continue
        if command == "/parse" or command.startswith("/parse "):
            result = build_parse_history_result(
                stores["parse_history"],
                request_id="console-parse",
                query=command.removeprefix("/parse").strip(),
            )
            print(result.body)
            continue
        if command.startswith("/download ") or command.startswith("下载 "):
            message = IncomingMessage(
                platform="console",
                adapter="console-repl",
                bot_id="console-bot",
                session_id="console:repl",
                session_type=SessionType.PRIVATE,
                sender_id="console-user",
                sender_display_name="控制台用户",
                plain_text=raw,
                raw_segments=[{"type": "text", "data": {"text": raw}}],
                mentions_bot=True,
            )
            receipt = pipeline.handle(
                message,
                build_download_capability(config, downloader=stores["downloader"]),
                capability_id="bot.download",
            )
            text = _reply_text(pipeline.send_queue, message.request_id)
            print(text or receipt.public_message or f"[{receipt.state.value}]")
            continue
        if command == "/group":
            group_mode = True
            print("[系统] 已切换到群聊模拟：消息按群聊策略处理（回复预算 1 条）。/private 返回私聊。")
            continue
        if command == "/private":
            group_mode = False
            print("[系统] 已返回私聊模式。")
            continue
        if command == "/alert" or command.startswith("/alert "):
            print(_run_console_alert(config, command))
            continue
        if (
            command.startswith("/runtime")
            or command.startswith("/nickname")
            or command.startswith("/persona")
        ):
            print(
                _run_console_runtime_admin(
                    config,
                    settings_manager,
                    effective_instance(config),
                    raw,
                )
            )
            continue
        alias = alias_resolver.resolve(raw)
        if alias is not None:
            if alias.capability_id in _LOCAL_COMMANDS:
                if alias.capability_id == "bot.help":
                    print(_help_text(config, alias_resolver))
                elif alias.capability_id == "bot.status":
                    print(_status_summary(config, runtime_settings))
                else:
                    print(_last_receipt_summary(last_receipt, last_tags))
            else:
                print(
                    f"[系统] {alias.capability_id} 在控制台模式暂未实现；"
                    "真实 NoneBot 入口已支持该命令。"
                )
            continue
        if group_mode:
            session_id = "group:10001"
            session_type = SessionType.GROUP
            group_id = "10001"
        else:
            session_id = "console:repl"
            session_type = SessionType.PRIVATE
            group_id = ""
        message = IncomingMessage(
            platform="console",
            adapter="console-repl",
            bot_id="console-bot",
            session_id=session_id,
            session_type=session_type,
            sender_id="console-user",
            sender_display_name="控制台用户",
            group_id=group_id,
            plain_text=raw,
            raw_segments=[{"type": "text", "data": {"text": raw}}],
            mentions_bot=True,
        )
        _record_turn(
            history_store, request_id=message.request_id, role="user", text=raw
        )
        handle_capability, handle_id = _route_for_message(
            config, raw, capability, stores
        )
        receipt = pipeline.handle(
            message, handle_capability, capability_id=handle_id
        )
        last_receipt = receipt
        if receipt.state is ReceiptState.SENT:
            text = _reply_text(pipeline.send_queue, message.request_id)
            print(f"\n{config.bot_persona_display_name}> {text or '（空回复，已拦截）'}")
            if text:
                _record_turn(
                    history_store,
                    request_id=message.request_id,
                    role="assistant",
                    text=text,
                )
            sent_request = next(
                (
                    request
                    for request in reversed(pipeline.send_queue.sent_requests)
                    if request.request_id == message.request_id
                ),
                None,
            )
            last_tags = list(sent_request.audit_tags) if sent_request else []
        else:
            print(f"\n[系统] {receipt.public_message or receipt.state.value}")
            last_tags = []
    return 0


def _run_console_alert(config: Config, command: str) -> str:
    try:
        reports = check_credentials_and_report(
            config,
            probe="--probe" in command,
        )
    except Exception as exc:  # noqa: BLE001
        return f"[凭据检查失败] {type(exc).__name__}"
    if not reports:
        return "未配置任何凭据引用，无需检查。"
    lines = [
        f"{report.ref_id}：{report.state}"
        + ("（需要重新登录）" if report.needs_reauth else "")
        + f" - {report.detail}"
        for report in reports
    ]
    return "\n".join(lines)


def _run_console_runtime_admin(
    config: Config,
    settings_manager: Any,
    default_instance: str,
    raw: str,
) -> str:
    from plugins.bot_unified_runtime.capabilities.runtime_admin import (
        build_runtime_admin_result,
    )

    command_text = raw.strip().lstrip("/")
    if command_text.startswith(("nickname", "persona", "model")):
        command_text = f"runtime {command_text}"
    result = build_runtime_admin_result(
        settings_manager,
        default_instance,
        config,
        request_id="console-admin",
        actor_roles=["admin", "user"],
        command_text=command_text.removeprefix("runtime").strip(),
    )
    return result.body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="控制台聊天（最小可执行程序）")
    parser.add_argument("--env", default=None, help="环境文件路径，默认 .env / .env.example")
    parser.add_argument(
        "--message",
        default="",
        help="单轮模式：只跑这一条消息并退出（非交互）。",
    )
    parser.add_argument(
        "--provider",
        choices=["static", "openai_compatible"],
        default=None,
        help="临时覆盖 LLM provider（不写 .env）。",
    )
    parser.add_argument("--model", default=None, help="临时覆盖模型名。")
    parser.add_argument(
        "--model-preset",
        default=None,
        help="模型预设：flash/pro（默认 deepseek-v4-flash / deepseek-v4-pro，可用 BOT_MODEL_PRESETS 覆盖）。",
    )
    parser.add_argument("--base-url", default=None, help="临时覆盖 OpenAI 兼容 base_url。")
    parser.add_argument("--api-key", default=None, help="临时覆盖 API key（仅本进程）。")
    parser.add_argument("--temperature", type=float, default=None, help="临时覆盖温度 0.0-2.0。")
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="临时覆盖最大 token 数；0 = 不设上限（不传给 API）。",
    )
    args = parser.parse_args(argv)
    _reconfigure_stdio()
    try:
        config = load_smoke_config(args.env)
        config = _apply_cli_overrides(config, args)
    except Exception as exc:  # pragma: no cover - 配置解析失败属于运维问题。
        print(f"[配置错误] 无法读取环境配置：{exc}")
        return 2
    if args.message:
        receipt = run_once(config, args.message)
        return 0 if receipt.state is ReceiptState.SENT else 1
    return run_interactive(config)


if __name__ == "__main__":
    raise SystemExit(main())

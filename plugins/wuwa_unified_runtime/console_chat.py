"""控制台交互聊天：最小可执行程序（无需 NapCat / NoneBot 服务器）。

这是"真实测试体验"的第一入口：用同一套统一运行时流水线跑对话。
默认使用 offline static provider；可以在 `.env` 里配置真实模型，
也可以直接用命令行参数覆盖（不会写回 `.env`）。

用法::

    python -m plugins.wuwa_unified_runtime.console_chat
    python -m plugins.wuwa_unified_runtime.console_chat --env .env
    python -m plugins.wuwa_unified_runtime.console_chat \\
        --provider openai_compatible --model deepseek-chat \\
        --base-url https://api.deepseek.com/v1 --api-key sk-xxx
    python -m plugins.wuwa_unified_runtime.console_chat --message "你好"   # 单轮

交互命令：

- ``/help`` ``/status`` ``/why`` ``/quit`` ``/exit``
- 昵称别名（配置了 ``WUWA_RUNTIME_PERSONA_NICKNAME`` 后）：
  ``/岸宝帮助``、``/岸宝状态``、``/岸宝为什么`` 等同义。

说明：本入口不连接 NapCat、不发送 QQ；审计和回执留在进程内；
多轮对话历史保存在内存里，退出即清空。真实机器人路径仍以
NoneBot 入口为准。
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from plugins.wuwa_unified_runtime.audit import InMemoryAuditLogger
from plugins.wuwa_unified_runtime.capabilities.chat import build_chat_capability
from plugins.wuwa_unified_runtime.character import build_character_context_provider
from plugins.wuwa_unified_runtime.character.history import (
    InMemoryConversationHistoryStore,
    SQLiteConversationHistoryRepository,
)
from plugins.wuwa_unified_runtime.config import Config
from plugins.wuwa_unified_runtime.config_readiness import (
    llm_generation_parameter_errors,
    persona_context_preflight_errors,
)
from plugins.wuwa_unified_runtime.contracts import (
    DeliveryReceipt,
    IncomingMessage,
    ReceiptState,
    SessionType,
)
from plugins.wuwa_unified_runtime.llm import (
    LLMProvider,
    OpenAICompatibleLLMProvider,
    StaticLLMProvider,
)
from plugins.wuwa_unified_runtime.policy import (
    build_quiet_hours_checker,
    build_rate_limiter,
    build_reply_budget_settings,
    build_role_settings,
)
from plugins.wuwa_unified_runtime.runtime.aliases import (
    CommandAliasResolver,
    build_command_alias_resolver,
)
from plugins.wuwa_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.wuwa_unified_runtime.sender import InMemorySendQueue
from plugins.wuwa_unified_runtime.smoke import load_smoke_config

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
"""

_LOCAL_COMMANDS = ("wuwa.help", "wuwa.status", "wuwa.why")


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
        updates["wuwa_chat_provider"] = args.provider
    if args.model:
        updates["wuwa_chat_model"] = args.model
    if args.base_url:
        updates["wuwa_chat_base_url"] = args.base_url
    if args.api_key:
        updates["wuwa_chat_api_key"] = args.api_key
    if args.temperature is not None:
        updates["wuwa_chat_temperature"] = float(args.temperature)
    if args.max_tokens is not None:
        updates["wuwa_chat_max_tokens"] = int(args.max_tokens)
    return config.model_copy(update=updates)


def _build_llm_provider(config: Config) -> LLMProvider:
    if config.wuwa_chat_provider == "openai_compatible":
        return OpenAICompatibleLLMProvider(
            api_key=config.wuwa_chat_api_key,
            model=config.wuwa_chat_model,
            base_url=config.wuwa_chat_base_url,
            timeout_seconds=config.wuwa_chat_timeout_seconds,
        )
    return StaticLLMProvider(model=config.wuwa_chat_model)


def _build_history_store(config: Config):
    if config.wuwa_history_enabled and config.wuwa_history_db_path.strip():
        return SQLiteConversationHistoryRepository(
            config.wuwa_history_db_path,
            max_items=config.wuwa_history_max_items,
        )
    return InMemoryConversationHistoryStore()


def _build_runtime(config: Config, history_store: Any) -> tuple[RuntimePipeline, Any]:
    audit_logger = InMemoryAuditLogger()
    send_queue = InMemorySendQueue(audit_logger=audit_logger)
    pipeline = RuntimePipeline(
        send_queue=send_queue,
        audit_logger=audit_logger,
        reply_budget_settings=build_reply_budget_settings(config),
        role_settings=build_role_settings(config),
        group_command_prefix=config.wuwa_runtime_group_command_prefix,
        runtime_enabled=config.wuwa_runtime_enabled,
        rate_limiter=build_rate_limiter(config),
        quiet_hours_checker=build_quiet_hours_checker(config),
    )
    capability = build_chat_capability(
        character_provider=build_character_context_provider(
            config,
            conversation_history_provider=history_store,
        ),
        llm_provider=_build_llm_provider(config),
        temperature=config.wuwa_chat_temperature,
        max_tokens=config.wuwa_chat_max_tokens,
        context_preflight_errors=persona_context_preflight_errors(config),
        llm_preflight_errors=llm_generation_parameter_errors(config),
        output_max_chars_per_message=config.wuwa_reply_max_chars_per_message,
    )
    return pipeline, capability


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


def _status_summary(config: Config) -> str:
    provider = config.wuwa_chat_provider
    model = config.wuwa_chat_model
    if provider == "static":
        llm_line = f"LLM：{provider}/{model}（离线静态回复，不联网）"
    else:
        key_state = "已配置" if config.wuwa_chat_api_key else "未配置"
        llm_line = (
            f"LLM：{provider}/{model}（API key {key_state}，"
            f"endpoint={config.wuwa_chat_base_url}）"
        )
    weather_line = (
        "开启"
        if config.wuwa_weather_enabled
        and config.wuwa_weather_latitude
        and config.wuwa_weather_longitude
        else "关闭（配置 WUWA_WEATHER_ENABLED + 经纬度后开启）"
    )
    nickname = config.wuwa_runtime_persona_nickname or "未配置"
    return "\n".join(
        [
            llm_line,
            f"人格：{config.wuwa_persona_display_name}（{config.wuwa_persona_profile_id}），昵称别名：{nickname}",
            f"人格文件数：{len(config.wuwa_persona_files)}，知识文件数：{len(config.wuwa_knowledge_files)}",
            f"环境信息：时间/日期/节气/节日 {'开启' if config.wuwa_temporal_enabled else '关闭'}（{config.wuwa_timezone}），天气：{weather_line}",
            f"动作括号：{'开启' if config.wuwa_persona_action_brackets else '关闭'}，时梗备注：{'开启' if config.wuwa_trend_enabled else '关闭'}",
            f"记忆：{'开启' if config.wuwa_memory_enabled else '关闭'}，历史：{'开启' if config.wuwa_history_enabled else '关闭（REPL 内存多轮）'}",
            f"限速：{'开启' if config.wuwa_rate_limit_enabled else '关闭'}，安静时间：{'开启' if config.wuwa_quiet_hours_enabled else '关闭'}",
        ]
    )


def _alias_help_lines(alias_resolver: CommandAliasResolver) -> str:
    if not alias_resolver.nickname:
        return "  昵称别名未配置：设置 WUWA_RUNTIME_PERSONA_NICKNAME 后可用 /<昵称>帮助 等。"
    return (
        f"  昵称别名：/{alias_resolver.nickname}帮助、"
        f"/{alias_resolver.nickname}状态、/{alias_resolver.nickname}为什么"
    )


def _help_text(config: Config, alias_resolver: CommandAliasResolver) -> str:
    return _HELP_TEMPLATE.format(
        alias_lines=_alias_help_lines(alias_resolver),
        max_messages=config.wuwa_reply_private_default_max_messages,
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


def run_once(
    config: Config,
    message_text: str,
    *,
    history_store: Any | None = None,
) -> DeliveryReceipt:
    store = history_store or _build_history_store(config)
    pipeline, capability = _build_runtime(config, store)
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
    receipt = pipeline.handle(message, capability, capability_id="wuwa.chat")
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
    alias_resolver = build_command_alias_resolver(config)
    history_store = _build_history_store(config)
    pipeline, capability = _build_runtime(config, history_store)
    last_receipt: DeliveryReceipt | None = None
    last_tags: list[str] = []
    print(_BANNER)
    print(_status_summary(config))
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
            print(_status_summary(config))
            continue
        if command == "/why":
            print(_last_receipt_summary(last_receipt, last_tags))
            continue
        alias = alias_resolver.resolve(raw)
        if alias is not None:
            if alias.capability_id in _LOCAL_COMMANDS:
                if alias.capability_id == "wuwa.help":
                    print(_help_text(config, alias_resolver))
                elif alias.capability_id == "wuwa.status":
                    print(_status_summary(config))
                else:
                    print(_last_receipt_summary(last_receipt, last_tags))
            else:
                print(
                    f"[系统] {alias.capability_id} 在控制台模式暂未实现；"
                    "真实 NoneBot 入口已支持该命令。"
                )
            continue
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
        _record_turn(
            history_store, request_id=message.request_id, role="user", text=raw
        )
        receipt = pipeline.handle(message, capability, capability_id="wuwa.chat")
        last_receipt = receipt
        if receipt.state is ReceiptState.SENT:
            text = _reply_text(pipeline.send_queue, message.request_id)
            print(f"\n{config.wuwa_persona_display_name}> {text or '（空回复，已拦截）'}")
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
    parser.add_argument("--base-url", default=None, help="临时覆盖 OpenAI 兼容 base_url。")
    parser.add_argument("--api-key", default=None, help="临时覆盖 API key（仅本进程）。")
    parser.add_argument("--temperature", type=float, default=None, help="临时覆盖温度 0.0-2.0。")
    parser.add_argument("--max-tokens", type=int, default=None, help="临时覆盖最大 token 数。")
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

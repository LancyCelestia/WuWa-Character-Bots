"""重启后真机验收脚本（E2E acceptance）。

目的：bot 重启后，向真实群/私聊逐条发送「所有可能的消息种类」（文本/长文本/
多段、解析卡、点歌候选卡、全球股指 18 指数全量、财经/科技快报全量、天气+预警、
随机图、占卜、help 卡、好感度卡、提醒查询），供用户回 ``test`` 人工验收。

真实管线（不绕过）：
    合成 IncomingMessage
      → RuntimePipeline.handle（policy → decision → capability → review
        → render_reviewed_output → 合并转发/分块 → SendRequest → send_queue.submit）
    与 plugins/bot_unified_runtime/__init__.py 注册的各 handler 走同一管道；
    能力构造函数也按 __init__.py 的装配方式原样复用（只读 import，零改动）。

安全阀：
- 默认 **DRY-RUN**：send_queue 为进程内 InMemorySendQueue，绝无真实发送路径；
  逐项打印「将发内容」（渲染后的 content_type / 文本预览 / 媒体计数）。
- ``--execute`` 才真发：send_queue 换成 build_send_queue(config) 的 SQLite 队列
  （与在线 bot 的 send-queue worker 共库），入队后由 bot worker 真实投递。
  若 .env 未启用持久化发送队列则拒绝执行（InMemory 队列跨进程不可达）。
- ``--target-group`` / ``--target-user`` 必填其一；群目标必须已在运行时 store
  的 BOT_GROUP_WHITE1 白名单（与 pipeline 同源读取），否则拒绝执行。
- 逐项打印 ``[序号] 能力 → 发送结果回执``：state/transport/skipped 原样可见，
  能力层静默降级（如随机图未配置目录）也会如实反映为 skipped/silent。

示例::

    python scripts/e2e_acceptance.py --target-group 123456          # DRY-RUN
    python scripts/e2e_acceptance.py --target-group 123456 --execute
    python scripts/e2e_acceptance.py --target-user 10001 --execute --only help,affinity
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 直接以 `python scripts/e2e_acceptance.py` 运行时，sys.path[0] 是 scripts/，
# 需要显式把仓库根加进搜索路径才能 import plugins.*（与 knowledge_bench 同式）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.capabilities.affinity import build_affinity_capability
from plugins.bot_unified_runtime.capabilities.content_parser import (
    build_content_capability,
)
from plugins.bot_unified_runtime.capabilities.divination import (
    build_divination_capability,
)
from plugins.bot_unified_runtime.capabilities.echo import build_help_result
from plugins.bot_unified_runtime.capabilities.market import build_market_capability
from plugins.bot_unified_runtime.capabilities.music import build_music_capability
from plugins.bot_unified_runtime.capabilities.news import build_news_capability
from plugins.bot_unified_runtime.capabilities.randpic import build_randpic_capability
from plugins.bot_unified_runtime.capabilities.reminder import (
    build_reminder_capability,
)
from plugins.bot_unified_runtime.capabilities.weather import build_weather_capability
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.output.render_backends import build_render_backend
from plugins.bot_unified_runtime.policy import (
    build_quiet_hours_checker,
    build_rate_limiter,
    build_reply_budget_settings,
    build_role_settings,
)
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.runtime.settings import (
    build_instance_settings_manager,
    effective_instance,
)
from plugins.bot_unified_runtime.sender import InMemorySendQueue
from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue
from plugins.bot_unified_runtime.smoke import load_smoke_config
from plugins.bot_unified_runtime.sources.parsers import (
    build_cookie_provider,
    music_candidate_providers,
)

BILI_SAMPLE_URL = "https://www.bilibili.com/video/BV1GJ411x7h7"
DEFAULT_INTERVAL_SECONDS = 8.0
PREVIEW_MAX_CHARS = 240


class E2eSafetyError(RuntimeError):
    """安全阀拒绝执行（目标缺失/非 white1 群/队列不满足真发条件）。"""


# --------------------------------------------------------------------------
# 运行时装配（镜像 __init__.py 的注册期装配，仅取本脚本需要的子集）
# --------------------------------------------------------------------------


@dataclass
class E2eRuntime:
    """装配产物：config / 渲染后端 / 运行时设置 / 模式开关。"""

    config: Any
    runtime_settings: Any
    render_backend: Any | None
    execute: bool
    city: str
    bot_id: str
    sender_id: str


def build_runtime(
    *,
    env_file: str | None,
    execute: bool,
    city: str,
    bot_id: str,
    sender_id: str,
) -> E2eRuntime:
    config = load_smoke_config(env_file)
    settings_manager = build_instance_settings_manager(config)
    runtime_settings = settings_manager.get(effective_instance(config))
    render_backend = (
        build_render_backend(config.bot_card_render_backend)
        if bool(getattr(config, "bot_card_render_enabled", True))
        else None
    )
    resolved_bot_id = str(
        bot_id or getattr(config, "bot_gscore_bot_self_id", "") or ""
    ).strip()
    return E2eRuntime(
        config=config,
        runtime_settings=runtime_settings,
        render_backend=render_backend,
        execute=execute,
        city=city,
        bot_id=resolved_bot_id,
        sender_id=sender_id,
    )


def build_pipeline(runtime: E2eRuntime, send_queue: Any) -> RuntimePipeline:
    """与 __init__.py 注册函数内同一套 RuntimePipeline 装配（子集）。"""
    config = runtime.config
    return RuntimePipeline(
        send_queue=send_queue,
        audit_logger=InMemoryAuditLogger(),
        reply_budget_settings=build_reply_budget_settings(config),
        role_settings=build_role_settings(config),
        group_command_prefix=config.bot_runtime_group_command_prefix,
        runtime_enabled=config.bot_runtime_enabled,
        rate_limiter=build_rate_limiter(config),
        quiet_hours_checker=build_quiet_hours_checker(config),
        forward_min_chars=config.bot_render_forward_min_chars,
        forward_max_nodes=config.bot_render_forward_max_nodes,
        forward_node_chars=config.bot_render_forward_node_chars,
        forward_min_nodes=int(
            getattr(config, "bot_render_forward_min_nodes", 4) or 4
        ),
        forward_sender_name=(
            getattr(config, "bot_persona_display_name", "") or "守岸人"
        ),
        group_auto_reply_enabled=False,
        group_auto_reply_probability=0.0,
    )


def choose_send_queue(
    runtime: E2eRuntime, audit_logger: Any
) -> tuple[Any, str]:
    """DRY-RUN → InMemory（零真实发送路径）；--execute → 与 bot 共享的 SQLite 队列。"""
    config = runtime.config
    if not runtime.execute:
        return InMemorySendQueue(audit_logger=audit_logger), "dry-run:in-memory"
    enabled = bool(getattr(config, "bot_send_queue_enabled", False))
    db_path = str(getattr(config, "bot_send_queue_db_path", "") or "").strip()
    if not enabled or not db_path:
        raise E2eSafetyError(
            "--execute 需要持久化发送队列（BOT_SEND_QUEUE_ENABLED + "
            "BOT_SEND_QUEUE_DB_PATH），否则入队请求没有任何进程会投递。"
            "请先在 .env 启用发送队列并重启 bot。"
        )
    from plugins.bot_unified_runtime.sender.queue import build_send_queue

    queue = build_send_queue(config, audit_logger=audit_logger)
    if not isinstance(queue, SQLiteSendRequestQueue):
        raise E2eSafetyError(
            "--execute 期望 SQLite 发送队列，实际构建出 "
            f"{type(queue).__name__}；拒绝执行以防假真发。"
        )
    return queue, f"execute:sqlite:{db_path}"


# --------------------------------------------------------------------------
# 白名单安全阀（与 pipeline group_lists_provider 同源：运行时 store 优先）
# --------------------------------------------------------------------------


def load_group_lists(config: Any) -> dict[str, frozenset[str]]:
    settings = build_instance_settings_manager(config).get(effective_instance(config))
    lists: dict[str, frozenset[str]] = {}
    for slot in ("black1", "black2", "white1", "white2"):
        key = f"BOT_GROUP_{slot.upper()}"
        raw = settings.get(key, config) or []
        lists[slot] = frozenset(
            str(item).strip() for item in raw if str(item).strip()
        )
    return lists


def check_group_allowed(runtime: E2eRuntime, group_id: str) -> tuple[bool, str]:
    """群验收目标必须在 white1/white2（运行时 store 覆盖优先），black1/black2 直接拒绝。"""
    lists = load_group_lists(runtime.config)
    gid = str(group_id).strip()
    if gid in lists["black1"]:
        return False, f"群 {gid} 在 BOT_GROUP_BLACK1（完全静默名单），拒绝执行"
    if gid in lists["black2"]:
        return False, f"群 {gid} 在 BOT_GROUP_BLACK2，拒绝执行"
    if gid in lists["white1"]:
        return True, f"群 {gid} 在 BOT_GROUP_WHITE1"
    if gid in lists["white2"]:
        return True, f"群 {gid} 在 BOT_GROUP_WHITE2"
    reason = (
        f"群 {gid} 不在 BOT_GROUP_WHITE1/WHITE2（运行时 store 白名单），拒绝执行；"
        "先把群加入白名单（/bot runtime set BOT_GROUP_WHITE1 ...）再跑 --execute"
    )
    return False, reason


# --------------------------------------------------------------------------
# 合成 IncomingMessage（等价 @bot + 文本 的群/私聊消息）
# --------------------------------------------------------------------------


def synthesize_message(
    *,
    text: str,
    session_type: SessionType,
    target_id: str,
    sender_id: str,
    bot_id: str,
    seq: int,
) -> IncomingMessage:
    is_group = session_type is SessionType.GROUP
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id=bot_id or "unknown",
        session_id=(f"group_{target_id}_{sender_id}" if is_group else target_id),
        session_type=session_type,
        sender_id=sender_id,
        group_id=(target_id if is_group else None),
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        # 群里等价「@bot + 指令」，white1/white2 门均放行；私聊天然 mentions。
        mentions_bot=True,
        message_id=f"e2e-{seq}-{int(time.time())}",
    )


# --------------------------------------------------------------------------
# 验收矩阵
# --------------------------------------------------------------------------


@dataclass
class MatrixItem:
    key: str
    label: str
    capability_id: str
    build: Callable[[E2eRuntime], Callable[[IncomingMessage, BotDecision], CapabilityResult]]
    text: Callable[[E2eRuntime], str] | str
    note: str = ""

    def trigger_text(self, runtime: E2eRuntime) -> str:
        return self.text(runtime) if callable(self.text) else self.text


def _text_capability(
    runtime: E2eRuntime, *, body: str = "", text_parts: list[str] | None = None
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """文本直发能力：镜像 __init__._send_text_through_unified_pipeline 的内联能力。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.text",
            kind="text",
            body=body,
            text_parts=text_parts,
            audit_tags=["e2e_acceptance", "unified_text_reply"],
        )

    return capability


def _long_text_body() -> str:
    lines = [
        f"E2E 长文本样例 第 {index:02d} 行：守岸人在此待命，行号与内容均为确定性生成，"
        "用于观察发送链路对多行长文本的切分/合并转发行为。"
        for index in range(1, 41)
    ]
    return "\n".join(lines)


def _help_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    config = runtime.config
    render_backend = runtime.render_backend

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return build_help_result(
            request_id=message.request_id,
            query="",
            is_admin=False,
            render_backend=render_backend,
            card_dir=str(
                getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"
            ),
            bot_name=str(
                getattr(config, "bot_persona_display_name", "守岸人") or "守岸人"
            ),
            bot_avatar_url="",
            accent_color=str(getattr(config, "bot_help_card_color", "") or ""),
        )

    return capability


def _music_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    config = runtime.config
    mode = (
        runtime.runtime_settings.get("BOT_MUSIC_MODE", config)
        or getattr(config, "bot_music_default_mode", "card+voice+link")
    )
    candidates_enabled = bool(getattr(config, "bot_music_candidates_enabled", False))
    capability = build_music_capability(
        config,
        default_mode=mode,
        request_store=None,  # 点歌分析埋点（可选旁路存储），验收脚本不写。
        candidate_providers=(
            music_candidate_providers(build_cookie_provider(config))
            if candidates_enabled
            else None
        ),
        render_backend=runtime.render_backend,
    )
    return capability


def _affinity_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    # 与 bot 同一好感度库（build_character_affinity_store 内部含
    # bot_affinity_enabled 开关，关闭时返回 None → 能力层给降级文案）。
    # store 构造只做幂等 DDL（CREATE TABLE IF NOT EXISTS），快照为只读。
    from plugins.bot_unified_runtime import build_character_affinity_store

    return build_affinity_capability(
        runtime.config,
        affinity_store=build_character_affinity_store(runtime.config),
        render_backend=runtime.render_backend,
    )


def _content_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    config = runtime.config
    parse_history_store = None
    if runtime.execute:
        from plugins.bot_unified_runtime.sources.parse_history import (
            build_parse_history_store,
        )

        parse_history_store = build_parse_history_store(config)
    return build_content_capability(
        config,
        parse_history_store=parse_history_store,
        # 下载/媒体分析为可选旁路：验收关注解析卡主链路，不拖入视频下载。
        downloader=None,
        render_backend=runtime.render_backend,
        card_dir=str(
            getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"
        ),
        bot_avatar_url="",
    )


def build_matrix(runtime: E2eRuntime) -> list[MatrixItem]:
    """验收矩阵（①文本/长文本/多段 ②解析卡 ③点歌候选 ④全球股指 ⑤财经/科技快报
    ⑥天气+预警 ⑦随机图 ⑧占卜 ⑨help ⑩好感度 ⑪提醒查询）。"""
    return [
        MatrixItem(
            key="text-short",
            label="①文本直发（短）",
            capability_id="bot.text",
            build=lambda rt: _text_capability(
                rt, body="E2E 验收 · 短文本直发：守岸人链路自检，收到请忽略。"
            ),
            text="E2E 验收 · 短文本直发",
            note="镜像 _send_text_through_unified_pipeline 的内联文本能力",
        ),
        MatrixItem(
            key="text-long",
            label="①长文本（≥合并转发阈值观察）",
            capability_id="bot.text",
            build=lambda rt: _text_capability(rt, body=_long_text_body()),
            text="E2E 验收 · 长文本直发",
            note="超过 bot_render_forward_min_chars 时由管道转合并转发",
        ),
        MatrixItem(
            key="text-parts",
            label="①多段（text_parts → chunks）",
            capability_id="bot.text",
            build=lambda rt: _text_capability(
                rt,
                text_parts=[
                    "E2E 多段验证 1/3：本条由能力层 text_parts 声明，渲染为 chunks 分片逐条发送。",
                    "E2E 多段验证 2/3：观察 QQ 侧是否按顺序收到三条独立消息。",
                    "E2E 多段验证 3/3：分片完毕。",
                ],
            ),
            text="E2E 验收 · 多段直发",
            note="content_type=chunks，sender 按 parts 逐条发",
        ),
        MatrixItem(
            key="content-bili",
            label="②解析卡（B 站视频）",
            capability_id="bot.content",
            build=_content_capability,
            text=BILI_SAMPLE_URL,
            note="真实解析 + Mica 信息卡（需外网；失败时能力层自带文本降级）",
        ),
        MatrixItem(
            key="music-candidates",
            label="③点歌候选卡",
            capability_id="bot.music",
            build=_music_capability,
            text="点歌 告白气球",
            note="BOT_MUSIC_CANDIDATES_ENABLED 开启时同名歧义返回候选卡；否则直接出歌曲卡",
        ),
        MatrixItem(
            key="market-global",
            label="④全球股指（18 指数全量）",
            capability_id="bot.market",
            build=lambda rt: build_market_capability(rt.config),
            text="全球股市",
            note="不带市场词（美股/港股/A股…）= 不过滤 → 指数全量",
        ),
        MatrixItem(
            key="news-finance",
            label="⑤财经快报（全量）",
            capability_id="bot.news",
            build=lambda rt: build_news_capability(rt.config),
            text="财经快报",
            note="条数上限 bot_news_max_items（默认 8）",
        ),
        MatrixItem(
            key="news-tech",
            label="⑤科技快报（全量）",
            capability_id="bot.news",
            build=lambda rt: build_news_capability(rt.config),
            text="科技快报",
            note="类目 tech",
        ),
        MatrixItem(
            key="weather-alert",
            label="⑥天气+预警",
            capability_id="bot.weather",
            build=lambda rt: build_weather_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text=lambda rt: f"天气 {rt.city or '北京'}",
            note="NMC 在报预警自动附在天气报告后（无预警时只出天气）",
        ),
        MatrixItem(
            key="randpic",
            label="⑦随机图",
            capability_id="bot.randpic",
            build=lambda rt: build_randpic_capability(rt.config),
            text="随机图",
            note="BOT_RANDPIC_DIRS 未配置/为空时给降级文案（真实行为）",
        ),
        MatrixItem(
            key="divination",
            label="⑧占卜（塔罗单张）",
            capability_id="bot.divination",
            build=lambda rt: build_divination_capability(rt.config),
            text="塔罗",
        ),
        MatrixItem(
            key="help",
            label="⑨help 卡",
            capability_id="bot.help",
            build=_help_capability,
            text="help",
            note="Mica 帮助页，主色 bot_help_card_color 派生",
        ),
        MatrixItem(
            key="affinity",
            label="⑩好感度卡",
            capability_id="bot.affinity",
            build=_affinity_capability,
            text="好感度",
            note="群=本群好感榜；私聊=双向分值卡（bot_affinity_enabled 关闭时给降级文案）",
        ),
        MatrixItem(
            key="reminder-list",
            label="⑪提醒查询（按设计静默）",
            capability_id="bot.reminder",
            build=lambda rt: build_reminder_capability(rt.config),
            text="提醒列表",
            note=(
                "提醒能力回执恒为 SILENT_AUDIT（只登记/查询，不当场发言）——"
                "预期收到 skipped 回执而非消息"
            ),
        ),
    ]


# --------------------------------------------------------------------------
# 执行与回执呈现
# --------------------------------------------------------------------------


@dataclass
class ItemOutcome:
    item: MatrixItem
    request_id: str
    receipt: DeliveryReceipt | None = None
    send_request: SendRequest | None = None
    error: str = ""
    trigger_text: str = ""


def _flatten(text: str) -> str:
    return str(text or "").replace("\r", "").replace("\n", " ⏎ ")


def format_preview(send_request: SendRequest | None) -> str:
    """把将要/已经入队的 SendRequest 渲染成一行预览（DRY-RUN 展示用）。"""
    if send_request is None:
        return "（无入队请求）"
    content = send_request.content
    parts = content.content_ref or {}
    media = 0
    if isinstance(parts, dict):
        media += sum(
            1
            for part in parts.get("parts", [])
            if isinstance(part, dict) and str(part.get("type", "")) != "text"
        )
    preview = _flatten(content.text_fallback)[:PREVIEW_MAX_CHARS]
    return (
        f"content_type={content.content_type} target={send_request.target_scope.value}:"
        f"{send_request.target_id} media={media} text[{len(content.text_fallback)}字]={preview!r}"
    )


def execute_item(
    *,
    pipeline: RuntimePipeline,
    send_queue: Any,
    item: MatrixItem,
    runtime: E2eRuntime,
    session_type: SessionType,
    target_id: str,
    seq: int,
) -> ItemOutcome:
    trigger = item.trigger_text(runtime)
    message = synthesize_message(
        text=trigger,
        session_type=session_type,
        target_id=target_id,
        sender_id=runtime.sender_id,
        bot_id=runtime.bot_id,
        seq=seq,
    )
    outcome = ItemOutcome(
        item=item, request_id=message.request_id, trigger_text=trigger
    )
    try:
        capability = item.build(runtime)
    except Exception as exc:  # noqa: BLE001 - 单项构造失败不拖垮整个矩阵。
        outcome.error = f"capability build failed: {type(exc).__name__}: {exc}"
        return outcome
    try:
        receipt = pipeline.handle(message, capability, capability_id=item.capability_id)
        outcome.receipt = receipt
    except Exception as exc:  # noqa: BLE001 - 管道异常按单项失败记录。
        outcome.error = f"pipeline raised: {type(exc).__name__}: {exc}"
        traceback.print_exc()
        return outcome
    try:
        outcome.send_request = send_queue.find_request(message.request_id)
    except Exception:  # noqa: BLE001 - 队列回查失败不影响主流程。
        outcome.send_request = None
    return outcome


def print_outcome(index: int, total: int, outcome: ItemOutcome, execute: bool) -> None:
    item = outcome.item
    if outcome.error:
        print(f"[{index}/{total}] {item.label} ({item.key}) → ERROR: {outcome.error}")
        return
    receipt = outcome.receipt
    assert receipt is not None
    state = receipt.state.value
    mode = "已入队" if execute else "DRY-RUN"
    extra = f" public={receipt.public_message!r}" if receipt.public_message else ""
    print(
        f"[{index}/{total}] {item.label} ({item.key}) → {mode} state={state} "
        f"transport={receipt.transport}{extra}"
    )
    if outcome.send_request is not None:
        print(f"          ↳ {format_preview(outcome.send_request)}")
    if item.note:
        print(f"          ↳ note: {item.note}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined, union-attr]
        except (AttributeError, OSError):
            pass


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="重启后真机验收：合成消息走真实管线逐项发送（默认 DRY-RUN）"
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--target-group", metavar="GROUP_ID", help="验收目标群号")
    target.add_argument("--target-user", metavar="USER_ID", help="验收目标私聊 QQ 号")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="真发：入队 SQLite 发送队列，由在线 bot worker 投递（默认 DRY-RUN）",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"逐项间隔秒数（默认 {DEFAULT_INTERVAL_SECONDS:g}s）",
    )
    parser.add_argument("--env", default=None, help=".env 路径（默认自动发现）")
    parser.add_argument(
        "--bot-id", default="", help="bot 自身 QQ 号（默认取 BOT_GSCORE_BOT_SELF_ID；"
        "留空时 worker 按适配器回退选择在线 OneBot bot）"
    )
    parser.add_argument(
        "--sender-id",
        default="",
        help="合成消息的发送者 QQ 号（留空=私聊时跟随 --target-user，群聊用占位 10000）",
    )
    parser.add_argument(
        "--city", default="北京", help="天气+预警项的查询城市（默认 北京）"
    )
    parser.add_argument(
        "--only", default="", help="只跑指定项（逗号分隔 key，如 help,affinity）"
    )
    parser.add_argument(
        "--list", action="store_true", help="只打印验收矩阵后退出"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdio()
    args = build_arg_parser().parse_args(argv)

    runtime = build_runtime(
        env_file=args.env,
        execute=bool(args.execute),
        city=str(args.city or "").strip(),
        bot_id=str(args.bot_id or "").strip(),
        # 私聊回执 target=sender：默认值必须跟随目标用户，否则私聊件投递到占位号。
        sender_id=str(
            args.sender_id
            or str(args.target_user or "").strip()
            or "10000"
        ).strip(),
    )
    matrix = build_matrix(runtime)
    if args.list:
        for index, item in enumerate(matrix, 1):
            print(f"[{index}] {item.label} key={item.key} text={item.trigger_text(runtime)!r}")
        return 0

    only = {part.strip() for part in str(args.only or "").split(",") if part.strip()}
    if only:
        matrix = [item for item in matrix if item.key in only]
        if not matrix:
            print(f"--only 无匹配项：{sorted(only)}", file=sys.stderr)
            return 2

    if args.target_group:
        session_type = SessionType.GROUP
        target_id = str(args.target_group).strip()
        allowed, reason = check_group_allowed(runtime, target_id)
        print(f"[安全阀] {reason}")
        if not allowed:
            return 2
    else:
        session_type = SessionType.PRIVATE
        target_id = str(args.target_user or "").strip()
        # 私聊场景收件人=发信人：sender_id 未显式给定时跟随目标用户，
        # 否则 pipeline 生成的 SendRequest.target_id 会指向占位 id 导致投递失败。
        if target_id and not str(args.sender_id or "").strip():
            args.sender_id = target_id
        print(f"[安全阀] 私聊目标 {target_id}（私聊策略默认放行，角色/风控拦截除外）")

    mode_line = (
        "execute（真发：入队 SQLite 队列，由在线 bot worker 投递）"
        if args.execute
        else "DRY-RUN（默认；InMemory 队列，无任何真实发送路径）"
    )
    print(
        f"[配置] env={args.env or 'auto'} 目标={session_type.value}:{target_id} "
        f"sender={runtime.sender_id} bot_id={runtime.bot_id or '(回退适配器选择)'} "
        f"间隔={args.interval:g}s 模式={mode_line}"
    )

    audit_logger = InMemoryAuditLogger()
    try:
        send_queue, queue_desc = choose_send_queue(runtime, audit_logger)
    except E2eSafetyError as exc:
        print(f"[安全阀] {exc}", file=sys.stderr)
        return 2
    print(f"[队列] {queue_desc}")

    pipeline = build_pipeline(runtime, send_queue)

    # 安静时间提示：真跑会话若落在安静窗口，命令也会被 pipeline 拦（回执可见）。
    quiet = build_quiet_hours_checker(runtime.config)
    probe = synthesize_message(
        text="e2e-probe",
        session_type=session_type,
        target_id=target_id,
        sender_id=runtime.sender_id,
        bot_id=runtime.bot_id,
        seq=0,
    )
    try:
        quiet_decision = quiet.check(probe, "bot.market")
        if not quiet_decision.allowed:
            print(f"[提示] {quiet_decision.reason}（安静时间窗口内发送会被 pipeline 拦截）")
    except Exception:  # noqa: S110, BLE001 - 提示失败不阻断，静默跳过。
        pass

    outcomes: list[ItemOutcome] = []
    total = len(matrix)
    for index, item in enumerate(matrix, 1):
        outcome = execute_item(
            pipeline=pipeline,
            send_queue=send_queue,
            item=item,
            runtime=runtime,
            session_type=session_type,
            target_id=target_id,
            seq=index,
        )
        outcomes.append(outcome)
        print_outcome(index, total, outcome, execute=bool(args.execute))
        if args.execute and outcome.receipt is not None:
            try:
                print(f"          ↳ queue summary: {send_queue.safe_summary()}")
            except Exception:  # noqa: S110, BLE001 - 队列摘要失败不阻断。
                pass
        if index < total and args.interval > 0:
            time.sleep(args.interval)

    errors = [outcome for outcome in outcomes if outcome.error]
    print("\n===== 验收汇总 =====")
    for outcome in outcomes:
        state = outcome.receipt.state.value if outcome.receipt else "error"
        mark = "✗" if outcome.error else "·"
        print(f"{mark} {outcome.item.key:18s} {state}")
    print(
        f"共 {len(outcomes)} 项，错误 {len(errors)} 项。"
        + (
            "\n真发提示：--execute 项已入队，bot 的 send-queue worker 会按 "
            "BOT_SEND_QUEUE_WORKER_INTERVAL_SECONDS 逐条投递；请在目标群/私聊回 test 验收。"
            if args.execute
            else "\nDRY-RUN：以上为「将发内容」，未入真实队列。确认无误后加 --execute 重跑。"
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

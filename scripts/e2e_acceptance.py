"""重启后真机验收脚本（E2E acceptance）。

目的：bot 重启后，向真实群/私聊逐条发送「所有可能的消息种类」（文本/长文本/
多段、解析卡、点歌候选卡、全球股指 18 指数全量、财经/科技快报全量、天气+预警、
随机图、占卜、help 卡、好感度卡、提醒查询、个股行情+非上市守卫、汇率面板/
定向换算、称谓自助），供用户回 ``test`` 人工验收。2026-09-13 批次起部分检查项
带 ``expect`` 回执断言（作用于入队 SendRequest 层，DRY-RUN/--execute 同语义）。

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

实战自测模式（2026-09-13 批次新增，只往后加参数，存量参数语义不变）::

    python scripts/e2e_acceptance.py --selftest
        # 全离线自检：矩阵生成/触发提取/payload 构造/报告渲染/探针/轮询，不依赖 bot 在线
    python scripts/e2e_acceptance.py --target-group 123456 --help-matrix
        # 从 echo._HELP_ENTRIES 全 topics 生成命令矩阵（DRY-RUN：只构造 payload + 路由体检）
    python scripts/e2e_acceptance.py --target-group 123456 --help-matrix --execute --report
        # 逐条发送 + 等待投递回执（响应/超时/异常三态与耗时），报告私聊超管（离线则写文件）
        # 注意：本模式验证的是「命令 payload 经发送链路的投递」，命令语义处理验收用存量矩阵
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import tempfile
import time
import traceback
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

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
    is_divination_command,
)
from plugins.bot_unified_runtime.capabilities.echo import (
    _HELP_ENTRIES as _HELP_REGISTRY,
)
from plugins.bot_unified_runtime.capabilities.echo import (
    build_decision_query_result,
    build_help_result,
)
from plugins.bot_unified_runtime.capabilities.fx import build_fx_capability
from plugins.bot_unified_runtime.capabilities.market import (
    build_market_capability,
    is_market_command,
)
from plugins.bot_unified_runtime.capabilities.meme_library import (
    build_meme_library_capability,
)
from plugins.bot_unified_runtime.capabilities.music import build_music_capability
from plugins.bot_unified_runtime.capabilities.news import build_news_capability
from plugins.bot_unified_runtime.capabilities.randpic import build_randpic_capability
from plugins.bot_unified_runtime.capabilities.reminder import (
    build_reminder_capability,
)
from plugins.bot_unified_runtime.capabilities.stocks import (
    build_stocks_capability,
    is_stocks_command,
)
from plugins.bot_unified_runtime.capabilities.user_copy import (
    GROUP_FAILURE_ACK_TEMPLATES,
)
from plugins.bot_unified_runtime.capabilities.weather import build_weather_capability
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    OperationalIssue,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.decision.trace import (
    InMemoryDecisionTraceSink,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy import (
    build_quiet_hours_checker,
    build_rate_limiter,
    build_reply_budget_settings,
    build_role_settings,
)
from plugins.bot_unified_runtime.domains.ops.smoke.smoke import load_smoke_config
from plugins.bot_unified_runtime.output.render_backends import build_render_backend
from plugins.bot_unified_runtime.runtime.base_router import (
    classify_message_route,
)
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.runtime.settings import (
    build_instance_settings_manager,
    effective_instance,
)
from plugins.bot_unified_runtime.sender import InMemorySendQueue
from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue
from plugins.bot_unified_runtime.sources.meme_library import MemeLibraryStore
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
    # 回执断言（可省）：入参 ItemOutcome，返回空串=PASS、非空=失败原因。
    # None=该检查项不做断言（2026-09-13 之前的存量项全部保持 None）。
    expect: Callable[[ItemOutcome], str] | None = None

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


def _identity_preference_capability(
    runtime: E2eRuntime, *, command_text: str
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """镜像 __init__ `/bot identity` 分支 + runtime_admin 对四个自助子命令
    （set-name/set-gender/unset-name/unset-gender）管理员门前的拦截转发
    （echo.build_identity_preference_result）。写真实 AddressingPreferenceStore
    （与 bot 同库，data/ 相对路径经 runtime_paths 落运行区）；验收矩阵里
    set-name 与 unset-name 成对出现，净效果为零。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        from plugins.bot_unified_runtime.capabilities.echo import (
            build_identity_preference_result,
        )

        return build_identity_preference_result(
            runtime.config,
            request_id=message.request_id,
            sender_id=str(message.sender_id or ""),
            group_id=str(message.group_id or ""),
            command_text=command_text,
        )

    return capability


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


def _meme_library_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """镜像 __init__ 表情收库装配：MemeLibraryStore（运行区库；pick/stats 只读）
    + build_meme_library_capability（mood_valence_fn 不接=中性档）。
    BOT_MEME_LIBRARY_ENABLED 未启用时给降级文案（与生产不注册 handler 同语义）。"""
    config = runtime.config
    if not bool(getattr(config, "bot_meme_library_enabled", False)):
        return _text_capability(
            runtime,
            body="E2E：BOT_MEME_LIBRARY_ENABLED 未启用，表情收库链路按生产语义跳过。",
        )
    store = MemeLibraryStore(
        str(
            getattr(config, "bot_meme_library_db_path", "data/meme_library.sqlite3")
            or ""
        ),
        prefer=list(getattr(config, "bot_meme_library_prefer", []) or []),
    )
    return build_meme_library_capability(store, config)


def _router_gated_capability(
    runtime: E2eRuntime,
    *,
    detector: Callable[[str], bool],
    domain_builder: Callable[
        [E2eRuntime],
        Callable[[IncomingMessage, BotDecision], CapabilityResult],
    ],
    domain_label: str,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """劫持守卫负样本专用：镜像 base_router 分流语义。

    真机链路里劫持守卫生在路由层（base_router 用 is_* 检测器定 RouteKind），
    本脚本绕过路由直挂能力，故用与路由同源的 detector 复现分流：
    命中 → 原样委托真实领域能力（守卫被改坏时仍可观察真实形态）；
    不命中 → 让路（生产由 chat/其他域接管，验收用确定性占位文本）。
    注意：负样本不能直喂领域能力——stocks/divination 的能力体对未命中文本
    会走 NON_PUBLIC/兜底分支（如 resolve_company_query('openai是什么')=OPENAI、
    parse_divination_intent 对算命句返回 bazi 意图，均实跑核实），
    与生产「根本不进该能力」语义不符。"""
    domain_capability = domain_builder(runtime)

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        if detector(str(message.plain_text or "")):
            return domain_capability(message, decision)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.text",
            kind="text",
            body="E2E 守卫观察：该消息未命中本域触发词，生产语义=让路（chat/其他域接管）。",
            audit_tags=["e2e_acceptance", "hijack_guard_negative"],
        )

    return capability


def _decision_query_capability(
    runtime: E2eRuntime, *, actor_roles: list[str]
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """镜像 __init__ `/bot decision` 出口（生产 elif 接线待 §26.10 登记的
    campus 席释放后补贴）：显式注入 actor_roles——矩阵绕过路由层，拿不到
    从 sender_id 解析的角色，故管理员/普通成员两态各建一个闭包。sink 走
    缺省（decision/trace 默认 sink：recent() 只读 URI 查询，绝不创建库，
    缺库回落热缓冲 → 「暂无记录」同为合法回执）。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return build_decision_query_result(
            request_id=message.request_id,
            actor_roles=actor_roles,
        )

    return capability


def _group_failure_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """A-19 正向观察：合成「能力执行失败错误态」结果（与生产失败能力同形：
    operational_issue 非 pipeline_busy + SILENT_AUDIT 空正文），管线在群聊/
    频道补一句 GROUP_FAILURE_ACK_TEMPLATES 池内短句。零外呼、零落盘。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.selftest-fail",
            kind="error",
            body="",
            send_policy=SendPolicy.SILENT_AUDIT,
            operational_issue=OperationalIssue(
                stage="capability",
                kind="capability_failure",
                retryable=False,
                debug_id=message.debug_id,
                safe_summary="e2e A-19 capability failure",
            ),
            audit_tags=["e2e_acceptance", "a19_group_failure_ack"],
        )

    return capability


def _pipeline_busy_capability(
    runtime: E2eRuntime,
) -> Callable[[IncomingMessage, BotDecision], CapabilityResult]:
    """A-19 负样本：超载快败（pipeline_busy）按设计静默——镜像
    pipeline._pipeline_busy_result 的形态，验证「限流/安静/超载拦截族
    零反馈」的降频设计语义未被降级池破坏。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.selftest-busy",
            kind="error",
            body="",
            send_policy=SendPolicy.SILENT_AUDIT,
            operational_issue=OperationalIssue(
                stage="runtime",
                kind="pipeline_busy",
                retryable=True,
                debug_id=message.debug_id,
                safe_summary="pipeline_busy",
            ),
            audit_tags=["pipeline_busy:v1"],
        )

    return capability


# --------------------------------------------------------------------------
# 回执断言（2026-09-13 批次：作用于入队 SendRequest 层，DRY-RUN/--execute 同语义；
# 渲染形态对照 renderer：能力 images 非空 ⇔ content_type=mixed + 图片部件）
# --------------------------------------------------------------------------


def _expect_preamble(outcome: ItemOutcome) -> tuple[SendRequest | None, str]:
    if outcome.error:
        return None, outcome.error
    if outcome.send_request is None:
        return None, "无入队请求（能力可能被静默/拦截，回执状态见上）"
    return outcome.send_request, ""


def _media_part_count(send_request: SendRequest | None) -> int:
    parts = send_request.content.content_ref if send_request is not None else None
    if not isinstance(parts, dict) or not isinstance(parts.get("parts"), list):
        return 0
    return sum(
        1
        for part in parts["parts"]
        if isinstance(part, dict) and str(part.get("type", "")) != "text"
    )


def expect_stock_card(outcome: ItemOutcome) -> str:
    """⑫ 英伟达股价 → 期望个股卡（images 非空或 kind=mixed 的入队等价形态）。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    media = _media_part_count(request)
    if request.content.content_type == "mixed" or media >= 1:
        return ""
    return (
        f"期望个股卡（content_type=mixed 或含图片部件），实际 "
        f"content_type={request.content.content_type} media={media}"
        "（多为行情源失败或渲染后端不可用时的文本降级）"
    )


# 守卫禁词：出现即视为产生了股价/OHLC 内容（估值口径说明文本不含这些词，
# 含「OpenAI 目前未上市…／最近公开估值：约 … 亿美元／来源 …」）。
_STOCK_CONTENT_MARKERS = ("现价", "KDJ", "收盘序列", "涨跌幅", "开 ", "OHLC")


def expect_nonpublic_guard(outcome: ItemOutcome) -> str:
    """⑫ OpenAI 估值 → 非上市守卫：不得产生任何股价/OHLC 内容或卡图。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    media = _media_part_count(request)
    if media:
        return f"守卫失败：产生了 {media} 个媒体部件（非上市公司不得出任何行情卡图）"
    text = request.content.text_fallback
    hits = [marker for marker in _STOCK_CONTENT_MARKERS if marker in text]
    if hits:
        return f"守卫失败：文本命中股价/OHLC 形态 {hits}"
    if "openai" not in text.lower():
        return "守卫失败：回复未指向 OpenAI（疑似误路由）"
    return ""


def expect_fx_panel_card(outcome: ItemOutcome) -> str:
    """⑬ 汇率 → 期望面板卡（mixed + 图片部件）+ 主要货币面板文本。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    text = request.content.text_fallback
    if "拉不到" in text:
        return "汇率快照拉取失败（上游不可用），未产出面板"
    media = _media_part_count(request)
    if request.content.content_type == "mixed" and media >= 1:
        return ""
    return (
        f"期望汇率面板卡，实际 content_type={request.content.content_type} "
        f"media={media}（渲染后端不可用时会文本降级，真机应出卡）"
    )


def expect_fx_converted(outcome: ItemOutcome) -> str:
    """⑬ 100日元换多少人民币 → 期望定向换算结果（≈ 折算行，JPY→CNY）。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    text = request.content.text_fallback
    if "拉不到" in text:
        return "汇率快照拉取失败（上游不可用），未产出换算"
    if "≈" in text and ("人民币" in text or "CNY" in text):
        return ""
    return (
        "期望定向换算结果（形如 100日元 ≈ X 人民币），"
        f"实际预览：{_flatten(text)[:120]!r}"
    )


def expect_divination_two_state(outcome: ItemOutcome) -> str:
    """⑭ 占卜 → 出卡（mixed）或纯文本二态皆可；断言本身不抛异常。

    纯文本态在入队层可能是 text，也可能是 pipeline 对超阈值长文的
    合并转发形态（forward，text_fallback 保留全文）——实测 192 字卦文
    即转 forward，两者同为「无卡图纯文本」，均算通过。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    if request.content.content_type not in ("mixed", "text", "forward"):
        return (
            "期望 mixed/纯文本（含合并转发形态）二态之一，实际 "
            f"content_type={request.content.content_type}"
        )
    if not request.content.text_fallback.strip():
        return "正文为空"
    return ""


def expect_identity_set_confirmed(outcome: ItemOutcome) -> str:
    """⑮ /bot identity set-name → 期望「已记下」确认回复。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    text = request.content.text_fallback
    if "已记下" in text:
        return ""
    return f"期望「已记下」确认回复，实际：{_flatten(text)[:120]!r}"


def expect_identity_unset_confirmed(outcome: ItemOutcome) -> str:
    """⑮ /bot identity unset-name → 清理确认（已清除/本就没有均算达成）。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    text = request.content.text_fallback
    if "已清除" in text or "还没有设置过" in text:
        return ""
    return f"期望清理确认（已清除/本就没有），实际：{_flatten(text)[:120]!r}"


def expect_chat_fallthrough(
    *, markers: tuple[str, ...], domain_label: str
) -> Callable[[ItemOutcome], str]:
    """劫持/排除守卫负样本通用断言：必须落纯文本（零卡图），
    且正文不含任何领域能力内容形态（markers 取自领域能力产出文案特征词，
    已逐一对照让路占位文本排除误伤）。"""
    def expect(outcome: ItemOutcome) -> str:
        request, reason = _expect_preamble(outcome)
        if reason:
            return reason
        media = _media_part_count(request)
        if media:
            return f"守卫失败：产生了 {media} 个媒体部件（{domain_label}不应被触发）"
        if request.content.content_type not in ("text", "forward"):
            return (
                "守卫失败：期望纯文本让路落点，实际 content_type="
                f"{request.content.content_type}"
            )
        text = request.content.text_fallback
        hits = [marker for marker in markers if marker in text]
        if hits:
            return f"守卫失败：文本命中{domain_label}内容形态 {hits}"
        return ""

    return expect


# 表情收库 pick 的三态确定性文案（出图 mixed 的 text_fallback 也含首句）。
_MEME_PICK_TEXTS = ("给你偷来一张表情", "表情库还是空的", "冷却中")


def expect_meme_library_pick(outcome: ItemOutcome) -> str:
    """表情收库（steal meme / meme random）→ 三态皆算真实行为：
    出图（mixed）/空库文案/会话冷却文案；落到其他文案才算异常。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    text = request.content.text_fallback
    if any(token in text for token in _MEME_PICK_TEXTS):
        return ""
    if request.content.content_type == "mixed":
        return ""
    return (
        "期望表情收库 pick 三态之一（出图/空库/冷却），"
        f"实际：{_flatten(text)[:120]!r}"
    )


def expect_decision_query_admin(outcome: ItemOutcome) -> str:
    """⑥§26.2 /bot decision（管理员）→ 期望「决策影子痕迹」文本回执
    （「暂无记录」与逐条列表二态皆算达成：影子模式 legacy_only 下无痕迹属预期）。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    if request is None:
        return "无入队请求（能力可能被静默/拦截，回执状态见上）"
    text = request.content.text_fallback
    if "决策影子痕迹" in text:
        return ""
    return f"期望决策影子痕迹摘要（暂无记录/逐条列表），实际：{_flatten(text)[:120]!r}"


def expect_admin_gate_refusal(outcome: ItemOutcome) -> str:
    """⑥§26.2 同命令普通成员 → 期望 ADMIN_GATE_TEMPLATES 池温和拒绝，
    且不得泄漏任何查询结果形态（拒绝与查询是两条互斥路径）。"""
    request, reason = _expect_preamble(outcome)
    if reason:
        return reason
    if request is None:
        return "无入队请求（能力可能被静默/拦截，回执状态见上）"
    text = request.content.text_fallback
    if "管理员" not in text:
        return f"期望管理员门温和拒绝话术（ADMIN_GATE_TEMPLATES 池），实际：{_flatten(text)[:120]!r}"
    leaks = [
        token
        for token in ("决策影子痕迹：", "暂无记录", "（新→旧）")
        if token in text
    ]
    if leaks:
        return f"拒绝话术泄漏了查询结果形态 {leaks}"
    return ""


def expect_group_failure_ack(outcome: ItemOutcome) -> str:
    """⑰A-19 正向：群聊会话能力失败应补一句池内降级短句（入队能力
    bot.group_failure_notice）。私聊按设计不覆盖（chat 私聊失败另有守岸人
    话术池）→ 私聊会话无断言语义直接 PASS。"""
    if outcome.session_type == SessionType.PRIVATE.value:
        return ""
    request, reason = _expect_preamble(outcome)
    if reason:
        return (
            reason
            + "（群聊应补一句池内降级短句；300s 会话节流窗内重跑会静默——"
            "等窗口过期或换 white1 群冷启动重跑观察）"
        )
    if request is None:
        return "无入队请求（能力可能被静默/拦截，回执状态见上）"
    if request.capability_id != "bot.group_failure_notice":
        return (
            "期望 bot.group_failure_notice 降级件，实际 capability_id="
            f"{request.capability_id}"
        )
    if request.content.text_fallback in GROUP_FAILURE_ACK_TEMPLATES:
        return ""
    return (
        "降级短句不在 GROUP_FAILURE_ACK_TEMPLATES 池内："
        f"{_flatten(request.content.text_fallback)[:120]!r}"
    )


def expect_pipeline_busy_silent(outcome: ItemOutcome) -> str:
    """⑰A-19 负样本：超载快败必须零反馈——无任何入队请求（拦截族静默
    语义不变）；回执应为 skipped/blocked 静默态。群/私聊两会话同语义。"""
    if outcome.error:
        return outcome.error
    if outcome.send_request is not None:
        return (
            "超载快败应保持静默（零入队请求），实际入队："
            f"{_flatten(outcome.send_request.content.text_fallback)[:120]!r}"
        )
    if outcome.receipt is not None and outcome.receipt.state.value not in (
        "skipped",
        "blocked",
    ):
        return f"期望 skipped/blocked 静默回执，实际 state={outcome.receipt.state.value}"
    return ""


def build_matrix(runtime: E2eRuntime) -> list[MatrixItem]:
    """验收矩阵（①文本/长文本/多段 ②解析卡 ③点歌候选 ④全球股指 ⑤财经/科技快报
    ⑥天气+预警 ⑦随机图 ⑧占卜 ⑨help ⑩好感度 ⑪提醒查询
    ⑫个股行情+非上市守卫 ⑬汇率面板/定向换算 ⑭占卜金钱卦 ⑮称谓自助
    ⑯决策影子查询双态 ⑰A-19 群失败降级正/负样本）。"""
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
        MatrixItem(
            key="stocks-nvda",
            label="⑫个股卡（英伟达）",
            capability_id="bot.stocks",
            build=lambda rt: build_stocks_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="英伟达股价",
            note="2026-09-13 批次：期望釉瑚金融卡（行情源/渲染失败降级文本会判 expect-FAIL）",
            expect=expect_stock_card,
        ),
        MatrixItem(
            key="stocks-nonpublic",
            label="⑫非上市守卫（OpenAI 估值）",
            capability_id="bot.stocks",
            build=lambda rt: build_stocks_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="OpenAI 估值",
            note="NON_PUBLIC 分支不触行情外呼：只给有来源的估值口径，零股价/OHLC/卡图",
            expect=expect_nonpublic_guard,
        ),
        MatrixItem(
            key="fx-panel",
            label="⑬汇率面板卡",
            capability_id="bot.fx",
            build=lambda rt: build_fx_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="汇率",
            note="主要货币（USD 基准）面板卡",
            expect=expect_fx_panel_card,
        ),
        MatrixItem(
            key="fx-convert",
            label="⑬汇率定向换算",
            capability_id="bot.fx",
            build=lambda rt: build_fx_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="100日元换多少人民币",
            note="JPY→CNY 定向换算（含 unit_base 折算，评审 P0-1 口径）",
            expect=expect_fx_converted,
        ),
        MatrixItem(
            key="divination-iching",
            label="⑭占卜（金钱卦，出卡二态）",
            capability_id="bot.divination",
            build=lambda rt: build_divination_capability(rt.config),
            text="占卜",
            note="渲染后端可用出 mixed 卡，不可用回纯文本——二态均算通过，断言不抛异常",
            expect=expect_divination_two_state,
        ),
        MatrixItem(
            key="identity-set-name",
            label="⑮称谓自助 set-name",
            capability_id="bot.identity",
            build=lambda rt: _identity_preference_capability(
                rt, command_text="set-name 岸友"
            ),
            text="/bot identity set-name 岸友",
            note=(
                "镜像 runtime_admin 管理员门前拦截转发；写真实 AddressingPreferenceStore"
                "（运行区库），随后由 identity-unset-name 项成对清理"
            ),
            expect=expect_identity_set_confirmed,
        ),
        MatrixItem(
            key="identity-unset-name",
            label="⑮称谓自助 unset-name（清理）",
            capability_id="bot.identity",
            build=lambda rt: _identity_preference_capability(
                rt, command_text="unset-name"
            ),
            text="/bot identity unset-name",
            note="整行移除称谓偏好（含性别自述），与 set-name 成对执行、净效果为零",
            expect=expect_identity_unset_confirmed,
        ),
        # ---- 二期扩展（2026-09-13）：多语言触发形态抽样 + 劫持守卫负样本 ----
        # 词表取证：.superpowers/sdd/2026-09-12-shorekeeper-global-audit/ 下
        # fix-py1/py2（拼音全拼/缩写）、fix-eng-verify（英文）、fix-tra2/tra3
        # （繁體）报告 + is_* 检测器实跑核验；fix-py1 市场词表无 meiguhang，
        # 按其实际入表词取 hangqing/hq。存量 21 项零改动。
        MatrixItem(
            key="music-pinyin",
            label="③点歌（拼音全拼 diange）",
            capability_id="bot.music",
            build=_music_capability,
            text="diange 晴天",
            note="fix-py1：_COMMAND_RE 全拼 diange（同音覆盖 點歌）；候选/歌曲卡同点歌主链路",
        ),
        MatrixItem(
            key="music-abbr",
            label="③点歌（缩写 dg）",
            capability_id="bot.music",
            build=_music_capability,
            text="dg 晴天",
            note="fix-py1：dg 入表缩写（(?![a-z0-9]) 右界；dgms/diangemoshi 归 mode 族不抢主命令）",
        ),
        MatrixItem(
            key="weather-pinyin",
            label="⑥天气（拼音全拼 tianqi）",
            capability_id="bot.weather",
            build=lambda rt: build_weather_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="tianqi 台北",
            note="fix-py2：tianqi/tq 入表（正则无 IGNORECASE，小写生效）；台北走 F18 城市别名",
        ),
        MatrixItem(
            key="weather-english",
            label="⑥天气（英文 weather）",
            capability_id="bot.weather",
            build=lambda rt: build_weather_capability(
                rt.config, render_backend=rt.render_backend
            ),
            text="weather 台北",
            note="T1.2 英文别名（weather(?![A-Za-z0-9]) 词界，weatherqq 胶合不触发）；"
            "query 必填故裸 weather 不匹配（实跑核实）",
        ),
        MatrixItem(
            key="market-pinyin",
            label="④股指（拼音全拼 hangqing）",
            capability_id="bot.market",
            build=lambda rt: build_market_capability(rt.config),
            text="hangqing",
            note="fix-py1：非锚定 search 双侧词界；无市场过滤词 → 18 指数全量（同 全球股市）",
        ),
        MatrixItem(
            key="market-abbr",
            label="④股指（缩写 hq）",
            capability_id="bot.market",
            build=lambda rt: build_market_capability(rt.config),
            text="hq",
            note="fix-py1：hq 入表缩写；两字母缩写群聊误伤面（hq≈总部等）即在本项真机观察",
        ),
        MatrixItem(
            key="meme-lib-steal-eng",
            label="表情收库（英文 steal meme）",
            capability_id="bot.meme_library",
            build=_meme_library_capability,
            text="steal meme",
            note="T1.2：按权重偷一张（mixed 出图）或空库/冷却文案；"
            "读真实运行区表情库（只读 pick，与好感度项同口径）",
            expect=expect_meme_library_pick,
        ),
        MatrixItem(
            key="meme-lib-random-eng",
            label="表情收库（英文 meme random）",
            capability_id="bot.meme_library",
            build=_meme_library_capability,
            text="meme random",
            note="T1.2：memes? random 同支；与 steal meme 同会话连跑时第二项常落 "
            "20s 会话冷却文案（真实防刷屏风控，非缺陷）",
            expect=expect_meme_library_pick,
        ),
        MatrixItem(
            key="news-trad",
            label="⑤快報（繁體）",
            capability_id="bot.news",
            build=lambda rt: build_news_capability(rt.config),
            text="快報",
            note="fix-tra2：繁體族 10 词入 _NEWS_TRIGGER_RE；类目提取繁體缺口（tra2 残余①）→ 落 mix 类目",
        ),
        MatrixItem(
            key="randpic-trad",
            label="⑦隨機圖（繁體）",
            capability_id="bot.randpic",
            build=lambda rt: build_randpic_capability(rt.config),
            text="隨機圖",
            note="fix-tra2：隨機圖/來張圖 对向繁體；BOT_RANDPIC_DIRS 未配置时降级文案（真实行为）",
        ),
        MatrixItem(
            key="guard-stocks-openai-question",
            label="劫持守卫（openai是什么 → 不触发个股）",
            capability_id="bot.text",
            build=lambda rt: _router_gated_capability(
                rt,
                detector=is_stocks_command,
                domain_builder=lambda rt2: build_stocks_capability(
                    rt2.config, render_backend=rt2.render_backend
                ),
                domain_label="个股行情",
            ),
            text="openai是什么",
            note="test_stocks_hijack_guard：路由层让路 moegirl_question；"
            "本项镜像 is_stocks_command 门（直喂会误走 NON_PUBLIC 分支），断言零股价/估值内容",
            expect=expect_chat_fallthrough(
                markers=_STOCK_CONTENT_MARKERS + ("估值",),
                domain_label="个股行情",
            ),
        ),
        MatrixItem(
            key="guard-divination-fortune-sentence",
            label="劫持守卫（算命陈述句 → 不触发占卜）",
            capability_id="bot.text",
            build=lambda rt: _router_gated_capability(
                rt,
                detector=is_divination_command,
                domain_builder=lambda rt2: build_divination_capability(rt2.config),
                domain_label="占卜",
            ),
            text="我说算命都是骗人的",
            note="test_divination_hijack_guard 八连样例之一：应落 chat；"
            "本项镜像 is_divination_command 门（直喂会误出 bazi 排盘），断言零排盘/塔罗内容",
            expect=expect_chat_fallthrough(
                markers=("排盘", "四柱", "干造", "塔罗", "金钱卦"),
                domain_label="占卜",
            ),
        ),
        MatrixItem(
            key="guard-market-oil-price",
            label="排除守卫（油价行情 → 不触发股指）",
            capability_id="bot.text",
            build=lambda rt: _router_gated_capability(
                rt,
                detector=is_market_command,
                domain_builder=lambda rt2: build_market_capability(rt2.config),
                domain_label="全球股指",
            ),
            text="油价行情",
            note="test_market_exclusion_guard：非股市「行情」（油价/金价族）让路 chat；"
            "本项镜像 is_market_command 门（含 _NON_STOCK_RE 排除），断言零股指面板形态",
            expect=expect_chat_fallthrough(
                markers=("全球股指", "红涨绿跌", "行情数据", "拉不到"),
                domain_label="全球股指",
            ),
        ),
        # ---- 三期扩展（2026-09-15 夜批 §26）：决策影子查询 + A-19 群失败降级 ----
        MatrixItem(
            key="decision-query-admin",
            label="⑯决策影子查询（管理员）",
            capability_id="bot.decision",
            build=lambda rt: _decision_query_capability(
                rt, actor_roles=["super_admin", "admin"]
            ),
            text="/bot decision",
            note=(
                "§26.2 P-03：/bot decision [N] 缺省 20（1-100）；读真实 "
                "decision_trace.sqlite3（只读，缺库回落热缓冲→「暂无记录」同达成）；"
                "影子模式 legacy_only 下无痕迹属预期；生产 __init__ elif 接线待 "
                "§26.10 登记的补贴，本项验收能力出口本体"
            ),
            expect=expect_decision_query_admin,
        ),
        MatrixItem(
            key="decision-query-member",
            label="⑯决策影子查询（普通成员温和拒绝）",
            capability_id="bot.decision",
            build=lambda rt: _decision_query_capability(rt, actor_roles=[]),
            text="/bot decision",
            note=(
                "同命令非管理员 → ADMIN_GATE_TEMPLATES 池温和拒绝"
                "（audit: decision_denied），不得泄漏任何查询结果形态"
            ),
            expect=expect_admin_gate_refusal,
        ),
        MatrixItem(
            key="group-failure-ack",
            label="⑰A-19 群失败降级短句（正向）",
            capability_id="bot.selftest-fail",
            build=_group_failure_capability,
            text="E2E 验收 · A-19 群失败降级观察",
            note=(
                "§26.4 A-19：群聊能力失败错误态 → 池内温和短句（300s 会话节流）；"
                "私聊不覆盖（另有守岸人话术池）；拦截族静默见 group-busy-silent 负样本"
            ),
            expect=expect_group_failure_ack,
        ),
        MatrixItem(
            key="group-busy-silent",
            label="⑰A-19 负样本：超载快败保持静默",
            capability_id="bot.selftest-busy",
            build=_pipeline_busy_capability,
            text="E2E 验收 · A-19 超载快败静默观察",
            note=(
                "pipeline_busy 与限流/安静时间同属故意降频设计 → 必须零反馈"
                "（零入队请求）；本项在群/私聊两会话下同语义"
            ),
            expect=expect_pipeline_busy_silent,
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
    # expect 断言结果：空串=PASS / 未断言；非空=失败原因（断言自身异常也折算进来）。
    expect_fail_reason: str = ""
    # 本项执行时的会话类型（SessionType.value；自测/离线构造可留空）。
    # 供会话敏感的 expect 区分群/私聊语义（如 A-19 只覆盖群聊）。
    session_type: str = ""


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
        item=item,
        request_id=message.request_id,
        trigger_text=trigger,
        session_type=session_type.value,
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
    if item.expect is not None:
        try:
            outcome.expect_fail_reason = item.expect(outcome)
        except Exception as exc:  # noqa: BLE001 - 断言自身不得抛异常拖垮验收。
            outcome.expect_fail_reason = (
                f"expect check raised: {type(exc).__name__}: {exc}"
            )
        verdict = (
            "PASS"
            if not outcome.expect_fail_reason
            else f"FAIL: {outcome.expect_fail_reason}"
        )
        print(f"          ↳ expect: {verdict}")


# --------------------------------------------------------------------------
# 实战自测（2026-09-13 批次）：帮助注册表命令矩阵 + 响应收集 + 私聊报告
#
# 与存量矩阵的分工（诚实边界）：
# - 存量矩阵（build_matrix）：镜像 __init__ 装配、进程内跑真实能力 → 验证
#   「命令语义处理」（能力产出什么回复）。
# - 命令矩阵（--help-matrix，本节）：从 echo._HELP_ENTRIES 全 topics 生成
#   命令清单，DRY-RUN 只构造 OneBot payload + 离线路由体检；--execute 把
#   每条命令文本经现有发送链路（管线 → 共享 SQLite 队列 → bot worker →
#   OneBot WS → QQ）投递并等待回执，收集「响应/超时/异常」三态与耗时。
#   真实 bot 进程的入站命令处理无法从外部脚本注入（需要真实 QQ 客户端），
#   故本模式不声称验证命令语义，报告措辞据此保持诚实。
# --------------------------------------------------------------------------


DEFAULT_DELIVERY_WAIT_SECONDS = 20.0
DEFAULT_PROBE_WAIT_SECONDS = 15.0
DEFAULT_WS_HOST = "127.0.0.1"
DEFAULT_WS_PORT = 3001
# 连续 N 条超时且零投递确认 → 判定 bot worker 离线，中止余项（防延迟补发轰炸）。
EARLY_OFFLINE_TIMEOUT_LIMIT = 3
_DELIVERY_TERMINAL_OK = frozenset({"sent", "redirected"})
_DELIVERY_TERMINAL_FAIL = frozenset({"failed_final", "failed_retryable"})


@dataclass(frozen=True)
class HelpTopicSpec:
    """命令矩阵条目：帮助注册表一个 topic 的主触发形态。"""

    topic: str
    admin_only: bool
    aliases: tuple[str, ...]
    trigger: str
    trigger_source: str  # "index"=从 index 提取 / "alias"=别名兜底 / "override"=定点覆盖


# 提取器对「无文本命令形态」主题的定点覆盖（保持最小，避免随注册表漂移）：
# 「链接」主题的真触发是一条平台链接，不是它的别名。
_HELP_TOPIC_OVERRIDE_TRIGGERS = {
    "链接": BILI_SAMPLE_URL,
}

# 描述性候选里出现这些标点 → 该段是说明文字而非命令形态，回退别名。
_TRIGGER_DESC_PUNCT = "，。；？！…、"
# 去掉参数占位与括注：<request_id|debug_id> [数量] （仅群聊） (note)
_TRIGGER_STRIP_BRACKETS = re.compile(r"<[^<>]*>|\[[^\[\]]*\]|（[^（）]*）|\([^()]*\)")


def extract_primary_trigger(index: str, aliases: tuple[str, ...]) -> tuple[str, str]:
    """从 index 用法串提取主触发形态；提取失败回退 aliases[0]。

    规则（按 68 条实况设计，来源可审计）：
    1. 去掉「【主题】」标题；候选 = 第一个全角冒号后的用法段；
    2. 候选含描述性标点（，。；？！…、）→ 说明文字，回退别名；
    3. 剥参数占位 <…>/[…] 与括注 （…）/(…)（连内部 | 一起去掉）；
    4. 依次按 ｜、\\s|\\s、|、或、＋、/ 取第一候选（不以 / 开头才切 /，
       保住 /bot xxx、/订阅 add）；
    5. 兜底门：空 / 残留冒号 / 非斜杠命令但长度 >8 → 回退别名
       （治「戳机器人有概率收到回应」这类描述句混入）。
    返回 (trigger, source)，source ∈ {"index", "alias"}。
    """
    fallback = aliases[0] if aliases else ""
    body = index.split("】", 1)[1].strip() if "】" in index else index.strip()
    candidate = body.split("：", 1)[1].strip() if "：" in body else body
    if not candidate or any(mark in candidate for mark in _TRIGGER_DESC_PUNCT):
        return fallback, "alias"
    candidate = _TRIGGER_STRIP_BRACKETS.sub("", candidate)
    for sep in ("｜", " | "):
        if sep in candidate:
            candidate = candidate.split(sep, 1)[0]
            break
    if "|" in candidate:
        candidate = candidate.split("|", 1)[0]
    for sep in (" 或 ", "＋", " / "):
        if sep in candidate:
            candidate = candidate.split(sep, 1)[0]
            break
    if not candidate.startswith("/"):
        candidate = candidate.split("/", 1)[0]
    candidate = candidate.strip()
    if not candidate or "：" in candidate:
        return fallback, "alias"
    if not candidate.startswith("/") and len(candidate) > 8:
        return fallback, "alias"
    return candidate, "index"


def load_help_topic_specs() -> list[HelpTopicSpec]:
    """帮助注册表（echo._HELP_ENTRIES，只读 import）→ 命令矩阵条目清单。"""
    specs: list[HelpTopicSpec] = []
    for entry in _HELP_REGISTRY:
        topic = str(entry.get("topic", "") or "").strip()
        if not topic:
            continue
        aliases = tuple(
            str(alias).strip()
            for alias in (entry.get("aliases") or ())
            if str(alias).strip()
        )
        if topic in _HELP_TOPIC_OVERRIDE_TRIGGERS:
            trigger, source = _HELP_TOPIC_OVERRIDE_TRIGGERS[topic], "override"
        else:
            trigger, source = extract_primary_trigger(
                str(entry.get("index", "") or ""), aliases
            )
            if not trigger:
                trigger, source = topic, "alias"
        specs.append(
            HelpTopicSpec(
                topic=topic,
                admin_only=bool(entry.get("admin_only", False)),
                aliases=aliases,
                trigger=trigger,
                trigger_source=source,
            )
        )
    return specs


def filter_topic_specs(
    specs: list[HelpTopicSpec], subset: str
) -> tuple[list[HelpTopicSpec], list[str]]:
    """--subset 过滤：逗号分隔 token，匹配 topic/别名（全等优先、子串兜底，
    大小写不敏感）。返回 (命中清单, 未命中 token)。subset 为空 → 全量。"""
    tokens = [
        token.strip()
        for token in str(subset or "").replace("，", ",").split(",")
        if token.strip()
    ]
    if not tokens:
        return list(specs), []

    def _matches(spec: HelpTopicSpec, folded: str) -> bool:
        haystacks = [spec.topic, *spec.aliases]
        if any(h.casefold() == folded for h in haystacks):
            return True
        return any(folded in h.casefold() for h in haystacks)

    matched: list[HelpTopicSpec] = []
    unknown: list[str] = []
    for token in tokens:
        folded = token.casefold()
        hits = [spec for spec in specs if _matches(spec, folded)]
        if hits:
            matched.extend(hits)
        else:
            unknown.append(token)
    # 去重保序（同一 spec 可能被多个 token 命中）。
    seen: set[str] = set()
    unique: list[HelpTopicSpec] = []
    for spec in matched:
        if spec.topic in seen:
            continue
        seen.add(spec.topic)
        unique.append(spec)
    return unique, unknown


def build_command_payload(
    spec: HelpTopicSpec, *, session_type: SessionType, target_id: str
) -> dict[str, Any]:
    """构造 OneBot V11 发送 payload（DRY-RUN 只构造不发送）。"""
    is_group = session_type is SessionType.GROUP
    target_value: int | str = (
        int(target_id) if str(target_id).isdigit() else str(target_id)
    )
    params: dict[str, Any] = {"message": spec.trigger, "auto_escape": False}
    if is_group:
        params["group_id"] = target_value
        action = "send_group_msg"
    else:
        params["user_id"] = target_value
        action = "send_private_msg"
    return {"action": action, "params": params, "echo": f"e2e-{spec.topic}"}


def probe_ws_online(
    host: str, port: int, timeout: float = 3.0
) -> tuple[bool, float]:
    """TCP 探测 OneBot WS 端口是否有人监听。返回 (可达, 耗时秒)。"""
    start = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, time.monotonic() - start
    except OSError:
        return False, time.monotonic() - start


def resolve_ws_probe_endpoint(explicit: str = "") -> tuple[str, int]:
    """探测端点：--ws-probe host:port > ONEBOT_WS_URLS 首条 > 默认 127.0.0.1:3001。"""
    raw = str(explicit or "").strip()
    if not raw:
        raw = str(os.environ.get("ONEBOT_WS_URLS", "") or "").split(",")[0].strip()
    if raw:
        parts = urlsplit(raw if "://" in raw else f"ws://{raw}")
        host = parts.hostname or DEFAULT_WS_HOST
        port = parts.port or DEFAULT_WS_PORT
        return str(host), int(port)
    return DEFAULT_WS_HOST, DEFAULT_WS_PORT


def classify_spec_route(
    spec: HelpTopicSpec, config: Any
) -> tuple[str, str, str]:
    """离线路由体检：主触发文本走 classify_message_route（与 base_router 同源）。
    返回 (kind, capability_id, reason)；分类自身异常折算为 error 条目不抛出。"""
    try:
        decision = classify_message_route(spec.trigger, config=config)
        return (
            str(getattr(decision.kind, "value", decision.kind)),
            str(decision.capability_id),
            str(decision.reason),
        )
    except Exception as exc:  # noqa: BLE001 - 单条体检失败不拖垮矩阵。
        return "error", "bot.ignore", f"{type(exc).__name__}: {exc}"


@dataclass
class CommandOutcome:
    """命令矩阵单项结果（响应/超时/异常三态 + 耗时）。"""

    spec: HelpTopicSpec
    request_id: str = ""
    # delivered（拿到投递确认）/ timeout（预算内未确认）/ error（失败终态/异常）/
    # blocked（策略门拦截）/ skipped（离线中止未执行）
    status: str = "skipped"
    state: str = ""
    elapsed: float = 0.0
    error: str = ""
    route_kind: str = ""
    route_capability: str = ""
    route_reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def wait_for_delivery(
    queue: Any,
    *,
    request_id: str,
    budget: float,
    poll_interval: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[str, float]:
    """轮询共享队列直至终态或预算耗尽。返回 (状态, 耗时秒)。

    终态：sent/redirected（投递确认）与 failed_final/failed_retryable（确认失败）；
    预算耗尽返回 "timeout"（bot worker 离线/卡住/UNKNOWN 未决都落这里——不悬挂）。
    sleep/monotonic 可注入，供离线测试用微预算验证轮询语义。"""
    start = monotonic()
    while True:
        try:
            entry = queue.find_request(request_id)
        except Exception as exc:  # noqa: BLE001 - 队列查询异常按失败终态折算。
            return f"query_error:{type(exc).__name__}", monotonic() - start
        state = str(getattr(entry, "state", "") or "") if entry is not None else ""
        if state in _DELIVERY_TERMINAL_OK or state in _DELIVERY_TERMINAL_FAIL:
            return state, monotonic() - start
        if monotonic() - start >= budget:
            return "timeout", monotonic() - start
        sleep(poll_interval)


def status_from_delivery_state(state: str) -> str:
    if state in _DELIVERY_TERMINAL_OK:
        return "delivered"
    if state.startswith(("failed", "query_error")):
        return "error"
    return "timeout"


def summarize_results(outcomes: list[CommandOutcome]) -> dict[str, Any]:
    counts = Counter(outcome.status for outcome in outcomes)
    attempted = sum(counts[name] for name in ("delivered", "timeout", "error", "blocked"))
    pass_rate = (counts["delivered"] * 100.0 / attempted) if attempted else 0.0
    return {
        "total": len(outcomes),
        "attempted": attempted,
        "delivered": counts["delivered"],
        "timeout": counts["timeout"],
        "error": counts["error"],
        "blocked": counts["blocked"],
        "skipped": counts["skipped"],
        "pass_rate": round(pass_rate, 1),
    }


def render_run_report(
    outcomes: list[CommandOutcome],
    *,
    mode: str,
    target_desc: str,
    generated_at: str,
    subset_desc: str = "无",
    wait_budget: float = DEFAULT_DELIVERY_WAIT_SECONDS,
    ws_desc: str = "",
    headline: str = "",
) -> str:
    """给超管的人读汇总报告：通过率/超时清单/异常清单/建议复查项。"""
    summary = summarize_results(outcomes)
    lines = [
        "【E2E 实战自测报告】",
        (
            f"生成：{generated_at}｜模式：{mode}｜目标：{target_desc}"
            f"｜矩阵：{summary['total']} 主题（subset={subset_desc}）"
        ),
    ]
    if ws_desc:
        lines.append(f"链路探测：{ws_desc}")
    if headline:
        lines.append(f"摘要：{headline}")
    lines.extend(
        (
            "■ 总览",
            (
                f"尝试 {summary['attempted']}｜响应 {summary['delivered']}"
                f"｜超时 {summary['timeout']}｜异常 {summary['error']}"
                f"｜拦截 {summary['blocked']}｜未执行 {summary['skipped']}"
            ),
            (
                f"通过率 {summary['pass_rate']}%（响应/尝试；超时预算 {wait_budget:g}s）"
                if summary["attempted"]
                else f"无投递尝试（超时预算 {wait_budget:g}s）"
            ),
        )
    )
    timeouts = [o for o in outcomes if o.status == "timeout"]
    errors = [o for o in outcomes if o.status in ("error", "blocked")]
    skipped = [o for o in outcomes if o.status == "skipped"]
    lines.append("■ 超时清单")
    if timeouts:
        lines.extend(
            f"- {o.spec.topic}（{o.spec.trigger}）最后状态={o.state or '无'} 耗时={o.elapsed:.1f}s"
            for o in timeouts
        )
    else:
        lines.append("- 无")
    lines.append("■ 异常清单")
    if errors:
        lines.extend(
            f"- {o.spec.topic}（{o.spec.trigger}）状态={o.state or '无'}"
            f"{('：' + o.error) if o.error else ''}"
            for o in errors
        )
    else:
        lines.append("- 无")
    route_missed = [o for o in outcomes if o.route_kind in ("ignore", "chat", "error")]
    lines.append(
        "■ 路由未命中主题（文档型/自动触发型，或主形态需带参数如「天气 城市」「点歌 歌名」；"
        "仅供参考，不计入失败）"
    )
    if route_missed:
        lines.append(
            "- " + "、".join(f"{o.spec.topic}({o.route_kind})" for o in route_missed)
        )
    else:
        lines.append("- 无")
    lines.append("■ 建议复查项")
    suggestions: list[str] = []
    if timeouts:
        suggestions.append(
            f"超时 {len(timeouts)} 项：确认 bot 进程在线、send-queue worker 在投递"
            "（/bot status 看 queue 状态），再单独重跑 --subset 复测。"
        )
    if errors:
        suggestions.append(
            f"异常 {len(errors)} 项：按清单逐项排查；admin 主题需 --sender-id 为超管/管理员。"
        )
    if skipped:
        suggestions.append(f"未执行 {len(skipped)} 项：早停/离线中止所致，恢复后重跑补测。")
    if not suggestions:
        suggestions.append("全链路投递确认正常，无必查项。")
    lines.extend(f"{index}. {text}" for index, text in enumerate(suggestions, 1))
    return "\n".join(lines)


def write_report_file(report_text: str, report_file: str = "") -> Path:
    base = Path(report_file) if report_file else None
    path = base if base and str(base.parent) else (
        Path(tempfile.gettempdir())
        / f"e2e_report_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text, encoding="utf-8")
    return path


def deliver_or_write_report(
    report_text: str,
    *,
    runtime: E2eRuntime,
    pipeline: RuntimePipeline | None,
    execute: bool,
    online: bool,
    report_file: str = "",
) -> str:
    """报告投递：bot 在线且 --execute → 经发送链路私聊全部超管；
    否则写文件（--report-file 或 %TEMP%）并返回路径描述。"""
    saved = write_report_file(report_text, report_file)
    delivered_desc: list[str] = []
    if execute and online and pipeline is not None:
        admin_ids = [
            str(aid).strip()
            for aid in (getattr(runtime.config, "bot_super_admin_user_ids", []) or [])
            if str(aid).strip()
        ]
        if not admin_ids:
            delivered_desc.append("未配置 BOT_SUPER_ADMIN_USER_IDS，报告仅落盘")
        for admin_id in admin_ids:
            message = synthesize_message(
                text="E2E 实战自测报告",
                session_type=SessionType.PRIVATE,
                target_id=admin_id,
                sender_id=admin_id,
                bot_id=runtime.bot_id,
                seq=0,
            )
            try:
                receipt = pipeline.handle(
                    message,
                    _text_capability(runtime, body=report_text),
                    capability_id="bot.text",
                )
                delivered_desc.append(
                    f"超管 {admin_id} 私聊报告已入队（state={receipt.state.value}）"
                )
            except Exception as exc:  # noqa: BLE001 - 单个超管投递失败不拖垮其余。
                delivered_desc.append(f"超管 {admin_id} 私聊报告入队失败：{exc}")
    return "；".join(delivered_desc + [f"报告文件：{saved}"])


def build_results_document(
    outcomes: list[CommandOutcome],
    *,
    mode: str,
    target_desc: str,
    subset: list[str],
    ws_endpoint: tuple[str, int],
    ws_online: bool,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "schema": "e2e_help_matrix_results/v1",
        "generated_at": generated_at,
        "mode": mode,
        "target": target_desc,
        "subset": subset,
        "ws_probe": {
            "host": ws_endpoint[0],
            "port": ws_endpoint[1],
            "online": ws_online,
        },
        "summary": summarize_results(outcomes),
        "outcomes": [
            {
                "topic": outcome.spec.topic,
                "trigger": outcome.spec.trigger,
                "trigger_source": outcome.spec.trigger_source,
                "admin_only": outcome.spec.admin_only,
                "route_kind": outcome.route_kind,
                "route_capability": outcome.route_capability,
                "status": outcome.status,
                "state": outcome.state,
                "elapsed_ms": round(outcome.elapsed * 1000, 1),
                "error": outcome.error,
                "request_id": outcome.request_id,
            }
            for outcome in outcomes
        ],
    }


def write_json_document(document: dict[str, Any], json_out: str) -> Path:
    path = (
        Path(json_out)
        if json_out
        else Path(tempfile.gettempdir())
        / f"e2e_help_matrix_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


# --------------------------------------------------------------------------
# 实战自测：--selftest（全离线自检，pytest 同源）
# --------------------------------------------------------------------------


def _scripted_queue(states: list[str]) -> Any:
    """wait_for_delivery 的离线脚本队列：按调用次序吐状态，末态保持。"""

    class _ScriptedQueue:
        def __init__(self, sequence: list[str]) -> None:
            self._sequence = sequence
            self.calls = 0

        def find_request(self, request_id: str) -> Any:
            self.calls += 1
            index = min(self.calls - 1, len(self._sequence) - 1)
            return SimpleNamespace(state=self._sequence[index])

    return _ScriptedQueue(states)


def _selftest_config() -> Config:
    # 与离线测试同口径：关安静时间/好感度，绝不打开 Runtime 真实库。
    return Config(bot_quiet_hours_enabled=False, bot_affinity_enabled=False)


_SELFTEST_TRIGGER_EXPECTATIONS = {
    "状态": "/bot status",
    "为什么": "/bot why",
    "决策": "/bot decision",
    "记忆": "/bot memory add",
    "历史": "/bot history clear",
    "怪癖": "/bot quirk list",
    "设置": "/bot runtime set",
    "身份": "/bot identity show",
    "帮助": "/bot help",
    "订阅": "/订阅 add",
    "点歌": "点歌",
    "天气": "天气",
    "行情": "行情",
    "个股行情": "英伟达股价",
    "汇率": "汇率",
    "快报": "快报",
    "占卜": "占卜",
    "提醒": "提醒",  # '12点提醒我写作业' 9 字触发非斜杠长度门 → 别名兜底
    "随机图": "随机图",
    "好感度": "好感度",
    "媒体归档": "收藏",
    "自然语言": "帮我查杭州天气",
    "模型": "/bot model list",
    "用量": "/bot model usage",
    "文件": "文件",
    "群文件": "/bot 群文件",
    "Epic": "epic",
}


def run_selftest() -> tuple[int, list[str]]:
    """全离线自检：矩阵生成/触发提取/subset/payload/报告/探针/轮询。
    返回 (退出码, 逐项检查行)；不依赖 bot 在线、不读 .env、不联网。"""
    lines: list[str] = []
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        if not ok:
            failures += 1
        lines.append(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))

    # 1. 帮助注册表加载（真相源 echo._HELP_ENTRIES，只读 import）。
    specs = load_help_topic_specs()
    topics = [spec.topic for spec in specs]
    ok = len(specs) >= 60 and len(topics) == len(set(topics)) and all(
        spec.aliases and spec.trigger for spec in specs
    )
    check("registry_load", ok, f"topics={len(specs)}")

    # 2. 主触发形态提取（逐条对照实跑钉住的期望表）。
    by_topic = {spec.topic: spec for spec in specs}
    mismatches = [
        f"{topic}: 期望 {expected!r} 实得 {by_topic[topic].trigger!r}"
        f"({by_topic[topic].trigger_source})"
        for topic, expected in _SELFTEST_TRIGGER_EXPECTATIONS.items()
        if by_topic[topic].trigger != expected
    ]
    check("trigger_extraction", not mismatches, "; ".join(mismatches) or "全部命中")

    # 3. 文档型主题回退别名且来源可审计。
    doc_topics = ["忽略", "戳一戳", "表情收库", "聊天"]
    bad = [
        topic
        for topic in doc_topics
        if by_topic[topic].trigger_source != "alias"
        or by_topic[topic].trigger not in by_topic[topic].aliases
    ]
    check("trigger_alias_fallback", not bad, f"异常项={bad or '无'}")

    # 4. 定点覆盖（链接 → 平台链接样例）。
    check(
        "trigger_override",
        by_topic["链接"].trigger == BILI_SAMPLE_URL
        and by_topic["链接"].trigger_source == "override",
    )

    # 5. --subset 过滤：命中 + 未命中 token。
    matched, unknown = filter_topic_specs(specs, "天气,点歌,不存在的主题")
    check(
        "subset_filter",
        [spec.topic for spec in matched] == ["天气", "点歌"]
        and unknown == ["不存在的主题"],
    )

    # 6. payload 构造（群/私聊两形态）。
    weather = by_topic["天气"]
    group_payload = build_command_payload(
        weather, session_type=SessionType.GROUP, target_id="123456"
    )
    private_payload = build_command_payload(
        weather, session_type=SessionType.PRIVATE, target_id="10001"
    )
    check(
        "payload_build",
        group_payload["action"] == "send_group_msg"
        and group_payload["params"]["group_id"] == 123456
        and group_payload["params"]["message"] == "天气"
        and private_payload["action"] == "send_private_msg"
        and private_payload["params"]["user_id"] == 10001,
    )

    # 7. 离线路由体检：全 topics 不抛异常；管理命令命中命令路由族。
    #    2026-09-18 核心链路排查：原 carve-out（未提交批次 runtime/timesync.py 的
    #    now() 缺 global _SHARED 声明 → UnboundLocalError，令「提醒」信号词路由
    #    必崩）经实跑确认**已修复**——真身 domains/schedule/timesync/timesync.py
    #    的 now() 已带 `global _SHARED, _SHARED_SIGNATURE`，直调返回正确时间。
    #    据此移除该特判：路由异常一律判 FAIL，不再有被静默降级为 WARN 的盲区。
    config = _selftest_config()
    route_probed: list[tuple[str, str, str]] = []
    for spec in specs:
        kind, capability, reason = classify_spec_route(spec, config)
        route_probed.append((spec.topic, f"{kind}/{capability}", reason))
    status_kind, status_capability, _ = classify_spec_route(by_topic["状态"], config)
    route_errors = {
        topic
        for topic, route, _reason in route_probed
        if route.startswith("error/")
    }
    check(
        "route_probe",
        not route_errors and status_capability.startswith("bot."),
        f"status→{status_kind}/{status_capability}; "
        f"路由异常={sorted(route_errors) or '无'}",
    )

    # 8. 报告渲染：三清单 + 通过率 + 建议复查。
    def _outcome(topic: str, status: str, **kwargs: Any) -> CommandOutcome:
        return CommandOutcome(spec=by_topic[topic], status=status, **kwargs)

    sample = [
        _outcome("天气", "delivered", state="sent", elapsed=1.2),
        _outcome("点歌", "delivered", state="sent", elapsed=2.5),
        _outcome("行情", "timeout", state="queued", elapsed=20.0),
        _outcome("汇率", "error", state="failed_final", error="boom"),
        _outcome("占卜", "skipped"),
    ]
    report = render_run_report(
        sample,
        mode="execute",
        target_desc="group:555",
        generated_at="2026-09-13 00:00:00",
    )
    check(
        "report_render",
        all(
            token in report
            for token in ("通过率 50.0%", "超时清单", "异常清单", "建议复查项", "行情")
        ),
    )

    # 9. WS 探针离线快速失败（本机不可能监听的端口）。
    online, elapsed = probe_ws_online("127.0.0.1", 1, timeout=1.5)
    check("ws_probe_offline", not online and elapsed < 5.0, f"elapsed={elapsed:.2f}s")

    # 10. 投递轮询：终态确认 / 预算超时 / 失败终态（微预算+注入时钟，零等待）。
    state_ok, took = wait_for_delivery(
        _scripted_queue(["queued", "queued", "sent"]),
        request_id="x",
        budget=5.0,
        poll_interval=0.0,
        sleep=lambda _s: None,
    )
    state_timeout, _ = wait_for_delivery(
        _scripted_queue(["queued"]), request_id="x", budget=0.0, poll_interval=0.0
    )
    state_fail, _ = wait_for_delivery(
        _scripted_queue(["failed_final"]), request_id="x", budget=1.0, poll_interval=0.0
    )
    check(
        "wait_for_delivery",
        state_ok == "sent"
        and status_from_delivery_state(state_ok) == "delivered"
        and state_timeout == "timeout"
        and status_from_delivery_state(state_timeout) == "timeout"
        and state_fail == "failed_final"
        and status_from_delivery_state(state_fail) == "error",
        f"ok={state_ok}/{took:.2f}s timeout={state_timeout} fail={state_fail}",
    )

    # 11. 汇总与 JSON 文档结构。
    summary = summarize_results(sample)
    document = build_results_document(
        sample,
        mode="execute",
        target_desc="group:555",
        subset=["天气"],
        ws_endpoint=("127.0.0.1", 3001),
        ws_online=False,
        generated_at="2026-09-13 00:00:00",
    )
    check(
        "summary_json",
        summary["attempted"] == 4
        and summary["delivered"] == 2
        and summary["timeout"] == 1
        and summary["error"] == 1
        and summary["skipped"] == 1
        and summary["pass_rate"] == 50.0
        and document["summary"] == summary
        and len(document["outcomes"]) == len(sample),
    )

    # 12. 2026-09-15 夜批 §26 新增矩阵项：结构完整 + 决策查询双路径离线语义
    #     （注入内存 sink，零磁盘；管理员出痕迹摘要、普通成员温和拒绝）。
    fake_rt = E2eRuntime(
        config=config,
        runtime_settings={},
        render_backend=None,
        execute=False,
        city="",
        bot_id="selftest-bot",
        sender_id="10000",
    )
    matrix = build_matrix(fake_rt)
    matrix_keys = [item.key for item in matrix]
    nightly_keys = {
        "decision-query-admin",
        "decision-query-member",
        "group-failure-ack",
        "group-busy-silent",
    }
    check(
        "nightly_matrix_structure",
        len(matrix_keys) == len(set(matrix_keys)) and nightly_keys <= set(matrix_keys),
        f"items={len(matrix_keys)}",
    )
    admin_body = str(
        build_decision_query_result(
            request_id="st-admin",
            actor_roles=["super_admin", "admin"],
            sink=InMemoryDecisionTraceSink(),
        ).body
    )
    member_body = str(
        build_decision_query_result(
            request_id="st-member", actor_roles=[], sink=InMemoryDecisionTraceSink()
        ).body
    )
    check(
        "decision_query_paths",
        "决策影子痕迹" in admin_body
        and "管理员" in member_body
        and "决策影子痕迹：" not in member_body,
        f"admin={admin_body.splitlines()[0][:48]!r} member={member_body[:48]!r}",
    )

    # 13. A-19 群失败降级：正向补池内短句 + 负样本（超载快败）零反馈
    #     （离线真实管线执行：策略→能力→A-19 通知→队列回查→expect 全链）。
    a19_queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    a19_pipeline = RuntimePipeline(
        send_queue=a19_queue,
        audit_logger=InMemoryAuditLogger(),
        rate_limiter=build_rate_limiter(config),
        quiet_hours_checker=build_quiet_hours_checker(config),
    )
    by_key = {item.key: item for item in matrix}
    a19_failures: dict[str, str] = {}
    for key, seq in (("group-failure-ack", 1), ("group-busy-silent", 2)):
        item = by_key[key]
        message = synthesize_message(
            text=item.trigger_text(fake_rt),
            session_type=SessionType.GROUP,
            target_id="555",
            sender_id="10000",
            bot_id="selftest-bot",
            seq=seq,
        )
        outcome = ItemOutcome(
            item=item,
            request_id=message.request_id,
            trigger_text=item.trigger_text(fake_rt),
            session_type=SessionType.GROUP.value,
        )
        try:
            outcome.receipt = a19_pipeline.handle(
                message, item.build(fake_rt), capability_id=item.capability_id
            )
            try:
                outcome.send_request = a19_queue.find_request(message.request_id)
            except Exception:  # noqa: BLE001 - 队列回查失败按无回执处理。
                outcome.send_request = None
            a19_failures[key] = item.expect(outcome) if item.expect else ""
        except Exception as exc:  # noqa: BLE001 - 自检内异常按 FAIL 折算。
            a19_failures[key] = f"{type(exc).__name__}: {exc}"
    check(
        "a19_group_failure",
        not a19_failures["group-failure-ack"]
        and not a19_failures["group-busy-silent"],
        f"ack={a19_failures['group-failure-ack'] or 'PASS'} "
        f"busy={a19_failures['group-busy-silent'] or 'PASS'}",
    )

    lines.insert(0, f"===== E2E selftest：{len(lines) - failures}/{len(lines)} 项通过 =====")
    return (0 if failures == 0 else 1), lines


# --------------------------------------------------------------------------
# 实战自测：--help-matrix 运行器
# --------------------------------------------------------------------------


def _print_help_matrix_dry_run(
    outcomes: list[CommandOutcome], total: int
) -> None:
    for index, outcome in enumerate(outcomes, 1):
        spec = outcome.spec
        payload = outcome.payload
        params = payload.get("params", {}) if isinstance(payload, dict) else {}
        route = f"{outcome.route_kind}/{outcome.route_capability}"
        admin = "Y" if spec.admin_only else "N"
        print(
            f"[{index}/{total}] {spec.topic} admin={admin} 触发={spec.trigger!r}"
            f"（{spec.trigger_source}）路由={route}"
        )
        print(
            f"          ↳ payload: {payload.get('action', '?')} "
            f"message={params.get('message', '')!r} target={params.get('group_id', params.get('user_id'))}"
        )


def run_help_matrix(args: argparse.Namespace) -> int:
    _reconfigure_stdio()
    runtime = build_runtime(
        env_file=args.env,
        execute=bool(args.execute),
        city=str(args.city or "").strip(),
        bot_id=str(args.bot_id or "").strip(),
        sender_id=str(
            args.sender_id or str(args.target_user or "").strip() or "10000"
        ).strip(),
    )
    specs, unknown = filter_topic_specs(load_help_topic_specs(), args.subset)
    if unknown:
        print(f"[提示] --subset 未命中 token：{unknown}", file=sys.stderr)
    if not specs:
        print("--subset 无匹配主题", file=sys.stderr)
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
        if target_id and not str(args.sender_id or "").strip():
            args.sender_id = target_id
        print(f"[安全阀] 私聊目标 {target_id}")

    ws_endpoint = resolve_ws_probe_endpoint(getattr(args, "ws_probe", "") or "")
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    target_desc = f"{session_type.value}:{target_id}"
    subset_list = [token for token in str(args.subset or "").replace("，", ",").split(",") if token.strip()]
    mode = "execute" if args.execute else "dry-run"

    outcomes: list[CommandOutcome] = []
    for spec in specs:
        outcome = CommandOutcome(spec=spec)
        outcome.payload = build_command_payload(
            spec, session_type=session_type, target_id=target_id
        )
        outcome.route_kind, outcome.route_capability, outcome.route_reason = (
            classify_spec_route(spec, runtime.config)
        )
        outcomes.append(outcome)

    if not args.execute:
        _print_help_matrix_dry_run(outcomes, len(outcomes))
        route_missed = sum(
            1 for o in outcomes if o.route_kind in ("ignore", "chat", "error")
        )
        print(
            f"\nDRY-RUN：{len(outcomes)} 条命令 payload 已构造，未发送。"
            f"路由未命中 {route_missed} 条（文档型/自动触发型或触发词失效，见逐条路由列）。"
        )
        document = build_results_document(
            outcomes,
            mode=mode,
            target_desc=target_desc,
            subset=subset_list,
            ws_endpoint=ws_endpoint,
            ws_online=False,
            generated_at=generated_at,
        )
        if args.json_out:
            print(f"[JSON] {write_json_document(document, args.json_out)}")
        if args.report:
            report = render_run_report(
                outcomes,
                mode=mode,
                target_desc=target_desc,
                generated_at=generated_at,
                subset_desc=",".join(subset_list) or "无",
                headline="DRY-RUN 矩阵审计（未发送）：投递验收请加 --execute。",
            )
            print(f"[报告] {deliver_or_write_report(report, runtime=runtime, pipeline=None, execute=False, online=False, report_file=args.report_file)}")
        return 0

    # ---- --execute：探测 → 探针 → 逐条发送+等回执 → 汇总/JSON/报告 ----
    ws_online, ws_elapsed = probe_ws_online(*ws_endpoint, timeout=3.0)
    print(
        f"[探测] OneBot WS {ws_endpoint[0]}:{ws_endpoint[1]} "
        f"{'可达' if ws_online else '不可达'}（{ws_elapsed:.2f}s）"
    )
    if not ws_online:
        report = render_run_report(
            outcomes,
            mode=mode,
            target_desc=target_desc,
            generated_at=generated_at,
            subset_desc=",".join(subset_list) or "无",
            ws_desc=f"{ws_endpoint[0]}:{ws_endpoint[1]} 不可达（离线快速失败，未发送任何消息）",
            headline="离线中止：bot/协议端（SnowLuma）未在线，全部条目未执行。",
        )
        for outcome in outcomes:
            outcome.status = "skipped"
            outcome.state = "offline"
        document = build_results_document(
            outcomes, mode=mode, target_desc=target_desc, subset=subset_list,
            ws_endpoint=ws_endpoint, ws_online=False, generated_at=generated_at,
        )
        json_path = write_json_document(document, args.json_out)
        report_desc = deliver_or_write_report(
            report, runtime=runtime, pipeline=None, execute=False, online=False,
            report_file=args.report_file,
        )
        print(f"[离线] 未发送任何消息。JSON：{json_path}")
        print(f"[报告] {report_desc}")
        return 3

    audit_logger = InMemoryAuditLogger()
    try:
        send_queue, queue_desc = choose_send_queue(runtime, audit_logger)
    except E2eSafetyError as exc:
        print(f"[安全阀] {exc}", file=sys.stderr)
        return 2
    print(f"[队列] {queue_desc}")
    pipeline = build_pipeline(runtime, send_queue)

    # worker 存活探针：一条无害文本，预算内拿到投递确认才继续（防 68 条延迟补发轰炸）。
    probe_outcome = CommandOutcome(spec=HelpTopicSpec(
        topic="(探针)", admin_only=False, aliases=(), trigger="e2e-probe", trigger_source="override",
    ))
    probe_message = synthesize_message(
        text="E2E 实战自测探针（worker 存活探测，可忽略）",
        session_type=session_type,
        target_id=target_id,
        sender_id=runtime.sender_id,
        bot_id=runtime.bot_id,
        seq=0,
    )
    probe_outcome.request_id = probe_message.request_id
    try:
        probe_receipt = pipeline.handle(
            probe_message,
            _text_capability(runtime, body="E2E 实战自测探针（worker 存活探测，可忽略）"),
            capability_id="bot.text",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[探针] 管线异常，按离线中止：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    if probe_receipt.state.value in ("blocked", "skipped"):
        print(
            f"[探针] 被策略门拦截（state={probe_receipt.state.value}），"
            "无法验证 worker 存活；改由运行中连续超时早停兜底。"
        )
    else:
        state, took = wait_for_delivery(
            send_queue,
            request_id=probe_message.request_id,
            budget=float(args.probe_wait),
        )
        probe_outcome.status = status_from_delivery_state(state)
        probe_outcome.state, probe_outcome.elapsed = state, took
        if probe_outcome.status != "delivered":
            report = render_run_report(
                outcomes,
                mode=mode,
                target_desc=target_desc,
                generated_at=generated_at,
                subset_desc=",".join(subset_list) or "无",
                ws_desc=f"{ws_endpoint[0]}:{ws_endpoint[1]} TCP 可达，但 worker {args.probe_wait:g}s 内无投递确认",
                headline="离线中止：发送队列 worker 无响应（bot 未重启或未启用发送队列），全部条目未执行。",
            )
            for outcome in outcomes:
                outcome.status = "skipped"
                outcome.state = "worker-offline"
            document = build_results_document(
                outcomes, mode=mode, target_desc=target_desc, subset=subset_list,
                ws_endpoint=ws_endpoint, ws_online=True, generated_at=generated_at,
            )
            json_path = write_json_document(document, args.json_out)
            report_desc = deliver_or_write_report(
                report, runtime=runtime, pipeline=None, execute=False, online=False,
                report_file=args.report_file,
            )
            print(f"[离线] 探针超时（state={state}，{took:.1f}s）。JSON：{json_path}")
            print(f"[报告] {report_desc}")
            return 3
        print(f"[探针] worker 在线（state={state}，{took:.1f}s），开始逐条发送。")

    total = len(outcomes)
    delivered_so_far = 0
    timeout_streak = 0
    offline_abort = False
    for index, outcome in enumerate(outcomes, 1):
        spec = outcome.spec
        if offline_abort:
            outcome.status, outcome.state = "skipped", "offline-abort"
            continue
        message = synthesize_message(
            text=spec.trigger,
            session_type=session_type,
            target_id=target_id,
            sender_id=runtime.sender_id,
            bot_id=runtime.bot_id,
            seq=index,
        )
        outcome.request_id = message.request_id
        try:
            receipt = pipeline.handle(
                message,
                _text_capability(runtime, body=spec.trigger),
                capability_id="bot.text",
            )
        except Exception as exc:  # noqa: BLE001 - 单项异常不拖垮矩阵。
            outcome.status, outcome.error = "error", (
                f"pipeline raised: {type(exc).__name__}: {exc}"
            )
            timeout_streak = 0
            print(f"[{index}/{total}] {spec.topic} → ERROR: {outcome.error}")
            continue
        if receipt.state.value in ("blocked", "skipped"):
            outcome.status = "blocked"
            outcome.state = receipt.state.value
            print(
                f"[{index}/{total}] {spec.topic} → 拦截 state={receipt.state.value}"
                f"{' public=' + repr(receipt.public_message) if receipt.public_message else ''}"
            )
        else:
            state, took = wait_for_delivery(
                send_queue,
                request_id=message.request_id,
                budget=float(args.wait),
            )
            outcome.status = status_from_delivery_state(state)
            outcome.state, outcome.elapsed = state, took
            print(
                f"[{index}/{total}] {spec.topic} → {outcome.status}"
                f" state={state} 耗时={took:.1f}s"
            )
        if outcome.status == "delivered":
            delivered_so_far += 1
            timeout_streak = 0
        elif outcome.status == "timeout":
            timeout_streak += 1
            if delivered_so_far == 0 and timeout_streak >= EARLY_OFFLINE_TIMEOUT_LIMIT:
                offline_abort = True
                print(
                    f"[早停] 连续 {timeout_streak} 条超时且零投递确认，判定 worker 离线，"
                    f"中止余下 {total - index} 条（防 bot 重启后延迟补发轰炸）。",
                    file=sys.stderr,
                )
        else:
            timeout_streak = 0
        if index < total and args.interval > 0:
            time.sleep(args.interval)

    summary = summarize_results(outcomes)
    print("\n===== 命令矩阵验收汇总 =====")
    for outcome in outcomes:
        mark = {
            "delivered": "·",
            "timeout": "!",
            "error": "✗",
            "blocked": "✗",
            "skipped": "-",
        }.get(outcome.status, "?")
        suffix = (
            f" state={outcome.state}"
            + (f" 耗时={outcome.elapsed:.1f}s" if outcome.elapsed else "")
            + (f" {outcome.error}" if outcome.error else "")
        )
        print(f"{mark} {outcome.spec.topic:12s} {outcome.status}{suffix}")
    print(
        f"共 {summary['total']} 项：响应 {summary['delivered']}"
        f"｜超时 {summary['timeout']}｜异常 {summary['error']}"
        f"｜拦截 {summary['blocked']}｜未执行 {summary['skipped']}"
        f"｜通过率 {summary['pass_rate']}%。"
    )
    document = build_results_document(
        outcomes, mode=mode, target_desc=target_desc, subset=subset_list,
        ws_endpoint=ws_endpoint, ws_online=ws_online, generated_at=generated_at,
    )
    json_path = write_json_document(document, args.json_out)
    print(f"[JSON] {json_path}")
    exit_code = 0 if summary["timeout"] == 0 and summary["error"] == 0 and summary["blocked"] == 0 else 1
    if args.report:
        report = render_run_report(
            outcomes,
            mode=mode,
            target_desc=target_desc,
            generated_at=generated_at,
            subset_desc=",".join(subset_list) or "无",
            wait_budget=float(args.wait),
            ws_desc=f"{ws_endpoint[0]}:{ws_endpoint[1]} 可达，探针 {probe_outcome.elapsed:.1f}s 确认",
            headline=(
                "离线早停：部分条目未执行。" if offline_abort else ""
            ),
        )
        report_desc = deliver_or_write_report(
            report,
            runtime=runtime,
            pipeline=pipeline,
            execute=True,
            online=not offline_abort,
            report_file=args.report_file,
        )
        print(f"[报告] {report_desc}")
    return exit_code


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
    # 目标参数在 parser 层不强制（--selftest 全离线无需目标）；
    # 存量矩阵与 --help-matrix 在 main 里补同一语义的强制校验。
    target = parser.add_mutually_exclusive_group()
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
    # ---- 实战自测（2026-09-13 批次）：新参数只往后加，存量语义不变 ----
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="全离线自检：矩阵生成/触发提取/payload/报告/探针/轮询，无需目标与 bot 在线",
    )
    parser.add_argument(
        "--help-matrix",
        action="store_true",
        help="命令矩阵模式：从 echo._HELP_ENTRIES 全 topics 生成命令清单逐条验收"
        "（DRY-RUN 只构造 payload + 路由体检；--execute 逐条发送并等投递回执）",
    )
    parser.add_argument(
        "--subset",
        default="",
        help="命令矩阵只跑指定主题（逗号分隔，匹配 topic/别名；隐含 --help-matrix）",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="生成给超管的汇总报告（--execute 且 bot 在线时私聊超管，否则写文件）",
    )
    parser.add_argument(
        "--report-file", default="", help="报告落盘路径（默认 %%TEMP%%/e2e_report_<时间戳>.txt）"
    )
    parser.add_argument(
        "--json-out", default="", help="结构化结果 JSON 路径（execute 模式缺省也写 %%TEMP%%）"
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=DEFAULT_DELIVERY_WAIT_SECONDS,
        help=f"逐条投递回执等待预算秒数（默认 {DEFAULT_DELIVERY_WAIT_SECONDS:g}s）",
    )
    parser.add_argument(
        "--probe-wait",
        type=float,
        default=DEFAULT_PROBE_WAIT_SECONDS,
        help=f"worker 存活探针等待秒数（默认 {DEFAULT_PROBE_WAIT_SECONDS:g}s）",
    )
    parser.add_argument(
        "--ws-probe",
        default="",
        help="OneBot WS 探测端点 host:port（默认 ONEBOT_WS_URLS 首条，再默认 127.0.0.1:3001）",
    )
    return parser


def _require_target(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not (args.target_group or args.target_user):
        parser.error("one of the arguments --target-group --target-user is required")


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdio()
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # 实战自测自检：全离线，不装配运行时、不读 .env、不要求目标。
    if args.selftest:
        code, lines = run_selftest()
        for line in lines:
            print(line)
        return code

    # 命令矩阵模式（--subset 隐含开启）；存量矩阵保持原语义。
    if args.help_matrix or str(args.subset or "").strip():
        _require_target(parser, args)
        return run_help_matrix(args)

    _require_target(parser, args)

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
    expect_fails = [
        outcome
        for outcome in outcomes
        if not outcome.error and outcome.expect_fail_reason
    ]
    print("\n===== 验收汇总 =====")
    for outcome in outcomes:
        state = outcome.receipt.state.value if outcome.receipt else "error"
        mark = "✗" if outcome.error or outcome.expect_fail_reason else "·"
        suffix = " expect-FAIL" if outcome.expect_fail_reason else ""
        print(f"{mark} {outcome.item.key:18s} {state}{suffix}")
    print(
        f"共 {len(outcomes)} 项，错误 {len(errors)} 项，期望未达成 {len(expect_fails)} 项。"
        + (
            "\n真发提示：--execute 项已入队，bot 的 send-queue worker 会按 "
            "BOT_SEND_QUEUE_WORKER_INTERVAL_SECONDS 逐条投递；请在目标群/私聊回 test 验收。"
            if args.execute
            else "\nDRY-RUN：以上为「将发内容」，未入真实队列。确认无误后加 --execute 重跑。"
        )
    )
    return 1 if errors or expect_fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

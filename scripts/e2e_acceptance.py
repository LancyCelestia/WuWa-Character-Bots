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
    is_divination_command,
)
from plugins.bot_unified_runtime.capabilities.echo import build_help_result
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


def build_matrix(runtime: E2eRuntime) -> list[MatrixItem]:
    """验收矩阵（①文本/长文本/多段 ②解析卡 ③点歌候选 ④全球股指 ⑤财经/科技快报
    ⑥天气+预警 ⑦随机图 ⑧占卜 ⑨help ⑩好感度 ⑪提醒查询
    ⑫个股行情+非上市守卫 ⑬汇率面板/定向换算 ⑭占卜金钱卦 ⑮称谓自助）。"""
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

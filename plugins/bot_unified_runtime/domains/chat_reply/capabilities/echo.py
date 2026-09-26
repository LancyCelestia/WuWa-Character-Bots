from __future__ import annotations

import asyncio
import hashlib
import html
import random
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

from plugins.bot_unified_runtime.audit import redact_private_debug
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    new_request_id,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    ROLE_SUPER_ADMIN,
    build_role_settings,
)
from plugins.bot_unified_runtime.domains.core.config.config_readiness import (
    run_config_smoke,
)
from plugins.bot_unified_runtime.domains.creation.reserved_health_alert import (
    creation_status_line,
    flush_reserved_issues_to_alerts,
)
from plugins.bot_unified_runtime.domains.media.voice_health_alert import (
    flush_probe_issue_to_alerts,
)
from plugins.bot_unified_runtime.domains.media.voice_health_probe import (
    voice_status_line,
)
from plugins.bot_unified_runtime.runtime import RuntimeControlState


class HelpEntry(TypedDict, total=False):
    topic: str
    admin_only: bool
    aliases: tuple[str, ...]
    index: str
    title_line: str
    lines: list[str]
    detail: str
    # 结构化扩展（向后兼容）：未填可省。数据经 _HELP_ENTRY_META 侧表登记、
    # 运行时合并；约定只在条目文本或项目文档有据时填写，宁缺勿臆造。
    capability: str
    network: bool
    chat_scope: str
    triggers_nl: tuple[str, ...]
    triggers_nickname: tuple[str, ...]
    config_vars: tuple[str, ...]
    examples: tuple[str, ...]
    tests: tuple[str, ...]
    outputs: tuple[str, ...]
    html_image: bool
    fallback: str


def _is_admin_actor(actor_roles: list[str] | None) -> bool:
    return "admin" in {str(role).strip() for role in (actor_roles or [])}


def build_status_result(
    config: Config | None = None,
    request_id: str | None = None,
    runtime_control: RuntimeControlState | None = None,
    actor_roles: list[str] | None = None,
) -> CapabilityResult:
    # 管理员门（审计重发现 P2）：status 会输出软暂停状态/原因、角色计数、
    # LLM provider/model、api_key set/missing、限速 bypass 角色等运行时姿态，
    # 与 debug 排障命令同档，不对普通成员开放。
    if not _is_admin_actor(actor_roles):
        return CapabilityResult(
            request_id=request_id or new_request_id("status"),
            capability_id="bot.status",
            kind="text",
            title="状态",
            # 审查 Q-02：权限拒绝入 user_copy 池（守岸人语气轮换）。
            body=random.choice(user_copy.ADMIN_GATE_TEMPLATES).format(action="看运行时状态"),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            send_policy=SendPolicy.IMMEDIATE,
        )
    status_config = config or Config()
    body = _build_status_body(status_config, runtime_control or RuntimeControlState())
    # 第 5 项（2026-09-25 接线）：超管在 /bot status 里附带宿主机快照行 + 状态卡。
    # 非超管路径不进入本分支 ⇒ 输出与接线前逐字节一致（回归锁见
    # tests/test_host_status.py::test_non_super_admin_status_body_is_unchanged）。
    host_lines, host_card_path = _host_status_extension(actor_roles)
    if host_lines:
        body = body + "\n" + "\n".join(host_lines)
    return CapabilityResult(
        request_id=request_id or new_request_id("status"),
        capability_id="bot.status",
        kind="text",
        title="状态",
        body=body,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
        images=[{"file": host_card_path}] if host_card_path else [],
    )


def _running_loop_here() -> bool:
    """当前线程是否跑着事件循环（能力被线程池 offload 时返回 False）。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _host_status_extension(
    actor_roles: list[str] | None,
) -> tuple[list[str], str]:
    """超管专属的宿主机附块：返回（标注行列表，卡片 PNG 路径或空串）。

    判据复用唯一角色源（roles.ROLE_SUPER_ADMIN，命令入口已随 decision.actor_roles
    带来），**零新配置键、零新名单**。非超管直接回空——调用方因此逐字节不变。

    线程口径（第 5 项 b）：`bot.status` 今天**不在**根 `__init__.py` 的
    ``OFFLOADED_CAPABILITY_IDS`` 里，``pipeline.handle`` 在事件循环线程同步调用
    能力（pipeline.py:1396,:1411）⇒ 本函数被 loop 调用时绝不做秒级的事：
    读数只吃缓存（`allow_blocking=False`）、不出卡（Playwright 渲染要秒级，
    压到 loop 上就是全会话卡死）。根把 "bot.status" 加进 offload 名单后（NEEDS-MAIN），
    这里自动走现取+出卡分支，零改动。
    """
    roles = {str(role).strip().lower() for role in (actor_roles or [])}
    if ROLE_SUPER_ADMIN not in roles:
        return [], ""
    from plugins.bot_unified_runtime.domains.ops.monitor import host_card, host_status

    off_loop = not _running_loop_here()
    groups, taken_at = host_status.cached_host_snapshot(allow_blocking=off_loop)
    rows = [row for items in groups.values() for row in items]
    if not rows:
        return (
            [
                (
                    "宿主机（超管视图）：这会儿拿不到读数——采集器没有可用数据源"
                    "（psutil 缺席，或本路径尚未在线程池里跑过一次现取）。"
                )
            ],
            "",
        )
    lines = [f"宿主机（超管视图，取样 {taken_at}）："]
    lines += [f"{label}：{value}" for label, value in rows]
    if not off_loop:
        # 诚实说明为什么只见字不见图——不是"图坏了"，是这条路今天不许渲染。
        lines.append("宿主机卡图片本轮未生成：/bot status 尚未接入线程池 offload。")
        return lines, ""
    card_png = host_card.render_host_card_png(groups, taken_at=taken_at)
    if not card_png:
        lines.append("宿主机卡未出图（渲染后端不可用），以上读数即全部结果。")
    return lines, card_png


# ==================== 决策影子痕迹查询（审查 P-03 消费侧） ====================
# 背景（A 方审计 P-03）：影子决策引擎的 trace sink 原本只有进程内 deque——
# 分歧记录无落库、无命令读取，是数据黑洞。落盘侧见 decision/trace.py
# （SqliteDecisionTraceSink：热缓冲+SQLite 异步落盘）；本节是查询消费的唯一
# 命令入口：/bot decision [N]（管理员），读最近 N 条输出路由分歧摘要。
# 脱敏红线：DecisionTrace 从设计上就不含任何消息原文，本命令只输出结构
# 字段（时间/路由/双方判定/耗时），自由文本字段（备注/错误）经
# redact_private_debug 打码 + 截断，双保险。

_DECISION_QUERY_DEFAULT_LIMIT = 20
_DECISION_QUERY_MAX_LIMIT = 100
_DECISION_NOTE_MAX_CHARS = 80


def _parse_decision_limit(query: str) -> int:
    """N 参数解析：缺省 20，钳制 1-100；垃圾输入回缺省（不报错不打脸）。"""
    try:
        return min(
            _DECISION_QUERY_MAX_LIMIT,
            max(1, int(query.strip() or _DECISION_QUERY_DEFAULT_LIMIT)),
        )
    except ValueError:
        return _DECISION_QUERY_DEFAULT_LIMIT


def _decision_note(value: str) -> str:
    """自由文本字段单行化 + 打码 + 截断（防串行刷屏与意外内容出卡）。"""
    text = redact_private_debug(str(value or "")).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > _DECISION_NOTE_MAX_CHARS:
        return text[:_DECISION_NOTE_MAX_CHARS] + "…"
    return text


def _format_decision_row(index: int, trace: Any) -> str:
    """单条痕迹 → 结构化摘要行（不回显任何用户原文）。"""
    created_at: Any = getattr(trace, "created_at", None)
    try:
        # UTC 落库，出卡转本地时区（运维读起来不烧脑）。
        stamp = created_at.astimezone().strftime("%m-%d %H:%M:%S")
    except (AttributeError, ValueError, OSError):
        stamp = "--"
    raw_agree: Any = getattr(trace, "agree", None)
    agree: bool | None = None if raw_agree is None else bool(raw_agree)
    if agree is True:
        verdict = "一致"
    elif agree is False:
        verdict = "分歧"
    else:
        verdict = "不可比"
    plan_cap = str(getattr(trace, "plan_capability_id", "") or "(引擎未判定)")
    plan_action = str(getattr(trace, "plan_action", "") or "")
    legacy_cap = str(getattr(trace, "legacy_capability_id", "") or "(无)")
    route_kind = str(getattr(trace, "route_kind", "") or "-")
    elapsed = float(getattr(trace, "elapsed_ms", 0.0) or 0.0)
    line = (
        f"{index}. {stamp} ｜ 路由 {route_kind} ｜ 引擎 {plan_cap}"
        f"{'(' + plan_action + ')' if plan_action else ''}"
        f" ｜ 现行 {legacy_cap} ｜ {verdict} ｜ {elapsed:.1f}ms"
    )
    notes: list[str] = []
    note = _decision_note(str(getattr(trace, "compare_note", "") or ""))
    if note:
        notes.append(f"   备注: {note}")
    error = _decision_note(str(getattr(trace, "error", "") or ""))
    if error:
        notes.append(f"   异常: {error}")
    return "\n".join([line, *notes])


def build_decision_query_result(
    *,
    request_id: str | None = None,
    actor_roles: list[str] | None,
    query: str = "",
    sink: Any = None,
) -> CapabilityResult:
    """``/bot decision [N]``：影子决策痕迹查询（管理员专属，审查 P-03）。

    读最近 N 条（默认 20，1-100）；优先读 SQLite 落盘（跨重启可查），
    库缺失/为空回落热缓冲。sink 可注入（测试隔离），缺省取进程默认 sink。
    """
    if not _is_admin_actor(actor_roles):
        return CapabilityResult(
            request_id=request_id or new_request_id("decision"),
            capability_id="bot.decision",
            kind="text",
            title="决策影子",
            body=random.choice(user_copy.ADMIN_GATE_TEMPLATES).format(
                action="查决策影子痕迹"
            ),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PERSONAL,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=["decision_query", "p03", "decision_denied"],
        )
    if sink is None:
        # 函数内惰性导入：echo 是高频导入模块，决策包保持按需拉起。
        from plugins.bot_unified_runtime.domains.core.decision.trace import (
            get_decision_trace_sink,
        )

        sink = get_decision_trace_sink()
    limit = _parse_decision_limit(query)
    recent = getattr(sink, "recent", None)
    traces: list[Any]
    if callable(recent):
        traces = list(recent(limit))  # SQLite 侧（新→旧）
    else:
        # 兜底：只有 InMemory 语义的 sink（如测试注入）取快照尾部，同口径新→旧。
        traces = list(reversed(sink.snapshot()))[:limit]
    if not traces:
        body = (
            "决策影子痕迹：暂无记录。\n"
            "影子模式（BOT_DECISION_ENGINE_MODE=shadow）才会产生痕迹；"
            "参数 /bot decision N 可调条数（1-100）。"
        )
    else:
        lines = [f"决策影子痕迹：最近 {len(traces)} 条（新→旧）"]
        lines.extend(_format_decision_row(i, t) for i, t in enumerate(traces, 1))
        lines.append("（只含结构字段，不回显消息原文）")
        body = "\n".join(lines)
    return CapabilityResult(
        request_id=request_id or new_request_id("decision"),
        capability_id="bot.decision",
        kind="text",
        title="决策影子",
        body=body,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["decision_query", "p03"],
    )


def normalize_help_topic(query: str) -> str | None:
    return _HELP_ALIAS_MAP.get((query or "").strip().lower())


def parse_help_command_text(command_text: str) -> str:
    """把 '/bot help <主题>'、'/bot 帮助 <主题>'、'帮助 <主题>' 中的主题提取出来。"""
    text = (command_text or "").strip()
    lowered = text.lower()
    for prefix in ("/bot", "/!"):
        if lowered == prefix:
            return ""
        if lowered.startswith(prefix + " "):
            text = text[len(prefix):].strip()
            lowered = text.lower()
            break
    for prefix in ("help", "帮助"):
        if lowered == prefix:
            return ""
        if lowered.startswith((prefix + " ", prefix + "　")):
            return text[len(prefix):].strip()
    return text


def resolve_help_query(command_text: str) -> str:
    """接入层用：只有明确是 help/帮助 前缀时才把主题交给帮助详情；其余回空=总览。"""
    text = (command_text or "").strip()
    lowered = text.lower()
    if lowered.startswith("/bot"):
        text = text[len("/bot"):].strip()
        lowered = text.lower()
    # /bot commands：命令目录（机器可读），与 help 总览分开，不渲染卡片。
    if lowered in _COMMANDS_CATALOG_QUERY:
        return "commands"
    if (
        lowered in {"help", "帮助"}
        or lowered.startswith(("help ", "帮助 ", "help　", "帮助　"))
    ):
        return parse_help_command_text(text)
    return ""


# Ordinary users see only interactive public capabilities. Diagnostics, state,
# history and administration remain available to administrators.
_PUBLIC_HELP_TOPICS = frozenset(
    {
        "订阅", "点歌", "表情", "天气", "行情", "个股行情", "商品行情", "国债收益率", "北向资金", "汇率", "占卜", "快报", "维基", "萌娘百科",
        "历史上的今天", "下载", "昵称", "链接", "Epic", "好感度", "吃什么", "偷表情",
        "随机图", "提醒", "笔记", "收件箱", "语音", "搜图", "记忆", "路由", "草稿",
        "帮助", "聊天", "戳一戳", "表情收库", "自然语言", "群信息", "亲密模式",
    }
)


def _visible_help_entries(is_admin: bool) -> list[HelpEntry]:
    if is_admin:
        return list(_HELP_ENTRIES)
    return [entry for entry in _HELP_ENTRIES if entry["topic"] in _PUBLIC_HELP_TOPICS]


_HELP_CATEGORIES = (
    (
        "管理员专属",
        {
            "状态", "为什么", "回执", "审计", "最近", "日志", "解析", "上下文",
            "对话", "历史", "人格", "角色", "队列", "配置", "就绪", "接入",
            "暂停", "回复", "设置", "凭据", "群策略", "群文件", "文件",
            "身份", "怪癖", "限流", "合并转发", "群摘要", "视频理解", "运行开关",
            "邮件", "Telegram", "供应商", "忽略", "媒体归档", "决策", "功能管理", "紧急信息",
            "宿主机状态", "书面同意",
        },
    ),
    ("大模型相关", {"模型", "用量", "搜索"}),
    (
        "子功能",
        {
            "订阅", "点歌", "表情", "偷表情", "搜图", "Epic", "历史上的今天",
            "天气", "行情", "个股行情", "商品行情", "国债收益率", "北向资金", "汇率", "占卜", "快报", "维基", "萌娘百科", "下载",
            "昵称", "链接", "吃什么", "好感度", "随机图", "提醒", "笔记", "收件箱", "语音", "记忆", "路由",
            "草稿", "帮助", "聊天", "戳一戳", "表情收库", "自然语言", "群信息", "亲密模式",
        },
    ),
)


def _help_grouped(entries: list[HelpEntry]) -> list[tuple[str, list[HelpEntry]]]:
    """按分类分组，但**行序一律跟 ``_HELP_ENTRIES`` 的声明序**。

    ``_HELP_CATEGORIES`` 的成员是 ``set`` 字面量，直接 ``for topic in topics``
    会把哈希序带进帮助页——字符串哈希默认随机化，于是每次重启 bot，命令手册
    的行序都会重洗一次（2026-09-25 澜汐要"看得懂"，第一条就是别每次不一样）。
    分类表在这里只当成员判定用，顺序由条目声明序派生。
    """
    grouped: dict[str, list[HelpEntry]] = {}
    for entry in entries:
        topic = str(entry["topic"])
        for name, topics in _HELP_CATEGORIES:
            if topic in topics:
                grouped.setdefault(name, []).append(entry)
                break
        else:
            grouped.setdefault("更多", []).append(entry)
    ordered = [(name, grouped[name]) for name, _ in _HELP_CATEGORIES if grouped.get(name)]
    if grouped.get("更多"):
        ordered.append(("更多", grouped["更多"]))
    return ordered


def _help_index_body(*, page: int, is_admin: bool) -> str:
    """One-page categorized overview; ``help 1/2`` stays a compatibility alias.

    每行末尾附二级展开引导：回复 /bot help <模块> 查看该模块逐参数说明。
    """
    entries = _visible_help_entries(is_admin)
    title = "管理员帮助总览" if is_admin else "功能帮助总览"
    lines = [title, "（回复 /bot help 模块名 看该模块子功能与参数）"]

    def _index_line(entry: HelpEntry) -> str:
        index = str(entry["index"])
        topic = str(entry["topic"])
        if "help " in index or "bot " in index and "/" in index:
            # 指令型条目已带完整用法，不重复堆叠引导。
            return index
        return f"{index}｜详情：/bot help {topic}"

    for category, category_entries in _help_grouped(entries):
        lines.extend(("", f"【{category}】"))
        lines.extend(_index_line(entry) for entry in category_entries)
    return "\n".join(lines)


def _help_unknown_body(query: str) -> str:
    display = (query or "").strip()
    if len(display) > 40:
        display = display[:40] + "…"
    return (
        f"没有找到「{display}」的帮助主题。\n"
        "试试 /bot 帮助 查看总览（/岸宝帮助 同样可用）；示例：/bot help 点歌、/bot help 订阅。"
    )


# ==================== IGNORE 命令形态引导（审查 C-07） ====================
# 背景（A 方审计 C-07）：RouteKind.IGNORE 兜底全项目原无消费点——/help、
# /帮助 等命令形态落 IGNORE 后完全静默。本节是消费侧唯一产出点：只对
# 「命令形态但未命中任何能力」（base_router.is_command_form_text，且路由
# 已判 kind=IGNORE）的输入回一句守岸人语气引导。
# 静默语义红线（审查 C-07 裁定不波及）：普通闲聊走 CHAT、空文本/纯媒体
# 走「空消息兜底不回复」、限流与安静时间拦截的静默（09-12 实弹裁定）
# 都不经过本节。接线由主模块按既有 matcher 模式完成：rule 判
# kind=IGNORE ∧ is_command_form_text ∧ IgnoreGuideGate 节流，handler 经
# 统一管线发送——引导与其他回复同受群门禁/安静时间/限流约束，绝不绕过。

_IGNORE_GUIDE_LINES: tuple[str, ...] = (
    "没认出这个指令。发 /bot help 看看我会什么，好吗？",
    "这个指令我没对上号……发 /bot help 的话，我把会的一起给你看。",
    "咦，这个指令有点陌生。先看 /bot help，好吗？",
)

_ignore_guide_cursor = 0
_IGNORE_GUIDE_CURSOR_LOCK = threading.Lock()


def build_ignore_command_guidance() -> str:
    """守岸人语气引导语（进程内轮换取句，确定性；静态文案，不回显用户输入）。"""
    global _ignore_guide_cursor
    with _IGNORE_GUIDE_CURSOR_LOCK:
        line = _IGNORE_GUIDE_LINES[_ignore_guide_cursor % len(_IGNORE_GUIDE_LINES)]
        _ignore_guide_cursor += 1
    return line


class IgnoreGuideGate:
    """同会话引导节流（审查 C-07 防刷屏；进程内即可，默认 60 秒窗口）。

    同一会话（session_key）窗口内只放行一次引导，其余静默放过；时钟可
    注入（time.monotonic 兼容）保证测试确定性；容量有界（超限整体清空，
    与 base_router 路由缓存同策略），长期运行不无界增长。
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = 4096,
    ) -> None:
        self._window = float(window_seconds)
        self._clock = clock
        self._max_entries = max(1, int(max_entries))
        self._last_allowed: dict[str, float] = {}
        self._lock = threading.Lock()

    def check_and_mark(self, session_key: str) -> bool:
        """放行并占用本会话窗口名额；窗口内重复调用返回 False（不再回）。"""
        now = self._clock()
        with self._lock:
            last = self._last_allowed.get(session_key)
            if last is not None and now - last < self._window:
                return False
            if len(self._last_allowed) >= self._max_entries:
                self._last_allowed.clear()
            self._last_allowed[session_key] = now
            return True

    def reset(self) -> None:
        """清空节流状态（测试用）。"""
        with self._lock:
            self._last_allowed.clear()


def build_ignore_guide_result(
    request_id: str,
    *,
    guidance: str | None = None,
) -> CapabilityResult:
    """IGNORE 命令形态引导的 CapabilityResult。

    capability_id 沿用路由兜底席的 ``bot.ignore``（审计可归因，不新增
    能力目录项）；kind=text 走统一管线发送，群门禁/安静时间照常约束。
    """
    return CapabilityResult(
        request_id=request_id or new_request_id(),
        capability_id="bot.ignore",
        kind="text",
        body=guidance or build_ignore_command_guidance(),
        audit_tags=["ignore_guide", "c07"],
    )


# Keystone 对齐（审查 C-06 二期，2026-09-14 批）：能力单一声明源在
# runtime/capability_registry.py。本帮助注册表（含 _HELP_ENTRY_META/
# _HELP_EXTRA_LINES）保持字面形态——scripts/command_catalog.py 与
# scripts/doc_sync.py 以 AST/正则静态提取本文件文本（不 import 插件包），
# 不改为运行时构建；作为对价，每主题的 (topic, admin_only, capability)
# 权威三元组已登记进声明源 HELP_TOPIC_DECLARATIONS，逐 topic 强一致性由
# tests/test_capability_registry.py 常驻锁定——两份数据漂移即红。
# 增删主题 / 翻转可见性 / 改能力入口，必须同步声明源（topic 数以 `docs/auto-facts.md`
# 与 `command_catalog.py --check` 实跑输出为准，本注释不写死数字——2026-09-20 HELP-1 修
# 审计件 §B-3：此处曾手抄「73 topics」而权威值是 77）。
# 命令行文案的**唯一事实源是本表的 `lines[]`**；`detail` 只写叙述小节，
# 【指令与参数】段在装配期由 `_compose_help_detail()` 派生注入，手写即被
# tests/test_help_single_source.py 的结构锁拦下。

_HELP_ENTRIES: list[HelpEntry] = [
        {
            "topic": "功能管理", "admin_only": True,
            "aliases": ("功能管理", "feature"),
            "index": "【功能管理】查询和控制能力树：/bot feature",
            "title_line": "【功能管理】能力树状态与版本",
            "lines": [
                "/bot feature list：作用=列出能力节点；参数=无；内容=稳定ID和有效状态；意义=定位待管理功能。",
                "/bot feature get <ID>：作用=查询状态；参数=稳定ID；内容=有效状态、版本和图修订；意义=确认父级与依赖影响。",
                "/bot feature enable|disable|reset <ID>：作用=启用、禁用或恢复默认；参数=稳定ID；内容=新版本和审计ID；意义=受控调整功能，修改仅限超管，已运行任务不强杀。",
                "/bot feature preview <ID> on|off|reset：作用=预览变更；参数=稳定ID与目标状态；内容=影响节点；意义=写入前核对，不修改数据。",
            ],
            "detail": (
                "【权限与效果】\n"
                "权限=仅管理员（含超管）；管理员只读，修改仅限超管，预览仅限超管；受保护核心能力不可关闭。"
                "命令与控制面共用服务。当前仅覆盖已登记并接入主Pipeline的能力，入站媒体和直接平台副作用仍在迁移。"
            ),
        },
        {
            "topic": '状态',
            "admin_only": True,
            "aliases": ('状态', '狀態', 'status'),
            "index": '【状态】查看运行状态摘要：/bot status',
            "title_line": '【状态】查看运行状态摘要',
            "lines": [
                '/bot status：作用=查看运行状态摘要；参数=无；内容=软暂停状态/原因、角色计数、人格与知识文件缺失数、记忆/历史/诊断/审计/回执/队列的开关与存储（sqlite/memory）、限速与安静时间、LLM provider/model/key 状态与就绪下一步；超管另附宿主机快照行（处理器/显卡/内存/磁盘/占用/版本）与状态卡图片；意义=排障第一入口，出问题先看状态再 /bot why。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  一条命令看清机器人此刻的整体姿态：运行时开关、软暂停、权限角色数量、\n'
                '  人格/知识/记忆等文件的在位情况、各持久化存储落在 sqlite 还是内存、\n'
                '  LLM 供应商与密钥是否就绪。所有信息脱敏输出，不显示密钥与会话原文。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（普通成员发送会收到拒绝提示）。\n'
                '  内容逐段对应：运行时硬开关/软暂停与原因→权限角色计数（admin/enterprise/trusted/blocked）→\n'
                '  人格档案与人格文件缺失数→知识文件缺失数→记忆/最近对话/诊断/审计/回执/发送队列的\n'
                '  enabled 与 db 状态→情绪感知→回复限速（窗口/各层上限/绕过角色）→安静时间→LLM 配置与就绪原因。\n'
                '【示例】/bot status'
            ),
        },
        {
            "topic": '记忆',
            "admin_only": False,
            "aliases": ('记忆', 'memory'),
            "index": '【记忆】管理我的长期记忆：/bot memory add|list|delete',
            "title_line": '【记忆】管理我交给机器人的长期记忆',
            "lines": [
                '/bot memory add <内容>：作用=记住一句话；参数=内容（必填，建议 ≤1200 字），或加 --sensitivity=（可选，personal|group|public|credentialed，默认 personal）；内容=回显已记住的正文与 fact_id、sensitivity；意义=让机器人长期记住你的偏好与事实。',
                '/bot memory list：作用=列出我的记忆；参数=无；内容=fact_id＋sensitivity＋正文的清单（私聊=全部个人记忆，群聊=仅 public/group 两级）；意义=核对机器人到底记住了什么。',
                '/bot memory delete <fact_id>：作用=删除一条记忆；参数=fact_id（必填，来自 add/list 输出）；内容=成功回显已删除，找不到会明说；意义=撤回不想被记住的内容。',
                '权限=全员（只增删查“你本人”的记忆，别人的看不到也删不掉）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  长期记忆是你主动交给机器人的事实卡片（区别于自动抽取的印象）。\n'
                '  每条记忆归属“写入它的那个人＋所在会话”，互相隔离。\n'
                '【取值范围】\n'
                '  sensitivity 四级：personal（仅自己）/ group（本群可见）/ public（可公开）/ credentialed（敏感凭据类，谨慎使用）。\n'
                '【权限与效果】\n'
                '  权限=全员，无需管理员；只能操作自己作为主体的记忆。\n'
                '  前置条件：BOT_MEMORY_ENABLED=true 且 BOT_MEMORY_DB_PATH 已配置，否则提示先配置。\n'
                '【示例】/bot memory add 我对芒果过敏 --sensitivity=group → /bot memory list → /bot memory delete fact_xxxxxxxxxxxx'
            ),
        },
        {
            "topic": '为什么',
            "admin_only": True,
            "aliases": ('为什么', '为啥', 'why'),
            "index": '【为什么】解释最近决策：/bot why [id]',
            "title_line": '【为什么】解释最近一次回复的决策与错误',
            "lines": [
                '/bot why [id]：作用=解释一次回复的路由/策略/错误；参数=id（可选，request_id 或 debug_id，可从 /bot recent 或回执/审计输出里取；省略=最近一次）；内容=该请求的路由判定、策略命中、失败类型与线索；意义=回答“它刚才为什么这么回/为什么没回”。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  决策解释器：把某次请求“走了哪条路由、命中什么策略、在哪一步失败”\n'
                '  翻译成人话。诊断链路的第二步（第一步是 /bot status）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。没有可解释的记录时会提示先和机器人说一句话。\n'
                '【示例】/bot why｜/bot why help_8f2a1b3c'
            ),
        },
        {
            "topic": '回执',
            "admin_only": True,
            "aliases": ('回执', 'receipt'),
            "index": '【回执】查询发送回执：/bot receipt <request_id|debug_id>',
            "title_line": '【回执】查询发送回执',
            "lines": [
                '/bot receipt <id>：作用=查询一条消息的发送回执；参数=id（必填，request_id 或 debug_id，可从 /bot recent 的输出里取）；内容=该消息的投递状态（待发/已发/失败）与关键时间点；意义=区分“没生成”和“生成了但没发出去”，确认“我发的命令到底发出去没有”。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  发送回执记录每条出站消息的投递过程。BOT_RECEIPTS_ENABLED=true 时\n'
                '  落库可跨重启查询，默认内存态（重启即清）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。查不到时回显脱敏后的 id。\n'
                '【示例】/bot receipt 7c9f…（用 /bot recent 里出现的 id）'
            ),
        },
        {
            "topic": '审计',
            "admin_only": True,
            "aliases": ('审计', 'audit'),
            "index": '【审计】查询审计记录：/bot audit <request_id>',
            "title_line": '【审计】查询审计记录',
            "lines": [
                '/bot audit <request_id>：作用=查询一次请求的审计事件；参数=request_id（必填，请求编号）；内容=该请求全链路的审计事件列表（脱敏）；意义=合规排查与事后追因。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  审计记录由 BOT_AUDIT_ENABLED=true 时落库（默认内存态）。\n'
                '  每个请求的关键节点（入站/路由/出站/异常）都会留事件。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。未找到时回显脱敏后的编号。\n'
                '【示例】/bot audit music_9a3bb2'
            ),
        },
        {
            "topic": '最近',
            "admin_only": True,
            "aliases": ('最近', 'recent'),
            "index": '【最近】最近诊断摘要：/bot recent [数量]',
            "title_line": '【最近】查看最近排障摘要',
            "lines": [
                '/bot recent [数量]：作用=汇总最近诊断＋回执＋审计；参数=数量（可选，1-20 整数，默认 5）；内容=三个板块的最近记录摘要；意义=不用分别调三个查询，一屏看完最近发生了什么。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  /bot recent ＝ 诊断（diagnostics）＋发送回执（receipts）＋审计（audits）\n'
                '  三个查询的合并视图，按各自动态截取最近 N 条。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。输出里的 id 可直接喂给 /bot why、/bot receipt、/bot audit。\n'
                '【示例】/bot recent 10'
            ),
        },
        {
            "topic": '队列',
            "admin_only": True,
            "aliases": ('队列', 'queue'),
            "index": '【队列】发送队列状态：/bot queue',
            "title_line": '【队列】查看发送队列状态',
            "lines": [
                '/bot queue：作用=查看发送队列健康；参数=无；内容=待发/处理中/重试/失败计数与队列参数；意义=消息发不出去时判断是队列堆积还是投递失败。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  所有出站消息统一经发送队列收口。BOT_SEND_QUEUE_ENABLED=true 时\n'
                '  队列持久化到 sqlite，重启不丢。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。\n'
                '【示例】/bot queue'
            ),
        },
        {
            "topic": '上下文',
            "admin_only": True,
            "aliases": ('上下文', 'context'),
            "index": '【上下文】测试上下文：/bot context [测试文本]',
            "title_line": '【上下文】测试注入给模型的上下文',
            "lines": [
                '/bot context [文本]：作用=看一段话会被注入什么上下文；参数=文本（可选，省略用「你好，守岸人。」）；内容=人格/知识/记忆/最近对话的注入摘要与预算（只出数字摘要不泄露原文）；意义=验证人格与知识装配是否生效，不动线上状态。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  把“如果现在说这句话，模型会看到什么”完整走一遍：注入检查→回复预算→\n'
                '  人格+向量知识+记忆+最近对话装配→prompt 构造，全程只读。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。输出为数字摘要（条数/字数/预算），不回显知识库原文。\n'
                '  失败时只报错误类型，不泄露堆栈。\n'
                '【示例】/bot context 鸣潮的守岸人是谁'
            ),
        },
        {
            "topic": '对话',
            "admin_only": True,
            "aliases": ('对话', 'dialogue', '对话测试'),
            "index": '【对话】对话诊断：/bot dialogue [测试文本]',
            "title_line": '【对话】本地跑一轮对话诊断',
            "lines": [
                '/bot dialogue [文本]：作用=完整跑一轮对话链路验收；参数=文本（可选，省略用「你好，守岸人。」）；内容=对话各阶段结果（配置/上下文/LLM 调用/回复）；意义=端到端验证聊天链路，不影响线上会话状态。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  与 /bot context 的区别：dialogue 会真的走完 LLM 调用（配置了真实模型时\n'
                '  会产生一次真实调用费用），用于验收整条链路。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。可能产生一次 LLM 调用费用；不写入线上会话历史。\n'
                '【示例】/bot dialogue 今天状态怎么样'
            ),
        },
        {
            "topic": '接入',
            "admin_only": True,
            "aliases": ('接入', 'setup', 'llm setup'),
            "index": '【接入】LLM 接入清单：/bot setup llm',
            "title_line": '【接入】LLM 接入清单',
            "lines": [
                '/bot setup llm：作用=看接真实 LLM 还缺哪些配置；参数=无；内容=七个必配键（provider/model/key/base_url/temperature/max_tokens/timeout）的当前值、合法取值与标红缺口，附下一步指引；意义=接入向导，照着补 .env 就能通。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  把接入 OpenAI 兼容模型要动的七个键逐项体检。渲染可用时输出 Mica\n'
                '  配置卡；密钥永远只显示 已设置/缺失，不回显值。只读，不写 .env。\n'
                '【取值范围】\n'
                '  BOT_CHAT_PROVIDER=openai_compatible|static；MODEL=供应商模型名；KEY=真实密钥或 env:变量名；\n'
                '  BASE_URL=http(s):// 开头一般以 /v1 结尾；TEMPERATURE=0.0-2.0；MAX_TOKENS=≥0（0=不设上限）；TIMEOUT=>0 秒。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。改完 .env 重启生效；就绪后可用 /bot llm 做真实连接诊断。\n'
                '【示例】/bot setup llm'
            ),
        },
        {
            "topic": '配置',
            "admin_only": True,
            "aliases": ('配置', 'config'),
            "index": '【配置】配置检查：/bot config',
            "title_line": '【配置】配置就绪检查',
            "lines": [
                '/bot config：作用=配置体检；参数=无；内容=配置冒烟结果（缺什么、什么不合法，全部脱敏）；意义=改完配置后的快速自检。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  运行 config smoke：检查 LLM 接入、路径、模板等配置就绪度。\n'
                '  与 /bot setup llm 的区别：config 是全量体检，setup llm 只聚焦 LLM 七键。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。\n'
                '【示例】/bot config'
            ),
        },
        {
            "topic": '就绪',
            "admin_only": True,
            "aliases": ('就绪', 'readiness'),
            "index": '【就绪】聚合就绪状态：/bot readiness',
            "title_line": '【就绪】聚合就绪状态',
            "lines": [
                '/bot readiness：作用=聚合各链路就绪度；参数=无；内容=环境/配置/上下文/对话链路的就绪判定与软暂停状态；意义=开机后一眼判断能不能正常接客。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  readiness smoke 的聊天入口：把环境依赖、配置、上下文装配、对话链路\n'
                '  的就绪状态聚合成一份报告，附带运行时软暂停状态。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。\n'
                '【示例】/bot readiness'
            ),
        },
        {
            "topic": '角色',
            "admin_only": True,
            "aliases": ('角色', 'roles'),
            "index": '【角色】权限角色摘要：/bot roles',
            "title_line": '【角色】权限角色摘要',
            "lines": [
                '/bot roles：作用=看权限角色分布；参数=无；内容=admin/enterprise/trusted/blocked 的数量摘要（不含具体 ID）；意义=核对 BOT_ADMIN_USER_IDS 等名单是否被正确加载。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  角色体系：user < trusted < enterprise < admin（另有 blocked 屏蔽）。\n'
                '  管理员由 BOT_ADMIN_USER_IDS（QQ）与 BOT_TELEGRAM_ADMIN_USER_IDS（TG）确定。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。\n'
                '【示例】/bot roles'
            ),
        },
        {
            "topic": '人格',
            "admin_only": True,
            "aliases": ('人格', 'persona'),
            "index": '【人格】人格自检：/bot persona',
            "title_line": '【人格】守岸人人格材料自检',
            "lines": [
                '/bot persona：作用=人格材料自检；参数=无；内容=人格强度/语气规则/边界的自检结果；意义=确认人格档案完整、语气与边界规则生效。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  运行 persona smoke：检查人格档案文件、语气规则与安全边界材料。\n'
                '  运行期人格切换用 /bot runtime persona（见「设置」模块）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。\n'
                '【示例】/bot persona'
            ),
        },
        {
            "topic": '路由',
            "admin_only": False,
            "aliases": ('路由', 'route', 'routes'),
            "index": '【路由】查看消息会走哪条路：/bot route <文本>｜/bot routes',
            "title_line": '【路由】查看文本命中的路由',
            "lines": [
                '/bot route <文本>：作用=判定一段文本会命中哪条路由；参数=文本（必填，任意文本，省略回用法）；内容=路由类型/能力/优先级/理由，自然语言意图还会给出归一化后的命令；意义=搞清“这句话为什么被当成点歌/天气/闲聊”。',
                '/bot routes：作用=查看全部路由注册表；参数=无；内容=按优先级排序的全部路由规则（kind/能力/说明）；意义=了解路由优先级全貌。',
                '权限=全员（只读诊断，不执行命令本身）。',
                '示例：/bot route 帮我解析这个 https://www.bilibili.com/video/BVxxxx',
            ],
            "detail": (
                '【板块介绍】\n'
                '  基层路由是确定性注册表：昵称命令(10)→管理员命令(11)→订阅(12)→自动发送(13)→\n'
                '  表情(20)→偷表情(22)→点歌模式(40)→点歌/历史上的今天/维基/萌百/Epic/天气/行情/吃什么/\n'
                '  好感度/占卜/快报/随机图/提醒(41)→自然语言命令(45)→二次元问句(46)→链接解析(46)→聊天(50)。\n'
                '  数字越小越先命中。\n'
                '【权限与效果】\n'
                '  权限=全员（只读，不真的执行命中命令）。\n'
                '【示例】/bot route 点歌 晴天 → 会显示 MUSIC 路由；/bot route 天气真好 → 落到 CHAT。'
            ),
        },
        {
            "topic": '历史',
            "admin_only": True,
            "aliases": ('历史', 'history', '清理历史'),
            "index": '【历史】清理会话历史：/bot history clear',
            "title_line": '【历史】清理本会话最近对话历史',
            "lines": [
                '/bot history clear：作用=清空本会话最近对话；参数=无；内容=清理的轮次数（cleared_turns）；意义=对话被带偏后一键重置上下文；只清“当前会话×当前发送者×当前实例”，不动长期记忆。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  最近对话历史是拼进 prompt 的短期上下文。清理范围精确到\n'
                '  平台×适配器×机器人×会话×发送者，别人的对话和长期记忆不受影响。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。清理失败只报类型不泄露库路径。\n'
                '【示例】/bot history clear'
            ),
        },
        {
            "topic": '暂停',
            "admin_only": True,
            "aliases": ('暂停', '暫停', 'pause', 'resume', '恢复', '继续', '繼續'),
            "index": '【暂停】软暂停/恢复：/bot pause|resume',
            "title_line": '【暂停】软暂停/恢复机器人回复',
            "lines": [
                '/bot pause：作用=软暂停回复；参数=无；内容=暂停后的运行时状态与原因；意义=维护/救火时让机器人闭嘴，不改任何配置。',
                '/bot resume：作用=恢复回复；参数=无；内容=恢复后的运行时状态；意义=解除软暂停。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  软暂停是运行时状态不是配置：不写 .env、不重启，暂停期间消息仍会接收\n'
                '  并留审计，只是不生成人格回复。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。状态记入 /bot status 的「运行时软暂停」一行。\n'
                '【示例】/bot pause → 维护 → /bot resume'
            ),
        },
        {
            "topic": '回复',
            "admin_only": True,
            "aliases": ('回复', 'reply', '详略'),
            "index": '【回复】回复详略：/bot reply <详细|精简|默认>',
            "title_line": '【回复】调整回复详略档位',
            "lines": [
                '/bot reply：作用=查看当前详略档位；参数=无；内容=当前 BOT_REPLY_DETAIL 值与用法提示；意义=确认现状再决定改不改。',
                '/bot reply <模式>：作用=设置详略档位；参数=模式（必填，详细|精简|默认；别名 科普/详尽=详细，简洁=精简，自动=默认；未知值会回用法不再静默当默认）；内容=已设为 detail/concise/auto；意义=控制回答是展开讲还是短平快，持久保存。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  回复详略影响聊天链路的输出风格：详细=先结论再展开身份/关系/关键经历\n'
                '  与资料缺口（不凑字数）；精简=短句直给；默认=按问题复杂度自动取舍。\n'
                '【取值范围】\n'
                '  仅接受上表模式词；其他输入会得到用法提示（不会被静默当成默认）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。写入运行时覆盖，持久保存，立即生效。\n'
                '  相关键：BOT_CHAT_MAX_TOKENS（输出上限）、BOT_CHAT_FAST_MODE（快速模式）。\n'
                '【示例】/bot reply 详细｜/bot reply 精简｜/bot reply 默认'
            ),
        },
        {
            "topic": '模型',
            "admin_only": True,
            "aliases": ('模型', 'model', 'llm', '渠道', '切换模型'),
            "index": '【模型】/bot model list | set | add | update | priority | effort | think | price | search | usage | health | probe | routes | vision | remove | reset',
            "title_line": '【模型】模型与供应商管理（管理员，改动即时生效）',
            "lines": [
                '/bot llm：作用=诊断当前 provider/model/key 并做一次短调用；参数=无；内容=诊断报告（会产生一次真实调用的费用）；意义=验证当前渠道真能通。',
                '/bot model list：作用=查看全部模型与顺序；参数=无；内容=各模型思考强度档位、故障转移顺序（priority 越小越先）、当前时段分组、渠道健康标注与价格；意义=选型与排障的底表。',
                '/bot model health：作用=渠道健康报告；参数=无；内容=正常/连续失败踢出/慢渠道三类清单（慢渠道按平滑延迟 EWMA 判定，踢出渠道 30 分钟半开重探自动回队）；意义=回答“为什么没用 A 渠道”。',
                '/bot model probe：作用=手动全渠道巡检；参数=无；内容=巡检受理提示（结果用 health 看）；意义=不等到后台周期主动体检，与后台巡检互斥。',
                '/bot model routes <模型名>：作用=按实测速度列渠道；参数=模型名（必填）；内容=快→慢的渠道排序（未实测排后）；意义=选最快渠道做手动 set。',
                '/bot model set <id|auto>：作用=切换当前模型；参数=id 或 auto（必填；id=已注册模型名/预设名/完整模型名，auto=回到自动选型）；内容=已手动指定 X 或已切自动；意义=手动钉死模型，失败仍自动转移。',
                '/bot model add <id> model=<模型名> base_url=<接口地址> key=<密钥> [tags=档位] [effort=档位] [group=<分组>] [priority=<n>]：作用=新增供应商；参数=id（必填，自定义名，之后 set/update/remove 用它）＋model（必填，供应商模型名原样填）＋base_url（必填，OpenAI 兼容接口，一般 /v1 结尾）＋key（必填，sk-xxx 或 env:变量名）＋其余可选（tags 逗号分隔档位、group 令牌分组、priority 整数越小越先，缺省 100）；内容=注册即生效并进路由；意义=零重启接入新渠道。',
                '/bot model update <id> <键=值...>：作用=改任意参数；参数=id（必填）＋要改的键=值（model/base_url/key/group/tags/effort/priority 任选）；内容=更新后的注册表；意义=换 key/调档位不用删了重建，可覆盖 .env 同名条目。',
                '/bot model priority <id> <n>：作用=只改故障转移顺序；参数=id（必填）＋n（必填，整数，越小越先，1..N 唯一槽位其余自动顺移）；内容=新顺序；意义=峰谷调序。',
                '/bot model effort <id> <档位>：作用=单模型思考强度覆盖；参数=id＋档位（必填，off|low|medium|high|xhigh|max|default，default=清除覆盖）；内容=确认信息；意义=给某个模型单独钉思考档。',
                '/bot model think <档位>：作用=全局思考强度；参数=档位（必填，off|low|medium|high|xhigh|max|留空；留空=清空回家族基线）；内容=确认信息；意义=一刀切控制 reasoning_effort 开销（复杂任务仍会在家族最高档内临时升档）。',
                '/bot model price <模型名> [input=<元/1M> output=<元/1M> cache_read=<元/1M> cache_creation=<元/1M> per_call=<元/请求>]：作用=维护价格表；参数=模型名（必填）＋价键（不带即清除该模型价格，数字≥0；cache_read/cache_creation=缓存读/缓存创建单价，per_call=按次计费渠道的元/请求）；内容=新价格确认；意义=账单计费依据，按调用时刻价格记账。',
                '/bot model usage [today|YYYY-MM-DD]：作用=每日用量账单；参数=日期（可选，today/今天 或 YYYY-MM-DD，省略=今天）；内容=输入/输出/缓存命中（含占输入比例）/缓存创建 Token、调用次数、按模型分组（含逐模型缓存读与缓存建）的费用；意义=看清钱花在哪、缓存有没有起作用。',
                '/bot model search <on|off>：作用=热切换联网搜索；参数=on|off（必填）；内容=开/关确认；意义=不用重启控制 web_search。',
                '/bot model vision list|add|update|priority|remove：作用=图片识别模型（VLM）注册表管理；参数=子命令＋各自参数（add 同 /bot model add：id/model/base_url/key/[priority]；update/remove 用同一 id；priority <id> <槽位> 调识别顺序）；内容=识别候选清单、优先级与开关状态，或写回确认；意义=给「图转文字」这条支路选型与排序，多候选按优先级轮询、单路失败自动降级到下一路。',
                '/bot model vision mode <relay|direct>：作用=切换图片进入对话的方式；参数=relay|direct（省略=只查询当前模式；relay=先由识别模型把图转成文字描述，再作为不可信上下文并给主模型；direct=图片直传给支持视觉的主模型、不再过识别模型）；内容=当前视觉模式；意义=主模型不带视觉（或想省一跳）时走 relay，能直传时细节不丢。',
                '/bot model remove <id>：作用=删除自定义模型；参数=id（必填；.env 来源条目不可删只能 update 覆盖）；内容=删除确认；意义=清理废弃渠道。',
                '/bot model reset：作用=清除手动指定；参数=无；内容=回到自动选型确认；意义=撤销 set。',
                '思考强度档位：DeepSeek/GLM/Kimi/MiniMax=low,high,max｜GPT/Grok=low,medium,high,xhigh｜Gemini=low,medium,high；默认=家族基线档，复杂任务自动升家族最高档。',
                '示例：/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1',
                '注意：key 不回显；等号两边不要加空格；新增/修改/价格/分组全部热更立即生效，重启保留。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  模型注册表＋故障转移＋渠道健康＋思考强度＋计费的总控台。\n'
                '  /bot model 与 /bot runtime model 等价。改动即时生效、无需重启；\n'
                '  运行时覆盖优先于 .env。\n'
                '【取值范围】\n'
                '  档位：DeepSeek/GLM/Kimi/MiniMax=low,high,max｜GPT/Grok=low,medium,high,xhigh｜Gemini=low,medium,high。\n'
                '  时段分组：/bot runtime set BOT_MODEL_PRIORITY_GROUPS <JSON 数组>，每组\n'
                '  {"name":"工作日高峰","days":[1..7],"windows":[["09:00","12:00"]],"order":[模型id...]}；\n'
                '  days 缺省=每天，windows 缺省=全天，都缺省=兜底组；按列表顺序取第一个命中组。\n'
                '  分时段切换：/bot runtime set BOT_MODEL_SCHEDULE {"23:00-07:00":"luna"}（支持跨零点）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。全部子命令热更立即生效、持久保存；key 永不回显；\n'
                '  不要在群聊发送真实 Key，用 key=env:变量名。\n'
                '【示例】/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1'
            ),
        },
        {
            "topic": '用量',
            "admin_only": True,
            "aliases": ('用量', 'usage', '账单', '花费', '监控'),
            "index": '【用量】Token 统计、费用记账与监控提醒：/bot model usage | /bot model price',
            "title_line": '【用量】Token 统计、费用记账与监控提醒',
            "lines": [
                '/bot model usage [today|YYYY-MM-DD]：作用=每日用量账单；参数=日期（可选，省略=今天）；内容=输入/缓存命中（含占输入比例）/缓存创建/输出 Token、调用次数、按模型分组费用与逐模型缓存读建、未计价次数；意义=每天钱花在哪、缓存有没有起作用一目了然。',
                '/bot model price <模型名> [input=<元/1M> output=<元/1M> cache_read=<元/1M> cache_creation=<元/1M> per_call=<元/请求>]：作用=维护价格表；参数=模型名（必填）＋价键（数字≥0；不带价格=清除；cache_read/cache_creation=缓存单价，per_call=按次计费）；内容=确认信息；意义=账单计费依据。',
                '实时提醒：单模型当日输出>500万或输入>5000万 token、当日账单>10元 → 自动推送管理员（阈值可在 .env 调）。',
                '定时报告：北京时间 13:00/18:00/23:00 推送自上个报告点至今的金额与 Token；13:00 附过去 24 小时总花费。',
                '口径：费用按每次调用时刻的价格记账，调价不影响历史账单；未配价格的模型不计费并在账单标注。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  用量监控三件套：账单查询（usage）、价格维护（price）、主动提醒\n'
                '  （实时阈值＋定时报告）。提醒与报告推给全部管理员（QQ 私聊，统一预警\n'
                '  管线），渲染可用时附 Mica 账单卡，失败回退纯文本。\n'
                '【取值范围】\n'
                '  阈值 .env 键：BOT_USAGE_ALERT_OUTPUT_TOKENS（默认 5,000,000）、\n'
                '  BOT_USAGE_ALERT_INPUT_TOKENS（默认 50,000,000）、BOT_USAGE_ALERT_DAILY_COST_YUAN（默认 10）。\n'
                '  报告时间：BOT_USAGE_REPORT_HOURS（逗号分隔整点，默认 13,18,23）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。每项实时提醒每天最多触发一次；报告时间点持久化，重启不丢。\n'
                '【示例】/bot model usage 2026-09-01'
            ),
        },
        {
            "topic": '设置',
            "admin_only": True,
            "aliases": ('设置', 'runtime', '参数', '設置', '參數', '运行时'),
            "index": '【设置】运行时参数：/bot runtime set|get|list|reset|nickname|persona|instance',
            "title_line": '【设置】运行时参数管理（管理员）',
            "lines": [
                '/bot runtime set <KEY> <VALUE>：作用=热改一个参数；参数=KEY（必填，可写键见 get 列表）＋VALUE（必填，按键校验），或加 --instance <名称>（可选，定位实例）；内容=已设置 KEY = 值（已持久化）；意义=不改 .env 立即生效，重启保留。',
                '/bot runtime get <KEY>：作用=读参数实际生效值；参数=KEY（必填）；内容=值＋（覆盖值）/（.env 默认值）来源标注；意义=确认运行时覆盖与 .env 谁在生效。',
                '/bot runtime list：作用=列出全部覆盖项；参数=无；内容=KEY=VALUE 清单；意义=盘点改过哪些。',
                '/bot runtime reset [KEY]：作用=恢复默认；参数=KEY（可选，省略=清空全部覆盖）；内容=清除项数；意义=撤销热改。',
                '/bot runtime persona <action>：作用=人格运行期管理；参数=action（list｜switch <id|default>｜probability <id> <0-1>）；内容=人格清单/切换确认/触发概率确认；意义=不重启换人格。',
                '/bot runtime nickname add|remove|list [昵称]：作用=角色昵称管理；参数=action（必填）＋昵称（add/remove 必填）；内容=昵称表；意义=控制哪些称呼能触发昵称命令。',
                '/bot runtime model <子命令>：作用=模型管理（=/bot model）；参数=见「模型」模块；内容=同 /bot model；意义=同义入口。',
                '/bot runtime instance list：作用=列出实例设置；参数=无；内容=已有实例名单；意义=多实例部署核对。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  运行时参数层：SETTABLE_KEYS 白名单内的键可热改并持久化（运行时覆盖\n'
                '  优先于 .env）；不在白名单的键（如五个持久化开关）只能改 .env 重启。\n'
                '  所有子命令都可加 --instance <名称> 操作指定实例。\n'
                '【常用可写键举例】\n'
                '  BOT_MODEL_SCHEDULE（分时段切换，JSON）、BOT_MODEL_PRIORITY_GROUPS（峰谷分组，JSON 数组）、\n'
                '  BOT_MODEL_PRICES（价格表 JSON）、BOT_CHAT_REASONING_EFFORT（off|low|medium|high|xhigh|max|留空）、\n'
                '  BOT_REPLY_DETAIL、BOT_CHAT_MAX_TOKENS、BOT_CHAT_FAST_MODE、BOT_VISION_ENABLED、\n'
                '  BOT_QUIET_HOURS_*（6 键）、BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR 等（完整清单：/bot runtime get 随便发一个错键）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。写入即持久化并通知热更；个别装配期读取的键（如\n'
                '  BOT_GROUP_CHAT_AUTO_REPLY_ENABLED）需重启，帮助各模块会单独标注。\n'
                '【示例】/bot runtime set BOT_QUIET_HOURS_ENABLED true'
            ),
        },
        {
            "topic": '搜索',
            "admin_only": True,
            "aliases": ('搜索', 'search'),
            "index": '【搜索】验证联网检索：/bot search <问题>',
            "title_line": '【搜索】管理员验证联网检索',
            "lines": [
                '/bot search <问题>：作用=验证联网检索链路；参数=问题（必填，省略回用法）；内容=至多 BOT_WEB_SEARCH_MAX_RESULTS 条检索结果（标题/摘要/链接，缺省上限 20）或失败原因；意义=区分“模型不知道”和“搜索没通”。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  直接调用检索供应商（Tavily 主链＋fallback）做一次真实搜索，\n'
                '  不走人格链路，用于验证搜索配置。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。检索源不可达/被反爬/代理未生效时给出降级说明。\n'
                '【示例】/bot search 守岸人是什么游戏的角色'
            ),
        },
        {
            "topic": '解析',
            "admin_only": True,
            "aliases": ('解析', 'parse'),
            "index": '【解析】解析历史：/bot parse [数量]',
            "title_line": '【解析】查看最近解析历史',
            "lines": [
                '/bot parse [数量]：作用=查看最近链接解析历史；参数=数量（可选，1-100，默认 10）；内容=跨会话的 URL＋标题＋时间清单（全局范围）；意义=排查“刚才那条链接解析出了什么”。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  解析历史是全局范围（跨群/跨私聊），因此收紧为管理员可见。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（M24 收紧：链接自带 token 时等于二次扩散，不对普通成员开放）。\n'
                '【示例】/bot parse 20'
            ),
        },
        {
            "topic": '凭据',
            "admin_only": True,
            "aliases": ('凭据', '凭证', '憑據', '憑證', '登录凭证', '登錄憑證', 'alert', 'cookie'),
            "index": '【凭据】凭据健康与 cookie 导入：/bot alert check｜/bot cookie status|import|login|check|expiry',
            "title_line": '【凭据】检查 cookie/凭据健康',
            "lines": [
                '/bot alert check：作用=凭据体检；参数=无；--probe（可选开关，追加在线探测，401/403=需重登）；内容=各凭据引用的状态清单；意义=解析突然 403 时的第一排查。',
                '/bot cookie status：作用=看各平台已录 cookie；参数=无；内容=平台×cookie 名×到期日（永不回显值）；意义=核对导入是否生效。',
                '/bot cookie import <平台> <Cookie头>：作用=热写入平台 cookie；参数=平台（必填，小写平台名，在收录名单内选 1，名单以 /bot cookie status 输出为准）＋Cookie头（必填，浏览器复制的 名=值; … 整行原文粘贴）；内容=accepted/normalized/skipped 三项统计与导入结果；意义=同名不覆盖、下一次解析即生效无需重启。',
                '/bot cookie login <平台>：作用=扫码登录；参数=平台（必填，当前仅 bilibili 支持扫码）；内容=二维码图＋登录指引；意义=免手动导 cookie。',
                '/bot cookie check <平台>：作用=查扫码结果；参数=平台（必填）；内容=最近一次扫码登录状态；意义=扫码后确认。',
                '/bot cookie expiry：作用=全平台过期报告；参数=无；内容=各平台凭证有效期报告；意义=批量核对到期情况。',
                '平台（18）：bilibili/xiaohongshu/douyin/qqmusic/netease/kuwo/kugou/twitter/youtube/kurobbs/weibo/kuaishou/acfun/moegirl/xiaoheihe/skland/miyoushe/zhihu',
                '权限=仅管理员；每天 10:00 自动巡检一次并向在线管理员推送过期预警。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  平台 cookie 是解析/下载/订阅的登录态。统一存在 cookies.txt，\n'
                '  值永不回显；每天 10:00 定时巡检（bot_cookie_expiry_reminder_enabled\n'
                '  可关），过期会私聊推送第一位在线管理员。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（命令匹配层就拦，非管理员无感）。\n'
                '【示例】/bot cookie import bilibili SESSDATA=...; bili_jct=...'
            ),
        },
        {
            "topic": '群策略',
            "admin_only": True,
            "aliases": ('群策略', 'group', '群'),
            "index": '【群策略】群回复策略档位：/bot group list|add|del|set|clear',
            "title_line": '【群策略】群聊回复策略档位（管理员）',
            "lines": [
                '/bot group [list]：作用=查看各档位群名单；参数=无或 list；内容=黑1/黑2/白1/白2 四档的群号清单；意义=盘点现状。',
                '/bot group add <档位> <群号...>：作用=把群加入档位；参数=档位（必填，black1|black2|white1|white2，可用 黑1/黑2/白1/白2）＋群号（必填，数字，可多个）；内容=更新后的名单；意义=批量拉黑/拉白。',
                '/bot group del <档位> <群号...>：作用=移出档位；参数=同 add；内容=更新后的名单；意义=解除。',
                '/bot group set <档位> <群号...>：作用=覆盖档位名单；参数=同 add；内容=更新后的名单；意义=整表重置。',
                '/bot group clear <档位>：作用=清空档位；参数=档位（必填）；内容=空名单确认；意义=一键清空。',
                '动作词可用中文别名：加/加入=add，删/移除/remove=del，设/设置=set，清/清空/reset=clear，查/查看=list。',
                '群号必须纯数字，可一次给多个；档位写错会提示四档取值。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  四档群聊策略：black1=完全静默只收不发；black2=只回“@且带指令”；\n'
                '  white1=正常回复并可参与主动接话；white2=只回“@或显式命令”。\n'
                '  不在任何名单=默认档（正常回复）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。写入运行时覆盖（BOT_GROUP_BLACK1/BLACK2/WHITE1/WHITE2），\n'
                '  热改立即生效。\n'
                '【示例】/bot group add white1 123456789 987654321'
            ),
        },
        {
            "topic": '群文件',
            "admin_only": True,
            "aliases": ('群文件', '群文件统计'),
            "index": '【群文件】群上传统计：/bot 群文件（仅群聊）',
            "title_line": '【群文件】群上传记录与整理建议（管理员）',
            "lines": [
                '/bot 群文件：作用=看本群文件上传统计；参数=无（仅群聊可用，统计当前群）；内容=最近上传清单＋扩展名分布（文档/压缩包/图片/视频/音频/其他）＋整理建议；意义=群盘整理前的摸底。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  群文件上传事件（OneBot group_upload）实时入 SQLite，按群/文件名/大小/\n'
                '  时间/上传者记录。OneBot 不提供移动文件夹 API，所以“整理”落地为\n'
                '  记录＋统计＋提醒，不假装能移动文件。\n'
                '【权限与效果】\n'
                '  权限=仅管理员；仅群聊可用（私聊提示不可用）。\n'
                '【示例】/bot 群文件'
            ),
        },
        {
            "topic": '日志',
            "admin_only": True,
            "aliases": ('日志', 'logs'),
            "index": '【日志】运行时日志：/bot logs [级别] [数量]',
            "title_line": '【日志】查看运行时事件日志',
            "lines": [
                '/bot logs [级别] [数量]：作用=查看运行时事件日志；参数=级别（可选，debug|info|warning|error，默认 info）＋数量（可选，1-200 整数，默认 50），两个参数按「先级别后数量」顺序写；内容=最近 N 条对应级别以上的日志；意义=看运行时到底发生了什么。',
                '权限=仅管理员（别名「日志」经昵称命令层同样需要 /bot 形式执行）。',
                '示例：/bot logs error 20',
            ],
            "detail": (
                '【板块介绍】\n'
                '  运行时事件日志（runtime_event_log）的查询口：统一记录各能力的关键\n'
                '  事件（WARNING/ERROR 等），按级别过滤、按条数截取。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。日志未启用时提示运行时事件日志未启用。\n'
                '【示例】/bot logs error 20'
            ),
        },
        {
            "topic": '文件',
            "admin_only": True,
            "aliases": ('文件', '文件导出', '导出'),
            "index": '【文件】生成文档并上传：文件 <md|markdown|docx|pptx|xlsx|pdf> <主题>',
            "title_line": '【文件】主题生成文档并群文件上传（管理员）',
            "lines": [
                '文件 <格式> <主题>：作用=围绕主题生成文档并以群文件形式上传；参数=格式（必填，md|markdown|docx|pptx|xlsx|pdf，大小写不敏感）＋主题（必填，非空文本，作为文档标题与大纲素材）；内容=已生成并上传 <格式>：文件名（KB）或失败原因；意义=长文/表格/幻灯一键落盘成文件，不刷屏。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  LLM 按文档撰写提示词生成结构化 Markdown（分级标题/列表/表格，\n'
                '  600-1200 字），再本地转换成目标格式，经平台上传接口发出。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（命令匹配层拦截）。生成与转换在后台线程执行（数十秒级），\n'
                '  产出落 data/downloads/export/ 后上传；LLM 失败只报错误类型。\n'
                '【示例】文件 docx 鸣潮 2.0 版本角色梯度整理'
            ),
        },
        {
            "topic": '身份',
            "admin_only": True,
            "aliases": ('身份', 'identity', '会话身份'),
            "index": '【身份】会话身份记忆：/bot identity show|set|tag|clear｜自助称谓偏好：set-name|set-gender|unset-name|unset-gender｜自助关系档：set-relation|unset-relation|show-relation',
            "title_line": '【身份】会话级身份记忆（管理员）＋用户自助称谓偏好',
            "lines": [
                '/bot identity show：作用=查看本会话身份；参数=无；内容=称呼/标签/设置人/更新时间（未设置会明说）；意义=核对当前会话的身份设定。',
                '/bot identity set <昵称>：作用=设定本会话称呼；参数=昵称（必填，非空文本，如 set 岸宝）；内容=已设定称呼确认；意义=让机器人在这群/这个私聊里只这么叫你。',
                '/bot identity tag <标签1,标签2>：作用=设定标签；参数=标签串（必填，逗号分隔，最多保留 8 个）；内容=已设定标签确认；意义=给语气调整提供更多线索。',
                '/bot identity clear：作用=清除本会话身份；参数=无；内容=已清除/本就没有；意义=恢复默认。',
                '权限=仅管理员；在哪个群/私聊执行就对哪个会话生效，各会话互不影响；只影响称呼与语气，人格不变（渲染层内建防 OOC 护栏）。',
                '/bot identity set-name <称呼>：作用=设置机器人对你的称谓偏好；参数=称呼（必填，非空，≤32 字）；内容=已记下确认；意义=无需管理员，你自己决定机器人怎么叫你（群里按「这个群+你」生效，私聊按你生效）。',
                '/bot identity set-gender <male|female|nonbinary|custom|unknown>：作用=登记你的性别自述；参数=五个值之一（大小写不敏感）；内容=已记下确认；意义=让语气分寸更合适；非法值不记录并列出可接受值。',
                '/bot identity unset-name：作用=清除称谓偏好；参数=无；内容=已清除/本就没有；意义=恢复自动称呼。',
                '/bot identity unset-gender：作用=清除性别自述；参数=无；内容=已清除/本就没有；意义=恢复 unknown。',
                '自助子命令权限=所有用户（只能操作自己的偏好，无他人参数）；unset-name/unset-gender 为整条记录清除（称谓与性别自述一并移除），unset-relation 只清关系档那一列；称谓偏好与上方管理员会话身份是两套数据，自助偏好优先级更高；关系档的开关语义与词表口径见「亲密模式」模块（/bot help 亲密模式）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  给单个会话（群或私聊）设置独立的身份记忆：机器人怎么称呼你、带哪些\n'
                '  标签。在哪个会话执行就只对那个会话生效。数据存\n'
                '  data/session_identity.sqlite3（.env 可用 BOT_SESSION_IDENTITY_DB_PATH 改路径）。\n'
                '  另有无需管理员的用户自助称谓偏好（set-name/set-gender/unset-name/\n'
                '  unset-gender）：存 data/addressing_preferences.sqlite3，聊天人格上下文\n'
                '  会优先采用你显式声明的称谓与性别。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。只调整该会话内的称呼与语气，不改变守岸人核心人格；\n'
                '  防止会话身份被用来推翻人格设定（防 OOC 护栏内建于渲染层）。\n'
                '  例外：set-name/set-gender/unset-name/unset-gender 四个自助子命令\n'
                '  所有用户可用，且只能操作自己的偏好。\n'
                '【示例】/bot identity set 岸宝｜/bot identity tag 早起,秃头,干饭人｜/bot identity set-name 岸友')
        },
        {
            "topic": '怪癖',
            "admin_only": True,
            "aliases": ('怪癖', 'quirk', '人格怪癖'),
            "index": '【怪癖】人格怪癖审核：/bot quirk list|approve|retire|add',
            "title_line": '【怪癖】人格怪癖演化区（管理员，审核制）',
            "lines": [
                '/bot quirk list [pending|active|retired]：作用=列出怪癖；参数=状态过滤（可选，pending=待审|active=生效|retired=退役，省略=全部，最多 20 条）；内容=id 前 8 位＋状态＋文本＋来源＋范围（global=全员渲染，user:名字=仅该用户）；意义=先拿 id 再审核，范围标注是审核依据之一。',
                '/bot quirk approve <id前缀>：作用=待审转生效；参数=id 前缀（必填，需唯一命中，0 条或多条都拒绝）；内容=已通过＋文本；意义=审核制放行，approve 前对回复零影响。',
                '/bot quirk retire <id前缀>：作用=退役生效项；参数=id 前缀（必填，唯一命中）；内容=已退役＋文本；意义=不再渲染但保留记录。',
                '/bot quirk add <习惯描述>：作用=管理员直添；参数=习惯描述（必填）；内容=已直接生效；意义=跳过审核立即影响 prompt。',
                '审核制红线：自动来源（反思回路等 propose）只进待审（pending_review），绝不直接影响 prompt；BOT_QUIRKS_ENABLED=false 时整个演化区停用。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  L4 人格演化区：一小批可选的说话习惯/怪癖，生效后由人格装配渲染进\n'
                '  上下文。审核制红线：自动来源只进待审队列；管理员 add 直添是唯一\n'
                '  免审通道。数据存 data/persona_quirks.sqlite3。\n'
                '【取值范围】\n'
                '  状态只有三种：待审 pending(pending_review)/生效 active/退役 retired；\n'
                '  前缀必须唯一命中；BOT_QUIRKS_ENABLED=false 时命令只返回停用提示。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。approve 后的 active 项渲染进人格上下文；待审项在\n'
                '  approve 前对回复没有任何影响。\n'
                '【示例】/bot quirk list pending → /bot quirk approve 3fa2'
            ),
        },
        {
            "topic": '限流',
            "admin_only": True,
            "aliases": ('限流', '句数帽', '安静时间', '情绪豁免', '自动接话'),
            "index": '【限流】群句数帽/情绪豁免/安静时间/自动接话：BOT_RATE_LIMIT_*、BOT_QUIET_HOURS_*',
            "title_line": '【限流】群聊句数帽、情绪豁免、安静时间与自动接话（管理员）',
            "lines": [
                'BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR：作用=每小时群聊句数帽；参数=≥0 整数（默认 0=该帽不生效）；内容=超帽后普通回复被静默拦截；意义=防刷屏。',
                'BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE：作用=每分钟群聊句数帽；参数=≥0 整数（默认 0=该帽不生效）；内容=超帽即拦，管住脉冲连发；意义=小时帽的补充。',
                'BOT_RATE_LIMIT_EMOTION_EXEMPT：作用=情绪豁免；参数=true/false（默认 true）；内容=安抚类回复不被句数帽拦截；意义=该安慰的时候不被限流卡住。',
                'BOT_GROUP_CHAT_AUTO_REPLY_ENABLED：作用=自动接话总开关；参数=true/false（默认 false）；内容=开启后未点名群消息按概率抽签接话，点名/命令不受影响；意义=群活跃度调节。',
                'BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY：作用=接话概率；参数=0..1（默认 0.004，与心情系数相乘后封顶 1.0）；内容=每次抽签现算，低落时少插话、兴奋时更活跃；意义=心情联动的活跃度旋钮。',
                'BOT_QUIET_HOURS_*：作用=安静时间窗；参数=BOT_QUIET_HOURS_ENABLED（true/false）/BOT_QUIET_HOURS_START·END（HH:MM，支持跨零点，默认 00:00-06:00）/BOT_QUIET_HOURS_TIMEZONE（IANA 名）/BOT_QUIET_HOURS_SESSION_TYPES（group|private|email 逗号分隔，默认 group）/BOT_QUIET_HOURS_BYPASS_ROLES（默认 admin）；内容=窗口内只拦截未点名的普通聊天/解析；意义=定时闭嘴。',
                '修改方式：以上全部支持 /bot runtime set 热改，立即生效（接话总开关 ENABLED 装配期读取，改后需重启）。',
                '示例：/bot runtime set BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR 60',
                '安静时间 6 键：作用=安静时间窗；参数=ENABLED（true/false）、START/END（HH:MM，支持跨零点，默认 00:00-06:00）、TIMEZONE（IANA 名）、SESSION_TYPES（group|private|email 逗号分隔，默认 group）、BYPASS_ROLES（默认 admin）；内容=窗口内只拦未点名普通聊天/解析；意义=作息。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  控制机器人在群里的回复频率与时机：句数帽封顶、情绪豁免保安抚、\n'
                '  安静时间定时闭嘴、自动接话按概率抽签。全部经 /bot runtime set 修改。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。热改立即生效；点名/显式命令永远不受安静时间与概率影响；\n'
                '  自动接话用确定性哈希抽签，同一消息结果稳定。\n'
                '【示例】/bot runtime set BOT_QUIET_HOURS_START 01:00'
            ),
        },
        {
            "topic": '合并转发',
            "admin_only": True,
            "aliases": ('合并转发', '转发合并'),
            "index": '【合并转发】长回复合并阈值：/bot runtime set BOT_RENDER_FORWARD_*',
            "title_line": '【合并转发】长回复合并为转发消息的阈值（管理员）',
            "lines": [
                'BOT_RENDER_FORWARD_MIN_NODES：作用=按条数触发合并；参数=≥0 整数，默认 4（0=不按条数只看字数）；内容=切分后达到该条数即合并成 QQ 合并转发；意义=超过 3 条就打包。',
                'BOT_RENDER_FORWARD_MIN_CHARS：作用=按字数触发合并；参数=≥0 整数，默认 1500；内容=达到字数也触发；意义=长文兜底。',
                'BOT_RENDER_FORWARD_MAX_NODES：作用=节点数上限；参数=≥0 整数，默认 0=不限制；内容=切分块数尽量压到该上限（硬长度边界优先）；意义=防刷屏。',
                'BOT_RENDER_FORWARD_NODE_CHARS：作用=单节点目标字数；参数=≥200 整数，默认 900；内容=每个转发节点的目标字数；意义=控制单条体积。',
                '四键（BOT_RENDER_FORWARD_MIN_NODES/MIN_CHARS/MAX_NODES/NODE_CHARS）是 .env+重启键：装配期烘进策略快照（settings.py:355-364 列在需重启名单），/bot runtime set 会拒绝并提示重启。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  长回复按字数/条数切成多个节点并合并成一条 QQ 合并转发消息，\n'
                '  四个键分别控制条数触发、字数触发、节点上限与单节点字数。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。条数达 MIN_NODES 或字数达 MIN_CHARS 即合并；\n'
                '  消费点在装配期读取，改动需重启生效。\n'
                '【示例】/bot runtime set BOT_RENDER_FORWARD_MIN_NODES 3'
            ),
        },
        {
            "topic": '群摘要',
            "admin_only": True,
            "aliases": ('群摘要', '群聊摘要', '群概要'),
            "index": '【群摘要】群聊摘要与名单：BOT_SHARED_GROUP_CONTEXT_ENABLED、BOT_GROUP_DIGEST_*、每日通讯总结推送',
            "title_line": '【群摘要】群聊上下文摘要、群名单与每日通讯总结推送（管理员）',
            "lines": [
                'BOT_SHARED_GROUP_CONTEXT_ENABLED：作用=群摘要总开关；参数=true/false（默认 false）；内容=开启才把群内近期对话浓缩成摘要供人格参考，关闭则完全不生成；意义=群上下文感知的前提。',
                'BOT_GROUP_DIGEST_LIST_MODE：作用=名单模式；参数=whitelist|blacklist|off|all（默认空=不过滤）；内容=whitelist 仅名单内群参与摘要/blacklist 排除名单内群；意义=控制哪些群参与。',
                'BOT_GROUP_DIGEST_WHITELIST / BOT_GROUP_DIGEST_BLACKLIST：作用=摘要白/黑名单；参数=数字群号列表（逗号/分号/顿号/空白分隔或 JSON 数组，自动去重，非数字拒绝）；内容=名单生效，精确圈定参与群；意义=该收的收、该避的避。',
                'BOT_GROUP_DIGEST_PUSH_ENABLED：作用=每日通讯总结推送开关；参数=true/false（.env 键，默认 true，不进 runtime set 白名单）；内容=开/关每日定时推送；意义=夜间日报总闸。',
                'BOT_GROUP_DIGEST_PUSH_TIME：作用=推送时刻；参数=HH:MM（时 0-23 分 0-59，默认 21:30，非法值启动即报错）；内容=每天这个时刻把当日群摘要推给白名单群各一遍（list_mode 非 whitelist 时零推送，绝不猜群）；意义=错峰推送。',
                'BOT_GROUP_DIGEST_MAX_TURNS：作用=摘要收录轮数上限；参数=正整数（默认 150）；内容=摘要最多回看最近 150 轮对话；意义=控制上下文窗口。',
                'BOT_GROUP_DIGEST_MAX_CHARS：作用=摘要字数预算；参数=≥100 整数（默认 800）；内容=摘要文本按字数预算截取；意义=控制注入长度。',
                'BOT_GROUP_DIGEST_LLM_ENABLED：作用=LLM 润色摘要；参数=true/false（默认 false）；内容=开启后用 LLM 把对话浓缩成更顺的摘要（结果缓存 1 小时）；意义=默认关闭零额外开销。',
                '示例：/bot runtime set BOT_GROUP_DIGEST_LIST_MODE whitelist → /bot runtime set BOT_GROUP_DIGEST_WHITELIST 1108838060,1076073471',
                'BOT_GROUP_DIGEST_WHITELIST/BLACKLIST：作用=名单；参数=群号列表（多分隔符/JSON，去重）；内容=名单；意义=白/黑名单内容。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  群聊上下文摘要（shared_group）：把群内近期对话浓缩成摘要供人格参考；\n'
                '  名单模式决定哪些群参与；每日通讯总结推送（G-DIGEST）在每天固定时刻\n'
                '  把当日摘要主动推回白名单群。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。总开关/名单/模式可 runtime set 热改；推送两键为 .env 键，\n'
                '  改后重启生效。推送正文=一句守岸人引子＋当日摘要；同群同天不重发。\n'
                '【示例】/bot runtime set BOT_GROUP_DIGEST_LIST_MODE whitelist'
            ),
        },
        {
            "topic": '视频理解',
            "admin_only": True,
            "aliases": ('视频理解', '识图', 'vision', '视频'),
            "index": '【视频理解】识图与视频理解开关：BOT_VISION_ENABLED、BOT_VIDEO_UNDERSTANDING_ENABLED',
            "title_line": '【视频理解】图片/表情包识别与视频理解（管理员）',
            "lines": [
                'BOT_VISION_ENABLED：作用=识图总闸；参数=true/false（默认 false）；内容=开启且注册表有可用模型才调用视觉模型；意义=群里发图能被看懂的前提。',
                'BOT_VISION_MODE：作用=识别管线选择；参数=relay|direct（默认 direct）；内容=relay=视觉模型转文字，direct=图片直传主模型；意义=质量与成本取舍。',
                'BOT_VISION_REPLY_PROBABILITY：作用=识图回应概率；参数=0..1（默认 1.0，0=仅 @ 时看图）；内容=识别触发频率；意义=控制打扰与开销。',
                'BOT_VIDEO_UNDERSTANDING_ENABLED：作用=视频理解总闸；参数=true/false（默认 false）；内容=开启后视频抽帧＋音轨/字幕生成感知简报，支持追问与深挖，关闭走旧抽帧摘要零额外开销；意义=视频消息的深度理解。',
                '识别模型管理：/bot model vision list|add|update|priority|remove（详见 /bot help 模型）。',
                'BOT_VIDEO_MAX_FRAMES：作用=抽帧数；参数=正整数（默认 6，0 视同 1）；内容=分析密度；意义=成本。',
                'BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE：作用=有 CC 字幕时跳过音轨转写；参数=true/false（默认 true）；内容=管线加速；意义=省时省钱。',
                'BOT_VIDEO_FUZZY_FOLLOWUP：作用=模糊追问（“刚才那个讲了什么”）；参数=true/false（默认 true）；内容=追问能力；意义=体验。',
                'BOT_VIDEO_DEEP_ENABLED：作用=深挖重分析（“再仔细看看”）；参数=true/false（默认 true）；内容=更多帧＋强制 ASR；意义=深读，耗时更长。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  识图（vision）：群图片/表情包内容识别；视频理解：视频抽帧＋音轨/字幕\n'
                '  生成感知简报，支持后续追问。两者各有总开关与模型注册表。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。全部可 /bot runtime set 热改；进度提示（“视频我看一下，\n'
                '  稍等…”）默认开，同会话 60 秒节流（BOT_VIDEO_PROGRESS_ACK_ENABLED）。\n'
                '【示例】/bot runtime set BOT_VISION_MODE relay'
            ),
        },
        {
            "topic": '运行开关',
            "admin_only": True,
            "aliases": ('运行开关', '诊断开关', '持久化开关'),
            "index": '【运行开关】发送队列/审计/回执/诊断持久化：BOT_SEND_QUEUE_ENABLED 等 5 键',
            "title_line": '【运行开关】发送队列、审计、回执、诊断持久化开关（管理员）',
            "lines": [
                'BOT_SEND_QUEUE_ENABLED：作用=发送队列持久化；参数=true/false，默认 false；内容=队列落 sqlite 重启不丢；意义=可靠投递的基础。',
                'BOT_SEND_QUEUE_WORKER_ENABLED：作用=队列后台投递线程；参数=true/false，默认 false；内容=后台按批投递待发消息；意义=不依赖事件触发投递。',
                'BOT_AUDIT_ENABLED：作用=审计落库；参数=true/false，默认 false；内容=/bot audit 可跨重启查询；意义=合规。',
                'BOT_RECEIPTS_ENABLED：作用=回执落库；参数=true/false，默认 false；内容=/bot receipt 跨重启可查；意义=投递追踪。',
                'BOT_DIAGNOSTICS_ENABLED：作用=运行诊断落库；参数=true/false，默认 false；内容=/bot recent 汇总有料；意义=排障。',
                '说明：5 键均为 .env 配置（不在 /bot runtime set 可写集合），改后重启生效。',
                '五键均为 true/false 布尔 .env 键；落库路径由对应 BOT_*_DB_PATH 配置',
                '（留空=内存态）。队列参数另有 BOT_SEND_QUEUE_MAX_ITEMS/MAX_ATTEMPTS/RETRY_* 等键。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  五个持久化开关：发送队列、队列后台 worker、审计记录、发送回执、\n'
                '  运行诊断。全部默认关闭；关闭时对应记录仅内存态，重启不保留。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。开启后 /bot status 会显示各开关与 store=sqlite/memory 状态。\n'
                '【示例】.env 里 BOT_AUDIT_ENABLED=true 后重启。'
            ),
        },
        {
            "topic": '邮件',
            "admin_only": True,
            "aliases": ('邮件', '电子邮件', 'mail', 'email', '邮箱'),
            "index": '【邮件】Gmail/QQ 收发与发件账户控制（Telegram 管理端）：/mail status|accounts|use|send|pause|resume',
            "title_line": '【邮件】Gmail/QQ IMAP/SMTP 收发与 Telegram 控制',
            "lines": [
                '/mail status：作用=看邮件桥接状态；参数=无；内容=桥接开关、已连接账户、当前发件账户；意义=邮件链路总览。',
                '/mail accounts：作用=列可用账户；参数=无；内容=认证账户与发件别名；意义=选发件身份前先看有什么。',
                '/mail use <发件邮箱>：作用=设默认发件身份；参数=发件邮箱（必填，完整地址且必须已连接或已映射）；内容=切换确认；意义=后续 send 不用每次 --from。',
                '/mail send <收件邮箱> | <主题> | <正文>：作用=发信；参数=收件邮箱（必填，完整地址）＋主题（必填非空）＋正文（必填非空），用 | 分隔三段；内容=发送结果；意义=快速发邮件。',
                '/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>：作用=临时指定发件身份发信；参数=四段（缺一不可）；内容=发送结果；意义=一次借用别的身份。',
                '/mail pause：作用=暂停邮件 AI 自动回复；参数=无；内容=暂停确认（收件提醒继续）；意义=只收不回。',
                '/mail resume：作用=恢复自动回复；参数=无；内容=恢复确认；意义=恢复。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  邮件桥把 Gmail/QQ 邮箱（IMAP/SMTP）接进统一运行时：新邮件提醒、\n'
                '  AI 自动回复、人工发信。控制面在 Telegram 管理端，QQ 侧不受理。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（Telegram 管理端：BOT_TELEGRAM_ADMIN_USER_IDS/CHAT_IDS），\n'
                '  且只能从 Telegram 适配器发送；非管理端执行会收到“仅允许从 Telegram\n'
                '  管理端执行”提示。SMTP/适配器错误只回报类型不回显细节。\n'
                '【示例】/mail send someone@example.com | 测试 | 这是一封测试邮件'
            ),
        },
        {
            "topic": 'Telegram',
            "admin_only": True,
            "aliases": ('telegram', 'tg', '电报', '纸飞机', '飞机'),
            "index": '【Telegram】提醒与远程控制配置：TELEGRAM_BOTS、BOT_TELEGRAM_ADMIN_*',
            "title_line": '【Telegram】新邮件提醒与 Bot 远程控制',
            "lines": [
                'TELEGRAM_BOTS：作用=注册 Telegram Bot；参数=JSON 数组（BotFather Token 列表，至少 1 个才连接）；内容=TG 侧 bot 上线；意义=远程控制入口。',
                'BOT_TELEGRAM_ADMIN_USER_IDS：作用=指定管理员；参数=JSON 字符串数组（user id）；内容=允许执行 /mail 控制的用户；意义=权限边界。',
                'BOT_TELEGRAM_ADMIN_CHAT_IDS：作用=指定提醒接收会话；参数=JSON 字符串数组（chat id）；内容=新邮件提醒推送目标；意义=收提醒。',
                '/bot status、/bot pause|resume：作用=在 TG 侧查看/控制运行时；参数=无；内容=同 QQ 侧；意义=出门在外远程运维。',
                '三键均为 .env 键，改后重启生效；/bot status、/bot pause|resume 可在 TG 侧远程执行。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  Telegram 通道的三大用途：新邮件提醒推送、/mail 邮件控制的管理端、\n'
                '  运行时远程控制（状态/暂停/恢复）。三个 .env 键决定它是否生效。\n'
                '【权限与效果】\n'
                '  权限=仅管理员配置可用。\n'
                '【示例】TELEGRAM_BOTS=["123456:ABC-DEF..."]'
            ),
        },
        {
            "topic": '供应商',
            "admin_only": True,
            "aliases": ('供应商', 'provider', 'providers', '模型供应商', '包台'),
            "index": '【供应商】模型分组、优先级与健康检查：BOT_MODEL_REGISTRY、probe_llm_providers.py',
            "title_line": '【供应商】LLM 分组、路由优先级与健康检查',
            "lines": [
                'BOT_MODEL_REGISTRY：作用=.env 里登记 AI API 中转供应商；参数=JSON 对象，每项含 model/base_url/api_key/group/priority；内容=模型注册表底表；意义=静态渠道来源（运行时 add 的条目会与它合并）。',
                'priority：作用=全局尝试顺序；参数=整数 1-999，越小越优先；内容=故障转移次序；意义=便宜稳定的放前面，HCN 保底项放最后。',
                'BOT_CHAT_FAST_MAX_CANDIDATES：作用=快速模式候选上限；参数=0=不限制，1-100=最多尝试数量；内容=候选裁剪；意义=控制快速模式开销。',
                'scripts/probe_llm_providers.py：作用=命令行脱敏探测全部渠道；参数=--max-tokens（可选，1-4096，默认 32）；内容=每模型一次探测结果，不删除配置；意义=批量验收供应商。',
                '运行期管理走 /bot model（见「模型」模块）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  供应商层：.env 静态注册表（BOT_MODEL_REGISTRY）＋运行时动态注册\n'
                '  （/bot model add）合并成统一视图；探测脚本用于离线验收。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。registry 改 .env 后重启生效；运行时条目热生效。\n'
                '【示例】BOT_MODEL_REGISTRY={"myapi":{"model":"deepseek-v4-pro","base_url":"https://api.xxx.com/v1","api_key":"env:MY_KEY","group":"g1","priority":1}}'
            ),
        },
        {
            "topic": '订阅',
            "admin_only": False,
            "aliases": ('订阅', '訂閱', 'subscribe'),
            "index": '【订阅】平台新内容推送：/订阅 add|list|pause|resume|remove',
            "title_line": '【订阅】订阅平台新内容推送',
            "lines": [
                '/订阅 add <公开目标>：作用=添加订阅并推送到当前会话；参数=公开目标（必填，主页链接或 类型:id 字符串，多余参数会被显式拒绝）；内容=订阅已添加：<id>；意义=新内容/开播自动播报；群内 add 需管理员；重加已存在的订阅只增目的地，不会改动暂停状态（管理员暂停的订阅不会被悄悄恢复）。',
                '/订阅 list：作用=列出订阅；参数=无；内容=本会话目的地下的订阅（id｜平台｜名字｜启用/暂停）；意义=拿 id、看状态；群内仅管理员可看本群订阅。',
                '/订阅 pause|resume <id>：作用=暂停/恢复订阅；参数=id（必填，来自 list）；内容=已暂停/已恢复（仅本目的地）；意义=临时静默不删订阅。',
                '/订阅 remove <id>：作用=删除订阅；参数=id（必填）；内容=已删除（其他群的目的地不受牵连，最后一个目的地移除才整条删）；意义=退订。',
                '权限=全员自助；群内 add/list 需管理员，pause/resume/remove 群内需管理员且订阅推往本群，私聊需推给自己。',
                '目标示例：https://space.bilibili.com/123456｜bilibili:up:123456｜youtube:live:<频道ID或@handle>｜xiaohongshu:column:<用户ID>｜music.163.com/playlist?id=xxx',
                '支持范围：B站（UP主/直播间/番剧/收藏夹/合集）、小红书（图文/专栏/直播）、YouTube（频道/播放列表/直播）、微博、推特、Pixiv、Telegram 频道、音乐平台（网易云/QQ/酷狗/酷我/Apple/Spotify 的歌手/专辑/歌单）；建议直接粘贴主页或链接。',
                '/订阅 与 /bot subscribe 等价。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  订阅运行时按目标平台轮询新内容（视频/动态/直播开播/新歌），经统一\n'
                '  发送管线推送。订阅目的地绑定“添加时的会话”：群里添加=推本群，\n'
                '  私聊添加=推给你本人。\n'
                '【权限与效果】\n'
                '  权限=全员自助；群内 add/list 需要管理员（add 会向全群推送外部内容，无门槛=投毒面）；\n'
                '  私聊自助。pause/resume/remove 的目的地粒度：只影响本群/本人，别的群\n'
                '  订同一条不受影响。\n'
                '【示例】/订阅 add https://space.bilibili.com/123456'
            ),
        },
        {
            "topic": '点歌',
            "admin_only": False,
            # 點唱/点唱（tra3 波入 music._COMMAND_RE）help 同步入册。
            "aliases": ('点歌', 'music', '點歌', '点唱', '點唱', 'song', 'diange', 'dg', 'diangemoshi', 'dgms'),
            "index": '【点歌】搜索并发送歌曲：点歌 <歌名>｜点歌 <编号>｜点歌模式 <部件组合>',
            "title_line": '【点歌】搜索并发送歌曲',
            "lines": [
                '点歌 <歌名>：作用=按平台顺序搜索并发送；参数=歌名或关键词（必填，中英文均可；#歌名=强制按歌名搜索的转义写法）；内容=平台音乐卡片（无卡则封面图）等部件；意义=群内点播。',
                '点歌 <编号>：作用=同名多候选时二次选择；参数=编号（必填，来自候选列表，默认最多 5 个）；内容=选中歌曲；意义=精确选版本；仅紧随候选列表、默认 300 秒内有效，过期会提示重新点歌。',
                '点歌模式 <模式>：作用=设置输出方式；参数=模式（卡片|语音|音频|链接|全部，可组合如 卡片+语音，中英文别名均可）；内容=模式持久化确认；意义=控制输出形态；仅管理员，持久保存。',
                '平台：网易云/酷我/酷狗/QQ音乐/Apple Music/Spotify 顺序尝试，单平台取第一名，失败自动换下一个。',
                '示例：点歌 晴天｜候选出来后回复「点歌 2」｜点歌模式 卡片+语音',
            ],
            "detail": (
                '【板块介绍】\n'
                '  纯接口搜索不调 LLM；输出部件可拆可组：card=平台音乐卡片（默认）、\n'
                '  voice=语音、file=音频文件、link=文本链接。多候选交互需开启\n'
                '  BOT_MUSIC_CANDIDATES_ENABLED（默认关）：同名歧义返回编号列表，\n'
                '  有效期 BOT_MUSIC_CANDIDATES_TTL_SECONDS（默认 300 秒，下限 30），\n'
                '  候选数 BOT_MUSIC_CANDIDATES_LIMIT（默认 5，下限 2）。\n'
                '【权限与效果】\n'
                '  点歌=全员；点歌模式=仅管理员（写入 BOT_MUSIC_MODE 持久化）。\n'
                '【常见错误】编号只在候选列表有效期内有效；直接拿数字当歌名搜索不是有效歌名。\n'
                '【示例】点歌 晴天｜点歌 2｜点歌模式 卡片+语音'
            ),
        },
        {
            "topic": '表情',
            "admin_only": False,
            "aliases": ('表情', 'meme', '表情包', '表情生成', '表情制作', '表情包制作', '表情产生', '表情包产生', '表情製作', '表情包製作', '表情產生', '表情包產生', 'biaoqing', 'biaoqingbao', 'bqb', 'biaoqingshengcheng', 'bqsc'),
            "index": '【表情】生成文字表情：表情 <模板> <文字>｜表情 列表',
            "title_line": '【表情】生成文字表情',
            "lines": [
                '表情 <模板> <文字>：作用=套模板生成表情图；参数=模板名（必填）＋文字（按模板要求，多段用 ｜ 分隔）；内容=生成的表情图；意义=玩梗输出；需要图片的模板发图或 @ 群友后输命令，不带图用你的头像。',
                '表情 列表：作用=列出全部模板；参数=无；内容=可用模板 key 清单；意义=先查再玩。',
                '表情帮助：作用=用法说明；参数=无；内容=完整用法；意义=入门。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  对接本地 meme-generator-rs HTTP API（默认 http://127.0.0.1:2233）。\n'
                '  未安装/未启动服务时能力不可用。总开关 BOT_MEME_COMMAND_ENABLED；\n'
                '  功能开关 BOT_MEME_API_ENABLED=true（管理员在 .env 配置，需本地 meme-generator-rs 服务）。\n'
                '【权限与效果】\n'
                '  权限=全员。\n'
                '【示例】表情 petpet 可爱｜表情 文字表情 早上好｜晚上好'
            ),
        },
        {
            "topic": '偷表情',
            "admin_only": False,
            # 偷圖/偷图（meme_library 双向补齐波）与 表情隨機/隨機表情/隨機表情包/
            # 表情抽籤（tra49 波）均已入 meme_library._COMMAND_RE，help 同步入册。
            "aliases": ('偷表情', '偷表情包', '偷圖', '偷图', '表情隨機', '隨機表情', '隨機表情包', '表情抽籤', 'steal', 'toubiaoqing', 'tbq', 'toubiaoqingbao', 'tbqb'),
            "index": '【偷表情】表情库随机：偷表情 [关键词]｜表情库统计',
            "title_line": '【偷表情】从表情库随机抽取',
            "lines": [
                '偷表情 [关键词]：作用=按权重随机发一张入库表情；参数=关键词/情绪标签（可选，命中描述/情绪/场景标签）；内容=表情图；意义=表情包补给；写「私聊/私聊我」等同不填关键词但改为私聊发送。',
                '表情库统计：作用=看库存；参数=无；内容=数量与来源分布；意义=摸底。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  表情库由群图片自动吸收（VLM 打标、NSFW≥0.2 降权、≥0.8 永不发送）。\n'
                '  权重：守岸人/岸宝最优先，其次鸣潮/战双/库洛，再次 ACG，最后普通。\n'
                '  冷却 BOT_MEME_LIBRARY_COOLDOWN_SECONDS（默认 20 秒）防刷屏；总开关\n'
                '  BOT_MEME_LIBRARY_ENABLED（默认 false，需开启）。\n'
                '【权限与效果】\n'
                '  权限=全员。\n'
                '【示例】偷表情｜偷表情 猫猫'
            ),
        },
        {
            "topic": '搜图',
            "admin_only": False,
            "aliases": ('搜图', '搜圖', '以图搜图'),
            "index": '【搜图】图片反搜来源：搜图 ＋图片/@图片',
            "title_line": '【搜图】SauceNAO 图片反搜',
            "lines": [
                '搜图 ＋图片：作用=反搜图片来源；参数=图片（同一条消息带图或 @ 一张图；引用消息拿不到原图会明确提示）；内容=SauceNAO 匹配结果（相似度/来源链接）；意义=找画师/找出处。',
                '搜图 [图片]：作用=反搜；参数=图片段（必传，命令后不带参数，图片在同一条消息里）；内容=匹配结果；意义=溯源。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  调 SauceNAO 对图片做来源反搜。图片 URL 从消息图片段提取；\n'
                '  引用消息里的原图链接拿不到时会提示把图片和「搜图」发在同一条消息。\n'
                '【权限与效果】\n'
                '  权限=全员。未配 SauceNAO key 或无结果时有降级提示。\n'
                '【示例】（发一张图＋文字）搜图'
            ),
        },
        {
            "topic": '天气',
            "admin_only": False,
            # 天氣/查天氣/天氣預報均在 weather._WEATHER_RE（天氣預報=tra3 修活），
            # 与 META triggers_nickname 已登记词形对齐，help 解析同步。
            "aliases": ('天气', 'weather', '天氣', '查天氣', '天氣預報', 'tianqi', 'tq', 'chatianqi', 'ctq'),
            "index": '【天气】查询城市/区县天气：天气 <城市>｜支持区县 <省>',
            "title_line": '【天气】查询城市与区县天气',
            "lines": [
                '天气 <城市>：作用=查天气；参数=城市名（必填，≤20 字且要像地名；同名城市用 省-市 区分，如 浙江-杭州）；内容=当前天气＋预报卡（中国气象局 NMC 免 key，Open-Meteo 兜底）；意义=出行参考。',
                '支持区县 <省>：作用=列出可查区县；参数=省名（必填）；内容=该省区县码表清单；意义=查县级精细天气前的发现入口。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  数据源：中国气象局 NMC（免 key，内置 2527 个区县码表），失败时\n'
                '  Open-Meteo 兜底；渲染可用时输出 Mica 天气卡。触发收窄：查询词需像\n'
                '  地名——长度受限、不以「今天/真好/怎么样」等口语词开头、不以语气词\n'
                '  收尾，所以「天气真好」不会误触发。\n'
                '【权限与效果】\n'
                '  权限=全员。自然语言「帮我查杭州天气」经意图归一化同样命中。\n'
                '【示例】天气 上海｜天气 河北-大城｜支持区县 浙江'
            ),
        },
        {
            "topic": '行情',
            "admin_only": False,
            "aliases": ('行情', 'market', 'stock market', '股指', '股市', '大盘', '美股行情', '港股行情', 'A股行情', 'B股行情', '莫斯科股指', '莫斯科行情', 'hangqing', 'hq', 'gushi', 'gs', 'dapan', 'dp', 'guzhi'),
            "index": '【行情】全球股指：行情 或 美股行情/港股行情/A股行情/B股行情/莫斯科行情…',
            "title_line": '【行情】全球主要股指行情',
            "lines": [
                '行情：作用=全球主要指数一览；参数=无；内容=中国区/亚太/欧美指数一览（点位/涨跌幅）；意义=一眼看盘。',
                '行情 + 市场词：作用=只看指定市场；参数=市场词（写在同一句话里，可多个取并集）：A股/B股/上证B/深证B/美股/港股/恒生/日经/纳斯达克/纳指/道琼斯/道指/标普/韩/新加坡/印度/台湾/台股/英国/富时/法国/德国/莫斯科/俄罗斯；内容=对应指数；意义=聚焦关注的市场。过滤词没命中任何指数时回退全部。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  数据来自东方财富 push2 免费接口（免 key），进程内 60 秒缓存，\n'
                '  失败降级为「晚点再试」。触发收窄：≤32 字、不带链接（带链接走解析）、\n'
                '  房价/基金/币圈/显卡/期货/汇率等非股市“行情”自动让路。\n'
                '【权限与效果】\n'
                '  权限=全员。B 股与莫斯科（IMOEX）指数已上线。\n'
                '【示例】行情｜A股行情｜B股行情｜莫斯科行情'
            ),
        },
        {
            "topic": '个股行情',
            "admin_only": False,
            "aliases": ('个股行情', '股价', '股票价格', '市值', '股價', '個股', '英伟达股价', 'AMD 股价', '英特尔股价', '美股股价', 'stocks', 'stock', 'gujia', 'gj', 'gupiao'),
            "index": '【个股行情】科技公司股价：英伟达股价/AMD 股价/英特尔股价 或 股价/市值/stocks',
            "title_line": '【个股行情】上市科技公司股价与市值',
            "lines": [
                '股价 / 市值 / stocks：作用=九家科技巨头面板；参数=无（不点名公司）；内容=九家美股科技公司一行一价（现价/涨跌幅/近 30 个交易日走势折线＋日收益分布箱形图）；意义=一图看盘。',
                '公司名 + 股价：作用=查单家公司行情；参数=公司名或 ticker（必填）；内容=现价/涨跌幅/日 K/KDJ/总市值金融卡＋延迟标注；意义=聚焦关注的股票。',
                'OpenAI / Anthropic / 字节跳动：作用=问估值；参数=无；内容=有来源的估值口径说明（官方公告/公开报道）；意义=未上市不给股价，只给可信估值。',
                '股价 [公司名]：作用=查股价/市值；参数=公司名或 ticker 可选（英伟达/AMD/英特尔/苹果/微软/谷歌/亚马逊/Meta/台积电，繁体 股價/個股 与英文 stock/stocks 同样可触发；不点名=九家面板）；内容=金融卡或纯文本速览；意义=个股速览。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  数据来自东方财富免费接口（免 key），进程内 60 秒缓存，免费源为\n'
                '  延迟口径、卡上如实标注。当前支持：英伟达（NVDA）、AMD、英特尔\n'
                '  （INTC）、苹果（AAPL）、微软（MSFT）、谷歌（GOOGL）、亚马逊（AMZN）、\n'
                '  Meta（META）、台积电（TSM）；OpenAI/Anthropic/字节跳动未上市，只给\n'
                '  有来源的估值说明、不接行情。触发收窄：≤32 字、不带链接；裸「行情」\n'
                '  仍归全球股指，两者互不抢路由。\n'
                '【权限与效果】\n'
                '  权限=全员，群聊/私聊行为一致。走势折线为近 30 个交易日收盘；\n'
                '  箱形图只画多日分布，单日 K 线不成箱（不把 K 线冒充分布）。\n'
                '【失败兜底】行情拉不到回「美股行情暂时拉不到，晚点再试试？」；\n'
                '  卡片渲染失败自动回退纯文本。\n'
                '【示例】英伟达股价｜AMD 股价｜英特尔股价｜股价｜市值｜美股股价｜stocks'
            ),
        },
        {
            "topic": '商品行情',
            "admin_only": False,
            "aliases": ('商品行情', '黄金', '金价', '白银', '银价', '原油', '油价', '铜价', '大宗商品', '黃金', '金價', '白銀', '銀價', '油價', '銅價', 'gold', 'silver', 'oil', 'commodity', 'huangjin', 'jinjia', 'youjia', 'yuanyou', 'baiyin'),
            "index": '【商品行情】黄金/白银/原油/铜现价：黄金 或 金价/油价/大宗商品/gold',
            "title_line": '【商品行情】国际大宗商品现价与走势',
            "lines": [
                '黄金 / 金价：作用=查贵金属现价；参数=品种词可选（黄金/白银/银价…，不带品种=全品种面板）；内容=现价/涨跌幅＋30 日走势折线；意义=一眼看金市。',
                '原油 / 油价：作用=查能源现价；参数=品种词（原油/油价/铜价…）；内容=外盘主力连续报价＋涨跌；意义=盘面速览。',
                '大宗商品：作用=全品种面板；参数=无；内容=贵金属/能源/工业金属分组报价（东财外盘主力连续，LME 无源品种用 COMEX 铜承接）；意义=商品市场一览。',
                '黄金|金价|白银|原油|油价|铜价|大宗商品：作用=查商品现价；参数=品种词写在同一句话里即可（繁体 黃金/金價/白銀/油價/銅價 与英文 gold/silver/oil 同样可触发）；内容=分组报价卡或纯文本速览；意义=商品行情速览。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  数据来自东方财富外盘主力连续（免 key），进程内缓存；LME 无源\n'
                '  品种以 COMEX 铜承接，缺数据如实标注、绝不补 0。触发收窄：\n'
                '  ≤32 字、不带链接；「黄金股行情」这类股市语境自动让路给个股/股指，\n'
                '  不会误触商品卡。\n'
                '【权限与效果】\n'
                '  权限=全员，群聊/私聊行为一致。30 日走势为真实收盘折线。\n'
                '【失败兜底】行情拉不到会如实说暂拉不到；卡片渲染失败自动回退纯文本。\n'
                '【示例】黄金｜金价｜原油｜铜价｜大宗商品｜gold'
            ),
        },
        {
            "topic": '国债收益率',
            "admin_only": False,
            "aliases": ('国债收益率', '国债', '债券收益率', '期限利差', '收益率曲线', '中美国债', '國債', '債券收益率', 'guozhai', 'xianqilicha'),
            "index": '【国债收益率】主要期限国债收益率与利差：国债 或 国债收益率/期限利差/收益率曲线',
            "title_line": '【国债收益率】国债收益率与期限利差速览',
            "lines": [
                '国债 / 国债收益率：作用=看各期限收益率；参数=期限词可选（不带期限=全期限面板）；内容=2Y/5Y/10Y 等主要期限收益率＋变动；意义=债市一览。',
                '期限利差 / 收益率曲线：作用=看利差与曲线形态；参数=无；内容=10Y−2Y 利差（上游直供口径）＋曲线速览；意义=衰退信号/资金面参考。',
                '国债|国债收益率|期限利差|收益率曲线：作用=查收益率与利差；参数=无（繁体 國債/債券收益率 同样可触发；「中美国债」给中美两侧对比）；内容=收益率面板或利差行；意义=债市与利差速览。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  数据来自东方财富 datacenter 国债收益率接口（免 key），进程内\n'
                '  缓存；1Y 期限暂无稳定公开源，诚实不接、卡上如实标注，绝不补 0。\n'
                '  利差为上游直供的 10Y−2Y 口径，不做本地二次计算伪造。\n'
                '【权限与效果】\n'
                '  权限=全员，群聊/私聊行为一致。\n'
                '【失败兜底】数据拉不到会如实说暂拉不到；卡片渲染失败自动回退纯文本。\n'
                '【示例】国债｜国债收益率｜期限利差｜收益率曲线｜中美国债'
            ),
        },
        {
            "topic": '北向资金',
            "admin_only": False,
            "aliases": ('北向资金', '北上资金', '北向', '沪股通', '深股通', '北向資金', '北上資金', '滬股通', 'beixiang', 'hugutong', 'shengutong'),
            "index": '【北向资金】沪股通/深股通成交动向：北向资金 或 沪股通/深股通',
            "title_line": '【北向资金】北向成交动向速览',
            "lines": [
                '北向资金 / 北上资金：作用=看北向整体动向；参数=无；内容=沪股通/深股通成交总额等仍在披露的字段；意义=外资参与度参考。',
                '沪股通 / 深股通：作用=分通道看；参数=通道词可选；内容=对应通道成交数据；意义=分市场观察。',
                '北向资金|北上资金|沪股通|深股通：作用=查北向成交动向；参数=无（繁体 北向資金/滬股通/深股通 同样可触发）；内容=成交面板或纯文本速览；意义=外资动向参考。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  数据来自东方财富（免 key），进程内缓存。诚实口径：2024-08 起\n'
                '  交易所不再披露北向净买入额，本模块只报仍在披露的成交总额等\n'
                '  字段，绝不推算、不伪造净买入。\n'
                '【权限与效果】\n'
                '  权限=全员，群聊/私聊行为一致。\n'
                '【失败兜底】数据拉不到会如实说暂拉不到；卡片渲染失败自动回退纯文本。\n'
                '【示例】北向资金｜沪股通｜深股通｜北上资金'
            ),
        },
        {
            "topic": '汇率',
            "admin_only": False,
            "aliases": ('汇率', '匯率', '主要货币', '美元兑人民币', '100日元换多少人民币', 'USD/CNY', 'fx', 'forex', 'exchange rate', 'huilv', '换算', '換算'),
            "index": '【汇率】主要货币汇率：汇率 或 美元兑人民币/100日元换多少人民币/USD/CNY',
            "title_line": '【汇率】主要货币汇率速览与换算',
            "lines": [
                '汇率：作用=主要货币面板；参数=无；内容=USD 基准的主要货币对速览（中间价/参考价口径）＋无源货币对诚实标注；意义=一眼看汇市。',
                '美元兑人民币 / USD/CNY：作用=查指定货币对；参数=两种币名或 ISO 代码（中文、英文大小写均可）；内容=单行换算与口径/延迟标注；意义=定点查询。',
                '100日元换多少人民币：作用=带金额换算；参数=金额+币名（金额可省，省略按 1 计）；内容=按中间价折算的结果；意义=换钱参考。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  数据来自东方财富快查（免 key），进程内 60 秒缓存；中间价/参考价\n'
                '  口径、延迟行情与非可成交价提示都标在卡上。覆盖 11 币种（USD/EUR/\n'
                '  GBP/JPY/KRW/TWD/CNY/HKD/SGD/MOP/AED）；USD/TWD、USD/MOP、USD/AED\n'
                '  东财暂无行情，会诚实说「暂无数据」，绝不补 0。汇率无可用日 K，\n'
                '  卡上走势一栏如实标注，不伪造走势。\n'
                '【权限与效果】\n'
                '  权限=全员，群聊/私聊行为一致。繁体（匯率/兌換/換匯）与英文\n'
                '  （fx/forex/exchange rate）同样可触发；股价/股指等股票语境词会\n'
                '  自动让路给行情模块，不会误触汇率。\n'
                '【失败兜底】汇率拉不到回「汇率数据暂时拉不到，稍后再试。」；\n'
                '  卡片渲染失败自动回退纯文本。\n'
                '【示例】汇率｜美元兑人民币｜100日元换多少人民币｜USD/CNY｜匯率'
            ),
        },
        {
            "topic": '占卜',
            "admin_only": False,
            "aliases": ('占卜', '塔罗', '八字', '算命', '算卦', '起卦', '塔羅', '排盤', '排盘', '命盤', '命盘', '四柱', '搖卦', '摇卦', '今日塔羅', '今日塔罗', '今天塔羅', '今天塔罗', '塔羅三張', '塔罗三张', 'divination', 'tarot', 'bazi', 'iching', 'zhanbu', 'taluo', 'tl', 'suanming', 'suangua', 'sg', 'qigua', 'qg', '求籤', '求签', '六十四卦', '金錢卦', '金钱卦', '生辰八字', '算一卦', '起一卦', '摇一卦', '搖一卦', '掷一卦', '擲一卦', '占一卦', '一卦', '每日一签', '每日一簽', '每日一抽', 'paipan', 'sizhu', 'mingpan', 'pp', 'mp', 'yaogua', 'yg', 'liushisigua', 'lssg', 'jinqiangua', 'hexagram'),
            "index": '【占卜】八字排盘/塔罗/金钱卦（含地支藏干）：占卜 | 塔罗 三张 | 八字 1998年3月2日早上7点',
            "title_line": '【占卜】玄学娱乐三件套',
            "lines": [
                '占卜 / 起卦 / 算卦 / 摇卦：作用=金钱卦六掷成卦；参数=无；内容=本卦＋变卦（老爻自动变）；意义=一事一问的娱乐向卜卦。',
                '塔罗：作用=单张指引；参数=无；内容=单张牌＋解读；意义=快问快答。',
                '塔罗 三张：作用=牌阵；参数=无（触发词：三张/过去现在未来/牌阵）；内容=过去/现在/未来三张牌阵；意义=看脉络。',
                '塔罗 每日一抽：作用=今日牌；参数=无（触发词：每日一抽/今日塔罗/今天塔罗）；内容=今日固定牌（同一天同一人不变）；意义=日签。',
                '八字 / 排盘 <生日时间>：作用=四柱排盘；参数=生日时间（可选，如「八字 1998年3月2日早上7点」；日期支持 1998年3月2日/1998-03-02/1998/3/2；时辰支持 早上7点/晚上9点05分/21:51/早上7点半 等，只给日期按午时 12:00 排，不给日期按当前时点排）；内容=四柱排盘＋地支藏干（逐柱本气/中气/余干与权重）＋藏干五行加权统计＋免责尾注；意义=传统命理娱乐；支持 1900-2100 年。',
                '占卜|起卦|算卦|摇卦|六十四卦|金钱卦：作用=起卦；参数=无；内容=卦象＋变卦；意义=卜问。',
                '八字|排盘|四柱|命盘|算命|生辰 [生日时间]：作用=排盘；参数=生日时间可选（日期三种写法；时辰词归一化：下午/晚上/夜里/深夜 +12、凌晨12点=0点、中午=12 点；默认午时；缺省当前时点并附提示）；内容=四柱＋藏干（本气/中气/余干与通行子平权重，单支合计 100）＋藏干五行加权汇总＋尾注；意义=深度排盘。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  玄学娱乐三件套：金钱卦（六十四卦）、塔罗（单张/三张/每日一抽）、\n'
                '  八字排盘（含地支藏干）。纯本地计算无网络；输出为娱乐向文本并附\n'
                '  免责尾注，不含医疗/投资等严肃建议。\n'
                '【取值范围】\n'
                '  可排盘区间 1900-2100 年；超出会优雅提示换时间。日期解析失败会给出\n'
                '  可读错误与示例，不静默忽略。\n'
                '【权限与效果】\n'
                '  权限=全员，纯娱乐。\n'
                '【示例】占卜｜塔罗 三张｜塔罗 每日一抽｜八字 1998年3月2日早上7点'
            ),
        },
        {
            "topic": '快报',
            "admin_only": False,
            # 快報族 10 词（tra2 波入 _NEWS_TRIGGER_RE，与简体逐词同序）help 同步入册。
            "aliases": ('快报', '快報', '今日快报', '早报', '早報', '晚报', '晚報', '今日热点', '今日熱點', '科技新闻', '科技新聞', 'AI新闻', 'AI新聞', 'AI快報', '财经快报', '財經快報', '财经新闻', '財經新聞', '国际新闻', '國際新聞', 'news', 'kuaibao', 'kb', 'jinrikuaibao', 'jrkb'),
            "index": '【快报】今日新闻快报：快报 或 科技新闻/AI新闻/财经快报/国际新闻',
            "title_line": '【快报】今日新闻快报',
            "lines": [
                '快报 / 早报 / 晚报 / 今日热点：作用=综合快报；参数=无；内容=8 条混合头条（科技/财经/国际轮转）；意义=每日资讯入口。',
                '科技新闻 / AI新闻 / AI快报：作用=科技类目；参数=无；内容=科技/AI 类头条；意义=技术动向。',
                '财经新闻 / 财经快报：作用=财经类目；参数=无；内容=财经头条；意义=市场动向。',
                '国际新闻：作用=国际类目；参数=无；内容=国际头条；意义=世界动向。',
                '快报 [类目词]：作用=取快报；参数=类目词写在同一句话里：财经→finance、国际→world、科技/AI/人工智能→tech、其余→mix 轮转；内容=8 条标题＋来源＋链接；意义=资讯。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  国内可达 RSS 聚合（IT之家/少数派/华尔街见闻/BBC 中文），进程内\n'
                '  10 分钟缓存，单源失败静默跳过；抓取为空给降级文案不阻塞会话。\n'
                '【取值范围】\n'
                '  只认显式触发词（快报/早报/晚报/今日热点/类目词×新闻|快报/AI快报），\n'
                '  ≤32 字、不带链接；裸「新闻」不触发（留给联网搜索链路），句子带\n'
                '  搜索/搜一下/查一下/找新闻/联网/上网 时让路。\n'
                '【权限与效果】\n'
                '  权限=全员。\n'
                '【示例】快报｜科技新闻｜财经快报｜国际新闻'
            ),
        },
        {
            "topic": '维基',
            "admin_only": False,
            "aliases": ('维基', 'wiki', '百科', 'weiji', 'wjbk'),
            "index": '【维基】查通用百科（MediaWiki）：维基 <词条>',
            "title_line": '【维基】查询百科词条',
            "lines": [
                '维基 <词条>：作用=查 MediaWiki 百科；参数=词条名（必填，省略回用法）；内容=词条摘要（游戏类词条自动精简）；意义=快速百科查询。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  纯 MediaWiki 公开 API（免 key），默认中文维基（BOT_WIKI_LANG 可切），\n'
                '  支持独立页缺失时的精确列表条目提取（BOT_WIKI_ENTRY_PAGES，默认\n'
                '  鳴潮角色列表，最多优先 3 页）。\n'
                '【权限与效果】\n'
                '  权限=全员。查不到时会说明是独立页缺失、列表条目缺失还是网络失败。\n'
                '【示例】维基 量子力学｜维基 鸣潮守岸人'
            ),
        },
        {
            "topic": '萌娘百科',
            "admin_only": False,
            "aliases": ('萌娘百科', '萌百', 'moegirl', 'mengbai', 'mb', '是誰', '是什麼', '介紹一下', '是谁', '是什么', '介绍一下'),
            "index": '【萌娘百科】查 ACG 向百科：萌娘百科 <词条>｜直接问 XX是谁',
            "title_line": '【萌娘百科】查询萌娘百科词条',
            "lines": [
                '萌娘百科 <词条>：作用=查萌百词条；参数=词条名（必填）；内容=词条摘要；意义=二次元知识库。',
                '直接问「XX是谁/是什么/介绍一下」：作用=实体问句自动查萌百；参数=实体名（2-30 字，剥掉问句后）；内容=萌百摘要；意义=自然问法直达；查不到时无感转人格聊天回答。',
                '「XX是谁？」式问句：作用=自动查询；参数=实体名（从问句剥离，2-30 字）；内容=命中=萌百摘要，未命中=人格聊天兜底；意义=无门槛问询。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  萌百 MediaWiki 公开 API。两条路径：显式指令；以及二次元实体问句\n'
                '  自动查询（群聊不 @ 不抢答，与聊天同门控；BOT_MOEGIRL_QUESTION_ENABLED\n'
                '  可关）。问句剥离后剩人称代词（你/我/谁…）、过短/过长、含链接的\n'
                '  一律不查，交给聊天链路。\n'
                '【权限与效果】\n'
                '  权限=全员。\n'
                '【示例】萌娘百科 初音未来｜初音未来是谁？'
            ),
        },
        {
            "topic": '历史上的今天',
            "admin_only": False,
            "aliases": ('历史上的今天', 'today', 'today in history', '今日', 'lssd', 'jinrilishi', 'jrls'),
            "index": '【历史上的今天】每日历史推送：立即查 | 设置 HH:MM | 状态 | 取消',
            "title_line": '【历史上的今天】每天定时推送历史',
            "lines": [
                '历史上的今天：作用=立即查询当天历史；参数=无；内容=当天历史事件清单；意义=即查即看。',
                '历史上的今天 设置 <HH:MM>：作用=设置每日推送时间；参数=时间（必填，HH:MM 24 小时制，取值 00:00-23:59）；内容=设置确认；意义=每天定时收到；群内需管理员（影响全群），私聊自助。',
                '历史上的今天 状态：作用=查看推送状态；参数=无；内容=当前推送时间或未设置；意义=核对。',
                '历史上的今天 取消：作用=取消每日推送；参数=无；内容=取消确认；意义=退订；群内需管理员。',
                '短别名：/历史、/今日历史（带斜杠，避免把聊天里的“历史”误触发）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  数据源百度百科公开接口（带缓存与代理支持）。推送订阅按会话存\n'
                '  data/today_history_push.json（私聊 f_<user_id>、群聊 g_<group_id>），\n'
                '  由调度器按表注册每日任务。\n'
                '【权限与效果】\n'
                '  权限=全员查询；设置/取消在群聊需要管理员（推送时间影响全群），\n'
                '  私聊自助。订阅表损坏时会拒绝改写以保护其他会话的订阅。\n'
                '【示例】历史上的今天 设置 08:30'
            ),
        },
        {
            "topic": '下载',
            "admin_only": False,
            "aliases": ('下载', 'download'),
            "index": '【下载】下载视频/音频：/bot download <链接>',
            "title_line": '【下载】下载视频/音频',
            "lines": [
                '/bot download <链接>：作用=下载媒体并回传文件；参数=链接（必填，http(s) 开头；B站/油管/推特/小红书/抖音等）；内容=文字摘要（标题/大小/分辨率/时长/画质标注）＋视频文件段；意义=把在线视频搬进群。',
                '限制：单文件 ≤1GB（超限自动降清晰度至最高 8K 上限内）；拒绝非 http(s) 与内网/保留地址（含 DNS 解析后的私网 IP）；依赖 yt-dlp。',
                '权限=全员（H6 定案：产品开放给普通用户，安全边界由 downloader 侧承担）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  yt-dlp 下载到 data/downloads/ 并做媒体分析，经发送管线回传文件段。\n'
                '  cookies（/bot cookie import）与代理（BOT_DOWNLOAD_PROXY）对下载同样生效。\n'
                '【取值范围】\n'
                '  大小上限 BOT_DOWNLOAD_MAX_BYTES（默认 1073741824=1GB）；最大高度\n'
                '  BOT_DOWNLOAD_MAX_HEIGHT（默认 0=不限制，超限自动降级）；超时\n'
                '  BOT_DOWNLOAD_TIMEOUT_SECONDS（默认 120 秒，发送侧最长 300 秒）。\n'
                '【权限与效果】\n'
                '  权限=全员。失败优雅降级为文字（只说原因类型，不泄露堆栈与 cookie）。\n'
                '【示例】/bot download https://www.bilibili.com/video/BVxxxxxxxx'
            ),
        },
        {
            "topic": '昵称',
            "admin_only": False,
            "aliases": ('昵称', 'alias'),
            "index": '【昵称】角色昵称触发命令：守岸人/岸宝 <命令>',
            "title_line": '【昵称】用角色昵称触发命令',
            "lines": [
                '/<昵称><命令>：作用=用昵称代替 /bot 前缀触发命令；参数=命令名（必填，如 帮助/状态/为什么/天气/点歌/订阅/日志/清理历史/暂停/继续，斜杠可省略）；内容=同对应命令；意义=角色扮演的日常用法。可用昵称经 /bot runtime nickname 维护。',
                '模块/动作词归一：模型=model、设置=runtime、帮助=help、维基=wiki；查看/列表=list、切换=set、用量=usage、思考=think 等动词自动映射。',
                '昵称命令受限：部分管理命令（如日志/记忆）会要求回落到 /bot 形式执行。',
                '管理员另可用 /bot 昵称 set <QQ号> <小名>（5-11 位数字＋1-32 字小名）为群友记小名，用于好感度称呼。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  昵称命令层：把「/岸宝帮助」「守岸人 状态」解析成对应能力。昵称清单\n'
                '  存运行时设置（BOT_PERSONA_NICKNAMES / runtime nickname 维护），\n'
                '  未配置时别名层关闭；标准 /bot 前缀不受影响。\n'
                '【权限与效果】\n'
                '  权限=触发本身全员；各命令自身的权限照旧生效。\n'
                '【示例】/岸宝帮助｜守岸人 天气 上海｜/岸宝点歌 晴天'
            ),
        },
        {
            "topic": '链接',
            "admin_only": False,
            "aliases": ('链接', 'links'),
            "index": '【链接】自动解析：直接发平台链接即可',
            "title_line": '【链接】平台链接自动解析信息卡',
            "lines": [
                '直接发链接：作用=自动解析成信息卡；参数=URL（消息里含 http(s) 链接即触发，无需命令词）；内容=平台信息卡（标题/作者/数据/封面，GitHub 仓库出星标/Fork/简介/README 摘要）；意义=不用打开 App 就知道链接里是什么。',
                '支持平台：B站/抖音/小红书/油管/推特/小黑盒/米游社/森空岛/库街区/Lofter/Pixiv/GitHub/音乐平台等；长视频走视频理解可追问。',
                '发链接（无命令词）：作用=解析；参数=URL（1 条或多条，取第一个）；内容=信息卡/摘要；意义=内容预览。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  链接解析在路由优先级 46：只要文本含 http(s) 链接且未命中更高优先级\n'
                '  命令（如 /bot download、订阅），就走解析器组出信息卡。\n'
                '【权限与效果】\n'
                '  权限=全员。相关平台需要登录态时用 /bot cookie import 补 cookie。\n'
                '【示例】直接粘贴 https://www.bilibili.com/video/BVxxxx'
            ),
        },
        {
            "topic": '草稿',
            "admin_only": False,
            "aliases": ('草稿', 'autosend', '自动发送', '报存', '報存'),
            "index": '【草稿】自然语言起草自动发送：报存 给 <收件人> 发消息|邮件，内容…',
            "title_line": '【草稿】自然语言起草自动发送',
            "lines": [
                '报存 给 <收件人> 发消息，内容…：作用=起草聊天消息草稿；参数=收件人（必填，可用 、,， 分隔多个）＋内容要求（可选，支持 主题：… 内容：… 结构）；内容=草稿预览（通道/收件人/主题/内容要求）；意义=把“要发什么”先落成结构化草稿。',
                '报存 给 <收件人> 发邮件，主题：<主题>，内容：<正文>：作用=起草邮件；参数=收件人（必填）＋主题（可选）＋内容（可选）；内容=草稿预览（M0 仅预览不真实发送）；意义=邮件起草。',
                '报存 给 <收件人> 发消息|邮件 [，内容要求]：作用=起草；参数=收件人必填（多个用 、,， 分隔）；「主题：」段作为邮件主题；「内容」后的文本作为正文要求；内容=草稿预览卡；意义=规划待发内容。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  自动发送子系统的入口：解析成结构化意图（通道/收件人/主题/正文）并\n'
                '  输出预览。当前版本只做预览（confirm_required），不真实发送。\n'
                '【权限与效果】\n'
                '  权限=全员（预览无副作用）。邮件通道风险级高于普通消息。\n'
                '【示例】报存 给小明、小红 发邮件，主题：周末聚餐，内容：周六晚上六点老地方见'
            ),
        },
        {
            "topic": '吃什么',
            "admin_only": False,
            "aliases": ('吃什么', '吃啥', '菜谱', 'eat', 'food', 'recipe', 'chishenme', 'csm', 'caipu', 'cp', 'zenmezuo', 'zmz'),
            "index": '【吃什么】随机推荐家常菜/查菜谱：吃什么 | 吃什么 三选一 | 菜谱 番茄炒蛋',
            "title_line": '【吃什么】解决选择困难',
            "lines": [
                '吃什么：作用=随机推荐 1 道家常菜；参数=无；内容=Mica 菜品卡（名字/口味/食材/做法，本地图包有图上卡）；意义=治今天吃什么。',
                '吃什么 三选一 / 来三道 / 再来一道：作用=控制数量与换一批；参数=修饰词（三选一|来三道|再来一道|再来）；内容=3 道不同菜或补一道；意义=选择困难加倍版。',
                '吃什么 辣的 / 不辣 / 微辣 / 中辣 / 特辣：作用=按辣度过滤；参数=辣度词；内容=过滤后的推荐；意义=口味适配。',
                '菜谱 <菜名> / 怎么做 <菜名> / 如何做 <菜名>：作用=查做法；参数=菜名（必填）；内容=食材＋步骤卡；意义=照着做。',
                '带忌口/食材/人数约束（如「不吃香菜 有鸡蛋 两人吃」）自动走 AI 生成菜谱；菜品图片放 Runtime data/food_images/<菜名>.jpg|.png|.webp 即可上卡。',
                '菜谱 <菜名>（别名 怎么做/如何做）：作用=查做法；参数=菜名必填；内容=食材与步骤；意义=烹饪指引。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  本地菜品库随机推荐＋AI 约束生成双层：命中修饰/约束词表走过滤或 AI，\n'
                '  否则纯随机。推荐与菜谱渲染 Mica 卡图（含本地封面），失败回退文本。\n'
                '【权限与效果】\n'
                '  权限=全员。普通闲聊（吃了吗/吃火锅）不会被误判成点菜。\n'
                '【示例】吃什么｜吃什么 三选一｜吃什么 不辣 有鸡蛋｜菜谱 番茄炒蛋'
            ),
        },
        {
            "topic": '媒体归档',
            "admin_only": True,
            "aliases": ('收藏', '归档', '存图', '收图', '存聊天记录', '存记录', 'archive', 'shoucang', 'guidang'),
            "index": '【媒体归档】媒体按 类别/作品 归档：收藏｜归档 IP=原神｜存聊天记录',
            "title_line": '【媒体归档】把媒体按 类别×作品 归档到本机',
            "lines": [
                '收藏：作用=归档媒体；参数=可选 分类= IP= 角色=（管理员另可 子路径=）；内容=与图片/动图/视频同条发送，或回复那条媒体；意义=自动分类存档。',
                '归档：作用=同收藏；参数=同上；内容=VLM 判类别与作品来源（cosplay/二次元插图/表情包/截图/照片/风景/人物/动图），判不出落「未识别」；意义=双层目录管理。',
                '存聊天记录：作用=归档聊天记录；参数=无（回复合并转发触发）；内容=展开为 Markdown（含一句话摘要）；意义=永久留档。',
                '安全=SSRF 护栏+magic bytes 质检+sha256 去重+单文件/每日限额；权限=仅管理员（bot_media_archive_min_role，默认超管）。',
                '收藏|归档 [分类=x] [IP=x] [角色=x]：作用=归档；参数=可选；内容=自动/指定分类；意义=整理。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  把发到 bot 的图片/动图/视频/聊天记录分析内容并按 类别×作品 双层\n'
                '  目录归档到本机 data/media_archive（VLM 判定，指令可覆盖）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（bot_media_archive_min_role，默认 super_admin；改 user 开放全员+限额）。\n'
                '【示例】[图片] 收藏｜[图片] 收藏 分类=cosplay IP=鸣潮｜（回复图片）收藏｜（回复转发）存聊天记录'
            ),
        },
        {
            "topic": '群信息',
            "admin_only": False,
            # 词表**必须写字面量**：`scripts/command_catalog.py::_eval_literal` 只解析
            # 同模块的简单常量赋值（跨模块引用当场 ValueError「无法解析的模块级名字」，
            # 2026-09-25 实测），所以「引用真身」这条路对本文件不成立。新增词形必须
            # 与 group_info._INTENT_OF_WORD 同步，由触发词双向门执法。
            "aliases": ('群信息', '本群信息', '群资料', '群主是谁', '谁是群主', '群人数', '群公告', '群精华', '精华消息', '本群多大了', '群相册', '本群相册', '群相册列表', '群待办', '本群待办', '群待办列表', '群里都有谁', '本群都有谁', '群里谁说过话', '本群谁说过话', '群参与者', '本群参与者', '都有谁说过话', '我都跟谁聊过', '跟谁聊过'),
            "index": '【群信息】查本群资料：群信息｜群主是谁｜群人数｜群公告｜群相册｜群里都有谁',
            "title_line": '【群信息】本群资料、群主、人数、公告、精华、相册、待办与参与者',
            "lines": [
                '群信息：作用=查本群小档案；参数=无；内容=群名/群主/人数/上限/管理员数，管理员另附公告首段与精华条数；意义=一问就知道群概况。',
                '群主是谁｜群人数｜本群多大了：作用=单点直问；参数=无；内容=只答问的那一项（建群时长依赖协议字段，没有就直说）；意义=口语直问直答。',
                '群公告｜群精华：作用=看公告首段/精华条数；参数=无；内容=仅管理员，其余成员收到权限提示；意义=群务信息分级可见。',
                '群相册｜群待办：作用=看本群相册概览与挂着的待办；参数=无；内容=相册只到「哪个相册多少张」这一层、不列单张照片，待办最多列 5 条并显式说另有几条；意义=群务一眼看全。',
                '群里都有谁｜群参与者｜谁说过话：作用=说清这个群里都有谁在说话；参数=无；内容=按记忆里的说话人给名字（不是协议成员名单），人多的群给前若干名并显式说还有多少，读过记录却一条都没取到时直说「没读到记录」而不是「没人说过话」；意义=知道自己在跟谁聊。',
                '边界（诚实降级）：群链接/群分享、群等级/群标签仍无对应动作，不做不假装；相册与待办的字段名认不出时只报条数、不编名字；接口失败如实说拿不到（≠本群没有）；成员名单不整列（隐私+防刷屏）；参与者来自记忆而非协议名单，两者不是一回事；仅群聊生效。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  在群里直接问「群信息 / 群主是谁 / 群人数 / 群公告 / 群精华 / 群相册 / 群待办 / 群里都有谁」，\n'
                '  守岸人走 OneBot V11 群接口（群资料/成员列表/公告/精华/相册/待办）现查现答；\n'
                '  资料带进程内缓存（资料 600s/成员 900s/公告 600s/相册 600s/待办 120s），\n'
                '  待办缓存刻意给得短——刚设好的待办不该被旧表盖住。\n'
                '【参与者这一项】\n'
                '  「群里都有谁 / 群参与者 / 谁说过话」这一族不查协议名单，答的是记忆里真的说过话的人；\n'
                '  同一份判据在群聊与私聊各自成腿，看的范围就是当前这个会话；没读到记录时如实说没读到。\n'
                '【权限与效果】\n'
                '  权限=群资料/人数/相册/待办/参与者全员；公告与精华仅管理员。仅群聊生效，私聊回提示。\n'
                '【示例】群信息｜群主是谁｜群人数｜本群多大了｜群公告｜群精华｜群里都有谁'
            ),
        },
        {
            "topic": '宿主机状态',
            "admin_only": True,
            # 词表必须写字面量（command_catalog 的静态求值只认同模块常量），
            # 且与 host_state.DEFAULT_TRIGGER_WORDS 逐字同集，由触发词双向门执法。
            "aliases": ('宿主机状态', '机器状态', '机器配置', '宿主状态', '宿主機狀態', '機器狀態', 'hoststate', 'jiqizhuangtai', 'jizhuangtai', 'jiqipeizhi'),
            "index": '【宿主机状态】超管看本机：机器状态｜机器配置｜版本与占用',
            "title_line": '【宿主机状态】这台机器的配置、占用与运行版本（仅超管）',
            "lines": [
                '机器状态：作用=报本机实况；参数=无；内容=CPU/内存/磁盘占用、显卡与显存、系统版本，附守岸人自己的运行版本族；意义=一句话知道机器现在累不累。',
                '机器配置：作用=报硬件；参数=无；内容=型号/核心数/总内存/磁盘分区容量；意义=区分「配置」与「此刻占用」两件事。',
                '读数来源：全部本机现算（版本走包元数据，占用走系统计数器），不是背下来的一段话；拿不到的项直说拿不到，绝不补一个看起来合理的数。',
                '出图：能出图时发一张超管视图卡片（属性名与属性值各自左对齐）；渲染后端不可用时退成纯文本，并把「卡未出图」那句话说明白。',
                '边界：这是超管专属视图，非超管问到只会得到一句温和的「这台机器我不对外报」，不会泄露盘符路径或任何密钥形态；本能力只读，不碰任何设置与文件。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  说「机器状态 / 机器配置 / 宿主机状态」，守岸人现读本机事实：\n'
                '  版本族（NoneBot、OneBot 适配器、协议端、插件、Python）走包元数据，\n'
                '  硬件与占用走系统计数器，两路都汇到 domains/ops/host_metrics.py 这一个取数口。\n'
                '【权限与效果】\n'
                '  权限=仅超级管理员（其余角色得到一句温和的拒绝，不报错、不泄露）。\n'
                '  效果=一张 Mica 卡片图 + 一份纯文本台账；渲染后端缺席时只剩文本，且卡上那行「未出图」会直说。\n'
                '  读数 90 秒内复用缓存，连续追问不重复扫机器；每行出卡前过打码口。\n'
                '【示例】机器状态｜机器配置｜宿主状态｜hoststate'
            ),
        },
        {
            "topic": '书面同意',
            "admin_only": True,
            # 词表必须写字面量（command_catalog 的静态求值只认同模块常量），
            # 且与 consent_admin.DEFAULT_TRIGGER_WORDS 逐字同集，由触发词双向门执法。
            "aliases": ('同意卡', '书面同意', '同意單', '書面同意', 'consentcard', 'yijika', 'shumiantongyi'),
            "index": '【书面同意】危险参数的批准入口：同意卡 待批｜看｜批｜驳（仅管理员）',
            "title_line": '【书面同意】哪些参数改动在等谁点头，以及怎么点这个头（仅管理员）',
            "lines": [
                '同意卡 待批：作用=列出还没人批的工单；参数=无；内容=每张卡的工单号、短码、要改哪枚参数、旧值→新值、风险档、申请人、签出与过期时刻；意义=点头之前先把要改的东西看完整，不靠别人转述。',
                '同意卡 看 <工单号>：作用=单看一张卡的全文；参数=工单号（卡面上那一串，必填）；内容=与待批页同一套字段，多一个「状态」；意义=群里传话传了一半时，以账上的原文为准。',
                '同意卡 批 <工单号> <短码>：作用=照卡面批准这一件；参数=工单号 + 卡上短码（两个都必填，短码必须逐字对上）；内容=批语已记下，并说清接下来该谁做什么；意义=危险的参数改动要的是有权限的人亲手的一句话，不是模型顺手的一个字。',
                '同意卡 驳 <工单号> <短码>：作用=驳回并作废这张卡；参数=工单号 + 短码；内容=已驳回，这张卡不再有效；意义=不想改就明说不改，别让它挂到过期还占着待办。',
                '认不下的句子一律不当命令：触发词后面跟了我看不懂的东西，我就当没听见，绝不「大概像」就把它读成一次批准。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  需要书面同意的参数被改动时，设置咽喉不落笔，先签一张同意卡；这一族命令就是把那张卡批掉或驳回的那句话。\n'
                '  分级表唯一住 domains/core/safety_exec/config_risk.py，同意账唯一住 domains/core/safety_exec/consent.py，\n'
                '  执法点唯一住 domains/core/safety_exec/settings_gate.py——本命令面零判定、零第二本账，只把一句入站消息交给它。\n'
                '【档位是什么】\n'
                '  R0 不问就改（每次照记一行流水）；R1 由管理员在原会话里确认；R2 要超级管理员在私聊里亲口批；\n'
                '  R3 连批都不给，只允许出待审补丁，部署由主人亲手做。\n'
                '【权限与效果】\n'
                '  权限=管理员可看单；一张具体的卡够不够格批，由账上的阶梯判：可信级、私聊门、原会话门、\n'
                '  发起人不得批自己发起的那张、一次性、到点作废（不可续）。判据只有一处，这里不复制。\n'
                '  效果=改动的真身在批之前一个字节都不动；短码对不上不算批也不算驳，那张卡照旧待批，但这次尝试会落一条流水。\n'
                '【批了之后】\n'
                '  批准只记下「谁批的、批的是哪件事」；真正落笔要原来发起这件事的人用同一参数再说一次，凭证一次有效。\n'
                '  账本装不上、值与当初批的对不上、没有热改路径的，一律不改，并且明说为什么没改——不做「看起来改了」那种回显。\n'
                '【示例】同意卡 待批｜同意卡 看 3f2a1b｜同意卡 批 3f2a1b 8c1d4e7a｜书面同意 驳 3f2a1b 8c1d4e7a'
            ),
        },
        {
            "topic": '好感度',
            "admin_only": False,
            # 親密度（tra3）/查詢好感（tra49）已入 affinity._COMMAND_RE，help 同步入册。
            # 裸「好感」（后随 空白/算法/说明/规则/榜/我 时触发）为 A21 审计补登词形。
            "aliases": ('好感度', '好感', '好感查看', '查询好感', '查詢好感', '親密度', 'affinity', 'haogandu', 'hgd', 'haoganchakan', 'hgck', 'chaxunhaogan', 'cxhg'),
            "index": '【好感度】双向好感与算法：好感度｜好感度 我｜好感度 算法',
            "title_line": '【好感度】守岸人与你的双向好感',
            "lines": [
                '好感度：作用=查好感；参数=无；内容=私聊=双向好感卡；群聊=本群好感榜（有印象成员，自己高亮，展示前 12/上限 60）；意义=关系可视化。',
                '好感度 我：作用=只看自己；参数=我（别名 自己/me）；内容=双向分值；意义=群里不想看榜时用。',
                '好感度 算法：作用=说明规则；参数=算法（别名 说明/规则/help）；内容=图文算法卡＋你与守岸人之间的氛围画像；意义=透明化。',
                '计分（v5 定性版）：好感随言行连续累积——综合说话的温度、相处的时间、第一印象、当天状态平滑变化，没有固定加几减几；同一天同类言行影响递减；久不联系慢慢回到基准；难听的记忆随时间淡去。',
                '档位：初识/生疏/微凉/稍淡/友善（基准）/亲近/挚友/独一份 共八档，连续过渡、不在门槛上生硬跳变；任何档位都不强硬、不辱骂、不弃聊。',
                '好感度 我|自己|me：作用=只看自己；参数=任选其一；内容=双向分值；意义=隐私。',
                '好感度 算法|说明|规则|help：作用=算法说明；参数=任选其一；内容=规则＋档位态度对照＋你与守岸人之间的氛围画像（定性描述，不展示具体加减数值）；意义=透明。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  双向好感体系：守岸人对你=印象好感度（-100~+100）；你对守岸人=你\n'
                '  表达中友好成分的加权占比（估算）。好感档位只影响语气与距离感，\n'
                '  不改变安全边界。\n'
                '【权限与效果】\n'
                '  权限=全员。好感度功能总开关 bot_affinity_enabled。\n'
                '【示例】好感度｜好感度 我｜好感度 算法'
            ),
        },
        {
            "topic": 'Epic',
            "admin_only": False,
            "aliases": ('epic', 'epic free', 'epic 免费', '免费游戏', '免費遊戲', '遊戲免費', 'steam免費', 'steam 免費', '游戏免费', 'steam免费', 'steam 免费'),
            "index": '【Epic】每周免费游戏：epic 或 Epic 免费',
            "title_line": '【Epic】查询每周免费游戏',
            "lines": [
                'epic / epicfree / Epic 免费 / 免费游戏 / steam免费：作用=查本周限免；参数=无；内容=Epic 每周限免＋Steam 100% 折扣限免合并清单（标题/截止/链接，Mica 卡图）；意义=白嫖情报。',
                'epic（别名 epicfree/epic free/epic 免费/免费游戏/游戏免费/steam免费/steam free/steamfree）：作用=查询；参数=无；内容=本周免费游戏清单；意义=情报。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  聚合 Epic 公开接口与 Steam 限免，渲染可用时输出 Mica 信息卡，\n'
                '  文本作兜底。\n'
                '【权限与效果】\n'
                '  权限=全员。\n'
                '【示例】epic'
            ),
        },
        {
            "topic": '随机图',
            "admin_only": False,
            # 隨機圖/來張圖（tra2 波入 DEFAULT_TRIGGER_WORDS）help 同步入册。
            "aliases": ('随机图', '来张图', '隨機圖', '來張圖', 'randpic', 'suijitu', 'sjt', 'laizhangtu', 'lzt'),
            "index": '【随机图】从图库随机发一张：随机图 / 来张图（也可回复后主动发）',
            "title_line": '【随机图】图库随机发图',
            "lines": [
                '随机图 / 来张图：作用=从你配置的图库文件夹随机发一张图；参数=无；内容=一张图片（jpg/jpeg/png/gif/webp/bmp，单张 ≤20MB）；意义=自建图库的抽卡玩法。',
                '回复后主动发图（P14）：bot 答完一句就有概率补一张图；BOT_RANDPIC_DISPATCH_ENABLED、BOT_RANDPIC_DISPATCH_PROBABILITY、BOT_RANDPIC_DISPATCH_COOLDOWN_SECONDS、BOT_RANDPIC_DISPATCH_MAX_PER_HOUR（缺省关）。戳 bot 那条走戳一戳的 randpic 臂（见「戳一戳」页），三触发共用同一条读目录路径与同一本窗账。',
                '窗内不重发：BOT_RANDPIC_NO_REPEAT_WINDOW_SECONDS（按会话记账，0=关=旧行为可重样）；开态下指令路整库都在窗内时退「最久没发」那张（不拒不发），主动路宁可不发也不刷屏。',
                '配置：图库目录写在 BOT_RANDPIC_DIRS（可多个、递归扫描、只读绝不自建目录）；触发词可用 BOT_RANDPIC_TRIGGER_WORDS 换成自己的（默认 随机图/来张图）。',
                '随机图|来张图：作用=发图；参数=无（触发词后跟标点/语气词也可命中；「随机图片库」这类包含关系词不误触发）；内容=图片或图库为空的配置提示；意义=娱乐。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  借鉴 nonebot-plugin-randpic 的“指令→随机图”玩法但只吸收思路：\n'
                '  不建目录、不建数据库、不做上传，一把随机梭哈。目录清单 30 秒 TTL\n'
                '  缓存，改文件夹半分钟内生效。P14 波把「谁开口要图才发」扩成\n'
                '  三触发：指令 / 回复完用户消息后 / 用户戳 bot 后（后两条缺省关）。\n'
                '【取值范围】\n'
                '  BOT_RANDPIC_DIRS：文件夹路径列表；扩展名 jpg/jpeg/png/gif/webp/bmp；\n'
                '  单文件 ≤20MB；目录不存在/为空/图被移走时给友好提示不报错、不发死引用。\n'
                '  BOT_RANDPIC_NO_REPEAT_WINDOW_SECONDS：≥0 秒，0=不记账按纯随机。\n'
                '【权限与效果】\n'
                '  权限=全员（bot_randpic_enabled 可关）。主动发图那条腿同样吃安静时间\n'
                '  窗与 blocked 名单两道硬门，拨开概率也越不过。\n'
                '【示例】随机图｜来张图'
            ),
        },
        {
            "topic": '提醒',
            "admin_only": False,
            "aliases": ('提醒', 'reminder', '叫我', '记得叫', '記得叫', '定时提醒', 'tixingliebiao', 'txlb', 'wodetixing', 'wdtx', 'kankantixing', 'kktx', 'younaxietixing', 'ynxt'),
            "index": '【提醒】到点督促：12点提醒我写作业｜提醒列表｜取消提醒 <id前几位>',
            "title_line": '【提醒】时间点记忆与主动督促',
            "lines": [
                '<时间>提醒我 <事项>：作用=到点主动督促；参数=时间（必填，支持绝对「12点/明天早上8点/下午三点半」与相对「半小时后/N分钟后/N小时后」）＋事项（可选，截取 ≤120 字，省略给默认文案）；内容=记下确认＋取消用的 id 前缀；意义=守岸人版闹钟。',
                '提醒列表 / 我的提醒：作用=查看待办；参数=无；内容=本会话待办提醒（id 前 6 位＋时刻＋事项）；意义=盘点。',
                '取消提醒 <id前缀>：作用=取消某条；参数=id 前缀（必填，4-12 位十六进制，需唯一命中，多条命中会要求换更长前缀）；内容=取消确认；意义=反悔。',
                '规则：只提醒“当前会话”；无明确日词且时刻已过自动顺延明天；时间必须晚于当前，否则视为没解析到。',
                '提醒列表|我的提醒|看看提醒|有哪些提醒：作用=列待办；参数=无；内容=清单；意义=盘点。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  时间点记忆：把“几点做什么”存库，每分钟调度任务到点以守岸人语气\n'
                '  主动督促。触发方式是自然语言（含 提醒/叫我/记得叫 信号词且能解析出\n'
                '  时间），或列表/取消查询。\n'
                '【权限与效果】\n'
                '  权限=全员（bot_reminder_enabled 可关）。投递按会话作用域（群=群内，\n'
                '  私聊=本人），发送走队列。\n'
                '【示例】12点提醒我写作业｜明天早上8点叫我起床｜半小时后提醒我去看汤｜提醒列表｜取消提醒 a3f2'
            ),
        },
        {
            "topic": '笔记',
            "admin_only": False,
            "aliases": ('笔记', '筆記', 'biji', 'note', '笔记列表', 'bijiliebiao', 'bjlb'),
            "index": '【笔记】Markdown 笔记与待办：笔记 记 <内容>｜笔记列表｜笔记 看 N｜做完 N｜删笔记 N',
            "title_line": '【笔记】Markdown 笔记与待办勾选',
            "lines": [
                '笔记 记 <内容>：作用=记一条笔记；参数=内容（必填，Markdown 原样存，#/## 三级标题可用；写「- [ ] 待办」的行按待办看待；可配图一起发，最多 4 张自动落盘）；内容=记下确认＋编号；意义=把事情交给我保管。',
                '笔记列表 / bijiliebiao：作用=列出本会话笔记；参数=无；内容=编号＋待办状态（□/☑）＋首行摘要；意义=盘点。',
                '笔记 看 N：作用=翻开第 N 条；参数=编号（必填）；内容=纯文本正文（标题保留 #，图片显示 [图片N]），配图原样补发；意义=回看。',
                '做完 N：作用=勾选第 N 条待办；参数=编号（必填）；内容=完成确认；自然语言也行——「作业做完了」会模糊匹配未完成提醒与笔记待办，命中即勾。',
                '删笔记 N：作用=删除第 N 条；参数=编号（必填）；内容=删除确认（配图一并清理）；意义=放下。',
                '笔记列表（筆記列表/bijiliebiao/bjlb）：作用=清单；参数=无；内容=编号＋状态＋摘要；意义=盘点。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  Markdown 笔记本：内容原样存储（#/## 三级标题、列表、勾选框），\n'
                '  按会话隔离（A 群看不到 B 群）；含「- [ ]」的笔记自动成为待办，\n'
                '  可被「做完 N」或自然语言勾选了结。\n'
                '【权限与效果】\n'
                '  权限=全员（bot_notes_enabled 可关）。单会话上限 bot_notes_max_per_chat\n'
                '  （默认 200），满了会提示先清理；数据库与图片经 runtime 路径落盘。\n'
                '【示例】笔记 记 周三要交总结（换行）- [ ] 写初稿｜笔记列表｜笔记 看 1｜做完 1｜删笔记 1｜作业做完了'
            ),
        },
        {
            "topic": '收件箱',
            "admin_only": False,
            "aliases": ('收件箱', 'inbox', 'shoujianxiang'),
            "index": '【收件箱】随手把事情丢进来：收件箱 <内容>｜收件箱',
            "title_line": '【收件箱】随手速记与早晚简报',
            "lines": [
                '收件箱 <内容>：作用=把待办/杂事记进收件箱文件；参数=内容（必填，≤2000 字）；内容=收录确认；意义=想到就丢，不用惦记。',
                '收件箱：作用=看当前攒着的事；参数=无；内容=编号清单；意义=盘点。',
                '定时：每天 09:00 早报整理收件箱并归档，21:00 晚报对账；到饭点还会随机推荐吃什么（BOT_DAILY_ASSIST_* 可调）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  收件箱是一份纯文本文件（bot_daily_assist_dir 下 inbox.md），\n'
                '  手机/电脑都能直接编辑；早报读取后归档到 daily/ 按日期存放。\n'
                '【权限与效果】\n'
                '  权限=全员（bot_daily_assist_enabled 可关）。定时推送目标只取\n'
                '  BOT_DAILY_ASSIST_PUSH_USER_IDS 名单，名单为空则只记不推。\n'
                '【示例】收件箱 周五前还信用卡｜收件箱 买猫粮｜收件箱'
            ),
        },
        {
            "topic": '语音',
            "admin_only": False,
            "aliases": ('语音', 'tts', 'yuyin', '语音合成', '說', '語音', '唸', '朗讀', '語音合成'),
            "index": '【语音】让我用声音念一段话：说 <文本>',
            "title_line": '【语音】用守岸人的声音念出来',
            "lines": [
                '说 <文本>：作用=把文本合成为守岸人音色的语音消息；参数=文本（必填，默认上限 200 字，BOT_TTS_MAX_CHARS=0 为不限）；内容=一段声音连同它所读的那串字（声音在前、文字在后，同一条消息里一起发出）；意义=让回复带上声音。',
                '语音 <文本>｜念 <文本>｜朗读 <文本>｜tts <文本>：触发词等价，繁體 說/語音/唸/朗讀/語音合成 同（正文保留繁體用字）；BOT_TTS_TRIGGER_WORDS 可自定义。',
                '对话自动配音：两闸串联才会发声——总闸 BOT_TTS_ENABLED 与自动配音闸 BOT_TTS_AUTO_REPLY_ENABLED 都得开着，人格回复才连同语音一起发出；范围由 BOT_TTS_AUTO_REPLY_SCOPE 决定（private/group/all）。',
                '配音走哪条腿：BOT_TTS_VOICE_HOOK_ENABLED 只选路、不是开关。开=新链，正文先过审再拿去合成，合成失败会留一条运营故障（进中央告警与诊断卡）；关=旧包装路径，失败就不带语音、正文照发，只在结果上留机读留痕。该键装配期读死，改后要重启。',
                '配音概率：默认有 10% 的回复会带语音（BOT_TTS_AUTO_REPLY_PROBABILITY）；BOT_TTS_AUTO_REPLY_ALWAYS=true 可临时改成条条都配，方便验收听音。',
                '长句拆条：BOT_TTS_AUTO_REPLY_SPLIT_MAX_CHARS>0 时，超字数自动按句末标点切成多条语音随同一条消息发出（0=不拆；语速 0.85 时 60 秒≈150~180 字）。',
                '预设与硬顶：合成参数以中央预设表为唯一缺省源（BOT_TTS_PRESET，其余数值键=管理员覆盖）；单次文本硬顶 2000 字、产物 8 MiB（BOT_TTS_HARD_MAX_CHARS / BOT_TTS_MAX_AUDIO_BYTES，超限拒绝并留痕）；群聊自动配音另受内容群白名单安全门约束（黑名单永远赢，白名单空=群面不配音绝不猜群）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  语音能力对接本机 GPT-SoVITS v2ProPlus 的 HTTP 接口（api_v2.py，默认 9880），\n'
                '  用你训练好的守岸人权重合成；文本不出本机，合成结果落运行时目录。\n'
                '【权限与效果】\n'
                '  权限=全员，前提是 BOT_TTS_ENABLED=true 且 9880 服务在跑。参考音频未配置、\n'
                '  服务未启动或超时，都会得到一句可读的降级文案而不是报错；引擎不可达时\n'
                '  会进入短暂退避冷却快速失败，不挂起消息。合成结果按内容+引擎身份缓存，\n'
                '  同一句话不重复合成（同句恒同音色）。\n'
                '  对话自动配音按概率触发（默认 5%），判定用确定性哈希——同一条消息结果\n'
                '  恒定，不会一会儿配一会儿不配。\n'
                '【示例】说 今天的潮汐很安静｜语音 我在这里｜tts hello'
            ),
        },
        {
            "topic": '帮助',
            "admin_only": False,
            "aliases": ('帮助', 'help', '菜单'),
            "index": '【帮助】查看功能总览与模块教程：/bot help｜/bot help <模块>',
            "title_line": '【帮助】功能总览与模块教程',
            "lines": [
                '/bot help：作用=按权限输出分类总览；参数=无；内容=管理员/大模型/子功能三类清单，每行附「/bot help <模块>」展开引导；意义=一切入口的入口。渲染成功发 Mica 卡，失败回纯文本。',
                '/bot help <模块>：作用=单模块深度页；参数=模块名或别名（如 /bot help 点歌、/bot help music）；内容=作用/参数/取值/权限四要素＋示例＋详细教程；意义=逐参数自助。',
                '权限=普通用户只见公开模块，管理员另见诊断与配置模块；查无此模块回「没有找到」并提示相近分类。',
                '/bot commands：作用=机器可读目录；参数=无；内容=路由表＋命令清单；意义=脚本对账。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  帮助系统自己也是一条命令：总览管「有什么」，深度页管「怎么用」，\n'
                '  机器可读目录 /bot commands 管「程序对账」。三者和 docs/command-catalog.md\n'
                '  共享同一份注册数据，改一处全端生效。\n'
                '【权限与效果】\n'
                '  权限=全员；可见范围按角色切换（非管理员查管理员模块会得到「没有找到」）。\n'
                '【示例】/bot help｜/bot help 点歌｜/bot help help'
            ),
        },
        {
            "topic": '聊天',
            "admin_only": False,
            "aliases": ('聊天', 'chat', '闲聊'),
            "index": '【聊天】和守岸人自然对话：群里 @点名，私聊直接说',
            "title_line": '【聊天】人格对话（不可显式调用，靠触发）',
            "lines": [
                '群聊：@机器人、昵称点名或直接写名字才会回；其余消息默认静默观察，自动接话开启时按概率抽签，且主动接话受好感门（好感档 ≥ 亲近）。',
                '私聊：白名单内直接发消息即可对话。',
                '边界：现实问题会联网检索（仅管理员可见 🔎 调试标记）；世界观问题走人格档案＋向量知识库。',
                '失败：私聊回守岸人话术提示，群聊保持静默不刷屏。',
                '无指令：作用=承接所有未命中路由的自然对话；参数=无；内容=人格化回复；意义=产品主体验。触发方式=@点名 / 昵称点名 / 私聊直说。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  聊天是兜底能力：没有任何「/bot chat」式命令，命中不了其他路由的\n'
                '  文本最终落到这里。它承载人格档案、向量知识库、世界观与好感语气。\n'
                '【权限与效果】\n'
                '  权限=全员（受群聊门禁与好感门约束）。回复经统一审查与渲染管线。\n'
                '【示例】（群里 @守岸人）今天状态怎么样？'
            ),
        },
        {
            "topic": '戳一戳',
            "admin_only": False,
            "aliases": ('戳一戳', 'poke'),
            "index": '【戳一戳】被戳回一个（六臂轮换）+ 跟戳 + 说完顺手戳（都有冷却）',
            "title_line": '【戳一戳】戳一戳互动回应',
            "lines": [
                '触发=QQ「戳一戳」头像互动；行为=按概率回应，默认有冷却防骚扰。',
                '被戳回一个（六臂确定性轮换，只出一个）：反戳 / 自然语言回复 / 语音+文本 / 表情包 / 随机图 / 固定话术；BOT_POKE_REPLY_MODE 显式指名任一臂，mix=轮换（扩臂要 BOT_POKE_EXTRA_ARMS_ENABLED=true，缺省停在旧三臂=旧行为）。',
                '跟戳：群里 A 戳 B 时按概率跟着戳 B；BOT_POKE_FOLLOW_ENABLED、BOT_POKE_FOLLOW_PROBABILITY、BOT_POKE_FOLLOW_COOLDOWN_SECONDS、BOT_POKE_FOLLOW_MAX_PER_HOUR（缺省关；独立于回戳的冷却与每小时账）。',
                '说完顺手戳：bot 回复完、群内主动接话、入群欢迎之后按概率戳一下对方；BOT_POKE_AFTER_REPLY_ENABLED、_PROBABILITY、_COOLDOWN_SECONDS、_MAX_PER_HOUR（缺省关）。',
                '硬门：安静时间窗内、blocked 名单里的人一律不戳也不主动发图——拨开概率开关也越不过这两道。',
                '语音臂复用 bot.tts 那条「文本+语音」能力（BOT_TTS_ENABLED 且引擎在线才有声，合成不成只留文本腿）；随机图臂吃 BOT_RANDPIC_DIRS（图库空则温和回退固定话术，绝不静默空回）。',
                '可调：BOT_POKE_ENABLED（开关）、BOT_POKE_*_COOLDOWN_SECONDS（冷却）、BOT_POKE_PROBABILITY（概率）。',
                '权限=全员；无文字命令，属互动事件。',
                '无指令：作用=头像互动回应与轻量主动接触；参数=无；内容=六臂之一（一句回应 / 语音+文本 / 一张图 / 回戳）；意义=轻互动。配置经 .env 或 /bot runtime set（可写键以 runtime 白名单为准，本族多为改 .env+重启）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  戳一戳是轻量互动：群友戳机器人头像，机器人按概率回应一个表达。\n'
                '  冷却与概率防止连戳刷屏。P14 波把「回应」扩成六臂矩阵，并补了\n'
                '  跟戳（A 戳 B 时跟着戳）与「说完话顺手戳一下」两条主动腿。\n'
                '【取值范围】\n'
                '  BOT_POKE_REPLY_MODE：fixed/llm/meme/voice/randpic/poke 六值显式指名，\n'
                '  或 mix=按 (会话,戳者,时间桶) 的 SHA-256 摘要确定性轮换（同戳同果，\n'
                '  不用随机数）；轮换池缺省三臂，BOT_POKE_EXTRA_ARMS_ENABLED=true 才扩到六臂。\n'
                '  概率类键取值 0..1；冷却与每小时上限各自独立记账。\n'
                '【权限与效果】\n'
                '  权限=全员。开关关闭时戳一戳无任何回应；安静时间窗与 blocked 名单\n'
                '  是硬门，主动腿（跟戳/说完顺手戳/主动发图）全部缺省关。\n'
                '【示例】戳一戳守岸人的头像 → 有概率收到回应（话术 / 语音 / 一张图 / 被戳回来）'
            ),
        },
        {
            "topic": '表情收库',
            "admin_only": False,
            "aliases": ('表情收库', '表情库', 'biaoqingku', 'bqk'),
            "index": '【表情收库】群聊图片自动入库，成为「偷表情」的弹药库',
            "title_line": '【表情收库】表情包自动收集（监听生效，无命令）',
            "lines": [
                '行为：监听群聊图片，自动异步下载、MD5 去重、≤5MB 入库，SQLite 记元数据。',
                '筛选：权重打分（守岸人×8 → 鸣潮/战双/库洛×4 → ACG×1.5 → 普通×1；非表情×0.25）；NSFW≥0.2 降权、≥0.8 永不发送；可选 VLM 自动打标。',
                '消费：用「偷表情 [关键词]」加权随机抽取，用「表情库统计」看库存；本模块自身无命令、靠监听生效。',
                '本模块无命令：作用=自动收库；参数=无；内容=群图异步入库（不直接回复）；意义=偷表情的弹药库。库存操作入口：偷表情｜表情库统计（见「偷表情」模块）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  表情收库是「偷表情」的后勤：群友发的图自动攒成表情库，机器人\n'
                '  心情低时还会偏向发吵闹梗。工程上有冷却、群黑白名单与 LRU 上限。\n'
                '【权限与效果】\n'
                '  权限=全员（被动机制）。下载绝不阻塞消息主链路。\n'
                '【示例】群里发一张表情图 → 自动入库 → 之后「偷表情」可能抽到它'
            ),
        },
        {
            "topic": '自然语言',
            "admin_only": False,
            "aliases": ('自然语言', '自然语言命令'),
            "index": '【自然语言】不用记命令，直接说话：帮我查杭州天气/来首晴天/今天有什么免费游戏',
            "title_line": '【自然语言】一句话归一成命令',
            "lines": [
                '天气：帮我查一下杭州天气｜杭州天气怎么样 → 「天气 杭州」。',
                '点歌：来首晴天｜放首歌 晴天｜帮我放一首周杰伦的歌 → 「点歌 …」。',
                '维基：帮我查维基 鸣潮 → 「wiki 鸣潮」；Epic：今天有什么免费游戏 → 「epic」。',
                '历史上的今天：今天历史上发生了什么 → 「历史上的今天」；偷表情：来张表情包 → 「偷表情」。',
                '未命中自然语言意图的文本会正常落入人格聊天，不会报错。',
                '无固定指令：作用=把口语归一成标准命令；参数=自然语言本身；内容=命中后按目标模块回复；意义=零记忆成本。查询类动词：帮我/麻烦/请/查一下/看看/告诉我…',
            ],
            "detail": (
                '【板块介绍】\n'
                '  自然语言层（priority 45）把口语说法归一成标准命令再进对应模块，\n'
                '  带城市黑名单与禁词保护，避免把「天气真好」当成天气查询。\n'
                '【权限与效果】\n'
                '  权限=全员。命中后按目标模块的权限与门禁执行。\n'
                '【示例】帮我查杭州天气｜来首晴天｜今天有什么免费游戏'
            ),
        },
        {
            "topic": '忽略',
            "admin_only": True,
            "aliases": ('忽略', 'ignore'),
            "index": '【忽略】哪些消息静默不回、未知命令会引导（排障「为什么不回我」）',
            "title_line": '【忽略】静默路由、沉默原因与未知指令引导',
            "lines": [
                '空消息/无有效文本 → IGNORE，不回复。',
                '命令形态（/ 开头等）但没命中任何能力 → 回一句守岸人引导，指路 /bot help；同一会话 60 秒内只提醒一次，防刷屏。普通闲聊不受影响。',
                '群聊非命令、非 @点名、非昵称点名 → passive 静默观察；自动接话开启时按概率抽签，且受好感门（≥ 亲近）。',
                '安静时间窗内、限流句数帽超帽、群策略 black1 → 静默拦截（黑名单完全只收不发）。',
                '排障路径：/bot status 看姿态 → /bot why <id> 看单条决策 → 本模块理解沉默语义。',
                '无专属命令：作用=解释沉默与引导；参数=无；内容=空消息静默（按设计），未知命令形态回一句引导；意义=区分按设计沉默与真异常。相关诊断：/bot status、/bot why、/bot route <文本>（route 会直接告诉你这段文本命中哪条路由）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  「忽略」是路由兜底语义：机器人不回 ≠ 出故障，多数沉默是门禁与\n'
                '  策略按设计工作。唯一例外：命令形态（/ 开头等）没命中任何能力时，\n'
                '  会回一句守岸人引导指路 /bot help（60 秒/会话节流）。本模块帮助\n'
                '  管理员区分「按设计沉默」与「真异常」。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（排障语义）。\n'
                '【示例】/bot route 今天天气不错 → 显示 chat 路由（正常回复场景）'
            ),
        },
        {
            # 审查 P-03：决策影子痕迹查询的命令入口与帮助页（消费侧闭环）。
            "topic": '决策',
            "admin_only": True,
            "aliases": ('决策', '决策引擎', 'decision'),
            "index": '【决策】影子决策引擎痕迹查询：/bot decision [N]',
            "title_line": '【决策】查看影子决策引擎的路由分歧痕迹',
            "lines": [
                '/bot decision [N]：作用=查看影子决策引擎最近 N 条痕迹；参数=N（缺省 20，范围 1-100）；内容=时间/路由类别/引擎判定与现行判定/一致或分歧/耗时，自由文本字段打码截断，不含消息原文；意义=评估中央决策引擎接管前的分歧率（痕迹已落盘，重启可查历史）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  影子决策引擎（BOT_DECISION_ENGINE_MODE=shadow）对每条经过管线\n'
                '  的事件只算不发，与现行 matcher 的裁决做比对。本页把比对痕迹\n'
                '  读出来给管理员看：分歧集中在哪类路由、引擎与现行差在哪，是\n'
                '  接管评估（阶段 1+）的核心依据。痕迹经 SQLite 落盘，热缓冲只\n'
                '  是短程补充，重启后仍可查询历史。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（普通成员发送会收到拒绝提示）。\n'
                '  影子模式默认关闭（legacy_only）：模式下无痕迹属预期，不是故障。\n'
                '【示例】/bot decision ｜ /bot decision 50'
            ),
        },
        {
            # WIRE-B1（2026-09-21 紧急信息接线波）：admin_only=True 为用户裁定 U-3，
            # 投递面上线前不进 _PUBLIC_HELP_TOPICS；装配半边归 B2。
            "topic": '紧急信息',
            "admin_only": True,
            "aliases": ('紧急信息', '预警', '地震', '震情', '待审', 'emergency', '緊急信息', '預警'),
            "index": '【紧急信息】外部紧急信息聚合（仅管理员）：紧急信息｜紧急信息 订阅 <条件>｜紧急信息 待审｜紧急信息 审核 <id> 通过',
            "title_line": '【紧急信息】外部紧急信息的采集、定级、人工审核与按群订阅投递',
            "lines": [
                '紧急信息：作用=查看当前已批准的紧急信息与等级；参数=可选 城市/等级；内容=红橙黄蓝四档 + 来源与时效标注（无源不编数）；意义=一眼分清哪些是真在报。',
                '紧急信息 订阅 area=<地名> kinds=<警情词> levels=<P0,P1 或 橙色以上> radius=<km>：作用=给本群（或私聊给自己）设一条投递条件，只推对得上的条目；参数=四项都可选，缺省即不筛该维，半径缺省 200km、只对带坐标的条目（震情类）生效；内容=一个目标只留一条规则，再说一句即改口，写完当轮生效不重启，地名不在气象码表里会当场点名并给相近候选；意义=推什么由群里说了算，不必经 .env 预填名单。',
                '紧急信息 订阅 看：作用=查本目标当前的条件与累计命中次数；参数=无；内容=从没命中过会直说，不让你猜是不是配错了；意义=「配了不生效」这件事必须自己开口。',
                '紧急信息 退订：作用=撤掉本目标这条订阅；参数=无；内容=退订后一条都不再推，重设即恢复；意义=退出只要一句话。',
                '紧急信息 待审：作用=列人工报料的待审队列；参数=可选 条数；内容=仅管理员，pending 条目不参与投递也不参与定级；意义=报料先审后发。',
                '紧急信息 审核 <id> 通过|驳回：作用=裁决一条报料；参数=item id + 通过/驳回；内容=只改 pending，二次裁决直说已被别人裁过；意义=审核留痕可追。',
                '边界（诚实降级）：中央投递闸未装配=照采照查但一条都不投；源未给失效时间就不假装知道有效期；未定级条目不冒充任何颜色、也一律不投；只有地名没有坐标的条目不拿半径硬凑命中（宁漏不误投）；等级≠卡片色值（色走 theme_tokens）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  外部紧急信息（NMC 预警 / GDACS / 公开震情等来源）采集→定级→去重→\n'
                '  人工审核批准后，才经中央投递闸投出去；查询面只见已批准条目。\n'
                '  投递目标由「紧急信息 订阅 …」在群里/私聊里现场设立并现读生效，\n'
                '  条件（地点·警情·等级·半径）不落 .env；.env 的两个名单降级为可选硬推腿。\n'
                '  作用=聚合外部紧急信息；意义=漏报比误报贵，所以先审再投、再按订阅筛。\n'
                '【权限与效果】查询与审核=管理员（审核人名单 BOT_EMERGENCY_INFO_REVIEWER_IDS，名单空=审核面关闭，缺省拒绝）；\n'
                '  设/退订阅=超级管理员、管理员或本群群主（仅 QQ 侧；别的平台的号存下来会送错地方，故不收）。\n'
                '【示例】紧急信息｜紧急信息 订阅 area=湘潭 kinds=暴雨 橙色以上｜紧急信息 订阅 看｜紧急信息 退订｜紧急信息 待审'
            ),
        },
        {
            "topic": '亲密模式',
            "admin_only": False,
            "aliases": ('亲密模式', '亲密档位', 'intimate', 'qinmimoshi'),
            "index": '【亲密模式】整句开关：亲密模式 开|深开|关｜关系档自助设定：/bot identity set-relation|unset-relation|show-relation',
            "title_line": '【亲密模式】这一阵用什么语气相处，你们自己说（整句开关＋关系档）',
            "lines": [
                '亲密模式 开（同义：亲密模式开／开启亲密模式／打开亲密模式／亲密模式 on）：作用=把当前会话上到亲密档的**浅档**（只给关系语气，不改默认模型）；参数=无（整句才算命令，句子中间带这几个字不算）；内容=一句守岸人语气的确认；意义=想被更柔软地对待就说一句，不必念名单。',
                '亲密模式 深开（同义：亲密模式 开 深／亲密模式 开 二档／亲密模式 开 grok／二档／深档）：作用=浅档之上再允许把首跳换到在册的成人内容通道（grok 优先）；参数=无（整句才算命令，三条深档判据先于浅档匹配）；内容=深档确认一句；意义=「档成立」与「该换模型」自此分家——要哪种自己说。',
                '亲密模式 关（同义：亲密模式关闭／解除亲密模式／亲密模式 off）：作用=深浅两档一起解除；参数=无；内容=回到平时语气的确认；意义=说完就撤，不粘着。',
                '自动退出：作用=亲密档从**激活那一刻**起 60 分钟后自然退出；参数=BOT_CONTENT_ROUTE_INTIMATE_TTL_MINUTES（.env+重启）；内容=会话活跃不续期、再说一次「开」即重置；意义=不会有哪句话把你永久钉在亲密档上。',
                '好感度自动进浅档：作用=相处到某一档的人不必开口也拿到浅档语气；参数=BOT_CONTENT_ROUTE_L1_AUTO_ENABLED（总闸）/ BOT_CONTENT_ROUTE_L1_AUTO_MIN_TIER（门槛档号，真身 character/affinity.py 的 _ATTITUDE_TIERS）；内容=只给档、不换模型，与 Master Love 同类；意义=亲密语气不该只发给名单里那两位。两枚改 .env 后要重启（合并层未登记，/bot runtime set 明确拒绝）。',
                '/bot identity set-relation <关系>：作用=告诉守岸人你们是什么关系，让这一档有具体的形状；参数=受控词表内的关系或其口语别名（词表与每档语气指令的真身=character/relationships.py，本册零抄录）；内容=已记下的档号；意义=同一句「亲密模式 开」，关系不同语气就该不同；词表外的值不落档也不清档，并把整张词表回给你。',
                '/bot identity unset-relation：作用=只清关系档那一列；参数=无；内容=已清除（带原先记的档号）；意义=称谓偏好与性别自述不受牵连——这与 unset-name 的整行删除是两件事。',
                '/bot identity show-relation：作用=看自己当前的关系档；参数=无；内容=档号，或明说「没设定过，按相处深浅自然来」；意义=先核对再改，不靠猜。',
                '权限=全员：任何人对自己说一句就生效，无需管理员。群聊里成员说的只对自己（个人档），要把整群钉上得管理员；群聊整面还受黑白名单约束（白名单为空=整群关闭，绝不猜群；黑名单永远赢）。',
                '硬线：内容放行面不因关系档而改变，仍由会话门 explicit_allowed_for_session 判；六条硬线任何关系、任何开关、任何设定都压不过（security/content_safety.py）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  亲密档=「这一阵用什么语气相处」的会话状态，分深浅两档：浅档只改称呼、\n'
                '  语气与投入度；深档才允许把首跳换到在册的成人内容通道。档**为什么**成立只\n'
                '  记一处（runtime/content_route.py 的 pin_source）：本人显式开关、管理员钉、\n'
                '  内容信号三类有权换模型，Master Love 与好感度自动腿属于「给档不换模型」。\n'
                '  关系档（恋人/情侣/夫妻/长辈/晚辈/家人/挚友/master…）给这一档具体的形状。\n'
                '【取值范围】\n'
                '  档位=浅(l1)/深(l2)；退出=一句「亲密模式 关」或 60 分钟 TTL 自然退出（按\n'
                '  激活时刻起算、活跃不续期、重开即重置）；显式钉与管理员钉不再被第二道\n'
                '  max_ttl 悄悄截掉（2026-09-24 裁定 R4 A）。关系档取值由受控词表决定，\n'
                '  词表外一律不落档；同时命中两档按歧义不记录，不替谁编一个方向。\n'
                '【权限与效果】\n'
                '  权限=全员（任何人对自己拨）。会话准入门链：总闸 BOT_CONTENT_ROUTE_ENABLED\n'
                '  → 私聊/群聊黑白名单（私聊白名单空=放开、群聊白名单空=整群关闭，刻意不对称；\n'
                '  黑名单永远赢）→ 群内成员个人档总闸 BOT_CONTENT_ROUTE_GROUP_PER_USER_ENABLED。\n'
                '  只改变称呼与投入度，不推翻任何既有的身份与称谓事实；六条硬线压不过。\n'
                '【示例】亲密模式 开｜亲密模式 深开｜亲密模式 关｜/bot identity set-relation 恋人'
            ),
        },
    ]

# 结构化元数据侧表：运行时（下方合并循环）与 scripts/command_catalog.py 的静态
# 提取共享同一份数据，防止帮助页与命令目录漂移。只登记有条目文本或项目文档依据的事实。
# S38（P-S28-1）单源常量：下面两枚串原为 META 内各手抄 13/5 枚的同串值，提为模块级
# 常量后 META 数据段与 command_catalog 的静态取数读同一份（后者自 S38 起支持解析同模块
# 模块级常量引用）。字符串值与本行落地前的今日口径逐字相同，运行期与目录产物零变更。
_CHAT_SCOPE_CONSISTENT = "群聊/私聊行为一致（无会话分支）"
_FALLBACK_RENDER_TEXT = "渲染失败回退纯文本"
_HELP_ENTRY_META: dict[str, dict[str, Any]] = {
    "功能管理": {
        "capability": "bot.runtime（/bot feature）", "network": False, "outputs": ("文本",),
        "config_vars": ("BOT_CONTROL_PLANE_FEATURES_DB",),
        "examples": ("/bot feature get bot.plugin.weather",),
        "tests": ("tests/test_runtime_feature_gate.py",),
    },
    "状态": {
        "capability": "bot.status",
        "triggers_nickname": ("状态", "狀態", "status", "查询"),
        "examples": ("/bot status",),
        "tests": ("tests/test_bot_commands_catalog_b10.py",),
    },
    "记忆": {
        "capability": "bot.memory",
        "network": False,
        "outputs": ("文本",),
        "triggers_nickname": ("记忆", "memory"),
        "chat_scope": "私聊=全部个人记忆；群聊=仅 public/group 两级，防止个人私事被围观",
        "config_vars": ("BOT_MEMORY_ENABLED", "BOT_MEMORY_DB_PATH"),
        "examples": ("/bot memory add 我对芒果过敏 --sensitivity=group",),
        "tests": ("tests/test_memory_router_reuse.py", "tests/test_memory_sanitize.py"),
    },
    "为什么": {
        "capability": "bot.why",
        "triggers_nickname": ("为什么", "为啥", "why"),
        "examples": ("/bot why｜/bot why help_8f2a1b3c",),
    },
    "回执": {
        "capability": "/bot receipt",
        "outputs": ("文本",),
        "config_vars": ("BOT_RECEIPTS_ENABLED",),
        "examples": ("/bot receipt 7c9f…（用 /bot recent 里出现的 id）",),
    },
    "审计": {
        "capability": "/bot audit",
        "outputs": ("文本",),
        "config_vars": ("BOT_AUDIT_ENABLED",),
        "examples": ("/bot audit music_9a3bb2",),
    },
    "最近": {
        "capability": "/bot recent",
        "outputs": ("文本",),
        "examples": ("/bot recent 10",),
    },
    "队列": {
        "capability": "/bot queue",
        "outputs": ("文本",),
        "config_vars": ("BOT_SEND_QUEUE_ENABLED",),
        "examples": ("/bot queue",),
        "tests": ("tests/test_part_idempotent_resume.py", "tests/test_queue_poison_row.py", "tests/test_auditfix_sender_queue.py"),
    },
    "上下文": {
        "capability": "/bot context",
        "network": True,
        "outputs": ("文本",),
        "examples": ("/bot context 鸣潮的守岸人是谁",),
    },
    "对话": {
        "capability": "bot.dialogue",
        "network": True,
        "outputs": ("文本诊断",),
        "triggers_nickname": ("对话验收", "dialogue"),
        "examples": ("/bot dialogue 今天状态怎么样",),
    },
    "接入": {
        "capability": "/bot setup llm",
        "network": False,
        "outputs": ("Mica 配置卡",),
        "html_image": True,
        "fallback": _FALLBACK_RENDER_TEXT,
        "config_vars": ("BOT_CHAT_PROVIDER",),
        "examples": ("/bot setup llm",),
    },
    "配置": {
        "capability": "bot.config",
        "network": False,
        "outputs": ("文本",),
        "triggers_nickname": ("配置", "config"),
        "examples": ("/bot config",),
    },
    "就绪": {
        "capability": "bot.readiness",
        "network": False,
        "outputs": ("文本",),
        "triggers_nickname": ("就绪", "readiness"),
        "examples": ("/bot readiness",),
    },
    "角色": {
        "capability": "bot.roles",
        "network": False,
        "outputs": ("文本",),
        "triggers_nickname": ("角色", "roles"),
        "config_vars": ("BOT_ADMIN_USER_IDS", "BOT_TELEGRAM_ADMIN_USER_IDS"),
        "examples": ("/bot roles",),
        "tests": ("tests/test_admin_roster_and_roles.py",),
    },
    "人格": {
        "capability": "bot.persona",
        "network": False,
        "outputs": ("文本",),
        "triggers_nickname": ("人格", "persona"),
        "examples": ("/bot persona",),
    },
    "路由": {
        "capability": "/bot route",
        "network": False,
        "outputs": ("文本",),
        "examples": ("/bot route 点歌 晴天",),
    },
    "历史": {
        "capability": "bot.history",
        "network": False,
        "outputs": ("文本",),
        "triggers_nickname": ("清理历史", "历史", "history"),
        "examples": ("/bot history clear",),
    },
    "暂停": {
        "capability": "bot.control",
        "network": False,
        "outputs": ("文本",),
        "triggers_nickname": ("暂停", "暫停", "pause", "继续", "繼續", "resume"),
        "examples": ("/bot pause → 维护 → /bot resume",),
    },
    "回复": {
        "capability": "/bot reply",
        "network": False,
        "outputs": ("文本",),
        "config_vars": ("BOT_REPLY_DETAIL", "BOT_CHAT_MAX_TOKENS", "BOT_CHAT_FAST_MODE"),
        "examples": ("/bot reply 详细",),
    },
    "模型": {
        "capability": "/bot model",
        "triggers_nickname": ("切换模型", "渠道"),
        "network": True,
        "config_vars": ("BOT_MODEL_SCHEDULE", "BOT_MODEL_PRIORITY_GROUPS"),
        "examples": ("/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1",),
        "tests": ("tests/test_model_admin_and_schedule.py", "tests/test_model_router_failover.py"),
    },
    "用量": {
        "capability": "/bot model usage",
        "network": False,
        "outputs": ("文本＋Mica 账单卡",),
        "html_image": True,
        "fallback": _FALLBACK_RENDER_TEXT,
        "config_vars": ("BOT_USAGE_ALERT_INPUT_TOKENS", "BOT_USAGE_ALERT_OUTPUT_TOKENS", "BOT_USAGE_ALERT_DAILY_COST_YUAN", "BOT_USAGE_REPORT_HOURS"),
        "examples": ("/bot model usage 2026-09-01",),
        "tests": ("tests/test_llm_ledger.py", "tests/test_model_effort_groups_and_pricing.py"),
    },
    "设置": {
        "capability": "/bot runtime",
        "triggers_nickname": ("設置", "參數"),
        "config_vars": (
            "BOT_REPLY_DETAIL", "BOT_CHAT_MAX_TOKENS", "BOT_CHAT_FAST_MODE", "BOT_CHAT_REASONING_EFFORT",
            "BOT_MODEL_PRICES", "BOT_MODEL_SCHEDULE", "BOT_MODEL_PRIORITY_GROUPS", "BOT_VISION_ENABLED",
            "BOT_QUIET_HOURS_ENABLED", "BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR", "BOT_GROUP_CHAT_AUTO_REPLY_ENABLED",
        ),
        "examples": ("/bot runtime set BOT_QUIET_HOURS_ENABLED true",),
        "tests": ("tests/test_help_entries_coverage.py",),
    },
    "搜索": {
        "capability": "/bot search",
        "outputs": ("文本（标题/摘要/链接列表）",),
        "network": True,
        "config_vars": ("BOT_WEB_SEARCH_MAX_RESULTS",),
        "examples": ("/bot search 守岸人是什么游戏的角色",),
        "tests": ("tests/test_search_api_providers.py",),
    },
    "解析": {
        "capability": "/bot parse",
        "network": False,
        "outputs": ("文本",),
        "chat_scope": "解析历史是全局范围（跨群/跨私聊），因此仅管理员可见",
        "examples": ("/bot parse 20",),
        "tests": ("tests/test_parse_presentation_v2.py",),
    },
    "凭据": {
        "capability": "/bot cookie",
        "network": True,
        "outputs": ("文本；cookie login 另含二维码图",),
        "chat_scope": "cookie 过期会私聊推送管理员告警",
        "triggers_nickname": ("凭证", "憑證", "憑據", "登录凭证", "登錄憑證"),
        "examples": ("/bot cookie import bilibili SESSDATA=...; bili_jct=...",),
        "tests": ("tests/test_cookie_import_hot_reload.py", "tests/test_platform_credentials.py"),
    },
    "群策略": {
        "capability": "/bot group",
        "chat_scope": "作用于群聊门禁：black1=完全静默只收不发；black2=只回「@且带指令」",
        "config_vars": ("BOT_GROUP_BLACK1",),
        "examples": ("/bot group add white1 123456789 987654321",),
        "tests": ("tests/test_group_policy.py",),
    },
    "群文件": {
        "capability": "/bot 群文件",
        "network": False,
        "outputs": ("文本",),
        "chat_scope": "仅群聊可用（统计当前群；私聊提示不可用）",
        "examples": ("/bot 群文件",),
    },
    "日志": {
        "capability": "bot.logs",
        "network": False,
        "outputs": ("文本",),
        "triggers_nickname": ("日志", "logs", "查询日志"),
        "examples": ("/bot logs error 20",),
    },
    "文件": {
        "capability": "matcher:admin_file_export（文件导出）",
        "network": True,
        "fallback": "LLM 失败/转换失败/上传失败均回文本报错",
        "outputs": ("文件",),
        "examples": ("文件 docx 鸣潮 2.0 版本角色梯度整理",),
        "tests": ("tests/test_file_exchange.py", "tests/test_file_gateway_phase1.py"),
    },
    "身份": {
            "capability": "/bot identity",
            "network": False,
            "outputs": ("文本",),
        "chat_scope": "在哪个群/私聊执行就对哪个会话生效，各会话互不影响",
        "config_vars": ("BOT_SESSION_IDENTITY_DB_PATH",),
        "examples": ("/bot identity set 岸宝｜/bot identity tag 早起,秃头,干饭人",),
    },
    # 亲密模式（2026-09-24 R1/R2/R3/R4 裁定的门面）：tests 只登记**今天在盘上**的
    # 回归件——`test_meta_test_paths_exist` 对不存在的路径直接判红，把另两枚
    # （tests/test_intimate_tier_wiring_v4.py、tests/test_relationships.py）写进来
    # 等于本席凭空造两条红。它们落地后由收口席补登记（同先例见 S38/T84 的补录口径）。
    "亲密模式": {
        "capability": "bot.chat（整句「亲密模式 开/深开/关」；关系档子命令见 /bot identity）",
        "network": False,
        "chat_scope": "私聊按本人；群聊成员说的只对自己（个人档），管理员拨上去的才是整群钉",
        "triggers_nl": ("亲密模式 开", "亲密模式 深开", "亲密模式 关"),
        "config_vars": (
            "BOT_CONTENT_ROUTE_ENABLED",
            "BOT_CONTENT_ROUTE_INTIMATE_TTL_MINUTES",
            "BOT_CONTENT_ROUTE_L1_AUTO_ENABLED",
            "BOT_CONTENT_ROUTE_L1_AUTO_MIN_TIER",
            "BOT_CONTENT_ROUTE_GROUP_PER_USER_ENABLED",
            "BOT_CONTENT_ROUTE_GROUP_WHITELIST",
            "BOT_CONTENT_ROUTE_GROUP_BLACKLIST",
            "BOT_CONTENT_ROUTE_PRIVATE_WHITELIST",
            "BOT_CONTENT_ROUTE_PRIVATE_BLACKLIST",
        ),
        "examples": (
            "亲密模式 开", "亲密模式 深开", "亲密模式 关",
            "/bot identity set-relation 恋人", "/bot identity show-relation",
        ),
        "tests": ("tests/test_intimate_tiers_v4.py",),
        "outputs": ("文本确认（语气与首跳资格的变化，不改内容放行面）",),
    },
    "怪癖": {
        "capability": "/bot quirk",
        "network": False,
        "outputs": ("文本",),
        "config_vars": ("BOT_QUIRKS_ENABLED",),
        "examples": ("/bot quirk list pending → /bot quirk approve 3fa2",),
        "tests": ("tests/test_quirks.py",),
    },
    "限流": {
        "capability": "/bot runtime set（配置型模块，无独立命令）",
        "outputs": ("无直接输出（配置型模块）",),
        "chat_scope": "群聊门禁：安静时间、句数帽、情绪豁免、自动接话",
        "config_vars": (
            "BOT_QUIET_HOURS_ENABLED", "BOT_QUIET_HOURS_START", "BOT_QUIET_HOURS_END", "BOT_QUIET_HOURS_TIMEZONE",
            "BOT_QUIET_HOURS_SESSION_TYPES", "BOT_QUIET_HOURS_BYPASS_ROLES", "BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR",
            "BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE", "BOT_RATE_LIMIT_EMOTION_EXEMPT",
            "BOT_GROUP_CHAT_AUTO_REPLY_ENABLED", "BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY",
        ),
        "examples": ("/bot runtime set BOT_QUIET_HOURS_START 01:00",),
        "tests": ("tests/test_group_rate_limit.py", "tests/test_sqlite_rate_limit_group.py", "tests/test_policy_sender_interval.py"),
    },
    "合并转发": {
        "capability": "/bot runtime set（配置型模块，无独立命令）",
        "network": False,
        "outputs": ("无直接输出（配置型模块）",),
        "config_vars": ("BOT_RENDER_FORWARD_MIN_NODES", "BOT_RENDER_FORWARD_MIN_CHARS", "BOT_RENDER_FORWARD_MAX_NODES", "BOT_RENDER_FORWARD_NODE_CHARS"),
        "examples": ("/bot runtime set BOT_RENDER_FORWARD_MIN_NODES 3",),
    },
    "群摘要": {
        "capability": "/bot runtime set（配置型模块，无独立命令）",
        "outputs": ("每日定时推送文本摘要",),
        "network": True,
        "chat_scope": "面向群聊：每日定时向摘要白名单群推送（非白名单零推送）",
        "config_vars": (
            "BOT_GROUP_DIGEST_LIST_MODE", "BOT_GROUP_DIGEST_WHITELIST", "BOT_GROUP_DIGEST_BLACKLIST",
            "BOT_GROUP_DIGEST_LLM_ENABLED", "BOT_GROUP_DIGEST_MAX_CHARS", "BOT_GROUP_DIGEST_MAX_TURNS",
            "BOT_GROUP_DIGEST_PUSH_ENABLED", "BOT_GROUP_DIGEST_PUSH_TIME", "BOT_SHARED_GROUP_CONTEXT_ENABLED",
        ),
        "examples": ("/bot runtime set BOT_GROUP_DIGEST_LIST_MODE whitelist",),
        "tests": ("tests/test_group_digest_push.py", "tests/test_shared_group_digest_list.py"),
    },
    "视频理解": {
        "capability": "/bot runtime set（配置型模块，无独立命令）",
        "outputs": ("随回复注入理解结果",),
        "network": True,
        "config_vars": (
            "BOT_VISION_ENABLED", "BOT_VISION_MODE", "BOT_VIDEO_UNDERSTANDING_ENABLED", "BOT_VIDEO_DEEP_ENABLED",
            "BOT_VIDEO_MAX_FRAMES", "BOT_VIDEO_FUZZY_FOLLOWUP", "BOT_VIDEO_PROGRESS_ACK_ENABLED",
            "BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE", "BOT_VISION_REPLY_PROBABILITY",
        ),
        "examples": ("/bot runtime set BOT_VISION_MODE relay",),
        "tests": ("tests/test_video_understanding.py", "tests/test_video_seam.py"),
    },
    "运行开关": {
        "capability": ".env（持久化开关，改后重启生效，无运行时命令）",
        "network": False,
        "outputs": ("无直接输出（.env 开关）",),
        "config_vars": ("BOT_SEND_QUEUE_ENABLED", "BOT_SEND_QUEUE_WORKER_ENABLED", "BOT_AUDIT_ENABLED", "BOT_RECEIPTS_ENABLED", "BOT_DIAGNOSTICS_ENABLED", "BOT_SEND_QUEUE_MAX_ITEMS"),
        "examples": (".env 里 BOT_AUDIT_ENABLED=true 后重启。",),
    },
    "邮件": {
        "capability": "on_command:mail",
        "outputs": ("文本确认",),
        "network": True,
        "examples": ("/mail send someone@example.com | 测试 | 这是一封测试邮件",),
        "tests": ("tests/test_mail_bridge.py", "tests/test_mail_adapter_resilience.py"),
    },
    "Telegram": {
        "capability": ".env（Telegram 适配器配置）",
        "outputs": ("跨平台消息/提醒",),
        "network": True,
        "config_vars": ("BOT_TELEGRAM_ADMIN_USER_IDS", "BOT_TELEGRAM_ADMIN_CHAT_IDS"),
        "examples": ('TELEGRAM_BOTS=["123456:ABC-DEF..."]',),
        "tests": ("tests/test_telegram_parser_v2.py", "tests/test_telegram_media.py"),
    },
    "供应商": {
        "capability": ".env（模型注册表；/bot model 亦可视图）",
        "network": False,
        "outputs": ("配置视图（.env/模型注册表）",),
        "config_vars": ("BOT_MODEL_REGISTRY", "BOT_CHAT_FAST_MAX_CANDIDATES"),
        "examples": ('BOT_MODEL_REGISTRY={"myapi":{"model":"deepseek-v4-pro","base_url":"https://api.xxx.com/v1","api_key":"env:MY_KEY","group":"g1","priority":1}}',),
        "tests": ("tests/test_chat_provider_chain.py",),
    },
    "订阅": {
        "capability": "bot.subscribe",
        "triggers_nickname": ("订阅", "訂閱", "subscribe", "查询订阅"),
        "network": True,
        "chat_scope": "群内 add/list 需管理员且推往本群，pause/resume/remove 群内需管理员；私聊添加=推给自己",
        "examples": ("/订阅 add https://space.bilibili.com/123456",),
        "tests": ("tests/test_subscribe_capability_v2.py", "tests/test_subscription_delivery_v2.py"),
    },
    "点歌": {
        "capability": "bot.music / bot.music_mode",
        "chat_scope": "群聊/私聊行为一致（会话仅用作统计 scope/候选键）",

        "triggers_nickname": ("点歌", "點歌", "点唱", "點唱", "music", "点歌模式"),
        "network": True,
        "triggers_nl": ("点歌 <歌名>", "来一首", "来首", "放一首", "播放 <歌名>", "唱一首歌"),
        "outputs": ("卡片图/文本/语音（按点歌模式组合）",),
        "html_image": True,
        "fallback": _FALLBACK_RENDER_TEXT,
        "config_vars": ("BOT_MUSIC_MODE", "BOT_MUSIC_CANDIDATES_ENABLED", "BOT_MUSIC_CANDIDATES_LIMIT", "BOT_MUSIC_CANDIDATES_TTL_SECONDS"),
        "examples": ("点歌 晴天｜点歌 2｜点歌模式 卡片+语音",),
        "tests": ("tests/test_music_capability_analytics_v2.py", "tests/test_music_candidates_card.py", "tests/test_music_charts_real_sources_v2.py"),
    },
    "表情": {
        "capability": "bot.meme",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,

        "network": False,
        "triggers_nickname": ("表情製作", "表情包製作", "表情產生", "表情包產生", "表情制作", "表情包制作", "表情产生", "表情包产生"),
        "triggers_nl": ("表情 <模板> <文字>", "表情帮助"),
        "outputs": ("图片",),
        "config_vars": ("BOT_MEME_COMMAND_ENABLED",),
        "examples": ("表情 petpet 可爱｜表情 文字表情 早上好",),
        "tests": ("tests/test_meme_domain_fixes.py",),
    },
    "偷表情": {
        "capability": "bot.meme_library",
        "triggers_nickname": ("偷表情", "偷表情包", "偷圖", "偷图", "随机表情", "表情隨機", "隨機表情", "隨機表情包", "表情抽籤", "表情库统计", "表情统计"),
        "triggers_nl": ("偷表情", "偷张表情包", "随机来张表情"),
        "outputs": ("图片",),
        "chat_scope": "写「私聊/私聊我」等同不填关键词，但改为私聊发送",
        "config_vars": ("BOT_MEME_LIBRARY_ENABLED", "BOT_MEME_LIBRARY_COOLDOWN_SECONDS"),
        "examples": ("偷表情｜偷表情 猫猫",),
        "tests": ("tests/test_meme_domain_fixes.py",),
    },
    "搜图": {
        "capability": "on_message:搜图",
        "outputs": ("文本（相似度/标题/URL 列表）",),
        "chat_scope": _CHAT_SCOPE_CONSISTENT,

        "network": True,
        "triggers_nickname": ("搜图", "搜圖"),
        "examples": ("（发一张图＋文字）搜图",),
    },
    "天气": {
        "capability": "bot.weather",
        "chat_scope": "查不到城市：群聊静默不回，私聊回明确报错文本（weather.py 会话分支）",

        "triggers_nickname": ("天气", "查天气", "weather", "天氣", "查天氣", "天氣預報"),
        "network": True,
        "triggers_nl": ("天气 <城市>", "帮我查<城市>天气", "<城市>天气怎么样"),
        "examples": ("天气 上海｜天气 河北-大城｜支持区县 浙江",),
        "tests": ("tests/test_weather_alerts_b10.py", "tests/test_weather_nmc_retry_nmcflix.py"),
    },
    "行情": {
        "capability": "bot.market",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,

        "network": True,
        "triggers_nl": ("行情", "A股行情", "B股行情", "莫斯科股指", "莫斯科行情", "全球股市", "股市", "大盘", "market", "stock market"),
        "outputs": ("釉瑚折线卡（MOEX 无东财 kline 时卡上无折线）/文本",),
        "html_image": True,
        "fallback": _FALLBACK_RENDER_TEXT,
        "examples": ("行情｜股市｜A股行情｜B股行情｜莫斯科行情",),
        "tests": ("tests/test_market_github.py",),
    },
    "个股行情": {
        "capability": "bot.stocks",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,

        "network": True,
        "triggers_nl": ("英伟达股价", "AMD 股价", "英特尔股价", "股价", "市值", "股價", "個股", "美股股价", "stocks", "stock"),
        "outputs": ("釉瑚金融卡（现价/日 K/KDJ/市值/走势折线/箱形图）/文本",),
        "html_image": True,
        "fallback": "行情拉不到回「美股行情暂时拉不到，晚点再试试？」；渲染失败回退纯文本",
        "config_vars": ("BOT_CARD_RENDER_DIR",),
        "examples": ("英伟达股价｜AMD 股价｜英特尔股价｜股价｜市值｜美股股价｜stocks",),
        "tests": ("tests/test_stock_data.py", "tests/test_finance_data.py", "tests/test_finance_routing.py"),
    },
    "商品行情": {
        "capability": "bot.commodities",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,
        "network": True,
        "triggers_nl": ("黄金", "金价", "白银", "银价", "原油", "油价", "铜价", "大宗商品", "黃金", "金價", "白銀", "油價", "銅價", "gold", "silver", "oil", "commodity"),
        "outputs": ("釉瑚金融卡（商品分组现价/30日走势折线）/文本",),
        "html_image": True,
        "fallback": "行情拉不到如实标注；渲染失败回退纯文本",
        "config_vars": ("BOT_CARD_RENDER_DIR",),
        "examples": ("黄金｜金价｜原油｜铜价｜大宗商品｜gold",),
        "tests": ("tests/test_finance_data.py", "tests/test_finance_route_wiring.py", "tests/test_market_exclusion_guard.py"),
    },
    "国债收益率": {
        "capability": "bot.bond",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,
        "network": True,
        "triggers_nl": ("国债", "国债收益率", "期限利差", "收益率曲线", "中美国债", "國債", "債券收益率"),
        "outputs": ("釉瑚金融卡（各期限收益率/10Y−2Y 利差）/文本",),
        "html_image": True,
        "fallback": "数据拉不到如实标注（1Y 无源诚实不接）；渲染失败回退纯文本",
        "config_vars": ("BOT_CARD_RENDER_DIR",),
        "examples": ("国债｜国债收益率｜期限利差｜收益率曲线｜中美国债",),
        "tests": ("tests/test_finance_data.py", "tests/test_finance_route_wiring.py"),
    },
    "北向资金": {
        "capability": "bot.northbound",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,
        "network": True,
        "triggers_nl": ("北向资金", "北上资金", "北向", "沪股通", "深股通", "北向資金", "北上資金", "滬股通"),
        "outputs": ("釉瑚金融卡（成交总额等仍在披露字段）/文本",),
        "html_image": True,
        "fallback": "数据拉不到如实标注（2024-08 起无净买入口径，不推算不伪造）；渲染失败回退纯文本",
        "config_vars": ("BOT_CARD_RENDER_DIR",),
        "examples": ("北向资金｜沪股通｜深股通｜北上资金",),
        "tests": ("tests/test_finance_data.py", "tests/test_finance_route_wiring.py"),
    },
    "汇率": {
        "capability": "bot.fx",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,

        "network": True,
        "triggers_nl": ("汇率", "匯率", "美元兑人民币", "100日元换多少人民币", "美元汇率", "换算", "換算", "USD/CNY", "fx", "forex", "exchange rate"),
        "outputs": ("釉瑚金融卡（货币面板/换算行）/文本",),
        "html_image": True,
        "fallback": "汇率拉不到回「汇率数据暂时拉不到，稍后再试。」；渲染失败回退纯文本",
        "config_vars": ("BOT_CARD_RENDER_DIR",),
        "examples": ("汇率｜美元兑人民币｜100日元换多少人民币｜USD/CNY｜匯率",),
        "tests": ("tests/test_fx_data.py", "tests/test_finance_routing.py"),
    },
    "占卜": {
        "capability": "bot.divination",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,

        "network": False,
        "triggers_nl": ("占卜", "塔罗", "塔羅", "八字", "算命", "起卦", "排盘", "排盤", "命盘", "命盤", "四柱", "摇卦", "搖卦", "求签", "求籤", "今日塔罗", "今日塔羅", "今天塔罗", "今天塔羅", "塔罗三张", "塔羅三張", "tarot", "bazi", "iching", "divination"),
        "examples": ("占卜｜塔罗 三张｜八字 1998年3月2日早上7点",),
        "tests": ("tests/test_divination.py",),
    },
    "快报": {
        "capability": "bot.news",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,

        "triggers_nickname": ("快报", "今日快报", "今日热点", "AI新闻", "AI快报", "科技新闻", "财经新闻", "财经快报", "国际新闻", "ai news", "news", "快報", "早報", "晚報", "今日熱點", "科技新聞", "AI新聞", "AI快報", "財經新聞", "財經快報", "國際新聞"),
        "network": True,
        "triggers_nl": ("快报", "快報", "今日热点", "今日熱點", "科技新闻", "科技新聞", "AI新闻", "AI新聞", "财经快报", "財經快報", "国际新闻", "國際新聞"),
        "examples": ("快报｜科技新闻｜财经快报｜国际新闻",),
        "tests": ("tests/test_news.py",),
    },
    "维基": {
        "capability": "bot.wiki",
        "outputs": ("文本",),
        "fallback": "区分「独立页缺失/列表缺失/网络失败」的文本提示",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,

        "triggers_nickname": ("wiki", "维基", "维基百科", "wikipedia"),
        "network": True,
        "triggers_nl": ("维基 <词条>", "wiki <词条>"),
        "config_vars": ("BOT_WIKI_LANG", "BOT_WIKI_ENTRY_PAGES"),
        "examples": ("维基 量子力学｜维基 鸣潮守岸人",),
    },
    "萌娘百科": {
        "capability": "bot.moegirl（二次元问句路由同归此能力）",
        "network": True,
        "triggers_nl": ("萌娘百科 <词条>", "<角色名>是谁？", "是谁", "是誰", "是什么", "是什麼", "介绍一下", "介紹一下"),
        "chat_scope": "二次元问句自动查询在群聊不 @ 不抢答（与聊天同门控）",
        "config_vars": ("BOT_MOEGIRL_QUESTION_ENABLED",),
        "examples": ("萌娘百科 初音未来｜初音未来是谁？",),
        "tests": ("tests/test_moegirl_search.py", "tests/test_moegirl_question_fix.py"),
    },
    "历史上的今天": {
        "capability": "bot.today_history",
        "triggers_nickname": ("历史上的今天", "今日历史", "today in history"),
        "network": True,
        "chat_scope": "设置每日推送时间：群内需管理员（影响全群），私聊自助",
        "examples": ("历史上的今天 设置 08:30",),
        "tests": ("tests/test_today_history_robustness.py",),
    },
    "下载": {
        "capability": "/bot download",
        "fallback": "失败优雅降级为文字（只说原因类型，不泄露堆栈与 cookie）",
        "network": True,
        "outputs": ("文件＋文字摘要",),
        "config_vars": ("BOT_DOWNLOAD_MAX_BYTES", "BOT_DOWNLOAD_MAX_HEIGHT", "BOT_DOWNLOAD_TIMEOUT_SECONDS", "BOT_DOWNLOAD_PROXY"),
        "examples": ("/bot download https://www.bilibili.com/video/BVxxxxxxxx",),
        "tests": ("tests/test_file_gateway_phase1.py", "tests/test_unified_gateways.py"),
    },
    "昵称": {
        "capability": "bot.alias",
        "triggers_nickname": ("帮助", "状态", "为什么", "天气", "点歌", "订阅", "日志", "清理历史", "暂停", "继续"),
        "config_vars": ("BOT_PERSONA_NICKNAMES",),
        "examples": ("/岸宝帮助｜守岸人 天气 上海｜/岸宝点歌 晴天",),
        "tests": ("tests/test_nickname_default_seed.py", "tests/test_nickname_learning.py"),
    },
    "链接": {
        "capability": "bot.content",
        "chat_scope": "群聊/私聊行为一致（解析按链接触发）",

        "network": True,
        "triggers_nl": ("直接粘贴平台链接",),
        "examples": ("直接粘贴 https://www.bilibili.com/video/BVxxxx",),
        "tests": ("tests/test_parser_v2_boundary.py",),
    },
    "草稿": {
        "capability": "bot.auto_send",
        "chat_scope": "群聊/私聊行为一致（仅预览不实发）",

        "triggers_nl": ("报存", "報存", "报存 给 <收件人> 发邮件", "報存 給 <收件人> 發郵件"),
        "examples": ("报存 给小明、小红 发邮件，主题：周末聚餐，内容：周六晚上六点老地方见",),
        "tests": ("tests/test_content_video_auto_send.py",),
    },
    "吃什么": {
        "capability": "bot.eat",
        "chat_scope": "群聊/私聊行为一致（会话仅用作去重缓存键）",

        "triggers_nickname": ("吃什么", "吃啥", "今天吃什么", "菜谱", "怎么做", "eat", "food", "recipe"),
        "triggers_nl": ("吃什么", "吃啥", "菜谱 <菜名>", "怎么做"),
        "examples": ("吃什么｜吃什么 三选一｜菜谱 番茄炒蛋",),
        "tests": ("tests/test_eat_capability.py",),
    },
    "媒体归档": {
        "capability": "bot.media_archive",
        "network": True,
        "triggers_nickname": ("收藏", "归档", "存图", "收图", "存聊天记录", "archive"),
        "chat_scope": "私聊/群聊行为一致（回复媒体或媒体+指令同条触发）",
        "triggers_nl": ("收藏", "归档", "存图", "存聊天记录", "archive"),
        "examples": ("[图片] 收藏 分类=cosplay IP=鸣潮｜（回复转发）存聊天记录",),
        "tests": ("tests/test_media_archive.py",),
    },
    "紧急信息": {
        "capability": "bot.emergency_info",
        "network": True,
        "chat_scope": "查询与审核=管理员；设/退订阅=超级管理员·管理员·本群群主（仅 QQ 侧）；群聊只读已批准条目",
        "triggers_nickname": ("紧急信息", "预警", "地震"),
        "triggers_nl": ("紧急信息", "预警", "地震", "震情", "待审", "emergency"),
        "config_vars": ("BOT_EMERGENCY_INFO_ENABLED", "BOT_EMERGENCY_INFO_MIN_LEVEL", "BOT_EMERGENCY_INFO_SOURCES", "BOT_EMERGENCY_INFO_AUTO_APPROVE_SOURCES", "BOT_EMERGENCY_INFO_REVIEWER_IDS"),
        "examples": ("紧急信息", "紧急信息 订阅 area=湘潭 kinds=暴雨 橙色以上", "紧急信息 订阅 看", "紧急信息 退订", "紧急信息 待审", "紧急信息 审核 <id> 通过"),
        "tests": ("tests/test_emergency_info_core.py", "tests/test_emergency_info_sources.py", "tests/test_emergency_info_subscriptions.py", "tests/test_emergency_info_reachability.py"),
        "outputs": ("文本",),
        "fallback": "源不可达时明确说拿不到，绝不把「取不到」说成「无预警」",
    },
    "群信息": {
        "capability": "bot.group_info",
        "network": True,
        "outputs": ("文本",),
        "triggers_nickname": ("群信息", "本群信息", "群资料", "群主是谁", "谁是群主", "群人数", "群公告", "群精华", "精华消息", "本群多大了", "群相册", "本群相册", "群相册列表", "群待办", "本群待办", "群待办列表", "群里都有谁", "本群都有谁", "群里谁说过话", "本群谁说过话", "群参与者", "本群参与者", "都有谁说过话", "我都跟谁聊过", "跟谁聊过"),
        "chat_scope": "仅群聊生效（私聊回守岸人提示）；群资料/人数/相册/待办/参与者全员，公告与精华仅管理员；成员名单不整列（隐私+防刷屏），参与者族读记忆里的说话人而非协议名单",
        "examples": ("群信息｜群主是谁｜群人数｜群公告｜群精华｜本群多大了",),
        "tests": ("tests/test_group_info.py",),
    },
    "宿主机状态": {
        "capability": "bot.host_state",
        "network": False,
        "outputs": ("文本", "图片"),
        "triggers_nickname": ("宿主机状态", "机器状态", "机器配置", "宿主状态", "宿主機狀態", "機器狀態", "hoststate", "jiqizhuangtai", "jizhuangtai", "jiqipeizhi"),
        "chat_scope": "仅超级管理员（其余角色得到一句温和拒绝）；群聊与私聊同面可问；读数本机现算、逐行打码，只读不改任何设置",
        "examples": ("机器状态｜机器配置｜宿主状态｜hoststate",),
        "tests": ("tests/test_host_state_card.py", "tests/test_host_metrics.py", "tests/test_host_status.py"),
    },
    "书面同意": {
        "capability": "bot.consent",
        "network": False,
        "outputs": ("文本",),
        "triggers_nickname": ("同意卡", "书面同意", "同意單", "書面同意", "consentcard", "yijika", "shumiantongyi"),
        "chat_scope": "仅管理员及其以上；看单不分群聊私聊，批一张具体的卡按同意账的阶梯判（R2=超管私聊亲批）；发起人不批自己发起的卡；只回显账上事实，本命令面自己绝不改参数",
        "examples": ("同意卡 待批｜同意卡 看 3f2a1b｜同意卡 批 3f2a1b 8c1d4e7a｜书面同意 驳 3f2a1b 8c1d4e7a",),
        "tests": ("tests/test_consent_command_surface.py", "tests/test_safety_exec_throat_wire.py"),
    },
    "好感度": {
        "capability": "bot.affinity",
        "triggers_nickname": ("好感度", "好感", "好感查看", "查询好感", "查詢好感", "好感值", "親密度", "affinity"),
        "chat_scope": "私聊=双向好感卡；群聊=本群好感榜（自己高亮，展示前 12/上限 60）",
        "triggers_nl": ("好感度", "好感", "查询好感", "查詢好感", "亲密度", "親密度", "affinity"),
        "examples": ("好感度｜好感度 我｜好感度 算法",),
        "tests": ("tests/test_affinity.py", "tests/test_affinity_query.py", "tests/test_affinity_numerical.py"),
    },
    "Epic": {
        "capability": "bot.epic",
        "outputs": ("卡片图＋文本（mixed）/文本",),
        "html_image": True,
        "fallback": "单源挂文本尾注；双源全挂回文本「拉取失败，稍后再试」",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,

        "triggers_nickname": ("epic", "epicfree", "epic免费", "epic free", "免费游戏", "免費遊戲", "游戏免费", "遊戲免費", "steam免费", "steam免費", "steam 免費", "steam free", "steam 免费"),
        "network": True,
        "triggers_nl": ("epic", "免费游戏", "免費遊戲"),
        "examples": ("epic",),
    },
    "随机图": {
        "capability": "bot.randpic",
        "chat_scope": _CHAT_SCOPE_CONSISTENT,

        "triggers_nickname": ("隨機圖", "來張圖"),
        "network": False,
        "triggers_nl": ("随机图", "来张图", "隨機圖", "來張圖"),
        "outputs": ("图片",),
        "config_vars": (
            "BOT_RANDPIC_DIRS",
            "BOT_RANDPIC_TRIGGER_WORDS",
            "BOT_RANDPIC_ENABLED",
            "BOT_RANDPIC_MAX_FILE_MB",
            "BOT_RANDPIC_NO_REPEAT_WINDOW_SECONDS",
            "BOT_RANDPIC_DISPATCH_ENABLED",
            "BOT_RANDPIC_DISPATCH_PROBABILITY",
            "BOT_RANDPIC_DISPATCH_COOLDOWN_SECONDS",
            "BOT_RANDPIC_DISPATCH_MAX_PER_HOUR",
        ),
        "examples": ("随机图｜来张图",),
        "tests": (
            "tests/test_randpic_identity.py",
            "tests/test_randpic_dispatch.py",
        ),
    },
    "提醒": {
        "capability": "bot.reminder",
        "chat_scope": "投递目标：群聊=原群，私聊=本人（target_scope=会话类型）",

        "triggers_nl": ("<时间>提醒我…", "<时间>叫我…", "记得叫", "記得叫", "提醒列表", "取消提醒 <id>"),
        "examples": ("12点提醒我写作业｜明天早上8点叫我起床｜半小时后提醒我去看汤｜提醒列表｜取消提醒 a3f2",),
        "tests": ("tests/test_reminder.py",),
    },
    "笔记": {
        "capability": "bot.reminder",
        "network": False,
        "chat_scope": "笔记按会话隔离（A 群看不到 B 群）；配图落 data/notes_images",
        "outputs": ("文本", "图片（回看补发）"),
        "triggers_nl": ("笔记 记 <内容>", "笔记列表", "笔记 看 N", "看笔记 N", "做完 N", "完成 N", "办完 N", "删笔记 N", "<事项>做完了"),
        "triggers_nickname": ("笔记", "筆記", "biji", "note", "bijiliebiao", "bjlb", "kanbiji", "shanbiji"),
        "config_vars": ("BOT_NOTES_ENABLED", "BOT_NOTES_DB_PATH", "BOT_NOTES_MAX_PER_CHAT"),
        "examples": ("笔记 记 周三要交总结｜笔记列表｜笔记 看 1｜做完 1｜完成 1｜删笔记 1",),
        "tests": ("tests/test_notes.py", "tests/test_todo_checkoff.py", "tests/test_reminder_tone.py"),
    },
    "收件箱": {
        "capability": "bot.daily_assist",
        "network": False,
        "chat_scope": "收件箱是全局一份纯文本文件（bot_daily_assist_dir），不分会话；定时简报仅私聊推送名单",
        "outputs": ("文本",),
        "triggers_nl": ("收件箱 <内容>", "收件箱"),
        "triggers_nickname": ("收件箱", "inbox", "shoujianxiang"),
        "config_vars": (
            "BOT_DAILY_ASSIST_ENABLED",
            "BOT_DAILY_ASSIST_DIR",
            "BOT_DAILY_ASSIST_PUSH_USER_IDS",
            "BOT_DAILY_ASSIST_MEAL_TIMES",
            "BOT_DAILY_ASSIST_MORNING_TIME",
            "BOT_DAILY_ASSIST_EVENING_TIME",
        ),
        "examples": ("收件箱 周五前还信用卡｜收件箱 买猫粮｜收件箱",),
        "tests": ("tests/test_daily_assist.py",),
    },
    "语音": {
        "capability": "bot.tts",
        "network": False,
        "outputs": ("语音",),
        "chat_scope": "全员可用；对话自动配音范围由 BOT_TTS_AUTO_REPLY_SCOPE 决定（private/group/all）",
        "triggers_nl": ("说 <文本>", "语音 <文本>", "念 <文本>", "朗读 <文本>", "语音合成 <文本>", "tts <文本>", "say <文本>", "說 <文本>", "語音 <文本>", "唸 <文本>", "朗讀 <文本>", "語音合成 <文本>"),
        "triggers_nickname": ("语音", "tts", "yuyin", "shuo", "nian", "语音合成", "朗读", "langdu", "say", "說", "語音", "唸", "朗讀", "語音合成"),
        "config_vars": (
            "BOT_TTS_ENABLED",
            "BOT_TTS_API_URL",
            "BOT_TTS_GPTSOVITS_DIR",
            "BOT_TTS_REF_AUDIOS",
            "BOT_TTS_TRIGGER_WORDS",
            "BOT_TTS_OUTPUT_DIR",
            "BOT_TTS_PRESET",
            "BOT_TTS_MAX_CHARS",
            "BOT_TTS_HARD_MAX_CHARS",
            "BOT_TTS_MAX_AUDIO_BYTES",
            "BOT_TTS_TIMEOUT_SECONDS",
            "BOT_TTS_SPEED_FACTOR",
            "BOT_TTS_TEMPERATURE",
            "BOT_TTS_TOP_K",
            "BOT_TTS_TOP_P",
            "BOT_TTS_TEXT_LANG",
            "BOT_TTS_TEXT_SPLIT_METHOD",
            "BOT_TTS_CACHE_ENABLED",
            "BOT_TTS_CACHE_MAX_BYTES",
            "BOT_TTS_CACHE_MAX_AGE_DAYS",
            "BOT_TTS_AUTO_REPLY_ENABLED",
            "BOT_TTS_AUTO_REPLY_SCOPE",
            "BOT_TTS_AUTO_REPLY_MAX_CHARS",
            "BOT_TTS_AUTO_REPLY_SPLIT_MAX_CHARS",
            "BOT_TTS_AUTO_REPLY_PROBABILITY",
            "BOT_TTS_AUTO_REPLY_ALWAYS",
            "BOT_TTS_VOICE_HOOK_ENABLED",
        ),
        "examples": ("说 今天的潮汐很安静｜语音 我在这里｜tts hello",),
        "tests": (
            "tests/test_tts.py",
            "tests/test_tts_outbound_chain.py",
            "tests/test_tts_hijack_guard.py",
            "tests/test_tts_speech_gate.py",
            "tests/test_tts_failure_visibility.py",
            "tests/test_tts_audio_gate.py",
        ),
    },
    "帮助": {
        "capability": "bot.help",
        "network": False,
        "outputs": ("Mica 卡/文本",),
        "html_image": True,
        "fallback": _FALLBACK_RENDER_TEXT,
        "chat_scope": "普通用户只见公开模块；查管理员模块回「没有找到」",
        "triggers_nickname": ("帮助", "help"),
        "examples": ("/bot help｜/bot help 点歌｜/bot help help",),
        "tests": ("tests/test_bot_commands_catalog_b10.py", "tests/test_help_entries_coverage.py", "tests/test_documentation_consistency.py"),
    },
    "聊天": {
        "capability": "bot.chat",
        "network": True,
        "outputs": ("文本",),
        "fallback": "私聊回守岸人话术提示，群聊保持静默不刷屏",
        "chat_scope": "群聊=@点名/昵称点名/接话抽签（好感门）；私聊=白名单直说",
    },
    "戳一戳": {
        "capability": "on_notice:戳一戳",
        "network": False,
        "outputs": ("文本回应", "语音+文本", "表情包图片", "随机图片", "回戳"),
        "config_vars": (
            "BOT_POKE_ENABLED",
            "BOT_POKE_PROBABILITY",
            "BOT_POKE_REPLY_ENABLED",
            "BOT_POKE_REPLY_MODE",
            "BOT_POKE_POKE_BACK",
            "BOT_POKE_EXTRA_ARMS_ENABLED",
            "BOT_POKE_PRIVATE_COOLDOWN_SECONDS",
            "BOT_POKE_GROUP_COOLDOWN_SECONDS",
            "BOT_POKE_GROUP_TEXT",
            "BOT_POKE_PRIVATE_TEXT",
            "BOT_POKE_FOLLOW_ENABLED",
            "BOT_POKE_FOLLOW_PROBABILITY",
            "BOT_POKE_FOLLOW_COOLDOWN_SECONDS",
            "BOT_POKE_FOLLOW_MAX_PER_HOUR",
            "BOT_POKE_AFTER_REPLY_ENABLED",
            "BOT_POKE_AFTER_REPLY_PROBABILITY",
            "BOT_POKE_AFTER_REPLY_COOLDOWN_SECONDS",
            "BOT_POKE_AFTER_REPLY_MAX_PER_HOUR",
            "BOT_POKE_AFFINITY_ENABLED",
            "BOT_POKE_AFFINITY_DELTA",
            "BOT_POKE_AFFINITY_DAILY_MAX",
        ),
        "tests": ("tests/test_poke_v2.py", "tests/test_poke_arms_v3.py"),
    },
    "表情收库": {
        "capability": "meme_absorb（群图自动收库，无命令）",
        "network": True,
        "outputs": ("无直接输出（图片异步入库）",),
    },
    "自然语言": {
        "capability": "bot.natural_command",
        "outputs": ("归一化后转目标模块执行",),
    },
    "忽略": {
        "capability": "matcher:IGNORE（空消息静默；未知命令形态回引导）",
        "outputs": ("按设计静默；未知命令形态回一句 /bot help 引导（60 秒/会话节流）",),
    },
    "决策": {
        "capability": "/bot decision",
        "network": False,
        "outputs": ("文本",),
        "triggers_nickname": ("决策", "decision"),
        "examples": ("/bot decision", "/bot decision 50"),
        "tests": ("tests/test_decision_trace_persistence.py",),
    },
}

# 追加式补充说明：与 _HELP_ENTRY_META 同理以字面量侧表维护，保持文本帮助与
# 渲染帮助卡的操作指引一致，并让静态目录能合并出与运行时相同的内容。
_HELP_EXTRA_LINES: dict[str, tuple[str, ...]] = {
    "回复": (
        "/bot reply 详细：先说明结论、身份、关系、关键经历和资料缺口，不强制凑字数。",
        "/bot runtime set BOT_CHAT_MAX_TOKENS 8192：输出上限，不是必须生成的长度。",
        "/bot runtime set BOT_CHAT_FAST_MODE false：知识验收阶段关闭快速模式。",
        "BOT_CHAT_MAX_TOKENS=65538 是最大上限，不是每次强制生成 64K。",
        "文件生成：明确说“生成/保存/导出文件”，机器人会先写文件，再走上传接口。",
        "戳一戳：默认响应有冷却；BOT_POKE_ENABLED、BOT_POKE_*_COOLDOWN_SECONDS、BOT_POKE_PROBABILITY 可调。",
        "/bot runtime set BOT_CHAT_FAST_MAX_TOKENS 8192：重新启用快速模式时的输出上限。",
        "运行时覆盖优先于 .env；用 runtime get 查看实际设置。",
    ),
    "设置": (
        "/bot runtime get BOT_REPLY_DETAIL：查看实际详略模式及覆盖来源。",
        "/bot runtime set BOT_MEMORY_EXTRACT_ENABLED false：暂停自动抽取，不删除已有记忆。",
        "/bot runtime set BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS 15：抽取总预算（秒）。",
        "/bot runtime set BOT_MEMORY_EXTRACT_MAX_TOKENS 200：抽取输出上限（1..4096）。",
        "/bot runtime set BOT_MEMORY_EXTRACT_ERROR_COOLDOWN_SECONDS 300：抽取失败后冷却。",
        "记忆抽取复用聊天路由配置，采用独立调用状态；不使用另一枚基础 key 绕开模型注册表。",
    ),
    "模型": (
        "priority 是 1..N 唯一槽位：移动一个模型，其他模型自动顺移；0 兼容为移到首位。",
        "手动指定 > 时段组 order > 基础 priority。时段组启用时基础排序不覆盖组内顺序。",
        "model list 显示候选配置，不等于上一条实际回答的供应商；/bot llm 会产生新的诊断调用。",
        "不要在群聊发送真实 Key；使用 key=env:变量名，在本地安全配置凭据。",
    ),
}

# ---------------------------------------------------------------------------
# HELP-1（2026-09-20）：帮助文案的**单一事实源**。
# 旧缺陷（docs/design/link-unification-audit-20260920.md §B-1）：同一主题的命令行在
# `lines[]` 与 `detail` 的【指令与参数】段里**平行手写两份**，实测 77 主题里 120 条
# 同句已漂移（例：「功能管理」的 detail 丢了「修改仅限超管」），且深页把两份都印出来
# ——一条消息把同一命令讲两遍且说法不同。
# 现行做法：`lines[]` 是唯一事实源；detail 的【指令与参数】段由下面的
# `_compose_help_detail()` 在装配期派生注入，**字面量里不再手写**（77 处手写段已删除）。
# 结构锁与负向锁见 tests/test_help_single_source.py。
_HELP_COMMAND_SECTION_HEADER = "【指令与参数】\n"
_HELP_COMMAND_SECTION_RE = re.compile(r"【指令与参数】\n.*?(?=^【|\Z)", re.MULTILINE | re.DOTALL)
_HELP_NARRATIVE_HEADER_RE = re.compile(r"^【[^】]{1,12}】", re.MULTILINE)
_HELP_INTRO_HEADER = "【板块介绍】"


def _derive_help_command_section(lines: list[str]) -> str:
    """由 `lines[]` 派生【指令与参数】段（含表头与收尾换行）。唯一派生入口。"""
    return _HELP_COMMAND_SECTION_HEADER + "\n".join(str(line) for line in lines) + "\n"


def _strip_help_command_section(detail: str) -> str:
    """摘掉【指令与参数】段，只留板块介绍/取值范围/权限与效果/示例等叙述小节。"""
    return _HELP_COMMAND_SECTION_RE.sub("", str(detail or ""))


def _compose_help_detail(narrative: str, lines: list[str]) -> str:
    """把派生的【指令与参数】段插回叙述小节的原位置（板块介绍之后、其余小节之前）。"""
    text = str(narrative or "")
    if text and not text.endswith("\n"):
        text += "\n"
    block = _derive_help_command_section(lines)
    positions = [
        match.start()
        for match in _HELP_NARRATIVE_HEADER_RE.finditer(text)
        if match.group(0) != _HELP_INTRO_HEADER
    ]
    if not positions:
        return text + block
    pos = min(positions)
    prefix = text[:pos]
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + block + text[pos:]


# Keep text help and rendered help cards on the same operational instructions.
for _entry in _HELP_ENTRIES:
    _extra = _HELP_EXTRA_LINES.get(_entry["topic"], ())
    if _extra:
        _entry["lines"] = [*_entry.get("lines", []), *_extra]
    for _key, _value in _HELP_ENTRY_META.get(_entry["topic"], {}).items():
        _entry.setdefault(_key, _value)  # type: ignore[misc]
    # detail 的命令行段一律派生，绝不手写；叙述小节仍逐主题人写。
    _entry["detail"] = _compose_help_detail(
        str(_entry.get("detail") or ""),
        [str(_line) for _line in _entry.get("lines", [])],
    )

# T5 结构修复（fix-trae2）：_HELP_ALIAS_MAP 此前只从 aliases 构建，META 的
# triggers_nickname/triggers_nl「深度页元数据看得见、help 查询搜不到」——
# aliases 漏登即搜不到的复发模式由此而来。现在 META 触发词一并纳入可搜索集合；
# aliases 永远优先（setdefault 不覆盖既有键），既有命中与管理员隔离零变化。
_HELP_ALIAS_MAP: dict[str, str] = {
    alias.lower(): entry["topic"]
    for entry in _HELP_ENTRIES
    for alias in entry["aliases"]
}
for _entry in _HELP_ENTRIES:
    _entry_meta = _HELP_ENTRY_META.get(_entry["topic"], {})
    for _field in ("triggers_nickname", "triggers_nl"):
        for _trigger in _entry_meta.get(_field) or ():
            _HELP_ALIAS_MAP.setdefault(str(_trigger).strip().lower(), _entry["topic"])

HELP_ENTRIES = _HELP_ENTRIES


def _split_command_row(row: str) -> tuple[str, str]:
    """把帮助行拆成「命令段 + 说明段」：在首个「：」或「: 」处切分。"""
    for sep in ("：", ": "):
        idx = row.find(sep)
        if 0 < idx < len(row) - len(sep):
            head = row[: idx + len(sep)]
            tail = row[idx + len(sep):]
            return head, tail
    return row, ""


_FACET_PAIR_RE = re.compile(r"^([^；=：]{1,6})=(.*)$")


def _facet_pair(text: str) -> tuple[str, str] | None:
    """「作用=列出能力节点」→ ("作用", "列出能力节点")；不是要素行返回 None。"""
    matched = _FACET_PAIR_RE.match(text.strip())
    if matched is None:
        return None
    label, value = matched.group(1).strip(), matched.group(2).strip()
    return (label, value) if label and value else None


def _help_card_rows(row: str) -> list[tuple[str, str]]:
    """正文一行 → 卡片若干「属性名｜属性值」行（2026-09-25 澜汐：每个值一行）。

    正文侧四要素早就由 ``_split_facets`` 拆成一行一个，但卡片把整行喂给
    ``_split_command_row``：像「　参数=无」这种行里没有「：」，于是**整行变成了
    药丸标签**，而 ``.pill`` 是 nowrap + 62% 宽省略号——参数、内容、意义在图上被
    悄悄切掉。这里把要素行拆成「标签｜正文」，正文落进可换行的说明列；命令行
    则拆成"命令名单独一行 ＋ 其后逐行属性"，属性名与属性值各自左对齐。
    没有要素的普通行照旧（首个人称分隔前作药丸、其后作说明）。
    """
    line = row.strip().strip("\u3000").strip()
    if not line:
        return []
    own = _facet_pair(line)
    if own is not None:
        return [own]
    head, sep, tail = line.partition("：")
    if sep and head.strip() and tail.strip():
        parts = [p.strip() for p in _FACET_SPLIT_RE.split(tail) if p.strip()]
        pairs = [_facet_pair(p) for p in parts]
        if parts and all(pair is not None for pair in pairs):
            rows: list[tuple[str, str]] = [(head.strip(), "")]
            for pair in pairs:
                if pair is not None:
                    rows.append(pair)
            return rows
    cmd, desc = _split_command_row(line)
    if not desc:
        # 没有「：」可切的整句（【示例】行、板块介绍行）落**说明列**：药丸是
        # nowrap+62%+省略号，长句会在图上被静默截掉——正文一个字都不该丢。
        return [("", line)]
    return [(cmd, desc)]


def _resolve_help_accent(accent_color: str) -> tuple[str, str]:
    """把配置主色归一成 (accent, accent_dark)；非法/留空回退中性灰。"""
    from plugins.bot_unified_runtime.output.card_render.bridge import (
        _darken,
        _hex_to_rgb,
        _rgb_to_hex,
    )

    rgb = _hex_to_rgb(accent_color or "")
    return _rgb_to_hex(rgb), _rgb_to_hex(_darken(rgb))


def _help_index_sections(is_admin: bool) -> list[tuple[str, list[tuple[str, str]]]]:
    """结构化索引：分类 → (药丸标签, 说明)。供帮助卡网格布局消费。"""
    hint_re = re.compile(r"｜详情：/bot help .*?$")
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    for category, category_entries in _help_grouped(_visible_help_entries(is_admin)):
        rows: list[tuple[str, str]] = []
        for entry in category_entries:
            topic = str(entry["topic"])
            desc = hint_re.sub("", re.sub(r"^【[^】]+】", "", str(entry["index"])).strip())
            desc = desc.strip("；;｜| ").strip()
            rows.append((str(entry["aliases"][0]) if entry["aliases"] else topic, desc or topic))
        if rows:
            sections.append((category, rows))
    return sections


def _help_mica_html(
    body: str,
    *,
    is_admin: bool,
    bot_name: str = "守岸人",
    bot_avatar_url: str = "",
    accent_color: str = "",
    sections: list[tuple[str, list[tuple[str, str]]]] | None = None,
) -> str:
    """Render a one-page categorized Mica help card with transparent outer space.

    ``sections`` 提供结构化索引（总览页 → 两列网格 + 命令药丸）；缺省时
    按正文解析（模块详情页：首行作卡题，其余行拆「命令段 + 说明段」）。
    总览页 topic 目录两栏化（台账 #13 残余）：外层 masonry 双栏分区 +
    分区内 topic 行再走两栏 CSS columns，<560px 媒体查询退回单栏。
    mica-glass v1 2026-09-12：釉瑚云母底（bridge 按 accent 派生 --wash-* 注入；
    工艺出处=用户裁定）+ 液态玻璃面板 + 三枚柔光色斑漂移（E01 二批：相位由
    payload digest 钉帧，bridge.payload_phase 单一事实源，页面零 JS）。
    """
    from plugins.bot_unified_runtime.domains.render.card_render.mica_shell import (
        drift_blobs_html,
        mica_decor_css,
        render_root_tokens,
        shell_base_css,
    )
    from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
        BRAND_WASH_TOKENS,
    )
    from plugins.bot_unified_runtime.output.card_render.bridge import (
        payload_phase,
    )

    accent, accent_dark = _resolve_help_accent(accent_color)
    # 底色锚点=本命蓝（2026-09-25 点名：背景要在守岸人的蓝色标志色上做渐变）。
    # accent 仍可被 bot_help_card_color 配走，但它只管强调线与色斑。
    wash = BRAND_WASH_TOKENS
    detail_title = ""
    if sections is None:
        sections = []
        current_title = "功能"
        current_rows: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line or line.endswith("总览"):
                continue
            if line.startswith("【") and line.endswith("】"):
                if current_rows:
                    sections.append(
                        (
                            current_title,
                            [(p, d) for r in current_rows for (p, d) in _help_card_rows(r)],
                        )
                    )
                current_title, current_rows = line[1:-1], []
                continue
            if detail_title:
                current_rows.append(line)
            else:
                detail_title = line.rstrip("：:")
                current_title = detail_title
        if current_rows:
            sections.append(
                (
                    current_title or "用法",
                    [(p, d) for r in current_rows for (p, d) in _help_card_rows(r)],
                )
            )
        if sections and not detail_title:
            detail_title = sections[0][0]

    def _esc(value: str) -> str:
        return html.escape(value)

    def _rows_html(rows: list[tuple[str, str]]) -> str:
        return "".join(
            "<div class=\"command-row\">"
            + (f"<span class=\"pill\">{_esc(cmd.rstrip('：:'))}</span>" if cmd else "")
            + (f"<span class=\"desc\">{_esc(desc)}</span>" if desc else "")
            + "</div>"
            for cmd, desc in rows
        )

    if detail_title:
        # 模块详情/分类说明书：单列卡，首段为主卡。
        cards = "".join(
            "<section class=\"help-section glass" + (" main" if index == 0 else "") + "\">"
            f"<h2><span class=\"dot\"></span>{_esc(title)}</h2>"
            f"<div class=\"command-list\">{_rows_html(rows)}</div></section>"
            for index, (title, rows) in enumerate(sections)
        )
        grid_cls = "single"
        header_title = f"{bot_name} · {detail_title}"
        # 详情页不再重复"参数标注/怎么用"——那两句已经在页脚和右上角，逐行标签
        # （作用/参数/内容/意义）本身就是读法说明（2026-09-25 澜汐：别复读）。
        header_sub = ""
    else:
        cards = "".join(
            "<section class=\"help-section glass" + (" wide" if len(rows) >= 40 else "") + "\">"
            f"<h2><span class=\"dot\"></span>{_esc(title)}</h2>"
            f"<div class=\"command-list\">{_rows_html(rows)}</div></section>"
            for title, rows in sections
        )
        grid_cls = "masonry"
        header_title = f"{bot_name} · 命令手册"
        header_sub = "回复「/bot help 模块名」看这个模块的逐条命令与参数，例：/bot help 点歌。"
    role = "管理员帮助" if is_admin else "公开帮助"
    # E01 二批：漂移相位 = 内容 digest 钉帧（同 payload 双渲一致、零 JS 随机源）。
    phase = payload_phase({"sections": sections, "detail_title": detail_title})
    avatar = (
        f'<img class="help-bot-avatar" src="{html.escape(bot_avatar_url)}" alt="" />'
        if bot_avatar_url else ""
    )
    avatar_block = avatar or f"<span class=\"avatar-fallback\">{_esc((bot_name or '守')[:1])}</span>"
    # 副标题为空时整块不渲染，不留一条只有 margin 的空行（详情页已无副标题）。
    subtitle_html = (
        f"<div class=\"help-subtitle\">{_esc(header_sub)}</div>" if header_sub else ""
    )
    # :root 单一产出（v21r3 渲染统一步 3）：公共 token 子集、顺序、书写风格
    # 与其余三张直拼卡及七张 Jinja 卡一致，改一处全项目同步。
    root_tokens = render_root_tokens(
        accent=accent,
        accent_dark=accent_dark,
        phase=phase,
        wash=wash,
    )
    # 通水切换（v21r3 统一收尾波 C2/C3）：壳层+玻璃两档+色斑层由 mica_shell
    # 生成器单一产出拼入（宽度 940=CARD_SHELL_WIDTHS["help"]；DOM 同源），
    # 手抄副本退役；缺省输出与历史 CSS 逐字节等价（CORE 席实弹断言）。
    shell_css = shell_base_css("help-shell", width_px=940)
    decor_css = mica_decor_css()
    blobs_html = drift_blobs_html()
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
:root {{ {root_tokens} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:0; font-family:var(--font-family); background:transparent; color:var(--ink); -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }}
.help-stage {{ width:fit-content; padding:0; background:transparent; }}
/* 釉瑚云母外壳+玻璃两档+漂移色斑层：mica_shell 生成器单一产出（v21r3 通水
   切换，2026-09-19）：shell_base_css("help-shell", width_px=940)（雾底打底、
   wash 对角透色、1px 内高光描边、.glass/.glass-foot 两档）+ mica_decor_css()
   （三枚 46/52/58s 交错漂移；reduced-motion 关停内建）；色斑垫底、内容抬升；
   阴影只经两枚 token。 */
{shell_css}
{decor_css}
.help-head {{ display:flex; align-items:center; gap:14px; padding:22px 26px 18px; border-bottom:1px solid rgba(255,255,255,.78); }}
.avatar-wrap {{ flex:0 0 auto; width:52px; height:52px; border-radius:16px; overflow:hidden; background:color-mix(in srgb, var(--accent) 14%, #fff); display:flex; align-items:center; justify-content:center; box-shadow:var(--mica-shadow-soft); }}
.avatar-wrap img {{ width:100%; height:100%; object-fit:cover; }}
.avatar-fallback {{ font-size:24px; font-weight:700; color:var(--accent-dark); }}
.head-main {{ flex:1 1 auto; min-width:0; }}
.help-kicker {{ color:var(--accent-dark); font-size:13px; font-weight:700; letter-spacing:.06em; }}
.help-title {{ margin-top:6px; font-size:26px; font-weight:700; letter-spacing:.02em; }}
.help-subtitle {{ margin-top:6px; color:var(--muted); font-size:13px; line-height:1.5; }}
.help-chip {{ flex:0 0 auto; padding:7px 14px; border-radius:999px; color:var(--accent-dark); background:color-mix(in srgb, var(--accent) 8%, rgba(255,255,255,.80)); border:1px solid rgba(255,255,255,.90); font-size:13px; font-weight:650; }}
.help-body {{ padding:14px; }}
.help-grid.masonry {{ column-count:2; column-gap:14px; }}
.help-grid.masonry .help-section {{ break-inside:avoid; margin-bottom:14px; }}
.help-grid.masonry .help-section.wide {{ column-span:all; }}
/* 目录页两栏（2026-09-25 澜汐：「太挤了，换成两栏」）——旧形态是**分区两栏 ×
   区内再两栏 = 四栏正文**，每栏 ~200px，摘要两行就放不下，于是被 line-clamp
   钳成省略号：她看到的「详细介绍不详细」大半是被切了，不是文案短（现算：
   79 个 topic 里按结构判据真算「薄」的只有 8 个，而目录行超 34 字的有 38 个）。
   现在整页就两栏，区内行铺满栏宽，钳位与省略号一并撤掉。 */
.help-grid.masonry .command-list {{ display:grid; gap:6px; }}
.help-grid.masonry .command-row {{ break-inside:avoid; padding:7px 10px; }}
.help-grid.single {{ display:grid; grid-template-columns:1fr; gap:12px; }}
.help-section {{ border-radius:16px; overflow:hidden; }}
.help-section h2 {{ display:flex; align-items:center; gap:8px; margin:0; padding:10px 14px; color:var(--accent-dark); background:linear-gradient(135deg, color-mix(in srgb, var(--accent) 7%, rgba(255,255,255,.62)), color-mix(in srgb, var(--accent) 12%, rgba(255,255,255,.48))); border-bottom:1px solid rgba(255,255,255,.85); font-size:15px; font-weight:700; letter-spacing:.02em; }}
.help-section h2 .dot {{ flex:0 0 auto; width:7px; height:7px; border-radius:50%; background:var(--accent); box-shadow:var(--mica-shadow-soft); }}
.command-list {{ padding:9px; display:grid; gap:6px; }}
.command-row {{ display:flex; align-items:flex-start; gap:8px; padding:7px 10px; border-radius:12px; background:rgba(255,255,255,.62); font-size:13px; line-height:1.5; }}
.command-row .pill {{ flex:0 0 auto; max-width:100%; padding:2px 10px; border-radius:999px; color:var(--accent-dark); background:color-mix(in srgb, var(--accent) 13%, rgba(255,255,255,.82)); font-weight:700; white-space:normal; overflow-wrap:anywhere; }}
.command-row .desc {{ color:var(--muted); min-width:0; overflow-wrap:anywhere; }}
.help-foot {{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding:10px 16px; background:rgba(255,255,255,.46); border-top:1px solid rgba(255,255,255,.80); }}
.help-foot .tip {{ color:var(--muted); font-size:13px; }}
.help-bot-pill {{ display:flex; align-items:center; gap:8px; padding:5px 13px 5px 6px; border-radius:999px; color:var(--accent-dark); background:color-mix(in srgb, var(--accent) 6%, rgba(255,255,255,.72)); border:1px solid #fff; box-shadow:var(--mica-shadow-soft); font-size:13px; font-weight:600; }}
.help-bot-avatar {{ width:27px; height:27px; object-fit:cover; border-radius:50%; }}
/* 窄卡（<560px）：目录两栏退回单栏，防挤压（.card 内媒体查询合规，无 viewport
   meta 铁律不受影响；置于样式块末尾保证覆盖基线规则）。 */
@media (max-width:559px) {{ .help-grid.masonry {{ column-count:1; }}
.help-grid.masonry .command-list {{ grid-template-columns:1fr; }} }}
</style></head><body><div class="help-stage card"><section class="help-shell">
{blobs_html}
<header class="help-head"><div class="avatar-wrap">{avatar_block}</div><div class="head-main"><div class="help-kicker">{_esc(role)}</div><div class="help-title">{_esc(header_title)}</div>{subtitle_html}</div><div class="help-chip">发 /bot help 获取本图</div></header><main class="help-body"><div class="help-grid {grid_cls}">{cards}</div></main><footer class="help-foot"><span class="tip">参数标注：&lt;&gt; 必填，[] 可选；群里直接发命令即可触发。</span><div class="help-bot-pill">{avatar}<span>{_esc(bot_name)}</span></div></footer></section></div>
</body></html>"""


def _help_category_body(query: str, *, is_admin: bool) -> str | None:
    """分类名（如「大模型」「子功能」「管理员」）→ 该分类的说明书页。

    命中分类时返回首行为标题、每个模块一节的完整命令正文；未命中返回 None。
    """
    q = query.strip().lower()
    if not q:
        return None
    for name, topics in _HELP_CATEGORIES:
        n = name.lower()
        if q == n or n.startswith(q) or q in n:
            entries = [
                entry
                for entry in _visible_help_entries(is_admin)
                if entry["topic"] in topics
            ]
            if not entries:
                return None
            lines = [f"{name} · 命令手册"]
            for entry in entries:
                lines.append(f"【{entry['topic']}】")
                for line in entry["lines"]:
                    lines.extend(_split_facets(str(line)))
            return "\n".join(lines)
    return None


def _try_render_help_image(
    body: str,
    *,
    render_backend: Any | None,
    card_dir: str,
    request_id: str,
    is_admin: bool,
    bot_name: str,
    bot_avatar_url: str = "",
    accent_color: str = "",
    sections: list[tuple[str, list[tuple[str, str]]]] | None = None,
) -> str:
    if render_backend is None or not getattr(render_backend, "available", False):
        return ""
    try:
        png = render_backend.render_card(
            {
                "html": _help_mica_html(
                    body,
                    is_admin=is_admin,
                    bot_name=bot_name,
                    bot_avatar_url=bot_avatar_url,
                    accent_color=accent_color,
                    sections=sections,
                ),
                "viewport": {"width": 1040, "height": 1200},
                "device_scale_factor": 2,
                "wait_ms": 0,
            }
        )
        if not isinstance(png, bytes) or not png:
            return ""
        target = Path(card_dir or "data/cards")
        target.mkdir(parents=True, exist_ok=True)
        # 摘要只按内容（admin/正文），同内容复用同一文件——request_id 参与摘要
        # 会让每次请求都生成新文件，data/cards 无界增长（audit #13）。
        digest = hashlib.sha1(f"{is_admin}:{body}".encode()).hexdigest()[:12]
        path = target / f"help_{digest}.png"
        path.write_bytes(png)
        try:
            from plugins.bot_unified_runtime.domains.chat_reply.runtime.cache_policy import (
                prune_prefixed,
            )

            prune_prefixed(target, "help", keep=200)
        except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响本次出图。
            pass
        return str(path)
    except Exception:  # noqa: BLE001 - 图片帮助失败时保留纯文本帮助。
        return ""


_COMMANDS_CATALOG_QUERY = frozenset({"commands", "cmds", "命令", "命令列表", "命令目录"})


def build_commands_catalog_body(*, is_admin: bool = False) -> str:
    """`/bot commands` 命令目录：机器可读纯文本，不走帮助卡渲染。

    自动生成，数据源两处，新增能力无需改本函数：
    - runtime.base_router 路由注册表（确定性路由：kind/capability/优先级）；
    - echo._HELP_ENTRIES（帮助模块：主题/别名/可见性）。
    行格式：区段头 `[名称] 字段 | 字段 | …`，数据行以 ` | ` 分隔。
    非管理员只列公开模块（与帮助总览同门控）；路由表为公开路由语义，全列。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
        list_route_rules_for_audit,
    )

    rules = sorted(list_route_rules_for_audit(), key=lambda item: int(item["priority"]))
    lines = [
        "命令目录 v1（机器可读：区段头 [名称]，数据行「字段 | 字段 | …」；模块详情 /bot help 模块名）",
        f"[routes] priority | kind | capability_id | label（{len(rules)} 条）",
    ]
    for rule in rules:
        lines.append(
            f"{rule['priority']} | {rule['kind']} | {rule['capability_id']} | {rule['label']}"
        )
    entries = _visible_help_entries(is_admin)
    lines.append(f"[commands] topic | aliases | access（{len(entries)} 条）")
    for entry in entries:
        aliases = "/".join(str(alias) for alias in (entry.get("aliases") or ())) or str(
            entry["topic"]
        )
        access = "admin" if entry.get("admin_only") else "public"
        lines.append(f"{entry['topic']} | {aliases} | {access}")
    return "\n".join(lines)


_FACET_SPLIT_RE = re.compile(r"；(?=[^；=：]{1,6}=)")


def _split_facets(line: str) -> list[str]:
    """F8（2026-09-12 实弹反馈⑧）：四要素「作用/参数/内容/意义」连排拆行。

    「好感度：作用=查好感；参数=无；内容=卡；意义=可视化」→ 首行保留
    前缀与第一要素，其余要素各占一行（全角空格缩进）。无要素连排的
    普通行原样返回。
    """
    if "=" not in line or "；" not in line:
        return [line]
    parts = [part.strip() for part in _FACET_SPLIT_RE.split(line) if part.strip()]
    if len(parts) <= 1:
        return [line]
    return [parts[0]] + [f"　{part}" for part in parts[1:]]


def build_help_result(
    request_id: str | None = None,
    query: str = "",
    is_admin: bool = False,
    *,
    render_backend: Any | None = None,
    card_dir: str = "data/cards",
    bot_name: str = "守岸人",
    bot_avatar_url: str = "",
    accent_color: str = "",
) -> CapabilityResult:
    cleaned = parse_help_command_text(query)
    if cleaned.strip().lower() in _COMMANDS_CATALOG_QUERY:
        # 命令目录：文本直出，不做帮助卡渲染（与 /bot help 不重复）。
        return CapabilityResult(
            request_id=request_id or new_request_id("commands"),
            capability_id="bot.commands",
            kind="text",
            title="命令目录",
            body=build_commands_catalog_body(is_admin=is_admin),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=["help", "commands_catalog"],
        )
    topic = normalize_help_topic(cleaned)
    page = 1 if cleaned in {"1", "2"} else None
    is_index = not cleaned or page is not None
    if is_index:
        body = _help_index_body(page=page or 1, is_admin=is_admin)
    elif topic is None:
        body = _help_category_body(cleaned, is_admin=is_admin) or _help_unknown_body(cleaned)
    else:
        entry = next(item for item in _HELP_ENTRIES if item["topic"] == topic)
        if not is_admin and entry["topic"] not in _PUBLIC_HELP_TOPICS:
            body = _help_unknown_body(cleaned)
        else:
            # M7：`detail` 字段过去是**只写死数据**——全部条目的四段式文案
            # （板块介绍 / 命令与参数 / 参数范围 / 设置效果）全部写好了，
            # 但没有任何读取点，深度页只输出 `lines` 的简表。
            # 这里把它接进 `/bot help <模块>` 的详情页，同时保留 `lines`，
            # 让"计划 D 四段式深度教学版"直接落地而不是从零重写。
            body = entry["title_line"] + "\n" + "\n".join(
                split
                for line in entry["lines"]
                for split in _split_facets(str(line))
            )
            detail_text = _strip_help_command_section(str(entry.get("detail") or "")).strip()
            if detail_text:
                detail_text = "\n".join(
                    split
                    for detail_line in detail_text.splitlines()
                    for split in _split_facets(detail_line)
                )
            if detail_text and detail_text not in body:
                body = f"{body}\n\n{detail_text}"
    actual_request_id = request_id or new_request_id("help")
    image_path = _try_render_help_image(
        body,
        render_backend=render_backend,
        card_dir=card_dir,
        request_id=actual_request_id,
        is_admin=is_admin,
        bot_name=bot_name,
        bot_avatar_url=bot_avatar_url,
        accent_color=accent_color,
        sections=_help_index_sections(is_admin) if is_index else None,
    )
    if image_path:
        return CapabilityResult(
            request_id=actual_request_id,
            capability_id="bot.help",
            kind="image",
            title="",
            body="",
            images=[{"type": "image", "file": image_path}],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=["help", "help_image", "help_page:1"],
        )
    return CapabilityResult(
        request_id=actual_request_id,
        capability_id="bot.help",
        kind="text",
        title="帮助",
        body=body,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
    )


_ADDRESSING_GENDER_VALUES = ("male", "female", "nonbinary", "custom", "unknown")
_ADDRESSING_NAME_MAX_CHARS = 32
# 用户自助面（绕管理员门、只能动自己的记录）。关系档三枚（2026-09-24 裁定 R2 A）
# 与称谓/性别同权：词表真身住 character/relationships.py，本处只列**子命令名**，
# 不抄第二份关系名单（抄了就是第二真身，"零副本"纪律）。
_IDENTITY_PREFERENCE_SUBCOMMANDS = frozenset(
    {
        "set-name", "set-gender", "unset-name", "unset-gender",
        "set-relation", "unset-relation", "show-relation",
    }
)


def _identity_preference_usage() -> str:
    return (
        "用法：/bot identity set-name <称呼> | set-gender <male|female|nonbinary|custom|unknown>"
        " | unset-name | unset-gender"
        " | set-relation <关系> | unset-relation | show-relation"
        "（只能设置你自己的称谓偏好，无需管理员；set 即记录、unset 即清除）"
    )


def _identity_preference_result(
    request_id: str, body: str, *, risk_level: RiskLevel = RiskLevel.LOW
) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id,
        capability_id="bot.identity",
        kind="text",
        title="称谓偏好",
        body=body,
        confidence=1.0,
        risk_level=risk_level,
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["identity", "identity_preference"],
    )


def _identity_relation_result(
    store: Any,
    request_id: str,
    sub: str,
    command_text: str,
    *,
    session_type: str,
    session_id: str,
    sender: str,
) -> CapabilityResult:
    """/bot identity set-relation|unset-relation|show-relation —— 用户自助关系档。

2026-09-24 用户裁定 R2 A：亲密档浅档不再由 Master Love 独占，用户可以直接说
「我们是恋人/夫妻/我妈的孩子…」这类关系。词的**真身**只住
`character/relationships.py`（受控词表 + 每档语气指令），本函数只做命令面：

- 词表外的输入（打错字、没裁过的关系）**不落档也不清档**，回话给
  `relationship_vocabulary_text()` 的投影——绝不在 echo 里再抄一份名单；
- 只改称呼、语气与投入度：内容放行面仍由 `content_route.explicit_allowed_for_session`
  会话门决定，六条硬线任何关系压不过（`security/content_safety.py`）；
- 作用域键与称谓偏好同一位（群里=这个群+你，私聊=你），仅本人可动自己的。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.relationships import (
        relationship_vocabulary_text,
    )

    lookup: dict[str, str] = {
        "session_type": session_type,
        "session_id": session_id,
        "sender_id": sender,
    }
    if sub == "show-relation":
        current = store.get_relationship(**lookup)
        if not current:
            return _identity_preference_result(
                request_id,
                "这一档你还没设定过，守岸人按相处深浅自然来。想直说就发"
                " /bot identity set-relation <关系>。",
            )
        return _identity_preference_result(
            request_id,
            f"当前关系档：{current}。只改变你们之间的称呼、语气与投入度，"
            "不改变内容放行面，也不推翻任何既有的身份与称谓事实。",
        )
    if sub == "unset-relation":
        current = store.get_relationship(**lookup)
        if not current:
            return _identity_preference_result(
                request_id, "你还没有设定过关系档，没有要清的东西（称谓偏好与性别自述照旧）。"
            )
        store.set_relationship(**lookup, relationship="")
        return _identity_preference_result(
            request_id,
            f"已清除关系档（原先记的是「{current}」），回到按相处深浅自然来；"
            "称谓偏好与性别自述没有动。",
        )
    raw = command_text.removeprefix("set-relation")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        return _identity_preference_result(
            request_id,
            "关系须为一行普通文字（不含换行/制表），例如 /bot identity set-relation 恋人。",
            risk_level=RiskLevel.MEDIUM,
        )
    value = " ".join(raw.split())
    if not value:
        return _identity_preference_result(
            request_id,
            "用法：/bot identity set-relation <关系>。可填的档："
            + relationship_vocabulary_text(),
        )
    stored = store.set_relationship(**lookup, relationship=value)
    if not stored:
        return _identity_preference_result(
            request_id,
            "这一档词表里没有，原有的关系档一个字都没动。可填的档："
            + relationship_vocabulary_text()
            + "（口语别名也认；一次只认一档，同时命中两档按歧义不记录）。",
            risk_level=RiskLevel.MEDIUM,
        )
    return _identity_preference_result(
        request_id,
        f"已记下：这一档按「{stored}」相处。它只改变称呼、语气与投入度，"
        "内容放行面与六条红线一格都没动。",
    )


def build_identity_preference_result(
    config: object,
    *,
    request_id: str,
    sender_id: str,
    group_id: str = "",
    command_text: str,
) -> CapabilityResult:
    """/bot identity set-name|set-gender|unset-name|unset-gender —— 用户自助称谓偏好。

    关系档三枚（set-relation/unset-relation/show-relation）同面同权，转
    `_identity_relation_result` 处理（同一存储、同一作用域键，只是列不同）。
    与管理员会话身份（session_identity）不同：这里写的是「用户显式声明」，
    存进 AddressingPreferenceStore，被聊天人格上下文优先读取
    （键位与读取端 providers.build_context 完全一致：群=group_id，私聊=空）。
    仅能操作发送者本人的偏好，无管理员门槛。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        build_addressing_preference_store,
    )

    parts = command_text.split()
    sub = parts[0].lower() if parts else ""
    if sub not in _IDENTITY_PREFERENCE_SUBCOMMANDS:
        return _identity_preference_result(request_id, _identity_preference_usage())
    if not str(sender_id or "").strip():
        return _identity_preference_result(
            request_id,
            "无法识别发送者，暂时记不了称谓偏好。",
            risk_level=RiskLevel.MEDIUM,
        )
    store = build_addressing_preference_store(config)
    if store is None:
        return _identity_preference_result(
            request_id,
            # 审查 Q-04：自称统一第三人称「守岸人」（原两处第一人称自称，旧句已废；
            # 回潮由 test_user_copy_unification_gate 拦截）。
            "守岸人这边记称谓的小本本暂时打不开，是守岸人自己要修的。你可以稍后再发一次 set-name，还不行就找管理员。",
            risk_level=RiskLevel.MEDIUM,
        )
    # 键位必须与读取端 providers.build_context 完全一致：群=group_id，私聊=空。
    session_type = "group" if str(group_id or "").strip() else "private"
    session_id = str(group_id or "").strip() if session_type == "group" else ""
    sender = str(sender_id).strip()
    if sub == "set-name":
        raw_name = command_text.removeprefix("set-name")
        # 消毒：拒绝换行/制表等控制字符（防持久化后经人格上下文分区注入提示）；
        # 多内部连续空格折叠为单个；既有合法一行称呼行为不变（帮助口径 ≤32 字）。
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_name):
            return _identity_preference_result(
                request_id,
                f"称呼须为一行普通文字（不含换行/制表），≤{_ADDRESSING_NAME_MAX_CHARS} 字，"
                "重新说一个吧。",
                risk_level=RiskLevel.MEDIUM,
            )
        name = " ".join(raw_name.split())
        if not name:
            return _identity_preference_result(
                request_id, f"用法：/bot identity set-name <称呼>（必填，≤{_ADDRESSING_NAME_MAX_CHARS} 字）"
            )
        if len(name) > _ADDRESSING_NAME_MAX_CHARS:
            return _identity_preference_result(
                request_id,
                f"这个称呼太长（{_ADDRESSING_NAME_MAX_CHARS} 字以内才记得住），重新说一个吧。",
                risk_level=RiskLevel.MEDIUM,
            )
        store.set(
            session_type=session_type, session_id=session_id, sender_id=sender,
            addressing_preference=name,
        )
        return _identity_preference_result(
            request_id, f"已记下：以后称呼你为「{name}」。（仅影响称呼与语气，人格不变）"
        )
    if sub == "set-gender":
        raw = command_text.removeprefix("set-gender").strip()
        value = raw.split()[0].lower() if raw.split() else ""
        if value not in _ADDRESSING_GENDER_VALUES:
            choices = " / ".join(_ADDRESSING_GENDER_VALUES)
            return _identity_preference_result(
                request_id,
                f"性别自述只接受这些值：{choices}（大小写不敏感）。刚才那句没有记录。",
                risk_level=RiskLevel.MEDIUM,
            )
        store.set(
            session_type=session_type, session_id=session_id, sender_id=sender,
            gender_identity=value,
        )
        return _identity_preference_result(
            request_id, f"已记下你的性别自述：{value}。仅用于称呼与语气分寸。"
        )
    # 关系档三枚（2026-09-24 用户裁定 R2 A）：走 AddressingPreferenceStore 的
    # set_relationship/get_relationship 两条口，与称谓偏好同一行记录、同一作用域键
    # （群里=「这个群+你」、私聊=你）。**不许在 echo 里抄一份关系名单**——非法值回显
    # 用 character/relationships.py::relationship_vocabulary_text() 投影（第二真身纪律）。
    if sub in ("set-relation", "unset-relation", "show-relation"):
        return _identity_relation_result(
            store,
            request_id,
            sub,
            command_text,
            session_type=session_type,
            session_id=session_id,
            sender=sender,
        )
    # unset-name / unset-gender：store.clear 为整行清除（称谓与性别自述一并移除）。
    # ⚠ 关系档**不走**这里——unset-relation 只清关系那一列（见上分支），因为这两个
    # 子命令的历史语义就是"整行删除"，把它们拆开各自可撤销才是用户要的。
    before_preference, before_gender = store.get(
        session_type=session_type, session_id=session_id, sender_id=sender
    )
    store.clear(session_type=session_type, session_id=session_id, sender_id=sender)
    if not before_preference and before_gender == "unknown":
        return _identity_preference_result(request_id, "你还没有设置过称谓偏好。")
    return _identity_preference_result(
        request_id, "已清除称谓偏好（整条记录移除，含性别自述），恢复自动称呼。"
    )


# ---- 中央能力健康度读出（S-HEALTH 席：收口 R2「中央登记了探针却零生产读者」）----
#: 非可用态一行最多点名几条，其余折叠成「等 N 项」（status 已经很长，防刷屏）。
_HEALTH_ATTENTION_PREVIEW = 4


def _capability_health_line(config: Config) -> str:
    """中央能力健康度摘要一行（只调用中央件，判据与探针真身都在别处）。

    真读的是 ``runtime/capability_protocols`` 的 `CapabilityInvoker.health()`
    （= `compute_health(descriptor, probes, config)`）对**在册且声明了 health_probe**
    的能力逐个取回的 `CapabilityHealth`。本函数只做展示聚合：不复制枚举、不新建
    探针、不解释判据——中央面才是唯一真身。

    三条硬约束（缺一即回退）：
    - **惰性**：中央模块与 invoker 都在函数体内取（import 期/装配期零触发探测）；
      探针自身也是被调才跑（实测 12 项聚合 ≈0ms、零网络——配置/文件面探针）。
    - **fail-open**：取不到 invoker / 探测抛异常 / 中央无探针 ⇒ 出诚实降级行，
      绝不让 status 整体失败，也绝不把"没读到"说成"没问题"。
    - **不假绿**：只有全部被探测能力都是 ``available`` 才写 ``verdict=全部可用``；
      其余任何组合（含 degraded/disabled/not_configured/unknown）一律
      ``verdict=部分不可用``，并逐条点名（截断到上限定额）。

    与既有语音行的分工（**非重复真身**）：`voice_status_line` 报的是语音引擎
    **TCP 可达性**（只读探测），`_probe_tts` 报的是**配置面三态**（docstring 明写
    零网络、绝不碰无鉴权的 `/control`）；两行两个事实，故并列新增而非替换。
    """
    try:
        from plugins.bot_unified_runtime.runtime import capability_protocols

        invoker = capability_protocols.default_invoker()
        readings: list[tuple[str, str]] = []
        for capability_id in sorted(capability_protocols.registered_capability_ids()):
            probed = invoker.health(capability_id, config)
            if probed is None:
                continue
            descriptor, health = probed
            if not str(getattr(descriptor, "health_probe", "") or ""):
                continue  # 无探针＝只是 health_default 静态缺省，不是"探测结论"，不计
            readings.append((capability_id, str(health.value)))
        vocabulary = [member.value for member in capability_protocols.CapabilityHealth]
    except Exception as exc:  # noqa: BLE001 - 中央面坏了也不能拖死状态查询
        return (
            "中央能力态：probe=unavailable，"
            f"reason={type(exc).__name__}（中央面未读到，不作判定）"
        )
    if not readings:
        return "中央能力态：probe=no_probe_registered（中央未登记可读探针，无从判定）"

    counts: dict[str, int] = {name: 0 for name in vocabulary}
    for _, state in readings:
        counts[state] = counts.get(state, 0) + 1
    # 计数顺序跟中央枚举序；中央若将来加值，落在末尾不丢数。
    ordered = [*vocabulary, *(key for key in counts if key not in vocabulary)]
    summary = "，".join(f"{name}={counts[name]}" for name in ordered)
    attention = [f"{cap}:{state}" for cap, state in readings if state != "available"]
    verdict = "全部可用" if not attention else "部分不可用"
    if attention:
        preview = "，".join(attention[:_HEALTH_ATTENTION_PREVIEW])
        if len(attention) > _HEALTH_ATTENTION_PREVIEW:
            preview += f" 等{len(attention)}项"
    else:
        preview = "无"
    return (
        f"中央能力态：probed={len(readings)}，{summary}，"
        f"verdict={verdict}，待关注={preview}"
    )


def _orchestration_execution_line() -> str:
    """中央调度层「管线管理形」在册一行（第三种执行形态，2026-09-22 本波新立）。

    只调用中央件 `capability_protocols.pipeline_managed_execution_cids()` 现算，不复制枚举、
    不手抄名单（对齐 AGENTS 铁律 10：叙述面不写会过期的计数）。

    「含义升级」的落点：这几枚层 1 直呼面（bot.chat 主链 / 订阅 outbox / campus 转发 /
    运维告警）以前只在册、没有执行体；现在中央描述符表里各有一枚管线管理形描述符 + 信封
    handler，`default_invoker().invoke` 认得并能真跑（包裹 `pipeline.handle_async`）。
    诚实边界：**生产根尚未把 handle_async 改道经中央出口**（根文件另一波在改）⇒ 现网仍走
    泛型直呼，缺口账对它们按 generic/not_wired 现算、不记通电——「能跑」不等于「已接」。
    fail-open：读不到中央面出诚实降级行，绝不让 status 整体失败、绝不把"没读到"说成"没问题"。
    """
    try:
        from plugins.bot_unified_runtime.runtime import capability_protocols

        ids = capability_protocols.pipeline_managed_execution_cids()
    except Exception as exc:  # noqa: BLE001 - 中央面坏了也不能拖死状态查询
        return (
            f"中央调度层·管线管理形：unavailable，reason={type(exc).__name__}"
            "（中央面未读到，不作判定）"
        )
    if not ids:
        return "中央调度层·管线管理形：在册 0 枚（第三种执行形态尚未登记）"
    preview = "、".join(sorted(ids))
    return (
        f"中央调度层·管线管理形：在册 {len(ids)} 枚（{preview}），"
        "执行形=管线管理(pipeline.handle_async)，待生产根改道通电"
    )


def _build_status_body(config: Config, runtime_control: RuntimeControlState) -> str:
    persona_total, persona_missing = _count_missing_paths(config.bot_persona_files)
    knowledge_total, knowledge_missing = _count_missing_paths(config.bot_knowledge_files)
    runtime_hard_state = "enabled" if config.bot_runtime_enabled else "disabled"
    runtime_soft_paused = str(runtime_control.paused).lower()
    memory_state = "enabled" if config.bot_memory_enabled else "disabled"
    memory_db_state = "set" if config.bot_memory_db_path else "missing"
    history_state = "enabled" if config.bot_history_enabled else "disabled"
    history_db_state = "set" if config.bot_history_db_path else "missing"
    diagnostics_state = "enabled" if config.bot_diagnostics_enabled else "disabled"
    diagnostics_db_state = "set" if config.bot_diagnostics_db_path else "missing"
    audit_state = "enabled" if config.bot_audit_enabled else "disabled"
    audit_store = "sqlite" if config.bot_audit_enabled and config.bot_audit_db_path else "memory"
    audit_db_state = "set" if config.bot_audit_db_path else "missing"
    receipts_state = "enabled" if config.bot_receipts_enabled else "disabled"
    receipts_store = (
        "sqlite" if config.bot_receipts_enabled and config.bot_receipts_db_path else "memory"
    )
    receipts_db_state = "set" if config.bot_receipts_db_path else "missing"
    send_queue_state = "enabled" if config.bot_send_queue_enabled else "disabled"
    send_queue_store = (
        "sqlite"
        if config.bot_send_queue_enabled and config.bot_send_queue_db_path
        else "memory"
    )
    send_queue_db_state = "set" if config.bot_send_queue_db_path else "missing"
    send_queue_worker_state = (
        "enabled" if config.bot_send_queue_worker_enabled else "disabled"
    )
    emotion_state = "enabled" if config.bot_emotion_enabled else "disabled"
    rate_limit_state = "enabled" if config.bot_rate_limit_enabled else "disabled"
    rate_limit_store = "sqlite" if config.bot_rate_limit_db_path else "memory"
    rate_limit_db_state = "set" if config.bot_rate_limit_db_path else "missing"
    rate_limit_bypass = ",".join(config.bot_rate_limit_bypass_roles) or "-"
    quiet_hours_state = "enabled" if config.bot_quiet_hours_enabled else "disabled"
    quiet_hours_sessions = ",".join(config.bot_quiet_hours_session_types) or "-"
    quiet_hours_bypass = ",".join(config.bot_quiet_hours_bypass_roles) or "-"
    chat_state = "enabled" if config.bot_chat_enabled else "disabled"
    api_key_state = "set" if config.bot_chat_api_key else "missing"
    role_counts = build_role_settings(config).counts()
    llm_readiness = run_config_smoke(config)
    llm_reasons = _format_reason_list(llm_readiness["llm_readiness_reasons"])
    body = "\n".join(
        [
            "统一运行时在线",
            f"运行时硬开关：{runtime_hard_state}",
            (
                f"运行时软暂停：{runtime_soft_paused}，"
                f"reason={runtime_control.reason}，"
                f"updated_by={runtime_control.updated_by_state}"
            ),
            (
                "权限角色："
                f"admins={role_counts['admin']}，"
                f"enterprise={role_counts['enterprise']}，"
                f"trusted={role_counts['trusted']}，"
                f"blocked={role_counts['blocked']}"
            ),
            f"人格：{config.bot_persona_profile_id} / {config.bot_persona_display_name}",
            f"人格版本：{config.bot_persona_version}",
            f"人格文件：{persona_total} 个，缺失 {persona_missing} 个",
            f"知识文件：{knowledge_total} 个，缺失 {knowledge_missing} 个",
            f"记忆：{memory_state}，db={memory_db_state}",
            (
                f"最近对话：{history_state}，db={history_db_state}，"
                f"max_turns={config.bot_history_max_turns}，"
                f"max_items={config.bot_history_max_items}"
            ),
            (
                f"运行诊断：{diagnostics_state}，db={diagnostics_db_state}，"
                f"max_items={config.bot_diagnostics_max_items}"
            ),
            (
                f"审计：{audit_state}，store={audit_store}，"
                f"db={audit_db_state}，max_items={config.bot_audit_max_items}"
            ),
            (
                f"发送回执：{receipts_state}，store={receipts_store}，"
                f"db={receipts_db_state}，max_items={config.bot_receipts_max_items}"
            ),
            (
                f"发送队列：{send_queue_state}，store={send_queue_store}，"
                f"db={send_queue_db_state}，"
                f"max_items={config.bot_send_queue_max_items}，"
                f"max_attempts={config.bot_send_queue_max_attempts}，"
                f"retry={config.bot_send_queue_retry_base_seconds}-"
                f"{config.bot_send_queue_retry_max_seconds}s，"
                f"worker={send_queue_worker_state}，"
                f"interval={config.bot_send_queue_worker_interval_seconds}s，"
                f"batch={config.bot_send_queue_worker_batch_size}"
            ),
            f"情绪感知：{emotion_state}，max_signals={config.bot_emotion_max_signals}",
            (
                "回复限速："
                f"{rate_limit_state}，"
                f"store={rate_limit_store}，"
                f"db={rate_limit_db_state}，"
                f"window={config.bot_rate_limit_window_seconds}s，"
                f"global={config.bot_rate_limit_chat_global_max_requests}，"
                f"session={config.bot_rate_limit_chat_session_max_requests}，"
                f"sender={config.bot_rate_limit_chat_sender_max_requests}，"
                f"target_min_interval={config.bot_rate_limit_target_min_interval_seconds}s，"
                f"bypass={rate_limit_bypass}"
            ),
            (
                "安静时间："
                f"{quiet_hours_state}，"
                f"{config.bot_quiet_hours_start}-{config.bot_quiet_hours_end}，"
                f"tz={config.bot_quiet_hours_timezone}，"
                f"sessions={quiet_hours_sessions}，"
                f"bypass={quiet_hours_bypass}"
            ),
            (
                f"LLM：{config.bot_chat_provider}，model={config.bot_chat_model}，"
                f"api_key={api_key_state}，chat={chat_state}"
            ),
            (
                f"LLM就绪：{llm_readiness['llm_readiness_status']}，"
                f"ready_for_real_llm={str(bool(llm_readiness['ready_for_real_llm'])).lower()}"
            ),
            f"LLM下一步：{llm_readiness['llm_next_action']}",
            f"LLM原因：{llm_reasons}",
            # 中央调度层「管线管理形」在册行（第三种执行形态，2026-09-22 本波新立）：
            # 只读中央件现算、fail-open；这几枚直呼面已登记真实执行形、invoke 认得能跑，
            # 但生产根未改道 ⇒ 行内如实标"待通电"。刻意放在语音/健康两行**之前**——
            # `test_capability_health_readout` 钉死语音行=lines[-2]、健康行=lines[-1]，
            # 追加在其后会顶漂那两条既有末行判据（属行为回归，禁改测试）。
            # 中央调度收编波 P5-E3：绘画/语音对接点缺位行（**同一判据源** reserved_provider，
            # 禁在本文件另算一遍）。刻意插在 `_orchestration_execution_line()` 之前：
            # `test_capability_health_readout` 钉死语音行=lines[-2]、健康行=lines[-1]，
            # 追加到末尾会顶漂那两条既有末行判据（同上方编排行的处理）。
            creation_status_line(config),
            _orchestration_execution_line(),
            # U-17=C 语音健康探针接线（T79 清单，触发点 1=status 查询）：
            # health 缺省=惰性探测（开关关时绝不真探）；≤2s 超时钳制、fail-open。
            # 管理门已在本能力上游，健康态不出普通成员面。注意：探针构造的
            # tts_service_unreachable issue **不**贴附到本 CapabilityResult——
            # 带 issue 的结果会触发 pipeline A-19 群聊吞体（status 本身没失败），
            # 且探针模块 `_last_issue` 不随读/恢复清空，贴附=陈旧 issue 永久
            # 误报；投喂中央告警链的正确落点是触发点 2（tts.py 退避窗进入沿）。
            voice_status_line(config),
            # S-HEALTH（R2 收口）：中央能力健康度的**第一个生产读者**。
            # 只新增一行、不碰上面任何既有行；探测惰性、失败诚实降级（见函数 docstring）。
            _capability_health_line(config),
        ]
    )
    # S-OBS：状态查询是语音探针的触发点 1。上面 voice_status_line 已惰性探测；此处把
    # 本次探测出的 pending issue 经**唯一消费者**交给中央告警链（sink 由 root 装配注入）。
    # fail-open、无 sink=诚实 no-op、投一次清一次；不贴本结果的 operational_issue 面
    # （贴附会触发 pipeline A-19 群聊吞体，见上方注释与 voice_health_probe docstring）。
    flush_probe_issue_to_alerts()
    # P5-E3 同构：状态查询同样是 creation 缺位告警的触发点（上面 creation_status_line
    # 已现算并整体替换 pending）。共用 root 注入的同一个 sink，投一次清一次。
    flush_reserved_issues_to_alerts()
    return body


def _count_missing_paths(paths: list[str]) -> tuple[int, int]:
    total = len(paths)
    missing = sum(1 for path in paths if not Path(path).expanduser().is_file())
    return total, missing


def _format_reason_list(value: object) -> str:
    if not isinstance(value, list):
        return "-"
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return ",".join(cleaned) if cleaned else "-"

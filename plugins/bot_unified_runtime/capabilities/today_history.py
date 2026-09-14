"""「历史上的今天」能力（bot.today_history）。

命令（无需前缀，消息以「历史上的今天」开头即触发）：
- 历史上的今天                → 当天条目
- 历史上的今天 设置 8:00      → 本会话（私聊/群）每日定时推送
- 历史上的今天 状态           → 查看推送时间
- 历史上的今天 取消           → 取消推送

订阅表存在 data/today_history_push.json（git 忽略），
{ "f_<user_id>": {"hour":8,"minute":0}, "g_<group_id>": {...} }。
NoneBot 入口在启动/bot 连接时按表注册 APScheduler 定时任务。

事件列表在渲染后端可用时合成 Mica 信息卡图（复用解析卡的 render_card_png
管线），文本作 caption/兜底——后端缺失或渲染失败时输出与纯文字版完全一致。
"""

from __future__ import annotations

import json
import logging
import random
import re
import shutil
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.capabilities import user_copy
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.sources.today_history import (
    TodayHistoryProvider,
    format_history_text,
)

logger = logging.getLogger(__name__)

# 英文短语右侧词边界（stocks _alias_hit 先例）：historyqq 类字母延续不触发；
# 中文别名与全角标点后缀（today in history？）不受影响。
_QUERY_RE = re.compile(
    r"^[/!！]?(?:历史上的今天|歷史上的今天|today in history(?![a-z0-9])"
    # 拼音全拼/缩写（T-Spec T1.5/T1.6）：lishishangdejintian 同覆盖繁体同音；
    # lssd 为截断缩写（原 lssdjt，≤4 位口径），查重无冲突；前缀锚定防左胶合，
    # (?![A-Za-z0-9]) 防右胶合（lssdqq）。
    r"|lishishangdejintian(?![A-Za-z0-9])|lssd(?![A-Za-z0-9]))\s*(?P<arg>.*)$",
    re.IGNORECASE,
)
# 短别名必须带斜杠，避免把普通聊天里的“历史”一词误触发；
# 英文 today/history 同门槛（T-Spec T1.2：today in history 短语可裸发，
# today/history 单词与「历史」同属聊天高频词，必须带斜杠）。
# 拼音同门槛（T-Spec T1.5/T1.6）：lishi/jinrilishi/ls/jrls 须 /前缀，
# 斜杠门槛天然低误伤（/ls 冲突组=历史×歷史 同源变体不算冲突）。
_SHORT_RE = re.compile(
    r"^[/!！](?:历史|今日历史|歷史|今日歷史|today|history"
    r"|lishi(?![A-Za-z0-9])|jinrilishi(?![A-Za-z0-9])|ls(?![A-Za-z0-9])|jrls(?![A-Za-z0-9]))\s*(?P<arg>.*)$",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"(\d{1,2})[:：](\d{1,2})")


def is_today_history_command(text: str) -> bool:
    stripped = text.strip()
    return _QUERY_RE.match(stripped) is not None or _SHORT_RE.match(stripped) is not None


def _load_push_table_checked(push_file: str) -> tuple[dict[str, dict[str, int]], bool]:
    """读取推送表；第二个返回值=False 表示文件损坏/不可读——调用方必须拒绝改写，
    否则只含当前条目的新表会整体覆写掉其他会话的订阅（数据丢失）。"""
    try:
        path = Path(push_file)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data, True
            return {}, False
    except (OSError, ValueError):
        return {}, False
    return {}, True


def _load_push_table(push_file: str) -> dict[str, dict[str, int]]:
    """兼容旧签名（__init__.py 调度注册用，只读不写）。"""
    return _load_push_table_checked(push_file)[0]


def _save_push_table(push_file: str, table: dict[str, dict[str, int]]) -> bool:
    """写盘成功返回 True；失败由调用方回错，不得静默吞掉。"""
    try:
        path = Path(push_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(table, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        logger.warning("push table save failed (%s): %s", push_file, exc)
        return False


def _card_dir_token(raw: str) -> str:
    """去重键 → 安全目录名：只留 ``[0-9A-Za-z_-]``，空则回退随机串。"""
    token = re.sub(r"[^0-9A-Za-z_-]", "", str(raw or ""))[:64]
    return token or uuid.uuid4().hex[:12]


def _prune_card_dirs(root: Path, *, keep: int = 120) -> int:
    """按 mtime 只保留 ``root`` 下最新 ``keep`` 个子目录，淘汰更旧的。

    历史卡按日落独立子目录，``cache_policy.prune_prefixed`` 的平铺文件
    前缀语义不适用；这里只删直接子目录（整棵子树），不碰散落文件。
    失败由调用方吞掉——配额清理绝不阻塞出图。
    """
    if keep <= 0 or not root.is_dir():
        return 0
    entries: list[tuple[int, Path]] = []
    for child in root.iterdir():
        try:
            if child.is_dir():
                entries.append((int(child.stat().st_mtime), child))
        except OSError:
            continue
    entries.sort(reverse=True)
    for _, stale in entries[max(0, keep):]:
        shutil.rmtree(stale, ignore_errors=True)
    return max(0, len(entries) - max(0, keep))


def build_history_card_content(body: str, *, month_day: str = "") -> Any:
    """事件列表 → 通用卡 payload（纯构造，无 IO；能力层与测试共用）。

    ``summary`` 只承载已拉取的真实事件行（截 1200 字），条数随现有结果，
    不为凑数编造；``month_day`` 来自正文首行（同一时间口径），缺省退回
    纯「历史上的今天」标题。``canonical_url`` 恒为 ``about:blank``（F10
    约定：无真实来源的卡不渲染页脚，评审 C2——``history://`` 伪 URL 不得
    泄漏给用户）；同日落盘去重由 ``_render_card`` 的 card_dir 子目录承载。
    """
    from plugins.bot_unified_runtime.contracts import build_parsed_content

    return build_parsed_content(
        platform="today_history",
        item_id="events",
        item_kind="article",
        title=f"历史上的今天 {month_day}" if month_day else "历史上的今天",
        author_name="百度百科 · 历史上的今天",
        summary=body[:1200],
        canonical_url="about:blank",
        parse_depth="deep",
    )


def build_today_history_capability(
    config: Any | None = None,
    *,
    provider: TodayHistoryProvider | None = None,
    push_file: str = "data/today_history_push.json",
    on_subscriptions_changed: Callable[[], None] | None = None,
    render_backend: Any | None = None,
) -> Any:
    if provider is None:
        proxy = str(getattr(config, "bot_download_proxy", "") or "") if config else ""
        cache_file = (
            str(getattr(config, "bot_today_history_cache_file", "") or "")
            if config
            else ""
        ) or "data/today_history_cache.json"
        provider = TodayHistoryProvider(proxy=proxy, cache_file=cache_file)

    # 推送表读-改-写互斥：能力在 offload 线程池并发执行，两个会话同时
    # 设置/取消会互相整表覆写丢订阅（load→change→save 全程持锁）。
    _push_table_lock = threading.Lock()

    def _render_card(body: str, month_day: str) -> str:
        """事件列表合成 Mica 卡图；后端不可用或任何失败返回空串。

        落盘走 ``today_history/<month_day>`` 子目录：同日事件列表内容一致，
        同日同卡同文件（去重）；不同日互不覆写。去重键不进 canonical_url。
        """
        if render_backend is None or not getattr(render_backend, "available", False):
            return ""
        try:
            from plugins.bot_unified_runtime.capabilities.content_parser import (
                render_card_png,
            )

            item = build_history_card_content(body, month_day=month_day)
            base_dir = str(
                getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"
            )
            history_root = Path(base_dir) / "today_history"
            payload = render_card_png(
                render_backend,
                item,
                config=config,
                card_dir=str(history_root / _card_dir_token(month_day or "today")),
                feature_label="历史上的今天",
            )
            if isinstance(payload, dict) and payload.get("file"):
                try:
                    _prune_card_dirs(history_root, keep=120)
                except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响出图。
                    pass
        except Exception:  # noqa: BLE001 - 渲染失败回退纯文本列表。
            return ""
        return str(payload.get("file") or "") if isinstance(payload, dict) else ""

    def _require_group_admin(sender_key: str, decision: BotDecision) -> bool:
        """群推送时间影响全群，设置/取消需要管理员；私聊键自助。"""
        if not sender_key.startswith("g_"):
            return True
        roles = {str(role).strip() for role in (getattr(decision, "actor_roles", None) or [])}
        return "admin" in roles

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        text = message.plain_text.strip()
        match = _QUERY_RE.match(text)
        arg = (match.group("arg") if match else "").strip()
        sender_key = (
            f"g_{message.group_id}"
            if message.group_id
            else f"f_{message.sender_id}"
        )
        table, load_ok = _load_push_table_checked(push_file)

        if arg:
            if "状态" in arg:
                entry = table.get(sender_key)
                if entry:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.today_history",
                        kind="text",
                        body=f"历史上的今天推送时间：{entry['hour']:02d}:{entry['minute']:02d}",
                        audit_tags=["today_history", "push_status"],
                    )
                if not load_ok:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.today_history",
                        kind="text",
                        body="推送表读取失败，请查日志（data/today_history_push.json 可能已损坏）。",
                        audit_tags=["today_history", "push_status", "load_failed"],
                    )
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.today_history",
                    kind="text",
                    body="还没有设置推送。发送「历史上的今天 设置 8:00」开启。",
                    audit_tags=["today_history", "push_status"],
                )
            if "取消" in arg or "关闭" in arg:
                if not _require_group_admin(sender_key, decision):
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.today_history",
                        kind="text",
                        # 审查 Q-02：权限拒绝入 user_copy 池（守岸人语气轮换）。
                        body=random.choice(user_copy.ADMIN_GATE_TEMPLATES).format(action="取消群推送时间"),
                        audit_tags=["today_history", "push_cancelled", "denied"],
                    )
                if not load_ok:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.today_history",
                        kind="text",
                        body="推送表读取失败，已拒绝改写以免丢失其他订阅。",
                        audit_tags=["today_history", "push_cancelled", "load_failed"],
                    )
                with _push_table_lock:
                    table.pop(sender_key, None)
                    if not _save_push_table(push_file, table):
                        return CapabilityResult(
                            request_id=message.request_id,
                            capability_id="bot.today_history",
                            kind="text",
                            body=user_copy.PUSH_SAVE_FAILED,
                            audit_tags=["today_history", "push_cancelled", "save_failed"],
                        )
                if on_subscriptions_changed is not None:
                    try:
                        on_subscriptions_changed()
                    except Exception:  # noqa: S110, BLE001 - 订阅变更通知失败不影响本次推送设置。
                        pass
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.today_history",
                    kind="text",
                    body="历史上的今天推送已取消。",
                    audit_tags=["today_history", "push_cancelled"],
                )
            if "设置" in arg or "推送" in arg:
                time_match = _TIME_RE.search(arg)
                if not time_match:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.today_history",
                        kind="text",
                        body="用法：历史上的今天 设置 8:00（小时:分钟）",
                        audit_tags=["today_history", "push_bad_format"],
                    )
                hour, minute = int(time_match.group(1)), int(time_match.group(2))
                if hour > 23 or minute > 59:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.today_history",
                        kind="text",
                        body="时间格式不对，小时 0-23、分钟 0-59。",
                        audit_tags=["today_history", "push_bad_format"],
                    )
                if not _require_group_admin(sender_key, decision):
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.today_history",
                        kind="text",
                        # 审查 Q-02：权限拒绝入 user_copy 池（守岸人语气轮换）。
                        body=random.choice(user_copy.ADMIN_GATE_TEMPLATES).format(action="设置群推送时间"),
                        audit_tags=["today_history", "push_subscribed", "denied"],
                    )
                if not load_ok:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.today_history",
                        kind="text",
                        body="推送表读取失败，已拒绝改写以免丢失其他订阅。",
                        audit_tags=["today_history", "push_subscribed", "load_failed"],
                    )
                with _push_table_lock:
                    table[sender_key] = {"hour": hour, "minute": minute}
                    if not _save_push_table(push_file, table):
                        return CapabilityResult(
                            request_id=message.request_id,
                            capability_id="bot.today_history",
                            kind="text",
                            body=user_copy.PUSH_SAVE_FAILED,
                            audit_tags=["today_history", "push_subscribed", "save_failed"],
                        )
                if on_subscriptions_changed is not None:
                    try:
                        on_subscriptions_changed()
                    except Exception:  # noqa: S110, BLE001 - 订阅变更通知失败不影响本次推送设置。
                        pass
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.today_history",
                    kind="text",
                    body=f"每日 {hour:02d}:{minute:02d} 推送历史上的今天，已设置。",
                    audit_tags=["today_history", "push_subscribed"],
                )
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.today_history",
                kind="text",
                body="用法：历史上的今天 设置 8:00 | 状态 | 取消",
                audit_tags=["today_history", "push_bad_format"],
            )

        events = provider.get_events()
        if not events:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.today_history",
                kind="text",
                # 审查 Q-01：入 user_copy 数据源失败池（原「……稍后再试。」）。
                body=random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(
                    reason="历史上的今天数据拉取失败"
                ),
                audit_tags=["today_history", "fetch_failed"],
            )
        body = format_history_text(events)
        # 月份日期取自正文首行（format_history_text 统一时间口径）。
        month_day = body.split("\n", 1)[0].removeprefix("历史上的今天").strip()
        card = _render_card(body, month_day)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.today_history",
            kind="mixed" if card else "text",
            title="历史上的今天",
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "today_history",
                f"today_history_events:{len(events)}",
                "card_rendered" if card else "text_only",
            ],
        )

    return capability


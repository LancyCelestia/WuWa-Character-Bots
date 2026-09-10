"""「历史上的今天」能力（bot.today_history）。

命令（无需前缀，消息以「历史上的今天」开头即触发）：
- 历史上的今天                → 当天条目
- 历史上的今天 设置 8:00      → 本会话（私聊/群）每日定时推送
- 历史上的今天 状态           → 查看推送时间
- 历史上的今天 取消           → 取消推送

订阅表存在 data/today_history_push.json（git 忽略），
{ "f_<user_id>": {"hour":8,"minute":0}, "g_<group_id>": {...} }。
NoneBot 入口在启动/bot 连接时按表注册 APScheduler 定时任务。
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

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

_QUERY_RE = re.compile(r"^[/!！]?(?:历史上的今天|歷史上的今天)\s*(?P<arg>.*)$")
# 短别名必须带斜杠，避免把普通聊天里的“历史”一词误触发。
_SHORT_RE = re.compile(r"^[/!！](?:历史|今日历史|歷史|今日歷史)\s*(?P<arg>.*)$")
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
    except OSError:
        return False


def build_today_history_capability(
    config: Any | None = None,
    *,
    provider: TodayHistoryProvider | None = None,
    push_file: str = "data/today_history_push.json",
    on_subscriptions_changed: Callable[[], None] | None = None,
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
                        body="群推送时间只有管理员可以取消。",
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
                            body="取消失败：推送表写盘出错，请查日志。",
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
                        body="群推送时间只有管理员可以设置。",
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
                            body="设置失败：推送表写盘出错，请查日志。",
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
                body="历史上的今天数据拉取失败，稍后再试。",
                audit_tags=["today_history", "fetch_failed"],
            )
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.today_history",
            kind="text",
            title="历史上的今天",
            body=format_history_text(events),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["today_history", f"today_history_events:{len(events)}"],
        )

    return capability


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
from pathlib import Path
from typing import Any, Callable

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


def _load_push_table(push_file: str) -> dict[str, dict[str, int]]:
    try:
        path = Path(push_file)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        return {}
    return {}


def _save_push_table(push_file: str, table: dict[str, dict[str, int]]) -> None:
    try:
        path = Path(push_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(table, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return


def build_today_history_capability(
    config: Any | None = None,
    *,
    provider: TodayHistoryProvider | None = None,
    push_file: str = "data/today_history_push.json",
    on_subscriptions_changed: Callable[[], None] | None = None,
) -> Any:
    if provider is None:
        proxy = str(getattr(config, "bot_download_proxy", "") or "") if config else ""
        provider = TodayHistoryProvider(proxy=proxy)

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        text = message.plain_text.strip()
        match = _QUERY_RE.match(text)
        arg = (match.group("arg") if match else "").strip()
        sender_key = (
            f"g_{message.group_id}"
            if message.group_id
            else f"f_{message.sender_id}"
        )
        table = _load_push_table(push_file)

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
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.today_history",
                    kind="text",
                    body="还没有设置推送。发送「历史上的今天 设置 8:00」开启。",
                    audit_tags=["today_history", "push_status"],
                )
            if "取消" in arg or "关闭" in arg:
                table.pop(sender_key, None)
                _save_push_table(push_file, table)
                if on_subscriptions_changed is not None:
                    try:
                        on_subscriptions_changed()
                    except Exception:  # noqa: BLE001
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
                table[sender_key] = {"hour": hour, "minute": minute}
                _save_push_table(push_file, table)
                if on_subscriptions_changed is not None:
                    try:
                        on_subscriptions_changed()
                    except Exception:  # noqa: BLE001
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

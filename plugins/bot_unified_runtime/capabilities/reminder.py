"""提醒能力（bot.reminder）：时间点记忆——记住"几点要做什么"，到点主动督促。

触发：
- 自然语言：「12点提醒我写作业」「中午提醒我吃药」「半小时后叫我」
- 管理查询：「提醒列表 / 我的提醒」「取消提醒 <id前缀>」
到点投递由 __init__ 的每分钟调度任务完成（守岸人语气文案）。
"""

from __future__ import annotations

import re
from typing import Any

from plugins.bot_unified_runtime.character.reminders import (
    build_reminder_store,
    parse_reminder_intent,
)
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
)

# 英文 reminder/reminders 精确等值与 my reminders/reminder list 短语为
# T-Spec T1.2 英文触发（列表查询面）；精确等值防英文整句（set a reminder）误触。
# 全拼/缩写（T-Spec T1.5/T1.6 第三批）：列表查询面拼音入表（双侧 ASCII 词边界）。
# 信号词面（提醒/叫我/记得叫 → tixing/jiaowo/jidejiao）不入表：端到端承接依赖
# character/reminders.parse_reminder_intent 的 _REMIND_SIGNAL_RE（白名单外）同步，
# 半边入表只会产生永不命中的死词（fix-py3-report 结构性边界）。
_LIST_RE = re.compile(
    r"提醒列表|我的提醒|看看提醒|有哪些提醒"
    r"|^(?:my\s+)?reminders?$|^(?:reminders?\s+list|list\s+reminders)$"
    r"|(?<![A-Za-z0-9])(?:tixingliebiao|wodetixing|kankantixing|younaxietixing"
    r"|txlb|wdtx|kktx|ynxt)(?![A-Za-z0-9])"
)
_CANCEL_RE = re.compile(r"取消提醒\s*([0-9a-fA-F]{4,12})?")
_SIGNAL_RE = re.compile(r"提醒|叫我|记得叫|記得叫")


def is_reminder_command(text: str) -> bool:
    """路由判定：提醒信号 + （可解析出时间，或是列表/取消查询）。"""
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _LIST_RE.search(stripped) or _CANCEL_RE.search(stripped):
        return True
    if not _SIGNAL_RE.search(stripped):
        return False
    return parse_reminder_intent(stripped) is not None


def build_reminder_capability(config: Any | None = None) -> Any:
    """构建提醒能力：与 eat 等能力一致，返回 (message, decision) -> 结果。"""

    def _result(message: IncomingMessage, body: str, *, tags: list[str]) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.reminder",
            kind="text",
            title="提醒",
            body=body,
            send_policy=SendPolicy.SILENT_AUDIT,
            audit_tags=["reminder", *tags],
        )

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        text = (message.plain_text or "").strip()
        session_key = message.session_id
        store = build_reminder_store(config)
        cancel_match = _CANCEL_RE.search(text)
        if cancel_match:
            prefix = (cancel_match.group(1) or "").strip().lower()
            pending = store.list_pending(session_key, limit=50)
            if not pending:
                return _result(message, "这个会话还没有待办的提醒。", tags=["cancel_empty"])
            if not prefix:
                return _result(
                    message,
                    "要取消哪一条？先看「提醒列表」，再用「取消提醒 <id前几位>」。",
                    tags=["cancel_need_id"],
                )
            hits = [item for item in pending if item.reminder_id.startswith(prefix)]
            if len(hits) != 1:
                return _result(
                    message,
                    f"id 前缀 {prefix} 命中 {len(hits)} 条，需要唯一。",
                    tags=["cancel_ambiguous"],
                )
            store.cancel(hits[0].reminder_id)
            return _result(message, f"好，这条提醒已经放下了：{hits[0].text}", tags=["cancelled"])
        if _LIST_RE.search(text):
            pending = store.list_pending(session_key)
            if not pending:
                return _result(message, "目前没有待办的提醒。", tags=["list_empty"])
            lines = [
                f"- {item.reminder_id[:6]}  {item.remind_at[11:16]}  {item.text}"
                for item in pending
            ]
            return _result(message, "待办提醒：\n" + "\n".join(lines), tags=["listed"])
        intent = parse_reminder_intent(text)
        if intent is None:
            return _result(
                message,
                "想让我什么时候提醒你？例如「12点提醒我写作业」"
                "「明天早上8点叫我起床」「半小时后提醒我去看一下汤」。",
                tags=["usage"],
            )
        reminder = store.add(
            session_key=session_key,
            sender_id=message.sender_id,
            target_scope=message.session_type.value,
            target_id=str(message.group_id or message.sender_id),
            adapter=message.adapter,
            bot_id=message.bot_id,
            remind_at=intent.remind_at,
            text=intent.text,
        )
        return _result(
            message,
            f"记下了。{intent.label}，我会来提醒你：{reminder.text}。"
            f"\n（取消可以说「取消提醒 {reminder.reminder_id[:6]}」）",
            tags=["added"],
        )

    return capability


__all__ = ["build_reminder_capability", "is_reminder_command"]

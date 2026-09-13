"""提醒能力（bot.reminder）：时间点记忆——记住"几点要做什么"，到点主动督促。

触发：
- 自然语言：「12点提醒我写作业」「中午提醒我吃药」「半小时后叫我」
- 管理查询：「提醒列表 / 我的提醒」「取消提醒 <id前缀>」
- 自然语言勾选：「作业做完了」「搞定了报告」→ 模糊匹配未完成提醒与
  笔记待办，命中即勾（2026-09-13 六域批）
- 笔记指令面：「笔记 记…」「笔记列表」「笔记 看 N」「做完 N」「删笔记 N」
  （capabilities/notes.py 承接；复用 REMINDER 路由不新增 RouteKind）
到点投递由 __init__ 的每分钟调度任务完成（守岸人语气分型文案）。
"""

from __future__ import annotations

import re
from typing import Any

from plugins.bot_unified_runtime.capabilities.notes import (
    _NOTES_ADD_RE,
    _NOTES_BARE_RE,
    _NOTES_DELETE_RE,
    _NOTES_DONE_RE,
    _NOTES_LIST_RE,
    _NOTES_VIEW_RE,
    build_notes_capability,
)
from plugins.bot_unified_runtime.character.reminders import (
    NEAR_MISS_FLOOR,
    build_reminder_store,
    match_todo_candidates,
    parse_reminder_intent,
    resolve_todo_match,
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

# ---------------------------------------------------------------------------
# 自然语言勾选（做完了/完成了/搞定 + 事项名）：门槛刻意收紧——短句、
# 非疑问、剥掉信号词后还剩得出事项名，防把普通聊天（"作业终于做完了
# 好开心"）整句吞进勾选面。
# ---------------------------------------------------------------------------

_CHECKOFF_SIGNAL_RE = re.compile(
    r"做完了?|完成了?|搞定了?|弄完了?|干完了?|办完了?|做好了|写完了?|结束了?"
)
_CHECKOFF_CLEAN_RE = re.compile(
    r"做完了?|完成了?|搞定了?|弄完了?|干完了?|办完了?|做好了|写完了?|结束了?"
    r"|[了吗吧呢啊哦呀的把]"
)
_CHECKOFF_MAX_CHARS = 32
_CHECKOFF_QUERY_MAX_CHARS = 20


def extract_checkoff_query(text: str) -> str | None:
    """「做完了 X / X 做完了」→ 事项名；不是勾选形态返回 None。"""
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _CHECKOFF_MAX_CHARS:
        return None
    if any(ch in stripped for ch in "？?"):
        return None
    if not _CHECKOFF_SIGNAL_RE.search(stripped):
        return None
    query = _CHECKOFF_CLEAN_RE.sub("", stripped).strip()
    if not query or len(query) > _CHECKOFF_QUERY_MAX_CHARS:
        return None
    return query


def is_reminder_command(text: str, *, config: Any | None = None) -> bool:
    """路由判定：提醒信号 + （可解析出时间，或是列表/取消查询），
    或笔记指令面，或自然语言勾选形态。"""
    stripped = (text or "").strip()
    if not stripped:
        return False
    # 笔记指令面（开关关掉时整组让路；正则直接引用以便触发体检收割）。
    if (config is None or getattr(config, "bot_notes_enabled", True)) and (
        _NOTES_LIST_RE.search(stripped)
        or _NOTES_DELETE_RE.search(stripped)
        or _NOTES_VIEW_RE.search(stripped)
        or _NOTES_DONE_RE.search(stripped)
        or _NOTES_ADD_RE.search(stripped)
        or _NOTES_BARE_RE.match(stripped)
    ):
        return True
    if _LIST_RE.search(stripped) or _CANCEL_RE.search(stripped):
        return True
    if _SIGNAL_RE.search(stripped) and parse_reminder_intent(stripped) is not None:
        return True
    return extract_checkoff_query(stripped) is not None


def build_reminder_capability(config: Any | None = None) -> Any:
    """构建提醒能力：与 eat 等能力一致，返回 (message, decision) -> 结果。"""
    notes_capability = build_notes_capability(config)

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

    def _checkoff_result(message: IncomingMessage, body: str, *, tags: list[str]) -> CapabilityResult:
        result = _result(message, body, tags=["checkoff", *tags])
        return result

    def _handle_checkoff(
        message: IncomingMessage, query: str
    ) -> CapabilityResult | None:
        """自然语言勾选：模糊匹配未完成提醒 + 笔记待办。

        返回 None 表示本会话没有任何候选（让位给普通提醒语义，避免把
        无关短句抢下来）。
        """
        from plugins.bot_unified_runtime.character.notes_store import build_notes_store

        store = build_reminder_store(config)
        pending = store.list_pending(message.session_id, limit=50)
        notes_enabled = getattr(config, "bot_notes_enabled", True)
        open_todos = []
        if notes_enabled:
            notes_store = build_notes_store(config)
            open_todos = notes_store.list_open_todos(message.session_id, limit=50)
        if not pending and not open_todos:
            return None
        # 候选文本：提醒取原文；笔记待办取**逐条未勾选条目行**（剥勾选框
        # 前缀）而非 display_headline 首行标题——「买牛奶」要对上
        # 「采购清单\n- [ ] 买牛奶」里的那一行，标题匹配永远勾不掉。
        names = [item.text for item in pending]
        todo_owners: list[Any] = []  # 与 names 笔记段一一对应（条目行 → 所属笔记）
        if notes_enabled:
            for todo in open_todos:
                for line_text in todo.todo_match_texts(max_chars=40):
                    names.append(line_text)
                    todo_owners.append(todo)
        outcome, indexes = resolve_todo_match(query, names)
        reminder_count = len(pending)

        def _mark(index: int) -> str:
            if index < reminder_count:
                reminder = pending[index]
                store.mark_done(reminder.reminder_id)
                return reminder.text
            todo = todo_owners[index - reminder_count]
            todo_store = build_notes_store(config)
            todo_store.mark_done(todo.note_id, message.session_id)
            return names[index]

        if outcome == "hit":
            name = _mark(indexes[0])
            return _checkoff_result(
                message,
                f"（轻轻点头）嗯，「{name}」——已经替你放下了。\n"
                "剩下的事不着急，一件一件来。我都在。",
                tags=["checked"],
            )
        if outcome == "ambiguous":
            lines = [f"- {_candidate_label(names[index])}" for index in indexes]
            return _checkoff_result(
                message,
                # 文案审计①：resolve_todo_match 可并列返回 2-3 个候选，
                # 正文不点数（「有几件」），与下方清单同屏不矛盾。
                "有几件事都对得上，是哪一件完成了？\n" + "\n".join(lines),
                tags=["ambiguous"],
            )
        # 未命中：给最接近的候选问一句（低于 NEAR_MISS_FLOOR 的不打扰）。
        near = match_todo_candidates(query, names, min_score=NEAR_MISS_FLOOR)
        if near:
            best = _candidate_label(names[near[0][0]])
            return _checkoff_result(
                message,
                f"这个会话里没有找到能对上「{query}」的事。你是指「{best}」吗？\n"
                "是的话再告诉我一声，我替你勾掉。",
                tags=["nearest"],
            )
        return _checkoff_result(
            message,
            f"现在没有挂着能对上「{query}」的待办——也许早就完成了，或者还没记下来。",
            tags=["no_match"],
        )

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        text = (message.plain_text or "").strip()
        session_key = message.session_id

        # 笔记指令面优先（显式命令形态，不会被提醒/勾选语义抢走）。
        if getattr(config, "bot_notes_enabled", True) and _is_notes_surface(text):
            return notes_capability(message, _decision)

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
                # 文案审计③：裸机器腔（"命中 N 条，需要唯一"）翻人话，
                # 保留前缀与条数这两个可行动信息。
                return _result(
                    message,
                    f"「{prefix}」开头的提醒有 {len(hits)} 条，先「提醒列表」里对一对，"
                    "告诉我要取消哪一条，我再帮你放下。",
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

        query = extract_checkoff_query(text)
        # 勾选只承接无提醒信号的形态（含 提醒/叫我 的句子归提醒语义，防
        # 「提醒我做完作业」被勾选面截走）。
        if query is not None and not _SIGNAL_RE.search(text):
            handled = _handle_checkoff(message, query)
            if handled is not None:
                return handled

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

    def _is_notes_surface(text: str) -> bool:
        stripped = (text or "").strip()
        if not stripped:
            return False
        return bool(
            _NOTES_LIST_RE.search(stripped)
            or _NOTES_DELETE_RE.search(stripped)
            or _NOTES_VIEW_RE.search(stripped)
            or _NOTES_DONE_RE.search(stripped)
            or _NOTES_ADD_RE.search(stripped)
            or _NOTES_BARE_RE.match(stripped)
        )

    return capability


def _candidate_label(name: str) -> str:
    label = str(name or "").strip()
    return label[:40] if label else "(无题)"


__all__ = ["build_reminder_capability", "extract_checkoff_query", "is_reminder_command"]

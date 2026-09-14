"""提醒能力（bot.reminder）：时间点记忆——记住"几点要做什么"，到点主动督促。

触发：
- 自然语言：「12点提醒我写作业」「中午提醒我吃药」「半小时后叫我」
- 管理查询：「提醒列表 / 我的提醒」「取消提醒 <id前缀>」
- 自然语言勾选：「作业做完了」「搞定了报告」→ 模糊匹配未完成提醒与
  笔记待办，命中即勾（2026-09-13 六域批）；勾选消歧追问（审查 A-10/A-11，
  2026-09-14）：唯一候选但相似度不足回肯定词确认、歧义清单回序号择一
- 笔记指令面：「笔记 记…」「笔记列表」「笔记 看 N」「做完 N」「删笔记 N」
  （capabilities/notes.py 承接；复用 REMINDER 路由不新增 RouteKind）
到点投递由 __init__ 的每分钟调度任务完成（守岸人语气分型文案）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from plugins.bot_unified_runtime.capabilities.notes import (
    _NOTES_ADD_RE,
    _NOTES_BARE_RE,
    _NOTES_DELETE_RE,
    _NOTES_DONE_RE,
    _NOTES_LIST_RE,
    _NOTES_UNDO_EXPLICIT_RE,
    _NOTES_UNDO_NATURAL_RE,
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


# ---------------------------------------------------------------------------
# 勾选消歧的追问回收（审查 A-10/A-11，2026-09-14）：
# - A-10：唯一候选但相似度不足（resolve_todo_match 判 "uncertain"）不再
#   直接勾——追问一句「是这件吗」，回肯定词才勾（kind="confirm"）；
# - A-11：歧义清单带编号，回序号（「1」「第一件」「第 2 个」）勾对应项
#   （kind="ordinal"）。
# 状态存进程内 dict（键=会话，TTL 300 秒，容量上限对齐点歌多候选先例）。
# 按会话而非按人隔离：勾选面本就是会话级（任何成员都能说「X做完了」），
# 追问回收不放大权限。路由闸 is_reminder_command 没有会话上下文，只能在
# 「进程内存在未过期追问」时放行光杆肯定词/序号——窗口（300 秒）之外，
# 这类日常短句与从前一样绝不进提醒路由；窗口内其他会话的同类短句会进
# 能力层、因无本会话状态而落回原流程（_consume 兜住），代价有界如实登记。
# ---------------------------------------------------------------------------

_CHECKOFF_PENDING_TTL_SECONDS = 300.0
_CHECKOFF_PENDING_MAX_SESSIONS = 256


@dataclass(frozen=True)
class _PendingOption:
    """追问状态里的一个候选定位：凭 id 重定位而非凭下标——追问与回收
    之间清单可能变化（到点投递/取消/已勾），id 消失就诚实说不在了。"""

    kind: str  # "reminder" | "note_todo"
    reminder_id: str = ""
    note_id: str = ""
    label: str = ""  # 展示名（勾掉后回执复述）


@dataclass(frozen=True)
class _CheckoffPending:
    """一条待回收的消歧追问（A-10 确认 / A-11 序号择一）。"""

    kind: str  # "confirm" | "ordinal"
    query: str  # 触发勾选的事项词（过期提示「再说一遍 X做完了」复用）
    options: tuple[_PendingOption, ...]


_CHECKOFF_PENDING: dict[str, tuple[float, _CheckoffPending]] = {}


def _monotonic() -> float:
    """追问时钟（模块级函数便于测试拨快/拨慢）。"""
    return time.monotonic()


def clear_checkoff_pending_for_tests() -> None:
    """清空勾选消歧追问状态（测试与运维用；对齐点歌候选会话的清理口）。"""
    _CHECKOFF_PENDING.clear()


def _prune_checkoff_pending(now: float | None = None) -> None:
    """清过期 + 容量淘汰（最早到期先逐出；只在落新追问时调用，
    消费路径自己判过期，避免把「刚好过期来回收」的状态提前抹掉）。"""
    current = _monotonic() if now is None else now
    expired = [
        key for key, (expires, _state) in _CHECKOFF_PENDING.items() if expires <= current
    ]
    for key in expired:
        _CHECKOFF_PENDING.pop(key, None)
    while len(_CHECKOFF_PENDING) > _CHECKOFF_PENDING_MAX_SESSIONS:
        oldest = min(_CHECKOFF_PENDING, key=lambda key: _CHECKOFF_PENDING[key][0])
        _CHECKOFF_PENDING.pop(oldest, None)


def _set_checkoff_pending(session_id: str, pending: _CheckoffPending) -> None:
    _prune_checkoff_pending()
    _CHECKOFF_PENDING[session_id] = (
        _monotonic() + _CHECKOFF_PENDING_TTL_SECONDS,
        pending,
    )


def _has_live_checkoff_pending() -> bool:
    """路由闸用：进程内是否还有未过期的追问（只读，不清理）。"""
    if not _CHECKOFF_PENDING:
        return False
    current = _monotonic()
    return any(expires > current for expires, _state in _CHECKOFF_PENDING.values())


# 追问回收的形态词面：光杆肯定词（A-10 指定的「是/对/嗯」及常见口语
# 变体，白名单精确等值）与光杆序号（A-11 的「1」「第一件」「第 2 个」）。
# 刻意只收裸形态——「是的吧」「第 2 名之后」这类带别义的一律不接。
_FOLLOWUP_STRIP_RE = re.compile(r"^[，,。．.!！?？~～、\s]+|[，,。．.!！?？~～、\s]+$")
_AFFIRMATIVE_WORDS: frozenset[str] = frozenset(
    {
        "是", "是啊", "是的", "是呀", "是呢", "是滴", "是的是的",
        "对", "对啊", "对的", "对呀", "对呢", "对滴", "对的对的",
        "嗯", "嗯啊", "嗯呢", "嗯呐", "嗯哼", "嗯嗯",
        "好", "好啊", "好的", "好呀", "好呢", "好的好的",
        "没错", "没错没错",
    }
)
_ORDINAL_RE = re.compile(
    r"^第\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*[件个条回]?$|^([0-9]{1,2})$"
)
_CN_DIGIT_VALUES: dict[str, int] = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}


def _chinese_numeral_to_int(text: str) -> int | None:
    """「一~九十九」中文数字 → int；其余 None（清单最多 3 项，范围够用）。"""
    if not text:
        return None
    if "十" in text:
        tens_text, _sep, ones_text = text.partition("十")
        # 「十」=10、「十五」=15（十位缺省 1）、「二十」=20、「二十三」=23。
        if ones_text and ones_text not in _CN_DIGIT_VALUES:
            return None
        if tens_text and tens_text not in _CN_DIGIT_VALUES:
            return None
        tens = _CN_DIGIT_VALUES[tens_text] if tens_text else 1
        ones = _CN_DIGIT_VALUES.get(ones_text, 0)
        return tens * 10 + ones
    return _CN_DIGIT_VALUES.get(text)


def _match_affirmative(text: str) -> bool:
    stripped = _FOLLOWUP_STRIP_RE.sub("", (text or "").strip())
    return stripped in _AFFIRMATIVE_WORDS


def _match_ordinal(text: str) -> int | None:
    """光杆序号 → 1 起始序数；不是序号形态返回 None。「0」/越界词形不接。"""
    stripped = _FOLLOWUP_STRIP_RE.sub("", (text or "").strip())
    match = _ORDINAL_RE.match(stripped)
    if match is None:
        return None
    token = match.group(1) or match.group(2) or ""
    if not token:
        return None
    value = int(token) if token.isdecimal() else _chinese_numeral_to_int(token)
    if value is None or value < 1:
        return None
    return value


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
        or _NOTES_UNDO_EXPLICIT_RE.match(stripped)
        or _NOTES_UNDO_NATURAL_RE.match(stripped)
    ):
        return True
    if _LIST_RE.search(stripped) or _CANCEL_RE.search(stripped):
        return True
    if _SIGNAL_RE.search(stripped) and parse_reminder_intent(stripped) is not None:
        return True
    # 审查 A-10/A-11：消歧追问窗口内的光杆肯定词/序号要能路由进提醒
    # 能力，否则用户照提示回「是」「1」永远没人接。闸没有会话上下文，
    # 只能在进程内存在未过期追问时放行（TTL 300 秒）；窗口之外这类
    # 日常短句与从前一样绝不进提醒路由，不会抢话。
    if _has_live_checkoff_pending() and (
        _match_affirmative(stripped) or _match_ordinal(stripped) is not None
    ):
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

    def _locate_and_mark(session_key: str, option: _PendingOption) -> str | None:
        """按 id 重新定位追问里的候选并勾掉；已不在（到点投递/取消/已勾）
        返回 None——追问与回收之间清单可能变化，绝不凭旧下标盲勾。"""
        store = build_reminder_store(config)
        if option.kind == "reminder":
            for item in store.list_pending(session_key, limit=50):
                if item.reminder_id == option.reminder_id:
                    store.mark_done(item.reminder_id)
                    return item.text
            return None
        if not getattr(config, "bot_notes_enabled", True):
            return None
        from plugins.bot_unified_runtime.character.notes_store import build_notes_store

        todo_store = build_notes_store(config)
        for todo in todo_store.list_open_todos(session_key, limit=50):
            if todo.note_id == option.note_id:
                todo_store.mark_done(todo.note_id, session_key)
                return option.label
        return None

    def _consume_checkoff_followup(
        message: IncomingMessage, text: str
    ) -> CapabilityResult | None:
        """回收消歧追问（审查 A-10/A-11）：光杆肯定词 / 光杆序号。

        本会话有未过期追问 → 按类消费；无状态返回 None 落回原流程——
        路由闸放行的跨会话短句在这里被兜住，绝不消费别人的追问。
        """
        affirmative = _match_affirmative(text)
        ordinal = _match_ordinal(text)
        if not affirmative and ordinal is None:
            return None
        session_key = message.session_id
        entry = _CHECKOFF_PENDING.pop(session_key, None)
        if entry is None:
            return None
        expires, state = entry
        if expires <= _monotonic():
            # 审查 A-10 ③：确认过了时效不勾，请用户重新说一遍。
            return _checkoff_result(
                message,
                f"刚才那件「{state.query}」的确认过了时效——"
                f"再说一遍「{state.query}做完了」，我重新帮你对一对。",
                tags=["followup", "expired"],
            )
        gone_body = (
            f"（翻了翻清单）「{_candidate_label(state.options[0].label if state.options else state.query)}」"
            "刚刚已经不在待办里了——也许已经替你放下，或者提醒过你了。"
        )
        if state.kind == "confirm":
            # A-10：唯一候选的确认。肯定词（或序号 1）→ 勾；其他序号拉回确认。
            if affirmative or ordinal == 1:
                option = state.options[0]
                name = _locate_and_mark(session_key, option)
                if name is None:
                    return _checkoff_result(message, gone_body, tags=["followup", "gone"])
                return _checkoff_result(
                    message, _checkoff_done_body(name), tags=["followup", "checked"]
                )
            _CHECKOFF_PENDING[session_key] = (expires, state)  # 保留追问可重试
            return _checkoff_result(
                message,
                f"这里只挂着一件——「{_candidate_label(state.options[0].label)}」。"
                "是的话回个「是」，我替你放下。",
                tags=["followup", "out_of_range"],
            )
        # kind == "ordinal"（A-11）：歧义清单按编号择一。
        if affirmative:
            # 回了肯定词但等的是编号：重列一遍，追问原样保留。
            _CHECKOFF_PENDING[session_key] = (expires, state)
            lines = _ordinal_option_lines(state.options)
            return _checkoff_result(
                message,
                "嗯，是哪一件呢？回个编号就行：\n" + "\n".join(lines),
                tags=["followup", "need_number"],
            )
        if ordinal is None:  # 形态闸已保证二者居其一；防御性让位。
            return None
        if ordinal > len(state.options):
            # 审查 A-11 ②：越界编号不勾，提示有效范围，追问保留可重试。
            _CHECKOFF_PENDING[session_key] = (expires, state)
            return _checkoff_result(
                message,
                f"这个编号不在刚才的清单里——回 1 到 {len(state.options)} 就行。"
                f"过了太久的话，再说说「{state.query}做完了」也可以。",
                tags=["followup", "out_of_range"],
            )
        option = state.options[ordinal - 1]
        name = _locate_and_mark(session_key, option)
        if name is None:
            return _checkoff_result(
                message,
                f"（翻了翻清单）「{_candidate_label(option.label)}」"
                "刚刚已经不在待办里了——也许已经替你放下，或者提醒过你了。",
                tags=["followup", "gone"],
            )
        return _checkoff_result(
            message, _checkoff_done_body(name), tags=["followup", "checked"]
        )

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
            """当场命中：下标是本次新鲜算出的，直接按位勾掉。"""
            if index < reminder_count:
                reminder = pending[index]
                store.mark_done(reminder.reminder_id)
                return reminder.text
            todo = todo_owners[index - reminder_count]
            todo_store = build_notes_store(config)
            todo_store.mark_done(todo.note_id, message.session_id)
            return names[index]

        def _option_at(index: int) -> _PendingOption:
            """把匹配下标固化成候选定位（追问回收时按 id 重定位）。"""
            if index < reminder_count:
                item = pending[index]
                return _PendingOption(
                    kind="reminder", reminder_id=item.reminder_id, label=item.text
                )
            todo = todo_owners[index - reminder_count]
            return _PendingOption(kind="note_todo", note_id=todo.note_id, label=names[index])

        if outcome == "hit":
            name = _mark(indexes[0])
            return _checkoff_result(
                message,
                _checkoff_done_body(name),
                tags=["checked"],
            )
        if outcome == "uncertain":
            # 审查 A-10：唯一候选但相似度不足（如「买牛奶」vs「买酸奶」
            # 0.667）——不再替用户做主，追问一句，回肯定词才勾（见
            # _consume_checkoff_followup）。
            option = _option_at(indexes[0])
            _set_checkoff_pending(
                message.session_id,
                _CheckoffPending(kind="confirm", query=query, options=(option,)),
            )
            return _checkoff_result(
                message,
                f"嗯……你说的是「{_candidate_label(option.label)}」这件吗？"
                "只对上了一半，我不敢替你做主。\n"
                "是的话回个「是」，我替你放下；不是就算了。",
                tags=["confirm"],
            )
        if outcome == "ambiguous":
            # 审查 A-11：清单带编号，回序号直接勾（追问状态落进程内）。
            # 文案审计①：resolve_todo_match 可并列返回 2-3 个候选，
            # 正文不点数（「有几件」），与下方清单同屏不矛盾。
            options = tuple(_option_at(index) for index in indexes)
            _set_checkoff_pending(
                message.session_id,
                _CheckoffPending(kind="ordinal", query=query, options=options),
            )
            lines = _ordinal_option_lines(options)
            return _checkoff_result(
                message,
                "有几件事都对得上，是哪一件完成了？\n" + "\n".join(lines)
                + "\n回个编号（比如「1」）就行，我替你放下。",
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

        # 审查 A-10/A-11：消歧追问的回收优先于一切子面——光杆肯定词
        # /序号只在追问窗口内被承接；无本会话状态时返回 None 落回原
        # 流程（路由闸放行的跨会话短句在这里兜住）。
        followup = _consume_checkoff_followup(message, text)
        if followup is not None:
            return followup

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
        if reminder is None:
            # 审查 A-07：清单满不再挤掉最旧一条（用户以为都记着，其实被静默
            # 删了）——如实告诉用户先做取舍，再记新的。
            return _result(
                message,
                "这个会话的提醒已经排满 20 条了。"
                "先看看「提醒列表」，把不要的那条取消掉，我再帮你记新的，好吗？",
                tags=["reminder_full"],
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
            or _NOTES_UNDO_EXPLICIT_RE.match(stripped)
            or _NOTES_UNDO_NATURAL_RE.match(stripped)
        )

    return capability


def _candidate_label(name: str) -> str:
    label = str(name or "").strip()
    return label[:40] if label else "(无题)"


def _checkoff_done_body(name: str) -> str:
    """勾掉后的守岸人回执（A-10 直接勾与追问回收共用一份口径）。"""
    return (
        f"（轻轻点头）嗯，「{name}」——已经替你放下了。\n"
        "剩下的事不着急，一件一件来。我都在。"
    )


def _ordinal_option_lines(options: tuple[_PendingOption, ...]) -> list[str]:
    """A-11 编号清单行：与序号回复（「1」「第一件」）一一对应。"""
    return [
        f"{position}. {_candidate_label(option.label)}"
        for position, option in enumerate(options, start=1)
    ]


__all__ = [
    "build_reminder_capability",
    "clear_checkoff_pending_for_tests",
    "extract_checkoff_query",
    "is_reminder_command",
]

"""共享群上下文：群消息短时记忆（元宝式摘要）。

设计分层：

- **确定性摘要（默认、免费）**：从 SQLite 群会话历史取最近 N 条
  （忽略发送者，只取公共投影），拼成 "时间 角色：截断文本" 的短
  摘要。不调 LLM、不产生 token 费用。
- **可选 LLM 摘要（默认关闭）**：``BOT_GROUP_DIGEST_LLM_ENABLED=true``
  时按 TTL 用 LLM 把确定性摘要压成更短的话题总结，缓存复用，避免
  每轮都烧钱。

注入位置：``SharedGroupContext.summary``，与"用户×机器人"个人历史
分开，属于不可信事实；个人私密内容不会出现在群摘要里（群会话的
历史本来就是群内可见的公共消息，摘要也只会截断处理）。
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Protocol

from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
    group_cast_prohibition,
)
from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
    guard_secondhand_text,
    neutralize_internal_markers,
    strip_injection_instruction_spans,
)
from plugins.bot_unified_runtime.domains.core import session_keys
from plugins.bot_unified_runtime.domains.core.contracts.character import (
    SharedGroupContext,
)

# 键口径（F4 席根修，2026-09-20；D-7 收编，SEAT-D7-FIX）：
# conversation_turns.session_id 由摄取层 NoneBot ``get_session_id()`` 产出
# （群=f"group_<群号>_<发送者>"，生产库 wuwa_history.sqlite3 实测 2457 行
# 全为此形态、旧读侧等值键 "group:<群号>" 0 行——两键永不相交即台账 #33
# 本 bug 根因）。读侧按群聚合的前缀**直接复用全仓唯一权威**
# domains/core/session_keys.py:group_session_prefix（B-2 裁定条款：禁再造
# 第二套键形——历史上本文件留过字节等价的镜像常量，仍是副本，副本漂移
# 正是病根）。tests/test_shared_group_key_alignment.py 双向上锁；
# tests/test_group_digest_session_key_query.py 锁推送链路与复用路由本身。
_LIKE_ESCAPE_CHAR = "!"


def _group_prefix(group_id: Any) -> str:
    """群级聚合前缀：直通中央权威 session_keys.group_session_prefix。

    非法/空群号返回 ""——调用方据此直接判无数据，绝不退化成全表扫。
    None 与 falsy 群号统一按空判（中央件口径，消灭两侧最后的理论漂移面）。
    """
    return session_keys.group_session_prefix(group_id)


def _like_prefix_pattern(prefix: str) -> str:
    """前缀 → LIKE 模式：转义 ``%``/``_``/转义符本身再追 ``%``。

    ``_`` 在 LIKE 里是单字符通配符，不转义则 ``group_123456_%`` 误吞
    ``group_1234567_*``（相邻群号串群）。
    """
    escaped = (
        prefix.replace(_LIKE_ESCAPE_CHAR, f"{_LIKE_ESCAPE_CHAR}{_LIKE_ESCAPE_CHAR}")
        .replace("%", f"{_LIKE_ESCAPE_CHAR}%")
        .replace("_", f"{_LIKE_ESCAPE_CHAR}_")
    )
    return f"{escaped}%"


def _normalize_group_id(value: Any) -> str:
    """群号规范形式：字符串化去空白（名单/会话 id 存在 int/str 混型）。"""
    return str(value).strip()


def _group_id_set(value: Any) -> set[str]:
    """名单项规范成去空白群号字符串集合；int/str 混型、单字符串均安全。"""
    if isinstance(value, str):
        candidates: list[Any] = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        candidates = list(value)
    else:
        candidates = []
    return {
        normalized
        for normalized in (_normalize_group_id(item) for item in candidates)
        if normalized
    }


def _clock_gap_minutes(previous: str, current: str) -> int | None:
    """HH:MM 分钟差（跨小时简单展开）；解析失败返回 None。"""
    try:
        prev_hour, prev_minute = (int(part) for part in previous.split(":"))
        curr_hour, curr_minute = (int(part) for part in current.split(":"))
    except (ValueError, AttributeError):
        return None
    prev_total = prev_hour * 60 + prev_minute
    curr_total = curr_hour * 60 + curr_minute
    gap = curr_total - prev_total
    if gap < -720:  # 跨天（如 23:59 -> 00:01）
        gap += 1440
    return gap


def sanitize_digest_line(text: str) -> str:
    """群成员原文行进摘要前的逐条处置：句级指令剥离 → 边界标记全角化。

    两件真身均在 ``security/injection.py``（``strip_injection_instruction_spans``
    与 ``neutralize_internal_markers``），零新机制。顺序**先剥离后全角**：
    剥离判据认 ASCII 方括号形态（``[SYSTEM PROMPT]`` 一类），先全角化会把
    伪造标记洗成判据不认的形态、反给指令句放行通道——同 chat 检索腿
    ``_sanitize_untrusted_context_text(_strip_injection_instruction_spans(…))``
    的既有口径。幂等：干净行逐字节不变，全角产物二次处置零变化。

    **fail-closed**：处置本身抛异常时返回空串，由调用方按「空行进空出」丢弃该行，
    绝不因为判据坏了就把裸文本发出去（群摘要会由 bot 自己的署名投递回全群，
    裸发一条伪造「系统指令」不是降级而是二次传播载荷）。
    """
    try:
        return neutralize_internal_markers(strip_injection_instruction_spans(text))
    except Exception:  # noqa: BLE001 - 判不了＝不注入：整行按空出，不裸发。
        return ""


class SharedGroupContextProvider(Protocol):
    def load(
        self,
        request_id: str,
        group_id: str,
        sender_id: str,
    ) -> SharedGroupContext:
        """读取群维度公共上下文投影；无可用数据返回 enabled=False。"""


class NullSharedGroupContextProvider:
    def load(
        self,
        request_id: str,
        group_id: str,
        sender_id: str,
    ) -> SharedGroupContext:
        return SharedGroupContext(request_id=request_id, enabled=False)


class GroupDigestListFilter:
    """群摘要白/黑名单参与判定。

    名单键（运行时 store 可热改，消费在此）：
    ``BOT_GROUP_DIGEST_LIST_MODE`` / ``_WHITELIST`` / ``_BLACKLIST``。

    - mode=whitelist：仅名单内群参与摘要注入；
    - mode=blacklist：名单内群排除；
    - mode 空/off/all/未知：不过滤（完全向后兼容，既有行为零变化）。

    名单项与群号统一字符串化比对（int/str 混型安全）。
    """

    _FILTERING_MODES = frozenset({"whitelist", "blacklist"})

    def __init__(
        self,
        *,
        mode: str = "",
        whitelist: Any = None,
        blacklist: Any = None,
    ) -> None:
        self.mode = str(mode or "").strip().lower()
        self.whitelist = _group_id_set(whitelist)
        self.blacklist = _group_id_set(blacklist)

    @property
    def filtering(self) -> bool:
        """名单是否生效；未配置/模式未知一律不改变既有行为。"""
        return self.mode in self._FILTERING_MODES

    def allows(self, group_id: str) -> bool:
        if not self.filtering:
            return True
        normalized = _normalize_group_id(group_id)
        if self.mode == "whitelist":
            return normalized in self.whitelist
        return normalized not in self.blacklist


class ListFilteredSharedGroupContextProvider:
    """按白/黑名单过滤群摘要参与资格；名单外群返回 enabled=False。

    包在确定性摘要（与可选 LLM 压缩）**之外**：名单外群连 SQLite
    读取与 LLM 压缩调用都不发生。全局开关关闭时上游直接返回
    Null provider，本层不会被构建（名单无意义）。
    """

    def __init__(
        self,
        inner: SharedGroupContextProvider,
        *,
        list_filter: GroupDigestListFilter,
    ) -> None:
        self.inner = inner
        self.list_filter = list_filter

    def load(
        self,
        request_id: str,
        group_id: str,
        sender_id: str,
    ) -> SharedGroupContext:
        if not self.list_filter.allows(group_id):
            return SharedGroupContext(request_id=request_id, enabled=False)
        return self.inner.load(request_id, group_id, sender_id)


class SQLiteGroupDigestProvider:
    """确定性群摘要：最近 N 条群会话公共投影（免费、无 LLM）。"""

    def __init__(
        self,
        db_path: str | Path,
        *,
        max_turns: int = 20,
        max_chars: int = 800,
    ) -> None:
        self.db_path = Path(db_path)
        self.max_turns = max(1, int(max_turns))
        self.max_chars = max(100, int(max_chars))

    def load(
        self,
        request_id: str,
        group_id: str,
        sender_id: str,
    ) -> SharedGroupContext:
        if not self.db_path.exists():
            return SharedGroupContext(request_id=request_id, enabled=False)
        rows = self._fetch_group_rows(group_id)
        if not rows:
            return SharedGroupContext(request_id=request_id, enabled=False)
        lines: list[str] = []
        chars_used = 0
        role_names = {"user": "成员", "assistant": "机器人"}
        previous_clock: str | None = None
        for row in rows:
            remaining = self.max_chars - chars_used
            if remaining <= 0:
                break
            created = str(row["created_at"])
            clock = created[11:16] if len(created) >= 16 and "T" in created else ""
            # 话题漂移分段：相邻两条间隔超过 10 分钟时插入空行分隔。
            if previous_clock is not None:
                gap_minutes = _clock_gap_minutes(previous_clock, clock)
                if gap_minutes is not None and gap_minutes > 10:
                    separator = "……"
                    if len(separator) <= remaining:
                        lines.append(separator)
                        chars_used += len(separator)
            previous_clock = clock
            text = sanitize_digest_line(str(row["text"]).replace("\n", " ").strip())
            if not text:
                # 整行皆为指令形态（或处置失败）⇒ 空进空出：整行不注入、
                # 不写占位文本——谎报「读到了东西」比不读更坏（同
                # guard_secondhand_text 口径），裸发更是不行（本腿会被 bot
                # 署名逐字复述回全群）。
                continue
            if len(text) > 80:
                text = f"{text[:79]}…"
            line = (
                f"- {clock} {role_names.get(str(row['role']), str(row['role']))}：{text}"
            )
            if len(line) > remaining:
                line = f"{line[: max(1, remaining - 1)]}…"
            lines.append(line)
            chars_used += len(line)
        if not lines:
            # 消毒后一条不剩＝如实「无内容」，走既有的 enabled=False 通道，
            # 不端一顶只有标题、没有正文的摘要给下游（下游会把它当有内容）。
            return SharedGroupContext(request_id=request_id, enabled=False)
        summary = (
            "最近群聊公共话题（确定性摘要，不含个人私聊内容；"
            # 主角边界禁令走单一真身 addressing.group_cast_prohibition（席 E2）：
            # 此处旧留一份自写副本，措辞与 LLM 压缩腿两样、判据一条，改一处漏一处。
            f"{group_cast_prohibition()}）：\n" + "\n".join(lines)
        )
        return SharedGroupContext(
            request_id=request_id,
            summary=summary,
            enabled=True,
        )

    def _fetch_group_rows(self, group_id: str) -> list[sqlite3.Row]:
        prefix = _group_prefix(group_id)
        if not prefix:
            return []
        try:
            with sqlite3.connect(self.db_path) as connection:
                connection.row_factory = sqlite3.Row
                # 过滤命令/被动回复（查天气、查状态等），只保留
                # 成员发言与机器人基于大模型的人格化回复。
                columns = {
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(conversation_turns)"
                    ).fetchall()
                }
                kind_filter = (
                    "AND (kind IS NULL OR kind = 'chat')"
                    if "kind" in columns
                    else ""
                )
                # 按群前缀聚合该群全部 per-sender 会话行（写侧键
                # group_<群号>_<发送者>，见模块头「键口径」注释）。
                cursor = connection.execute(
                    f"""
                    SELECT role, text, created_at
                    FROM conversation_turns
                    WHERE session_id LIKE ? ESCAPE '{_LIKE_ESCAPE_CHAR}'
                      {kind_filter}
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (_like_prefix_pattern(prefix), self.max_turns),
                )
                return list(cursor.fetchall())
        except sqlite3.Error:
            return []


class OpenAICompatibleGroupSummarizer:
    """按 TTL 缓存 LLM 摘要；失败回退原摘要，不阻塞对话。

    缓存键是群聊全文摘要（随对话持续变化），旧键几乎不会再次命中：
    用 OrderedDict LRU（上限 32 条）防止进程常驻内存无限增长。
    """

    _CACHE_CAPACITY = 32

    def __init__(
        self,
        llm_provider: Any,
        *,
        ttl_seconds: int = 3600,
        max_chars: int = 400,
    ) -> None:
        self.llm_provider = llm_provider
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.max_chars = max(100, int(max_chars))
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        # LRU get/move_to_end/popitem 序列跨线程不原子：并发驱逐会让
        # move_to_end 抛 KeyError 穿透 load()，故所有缓存操作持锁。
        self._cache_lock = threading.Lock()

    def summarize(self, digest_text: str) -> str:
        # 逐行二次消毒（幂等，干净行逐字节不变）：summarize 也可能被直接喂
        # 未过 SQLiteGroupDigestProvider 的文本（推送腿、测试夹具、将来新调用方）。
        # LLM 失败回退 ``return key`` 腿与缓存键一并吃到消毒后形态 ⇒ 裸标记
        # 不再有任何一条进模型/回会话的通路（回退文本会常驻 LRU 与 summary）。
        # 空行进空出、不写占位文本；整段皆毒 ⇒ key 为空，走既有「无内容」早退腿。
        key = "\n".join(
            sanitize_digest_line(line) for line in digest_text.splitlines()
        ).strip()
        if not key:
            return key
        with self._cache_lock:
            cached_at, cached = self._cache.get(key, (0.0, ""))
            if cached and time.monotonic() - cached_at <= self.ttl_seconds:
                self._cache.move_to_end(key)
                return cached
        prompt = (
            "请把下面的群聊公共消息压缩成 3-5 条中性话题摘要，"
            "不保留任何个人敏感信息，不评价、不编造；"
            f"成员一律按其原有称呼呈现，{group_cast_prohibition()}：\n"
            # 群聊历史行是群成员产出的**二手内容**：入 prompt 前过统一咽喉
            # （S-FIX-ATK-NOTES 2026-09-27；旧形态裸拼接——「双隔离」只隔离
            # 人格词（漂泊者称呼），不隔离注入；开关默认关、开即实锤）。
            + guard_secondhand_text(key, source_label="群聊公共摘要")
        )
        try:
            reply = self.llm_provider.generate(
                [
                    {"role": "system", "content": "你是群聊话题摘要助手。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=200,
            )
            summary = reply.text.strip()
        except Exception:  # noqa: BLE001 - LLM 摘要失败时回退原始键，不阻断群上下文构建。
            return key
        if not summary:
            return key
        summary = _strip_summary(summary)
        with self._cache_lock:
            self._cache[key] = (time.monotonic(), summary)
            self._cache.move_to_end(key)
            while len(self._cache) > self._CACHE_CAPACITY:
                self._cache.popitem(last=False)
        return summary


class LLMSummarizingGroupDigestProvider:
    """确定性摘要 + 可选 LLM 压缩的包装。"""

    def __init__(
        self,
        inner: SharedGroupContextProvider,
        summarizer: Any,
    ) -> None:
        self.inner = inner
        self.summarizer = summarizer

    def load(
        self,
        request_id: str,
        group_id: str,
        sender_id: str,
    ) -> SharedGroupContext:
        context = self.inner.load(request_id, group_id, sender_id)
        if not context.enabled or not context.summary:
            return context
        return context.model_copy(
            update={"summary": self.summarizer.summarize(context.summary)}
        )


def _strip_summary(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > 400:
        value = f"{value[:399]}…"
    return value


def build_shared_group_context_provider(
    config: object,
    *,
    llm_provider: object | None = None,
) -> SharedGroupContextProvider:
    """按配置构造：默认关闭；开启后优先确定性摘要，可选 LLM 压缩。"""
    enabled = bool(getattr(config, "bot_shared_group_context_enabled", False))
    if not enabled:
        return NullSharedGroupContextProvider()
    db_path = str(getattr(config, "bot_history_db_path", "")).strip()
    if not db_path:
        return NullSharedGroupContextProvider()
    provider: SharedGroupContextProvider = SQLiteGroupDigestProvider(
        db_path,
        max_turns=int(getattr(config, "bot_group_digest_max_turns", 150)),
        max_chars=int(getattr(config, "bot_group_digest_max_chars", 800)),
    )
    # 白/黑名单参与过滤（装配期快照；模式空/未知不过滤=既有行为零变化）。
    digest_list = GroupDigestListFilter(
        mode=str(getattr(config, "bot_group_digest_list_mode", "") or ""),
        whitelist=getattr(config, "bot_group_digest_whitelist", None),
        blacklist=getattr(config, "bot_group_digest_blacklist", None),
    )
    if digest_list.filtering:
        provider = ListFilteredSharedGroupContextProvider(
            provider,
            list_filter=digest_list,
        )
    if (
        bool(getattr(config, "bot_group_digest_llm_enabled", False))
        and llm_provider is not None
    ):
        provider = LLMSummarizingGroupDigestProvider(
            provider,
            OpenAICompatibleGroupSummarizer(
                llm_provider,
                ttl_seconds=int(getattr(config, "bot_group_digest_llm_ttl_seconds", 3600)),
            ),
        )
    return provider


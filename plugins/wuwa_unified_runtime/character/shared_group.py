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
import time
from pathlib import Path
from typing import Protocol

from plugins.wuwa_unified_runtime.contracts.character import SharedGroupContext

_GROUP_SESSION_PREFIX = "group:"


def _group_session_id(group_id: str) -> str:
    return f"{_GROUP_SESSION_PREFIX}{group_id}"


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
        for row in rows:
            remaining = self.max_chars - chars_used
            if remaining <= 0:
                break
            created = str(row["created_at"])
            clock = created[11:16] if len(created) >= 16 and "T" in created else ""
            text = str(row["text"]).replace("\n", " ").strip()
            if len(text) > 80:
                text = f"{text[:79]}…"
            line = (
                f"- {clock} {role_names.get(str(row['role']), str(row['role']))}：{text}"
            )
            if len(line) > remaining:
                line = f"{line[: max(1, remaining - 1)]}…"
            lines.append(line)
            chars_used += len(line)
        summary = (
            "最近群聊公共话题（确定性摘要，不含个人私聊内容）：\n"
            + "\n".join(lines)
        )
        return SharedGroupContext(
            request_id=request_id,
            summary=summary,
            enabled=True,
        )

    def _fetch_group_rows(self, group_id: str) -> list[sqlite3.Row]:
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
                cursor = connection.execute(
                    f"""
                    SELECT role, text, created_at
                    FROM conversation_turns
                    WHERE session_id = ?
                      {kind_filter}
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (_group_session_id(group_id), self.max_turns),
                )
                return list(cursor.fetchall())
        except sqlite3.Error:
            return []


class LLMGroupSummarizer(Protocol):
    def summarize(self, digest_text: str) -> str:
        """把确定性摘要压成话题总结；失败返回原摘要。"""


class NullLLMGroupSummarizer:
    def summarize(self, digest_text: str) -> str:
        return digest_text


class OpenAICompatibleGroupSummarizer:
    """按 TTL 缓存 LLM 摘要；失败回退原摘要，不阻塞对话。"""

    def __init__(
        self,
        llm_provider: object,
        *,
        ttl_seconds: int = 3600,
        max_chars: int = 400,
    ) -> None:
        self.llm_provider = llm_provider
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.max_chars = max(100, int(max_chars))
        self._cache: dict[str, tuple[float, str]] = {}

    def summarize(self, digest_text: str) -> str:
        key = digest_text.strip()
        if not key:
            return key
        cached_at, cached = self._cache.get(key, (0.0, ""))
        if cached and time.monotonic() - cached_at <= self.ttl_seconds:
            return cached
        prompt = (
            "请把下面的群聊公共消息压缩成 3-5 条中性话题摘要，"
            "不保留任何个人敏感信息，不评价、不编造：\n" + key
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
        except Exception:
            return key
        if not summary:
            return key
        summary = _strip_summary(summary)
        self._cache[key] = (time.monotonic(), summary)
        return summary


class LLMSummarizingGroupDigestProvider:
    """确定性摘要 + 可选 LLM 压缩的包装。"""

    def __init__(
        self,
        inner: SharedGroupContextProvider,
        summarizer: object,
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
    enabled = bool(getattr(config, "wuwa_shared_group_context_enabled", False))
    if not enabled:
        return NullSharedGroupContextProvider()
    db_path = str(getattr(config, "wuwa_history_db_path", "")).strip()
    if not db_path:
        return NullSharedGroupContextProvider()
    provider: SharedGroupContextProvider = SQLiteGroupDigestProvider(
        db_path,
        max_turns=int(getattr(config, "wuwa_group_digest_max_turns", 150)),
        max_chars=int(getattr(config, "wuwa_group_digest_max_chars", 800)),
    )
    if (
        bool(getattr(config, "wuwa_group_digest_llm_enabled", False))
        and llm_provider is not None
    ):
        provider = LLMSummarizingGroupDigestProvider(
            provider,
            OpenAICompatibleGroupSummarizer(
                llm_provider,
                ttl_seconds=int(getattr(config, "wuwa_group_digest_llm_ttl_seconds", 3600)),
            ),
        )
    return provider

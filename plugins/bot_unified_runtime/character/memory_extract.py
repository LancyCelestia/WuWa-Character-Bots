"""从单轮对话中抽取用户事实并写入记忆库。

写入侧此前完全缺失：检索器与注入管线都在，但没有任何代码调用
``upsert_fact``，记忆库始终为空。本模块补上“回复后后台抽取”这一环：
用轻量 LLM 调用从用户消息与回复中提取值得长期记住的事实，去重后入库。
抽取只发生在后台线程，任何失败都不影响主回复链路。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from plugins.bot_unified_runtime.character.memory import build_fact_id

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM_PROMPT = (
    "你是聊天记忆抽取器。从对话交换中提取值得长期记住的、关于用户本人的事实："
    "身份、偏好、约定、重要经历、稳定的情感倾向。\n"
    "规则：只输出事实条目，每行一条，每条不超过60字，最多3条；"
    "只记稳定信息，不记寒暄和一次性话题；"
    "没有值得记住的内容时只输出一个字：无"
)
_FACT_LINE_PREFIX = re.compile(r"^[\s\-—•·*>)）\]】\d+ [.、)）]*\s*")
_NO_FACT_MARKERS = {"无", "没有", "没有。", "无。", "none", "n/a"}
_MAX_FACT_CHARS = 120


def extract_memory_texts(
    llm_provider: Any,
    *,
    user_text: str,
    reply_text: str,
    max_facts: int = 3,
    generation_options: dict[str, Any] | None = None,
) -> list[str]:
    """调用 LLM 抽取事实条目；返回裁剪、去重后的文本列表。"""
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"用户消息：{_clip(user_text, 400)}\n回复：{_clip(reply_text, 400)}"
            ),
        },
    ]
    options = {"max_tokens": 200, "temperature": 0.1, **(generation_options or {})}
    reply = llm_provider.generate(messages, **options)
    text = str(getattr(reply, "text", "") or "")
    facts: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = _FACT_LINE_PREFIX.sub("", raw_line.strip())
        if not line or line.lower() in _NO_FACT_MARKERS:
            continue
        line = _clip(line, _MAX_FACT_CHARS)
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        facts.append(line)
        if len(facts) >= max_facts:
            break
    return facts


def store_extracted_memories(
    repository: Any,
    *,
    subject_user_id: str,
    session_id: str,
    texts: list[str],
) -> int:
    """把抽取结果写入记忆库；单条失败只记录日志，不中断其余条目。"""
    stored = 0
    for text in texts:
        try:
            repository.upsert_fact(
                fact_id=build_fact_id(subject_user_id, session_id, text),
                subject_user_id=subject_user_id,
                session_id=session_id,
                memory_kind="auto",
                text=text,
                confidence=0.6,
                source="llm_extract",
                sensitivity="personal",
            )
            stored += 1
        except Exception as exc:  # noqa: BLE001 - 记忆入库失败不应影响其他条目，也不打印敏感堆栈。
            logger.warning(
                "memory fact upsert failed type=%s subject=%s session=%s",
                type(exc).__name__,
                subject_user_id,
                session_id,
            )
    if stored:
        logger.info(
            "memory facts stored count=%d subject=%s session=%s",
            stored,
            subject_user_id,
            session_id,
        )
    return stored


def _clip(value: str, max_chars: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"

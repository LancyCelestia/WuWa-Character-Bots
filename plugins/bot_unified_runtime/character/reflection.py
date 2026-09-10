"""反思回路（非线性记忆 / episodic memory consolidation）。

设计蓝本为 Stanford generative_agents 的 reflection 机制（仅借鉴思想，
零代码复制）：周期性把近一天的原始对话轮次沉淀为两类更高层记忆，供
FUTURE 会话在记忆召回链路使用——

- ``reflection_digests``：每个会话当天的两句话摘要；同日重跑整行替换，
  并连带作废引用旧摘要的事实（facts supersede）。
- ``reflection_facts``：关于用户本人的稳定事实（类别 + 置信度）；
  同一 sender 下归一化文本相同的事实 keep-newest，旧行置 superseded=1。

归纳器两档：``HeuristicSummarizer``（零 LLM、确定性正则抽取，默认）
与 ``LLMSummarizer``（注入 OpenAI 兼容客户端，失败/未注入回退启发式）。
落库 conventions 与 ``character/affinity.py`` 的 DynamicAffinityStore
保持一致：WAL 先于 DML、单连接 + threading.Lock、check_same_thread=False。

数据来源：``character/history.py`` 的 conversation_turns 表（本模块不改写
history.py，自行按同一表结构做按日查询，schema 出处见 gather_turns_by_date）。
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from plugins.bot_unified_runtime.contracts import MemoryRetrievalResult, PrivacyLevel

logger = logging.getLogger(__name__)

# ---- 常量（与 memory_extract.py 的抽取纪律对齐：≤3 条、短句、只记稳定事实）----
_MAX_SESSION_FACTS = 3
_MAX_FACT_CHARS = 60
_DIGEST_SENTENCE_CHARS = 80
_MIN_FACT_CONFIDENCE = 0.5
_HEURISTIC_CONFIDENCE = 0.5
_LLM_CONFIDENCE = 0.6

_FACT_LINE_PREFIX = re.compile(r"^[\s\-—•·*>)）\]】\d+ [.、)）]*\s*")
_NO_FACT_MARKERS = {"无", "没有", "没有。", "无。", "none", "n/a"}

# 用户自述句式（参考 affinity.py _PROFILE_PATTERNS 的写法，本模块独立维护）：
# 「我(很/最)喜欢X」「我(最近)在Y」「我要Z」「我是/住在W」，取到标点/空白为止。
_SELF_STATEMENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"我(?:很|最)?(?:喜欢|爱|讨厌|恨)(?:[^，。！!？?；;～~\s]{1,18})"), "preference"),
    (re.compile(r"我(?:最近|这几天|近期)?(?:在|正在)(?:[^，。！!？?；;～~\s]{2,18})"), "activity"),
    (re.compile(r"我(?:要|打算|准备|计划|想)(?:[^，。！!？?；;～~\s]{2,18})"), "plan"),
    (re.compile(r"我(?:是|住在|来自)(?:[^，。！!？?；;～~\s]{2,12})"), "identity"),
)

_REFLECT_SYSTEM_PROMPT = (
    "你是聊天反思器。从一天的会话记录里提炼关于用户本人的高层事实："
    "身份、偏好、约定、重要经历、近况、稳定的情感倾向。\n"
    "规则：只输出事实条目，每行一条，每条不超过60字，最多3条；"
    "只记稳定信息，不记寒暄和一次性话题；"
    "没有值得记住的内容时只输出一个字：无"
)

_SCOPE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---- 数据结构 ----


@dataclass(frozen=True)
class Turn:
    """会话中的一个对话轮次（history.py ConversationTurn 的轻量镜像）。

    sender_id 由 gather_turns_by_date 落入；会话级归纳用它定位主用户
    （私聊即本人），无 sender 信息时为空串。
    """

    role: str
    text: str
    created_at: str
    sender_id: str = ""


@dataclass(frozen=True)
class FactDraft:
    """待入库的事实草稿：正文 + 类别 + 置信度。"""

    text: str
    category: str = ""
    confidence: float = 0.6


@dataclass(frozen=True)
class ReflectionFact:
    """一条已入库的高层用户事实（superseded=0 才会参与召回）。"""

    fact_id: str
    sender_id: str
    session_key: str
    fact_text: str
    category: str
    confidence: float
    source_digest_id: str
    created_at: str


@dataclass(frozen=True)
class ReflectionDigest:
    """一个会话在某一天的抽取式摘要（同日唯一，重跑替换）。"""

    digest_id: str
    session_key: str
    scope_date: str
    summary: str
    turn_count: int
    created_at: str


@dataclass(frozen=True)
class SessionReflection:
    """单个会话的归纳产物：两句话摘要 + 事实草稿列表。"""

    summary: str
    facts: tuple[FactDraft, ...] = ()


@dataclass(frozen=True)
class ReflectionReport:
    """一次反思任务的计数汇总。"""

    scope_date: str
    sessions_seen: int
    sessions_processed: int
    digests_saved: int
    facts_saved: int


class SessionSummarizer(Protocol):
    """归纳器协议：给定会话轮次，产出摘要 + 事实。"""

    def summarize(self, session_key: str, turns: Sequence[Turn]) -> SessionReflection: ...


# ---- 工具函数 ----


def _format_utc(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _clip(value: str, max_chars: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"


def _normalize_fact_text(text: str) -> str:
    """事实文本的归一化键：去全部空白 + 小写，供跨摘要去重。"""
    return "".join((text or "").split()).lower()


def build_digest_id(session_key: str, scope_date: str) -> str:
    digest = hashlib.sha1(f"{session_key}:{scope_date}".encode()).hexdigest()
    return f"rd_{digest[:16]}"


def build_reflection_fact_id(sender_id: str, normalized_text: str) -> str:
    digest = hashlib.sha1(f"{sender_id}:{normalized_text}".encode()).hexdigest()
    return f"rf_{digest[:16]}"


def _primary_sender(turns: Sequence[Turn]) -> str:
    """会话内发言最多的 user 角色 sender（并列取字典序最小，确定性）。

    私聊会话即本人；群聊无 per-fact 归属信息，退化为最活跃者——
    反思事实是会话级的粗粒度沉淀，该近似可接受（docstring 已注明）。
    """
    counts: Counter[str] = Counter(
        turn.sender_id.strip()
        for turn in turns
        if turn.role == "user" and turn.sender_id.strip()
    )
    if not counts:
        return ""
    top = max(counts.values())
    return min(sender for sender, count in counts.items() if count == top)


# ---- SQLite 存储 ----


class ReflectionStore:
    """SQLite 反思产物存储；线程安全，conventions 与 affinity.py 一致。"""

    def __init__(self, db_path: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        self.db_path = Path(db_path)
        self._clock = clock
        self._lock = threading.Lock()
        # 进程内复用单一连接：夜间任务与记忆召回可能跨线程并发访问，
        # 全部操作已在 self._lock 下串行，check_same_thread=False 允许共用。
        self._connection: sqlite3.Connection | None = None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            # WAL 必须先于一切 DML/D设置：夜间批量写与召回读并发时不阻塞事件循环。
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reflection_facts (
                    fact_id TEXT PRIMARY KEY,
                    sender_id TEXT NOT NULL,
                    session_key TEXT NOT NULL DEFAULT '',
                    fact_text TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.6,
                    source_digest_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    superseded INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reflection_facts_sender_time
                ON reflection_facts (sender_id, created_at)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reflection_digests (
                    digest_id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    scope_date TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    turn_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE (session_key, scope_date)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            connection = sqlite3.connect(
                self.db_path, timeout=5.0, check_same_thread=False
            )
            connection.row_factory = sqlite3.Row
            self._connection = connection
        return self._connection

    def save_digest(
        self,
        *,
        session_key: str,
        scope_date: str,
        summary: str,
        turn_count: int,
    ) -> str:
        """写入/替换 (session_key, scope_date) 唯一的摘要；返回 digest_id。

        同日重跑：digest_id 确定性派生自 (session_key, scope_date)，整行替换；
        替换前先把引用该摘要的事实全部置 superseded=1（旧归纳随旧摘要作废）。
        """
        key = session_key.strip()
        day = scope_date.strip()
        if not key or not day:
            raise ValueError("reflection digest requires session_key and scope_date")
        digest_id = build_digest_id(key, day)
        now_text = _format_utc(float(self._clock()))
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE reflection_facts SET superseded = 1 WHERE source_digest_id = ?",
                (digest_id,),
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO reflection_digests
                    (digest_id, session_key, scope_date, summary, turn_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (digest_id, key, day, summary, max(0, int(turn_count)), now_text),
            )
        return digest_id

    def save_facts(
        self,
        digest_id: str,
        sender_id: str,
        facts: Sequence[FactDraft],
    ) -> int:
        """把事实草稿挂到 digest 下并归属 sender；返回成功入库条数。

        去重规则（keep-newest）：同一 sender 下归一化文本相同的旧行先置
        superseded=1，新行以最新 created_at/置信度/来源覆盖插入。
        """
        if not digest_id.strip():
            return 0
        sender = sender_id.strip()
        now_text = _format_utc(float(self._clock()))
        saved = 0
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT session_key FROM reflection_digests WHERE digest_id = ?",
                (digest_id,),
            ).fetchone()
            session_key = str(row["session_key"]) if row is not None else ""
            for draft in facts:
                text = _clip(draft.text, _MAX_FACT_CHARS)
                if not text:
                    continue
                normalized = _normalize_fact_text(text)
                fact_id = build_reflection_fact_id(sender, normalized)
                existing = connection.execute(
                    "SELECT fact_id, fact_text FROM reflection_facts"
                    " WHERE sender_id = ? AND superseded = 0",
                    (sender,),
                ).fetchall()
                for stale in existing:
                    stale_id = str(stale["fact_id"])
                    if (
                        stale_id != fact_id
                        and _normalize_fact_text(str(stale["fact_text"])) == normalized
                    ):
                        connection.execute(
                            "UPDATE reflection_facts SET superseded = 1 WHERE fact_id = ?",
                            (stale_id,),
                        )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO reflection_facts
                        (fact_id, sender_id, session_key, fact_text, category,
                         confidence, source_digest_id, created_at, superseded)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        fact_id,
                        sender,
                        session_key,
                        text,
                        draft.category.strip(),
                        max(0.0, min(1.0, float(draft.confidence))),
                        digest_id,
                        now_text,
                    ),
                )
                saved += 1
        return saved

    def facts_for(
        self,
        sender_id: str,
        *,
        limit: int = 6,
        max_chars: int = 900,
    ) -> list[ReflectionFact]:
        """召回某用户的有效事实：superseded=0、置信度达标、新者在前。"""
        sender = sender_id.strip()
        if not sender or limit <= 0 or max_chars <= 0:
            return []
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT fact_id, sender_id, session_key, fact_text, category,
                       confidence, source_digest_id, created_at
                FROM reflection_facts
                WHERE sender_id = ?
                  AND superseded = 0
                  AND confidence >= ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (sender, _MIN_FACT_CONFIDENCE, max(1, int(limit))),
            ).fetchall()
        selected: list[ReflectionFact] = []
        chars_used = 0
        for row in rows:
            text = str(row["fact_text"])
            remaining = max_chars - chars_used
            if remaining <= 0:
                break
            if len(text) > remaining:
                text = _clip(text, remaining)
            selected.append(
                ReflectionFact(
                    fact_id=str(row["fact_id"]),
                    sender_id=str(row["sender_id"]),
                    session_key=str(row["session_key"]),
                    fact_text=text,
                    category=str(row["category"]),
                    confidence=float(row["confidence"]),
                    source_digest_id=str(row["source_digest_id"]),
                    created_at=str(row["created_at"]),
                )
            )
            chars_used += len(text)
        return selected

    def digest_for(self, session_key: str, scope_date: str) -> ReflectionDigest | None:
        """读取某会话某天的摘要；不存在返回 None。"""
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT digest_id, session_key, scope_date, summary, turn_count, created_at
                FROM reflection_digests
                WHERE session_key = ? AND scope_date = ?
                """,
                (session_key.strip(), scope_date.strip()),
            ).fetchone()
        if row is None:
            return None
        return ReflectionDigest(
            digest_id=str(row["digest_id"]),
            session_key=str(row["session_key"]),
            scope_date=str(row["scope_date"]),
            summary=str(row["summary"]),
            turn_count=int(row["turn_count"]),
            created_at=str(row["created_at"]),
        )


# ---- 归纳器 ----


def _extractive_summary(user_texts: list[str]) -> str:
    """抽取式两句话摘要：开场第一条用户消息 + 最后话题（确定性）。"""
    if not user_texts:
        return ""
    first = _clip(user_texts[0], _DIGEST_SENTENCE_CHARS)
    if len(user_texts) == 1:
        return f"开场话题：{first}。"
    last = _clip(user_texts[-1], _DIGEST_SENTENCE_CHARS)
    if _normalize_fact_text(first) == _normalize_fact_text(last):
        return f"开场话题：{first}。"
    return f"开场话题：{first}。后来聊到：{last}。"


def _heuristic_facts(user_texts: list[str]) -> tuple[FactDraft, ...]:
    """正则抽取用户自述事实：≤3 条、每条 ≤60 字、归一化去重、确定性。"""
    drafts: list[FactDraft] = []
    seen: set[str] = set()
    for text in user_texts:
        for pattern, category in _SELF_STATEMENT_PATTERNS:
            for match in pattern.finditer(text):
                fact = _clip(match.group(0), _MAX_FACT_CHARS)
                key = _normalize_fact_text(fact)
                if not fact or key in seen:
                    continue
                seen.add(key)
                drafts.append(
                    FactDraft(text=fact, category=category, confidence=_HEURISTIC_CONFIDENCE)
                )
                if len(drafts) >= _MAX_SESSION_FACTS:
                    return tuple(drafts)
    return tuple(drafts)


class HeuristicSummarizer:
    """零 LLM 的确定性归纳：正则抽自述事实 + 抽取式两句话摘要。"""

    def summarize(self, session_key: str, turns: Sequence[Turn]) -> SessionReflection:
        user_texts = [
            turn.text.strip()
            for turn in turns
            if turn.role == "user" and turn.text.strip()
        ]
        return SessionReflection(
            summary=_extractive_summary(user_texts),
            facts=_heuristic_facts(user_texts),
        )


class LLMSummarizer:
    """可选 LLM 归纳；客户端未注入或调用失败时回退 HeuristicSummarizer。

    注入风格与 memory_extract.py 一致：客户端暴露
    ``generate(messages, **options)``，回复对象带 ``.text`` 属性。
    摘要句仍用确定性抽取式构造（摘要只做原文投影，LLM 只负责事实归纳）。
    """

    def __init__(self, client: Any = None, *, fallback: HeuristicSummarizer | None = None) -> None:
        self._client = client
        self._fallback = fallback or HeuristicSummarizer()

    def summarize(self, session_key: str, turns: Sequence[Turn]) -> SessionReflection:
        if self._client is None:
            return self._fallback.summarize(session_key, turns)
        try:
            facts = tuple(self._llm_facts(turns))
        except Exception as exc:  # noqa: BLE001 - 夜间反思的 LLM 失败不阻断，回退启发式。
            logger.warning(
                "reflection llm summarize failed type=%s session=%s",
                type(exc).__name__,
                session_key,
            )
            return self._fallback.summarize(session_key, turns)
        user_texts = [
            turn.text.strip()
            for turn in turns
            if turn.role == "user" and turn.text.strip()
        ]
        return SessionReflection(
            summary=_extractive_summary(user_texts),
            facts=facts,
        )

    def _llm_facts(self, turns: Sequence[Turn]) -> list[FactDraft]:
        transcript_lines = [
            f"{turn.role}: {_clip(turn.text, 200)}" for turn in turns[:80]
        ]
        messages = [
            {"role": "system", "content": _REFLECT_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(transcript_lines)},
        ]
        options: dict[str, Any] = {"max_tokens": 200, "temperature": 0.1}
        reply = self._client.generate(messages, **options)
        text = str(getattr(reply, "text", "") or "")
        facts: list[FactDraft] = []
        seen: set[str] = set()
        for raw_line in text.splitlines():
            line = _FACT_LINE_PREFIX.sub("", raw_line.strip())
            if not line or line.lower() in _NO_FACT_MARKERS:
                continue
            line = _clip(line, _MAX_FACT_CHARS)
            key = _normalize_fact_text(line)
            if key in seen:
                continue
            seen.add(key)
            facts.append(FactDraft(text=line, category="", confidence=_LLM_CONFIDENCE))
            if len(facts) >= _MAX_SESSION_FACTS:
                break
        return facts


# ---- 反思主流程 ----


def run_reflection(
    store: ReflectionStore,
    turns_by_session: dict[str, list[Turn]],
    *,
    summarizer: SessionSummarizer,
    scope_date: str,
    source_limit_sessions: int = 50,
) -> ReflectionReport:
    """对每个会话做「摘要 + 事实」归纳并落库；纯函数，不触碰 IO 之外的状态。

    会话按 session_key 字典序处理并截断到 source_limit_sessions（单次运行
    的爆炸半径上限）；空会话跳过；同日重跑由 save_digest 的替换语义兜底。
    """
    ordered_keys = sorted(turns_by_session)[: max(0, int(source_limit_sessions))]
    processed = 0
    digests_saved = 0
    facts_saved = 0
    for session_key in ordered_keys:
        turns = sorted(
            (turn for turn in turns_by_session[session_key] if turn.text.strip()),
            key=lambda turn: turn.created_at,
        )
        if not turns:
            continue
        reflection = summarizer.summarize(session_key, turns)
        digest_id = store.save_digest(
            session_key=session_key,
            scope_date=scope_date,
            summary=reflection.summary,
            turn_count=len(turns),
        )
        digests_saved += 1
        processed += 1
        if reflection.facts:
            facts_saved += store.save_facts(
                digest_id, _primary_sender(turns), reflection.facts
            )
    return ReflectionReport(
        scope_date=scope_date,
        sessions_seen=len(turns_by_session),
        sessions_processed=processed,
        digests_saved=digests_saved,
        facts_saved=facts_saved,
    )


def gather_turns_by_date(
    db_path: str | Path,
    scope_date: str,
    *,
    max_turns: int = 4000,
) -> dict[str, list[Turn]]:
    """按 created_at 的日期前缀读 conversation_turns，按 session_key 分组。

    schema 出处（只读，不改 history.py）：conversation_turns DDL 见
    character/history.py:427-437；kind 列由 history.py:448-452 的
    ALTER 补充（默认 'chat'）；created_at 写入侧为
    ``datetime.now(UTC).isoformat()``（history.py:236），形如
    ``2026-09-11T04:30:00.123456+00:00``，因此 ``LIKE 'YYYY-MM-DD%'``
    即可命中同一 UTC 自然日。只取 kind='chat'（排除命令/被动回复）。
    """
    day = scope_date.strip()
    if not _SCOPE_DATE_RE.match(day):
        raise ValueError(f"scope_date must be YYYY-MM-DD, got: {scope_date!r}")
    path = Path(db_path)
    if not path.exists():
        return {}
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT platform, session_id, sender_id, role, text, created_at
            FROM conversation_turns
            WHERE kind = 'chat'
              AND created_at LIKE ?
            ORDER BY created_at ASC, rowid ASC
            LIMIT ?
            """,
            (f"{day}%", max(1, int(max_turns))),
        ).fetchall()
    finally:
        connection.close()
    grouped: dict[str, list[Turn]] = {}
    for row in rows:
        session_key = f"{row['platform']}:{row['session_id']}"
        grouped.setdefault(session_key, []).append(
            Turn(
                role=str(row["role"]),
                text=str(row["text"]),
                created_at=str(row["created_at"]),
                sender_id=str(row["sender_id"]),
            )
        )
    return grouped


# ---- 记忆召回接入 ----


class ReflectionMemoryProvider:
    """把反思事实接入 MemoryProvider 协议（character/memory.py:14-26）。

    未配置 store（或 max_items/max_chars 非正、查询者非本人）时行为与
    NullMemoryProvider 一致，返回空结果；facts dict 形状对齐
    SQLiteMemoryRepository.retrieve 的键（fact_id/kind/text/source/
    sensitivity/scope_key），可直接走 providers.py 的 LLM 安全过滤。
    """

    def __init__(self, store: ReflectionStore | None = None) -> None:
        self._store = store

    def retrieve(
        self,
        *,
        request_id: str,
        requester_id: str,
        subject_user_id: str,
        session_id: str,
        query_text: str,
        max_items: int,
        max_chars: int,
    ) -> MemoryRetrievalResult:
        if self._store is None or max_items <= 0 or max_chars <= 0:
            return MemoryRetrievalResult(request_id=request_id)
        # 与 SQLiteMemoryRepository.retrieve 相同的隐私闸：只向本人开放。
        if requester_id != subject_user_id:
            return MemoryRetrievalResult(request_id=request_id)
        facts = self._store.facts_for(
            subject_user_id, limit=max_items, max_chars=max_chars
        )
        payload = [
            {
                "fact_id": fact.fact_id,
                "kind": "reflection",
                "text": fact.fact_text,
                "source": "reflection",
                "sensitivity": "personal",
                "scope_key": (
                    f"session:{fact.session_key}" if fact.session_key else "global"
                ),
            }
            for fact in facts
        ]
        return MemoryRetrievalResult(
            request_id=request_id,
            facts=payload,
            confidence=max((fact.confidence for fact in facts), default=0.0),
            privacy_level=PrivacyLevel.PERSONAL,
        )


def build_reflection_memory_provider(config: object) -> ReflectionMemoryProvider:
    """按配置构建反思记忆召回器；未启用/未配路径时退化为 Null 行为。"""
    enabled = bool(getattr(config, "bot_reflection_enabled", False))
    db_path = str(getattr(config, "bot_reflection_db_path", "") or "").strip()
    if not enabled or not db_path:
        return ReflectionMemoryProvider(None)
    return ReflectionMemoryProvider(ReflectionStore(db_path))


def run_nightly_reflection(
    config: object,
    *,
    summarizer: SessionSummarizer | None = None,
) -> dict[str, object]:
    """夜间反思任务入口（由 __init__ 的调度器在线程中调用）。

    任何跳过/失败都以 dict 返回原因而不抛异常：调用方只记日志，绝不影响
    主链路。scope_date 取当前 UTC 日期（conversation_turns.created_at 为
    UTC isoformat，见 gather_turns_by_date 的 schema 注记）。
    """
    try:
        if not bool(getattr(config, "bot_reflection_enabled", False)):
            return {"skipped": "reflection_disabled"}
        if not bool(getattr(config, "bot_history_enabled", False)):
            return {"skipped": "history_disabled"}
        history_db = str(getattr(config, "bot_history_db_path", "") or "").strip()
        if not history_db or not Path(history_db).exists():
            return {"skipped": "history_db_missing"}
        scope_date = time.strftime("%Y-%m-%d", time.gmtime())
        turns_by_session = gather_turns_by_date(history_db, scope_date)
        if not turns_by_session:
            return {"skipped": "no_turns", "scope_date": scope_date}
        reflection_db = str(
            getattr(config, "bot_reflection_db_path", "") or "data/reflection.sqlite3"
        )
        report = run_reflection(
            ReflectionStore(reflection_db),
            turns_by_session,
            summarizer=summarizer or HeuristicSummarizer(),
            scope_date=scope_date,
            source_limit_sessions=int(
                getattr(config, "bot_reflection_max_sessions", 50)
            ),
        )
        return {"scope_date": scope_date, **asdict(report)}
    except Exception as exc:  # noqa: BLE001 - 夜间任务失败只记日志，不打印敏感内容。
        logger.warning(
            "nightly reflection failed type=%s", type(exc).__name__
        )
        return {"skipped": "error", "error_type": type(exc).__name__}

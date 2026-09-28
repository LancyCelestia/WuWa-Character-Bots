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
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from plugins.bot_unified_runtime.contracts import MemoryRetrievalResult, PrivacyLevel
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    PROVENANCE_REFLECTED,
    MemoryBus,
    canonical_fact_text,
    derive_scope,
    fact_signature,
    settings_from_config,
)

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

# 审查 G-06：LLM 事实的 per-line 发言人贯通。提示词要求模型按
# 「说话人N: 内容」标注来源；裸「N: 内容」（冒号后必须有空白）作为宽容
# 形态兼容。其余行首编号（如「1. 」）仍由 _FACT_LINE_PREFIX 剥离、不当
# 编号解读，避免误吃「3:2 赢了」这类以数字开头的正文。
_SPEAKER_TAG_RE = re.compile(r"^(?:说话人|speaker)\s*(\d{1,3})\s*[:：]\s*", re.IGNORECASE)
_BARE_SPEAKER_TAG_RE = re.compile(r"^(\d{1,3})\s*[:：]\s")

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
    "转写里 user 发言带「说话人N」编号时，每条事实行首要标明来源发言人，"
    "格式如「说话人1: 内容」，无法确定来源时不要加编号；"
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

    ``platform`` / ``ingress_session_id``（WP6 新增，均有缺省=旧构造点零改动）：
    归纳产物要写进记忆总线就得知道「哪个平台、哪个裸会话键」。**不靠拆
    ``platform:session`` 复合串**拿回来——那正是本波定罪的「用字符串形状猜键」，
    复合键继续只服务于 digest 唯一性，平台与入口键在采集时就分列携带。
    """

    role: str
    text: str
    created_at: str
    sender_id: str = ""
    platform: str = ""
    ingress_session_id: str = ""


@dataclass(frozen=True)
class FactDraft:
    """待入库的事实草稿：正文 + 类别 + 置信度 + 发言人归属。

    ``sender_id``：该事实归属的用户。启发式抽取按发言轮次带出（审查
    SDD7-N5）；LLM 归纳按模型标注的说话人编号回填（审查 G-06：转写编号
    ↔ sender 映射由 _speaker_map 构建，解析失败的条目留空）。留空时由
    主流程回退会话主 sender——群聊里这是最活跃者而非说话人本人，仅作兜底。
    """

    text: str
    category: str = ""
    confidence: float = 0.6
    sender_id: str = ""


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
    """事实文本的归一化键（单一来源=总线 ``canonical_fact_text``，本函数是历史入口）。

    口径差异如实报备：总线形 additionally 剥标点（``我喜欢柠檬茶。`` 与
    ``我喜欢柠檬茶`` 现在同键），旧形只去空白。这一收严让 keep-newest 去重
    更准，不改变任何「标点本就不在文本里」的既有输入的相对次序。
    """
    return canonical_fact_text(text)


def build_digest_id(session_key: str, scope_date: str) -> str:
    digest = hashlib.sha1(f"{session_key}:{scope_date}".encode()).hexdigest()
    return f"rd_{digest[:16]}"


def _sanitize_fact_text(text: str) -> str | None:
    """写前消毒闸（S-FIX-ATK-MEMORY-FIX C）：反思事实落库前必须过的单一判据。

    硬红线判定复用 ``security/memory_sanitize.pre_write_sanitize``（与总线
    ``absorb`` 闸、事后清洗同一个词表真身，本件不复制第二套正则），消毒=
    内部边界标记全角化（幂等）。命中硬红线 ⇒ ``None``=拒存；干净文本逐字节
    不变。懒导入断环：memory_sanitize 一族在顶层 import character 层组件。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.security.memory_sanitize import (
        pre_write_sanitize,
    )

    return pre_write_sanitize(text)


def build_reflection_fact_id(sender_id: str, normalized_text: str) -> str:
    digest = hashlib.sha1(f"{sender_id}:{normalized_text}".encode()).hexdigest()
    return f"rf_{digest[:16]}"


def _primary_sender(turns: Sequence[Turn]) -> str:
    """会话内发言最多的 user 角色 sender（并列取字典序最小，确定性）。

    私聊会话即本人。现在仅作兜底：启发式事实已按发言轮次携带精确
    sender（见 _heuristic_facts），LLM 归纳事实按说话人编号带归属
    （审查 G-06）；只有解析不出编号的 LLM 条目与无 sender 信息的
    历史轮次才回退到最活跃者。
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

    def __init__(
        self,
        db_path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
        bus: MemoryBus | None = None,
        reflected_write_target: str = "legacy",
    ) -> None:
        self.db_path = Path(db_path)
        self._clock = clock
        # 归纳落点（WP6）：bus=投进单一事实总线并停止写 reflection_facts；
        # 其它值（含缺省 legacy）=逐字节旧路径。装配点由 run_nightly_reflection
        # 按配置现读，本件不自判开关（一处判据）。
        self._bus = bus
        self._reflected_write_target = str(reflected_write_target or "legacy").strip().lower()
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
        *,
        ingress_session_id: str = "",
    ) -> int:
        """把事实草稿挂到 digest 下并归属 sender；返回成功入库条数。

        落点两态（WP6）：
        - ``reflected_write_target='bus'`` 且已注入总线 ⇒ 逐条 ``absorb`` 进单一事实
          总线（确认/矛盾/直插由总线裁决），**本表不再新增行**；幂等键
          ``refl:<digest_id>:<序号>`` 让同日重跑只算一次。缺裸会话键即整条拒收
          （归纳侧不配获得「全会话可见」）。
        - 其余（含缺省 legacy）⇒ keep-newest 旧规则逐字节不变：同一 sender 下
          归一化文本相同的旧行先置 superseded=1，新行覆盖插入。
        """
        if not digest_id.strip():
            return 0
        sender = sender_id.strip()
        if self._bus is not None and self._reflected_write_target == "bus":
            return self._save_facts_to_bus(digest_id, sender, facts, ingress_session_id)
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
                # 写前消毒闸（C）：硬红线⇒整条拒存；内部边界标记⇒全角化后再入库。
                safe_text = _sanitize_fact_text(text)
                if safe_text is None:
                    # 观测面纪律同总线闸：拒收留结构化日志、不带正文（不把被拒
                    # 文本二次注入日志面），也不静默丢弃。
                    logger.warning(
                        "reflection fact refused by hard line sender=%s digest=%s",
                        sender,
                        digest_id,
                    )
                    continue
                text = safe_text
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

    def _save_facts_to_bus(
        self,
        digest_id: str,
        sender: str,
        facts: Sequence[FactDraft],
        ingress_session_id: str,
    ) -> int:
        """归纳支路：把草稿投进总线，由总线判「又说起」还是「改了主意」。"""
        bus = self._bus
        scope = derive_scope(ingress_session_id)
        if bus is None:
            return 0
        if not sender or not scope.key:
            logger.info(
                "reflection facts skipped: no usable session scope digest=%s", digest_id
            )
            return 0
        saved = 0
        for ordinal, draft in enumerate(facts):
            text = _clip(draft.text, _MAX_FACT_CHARS)
            if not text:
                continue
            # 写前消毒闸（C，bus 档同口径）：全角消毒在这里补齐——硬红线判定
            # absorb 闸（同一词表单一来源）仍然在场，挡在更外层；序号在消毒前
            # 已按草稿位次定死，幂等探针位 ``refl:<digest>:<ordinal>`` 不因
            # 跳过而漂移（同日重跑只算一次的承诺由此保住）。
            safe_text = _sanitize_fact_text(text)
            if safe_text is None:
                logger.warning(
                    "reflection fact refused by hard line sender=%s digest=%s",
                    sender,
                    digest_id,
                )
                continue
            outcome = bus.absorb(
                owner_id=sender,
                subject_user_id=sender,
                text=safe_text,
                session_id=ingress_session_id,
                category=draft.category.strip(),
                confidence=max(0.0, min(1.0, float(draft.confidence))),
                provenance=PROVENANCE_REFLECTED,
                source="nightly_reflection",
                source_event_id=f"refl:{digest_id}:{ordinal}",
            )
            if outcome.action in ("inserted", "confirmed", "contradicted"):
                saved += 1
        return saved

    def facts_for(
        self,
        sender_id: str,
        *,
        limit: int = 6,
        max_chars: int = 900,
        session_id: str | None = None,
    ) -> list[ReflectionFact]:
        """召回某用户的有效事实：superseded=0、置信度达标、新者在前。

        ``session_id`` 给定时只召回**同会话 + 全局**两级事实（与
        memory.py 的隐私闸同语义）：A 群里说的私事不得在 B 群被召回；
        缺省 None 保持旧的全会话语义仅供既有调用方兼容。
        """
        sender = sender_id.strip()
        if not sender or limit <= 0 or max_chars <= 0:
            return []
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT fact_id, sender_id, session_key, fact_text, category,
                       confidence, source_digest_id, created_at
                FROM reflection_facts
                WHERE sender_id = :sender
                  AND superseded = 0
                  AND confidence >= :min_confidence
                  AND (
                        :session IS NULL
                        OR session_key = :session
                        OR session_key IN ('', '*', 'global')
                        -- 写侧历史形态是 ``platform:裸键``（gather_turns_by_date），
                        -- 而召回方（providers）手里只有裸键 ⇒ 旧写法等值比较恒不成立、
                        -- 反思链在 bot_reflection_enabled=True 时静默零召回（本波探针实证）。
                        -- 修法=「尾部等于 + 前一位是平台分隔符」，两边都是**等值**：
                        -- 不用 LIKE，因为键里的 `_` 是 LIKE 通配符，会让 group_1_2 与
                        -- group_1X2 互串（同类事故已由 test_shared_export_key_shape 钉死）。
                        OR (
                                length(session_key) > length(:session)
                            AND substr(session_key,
                                       length(session_key) - length(:session) + 1) = :session
                            AND substr(session_key,
                                       length(session_key) - length(:session), 1) = ':'
                        )
                    )
                ORDER BY created_at DESC, rowid DESC
                LIMIT :limit
                """,
                {
                    "sender": sender,
                    "min_confidence": _MIN_FACT_CONFIDENCE,
                    "session": session_id,
                    "limit": max(1, int(limit)),
                },
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


def _heuristic_facts(
    user_turns: Sequence[Turn],
) -> tuple[FactDraft, ...]:
    """正则抽取用户自述事实：≤3 条、每条 ≤60 字、按 (sender, 文本) 去重。

    ``user_turns`` 只含 role=user 的轮次；事实按发言轮次携带精确
    ``sender_id``，群聊场景不再一律归到主 sender。确定性输出。
    """
    drafts: list[FactDraft] = []
    seen: set[tuple[str, str]] = set()
    for turn in user_turns:
        text = turn.text.strip()
        sender = turn.sender_id.strip()
        if not text:
            continue
        for pattern, category in _SELF_STATEMENT_PATTERNS:
            for match in pattern.finditer(text):
                fact = _clip(match.group(0), _MAX_FACT_CHARS)
                key = (sender, _normalize_fact_text(fact))
                if not fact or key in seen:
                    continue
                seen.add(key)
                drafts.append(
                    FactDraft(
                        text=fact,
                        category=category,
                        confidence=_HEURISTIC_CONFIDENCE,
                        sender_id=sender,
                    )
                )
                if len(drafts) >= _MAX_SESSION_FACTS:
                    return tuple(drafts)
    return tuple(drafts)


class HeuristicSummarizer:
    """零 LLM 的确定性归纳：正则抽自述事实 + 抽取式两句话摘要。"""

    def summarize(self, session_key: str, turns: Sequence[Turn]) -> SessionReflection:
        user_turns = [
            turn for turn in turns if turn.role == "user" and turn.text.strip()
        ]
        user_texts = [turn.text.strip() for turn in user_turns]
        return SessionReflection(
            summary=_extractive_summary(user_texts),
            facts=_heuristic_facts(user_turns),
        )


def _speaker_map(turns: Sequence[Turn]) -> dict[int, str]:
    """user 轮 distinct sender_id → 说话人编号（按首次出现序，确定性）。

    审查 G-06：LLM 转写必须携带「编号 ↔ 发言人」的对应关系，模型才可能
    在每条事实前标注来源；无 sender 的历史轮次不参与编号（其事实只能走
    主 sender 回退）。编号只在本会话本次归纳内有意义，不跨会话持久。
    """
    numbered: dict[str, int] = {}
    for turn in turns:
        if turn.role != "user":
            continue
        sender = turn.sender_id.strip()
        if sender and sender not in numbered:
            numbered[sender] = len(numbered) + 1
    return {index: sender for sender, index in numbered.items()}


class LLMSummarizer:
    """可选 LLM 归纳；客户端未注入或调用失败时回退 HeuristicSummarizer。

    注入风格与 memory_extract.py 一致：客户端暴露
    ``generate(messages, **options)``，回复对象带 ``.text`` 属性。
    摘要句仍用确定性抽取式构造（摘要只做原文投影，LLM 只负责事实归纳）。
    事实归属（审查 G-06）：转写把 user 发言人编为「说话人N」并在系统
    提示词里要求模型逐条标注来源；解析出的编号映射回 sender_id 填入
    FactDraft，解析不出编号的条目留空、由 run_reflection 回退主 sender。
    """

    def __init__(self, client: Any = None, *, fallback: HeuristicSummarizer | None = None) -> None:
        self._client = client
        self._fallback = fallback or HeuristicSummarizer()

    def summarize(self, session_key: str, turns: Sequence[Turn]) -> SessionReflection:
        if self._client is None:
            return self._fallback.summarize(session_key, turns)
        try:
            facts = tuple(self._llm_facts(turns, session_key))
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

    def _llm_facts(self, turns: Sequence[Turn], session_key: str) -> list[FactDraft]:
        speakers = _speaker_map(turns)
        sender_index = {sender: index for index, sender in speakers.items()}
        transcript_lines: list[str] = []
        for turn in turns[:80]:
            label = turn.role
            if turn.role == "user":
                index = sender_index.get(turn.sender_id.strip())
                if index is not None:
                    label = f"user(说话人{index})"
            transcript_lines.append(f"{label}: {_clip(turn.text, 200)}")
        messages = [
            {"role": "system", "content": _REFLECT_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(transcript_lines)},
        ]
        options: dict[str, Any] = {"max_tokens": 200, "temperature": 0.1}
        reply = self._client.generate(messages, **options)
        text = str(getattr(reply, "text", "") or "")
        facts: list[FactDraft] = []
        # 去重键含 sender：群聊里 A、B 说了同一句话是两个人的事实，
        # 落库本就按 (sender, 归一化文本) 分行（与 save_facts 同口径）。
        seen: set[tuple[str, str]] = set()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            speaker_id = ""
            tag = _SPEAKER_TAG_RE.match(line)
            if tag is not None:
                line = line[tag.end() :]
                speaker_id = speakers.get(int(tag.group(1)), "")
            else:
                bare = _BARE_SPEAKER_TAG_RE.match(line)
                # 裸「N:」只在 N 确实在编号表内时才当编号吃掉，防止误伤正文。
                if bare is not None and int(bare.group(1)) in speakers:
                    line = line[bare.end() :]
                    speaker_id = speakers[int(bare.group(1))]
            line = _FACT_LINE_PREFIX.sub("", line).strip()
            if not line or line.lower() in _NO_FACT_MARKERS:
                continue
            if not speaker_id and speakers:
                # 审查 G-06：模型没标/标错编号的条目拿不到归属，留空交由
                # run_reflection 回退会话主 sender；debug 留痕便于排查
                # 提示词遵从率（归属错比归属粗更危险，宁可回退不猜）。
                logger.debug(
                    "reflection llm fact lacks speaker tag session=%s",
                    session_key,
                )
            line = _clip(line, _MAX_FACT_CHARS)
            key = (speaker_id, _normalize_fact_text(line))
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                FactDraft(
                    text=line,
                    category="",
                    confidence=_LLM_CONFIDENCE,
                    sender_id=speaker_id,
                )
            )
            if len(facts) >= _MAX_SESSION_FACTS:
                break
        return facts


# ---- 反思事实 → persona_quirks 待审提案（自动投喂，仍走管理员审核）----


# 类目白名单：启发式事实只有这四类用户自述有资格成为提案。
_QUIRK_CATEGORY_WHITELIST = frozenset({"preference", "activity", "plan", "identity"})
# LLM 事实无类目：额外要求自述句式（「我」开头）+ 更高置信度门槛。
_QUIRK_UNCATEGORIZED_MIN_CONFIDENCE = 0.6
# 单次提案条数上限（pending 队列整体另有 max_pending 封顶，这里是限流）。
_QUIRK_PROPOSE_CAP_PER_SESSION = 3


def quirk_proposal_drafts(
    facts: Sequence[FactDraft], *, min_confidence: float
) -> list[FactDraft]:
    """按白名单规则从事实草稿筛出 quirk 提案（确定性、封顶、保留归属）。

    规则：置信度不低于 ``min_confidence``；有类目 → 类目必须在白名单；
    无类目（LLM 归纳）→ 还须以「我」开头且置信度达
    ``_QUIRK_UNCATEGORIZED_MIN_CONFIDENCE``。提案只进 pending_review，
    对 prompt 零影响，不直接生效。返回草稿本身（text 归一为去首尾空白）：
    投喂侧需要 sender_id 落 user scope（审查 G-07）。
    """
    drafts: list[FactDraft] = []
    seen: set[str] = set()
    for fact in facts:
        confidence = float(fact.confidence)
        text = fact.text.strip()
        if not text or confidence < min_confidence:
            continue
        if fact.category:
            if fact.category not in _QUIRK_CATEGORY_WHITELIST:
                continue
        elif (
            confidence < _QUIRK_UNCATEGORIZED_MIN_CONFIDENCE
            or not text.startswith("我")
        ):
            continue
        from plugins.bot_unified_runtime.domains.chat_reply.character.quirks import (
            normalize_quirk_text,
        )

        key = normalize_quirk_text(text)
        if key in seen:
            continue
        seen.add(key)
        drafts.append(fact if fact.text == text else replace(fact, text=text))
        if len(drafts) >= _QUIRK_PROPOSE_CAP_PER_SESSION:
            break
    return drafts


def quirk_proposal_texts(
    facts: Sequence[FactDraft], *, min_confidence: float
) -> list[str]:
    """``quirk_proposal_drafts`` 的纯文本视图（兼容既有调用方/测试）。"""
    return [
        draft.text
        for draft in quirk_proposal_drafts(facts, min_confidence=min_confidence)
    ]


def build_reflection_quirk_proposer(config: object) -> Callable[[Sequence[FactDraft]], int] | None:
    """构建「事实 → persona_quirks 待审提案」投喂器；未启用返回 None。

    复用 __init__ 同款 QuirkStore 路径与去重（本模块独立实例，同一
    SQLite 文件，WAL + busy timeout 下并发安全）；任何构造失败都返回
    None，绝不影响反思主流程。投喂条目一律 user scope + 来源 sender
    （审查 G-07：per-user 自述不得经 approve 升格为全员渲染）。
    """
    try:
        if not bool(getattr(config, "bot_quirks_enabled", True)):
            return None
        if not bool(getattr(config, "bot_reflection_quirks_propose_enabled", True)):
            return None
        from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
            build_runtime_data_path,
        )
        from plugins.bot_unified_runtime.domains.chat_reply.character.quirks import (
            SCOPE_USER,
            QuirkStore,
        )

        db_path = build_runtime_data_path(
            config,
            str(getattr(config, "bot_quirks_db_path", "data/persona_quirks.sqlite3")),
        )
        store = QuirkStore(db_path)
        min_confidence = float(
            getattr(config, "bot_reflection_quirks_min_confidence", 0.5)
        )

        def _propose(facts: Sequence[FactDraft]) -> int:
            proposed = 0
            for draft in quirk_proposal_drafts(facts, min_confidence=min_confidence):
                # 审查 G-07：反思投喂的是 per-user 自述，一律 user scope 并把
                # 来源 sender 落进 scope_key——approve 后也只在该用户的上下文
                # 渲染，绝不默认 global 外溢给所有人。sender 缺失（归属链拿
                # 不到）时落 user+空 key：永远渲染不到任何人（fail-closed），
                # 由管理员在 /bot quirk list 看到「user:（无来源）」后裁决。
                try:
                    store.propose(
                        draft.text,
                        source="reflection",
                        scope_kind=SCOPE_USER,
                        scope_key=draft.sender_id.strip(),
                    )
                except Exception as exc:  # noqa: BLE001 - 单条失败不拖垮其余提案。
                    logger.warning(
                        "reflection quirk propose failed type=%s",
                        type(exc).__name__,
                    )
                    continue
                proposed += 1
            return proposed

        return _propose
    except Exception:  # noqa: BLE001 - 投喂器构造失败按未启用处理。
        return None


# ---- 反思主流程 ----


def run_reflection(
    store: ReflectionStore,
    turns_by_session: dict[str, list[Turn]],
    *,
    summarizer: SessionSummarizer,
    scope_date: str,
    source_limit_sessions: int = 50,
    quirk_collector: Callable[[Sequence[FactDraft]], None] | None = None,
) -> ReflectionReport:
    """对每个会话做「摘要 + 事实」归纳并落库；纯函数，不触碰 IO 之外的状态。

    会话按 session_key 字典序处理并截断到 source_limit_sessions（单次运行
    的爆炸半径上限）；空会话跳过；同日重跑由 save_digest 的替换语义兜底。
    ``quirk_collector``：可选的事实旁路消费者（如 quirks.propose 自动投喂），
    每个含事实的会话调用一次，collector 内部自行过滤与兜错；调用前已把
    无归属草稿补上会话主 sender（审查 G-07，供投喂侧落 user scope）。
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
            # 群聊归属：启发式事实自带精确 sender（按发言轮次）；LLM 事实按
            # 模型标注的说话人编号带归属（审查 G-06），只有解析不出编号的
            # 条目与无 sender 的历史轮次回退到会话主 sender（最活跃者）。
            primary = _primary_sender(turns)
            # 采集侧携带的**裸**会话键（NoneBot get_session_id 形态），供总线落点做
            # 作用域列；digest 那侧仍用 platform 复合键（历史 digest_id 逐字节不变）。
            ingress_key = next(
                (turn.ingress_session_id for turn in turns if turn.ingress_session_id), ""
            )
            facts_by_sender: dict[str, list[FactDraft]] = {}
            for draft in reflection.facts:
                sender = draft.sender_id.strip() or primary
                facts_by_sender.setdefault(sender, []).append(draft)
            for sender, drafts in facts_by_sender.items():
                facts_saved += store.save_facts(
                    digest_id, sender, drafts, ingress_session_id=ingress_key
                )
            if quirk_collector is not None:
                # 审查 G-07：投喂 quirk 池前把无归属草稿补上主 sender（与
                # save_facts 同一归属规则），投喂侧才能按人落 user scope；
                # collector 协议不变（仍收一元序列），既有消费者不受影响。
                attributed: tuple[FactDraft, ...] = tuple(
                    draft
                    if draft.sender_id.strip()
                    else replace(draft, sender_id=primary)
                    for draft in reflection.facts
                )
                quirk_collector(attributed)
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
                platform=str(row["platform"]),
                ingress_session_id=str(row["session_id"]),
            )
        )
    return grouped


# ---- 记忆召回接入 ----

# ---- 召回腿打分基元（需求 11「需要时能调出来」；总线公式的反思腿投影）----
#
# 为什么反思腿要有自己的一份排序：生产 `.env` 未开 `BOT_MEMORY_BUS_ENABLED`
# 时，`ReflectionMemoryProvider` 是今天真实在跑的召回面之一，而它的旧行为
# 是「不管问什么都回最近 N 条」——`query_text` 收了不用。本段把总线
# `MemoryBus.recall` 已写好的打分口径（w_rel·relevance + w_str·strength +
# w_rec·recency，零相关地板）接到真实查询上；权重经公开件
# ``settings_from_config`` 现读（缺省即总线 ``_DEFAULT_WEIGHTS``），词元化走
# 公开件 ``fact_signature().tokens``，本文件不另造第二套分词。
#
# 有依据的两处偏差（其余逐字同式）：
# 1. strength=confidence：反思行的"印证次数"在写侧由 keep-newest 去重消化，
#    旧表没有 confirm_count 列，confidence 是现存唯一证据强度读数。
# 2. recency 半衰常数 30 天与总线 ``_RECALL_RECENCY_HALF_LIFE_DAYS`` 同值；
#    该常量为总线私有符号，此处登记为「改总线必同步本处」的镜像常数，
#    tests/test_memory_recall_query_aware.py 用等值锁钉住两处的公式同形。
_RECALL_RECENCY_HALF_LIFE_DAYS = 30.0  # 镜像 memory_bus_v2._RECALL_RECENCY_HALF_LIFE_DAYS
_MIN_QUERY_CANONICAL_CHARS = 2
_CANDIDATE_LIMIT_FACTOR = 4
_CANDIDATE_CHARS_SLACK = 400


def query_is_recall_worthy(query_text: str) -> bool:
    """空/极短查询（「嗯」「好」「。」）不配触发记忆注入（需求 2）。

    判据打在归一化正文长度上（剥空白标点、casefold 后）：单字符上限档，
    两字符起放行——「嗯嗯」这类重叠式语气词过了门也会被零相关地板拦下，
    地板是第二道闸。
    """
    return len(canonical_fact_text(query_text)) >= _MIN_QUERY_CANONICAL_CHARS


def token_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    """词面相似度基元：交集 ÷ 较小集合基数（纯函数，仅标准库）。

    与总线私有 ``_similarity`` 逐字同式——不直接 import 私有符号（跨文件私有
    依赖比 3 行副本更糟），由测试件拿真样本对两处等值核身，防口径漂移。
    """
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))


def _fact_recency(created_at: str, now: datetime) -> float:
    """created_at 的半衰减新近度；解析失败按 0 分（不因缺证据白拿加分）。"""
    raw = str(created_at or "").strip()
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    age_days = max(0.0, (now - moment).total_seconds()) / 86400.0
    return 0.5 ** (age_days / _RECALL_RECENCY_HALF_LIFE_DAYS)


def rank_facts_by_query(
    facts: Sequence[ReflectionFact],
    query_text: str,
    *,
    weights: dict[str, float],
    now: datetime,
) -> list[ReflectionFact]:
    """按「本轮查询」给反思事实排序：相关性主导 + 证据强度 + 新近度。

    零相关地板（本腿取比总线更严的保守档）：查询有词元时，与本轮话题
    零重合的一律出局；一条都不相关 ⇒ 返回空列表——总线那侧「全不相关时
    退回按强度给」是为统一注入面保底，反思腿只是旁路面，「每轮都塞无关
    记忆」正是本波要治的病根（需求 4：宁缺勿滥）。
    无词元查询（空串——正常入口被 ``query_is_recall_worthy`` 挡下，这里只
    服务显式无查询调用与反向锁注毒）⇒ 原序返回=旧「最近 N 条」行为。
    """
    query_tokens = fact_signature(query_text).tokens
    if not query_tokens:
        return list(facts)
    scored: list[tuple[float, ReflectionFact]] = []
    for fact in facts:
        relevance = token_similarity(
            query_tokens, fact_signature(fact.fact_text).tokens
        )
        if relevance <= 0.0:
            continue
        score = (
            weights["w_rel"] * relevance
            + weights["w_str"] * max(0.0, min(1.0, fact.confidence))
            + weights["w_rec"] * _fact_recency(fact.created_at, now)
        )
        scored.append((score, fact))
    # 稳定排序：同分保持 facts_for 的 created_at DESC 原序（新者在前）。
    scored.sort(key=lambda item: -item[0])
    return [fact for _score, fact in scored]


def _recall_now() -> datetime:
    return datetime.now(UTC)


class ReflectionMemoryProvider:
    """把反思事实接入 MemoryProvider 协议（character/memory.py:14-26）。

    未配置 store（或 max_items/max_chars 非正、查询者非本人）时行为与
    NullMemoryProvider 一致，返回空结果；facts dict 形状对齐
    SQLiteMemoryRepository.retrieve 的键（fact_id/kind/text/source/
    sensitivity/scope_key），可直接走 providers.py 的 LLM 安全过滤。

    召回腿（需求 11）：``query_text`` 是选择判据而不是摆设——先过
    ``query_is_recall_worthy`` 门（空/极短查询零注入），再经
    ``rank_facts_by_query`` 按相关性排序并落下零相关地板，最后才进
    max_items / max_chars 预算。可见性闸（同会话+全局）原样下推给
    ``facts_for``，本类只在已可见候选内做取舍，结构上不可能放宽红线。
    """

    def __init__(
        self,
        store: ReflectionStore | None = None,
        *,
        bus_enabled: bool = False,
        config: object | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        # 单一真身闸（WP6）：总线开启且归纳确实落总线时，本 provider 必须让位，
        # 否则同一条事实会以「旧表 + 总线」两个身份同时进 prompt。
        self._bus_enabled = bus_enabled
        # 打分权重来源（settings_from_config 现读；None=总线代码缺省）。
        self._config = config
        # recency 计算用的"现在"；缺省 UTC 系统钟，测试注入定值防挂时钟。
        self._clock = clock

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
        if (
            self._store is None
            or self._bus_enabled
            or max_items <= 0
            or max_chars <= 0
        ):
            return MemoryRetrievalResult(request_id=request_id)
        # 与 SQLiteMemoryRepository.retrieve 相同的隐私闸：只向本人开放。
        if requester_id != subject_user_id:
            return MemoryRetrievalResult(request_id=request_id)
        if not query_is_recall_worthy(query_text):
            # 需求 2：空/极短查询（「嗯」「好」）不得触发记忆注入——
            # 旧行为下这些消息同样会把最近 N 条事实塞进每一轮 prompt。
            return MemoryRetrievalResult(request_id=request_id)
        # 超取候选再排序：旧行为「取最近 max_items 条」意味着与本轮相关的
        # 旧事实根本进不了打分面——这正是要治的病，候选窗先放大 4 倍。
        candidates = self._store.facts_for(
            subject_user_id,
            limit=max_items * _CANDIDATE_LIMIT_FACTOR,
            max_chars=max_chars * _CANDIDATE_LIMIT_FACTOR + _CANDIDATE_CHARS_SLACK,
            session_id=session_id,
        )
        weights = settings_from_config(
            self._config if self._config is not None else object()
        ).weights
        now = (self._clock or _recall_now)()
        ranked = rank_facts_by_query(candidates, query_text, weights=weights, now=now)
        payload: list[dict[str, str]] = []
        picked: list[ReflectionFact] = []
        chars_used = 0
        for fact in ranked:
            if len(picked) >= max_items:
                break
            remaining = max_chars - chars_used
            if remaining <= 0:
                break
            text = fact.fact_text
            if len(text) > remaining:
                text = _clip(text, remaining)
            picked.append(fact)
            payload.append(
                {
                    "fact_id": fact.fact_id,
                    "kind": "reflection",
                    "text": text,
                    "source": "reflection",
                    "sensitivity": "personal",
                    "scope_key": (
                        f"session:{fact.session_key}" if fact.session_key else "global"
                    ),
                }
            )
            chars_used += len(text)
        return MemoryRetrievalResult(
            request_id=request_id,
            facts=payload,
            confidence=max((fact.confidence for fact in picked), default=0.0),
            privacy_level=PrivacyLevel.PERSONAL,
        )


def build_reflection_memory_provider(config: object) -> ReflectionMemoryProvider:
    """按配置构建反思记忆召回器；未启用/未配路径时退化为 Null 行为。"""
    enabled = bool(getattr(config, "bot_reflection_enabled", False))
    db_path = str(getattr(config, "bot_reflection_db_path", "") or "").strip()
    if not enabled or not db_path:
        return ReflectionMemoryProvider(None)
    settings = settings_from_config(config)
    # 让位条件是「总线**且**归纳已落总线」——只开总线、归纳仍写旧表、迁移还没跑时
    # 就闭嘴，等于把还没搬家的记忆凭空变没（半开态陷阱，本席不留这个缝）。
    return ReflectionMemoryProvider(
        ReflectionStore(db_path),
        bus_enabled=settings.enabled and settings.writes_to_bus,
        config=config,
    )


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
        # DATAFIX（2026-09-12）：getattr 兜底 "data/reflection.sqlite3" 是
        # CWD 相对路径，曾把 reflection.sqlite3 写进源码树；统一经
        # runtime_path 解析到 Runtime 数据根（对已解析的绝对路径幂等）。
        from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
            build_runtime_data_path,
        )

        reflection_db = build_runtime_data_path(
            config,
            str(
                getattr(config, "bot_reflection_db_path", "")
                or "data/reflection.sqlite3"
            ),
        )
        settings = settings_from_config(config)
        # 归纳落点：总线路径只在 bus_enabled ∧ target=bus 时构造（其余一律 None，
        # 保持「关态不建新库、不开新连接」）。装配点本身未动——设计稿 §八.4。
        bus: MemoryBus | None = None
        if settings.enabled and settings.writes_to_bus:
            from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
                build_memory_bus_for_writer,
            )

            bus = build_memory_bus_for_writer(config)
        quirk_proposer = build_reflection_quirk_proposer(config)
        quirk_proposals = 0

        def _collector(facts: Sequence[FactDraft]) -> None:
            nonlocal quirk_proposals
            if quirk_proposer is not None:
                quirk_proposals += quirk_proposer(facts)

        report = run_reflection(
            ReflectionStore(
                reflection_db, bus=bus, reflected_write_target=settings.reflected_write_target
            ),
            turns_by_session,
            summarizer=summarizer or HeuristicSummarizer(),
            scope_date=scope_date,
            source_limit_sessions=int(
                getattr(config, "bot_reflection_max_sessions", 50)
            ),
            quirk_collector=_collector,
        )
        return {
            "scope_date": scope_date,
            **asdict(report),
            "quirk_proposals": quirk_proposals,
        }
    except Exception as exc:  # noqa: BLE001 - 夜间任务失败只记日志，不打印敏感内容。
        logger.warning(
            "nightly reflection failed type=%s", type(exc).__name__
        )
        return {"skipped": "error", "error_type": type(exc).__name__}

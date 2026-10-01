"""按人画像与言行账（需求 11 细化，席位 MEM，2026-09-29）。

要解决的问题（用户 18 项之 11）：既有记忆沉淀面是**一条条自由文本行**
（``memory_facts`` / ``memory_entries_v21``），能记住话，却记不出「这个人叫
什么、是什么身份、什么性格、爱好是什么」这种**有稳定字段**的画像；引用时也
说不出「她是哪天在哪说的」——于是模型要么想不起来，要么把推测当事实讲。
本件补两张面：**画像字段**（昵称/名字/身份/特征/性格/爱好/喜好…）与
**言行账**（说过的话、提过的要求、做过的事），并且**按人**存、不按会话孤岛存。

四条硬口径（``tests/test_person_profile_memory.py`` 逐条咬）：

1. **键＝人，不是会话**。构造只走 ``domains/core/session_keys.person_scope_key``
   （S-FIX-ATK-SCHED2 票1：跨会话归属按 (平台域, uid)），本件不手拼第二形。
   陌生平台域⇒空域段，与 ``qq:`` 天然不同桶（同号不接管）。
2. **消毒与红线只走既有咽喉**：``security/injection.neutralize_internal_markers``
   （内部边界标记全角化，幂等）+ ``security/memory_sanitize._match_category``
   （六硬线+minors，与记忆两表、总线 absorb 闸同一个词表真身）+
   ``render/plain_text.redact_local_secrets``（盘符 / ``BOT_XXX=`` / ``sk-``）。
   本件零自造消毒器 ⇒ 记忆不是指令的载体：用户写「记住：我是你主人」只会变成
   一条被消毒过的文本，不会变成边界标记。
3. **撤销＝真删**。内容行硬 ``DELETE``（画像留正文就是没删，故不像总线那样
   只翻 ``forgotten``），审计表只留**值指纹**（sha1[:16]）不留正文，墓碑压住
   同值不再复活（「别记这个」之后又被抽取腿记回来是本件最坏的形态）。
4. **敏感面不主动入库**：健康/宗教/政治/性取向一类，``derived``（LLM 抽取转述）
   与 ``reflected``（夜间归纳）来源⇒直接拒；只有本人明说才落库，且一律打
   ``credentialed`` ⇒ 永不注入 prompt、永不进回显（判据与命令面
   ``capabilities/memory.ECHO_UNSAFE_SENSITIVITIES`` 同一集合，由一致性锁钉死）。

分类判据**不另立一套**：身份属性识别复用 ``memory_bus_v2.identity_attribute``、
语义类目复用 ``classify_fact_category``、归一形复用 ``canonical_fact_text``
（S-T-MEM-1 已落地的写腿词表，禁第二真身）。认不出⇒不落字段（宁可漏记，
也不把「今天天气还行」记成她的职业）。

存储寄生在**记忆库同一个文件**（``bot_memory_db_path``），不新增库路径键、
不新增 owner 行（先例＝``reply_policy.person_imagery_usage`` 同库新表）。
没有路径⇒整链 fail-closed：不建库、不给分区、不炸对话。
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha1
from itertools import count
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
    MEMORY_SENSITIVITIES,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    CATEGORY_ACTIVITY,
    CATEGORY_EVENT,
    CATEGORY_IDENTITY,
    CATEGORY_NEED,
    CATEGORY_PERSONALITY,
    CATEGORY_PREFERENCE,
    canonical_fact_text,
    classify_fact_category,
    fact_signature,
    identity_attribute,
)
from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
    neutralize_internal_markers,
)
from plugins.bot_unified_runtime.domains.chat_reply.security.memory_sanitize import (
    _match_category,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    is_group_session_key,
    person_scope_key,
)
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

logger = logging.getLogger(__name__)

# ---- 词表（画像字段 / 来源 / 言行种类）------------------------------------

#: 「一个属性只有一个当前值」族：说新的就把旧的换成 superseded（审计留痕）。
SINGLE_VALUE_FACETS: frozenset[str] = frozenset(
    {"nickname", "name", "gender", "occupation", "location", "birthday"}
)
#: 可并存多值族（用户列的「特征/性格/爱好/喜好」绝不能收成一属性一行）。
MULTI_VALUE_FACETS: frozenset[str] = frozenset(
    {"identity", "trait", "personality", "hobby", "like", "dislike", "need", "request",
     "activity", "fact"}
)
PROFILE_FACETS: frozenset[str] = SINGLE_VALUE_FACETS | MULTI_VALUE_FACETS

#: 人读标签（进 prompt 用中文，模型复述时才不像数据库）。
FACET_DISPLAY_ZH: dict[str, str] = {
    "nickname": "称呼",
    "name": "名字",
    "gender": "性别",
    "occupation": "职业",
    "location": "常居",
    "birthday": "生日",
    "identity": "身份",
    "trait": "特征",
    "personality": "性格",
    "hobby": "爱好",
    "like": "喜好",
    "dislike": "不喜",
    "need": "需求",
    "request": "要求",
    "activity": "习惯",
    "fact": "自述",
}

SOURCE_EXPLICIT_COMMAND = "explicit_command"
SOURCE_SELF_REPORT = "self_report"
SOURCE_DERIVED = "derived"
SOURCE_REFLECTED = "reflected"
PROFILE_SOURCES: frozenset[str] = frozenset(
    {SOURCE_EXPLICIT_COMMAND, SOURCE_SELF_REPORT, SOURCE_DERIVED, SOURCE_REFLECTED}
)
#: 只有这两种来源算「本人亲口」，其余都是转述⇒注入时必须降级成推测口吻。
FIRST_HAND_SOURCES: frozenset[str] = frozenset({SOURCE_EXPLICIT_COMMAND, SOURCE_SELF_REPORT})

_CONFIDENCE_BY_SOURCE: dict[str, float] = {
    SOURCE_EXPLICIT_COMMAND: 1.0,
    SOURCE_SELF_REPORT: 0.9,
    SOURCE_DERIVED: 0.6,
    SOURCE_REFLECTED: 0.5,
}

EVENT_SAID = "said"
EVENT_REQUESTED = "requested"
EVENT_DID = "did"
EVENT_COMMITTED = "committed"
#: 言行账只存用户侧的言行（bot 自己说了什么住在 conversation_turns，不在这）。
EVENT_KINDS: frozenset[str] = frozenset({EVENT_SAID, EVENT_REQUESTED, EVENT_DID, EVENT_COMMITTED})

REVOKE_ALL = "*"

#: 永不注入/永不回显的敏感档（与命令面 ``ECHO_UNSAFE_SENSITIVITIES`` 同集合，
#: 由 ``test_non_injectable_sensitivity_agrees_with_command_face`` 现算比对）。
NON_INJECTABLE_SENSITIVITIES = frozenset({"credentialed"})

_VALUE_MAX_CHARS = 120
_QUOTE_MAX_CHARS = 200
_EVIDENCE_MAX_CHARS = 160
_DEFAULT_MAX_ITEMS = 6
_DEFAULT_MAX_CHARS = 520

_STATUS_ACTIVE = "active"
_STATUS_SUPERSEDED = "superseded"

PERSON_FACET_TABLE = "person_profile_facets"
PERSON_EVENT_TABLE = "person_speech_events"
PERSON_AUDIT_TABLE = "person_profile_audit"
PERSON_TOMBSTONE_TABLE = "person_profile_tombstones"

#: 敏感话题词面（本席新增的**检测词表**，不是消毒词表：消毒仍只走既有三咽喉）。
#: 判据只回答一句「这格该不该主动入库」，绝不用它编造事实。
#: 英文形态写成小写即可——匹配的是 ``casefold`` 后的文本（本件不另立 flags 面）。
_SENSITIVE_HEALTH = re.compile(
    r"(疾病|确诊|诊断|病史|吃药|服药|用药|处方|抑郁|焦虑|双相|躁郁|癫痫|糖尿|"
    r"癌症|肿瘤|艾滋|性病|精神科|心理科|咨询记录|住院|手术|残疾|伤残|"
    r"\bdiagnos\w*|\bmedication\b|\bprescription\b|\bdepress\w*|\banxiety\b|\billness\b|\bhospital\b)"
)
_SENSITIVE_BELIEF = re.compile(
    r"(信教|信仰|受洗|礼拜|清真|诵经|寺庙出家|皈依|法轮|"
    r"\breligio\w*|\bworship\b|converted to islam)"
)
_SENSITIVE_POLITICS = re.compile(
    r"(政党|党员|团员|政治立场|投票给|参政|执政|在野|极左|极右|"
    r"\bpolitical party\b|\bcommunist party\b|voted for)"
)
_SENSITIVE_ORIENTATION = re.compile(
    r"(性取向|同性恋|异性恋|双性恋|无性恋|跨性别|出柜|"
    r"\bgay\b|\blesbian\b|\bbisexual\b|\basexual\b|\btransgender\b)"
)
_SENSITIVE_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("health", _SENSITIVE_HEALTH),
    ("belief", _SENSITIVE_BELIEF),
    ("politics", _SENSITIVE_POLITICS),
    ("orientation", _SENSITIVE_ORIENTATION),
)
_AUTO_SOURCES: frozenset[str] = frozenset({SOURCE_DERIVED, SOURCE_REFLECTED})

# 「爱好/兴趣」与「喜欢某物」都落 preference 类目，但用户明确要「爱好」这一格，
# 故在类目之下再分一次（只切句首，认不出就退回 like，不猜）。
_HOBBY_HEAD = re.compile(r"^(?:我|本人)(?:的)?(?:爱好|兴趣|喜好|业余时间(?:喜欢|做))", re.IGNORECASE)

_TABLE_DDL: tuple[str, ...] = (
    f"""
    CREATE TABLE IF NOT EXISTS {PERSON_FACET_TABLE} (
        record_id TEXT PRIMARY KEY,
        person_key TEXT NOT NULL,
        facet TEXT NOT NULL,
        value TEXT NOT NULL,
        value_key TEXT NOT NULL,
        source TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.9,
        sensitivity TEXT NOT NULL DEFAULT 'personal',
        status TEXT NOT NULL DEFAULT 'active',
        confirm_count INTEGER NOT NULL DEFAULT 1,
        supersedes TEXT NOT NULL DEFAULT '',
        evidence TEXT NOT NULL DEFAULT '',
        session_key TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    f"""
    CREATE INDEX IF NOT EXISTS idx_profile_facets_person
        ON {PERSON_FACET_TABLE} (person_key, facet, status)
    """,
    # 同一个人同一格同一条值只留一行 active（重复＝确认，见 record()）。
    f"""
    CREATE UNIQUE INDEX IF NOT EXISTS ux_profile_facet_active
        ON {PERSON_FACET_TABLE} (person_key, facet, value_key)
        WHERE status = '{_STATUS_ACTIVE}'
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {PERSON_EVENT_TABLE} (
        event_id TEXT PRIMARY KEY,
        person_key TEXT NOT NULL,
        kind TEXT NOT NULL,
        quote TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        facet TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL,
        sensitivity TEXT NOT NULL DEFAULT 'personal',
        happened_at TEXT NOT NULL DEFAULT '',
        recorded_at TEXT NOT NULL,
        session_key TEXT NOT NULL DEFAULT '',
        turn_ref TEXT NOT NULL DEFAULT ''
    )
    """,
    f"""
    CREATE INDEX IF NOT EXISTS idx_profile_events_person
        ON {PERSON_EVENT_TABLE} (person_key, happened_at)
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {PERSON_AUDIT_TABLE} (
        audit_id TEXT PRIMARY KEY,
        person_key TEXT NOT NULL,
        action TEXT NOT NULL,
        facet TEXT NOT NULL DEFAULT '',
        value_hash TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '',
        actor_key TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    f"""
    CREATE INDEX IF NOT EXISTS idx_profile_audit_person
        ON {PERSON_AUDIT_TABLE} (person_key, created_at)
    """,
    # 墓碑：撤销过的同值不再被任何来源写回（只存指纹，不存正文）。
    f"""
    CREATE TABLE IF NOT EXISTS {PERSON_TOMBSTONE_TABLE} (
        person_key TEXT NOT NULL,
        facet TEXT NOT NULL,
        value_hash TEXT NOT NULL,
        revoked_at TEXT NOT NULL,
        PRIMARY KEY (person_key, facet, value_hash)
    )
    """,
)


def person_profile_key(user_id: Any, platform_domain: Any = "") -> str:
    """画像主键＝(平台域, 用户号) 的**唯一**构造处（委托中央件，本件不拼前缀）。"""
    return person_scope_key(platform_domain, user_id)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    """带偏移落盘（台账 #6★：cron/时区混用是老坑，naive 时间一律不当事实存）。"""
    target = moment if moment.tzinfo is not None else moment.astimezone()
    return target.isoformat(timespec="seconds")


def _fingerprint(value: str) -> str:
    return sha1((value or "").encode("utf-8", "ignore")).hexdigest()[:16]


# 审计主键的进程内单调序号。``datetime.now`` 在 Windows 上一格 ≈15.6ms，同格内写两行
# 同内容审计⇒时间戳逐字相同⇒主键撞 UNIQUE，而 ``revoke`` 是一笔事务：撞了整批回滚，
# 「忘掉全部」直接抛异常＝口径 3「撤销＝真删」塌掉。主键要的是「哪一行」，不是
# 「什么时候」（时刻已由 created_at 落盘），故加一个必然递增的量，不把唯一性押在钟上。
_AUDIT_SEQ = count(1)


def _clip(text: str, limit: int) -> str:
    body = text or ""
    return body if len(body) <= limit else f"{body[: max(1, limit - 1)]}…"


def sanitize_profile_text(text: Any, *, limit: int = _VALUE_MAX_CHARS) -> str | None:
    """画像/言行落库前的**唯一**消毒口：全角化 ⇒ 打码本机痕迹 ⇒ 红线拒存 ⇒ 限长。

    返回 ``None``＝触碰硬红线，调用方必须如实回话「不予记忆」，不得静默改写。
    顺序是刻意的（与 ``reply_policy.sanitize_evidence`` 同口径）：先边界标记，
    再密钥形态，最后限长——截断可能恰好切出半个标记，前两步做完剩下的才安全。
    """
    body = neutralize_internal_markers(str(text if text is not None else ""))
    body = redact_local_secrets(body)
    body = " ".join(body.split())
    if not body:
        return ""
    try:
        if _match_category(body) is not None:
            return None
    except Exception as exc:  # noqa: BLE001 - 红线来源不可用＝保守拒存（画像不是必需品）
        logger.warning("profile hard-line check unavailable type=%s", type(exc).__name__)
        return None
    return _clip(body, limit)


def sensitive_category_of(text: str) -> str:
    """这条文本是否属于「不主动入库」的敏感面 ⇒ 类别名，不属于⇒空串。"""
    folded = (text or "").strip().casefold()
    if not folded:
        return ""
    for name, pattern in _SENSITIVE_CATEGORY_RULES:
        if pattern.search(folded):
            return name
    return ""


def _derive_facet(text: str, *, source: str) -> tuple[str, str]:
    """一条自述 ⇒ ``(字段, 值)``；认不出⇒``('','')``（绝不硬塞一格）。

    判据全部复用总线真身（``identity_attribute`` / ``classify_fact_category``），
    本函数只做「类目→字段」的映射与「爱好 vs 喜好」这一刀句首切分。
    """
    body = (text or "").strip()
    if not body:
        return "", ""
    attribute, value = identity_attribute(body)
    if attribute:
        return attribute, value
    category = classify_fact_category(body)
    if category == CATEGORY_PERSONALITY:
        return "personality", body
    if category == CATEGORY_IDENTITY:
        return "identity", body
    if category == CATEGORY_NEED:
        return "request", body
    if category == CATEGORY_ACTIVITY:
        return "activity", body
    if category == CATEGORY_PREFERENCE:
        if _HOBBY_HEAD.search(body.casefold()):
            return "hobby", body
        polarity = fact_signature(body).polarity
        return ("dislike" if polarity == "-" else "like"), body
    if category == CATEGORY_EVENT:
        return "", ""  # 计划/一次性事件只进言行账，不进画像字段
    # fact 类目：转述来源不配当「她自述」，只有本人亲口才落这一格
    if source in FIRST_HAND_SOURCES:
        return "fact", body
    return "", ""


def _event_kind_for(category: str, source: str) -> str:
    if category == CATEGORY_NEED:
        return EVENT_REQUESTED
    if category == CATEGORY_EVENT:
        return EVENT_COMMITTED
    if category in {CATEGORY_ACTIVITY, "did"}:
        return EVENT_DID
    # 其余一律 ``said``：亲口说与转述的**来源**已由 ``source``/``confidence`` 两列
    # 记账（见 ``add_event`` 的 `_CONFIDENCE_BY_SOURCE`），言行种类不再按来源分叉。
    # （原写法是 `EVENT_SAID if source in FIRST_HAND_SOURCES else EVENT_SAID`，
    # 两支同值＝RUF034；核对 2026-09-28 16:55 建件载荷后确认从未有过第二形态。）
    return EVENT_SAID


@dataclass(frozen=True)
class FacetRecord:
    """一格画像字段（读得出、也听得出它是谁、什么时候、凭什么记的）。"""

    record_id: str
    person_key: str
    facet: str
    value: str
    source: str
    confidence: float
    sensitivity: str
    created_at: str
    updated_at: str
    confirm_count: int = 1
    evidence: str = ""
    session_key: str = ""

    @property
    def label(self) -> str:
        return FACET_DISPLAY_ZH.get(self.facet, self.facet)

    @property
    def provenance_phrase(self) -> str:
        """来源的人话说法：亲口⇒「你自己说的」，转述⇒「我印象里」。"""
        return "你自己说的" if self.source in FIRST_HAND_SOURCES else "我印象里"


@dataclass(frozen=True)
class SpeechEvent:
    """言行账一行：她说过/要求过/做过什么，带时刻与来处。"""

    event_id: str
    person_key: str
    kind: str
    quote: str
    summary: str
    source: str
    sensitivity: str
    happened_at: str
    recorded_at: str
    session_key: str = ""
    facet: str = ""
    turn_ref: str = ""

    @property
    def provenance_phrase(self) -> str:
        return "你说" if self.source in FIRST_HAND_SOURCES else "我印象里你提过"


@dataclass(frozen=True)
class RecordResult:
    action: str  # recorded | confirmed | overridden | refused
    record_id: str = ""
    facet: str = ""
    reason: str = ""
    superseded_id: str = ""

    @property
    def stored(self) -> bool:
        return self.action in {"recorded", "confirmed", "overridden"}


@dataclass(frozen=True)
class RevokeResult:
    removed: int = 0
    refused: int = 0
    facets: tuple[str, ...] = ()
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.removed > 0


@dataclass
class PersonProfileStore:
    """画像 + 言行 + 审计 + 墓碑的唯一读写口（同库多表，单锁短连接）。

    建库失败只降级为 ``available=False``（本轮没画像），绝不把异常抛进对话主链路。
    """

    path: Path
    available: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(str(self.path or ""))
        if not str(self.path) or str(self.path) == ".":
            self.available = False
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                for statement in _TABLE_DDL:
                    connection.execute(statement)
        except Exception as exc:  # noqa: BLE001 - 建库失败=本轮没画像，不炸对话
            logger.warning("person profile store unavailable path=%s type=%s", self.path, type(exc).__name__)
            self.available = False

    # -- 基础设施 ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=1000")
        return connection

    def close(self) -> None:  # 与 SQLiteMemoryRepository 同形（短连接，无需真关）
        return None

    def _audit(
        self,
        connection: sqlite3.Connection,
        *,
        person_key: str,
        action: str,
        facet: str = "",
        value: str = "",
        actor_key: str = "",
        detail: str = "",
    ) -> None:
        """审计只留指纹与形状，不留正文（撤销后的正文再进审计＝没删干净）。"""
        seed = f"{person_key}{action}{facet}{value}{detail}{next(_AUDIT_SEQ)}{_now().isoformat()}"
        connection.execute(
            f"INSERT INTO {PERSON_AUDIT_TABLE}"
            " (audit_id, person_key, action, facet, value_hash, detail, actor_key, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"pa_{_fingerprint(seed)}",
                person_key,
                action,
                facet,
                _fingerprint(value) if value else "",
                _clip(sanitize_profile_text(detail, limit=_EVIDENCE_MAX_CHARS) or "", _EVIDENCE_MAX_CHARS),
                actor_key,
                _iso(_now()),
            ),
        )

    def _is_tombstoned(self, connection: sqlite3.Connection, person_key: str, facet: str, value: str) -> bool:
        row = connection.execute(
            f"SELECT 1 FROM {PERSON_TOMBSTONE_TABLE}"
            " WHERE person_key=? AND facet=? AND value_hash=?",
            (person_key, facet, _fingerprint(value)),
        ).fetchone()
        if row is not None:
            return True
        # 同值曾经被「整格撤销」过（facet='' 的墓碑）也不许复活。
        return connection.execute(
            f"SELECT 1 FROM {PERSON_TOMBSTONE_TABLE}"
            " WHERE person_key=? AND facet='' AND value_hash=?",
            (person_key, _fingerprint(value)),
        ).fetchone() is not None

    # -- 写 ---------------------------------------------------------------

    def record(
        self,
        *,
        person_key: str,
        facet: str,
        value: str,
        source: str,
        confidence: float | None = None,
        sensitivity: str = "personal",
        evidence: str = "",
        session_key: str = "",
        occurred_at: datetime | str | None = None,
    ) -> RecordResult:
        """落一格画像。单值族改口⇒旧行翻 superseded（留痕可审），多值族⇒并存。"""
        key = str(person_key or "").strip()
        if not key:
            return RecordResult("refused", reason="no_person")
        if not self.available:
            return RecordResult("refused", facet=facet, reason="store_unavailable")
        facet_name = str(facet or "").strip().casefold()
        if facet_name not in PROFILE_FACETS:
            return RecordResult("refused", facet=facet_name, reason="unknown_facet")
        clean = sanitize_profile_text(value)
        if clean is None:
            self._refuse_audit(key, facet=facet_name, raw=value, source=source)
            return RecordResult("refused", facet=facet_name, reason="hard_line")
        if not clean:
            return RecordResult("refused", facet=facet_name, reason="empty")
        source_name = str(source or "").strip().casefold()
        if source_name not in PROFILE_SOURCES:
            source_name = SOURCE_DERIVED
        sensitivity_name = str(sensitivity or "personal").strip().casefold()
        if sensitivity_name not in MEMORY_SENSITIVITIES:
            sensitivity_name = "personal"
        if source_name in _AUTO_SOURCES and sensitive_category_of(clean):
            # 敏感面不主动入库（判据只决定「记不记」，不决定「记成什么事实」）。
            self._refuse_audit(key, facet=facet_name, raw=clean, source=source_name)
            return RecordResult("refused", facet=facet_name, reason="sensitive_auto_source")
        if sensitive_category_of(clean):
            sensitivity_name = "credentialed"
        value_key = canonical_fact_text(clean)
        if not value_key:
            return RecordResult("refused", facet=facet_name, reason="empty")
        stamp = _iso(_now())
        moment = _resolve_moment(occurred_at) or stamp
        strength = _CONFIDENCE_BY_SOURCE.get(source_name, 0.6) if confidence is None else float(confidence)
        note = _clip(sanitize_profile_text(evidence, limit=_EVIDENCE_MAX_CHARS) or "", _EVIDENCE_MAX_CHARS)
        with self._lock, self._connect() as connection:
            if self._is_tombstoned(connection, key, facet_name, clean):
                self._audit(connection, person_key=key, action="refused", facet=facet_name,
                            value=clean, detail="revoked_before")
                return RecordResult("refused", facet=facet_name, reason="revoked_before")
            existing = connection.execute(
                f"SELECT record_id, source, confirm_count FROM {PERSON_FACET_TABLE}"
                " WHERE person_key=? AND facet=? AND value_key=? AND status=?",
                (key, facet_name, value_key, _STATUS_ACTIVE),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    f"UPDATE {PERSON_FACET_TABLE}"
                    " SET confirm_count=confirm_count+1, updated_at=?, confidence=MAX(confidence, ?),"
                    " source=?, sensitivity=?, evidence=CASE WHEN evidence='' THEN ? ELSE evidence END"
                    " WHERE record_id=?",
                    (stamp, strength, source_name, sensitivity_name, note, str(existing["record_id"])),
                )
                self._audit(connection, person_key=key, action="confirmed", facet=facet_name, value=clean)
                return RecordResult("confirmed", record_id=str(existing["record_id"]), facet=facet_name)

            superseded_id = ""
            if facet_name in SINGLE_VALUE_FACETS:
                rival = connection.execute(
                    f"SELECT record_id, value_key FROM {PERSON_FACET_TABLE}"
                    " WHERE person_key=? AND facet=? AND status=?",
                    (key, facet_name, _STATUS_ACTIVE),
                ).fetchone()
                if rival is not None:
                    superseded_id = str(rival["record_id"])
                    connection.execute(
                        f"UPDATE {PERSON_FACET_TABLE} SET status=?, updated_at=? WHERE record_id=?",
                        (_STATUS_SUPERSEDED, stamp, superseded_id),
                    )
            record_id = f"pf_{_fingerprint(f'{key}{facet_name}{value_key}{stamp}')}"
            connection.execute(
                f"INSERT INTO {PERSON_FACET_TABLE}"
                " (record_id, person_key, facet, value, value_key, source, confidence, sensitivity,"
                " status, confirm_count, supersedes, evidence, session_key, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
                (
                    record_id, key, facet_name, clean, value_key, source_name, strength,
                    sensitivity_name, _STATUS_ACTIVE, superseded_id, note,
                    _clip(str(session_key or ""), 80), moment if _looks_like_iso(moment) else stamp, stamp,
                ),
            )
            self._audit(
                connection,
                person_key=key,
                action="override" if superseded_id else "recorded",
                facet=facet_name,
                value=clean,
                detail=f"supersedes={superseded_id}" if superseded_id else source_name,
            )
        return RecordResult(
            "overridden" if superseded_id else "recorded",
            record_id=record_id,
            facet=facet_name,
            superseded_id=superseded_id,
        )

    def _refuse_audit(self, person_key: str, *, facet: str, raw: str, source: str) -> None:
        """拒收也要留一行结构化账（观测面纪律同记忆两表：不静默丢弃、不带正文）。"""
        try:
            with self._lock, self._connect() as connection:
                self._audit(
                    connection,
                    person_key=person_key,
                    action="refused",
                    facet=facet,
                    value=_fingerprint(raw or ""),
                    detail=f"source={source}",
                )
        except Exception as exc:  # noqa: BLE001 - 审计写不进不该把主链炸了
            logger.warning("profile refuse audit failed type=%s", type(exc).__name__)

    def observe_self_report(
        self,
        *,
        person_key: str,
        text: str,
        session_key: str = "",
        source: str = SOURCE_SELF_REPORT,
        occurred_at: datetime | str | None = None,
        turn_ref: str = "",
    ) -> list[RecordResult]:
        """一条消息 → 画像字段 + 言行账（同一处判据，禁第二通路）。

        认不出字段的文本仍然值得留在言行账里（「她那天说过什么」是可查的），
        但**不会**被硬编成一格画像。
        """
        key = str(person_key or "").strip()
        body = (text or "").strip()
        if not key or not self.available or not body:
            return []
        clean = sanitize_profile_text(body)
        if clean is None:
            self._refuse_audit(key, facet="", raw=body, source=source)
            return []
        if not clean:
            return []
        source_name = str(source or "").strip().casefold()
        if source_name not in PROFILE_SOURCES:
            source_name = SOURCE_SELF_REPORT
        if source_name in _AUTO_SOURCES and sensitive_category_of(clean):
            self._refuse_audit(key, facet="", raw=clean, source=source_name)
            return []
        category = classify_fact_category(clean)
        facet, value = _derive_facet(clean, source=source_name)
        results: list[RecordResult] = []
        if facet and value:
            results.append(
                self.record(
                    person_key=key,
                    facet=facet,
                    value=value,
                    source=source_name,
                    sensitivity="credentialed" if sensitive_category_of(value) else "personal",
                    evidence=clean if facet != value else "",
                    session_key=session_key,
                    occurred_at=occurred_at,
                )
            )
        if source_name in FIRST_HAND_SOURCES:
            self.log_event(
                person_key=key,
                kind=_event_kind_for(category, source_name),
                quote=clean,
                session_key=session_key,
                source=source_name,
                facet=facet,
                occurred_at=occurred_at,
                turn_ref=turn_ref,
            )
        return results

    def log_event(
        self,
        *,
        person_key: str,
        kind: str,
        quote: str,
        summary: str = "",
        session_key: str = "",
        source: str = SOURCE_SELF_REPORT,
        facet: str = "",
        sensitivity: str = "personal",
        occurred_at: datetime | str | None = None,
        turn_ref: str = "",
    ) -> SpeechEvent | None:
        """言行账落一行。硬红线⇒不落（返回 None）；同句重复⇒只推时刻，不新造行。"""
        key = str(person_key or "").strip()
        if not key or not self.available:
            return None
        clean_quote = sanitize_profile_text(quote, limit=_QUOTE_MAX_CHARS)
        if clean_quote is None:
            self._refuse_audit(key, facet=facet, raw=quote, source=source)
            return None
        clean_summary = sanitize_profile_text(summary, limit=_QUOTE_MAX_CHARS) or ""
        if not clean_quote and not clean_summary:
            return None
        kind_name = str(kind or "").strip().casefold()
        if kind_name not in EVENT_KINDS:
            kind_name = EVENT_SAID
        source_name = str(source or "").strip().casefold()
        if source_name not in PROFILE_SOURCES:
            source_name = SOURCE_SELF_REPORT
        if source_name in _AUTO_SOURCES and sensitive_category_of(clean_quote or clean_summary):
            self._refuse_audit(key, facet=facet, raw=clean_quote, source=source_name)
            return None
        sensitivity_name = "credentialed" if sensitive_category_of(clean_quote or clean_summary) else str(
            sensitivity or "personal"
        ).strip().casefold()
        if sensitivity_name not in MEMORY_SENSITIVITIES:
            sensitivity_name = "personal"
        stamp = _iso(_now())
        moment = _resolve_moment(occurred_at) or stamp
        value_key = canonical_fact_text(clean_quote or clean_summary)
        with self._lock, self._connect() as connection:
            if value_key and self._is_tombstoned(connection, key, "", clean_quote or clean_summary):
                self._audit(connection, person_key=key, action="refused", facet=facet,
                            value=clean_quote, detail="revoked_before")
                return None
            # 同一句再说一次＝刷新时刻，不新造行（言行账要的是「她说过几次」里
            # 最新那一次的可引用形态，重复行会把预算吃光）。
            candidates = connection.execute(
                f"SELECT event_id, quote, summary, happened_at FROM {PERSON_EVENT_TABLE}"
                " WHERE person_key=? AND kind=? ORDER BY recorded_at DESC LIMIT 60",
                (key, kind_name),
            ).fetchall()
            for row in candidates:
                if value_key and canonical_fact_text(f"{row['quote']}{row['summary']}") == value_key:
                    stored_moment = str(row["happened_at"] or "") or moment
                    connection.execute(
                        f"UPDATE {PERSON_EVENT_TABLE} SET recorded_at=?, happened_at=?,"
                        " session_key=CASE WHEN session_key='' THEN ? ELSE session_key END"
                        " WHERE event_id=?",
                        (stamp, stored_moment, _clip(str(session_key or ""), 80), str(row["event_id"])),
                    )
                    return SpeechEvent(
                        event_id=str(row["event_id"]), person_key=key, kind=kind_name,
                        quote=clean_quote, summary=clean_summary, source=source_name,
                        sensitivity=sensitivity_name, happened_at=stored_moment, recorded_at=stamp,
                        session_key=str(session_key or ""), facet=facet, turn_ref=turn_ref,
                    )
            event_id = f"ev_{_fingerprint(f'{key}{kind_name}{value_key}{stamp}')}"
            connection.execute(
                f"INSERT INTO {PERSON_EVENT_TABLE}"
                " (event_id, person_key, kind, quote, summary, facet, source, sensitivity,"
                " happened_at, recorded_at, session_key, turn_ref)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id, key, kind_name, clean_quote, clean_summary, facet, source_name,
                    sensitivity_name, moment, stamp, _clip(str(session_key or ""), 80),
                    _clip(str(turn_ref or ""), 80),
                ),
            )
            self._audit(connection, person_key=key, action="recorded", facet=facet,
                        value=clean_quote or clean_summary, detail=f"event:{kind_name}")
        return SpeechEvent(
            event_id=event_id, person_key=key, kind=kind_name, quote=clean_quote,
            summary=clean_summary, source=source_name, sensitivity=sensitivity_name,
            happened_at=moment, recorded_at=stamp, session_key=str(session_key or ""),
            facet=facet, turn_ref=turn_ref,
        )

    # -- 读 ---------------------------------------------------------------

    def facets(
        self,
        person_key: str,
        *,
        facets: Sequence[str] | None = None,
        include_credentialed: bool = False,
    ) -> list[FacetRecord]:
        key = str(person_key or "").strip()
        if not key or not self.available:
            return []
        wanted = {str(item).strip().casefold() for item in facets or () if str(item or "").strip()}
        placeholders = ",".join("?" for _ in wanted)
        sql = (
            f"SELECT record_id, person_key, facet, value, value_key, source, confidence, sensitivity,"
            f" status, confirm_count, evidence, session_key, created_at, updated_at"
            f" FROM {PERSON_FACET_TABLE} WHERE person_key=? AND status=?"
        )
        args: list[Any] = [key, _STATUS_ACTIVE]
        if wanted:
            sql += f" AND facet IN ({placeholders})"
            args.extend(sorted(wanted))
        sql += " ORDER BY updated_at DESC, record_id DESC"
        try:
            with self._connect() as connection:
                rows = connection.execute(sql, args).fetchall()
        except Exception as exc:  # noqa: BLE001 - 读不出就当没记住，不谎报
            logger.warning("profile facets read failed type=%s", type(exc).__name__)
            return []
        records = [_facet_from_row(row) for row in rows]
        if not include_credentialed:
            records = [item for item in records if item.sensitivity not in NON_INJECTABLE_SENSITIVITIES]
        return records

    def events(
        self,
        person_key: str,
        *,
        limit: int = 40,
        include_credentialed: bool = False,
    ) -> list[SpeechEvent]:
        key = str(person_key or "").strip()
        if not key or not self.available:
            return []
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT event_id, person_key, kind, quote, summary, facet, source, sensitivity,"
                    f" happened_at, recorded_at, session_key, turn_ref"
                    f" FROM {PERSON_EVENT_TABLE} WHERE person_key=?"
                    " ORDER BY happened_at DESC, recorded_at DESC LIMIT ?",
                    (key, max(1, int(limit))),
                ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("profile events read failed type=%s", type(exc).__name__)
            return []
        found = [_event_from_row(row) for row in rows]
        if not include_credentialed:
            found = [item for item in found if item.sensitivity not in NON_INJECTABLE_SENSITIVITIES]
        return found

    def search_events(
        self,
        *,
        person_key: str,
        query: str = "",
        limit: int = 5,
        requester_key: str | None = None,
    ) -> list[SpeechEvent]:
        """按当前话题取言行（无查询⇒最近几条；越权请求⇒空）。"""
        key = str(person_key or "").strip()
        if requester_key is not None and str(requester_key or "").strip() != key:
            return []
        pool = self.events(key, limit=80)
        if not pool:
            return []
        needle = canonical_fact_text(query)
        if not needle:
            return pool[: max(1, int(limit))]
        query_tokens = fact_signature(query).tokens
        scored: list[tuple[float, int, SpeechEvent]] = []
        for index, event in enumerate(pool):
            body = f"{event.quote}{event.summary}"
            if needle and needle in canonical_fact_text(body):
                scored.append((2.0, -index, event))
                continue
            overlap = len(query_tokens & fact_signature(body).tokens)
            if overlap:
                scored.append((overlap / max(1, min(len(query_tokens), 1) + len(fact_signature(body).tokens) // 3), -index, event))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[: max(1, int(limit))]]

    def audit_rows(self, person_key: str, *, limit: int = 50) -> list[dict[str, Any]]:
        key = str(person_key or "").strip()
        if not key or not self.available:
            return []
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT audit_id, person_key, action, facet, value_hash, detail, actor_key, created_at"
                    f" FROM {PERSON_AUDIT_TABLE} WHERE person_key=? ORDER BY created_at DESC LIMIT ?",
                    (key, max(1, int(limit))),
                ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("profile audit read failed type=%s", type(exc).__name__)
            return []
        return [dict(row) for row in rows]

    # -- 撤销（真删 + 审计 + 不复活）--------------------------------------

    def revoke(
        self,
        *,
        person_key: str,
        actor_key: str,
        target: str = "",
        privileged: bool = False,
    ) -> RevokeResult:
        """「别记这个」⇒内容行硬 DELETE、写墓碑、审计留指纹。删不掉就说删不掉。

        ``target`` 三态：``*``＝这个人的一切；字段名（如 ``nickname``）＝整格；
        其余＝按值匹配（画像与言行一起找）。归属门：非本人且非受权⇒一条不动。
        """
        key = str(person_key or "").strip()
        actor = str(actor_key or "").strip()
        needle_all = str(target or "").strip()
        if not key:
            return RevokeResult(reason="no_person")
        if not self.available:
            return RevokeResult(reason="store_unavailable")
        if not privileged and actor != key:
            return RevokeResult(reason="not_owner")
        if not needle_all:
            return RevokeResult(reason="empty_target")
        wipe_all = needle_all == REVOKE_ALL
        facet_target = needle_all.casefold()
        is_facet = (not wipe_all) and facet_target in PROFILE_FACETS
        needle = "" if (wipe_all or is_facet) else canonical_fact_text(needle_all)
        removed = 0
        touched: list[str] = []
        deleted_values: list[str] = []
        with self._lock, self._connect() as connection:
            if wipe_all:
                facet_rows = connection.execute(
                    f"SELECT record_id, facet, value, value_key FROM {PERSON_FACET_TABLE}"
                    " WHERE person_key=?",
                    (key,),
                ).fetchall()
            elif is_facet:
                facet_rows = connection.execute(
                    f"SELECT record_id, facet, value, value_key FROM {PERSON_FACET_TABLE}"
                    " WHERE person_key=? AND facet=?",
                    (key, facet_target),
                ).fetchall()
            else:
                facet_rows = connection.execute(
                    f"SELECT record_id, facet, value, value_key FROM {PERSON_FACET_TABLE}"
                    " WHERE person_key=? AND status=?",
                    (key, _STATUS_ACTIVE),
                ).fetchall()
                facet_rows = [row for row in facet_rows if needle and needle in str(row["value_key"])]
            for row in facet_rows:
                record_id = str(row["record_id"] or "")
                value = str(row["value"] or "")
                facet_name = str(row["facet"] or "")
                connection.execute(f"DELETE FROM {PERSON_FACET_TABLE} WHERE record_id=?", (record_id,))
                connection.execute(
                    f"INSERT OR REPLACE INTO {PERSON_TOMBSTONE_TABLE}"
                    " (person_key, facet, value_hash, revoked_at) VALUES (?, ?, ?, ?)",
                    (key, facet_name, _fingerprint(value), _iso(_now())),
                )
                self._audit(
                    connection, person_key=key, action="revoked", facet=facet_name,
                    value=value, actor_key=actor, detail=f"record_id={record_id}",
                )
                removed += 1
                touched.append(facet_name)
                deleted_values.append(value)
            if is_facet:
                connection.execute(
                    f"INSERT OR REPLACE INTO {PERSON_TOMBSTONE_TABLE}"
                    " (person_key, facet, value_hash, revoked_at) VALUES (?, ?, ?, ?)",
                    (key, facet_target, _fingerprint(f"facet:{facet_target}"), _iso(_now())),
                )
            for row in connection.execute(
                f"SELECT event_id, quote, summary, facet FROM {PERSON_EVENT_TABLE}"
                " WHERE person_key=?",
                (key,),
            ).fetchall():
                body = f"{row['quote'] or ''}{row['summary'] or ''}"
                body_key = canonical_fact_text(body)
                if wipe_all:
                    matched = True
                elif is_facet:
                    matched = str(row["facet"] or "") == facet_target or any(
                        value and canonical_fact_text(value) in body_key for value in deleted_values
                    )
                else:
                    matched = bool(needle) and needle in body_key
                if not matched:
                    continue
                connection.execute(
                    f"DELETE FROM {PERSON_EVENT_TABLE} WHERE event_id=?", (str(row["event_id"]),)
                )
                connection.execute(
                    f"INSERT OR REPLACE INTO {PERSON_TOMBSTONE_TABLE}"
                    " (person_key, facet, value_hash, revoked_at) VALUES (?, '', ?, ?)",
                    (key, _fingerprint(body), _iso(_now())),
                )
                self._audit(
                    connection, person_key=key, action="revoked", facet=str(row["facet"] or ""),
                    value=body, actor_key=actor, detail=f"event_id={row['event_id']}",
                )
                removed += 1
        if removed == 0:
            return RevokeResult(reason="not_found")
        return RevokeResult(removed=removed, facets=tuple(item for item in touched if item))

    # -- 注入面（分区文本；空⇒空串）--------------------------------------

    def render_profile(
        self,
        person_key: str = "",
        requester_key: str = "",
        session_key: str = "",
        *,
        query_text: str = "",
        max_items: int = _DEFAULT_MAX_ITEMS,
        max_chars: int = _DEFAULT_MAX_CHARS,
    ) -> str:
        """把「我关于这个人记得什么」渲染成一段可注入的分区文本。

        归属门在这里，不在调用方：``requester_key`` 必须逐字等于 ``person_key``
        （群聊里问别人⇒空串），否则一条都不给。空 ⇒ 空串（空分区不渲染）。
        """
        key = str(person_key or "").strip()
        requester = str(requester_key or "").strip()
        if not key or not self.available or not requester or requester != key:
            return ""
        records = self.facets(key)[: max(1, int(max_items))]
        events = self.search_events(person_key=key, query=query_text, limit=max_items)
        if not records and not events:
            return ""
        lines = [
            "关于你（这些是我自己记下来的，可能过时；只在你面前说，不转述给别人）：",
        ]
        for record in records:
            origin = _origin_label(record.session_key)
            date = _date_label(record.updated_at)
            tail = f"（{record.provenance_phrase}，{date}{origin}）" if date or origin else ""
            lines.append(f"- {record.label}：{record.value}{tail}")
        if events:
            lines.append("你交代过、我留着的话：")
            for event in events:
                date = _date_label(event.happened_at)
                origin = _origin_label(event.session_key)
                where = " ".join(item for item in (date, origin) if item)
                body = event.quote or event.summary
                lines.append(f"- {where} {event.provenance_phrase}「{body}」〔{event.event_id}〕")
        lines.append("标了「我印象里」的都是我自己推的，别当你的原话讲；哪条不对，说一声我就改掉。")
        return _budget(lines, max_chars)


def _budget(lines: list[str], max_chars: int) -> str:
    """预算裁剪：从尾部丢行，并**如实**点名丢了几条（静默截断＝谎报）。"""
    budget = max(40, int(max_chars))
    if sum(len(item) + 1 for item in lines) <= budget:
        return "\n".join(lines)
    dropped = 0
    kept = list(lines)
    while kept and sum(len(item) + 1 for item in kept) + len(f"（另有 {dropped + 1} 条没列出）") > budget:
        if len(kept) <= 1:
            break
        kept.pop()
        dropped += 1
    if dropped:
        kept.append(f"（另有 {dropped} 条没列出）")
    return "\n".join(kept)


def _origin_label(session_key: str) -> str:
    key = str(session_key or "").strip()
    if not key:
        return ""
    return "群里" if is_group_session_key(key) else "私聊里"


def _looks_like_iso(value: str) -> bool:
    return bool(value) and value[4:5] == "-"


def _resolve_moment(value: datetime | str | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return _iso(value)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:32]
    return _iso(parsed)


def _date_label(value: str) -> str:
    """落盘 ISO（带偏移）→ 人读日期；解析不出来就取前 10 个字符，再不行⇒空。"""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return text[:10] if _looks_like_iso(text) else ""


def _facet_from_row(row: sqlite3.Row) -> FacetRecord:
    return FacetRecord(
        record_id=str(row["record_id"]),
        person_key=str(row["person_key"]),
        facet=str(row["facet"]),
        value=str(row["value"]),
        source=str(row["source"]),
        confidence=float(row["confidence"] or 0.0),
        sensitivity=str(row["sensitivity"] or "personal"),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        confirm_count=int(row["confirm_count"] or 1),
        evidence=str(row["evidence"] or ""),
        session_key=str(row["session_key"] or ""),
    )


def _event_from_row(row: sqlite3.Row) -> SpeechEvent:
    return SpeechEvent(
        event_id=str(row["event_id"]),
        person_key=str(row["person_key"]),
        kind=str(row["kind"]),
        quote=str(row["quote"] or ""),
        summary=str(row["summary"] or ""),
        source=str(row["source"] or ""),
        sensitivity=str(row["sensitivity"] or "personal"),
        happened_at=str(row["happened_at"] or ""),
        recorded_at=str(row["recorded_at"] or ""),
        session_key=str(row["session_key"] or ""),
        facet=str(row["facet"] or ""),
        turn_ref=str(row["turn_ref"] or ""),
    )


# ---------------------------------------------------------------------------
# 装配（开关只在装配层判；存储自身不读配置，同 memory.py 的家规）
# ---------------------------------------------------------------------------

_STORES_LOCK = threading.Lock()
_STORES: dict[str, PersonProfileStore] = {}

#: 画像总门（config 键名；``getattr`` 兜底 False＝没这个字段时整链关）。
PROFILE_ENABLED_ATTR = "bot_person_profile_enabled"
PROFILE_MAX_CHARS_ATTR = "bot_person_profile_max_chars"
PROFILE_MAX_ITEMS_ATTR = "bot_person_profile_max_items"


def build_person_profile_store(config: object) -> PersonProfileStore | None:
    """进程级共享 store（懒建；门没开/没配路径/建库失败⇒None，调用方按 None 走空）。"""
    if not bool(getattr(config, PROFILE_ENABLED_ATTR, False)):
        return None
    db_path = str(getattr(config, "bot_memory_db_path", "") or "").strip()
    if not db_path:
        return None
    with _STORES_LOCK:
        store = _STORES.get(db_path)
        if store is None:
            # ``Any``：装配层的构造口可以被换掉（测试注入桩件），这里只认「有没有」。
            # 构造入参显式 ``Path``：字段声明就是 ``path: Path``（``__post_init__``
            # 虽宽容，但类型面不宽容），传 str 会让 mypy 判不兼容——在**调用侧**收形，
            # 不把 dataclass 的字段类型放宽成 ``str | Path``（那是放宽契约）。
            built: Any = PersonProfileStore(Path(db_path))
            if built is None or not getattr(built, "available", False):
                return None
            _STORES[db_path] = built
            return built
        return store


def compose_person_profile_context(
    config: object,
    *,
    requester_id: str,
    subject_user_id: str,
    session_id: str = "",
    query_text: str = "",
    platform_domain: str = "",
    max_items: int | None = None,
    max_chars: int | None = None,
) -> str:
    """对话前的画像召回出口：给不出就诚实给空串，绝不编造记忆。"""
    if not bool(getattr(config, PROFILE_ENABLED_ATTR, False)):
        return ""
    subject = person_profile_key(subject_user_id, platform_domain)
    requester = person_profile_key(requester_id, platform_domain)
    if not subject or requester != subject:
        return ""
    store = build_person_profile_store(config)
    if store is None:
        return ""
    try:
        return store.render_profile(
            person_key=subject,
            requester_key=requester,
            session_key=session_id,
            query_text=query_text,
            max_items=int(max_items or getattr(config, PROFILE_MAX_ITEMS_ATTR, _DEFAULT_MAX_ITEMS) or _DEFAULT_MAX_ITEMS),
            max_chars=int(max_chars or getattr(config, PROFILE_MAX_CHARS_ATTR, _DEFAULT_MAX_CHARS) or _DEFAULT_MAX_CHARS),
        )
    except Exception as exc:  # noqa: BLE001 - 画像读不出就本轮没画像，不许炸对话
        logger.warning("person profile render failed type=%s", type(exc).__name__)
        return ""


def observe_conversation_message(
    config: object,
    *,
    sender_id: str,
    session_id: str,
    user_text: str,
    platform_domain: str = "",
    occurred_at: datetime | str | None = None,
    turn_ref: str = "",
    source: str = SOURCE_SELF_REPORT,
) -> list[RecordResult]:
    """本人消息的确定性沉淀口（不需要 LLM，抽取腿开关也压得住）。

    写入口一共两个（禁第三个）：**本人亲口**这一路走本函数（命令面「记住」腿、
    以及将来的摄取直落）；**模型转述**那一路线走
    :func:`settle_extracted_facts`（后台抽取腿 ``memory_extract.store_extracted_memories``
    唯一委托它，不在那边自己推字段）。开关关⇒零副作用（``build_person_profile_store``
    先判门再建库）。
    """
    store = build_person_profile_store(config)
    if store is None or not bool(getattr(config, PROFILE_ENABLED_ATTR, False)):
        return []
    key = person_profile_key(sender_id, platform_domain)
    if not key:
        return []
    return store.observe_self_report(
        person_key=key, text=user_text, session_key=session_id,
        source=source, occurred_at=occurred_at, turn_ref=turn_ref,
    )


def settle_extracted_facts(
    store: PersonProfileStore | None,
    *,
    person_key: str,
    session_key: str,
    facts: Sequence[str],
    original_user_text: str = "",
    turn_ref: str = "",
) -> list[RecordResult]:
    """后台抽取腿的画像沉淀口（**唯一**一处；``memory_extract`` 只准委托这里，禁自推字段）。

    两条来源分开记账，这是本件与「按人策略」之外最容易记脏的一刀：

    * ``facts`` 是**模型转述**⇒ ``derived`` 档，只进画像字段（注入面因此自带
      「我印象里」口吻，绝不冒充本人原话）；
    * ``original_user_text`` 是**她的原话**⇒ 只进行为账（``log_event``），
      **不**再推一遍字段。原因现算过：``_derive_facet`` 的极性吃的是整句，
      「我喜欢柠檬茶，别记错了」会被判成 ``dislike``——抽取腿拿到的原话本来就
      带着「别记错了」这种对本轮的编辑，把它再推一次字段＝把噪声焊进画像。
      原话的价值只有「她哪天在哪说过什么」，那一格言行账已经够了。

    开关关⇒``store`` 为 ``None``（``build_person_profile_store`` 先判门再建库），
    本函数零副作用、零建库。落库失败一律由调用方兜住，不在这层吞。
    """
    key = str(person_key or "").strip()
    if store is None or not key or not bool(getattr(store, "available", False)):
        return []
    results: list[RecordResult] = []
    for fact in facts:
        body = str(fact or "").strip()
        if not body:
            continue
        results.extend(
            store.observe_self_report(
                person_key=key, text=body, session_key=session_key,
                source=SOURCE_DERIVED, turn_ref=turn_ref,
            )
        )
    quote = str(original_user_text or "").strip()
    if quote:
        # 消毒／红线／墓碑判据全在 store.log_event 内部那一道咽喉里，本层不预清洗
        # （预清洗＝第二把尺，且会把「拒收也要留账」那条出口绕过去）。
        store.log_event(
            person_key=key,
            kind=_event_kind_for(classify_fact_category(quote), SOURCE_SELF_REPORT),
            quote=quote,
            session_key=session_key,
            source=SOURCE_SELF_REPORT,
            turn_ref=turn_ref,
        )
    return results


# ---------------------------------------------------------------------------
# 命令面（「说出来、指出来、忘掉它」）——本体只出文本，包装由命令腿负责
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProfileCommandOutcome:
    body: str
    ok: bool = True
    tags: tuple[str, ...] = ()


_PROFILE_COMMAND_ALIASES: dict[str, str] = {
    "memory profile": "profile",
    "profile": "profile",
    "画像": "profile",
    "记忆画像": "profile",
    "你记得我什么": "profile",
    "memory forget": "forget",
    "forget": "forget",
    "忘掉": "forget",
    "别记这个": "forget",
    "memory remember": "remember",
    "remember": "remember",
    "记住": "remember",
    "memory events": "events",
    "events": "events",
    "说过": "events",
    "你说过": "events",
}


def _split_profile_command(text: str) -> tuple[str, str]:
    """命令文本 → ``(动作, 参数)``；两种语序都认（``memory forget X`` 与 ``忘掉X``）。"""
    raw = (text or "").strip()
    folded = raw.casefold()
    if not folded:
        return "", ""
    for alias in sorted(_PROFILE_COMMAND_ALIASES, key=len, reverse=True):
        if folded.startswith(alias):
            return _PROFILE_COMMAND_ALIASES[alias], raw[len(alias):].strip(" :：=，,")
    return "", ""


def _facet_hint() -> str:
    return "、".join(f"{FACET_DISPLAY_ZH[name]}（{name}）" for name in sorted(PROFILE_FACETS))


def _resolve_facet_target(token: str) -> str:
    """字段标签（中文人读名，如「称呼」）→ 英文字段名（``nickname``）；认不出⇒原样返回。

    记住／忘掉两条腿共用这**唯一一处**解析，杜绝「记住落 '称呼'、忘掉按 'nickname'」
    这种读写各拿一把键、永不相交的老坑（台账 #33★ 会话键同族）。
    """
    body = str(token or "").strip()
    for name, label in FACET_DISPLAY_ZH.items():
        if body == label:
            return name
    return body


def handle_profile_command(
    config: object,
    *,
    command_text: str,
    sender_id: str,
    session_id: str = "",
    platform_domain: str = "",
) -> ProfileCommandOutcome:
    """画像命令面的真身（``capabilities/memory.py`` 只准委托这一处，禁第二通路）。

    永远只对**本人**生效：命令面拿的是发起人自己的号，键由中央构造器算，
    所以「替别人查画像」在这里根本没有入口（不是靠判据挡住，是结构上没有）。
    """
    action, argument = _split_profile_command(command_text)
    if not action:
        return ProfileCommandOutcome(
            body="画像这几格我能查：记忆画像／记住 字段=内容／忘掉 <内容或字段>／说过 <关键词>。可用字段："
            + _facet_hint(),
            ok=False,
            tags=("profile_usage",),
        )
    store = build_person_profile_store(config)
    if store is None:
        return ProfileCommandOutcome(
            body="画像这条线还没开：要让管理员在 .env 里设 BOT_PERSON_PROFILE_ENABLED=true，"
                 "并配好记忆库路径（BOT_MEMORY_DB_PATH），重启后才生效。现在我只能走旧那套记忆。",
            ok=False,
            tags=("profile_disabled",),
        )
    person = person_profile_key(sender_id, platform_domain)
    if not person:
        return ProfileCommandOutcome(
            body="没带上你的身份号，我不敢替谁记，也不敢替谁删。", ok=False, tags=("no_identity",)
        )
    if action == "profile":
        records = store.facets(person)[:12]
        if not records:
            return ProfileCommandOutcome(
                body="关于你，我这儿还是空的。你愿意说，我就记；说了不要的，我删。",
                tags=("profile_empty",),
            )
        lines = ["我记下的你："]
        for record in records:
            origin = _origin_label(record.session_key)
            date = _date_label(record.updated_at)
            tail = "，".join(item for item in (date, origin) if item)
            lines.append(
                f"- {record.label}：{record.value}（{record.provenance_phrase}"
                + (f"，{tail}" if tail else "")
                + f"）〔{record.record_id}〕"
            )
        lines.append("哪条不对，跟我说「忘掉 <那格或那一句>」，我就真删掉，不是打个包藏起来。")
        return ProfileCommandOutcome(body="\n".join(lines), tags=("profile_ok",))
    if action == "forget":
        if not argument:
            return ProfileCommandOutcome(
                body="要忘哪一条？说内容、说字段名（比如「称呼」），或者干脆说「忘掉全部」。",
                ok=False,
                tags=("profile_need_target",),
            )
        target = _resolve_facet_target(argument)
        if target in {"全部", "所有", "一切"}:
            target = REVOKE_ALL
        result = store.revoke(person_key=person, actor_key=person, target=target)
        if result.removed:
            return ProfileCommandOutcome(
                body=f"忘掉了 {result.removed} 条。这条以后不会再被我想起来——"
                     "真要重新记，得你亲口再说一次。",
                tags=("profile_revoked", str(result.removed)),
            )
        if result.reason == "not_found":
            return ProfileCommandOutcome(
                body="没找到这条，所以我什么都没动。", tags=("profile_not_found",)
            )
        return ProfileCommandOutcome(
            body=f"这条我没删掉（原因：{result.reason or 'unknown'}）。",
            ok=False,
            tags=("profile_revoke_failed", result.reason or "unknown"),
        )
    if action == "remember":
        if "=" not in argument and "＝" not in argument:
            return ProfileCommandOutcome(
                body="这样写：记住 称呼=小红。左边是字段，右边是内容。可用字段：" + _facet_hint(),
                ok=False,
                tags=("profile_need_pair",),
            )
        facet_name, _, value = argument.replace("＝", "=").partition("=")
        outcome = store.record(
            person_key=person,
            facet=_resolve_facet_target(facet_name).casefold(),
            value=value.strip(),
            source=SOURCE_EXPLICIT_COMMAND,
            session_key=session_id,
        )
        if outcome.action == "refused":
            if outcome.reason == "hard_line":
                return ProfileCommandOutcome(
                    body="这条我碰不得，不记。", tags=("profile_refused", "hard_line")
                )
            if outcome.reason == "unknown_facet":
                return ProfileCommandOutcome(
                    body=f"没有「{facet_name.strip()}」这一格。可用字段：" + _facet_hint(),
                    ok=False,
                    tags=("profile_unknown_facet",),
                )
            return ProfileCommandOutcome(
                body=f"这条没记进去（{outcome.reason}）。", ok=False,
                tags=("profile_refused", outcome.reason or "unknown")
            )
        label = FACET_DISPLAY_ZH.get(outcome.facet, outcome.facet)
        said = "改过来了" if outcome.action == "overridden" else "记下了"
        return ProfileCommandOutcome(
            body=f"{label}{said}：{value.strip()}。",
            tags=("profile_recorded", outcome.action, outcome.record_id),
        )
    hits = store.search_events(person_key=person, query=argument, limit=5)
    if not hits:
        return ProfileCommandOutcome(
            body="这回没检索到相关的，我不拿猜的补。", tags=("profile_events_miss",)
        )
    lines = [f"你说过、我留着的（{len(hits)} 条）："]
    lines.extend(
        f"- {_date_label(item.happened_at)} {_origin_label(item.session_key)}"
        f" {item.provenance_phrase}「{item.quote or item.summary}」〔{item.event_id}〕"
        for item in hits
    )
    return ProfileCommandOutcome(body="\n".join(lines), tags=("profile_events_ok", str(len(hits))))


__all__ = [
    "EVENT_COMMITTED",
    "EVENT_DID",
    "EVENT_KINDS",
    "EVENT_REQUESTED",
    "EVENT_SAID",
    "FACET_DISPLAY_ZH",
    "MULTI_VALUE_FACETS",
    "NON_INJECTABLE_SENSITIVITIES",
    "PERSON_AUDIT_TABLE",
    "PERSON_EVENT_TABLE",
    "PERSON_FACET_TABLE",
    "PROFILE_FACETS",
    "PROFILE_SOURCES",
    "REVOKE_ALL",
    "SINGLE_VALUE_FACETS",
    "SOURCE_DERIVED",
    "SOURCE_EXPLICIT_COMMAND",
    "SOURCE_REFLECTED",
    "SOURCE_SELF_REPORT",
    "FacetRecord",
    "PersonProfileStore",
    "ProfileCommandOutcome",
    "RecordResult",
    "RevokeResult",
    "SpeechEvent",
    "build_person_profile_store",
    "compose_person_profile_context",
    "observe_conversation_message",
    "person_profile_key",
    "sanitize_profile_text",
    "sensitive_category_of",
    "settle_extracted_facts",
]

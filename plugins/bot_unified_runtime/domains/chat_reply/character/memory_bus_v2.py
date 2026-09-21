"""记忆总线 v2（WP6，规格 `docs/design/memory-reflection-v2-design.md`）。

为什么要有这一件（现状三条病，逐条对应本件的一个机制）：

1. **两套并行存储互相矛盾时无人裁决**——显式事实与夜间归纳各写各的表，
   只在召回出口用 fact_id 拼一下。本件把它们收进**同一张表**
   （``memory_entries_v21`` + v2 列），归纳侧降级为**写侧归纳器**：它不再
   拥有存储，只负责把候选事实投进 ``absorb``。
2. **可见性写在字符串里**（``''``/``'*'``/``'global'``/``platform:`` 前缀混用），
   读侧绑裸 session_id、写侧存 ``platform:session_id`` ⇒ 反思链恒召回 0。
   本件把可见性升成**列**（``scope_kind`` + ``scope_key``），形状唯一由中央件
   ``domains/core/session_keys.parse_session_key`` 派生，平台维度留在
   ``owner_id``（``MemoryPrincipal.owner_id`` 本来就带平台前缀）。跨会话召回到
   非 global 行，在 SQL 层**结构上取不到**（不是靠字符串碰运气）。
3. **取信判据只有 confidence + 时间序，query_text 收了不用**——说过 20 次和
   说过 1 次同权，不相关的老事实照塞。本件按「证据累积」记账
   （``confirm_count``/``contradict_count``/``supersedes``/``decay_class``），
   召回打分 ``w_rel·relevance + w_str·strength + w_rec·recency − w_red·redundancy``
   并做同簇上限（MMR-lite），每次注入落一行审计，``/bot why`` 可解释。

关键语义区分（v1 把它吞进了 keep-newest）：**「又说起」≠「改了主意」**。
同一槽位同极性 ⇒ 确认（计数+1，强度饱和上升）；同一槽位反极性 ⇒ 矛盾
（双行并存 + ``supersedes`` 留痕 + 双方降权，高确认次数一方在召回面上胜出）。

红线（本件自锁，见 ``tests/test_memory_bus_v2.py``）：
- ``credentialed`` 敏感级永不进召回面；``requester != subject`` 直接零结果；
- 非 global 行只在**同一 canonical 作用域键**下可见，缺作用域=只给 global
  （v1 是「忘了传就是全会话」的 fail-open，这里翻成 fail-closed）；
- 用户显式删除=真删 + 墓碑，且 ``source_event_id`` 幂等探针让「迁移/重跑」
  都无法复活已删事实；
- 沉淀面复用 ``security/memory_sanitize`` 的单一词表来源（六硬线 + minors，
  fail-closed）——本件**不另建第二套清洗词表**；该来源不可用时退回今日行为
  （不清洗）并点名一次，绝不静默换成另一套判据；
- 显式来源永远压过归纳来源（归纳不得作废 explicit 行）。
"""

from __future__ import annotations

import json
import logging
import math
import re
import secrets
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    MemoryRetrievalResult,
    PrivacyLevel,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_store_v21 import (
    MemoryStoreV21,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    KIND_GROUP,
    parse_session_key,
)

logger = logging.getLogger(__name__)

# ---- 词表（来源：设计稿 §三/§四；全部可由配置调，见 BusSettings）----

PROVENANCE_EXPLICIT = "explicit"
PROVENANCE_REFLECTED = "reflected"
PROVENANCE_DERIVED = "derived"

# 来源可靠度：置信度封顶 + 强度乘子。显式命令 > 夜间归纳 > 单轮抽取。
_SOURCE_RELIABILITY: dict[str, float] = {
    PROVENANCE_EXPLICIT: 1.0,
    PROVENANCE_REFLECTED: 0.8,
    PROVENANCE_DERIVED: 0.7,
}
_CONFIDENCE_CEILING: dict[str, float] = {
    PROVENANCE_EXPLICIT: 1.0,
    PROVENANCE_REFLECTED: 0.85,
    PROVENANCE_DERIVED: 0.8,
}

SCOPE_GLOBAL = "global"
SCOPE_SESSION = "session"
SCOPE_GROUP_MEMBER = "group_member"

DECAY_STABLE = "stable"
DECAY_SEASONAL = "seasonal"
DECAY_EPISODIC = "episodic"
# 设计稿 §三 的列缺省写的是 'slow'（历史包袱），此处把「未知/缺省」按 stable 处理。
_DECAY_ALIASES: dict[str, str] = {
    "": DECAY_STABLE,
    "slow": DECAY_STABLE,
    "stable": DECAY_STABLE,
    "seasonal": DECAY_SEASONAL,
    "fast": DECAY_EPISODIC,
    "episodic": DECAY_EPISODIC,
}
_CATEGORY_DECAY: dict[str, str] = {
    "identity": DECAY_STABLE,
    "preference": DECAY_STABLE,
    "fact": DECAY_STABLE,
    "activity": DECAY_SEASONAL,
    "plan": DECAY_SEASONAL,
    "event": DECAY_EPISODIC,
}

_KIND_BY_CATEGORY: dict[str, str] = {
    "preference": "preference",
    "identity": "fact",
    "activity": "fact",
    "plan": "event",
    "event": "event",
    "": "fact",
}

# 极性词：先长后短匹配，避免「不喜欢」被「不」抢先吃掉留下歧义文本。拉丁词带词界，
# 否则 "not" 会咬进 "note"、"no " 会咬进 "nothing"（CJK 无词界可寻，按字面命中）。
_CJK_NEGATIONS: tuple[str, ...] = (
    "不喜欢",
    "不爱",
    "不再",
    "不想",
    "不吃",
    "不喝",
    "不要",
    "没有",
    "讨厌",
    "厌恶",
    "反感",
    "不",
    "没",
    "无",
    "别",
)
# 归一化会剥掉撇号（don't→dont），故缩写形态按剥完的样子登记。
_LATIN_NEGATIONS: tuple[str, ...] = (
    "dont",
    "doesnt",
    "cant",
    "cannot",
    "never",
    "dislike",
    "hate",
    "not",
    "no",
)
_NEGATION_PATTERN = re.compile(
    "|".join(
        [re.escape(marker) for marker in _CJK_NEGATIONS]
        + [rf"\b{re.escape(marker)}\b" for marker in _LATIN_NEGATIONS]
    ),
    re.IGNORECASE,
)

# 谓词/程度/填充词受控小词表：槽位键=剥掉这些词之后的残体，剥空则退回全文归一。
# 目的不是语法正确，而是让「我喜欢柠檬茶 / 我超爱柠檬茶 / 我平时爱喝柠檬茶」
# 收敛到同一槽位，从而能被确认、能被矛盾、能在召回时只留一条。
# CJK 段按字面剥（无词界可寻）；拉丁段必须带词界，否则 "i" 会把 fish 剥成 fsh。
_CJK_STOPWORDS: tuple[str, ...] = (
    "我们自己",
    "我",
    "你",
    "本人",
    "自己",
    "现在",
    "以前",
    "从前",
    "平时",
    "通常",
    "一般",
    "最近",
    "这几天",
    "比较",
    "非常",
    "特别",
    "真的",
    "有点",
    "超",
    "很",
    "最",
    "挺",
    "蛮",
    "就是",
    "喜欢",
    "喜爱",
    "偏好",
    "爱好",
    "习惯",
    "爱",
    "喝",
    "吃",
    "用",
    "玩",
    "看",
    "学",
    "做",
    "想",
    "要",
    "打算",
    "计划",
    "是",
    "的",
    "了",
    "过",
    "着",
    "啦",
    "呢",
    "吧",
    "啊",
    "也",
    "还",
    "都",
    "就",
    "在",
)
_LATIN_STOPWORDS: tuple[str, ...] = (
    "like",
    "love",
    "loved",
    "am",
    "is",
    "are",
    "the",
    "a",
    "an",
    "i",
    "my",
    "me",
    "do",
    "did",
    "have",
    "had",
    "has",
    "been",
    "just",
    "really",
    "very",
)
_SLOT_STOPWORD_PATTERN = re.compile(
    "("
    + "|".join(
        [re.escape(word) for word in _CJK_STOPWORDS]
        + [rf"\b{re.escape(word)}\b" for word in _LATIN_STOPWORDS]
    )
    + ")",
    re.IGNORECASE,
)
_PUNCT_PATTERN = re.compile(
    r"[\s，。、！!？?；;：:～~\"'“”‘’（）()【】\[\]{}<>〈〉.…·\-—_,/\\|+*#&%$@^`~]+"
)
_RECALL_RECENCY_HALF_LIFE_DAYS = 30.0
_CONTRADICT_PENALTY_STEP = 0.25
_CONTRADICT_PENALTY_CAP = 0.6
_DUPLICATE_SIMILARITY = 0.62
_NEUTRAL_RELEVANCE_WITHOUT_QUERY = 0.5

_DEFAULT_WEIGHTS: dict[str, float] = {
    "w_rel": 0.45,
    "w_str": 0.35,
    "w_rec": 0.15,
    "w_red": 0.5,
}


def canonical_fact_text(text: str) -> str:
    """事实文本归一形（全仓唯一实现）：去空白与标点 + 小写。

    反思侧的 ``_normalize_fact_text`` 从本件派生（单一来源，禁第二副本）。
    """
    return _PUNCT_PATTERN.sub("", (text or "").strip()).casefold()


@dataclass(frozen=True)
class FactSignature:
    """一条事实的「槽位 + 残体 + 极性 + 词元集」——确认/矛盾/近重复判定的尺子。

    ``slot``（含类别前缀）是**写入侧**的合并键：不同类别的「同一句话」不互相
    作废（我的偏好不该被我的计划确认掉）。``residual``（不含类别）是**召回侧**的
    聚簇键：显式命令与夜间归纳常带不同类别标签，说的是同一件事时必须在预算里
    只占一个名额，所以簇键要比合并键宽一档。
    """

    normalized: str
    slot: str
    residual: str
    polarity: str  # '+' | '-' | ''（无从判定的自由文本）
    tokens: frozenset[str]


def fact_signature(text: str, *, category: str = "") -> FactSignature:
    """把自由文本折成可比较的槽位签名（确定性、零依赖、可在 /bot why 里复述）。

    极性与剥词在**保留空白的折叠原文**上做（拉丁词界需要空白），槽位与词元
    在归一形上做。剥完为空（整句都是谓词）时槽位退回全文归一形——宁可漏合
    一条，也不把两句无关的话并进同一槽位互相判矛盾。
    """
    folded = (text or "").strip().casefold()
    normalized = canonical_fact_text(text)
    if not normalized:
        return FactSignature("", "", "", "", frozenset())
    polarity = "-" if _NEGATION_PATTERN.search(folded) else ""
    destopped = _SLOT_STOPWORD_PATTERN.sub(" ", _NEGATION_PATTERN.sub(" ", folded))
    residual = canonical_fact_text(destopped) or normalized
    return FactSignature(
        normalized=normalized,
        slot=f"{(category or '').strip().casefold()}|{residual}",
        residual=residual,
        polarity=polarity or "+",
        tokens=_token_set(normalized),
    )


def _token_set(normalized: str) -> frozenset[str]:
    """词元集：CJK 二元组 + 拉丁词。用于相关性冗余两处的无依赖相似度。"""
    tokens: set[str] = set()
    latin = re.findall(r"[a-z0-9]+", normalized)
    tokens.update(latin)
    cjk = re.sub(r"[^一-鿿]", " ", normalized)
    for chunk in cjk.split():
        if len(chunk) == 1:
            tokens.add(chunk)
        for index in range(len(chunk) - 1):
            tokens.add(chunk[index : index + 2])
    return frozenset(tokens)


def _similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    return overlap / max(1, min(len(left), len(right)))


# ---- 配置（逐调用现读，本轮不登记 SETTABLE_KEYS=不做热改快照）----


@dataclass(frozen=True)
class BusSettings:
    enabled: bool
    reflected_write_target: str
    strength_k: float
    tau_days: dict[str, float]
    weights: dict[str, float]
    per_slot_max: int
    semantic_recall_enabled: bool

    @property
    def writes_to_bus(self) -> bool:
        return self.reflected_write_target == "bus"


_WEIGHTS_WARNED = False


def settings_from_config(config: object) -> BusSettings:
    """从 Config 现读九键；非法权重 JSON=按代码缺省并点名一次（不静默猜权重）。"""
    global _WEIGHTS_WARNED
    raw_weights = str(getattr(config, "bot_memory_relevance_weights", "") or "").strip()
    weights = dict(_DEFAULT_WEIGHTS)
    if raw_weights:
        try:
            parsed = json.loads(raw_weights)
            if not isinstance(parsed, dict):
                raise TypeError("relevance weights must be a JSON object")
            for key in _DEFAULT_WEIGHTS:
                value = parsed.get(key)
                if value is not None:
                    weights[key] = max(0.0, float(value))
        except (ValueError, TypeError) as exc:
            if not _WEIGHTS_WARNED:
                _WEIGHTS_WARNED = True
                logger.warning(
                    "memory bus relevance weights unusable, falling back to code "
                    "defaults type=%s message=%s",
                    type(exc).__name__,
                    exc,
                )
    return BusSettings(
        enabled=bool(getattr(config, "bot_memory_bus_enabled", False)),
        reflected_write_target=str(
            getattr(config, "bot_memory_reflected_write_target", "legacy") or "legacy"
        )
        .strip()
        .casefold(),
        strength_k=max(0.5, float(getattr(config, "bot_memory_strength_k", 3.0))),
        tau_days={
            DECAY_STABLE: max(1.0, float(getattr(config, "bot_memory_tau_stable_days", 180))),
            DECAY_SEASONAL: max(
                1.0, float(getattr(config, "bot_memory_tau_seasonal_days", 45))
            ),
            DECAY_EPISODIC: max(
                1.0, float(getattr(config, "bot_memory_tau_episodic_days", 14))
            ),
        },
        weights=weights,
        per_slot_max=max(1, int(getattr(config, "bot_memory_per_category_max", 1))),
        semantic_recall_enabled=bool(
            getattr(config, "bot_memory_semantic_recall_enabled", True)
        ),
    )


# ---- 作用域：形状唯一来自中央件 ----


@dataclass(frozen=True)
class FactScope:
    kind: str
    key: str

    @property
    def is_global(self) -> bool:
        return self.kind == SCOPE_GLOBAL


def derive_scope(session_id: Any) -> FactScope:
    """裸会话键 → (scope_kind, scope_key)。

    判据全部走 ``parse_session_key``（中央件），本函数不做任何 startswith/in 猜测：
    - 群键（``group_<gid>_<uid>``）→ ``group_member``，键取中央件归一形；
    - 私聊键 → ``session``；
    - 空/脏键 → ``global`` 作用域**不可写**（返回 key=''，写侧据此拒收），
      读侧只放行 global 行——这是 fail-closed 的一侧。
    """
    parsed = parse_session_key(session_id)
    normalized = parsed.normalized
    if not normalized:
        return FactScope(SCOPE_GLOBAL, "")
    if parsed.kind == KIND_GROUP and parsed.user_id:
        return FactScope(SCOPE_GROUP_MEMBER, normalized)
    return FactScope(SCOPE_SESSION, normalized)


# ---- 观测面数据结构 ----


@dataclass(frozen=True)
class AbsorbOutcome:
    action: str  # confirmed | contradicted | inserted | duplicate_skipped | rejected
    memory_id: str
    confirm_count: int = 0
    contradict_count: int = 0
    superseded_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ScoredFact:
    fact_id: str
    text: str
    kind: str
    sensitivity: str
    scope_key: str
    scope_kind: str
    provenance: str
    score: float
    relevance: float
    strength: float
    recency: float
    redundancy: float
    confirm_count: int
    contradict_count: int


@dataclass(frozen=True)
class DroppedFact:
    fact_id: str
    text: str
    reason: str


@dataclass(frozen=True)
class RecallOutcome:
    request_id: str
    items: list[ScoredFact] = field(default_factory=list)
    dropped: list[DroppedFact] = field(default_factory=list)
    candidates: int = 0
    semantic_available: bool = False
    scope_key: str = ""
    rendered: str = ""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="microseconds")


def _parse_time(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age_days(moment: datetime | None, now: datetime) -> float:
    if moment is None:
        # 没时间戳的存量行按「很久以前」处理：不因缺证据而白拿新近度加分。
        return 3650.0
    return max(0.0, (now - moment).total_seconds()) / 86400.0


_BUS_STORE_LOCK = threading.Lock()
_BUS_STORES: dict[str, MemoryStoreV21] = {}


def shared_bus_store(db_path: str) -> MemoryStoreV21:
    """同一路径单一连接（store 自带 RLock，跨线程共用一把锁才有意义）。"""
    key = str(db_path)
    with _BUS_STORE_LOCK:
        store = _BUS_STORES.get(key)
        if store is None:
            store = MemoryStoreV21(key)
            _BUS_STORES[key] = store
        return store


def _sanitize_violation(text: str) -> str | None:
    """沉淀面清洗：复用 ``memory_sanitize`` 的单一词表来源（六硬线 + minors）。

    不可用（导入/调用失败）时返回 None=维持今日实况（不清洗），并点名一次——
    绝不在此另建第二套词表，也绝不因此放宽既有清洗面。
    """
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.security.memory_sanitize import (
            _match_category,
        )
    except Exception as exc:  # noqa: BLE001 - 清洗来源不可用=退回实况
        logger.warning("memory bus sanitize source unavailable type=%s", type(exc).__name__)
        return None
    try:
        return _match_category(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory bus sanitize check failed type=%s", type(exc).__name__)
        return None


class MemoryBus:
    """单一事实总线的写入/召回/观测三面。"""

    def __init__(
        self,
        store: MemoryStoreV21,
        *,
        config: object,
        clock: Callable[[], datetime] | None = None,
        legacy_explicit_reader: Callable[[str], Sequence[dict[str, Any]]] | None = None,
        semantic_scorer: Callable[[str, str], float] | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._clock = clock or _utc_now
        self._legacy_explicit_reader = legacy_explicit_reader
        self._semantic_scorer = semantic_scorer

    @property
    def store(self) -> MemoryStoreV21:
        return self._store

    def settings(self) -> BusSettings:
        return settings_from_config(self._config)

    # ---------------------------------------------------------------- 写入面

    def absorb(
        self,
        *,
        owner_id: str,
        subject_user_id: str,
        text: str,
        session_id: Any,
        category: str = "",
        confidence: float = 0.8,
        provenance: str = PROVENANCE_EXPLICIT,
        source: str = "memory_command",
        sensitivity: str = "personal",
        scope: FactScope | None = None,
        source_event_id: str = "",
        audit_only_reason: str = "",
    ) -> AbsorbOutcome:
        """一条候选事实进总线：确认 / 矛盾 / 直插（+ 幂等与硬线闸）。"""
        body = (text or "").strip()
        owner = (owner_id or "").strip() or str(subject_user_id or "").strip()
        if not body or not owner:
            return AbsorbOutcome("rejected", "", reason="empty_candidate")
        violation = _sanitize_violation(body)
        if violation:
            # 硬线内容不入库；这里留一行结构化日志而不是静默丢弃（观测面纪律）。
            logger.warning(
                "memory bus candidate refused category=%s owner=%s scope=%s",
                violation,
                owner,
                audit_only_reason or "n-a",
            )
            return AbsorbOutcome("rejected", "", reason=f"hard_line:{violation}")
        resolved_scope = scope or derive_scope(session_id)
        if provenance != PROVENANCE_EXPLICIT and not resolved_scope.key:
            # 归纳侧的脏/空作用域不配拿到「全会话可见」——v1 的 fail-open 在此关死。
            return AbsorbOutcome("rejected", "", reason="unscoped_candidate")
        if source_event_id:
            existing_event = self._store.find_by_source_event(
                owner_id=owner, source_event_id=source_event_id
            )
            if existing_event is not None:
                return AbsorbOutcome(
                    "duplicate_skipped",
                    str(existing_event["memory_id"]),
                    confirm_count=int(existing_event.get("confirm_count") or 1),
                    contradict_count=int(existing_event.get("contradict_count") or 0),
                    reason="source_event_seen",
                )
        signature = fact_signature(body, category=category)
        if provenance != PROVENANCE_EXPLICIT and self._slot_was_forgotten(
            owner=owner, slot=signature.slot, polarity=signature.polarity
        ):
            # 遗忘权优先于归纳：用户删掉的这件事，夜里想了想又记回来=最坏体验。
            # 本人再显式说一次（``记忆 add``）仍然可以重建——那是改主意，不是回魂。
            return AbsorbOutcome("rejected", "", reason="forgotten_slot")
        now = self._clock()
        now_text = _iso(now)
        peers = self._store.list_slot_rows(owner_id=owner, slot_key=signature.slot)
        # 同槽位同极性=「又说起」（措辞可以不同：「我喜欢柠檬茶」与「我超爱柠檬茶」
        # 折到同一槽位）。旧文措辞不改写——确认只加证据，不覆盖第一手的说法。
        same_polarity = next(
            (
                row
                for row in peers
                if str(row.get("polarity") or "") == signature.polarity
            ),
            None,
        )
        if same_polarity is not None:
            memory_id = str(same_polarity["memory_id"])
            confirm_count = int(same_polarity.get("confirm_count") or 1) + 1
            fields: dict[str, Any] = {
                "confirm_count": confirm_count,
                "last_confirmed_at": now_text,
                "updated_at": now_text,
            }
            # 显式命令再确认一次即取得最高可靠度：归纳行被 explicit 复述后升格。
            if provenance == PROVENANCE_EXPLICIT and str(
                same_polarity.get("provenance") or ""
            ) != PROVENANCE_EXPLICIT:
                fields["provenance"] = PROVENANCE_EXPLICIT
                fields["confidence"] = _CONFIDENCE_CEILING[PROVENANCE_EXPLICIT] * max(
                    0.0, min(1.0, float(confidence))
                )
            self._store.update_bus_fields(memory_id, fields)
            return AbsorbOutcome(
                "confirmed", memory_id, confirm_count=confirm_count
            )
        contradiction = next(
            (
                row
                for row in peers
                if str(row.get("polarity") or "") != signature.polarity
                and signature.polarity
                and str(row.get("polarity") or "")
            ),
            None,
        )
        if contradiction is not None and str(
            contradiction.get("provenance") or ""
        ) == PROVENANCE_EXPLICIT and provenance != PROVENANCE_EXPLICIT:
            # 「显式压过归纳」：归纳不得作废 explicit 行，只能自己另立一条降权行。
            contradiction = None
        superseded_id = ""
        if contradiction is not None:
            superseded_id = str(contradiction["memory_id"])
            self._store.update_bus_fields(
                contradiction["memory_id"],
                {
                    "contradict_count": int(contradiction.get("contradict_count") or 0)
                    + 1,
                    # 旧行不判死：只降权，高确认次数一方在召回面上自己胜出。
                    "status": str(contradiction.get("status") or "active"),
                    "updated_at": now_text,
                },
            )
        decay_class = _DECAY_ALIASES.get(
            _CATEGORY_DECAY.get((category or "").strip().casefold(), ""), DECAY_STABLE
        )
        ceiling = _CONFIDENCE_CEILING.get(provenance, 0.8)
        memory_id = f"mb_{secrets.token_hex(6)}"
        row: dict[str, Any] = {
            "memory_id": memory_id,
            "owner_id": owner,
            # session_id 列保留旧语义（既有服务/投影按它取值）：global 或本次会话键。
            "session_id": resolved_scope.key or "global",
            "kind": _KIND_BY_CATEGORY.get(
                (category or "").strip().casefold(), "fact"
            ),
            "status": "active"
            if provenance == PROVENANCE_EXPLICIT
            else ("active" if confidence >= 0.5 else "pending_review"),
            "version": 1,
            "text": body,
            "confidence": max(0.0, min(1.0, float(confidence))) * ceiling,
            "sensitivity": sensitivity if sensitivity in _SENSITIVITY_VALUES else "personal",
            "source": source,
            "source_event_id": source_event_id,
            "correction_of": superseded_id or None,
            "ttl_seconds": None,
            "expires_at": None,
            "created_at": now_text,
            "updated_at": now_text,
            "provenance": provenance,
            "confirm_count": 1,
            "contradict_count": 0,
            "first_seen_at": now_text,
            "last_confirmed_at": now_text,
            "scope_kind": resolved_scope.kind,
            "scope_key": resolved_scope.key,
            "supersedes": superseded_id,
            "decay_class": decay_class,
            "slot_key": signature.slot,
            "polarity": signature.polarity,
        }
        clash = self._store.insert_bus_entry(row)
        if clash is not None:
            return AbsorbOutcome("duplicate_skipped", clash, reason="unique_index")
        action = "contradicted" if superseded_id else "inserted"
        return AbsorbOutcome(
            action,
            memory_id,
            confirm_count=1,
            superseded_id=superseded_id,
        )

    def _slot_was_forgotten(self, *, owner: str, slot: str, polarity: str) -> bool:
        """同槽同极性的行是否被用户亲自抹掉过（墓碑优先，迁移/重跑同样压得住）。"""
        return bool(
            self._store.list_forgotten_slot_rows(
                owner_id=owner, slot_key=slot, polarity=polarity
            )
        )

    def forget(self, *, memory_id: str, owner_id: str, forgotten_by: str) -> bool:
        """显式遗忘：墓碑先行 + 行翻 forgotten；幂等探针随后无法复活它。"""
        entry = self._store.get_entry(memory_id)
        if entry is None or str(entry.get("owner_id")) != owner_id:
            return False
        self._store.insert_tombstone(
            {
                "memory_id": memory_id,
                "owner_id": owner_id,
                "reason": "forget",
                "original_version": int(entry.get("version") or 1),
                "forgotten_by": forgotten_by,
                "created_at": _iso(self._clock()),
            }
        )
        self._store.remove_index_row(memory_id)
        self._store.update_bus_fields(
            memory_id, {"status": "forgotten", "updated_at": _iso(self._clock())}
        )
        return True

    # ---------------------------------------------------------------- 强度与打分

    def strength_of(
        self,
        row: dict[str, Any],
        now: datetime,
        *,
        settings: BusSettings | None = None,
    ) -> float:
        settings = settings or self.settings()
        confirm = max(1, int(row.get("confirm_count") or 1))
        saturated = 1.0 - math.exp(-confirm / settings.strength_k)
        decay_class = _DECAY_ALIASES.get(
            str(row.get("decay_class") or ""), DECAY_STABLE
        )
        tau = settings.tau_days.get(decay_class, settings.tau_days[DECAY_STABLE])
        aged = _age_days(
            _parse_time(row.get("last_confirmed_at") or row.get("created_at")), now
        )
        decay = math.exp(-aged / tau)
        reliability = _SOURCE_RELIABILITY.get(
            str(row.get("provenance") or PROVENANCE_EXPLICIT), 0.7
        )
        penalty = min(
            _CONTRADICT_PENALTY_CAP,
            _CONTRADICT_PENALTY_STEP * max(0, int(row.get("contradict_count") or 0)),
        )
        return saturated * decay * reliability * (1.0 - penalty)

    def recency_of(self, row: dict[str, Any], now: datetime) -> float:
        moment = _parse_time(
            row.get("last_confirmed_at") or row.get("used_at") or row.get("created_at")
        )
        return math.pow(0.5, _age_days(moment, now) / _RECALL_RECENCY_HALF_LIFE_DAYS)

    def relevance_of(
        self,
        row_text_tokens: frozenset[str],
        query_tokens: frozenset[str],
        *,
        query_text: str,
        row_text: str,
        settings: BusSettings,
    ) -> tuple[float, bool]:
        """两级相关性：①语义（有注入缝才可用）②词元重叠退化，返回 (分, 语义可用)。"""
        lexical = _similarity(row_text_tokens, query_tokens) if query_tokens else 0.0
        if not settings.semantic_recall_enabled or self._semantic_scorer is None:
            return (
                lexical if query_tokens else _NEUTRAL_RELEVANCE_WITHOUT_QUERY,
                False,
            )
        try:
            semantic = float(self._semantic_scorer(query_text, row_text))
        except Exception as exc:  # noqa: BLE001 - 语义面故障即降级，不断召回链
            logger.warning("memory bus semantic scorer failed type=%s", type(exc).__name__)
            return (
                lexical if query_tokens else _NEUTRAL_RELEVANCE_WITHOUT_QUERY,
                False,
            )
        return (max(lexical, max(0.0, min(1.0, semantic))), True)

    # ---------------------------------------------------------------- 召回面

    def recall(
        self,
        *,
        owner_id: str,
        session_id: Any,
        query_text: str = "",
        max_items: int = 5,
        max_chars: int = 1200,
        request_id: str = "",
        persist_audit: bool = True,
    ) -> RecallOutcome:
        settings = self.settings()
        now = self._clock()
        scope = derive_scope(session_id)
        rows = self._store.list_bus_candidates(
            owner_id=owner_id, scope_key=scope.key
        )
        folded = list(rows) + self._legacy_explicit_rows(owner_id=owner_id)
        query_tokens = _token_set(canonical_fact_text(query_text))
        weights = settings.weights
        scored: list[tuple[ScoredFact, frozenset[str], str]] = []
        dropped: list[DroppedFact] = []
        semantic_available = False
        for row in folded:
            text = str(row.get("text") or "").strip()
            fact_id = str(row.get("memory_id") or row.get("fact_id") or "")
            if not text or not fact_id:
                continue
            sensitivity = str(row.get("sensitivity") or "personal")
            if sensitivity == "credentialed":
                # 红线：凭证级永不进 prompt（与 providers 的 LLM-safe 名单双保险）。
                dropped.append(DroppedFact(fact_id, text, "credentialed"))
                continue
            decay_class = _DECAY_ALIASES.get(str(row.get("decay_class") or ""), DECAY_STABLE)
            if decay_class == DECAY_EPISODIC:
                dropped.append(DroppedFact(fact_id, text, "episodic_not_profile"))
                continue
            tokens = _token_set(canonical_fact_text(text))
            relevance, semantic_row_available = self.relevance_of(
                tokens,
                query_tokens,
                query_text=query_text,
                row_text=text,
                settings=settings,
            )
            semantic_available = semantic_available or semantic_row_available
            strength = float(row.get("_strength_override") or 0.0) or self.strength_of(
                row, now, settings=settings
            )
            recency = self.recency_of(row, now)
            score = (
                weights["w_rel"] * relevance
                + weights["w_str"] * strength
                + weights["w_rec"] * recency
            )
            scored.append(
                (
                    ScoredFact(
                        fact_id=fact_id,
                        text=text,
                        kind=str(row.get("kind") or "fact"),
                        sensitivity=sensitivity,
                        scope_key=str(row.get("scope_key") or ""),
                        scope_kind=str(row.get("scope_kind") or SCOPE_GLOBAL),
                        provenance=str(row.get("provenance") or PROVENANCE_EXPLICIT),
                        score=round(score, 6),
                        relevance=round(relevance, 6),
                        strength=round(strength, 6),
                        recency=round(recency, 6),
                        redundancy=0.0,
                        confirm_count=int(row.get("confirm_count") or 1),
                        contradict_count=int(row.get("contradict_count") or 0),
                    ),
                    tokens,
                    fact_signature(text).residual,
                )
            )
        # 零相关地板（§七场景 4 的执法面）：有查询词且**至少一条相关**时，与本轮
        # 话题零重合的旧事实直接出局——光靠加权压不住它（印证次数多到一定程度会
        # 反赢相关性），而 v1 的毛病正是「confidence 够就照塞」。一条都不相关时
        # 不地板（退回按强度给，绝不让注入面因为「没查到」而清空）。
        if query_tokens and any(candidate.relevance > 0.0 for candidate, _t, _s in scored):
            kept = [
                entry for entry in scored if entry[0].relevance > 0.0
            ]
            for candidate, _tokens, _slot in scored:
                if candidate.relevance <= 0.0:
                    dropped.append(
                        DroppedFact(candidate.fact_id, candidate.text, "irrelevant")
                    )
            scored = kept
        scored.sort(key=lambda item: (-item[0].score, item[0].fact_id))
        picked: list[ScoredFact] = []
        picked_tokens: list[frozenset[str]] = []
        slot_counts: dict[str, int] = {}
        used_chars = 0
        for candidate, tokens, slot in scored:
            redundancy = max(
                (_similarity(tokens, other) for other in picked_tokens), default=0.0
            )
            if slot_counts.get(slot, 0) >= settings.per_slot_max:
                dropped.append(DroppedFact(candidate.fact_id, candidate.text, "slot_cap"))
                continue
            if redundancy >= _DUPLICATE_SIMILARITY:
                dropped.append(
                    DroppedFact(candidate.fact_id, candidate.text, "near_duplicate")
                )
                continue
            final_score = candidate.score - weights["w_red"] * redundancy
            cost = len(candidate.text) + (1 if picked else 0)
            if len(picked) >= max(0, int(max_items)) or used_chars + cost > max_chars:
                dropped.append(DroppedFact(candidate.fact_id, candidate.text, "budget"))
                continue
            picked.append(
                ScoredFact(
                    **{
                        **candidate.__dict__,
                        "score": round(final_score, 6),
                        "redundancy": round(redundancy, 6),
                    }
                )
            )
            picked_tokens.append(tokens)
            slot_counts[slot] = slot_counts.get(slot, 0) + 1
            used_chars += cost
        rendered = ""
        if picked:
            rendered = "【长期记忆】\n" + "\n".join(f"- {item.text}" for item in picked)
        outcome = RecallOutcome(
            request_id=request_id,
            items=picked,
            dropped=dropped,
            candidates=len(folded),
            semantic_available=semantic_available,
            scope_key=scope.key,
            rendered=rendered,
        )
        if persist_audit:
            self._write_audit(owner_id=owner_id, outcome=outcome, request_id=request_id)
        return outcome

    def _legacy_explicit_rows(self, *, owner_id: str) -> list[dict[str, Any]]:
        """双读影子期：旧 ``memory_facts`` 里的显式事实按 explicit 口径并进打分，
        不迁移、不改写、不复活（写侧仍由 ``记忆 add`` 落在原库）。
        """
        if self._legacy_explicit_reader is None:
            return []
        try:
            raw_rows = list(self._legacy_explicit_reader(owner_id))
        except Exception as exc:  # noqa: BLE001 - 影子读失败=少一路候选，不断召回
            logger.warning(
                "memory bus legacy shadow read failed type=%s", type(exc).__name__
            )
            return []
        folded: list[dict[str, Any]] = []
        for row in raw_rows:
            if str(row.get("owner_id") or row.get("subject_user_id") or "") != owner_id:
                continue
            folded.append(
                {
                    "memory_id": f"legacy:{row.get('fact_id')}",
                    "kind": str(row.get("memory_kind") or "fact"),
                    "text": str(row.get("text") or ""),
                    "sensitivity": str(row.get("sensitivity") or "personal"),
                    "scope_kind": SCOPE_GLOBAL,  # 旧库无列化作用域，按既有可见面呈现
                    "scope_key": str(row.get("session_id") or ""),
                    "provenance": PROVENANCE_EXPLICIT,
                    "confirm_count": 1,
                    "contradict_count": 0,
                    "decay_class": DECAY_STABLE,
                    "created_at": str(row.get("updated_at") or row.get("created_at") or ""),
                    "last_confirmed_at": str(row.get("updated_at") or ""),
                    "_strength_override": float(row.get("confidence") or 0.6),
                }
            )
        return folded

    # ---------------------------------------------------------------- 观测面

    def _write_audit(
        self, *, owner_id: str, outcome: RecallOutcome, request_id: str
    ) -> None:
        try:
            self._store.insert_recall_audit(
                {
                    "audit_id": f"mra_{secrets.token_hex(6)}",
                    "request_id": request_id,
                    "owner_id": owner_id,
                    "scope_key": outcome.scope_key,
                    "created_at": _iso(self._clock()),
                    "selected_json": json.dumps(
                        [
                            {
                                "fact_id": item.fact_id,
                                "score": item.score,
                                "relevance": item.relevance,
                                "strength": item.strength,
                                "recency": item.recency,
                                "redundancy": item.redundancy,
                                "provenance": item.provenance,
                                "confirm": item.confirm_count,
                                "contradict": item.contradict_count,
                                "text": item.text[:80],
                            }
                            for item in outcome.items
                        ],
                        ensure_ascii=False,
                    ),
                    "excluded_json": json.dumps(
                        [
                            {
                                "fact_id": item.fact_id,
                                "reason": item.reason,
                                # 凭证级的正文连观测面都不落（audit 会被 /bot why 转述）。
                                "text": "" if item.reason == "credentialed" else item.text[:60],
                            }
                            for item in outcome.dropped
                        ],
                        ensure_ascii=False,
                    ),
                    "candidates": outcome.candidates,
                    "semantic_available": 1 if outcome.semantic_available else 0,
                }
            )
            self._store.prune_recall_audits(keep=200)
        except Exception as exc:  # noqa: BLE001 - 观测面失败绝不阻断召回
            logger.warning("memory bus audit write failed type=%s", type(exc).__name__)

    def latest_audit(self, *, owner_id: str, limit: int = 1) -> dict[str, Any] | None:
        rows = self._store.list_recall_audits(owner_id=owner_id, limit=limit)
        return rows[0] if rows else None

    def render_why(self, *, owner_id: str, now: datetime | None = None) -> str:
        """把最近一次注入的账目渲染成人话（``/bot why`` 的展示体，纯函数无 IO 之外的副作用）。"""
        row = self.latest_audit(owner_id=owner_id)
        if row is None:
            return "这一会话还没有记忆被用过的记录——要么没值得记的事，要么总线还没开启。"
        moment = _parse_time(row.get("created_at"))
        when = moment.astimezone().strftime("%m-%d %H:%M") if moment else "未知时刻"
        try:
            selected = json.loads(str(row.get("selected_json") or "[]"))
            excluded = json.loads(str(row.get("excluded_json") or "[]"))
        except ValueError:
            return "上一次记忆账目读不出来（已记录，按未使用处理）。"
        semantic_note = (
            "语义召回可用"
            if int(row.get("semantic_available") or 0)
            else "语义召回不可用（已降级为词面重叠）"
        )
        lines = [
            (
                f"最近一次记忆注入：{when}，候选 {int(row.get('candidates') or 0)} 条，"
                f"用了 {len(selected)} 条，{semantic_note}"
            )
        ]
        if selected:
            lines.append("用上的：")
            lines.extend(
                f"- {item.get('text', '')!s}（分 {float(item.get('score') or 0.0):.3f}"
                f"｜相关 {float(item.get('relevance') or 0.0):.2f}"
                f"｜强度 {float(item.get('strength') or 0.0):.2f}"
                f"｜新近 {float(item.get('recency') or 0.0):.2f}"
                f"｜{_provenance_label(str(item.get('provenance') or ''))}"
                f"·{int(item.get('confirm') or 1)} 次印证）"
                for item in selected
            )
        else:
            lines.append("这次一条都没用。")
        if excluded:
            lines.append("没用上的：")
            lines.extend(
                f"- {item.get('text', '')!s}（{_drop_label(str(item.get('reason') or ''))}）"
                for item in excluded
            )
        return "\n".join(lines)


_SENSITIVITY_VALUES = frozenset({"public", "group", "personal", "credentialed"})


def _provenance_label(provenance: str) -> str:
    return {
        PROVENANCE_EXPLICIT: "你亲口说的",
        PROVENANCE_REFLECTED: "我回头想的",
        PROVENANCE_DERIVED: "聊天里顺手记的",
    }.get(provenance, provenance or "来源未知")


def _drop_label(reason: str) -> str:
    return {
        "credentialed": "凭证级内容（正文不显示）",
        "episodic_not_profile": "一次性的事，不入长期画像",
        "slot_cap": "同一件事只留最可信的一条",
        "near_duplicate": "和已用的那条太像",
        "irrelevant": "和这轮话题没关系",
        "budget": "长度/条数预算放不下",
    }.get(reason, reason or "未采用")


# ---- 与既有 MemoryProvider 协议的适配 ----


class MemoryBusProvider:
    """总线召回器：满足 ``character/memory.MemoryProvider`` 协议（同名同参）。"""

    def __init__(self, bus: MemoryBus) -> None:
        self._bus = bus

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
    ) -> Any:
        if max_items <= 0 or max_chars <= 0:
            return MemoryRetrievalResult(request_id=request_id)
        # 隐私闸（与 v1 同语义、逐条锁死）：只向本人开放。
        if str(requester_id) != str(subject_user_id):
            return MemoryRetrievalResult(request_id=request_id)
        owner_id = _owner_id_for(subject_user_id, session_id)
        outcome = self._bus.recall(
            owner_id=owner_id,
            session_id=session_id,
            query_text=query_text,
            max_items=max_items,
            max_chars=max_chars,
            request_id=request_id,
            persist_audit=True,
        )
        facts = [
            {
                "fact_id": item.fact_id,
                "kind": item.kind,
                "text": item.text,
                "source": f"memory_bus:{item.provenance}",
                "sensitivity": item.sensitivity,
                "scope_key": item.scope_key or "global",
                "score": str(item.score),
                "provenance": item.provenance,
                "confirm_count": str(item.confirm_count),
            }
            for item in outcome.items
        ]
        return MemoryRetrievalResult(
            request_id=request_id,
            facts=facts,
            confidence=max((item.strength for item in outcome.items), default=0.0),
            privacy_level=PrivacyLevel.PERSONAL,
        )


def _owner_id_for(subject_user_id: str, session_id: Any) -> str:
    """总线 owner：``platform:identity`` 的形态由既有 MemoryPrincipal 负责；
    召回侧只有裸 sender，故与 ``SQLiteMemoryRepository`` 的 subject 口径一致
    （旧库按 sender 存）。有绑定需求时由服务层做身份归并，本件不猜平台。
    """
    return str(subject_user_id or "").strip()


# ---- /bot why 命令面出口（装配：根 __init__ 判据 + 一句 return）----

_WHY_COMMANDS: frozenset[str] = frozenset(
    {
        "why",
        "memory why",
        "为什么记住",
        "为什么用这条",
        "记忆为什么",
        "为什么记得",
        "为什么没记住",
    }
)


def is_memory_why_command(command_text: str) -> bool:
    """``/bot why`` 的文本判据（与 ``is_memory_command_text`` 同族，独立不重叠）。"""
    return command_text.strip().casefold() in _WHY_COMMANDS


def render_memory_why(config: object, subject_user_id: str) -> str:
    """把「最近一次注入用了哪几条、分数、来源、为什么没用别的」说给人听。"""
    owner = str(subject_user_id or "").strip()
    if not owner:
        return "没带上你的身份，我没法查这条记忆账目。"
    bus = build_memory_bus(config)
    if bus is None:
        return "记忆账目还没开：总线的开关没打开（BOT_MEMORY_BUS_ENABLED），现在走的还是旧那套。"
    return bus.render_why(owner_id=owner)


def build_memory_bus(
    config: object,
    *,
    legacy_explicit_reader: Callable[[str], Sequence[dict[str, Any]]] | None = None,
    semantic_scorer: Callable[[str, str], float] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> MemoryBus | None:
    """总线实例（开关关/未配库/建库失败一律 None，调用方按 None 走旧路径）。"""
    settings = settings_from_config(config)
    if not settings.enabled:
        return None
    db_path = str(getattr(config, "bot_memory_db_path", "") or "").strip()
    if not db_path:
        return None
    try:
        store = shared_bus_store(db_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory bus store unavailable type=%s", type(exc).__name__)
        return None
    return MemoryBus(
        store,
        config=config,
        legacy_explicit_reader=legacy_explicit_reader,
        semantic_scorer=semantic_scorer,
        clock=clock,
    )

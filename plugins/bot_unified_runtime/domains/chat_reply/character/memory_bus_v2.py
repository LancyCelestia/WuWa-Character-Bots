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

# ---- 写腿词表（S-T-MEM-1，需求 11「记住昵称/名字/身份并说得出」）----

# 槽位前缀：身份属性类事实的合并键以它开头（``attr:name``）。
ATTRIBUTE_SLOT_PREFIX = "attr:"

# 状态面（与 memory_store_v21 的列注释同源；召回口只收 ACTIVE）。
STATUS_ACTIVE = "active"
STATUS_PENDING = "pending_review"
STATUS_SUPERSEDED = "superseded"

# 来源标签（不是语义类别）：一律折进空命名空间，见 ``slot_namespace``。
_SOURCE_LABEL_CATEGORIES: frozenset[str] = frozenset(
    {
        "",
        "auto",
        "manual",
        "sqlite",
        "memory_command",
        "llm_extract",
        "nightly_reflection",
        "modality_preprocess",
        "legacy",
        "unknown",
    }
)

# 身份属性词表：属性名 → 锚定句首的直陈式（值恒在**某一个**捕获组里，多路并列时
# 组号不固定，故取值走 ``_first_matched_group``，绝不写死 ``group(1)``）。
# 第三元 ``"address"`` = 该路的值必须像「一个称呼」（见 ``_looks_like_form_of_address``）：
# 「叫我小红」是改称呼，「叫我起床/叫我喝水」是提要求，两种都命中同一串字面，
# 不收这道闸就会把「起床」当称呼记下、并在下一句「叫我吃药」时被顶掉。
_VALUE = r"(.{1,24})"
_LATIN_VALUE = r"(.{1,40})"
_IDENTITY_ATTR_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "name",
        re.compile(
            rf"^(?:我|本人|我的)(?:不|才|并)?(?:的名字|名称|的大名|全名)"
            rf"(?:叫|叫做|称为|唤作|是|为){_VALUE}$"
            rf"|^(?:我|本人)(?:不|才)?叫{_VALUE}$"
            rf"|^(?:my\s+name\s+is\s+{_LATIN_VALUE})$"
            rf"|^(?:i\s+(?:am|'m)\s+(?:called|named)\s+{_LATIN_VALUE})$"
        ),
        "address",
    ),
    (
        "nickname",
        re.compile(
            rf"^(?:请|以后|今后|你|你可以|麻烦|记得|别)?(?:叫|喊|称呼|称一下)我"
            rf"(?:作|为|成)?{_VALUE}$"
            rf"|^(?:我的)?(?:昵称|小名|称呼|别名)(?:是|叫|为){_VALUE}$"
            rf"|^(?:please\s+)?call\s+me\s+{_LATIN_VALUE}$"
            rf"|^my\s+nickname\s+is\s+{_LATIN_VALUE}$"
        ),
        "address",
    ),
    (
        "gender",
        re.compile(
            rf"^(?:我的)?性别(?:是|为|:|：)?{_VALUE}$"
            rf"|^我是(?:个)?(男生|女生|男孩子|女孩子|男的|女的)$"
            rf"|^i\s+am\s+a?\s*(male|female|man|woman|non-?binary)$"
        ),
        "value",
    ),
    (
        "occupation",
        re.compile(
            rf"^(?:我的)?(?:职业|工作)(?:是|为|:|：)?{_VALUE}$"
            rf"|^我是做{_VALUE}的$"
            rf"|^我(?:现在|目前)?(?:从事|做){_VALUE}(?:工作|的职业)?$"
            rf"|^my\s+job\s+is\s+{_LATIN_VALUE}$"
        ),
        "value",
    ),
    (
        "location",
        re.compile(
            rf"^我(?:现在|目前|一直)?(?:住在|居住在|定居在?|家在|就住){_VALUE}$"
            rf"|^(?:我的)?(?:城市|所在地|常居地|家乡)(?:是|为|:|：){_VALUE}$"
            rf"|^我在{_VALUE}(?:生活|定居|长住)$"
            rf"|^i\s+(?:live|am)\s+in\s+{_LATIN_VALUE}$"
        ),
        "value",
    ),
    (
        "birthday",
        re.compile(
            rf"^(?:我的)?(?:生日|出生日期|诞辰|出生日)(?:是|为|:|：)?{_VALUE}$"
            rf"|^我是{_VALUE}出(?:生|世)的$"
            rf"|^(?:我)?(?:生于|出生于){_VALUE}$"
            rf"|^my\s+birthday\s+is\s+{_LATIN_VALUE}$"
        ),
        "value",
    ),
)

# 「像一个称呼」的闸：短、纯称谓字形，且不含动作/时间字面（宁可漏记不误记）。
_FORM_OF_ADDRESS_CJK = re.compile(r"[一-鿿]{1,4}")
_FORM_OF_ADDRESS_LATIN = re.compile(r"[a-z0-9·_.\-]{1,12}")
_FORM_OF_ADDRESS_REJECT = re.compile(
    r"[吃喝睡醒起床带拿催习点时分秒周星期日号礼拜明晚午早做写念读练打看学忘别喊叫诉告]"
)


def _first_matched_group(match: re.Match[str]) -> str:
    """取本次命中那一组的值（并列分支的组号不固定，写死 group(1) 必翻车）。"""
    for group in match.groups():
        if group:
            return str(group).strip()
    return ""


def _looks_like_form_of_address(value: str) -> bool:
    """``叫我X`` 的 X 是否像一个称呼。判不出就算不像（fail-closed）。"""
    normalized = canonical_fact_text(value)
    if not normalized:
        return False
    if _FORM_OF_ADDRESS_LATIN.fullmatch(normalized):
        return True
    if not _FORM_OF_ADDRESS_CJK.fullmatch(normalized):
        return False
    return not bool(_FORM_OF_ADDRESS_REJECT.search(normalized))


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
    """一条事实的「槽位 + 残体 + 极性 + 值 + 词元集」——确认/矛盾/近重复判定的尺子。

    ``slot``（含类别前缀）是**写入侧**的合并键：不同类别的「同一句话」不互相
    作废（我的偏好不该被我的计划确认掉）。``residual``（不含类别）是**召回侧**的
    聚簇键：显式命令与夜间归纳常带不同类别标签，说的是同一件事时必须在预算里
    只占一个名额，所以簇键要比合并键宽一档。

    ``attribute``/``value``（S-T-MEM-1 写腿）只服务于**身份属性类**事实
    （名字/称呼/性别/职业/所在地/生日）：这类槽位的语义是「一个属性只有一个
    当前值」，所以合并键是属性本身（``attr:name``），而「同一属性换个值」必须
    判改口而不是判确认——判据就是这里的 ``value``。识别不出来时两字段皆空，
    行为与旧版逐字节相同（fail-closed：宁可多一行，也不误并两条）。
    """

    normalized: str
    slot: str
    residual: str
    polarity: str  # '+' | '-' | ''（无从判定的自由文本）
    tokens: frozenset[str]
    attribute: str = ""
    value: str = ""

    @property
    def is_attribute(self) -> bool:
        return bool(self.attribute)


def slot_namespace(category: str) -> str:
    """槽位命名空间：类别原样，来源标签归一（写腿 S-T-MEM-1）。

    ``manual``（``记忆 add``）、``auto``（单轮抽取）、``sqlite``（旧仓储缺省）说
    的是「这句话从哪来」，不是「这是哪一类事实」。它们若各占一个命名空间，同
    一句话经命令与经抽取会永远落在两个槽里 —— 「又说起=确认」与「显式压过归
    纳」两条教义在写入侧直接失效（生产实况正是这个形态：抽取面恒传 ``auto``，
    命令面恒传 ``manual``）。来源标签一律折进 ``''``，语义类别一个不动。
    """
    folded = (category or "").strip().casefold()
    return "" if folded in _SOURCE_LABEL_CATEGORIES else folded


def identity_attribute(text: str) -> tuple[str, str]:
    """该事实是否声明/更改一个「一个当前值」型身份属性 → ``(属性, 值)``。

    判据是**锚定在句首的第一人称直陈式**，认不出一律返回 ``('','')``：

    - 为什么收得这么紧：属性槽位一旦命中，同属性的两条就互相取代（旧行翻
      ``superseded``）。宽松的判据会把「我妹妹住在北京」「我是在三月份入职的」
      记成她本人的所在地/入职时间并被下一句顶掉，那是**改写她的身份事实**。
      认不中的代价只是退回残体槽位（=今日行为，多一行而非误并）。
    - 为什么只有这六个：需求 11 列的「特征/性格/爱好/喜好/需求/行为」是**可
      并存多项**的，绝不能收成一属性一行；只有名字/称呼/性别/职业/所在地/生
      日属于「说新的就把旧的换掉」那一类。
    - 为什么**不看 category**（本函数只认文本）：属性槽位的值不另立列，比较
      旧行时靠对旧行 ``text`` 现算一次本函数。若类别能单独造出属性槽，现算就
      会算不出当时那个值 ⇒ 同一句话第二次进来被判成「改了主意」并顶掉自己。
      判据必须是纯函数、写侧读侧同形，这是本件的一条硬口径。
    """
    folded = (text or "").strip().casefold()
    if not folded:
        return "", ""
    for attribute, pattern, gate in _IDENTITY_ATTR_PATTERNS:
        match = pattern.match(folded)
        if match is None:
            continue
        captured = _first_matched_group(match)
        if gate == "address" and not _looks_like_form_of_address(captured):
            continue  # 「叫我起床」= 提要求，不是改称呼：退回残体槽位，不占属性槽
        return attribute, canonical_fact_text(captured)
    return "", ""


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
    attribute, attribute_value = identity_attribute(folded)
    namespace = slot_namespace(category)
    if attribute:
        slot = f"{ATTRIBUTE_SLOT_PREFIX}{attribute}"
    else:
        slot = f"{namespace}|{residual}"
    return FactSignature(
        normalized=normalized,
        slot=slot,
        residual=residual,
        polarity=polarity or "+",
        tokens=_token_set(normalized),
        attribute=attribute,
        value=attribute_value or (residual if attribute else ""),
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

# 写腿的读-改-写串行锁（同进程）。理由见 ``MemoryBus.absorb`` 内注释：store 自带的
# RLock 只锁单条语句，锁不住「先查同槽行、再据此决定确认/矛盾/直插」这一段。
_ABSORB_WRITE_LOCK = threading.RLock()


def _peer_value(row: dict[str, Any]) -> str:
    """既有行所记的属性值——**对行内 text 现算**，不另立列（判据单一真身）。

    属性槽位的识别是纯函数（``identity_attribute`` 只认文本、不看类别），故现算
    与写入当时逐字节同形；存第二份值反而会造出「两个真身会漂移」的老毛病。
    """
    return fact_signature(str(row.get("text") or "")).value


def _peer_relation(row: dict[str, Any], signature: FactSignature) -> str:
    """既有行与候选的关系：``same``（又说起）/ ``rival``（改了主意）/ ``''``。

    普通槽位只看极性（今日语义，一字未动）。身份属性槽位多一条：**同属性不同值
    即改口**——「叫我小红」再说成「叫我阿澜」极性都是 ``+``，只比极性就会把新称呼
    当旧称呼的印证吞掉（用户改了称呼而 bot 一直叫老的，正是需求 11 要治的病）。
    """
    row_polarity = str(row.get("polarity") or "")
    if not row_polarity or not signature.polarity:
        return ""
    if not signature.is_attribute:
        return "same" if row_polarity == signature.polarity else "rival"
    peer_value = _peer_value(row)
    if not peer_value or not signature.value:
        # 值算不出（不该发生）：保守判「又说起」——宁可少顶一行，也不误作废旧行。
        return "same"
    if peer_value == signature.value and row_polarity == signature.polarity:
        return "same"
    return "rival"


def _pick_rival(rivals: list[dict[str, Any]], *, is_attribute: bool) -> Any | None:
    """选出被改口的那条：属性槽取「最近被确认的当前值」，其余取最早那条（旧语义）。"""
    if not rivals:
        return None
    if not is_attribute:
        return rivals[0]
    return max(
        rivals,
        key=lambda row: (
            str(row.get("last_confirmed_at") or row.get("created_at") or ""),
            str(row.get("memory_id") or ""),
        ),
    )


def _kind_for(signature: FactSignature, category: str) -> str:
    """行的 ``kind`` 取值。

    身份属性类**用属性名当 kind**（``name``/``nickname``/``gender``/…）：渲染腿
    （S-T-MEM-3，需求 11「kind=昵称/名字/身份…进分区」）要的就是这个信息，写侧
    把它压成 ``fact`` 就等于让她从文本里再猜一次。其余仍走既有词表
    （``fact``/``preference``/``event``），一个不动。渲染面对未登记 kind 的既有
    口径是「短标识原样点名、不编造」⇒ 新增取值不会让注入面瞎。
    """
    if signature.is_attribute:
        return signature.attribute
    return _KIND_BY_CATEGORY.get((category or "").strip().casefold(), "fact")


def _initial_status(
    *, provenance: str, confidence: float, is_attribute: bool
) -> str:
    """新行初值状态。

    在旧口径（explicit 直入 active；归纳按置信度分档）之上加一条**身份属性闸**：
    机器猜出来的名字/称呼/性别未经本人确认不得进召回面（召回口只取 active），
    因为她最不能被叫错的就是名字。她本人再说一次即经确认分支升格为
    explicit+active（见 ``_absorb_locked`` 的「升格即可见」）。
    """
    if provenance == PROVENANCE_EXPLICIT:
        return STATUS_ACTIVE
    if is_attribute:
        return STATUS_PENDING
    return STATUS_ACTIVE if confidence >= 0.5 else STATUS_PENDING



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


# ---- 单一打分器的候选池（消费腿，需求 11）----

# 装配期注入的候选读取口：``(owner_id, session_id) -> rows``。
_CandidateSource = Callable[[str, str], "Sequence[dict[str, Any]]"]

# 旧库（``memory_facts`` / ``reflection_facts``）里表示「不限会话」的书写形态。
# 与 v1 召回腿 ``session_id IN (?, '', '*', 'global')`` 逐字同集合——影子读不得
# 比旧腿更宽，否则同一份数据换个开关就多出跨会话可见面（S-T-MEM-5 普查抓到）。
_GLOBAL_SESSION_FORMS: frozenset[str] = frozenset({"", "*", "global"})

# 复合键的「平台前缀 / 裸键」分隔符字面量：与写侧
# ``reflection.gather_turns_by_date`` 的 ``f"{platform}:{session_id}"``、以及
# ``ReflectionStore.facts_for`` SQL 里 ``substr(session_key, ..., 1) = ':'`` 同一
# 枚字符。**这里只登记分隔符、不登记平台名**——平台名的清单在数据里
# （``conversation_turns.platform``），代码侧没有任何登记表可引用。
_PLATFORM_PREFIX_DELIMITER: str = ":"

# 降级归因码（进 ``memory_recall_audit_v21.excluded_json`` 的 reason，人话表见
# ``_drop_label``）：总线挂了退回旧腿时必须留痕，静默降级=漏报的谎。
DEGRADED_REASON_BUS_RECALL_FAILED = "bus_recall_failed"
DEGRADED_REASON_LEGACY_NEWEST_N = "legacy_newest_n"
#: 非打分腿（旧归纳表/旧显式库）自己挂了。与上一枚分开：合并层若对所有腿都报
#: ``bus_recall_failed``，总线今天根本没开会让人去查一个不存在的东西（归因必须
#: 指向真挂的那条腿）。
DEGRADED_REASON_MEMORY_LEG_FAILED = "memory_leg_failed"


def legacy_session_visible(
    row_session_id: Any,
    current_session_id: Any,
    *,
    accept_platform_prefix: bool = False,
) -> bool:
    """旧池行的会话可见性判定（与各条 v1 召回腿**逐字同宽**，唯一真身在本件）。

    认三种情形：「与本会话整串等值」／「登记在案的全局形态」／（仅
    ``accept_platform_prefix=True`` 时）「整尾等于本会话键、且紧邻前一位是冒号」。

    最后这一档不是新造的宽度，是**照着某一条 v1 腿补齐的**：旧归纳表
    ``reflection_facts.session_key`` 的写侧形态是 ``platform:裸键``
    （``reflection.gather_turns_by_date`` 的 ``f"{platform}:{session_id}"``），而
    召回方手里只有裸键；其 v1 读取口 ``ReflectionStore.facts_for`` 的 SQL 本来就带
    这一档（``length(>)`` + 尾部等值 + 前一位 ``':'`` 三条件），所以注入方放行的行
    必须在折叠处同样放行——否则折叠闸比注入闸更严，整表被自己拒掉。生产现算：该库
    112 行、去重 35 个键，**100% 是复合形**（2026-09-26 只读普查）；旧写法只兜裸键
    等值 ⇒ 第一档（``target=legacy``）下反思事实一条都进不了打分池，而既有夹具全用
    裸键 ⇒ 测试全绿。

    宽度**按来源分别给定**，不是一把尺量两条腿（「影子读不得比旧腿更宽」）：

    - 旧显式库 ``memory_facts`` 的 v1 腿是 SQL 等值
      ``session_id IN (?, '', '*', 'global')``，**没有**前缀档 ⇒ 该路传
      ``accept_platform_prefix=False``（本函数的缺省值，调用点不写就是旧行为）；
    - 装配期注入源（今天只有旧归纳表那一路）的 v1 腿 = ``facts_for`` ⇒ 传 True，
      并由 ``tests/test_memory_bus_read_leg.py`` 的「总线可见集 ⊆ facts_for 放行集」
      逐条比对锁住，两处判据不得各说各话。

    仍**不用 LIKE、不做子串或通配**：键里的 ``_`` 一旦当通配就是 ``group_1_2``
    串进 ``group_1X2`` 那类事故（同 ``test_shared_export_key_shape`` 钉过的病）。
    前缀档为什么不构成「尾部包含」那类放宽：命中的行必须把 ``current`` **整串**当
    后缀、且分隔符固定是冒号——群复合键 ``qq:group_<gid>_<uid>`` 里 uid 前一位是
    ``_`` 而非 ``:``，所以它折不进私聊裸键 ``<uid>``，也折不进另一个群的键；反过来
    私聊行 ``qq:<uid>`` 与群本轮键 ``group_<gid>_<uid>`` 整尾不等值 ⇒ 两边都过不去。
    判据刻意**不查平台名登记表**（中央件 ``session_keys`` 没有这张表，凭空造一份就
    是第二真身，而且适配器平台名会随适配器增加而漂移）：只认「冒号 + 整尾等值」，
    既不因漏登记而静默丢行，也不会把不是本会话键的尾巴折进来。
    """
    current = str(current_session_id or "").strip()
    row = str(row_session_id or "").strip()
    if row in _GLOBAL_SESSION_FORMS:
        return True
    if not current:
        # 本轮拿不到会话键：只见全局行（fail-closed，与 derive_scope 空键同侧）。
        return False
    if row == current:
        return True
    if not accept_platform_prefix:
        return False
    # endswith(":" + current) 本身蕴含「前缀至少一名字符 + 分隔符是冒号 + 整尾等值」，
    # 与 facts_for 那三条 SQL 条件逐一对应（len 大于 / 尾部等值 / 前一位是 ':'）。
    return row.endswith(_PLATFORM_PREFIX_DELIMITER + current)


def _as_bus_row(
    row: dict[str, Any],
    *,
    memory_id: str,
    provenance: str,
) -> dict[str, Any]:
    """把外部旧池行折成总线打分形状（缺列一律取保守值，绝不凭空造证据）。"""
    raw_session = str(row.get("session_id") or row.get("session_key") or "")
    return {
        "memory_id": memory_id,
        "kind": str(row.get("kind") or row.get("memory_kind") or "fact"),
        "text": str(row.get("text") or row.get("fact_text") or ""),
        "sensitivity": str(row.get("sensitivity") or "personal"),
        # 旧池没有列化作用域；按「本轮可见的行」呈现，取值仍走中央件派生。
        "scope_kind": derive_scope(raw_session).kind,
        "scope_key": raw_session,
        "provenance": provenance,
        "confirm_count": int(row.get("confirm_count") or 1),
        "contradict_count": int(row.get("contradict_count") or 0),
        "decay_class": str(row.get("decay_class") or DECAY_STABLE),
        "created_at": str(row.get("updated_at") or row.get("created_at") or ""),
        "last_confirmed_at": str(row.get("updated_at") or row.get("created_at") or ""),
        "_strength_override": float(row.get("confidence") or 0.6),
    }


class MemoryBus:
    """单一事实总线的写入/召回/观测三面。

    **写入面是全仓唯一的事实落库口**（需求 11 写腿，S-T-MEM-1）：命令面
    ``记忆 add``、单轮抽取、夜间归纳、材料沉淀四条来源统统经 ``absorb`` 进来，
    幂等与冲突在这里裁决——三层判据：

    1. ``source_event_id`` 探针 + ``(owner, source_event_id)`` 唯一索引
       ⇒ 同一**来源事件**重放（迁移/重试/双投）绝不第二行；
    2. 同 owner + 同作用域 + 同槽位（内容指纹 = 归一残体，身份属性类 = 属性值）
       且同极性 ⇒ 「又说起」：只给既有行 ``confirm_count+1``，**不新增行、
       不改写第一手措辞**；
    3. 同槽位反极性（或身份属性换了值）⇒ 「改了主意」：双行并存 + 新行
       ``supersedes`` 指回旧行 + 旧行 ``contradict_count+1``；身份属性类且来源
       为本人明示时旧行另翻 ``superseded``（一个属性只留一个当前值）。

    没有任何一条路可以绕过这三层直写 ``memory_entries_v21``——由
    ``tests/test_memory_bus_v2_write_leg.py`` 的 AST 锁执法。
    """

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
        # 装配期注入的**额外候选源**（需求 11 消费腿）：总线是唯一打分器，
        # 尚未迁进总线的旧池子（夜间归纳旧表）由这里并进同一打分池，
        # 而不是在合并层各排各的再串接。键=源名（同名覆盖=幂等重装配）。
        self._candidate_sources: dict[str, tuple[_CandidateSource, str]] = {}

    @property
    def store(self) -> MemoryStoreV21:
        return self._store

    def settings(self) -> BusSettings:
        return settings_from_config(self._config)

    def attach_candidate_source(
        self,
        name: str,
        reader: _CandidateSource,
        *,
        provenance: str = PROVENANCE_REFLECTED,
    ) -> None:
        """登记一路「尚未落总线的候选」（装配期调用，读路径不改内容）。

        ``reader(owner_id, session_id)`` 必须**自带可见性闸**（只给本人 +
        本会话 + 全局），返回行需带 ``memory_id/kind/text/sensitivity/
        session_id/confidence/created_at``。本方法只登记，不建第二打分器：
        这些行与总线原生行同池同公式同预算。
        """
        key = str(name or "").strip()
        if not key:
            raise ValueError("candidate source needs a name")
        if provenance not in _SOURCE_RELIABILITY:
            raise ValueError(f"unknown provenance for candidate source: {provenance}")
        self._candidate_sources[key] = (reader, provenance)

    def candidate_source_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._candidate_sources))

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
        signature = fact_signature(body, category=category)
        # 读-改-写一整段串行：`chat.py:3190` 允许最多 4 个抽取线程在飞，而本方法
        # 的形状是「查同槽行 → 据此决定确认/矛盾/直插 → 落库」。不套锁时两个线程
        # 可以同时在「 peers 为空」的分支里各插一行 ⇒ 同一条事实两行，且
        # confirm_count 互相覆盖（丢更新）。SQLite 侧的 RLock 只保证单条语句原子，
        # 保证不了这段的判定原子性——锁必须在这里，不能在 store 里。
        # 跨进程（迁移脚本与 bot 同时在写）本锁管不住，那一层仍靠 source_event_id
        # 的幂等探针 + 唯一索引兜底，本件如实登记不夸大。
        with _ABSORB_WRITE_LOCK:
            return self._absorb_locked(
                owner=owner,
                body=body,
                category=category,
                confidence=confidence,
                provenance=provenance,
                source=source,
                sensitivity=sensitivity,
                resolved_scope=resolved_scope,
                source_event_id=source_event_id,
                signature=signature,
            )

    def _absorb_locked(
        self,
        *,
        owner: str,
        body: str,
        category: str,
        confidence: float,
        provenance: str,
        source: str,
        sensitivity: str,
        resolved_scope: FactScope,
        source_event_id: str,
        signature: FactSignature,
    ) -> AbsorbOutcome:
        """``absorb`` 的落库段：**只能在 ``_ABSORB_WRITE_LOCK`` 内调用**。"""
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
        if provenance != PROVENANCE_EXPLICIT and self._slot_was_forgotten(
            owner=owner, slot=signature.slot, polarity=signature.polarity
        ):
            # 遗忘权优先于归纳：用户删掉的这件事，夜里想了想又记回来=最坏体验。
            # 本人再显式说一次（``记忆 add``）仍然可以重建——那是改主意，不是回魂。
            # 判据刻意**不收作用域窗**（比下面的合并窗宽）：遗忘是对这件事的表达，
            # 不是对某个房间的表达——宁可少记，不可把刚删掉的东西从别处绕回来。
            return AbsorbOutcome("rejected", "", reason="forgotten_slot")
        now = self._clock()
        now_text = _iso(now)
        # 合并窗 = 同 owner + 同槽位 + **同作用域**（列等值）。不收作用域窗会让
        # 「群 A 说过、私聊再说一次」并进群 A 那行而私聊永远召不回，见
        # ``MemoryStoreV21.list_slot_rows`` 的注释。
        peers = self._store.list_slot_rows(
            owner_id=owner,
            slot_key=signature.slot,
            scope_kind=resolved_scope.kind,
            scope_key=resolved_scope.key,
        )
        same_polarity = next(
            (row for row in peers if _peer_relation(row, signature) == "same"), None
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
            upgraded = provenance == PROVENANCE_EXPLICIT and str(
                same_polarity.get("provenance") or ""
            ) != PROVENANCE_EXPLICIT
            if upgraded:
                fields["provenance"] = PROVENANCE_EXPLICIT
                fields["confidence"] = _CONFIDENCE_CEILING[PROVENANCE_EXPLICIT] * max(
                    0.0, min(1.0, float(confidence))
                )
            # 「升格即可见」：低置信归纳行初值是 pending_review，而召回口只取 active。
            # 本人亲口复述过一次却仍留在待审，等于「记了但说不出来」——升格半截
            # 停在磁盘上就是这一处的漏网（S-T-MEM-1 写腿实算抓到）。
            if (
                upgraded or provenance == PROVENANCE_EXPLICIT
            ) and str(same_polarity.get("status") or "") != STATUS_ACTIVE:
                fields["status"] = STATUS_ACTIVE
            self._store.update_bus_fields(memory_id, fields)
            return AbsorbOutcome(
                "confirmed", memory_id, confirm_count=confirm_count
            )
        rivals = [row for row in peers if _peer_relation(row, signature) == "rival"]
        contradiction = _pick_rival(rivals, is_attribute=signature.is_attribute)
        if contradiction is not None and str(
            contradiction.get("provenance") or ""
        ) == PROVENANCE_EXPLICIT and provenance != PROVENANCE_EXPLICIT:
            # 「显式压过归纳」：归纳不得作废 explicit 行，只能自己另立一条降权行。
            contradiction = None
        superseded_id = ""
        if contradiction is not None:
            superseded_id = str(contradiction["memory_id"])
            rival_fields: dict[str, Any] = {
                "contradict_count": int(contradiction.get("contradict_count") or 0) + 1,
                "updated_at": now_text,
            }
            if signature.is_attribute and provenance == PROVENANCE_EXPLICIT:
                # 身份属性「一个属性只有一个当前值」：本人改口 ⇒ 旧行退场留痕。
                # 不是静默覆盖：行不删、文本不改，新行 supersedes 指回它，旧行
                # 记一次 contradict_count，`/bot why` 与 list_entries_by_owner 都还在。
                rival_fields["status"] = STATUS_SUPERSEDED
            self._store.update_bus_fields(superseded_id, rival_fields)
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
            "kind": _kind_for(signature, category),
            "status": _initial_status(
                provenance=provenance,
                confidence=confidence,
                is_attribute=signature.is_attribute,
            ),
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
        folded = self._candidate_pool(
            owner_id=owner_id, session_id=session_id, bus_rows=rows
        )
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

    def _candidate_pool(
        self,
        *,
        owner_id: str,
        session_id: Any,
        bus_rows: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """本轮打分池 = 总线原生行 ∪ 旧显式影子行 ∪ 装配注入的旧归纳行（唯一并池处）。

        顺序即优先级：总线原生 → 旧显式 → 注入源；同正文只留第一条。所以「旧行
        已迁进总线」时 prompt 里看到的是它的总线身份，不会两句话各占一格——
        合并层按 ``fact_id`` 去重拦不住这种「同一句话两个身份」。
        """
        pool = [dict(row) for row in bus_rows]
        taken = {str(row.get("text") or "").casefold() for row in pool}
        pool += self._legacy_explicit_rows(
            owner_id=owner_id, session_id=session_id, taken_texts=taken
        )
        pool += self._attached_rows(
            owner_id=owner_id, session_id=session_id, taken_texts=taken
        )
        return pool

    def _legacy_explicit_rows(
        self,
        *,
        owner_id: str,
        session_id: Any = "",
        taken_texts: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """双读影子期：旧 ``memory_facts`` 里的显式事实按 explicit 口径并进打分，
        不迁移、不改写、不复活（写侧仍由 ``记忆 add`` 落在原库）。

        **可见性与 v1 召回腿同宽、绝不更宽**（S-T-MEM-5 收口；S-T-MEM-4 现算挂账）：
        旧库读取口按主体给全量行（迁移与命令面要的就是全量），本函数是它进 prompt
        前的唯一收口——只留「本会话 + 登记在案的全局形态」。旧实现把这些行一律标成
        ``scope_kind=global`` 直接并池，等于开了总线之后私聊行在任意群可被召回
        （v1 靠 SQL 的 session_id 等值挡着，开闸反而拆了这道闸）。
        """
        if self._legacy_explicit_reader is None:
            return []
        try:
            rows = list(self._legacy_explicit_reader(owner_id))
        except Exception as exc:  # noqa: BLE001 - 影子读失败=少一路候选，不断召回
            logger.warning(
                "memory bus legacy shadow read failed type=%s", type(exc).__name__
            )
            return []
        return self._fold_pool(
            owner_id=owner_id,
            session_id=session_id,
            rows=rows,
            id_prefix="legacy",
            provenance=PROVENANCE_EXPLICIT,
            taken_texts=taken_texts if taken_texts is not None else set(),
            # 该来源的 v1 腿（memory.py 的 SQL）只有等值 + 全局形态，没有平台前缀档
            # ⇒ 显式写死 False：影子读不得比旧腿更宽，别顺着上面那档一起放宽。
            accept_platform_prefix=False,
        )

    def _attached_rows(
        self,
        *,
        owner_id: str,
        session_id: Any,
        taken_texts: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """装配期注入的额外候选池（尚未迁进总线的旧归纳表）→ 同一个打分池。

        注入源必须**自带可见性闸**（只交本人 + 本会话 + 全局）；本函数再兜一层会话
        闸，防某条源漏了闸就把别的会话的行送进来。这一层**按注入源自己的 v1 腿给宽**
        （这里传 ``accept_platform_prefix=True``）：今天的注入源是
        ``providers._reflection_candidate_source``，其唯一读取口是
        ``ReflectionStore.facts_for``——那条 SQL 自己就认 ``platform:裸键``，并且把
        行上的 ``session_key``（复合形）原样交下来当 ``session_id``。折叠闸若只认裸
        键等值，就是把注入方**已经放行**的行再拒一遍：整表进不了打分池，而注入源的
        测试用裸键夹具 ⇒ 两边各自都「绿」。宽度不自行放大：``test_memory_bus_read_leg
        宽度不自行放大：``tests/test_memory_bus_read_leg.py`` 的
        ``test_folded_pool_never_wider_than_facts_for`` 逐条比对「折叠后可见集 ⊆
        facts_for 放行集」，注毒放宽即红。id 前缀=源名 ⇒ 与总线原生行、``legacy:``
        影子行三者身份互不碰撞。
        """
        folded: list[dict[str, Any]] = []
        for name, (reader, provenance) in sorted(self._candidate_sources.items()):
            try:
                rows = list(reader(owner_id, str(session_id or "")))
            except Exception as exc:  # noqa: BLE001 - 少一路候选，不断召回链
                logger.warning(
                    "memory bus candidate source failed source=%s type=%s",
                    name,
                    type(exc).__name__,
                )
                continue
            folded.extend(
                self._fold_pool(
                    owner_id=owner_id,
                    session_id=session_id,
                    rows=rows,
                    id_prefix=name,
                    provenance=provenance,
                    taken_texts=taken_texts if taken_texts is not None else set(),
                    # 注入源那侧的 v1 腿（ReflectionStore.facts_for）认平台前缀形，
                    # 折叠闸必须同宽，否则注入方放行的行在这里被整表再拒一次。
                    accept_platform_prefix=True,
                )
            )
        return folded

    def _fold_pool(
        self,
        *,
        owner_id: str,
        session_id: Any,
        rows: Sequence[dict[str, Any]],
        id_prefix: str,
        provenance: str,
        taken_texts: set[str],
        accept_platform_prefix: bool = False,
    ) -> list[dict[str, Any]]:
        """外部池的行进打分池前的三道闸：主体 → 会话可见性 → 同文去重。

        - **主体闸**：行上的 owner/subject 与本轮 owner 不等 ⇒ 不入池（旧腿 SQL 是
          ``WHERE subject_user_id = ?``，影子读若丢了这层就等于把别人的事念给本轮
          用户听，故在折叠处再兜一次，结构性不可放宽）；
        - **会话闸**：见 ``legacy_session_visible``；``accept_platform_prefix`` 由
          **调用方按该来源自己的 v1 腿给定**（缺省 False=旧显式库那条等值腿的形状），
          本函数不自行猜来源的形态；
        - **同文去重**：按归一正文（casefold）先到先得，重复身份不再占预算。
        """
        folded: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("owner_id") or row.get("subject_user_id") or "") != owner_id:
                continue
            raw_session = str(row.get("session_id") or row.get("session_key") or "")
            if not legacy_session_visible(
                raw_session, session_id, accept_platform_prefix=accept_platform_prefix
            ):
                continue
            source_id = str(row.get("memory_id") or row.get("fact_id") or "")
            if not source_id:
                continue
            memory_id = (
                source_id
                if source_id.startswith(f"{id_prefix}:")
                else f"{id_prefix}:{source_id}"
            )
            text_key = str(row.get("text") or row.get("fact_text") or "").casefold()
            if text_key and text_key in taken_texts:
                continue
            taken_texts.add(text_key)
            folded.append(_as_bus_row(row, memory_id=memory_id, provenance=provenance))
        return folded
    # ---------------------------------------------------------------- 观测面

    def record_degraded_recall(
        self,
        *,
        owner_id: str,
        session_id: Any,
        request_id: str,
        reason: str,
        detail: str = "",
    ) -> bool:
        """**降级留痕**：本轮没走总线打分（挂了/退回旧腿）时落一条注入审计。

        静默降级是漏报的谎——今天生产关着总线，「召回与本轮话题无关」这个症状
        没有任何一处会自己承认。本方法只写既有审计表（``excluded_json`` 里一条
        归因记录，正文不落），绝不影响回复；写不进（库都挂了）返回 False，
        由调用方按日志兜底。
        """
        outcome = RecallOutcome(
            request_id=request_id,
            items=[],
            dropped=[DroppedFact(fact_id="", text="", reason=reason)],
            candidates=0,
            semantic_available=False,
            scope_key=derive_scope(session_id).key,
            rendered="",
        )
        try:
            self._write_audit(owner_id=owner_id, outcome=outcome, request_id=request_id)
            if detail:
                logger.info(
                    "memory recall degraded reason=%s detail=%s", reason, detail[:160]
                )
            return True
        except Exception as exc:  # noqa: BLE001 - 观测面故障绝不阻断对话
            logger.warning(
                "memory recall degraded without audit reason=%s type=%s",
                reason,
                type(exc).__name__,
            )
            return False

    def _write_audit(
        self, *, owner_id: str, outcome: RecallOutcome, request_id: str
    ) -> bool:
        """落一条注入审计；返回是否真的写进去（降级留痕不许谎报成功）。"""
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
            return True
        except Exception as exc:  # noqa: BLE001 - 观测面失败绝不阻断召回
            logger.warning("memory bus audit write failed type=%s", type(exc).__name__)
            return False

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
        DEGRADED_REASON_BUS_RECALL_FAILED: "统一打分器这轮没工作（已退回按时间取最近几条，"
        "且可能混进与本轮无关的话）",
        DEGRADED_REASON_LEGACY_NEWEST_N: "统一打分器没开启（按时间取最近几条，"
        "与本轮话题无关的也可能被用上）",
        DEGRADED_REASON_MEMORY_LEG_FAILED: "记忆的一条来源腿这轮没读出来"
        "（只少一路内容，不是打分器故障）",
    }.get(reason, reason or "未采用")


# ---- 与既有 MemoryProvider 协议的适配 ----


class MemoryBusProvider:
    """总线召回器：满足 ``character/memory.MemoryProvider`` 协议（同名同参）。

    ``bus`` 属性是**装配层的接缝**（唯一读取路径 ``providers.build_memory_read_provider``
    用它确认「本轮打分器就是总线」并挂候选源/降级审计），不是第二条取数口：
    取数仍然只经本类的 ``retrieve``。
    """

    #: 本协议实现的取数口径标识（供装配层与观测面归因，勿当字符串自造第二套）。
    recall_mode = "memory_bus"

    def __init__(self, bus: MemoryBus) -> None:
        self._bus = bus

    @property
    def bus(self) -> MemoryBus:
        return self._bus

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

"""贴纸选图打分：主题相关性 × bot 心情 × 好感档 × 用户口味（goal-12 半 B）。

只打分、不碰存储、不碰网络、不读配置——纯函数件，输入是 ``MemeLibraryStore``
已经取好的候选行（含 ``description/emotion_tags/scene_tags/persona_hint/weight``）
加一份 :class:`StickerContext`，输出是「按分数降序、已淘汰不合格者」的候选表，
或由 :func:`select_sticker` 直接给出**唯一**那张（并原子占坑）。

四条口径钉死在代码里：

1. **不造第二套 taxonomy。** 主题词表全部来自既有真身：库自己的
   ``emotion_tags/scene_tags/persona_hint`` 字段、``meme_library._PRIORITY_HINTS``
   的人格/作品族词、``capabilities/meme_library.py`` 的吵闹词族（本件把那份
   词表收编为唯一真身，能力层改为 import 本件，副本数 1→1 而非 +1）、
   ``reactions/engine.py`` 的情绪意图词，以及配置项 ``bot_meme_library_prefer``。
   本件不新增任何标签名词。
2. **不合格 = 不发，不是硬凑。** 命中用户厌恶词 ⇒ 0 分淘汰；主题零重叠且
   好感档不够 ⇒ 0 分淘汰；全表淘汰或全部已发过 ⇒ ``select_sticker`` 返回
   ``None``，由调用方走各自的「没有表情」分支（**绝不回退成重发**）。
3. **相关性只认「同一词表的两侧重叠」。** 从本轮文本里挑出属于既有词表的词，
   与候选标签文本求交——两侧同源自洽，不做自由文本相似度，避免把「今天天气」
   和「开心」靠一个通用相似度模型硬连起来。
4. **确定性。** :func:`select_sticker` 按 (分数降序, 内容哈希升序) 取第一张可占坑者，
   不用 ``random`` ⇒ 同一库 + 同一历史 + 同一上下文 = 同一结果，可测可复盘。
   （无上下文的旧加权随机路径仍由 ``weighted_pick`` 保留，见该函数。）

心情阈值与 ``character/mood.py`` 的低落档同源（``_V_NEGATIVE``），改值需两处同步；
本件把「低落 ⇒ 收敛吵闹梗」从能力层的私有策略升成所有选图腿共用的打分因子。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

#: 心情低落判定阈值：与 ``domains/chat_reply/character/mood.py`` 的低落档
#: （``_V_NEGATIVE``）同源，**改值需两处同步**（旧副本住在能力层，本件为真身）。
MOOD_LOW_VALENCE = -0.25
#: 低落时对「吵闹梗」的乘性降权（软偏置，不是硬开关——与旧能力层语义一致）。
MOOD_NOISY_PENALTY = 0.35
#: 无主题信号（本轮没抽到任何词表词）时的中性相关度：可发，但排在有主题者之后。
NEUTRAL_RELEVANCE = 0.5
#: 主题零重叠时，好感档达到该值才允许（不认识的人只发明确对题的）。
DEFAULT_OFFTOPIC_MIN_TIER = 2
#: 命中用户印象标签（口味）的每一条加成与封顶条数。
TASTE_BONUS_PER_HIT = 0.15
TASTE_HIT_CAP = 3
#: 人格本命贴纸（守岸人本体）的乘性加成。
PERSONA_BONUS = 1.25


@dataclass(frozen=True)
class StickerContext:
    """一轮选图的语境：主题 / 心情 / 好感档 / 用户口味。

    全部可缺省——缺省即「无信号」，打分退化为中性档（不加分也不淘汰），
    这样未接入某一条腿（例如 poke 没有本轮文本）也不会整条链空转。
    """

    topic_terms: tuple[str, ...] = ()
    mood_valence: float | None = None
    affinity_tier: int | None = None
    liked_terms: tuple[str, ...] = ()
    disliked_terms: tuple[str, ...] = ()
    #: 参与诊断的可读理由（审计标签用，不含用户原文）。
    @property
    def has_topic_signal(self) -> bool:
        return bool(self.topic_terms)


@dataclass(frozen=True)
class ScoredSticker:
    content_sha256: str
    score: float
    candidate: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


# ------------------------------------------------------------------ 词表与文本


def candidate_text(candidate: dict[str, Any]) -> str:
    """候选行的可匹配文本：描述 + 情绪标签 + 场景标签 + 人格归属。

    字段集与 ``meme_library_listener.TAG_PROMPT`` 的输出契约一致（同一词表，
    不新增字段）；JSON 数组的方括号/引号按分隔符处理，不当词。
    """
    parts = [
        str(candidate.get("description", "") or ""),
        str(candidate.get("emotion_tags", "") or ""),
        str(candidate.get("scene_tags", "") or ""),
        str(candidate.get("persona_hint", "") or ""),
    ]
    return " ".join(parts).lower()


def _terms(terms: Iterable[str] | None) -> tuple[str, ...]:
    out: list[str] = []
    for term in terms or ():
        text = str(term or "").strip().lower()
        if text and text not in out:
            out.append(text)
    return tuple(out)


def topic_terms_from_text(
    text: str,
    *,
    vocabulary: Iterable[str],
    max_terms: int = 12,
) -> tuple[str, ...]:
    """本轮文本 → 命中既有词表的主题词（保序去重，上限 ``max_terms``）。

    只做「词表词是否出现在原文里」的子串判定：**不接受原文里的自由词**做主题词，
    所以两侧永远住在同一词表里；这也让「未打标的库」表现为「无主题信号」
    而不是「假装相关」。
    """
    haystack = " ".join(str(text or "").split()).lower()
    if not haystack:
        return ()
    hits: list[str] = []
    for term in _terms(vocabulary):
        if term and term in haystack and term not in hits:
            hits.append(term)
        if len(hits) >= max(1, int(max_terms)):
            break
    return tuple(hits)


def default_vocabulary(
    *,
    prefer: Iterable[str] = (),
    persona_terms: Iterable[str] = (),
    intent_terms: Iterable[str] = (),
    extra: Iterable[str] = (),
) -> tuple[str, ...]:
    """主题词表 = 配置 prefer ∪ 人格别名 ∪ 情绪意图词 ∪ 吵闹词族（全部既有真身）。

    ``persona_terms`` 由调用方从中央别名源注入（``shorekeeper_absorb.persona_alias_terms``），
    本件**不**硬写人名；吵闹词族直接 import 自己（同包，零副本）。
    """
    from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
        PRIORITY_HINT_TERMS,
    )

    collected: list[str] = []
    for source in (prefer, persona_terms, intent_terms, PRIORITY_HINT_TERMS, NOISY_MEME_TERMS, extra):
        for term in _terms(source):
            if term not in collected:
                collected.append(term)
    return tuple(collected)


#: 吵闹梗词族（真身在此；能力层 ``capabilities/meme_library.py`` 改 import 本件）。
NOISY_MEME_TERMS = (
    "搞笑",
    "沙雕",
    "整活",
    "鬼畜",
    "爆笑",
    "疯狂",
    "抽象",
    "玩梗",
    "兴奋",
    "吵闹",
)

#: 「像在闹」的判定：候选文本命中吵闹词族任一。
def is_noisy_text(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in NOISY_MEME_TERMS)


# ------------------------------------------------------------------ 打分


def relevance_score(
    context: StickerContext,
    text: str,
    *,
    offtopic_min_tier: int,
) -> float:
    """主题相关度 ∈ {0.0, NEUTRAL_RELEVANCE, 1.0}。

    * 本轮无主题信号 → 中性档（不加分、不淘汰）；
    * 有信号且候选标签与之重叠 → 1.0；
    * 有信号但零重叠 → 只有好感档够（熟人）才给中性档，否则 0.0 淘汰。
    """
    if not context.topic_terms:
        return NEUTRAL_RELEVANCE
    lowered = str(text or "").lower()
    if any(term in lowered for term in context.topic_terms):
        return 1.0
    tier = context.affinity_tier
    if isinstance(tier, int) and tier >= int(offtopic_min_tier):
        return NEUTRAL_RELEVANCE
    return 0.0


def score_sticker_candidate(
    candidate: dict[str, Any],
    context: StickerContext,
    *,
    persona_terms: Sequence[str] = (),
    offtopic_min_tier: int = DEFAULT_OFFTOPIC_MIN_TIER,
) -> tuple[float, float, str]:
    """单张候选打分 → ``(地板分, 排序分, 淘汰/降权理由代号)``。

    **两个分数不是一回事，地板只看第一个**：

    * ``gate = 库权重 × 主题相关度`` —— 合格性。地板（``min_relevance``）比的是它，
      所以被地板拦下的只有两类：库自己判「不算表情/高危」的（权重 0.25/0.0）与
      离题且不熟的（相关度 0.0）。
    * ``rank = gate × 心情 × 口味 × 本命`` —— 排序用。心情降权、口味加成、本命加成
      **一律不参与地板**：它们是倾向不是开关。旧能力层的 N4 语义（「全部吵闹也照发」）
      靠这条边界保住——否则「低落 × 中性档」= 0.175 会被地板吃掉，软偏置就成了硬开关。

    任一致命项（厌恶词、离题且不够熟、库权重≤0）两个分数都归零，排序也无从谈起。
    """
    text = candidate_text(candidate)
    try:
        weight = float(candidate.get("weight", 1.0) or 0.0)
    except (TypeError, ValueError):
        weight = 0.0
    if weight <= 0.0:
        return 0.0, 0.0, "weight_zero"
    relevance = relevance_score(context, text, offtopic_min_tier=offtopic_min_tier)
    if relevance <= 0.0:
        return 0.0, 0.0, "off_topic"
    gate = weight * relevance
    score = gate
    reason = ""
    disliked = _terms(context.disliked_terms)
    if disliked and any(term in text for term in disliked):
        return 0.0, 0.0, "disliked"
    if is_noisy_text(text) and context.mood_valence is not None:
        try:
            if float(context.mood_valence) <= MOOD_LOW_VALENCE:
                score *= MOOD_NOISY_PENALTY
                reason = "mood_muted"
        except (TypeError, ValueError):
            pass
    liked = _terms(context.liked_terms)
    if liked:
        hits = min(sum(1 for term in liked if term in text), TASTE_HIT_CAP)
        if hits:
            score *= 1.0 + TASTE_BONUS_PER_HIT * hits
            reason = f"{reason}+taste" if reason else "taste"
    lowered_persona = _terms(persona_terms)
    if lowered_persona and any(term in text for term in lowered_persona):
        score *= PERSONA_BONUS
        reason = f"{reason}+persona" if reason else "persona"
    return round(gate, 6), round(score, 6), reason


def rank_sticker_candidates(
    candidates: Iterable[dict[str, Any]],
    context: StickerContext,
    *,
    persona_terms: Sequence[str] = (),
    offtopic_min_tier: int = DEFAULT_OFFTOPIC_MIN_TIER,
    min_relevance: float = 0.35,
) -> list[ScoredSticker]:
    """打分 + 按 (分数降序, 内容哈希升序) 排序；``gate < min_relevance`` 不入表。

    地板比的是 **gate（库权重 × 主题相关度）**，不是加了心情/口味/本命之后的 rank
    分（理由见 :func:`score_sticker_candidate`：软偏置不许变成硬开关）。
    ``gate`` 里库权重已经打过折：缺省 1.0、本命 8.0，判非表情/NSFW≥0.8 会低到
    0/0.25，所以这一道同时兜住「离题但权重虚高」与「库自己判不算表情」两类候选。
    """
    scored: list[ScoredSticker] = []
    for candidate in candidates:
        sha = str(candidate.get("content_sha256", "") or "").strip().lower()
        gate, score, reason = score_sticker_candidate(
            candidate,
            context,
            persona_terms=persona_terms,
            offtopic_min_tier=offtopic_min_tier,
        )
        if gate < float(min_relevance):
            continue
        scored.append(ScoredSticker(content_sha256=sha, score=score, candidate=candidate, reason=reason))
    scored.sort(key=lambda item: (-item.score, item.content_sha256))
    return scored


def attribution_for(item: ScoredSticker, context: StickerContext) -> str:
    """把「为什么是这张」压成一段可落盘的归因代号串（S-STICKER-FINAL）。

    构成（全部是代号与分值，**零用户原文**——主题词来自既有词表、口味词是
    bot 自己的印象标签，昵称/聊天句子一律不进）::

        why=<打分理由代号>|topic=<≤3 个词表词>|tier=<好感档或->|mood=<valence 或->|score=<排序分>

    ``why`` 的取值域就是 :func:`score_sticker_candidate` 第三返回值
    （``mood_muted`` / ``taste`` / ``persona`` 的组合，空者记 ``plain``）。
    这段串进 ``meme_sends.reason`` 与门面审计标签，供事后回答
    「你刚为什么发这张」（本仓哲学：算了不落盘＝没做，先例 ``phases_ms``）。
    """
    bits = [f"why={item.reason or 'plain'}"]
    if context.topic_terms:
        bits.append("topic=" + ",".join(context.topic_terms[:3]))
    bits.append(f"tier={'-' if context.affinity_tier is None else context.affinity_tier}")
    bits.append(f"mood={'-' if context.mood_valence is None else round(float(context.mood_valence), 2)}")
    bits.append(f"score={item.score}")
    return "|".join(bits)


def claim_for_send(history: Any, sha: str, scope: str | None, reason: str) -> bool:
    """占坑调用兼容层：认识 ``reason`` 形参的新账本记归因，旧桩回退旧签名。

    与门面 ``_call_weighted_pick`` 同型理由——只对「签名不接受该关键字」这一种
    ``TypeError`` 回退；其余异常原样上抛（吞真 bug 比少记一条归因严重得多）。
    """
    try:
        return bool(history.try_claim(sha, scope=scope, reason=reason))
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        return bool(history.try_claim(sha, scope=scope))


def select_sticker(
    candidates: Iterable[dict[str, Any]],
    context: StickerContext,
    *,
    history: Any | None = None,
    scope: str | None = None,
    persona_terms: Sequence[str] = (),
    offtopic_min_tier: int = DEFAULT_OFFTOPIC_MIN_TIER,
    min_relevance: float = 0.35,
) -> ScoredSticker | None:
    """确定性选一张：**没有合格且没发过的就返回 None**（调用方不得重发）。

    占坑走 ``history.try_claim``（查+插同一事务同一锁），所以并发两条腿抢同一张时
    只有一条拿得到；拿不到就顺延下一名，全部落空返回 None。``history=None``
    退化为「不做反重复」的纯打分选择（测试/预览用），生产咽喉会一直带着账本。
    占坑成功的同时把 :func:`attribution_for` 的归因串记进账本（旧桩无该形参则
    回退旧签名，见 :func:`claim_for_send`）。
    """
    ranked = rank_sticker_candidates(
        candidates,
        context,
        persona_terms=persona_terms,
        offtopic_min_tier=offtopic_min_tier,
        min_relevance=min_relevance,
    )
    for item in ranked:
        if not item.content_sha256:
            # 身份缺失 = 无法保证不重发，宁可不发。
            continue
        if history is None:
            return item
        try:
            claimed = claim_for_send(history, item.content_sha256, scope, attribution_for(item, context))
        except Exception:  # noqa: BLE001 - 账本坏了不放行（重复比空手更糟）。
            return None
        if claimed:
            return item
    return None


# ------------------------------------------------------------------ 语境装配


def build_context(
    *,
    turn_text: str = "",
    vocabulary: Iterable[str] = (),
    mood_valence_fn: Callable[[], Any] | None = None,
    affinity_snapshot: dict[str, Any] | None = None,
    is_group_owner: bool = False,
) -> StickerContext:
    """把四条真身缝成语境：本轮文本 / ``BotMoodStore.snapshot().valence`` /
    ``DynamicAffinityStore.snapshot(sender_id)`` / 群主身份。

    任何一条读不到都退化为「无信号」，绝不抛异常——表情包是增益腿，
    增益腿不许把主回复拖下水。
    """
    topic_terms = topic_terms_from_text(turn_text, vocabulary=vocabulary)
    mood: float | None = None
    if mood_valence_fn is not None:
        try:
            mood = float(mood_valence_fn())
        except Exception:  # noqa: BLE001 - 心情读不到按中性。
            mood = None
    tier: int | None = None
    liked: tuple[str, ...] = ()
    if isinstance(affinity_snapshot, dict):
        raw_tier = affinity_snapshot.get("tier")
        if isinstance(raw_tier, int):
            tier = raw_tier
        liked = _terms([str(item) for item in (affinity_snapshot.get("tags") or [])][:12])
    if is_group_owner and tier is None:
        # 群主在本群的语气比陌生群友更放得开（既有人格层的常识），只抬一档口径，
        # 不改变「离题不发」的底线：给的仍是 DEFAULT_OFFTOPIC_MIN_TIER 的门槛档。
        tier = DEFAULT_OFFTOPIC_MIN_TIER
    disliked = _terms(affinity_snapshot.get("disliked_tags") or []) if isinstance(affinity_snapshot, dict) else ()
    return StickerContext(
        topic_terms=topic_terms,
        mood_valence=mood,
        affinity_tier=tier,
        liked_terms=liked,
        disliked_terms=disliked,
    )


__all__ = [
    "DEFAULT_OFFTOPIC_MIN_TIER",
    "MOOD_LOW_VALENCE",
    "MOOD_NOISY_PENALTY",
    "NEUTRAL_RELEVANCE",
    "NOISY_MEME_TERMS",
    "PERSONA_BONUS",
    "ScoredSticker",
    "StickerContext",
    "attribution_for",
    "build_context",
    "candidate_text",
    "claim_for_send",
    "default_vocabulary",
    "is_noisy_text",
    "rank_sticker_candidates",
    "relevance_score",
    "score_sticker_candidate",
    "select_sticker",
    "topic_terms_from_text",
]

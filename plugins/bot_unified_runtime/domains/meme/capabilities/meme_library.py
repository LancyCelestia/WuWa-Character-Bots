"""群聊表情包能力（bot.meme_library）：/偷表情 按权重随机发送入库表情。

权重策略（来源 meme_library.py）：
- VLM 判定非表情/普通图片降权；NSFW≥0.2 再降权，≥0.8 永不发送；
- 守岸人/岸宝 最优先，其次 鸣潮/战双帕弥什/库洛，再次 ACG，最后普通；
- 支持关键词/情绪标签过滤；带冷却时间防刷屏风控；
- N4 情绪档：bot 心情低落（valence ≤ -0.25，与 mood.py 低落档同阈值）时
  少推吵闹梗——命中吵闹标签的候选有限次重抽，全部吵闹也照发（只调
  倾向，绝不硬开关）；心情未接入/中性时行为不变。
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)

_COMMAND_RE = re.compile(
    # meme random(?![a-z0-9]) / steal meme(?![a-z0-9])：ASCII 短语右侧词边界
    # （wiki _alias_hit 先例），randomqq/memeqq 类胶合不触发（边界体检 ×2 清账）。
    # steal(?!\S)(?! meme[a-z0-9])：裸「steal」精确命中（帮助别名 'steal' 的
    # 实际触发，T-Spec T1.2）之外，再挡「steal memeqq」借道裸 steal 把胶合
    # 吃进 arg；stealing/steal a car 等不触发。
    # 全拼/缩写（T-Spec T1.5/T1.6 第二批）：toutu/toubiaoqing 族同音覆盖
    # 偷圖/偷图 简繁词；(?![a-z0-9]) 右边界同边界纪律（toutuq/tbqq 类胶合
    # 不触发）；sjbq 为 随机表情/随机表情包 同能力双词共享缩写（变体对口径
    # 启用一次）；bqsj/tbq 与 bot.meme 的 bqb 族前缀不同串、零冲突。
    r"^[/!！]?(?:偷表情|偷表情包|表情随机|随机表情|随机表情包|"
    r"表情抽签|表情隨機|隨機表情|隨機表情包|表情抽籤|"
    r"toubiaoqingbao(?![a-z0-9])|tbqb(?![a-z0-9])"
    r"|toubiaoqing(?![a-z0-9])|tbq(?![a-z0-9])"
    r"|suijibiaoqingbao(?![a-z0-9])|suijibiaoqing(?![a-z0-9])|sjbq(?![a-z0-9])"
    r"|biaoqingsuiji(?![a-z0-9])|bqsj(?![a-z0-9])"
    r"|biaoqingchouqian(?![a-z0-9])|bqcq(?![a-z0-9])"
    r"|toutu(?![a-z0-9])|tt(?![a-z0-9])"
    r"|memes? random(?![a-z0-9])|steal meme(?![a-z0-9])"
    r"|steal(?!\S)(?! meme[a-z0-9])|偷圖|偷图|偷表情包)\s*(?P<arg>.*)$",
    re.IGNORECASE,
)
_STATS_RE = re.compile(
    # 全拼/缩写（T-Spec T1.5/T1.6 第二批）：biaoqingku/biaoqingtongji 同
    # 表情库/表情统计；\s*$ 结构天然成界。memes? stats(?![a-z0-9]) 兜底
    # 「memes stats」复数误拼（同 _COMMAND_RE 的 memes? random 款）；
    # bot.meme 侧 meme/memes 双裸词均带 (?! (?:random|stats)\b) 负向前瞻，
    # 本变体不被表情生成抢匹配。
    r"^[/!！]?(?:表情库统计|biaoqingtongji(?![a-z0-9])|bqtj(?![a-z0-9])"
    r"|表情统计|表情库|biaoqingku(?![a-z0-9])|bqk(?![a-z0-9])"
    r"|memes? stats(?![a-z0-9]))\s*$",
    re.IGNORECASE,
)

# 冷却登记 LRU 上限：会话数极大时防止 dict 无界慢泄漏（审计 #30）。
_COOLDOWN_CAP = 4096

# ---- N4 情绪档：低落时少推吵闹梗 ----
# 阈值与吵闹词表的**真身**在 ``domains/meme/sources/meme_selection.py``（goal-12
# 半 B 收编：原来这份词表住在本文件，选图打分件要用就得复制第二份 ⇒ 反向收编，
# 能力层改为 import，副本数 2→1）。心情阈值与 character/mood.py 的低落档同口径，
# 改值需两处同步。
from plugins.bot_unified_runtime.domains.meme.sources import meme_selection

_MOOD_LOW_VALENCE = meme_selection.MOOD_LOW_VALENCE
_NOISY_MEME_TERMS = meme_selection.NOISY_MEME_TERMS
# 重抽是倾向不是硬开关：心情低落时对吵闹候选的最大重抽次数（含首次）。
_MOOD_REPICK_ATTEMPTS = 3


def _candidate_text(candidate: dict[str, Any]) -> str:
    return meme_selection.candidate_text(candidate)


def _is_noisy_meme(candidate: dict[str, Any]) -> bool:
    return meme_selection.is_noisy_text(_candidate_text(candidate))


def sticker_scope_for(mode: str, session_key: str) -> str | None:
    """作用域口径 → 传给存储层的 ``scope``。``None`` = 只记全局保留作用域。

    写死一件事：任何取值都**不会**比缺省更松。``global``/未识别值 ⇒ ``None``
    （只看全局账）；``session`` ⇒ 会话键（存储层把全局并进来判，所以是「更严一档」）。
    """
    if str(mode or "").strip().lower() == "session":
        text = " ".join(str(session_key or "").split()).strip()
        return text or None
    return None


def _call_weighted_pick(
    store: Any,
    *,
    keyword: str,
    nsfw_max: float,
    scope: str | None = None,
    context: Any | None = None,
    min_relevance: float | None = None,
    persona_terms: Sequence[str] = (),
) -> dict[str, Any] | None:
    """调 ``store.weighted_pick``，兼容不认识新形参的旧桩/旧实现。

    为什么要有这层绕行：本仓多处测试与内嵌替身按**旧两参数**签名定义
    （``weighted_pick(*, keyword, nsfw_max)``）。新参数全部可选，真库走全参路径；
    只对「签名不接受该关键字」这一种 ``TypeError`` 回退，其余异常原样上抛
    ——否则就是把真 bug 吞成降级。
    """
    attempts: list[dict[str, Any]] = [
        {
            "keyword": keyword,
            "nsfw_max": nsfw_max,
            "scope": scope,
            "context": context,
            "min_relevance": min_relevance,
            "persona_terms": persona_terms,
        },
        {"keyword": keyword, "nsfw_max": nsfw_max, "scope": scope},
        {"keyword": keyword, "nsfw_max": nsfw_max},
    ]
    for index, kwargs in enumerate(attempts):
        try:
            if index:
                # 回退到不带 context 的旧签名 ⇒ 反重复仍在（store 内部默认作用域）。
                pass
            return store.weighted_pick(**kwargs)
        except TypeError as exc:
            text = str(exc)
            if "unexpected keyword argument" not in text or index == len(attempts) - 1:
                raise
    return None


def select_sticker_for_turn(
    store: Any,
    *,
    turn_text: str = "",
    session_key: str = "",
    sender_id: str = "",
    config: Any | None = None,
    mood_valence_fn: Callable[[], float] | None = None,
    affinity_snapshot: dict[str, Any] | None = None,
    is_group_owner: bool = False,
    extra_topic_terms: Sequence[str] = (),
) -> tuple[dict[str, Any] | None, list[str]]:
    """一轮对话/一次戳一戳该发哪张贴纸：**主题 × 人格 × 口味 × 心情**四路合一。

    这是给装配层（根 ``__init__.py``）的唯一公共入口——它自己不再拼判据。
    返回 ``(候选字典或 None, 审计标签)``；``None`` 的唯一含义是「没有合适且没
    发过的」，调用方必须走「不发贴纸」分支（戳一戳回退固定话术、聊天回退纯文本），
    **不允许**回退成随便发一张。

    四条腿的真身各在哪里：
    * 主题 = 本轮文本 ∩ 既有词表（``meme_selection.default_vocabulary``：prefer ∪
      人格别名 ∪ 情绪意图 ∪ 本命族 ∪ 吵闹族），不引入自由词；
    * 人格 = 候选命中她的别名 ⇒ ``PERSONA_BONUS``，且本命图本就吃 ``_PRIORITY_HINTS`` 8.0；
    * 口味 = ``DynamicAffinityStore.snapshot(sender_id)["tags"]``（正向印象加成；
      **负向印象标签一票否决**——正负劈分判据派生自 affinity 真身规则表，
      见 ``meme_selection.negative_impression_tags``）；
    * 心情/好感 = ``BotMoodStore`` 的 valence 与好感档（低档只发明确对题的）。
    """
    if store is None:
        return None, ["meme_sticker", "no_store"]
    persona_terms = meme_selection_default_persona_terms(config)
    vocabulary = meme_selection.default_vocabulary(
        prefer=list(getattr(config, "bot_meme_library_prefer", []) or []),
        persona_terms=persona_terms,
        intent_terms=intent_vocabulary_terms(),
        extra=extra_topic_terms,
    )
    context = meme_selection.build_context(
        turn_text=turn_text,
        vocabulary=vocabulary,
        mood_valence_fn=mood_valence_fn,
        affinity_snapshot=affinity_snapshot,
        is_group_owner=is_group_owner,
    )
    nsfw_max = float(getattr(config, "bot_meme_library_nsfw_max", 0.2) or 0.2)
    min_relevance = getattr(config, "bot_meme_relevance_min", None)
    picked = _call_weighted_pick(
        store,
        keyword="",
        nsfw_max=nsfw_max,
        scope=sticker_scope_for(
            str(getattr(config, "bot_meme_sticker_scope_mode", "global") or "global"),
            session_key,
        ),
        context=context,
        min_relevance=(float(min_relevance) if min_relevance is not None else None),
        persona_terms=persona_terms,
    )
    tags = ["meme_sticker", "sent" if picked else "none"]
    if context.topic_terms:
        tags.append("topic:" + ",".join(context.topic_terms[:4]))
    if context.affinity_tier is not None:
        tags.append(f"tier:{context.affinity_tier}")
    if sender_id and not context.liked_terms:
        tags.append("taste:none")
    if picked:
        # 归因（S-STICKER-FINAL）：把「选它的理由代号」随结果一起交回调用方，
        # 账本里已存全串（meme_sends.reason），这里给审计标签一份可贴的短形态
        # （与 "tier:3"/"topic:开心" 同式；理由段内逗号换成下划线防分段歧义）。
        why_code = str(picked.get("sticker_reason", "") or "").split("|", 1)[0]
        if why_code.startswith("why="):
            tags.append("why:" + why_code[4:].replace(",", "_"))
    return picked, tags


def meme_selection_default_persona_terms(config: Any) -> tuple[str, ...]:
    """她的别名（经中央别名口，本文件零硬写人名）。"""
    from plugins.bot_unified_runtime.domains.meme.sources.shorekeeper_absorb import (
        persona_subject_terms,
    )

    return persona_subject_terms(config)


def intent_vocabulary_terms() -> tuple[str, ...]:
    """情绪意图词表：直接借 ``reactions/engine`` 的那一份真身（不复制常量）。"""
    from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
        reaction_meme_intent_vocabulary,
    )

    return reaction_meme_intent_vocabulary()


def _pick_with_mood(
    store: Any,
    *,
    keyword: str,
    nsfw_max: float,
    mood_muted: bool,
    scope: str | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    """加权挑选；心情低落时对吵闹候选做有限次重抽（软偏置）。

    返回 (候选|None, 是否发生过吵闹回避)。候选耗尽/全部吵闹时照常返回，
    绝不因情绪档把空手结果放大。注意「耗尽」的语义在 goal-12 之后已经是
    **「没发过的耗尽」**——反重复在 ``store.weighted_pick`` 内部生效，所以
    这里拿到的 ``None`` 可能是「库里有图但都发过了」，文案侧据此区分。
    """
    picked = _call_weighted_pick(store, keyword=keyword, nsfw_max=nsfw_max, scope=scope)
    if not mood_muted or picked is None or not _is_noisy_meme(picked):
        return picked, False
    avoided = False
    for _ in range(_MOOD_REPICK_ATTEMPTS - 1):
        alternative = _call_weighted_pick(
            store, keyword=keyword, nsfw_max=nsfw_max, scope=scope
        )
        if alternative is None:
            break
        if not _is_noisy_meme(alternative):
            return alternative, True
        avoided = True
    return picked, avoided


def is_meme_library_command(text: str) -> bool:
    stripped = (text or "").strip()
    return _COMMAND_RE.match(stripped) is not None or _STATS_RE.match(stripped) is not None


def parse_meme_library_command(text: str) -> tuple[str, str]:
    """返回 (动作, 参数)。动作：pick / stats。"""
    stripped = (text or "").strip()
    match = _STATS_RE.match(stripped)
    if match:
        return "stats", ""
    match = _COMMAND_RE.match(stripped)
    if not match:
        raise ValueError("not a meme library command")
    return "pick", (match.group("arg") or "").strip()


def build_meme_library_capability(
    store: Any,
    config: Any | None = None,
    *,
    mood_valence_fn: Callable[[], float] | None = None,
) -> Any:
    cooldown: OrderedDict[str, float] = OrderedDict()
    cooldown_seconds = int(getattr(config, "bot_meme_library_cooldown_seconds", 20) or 20)
    nsfw_max = float(getattr(config, "bot_meme_library_nsfw_max", 0.2) or 0.2)
    # 反重复作用域口径（缺省 global=本机发过即不再发）。"session" 只是**再加**
    # 一本会话账（判定取并集），永远不会比 global 更松——写反了就等于给了复发的口子。
    scope_mode = str(getattr(config, "bot_meme_sticker_scope_mode", "global") or "global").strip().lower()

    def _mood_muted() -> bool:
        """bot 心情是否低落到该收敛语气档；未接入/读取失败一律 False。"""
        if mood_valence_fn is None:
            return False
        try:
            return float(mood_valence_fn()) <= _MOOD_LOW_VALENCE
        except Exception:  # noqa: BLE001 - 心情读取失败按中性处理。
            return False

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        try:
            action, arg = parse_meme_library_command(message.plain_text)
        except ValueError:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme_library",
                kind="text",
                body="用法：偷表情 [关键词|情绪标签|私聊]；表情库统计 查看数量。",
                audit_tags=["meme_library", "usage"],
            )
        if action == "stats":
            stats = store.stats()
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme_library",
                kind="text",
                title="表情库",
                body=(
                    f"已收藏 {stats['total']} 张，累计发送 {stats['used_total']} 次，"
                    f"高危拦截 {stats['nsfw_blocked']} 张。"
                ),
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["meme_library", "stats"],
            )

        # 冷却：同一会话防刷屏，避免 QQ 风控。
        key = f"{message.session_id}:{message.sender_id}"
        now = time.monotonic()
        # 有界化（审计重发现）：会话键无界增长，超阈值先清过期再裁最旧。
        if len(cooldown) > 512:
            for stale in [k for k, ts in cooldown.items() if now - ts >= cooldown_seconds]:
                cooldown.pop(stale, None)
            while len(cooldown) > 512:
                cooldown.popitem(last=False)
        if key in cooldown:
            cooldown.move_to_end(key)
            if now - cooldown[key] < cooldown_seconds:
                remaining = int(cooldown_seconds - (now - cooldown[key])) + 1
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.meme_library",
                    kind="text",
                    # 审查 Q-03：失败/限流类文案统一去语气符「～」（守岸人语气
                    # 温和但不拖尾音，与 user_copy.py 池内句式口径一致）。
                    body=f"表情包还在冷却中，请 {remaining} 秒后再来偷。",
                    risk_level=RiskLevel.LOW,
                    privacy_level=PrivacyLevel.PERSONAL,
                    audit_tags=["meme_library", "cooldown"],
                )

        keyword = "" if arg.lower() in {"私聊", "私聊我", "private", "私"} else arg
        picked, avoided_noisy = _pick_with_mood(
            store,
            keyword=keyword,
            nsfw_max=nsfw_max,
            mood_muted=_mood_muted(),
            scope=sticker_scope_for(scope_mode, key),
        )
        if picked is None:
            # 空手有两种真因：库里没图 / 有图但**都发过了**（反重复在咽喉生效）。
            # 文案必须区分——否则她把「我已经发过了」听成「你得再发我几张」。
            # 判定失败一律退回旧文案（诚实但不精确），绝不因此抛异常。
            remaining = -1
            try:
                remaining = int(
                    store.eligible_count(
                        keyword=keyword,
                        nsfw_max=nsfw_max,
                        scope=sticker_scope_for(scope_mode, key),
                    )
                )
            except Exception:  # noqa: BLE001 - 计数是解释性附加信息，读不到就算了。
                remaining = -1
            exhausted = remaining == 0
            body = (
                "能配得上这句话的表情，守岸人都发过一遍了。再说一张也不太合适，"
                "就不重复糊弄你。"
                if exhausted
                else "表情库还是空的（或没有匹配的表情）。多发点图给守岸人收藏吧。"
            )
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme_library",
                kind="text",
                # 审查 Q-04：自称统一第三人称「守岸人」（原为第一人称自称，旧句已废）。
                # 审查 Q-03：失败类文案去语气符「～」（正常发送回执「给你偷来一张
                # 表情～」属正常对话类，不在本项范围，保留原样）。
                body=body,
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["meme_library", "all_sent" if exhausted else "empty"],
            )
        cooldown[key] = now
        cooldown.move_to_end(key)
        while len(cooldown) > _COOLDOWN_CAP:
            cooldown.popitem(last=False)
        tags = ["meme_library", "pick", f"weight:{picked.get('weight')}"]
        if str(picked.get("sticker_reason", "") or "").startswith("why=random"):
            tags.append("why=random")
        if avoided_noisy:
            tags.append("mood_muted")
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.meme_library",
            kind="mixed",
            title="表情包",
            body="给你偷来一张表情～",
            images=[{"file": str(picked["path"])}],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=tags,
        )

    return capability

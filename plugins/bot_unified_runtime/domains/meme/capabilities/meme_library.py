"""群聊表情包能力（bot.meme_library）：/偷表情 按权重随机发送入库表情。

权重策略（来源 meme_library.py）：
- VLM 判定非表情/普通图片降权；NSFW≥0.2 再降权，≥0.8 永不发送；
- 守岸人/岸宝 最优先，其次 鸣潮/战双帕弥什/库洛，再次 ACG，最后普通；
- 支持关键词/情绪标签过滤；带冷却时间防刷屏风控；
- N4 情绪档：bot 心情低落（valence ≤ -0.25，与 mood.py 低落档同阈值）时
  少推吵闹梗——命中吵闹标签的候选有限次重抽，全部吵闹也照发（只调
  倾向，绝不硬开关）；心情未接入/中性时行为不变。
- 审批面（S-MEME2-REVIEW 2026-09-29，需求 12）：`/表情库 待审` 看队列、
  `/表情库 审批 通过|拒绝 <编号前缀>` 落子——单面证据的图只停在待审档，
  进本命池必须由管理员点头（审核制 propose→approve→render 的 approve 腿）。
- 表情册面（S-ALBUM 2026-09-30）：`/表情册 [统计|重扫|查重|入册 <编号前缀>]` 是管理员
  的册账——逐册数图、失配路径重链、跨册同名查重、把库里的行落到人格册目录。四个动作
  都先过 admin 门；登记根没配上＝诚实缺席，绝不自己造目录、绝不越出容器。
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)

if TYPE_CHECKING:  # 仅注解：运行期仍由 meme_sentiment_type() 延迟取，不破包内环
    from plugins.bot_unified_runtime.domains.meme.reactions.sentiment_selector import (
        SentimentVerdict,
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
_REVIEW_RE = re.compile(
    # S-MEME2-REVIEW（2026-09-29，需求 12）审批面的两枚触发形：
    # 「表情库 待审」＝只读队列；「表情库 审批 通过|拒绝 <md5 前缀>」＝落子。
    # 命令前缀可省（裸「待审」也认）——管理员在群里打全字的成本不该换不来一条读数。
    # 串必须**开头**就是 待审/审批（前缀之后），所以「偷表情 待审」这类带关键词的
    # 抽取仍走 pick 腿，不被本形抢匹配（test_meme_conflict_fix 的唯一性锁靠这条）。
    r"^[/!！]?(?:表情库统计|表情统计|表情库|biaoqingtongji(?![a-z0-9])|bqtj(?![a-z0-9])"
    r"|biaoqingku(?![a-z0-9])|bqk(?![a-z0-9]))?\s*(?:待审|审批)\s*(?P<arg>.*)$",
    re.IGNORECASE,
)
_ALBUM_RE = re.compile(
    # S-ALBUM（2026-09-30）表情册面：行首只认「表情册／表情相冊」两形（简繁成对，
    # 同 _COMMAND_RE 的 隨機/随机 口径）＋全拼一枚（同 表情库 那面 biaoqingku/bqk 的
    # 口径；缩写 bqc 有意不收——`bqcq`（抽表情）已占前缀，收进来就是抢串）。
    # 动作词 统计/重扫/查重/入册 **不进正则**——
    # 交给 ``_ALBUM_ACTION_WORDS`` 查表：正则里堆动作词会长出第二张动作词表，
    # 而 ``/bot help`` 侧的触发词真相源另有其人（echo 的 _HELP_ENTRIES，规则 10）。
    # 参数 ``(?P<arg>.*)$``：裸「表情册」⇒ 空串＝统计（只读腿当默认，误触零代价）。
    # 不与 stats/review 抢串：那两族的词面是「表情库/表情统计」，与本形不同串。
    r"^[/!！]?(?:表情册|表情相冊|biaoqingce(?![a-z0-9]))\s*(?P<arg>.*)$",
    re.IGNORECASE,
)

# 冷却登记 LRU 上限：会话数极大时防止 dict 无界慢泄漏（审计 #30）。
_COOLDOWN_CAP = 4096

# ---- N4 情绪档：低落时少推吵闹梗 ----
# 阈值与吵闹词表的**真身**在 ``domains/meme/sources/meme_selection.py``（goal-12
# 半 B 收编：原来这份词表住在本文件，选图打分件要用就得复制第二份 ⇒ 反向收编，
# 能力层改为 import，副本数 2→1）。心情阈值与 character/mood.py 的低落档同口径，
# 改值需两处同步。
from plugins.bot_unified_runtime.domains.meme.sources import (
    meme_selection,
    sticker_send_routing,
)

_MOOD_LOW_VALENCE = meme_selection.MOOD_LOW_VALENCE
_NOISY_MEME_TERMS = meme_selection.NOISY_MEME_TERMS
# 重抽是倾向不是硬开关：心情低落时对吵闹候选的最大重抽次数（含首次）。
_MOOD_REPICK_ATTEMPTS = 3

# ---- S-STICKER 情感判定腿（2026-09-28）：看过 bot 实际回复内容再选贴 ----
# 哨兵：区分「调用方没表态（内部自行判定）」与「调用方明确传入 None/判定结果」。
_SENTIMENT_UNSET = object()


def meme_sentiment_type() -> type[SentimentVerdict]:
    """情感判定结果的类对象（延迟取，避免模块级 import 造成包内环）。

    返回值带 ``type[SentimentVerdict]`` 精度是必需项而非装饰：调用侧
    ``isinstance(resolved_sentiment, meme_sentiment_type())`` 只能按返回值的
    参数化形态收窄变量，写成裸 ``type`` 会把它收窄成 ``object``，于是判定结果
    本体上**确实存在**的 ``positive_terms()`` / ``avoid_terms`` 两枚真身成员被报成
    「object has no attribute」。运行时一字未动：函数体照旧延迟 import、返回同一个
    类对象，收窄只影响静态判读。
    """
    from plugins.bot_unified_runtime.domains.meme.reactions.sentiment_selector import (
        SentimentVerdict,
    )

    return SentimentVerdict


def _resolve_meme_sentiment(
    config: Any,
    *,
    user_text: str,
    reply_text: str,
    session_key: str,
    sentiment_classifier: Callable[..., Any] | None,
) -> Any | None:
    """调用情感判定（缺省走真 LLM 腿）；任何异常一律 ``None``（不贴）。

    本函数被 ``select_sticker_for_turn`` 调用，而后者在根装配里已由
    ``asyncio.to_thread`` 下放线程池执行（见 ``_maybe_send_reaction_meme``），
    故此处按同步阻塞调用真判定腿是安全的。
    """
    if sentiment_classifier is not None:
        try:
            return sentiment_classifier(
                config, user_text=user_text, reply_text=reply_text, session_key=session_key
            )
        except Exception:  # noqa: BLE001 - 注入腿抛错＝不贴。
            return None
    try:
        from plugins.bot_unified_runtime.domains.meme.reactions.sentiment_selector import (
            classify_sticker_sentiment,
        )

        return classify_sticker_sentiment(
            config, user_text=user_text, reply_text=reply_text, session_key=session_key
        )
    except Exception:  # noqa: BLE001 - 判定腿缺席＝不贴。
        return None


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


def _locked_sticker_subdirs(
    config: Any | None, affinity_snapshot: dict[str, Any] | None
) -> tuple[str, ...]:
    """S4 好感档联动：档位不够 ⇒ 锁定「私藏」类子目录（判据真身在此，单读点）。

    * 子目录名与解锁档位都出自配置（``bot_sticker_private_subdir`` /
      ``bot_sticker_private_min_tier``）；子目录名空串＝功能整体关闭。
    * 档位读好感快照的 ``tier`` 格（8 档体系，值大＝更亲近）；快照缺席或档位读
      不出 ⇒ **按未解锁算**（fail-closed：私藏就当没有这批图，绝不猜档）。
    """
    subdir = str(getattr(config, "bot_sticker_private_subdir", "") or "").strip() if config is not None else ""
    if not subdir:
        return ()
    try:
        min_tier = int(getattr(config, "bot_sticker_private_min_tier", 7) or 7)
    except (TypeError, ValueError):
        min_tier = 7
    tier: int | None = None
    if isinstance(affinity_snapshot, dict):
        try:
            raw = affinity_snapshot.get("tier")
            tier = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            tier = None
    if tier is not None and tier >= min_tier:
        return ()
    return (subdir,)


def _packs_prefer_tags(
    *,
    turn_text: str,
    reply_text: str,
    extra_topic_terms: Sequence[str],
    provided_sentiment: Any,
) -> tuple[str, ...]:
    """S1 语境标签：本轮文本里命中的情绪词＋调用方点名的主题词＋已判定的正向情感词。

    只做**零成本**的词面匹配（词表＝``intent_vocabulary_terms`` 既有真身，不开第二份），
    绝不为贴纸发问 LLM；命中词与册内子目录名互含即偏置（真身在
    ``sticker_packs.pick_sticker`` 的探查序重排）。用户按这些词给册建子目录，出图
    就贴语境；没建子目录＝标签落空＝整册原序，行为与旧版逐字相同。
    """
    tags = [str(term).strip() for term in extra_topic_terms]
    text = f"{turn_text or ''}\n{reply_text or ''}"
    if text.strip():
        for term in intent_vocabulary_terms():
            word = str(term or "").strip()
            if word and word in text:
                tags.append(word)
    if provided_sentiment is not None and provided_sentiment is not _SENTIMENT_UNSET:
        try:
            tags.extend(str(term).strip() for term in provided_sentiment.positive_terms())
        except Exception as exc:  # noqa: BLE001 - 情感词读不出＝标签缺席，绝不影响选图。
            logger.debug("packs prefer tags from sentiment unavailable: %s", type(exc).__name__)
    return tuple(dict.fromkeys(tag for tag in tags if tag))


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
    reply_text: str = "",
    sentiment: Any | None = _SENTIMENT_UNSET,
    sentiment_classifier: Callable[..., Any] | None = None,
    pool_policy: str = sticker_send_routing.POOL_POLICY_PACKS_THEN_LIBRARY,
    pool_seed: str = "",
    persona_albums: Sequence[str] = (),
) -> tuple[dict[str, Any] | None, list[str]]:
    """一轮对话/一次戳一戳该发哪张贴纸：**先贴纸池、后表情库**，四路打分在库腿里。

    这是给装配层（根 ``__init__.py``）的唯一公共入口——它自己不再拼判据。
    返回 ``(候选字典或 None, 审计标签)``；``None`` 的唯一含义是「没有合适且没
    发过的」，调用方必须走「不发贴纸」分支（戳一戳回退固定话术、聊天回退纯文本），
    **不允许**回退成随便发一张。

    S-STICKER-POOLS（2026-09-29）池子路由（``pool_policy`` 两态，判据真身在
    ``domains/meme/sources/sticker_send_routing.py``）：

    * ``packs_then_library``（缺省＝指令路口径）：管理员登记的贴纸池在场且拿得出
      东西 ⇒ 直接用池子那张；池子不在场（开关关掉 ⇒ ``list_sticker_images`` 交回
      空）或这一张挑不出来 ⇒ 落到下面既有表情库加权腿。
    * ``packs_only``（**主动腿专用**：P3 情绪时刻发图、戳一戳 ``meme`` 臂）：只准
      用贴纸池，挑不出就 ``(None, [... "sticker_pool:none"])``——**绝不回退吸收池**。
      这一条是用户点名的红线：现网「没命令自己甩图」甩出去的正是别人群里的截图，
      主动腿一旦允许兜底，那条红线当场作废。

    四条腿的真身各在哪里（**贴纸池腿不走这四条**：池子是管理员手挑的 curated 盘，
    没有 VLM 标签可打分，走 ``pick_sticker`` 自己的轮换/去重账）：
    * 主题 = 本轮文本 ∩ 既有词表（``meme_selection.default_vocabulary``：prefer ∪
      人格别名 ∪ 情绪意图 ∪ 本命族 ∪ 吵闹族），不引入自由词；
    * 人格 = 候选命中她的别名 ⇒ ``PERSONA_BONUS``，且本命图本就吃 ``_PRIORITY_HINTS`` 8.0；
    * 口味 = ``DynamicAffinityStore.snapshot(sender_id)["tags"]``（正向印象加成；
      **负向印象标签一票否决**——正负劈分判据派生自 affinity 真身规则表，
      见 ``meme_selection.negative_impression_tags``）；
    * 心情/好感 = ``BotMoodStore`` 的 valence 与好感档（低档只发明确对题的）。

    S-STICKER（2026-09-28）第五条腿＝**看过 bot 实际回复内容的语义判定**
    （用户点名「报喜却贴大哭」的根治）：调用方把本轮 bot 回复文本经 ``reply_text``
    传进来后，交给 ``reactions/sentiment_selector`` 判情感，据此：
    * 正向：把该情感的表情词并入主题面（对题贴纸优先）；
    * 回避：把该场合禁忌的表情词并入一票否决面（复用既有 disliked 真身，不开第二
      份选贴器）——报喜场合的哭脸/丧脸由此被硬否决；
    * fail-safe：判定失败/超时/枚举外 ⇒ 返回 ``(None, ...)``＝本轮不贴（错配比不贴更糟）；
      conflict 等无正向情感的场合同样不贴。``reply_text`` 为空＝时序未到，退回旧四路
      行为，绝不为此发问 LLM（成本门）。``sentiment`` 直接传入判定结果可跳过内部发问
      （测试注入用），缺省由内部按 ``reply_text`` 判定。
    """
    # ---- 池子路由：读点收在 sticker_send_routing，本件不拼第二判据口 ----
    # 只扫一次池：``pick_from_packs`` 自己就能区分「拿得出」与「拿不出」，先在
    # 这里再调一次 ``pool_available`` 等于每轮多盘一遍目录（P3 在热链路上）。
    packs_only = pool_policy == sticker_send_routing.POOL_POLICY_PACKS_ONLY
    pack_path = sticker_send_routing.pick_from_packs(
        config,
        session_key=session_key,
        seed=pool_seed or session_key,
        # 主动腿宁可不发也不刷屏；指令路（她开口要）整库都在窗内时退「最久没发」那张。
        allow_exhausted=not packs_only,
        # 人格分册（2026-09-29 用户裁定）：只准从现役人格同名子目录取，缺册＝拿不到。
        persona_names=tuple(persona_albums or ()),
        # S1 语境标签：命中子目录名的候选排前（零成本词面匹配，判据在池子那侧）。
        prefer_tags=_packs_prefer_tags(
            turn_text=turn_text,
            reply_text=reply_text,
            extra_topic_terms=extra_topic_terms,
            provided_sentiment=sentiment,
        ),
        # S4 好感档联动：档位不够 ⇒ 私藏类子目录整条锁死（fail-closed）。
        locked_subdirs=_locked_sticker_subdirs(config, affinity_snapshot),
    )
    if pack_path is not None:
        sticker_send_routing.remember_pool(session_key, sticker_send_routing.POOL_STICKER_PACKS)
        return (
            {"path": str(pack_path), "pool": sticker_send_routing.POOL_STICKER_PACKS},
            [
                "meme_sticker",
                "sent",
                sticker_send_routing.pool_audit_tag(sticker_send_routing.POOL_STICKER_PACKS),
            ],
        )
    if packs_only:
        # 主动腿到此为止：贴纸池挑不出＝不发，绝不端吸收池的图兜底。
        sticker_send_routing.remember_pool(session_key, sticker_send_routing.POOL_NONE)
        return None, [
            "meme_sticker",
            "none",
            sticker_send_routing.pool_audit_tag(sticker_send_routing.POOL_NONE),
        ]

    if store is None:
        return None, ["meme_sticker", "no_store"]

    resolved_sentiment = sentiment
    sentiment_engaged = sentiment is not _SENTIMENT_UNSET or (
        bool(reply_text) and bool(getattr(config, "bot_reactions_sentiment_enabled", True))
    )
    if sentiment is _SENTIMENT_UNSET:
        resolved_sentiment = None
        if reply_text and bool(getattr(config, "bot_reactions_sentiment_enabled", True)):
            resolved_sentiment = _resolve_meme_sentiment(
                config,
                user_text=turn_text,
                reply_text=reply_text,
                session_key=session_key,
                sentiment_classifier=sentiment_classifier,
            )
    if sentiment_engaged:
        # 判定不中（失败/超时/枚举外）＝本轮不贴；conflict 等无正向情感的场合同样不贴。
        # 二者都绝不回退成「随便挑一张」——错配比缺席更糟（用户红线）。
        if resolved_sentiment is None:
            return None, ["meme_sticker", "sentiment_none"]
        if not resolved_sentiment.positive_terms():
            return None, ["meme_sticker", "sentiment_avoid", "sentiment:" + str(resolved_sentiment.label)]

    forced_topic_terms = tuple(extra_topic_terms)
    forced_avoid_terms: tuple[str, ...] = ()
    if isinstance(resolved_sentiment, meme_sentiment_type()):
        forced_topic_terms = tuple(dict.fromkeys([*forced_topic_terms, *resolved_sentiment.positive_terms()]))
        forced_avoid_terms = tuple(resolved_sentiment.avoid_terms)

    persona_terms = meme_selection_default_persona_terms(config)
    vocabulary = meme_selection.default_vocabulary(
        prefer=list(getattr(config, "bot_meme_library_prefer", []) or []),
        persona_terms=persona_terms,
        intent_terms=intent_vocabulary_terms(),
        extra=[*forced_topic_terms],
    )
    context = meme_selection.build_context(
        turn_text=turn_text,
        vocabulary=vocabulary,
        mood_valence_fn=mood_valence_fn,
        affinity_snapshot=affinity_snapshot,
        is_group_owner=is_group_owner,
        extra_topic_terms=forced_topic_terms,
        extra_avoid_terms=forced_avoid_terms,
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
    if resolved_sentiment is not None and resolved_sentiment is not _SENTIMENT_UNSET:
        tags.append("sent:" + str(getattr(resolved_sentiment, "label", "none")))
    if context.topic_terms:
        tags.append("topic:" + ",".join(context.topic_terms[:4]))
    if context.affinity_tier is not None:
        tags.append(f"tier:{context.affinity_tier}")
    if sender_id and not context.liked_terms:
        tags.append("taste:none")
    if picked:
        why_code = str(picked.get("sticker_reason", "") or "").split("|", 1)[0]
        if why_code.startswith("why="):
            tags.append("why:" + why_code[4:].replace(",", "_"))
    # 审计轨：落到库腿时也要留名——「这一张来自哪个池」必须能从标签里读出来，
    # 否则「贴纸池接线了没有」只能靠猜（本仓最贵的一种假绿）。
    library_pool = (
        sticker_send_routing.POOL_MEME_LIBRARY if picked else sticker_send_routing.POOL_NONE
    )
    tags.append(sticker_send_routing.pool_audit_tag(library_pool))
    sticker_send_routing.remember_pool(session_key, library_pool)
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
    return (
        _COMMAND_RE.match(stripped) is not None
        or _STATS_RE.match(stripped) is not None
        or _REVIEW_RE.match(stripped) is not None
        or _ALBUM_RE.match(stripped) is not None
    )


def parse_meme_library_command(text: str) -> tuple[str, str]:
    """返回 (动作, 参数)。动作：album / pick / stats / review。"""
    stripped = (text or "").strip()
    # 册面**先判**：它以「表情册」行首独占，与其余三族词面互斥，放在最前只表达
    # 「这条串归册面管」，不改变任何旧串的归属（表情库/表情统计/偷表情 照旧）。
    album = _ALBUM_RE.match(stripped)
    if album:
        return "album", _parse_album_arg(album.group("arg") or "")
    # 审批形**先判**，再判 stats：`_STATS_RE` 末尾钉着 `\s*$`，「表情统计 审批 通过 1abcd」
    # 这种带尾巴的串过了 stats 只会整条 ValueError——优先级写在这里是**功能项**不是风格
    # （锁 tests/test_meme_persona_review_queue.py::test_review_command_parses_as_action）。
    review = _REVIEW_RE.match(stripped)
    if review:
        return "review", (review.group("arg") or "").strip()
    match = _STATS_RE.match(stripped)
    if match:
        return "stats", ""
    match = _COMMAND_RE.match(stripped)
    if not match:
        raise ValueError("not a meme library command")
    return "pick", (match.group("arg") or "").strip()


def _parse_album_arg(raw: str) -> str:
    """把「表情册」后面那串折成 ``<动作码> <参数>``（裸命令＝``stats``）。

    首词查 ``_ALBUM_ACTION_WORDS``；**查不到也一律落回 stats**（只读腿）——册面只开
    重扫/查重/入册三枚写口，读侧多同义词不扩大写面，这一条与审批面「首词不是落子
    动词就走只读腿」同构。全角空格先折成半角再切：QQ 里输入法带的全角空格很常见。
    """
    text = " ".join(str(raw or "").replace("\u3000", " ").split())
    if not text:
        return "stats"
    head, _, payload = text.partition(" ")
    action = _ALBUM_ACTION_WORDS.get(head.lower(), _ALBUM_ACTION_WORDS.get(head, "stats"))
    return f"{action} {payload}".strip()


# ---- S-MEME2-REVIEW（2026-09-29，需求 12）：本命准入的审批面 ----
# 判据本体不住这里（`sources/persona_review.py` 那张双证据表 + `sources/meme_library.py`
# 的 set_review_state/reject_review/list_review/match_review_key 四枚执法口）。本面只做
# 「命令 → 判据 → 回执」三件事，一件都不重造。
#: 落子动作词：通过 ⇒ ``set_review_state(ADMIT)``（标本命 + 复档加权）；
#: 拒绝 ⇒ ``reject_review``（删行删文件 + 内容级墓碑，同图重发不复活，口径同 NSFW 删除）。
#: 除这两族之外的一切首词（含裸「待审」与「列表/队列/list」这类读法）**一律走只读腿**——
#: 审批面只开两枚写入口，读侧想加多少同义词都不扩大写面，这是本面最小的攻击面形状。
_REVIEW_APPROVE_WORDS = frozenset({"通过", "同意", "批准", "准入", "收", "收下", "approve", "admit"})
_REVIEW_REJECT_WORDS = frozenset({"拒绝", "驳回", "不收", "reject", "deny"})
#: 一次端几张给管理员看：图片条数与合并转发都有界，别在几十张里翻。
_REVIEW_PAGE_LIMIT = 6
#: 前缀匹配时读多少行：比列表页宽，为的是「不唯一」这件事要说得出口（台账 #18 同名先问）。
_REVIEW_MATCH_LIMIT = 50
#: 回执里给出的 md5 前缀位数：够管理员敲，不够撞库（8 位十六进制＝4 字节熵）。
_REVIEW_KEY_DIGITS = 8


def _review_display_label(value: object) -> str:
    """待审行的短标签（VLM 描述句 / 管理员敲的前缀）进用户可见文案前的消毒。

    描述句是**二手**产出、管理员敲的那串是外部输入，两者都以肉眼形态出现在同一格里：
    与 ``/表情 列表`` 后端 key 同一类显示欺骗风险（P2D 显示腿，台账 #68）。处置口只准
    用中央咽喉 ``chat_reply/security/injection::render_safe_display_name``，本文件不自建
    第二套码点表；**局部导入**避开跨域成环——先例
    ``domains/meme/capabilities/meme.py::_display_safe_name``。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
        render_safe_display_name,
    )

    return render_safe_display_name(" ".join(str(value or "").split())[:60])


def _review_result(
    message: IncomingMessage,
    *,
    body: str,
    audit: Sequence[str],
    kind: str = "text",
    title: str = "表情库审批",
    images: Sequence[dict[str, Any]] = (),
    risk: RiskLevel = RiskLevel.LOW,
) -> CapabilityResult:
    """审批面回执的唯一出口（request_id/capability_id/隐私级三件事不许每支各拼一遍）。

    隐私级恒为 ``PERSONAL``：队列里是库内部读数与本 bot 的判断依据，不是群公告。
    """
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.meme_library",
        kind=kind,
        title=title,
        body=body,
        images=[dict(item) for item in images],
        risk_level=risk,
        privacy_level=PrivacyLevel.PERSONAL,
        audit_tags=list(audit),
    )


def handle_meme_review_command(
    store: Any,
    config: Any | None,
    message: IncomingMessage,
    arg: str,
) -> CapabilityResult:
    """``/表情库 待审`` / ``/表情库 审批 通过|拒绝 <md5 前缀>`` 的一条腿。

    四道牙，逐枚都有锁（``tests/test_meme_persona_review_queue.py`` 审批段）：

    1. **管理判定走中央口** ``policy/roles.py::is_admin_message``——本文件零名单副本，
       非管理员＝``denied`` 审计 + 拒收文案，**库一个字节都不许动**（连读都不必读）。
    2. **列表＝真图**：``kind="mixed"`` + ``images``，管理员不看图就是在盲签；
       空队列说「空」，不拿「0 张」冒充有过内容。
    3. **落子＝先过形状闸门，再前缀匹配 0/1/N 三岔**：编号太短 ⇒ ``ambiguous`` +
       ``prefix_too_short``、非十六进制 ⇒ ``need_key`` + ``prefix_not_hex``（两支都
       一次 SQL 不发，且回执说的是「你没说清」而不是「库里没图」）；三岔为
       0 ⇒ ``not_found``（绝不新建行）；N ⇒ ``ambiguous`` 先问、两张都不动
       （猜＝替管理员签了他没写的字）；1 ⇒ 通过走 ``set_review_state(ADMIT)``、
       拒绝走 ``reject_review``。
    4. **冷却不沾**：审批是管理员的管理动作，不是刷屏面；把它接进 pick 的会话冷却
       等于让「连批三张」在第二张开始被拒——那是限流不是审核。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
        is_admin_message,
    )
    from plugins.bot_unified_runtime.domains.meme.sources import persona_review
    from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
        MD5_PREFIX_MIN_LENGTH,
        MD5_PREFIX_NOT_HEX,
        MD5_PREFIX_TOO_SHORT,
        md5_prefix_gate,
    )

    if not bool(is_admin_message(config, message)):
        return _review_result(
            message,
            body="这张要不要算守岸人的本命收藏，得管理员点过头才行。守岸人不能自己批自己的账。",
            audit=["meme_library", "review", "denied"],
        )
    if store is None:
        return _review_result(
            message,
            body="表情库这一路没接上，待审队列也就无从可看。",
            audit=["meme_library", "review", "no_store"],
        )

    tokens = str(arg or "").split()
    verb = tokens[0] if tokens else ""
    key = " ".join(tokens[1:]).strip()
    is_approve = verb in _REVIEW_APPROVE_WORDS
    is_reject = verb in _REVIEW_REJECT_WORDS

    if not (is_approve or is_reject):
        # 首词不是落子动词（裸「待审」、「列表/队列/list」、乃至把编号直接当首词敲）
        # ⇒ **只读**：整串当过滤前缀用（「待审 abcde」只看那一类），一个字节都不改库。
        needle = " ".join(tokens).strip().lower()
        rows = store.list_review(persona_review.PENDING, limit=_REVIEW_PAGE_LIMIT)
        if needle:
            narrowed = [
                row for row in rows if str(row.get("md5", "")).lower().startswith(needle)
            ]
            # 前缀没对上任何一行也不空手回：交回整条队列，比「什么都没找到」有用。
            rows = narrowed or rows
        return _render_review_queue(message, rows, store=store, pending_state=persona_review.PENDING)

    if not key:
        # 「审批 通过」不带编号＝没说要批哪一张。落子必须指名——
        # 按队列顺序挑第一张＝替管理员签了他没写的字。
        return _review_result(
            message,
            body=(
                f"通过还是拒绝守岸人听清了，可不知道该落到哪一张。"
                f"补上表情编号的前 {_REVIEW_KEY_DIGITS} 位再报一次：表情库 审批 "
                f"{'通过' if is_approve else '拒绝'} <编号前缀>。"
            ),
            audit=["meme_library", "review", "need_key"],
        )

    # 编号形状闸门：判据真身在库侧 ``md5_prefix_gate``（本面一份都不重抄），在这里
    # 先问一句只为把**回执**措辞对——「前缀太短」是「你没说清」，不是「库里没图」。
    # 太短那一支的审计归入 ``ambiguous`` 族：短到不可能只对上那一张，与「撞上好几张」
    # 是同一条判据（先问、不落子）的前置形态，另附一枚 ``prefix_too_short`` 分得开账。
    gate = md5_prefix_gate(key)
    if gate == MD5_PREFIX_TOO_SHORT:
        return _review_result(
            message,
            body=(
                f"编号前缀「{_review_display_label(key)}」太短了：这么短不可能只对上那一张，"
                f"守岸人不猜。库里那串是 32 位十六进制，说满 {MD5_PREFIX_MIN_LENGTH} 位"
                "再报一次同一条令就行——没说清不等于没图可批。"
            ),
            audit=["meme_library", "review", "ambiguous", "prefix_too_short"],
        )
    if gate == MD5_PREFIX_NOT_HEX:
        return _review_result(
            message,
            body=(
                f"「{_review_display_label(key)}」对不上表情编号的形状：库里那串是十六进制。"
                f"照队列里露出的前 {_REVIEW_KEY_DIGITS} 位重报一次同一条令，"
                "守岸人不动库。"
            ),
            audit=["meme_library", "review", "need_key", "prefix_not_hex"],
        )

    # 候选集：批准这条腿**不按队列位设限**（``state=None``）。存量行的 review_state
    # 是空串，只看 pending＝回执让管理员「先去审批」、而那批行根本永远进不了可批集合
    # （断头路）。拒绝照旧只认 pending：删行删文件加立墓碑是不可逆动作，
    # 把「可删集合」从待审队列放大到整库不是这次要的东西，一寸不放宽。
    # 两支**都**由库侧在 SQL 里先按前缀收窄、再截断（曾有的形状是「拒绝那支先截断
    # 再在 python 侧筛」＝只对最新 N 行有效，老行照旧够不着）。
    matches = store.match_review_key(
        key,
        state=None if is_approve else persona_review.PENDING,
        limit=_REVIEW_MATCH_LIMIT,
    )
    if not matches:
        return _review_result(
            message,
            body=(
                f"{'库里' if is_approve else '待审队列里'}没有以「{_review_display_label(key)}」"
                "开头的表情。"
                "也许已经批过了——想再看一遍就说：表情库 待审。"
            ),
            audit=["meme_library", "review", "not_found"],
        )
    if len(matches) > 1:
        listed = "、".join(
            str(row.get("md5", ""))[:_REVIEW_KEY_DIGITS] for row in matches[: _REVIEW_MATCH_LIMIT]
        )
        return _review_result(
            message,
            body=(
                f"前缀「{_review_display_label(key)}」在{'库里' if is_approve else '待审队列里'}"
                f"对上了 {len(matches)} 张：{listed}。"
                "守岸人不知道该批哪一张，编号说长一点再报一次。"
            ),
            audit=["meme_library", "review", "ambiguous"],
        )

    row = matches[0]
    md5 = str(row.get("md5", "") or "")
    label = _review_display_label(row.get("description"))
    short = md5[:_REVIEW_KEY_DIGITS]
    if is_approve:
        if not bool(store.set_review_state(md5, persona_review.ADMIT)):
            return _review_result(
                message,
                body=f"这一张（{short}）刚刚不在库里了，审批没有落下去。再看一次：表情库 待审。",
                audit=["meme_library", "review", "stale"],
                risk=RiskLevel.MEDIUM,
            )
        return _review_result(
            message,
            body=(
                f"已收进本命池：{short} {label}。"
                "往后这张按守岸人自己的收藏记档，也不再被按龄裁剪。"
            ),
            audit=["meme_library", "review", "approved"],
            risk=RiskLevel.MEDIUM,
        )
    if not bool(store.reject_review(md5)):
        return _review_result(
            message,
            body=f"这一张（{short}）没退掉——库里已经找不到它了，不谎报成果。",
            audit=["meme_library", "review", "stale"],
            risk=RiskLevel.MEDIUM,
        )
    return _review_result(
        message,
        body=f"已退回并删掉：{short} {label}。同一张图再发进来也不会复活。",
        audit=["meme_library", "review", "rejected"],
        risk=RiskLevel.MEDIUM,
    )


def _render_review_queue(
    message: IncomingMessage,
    rows: Sequence[dict[str, Any]],
    *,
    store: Any,
    pending_state: str,
) -> CapabilityResult:
    """待审队列的回执：有图端图，没图说人话——两种形态都不许改库。"""
    if not rows:
        return _review_result(
            message,
            body="待审队列是空的——眼下没有证据不齐、卡在门口的表情。",
            audit=["meme_library", "review", "list", "queue_empty"],
        )
    lines: list[str] = [f"待审队列 {len(rows)} 张，等证据齐了才收进本命池："]
    images: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        md5 = str(row.get("md5", "") or "")
        path = str(row.get("path", "") or "").strip()
        label = _review_display_label(row.get("description"))
        lines.append(f"{index}. {md5[:_REVIEW_KEY_DIGITS]} {label}（权重 {row.get('weight')}）")
        if path:
            images.append({"file": path})
    lines.append(
        "批出去：表情库 审批 通过 <编号前缀>；不收：表情库 审批 拒绝 <编号前缀>。"
    )
    pending_total = 0
    try:
        pending_total = int(store.stats().get("pending_review", 0))
    except Exception:  # noqa: BLE001 - 总数是解释性附加信息，读不到不许拖累审批页。
        pending_total = 0
    if pending_total > len(rows):
        lines.append(f"队列共 {pending_total} 张，本次只端最前面的 {len(rows)} 张。")
    return _review_result(
        message,
        body="\n".join(lines),
        audit=["meme_library", "review", "list", f"pending:{len(rows)}", f"state:{pending_state}"],
        kind="mixed",
        images=images,
    )


# ---- S-ALBUM（2026-09-30）表情册面：管理员的四动作册账 ----
# 判据本体一律不住这里：库行怎么改、失配怎么判、落到册里算 moved 还是撞名，全在
# ``sources/meme_library.py`` 的四枚执法口（``match_md5_prefix`` / ``relink_path`` /
# ``missing_path_rows`` / ``admit_into_album``）。本面只做「命令 → 扫盘 → 执法口 → 回执」。
# 手里的尺全是别人的真身，一枚都不新造（同「禁第二份牌堆算法」的口径）：容器门交给
# store、重解析点交给 ``path_gate.reparse_point``、目录名剪枝交给
# ``capabilities/randpic.py::_should_prune_dir``、图片后缀交给 ``sticker_packs`` 那张表。
#: 动作词 → 动作码。裸命令（只有「表情册」）折成 ``stats``：默认值定在最保守的一档，
#: 误触代价为零；三枚写口（重扫/查重/入册）一律要首词点名。
_ALBUM_ACTION_WORDS = {
    "统计": "stats",
    "重扫": "rescan",
    "查重": "dedupe",
    "入册": "admit",
}
#: 统计页每册最多列几份子标签目录：再多就翻不动，截断必须当场公告（不许静吃）。
_ALBUM_LABEL_DIR_LIMIT = 12
#: 查重一次最多端几对：与审批页同一个道理，管理员一眼要能看完。
_ALBUM_DUPE_LIMIT = 20


def _album_image_suffixes() -> frozenset[str]:
    """图片后缀判定**直读贴纸池那一张表**（``sticker_packs._STICKER_EXTENSIONS``）。

    本面不建第二张后缀表：那张改了，册账自动跟着改。读不到（桩件里没这枚常量）⇒
    空集＝册里一张都不数，宁可如实报 0，也不拿自备的后缀猜。
    """
    from plugins.bot_unified_runtime.domains.meme.sources import sticker_packs

    return frozenset(getattr(sticker_packs, "_STICKER_EXTENSIONS", ()) or ())


def _album_store_method(store: Any, name: str) -> Callable[..., Any] | None:
    """取 store 的册面执法口；没这一枚 ⇒ ``None``。

    四法与 store 席同波落地，装配顺序没有保证。缺法时**诚实降级**（回执点名哪一格
    没接上）比抛 ``AttributeError`` 好：后者会把整条能力打成内部错误卡，管理员只看
    见「出错了」、看不见「哪一格没接」——那是把真信息换成噪音。判据仍一字不重造。
    """
    method = getattr(store, name, None)
    return method if callable(method) else None


def _walk_album_tree(
    root: Path,
) -> tuple[list[Path], list[str], int, int]:
    """扫一棵册树，交回（图片清单、第一层子标签目录名、剪掉的条目数、读不动的目录数）。

    遍历形状仿 ``sources/sticker_packs.py::_scan_root``（同一条隐私红线）：
    ``os.walk(followlinks=False)`` 只挡得住 POSIX 符号链接，Windows 的 junction 得看
    ``path_gate.reparse_point``；命中 ``randpic._should_prune_dir`` 的目录名不进树。
    **只数不动**：本函数一个字节都不写、不删、不建。
    """
    from plugins.bot_unified_runtime.domains.media import path_gate
    from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import (
        _should_prune_dir,
    )

    suffixes = _album_image_suffixes()
    images: list[Path] = []
    labels: list[str] = []
    pruned = unreadable = 0

    def _note_walk_error(_error: OSError) -> None:
        nonlocal unreadable
        unreadable += 1

    try:
        for current, dirs, files in os.walk(
            root, onerror=_note_walk_error, followlinks=False
        ):
            here = Path(current)
            kept: list[str] = []
            for name in dirs:
                if _should_prune_dir(name) or path_gate.reparse_point(here / name):
                    pruned += 1
                    continue
                kept.append(name)
                if here == root:
                    labels.append(name)
            dirs[:] = kept
            for name in sorted(files):
                path = here / name
                if path.suffix.lower() not in suffixes:
                    continue
                if path_gate.reparse_point(path):
                    pruned += 1
                    continue
                images.append(path)
    except OSError:
        # 根被拔掉 / 权限中途变化：如实记 unreadable，不假装扫过（同 _scan_root 那枚牙）。
        unreadable += 1
    return images, sorted(labels), pruned, unreadable


def _newest_mtime(paths: Sequence[Path]) -> float:
    """这批图里最新的一张什么时候动过；一张都 stat 不动 ⇒ ``0.0``（调用方报「无」）。"""
    newest = 0.0
    for path in paths:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            continue
        newest = max(newest, stamp)
    return newest


def _album_name_for(path: Path, base: Path) -> str:
    """这张图落在哪一册＝基根第一层目录名；直接在基根下的散件 ⇒ 空串。"""
    try:
        parts = path.relative_to(base).parts
    except ValueError:
        return ""
    return parts[0] if len(parts) >= 2 else ""


def _album_single_segment(value: object) -> str:
    """册名必须是**一段干净的名字**才拿去拼路径：带分隔符／``..``／空 ⇒ 交回空串。

    这不是第二把路径尺—— containment 仍由 store 的容器门判（本面不 resolve、不比
    前缀）。这里只挡「名字里带分隔符 ⇒ 拼出来的路根本不在基根那一层」这一种形状，
    免得把 ``base / "a/b"`` 这种越层候选送进执法口去试。
    """
    text = " ".join(str(value or "").split()).strip()
    if not text or text in {".", ".."}:
        return ""
    separators = {"/", "\\", os.sep, os.altsep or ""}
    if any(sep and sep in text for sep in separators):
        return ""
    return text


def _current_persona_album_name(config: Any) -> str:
    """现役人格的展示名（人格册目录按它开）；读不出 ⇒ 空串，绝不猜一个名字。

    只走 ``persona_profile`` 那两枚唯一读法（先定 id、再取名），**绝不读
    ``get_login_info``** 的自身身份缓存——台账 #60 的禁读口；切人格后这里自动跟换。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        active_persona_id,
        current_bot_nickname,
    )

    try:
        name = current_bot_nickname(active_persona_id(config), config=config)
    except Exception:  # noqa: BLE001 - 名字读不出＝册没法定，交给调用方诚实报缺席。
        return ""
    return _album_single_segment(name)


def _album_row_field(item: Any, key: str, default: str = "") -> str:
    """从 ``match_md5_prefix`` 的一枚命中里读一个字段（行字典读键）。

    契约（F2，2026-09-30）：``match_md5_prefix`` 交回**行字典**，键与
    ``missing_path_rows`` 同形（``md5/path/persona_hint/ext``）——只交回裸 md5 的话
    「目标册＝该行的人格提示」这条路径永远不可达。这里仍按**在场的那一形**取：
    拿不到键就用调用方的回落值，绝不假装知道人格提示。
    """
    if isinstance(item, dict):
        return str(item.get(key, default) or default)
    return default


def _album_container(store: Any) -> Path | None:
    """读 store 的**容器根**（册账的登记根）；口不在／读数空／抛错 ⇒ ``None``。

    ``None`` 不猜、不回落：交给 ``unconfigured`` 门如实报缺席，绝不退到家目录或贴纸池。
    """
    container_method = _album_store_method(store, "media_container")
    if container_method is None:
        return None
    try:
        value = container_method()
    except Exception as exc:  # noqa: BLE001 - 读不出容器＝没判据，交给缺席门如实报。
        logger.debug("album container unreadable: %s", type(exc).__name__)
        return None
    text = str(value or "").strip()
    return Path(text) if text else None


def handle_meme_album_command(
    store: Any,
    config: Any | None,
    message: IncomingMessage,
    arg: str,
) -> CapabilityResult:
    """``/表情册 统计|重扫|查重|入册 <编号前缀>`` 的一条腿（四动作共用四道门）。

    门的次序就是代价的次序，逐枚都有账：

    1. **管理判定走中央口** ``policy/roles.py::is_admin_message``（照抄审批面，本文件
       零名单副本）⇒ 非管理员 ``denied``，**连盘都不许扫**。
    2. ``store is None`` ⇒ ``no_store``：册面的三枚写口全住在 store，没它就没判据。
    3. 登记根没配上 ⇒ ``unconfigured``：零扫描、零异常，不去别处找。
    4. 登记根不在盘上 ⇒ ``root_absent``：**诚实缺席**——绝不自动创建目录、绝不越出容器
       （口径同 ``sticker_packs.persona_album_root``：册缺就是册缺）。

    册基根＝**表情库的登记容器** ``store.media_container()``（真身是 ``BOT_MEME_LIBRARY_DIR``，
    缺省退库文件所在目录），**不是贴纸池 ``BOT_STICKER_DIR``**（F1，2026-09-30 用户裁甲案）：
    册账与贴纸池是两枚键两片目录，而 store 的 ``admit_into_album``/``relink_path`` 一律按
    容器判界，拿贴纸池当基根只会让「入册」永远 ``escape``、「重扫」永远重链 0。

    四动作的写面：查重与统计纯只读；重扫只改 ``path``/``persona_hint``（经
    ``relink_path``）；入册经 ``admit_into_album`` 搬文件改行，逐态各一句人话回执——
    态的清单以 ``sources/meme_library.admit_into_album`` 的各 ``return`` 点为准（此枚
    返回码比旧文案多一层出处门 ``not_admitted``，故旧写「六态」已失真；枚数不写死，规则 10）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
        is_admin_message,
    )

    if not bool(is_admin_message(config, message)):
        return _review_result(
            message,
            title="表情册",
            body="开册、重链、入册这些都是动库的，得管理员点头才让走。守岸人不自开自己的册子。",
            audit=["meme_library", "album", "denied"],
        )
    if store is None:
        return _review_result(
            message,
            title="表情册",
            body="表情库这一路没接上，册面的统计、重扫、入册都无从谈起。",
            audit=["meme_library", "album", "no_store"],
        )
    base = _album_container(store)
    if base is None:
        return _review_result(
            message,
            title="表情册",
            body=(
                "册账的登记根（表情库目录，配的是 BOT_MEME_LIBRARY_DIR）还没配上，"
                "守岸人不知道去哪儿找表情册，也就不去别处翻——它和贴纸池 BOT_STICKER_DIR "
                "是两枚键，守岸人拿后者顶不了数。"
            ),
            audit=["meme_library", "album", "unconfigured"],
        )
    if not base.is_dir():
        return _review_result(
            message,
            title="表情册",
            body=(
                "配好的登记根（表情库目录，不是贴纸池）眼下不在盘上（或那不是个目录）。"
                "守岸人不会自己造一个册子出来，也不拿别的目录顶数——先把它放回原位，"
                "再说表情册 统计。"
            ),
            audit=["meme_library", "album", "root_absent"],
            risk=RiskLevel.MEDIUM,
        )

    tokens = str(arg or "").split(maxsplit=1)
    action = tokens[0] if tokens else "stats"
    payload = tokens[1].strip() if len(tokens) > 1 else ""
    if action == "rescan":
        return _album_rescan(message, store, base)
    if action == "dedupe":
        return _album_dedupe(message, base)
    if action == "admit":
        return _album_admit(message, store, config, base, payload)
    return _album_stats(message, base)


def _album_stats(message: IncomingMessage, base: Path) -> CapabilityResult:
    """统计：基根第一层逐册报「图片数／子标签目录（≤12）／最新 mtime」，只数不动。"""
    from plugins.bot_unified_runtime.domains.media import path_gate
    from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import (
        _should_prune_dir,
    )

    try:
        entries = sorted(base.iterdir(), key=lambda item: str(item).lower())
    except OSError:
        return _review_result(
            message,
            title="表情册",
            body="登记根眼下打不开（被拔掉或权限不够），守岸人没有读数可以报。",
            audit=["meme_library", "album", "stats", "unreadable_root"],
            risk=RiskLevel.MEDIUM,
        )
    # 第一层同样要过那两把尺——登记根本人不做例外（与 ``_scan_root``/``randpic`` 同形）：
    # ``_skip``、``.hidden``、junction 冒充的「册」都不配端出来当一本账。
    suffixes = _album_image_suffixes()
    albums: list[Path] = []
    pruned_total = unreadable_total = 0
    for item in entries:
        if not item.is_dir():
            continue
        if _should_prune_dir(item.name) or path_gate.reparse_point(item):
            pruned_total += 1
            continue
        albums.append(item)
    loose = sum(
        1
        for item in entries
        if item.is_file() and item.suffix.lower() in suffixes
    )
    lines: list[str] = [
        f"表情册账：基根第一层 {len(albums)} 册，未归档散件 {loose} 张。"
    ]
    for album in albums:
        images, labels, pruned, unreadable = _walk_album_tree(album)
        pruned_total += pruned
        unreadable_total += unreadable
        newest = _newest_mtime(images)
        stamp = time.strftime("%Y-%m-%d", time.localtime(newest)) if newest else "无"
        shown = [_review_display_label(name) for name in labels[:_ALBUM_LABEL_DIR_LIMIT]]
        tail = (
            f"（另有 {len(labels) - len(shown)} 个未列）"
            if len(labels) > len(shown)
            else ""
        )
        label_part = f"子标签 {len(labels)} 个：{'、'.join(shown)}{tail}" if labels else "无子标签目录"
        lines.append(
            f"《{_review_display_label(album.name)}》图片 {len(images)} 张｜最新 {stamp}｜{label_part}"
        )
    if not albums:
        lines.append("第一层没有册目录——册子还没按人格开起来，图都散在基根上。")
    if pruned_total:
        lines.append(f"另有 {pruned_total} 处链接／隐藏目录按规矩跳过，没数进这张账。")
    if unreadable_total:
        lines.append(f"读不动的目录 {unreadable_total} 处，守岸人不猜它们里面有什么。")
    if loose:
        lines.append("想收进册里：表情册 入册 <编号前缀>。散件守岸人不会自己认领。")
    return _review_result(
        message,
        title="表情册",
        body="\n".join(lines),
        audit=["meme_library", "album", "stats", f"albums:{len(albums)}", f"loose:{loose}"],
    )


def _album_rescan(message: IncomingMessage, store: Any, base: Path) -> CapabilityResult:
    """重扫：``missing_path_rows`` 逐行在基根内找同名／同编号的文件，找得到就重链。

    找法只认**在场的那一枚**：编号对上了多张、或一处都没对上 ⇒ 记「仍失配」，绝不
    挑一张交差（猜＝替库写了一条没人核对过的路径）。重链一律经 ``relink_path``。
    """
    rows_method = _album_store_method(store, "missing_path_rows")
    relink_method = _album_store_method(store, "relink_path")
    if rows_method is None or relink_method is None:
        return _review_result(
            message,
            title="表情册",
            body="重扫这条腿还没和库接好（失配读数或重链口有一格不在），守岸人不动库。",
            audit=["meme_library", "album", "rescan", "unsupported"],
            risk=RiskLevel.MEDIUM,
        )
    # store 侧 limit 数的是「报出的失配行」而非库里的行，所以这里给的是本轮上报上限。
    # 库里失配面比这个数更大时，本轮只覆盖前这么多条——必须在回执里讲明，
    # 不能让人以为账已经见底。
    report_max = 500
    try:
        rows = list(rows_method(report_max) or [])
    except Exception as exc:  # noqa: BLE001 - 失配读不出来＝一个字节都不改，如实说。
        logger.debug("album missing rows unavailable: %s", type(exc).__name__)
        return _review_result(
            message,
            title="表情册",
            body="库里的失配行读不出来，重扫没有开始，一个字节都没改。",
            audit=["meme_library", "album", "rescan", "read_failed"],
            risk=RiskLevel.MEDIUM,
        )
    if not rows:
        return _review_result(
            message,
            title="表情册",
            body="库里的路径行都对得上，这一轮没有要补的账。",
            audit=["meme_library", "album", "rescan", "nothing_missing"],
        )

    images, _labels, _pruned, _unreadable = _walk_album_tree(base)
    by_stem: dict[str, list[Path]] = {}
    by_name: dict[str, list[Path]] = {}
    for path in images:
        by_stem.setdefault(path.stem.lower(), []).append(path)
        by_name.setdefault(path.name.lower(), []).append(path)

    relinked = unmatched = unapproved = 0
    from plugins.bot_unified_runtime.domains.meme.sources import (
        persona_review,  # 出处门唯一真身（与 admit_into_album 同一枚字面）
    )
    for row in rows:
        if not isinstance(row, dict):
            unmatched += 1
            continue
        md5 = str(row.get("md5", "") or "").strip().lower()
        hint = _album_single_segment(row.get("persona_hint"))
        ext = str(row.get("ext", "") or "").strip().lower()
        old_name = Path(str(row.get("path", "") or "")).name.lower()
        if not md5:
            unmatched += 1
            continue
        candidates = by_stem.get(md5) or by_name.get(old_name) or []
        if not candidates and ext:
            candidates = by_name.get(f"{md5}{ext}") or []
        if hint:
            hinted = [item for item in candidates if _album_name_for(item, base) == hint]
            candidates = hinted or candidates
        if len(candidates) != 1:
            # 0 张＝没找到；≥2 张＝守岸人不知道是哪一张，不替库猜。
            unmatched += 1
            continue
        hit = candidates[0]
        album = _album_name_for(hit, base)
        if album and str(row.get("review_state") or "").strip() != persona_review.ADMIT:
            # 出处门的第二条腿（2026-10-01 补，T16/T11 两席各自独立点出同一格）：
            # 文件躺在册目录里≠它被批准进册。没过审的行若由重扫正式改道，
            # ``persona_owned`` 就被机器宣成「某人格的册图」，而发送面纯文件遍历
            # 不过 DB——那就是「没过审不搬进人格册」这条裁定的绕行通道。
            # 所以这里只认路径、不认身份：重链照做，persona 两列一律不替它宣。
            unapproved += 1
            album = ""  # 只认路径、不认身份：见上，重链照做但 persona 两列一律不宣
        try:
            ok = bool(
                relink_method(
                    md5,
                    str(hit),
                    persona_hint=album,
                    persona_owned=bool(album),
                )
            )
        except Exception as exc:  # noqa: BLE001 - 单行重链失败只算失配，不中断整本账。
            logger.debug("album relink failed: %s", type(exc).__name__)
            ok = False
        if ok:
            relinked += 1
        else:
            unmatched += 1
    return _review_result(
        message,
        title="表情册",
        body=(
            f"重扫完：重链 {relinked} 行，仍失配 {unmatched} 行（本轮待对 {len(rows)} 行）。"
            + (
                f"本轮最多报 {report_max} 条失配，库里要是有更多就还没进入这一轮——"
                "再报一次「表情册 重扫」接着往下对。"
                if len(rows) >= report_max
                else ""
            )
            + ("仍失配的那些守岸人没有动手，路径与账本都原样留着。" if unmatched else "")
            + (
                f"另有 {unapproved} 行的文件就在册目录里，可它没过审——重扫不替谁把身份宣成「人格的册图」，"
                "先走审批（或人工处置），再回来重扫。"
                if unapproved
                else ""
            )
        ),
        audit=[
            "meme_library",
            "album",
            "rescan",
            f"relinked:{relinked}",
            f"missing:{unmatched}",
            f"unapproved:{unapproved}",
        ],
        risk=RiskLevel.MEDIUM,
    )


def _album_dedupe(message: IncomingMessage, base: Path) -> CapabilityResult:
    """查重：同一个编号（文件名去后缀＝库里的 md5）跨册出现的对，最多端 20 对。

    只报**册名对**、不给绝对路径：管理员要的是「哪两册撞了」，盘符串进聊天窗是风险
    不是信息（``redact_local_secrets`` 兜的是出站，本面从一开始就不写它）。
    """
    images, _labels, _pruned, _unreadable = _walk_album_tree(base)
    grouped: dict[str, list[str]] = {}
    for path in images:
        album = _album_name_for(path, base) or "基根散件"
        bucket = grouped.setdefault(path.stem.lower(), [])
        if album not in bucket:
            bucket.append(album)
    pairs: list[tuple[str, str, str]] = []
    for stem, albums in grouped.items():
        if len(albums) < 2:
            continue
        pairs.extend((stem, left, right) for left, right in pairwise(albums))
    pairs.sort(key=lambda item: (item[1], item[2], item[0]))
    if not pairs:
        return _review_result(
            message,
            title="表情册",
            body=(
                f"扫过 {len(images)} 张，册与册之间没有同编号重复——这一本眼下是干净的。"
            ),
            audit=["meme_library", "album", "dedupe", "clean", f"images:{len(images)}"],
        )
    lines = [f"同编号跨册 {len(pairs)} 对，一次端 {min(len(pairs), _ALBUM_DUPE_LIMIT)} 对："]
    for stem, left, right in pairs[:_ALBUM_DUPE_LIMIT]:
        lines.append(
            f"{_review_display_label(stem[:_REVIEW_KEY_DIGITS])}："
            f"《{_review_display_label(left)}》↔《{_review_display_label(right)}》"
        )
    if len(pairs) > _ALBUM_DUPE_LIMIT:
        lines.append(f"另有 {len(pairs) - _ALBUM_DUPE_LIMIT} 对没列出，守岸人不装看不见。")
    return _review_result(
        message,
        title="表情册",
        body="\n".join(lines),
        audit=["meme_library", "album", "dedupe", f"pairs:{len(pairs)}"],
    )


def _album_admit(
    message: IncomingMessage,
    store: Any,
    config: Any | None,
    base: Path,
    payload: str,
) -> CapabilityResult:
    """入册：编号前缀 0/1/N 三岔定行，目标册定完交给 ``admit_into_album`` 落子。

    与审批面同一套岔口：0 ⇒ 不新建行；N ⇒ 先问、一张都不搬（猜＝替管理员落了他没写的
    子）。基根＝表情库登记容器（由调用方取好交进来，与 store 判界那一片同一片）；
    目标册＝``基根/<行上的人格提示>``，行上没写提示才落到 ``基根/<现役人格展示名>``，
    且**只在这时**才把册名登记进 ``persona_hint``——行上原提示一概不覆写（F2）。
    册目录不在＝**不创建**，直接说缺席。搬动与改行全在 store 那一侧，本面一字不写。
    """
    match_method = _album_store_method(store, "match_md5_prefix")
    admit_method = _album_store_method(store, "admit_into_album")
    if match_method is None or admit_method is None:
        return _review_result(
            message,
            title="表情册",
            body="入册这条腿还没和库接好（前缀查或落子口有一格不在），守岸人不动库。",
            audit=["meme_library", "album", "admit", "unsupported"],
            risk=RiskLevel.MEDIUM,
        )
    if not payload:
        return _review_result(
            message,
            title="表情册",
            body=(
                f"要收进册守岸人听见了，可不知道该收哪一张。补上表情编号的前 "
                f"{_REVIEW_KEY_DIGITS} 位再报一次：表情册 入册 <编号前缀>。"
            ),
            audit=["meme_library", "album", "admit", "need_key"],
        )
    try:
        matches = list(match_method(payload, limit=_REVIEW_MATCH_LIMIT) or [])
    except Exception as exc:  # noqa: BLE001 - 前缀查失败＝没落子，如实报，不换个姿势重试。
        logger.debug("album prefix match failed: %s", type(exc).__name__)
        return _review_result(
            message,
            title="表情册",
            body="编号查不动，入册没有开始，库里一个字节都没改。",
            audit=["meme_library", "album", "admit", "read_failed"],
            risk=RiskLevel.MEDIUM,
        )
    if not matches:
        return _review_result(
            message,
            title="表情册",
            body=(
                f"库里没有以「{_review_display_label(payload)}」开头的表情。"
                "也许已经入过册了——想再看一遍就说：表情册 统计。"
            ),
            audit=["meme_library", "album", "admit", "not_found"],
        )
    if len(matches) > 1:
        listed = "、".join(
            _review_display_label(str(_album_row_field(item, "md5") or item)[:_REVIEW_KEY_DIGITS])
            for item in matches[:_REVIEW_MATCH_LIMIT]
        )
        return _review_result(
            message,
            title="表情册",
            body=(
                f"前缀「{_review_display_label(payload)}」在库里对上了 {len(matches)} 张：{listed}。"
                "守岸人不知道该收哪一张，编号说长一点再报一次。"
            ),
            audit=["meme_library", "album", "admit", "ambiguous"],
        )

    item = matches[0]
    md5 = str(_album_row_field(item, "md5") or item).strip()
    short = md5[:_REVIEW_KEY_DIGITS]
    if not md5:
        return _review_result(
            message,
            title="表情册",
            body="这一张的编号没读全，守岸人没有落子。编号说长一点再报一次。",
            audit=["meme_library", "album", "admit", "bad_key"],
            risk=RiskLevel.MEDIUM,
        )
    album_name = _album_single_segment(_album_row_field(item, "persona_hint"))
    row_hint = bool(album_name)
    if not album_name:
        album_name = _current_persona_album_name(config)
    if not album_name:
        return _review_result(
            message,
            title="表情册",
            body=(
                "这一张的行上没有册名，现役人格的名字守岸人也没读准——"
                "没有可靠册名就不落子，先说一句「切人格」或把人格册建起来，再报一次。"
            ),
            audit=["meme_library", "album", "admit", "no_album_name"],
            risk=RiskLevel.MEDIUM,
        )
    target = base / album_name
    if not target.is_dir():
        return _review_result(
            message,
            title="表情册",
            body=(
                f"《{_review_display_label(album_name)}》这一册眼下不在登记根里。"
                "守岸人不替谁新建目录，也不把图塞到别处去——册开好了再报一次。"
            ),
            audit=["meme_library", "album", "admit", "album_absent"],
        )

    try:
        # 行上本来就写着册名 ⇒ ``persona_hint`` 交空串＝不改这一列（F2：绝不拿本轮
        # 落定的册名去覆写行上原提示）；只有行上没写、用的是现役人格名时才登记进去。
        status = str(
            admit_method(
                md5,
                str(target),
                persona_hint="" if row_hint else album_name,
            )
            or "error"
        )
    except Exception as exc:  # noqa: BLE001 - 落子抛错＝没落，如实报；不重试不换路。
        logger.debug("album admit failed: %s", type(exc).__name__)
        status = "error"
    label = _review_display_label(album_name)
    if status == "moved":
        body = (
            f"已把 {short} 收进《{label}》。路径与归属都跟着改好了，"
            "往后这张就按守岸人自己的册子记档。"
        )
    elif status == "no_row":
        body = f"库里已经找不到 {short} 这一行，入册没有落下去。先看一眼：表情册 统计。"
    elif status == "no_file":
        body = (
            f"{short} 的原文件不在库里了（被移走或清掉了）。"
            "守岸人不造一张假的成功，行没动。"
        )
    elif status == "escape":
        body = (
            f"《{label}》不在登记范围内，{short} 守岸人没有放进去——"
            "册子只在登记根里开合，越界的一律不接。"
        )
    elif status == "duplicate_name":
        body = (
            f"《{label}》里已经有同名的文件了，{short} 没有落下去，"
            "守岸人不覆盖已经在册的那一张。"
        )
    elif status == "not_admitted":
        body = (
            f"{short} 还没过审，守岸人不把它塞进人格册——进了册就意味着往后会主动"
            f"发给别人。要收它就报一句：表情库 审批 通过 {short}"
            "（这句认的是编号，不问它卡在哪个队列位），批过之后再报一次入册。"
        )
    else:
        body = (
            f"{short} 这一次没进册（库里撞到守岸人没预料的状况）。"
            "账没改，稍后再报一次就好。"
        )
    return _review_result(
        message,
        title="表情册",
        body=body,
        audit=["meme_library", "album", "admit", status],
        risk=RiskLevel.MEDIUM,
    )


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
        if action == "album":
            # 表情册面：四道门（admin／无库／无登记根／册不在盘上）与四动作的写面边界
            # 都在 ``handle_meme_album_command`` 一处；库行判据住 ``sources/meme_library.py``，
            # 本文件不搬文件、不改行、不建第二把路径尺。
            return handle_meme_album_command(store, config, message, arg)
        if action == "review":
            # 审批面：管理判定、前缀 0/1/N 分岔、待审≠禁发的口径都在
            # ``handle_meme_review_command`` 一处；判据本体住 ``sources/persona_review.py``，
            # 执法口住 ``sources/meme_library.py``——本文件不重算加权、不建第二张名单。
            return handle_meme_review_command(store, config, message, arg)
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

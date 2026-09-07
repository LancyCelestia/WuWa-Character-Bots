"""可解释的联网决策。

该模块只负责判断“是否值得联网”，不执行搜索。决策分成三层：

* ``NEVER``：闲聊、情绪、用户已提供的文本和稳定常识不预搜索；
* ``PRIMARY``：用户明确要求搜索，或问题明显依赖实时/外部事实；
* ``FALLBACK``：本地知识库优先，命中不足时再搜索；
* ``TOOL_ALLOWED``：信息需求不够确定，把是否搜索交给模型一次性判断。

所有返回值都包含置信度、原因码和分数分解，便于审计、统计和调整权重。
正则只负责提取信号，最终决策由“优先级 + 加权信号”共同决定，避免单个词
（例如“科学”“今天”）直接把普通对话送上网。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class QuestionIntent(str, Enum):
    KNOWLEDGE_FIRST = "knowledge_first"
    WEB_SEARCH = "web_search"
    NEUTRAL = "neutral"


class WebDecision(str, Enum):
    NEVER = "never"
    PRIMARY = "primary"
    FALLBACK = "fallback"
    TOOL_ALLOWED = "tool_allowed"


@dataclass(frozen=True)
class IntentDecision:
    intent: QuestionIntent
    reason: str
    allow_web_fallback: bool = False
    category: str = "AMBIGUOUS"
    decision: WebDecision = WebDecision.NEVER
    confidence: float = 0.0
    reason_codes: tuple[str, ...] = ()
    score_breakdown: dict[str, float] = field(default_factory=dict)
    allow_model_tool: bool = False
    knowledge_threshold: float = 0.35
    algorithm_version: str = "intent-v3"


# 世界观/本地知识词：它们只表示“可以先查本地知识库”，不是永久禁网。
DOMAIN_TERMS = (
    "鸣潮",
    "守岸人",
    "岸宝",
    "漂泊者",
    "黑海岸",
    "黎那汐塔",
    "今州",
    "七丘",
    "拉古那",
    "索拉里斯",
    "声骸",
    "共鸣者",
    "残星会",
    "瑝珑",
    "阿维纽林",
    "椿",
    "维里奈",
    "卡卡罗",
    "布兰特",
    "弗洛洛",
    "露帕",
    "夏空",
    "卡缇娅",
    "帕弥什",
    "无冠者",
    "黑潮",
    "鸣式",
    "艾弥斯",
    "洛斯拉",
    "泰缇斯",
    "调律大厅",
    "卡庇托",
    "鹫巢",
)

_EXPLICIT_SEARCH_RE = re.compile(
    r"(搜(索|一下|一查)?|查(一下|一查|资料|证)?|联网|上网|检索|"
    r"看官网|找新闻|查来源|给我来源|给我链接|引用来源|网页搜索|搜索一下)"
)
_NO_WEB_RE = re.compile(
    r"(不要(联网|搜索|上网)|别(联网|搜索|上网)|不用查|无需联网|只用本地|"
    r"仅根据我提供|根据上面的内容|不要引用外部资料)"
)
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_CURRENT_RE = re.compile(
    r"(今天|今日|现在|目前|最新|最近|新闻|消息|更新|版本|公告|维护|"
    r"开服|上线|发布|首发|前瞻|直播|什么时候|何时|几点|几号|"
    r"卡池|活动|限定|复刻|加强|削弱|改动|实装|预告|解禁|发售|"
    r"价格|多少钱|汇率|股票|股价|行情|房价|门票|时间地点|天气|气温|降雨|台风|空气质量)"
)
# Strong current-information nouns can imply a lookup even without a question mark.
_CURRENT_REQUEST_RE = re.compile(r"(新闻|消息|更新|版本|公告|维护|发布|前瞻|直播|卡池|活动|限定|复刻|加强|削弱|改动|实装|预告|解禁|发售|价格|多少钱|汇率|股票|股价|行情|房价|门票|时间地点|台风|空气质量)")

_REAL_WORLD_RE = re.compile(
    r"(官方|官宣|官网|公司|企业|工作室|开发商|制作人|创始人|总部|"
    r"所在地|地址|员工|作品|代表作|演唱会|音乐会|漫展|线下|举办|"
    r"展览|访谈|采访|热搜|百科|国际局势|国际关系|中美|中俄|"
    r"中欧|欧盟|俄乌|巴以|台海|世界局势|贸易战|关税|时事|地缘)"
)
_ENTITY_QUESTION_RE = re.compile(
    r"(是什么|是谁|是什么样|介绍一下|介绍|百科|背景|来历|在哪里|在哪儿|哪家公司)"
)
_STATIC_KNOWLEDGE_RE = re.compile(
    r"(为什么|什么是|原理|定义|区别|含义|意思|如何理解|能否解释|"
    r"光合作用|量子力学|天空是蓝的|数学|物理|化学|生物|历史|哲学)"
)
_TECHNICAL_HOWTO_RE = re.compile(
    r"(怎么安装|如何安装|怎么配置|如何配置|怎么部署|如何部署|"
    r"教程|排查|报错|代码|接口|框架|命令|环境|依赖|编程|"
    r"怎么用|如何使用|使用方法|一步一步|逐步)"
)
_USER_CONTENT_RE = re.compile(
    r"(请(帮我)?(总结|概括|改写|润色|校对|翻译|提取|整理)|"
    r"把下面|这段文字|以下内容|根据我提供|按这段内容)"
)
_CREATIVE_RE = re.compile(
    r"(角色扮演|扮演|写诗|写歌词|写故事|续写|同人|以.{0,12}(口吻|身份|风格)|"
    r"创作一段|编一个故事)"
)
_SELF_CHAT_RE = re.compile(
    r"(心情|感受|感觉|累|困|饿|难过|开心|快乐|害怕|孤单|寂寞|"
    r"陪我|陪我说|聊天|喜欢|爱|想你|在吗|你好|早上好|中午好|晚上好|"
    r"晚安|早安|谢谢|抱歉|辛苦|抱抱|摸摸)"
)
_YOU_STATE_RE = re.compile(
    r"(你最近怎么样|你怎么样|你还好吗|你好吗|最近好吗|"
    r"你现在感觉|你今天心情|你是谁|你是什么机器人|你是机器人吗|"
    r"你是ai吗|你是人工智能吗)"
)
_SHORT_SMALLTALK_RE = re.compile(
    r"^(?:你好|您好|嗨|哈喽|在吗|在不在|有人吗)[呀啊哇嘛吗呢哦喔~～!！?？。,.，]*$",
    re.IGNORECASE,
)
_ASKS_USER_IDENTITY_RE = re.compile(
    r"^(?:我是谁|你知道我是谁吗|你还记得我是谁吗|还记得我是谁吗)[~～!！?？。,.，]*$"
)
_QUESTION_LIKE_RE = re.compile(
    r"(\?|？|吗[？?。!！]*$|呢[？?。!！]*$|嘛[？?。!！]*$|"
    r"^(为什么|为何|怎么|如何|什么|谁|哪|是否|能不能|可以不可以|请问))"
)
# In-sentence question words cover forms such as “updated what” and “when rerun”.
_QUESTION_WORD_RE = re.compile(r"(什么时候|何时|几点|多少|哪里|哪儿|什么|谁|是否|怎么回事|怎么样)")

_ENTITY_SUBJECT_RE = re.compile(
    r"^(.{1,24}?)(?:是什么|是谁|是什么样|介绍一下|百科|来历)"
)


def _strip(text: str) -> str:
    return (text or "").strip()


def _is_question_like(text: str) -> bool:
    return bool(_QUESTION_LIKE_RE.search(text) or _QUESTION_WORD_RE.search(text))


def _domain_subject_present(text: str) -> bool:
    match = _ENTITY_SUBJECT_RE.match(text)
    if not match:
        return any(term in text for term in DOMAIN_TERMS)
    subject = match.group(1).strip("，。？?!！、 ")
    return any(term in subject for term in DOMAIN_TERMS) or any(
        term in text for term in DOMAIN_TERMS
    )


def _finish(
    *,
    intent: QuestionIntent,
    reason: str,
    category: str,
    decision: WebDecision,
    confidence: float,
    reason_codes: list[str],
    scores: dict[str, float],
    allow_web_fallback: bool = False,
    allow_model_tool: bool = False,
) -> IntentDecision:
    return IntentDecision(
        intent=intent,
        reason=reason,
        allow_web_fallback=allow_web_fallback,
        category=category,
        decision=decision,
        confidence=max(0.0, min(1.0, confidence)),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        score_breakdown={key: round(value, 3) for key, value in scores.items() if value},
        allow_model_tool=allow_model_tool,
    )


def classify_question_intent(text: str) -> IntentDecision:
    """提取信号、计算分数并按安全优先级生成可解释决策。"""
    stripped = _strip(text)
    if not stripped:
        return _finish(
            intent=QuestionIntent.NEUTRAL,
            reason="empty",
            category="SMALL_TALK",
            decision=WebDecision.NEVER,
            confidence=1.0,
            reason_codes=["empty"],
            scores={},
        )

    question_like = _is_question_like(stripped)
    has_domain = any(term in stripped for term in DOMAIN_TERMS)
    domain_subject = _domain_subject_present(stripped)
    explicit_search = bool(_EXPLICIT_SEARCH_RE.search(stripped))
    no_web = bool(_NO_WEB_RE.search(stripped))
    has_url = bool(_URL_RE.search(stripped))
    current = bool(_CURRENT_RE.search(stripped))
    current_request = bool(_CURRENT_REQUEST_RE.search(stripped))
    real_world = bool(_REAL_WORLD_RE.search(stripped))
    entity_question = bool(_ENTITY_QUESTION_RE.search(stripped))
    static_knowledge = bool(_STATIC_KNOWLEDGE_RE.search(stripped))
    technical_howto = bool(_TECHNICAL_HOWTO_RE.search(stripped))
    user_content = bool(_USER_CONTENT_RE.search(stripped))
    creative = bool(_CREATIVE_RE.search(stripped))
    self_chat = bool(_SELF_CHAT_RE.search(stripped))
    you_state = bool(_YOU_STATE_RE.search(stripped))
    short_smalltalk = bool(_SHORT_SMALLTALK_RE.fullmatch(stripped))
    asks_user_identity = bool(_ASKS_USER_IDENTITY_RE.fullmatch(stripped))

    scores: dict[str, float] = {}
    if explicit_search:
        scores["explicit_search"] = 1.0
    if has_url:
        scores["external_url"] = 0.95
    if current:
        scores["current_or_time_sensitive"] = 0.85
    if current_request:
        scores["current_request_noun"] = 0.9
    if real_world:
        scores["external_reality"] = 0.8
    if entity_question and not domain_subject and not static_knowledge:
        scores["external_entity"] = 0.8
    if has_domain:
        scores["local_domain"] = 0.7
    if static_knowledge:
        scores["static_knowledge"] = 0.65
    if technical_howto:
        scores["technical_how_to"] = 0.6
    if question_like:
        scores["question_form"] = 0.35

    # 明确的“不要联网”优先于一般搜索信号；只保留本地回答。
    if no_web:
        return _finish(
            intent=QuestionIntent.KNOWLEDGE_FIRST if has_domain else QuestionIntent.NEUTRAL,
            reason="explicit_no_web",
            category="LOCAL_KNOWLEDGE" if has_domain else "GENERAL_STATIC_KNOWLEDGE",
            decision=WebDecision.NEVER,
            confidence=0.98,
            reason_codes=["explicit_no_web"],
            scores=scores,
            allow_web_fallback=False,
        )

    # 个人对话永远不能因为“今天/最近”等词触发网页搜索。
    if short_smalltalk or asks_user_identity or self_chat or you_state:
        reason = (
            "short_smalltalk"
            if short_smalltalk
            else "asks_user_identity"
            if asks_user_identity
            else "you_state_chat"
            if you_state
            else "personal_emotional"
        )
        return _finish(
            intent=QuestionIntent.NEUTRAL,
            reason=reason,
            category="SMALL_TALK" if reason != "personal_emotional" else "PERSONAL_EMOTIONAL",
            decision=WebDecision.NEVER,
            confidence=0.99,
            reason_codes=[reason],
            scores=scores,
        )

    if creative:
        return _finish(
            intent=QuestionIntent.NEUTRAL,
            reason="creative_roleplay",
            category="CREATIVE_ROLEPLAY",
            decision=WebDecision.NEVER,
            confidence=0.95,
            reason_codes=["creative_roleplay"],
            scores=scores,
        )

    if user_content:
        return _finish(
            intent=QuestionIntent.NEUTRAL,
            reason="user_provided_content",
            category="USER_PROVIDED_CONTENT",
            decision=WebDecision.NEVER,
            confidence=0.94,
            reason_codes=["user_provided_content"],
            scores=scores,
        )

    # 显式搜索、URL、实时信息和外部实体是确定性主搜索。
    if explicit_search or has_url or (current and (question_like or real_world or current_request)) or real_world:
        reason = (
            "explicit_search"
            if explicit_search
            else "external_url"
            if has_url
            else "temporal_intent"
            if current
            else "real_world_signal"
        )
        return _finish(
            intent=QuestionIntent.WEB_SEARCH,
            reason=reason,
            category="CURRENT_REAL_WORLD",
            decision=WebDecision.PRIMARY,
            confidence=0.98 if explicit_search else 0.94,
            reason_codes=[reason],
            scores=scores,
        )

    if entity_question and not domain_subject and not static_knowledge:
        return _finish(
            intent=QuestionIntent.WEB_SEARCH,
            reason="entity_not_in_domain",
            category="EXTERNAL_ENTITY",
            decision=WebDecision.PRIMARY,
            confidence=0.9,
            reason_codes=["external_entity"],
            scores=scores,
        )

    # 本地世界观/角色资料先查知识库；低置信度时由 chat 层回退网页。
    if has_domain:
        return _finish(
            intent=QuestionIntent.KNOWLEDGE_FIRST,
            reason="domain_lore" if static_knowledge or entity_question else "domain_fallback",
            category="LOCAL_KNOWLEDGE",
            decision=WebDecision.FALLBACK,
            confidence=0.88,
            reason_codes=["local_domain", "knowledge_first"],
            scores=scores,
            allow_web_fallback=True,
        )

    # 技术操作具有版本差异，但不一定值得预搜索；允许模型在缺信息时调用一次工具。
    if technical_howto:
        return _finish(
            intent=QuestionIntent.NEUTRAL,
            reason="technical_how_to",
            category="HOW_TO_TECHNICAL",
            decision=WebDecision.TOOL_ALLOWED,
            confidence=0.68,
            reason_codes=["technical_how_to", "model_tool_allowed"],
            scores=scores,
            allow_model_tool=True,
        )

    if static_knowledge or question_like:
        return _finish(
            intent=QuestionIntent.NEUTRAL,
            reason="general_static_knowledge",
            category="GENERAL_STATIC_KNOWLEDGE",
            decision=WebDecision.NEVER,
            confidence=0.84 if static_knowledge else 0.72,
            reason_codes=["static_knowledge" if static_knowledge else "question_form"],
            scores=scores,
        )

    return _finish(
        intent=QuestionIntent.NEUTRAL,
        reason="no_strong_signal",
        category="AMBIGUOUS",
        decision=WebDecision.TOOL_ALLOWED if question_like else WebDecision.NEVER,
        confidence=0.45 if question_like else 0.7,
        reason_codes=["ambiguous" if question_like else "no_strong_signal"],
        scores=scores,
        allow_model_tool=question_like,
    )


def classify_question_intent_legacy(text: str) -> IntentDecision:
    """影子统计用的旧版近似决策，不参与线上路由。"""
    stripped = _strip(text)
    if not stripped or _SHORT_SMALLTALK_RE.fullmatch(stripped) or _ASKS_USER_IDENTITY_RE.fullmatch(stripped):
        return _finish(
            intent=QuestionIntent.NEUTRAL,
            reason="legacy_neutral",
            category="LEGACY_NEUTRAL",
            decision=WebDecision.NEVER,
            confidence=0.8,
            reason_codes=["legacy"],
            scores={},
        )
    if any(term in stripped for term in DOMAIN_TERMS):
        return _finish(
            intent=QuestionIntent.KNOWLEDGE_FIRST,
            reason="legacy_domain",
            category="LEGACY_KNOWLEDGE_FIRST",
            decision=WebDecision.FALLBACK,
            confidence=0.7,
            reason_codes=["legacy"],
            scores={},
            allow_web_fallback=True,
        )
    if _QUESTION_LIKE_RE.search(stripped) or _CURRENT_RE.search(stripped):
        return _finish(
            intent=QuestionIntent.WEB_SEARCH,
            reason="legacy_web",
            category="LEGACY_WEB_SEARCH",
            decision=WebDecision.PRIMARY,
            confidence=0.7,
            reason_codes=["legacy"],
            scores={},
        )
    return _finish(
        intent=QuestionIntent.NEUTRAL,
        reason="legacy_neutral",
        category="LEGACY_NEUTRAL",
        decision=WebDecision.NEVER,
        confidence=0.7,
        reason_codes=["legacy"],
        scores={},
    )


def should_web_search(text: str) -> bool:
    return classify_question_intent(text).intent is QuestionIntent.WEB_SEARCH


def looks_like_question_text(text: str) -> bool:
    """判断文本是否像提问，供群聊自然语言回复策略使用。"""
    return _is_question_like(_strip(text))

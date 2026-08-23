"""问题意图分层判定：智能区分“世界观知识问题 / 现实时效问题 / 人格寒暄”。

设计原则（避免词表一刀切）：
- 不因为出现“鸣潮/守岸人”就一律禁止联网；
- 也不因为出现“今天/最新”就一律联网；
- 先判断**问的是什么**（意图），再结合**领域词**做证据叠加；
- 判定不了时返回 neutral：不联网、交给人格大模型回答（宁可慢一点少搜，
  也不为了“搜一下”走错路或拖慢所有对话）。

三层信号：
1. 现实时效意图（新闻/更新/版本/价格/汇率/开服/上线/什么时候…）→ 联网；
2. 世界观知识意图（是什么/介绍/背景/设定/剧情/角色/在哪/为什么叫…）→ 只走本地知识库；
3. 人格寒暄（心情/感受/在吗/陪我/你是谁…）→ neutral，交给大模型。

规则优先级（带理由、可审计）：
A. 现实行情信号（价格/汇率/行情…）→ web_search（即便带世界观词，例如“今州房价”）；
B. 时效意图（最新/今天/更新/版本/什么时候…）→ web_search，
   但若同时是“问机器人本人的状态/心情”则降级，不联网；
C. 世界观词 + 知识意图 → knowledge_only；
D. 世界观词且无时效/现实意图 → knowledge_only（本地知识库兜底）；
E. 其余 → neutral（不联网，不拖慢）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class QuestionIntent(str, Enum):
    KNOWLEDGE_ONLY = "knowledge_only"
    WEB_SEARCH = "web_search"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class IntentDecision:
    intent: QuestionIntent
    reason: str


# 世界观/领域词（出现这些词只说明“话题在领域内”，不代表不能联网）。
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
)

# 世界观知识意图：问“是什么/介绍/设定”这类静态知识。
_LORE_INTENT_RE = re.compile(
    r"(是什么|是什么东西|是什么意思|什么意思|介绍|背景|设定|剧情|世界观|"
    r"人物|角色|武器|能力|技能|在哪里|在哪儿|干什么|为什么叫|由来|典故|"
    r"人设|档案|属性|阵营|关系|是谁|怎么样的人物)"
)

# 现实时效意图：这类问题答案会随时间变化，需要联网保鲜。
_CURRENT_INTENT_RE = re.compile(
    r"(今天|今日|现在|目前|最新|最近|新闻|消息|更新|版本|公告|维护|"
    r"开服|上线|发布|首发|前瞻|直播|什么时候|何时|几点|几号|多少抽|"
    r"卡池|活动|限定|复刻|加强|削弱|改动|实装|官宣)"
)

# 现实行情/现实世界信号：这类问题几乎必然是现实信息。
_REAL_WORLD_RE = re.compile(
    r"(价格|多少钱|汇率|股票|股价|行情|房价|放假|倒闭|收购|曝光|"
    r"现实中|真实世界|现实里|实际上|官方|官宣|公司|工作室|开发商|制作人)"
)

# 人格寒暄：问机器人本人状态/情绪，不需要联网。
_SELF_CHAT_RE = re.compile(
    r"(心情|感受|感觉|累|困|饿|难过|开心|快乐|害怕|孤单|寂寞|"
    r"陪我|陪我说|聊天|喜欢|爱|想你|在吗|你好|早上好|中午好|晚上好|"
    r"晚安|早安|谢谢|抱歉|辛苦|抱抱|摸摸)"
)

# “你最近怎么样/你还好吗”这类指向对话对象本人状态的寒暄。
_YOU_STATE_RE = re.compile(
    r"(你最近怎么样|你怎么样|你还好吗|你好吗|最近好吗|"
    r"你好不好|你心情|你感觉|你累不累|你困不困|你饿不饿)"
)

# 天气小聊（不是天气查询命令）：保持 neutral，交给对话层。
_WEATHER_SMALLTALK_RE = re.compile(
    r"(天气不错|天气真好|天气好|今天天气|明天天气|好热|好冷|下雨了|降温了)"
)

# 直接问“你是谁/你叫什么”这类机器人身份问题。
_ASKS_BOT_RE = re.compile(
    r"(你是谁|你叫什么|你是什么|你多大了|介绍你自己|介绍一下你自己|"
    r"你是机器人吗|你是ai吗|你是人工智能吗)"
)


def _strip(text: str) -> str:
    return (text or "").strip()


def classify_question_intent(text: str) -> IntentDecision:
    """分层判定问题意图；返回带理由的决策，便于审计与回归测试。"""
    stripped = _strip(text)
    if not stripped:
        return IntentDecision(QuestionIntent.NEUTRAL, "empty")

    has_domain = any(term in stripped for term in DOMAIN_TERMS)
    lore_intent = bool(_LORE_INTENT_RE.search(stripped))
    you_state = bool(_YOU_STATE_RE.search(stripped))
    weather_smalltalk = bool(_WEATHER_SMALLTALK_RE.search(stripped))
    current_intent = bool(_CURRENT_INTENT_RE.search(stripped))
    real_world = bool(_REAL_WORLD_RE.search(stripped))
    self_chat = bool(_SELF_CHAT_RE.search(stripped))
    asks_bot = bool(_ASKS_BOT_RE.search(stripped))

    # 直接问机器人身份 → 人格知识，不联网。
    if asks_bot and has_domain:
        return IntentDecision(QuestionIntent.KNOWLEDGE_ONLY, "asks_bot_identity")

    # 天气小聊/寒暄不是时效查询，不联网。
    if weather_smalltalk:
        return IntentDecision(QuestionIntent.NEUTRAL, "weather_smalltalk")

    # “你最近怎么样/你还好吗”指向对话对象本人，不联网。
    if you_state:
        return IntentDecision(QuestionIntent.NEUTRAL, "you_state_chat")

    # A. 现实行情/现实世界信号最优先：即使带领域词也要联网保鲜。
    if real_world and not asks_bot:
        return IntentDecision(QuestionIntent.WEB_SEARCH, "real_world_signal")

    # B. 时效意图：联网；但问机器人本人的状态/情绪时降级，不联网。
    if current_intent:
        if self_chat:
            if has_domain:
                return IntentDecision(
                    QuestionIntent.KNOWLEDGE_ONLY, "temporal_but_self_chat"
                )
            return IntentDecision(QuestionIntent.NEUTRAL, "self_chat")
        return IntentDecision(QuestionIntent.WEB_SEARCH, "temporal_intent")

    # C. 领域词 + 知识意图 → 本地知识库。
    if has_domain and lore_intent:
        return IntentDecision(QuestionIntent.KNOWLEDGE_ONLY, "domain_lore")

    # D. 领域词但没有时效/现实意图 → 本地知识库兜底。
    if has_domain:
        return IntentDecision(QuestionIntent.KNOWLEDGE_ONLY, "domain_fallback")

    # E. 其余：neutral，不联网、不拖慢，交给大模型。
    return IntentDecision(QuestionIntent.NEUTRAL, "no_strong_signal")


def should_web_search(text: str) -> bool:
    return classify_question_intent(text).intent is QuestionIntent.WEB_SEARCH

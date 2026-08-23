"""问题意图分层判定 v2：不斩断联网权限。

核心变化（相比 v1）：
- 不再因为出现“鸣潮/守岸人”就永远禁止联网；
- 对“X是什么/是谁”这类实体问句，先看 X 是否是领域词：
  - 是领域词 → 先走本地知识库，但携带 allow_web_fallback；
  - 不是领域词（如“习近平是谁/库洛是什么公司”）→ 直接联网做百科检索；
- 现实信号（公司/所在地/演唱会/音乐会/活动/价格/时间地点…）永远放行联网；
- 本地知识库检索“不可答/置信度过低”时，即便领域词问题也允许回退联网
  （由 chat 能力根据 RetrievalResult.answerable/confidence 决定）。

规则优先级（每条带 reason，可审计）：
A. 天气小聊 / “你最近怎么样” / 问机器人身份 → 不联网；
B. 现实信号（公司/官方/所在地/演唱会/音乐会/漫展/价格/汇率/新闻/现实…）→ 联网；
C. 时效信号（今天/最新/更新/版本/什么时候/开服/复刻/活动…）→ 联网；
D. 实体问句（是什么/是谁/是什么样的/介绍/背景）：
   - 实体非领域词 → 联网（百科）；
   - 实体是领域词 → 本地知识库优先 + 允许回退联网；
E. 领域词 + 知识意图 → 本地知识库优先 + 允许回退联网；
F. 领域词（无强信号）→ 本地知识库优先 + 允许回退联网；
G. 其余 → neutral（一般知识交给大模型，不联网、不拖慢）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class QuestionIntent(str, Enum):
    KNOWLEDGE_FIRST = "knowledge_first"
    WEB_SEARCH = "web_search"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class IntentDecision:
    intent: QuestionIntent
    reason: str
    # True 表示：本地知识库不可答/置信度过低时，允许回退联网（不斩断搜索权限）。
    allow_web_fallback: bool = False


# 世界观/领域词（只表示“话题在领域内”，不再作为禁网依据）。
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

# 现实信号：出现这些词几乎必然是现实世界问题，必须放行联网。
_REAL_WORLD_RE = re.compile(
    r"(价格|多少钱|汇率|股票|股价|行情|房价|放假|倒闭|收购|曝光|"
    r"现实中|真实世界|现实里|实际上|官方|官宣|官网|公司|工作室|开发商|制作人|创始人|"
    r"所在地|位于|总部|地址|在哪|在哪个城市|员工|作品|代表作|演唱会|音乐会|"
    r"漫展|线下|举办|门票|时间地点|展览|访谈|采访|新闻|热搜|百科)"
)

# 时效信号：答案随时间变化，联网保鲜。
_CURRENT_INTENT_RE = re.compile(
    r"(今天|今日|现在|目前|最新|最近|新闻|消息|更新|版本|公告|维护|"
    r"开服|上线|发布|首发|前瞻|直播|什么时候|何时|几点|几号|多少抽|"
    r"卡池|活动|限定|复刻|加强|削弱|改动|实装|官宣|公告|预告|解禁|发售)"
)

# 实体问句：问某个名词“是什么/是谁”。
_ENTITY_QUESTION_RE = re.compile(
    r"(是什么|是谁|是什么样|是什么样的|介绍一下|介绍|百科|背景|来历)"
)

# 知识意图（领域内静态知识）。
_LORE_INTENT_RE = re.compile(
    r"(是什么|是什么东西|是什么意思|什么意思|介绍|背景|设定|剧情|世界观|"
    r"人物|角色|武器|能力|技能|在哪里|在哪儿|干什么|为什么叫|由来|典故|"
    r"人设|档案|属性|阵营|关系|是谁|怎么样的人物)"
)

# 人格寒暄：问机器人本人状态/情绪，不联网。
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

# 提取“X是什么/是谁”里的 X（用于判断是否领域词）。
_ENTITY_SUBJECT_RE = re.compile(
    r"^(.{1,24}?)(?:是什么|是谁|是什么样|是什么样的|介绍一下|百科|来历)"
)


def _strip(text: str) -> str:
    return (text or "").strip()


def _domain_subject_present(text: str) -> bool:
    match = _ENTITY_SUBJECT_RE.match(text)
    if not match:
        return any(term in text for term in DOMAIN_TERMS)
    subject = match.group(1).strip("，。？?!！、 ")
    return any(term in subject for term in DOMAIN_TERMS) or any(
        term in text for term in DOMAIN_TERMS
    )


def classify_question_intent(text: str) -> IntentDecision:
    """分层判定问题意图；返回带理由的决策，便于审计与回归测试。"""
    stripped = _strip(text)
    if not stripped:
        return IntentDecision(QuestionIntent.NEUTRAL, "empty")

    asks_bot = bool(_ASKS_BOT_RE.search(stripped))
    weather_smalltalk = bool(_WEATHER_SMALLTALK_RE.search(stripped))
    you_state = bool(_YOU_STATE_RE.search(stripped))
    self_chat = bool(_SELF_CHAT_RE.search(stripped))
    real_world = bool(_REAL_WORLD_RE.search(stripped))
    current_intent = bool(_CURRENT_INTENT_RE.search(stripped))
    entity_question = bool(_ENTITY_QUESTION_RE.search(stripped))
    lore_intent = bool(_LORE_INTENT_RE.search(stripped))
    domain_subject = _domain_subject_present(stripped)
    has_domain = any(term in stripped for term in DOMAIN_TERMS)

    # 直接问机器人身份 → 人格知识，不联网。
    if asks_bot:
        return IntentDecision(
            QuestionIntent.KNOWLEDGE_FIRST, "asks_bot_identity", allow_web_fallback=False
        )

    # 天气小聊/寒暄不是时效查询，不联网。
    if weather_smalltalk:
        return IntentDecision(QuestionIntent.NEUTRAL, "weather_smalltalk")
    if you_state:
        return IntentDecision(QuestionIntent.NEUTRAL, "you_state_chat")

    # B. 现实信号：永远放行联网（不因领域词被切断）。
    if real_world:
        return IntentDecision(QuestionIntent.WEB_SEARCH, "real_world_signal")

    # C. 时效信号：联网；问机器人本人状态/情绪时降级，不联网。
    if current_intent:
        if self_chat:
            return IntentDecision(
                QuestionIntent.KNOWLEDGE_FIRST if has_domain else QuestionIntent.NEUTRAL,
                "temporal_but_self_chat",
                allow_web_fallback=False,
            )
        return IntentDecision(QuestionIntent.WEB_SEARCH, "temporal_intent")

    # D. 实体问句：非领域词 → 百科联网；领域词 → 知识库优先 + 允许回退联网。
    if entity_question:
        if not domain_subject:
            return IntentDecision(QuestionIntent.WEB_SEARCH, "entity_not_in_domain")
        return IntentDecision(
            QuestionIntent.KNOWLEDGE_FIRST, "entity_in_domain", allow_web_fallback=True
        )

    # E/F. 领域词 → 知识库优先，但允许回退联网（不斩断权限）。
    if has_domain and lore_intent:
        return IntentDecision(
            QuestionIntent.KNOWLEDGE_FIRST, "domain_lore", allow_web_fallback=True
        )
    if has_domain:
        return IntentDecision(
            QuestionIntent.KNOWLEDGE_FIRST, "domain_fallback", allow_web_fallback=True
        )

    # G. 其余：neutral，不联网、不拖慢，交给大模型。
    return IntentDecision(QuestionIntent.NEUTRAL, "no_strong_signal")


def should_web_search(text: str) -> bool:
    return classify_question_intent(text).intent is QuestionIntent.WEB_SEARCH

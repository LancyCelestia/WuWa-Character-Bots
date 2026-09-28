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

# 本地域词表的外部游戏段由此派生（同源，不手抄名单）：``search_intent`` 只依赖
# 标准库，没有回灌 chat_reply，因此模块级导入无环；``ACG_DOMAIN_TERMS`` 是
# 「这句是不是二游题」的唯一词表真身，本件只是它的另一个消费方。
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    ACG_DOMAIN_TERMS,
    ACG_TIER_STRONG,
)

_ACG_GAME_DOMAIN: str = "game"


class QuestionIntent(str, Enum):
    KNOWLEDGE_FIRST = "knowledge_first"
    WEB_SEARCH = "web_search"
    NEUTRAL = "neutral"


class TimelyDomain(str, Enum):
    """「该往哪儿搜、该信谁」的垂直分域（2026-09-25 用户裁定第 3 项）。

    旧实现只有一条时效判据（`_CURRENT_RE` 一类时间词），所以「美联储加息了吗」
    和「鸣潮新版本更新了什么」走的是同一套检索扩展与同一份来源优先级——
    于是金融题被补上「萌娘百科」这个扩展词、来源表又把所有查询的
    第一名都给萌百。本枚举是分流的唯一入口。

    与 `category`（意图分类，管"要不要联网"）是两回事：这里管"联网之后偏向谁"。
    """

    FINANCE = "finance_economy"        # 金融/经济/行情/货币/财政
    CURRENT_AFFAIRS = "current_affairs"  # 时政/国际关系/政策/任免
    TECH = "tech"                      # 科技/产品/公司/AI/芯片
    NEWS = "news"                      # 泛新闻（最宽，故排在最后判）
    ANIME_LORE = "anime_lore"          # 二游角色/剧情/事件/人事物（本地库优先）
    GENERAL = "general"


# 各域的锚点词。刻意只收"成词的现实名词"，不收"最新/今天"这类纯时间词——
# 那是 `_CURRENT_RE` 的活，重复收一份就是第二真身。
_FINANCE_RE = re.compile(
    r"(美联储|央行|人民银行|证监会|银监会|保监会|财政部|发改委|统计局|"
    r"加息|降息|降准|利率|LPR|逆回购|MLF|国债|地方债|专项债|"
    r"汇率|兑换|人民币|美元|欧元|日元|英镑|韩元|新台币|澳门元|迪拉姆|"
    r"股票|股价|股市|A股|港股|美股|指数|上证|深证|恒生|纳斯达克|道琼斯|"
    r"标普|富时|日经|KOSPI|MOEX|北向|资金流|市值|市盈率|分红|回购|"
    r"基金|ETF|理财|保险|养老金|社保|黄金|金价|白银|原油|石油|铜铝|"
    r"大宗商品|期货|现货|债券|收益率|通胀|通缩|CPI|PPI|GDP|PMI|"
    r"进出口|贸易顺差|外汇储备|房价|楼市|楼市政策|工资|收入|就业|失业|"
    r"失业率|消费|零售|旅游收入|票房|营收|财报|业绩|利润|亏损|并购|重组|"
    r"上市|退市|IPO|定增|减持|股权|估值|独角兽|供应链|产能|订单)"
)
_AFFAIRS_RE = re.compile(
    r"(国务院|全国人大|政协|两会|人大|代表|委员|部委|政府|市政|"
    r"政策|法规|条例|新规|办法|意见|白皮书|发布会|吹风会|"
    r"主席|总理|副总理|部长|省长|市长|书记|任免|任命|免去|当选|连任|"
    r"外交|发言人|外交部|使馆|领事|签证|入境|出境|免签|"
    r"选举|投票|公投|民调|议会|国会|总统|首相|总理任期|"
    r"俄乌|俄伊|以伊|巴以|加沙|黎巴嫩|台海|朝鲜|半岛|南海|中印|"
    r"中美|中俄|中欧|欧盟|北约|上合|金砖|联合国|安理会|G7|G20|APEC|"
    r"关税|制裁|禁运|出口管制|实体清单|脱钩|去风险|"
    r"战争|停火|和谈|峰会|声明|抗议|引渡|判决|审判|立案|调查组|"
    r"地震|震级|台风|洪涝|旱灾|山火|疫情|流感|疫苗|停课|撤离|救援)"
)
_TECH_RE = re.compile(
    r"(芯片|半导体|晶圆|光刻|制程|纳米|GPU|CPU|NPU|处理器|显卡|"
    r"人工智能|AI|大模型|LLM|GPT|Gemini|Claude|文心|通义|DeepSeek|"
    r"开源|模型发布|训练|推理|参数|多模态|智能体|Agent|"
    r"手机|旗舰|发布会|新机|系统|鸿蒙|iOS|安卓|Android|"
    r"汽车|新能源|电池|续航|自动驾驶|智驾|整车|车企|"
    r"火箭|卫星|航天|空间站|探月|量子|核聚变|脑机|"
    r"苹果|谷歌|微软|英伟达|特斯拉|OpenAI|Anthropic|Meta|亚马逊|"
    r"华为|小米|OPPO|vivo|字节|腾讯|阿里|京东|美团|比亚迪|宁德时代|"
    r"机器人|人形|无人机|低空|5G|6G|算力|数据中心|云服务|操作系统)"
)
_NEWS_RE = re.compile(
    r"(新闻|快讯|报道|消息称|据悉|刚刚|近日|今日|昨天|上周|本月|"
    r"官方公告|通报|披露|宣布|启动|落地|出台|发生|事故|"
    r"头条|热搜|舆论|媒体|记者|专访|独家)"
)
# 二游/ACG 本地域锚点：判定直接复用 DOMAIN_TERMS（唯一真身），不另立词表。
_ANIME_LORE_HINT_RE = re.compile(
    r"(角色|剧情|版本卡池|卡池|复刻|实装|立绘|声优|CV|配音|"
    r"世界观|设定|主线|活动剧情|好感|命座|影装|武器|"
    r"萌娘百科|BWIKI|PRTS|灰机|wiki)",
    re.IGNORECASE,
)


def classify_timely_domain(
    text: str,
    *,
    in_local_domain: bool = False,
) -> str:
    """这条问题属于哪个垂直域；返回 `TimelyDomain` 的值。

    判序是**有意**的：
    ① 本地已知的二游话题（`in_local_domain`，由调用方从 DOMAIN_TERMS 传进来）
       优先判 ANIME_LORE——「鸣潮新版本更新了什么」既含时间词又含游戏词，
       它该走本地库 + 萌百，不该被当成时政/科技题推到通用新闻源。
    ② 金融先于时政先于科技：三者都可能含"公司/发布/价格"这类共用词，
       越具体的域先判，否则被宽域抢走。
    ③ NEWS 最宽，放最后当兜底；都不命中才是 GENERAL。
    """
    stripped = str(text or "").strip()
    # 本地锚点在本函数内自己查 DOMAIN_TERMS（唯一真身），不要求调用方记得传旗标——
    # 靠调用方自觉的判据总有一天会被某条路径忘掉。
    if in_local_domain or any(
        term.casefold() in stripped.casefold() for term in DOMAIN_TERMS
    ):
        return TimelyDomain.ANIME_LORE.value
    if not stripped:
        return TimelyDomain.GENERAL.value
    if _FINANCE_RE.search(stripped):
        return TimelyDomain.FINANCE.value
    if _AFFAIRS_RE.search(stripped):
        return TimelyDomain.CURRENT_AFFAIRS.value
    if _TECH_RE.search(stripped):
        return TimelyDomain.TECH.value
    if _NEWS_RE.search(stripped) or _ANIME_LORE_HINT_RE.search(stripped):
        # 泛新闻算一类；带"角色/剧情/卡池"这类 ACG 提示但没有本地锚点的，
        # 也归到 ANIME_LORE——它想要的是百科型来源，不是财经媒体。
        return (
            TimelyDomain.ANIME_LORE.value
            if _ANIME_LORE_HINT_RE.search(stripped)
            else TimelyDomain.NEWS.value
        )
    return TimelyDomain.GENERAL.value


def is_encyclopedic_domain(value: str) -> bool:
    """该域是否该用百科/社区型来源（萌百·维基·B站）而不是财经时政媒体。"""
    return value == TimelyDomain.ANIME_LORE.value


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
#
# 分成两段是刻意的（T4①，2026-09-28）：
# * ``_SHOREKEEPER_DOMAIN_TERMS``＝本 bot 自有的人格/世界观锚点（鸣潮/库洛/角色名…），
#   这份是真·本地设定，没有别处可取，只能登记在此；
# * ``_EXTERNAL_GAME_DOMAIN_TERMS``＝**外部游戏域**（原神/星穹铁道/FGO…）——它们在库里
#   有整套语料，却长期不在本地域词表里，于是「原神谁是最强的角色」既不判 LOCAL_KNOWLEDGE、
#   也不走"本地优先、低置信才补网"，而是直接被当域外实体推去联网。
#   这段**一律不手写**：真身是检索意图词表 ``search_intent.ACG_DOMAIN_TERMS["game"]``
#   的强专名档（同一批语料"是不是二游题"的判据本来就住在那里，抄第二份必漂——规则 10）。
#   同源锁见 ``tests/test_question_intent.py``：词表加一域、这里没跟上即红。
# 「明日方舟·终末地」按需求明确不加：它不在强专名档，因此也不会被带进来。
_SHOREKEEPER_DOMAIN_TERMS: tuple[str, ...] = (
    "鸣潮",
    "战双",
    "战双帕弥什",
    "库洛",
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


def _external_game_domain_terms() -> tuple[str, ...]:
    """外部游戏域锚点：由检索意图词表的强专名档现取（不在这里抄一遍名单）。"""
    try:
        tier = ACG_DOMAIN_TERMS[_ACG_GAME_DOMAIN][ACG_TIER_STRONG]
    except KeyError:  # pragma: no cover - 词表改名/改结构时必须在这里现形
        raise RuntimeError(
            "本地域词表依赖的检索意图词表结构变了："
            f"缺少 {ACG_DOMAIN_TERMS!r} 的 {_ACG_GAME_DOMAIN!r}/{ACG_TIER_STRONG!r} 一档，"
            "请同步修 question_intent._external_game_domain_terms（不许改成手写名单）"
        ) from None
    return tuple(str(term) for term in tier)


_External_GAME_DOMAIN_TERMS: tuple[str, ...] = _external_game_domain_terms()

#: 本地域词表**唯一真身**：自有设定 ∪ 在库的外部游戏域（去重、保持登记序）。
DOMAIN_TERMS: tuple[str, ...] = tuple(
    dict.fromkeys(_SHOREKEEPER_DOMAIN_TERMS + _External_GAME_DOMAIN_TERMS)
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
    r"(今天|今日|现在|目前|最新|最近|新闻|消息|更新|进展|版本|公告|维护|"
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
# 域外现实实体锚点：本仓既无厂商/产品名册、也不认版本号形态，故此枚是新概念真身
# （非既有词表的第二份副本）。命中它仅代表“可能是域外现实话题”，仍须叠加
# 问法/时效信号才判检索，避免单个通名把普通对话送上网。
# 拉丁品牌/AI 一律用拉丁环视限定，防止 email/explain/said/pineapple 之类子串误命中。
_EXTERNAL_ENTITY_RE = re.compile(
    r"(英伟达|英特尔|台积电|三星|华为|小米|比亚迪|特斯拉|苹果|谷歌|微软|亚马逊|"
    r"半导体|芯片|大模型|算力|光刻机|美联储|央行|证监会|纳斯达克|道琼斯|"
    r"(?<![A-Za-z])(OpenAI|Anthropic|Claude|ChatGPT|GPT|Gemini|Sora|DeepSeek"
    r"|LLaMA|Copilot|AMD|Intel|Nvidia|AI)(?![A-Za-z])|"
    r"[A-Za-z][A-Za-z0-9]*\s*[-]?\d+\.\d+)",
    re.IGNORECASE,
)
_ENTITY_QUESTION_RE = re.compile(
    r"(是什么|是谁|是什么样|介绍一下|介绍|百科|背景|来历|在哪里|在哪儿|哪家公司)"
)
# 纯评价/意见问法：句子里虽含现实域锚点（手机/昨天…），但用户要的是「你怎么看」
# 而非「去查一个事实」。把它当新概念真身登记在此，供 PRIMARY 判据一票否决，
# 免得「这款手机好不好用」「昨天那场球怎么看」这类意见句被域词表顺手拖上网。
_OPINION_EVAL_RE = re.compile(
    r"(好不好|好用吗|怎么样|值得买|值不值|靠不靠谱|怎么评价|如何看待|怎么看|"
    r"好不好看|好看吗|帅不帅|强不强)"
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
_QUESTION_WORD_RE = re.compile(
    r"(什么时候|何时|几点|多少|哪里|哪儿|什么|谁|是否|怎么回事|怎么样"
    r"|好不好|好用|怎么看|了解|知道吗)"
)

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
    external_entity_anchor = bool(_EXTERNAL_ENTITY_RE.search(stripped))
    entity_question = bool(_ENTITY_QUESTION_RE.search(stripped))
    static_knowledge = bool(_STATIC_KNOWLEDGE_RE.search(stripped))
    # 「要不要搜」直接复用「搜了之后信谁」那四张表（经 classify_timely_domain 单一真身），
    # 不再新建第二份词表（规则 10）。命中时政/金融/科技/新闻任一现实域、且本地域未抢先、
    # 又不是纯意见问法或稳定常识，就构成确定性主搜索——这正是审计席 22 句实测恒判 never
    # 的根因：那四张表过去只参与检索后的来源排序，从没接进 PRIMARY。
    _timely = classify_timely_domain(stripped, in_local_domain=has_domain)
    opinion_eval = bool(_OPINION_EVAL_RE.search(stripped))
    timely_reality = (
        _timely
        in (
            TimelyDomain.FINANCE.value,
            TimelyDomain.CURRENT_AFFAIRS.value,
            TimelyDomain.TECH.value,
            TimelyDomain.NEWS.value,
        )
        and not static_knowledge
        and not opinion_eval
    )
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
    if external_entity_anchor:
        scores["external_entity_anchor"] = 0.8
    if entity_question and not domain_subject and not static_knowledge:
        scores["external_entity"] = 0.8
    if timely_reality:
        scores["timely_domain_signal"] = 0.85
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

    # 显式搜索、URL、实时信息、外部实体，以及时效现实域是确定性主搜索。
    # 「……了吗」这类纯时效问句（LPR又降了吗）也归此支：它命中现实域即上网，
    # 不再恒判 never。
    if (
        explicit_search
        or has_url
        or (current and (question_like or real_world or current_request))
        or real_world
        or timely_reality
    ):
        reason = (
            "explicit_search"
            if explicit_search
            else "external_url"
            if has_url
            else "temporal_intent"
            if current
            else "real_world_signal"
            if real_world
            else "timely_domain_signal"
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

    # 域外现实实体（厂商/产品/币种专名或版本号形态）叠加问法·时效信号即判检索。
    # 置于 has_domain 之前：本地世界观与游戏问句里没有这些外部名，不会被误抢；
    # 反过来「@守岸人 英伟达财报怎么看」这类“直呼bot + 域外现实话题”应走检索而非本地库。
    # 单独命中实体名而无任何问法/时效词不触发，避免「手机/公司」这类通名把闲聊送上网。
    if external_entity_anchor and (question_like or current or current_request):
        return _finish(
            intent=QuestionIntent.WEB_SEARCH,
            reason="external_entity_topic",
            category="CURRENT_REAL_WORLD",
            decision=WebDecision.PRIMARY,
            confidence=0.9,
            reason_codes=["external_entity_topic"],
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


def looks_like_question_text(text: str) -> bool:
    """判断文本是否像提问，供群聊自然语言回复策略使用。"""
    return _is_question_like(_strip(text))


# ---------------------------------------------------------------------------
# T6 回复形态判据（2026-09-27）：把「题型」从联网意图之外补两格，接入既有派生表。
# 刻意复用 _ENTITY_QUESTION_RE（真身已在），不另起「介绍/历史」词表（规则 10）。
# ---------------------------------------------------------------------------

def wants_narrative_shape(text: str) -> bool:
    """「介绍人物/事件/物品/来历/背景/百科」类叙述题：交付要展开，不砍成一句话。

    只认既有的 _ENTITY_QUESTION_RE（介绍一下/介绍/背景/来历/是什么/是谁/百科…），
    避免把「历史/经历/来龙去脉」再抄成第二张表；这类词通常也与介绍共现。
    """
    return bool(_ENTITY_QUESTION_RE.search(_strip(text)))


# 纯是非/单点时效事实（「LPR又降了吗」）——搜到即可短答，别为凑长度写小作文。
# 这是新概念谓词（如 _EXTERNAL_ENTITY_RE 先例），不是既有词表的副本。
_BRIEF_FACTUAL_RE = re.compile(r"(了吗|了么|过吗|是不是|有没有|要不要|行不行|成不成|是否)")


def looks_like_brief_factual(text: str) -> bool:
    """短小的是非/单点事实问句：判「简明事实」而非「详尽叙述」。"""
    stripped = _strip(text)
    if not stripped or len(stripped) > 24:
        return False
    return bool(_BRIEF_FACTUAL_RE.search(stripped))


# ---------------------------------------------------------------------------
# 联网行为的单一真身：可答性判定 + 检索决策（S13）
#
# 这一族是「行为」而非「观测」。观测面（intent_telemetry）只记录哈希/决策/命中，
# 绝不反过来左右是否联网；是否联网只由下面两个纯函数 + 两个行为阈值决定，
# 二者在 config 里明显区别于 bot_web_intent_telemetry_*。
# ---------------------------------------------------------------------------

# 提取检索相关性时视作「语法/疑问虚词」的字符：命中即从词元里剔除，
# 使置信度反映「主题实体是否被知识库覆盖」，而非「疑问词是否碰巧复现」。
# 只收纯功能词与疑问词，不收「游戏/角色/活动」这类主题词，避免误杀正文信号。
_RELEVANCE_STOP_CHARS = frozenset(
    "的了是在和与及或也都就很更太把被给让向对从以之其而但因所有个中上下"
    "这那些我你他她它们吗呢啊吧呀哦嗯么什怎如何哪些谁为请问一二三没要会"
    "能可该应得着过来去又再才已经"
)


def _relevance_terms(text: str) -> list[str]:
    """提取用于相关性打分的词元：拉丁/数字词 + 中文二元组，剔除语法/疑问虚词。

    与 ``vector_knowledge._query_terms`` 同族口径（拉丁词 + 中文 bigram），
    但额外过滤虚词，使置信度度量的是主题覆盖度。
    """
    raw: list[str] = []
    for match in re.finditer(r"[A-Za-z0-9_]+", text or ""):
        raw.append(match.group(0).lower())
    cjk = "".join(re.findall(r"[一-鿿]", text or ""))
    for index in range(max(0, len(cjk) - 1)):
        raw.append(cjk[index : index + 2])
    kept = [
        term
        for term in raw
        if not (len(term) == 2 and (term[0] in _RELEVANCE_STOP_CHARS or term[1] in _RELEVANCE_STOP_CHARS))
    ]
    return list(dict.fromkeys(kept))


def knowledge_confidence_from_evidence(
    query_text: str,
    chunk_contents: list[str],
) -> float:
    """由检索证据给出「知识库能否回答」的可复现置信度（0~1）。

    旧实现是「有块就恒定 0.8」的近似，把一次偶然词面命中也当成能答，直接
    压制了联网（S13 根因）。这里改成真实信号：**查询主题词元被检索到的知识
    块覆盖的比例**，再叠加多块佐证的小幅加分。纯函数、零外部调用、离线可复现。

    保守方向：语义相近但表面词不重叠时会低估置信度 → 倾向多搜一次，符合
    「宁可多搜也别误判成不用搜」。
    """
    terms = _relevance_terms(query_text)
    contents = [c for c in (chunk_contents or []) if c]
    if not terms or not contents:
        return 0.0
    joined = "\n".join(contents)
    covered = sum(1 for term in terms if term in joined)
    coverage = covered / len(terms)
    corroboration = min(0.15, 0.05 * max(0, len(contents) - 1))
    confidence = coverage + corroboration
    return round(max(0.0, min(1.0, confidence)), 4)


def decide_web_search(
    *,
    web_enabled: bool,
    decision: WebDecision,
    allow_web_fallback: bool,
    answerable: bool,
    confidence: float,
    chunk_count: int,
    knowledge_threshold: float,
    confidence_floor: float,
) -> bool:
    """联网是否执行的唯一行为判定（不写日志、不落库、只返回布尔）。

    分层：
    * 关联网 → 永不搜（行为总闸，不是观测）；
    * PRIMARY（显式搜索/时效/域外实体）→ 必搜；
    * FALLBACK（本地世界观/角色资料优先）→ 置信度低于阈值才补搜；
      且置信度低于**硬底线**时无条件补搜（安全阀，独立于可被调高/调低的阈值，
      防止本地知识近乎空白却被误判成「不用搜」）；
    * 其余（NEVER / TOOL_ALLOWED）→ 默认不搜，但 allow_web_fallback 为真
      （即分类器本就把它当本地知识候选）且置信度低于硬底线时补搜一次。
      闲聊/创作/用户自带内容/explicit_no_web 的 allow_web_fallback 恒为 False，
      因此永不会被安全阀拖上网。
    """
    if not web_enabled:
        return False
    threshold = max(0.0, min(1.0, float(knowledge_threshold)))
    floor = max(0.0, min(1.0, float(confidence_floor)))
    score = max(0.0, min(1.0, float(confidence)))
    if decision is WebDecision.PRIMARY:
        return True
    if decision is WebDecision.FALLBACK:
        if score < floor:  # 硬底线安全阀，优先于阈值
            return True
        return (not answerable) or (score < threshold) or (chunk_count <= 0)
    return bool(allow_web_fallback and score < floor)

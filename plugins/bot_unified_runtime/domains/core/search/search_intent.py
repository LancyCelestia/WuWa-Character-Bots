"""ACG 检索意图识别（v21r2 SEARCH 席）。

针对用户反馈「bot 对最新消息获取能力较差，尤其二次元/动漫番剧/漫画/B站热门梗/
二次元游戏」，本模块用词表+正则做**纯本地**意图检测（零网络、零 LLM 调用）：

1. 是否命中二次元检索意图（``AcgIntent.is_acg``）；
2. 命中哪些子域（anime/manga/game/meme/vtuber/bilibili 标签）；
3. 时效需求档（``latest``=最新动态 / ``background``=背景知识）；
4. 把口语问句洗成适合竖源（Bangumi/萌百/B站）的关键词；
5. 给 chat 层的门禁判定：哪些 ``classify_question_intent`` 的 NEVER reason
   允许被 ACG 专项检索放行（显式拒绝联网/闲聊/创作等安全类 NEVER 永不放行）。

边界声明：词表覆盖主流高热条目与黑话，不可能穷尽所有番剧/游戏名；
未命中词表的冷门条目靠模式规则（第N集/新番/卡池等）兜底，仍可能漏检——
漏检时行为与旧版完全一致（不搜索），属诚实降级而非回归。

2026-09-26 S-ACG-TIER 补一条同向边界：词表分 **strong/medium/weak** 三档，
弱档通用词（日常/毕业/切片…）单独命中一律不判 ⇒ 这类问句里若真在问二次元，
需要句内另有专名或模式线索才够得着竖源。这同样是**诚实降级**（少搜），
不是把不该搜的搜出来；换来的是「高血压病人日常吃什么药」不再被萌百回答。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "ACG_DOMAIN_TERMS",
    "ACG_TIERS",
    "ACG_TIER_MEDIUM",
    "ACG_TIER_STRONG",
    "ACG_TIER_WEAK",
    "TIMELINESS_BACKGROUND",
    "TIMELINESS_LATEST",
    "AcgIntent",
    "QueryRecency",
    "acg_query_variants",
    "acg_search_allowed",
    "detect_acg_intent",
    "detect_query_recency",
    "extract_acg_query",
]

TIMELINESS_LATEST = "latest"
TIMELINESS_BACKGROUND = "background"

# ---------------------------------------------------------------------------
# 词表（驱动式设计：全部集中在此，便于审计与扩充）
# ---------------------------------------------------------------------------
#
# 2026-09-26 S-ACG-TIER：词表由「一级平铺」改为**分档**。改前每一枚词都是同一种
# 证据——``鸣潮``（专名，别的语境不会这么说）与 ``日常``（普通汉语词，谁都会说）
# 在判据上完全等价，于是「我的工作日常真的很无聊」被当成二次元问句；而
# ``_NON_ACG_HINTS`` 那条反证又只在「一枚词都没命中」时才看（命中了泛用词就整段
# 绕过），等于拦不住任何东西。现算实证：改前有 21 句与二次元无关的话被这道门放行
# （名单见席报告 §行为变更清单，逐条锁在 ``tests/test_acg_intent_tiers.py``）。
#
# 三档语义（档位即下面注册表的键名，唯一真身就是那份表，别再抄第二份）：
#   ``strong`` 专名——作品名/公司名/团体名/平台名/角色名。单独命中即判 ACG，
#       且**不受反证词否决**：库里明明有的条目名，不该被「怎么做」挡在门外。
#   ``medium`` 域专名——番剧/卡池/中之人/鬼畜这一类，离开二次元基本没人说。
#       单独命中可判，但与 ``_NON_ACG_HINTS`` 共现时**判否**（共决，见 §裁决）。
#   ``weak``   通用汉语词——当年进表是因为它在二次元语境里高频（毕业/切片/复刻/
#       腰斩/高达/充电…），可它在别的语境里更高频，因此**永不单独成判**：
#       只在与 strong/medium/模式规则共现时贡献子域标签与审计词。

#: 档位名（判据读的就是这三个字面值）。
ACG_TIER_STRONG = "strong"
ACG_TIER_MEDIUM = "medium"
ACG_TIER_WEAK = "weak"

#: 遍历序＝判据优先级；每一枚词表词必须且只能落在其中一档。
ACG_TIERS: tuple[str, ...] = (ACG_TIER_STRONG, ACG_TIER_MEDIUM, ACG_TIER_WEAK)

#: 子域 → 档位 → 词表。**这张表就是词表本身**：新增词条必须显式选档，
#: 漏档或跨档重复都会被 ``tests/test_acg_intent_tiers.py`` 的分区锁打红。
ACG_DOMAIN_TERMS: dict[str, dict[str, tuple[str, ...]]] = {
    # 动画/番剧域：专名 + 类型词（类型词按"离开二次元还有多少人这么说"分档）
    "anime": {
        ACG_TIER_STRONG: (
            # 长青高热条目（中文名/通称）
            "芙莉莲", "葬送的芙莉莲", "鬼灭之刃", "咒术回战", "海贼王", "航海王",
            "火影忍者", "间谍过家家", "孤独摇滚", "进击的巨人",
            "约会大作战", "Re:0", "Re0", "无职转生", "药屋少女", "我推的孩子",
            "败犬女主", "义妹生活", "青之箱", "物语系列", "机动战士",
            "新世纪福音战士", "凉宫春日", "刀剑神域", "粗点心屋",
            # 2026-09-26 补：高热但此前判不出来的条目名（现算漏检锁）
            "辉夜大小姐", "命运石之门",
        ),
        ACG_TIER_MEDIUM: (
            "番剧", "新番", "动画", "动漫", "剧场版", "OAD", "OVA", "声优",
            "制作组", "作画", "放送", "动画化", "一月番", "四月番",
            "七月番", "十月番", "季番", "年番", "国创", "里番",
            # 「葬送」是通称截断、EVA 另有发泡材质义项：可判，但反证词能压住。
            "葬送", "EVA",
        ),
        # 「高达」＝"高达 30 度"的副词、「开播」电视剧/直播同样在说：降为提示级。
        ACG_TIER_WEAK: ("开播", "高达"),
    },
    # 漫画/轻小说域
    "manga": {
        ACG_TIER_STRONG: ("少年JUMP",),
        ACG_TIER_MEDIUM: ("漫画", "漫画家", "单行本", "汉化", "条漫", "轻小说"),
        # 原作/连载/停更/断更/日更 网文与公众号同样高频；腰斩 是股市口语；
        # jump 是英文常用动词——单独命中一律不算。
        ACG_TIER_WEAK: (
            "原作", "连载", "停更", "断更", "腰斩", "日更", "jump", "JUMP",
        ),
    },
    # 二次元游戏域（游戏名 + 圈内黑话）
    "game": {
        ACG_TIER_STRONG: (
            "原神", "星穹铁道", "崩坏3", "崩坏三", "绝区零", "鸣潮", "明日方舟",
            "米哈游", "miHoYo", "mihoyo", "库洛", "库街区", "鹰角",
            "尘白禁区", "重返未来1999", "深空之眼", "战双帕弥什", "蔚蓝档案",
            "碧蓝档案", "碧蓝航线", "少女前线", "少前2", "FGO", "fgo", "赛马娘",
            "公主连结", "碧蓝幻想", "无期迷途", "物华弥新", "白荆回廊", "异环",
            "无限暖暖", "二游", "二次元游戏", "深境螺旋", "星琼",
        ),
        ACG_TIER_MEDIUM: (
            "抽卡", "卡池", "大保底", "小保底", "UP池", "up池", "前瞻直播",
            "虚构叙事", "模拟宇宙", "合成区", "公测", "开服", "缠芯",
            # 「崩坏」既是社名也是"人设崩坏"这种普通说法：留中档，反证词压得住。
            "崩坏",
        ),
        ACG_TIER_WEAK: (
            "保底", "歪了", "复刻", "前瞻", "深渊", "追放", "原石", "蓝莓",
            "体力", "日常", "周本", "月卡", "版本更新", "周年庆",
        ),
    },
    # B站梗/黑话域
    "meme": {
        ACG_TIER_STRONG: ("梗百科", "拜年祭"),
        ACG_TIER_MEDIUM: (
            "梗", "名场面", "鬼畜", "弹幕", "百大", "UP主", "up主",
            "一键三连", "下次一定", "好活", "整活", "硬控", "锐评",
            "空耳", "生草", "洗脑循环", "名梗", "热梗", "烂梗", "玩梗",
            "小黑屋", "跨晚",
        ),
        # 充电＝手机充电、干杯＝饭桌用语、三连＝K线/赛况口语：只作共现提示。
        ACG_TIER_WEAK: ("三连", "充电", "干杯"),
    },
    # VTuber/虚拟主播域
    "vtuber": {
        ACG_TIER_STRONG: (
            # 2026-09-26 补：团体名与虚拟歌姬/虚拟主播条目名（现算漏检锁）。
            "hololive", "初音未来", "巡音流歌", "鹿鸣",
        ),
        ACG_TIER_MEDIUM: (
            "vtuber", "VTuber", "Vtuber", "V圈", "v圈", "中之人",
            "虚拟主播", "虚拟偶像", "转生", "初配信",
        ),
        # 毕业＝离校、切片＝厨房/化验、皮套＝手机壳：降为提示级。
        ACG_TIER_WEAK: ("皮套", "切片", "毕业"),
    },
    # B站平台域（平台专名：命中即说明用户在问 B站这件事本身）
    "bilibili": {
        ACG_TIER_STRONG: ("B站", "b站", "哔哩哔哩", "bilibili", "BILIBILI"),
        ACG_TIER_MEDIUM: ("小电视",),
        ACG_TIER_WEAK: (),
    },
}

# 旧坐标保留为**派生视图**（真身是上面那张表，这里不再抄一遍词条）：
# S-T-ACGFUSE 席报告 §5 的 A1/A2 指针写的是这些名字，留着让后来人找得到路。
_ANIME_TERMS = ACG_DOMAIN_TERMS["anime"]
_MANGA_TERMS = ACG_DOMAIN_TERMS["manga"]
_GAME_TERMS = ACG_DOMAIN_TERMS["game"]
_MEME_TERMS = ACG_DOMAIN_TERMS["meme"]
_VTUBER_TERMS = ACG_DOMAIN_TERMS["vtuber"]
_BILIBILI_TERMS = ACG_DOMAIN_TERMS["bilibili"]

#: 非二次元域的「更新/最新」高频干扰词。2026-09-26 起语义变更：此前它只在
#: 「一枚词表词都没命中」时才被读（见旧 ``detect_acg_intent`` 的
#: ``if not tag_terms and …``），命中泛用词即绕过 ⇒ 形同虚设。现在它是
#: **与词表共存的反证信号**，裁决式见 ``detect_acg_intent`` 的三档注释。
_NON_ACG_HINTS: tuple[str, ...] = (
    "天气", "行情", "股价", "股票", "汇率", "基金", "国债", "黄金", "原油",
    "提醒我", "笔记", "菜谱", "怎么做", "怎么弄", "教程", "报错", "报障",
    "工资", "房贷", "快递", "医保", "社保",
)

# ---------------------------------------------------------------------------
# 模式规则
# ---------------------------------------------------------------------------

_EPISODE_RE = re.compile(r"第\s*\d+\s*[集话話季部]")
_NUM_EP_RE = re.compile(r"(?:更新|追|看|更)\s*(?:到|至|了)\s*\d+\s*[集话話]")
_YEAR_ANIME_RE = re.compile(r"20\d{2}\s*年.{0,8}(?:新番|动画|番剧)|(?:新番|动画|番剧).{0,4}20\d{2}\s*年")
_NEW_SEASON_RE = re.compile(r"(?:新一[集话季]|最新一[集话季]|下一[集话季])")
_QUESTION_MENTATION_RE = re.compile(r"(?:是什么|什么)(?:梗|意思|出处)|哪(?:里|来)(?:的|来的)?(?:梗|出自)|出自哪|谁做的|谁整的")

# 最新档信号：明确要「现在/最近」状态
_LATEST_RE = re.compile(
    r"最新|最近|现在|这几天|今天|昨天|刚出|出了吗|出了没|出了没有|更新了吗|更新了没"
    r"|更新到|连载到|更到|进度|开播了吗|开播了没|什么时候出|啥时候出|几点|前瞻"
    r"|卡池|复刻|版本|百大|新番|本季|这季|下一集|哪里能看|在哪看|还能看吗|下架了吗"
    r"|完结了吗|完结了没|停更了吗|断更了吗|这期|本期|这赛季|新赛季"
    r"|公测了吗|公测了没|上线了吗|上线了没|开服了吗|开服了没|发售了吗"
)
# 背景档信号：出处/释义/设定
_BACKGROUND_RE = re.compile(
    r"是什么|是什么意思|什么意思|出处|来源|出自|设定|剧情|简介|人物|角色|声优是谁"
    r"|如何评价|怎么看|推荐|安利|入门|补番|入坑"
)

# 口语问句洗涤：竖源检索只想要条目关键词
_STRIP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"请问|麻烦|帮我|帮忙|帮我看看|看看|想知道|告诉我|说一下|讲讲|介绍一下|介绍下|查一下|查查|搜索一下|搜一下"
    ),
    re.compile(
        r"出了吗|出了没|出了没有|更新了吗|更新了没|更新到哪|更新到了|连载到哪|完结了吗|完结了没"
        r"|是什么梗|什么梗|是什么意思|什么意思|是什么|是什么|有哪些|有没有|好不好看|好看吗|怎么样|如何评价|怎么看"
        r"|哪里能看|在哪看|哪里有|什么时候出|啥时候出|最新消息|最新|最近|现在"
    ),
    re.compile(r"[?？!！。．，,、\s]+$"),
    re.compile(r"^(?:那个|这个|请问一下|你好|喂)[，,、\s]?"),
)

_STRIP_TAIL_RE = re.compile(r"[吗嘛呢吧么？?！!。.\s]+$")


@dataclass(frozen=True)
class AcgIntent:
    """ACG 检索意图判定结果。

    Attributes:
        is_acg: 是否命中二次元检索意图。
        tags: 命中的子域标签（anime/manga/game/meme/vtuber/bilibili）。
        timeliness: ``latest``（要最新动态，结果必须带日期）/ ``background``
            （要权威背景知识，权威度优先）。
        matched_terms: 命中的词表词（去重、保持词表序），供审计/遥测。
    """

    is_acg: bool
    tags: tuple[str, ...] = ()
    timeliness: str = TIMELINESS_BACKGROUND
    matched_terms: tuple[str, ...] = ()

    @property
    def wants_latest(self) -> bool:
        return self.timeliness == TIMELINESS_LATEST


def _hit_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in text or (term.isascii() and term.lower() in lowered)]


def detect_acg_intent(text: str) -> AcgIntent:
    """检测查询是否命中二次元/番剧/漫画/B站梗/二次元游戏检索意图。

    纯函数：零网络、零时钟依赖、确定性输出。
    """
    stripped = str(text or "").strip()
    if not stripped:
        return AcgIntent(is_acg=False)

    # 模式规则（第N集/新番/卡池…）是独立于词表的兜底证据，先算。
    strong_pattern_hit = bool(
        _EPISODE_RE.search(stripped)
        or _NUM_EP_RE.search(stripped)
        or _YEAR_ANIME_RE.search(stripped)
        or _NEW_SEASON_RE.search(stripped)
        or _QUESTION_MENTATION_RE.search(stripped)
    )

    # 命中收集：(子域, 词, 档)。弱档**照样收**——它不单独定罪，但在问句已被
    # 强/中档或模式放行时，它仍然是一条真实的子域线索（供 tags 与审计用）。
    tag_terms: list[tuple[str, str, str]] = []
    for tag, tier_terms in ACG_DOMAIN_TERMS.items():
        for tier in ACG_TIERS:
            for term in _hit_terms(stripped, tier_terms[tier]):
                tag_terms.append((tag, term, tier))

    has_strong = any(tier == ACG_TIER_STRONG for _, _, tier in tag_terms)
    has_decisive = any(tier != ACG_TIER_WEAK for _, _, tier in tag_terms)
    non_acg_hint_hit = any(hint in stripped for hint in _NON_ACG_HINTS)

    # ---- 三档裁决（与反证信号共存，取代旧的「先拦再判」单级判据）----
    # ① 弱通用词单独命中 ⇒ 不判。旧版在这里判是 21 句误开的总成因（现算名单见
    #    席报告），例：「我的工作日常真的很无聊」只命中 ``日常`` 这一枚提示级词。
    # ② 反证词不再是「零命中才看」的装饰：无强专名压场时，它一票否决。
    #    例：「PPT动画怎么做」命中中档 ``动画`` + 反证 ``怎么做`` ⇒ 不判。
    # ③ 强专名不受②影响：库里有的条目名不该被干扰词挡在门外。
    #    例：「原神教程怎么做」仍判 ACG。
    if not tag_terms and not strong_pattern_hit:
        return AcgIntent(is_acg=False)
    if not has_decisive and not strong_pattern_hit:
        return AcgIntent(is_acg=False)
    if not has_strong and non_acg_hint_hit:
        return AcgIntent(is_acg=False)

    tags: list[str] = []
    matched: list[str] = []
    seen_tags: set[str] = set()
    for tag, term, _tier in tag_terms:
        if tag not in seen_tags:
            seen_tags.add(tag)
            tags.append(tag)
        if term not in matched:
            matched.append(term)

    is_acg = bool(tags) or strong_pattern_hit

    # 时效档：明确「要最新」信号 → latest；
    # 梗查询默认 latest（B站热梗生命周期短，宁可按最新档要求带日期），
    # 但「出处/什么意思」类语义查询归 background（要的是释义不是动态）。
    if _LATEST_RE.search(stripped) or strong_pattern_hit and not _BACKGROUND_RE.search(stripped):
        timeliness = TIMELINESS_LATEST
    elif "meme" in tags and _QUESTION_MENTATION_RE.search(stripped):
        timeliness = TIMELINESS_BACKGROUND
    elif "meme" in tags:
        timeliness = TIMELINESS_LATEST
    else:
        timeliness = TIMELINESS_BACKGROUND

    return AcgIntent(
        is_acg=is_acg,
        tags=tuple(tags),
        timeliness=timeliness,
        matched_terms=tuple(matched),
    )


# ---------------------------------------------------------------------------
# chat 层门禁：ACG 专项检索允许放行的 NEVER reason
# ---------------------------------------------------------------------------

# classify_question_intent 的这些 NEVER reason 是**安全/体验红线**，
# ACG 检索永不越过：用户显式拒绝联网、纯闲聊、身份询问、自我状态、
# 情感倾诉、创作扮演、用户自己贴的内容。
_ACG_SEARCH_DENIED_REASONS: frozenset[str] = frozenset(
    {
        "explicit_no_web",
        "short_smalltalk",
        "asks_user_identity",
        "you_state_chat",
        "personal_emotional",
        "creative_roleplay",
        "user_provided_content",
        "empty",
    }
)


def acg_search_allowed(intent_reason: str) -> bool:
    """判定 ACG 专项检索是否可越过 ``classify_question_intent`` 的结论。

    规则：安全红线类 NEVER（见 ``_ACG_SEARCH_DENIED_REASONS``）一律拒绝；
    其余（general_static_knowledge / no_strong_signal / domain_* / temporal 等）
    允许放行——这正是旧行为下「X是什么梗」不搜索的缺口。
    """
    return str(intent_reason or "") not in _ACG_SEARCH_DENIED_REASONS


# ---------------------------------------------------------------------------
# 查询洗涤与增强
# ---------------------------------------------------------------------------

def extract_acg_query(text: str) -> str:
    """把口语问句洗成竖源关键词（去掉客套/疑问/时效词，留条目主体）。

    例：``芙莉莲第三季出了吗`` → ``芙莉莲第三季``；
    ``硬控是什么梗`` → ``硬控``；``原神5.0卡池最新消息`` → ``原神5.0卡池``。
    洗完为空则回退原文 strip。
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    for pattern in _STRIP_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = _STRIP_TAIL_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if not cleaned:
        cleaned = str(text or "").strip()
    return cleaned


def acg_query_variants(text: str, intent: AcgIntent) -> list[str]:
    """按子域生成至多 2 条检索增强变体（供通用 web 检索链使用）。

    纯函数；无 ACG 意图返回空列表。
    """
    if not intent.is_acg:
        return []
    base = extract_acg_query(text)
    if not base:
        return []
    variants: list[str] = []
    if "anime" in intent.tags:
        variants.append(f"{base} 番剧 放送 最新")
    if "game" in intent.tags:
        variants.append(f"{base} 版本 前瞻" if intent.wants_latest else f"{base} 游戏 剧情 设定")
    if "meme" in intent.tags:
        variants.append(f"{base} 梗 出处" if not intent.wants_latest else f"{base} B站 热梗")
    if "manga" in intent.tags and len(variants) < 2:
        variants.append(f"{base} 漫画 连载 更新")
    if "vtuber" in intent.tags and len(variants) < 2:
        variants.append(f"{base} VTuber 切片")
    deduped: list[str] = []
    for variant in variants:
        if variant not in deduped:
            deduped.append(variant)
    return deduped[:2]


# ---------------------------------------------------------------------------
# 通用时效信号（2026-09-26 S-T-SEARCHQ-1）
# ---------------------------------------------------------------------------
#
# 为什么开这一节：此前整个 core/search 层唯一的「要不要最新」信号是 ACG 专用的
# ``AcgIntent.timeliness``，消费点只有 ``acg_query_variants`` 与
# ``source_authority.order_key`` 的抬档。科技/时政/新闻/金融四类的检索结果侧
# 今天没有任何时效信号可比——于是「带日期的权威页」与「无日期的转载页」在排序上
# 同权，实测（席报告 §3.2）表现为最该先看的那条排在后面或被当噪声丢掉。
#
# 刻意**不做**的事：
# 1. 不判话题归属。「这条问题属于时政还是金融」的真身在
#    ``domains/chat_reply/runtime/question_intent.py:classify_timely_domain``，
#    core 层反向 import 是分层倒置（``source_authority.py`` 头注已写明同一理由），
#    再抄一份正则就是第二真身。本节的判据只读**问句自身**带的时效线索；
# 2. 不读时钟。年份只按字面提取、不与「今年」比较，于是本函数是纯函数、
#    离线可测、跨日不变（时钟口径归 ``chat.py`` 的【当前时间】与运行时授时）。

#: 问句里点名了某年（"2026 年…"/"… 2026"）——装饰词面由 chat.py 尾部追加。
_RECENCY_YEAR_RE = re.compile(r"(20[0-9]{2})\s*(?:年|年度)?")

#: 明示「要现在/要最近」的词面。含 chat.py 查询装饰实际会带的词
#: （`最新 消息` / `官方 发布 公告` / `最新 进展`），使装配后的查询也能被认出。
_RECENCY_MARKER_RE = re.compile(
    r"最新|最近|近期|目前|现在|今天|今日|昨天|本周|本月|今年|刚刚|刚出"
    r"|消息|动态|进展|公告|发布|实况|行情|赛果|比分|股价|汇率"
)


@dataclass(frozen=True)
class QueryRecency:
    """问句自带的时效线索（纯派生，零网络零时钟）。

    Attributes:
        wants_latest: 问句是否要求新鲜度（命中时效词或点名了年份）。
        years: 问句里出现的年份（升序去重）。这些年份**不构成实体证据**——
            它们由查询装饰追加，任何带日期的页面都含得上，实测正是拿它凑够
            相关性地板把「中国地图」放进了「个人所得税起征点」的结果块。
        explicit_latest: 问句是否**明示**要最新（命中 ``_RECENCY_MARKER_RE``
            词面）。与 ``wants_latest`` 的分工：裸年份（「2019年 票房 冠军」）
            要求新鲜度参与排序，却绝不构成请求级时效窗的证据——历史年题被
            time_range 挡掉旧档是错的（WEBCFG-AUDIT E-3 注毒负例）。
    """

    wants_latest: bool
    years: tuple[int, ...] = ()
    explicit_latest: bool = False

    def names_year(self, token: str) -> bool:
        """某一枚查询 token 是不是「只有年份」的装饰（数字且落在问句点名的年份里）。"""
        digits = token.strip()
        if not digits.isdigit():
            return False
        try:
            value = int(digits)
        except ValueError:
            return False
        return value in self.years


def detect_query_recency(text: str) -> QueryRecency:
    """问句自带的时效信号。纯函数：零网络、零时钟、确定性输出。"""
    stripped = str(text or "").strip()
    if not stripped:
        return QueryRecency(wants_latest=False)
    years = tuple(sorted({int(match) for match in _RECENCY_YEAR_RE.findall(stripped)}))
    marked = bool(_RECENCY_MARKER_RE.search(stripped))
    return QueryRecency(
        wants_latest=marked or bool(years), years=years, explicit_latest=marked
    )

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
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "TIMELINESS_BACKGROUND",
    "TIMELINESS_LATEST",
    "AcgIntent",
    "acg_query_variants",
    "acg_search_allowed",
    "detect_acg_intent",
    "extract_acg_query",
]

TIMELINESS_LATEST = "latest"
TIMELINESS_BACKGROUND = "background"

# ---------------------------------------------------------------------------
# 词表（驱动式设计：全部集中在此，便于审计与扩充）
# ---------------------------------------------------------------------------

# 动画/番剧域：类型词+高热条目名（条目名只收长青高热，冷门靠模式兜底）
_ANIME_TERMS: tuple[str, ...] = (
    "番剧", "新番", "动画", "动漫", "剧场版", "OAD", "OVA", "声优",
    "制作组", "作画", "放送", "开播", "动画化", "一月番", "四月番",
    "七月番", "十月番", "季番", "年番", "国创", "里番",
    # 长青高热条目（中文名/通称）
    "芙莉莲", "葬送的芙莉莲", "鬼灭之刃", "咒术回战", "海贼王", "航海王",
    "火影忍者", "间谍过家家", "孤独摇滚", "葬送", "进击的巨人",
    "约会大作战", "Re:0", "Re0", "无职转生", "药屋少女", "我推的孩子",
    "败犬女主", "义妹生活", "青之箱", "物语系列", "机动战士",
    "高达", "EVA", "新世纪福音战士", "凉宫春日", "刀剑神域", "粗点心屋",
)

# 漫画/轻小说域
_MANGA_TERMS: tuple[str, ...] = (
    "漫画", "原作", "单行本", "连载", "汉化", "停更", "断更", "腰斩",
    "轻小说", "漫画家", "少年JUMP", "jump", "JUMP", "条漫", "日更",
)

# 二次元游戏域（游戏名+圈内黑话）
_GAME_TERMS: tuple[str, ...] = (
    "原神", "星穹铁道", "崩坏", "绝区零", "鸣潮", "明日方舟",
    "米哈游", "miHoYo", "mihoyo", "库洛", "库街区", "鹰角", "抽卡", "卡池",
    "保底", "歪了", "大保底", "小保底", "UP池", "up池", "复刻", "前瞻直播",
    "前瞻", "深境螺旋", "深渊", "虚构叙事", "模拟宇宙", "合成区", "尘白禁区",
    "重返未来1999", "深空之眼", "战双帕弥什", "蔚蓝档案", "碧蓝档案",
    "碧蓝航线", "少女前线", "少前2", "追放", "FGO", "fgo", "赛马娘",
    "公主连结", "碧蓝幻想", "无期迷途", "物华弥新", "白荆回廊", "异环",
    "无限暖暖", "二游", "二次元游戏", "公测", "开服", "周年庆", "版本更新",
    "星琼", "原石", "缠芯", "蓝莓", "体力", "日常", "周本", "月卡",
)

# B站梗/黑话域
_MEME_TERMS: tuple[str, ...] = (
    "梗", "名场面", "鬼畜", "弹幕", "百大", "UP主", "up主",
    "一键三连", "三连", "下次一定", "好活", "整活", "硬控", "锐评",
    "空耳", "生草", "洗脑循环", "名梗", "热梗", "烂梗", "玩梗",
    "梗百科", "小黑屋", "充电", "拜年祭", "跨晚", "干杯",
)

# VTuber/虚拟主播域
_VTUBER_TERMS: tuple[str, ...] = (
    "vtuber", "VTuber", "Vtuber", "V圈", "v圈", "中之人", "皮套",
    "切片", "虚拟主播", "虚拟偶像", "毕业", "转生", "初配信",
)

# B站平台域
_BILIBILI_TERMS: tuple[str, ...] = (
    "B站", "b站", "哔哩哔哩", "bilibili", "BILIBILI", "小电视",
)

# 非二次元域的「更新/最新」高频干扰词——先拦再判，防误触发
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

    # 非二次元域高频干扰先拦（防止「基金最新行情」因「最新」误入）。
    # 只拦「纯干扰词命中且无任何 ACG 强模式」的场景，词表命中优先级更高。
    strong_pattern_hit = bool(
        _EPISODE_RE.search(stripped)
        or _NUM_EP_RE.search(stripped)
        or _YEAR_ANIME_RE.search(stripped)
        or _NEW_SEASON_RE.search(stripped)
        or _QUESTION_MENTATION_RE.search(stripped)
    )

    tag_terms: list[tuple[str, str]] = []
    for tag, terms in (
        ("anime", _ANIME_TERMS),
        ("manga", _MANGA_TERMS),
        ("game", _GAME_TERMS),
        ("meme", _MEME_TERMS),
        ("vtuber", _VTUBER_TERMS),
        ("bilibili", _BILIBILI_TERMS),
    ):
        for term in _hit_terms(stripped, terms):
            tag_terms.append((tag, term))

    if not tag_terms and not strong_pattern_hit:
        return AcgIntent(is_acg=False)
    if not tag_terms and strong_pattern_hit and any(hint in stripped for hint in _NON_ACG_HINTS):
        # 只有模糊模式+明确非 ACG 域词 → 不算
        return AcgIntent(is_acg=False)

    tags: list[str] = []
    matched: list[str] = []
    seen_tags: set[str] = set()
    for tag, term in tag_terms:
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

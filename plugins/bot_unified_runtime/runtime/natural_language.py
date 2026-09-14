"""自然语言命令识别（基层确定性层，不调用大模型）。

把“帮我查杭州天气 / 来首晴天 / 查一下维基 鸣潮 / 今天有什么免费游戏 /
今天历史上发生了什么”这类不带斜杠的自然说法，归一化成标准命令文本，
交给对应的子能力执行。规则刻意保守：必须有强动作信号才会命中，
普通闲聊（如“今天天气不错”“播放量好高”）不会误入命令路由。

该层位于基层路由优先级 45：昵称命令 / 管理员命令 / 标准命令 / 表情包
之前都不会被它抢占；含 http 链接时由基层先行让位给链接解析。

设置分支（审查 C-01）：“把识图关掉 / 开启安静时间”这类口语改设置说法
被归一化成 ``/bot runtime set <KEY> <VALUE>`` 结构化意图（capability_id
= ``bot.runtime_settings``，载荷携带 setting_key/setting_value/原话）。
权限红线：设置是管理员操作——本层只识别、不授权、不执行；派发层必须
把该意图送入 build_runtime_admin_result（capabilities/runtime_admin.py）
的既有管理员门，非 admin 角色一律拒绝。功能词 → 运行时键的映射表为
FUNCTION_KEY_MAP，其目标键必须在 runtime.settings.SETTABLE_KEYS 内
（tests 有防漂移遍历断言），映射不到真实键的功能（提醒/笔记/群摘要等）
一律不命中、落回 chat，绝不静默假映射。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from plugins.bot_unified_runtime.capabilities.music import parse_music_mode_spec
from plugins.bot_unified_runtime.capabilities.weather import is_statement_lead
from plugins.bot_unified_runtime.config import Config


@dataclass(frozen=True)
class NaturalResolution:
    capability_id: str
    normalized_text: str
    intent_label: str
    # ---- 审查 C-01 设置意图载荷（旧 7 支不带，缺省即零破坏）----
    # setting_key 必须是 runtime.settings.SETTABLE_KEYS 的真实键；
    # setting_value 是转换器可解析的字符串（布尔开关为 "true"/"false"）。
    # admin_required=True 表示该意图属管理员操作：映射层只识别不授权，
    # 派发层必须走 build_runtime_admin_result 既有管理员门。
    setting_key: str | None = None
    setting_value: str | None = None
    source_text: str | None = None
    ambiguous: bool = False
    admin_required: bool = False


# 禮貌前綴（TRA 草稿 幫我 词条）：繁體形与简体逐一成对（影响全部 NL 问句入口）。
_POLITE_PREFIX = r"(?:帮我|幫我|麻烦|麻煩|请你?|請你?|请|請|给我|給我|我想)"
_POLITE_OPT = rf"(?:{_POLITE_PREFIX})?"
_LOOKUP_PREFIX = r"(?:查一下|查查|查询|查|搜一下|搜索|搜|看看|看|告诉我)?"

# 天气问法 A：城市 + 天气（怎么样）。保守锚定，不匹配“今天天气不错”。
_WEATHER_ASK_RE = re.compile(
    r"^(?:今天|明天|后天)?(?P<city>[^\s，。？?！!.．]{1,12}?)(?:的)?天气"
    r"(?:怎么样|如何|怎样|咋样|预报)?[?？]?$"
)
# 天气问法 B（礼貌式）：必须出现“天气”二字，避免误吞无关请求。
_WEATHER_PLEASE_RE = re.compile(
    rf"^{_POLITE_OPT}{_LOOKUP_PREFIX}\s*(?:"
    r"天气\s*(?P<city1>[^\s，。？?！!.．]{1,12}?)(?:的天气|天气)?"
    r"|(?P<city2>[^\s，。？?！!.．]{1,12}?)(?:的)?天气"
    r")(?:怎么样|如何|怎样|咋样|预报)?[?？]?$"
)

_MUSIC_TRIGGERS = (
    r"点一首|点首歌|点首|点歌|来一首|来首歌|来首|放一首|放首歌|放首|"
    r"播放一首|播一首|唱一首|唱首歌|来点音乐|放点音乐|播放点音乐|"
    # 繁體形（TRA 草稿 點一首/來首 词条；放/播/唱/播放 简繁同形不重列）。
    r"點一首|點首歌|點首|點歌|來一首|來首歌|來首|來點音樂|放點音樂"
)
_MUSIC_RE = re.compile(
    rf"^{_POLITE_OPT}(?:{_MUSIC_TRIGGERS})(?:歌|音乐)?\s*"
    r"(?P<q>.{1,40}?)(?:吧|呗|嘛|谢谢|听|听听)?[?？！!。]?$"
)

_MUSIC_MODE_NL_RE = re.compile(
    r"^(?:以后|之後|之后|从现在起|从今以后)?(?:点歌|點歌|音乐|音樂)"
    r"(?:的)?(?:输出|輸出|发送|發送|回复|回覆)?(?:模式|方式)?"
    r"(?:设置成|設置成|设为|設為|改成|改为|改為|切换成|切換成|切换为|切換為|变成|變成)?"
    r"(?:只|仅|僅)?(?:发|發|输出|輸出|用|要)?(?P<spec>.{1,40}?)(?:模式|方式|输出|輸出)?$",
    re.IGNORECASE,
)

_MUSIC_MODE_EN_RE = re.compile(
    r"^(?:music mode|song mode)\s+(?P<spec>.+)$",
    re.IGNORECASE,
)

_WEATHER_EN_RE = re.compile(
    r"^(?:(?:what(?:'s| is)|whats) the weather(?: like)?(?: in| at)?|weather(?: in| at)?)"
    r"\s*(?P<city>[a-zA-Z\u4e00-\u9fff\- ]{1,30}?)[?？]?$",
    re.IGNORECASE,
)
_MUSIC_EN_RE = re.compile(
    r"^play\s+(?:me\s+)?(?:a\s+)?song\s+(?P<q>.{1,50}?)[.!?]?$|"
    r"^play\s+(?:me\s+)?(?P<q2>[a-zA-Z0-9\u4e00-\u9fff'’\- ]{1,50}?)\s+(?:please|for me|for you)?[.!?]?$",
    re.IGNORECASE,
)
_WIKI_EN_RE = re.compile(
    r"^(?:search\s+)?(?:wiki|wikipedia)\s+(?P<q>.+)$|"
    r"^what is\s+(?P<q2>.+?)\s+on wikipedia[?？]?$",
    re.IGNORECASE,
)
_EPIC_EN_RE = re.compile(
    r"^(?:what|which|any|are there).{0,20}?free games.{0,20}?(?:this week|today)?[?？]?$",
    re.IGNORECASE,
)
_MEME_LIBRARY_NL_RE = re.compile(
    r"^(?:帮我|给我|来一|来一张|来张|偷一张|偷个|随机来|抽|偷|拿)"
    r"(?:张|个)?(?:偷)?(?:表情|表情包)$|"
    r"^(?:steal|give me|random|send|gimme)(?:\s+(?:a|an))?\s*memes?$",
    re.IGNORECASE,
)

_HISTORY_EN_RE = re.compile(
    r"^(?:what happened )?today in history[?？]?$|"
    r"^history today[?？]?$|^on this day[?？]?$",
    re.IGNORECASE,
)

_WIKI_RE = re.compile(
    rf"^{_POLITE_OPT}{_LOOKUP_PREFIX}\s*(?:一下)?\s*"
    r"(?:wiki|wikipedia|维基|维基百科)\s*(?P<q>.+)$",
    re.IGNORECASE,
)

_EPIC_RE = re.compile(
    r"^(?:这周|本周|今天|今日|這週|本週)?(?:有)?(?:什么|哪些|什麼)?(?:的)?"
    r"(?:epic\s*)?(?:免费游戏|免費遊戲)(?:有哪些|有什么|是什么|有什麼|是什麼)?[?？]?$",
    re.IGNORECASE,
)

_HISTORY_RE = re.compile(
    r"^(?:今天|今日)(?:在)?(?:历史上|历史)(?:发生了什么|有什么|有哪些|大事)?[?？]?$"
)

# 城市里出现这些词说明吞进了动作/礼貌词，不是真实地名，必须拒绝。
# （繁體形与简体同口径，TRA 草稿 幫我 词条连动。）
_CITY_FORBIDDEN_FRAGMENTS = (
    "帮我",
    "幫我",
    "麻烦",
    "麻煩",
    "请",
    "請",
    "查",
    "搜",
    "看看",
    "看",
    "查询",
    "告诉",
    "给我",
    "給我",
    "我想",
    "放",
    "点",
    "来",
    "天气",
    # 反噬守卫（invest-moegirl-hijack §四 C）：moegirl_question 让路到 46 后，
    # 「帮我查一下天气之子是谁」会先到本层，若把「之子是谁」吞成城市就会
    # 反噬成 weather——问句后缀不是地名，必须拒绝（让路 46 萌百实体问句）。
    "是谁",
    "是什么",
    "是啥",
)
EN_CITY_MAP = {
    "beijing": "北京", "shanghai": "上海", "guangzhou": "广州", "shenzhen": "深圳",
    "hangzhou": "杭州", "chengdu": "成都", "chongqing": "重庆", "wuhan": "武汉",
    "nanjing": "南京", "xian": "西安", "suzhou": "苏州", "tianjin": "天津",
    "changsha": "长沙", "zhengzhou": "郑州", "qingdao": "青岛", "dalian": "大连",
    "xiamen": "厦门", "fuzhou": "福州", "kunming": "昆明", "haikou": "海口",
    "sanya": "三亚", "harbin": "哈尔滨", "shenyang": "沈阳", "jinan": "济南",
    "hefei": "合肥", "nanchang": "南昌", "nanning": "南宁", "guiyang": "贵阳",
    "lanzhou": "兰州", "xining": "西宁", "yinchuan": "银川", "urumqi": "乌鲁木齐",
    "lhasa": "拉萨", "hohhot": "呼和浩特", "shijiazhuang": "石家庄", "taiyuan": "太原",
}


def _map_english_city(raw: str) -> str:
    key = (raw or "").strip().lower().replace(" ", "")
    return EN_CITY_MAP.get(key, (raw or "").strip())


_WEATHER_CITY_BLACKLIST = {
    "今天",
    "明天",
    "后天",
    "现在",
    "这",
    "那",
    "一个",
    "一下",
    "天气",
}


def _clean_city(raw: str | None) -> str | None:
    if not raw:
        return None
    city = raw.strip().strip("，。？?！!.．")
    if not city or city in _WEATHER_CITY_BLACKLIST:
        return None
    if any(fragment in city for fragment in _CITY_FORBIDDEN_FRAGMENTS):
        return None
    # 陈述句守卫（与 weather 触发层共用 is_statement_lead）：weather 基层
    # 让位后，本层 weather 问法不得把「天气预报说明天下雨」整段当地名
    # 归一化成「天气 预报说明天下雨」（二阶劫持）。
    if is_statement_lead(city):
        return None
    return city


# ============================================================================
# 审查 C-01：自然语言改设置（映射层：话 → 结构化意图）。
# 权限红线：设置是管理员操作。本层只识别、绝不授权、绝不执行；派发层
# 必须把 bot.runtime_settings 意图送入 build_runtime_admin_result
# （capabilities/runtime_admin.py，内建 "admin" 角色门）执行。
# 防漂移契约：FUNCTION_KEY_MAP 的目标键必须是 runtime.settings.SETTABLE_KEYS
# 的真实键（tests/test_natural_settings_nl.py 遍历断言）；真实键不存在的
# 功能（提醒/笔记/表情回应/天气/快报/群摘要/搜图等）刻意不映射——命中
# 与否以映射表为准，映射表外功能词一律落回 chat，绝不假映射。
# ============================================================================

# 开关动词：繁体形与简体同口径（TRA 词条惯例）。关/停 族先于开 族匹配。
_SETTING_ON_VERBS = ("打开", "打開", "開啓", "開啟", "开启", "開启", "开起来", "開起來",
                     "开着", "開著", "启用", "啓用", "啟用", "开", "開")
_SETTING_OFF_VERBS = ("关掉", "關掉", "关闭", "關閉", "关上", "關上", "停用",
                      "禁用", "关了", "關了", "关", "關")
_SETTING_ON_SET = frozenset(_SETTING_ON_VERBS)
_SETTING_OFF_SET = frozenset(_SETTING_OFF_VERBS)
# 正则交替必须长词在前，否则单字「开/关」会抢先吃掉「打开/关掉」。
_SETTING_TOGGLE_VERBS = "|".join(
    sorted(_SETTING_ON_SET | _SETTING_OFF_SET, key=len, reverse=True)
)

# 功能名词槽后缀与语气助词：让「识图功能/安静时间吧」这类口语尾巴可剥。
_SETTING_FUNC_SUFFIX = r"(?:的)?(?:功能|功能模块|模塊|模块|開關|开关|設置|设置)?"
_SETTING_PARTICLE = r"(?:一下|掉)?(?:吧|呗|嘛|啦)?"
_FUNC_CHAR = r"[\u4e00-\u9fffa-zA-Z0-9]"

# 把字句：[礼貌前缀]把/将 X [功能] 关掉/打开…（动词收尾，锚定极强）。
_SETTING_NL_BA_RE = re.compile(
    rf"^{_POLITE_OPT}[把將将]\s*(?P<func>{_FUNC_CHAR}{{1,12}}?)"
    rf"{_SETTING_FUNC_SUFFIX}(?:都|先|给|給)?(?P<verb>{_SETTING_TOGGLE_VERBS})"
    rf"{_SETTING_PARTICLE}[?？!！。]?$"
)
# 动词前置句：[礼貌前缀]打开/关闭/启用 X [功能]。
_SETTING_NL_VF_RE = re.compile(
    rf"^{_POLITE_OPT}(?P<verb>{_SETTING_TOGGLE_VERBS}){_SETTING_PARTICLE}"
    rf"\s*(?P<func>{_FUNC_CHAR}{{1,12}}?){_SETTING_FUNC_SUFFIX}"
    rf"{_SETTING_PARTICLE}[?？!！。]?$"
)

# 功能词槽内允许的填充字：剥掉命中功能词后，槽内剩余必须全为填充字，
# 否则视为未知实体（「识图结果」「有关的东西」）→ 不算设置意图落回 chat。
# 刻意不含 开/关/打/停/启 等动词字，防动词残渣被当成填充吞掉。
_SETTING_FILLER_CHARS = frozenset(
    "的功能模块模塊設置设置都先和跟与及給给請请帮幫我並并一并起全全部所有順顺便利"
)

# 功能词 → (SETTABLE_KEY, 功能中文名)。值只取布尔开关键：口语开/关的
# 方向由句中动词决定（开→"true"，关→"false"，交给 _bool_converter）。
# tuple[1] 是给人看的功能名（歧义提示/日志用），不是开关值。
FUNCTION_KEY_MAP: dict[str, tuple[str, str]] = {
    # 识图（VLM 看图）
    "识图": ("BOT_VISION_ENABLED", "识图"),
    "識圖": ("BOT_VISION_ENABLED", "识图"),
    "看图": ("BOT_VISION_ENABLED", "识图"),
    "看圖": ("BOT_VISION_ENABLED", "识图"),
    # 视频理解（含深度档）
    "视频理解": ("BOT_VIDEO_UNDERSTANDING_ENABLED", "视频理解"),
    "視頻理解": ("BOT_VIDEO_UNDERSTANDING_ENABLED", "视频理解"),
    "视频深度理解": ("BOT_VIDEO_DEEP_ENABLED", "视频深度理解"),
    "視頻深度理解": ("BOT_VIDEO_DEEP_ENABLED", "视频深度理解"),
    # 语音识别（ASR）
    "语音识别": ("BOT_ASR_ENABLED", "语音识别"),
    "語音識別": ("BOT_ASR_ENABLED", "语音识别"),
    "语音转文字": ("BOT_ASR_ENABLED", "语音识别"),
    "語音轉文字": ("BOT_ASR_ENABLED", "语音识别"),
    # 戳一戳三件（互不包含歧义由长词覆盖短词消解）
    "戳一戳": ("BOT_POKE_ENABLED", "戳一戳"),
    "戳一戳回话": ("BOT_POKE_REPLY_ENABLED", "戳一戳回话"),
    "戳一戳回覆": ("BOT_POKE_REPLY_ENABLED", "戳一戳回话"),
    "戳一戳回复": ("BOT_POKE_REPLY_ENABLED", "戳一戳回话"),
    "戳一戳回戳": ("BOT_POKE_POKE_BACK", "戳一戳回戳"),
    "回戳": ("BOT_POKE_POKE_BACK", "戳一戳回戳"),
    # 群聊自动接话
    "自动接话": ("BOT_GROUP_CHAT_AUTO_REPLY_ENABLED", "群聊自动接话"),
    "自動接話": ("BOT_GROUP_CHAT_AUTO_REPLY_ENABLED", "群聊自动接话"),
    "自动回复": ("BOT_GROUP_CHAT_AUTO_REPLY_ENABLED", "群聊自动接话"),
    "自動回復": ("BOT_GROUP_CHAT_AUTO_REPLY_ENABLED", "群聊自动接话"),
    "群聊自动回复": ("BOT_GROUP_CHAT_AUTO_REPLY_ENABLED", "群聊自动接话"),
    # 安静时间（免打扰）
    "安静时间": ("BOT_QUIET_HOURS_ENABLED", "安静时间"),
    "安靜時間": ("BOT_QUIET_HOURS_ENABLED", "安静时间"),
    "安静时段": ("BOT_QUIET_HOURS_ENABLED", "安静时间"),
    "免打扰": ("BOT_QUIET_HOURS_ENABLED", "安静时间"),
    "免打擾": ("BOT_QUIET_HOURS_ENABLED", "安静时间"),
    # 快速回复模式
    "快速模式": ("BOT_CHAT_FAST_MODE", "快速回复模式"),
    "快速回复": ("BOT_CHAT_FAST_MODE", "快速回复模式"),
    # 记忆抽取（夜间反思喂料）
    "记忆抽取": ("BOT_MEMORY_EXTRACT_ENABLED", "记忆抽取"),
    "記憶抽取": ("BOT_MEMORY_EXTRACT_ENABLED", "记忆抽取"),
    "记忆提取": ("BOT_MEMORY_EXTRACT_ENABLED", "记忆抽取"),
    # 联网搜索
    "联网搜索": ("BOT_WEB_SEARCH_ENABLED", "联网搜索"),
    "聯網搜索": ("BOT_WEB_SEARCH_ENABLED", "联网搜索"),
    "网页搜索": ("BOT_WEB_SEARCH_ENABLED", "联网搜索"),
    "網頁搜索": ("BOT_WEB_SEARCH_ENABLED", "联网搜索"),
    "网络搜索": ("BOT_WEB_SEARCH_ENABLED", "联网搜索"),
    "網絡搜索": ("BOT_WEB_SEARCH_ENABLED", "联网搜索"),
    # 梗/表情搜索（二次元平台白名单）
    "表情搜索": ("BOT_MEME_SEARCH_ENABLED", "梗搜索"),
    "表情搜尋": ("BOT_MEME_SEARCH_ENABLED", "梗搜索"),
    "梗搜索": ("BOT_MEME_SEARCH_ENABLED", "梗搜索"),
    "梗搜尋": ("BOT_MEME_SEARCH_ENABLED", "梗搜索"),
    # 人格动作括号
    "动作括号": ("BOT_PERSONA_ACTION_BRACKETS", "动作括号"),
    "動作括號": ("BOT_PERSONA_ACTION_BRACKETS", "动作括号"),
}

# 长词优先清单：命中扫描用，保证「群聊自动回复」不被「自动回复」拆双。
_FUNCTION_WORDS_BY_LEN = sorted(FUNCTION_KEY_MAP, key=len, reverse=True)

# 设置意图的 capability_id：派发层（__init__.py 消费侧，审查 C-02 接线）
# 按此 id 分发到 build_runtime_admin_result。
SETTING_CAPABILITY_ID = "bot.runtime_settings"


def runtime_set_command_text(setting_key: str, setting_value: str) -> str:
    """C-02 派发层用：把映射结果拼成 /bot runtime 的 ``runtime set`` 子命令体。

    单独成函数便于测试锁定格式（派发层把 build_runtime_admin_result 的
    ``command_text`` 直接喂它）。
    """
    return f"runtime set {setting_key.strip()} {setting_value.strip()}"


def _prune_covered_spans(
    spans: list[tuple[int, int, str]],
) -> list[tuple[int, int, str]]:
    """去掉被更长命中完全覆盖的短命中（长词覆盖短词，同位置同词不受影响）。"""
    return [
        s
        for s in spans
        if not any(
            o is not s and o[0] <= s[0] and s[1] <= o[1] and (o[1] - o[0]) > (s[1] - s[0])
            for o in spans
        )
    ]


def _extract_func_targets(func_text: str) -> list[str] | None:
    """从功能名词槽提取命中功能词（按出现位置排序、去重）。

    返回 None 表示槽内有非填充残留（未知实体）或零命中——两种情况都
    不算设置意图，调用方必须返回 None 落回 chat。
    """
    spans: list[tuple[int, int, str]] = []
    for word in _FUNCTION_WORDS_BY_LEN:
        start = 0
        while (idx := func_text.find(word, start)) != -1:
            spans.append((idx, idx + len(word), word))
            start = idx + 1
    hits = sorted(_prune_covered_spans(spans))
    if not hits:
        return None
    leftover: list[str] = []
    cursor = 0
    for begin, end, _word in hits:
        leftover.extend(func_text[cursor:begin])
        cursor = end
    leftover.extend(func_text[cursor:])
    if any(ch not in _SETTING_FILLER_CHARS for ch in leftover):
        return None
    words = [word for _b, _e, word in hits]
    return list(dict.fromkeys(words))


def _match_setting_intent(stripped: str) -> NaturalResolution | None:
    """把设置类口语句映射成结构化意图；不像设置句/功能词不可映射则 None。"""
    for pattern in (_SETTING_NL_BA_RE, _SETTING_NL_VF_RE):
        match = pattern.match(stripped)
        if match is None:
            continue
        groups = match.groupdict()
        func_text = str(groups.get("func") or "")
        verb = str(groups.get("verb") or "")
        words = _extract_func_targets(func_text)
        if not words:
            # 消歧规则：功能词不在映射表（或槽内夹带未知实体）→ 不命中，
            # 落回 chat；绝不猜测用户想改哪个键。
            return None
        ambiguous = len(words) > 1
        target_word = words[0]
        key, _label = FUNCTION_KEY_MAP[target_word]
        value = "false" if verb in _SETTING_OFF_SET else "true"
        return NaturalResolution(
            SETTING_CAPABILITY_ID,
            f"/bot runtime set {key} {value}",
            "设置功能开关",
            setting_key=key,
            setting_value=value,
            source_text=stripped,
            ambiguous=ambiguous,
            # 权限红线写进载荷：派发层见 True 必须走
            # build_runtime_admin_result 管理员门，映射层不授权。
            admin_required=True,
        )
    return None


def detect_natural_command(text: str, config: Config | None = None) -> NaturalResolution | None:
    """把自然语言意图归一化成标准命令；没有强信号时返回 None。"""
    stripped = (text or "").strip().strip("/!！")
    if not stripped:
        return None
    if "http://" in stripped or "https://" in stripped:
        return None

    # 审查 C-01：设置分支放最前——句形以开关动词收尾、锚定极强，不允许
    # 被下方宽松问句抢占；映射层只识别不授权（权限红线见模块 docstring
    # 与 NaturalResolution.admin_required，派发层必须走管理员门）。
    setting = _match_setting_intent(stripped)
    if setting is not None:
        return setting

    if getattr(config, "bot_music_enabled", True):
        mode_match = _MUSIC_MODE_NL_RE.match(stripped) or _MUSIC_MODE_EN_RE.match(stripped)
        if mode_match:
            spec = parse_music_mode_spec(str(mode_match.groupdict().get("spec") or ""))
            if spec is not None:
                from plugins.bot_unified_runtime.capabilities.music import (
                    normalize_music_mode,
                )

                normalized_mode = normalize_music_mode("+".join(sorted(spec)))
                if normalized_mode:
                    return NaturalResolution(
                        "bot.music_mode",
                        f"点歌模式 {normalized_mode}",
                        "设置点歌输出组合",
                    )

    if getattr(config, "bot_weather_query_enabled", True):
        english_weather = _WEATHER_EN_RE.match(stripped)
        if english_weather:
            city = _clean_city(english_weather.groupdict().get("city"))
            if city:
                return NaturalResolution(
                    "bot.weather", f"天气 {_map_english_city(city)}", "查询天气"
                )
        # 礼貌式优先：能精确切出城市；问句式其次。
        match = _WEATHER_PLEASE_RE.match(stripped)
        if match is None:
            match = _WEATHER_ASK_RE.match(stripped)
        if match is not None:
            groups = match.groupdict()
            city = _clean_city(groups.get("city") or groups.get("city1") or groups.get("city2"))
            if city:
                return NaturalResolution(
                    "bot.weather", f"天气 {city}", "查询天气"
                )

    if getattr(config, "bot_music_enabled", True):
        english_music = _MUSIC_EN_RE.match(stripped)
        if english_music:
            groups = english_music.groupdict()
            query = (groups.get("q") or groups.get("q2") or "").strip("，。？?！!.．")
            if query and parse_music_mode_spec(query) is None:
                return NaturalResolution("bot.music", f"点歌 {query}", "点歌")
        match = _MUSIC_RE.match(stripped)
        if match:
            query = (match.groupdict().get("q") or "").strip("，。？?！!.．")
            if query:
                return NaturalResolution("bot.music", f"点歌 {query}", "点歌")

    if getattr(config, "bot_wiki_enabled", True):
        english_wiki = _WIKI_EN_RE.match(stripped)
        if english_wiki:
            groups = english_wiki.groupdict()
            query = (groups.get("q") or groups.get("q2") or "").strip()
            if query:
                return NaturalResolution("bot.wiki", f"wiki {query}", "查维基")
        match = _WIKI_RE.match(stripped)
        if match:
            query = (match.groupdict().get("q") or "").strip()
            if query:
                return NaturalResolution("bot.wiki", f"wiki {query}", "查维基")

    if getattr(config, "bot_epic_enabled", True) and (
        _EPIC_RE.match(stripped) or _EPIC_EN_RE.match(stripped)
    ):
        return NaturalResolution("bot.epic", "epic", "查免费游戏")

    if getattr(config, "bot_today_history_enabled", True) and (
        _HISTORY_RE.match(stripped) or _HISTORY_EN_RE.match(stripped)
    ):
        return NaturalResolution(
            "bot.today_history", "历史上的今天", "历史上的今天"
        )

    if getattr(config, "bot_meme_library_enabled", False):
        meme_lib_match = _MEME_LIBRARY_NL_RE.match(stripped)
        if meme_lib_match:
            return NaturalResolution("bot.meme_library", "偷表情", "偷表情")

    return None

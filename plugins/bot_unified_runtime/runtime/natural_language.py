"""自然语言命令识别（基层确定性层，不调用大模型）。

把“帮我查杭州天气 / 来首晴天 / 查一下维基 鸣潮 / 今天有什么免费游戏 /
今天历史上发生了什么”这类不带斜杠的自然说法，归一化成标准命令文本，
交给对应的子能力执行。规则刻意保守：必须有强动作信号才会命中，
普通闲聊（如“今天天气不错”“播放量好高”）不会误入命令路由。

该层位于基层路由优先级 45：昵称命令 / 管理员命令 / 标准命令 / 表情包
之前都不会被它抢占；含 http 链接时由基层先行让位给链接解析。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from plugins.bot_unified_runtime.config import Config


@dataclass(frozen=True)
class NaturalResolution:
    capability_id: str
    normalized_text: str
    intent_label: str


_POLITE_PREFIX = r"(?:帮我|麻烦|请你?|请|给我|我想)"
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
    r"播放一首|播一首|唱一首|唱首歌|来点音乐|放点音乐|播放点音乐"
)
_MUSIC_RE = re.compile(
    rf"^{_POLITE_OPT}(?:{_MUSIC_TRIGGERS})(?:歌|音乐)?\s*"
    r"(?P<q>.{1,40}?)(?:吧|呗|嘛|谢谢|听|听听)?[?？！!。]?$"
)

_WIKI_RE = re.compile(
    rf"^{_POLITE_OPT}{_LOOKUP_PREFIX}\s*(?:一下)?\s*"
    r"(?:wiki|wikipedia|维基|维基百科)\s*(?P<q>.+)$",
    re.IGNORECASE,
)

_EPIC_RE = re.compile(
    r"^(?:这周|本周|今天|今日)?(?:有)?(?:什么|哪些)?(?:的)?"
    r"(?:epic\s*)?免费游戏(?:有哪些|有什么|是什么)?[?？]?$",
    re.IGNORECASE,
)

_HISTORY_RE = re.compile(
    r"^(?:今天|今日)(?:在)?(?:历史上|历史)(?:发生了什么|有什么|有哪些|大事)?[?？]?$"
)

# 城市里出现这些词说明吞进了动作/礼貌词，不是真实地名，必须拒绝。
_CITY_FORBIDDEN_FRAGMENTS = (
    "帮我",
    "麻烦",
    "请",
    "查",
    "搜",
    "看看",
    "看",
    "查询",
    "告诉",
    "给我",
    "我想",
    "放",
    "点",
    "来",
    "天气",
)
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
    return city


def detect_natural_command(text: str, config: Config | None = None) -> NaturalResolution | None:
    """把自然语言意图归一化成标准命令；没有强信号时返回 None。"""
    stripped = (text or "").strip().strip("/!！")
    if not stripped:
        return None
    if "http://" in stripped or "https://" in stripped:
        return None

    if getattr(config, "bot_weather_query_enabled", True):
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
        match = _MUSIC_RE.match(stripped)
        if match:
            query = (match.groupdict().get("q") or "").strip("，。？?！!.．")
            if query:
                return NaturalResolution("bot.music", f"点歌 {query}", "点歌")

    if getattr(config, "bot_wiki_enabled", True):
        match = _WIKI_RE.match(stripped)
        if match:
            query = (match.groupdict().get("q") or "").strip()
            if query:
                return NaturalResolution("bot.wiki", f"wiki {query}", "查维基")

    if getattr(config, "bot_epic_enabled", True) and _EPIC_RE.match(stripped):
        return NaturalResolution("bot.epic", "epic", "查免费游戏")

    if getattr(config, "bot_today_history_enabled", True) and _HISTORY_RE.match(stripped):
        return NaturalResolution(
            "bot.today_history", "历史上的今天", "历史上的今天"
        )

    return None

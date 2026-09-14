"""基层统一路由器（Base Router）：所有可能接口的确定性注册表。

入站文本先在这里做确定性分类，决定走哪条路：

- 确定性命令：昵称别名 / 管理员 / 订阅 / 自动发送 / 表情包 / 点歌 /
  维基 / Epic / 天气 / 历史上的今天。
- 自然语言意图：不带斜杠的“帮我查天气 / 来首歌 / 查维基”等，
  归一化成标准命令后仍走对应子能力。
- 人格大模型：普通自然语言聊天（带人格、世界观、价值观和方法论回复）。
- 链接解析：文本含 http(s) 链接时优先走解析器。

子能力执行完后把 ``CapabilityResult`` 交回 ``RuntimePipeline``（基层），
基层统一做安全审查、渲染（文本/卡片/合并转发）并交给 NapCat 发送。
这里只做判断，不直接执行、不直接发消息。

同时维护 ``INTERFACE_MANIFEST``：把目前和未来所有可想象的接口
（GsCore/早柚核心桥、NapCat 传输、解析插件、人格、天气、游戏直播、
订阅、表情包吸收/生成等）提前登记成一张可审计的清单，已接入的标
``active``，尚未接线的标 ``reserved``。新增能力只需在注册表加一行，
不改变判定主循环。
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from plugins.bot_unified_runtime.capabilities.affinity import is_affinity_command
from plugins.bot_unified_runtime.capabilities.auto_send import (
    is_auto_send_command_text,
)
from plugins.bot_unified_runtime.capabilities.chat import looks_like_chat_text
from plugins.bot_unified_runtime.capabilities.divination import is_divination_command
from plugins.bot_unified_runtime.capabilities.eat import (
    is_eat_command,
    is_recipe_command,
)
from plugins.bot_unified_runtime.capabilities.epic import is_epic_command
from plugins.bot_unified_runtime.capabilities.fx import is_fx_command
from plugins.bot_unified_runtime.capabilities.group_info import is_group_info_command
from plugins.bot_unified_runtime.capabilities.market import (
    is_bond_command,
    is_commodity_command,
    is_market_command,
    is_northbound_command,
)
from plugins.bot_unified_runtime.capabilities.media_archive import (
    is_media_archive_command,
)
from plugins.bot_unified_runtime.capabilities.meme import is_meme_command
from plugins.bot_unified_runtime.capabilities.meme_library import (
    is_meme_library_command,
)
from plugins.bot_unified_runtime.capabilities.moegirl import (
    is_entity_question,
    is_moegirl_command,
)
from plugins.bot_unified_runtime.capabilities.music import (
    is_music_command,
    is_music_mode_command,
)
from plugins.bot_unified_runtime.capabilities.news import is_news_command
from plugins.bot_unified_runtime.capabilities.randpic import is_randpic_command
from plugins.bot_unified_runtime.capabilities.reminder import is_reminder_command
from plugins.bot_unified_runtime.capabilities.stocks import is_stocks_command
from plugins.bot_unified_runtime.capabilities.subscribe import (
    is_standalone_subscribe_command,
)
from plugins.bot_unified_runtime.capabilities.today_history import (
    is_today_history_command,
)
from plugins.bot_unified_runtime.capabilities.weather import is_weather_command
from plugins.bot_unified_runtime.capabilities.wiki import is_wiki_command
from plugins.bot_unified_runtime.runtime.capability_registry import (
    COMMAND_ROUTE_KIND_NAMES,
)
from plugins.bot_unified_runtime.runtime.natural_language import (
    detect_natural_command,
)


# Keystone（C-06 能力单一声明源）：成员清单的权威声明在
# runtime/capability_registry.py 的 ROUTE_CAPABILITY_DECLARATIONS（每能力
# 一行：kind/capability_id/priority/label/reason/tags/command/matcher/note）。
# 本枚举与下方 RouteRule 注册表、接口清单、INTERNAL_CAPABILITY_NOTES 保持
# 字面形态，是四处离线静态解析器（scripts/doc_sync.py、
# scripts/command_catalog.py、tests/test_doc_sync_gates.py、
# scripts/extract_trigger_words.py）的机器可读投影；两方向逐字段一致性由
# tests/test_capability_registry.py 常驻锁定，增删成员必须两处同步。
class RouteKind(str, Enum):
    ALIAS = "alias"
    ADMIN = "admin"
    SUBSCRIBE = "subscribe"
    AUTO_SEND = "auto_send"
    MEME = "meme"
    MEME_LIBRARY = "meme_library"
    MUSIC_MODE = "music_mode"
    MUSIC = "music"
    TODAY_HISTORY = "today_history"
    WIKI = "wiki"
    MOEGIRL = "moegirl"
    MOEGIRL_QUESTION = "moegirl_question"
    EPIC = "epic"
    WEATHER = "weather"
    MARKET = "market"
    STOCKS = "stocks"
    COMMODITIES = "commodities"
    BOND = "bond"
    NORTHBOUND = "northbound"
    FX = "fx"
    NEWS = "news"
    RANDPIC = "randpic"
    REMINDER = "reminder"
    MEDIA_ARCHIVE = "media_archive"
    GROUP_INFO = "group_info"
    EAT = "eat"
    AFFINITY = "affinity"
    DIVINATION = "divination"
    NATURAL_COMMAND = "natural_command"
    CONTENT = "content"
    CHAT = "chat"
    IGNORE = "ignore"


@dataclass(frozen=True)
class RouteDecision:
    """基层路由判定结果（可审计、可解释）。"""

    kind: RouteKind
    capability_id: str
    priority: int
    reason: str
    audit_tags: tuple[str, ...] = ()
    # 自然语言意图被归一化成标准命令后走的具体能力与命令文本。
    target_capability_id: str | None = None
    normalized_text: str | None = None

    def to_dict(self) -> dict:
        data = {
            "kind": self.kind.value,
            "capability_id": self.capability_id,
            "priority": self.priority,
            "reason": self.reason,
            "audit_tags": list(self.audit_tags),
        }
        if self.target_capability_id:
            data["target_capability_id"] = self.target_capability_id
        if self.normalized_text is not None:
            data["normalized_text"] = self.normalized_text
        return data


@dataclass(frozen=True)
class InterfaceEntry:
    """接口清单条目：把基层要接的所有接口提前登记，便于审计与规划。

    help_topic/internal_note 是审计元数据：active 接口必须指向一个帮助主题
    （capabilities/echo.py 的 topic）或登记为内部功能；reserved 接口必须登记说明。
    """

    interface_id: str
    label: str
    status: Literal["active", "reserved"]
    route_kind: str
    priority: int | None
    description: str
    help_topic: str = ""
    internal_note: str = ""


@dataclass(frozen=True)
class RouteRule:
    kind: RouteKind
    capability_id: str
    priority: int
    label: str
    reason: str
    tags: tuple[str, ...] = ()
    # 返回 RouteDecision|None；None 表示不命中，继续下一规则。
    matcher: Callable[[str, Any, Any], RouteDecision | None] | None = None


def _admin_command_match(text: str) -> bool:
    stripped = text.strip()
    return stripped == "/bot" or stripped.startswith(("/bot ", "bot "))


def _resolve_alias(text: str, alias_resolver: Any) -> Any | None:
    if alias_resolver is None:
        return None
    return alias_resolver.resolve(text)


def build_route_rules() -> list[RouteRule]:
    """构建全部路由规则；新增能力在此表加一行即可。

    书写序=声明登记序（审计/文档生成依赖，不做物理重排）；真实判定序由
    判定循环按 (priority, 书写序) 稳定排序得出（见 classify_message_route）。

    Keystone（C-06）：本表每行的数据列（kind/capability_id/priority/label/
    reason/tags/matcher 名）以 capability_registry.ROUTE_CAPABILITY_DECLARATIONS
    为权威声明源，逐行逐字段由 tests/test_capability_registry.py 锁定——
    新增/修改能力先改声明表，再同步本表与枚举，漏一处即测试红。
    """

    def subscribe_match(text, config, _alias):
        if not getattr(config, "bot_subscribe_enabled", True):
            return None
        if not is_standalone_subscribe_command(text):
            return None
        return RouteDecision(
            RouteKind.SUBSCRIBE, "bot.subscribe", 12, "订阅命令（中文/英文）", ("base_route:subscribe",)
        )

    def alias_match(text, _config, alias_resolver):
        if alias_resolver is not None and _resolve_alias(text, alias_resolver) is not None:
            return RouteDecision(
                RouteKind.ALIAS, "bot.alias", 10, "昵称命令（/岸宝… /守岸人…）", ("base_route:alias",)
            )
        return None

    def admin_match(text, _config, _alias):
        if not _admin_command_match(text):
            return None
        return RouteDecision(
            RouteKind.ADMIN, "bot.status", 11, "管理员命令（/bot …）", ("base_route:admin",)
        )

    def auto_send_match(text, _config, _alias):
        if not is_auto_send_command_text(text):
            return None
        return RouteDecision(
            RouteKind.AUTO_SEND, "bot.auto_send", 13, "自动发送/定时任务命令", ("base_route:auto_send",)
        )

    def meme_match(text, config, _alias):
        if not getattr(config, "bot_meme_command_enabled", True):
            return None
        if not is_meme_command(text):
            return None
        return RouteDecision(
            RouteKind.MEME, "bot.meme", 20, "表情包生成命令（对接 meme-generator-rs）", ("base_route:meme",)
        )

    def meme_library_match(text, config, _alias):
        if not getattr(config, "bot_meme_library_enabled", False):
            return None
        if not is_meme_library_command(text):
            return None
        return RouteDecision(
            RouteKind.MEME_LIBRARY, "bot.meme_library", 22,
            "偷表情/表情库命令（权重随机发送）", ("base_route:meme_library",)
        )

    def music_mode_match(text, config, _alias):
        if not getattr(config, "bot_music_enabled", True):
            return None
        if not is_music_mode_command(text):
            return None
        return RouteDecision(
            RouteKind.MUSIC_MODE, "bot.music_mode", 40, "点歌输出模式设置", ("base_route:music_mode",)
        )

    def music_match(text, config, _alias):
        if not getattr(config, "bot_music_enabled", True):
            return None
        if not is_music_command(text):
            return None
        return RouteDecision(RouteKind.MUSIC, "bot.music", 41, "点歌", ("base_route:music",))

    def today_history_match(text, config, _alias):
        if not getattr(config, "bot_today_history_enabled", True):
            return None
        if not is_today_history_command(text):
            return None
        return RouteDecision(
            RouteKind.TODAY_HISTORY, "bot.today_history", 41, "历史上的今天", ("base_route:today_history",)
        )

    def wiki_match(text, config, _alias):
        if not getattr(config, "bot_wiki_enabled", True):
            return None
        if not is_wiki_command(text):
            return None
        return RouteDecision(RouteKind.WIKI, "bot.wiki", 41, "维基百科查询", ("base_route:wiki",))

    def moegirl_match(text, config, _alias):
        if not getattr(config, "bot_moegirl_enabled", True):
            return None
        if not is_moegirl_command(text):
            return None
        return RouteDecision(RouteKind.MOEGIRL, "bot.moegirl", 41, "萌娘百科查询", ("base_route:moegirl",))

    def epic_match(text, config, _alias):
        if not getattr(config, "bot_epic_enabled", True):
            return None
        if not is_epic_command(text):
            return None
        return RouteDecision(RouteKind.EPIC, "bot.epic", 41, "Epic 免费游戏查询", ("base_route:epic",))

    def weather_match(text, config, _alias):
        if not getattr(config, "bot_weather_query_enabled", True):
            return None
        if not is_weather_command(text):
            return None
        return RouteDecision(RouteKind.WEATHER, "bot.weather", 41, "天气查询", ("base_route:weather",))

    # 金融三能力让路口径（2026-09-13 六域批接线）：商品触发词（黄金/金价/
    # 原油…）撞上股/大盘/指数词时是股市语境（「黄金股行情」=黄金板块股票），
    # 商品卡不抢、让位 market（与 market._NON_STOCK_RE/_STOCK_HINT_RE 守卫
    # 同源语义；market.py 本席只读，故正则在此地持有）。
    _FIN_STOCK_HINT_RE = re.compile(r"(股|大盘|大盤|指数|指數)")

    def commodities_match(text, config, _alias):
        # 商品行情：黄金/金价/白银/原油/铜价/大宗商品（+gold/silver/oil）。
        if not getattr(config, "bot_commodities_enabled", True):
            return None
        if not is_commodity_command(text):
            return None
        if _FIN_STOCK_HINT_RE.search(text):
            return None  # 股市语境让位 market（黄金股行情仍归股指面板）。
        return RouteDecision(
            RouteKind.COMMODITIES, "bot.commodities", 41, "商品行情", ("base_route:commodities",)
        )

    def bond_match(text, config, _alias):
        # 国债收益率：国债/期限利差/收益率曲线（中美国债利差）。
        if not getattr(config, "bot_bond_enabled", True):
            return None
        if not is_bond_command(text):
            return None
        return RouteDecision(RouteKind.BOND, "bot.bond", 41, "国债收益率", ("base_route:bond",))

    def northbound_match(text, config, _alias):
        # 北向资金：北向资金/沪股通/深股通（成交总额口径）。
        if not getattr(config, "bot_northbound_enabled", True):
            return None
        if not is_northbound_command(text):
            return None
        return RouteDecision(
            RouteKind.NORTHBOUND, "bot.northbound", 41, "北向资金", ("base_route:northbound",)
        )

    def market_match(text, config, _alias):
        # 全球股指行情：短命令级触发（≤32 字、无链接），长句问盘自然落回聊天。
        if not getattr(config, "bot_market_enabled", True):
            return None
        if not is_market_command(text):
            return None
        return RouteDecision(RouteKind.MARKET, "bot.market", 41, "全球股指行情", ("base_route:market",))

    def fx_match(text, config, _alias):
        # 汇率查询：fx 触发词「汇率」已被 market 非股市词表排除（天然互斥）；
        # 与 stocks 触发面若重叠，fx 数值优先级更高（41 < 42）。
        if not getattr(config, "bot_fx_enabled", True):
            return None
        if not is_fx_command(text):
            return None
        return RouteDecision(RouteKind.FX, "bot.fx", 41, "汇率查询", ("base_route:fx",))

    def stocks_match(text, config, _alias):
        # 个股行情：英伟达/AMD/英特尔股价兜底；裸「行情」归 market（互不抢路由），
        # 排在 market/fx 之后做让路（同文本先到先得）。
        if not getattr(config, "bot_stocks_enabled", True):
            return None
        if not is_stocks_command(text):
            return None
        return RouteDecision(RouteKind.STOCKS, "bot.stocks", 42, "个股行情", ("base_route:stocks",))

    def eat_match(text, config, _alias):
        if not getattr(config, "bot_eat_enabled", True):
            return None
        if is_recipe_command(text) or is_eat_command(text):
            return RouteDecision(RouteKind.EAT, "bot.eat", 41, "吃什么推荐", ("base_route:eat",))
        return None

    def divination_match(text, config, _alias):
        # 占卜娱乐三件套（八字/塔罗/金钱卦）：纯本地计算，显式触发词。
        if not getattr(config, "bot_divination_enabled", True):
            return None
        if not is_divination_command(text):
            return None
        return RouteDecision(RouteKind.DIVINATION, "bot.divination", 41, "占卜（八字/塔罗/金钱卦）", ("base_route:divination",))

    def news_match(text, config, _alias):
        # 今日快报：仅显式触发词（快报/早报/科技新闻…），裸「新闻」让给联网搜索意图。
        if not getattr(config, "bot_news_enabled", True):
            return None
        if not is_news_command(text):
            return None
        return RouteDecision(RouteKind.NEWS, "bot.news", 41, "今日快报", ("base_route:news",))

    def randpic_match(text, config, _alias):
        # 随机图片：触发词（默认 随机图/来张图）即从用户自定义图库发一张。
        if not getattr(config, "bot_randpic_enabled", True):
            return None
        if not is_randpic_command(
            text, getattr(config, "bot_randpic_trigger_words", []) or None
        ):
            return None
        return RouteDecision(RouteKind.RANDPIC, "bot.randpic", 41, "随机图片", ("base_route:randpic",))

    def reminder_match(text, config, _alias):
        # 时间点提醒：自然语言「12点提醒我写作业」或列表/取消查询；
        # 亦含笔记指令面与自然语言勾选（复用 REMINDER 路由，不新增 kind）。
        if not getattr(config, "bot_reminder_enabled", True):
            return None
        if not is_reminder_command(text, config=config):
            return None
        return RouteDecision(RouteKind.REMINDER, "bot.reminder", 41, "提醒", ("base_route:reminder",))

    def affinity_match(text, config, _alias):
        # 好感度查询与动态好感度层共用 bot_affinity_enabled 开关。
        if not getattr(config, "bot_affinity_enabled", True):
            return None
        if is_affinity_command(text):
            return RouteDecision(RouteKind.AFFINITY, "bot.affinity", 41, "好感度查询", ("base_route:affinity",))
        return None

    def moegirl_question_match(text, config, _alias):
        # 二次元实体问句（「初音未来是谁？」）：不进 COMMAND_ROUTE_KINDS，
        # 群聊不 @ 不抢答（与 CHAT 同门控）；未命中时 handler 无感降级聊天链路。
        if not getattr(config, "bot_moegirl_enabled", True):
            return None
        if not getattr(config, "bot_moegirl_question_enabled", True):
            return None
        if not is_entity_question(text):
            return None
        return RouteDecision(
            RouteKind.MOEGIRL_QUESTION,
            "bot.moegirl",
            46,
            "二次元问句（萌娘百科自动查询）",
            ("base_route:moegirl_question",),
        )

    def natural_match(text, config, alias_resolver):
        if not getattr(config, "bot_natural_command_enabled", True):
            return None
        candidate = text
        if alias_resolver is not None:
            nicknames = sorted(
                {
                    str(item).strip()
                    for item in getattr(alias_resolver, "nicknames", [])
                    if str(item).strip()
                },
                key=len,
                reverse=True,
            )
            for nickname in nicknames:
                if candidate.startswith(nickname) and (
                    candidate == nickname
                    or candidate[len(nickname)] in "，,。！？!?：: 的"
                ):
                    candidate = candidate[len(nickname):].lstrip("，,。！？!?：: ")
                    break
        resolution = detect_natural_command(candidate, config)
        if resolution is None:
            return None
        return RouteDecision(
            RouteKind.NATURAL_COMMAND,
            "bot.natural_command",
            45,
            f"自然语言命令（意图：{resolution.intent_label}）",
            ("base_route:natural_command",),
            target_capability_id=resolution.capability_id,
            normalized_text=resolution.normalized_text,
        )

    def content_match(text, config, _alias):
        if not getattr(config, "bot_content_parse_enabled", True):
            return None
        if not extract_http_urls(text):
            return None
        return RouteDecision(
            RouteKind.CONTENT, "bot.content", 46, "链接解析（视频/图片/社交媒体/商品等）", ("base_route:content",)
        )

    def chat_match(text, config, _alias):
        if not getattr(config, "bot_chat_enabled", True):
            return None
        if not looks_like_chat_text(text):
            return None
        if is_auto_send_command_text(text):
            return None
        return RouteDecision(
            RouteKind.CHAT, "bot.chat", 50, "自然语言对话（人格+世界观+价值观+方法论）", ("base_route:chat",)
        )

    def media_archive_match(text, config, _alias):
        if not getattr(config, "bot_media_archive_enabled", True):
            return None
        if not is_media_archive_command(text):
            return None
        return RouteDecision(
            RouteKind.MEDIA_ARCHIVE,
            "bot.media_archive",
            43,
            "媒体归档（收藏/归档媒体，VLM 分类落盘）",
            ("base_route:media_archive",),
        )

    def group_info_match(text, config, _alias):
        # 群资料/群主/人数/公告/精华（审查 B-01/B-04）：CJK 复合触发词，词界
        # 天然安全；能力侧仅群聊生效（私聊回守岸人提示）并做管理员分级。
        if not is_group_info_command(text):
            return None
        return RouteDecision(
            RouteKind.GROUP_INFO,
            "bot.group_info",
            41,
            "群信息（群主/人数/公告/精华）",
            ("base_route:group_info",),
        )

    return [
        RouteRule(RouteKind.ALIAS, "bot.alias", 10, "昵称命令", "昵称命令（/岸宝… /守岸人…）", ("base_route:alias",), alias_match),
        RouteRule(RouteKind.ADMIN, "bot.status", 11, "管理员命令", "管理员命令（/bot …）", ("base_route:admin",), admin_match),
        RouteRule(RouteKind.SUBSCRIBE, "bot.subscribe", 12, "订阅命令", "订阅命令（中文/英文）", ("base_route:subscribe",), subscribe_match),
        RouteRule(RouteKind.AUTO_SEND, "bot.auto_send", 13, "自动发送", "自动发送/定时任务命令", ("base_route:auto_send",), auto_send_match),
        RouteRule(RouteKind.MEME, "bot.meme", 20, "表情包生成", "表情包生成命令", ("base_route:meme",), meme_match),
        RouteRule(RouteKind.MEME_LIBRARY, "bot.meme_library", 22, "偷表情", "偷表情/表情库命令", ("base_route:meme_library",), meme_library_match),
        RouteRule(RouteKind.MUSIC_MODE, "bot.music_mode", 40, "点歌模式", "点歌输出模式设置", ("base_route:music_mode",), music_mode_match),
        RouteRule(RouteKind.MUSIC, "bot.music", 41, "点歌", "点歌", ("base_route:music",), music_match),
        RouteRule(RouteKind.TODAY_HISTORY, "bot.today_history", 41, "历史上的今天", "历史上的今天", ("base_route:today_history",), today_history_match),
        RouteRule(RouteKind.WIKI, "bot.wiki", 41, "维基百科", "维基百科查询", ("base_route:wiki",), wiki_match),
        RouteRule(RouteKind.MOEGIRL, "bot.moegirl", 41, "萌娘百科", "萌娘百科查询", ("base_route:moegirl",), moegirl_match),
        RouteRule(RouteKind.EPIC, "bot.epic", 41, "Epic 免费游戏", "Epic 免费游戏查询", ("base_route:epic",), epic_match),
        RouteRule(RouteKind.WEATHER, "bot.weather", 41, "天气查询", "天气查询", ("base_route:weather",), weather_match),
        # 金融三能力（2026-09-13 六域批）：排在 market 之前（同 41 先到先得）
        # ——「黄金行情」这类商品语境由特异触发词先接住；股市语境经
        # commodities_match 的股词让路仍归 market，互不劫持。
        RouteRule(RouteKind.COMMODITIES, "bot.commodities", 41, "商品行情", "商品行情（黄金/金价/白银/原油/铜价/大宗商品）", ("base_route:commodities",), commodities_match),
        RouteRule(RouteKind.BOND, "bot.bond", 41, "国债收益率", "国债收益率（国债/期限利差/收益率曲线）", ("base_route:bond",), bond_match),
        RouteRule(RouteKind.NORTHBOUND, "bot.northbound", 41, "北向资金", "北向资金（北向资金/沪股通/深股通）", ("base_route:northbound",), northbound_match),
        RouteRule(RouteKind.MARKET, "bot.market", 41, "全球股指行情", "全球股指行情（行情/美股行情/大盘）", ("base_route:market",), market_match),
        RouteRule(RouteKind.FX, "bot.fx", 41, "汇率查询", "汇率（美元兑人民币/汇率面板）", ("base_route:fx",), fx_match),
        RouteRule(RouteKind.STOCKS, "bot.stocks", 42, "个股行情", "个股行情（英伟达/AMD/英特尔股价）", ("base_route:stocks",), stocks_match),
        RouteRule(RouteKind.EAT, "bot.eat", 41, "吃什么推荐", "吃什么/菜谱推荐", ("base_route:eat",), eat_match),
        RouteRule(RouteKind.AFFINITY, "bot.affinity", 41, "好感度查询", "好感度/好感查看/查询好感", ("base_route:affinity",), affinity_match),
        RouteRule(RouteKind.DIVINATION, "bot.divination", 41, "占卜", "占卜/塔罗/八字排盘", ("base_route:divination",), divination_match),
        RouteRule(RouteKind.NEWS, "bot.news", 41, "今日快报", "今日快报（快报/科技新闻/财经快报/国际新闻）", ("base_route:news",), news_match),
        RouteRule(RouteKind.RANDPIC, "bot.randpic", 41, "随机图片", "随机图片（随机图/来张图）", ("base_route:randpic",), randpic_match),
        RouteRule(RouteKind.REMINDER, "bot.reminder", 41, "提醒", "提醒（12点提醒我写作业/提醒列表/取消提醒）", ("base_route:reminder",), reminder_match),
        RouteRule(RouteKind.MEDIA_ARCHIVE, "bot.media_archive", 43, "媒体归档", "媒体归档（收藏/归档/存图+媒体；存聊天记录）", ("base_route:media_archive",), media_archive_match),
        RouteRule(RouteKind.GROUP_INFO, "bot.group_info", 41, "群信息", "群信息（群信息/群主是谁/群人数/群公告/群精华/本群多大了）", ("base_route:group_info",), group_info_match),
        RouteRule(RouteKind.MOEGIRL_QUESTION, "bot.moegirl", 46, "二次元问句", "二次元问句（萌娘百科自动查询，未命中降级聊天）", ("base_route:moegirl_question",), moegirl_question_match),
        RouteRule(RouteKind.NATURAL_COMMAND, "bot.natural_command", 45, "自然语言命令", "自然语言命令归一化", ("base_route:natural_command",), natural_match),
        RouteRule(RouteKind.CONTENT, "bot.content", 46, "链接解析", "链接解析（视频/图片/社交媒体/商品等）", ("base_route:content",), content_match),
        RouteRule(RouteKind.CHAT, "bot.chat", 50, "人格对话", "自然语言对话（人格+世界观+价值观+方法论）", ("base_route:chat",), chat_match),
    ]


ROUTE_RULES: list[RouteRule] = build_route_rules()


def build_interface_manifest() -> list[InterfaceEntry]:
    """把所有可能接口（含未来预留）登记成审计清单。

    Keystone（C-06）：行数据以 capability_registry.INTERFACE_DECLARATIONS
    为权威声明源（书写序一致），逐行逐字段由 tests/test_capability_registry.py
    锁定；字面形态为静态解析器（scripts/command_catalog.py）所需投影。
    """
    return [
        InterfaceEntry("transport.onebot", "NapCat / OneBot V11 传输", "active", "transport", None, "入站 QQ 消息与出站发送统一走 OneBot V11（NapCat），由发送队列收口", internal_note="内部：传输层，无用户命令"),
        InterfaceEntry("core.gscore", "GsCore / 早柚核心桥", "active", "bridge", None, "ws://HOST:PORT/BOT_ID?token=TOKEN 桥接，接收游戏侧消息，配置 BOT_GSCORE_*", internal_note="内部：桥接层，接收游戏侧消息，无用户命令"),
        InterfaceEntry("parser.content", "平台链接解析插件组", "active", "content", 46, "B站/小红书/抖音/油管/推特/Lofter/Pixiv/allcpp/米画师/小黑盒/音乐平台", help_topic="链接"),
        InterfaceEntry("persona.chat", "人格大模型对话", "active", "chat", 50, "人格档案 + 向量知识库 + 世界观注入的大模型回复", help_topic="聊天"),
        InterfaceEntry("capability.weather", "天气", "active", "weather", 41, "中国气象局 NMC 免 key 查询", help_topic="天气"),
        InterfaceEntry("capability.music", "点歌", "active", "music", 41, "网易云/酷我/酷狗/QQ音乐/Apple Music/Spotify 搜索", help_topic="点歌"),
        InterfaceEntry("capability.wiki", "维基百科", "active", "wiki", 41, "MediaWiki 公开 API", help_topic="维基"),
        InterfaceEntry("capability.moegirl", "萌娘百科", "active", "moegirl", 46, "萌百 MediaWiki 公开 API：显式指令 + 二次元问句自动查询（未命中降级人格聊天）", help_topic="萌娘百科"),
        InterfaceEntry("capability.epic", "Epic 免费游戏", "active", "epic", 41, "Epic 公开接口", help_topic="Epic"),
        InterfaceEntry("capability.today_history", "历史上的今天", "active", "today_history", 41, "百度百科公开接口 + 每日推送", help_topic="历史上的今天"),
        InterfaceEntry("capability.subscribe", "订阅博主/直播推送", "active", "subscribe", 12, "UP主/番剧/小红书博主等新内容与开播推送", help_topic="订阅"),
        InterfaceEntry("capability.meme", "表情包生成", "active", "meme", 20, "调用本地 meme-generator-rs HTTP API 生成表情包", help_topic="表情"),
        InterfaceEntry("capability.auto_send", "自动发送/定时任务", "active", "auto_send", 13, "报存 给 A 发… 草稿/预览/发送", help_topic="草稿"),
        InterfaceEntry("capability.game_live", "游戏直播状态", "reserved", "game_live", None, "预留：游戏内直播/活动事件接入", internal_note="预留：游戏直播事件接入，尚未实现"),
        InterfaceEntry("capability.meme_absorb", "吸收表情包", "active", "meme_absorb", None, "监听群图片异步下载、MD5 去重、权重筛选、VLM 打标与 NSFW 过滤", help_topic="表情收库"),
        InterfaceEntry("capability.group_info", "群信息", "active", "group_info", 41, "OneBot V11 群 API（get_group_info/成员列表/公告/精华）：群资料/人数全员，公告与精华仅管理员；诚实降级清单见 capabilities/group_info.py", help_topic="群信息"),
        InterfaceEntry("capability.emotion", "情绪状态注入", "active", "context", None, "作为上下文能力注入，不单独占用文本路由", internal_note="内部：心情引擎，经上下文注入，不占文本路由"),
        InterfaceEntry("capability.gscore", "GsCore 上行命令", "reserved", "gscore", None, "预留：GsCore 侧指令统一进入基层路由", internal_note="预留：GsCore 侧指令统一进入基层路由，尚未实现"),
    ]


# 内部路由能力的补充说明登记：
# 已主题化的能力不在此登记；此表仅收 stocks/fx 等仍有独立说明价值的内部条目，
# 供命令目录（scripts/command_catalog.py，帮助主题优先、此表兜底展示）
# 与 tests/test_finance_routing.py 的 stocks/fx 防脱册断言消费。
# Keystone（C-06）：条目内容以 capability_registry 声明行的 note 列为权威
# 声明源（键值集一致由 tests/test_capability_registry.py 锁定）；字面 dict
# 形态为 scripts/command_catalog.py 的 literal_assign 静态提取所需。
INTERNAL_CAPABILITY_NOTES: dict[str, str] = {
    "bot.stocks": "个股行情（英伟达/AMD/英特尔股价兜底，触发词见 capabilities/stocks.py；帮助页 topic=个股行情）",
    "bot.fx": "汇率查询（美元兑人民币/汇率面板，触发词见 capabilities/fx.py；帮助页 topic=汇率）",
    "bot.commodities": "商品行情（黄金/白银/原油/铜现货与 30 日走势，触发词见 capabilities/market.py；帮助页 topic=商品行情）",
    "bot.bond": "国债收益率（国债/期限利差/收益率曲线，触发词见 capabilities/market.py；帮助页 topic=国债收益率）",
    "bot.northbound": "北向资金（北向资金/沪股通/深股通成交总额，触发词见 capabilities/market.py；帮助页 topic=北向资金）",
}


# Keystone（C-06）：命令路由成员清单的单一声明源是
# capability_registry.ROUTE_CAPABILITY_DECLARATIONS 的 command 列，
# 在此 import 时派生（禁在本文件手写增删成员；漏登/多登即测试红）。
# 群门禁 looks_like_command_text 与 /bot commands 目录取本集合判定。
COMMAND_ROUTE_KINDS = frozenset(
    RouteKind[name] for name in COMMAND_ROUTE_KIND_NAMES
)


def looks_like_command_text(
    text: str,
    *,
    config: object,
    alias_resolver=None,
) -> bool:
    """群聊门禁用：确定性命令（含自然语言命令）都算命令触发。

    不含 CHAT/CONTENT/IGNORE，因此“今天天气不错”“看这个链接”这类
    仍属于被动消息，不会因为这条检查而在群里主动开火。
    """
    if not text.strip():
        return False
    if alias_resolver is not None and alias_resolver.resolve(text) is not None:
        return True
    decision = classify_message_route(text, config=config, alias_resolver=alias_resolver)
    return decision.kind in COMMAND_ROUTE_KINDS


def is_command_form_text(text: str) -> bool:
    """「命令形态」判定（审查 C-07 消费侧判据）。

    与 ``chat.looks_like_chat_text`` 同源反义：/、!、！开头即命令形态。
    前置条件：仅应在 :func:`classify_message_route` 判定 ``kind=IGNORE``
    之后调用——此时命令形态即「未命中任何能力」（/bot …、/mail … 等已有
    专属 matcher 的形态有自己的判定/消费路径，到不了这里）。

    刻意收窄的两类（静默语义红线，审查 C-07 裁定不波及）：
    - 空文本/纯媒体消息（plain_text 为空落 IGNORE 兜底）恒 False——
      「空消息兜底，不回复」语义不变；
    - chat 关闭时普通闲聊文本也落 IGNORE，但其非命令形态，同样 False，
      不会用引导语打扰。
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    return not looks_like_chat_text(stripped)


def classify_message_route(
    text: str,
    *,
    config: object,
    alias_resolver=None,
) -> RouteDecision:
    """按 (priority, 声明序) 稳定排序后的注册表顺序做确定性路由判断
    （低数值优先；同 priority 保持清单书写序先到先得，见 T-Spec T2）。

    ``alias_resolver`` 提供昵称命令解析；传入 None 时昵称命令落到后续路由。

    每条消息最多触发 2-3 次全量分类（matcher plain/effective 各一次 +
    群门禁 ``looks_like_command_text`` 再一次），而分类是纯函数——进程内
    TTL-LRU 按 (有无 resolver, 文本) 去重，条目持有 config 强引用并在命中
    时校验同一性，不同 config 对象（测试/多实例）互不串结果。TTL 仅 10 秒：
    管理员修改路由相关配置（群名单/昵称/开关）最迟 10 秒生效；需要立即
    生效可调 ``clear_route_decision_cache()``（settings 保存监听已自动接线）。
    """
    stripped = (text or "").strip()
    if not stripped:
        return RouteDecision(RouteKind.IGNORE, "bot.ignore", 999, "空消息")
    cache_key = (alias_resolver is not None, stripped)
    now = time.monotonic()
    with _ROUTE_CACHE_LOCK:
        hit = _ROUTE_CACHE.get(cache_key)
    if (
        hit is not None
        and hit[1] is config
        and now - hit[0] < _ROUTE_CACHE_TTL_SECONDS
    ):
        return hit[2]
    # T-Spec T2：priority 数值即真实判定序——按 (priority, 原清单序) 稳定排序
    # 后遍历（低数值优先；同值保持书写序先到先得）。每次调用实时对模块全局
    # ROUTE_RULES 排序，保持测试/决策引擎对该注册表的替换语义不变。
    for rule in sorted(ROUTE_RULES, key=lambda candidate: candidate.priority):
        if rule.matcher is None:
            continue
        decision = rule.matcher(stripped, config, alias_resolver)
        if decision is not None:
            _route_cache_put(cache_key, now, config, decision)
            return decision
    # 审查 C-07：此兜底曾是无消费静默点（全项目原无任何 matcher 消费 IGNORE，
    # /help、/帮助 等命令形态坠此即无声）。消费侧收敛在 echo.py
    # （build_ignore_guide_result + IgnoreGuideGate 60s 会话节流），由主模块
    # 的 help_guide matcher 按既有 matcher 模式接线；仅 is_command_form_text
    # 为真的输入回守岸人语气引导，普通闲聊/空消息/限流与安静时间拦截的
    # 静默语义不受影响。字面量保持原样（capability_registry 兜底席测试锁定）。
    fallback = RouteDecision(
        RouteKind.IGNORE, "bot.ignore", 999, "无匹配路由（命令被禁用或文本不满足任何规则）"
    )
    _route_cache_put(cache_key, now, config, fallback)
    return fallback


_ROUTE_CACHE: dict[tuple[bool, str], tuple[float, object, RouteDecision]] = {}
_ROUTE_CACHE_LOCK = threading.Lock()
_ROUTE_CACHE_TTL_SECONDS = 10.0
_ROUTE_CACHE_MAX_ENTRIES = 1024


def _route_cache_put(
    key: tuple[bool, str], now: float, config: object, decision: RouteDecision
) -> None:
    with _ROUTE_CACHE_LOCK:
        if len(_ROUTE_CACHE) >= _ROUTE_CACHE_MAX_ENTRIES:
            _ROUTE_CACHE.clear()
        _ROUTE_CACHE[key] = (now, config, decision)


def clear_route_decision_cache() -> None:
    """清空路由分类缓存（配置热更新立即生效、测试用）。"""
    with _ROUTE_CACHE_LOCK:
        _ROUTE_CACHE.clear()


def list_route_rules_for_audit() -> list[dict]:
    """把当前生效的优先级表导出成可审计列表（/bot routes 与文档共用）。"""
    return [
        {
            "priority": rule.priority,
            "kind": rule.kind.value,
            "capability_id": rule.capability_id,
            "label": rule.label,
            "reason": rule.reason,
        }
        for rule in ROUTE_RULES
    ]


# 热路径压榨项：每消息路由/摄取/影子决策都会调用，pattern 提为模块级。
_URL_RE = re.compile(r"https?://[^\s<>\"\'（）()【】\[\]{}]+")


def extract_http_urls(text: str) -> list[str]:
    """基层判定链接解析用；实现与 parsers 注册表一致，避免循环依赖。"""
    candidates: list[str] = []
    for match in _URL_RE.findall(text or ""):
        raw = match
        while raw and raw[-1] in ".,;:!?，。；：！？":
            raw = raw[:-1]
        if raw not in candidates:
            candidates.append(raw)
    return candidates


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

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from plugins.bot_unified_runtime.capabilities.auto_send import (
    is_auto_send_command_text,
)
from plugins.bot_unified_runtime.capabilities.chat import looks_like_chat_text
from plugins.bot_unified_runtime.capabilities.epic import is_epic_command
from plugins.bot_unified_runtime.capabilities.meme import is_meme_command
from plugins.bot_unified_runtime.capabilities.meme_library import (
    is_meme_library_command,
)
from plugins.bot_unified_runtime.capabilities.music import (
    is_music_command,
    is_music_mode_command,
)
from plugins.bot_unified_runtime.capabilities.subscribe import (
    is_standalone_subscribe_command,
)
from plugins.bot_unified_runtime.capabilities.today_history import (
    is_today_history_command,
)
from plugins.bot_unified_runtime.capabilities.weather import is_weather_command
from plugins.bot_unified_runtime.capabilities.wiki import is_wiki_command
from plugins.bot_unified_runtime.runtime.natural_language import (
    detect_natural_command,
)


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
    EPIC = "epic"
    WEATHER = "weather"
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
    """接口清单条目：把基层要接的所有接口提前登记，便于审计与规划。"""

    interface_id: str
    label: str
    status: Literal["active", "reserved"]
    route_kind: str
    priority: int | None
    description: str


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
    """按优先级升序构建全部路由规则；新增能力在此表加一行即可。"""

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
        RouteRule(RouteKind.EPIC, "bot.epic", 41, "Epic 免费游戏", "Epic 免费游戏查询", ("base_route:epic",), epic_match),
        RouteRule(RouteKind.WEATHER, "bot.weather", 41, "天气查询", "天气查询", ("base_route:weather",), weather_match),
        RouteRule(RouteKind.NATURAL_COMMAND, "bot.natural_command", 45, "自然语言命令", "自然语言命令归一化", ("base_route:natural_command",), natural_match),
        RouteRule(RouteKind.CONTENT, "bot.content", 46, "链接解析", "链接解析（视频/图片/社交媒体/商品等）", ("base_route:content",), content_match),
        RouteRule(RouteKind.CHAT, "bot.chat", 50, "人格对话", "自然语言对话（人格+世界观+价值观+方法论）", ("base_route:chat",), chat_match),
    ]


ROUTE_RULES: list[RouteRule] = build_route_rules()


def build_interface_manifest() -> list[InterfaceEntry]:
    """把所有可能接口（含未来预留）登记成审计清单。"""
    return [
        InterfaceEntry("transport.onebot", "NapCat / OneBot V11 传输", "active", "transport", None, "入站 QQ 消息与出站发送统一走 OneBot V11（NapCat），由发送队列收口"),
        InterfaceEntry("core.gscore", "GsCore / 早柚核心桥", "active", "bridge", None, "ws://HOST:PORT/BOT_ID?token=TOKEN 桥接，接收游戏侧消息，配置 BOT_GSCORE_*"),
        InterfaceEntry("parser.content", "平台链接解析插件组", "active", "content", 46, "B站/小红书/抖音/油管/推特/Lofter/Pixiv/allcpp/米画师/小黑盒/音乐平台"),
        InterfaceEntry("persona.chat", "人格大模型对话", "active", "chat", 50, "人格档案 + 向量知识库 + 世界观注入的大模型回复"),
        InterfaceEntry("capability.weather", "天气", "active", "weather", 41, "中国气象局 NMC 免 key 查询"),
        InterfaceEntry("capability.music", "点歌", "active", "music", 41, "网易云/酷我/酷狗/QQ音乐/Apple Music/Spotify 搜索"),
        InterfaceEntry("capability.wiki", "维基百科", "active", "wiki", 41, "MediaWiki 公开 API"),
        InterfaceEntry("capability.epic", "Epic 免费游戏", "active", "epic", 41, "Epic 公开接口"),
        InterfaceEntry("capability.today_history", "历史上的今天", "active", "today_history", 41, "百度百科公开接口 + 每日推送"),
        InterfaceEntry("capability.subscribe", "订阅博主/直播推送", "active", "subscribe", 12, "UP主/番剧/小红书博主等新内容与开播推送"),
        InterfaceEntry("capability.meme", "表情包生成", "active", "meme", 20, "调用本地 meme-generator-rs HTTP API 生成表情包"),
        InterfaceEntry("capability.auto_send", "自动发送/定时任务", "active", "auto_send", 13, "报存 给 A 发… 草稿/预览/发送"),
        InterfaceEntry("capability.game_live", "游戏直播状态", "reserved", "game_live", None, "预留：游戏内直播/活动事件接入"),
        InterfaceEntry("capability.meme_absorb", "吸收表情包", "active", "meme_absorb", None, "监听群图片异步下载、MD5 去重、权重筛选、VLM 打标与 NSFW 过滤"),
        InterfaceEntry("capability.emotion", "情绪状态注入", "active", "context", None, "作为上下文能力注入，不单独占用文本路由"),
        InterfaceEntry("capability.gscore", "GsCore 上行命令", "reserved", "gscore", None, "预留：GsCore 侧指令统一进入基层路由"),
    ]


COMMAND_ROUTE_KINDS = frozenset(
    {
        RouteKind.ALIAS,
        RouteKind.ADMIN,
        RouteKind.SUBSCRIBE,
        RouteKind.AUTO_SEND,
        RouteKind.MEME,
        RouteKind.MEME_LIBRARY,
        RouteKind.MUSIC_MODE,
        RouteKind.MUSIC,
        RouteKind.TODAY_HISTORY,
        RouteKind.WIKI,
        RouteKind.EPIC,
        RouteKind.WEATHER,
        RouteKind.NATURAL_COMMAND,
    }
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


def classify_message_route(
    text: str,
    *,
    config: object,
    alias_resolver=None,
) -> RouteDecision:
    """按声明式注册表顺序做确定性路由判断。

    ``alias_resolver`` 提供昵称命令解析；传入 None 时昵称命令落到后续路由。
    """
    stripped = (text or "").strip()
    if not stripped:
        return RouteDecision(RouteKind.IGNORE, "bot.ignore", 999, "空消息")
    for rule in ROUTE_RULES:
        if rule.matcher is None:
            continue
        decision = rule.matcher(stripped, config, alias_resolver)
        if decision is not None:
            return decision
    return RouteDecision(
        RouteKind.IGNORE, "bot.ignore", 999, "无匹配路由（命令被禁用或文本不满足任何规则）"
    )


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


def extract_http_urls(text: str) -> list[str]:
    """基层判定链接解析用；实现与 parsers 注册表一致，避免循环依赖。"""
    import re

    pattern = re.compile(r"https?://[^\s<>\"\'（）()【】\[\]{}]+")
    candidates: list[str] = []
    for match in pattern.findall(text or ""):
        raw = match
        while raw and raw[-1] in ".,;:!?，。；：！？":
            raw = raw[:-1]
        if raw not in candidates:
            candidates.append(raw)
    return candidates


"""基层统一路由器（Base Router）。

所有入站文本先在这里做确定性分类，决定走哪条路：

- 确定性插件：天气 / 链接解析 / 点歌 / 维基 / Epic / 历史上的今天 /
  订阅 / 管理员命令 / 昵称别名 / 自动发送。
- 人格大模型：普通自然语言聊天（带着人格、世界观、价值观和方法论回复）。

子能力执行完后把 ``CapabilityResult`` 交回 ``RuntimePipeline``（基层），
基层统一做安全审查、渲染（文本/卡片/合并转发）并交给 NapCat 发送。
这里只做判断，不直接执行、不直接发消息。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from plugins.bot_unified_runtime.capabilities.auto_send import (
    is_auto_send_command_text,
)
from plugins.bot_unified_runtime.capabilities.chat import looks_like_chat_text
from plugins.bot_unified_runtime.capabilities.epic import is_epic_command
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


class RouteKind(str, Enum):
    SUBSCRIBE = "subscribe"
    ALIAS = "alias"
    ADMIN = "admin"
    AUTO_SEND = "auto_send"
    MUSIC_MODE = "music_mode"
    MUSIC = "music"
    TODAY_HISTORY = "today_history"
    WIKI = "wiki"
    EPIC = "epic"
    WEATHER = "weather"
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

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "capability_id": self.capability_id,
            "priority": self.priority,
            "reason": self.reason,
            "audit_tags": list(self.audit_tags),
        }


def _admin_command_match(text: str) -> bool:
    stripped = text.strip()
    return stripped == "/bot" or stripped.startswith("/bot ") or stripped.startswith("bot ")


def classify_message_route(
    text: str,
    *,
    config: object,
    alias_resolver=None,
) -> RouteDecision:
    """按现有 matcher 的优先级顺序做确定性路由判断。

    ``alias_resolver`` 提供昵称命令解析；传入 None 时昵称命令落到后续路由。
    """
    stripped = (text or "").strip()
    if not stripped:
        return RouteDecision(RouteKind.IGNORE, "bot.ignore", 999, "空消息")

    if getattr(config, "bot_subscribe_enabled", True) and is_standalone_subscribe_command(stripped):
        return RouteDecision(
            RouteKind.SUBSCRIBE, "bot.subscribe", 18, "订阅命令", ("base_route:subscribe",)
        )
    if alias_resolver is not None and alias_resolver.resolve(stripped) is not None:
        return RouteDecision(
            RouteKind.ALIAS, "bot.alias", 19, "昵称命令（/岸宝… /守岸人…）", ("base_route:alias",)
        )
    if _admin_command_match(stripped):
        return RouteDecision(
            RouteKind.ADMIN, "bot.status", 20, "管理员命令（/bot …）", ("base_route:admin",)
        )
    if is_auto_send_command_text(stripped):
        return RouteDecision(
            RouteKind.AUTO_SEND, "bot.auto_send", 21, "自动发送/定时任务命令", ("base_route:auto_send",)
        )

    if getattr(config, "bot_music_enabled", True):
        if is_music_mode_command(stripped):
            return RouteDecision(
                RouteKind.MUSIC_MODE, "bot.music_mode", 43, "点歌输出模式设置", ("base_route:music_mode",)
            )
        if is_music_command(stripped):
            return RouteDecision(
                RouteKind.MUSIC, "bot.music", 44, "点歌", ("base_route:music",)
            )
    if getattr(config, "bot_today_history_enabled", True) and is_today_history_command(stripped):
        return RouteDecision(
            RouteKind.TODAY_HISTORY, "bot.today_history", 44, "历史上的今天", ("base_route:today_history",)
        )
    if getattr(config, "bot_wiki_enabled", True) and is_wiki_command(stripped):
        return RouteDecision(
            RouteKind.WIKI, "bot.wiki", 44, "维基百科查询", ("base_route:wiki",)
        )
    if getattr(config, "bot_epic_enabled", True) and is_epic_command(stripped):
        return RouteDecision(
            RouteKind.EPIC, "bot.epic", 44, "Epic 免费游戏查询", ("base_route:epic",)
        )
    if getattr(config, "bot_weather_query_enabled", True) and is_weather_command(stripped):
        return RouteDecision(
            RouteKind.WEATHER, "bot.weather", 44, "天气查询", ("base_route:weather",)
        )

    if getattr(config, "bot_content_parse_enabled", True) and extract_http_urls(stripped):
        return RouteDecision(
            RouteKind.CONTENT, "bot.content", 46, "链接解析（视频/图片/社交媒体/商品等）", ("base_route:content",)
        )

    if getattr(config, "bot_chat_enabled", True) and looks_like_chat_text(stripped) and not is_auto_send_command_text(stripped):
        return RouteDecision(
            RouteKind.CHAT, "bot.chat", 50, "自然语言对话（人格+世界观+价值观+方法论）", ("base_route:chat",)
        )
    return RouteDecision(RouteKind.IGNORE, "bot.ignore", 999, "无匹配路由（命令被禁用或文本不满足任何规则）")


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

"""角色昵称命令别名：把 "/岸宝帮助" 这类输入解析成能力 id。

默认映射（动词 → capability_id）：::

    帮助/help -> bot.help
    状态/status -> bot.status
    为什么/为啥/why -> bot.why
    记忆/memory -> bot.memory
    配置/config -> bot.config
    就绪/readiness -> bot.readiness
    人格/persona -> bot.persona
    对话验收/dialogue -> bot.dialogue
    角色/roles -> bot.roles
    清理历史/历史/history -> bot.history
    暂停/pause / 继续/resume -> bot.control

格式：``/<昵称><动词>[ 剩余文本]``，例如 ``/岸宝帮助``、``/岸宝为什么``。
昵称未配置时别名关闭；标准 ``/bot ...`` 前缀不受影响。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_VERB_MAP: dict[str, str] = {
    "帮助": "bot.help",
    "help": "bot.help",
    "状态": "bot.status",
    "status": "bot.status",
    "为什么": "bot.why",
    "为啥": "bot.why",
    "why": "bot.why",
    "记忆": "bot.memory",
    "memory": "bot.memory",
    "配置": "bot.config",
    "config": "bot.config",
    "就绪": "bot.readiness",
    "readiness": "bot.readiness",
    "人格": "bot.persona",
    "persona": "bot.persona",
    "对话验收": "bot.dialogue",
    "dialogue": "bot.dialogue",
    "角色": "bot.roles",
    "roles": "bot.roles",
    "清理历史": "bot.history",
    "历史": "bot.history",
    "history": "bot.history",
    "暂停": "bot.control",
    "pause": "bot.control",
    "继续": "bot.control",
    "resume": "bot.control",
    "天气": "bot.weather",
    "查询天气": "bot.weather",
    "查询": "bot.status",
    "查询订阅": "bot.subscribe",
    "查询日志": "bot.logs",

    "查天气": "bot.weather",
    "weather": "bot.weather",
    "点歌": "bot.music",
    "点歌模式": "bot.music_mode",
    "music mode": "bot.music_mode",
    "music": "bot.music",
    "wiki": "bot.wiki",
    "维基": "bot.wiki",
    "维基百科": "bot.wiki",
    "wikipedia": "bot.wiki",
    "epic": "bot.epic",
    "epicfree": "bot.epic",
    "epic免费": "bot.epic",
    "epic free": "bot.epic",
    "历史上的今天": "bot.today_history",
    "今日历史": "bot.today_history",
    "订阅": "bot.subscribe",
    "subscribe": "bot.subscribe",
    "日志": "bot.logs",
    "偷表情": "bot.meme_library",
    "偷表情包": "bot.meme_library",
    "随机表情": "bot.meme_library",
    "表情库统计": "bot.meme_library",
    "表情统计": "bot.meme_library",
    "logs": "bot.logs",
}


@dataclass(frozen=True)
class AliasResolution:
    capability_id: str
    verb: str
    rest_text: str


class CommandAliasResolver:
    """把昵称命令解析成能力 id；不负责执行，执行仍走统一流水线。

    支持多昵称：``nicknames`` 传多个，任一命中即可。
    """

    def __init__(
        self,
        *,
        nickname: str = "",
        nicknames: list[str] | tuple[str, ...] = (),
        verb_map: dict[str, str] | None = None,
    ) -> None:
        raw_nicknames: list[str] = []
        if nickname.strip():
            raw_nicknames.append(nickname.strip())
        raw_nicknames.extend(str(item).strip() for item in nicknames if str(item).strip())
        self.nicknames = list(dict.fromkeys(raw_nicknames))
        self.verb_map = dict(verb_map or DEFAULT_VERB_MAP)
        self._patterns: list[tuple[re.Pattern[str], str, str]] = []
        for current_nickname in self.nicknames:
            escaped = re.escape(current_nickname)
            # 长动词优先，避免 "清理历史" 被 "历史" 抢先匹配。
            for verb, capability_id in sorted(
                self.verb_map.items(), key=lambda item: -len(item[0])
            ):
                self._patterns.append(
                    (
                        re.compile(rf"^/?{escaped}{re.escape(verb)}(?:\s+(.*))?$", flags=re.IGNORECASE),
                        verb,
                        capability_id,
                    )
                )

    def resolve(self, text: str) -> AliasResolution | None:
        stripped = (text or "").strip()
        if not stripped:
            return None
        for pattern, verb, capability_id in self._patterns:
            match = pattern.match(stripped)
            if match:
                return AliasResolution(
                    capability_id=capability_id,
                    verb=verb,
                    rest_text=(match.group(1) or "").strip(),
                )
        return None


def build_command_alias_resolver(
    config: object,
    extra_nicknames: list[str] | tuple[str, ...] = (),
) -> CommandAliasResolver:
    """按配置构造；昵称优先取人格级配置（随人格走），兼容旧的
    runtime 级字段，再叠加实例设置 store 里的动态昵称。"""
    nicknames: list[str] = []
    persona_nicknames = getattr(config, "bot_persona_nicknames", []) or []
    for item in persona_nicknames:
        if str(item).strip():
            nicknames.append(str(item).strip())
    single = str(getattr(config, "bot_runtime_persona_nickname", "")).strip()
    if single:
        nicknames.append(single)
    configured = getattr(config, "bot_runtime_persona_nicknames", []) or []
    for item in configured:
        if str(item).strip():
            nicknames.append(str(item).strip())
    for item in extra_nicknames:
        if str(item).strip():
            nicknames.append(str(item).strip())
    instance_name = str(getattr(config, "bot_runtime_instance", "")).strip()
    if instance_name and instance_name.lower() != "default":
        nicknames.append(instance_name)
    return CommandAliasResolver(nicknames=nicknames)

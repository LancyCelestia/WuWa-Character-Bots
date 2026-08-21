"""角色昵称命令别名：把 "/岸宝帮助" 这类输入解析成能力 id。

默认映射（动词 → capability_id）：::

    帮助/help -> wuwa.help
    状态/status -> wuwa.status
    为什么/为啥/why -> wuwa.why
    记忆/memory -> wuwa.memory
    配置/config -> wuwa.config
    就绪/readiness -> wuwa.readiness
    人格/persona -> wuwa.persona
    对话验收/dialogue -> wuwa.dialogue
    角色/roles -> wuwa.roles
    清理历史/历史/history -> wuwa.history
    暂停/pause / 继续/resume -> wuwa.control

格式：``/<昵称><动词>[ 剩余文本]``，例如 ``/岸宝帮助``、``/岸宝为什么``。
昵称未配置时别名关闭；标准 ``/wuwa ...`` 前缀不受影响。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_VERB_MAP: dict[str, str] = {
    "帮助": "wuwa.help",
    "help": "wuwa.help",
    "状态": "wuwa.status",
    "status": "wuwa.status",
    "为什么": "wuwa.why",
    "为啥": "wuwa.why",
    "why": "wuwa.why",
    "记忆": "wuwa.memory",
    "memory": "wuwa.memory",
    "配置": "wuwa.config",
    "config": "wuwa.config",
    "就绪": "wuwa.readiness",
    "readiness": "wuwa.readiness",
    "人格": "wuwa.persona",
    "persona": "wuwa.persona",
    "对话验收": "wuwa.dialogue",
    "dialogue": "wuwa.dialogue",
    "角色": "wuwa.roles",
    "roles": "wuwa.roles",
    "清理历史": "wuwa.history",
    "历史": "wuwa.history",
    "history": "wuwa.history",
    "暂停": "wuwa.control",
    "pause": "wuwa.control",
    "继续": "wuwa.control",
    "resume": "wuwa.control",
}


@dataclass(frozen=True)
class AliasResolution:
    capability_id: str
    verb: str
    rest_text: str


class CommandAliasResolver:
    """把昵称命令解析成能力 id；不负责执行，执行仍走统一流水线。"""

    def __init__(
        self,
        *,
        nickname: str = "",
        verb_map: dict[str, str] | None = None,
    ) -> None:
        self.nickname = (nickname or "").strip()
        self.verb_map = dict(verb_map or DEFAULT_VERB_MAP)
        self._patterns: list[tuple[re.Pattern[str], str, str]] = []
        if self.nickname:
            escaped = re.escape(self.nickname)
            # 长动词优先，避免 "清理历史" 被 "历史" 抢先匹配。
            for verb, capability_id in sorted(
                self.verb_map.items(), key=lambda item: -len(item[0])
            ):
                self._patterns.append(
                    (
                        re.compile(rf"^/{escaped}{re.escape(verb)}(?:\s+(.*))?$"),
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


def build_command_alias_resolver(config: object) -> CommandAliasResolver:
    """按配置构造；``wuwa_runtime_persona_nickname`` 为空时别名关闭。"""
    nickname = str(getattr(config, "wuwa_runtime_persona_nickname", "")).strip()
    return CommandAliasResolver(nickname=nickname)

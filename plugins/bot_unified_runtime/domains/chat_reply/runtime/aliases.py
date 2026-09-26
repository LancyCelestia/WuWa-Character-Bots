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
from pathlib import Path

MODULE_ALIASES: dict[str, str] = {
    "model": "model",
    "模型": "model",
    "help": "help",
    "帮助": "help",
    "runtime": "runtime",
    "功能管理": "feature",
    "设置": "runtime",
    "参数": "runtime",
    "wiki": "wiki",
    "维基": "wiki",
    "百科": "wiki",
    # 繁體形（TRA 草稿 幫助/設置/參數 词条）：/bot 幫助 等此前墜 help 兜底。
    "幫助": "help",
    "設置": "runtime",
    "參數": "runtime",
}

_COMMAND_ACTION_ALIASES: dict[str, str] = {
    "添加": "add",
    "新增": "add",
    "切换": "set",
    "切换模型": "set",
    "查看": "list",
    "列表": "list",
    "用量": "usage",
    "用量统计": "usage",
    "搜索": "search",
    "联网": "search",
    "思考": "think",
    "推理": "think",
    "模型": "model",
}


def normalize_command_text(command_text: str) -> str:
    """Normalize module/action tokens while preserving parameter spelling/content."""
    parts = (command_text or "").strip().split(maxsplit=2)
    if not parts:
        return ""
    module = MODULE_ALIASES.get(parts[0].lower(), parts[0].lower())
    if len(parts) == 1:
        return module
    if module not in {"model", "runtime"}:
        return f"{module} {parts[1]}" + (f" {parts[2]}" if len(parts) == 3 else "")
    raw_action = parts[1]
    action = _COMMAND_ACTION_ALIASES.get(raw_action, raw_action.lower())
    return f"{module} {action}" + (f" {parts[2]}" if len(parts) == 3 else "")


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
    "天气预报": "bot.weather",
    "查询天气": "bot.weather",
    "查询": "bot.status",
    "查询订阅": "bot.subscribe",
    "查询日志": "bot.logs",

    "查天气": "bot.weather",
    "weather": "bot.weather",
    "点歌": "bot.music",
    "点唱": "bot.music",
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
    "免费游戏": "bot.epic",
    "吃什么": "bot.eat",
    "吃啥": "bot.eat",
    "今天吃什么": "bot.eat",
    "菜谱": "bot.eat",
    "怎么做": "bot.eat",
    "游戏免费": "bot.epic",
    "steam免费": "bot.epic",
    "steam free": "bot.epic",
    "历史上的今天": "bot.today_history",
    "今日历史": "bot.today_history",
    "好感度": "bot.affinity",
    "好感查看": "bot.affinity",
    "查询好感": "bot.affinity",
    # F15（2026-09-12 实弹反馈⑮）：繁体/常见变体触发词补齐。
    "好感值": "bot.affinity",
    "親密度": "bot.affinity",
    "點歌": "bot.music",
    "點唱": "bot.music",
    "隨機圖": "bot.randpic",
    "來張圖": "bot.randpic",
    "快報": "bot.news",
    "財經新聞": "bot.news",
    "國際新聞": "bot.news",
    "天氣": "bot.weather",
    "查天氣": "bot.weather",
    "天氣預報": "bot.weather",
    # F9（2026-09-12 实弹反馈⑨⑮）：快报族此前只有 base-router 裸触发，
    # 昵称命令（守岸人 AI新闻）坠 help 兜底——「AI新闻调不出」的根因。
    "快报": "bot.news",
    "今日快报": "bot.news",
    "今日热点": "bot.news",
    "AI新闻": "bot.news",
    "AI快报": "bot.news",
    "科技新闻": "bot.news",
    "财经新闻": "bot.news",
    "财经快报": "bot.news",
    "国际新闻": "bot.news",
    "ai news": "bot.news",
    "订阅": "bot.subscribe",
    "訂閱": "bot.subscribe",
    "subscribe": "bot.subscribe",
    "日志": "bot.logs",
    "偷表情": "bot.meme_library",
    "偷表情包": "bot.meme_library",
    "随机表情": "bot.meme_library",
    "隨機表情": "bot.meme_library",
    "表情库统计": "bot.meme_library",
    "表情统计": "bot.meme_library",
    "logs": "bot.logs",
    # TRA 草稿（2026-09-13 繁體缺失补齐批）：昵称动词繁體对向补齐，
    # 防「守岸人幫助/守岸人暫停」类坠空（F15 同哲学）。
    "幫助": "bot.help",
    "狀態": "bot.status",
    "暫停": "bot.control",
    "繼續": "bot.control",
    "查詢好感": "bot.affinity",
    "免費遊戲": "bot.epic",
    "遊戲免費": "bot.epic",
    "steam免費": "bot.epic",
    # P-03（2026-09-15）：决策影子痕迹查询触发词（admin_only，/bot decision）。
    "决策": "bot.decision",
    "decision": "bot.decision",
    # 管理昵称沿用 /bot 引导；执行能力与 feature 命令保持一致。
    "功能管理": "bot.runtime",
    "feature": "bot.runtime",
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


def _load_persona_alias_file(config: object) -> list[str]:
    """读取 personas/<profile>/aliases.txt（竖线分隔）。

    历史事故：该文件曾长期没有任何代码消费——昵称词表全靠 env，生产没配
    BOT_PERSONA_NICKNAMES 时「岸宝」根本不在称呼词表里，群里叫破喉咙也没人应。
    这里把它真正接线；文件缺失/不可读时静默跳过（下方还有硬编码兜底）。
    """
    profile = str(getattr(config, "bot_persona_profile_id", "") or "").strip()
    if not profile:
        return []
    candidate = Path("personas") / profile / "aliases.txt"
    try:
        raw = candidate.read_text(encoding="utf-8")
    except OSError:
        return []
    return [item.strip() for item in raw.replace("\n", "|").split("|") if item.strip()]


def persona_alias_terms(config: object) -> tuple[str, ...]:
    """守岸人称呼全集（**唯一对外口径**）：人格别名文件 ∪ 官方策展兜底。

    为什么要有这个公共口：``_load_persona_alias_file`` 与
    :data:`DEFAULT_PERSONA_NICKNAMES` 此前只被本模块的解析器内部消费，别的域
    想用「哪些词算指代守岸人」就只能自己硬写人名——表情库的主体判定（收图时
    「这张画的是不是她」）正是第二个消费者。收在这里 ⇒ 名单只有一份，
    ``personas/shorekeeper/aliases.txt`` 一改处处跟随（AGENTS 铁律：禁第二真身）。

    顺序稳定、去重、去空；文件不可读时只剩兜底表（与解析器同口径，不抛异常）。
    """
    collected: list[str] = []
    persona_nicknames = getattr(config, "bot_persona_nicknames", []) or []
    for item in [*persona_nicknames, *_load_persona_alias_file(config), *DEFAULT_PERSONA_NICKNAMES]:
        text = str(item or "").strip()
        if text and text not in collected:
            collected.append(text)
    return tuple(collected)


# 官方策展昵称硬编码兜底：与 personas/shorekeeper/aliases.txt 保持一致。
# 用户实际使用中的子昵称全集（含「我的蒙娜丽莎」「第二实例」）——
# env 未配置任何昵称时也必须能被叫应（2026-09-11 昵称无响应问题根因修复）。
DEFAULT_PERSONA_NICKNAMES: tuple[str, ...] = (
    "岸宝",
    "守岸人",
    "小岸同学",
    "我的蒙娜丽莎",
    "第二实例",
    "蓝蝴蝶",
    "花房的守护者",
    "漂泊的终点",
    "独属于我的蒙娜丽莎",
)


def build_command_alias_resolver(
    config: object,
    extra_nicknames: list[str] | tuple[str, ...] = (),
) -> CommandAliasResolver:
    """按配置构造；昵称优先取人格级配置（随人格走），兼容旧的
    runtime 级字段，再叠加实例设置 store 里的动态昵称；
    全部为空时落官方策展昵称兜底（保证默认可被叫应）。"""
    nicknames: list[str] = []
    persona_nicknames = getattr(config, "bot_persona_nicknames", []) or []
    for item in persona_nicknames:
        if str(item).strip() and str(item).strip() not in nicknames:
            nicknames.append(str(item).strip())
    single = str(getattr(config, "bot_runtime_persona_nickname", "")).strip()
    if single and single not in nicknames:
        nicknames.append(single)
    configured = getattr(config, "bot_runtime_persona_nicknames", []) or []
    for item in configured:
        if str(item).strip() and str(item).strip() not in nicknames:
            nicknames.append(str(item).strip())
    for item in _load_persona_alias_file(config):
        if item not in nicknames:
            nicknames.append(item)
    for item in extra_nicknames:
        if str(item).strip() and str(item).strip() not in nicknames:
            nicknames.append(str(item).strip())
    instance_name = str(getattr(config, "bot_runtime_instance", "")).strip()
    if instance_name and instance_name.lower() != "default" and instance_name not in nicknames:
        nicknames.append(instance_name)
    if not nicknames:
        nicknames.extend(DEFAULT_PERSONA_NICKNAMES)
    return CommandAliasResolver(nicknames=nicknames)

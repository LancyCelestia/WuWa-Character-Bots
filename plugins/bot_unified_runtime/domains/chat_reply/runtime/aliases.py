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

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 人格附属资产（aliases.txt / imagery_families.txt / registry/*.json）的**唯一一根**：
# 本件位于 .../domains/chat_reply/runtime/aliases.py，parents[5]＝仓库根——与
# character/imagery_roster.py::_repo_root、character/persona_profile.py::_REPO_ROOT、
# character/glossary.py 同式。**不许换成相对 cwd 的路径**：那会让"人格侧词表"在
# cwd≠仓库根时读空、静默塌回主人格的策展兜底表（切人格只换外观的一条成因）。
_REPO_ROOT = Path(__file__).resolve().parents[5]

MODULE_ALIASES: dict[str, str] = {
    "model": "model",
    "模型": "model",
    "help": "help",
    "帮助": "help",
    "runtime": "runtime",
    "功能管理": "feature",
    # 描写档中文词头（席 aliasgap，2026-10-04）：`/bot 描写 …` 与 `/bot narration …`
    # 是同一支 handler 的两个词头。词面**只准住这一格**——派发条件式只读 canonical 名
    # （`功能管理 → feature` 的在册先例同式；此前中文词头被硬写进 `__init__.py` 的
    # 条件式里＝第二处声明位，判据锁 tests/test_narration_alias_dispatch.py）。
    # ⚠ 只搬**词头**：四枚子命令（speech/scene/reset/show）的词表真身仍是
    # `content_route._NARRATION_SUBCOMMAND_TABLE`，本格不收录它们（裁定 G-0 乙：
    # 命令面走英文子命令、人格口语面走中文整句，两套词面互不引用）。
    "描写": "narration",
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
    # S-ALBUM（2026-09-30）表情册面（管理员册账，简繁成对，同 隨機/随机 口径）：
    # 缺这两键时「守岸人 表情册」会坠 help 兜底（F9 同因）。
    "表情册": "bot.meme_library",
    "表情相冊": "bot.meme_library",
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
    这里把它真正接线；文件缺失/不可读时**只申报缺席**（本模块不再无条件兜底：
    兜底表是否入场由 :func:`_curated_fallback_applies` 判，非主人格不借）。

    根＝**包内定位的仓库根**（`_REPO_ROOT`），不是当前工作目录：原先写的是
    ``Path("personas") / …``，只有 cwd 恰为仓库根时才读得到。这份词表是**跟着人格走**
    的文本腿资产——读不到时 ``DEFAULT_PERSONA_NICKNAMES``（出厂主人格的策展九名）会静默
    顶上来，于是"切了人格、称呼还是原来那套"，而日志一切正常（台账 #66★ 同型：
    盘上状态≠运行时状态）。意象名册 ``imagery_roster._repo_root()``、人格册
    ``persona_profile._REPO_ROOT``、术语表 ``glossary`` 早就是同一根，本件并过去
    （一根锁：tests/test_seat_t1_persona_contract_20261002.py）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        resolve_persona_id,
    )

    profile = resolve_persona_id(config)
    if not profile:
        return []
    candidate = _REPO_ROOT / "personas" / profile / "aliases.txt"
    try:
        raw = candidate.read_text(encoding="utf-8")
    except OSError as exc:
        # 缺文件在「新建人格册还没配词表」时是正常态（与 imagery_roster 同口径），
        # 只留 debug；每消息一 WARN 会把日志刷成噪音。
        logger.debug(
            "persona alias file unreadable profile=%s type=%s", profile, type(exc).__name__
        )
        return []
    terms = [item.strip() for item in raw.replace("\n", "|").split("|") if item.strip()]
    if not terms:
        # 文件在而读空＝文本腿要塌向兜底表（兜底表是**主人格**的策展名，切人格时最危险）：
        # 留一行可 grep 的读数，别让人回头猜「改了 aliases.txt 怎么没生效」。
        logger.warning("persona alias file parsed empty profile=%s", profile)
    return terms


def _curated_fallback_applies(config: object) -> bool:
    """策展兜底表只对**主人格那一格**生效（S5 多人格隔离波 单元 1）。

    旧行为＝无条件并上 ``DEFAULT_PERSONA_NICKNAMES``：那九名是**主人格**的策展称呼，
    切到备用人格后它继续把"旧人格的名字"当"当前人格的名字"——昵称门、表情主体判定、
    命令别名三条腿一起认错人，而盘上的 ``personas/<新人格>/aliases.txt`` 缺席这件事
    被兜底表吃掉了（台账 #66★ 同型：盘上状态≠运行时状态）。
    现在：非主人格缺词表＝**申报缺席**（只回 env 显式昵称 + 文件读数，可能为空），
    由调用方按"这一格没备料"处理。主人格档沿用兜底（2026-09-11 昵称无响应根修不许回退）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        main_persona_id,
        resolve_persona_id,
    )

    wanted = resolve_persona_id(config)
    if not wanted:
        return True  # 连"生效谁"都取不到＝没切过，保持出厂行为
    if wanted == main_persona_id():
        return True
    # 🔴 缺席必须留痕（S5c：与 ``imagery_roster.load_imagery_families`` 同口径——
    # 读不到只记一行可 grep 的读数，级别按"新建人格册还没配词表属正常态"取 debug，
    # 不刷 WARN 噪音）。没这一行的后果＝非主人格拿到空名册却无人知道是"没备料"
    # 还是"读错了根"，排查只能靠猜（台账 #66★ 同型：盘上状态≠运行时状态）。
    logger.debug(
        "persona alias curated fallback declined profile=%s reason=not_main_persona"
        " (honest absence: this persona ships no aliases.txt of its own)",
        wanted,
    )
    return False


def persona_alias_terms(config: object) -> tuple[str, ...]:
    """当前生效人格的称呼全集（**唯一对外口径**）：人格别名文件 ∪ env ∪ 主人格策展兜底。

    兜底那一支只在**主人格生效**时才入场（见 :func:`_curated_fallback_applies`）：
    非主人格既没 env 昵称又没自己的 ``aliases.txt`` ⇒ 返回**空名册**＝申报缺席，
    绝不借主人格的九名顶上（那等于"叫新人格却用旧人格的名字应"）。

    为什么要有这个公共口：``_load_persona_alias_file`` 与
    :data:`DEFAULT_PERSONA_NICKNAMES` 此前只被本模块的解析器内部消费，别的域
    想用「哪些词算指代当前人格」就只能自己硬写人名——表情库的主体判定（收图时
    「这张画的是不是她」）正是第二个消费者。收在这里 ⇒ 名单只有一份，
    ``personas/<persona_id>/aliases.txt`` 一改处处跟随（AGENTS 铁律：禁第二真身）。

    顺序稳定、去重、去空；文件不可读时只剩兜底表（与解析器同口径，不抛异常）——
    但兜底表是否入场由 :func:`_curated_fallback_applies` 判，非主人格不借。
    """
    collected: list[str] = []
    persona_nicknames = getattr(config, "bot_persona_nicknames", []) or []
    curated: tuple[str, ...] = DEFAULT_PERSONA_NICKNAMES if _curated_fallback_applies(
        config
    ) else ()
    for item in [
        *persona_nicknames,
        *_load_persona_alias_file(config),
        *curated,
    ]:
        text = str(item or "").strip()
        if text and text not in collected:
            collected.append(text)
    return tuple(collected)


# 官方策展昵称兜底：**主人格**（``is_main`` 那一格）aliases.txt 的同内容副本，
# 且只在主人格生效时并入（见 :func:`_curated_fallback_applies`）。
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
    if not nicknames and _curated_fallback_applies(config):
        # 非主人格走到这里＝这一格既没 env 昵称也没词表 ⇒ **申报缺席**（解析器
        # 拿到空名册＝谁都叫不应），绝不借主人格的九名顶上（S5 单元 1）。
        nicknames.extend(DEFAULT_PERSONA_NICKNAMES)
    return CommandAliasResolver(nicknames=nicknames)

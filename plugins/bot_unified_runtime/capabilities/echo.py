from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path
from typing import Any, TypedDict

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.config_readiness import run_config_smoke
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    new_request_id,
)
from plugins.bot_unified_runtime.policy.roles import build_role_settings
from plugins.bot_unified_runtime.runtime import RuntimeControlState


class HelpEntry(TypedDict, total=False):
    topic: str
    admin_only: bool
    aliases: tuple[str, ...]
    index: str
    title_line: str
    lines: list[str]
    detail: str


def _is_admin_actor(actor_roles: list[str] | None) -> bool:
    return "admin" in {str(role).strip() for role in (actor_roles or [])}


def build_status_result(
    config: Config | None = None,
    request_id: str | None = None,
    runtime_control: RuntimeControlState | None = None,
    actor_roles: list[str] | None = None,
) -> CapabilityResult:
    # 管理员门（审计重发现 P2）：status 会输出软暂停状态/原因、角色计数、
    # LLM provider/model、api_key set/missing、限速 bypass 角色等运行时姿态，
    # 与 debug 排障命令同档，不对普通成员开放。
    if not _is_admin_actor(actor_roles):
        return CapabilityResult(
            request_id=request_id or new_request_id("status"),
            capability_id="bot.status",
            kind="text",
            title="状态",
            body="只有管理员可以查看运行时状态。",
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            send_policy=SendPolicy.IMMEDIATE,
        )
    status_config = config or Config()
    return CapabilityResult(
        request_id=request_id or new_request_id("status"),
        capability_id="bot.status",
        kind="text",
        title="状态",
        body=_build_status_body(status_config, runtime_control or RuntimeControlState()),
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
    )


def normalize_help_topic(query: str) -> str | None:
    return _HELP_ALIAS_MAP.get((query or "").strip().lower())


def parse_help_command_text(command_text: str) -> str:
    """把 '/bot help <主题>'、'/bot 帮助 <主题>'、'帮助 <主题>' 中的主题提取出来。"""
    text = (command_text or "").strip()
    lowered = text.lower()
    for prefix in ("/bot", "/!"):
        if lowered == prefix:
            return ""
        if lowered.startswith(prefix + " "):
            text = text[len(prefix):].strip()
            lowered = text.lower()
            break
    for prefix in ("help", "帮助"):
        if lowered == prefix:
            return ""
        if lowered.startswith((prefix + " ", prefix + "　")):
            return text[len(prefix):].strip()
    return text


def resolve_help_query(command_text: str) -> str:
    """接入层用：只有明确是 help/帮助 前缀时才把主题交给帮助详情；其余回空=总览。"""
    text = (command_text or "").strip()
    lowered = text.lower()
    if lowered.startswith("/bot"):
        text = text[len("/bot"):].strip()
        lowered = text.lower()
    if (
        lowered in {"help", "帮助"}
        or lowered.startswith(("help ", "帮助 ", "help　", "帮助　"))
    ):
        return parse_help_command_text(text)
    return ""


_HELP_PAGE_COUNT = 1
_HELP_INDEX_COMMAND_TOPICS = frozenset(
    {"上下文", "对话", "模型", "接入", "配置", "就绪", "角色", "人格"}
)
# Ordinary users see only interactive public capabilities. Diagnostics, state,
# history, memory and administration remain available to administrators.
_PUBLIC_HELP_TOPICS = frozenset(
    {"订阅", "点歌", "表情", "天气", "维基", "萌娘百科", "历史上的今天", "下载", "昵称", "链接", "Epic", "好感度", "吃什么", "偷表情"}
)


def _visible_help_entries(is_admin: bool) -> list[HelpEntry]:
    if is_admin:
        return list(_HELP_ENTRIES)
    return [entry for entry in _HELP_ENTRIES if entry["topic"] in _PUBLIC_HELP_TOPICS]


def _help_index_line(entry: HelpEntry) -> str:
    if entry["topic"] in _HELP_INDEX_COMMAND_TOPICS:
        return str(entry["index"])
    return f"【{entry['topic']}】"


_HELP_CATEGORIES = (
    (
        "管理员专属",
        {
            "状态", "为什么", "回执", "审计", "最近", "日志", "解析", "记忆",
            "上下文", "对话", "历史", "人格", "角色", "队列", "配置", "就绪",
            "接入", "暂停", "回复", "设置", "路由", "邮件", "Telegram", "供应商",
            "草稿", "凭据", "群策略",
        },
    ),
    ("大模型相关", {"模型", "搜索"}),
    (
        "子功能",
        {
            "链接", "下载", "订阅", "点歌", "表情", "偷表情", "Epic",
            "历史上的今天", "天气", "维基", "萌娘百科", "昵称", "吃什么", "好感度",
        },
    ),
)


def _help_index_body(*, page: int, is_admin: bool) -> str:
    """One-page categorized overview; ``help 1/2`` stays a compatibility alias.

    每行末尾附二级展开引导：回复 /bot help <模块> 查看该模块逐参数说明。
    """
    entries = _visible_help_entries(is_admin)
    by_topic = {str(entry["topic"]): entry for entry in entries}
    title = "管理员帮助总览" if is_admin else "功能帮助总览"
    lines = [title, "（回复 /bot help 模块名 看该模块子功能与参数）"]

    def _index_line(entry: HelpEntry) -> str:
        index = str(entry["index"])
        topic = str(entry["topic"])
        if "help " in index or "bot " in index and "/" in index:
            # 指令型条目已带完整用法，不重复堆叠引导。
            return index
        return f"{index}｜详情：/bot help {topic}"

    categorized: set[str] = set()
    for category, topics in _HELP_CATEGORIES:
        category_entries = [by_topic[topic] for topic in topics if topic in by_topic]
        if not category_entries:
            continue
        categorized.update(entry["topic"] for entry in category_entries)
        lines.extend(("", f"【{category}】"))
        lines.extend(_index_line(entry) for entry in category_entries)
    orphans = [entry for topic, entry in by_topic.items() if topic not in categorized]
    if orphans:
        lines.extend(("", "【更多】"))
        lines.extend(_index_line(entry) for entry in orphans)
    return "\n".join(lines)


def _help_unknown_body(query: str) -> str:
    display = (query or "").strip()
    if len(display) > 40:
        display = display[:40] + "…"
    return (
        f"没有找到「{display}」的帮助主题。\n"
        "试试 /bot 帮助 查看总览（/岸宝帮助 同样可用）；示例：/bot help 点歌、/bot help 订阅。"
    )


_HELP_ENTRIES: list[HelpEntry] = [
        {
            "topic": '状态',
            "admin_only": True,
            "aliases": ('状态', 'status'),
            "index": '【状态】查看运行状态摘要：/bot status',
            "title_line": '【状态】查看运行状态摘要',
            "lines": ['/bot status: 查看运行状态摘要，无参数'],
            "detail": '【状态】查看运行状态摘要\n/bot status: 查看运行状态摘要，无参数',
        },
        {
            "topic": '记忆',
            "admin_only": True,
            "aliases": ('记忆', 'memory'),
            "index": '【记忆】管理长期记忆：/bot memory add|list|delete',
            "title_line": '【记忆】管理长期记忆',
            "lines": ['/bot memory add: 记住一句话，<content>：任意内容，建议 ≤1200 字', '/bot memory list: 列出我的记忆，无参数', '/bot memory delete: 删除一条记忆，<fact_id>：形如 fact_xxxxxxxxxxxx，来自 add/list 输出'],
            "detail": '【记忆】管理长期记忆\n/bot memory add: 记住一句话，<content>：任意内容，建议 ≤1200 字\n/bot memory list: 列出我的记忆，无参数\n/bot memory delete: 删除一条记忆，<fact_id>：形如 fact_xxxxxxxxxxxx，来自 add/list 输出',
        },
        {
            "topic": '为什么',
            "admin_only": True,
            "aliases": ('为什么', '为啥', 'why'),
            "index": '【为什么】解释最近决策：/bot why [id]',
            "title_line": '【为什么】解释最近一次回复的决策与错误',
            "lines": ['/bot why: 查看决策解释，<id>：可选，request_id 或 debug_id，省略=最近一次'],
            "detail": '【为什么】解释最近一次回复的决策与错误\n/bot why: 查看决策解释，<id>：可选，request_id 或 debug_id，省略=最近一次',
        },
        {
            "topic": '回执',
            "aliases": ('回执', 'receipt'),
            "index": '【回执】查询发送回执：/bot receipt <request_id|debug_id>',
            "title_line": '【回执】查询发送回执',
            "lines": ['/bot receipt: 查询发送回执状态，<id>：必填，request_id 或 debug_id'],
            "detail": '【回执】查询发送回执\n/bot receipt: 查询发送回执状态，<id>：必填，request_id 或 debug_id',
        },
        {
            "topic": '审计',
            "aliases": ('审计', 'audit'),
            "index": '【审计】查询审计记录：/bot audit <request_id>',
            "title_line": '【审计】查询审计记录',
            "lines": ['/bot audit: 查询审计记录，<request_id>：必填，请求编号，敏感项仅管理员可见'],
            "detail": '【审计】查询审计记录\n/bot audit: 查询审计记录，<request_id>：必填，请求编号，敏感项仅管理员可见',
        },
        {
            "topic": '最近',
            "admin_only": True,
            "aliases": ('最近', 'recent'),
            "index": '【最近】最近诊断摘要：/bot recent [数量]',
            "title_line": '【最近】查看最近排障摘要',
            "lines": ['/bot recent: 查看最近诊断+回执+审计摘要，<count>：1-20 整数，默认 5'],
            "detail": '【最近】查看最近排障摘要\n/bot recent: 查看最近诊断+回执+审计摘要，<count>：1-20 整数，默认 5',
        },
        {
            "topic": '队列',
            "aliases": ('队列', 'queue'),
            "index": '【队列】发送队列状态：/bot queue',
            "title_line": '【队列】查看发送队列状态',
            "lines": ['/bot queue: 查看待发/处理中/重试/失败计数，无参数'],
            "detail": '【队列】查看发送队列状态\n/bot queue: 查看待发/处理中/重试/失败计数，无参数',
        },
        {
            "topic": '上下文',
            "aliases": ('上下文', 'context'),
            "index": '【上下文】测试上下文：/bot context [测试文本]',
            "title_line": '【上下文】测试注入给模型的上下文',
            "lines": ['/bot context: 测试上下文注入，<text>：可选，测试文本，省略用默认'],
            "detail": '【上下文】测试注入给模型的上下文\n/bot context: 测试上下文注入，<text>：可选，测试文本，省略用默认',
        },
        {
            "topic": '对话',
            "aliases": ('对话', 'dialogue', '对话测试'),
            "index": '【对话】对话诊断：/bot dialogue [测试文本]',
            "title_line": '【对话】本地跑一轮对话诊断',
            "lines": ['/bot dialogue: 跑一轮对话诊断，<text>：可选，测试文本，不改变线上状态'],
            "detail": '【对话】本地跑一轮对话诊断\n/bot dialogue: 跑一轮对话诊断，<text>：可选，测试文本，不改变线上状态',
        },
        {
            "topic": '接入',
            "aliases": ('接入', 'setup', 'llm setup'),
            "index": '【接入】LLM 接入清单：/bot setup llm',
            "title_line": '【接入】LLM 接入清单',
            "lines": ['/bot setup llm: 查看缺哪些配置与安全模板，无参数，不写 .env'],
            "detail": '【接入】LLM 接入清单\n/bot setup llm: 查看缺哪些配置与安全模板，无参数，不写 .env',
        },
        {
            "topic": '配置',
            "aliases": ('配置', 'config'),
            "index": '【配置】配置检查：/bot config',
            "title_line": '【配置】配置就绪检查',
            "lines": ['/bot config: 检查配置就绪状态（脱敏），无参数'],
            "detail": '【配置】配置就绪检查\n/bot config: 检查配置就绪状态（脱敏），无参数',
        },
        {
            "topic": '就绪',
            "aliases": ('就绪', 'readiness'),
            "index": '【就绪】聚合就绪状态：/bot readiness',
            "title_line": '【就绪】聚合就绪状态',
            "lines": ['/bot readiness: 查看环境/配置/上下文/对话链路状态，无参数'],
            "detail": '【就绪】聚合就绪状态\n/bot readiness: 查看环境/配置/上下文/对话链路状态，无参数',
        },
        {
            "topic": '角色',
            "aliases": ('角色', 'roles'),
            "index": '【角色】权限角色摘要：/bot roles',
            "title_line": '【角色】权限角色摘要',
            "lines": ['/bot roles: 查看角色数量摘要（不含具体 ID），无参数'],
            "detail": '【角色】权限角色摘要\n/bot roles: 查看角色数量摘要（不含具体 ID），无参数',
        },
        {
            "topic": '人格',
            "aliases": ('人格', 'persona'),
            "index": '【人格】人格自检：/bot persona',
            "title_line": '【人格】守岸人人格材料自检',
            "lines": ['/bot persona: 自检人格强度/语气规则/边界，无参数'],
            "detail": '【人格】守岸人人格材料自检\n/bot persona: 自检人格强度/语气规则/边界，无参数',
        },
        {
            "topic": '路由',
            "aliases": ('路由', 'route', 'routes'),
            "index": '【路由】路由判定：/bot route <文本>',
            "title_line": '【路由】查看文本命中的路由',
            "lines": ['/bot route: 判定一段文本的路由，<text>：必填，任意文本', '/bot routes: 查看全部路由表，无参数', '示例: /bot route 帮我解析这个 https://www.bilibili.com/video/BVxxxx'],
            "detail": '【路由】查看文本命中的路由\n/bot route: 判定一段文本的路由，<text>：必填，任意文本\n/bot routes: 查看全部路由表，无参数\n示例: /bot route 帮我解析这个 https://www.bilibili.com/video/BVxxxx',
        },
        {
            "topic": '历史',
            "aliases": ('历史', 'history', '清理历史'),
            "index": '【历史】清理会话历史：/bot history clear',
            "title_line": '【历史】清理本会话最近对话历史',
            "lines": ['/bot history clear: 清空本会话最近对话，无参数'],
            "detail": '【历史】清理本会话最近对话历史\n/bot history clear: 清空本会话最近对话，无参数',
        },
        {
            "topic": '暂停',
            "aliases": ('暂停', 'pause', 'resume', '恢复'),
            "index": '【暂停】软暂停/恢复：/bot pause|resume',
            "title_line": '【暂停】软暂停/恢复机器人回复',
            "lines": ['/bot pause: 软暂停回复（不改配置），无参数', '/bot resume: 恢复回复，无参数'],
            "detail": '【暂停】软暂停/恢复机器人回复\n/bot pause: 软暂停回复（不改配置），无参数\n/bot resume: 恢复回复，无参数',
        },
        {
            "topic": '回复',
            "aliases": ('回复', 'reply', '详略'),
            "index": '【回复】回复详略：/bot reply <详细|精简|默认>',
            "title_line": '【回复】调整回复详略档位',
            "lines": ['/bot reply: 查看当前档位，无参数', '/bot reply: 设置详略档位，<mode>：详细|精简|默认（别名 科普/详尽=详细，简洁=精简，自动=默认），仅管理员，设置后持久保存'],
            "detail": '【回复】调整回复详略档位\n/bot reply: 查看当前档位，无参数\n/bot reply: 设置详略档位，<mode>：详细|精简|默认（别名 科普/详尽=详细，简洁=精简，自动=默认），仅管理员，设置后持久保存',
        },
        {
            "topic": '模型',
            "aliases": ('模型', 'model', 'llm', '供应商', '切换模型'),
            "index": '【模型】/bot model list | set | add | update | priority | effort | price | remove | reset | health | probe | routes',
            "title_line": '【模型】模型与供应商管理（管理员，改动即时生效）',
            "lines": [
                '/bot llm: 诊断当前 provider/model/key 与一次短调用，不修改配置',
                '/bot model list: 查看全部模型、思考强度档位与故障转移顺序（priority 越小越先；同时显示当前时段分组）',
                '/bot model health: 查看渠道健康报告（正常/连续失败踢出/慢渠道，30 分钟半开重探自动回队）',
                '/bot model probe: 手动发起一轮全渠道巡检（每渠道一次最小调用，与后台巡检互斥），结果用 health 查看',
                '/bot model routes <模型名>: 按实测响应速度快→慢列出该模型的全部可用渠道（未实测的排后）',
                '/bot model set <id|auto>: 切换当前模型；auto=按时段分组/priority 顺序自动选型',
                '/bot model add <id> model=<模型名> base_url=<接口地址> key=<API密钥> [tags=档位] [effort=档位] [group=<分组>] [priority=<n>]: 新增供应商',
                '/bot model update <id> model=... base_url=... key=... tags=... effort=... group=... priority=...: 修改任意参数（可只写要改的项，可覆盖 .env 同名条目）',
                '/bot model priority <id> <n>: 只改故障转移顺序，n 越小越先被调用',
                '/bot model effort <id> <off|low|medium|high|xhigh|max|default>: 设置单模型思考强度；default=清除覆盖',
                '/bot model think <off|low|medium|high|xhigh|max|留空>: 全局思考强度；留空=各模型家族默认最高档',
                '/bot model price <模型名> input=<元/1M> output=<元/1M>: 设置价格，之后调用按新价记账',
                '/bot model usage [today|YYYY-MM-DD]: 每日用量账单（输入/缓存命中/缓存创建/输出/费用，按模型分组）',
                '/bot model search <on|off>: 热切换联网搜索，无需重启',
                '/bot model remove <id>: 删除自定义模型（.env 来源的条目不可删，只能 update 覆盖）',
                '/bot model vision list|add|update|priority|remove: 图片识别模型管理（参数同 add）',
                '/bot model vision mode <relay|direct>: relay=视觉模型转文字；direct=图片直传主模型',
                '/bot model reset: 清除手动指定，回到自动选型',
                '思考强度档位: DeepSeek/GLM/Kimi/MiniMax=low,high,max｜GPT/Grok=low,medium,high,xhigh｜Gemini=low,medium,high；默认=家族最高档',
                '时段分组: /bot runtime set BOT_MODEL_PRIORITY_GROUPS <JSON>（峰谷顺序，工作日高峰自动切换，改完立即生效）',
                '参数: id=自定义名称｜model=模型名｜base_url=OpenAI兼容接口（/v1 结尾）｜key=密钥或 env:变量名｜tags=档位列表｜effort=单模型覆盖｜group=令牌分组｜priority=数字越小越先',
                '示例: /bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1',
                '注意: key 不会被回显；等号两边不要加空格；新增/修改立即生效；价格与分组支持热更，重启后仍保留',
            ],
            "detail": (
                '【模型】模型与供应商管理（管理员，改动即时生效，无需重启）\n'
                '\n'
                '■ /bot model list\n'
                '  查看当前模型、当前时段分组、每个模型的思考强度档位（effort）与故障转移顺序。\n'
                '  顺序 = 时段分组命中的组内 order，否则 priority 从小到大。\n'
                '\n'
                '■ /bot model health\n'
                '  查看渠道健康报告：正常渠道、连续失败被踢出的渠道（30 分钟半开重探自动回队）与慢渠道标注。\n'
                '\n'
                '■ /bot model probe\n'
                '  手动发起一轮全渠道巡检（每渠道一次最小调用，费用极低）。与后台巡检互斥，进行中重复发起会有提示；\n'
                '  结果稍后用 /bot model health 查看。\n'
                '\n'
                '■ /bot model routes <模型名>\n'
                '  按实测响应速度 快→慢 列出该模型的全部可用渠道；未实测的按价格/优先级排在后面。\n'
                '\n'
                '■ /bot model set <id|auto>\n'
                '  切换当前使用的模型。id 必须是已存在的模型名或预设名；\n'
                '  auto = 回到自动选型（时段分组/priority 顺序，失败自动转移）。\n'
                '\n'
                '■ /bot model add <id> model=<模型名> base_url=<接口地址> key=<API密钥> [tags=档位] [effort=档位] [group=<分组>] [priority=<数字>]\n'
                '  新增一个自定义模型供应商。参数逐个说明：\n'
                '  · <id>：你给这个模型起的名字，字母数字，如 myapi（之后 set/update/remove 都用它）\n'
                '  · model=：供应商提供的模型名，原样填写，如 deepseek-v4-pro\n'
                '  · base_url=：OpenAI 兼容接口地址，必须以 http(s):// 开头，一般以 /v1 结尾\n'
                '  · key=：API 密钥，如 sk-xxx；也可写 env:变量名 引用环境变量（更安全）\n'
                '  · tags=：思考强度档位，逗号分隔。DeepSeek/GLM/Kimi/MiniMax=low,high,max；GPT/Grok=low,medium,high,xhigh；Gemini=low,medium,high\n'
                '  · effort=：可选，覆盖该模型默认思考强度；off=不发送；省略=家族最高档\n'
                '  · group=：可选，令牌分组名（同供应商多密钥时用）\n'
                '  · priority=：可选，整数，越小越先被调用；省略默认 100\n'
                '  · 常见错误：等号两边加了空格（会报“参数格式应为 键=值”）；漏写 model= 或 base_url=（会提示必填）\n'
                '  示例：/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1\n'
                '\n'
                '■ /bot model update <id> <键=值...>\n'
                '  修改已有模型的任意参数，只写要改的项，如：/bot model update myapi key=sk-new effort=high priority=3\n'
                '  可用键：model base_url key group tags effort priority。自定义条目与 .env 同名条目都可改。\n'
                '\n'
                '■ /bot model priority <id> <数字>\n'
                '  只调整故障转移顺序。数字越小，越早被调用；前一个失败时按顺序切到下一个。\n'
                '\n'
                '■ /bot model effort <id> <off|low|medium|high|xhigh|max|default>\n'
                '  设置单个模型的思考强度覆盖。default/默认=清除覆盖回到家族最高档；off=该模型不发送 reasoning_effort。\n'
                '  示例：/bot model effort umi-gpt-terra high\n'
                '\n'
                '■ /bot model think <off|low|medium|high|xhigh|max|留空>\n'
                '  全局思考强度（对所有未单独设置 effort 的模型生效）。\n'
                '  off=不发送 reasoning_effort；留空=清空覆盖，各模型回到家族默认最高档。\n'
                '  复杂任务（长文本/教程/分析类）会自动把全局/默认档位临时升到家族最高档。\n'
                '\n'
                '■ /bot model price <模型名> input=<元/1M输入> output=<元/1M输出>\n'
                '  设置每百万 token 价格（元）。成本按每次调用时刻的价格记账，之后调价不影响历史账单；峰谷差价因此天然正确。\n'
                '  示例：/bot model price deepseek-v4-pro input=4 output=16\n'
                '  清除：/bot model price deepseek-v4-pro（不带价格参数即清除）\n'
                '\n'
                '■ /bot model usage [today|YYYY-MM-DD]\n'
                '  每日用量账单：输入/输出/缓存命中/缓存创建 Token、调用次数、按调用时价格记账的费用，按模型分组。\n'
                '\n'
                '■ /bot model remove <id>\n'
                '  删除自定义模型。.env 的 BOT_MODEL_REGISTRY 来源条目不可删除（会提示），只能 update 覆盖。\n'
                '\n'
                '■ /bot model reset\n'
                '  清除手动指定，回到自动选型。\n'
                '\n'
                '■ 时段优先级分组（峰谷价格调序）\n'
                '  /bot runtime set BOT_MODEL_PRIORITY_GROUPS <JSON数组>\n'
                '  每组：{"name":"工作日高峰","days":[1,2,3,4,5],"windows":[["09:00","12:00"],["14:00","18:00"]],"order":[模型id...]}\n'
                '  days=ISO周编号（1=周一…7=周日），缺省=每天；windows 缺省=全天；两者都缺省=兜底组；\n'
                '  按列表顺序取第一个命中的组，命中组按 order 排序；未命中组外的模型按原 priority 排在后面。\n'
                '  只影响自动路由，手动 /bot model set 不受影响；热更立即生效。\n'
                '\n'
                '■ 图片/表情包识别（Vision）\n'
                '  /bot model vision list: 查看识别候选、优先级与开关状态。\n'
                '  /bot model vision add <id> model=<视觉模型> base_url=<接口> key=<API密钥> [priority=<n>]\n'
                '  /bot model vision mode relay|direct：relay=视觉模型转文字；direct=图片直传主模型。\n'
                '\n'
                '■ 分时段自动切换单个模型（可选，与分组互不影响）\n'
                '  /bot runtime set BOT_MODEL_SCHEDULE {"23:00-07:00":"luna"}\n'
                '  JSON 写法：时间窗"开始-结束"对应模型 id 或预设名；支持跨零点；窗口外自动回到自动选型。'
            ),
        },
        {
            "topic": '用量',
            "aliases": ('用量', 'usage', '账单', '花费', '监控'),
            "index": '【用量】/bot model usage：每日 Token/账单、阈值提醒与定时报告',
            "title_line": '【用量】Token 统计、费用记账与监控提醒',
            "lines": [
                '/bot model usage [today|YYYY-MM-DD]: 每日用量账单，无参数=今天',
                '/bot model price <模型名> input=<元/1M> output=<元/1M>: 维护价格表（热更）',
                '统计口径: 输入/缓存命中/缓存创建/输出 Token 按模型分组；费用按每次调用时刻的价格记账',
                '实时提醒: 单模型当日输出>500万 或 输入>5000万 token；当日账单>10元 → 自动推送管理员（阈值可在 .env 调整）',
                '定时报告: 北京时间 13:00/18:00/23:00 推送管理员——自上个报告点至今的金额与 Token；13:00 附过去 24 小时总花费',
                '未配置价格的模型不计费，账单会标注未计价调用次数',
                '管理员推送走 QQ 私聊预警管线；报告附带 Mica 云母质感账单卡图片（渲染不可用时回退文本）',
            ],
            "detail": (
                '【用量】Token 统计、费用记账与监控提醒\n'
                '\n'
                '■ /bot model usage [today|YYYY-MM-DD]\n'
                '  查看每日用量账单。统计每个模型的：输入 Token、缓存命中 Token、缓存创建 Token、\n'
                '  输出 Token、调用次数与费用；合计行给出当日总开销。\n'
                '  示例：/bot model usage 2026-09-01\n'
                '\n'
                '■ /bot model price <模型名> input=<元/1M输入> output=<元/1M输出>\n'
                '  维护价格表（元/每百万 token）。成本按调用时刻价格记账：\n'
                '  调价只影响之后的调用，历史账单不变；峰谷差价按调用时间天然区分。\n'
                '  示例：/bot model price deepseek-v4-pro input=4 output=16\n'
                '\n'
                '■ 实时阈值提醒（每 60 秒巡检当日数据，每项每天只提醒一次）\n'
                '  · 单模型当日输出 Token > 5,000,000；\n'
                '  · 单模型当日输入 Token > 50,000,000；\n'
                '  · 当日实际账单 > 10 元 → 立即发送报告卡 + 提醒（含各模型金额明细）。\n'
                '  阈值可在 .env 调整：BOT_USAGE_ALERT_OUTPUT_TOKENS / BOT_USAGE_ALERT_INPUT_TOKENS / BOT_USAGE_ALERT_DAILY_COST_YUAN\n'
                '\n'
                '■ 定时报告（北京时间 13:00 / 18:00 / 23:00）\n'
                '  统计自上个报告时间点至今的总花费（金额 + Token 数量）；\n'
                '  13:00 报告额外统计过去 24 小时总花费。报告时间点持久化，重启不丢。\n'
                '  报告时间可用 BOT_USAGE_REPORT_HOURS 调整（逗号分隔整点）。\n'
                '\n'
                '■ 推送与 UI\n'
                '  提醒与报告推送给全部管理员（QQ 私聊，走统一预警管线）；\n'
                '  渲染可用时附带 Mica 云母质感账单卡（大圆角、平台色派生），失败自动回退纯文本。'
            ),
        },
        {
            "topic": '设置',
            "aliases": ('设置', 'runtime', '参数', '运行时'),
            "index": '【设置】运行时参数：/bot runtime set|get|list',
            "title_line": '【设置】运行时参数管理（管理员）',
            "lines": ['/bot runtime set: 设置参数，<key>：可写键名（如 BOT_REPLY_DETAIL），<value>：键对应取值', '/bot runtime get: 读取参数，<key>：键名', '/bot runtime list: 列出覆盖项，无参数', '/bot runtime reset: 恢复默认，<key>：可选，省略=全部', '/bot runtime persona: 人格管理，<action>：list | switch <id|default> | probability <id> <0-1>', '/bot model: 模型与供应商管理（详见 /bot help 模型）：list | set | add | update | priority | effort | price | remove | reset | health | probe | routes', '/bot runtime set BOT_MODEL_SCHEDULE: 分时段自动切换模型，<value>：JSON，如 {"23:00-07:00":"luna"}', '/bot runtime set BOT_MODEL_PRIORITY_GROUPS: 时段优先级分组（峰谷顺序），<value>：JSON 数组', '/bot runtime set BOT_MODEL_PRICES: 每模型价格表，<value>：JSON 对象，如 {"deepseek-v4-pro":{"input":4,"output":16}}', '/bot runtime set BOT_CHAT_REASONING_EFFORT: 全局思考强度，<value>：off|low|medium|high|xhigh|max|留空', '/bot runtime nickname: 昵称管理，<action>：add|remove|list，<name>：昵称文本', '--instance: 可选开关，<name>：目标实例名'],
            "detail": '【设置】运行时参数管理（管理员）\n/bot runtime set: 设置参数，<key>：可写键名（如 BOT_REPLY_DETAIL），<value>：键对应取值\n/bot runtime get: 读取参数，<key>：键名\n/bot runtime list: 列出覆盖项，无参数\n/bot runtime reset: 恢复默认，<key>：可选，省略=全部\n/bot runtime persona: 人格管理，<action>：list | switch <id|default> | probability <id> <0-1>\n/bot runtime model: 模型管理（自定义供应商即时生效）\n  set <id|auto>: 切换当前模型（auto=自动选型）\n  list: 查看故障转移顺序与全部可用模型\n  add <id> model=<模型> base_url=<接口> key=<密钥|env:变量> [tags=fast,strong] [priority=<n>]: 新增供应商\n  update <id> <键=值...>: 修改供应商参数（可覆盖 .env 同名条目）\n  priority <id> <n>: 调整故障转移顺序（越小越先）\n  remove <id>: 删除自定义供应商\n  reset: 清除手动指定，回到自动选型\n/bot runtime set BOT_MODEL_SCHEDULE: 分时段自动切换模型，<value>：JSON 对象，如 {"23:00-07:00":"luna"}（跨零点窗口支持；窗口外自动回到自动选型）\n/bot runtime nickname: 昵称管理，<action>：add|remove|list，<name>：昵称文本\n--instance: 可选开关，<name>：目标实例名',
        },
        {
            "topic": '订阅',
            "aliases": ('订阅', 'subscribe'),
            "index": '【订阅】订阅内容推送：/订阅 add|list|pause|resume|remove',
            "title_line": '【订阅】订阅平台新内容推送',
            "lines": ['/订阅 add <公开目标>: 添加订阅并推送到当前会话（群=本群，私聊=自己）；目的地/日报等附加参数暂不支持', '/订阅 list: 列出订阅，群内仅管理员可看本群订阅，私聊只看推给自己的', '/订阅 pause|resume <id>: 暂停/恢复订阅，<id>：订阅编号，来自 list', '/订阅 remove <id>: 删除订阅', '权限: pause/resume/remove 群内需管理员且订阅推往本群，私聊需推给自己', '目标示例: https://space.bilibili.com/123456｜bilibili:up:123456｜music.163.com/playlist?id=xxx', '支持范围: B站（UP主/直播间/番剧/收藏夹/合集）、小红书、YouTube 频道、微博、推特、Pixiv、Telegram 频道、音乐平台（网易云/QQ/酷狗/酷我/Apple/Spotify 的歌手/专辑/歌单）；建议直接粘贴主页或链接'],
            "detail": '【订阅】订阅平台新内容推送\n/订阅 add <公开目标>: 添加订阅并推送到当前会话（群=本群，私聊=自己）；目的地/日报等附加参数暂不支持\n/订阅 list: 列出订阅，群内仅管理员可看本群订阅，私聊只看推给自己的\n/订阅 pause|resume <id>: 暂停/恢复订阅，<id>：订阅编号，来自 list\n/订阅 remove <id>: 删除订阅\n权限: pause/resume/remove 群内需管理员且订阅推往本群，私聊需推给自己\n目标示例: https://space.bilibili.com/123456｜bilibili:up:123456｜music.163.com/playlist?id=xxx\n支持范围: B站（UP主/直播间/番剧/收藏夹/合集）、小红书、YouTube 频道、微博、推特、Pixiv、Telegram 频道、音乐平台（网易云/QQ/酷狗/酷我/Apple/Spotify 的歌手/专辑/歌单）；建议直接粘贴主页或链接\n/订阅 与 /bot subscribe 等价',
        },
        {
            "topic": '点歌',
            "aliases": ('点歌', 'music', '點歌', 'song'),
            "index": '【点歌】搜索并发送歌曲：点歌 / 点歌模式',
            "title_line": '【点歌】搜索并发送歌曲',
            "lines": ['点歌: 播放指定歌曲，<song_name>：歌曲名称或关键词，支持中文或拼音', '点歌 <编号>: 多首同名歌曲时回复编号选择（如「点歌 2」），仅紧随候选列表、300 秒内有效', '点歌模式: 设置输出方式，<mode>：卡片|语音|音频|链接|全部，可组合，管理员持久化', '示例: 点歌 晴天｜候选出来后回复「点歌 2」｜点歌模式 卡片+语音', '常见错误：编号只在候选列表 300 秒内有效，过期或无效会提示重新点歌（不再当歌名搜索）；直接拿数字当歌名搜索不是有效歌名'],
            "detail": '【点歌】搜索并发送歌曲\n点歌: 播放指定歌曲，<song_name>：歌曲名称或关键词，支持中文或拼音\n点歌 <编号>: 多首同名歌曲时回复编号选择（如「点歌 2」），仅紧随候选列表、300 秒内有效\n点歌模式: 设置输出方式，<mode>：卡片|语音|音频|链接|全部，可组合，管理员持久化\n示例: 点歌 晴天｜候选出来后回复「点歌 2」｜点歌模式 卡片+语音\n常见错误：编号只在候选列表 300 秒内有效，过期或无效会提示重新点歌（不再当歌名搜索）；直接拿数字当歌名搜索不是有效歌名',
        },
        {
            "topic": '表情',
            "aliases": ('表情', 'meme', '表情包', '表情生成'),
            "index": '【表情】生成文字表情：表情 <key> <文字>',
            "title_line": '【表情】生成文字表情',
            "lines": ['表情: 生成表情，<key>：模板名，<text>：文字，多段用 ｜ 分隔', '表情 列表: 列出全部模板，无参数', '示例: 先「表情 列表」查模板名，再发「表情 模板名 你好」'],
            "detail": '【表情】生成文字表情\n表情: 生成表情，<key>：模板名，<text>：文字，多段用 ｜ 分隔\n表情 列表: 列出全部模板，无参数\n示例: 先「表情 列表」查模板名，再发「表情 模板名 你好」',
        },
        {
            "topic": '偷表情',
            "aliases": ('偷表情', '偷表情包', 'steal'),
            "index": '【偷表情】表情库随机：偷表情 [关键词]',
            "title_line": '【偷表情】从表情库随机抽取',
            "lines": ['偷表情: 随机发一张表情，<keyword>：可选，关键词/情绪标签，写「私聊/私聊我」等同不填关键词', '表情库统计: 查看库存数量，无参数', '示例: 偷表情｜偷表情 猫猫'],
            "detail": '【偷表情】从表情库随机抽取\n偷表情: 随机发一张表情，<keyword>：可选，关键词/情绪标签，写「私聊/私聊我」等同不填关键词\n表情库统计: 查看库存数量，无参数\n示例: 偷表情｜偷表情 猫猫',
        },
        {
            "topic": '天气',
            "aliases": ('天气', 'weather'),
            "index": '【天气】查询城市天气：天气 <城市>',
            "title_line": '【天气】查询城市天气',
            "lines": ['天气: 查询天气，<city>：城市名，同名城市用 省-市 区分', '示例: 天气 上海｜天气 浙江-杭州'],
            "detail": '【天气】查询城市天气\n天气: 查询天气，<city>：城市名，同名城市用 省-市 区分\n示例: 天气 上海｜天气 浙江-杭州',
        },
        {
            "topic": '维基',
            "aliases": ('维基', 'wiki', '百科'),
            "index": '【维基】查询百科：维基 <词条>',
            "title_line": '【维基】查询百科词条',
            "lines": ['维基: 查询百科词条，<word>：词条名', '示例: 维基 量子力学'],
            "detail": '【维基】查询百科词条\n维基: 查询百科词条，<word>：词条名\n示例: 维基 量子力学',
        },
        {
            "topic": '萌娘百科',
            "aliases": ('萌娘百科', '萌百', 'moegirl'),
            "index": '【萌娘百科】查询萌娘百科：萌娘百科 <词条>｜直接问 XX是谁',
            "title_line": '【萌娘百科】查询萌娘百科词条',
            "lines": ['萌娘百科: 查询萌娘百科词条，<word>：词条名', '直接问: 「初音未来是谁？」这类问句会自动查萌娘百科并回复；查不到时转人工聊天回答'],
            "detail": '【萌娘百科】查询萌娘百科词条\n萌娘百科: 查询萌娘百科词条，<word>：词条名\n直接问: 「初音未来是谁？」这类问句会自动查萌娘百科并回复；查不到时转人工聊天回答',
        },
        {
            "topic": '历史上的今天',
            "aliases": ('历史上的今天', 'today', '今日'),
            "index": '【历史上的今天】每日历史推送：设置|状态|取消',
            "title_line": '【历史上的今天】每天定时推送历史',
            "lines": ['历史上的今天: 立即查询当天历史，无参数', '历史上的今天 设置: 设置推送时间，<time>：HH:MM，24 小时制，取值 00:00-23:59', '示例: 历史上的今天 设置 08:30', '历史上的今天 状态: 查看推送状态，无参数', '历史上的今天 取消: 取消每日推送，无参数'],
            "detail": '【历史上的今天】每天定时推送历史\n历史上的今天: 立即查询当天历史，无参数\n历史上的今天 设置: 设置推送时间，<time>：HH:MM，24 小时制，取值 00:00-23:59\n示例: 历史上的今天 设置 08:30\n历史上的今天 状态: 查看推送状态，无参数\n历史上的今天 取消: 取消每日推送，无参数',
        },
        {
            "topic": '下载',
            "aliases": ('下载', 'download'),
            "index": '【下载】下载视频音频：/bot download <链接>',
            "title_line": '【下载】下载视频/音频',
            "lines": ['/bot download: 下载媒体文件，<url>：B站/油管/推特/小红书/抖音链接；单文件 ≤1GB，最高8K超限自动降级', '示例: /bot download https://www.bilibili.com/video/BVxxxxxxxx'],
            "detail": '【下载】下载视频/音频\n/bot download: 下载媒体文件，<url>：B站/油管/推特/小红书/抖音链接；单文件 ≤1GB，最高8K超限自动降级\n示例: /bot download https://www.bilibili.com/video/BVxxxxxxxx',
        },
        {
            "topic": '群策略',
            "aliases": ('群策略', 'group', '群'),
            "index": '【群策略】群回复策略档位：/bot group add|del|set|clear',
            "title_line": '【群策略】群聊回复策略档位（管理员）',
            "lines": ['/bot group list: 查看各档位，无参数', '/bot group add: 加入群，<tier>：black1|black2|white1|white2，<gid>：群号，数字可多个', '/bot group del: 移出群，<tier>：档位，<gid>：群号', '/bot group set: 覆盖档位，<tier>：档位，<gid>：群号', '/bot group clear: 清空档位，<tier>：档位', '示例: /bot group add white1 123456789 987654321'],
            "detail": '【群策略】群聊回复策略档位（管理员）\n/bot group list: 查看各档位，无参数\n/bot group add: 加入群，<tier>：black1|black2|white1|white2，<gid>：群号，数字可多个\n/bot group del: 移出群，<tier>：档位，<gid>：群号\n/bot group set: 覆盖档位，<tier>：档位，<gid>：群号\n/bot group clear: 清空档位，<tier>：档位\n示例: /bot group add white1 123456789 987654321',
        },
        {
            "topic": '日志',
            "aliases": ('日志', 'logs'),
            "index": '【日志】运行时日志：/bot logs [级别] [数量]',
            "title_line": '【日志】查看运行时事件日志',
            "lines": ['/bot logs: 查看运行日志，<级别>：debug|info|warning|error（默认 info），<数量>：1-200（默认 50），两个参数按「先级别后数量」的顺序写，仅管理员', '示例: /bot logs error 20'],
            "detail": '【日志】查看运行时事件日志\n/bot logs: 查看运行日志，<级别>：debug|info|warning|error（默认 info），<数量>：1-200（默认 50），两个参数按「先级别后数量」的顺序写，仅管理员\n示例: /bot logs error 20',
        },
        {
            "topic": '昵称',
            "aliases": ('昵称', 'alias'),
            "index": '【昵称】昵称触发命令：守岸人/岸宝 <命令>',
            "title_line": '【昵称】用角色昵称触发命令',
            "lines": ['守岸人/岸宝 <cmd>: 触发已映射的命令，<cmd>：命令名（帮助/状态/为什么/天气/点歌/订阅/日志等），斜杠可省略'],
            "detail": '【昵称】用角色昵称触发命令\n守岸人/岸宝 <cmd>: 触发任意命令，<cmd>：命令名，斜杠可省略',
        },
        {
            "topic": '链接',
            "aliases": ('链接', 'links'),
            "index": '【链接】链接自动解析：直接发平台链接',
            "title_line": '【链接】平台链接自动解析信息卡',
            "lines": ['发链接: 自动解析信息卡，<url>：B站/抖音/小红书/油管/推特/小黑盒/米游社/森空岛/库街区/Lofter/Pixiv/音乐平台链接'],
            "detail": '【链接】平台链接自动解析信息卡\n发链接: 自动解析信息卡，<url>：B站/抖音/小红书/油管/推特/小黑盒/米游社/森空岛/库街区/Lofter/Pixiv/音乐平台链接',
        },
        {
            "topic": '草稿',
            "aliases": ('草稿', 'autosend', '自动发送'),
            "index": '【草稿】自动发送草稿：给 A 发消息，内容…',
            "title_line": '【草稿】自然语言起草自动发送',
            "lines": ['给 <target> 发消息: 起草草稿，<target>：目标群或联系人，<内容>：正文', '示例: 给小明发消息，内容：今晚一起吃饭吗'],
            "detail": '【草稿】自然语言起草自动发送\n给 <target> 发消息: 起草草稿，<target>：目标群或联系人，<内容>：正文\n示例: 给小明发消息，内容：今晚一起吃饭吗',
        },
        {
            "topic": '搜索',
            "aliases": ('搜索', 'search'),
            "index": '【搜索】验证联网检索：/bot search <问题>',
            "title_line": '【搜索】管理员验证联网检索',
            "lines": ['/bot search: 验证联网检索链路，<question>：必填，问题文本', '示例: /bot search 守岸人是什么游戏的角色'],
            "detail": '【搜索】管理员验证联网检索\n/bot search: 验证联网检索链路，<question>：必填，问题文本\n示例: /bot search 守岸人是什么游戏的角色',
        },
        {
            "topic": '解析',
            "aliases": ('解析', 'parse'),
            "index": '【解析】解析历史：/bot parse [数量]',
            "title_line": '【解析】查看最近解析历史',
            "lines": ['/bot parse: 查看解析历史，<count>：1-100，默认 10'],
            "detail": '【解析】查看最近解析历史\n/bot parse: 查看解析历史，<count>：1-100，默认 10',
        },
        {
            "topic": '凭据',
            "aliases": ('凭据', 'alert', 'cookie'),
            "index": '【凭据】凭据健康检查与 cookie 导入：/bot alert check｜/bot cookie import|status',
            "title_line": '【凭据】检查 cookie/凭据健康',
            "lines": ['/bot alert check: 检查凭据是否过期，--probe：可选，追加在线探测（401/403=需重登）', '/bot cookie import <平台> <Cookie头>: 热写入平台 cookie（同名不覆盖，下一次解析即生效，无需重启），平台：bilibili/xiaohongshu/douyin/qqmusic/netease/kuwo/kugou/twitter/youtube/kurobbs/weibo/kuaishou/acfun/moegirl/xiaoheihe/skland/miyoushe', '/bot cookie status: 查看各平台已录入的 cookie 名与到期日（不显示值）'],
            "detail": '【凭据】检查 cookie/凭据健康\n/bot alert check: 检查凭据是否过期，--probe：可选，追加在线探测（401/403=需重登）\n/bot cookie import <平台> <Cookie头>: 热写入平台 cookie（同名不覆盖，下一次解析即生效，无需重启）\n/bot cookie status: 查看各平台已录入的 cookie 名与到期日（不显示值）',
        },
        {
            "topic": '好感度',
            "admin_only": False,
            "aliases": ('好感度', '好感查看', '查询好感'),
            "index": '【好感度】查看双向好感：好感度｜好感度 我｜好感度 算法',
            "title_line": '【好感度】守岸人与你的双向好感',
            "lines": [
                '好感度: 私聊看双向好感卡；群聊出本群好感榜（有印象的成员，自己高亮），无参数',
                '好感度 我: 只看自己的双向分值，任意场景可用',
                '好感度 算法: 图文说明计算规则与档位回应方式（含你此刻的精确步长）',
                '计分: 初始10分；感谢/夸奖/问候 +2起、玩笑 -1起、抱怨 -5起、辱骂 -10起（每日各有限次）；步长随分数靠近0/100幂律衰减，每人另有±15%个人系数',
                '双向: 守岸人对你=印象好感度（0-100）；你对守岸人=你表达中友好成分的加权占比（估算值）',
                '档位: 亲近 ≥75｜友善 45-74｜客气 25-44｜疏离 <25；只影响语气，任何档位都不辱骂、不弃聊',
                '示例: 好感度｜好感度 我｜好感度 算法',
            ],
            "detail": (
                '【好感度】守岸人与你的双向好感\n'
                '好感度: 私聊看双向好感卡；群聊出本群好感榜（有印象的成员，自己高亮），无参数\n'
                '好感度 我: 只看自己的双向分值，任意场景可用\n'
                '好感度 算法: 图文说明计算规则与档位回应方式（含你此刻的精确步长）\n'
                '计分: 初始10分；感谢/夸奖/问候 +2起、玩笑 -1起、抱怨 -5起、辱骂 -10起（每日各有限次）；步长随分数靠近0/100幂律衰减，每人另有±15%个人系数\n'
                '双向: 守岸人对你=印象好感度（0-100）；你对守岸人=你表达中友好成分的加权占比（估算值）\n'
                '档位: 亲近 ≥75｜友善 45-74｜客气 25-44｜疏离 <25；只影响语气，任何档位都不辱骂、不弃聊\n'
                '示例: 好感度｜好感度 我｜好感度 算法'
            ),
        },
        {
            "topic": '吃什么',
            "admin_only": False,
            "aliases": ('吃什么', '吃啥', '菜谱'),
            "index": '【吃什么】随机推荐家常菜/查菜谱：吃什么 | 吃什么 三选一 | 菜谱 番茄炒蛋',
            "title_line": '【吃什么】解决选择困难',
            "lines": [
                '吃什么: 随机推荐 1 道家常菜（Mica 卡图）',
                '吃什么 三选一: 一次推 3 道不同菜',
                '吃什么 不辣 / 吃什么 辣的: 按辣度过滤',
                '菜谱 <菜名>: 查做法（例：菜谱 番茄炒蛋、怎么做 可乐鸡翅）',
                '带忌口/食材约束（如"不吃香菜 有鸡蛋"）自动走 AI 生成菜谱',
                '菜谱图片：把 <菜名>.jpg 放到 Runtime data/food_images/ 即可上卡',
            ],
            "detail": '【吃什么】解决选择困难\n吃什么: 随机推荐\n吃什么 三选一: 3 道\n菜谱 <菜名>: 查做法',
        },
        {
            "topic": 'Epic',
            "aliases": ('epic', 'epicfree', 'epic free', 'epic 免费', '免费游戏'),
            "index": '【Epic】每周免费游戏：epic 或 Epic 免费',
            "title_line": '【Epic】查询每周免费游戏',
            "lines": ['epic: 查询 Epic 本周免费游戏，无参数'],
            "detail": '【Epic】查询每周免费游戏\nepic: 查询 Epic 本周免费游戏，无参数',
        },
    {
        "topic": "邮件",
        "aliases": ("邮件", "电子邮件", "mail", "email", "邮箱"),
        "index": "【邮件】Gmail/QQ 收发与发件账户控制：/mail status|send|use|pause|resume",
        "title_line": "【邮件】Gmail/QQ IMAP/SMTP 收发与 Telegram 控制",
        "lines": [
            "/mail status: 查看桥接、已连接账户和当前发件账户，无参数",
            "/mail accounts: 列出可用认证账户与发件别名，无参数",
            "/mail use <发件邮箱>: 选择默认发件身份，<发件邮箱>：完整地址且必须已连接或映射",
            "/mail send <收件邮箱> | <主题> | <正文>: 发信；收件邮箱：完整地址，主题：非空，正文：非空",
            "/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>: 临时指定发件身份",
            "/mail pause: 暂停邮件 AI 自动回复，无参数；收件提醒继续",
            "/mail resume: 恢复邮件 AI 自动回复，无参数",
        ],
        "detail": "【邮件】Gmail/QQ IMAP/SMTP 收发与 Telegram 控制\n"
        "/mail status: 查看桥接、已连接账户和当前发件账户，无参数\n"
        "/mail accounts: 列出可用认证账户与发件别名，无参数\n"
        "/mail use <发件邮箱>: 选择默认发件身份，<发件邮箱>：完整地址且必须已连接或映射\n"
        "/mail send <收件邮箱> | <主题> | <正文>: 发信；收件邮箱：完整地址，主题：非空，正文：非空\n"
        "/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>: 临时指定发件身份\n"
        "/mail pause: 暂停邮件 AI 自动回复，无参数；收件提醒继续\n"
        "/mail resume: 恢复邮件 AI 自动回复，无参数",
    },
    {
        "topic": "Telegram",
        "aliases": ("telegram", "tg", "电报", "纸飞机", "飞机"),
        "index": "【Telegram】提醒与远程控制配置：TELEGRAM_BOTS / /bot status",
        "title_line": "【Telegram】新邮件提醒与 Bot 远程控制",
        "lines": [
            "TELEGRAM_BOTS: BotFather Token 列表；格式：JSON 数组，至少 1 个 token 才连接",
            "BOT_TELEGRAM_ADMIN_USER_IDS: 管理员 user id；格式：JSON 字符串数组",
            "BOT_TELEGRAM_ADMIN_CHAT_IDS: 邮件提醒 chat id；格式：JSON 字符串数组",
            "/bot status: 查看运行状态，无参数",
            "/bot pause | /bot resume: 暂停或恢复统一运行时，无参数",
        ],
        "detail": "【Telegram】新邮件提醒与 Bot 远程控制\n"
        "TELEGRAM_BOTS: BotFather Token 列表；格式：JSON 数组，至少 1 个 token 才连接\n"
        "BOT_TELEGRAM_ADMIN_USER_IDS: 管理员 user id；格式：JSON 字符串数组\n"
        "BOT_TELEGRAM_ADMIN_CHAT_IDS: 邮件提醒 chat id；格式：JSON 字符串数组\n"
        "/bot status: 查看运行状态，无参数\n"
        "/bot pause | /bot resume: 暂停或恢复统一运行时，无参数",
    },
    {
        "topic": "供应商",
        "aliases": ("供应商", "provider", "providers", "模型供应商", "包台"),
        "index": "【供应商】模型分组、优先级与健康检查：probe_llm_providers.py",
        "title_line": "【供应商】LLM 分组、路由优先级与健康检查",
        "lines": [
            "BOT_MODEL_REGISTRY: AI API 中转供应商的 JSON 对象；每项包含 model/base_url/api_key/group/priority",
            "priority: 全局尝试顺序，整数 1-999，数字越小越优先；HCN 保底项放最后",
            "BOT_CHAT_FAST_MAX_CANDIDATES: 快速模式候选上限，0=不限制候选数量，1-100=最多尝试数量",
            "scripts/probe_llm_providers.py: 每模型一次脱敏探测；--max-tokens：1-4096，默认 32，不删除配置",
        ],
        "detail": "【供应商】LLM 分组、路由优先级与健康检查\n"
        "BOT_MODEL_REGISTRY: AI API 中转供应商的 JSON 对象；每项包含 model/base_url/api_key/group/priority\n"
        "priority: 全局尝试顺序，整数 1-999，数字越小越优先；HCN 保底项放最后\n"
        "BOT_CHAT_FAST_MAX_CANDIDATES: 快速模式候选上限，0=不限制候选数量，1-100=最多尝试数量\n"
        "scripts/probe_llm_providers.py: 每模型一次脱敏探测；--max-tokens：1-4096，默认 32，不删除配置",
    },
]

# Keep text help and rendered help cards on the same operational instructions.
for _entry in _HELP_ENTRIES:
    _extra: list[str] = []
    if _entry["topic"] == "回复":
        _extra = [
            "/bot reply 详细：先说明结论、身份、关系、关键经历和资料缺口，不强制凑字数。",
            "/bot runtime set BOT_CHAT_MAX_TOKENS 8192：输出上限，不是必须生成的长度。",
            "/bot runtime set BOT_CHAT_FAST_MODE false：知识验收阶段关闭快速模式。",
            "BOT_CHAT_MAX_TOKENS=65538 是最大上限，不是每次强制生成 64K。",
            "文件生成：明确说“生成/保存/导出文件”，机器人会先写文件，再走上传接口。",
            "戳一戳：默认响应有冷却；BOT_POKE_ENABLED、BOT_POKE_*_COOLDOWN_SECONDS、BOT_POKE_PROBABILITY 可调。",
            "/bot runtime set BOT_CHAT_FAST_MAX_TOKENS 8192：重新启用快速模式时的输出上限。",
            "运行时覆盖优先于 .env；用 runtime get 查看实际设置。",
        ]
    elif _entry["topic"] == "设置":
        _extra = [
            "/bot runtime get BOT_REPLY_DETAIL：查看实际详略模式及覆盖来源。",
            "/bot runtime set BOT_MEMORY_EXTRACT_ENABLED false：暂停自动抽取，不删除已有记忆。",
            "/bot runtime set BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS 15：抽取总预算（秒）。",
            "/bot runtime set BOT_MEMORY_EXTRACT_MAX_TOKENS 200：抽取输出上限（1..4096）。",
            "/bot runtime set BOT_MEMORY_EXTRACT_ERROR_COOLDOWN_SECONDS 300：抽取失败后冷却。",
            "记忆抽取复用聊天路由配置，采用独立调用状态；不使用另一枚基础 key 绕开模型注册表。",
        ]
    elif _entry["topic"] == "模型":
        _extra = [
            "priority 是 1..N 唯一槽位：移动一个模型，其他模型自动顺移；0 兼容为移到首位。",
            "手动指定 > 时段组 order > 基础 priority。时段组启用时基础排序不覆盖组内顺序。",
            "model list 显示候选配置，不等于上一条实际回答的供应商；/bot llm 会产生新的诊断调用。",
            "不要在群聊发送真实 Key；使用 key=env:变量名，在本地安全配置凭据。",
        ]
    if _extra:
        _entry["lines"] = [*_entry.get("lines", []), *_extra]
        _entry["detail"] = _entry.get("detail", "") + "\n" + "\n".join(_extra)

_HELP_ALIAS_MAP = {
    alias.lower(): entry["topic"]
    for entry in _HELP_ENTRIES
    for alias in entry["aliases"]
}

HELP_ENTRIES = _HELP_ENTRIES


def _split_command_row(row: str) -> tuple[str, str]:
    """把帮助行拆成「命令段 + 说明段」：在首个「：」或「: 」处切分。"""
    for sep in ("：", ": "):
        idx = row.find(sep)
        if 0 < idx < len(row) - len(sep):
            head = row[: idx + len(sep)]
            tail = row[idx + len(sep):]
            return head, tail
    return row, ""


def _resolve_help_accent(accent_color: str) -> tuple[str, str]:
    """把配置主色归一成 (accent, accent_ink)；非法/留空回退中性灰。"""
    from plugins.bot_unified_runtime.output.card_render.bridge import (
        _darken,
        _hex_to_rgb,
        _rgb_to_hex,
    )

    rgb = _hex_to_rgb(accent_color or "")
    return _rgb_to_hex(rgb), _rgb_to_hex(_darken(rgb))


def _help_index_sections(is_admin: bool) -> list[tuple[str, list[tuple[str, str]]]]:
    """结构化索引：分类 → (药丸标签, 说明)。供帮助卡网格布局消费。"""
    visible = {str(entry["topic"]): entry for entry in _visible_help_entries(is_admin)}
    hint_re = re.compile(r"｜详情：/bot help .*?$")
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    for category, topics in _HELP_CATEGORIES:
        rows: list[tuple[str, str]] = []
        for topic in topics:
            entry = visible.get(topic)
            if entry is None:
                continue
            desc = hint_re.sub("", re.sub(r"^【[^】]+】", "", str(entry["index"])).strip())
            desc = desc.strip("；;｜| ").strip()
            rows.append((str(entry["aliases"][0]) if entry["aliases"] else topic, desc or topic))
        if rows:
            sections.append((category, rows))
    categorized = {topic for _, topics in _HELP_CATEGORIES for topic in topics}
    orphans = [entry for topic, entry in visible.items() if topic not in categorized]
    if orphans:
        sections.append(("更多", [
            (
                str(entry["aliases"][0]) if entry["aliases"] else str(entry["topic"]),
                hint_re.sub("", re.sub(r"^【[^】]+】", "", str(entry["index"])).strip()).strip("；;｜| ").strip(),
            )
            for entry in orphans
        ]))
    return sections


def _help_mica_html(
    body: str,
    *,
    is_admin: bool,
    bot_name: str = "守岸人",
    bot_avatar_url: str = "",
    accent_color: str = "",
    sections: list[tuple[str, list[tuple[str, str]]]] | None = None,
) -> str:
    """Render a one-page categorized Mica help card with transparent outer space.

    ``sections`` 提供结构化索引（总览页 → 两列网格 + 命令药丸）；缺省时
    按正文解析（模块详情页：首行作卡题，其余行拆「命令段 + 说明段」）。
    """
    accent, accent_ink = _resolve_help_accent(accent_color)
    detail_title = ""
    if sections is None:
        sections = []
        current_title = "功能"
        current_rows: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line or line.endswith("总览"):
                continue
            if line.startswith("【") and line.endswith("】"):
                if current_rows:
                    sections.append((current_title, [_split_command_row(r) for r in current_rows]))
                current_title, current_rows = line[1:-1], []
                continue
            if detail_title:
                current_rows.append(line)
            else:
                detail_title = line.rstrip("：:")
                current_title = detail_title
        if current_rows:
            sections.append((current_title or "用法", [_split_command_row(r) for r in current_rows]))
        if sections and not detail_title:
            detail_title = sections[0][0]

    def _esc(value: str) -> str:
        return html.escape(value)

    def _rows_html(rows: list[tuple[str, str]]) -> str:
        return "".join(
            "<div class=\"command-row\">"
            + (f"<span class=\"pill\">{_esc(cmd.rstrip('：:'))}</span>" if cmd else "")
            + (f"<span class=\"desc\">{_esc(desc)}</span>" if desc else "")
            + "</div>"
            for cmd, desc in rows
        )

    if detail_title:
        # 模块详情/分类说明书：单列卡，首段为主卡。
        cards = "".join(
            "<section class=\"help-section" + (" main" if index == 0 else "") + "\">"
            f"<h2><span class=\"dot\"></span>{_esc(title)}</h2>"
            f"<div class=\"command-list\">{_rows_html(rows)}</div></section>"
            for index, (title, rows) in enumerate(sections)
        )
        grid_cls = "single"
        header_title = f"{bot_name} · {detail_title}"
        header_sub = "参数标注：<> 必填、[] 可选；把命令复制到聊天即可使用，具体取值见各行说明。"
    else:
        cards = "".join(
            "<section class=\"help-section" + (" wide" if len(rows) >= 40 else "") + "\">"
            f"<h2><span class=\"dot\"></span>{_esc(title)}</h2>"
            f"<div class=\"command-list\">{_rows_html(rows)}</div></section>"
            for title, rows in sections
        )
        grid_cls = "masonry"
        header_title = f"{bot_name} · 命令手册"
        header_sub = "按模块分类汇总；回复「/bot help 模块名」展开该模块的子命令、参数与示例（如 /bot help 点歌、/bot help 订阅）。"
    role = "管理员帮助" if is_admin else "公开帮助"
    avatar = (
        f'<img class="help-bot-avatar" src="{html.escape(bot_avatar_url)}" alt="" />'
        if bot_avatar_url else ""
    )
    avatar_block = avatar or f"<span class=\"avatar-fallback\">{_esc((bot_name or '守')[:1])}</span>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
:root {{ --accent:{accent}; --accent-ink:{accent_ink}; --ink:#27232a; --muted:#6f646c; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:0; font-family:"Segoe UI","Microsoft YaHei",sans-serif; background:transparent; color:var(--ink); -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }}
.help-stage {{ width:auto; padding:26px; background:transparent; }}
.help-shell {{ width:940px; overflow:hidden; border-radius:24px; border:1px solid rgba(255,255,255,.92); background:linear-gradient(168deg, color-mix(in srgb, var(--accent) 3%, #fff) 0%, color-mix(in srgb, var(--accent) 7%, #fff) 100%); box-shadow:0 14px 34px rgba(31,35,41,.10); }}
.help-head {{ display:flex; align-items:center; gap:14px; padding:22px 26px 18px; border-bottom:1px solid color-mix(in srgb, var(--accent) 14%, #fff); }}
.avatar-wrap {{ flex:0 0 auto; width:52px; height:52px; border-radius:16px; overflow:hidden; background:color-mix(in srgb, var(--accent) 14%, #fff); display:flex; align-items:center; justify-content:center; box-shadow:inset 0 0 0 1px rgba(255,255,255,.9); }}
.avatar-wrap img {{ width:100%; height:100%; object-fit:cover; }}
.avatar-fallback {{ font-size:24px; font-weight:700; color:var(--accent-ink); }}
.head-main {{ flex:1 1 auto; min-width:0; }}
.help-kicker {{ color:var(--accent-ink); font-size:11px; font-weight:700; letter-spacing:.14em; }}
.help-title {{ margin-top:6px; font-size:27px; font-weight:700; letter-spacing:.01em; }}
.help-subtitle {{ margin-top:6px; color:var(--muted); font-size:12.5px; line-height:1.55; }}
.help-chip {{ flex:0 0 auto; padding:7px 14px; border-radius:999px; color:var(--accent-ink); background:color-mix(in srgb, var(--accent) 6%, #fff); border:1px solid color-mix(in srgb, var(--accent) 20%, #fff); font-size:12px; font-weight:650; }}
.help-body {{ padding:14px; background:color-mix(in srgb, var(--accent) 3%, #fff); }}
.help-grid.masonry {{ column-count:2; column-gap:12px; }}
.help-grid.masonry .help-section {{ break-inside:avoid; margin-bottom:12px; }}
.help-grid.masonry .help-section.wide {{ column-span:all; }}
.help-grid.single {{ display:grid; grid-template-columns:1fr; gap:12px; }}
.help-section {{ border-radius:16px; overflow:hidden; border:1px solid rgba(255,255,255,.95); background:linear-gradient(150deg, color-mix(in srgb, var(--accent) 2%, #fff), color-mix(in srgb, var(--accent) 5%, #fff)); box-shadow:0 3px 10px rgba(31,35,41,.05); }}
.help-section h2 {{ display:flex; align-items:center; gap:8px; margin:0; padding:10px 14px; color:var(--accent-ink); background:linear-gradient(135deg, color-mix(in srgb, var(--accent) 7%, #fff), color-mix(in srgb, var(--accent) 12%, #fff)); border-left:4px solid var(--accent); font-size:14.5px; font-weight:700; letter-spacing:.02em; }}
.help-section h2 .dot {{ flex:0 0 auto; width:7px; height:7px; border-radius:50%; background:var(--accent); box-shadow:0 0 0 3px color-mix(in srgb, var(--accent) 18%, #fff); }}
.command-list {{ padding:9px; display:grid; gap:6px; }}
.command-row {{ display:flex; align-items:flex-start; gap:9px; padding:7px 10px; border-radius:11px; background:rgba(255,255,255,.72); font-size:12px; line-height:1.55; }}
.command-row .pill {{ flex:0 0 auto; max-width:62%; padding:2px 10px; border-radius:999px; color:var(--accent-ink); background:color-mix(in srgb, var(--accent) 13%, #fff); font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.command-row .desc {{ color:var(--muted); min-width:0; overflow-wrap:anywhere; }}
.help-foot {{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding:10px 16px; background:color-mix(in srgb, var(--accent) 9%, #fff); border-top:1px solid color-mix(in srgb, var(--accent) 15%, #fff); }}
.help-foot .tip {{ color:var(--muted); font-size:11.5px; }}
.help-bot-pill {{ display:flex; align-items:center; gap:8px; padding:5px 13px 5px 6px; border-radius:999px; color:var(--accent-ink); background:color-mix(in srgb, var(--accent) 4%, #fff); border:1px solid #fff; box-shadow:0 4px 10px rgba(31,35,41,.07); font-size:13px; font-weight:600; }}
.help-bot-avatar {{ width:27px; height:27px; object-fit:cover; border-radius:50%; }}
</style></head><body><div class="help-stage card"><section class="help-shell"><header class="help-head"><div class="avatar-wrap">{avatar_block}</div><div class="head-main"><div class="help-kicker">{_esc(role)}</div><div class="help-title">{_esc(header_title)}</div><div class="help-subtitle">{_esc(header_sub)}</div></div><div class="help-chip">发 /bot help 获取本图</div></header><main class="help-body"><div class="help-grid {grid_cls}">{cards}</div></main><footer class="help-foot"><span class="tip">参数标注：&lt;&gt; 必填，[] 可选；群里直接发命令即可触发。</span><div class="help-bot-pill">{avatar}<span>{_esc(bot_name)} · 命令手册</span></div></footer></section></div></body></html>"""


def _help_category_body(query: str, *, is_admin: bool) -> str | None:
    """分类名（如「大模型」「子功能」「管理员」）→ 该分类的说明书页。

    命中分类时返回首行为标题、每个模块一节的完整命令正文；未命中返回 None。
    """
    q = query.strip().lower()
    if not q:
        return None
    for name, topics in _HELP_CATEGORIES:
        n = name.lower()
        if q == n or n.startswith(q) or q in n:
            entries = [
                entry
                for entry in _visible_help_entries(is_admin)
                if entry["topic"] in topics
            ]
            if not entries:
                return None
            lines = [f"{name} · 命令手册"]
            for entry in entries:
                lines.append(f"【{entry['topic']}】")
                lines.extend(str(line) for line in entry["lines"])
            return "\n".join(lines)
    return None


def _try_render_help_image(
    body: str,
    *,
    render_backend: Any | None,
    card_dir: str,
    request_id: str,
    is_admin: bool,
    bot_name: str,
    bot_avatar_url: str = "",
    accent_color: str = "",
    sections: list[tuple[str, list[tuple[str, str]]]] | None = None,
) -> str:
    if render_backend is None or not getattr(render_backend, "available", False):
        return ""
    try:
        png = render_backend.render_card(
            {
                "html": _help_mica_html(
                    body,
                    is_admin=is_admin,
                    bot_name=bot_name,
                    bot_avatar_url=bot_avatar_url,
                    accent_color=accent_color,
                    sections=sections,
                ),
                "viewport": {"width": 1040, "height": 1200},
                "device_scale_factor": 2,
                "wait_ms": 0,
            }
        )
        if not isinstance(png, bytes) or not png:
            return ""
        target = Path(card_dir or "data/cards")
        target.mkdir(parents=True, exist_ok=True)
        # 摘要只按内容（admin/正文），同内容复用同一文件——request_id 参与摘要
        # 会让每次请求都生成新文件，data/cards 无界增长（audit #13）。
        digest = hashlib.sha1(f"{is_admin}:{body}".encode()).hexdigest()[:12]
        path = target / f"help_{digest}.png"
        path.write_bytes(png)
        try:
            from plugins.bot_unified_runtime.runtime.cache_policy import prune_prefixed

            prune_prefixed(target, "help", keep=200)
        except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响本次出图。
            pass
        return str(path)
    except Exception:  # noqa: BLE001 - 图片帮助失败时保留纯文本帮助。
        return ""


def build_help_result(
    request_id: str | None = None,
    query: str = "",
    is_admin: bool = False,
    *,
    render_backend: Any | None = None,
    card_dir: str = "data/cards",
    bot_name: str = "守岸人",
    bot_avatar_url: str = "",
    accent_color: str = "",
) -> CapabilityResult:
    cleaned = parse_help_command_text(query)
    topic = normalize_help_topic(cleaned)
    page = 1 if cleaned in {"1", "2"} else None
    is_index = not cleaned or page is not None
    if is_index:
        body = _help_index_body(page=page or 1, is_admin=is_admin)
    elif topic is None:
        body = _help_category_body(cleaned, is_admin=is_admin) or _help_unknown_body(cleaned)
    else:
        entry = next(item for item in _HELP_ENTRIES if item["topic"] == topic)
        if not is_admin and entry["topic"] not in _PUBLIC_HELP_TOPICS:
            body = _help_unknown_body(cleaned)
        else:
            body = entry["title_line"] + "\n" + "\n".join(entry["lines"])
    actual_request_id = request_id or new_request_id("help")
    image_path = _try_render_help_image(
        body,
        render_backend=render_backend,
        card_dir=card_dir,
        request_id=actual_request_id,
        is_admin=is_admin,
        bot_name=bot_name,
        bot_avatar_url=bot_avatar_url,
        accent_color=accent_color,
        sections=_help_index_sections(is_admin) if is_index else None,
    )
    if image_path:
        return CapabilityResult(
            request_id=actual_request_id,
            capability_id="bot.help",
            kind="image",
            title="",
            body="",
            images=[{"type": "image", "file": image_path}],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=["help", "help_image", "help_page:1"],
        )
    return CapabilityResult(
        request_id=actual_request_id,
        capability_id="bot.help",
        kind="text",
        title="帮助",
        body=body,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
    )


def route_bot_command(
    command_text: str,
    request_id: str | None = None,
    config: Config | None = None,
    runtime_control: RuntimeControlState | None = None,
    actor_roles: list[str] | None = None,
) -> CapabilityResult:
    if command_text.strip() == "status":
        return build_status_result(
            config=config,
            request_id=request_id,
            runtime_control=runtime_control,
            actor_roles=actor_roles,
        )
    return build_help_result(request_id=request_id)


def _build_status_body(config: Config, runtime_control: RuntimeControlState) -> str:
    persona_total, persona_missing = _count_missing_paths(config.bot_persona_files)
    knowledge_total, knowledge_missing = _count_missing_paths(config.bot_knowledge_files)
    runtime_hard_state = "enabled" if config.bot_runtime_enabled else "disabled"
    runtime_soft_paused = str(runtime_control.paused).lower()
    memory_state = "enabled" if config.bot_memory_enabled else "disabled"
    memory_db_state = "set" if config.bot_memory_db_path else "missing"
    history_state = "enabled" if config.bot_history_enabled else "disabled"
    history_db_state = "set" if config.bot_history_db_path else "missing"
    diagnostics_state = "enabled" if config.bot_diagnostics_enabled else "disabled"
    diagnostics_db_state = "set" if config.bot_diagnostics_db_path else "missing"
    audit_state = "enabled" if config.bot_audit_enabled else "disabled"
    audit_store = "sqlite" if config.bot_audit_enabled and config.bot_audit_db_path else "memory"
    audit_db_state = "set" if config.bot_audit_db_path else "missing"
    receipts_state = "enabled" if config.bot_receipts_enabled else "disabled"
    receipts_store = (
        "sqlite" if config.bot_receipts_enabled and config.bot_receipts_db_path else "memory"
    )
    receipts_db_state = "set" if config.bot_receipts_db_path else "missing"
    send_queue_state = "enabled" if config.bot_send_queue_enabled else "disabled"
    send_queue_store = (
        "sqlite"
        if config.bot_send_queue_enabled and config.bot_send_queue_db_path
        else "memory"
    )
    send_queue_db_state = "set" if config.bot_send_queue_db_path else "missing"
    send_queue_worker_state = (
        "enabled" if config.bot_send_queue_worker_enabled else "disabled"
    )
    emotion_state = "enabled" if config.bot_emotion_enabled else "disabled"
    rate_limit_state = "enabled" if config.bot_rate_limit_enabled else "disabled"
    rate_limit_store = "sqlite" if config.bot_rate_limit_db_path else "memory"
    rate_limit_db_state = "set" if config.bot_rate_limit_db_path else "missing"
    rate_limit_bypass = ",".join(config.bot_rate_limit_bypass_roles) or "-"
    quiet_hours_state = "enabled" if config.bot_quiet_hours_enabled else "disabled"
    quiet_hours_sessions = ",".join(config.bot_quiet_hours_session_types) or "-"
    quiet_hours_bypass = ",".join(config.bot_quiet_hours_bypass_roles) or "-"
    chat_state = "enabled" if config.bot_chat_enabled else "disabled"
    api_key_state = "set" if config.bot_chat_api_key else "missing"
    role_counts = build_role_settings(config).counts()
    llm_readiness = run_config_smoke(config)
    llm_reasons = _format_reason_list(llm_readiness["llm_readiness_reasons"])
    return "\n".join(
        [
            "统一运行时在线",
            f"运行时硬开关：{runtime_hard_state}",
            (
                f"运行时软暂停：{runtime_soft_paused}，"
                f"reason={runtime_control.reason}，"
                f"updated_by={runtime_control.updated_by_state}"
            ),
            (
                "权限角色："
                f"admins={role_counts['admin']}，"
                f"enterprise={role_counts['enterprise']}，"
                f"trusted={role_counts['trusted']}，"
                f"blocked={role_counts['blocked']}"
            ),
            f"人格：{config.bot_persona_profile_id} / {config.bot_persona_display_name}",
            f"人格版本：{config.bot_persona_version}",
            f"人格文件：{persona_total} 个，缺失 {persona_missing} 个",
            f"知识文件：{knowledge_total} 个，缺失 {knowledge_missing} 个",
            f"记忆：{memory_state}，db={memory_db_state}",
            (
                f"最近对话：{history_state}，db={history_db_state}，"
                f"max_turns={config.bot_history_max_turns}，"
                f"max_items={config.bot_history_max_items}"
            ),
            (
                f"运行诊断：{diagnostics_state}，db={diagnostics_db_state}，"
                f"max_items={config.bot_diagnostics_max_items}"
            ),
            (
                f"审计：{audit_state}，store={audit_store}，"
                f"db={audit_db_state}，max_items={config.bot_audit_max_items}"
            ),
            (
                f"发送回执：{receipts_state}，store={receipts_store}，"
                f"db={receipts_db_state}，max_items={config.bot_receipts_max_items}"
            ),
            (
                f"发送队列：{send_queue_state}，store={send_queue_store}，"
                f"db={send_queue_db_state}，"
                f"max_items={config.bot_send_queue_max_items}，"
                f"max_attempts={config.bot_send_queue_max_attempts}，"
                f"retry={config.bot_send_queue_retry_base_seconds}-"
                f"{config.bot_send_queue_retry_max_seconds}s，"
                f"worker={send_queue_worker_state}，"
                f"interval={config.bot_send_queue_worker_interval_seconds}s，"
                f"batch={config.bot_send_queue_worker_batch_size}"
            ),
            f"情绪感知：{emotion_state}，max_signals={config.bot_emotion_max_signals}",
            (
                "回复限速："
                f"{rate_limit_state}，"
                f"store={rate_limit_store}，"
                f"db={rate_limit_db_state}，"
                f"window={config.bot_rate_limit_window_seconds}s，"
                f"global={config.bot_rate_limit_chat_global_max_requests}，"
                f"session={config.bot_rate_limit_chat_session_max_requests}，"
                f"sender={config.bot_rate_limit_chat_sender_max_requests}，"
                f"target_min_interval={config.bot_rate_limit_target_min_interval_seconds}s，"
                f"bypass={rate_limit_bypass}"
            ),
            (
                "安静时间："
                f"{quiet_hours_state}，"
                f"{config.bot_quiet_hours_start}-{config.bot_quiet_hours_end}，"
                f"tz={config.bot_quiet_hours_timezone}，"
                f"sessions={quiet_hours_sessions}，"
                f"bypass={quiet_hours_bypass}"
            ),
            (
                f"LLM：{config.bot_chat_provider}，model={config.bot_chat_model}，"
                f"api_key={api_key_state}，chat={chat_state}"
            ),
            (
                f"LLM就绪：{llm_readiness['llm_readiness_status']}，"
                f"ready_for_real_llm={str(bool(llm_readiness['ready_for_real_llm'])).lower()}"
            ),
            f"LLM下一步：{llm_readiness['llm_next_action']}",
            f"LLM原因：{llm_reasons}",
        ]
    )


def _count_missing_paths(paths: list[str]) -> tuple[int, int]:
    total = len(paths)
    missing = sum(1 for path in paths if not Path(path).expanduser().is_file())
    return total, missing


def _format_reason_list(value: object) -> str:
    if not isinstance(value, list):
        return "-"
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return ",".join(cleaned) if cleaned else "-"

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
    # /bot commands：命令目录（机器可读），与 help 总览分开，不渲染卡片。
    if lowered in _COMMANDS_CATALOG_QUERY:
        return "commands"
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
# history and administration remain available to administrators.
_PUBLIC_HELP_TOPICS = frozenset(
    {
        "订阅", "点歌", "表情", "天气", "行情", "占卜", "快报", "维基", "萌娘百科",
        "历史上的今天", "下载", "昵称", "链接", "Epic", "好感度", "吃什么", "偷表情",
        "随机图", "提醒", "搜图", "记忆", "路由", "草稿",
    }
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
            "状态", "为什么", "回执", "审计", "最近", "日志", "解析", "上下文",
            "对话", "历史", "人格", "角色", "队列", "配置", "就绪", "接入",
            "暂停", "回复", "设置", "凭据", "群策略", "群文件", "文件",
            "身份", "怪癖", "限流", "合并转发", "群摘要", "视频理解", "运行开关",
            "邮件", "Telegram", "供应商",
        },
    ),
    ("大模型相关", {"模型", "用量", "搜索"}),
    (
        "子功能",
        {
            "订阅", "点歌", "表情", "偷表情", "搜图", "Epic", "历史上的今天",
            "天气", "行情", "占卜", "快报", "维基", "萌娘百科", "下载",
            "昵称", "链接", "吃什么", "好感度", "随机图", "提醒", "记忆", "路由",
            "草稿",
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
            "lines": [
                '/bot status：作用=查看运行状态摘要；参数=无；内容=软暂停状态/原因、角色计数、人格与知识文件缺失数、记忆/历史/诊断/审计/回执/队列的开关与存储（sqlite/memory）、限速与安静时间、LLM provider/model/key 状态与就绪下一步；意义=排障第一入口，出问题先看状态再 /bot why。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  一条命令看清机器人此刻的整体姿态：运行时开关、软暂停、权限角色数量、\n'
                '  人格/知识/记忆等文件的在位情况、各持久化存储落在 sqlite 还是内存、\n'
                '  LLM 供应商与密钥是否就绪。所有信息脱敏输出，不显示密钥与会话原文。\n'
                '【指令与参数】\n'
                '/bot status：作用=查看运行状态摘要；参数=无；内容=多行状态清单（详见下方效果）；意义=排障第一入口，先看状态再 /bot why 追原因。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（普通成员发送会收到拒绝提示）。\n'
                '  内容逐段对应：运行时硬开关/软暂停与原因→权限角色计数（admin/enterprise/trusted/blocked）→\n'
                '  人格档案与人格文件缺失数→知识文件缺失数→记忆/最近对话/诊断/审计/回执/发送队列的\n'
                '  enabled 与 db 状态→情绪感知→回复限速（窗口/各层上限/绕过角色）→安静时间→LLM 配置与就绪原因。\n'
                '【示例】/bot status'
            ),
        },
        {
            "topic": '记忆',
            "admin_only": False,
            "aliases": ('记忆', 'memory'),
            "index": '【记忆】管理我的长期记忆：/bot memory add|list|delete',
            "title_line": '【记忆】管理我交给机器人的长期记忆',
            "lines": [
                '/bot memory add <内容>：作用=记住一句话；参数=内容（必填，建议 ≤1200 字）＋--sensitivity=（可选，personal|group|public|credentialed，默认 personal）；内容=回显已记住的正文与 fact_id、sensitivity；意义=让机器人长期记住你的偏好与事实。',
                '/bot memory list：作用=列出我的记忆；参数=无；内容=fact_id＋sensitivity＋正文的清单（私聊=全部个人记忆，群聊=仅 public/group 两级）；意义=核对机器人到底记住了什么。',
                '/bot memory delete <fact_id>：作用=删除一条记忆；参数=fact_id（必填，来自 add/list 输出）；内容=成功回显已删除，找不到会明说；意义=撤回不想被记住的内容。',
                '权限=全员（只增删查“你本人”的记忆，别人的看不到也删不掉）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  长期记忆是你主动交给机器人的事实卡片（区别于自动抽取的印象）。\n'
                '  每条记忆归属“写入它的那个人＋所在会话”，互相隔离。\n'
                '【指令与参数】\n'
                '/bot memory add <内容>：作用=新增记忆；参数=内容（必填，任意文本，建议 ≤1200 字）；--sensitivity=（可选开关，取值 personal|group|public|credentialed，默认 personal）；内容=回显正文、fact_id（形如 fact_xxxxxxxxxxxx）与 sensitivity；意义=把“我对芒果过敏”这类事实固定下来，之后对话会被参考。\n'
                '/bot memory list：作用=列出记忆；参数=无；内容=fact_id（sensitivity=…）：正文 逐行清单；意义=盘点与拿 fact_id。群聊里只显示 public/group 两级，防止个人私事被围观；私聊显示全部。\n'
                '/bot memory delete <fact_id>：作用=删除记忆；参数=fact_id（必填，从 add/list 输出复制）；内容=已删除 或 未找到；意义=被遗忘权，删掉不想被记住的内容。\n'
                '【取值范围】\n'
                '  sensitivity 四级：personal（仅自己）/ group（本群可见）/ public（可公开）/ credentialed（敏感凭据类，谨慎使用）。\n'
                '【权限与效果】\n'
                '  权限=全员，无需管理员；只能操作自己作为主体的记忆。\n'
                '  前置条件：BOT_MEMORY_ENABLED=true 且 BOT_MEMORY_DB_PATH 已配置，否则提示先配置。\n'
                '【示例】/bot memory add 我对芒果过敏 --sensitivity=group → /bot memory list → /bot memory delete fact_xxxxxxxxxxxx'
            ),
        },
        {
            "topic": '为什么',
            "admin_only": True,
            "aliases": ('为什么', '为啥', 'why'),
            "index": '【为什么】解释最近决策：/bot why [id]',
            "title_line": '【为什么】解释最近一次回复的决策与错误',
            "lines": [
                '/bot why [id]：作用=解释一次回复的路由/策略/错误；参数=id（可选，request_id 或 debug_id，省略=最近一次）；内容=该请求的路由判定、策略命中、失败类型与线索；意义=回答“它刚才为什么这么回/为什么没回”。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  决策解释器：把某次请求“走了哪条路由、命中什么策略、在哪一步失败”\n'
                '  翻译成人话。诊断链路的第二步（第一步是 /bot status）。\n'
                '【指令与参数】\n'
                '/bot why：作用=解释最近一次回复；参数=无；内容=最近一次请求的决策解释；意义=最快的“刚才怎么回事”。\n'
                '/bot why <id>：作用=解释指定请求；参数=id（可选填，request_id 或 debug_id，来自回执/审计输出）；内容=该请求的决策解释；意义=追溯历史某一条。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。没有可解释的记录时会提示先和机器人说一句话。\n'
                '【示例】/bot why｜/bot why help_8f2a1b3c'
            ),
        },
        {
            "topic": '回执',
            "admin_only": True,
            "aliases": ('回执', 'receipt'),
            "index": '【回执】查询发送回执：/bot receipt <request_id|debug_id>',
            "title_line": '【回执】查询发送回执',
            "lines": [
                '/bot receipt <id>：作用=查询一条消息的发送回执；参数=id（必填，request_id 或 debug_id）；内容=该消息的投递状态（待发/已发/失败）与时间线；意义=确认“我发的命令机器人到底发出去没有”。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  发送回执记录每条出站消息的投递过程。BOT_RECEIPTS_ENABLED=true 时\n'
                '  落库可跨重启查询，默认内存态（重启即清）。\n'
                '【指令与参数】\n'
                '/bot receipt <id>：作用=查询发送回执；参数=id（必填，request_id 或 debug_id，可从 /bot recent 输出拿）；内容=回执状态与关键时间点；意义=区分“没生成”和“生成了但没发出去”。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。查不到时回显脱敏后的 id。\n'
                '【示例】/bot receipt 7c9f…（用 /bot recent 里出现的 id）'
            ),
        },
        {
            "topic": '审计',
            "admin_only": True,
            "aliases": ('审计', 'audit'),
            "index": '【审计】查询审计记录：/bot audit <request_id>',
            "title_line": '【审计】查询审计记录',
            "lines": [
                '/bot audit <request_id>：作用=查询一次请求的审计事件；参数=request_id（必填，请求编号）；内容=该请求全链路的审计事件列表（脱敏）；意义=合规排查与事后追因。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  审计记录由 BOT_AUDIT_ENABLED=true 时落库（默认内存态）。\n'
                '  每个请求的关键节点（入站/路由/出站/异常）都会留事件。\n'
                '【指令与参数】\n'
                '/bot audit <request_id>：作用=查询审计记录；参数=request_id（必填，请求编号）；内容=按时间排序的事件列表（stage/event/severity，敏感字段脱敏）；意义=事后追因与合规留痕的官方入口。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。未找到时回显脱敏后的编号。\n'
                '【示例】/bot audit music_9a3bb2'
            ),
        },
        {
            "topic": '最近',
            "admin_only": True,
            "aliases": ('最近', 'recent'),
            "index": '【最近】最近诊断摘要：/bot recent [数量]',
            "title_line": '【最近】查看最近排障摘要',
            "lines": [
                '/bot recent [数量]：作用=汇总最近诊断＋回执＋审计；参数=数量（可选，1-20 整数，默认 5）；内容=三个板块的最近记录摘要；意义=不用分别调三个查询，一屏看完最近发生了什么。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  /bot recent ＝ 诊断（diagnostics）＋发送回执（receipts）＋审计（audits）\n'
                '  三个查询的合并视图，按各自动态截取最近 N 条。\n'
                '【指令与参数】\n'
                '/bot recent：作用=看最近排障摘要；参数=无；内容=默认各 5 条的合并摘要；意义=快速扫一眼。\n'
                '/bot recent <数量>：作用=控制条数；参数=数量（可选，1-20 整数，默认 5，越界自动收敛到边界）；内容=对应条数的摘要；意义=想多看几条时用。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。输出里的 id 可直接喂给 /bot why、/bot receipt、/bot audit。\n'
                '【示例】/bot recent 10'
            ),
        },
        {
            "topic": '队列',
            "admin_only": True,
            "aliases": ('队列', 'queue'),
            "index": '【队列】发送队列状态：/bot queue',
            "title_line": '【队列】查看发送队列状态',
            "lines": [
                '/bot queue：作用=查看发送队列健康；参数=无；内容=待发/处理中/重试/失败计数与队列参数；意义=消息发不出去时判断是队列堆积还是投递失败。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  所有出站消息统一经发送队列收口。BOT_SEND_QUEUE_ENABLED=true 时\n'
                '  队列持久化到 sqlite，重启不丢。\n'
                '【指令与参数】\n'
                '/bot queue：作用=查看队列状态；参数=无；内容=各状态计数与 max_items/max_attempts/retry 等参数；意义=判断发送瓶颈位置。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。\n'
                '【示例】/bot queue'
            ),
        },
        {
            "topic": '上下文',
            "admin_only": True,
            "aliases": ('上下文', 'context'),
            "index": '【上下文】测试上下文：/bot context [测试文本]',
            "title_line": '【上下文】测试注入给模型的上下文',
            "lines": [
                '/bot context [文本]：作用=看一段话会被注入什么上下文；参数=文本（可选，省略用「你好，守岸人。」）；内容=人格/知识/记忆/最近对话的注入摘要与预算（只出数字摘要不泄露原文）；意义=验证人格与知识装配是否生效，不动线上状态。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  把“如果现在说这句话，模型会看到什么”完整走一遍：注入检查→回复预算→\n'
                '  人格+向量知识+记忆+最近对话装配→prompt 构造，全程只读。\n'
                '【指令与参数】\n'
                '/bot context：作用=用默认文本做上下文诊断；参数=无；内容=注入摘要与预算；意义=开箱自检。\n'
                '/bot context <文本>：作用=用指定文本诊断；参数=文本（可选，任意内容，会先过注入检查）；内容=同上，按你的文本装配；意义=复现特定说法下的上下文。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。输出为数字摘要（条数/字数/预算），不回显知识库原文。\n'
                '  失败时只报错误类型，不泄露堆栈。\n'
                '【示例】/bot context 鸣潮的守岸人是谁'
            ),
        },
        {
            "topic": '对话',
            "admin_only": True,
            "aliases": ('对话', 'dialogue', '对话测试'),
            "index": '【对话】对话诊断：/bot dialogue [测试文本]',
            "title_line": '【对话】本地跑一轮对话诊断',
            "lines": [
                '/bot dialogue [文本]：作用=完整跑一轮对话链路验收；参数=文本（可选，省略用「你好，守岸人。」）；内容=对话各阶段结果（配置/上下文/LLM 调用/回复）；意义=端到端验证聊天链路，不影响线上会话状态。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  与 /bot context 的区别：dialogue 会真的走完 LLM 调用（配置了真实模型时\n'
                '  会产生一次真实调用费用），用于验收整条链路。\n'
                '【指令与参数】\n'
                '/bot dialogue：作用=默认文本跑一轮；参数=无；内容=各阶段诊断结果；意义=部署后第一轮验收。\n'
                '/bot dialogue <文本>：作用=指定输入跑一轮；参数=文本（可选）；内容=该输入的完整对话诊断；意义=复现特定问题的处理链路。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。可能产生一次 LLM 调用费用；不写入线上会话历史。\n'
                '【示例】/bot dialogue 今天状态怎么样'
            ),
        },
        {
            "topic": '接入',
            "admin_only": True,
            "aliases": ('接入', 'setup', 'llm setup'),
            "index": '【接入】LLM 接入清单：/bot setup llm',
            "title_line": '【接入】LLM 接入清单',
            "lines": [
                '/bot setup llm：作用=看接真实 LLM 还缺哪些配置；参数=无；内容=七个必配键（provider/model/key/base_url/temperature/max_tokens/timeout）的当前值、合法取值与标红缺口，附下一步指引；意义=接入向导，照着补 .env 就能通。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  把接入 OpenAI 兼容模型要动的七个键逐项体检。渲染可用时输出 Mica\n'
                '  配置卡；密钥永远只显示 已设置/缺失，不回显值。只读，不写 .env。\n'
                '【指令与参数】\n'
                '/bot setup llm：作用=输出接入清单；参数=无；内容=逐键：说明＋取值范围＋当前值＋OK/缺口，加下一步动作提示；意义=新部署接入或换供应商时照单抓药。\n'
                '【取值范围】\n'
                '  BOT_CHAT_PROVIDER=openai_compatible|static；MODEL=供应商模型名；KEY=真实密钥或 env:变量名；\n'
                '  BASE_URL=http(s):// 开头一般以 /v1 结尾；TEMPERATURE=0.0-2.0；MAX_TOKENS=≥0（0=不设上限）；TIMEOUT=>0 秒。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。改完 .env 重启生效；就绪后可用 /bot llm 做真实连接诊断。\n'
                '【示例】/bot setup llm'
            ),
        },
        {
            "topic": '配置',
            "admin_only": True,
            "aliases": ('配置', 'config'),
            "index": '【配置】配置检查：/bot config',
            "title_line": '【配置】配置就绪检查',
            "lines": [
                '/bot config：作用=配置体检；参数=无；内容=配置冒烟结果（缺什么、什么不合法，全部脱敏）；意义=改完配置后的快速自检。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  运行 config smoke：检查 LLM 接入、路径、模板等配置就绪度。\n'
                '  与 /bot setup llm 的区别：config 是全量体检，setup llm 只聚焦 LLM 七键。\n'
                '【指令与参数】\n'
                '/bot config：作用=配置体检；参数=无；内容=各项检查结果与原因（脱敏）；意义=定位配置错误的第一站。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。\n'
                '【示例】/bot config'
            ),
        },
        {
            "topic": '就绪',
            "admin_only": True,
            "aliases": ('就绪', 'readiness'),
            "index": '【就绪】聚合就绪状态：/bot readiness',
            "title_line": '【就绪】聚合就绪状态',
            "lines": [
                '/bot readiness：作用=聚合各链路就绪度；参数=无；内容=环境/配置/上下文/对话链路的就绪判定与软暂停状态；意义=开机后一眼判断能不能正常接客。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  readiness smoke 的聊天入口：把环境依赖、配置、上下文装配、对话链路\n'
                '  的就绪状态聚合成一份报告，附带运行时软暂停状态。\n'
                '【指令与参数】\n'
                '/bot readiness：作用=看聚合就绪；参数=无；内容=各链路 ok/blocked 与原因；意义=部署验收与健康巡检。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。\n'
                '【示例】/bot readiness'
            ),
        },
        {
            "topic": '角色',
            "admin_only": True,
            "aliases": ('角色', 'roles'),
            "index": '【角色】权限角色摘要：/bot roles',
            "title_line": '【角色】权限角色摘要',
            "lines": [
                '/bot roles：作用=看权限角色分布；参数=无；内容=admin/enterprise/trusted/blocked 的数量摘要（不含具体 ID）；意义=核对 BOT_ADMIN_USER_IDS 等名单是否被正确加载。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  角色体系：user < trusted < enterprise < admin（另有 blocked 屏蔽）。\n'
                '  管理员由 BOT_ADMIN_USER_IDS（QQ）与 BOT_TELEGRAM_ADMIN_USER_IDS（TG）确定。\n'
                '【指令与参数】\n'
                '/bot roles：作用=角色计数摘要；参数=无；内容=各角色数量；意义=权限问题排查（只给数量，不泄露名单）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。\n'
                '【示例】/bot roles'
            ),
        },
        {
            "topic": '人格',
            "admin_only": True,
            "aliases": ('人格', 'persona'),
            "index": '【人格】人格自检：/bot persona',
            "title_line": '【人格】守岸人人格材料自检',
            "lines": [
                '/bot persona：作用=人格材料自检；参数=无；内容=人格强度/语气规则/边界的自检结果；意义=确认人格档案完整、语气与边界规则生效。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  运行 persona smoke：检查人格档案文件、语气规则与安全边界材料。\n'
                '  运行期人格切换用 /bot runtime persona（见「设置」模块）。\n'
                '【指令与参数】\n'
                '/bot persona：作用=人格自检；参数=无；内容=自检 ok/error 与缺项；意义=人格“变了/淡了”类问题的第一排查点。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。\n'
                '【示例】/bot persona'
            ),
        },
        {
            "topic": '路由',
            "admin_only": False,
            "aliases": ('路由', 'route', 'routes'),
            "index": '【路由】查看消息会走哪条路：/bot route <文本>｜/bot routes',
            "title_line": '【路由】查看文本命中的路由',
            "lines": [
                '/bot route <文本>：作用=判定一段文本会命中哪条路由；参数=文本（必填，任意文本，省略回用法）；内容=路由类型/能力/优先级/理由，自然语言意图还会给出归一化后的命令；意义=搞清“这句话为什么被当成点歌/天气/闲聊”。',
                '/bot routes：作用=查看全部路由注册表；参数=无；内容=按优先级排序的全部路由规则（kind/能力/说明）；意义=了解路由优先级全貌。',
                '权限=全员（只读诊断，不执行命令本身）。',
                '示例：/bot route 帮我解析这个 https://www.bilibili.com/video/BVxxxx',
            ],
            "detail": (
                '【板块介绍】\n'
                '  基层路由是确定性注册表：昵称命令(10)→管理员命令(11)→订阅(12)→自动发送(13)→\n'
                '  表情(20)→偷表情(22)→点歌模式(40)→点歌/历史上的今天/维基/萌百/Epic/天气/行情/吃什么/\n'
                '  好感度/占卜/快报/随机图/提醒(41)→二次元问句(44)→自然语言命令(45)→链接解析(46)→聊天(50)。\n'
                '  数字越小越先命中。\n'
                '【指令与参数】\n'
                '/bot route <文本>：作用=单句路由判定；参数=文本（必填，任意文本）；内容=命中的 kind/capability_id/优先级/理由（含归一化结果）；意义=解释路由行为、验证触发词写法。\n'
                '/bot routes：作用=列出路由表；参数=无；内容=全部规则的审计视图；意义=宏观理解与排错。\n'
                '【权限与效果】\n'
                '  权限=全员（只读，不真的执行命中命令）。\n'
                '【示例】/bot route 点歌 晴天 → 会显示 MUSIC 路由；/bot route 天气真好 → 落到 CHAT。'
            ),
        },
        {
            "topic": '历史',
            "admin_only": True,
            "aliases": ('历史', 'history', '清理历史'),
            "index": '【历史】清理会话历史：/bot history clear',
            "title_line": '【历史】清理本会话最近对话历史',
            "lines": [
                '/bot history clear：作用=清空本会话最近对话；参数=无；内容=清理的轮次数（cleared_turns）；意义=对话被带偏后一键重置上下文；只清“当前会话×当前发送者×当前实例”，不动长期记忆。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  最近对话历史是拼进 prompt 的短期上下文。清理范围精确到\n'
                '  平台×适配器×机器人×会话×发送者，别人的对话和长期记忆不受影响。\n'
                '【指令与参数】\n'
                '/bot history clear：作用=清理最近对话；参数=无（写成别的子命令回用法）；内容=cleared_turns=N；意义=上下文污染后的软重置。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。清理失败只报类型不泄露库路径。\n'
                '【示例】/bot history clear'
            ),
        },
        {
            "topic": '暂停',
            "admin_only": True,
            "aliases": ('暂停', 'pause', 'resume', '恢复'),
            "index": '【暂停】软暂停/恢复：/bot pause|resume',
            "title_line": '【暂停】软暂停/恢复机器人回复',
            "lines": [
                '/bot pause：作用=软暂停回复；参数=无；内容=暂停后的运行时状态与原因；意义=维护/救火时让机器人闭嘴，不改任何配置。',
                '/bot resume：作用=恢复回复；参数=无；内容=恢复后的运行时状态；意义=解除软暂停。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  软暂停是运行时状态不是配置：不写 .env、不重启，暂停期间消息仍会接收\n'
                '  并留审计，只是不生成人格回复。\n'
                '【指令与参数】\n'
                '/bot pause：作用=软暂停；参数=无；内容=已暂停＋当前状态（reason/updated_by）；意义=紧急静音。\n'
                '/bot resume：作用=恢复；参数=无；内容=已恢复＋当前状态；意义=恢复服务。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。状态记入 /bot status 的「运行时软暂停」一行。\n'
                '【示例】/bot pause → 维护 → /bot resume'
            ),
        },
        {
            "topic": '回复',
            "admin_only": True,
            "aliases": ('回复', 'reply', '详略'),
            "index": '【回复】回复详略：/bot reply <详细|精简|默认>',
            "title_line": '【回复】调整回复详略档位',
            "lines": [
                '/bot reply：作用=查看当前详略档位；参数=无；内容=当前值与用法提示；意义=确认现状再决定改不改。',
                '/bot reply <模式>：作用=设置详略档位；参数=模式（必填，详细|精简|默认；别名 科普/详尽=详细，简洁=精简，自动=默认；未知值会回用法不再静默当默认）；内容=已设为 detail/concise/auto；意义=控制回答是展开讲还是短平快，持久保存。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  回复详略影响聊天链路的输出风格：详细=先结论再展开身份/关系/关键经历\n'
                '  与资料缺口（不凑字数）；精简=短句直给；默认=按问题复杂度自动取舍。\n'
                '【指令与参数】\n'
                '/bot reply：作用=查档位；参数=无；内容=当前 BOT_REPLY_DETAIL 值；意义=查看现状。\n'
                '/bot reply <模式>：作用=设档位；参数=模式（必填：详细/科普/详尽→detail；精简/简洁→concise；默认/自动→auto）；内容=回复详略已设为 X；意义=全员体感最直接的输出风格开关。\n'
                '【取值范围】\n'
                '  仅接受上表模式词；其他输入会得到用法提示（不会被静默当成默认）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。写入运行时覆盖，持久保存，立即生效。\n'
                '  相关键：BOT_CHAT_MAX_TOKENS（输出上限）、BOT_CHAT_FAST_MODE（快速模式）。\n'
                '【示例】/bot reply 详细｜/bot reply 精简｜/bot reply 默认'
            ),
        },
        {
            "topic": '模型',
            "admin_only": True,
            "aliases": ('模型', 'model', 'llm', '渠道', '切换模型'),
            "index": '【模型】/bot model list | set | add | update | priority | effort | think | price | search | usage | health | probe | routes | vision | remove | reset',
            "title_line": '【模型】模型与供应商管理（管理员，改动即时生效）',
            "lines": [
                '/bot llm：作用=诊断当前 provider/model/key 并做一次短调用；参数=无；内容=诊断报告（会产生一次真实调用的费用）；意义=验证当前渠道真能通。',
                '/bot model list：作用=查看全部模型与顺序；参数=无；内容=各模型思考强度档位、故障转移顺序（priority 越小越先）、当前时段分组、渠道健康标注与价格；意义=选型与排障的底表。',
                '/bot model health：作用=渠道健康报告；参数=无；内容=正常/连续失败踢出/慢渠道三类清单（踢出渠道 30 分钟半开重探自动回队）；意义=回答“为什么没用 A 渠道”。',
                '/bot model probe：作用=手动全渠道巡检；参数=无；内容=巡检受理提示（结果用 health 看）；意义=不等到后台周期主动体检，与后台巡检互斥。',
                '/bot model routes <模型名>：作用=按实测速度列渠道；参数=模型名（必填）；内容=快→慢的渠道排序（未实测排后）；意义=选最快渠道做手动 set。',
                '/bot model set <id|auto>：作用=切换当前模型；参数=id 或 auto（必填；id=已注册模型名/预设名/完整模型名，auto=回到自动选型）；内容=已手动指定 X 或已切自动；意义=手动钉死模型，失败仍自动转移。',
                '/bot model add <id> model=<模型名> base_url=<接口地址> key=<密钥> [tags=档位] [effort=档位] [group=<分组>] [priority=<n>]：作用=新增供应商；参数=id（必填，自定义名）＋model（必填）＋base_url（必填，OpenAI 兼容，一般 /v1 结尾）＋key（必填，支持 env:变量名）＋其余可选；内容=注册即生效；意义=零重启接入新渠道。',
                '/bot model update <id> <键=值...>：作用=改任意参数；参数=id（必填）＋要改的键=值（model/base_url/key/group/tags/effort/priority 任选）；内容=更新后的注册表；意义=换 key/调档位不用删了重建，可覆盖 .env 同名条目。',
                '/bot model priority <id> <n>：作用=只改故障转移顺序；参数=id（必填）＋n（必填，整数，越小越先，1..N 唯一槽位其余自动顺移）；内容=新顺序；意义=峰谷调序。',
                '/bot model effort <id> <档位>：作用=单模型思考强度覆盖；参数=id＋档位（必填，off|low|medium|high|xhigh|max|default，default=清除覆盖）；内容=确认信息；意义=给某个模型单独钉思考档。',
                '/bot model think <档位>：作用=全局思考强度；参数=档位（必填，off|low|medium|high|xhigh|max|留空；留空=清空回家族基线）；内容=确认信息；意义=一刀切控制 reasoning_effort 开销。',
                '/bot model price <模型名> [input=<元/1M> output=<元/1M>]：作用=维护价格表；参数=模型名（必填）＋input/output（不带即清除该模型价格，数字≥0）；内容=新价格确认；意义=账单计费依据，按调用时刻价格记账。',
                '/bot model usage [today|YYYY-MM-DD]：作用=每日用量账单；参数=日期（可选，today/今天 或 YYYY-MM-DD，省略=今天）；内容=输入/输出/缓存命中/缓存创建 Token、调用次数、按模型分组的费用；意义=看清钱花在哪。',
                '/bot model search <on|off>：作用=热切换联网搜索；参数=on|off（必填）；内容=开/关确认；意义=不用重启控制 web_search。',
                '/bot model vision list|add|update|priority|remove|mode <relay|direct>：作用=图片识别模型管理；参数=子命令＋各自参数（add 同 model add，mode=relay 转文字|direct 直传主模型）；内容=注册表/模式确认；意义=识图管线选型。',
                '/bot model remove <id>：作用=删除自定义模型；参数=id（必填；.env 来源条目不可删只能 update 覆盖）；内容=删除确认；意义=清理废弃渠道。',
                '/bot model reset：作用=清除手动指定；参数=无；内容=回到自动选型确认；意义=撤销 set。',
                '思考强度档位：DeepSeek/GLM/Kimi/MiniMax=low,high,max｜GPT/Grok=low,medium,high,xhigh｜Gemini=low,medium,high；默认=家族基线档，复杂任务自动升家族最高档。',
                '示例：/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1',
                '注意：key 不回显；等号两边不要加空格；新增/修改/价格/分组全部热更立即生效，重启保留。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  模型注册表＋故障转移＋渠道健康＋思考强度＋计费的总控台。\n'
                '  /bot model 与 /bot runtime model 等价。改动即时生效、无需重启；\n'
                '  运行时覆盖优先于 .env。\n'
                '【指令与参数】\n'
                '/bot llm：作用=诊断当前渠道；参数=无；内容=provider/model/key 状态与一次短调用结果；意义=真实连通性验证（会花钱）。\n'
                '/bot model list：作用=看底表；参数=无；内容=候选模型/档位/顺序/时段分组/健康/价格；意义=一切模型操作的起点。\n'
                '/bot model health：作用=健康报告；参数=无；内容=ok/踢出/慢渠道三段（评级用平滑延迟 EWMA）；意义=解释渠道为什么被跳过。\n'
                '/bot model probe：作用=手动巡检；参数=无；内容=受理提示；意义=立刻体检全部渠道（每渠道一次最小调用，费用极低；与后台巡检互斥）。\n'
                '/bot model routes <模型名>：作用=渠道测速排名；参数=模型名（必填）；内容=快→慢列表；意义=挑最快渠道。\n'
                '/bot model set <id|auto>：作用=手动指定；参数=id|auto（必填）；内容=确认信息；意义=钉死模型；auto 撤销。手动指定 > 时段组 order > 基础 priority。\n'
                '/bot model add <id> model= base_url= key= [tags=] [effort=] [group=] [priority=]：作用=新增；参数逐个：id=你起的名字（之后 set/update/remove 用它）；model=供应商模型名原样填；base_url=OpenAI 兼容接口，http(s):// 开头一般 /v1 结尾；key=sk-xxx 或 env:变量名；tags=档位列表逗号分隔；effort=单模型覆盖；group=令牌分组；priority=整数越小越先（默认 100）；内容=注册即进路由；意义=免重启扩容。\n'
                '/bot model update <id> <键=值...>：作用=改条目；参数=只写要改的键（model base_url key group tags effort priority）；内容=更新确认；意义=换 key/改档位；可覆盖 .env 同名条目。\n'
                '/bot model priority <id> <n>：作用=调转移顺序；参数=n 整数，1..N 唯一槽位（移动一个其余顺移，0 兼容为移到首位）；内容=新顺序；意义=控成本（贵的放后）。\n'
                '/bot model effort <id> <档位>：作用=单模型强度；参数=off|low|medium|high|xhigh|max|default（default/默认/reset=清除覆盖回家族基线）；内容=确认信息；意义=单点微调。\n'
                '/bot model think <档位>：作用=全局强度；参数=off|low|medium|high|xhigh|max 或留空（留空=清空覆盖）；内容=确认信息；意义=全局控制推理开销；复杂任务会临时升档。\n'
                '/bot model price <模型名> [input= output=]：作用=维护价格；参数=模型名必填；input/output=元/每百万 token，数字≥0；不带价格参数=清除；内容=设置/清除确认；意义=账单准确性；调价只影响之后的调用。\n'
                '/bot model usage [today|YYYY-MM-DD]：作用=日账单；参数=日期可选；内容=Token/费用/按模型分组/未计价次数；意义=成本可见。\n'
                '/bot model search <on|off>：作用=联网搜索开关；参数=on|off 必填；内容=开关确认；意义=热控 web_search。\n'
                '/bot model vision list|add|update|priority|remove：作用=识图模型管理；参数=同模型条目；内容=注册表变化；意义=识图选型。\n'
                '/bot model vision mode <relay|direct>：作用=识图模式；参数=relay（视觉模型转文字）|direct（图片直传主模型）；内容=模式确认；意义=多模态质量与成本取舍。\n'
                '/bot model remove <id>：作用=删除；参数=id 必填（.env 来源不可删）；内容=删除确认；意义=清理。\n'
                '/bot model reset：作用=回自动选型；参数=无；内容=确认信息；意义=撤销手动 set。\n'
                '【取值范围】\n'
                '  档位：DeepSeek/GLM/Kimi/MiniMax=low,high,max｜GPT/Grok=low,medium,high,xhigh｜Gemini=low,medium,high。\n'
                '  时段分组：/bot runtime set BOT_MODEL_PRIORITY_GROUPS <JSON 数组>，每组\n'
                '  {"name":"工作日高峰","days":[1..7],"windows":[["09:00","12:00"]],"order":[模型id...]}；\n'
                '  days 缺省=每天，windows 缺省=全天，都缺省=兜底组；按列表顺序取第一个命中组。\n'
                '  分时段切换：/bot runtime set BOT_MODEL_SCHEDULE {"23:00-07:00":"luna"}（支持跨零点）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。全部子命令热更立即生效、持久保存；key 永不回显；\n'
                '  不要在群聊发送真实 Key，用 key=env:变量名。\n'
                '【示例】/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1'
            ),
        },
        {
            "topic": '用量',
            "admin_only": True,
            "aliases": ('用量', 'usage', '账单', '花费', '监控'),
            "index": '【用量】Token 统计、费用记账与监控提醒：/bot model usage | /bot model price',
            "title_line": '【用量】Token 统计、费用记账与监控提醒',
            "lines": [
                '/bot model usage [today|YYYY-MM-DD]：作用=每日用量账单；参数=日期（可选，省略=今天）；内容=输入/缓存命中/缓存创建/输出 Token、调用次数、按模型分组费用、未计价次数；意义=每天钱花在哪一目了然。',
                '/bot model price <模型名> input=<元/1M> output=<元/1M>：作用=维护价格表；参数=模型名（必填）＋价格（数字≥0；不带价格=清除）；内容=确认信息；意义=账单计费依据。',
                '实时提醒：单模型当日输出>500万或输入>5000万 token、当日账单>10元 → 自动推送管理员（阈值可在 .env 调）。',
                '定时报告：北京时间 13:00/18:00/23:00 推送自上个报告点至今的金额与 Token；13:00 附过去 24 小时总花费。',
                '口径：费用按每次调用时刻的价格记账，调价不影响历史账单；未配价格的模型不计费并在账单标注。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  用量监控三件套：账单查询（usage）、价格维护（price）、主动提醒\n'
                '  （实时阈值＋定时报告）。提醒与报告推给全部管理员（QQ 私聊，统一预警\n'
                '  管线），渲染可用时附 Mica 账单卡，失败回退纯文本。\n'
                '【指令与参数】\n'
                '/bot model usage [today|YYYY-MM-DD]：作用=查账单；参数=日期（可选，today/今天/YYYY-MM-DD，省略=今天，格式错回用法）；内容=Token 四项＋调用次数＋费用＋按模型明细；意义=成本审计。\n'
                '/bot model price <模型名> [input= output=]：作用=维护价格；参数=见「模型」模块；内容=确认信息；意义=计费基准。\n'
                '【取值范围】\n'
                '  阈值 .env 键：BOT_USAGE_ALERT_OUTPUT_TOKENS（默认 5,000,000）、\n'
                '  BOT_USAGE_ALERT_INPUT_TOKENS（默认 50,000,000）、BOT_USAGE_ALERT_DAILY_COST_YUAN（默认 10）。\n'
                '  报告时间：BOT_USAGE_REPORT_HOURS（逗号分隔整点，默认 13,18,23）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。每项实时提醒每天最多触发一次；报告时间点持久化，重启不丢。\n'
                '【示例】/bot model usage 2026-09-01'
            ),
        },
        {
            "topic": '设置',
            "admin_only": True,
            "aliases": ('设置', 'runtime', '参数', '运行时'),
            "index": '【设置】运行时参数：/bot runtime set|get|list|reset|nickname|persona|instance',
            "title_line": '【设置】运行时参数管理（管理员）',
            "lines": [
                '/bot runtime set <KEY> <VALUE>：作用=热改一个参数；参数=KEY（必填，可写键见 get 列表）＋VALUE（必填，按键校验）＋--instance <名称>（可选，定位实例）；内容=已设置 KEY = 值（已持久化）；意义=不改 .env 立即生效，重启保留。',
                '/bot runtime get <KEY>：作用=读参数实际生效值；参数=KEY（必填）；内容=值＋（覆盖值）/（.env 默认值）来源标注；意义=确认运行时覆盖与 .env 谁在生效。',
                '/bot runtime list：作用=列出全部覆盖项；参数=无；内容=KEY=VALUE 清单；意义=盘点改过哪些。',
                '/bot runtime reset [KEY]：作用=恢复默认；参数=KEY（可选，省略=清空全部覆盖）；内容=清除项数；意义=撤销热改。',
                '/bot runtime persona <action>：作用=人格运行期管理；参数=action（list｜switch <id|default>｜probability <id> <0-1>）；内容=人格清单/切换确认/触发概率确认；意义=不重启换人格。',
                '/bot runtime nickname add|remove|list [昵称]：作用=角色昵称管理；参数=action（必填）＋昵称（add/remove 必填）；内容=昵称表；意义=控制哪些称呼能触发昵称命令。',
                '/bot runtime model <子命令>：作用=模型管理（=/bot model）；参数=见「模型」模块；内容=同 /bot model；意义=同义入口。',
                '/bot runtime instance list：作用=列出实例设置；参数=无；内容=已有实例名单；意义=多实例部署核对。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  运行时参数层：SETTABLE_KEYS 白名单内的键可热改并持久化（运行时覆盖\n'
                '  优先于 .env）；不在白名单的键（如五个持久化开关）只能改 .env 重启。\n'
                '  所有子命令都可加 --instance <名称> 操作指定实例。\n'
                '【指令与参数】\n'
                '/bot runtime set <KEY> <VALUE>：作用=设置；参数=KEY 必填（白名单键，发错会列出可用键）、VALUE 必填（按键的类型校验，非法值拒绝）；内容=设置确认；意义=热改主入口。\n'
                '/bot runtime get <KEY>：作用=读取；参数=KEY 必填；内容=值＋来源；意义=查实际生效值。\n'
                '/bot runtime list：作用=列覆盖；参数=无；内容=覆盖清单；意义=盘点。\n'
                '/bot runtime reset [KEY]：作用=清覆盖；参数=KEY 可选（省略=全部）；内容=清除计数；意义=回滚热改。\n'
                '/bot runtime persona list：作用=列人格；参数=无；内容=可选人格与当前项；意义=选型。\n'
                '/bot runtime persona switch <id|default>：作用=切人格；参数=id 或 default（default=回默认）；内容=切换确认；意义=运行期换人格。\n'
                '/bot runtime persona probability <id> <0-1>：作用=设人格触发概率；参数=id＋概率（0..1）；内容=确认信息；意义=多人格混投。\n'
                '/bot runtime nickname add|remove|list [昵称]：作用=昵称管理；参数=add/remove 需昵称参数；内容=昵称表；意义=昵称命令的触发词维护。\n'
                '【常用可写键举例】\n'
                '  BOT_MODEL_SCHEDULE（分时段切换，JSON）、BOT_MODEL_PRIORITY_GROUPS（峰谷分组，JSON 数组）、\n'
                '  BOT_MODEL_PRICES（价格表 JSON）、BOT_CHAT_REASONING_EFFORT（off|low|medium|high|xhigh|max|留空）、\n'
                '  BOT_REPLY_DETAIL、BOT_CHAT_MAX_TOKENS、BOT_CHAT_FAST_MODE、BOT_VISION_ENABLED、\n'
                '  BOT_QUIET_HOURS_*（6 键）、BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR 等（完整清单：/bot runtime get 随便发一个错键）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。写入即持久化并通知热更；个别装配期读取的键（如\n'
                '  BOT_GROUP_CHAT_AUTO_REPLY_ENABLED）需重启，帮助各模块会单独标注。\n'
                '【示例】/bot runtime set BOT_QUIET_HOURS_ENABLED true'
            ),
        },
        {
            "topic": '搜索',
            "admin_only": True,
            "aliases": ('搜索', 'search'),
            "index": '【搜索】验证联网检索：/bot search <问题>',
            "title_line": '【搜索】管理员验证联网检索',
            "lines": [
                '/bot search <问题>：作用=验证联网检索链路；参数=问题（必填，省略回用法）；内容=检索结果列表（标题/摘要/链接）或失败原因；意义=区分“模型不知道”和“搜索没通”。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  直接调用检索供应商（Tavily 主链＋fallback）做一次真实搜索，\n'
                '  不走人格链路，用于验证搜索配置。\n'
                '【指令与参数】\n'
                '/bot search <问题>：作用=真实检索一次；参数=问题（必填）；内容=至多 BOT_WEB_SEARCH_MAX_RESULTS 条结果（默认 12）；意义=排障检索链路。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。检索源不可达/被反爬/代理未生效时给出降级说明。\n'
                '【示例】/bot search 守岸人是什么游戏的角色'
            ),
        },
        {
            "topic": '解析',
            "admin_only": True,
            "aliases": ('解析', 'parse'),
            "index": '【解析】解析历史：/bot parse [数量]',
            "title_line": '【解析】查看最近解析历史',
            "lines": [
                '/bot parse [数量]：作用=查看最近链接解析历史；参数=数量（可选，1-100，默认 10）；内容=跨会话的 URL＋标题＋时间清单（全局范围）；意义=排查“刚才那条链接解析出了什么”。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  解析历史是全局范围（跨群/跨私聊），因此收紧为管理员可见。\n'
                '【指令与参数】\n'
                '/bot parse：作用=看最近 10 条；参数=无；内容=URL/标题/时间；意义=快速回查。\n'
                '/bot parse <数量>：作用=控制条数；参数=数量（可选，1-100，默认 10）；内容=对应条数；意义=深挖。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（M24 收紧：链接自带 token 时等于二次扩散，不对普通成员开放）。\n'
                '【示例】/bot parse 20'
            ),
        },
        {
            "topic": '凭据',
            "admin_only": True,
            "aliases": ('凭据', 'alert', 'cookie'),
            "index": '【凭据】凭据健康与 cookie 导入：/bot alert check｜/bot cookie status|import|login|check|expiry',
            "title_line": '【凭据】检查 cookie/凭据健康',
            "lines": [
                '/bot alert check：作用=凭据体检；参数=无；--probe（可选开关，追加在线探测，401/403=需重登）；内容=各凭据引用的状态清单；意义=解析突然 403 时的第一排查。',
                '/bot cookie status：作用=看各平台已录 cookie；参数=无；内容=平台×cookie 名×到期日（永不回显值）；意义=核对导入是否生效。',
                '/bot cookie import <平台> <Cookie头>：作用=热写入平台 cookie；参数=平台（必填）＋Cookie头（必填，浏览器复制的 名=值; … 整行）；内容=导入结果；意义=同名不覆盖、下一次解析即生效无需重启。',
                '/bot cookie login <平台>：作用=扫码登录；参数=平台（必填，当前仅 bilibili 支持扫码）；内容=二维码图＋登录指引；意义=免手动导 cookie。',
                '/bot cookie check <平台>：作用=查扫码结果；参数=平台（必填）；内容=最近一次扫码登录状态；意义=扫码后确认。',
                '/bot cookie expiry：作用=全平台过期报告；参数=无；内容=各平台凭证有效期报告；意义=批量核对到期情况。',
                '平台（18）：bilibili/xiaohongshu/douyin/qqmusic/netease/kuwo/kugou/twitter/youtube/kurobbs/weibo/kuaishou/acfun/moegirl/xiaoheihe/skland/miyoushe/zhihu',
                '权限=仅管理员；每天 10:00 自动巡检一次并向在线管理员推送过期预警。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  平台 cookie 是解析/下载/订阅的登录态。统一存在 cookies.txt，\n'
                '  值永不回显；每天 10:00 定时巡检（bot_cookie_expiry_reminder_enabled\n'
                '  可关），过期会私聊推送第一位在线管理员。\n'
                '【指令与参数】\n'
                '/bot alert check：作用=凭据体检；参数=--probe 可选开关；内容=各引用状态＋是否需重登；意义=被动巡检的手动版。\n'
                '/bot cookie status：作用=查已录凭证；参数=无；内容=共 N/18 个平台已有凭证＋各平台明细；意义=核对。\n'
                '/bot cookie import <平台> <Cookie头>：作用=导入；参数=平台（18 选 1，小写）＋Cookie 头（整行原文粘贴）；内容=accepted/normalized/skipped 统计；意义=同名不覆盖、热生效。\n'
                '/bot cookie login <平台>：作用=扫码；参数=平台（当前 bilibili）；内容=二维码；意义=便捷登录。\n'
                '/bot cookie check <平台>：作用=扫码结果；参数=平台；内容=登录状态；意义=确认。\n'
                '/bot cookie expiry：作用=过期报告；参数=无；内容=全平台有效期；意义=批量巡检。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（命令匹配层就拦，非管理员无感）。\n'
                '【示例】/bot cookie import bilibili SESSDATA=...; bili_jct=...'
            ),
        },
        {
            "topic": '群策略',
            "admin_only": True,
            "aliases": ('群策略', 'group', '群'),
            "index": '【群策略】群回复策略档位：/bot group list|add|del|set|clear',
            "title_line": '【群策略】群聊回复策略档位（管理员）',
            "lines": [
                '/bot group [list]：作用=查看各档位群名单；参数=无或 list；内容=黑1/黑2/白1/白2 四档的群号清单；意义=盘点现状。',
                '/bot group add <档位> <群号...>：作用=把群加入档位；参数=档位（必填，black1|black2|white1|white2，可用 黑1/黑2/白1/白2）＋群号（必填，数字，可多个）；内容=更新后的名单；意义=批量拉黑/拉白。',
                '/bot group del <档位> <群号...>：作用=移出档位；参数=同 add；内容=更新后的名单；意义=解除。',
                '/bot group set <档位> <群号...>：作用=覆盖档位名单；参数=同 add；内容=更新后的名单；意义=整表重置。',
                '/bot group clear <档位>：作用=清空档位；参数=档位（必填）；内容=空名单确认；意义=一键清空。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  四档群聊策略：black1=完全静默只收不发；black2=只回“@且带指令”；\n'
                '  white1=正常回复并可参与主动接话；white2=只回“@或显式命令”。\n'
                '  不在任何名单=默认档（正常回复）。\n'
                '【指令与参数】\n'
                '/bot group list：作用=查看各档位名单；参数=无或 list；内容=四档群号清单；意义=盘点现状。\n'
                '/bot group add <档位> <群号...>：作用=加群入档；参数=档位（必填，black1|black2|white1|white2）＋群号（必填，数字可多个）；内容=更新后名单；意义=批量管理。\n'
                '/bot group del <档位> <群号...>：作用=移出档位；参数=同 add；内容=更新后名单；意义=解除。\n'
                '/bot group set <档位> <群号...>：作用=覆盖档位名单；参数=同 add；内容=更新后名单；意义=整表重置。\n'
                '/bot group clear <档位>：作用=清空档位；参数=档位（必填）；内容=空名单；意义=一键清空。\n'
                '  动作词可用中文别名：加/加入=add，删/移除/remove=del，设/设置=set，清/清空/reset=clear，查/查看=list。\n'
                '  群号必须纯数字，可一次给多个；档位写错会提示四档取值。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。写入运行时覆盖（BOT_GROUP_BLACK1/BLACK2/WHITE1/WHITE2），\n'
                '  热改立即生效。\n'
                '【示例】/bot group add white1 123456789 987654321'
            ),
        },
        {
            "topic": '群文件',
            "admin_only": True,
            "aliases": ('群文件', '群文件统计'),
            "index": '【群文件】群上传统计：/bot 群文件（仅群聊）',
            "title_line": '【群文件】群上传记录与整理建议（管理员）',
            "lines": [
                '/bot 群文件：作用=看本群文件上传统计；参数=无（仅群聊可用，统计当前群）；内容=最近上传清单＋扩展名分布（文档/压缩包/图片/视频/音频/其他）＋整理建议；意义=群盘整理前的摸底。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  群文件上传事件（OneBot group_upload）实时入 SQLite，按群/文件名/大小/\n'
                '  时间/上传者记录。OneBot 不提供移动文件夹 API，所以“整理”落地为\n'
                '  记录＋统计＋提醒，不假装能移动文件。\n'
                '【指令与参数】\n'
                '/bot 群文件：作用=统计当前群；参数=无；内容=最近上传与类型分布；意义=摸底。\n'
                '【权限与效果】\n'
                '  权限=仅管理员；仅群聊可用（私聊提示不可用）。\n'
                '【示例】/bot 群文件'
            ),
        },
        {
            "topic": '日志',
            "admin_only": True,
            "aliases": ('日志', 'logs'),
            "index": '【日志】运行时日志：/bot logs [级别] [数量]',
            "title_line": '【日志】查看运行时事件日志',
            "lines": [
                '/bot logs [级别] [数量]：作用=查看运行时事件日志；参数=级别（可选，debug|info|warning|error，默认 info）＋数量（可选，1-200 整数，默认 50），两个参数按「先级别后数量」顺序写；内容=最近 N 条对应级别以上的日志；意义=看运行时到底发生了什么。',
                '权限=仅管理员（别名「日志」经昵称命令层同样需要 /bot 形式执行）。',
                '示例：/bot logs error 20',
            ],
            "detail": (
                '【板块介绍】\n'
                '  运行时事件日志（runtime_event_log）的查询口：统一记录各能力的关键\n'
                '  事件（WARNING/ERROR 等），按级别过滤、按条数截取。\n'
                '【指令与参数】\n'
                '/bot logs：作用=默认查询；参数=无；内容=info 级最近 50 条；意义=日常快查。\n'
                '/bot logs <级别>：作用=按级别过滤；参数=级别（debug|info|warning|error，其他词回退 info）；内容=对应级别日志；意义=聚焦错误。\n'
                '/bot logs <级别> <数量>：作用=级别＋条数；参数=数量（1-200，越界自动收敛；非数字回退 50）；内容=对应日志；意义=多看几条。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。日志未启用时提示运行时事件日志未启用。\n'
                '【示例】/bot logs error 20'
            ),
        },
        {
            "topic": '文件',
            "admin_only": True,
            "aliases": ('文件', '文件导出', '导出'),
            "index": '【文件】生成文档并上传：文件 <md|markdown|docx|pptx|xlsx|pdf> <主题>',
            "title_line": '【文件】主题生成文档并群文件上传（管理员）',
            "lines": [
                '文件 <格式> <主题>：作用=围绕主题生成文档并以群文件形式上传；参数=格式（必填，md|markdown|docx|pptx|xlsx|pdf，大小写不敏感）＋主题（必填，非空文本，作为文档标题与大纲素材）；内容=已生成并上传 <格式>：文件名（KB）或失败原因；意义=长文/表格/幻灯一键落盘成文件，不刷屏。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  LLM 按文档撰写提示词生成结构化 Markdown（分级标题/列表/表格，\n'
                '  600-1200 字），再本地转换成目标格式，经平台上传接口发出。\n'
                '【指令与参数】\n'
                '文件 <格式> <主题>：作用=生成并上传文档；参数=格式（md/markdown/docx/pptx/xlsx/pdf，markdown 归一为 md）＋主题（必填，截 40 字作标题）；内容=上传确认或失败类型；意义=文件交付。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（命令匹配层拦截）。生成与转换在后台线程执行（数十秒级），\n'
                '  产出落 data/downloads/export/ 后上传；LLM 失败只报错误类型。\n'
                '【示例】文件 docx 鸣潮 2.0 版本角色梯度整理'
            ),
        },
        {
            "topic": '身份',
            "admin_only": True,
            "aliases": ('身份', 'identity', '会话身份'),
            "index": '【身份】会话身份记忆：/bot identity show|set|tag|clear',
            "title_line": '【身份】会话级身份记忆（管理员）',
            "lines": [
                '/bot identity show：作用=查看本会话身份；参数=无；内容=称呼/标签/设置人/更新时间（未设置会明说）；意义=核对当前会话的身份设定。',
                '/bot identity set <昵称>：作用=设定本会话称呼；参数=昵称（必填，非空文本，如 set 岸宝）；内容=已设定称呼确认；意义=让机器人在这群/这个私聊里只这么叫你。',
                '/bot identity tag <标签1,标签2>：作用=设定标签；参数=标签串（必填，逗号分隔，最多保留 8 个）；内容=已设定标签确认；意义=给语气调整提供更多线索。',
                '/bot identity clear：作用=清除本会话身份；参数=无；内容=已清除/本就没有；意义=恢复默认。',
                '权限=仅管理员；在哪个群/私聊执行就对哪个会话生效，各会话互不影响；只影响称呼与语气，人格不变（渲染层内建防 OOC 护栏）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  给单个会话（群或私聊）设置独立的身份记忆：机器人怎么称呼你、带哪些\n'
                '  标签。在哪个会话执行就只对那个会话生效。数据存\n'
                '  data/session_identity.sqlite3（.env 可用 BOT_SESSION_IDENTITY_DB_PATH 改路径）。\n'
                '【指令与参数】\n'
                '/bot identity show：作用=查看；参数=无；内容=称呼「…」＋标签＋设置人＋更新时间；意义=核对。\n'
                '/bot identity set <昵称>：作用=设称呼；参数=昵称必填（非空文本，可含中文/英文，建议 ≤16 字）；内容=已设定确认；意义=个性化称呼。\n'
                '/bot identity tag <标签1,标签2>：作用=设标签；参数=逗号分隔标签串（最多保留 8 个，超出截断）；内容=已设定确认；意义=补充语气线索。\n'
                '/bot identity clear：作用=清除；参数=无；内容=清除确认；意义=重置。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。只调整该会话内的称呼与语气，不改变守岸人核心人格；\n'
                '  防止会话身份被用来推翻人格设定（防 OOC 护栏内建于渲染层）。\n'
                '【示例】/bot identity set 岸宝｜/bot identity tag 早起,秃头,干饭人'
            ),
        },
        {
            "topic": '怪癖',
            "admin_only": True,
            "aliases": ('怪癖', 'quirk', '人格怪癖'),
            "index": '【怪癖】人格怪癖审核：/bot quirk list|approve|retire|add',
            "title_line": '【怪癖】人格怪癖演化区（管理员，审核制）',
            "lines": [
                '/bot quirk list [pending|active|retired]：作用=列出怪癖；参数=状态过滤（可选，pending=待审|active=生效|retired=退役，省略=全部，最多 20 条）；内容=id 前 8 位＋状态＋文本＋来源；意义=先拿 id 再审核。',
                '/bot quirk approve <id前缀>：作用=待审转生效；参数=id 前缀（必填，需唯一命中，0 条或多条都拒绝）；内容=已通过＋文本；意义=审核制放行，approve 前对回复零影响。',
                '/bot quirk retire <id前缀>：作用=退役生效项；参数=id 前缀（必填，唯一命中）；内容=已退役＋文本；意义=不再渲染但保留记录。',
                '/bot quirk add <习惯描述>：作用=管理员直添；参数=习惯描述（必填）；内容=已直接生效；意义=跳过审核立即影响 prompt。',
                '审核制红线：自动来源（反思回路等 propose）只进待审（pending_review），绝不直接影响 prompt；BOT_QUIRKS_ENABLED=false 时整个演化区停用。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  L4 人格演化区：一小批可选的说话习惯/怪癖，生效后由人格装配渲染进\n'
                '  上下文。审核制红线：自动来源只进待审队列；管理员 add 直添是唯一\n'
                '  免审通道。数据存 data/persona_quirks.sqlite3。\n'
                '【指令与参数】\n'
                '/bot quirk list [状态]：作用=列出；参数=状态过滤可选（pending|active|retired，其他值回用法），limit=20；内容=清单；意义=审核前置。\n'
                '/bot quirk approve <id前缀>：作用=放行；参数=id 前缀（唯一命中）；内容=已通过；意义=待审→生效，之后渲染进人格上下文。\n'
                '/bot quirk retire <id前缀>：作用=退役；参数=id 前缀（唯一命中）；内容=已退役；意义=生效→退役，记录保留不再渲染。\n'
                '/bot quirk add <习惯描述>：作用=直添；参数=描述必填；内容=已直接生效；意义=管理员特权通道。\n'
                '【取值范围】\n'
                '  状态只有三种：待审 pending(pending_review)/生效 active/退役 retired；\n'
                '  前缀必须唯一命中；BOT_QUIRKS_ENABLED=false 时命令只返回停用提示。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。approve 后的 active 项渲染进人格上下文；待审项在\n'
                '  approve 前对回复没有任何影响。\n'
                '【示例】/bot quirk list pending → /bot quirk approve 3fa2'
            ),
        },
        {
            "topic": '限流',
            "admin_only": True,
            "aliases": ('限流', '句数帽', '安静时间', '情绪豁免', '自动接话'),
            "index": '【限流】群句数帽/情绪豁免/安静时间/自动接话：BOT_RATE_LIMIT_*、BOT_QUIET_HOURS_*',
            "title_line": '【限流】群聊句数帽、情绪豁免、安静时间与自动接话（管理员）',
            "lines": [
                '群聊句数帽：BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR / BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE，取值=≥0 整数（0=该帽不生效），默认 0；内容=超帽后普通回复被静默拦截；意义=防刷屏。',
                '情绪豁免：BOT_RATE_LIMIT_EMOTION_EXEMPT，取值=true/false，默认 true；内容=安抚类回复不被句数帽拦截；意义=该安慰的时候不被限流卡住。',
                '自动接话：BOT_GROUP_CHAT_AUTO_REPLY_ENABLED（true/false，默认 false）＋BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY（0..1，默认 0.05）；内容=未点名消息按概率（与心情系数相乘）抽签接话；意义=群活跃度调节。',
                '安静时间 6 键：BOT_QUIET_HOURS_ENABLED / BOT_QUIET_HOURS_START / BOT_QUIET_HOURS_END / BOT_QUIET_HOURS_TIMEZONE / BOT_QUIET_HOURS_SESSION_TYPES / BOT_QUIET_HOURS_BYPASS_ROLES；内容=窗口内只拦截未点名的普通聊天/解析；意义=定时闭嘴。',
                '修改方式：以上全部支持 /bot runtime set 热改，立即生效（接话总开关 ENABLED 装配期读取，改后需重启）。',
                '示例：/bot runtime set BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR 60',
            ],
            "detail": (
                '【板块介绍】\n'
                '  控制机器人在群里的回复频率与时机：句数帽封顶、情绪豁免保安抚、\n'
                '  安静时间定时闭嘴、自动接话按概率抽签。全部经 /bot runtime set 修改。\n'
                '【指令与参数】\n'
                'BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR：作用=每小时句数帽；参数=≥0 整数（0=该帽不生效）；内容=超帽静默；意义=小时级封顶。\n'
                'BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE：作用=每分钟句数帽；参数=同上；内容=同上；意义=脉冲防护；用户口径建议 60/小时、3/分钟。\n'
                'BOT_RATE_LIMIT_EMOTION_EXEMPT：作用=情绪豁免；参数=true/false（默认 true）；内容=安抚类回复绕过句数帽；意义=该安慰的时候不被限流卡住。\n'
                'BOT_GROUP_CHAT_AUTO_REPLY_ENABLED：作用=自动接话总开关；参数=true/false（默认 false）；内容=开/关；意义=接话前提。\n'
                'BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY：作用=接话概率；参数=0..1（默认 0.05，与心情系数相乘后封顶 1.0）；内容=抽签；意义=频率。\n'
                '安静时间 6 键：ENABLED（true/false）、START/END（HH:MM，支持跨零点，默认 00:00-06:00）、TIMEZONE（IANA 名）、SESSION_TYPES（group|private|email 逗号分隔，默认 group）、BYPASS_ROLES（默认 admin）；内容=窗口内只拦未点名普通聊天/解析；意义=作息。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。热改立即生效；点名/显式命令永远不受安静时间与概率影响；\n'
                '  自动接话用确定性哈希抽签，同一消息结果稳定。\n'
                '【示例】/bot runtime set BOT_QUIET_HOURS_START 01:00'
            ),
        },
        {
            "topic": '合并转发',
            "admin_only": True,
            "aliases": ('合并转发', '转发合并'),
            "index": '【合并转发】长回复合并阈值：/bot runtime set BOT_RENDER_FORWARD_*',
            "title_line": '【合并转发】长回复合并为转发消息的阈值（管理员）',
            "lines": [
                'BOT_RENDER_FORWARD_MIN_NODES：作用=按条数触发合并；参数=≥0 整数，默认 4（0=不按条数只看字数）；内容=切分后达到该条数即合并成 QQ 合并转发；意义=超过 3 条就打包。',
                'BOT_RENDER_FORWARD_MIN_CHARS：作用=按字数触发合并；参数=≥0 整数，默认 1500；内容=达到字数也触发；意义=长文兜底。',
                'BOT_RENDER_FORWARD_MAX_NODES：作用=节点数上限；参数=≥0 整数，默认 0=不限制；内容=切分块数尽量压到该上限（硬长度边界优先）；意义=防刷屏。',
                'BOT_RENDER_FORWARD_NODE_CHARS：作用=单节点目标字数；参数=≥200 整数，默认 900；内容=每个转发节点的目标字数；意义=控制单条体积。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  长回复按字数/条数切成多个节点并合并成一条 QQ 合并转发消息，\n'
                '  四个键分别控制条数触发、字数触发、节点上限与单节点字数。\n'
                '【指令与参数】\n'
                'BOT_RENDER_FORWARD_MIN_NODES：作用=按条数触发合并；参数=≥0 整数（默认 4，0=不按条数）；内容=达标即合并；意义=超过 3 条就打包。\n'
                'BOT_RENDER_FORWARD_MIN_CHARS：作用=按字数触发合并；参数=≥0 整数（默认 1500）；内容=达标也合并；意义=长文兜底。\n'
                'BOT_RENDER_FORWARD_MAX_NODES：作用=节点数上限；参数=≥0 整数（默认 0=不限制）；内容=块数尽量压到上限；意义=防刷屏。\n'
                'BOT_RENDER_FORWARD_NODE_CHARS：作用=单节点目标字数；参数=≥200 整数（默认 900）；内容=单节点体积；意义=阅读体验。\n'
                '  四键均经 /bot runtime set 热改。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。条数达 MIN_NODES 或字数达 MIN_CHARS 即合并；\n'
                '  消费点在装配期读取，改动需重启生效。\n'
                '【示例】/bot runtime set BOT_RENDER_FORWARD_MIN_NODES 3'
            ),
        },
        {
            "topic": '群摘要',
            "admin_only": True,
            "aliases": ('群摘要', '群聊摘要', '群概要'),
            "index": '【群摘要】群聊摘要与名单：BOT_SHARED_GROUP_CONTEXT_ENABLED、BOT_GROUP_DIGEST_*、每日通讯总结推送',
            "title_line": '【群摘要】群聊上下文摘要、群名单与每日通讯总结推送（管理员）',
            "lines": [
                '总开关：BOT_SHARED_GROUP_CONTEXT_ENABLED，取值=true/false，默认 false；内容=开启才生成群摘要；意义=群上下文感知的前提。',
                '名单模式：BOT_GROUP_DIGEST_LIST_MODE，取值=whitelist|blacklist|off|all，默认空；内容=whitelist 仅名单内群/blacklist 排除名单内群；意义=控制哪些群参与。',
                '名单：BOT_GROUP_DIGEST_WHITELIST / BOT_GROUP_DIGEST_BLACKLIST，取值=数字群号列表（逗号/分号/顿号/空白分隔或 JSON 数组，自动去重，非数字拒绝）；内容=名单生效；意义=精确圈群。',
                '每日通讯总结推送：BOT_GROUP_DIGEST_PUSH_ENABLED（.env 键，true/false，默认 true）＋BOT_GROUP_DIGEST_PUSH_TIME（HH:MM，0-23:0-59，默认 21:30）；内容=每天定时把当日群摘要推给白名单群各一遍（list_mode 非 whitelist 时零推送，绝不猜群）；意义=夜间日报。',
                '衍生键：BOT_GROUP_DIGEST_MAX_TURNS（默认 150）、BOT_GROUP_DIGEST_MAX_CHARS（默认 800）、BOT_GROUP_DIGEST_LLM_ENABLED（默认 false）。',
                '示例：/bot runtime set BOT_GROUP_DIGEST_LIST_MODE whitelist → /bot runtime set BOT_GROUP_DIGEST_WHITELIST 1108838060,1076073471',
            ],
            "detail": (
                '【板块介绍】\n'
                '  群聊上下文摘要（shared_group）：把群内近期对话浓缩成摘要供人格参考；\n'
                '  名单模式决定哪些群参与；每日通讯总结推送（G-DIGEST）在每天固定时刻\n'
                '  把当日摘要主动推回白名单群。\n'
                '【指令与参数】\n'
                'BOT_SHARED_GROUP_CONTEXT_ENABLED：作用=总开关；参数=true/false（默认 false）；内容=关=完全不生成；意义=前提。\n'
                'BOT_GROUP_DIGEST_LIST_MODE：作用=名单模式；参数=whitelist|blacklist|off|all；内容=筛选规则；意义=圈群。\n'
                'BOT_GROUP_DIGEST_WHITELIST/BLACKLIST：作用=名单；参数=群号列表（多分隔符/JSON，去重）；内容=名单；意义=白/黑名单内容。\n'
                'BOT_GROUP_DIGEST_PUSH_ENABLED：作用=每日推送开关；参数=true/false（.env 键，默认 true，不进 runtime set 白名单）；内容=开/关夜间推送；意义=日报总闸。\n'
                'BOT_GROUP_DIGEST_PUSH_TIME：作用=推送时刻；参数=HH:MM（时 0-23 分 0-59，默认 21:30，非法值启动即报错）；内容=调度时刻；意义=错峰推送。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。总开关/名单/模式可 runtime set 热改；推送两键为 .env 键，\n'
                '  改后重启生效。推送正文=一句守岸人引子＋当日摘要；同群同天不重发。\n'
                '【示例】/bot runtime set BOT_GROUP_DIGEST_LIST_MODE whitelist'
            ),
        },
        {
            "topic": '视频理解',
            "admin_only": True,
            "aliases": ('视频理解', '识图', 'vision', '视频'),
            "index": '【视频理解】识图与视频理解开关：BOT_VISION_ENABLED、BOT_VIDEO_UNDERSTANDING_ENABLED',
            "title_line": '【视频理解】图片/表情包识别与视频理解（管理员）',
            "lines": [
                '识图开关：BOT_VISION_ENABLED，取值=true/false，默认 false；内容=开启且注册表有可用模型才调用视觉模型；意义=群里发图能被看懂的前提。',
                '识图模式：BOT_VISION_MODE，取值=relay|direct，默认 direct（relay=视觉模型转文字，direct=图片直传主模型）；内容=识别管线选择；意义=质量与成本取舍。',
                '识图概率：BOT_VISION_REPLY_PROBABILITY，取值=0..1，默认 1.0（发图即识别回应；0=仅 @ 时看图）；内容=识别触发频率；意义=控制打扰与开销。',
                '视频理解：BOT_VIDEO_UNDERSTANDING_ENABLED，取值=true/false，默认 false；内容=开启后视频抽帧＋音轨/字幕生成感知简报，支持追问与深挖；关闭走旧抽帧摘要零额外开销；意义=视频消息的深度理解。',
                '识别模型管理：/bot model vision list|add|update|priority|remove（详见 /bot help 模型）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  识图（vision）：群图片/表情包内容识别；视频理解：视频抽帧＋音轨/字幕\n'
                '  生成感知简报，支持后续追问。两者各有总开关与模型注册表。\n'
                '【指令与参数】\n'
                'BOT_VISION_ENABLED：作用=识图总闸；参数=true/false（默认 false）；内容=开/关；意义=前提。\n'
                'BOT_VISION_MODE：作用=模式；参数=relay|direct（默认 direct）；内容=管线；意义=取舍。\n'
                'BOT_VISION_REPLY_PROBABILITY：作用=回应概率；参数=0..1（默认 1.0）；内容=触发率；意义=降噪。\n'
                'BOT_VIDEO_UNDERSTANDING_ENABLED：作用=视频理解总闸；参数=true/false（默认 false）；内容=开/关；意义=前提。\n'
                'BOT_VIDEO_MAX_FRAMES：作用=抽帧数；参数=正整数（默认 6，0 视同 1）；内容=分析密度；意义=成本。\n'
                'BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE：作用=有 CC 字幕时跳过音轨转写；参数=true/false（默认 true）；内容=管线加速；意义=省时省钱。\n'
                'BOT_VIDEO_FUZZY_FOLLOWUP：作用=模糊追问（“刚才那个讲了什么”）；参数=true/false（默认 true）；内容=追问能力；意义=体验。\n'
                'BOT_VIDEO_DEEP_ENABLED：作用=深挖重分析（“再仔细看看”）；参数=true/false（默认 true）；内容=更多帧＋强制 ASR；意义=深读，耗时更长。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。全部可 /bot runtime set 热改；进度提示（“视频我看一下，\n'
                '  稍等…”）默认开，同会话 60 秒节流（BOT_VIDEO_PROGRESS_ACK_ENABLED）。\n'
                '【示例】/bot runtime set BOT_VISION_MODE relay'
            ),
        },
        {
            "topic": '运行开关',
            "admin_only": True,
            "aliases": ('运行开关', '诊断开关', '持久化开关'),
            "index": '【运行开关】发送队列/审计/回执/诊断持久化：BOT_SEND_QUEUE_ENABLED 等 5 键',
            "title_line": '【运行开关】发送队列、审计、回执、诊断持久化开关（管理员）',
            "lines": [
                'BOT_SEND_QUEUE_ENABLED：作用=发送队列持久化；参数=true/false，默认 false；内容=队列落 sqlite 重启不丢；意义=可靠投递的基础。',
                'BOT_SEND_QUEUE_WORKER_ENABLED：作用=队列后台投递线程；参数=true/false，默认 false；内容=后台按批投递待发消息；意义=不依赖事件触发投递。',
                'BOT_AUDIT_ENABLED：作用=审计落库；参数=true/false，默认 false；内容=/bot audit 可跨重启查询；意义=合规。',
                'BOT_RECEIPTS_ENABLED：作用=回执落库；参数=true/false，默认 false；内容=/bot receipt 跨重启可查；意义=投递追踪。',
                'BOT_DIAGNOSTICS_ENABLED：作用=运行诊断落库；参数=true/false，默认 false；内容=/bot recent 汇总有料；意义=排障。',
                '说明：5 键均为 .env 配置（不在 /bot runtime set 可写集合），改后重启生效。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  五个持久化开关：发送队列、队列后台 worker、审计记录、发送回执、\n'
                '  运行诊断。全部默认关闭；关闭时对应记录仅内存态，重启不保留。\n'
                '【指令与参数】\n'
                'BOT_SEND_QUEUE_ENABLED：作用=发送队列持久化；参数=true/false（默认 false）；内容=队列落 sqlite；意义=可靠投递。\n'
                'BOT_SEND_QUEUE_WORKER_ENABLED：作用=队列后台投递线程；参数=true/false（默认 false）；内容=后台按批投递；意义=投递自动化。\n'
                'BOT_AUDIT_ENABLED：作用=审计落库；参数=true/false（默认 false）；内容=/bot audit 跨重启可查；意义=合规。\n'
                'BOT_RECEIPTS_ENABLED：作用=回执落库；参数=true/false（默认 false）；内容=/bot receipt 跨重启可查；意义=投递追踪。\n'
                'BOT_DIAGNOSTICS_ENABLED：作用=运行诊断落库；参数=true/false（默认 false）；内容=/bot recent 汇总有料；意义=排障。\n'
                '  五键均为 true/false 布尔 .env 键；落库路径由对应 BOT_*_DB_PATH 配置\n'
                '  （留空=内存态）。队列参数另有 BOT_SEND_QUEUE_MAX_ITEMS/MAX_ATTEMPTS/RETRY_* 等键。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。开启后 /bot status 会显示各开关与 store=sqlite/memory 状态。\n'
                '【示例】.env 里 BOT_AUDIT_ENABLED=true 后重启。'
            ),
        },
        {
            "topic": '邮件',
            "admin_only": True,
            "aliases": ('邮件', '电子邮件', 'mail', 'email', '邮箱'),
            "index": '【邮件】Gmail/QQ 收发与发件账户控制（Telegram 管理端）：/mail status|accounts|use|send|pause|resume',
            "title_line": '【邮件】Gmail/QQ IMAP/SMTP 收发与 Telegram 控制',
            "lines": [
                '/mail status：作用=看邮件桥接状态；参数=无；内容=桥接开关、已连接账户、当前发件账户；意义=邮件链路总览。',
                '/mail accounts：作用=列可用账户；参数=无；内容=认证账户与发件别名；意义=选发件身份前先看有什么。',
                '/mail use <发件邮箱>：作用=设默认发件身份；参数=发件邮箱（必填，完整地址且必须已连接或已映射）；内容=切换确认；意义=后续 send 不用每次 --from。',
                '/mail send <收件邮箱> | <主题> | <正文>：作用=发信；参数=收件邮箱（必填，完整地址）＋主题（必填非空）＋正文（必填非空），用 | 分隔三段；内容=发送结果；意义=快速发邮件。',
                '/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>：作用=临时指定发件身份发信；参数=四段（缺一不可）；内容=发送结果；意义=一次借用别的身份。',
                '/mail pause：作用=暂停邮件 AI 自动回复；参数=无；内容=暂停确认（收件提醒继续）；意义=只收不回。',
                '/mail resume：作用=恢复自动回复；参数=无；内容=恢复确认；意义=恢复。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  邮件桥把 Gmail/QQ 邮箱（IMAP/SMTP）接进统一运行时：新邮件提醒、\n'
                '  AI 自动回复、人工发信。控制面在 Telegram 管理端，QQ 侧不受理。\n'
                '【指令与参数】\n'
                '/mail status：作用=看桥接状态；参数=无；内容=开关/账户/发件身份；意义=总览。\n'
                '/mail accounts：作用=列可用账户；参数=无；内容=认证账户与别名；意义=选型。\n'
                '/mail use <发件邮箱>：作用=设默认发件身份；参数=邮箱（必填，须已连接或已映射）；内容=切换确认；意义=免每次 --from。\n'
                '/mail send <收件邮箱> | <主题> | <正文>：作用=发信；参数=三段必填（| 分隔，主题/正文非空）；内容=发送结果；意义=快速发信。\n'
                '/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>：作用=临时身份发信；参数=四段缺一不可；内容=发送结果；意义=借身份。\n'
                '/mail pause：作用=暂停自动回复；参数=无；内容=确认（收件提醒继续）；意义=只收不回。\n'
                '/mail resume：作用=恢复自动回复；参数=无；内容=确认；意义=恢复。\n'
                '【权限与效果】\n'
                '  权限=仅管理员（Telegram 管理端：BOT_TELEGRAM_ADMIN_USER_IDS/CHAT_IDS），\n'
                '  且只能从 Telegram 适配器发送；非管理端执行会收到“仅允许从 Telegram\n'
                '  管理端执行”提示。SMTP/适配器错误只回报类型不回显细节。\n'
                '【示例】/mail send someone@example.com | 测试 | 这是一封测试邮件'
            ),
        },
        {
            "topic": 'Telegram',
            "admin_only": True,
            "aliases": ('telegram', 'tg', '电报', '纸飞机', '飞机'),
            "index": '【Telegram】提醒与远程控制配置：TELEGRAM_BOTS、BOT_TELEGRAM_ADMIN_*',
            "title_line": '【Telegram】新邮件提醒与 Bot 远程控制',
            "lines": [
                'TELEGRAM_BOTS：作用=注册 Telegram Bot；参数=JSON 数组（BotFather Token 列表，至少 1 个才连接）；内容=TG 侧 bot 上线；意义=远程控制入口。',
                'BOT_TELEGRAM_ADMIN_USER_IDS：作用=指定管理员；参数=JSON 字符串数组（user id）；内容=允许执行 /mail 控制的用户；意义=权限边界。',
                'BOT_TELEGRAM_ADMIN_CHAT_IDS：作用=指定提醒接收会话；参数=JSON 字符串数组（chat id）；内容=新邮件提醒推送目标；意义=收提醒。',
                '/bot status、/bot pause|resume：作用=在 TG 侧查看/控制运行时；参数=无；内容=同 QQ 侧；意义=出门在外远程运维。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  Telegram 通道的三大用途：新邮件提醒推送、/mail 邮件控制的管理端、\n'
                '  运行时远程控制（状态/暂停/恢复）。三个 .env 键决定它是否生效。\n'
                '【指令与参数】\n'
                'TELEGRAM_BOTS：作用=注册 Telegram Bot；参数=JSON 数组（BotFather Token 列表，至少 1 个才连接）；内容=TG 侧 bot 上线；意义=远程控制入口。\n'
                'BOT_TELEGRAM_ADMIN_USER_IDS：作用=指定管理员；参数=JSON 字符串数组（user id）；内容=允许执行 /mail 控制的用户；意义=权限边界。\n'
                'BOT_TELEGRAM_ADMIN_CHAT_IDS：作用=指定提醒接收会话；参数=JSON 字符串数组（chat id）；内容=新邮件提醒推送目标；意义=收提醒。\n'
                '  三键均为 .env 键，改后重启生效；/bot status、/bot pause|resume 可在 TG 侧远程执行。\n'
                '【权限与效果】\n'
                '  权限=仅管理员配置可用。\n'
                '【示例】TELEGRAM_BOTS=["123456:ABC-DEF..."]'
            ),
        },
        {
            "topic": '供应商',
            "admin_only": True,
            "aliases": ('供应商', 'provider', 'providers', '模型供应商', '包台'),
            "index": '【供应商】模型分组、优先级与健康检查：BOT_MODEL_REGISTRY、probe_llm_providers.py',
            "title_line": '【供应商】LLM 分组、路由优先级与健康检查',
            "lines": [
                'BOT_MODEL_REGISTRY：作用=.env 里登记 AI API 中转供应商；参数=JSON 对象，每项含 model/base_url/api_key/group/priority；内容=模型注册表底表；意义=静态渠道来源（运行时 add 的条目会与它合并）。',
                'priority：作用=全局尝试顺序；参数=整数 1-999，越小越优先；内容=故障转移次序；意义=便宜稳定的放前面，HCN 保底项放最后。',
                'BOT_CHAT_FAST_MAX_CANDIDATES：作用=快速模式候选上限；参数=0=不限制，1-100=最多尝试数量；内容=候选裁剪；意义=控制快速模式开销。',
                'scripts/probe_llm_providers.py：作用=命令行脱敏探测全部渠道；参数=--max-tokens（可选，1-4096，默认 32）；内容=每模型一次探测结果，不删除配置；意义=批量验收供应商。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  供应商层：.env 静态注册表（BOT_MODEL_REGISTRY）＋运行时动态注册\n'
                '  （/bot model add）合并成统一视图；探测脚本用于离线验收。\n'
                '【指令与参数】\n'
                'BOT_MODEL_REGISTRY：作用=登记中转供应商；参数=JSON 对象（每项 model/base_url/api_key/group/priority）；内容=注册表底表；意义=静态渠道来源。\n'
                'priority：作用=全局尝试顺序；参数=整数 1-999（越小越优先）；内容=故障转移次序；意义=控成本，HCN 保底放最后。\n'
                'BOT_CHAT_FAST_MAX_CANDIDATES：作用=快速模式候选上限；参数=0=不限制，1-100=最多尝试数；内容=候选裁剪；意义=控开销。\n'
                'scripts/probe_llm_providers.py：作用=命令行脱敏探测；参数=--max-tokens（可选，1-4096，默认 32）；内容=每模型一次探测，不删除配置；意义=批量验收。\n'
                '  运行期管理走 /bot model（见「模型」模块）。\n'
                '【权限与效果】\n'
                '  权限=仅管理员。registry 改 .env 后重启生效；运行时条目热生效。\n'
                '【示例】BOT_MODEL_REGISTRY={"myapi":{"model":"deepseek-v4-pro","base_url":"https://api.xxx.com/v1","api_key":"env:MY_KEY","group":"g1","priority":1}}'
            ),
        },
        {
            "topic": '订阅',
            "admin_only": False,
            "aliases": ('订阅', 'subscribe'),
            "index": '【订阅】平台新内容推送：/订阅 add|list|pause|resume|remove',
            "title_line": '【订阅】订阅平台新内容推送',
            "lines": [
                '/订阅 add <公开目标>：作用=添加订阅并推送到当前会话；参数=公开目标（必填，主页链接或 类型:id 字符串，多余参数会被显式拒绝）；内容=订阅已添加：<id>；意义=新内容/开播自动播报；群内 add 需管理员。',
                '/订阅 list：作用=列出订阅；参数=无；内容=本会话目的地下的订阅（id｜平台｜名字｜启用/暂停）；意义=拿 id、看状态；群内仅管理员可看本群订阅。',
                '/订阅 pause|resume <id>：作用=暂停/恢复订阅；参数=id（必填，来自 list）；内容=已暂停/已恢复（仅本目的地）；意义=临时静默不删订阅。',
                '/订阅 remove <id>：作用=删除订阅；参数=id（必填）；内容=已删除（其他群的目的地不受牵连，最后一个目的地移除才整条删）；意义=退订。',
                '权限=全员自助；群内 add/list 需管理员，pause/resume/remove 群内需管理员且订阅推往本群，私聊需推给自己。',
                '目标示例：https://space.bilibili.com/123456｜bilibili:up:123456｜youtube:live:<频道ID或@handle>｜xiaohongshu:column:<用户ID>｜music.163.com/playlist?id=xxx',
                '支持范围：B站（UP主/直播间/番剧/收藏夹/合集）、小红书（图文/专栏/直播）、YouTube（频道/播放列表/直播）、微博、推特、Pixiv、Telegram 频道、音乐平台（网易云/QQ/酷狗/酷我/Apple/Spotify 的歌手/专辑/歌单）；建议直接粘贴主页或链接。',
                '/订阅 与 /bot subscribe 等价。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  订阅运行时按目标平台轮询新内容（视频/动态/直播开播/新歌），经统一\n'
                '  发送管线推送。订阅目的地绑定“添加时的会话”：群里添加=推本群，\n'
                '  私聊添加=推给你本人。\n'
                '【指令与参数】\n'
                '/订阅 add <公开目标>：作用=添加；参数=目标必填（链接或 类型:id；目的地/日报等附加参数暂不支持，写了会被拒绝并提示）；内容=添加确认；意义=订阅入口。\n'
                '/订阅 list：作用=列表；参数=无；内容=订阅清单；意义=管理前置。\n'
                '/订阅 pause <id>：作用=暂停；参数=id 必填；内容=暂停确认（只暂停本会话目的地）；意义=临时静默。\n'
                '/订阅 resume <id>：作用=恢复；参数=id 必填；内容=恢复确认；意义=复播。\n'
                '/订阅 remove <id>：作用=删除；参数=id 必填；内容=删除确认；意义=退订；重加已存在订阅不会把管理员暂停的订阅悄悄重启。\n'
                '【权限与效果】\n'
                '  权限=全员自助；群内 add/list 需要管理员（add 会向全群推送外部内容，无门槛=投毒面）；\n'
                '  私聊自助。pause/resume/remove 的目的地粒度：只影响本群/本人，别的群\n'
                '  订同一条不受影响。\n'
                '【示例】/订阅 add https://space.bilibili.com/123456'
            ),
        },
        {
            "topic": '点歌',
            "admin_only": False,
            "aliases": ('点歌', 'music', '點歌', 'song'),
            "index": '【点歌】搜索并发送歌曲：点歌 <歌名>｜点歌 <编号>｜点歌模式 <部件组合>',
            "title_line": '【点歌】搜索并发送歌曲',
            "lines": [
                '点歌 <歌名>：作用=按平台顺序搜索并发送；参数=歌名或关键词（必填，中英文均可；#歌名=强制按歌名搜索的转义写法）；内容=平台音乐卡片（无卡则封面图）等部件；意义=群内点播。',
                '点歌 <编号>：作用=同名多候选时二次选择；参数=编号（必填，来自候选列表，默认最多 5 个）；内容=选中歌曲；意义=精确选版本；仅紧随候选列表、默认 300 秒内有效，过期会提示重新点歌。',
                '点歌模式 <模式>：作用=设置输出方式；参数=模式（卡片|语音|音频|链接|全部，可组合如 卡片+语音，中英文别名均可）；内容=模式持久化确认；意义=控制输出形态；仅管理员，持久保存。',
                '平台：网易云/酷我/酷狗/QQ音乐/Apple Music/Spotify 顺序尝试，单平台取第一名，失败自动换下一个。',
                '示例：点歌 晴天｜候选出来后回复「点歌 2」｜点歌模式 卡片+语音',
            ],
            "detail": (
                '【板块介绍】\n'
                '  纯接口搜索不调 LLM；输出部件可拆可组：card=平台音乐卡片（默认）、\n'
                '  voice=语音、file=音频文件、link=文本链接。多候选交互需开启\n'
                '  BOT_MUSIC_CANDIDATES_ENABLED（默认关）：同名歧义返回编号列表，\n'
                '  有效期 BOT_MUSIC_CANDIDATES_TTL_SECONDS（默认 300 秒，下限 30），\n'
                '  候选数 BOT_MUSIC_CANDIDATES_LIMIT（默认 5，下限 2）。\n'
                '【指令与参数】\n'
                '点歌 <歌名>：作用=搜索发送；参数=歌名必填；内容=按当前模式的部件组合；意义=核心玩法。查询词与模式别名同名（如「点歌 link」）会得到冲突提示与转义用法，不再静默丢弃。\n'
                '点歌 <编号>：作用=候选选择；参数=编号必填；内容=歌曲；意义=选版本；过期/无效编号会明确提示重新点歌，不会拿数字当歌名再搜一遍。\n'
                '点歌模式 [模式]：作用=查/设输出方式；参数=模式（卡片|语音|音频|链接|全部，支持 +/和/与 组合词；省略=查当前模式）；内容=当前或新模式的部件清单；意义=输出定制。\n'
                '【权限与效果】\n'
                '  点歌=全员；点歌模式=仅管理员（写入 BOT_MUSIC_MODE 持久化）。\n'
                '【常见错误】编号只在候选列表有效期内有效；直接拿数字当歌名搜索不是有效歌名。\n'
                '【示例】点歌 晴天｜点歌 2｜点歌模式 卡片+语音'
            ),
        },
        {
            "topic": '表情',
            "admin_only": False,
            "aliases": ('表情', 'meme', '表情包', '表情生成'),
            "index": '【表情】生成文字表情：表情 <模板> <文字>｜表情 列表',
            "title_line": '【表情】生成文字表情',
            "lines": [
                '表情 <模板> <文字>：作用=套模板生成表情图；参数=模板名（必填）＋文字（按模板要求，多段用 ｜ 分隔）；内容=生成的表情图；意义=玩梗输出；需要图片的模板发图或 @ 群友后输命令，不带图用你的头像。',
                '表情 列表：作用=列出全部模板；参数=无；内容=可用模板 key 清单；意义=先查再玩。',
                '表情帮助：作用=用法说明；参数=无；内容=完整用法；意义=入门。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  对接本地 meme-generator-rs HTTP API（默认 http://127.0.0.1:2233）。\n'
                '  未安装/未启动服务时能力不可用。总开关 BOT_MEME_COMMAND_ENABLED。\n'
                '【指令与参数】\n'
                '表情 <模板> [文字]：作用=生成；参数=模板 key 必填；文字按模板 min_texts/max_texts 要求，多段用全角 ｜ 分隔；内容=表情图；意义=梗图。纯 key 无文字时按模板的最少文字数判断是零文字模板还是打错 key。\n'
                '表情 列表：作用=列模板；参数=无；内容=模板清单；意义=发现。\n'
                '表情帮助：作用=说明；参数=无；内容=用法；意义=自助。\n'
                '【权限与效果】\n'
                '  权限=全员。\n'
                '【示例】表情 petpet 可爱｜表情 文字表情 早上好｜晚上好'
            ),
        },
        {
            "topic": '偷表情',
            "admin_only": False,
            "aliases": ('偷表情', '偷表情包', 'steal'),
            "index": '【偷表情】表情库随机：偷表情 [关键词]｜表情库统计',
            "title_line": '【偷表情】从表情库随机抽取',
            "lines": [
                '偷表情 [关键词]：作用=按权重随机发一张入库表情；参数=关键词/情绪标签（可选，命中描述/情绪/场景标签）；内容=表情图；意义=表情包补给；写「私聊/私聊我」等同不填关键词但改为私聊发送。',
                '表情库统计：作用=看库存；参数=无；内容=数量与来源分布；意义=摸底。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  表情库由群图片自动吸收（VLM 打标、NSFW≥0.2 降权、≥0.8 永不发送）。\n'
                '  权重：守岸人/岸宝最优先，其次鸣潮/战双/库洛，再次 ACG，最后普通。\n'
                '  冷却 BOT_MEME_LIBRARY_COOLDOWN_SECONDS（默认 20 秒）防刷屏；总开关\n'
                '  BOT_MEME_LIBRARY_ENABLED（默认 false，需开启）。\n'
                '【指令与参数】\n'
                '偷表情 [关键词]：作用=随机抽取；参数=关键词可选；内容=表情图；意义=氛围担当。bot 心情低落时对“吵闹”标签候选有限重抽（软偏置，不硬开关）。\n'
                '表情库统计：作用=统计；参数=无；内容=库存概览；意义=盘点。\n'
                '【权限与效果】\n'
                '  权限=全员。\n'
                '【示例】偷表情｜偷表情 猫猫'
            ),
        },
        {
            "topic": '搜图',
            "admin_only": False,
            "aliases": ('搜图', '以图搜图'),
            "index": '【搜图】图片反搜来源：搜图 ＋图片/@图片',
            "title_line": '【搜图】SauceNAO 图片反搜',
            "lines": [
                '搜图 ＋图片：作用=反搜图片来源；参数=图片（同一条消息带图或 @ 一张图；引用消息拿不到原图会明确提示）；内容=SauceNAO 匹配结果（相似度/来源链接）；意义=找画师/找出处。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  调 SauceNAO 对图片做来源反搜。图片 URL 从消息图片段提取；\n'
                '  引用消息里的原图链接拿不到时会提示把图片和「搜图」发在同一条消息。\n'
                '【指令与参数】\n'
                '搜图 [图片]：作用=反搜；参数=图片段（必传，命令后不带参数，图片在同一条消息里）；内容=匹配结果；意义=溯源。\n'
                '【权限与效果】\n'
                '  权限=全员。未配 SauceNAO key 或无结果时有降级提示。\n'
                '【示例】（发一张图＋文字）搜图'
            ),
        },
        {
            "topic": '天气',
            "admin_only": False,
            "aliases": ('天气', 'weather'),
            "index": '【天气】查询城市/区县天气：天气 <城市>｜支持区县 <省>',
            "title_line": '【天气】查询城市与区县天气',
            "lines": [
                '天气 <城市>：作用=查天气；参数=城市名（必填，≤20 字且要像地名；同名城市用 省-市 区分，如 浙江-杭州）；内容=当前天气＋预报卡（中国气象局 NMC 免 key，Open-Meteo 兜底）；意义=出行参考。',
                '支持区县 <省>：作用=列出可查区县；参数=省名（必填）；内容=该省区县码表清单；意义=查县级精细天气前的发现入口。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  数据源：中国气象局 NMC（免 key，内置 2527 个区县码表），失败时\n'
                '  Open-Meteo 兜底；渲染可用时输出 Mica 天气卡。触发收窄：查询词需像\n'
                '  地名——长度受限、不以「今天/真好/怎么样」等口语词开头、不以语气词\n'
                '  收尾，所以「天气真好」不会误触发。\n'
                '【指令与参数】\n'
                '天气 <城市>：作用=查询；参数=城市或 省-市/省-县（必填，≤20 字）；内容=天气报告卡；意义=日常查询。\n'
                '支持区县 <省>（别名 查询区县/可查区县）：作用=列区县；参数=省名必填；内容=区县列表；意义=发现可查的县级地名。\n'
                '【权限与效果】\n'
                '  权限=全员。自然语言「帮我查杭州天气」经意图归一化同样命中。\n'
                '【示例】天气 上海｜天气 河北-大城｜支持区县 浙江'
            ),
        },
        {
            "topic": '行情',
            "admin_only": False,
            "aliases": ('行情', 'market', '股指', '大盘', '美股行情', '港股行情', 'A股行情'),
            "index": '【行情】全球股指：行情 或 美股行情/港股行情/A股行情/B股行情/莫斯科行情…',
            "title_line": '【行情】全球主要股指行情',
            "lines": [
                '行情：作用=全球主要指数一览；参数=无；内容=中国区/亚太/欧美指数一览（点位/涨跌幅）；意义=一眼看盘。',
                '行情 + 市场词：作用=只看指定市场；参数=市场词（写在同一句话里，可多个取并集）：A股/B股/上证B/深证B/美股/港股/恒生/日经/纳斯达克/纳指/道琼斯/道指/标普/韩/新加坡/印度/台湾/台股/英国/富时/法国/德国/莫斯科/俄罗斯；内容=对应指数；意义=聚焦关注的市场。过滤词没命中任何指数时回退全部。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  数据来自东方财富 push2 免费接口（免 key），进程内 60 秒缓存，\n'
                '  失败降级为「晚点再试」。触发收窄：≤32 字、不带链接（带链接走解析）、\n'
                '  房价/基金/币圈/显卡/期货/汇率等非股市“行情”自动让路。\n'
                '【指令与参数】\n'
                '行情 [市场词…]：作用=查指数；参数=市场词可选（A股/B股/上证B/深证B/美股/港股/恒生/日经/纳斯达克/纳指/道琼斯/道指/标普/韩/新加坡/印度/台湾/台股/英国/富时/法国/德国/莫斯科/俄罗斯，多词取并集）；内容=指数清单；意义=盘面速览。\n'
                '【权限与效果】\n'
                '  权限=全员。B 股与莫斯科（IMOEX）指数已上线。\n'
                '【示例】行情｜A股行情｜B股行情｜莫斯科行情'
            ),
        },
        {
            "topic": '占卜',
            "admin_only": False,
            "aliases": ('占卜', '塔罗', '八字', '算命', '算卦', '起卦'),
            "index": '【占卜】八字排盘/塔罗/金钱卦（含地支藏干）：占卜 | 塔罗 三张 | 八字 1998年3月2日早上7点',
            "title_line": '【占卜】玄学娱乐三件套',
            "lines": [
                '占卜 / 起卦 / 算卦 / 摇卦：作用=金钱卦六掷成卦；参数=无；内容=本卦＋变卦（老爻自动变）；意义=一事一问的娱乐向卜卦。',
                '塔罗：作用=单张指引；参数=无；内容=单张牌＋解读；意义=快问快答。',
                '塔罗 三张：作用=牌阵；参数=无（触发词：三张/过去现在未来/牌阵）；内容=过去/现在/未来三张牌阵；意义=看脉络。',
                '塔罗 每日一抽：作用=今日牌；参数=无（触发词：每日一抽/今日塔罗/今天塔罗）；内容=今日固定牌（同一天同一人不变）；意义=日签。',
                '八字 / 排盘 <生日时间>：作用=四柱排盘；参数=生日时间（可选，如「八字 1998年3月2日早上7点」；日期支持 1998年3月2日/1998-03-02/1998/3/2；时辰支持 早上7点/晚上9点05分/21:51/早上7点半 等，只给日期按午时 12:00 排，不给日期按当前时点排）；内容=四柱排盘＋地支藏干（逐柱本气/中气/余干与权重）＋藏干五行加权统计＋免责尾注；意义=传统命理娱乐；支持 1900-2100 年。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  玄学娱乐三件套：金钱卦（六十四卦）、塔罗（单张/三张/每日一抽）、\n'
                '  八字排盘（含地支藏干）。纯本地计算无网络；输出为娱乐向文本并附\n'
                '  免责尾注，不含医疗/投资等严肃建议。\n'
                '【指令与参数】\n'
                '占卜|起卦|算卦|摇卦|六十四卦|金钱卦：作用=起卦；参数=无；内容=卦象＋变卦；意义=卜问。\n'
                '塔罗 [玩法]：作用=抽牌；参数=无=单张｜三张/牌阵=三张牌阵｜每日一抽/今日塔罗=日签（按 日期+用户 哈希同日固定）；内容=牌面与解读；意义=指引娱乐。\n'
                '八字|排盘|四柱|命盘|算命|生辰 [生日时间]：作用=排盘；参数=生日时间可选（日期三种写法；时辰词归一化：下午/晚上/夜里/深夜 +12、凌晨12点=0点、中午=12 点；默认午时；缺省当前时点并附提示）；内容=四柱＋藏干（本气/中气/余干与通行子平权重，单支合计 100）＋藏干五行加权汇总＋尾注；意义=深度排盘。\n'
                '【取值范围】\n'
                '  可排盘区间 1900-2100 年；超出会优雅提示换时间。日期解析失败会给出\n'
                '  可读错误与示例，不静默忽略。\n'
                '【权限与效果】\n'
                '  权限=全员，纯娱乐。\n'
                '【示例】占卜｜塔罗 三张｜塔罗 每日一抽｜八字 1998年3月2日早上7点'
            ),
        },
        {
            "topic": '快报',
            "admin_only": False,
            "aliases": ('快报', '今日快报', '早报', '晚报', '今日热点', '科技新闻', 'AI新闻', '财经快报', '国际新闻'),
            "index": '【快报】今日新闻快报：快报 或 科技新闻/AI新闻/财经快报/国际新闻',
            "title_line": '【快报】今日新闻快报',
            "lines": [
                '快报 / 早报 / 晚报 / 今日热点：作用=综合快报；参数=无；内容=8 条混合头条（科技/财经/国际轮转）；意义=每日资讯入口。',
                '科技新闻 / AI新闻 / AI快报：作用=科技类目；参数=无；内容=科技/AI 类头条；意义=技术动向。',
                '财经新闻 / 财经快报：作用=财经类目；参数=无；内容=财经头条；意义=市场动向。',
                '国际新闻：作用=国际类目；参数=无；内容=国际头条；意义=世界动向。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  国内可达 RSS 聚合（IT之家/少数派/华尔街见闻/BBC 中文），进程内\n'
                '  10 分钟缓存，单源失败静默跳过；抓取为空给降级文案不阻塞会话。\n'
                '【指令与参数】\n'
                '快报 [类目词]：作用=取快报；参数=类目词写在同一句话里：财经→finance、国际→world、科技/AI/人工智能→tech、其余→mix 轮转；内容=8 条标题＋来源＋链接；意义=资讯。\n'
                '【取值范围】\n'
                '  只认显式触发词（快报/早报/晚报/今日热点/类目词×新闻|快报/AI快报），\n'
                '  ≤32 字、不带链接；裸「新闻」不触发（留给联网搜索链路），句子带\n'
                '  搜索/搜一下/查一下/找新闻/联网/上网 时让路。\n'
                '【权限与效果】\n'
                '  权限=全员。\n'
                '【示例】快报｜科技新闻｜财经快报｜国际新闻'
            ),
        },
        {
            "topic": '维基',
            "admin_only": False,
            "aliases": ('维基', 'wiki', '百科'),
            "index": '【维基】查询百科词条：维基 <词条>',
            "title_line": '【维基】查询百科词条',
            "lines": [
                '维基 <词条>：作用=查 MediaWiki 百科；参数=词条名（必填，省略回用法）；内容=词条摘要（游戏类词条自动精简）；意义=快速百科查询。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  纯 MediaWiki 公开 API（免 key），默认中文维基（BOT_WIKI_LANG 可切），\n'
                '  支持独立页缺失时的精确列表条目提取（BOT_WIKI_ENTRY_PAGES，默认\n'
                '  鳴潮角色列表，最多优先 3 页）。\n'
                '【指令与参数】\n'
                '维基 <词条>：作用=查询；参数=词条名必填；内容=摘要或未找到提示（含可能原因）；意义=知识速查。\n'
                '【权限与效果】\n'
                '  权限=全员。查不到时会说明是独立页缺失、列表条目缺失还是网络失败。\n'
                '【示例】维基 量子力学｜维基 鸣潮守岸人'
            ),
        },
        {
            "topic": '萌娘百科',
            "admin_only": False,
            "aliases": ('萌娘百科', '萌百', 'moegirl'),
            "index": '【萌娘百科】查询萌娘百科：萌娘百科 <词条>｜直接问 XX是谁',
            "title_line": '【萌娘百科】查询萌娘百科词条',
            "lines": [
                '萌娘百科 <词条>：作用=查萌百词条；参数=词条名（必填）；内容=词条摘要；意义=二次元知识库。',
                '直接问「XX是谁/是什么/介绍一下」：作用=实体问句自动查萌百；参数=实体名（2-30 字，剥掉问句后）；内容=萌百摘要；意义=自然问法直达；查不到时无感转人格聊天回答。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  萌百 MediaWiki 公开 API。两条路径：显式指令；以及二次元实体问句\n'
                '  自动查询（群聊不 @ 不抢答，与聊天同门控；BOT_MOEGIRL_QUESTION_ENABLED\n'
                '  可关）。问句剥离后剩人称代词（你/我/谁…）、过短/过长、含链接的\n'
                '  一律不查，交给聊天链路。\n'
                '【指令与参数】\n'
                '萌娘百科 <词条>：作用=显式查询；参数=词条名必填；内容=摘要；意义=定向。\n'
                '「XX是谁？」式问句：作用=自动查询；参数=实体名（从问句剥离，2-30 字）；内容=命中=萌百摘要，未命中=人格聊天兜底；意义=无门槛问询。\n'
                '【权限与效果】\n'
                '  权限=全员。\n'
                '【示例】萌娘百科 初音未来｜初音未来是谁？'
            ),
        },
        {
            "topic": '历史上的今天',
            "admin_only": False,
            "aliases": ('历史上的今天', 'today', '今日'),
            "index": '【历史上的今天】每日历史推送：立即查 | 设置 HH:MM | 状态 | 取消',
            "title_line": '【历史上的今天】每天定时推送历史',
            "lines": [
                '历史上的今天：作用=立即查询当天历史；参数=无；内容=当天历史事件清单；意义=即查即看。',
                '历史上的今天 设置 <HH:MM>：作用=设置每日推送时间；参数=时间（必填，HH:MM 24 小时制，取值 00:00-23:59）；内容=设置确认；意义=每天定时收到；群内需管理员（影响全群），私聊自助。',
                '历史上的今天 状态：作用=查看推送状态；参数=无；内容=当前推送时间或未设置；意义=核对。',
                '历史上的今天 取消：作用=取消每日推送；参数=无；内容=取消确认；意义=退订；群内需管理员。',
                '短别名：/历史、/今日历史（带斜杠，避免把聊天里的“历史”误触发）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  数据源百度百科公开接口（带缓存与代理支持）。推送订阅按会话存\n'
                '  data/today_history_push.json（私聊 f_<user_id>、群聊 g_<group_id>），\n'
                '  由调度器按表注册每日任务。\n'
                '【指令与参数】\n'
                '历史上的今天：作用=查询；参数=无；内容=当天历史；意义=即时消费。\n'
                '历史上的今天 设置 <HH:MM>：作用=设每日推送；参数=HH:MM（24 小时制，冒号可用：）；内容=确认；意义=定时触达。\n'
                '历史上的今天 状态：作用=查状态；参数=无；内容=推送时间；意义=核对。\n'
                '历史上的今天 取消：作用=退订；参数=无；内容=确认；意义=退订。\n'
                '【权限与效果】\n'
                '  权限=全员查询；设置/取消在群聊需要管理员（推送时间影响全群），\n'
                '  私聊自助。订阅表损坏时会拒绝改写以保护其他会话的订阅。\n'
                '【示例】历史上的今天 设置 08:30'
            ),
        },
        {
            "topic": '下载',
            "admin_only": False,
            "aliases": ('下载', 'download'),
            "index": '【下载】下载视频/音频：/bot download <链接> 或 下载 <链接>',
            "title_line": '【下载】下载视频/音频',
            "lines": [
                '/bot download <链接>：作用=下载媒体并回传文件；参数=链接（必填，http(s) 开头；B站/油管/推特/小红书/抖音等）；内容=文字摘要（标题/大小/分辨率/时长/画质标注）＋视频文件段；意义=把在线视频搬进群。',
                '限制：单文件 ≤1GB（超限自动降清晰度至最高 8K 上限内）；拒绝非 http(s) 与内网/保留地址（含 DNS 解析后的私网 IP）；依赖 yt-dlp。',
                '权限=全员（H6 定案：产品开放给普通用户，安全边界由 downloader 侧承担）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  yt-dlp 下载到 data/downloads/ 并做媒体分析，经发送管线回传文件段。\n'
                '  cookies（/bot cookie import）与代理（BOT_DOWNLOAD_PROXY）对下载同样生效。\n'
                '【指令与参数】\n'
                '/bot download <链接>（别名：下载 <链接>）：作用=下载；参数=URL 必填；内容=摘要＋文件；意义=核心功能。\n'
                '【取值范围】\n'
                '  大小上限 BOT_DOWNLOAD_MAX_BYTES（默认 1073741824=1GB）；最大高度\n'
                '  BOT_DOWNLOAD_MAX_HEIGHT（默认 0=不限制，超限自动降级）；超时\n'
                '  BOT_DOWNLOAD_TIMEOUT_SECONDS（默认 120 秒，发送侧最长 300 秒）。\n'
                '【权限与效果】\n'
                '  权限=全员。失败优雅降级为文字（只说原因类型，不泄露堆栈与 cookie）。\n'
                '【示例】/bot download https://www.bilibili.com/video/BVxxxxxxxx'
            ),
        },
        {
            "topic": '昵称',
            "admin_only": False,
            "aliases": ('昵称', 'alias'),
            "index": '【昵称】角色昵称触发命令：守岸人/岸宝 <命令>',
            "title_line": '【昵称】用角色昵称触发命令',
            "lines": [
                '/<昵称><命令>：作用=用昵称代替 /bot 前缀触发命令；参数=命令名（必填，如 帮助/状态/为什么/天气/点歌/订阅/日志/清理历史/暂停/继续，斜杠可省略）；内容=同对应命令；意义=角色扮演的日常用法。可用昵称经 /bot runtime nickname 维护。',
                '模块/动作词归一：模型=model、设置=runtime、帮助=help、维基=wiki；查看/列表=list、切换=set、用量=usage、思考=think 等动词自动映射。',
                '昵称命令受限：部分管理命令（如日志/记忆）会要求回落到 /bot 形式执行。',
                '管理员另可用 /bot 昵称 set <QQ号> <小名>（5-11 位数字＋1-32 字小名）为群友记小名，用于好感度称呼。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  昵称命令层：把「/岸宝帮助」「守岸人 状态」解析成对应能力。昵称清单\n'
                '  存运行时设置（BOT_PERSONA_NICKNAMES / runtime nickname 维护），\n'
                '  未配置时别名层关闭；标准 /bot 前缀不受影响。\n'
                '【指令与参数】\n'
                '/<昵称><命令> [参数]：作用=触发；参数=命令动词（帮助/help、状态/status、为什么/why、记忆/memory、配置/config、就绪/readiness、人格/persona、对话验收/dialogue、角色/roles、清理历史/历史、暂停/pause、继续/resume、天气、点歌、点歌模式、epic、吃什么/菜谱、历史上的今天、好感度、订阅、日志、偷表情、表情库统计、维基…）；内容=对应命令的输出；意义=顺口。\n'
                '/bot 昵称 set <QQ号> <小名>：作用=记小名；参数=QQ 号（5-11 位数字）＋小名（1-32 字）；内容=确认；意义=好感度与称呼个性化（仅管理员）。\n'
                '【权限与效果】\n'
                '  权限=触发本身全员；各命令自身的权限照旧生效。\n'
                '【示例】/岸宝帮助｜守岸人 天气 上海｜/岸宝点歌 晴天'
            ),
        },
        {
            "topic": '链接',
            "admin_only": False,
            "aliases": ('链接', 'links'),
            "index": '【链接】自动解析：直接发平台链接即可',
            "title_line": '【链接】平台链接自动解析信息卡',
            "lines": [
                '直接发链接：作用=自动解析成信息卡；参数=URL（消息里含 http(s) 链接即触发，无需命令词）；内容=平台信息卡（标题/作者/数据/封面，GitHub 仓库出星标/Fork/简介/README 摘要）；意义=不用打开 App 就知道链接里是什么。',
                '支持平台：B站/抖音/小红书/油管/推特/小黑盒/米游社/森空岛/库街区/Lofter/Pixiv/GitHub/音乐平台等；长视频走视频理解可追问。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  链接解析在路由优先级 46：只要文本含 http(s) 链接且未命中更高优先级\n'
                '  命令（如 /bot download、订阅），就走解析器组出信息卡。\n'
                '【指令与参数】\n'
                '发链接（无命令词）：作用=解析；参数=URL（1 条或多条，取第一个）；内容=信息卡/摘要；意义=内容预览。\n'
                '【权限与效果】\n'
                '  权限=全员。相关平台需要登录态时用 /bot cookie import 补 cookie。\n'
                '【示例】直接粘贴 https://www.bilibili.com/video/BVxxxx'
            ),
        },
        {
            "topic": '草稿',
            "admin_only": False,
            "aliases": ('草稿', 'autosend', '自动发送'),
            "index": '【草稿】自然语言起草自动发送：报存 给 <收件人> 发消息|邮件，内容…',
            "title_line": '【草稿】自然语言起草自动发送',
            "lines": [
                '报存 给 <收件人> 发消息，内容…：作用=起草聊天消息草稿；参数=收件人（必填，可用 、,， 分隔多个）＋内容要求（可选，支持 主题：… 内容：… 结构）；内容=草稿预览（通道/收件人/主题/内容要求）；意义=把“要发什么”先落成结构化草稿。',
                '报存 给 <收件人> 发邮件，主题：<主题>，内容：<正文>：作用=起草邮件；参数=收件人（必填）＋主题（可选）＋内容（可选）；内容=草稿预览（M0 仅预览不真实发送）；意义=邮件起草。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  自动发送子系统的入口：解析成结构化意图（通道/收件人/主题/正文）并\n'
                '  输出预览。当前版本只做预览（confirm_required），不真实发送。\n'
                '【指令与参数】\n'
                '报存 给 <收件人> 发消息|邮件 [，内容要求]：作用=起草；参数=收件人必填（多个用 、,， 分隔）；「主题：」段作为邮件主题；「内容」后的文本作为正文要求；内容=草稿预览卡；意义=规划待发内容。\n'
                '【权限与效果】\n'
                '  权限=全员（预览无副作用）。邮件通道风险级高于普通消息。\n'
                '【示例】报存 给小明、小红 发邮件，主题：周末聚餐，内容：周六晚上六点老地方见'
            ),
        },
        {
            "topic": '吃什么',
            "admin_only": False,
            "aliases": ('吃什么', '吃啥', '菜谱'),
            "index": '【吃什么】随机推荐家常菜/查菜谱：吃什么 | 吃什么 三选一 | 菜谱 番茄炒蛋',
            "title_line": '【吃什么】解决选择困难',
            "lines": [
                '吃什么：作用=随机推荐 1 道家常菜；参数=无；内容=Mica 菜品卡（名字/口味/食材/做法，本地图包有图上卡）；意义=治今天吃什么。',
                '吃什么 三选一 / 来三道 / 再来一道：作用=控制数量与换一批；参数=修饰词（三选一|来三道|再来一道|再来）；内容=3 道不同菜或补一道；意义=选择困难加倍版。',
                '吃什么 辣的 / 不辣 / 微辣 / 中辣 / 特辣：作用=按辣度过滤；参数=辣度词；内容=过滤后的推荐；意义=口味适配。',
                '菜谱 <菜名> / 怎么做 <菜名> / 如何做 <菜名>：作用=查做法；参数=菜名（必填）；内容=食材＋步骤卡；意义=照着做。',
                '带忌口/食材/人数约束（如「不吃香菜 有鸡蛋 两人吃」）自动走 AI 生成菜谱；菜品图片放 Runtime data/food_images/<菜名>.jpg|.png|.webp 即可上卡。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  本地菜品库随机推荐＋AI 约束生成双层：命中修饰/约束词表走过滤或 AI，\n'
                '  否则纯随机。推荐与菜谱渲染 Mica 卡图（含本地封面），失败回退文本。\n'
                '【指令与参数】\n'
                '吃什么 [修饰/约束]：作用=推荐；参数=修饰词（三选一/来三道/再来一道/再来/辣的/不辣/微辣/中辣/特辣）或约束描述（不吃/不要/忌口/过敏/有/加/N人/清淡/减脂…）；内容=菜品卡；意义=选菜。\n'
                '菜谱 <菜名>（别名 怎么做/如何做）：作用=查做法；参数=菜名必填；内容=食材与步骤；意义=烹饪指引。\n'
                '【权限与效果】\n'
                '  权限=全员。普通闲聊（吃了吗/吃火锅）不会被误判成点菜。\n'
                '【示例】吃什么｜吃什么 三选一｜吃什么 不辣 有鸡蛋｜菜谱 番茄炒蛋'
            ),
        },
        {
            "topic": '好感度',
            "admin_only": False,
            "aliases": ('好感度', '好感查看', '查询好感'),
            "index": '【好感度】双向好感与算法：好感度｜好感度 我｜好感度 算法',
            "title_line": '【好感度】守岸人与你的双向好感',
            "lines": [
                '好感度：作用=查好感；参数=无；内容=私聊=双向好感卡；群聊=本群好感榜（有印象成员，自己高亮，展示前 12/上限 60）；意义=关系可视化。',
                '好感度 我：作用=只看自己；参数=我（别名 自己/me）；内容=双向分值；意义=群里不想看榜时用。',
                '好感度 算法：作用=说明规则；参数=算法（别名 说明/规则/help）；内容=图文算法卡＋你与守岸人之间的氛围画像；意义=透明化。',
                '计分（v5 定性版）：好感随言行连续累积——综合说话的温度、相处的时间、第一印象、当天状态平滑变化，没有固定加几减几；同一天同类言行影响递减；久不联系慢慢回到基准；难听的记忆随时间淡去。',
                '档位：初识/生疏/微凉/稍淡/友善（基准）/亲近/挚友/独一份 共八档，连续过渡、不在门槛上生硬跳变；任何档位都不强硬、不辱骂、不弃聊。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  双向好感体系：守岸人对你=印象好感度（-100~+100）；你对守岸人=你\n'
                '  表达中友好成分的加权占比（估算）。好感档位只影响语气与距离感，\n'
                '  不改变安全边界。\n'
                '【指令与参数】\n'
                '好感度：作用=查好感；参数=无；内容=双向卡或群榜；意义=关系可视化。\n'
                '好感度 我|自己|me：作用=只看自己；参数=任选其一；内容=双向分值；意义=隐私。\n'
                '好感度 算法|说明|规则|help：作用=算法说明；参数=任选其一；内容=规则＋档位态度对照＋你与守岸人之间的氛围画像（定性描述，不展示具体加减数值）；意义=透明。\n'
                '【权限与效果】\n'
                '  权限=全员。好感度功能总开关 bot_affinity_enabled。\n'
                '【示例】好感度｜好感度 我｜好感度 算法'
            ),
        },
        {
            "topic": 'Epic',
            "admin_only": False,
            "aliases": ('epic', 'epicfree', 'epic free', 'epic 免费', '免费游戏'),
            "index": '【Epic】每周免费游戏：epic 或 Epic 免费',
            "title_line": '【Epic】查询每周免费游戏',
            "lines": [
                'epic / epicfree / Epic 免费 / 免费游戏 / steam免费：作用=查本周限免；参数=无；内容=Epic 每周限免＋Steam 100% 折扣限免合并清单（标题/截止/链接，Mica 卡图）；意义=白嫖情报。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  聚合 Epic 公开接口与 Steam 限免，渲染可用时输出 Mica 信息卡，\n'
                '  文本作兜底。\n'
                '【指令与参数】\n'
                'epic（别名 epicfree/epic free/epic 免费/免费游戏/游戏免费/steam免费/steam free/steamfree）：作用=查询；参数=无；内容=本周免费游戏清单；意义=情报。\n'
                '【权限与效果】\n'
                '  权限=全员。\n'
                '【示例】epic'
            ),
        },
        {
            "topic": '随机图',
            "admin_only": False,
            "aliases": ('随机图', '来张图', 'randpic'),
            "index": '【随机图】从图库随机发一张：随机图 / 来张图',
            "title_line": '【随机图】图库随机发图',
            "lines": [
                '随机图 / 来张图：作用=从你配置的图库文件夹随机发一张图；参数=无；内容=一张图片（jpg/jpeg/png/gif/webp/bmp，单张 ≤20MB）；意义=自建图库的抽卡玩法。',
                '配置：图库目录写在 BOT_RANDPIC_DIRS（可多个、递归扫描、只读绝不自建目录）；触发词可用 BOT_RANDPIC_TRIGGER_WORDS 换成自己的（默认 随机图/来张图）。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  借鉴 nonebot-plugin-randpic 的“指令→随机图”玩法但只吸收思路：\n'
                '  不建目录、不建数据库、不做上传，一把随机梭哈。目录清单 30 秒 TTL\n'
                '  缓存，改文件夹半分钟内生效。\n'
                '【指令与参数】\n'
                '随机图|来张图：作用=发图；参数=无（触发词后跟标点/语气词也可命中；「随机图片库」这类包含关系词不误触发）；内容=图片或图库为空的配置提示；意义=娱乐。\n'
                '【取值范围】\n'
                '  BOT_RANDPIC_DIRS：文件夹路径列表；扩展名 jpg/jpeg/png/gif/webp/bmp；\n'
                '  单文件 ≤20MB；目录不存在/为空时给友好提示不报错。\n'
                '【权限与效果】\n'
                '  权限=全员（bot_randpic_enabled 可关）。\n'
                '【示例】随机图｜来张图'
            ),
        },
        {
            "topic": '提醒',
            "admin_only": False,
            "aliases": ('提醒', 'reminder', '叫我', '定时提醒'),
            "index": '【提醒】到点督促：12点提醒我写作业｜提醒列表｜取消提醒 <id前几位>',
            "title_line": '【提醒】时间点记忆与主动督促',
            "lines": [
                '<时间>提醒我 <事项>：作用=到点主动督促；参数=时间（必填，支持绝对「12点/明天早上8点/下午三点半」与相对「半小时后/N分钟后/N小时后」）＋事项（可选，截取 ≤120 字，省略给默认文案）；内容=记下确认＋取消用的 id 前缀；意义=守岸人版闹钟。',
                '提醒列表 / 我的提醒：作用=查看待办；参数=无；内容=本会话待办提醒（id 前 6 位＋时刻＋事项）；意义=盘点。',
                '取消提醒 <id前缀>：作用=取消某条；参数=id 前缀（必填，4-12 位十六进制，需唯一命中，多条命中会要求换更长前缀）；内容=取消确认；意义=反悔。',
                '规则：只提醒“当前会话”；无明确日词且时刻已过自动顺延明天；时间必须晚于当前，否则视为没解析到。',
            ],
            "detail": (
                '【板块介绍】\n'
                '  时间点记忆：把“几点做什么”存库，每分钟调度任务到点以守岸人语气\n'
                '  主动督促。触发方式是自然语言（含 提醒/叫我/记得叫 信号词且能解析出\n'
                '  时间），或列表/取消查询。\n'
                '【指令与参数】\n'
                '<时间>提醒我 [事项]（别名 叫我）：作用=建提醒；参数=时间（自然语言：X点/X点半/X:MM/下午X点/N分钟后/半小时后/明天早上8点…）＋事项可选（≤120 字）；内容=记下确认；意义=核心玩法。\n'
                '提醒列表|我的提醒|看看提醒|有哪些提醒：作用=列待办；参数=无；内容=清单；意义=盘点。\n'
                '取消提醒 [id前缀]：作用=取消；参数=4-12 位十六进制前缀（唯一命中才取消；不带前缀会提示先看列表）；内容=取消确认；意义=反悔。\n'
                '【权限与效果】\n'
                '  权限=全员（bot_reminder_enabled 可关）。投递按会话作用域（群=群内，\n'
                '  私聊=本人），发送走队列。\n'
                '【示例】12点提醒我写作业｜明天早上8点叫我起床｜半小时后提醒我去看汤｜提醒列表｜取消提醒 a3f2'
            ),
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
    mica-glass v1 2026-09-12：釉瑚云母底（bridge 按 accent 派生 --wash-* 注入；
    工艺出处=用户裁定）+ 液态玻璃面板 + 三枚柔光色斑漂移 + 内联脚本随机相位。
    """
    from plugins.bot_unified_runtime.output.card_render.bridge import (
        _derive_wash_tokens,
    )

    accent, accent_ink = _resolve_help_accent(accent_color)
    wash = _derive_wash_tokens(accent)
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
            "<section class=\"help-section glass" + (" main" if index == 0 else "") + "\">"
            f"<h2><span class=\"dot\"></span>{_esc(title)}</h2>"
            f"<div class=\"command-list\">{_rows_html(rows)}</div></section>"
            for index, (title, rows) in enumerate(sections)
        )
        grid_cls = "single"
        header_title = f"{bot_name} · {detail_title}"
        header_sub = "参数标注：<> 必填、[] 可选；把命令复制到聊天即可使用，具体取值见各行说明。"
    else:
        cards = "".join(
            "<section class=\"help-section glass" + (" wide" if len(rows) >= 40 else "") + "\">"
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
:root {{ --phase:0.2; --accent:{accent}; --accent-ink:{accent_ink};
  /* 釉瑚云母底主题 token，全卡统一（bridge 按 --accent 派生；工艺出处=用户裁定）。 */
  --wash-1:{wash['wash_1']}; --wash-2:{wash['wash_2']}; --wash-3:{wash['wash_3']}; --wash-mist:{wash['wash_mist']};
  --wash-blob-1:color-mix(in srgb, var(--accent) 35%, var(--wash-1));
  --ink:#27232a; --muted:#6f646c; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:0; font-family:"Segoe UI","Microsoft YaHei",sans-serif; background:transparent; color:var(--ink); -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }}
.help-stage {{ width:fit-content; padding:0; background:transparent; }}
/* 釉瑚云母外壳：雾底打底、wash-1/2 对角透色、wash-3 只作第三色透底（不透明基础层）
   + 1px 内高光渐变描边；色斑垫底、内容抬升；阴影两枚 token。 */
.help-shell {{ position:relative; width:940px; overflow:hidden; border-radius:24px; border:1px solid transparent;
  background:linear-gradient(145deg, var(--wash-mist) 0%, color-mix(in srgb, var(--wash-1) 55%, var(--wash-mist)) 30%,
    color-mix(in srgb, var(--wash-2) 48%, var(--wash-mist)) 64%, color-mix(in srgb, var(--wash-3) 40%, var(--wash-mist)) 100%) padding-box,
    linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%, rgba(255,255,255,.72) 100%) border-box;
  box-shadow:0 14px 34px rgba(31,35,41,.10); }}
.help-shell > :not(.drift-blobs) {{ position:relative; z-index:1; }}
/* 渐变漂移色斑（wash 三色半透明互相透过，46s/52s/58s 交错漂移+呼吸）。 */
.drift-blobs {{ position:absolute; inset:0; z-index:0; overflow:hidden; pointer-events:none; border-radius:inherit; }}
.drift-blob {{ position:absolute; display:block; border-radius:50%; will-change:transform; }}
.drift-blob.drift-a {{ width:58%; aspect-ratio:1; left:-14%; top:-22%;
  background:radial-gradient(closest-side, color-mix(in srgb, var(--wash-blob-1) 50%, transparent) 0%,
    color-mix(in srgb, var(--wash-blob-1) 28%, transparent) 46%, color-mix(in srgb, var(--wash-blob-1) 6%, transparent) 70%, transparent 100%);
  animation:mica-drift-a 46s ease-in-out infinite alternate; animation-delay:calc(var(--phase, 0.2) * -46s); }}
.drift-blob.drift-b {{ width:52%; aspect-ratio:1; right:-16%; bottom:-24%;
  background:radial-gradient(closest-side, color-mix(in srgb, var(--wash-2) 30%, transparent) 0%,
    color-mix(in srgb, var(--wash-2) 16%, transparent) 48%, color-mix(in srgb, var(--wash-2) 5%, transparent) 72%, transparent 100%);
  animation:mica-drift-b 58s ease-in-out infinite alternate; animation-delay:calc(var(--phase, 0.2) * -58s - 9s); }}
.drift-blob.drift-c {{ width:64%; aspect-ratio:1; left:22%; top:34%;
  background:radial-gradient(closest-side, color-mix(in srgb, var(--wash-3) 26%, transparent) 0%,
    color-mix(in srgb, var(--wash-3) 14%, transparent) 48%, color-mix(in srgb, var(--wash-3) 5%, transparent) 72%, transparent 100%);
  animation:mica-drift-c 52s ease-in-out infinite alternate; animation-delay:calc(var(--phase, 0.2) * -52s - 21s); }}
@keyframes mica-drift-a {{ 0% {{ transform:translate3d(-4%,-2%,0) scale(1); }} 50% {{ transform:translate3d(7%,9%,0) scale(1.18); }} 100% {{ transform:translate3d(-3%,14%,0) scale(.92); }} }}
@keyframes mica-drift-b {{ 0% {{ transform:translate3d(3%,4%,0) scale(1.05); }} 50% {{ transform:translate3d(-8%,-6%,0) scale(.9); }} 100% {{ transform:translate3d(-2%,-12%,0) scale(1.2); }} }}
@keyframes mica-drift-c {{ 0% {{ transform:translate3d(-5%,4%,0) scale(1.1); }} 50% {{ transform:translate3d(9%,-7%,0) scale(.88); }} 100% {{ transform:translate3d(2%,-3%,0) scale(1.16); }} }}
@media (prefers-reduced-motion: reduce) {{ .drift-blob.drift-a, .drift-blob.drift-b, .drift-blob.drift-c {{ animation:none; }} }}
/* 液态玻璃面板：半透明白 + 1px 内高光渐变描边（无 backdrop-filter）。 */
.glass {{ background:linear-gradient(150deg, rgba(255,255,255,.66) 0%, rgba(255,255,255,.44) 100%) padding-box,
    linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%, rgba(255,255,255,.72) 100%) border-box;
  border:1px solid transparent; box-shadow:0 3px 10px rgba(31,35,41,.05); }}
.help-head {{ display:flex; align-items:center; gap:14px; padding:22px 26px 18px; border-bottom:1px solid rgba(255,255,255,.78); }}
.avatar-wrap {{ flex:0 0 auto; width:52px; height:52px; border-radius:16px; overflow:hidden; background:color-mix(in srgb, var(--accent) 14%, #fff); display:flex; align-items:center; justify-content:center; box-shadow:inset 0 0 0 1px rgba(255,255,255,.9); }}
.avatar-wrap img {{ width:100%; height:100%; object-fit:cover; }}
.avatar-fallback {{ font-size:24px; font-weight:700; color:var(--accent-ink); }}
.head-main {{ flex:1 1 auto; min-width:0; }}
.help-kicker {{ color:var(--accent-ink); font-size:11px; font-weight:700; letter-spacing:.14em; }}
.help-title {{ margin-top:6px; font-size:27px; font-weight:700; letter-spacing:.01em; }}
.help-subtitle {{ margin-top:6px; color:var(--muted); font-size:12.5px; line-height:1.55; }}
.help-chip {{ flex:0 0 auto; padding:7px 14px; border-radius:999px; color:var(--accent-ink); background:color-mix(in srgb, var(--accent) 8%, rgba(255,255,255,.80)); border:1px solid rgba(255,255,255,.90); font-size:12px; font-weight:650; }}
.help-body {{ padding:14px; }}
.help-grid.masonry {{ column-count:2; column-gap:12px; }}
.help-grid.masonry .help-section {{ break-inside:avoid; margin-bottom:12px; }}
.help-grid.masonry .help-section.wide {{ column-span:all; }}
.help-grid.single {{ display:grid; grid-template-columns:1fr; gap:12px; }}
.help-section {{ border-radius:16px; overflow:hidden; }}
.help-section h2 {{ display:flex; align-items:center; gap:8px; margin:0; padding:10px 14px; color:var(--accent-ink); background:linear-gradient(135deg, color-mix(in srgb, var(--accent) 7%, rgba(255,255,255,.62)), color-mix(in srgb, var(--accent) 12%, rgba(255,255,255,.48))); border-bottom:1px solid rgba(255,255,255,.85); font-size:14.5px; font-weight:700; letter-spacing:.02em; }}
.help-section h2 .dot {{ flex:0 0 auto; width:7px; height:7px; border-radius:50%; background:var(--accent); box-shadow:0 0 0 3px color-mix(in srgb, var(--accent) 18%, #fff); }}
.command-list {{ padding:9px; display:grid; gap:6px; }}
.command-row {{ display:flex; align-items:flex-start; gap:9px; padding:7px 10px; border-radius:11px; background:rgba(255,255,255,.62); font-size:12px; line-height:1.55; }}
.command-row .pill {{ flex:0 0 auto; max-width:62%; padding:2px 10px; border-radius:999px; color:var(--accent-ink); background:color-mix(in srgb, var(--accent) 13%, rgba(255,255,255,.82)); font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.command-row .desc {{ color:var(--muted); min-width:0; overflow-wrap:anywhere; }}
.help-foot {{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding:10px 16px; background:rgba(255,255,255,.42); border-top:1px solid rgba(255,255,255,.80); }}
.help-foot .tip {{ color:var(--muted); font-size:11.5px; }}
.help-bot-pill {{ display:flex; align-items:center; gap:8px; padding:5px 13px 5px 6px; border-radius:999px; color:var(--accent-ink); background:color-mix(in srgb, var(--accent) 6%, rgba(255,255,255,.72)); border:1px solid #fff; box-shadow:0 4px 10px rgba(31,35,41,.07); font-size:13px; font-weight:600; }}
.help-bot-avatar {{ width:27px; height:27px; object-fit:cover; border-radius:50%; }}
</style></head><body><div class="help-stage card"><section class="help-shell">
<div class="drift-blobs" aria-hidden="true"><span class="drift-blob drift-a"></span><span class="drift-blob drift-b"></span><span class="drift-blob drift-c"></span></div>
<header class="help-head"><div class="avatar-wrap">{avatar_block}</div><div class="head-main"><div class="help-kicker">{_esc(role)}</div><div class="help-title">{_esc(header_title)}</div><div class="help-subtitle">{_esc(header_sub)}</div></div><div class="help-chip">发 /bot help 获取本图</div></header><main class="help-body"><div class="help-grid {grid_cls}">{cards}</div></main><footer class="help-foot"><span class="tip">参数标注：&lt;&gt; 必填，[] 可选；群里直接发命令即可触发。</span><div class="help-bot-pill">{avatar}<span>{_esc(bot_name)} · 命令手册</span></div></footer></section></div>
<script>/* mica-glass v1 2026-09-12：随机漂移相位，纯内联零依赖，失败静默。 */
try{{document.documentElement.style.setProperty("--phase",Math.random().toFixed(4));}}catch(e){{}}</script></body></html>"""


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
                for line in entry["lines"]:
                    lines.extend(_split_facets(str(line)))
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


_COMMANDS_CATALOG_QUERY = frozenset({"commands", "cmds", "命令", "命令列表", "命令目录"})


def build_commands_catalog_body(*, is_admin: bool = False) -> str:
    """`/bot commands` 命令目录：机器可读纯文本，不走帮助卡渲染。

    自动生成，数据源两处，新增能力无需改本函数：
    - runtime.base_router 路由注册表（确定性路由：kind/capability/优先级）；
    - echo._HELP_ENTRIES（帮助模块：主题/别名/可见性）。
    行格式：区段头 `[名称] 字段 | 字段 | …`，数据行以 ` | ` 分隔。
    非管理员只列公开模块（与帮助总览同门控）；路由表为公开路由语义，全列。
    """
    from plugins.bot_unified_runtime.runtime.base_router import (
        list_route_rules_for_audit,
    )

    rules = sorted(list_route_rules_for_audit(), key=lambda item: int(item["priority"]))
    lines = [
        "命令目录 v1（机器可读：区段头 [名称]，数据行「字段 | 字段 | …」；模块详情 /bot help 模块名）",
        f"[routes] priority | kind | capability_id | label（{len(rules)} 条）",
    ]
    for rule in rules:
        lines.append(
            f"{rule['priority']} | {rule['kind']} | {rule['capability_id']} | {rule['label']}"
        )
    entries = _visible_help_entries(is_admin)
    lines.append(f"[commands] topic | aliases | access（{len(entries)} 条）")
    for entry in entries:
        aliases = "/".join(str(alias) for alias in (entry.get("aliases") or ())) or str(
            entry["topic"]
        )
        access = "admin" if entry.get("admin_only") else "public"
        lines.append(f"{entry['topic']} | {aliases} | {access}")
    return "\n".join(lines)


_FACET_SPLIT_RE = re.compile(r"；(?=[^；=：]{1,6}=)")


def _split_facets(line: str) -> list[str]:
    """F8（2026-09-12 实弹反馈⑧）：四要素「作用/参数/内容/意义」连排拆行。

    「好感度：作用=查好感；参数=无；内容=卡；意义=可视化」→ 首行保留
    前缀与第一要素，其余要素各占一行（全角空格缩进）。无要素连排的
    普通行原样返回。
    """
    if "=" not in line or "；" not in line:
        return [line]
    parts = [part.strip() for part in _FACET_SPLIT_RE.split(line) if part.strip()]
    if len(parts) <= 1:
        return [line]
    return [parts[0]] + [f"　{part}" for part in parts[1:]]


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
    if cleaned.strip().lower() in _COMMANDS_CATALOG_QUERY:
        # 命令目录：文本直出，不做帮助卡渲染（与 /bot help 不重复）。
        return CapabilityResult(
            request_id=request_id or new_request_id("commands"),
            capability_id="bot.commands",
            kind="text",
            title="命令目录",
            body=build_commands_catalog_body(is_admin=is_admin),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=["help", "commands_catalog"],
        )
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
            # M7：`detail` 字段过去是**只写死数据**——49 个条目的四段式文案
            # （板块介绍 / 命令与参数 / 参数范围 / 设置效果）全部写好了，
            # 但没有任何读取点，深度页只输出 `lines` 的简表。
            # 这里把它接进 `/bot help <模块>` 的详情页，同时保留 `lines`，
            # 让"计划 D 四段式深度教学版"直接落地而不是从零重写。
            body = entry["title_line"] + "\n" + "\n".join(
                split
                for line in entry["lines"]
                for split in _split_facets(str(line))
            )
            detail_text = str(entry.get("detail") or "").strip()
            if detail_text:
                detail_text = "\n".join(
                    split
                    for detail_line in detail_text.splitlines()
                    for split in _split_facets(detail_line)
                )
            if detail_text and detail_text not in body:
                body = f"{body}\n\n{detail_text}"
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

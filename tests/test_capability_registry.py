"""Keystone（审查 C-06 能力单一声明源）双向逐字段锁定测试（全离线）。

C-06：能力属性此前散落 base_router.py 的 5 份手写清单（RouteKind 枚举 /
RouteRule 注册表 / 接口清单 / COMMAND_ROUTE_KINDS / INTERNAL_CAPABILITY_
NOTES），新增能力要改 4-5 处、漏登即不可见。2026-09-14 批把声明收拢到
runtime/capability_registry.py（每能力一行），并在 base_router import 时
派生 COMMAND_ROUTE_KINDS。

四处离线静态解析器（scripts/doc_sync.py、scripts/command_catalog.py、
tests/test_doc_sync_gates.py、scripts/extract_trigger_words.py）按源码文本
提取 base_router 的字面四表，故字面形态必须留在 base_router.py。本测试
把「声明源 ↔ 字面投影」双向锁死，任何一侧改动而不同步另一侧即红：

1. 声明表覆盖 RouteKind 全体成员（含 IGNORE 兜底席），成员名/取值/序一致；
2. RouteRule 注册表每行数据列与声明行逐字段相等，matcher 绑定名与声明
   matcher_name 相等（AST 提取），书写序与本批改动前快照逐行相等（零漂移）；
3. COMMAND_ROUTE_KINDS 确由声明表 command 列派生，且与改动前快照相等；
4. 接口清单 18 行与 INTERFACE_DECLARATIONS 逐字段逐序相等（= 快照）；
5. INTERNAL_CAPABILITY_NOTES 键值集与声明 note 列相等（= 快照，含序）；
6. classify_message_route 的 IGNORE 兜底 RouteDecision 字面量与声明兜底席
   一致（AST 提取）。

二期（2026-09-14）：帮助注册表同哲学对齐——
7. 声明源 HELP_TOPIC_DECLARATIONS（每主题一行 topic/admin_only/capability
   权威三元组）与 echo._HELP_ENTRIES 逐 topic 强一致（缺失/多出/字段不符
   即红）；普通用户可见集与分类表引用面、接口清单 help_topic 引用、路由
   能力 → 帮助归属可解析性一并锁死。echo 字面表因 command_catalog.py 与
   doc_sync.py 的静态解析而保持原位（与第一期「声明源=权威数据+字面=投影」
   同哲学）。

改动前快照来源：本批动手前以运行时 introspection 导出（五表全量 JSON），
逐值转录于此，作为「纯重构零行为变化」的回归锚。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from plugins.bot_unified_runtime.capabilities.echo import (
    _HELP_CATEGORIES,
    _PUBLIC_HELP_TOPICS,
    HELP_ENTRIES,
)
from plugins.bot_unified_runtime.runtime import base_router as br
from plugins.bot_unified_runtime.runtime import capability_registry as cr

ROOT = Path(__file__).resolve().parents[1]
BASE_ROUTER_PY = ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "base_router.py"

# ---------------------------------------------------------------------------
# 改动前快照（2026-09-14，C-06 动手前实跑导出；纯重构回归锚，勿手改数值）
# ---------------------------------------------------------------------------

_SNAPSHOT_ROUTE_KINDS: tuple[tuple[str, str], ...] = (
    ("ALIAS", "alias"), ("ADMIN", "admin"), ("SUBSCRIBE", "subscribe"),
    ("AUTO_SEND", "auto_send"), ("MEME", "meme"), ("MEME_LIBRARY", "meme_library"),
    ("MUSIC_MODE", "music_mode"), ("MUSIC", "music"), ("TODAY_HISTORY", "today_history"),
    ("WIKI", "wiki"), ("MOEGIRL", "moegirl"), ("MOEGIRL_QUESTION", "moegirl_question"),
    ("EPIC", "epic"), ("WEATHER", "weather"), ("MARKET", "market"),
    ("STOCKS", "stocks"), ("COMMODITIES", "commodities"), ("BOND", "bond"),
    ("NORTHBOUND", "northbound"), ("FX", "fx"), ("NEWS", "news"),
    ("RANDPIC", "randpic"), ("REMINDER", "reminder"), ("MEDIA_ARCHIVE", "media_archive"),
    ("DAILY_ASSIST", "daily_assist"),
    ("GROUP_INFO", "group_info"), ("EAT", "eat"), ("AFFINITY", "affinity"),
    ("DIVINATION", "divination"), ("TTS", "tts"), ("NATURAL_COMMAND", "natural_command"),
    ("CONTENT", "content"), ("CHAT", "chat"), ("EMERGENCY_INFO", "emergency_info"),
    ("IGNORE", "ignore"),
)

# (kind 取值, capability_id, priority, label, reason, tags)——build_route_rules
# 字面书写序（= 判定循环同 priority 的先到先得序）。
_SNAPSHOT_ROUTE_RULES: tuple[tuple[str, str, int, str, str, tuple[str, ...]], ...] = (
    ("alias", "bot.alias", 10, "昵称命令", "昵称命令（/岸宝… /守岸人…）", ("base_route:alias",)),
    ("admin", "bot.status", 11, "管理员命令", "管理员命令（/bot …）", ("base_route:admin",)),
    ("subscribe", "bot.subscribe", 12, "订阅命令", "订阅命令（中文/英文）", ("base_route:subscribe",)),
    ("auto_send", "bot.auto_send", 13, "自动发送", "自动发送/定时任务命令", ("base_route:auto_send",)),
    ("meme", "bot.meme", 20, "表情包生成", "表情包生成命令", ("base_route:meme",)),
    ("meme_library", "bot.meme_library", 22, "偷表情", "偷表情/表情库命令", ("base_route:meme_library",)),
    ("music_mode", "bot.music_mode", 40, "点歌模式", "点歌输出模式设置", ("base_route:music_mode",)),
    ("music", "bot.music", 41, "点歌", "点歌", ("base_route:music",)),
    ("today_history", "bot.today_history", 41, "历史上的今天", "历史上的今天", ("base_route:today_history",)),
    ("wiki", "bot.wiki", 41, "维基百科", "维基百科查询", ("base_route:wiki",)),
    ("moegirl", "bot.moegirl", 41, "萌娘百科", "萌娘百科查询", ("base_route:moegirl",)),
    ("epic", "bot.epic", 41, "Epic 免费游戏", "Epic 免费游戏查询", ("base_route:epic",)),
    ("weather", "bot.weather", 41, "天气查询", "天气查询", ("base_route:weather",)),
    ("commodities", "bot.commodities", 37, "商品行情", "商品行情（黄金/金价/白银/原油/铜价/大宗商品）", ("base_route:commodities",)),
    ("bond", "bot.bond", 38, "国债收益率", "国债收益率（国债/期限利差/收益率曲线）", ("base_route:bond",)),
    ("northbound", "bot.northbound", 39, "北向资金", "北向资金（北向资金/沪股通/深股通）", ("base_route:northbound",)),
    ("market", "bot.market", 41, "全球股指行情", "全球股指行情（行情/美股行情/大盘）", ("base_route:market",)),
    ("fx", "bot.fx", 36, "汇率查询", "汇率（美元兑人民币/汇率面板）", ("base_route:fx",)),
    ("stocks", "bot.stocks", 42, "个股行情", "个股行情（英伟达/AMD/英特尔股价）", ("base_route:stocks",)),
    ("eat", "bot.eat", 41, "吃什么推荐", "吃什么/菜谱推荐", ("base_route:eat",)),
    ("affinity", "bot.affinity", 41, "好感度查询", "好感度/好感查看/查询好感", ("base_route:affinity",)),
    ("divination", "bot.divination", 41, "占卜", "占卜/塔罗/八字排盘", ("base_route:divination",)),
    ("tts", "bot.tts", 41, "语音合成", "语音合成（说/语音/念+正文）", ("base_route:tts",)),
    ("news", "bot.news", 41, "今日快报", "今日快报（快报/科技新闻/财经快报/国际新闻）", ("base_route:news",)),
    ("randpic", "bot.randpic", 41, "随机图片", "随机图片（随机图/来张图）", ("base_route:randpic",)),
    ("reminder", "bot.reminder", 41, "提醒", "提醒（12点提醒我写作业/提醒列表/取消提醒）", ("base_route:reminder",)),
    ("media_archive", "bot.media_archive", 43, "媒体归档", "媒体归档（收藏/归档/存图+媒体；存聊天记录）", ("base_route:media_archive",)),
    ("daily_assist", "bot.daily_assist", 42, "收件箱速记", "收件箱（收件箱 买牛奶/收件箱）", ("base_route:daily_assist",)),
    ("emergency_info", "bot.emergency_info", 44, "紧急信息", "紧急信息（外部预警与政务应急聚合：紧急信息｜紧急信息 待审）", ("base_route:emergency_info",)),
    ("group_info", "bot.group_info", 41, "群信息", "群信息（群信息/群主是谁/群人数/群公告/群精华/本群多大了）", ("base_route:group_info",)),
    ("moegirl_question", "bot.moegirl", 46, "二次元问句", "二次元问句（萌娘百科自动查询，未命中降级聊天）", ("base_route:moegirl_question",)),
    ("natural_command", "bot.natural_command", 45, "自然语言命令", "自然语言命令归一化", ("base_route:natural_command",)),
    ("content", "bot.content", 46, "链接解析", "链接解析（视频/图片/社交媒体/商品等）", ("base_route:content",)),
    ("chat", "bot.chat", 50, "人格对话", "自然语言对话（人格+世界观+价值观+方法论）", ("base_route:chat",)),
)

_SNAPSHOT_COMMAND_ROUTE_KINDS: frozenset[str] = frozenset(
    {
        "ALIAS", "ADMIN", "SUBSCRIBE", "AUTO_SEND", "MEME", "MEME_LIBRARY",
        "MUSIC_MODE", "MUSIC", "TODAY_HISTORY", "WIKI", "MOEGIRL", "EPIC",
        "WEATHER", "MARKET", "STOCKS", "COMMODITIES", "BOND", "NORTHBOUND",
        "FX", "EAT", "DIVINATION", "TTS", "NEWS", "RANDPIC", "REMINDER",
        "MEDIA_ARCHIVE", "DAILY_ASSIST", "GROUP_INFO", "NATURAL_COMMAND", "EMERGENCY_INFO",
    }
)

# (interface_id, label, status, route_kind, priority, description, help_topic,
#  internal_note)——build_interface_manifest 字面书写序。
_SNAPSHOT_INTERFACE_MANIFEST: tuple[tuple[str, str, str, str, int | None, str, str, str], ...] = (
    ("transport.onebot", "SnowLuma / OneBot V11 传输", "active", "transport", None, "入站 QQ 消息与出站发送统一走 OneBot V11（SnowLuma），由发送队列收口", "", "内部：传输层，无用户命令"),
    ("core.gscore", "GsCore / 早柚核心桥", "active", "bridge", None, "ws://HOST:PORT/BOT_ID?token=TOKEN 桥接，接收游戏侧消息，配置 BOT_GSCORE_*", "", "内部：桥接层，接收游戏侧消息，无用户命令"),
    ("parser.content", "平台链接解析插件组", "active", "content", 46, "B站/小红书/抖音/油管/推特/Lofter/Pixiv/allcpp/米画师/小黑盒/音乐平台", "链接", ""),
    ("persona.chat", "人格大模型对话", "active", "chat", 50, "人格档案 + 向量知识库 + 世界观注入的大模型回复", "聊天", ""),
    ("capability.weather", "天气", "active", "weather", 41, "中国气象局 NMC 免 key 查询", "天气", ""),
    ("capability.music", "点歌", "active", "music", 41, "网易云/酷我/酷狗/QQ音乐/Apple Music/Spotify 搜索", "点歌", ""),
    ("capability.wiki", "维基百科", "active", "wiki", 41, "MediaWiki 公开 API", "维基", ""),
    ("capability.moegirl", "萌娘百科", "active", "moegirl", 46, "萌百 MediaWiki 公开 API：显式指令 + 二次元问句自动查询（未命中降级人格聊天）", "萌娘百科", ""),
    ("capability.epic", "Epic 免费游戏", "active", "epic", 41, "Epic 公开接口", "Epic", ""),
    ("capability.today_history", "历史上的今天", "active", "today_history", 41, "百度百科公开接口 + 每日推送", "历史上的今天", ""),
    ("capability.subscribe", "订阅博主/直播推送", "active", "subscribe", 12, "UP主/番剧/小红书博主等新内容与开播推送", "订阅", ""),
    ("capability.meme", "表情包生成", "active", "meme", 20, "调用本地 meme-generator-rs HTTP API 生成表情包", "表情", ""),
    ("capability.auto_send", "自动发送/定时任务", "active", "auto_send", 13, "报存 给 A 发… 草稿/预览/发送", "草稿", ""),
    ("capability.game_live", "游戏直播状态", "reserved", "game_live", None, "预留：游戏内直播/活动事件接入", "", "预留：游戏直播事件接入，尚未实现"),
    ("capability.meme_absorb", "吸收表情包", "active", "meme_absorb", None, "监听群图片异步下载、MD5 去重、权重筛选、VLM 打标与 NSFW 过滤", "表情收库", ""),
    ("capability.group_info", "群信息", "active", "group_info", 41, "OneBot V11 群 API（get_group_info/成员列表/公告/精华）：群资料/人数全员，公告与精华仅管理员；诚实降级清单见 capabilities/group_info.py", "群信息", ""),
    ("capability.daily_assist", "收件箱速记/早晚简报", "active", "daily_assist", 42, "收件箱随手记 + 定时吃什么推荐与早晚简报（BOT_DAILY_ASSIST_*，纯文本文件驱动）", "收件箱", ""),
    ("capability.tts", "语音合成", "active", "tts", 41, "本机 GPT-SoVITS v2ProPlus HTTP API（api_v2.py 的 /tts）：文本合成守岸人音色语音；参考音频与开关见 BOT_TTS_*", "语音", ""),
    ("capability.emotion", "情绪状态注入", "active", "context", None, "作为上下文能力注入，不单独占用文本路由", "", "内部：心情引擎，经上下文注入，不占文本路由"),
    ("capability.gscore", "GsCore 上行命令", "reserved", "gscore", None, "预留：GsCore 侧指令统一进入基层路由", "", "预留：GsCore 侧指令统一进入基层路由，尚未实现"),
)

# INTERNAL_CAPABILITY_NOTES 字面 dict 的 (键, 值) 序。
_SNAPSHOT_INTERNAL_NOTES: tuple[tuple[str, str], ...] = (
    ("bot.stocks", "个股行情（英伟达/AMD/英特尔股价兜底，触发词见 capabilities/stocks.py；帮助页 topic=个股行情）"),
    ("bot.fx", "汇率查询（美元兑人民币/汇率面板，触发词见 capabilities/fx.py；帮助页 topic=汇率）"),
    ("bot.commodities", "商品行情（黄金/白银/原油/铜现货与 30 日走势，触发词见 capabilities/market.py；帮助页 topic=商品行情）"),
    ("bot.bond", "国债收益率（国债/期限利差/收益率曲线，触发词见 capabilities/market.py；帮助页 topic=国债收益率）"),
    ("bot.northbound", "北向资金（北向资金/沪股通/深股通成交总额，触发词见 capabilities/market.py；帮助页 topic=北向资金）"),
)


# ---------------------------------------------------------------------------
# AST 静态提取（与 tests/test_doc_sync_gates.py 同手法，离线不 import 包）
# ---------------------------------------------------------------------------


def _rule_table_entries() -> list[dict[str, object]]:
    """从 build_route_rules 的 return [...] 逐行提取 (member/capability_id/
    priority/matcher 名)。"""
    tree = ast.parse(BASE_ROUTER_PY.read_text(encoding="utf-8"))
    entries: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "build_route_rules"):
            continue
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Return) and isinstance(sub.value, ast.List)):
                continue
            for elt in sub.value.elts:
                assert isinstance(elt, ast.Call), "RouteRule 注册表出现非 Call 行"
                kind_attr = elt.args[0]
                assert isinstance(kind_attr, ast.Attribute)
                matcher_name = ""
                for kw in elt.keywords:
                    if kw.arg == "matcher" and isinstance(kw.value, ast.Name):
                        matcher_name = kw.value.id
                if len(elt.args) > 6 and isinstance(elt.args[6], ast.Name):
                    matcher_name = elt.args[6].id
                entries.append(
                    {
                        "member": kind_attr.attr,
                        "capability_id": ast.literal_eval(elt.args[1]),
                        "priority": ast.literal_eval(elt.args[2]),
                        "matcher": matcher_name,
                    }
                )
    return entries


def _ignore_fallback_entries() -> set[tuple[str, int]]:
    """classify_message_route 里 IGNORE 兜底 RouteDecision 的 (capability, priority)。"""
    tree = ast.parse(BASE_ROUTER_PY.read_text(encoding="utf-8"))
    fallbacks: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "classify_message_route"):
            continue
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)):
                continue
            if sub.func.id != "RouteDecision" or len(sub.args) < 3:
                continue
            kind_arg = sub.args[0]
            if (
                isinstance(kind_arg, ast.Attribute)
                and isinstance(kind_arg.value, ast.Name)
                and kind_arg.value.id == "RouteKind"
                and kind_arg.attr == "IGNORE"
            ):
                fallbacks.add((ast.literal_eval(sub.args[1]), ast.literal_eval(sub.args[2])))
    return fallbacks


_DECL_BY_KIND = {decl.kind: decl for decl in cr.ROUTE_CAPABILITY_DECLARATIONS}
_RULE_KINDS_IN_BOOK_ORDER = [rule.kind.name for rule in br.ROUTE_RULES]


# ---------------------------------------------------------------------------
# ① 声明表 ↔ RouteKind 枚举
# ---------------------------------------------------------------------------


def test_registry_covers_every_route_kind() -> None:
    """声明行数 = RouteKind 成员数；成员名/取值/顺序逐一相等（含 IGNORE 兜底席）。"""
    live = [(member.name, member.value) for member in br.RouteKind]
    declared = [(decl.kind, decl.value) for decl in cr.ROUTE_CAPABILITY_DECLARATIONS]
    assert len(cr.ROUTE_CAPABILITY_DECLARATIONS) == len(br.RouteKind) == 35
    assert declared == live
    assert live == [tuple(pair) for pair in _SNAPSHOT_ROUTE_KINDS]  # 枚举本体与改动前快照一致


def test_declared_kind_values_resolve_to_enum_members() -> None:
    for decl in cr.ROUTE_CAPABILITY_DECLARATIONS:
        member = getattr(br.RouteKind, decl.kind)
        assert member.value == decl.value


# ---------------------------------------------------------------------------
# ② 声明表 ↔ RouteRule 注册表（运行时 + AST 字面 + 改动前快照）
# ---------------------------------------------------------------------------


def test_route_rules_data_columns_equal_registry() -> None:
    """每条 RouteRule 的数据列与同 kind 声明行逐字段相等；声明无多登/漏登。"""
    rules_by_kind = {rule.kind.name: rule for rule in br.ROUTE_RULES}
    rule_producing_decls = [decl for decl in cr.ROUTE_CAPABILITY_DECLARATIONS if decl.has_rule]
    assert {decl.kind for decl in rule_producing_decls} == set(rules_by_kind)
    assert len(rule_producing_decls) == len(br.ROUTE_RULES) == 34
    for decl in rule_producing_decls:
        rule = rules_by_kind[decl.kind]
        assert rule.kind.value == decl.value
        assert rule.capability_id == decl.capability_id
        assert rule.priority == decl.priority
        assert rule.label == decl.label
        assert rule.reason == decl.reason
        assert rule.tags == decl.tags
        assert rule.matcher is not None and callable(rule.matcher)


def test_route_rules_book_order_equal_pre_change_snapshot() -> None:
    """注册表书写序（判定循环同 priority 先到先得序）与改动前快照逐行相等。"""
    live = [
        (rule.kind.value, rule.capability_id, rule.priority, rule.label, rule.reason, rule.tags)
        for rule in br.ROUTE_RULES
    ]
    assert tuple(live) == _SNAPSHOT_ROUTE_RULES


def test_literal_rule_table_matchers_equal_registry_names() -> None:
    """AST 提取的字面表 (member, capability_id, priority, matcher 名) 与声明行
    按书写序逐行相等——matcher 绑定列也是声明源管的数据。"""
    entries = _rule_table_entries()
    book_decls = [
        _DECL_BY_KIND[member]
        for member in _RULE_KINDS_IN_BOOK_ORDER
    ]
    assert len(entries) == len(book_decls)
    for entry, decl in zip(entries, book_decls):
        assert entry["member"] == decl.kind
        assert entry["capability_id"] == decl.capability_id
        assert entry["priority"] == decl.priority
        assert entry["matcher"] == decl.matcher_name


# ---------------------------------------------------------------------------
# ③ COMMAND_ROUTE_KINDS：真派生 + 快照回归
# ---------------------------------------------------------------------------


def test_command_route_kinds_derived_from_registry() -> None:
    """base_router.COMMAND_ROUTE_KINDS 确由声明表 command 列派生（成员集合恒等）。"""
    derived = frozenset(
        br.RouteKind[decl.kind] for decl in cr.ROUTE_CAPABILITY_DECLARATIONS if decl.command
    )
    assert br.COMMAND_ROUTE_KINDS == derived
    assert {m.name for m in br.COMMAND_ROUTE_KINDS} == set(cr.COMMAND_ROUTE_KIND_NAMES)


def test_command_route_kinds_equal_pre_change_snapshot() -> None:
    """派生结果与改动前字面 frozenset 快照逐成员相等（零行为变化锚）。"""
    assert {member.name for member in br.COMMAND_ROUTE_KINDS} == set(_SNAPSHOT_COMMAND_ROUTE_KINDS)
    assert len(br.COMMAND_ROUTE_KINDS) == 30
    # 非命令路由席（让路档/兜底）确不在册：affinity 查询走 /bot 链与 matcher，
    # moegirl_question/content/chat 是被动路由，ignore 是兜底。
    excluded = {"AFFINITY", "MOEGIRL_QUESTION", "CONTENT", "CHAT", "IGNORE"}
    assert excluded.isdisjoint({member.name for member in br.COMMAND_ROUTE_KINDS})
    assert {_DECL_BY_KIND[name].kind for name in excluded if _DECL_BY_KIND[name].command} == set()


# ---------------------------------------------------------------------------
# ④ 接口清单：声明表 ↔ build_interface_manifest ↔ 快照
# ---------------------------------------------------------------------------


def test_interface_manifest_equal_registry_field_by_field() -> None:
    entries = br.build_interface_manifest()
    assert len(entries) == len(cr.INTERFACE_DECLARATIONS) == 20
    for entry, decl in zip(entries, cr.INTERFACE_DECLARATIONS):
        assert entry.interface_id == decl.interface_id
        assert entry.label == decl.label
        assert entry.status == decl.status
        assert entry.route_kind == decl.route_kind
        assert entry.priority == decl.priority
        assert entry.description == decl.description
        assert entry.help_topic == decl.help_topic
        assert entry.internal_note == decl.internal_note


def test_interface_manifest_equal_pre_change_snapshot() -> None:
    live = tuple(
        (
            entry.interface_id, entry.label, entry.status, entry.route_kind,
            entry.priority, entry.description, entry.help_topic, entry.internal_note,
        )
        for entry in br.build_interface_manifest()
    )
    assert live == _SNAPSHOT_INTERFACE_MANIFEST


# ---------------------------------------------------------------------------
# ⑤ INTERNAL_CAPABILITY_NOTES：声明 note 列 ↔ 字面 dict ↔ 快照
# ---------------------------------------------------------------------------


def test_internal_capability_notes_equal_registry() -> None:
    """字面 dict 与声明表 note 列键值集相等；无 note 的声明行不登记。"""
    assert dict(_SNAPSHOT_INTERNAL_NOTES) == br.INTERNAL_CAPABILITY_NOTES
    registry_notes = {
        decl.capability_id: decl.note
        for decl in cr.ROUTE_CAPABILITY_DECLARATIONS
        if decl.note
    }
    assert registry_notes == br.INTERNAL_CAPABILITY_NOTES
    assert len(registry_notes) == 5
    for decl in cr.ROUTE_CAPABILITY_DECLARATIONS:
        if decl.note:
            assert br.INTERNAL_CAPABILITY_NOTES.get(decl.capability_id) == decl.note
        else:
            assert decl.capability_id not in br.INTERNAL_CAPABILITY_NOTES


def test_internal_capability_notes_order_equal_snapshot() -> None:
    """dict 书写序（命令目录渲染序）与改动前快照逐条相等。"""
    assert list(br.INTERNAL_CAPABILITY_NOTES.items()) == list(_SNAPSHOT_INTERNAL_NOTES)


# ---------------------------------------------------------------------------
# ⑥ IGNORE 兜底席：classify_message_route 字面量 ↔ 声明
# ---------------------------------------------------------------------------


def test_ignore_fallback_literals_match_registry_decl() -> None:
    ignore_decl = _DECL_BY_KIND["IGNORE"]
    assert ignore_decl.has_rule is False
    assert ignore_decl.command is False
    assert ignore_decl.tags == ()
    assert br.RouteKind.IGNORE not in br.COMMAND_ROUTE_KINDS
    assert _ignore_fallback_entries() == {("bot.ignore", ignore_decl.priority)}
    # 运行时兜底与声明行同 capability_id/priority。
    decision = br.classify_message_route("   ", config=object(), alias_resolver=None)
    br.clear_route_decision_cache()
    assert decision.kind is br.RouteKind.IGNORE
    assert decision.capability_id == ignore_decl.capability_id
    assert decision.priority == ignore_decl.priority


# ---------------------------------------------------------------------------
# ⑦ echo 帮助注册表（_HELP_ENTRIES）：声明 help 维度 ↔ 字面表（C-06 二期）
# ---------------------------------------------------------------------------

_HELP_DECLARED_TOPICS = [decl.topic for decl in cr.HELP_TOPIC_DECLARATIONS]


def test_help_topics_equal_registry_book_order() -> None:
    """声明 help 维度与 echo 帮助注册表逐 topic 书序相等；缺失/多出/重复即红。

    74 = doc_sync 机器册「帮助 topic 数」同口径（该册由 echo 字面行数出，
    本断言把声明源钉在同一口径上，两侧各自漂移都过不了这道门）。
    73→74：审查 P-03 新增「决策」topic（/bot decision 查询，2026-09-15）。
    76→77：语音能力批次新增「语音」topic（bot.tts，公开）。
    """
    live_topics = [str(entry["topic"]) for entry in HELP_ENTRIES]
    assert _HELP_DECLARED_TOPICS == live_topics
    assert len(_HELP_DECLARED_TOPICS) == len(set(_HELP_DECLARED_TOPICS)) == 78


def test_help_visibility_and_capability_equal_registry() -> None:
    """每主题的 admin_only / capability 字段与声明行逐字段相等（字段不符即红）。

    比对口径 = echo 运行时合并视图（HELP_ENTRIES，经 _HELP_ENTRY_META
    setdefault 合并后）——与 /bot help、/bot commands 实际消费的数据同源。
    """
    assert len(cr.HELP_TOPIC_DECLARATIONS) == len(HELP_ENTRIES)
    for decl, entry in zip(cr.HELP_TOPIC_DECLARATIONS, HELP_ENTRIES):
        assert str(entry["topic"]) == decl.topic
        assert bool(entry.get("admin_only", False)) == decl.admin_only, decl.topic
        assert str(entry.get("capability", "")) == decl.capability, decl.topic


def test_help_public_visibility_derived_from_declaration() -> None:
    """普通用户可见集 = 声明 admin_only=False 全体；管理员面与公开面零交集。

    治理的真实漏洞类：新公开能力漏登 _PUBLIC_HELP_TOPICS 时对普通用户
    完全隐形（有命令却看不见）——两侧集合必须恒等，漂移即红。
    """
    declared_public = {d.topic for d in cr.HELP_TOPIC_DECLARATIONS if not d.admin_only}
    declared_admin = {d.topic for d in cr.HELP_TOPIC_DECLARATIONS if d.admin_only}
    assert declared_public == set(_PUBLIC_HELP_TOPICS)
    assert declared_admin.isdisjoint(_PUBLIC_HELP_TOPICS)
    assert len(declared_public) == 37 and len(declared_admin) == 41  # 语音批次 +1 公开主题


def test_help_categories_reference_declared_topics() -> None:
    """分类表引用的主题必须全部在册（陈旧分类行不得静默失效）。"""
    declared = set(_HELP_DECLARED_TOPICS)
    for _, topics in _HELP_CATEGORIES:
        unknown = topics - declared
        assert not unknown, f"分类表引用了不在册的主题：{sorted(unknown)}"


def test_interface_help_topics_resolve_to_help_registry() -> None:
    """接口清单 help_topic 列引用的主题必须落在声明 help 维度内（跨表链接）。"""
    declared = set(_HELP_DECLARED_TOPICS)
    for idecl in cr.INTERFACE_DECLARATIONS:
        if idecl.help_topic:
            assert idecl.help_topic in declared, idecl.interface_id


def test_every_routed_capability_resolves_to_help_owner() -> None:
    """路由能力 → 帮助归属必须可解析（与命令目录渲染规则同口径）。

    command_catalog 的路由覆盖段按「条目 capability 文正则提 bot.* → 归属
    主题，否则内部说明，否则（未登记）」渲染；本断言锁死 has_rule 声明行
    全部可归属——新增路由能力漏登帮助主题/内部说明即红。
    """
    topic_by_capability: dict[str, str] = {}
    for entry in HELP_ENTRIES:
        for cid in re.findall(r"bot\.[a-z_]+", str(entry.get("capability", ""))):
            topic_by_capability.setdefault(cid, str(entry["topic"]))
    internal_notes = set(br.INTERNAL_CAPABILITY_NOTES)
    for decl in cr.ROUTE_CAPABILITY_DECLARATIONS:
        if not decl.has_rule:
            continue
        assert (
            decl.capability_id in topic_by_capability or decl.capability_id in internal_notes
        ), f"路由能力 {decl.capability_id}（{decl.kind}）无帮助主题归属"

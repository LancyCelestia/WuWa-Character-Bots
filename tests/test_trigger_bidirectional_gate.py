"""触发词双向机械门（P2-9）：路由侧 ↔ help 侧词级全量 diff。

治「路由有、help 无」类复发痛点（求籤事件先例：路由双正则收得下、
``/bot help 求籤`` 搜不到，坠 help 兜底）。既有门只做 topic 级 set 相等
（tests/test_documentation_consistency.py 的 _HELP_ALIAS_MAP 等势门）与
能力 id 级覆盖门，词级双向 diff 此前为空白；docs/route-matrix 门
（test_doc_sync_gates）自述「不做触发词全量等价比对」——本文件补齐。

双向语义（真值源各自机械提取后 diff，零手工词表拷贝）：
1. 路由→帮助：路由侧每个触发词（``verified_triggers`` 行为验证词 ∪
   ``DEFAULT_VERB_MAP`` 动词）必须在同能力 help 词表（aliases ∪
   triggers_nl ∪ triggers_nickname，按 capability 字段聚合）有落点。
2. 帮助→路由：help 每条触发词必须能被路由面命中——动词映射（昵称命令，
   「守岸人 决策」不坠 help 兜底）/ 行为检测器探针 / 自然语言归一
   （``detect_natural_command`` 的 capability_id 须落在本 topic 声明能力内）
   三选一。capability 字段自证无命令入口的纯文档 topic（doc_only）豁免。

现状缺口以**台账制**管理（体检不是改造，不改能力文件凑绿）：
- ``LEDGER_ROUTE_TO_HELP`` / ``LEDGER_HELP_TO_ROUTE`` 登记 2026-09-15 基线
  实测红点；双向棘轮——台账外新增缺口 → 硬断言失败自动浮出为工作清单，
  台账红点被修复 → 强制失败提醒清账。
- 可红性由**变异测试**常驻锁死：测试内构造缺口（删别名/删动词）→ 门必须
  变红，防门退化成永真的摆设。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.runtime.aliases import (
    CommandAliasResolver,
    normalize_command_text,
)
from scripts.extract_trigger_words import (
    build_help_trigger_side,
    build_inventory,
    build_route_trigger_side,
    flat_verb_map,
    gate_help_to_route,
    gate_route_to_help,
    live_detectors_by_capability,
)

INV = build_inventory()

# 路由侧：verified_triggers ∪ DEFAULT_VERB_MAP（归一键，按能力聚合）。
ROUTE_SIDE = build_route_trigger_side(INV)
# help 侧：aliases ∪ META 触发词（含 '/bot <名>' 派生落点）。
HELP_SIDE = build_help_trigger_side(INV["help_topics"])
# 方向2 路由面实跑件。
VERB_MAP_FLAT = flat_verb_map(INV)
DETECTORS = live_detectors_by_capability(INV)

# 双向门全量实跑结果（现状缺口，排序确定）。
GAPS_ROUTE_TO_HELP = gate_route_to_help(ROUTE_SIDE, HELP_SIDE)
VIOLATIONS_HELP_TO_ROUTE = gate_help_to_route(INV["help_topics"], VERB_MAP_FLAT, DETECTORS)

# ---------------------------------------------------------------------------
# 现状红点台账（2026-09-15 基线，修复后必须同步清账）
# ---------------------------------------------------------------------------
# 形态注记（交主会话裁决的四大类）：
# A 拼音词（全拼/缩写，T-Spec 拼音波入路由正则未入 help）；
# B 繁體孪生词（tra 波入路由未同步 help，求籤同型：菜譜/兌換/維基/歷史上的今天…）；
# C 自然语言句式（提醒做完族/group_info 口语族，help 只登记代表词）；
# D help 侧词在三个路由面（动词映射/检测器/NL 归一）都不可达（管理子命令
#   topic 未配昵称动词、上下文/下载/凭据/模型等 /bot <名> 族、NL 文档句式）。

LEDGER_ROUTE_TO_HELP: frozenset[tuple[str, str]] = frozenset({
    # bot.affinity（A：haogan 全拼/hgz 缩写等）
    ('bot.affinity', 'haogan'),
    ('bot.affinity', 'haoganzhi'),
    ('bot.affinity', 'hgz'),
    ('bot.affinity', 'qinmidu'),
    ('bot.affinity', 'qmd'),
    # bot.divination（英文 hexagrams/tarots）
    ('bot.divination', 'hexagrams'),
    ('bot.divination', 'tarots'),
    # bot.eat（B：菜譜/怎麼做；C：如何做/吃）
    ('bot.eat', 'recipes'),
    ('bot.eat', '吃'),
    ('bot.eat', '如何做'),
    ('bot.eat', '怎麼做'),
    ('bot.eat', '菜譜'),
    # bot.fx（B：兌換/換匯；A：duihuan/hh/huanhui；C：换汇/兑换）
    ('bot.fx', 'duihuan'),
    ('bot.fx', 'hh'),
    ('bot.fx', 'huanhui'),
    ('bot.fx', '兌換'),
    ('bot.fx', '兑换'),
    ('bot.fx', '换汇'),
    ('bot.fx', '換匯'),
    # bot.group_info（C：口语问句族）
    ('bot.group_info', '本群人数'),
    ('bot.group_info', '本群公告'),
    ('bot.group_info', '本群多大'),
    ('bot.group_info', '本群多少人'),
    ('bot.group_info', '本群精华'),
    ('bot.group_info', '本群资料'),
    ('bot.group_info', '群主'),
    ('bot.group_info', '群多大'),
    ('bot.group_info', '群多大了'),
    # bot.help（B：幫助——动词表有 /bot 幫助，help 页搜不到）
    ('bot.help', '幫助'),
    # bot.market（B：大盤；A：quanqiugushi/markets）
    ('bot.market', 'markets'),
    ('bot.market', 'quanqiugushi'),
    ('bot.market', '大盤'),
    # bot.meme（A：bqbc 等缩写族）
    ('bot.meme', 'biaoqingbaochansheng'),
    ('bot.meme', 'biaoqingbaoshengcheng'),
    ('bot.meme', 'biaoqingbaozhizuo'),
    ('bot.meme', 'biaoqingchansheng'),
    ('bot.meme', 'biaoqingzhizuo'),
    ('bot.meme', 'bqbc'),
    ('bot.meme', 'bqbs'),
    ('bot.meme', 'bqbz'),
    ('bot.meme', 'bqcs'),
    ('bot.meme', 'bqzz'),
    ('bot.meme', 'memegenerate'),
    ('bot.meme', 'memes'),
    ('bot.meme', '表情包生成'),
    # bot.meme_library（A：拼音/缩写族；C：表情随机族）
    ('bot.meme_library', 'biaoqingchouqian'),
    ('bot.meme_library', 'biaoqingku'),
    ('bot.meme_library', 'biaoqingsuiji'),
    ('bot.meme_library', 'biaoqingtongji'),
    ('bot.meme_library', 'bqcq'),
    ('bot.meme_library', 'bqk'),
    ('bot.meme_library', 'bqsj'),
    ('bot.meme_library', 'bqtj'),
    ('bot.meme_library', 'sjbq'),
    ('bot.meme_library', 'stealmeme'),
    ('bot.meme_library', 'suijibiaoqing'),
    ('bot.meme_library', 'suijibiaoqingbao'),
    ('bot.meme_library', 'toutu'),
    ('bot.meme_library', 'tt'),
    ('bot.meme_library', '表情库'),
    ('bot.meme_library', '表情抽签'),
    ('bot.meme_library', '表情随机'),
    ('bot.meme_library', '随机表情包'),
    # bot.music_mode（B：點歌模式；A：musicmode/songmode）
    ('bot.music_mode', 'musicmode'),
    ('bot.music_mode', 'songmode'),
    ('bot.music_mode', '點歌模式'),
    # bot.news（A：akb/cjxw/wb 等缩写与全拼族）
    ('bot.news', 'aikuaibao'),
    ('bot.news', 'aixinwen'),
    ('bot.news', 'akb'),
    ('bot.news', 'axw'),
    ('bot.news', 'caijingkuaibao'),
    ('bot.news', 'caijingxinwen'),
    ('bot.news', 'cjkb'),
    ('bot.news', 'cjxw'),
    ('bot.news', 'gjxw'),
    ('bot.news', 'guojixinwen'),
    ('bot.news', 'jinriredian'),
    ('bot.news', 'jrrd'),
    ('bot.news', 'kejixinwen'),
    ('bot.news', 'kjxw'),
    ('bot.news', 'wanbao'),
    ('bot.news', 'wb'),
    ('bot.news', 'zaobao'),
    # bot.reminder（C：做完/没做完族；A：reminders）
    ('bot.reminder', 'reminders'),
    ('bot.reminder', '做完'),
    ('bot.reminder', '办完'),
    ('bot.reminder', '完成'),
    ('bot.reminder', '我的提醒'),
    ('bot.reminder', '有哪些提醒'),
    ('bot.reminder', '沒做完'),
    ('bot.reminder', '没做完'),
    ('bot.reminder', '看看提醒'),
    ('bot.reminder', '还没做完'),
    ('bot.reminder', '还没弄完'),
    ('bot.reminder', '還沒做完'),
    ('bot.reminder', '還沒弄完'),
    # bot.stocks（A：gegu/gupiaojiage；C：股票）
    ('bot.stocks', 'gegu'),
    ('bot.stocks', 'gupiaojiage'),
    ('bot.stocks', '股票'),
    # bot.today_history（B：歷史上的今天；A：全拼）
    ('bot.today_history', 'lishishangdejintian'),
    ('bot.today_history', '歷史上的今天'),
    # bot.weather（动词表词无 help 落点：/bot help 天气预报 坠兜底）
    ('bot.weather', '天气预报'),
    ('bot.weather', '查询天气'),
    # bot.wiki（B：維基/維基百科；A：全拼）
    ('bot.wiki', 'weijibaike'),
    ('bot.wiki', '維基'),
    ('bot.wiki', '維基百科'),
})

LEDGER_HELP_TO_ROUTE: frozenset[tuple[str, str]] = frozenset({
    # 上下文/下载（/bot context、/bot download：无昵称动词）
    ('上下文', 'context'),
    ('上下文', '上下文'),
    ('下载', 'download'),
    ('下载', '下载'),
    # 个股行情（个股行情/市值须带公司名才可路由，单词不可达）
    ('个股行情', '个股行情'),
    ('个股行情', '市值'),
    # 偷表情（NL 文档句式变体）
    ('偷表情', '偷张表情包'),
    ('偷表情', '随机来张表情'),
    # 决策（决策引擎：动词只配了 决策/decision）
    ('决策', '决策引擎'),
    # 凭据（/bot cookie：全词不可达）
    ('凭据', 'alert'),
    ('凭据', 'cookie'),
    ('凭据', '凭据'),
    ('凭据', '凭证'),
    ('凭据', '憑據'),
    ('凭据', '憑證'),
    ('凭据', '登录凭证'),
    ('凭据', '登錄憑證'),
    # 历史上的今天（A：jrls 等；C：今日）
    ('历史上的今天', 'jinrilishi'),
    ('历史上的今天', 'jrls'),
    ('历史上的今天', 'today'),
    ('历史上的今天', 'todayinhistory'),
    ('历史上的今天', '今日'),
    # 商品行情（单词不可达，须带品种）
    ('商品行情', '商品行情'),
    # 回复/回执/审计（admin 子命令 topic 无昵称动词）
    ('回复', 'reply'),
    ('回复', '回复'),
    ('回复', '详略'),
    ('回执', 'receipt'),
    ('回执', '回执'),
    ('审计', 'audit'),
    ('审计', '审计'),
    # 对话（对话验收模块：只有 对话验收/dialogue 动词可达）
    ('对话', '对话'),
    ('对话', '对话测试'),
    # 帮助（菜单：help 别名但路由面不可达）
    ('帮助', '菜单'),
    # 快报（A：ainews）
    ('快报', 'ainews'),
    # 怪癖（/bot quirk：无昵称动词）
    ('怪癖', 'quirk'),
    ('怪癖', '人格怪癖'),
    ('怪癖', '怪癖'),
    # 接入（/bot setup llm：无昵称动词）
    ('接入', 'llmsetup'),
    ('接入', 'setup'),
    ('接入', '接入'),
    # 提醒（C：叫我/记得叫族未入路由词表）
    ('提醒', '叫我'),
    ('提醒', '定时提醒'),
    ('提醒', '提醒'),
    ('提醒', '提醒我'),
    ('提醒', '記得叫'),
    ('提醒', '记得叫'),
    # 搜索（/bot search：无昵称动词）
    ('搜索', 'search'),
    ('搜索', '搜索'),
    # 昵称（ALIAS 结构路由主题：词本身不是动词）
    ('昵称', 'alias'),
    ('昵称', '昵称'),
    # 暂停（恢复：动词表只有 暂停/继续/pause/resume）
    ('暂停', '恢复'),
    # 最近（/bot recent：无昵称动词）
    ('最近', 'recent'),
    ('最近', '最近'),
    # 模型（/bot model：无昵称动词）
    ('模型', 'llm'),
    ('模型', 'model'),
    ('模型', '切换模型'),
    ('模型', '模型'),
    ('模型', '渠道'),
    # 汇率（C：换算族；A：exchangerate）
    ('汇率', 'exchangerate'),
    ('汇率', '换算'),
    ('汇率', '換算'),
    # 点歌（播放：裸播放不在 NL/正则触发面）
    ('点歌', '播放'),
    # 用量（/bot model usage：无昵称动词）
    ('用量', 'usage'),
    ('用量', '用量'),
    ('用量', '监控'),
    ('用量', '花费'),
    ('用量', '账单'),
    # 笔记（C：看笔记 N/删笔记 N 文档式写法）
    ('笔记', '删笔记n'),
    ('笔记', '看笔记n'),
    # 维基（百科：可路由词是 维基/维基百科/wiki/wikipedia）
    ('维基', '百科'),
    # 群文件（/bot 群文件：无昵称动词）
    ('群文件', '群文件'),
    ('群文件', '群文件统计'),
    # 群策略（/bot group：无昵称动词）
    ('群策略', 'group'),
    ('群策略', '群'),
    ('群策略', '群策略'),
    # 聊天/自然语言/链接（结构路由主题：词为描述性）
    ('聊天', 'chat'),
    ('聊天', '聊天'),
    ('聊天', '闲聊'),
    ('自然语言', '自然语言'),
    ('自然语言', '自然语言命令'),
    ('链接', 'links'),
    ('链接', '直接粘贴平台链接'),
    ('链接', '链接'),
    # 草稿（auto_send：报存族不可达）
    ('草稿', 'autosend'),
    ('草稿', '報存'),
    ('草稿', '報存給發郵件'),
    ('草稿', '报存'),
    ('草稿', '报存给发邮件'),
    ('草稿', '自动发送'),
    ('草稿', '草稿'),
    # 萌娘百科（是谁/是什么须带实体词，单词不可达）
    ('萌娘百科', '是什么'),
    ('萌娘百科', '是什麼'),
    ('萌娘百科', '是誰'),
    ('萌娘百科', '是谁'),
    ('萌娘百科', '是谁？'),
    # 行情（A：stockmarket）
    ('行情', 'stockmarket'),
    # 表情（表情包产生：路由词是 bqbz/表情包生成 族）
    ('表情', '表情包产生'),
    # 解析/设置/路由/身份/队列（admin 子命令 topic 无昵称动词）
    ('解析', 'parse'),
    ('解析', '解析'),
    ('设置', 'runtime'),
    ('设置', '参数'),
    ('设置', '參數'),
    ('设置', '設置'),
    ('设置', '设置'),
    ('设置', '运行时'),
    ('路由', 'route'),
    ('路由', 'routes'),
    ('路由', '路由'),
    ('身份', 'identity'),
    ('身份', '会话身份'),
    ('身份', '身份'),
    ('队列', 'queue'),
    ('队列', '队列'),
})


# ---------------------------------------------------------------------------
# 双向门 vs 台账（棘轮）
# ---------------------------------------------------------------------------


def test_route_to_help_gate_matches_ledger() -> None:
    """方向1：路由→帮助缺口必须与台账严格相等（新增即红、修复催清账）。"""
    gaps = set(GAPS_ROUTE_TO_HELP)
    unknown = sorted(gaps - LEDGER_ROUTE_TO_HELP)
    stale = sorted(LEDGER_ROUTE_TO_HELP - gaps)
    assert not unknown, (
        f"新增「路由有、help 无」缺口 {len(unknown)} 条（未登记台账，"
        f"先补 help 别名或登记 LEDGER_ROUTE_TO_HELP），前 15 条：{unknown[:15]}"
    )
    assert not stale, (
        f"台账红点已修复 {len(stale)} 条，请从 LEDGER_ROUTE_TO_HELP 清账，"
        f"前 15 条：{stale[:15]}"
    )


def test_help_to_route_gate_matches_ledger() -> None:
    """方向2：帮助→路由缺口必须与台账严格相等（新增即红、修复催清账）。"""
    violations = {(item["topic"], item["word"]) for item in VIOLATIONS_HELP_TO_ROUTE}
    unknown = sorted(violations - LEDGER_HELP_TO_ROUTE)
    stale = sorted(LEDGER_HELP_TO_ROUTE - violations)
    assert not unknown, (
        f"新增「help 有、路由坠兜底」缺口 {len(unknown)} 条（未登记台账，"
        f"先补路由面或登记 LEDGER_HELP_TO_ROUTE），前 15 条：{unknown[:15]}"
    )
    assert not stale, (
        f"台账红点已修复 {len(stale)} 条，请从 LEDGER_HELP_TO_ROUTE 清账，"
        f"前 15 条：{stale[:15]}"
    )


# ---------------------------------------------------------------------------
# 门自检：真值源非空（防提取器空转导致门永真）
# ---------------------------------------------------------------------------


def test_gate_truth_sources_nonempty() -> None:
    """路由侧/help 侧/动词表必须实质非空，门才有比对意义。"""
    assert sum(len(words) for words in ROUTE_SIDE.values()) >= 400
    assert len(INV["help_topics"]) >= 70
    assert len(VERB_MAP_FLAT) >= 50
    assert len(GAPS_ROUTE_TO_HELP) + len(VIOLATIONS_HELP_TO_ROUTE) >= 100


# ---------------------------------------------------------------------------
# L-C04 extractor 棘轮：bot.tts 触发词表必须持续可见（T68 修复锁）
# ---------------------------------------------------------------------------


def test_tts_verified_triggers_ratchet() -> None:
    """bot.tts 行为验证词与内置词表等势且不坠盲区清单（L-C04 棘轮）。

    根因史：domains 迁移后 ``is_tts_command`` 退化为单行委托
    （``bool(extract_tts_text(...))``），harvest 只摘检测函数体内字面量 +
    ``__globals__`` 直引常量，词表住委托实现函数的 globals —— 棘轮对 TTS
    整体失明（M-01 劫持样本溜进去的哨兵盲区，T15/T39 实证）。修法=
    能力级委托追踪；本锁钉「再断链必红」：词表再被藏进追不动的委托
    （跨模块/动态构造），verified 掉空或与真值源漂移即失败。
    """
    from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
        DEFAULT_TRIGGER_WORDS,
    )

    entry = INV["capabilities"]["bot.tts"]
    assert entry["verified_triggers"], "bot.tts verified_triggers 掉空（棘轮失明复发）"
    missing = sorted(set(DEFAULT_TRIGGER_WORDS) - set(entry["verified_triggers"]))
    extra = sorted(set(entry["verified_triggers"]) - set(DEFAULT_TRIGGER_WORDS))
    assert not missing and not extra, (
        f"bot.tts 行为验证词与内置词表漂移：missing={missing} extra={extra}"
    )
    blind = [
        capability_id
        for capability_id, item in INV["capabilities"].items()
        if not item["verified_triggers"]
    ]
    assert "bot.tts" not in blind, "bot.tts 重新坠入无 verified 盲区清单"


# ---------------------------------------------------------------------------
# 可红性（变异测试）：测试内构造缺口 → 门必须红
# ---------------------------------------------------------------------------


def test_route_to_help_gate_catches_dropped_alias() -> None:
    """方向1 可红性：从 help 注册表全字段删「随机图」→ 门必须报缺口。"""
    mutated = {topic: dict(info) for topic, info in INV["help_topics"].items()}
    entry = dict(mutated["随机图"])
    for field in ("aliases", "triggers_nl", "triggers_nickname"):
        entry[field] = tuple(w for w in entry.get(field) or () if w != "随机图")
    assert any(
        entry[f] != (mutated["随机图"].get(f) or ())
        for f in ("aliases", "triggers_nl", "triggers_nickname")
    ), "变异前提失效：词不在注册表"
    mutated["随机图"] = entry
    gaps = set(gate_route_to_help(ROUTE_SIDE, build_help_trigger_side(mutated)))
    assert ("bot.randpic", "随机图") in gaps, "门失效：删除别名未报缺口（永真摆设）"
    added = gaps - set(GAPS_ROUTE_TO_HELP)
    assert added == {("bot.randpic", "随机图")}, (
        f"变异应恰好引入一条缺口，实际多出：{sorted(added - {('bot.randpic', '随机图')})[:10]}"
    )


def test_help_to_route_gate_catches_dropped_verb() -> None:
    """方向2 可红性：从动词映射删「决策」→「守岸人 决策」坠兜底，门必须报。"""
    verb_map = {k: v for k, v in VERB_MAP_FLAT.items() if k != "决策"}
    assert len(verb_map) == len(VERB_MAP_FLAT) - 1, "变异前提失效：动词本不在映射"
    violations = {
        (item["topic"], item["word"])
        for item in gate_help_to_route(INV["help_topics"], verb_map, DETECTORS)
    }
    assert ("决策", "决策") in violations, "门失效：删除动词未报缺口（永真摆设）"
    added = violations - {
        (item["topic"], item["word"]) for item in VIOLATIONS_HELP_TO_ROUTE
    }
    assert added == {("决策", "决策")}, (
        f"变异应恰好引入一条缺口，实际多出：{sorted(added - {('决策', '决策')})[:10]}"
    )


@pytest.mark.parametrize("verb", ["功能管理", "feature"])
@pytest.mark.parametrize("prefix", ["守岸人", "/岸宝"])
def test_feature_trigger_resolves_to_real_runtime_capability(verb: str, prefix: str) -> None:
    resolver = CommandAliasResolver(nicknames=["守岸人", "岸宝"])
    resolution = resolver.resolve(f"{prefix}{verb} get bot.plugin.weather")
    assert resolution is not None
    assert resolution.capability_id == "bot.runtime"
    assert resolution.rest_text == "get bot.plugin.weather"
    # 管理昵称只引导到 /bot；中文引导也必须能进入现有 feature 分支。
    assert normalize_command_text(f"{resolution.verb} {resolution.rest_text}") == (
        "feature get bot.plugin.weather"
    )
    assert resolver.resolve(f"{verb} get bot.plugin.weather") is None
    assert resolver.resolve(f"{prefix}{verb}说明") is None


def test_feature_help_gate_catches_removed_route_without_exemption() -> None:
    verbs = {key: value for key, value in VERB_MAP_FLAT.items() if key not in {"功能管理", "feature"}}
    violations = gate_help_to_route({"功能管理": INV["help_topics"]["功能管理"]}, verbs, DETECTORS)
    assert {(item["topic"], item["word"]) for item in violations} == {
        ("功能管理", "功能管理"), ("功能管理", "feature"),
    }

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
3. 台账行不等于实物：``LEDGER_HELP_TO_ROUTE_EVIDENCE`` 给「已登记放行」的词逐枚
   钉住**由谁消化**（函数 + 函数体内的调用名，AST 取数不吃行号）与今天的实测
   结果；``test_ledger_entries_still_backed_by_real_objects`` 双向反查——词被从
   帮助册删掉而台账还留着 ⇒ 红，登记的消化者改名/摘掉 ⇒ 红。登记与实物分家即
   是这张台账最坏的失效形态（2026-09-25 S266 立，起因＝亲密模式七枚新台账）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
    CommandAliasResolver,
    normalize_command_text,
)
from scripts.extract_trigger_words import (
    build_help_trigger_side,
    build_inventory,
    build_route_trigger_side,
    classify_help_topics,
    flat_verb_map,
    gate_help_to_route,
    gate_route_to_help,
    live_detectors_by_capability,
    normalize_trigger_key,
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
    # 参与者族九枚（2026-09-26 S-T-GRP-2「参与者按记忆算」那条腿）：路由侧谓词
    # ``is_group_info_command`` 收词即生效（``base_router.group_info_match`` 直调它，
    # 零路由改动），help 侧词条归 ``echo.py`` 的「群信息」topic。**2026-09-26 主会话清账**：
# 参与者九枚（群里都有谁/本群都有谁/群里谁说过话/本群谁说过话/群参与者/本群参与者/
# 都有谁说过话/我都跟谁聊过/跟谁聊过）已补进 ``_HELP_ENTRIES['群信息'].aliases`` 与
# ``_HELP_ENTRY_META['群信息'].triggers_nickname``，本门「台账红点被修复 ⇒ 强制提醒清账」
# 那一把当场打红提醒后删掉；其余九枚（本群人数/本群公告/群主…）**仍是缺口**，继续挂账。
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
    # 亲密模式（2026-09-24 晚「亲密档分级二批」新建 topic、本波 2026-09-25 逐枚现算补登记）
    # ⚠ 这七枚**不是一件事**，分两档登记、反查腿也分两档（见
    # LEDGER_HELP_TO_ROUTE_EVIDENCE）：
    #   甲·三枚开关词＝「真生效、但没有 RouteKind 宿主」——话说到整句时消息经
    #     base_router 的 chat_match 落到 bot.chat，之后由 **bot.chat 能力体内**
    #     `build_chat_result` 吃 content_route.match_intimate_command 上钉/解钉并
    #     直接回确认句（chat.py:2468-2523 当时坐标）。本门的三个面（昵称动词 /
    #     行为检测器 / 自然语言归一）都只到「消息交给谁」这一层，看不见能力体内的
    #     第四面，所以判「不可达」是门的视野所限，不是词失效——实测 verdict 会变：
    #     开→(intimate,l1)、深开→(intimate,l2 且首跳换 grok 优先)、关→(normal,"")。
    #     ⚠ 「真生效」是有条件的：总闸 bot_content_route_enabled ∧ 会话准入
    #     （explicit_allowed_for_session）两支都得成立；群聊白名单为空时整群不准入
    #     ⇒ 这一句既不上钉也不回确认句，只当普通对话。登记的是「消化点在真件里、
    #     且在它自己的准入门内确实改行为」，不是「谁说了都管用」（逐枚实测读数见
    #     .superpowers/sdd/2026-09-24-central-dispatch/probes/s266-probe2-e2e.py 的
    #     C_private/D_group 两列，与 SEAT-S266 §2 的表同源）。
    #     另一处门的视野所限顺带记下：face2 在 bot.chat 上是**空表**（现算
    #     live_detectors_by_capability()['bot.chat'] == []，全仓有检测器的能力里
    #     没有 bot.chat），所以任何宿主为 bot.chat 的帮助词都只能从 face1/face3
    #     求通行——既有台账里 ('聊天','chat') 那一族就是这么进来的。
    #   乙·四枚帮助检索词＝**设计上就不是命令**，与既登记的同型条目（('聊天','chat')、
    #     ('快报','ainews')、('维基','百科')）同类：只在 echo._HELP_ALIAS_MAP 里当
    #     `/bot help <词>` 的落点。帮助正文从未把它们写成可说的命令（index 只列
    #     「整句开关：亲密模式 开|深开|关」），故非「页面骗人」。
    # 反查腿（test_ledger_entries_still_backed_by_real_objects）执法两件事：
    # 词还在帮助册里 + 登记的消化者还真在消化——词被删而台账还在＝红。
    ('亲密模式', '亲密模式开'),      # 甲：上钉浅档
    ('亲密模式', '亲密模式深开'),    # 甲：上钉深档（换首跳）
    ('亲密模式', '亲密模式关'),      # 甲：两档齐解
    ('亲密模式', '亲密模式'),        # 乙：本 topic 自身检索键
    ('亲密模式', '亲密档位'),        # 乙：中文别名检索键
    ('亲密模式', 'intimate'),        # 乙：英文检索键
    ('亲密模式', 'qinmimoshi'),      # 乙：拼音检索键
})

# ---------------------------------------------------------------------------
# 台账行的「实物凭证」（S266，2026-09-25 现算）：逐枚写清由谁消化、住在哪一行
# ---------------------------------------------------------------------------
# 为什么要有这张表：LEDGER_HELP_TO_ROUTE 只是「允许这些词不可达」的一句许可，
# 它自己不证明任何东西——词被从帮助册删掉、或消化它的代码被搬走/摘掉，许可都会
# 变成一张空头账（门照样绿）。本表把每条许可钉到**可反查的实物**上：
#   kind="capability-body" → 消化者 = (模块, 函数, 函数内必须存在的调用名)，
#                             并钉住该词今天的实测结果（mode/tier）。
#   kind="help-search-key" → 消化者 = echo._HELP_ALIAS_MAP 的落点（topic 名），
#                             且必须**仍然不是**亲密档开关（否则分类该重判）。
# ⚠ 只登记「亲密模式」这一批（本波现算过七枚）。其余既有台账行本波未核，
#   不为其背书——将来谁核谁补，别拿这张表当全量已审的证据。

# 甲·三枚开关词的凭证＝手写字面键（消化点住 bot.chat 能力体，正则真身 content_route.py:134-153）。
_EVIDENCE_INTIMATE_BODY: dict[tuple[str, str], dict[str, Any]] = {
    ("亲密模式", "亲密模式开"): {
        "kind": "capability-body",
        "module": "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py",
        "function": "build_chat_result",
        "call": "match_intimate_command",
        "expects": ("intimate", "l1"),
    },
    ("亲密模式", "亲密模式深开"): {
        "kind": "capability-body",
        "module": "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py",
        "function": "build_chat_result",
        "call": "match_intimate_command",
        "expects": ("intimate", "l2"),
    },
    ("亲密模式", "亲密模式关"): {
        "kind": "capability-body",
        "module": "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py",
        "function": "build_chat_result",
        "call": "match_intimate_command",
        "expects": ("normal", ""),
    },
}

# S-TRIG 收编（2026-09-26）：乙档凭证原先在此手抄一枚四词元组——那是本文件台账行「乙：…检索键」
# 四行之外、对同一词集的**同文件第二份字面量**，被 tests/test_trigger_word_copy_ratchet.py 点名
# 为 44>42 越界副本之一（D1）。现改为从 LEDGER_HELP_TO_ROUTE 派生（该 topic 的台账行减甲档字面键）：
# 词面在文件里只声明一次，凭证覆盖面由台账结构保证。台账行本身仍是本门对 echo 真身的独立声明
# （整账若从 echo 派生才会拆双向检查＝恒真；同文件去重不放宽任何门的判据）。
LEDGER_HELP_TO_ROUTE_EVIDENCE: dict[tuple[str, str], dict[str, Any]] = {
    **_EVIDENCE_INTIMATE_BODY,
    # 乙·帮助检索词＝台账里该 topic 除甲档三枚开关词外的全部行（_HELP_ALIAS_MAP 由 echo.py 派生，
    # 唯一读点 echo.normalize_help_topic）。
    **{
        row: {
            "kind": "help-search-key",
            "module": "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py",
            "function": "normalize_help_topic",
            "resolves_to": row[0],
        }
        for row in LEDGER_HELP_TO_ROUTE
        if row[0] == "亲密模式" and row not in _EVIDENCE_INTIMATE_BODY
    },
}


def _function_call_names(module_path: str, function_name: str) -> set[str]:
    """AST 取某函数体内的调用名集合（行号会漂，函数与调用名不会）。

    路径按仓库根解析，不靠 pytest 的当前工作目录。
    """
    source = (Path(__file__).resolve().parents[1] / module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == function_name:
            return {
                str(getattr(call.func, "id", None) or getattr(call.func, "attr", ""))
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
            }
    raise AssertionError(f"函数 {function_name} 不在 {module_path}（凭证坐标已失效）")


def _ledger_evidence_problems(
    evidence: dict[tuple[str, str], dict[str, Any]],
    *,
    ledger: set[tuple[str, str]],
    help_words: dict[str, set[str]],
    resolve_help_topic: Any,
    match_command: Any,
    call_names: Any,
) -> list[str]:
    """纯函数版反查腿：返回「台账行已失去实物」的人话清单（空＝逐枚对得上）。

    四个面的失效形态各不同，缺一面就有一条空头账能活下来：
    ①有凭证却没进台账 / 台账里留着凭证没有的行 ⇒ 两本账分家；
    ②词已从帮助册消失而台账与凭证还在 ⇒ 为不存在的词放行；
    ③登记的消化函数里再没有那个调用名（改名、搬走、整段摘除）⇒ 真生效已失真；
    ④检索键不再是检索键（帮助落点漂了，或被做成了命令）⇒ 归类已失真。
    参数全部注入（`resolve_help_topic`/`match_command`/`call_names`），所以本函数
    可以在测试里被注毒复跑，而不是只在「一切正常」时被自证。
    """
    problems: list[str] = []
    covered_topics = {topic for topic, _ in evidence}
    for key in sorted(set(evidence) - ledger):
        problems.append(f"凭证有、台账没有：{key}（该词未被登记放行，不该悄悄存在）")
    for topic in sorted(covered_topics):
        for key in sorted({k for k in ledger if k[0] == topic} - set(evidence)):
            problems.append(f"台账有、凭证没有：{key}（放行却没有实物可反查）")
    for (topic, word), record in sorted(evidence.items()):
        if word not in help_words.get(topic, set()):
            problems.append(f"{topic}/{word}：帮助册里已无此词，台账与凭证成空头账")
            continue
        kind = str(record.get("kind") or "")
        if kind == "capability-body":
            if str(record.get("call") or "") not in call_names(
                str(record.get("module") or ""), str(record.get("function") or "")
            ):
                problems.append(
                    f"{topic}/{word}：{record.get('function')}() 里已无 "
                    f"{record.get('call')} 调用（消化者已被摘掉或改名）"
                )
            verdict = match_command(word)
            if verdict != tuple(record.get("expects") or ()):
                problems.append(
                    f"{topic}/{word}：实测结果 {verdict!r} 与登记的 "
                    f"{tuple(record.get('expects') or ())!r} 不符（词不再改行为？）"
                )
        elif kind == "help-search-key":
            if resolve_help_topic(word) != record.get("resolves_to"):
                problems.append(
                    f"{topic}/{word}：帮助落点漂到 "
                    f"{resolve_help_topic(word)!r}（不再是 {record.get('resolves_to')!r}）"
                )
            if match_command(word) is not None:
                problems.append(f"{topic}/{word}：已变成开关命令，凭证的 help-search-key 归类失效")
        else:
            problems.append(f"{topic}/{word}：未知 kind={kind!r}")
    return problems


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


# ---------------------------------------------------------------------------
# 台账行的实物反查腿（S266）：登记 ≠ 实物，逐枚反查「词还在 + 消化者还在」
# ---------------------------------------------------------------------------


def _live_evidence_inputs(
    topics: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """把反查腿的四个注入位接到今天的真件上（生产代码，非夹具）。

    `topics` 缺省取 `INV["help_topics"]`（echo._HELP_ENTRIES 的机械提取），注毒用例
    可以传一份改过的注册表进来——注在**注册表层**而不是预先算好的词集上，才真的
    把 `echo 帮助册 → classify_help_topics → 反查腿` 这条链走一遍（本仓为「把毒注
    在不会被执行的路径上、测试却绿」那型假绿烧过两次，见台账 #50）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import content_route

    source = INV["help_topics"] if topics is None else topics
    return {
        "ledger": set(LEDGER_HELP_TO_ROUTE),
        "help_words": {
            topic: set(parsed["words"])
            for topic, parsed in classify_help_topics(source).items()
        },
        "resolve_help_topic": echo.normalize_help_topic,
        "match_command": content_route.match_intimate_command,
        "call_names": _function_call_names,
    }


def test_ledger_entries_still_backed_by_real_objects() -> None:
    """反查腿实跑：每条凭证都对得上今天的实物（词在帮助册、消化者还在吃它）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo

    # 先自证尺没瞎：本腿读的 `INV["help_topics"]` 必须逐字等于 echo 的活注册表，
    # 否则「词还在」这条判据测的是提取器缓存、不是生产件（注毒注在不会被执行的路径
    # 上＝本仓烧过两次的假绿形态，见台账 #50）。
    live_entries = {str(entry["topic"]): entry for entry in echo._HELP_ENTRIES}
    assert set(live_entries) >= {topic for topic, _ in LEDGER_HELP_TO_ROUTE_EVIDENCE}
    for (topic, word), record in sorted(LEDGER_HELP_TO_ROUTE_EVIDENCE.items()):
        # 归一口与门自身完全一致（classify_help_topics 也用 normalize_trigger_key）：
        # 帮助册写「亲密模式 关」，台账写归一后的「亲密模式关」，两侧不同尺就永远对不上。
        live_words = {
            normalize_trigger_key(item)
            for item in (
                *live_entries[topic]["aliases"],
                *(echo._HELP_ENTRY_META.get(topic, {}).get("triggers_nl") or ()),
                *(echo._HELP_ENTRY_META.get(topic, {}).get("triggers_nickname") or ()),
            )
        }
        assert word in live_words, f"尺与生产件脱钩：{topic} 的活注册表里已无 {word}"
        if str(record.get("kind") or "") == "help-search-key":
            assert echo.normalize_help_topic(word) == topic
    problems = _ledger_evidence_problems(LEDGER_HELP_TO_ROUTE_EVIDENCE, **_live_evidence_inputs())
    assert not problems, "台账与实物分家：" + "；".join(problems)


def test_ledger_leg_catches_help_word_removed() -> None:
    """注毒①：从**帮助注册表**删一枚在册真身词（qinmimoshi）⇒ 陈旧台账腿必红。

    毒注在注册表层（`INV["help_topics"]` 的一份副本）而不是预先算好的词集上，
    于是 `echo 帮助册 → classify_help_topics → 反查腿` 整条链被走一遍。
    """
    mutated = {topic: dict(info) for topic, info in INV["help_topics"].items()}
    entry = dict(mutated["亲密模式"])
    before = tuple(entry["aliases"])
    entry["aliases"] = tuple(word for word in before if word != "qinmimoshi")
    assert entry["aliases"] != before, "注毒前提失效：这枚词本不在帮助册 aliases 里"
    mutated["亲密模式"] = entry
    problems = _ledger_evidence_problems(LEDGER_HELP_TO_ROUTE_EVIDENCE, **_live_evidence_inputs(mutated))
    assert len(problems) == 1, f"注毒①应只引入一条破绽，实际：{problems}"
    assert "qinmimoshi" in problems[0] and "空头账" in problems[0], problems[0]


def test_ledger_leg_catches_consumer_stripped() -> None:
    """注毒②：把消化点换成「函数里不再调用 match_intimate_command」⇒ 开关词逐枚报红。

    这条是老棘轮**看不见**的那一格：词仍留在帮助册、仍不可路由 ⇒ `LEDGER == 缺口`
    照常成立，双向门全绿，而「这枚词真改行为」的登记理由已经死了。
    期望发数由凭证表自己派生（不硬编码），以后谁补登记不必回来改这里。
    """
    expect_stripped = {
        word for (_topic, word) in LEDGER_HELP_TO_ROUTE_EVIDENCE
        if str(LEDGER_HELP_TO_ROUTE_EVIDENCE[(_topic, word)].get("kind") or "") == "capability-body"
    }
    assert expect_stripped, "注毒②前提失效：凭证表里没有 capability-body 形态的行"
    inputs = _live_evidence_inputs()
    inputs["call_names"] = lambda _module, _function: set()
    problems = _ledger_evidence_problems(LEDGER_HELP_TO_ROUTE_EVIDENCE, **inputs)
    assert len(problems) == len(expect_stripped), (
        f"注毒②应恰红 {len(expect_stripped)} 枚开关词，实际：{problems}"
    )
    assert all("消化者已被摘掉或改名" in problem for problem in problems), problems


def test_ledger_leg_catches_category_drift() -> None:
    """注毒③：让「帮助检索键」那批突然变成开关命令 ⇒ 归类失效必须浮出。"""
    drift_words = {
        word for (_topic, word) in LEDGER_HELP_TO_ROUTE_EVIDENCE
        if str(LEDGER_HELP_TO_ROUTE_EVIDENCE[(_topic, word)].get("kind") or "") == "help-search-key"
    }
    assert drift_words, "注毒③前提失效：凭证表里没有 help-search-key 形态的行"
    inputs = _live_evidence_inputs()
    original = inputs["match_command"]

    def poisoned(word: str) -> Any:
        if word in drift_words:
            return ("intimate", "l1")
        return original(word)

    inputs["match_command"] = poisoned
    problems = _ledger_evidence_problems(LEDGER_HELP_TO_ROUTE_EVIDENCE, **inputs)
    assert len(problems) == len(drift_words), (
        f"注毒③应恰红 {len(drift_words)} 枚检索键，实际：{problems}"
    )
    assert all("help-search-key 归类失效" in problem for problem in problems), problems


def test_ledger_leg_catches_ledger_evidence_split() -> None:
    """注毒④：台账撤掉一行而凭证留着（两本账分家）⇒ 当场红。"""
    victim = min(
        key for key, record in LEDGER_HELP_TO_ROUTE_EVIDENCE.items()
        if str(record.get("kind") or "") == "capability-body"
    )
    inputs = _live_evidence_inputs()
    inputs["ledger"] = inputs["ledger"] - {victim}
    problems = _ledger_evidence_problems(LEDGER_HELP_TO_ROUTE_EVIDENCE, **inputs)
    assert any("凭证有、台账没有" in problem for problem in problems), problems
    assert any(repr(victim[1]) in problem or victim[1] in problem for problem in problems), problems

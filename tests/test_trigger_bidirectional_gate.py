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
import re
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
    # 〔席 CMD-TRILINGUAL 2026-10-11 清账〕'菜譜'/'怎麼做' 两枚繁體形已从台账删掉：路由侧
    # `is_recipe_command` 一直认它们，是帮助册 `吃什么.aliases` 只写了简体形——册上同族形已在、
    # 路由却只有简体那枚＝「三轴不同级」那一格，修法＝把繁体形补成在册触发词（echo.py 同批）。
    ('bot.eat', 'recipes'),
    ('bot.eat', '吃'),
    ('bot.eat', '如何做'),
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
# 〔席 cb-hs3 2026-10-12 清账〕'本群人数'/'本群精华'/'本群资料' 三枚已补进
# ``_HELP_ENTRIES['群信息'].aliases``：它们的繁體孪生（本群人數/本群精華/本群資料）是本轮
# 册侧补齐时入册的，入册后简体形按三轴同级腿②反过来被点名＝册上少一轴，故一并补登简体正形，
# 三行随之 stale 删账；其余六枚（本群公告/本群多大/群主…）**仍是缺口**，继续挂账。
    ('bot.group_info', '本群公告'),
    ('bot.group_info', '本群多大'),
    ('bot.group_info', '本群多少人'),
    ('bot.group_info', '群主'),
    ('bot.group_info', '群多大'),
    ('bot.group_info', '群多大了'),
    # bot.help（B：幫助——动词表有 /bot 幫助，help 页搜不到）
    # 〔席 CMD-TRILINGUAL 2026-10-11 清账〕'幫助' 已补进 `帮助.aliases`，本行按 stale 腿删掉。
    # bot.market（B：大盤；A：quanqiugushi/markets）
    # 〔同上〕'大盤' 已补进 `行情.aliases`。
    ('bot.market', 'markets'),
    ('bot.market', 'quanqiugushi'),
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
    # 〔席 cb-hs3 2026-10-12 清账〕'表情库' 已补进 `_HELP_ENTRY_META['表情册'].triggers_nl`
    # （走 META 不走 aliases＝检索落点仍归先建键的「表情收库」，本主题只多一条可搜键），
    # 其繁體孪生 '表情庫' 同批进 `偷表情.aliases`，两轴齐 ⇒ 本行 stale 删账。
    # 〔席 CMD-TRILINGUAL 2026-10-11 清账〕'表情抽签'/'表情随机'/'随机表情包' 三枚**简体**形
    # 删账：`is_meme_library_command` 本就认它们，而帮助册 `偷表情.aliases` 只抄了繁體那三枚
    # （表情抽籤/表情隨機/隨機表情包）＝同一族里册只写一轴、路由认两轴，已按「不统一的全改过来」
    # 把简体形补进册。'表情抽签' 那类「随机表情」册上有繁體而路由不认的形**没动**（不在本轮判域）。
    # bot.music_mode（B：點歌模式；A：musicmode/songmode）
    # 〔同上〕'點歌模式' 已补进 `点歌.aliases`。
    ('bot.music_mode', 'musicmode'),
    ('bot.music_mode', 'songmode'),
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
    # 〔席 cb-hs3 2026-10-12 清账〕'办完' 与它的繁體孪生 '辦完' 双形同批补进
    # ``_HELP_ENTRY_META['笔记'].triggers_nl``（notes._NOTES_DONE_RE 是 reminder 路由腿真身，
    # 一处补形两侧跟随）⇒ 本行 stale 删账。'做完'/'完成'/'没做完' 那几枚仍挂账不动。
    ('bot.reminder', '完成'),
    ('bot.reminder', '沒做完'),
    ('bot.reminder', '没做完'),
    ('bot.reminder', '还没做完'),
    ('bot.reminder', '还没弄完'),
    ('bot.reminder', '還沒做完'),
    ('bot.reminder', '還沒弄完'),
    # 〔席 CMD-TRILINGUAL 2026-10-11 清账〕'我的提醒'/'看看提醒'/'有哪些提醒' 三枚删账：提醒册
    # aliases 原先只登记它们各自的**拼音形**（wodetixing/wdtx、kankantixing/kktx、younaxietixing/
    # ynxt），**中文正形一枚都没登记**＝拼音与中文两轴在册侧不同级（`is_reminder_command` 三枚
    # 中文形本来就认）。修法＝把中文正形补进册（echo.py 同批），不是把拼音摘掉。
    # bot.stocks（A：gegu/gupiaojiage；C：股票）
    # 〔同上〕'股票' 已补进 `个股行情.aliases`（册上原有同族拼音形 gupiao，缺中文正形）。
    ('bot.stocks', 'gegu'),
    ('bot.stocks', 'gupiaojiage'),
    # bot.today_history（B：歷史上的今天；A：全拼）
    # 〔同上〕'歷史上的今天' 已补进 `历史上的今天.aliases`（册上繁體形此前一枚都没有）。
    ('bot.today_history', 'lishishangdejintian'),
    # bot.weather（动词表词无 help 落点：/bot help 天气预报 坠兜底）
    # 〔席 CMD-TRILINGUAL 2026-10-11 清账〕'天气预报'/'查询天气' 两枚删账：天气册只抄了繁體
    # '天氣預報'/'查天氣'，简体正形没抄＝简繁两轴在册侧单形；两枚简体形 `weather._COMMAND_RE`
    # 与 DEFAULT_VERB_MAP 都认，已补进册。
    # bot.wiki（B：維基/維基百科；A：全拼）
    # 〔同上〕'維基'/'維基百科' 已补进 `维基.aliases`（册上原只有简体 '维基'，繁體一枚没有）。
    # 'weijibaike' 仍挂账＝拼音全拼形册上无、路由侧 verified 有，不属三轴同级（无同族在册形）。
    ('bot.wiki', 'weijibaike'),
})

LEDGER_HELP_TO_ROUTE: frozenset[tuple[str, str]] = frozenset({
    # 上下文/下载（/bot context、/bot download：无昵称动词）
    ('上下文', 'context'),
    ('上下文', '上下文'),
    ('下载', 'download'),
    ('下载', '下载'),
    # 个股行情（个股行情/市值须带公司名才可路由，单词不可达）
    # 〔席 cb-hs3 2026-10-12 清账〕'个股行情' 一枚已修：stocks._STOCK_HINT_RE 现认裸形，
    # 且本轮把反向缺形 '个股'／'股票價格' 补进 `个股行情.aliases` 后该 topic 的可达能力面
    # 覆盖了它 ⇒ stale 腿点名，删账。'市值' 仍须公司名才可路由，继续挂账。
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
    # 〔席 CMD-TRILINGUAL 2026-10-11 清账·本轮唯一的「路由只认单一形态」实装反例〕'表情包产生'
    # 删账：帮助册 `表情.aliases` 写着简体 '表情包产生'，`meme._COMMAND_RE` 那一族手抄了
    # '表情产生'(简)／'表情產生'／'表情包產生'(繁) 三枚、**独漏 '表情包产生'**——同族繁體认、
    # 简体不认，用户照册敲就被拒。修法＝把这枚简体形补进路由正则（同批 meme.py），不是删册上的词。
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


# ===========================================================================
# G-3 腿①（席 CB-CMDUNIFY-20261008）：「帮助页宣称的 /bot 子令 ⊆ root 真受理集合」
# ===========================================================================
# 与既有两把尺的分工（刻意不重抄实物，避免第二真身）：
# - `tests/test_claims_subset_implementation_gate.py` 腿 A 判「宣称有没有落点」，落点
#   认 E1 分发链字面 ∪ E2 判定正则 ∪ E3 别名字册三条腿。它的 E1 只吃 `==`/`startswith`
#   的**字面量**，不吃 `MODULE_ALIASES` 归一，所以 `/bot 描写` 那枚到今天还红（既存红，
#   本席不代修）；本腿把宣称先过 `normalize_command_text`（＝生产真口）再比，量的正是
#   "敲下去到底派到哪一支"。
# - 词级双向台账（本文件上面那两本）管"册上的词路由认不认"，看不见"这条入口能不能真出结果"。
# - **本腿新咬的那一格**＝G-1 之后链尾不再有"什么都往 help 兜底"的 Catch-all：一条宣称
#   再也不能靠兜底 laundering 成"看起来有回应"。所以兜底形必须逐枚**显式在册**，
#   白名单只有下列四组，多一枚都要在交接报告里点名。

_INIT_PY = (
    Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime" / "__init__.py"
)

#: 在册兜底形（G-1 显式登记，唯一一把尺；扩一枚＝报告点名）：
#:   ""                         ＝ `/bot` 裸打 → 帮助总览（主人的手感，不许变）
#:   "status"                   ＝ `/bot status` → 状态（旧 else 支的正身）
#:   HELP_COMMAND_HEAD_WORDS    ＝ `/bot help|帮助|幫助 …` → 总览/深度页
#:   _COMMANDS_CATALOG_QUERY     ＝ `/bot commands|cmds|命令|命令列表|命令目录` → 命令目录
def _registered_fallback_forms() -> set[str]:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo

    return (
        {"", "status"}
        | {str(w).lower() for w in echo.HELP_COMMAND_HEAD_WORDS}
        | {str(w).lower() for w in echo._COMMANDS_CATALOG_QUERY}
    )


def _status_handler_ast() -> ast.AsyncFunctionDef:
    tree = ast.parse(_INIT_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_status":
            return node
    raise AssertionError("根 __init__.py 里找不到 _handle_status（命令面已搬家？）")


def command_text_literal_heads() -> set[str]:
    """根分发链上对 `command_text` 的字面比较 → 词头集（== / in 容器 / startswith，含元组形）。"""
    heads: set[str] = set()

    def add(token: object) -> None:
        text = str(token or "").strip().lower()
        if text:
            heads.add(text.split(maxsplit=1)[0])

    for node in ast.walk(_status_handler_ast()):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) \
                and node.left.id == "command_text":
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant):
                    add(comparator.value)
                elif isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
                    for element in comparator.elts:
                        if isinstance(element, ast.Constant):
                            add(element.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "startswith" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "command_text" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant):
                add(first.value)
            elif isinstance(first, (ast.Tuple, ast.List, ast.Set)):
                for element in first.elts:
                    if isinstance(element, ast.Constant):
                        add(element.value)
    return heads


#: 🔴 `、`（顿号）必须在排除集里：册上并列命令行就按它排（`/bot status、/bot pause|resume`），
#: 少了这一枚正则会一路吞到下一个空格，把 `status、/bot` 当成**一枚**词头报出来——
#: 假红的同时更要紧的是**吞掉了后半枚**（`pause` 从此不在宣称面上＝尺瞎）。2026-10-08 实测。
_BOT_CLAIM_PATTERN = r"/bot\s*([^\s｜|<>（）()，,。、；;：:]+)"


def bot_claim_heads(text: object) -> list[str]:
    """一枚册上字符串里所有 `/bot X` 宣称的词头（先过生产归一口 normalize_command_text）。"""
    import re

    heads: list[str] = []
    for raw in re.findall(_BOT_CLAIM_PATTERN, str(text or "")):
        head = normalize_command_text(raw).split(maxsplit=1)[0].strip().lower()
        if head:
            heads.append(head)
    return heads


def help_page_subcommand_claims() -> dict[str, str]:
    """帮助页与主题登记册**自己申报**的 `/bot` 入口：topic → 词头（每 topic 记第一枚）。

    取数三处真身：`_HELP_ENTRY_META[topic]["capability"]` ∪ `["examples"]` ∪
    `capability_registry` 的 `HelpTopicDecl.capability` ∪ `_HELP_ENTRIES` 的 `index`
    （册顶那一行就是给用户照着敲的）。本腿不另立第二份词表。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry,
    )

    claims: dict[str, str] = {}

    def note(topic: object, text: object) -> None:
        found = bot_claim_heads(text)
        if found:
            claims.setdefault(f"{topic}", found[0])

    for topic, record in echo._HELP_ENTRY_META.items():
        note(topic, record.get("capability"))
        for example in record.get("examples") or ():
            note(topic, example)
    for entry in echo._HELP_ENTRIES:
        note(entry.get("topic"), entry.get("index"))
    for decl in getattr(capability_registry, "HELP_TOPIC_DECLARATIONS", ()):
        note(getattr(decl, "topic", ""), getattr(decl, "capability", ""))
    return claims


def _chain_predicate_legs() -> list[str]:
    """链上「整支交给一个谓词」的判定名（现网只有一支：`is_memory_command_text(command_text)`）。

    这类支没有字面词头可比——它的受理集住在谓词自家模块里。本腿**不去抄那张词表**
    （抄＝第二真身），而是把谓词本身 import 回来、拿宣称词头当场问它一遍。
    """
    names: list[str] = []
    for node in ast.walk(_status_handler_ast()):
        # 🔴 只看**判定式**（`If.test`），不看支体：整颗 handler 里 walk 会把支体内的
        # `route_memory_command(command_text, sender_id=…, db_path=…)` 也当成谓词收进来，
        # 而它不是"一个字符串进、布尔出"的谓词——当场 TypeError＝这条 slash 判据瞎掉。
        if not isinstance(node, ast.If):
            continue
        for call in ast.walk(node.test):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.args
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == "command_text"
            ):
                names.append(call.func.id)
    return sorted(set(names))


def _predicate_accepts(head: str) -> bool:
    """链上任一谓词认这枚词头 ⇒ root 真受理（执行生产谓词原文，零第二份词表）。"""
    import importlib

    plugins_root = _INIT_PY.parent
    for name in _chain_predicate_legs():
        for path in plugins_root.rglob("*.py"):
            rel = path.relative_to(plugins_root).as_posix()
            if f"def {name}(" not in path.read_text(encoding="utf-8", errors="ignore"):
                continue
            module = importlib.import_module(
                "plugins.bot_unified_runtime." + rel[: -len(".py")].replace("/", ".")
            )
            predicate = getattr(module, name, None)
            if callable(predicate) and predicate(head):
                return True
    return False


def root_accepted_head_set(claims: dict[str, str] | None = None) -> set[str]:
    from tests.test_claims_subset_implementation_gate import landing_evidence

    accepted = (
        command_text_literal_heads()
        | set(landing_evidence())
        | _registered_fallback_forms()
    )
    # 宣称值既可能是单枚词头也可能是词头清单（一枚主题宣称多个可敲形），
    # 直接 `set(values())` 会在清单上炸 `TypeError: unhashable type: 'list'`
    # ＝整条 slash 面判据当场瞎掉（2026-10-08 实测）。所以先摊平再判。
    for value in (claims or {}).values():
        heads = value if isinstance(value, (list, tuple, set, frozenset)) else (value,)
        for head in heads:
            if not isinstance(head, str):
                continue
            if head not in accepted and _predicate_accepts(head):
                accepted.add(head)
    return accepted


def _claims_subset_problems(claims: dict[str, str], accepted: set[str]) -> list[str]:
    return sorted(
        f"帮助页宣称 /bot {head}（topic＝{topic}）在 root 真受理集合里没有落点"
        for topic, head in claims.items()
        if head not in accepted
    )


def test_help_page_claims_are_subset_of_root_accepted_heads() -> None:
    """主门：册上每枚 `/bot X` 宣称，root 必须真收得住——收不住就是手册骗人。"""
    claims = help_page_subcommand_claims()
    assert claims, "尺读空＝宣称面搬家了，本腿先报警而不是静默绿"
    accepted = root_accepted_head_set()
    assert accepted, "尺读空＝受理面取数失效，本腿先报警而不是静默绿"
    assert "decision" in command_text_literal_heads(), "G-2（乙）的 decision 分发支不见了"
    problems = _claims_subset_problems(claims, root_accepted_head_set(claims))
    assert not problems, "宣称 ⊄ 受理：" + "；".join(problems)


def test_root_accepted_leg_catches_fabricated_claim() -> None:
    """注毒②：往帮助页塞一枚 root 不认的宣称（`/bot zzzfabricated`）⇒ 本腿必红。"""
    poisoned = dict(help_page_subcommand_claims(), 注毒样本="zzzfabricated")
    problems = _claims_subset_problems(poisoned, root_accepted_head_set())
    assert any("zzzfabricated" in p for p in problems), (
        "注毒未奏效：宣称面多一枚没牙的命令，门照样绿 ⇒ 本腿已退化成摆设"
    )


def test_root_accepted_leg_catches_unwired_claim() -> None:
    """注毒①：往 root 塞一枚真未登记动词（受理面凭空多一支 `zzznewverb`）而册上不写 ⇒
    由 `_claims_subset_problems` 的对偶面验：把一枚**真在册词头**从受理集合里摘掉必红。

    两头都咬实物：②动宣称、①动受理；只动一边就绿的尺不算尺。
    """
    claims = help_page_subcommand_claims()
    accepted = root_accepted_head_set(claims)
    claimed = set(claims.values())
    victims = sorted(claimed & accepted)
    assert victims, "注毒前提失效：宣称与受理没有交集，本腿其实什么都没比"
    victim = victims[0]
    problems = _claims_subset_problems(
        {f"注毒/{victim}": victim}, accepted - {victim}
    )
    assert any(victim in p for p in problems), (
        f"注毒未奏效：受理面少了 {victim}，门照样绿"
    )
    # 对偶：真未登记动词绝不许出现在受理集合里（兜底形只有那四组）
    from tests.test_claims_subset_implementation_gate import landing_evidence

    extra = accepted - command_text_literal_heads() - set(landing_evidence()) - claimed
    assert extra <= _registered_fallback_forms(), (
        f"兜底形白名单被扩了：{sorted(extra - _registered_fallback_forms())}"
    )


# ===========================================================================
# G-4 腿（席 CMD-SLASH-HEADS-20261008）：`_HELP_ENTRIES` **命令行**宣称的 `/bot <词头>`
# 必须在 root 链上找到落点（分支字面量或谓词支当场执行）
# ===========================================================================
# 上面那把尺（G-3 腿①）读的是 `META.capability` ∪ `META.examples` ∪ `_HELP_ENTRIES.index`
# ∪ registry `HelpTopicDecl.capability`，**每主题只记第一枚词头**，且看不见 `lines[]`——
# 而 `lines[]` 才是 HELP-1 定的命令行唯一事实源（深页的【指令与参数】段由它派生）。
# 于是「册子在命令行里教了一条没牙的 `/bot 天气 <城市>`」这一格今天没人管：
# G-1 拒止支上线后，它会当场把用户拒掉，而帮助页照旧教着。本腿补的就是这一格。
# 🔴 同门加腿、不另立第二件门：宣称面仍由 `bot_claim_heads`（先过生产归一口
# `normalize_command_text`）取词，受理面仍由 `root_accepted_head_set`（链上字面量 ∪
# E2/E3 判定正则与别名字册 ∪ 在册兜底形 ∪ 谓词支**当场执行**）作答。

#: 判据 7 的命令行骨架（`^…：作用=…；参数=…；内容=…；意义=`）——只有合这个骨架的行
#: 才是「命令行」，其余是讲解散文（讲解行按甲批口径该迁 `_HELP_EXTRA_LINES`）。
_HELP_COMMAND_LINE_RE = re.compile(r"^([^：]+：)作用=.+；参数=.+；内容=.+；意义=")
#: 行末独立短句「（中文｜英文）同义：…」——甲批定的形：同义**不进命令段**，只在这句里出现，
#: 所以它同样是宣称面（写了就得有牙），也必须过这把尺。
_HELP_SYNONYM_CLAUSE_RE = re.compile(r"[\u4e00-\u9fff]*同义[:：](.+)$")


def help_entry_command_line_claims() -> dict[str, list[str]]:
    """topic → `_HELP_ENTRIES[*]["lines"]` 命令行里宣称的 `/bot` 词头（命令段＋同义短句）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo

    claims: dict[str, list[str]] = {}
    for entry in echo._HELP_ENTRIES:
        topic = str(entry.get("topic") or "")
        for line in entry.get("lines") or ():
            text = str(line or "")
            if not _HELP_COMMAND_LINE_RE.match(text):
                continue  # 讲解行不是命令行，不在本尺面上
            found = bot_claim_heads(_HELP_COMMAND_LINE_RE.match(text).group(1))
            synonym = _HELP_SYNONYM_CLAUSE_RE.search(text)
            if synonym is not None:
                found = [*found, *bot_claim_heads(synonym.group(1))]
            if found:
                claims.setdefault(topic, []).extend(found)
    return claims


def _command_line_claim_problems(claims: dict[str, list[str]], accepted: set[str]) -> list[str]:
    return sorted(
        f"帮助册命令行宣称 /bot {head}（topic＝{topic}）在 root 链上找不到落点"
        for topic, heads in claims.items()
        for head in set(heads)
        if head not in accepted
    )


def test_help_entry_command_line_claims_land_on_root_chain() -> None:
    """主门：`lines[]` 命令行（含行末「…同义：…」短句）里每枚 `/bot 词头` 都得有牙。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo

    claims = help_entry_command_line_claims()
    assert claims, "尺读空＝命令行骨架或词头取数口塌了，本腿先报警而不是静默绿"
    # 宣称面确实覆盖了本波补的那几枚（尺不许只对着空集自证）
    landed_topics = {str(entry["topic"]) for entry in echo._HELP_ENTRIES if entry.get("lines")}
    assert set(claims) <= landed_topics
    accepted = root_accepted_head_set(claims)
    problems = _command_line_claim_problems(claims, accepted)
    assert not problems, "命令行宣称 ⊄ root 受理：" + "；".join(problems)


def test_command_line_leg_catches_new_headless_claim() -> None:
    """注毒：往某一枚**合法骨架**的命令行里塞一枚没牙词头（`/bot zzzheadless`）⇒ 必红。

    注在**行末同义短句**上（＝甲批那形），因为「命令段有牙、同义没牙」正是本波最容易
    再犯的一格：补了英文正形忘了中文同义，用户照册敲中文就被拒止支拒掉。
    """

    claims = help_entry_command_line_claims()
    poisoned_topic = next(iter(sorted(claims)))
    poisoned = dict(claims, **{poisoned_topic: [*claims[poisoned_topic], "zzzheadless"]})
    problems = _command_line_claim_problems(poisoned, root_accepted_head_set(claims))
    assert any("zzzheadless" in problem for problem in problems), (
        "注毒未奏效：命令行多教了一条没牙的命令（还是同义短句那一格），门照样绿"
    )
    # 反向不误伤：同一枚词头真有落点时不得被点名
    real = sorted({head for heads in claims.values() for head in heads})
    clean_problems = _command_line_claim_problems({poisoned_topic: real[:1]}, root_accepted_head_set(claims))
    assert not clean_problems, f"在册真词头被误判没牙：{clean_problems}"


def test_claim_tokenizer_keeps_every_enum_item_on_the_ruler() -> None:
    """量具自证：`/bot A、/bot B` 必须拆成**两枚**词头，后半枚不许被吞进前一枚的串里。

    2026-10-08 实测的反面：排除集缺 `、` 时正则一路吞到空格 ⇒ 整行只吐 `status、/bot` 一枚，
    既造出「/bot status、/bot 在 root 链上找不到落点」这枚假红，又把真词头 `pause` 从宣称面上
    **整枚吃掉**。后者比假红贵得多——那一格此后怎么写没牙命令都没人管，而门照绿。
    🔴 断言只认拆出来的**序列本身**：拿「报错文案里有没有这枚字面」当判据会被合并串蒙混过关
    （合并后 `status、/bot zzzheadless` 照样含 `zzzheadless` 子串）。
    """
    assert bot_claim_heads("/bot status、/bot pause|resume：") == ["status", "pause"]

    headless = bot_claim_heads("/bot status、/bot zzzheadless")
    assert headless == ["status", "zzzheadless"], f"没牙的后半枚被吞掉了：{headless}"
    problems = _command_line_claim_problems({"注毒": headless}, root_accepted_head_set())
    assert problems == [
        "帮助册命令行宣称 /bot zzzheadless（topic＝注毒）在 root 链上找不到落点"
    ], f"注毒点名不精确（合并串会把 `status` 或整串一起咬进来）：{problems}"


# ===========================================================================
# G-5 腿（席 CMD-TRILINGUAL，2026-10-11）：命令面「三轴同级」在**路由/派发面**的逐族一致
# ===========================================================================
# 主人的裁定（三轴同级）：①英文大小写相等 ②简体／繁体相等 ③拼音＝全拼 + 首字母 + 大小写三
# 种形态相等。这套等价在**帮助页展示面**早有投影件锁着，在派发面此前只有
# `tests/test_narration_alias_dispatch.py` 一段守 `/bot <词头>`（`MODULE_ALIASES` 一张表）；
# 「帮助册/命令目录登记的触发词 ↔ 路由认的词」这两面**从没按族比过**——上面那两本账是
# **词级**的（这枚词在不在对面），按构造看不见「同族两枚字面里路由只认一枚」：
# `normalize_trigger_key` 两侧都 casefold ⇒ 大小写轴在词级 diff 里被压平；繁简两枚是**不同**
# 字面，只会被当成两条独立缺口**分别记账**（＝台账 #72 那型「收编即藏问题」）。本腿按族判。
#
# 判域与判据（全部现算，本文件不写一份词面清单——AGENTS 规则 10）：
# * 族关系只在**已登记的字面之间**配对，绝不给「册上没写的形」发判定（v1 探针给每枚中文词
#   现造拼音形，现算 212 枚全是造词，作废）。折形真身＝`zhconv`、读音真身＝
#   `scripts/gen_trigger_pinyin.py`（全拼/首字母/`ABBR_MAX_LEN` 口径一字未动）——与
#   `runtime/aliases.py`、`test_narration_alias_dispatch.py` 同一根，本腿**不另起**第二套
#   lower/繁转简/拼音逻辑（那正是本波在治的病）。
# * 路由判定复用门自己那三张面（`_route_face_hit`＝动词映射 ∪ 行为检测器 ∪ 自然语言归一）
#   与既算好的 `VIOLATIONS_HELP_TO_ROUTE`/`GAPS_ROUTE_TO_HELP`，不新开一把路由尺。
# * 大小写轴本腿**明写看不见**（判据过 `normalize_trigger_key` 就被压平），那一轴由
#   `test_narration_alias_dispatch.py` 的 `case_fold_problems` 在词头面守；本腿只咬简繁轴与
#   拼音↔中文轴在册侧/路由侧的成对缺形。
#
# 本波现算清账 18 条（`LEDGER_ROUTE_TO_HELP` 17 + `LEDGER_HELP_TO_ROUTE` 1，逐条批注写在两本
# 账里），此后任何新增「同族只认一枚」当场红。两本例外册（`LEDGER_AXIS_PROBE_BLIND` /
# `LEDGER_AXIS_ROUTE_WITHHELD`）各带 stale 反查：条目被修好却不删 ⇒ 一样红。

TOPICS = classify_help_topics(INV["help_topics"])

_TRADITIONAL_LOCALE = "zh-tw"
_SIMPLIFIED_LOCALE = "zh-cn"

#: 例外册①（**路由只认单形·本席文件域之外**）：`axis_verb_script_problems` 现算出的缺形里，
#: 住在各能力自家触发正则里的那些。本波把中央动词表 `DEFAULT_VERB_MAP` 那 21 枚缺繁體对形的
#: 全补进那一张表（一個出口、零第二套折形逻辑）；剩下的 46 枚散在 bond/consent/divination/
#: emergency_info/group_info/host_state/media_archive/meme_library/reminder/stocks 十张能力正则里
#: ＝本席文件域之外（四席并发，按规则 7 互斥切分）＋`词面级独立声明债` 那把门在 HEAD 已红
#: （436>430，台账 #77★「加键账册没跟」），此时再往 10 个文件里塞 46 枚孪生字面＝替别的席
#: 加债。**登记不是放行**：反查腿 `test_axis_script_register_is_neither_stale_nor_growing`
#: 判「现算集合 == 本册」——新增一枚当场红、修好一枚不删也红，只准缩不许长。
#: 逐枚给的是（能力, 路由认的那枚, 路由不认的同族形），判据尺在函数体里现问 `zhconv`。
LEDGER_AXIS_SCRIPT_ROUTE_OPEN: frozenset[tuple[str, str, str]] = frozenset({
})

#: 例外册②（刻意只认单轴）：路由认的中文形、册上按族该登记却没登记的形。**本波现算为空**——
#: 主人裁的是「不统一的全改过来」，所以这里默认不许有货；真出现「刻意不登记」那一格，
#: 须逐枚写理由并同批补反查，不许悄悄往里塞。
LEDGER_AXIS_ROUTE_WITHHELD: frozenset[tuple[str, str]] = frozenset()

from zhconv import (
    convert as _zhconvert,  # 真身：pyproject 在册运行时依赖（折形唯一出口）
)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def axis_family_variants(word: str) -> dict[str, set[str]]:
    """一枚字面的三轴同族形（按轴分组；**只用于配对**，不构成新触发词）。

    简繁只收**可逆对**（折过去再折回来相等才算同族）——单向折形会把无关词拉进同一族＝尺变松；
    拼音走真身的全拼与首字母（含 `ABBR_MAX_LEN` 截断口径），并铺开大小写三形态。
    """
    out: dict[str, set[str]] = {"case": set(), "script": set(), "pinyin": set()}
    text = str(word or "")
    if not text:
        return out
    if not _has_cjk(text):
        out["case"] = {text.lower(), text.upper(), text.capitalize(), text.title()} - {text}
        return out
    from zhconv import convert as _zhconvert  # 真身：pyproject 在册运行时依赖

    simplified = _zhconvert(text, _SIMPLIFIED_LOCALE)
    for folded in (_zhconvert(text, _TRADITIONAL_LOCALE), simplified):
        if folded != text and _zhconvert(folded, _SIMPLIFIED_LOCALE) == simplified:
            out["script"].add(folded)
    from scripts import gen_trigger_pinyin as _gp  # 真身：读音表＋多音字覆写＋缩写口径

    for base in (_gp.word_full_pinyin(text), _gp.word_abbr(text)[: _gp.ABBR_MAX_LEN]):
        if base and not _has_cjk(base):
            out["pinyin"] |= {base, base.lower(), base.upper(), base.capitalize()}
    return out


def registered_surface_forms(
    topic: str, topics: dict[str, dict[str, Any]] | None = None
) -> set[str]:
    """某 topic 在帮助册登记的**原拼写**字面（不归一——注毒要能在注册表层被看见）。"""
    source = INV["help_topics"] if topics is None else topics
    info = source.get(topic) or {}
    return {
        str(word)
        for field in ("aliases", "triggers_nl", "triggers_nickname")
        for word in info.get(field) or ()
    }


def _axis_variants(word: str) -> set[str]:
    return {v for bucket in axis_family_variants(word).values() for v in bucket}


def axis_relations(forms: set[str]) -> dict[str, set[str]]:
    """字面集内部的同族关系（**对称**）。

    🔴 必须对称：`axis_family_variants('菜譜')` 给得出 `菜谱`，反过来
    `axis_family_variants('jrls')` 只给得出大小写三形、**给不出**它的中文源形 `今日历史`
    ——拼音轴是「中文→拉丁」的单向派生。非对称写法会让拼音↔中文那一格在 ASCII 侧整面失明
    （本腿第一轮犯过这个错：例外册反查报「同族再无可达形」＝尺瞎，不是问题已修）。
    判同族＝`b ∈ variants(a)` 或 `a ∈ variants(b)`；折形与读音全部现问真身。
    """
    variants = {form: _axis_variants(form) for form in forms}
    related: dict[str, set[str]] = {form: set() for form in forms}
    for left in sorted(forms):
        for right in sorted(forms):
            if left == right:
                continue
            if right in variants[left] or left in variants[right]:
                related[left].add(right)
    return related


def _axis_label(word: str, siblings: set[str]) -> str:
    """给报出来的同族形标是哪一轴（只影响文案，不参与判定）。"""
    buckets = axis_family_variants(word)
    reverse = {s for s in siblings if word in _axis_variants(s)}
    if siblings & buckets["script"] or any(buckets["script"] & _axis_variants(s) for s in reverse):
        return "script"
    if siblings & buckets["pinyin"] or any(buckets["pinyin"] & _axis_variants(s) for s in reverse):
        return "pinyin"
    return "case"


def _registered_keys(source: dict[str, dict[str, Any]], topic: str) -> set[str]:
    """某 topic 在册触发词形的归一键集（与 `classify_help_topics` 同一把尺）。"""
    return {
        key
        for field in ("aliases", "triggers_nl", "triggers_nickname")
        for word in (source.get(topic) or {}).get(field) or ()
        if (key := normalize_trigger_key(word))
    }


def axis_help_side_problems(
    blind: frozenset[tuple[str, str]] = frozenset(),
    topics: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """腿①（写了不认）：在册却不可达的**中文形**，若它的同族形在同一 topic 可达 ⇒ 报红。

    判域只收中文形（`_has_cjk`）：册上「写了拉丁形而路由不认」的那一族属**覆盖面**问题
    （词级台账 `LEDGER_HELP_TO_ROUTE` 那本，逐枚有「斜杠门槛/文档式写法」凭据），
    不属「同一枚命令的三种写法互相等价」这一问——把两问混成一把尺会既咬不动真缺口、
    又把 44 枚已裁过的有意缺席重新拖红（本席第一轮就犯过）。
    本波实证＝`表情包产生`：册上写着简体形，`meme._COMMAND_RE` 只手抄了
    `表情產生`／`表情包產生` 兩枚繁體，同族繁體认、简体不认。
    """
    source = INV["help_topics"] if topics is None else topics
    parsed_topics = classify_help_topics(source)
    # 默认走门已经算好的那本 `VIOLATIONS_HELP_TO_ROUTE`（全量实跑，省一遍探针）；
    # 一旦注入改了过的注册表（注毒腿），**必须对那份副本重跑生产判据**——读缓存的注毒
    # 等于把毒注在不会被执行的路径上（台账 #50 那型假绿）。
    items = (
        VIOLATIONS_HELP_TO_ROUTE
        if topics is None
        else gate_help_to_route(source, VERB_MAP_FLAT, DETECTORS)
    )
    unreachable: dict[str, set[str]] = {}
    for item in items:
        unreachable.setdefault(str(item["topic"]), set()).add(str(item["word"]))
    problems: list[str] = []
    for topic in sorted(parsed_topics):
        parsed = parsed_topics[topic]
        if parsed["doc_only"]:
            continue
        registered = _registered_keys(source, topic)
        missing = unreachable.get(topic, set()) & registered
        reachable = registered - missing
        relations = axis_relations(registered)
        for word in sorted(missing):
            if not _has_cjk(word) or (topic, word) in blind:
                continue
            landed = relations[word] & reachable
            if not landed:
                continue
            problems.append(
                f"{topic}/{word}（轴={_axis_label(word, landed)}）：同族形 {sorted(landed)} "
                f"路由认、它不认＝册上写了却不认（三轴不同级）"
            )
    return sorted(set(problems))


def axis_route_side_problems(
    withheld: frozenset[tuple[str, str]] = LEDGER_AXIS_ROUTE_WITHHELD,
    topics: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """腿②（认得不登记）：路由认的**中文形**不在册、而同族另一枚在册 ⇒ 报红。

    同样只收中文形：`haogan`/`akb` 这类「路由有拼音、册上只有中文」的拉丁形属既有
    `LEDGER_ROUTE_TO_HELP` 的 A 类覆盖面账（本波现算 46 枚，其中还有 `bz`/`sz`/`sm` 这种
    在册规格里「永不启用／不建议」的刻意缺形），与本问不同判域。
    这一腿专咬「新增一枚只认单轴的路由词、顺手进词级台账就绿」那一格。本波清账 17 条全属
    这一型：`菜譜`/`怎麼做`/`幫助`/`大盤`/`點歌模式`/`歷史上的今天`/`維基`/`維基百科`
    （简繁轴：册上只抄简体）·`表情抽签`/`表情随机`/`随机表情包`（册上只抄繁體）·
    `我的提醒`/`看看提醒`/`有哪些提醒`/`股票`（册上只抄拼音、中文正形一枚没有）·
    `天气预报`/`查询天气`。
    """
    parsed_topics = classify_help_topics(INV["help_topics"] if topics is None else topics)
    problems: list[str] = []
    for capability_id, words in sorted(ROUTE_SIDE.items()):
        help_words: set[str] = set()
        for parsed in parsed_topics.values():
            if capability_id in (parsed["caps"] | parsed["admin_caps"]):
                help_words |= parsed["words"]
        for word in sorted(words - help_words):
            if not _has_cjk(word) or (capability_id, word) in withheld:
                continue
            landed = sorted(axis_relations(words | help_words)[word] & help_words)
            if landed:
                problems.append(
                    f"{capability_id}/{word}：路由认它、帮助册/命令目录只登记了同族 {landed}"
                    f"＝册上少一轴（三轴不同级）"
                )
    return sorted(set(problems))


def axis_verb_script_problems(
    with_held: frozenset[tuple[str, str, str]] = LEDGER_AXIS_SCRIPT_ROUTE_OPEN,
) -> list[str]:
    """腿③（路由只认单形）：路由认的中文触发字面，其简繁孪生两侧都不认 ⇒ 报红。

    判域＝路由侧全部在册字面（`verified_triggers` ∪ `DEFAULT_VERB_MAP`）里的中文形；
    孪生折形现问 `zhconv`（只收可逆对）。这一问此前**没有任何尺在管**：词级双向台账比的是
    「这枚词在不在对面」，而这里两枚形其中一枚根本不存在于任何一侧，词级 diff 看不见。
    本波把 `DEFAULT_VERB_MAP` 那 21 枚缺繁體对形的补齐（`為什麼`/`記憶`/`查詢`/`吃什麼`…
    一张中央表，`CommandAliasResolver` 的 `re.IGNORECASE` 只折大小写、**不折简繁**）；
    剩下的 44 枚住在各能力自家的触发正则里（bond/divination/emergency_info/group_info/
    host_state/media_archive/meme_library/reminder/stocks），本席文件域之外、四席并发，
    故逐枚登进 `LEDGER_AXIS_SCRIPT_ROUTE_OPEN` 只准缩不许长。
    """
    problems: list[str] = []
    for capability_id, words in sorted(ROUTE_SIDE.items()):
        pool = set(words) | HELP_SIDE.get(capability_id, set())
        for word in sorted(words):
            if not _has_cjk(word):
                continue
            simplified = _zhconvert(word, _SIMPLIFIED_LOCALE)
            for twin in (_zhconvert(word, _TRADITIONAL_LOCALE), simplified):
                if twin == word or not twin or _zhconvert(twin, _SIMPLIFIED_LOCALE) != simplified:
                    continue  # 简繁同形，或单向折形（不可逆＝不算同族）
                if twin in pool:
                    continue
                if (capability_id, word, twin) in with_held:
                    continue
                problems.append(
                    f"{capability_id}/{word}：路由认简体形却不认同族繁體 {twin}＝只认单一形态"
                )
    return sorted(set(problems))


def test_three_axis_help_side_forms_route_alike() -> None:
    """主门①：帮助册/命令目录登记的中文形，其同族形路由认了它也必须认。"""
    assert {"菜谱", "菜譜", "怎麼做"} <= registered_surface_forms("吃什么"), (
        "尺读空＝在册字面取数塌了"
    )
    problems = axis_help_side_problems()
    assert not problems, "命令面三轴不同级（写了不认）：" + "；".join(problems)


def test_three_axis_route_side_forms_registered_alike() -> None:
    """主门②：路由认的中文形，同族既已在册登记，它自己也须登记（例外册须保持空）。"""
    assert not LEDGER_AXIS_ROUTE_WITHHELD, (
        f"例外册被塞了货 {sorted(LEDGER_AXIS_ROUTE_WITHHELD)}——「不统一的全改过来」，"
        "要留单轴形须在报告里逐枚点名并补反查"
    )
    problems = axis_route_side_problems()
    assert not problems, "命令面三轴不同级（认得不登记）：" + "；".join(problems)


def test_three_axis_verb_table_has_traditional_twins() -> None:
    """主门③：中央动词表的中文动词必须簡繁成对（本波把 21 枚缺形补进那张表）。

    执法面只判 `DEFAULT_VERB_MAP`（一张表、一个出口）；各能力正则那 44 枚走例外册。
    """
    verbs = {verb for group in INV["verb_map_groups"].values() for verb in group}
    assert verbs, "尺读空＝动词表取数塌了"
    problems: list[str] = []
    for verb in sorted(verbs):
        if not _has_cjk(verb):
            continue
        simplified = _zhconvert(verb, _SIMPLIFIED_LOCALE)
        for twin in (_zhconvert(verb, _TRADITIONAL_LOCALE), simplified):
            if twin == verb or not twin:
                continue
            if _zhconvert(twin, _SIMPLIFIED_LOCALE) != simplified:
                continue
            if twin not in verbs:
                problems.append(f"动词表缺繁體/简体对形：{verb} → {twin}")
    assert not problems, "；".join(problems)


def test_three_axis_route_leg_catches_dropped_catalog_twin() -> None:
    """注毒②：从帮助册摘掉一枚繁體同族形（`菜譜`）⇒ 腿②必须点名 `bot.eat/菜譜`。

    毒注在**注册表副本**上（`INV["help_topics"]` 的一份拷贝），经
    `classify_help_topics → axis_route_side_problems` 真走一遍，不是改预先算好的词集
    （台账 #50 那型「注在不会被执行的路径上＝假绿」）。
    """
    forms = registered_surface_forms("吃什么")
    assert {"菜谱", "菜譜"} <= forms, f"注毒前提失效：简繁两枚本不都在册：{sorted(forms)}"
    mutated = {topic: dict(info) for topic, info in INV["help_topics"].items()}
    entry = dict(mutated["吃什么"])
    entry["aliases"] = tuple(word for word in entry["aliases"] if word != "菜譜")
    assert "菜譜" not in entry["aliases"], "注毒没摘掉那枚"
    mutated["吃什么"] = entry
    problems = axis_route_side_problems(topics=mutated)
    assert any("bot.eat/菜譜" in problem for problem in problems), (
        "注毒未奏效：册上少一枚繁體同族形，腿②照样绿＝本腿已退化成摆设"
    )
    assert not any("bot.eat/菜譜" in p for p in axis_route_side_problems()), (
        "未注毒那遍不该点名——两遍读的是同一份缓存"
    )


def test_three_axis_help_leg_catches_unroutable_registered_twin() -> None:
    """注毒①：往帮助册登记一枚路由根本不认的繁體形（`主人在幹嘛`）⇒ 腿①必须点名。

    这枚不是编的：`日程.aliases` 在册且可路由的是简体 `主人在干嘛`（NL 面 `question_intent`
    只手抄简体那一枚），繁體同族 `主人在幹嘛` 三个路由面都坠不住——注进副本即当场浮出。

    锚点换代留账（席 cb-hs3，2026-10-12 三轴同级册侧收口）：本腿原注 `占卜/佔一卦`，
    那枚在**第二层**（13 枚能力自家正则补孪生形）落地后已变成可路由形——`divination.
    _DIVINATION_COMMAND_RE` 现认 `佔一卦` ⇒ 注入它不再是「写了不认」，腿必然看不见毒；
    而第三层（册侧）又按主人裁「认得不登记」把 `佔一卦` 登记进 `占卜.aliases`，与本腿前置
    `assert "佔一卦" not in forms` **直接互斥**。两层都按裁定落过地，失效的是锚点而非判据，
    故只换锚、不放宽尺：换到「册上确实未登记＋三面确实不认＋同族形在册且可认」的真实一对
    （现算候选＝`axis_help_side_problems` 注毒前置同款折形判据，全树 23 对，本腿取其中一枚）。
    🔴 反证同批锁死：`axis_help_side_problems()` 未注毒那遍必须**不**点名任何一枚——若哪天
    有人把 NL 面简繁补齐、这对缺口消失，前置 `assert` 当场红催换锚，不会静默退化成摆设。
    """
    forms = registered_surface_forms("日程")
    assert "主人在干嘛" in forms and "主人在幹嘛" not in forms, f"注毒前提失效：{sorted(forms)}"
    mutated = {topic: dict(info) for topic, info in INV["help_topics"].items()}
    entry = dict(mutated["日程"])
    entry["aliases"] = tuple(entry["aliases"]) + ("主人在幹嘛",)
    mutated["日程"] = entry
    problems = axis_help_side_problems(topics=mutated)
    assert any("日程/主人在幹嘛" in problem for problem in problems), (
        f"注毒未奏效：册上多一枚路由不认的繁體形，腿①照样绿：{problems}"
    )
    assert not any("主人在幹嘛" in p for p in axis_help_side_problems()), "未注毒那遍不该点名"
    # 锚点换代不可反悔：`佔一卦` 如今在册又可路由（第二层＋第三层都落过地），
    # 谁把它从册上摘掉＝腿②（认得不登记）当场点名。
    assert "佔一卦" in registered_surface_forms("占卜"), (
        "锚点旧毒 `佔一卦` 已从 `占卜.aliases` 消失＝册侧三轴同级账被摘"
    )


def test_axis_script_register_is_neither_stale_nor_growing() -> None:
    """例外册反查：每枚登记缺形须**仍然**缺（同族孪生两侧都不认）；被修好却不删 ⇒ 红。

    登记 ≠ 实物（台账 #68★：落地件必过三道闸）。将来谁把 `佔卜` 补进 divination 正则，
    这一腿当场红催清账——不留「台账收编了但问题已消失」的空头许可。
    """
    stale: list[str] = []
    for capability_id, word, twin in sorted(LEDGER_AXIS_SCRIPT_ROUTE_OPEN):
        pool = set(ROUTE_SIDE.get(capability_id, set())) | HELP_SIDE.get(capability_id, set())
        if word not in ROUTE_SIDE.get(capability_id, set()):
            stale.append(f"{capability_id}/{word}：路由侧已无这枚字面，登记对象已不在")
        elif twin in pool:
            stale.append(
                f"{capability_id}/{word}→{twin}：孪生形已被认，例外册该清账"
            )
    assert not stale, "；".join(stale)
    current = set(axis_verb_script_problems(with_held=frozenset()))
    registered = {f"{c}/{w}：路由认简体形却不认同族繁體 {t}＝只认单一形态" for c, w, t in
                  LEDGER_AXIS_SCRIPT_ROUTE_OPEN}
    assert current == registered, (
        f"例外册与现算缺形不等：新增={sorted(current - registered)[:6]} "
        f"已修={sorted(registered - current)[:6]}"
    )

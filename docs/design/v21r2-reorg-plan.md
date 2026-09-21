# v21r2 代码板块重组方案（domains/ 八大板块 + 扩展域）

> 席位：RO 席（只读盘点 + 规划，**未动任何代码**）。生成时间：2026-09-17。
> 数据口径：全部来自本机实跑 `find / wc -l / grep`，解释器与探针均按直跑纪律（`PYTHONDONTWRITEBYTECODE=1`）。
> 用户需求原文锚定：按主要功能板块归类，放入独立完整文件夹（`plugins/bot_unified_runtime/domains/`），板块下再分子板块/子功能文件夹。八大板块 = 消息回复 / 表情包 / 社交媒体链接平台解析 / 点歌 / 查询地点 / 查询天气 / 查询菜谱（今天吃什么）/ 金融元素；其余按实盘点扩展。

---

## 0. 结论摘要

| 项 | 结论 |
|---|---|
| 现状总量 | **329 个 .py 文件 / 147,194 行**，另有 7 张 HTML 卡片模板 + 1 个随包内置资产（`sources/data/qx.json`） |
| 目标结构 | `plugins/bot_unified_runtime/domains/` 下 **19 个域**（用户 8 域 + 11 扩展域），域内按子功能再分层 |
| 迁移规模 | 327 个 .py 移动（2 个留守原位：根 `__init__.py`、`config.py`）+ 7 张模板随 render 域移动 |
| 分波 | **16 波 + 尾声**；先无冲突小域（链接解析→点歌→天气→菜谱）验证机制，热区（chat_reply/transport/core）最后 |
| 兼容 | 全程旧路径 re-export 薄壳垫片；NoneBot 插件 id / 加载入口不动；垫片退役单列尾声波 |
| 最大风险 | ① 根 `__init__.py`（8105 行、61 处 matcher/调度注册）与 4+ 在飞批次共享，必须最后动、保守拆；② 垫片期 `monkeypatch.setattr("旧路径.函数")` 补丁打在壳模块上打不进真身——受影响测试必须与移动同波改写；③ 门禁网（`render_hashes.json` 19 项绝对路径、config-catalog、渲染契约、命令目录）不随波同步就全量假红 |

---

## 1. 现状盘点（实跑 2026-09-17）

### 1.1 目录级统计（.py 文件数 / 行数，`find + wc -l` 实测）

| 目录 | .py 文件数 | 说明 |
|---|---|---|
| 根目录（`plugins/bot_unified_runtime/*.py`） | 11 | `__init__.py` 8105 行（插件入口）、smoke 3831、config 1394、diagnostics 1171、console_chat 747、config_readiness 532、message_context 465、mail_bridge 461、mail_adapter 301、backend_unit 285、route_demo 231 |
| `capabilities/`（含 `auto_send/`） | 43 | 40 个能力模块 + `auto_send/` 2 + `__init__`；最大 echo 3932 / chat 3308 / runtime_admin 1880 / debug 1807 |
| `character/` | 30 | 人格与记忆域；最大 vector_knowledge 1867 / affinity 1320 / reflection 1005 / memory_service 1002 |
| `llm/` | 9 | model_router 2211 / usage_service 1632 / billing_service 1201 / ledger 837 / channel_health 748 等 |
| `output/`（含 `card_render/`） | 13 | 渲染族 + card_render 5 py；另 7 张 `.html` 模板（universal 1752 行最大） |
| `policy/` | 6 | rate_limit 1271 / gate 380 / reply_budget 205 / quiet_hours 195 / roles 66 |
| `runtime/` | 41 | 管线/路由/调度/监控杂域；error_report 1282 / pipeline 1131 / settings 1033 / base_router 792 / reactions 776 |
| `sender/` | 9 | queue 1853 / worker 1118 / onebot 1043 / nonebot 614 / file_gateway 460 |
| `security/` | 4 | injection 223 / memory_sanitize 171 / content_safety 108（R-18 批热区） |
| `supervisor/` | 7 | windows_sandbox 971 / job_objects 632 / appcontainer 525 / acl 396 / sandbox 292 / ipc 212 |
| `audit/` | 3 | logger 244 / file_logger 102 |
| `contracts/` | 11 | media 849 / runtime 366 / finance 343 / character 273 等（测试引用面最广） |
| `decision/` | 9 | outbound_contracts 858 / outbound_registry 652 / trace 461 / engine 396 / shadow 263 |
| `control_plane/`（含 `api/`） | 31 | 独立控制面服务（在飞批次热点：workspaces/features/actions 等） |
| `sources/`（本层） | 56 | 金融 7 / 订阅 10 / 媒体 6 / 搜索基建 7 / 占卜 5 / 表情 4 等 |
| `sources/parsers/` | 37 | 28 个 `platforms_*.py` + 基建 9（http_util/ssrf_guard/cookies/wbi/image_stitch/context/types/platform_login/__init__） |
| `sources/subscriptions/` | 6 | social_v2 1482 / bilibili_adapter 793 / xiaohongshu 306 / music_v2 242 |
| `sources/fetchers/` | 3 | playwright_backend 140 / xhs_sign 17 |
| **合计** | **329** | **147,194 行**（非 py：7 张模板 html + `sources/data/qx.json` 内置资产） |

### 1.2 tests/ 引用面（`grep -rl` 实测，384 个测试文件）

| 被引用子包 | 引用测试文件数 | 被引用子包 | 引用测试文件数 |
|---|---|---|---|
| contracts | 159 | character | 59 |
| capabilities | 137 | output | 46 |
| sources | 113 | llm | 43 |
| runtime | 86 | sender | 37 |
| config（模块级） | 30 | audit | 23 |
| control_plane | 19 | policy | 17 |
| security | 7 | decision | 4 |
| supervisor | 2 | smoke | 2 |
| 裸 `from plugins.bot_unified_runtime import …` | 28 | — | — |

结论：contracts/capabilities/sources/runtime 四个包垫片必须先行且长期保留；任何「直接改 import 不留垫片」的激进路线在 384 个测试文件面前不成立。

### 1.3 外部引用面

- `bot.py`：`nonebot.load_plugin` 装载后断言 `plugin.id = bot_unified_runtime`（短名），并 `from plugins.bot_unified_runtime.mail_adapter import ResilientMailAdapter`（454-463 行区）。→ 插件根包与 `mail_adapter` 符号面不可破坏。
- `scripts/` 16 个文件 import 插件内部符号：command_catalog（读 `capabilities/echo.py` 的 `_HELP_ENTRIES`）、e2e_acceptance、doc_sync、measure_latency_chains、import_model_prices、clean_food_gallery、render_card_samples、crash_trap、pre_restart_check、probe_intimate_route、probe_trigger_hijack、gen_trigger_pinyin、extract_trigger_words、fetch_mermaid_js、knowledge_bench、import_meme_packs。→ 全部靠垫片覆盖，脚本零改动。
- 门禁脚本：`scripts/runtime_layout_smoke.py` 只查运行时数据边界（ChatBot_Runtime/data 不在源码树），**不锁定源码树形状** → 域内移动不触发；但 `tests/test_no_source_tree_data_writes.py` 的 `qx.json` 例外规则、`tests/verify_hashes.py` 的 19 项**绝对相对路径清单**、`tests/test_doc_sync_gates.py` 的 config-catalog 锚定、渲染契约测试的模板路径，都会随移动而红（见 §6）。

### 1.4 歧义文件归域判定（逐文件实读 docstring）

| 文件 | 判定 | 依据 |
|---|---|---|
| `character/draw_store.py`、`sources/draw_store.py` | divination | 「V2.1 S12 抽签持久层/公平性服务（占卜/每日运势/塔罗）」 |
| `sources/gscore_bridge.py` | ops/integrations | 「GsCore / gsuid-core 适配桥」外部服务桥 |
| `sources/runtime_event_log.py` | ops/monitor | 运行时事件日志 |
| `runtime/model_schedule.py` | chat_reply/llm_engine | 「分时段自动切换模型预设」 |
| `runtime/pricing.py` | chat_reply/llm_engine | LLM 计价（随引擎走） |
| `backend_unit.py` | chat_reply/pipeline | 「core reply pipeline 一次性执行单元」 |
| `route_demo.py`、`smoke.py`、`console_chat.py`、`diagnostics.py` | ops/smoke | 烟测/诊断/控制台试聊入口 |
| `message_context.py` | chat_reply/ingest | 「Platform-neutral message segment normalization」 |
| `mail_bridge.py` | transport/mail | 邮件桥（无 docstring，按命名+引用判定） |
| `character/media_registry.py` | media/registry | 「媒体档案库：chat_message_id 与视频/CC 字幕关联存档」 |
| `sources/video_understanding.py`、`vision_describe.py`、`transcribe.py` | media/ingest | 视频理解/识图/转写 |
| `runtime/natural_language.py` | chat_reply/runtime | 「自然语言命令识别（确定性层）」 |
| `runtime/question_intent.py` | chat_reply/runtime | 「可解释的联网决策」 |
| `sources/registry.py` | link_parse | 推断为解析注册表（无 docstring；**迁移时实读确认**，低置信标记） |
| `capabilities/randpic.py` | meme/randpic | 随机图能力 |
| `character/shared_group.py` | chat_reply/character | 群上下文短时记忆摘要 |
| `sources/telegram_media.py` | media/ingest | TG file_id→媒体字节（摄取侧） |

---

## 2. 目标结构

### 2.1 域定义（用户 8 域 + 扩展 11 域）

| # | 域文件夹 | 板块 | 覆盖功能 | 现载体（摘要） |
|---|---|---|---|---|
| 1 | `domains/chat_reply/` | 消息回复 | 人格对话、好感度、记忆/反思、称谓、门禁限流、安全审查、管线/路由、自然语言意图、LLM 引擎（模型路由/渠道健康/计费账单）、帮助命令面 | capabilities/{chat,echo,affinity,memory,poke,group_info,user_copy}、character/ 大部、llm/ 全部、policy/、security/、runtime 核心 18 件 + model_schedule + pricing、message_context、backend_unit |
| 2 | `domains/meme/` | 表情包 | 表情能力、表情收库、贴纸回应、随机图、表情搜索 | capabilities/{meme,meme_library,randpic}、sources/{meme_search,meme_library,meme_library_listener,reaction_store}、runtime/reactions |
| 3 | `domains/link_parse/` | 社交媒体链接解析 | 37+ 平台解析、SSRF 护栏、cookie、URL 清洗、解析历史、内容解析入口、fetchers | sources/parsers/ 全部 37、sources/fetchers/ 全部 3、capabilities/content_parser、sources/{url_cleaner,parse_history,registry} |
| 4 | `domains/music/` | 点歌平台 | 点歌候选、真实榜单、点歌请求存储、归一化 | capabilities/music、sources/{music_charts,music_request_store,music_normalization} |
| 5 | `domains/location/` | 查询地点 | 百科/地理类查询（现有=维基+萌娘+KB）；**POI/地图/导航为空白**，预留 `poi/` 子文件夹等外部数据源 | capabilities/{wiki,moegirl}、character/kb_wiki、sources/{mediawiki,moegirl} |
| 6 | `domains/weather/` | 查询天气 | 天气+预警、NMC 主通道、Open-Meteo 兜底、区县码表 | capabilities/weather、sources/{nmc_weather,open_meteo}、`sources/data/qx.json` 随迁 |
| 7 | `domains/food/` | 查询菜谱（今天吃什么） | 菜谱推荐、吃什么、图库防污染 | capabilities/eat、sources/food_data |
| 8 | `domains/finance/` | 金融元素 | 股指/个股/汇率/商品/债券/北向/交叉核验/金融图表 | capabilities/{market,stocks,fx}、sources/{stock_data,market_data,fx_data,commodities_data,bond_data,market_crosscheck,finance_chart} |
| 9 | `domains/divination/` | 占卜命理（扩展） | 八字/塔罗/易经/抽签/多历法 | capabilities/divination、character/draw_store、sources/{ganzhi,tarot,iching,multi_calendar,draw_store}、runtime/{divination_service,fortune,tarot_draw} |
| 10 | `domains/schedule/` | 日程与提醒（扩展） | 提醒督促、定时调度族、NTP 授时、自动发送解析 | capabilities/reminder、capabilities/auto_send/、character/reminders、runtime/{schedule_service,schedule_dag,schedule_store,schedule_rrule,timesync} |
| 11 | `domains/notes/` | 笔记备忘（扩展） | Markdown 笔记 CRUD、自然勾选 | capabilities/notes、character/notes_store |
| 12 | `domains/subscribe/` | 订阅与资讯（扩展） | 订阅 V1/V2、平台适配器、快报、喜加一、历史上的今天 | capabilities/{subscribe,subscribe_v2,news,epic,today_history}、sources/subscriptions/ 全部、sources/订阅存储 6 件 + {news_feeds,epicfree,steamfree,today_history} |
| 13 | `domains/media/` | 媒体处理（扩展） | 媒体归档、识图、视频理解/转写、搜图、TTS、TG 媒体摄取 | capabilities/{media_archive,tts,image_search}、character/media_registry、sources/{media_archive,vision_describe,video_understanding,transcribe,telegram_media,sauce_search}、runtime/video_pipeline |
| 14 | `domains/files/` | 文件进出站（扩展） | 下载器、文件交换、群文件 | capabilities/{download,file_exchange,group_files}、sources/{downloader,file_reader} |
| 15 | `domains/transport/` | 出站通道（扩展） | 发送队列、OneBot/NoneBot 通道、回执、邮件适配 | sender/ 全部 9、mail_adapter、mail_bridge |
| 16 | `domains/assistant/` | 日常助理+校园转发（扩展） | 收件箱/早晚报/到点吃什么、校园群监听转发 | capabilities/{daily_assist,campus}、character/daily_assist、sources/campus_store |
| 17 | `domains/ops/` | 运维管理（扩展） | debug/管理面板/日志/特性开关、告警监控、审计、烟测工具、外部桥 | capabilities/{debug,runtime_admin,runtime_logs,feature_control}、runtime 监控 10 件、audit/、根 {diagnostics,smoke,console_chat,route_demo}、sources/{gscore_bridge,runtime_event_log} |
| 18 | `domains/core/` | 系统内核（扩展） | 配置体检、凭据、契约、决策引擎、控制面、进程沙箱、联网搜索基建 | 根 config_readiness、capabilities/platform_credentials、contracts/、decision/、control_plane/、supervisor/、sources/{search_service,search_api,web_search,mcp_web_search_server,search_smoke,credentials,credential_health} |
| 19 | `domains/render/` | 渲染出站（扩展） | 出站文本管线、云母卡片、主题 token、模板 | output/ 全部 13 py + 7 html |
| — | （留守原位） | 入口与配置 | 插件入口、529 字段配置 | 根 `__init__.py`（尾声波才拆内部）、根 `config.py`（**裁定留守**，见 §4.3） |

> 说明：`config.py` 留守但逻辑归属 core 域；core/transforms 阶段只留可选垫片。`location` 域现有能力最薄，是用户点名 8 域中唯一的"结构性空白"，文档如实登记，不虚构模块。

### 2.2 目标树（骨架 + 子板块分层）

```
plugins/bot_unified_runtime/
├── __init__.py                      ← 留守：NoneBot 插件入口（matcher 注册段永在此，见 §4.4）
├── config.py                        ← 留守：529 字段，30 测试文件 + config-catalog 门禁锚定
├── capabilities/__init__.py         ← 薄壳垫片（re-export），直到尾声波退役
├── sources/__init__.py              ← 薄壳垫片
└── domains/
    ├── chat_reply/
    │   ├── capabilities/            chat, echo*, affinity, memory, poke, group_info, user_copy
    │   ├── character/               providers, history, memory*, reflection, memory_extract,
    │   │                            addressing, session_identity, mood, quirks, relationship,
    │   │                            emotion, glossary, trend, temporal, persona_set,
    │   │                            source_summary, documents, shared_group, shared_export,
    │   │                            vector_knowledge, affinity            （23 件）
    │   ├── llm_engine/              model_router*, providers, channel_health*, ledger,
    │   │                            billing_{service,entities,pricing}, usage_service,
    │   │                            model_schedule, pricing, __init__
    │   ├── policy/                  gate*, rate_limit, reply_budget, quiet_hours, roles
    │   ├── security/                injection, memory_sanitize, content_safety*
    │   ├── runtime/                 pipeline*, base_router, settings, natural_language,
    │   │                            question_intent, mentions, parrot, aliases, ingress,
    │   │                            cache_policy, group_cache, time_window, deadline,
    │   │                            event_idempotency, prompt_audit, prompt_preview,
    │   │                            capability_registry, content_route*
    │   ├── ingest/                  message_context
    │   └── pipeline/                backend_unit
    ├── meme/
    │   ├── capabilities/            meme, meme_library, randpic
    │   ├── sources/                 meme_search, meme_library, meme_library_listener, reaction_store
    │   └── reactions/               runtime/reactions → reactions/engine
    ├── link_parse/
    │   ├── parsers/                 28 个 platforms_*.py（保原名）+ http_util, ssrf_guard,
    │   │                            cookies, wbi, image_stitch, context, types,
    │   │                            platform_login, __init__
    │   ├── fetchers/                playwright_backend, xhs_sign
    │   ├── capabilities/            content_parser
    │   └── support/                 url_cleaner, parse_history, registry(待实读确认)
    ├── music/
    │   ├── capabilities/            music
    │   └── data/                    music_charts, music_request_store, music_normalization
    ├── location/
    │   ├── capabilities/            wiki, moegirl
    │   ├── knowledge/               kb_wiki
    │   ├── data/                    mediawiki, moegirl
    │   └── poi/                     （预留空白：POI/地图/导航，等外部数据源立项）
    ├── weather/
    │   ├── capabilities/            weather
    │   ├── data/                    nmc_weather, open_meteo
    │   └── assets/                  qx.json（随包内置资产，test_no_source_tree_data_writes 例外同步改）
    ├── food/
    │   ├── capabilities/            eat
    │   └── data/                    food_data
    ├── finance/
    │   ├── capabilities/            market, stocks, fx
    │   └── data/                    stock_data, market_data, fx_data, commodities_data,
    │                                bond_data, market_crosscheck, finance_chart
    ├── divination/
    │   ├── capabilities/            divination
    │   ├── service/                 divination_service, fortune, tarot_draw
    │   ├── store/                   character/draw_store
    │   └── data/                    ganzhi, tarot, iching, multi_calendar, draw_store
    ├── schedule/
    │   ├── capabilities/            reminder
    │   ├── auto_send/               parser（+ __init__）
    │   ├── store/                   character/reminders
    │   ├── service/                 schedule_service, schedule_dag, schedule_store, schedule_rrule
    │   └── timesync/                timesync*
    ├── notes/
    │   ├── capabilities/            notes
    │   └── store/                   notes_store
    ├── subscribe/
    │   ├── capabilities/            subscribe, subscribe_v2, news, epic, today_history
    │   ├── adapters/                sources/subscriptions/（social_v2, bilibili_adapter,
    │   │                            xiaohongshu_adapter, music_v2, target_notice, __init__）
    │   ├── store/                   subscription_{store,store_v2,scheduler,watcher,migration,runtime_v2}
    │   └── feeds/                   news_feeds, epicfree, steamfree, today_history
    ├── media/
    │   ├── capabilities/            media_archive, tts, image_search
    │   ├── archive/                 sources/media_archive
    │   ├── ingest/                  vision_describe, video_understanding, transcribe,
    │   │                            telegram_media
    │   ├── search/                  sauce_search
    │   ├── registry/                character/media_registry
    │   └── video/                   runtime/video_pipeline
    ├── files/
    │   ├── capabilities/            download, file_exchange, group_files
    │   └── sources/                 downloader, file_reader
    ├── transport/
    │   ├── sender/                  queue*, worker*, onebot*, nonebot, file_gateway, receipts,
    │   │                            gateway, timeout, __init__
    │   └── mail/                    mail_adapter*, mail_bridge
    ├── assistant/
    │   ├── daily/                   daily_assist（capability+store 两件）
    │   └── campus/                  campus, campus_store
    ├── ops/
    │   ├── admin/                   debug, runtime_admin, runtime_logs
    │   ├── features/                feature_control, feature_catalog, feature_gate
    │   ├── monitor/                 error_report, alerts, event_store, event_service,
    │   │                            usage_monitor, intent_telemetry, result_unknown,
    │   │                            disconnect_notice, runtime_event_log
    │   ├── audit/                   logger, file_logger
    │   ├── smoke/                   smoke, route_demo, console_chat
    │   └── integrations/            gscore_bridge
    ├── core/
    │   ├── config/                  config_readiness（config.py 本体留守根位）
    │   ├── credentials/             platform_credentials, credentials, credential_health
    │   ├── contracts/               全部 11 件（保内部结构，垫片长期保留）
    │   ├── decision/                全部 9 件
    │   ├── control_plane/           全部 31 件（含 api/，在飞批，最后动）
    │   ├── supervisor/              全部 7 件
    │   └── search/                  search_service, search_api, web_search,
    │                                mcp_web_search_server, search_smoke
    └── render/
        ├── plain_text.py            （redact_local_secrets 等出站文本纪律）
        ├── renderer.py / templates.py / roleplay.py / reviewer.py / bot_avatar.py
        ├── render_backends.py
        └── card_render/             bridge, theme_tokens*, usage_cards, models + templates/7 html
```

`*` 标记 = 在飞批次热区（详见 §4.1），其所在波需独占窗口。

### 2.3 完整映射表：现有文件 → 目标位置（329 .py 全列举，`*`=热区）

**根目录（11）**

| 现路径 | 数 | 目标 |
|---|---|---|
| `__init__.py` | 1 | **留守原位**（NoneBot 插件入口；内部拆分策略见 §4.4，拆出物落入各域 `wiring/`） |
| `config.py` | 1 | **留守原位**（裁定见 §4.3） |
| `diagnostics.py` `smoke.py` `console_chat.py` `route_demo.py` | 4 | `domains/ops/smoke/` |
| `config_readiness.py` | 1 | `domains/core/config/` |
| `message_context.py` | 1 | `domains/chat_reply/ingest/` |
| `backend_unit.py` | 1 | `domains/chat_reply/pipeline/` |
| `mail_bridge.py` `mail_adapter.py`* | 2 | `domains/transport/mail/` |

**capabilities/（43）**

| 现文件 | 数 | 目标 |
|---|---|---|
| `chat.py` `echo.py`* `affinity.py`* `memory.py` `poke.py` `group_info.py` `user_copy.py` | 7 | `domains/chat_reply/capabilities/` |
| `meme.py` `meme_library.py` `randpic.py` | 3 | `domains/meme/capabilities/` |
| `content_parser.py` | 1 | `domains/link_parse/capabilities/` |
| `music.py` | 1 | `domains/music/capabilities/` |
| `wiki.py` `moegirl.py` | 2 | `domains/location/capabilities/` |
| `weather.py` | 1 | `domains/weather/capabilities/` |
| `eat.py` | 1 | `domains/food/capabilities/` |
| `market.py` `stocks.py` `fx.py` | 3 | `domains/finance/capabilities/` |
| `divination.py` | 1 | `domains/divination/capabilities/` |
| `reminder.py`；`auto_send/parser.py` `auto_send/__init__.py` | 3 | `domains/schedule/capabilities/`；`domains/schedule/auto_send/` |
| `notes.py` | 1 | `domains/notes/capabilities/` |
| `subscribe.py` `subscribe_v2.py` `news.py` `epic.py` `today_history.py` | 5 | `domains/subscribe/capabilities/` |
| `media_archive.py` `tts.py` `image_search.py` | 3 | `domains/media/capabilities/` |
| `download.py` `file_exchange.py` `group_files.py` | 3 | `domains/files/capabilities/` |
| `daily_assist.py`*；`campus.py` | 2 | `domains/assistant/daily/`；`domains/assistant/campus/` |
| `debug.py` `runtime_admin.py` `runtime_logs.py`；`feature_control.py` | 4 | `domains/ops/admin/`；`domains/ops/features/` |
| `platform_credentials.py` | 1 | `domains/core/credentials/` |
| `__init__.py` | 1 | 原位改写为薄壳垫片 |

**character/（30）**

| 现文件 | 数 | 目标 |
|---|---|---|
| `providers.py` `history.py` `memory.py` `memory_service.py`* `memory_store_v21.py`* `reflection.py` `memory_extract.py` `addressing.py` `session_identity.py` `mood.py` `quirks.py` `relationship.py` `emotion.py` `glossary.py` `trend.py` `temporal.py` `persona_set.py` `source_summary.py` `documents.py` `shared_group.py` `shared_export.py` `vector_knowledge.py` `affinity.py`* | 23 | `domains/chat_reply/character/` |
| `reminders.py` | 1 | `domains/schedule/store/` |
| `notes_store.py` | 1 | `domains/notes/store/` |
| `daily_assist.py` | 1 | `domains/assistant/daily/` |
| `draw_store.py` | 1 | `domains/divination/store/` |
| `media_registry.py` | 1 | `domains/media/registry/` |
| `kb_wiki.py` | 1 | `domains/location/knowledge/` |
| `__init__.py` | 1 | 原位改写为薄壳垫片 |

**llm/（9）→ `domains/chat_reply/llm_engine/`**：`model_router.py`* `providers.py` `channel_health.py`* `ledger.py` `billing_service.py` `billing_entities.py` `billing_pricing.py` `usage_service.py` `__init__.py`（旧 `llm/` 留薄壳）

**policy/（6）→ `domains/chat_reply/policy/`**：`gate.py`* `rate_limit.py` `reply_budget.py` `quiet_hours.py` `roles.py` `__init__.py`

**security/（4）→ `domains/chat_reply/security/`**：`injection.py` `memory_sanitize.py` `content_safety.py`* `__init__.py`

**runtime/（41）**

| 现文件 | 数 | 目标 |
|---|---|---|
| `pipeline.py`* `base_router.py` `settings.py` `natural_language.py` `question_intent.py` `mentions.py` `parrot.py` `aliases.py` `ingress.py` `cache_policy.py` `group_cache.py` `time_window.py` `deadline.py` `event_idempotency.py` `prompt_audit.py` `prompt_preview.py` `capability_registry.py` `content_route.py`* | 18 | `domains/chat_reply/runtime/` |
| `model_schedule.py` `pricing.py` | 2 | `domains/chat_reply/llm_engine/` |
| `reactions.py` | 1 | `domains/meme/reactions/` |
| `schedule_service.py` `schedule_dag.py` `schedule_store.py` `schedule_rrule.py` | 4 | `domains/schedule/service/` |
| `timesync.py`* | 1 | `domains/schedule/timesync/` |
| `divination_service.py` `fortune.py` `tarot_draw.py` | 3 | `domains/divination/service/` |
| `error_report.py` `alerts.py` `event_store.py` `event_service.py` `usage_monitor.py` `intent_telemetry.py` `result_unknown.py` `disconnect_notice.py` | 8 | `domains/ops/monitor/` |
| `feature_catalog.py` `feature_gate.py` | 2 | `domains/ops/features/` |
| `video_pipeline.py` | 1 | `domains/media/video/` |
| `__init__.py` | 1 | 原位改写为薄壳垫片 |

**sender/（9）→ `domains/transport/sender/`**：`queue.py`* `worker.py`* `onebot.py`* `nonebot.py` `file_gateway.py` `receipts.py` `gateway.py` `timeout.py` `__init__.py`

**output/（13 py + 7 html）→ `domains/render/`**：`render_backends.py` `renderer.py` `plain_text.py`* `templates.py` `roleplay.py`* `reviewer.py` `bot_avatar.py` `__init__.py`；`card_render/{bridge.py theme_tokens.py* usage_cards.py models.py __init__.py}`；`card_render/templates/*.html` ×7（保内部结构）

**supervisor/（7）→ `domains/core/supervisor/`**（全部，保结构）；**audit/（3）→ `domains/ops/audit/`**；**contracts/（11）→ `domains/core/contracts/`**（垫片长期保留）；**decision/（9）→ `domains/core/decision/`**；**control_plane/（31，含 api/）→ `domains/core/control_plane/`***（在飞批，最后动）

**sources/（56）**

| 现文件 | 数 | 目标 |
|---|---|---|
| `stock_data.py` `market_data.py` `fx_data.py` `commodities_data.py` `bond_data.py` `market_crosscheck.py` `finance_chart.py` | 7 | `domains/finance/data/` |
| `music_charts.py` `music_request_store.py` `music_normalization.py` | 3 | `domains/music/data/` |
| `nmc_weather.py` `open_meteo.py`；`data/qx.json`（资产） | 2+1 | `domains/weather/data/`；`domains/weather/assets/` |
| `food_data.py` | 1 | `domains/food/data/` |
| `ganzhi.py` `tarot.py` `iching.py` `multi_calendar.py` `draw_store.py` | 5 | `domains/divination/data/` |
| `subscription_store.py` `subscription_store_v2.py` `subscription_scheduler.py` `subscription_watcher.py` `subscription_migration.py` `subscription_runtime_v2.py` | 6 | `domains/subscribe/store/` |
| `news_feeds.py` `epicfree.py` `steamfree.py` `today_history.py` | 4 | `domains/subscribe/feeds/` |
| `meme_search.py` `meme_library.py` `meme_library_listener.py` `reaction_store.py` | 4 | `domains/meme/sources/` |
| `media_archive.py`；`vision_describe.py` `video_understanding.py` `transcribe.py` `telegram_media.py`；`sauce_search.py` | 6 | `domains/media/archive/`；`domains/media/ingest/`；`domains/media/search/` |
| `downloader.py` `file_reader.py` | 2 | `domains/files/sources/` |
| `url_cleaner.py` `parse_history.py` `registry.py`(待实读确认) | 3 | `domains/link_parse/support/` |
| `mediawiki.py` `moegirl.py` | 2 | `domains/location/data/` |
| `runtime_event_log.py`；`gscore_bridge.py` | 2 | `domains/ops/monitor/`；`domains/ops/integrations/` |
| `credentials.py` `credential_health.py` | 2 | `domains/core/credentials/` |
| `search_service.py` `search_api.py` `web_search.py` `mcp_web_search_server.py` `search_smoke.py` | 5 | `domains/core/search/` |
| `campus_store.py` | 1 | `domains/assistant/campus/` |
| `__init__.py` | 1 | 原位改写为薄壳垫片 |

**sources/parsers/（37）→ `domains/link_parse/parsers/`**：28 个 `platforms_*.py`（bilibili, generic, music*, weibo, steam, epic, lofter, acfun, huajia, kurobbs, kuaishou, xiaoheihe, facebook, pixiv, moegirl, miyoushe, bilibili_goods, github, community, telegram, zhihu, media_share, mihuashi, allcpp, taptap, skland, discourse, douban）+ 基建 9（`http_util` `ssrf_guard` `cookies` `wbi` `image_stitch` `context` `types` `platform_login` `__init__`）

**sources/subscriptions/（6）→ `domains/subscribe/adapters/`**：`social_v2.py` `bilibili_adapter.py` `xiaohongshu_adapter.py` `music_v2.py` `target_notice.py` `__init__.py`

**sources/fetchers/（3）→ `domains/link_parse/fetchers/`**：`playwright_backend.py` `xhs_sign.py` `__init__.py`

行数合计核对：各表「数」列合计 = 329（11+43+30+9+6+4+41+9+13+7+3+11+9+31+56+37+6+3），与 §1.1 目录级实测一致。

---

## 3. 兼容策略

### 3.1 旧 import 路径兼容垫片（原位 re-export 薄壳）

- 形态：旧路径文件替换为薄壳，例如 `plugins/bot_unified_runtime/sources/nmc_weather.py` →

  ```python
  """Compat shim: moved to domains/weather/data/nmc_weather.py (v21r2 reorg)."""
  from plugins.bot_unified_runtime.domains.weather.data.nmc_weather import *  # noqa: F401,F403
  from plugins.bot_unified_runtime.domains.weather.data.nmc_weather import __all__  # noqa: F401
  ```

- 纪律：只对**纯模块**做 `import *` 薄壳；带副作用的包 `__init__.py`（如 `contracts/__init__.py`、`control_plane/__init__.py`）薄壳必须显式列举符号或直接整体保留原位（contracts 159 个测试文件引用，建议 contracts 垫片长期保留、退役无限期推迟）。
- **相对导入必须换绝对导入**（随移动同波改写）：被移动文件内部的 `from ..config import X` → `from plugins.bot_unified_runtime.config import X`。原因：包层级变了，相对导入在垫片期语义脆弱；绝对导入让真身与薄壳指向同一对象，`isinstance` 不分裂。
- **monkeypatch 陷阱（本方案最大技术风险）**：测试里 `monkeypatch.setattr("plugins.bot_unified_runtime.sources.nmc_weather.fetch_x", ...)` 打在薄壳模块上，真身内部调用自己的符号 → 补丁失效、测试假绿或假红。对策：每波迁移前 `rg -l "monkeypatch.setattr|mock.patch" tests` 过滤出命中该模块旧路径的测试文件清单，**与移动同一波内把这些测试改指新路径**；改不完不动该模块。
- 垫片退役：尾声波统计旧路径 import 残留（`rg "bot_unified_runtime\.(sources|capabilities|character|…)\." --count-matches`），全零（或仅剩刻意保留的 contracts/llm 等长期垫片）才允许删；默认**全部保留**，不设强制截止。

### 3.2 NoneBot 插件加载不受影响的论证

1. `bot.py` 经 `nonebot.load_plugin` 装载，plugin.id = 包目录短名 `bot_unified_runtime`；本方案**不移动根包目录、不移动根 `__init__.py`**（尾声波也只做其内部拆分，路径不变）→ plugin.id 与加载语义零变化。
2. NoneBot 的 matcher/调度器注册发生在根 `__init__.py` import 期；拆分只把**纯函数簇**搬走并由根 import 回来，import 期副作用（`_register_nonebot_handlers`、driver 钩子、control_plane lifecycle）留在根 → 注册时序不变。
3. `bot.py` 直接 import 的 `mail_adapter.ResilientMailAdapter`：mail_adapter 移走后旧路径垫片覆盖 → bot.py 零改动（尾声波可改为直连新路径，非必须）。
4. 适配器（OneBot/Telegram/Mail/Console）只认 NoneBot 事件与发送 API，不 import 插件内部路径 → 不受影响。

### 3.3 tests/ 引用面与兼容结论

- 引用计数见 §1.2（contracts 159 / capabilities 137 / sources 113 / runtime 86 …）。垫片方案下 **tests 零改动全绿**是每波的验收底线；monkeypatch 命中文件按 §3.1 同波改写（这是唯一允许的测试改动）。
- `tests/verify_hashes.py` 的 `TRACKED_FILES`（render 域 19 项绝对相对路径）在 render 波**必须同波改路径 + `--write` 重录**，否则常驻门 `test_cross_validation_gates.py` 全量红。
- `scripts/command_catalog.py`（echo `_HELP_ENTRIES`）等 16 个脚本靠垫片零改动；命令目录生成物如因移动漂移，波内重跑 `command_catalog.py --write`。

---

## 4. 风险与冲突清单

### 4.1 在飞批次冲突矩阵（本方案波次 ↔ 近期批次改动面）

| 热区文件 | 在飞批次（据工作区台账） | 命中波次 | 处置 |
|---|---|---|---|
| 根 `__init__.py`（8105 行） | 所有批次共享（每日助理/校园/控制面/R-18/五池…） | 尾声（W16 之后） | 最后动；拆分见 §4.4 |
| `llm/model_router.py`、`channel_health.py` | 上下文钳制批、渠道重排/瘦身批、链路收敛批 | W15b | 独占窗口，先等在飞批收口 |
| `runtime/pipeline.py`、`content_route.py`、`capability_registry.py` | R-18 内容路由批、pipeline 异步化批 | W15d | 独占窗口 |
| `policy/gate.py`、`character/affinity.py` | R 系列角色批、红线门扩面批 | W15c | 与红线批协调 |
| `character/memory_service.py`、`memory_store_v21.py` | 控制面在飞批（test_memory_service_v21） | W15a | 协调窗口 |
| `sender/*`（queue/worker/onebot）、`mail_adapter.py` | 发送队列/UNKNOWN 确认批、mail 韧性批 | W14 | 独占窗口 |
| `runtime/timesync.py` | 授时收编批（789700c 后续） | W10 | 协调窗口 |
| `capabilities/daily_assist.py`、`character/daily_assist.py` | 日常助理批（#32/#36 相邻） | W12 | 协调窗口 |
| `control_plane/**` | 控制面核心切片批（workspaces/features/actions 等） | W16 | 等控制面批收口后动 |
| `capabilities/echo.py`（3932 行帮助注册表） | 批批共享（每批都加 topic） | W15e（末位） | 独占窗口；`_HELP_ENTRIES` 整体搬，`echo` 薄壳永久保留 |
| `config.py` | doc_sync_gates/config-catalog 锚定 | **不迁移** | 见 §4.3 |

### 4.2 通用风险登记

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R1 | monkeypatch 垫片失效（§3.1） | **Critical** | 波前 grep 清单、波内同改，未清零不挪 |
| R2 | 门禁网假红：render_hashes 19 项路径、渲染契约测试模板路径、doc_sync_gates、command_catalog 生成物、`test_no_source_tree_data_writes` 的 qx.json 例外 | **High** | 每波门禁清单（§6）波内同步；render 波必须 `--write` 重录 |
| R3 | 相对导入层级变化 | High | 移动即改绝对导入（§3.1），ruff/mypy 全量兜底 |
| R4 | 多代理并发共享工作树，迁移 PR 与功能批互相踩 | High | 每波一个无冲突域 + 独占窗口 + 波前 `git status` 取证；迁移波期间冻结该域功能改动 |
| R5 | NoneBot 插件入口被破坏 | Critical（低概率） | 根包/根 `__init__.py` 不动；每波后跑 bot 侧冒烟（import 插件 + matcher 计数断言） |
| R6 | `sources/data/qx.json` 随包资产被清理波误删（历史三次事故） | Medium | 随迁 weather/assets 并同波更新数据写守卫例外规则；迁移后立刻验证文件存在+sha |
| R7 | 模板/契约测试对 `output/card_render/templates` 的路径硬编码 | Medium | render 波一次性全改（契约测试 + verify_hashes + bridge 模板加载路径） |
| R8 | Windows `git mv` 与大小写、长路径 | Low | 全程 `git mv`（保历史），禁手拷 |
| R9 | 拆分让 `smoke.py`/`diagnostics.py`/脚本断掉的隐式依赖 | Low | 垫片覆盖 + 波后跑 `dev.ps1 -Task runtime-layout` 与 smoke |

### 4.3 `config.py` 留守裁定（两案并存，推荐 A）

- **案 A（推荐）**：`config.py` 留守根位。理由：529 字段、30 个测试文件引用、`doc_sync_gates` 的 config-catalog 门禁锚定字段清单、`runtime_paths` 的 path_fields 重映射全部以现路径为前提；收益（目录美观）<< 风险（门禁全红 + 在飞批冲突）。
- **案 B（可选尾声）**：真要归位 → 移 `domains/core/config/config.py` + 根位薄壳 + catalog/门禁三处路径同步。仅在全部波收口、全量常绿后作为独立 PR。

### 4.4 根 `__init__.py`（8105 行）拆分策略（单列）

现状实测：92 个 def/class，61 处 matcher/scheduler 注册调用，`get_driver` 出现 9 处；关键锚点：`_register_nonebot_handlers`（≈L3273）、`register_control_plane_lifecycle`（≈L3553）、10 个 `_register_*_scheduler` 工厂、摄取辅助（`_forward_message_text` L950、`_transcode_record_segments` L1012）、投递辅助（`_deliver_onebot_send_request` L2160、`_deliver_transport_send_request` L2297）、头像解析（L2033/L2062）。

三阶段保守拆分（每阶段每簇一步一验证，任何一步异常即停）：

1. **纯函数簇先行**（无 matcher、无 import 期副作用）：摄取辅助 → `domains/chat_reply/ingest/wiring.py`；投递辅助 → `domains/transport/sender/wiring.py`；头像解析 → `domains/render/wiring.py`；各调度器工厂 `_register_xxx_scheduler` → 所属域 `wiring.py`（digest→assistant、reminder→schedule、reflection→chat_reply、credential→core、today_history→subscribe、daily_assist→assistant、send_queue→transport）。根 `__init__.py` 只留 `from … import _register_xxx_scheduler`。
2. **装配函数簇次之**：config 装配、capability 工厂、pipeline 装配段 → `domains/chat_reply/runtime/wiring.py`（拆前必须先确认与在飞 pipeline 批无冲突）。
3. **matcher 注册段最后、默认永驻根**：`@on_message/@on_command/on_fullmatch/on_regex` 族、`_register_nonebot_handlers`、driver 钩子、control_plane lifecycle 注册**留在根 `__init__.py`**。NoneBot 语义依赖「插件包 import 期完成注册」，根文件就是注册表的唯一稳定锚点；除非未来 NoneBot 提供显式注册 API，否则不拆。
- 拆分纪律：每抽一簇 → 直跑「插件导入冒烟 + matcher 计数 + 受影响域测试」三件套再抽下一簇；拆分全程与任何功能批互斥（独占窗口）。

---

## 5. 分波迁移计划（16 波 + 尾声）

通用波模板（每波五步）：
1. **波前取证**：`git status` 确认该域无在飞未收口改动；`rg` 生成该域 monkeypatch 命中测试清单；`rg` 生成内部相对导入清单。
2. **移动**：全部用 `git mv` 到 §2.3 目标位；被移动文件相对导入 → 绝对导入。
3. **垫片**：旧路径落 re-export 薄壳；monkeypatch 命中测试同波改指新路径（未清零不收波）。
4. **门禁同步**：波内涉及的路径锚定门禁（verify_hashes/config-catalog/契约测试/qx.json 例外）同波更新。
5. **回归 + 回滚点**：跑 §6 常绿清单 + 全量 `dev.ps1 -Task test`；单独 commit（回滚 = revert 该波 commit + 删 `domains/<域>/`，垫片与测试改动随 revert 一并消失，无残留中间态）。

| 波 | 域 | 移动量 | 冲突面 | 要点 |
|---|---|---|---|---|
| W1a | link_parse/parsers 平台适配器 | 28 | 极小（纯平台文件） | **机制验证波**：首个域，全流程走通再继续；`platforms_music.py` 与 music 波联动垫片 |
| W1b | link_parse 其余 | 16 | 小 | parsers 基建 9 + `content_parser` + `url_cleaner/parse_history/registry` + fetchers 3；`registry.py` 迁移时实读确认归域 |
| W2 | music | 4 | 小 | `platforms_music` 已在 W1；本波 capability+data 3 件；`song_candidates.html` 留 render 域（W13 联动） |
| W3 | weather | 3+资产 | 小 | `qx.json` 随迁 `weather/assets/`，同波改 `test_no_source_tree_data_writes` 例外，迁后校验文件+内容 |
| W4 | food | 2 | 极小 | 与 `scripts/clean_food_gallery.py` 引用联动（垫片覆盖） |
| W5 | divination | 10 | 小 | 含 `draw_store` 双件与 runtime service 3 件；卡片 prune 逻辑随行 |
| W6 | meme | 8 | 小 | `reaction_store`/`reactions` 同波（R-18 批已收口为前提） |
| W7 | finance | 10 | 小 | `contracts/finance.py` 留 core（W16），capability 经垫片引用 |
| W8 | subscribe | 21 | 小 | 订阅存储离环批已收口为前提；适配器整体搬 |
| W9 | notes + files | 7 | 小 | 笔记 mark_done 修复已入库为前提 |
| W10 | schedule | 9 | 中（timesync 在飞） | 授时批协调窗口；NTP 门测试随行 |
| W11 | media | 11 | 小 | `contracts/media.py` 留 core（W16） |
| W12 | assistant | 4 | 中（daily_assist 在飞） | 与日常助理批协调 |
| W13 | render | 13 py + 7 html | 中（渲染契约门） | `verify_hashes.py` `TRACKED_FILES` 同波改路径 + `--write` 重录；渲染契约测试模板路径全改；`bridge.py` 模板加载路径改 |
| W14 | transport | 11 | **高**（sender/queue/worker/onebot、mail 在飞） | 独占窗口；`bot.py` 的 mail_adapter import 靠垫片覆盖 |
| W15 | chat_reply 主体 | 71 | **最高** | 拆 5 子波：15a character 23 → 15b llm_engine 11 → 15c policy+security 10 → 15d runtime 核心 18 + ingest/pipeline 2 → 15e capabilities 7（含 echo 3932 行、chat 3308 行）；每子波独占窗口、等对应在飞批收口 |
| W16 | ops + core | 90 | **高**（control_plane 在飞） | 等控制面批收口；contracts 垫片标记为长期保留；config.py 案 B 仅在此后评估 |
| 尾声 | 入口与退役 | — | 最高（全批次共享） | 根 `__init__.py` 三阶段拆分（§4.4）；垫片退役统计；AGENTS.md 目录地图 + HANDBOOK + docs/README 全量同步 |

顺序原则：无冲突小域（W1-W9）先行验证垫片/门禁机制 → 中冲突（W10-W13）→ 热区（W14-W16）最后；任何一波全量红且 30 分钟内无法定位 → revert 该波、落盘断点、换下一无冲突域续跑（不空等）。

---

## 6. 机器门禁（迁移期间常绿验证清单，直跑纪律版）

```bash
# 固定解释器 + 源码树零缓存纪律
PY="C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe"
export PYTHONDONTWRITEBYTECODE=1
BT="--basetemp=$TEMP/pytest-v21r2 -p no:cacheprovider"

# ① 波内受影响域测试（关键词随波换：parse/music/weather|nmc|open_meteo/eat|food/
#    divination|tarot|ganzhi|meme|reaction/stock|market|fx/subscribe|digest/
#    notes|reminder|schedule|timesync/media|vision/tts/daily_assist|campus/
#    render|card|roleplay/sender|queue|mail/chat|affinity|policy|security|llm|model/control_plane）
"$PY" -m pytest tests -k "<wave-keywords>" $BT -q

# ② 出站文本/模板相关波必跑渲染契约（W13 及一切动 plain_text/roleplay 的波）
"$PY" -m pytest tests/test_rendering_contract.py tests/test_mica_builders_contract.py $BT -q

# ③ 哈希门：非 render 波 --check；W13 先改 TRACKED_FILES 路径再 --write 重录
"$PY" tests/verify_hashes.py --check

# ④ 事实册与命令目录门（凡动 config 引用/帮助注册表的波）
"$PY" -m pytest tests/test_doc_sync_gates.py $BT -q
"$PY" scripts/command_catalog.py --write   # 生成物漂移即波内收口

# ⑤ 树卫生 + 运行时边界（每波必跑）
"$PY" scripts/runtime_layout_smoke.py
"$PY" -m pytest tests/test_no_source_tree_data_writes.py $BT -q

# ⑥ 静态门（本波改动面零新增错误）
"$PY" -m ruff check plugins tests
"$PY" -m mypy plugins/bot_unified_runtime

# ⑦ 插件入口冒烟（每波必跑；垫片断链在此现形）
"$PY" -c "import plugins.bot_unified_runtime as m; import plugins.bot_unified_runtime.mail_adapter as ma; assert hasattr(ma,'ResilientMailAdapter'); print('plugin import OK')"

# ⑧ 波收口：全量权威门（唯一「完成」判据）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
# 提交纪律：逐文件显式 git add（禁 add -A/-A .），提交后 git show --stat HEAD 核对
```

### 6.1 建议新增（后续席位执行，本 RO 席不写码）

- `tests/test_domain_layout.py`：断言 §2.3 映射表 ↔ 文件系统一致（每域目录存在、旧路径薄壳存在且指向新位、`qx.json` 在 `domains/weather/assets/`）——把本方案变成常驻机器门。
- 垫片覆盖率门：脚本统计「已迁移模块数 == 薄壳数」，防迁移漏垫。

---

## 7. 交接注记

- 本文档为 RO 席只读产物，未动任何代码、未 commit、未派代理。
- 下手顺序建议：W1a 起步前先在本文件勾选各波「波前取证」结果；每波完成后在 §5 表格追加「实跑证据列」（哈希/命令+输出）。
- 与在飞批次的窗口协调是执行期第一优先事项：W14/W15/W16 开波前必须确认对应批次已收口（以 `docs/design/COMPACT-CHECKPOINT.md` 顶部为准）。

---

> **以下 §8/§9/§10 为 PA 席（合同对齐+未来预留，RO 席续作）2026-09-18 追加，纯文档零代码。**
> **编号声明**：任务指定追加「§7/§8/§9」，但本文件 §7 已被 RO 席用作「交接注记」且禁改一字 → 三新章节顺延为 **§8 合同对齐矩阵 / §9 未来功能预留 / §10 波次修订**，内容顺序与任务要求一致；RO 席 §0-§7 未动一字。
> **引文坐标约定**：`矩阵 Lnn` = `docs/design/backend-v2-acceptance-matrix.md` 需求主表该行（主表 65 行=L13-L77）；`指南 §n/Lnn` = `backend-v2-implementation-guide.md`；`扩展 §n/Lnn` = `backend-v2-product-extensions.md`；`方案 §n` = 本文件既有节。全部为实读坐标，未实读文件不引。

## 8. 合同对齐矩阵（19 域 ↔ 65 需求行双向覆盖）

### 8.0 对齐口径

- 合同三件套：实施规范（指南，S0-S16 阶段定义=指南 §13 L271-L290）、产品扩展（扩展 §1-§10）、验收矩阵（65 行四列制=矩阵 L7）。重组方案是**代码组织层**的迁移施工图；本节回答「每个域承载合同的哪些需求行、未来按哪个 S 阶段验收、统一 Service 形态长什么样、证据落在哪」。
- 需求行的 `implementation` 现值（partial/unknown）描述的是**代码实现进度**，与重组域是否覆盖是两回事——重组只管「搬进去后归谁」，不改矩阵四列的值。本节只做归属映射，不得被读成「域已建成=需求已实现」。
- 多席施工注意：RW1a/RW2/RW3 正按 §5 施工（实况：`domains/` 已有 link_parse/music/weather 三目录，2026-09-18 实证）；本节对它们是**只读参考**，§5 波次模板优先。

### 8.1 正向表：19 域逐域对齐

| 域（方案 §2.1 编号） | 承载需求行（ID@矩阵行号） | 对应阶段（指南 §13） | 域内统一 Service 入口形态（合同锚点） | 四列验收证据落点 |
|---|---|---|---|---|
| 1 chat_reply | PERSONA-001@L38、KB-001@L40、MEM-001@L41、ROUTE-001@L44、ROUTE-002@L45、BILL-001@L31、BILL-003@L33、AFFINITY-001/002/003@L59/L60/L61、POKE-001@L62（主）、TIME-001@L55（半：temporal）、DISPATCH-001@L34（半：pipeline 收敛起点，指南 L73） | S6/S7/S8/S9/S12（ affinity 计费属 S5） | 能力经 RuntimePipeline 收敛到统一 `execute(context, request)` 入口（指南 §5 L120）；调用顺序 认证→schema→scope→Feature→限流/资源→幂等→业务→输出schema→Review→结果/审计→事件（指南 §5 L122）；policy/rate_limit 对应架构 G 层（指南 §2 L46）；好感事件/points 单位/滚动预算按扩展 §2 L74/L108 | 上述矩阵行四列 + §6 ①关键词门（chat\|affinity\|policy\|security\|llm\|model）+ §6 ⑧全量门；证据记录格式按矩阵 L81-L93 |
| 2 meme | EXPRESSION-001@L63（矩阵引 reaction_store.py:35+reactions.py:458，两件均落本域=方案 §2.3）、POKE-001@L62（表达面：plan_poke mix 权重，扩展 §5 L184） | S12 | `normalize_interaction/claim_interaction/plan_poke/select_expression/validate_platform_expression/build_interaction_intents`（扩展 §5 L190）；四种表情语义不得混称（扩展 §5 L180）；全部经 SendQueue，不支持记 `unsupported_platform_capability`（扩展 §5 L190） | L62/L63 四列 + §6 ①（meme\|reaction） |
| 3 link_parse | SEARCH-002@L54（协同：parsers/ssrf_guard 逐跳校验，扩展 §6 L219）、LEGACY-001@L67（横切：37+ 平台解析行为对照） | S10/S13 | 解析入口受 SearchBroker/DownloadBroker 约束（指南 §2 brokers 层 L65；扩展 §6 `fetch_reference` L215）；本域**无独立专属需求行**，如实登记 | L54/L67 四列 + §6 ①（parse） |
| 4 music | LEGACY-001@L67（横切；矩阵 L67 明列音乐） | S13 | capability 经统一 execute 出站走 Queue（指南 §10 L238）；无专属行，如实登记 | L67 四列 + §6 ①（music） |
| 5 location | LEGACY-001@L67（横切） | S13 | 同上；POI 为结构性空白（方案 §2.1 注），未来立项走 §9.3 四步接入 | L67 四列 + §6 ①（wiki\|moegirl） |
| 6 weather | LEGACY-001@L67（横切；矩阵 L67 明列天气） | S13 | 同上 | L67 四列 + §6 ①（weather\|nmc\|open_meteo） |
| 7 food | LEGACY-001@L67（横切；「所有存量业务」涵盖） | S13 | 同上 | L67 四列 + §6 ①（eat\|food） |
| 8 finance | LEGACY-001@L67（横切；矩阵 L67 明列金融） | S13 | 同上；contracts/finance.py 落 core/contracts（方案 §2.3 W7 注） | L67 四列 + §6 ①（stock\|market\|fx） |
| 9 divination | DIVINATION-001@L64、DIVINATION-002@L65、DIVINATION-003@L66 | S12/S13 | 共享 DivinationService/DrawStore/AssetService/ModelBroker（扩展 §3 L126）；`DrawRequest/DrawResult` DTO（扩展 §3 L134）；REST `/divination/*`（扩展 §3 L136）；错误 `invalid_spread/deck_integrity_mismatch`（扩展 §3 L140+§10 L311）；不为统一入口重写专业算法（扩展 §3 L126） | L64-L66 四列 + §6 ①（divination\|tarot\|ganzhi） |
| 10 schedule | SCHEDULE-001@L56、SCHEDULE-002@L57、SCHEDULE-003@L58（矩阵引 reminders.py:323→域内 store/）、TIME-001@L55（主：timesync，矩阵引 runtime/timesync.py:86） | S11 | `SchedulePlan/TaskTemplate/DependencyEdge/RecurrenceRule/Occurrence/ReminderPolicy` 统一模型（扩展 §4 L148）；`parse_plan…reconcile_missed` 函数族（扩展 §4 L174）；REST `/schedules/*`+`/reminders/{id}/snooze\|skip\|complete`（扩展 §4 L174）；claim_due 持久化 lease（扩展 §4 L168）；错误 `schedule_cycle/missing_calendar/ambiguous_local_time/schedule_conflict/occurrence_expired`（扩展 §4 L176） | L55-L58 四列 + §6 ①（reminder\|schedule\|timesync） |
| 11 notes | LEGACY-001@L67（横切；无专属行，如实登记） | S13 | CRUD 经统一 execute；自然勾选属业务语义不重写（指南 §5 L137） | L67 四列 + §6 ①（notes） |
| 12 subscribe | LEGACY-001@L67（横切；矩阵 L67 明列订阅） | S13 | 适配器族经统一 execute；出站经 Queue | L67 四列 + §6 ①（subscribe\|digest） |
| 13 media | MEDIA-001@L47（OCR 无，矩阵实证）、MEDIA-002@L48（ASR 无，矩阵引 video_understanding.py:62）、TTS-001@L51（**现载体**：capabilities/tts.py 落本域=方案 §2.3 W11；协议 implementation=unknown；目标归宿见 §9.1 creation）、SEARCH-002@L54（协同） | S10 | `MediaAnalysisResult` DTO：observations/OCR/transcript/subtitles/frames/entities/citations/confidence/limitations/usage/trace（指南 §11 L252）；受控下载走 DownloadBroker（指南 §11 L254） | L47/L48/L51 四列 + §6 ①（media\|vision\|tts） |
| 14 files | FILE-001@L49（矩阵引 file_reader.py:102-137）、FILE-002@L50（域内侧：ArtifactGateway 域内**无现槽**→§9.2 建议预留 files/artifacts/；矩阵引 sender/file_gateway.py:382 在 transport）、SEARCH-002@L54（主：downloader） | S10 | `FileAsset`：magic/MIME/配额/owner 校验、API 用 asset_id 非服务器路径、reparse point 检查（指南 §11 L254）；生成→静态检查→原子保存唯一 asset→Review→FileGateway→Queue（指南 §11 L254）；旧 Office 不得伪装现代格式解析成功（指南 §1 L33） | L49/L50/L54 四列 + §6 ①（download\|file） |
| 15 transport | DELIVERY-001@L35（矩阵引 queue.py:237；3 组绕队列未收编）、DELIVERY-002@L36（queue.py:36,584 PARTIAL）、FILE-002@L50（出站段：file_gateway）、SEARCH-002@L54（出站段：worker check_download_url）、STARTUP-001@L69（**注记：bot.py 与 scripts/telegram_resilience.py 在插件树外，本方案不迁移**，见 §8.3 G2） | S6/S13/S14 | `OutboundIntent`：operation/target/parts/feature_id/policy_revision/dedupe_key/expires_at/trace_id（指南 §10 L238）；发送前复验权限/feature/过期/确认/part 状态；领取受控许可=线性化点（指南 §10 L238）；投递状态机 queued→sending→delivered/failed/unknown/cancelled（指南 §7 L198） | L35/L36/L50/L54 四列 + §6 ①（sender\|queue\|mail）+ §6 ⑦插件入口冒烟 |
| 16 assistant | LEGACY-001@L67（横切；矩阵 L67 明列校园；daily_assist 属存量业务全员登记，指南 §5 L137） | S13 | 同上；推送名单空=整链不注册的保守门保持 | L67 四列 + §6 ①（daily_assist\|campus） |
| 17 ops | LOG-001@L29（域内侧：日志源白名单/分类，指南 §8 L210）、REG-001/002@L19/L20（域内侧：矩阵引 runtime/feature_catalog.py+feature_gate.py→域内 features/，方案 §2.3）、HEAL-001@L70（矩阵引 alerts.py:154→monitor/）、INCIDENT-001@L72（矩阵引 error_report.py:269→monitor/）、ACTION-001@L68（executor 落点之一）、REPAIR-001@L71（**无现载体**，建议本域立项 recovery/，见 §8.3 G8）、DOC-001@L75（数据源侧：echo 帮助注册表在 chat_reply，本域供监控面） | S3/S5/S14 | 恢复动作进 ControlActionRegistry，带 executor/前置/验证器/补偿器（扩展 §7 L229）；Incident 字段清单（扩展 §7 L235）；通知经 SendQueue+持久化 outbox，告警链自故障防递归（扩展 §7 L241）；目标命令 `/bot incidents\|recovery\|repairs`（扩展 §7 L243） | L19/L20/L29/L68/L70/L71/L72/L75 四列 + §6 ①（feature\|control_plane）+ §6 ⑤树卫生 |
| 18 core | CORE-001@L16（contracts/ 11 件→域内 contracts/）、AUTH-001@L17、REG-001/002@L19/L20（主：control_plane/features.py+services.py）、CFG-001@L21、RELOAD-001@L22、API-001@L23（v1.py 28 路由+contracts/envelope.py，envelope 实存已验证）、SSE-001@L24、RESOURCE-001@L25（resources.py+supervisor 双点同域）、TASK-001@L26、AUDIT-001@L27、TRACE-001@L28、METRIC-001@L30、ISO-001/002@L14/L15（supervisor）、AUTH-002@L18（ipc.py:46）、WORLD-001@L39（workspaces.py:43）、WORKSPACE-001@L46（workspaces.py:96）、DB-001@L42（**无载体**，建议域内 brokers/ 立项，见 §8.3 G6）、SEARCH-001@L53（search_service.py:145→域内 search/；xhs/YT/X/LinuxDo 缺）、DISPATCH-001@L34（半：decision/dispatcher.py shadow） | S1-S5/S8/S9/S10 | `/api/v1` 统一 envelope+error 协议（指南 §6 L146/L149）；`execute(context, request)`（指南 §5 L120）；ProductManifest 16 类节点+必填字段（指南 §5 L124/L126）；`compile_registry/resolve_states/preview_change/apply_change`+Config describe/validate_patch/prepare_reload/activate_revision（指南 §5 L139）；CAS/expected_version/Idempotency-Key（指南 §6 L149） | L14-L28/L30/L34/L39/L42/L46/L53 四列 + §6 ④doc_sync + §6 ①（control_plane） |
| 19 render | REPLY-001@L37（矩阵引 plain_text.py:286,340；字素切分无）、DELIVERY-001@L35（Review/Renderer 段）、DOC-001@L75（help 呈现段）、INCIDENT-001@L72（错误卡渲染兜底段） | S6 | `ReplyDraft` schema_version=reply.v1、lines[1..12]、每行≤300 字素（指南 §10 L240）；normalize_reply_lines 管线（指南 §10 L242）；四套分词分开（指南 §10 L244）；TG 不设 Markdown parse_mode | L37 四列 + §6 ②渲染契约 + §6 ③哈希门（W13 `--write` 重录） |
| 留守：根 `__init__.py`+`config.py`（方案 §2.1 末行） | DISPATCH-001@L34（matcher 注册段永驻根，方案 §4.4）、REG-001@L19（AST 发现面扫到根注册）、LEGACY-001@L67（50 matcher 收编基准，矩阵 L67 引 base_router.py:98） | S6/S13/S3 | 注册时序不变是 NoneBot 语义前提（方案 §3.2）；config.py 案 A 留守（方案 §4.3） | 上述行四列 + §6 ⑦插件入口冒烟 + §6 ④config-catalog 门 |
| （预留，本方案 §9.1 新增）creation | TTS-001@L51（目标归宿）、IMAGE-001@L52（**现无任何载体**，矩阵 L52 implementation=unknown） | S10 | 见 §9.1 契约草案（全部 reserved） | L51/L52 四列；实现前仅 §9.4 占位门 |

### 8.2 反向表：65 行 → 域（全量核对，按矩阵行序分组）

| 矩阵行 | 主承域 | 协同域 | 覆盖状态 |
|---|---|---|---|
| L13 BASE-001 | **域外（主会话 S0）** | ops/smoke 供盘点工具面 | 域外（§8.3 G1） |
| L14/L15 ISO-001/002 | core/supervisor | — | 覆盖 |
| L16 CORE-001 | core/contracts | — | 覆盖 |
| L17 AUTH-001 | core/control_plane | — | 覆盖 |
| L18 AUTH-002 | core/supervisor（ipc） | core/control_plane（授权层） | 覆盖 |
| L19/L20 REG-001/002 | core/control_plane | ops/features（feature_catalog/feature_gate） | 覆盖（双域分工） |
| L21 CFG-001 | core/control_plane | 留守 config.py（字段源） | 覆盖 |
| L22 RELOAD-001 | core/control_plane | ops（S14 动作面） | 覆盖 |
| L23 API-001 | core/control_plane | core/contracts（envelope） | 覆盖 |
| L24 SSE-001 | core/control_plane | — | 覆盖 |
| L25 RESOURCE-001 | core/control_plane | core/supervisor | 覆盖 |
| L26 TASK-001 | core/control_plane | — | 覆盖 |
| L27 AUDIT-001 | core/control_plane | ops/audit | 覆盖 |
| L28 TRACE-001 | core/control_plane | — | 覆盖 |
| L29 LOG-001 | core/control_plane（log_collectors） | ops（审计/监控面） | 覆盖（双域分工） |
| L30 METRIC-001 | core/control_plane | chat_reply/llm_engine（usage 源） | 覆盖 |
| L31 BILL-001 | chat_reply/llm_engine（ledger） | — | 覆盖 |
| L32 BILL-002 | chat_reply/llm_engine（usage_service，S5 段） | creation 预留（S10 段 TaskPorts/TTS/绘图，§9.1） | 覆盖（S10 段=预留） |
| L33 BILL-003 | chat_reply/llm_engine | core/control_plane（CAS 预算事务，扩展 §1 L58） | 覆盖 |
| L34 DISPATCH-001 | chat_reply/runtime（pipeline 收敛起点）+ core/decision（dispatcher） | 留守根 `__init__.py`（注册段） | 覆盖（双域+留守） |
| L35 DELIVERY-001 | transport | render（Review/Renderer）、chat_reply（3 组绕队列收编面） | 覆盖 |
| L36 DELIVERY-002 | transport | — | 覆盖 |
| L37 REPLY-001 | render | chat_reply（模型输出面） | 覆盖 |
| L38 PERSONA-001 | chat_reply/character（persona_set，矩阵引 :32） | core/control_plane（生命周期/发布权） | 覆盖（分工待实施卡细化，§8.3 G11） |
| L39 WORLD-001 | core/control_plane（workspaces.py:43） | chat_reply/character（业务服务未来落点） | 覆盖（同 G11） |
| L40 KB-001 | chat_reply/character（vector_knowledge:386,1681） | core（索引切换治理） | 覆盖 |
| L41 MEM-001 | chat_reply/character（memory:44；memory_service V2 席在飞补全中，COORDINATION L6） | core（墓碑/审计面） | 覆盖 |
| L42 DB-001 | **缺口**（无载体） | 建议 core/brokers/ 立项 | 缺口（G6） |
| L43 TEACH-001 | **缺口**（无载体） | 建议 chat_reply/character 或独立 services 位立项 | 缺口（G7） |
| L44 ROUTE-001 | chat_reply/llm_engine（model_router:624） | core/control_plane（执行门） | 覆盖 |
| L45 ROUTE-002 | chat_reply/runtime（content_route:133） | meme（表情联动面） | 覆盖 |
| L46 WORKSPACE-001 | core/control_plane | — | 覆盖 |
| L47 MEDIA-001 | media | — | 覆盖（OCR 缺=实现缺口非组织缺口） |
| L48 MEDIA-002 | media | — | 覆盖（ASR 缺同上；预留槽见 §9.2） |
| L49 FILE-001 | files | — | 覆盖 |
| L50 FILE-002 | files（ArtifactGateway 建议槽）+ transport/sender（file_gateway:382，矩阵引） | render（Review） | 覆盖（双域；域内槽缺口见 G9.2） |
| L51 TTS-001 | 现载体 media/capabilities/tts.py；**目标归宿 creation/tts（§9.1，归属裁决见 §10 W-PA2）** | chat_reply（content 门） | 覆盖（预留态） |
| L52 IMAGE-001 | creation/image（**零现载体**，§9.1 预留） | render（Review→asset） | 覆盖（纯预留） |
| L53 SEARCH-001 | core/search | link_parse（复用解析） | 覆盖（xhs/YT/X/LinuxDo 缺=实现缺口；适配器槽见 §9.2） |
| L54 SEARCH-002 | files（downloader）+ transport（worker） | link_parse（ssrf_guard）、media | 覆盖（三域共担） |
| L55 TIME-001 | schedule/timesync | chat_reply/character（temporal:128） | 覆盖（双域分工） |
| L56/L57/L58 SCHEDULE-001/002/003 | schedule | — | 覆盖（001/002 无现载体=实现缺口，矩阵已标 unknown） |
| L59/L60/L61 AFFINITY-001/002/003 | chat_reply（affinity+addressing） | core（事件/outbox 面） | 覆盖 |
| L62 POKE-001 | chat_reply/capabilities（poke:146） | meme（plan_poke/select_expression） | 覆盖（双域分工） |
| L63 EXPRESSION-001 | meme | — | 覆盖 |
| L64/L65/L66 DIVINATION-001/002/003 | divination | render（卡片回退）、chat_reply（解读上下文） | 覆盖 |
| L67 LEGACY-001 | **全域横切**（矩阵 L67 点名：天气/金融/音乐/订阅/归档/校园；「所有存量业务逐个迁移」） | core/supervisor（沙箱）+ 各域 manifests | 覆盖（横切；重组≠沙箱迁移，见 G10） |
| L68 ACTION-001 | core/control_plane（actions:57） | ops（真实 executor 落点） | 覆盖 |
| L69 STARTUP-001 | **域外**（bot.py+scripts/telegram_resilience.py，均不在 329 文件盘点内） | — | 域外（G2） |
| L70 HEAL-001 | ops/monitor（alerts:154） | core/control_plane | 覆盖 |
| L71 REPAIR-001 | **缺口**（无载体） | 建议 ops 立项 recovery/ | 缺口（G8） |
| L72 INCIDENT-001 | ops/monitor（error_report:269） | render（错误卡） | 覆盖 |
| L73 ACCEPTANCE-001 | **域外**（scripts/e2e_acceptance.py，矩阵 L73 引） | ops/smoke（未来 Runner Service 化落点候选） | 域外（G3） |
| L74 ACCEPTANCE-002 | **域外**（Artifact/ReportService 无载体） | ops（候选）、creation/media（产物源） | 域外+缺口（G3） |
| L75 DOC-001 | chat_reply/echo（数据源 _HELP_ENTRIES）+ core（投影框架 compile_catalog，指南 §12 L268） | **域外**（scripts/doc_sync+command_catalog 生成器不迁移，方案 §1.3） | 半覆盖（G5） |
| L76 RELEASE-001 | **域外**（scripts/dev.ps1:875，矩阵 L76 引） | — | 域外（G4） |
| L77 RELEASE-002 | **域外**（主会话授权部署） | — | 域外（G4） |

### 8.3 覆盖缺口清单（如实登记，不虚构归属）

| # | 缺口 | 涉及行 | 定性 | 处置建议 |
|---|---|---|---|---|
| G1 | V21-BASE-001（S0 冻结基线/变更归属） | L13 | **域外**：S0 inventory 是主会话职责，19 域是搬迁对象不是执行者 | 维持主会话；ops/smoke 只提供盘点工具面 |
| G2 | V21-STARTUP-001（NoneBot/TG 鉴权/实例冲突） | L69 | **域外**：bot.py、scripts/telegram_resilience.py 均在插件树外，方案 §1.3 已定 bot.py 只读不改 | 方案 §6 ⑦插件入口冒烟已覆盖「不弄断」半边；行为验收归 S14，与重组正交 |
| G3 | V21-ACCEPTANCE-001/002（自动 Runner+admin 媒体产物） | L73/L74 | **域外+无载体**：e2e_acceptance.py 在 scripts/；AcceptanceRunner/ReportService 未来 Service 化无域内槽 | 二选一：落 ops/smoke（贴 smoke 族）或未来独立 acceptance 域；待用户/主会话裁决，本期不预设 |
| G4 | V21-RELEASE-001/002（门禁/依赖重建/授权部署） | L76/L77 | **域外**：dev.ps1 与部署授权永不进插件树 | 维持域外；§6 ⑧引用其判据 |
| G5 | V21-DOC-001（统一投影） | L75 | **半覆盖**：数据源（echo 注册表）在 chat_reply、投影框架在 core，但生成器本体在 scripts/ 域外 | 维持现状（方案 §1.3：16 脚本靠垫片零改动）；波内漂移按 §6 ④收口 |
| G6 | V21-DB-001（DatabaseBroker，query_id 参数化） | L42 | **无载体**：矩阵四列全 unknown；Broker 层在指南 §2 有位、方案 §2.1 无目录 | 建议 core 域增 `brokers/` 子目录立项；属实现缺口非重组缺口 |
| G7 | V21-TEACH-001（TeachingService） | L43 | **无载体**：矩阵全 unknown；指南 §9 L232 有定义 | 建议落 chat_reply/character（贴偏好/记忆族）或独立 teaching/；待立项裁决 |
| G8 | V21-REPAIR-001（自修复待审补丁） | L71 | **无载体**：矩阵全 unknown；扩展 §7.1 L231 有全流程 | 建议落 ops/ 新增 recovery/（与 monitor 同域）；注意「待审不自动部署」红线（AGENTS.md 顶注） |
| G9 | TTS-001/IMAGE-001 归属与零载体 | L51/L52 | L51 现载体（tts.py）在 media、目标协议域 creation 未建；L52 零载体 | §9.1 建 creation 预留域；tts.py 归属裁决=§10 W-PA2；FILE-002 域内 artifacts 槽=§9.2 |
| G10 | LEGACY-001 与重组的关系 | L67 | **正交性声明**：代码搬家（本方案）≠沙箱迁移+行为对照（S13）；搬完不等于隔离完成 | 两线共享垫片纪律与 manifests 面；S13 验收以矩阵 L67 为准，本方案不代替 |
| G11 | PERSONA/WORLD 生命周期双域分工 | L38/L39 | 组织覆盖但分工未细化：persona_set 在 chat_reply，draft/publish/activate 面（矩阵引 workspaces.py）在 core | 各自叶执行卡（指南 §13 L292）里写明 DTO 归属与调用方向；本期不强行改映射 |
| G12 | 无专属需求行的小域 | L67 | music/location/weather/food/notes/subscribe/assistant 七域仅靠 LEGACY-001 挂靠 | 如实登记即可——LEGACY-001 本就要求「逐个列已有业务，不能只测天气代表全插件」（矩阵 L98）；七域在 S13 行为对照全表中各占一行 |

## 9. 未来功能预留（TTS/AI 绘图生成域 + S10 插槽复核 + 通配规则 + 门禁网接入）

> 用户令锚定：「这些计划必须完美适配 V2.1 的合同，同时还得加入 TTS 语音生成、AI 绘图等未来功能的接口、协议预留。」
> **本节全部为协议预留，零实现承诺**：凡标注 `reserved: 依赖外部 provider 配置，未实现` 的条目，矩阵四列维持 unknown（矩阵 L101：未配置外部 provider 只可标协议实现、live blocked；不能宣称整机可发布）。

### 9.1 creation 生成域（预留态第 20 域，不改 RO §2.1/§2.2 既有 19 域定义）

**路径**：`domains/creation/tts/`、`domains/creation/image/`、`domains/creation/extensions/`、`domains/creation/_common/`（任务状态机与 asset 交付共用件，同样 reserved）。
**与既有 §2.3 的关系**：`capabilities/tts.py` 现映射 `media/capabilities/`（§2.3 W11 行）——creation 激活前 tts.py 留 media 原映射不动；激活时迁移或留薄适配为**归属裁决项**（§10 W-PA2）。creation 域骨架只新增目录与 reserved DTO，零移动、零冲突（W1a-W3 不受影响）。

#### 9.1.1 TTS 接口契约草案（合同锚点：矩阵 L51 V21-TTS-001；指南 §11 L256；扩展 §1 L23/L49）

`reserved: 依赖外部 provider 配置，未实现`

**REST 面**（挂 `/api/v1` 前缀，指南 §6 L143）：GET `/tts/providers`、GET `/tts/voices`、GET `/tts/capabilities`；POST `/tts/preview`、POST `/tts/jobs`；GET `/tts/jobs/{id}`；POST `/tts/jobs/{id}/cancel`（指南 §11 L256）。静态路径先于参数路由（指南 §6 L176）。

**TTSJobRequest DTO（字段级）**：

| 字段 | 类型/约束 | 合同锚点 |
|---|---|---|
| text | `str\|None`，≤3000 字符 | 指南 §11 L256 |
| approved_reply_id | `str\|None`，与 text **二选一**；引用已过 Review 的出站草稿，不得由模型自报 | 指南 §11 L256；指南 §10 L240 metadata 由运行时写 |
| provider / model / voice / language / format | 枚举来自注册表能力目录；禁任意音色路径/URL；禁原始 SSML | 指南 §11 L256 |
| speed | float，默认 1.0，范围 0.75..1.25 **∩ provider 能力** | 指南 §11 L256 |
| workspace_id / target / version | 隔离与版本绑定 | 指南 §11 L256 |
| 输出上限 | 时长 ≤60s 且体积 ≤20MiB | 指南 §11 L256 |

**参数校验与错误码**：Pydantic 严格 DTO 拒未知字段/NaN/Infinity（指南 §6 L149）；未支持参数 422 `unsupported_parameter` 不静默丢弃；provider 未配置 503 `dependency_unavailable`；价格缺失且无保守上限 503 `price_unavailable`（扩展 §10 L311）；预算超 429 `budget_exceeded`。错误目录为单一注册源（指南 §6 L194）。

**任务状态机与取消**：pending→admitted→running→succeeded/failed/cancelled/unknown；`cancel_requested` ≠ `cancelled`（指南 §7 L198）；未知已受理请求**不盲重合成**（指南 §11 L256）；取消保留可能已产生费用（扩展 §1 L58）。

**usage 多单位计费**（对齐矩阵 L32 V21-BILL-002「字符/秒/图/次/Token 账单、未支持不虚构」）：UsageQuantity metric 取 `characters / audio_seconds / requests`（扩展 §1 L16 字段表）；Token 仅 provider 真报才填，否则 `not_applicable`，**不得按字符伪造精确 Token**（扩展 §1 L23）；确定性算例：TTS 1200 字符×每百万 15=0.018，Token 字段 not_applicable（扩展 §1 L49）；金额 Decimal 禁浮点（扩展 §1 L29）；预算 CAS 预留/每 attempt 结算/UNKNOWN 挂账（扩展 §1 L58）。

**资产**：asset 记录时长/MIME/codec/provider_operation/usage/成本/fallback（指南 §11 L256）；走 AssetBroker/ArtifactGateway（V21-FILE-002 面，指南 §11 L254）。

**出站**：Review 后断句合成（指南 §11 L256）；TG/QQ 编码按**实际能力验证**，文件回退**不得称原生 voice**（指南 §11 L256）；出站标签不朗读（矩阵 L51 验收重点）；经 render（Review）→transport（Queue/OutboundIntent，指南 §10 L238）出站，不走旁路。

**安全检查**：内容门复用 chat_reply/security Review 面；资源准入 TTS 全局 2/同会话 1（指南 §4 L102 池化表）；S1 隔离 worker 内执行。

#### 9.1.2 AI 绘图接口契约草案（合同锚点：矩阵 L52 V21-IMAGE-001；指南 §11 L258；扩展 §1 L23/L49）

`reserved: 依赖外部 provider 配置，未实现`

**REST 面**：GET `/image-generation/providers`、`/models`、`/capabilities`；POST `/image-generation/preview`、`/jobs`；GET `/image-generation/jobs/{id}`；POST `/image-generation/jobs/{id}/cancel`（指南 §11 L258）。

**ImageJobRequest DTO（字段级）**：

| 字段 | 类型/约束 | 合同锚点 |
|---|---|---|
| task | 枚举 `text_to_image / image_to_image / inpaint` | 指南 §11 L258 |
| prompt / negative_prompt | ≤4000 / ≤2000 字符 | 指南 §11 L258 |
| assets / mask | 引用 `asset_id`（非服务器路径），输入 ≤20MP | 指南 §11 L258 |
| provider / model / size | size 取 provider 支持尺寸枚举；不默认本地 GPU | 指南 §11 L258 |
| count | 默认 1，最大 2 | 指南 §11 L258 |
| seed / steps / guidance | 可选；steps ≤50 ∩ provider | 指南 §11 L258 |
| workspace_id / version | 隔离与版本绑定 | 指南 §11 L258 |

**参数校验**：未支持参数 422 不静默丢弃；**不接任意 workflow/code/路径**（指南 §11 L258）；输入图获取走 DownloadBroker（对齐 SEARCH-002@L54 面），不接任意 URL 抓取。

**任务状态机/取消**：同 §9.1.1；验收重点「未知不重发」（矩阵 L52）；取消在途不假成功（对齐 V21-TASK-001@L26 语义）。

**usage 多单位计费**：metric 取 `images / requests` + 分辨率档独立计费（扩展 §1 L23）；算例：绘图 2 张×每张 0.04=0.08，**不伪造 Token**（扩展 §1 L49）；一个请求多张图按实际数量结算，重试是否重复收费由 provider 事实决定（扩展 §1 L56）。

**资产与出站**：输出解码/真实 MIME/尺寸/帧数/**EXIF 清理**→Review→asset；**默认预览→确认发送**（指南 §11 L258；确认 token 绑定 actor/目标/版本/摘要、120s 一次消费，指南 §6 L149）；出站经 render→transport 主链。

**安全检查**：内容安全门（minors 等硬红线沿用 chat_reply/security 既有语义）；Review 不过不出 asset；真伪 MIME/magic 校验对齐 FILE-002 面。

### 9.2 files / media / search 域 S10 协议插槽复核

S10 =「媒体/文件/搜索/代码资产/TTS/绘图协议与处理器」（指南 §13 L284）。逐项复核方案 §2.2 现插槽：

| S10 协议项 | 矩阵行 | 方案 §2.2 现插槽 | 复核结论 | 建议预留槽（全部 reserved） |
|---|---|---|---|---|
| 图片/OCR/GIF | L47 | media/ingest（vision_describe） | 有识图无 OCR（矩阵 L47「OCR 无」实证） | `domains/media/ingest/extensions/`——OCR 适配器落位处 |
| ASR/视频/字幕 | L48 | media/ingest（video_understanding/transcribe） | 有转写无 ASR（矩阵 L48「ASR 无」） | 同上 extensions/ 内 asr 子槽；抽帧上限/overlap 去重参数随实现卡 |
| 文件读取 | L49 | files/sources（file_reader） | 已覆盖（.ppt 冒充风险=实现面，指南 §1 L33） | 无需新槽 |
| 代码资产 ArtifactGateway | L50 | **域内无槽**（file_gateway.py 在 transport/sender） | 「生成+原子保存唯一 asset」半边无域内家（指南 §11 L254） | `domains/files/artifacts/` 预留（§10 W-PA3） |
| 九源搜索 | L53 | core/search（5 文件，无 per-source 结构） | search_service 单体承载；扩展 §6 L198-L209 十源（9 专源+general）适配器无处落 | `domains/core/search/adapters/` 预留，一源一文件（§10 W-PA4） |
| SSRF/注入防护 | L54 | link_parse/parsers/ssrf_guard + files/sources/downloader + transport worker | 主链三点已覆盖；DNS rebinding 无证据（矩阵 L54） | 增强实现落 DownloadBroker（建议 files 域内槽），不新增域 |
| TTS | L51 | media/capabilities/tts.py（现载体） | 协议面（providers/voices/capabilities/jobs）缺 | 目标归宿 creation/tts（§9.1.1；归属裁决 §10 W-PA2） |
| 绘图 | L52 | **无** | 零载体 | creation/image（§9.1.2） |

### 9.3 通配规则：每域 extensions/ 槽位 + 注册表开放条目 + 新功能四步接入

- **每域 extensions/ 槽位**：19 域各建 `domains/<域>/extensions/`（占位文件首行 docstring 含 `reserved:` 声明）。新子功能默认落 `extensions/<名>/`，验证成熟后晋升为正式子板块（§2.2 树结构变更走方案书修订+layout 门同步）。extensions 不是垃圾抽屉：层禁令（指南 §2 L59-L69）全量适用——禁读生产凭据、禁绕 Broker、禁绕 Queue。
- **注册表开放条目**：ProductManifest 16 类节点（指南 §5 L124）中，extensions 起步开放七类：`feature / sub_feature / command / help / scheduled_job / control_action / config`；节点必填字段（stable_id/parent_id/kind/label/aliases/implementation_ref/capability_id/route_kind/default_enabled/reload_strategy/dependencies/required_roles/config_keys/documentation_refs/privacy_level/protected/version，指南 §5 L126）不可缺省；`default_enabled` 对预留/新功能**一律 false**。AST 发现未登记入口阻塞发布（指南 §5 L135）。
- **新功能四步接入**：
  1. **注册**：manifest 显式登记（动态注册必须显式 manifest，指南 §5 L135）；
  2. **协议**：DTO 进 contracts/ 严格形态 + `/api/v1` envelope + 错误码进单一错误目录（指南 §6 L194；扩展 §10 L311 集中注册）；
  3. **门禁**：FeatureState 默认关 + 资源准入（指南 §4 池化参数）+ Review 面；休眠参数登记 `status=dormant`+理由，**禁止冒充已生效**（扩展 §9.2 L299）；
  4. **投影**：CommandDescriptor→help/命令目录/OpenAPI/配置册（指南 §12 L268；扩展 §9 全节）；`--check` 只读、`--write` 显式、连续生成两次字节相同（扩展 §9.2 L301）；菜单不把无 handler 占位项显示为可用（扩展 §9.2 L303）。
- 与 CMD 席 v21r2-command-spec 的衔接：extensions 新命令的四段式正形与九形态约束以该规格为准（COORDINATION L1），本节不重复定义命令语法。

### 9.4 预留如何进 §6 门禁网（对 RO §6.1 的具体化，不改 §6 本体）

- **占位目录存在性**：§6.1 `tests/test_domain_layout.py` 增断言——①`domains/creation/{tts,image,extensions,_common}/` 存在；②19 域 `extensions/` 存在；③每个占位首行 docstring 匹配 `^reserved:`；④占位文件数与注册表 dormant 条目一致（防「目录在、册上无」漂移）。
- **契约形态 lint**：reserved 模块只允许定义 Pydantic DTO/协议常量/枚举——禁 import `httpx/requests/nonebot`、禁读生产 config、禁起线程/网络（对齐 V21-CORE-001@L16 import 副作用探针语义）；实现建议为独立进程 import 探针测试（矩阵 L16 验收手段同款）+ ruff 规则集，不上重型 AST 框架。
- **投影隔离**：reserved DTO 不进 OpenAPI/help/命令目录（扩展 §9.2 L303「无 handler 占位项不显示为可用」）；dormant 参数进配置册必须带 dormant 标记（扩展 §9.2 L299）。
- **波门接线**：凡动 creation/ 或任一 extensions/ 的波，§6 ① 关键词追加 `creation|extensions`；§6 ⑤⑦ 照常。W13 渲染波不受影响（creation 无模板）。

## 10. 波次修订建议（基于 §8 对齐矩阵 + §9 预留；不推翻已开工的 W1a-W3）

> 前提：W1a/W1b/W2/W3 已开工或完成（实况：`domains/` 已有 link_parse/music/weather，2026-09-18 实证）——本节只列**增补**，不改既有 16 波顺序与范围（方案 §5）。增补波遵循 §5 通用波模板五步与 §6 门禁。

| 增补 | 内容 | 插入位置 | 优先级 | 冲突面/理由 |
|---|---|---|---|---|
| W-PA1 creation 骨架波 | 新建 `domains/creation/{tts,image,extensions,_common}/` 占位（reserved docstring）+ §9.1 两份 DTO 草案落 reserved 模块 + §9.4 layout/lint 门接线 | 独立小波，建议 W9 之后、W10 之前（或与任一无冲突波并行窗口） | **中** | 零移动零冲突（纯新增目录）；早建可让 W11 媒体波直接看到 TTS 目标归宿 |
| W-PA2 tts.py 归属裁决（W11 微调，需裁定） | 二选一：a) tts.py 维持 §2.3 原映射留 media，creation 激活时再迁；b) W11 波把 tts.py 直接落 `domains/creation/tts/`（W11 表述改「media 10 件 + creation 1 件」）。**改 RO §2.3 映射，裁决权在用户/主会话**，两案皆不阻塞 W11 开波（a 案=零改动默认案） | W11 开波前裁定 | 中 | 推荐 a 案：最小改动+垫片面不变；b 案收益仅目录语义，代价是 W11 与 creation 两个面耦合 |
| W-PA3 files artifacts 槽 | W9（notes+files）波内加建 `domains/files/artifacts/` 占位（reserved） | 随 W9 | 低 | W9 未开波，顺手一步；FILE-002@L50 域内家（§9.2） |
| W-PA4 search adapters 槽 | W16（core）波内加建 `domains/core/search/adapters/` 占位（reserved，扩展 §6 十源表为落位图） | 随 W16 | 低 | W16 在远期；SEARCH-001@L53 缺源适配器落位处（§9.2） |
| W-PA5 每域 extensions/ 占位 | 各域本波顺手建 `extensions/` 占位（波模板第 2 步移动后加半步），或统一并入尾声波批量建 | 随各波/尾声 | 低 | 纯新增；若嫌逐波散碎，尾声波一次建齐+layout 门一次断言亦可 |
| W-PA6 合同对齐验证波 | 尾声前（或并入尾声）跑 §8/§9 对齐复核：test_domain_layout 全绿 + §8.2 反向表 65 行逐一核对四列更新责任归属 + §8.3 缺口清单 G1-G12 复核（已立项的销账、仍缺口的保持登记） | 尾声波内，垫片退役统计之前 | **中** | 这是「重组完成」与「合同覆盖」两个概念的收口闸；防「搬完=做完」误判（G10 正交性） |

**明确不推荐**：①不为 music/location/weather/food 等小域单设对齐波（§8.1 表已逐域标注，LEGACY-001 横切足够）；②不把 creation DTO 实现排进任何既有波（reserved 纪律，矩阵 L101 协议≠可用）；③不因 §9 预留改动 W14-W16 热区窗口判断（§4.1 冲突矩阵不受影响）。

**执行纪律不变项**：所有增补波仍守 §5 波模板（波前取证→git mv→垫片→门禁同步→回归+回滚点）、§6 直跑纪律、多代理按文件域互斥（AGENTS.md 第 7 条）；代理无 git 写操作。


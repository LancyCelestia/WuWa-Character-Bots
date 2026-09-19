# 代码地图（CODE-MAP）

> 本文件是**导航件**，不是说明件：只给「哪块代码在哪、顺着哪条链走、出什么症状查哪个文件」，
> 一律用链接指向真身，**不复制任何正文**。 deeper 细节看链接目标。
>
> - 功能全貌与话术口径 → [AGENTS.md](../AGENTS.md) 第四部分；历史与裁定 → [docs/HANDBOOK.md](HANDBOOK.md)
> - 命令手册 → [COMMANDS.md](../COMMANDS.md) / [docs/command-catalog.md](command-catalog.md)（机器生成）
> - 机器事实册（配置字段数/topic 数等以它为准）→ [docs/auto-facts.md](auto-facts.md)
> - 路由矩阵 → [docs/route-matrix.md](route-matrix.md)；配置目录 → [docs/config-catalog-full.md](config-catalog-full.md)
> - SQLite 库 owner → [docs/db-owners.md](db-owners.md)；渲染契约 → [docs/rendering-contract.md](rendering-contract.md)
>
> **取证时点**：HEAD `21b702c`（2026-09-20，MAP-1 席）。域数、文件数、符号名均 `find`/`grep`/`git ls-files` 实跑。
> 工作树多会话共享且正在推进 20 域重组的**分批 commit**，数字会漂；本文所有计数旁边都附了复跑命令，改完自己重跑一遍。

## 0. 仓库骨架（一眼版）

```
ChatBot/
├── bot.py                         ← NoneBot 启动 + 崩溃守卫（503 行）
├── plugins/bot_unified_runtime/   ← 主包（635 个 .py）
│   ├── __init__.py                ← 插件入口：matcher 注册 + 装配（8735 行，未拆）
│   ├── config.py                  ← 633 个 bot_* 字段的 pydantic 配置，1630 行（机器册 docs/auto-facts.md 口径；AGENTS 写 529 已过期），裁定留守原位
│   ├── domains/<21 域>/           ← 真身（424 个 .py），见 §1
│   └── 旧路径（211 个 .py）        ← 158 张 PEP 562 垫片 + control_plane/ 真身 + 入口件，见 §1.2
├── scripts/                       ← dev.ps1 任务入口 + runtime_paths.py + 三个生成物脚本
├── tests/                         ← 471 个 .py，全离线 mock
├── personas/shorekeeper/          ← 人格源（Runtime 副本由 sync 脚本对齐）
└── docs/                          ← 本文件所在；design/ 存规格与逐波施工日志
```

运行数据**不在本仓库**：`data/` 相对路径全部经 [scripts/runtime_paths.py](../scripts/runtime_paths.py)
重映射到仓库外 `../ChatBot_Runtime/`。见 §3 症状 S13。

---

## 1. 域清单（domains/ 实测 21 个域）

> 「旧路径垫片」列写的是**该域真身迁移前所在的位置**（现在是一张 re-export 薄壳）。
> 垫片语义：从旧路径 `import` 拿到的是**同一个对象**，但 **monkeypatch 必须打真身新路径**，
> 打旧路径只改垫片命名空间、对真身无效（本仓踩过多次的坑）。
> 计数复跑：`find plugins/bot_unified_runtime/domains/<域> -name '*.py' | wc -l`

| 域 | 干什么（一句） | 真身 | 旧路径垫片（在盘数 / 代表件） | 关键公开符号 | 归属批次 | 常驻门禁 |
|---|---|---|---|---|---|---|
| `chat_reply` | 人格对话、好感度、记忆反思、称谓、门禁限流、安全审查、路由管线、LLM 引擎、帮助命令面 | [domains/chat_reply/](../plugins/bot_unified_runtime/domains/chat_reply/)（83 py） | 62 张：[capabilities/chat.py](../plugins/bot_unified_runtime/capabilities/chat.py)、[runtime/base_router.py](../plugins/bot_unified_runtime/runtime/base_router.py)、[runtime/pipeline.py](../plugins/bot_unified_runtime/runtime/pipeline.py)、[policy/gate.py](../plugins/bot_unified_runtime/policy/gate.py)、[llm/model_router.py](../plugins/bot_unified_runtime/llm/model_router.py)、[security/content_safety.py](../plugins/bot_unified_runtime/security/content_safety.py) | `RuntimePipeline`、`classify_message_route`、`RouteKind`(34 成员)、`evaluate_policy` | v21r2 W15a–W15e；物理入库 G-0 批2/5 | [tests/test_doc_sync_gates.py](../tests/test_doc_sync_gates.py)、[tests/test_rendering_contract.py](../tests/test_rendering_contract.py)（98 个测试文件引用本域） |
| `core` | 系统内核：配置体检、契约、凭据、决策引擎、联网搜索基建、进程沙箱 | [domains/core/](../plugins/bot_unified_runtime/domains/core/)（41 py） | 5 张：[config_readiness.py](../plugins/bot_unified_runtime/config_readiness.py)、[contracts/media.py](../plugins/bot_unified_runtime/contracts/media.py)、[decision/trace.py](../plugins/bot_unified_runtime/decision/trace.py) | `outbound_registry.TransportEntry`、`text_boundary.is_trigger`、`decision.engine` | v21r2 RWOC/W16；G-0 批1/5 | [tests/test_contracts_v21.py](../tests/test_contracts_v21.py)、[tests/test_a18_gate_idempotency_rollback.py](../tests/test_a18_gate_idempotency_rollback.py) |
| `ops` | 运维面：特性开关、告警监控、错误卡、审计、事件存储、烟测与验收、恢复与修复 | [domains/ops/](../plugins/bot_unified_runtime/domains/ops/)（40 py） | 2 张：[audit/\_\_init\_\_.py](../plugins/bot_unified_runtime/audit/__init__.py)、[capabilities/debug.py](../plugins/bot_unified_runtime/capabilities/debug.py) | `EventStore`、`ProductFeatureGate`、`build_error_report`、`build_feature_control_result` | v21r2 RWOC/W16；G-0 批1/5 | [tests/test_runtime_feature_gate.py](../tests/test_runtime_feature_gate.py)、[tests/test_error_card_contract.py](../tests/test_error_card_contract.py) |
| `render` | 出站文本与卡片渲染：说人话/脱敏、云母壳、主题 token、playwright 后端、7 张 HTML 模板 | [domains/render/](../plugins/bot_unified_runtime/domains/render/)（14 py + 7 html） | 12 张：[output/renderer.py](../plugins/bot_unified_runtime/output/renderer.py)、[output/card_render/theme_tokens.py](../plugins/bot_unified_runtime/output/card_render/theme_tokens.py) | `review_capability_result`、`render_reviewed_output`、`ThemeTokens`/`get_platform_theme`、`PlaywrightRenderBackend` | v21r2 W13；G-0 批1/5 | [tests/test_rendering_contract.py](../tests/test_rendering_contract.py)、[tests/test_mica_builders_contract.py](../tests/test_mica_builders_contract.py)、[tests/verify_hashes.py](../tests/verify_hashes.py) |
| `media` | 识图/视频理解/转写/搜图/媒体归档/TTS 语音出站 | [domains/media/](../plugins/bot_unified_runtime/domains/media/)（21 py） | 10 张：[capabilities/tts.py](../plugins/bot_unified_runtime/capabilities/tts.py)、[sources/vision_describe.py](../plugins/bot_unified_runtime/sources/vision_describe.py) | `is_tts_command`、`TtsParams`、`voice_enricher`、`sauce_search` | v21r2 W11；G-0 批1/5 | [tests/test_tts_contract_layer.py](../tests/test_tts_contract_layer.py)、[tests/test_media_contract_v2.py](../tests/test_media_contract_v2.py) |
| `transport` | 出站通道：发送队列、出站门、OneBot/NoneBot 通道、文件网关、回执、超时、邮件 | [domains/transport/](../plugins/bot_unified_runtime/domains/transport/)（15 py） | 9 张：[sender/queue.py](../plugins/bot_unified_runtime/sender/queue.py)、[sender/worker.py](../plugins/bot_unified_runtime/sender/worker.py)、[mail_adapter.py](../plugins/bot_unified_runtime/mail_adapter.py) | `SendQueue`、`OutboundGate`、`submit_active_push`、`drain_send_queue_once`、`UnifiedDeliveryGateway` | v21r2 W14（热区独占窗口） | [tests/test_outbound_gate.py](../tests/test_outbound_gate.py)、[tests/test_unified_gateways.py](../tests/test_unified_gateways.py) |
| `link_parse` | 社交媒体链接解析：37+ 平台适配器 + SSRF 护栏 + cookie + URL 清洗 | [domains/link_parse/](../plugins/bot_unified_runtime/domains/link_parse/)（47 py） | 11 张：[sources/parsers/ssrf_guard.py](../plugins/bot_unified_runtime/sources/parsers/ssrf_guard.py)、[sources/registry.py](../plugins/bot_unified_runtime/sources/registry.py)（`sources/parsers/` 下 git 仍跟踪 37 件、其中 **31 件已从工作树删除**；28 个平台适配器真身在 [domains/link_parse/parsers/](../plugins/bot_unified_runtime/domains/link_parse/parsers/)） | `ParserRegistry`、`check_download_url`、`content_parser` | v21r2 W1a/W1b（首个机制验证波） | [tests/test_parser_contract_migration_v2.py](../tests/test_parser_contract_migration_v2.py) |
| `subscribe` | 订阅（B 站/YT/xhs/推特/微博）+ 快报 + 喜加一 + 历史上的今天 | [domains/subscribe/](../plugins/bot_unified_runtime/domains/subscribe/)（25 py） | 11 张：[capabilities/subscribe_v2.py](../plugins/bot_unified_runtime/capabilities/subscribe_v2.py)、[sources/subscriptions/social_v2.py](../plugins/bot_unified_runtime/sources/subscriptions/social_v2.py) | `SubscriptionScheduler`、`PlatformThrottle`、`subscription_store_v2` | v21r2 W8 | [tests/test_auditfix_subscriptions_capabilities.py](../tests/test_auditfix_subscriptions_capabilities.py) |
| `schedule` | 提醒督促、定时调度族（DAG/RRULE）、NTP 授时、自动发送解析 | [domains/schedule/](../plugins/bot_unified_runtime/domains/schedule/)（19 py） | 4 张：[character/reminders.py](../plugins/bot_unified_runtime/character/reminders.py)、[runtime/schedule_rrule.py](../plugins/bot_unified_runtime/runtime/schedule_rrule.py) | `schedule_service.ReschedulePreview`、`timesync`、`delivery` | v21r2 W10 | [tests/test_reminder.py](../tests/test_reminder.py) |
| `divination` | 八字/塔罗/金钱卦/抽签 + 多历法换算 | [domains/divination/](../plugins/bot_unified_runtime/domains/divination/)（21 py） | 1 张：[capabilities/divination.py](../plugins/bot_unified_runtime/capabilities/divination.py) | `divination_service.DrawRequest`/`DrawResult`、`ganzhi`、`multi_calendar` | v21r2 W5 | [tests/test_divination_service_v21.py](../tests/test_divination_service_v21.py)、[tests/test_multi_calendar.py](../tests/test_multi_calendar.py) |
| `finance` | 全球股指、个股、汇率、商品、债券、北向资金 + 交叉核验 | [domains/finance/](../plugins/bot_unified_runtime/domains/finance/)（13 py） | 4 张：[capabilities/market.py](../plugins/bot_unified_runtime/capabilities/market.py)、[sources/finance_chart.py](../plugins/bot_unified_runtime/sources/finance_chart.py) | `is_market_command`、`market_data`、`market_crosscheck` | v21r2 W7（契约 `contracts/finance.py` 留守 core） | [tests/test_finance_data.py](../tests/test_finance_data.py)、[tests/test_market_crosscheck_tencent_gbk.py](../tests/test_market_crosscheck_tencent_gbk.py) |
| `meme` | 表情包能力/收库/搜索 + 贴纸回应引擎 + 随机图 | [domains/meme/](../plugins/bot_unified_runtime/domains/meme/)（12 py） | 8 张：[runtime/reactions.py](../plugins/bot_unified_runtime/runtime/reactions.py)、[sources/reaction_store.py](../plugins/bot_unified_runtime/sources/reaction_store.py) | `reactions.engine`、`reaction_store`、`meme_library_listener` | v21r2 W6 | [tests/test_meme_domain_fixes.py](../tests/test_meme_domain_fixes.py) |
| `weather` | 天气 + 预警（NMC 主通道、Open-Meteo 兜底、区县码表） | [domains/weather/](../plugins/bot_unified_runtime/domains/weather/)（6 py + `assets/qx.json`） | 1 张：[capabilities/weather.py](../plugins/bot_unified_runtime/capabilities/weather.py) | `fetch_nmc_weather`、`search_city_code`、`open_meteo` | v21r2 W3（**随迁资产**，见 §1.3） | [tests/test_weather_alerts_b10.py](../tests/test_weather_alerts_b10.py) |
| `location` | 维基/萌娘百科查询（POI/地图为**结构性空白**，`poi/` 空占位） | [domains/location/](../plugins/bot_unified_runtime/domains/location/)（11 py） | 4 张：[capabilities/wiki.py](../plugins/bot_unified_runtime/capabilities/wiki.py)、[character/kb_wiki.py](../plugins/bot_unified_runtime/character/kb_wiki.py) | `build_wiki_capability`、`mediawiki`、`kb_wiki` | v21r2 W16（与 ops/core 同批） | [tests/test_kb_topic_name_contract.py](../tests/test_kb_topic_name_contract.py) |
| `assistant` | 日常助理（收件箱/早晚报/到点吃什么）+ 校园群自动转发 | [domains/assistant/](../plugins/bot_unified_runtime/domains/assistant/)（9 py） | 4 张：[capabilities/campus.py](../plugins/bot_unified_runtime/capabilities/campus.py)、[sources/campus_store.py](../plugins/bot_unified_runtime/sources/campus_store.py) | `build_campus_source`、`build_campus_forward_text`、`build_daily_assist_capability` | v21r2 W12 | [tests/test_campus_digest.py](../tests/test_campus_digest.py)、[tests/test_daily_assist.py](../tests/test_daily_assist.py) |
| `notes` | Markdown 笔记 CRUD + 自然语言勾选 | [domains/notes/](../plugins/bot_unified_runtime/domains/notes/)（5 py） | 2 张：[capabilities/notes.py](../plugins/bot_unified_runtime/capabilities/notes.py)、[character/notes_store.py](../plugins/bot_unified_runtime/character/notes_store.py) | `NotesStore`、`build_notes_store`、`detect_note_kind` | v21r2 W9 | [tests/test_notes_item_checkoff.py](../tests/test_notes_item_checkoff.py) |
| `files` | 文件进出站：下载器、文件交换、群文件 | [domains/files/](../plugins/bot_unified_runtime/domains/files/)（9 py） | 5 张：[capabilities/download.py](../plugins/bot_unified_runtime/capabilities/download.py)、[sources/downloader.py](../plugins/bot_unified_runtime/sources/downloader.py) | `build_download_capability`、`extract_download_url`、`file_reader` | v21r2 W9 | [tests/test_file_gateway_phase1.py](../tests/test_file_gateway_phase1.py) |
| `music` | 点歌（5 供应商 + 真实榜单 ×5 + 候选卡） | [domains/music/](../plugins/bot_unified_runtime/domains/music/)（7 py） | 2 张：[capabilities/music.py](../plugins/bot_unified_runtime/capabilities/music.py)、[sources/music_request_store.py](../plugins/bot_unified_runtime/sources/music_request_store.py) | `is_music_command`、`music_charts`、`parse_music_mode_spec` | v21r2 W2（`song_candidates.html` 归 render） | [tests/test_music_charts_real_sources_v2.py](../tests/test_music_charts_real_sources_v2.py) |
| `food` | 今天吃什么（菜谱推荐 + 图库防污染） | [domains/food/](../plugins/bot_unified_runtime/domains/food/)（5 py） | 1 张：[capabilities/eat.py](../plugins/bot_unified_runtime/capabilities/eat.py) | `fuzzy_dish_hits`、`food_data` | v21r2 W4 | [tests/test_eat_image_quality.py](../tests/test_eat_image_quality.py) |
| `creation` | **预留态**（第 20 域）：绘图/TTS 生成能力的注册面 DTO，零实现零 I/O | [domains/creation/](../plugins/bot_unified_runtime/domains/creation/)（8 py，全 contracts） | 无（新域，旧路径不存在） | `CreationCapabilityRegistry`、`UnregisteredCapabilityError`、`manifest_registration_blockers` | v21r2 §9.1 预留（W-PA2）；TTS 真身仍在 media 域 | [tests/test_v21_creation_skeleton.py](../tests/test_v21_creation_skeleton.py) |
| `emergency_info` | **新域**：外部紧急信息聚合内核（定级/去重/审核门/存储 + GDACS·NMC·开放数据源） | [domains/emergency_info/](../plugins/bot_unified_runtime/domains/emergency_info/)（12 py） | 无（新域） | `grading.grade`、`dedupe`、`review`、`sources/store` | 2026-09-20 E-WAVE B1R3 席 | [tests/test_emergency_info_core.py](../tests/test_emergency_info_core.py)、[tests/test_emergency_info_sources.py](../tests/test_emergency_info_sources.py) |

**装配现状（重要，别误读）**：`creation` 与 `emergency_info` 两域**零生产接线**——
`grep -rn 'emergency_info' plugins/ | grep -v 'domains/emergency_info/'` 实跑命中 **0**，
即除自身包与两个测试文件外全仓无消费者；该域 `__init__.py` 自述「不新增配置键、不注册路由、不出卡」。
`domains/creation/` 同理，是「注册表开放条目 + 新功能四步接入」的注册面骨架。
**不要把「代码在树上」读成「生产在跑」。**

### 1.2 旧路径（非 domains/）到底还剩什么

复跑：`find plugins/bot_unified_runtime -name '*.py' -not -path '*/domains/*' | wc -l` → **211**

| 类别 | 数量 | 说明 |
|---|---|---|
| PEP 562 / `import *` 兼容垫片 | **158** | 文件头一律带 `Compat shim:` 字样；`grep -rl 'Compat shim' plugins/bot_unified_runtime --include='*.py' \| grep -v /domains/ \| wc -l` |
| `control_plane/` **真身** | 39 | **整包未迁**，仍住旧路径；domains/core 下没有 control_plane 对应物（[v21r2-reorg-plan.md](design/v21r2-reorg-plan.md) §2.1 #18 记它「按在飞批缓迁」） |
| 其他留守真身 | 8 | [runtime/service_wiring.py](../plugins/bot_unified_runtime/runtime/service_wiring.py)、[runtime/database_broker.py](../plugins/bot_unified_runtime/runtime/database_broker.py)、[runtime/loop_watchdog.py](../plugins/bot_unified_runtime/runtime/loop_watchdog.py)、[runtime/capability_protocols.py](../plugins/bot_unified_runtime/runtime/capability_protocols.py)、[sources/acg_search.py](../plugins/bot_unified_runtime/sources/acg_search.py)、[sources/search_intent.py](../plugins/bot_unified_runtime/sources/search_intent.py)，外加根 [\_\_init\_\_.py](../plugins/bot_unified_runtime/__init__.py) 与 [config.py](../plugins/bot_unified_runtime/config.py)（裁定留守） |
| 非垫片包壳 | 6 | `capabilities/`、`character/`、`runtime/`、`sources/`、`output/`、`output/card_render/` 六个目录的 `__init__.py` 仍是普通包声明（不是 re-export 壳） |

158 + 39 + 8 + 6 = **211**，与上面的 `find` 实跑数自洽。

**git 侧的坑（排查必看）**：`git ls-files 'plugins/bot_unified_runtime/*' | grep -v '/domains/'` = **275**，
其中 **112 个路径已从工作树删除但 index 里还在**（退役波尚未 commit，共享树常态）。
判「某旧路径是否真的还在」请用 `test -f <路径>` 而不是 `git ls-files`。

### 1.3 域内随包资产（清理波不许删）

- [domains/weather/assets/qx.json](../plugins/bot_unified_runtime/domains/weather/assets/qx.json) —— NMC 2527 区县码表，
  `.gitignore` 有否定规则保护；历史上被误清三次，每次清掉 NMC 路径整体塌向 Open-Meteo。
- [domains/render/card_render/templates/](../plugins/bot_unified_runtime/domains/render/card_render/templates/) 7 张 Jinja/HTML 模板
  （affinity/error/finance/market/mermaid/song_candidates/universal）+ `usage_cards.py` 直拼卡。
- [domains/divination/data/](../plugins/bot_unified_runtime/domains/divination/data/)、[domains/finance/data/](../plugins/bot_unified_runtime/domains/finance/data/) 内置数据表。
- 全量核对：`find plugins/bot_unified_runtime/domains -type f ! -name '*.py'` → 10 件（render 7 + weather 1 + schedule 1 + 其余另计）。

---

## 2. 五条链路跳转表

> 每格 = 「节点 → 真身文件:符号（带行号）」。行号是取证时点的锚，函数名才是长期有效的坐标；
> 找不到行号就用 `grep -n 'def <符号>' <文件>`。

### 2.1 入站主链路（一条 QQ 消息走完全程）

| # | 节点 | 落点 |
|---|---|---|
| 1 | 协议端接入 | SnowLuma forward-WS `127.0.0.1:3001`（学校号第二实例 3002），NoneBot 侧装配在 [bot.py](../bot.py) |
| 2 | 事件摄取（段归一/引用链反查/语音预转码/TG file_id→字节） | [plugins/bot_unified_runtime/\_\_init\_\_.py](../plugins/bot_unified_runtime/__init__.py) → [domains/chat_reply/runtime/ingress.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/ingress.py) `IngressGateway:8` / `from_event:14`（入口调用点 `__init__.py:2543`） |
| 3 | 路由判定（matcher 族 → `RouteKind`） | [domains/chat_reply/runtime/base_router.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py) `RouteKind:103`（34 成员）、`classify_message_route:706`（入口调用点 `__init__.py:833`、`:6853`）；能力声明 [runtime/capability_registry.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py) `ROUTE_CAPABILITY_DECLARATIONS:97` |
| 4 | 影子决策（默认不接管） | [domains/core/decision/](../plugins/bot_unified_runtime/domains/core/decision/) `shadow.py`/`engine.py`；开关 `bot_decision_engine_mode`（[config.py:290](../plugins/bot_unified_runtime/config.py)，缺省 `legacy_only`） |
| 5 | 门禁（黑白名单/安静时间/限流/主动搭话好感门） | [domains/chat_reply/policy/gate.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/gate.py) `evaluate_policy:215`；同目录 [quiet_hours.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/quiet_hours.py) `QuietHoursChecker:66`、[rate_limit.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/rate_limit.py) `InMemoryRateLimiter:220`/`SQLiteRateLimiter:638`、[roles.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/roles.py)；幂等 [runtime/event_idempotency.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/event_idempotency.py) |
| 6 | 管线（线程池 offload） | [domains/chat_reply/runtime/pipeline.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py) `RuntimePipeline:366`、`handle:1113`/`handle_async:1144`（装配点 `__init__.py:3757`） |
| 7 | 能力实现（返回 `CapabilityResult`） | 各域 `capabilities/`：[chat](../plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py) / [echo](../plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py) / [weather](../plugins/bot_unified_runtime/domains/weather/capabilities/weather.py) / [market](../plugins/bot_unified_runtime/domains/finance/capabilities/market.py) …（协议基类 [runtime/capability_protocols.py](../plugins/bot_unified_runtime/runtime/capability_protocols.py)，**真身仍在旧路径**） |
| 8 | 出站复审（人格漂移/不安全输出） | [domains/render/reviewer.py](../plugins/bot_unified_runtime/domains/render/reviewer.py) `review_capability_result:156` |
| 9 | 文本规整（说人话/数值与密钥打码/分段换行） | [domains/render/plain_text.py](../plugins/bot_unified_runtime/domains/render/plain_text.py) `naturalize_chat_text:203`、`redact_local_secrets:340`；角色扮演分段 [roleplay.py](../plugins/bot_unified_runtime/domains/render/roleplay.py) |
| 10 | 出卡 / 合并转发 / 分块 | [domains/render/renderer.py](../plugins/bot_unified_runtime/domains/render/renderer.py) `render_reviewed_output:287`（内部经 §2.3 渲染链） |
| 11 | 发送队列落库 | [domains/transport/sender/queue.py](../plugins/bot_unified_runtime/domains/transport/sender/queue.py) `SendQueue:167`、`submit:418`、part 幂等键 `_part_key:104`（入口调用点 `__init__.py:2954/3065/3223/3372`） |
| 12 | 队列排空 → 通道实发 | [sender/worker.py](../plugins/bot_unified_runtime/domains/transport/sender/worker.py) `drain_send_queue_once:209`（`__init__.py:1661`）→ [onebot.py](../plugins/bot_unified_runtime/domains/transport/sender/onebot.py) / [nonebot.py](../plugins/bot_unified_runtime/domains/transport/sender/nonebot.py) / [mail](../plugins/bot_unified_runtime/domains/transport/mail/) |

被动 matcher 族（不经门禁、直接挂在入口包）也全在 [\_\_init\_\_.py](../plugins/bot_unified_runtime/__init__.py)：
`auto_send:4802`、`mail_notice:4810`、`chat:4811`、`meme:4824`、`natural:4825`、`meme_library:4833`、
`campus_record_matcher:5027`、`file_export:5521`、`image_search:5619`、`cookie_admin:5698`；
notice 族 `_handle_poke_notice:5279`、`_handle_msg_emoji_like_notice:5360`、`_handle_group_increase:5395`。
**要加新 matcher，改这里；要改业务逻辑，改域内真身。**

### 2.2 LLM 子链路

| # | 节点 | 落点 |
|---|---|---|
| 1 | 模型路由（优先组/EWMA/影子并发/升档/链级 fail-fast） | [domains/chat_reply/llm_engine/model_router.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/model_router.py) `ModelRouter:944`、`generate:1876`、`build_model_router:2387`、`parse_priority_groups:263`、`resolve_active_priority_group:325`、上下文钳制 `_enforce_context_caps:142` |
| 2 | 内容感知路由（亲密档，决定切哪个模型） | [domains/chat_reply/runtime/content_route.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py) `ContentRouteEngine:207`、`explicit_allowed_for_session:501`、`resolve_intimate_context:553`、`build_router_cb:604`、成员键 `member_session_key:174` |
| 3 | 渠道注册表与调度（谁是首选） | [llm_engine/channel_health.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/channel_health.py)、[model_schedule.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/model_schedule.py)、[pricing.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/pricing.py)；注册表装载 `build_model_registry:876` |
| 4 | HTTP 出口（OpenAI 兼容 POST，connect 5s / read 30s） | [llm_engine/providers.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/providers.py) `LLMProviderError:17`、`should_failover:51`、`LLMProvider:110` |
| 5 | 计费账本（默认关，失败不阻塞） | [llm_engine/ledger.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/ledger.py) `ledger_enabled:70`、`build_call_draft:189`、`LedgerService:310`、`aggregate_channel_usage:693`；价目灌入 [scripts/import_model_prices.py](../scripts/import_model_prices.py) |
| 6 | 人格上下文注入（13 分区，喂给上面的 messages） | [domains/chat_reply/character/providers.py](../plugins/bot_unified_runtime/domains/chat_reply/character/providers.py)；好感/心情/称谓/怪癖同目录 [affinity.py](../plugins/bot_unified_runtime/domains/chat_reply/character/affinity.py) / [mood.py](../plugins/bot_unified_runtime/domains/chat_reply/character/mood.py) / [addressing.py](../plugins/bot_unified_runtime/domains/chat_reply/character/addressing.py) / [quirks.py](../plugins/bot_unified_runtime/domains/chat_reply/character/quirks.py) |
| 7 | 失败面（五池话术轮换 / 群聊温和降级） | [chat_reply/capabilities/chat.py](../plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py) 内失败池 + [domains/chat_reply/runtime/deadline.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/deadline.py)；预算键 `bot_chat_failover_max_seconds` |

### 2.3 渲染链路

| # | 节点 | 落点 |
|---|---|---|
| 1 | 设计 token 单一事实源（本命色/17 平台主题/阴影族/半径/宽度登记表/间距刻度） | [domains/render/card_render/theme_tokens.py](../plugins/bot_unified_runtime/domains/render/card_render/theme_tokens.py) `ThemeTokens`、`get_platform_theme`、`theme_to_css_vars` |
| 2 | 投影与装配（payload → HTML 上下文，含模板选择） | [card_render/bridge.py](../plugins/bot_unified_runtime/domains/render/card_render/bridge.py) `parse_to_render_payload:875`、`stable_payload_digest:1223`、`render_universal_card_html:1345` 等 6 个 `render_*_card_html`；云母壳 [mica_shell.py](../plugins/bot_unified_runtime/domains/render/card_render/mica_shell.py)；f-string 直拼卡 [usage_cards.py](../plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py) |
| 3 | 模板真身（7 张） | [card_render/templates/](../plugins/bot_unified_runtime/domains/render/card_render/templates/)：universal / market / finance / affinity / error / mermaid / song_candidates |
| 4 | 截图后端（playwright 常驻浏览器，`.card` 元素截图；mermaid CDN 本地拦截） | [domains/render/render_backends.py](../plugins/bot_unified_runtime/domains/render/render_backends.py) `RenderBackend:352`、`NullRenderBackend:360`、`HtmlKitRenderBackend:368`、`PlaywrightRenderBackend:407`、`render_card:576`、mermaid 资产 `resolve_mermaid_asset_path`；资产下载 [scripts/fetch_mermaid_js.py](../scripts/fetch_mermaid_js.py) |
| 5 | 契约（改模板前必读，测试会拦） | [docs/rendering-contract.md](rendering-contract.md) + 机器门 [tests/test_rendering_contract.py](../tests/test_rendering_contract.py)、[tests/test_mica_builders_contract.py](../tests/test_mica_builders_contract.py)、视觉族 [tests/test_v21r3_visual_gates.py](../tests/test_v21r3_visual_gates.py) |
| 6 | 兜底 | 渲染失败 → 纯文本，零契约破坏（出口在 §2.1 第 10 格） |

### 2.4 出站链路（含主动推送）

| # | 节点 | 落点 |
|---|---|---|
| 1 | 统一投递网关（FileSource→Ticket→通道 deliver） | [domains/transport/sender/gateway.py](../plugins/bot_unified_runtime/domains/transport/sender/gateway.py) `UnifiedDeliveryGateway:11`；文件网关 [file_gateway.py](../plugins/bot_unified_runtime/domains/transport/sender/file_gateway.py) |
| 2 | 出站门（主动推送的白名单/安静时间/去重三重闸） | [sender/outbound_gate.py](../plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py) `OutboundGate:296`、`submit_active_push:639`、`dedupe_key_shape_ok:259`、`build_outbound_gate:748`；门禁声明面 [core/decision/outbound_registry.py](../plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py) `TransportEntry`/`UnregisteredTransportError` |
| 3 | 队列与 part 级幂等（UNKNOWN 确认、PARTIAL 断点续发） | [sender/queue.py](../plugins/bot_unified_runtime/domains/transport/sender/queue.py) `SendQueue:167`、`InMemorySendQueue`、`_part_key:104`；超时 [sender/timeout.py](../plugins/bot_unified_runtime/domains/transport/sender/timeout.py) |
| 4 | 实发通道 | [onebot.py](../plugins/bot_unified_runtime/domains/transport/sender/onebot.py)（`set_outbound_verify_provider:59`、retcode 解析 `_extract_onebot_retcode:134`）/ [nonebot.py](../plugins/bot_unified_runtime/domains/transport/sender/nonebot.py) / [mail/mail_bridge.py](../plugins/bot_unified_runtime/domains/transport/mail/mail_bridge.py) |
| 5 | 回执核验与「结果未知」台账 | [sender/receipts.py](../plugins/bot_unified_runtime/domains/transport/sender/receipts.py) `ReceiptRepository`/`SQLiteReceiptRepository`；[domains/ops/monitor/result_unknown.py](../plugins/bot_unified_runtime/domains/ops/monitor/result_unknown.py) + [alerts.py](../plugins/bot_unified_runtime/domains/ops/monitor/alerts.py)（300s 抑制）+ [disconnect_notice.py](../plugins/bot_unified_runtime/domains/ops/monitor/disconnect_notice.py) |
| 6 | 各域主动投递口（都走 2/3，不许直连 send） | 群摘要 [chat_reply/character/shared_group.py](../plugins/bot_unified_runtime/domains/chat_reply/character/shared_group.py)、订阅 [subscribe/store/subscription_scheduler.py](../plugins/bot_unified_runtime/domains/subscribe/store/subscription_scheduler.py)、提醒投递 [schedule/delivery.py](../plugins/bot_unified_runtime/domains/schedule/delivery.py)、助理 [assistant/daily/](../plugins/bot_unified_runtime/domains/assistant/daily/)、校园转发 [assistant/campus/campus.py](../plugins/bot_unified_runtime/domains/assistant/campus/campus.py) |

### 2.5 控制面链路（**两套并行，别混**）

| 面 | 落点 | 说明 |
|---|---|---|
| 运维 HTTP 服务（默认关） | [control_plane/](../plugins/bot_unified_runtime/control_plane/) —— **整包未迁进 domains/**；入口 [control_plane/\_\_init\_\_.py](../plugins/bot_unified_runtime/control_plane/__init__.py)（`_DEFAULT_PORT = 8742`，仅 loopback，误绑 `0.0.0.0` 直接拒启动见 [_app.py:816](../plugins/bot_unified_runtime/control_plane/_app.py)）；鉴权 [auth.py](../plugins/bot_unified_runtime/control_plane/auth.py) `BearerAuthenticator:61`；端点面 [api/v1.py](../plugins/bot_unified_runtime/control_plane/api/v1.py) `/api/v1` | 401 抛出点在 [_app.py:145](../plugins/bot_unified_runtime/control_plane/_app.py) 与 `:176`（"缺少或无效的 Bearer 凭据"） |
| V2.1 合同事件存储 | [domains/ops/monitor/event_store.py](../plugins/bot_unified_runtime/domains/ops/monitor/event_store.py) `EventStore:473`（`append:518`、`query:605`）、`RuntimeEventV21:302`、`CursorExpired:380`；订阅分发 [event_service.py](../plugins/bot_unified_runtime/domains/ops/monitor/event_service.py) `EventBroker:136`/`EventService:177`/`create_event_stream_app:490`（SSE） | 这是**合同事实面**（V2.1 验收矩阵口径） |
| 控制面自用事件面 | [control_plane/events.py](../plugins/bot_unified_runtime/control_plane/events.py) `RuntimeEventService:229`（`append:278`/`query:320`）、`RuntimeEventBus:382`，另有**同名** `EventStoreUnavailable:224`；采集器 [log_collectors.py](../plugins/bot_unified_runtime/control_plane/log_collectors.py) | `/api/v1/events` 走的是**这一套**（[api/events.py:21](../plugins/bot_unified_runtime/control_plane/api/events.py) `from ..events import …`），**不是** ops 的 `EventStore` |
| WebUI | [api/webui.py](../plugins/bot_unified_runtime/control_plane/api/webui.py) + [api/webui_ext.py](../plugins/bot_unified_runtime/control_plane/api/webui_ext.py) + [webui_stats.py](../plugins/bot_unified_runtime/control_plane/webui_stats.py) / [webui_plugins.py](../plugins/bot_unified_runtime/control_plane/webui_plugins.py) / [webui_memory_graph.py](../plugins/bot_unified_runtime/control_plane/webui_memory_graph.py) / [webui_knowledge.py](../plugins/bot_unified_runtime/control_plane/webui_knowledge.py)；离线夹具 [scripts/webui_mock_server.py](../scripts/webui_mock_server.py)、验收 [scripts/webui_acceptance.py](../scripts/webui_acceptance.py) | 版式宪法门见 [tests/test_webui_http.py](../tests/test_webui_http.py) 与 §4 |

**读这张表的意义**：日志里出现 `EventStoreUnavailable` 时，先分清是 `control_plane/events.py:224` 还是
`domains/ops/monitor/event_store.py:388` 抛的——两条链的存储、游标、SSE 各自独立，修错地方等于没修。

---

## 3. 按症状查文件（反查索引）

> 命令约定：均在仓库根目录执行。全量门禁一律走
> `powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"`；
> 表里的 `pytest <文件>` 是**单域快查**，直跑必须带卫生旗（本仓铁律）：
> `PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest <文件> -p no:cacheprovider --basetemp="$TEMP/pt-<席号>"`
> 下表为简洁只写 `pytest <文件>`。**别用 `git ls-files` 判断文件在不在**（index 里有 112 个已删未 commit 的旧路径）。

| # | 症状（用户/日志可见现象） | 首查（文件:符号） | 一条可复跑验证命令 | 若正常，下一步查哪 |
|---|---|---|---|---|
| S01 | 消息完全不回（bot 在线但零输出） | [chat_reply/policy/gate.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/gate.py) `evaluate_policy:215` | `pytest tests/test_policy_quiet_hours.py` | [quiet_hours.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/quiet_hours.py) `QuietHoursChecker:66` → [roles.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/roles.py) 黑白名单 → 最后看 matcher 是否注册在 [\_\_init\_\_.py](../plugins/bot_unified_runtime/__init__.py) |
| S02 | 只在群里不回、私聊正常（点名门） | [runtime/mentions.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/mentions.py) + [policy/rate_limit.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/rate_limit.py) `distress_exemption:177` | `pytest tests/test_white2_strict_mention.py tests/test_policy_soft_mention_gate.py` | `bot_group_*` 名单类配置（[docs/config-catalog-full.md](config-catalog-full.md) 查键）→ §2.1 第 5 格 |
| S03 | 回复很慢 / 最后落一句降级话术 | [llm_engine/model_router.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/model_router.py) `ModelRouter:944`、链级 fail-fast 常量 | `pytest tests/test_model_router_failover.py tests/test_llm_failfast.py` | 告警里的 `[kind,chain=N,last=轨迹]` → [providers.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/providers.py) `should_failover:51` → 渠道生死簿 [channel_health.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/channel_health.py) |
| S04 | 回复超时到 300s 才出 | `bot_chat_failover_max_seconds`（[config.py](../plugins/bot_unified_runtime/config.py)）+ [runtime/deadline.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/deadline.py) | `grep -n 'failover_max_seconds' plugins/bot_unified_runtime/config.py` | 网关侧（本机 AxonHub）不是 bot 侧；先看 §S03 的 trace |
| S05 | 卡片不出、只发纯文本 | [render/render_backends.py](../plugins/bot_unified_runtime/domains/render/render_backends.py) `PlaywrightRenderBackend:407`/`NullRenderBackend:360` | `pytest tests/test_render_card_samples.py` | 是"有意兜底"还是"后端挂了"→ 看 `BOT_RENDER_*` 与告警；再查 §S06 |
| S06 | 卡片样式错乱 / 颜色阴影不合规 | [card_render/theme_tokens.py](../plugins/bot_unified_runtime/domains/render/card_render/theme_tokens.py)（唯一 token 来源）+ [bridge.py](../plugins/bot_unified_runtime/domains/render/card_render/bridge.py) `parse_to_render_payload:875` | `pytest tests/test_rendering_contract.py tests/test_mica_builders_contract.py` | 模板 DOM → [card_render/templates/](../plugins/bot_unified_runtime/domains/render/card_render/templates/)；契约条文 [docs/rendering-contract.md](rendering-contract.md) |
| S07 | 卡片截图字节不稳定（样张对比假红/真红分不清） | [bridge.py](../plugins/bot_unified_runtime/domains/render/card_render/bridge.py) `stable_payload_digest:1223`、`digest_phase:1234` | `python tests/verify_hashes.py --check` | 动画钉帧与 `reduced-motion` → [tests/test_v21r3_visual_gates.py](../tests/test_v21r3_visual_gates.py) |
| S08 | 同一条消息发两遍 / 重启后重复投递 | [transport/sender/queue.py](../plugins/bot_unified_runtime/domains/transport/sender/queue.py) `_part_key:104`、`SendQueue:167` | `pytest tests/test_part_idempotent_resume.py tests/test_auditfix_sender_queue.py` | 幂等层 [runtime/event_idempotency.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/event_idempotency.py) → 出站门去重键 [outbound_gate.py](../plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py) `dedupe_key_shape_ok:259` |
| S09 | 主动推送（早报/提醒/订阅）重复或不发 | [outbound_gate.py](../plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py) `OutboundGate:296`、`submit_active_push:639` | `pytest tests/test_outbound_gate.py tests/test_outbound_v21.py` | 声明面缺条目 → [core/decision/outbound_registry.py](../plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py) `UnregisteredTransportError` |
| S10 | 安静时间不生效（深夜还在说话） | [policy/quiet_hours.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/quiet_hours.py) `build_quiet_hours_settings:154` | `pytest tests/test_v21r2_hotzone_quiet_silence.py tests/test_policy_quiet_hours.py` | 时区口径：cron 用系统本地时区（台账 #6）+ NTP 钟 [schedule/timesync/timesync.py](../plugins/bot_unified_runtime/domains/schedule/timesync/timesync.py) |
| S11 | 限流误拦（正常说话被判频繁） | [policy/rate_limit.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/rate_limit.py) `InMemoryRateLimiter:220` / `SQLiteRateLimiter:638` | `pytest tests/test_group_rate_limit.py tests/test_sqlite_rate_limit_group.py tests/test_policy_sender_interval.py` | SQLite 路径**不支持热改**（台账 #3）→ 改完必须重启；再查 `distress_exemption:177` |
| S12 | 同一人 @ 一下就被回、或怎么 @ 都不回 | [policy/rate_limit.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/rate_limit.py) 点名最小间隔 + [runtime/mentions.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/mentions.py) | `pytest tests/test_policy_sender_interval.py` | 角色门 [roles.py](../plugins/bot_unified_runtime/domains/chat_reply/policy/roles.py)（超管可越过限流，这是设计） |
| S13 | `data/` 出现在源码树（脏树门红） | [scripts/runtime_paths.py](../scripts/runtime_paths.py)（唯一重映射口） | `pytest tests/test_datafix_runtime_paths.py` | `dev.ps1 -Task runtime-layout`（→ [scripts/runtime_layout_smoke.py](../scripts/runtime_layout_smoke.py)）；**先备份 `%TEMP%` 再清**，别直接删 |
| S14 | 语音「说了但没收到」/ TTS 谎报送达 | [media/capabilities/tts.py](../plugins/bot_unified_runtime/domains/media/capabilities/tts.py) `is_tts_command:208`、退避闸 | `pytest tests/test_tts_failure_visibility.py tests/test_tts_health_backoff.py` | 出站契约 [tests/test_voice_outbound_contract.py](../tests/test_voice_outbound_contract.py) → 「结果未知」台账 [ops/monitor/result_unknown.py](../plugins/bot_unified_runtime/domains/ops/monitor/result_unknown.py) `ResultUnknownLedger:48` |
| S15 | 语音音色突然变了 / 同句不同声 | [media/tts_presets.py](../plugins/bot_unified_runtime/domains/media/tts_presets.py) + 缓存身份（api_url 归一 + ref sha 指纹） | `pytest tests/test_tts_cache_identity.py tests/test_tts_identity_watch.py` | 基线册 [scripts/tts_voice_baseline.json](../scripts/tts_voice_baseline.json) → `python scripts/pre_restart_check.py`（第 10 项音色守望） |
| S16 | 天气预警整段消失 | [weather/data/nmc_weather.py](../plugins/bot_unified_runtime/domains/weather/data/nmc_weather.py) `fetch_nmc_weather:113`、`search_city_code:33` | `pytest tests/test_weather_alerts_b10.py tests/test_weather_nmc_retry_nmcflix.py` | **码表资产是否又被删**：`test -f plugins/bot_unified_runtime/domains/weather/assets/qx.json && echo OK`（见 §1.3）→ 兜底源 [open_meteo.py](../plugins/bot_unified_runtime/domains/weather/data/open_meteo.py) |
| S17 | 天气把「东京」定位到江苏小镇 | [weather/capabilities/weather.py](../plugins/bot_unified_runtime/domains/weather/capabilities/weather.py) 变体链与别名表 | `pytest tests/test_weather_statement_guard.py` | geocoding 排序（人口/精确名）→ 同文件别名表 |
| S18 | 订阅不推 / 推得慢 / 平台被限流 | [subscribe/store/subscription_scheduler.py](../plugins/bot_unified_runtime/domains/subscribe/store/subscription_scheduler.py) `SubscriptionScheduler`、`PlatformThrottle` | `pytest tests/test_subscribe_capability_v2.py tests/test_subscribe_platform_switch_j02.py` | 存储离环 → [subscription_store_v2.py](../plugins/bot_unified_runtime/domains/subscribe/store/subscription_store_v2.py)；适配器实况 → [adapters/](../plugins/bot_unified_runtime/domains/subscribe/adapters/) |
| S19 | 校园群消息不转发到主人 | [assistant/campus/campus.py](../plugins/bot_unified_runtime/domains/assistant/campus/campus.py) `build_campus_source`、`matches_campus_source`（三重来源门） | `pytest tests/test_campus_digest.py` | 装配点在 [\_\_init\_\_.py:5027](../plugins/bot_unified_runtime/__init__.py)（门任一空=整链不装配）→ 去重库 [campus_store.py](../plugins/bot_unified_runtime/domains/assistant/campus/campus_store.py) → 第二 WS 实例是否在跑 |
| S20 | 群摘要 21:30 推了个空的 | [chat_reply/character/shared_group.py](../plugins/bot_unified_runtime/domains/chat_reply/character/shared_group.py)（`session_id` 口径） | `pytest tests/test_group_digest_push.py tests/test_shared_group_digest_list.py` | 已知存量缺陷（台账 #33 调研项）：查询键 `group:<群号>` vs 库存 `group_<群号>_<发送者>`；LLM 侧 `build_shared_group_context_provider` 未传 provider |
| S21 | 提醒时间不对（13 点报 23 点、跨天错位） | [schedule/store/reminders.py](../plugins/bot_unified_runtime/domains/schedule/store/reminders.py) + 解析器 [schedule/capabilities/reminder.py](../plugins/bot_unified_runtime/domains/schedule/capabilities/reminder.py) | `pytest tests/test_reminder.py tests/test_v21r2_reminder_guards.py` | 授时 [timesync.py](../plugins/bot_unified_runtime/domains/schedule/timesync/timesync.py)（UDP 123 被防火墙拦会回退系统钟，属预期）→ 投递 [delivery.py](../plugins/bot_unified_runtime/domains/schedule/delivery.py) |
| S22 | 「X 做完了」勾错 / 勾不上 | [notes/store/notes_store.py](../plugins/bot_unified_runtime/domains/notes/store/notes_store.py) `detect_note_kind`、`NotesStore` | `pytest tests/test_notes_item_checkoff.py tests/test_notes.py` | 并列候选话术 → [notes/capabilities/notes.py](../plugins/bot_unified_runtime/domains/notes/capabilities/notes.py) |
| S23 | 控制面 401 / 拒绝启动 | [control_plane/auth.py](../plugins/bot_unified_runtime/control_plane/auth.py) `BearerAuthenticator:61`；抛出点 [_app.py:145](../plugins/bot_unified_runtime/control_plane/_app.py)（"缺少或无效的 Bearer 凭据"） | `pytest tests/test_control_plane_host_guard.py tests/test_control_plane_m1.py` | 端口/绑定 → `bot_control_plane_port`（[config.py:94](../plugins/bot_unified_runtime/config.py)，缺省 8742）；误绑 `0.0.0.0` 在 [_app.py:816](../plugins/bot_unified_runtime/control_plane/_app.py) 直接拒启 |
| S24 | 事件/SSE 报错但不知道是哪套事件面 | 同名 `EventStoreUnavailable` 两处：[ops/monitor/event_store.py:388](../plugins/bot_unified_runtime/domains/ops/monitor/event_store.py) vs [control_plane/events.py:224](../plugins/bot_unified_runtime/control_plane/events.py) | `grep -rn 'class EventStoreUnavailable' plugins/bot_unified_runtime` | 看 traceback 的文件名定归属；SSE 服务面 [event_service.py](../plugins/bot_unified_runtime/domains/ops/monitor/event_service.py) `create_event_stream_app:490` |
| S25 | `/bot help` 少了某个命令 / 深度页参数不对 | [chat_reply/capabilities/echo.py](../plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py) `_HELP_ENTRIES:451`、`_HELP_ENTRY_META:2460` | `python scripts/command_catalog.py --check` | 一致性门 → `pytest tests/test_help_entries_coverage.py tests/test_e2e_help_matrix.py tests/test_bot_commands_catalog_b10.py` |
| S26 | 命令触发不了 / 一触发就抢别人的话 | [chat_reply/runtime/base_router.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py) `build_route_rules`、`looks_like_command_text:667`；中央边界字符集 [core/text_boundary.py](../plugins/bot_unified_runtime/domains/core/text_boundary.py) `is_trigger` | `pytest tests/test_trigger_bidirectional_gate.py tests/test_trigger_spec.py` | 劫持探针 [scripts/probe_trigger_hijack.py](../scripts/probe_trigger_hijack.py)；拼音/繁体族 `tests/test_pinyin_triggers*.py`、`tests/test_traditional_triggers*.py` |
| S27 | 生成物漂移（文档/事实册/哈希门红） | 三个生成物：[scripts/command_catalog.py](../scripts/command_catalog.py)、[scripts/doc_sync.py](../scripts/doc_sync.py)、[tests/verify_hashes.py](../tests/verify_hashes.py) | `python scripts/doc_sync.py --check; python tests/verify_hashes.py --check` | 判定"是不是我改的"：`git diff --name-only` 对照；确认是自己的改动才 `--write` 重录，**别人的在飞改动别顺手重录**（见 §4.2） |
| S28 | 亲密/内容路由不切模型（或乱切） | [chat_reply/runtime/content_route.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py) `ContentRouteEngine:207`、`match_manual_command:155`、成员键 `member_session_key:174` | `pytest tests/test_content_route.py tests/test_content_route_v3.py` | 硬拦截面 [security/content_safety.py](../plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py) → 探针 [scripts/probe_intimate_route.py](../scripts/probe_intimate_route.py) |
| S29 | 好感度不动 / 掉了不回 / 说明里出现固定加减分 | [chat_reply/character/affinity.py](../plugins/bot_unified_runtime/domains/chat_reply/character/affinity.py) | `pytest tests/test_affinity.py tests/test_affinity_numerical.py tests/test_affinity_v6_smoothing.py` | 被动观测入口在 [\_\_init\_\_.py](../plugins/bot_unified_runtime/__init__.py)（注意 `session_type` 必传，群消息别按私聊口径评估）→ 数值规范 [docs/affinity-design.md](affinity-design.md) |
| S30 | 表情不贴 / 贴太多 / 私聊也贴（不该贴） | [meme/reactions/engine.py](../plugins/bot_unified_runtime/domains/meme/reactions/engine.py) `maybe_react_on_message` 五层门 | `pytest tests/test_reactions.py tests/test_reaction_store.py` | 群会话键判定 `_is_group_session` → 双写库 [reaction_store.py](../plugins/bot_unified_runtime/domains/meme/sources/reaction_store.py) |
| S31 | 链接发出去不解析 / 某平台突然全挂 | [link_parse/support/registry.py](../plugins/bot_unified_runtime/domains/link_parse/support/registry.py) `ParserRegistry` + 对应 `parsers/platforms_<平台>.py` | `pytest tests/test_parser_contract_migration_v2.py tests/test_auditfix_parsers.py` | 抓取层 [fetchers/playwright_backend.py](../plugins/bot_unified_runtime/domains/link_parse/fetchers/playwright_backend.py) → cookie [parsers/cookies.py](../plugins/bot_unified_runtime/domains/link_parse/parsers/cookies.py) → SSRF 护栏 [parsers/ssrf_guard.py](../plugins/bot_unified_runtime/domains/link_parse/parsers/ssrf_guard.py) |
| S32 | 下载/取图被拒但 URL 明明没问题 | [link_parse/parsers/ssrf_guard.py](../plugins/bot_unified_runtime/domains/link_parse/parsers/ssrf_guard.py) `check_download_url` | `pytest tests/test_file_gateway_phase1.py tests/test_auditfix_wave3_resources.py` | 落点侧限额 → [files/sources/downloader.py](../plugins/bot_unified_runtime/domains/files/sources/downloader.py)、[media/archive/media_archive.py](../plugins/bot_unified_runtime/domains/media/archive/media_archive.py) |
| S33 | 媒体归档没落盘 / 类别判错 | [media/capabilities/media_archive.py](../plugins/bot_unified_runtime/domains/media/capabilities/media_archive.py) + 判类 [ingest/vision_describe.py](../plugins/bot_unified_runtime/domains/media/ingest/vision_describe.py) | `pytest tests/test_media_archive.py tests/test_media_contract_v2.py` | 权限门 `BOT_MEDIA_ARCHIVE_MIN_ROLE`（缺省 super_admin）→ 限额与目录名消毒 |
| S34 | TG 吞消息 / TG 适配器把进程搞崩 | [transport/mail/](../plugins/bot_unified_runtime/domains/transport/mail/) 之外，TG 韧性在 [scripts/telegram_resilience.py](../scripts/telegram_resilience.py)（poll 阶段 catch_all） | `pytest tests/test_telegram_resilience.py tests/test_telegram_media.py` | 摄取侧 file_id→字节 [media/ingest/telegram_media.py](../plugins/bot_unified_runtime/domains/media/ingest/telegram_media.py) |
| S35 | 邮件通知/日报不发 | [transport/mail/mail_bridge.py](../plugins/bot_unified_runtime/domains/transport/mail/mail_bridge.py) + [mail_adapter.py](../plugins/bot_unified_runtime/domains/transport/mail/mail_adapter.py) | `pytest tests/test_mail_bridge.py tests/test_mail_adapter_resilience.py` | 连通性探针 [scripts/mail_connectivity_smoke.py](../scripts/mail_connectivity_smoke.py) |
| S36 | 能力抛异常但只看到一句冷冰冰失败 | [ops/monitor/error_report.py](../plugins/bot_unified_runtime/domains/ops/monitor/error_report.py) `build_error_report`、`ErrorCardGate` | `pytest tests/test_error_card_contract.py` | 两段式补发时序在 [runtime/pipeline.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py) `_internal_error` 旁路；冷却降级话术见 §S37 |
| S37 | 告警刷屏 / 该告的没告 | [ops/monitor/alerts.py](../plugins/bot_unified_runtime/domains/ops/monitor/alerts.py)（300s 抑制） | `pytest tests/test_operational_failures.py tests/test_startup_queue_warning.py` | 日志采集面 [log_collectors.py](../plugins/bot_unified_runtime/control_plane/log_collectors.py) + 协议端尾巴 [ops/collectors/snowluma_tail.py](../plugins/bot_unified_runtime/domains/ops/collectors/snowluma_tail.py) |
| S38 | 改了代码但线上行为没变 | 不是 bug，是铁律：**必须重启**。生效前自检：`python scripts/pre_restart_check.py` | 见左 | 重启步骤与提权口径在仓库外导航件 `../代码地图/排查手册.md`；改了垫片路径的 monkeypatch 也会「看着改了其实没改」→ §1.2 |
| S39 | 配置改了不生效（或启动就崩） | [config.py](../plugins/bot_unified_runtime/config.py)（633 个 bot_* 字段，缺省与校验器）+ [core/config/config_readiness.py](../plugins/bot_unified_runtime/domains/core/config/config_readiness.py) | `pytest tests/test_config_json_validators.py tests/test_doc_sync_gates.py` 或 `powershell ... dev.ps1 -Task config-smoke` | 键名/可改性对照 [docs/config-catalog-full.md](config-catalog-full.md)；装配期快照类（调度器族）不支持热改，见台账 #3 |
| S40 | 账单是 0 元 / 「未计价」 | [llm_engine/ledger.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/ledger.py) `ledger_enabled:70`、`build_call_draft:189` + [pricing.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/pricing.py) | `pytest tests/test_llm_ledger.py tests/test_ledger_channel_breakdown.py` | 价目灌入 [scripts/import_model_prices.py](../scripts/import_model_prices.py)（幂等）；`BOT_LLM_BILLING_ENABLED` 缺省关 |

---

## 4. 门禁与生成物速查

### 4.1 四个常驻门（`scripts/dev.ps1`）

统一入口 [scripts/dev.ps1](../scripts/dev.ps1)（918 行，任务分派在 `:875` 的 `switch`）。全部命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout"
```

| 任务 | 实跑什么 | 源码位置 | 关键点 |
|---|---|---|---|
| `test` | `python -X faulthandler -m pytest -p no:cacheprovider --basetemp=<Runtime>/cache/pytest_ci_<pid>/basetemp` | [dev.ps1:234](../scripts/dev.ps1) `Invoke-Test` | TMP/TEMP/PYTEST_DEBUG_TEMPROOT 三件全重定向到仓库外（源码树零缓存铁律）；`BOT_AUTOSYNC` **仅在你没显式设置时**默认 1（`:246`）——显式 `0` = 禁自动重录，验收模式必用 |
| `lint` | `ruff check --cache-dir <Runtime>/cache/ruff .` | [dev.ps1:330](../scripts/dev.ps1) `Invoke-Lint` | 全树扫，不只扫改动面；缓存落在 Runtime 不落在源码树 |
| `typecheck` | `python -m mypy`（缓存同样外置） | [dev.ps1:347](../scripts/dev.ps1) `Invoke-Typecheck` | 刻意用 `python -m mypy` 而非 `mypy.exe`，避开 venv 搬家后的陈旧启动器元数据 |
| `runtime-layout` | `python scripts/runtime_layout_smoke.py` | [dev.ps1:499](../scripts/dev.ps1) `Invoke-RuntimeLayout` | 源码树/运行数据边界体检：冒出 `data/`、`__pycache__`、`.pytest_cache` 等就在这里红 |

**一条命令跑全套**：`-Task verify`（[dev.ps1:746](../scripts/dev.ps1) `Invoke-Verify` = docs-check → plugin-check → test → lint → typecheck）。
另有 20 个 `*-smoke` 子任务（路由/队列/传输/人格/凭据/知识库…），全清单直接读 `switch` 块（`:875-918`）；
**没有顶层 `health` 任务**，健康信息在 `/bot status` 里。

绕开 `dev.ps1` 直跑 Python 时的卫生纪律（本仓铁律 6）：
`PYTHONDONTWRITEBYTECODE=1` + `pytest -p no:cacheprovider --basetemp="$TEMP/<席号>"`。

### 4.2 三个生成物（**永远不要手改生成物**）

| 生成物 | 真身（可改） | 生成物（只读，改它=自找冲突） | 校验 / 重录 |
|---|---|---|---|
| 命令目录 | [domains/chat_reply/capabilities/echo.py](../plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py) `_HELP_ENTRIES:451` + `_HELP_ENTRY_META:2460`、路由 manifest `build_interface_manifest`、动词映射 [runtime/aliases.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/aliases.py) | [docs/command-catalog.md](command-catalog.md) | `python scripts/command_catalog.py --check`（无参数即校验；过期返回 1）／`--write` 重录 |
| 机器事实册 | [config.py](../plugins/bot_unified_runtime/config.py) 字段、模板目录、`_HELP_ENTRIES`、路由矩阵来源 [base_router.py](../plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py) | [docs/auto-facts.md](auto-facts.md)（**计数唯一权威**，别在散文里抄数字） | `python scripts/doc_sync.py --check`／`--write` |
| 交付物哈希册 | 19 个受锚文件（7 张卡片模板 + 主题/桥接/直拼卡等），名单在 [tests/verify_hashes.py](../tests/verify_hashes.py) `TRACKED_FILES:34` | [tests/render_hashes.json](../tests/render_hashes.json) | `python tests/verify_hashes.py --check`（缺省即 `--check`）／`--write` |

**三条常驻 pytest 门**把上面三件事钉在全量套件里：
[tests/test_doc_sync_gates.py](../tests/test_doc_sync_gates.py)（事实册 + config-catalog 覆盖）、
[tests/test_verify_hashes_coverage.py](../tests/test_verify_hashes_coverage.py)（锚定名单本身）、
[tests/test_cross_validation_gates.py](../tests/test_cross_validation_gates.py)（subprocess 跑 `--check`，
外加 [tests/cross_validate.py](../tests/cross_validate.py) 双引擎互证与 [tests/test_perf_regression.py](../tests/test_perf_regression.py) 性能量级门）。

**共享树特别提醒**：多会话并发改树时，`--check` 变红**未必是你造成的**。
先 `git diff --name-only` 对照自己的改动面，只有确认是自己的改动才 `--write`；
顺手重录会把别人的在飞改动洗成基线（本仓出过真实事故，见 [AGENTS.md](../AGENTS.md) 台账 #42 的「终验四件残余」段）。

### 4.3 三条静态门禁红绿现状（MAP-2 席 2026-09-20 实跑，HEAD `5ddf704`，`BOT_AUTOSYNC=0`）

> 只跑只读三件（未跑全量 `test`：他席在飞不可归因）。红只记归属，一律未修。

| 门 | 结果 | 摘要 | 归属 |
|---|---|---|---|
| `lint`（ruff） | **RED** `Found 9 errors`（8 fixable） | `chat_reply/character/providers.py:780`、`chat_reply/pipeline/backend_unit.py:3`、`chat_reply/policy/quiet_hours.py:1`、`chat_reply/policy/rate_limit.py:1`、`chat_reply/security/injection.py:1`、`render/card_render/mica_shell.py:22`、`render/card_render/theme_tokens.py:528`、`tests/test_kb_topic_name_contract.py:98`、`tests/test_kb_wiki_retriever_wiring.py:28` | **全在他席在飞改动面**（v21r5 内容路由/渲染/位置 kb_wiki），本席可写面之外，未修 |
| `typecheck`（mypy） | **GREEN** `Success: no issues found in 636 source files` | 仅 `annotation-unchecked` note（未开 `--check-untyped-defs`），非错误 | — |
| `runtime-layout` | **GREEN** `PASS` | `source_generated_dirs=empty`、`python_bytecode=absent`、外部数据边界 OK | — |

复跑：`BOT_AUTOSYNC=0 powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint|typecheck|runtime-layout"`

---

## 5. 链接与坐标体检（MAP-2 席续跑，HEAD `5ddf704`，2026-09-20）

MAP-1 死在「链接存在性校验」那一步（其 §5 的 broken=0 是**计划**未实跑）。本席脚本化实跑补上，口径：
`docs/CODE-MAP.md` + 仓库外 `代码地图/{README,排查手册,分区速查}.md` 的**全部** markdown 链接与 `文件:行`/`符号:行` 坐标。

**结论**：
- **markdown 链接**：全量 417 处 / 去重 327 个落点，**断链 0 条**（含 `../plugins/...`、`file:///` 绝对、`design/` 相对、脚本与测试链接全部命中）。MAP-1 的链接层没问题。
- **坐标**：可归因到文件的坐标共检 130 处（符号型 106 + `文件名.ext:行` 型 24），**越界 0 处**、**符号型无「±10 行找不到」** 除下表 5 处行号漂移。
- `build_model_registry:876`（§2.2）核对为**正确**——真身在 [model_router.py](../plugins/bot_unified_runtime/domains/chat_reply/llm_engine/model_router.py):876（该行号准确；只是行分组措辞把它摆在 channel_health/model_schedule/pricing 那条下，无断链，不改）。

### 5.1 待复核（代码真的动了 → 按简报「登记不改图」，附实测 def 行与时刻）

> 判据：`git log 21b702c..HEAD` + `git status --porcelain` 实跑。两文件均属他席改动面，本席**未动地图行号**
> （§2 表头已声明「函数名才是长期坐标，找不到行号就 `grep -n 'def <符号>'`」，此处给实测锚点即可）。

| 地图坐标 | 现真身 def 行 | 归属判定 | 证据 |
|---|---|---|---|
| [renderer.py](../plugins/bot_unified_runtime/domains/render/renderer.py) `render_reviewed_output:287` | **315** | 代码已 commit 漂移 | `git log 21b702c..HEAD -- renderer.py` → `d823232`（Wave H TTS 摘要层） |
| [outbound_gate.py](../plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py) `OutboundGate:296` | **313** | 代码在飞（工作树脏，未 commit） | `git status` → ` M outbound_gate.py` |
| 同上 `submit_active_push:639` | **656** | 同上 | 同上 |
| 同上 `dedupe_key_shape_ok:259` | **270** | 同上 | 同上 |
| 同上 `build_outbound_gate:748` | **765** | 同上 | 同上 |

**收工复核命令**：`grep -n -E 'class OutboundGate|def submit_active_push|def dedupe_key_shape_ok|def build_outbound_gate' plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py`。
他席 commit 后，收尾波统一 `--write` 重录或改行号即可（非本席职责）。

---

## 6. 按域找测试（MAP-2 席 T2，覆盖 21 域；非 471 文件全映射）

> 复跑口径：`grep -rl -E 'domains\.<域>[\./]' tests/`（本表数=该正则命中的 `test_*.py` 数，2026-09-20 实测 466 个 test 文件）。
> 代表测试只给 2-3 个入口，全映射留后续席。**151 个测试文件不直接引用 `domains.<域>` 路径**（多走旧垫片 import，或为跨域 harness/生成物门），别按此表数当测试总数。

| 域 | 命中测试数 | 代表测试（入口） |
|---|---|---|
| `chat_reply` | 107 | [test_admin_roster_and_roles.py](../tests/test_admin_roster_and_roles.py)、[test_affinity_numerical.py](../tests/test_affinity_numerical.py)、[test_a18_gate_idempotency_rollback.py](../tests/test_a18_gate_idempotency_rollback.py) |
| `core` | 93 | [test_contracts_v21.py](../tests/test_contracts_v21.py)、[test_audit_fixes_b.py](../tests/test_audit_fixes_b.py)、[test_auditfix_parsers.py](../tests/test_auditfix_parsers.py) |
| `ops` | 54 | [test_a03_timeout_retry_semantics.py](../tests/test_a03_timeout_retry_semantics.py)、[test_error_card_contract.py](../tests/test_error_card_contract.py)、[test_runtime_feature_gate.py](../tests/test_runtime_feature_gate.py) |
| `media` | 35 | [test_asr_transcribe.py](../tests/test_asr_transcribe.py)、[test_media_archive.py](../tests/test_media_archive.py)、[test_bgroup_chat_pipeline.py](../tests/test_bgroup_chat_pipeline.py) |
| `render` | 31 | [test_rendering_contract.py](../tests/test_rendering_contract.py)、[test_mica_builders_contract.py](../tests/test_mica_builders_contract.py)、[test_bot_avatar.py](../tests/test_bot_avatar.py) |
| `subscribe` | 27 | [test_auditfix_subscriptions_capabilities.py](../tests/test_auditfix_subscriptions_capabilities.py)、[test_music_subscription_netease_v2.py](../tests/test_music_subscription_netease_v2.py)、[test_epic_card.py](../tests/test_epic_card.py) |
| `link_parse` | 24 | [test_auditfix_parsers.py](../tests/test_auditfix_parsers.py)、[test_content_parser_quota_throttle.py](../tests/test_content_parser_quota_throttle.py)、[test_cookie_import_hot_reload.py](../tests/test_cookie_import_hot_reload.py) |
| `transport` | 24 | [test_outbound_gate.py](../tests/test_outbound_gate.py)、[test_bgroup_sender_delivery.py](../tests/test_bgroup_sender_delivery.py)、[test_delivery_verification_tier1.py](../tests/test_delivery_verification_tier1.py) |
| `schedule` | 17 | [test_reminder.py](../tests/test_reminder.py)、[test_reminder_delivery.py](../tests/test_reminder_delivery.py)、[test_copy_redline_gate.py](../tests/test_copy_redline_gate.py) |
| `finance` | 16 | [test_finance_data.py](../tests/test_finance_data.py)、[test_bond_data.py](../tests/test_bond_data.py)、[test_commodities_data.py](../tests/test_commodities_data.py) |
| `meme` | 12 | [test_meme_domain_fixes.py](../tests/test_meme_domain_fixes.py)、[test_randpic_identity.py](../tests/test_randpic_identity.py)、[test_randpic_scan_cache_l10.py](../tests/test_randpic_scan_cache_l10.py) |
| `location` | 10 | [test_kb_topic_name_contract.py](../tests/test_kb_topic_name_contract.py)、[test_kb_wiki_metadata_sync.py](../tests/test_kb_wiki_metadata_sync.py)、[test_kb_wiki_retriever_wiring.py](../tests/test_kb_wiki_retriever_wiring.py) |
| `assistant` | 3 | [test_campus_digest.py](../tests/test_campus_digest.py)、[test_daily_assist.py](../tests/test_daily_assist.py)、[test_v21r2_hotzone_meal_variants.py](../tests/test_v21r2_hotzone_meal_variants.py) |
| `files` | 6 | [test_ssrf_throat_coverage.py](../tests/test_ssrf_throat_coverage.py)、[test_user_copy_pool.py](../tests/test_user_copy_pool.py)、[test_runtime_subfeatures.py](../tests/test_runtime_subfeatures.py) |
| `divination` | 7 | [test_divination.py](../tests/test_divination.py)、[test_divination_service_v21.py](../tests/test_divination_service_v21.py)、[test_multi_calendar.py](../tests/test_multi_calendar.py) |
| `weather` | 6 | [test_weather_alerts_b10.py](../tests/test_weather_alerts_b10.py)、[test_weather_card.py](../tests/test_weather_card.py) |
| `music` | 5 | [test_music_backend_v2.py](../tests/test_music_backend_v2.py)、[test_music_charts_real_sources_v2.py](../tests/test_music_charts_real_sources_v2.py)、[test_music_charts_v2.py](../tests/test_music_charts_v2.py) |
| `emergency_info` | 3 | [test_emergency_info_core.py](../tests/test_emergency_info_core.py)、[test_emergency_info_sources.py](../tests/test_emergency_info_sources.py) |
| `food` | 3 | [test_eat_image_quality.py](../tests/test_eat_image_quality.py)、[test_prfix_eat.py](../tests/test_prfix_eat.py) |
| `notes` | 2 | [test_notes.py](../tests/test_notes.py)、[test_notes_item_checkoff.py](../tests/test_notes_item_checkoff.py) |
| `creation` | 1 | [test_v21_creation_skeleton.py](../tests/test_v21_creation_skeleton.py) |




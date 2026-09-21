# V21R2 存量业务行为对照全表·草案（LEGb 席，2026-09-18）

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](../snowluma-setup.md)。

> **合同依据**：验收矩阵行 **V21-LEGACY-001@L67**（存量业务逐个对照，不能只测天气代表全插件，矩阵 L98 点名）+ §覆盖维护条款；重组正交性声明见 `v21r2-reorg-plan.md` §8.3 G10/G12。
> **性质**：草案（LEGb 席只读盘点产物）。零代码改动、零测试套件实跑（纪律禁令）；全部 rg/ls/import 探针级取证。
> **产出四件**：①存量业务全量清单（19 域逐域）；②行为对照表框架（逐业务模板+real/pending 填法）；③Plugin manifests 骨架（19 域）；④缺口清单。

## 〇、口径、真值源与方法

### 0.1 真值源（全部只读，禁编造）

| 源 | 用途 | 本席核验 |
|---|---|---|
| `docs/design/v21r2-reorg-plan.md` §2 | 19 域定义 + 329 文件全映射 | 通读；§2.3 逐表合计=329 与 §1.1 实测一致（RO 席实跑） |
| `docs/design/v21r2-command-spec-inventory.md` §A.1/A.2 | **77 个帮助主题**逐条坐标（echo.py 行号/权限/路由/别名） | 通读；A.0 总量核对：77 topics / 501 别名 / 37 公开+40 admin / 33 路由规则 |
| `docs/command-catalog.md` | 机器生成目录（真值口径） | 头部实读：模块数 77 / 别名数 501 / 普通 37+admin 40 / 路由规则 33（内部能力 5）；生成源已指 `domains/chat_reply/capabilities/echo.py` |
| `plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py` | RouteKind 枚举 + build_route_rules | 实测：RouteKind **34 值**（ALIAS…IGNORE）；catalog 口径 33 规则=32 注册行+IGNORE 兜底 |
| 各波日志（`v21r2-reorg-w*.md`/`wc*.md`/`woc`/`w13b`/`wpa1`） | 迁移状态+回归实跑证据 | 逐波实读（证据见 §1 总览表） |
| `v21r2-COORDINATION.md` / `v21r2-matrix-backfill-draft.md` | 席位交付与矩阵回填口径 | 通读 |

### 0.2 三源交叉对齐方法（禁漏项）

1. **77 topics**（command-spec-inventory A.1=42 admin 族 + A.2=35 子功能族）逐一分配到唯一主承域 → §1 各域表；分配完做 77/77 封账（§四）。
2. **路由 manifest**：33 路由规则 + RouteKind 34 值 + 2 条 reserved 接口（capability.game_live / capability.gscore，base_router L615/L621 未实现）全部落域。
3. **capabilities 文件**：reorg-plan §2.3 的 43 个 capability 文件逐一对号（真身现位=domains/，旧位=垫片）。
4. **非命令可感业务**：根 `__init__.py` 9 个 `_register_*_scheduler` 工厂 + 7 处 on_notice + 被动监听（meme 收库/校园转发/订阅轮询）逐条落域。

### 0.3 状态词汇（禁美化）

- `real(波X)`：该业务载体已迁 `domains/`，且该波日志有实跑回归数字（**只证明组织迁移零行为改动+域回归绿**，不构成行为验收）。
- `待迁`：真身仍在旧路径（本草案实读核验：`policy/`+`security/` 真身在旧位=380/108 行非垫片；`control_plane/` 真身在旧位）。
- `pending-live`：行为对照的触发/输出/边界/降级列只有源码盘点值，真机实测未做（bot 未重启，矩阵 L67 行级 live=unknown）。

---

## 一、存量业务全量清单（19 域）

### 1.0 域总览与迁移状态（逐波证据）

| # | 域 | 真身目录（domains/） | 迁移状态 | 波次/回归实跑证据（波日志） | 分配 topics |
|---|---|---|---|---|---|
| 1 | chat_reply 消息回复 | `chat_reply/{capabilities,character,llm_engine,runtime,ingest,pipeline}` | **大部已迁**；例外：`policy/+security/`（15c）**未迁**；`memory_service/memory_store_v21/knowledge_service/teaching_service` 留守旧位（RWC1 SKIP 登记，待 S8 收官波） | W15a(RWC1)：域关键词 755+消费方 289；W15b(RWC2)：46 文件 739；W15d(RWC4)：批A-C 3186；W15e(RWC3)：63 文件 1241 | 27 |
| 2 | meme 表情包 | `meme/{capabilities,sources,reactions}` | 已迁 | W6：域关键词 439+显式 16 文件 413 | 4 |
| 3 | link_parse 链接解析 | `link_parse/{parsers,capabilities,support,fetchers}` | 已迁 | W1a：广域 698+受影响 225；W1b(W8 序)：定向 316+广域 1204 | 2 |
| 4 | music 点歌 | `music/{capabilities,data}` | 已迁 | W2：432 passed | 1 |
| 5 | location 查询地点 | `location/{capabilities,knowledge,data,poi(空白),extensions}` | 已迁 | W16 序(RW16)：显式 12 文件 436+关键词 288 | 2 |
| 6 | weather 查询天气 | `weather/{capabilities,data,assets}` | 已迁（qx.json 随迁 sha=e8285e77…完好） | W3：域测试 259+关键词 139 | 1 |
| 7 | food 查询菜谱 | `food/{capabilities,data}` | 已迁 | W4：域 8 文件 214 | 1 |
| 8 | finance 金融 | `finance/{capabilities,data}` | 已迁 | W7：域 23 文件 780+宽域 857 | 6 |
| 9 | divination 占卜 | `divination/{capabilities,data,store,service,api,projection}` | 已迁（api/projection 为 S12 增量） | W5：13 文件 743/1 skipped；S12：27 passed | 1 |
| 10 | schedule 日程提醒 | `schedule/{capabilities,auto_send,store,service,timesync,data,extensions}` | 已迁 | W10：显式 17 文件 653；S11 增量：新测试 54+W10 面 574 | 2 |
| 11 | notes 笔记 | `notes/{capabilities,store}` | 已迁 | W9（与 files 合波）：16 文件 261 | 1 |
| 12 | subscribe 订阅资讯 | `subscribe/{capabilities,adapters,store,feeds}` | 已迁 | W8 序(RW12)：43 文件 629 | 4 |
| 13 | media 媒体处理 | `media/{capabilities,registry,archive,ingest,search,video}` | 已迁 | W11：显式 18 文件 275+关键词 424 | 4 |
| 14 | files 文件进出站 | `files/{capabilities,sources,artifacts(reserved)}` | 已迁 | W9：同上 261 面 | 3 |
| 15 | transport 出站通道 | `transport/{sender,mail,extensions}` | 已迁 | W14 序(RW15)：域关键词 281+消费方 233 | 3 |
| 16 | assistant 助理+校园 | `assistant/{daily,campus}` | 已迁 | W12 序(RW13)：域 4 文件 47+关键词 43+lifecycle 68 | 1 |
| 17 | ops 运维管理 | `ops/{admin,features,monitor,audit,smoke,integrations,recovery,incident,collectors,repair,acceptance}` | 已迁 | W16(RWOC)：59 件移动+59 张垫片；批1 292/批2 348/批3 229 passed | 9 |
| 18 | core 系统内核 | `core/{config,contracts,credentials,decision,search,supervisor}` | **大部已迁**；例外：`control_plane/`（31 件）**未迁**（在飞批，真身仍在 `control_plane/`）；`sources/{search_intent,acg_search}`、`runtime/{capability_protocols,database_broker,loop_watchdog}` 未迁（woc-log §八.4） | W16(RWOC)：同上 | 4 |
| 19 | render 渲染出站 | `render/{根 7 件,card_render/4 件+templates/7 html}` | 已迁 | W13(W13b)：契约族 181 passed+终轮 867 | 1 |
| — | creation 生成域（预留第 20 域） | `creation/{tts,image,extensions,_common}` | **非存量业务**：W-PA1 骨架波（39 passed 协议形态测试），全 reserved，登记不展开 | wpa1 | 0 |

> 迁移总账（EP1 席机核）：275 张垫片 / 1591 消费边，波次归因 275/275 全命中；~200+ 件真身在 `domains/`（现 386 py，含各批次新增模块）。**重组≠沙箱迁移≠行为对照完成（G10）**——本草案即 L67「行为对照全表+Plugin manifests 仍无」缺口的填补草案。

### 1.1 域 chat_reply（消息回复；27 topics + 非命令业务）

> 载体根：`domains/chat_reply/`。迁移：W15a/15b/15d/15e 四子波已收（§1.0）；**policy/+security/ 真身未迁（15c 未执行）**，下表相关行标 `待迁`。

| 稳定 ID | 业务(topic#) | 载体（domains/ 真身路径） | 入口 | 关键行为/边界（源码与帮助注册表盘点） | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.chat_reply.chat | 人格对话(74) | `chat_reply/capabilities/chat.py` + `chat_reply/character/providers.py` | CHAT@50 兜底（不可显式调用）+@bot/白名单抽签/昵称点名 | 人设【标签】13 分区注入（空分区不渲染）；好感/心情/怪癖/称谓四层；反注入包裹+指令剥离；五池失败话术游标轮换；INTIMATE/normal 文风互斥注入 | test_bgroup_chat_pipeline、test_chat_and_sources_regressions、test_rp_style_directives | real(W15e 1241) |
| bot.plugin.chat_reply.affinity | 好感度(66) | `chat_reply/capabilities/affinity.py` + `chat_reply/character/affinity.py` | AFFINITY@41；`好感度`/`好感度 算法` | -100~+100 基准 10；v5 多因素线性步长 ×v6 平滑（饱和曲线/同日递减/日节奏帽）；8 档温和连续过渡；算法定性不显数值；红线场景写死 | test_affinity、test_affinity_numerical、test_affinity_v6_smoothing（R4 实跑 151） | real(RWC1/RWC3) |
| bot.plugin.chat_reply.memory | 记忆自助(3) | `chat_reply/capabilities/memory.py` | `/bot memory add/list/delete (--sensitivity=)` | 全员仅本人；敏感度分级 | test_memory_router_reuse | real(W15e) |
| bot.plugin.chat_reply.reflection | 夜间反思定时批 | `chat_reply/character/reflection.py` + 根 `_register_reflection_scheduler` | 定时（per-sender 归属） | 记忆反思回路自动投喂；提醒 LLM 抽取默认关 | test_reflection | real(RWC1 755) |
| bot.plugin.chat_reply.identity | 会话身份+称谓(30) | `chat_reply/character/session_identity.py` + `addressing.py` | `/bot identity show/set/tag/clear`＋自助 `set-name/set-gender/unset-*`（绕管理员门） | 管理员设昵称/标签防 OOC 护栏；AddressingContext：私聊漂泊者/群聊群友/超管 master 例外/性别 unknown 不推断；群聊"漂泊者"保留字回退 | test_addressing_context | real(RWC1) |
| bot.plugin.chat_reply.alias | 昵称别名(61) | `chat_reply/runtime/aliases.py` | ALIAS@10；`/bot 昵称 set` 管理员 | 触发别名注册 | test_affection_alias（rg 级） | real(RWC4) |
| bot.plugin.chat_reply.group_info | 群信息(65) | `chat_reply/capabilities/group_info.py` | GROUP_INFO@41（仅群聊） | 群主/人数/公告/精华；公告与精华仅管理员 | test_group_info | real(W15e) |
| bot.plugin.chat_reply.quirk | 人格怪癖(31) | `chat_reply/character/quirks.py` | `/bot quirk list/approve/retire/add` | 审核制演化 propose→approve→渲染；管理员门 | test_quirks、test_quirks_scope | real(RWC1) |
| bot.plugin.chat_reply.persona | 人格自检/版本化(15) | `chat_reply/character/persona_set.py` + `persona_service.py` + `persona_injection.py` | `/bot persona`（自检）；运行期切换走 `/bot runtime persona` | V1 版本生命周期 draft/publish/activate/rollback + CAS + quarantine；**注入切换默认 False 灰度（待重启，禁记 wired）** | test_persona_service_v21（19）、test_persona_injection_v21（14） | real(RWC1/WIRE) |
| bot.plugin.chat_reply.help | 帮助命令面(73) | `chat_reply/capabilities/echo.py`（77 topics 注册表 `_HELP_ENTRIES`，旧位 18 行垫片） | `/bot help [topic]`/`/bot commands`；帮助/菜单别名 | Mica 卡/深度页逐参数四要素/可见范围按角色；65→77 topics；触发词三语+拼音缩写（zb/bz/sz/sm 永不启用） | test_help_entries_coverage、test_help_meta_search_and_tra49_aliases、test_pinyin_triggers×3、test_traditional_help_aliases | real(RWC3，verify_hashes/catalog 同波重录) |
| bot.plugin.chat_reply.model | 模型管理(20) | `chat_reply/llm_engine/model_router.py` + `channel_health.py` | `/bot model list/set/add/update/priority/effort/think/price/search/usage/health/probe/routes/vision/remove/reset`；`/bot llm 诊断` | 严格优先级渠道序；90s 冷却 SQLite 降级；3s 链止损；INTIMATE grok 钉一；EWMA 影子；failover 总预算 | test_model_router_failover、test_model_router_channel_failover、test_channel_health_v2（R1 批 23+253） | real(W15b 739) |
| bot.plugin.chat_reply.usage | 用量账单(21) | `chat_reply/llm_engine/usage_service.py` + `billing_{service,entities,pricing}.py` | `/bot model usage [today\|日期]`、`/bot model price` | 家族归一化合并/渠道价计价/未计价诚实 None | test_usage_billing_v21、test_usage_card、test_billing_service_v21 | real(W15b) |
| bot.plugin.chat_reply.ledger | LLM 计费账本 | `chat_reply/llm_engine/ledger.py` | 生成出口 sink（默认关 `BOT_LLM_BILLING_ENABLED`） | 三表；失败不阻塞 | test_ledger_channel_breakdown、test_ledger_range_query | real(W15b) |
| bot.plugin.chat_reply.model_schedule | 模型分时段切换 | `chat_reply/llm_engine/model_schedule.py` + 根 `_register_model_schedule_scheduler` | 定时预设切换（配置型） | 分时段自动切换模型预设 | test_model_admin_and_schedule（rg 级） | real(W15b) |
| bot.plugin.chat_reply.providers_cfg | 模型供应商配置(39) | `chat_reply/llm_engine/`（BOT_MODEL_REGISTRY 注册表面）+ `scripts/probe_llm_providers.py`（域外工具） | 配置型 .env + probe 工具（admin） | 渠道注册表/探测；注册表运行时直改需备份（#36 渠道重排先例） | test_model_admin_and_schedule（rg 级） | real(W15b) |
| bot.plugin.chat_reply.route | 路由投影(16) | `chat_reply/runtime/base_router.py` | `/bot route <文本>`｜`/bot routes`（**全员只读**） | 33 规则稳定排序 (priority,声明序)；RouteKind 34 值 | test_capability_registry、test_help_meta_search_and_tra49_aliases | real(W15d 3186 面) |
| bot.plugin.chat_reply.settings | 配置/设置(12+22) | `chat_reply/runtime/settings.py`（`config.py` 529 字段留守根位） | `/bot config`；`/bot runtime set/get/list/reset/nickname/persona/instance` | SETTABLE 白名单面；热改部分即生效、调度器族装配期快照不生效（台账 #3） | test_settings_hot_audit（rg 级）、test_help_deep_teaching_n2re | real(W15d) |
| bot.plugin.chat_reply.reply_budget | 回复详略(19) | `policy/reply_budget.py`（**待迁 15c**） | `/bot reply [详细\|科普\|详尽\|精简\|简洁\|默认\|自动]` | 详略档控制输出长度 | （未检得专属测试文件） | 待迁 |
| bot.plugin.chat_reply.group_policy | 群策略门禁(26) | `policy/gate.py`（**待迁 15c**） | `/bot group list/add/del/set/clear`（档位 black1\|black2\|white1\|white2） | 黑白名单/安静时间/限流门禁链 | test_a18_gate_idempotency_rollback（引用面） | 待迁 |
| bot.plugin.chat_reply.rate_limit | 限流/安静时间(32) | `policy/rate_limit.py` + `quiet_hours.py`（**待迁 15c**） | 配置型：`/bot runtime set BOT_RATE_LIMIT_*/BOT_QUIET_HOURS_*` 等 11 键 | InMemory+SQLite 双轨（SQLite 路径不支持热改，台账 #3）；安静时间自发文案 BLOCKED 零入队（R5 锁） | test_group_rate_limit、test_rate_limit_silent_and_chat_forward、test_policy_quiet_hours | 待迁 |
| bot.plugin.chat_reply.roles | 角色权限(14) | `policy/roles.py`（**待迁 15c**） | `/bot roles` | user/trusted/enterprise/admin/super_admin/blocked 六级；超管自动叠加 admin | test_admin_roster_and_roles | 待迁 |
| bot.plugin.chat_reply.history | 历史清理(17) | `chat_reply/character/history.py` | `/bot history clear` | 线性对话清空 | test_bgroup_chat_pipeline（引用面） | real(RWC1) |
| bot.plugin.chat_reply.pause | 暂停/恢复(18) | `chat_reply/runtime/pipeline.py` | `/bot pause`｜`/bot resume`（暫停/恢复/继续/繼續） | 管线级暂停；重启失效 | test_pipeline_review_fixes | real(W15d) |
| bot.plugin.chat_reply.context_dialogue | 上下文试注入(9)+对话测试(10) | `chat_reply/pipeline/backend_unit.py` | `/bot context [文本]`｜`/bot dialogue [文本]`（admin） | 一次性执行单元试跑 | test_backend_unit | real(W15d) |
| bot.plugin.chat_reply.digest_push | 群摘要定时推送(34) | `chat_reply/character/shared_group.py` + 根 `_register_digest_push_scheduler` | 定时 21:30 白名单群；配置型 9 键 | dedupe 按日期；非白名单零推送。**已知存量缺陷（#33 台账）：摘要读零行（session_id 口径不符）+推送侧 LLM 未装配** | test_group_digest_push、test_shared_group_digest_list | real(RWC1) |
| bot.plugin.chat_reply.time_window | 时间窗总结 | `chat_reply/runtime/time_window.py` | 自然语言（@bot 总结 N 分钟内消息） | 会话级时间窗查询 | test_time_window_summary | real(W15d) |
| bot.plugin.chat_reply.parrot | 自动接话 | `chat_reply/runtime/parrot.py` | 被动概率接话 | 受限流/概率门 | test_parrot | real(W15d) |
| bot.plugin.chat_reply.natural_command | 自然语言命令(77) | `chat_reply/runtime/natural_language.py` | NATURAL_COMMAND@45 | 确定性层自然语言命令识别 | test_natural_settings_nl、test_moegirl_yield_fix（rg 级） | real(W15d) |
| bot.plugin.chat_reply.question_intent | 联网决策意图 | `chat_reply/runtime/question_intent.py` | 自然语言内部（可解释联网决策） | 意图判定可解释 | test_sdd9_n3re（rg 级） | real(W15d) |
| bot.plugin.chat_reply.mentions | 点名/抽签门 | `chat_reply/runtime/mentions.py` | 被动（@bot/白名单抽签） | R3 同人点名最小间隔 45s（InMemory+SQLite 同语义）；R4 长文软点名观察门 | test_policy_sender_interval、test_policy_soft_mention_gate（引用面） | real(W15d) |
| bot.plugin.chat_reply.poke | 戳一戳(75) | `chat_reply/capabilities/poke.py` | on_notice | 回戳缺省开/BOT_POKE_REPLY_MODE mix 三选一轮换/群聊 @ 戳者/好感小额正向（每日 5 分上限）；同键在途租约防环 | test_poke_notice_ingest、test_poke_unified_reaction_b10、test_poke_v2（dsp 152 面内 13 例）、r5 面 166 | real(RWC3/dsp) |
| bot.plugin.chat_reply.ignore | 忽略兜底+引导(40) | `chat_reply/capabilities/echo.py`（IGNORE@999） | 被动兜底 | 未知命令形态 60s/会话引导（build_ignore_guide_result） | test_capability_registry（引用面） | real(W15e) |
| bot.plugin.chat_reply.ingest | 消息摄取归一（基建） | `chat_reply/ingest/message_context.py` + 根摄取辅助 | 被动（所有入站消息） | 段归一/引用链递归反查 5 层/语音预转码/TG file_id→字节/sender_display_name | test_internal_marker_regex、test_message_context 族（引用面） | real(W15d) |

> 域内未单列的支撑件（非用户可感，manifests implementation_ref 引用）：`runtime/{cache_policy,group_cache,deadline,event_idempotency,prompt_audit,prompt_preview,content_route,capability_registry}`、`security/{injection,memory_sanitize,content_safety}`（**待迁 15c**，测试 test_prompt_injection/test_memory_sanitize/test_content_safety_v2）、`character/{memory_service,memory_store_v21,knowledge_service,teaching_service,mood,emotion,glossary,trend,temporal,relationship,documents,source_summary,shared_export,vector_knowledge}`、根 `message_context`。

### 1.2 域 meme（表情包；4 topics + 非命令业务）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.meme.meme | 表情生成(45) | `meme/capabilities/meme.py` | MEME@20；`表情`/`bqb` 等 15 别名 | 表情包生成（生成器 2233 端口 enabled）；点歌模式互斥 | test_meme_conflict_fix、test_meme_domain_fixes | real(W6 439+413) |
| bot.plugin.meme.meme_library | 偷表情(46) | `meme/capabilities/meme_library.py` + `meme/sources/meme_library.py` | MEME_LIBRARY@22；`偷表情`/`steal` 等 | 表情随机抽取（收库图源） | test_capability_registry（声明面）、test_meme_conflict_fix | real(W6) |
| bot.plugin.meme.meme_absorb | 表情收库(76) | `meme/sources/meme_library_listener.py` | 被动监听（群图收库，无命令） | NSFW 降权；mface/sticker 段扩收（v2） | test_meme_conflict_fix（引用面）、AST 终验 W6 日志 | real(W6) |
| bot.plugin.meme.randpic | 随机图(68) | `meme/capabilities/randpic.py` | RANDPIC@41；`随机图`/`来张图` | 只读 BOT_RANDPIC_DIRS；title 置空防兜底链文案；原图字节直发无重编码 | test_randpic_identity、test_randpic_scan_cache_l10 | real(W6) |
| bot.plugin.meme.reactions | 贴纸回应（非命令） | `meme/reactions/engine.py`（旧 `runtime/reactions.py`）+ `meme/sources/reaction_store.py` | on_notice（贴纸回应识别）+五层防刷门 | 会话环形缓冲→【表情回应】分区注入；主动贴 set_msg_emoji_like（开关/去重/概率/冷却/小时滑窗，缺省 True/0.2/30s/20）；双层表情第二层意图匹配发图；TG reaction 无触发键诚实降级 | test_reactions、test_reaction_store | real(W6) |

### 1.3 域 link_parse（社交媒体链接解析；2 topics + 主链）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.link_parse.parse_chain | 链接解析主链（被动） | `link_parse/parsers/`（28 个 platforms_*.py + 基建 9：http_util/ssrf_guard/cookies/wbi/image_stitch/context/types/platform_login）+ `fetchers/{playwright_backend,xhs_sign}` | 被动：发链接即解析；引用/语音/转发/TG 媒体全通 | 37+ 平台；cookie 18 平台已灌；SSRF 逐跳校验；image_stitch 长图拼接 | test_chat_and_sources_regressions、test_auditfix_parsers、test_parser_ssrf_guard、test_content_parser_quota_throttle | real(W1a 698/W1b 1204) |
| bot.plugin.link_parse.content | 链接命令(62) | `link_parse/capabilities/content_parser.py` | CONTENT@46；`链接`/`links` | 解析能力显式入口；配额/节流 | test_content_parser_quota_throttle | real(W1b) |
| bot.plugin.link_parse.parse_history | 解析历史查询(24) | `link_parse/support/parse_history.py` | `/bot parse [数量 1-100 默认10]`（admin） | 近期解析记录查询 | （未检得专属测试文件） | real(W1b) |
| bot.plugin.link_parse.cookies | cookie 凭据群（非命令） | `link_parse/parsers/cookies.py` | `/bot cookie status/import/login/check/expiry`（admin，载体 core 凭据面+本域文件） | 18 平台 cookie 灌入/到期检查 | test_auditfix_parsers、test_auditfix_wave3_resources | real(W1b) |

> 支撑件未单列：`support/url_cleaner.py`（URL 清洗）、`support/registry.py`（解析注册表，W1b 实读确认归域）——**无直接测试指针，入缺口清单**。

### 1.4 域 music（点歌；1 topic）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.music.music | 点歌(44) | `music/capabilities/music.py` + `music/data/{music_charts,music_request_store,music_normalization}.py` | MUSIC@41 + MUSIC_MODE@40；`点歌`/`dg`/`dgms` 等 | 5 供应商+候选卡（同名先问）；真实榜单×5（netease×2/QQ/酷狗×2）；点歌模式=admin；请求存储+归一化 | test_music_capability_analytics_v2、test_music_backend_v2、test_music_charts_real_sources_v2、test_music_analytics_v2 | real(W2 432) |

### 1.5 域 weather（查询天气；1 topic）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.weather.weather | 天气+预警(48) | `weather/capabilities/weather.py` + `weather/data/{nmc_weather,open_meteo}.py` + `weather/assets/qx.json`（2527 区县码表，sha=e8285e77…） | WEATHER@41；`天气`/`tq` 等 8 别名 | NMC 主通道 2 次重试+Open-Meteo 兜底+预警支路≤5 条；geocoding count=10 人口排序；60+ 中英城市别名；查询变体链逐级拆 | test_weather_card、test_weather_alerts_b10、test_weather_nmc_retry_nmcflix、test_auditfix_wave3_resources | real(W3 259+139) |

> 已知遗留：W3 Q03 锚未随真身同步（RW6 登记移交 W15d/尾声波）——入缺口清单。

### 1.6 域 food（查询菜谱；1 topic）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.food.eat | 吃什么/菜谱(64) | `food/capabilities/eat.py` + `food/data/food_data.py` | EAT@41；`吃什么`/`csm`/`cp` 等 10 别名 | 菜谱推荐+图片质检（分辨率/宽高比/来源落盘）；图库防污染域黑名单；「<事项>做完了」自然勾选不在此域（notes） | test_eat_capability、test_creator_dualname、test_prfix_eat、test_clean_food_gallery | real(W4 214) |

### 1.7 域 finance（金融；6 topics）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.finance.market | 行情(49) | `finance/capabilities/market.py` + `finance/data/{market_data,market_crosscheck}.py` | MARKET@41；`行情`/`hq`/`gs`/`dp` 等 16 别名 | 18 指数（东财 17+MOEX ISS）；30 日走势（MOEX 真折线）；腾讯源 6 指数交叉核验脚注；市场词过滤；东财 kline 必带 end 参数；空响应重试 | test_finance_market_expansion、test_market_backoff、test_finance_data | real(W7 780+857) |
| bot.plugin.finance.stocks | 个股行情(50) | `finance/capabilities/stocks.py` + `finance/data/stock_data.py` | STOCKS@42；`股价`/`gj`/`英伟达股价` 等 | 9 巨头 OHLCV/市值/KDJ/多日收益箱形图；f47/f48/f84/f85 成交与股本；非上市红线（OpenAI 等结构性无价格字段） | test_stocks_hijack_guard、test_stock_data | real(W7) |
| bot.plugin.finance.commodities | 商品行情(51) | `finance/capabilities/market.py` + `finance/data/commodities_data.py` | COMMODITIES@41；`黄金`/`oil` 等 24 别名 | COMEX 金/银/铜+NYMEX 原油 30 日折线；LME/Brent 无源诚实不接；商品触发股词让路 | test_commodities_data | real(W7) |
| bot.plugin.finance.bond | 国债收益率(52) | `finance/capabilities/market.py` + `finance/data/bond_data.py` | BOND@41；`国债`/`guozhai` 等 | 中/美国债 2/5/10/30 年+10Y−2Y 期限利差；1Y 无源不接 | test_bond_data | real(W7) |
| bot.plugin.finance.northbound | 北向资金(53) | `finance/capabilities/market.py` + `finance/data/market_data.py`（北向段） | NORTHBOUND@41；`北向资金`/`beixiang` 等 | 成交总额/笔数/领涨股口径；净买入 2024-08 起停止披露绝不编数 | test_northbound_data | real(W7) |
| bot.plugin.finance.fx | 汇率(54) | `finance/capabilities/fx.py` + `finance/data/fx_data.py` | FX@41；`汇率`/`换算` 等 18 别名 | 11 币种面板+定向换算；TWD/MOP/AED 无源诚实标注；面板/换算语义显式；出图文件名 digest 纳入查询语义 | test_fx_card_semantics、test_fx_data | real(W7) |

> 支撑件：`finance/data/finance_chart.py`（金融图表）；契约 `contracts/finance.py` 留 core 域（W7 裁定）。渲染走 finance_card sections/rows 契约。

### 1.8 域 divination（占卜命理；1 topic + REST）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.divination.divination | 占卜(55) | `divination/capabilities/divination.py` + `service/{divination_service,fortune,tarot_draw}.py` + `data/{ganzhi,tarot,iching,multi_calendar,draw_store}.py` + `store/character→divination/store/draw_store.py` | DIVINATION@41；`占卜`/`塔罗`/`pp`/`lssg` 等 60 别名 | 八字（Meeus 节气+藏干权重）/塔罗 78 无放回/金钱卦/求签/每日一签；同日幂等+频控；卡片 prune keep=120；渲染回退纯文本 | test_divination、test_divination_hijack_guard、test_divination_service_v21、test_multi_calendar、test_card_prune | real(W5 743；S12 27) |
| bot.plugin.divination.rest_api | 占卜控制面 REST（非命令） | `divination/api/{dto,errors,facet}` + `projection/` + control_plane 挂接（`_app.py:478-491`） | `/api/v1` 8 端点（admin Bearer） | 8 端点全 envelope/RBAC/错误码注册表；真装配 503 divination_unavailable 兜底；生产启用键 bot_control_plane_divination_db 未配未部署 | test_v21_s12_divination_api | real(S12) |

### 1.9 域 location（查询地点；2 topics + 定时同步）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.location.wiki | 维基(57) | `location/capabilities/wiki.py` + `location/data/mediawiki.py` | WIKI@41；`维基`/`wjbk` 等 | 维基摘要（机械标签废除+状态空省略）；标题全 urlencode | test_chat_and_sources_regressions、test_phase0_3_features | real(W16 序 436+288) |
| bot.plugin.location.moegirl | 萌娘百科(58) | `location/capabilities/moegirl.py` + `location/data/moegirl.py` | MOEGIRL@41 + MOEGIRL_QUESTION@46；`萌百`/`mb`/问句形态 | 二次元问句 priority=46（echo 帮助文本写 44 为已知漂移）；yield 修正 | test_moegirl_question_fix、test_moegirl_search | real(W16 序) |
| bot.plugin.location.kb_wiki_sync | KB 百科定时同步（非命令） | `location/knowledge/kb_wiki.py` + 根 `_register_kb_wiki_sync_scheduler` | 定时批 | 独立线程池同步（R3 停摆根修：互斥 busy 跳过/协作取消/零变更夜跳过 ANN 重建/锁外预热+流式 fetchmany） | test_kb_wiki_sync、test_v21r2_stall_kbsync | real(W16 序；R3 批) |

> 结构性空白：`location/poi/`（POI/地图/导航）预留——用户点名 8 域中唯一空白，CMD 席 E-35 同口径登记，不虚构模块。

### 1.10 域 schedule（日程与提醒；2 topics + 执行面）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.schedule.reminder | 提醒(69) | `schedule/capabilities/reminder.py` + `schedule/store/reminders.py` | REMINDER@41；`提醒`/`叫我`/`txlb` 等 10 别名 | 自然语言时间点→会话待办≤20；过期治理（迟到>30min 顺延/超 24h 作废） | test_reminder、test_reminder_delivery | real(W10 653) |
| bot.plugin.schedule.reminder_delivery | 提醒每分钟投递（非命令） | 根 `_register_reminder_scheduler` + `schedule/store/reminders.py` | 定时每分钟 | 守岸人督促投递；时序由 timesync 校准 | test_reminder_delivery | real(W10) |
| bot.plugin.schedule.auto_send | 草稿/自动发送(63) | `schedule/auto_send/parser.py` | AUTO_SEND@13；`草稿`/`报存` | 自动发送解析→草稿（仅预览） | test_content_video_auto_send | real(W10) |
| bot.plugin.schedule.timesync | NTP 授时（非命令） | `schedule/timesync/timesync.py` | 定时（重启后 ~65s 起每 10 分钟） | NTP 全败→HTTPS Date 头兜底（仅收 https，±1.5s 钳制）；mode=4-only；1970 编码解包门；驱动提醒/笔记时序 | test_timesync、test_v21r2_stall_timesync_http（R3 批 132 面） | real(W10/R3) |

> S11 增量（非存量、not_wired 登记）：`schedule/service/llm_draft.py`（NL→ScheduleDraft）、`timetable.py`（课表截图→结构草稿）、`delivery.py`（occurrence→SendQueue 干跑不伪装）、`data/calendar_exceptions.json`（空表不臆造）——54 例离线，production_wiring=not_wired（矩阵 L56-L58）。支撑件：`schedule/service/{schedule_service,schedule_dag,schedule_store,schedule_rrule}.py`。

### 1.11 域 notes（笔记备忘；1 topic）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.notes.notes | 笔记(70) | `notes/capabilities/notes.py` + `notes/store/notes_store.py` | REMINDER@41 复用提醒路由；`笔记`/`bjlb` | Markdown 笔记 CRUD（记/看/放下/列表）；uuid 图片落盘 SSRF 入口+落点双查；「<事项>做完了」自然勾选（并列候选问「有几件事都对得上」）；mark_done 死锁已修 | test_notes、test_notes_item_checkoff | real(W9 261) |

### 1.12 域 subscribe（订阅与资讯；4 topics + 轮询推送）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.subscribe.subscribe | 订阅(43) | `subscribe/capabilities/{subscribe,subscribe_v2}.py` + `subscribe/store/subscription_*×6` + `subscribe/adapters/`（social_v2/bilibili/xiaohongshu/music_v2/target_notice） | SUBSCRIBE@12；`订阅`/`subscribe`（群内 add/list 需管理员） | B站/YT(含 live)/xhs(creator/column/live-degraded)/推特/微博；outbox+metadata 落库；存储离环（17 门面 await 化） | test_subscribe_capability_v2、test_subscribe_capability_bridge、test_social_subscription_fetch_v2、test_auditfix_subscriptions_capabilities | real(W12 面 629) |
| bot.plugin.subscribe.push_poller | 订阅轮询推送（非命令） | `subscribe/store/{subscription_scheduler,subscription_watcher,subscription_runtime_v2}.py` | 定时轮询+推送 | 调度投递；watcher 为孤儿模块（W12 登记）——入缺口清单 | test_audit_fixes_b（引用面） | real(W12) |
| bot.plugin.subscribe.news | 快报(56) | `subscribe/capabilities/news.py` + `subscribe/feeds/news_feeds.py` | NEWS@41；`快报`/`kb`/`AI新闻` 等 22 别名 | V2EX 真 Atom+IT之家/少数派/华尔街见闻/BBC中文；营销过滤+RSS 摘要行；默认 20 条 | test_news、test_sdd7_n4 | real(W12) |
| bot.plugin.subscribe.today_history | 历史上的今天(59) | `subscribe/capabilities/today_history.py` + `subscribe/feeds/today_history.py` + 根 `_register_today_history_scheduler` | TODAY_HISTORY@41；`历史上的今天`/`lssd`（群内设置/取消 admin） | 多历法行（黄帝纪元/佛历/伊斯兰历/和历/拜占庭）；定时推送 | test_today_history_robustness | real(W12) |
| bot.plugin.subscribe.epic | Epic 免费游戏(67) | `subscribe/capabilities/epic.py` + `subscribe/feeds/{epicfree,steamfree}.py` | EPIC@41；`epic`/`免费游戏` 等 9 别名 | Epic/Steam 免费游戏速报 | test_epic_card | real(W12) |

### 1.13 域 media（媒体处理；4 topics）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.media.media_archive | 媒体归档(42) | `media/capabilities/media_archive.py` + `media/archive/`（sources） | MEDIA_ARCHIVE@43 + `收藏\|归档`+`存聊天记录`；回复媒体触发（get_msg 反查/get_forward_msg 展开） | VLM 判 类别×IP 双层归档；sha256 去重+JSON 旁车；视频 ffmpeg 抽帧 5 帧；SSRF 护栏+magic bytes+100MB/50 件日/4 件单条限额；min_role 默认 super_admin；卡片 prune keep=120 | test_media_archive（35 例） | real(W11 275+424) |
| bot.plugin.media.vision | 视频理解/识图(35) | `media/ingest/{vision_describe,video_understanding,transcribe,telegram_media}.py` + `media/video/video_pipeline.py` | 配置型 9 键 BOT_VISION_*/BOT_VIDEO_* + 被动（识图 registry） | 识图群最近图 5 分钟环形缓存；看图意图门控；视频理解配额；S10 协议化（8 描述符；OCR=VLM 代位 degraded；ASR provider 在盘） | test_vision_and_failover、test_asr_transcribe、test_video_progress_ack、test_video_seam | real(W11) |
| bot.plugin.media.image_search | 搜图(47) | `media/capabilities/image_search.py` + `media/search/sauce_search.py` | on_message matcher（非 RouteKind）；`搜图`/`以图搜图` | 回复图片可触发（get_msg 反查）；失败三分类（no_key/http_error/真无结果）；Tavily 兜底 | test_auditfix_wave3_logic、test_copy_redline_gate（引用面） | real(W11) |
| bot.plugin.media.tts | 语音合成(72) | `media/capabilities/tts.py`（归属裁决=W-PA2 待定，creation 激活前留 media） | TTS@41；`语音`/`tts`（需 BOT_TTS_ENABLED） | TTS 出站链；S10 协议面 descriptor+limits（invoke=unavailable 不假成功；实现体缺，矩阵 L51 partial+live blocked） | test_tts、test_tts_outbound_chain | real(W11) |

> 支撑件：`media/registry/`（character/media_registry.py：chat_message_id 与视频/CC 关联存档）；CC 字幕必存（download 域联动）。

### 1.14 域 files（文件进出站；3 topics）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.files.download | 下载(60) | `files/capabilities/download.py` + `files/sources/downloader.py` | `/bot download`（ADMIN 前缀族；裸「下载」不走路由） | yt-dlp 原生 8 并发+16MB Range；SSRF 护栏（check_download_url）；CC 字幕自动抓取（zh 优先 srt）落盘 | test_audit_fixes_b、test_chat_and_sources_regressions（downloader 引用面） | real(W9 261) |
| bot.plugin.files.group_files | 群文件(27) | `files/capabilities/group_files.py` | `/bot 群文件`（admin，仅群聊） | 群文件统计 | test_batch_cdf_modules | real(W9) |
| bot.plugin.files.export | 文件导出(29) | `files/capabilities/file_exchange.py` + `files/sources/file_reader.py` + `transport/sender/file_gateway.py`（出站段在 transport） | `文件 <md\|docx\|pptx\|xlsx\|pdf> <主题>`（admin_file_export matcher，无 /bot 前缀） | 7 读通道；.ppt/.xls 诚实 parser_unavailable；旧 Office 禁冒充现代格式；FileSource→Ticket→deliver | test_file_exchange、test_file_gateway_phase1、test_runtime_subfeatures、test_phase0_3_features | real(W9) |

> 预留：`files/artifacts/`（W-PA3，FILE-002 域内槽，reserved 非业务）。

### 1.15 域 transport（出站通道；3 topics + 执行面）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.transport.send_queue | 发送队列执行面（非命令） | `transport/sender/{queue,worker,gateway,timeout}.py` + 根 `_register_send_queue_scheduler` | SQLite 队列（所有出站消息） | part 级幂等+UNKNOWN 确认+PARTIAL 断点续发；retcode=1200→bot_unavailable 挂起（90s 重探不烧预算）；worker bot_unavailable 静默化（R2/FIX 裁定） | test_auditfix_sender_queue、test_queue_poison_row、test_a03_timeout_retry_semantics、test_a22_inline_claim_race、test_operational_failures | real(W14 281+233) |
| bot.plugin.transport.queue_view | 队列查询(8) | `ops/admin/runtime_admin.py`（查询面）+ `transport/sender/queue.py`（数据面） | `/bot queue`（admin） | 队列深度/状态投影 | test_auditfix_llm_route、test_audit_fixes_b（引用面） | real(W14/W16) |
| bot.plugin.transport.receipt_view | 回执查询(5) | `transport/sender/receipts.py`（数据面） | `/bot receipt <id>`（admin） | 发送回执逐 part 查询 | test_decision_engine_shadow（引用面）、W14 波面 | real(W14) |
| bot.plugin.transport.mail | 邮件(37) | `transport/mail/{mail_adapter,mail_bridge}.py` | `/mail status/accounts/use/send/pause/resume`（仅 TG 管理端） | ResilientMailAdapter（bot.py 直依赖，垫片覆盖）；退避韧性（R2 批） | test_mail_adapter_resilience、test_mail_bridge | real(W14) |

### 1.16 域 assistant（日常助理+校园转发；1 topic + 定时/被动）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.assistant.inbox | 收件箱(71) | `assistant/daily/capabilities/daily_assist.py` | DAILY_ASSIST@42；`收件箱`/`inbox` | 速记落纯文本收件箱（inbox.md 待处理段+按日归档 daily/，与 ZCode/手机端共享） | test_daily_assist（18+R6 池化 21） | real(W13 面 47+43+68) |
| bot.plugin.assistant.scheduled | 早报/晚报/到点吃什么（非命令） | `assistant/daily/store/daily_assist.py` + 根 `_register_daily_assist_scheduler` | 定时（餐点 11:15/17:15、早报 09:00、晚报 21:00） | food.md 自定义优先+内置库兜底+jsonl 历史 7 天不重复；早报 LLM 划重点失败回退原文；推送名单空=整链不注册绝不猜人；11 文案池 pick_variant 轮换（R6/R5） | test_daily_assist | real(W13) |
| bot.plugin.assistant.campus | 校园自动转发（非命令） | `assistant/campus/campus.py` + `assistant/campus/campus_store.py` + 根被动 matcher(priority=8, block=False) | 被动（学校号所在群文本） | message_id 幂等（90 天 prune）→私聊转发【校园转发】前缀 1500 字截断；**纯监听绝不向学校群发消息**；三重来源门 enabled∧self_ids∧whitelist | test_campus_digest（15 例） | real(W13) |

### 1.17 域 ops（运维管理；9 topics + 监控面）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.ops.feature | 功能管理(1) | `ops/features/feature_control.py` + `feature_catalog.py` + `feature_gate.py` | `/bot feature list/get/enable/disable/reset/preview`（改仅超管） | 特性树/CAS 父子开关；执行门未接生产（矩阵 L20） | test_feature_cards、test_feature_store_integrity、test_runtime_feature_gate | real(W16 批2 348) |
| bot.plugin.ops.status | 状态面板(2) | `ops/admin/runtime_admin.py` | `/bot status`（无参） | 运行状态汇总（健康信息在 status 内，无顶层 health 子命令） | test_auditfix_runtime_policy（rg 级） | real(W16) |
| bot.plugin.ops.why | 决策解释(4) | `ops/admin/runtime_admin.py` + `core/decision/trace.py` | `/bot why [id]` | 最近决策回放解释 | test_runtime_admin（rg 级） | real(W16) |
| bot.plugin.ops.audit_view | 审计查询(6) | `ops/audit/{logger,file_logger}.py`（数据面） | `/bot audit <request_id>`（admin） | 审计链按 request_id 关联 | test_audit_fixes_b、test_auditfix_llm_route | real(W16) |
| bot.plugin.ops.recent | 最近事件(7) | `ops/admin/runtime_admin.py` | `/bot recent [数量 1-20 默认5]` | 最近运行事件 | 同上（引用面） | real(W16) |
| bot.plugin.ops.setup | 接入诊断(11) | `ops/smoke/diagnostics.py` | `/bot setup llm` | LLM 接入体检 | test_audit_fixes_b（diagnostics 引用面） | real(W16) |
| bot.plugin.ops.logs | 日志查看(28) | `ops/admin/runtime_logs.py` | `/bot logs [级别] [数量 1-200 默认50]` | 日志摘要查询 | test_help_deep_teaching_n2re（引用面） | real(W16) |
| bot.plugin.ops.runtime_switches | 运行开关(36) | `ops/smoke/diagnostics.py`（配置型 .env 5 键：SEND_QUEUE/WORKER/AUDIT/RECEIPTS/DIAGNOSTICS） | 配置型，改后重启 | 出站链分段开关 | test_smoke_config | real(W16) |
| bot.plugin.ops.telegram_cfg | Telegram 适配(38) | 域外（bot.py 适配器，非 329 文件）+配置面 | 配置型 TELEGRAM_BOTS/BOT_TELEGRAM_ADMIN_* | TG 管理端/轮询韧性（R2 catch_all 永不逃逸）；**载体域外（G2）** | r2 面 21+111+66 | real（配置面登记；适配器域外） |
| bot.plugin.ops.error_card | 统一错误报告卡（非命令） | `ops/monitor/error_report.py` + `render/`（卡渲染）+ `card_render/templates/error_card.html` | 自动（能力异常时） | 两段式异步：毫秒级文本回执先行，卡图 3-33s 补发；冷却闸 60s 降级一句纯文本；渲染失败纯文本兜底 fail-open | test_error_report、test_error_card_async、test_error_card_contract | real(W16 批1 292) |
| bot.plugin.ops.alerts | 运维告警（非命令） | `ops/monitor/alerts.py` + `result_unknown.py` + `disconnect_notice.py` + `event_{store,service}.py` | 自动 | 300s 抑制；台账 TTL；重连对账；断线通知；UNKNOWN 处理 | test_result_unknown、test_disconnect_notice、test_event_service_v21 | real(W16) |
| bot.plugin.ops.recovery_incident | 自愈/故障/采集器（非命令，S14 增量） | `ops/{recovery,incident,collectors,repair}`（REP 席 repair 在飞） | 控制面/自动 | RecoveryService/IncidentService/NapCat 采集器/两轮预算待审补丁（绝不自动部署）；**计划面+在飞，实跑证据待补** | （S14 实跑节待填） | 在飞 |

### 1.18 域 core（系统内核；4 topics + 内核面）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.core.readiness | 配置就绪(13) | `core/config/config_readiness.py`（config.py 529 字段留守根位） | `/bot readiness`（admin） | 配置体检 | test_perf_hotpath（引用面） | real(W16) |
| bot.plugin.core.search | 联网搜索(23) | `core/search/{search_service,search_api,web_search,mcp_web_search_server,search_smoke}.py` | `/bot search <问题>`（admin） | 九源逐源诚实状态（xhs/YT/X/LinuxDo 缺）；ACG 竖源三源（chat 链时效检索）；provider 生产装配未接（not_wired） | test_search_service_v21、test_v21_s10_protocols | real(W16 批2) |
| bot.plugin.core.credentials | 凭据(25) | `core/credentials/{platform_credentials,credentials,credential_health}.py` + 根 `_register_credential_check_scheduler` | `/bot alert check [--probe]`；`/bot cookie status/import/login/check/expiry` | 凭据健康巡检定时批；cookie 文件管理面联动 link_parse/parsers/cookies | test_platform_credentials | real(W16 批2) |
| bot.plugin.core.decision | 决策引擎(41) | `core/decision/`（engine/shadow/trace/dispatcher/outbound_*） | `/bot decision [N 1-100 默认20]`（admin） | 影子对照默认 legacy_only 不接管；出站统一执行器阶段 1 收编（poke/表情直连点）；shadow 绝不发送 | test_decision_engine_shadow、test_decision_trace_persistence | real(W16 批1/2) |
| bot.plugin.core.control_plane | 控制面 REST（非命令） | **`control_plane/`（真身未迁，旧位 31 件）** | `python -m …control_plane`；loopback 8742+Bearer | /api/v1 功能树/配置 CAS/LLM 端点 13+占卜 8/日志 SSE/工作区/动作；**无聊天命令（COMMANDS.md 明示）**；真实发送端口 503 not_wired | test_control_plane_*（15 文件 197+215 面） | **待迁（在飞批）** |
| bot.plugin.core.supervisor | 进程沙箱（非命令） | `core/supervisor/`（windows_sandbox/job_objects/appcontainer/acl/sandbox/ipc） | 内部（控制面资源治理） | AppContainer/Job 限制；ISO-001/002 面 | test_bot_supervisor、test_supervisor_isolation、test_sandbox_windows | real(W16) |

### 1.19 域 render（渲染出站；1 topic + 管线）

| 稳定 ID | 业务(topic#) | 载体 | 入口 | 关键行为/边界 | 测试指针 | 迁移 |
|---|---|---|---|---|---|---|
| bot.plugin.render.forward | 合并转发(33) | `render/renderer.py` + `render/templates.py` | 配置型 BOT_RENDER_FORWARD_* 4 键 | 合并转发/chunks 切分 | test_rendering_contract（171 面）、W13b 契约族 181 | real(W13b) |
| bot.plugin.render.card_pipeline | 卡片渲染管线（非命令） | `render/{renderer,render_backends,card_render/{bridge,theme_tokens,usage_cards,models}}` + templates/7 html | 随各能力出图 | 釉瑚云母+液态玻璃；theme_tokens 单一来源；17 平台注册表；mermaid 本地化拦截；playwright 常驻浏览器；UI 铁律（无 meta viewport/body 透明/字重≤700/两枚阴影 token） | test_rendering_contract、test_mica_builders_contract、render_hashes 19 项门 | real(W13b 867) |
| bot.plugin.render.plain_text | 出站文本纪律（非命令） | `render/plain_text.py` + `render/roleplay.py` | 所有出站文本 | 说人话/数值打码/密钥与路径打码（redact_local_secrets）；normalize_paragraph_breaks 段间单换行 | test_rendering_contract、test_roleplay_paragraphs（rp 面 12） | real(W13b) |

## 二、行为对照表框架（逐业务模板 + 填写状态）

### 2.1 逐业务对照模板（每业务一行，S13 执行批照此填充）

| 列 | 填法 | 证据等级 |
|---|---|---|
| 业务 ID | §1 表稳定 ID | — |
| 触发形态 | 别名/路由@priority/被动事件/定时（盘点值=command-spec-inventory A.1/A.2 + base_router） | 盘点 |
| 输出形态 | 纯文本/卡片（模板名）/合并转发/文件/语音；错误卡兜底路径 | 盘点 |
| 边界限额 | 配额/条数/字数截断/权限门/冷却/每日上限（盘点值=源码+帮助页） | 盘点 |
| 降级行为 | 主通道失败→兜底源/纯文本兜底/五池话术/诚实无源标注 | 盘点 |
| 回归命令 | `pytest -k "<域关键词>"`（各波实跑命令，见 §1.0 证据列） | **real（波日志实跑数字）** |
| 真机对照 | 重启后按 acceptance-manual §6.6 族逐条实测 | **pending-live（全部业务）** |

### 2.2 已填示例：weather 域（示范一行完整填充）

| 列 | 值 |
|---|---|
| 业务 ID | bot.plugin.weather.weather |
| 触发形态 | WEATHER@41；别名 8 条（天气/weather/天氣/查天氣/天氣預報/tianqi/tq/chatianqi/ctq） |
| 输出形态 | 天气卡（渲染管线）；预警支路文本 |
| 边界限额 | 预警≤5 条；geocoding count=10；NMC rest/weather 必须带码表有效 stationid |
| 降级行为 | NMC 主通道 2 次重试→Open-Meteo 兜底；无源诚实标注 |
| 回归命令 | `"$PY" -m pytest tests -k "weather|nmc|open_meteo" --basetemp=$TEMP/pytest-v21r2 -p no:cacheprovider -q` → W3 实跑 259 passed + 关键词 139 passed（real） |
| 真机对照 | pending-live（等提权重启+acceptance-manual §6.6 实测） |

### 2.3 全域填写状态矩阵（real=迁移零回归已证；行为列=盘点值；live=全 pending）

| 域 | 迁移对照 | 波日志回归（real 证据） | 行为真机对照 |
|---|---|---|---|
| chat_reply | real（15a/15b/15d/15e） | 755+289 / 739 / 3186 / 1241；policy/security 行=待迁 | pending-live |
| meme | real(W6) | 439+413 | pending-live |
| link_parse | real(W1a+W1b) | 698+225 / 316+1204 | pending-live |
| music | real(W2) | 432 | pending-live |
| location | real(W16 序) | 436+288 | pending-live |
| weather | real(W3) | 259+139 | pending-live |
| food | real(W4) | 214 | pending-live |
| finance | real(W7) | 780+857 | pending-live |
| divination | real(W5+S12) | 743/1 skipped；27 | pending-live |
| schedule | real(W10+S11) | 653；54+574 | pending-live |
| notes | real(W9) | 261（与 files 合面） | pending-live |
| subscribe | real(W8 序) | 629 | pending-live |
| media | real(W11) | 275+424 | pending-live |
| files | real(W9) | 261（与 notes 合面） | pending-live |
| transport | real(W14 序) | 281+233 | pending-live |
| assistant | real(W12 序) | 47+43+68 | pending-live |
| ops | real(W16) | 292/348/229 | pending-live |
| core | real 除 control_plane | 同 W16；control_plane=待迁 | pending-live |
| render | real(W13b) | 181+867 | pending-live |

> **纪律声明（禁美化）**：`real` 只证明「组织迁移零行为改动+域回归绿」（矩阵回填草案 §〇.9 口径），不构成 LEGACY-001 行为验收；65 行 live_validation 本会话零 passed，本草案不宣称任何行为真机通过。

---

## 三、Plugin manifests 骨架（19 域草案）

字段对齐核心要求 §四/指南 §5 L126 节点必填面：`stable_id / parent / kind / implementation_ref / route_kind / default_enabled / required_roles / config_keys / documentation_refs`。kind 一律 `domain`（域根节点；域内能力建叶节点时 kind=feature/sub_feature/command）。**default_enabled=true 仅对存量在产业务；reserved 空白（poi/game_live/gscore/creation）一律 false。**

| 域 | stable_id | parent | implementation_ref | route_kind | default_enabled | required_roles | config_keys（有据键/前缀†） | documentation_refs |
|---|---|---|---|---|---|---|---|---|
| 1 | bot.plugin.chat_reply | bot.plugin | `domains/chat_reply/`（policy/+security/ 待迁，implementation_ref 双写旧路径） | CHAT、ADMIN、NATURAL_COMMAND、ALIAS、AFFINITY、GROUP_INFO、IGNORE | true | user（admin 面 admin） | BOT_MODEL_*、BOT_CHAT_*、BOT_CONTENT_ROUTE_*、BOT_RATE_LIMIT_*、BOT_QUIET_HOURS_*、BOT_SHARED_GROUP_CONTEXT_*、BOT_GROUP_DIGEST_*、BOT_PERSONA_VERSIONED_INJECTION、BOT_MASTER_LOVE_* | command-catalog 27 topic 页；COMMANDS.md；HANDBOOK §人格/好感/记忆族 |
| 2 | bot.plugin.meme | bot.plugin | `domains/meme/` | MEME、MEME_LIBRARY、RANDPIC | true | user | BOT_REACTIONS_ENABLED/PROBABILITY/COOLDOWN_SECONDS/MAX_PER_HOUR | command-catalog 4 topic 页；HANDBOOK §30 |
| 3 | bot.plugin.link_parse | bot.plugin | `domains/link_parse/` | CONTENT | true | user | cookie 群（catalog A26 为准） | command-catalog 2 topic 页；HANDBOOK §链接解析 |
| 4 | bot.plugin.music | bot.plugin | `domains/music/` | MUSIC、MUSIC_MODE | true | user（点歌模式 admin） | （catalog A26 为准） | command-catalog topic「点歌」 |
| 5 | bot.plugin.location | bot.plugin | `domains/location/`（poi/ 预留 false） | WIKI、MOEGIRL、MOEGIRL_QUESTION | true | user | （catalog A26 为准） | command-catalog 2 topic 页；CMD 规格 E-35 |
| 6 | bot.plugin.weather | bot.plugin | `domains/weather/`（assets/qx.json） | WEATHER | true | user | （catalog A26 为准） | command-catalog topic「天气」；台账 #9 |
| 7 | bot.plugin.food | bot.plugin | `domains/food/` | EAT | true | user | （catalog A26 为准） | command-catalog topic「吃什么」 |
| 8 | bot.plugin.finance | bot.plugin | `domains/finance/`（contracts/finance.py 留 core） | MARKET、STOCKS、COMMODITIES、BOND、NORTHBOUND、FX | true | user | （catalog A26 为准） | command-catalog 6 topic 页；HANDBOOK §24.2 |
| 9 | bot.plugin.divination | bot.plugin | `domains/divination/` | DIVINATION | true | user（REST admin） | bot_control_plane_divination_db（生产未配） | command-catalog topic「占卜」；S12 日志 |
| 10 | bot.plugin.schedule | bot.plugin | `domains/schedule/` | REMINDER、AUTO_SEND | true | user | bot_time_sync_http_enabled/url、bot_schedule_*×7（S11） | command-catalog 2 topic 页；S10/S11 日志 |
| 11 | bot.plugin.notes | bot.plugin | `domains/notes/` | REMINDER（复用提醒路由） | true | user | bot_notes_* 六键（7414e87） | command-catalog topic「笔记」 |
| 12 | bot.plugin.subscribe | bot.plugin | `domains/subscribe/` | SUBSCRIBE、NEWS、TODAY_HISTORY、EPIC | true | user（群内 add/list admin） | （catalog A26 为准） | command-catalog 4 topic 页 |
| 13 | bot.plugin.media | bot.plugin | `domains/media/` | MEDIA_ARCHIVE、TTS（搜图=on_message 非 RouteKind） | true | user（media_archive min_role=super_admin） | BOT_MEDIA_ARCHIVE_*×9、BOT_VISION_*、BOT_VIDEO_*、BOT_TTS_ENABLED | command-catalog 4 topic 页；HANDBOOK §23 |
| 14 | bot.plugin.files | bot.plugin | `domains/files/`（artifacts/ 预留 false） | ADMIN 前缀族（download/群文件/文件导出） | true | user（群文件/导出 admin） | （catalog A26 为准） | command-catalog 3 topic 页 |
| 15 | bot.plugin.transport | bot.plugin | `domains/transport/` | （无专属 RouteKind；ADMIN 查询面） | true | admin（查询面） | .env 运行开关 SEND_QUEUE/WORKER/AUDIT/RECEIPTS/DIAGNOSTICS | command-catalog 3 topic 页；矩阵 L35/L36 |
| 16 | bot.plugin.assistant | bot.plugin | `domains/assistant/` | DAILY_ASSIST（+被动 on_message） | true | user（推送名单空=链路关） | BOT_DAILY_ASSIST_*、BOT_CAMPUS_* 六键 | command-catalog topic「收件箱」；HANDBOOK §27；#33 |
| 17 | bot.plugin.ops | bot.plugin | `domains/ops/` | ADMIN 前缀族 | true | admin（feature 改=super_admin） | .env 运行开关 5 键 | command-catalog 9 topic 页；矩阵 L19/L20/L29/L68-L72 |
| 18 | bot.plugin.core | bot.plugin | `domains/core/`（control_plane 未迁，双写旧路径） | ADMIN 前缀族（+REST /api/v1） | true | admin（REST 按 RBAC） | BOT_MODEL_REGISTRY、control_plane platform_db/actions_db | command-catalog 4 topic 页；矩阵 L14-L30/L53 |
| 19 | bot.plugin.render | bot.plugin | `domains/render/` | （无；出站管线经各能力） | true | user（随能力） | BOT_RENDER_FORWARD_*×4、BOT_RENDER_MAX_CONCURRENCY、BOT_RENDER_WAIT_BUDGET_MS | docs/rendering-contract.md；render_hashes 门 |
| — | bot.plugin.core.reserved.game_live / gscore | bot.plugin.core | base_router L615/L621（无实现） | （reserved 接口） | **false** | — | — | command-spec-inventory A.3 |

† config_keys 全量（529 字段）以 `config.py`+`docs/config-catalog*`（doc_sync 门锚定）为准；本列只列本席有据键，落正式 manifest 前按缺口 #9 对齐。

## 四、缺口清单（精确列明）

| # | 缺口 | 精确位置 | 影响 |
|---|---|---|---|
| 1 | **chat_reply 域 15c 未迁**：policy/ 5 件+security/ 4 件真身仍在旧位（本席实读 gate.py=380 行、content_safety.py=108 行，非垫片） | `plugins/bot_unified_runtime/policy/`、`security/` | §1.1 五行标 `待迁`（topic 14/19/26/32 载体+安全支撑件）；chat_reply 域迁移不完整 |
| 2 | **core 域残留未迁**：control_plane/ 31 件（在飞批）+ `sources/{search_intent,acg_search}` + `runtime/{capability_protocols,database_broker,loop_watchdog}` | `plugins/bot_unified_runtime/control_plane/` 等（woc-log §八.4 不迁清单） | §1.18 control_plane 行标 `待迁`；core manifest implementation_ref 需双写 |
| 3 | **live 行为验证全空白**：bot 未重启（台账 #10+全批 WIP），77 topic + 全部非命令业务 live=pending；L67 行级验收未做 | 全部业务 | §2.3 矩阵最后一列全 pending-live；补齐需提权重启+acceptance-manual §6.6 族实测 |
| 4 | **无直接测试指针**（文件名+rg 双探针均无专属断言）：`link_parse/support/url_cleaner`、`support/parse_history`、`parsers/image_stitch`、`subscribe/feeds/{epicfree,steamfree}`、`subscribe/store/subscription_watcher`（W12 孤儿登记）、`ops/monitor/intent_telemetry`、`ops/smoke/{console_chat,route_demo}`、`ops/integrations/gscore_bridge`、`chat_reply/policy/reply_budget` | 各域支撑件 | §1 对应行测试指针列留空；S13 前需补离线断言或显式接受引用面覆盖 |
| 5 | **配置型 7 topics 无命令行为断言面**：限流(32)/合并转发(33)/群摘要(34)/视频理解(35)/运行开关(36)/Telegram(38)/供应商(39)——行为=配置生效，无 e2e 断言；其中 34 另有 #33 台账两存量缺陷（摘要读零行+推送侧 LLM 未装配） | config 键面 | 对照表须以「config 键断言+真机生效验证」双件补齐；#34 行为对照预期会暴露 #33 缺陷 |
| 6 | **37+ 平台解析无逐平台断言矩阵**（现覆盖=样本级）；discourse 真实样本依赖用户外部目录缺失（W8 环境红登记） | `domains/link_parse/parsers/` | LEGACY-001「逐个对照」在 link_parse 域的最小颗粒=平台级，需建平台×样本矩阵 |
| 7 | **已知漂移/遗留锚**：echo.py:785 帮助文本「二次元问句(44)」实值 46（CMD 席登记未改）；W3 weather Q03 锚移交 W15d/尾声波；command_catalog:201 生成物 header 装饰行留尾声波；根 `__init__.py` 惰性导入切换+垫片退役留尾声波（108 张被根消费） | 各处 | 尾声波清账项；对照表以实际行为为准（46） |
| 8 | **reserved 未实现 2 条**：capability.game_live / capability.gscore（base_router L615/L621） | base_router | manifest default_enabled=false，不入业务行 |
| 9 | **manifest config_keys 全量核对未做**：本草案只列有据键/前缀，529 字段全量对齐需逐域过 config-catalog A26（doc_sync 门锚定） | 本草案 §三† | 落正式 ProductManifest 前的机械对齐批 |
| 10 | **RWC1 SKIP 四件**：memory_service/memory_store_v21/knowledge_service/teaching_service 仍留 character/ 旧位（待 S8 收官波）——**✅已闭环转正（2026-09-19 LEGACY-FIX-c 实证）**：四件真身已迁 `domains/chat_reply/character/`（垫片 docstring 自证 v21r2 S8 收官波收编；WIRE-SVC 日志引用 canonical 路径），旧位 18 行 PEP 562 活转发垫片，四垫片→canonical 属性 `is` 同对象冒烟 OK，四模块测试族（memory_service_v21/memory_router_reuse/v21_knowledge_service/v21_teaching_service/v21_wire_svc_assembly/webui_knowledge/knowledge_mtime_cache）**129 passed** | `character/`（旧位=垫片） | chat_reply 域 implementation_ref 双写；三件为 V21 新服务（not_wired）非存量业务（not_wired 语义仍有效：生产装配见 runtime/service_wiring.py 主门缺省关，WIRE-SVC 席） |
| 11 | **location poi/ 结构性空白**（POI/地图/导航无载体，CMD 席 E-35 待立项） | `domains/location/poi/`（reserved 占位） | 用户点名 8 域中唯一空白，manifest default_enabled=false |
| 12 | **S14 三子包+REP repair 在飞**：recovery/incident/collectors/repair 行为对照无实跑节（s14 §五待填、REP 占域施工中） | `domains/ops/{recovery,incident,collectors,repair}` | §1.17 标 `在飞`；收口波补实测后转 real |

## 五、统计封账（LEGb 席，2026-09-18）

- **77/77 帮助 topic 全分配**：A.1 admin 族 42 + A.2 子功能族 35，逐域计数与 §1.0 表一致（chat_reply 27 / ops 9 / finance 6 / core 4 / media 4 / meme 4 / subscribe 4 / transport 3 / files 3 / link_parse 2 / location 2 / schedule 2 / chat_reply 外单 topic 域各 1：music/weather/food/divination/notes/assistant/render）。
- **业务行总数 101** = 77 topic 行 + 24 条非命令可感业务行（定时批 9 个 scheduler 工厂中的用户可感面、被动监听 4、出站/渲染/管线执行面、控制面 REST、沙箱等，逐行见 §1 各表）。
- **域分布**：19 域全部有业务行；creation 预留域登记不展开（非存量）。
- **已迁覆盖率（组织面）**：19/19 域开工、17 域全量收波；chat_reply 差 15c（policy+security 9 件）、core 差 control_plane 等 8 件（缺口 #1/#2）——EP1 席机核 275 张垫片/1591 消费边与各波声明吻合。
- **行为对照**：模板+全域 real 回归证据已填（§2.3）；真机对照 101/101 行 pending-live（缺口 #3）。
- **缺口 Top5**：①15c 未迁 ②control_plane 未迁 ③live 全 pending ④9 模块无直接测试指针 ⑤配置型 7 topic 无行为断言面。

> 本草案为 LEGb 席只读盘点产物：零代码改动、零测试套件实跑（仅 rg/ls/探针）、零 git 写操作。数字全部来自文首 §0.1 真值源与本席实跑探针，无编造。

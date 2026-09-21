# V2.1 S0 冻结席（A1）— 工作树 WIP 快照 + 全入口清单

- 冻结时刻：2026-09-17（S0 轮）
- 冻结人：S0 冻结席 A1（全程只读，唯一写入=本文件）
- HEAD：`56d1461305e0dc8443c777f2eeb06d2f39da3ac9`（`git rev-parse HEAD` 实跑）
- 证据命令（全部实跑）：
  - `git status --porcelain=v1` / `git rev-parse HEAD` / `git log --oneline -15`
  - `rg -n "on_message|on_command|on_notice|on_request|on_metaevent" plugins/bot_unified_runtime --type py`
  - `rg -n "scheduler|add_job|register_.*schedul" plugins/bot_unified_runtime --type py -i`（含非 __init__ 补扫）
  - `rg -n "@(app|router)\.(get|post|put|delete|websocket)" plugins/bot_unified_runtime/control_plane` + `rg -c` 分文件计数
  - `rg -n "call_api\(|send_private_msg|send_group_msg|set_msg_emoji_like" plugins/bot_unified_runtime --type py`
  - 扫描范围：`plugins/`、`scripts/telegram_resilience.py`；未进 `ChatBot_Runtime/`、`ChatBot_Archive/`、`.env`；未运行测试。
- 诚实声明：标注 `unknown` 处为只读扫描未深挖项（按任务预算纪律不做二次定位）。

---

## 一、git 快照

### 1.1 `git log --oneline -15`（HEAD=`56d1461`）

```
56d1461 docs(handover): 交接总报告+接手提示词全量更正版（用户 mandate 九个统一）
6ac897b fix(llm,persona): 请求预算 150→300s+五池话术官方语音文风重写（用户裁定）
12b7f4a fix(llm): 生产超时告警三处根修——连接/读取分类拆分+告警带路由轨迹+TG 噪音三段退避
331e2a2 docs(design): WebUI 仪表盘规格 v1
97d0aa6 feat(persona): P2-4 二改——四类拒绝/降级话术池化，守岸人语气 ≥10 变体
ebe6843 feat(chat): P2-4 反注入护栏文案定案——极简版零泄露
793e647 fix(config): 标量 QQ 号键 int→str 宽容装载
d7c55b7 docs(report): 夜间工程总报告（105 笔全对账）
4608235 feat(settings): SETTABLE 热改面全量审计收口——28 死开关诚实化 65→41/31
da255b0 feat(daily-assist): 日常助理能力
4252944 feat(triggers): P2-9 触发词双向机械门
5349bb6 fix(parsers): P2-12 收窄——xhs/douyin 深解析 4 抓取点补 SSRF 落点复查
94b04e6 feat(reminders): A-05 过期治理回执补缺
58d8d41 perf(ledger): P3-9 账本聚合查询索引化
350bf79 fix(timesync): P3-15 NTP originate 校验+源门
```

### 1.2 `git status --porcelain=v1` 完整快照（84 M + 60+ ??）

**M（已跟踪已改，39 文件）**：

| 文件 | 归属判读（对照 HANDOFF-NEXT §6 在飞席） |
|---|---|
| `.env.example` | 并行批配置键同步（在飞共用面） |
| `AGENTS.md` / `COMMANDS.md` / `HANDOFF-NEXT.md` / `docs/HANDBOOK.md` / `docs/HANDOVER-2026-09-15.md` / `docs/README.md` / `docs/acceptance-manual.md` / `docs/command-catalog.md` / `docs/config-catalog-full.md` / `docs/db-owners.md` | 文档面多会话共享；HANDOFF §6 自述为交接更正+并行批收敛 |
| `docs/auto-facts.md` | **在飞席⑤：auto-facts 机器册重生成（勿手收）** |
| `bot.py` | 进程入口被改（哪席所有 unknown） |
| `plugins/bot_unified_runtime/__init__.py` | **热区**：多席共享（campus 装配+glossary+调度器+matcher 面），归属混合 |
| `capabilities/chat.py` | **热区**：persona/glossary 席触碰（拆分无歧义归属 unknown） |
| `capabilities/divination.py` | V2.1 divination service 批（tests/test_divination_service_v21.py 对应） |
| `capabilities/echo.py` | **热区**：帮助注册表/多席共享 |
| `capabilities/poke.py` | 戳一戳 v2 批（tests/test_poke_v2.py 对应） |
| `capabilities/runtime_admin.py` | 控制面/管理面批 |
| `character/affinity.py` | affinity v2.1 批（tests/test_affinity_v21.py 对应） |
| `character/glossary.py` | **在飞席②：glossary**（tests/test_glossary_seed.py+test_glossary_recall.py 对应） |
| `config.py` | **热区**：多席配置键共享 |
| `contracts/runtime.py` | 运行时契约改动（席归属 unknown） |
| `control_plane/__init__.py` / `control_plane/_app.py` | 控制面 V2.1 批（api/* untracked 对应） |
| `llm/channel_health.py` / `llm/model_router.py` | LLM 链路批（content_route/usage_service 对应） |
| `output/renderer.py` | 渲染面改动（席归属 unknown） |
| `runtime/aliases.py` / `runtime/capability_registry.py` / `runtime/error_report.py` / `runtime/model_schedule.py` / `runtime/pipeline.py` / `runtime/reactions.py` / `runtime/settings.py` / `runtime/usage_monitor.py` | 运行时面混合改动（feature_gate/feature_catalog、usage_billing、poke v2、content_route 各批触碰，逐席拆分 unknown） |
| `sender/onebot.py` / `sender/worker.py` | **在飞席③：sender 韧性**（tests/test_media_rejection_retry_and_fallback.py 对应） |
| `sources/file_reader.py` / `sources/meme_library_listener.py` / `sources/subscription_runtime_v2.py` | sources 面混合改动（unknown 细分） |
| `scripts/dev.ps1` | 任务入口改动（unknown） |
| `tests/render_hashes.json` + `tests/test_*`（18 个 M 测试，全列于 1.3 下方原表） | 各在飞批的存量测试更新（与上述席一一对应为主） |
| `审查结论与重构计划.md`（`"\345\256\241..."` 转义名） | 评审文档（git core.quotepath 转义显示） |

**??（untracked，60 项）**：

| 文件 | 归属判读 |
|---|---|
| `plugins/bot_unified_runtime/capabilities/campus.py` / `sources/campus_store.py` / `tests/test_campus_digest.py` | **在飞席①：campus**（HANDOFF §6 自述"3 文件 untracked+台账行，提交裁决权在用户"） |
| `plugins/bot_unified_runtime/control_plane/`（24 个新文件：actions.py、api/{actions,events,llm,platform,protocol,v1,workspaces}.py、config_service.py、config_store.py、dispatcher.py、events.py、factory.py、features.py、file_access.py、lifecycle.py、log_collectors.py、metrics.py、platform.py、resources.py、sandbox.py、services.py、sqlite_features.py、workspaces.py）+ `runtime/feature_catalog.py` / `runtime/feature_gate.py` / `capabilities/feature_control.py` | 控制面 V2.1 批（2026-09-17 接手主线；对应 tests/test_control_plane_*×12、test_sqlite_feature_store、test_feature_store_integrity、test_config_control_service、test_runtime_feature_gate、test_runtime_subfeatures） |
| `plugins/bot_unified_runtime/llm/usage_service.py` | usage/billing v2.1 批（tests/test_usage_billing_v21.py） |
| `plugins/bot_unified_runtime/runtime/content_route.py` | R-18 内容路由批（tests/test_content_route.py；AGENTS 台账 #35 记载未提交） |
| `plugins/bot_unified_runtime/sources/draw_store.py` / `sources/reaction_store.py` / `sources/search_service.py` | 抽签存储/贴纸回应 v2/搜图 v2.1 批（tests/test_reaction_store.py、test_search_service_v21.py 对应） |
| `plugins/bot_unified_runtime/supervisor/`（目录）+ `tests/test_supervisor_isolation.py` | supervisor 隔离批（unknown 细节，COMPACT-CHECKPOINT 应有载） |
| `scripts/telegram_resilience.py` + `tests/test_telegram_resilience.py` | TG getUpdates 网络韧性批（AGENTS 顶部载"已落地"） |
| `tests/test_affinity_v21.py` / `test_divination_service_v21.py` / `test_usage_billing_v21.py` / `test_glossary_recall.py` / `test_poke_v2.py` / `test_poke_notice_ingest.py` / `test_media_rejection_retry_and_fallback.py` | 各对应席的 V2.1 新增测试 |
| `tests/_autosync_fixture.py` | autosync 门禁 fixture（unknown） |
| `docs/design/backend-v2-{implementation-guide,product-extensions,acceptance-matrix}.md` / `docs/design/COMPACT-CHECKPOINT.md` | 本轮 V2.1 规格四件（AGENTS 顶部指定入口） |
| `docs/design/control-plane-{core-status,events,metrics,registry,services,workspaces}.md` | 控制面规格六件 |
| `docs/核心要求.md`（转义名） / `findings.md` / `progress.md` / `task_plan.md` / `.cp-test-output.txt` / `.zcode/` | 会话工作残留（unknown；`.zcode/`、`.cp-test-output.txt` 疑为工具生成物，建议后续裁定是否入 .gitignore） |

**M 测试文件全列**（18）：`render_hashes.json`、`test_a18_gate_idempotency_rollback.py`、`test_affinity.py`、`test_affinity_numerical.py`、`test_affinity_query.py`、`test_auditfix_llm_route.py`、`test_autosync_hook.py`、`test_capability_registry.py`、`test_datafix_runtime_paths.py`、`test_deadline_budget.py`、`test_e2e_acceptance.py`、`test_error_card_async.py`、`test_error_report.py`、`test_glossary_seed.py`、`test_help_deep_teaching_n2re.py`、`test_persona_prompt_and_memory.py`、`test_pipeline_review_fixes.py`、`test_trigger_bidirectional_gate.py`。

**在飞五席 → 文件映射总表**（HANDOFF-NEXT.md §6 line 99 原文实读）：
1. campus = campus.py + campus_store.py + test_campus_digest.py（+__init__.py/config.py 共享改动）
2. glossary = character/glossary.py + test_glossary_seed.py + test_glossary_recall.py
3. sender 韧性 = sender/onebot.py + sender/worker.py + test_media_rejection_retry_and_fallback.py
4. persona 测试 = test_persona_prompt_and_memory.py（+capabilities/chat.py 触碰）
5. auto-facts 重生成 = docs/auto-facts.md（勿手收）

---

## 二、全入口清单

### 2.1 NoneBot matcher 注册（50 个，全部在 `plugins/bot_unified_runtime/__init__.py`）

- **on_message ×41**：`:4398` auto_send(p13) / `:4406` mail_notice(p9) / `:4407` chat(p50) / `:4420` meme(p20) / `:4421` natural(p45) / `:4429` meme_library(p22) / `:4431` meme_absorb(p10) / `:4558` dirty_guard_matcher(p3) / `:4581` campus_record_matcher(campus 席新增) / `:4957` file_export(p8) / `:5026` image_search(p46) / `:5105` cookie_admin(p8) / `:5112` nickname_set(p8) / `:5138` group_file_stats(p8) / `:5526` content(p46) / `:5527` music_mode(p40) / `:5528` music(p41) / `:5529` today_history / `:5532` wiki(p41) / `:5533` moegirl(p41) / `:5534` moegirl_question / `:5537` epic(p41) / `:5538` weather(p41) / `:5539` market(p41) / `:5540` fx(p41) / `:5541` stocks(p42) / `:5542` commodities(p41) / `:5543` bond(p41) / `:5544` northbound(p41) / `:5545` divination(p41) / `:5546` news(p41) / `:5547` randpic(p41) / `:5548` reminder(p41) / `:5549` daily_assist(p42) / `:5550` eat(p41) / `:5551` subscribe_cmd(p12) / `:5561` affinity(p41) / `:5571` alias(p10) / `:7368` group_info_matcher(p41) / `:7432` ignore_guide / `:7454` media_archive(p43)
- **on_command ×2**：`:4391` status / `:4399` mail_control
- **on_notice ×7**：`:4537` group_upload_notice(p6) / `:4615` file_notice(p8) / `:4725` poke_notice(p7) / `:4811` emoji_like_notice(p7) / `:4844` group_increase_notice(p6) / `:4845` group_decrease_notice(p6) / `:4846` group_admin_notice(p6)
- **on_request / on_metaevent：0**（rg 无命中）
- 非 `= on_*(` 的命中均为文本/函数名/参数传递（如 `gscore_bridge.py` 的 `on_message` 回调参数、`divination.py` 的 `is_divination_command` 判定函数名、`base_router.py:41` import），非 matcher 注册。

### 2.2 调度器 / 定时任务（APScheduler，`nonebot_plugin_apscheduler.scheduler` 于 `__init__.py:3800` 引入）

**注册函数族 12 个**：

| 注册点 | 调度族 | add_job 位置 |
|---|---|---|
| `__init__.py:1455` `_register_send_queue_scheduler` | 发送队列 worker | `__init__.py:1494` |
| `__init__.py:1512` `_register_credential_check_scheduler` | cookie 凭证检查 | `__init__.py:1609` |
| `__init__.py:1625` `_register_today_history_scheduler` | 历史上的今天 | `__init__.py:1707,1743`（含 job 重排） |
| `__init__.py:1764` `_register_kb_wiki_sync_scheduler` | KB wiki 同步 | `__init__.py:1799,1815` |
| `__init__.py:2608` `_register_reflection_scheduler` | 夜间反思 | `__init__.py:2643,2658` |
| `__init__.py:2804` `_register_reminder_scheduler` | 提醒投递 | `__init__.py:2832` |
| `__init__.py:2939` `_register_digest_push_scheduler` | 21:30 群摘要推送 | `__init__.py:2966` |
| `__init__.py:3174` `_register_daily_assist_scheduler` | 日常助理（餐点/早报/晚报） | `__init__.py:3196,3216,3234` |
| `runtime/model_schedule.py:133` `_register_model_schedule_scheduler` | 模型计划 | `model_schedule.py:162` |
| `runtime/usage_monitor.py:396` `register_usage_monitor_scheduler` | 用量监控 | `usage_monitor.py:656,674` |
| `sources/subscription_runtime_v2.py`（模块级） | 订阅轮询 ×2 | `subscription_runtime_v2.py:40,49` |
| `__init__.py:4027,4082` 直接 `scheduler.add_job` ×2 | 用途 unknown（位于装配区，疑似 poke 好感日限重置/其他） | — |

装配调用链：`__init__.py:3816-3918`（send_queue→credential→model_schedule→usage_monitor→today_history→kb_wiki→reflection→reminder→digest_push→daily_assist）。**add_job 总计 20 处**（`__init__.py` 15 + model_schedule 1 + usage_monitor 2 + subscription_runtime_v2 2，rg -n 实跑）。

### 2.3 控制面路由（FastAPI，62 个装饰器路由 + 1 处动态未枚举）

| 文件 | 路由数 | 路由 |
|---|---|---|
| `control_plane/api/v1.py` | 28 | `/protocol`、`/openapi.json`、`/features`(tree/{id}/children/{id}/state/preview/enable/disable/reset/audit)、`/config`(schema/changes/{key}/{key}/preview/{key}/set/{key}/reset)、`/logs`(sources)、`/metrics`(resources/overview/models/sessions/tokens/trends)、`/traces` |
| `control_plane/api/workspaces.py` | 10 | `/workspaces` GET/POST、`/{id}` GET/DELETE、`/{id}/messages` GET/POST、`/{id}/reset`、`/{id}/preview`、`/{id}/send`、`/{id}/audit` |
| `control_plane/api/llm.py` | 9 | `/llm/providers`(批量/单个)、`/channels`(批量/单个)、`/models`(批量/单个)、`/health`、`/routes`、`/routes/preview` POST |
| `control_plane/api/actions.py` | 7 | `/actions`、`/actions/runs`、`/runs/{id}`、`/runs/{id}/cancel`、`/actions/{id}`、`/{id}/preview`、`/{id}/execute` |
| `control_plane/api/health.py` | 4 | `/healthz`、`/health`、`/status/bot`、`/status/models`（前缀 `/admin/api/v1`） |
| `control_plane/api/events.py` | 4 | `""`、`/sources`、`/stream`（SSE）、`/{event_id}`（前缀 `/api/v1/logs`） |
| `control_plane/api/platform.py` | **unknown** | `:40` 动态 `APIRouter(prefix=prefix)`，无装饰器路由被 rg 命中，路由注册方式未深挖 |
| `control_plane/_app.py` | 5 处 `include_router`（`:285,286,341,469,479`） | 挂载点 |

### 2.4 直接出站 / 疑似绕过 SendQueue 路径（V21-DISPATCH-001 / DELIVERY-001 收编清单素材）

**真出站（写路径）**：

| 位置 | API | 初判 |
|---|---|---|
| `__init__.py:4070-4071` | `send_private_msg` | **疑似绕队列**（装配/调度区内直接 bot.call_api） |
| `__init__.py:4878-4879` | `send_group_msg` | **疑似绕队列**（群成员变动通知区） |
| `__init__.py:5175-5182` | `send_group_msg` + `send_private_msg` | **疑似绕队列**（管理命令回复区） |
| `__init__.py:4569` | `delete_msg` | 撤回（dirty guard），设计上非消息投递 |
| `__init__.py:4745,4751` | `friend_poke` | 戳一戳 v2 直发（by design，低风险） |
| `runtime/reactions.py:652-653,681` | `set_msg_emoji_like` | 贴表情（by design 旁路，台账已载"失败静默"） |
| `sender/onebot.py:444,449,469,477,546,554,583,588,962` | `send_*_msg`/`call_api` | **合法通道本体**（SendQueue worker 的 channel 实现，非绕行） |
| `sender/file_gateway.py:382` | `call_api` | Phase-1 文件网关 deliver 直连（是否收编待 DELIVERY-001 裁决） |

**读路径（非出站，仅供甄别）**：`__init__.py:949`(get_forward_msg)、`:1014`(get_record)、`:2059`(get_stranger_info)、`:4924,4928`(get_file/download_file)、`:7468`(get_forward_msg)；`runtime/video_pipeline.py:72,74`(get_msg)；`capabilities/group_info.py:146`（**通用 call_api 透传 sink，动作面宽，建议 DISPATCH-001 单列**）；`sources/telegram_media.py:133`(get_file)；`smoke.py:1283-1474`（mock，非生产）。

### 2.5 计数汇总

| 入口类型 | 数量 |
|---|---|
| NoneBot matcher | **50**（on_message 41 / on_notice 7 / on_command 2 / on_request+on_metaevent 0） |
| 调度族 | **12**（含 __init__:4027/4082 两笔用途 unknown 的裸 add_job）；add_job 调用共 **20** 处 |
| 控制面路由 | **62** 装饰器路由（6 文件）+ platform.py 动态注册 unknown + 5 处 include_router |
| 直接出站写路径命中 | **8 组**（绕队列嫌疑 3 组：__init__:4071/4879/5175-5182；by design 4 组：poke/贴纸/撤回/file_gateway；通道本体 1 组：sender/onebot.py） |

---

## 三、共享热区文件表（多会话高危，当前全部 dirty）

| 文件 | 状态 | 触碰席（判读） | 冲突风险 |
|---|---|---|---|
| `plugins/bot_unified_runtime/__init__.py` | M | campus 席+persona 席+控制面装配+历史批（混合） | **极高**（5000+ 行入口，matcher+调度器+装配三面交汇） |
| `plugins/bot_unified_runtime/capabilities/echo.py` | M | 帮助注册表面（多席追加 topic） | 高 |
| `plugins/bot_unified_runtime/capabilities/chat.py` | M | persona/glossary 席 | 高 |
| `plugins/bot_unified_runtime/config.py` | M | campus+控制面+各批配置键 | 高 |
| `plugins/bot_unified_runtime/runtime/capability_registry.py` | M | 控制面 feature 门批 | 中高 |
| `plugins/bot_unified_runtime/runtime/pipeline.py` | M | 出站收编相关（DELIVERY-001 将动） | 中高 |
| `plugins/bot_unified_runtime/sender/onebot.py` / `sender/worker.py` | M | sender 韧性席（独占中） | 中（属主明确，外来改动危险） |
| `plugins/bot_unified_runtime/control_plane/_app.py` | M | 控制面批（独占中） | 中 |
| `plugins/bot_unified_runtime/output/renderer.py` | M | unknown | 中 |
| `runtime/base_router.py` | **clean**（不在 git status） | — | 低（本席实证：当前无人改） |

---

## 四、风险注记（初步印象，未深挖）

1. **出站三处疑似绕 SendQueue**：`__init__.py:4071`（send_private_msg，调度/装配区）、`:4879`（send_group_msg，群变动通知）、`:5175-5182`（管理命令双通道回复）——V21-DELIVERY-001 收编时的首要核对对象；收编前必须先确认各自幂等/失败语义（unknown）。
2. **`capabilities/group_info.py:146` 通用 call_api 透传**：任意 action 放行面，DISPATCH-001 应单列审计（是只读白名单还是无限制 unknown）。
3. **控制面 `/workspaces/{id}/send` 路由**（`api/workspaces.py:80`）：按规格为隔离工作区"模拟发送"，但其是否绝对不触达生产 SendQueue/通道，静态扫描无法证实（unknown）——接线生产 Runtime 执行门时的红线点。
4. **`__init__.py:4027,4082` 两笔裸 `scheduler.add_job` 用途 unknown**：调度族清单留缺口，接管席应先定位再动调度面。
5. **控制面 `api/platform.py` 路由动态注册未枚举**：protocol 面 62 路由计数不含它，OpenAPI 实际面以 `/protocol` 端点实跑为准（unknown）。
6. **工作树 140+ 项未提交**：五席在飞 + 控制面 V2.1 大批（24 新文件）+ R-18/content_route 批（台账 #35 自述未 commit）同时悬空；任何席位执行 `git add` 类操作前必须按 §一归属表逐文件核对，禁止全量收编。
7. **bot.py 有未归属改动**：进程入口被改但无对应席（unknown），接管时优先 diff 取证。

---

*本文件为 S0 冻结快照，反映 2026-09-17 冻结时刻实况；此后工作树任何变化以 `git status` 实跑为准，不以本文件为准。*

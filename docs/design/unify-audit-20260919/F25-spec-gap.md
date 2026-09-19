# F25 · WebUI 规格-实现差距审计（只读）

> **快照声明**：`date` = **Sat Sep 19 17:09:23 2026**（Git Bash）。本席为「守岸人 Bot」前端波第 25 席（F25），
> 任务是**规格 vs 实现的差距对账**：规格说要做的做到哪了、哪些「写了规格没做」、哪些「做了但规格没写」。
> **只读审计**：全程未改工作树（除本文件）、未起服务、未发任何真实请求、未调用任何控制面写端点、未跑 `npm`/`--write`。
> 所有 python 命令均带 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe ... -p no:cacheprovider --basetemp=$TEMP/f25-*`，
> 且仅 `--collect-only`（不执行测试体，避免写 `data/`）。
> **主规格**=`docs/design/webui-dashboard-spec.md`（55 行）；**次规格**=`docs/design/webui-axonhub-adoption.md`（路线 B，含 §五页面清单 + §八版式宪法）与 `docs/design/webui-pages2-spec.md`（二期三页）。
> **实现**=`webui/src/**`；**后端只读参考**=`plugins/bot_unified_runtime/control_plane/`。
> **诚实前提（MEMORY 实证）**：`webui/` 至今**未进 git**（`git ls-files webui` = **0**，本席复核确认），`dist/index.html` 为他席构建产物。

---

## ① 规格条目判定总表

判定五态：`已实现` / `部分实现（缺哪块）` / `未实现` / `实现偏离规格` / `规格本身已过时`。
「证据」列一律给 `文件:行`，不按页面名猜。搜索过的反证词见「未实现」行的括注。

### Phase A · 只读仪表盘（spec §三 lines 33-42）

| ID | 规格条目（坐标） | 判定 | 证据 / 缺哪块 |
|---|---|---|---|
| A1 | 壳：control_plane 挂单文件 SPA（`vite-plugin-singlefile`），离线可开、零外部 CDN（spec:34） | **已实现** | `control_plane/api/webui.py:98-116`（`build_ui_router` GET `/ui`，未构建→404 `ui_not_built`）；产物 `webui/dist/index.html`（975KB，他席构建）；`webui/vite.config.ts` `vite-plugin-singlefile` |
| A2 | 壳：AxonHub 设计系统抽取（Apache-2.0 路线 B）+ 守岸人主题 token（brand/wash/mica 同源、浅色）（spec:34） | **已实现** | `webui/THIRD_PARTY/axonhub-LICENSE` + `axonhub-frontend-NOTICE`；token 映射=adoption §三；`webui/src/index.css`；wash 取色同源 `domains/render/card_render/theme_tokens.py`（adoption:35-36 声明） |
| A3 | 页面·总览：bot **在线/版本/运行时长/发送队列深度/告警数**（spec:36） | **部分实现** | 在线=`/admin/api/v1/health`（`api/health.py:52`→`dashboard.tsx:93`）、运行时长=`/status/bot`（`api/health.py:72`→`dashboard.tsx:94`）；**版本 / 发送队列深度 / 告警数 三项无只读端点**——页面诚实标「未接入」卡 `dashboard.tsx:203-214`（`/status/bot` 返回体无 version 字段，见 `api/health.py:90-94`） |
| A4 | 页面·调用统计：时间窗(24h/7d/30d)×维度（会话/群内用户 TopN/能力 TopN）+趋势折线（spec:37） | **已实现** | `webui/src/pages/calls.tsx:144-198`（trend LineChart + by_capability/by_session/by_user 三 TopN），端点 `api/webui.py:50` `/stats/calls`；DTO `api-client.ts:241-255` |
| A5 | 页面·Token 面板：四项堆叠（输入/缓存建/缓存命中/输出）×窗×模型族（spec:38） | **已实现（展示面）** | `pages/tokens.tsx:139-163`（recharts `BarChart` + `stackId='tokens'`，四键 `input/output/cache_read/cache_creation`）；端点 `api/webui.py:61`；**数据依赖 A9（账本记录面）** |
| A6 | 页面·延迟：渠道 EWMA **当前值 + 历史曲线**（spec:39） | **部分实现** | 当前 EWMA `pages/latency.tsx`（`/stats/latency`）；**历史曲线无存储**——后端 `LatencyData.history` 恒 `{status:"unavailable",reason:"not_persisted"}`（`api-client.ts:276`），页面诚实「暂无历史」`latency.tsx:87-101`，不画假曲线 |
| A7 | 页面·好感度：排行榜卡（昵称+数值+档位色阶，负值红阶）（spec:40） | **已实现** | `pages/affinity.tsx:13-25`（`tierTone` 档色阶 magenta/purple/brand/info/warn/bad，负值走 warn/bad 红阶），端点 `api/webui.py:85` `/affinity/board`（`score`×100 显数值） |
| A8 | 新后端 API：`GET /api/stats/calls`、`/stats/tokens`、`/stats/latency`、`/api/affinity/board`，只读 SQL 聚合（spec:41） | **已实现**（路径落 `/api/v1/*`） | `api/webui.py:41-95` 四端点全在；信封/降级/422 见同文件；命名带版本前缀 `/api/v1`（spec 写 `/api/`，属版本化收敛，非缺陷） |
| A9 | 前置数据：ledger 开「记录面」（`BOT_LLM_BILLING_ENABLED` 或新增只记账开关），providers 写 usage 四项（spec:42） | **部分实现 / 规格表述过时** | 计价/usage 入 ledger 已接（AGENTS #25 `483f852`），`/stats/tokens` 经 `LedgerMetricsService` 读库（`_app.py:375-379`）；**「新增只记账开关」独立键未在本席搜证域证实**（webui 域内无此键；账本关→`source_unavailable` 空态）。属后端 `llm/` 域，**交后端核实**，前端不擅断 |

### Phase B · 配置在线改（spec §三 lines 44-47）

| ID | 规格条目 | 判定 | 证据 |
|---|---|---|---|
| B1 | SETTABLE 41 键表单化：读 `/api/config`，写 `POST /api/config/{key}` **走 set_override 同一函数路径**（spec:45） | **部分实现 + 实现偏离（命名）** | 后端读=`api/v1.py:147-161` `/config` `/config/{key}` `/config/schema` `/config/changes`；写端点实为 `POST /api/v1/config/{key}/set`（`api/v1.py:167`，非 spec 的 `/{key}`）→ **命名漂移**；写路径经 `config_service.py:135 _write→backend.set_override`，与聊天侧 `RuntimeSettingsStore.set_override` 同函数（**中央路径成立**）。**前端零实现**：搜 `webui/src` 全树 `method:'POST'`/`/config`（页面消费）命中 **0**（`api-client.ts:448-478` `controlApi` 全 GET） |
| B2 | RESTART_REQUIRED 键只读展示 +「生成 .env 片段」复制按钮（spec:46） | **未实现** | 后端读项含 `restart_required` 标（`config_service.py:64`）；`webui/src` 无配置页、无 `.env` 片段/复制——搜 `clipboard|生成.*片段|\.env` 于 src 命中 **0**（仅 plugins 页 `要重启` 徽章 + locales hint 文案，非 .env 生成器） |
| B3 | 模型/渠道只读展示 + 片段生成（表单编辑留 C）（spec:47） | **未实现（UI）/ 后端只读端点已在** | 后端 `api/llm.py:71-111` `/llm/providers|channels|models|health|routes` 只读投影具备；`webui/src` 无对应页（`router.tsx` 九路由无 llm 页）、无片段生成 |

### Phase C · 排队（spec §三 lines 49-50）

| ID | 规格条目 | 判定 | 证据 |
|---|---|---|---|
| C1 | 会话浏览器（history/notes 只读）（spec:50） | **未实现** | `webui/src` 搜 `session-history|会话浏览|notes`（页/端点）命中 **0**；后端亦无只读会话浏览端点（`/memory/graph` 非会话浏览器） |
| C2 | 日志尾流（logs API）（spec:50） | **已实现**（提前于 Phase C 交付） | `pages/logs.tsx` + SSE `api/events.py:131` `/api/v1/logs/stream` + `lib/sse.ts:97`（fetch 流式，非 EventSource）；来源列表 `logsSources` `api-client.ts:465` |
| C3 | 提醒/订阅管理（spec:50） | **未实现** | `webui/src` 搜 `reminder|subscribe|订阅|提醒`（页/端点）命中 **0**；后端无对应只读/管理端点 |

### §四 · 好感度数值展示边界（spec line 54）

| ID | 条目 | 判定 | 证据 |
|---|---|---|---|
| D1 | WebUI 面板**直接显示数值**（用户 2026-09-15 裁定），聊天侧定性口径不变 | **已实现** | `pages/affinity.tsx` 显 `score`（×100）+ `api/webui.py:85`；与聊天侧档位表分列（手册 §6.6.9⑥ 对账见 ⑥ 表） |

### 计数（16 条规格需求项）

| 状态 | 计数 | 条目 |
|---|---|---|
| **已实现** | **8** | A1,A2,A4,A5,A7,A8,C2,D1 |
| **部分实现** | **4** | A3（缺版本/队列深度/告警数）,A6（缺历史曲线数据）,A9（只记账开关未证实）,B1（后端就绪·前端缺） |
| **未实现** | **4** | B2,B3,C1,C3 |
| **实现偏离规格** | 1（叠于 B1） | 写端点 `POST /api/config/{key}/set` ≠ spec `POST /api/config/{key}` |
| **规格本身过时** | 2 | A9 ledger 表述滞后（计价已接）；adoption §五 把 logs 列 Phase A 页面、dashboard §三 列 logs 为 Phase C —— 两规格内部冲突，实盘按页面清单为准（logs 已上线） |

> **主结论**：Phase A 五页只读仪表盘**基本落地**（真数据、诚实降级、无假数）；**Phase B/C 的写面与管理面基本未做前端**（后端 config/features 写路径已在，前端零接线）。

---

## ② 反向缺口表（实盘有、主规格 `webui-dashboard-spec.md` 未写）

判：`规格该补登记` = 功能合理、规格滞后，应回写规格；`实现该收编` = 实现偏离规格意图，应收敛实现。

| # | 实盘存在（证据） | 规格覆盖情况 | 判定 |
|---|---|---|---|
| R1 | **二期三页** knowledge/plugins/memory-graph（`router.tsx:62-95`、`api/webui_ext.py`、`webui_knowledge.py`/`webui_plugins.py`/`webui_memory_graph.py`） | 主 dashboard-spec 无；**`webui-pages2-spec.md` + adoption §五有** | **补登记**：dashboard-spec §三应加指针指向 pages2-spec（读者只读主规格会误判范围） |
| R2 | **SSE 日志尾流**（`api/events.py:131-235`，bounded page + heartbeat + cursor_expired 410） | 主规格仅列「logs API（Phase C）」，无 SSE 语义 | 补登记：adoption §四已提 transport，主规格未同步 |
| R3 | **只读令牌回退**（`webui:bearer:ro`，`api-client.ts:14,84-90`；`_app.py:152 _v1_read_dependency` 双令牌） | 主规格未提双令牌模型 | 补登记（adoption §四有） |
| R4 | **路由错误边界**（`router.tsx:16-26 RouteErrorBoundary key=pathname`） | 两规格均未写 | 收编入规格的「工程/健壮性」节（属正向实现，登记即可） |
| R5 | **i18n 双语** en/zh（`locales/{en,zh-CN}/common.json` 各 288 行对称；`lib/i18n.ts`） | 主规格无本地化条目；adoption §二提基建未提完成度 | 补登记 |
| R6 | **版式宪法机器门纳入 pytest**：`tests/test_webui_constitution.py` 5 例（`test_layout_constitution_gate`/`test_tsc_typecheck_all_projects`/`test_graph_layout_determinism`/`test_package_json_entries_match_gates`/`test_cn_merges_type_ladder_classes`） | adoption §八定宪法但**未写 pytest 常驻接线**；MEMORY「前端三门 pytest 零接线」与现状**冲突** | **现状更正 + 补登记**：门已进 pytest（本席 collect-only 5 例坐实；**本席未运行**——其体含 node/tsc 调用，越界）。MEMORY 那条应更新 |
| R7 | **baseUrl 白名单校验**（同源/127.0.0.1/localhost，防 Bearer 外带，`api-client.ts:51-71`，SECWEB Minor-2） | 规格无 | 补登记（安全面） |
| R8 | **后端 control_plane 写/资源/动作/工作区/占卜/platform 端点群**（详见 ③「后端有」列 ~45 端点） | 主规格完全未提其存在 | **补登记**：规格须显式声明「WebUI = 只读观测面；下列写面为超管专用、默认关闭、前端零接线」，否则接手者误以为 UI 能改生产 |

> 反向缺口共 **8** 条（R1-R6/R8 补登记、R4 收编入规格工程节、R6 兼现状更正）。

---

## ③ 端点缺口表（规格数据面 vs `control_plane/api/*` 实注册）

### 3a. 规格要、后端缺 / 形态不符（这些**前端改不动，须交后端**）

| # | 规格需求（坐标） | 后端实况 | 归属 |
|---|---|---|---|
| G1 | 总览「版本」（spec:36） | `/status/bot` 返回体无 version（`api/health.py:90-94`） | 须后端加只读 version 字段 |
| G2 | 总览「发送队列深度」（spec:36） | 无只读端点；仅 `actions` 写动作 `queue.pause/resume/drain`（`_app.py:424`），无 `GET /queue` | 须后端补只读端点 |
| G3 | 总览「告警数」（spec:36） | 无只读端点（告警在 `runtime/alerts`，未投影到控制面 GET） | 须后端补 |
| G4 | 延迟「历史曲线」（spec:39） | `history` 恒 `source_unavailable/not_persisted`（无时序表；手册诚实缺口 2） | 须后端先落时序表（未立项） |
| G5 | B1 写端点形态 `POST /api/config/{key}`（spec:45） | 实为 `POST /api/v1/config/{key}/set`（`api/v1.py:167`） | 文档/实现二选一收敛（**命名漂移**，非功能缺陷） |
| G6 | C1 会话浏览器 / C3 提醒订阅管理只读端点（spec:50） | 无任何后端端点 | 须后端立项（Phase C 未启动） |

### 3b. 后端有、规格/前端未用（前端不改，登记为「后端过剩/未接线面」）

来源：`control_plane/api/` 路由注册逐文件核对（`v1.py` / `webui.py` / `webui_ext.py` / `events.py` / `health.py` / `actions.py` / `workspaces.py` / `llm.py` / `platform.py` / `divination.py`），挂载见 `_app.py:312-621`。

| 组 | 端点（节选） | 读/写 | 被前端用? | 被规格写? |
|---|---|---|---|---|
| health | `/admin/api/v1/status/models` | R | 否（前端用 `/stats/latency` 替代） | 否 |
| protocol | `/api/v1/protocol`、`/openapi.json` | R | 否 | 否 |
| features | `/features` `/features/tree` `/features/{id}[/children|/state|/audit]` + **POST preview/enable/disable/reset** | R/**W** | **否** | **否** |
| config | `/config[/schema|/changes|/{key}]` + **POST {key}/preview|set|reset** | R/**W** | **否** | B1（形态漂移 G5） |
| logs | `GET /logs`、`GET /logs/{event_id}` | R | 否（用 stream） | 部分 |
| metrics | `/metrics/{overview,models,sessions,tokens,trends,resources}` | R | 否 | 否 |
| traces | `GET /traces`（503 stub `api/v1.py:229`） | R | 否 | 否 |
| actions | `/actions[/runs|/runs/{id}]` + **POST cancel/preview/execute** | R/**W** | **否** | **否** |
| llm | `/llm/{providers,channels,models,health,routes}` + **POST routes/preview(读), models/{id}/test, config/preview, config/apply, cache/reload** | R/**W** | **否** | B3（只读部分） |
| workspaces | `/workspaces` CRUD + `[/messages|/preview|/send|/reset|/audit]`（`api/workspaces.py`） | **W(含 GET)** | **否** | **否** |
| platform | `/api/v1/{persona-profiles,worlds,worldbooks,references,knowledge-bases,memories,databases,media-capabilities,file-capabilities,search-providers}` GET/**PUT** + lifecycle `draft/publish/rollback/activate` + **POST logs/level,traces,usage,model-calls,reindex,rebuild,memories approve/reject/forget,files/read,media/analyze** + GET `traces/usage/model-calls/search/jobs/capabilities`（`api/platform.py`） | R/**W** | **否** | **否** |
| divination | `/api/v1/divination/*`（capabilities/draws/fortune/tarot/bazi/interpretation/config）（`api/divination.py`） | R/**W(draw)** | **否** | **否** |

> 端点缺口：3a **6 条**（须后端）+ 3b 约 **45+ 个后端端点**（写面/资源面）规格未登记、前端未用。

---

## ④ 「UI 能否改变生产行为」判定表（用户最在意的中央指令落点）

**核心裁决**：**已交付的 WebUI 前端（`webui/`）是纯只读观测面，自身改变不了任何生产行为。**
「改变生产行为」的能力全部活在**后端 control_plane 写端点**里——规格未登记、前端零接线，且受**三重门**（缺省 `bot_control_plane_enabled=False` → 整面不启动；写须 super_admin **独立**令牌，读写令牌相同则写禁 `_app.py:299-306`；Host 白名单 `_app.py:695-717`）。

| # | 入口 | 坐标 | 前端是否接线 | 真生效 / 恒 503 / 诚实降级 | 判定依据 |
|---|---|---|---|---|---|
| U1 | 九个前端页面 + `controlApi` 全部 | `api-client.ts:448-478` | 全是 GET | **只读，不改生产** | 无 `method:'POST'` 调用（grep src 命中 0） |
| U2 | 设置对话框 | `settings-dialog.tsx:56-69` | — | **仅写 localStorage**（baseUrl/token），刷新即 reload，**不触后端** | 只调 `setBaseUrl/setApiToken`（本地），无网络写 |
| U3 | 功能开关 启/停 | `api/v1.py:126-136` POST enable/disable；写门 `_app.py:560` | **否** | **真能生效（若控制面附宿主运行）**：写 SQLite feature store，运行时 `ProductFeatureGate` 读同一 `FeatureControlService` 并在 Pipeline 处拦截能力（`__init__.py:3731`、`pipeline.py:484-488`、`feature_gate.py:53-62`） | **改生产派发行为**；`RECOVERY_CAPABILITIES` 白名单旁路保护 |
| U4 | 配置在线改 | `api/v1.py:167-173`；`config_service.py:135` | **否** | **真能生效**：`set_override` 与聊天侧 `/bot runtime` 同函数（**中央路径成立**）；仅 SETTABLE 热更，RESTART 键拒 409（`config_service.py:48`） | 走同一中央 set_override，非 UI 旁路 |
| U5 | 动作下发 execute | `api/actions.py:54`；`_app.py:401-472` | **否** | **分档**：`logging.level`/`resources.refresh`/`napcat.status`/`queue.pause|resume|drain` **真生效**（宿主注入 send_queue+probe `_app.py:424,441`；standalone `serve()` 则 queue/napcat **degraded**）；`runtime.safe_restart`/`adapter.reconnect`/`llm.routes.reload`/`knowledge.reindex`/`memory.maintenance` 走 fall-through **`degraded adapter_not_connected`（`_app.py:466-472`，注册但不执行）** | 部分是**空壳动作**，须真机+宿主注入才生效 |
| U6 | 平台日志级别 setter | `api/platform.py:144-169` POST `/logs/level` | **否** | **真生效**：`_apply_platform_log_level`→`logging.getLogger().setLevel`（`_app.py:37-48`）；setter 自报失败/未装配如实 `applied=false`（V21-risk-3） | 读依赖即可达？否——`write_dependency`（`platform.py:146`）超管 |
| U7 | 平台资源 CRUD / lifecycle | `platform.py:95-100`（PUT）、`:258-267`（publish/rollback/activate） | **否** | 写 PlatformStore（人格/世界观/记忆库）→ **潜在改生产人格面**；`databases/health|stats` 恒 `unknown`（`:341,351` 诚实） | 超管写门；前端不用 |
| U8 | 媒体分析 / 文件读 / 搜索 | `platform.py:382,354,451`（**read_dependency 的 POST/GET 副作用**） | **否** | **真触发 VLM/ASR/web provider = 成本支出**；`files/read` 读任意工作区相对文件（cwd 内穿越护栏 `:365`）；`config=None` 时 media 恒 503（`:389`） | **注意**：这三个是**只读令牌即可驱动的副作用面**（非中央写门），属**旁路面**（缺陷记账） |
| U9 | 隔离工作区 send | `api/workspaces.py:80`；`factory.py:105` | **否** | **沙箱模拟、非生产发送**：`sandbox_generate` 建临时会话适配器；协议 `workspaces.real_session=real_adapter is not None`，宿主挂载未传 real_adapter → **false**（`api/v1.py:74-75`） | 不落生产 QQ 出站 |
| U10 | LLM 配置 apply / cache reload | `api/llm.py:150-163` | **否** | 写经 `config_service`（同 set_override 中央路径）；`models/{id}/test` **live 模式恒 503 `not_configured`（诚实不装真调）** `llm.py:131` | 中央层收敛 |
| U11 | 占卜 draws | `api/divination.py:141` POST `/draws`（**read_dependency**） | **否** | 写 draw_store（额度扣减，`interpretation` 恒 503 `not_wired` `:202`）；facade 未配持久化路径→**503 诚实** | 记数据不改机器人行为；但读令牌即可 POST，需额度门（服务层） |

### 中央统一「先经中央指令再派发」在 UI 层的落点裁决

- **配置层 / 功能层成立**：U3/U4/U10 写路径与聊天侧共用同一 `FeatureControlService` / `RuntimeSettingsStore.set_override`，**UI 无旁路**（因为 UI 根本不发写请求）。规格里 Phase B「走 set_override 同一函数路径…与聊天侧完全一致」（spec:45）**已被后端兑现**。
- **观测层成立**：九页全经统一信封（`envelope`+双令牌读依赖），单一真相源。
- **派发层的隐患（缺陷记账，非 UI 之过）**：U8（media/files/search 挂在**只读令牌**下的副作用端点）与 U5/U7 的 platform 资源面构成**绕开「超管写门」的第二入口**——这是「中央自身多份实现/旁路」形态，应并入 control-plane 写依赖或显式标权限。
- **总账**：WebUI 作为**已交付形态**是「只读观测面」这一命题**为真**；改变生产行为的中央写面在后端、默认关闭、前端未接线、且部分动作/端口为诚实空壳。

---

## ⑤ 下一波次建议清单（≤10，按用户可见价值×成本，带归属）

| 序 | 事项 | 归属 | 说明 |
|---|---|---|---|
| 1 | **Phase B 配置表单页**（SETTABLE 键读+写 `/config/{key}/set`，走中央 set_override）+ RESTART 键只读标 | **前端可自闭环**（后端端点已在）+ 需真机验证热改 | 唯一「规格明文要做、后端已备、前端全缺」的高价值项；须 super_admin 令牌 |
| 2 | **总览补版本/队列深度/告警数三块** | **须后端**（G1/G2/G3 无只读端点）→ 前端再接 | 否则总览卡永远三枚「未接入」 |
| 3 | 若做「生成 .env 片段」复制按钮（B2/B3） | **前端自闭环**（纯本地 clipboard，无需后端） | spec:46-47 明文；当前 `clipboard` 命中 0 |
| 4 | **主规格↔pages2-spec↔adoption 三文档对账收编**：dashboard-spec 补登二期三页/SSE/双令牌/宪法门；修 logs 的 Phase A/C 归属冲突 | **文档（前端域可自闭环）** | R1/R2/R8 + A9 过时 |
| 5 | **U8 只读令牌副作用面收权**：`media/analyze`/`files/read`/`search`/`divination/draws` 改挂写依赖或显式额度门 | **须后端**（control-plane），前端无关 | 「中央指令」纪律落点；本席只判定不改 |
| 6 | **延迟历史曲线**（spec:39 要求） | **须后端**（先落 EWMA 时序表，G4）→ 前端加 Area 图 | 未立项，成本中高 |
| 7 | **Phase C 会话浏览器/提醒订阅管理** | **须后端**（端点全缺）+ 前端页 | spec:50，Phase C 排队中，价值待用户排 |
| 8 | 前端三门（tsc/layout/graph）确认在 `dev.ps1 -Task test` 常驻且**缺 node 即 FAIL**（承 MEMORY 裁定） | **前端/门禁可自闭环**（R6 显示门已进 pytest） | 本席未运行其体（含 node），交前端域实跑 |
| 9 | **`webui/` 纳入 git**（逐文件显式 add，禁 `add -A`） | **须用户裁决**（提交权在用户，AGENTS 铁律 4） | 单机唯一副本，任何 `git clean`/误删即整体丢失（MEMORY 高危事实，本席复核 `git ls-files webui`=0） |
| 10 | 真机/重启验收：§6.6.9①-⑦、⑨-㉑ 全链 | **须真机/重启**（起独立 control_plane 进程 + 双 token + 浏览器） | 本席只读不可复跑 |

> **前端可自闭环**：1(部分)、3、4、8；**须后端配合**：2、5、6、7；**须真机/重启**：1(验)、2、10；**须用户裁决**：9。

---

## ⑥ 验收手册对账（`docs/acceptance-manual.md` §6.6.9 / §6.6.10）

### 与实盘对不上的「手册滞后」项

| # | 手册原文（行） | 实盘实况 | 判定 |
|---|---|---|---|
| ⑧ | 「侧边栏**六项**导航（总览/调用统计/Token/延迟/好感度/日志）」（acceptance:398） | `app-shell.tsx:46-56` **九项**（+知识库/插件/记忆图谱） | **手册过时**：二期三页已并入导航，⑧ 文字未更 |
| ⑨ | 「总览三统计卡若仍带 **mock 徽章**…（非缺陷）」（acceptance:399） | `dashboard.tsx:203-214` 已无 mock 徽章卡，改**诚实「未接入」卡** | **手册过时**（实现更好）；「mock 徽章演示卡为唯一例外」的表述（㉑，acceptance:422）同样失效 |
| ③ | stats/calls「生产 `bot_audit_db_path` **默认空=内存实现无数据**（空态预期）」（acceptance:393） | 复核：`config.py:202` `bot_audit_db_path: str = ""` 确为空 | 手册**与实盘一致**（此条不误，列此为澄清） |
| ⑤ | latency `history` 恒 `{status:"unavailable",reason:"not_persisted"}`，页面历史曲线无数据=预期（acceptance:395） | `api-client.ts:276` DTO + `latency.tsx:91-101` 一致 | **一致** |

### 「手册写了但本轮无法复跑」的项（只读纪律 + 未起服务）

| 手册验收项 | 触发依赖 | 本轮可复跑? | 离线替代证据 |
|---|---|---|---|
| §6.6.9 ①-⑦（/healthz、protocol、四统计端点、鉴权矩阵） | **独立 control_plane 进程 8742 + 双 token** | **否**（禁起服务/占端口/发真实请求） | 端点存在性由源码坐实（`api/webui.py`、`api/health.py`） |
| §6.6.9 ⑧（/ui 壳浏览器打开、暗色切换、断网可开） | 运行控制面 + 浏览器 | **否** | 壳路由 `api/webui.py:101`；产物 `webui/dist/index.html` 存在 |
| §6.6.9 ⑨⑩（五页+日志尾流【待真机】、SSE 滚动/重连） | 真机 + QQ 侧触发事件 | **否**（手册已自标【待真机】） | — |
| §6.6.9 二期三页 ⑪-㉑ | 真机 control_plane **或** `scripts/webui_mock_server.py` + 浏览器 | **否**（禁起 mock server / 占 8743） | 端点+服务层源码坐实 |
| 计数类宣称（stats 53 例、三新文件 55 例、control_plane 族 290/406 passed、8532P 等） | 全量实跑 | **部分**：本席 `--collect-only` 复算得 stats **58**、http **6**、knowledge **27**、plugins **18**、memory_graph **21**、constitution **5**（合计 **135**） | **手册宣称数与当前树漂移**：53→58、55(=27+18+21=66)；「290/406 passed」为他席快照，本席未复跑，只报 collect 计数 |

> **手册写了但本轮完全无法执行**：§6.6.9 ①-⑦、⑧、⑨-⑩、⑪-㉑（全需 live 控制面进程 / mock server / 浏览器）；离线**仅** `pytest --collect-only`（135 例存在性）可复跑，§6.6.10（渲染批 11 面）属**渲染域**非本席 WebUI 面，未展开。

---

## 附：本席「未实现」结论的搜证口径（诚实红线）

- Phase B/C 前端写面「未实现」：`Grep webui/src` 搜 `method:|POST|/config|/features|/actions|/workspaces|apiRequest<|fetch\(` → `controlApi`（`api-client.ts:448-478`）全为 GET 端点，唯二 `fetch` 为 GET（`apiRequest` 默认 method GET，`lib/sse.ts:97` logs stream GET）；命中 0 处写调用。
- B2/B3「.env 片段生成」未实现：`Grep webui/src` 搜 `clipboard|生成.*片段` → 0（仅 `placeholder`/settings 文案）。
- C1/C3 未实现：`Grep webui/src pages` 搜 `session-history|提醒|订阅|reminder|subscribe` 页面/端点 → 0（`router.tsx` 九路由固定，无此类页）。
- 规格 logs Phase 冲突：`webui-dashboard-spec.md:50`（Phase C）vs `webui-axonhub-adoption.md:114`（§五 Phase A 第 6 页）——两处口径不一致，实盘 logs 已上线（`pages/logs.tsx`）。
- **未运行**：`webui_acceptance.py`（需起服务）、`npm run build`、`layout-constitution.mjs`/`tsc`/`node --test`（test_webui_constitution 测试体，含 node 工具链）、任何控制面端点——均属越界动作，本席只读判定不下「已生效」结论。

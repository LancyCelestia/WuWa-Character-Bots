# F2 前端↔控制面契约审计（WebUI API Contract Audit）

> **快照声明**：取值 `Sat Sep 19 16:07–16:31 +08 2026`（`date` 实跑）。本审计**只读零修改**；`webui/` 与渲染域可能被其他会话并发改写，**全部行号仅为快照**，每条发现附可 grep 锚点字符串。审计期间实证并发：`webui/src/hooks/use-async-queries.ts` 在 16:07 首扫时在册、16:25 复查时已被并行会话删除（孤儿钩子清理事件，本文件按"现存=仅 `use-semantic-query.ts`"记账）。本报告不采信项目宣称，一切以代码与实跑证据为准。
>
> **零污染自证**：本报告为该目录内本席唯一新建文件；定向 pytest 带三件套（`--basetemp=$TEMP/f2-webuihttp-20260919 -p no:cacheprovider`，6 passed/7.15s 实跑），未跑 `npm build/install/tsc -b`（`tsc -b` 会写 `node_modules/.tmp`，属禁改面，故类型门强度按配置+人工核读判定并如实披露）；复查源码树无本席造成的 `__pycache__/.pytest_cache/data/`。

## 0. 执行摘要与宣称核验

| 宣称 | 判定 | 证据 |
|---|---|---|
| 一期六页 + 二期三页「真数据」 | **代码层成立**：12 个前端请求全部打到真实路由，服务端全部只读真实 SQLite/ledger（URI `mode=ro`+`query_only`）；无前端硬编码假数据 | `webui_stats.py:126-225`、`webui_ext.py` 全文、§1 对照表 |
| `legacy health/status/models 三端点已 mock 化` | **口径属实但易误读**：mock 化的是**离线夹具服务器**（`scripts/webui_mock_server.py` 自述 "legacy 裸体；mock 恒回组件全 ok"），真实三端点是活实现（`api/health.py`）；前端消费其中两个真端点 | `webui_mock_server.py:20,424,1398-1410` |
| `webui_acceptance.py 9 页 9 PASS 双轮` | **判定实为**：一轮=mock 8743（数据态）+ 一轮=死端口 8749（**降级态也算 PASS**）；真实 8742 一轮**自认未跑**（窗口内控制面下线）。且脚本 `--api` **默认值就是 mock 端口 8743** | `progress-UIACC.md:12-14,26`；`webui_acceptance.py:346` |
| 统一信封 + 前端统一解包 | **成立**：手搓 `payload.data.data.x` 解包点 **0 处**（穷举法见 §2）；但存在两处「宽容兜底把未知形态当 ok」风险（F2-08） | `api-client.ts:115-118,208-219` |
| 任务简报假设的 settings/stats 页 | **不存在**：`webui/src/pages/` 实存 9 页（find 全列）；settings 仅为对话框组件，stats 拆为 calls/tokens/latency | 快照实测 |

**总计**：P0=0｜P1=3｜P2=11｜P3=6。端点对照四类缺口：①假真数据 0（条件性降级均如实）②前端零消费 ~94 ③前缀/鉴权/信封差异 2 处点名 ④同名双 schema 1 组（`/logs/sources`，含真崩溃路径）。

---

## 1. 端点穷举对照表

### 1.1 前端全部请求函数（`webui/src/lib/api-client.ts` 全文核读，12/12 无遗漏）

| # | 路径 | 方法 | 参数 | 返回类型（TS） | 消费者 | Bearer | 后端真身 | 判定 |
|---|---|---|---|---|---|---|---|---|
| 1 | `/admin/api/v1/health` | GET | — | `HealthData` | dashboard.tsx:93 | 主→只读回退 | `api/health.py:52`（真实现） | ✅ |
| 2 | `/admin/api/v1/status/bot` | GET | — | `BotStatusData` | dashboard.tsx:94 | 同上 | `health.py:72`（真实现） | ✅ |
| 3 | `/api/v1/stats/calls` | GET | `window/bucket/limit` | `CallsData` | dashboard.tsx:95,97；calls.tsx:94 | 同上 | `api/webui.py:50`→`AuditCallStatsService`（审计库真读） | ✅（未配 `bot_audit_db_path` 时**恒 source_unavailable**，UI 如实「暂无数据」，非假真数据） |
| 4 | `/api/v1/stats/tokens` | GET | `window/limit` | `TokensData` | dashboard.tsx:98；tokens.tsx:77 | 同上 | `webui.py:61`→`LedgerMetricsService.token_families`（账本真读；未接线=信封内诚实降级） | ✅ |
| 5 | `/api/v1/stats/latency` | GET | — | `LatencyData` | dashboard.tsx:99；latency.tsx:53 | 同上 | `webui.py:78`→`latency_view(channel_health_store)`（进程内真单例；独立冒烟启动=not_connected 如实） | ✅ |
| 6 | `/api/v1/affinity/board` | GET | `limit/order` | `AffinityBoardData` | affinity.tsx:68 | 同上 | `webui.py:85`→`AffinityBoardService`（`user_affinity` 真读） | ✅ |
| 7 | `/api/v1/logs/sources` | GET | — | `LogsSourcesData` | logs.tsx:68 | 同上 | **双实现**：`events.py:119`（4 字段）/ `v1.py:184`（fallback 仅 items） | ⚠ F2-06 |
| 8 | `/api/v1/knowledge/collections` | GET | — | `KnowledgeCollectionsData` | knowledge.tsx:91；app-shell.tsx:58 | 同上 | `webui_ext.py:36` | ✅ |
| 9 | `/api/v1/knowledge/terms` | GET | `collection/q/page/page_size` | `KnowledgeTermsData` | knowledge.tsx:117 | 同上 | `webui_ext.py:43` | ✅ |
| 10 | `/api/v1/plugins` | GET | — | `PluginsCatalogData` | plugins.tsx:147 | 同上 | `webui_ext.py:65` | ✅ |
| 11 | `/api/v1/memory/graph` | GET | `window/max_nodes`(前端恒 200) | `MemoryGraphData` | memory-graph.tsx:45 | 同上 | `webui_ext.py:83` | ✅ |
| 12 | `/api/v1/logs/stream` | GET(SSE) | `source/category`(游标走 `Last-Event-ID` 头) | 帧流 `LogEventRow` | logs.tsx 经 `lib/sse.ts:97` | 手工附 主→只读 | `events.py:131` | ✅ 契约细节见 §5 |

**计数自证**：`grep -c "" /dev/null; grep -n "apiRequest<\|logsStreamUrl(" webui/src/lib/api-client.ts` → 12 命中；`grep -rn "fetch(" webui/src --include="*.ts" --include="*.tsx"` → 恰 2 个网络出口（`api-client.ts:169`、`sse.ts:97`），**无页面绕过 api-client 直连 fetch**。前端函数零闲置（12/12 均有消费者）。

### 1.2 四类缺口点名

**① 前端调、后端不存在/恒 503/恒 mock —— 0 条**。全部 12 路径在现行 `create_control_plane_app` 装配链上真实注册（`_app.py:312-621` 逐 router 核读）。两个**条件性缺口**如实记录（非欺骗）：stats/calls 依赖 `bot_audit_db_path` 配置、tokens 依赖账本接线——缺席时后端回 200+`source_unavailable`，前端渲染「暂无数据」。**对旧版进程**（无 Phase B 路由的前一版控制面在跑），knowledge/plugins/memory 三组会 404——前端用字符串嗅探特判成「未部署」提示（见 F2-07，机制脆弱但意图诚实）。

**② 后端有、前端零消费（死端点）—— 106−12≈94 条**（计数命令：`grep -rn "@router\.\(get\|post\|put\|patch\|delete\)(\|@r\.\(get\|post\|put\|patch\|delete\)(" plugins/bot_unified_runtime/control_plane/api/*.py | wc -l` → 实跑 **103**，其中 `platform.py:122` 循环一行展 4 → 106；`v1.py:176,184` 两条与 events 路由互斥）。分组点名：
- `health.py:35` `/healthz`；`health.py:96` **`/admin/api/v1/status/models`（唯一"宣称面"相关死端点：渠道健康 legacy 投影，前端用 `/api/v1/stats/latency` 替代）**
- `events.py:90,237` `/api/v1/logs`（列表分页）与 `/api/v1/logs/{event_id}`（详情）——前端只做流式
- `v1.py` 28 条：protocol/openapi/features×11/config×8/metrics×6/traces-stub
- `api/actions.py` 7、`api/llm.py` 12、`api/workspaces.py` 9、`api/divination.py` 9（前缀 `/api/v1/divination`）、`platform.py` 22（traces×7/usage/model-calls/logs-level/knowledge-bases×2/memories/jobs/databases×3/files/media/search/capabilities）
判定：绝大多数为 V2.1 后续阶段写面/平台面，**属路线图预留而非缺陷**；但前端↔这套 94 条零耦合、零代码生成，放大 F2-14（漂移无锁）。

**③ 路径前缀混用与鉴权/信封差异（2 处实质点）**
- `/admin/api/v1/*`：**裸 dict 无信封** + **只认 `BOT_CONTROL_PLANE_TOKEN_SHA256`**（`_app.py:313-321` 挂 `_auth_dependency`）；`/api/v1/*`：统一信封 + 双令牌皆收（`_v1_read_dependency`，`_app.py:152-180`）；`/ui`、`/healthz` 无鉴权。前端用 `unwrapEnvelope`「有 data 才解」吸收差异——设计自洽，但见 F2-11（token 槽命名错位 + 缺席面聚合阻塞）与 F2-16（dev proxy 只覆盖 `/api/v1`，`vite.config.ts:18-24`——开发模式总览两张 admin 卡必红）。
- Host 白名单后端默认仅 `127.0.0.1/localhost`（`_app.py:103`），前端 `LOOPBACK_HOSTS` 与之同缺 `::1`（见 §6）。

**④ 同名端点前后两套 schema —— 1 组会伤前端**：`GET /api/v1/logs/sources` 双实现形态漂移（events 版 `{items:14 源, categories:7, collector_status, collectors}` vs v1-fallback 版 `{items:10 源}` **无 categories**、且 10 源名单落后于 `EVENT_SOURCES`——`events.py:42-57` 比对）→ 未配 events db 的实例上 LogsPage 渲染期 TypeError（`logs.tsx:176,264`），详见 F2-06。次级：`GET /api/v1/logs` 列表双形态（page{items,next_cursor,has_more} vs {items,source}）前端零消费不受伤；`/api/v1/traces` stub-503 与 platform 真实现同路径双注册（`v1.py:229` 注释自述 RK5 以 operation_id 消歧，注册序 platform 先）——后端内部，前端不受伤，登记备查。

---

## 2. 信封解包一致性

**统一性总体成立**：外层解包 1 处（`api-client.ts:115-118 unwrapEnvelope`）→ 内层语义 1 处（`api-client.ts:208-219 resolveSemantic`）→ 状态归一 1 处（`use-semantic-query.ts:54`）。**手搓 `payload.data.data.x` 解包 = 0 处**（穷举：`grep -rn "\.data\.data" webui/src` 零命中；9 页 + app-shell 全文核读，无页面直调 `apiRequest`）。`source_unavailable` 经 hook 归一为 `unavailable` 态 → `SemanticState` 统一呈现，reason 文案表集中于 `semantic-state.tsx:16-39 reasonKey()`（18 码，与 `locales/*/common.json reason.*` 18 键**双向零缺漏**，脚本比对实跑 zh-only=[]/en-only=[]）。

残余不一致（逐条进 §9）：404 特判嗅探 ×3（F2-07）、未知形态当 ok ×2（F2-08）、重试策略两套（F2-09）、错误码→文案「集中」仅限 reason 面（HTTP 错误仅 message 文本透出，`ApiError.code/status` 在 hook 处被丢弃）。

---

## 3. 可空性与「不造数」——全树穷举

`grep -rn "?? 0\|??0" webui/src --include="*.ts*"` 命中 **15 行**，逐行判定：

| 坐标 | 内容 | 判定 |
|---|---|---|
| `pages/dashboard.tsx:184` | `formatInt(tokensData.totals?.calls ?? 0)` | **造数**（旧后端缺 totals→显示 0 而非「—」）= F2-04 |
| `pages/dashboard.tsx:187`（行内 2 处） | `tokens.input.value ?? 0`、`output.value ?? 0` | **造数**（`TokenBlock.value: number|null`，null=未知显 0；tokens 页同字段显「—」→ 两页口径相反）= **P2-11 核为真、现行未修**（F2-04） |
| `pages/logs.tsx:187` | `statusInfo.attempt ?? 0`（i18n 参数） | 豁免：仅 reconnecting 文案插值 |
| `pages/memory-graph.tsx:222` | `degrees.get(…) ?? 0` | 豁免：图论度数，0 语义正确 |
| `components/graph/memory-canvas.tsx:106,160`；`lib/graph-layout.ts:51,52,85,107,108,109,110,123,124`（11 处） | 布局几何兜底 | 豁免：内部坐标，非后端可空字段 |
| `pages/tokens.tsx:157` | `formatInt(Number(value))`（recharts Tooltip） | **造数**（`Number(null)=0`——null 块 tooltip 显 0；NaN→`formatInt` 有 '—' 守卫，null 无）= F2-05 |

`|| 0` 零命中；`.length` 前不判空：`knowledge.tsx:45 item.aliases.length`（后端各集合恒发数组，`webui_knowledge.py:241,284,386,465,487` 逐路核到——暂安全，无锁）。裸属性访问无 phase 守卫 = 0（9 页均以 `phase==='ok'` 收口，但见 F2-08：ok 本身可能承载 `undefined`）。其余显式判空示范：`tokens.tsx:61,190`（`value===null?'—':…`）、`latency.tsx:30,33`、`dashboard.tsx:70,74`（`active_users!=null`、`last_message_at?…:'—'`）——**同语义在 tokens/latency/dashboard 详情组做对、在 dashboard 汇总卡做错**，恰证「同一字段两口径」。

---

## 4. 时间与数字格式化口径

单源部分：`lib/format.ts` 6 函数（formatInt/formatMs/formatUptime/formatDateTime/formatTime/formatBucket）+ `patterns.tsx:127 Pager`（唯一分页实现，仅 knowledge 消费）——集中、页面不自建。**后端时间戳全 ISO-UTC**（`events.py` created_at、`webui_stats.py:207`、`protocol.py:39`），前端 `new Date().toLocaleString('zh-CN')` 本地化显示——私用工具面板属可接受惯例，但有一处口径矛盾：

- **F2-10**：`calls.tsx:152` 文案直出后端 `trend.timezone="UTC"`（`webui_stats.py:215`），而轴标签 `formatBucket`（`format.ts:41-48`）按**浏览器本地时区**渲染 → 描述说 UTC、刻度是本地钟面（UTC+8 下整移 8 小时），同页两口径。
- 内联散落（P3=F2-17）：`affinity.tsx:48-49 score.toFixed(1)`+正号逻辑内联；`memory-graph.tsx:230 {selectedNode.weight}` 裸数直排（不判位数）；`logs.tsx:191 Math.floor(heartbeatAge/1000)` 相对时间唯一实现（全树仅此一处相对时间，暂无第二套可对照）；`calls.tsx:197` 后端码 `derived_from_session_id_onebot_convention` 魔法串硬编码三元。
- `compactNumber`（`format.ts:50`）**零调用死代码**；货币/字节格式：前后端均无该语义字段进 UI（账本成本未投影到 stats 面），**未找到**同类实现——无两套问题。

---

## 5. SSE 契约

帧格式前后端逐字段对表（`events.py:66-73 _frame` vs `sse.ts:142-198`）：`id:` 游标✓ `event: log|error`✓（默认 `message` 分支容错）`data:` JSON 信封 `record.data`✓ 心跳 `: heartbeat`→`onHeartbeat`✓；`Last-Event-ID` 优先于 `after` 两端同注释同实现（`events.py:142-143` / `sse.ts:91-92`）；410→HTTP 与流内 `cursor_expired` 帧双路皆**停自动重连+等用户显式 resubscribe**，与服务层明文约定一致（`events.py:110-113,194-204`；前端 `sse.ts:106-111,157-161`）。游标经 `sessionStorage webui:logsCursor`（per-tab，`logs.tsx:116,134`）跨页面挂载续传，与 header 回传闭环。**重放不清 rows＝核实为真，现行未修**：

- **F2-01（P1，复核 2026-09-19 审计 P1-4）**：`logs.tsx:165-168 resubscribe()` 与 `:170-173 applyFilters()` 都只 `sessionStorage.removeItem(CURSOR_KEY); startStream(null)`——**不清 `rows`**。服务端随后从保留窗口最旧重放（`events.py:232` docstring：after=None=oldest available），旧行仍在 → 同 `cursor` 行重复追加（React `key={row.cursor}` 撞 key、视觉重复行；改过滤器时旧未过滤行与新过滤行混排）。修法：`startStream` 首行 `setRows([]); setDroppedCount(0);`（backlogRef 同清）。无回归锁。
- **F2-12（P2）**：连接期 HTTP `503` 被归入「鉴权/参数类不重试」名单直接 `auth_error` 终态（`sse.ts:113-118`），而**流内** `events_unavailable`(=同一 503 语义) 却退避重连（`sse.ts:163-165`），且 119 行注释自称「429/5xx 抖动退避重连」与实现矛盾——后端 503 标记 `retryable=true`（`protocol.py` error_body 经 `_app.py:640`）。事件库瞬时抖动恰在重连窗口最常命中 503 → 流一断到底，用户须手点「连接」。
- 余注（不立项）：`heartbeat` 查询参数前端从不传（吃后端默认 15s，前端 45s 陈旧线自洽）；错误帧无 `id:` 不污染游标；畸形帧静默丢弃与「缺口须显式复订」约定不冲突（游标仍推进）。

---

## 6. baseUrl / Origin / 凭据面

- **回环白名单现行实态**：`api-client.ts:42 LOOPBACK_HOSTS = {'127.0.0.1','localhost'}`——**`::1` 仍缺（审计旧记属实、未修）**；但属 HARDEN 席**明文设计裁量**（`progress-HARDEN.md:45`：`[::1]` 与 https 回环一并裁掉，与 Host 白名单后端同口径 `health…_app.py:103`）。列 P3=F2-15。scheme 校验 `http(s)`✓；userinfo 欺骗防（`hostname` 归一）注释与实现相符✓；同源旁路 `window.location.hostname` 比对✓。
- **实施判定（非只测试断言）**：`validateBaseUrl` 被 `setBaseUrl`（:79）**和** `settings-dialog.tsx:57` 保存路径双重调用（纵深真落地）；CSP meta 在 `webui/index.html:8-13`，且 **dist 产物中实存**（`grep -o "connect-src [^;\"]*" webui/dist/index.html` → `connect-src 'self' http://127.0.0.1:* http://localhost:*`）。但「9 用例 9 PASS」验证脚本系**一次性临时 playwright 件已删**（`progress-HARDEN.md:37`）→ 无常驻锁 = F2-18（P3）。
- **Bearer 存放与去向**：localStorage `webui:bearer`/`webui:bearer:ro`（:13-14），仅进 `Authorization` 头（REST `apiRequest:159`、SSE `sse.ts:90`），**全树零 token 进 URL/query**（qs() 参数表不含令牌，logsStreamUrl 只带 filter）✓。CSP 压缩 XSS 半径 + 令牌明文永不出页面（对话框保存后清空、password 型输入）。残余：localStorage 不可用时静默丢配置（`storageSet:24-31` 注释自述，P3 并入 F2-15 披露）。
- **F2-11（P2）鉴权面错位**：对话框标签「主令牌（读写）」= 后端 `token_sha256`（`Principal` 角色恒 `admin`，**并无写能力**——写要 `super_admin` 另一槽）；「只读令牌」在后端**无独立槽位**。后果：仅持 super-admin 令牌的操作者把它填进「主」槽 → `/admin/api/v1/health|status/bot` 恒 401（`_auth_dependency` 不收 super）→ dashboard.tsx:102-112 把 health/status-bot 列进**阻塞聚合名单**，**整张总览页**（含本可工作的 /api/v1 六卡）一并「令牌无效」；填进「只读」槽则经 :158 回退同样 401。两套前缀两套令牌语义，前端单一下拉双回退吸收不了（修法见 §9）。
- **F2-03（P1）保存即清令牌**：`settings-dialog.tsx:64-65` 无条件 `setApiToken(adminToken…)`，`api-client.ts:88-90` 空串→`removeItem`；而对话框打开即 `setAdminToken('')`（:41-42）且占位「已保存（粘贴新值可覆盖）」**反向暗示**留空=保留。改 baseUrl 一次保存 → 双令牌静默蒸发 → 全站回退 not_provisioned。

---

## 7. mock 边界

**前端代码零 mock 面（判定=干净）**：`grep -rn "MOCKUI\|mock" webui/src` → **0 命中**；`import.meta.env` 全树仅 1 支（`api-client.ts:35` VITE_API_BASE_URL，只影响**基址缺省**非数据）；无假数据常量（dashboard「未接入」卡=诚实空壳文案）。mock 真身=独立 stdlib 夹具 `scripts/webui_mock_server.py`（自述「绝不接入生产链路」+「不模拟 503 not_provisioned/失败限速」，与真实端有显式差异清单——形状保真但**非**行为全等）。构建产物 dist 实测无 `:8743`（7 处 `8743` 子串全落 React 压缩位掩码 `18874368`，逐处上下文核验）、无 `VITE_API_BASE_URL` 烘焙、无功能性质 8742（两处均为提示文案字符串）。
**会不会被看见？——不会**：mock 形状保真且回显同款 `source` 字段，而 `SemanticResult.source` 前端**从不渲染**（§1.1 消费者列无 source；`use-semantic-query.ts:58` 透传后无人消费）→ baseUrl 误指向残留 8743 进程时，9 页呈现与真后端**视觉不可分**。加上验收默认 `--api 8743`，「看到的好数据」缺一道「这是夹具」水印。列 F2-13（P2，缓解成本低：卡片页眉渲 source + mock 加 `X-Mock-Data` 标记头并显式呈现）。

---

## 8. 锁与判据（逐把强度实测）

| 锁 | 实跑/核验 | 断言强度 | 绕过方式 |
|---|---|---|---|
| `tests/test_webui_http.py` | **本席实跑 6 passed/7.15s**（三件套合规） | 后端面较强：401 无令牌、信封壳/`meta.schema_version`、**内层 `data.data.total_calls==1` 数值断言**、422 码 `stats_invalid_query`、503 not_provisioned、降级 200 壳、/ui 200/404+no-store | **零前端断言**：只验后端；TS DTO、页面解包、日志页双 schema（F2-06）全不覆盖；knowledge/plugins/memory 分册（test_webui_knowledge 等）同例 |
| `tests/test_pre_restart_check.py`+`pre_restart_check.check_webui` | 读码 :432-477 | dist **形态**四检：存在(缺=SKIP)/非空/<10MB/**零外链** | 不比 dist↔src 新旧（本席人工 find：当前 dist 03:55 ≥ 最新 src 03:54，暂无陈旧漂移；门本身抓不到下次）；不验 CSP/路由清单 |
| `scripts/webui_acceptance.py` | 读码全文 + UIACC 台账 | **文本标记存在性**（data 或 graceful **双模皆 PASS**）+ 非白屏(≥30 字) + 控制台错误白名单 | 数据错值（0 vs「—」）照过；默认打 mock；真 8742 一轮未跑（台账自述）；`--pages` 可裁 |
| `webui/scripts/layout-constitution.mjs` | **本席实跑 EXIT=0**「hex=0/字号五档/栅格/调色板=0」 | 视觉宪法正则门 | 纯样式，**不涉 API 契约**；只在 `npm run build` 前置或手跑，pytest 不跑 |
| `tsc -b` | **未跑**（会写 `node_modules/.tmp`，禁改面——如实披露）；tsconfig 核验：`strict+noUnusedLocals` 全开，include 覆盖 test 件 | 前端**内部**类型一致 | **类型是手抄契约**：后端改字段→tsc 全绿；未接 dev.ps1（typecheck=mypy） |
| `graph-layout.test.ts` | **本席实跑 7/7 pass**（node v26 原生 --test） | 布局确定性（坐标全等） | 不在任何 npm script/CI 清单，靠人记得 |
| `tests/verify_hashes.py` | grep 无 webui 键 | — | 前端 34 源文件**不在哈希清单** |
| CSP/baseUrl 9 用例 | 台账 `progress-HARDEN.md:37` | 一次性 | 临时脚本已删，**无常驻锁**（F2-18） |

**总判**：前端↔后端契约**没有任何一把跨栈锁**——`api-client.ts` 的「对表」全靠注释人肉锚定（:2-9），真实/夹具（`webui_mock_server.py`）两套后端形状同样手抄同步（其头注自认）。→ F2-14。

---

## 9. 发现清单（七要素：严重度｜坐标｜锚点｜根因｜改法 before→after｜验证命令｜回归锁）

### F2-01｜P1｜SSE 重放/换过滤器不清行 → 重复行 + React key 撞车（审计 P1-4 核为真，未修）
- 坐标：`webui/src/pages/logs.tsx:165-168`（resubscribe）、`:170-173`（applyFilters）
- 锚点：`sessionStorage.removeItem(CURSOR_KEY); startStream(null);`
- 根因：重放语义（after=null=自最旧保留事件全窗回放）与残留 `rows` state 叠加；`key={row.cursor}` 同值双现。
- 改法：`const startStream = (after: string | null) => { setGapMessage(null);` → `const startStream = (after: string | null) => { setGapMessage(null); setRows([]); setDroppedCount(0); backlogRef.current = [];`（resubscribe/换过滤器/手动连接三入口共用）。
- 验证：起 mock `python scripts/webui_mock_server.py --port 8743 --bearer any` → 浏览器连流→点「重新订阅」→DevTools 无 duplicate key 警告、行数=重放窗行数（人工；或补 playwright 断言 `rows.length==新窗行数`）。
- 回归锁：**无**。

### F2-02｜P1｜memory-graph 降级数据源在主视图当正常数据展示（判据：降级=欺骗→P1）
- 坐标：`webui/src/pages/memory-graph.tsx:73-76`（degradedSources 已算出）、`:244-255`（唯一渲染点在 selectedNode 详情卡内）
- 锚点：`const degradedSources = useMemo(` / `degradedSources.map(([name, state]) => (`
- 根因：后端 `data.sources`（`MemoryGraphData:431` 注释 ok/missing/unreadable）供整图诚实性，UI 只在**选中某节点后**于侧栏披露；不选=六统计卡+画布以全量口径示人（如 history 缺源时 persons/会话数系统性偏小仍是「数字」）。
- 改法：`{data.nodes.length === 0 ? (` 之前插入常驻横幅：`{degradedSources.length > 0 && <SectionCard><p>{t('memoryGraph.degradedBanner', { sources: degradedSources.map(([n, s]) => \`${n}(${s})\`).join('、') })}</p></SectionCard>}`（locales 双语补 `degradedBanner` 一键）。
- 验证：mock 8743（夹具可控缺源）或构造缺 history 库实例 → 首屏无选中节点亦见降级条；grep `degradedBanner`。
- 回归锁：**无**（acceptance 只看「图例/canvas」标记，文案在场即 PASS，测不到语义诚实）。

### F2-03｜P1｜设置保存把两个已存令牌静默清空（改 baseUrl 必踩）
- 坐标：`webui/src/components/settings/settings-dialog.tsx:64-65` + `webui/src/lib/api-client.ts:88-90`
- 锚点：`setApiToken(adminToken, 'admin');` / `storageSet(..., token && token.trim() ? token.trim() : null)`
- 根因：对话框打开即清空输入框（:41-42），save 无条件回写——空串=删除；占位文案「已保存（粘贴新值可覆盖）」与行为相反。
- 改法：`setApiToken(adminToken, 'admin'); setApiToken(roToken, 'ro');` → `if (adminToken.trim()) setApiToken(adminToken, 'admin'); if (roToken.trim()) setApiToken(roToken, 'ro');`（清除走显式「移除」小按钮：`setApiToken(null, kind)`）。
- 验证：手测或 playwright——存令牌→只改 baseUrl 再保存→`localStorage.getItem('webui:bearer')` 仍在。
- 回归锁：**无**。

### F2-04｜P2｜dashboard `?? 0` 把未知伪造成 0（**P2-11 核为真、现行在架**；同字段 tokens 页显「—」两页口径相反）
- 坐标：`webui/src/pages/dashboard.tsx:184,187`（:187 行内两处）
- 锚点：`formatInt(tokensData.totals?.calls ?? 0)` / `tokens.input.value ?? 0`
- 根因：`TokenBlock.value: number | null`（null=unknown_rows>0 的「未上报」，后端 `webui_stats/metrics` 契约）被 `?? 0` 归零；旧控制面缺 `totals` 同路径显 0。
- 改法：`formatInt(tokensData.totals?.calls ?? 0)` → `formatInt(tokensData.totals?.calls)`；`formatInt(tokensData.totals?.tokens.input.value ?? 0)` → `formatInt(tokensData.totals?.tokens.input.value)`（`formatInt` 对 null/undefined 已回 '—'，直接删兜零即修）。
- 验证：`grep -n "?? 0" webui/src/pages/dashboard.tsx` 期望零命中；mock 造 quality=unknown 族 → 总览卡「—」与 tokens 页一致。
- 回归锁：**无**（issue-ledger P2-11 曾点名，页面未接锁）。

### F2-05｜P2｜tokens 堆叠图 tooltip `Number(null)→0`
- 坐标：`webui/src/pages/tokens.tsx:157`
- 锚点：`formatter={(value, name) => [formatInt(Number(value)), String(name)]`
- 根因：recharts 对 null 数据点可回传 `null`/`''`，`Number(null)=0` 伪造零（NaN 路径 formatInt 有守卫，null 无）。
- 改法：`formatInt(Number(value))` → `value === null || value === '' || value === undefined ? '—' : formatInt(Number(value))`。
- 验证：hover 未上报块族 → tooltip「—」。回归锁：**无**。

### F2-06｜P2｜`/api/v1/logs/sources` 前后两套 schema，fallback 形态令日志页渲染期崩（④类唯一点名）
- 坐标：`plugins/.../api/v1.py:184-187`（fallback 仅 `{items}`）vs `api/events.py:119-128`（四字段）；受害面 `webui/src/pages/logs.tsx:176`（`sources.state.data.categories`）、`:264`（`categoryItems.map`）；TS 契约 `api-client.ts:319-324`
- 锚点：`"items": ["bot", "nonebot", "napcat"`（v1 版还缺 telegram/mail/capability/renderer 四名，`events.py:42-57` 已比对）
- 根因：`event_service is None`（未配 `bot_control_plane_events_db`）时 v1 注册**同名异体**兜底路由，形态未同步前端。
- 改法（前端收口）：`const categoryItems = sources.state.phase === 'ok' ? sources.state.data.categories : [];` → `… ? (sources.state.data.categories ?? []) : [];`（items 同收口）；（后端根治）v1 fallback 补 `"categories": [], "collector_status": "not_connected", "collectors": []` 并在 events.py 头注登记双形态契约。
- 验证：`../ChatBot_Runtime/venv/Scripts/python.exe -c` 构 `create_control_plane_app(config without events db)` + TestClient GET `/api/v1/logs/sources` 断言键集 ⊇ {items,categories}（可做成小 pytest）；前端 `grep -n "categories ?? \[\]" webui/src/pages/logs.tsx`。
- 回归锁：**无**（test_webui_http 不测 fallback 形态）。

### F2-07｜P2｜错误态丢结构化码 → 三页用 `/HTTP 404/` 嗅探 message 字符串
- 坐标：`webui/src/hooks/use-semantic-query.ts:49`（`{phase:'error', message}` 丢弃 `ApiError.code/status`）；`knowledge.tsx:28-30`、`plugins.tsx:19-21`、`memory-graph.tsx:34-36`（`isNotFound`）
- 锚点：`return /HTTP 404/.test(message);`
- 根因：旧进程 404 走 FastAPI 默认体 `{"detail":"Not Found"}` → 前端自拼 `HTTP 404: Not Found` 才命中——依赖 statusText 措辞与拼接格式，非 `ApiError.status`。
- 改法：hook：`return { state: { phase: 'error', message: error.message, status: error.status, code: error.code }, … }`；页面：`isNotFound(message)` → `notFound(state) { return state.status === 404; }`。
- 验证：`grep -rn "HTTP 404" webui/src` 零命中。回归锁：**无**。

### F2-08｜P2｜「非 JSON 200/未知形态」被当 ok+undefined（宽容兜底反噬）
- 坐标：`webui/src/lib/api-client.ts:198`（`return undefined as T;`）、`:217-218`（resolveSemantic 兜底透传）；引爆面 `knowledge.tsx:97`、`plugins.tsx:152`、`logs.tsx:175`（phase ok 即裸访问 `.items/.groups`）
- 锚点：`return undefined as T;`
- 根因：为吸收「裸数据端点」（health/status-bot/旧 logs/sources）设计的透传，把 `undefined`/HTML 壳（误配 baseURL、dev 代理缺 `/admin` 面）也归为 ok 数据。
- 改法：`return undefined as T;` → `throw new ApiError('响应非 JSON（端点或基址配置错误）', response.status, null);`；透传兜底加 `if (payload == null) return { state: 'source_unavailable', reason: 'empty_response' };`。
- 验证：dev 模式起 `vite` 不开 8742 → 总览 health 卡显示错误态而非空白。回归锁：**无**。

### F2-09｜P2｜重试策略两套并存且互相矛盾（一处名存实亡）
- 坐标：`webui/src/main.tsx:18-22`（不重试 401/403/404/**500**）vs `webui/src/hooks/use-semantic-query.ts:32-35`（不重试 401/403/404/**422**，500 可重试；503 含 not_provisioned 可重试×2）
- 锚点：`[401, 403, 404, 500].includes(error.status)`
- 根因：hook 恒覆写 per-query retry → 入口默认对现网全部查询失效（当前唯一查询出口是 hook），纯死配置还留着语义分歧。
- 改法：提取 `lib/retry-policy.ts` `export const shouldRetryQuery = (failureCount, e) => …` 两处共用；not_provisioned 503 直接不重试（配置态重试无益且刷审计行——后端 `_audit_middleware` 每次落库）。
- 验证：`grep -rn "failureCount < 2" webui/src` 仅 1 命中。回归锁：**无**。

### F2-10｜P2｜趋势图双时区口径：描述声明 UTC、刻度画本地
- 坐标：`webui/src/pages/calls.tsx:152` + `webui/src/lib/format.ts:41-48`；后端事实源 `webui_stats.py:215`（`"timezone": "UTC"`）
- 锚点：`{t('calls.trendDesc', { bucket: data.trend.bucket, timezone: data.trend.timezone })}`
- 根因：`toLocaleTimeString` 无 `timeZone` 参→浏览器本地；UTC+8 下刻度整体偏 8h。
- 改法：`return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });` → 增 `timeZone: data.trend.timezone`（formatBucket 加可选 tz 参，缺省本地）。
- 验证：TZ=Asia/Shanghai 与 UTC 两跑截图刻度不漂（或单测断言固定 tz 输出）。回归锁：**无**。

### F2-11｜P2｜前端令牌槽命名/回退与后端双槽语义错位；/admin 面 401 拖垮整页（详见 §6）
- 坐标：`api-client.ts:12-14,157-160` + `settings-dialog` locale「主令牌（读写）」+ 后端 `_app.py:313-321`（/admin 只认 token_sha256）、`auth.py:28-34`（Principal 恒 admin 角色）
- 锚点：`const READONLY_TOKEN_KEY = 'webui:bearer:ro';`
- 根因：前端「主/只读」双槽映射不到后端「读/超管」双槽；「读写」文案错误；dashboard 阻塞名单把仅 /admin 前缀可见的 health/status-bot 与全站聚合卡耦合。
- 改法：文案改「控制面令牌（BOT_CONTROL_PLANE_TOKEN）/超管令牌（SUPER_ADMIN，Phase A 无需）」；`dashboard.tsx:102` blocking 名单只留 `not_provisioned`，`auth` 态降级为**单卡** SemanticState（health/bot 两卡自红，其余四卡照常渲染——它们走双令牌皆收的 /api/v1）。
- 验证：仅填 ro 槽 + 真控制面 → 总览 4/6 卡出数而非整页拦截。回归锁：**无**。

### F2-12｜P2｜SSE 连接期 HTTP 503 终态化，与流内同码退避重连矛盾（§5 已证）
- 坐标：`webui/src/lib/sse.ts:113-118`（对照 `:163-165` 与 `:119` 注释）
- 锚点：`response.status === 422 || response.status === 503`
- 改法：`if (response.status === 401 || response.status === 403 || response.status === 422) { …stop… } if (response.status === 503 && code.code !== 'control_plane_not_provisioned') { this.scheduleReconnect(); return; }`
- 验证：流中途 kill 控制面再起 → 自动回连非「连接被拒」终态。回归锁：**无**。

### F2-13｜P2｜mock/真后端在 UI 上不可分辨 + 验收默认打 mock（§7 裁决；含 source 字段零消费）
- 坐标：`use-semantic-query.ts:58`（source 透传无消费者）、`webui_acceptance.py:346`（`default="http://127.0.0.1:8743"`）、`webui_mock_server.py:19-21`（自认不模拟 503/限速）
- 锚点：`SemanticResult<T> = { state: 'ok'; data: T; source?: string }`
- 改法：mock server 信封 `meta` 加 `"fixture": true`（其本就是夹具自证）→ `use-semanticQuery` 检出即渲染顶部黄条「数据源=离线夹具」；acceptance `--api` 默认改必填或打真 8742 缺省 SKIP。
- 验证：跑 mock 验收 → JSON 摘要含 fixture 标记；跑真后端 → 无黄条。回归锁：**无**。

### F2-14｜P2｜前端↔后端契约零机器锁（§8 总判；「穷举对表」靠注释）
- 坐标：`api-client.ts:2-9`（对表注释）、`webui_mock_server.py:12-14`（「形状保真=人工对照」自述）、`tests/verify_hashes.py`（grep 无 webui）
- 锚点：`// wave-2 对表（2026-09-18，DTO 真相源=`
- 改法：新增 `tests/test_webui_contract_lock.py`——①从 `create_control_plane_app(...)` 的 `app.openapi()["paths"]` 取全 GET 面；②常量表列出前端 12 路径+query 名（人工维护源=api-client.ts 顶注仍要求对表，但漂移现形）；③断言①⊇②且参数名对得上；④`verify_hashes --write` 纳入 `webui/src/**` 12 关键件。
- 验证：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_webui_contract_lock.py --basetemp="$TEMP/f2-lockcheck" -p no:cacheprovider -q`（本席未落盘，属建议件）。
- 回归锁：本条即锁缺失本身。

### F2-15｜P3｜`::1` 缺席双处（HARDEN 明文裁量在册，非遗忘）+ 存储不可用静默
- 坐标：`api-client.ts:42`；`webui/index.html:12`（connect-src 同缺）
- 改法（若裁量变更）：`new Set(['127.0.0.1', 'localhost', '::1'])` + CSP 补 `http://[::1]:*`。验证：`node --input-type=module -e "…" validateBaseUrl('http://[::1]:8742')`。锁：无（一次性用例已删，见 F2-18）。

### F2-16｜P3｜vite dev proxy 不含 `/admin/api/v1`（`vite.config.ts:18-24` 锚点 `'/api/v1': {`）→ 改 `proxy: { '/api/v1': …, '/admin/api/v1': … }`。锁：无。
### F2-17｜P3｜死码/内联格式合集：`format.ts:50 compactNumber`（锚点 `export function compactNumber`，零调用）；`affinity.tsx:49 toFixed(1)`；`memory-graph.tsx:230` weight 裸渲；`calls.tsx:197` 后端码魔法串；`use-async-queries.ts` 孤儿（审计中 16:07 在/16:25 被并行席删除——披露）。
### F2-18｜P3｜CSP/baseUrl 白名单「9 用例」无常驻锁（`progress-HARDEN.md:37` 临时件已删）→ 固化进 `webui/scripts/` + build 前置或 pytest+playwright 门。
### F2-19｜P3｜`setBaseUrl(null)` 清除后回退烘焙 `VITE_API_BASE_URL` 而非同源（`api-client.ts:34-36`）——当前 dist 未烘焙（§7 实证），纯前瞻。
### F2-20｜P3｜验收截图落源码树根：`affinity-page.png/calls-page.png/logs-page.png/logs-page-live.png/tokens-page.png`（铁律 6 卫生，非 webui 域顺带披露；先例 shot-dir 默认 %TEMP%）。

---

## 10. 「假真数据」端点清单（专问专答）

**空集**——现行 12 个前端消费端点在代码层全部接真数据源；最接近的三项风险均已按性质归档：①`stats/calls` 在 `bot_audit_db_path` 未配时恒「暂无数据」（如实，**非**假）；②验收「9 PASS」证据链=mock 一轮+graceful 一轮，**真后端一轮未跑**（判据缺陷，F2-13/§0）；③mock 指向不可辨（F2-13）。P2-11（`?? 0`）**为真且未修**（F2-04），属「未知显 0」的显示层造假，非端点假数据。

*本席零修改（除本报告）；全部行号快照 2026-09-19 16:07-16:31；并发漂移以锚点字符串为准。*

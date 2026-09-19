# F9 · WebUI 前端架构一致性审计（统一消息/协议/架构/函数/变量/参数 → 前端落地检验）

> **快照声明**：`date` 实跑输出 `Sat Sep 19 16:29:59 2026`；本审计为**只读**审读，快照期 16:29–16:40。
> 审读期间（16:33–16:34）主会话并发修改了 3 个文件（`dashboard.tsx`、`ui/card.tsx`、`patterns.tsx`，mtime 实证 `stat -c %y`），
> 系前轮审计（`docs/design/audit-20260919-unify-wave.md`）P1 项的在途修复：`?? 0` 已不在 dashboard 源码（`grep -n "?? 0" webui/src/pages/dashboard.tsx` 命中 0）、`CardTitle` 基类行高已除。
> **本台账对这些在途修复不重复记账**，只在§十收口顺序里提示「src 已新于 dist」。
> 工作树状态：`git status --porcelain webui/src` → `?? webui/src/`（全部未跟踪，与前轮审计一致）。
> 范围：`webui/` 35 源文件全量逐行 + `scripts/webui_acceptance.py`、`scripts/webui_mock_server.py`、`scripts/pre_restart_check.py::check_webui`、`tests/test_webui_*.py`、`tests/verify_hashes.py` 的取证（均只读）。

## 总裁决（一句话版）

前端**有真中央**：一切取数确实收口在 `lib/api-client.ts`（`controlApi` 11 端点 + `apiRequest`）与 `hooks/use-semantic-query.ts`（四态统一），页面**零处**裸 `fetch`（证据：`grep -rn "fetch(" webui/src` 仅 api-client.ts:169 与 sse.ts:97 两处，均在中央 lib 内）。
**但中央本身带三处「写了没接线/漏了字段」型缺陷**（正合用户裁定口径「中央自身多份定义/零接线=更严重缺陷」）：①错误中央把 `status`/`code` 丢掉，逼出 3 页 `isNotFound` 正则补丁；②重试策略两处分叉清单（main.tsx 与 hook 各一套、全局那套实际零消费）；③`apiRequest` 支持 `signal` 但全链零传递、且无任何超时。
外围最大问题是**执法面**：三个前端门（tsc / 版式宪法 / node --test）全部不在常驻 pytest 里，dist 与 src 无新鲜度锁——**本次快照 dist(03:55) 已旧于三个 src 文件(16:34)**，且 webui 一件都不在 `verify_hashes.py` 哈希册。

---

## 一、数据获取路径清单与行为差异表

### 1.1 全部取数路径（枚举完备，命令见 1.4）

| # | 路径 | 载体 | 走中央? | 备注 |
|---|---|---|---|---|
| 1 | REST 统一入口 | `lib/api-client.ts apiRequest<T>()` | ✅ 本体 | 11 端点全部经 `controlApi` 登记 |
| 2 | 语义包解包 | `resolveSemantic<T>()`（api-client.ts:208） | ✅ 本体 | 双层信封：外层 `apiRequest`、内层 hook |
| 3 | 页面取数 | 9 页 + app-shell 全用 `useSemanticQuery` | ✅ | 无一处页面级 fetch/axios/EventSource |
| 4 | SSE 日志流 | `lib/sse.ts LogsStreamClient`（fetch+ReadableStream 自实现） | ⚠️ **第二中央** | 与 api-client 并列的独立通道；鉴权回退、状态码分类、退避逻辑**各自实现一份**（差异见 1.2） |
| 5 | 端点 URL 构造 | `controlApi` 内 `qs()` + `logsStreamUrl()` | ✅ | SSE 也复用 `logsStreamUrl`，URL 单源 ✓ |
| 6 | mock 分支 | **前端源码内零 mock**（grep 证实无 `MOCK`/夹具常量分支）；mock 在带外 `scripts/webui_mock_server.py`（夹具后端） | ✅ 干净 | 值得表扬：不存在「前端藏假数据」形态 |
| 7 | 直连 localStorage | `api-client` storageGet/ storageSet 封装 vs `theme-context`/`logs.tsx`/i18next 直取 | ⚠️ | 存储访问风格 ×4（见 §二-3） |

**旁路计数：页面级旁路 0 条**；中央内部并存通道 1 条（SSE），其与 REST 通道的行为差异见下表——判定为「可接受的形态差异 + 不可接受的清单复制」。

### 1.2 REST 中央 vs SSE 中央的行为差异表

| 行为 | `apiRequest`（REST） | `LogsStreamClient`（SSE） | 差异判定 |
|---|---|---|---|
| Bearer 注入 | `getApiToken(auth) ?? getApiToken('ro')`（admin→ro 回退，api-client.ts:158） | `getApiToken('admin') ?? getApiToken('ro')`（sse.ts:89） | 语义一致但**逻辑双写**；改回退规则要动两处 |
| 超时 | **无**（`signal` 可传但无人传） | **无** | 两通道同病：后端挂起=前端永久 loading 态（react-query 层无 timeout 兜底） |
| 重试 | react-query `failureCount < 2`（在 hook） | 自有指数退避 `BASE_BACKOFF_MS=1_000`/`MAX_BACKOFF_MS=30_000`（常量形态✓） | 双机制并存；对同一无状态后端各自为政（可理解，但**不共享一份「可重试性」判定**） |
| 不可重试状态码 | hook：`[401,403,404,422]`（use-semantic-query.ts:33）；main.tsx 全局：`[401,403,404,500]` | sse.ts:114：`401/403/422/503` 停止，其余退避 | **三处三份清单，两两不一致**（F9-P1-2 根词条） |
| 错误归一 | 抛 `ApiError{status,code}` | 回调 `onStatus('auth_error',{code,message})`/`onGap` | 形态不同可接受；但 401/403 的**人话解释**在 REST 侧走 `SemanticState`、SSE 侧走 logs.tsx 手写横幅，分叉 |
| 信封解包 | `unwrapEnvelope`（含 data 即剥） | 帧内 `record?.data` 直取（sse.ts:170） | 同一信封两种解包实现；后端信封若加字段需双改 |
| abort | options 支持 `signal`——**全仓零消费**（写而不接） | 内部 AbortController（自管用，✅） | REST 侧 react-query 的 cancel 不传导到底层 fetch |
| 加载态 | hook 统一 `phase:'loading'` | 页面自持 `status` state（idle/connecting/…） | SSE 无 hook 层，属形态使然；但 `StreamStatus` 7 字面量与 locales `logs.status.*` 键是**无锁镜像** |

### 1.3 统一化方案（能直接落手）

1. **`lib/constants.ts`（新）**：`RETRY_NO_RETRY_STATUSES = [401,403,404,422,500] as const`、`API_TIMEOUT_MS = 15_000`、`POLL = { fast: 30_000, normal: 60_000, slow: 120_000 }`、`LIMITS = { callsOverview: 5, callsPage: 10, tokensOverview: 5, tokensPage: 20, affinityPage: 100, knowledgePageSize: 20, graphMaxNodes: 200 }`、`LOGS = { maxRows: 500, heartbeatStaleMs: 45_000, tickMs: 1_000, detailsMax: 200 }`、`DEBOUNCE_SEARCH_MS = 300`。api-client `controlApi` 的 `?? 50`/`?? 20`/`?? 200` 缺省改引 `LIMITS`（当前 api-client 缺省 50 与 affinity 页实传 100 是「同参数两真值」）。
2. **hook 透传 signal + 超时**：`useSemanticQuery` 的 fetcher 签名 `() => Promise<unknown>` 改 `(ctx: { signal: AbortSignal }) => Promise<unknown>`；`apiRequest` 内 `signal ?? AbortSignal.timeout(API_TIMEOUT_MS)`。一处改中央，11 端点 + 10 调用点全得超时与取消能力（before：`apiRequest(endpoint, options)` 无缺省 signal → after：`const signal = options.signal ?? AbortSignal.timeout(API_TIMEOUT_MS)`）。
3. **重试单源**：main.tsx 与 hook 二选一——推荐**删 hook 的 `retry`**，只留 QueryClient 全局一份清单（含 422/500）；hook 里注释指向 constants。现状全局那份对经 hook 的查询**事实上零消费**=典型「写了但没接线」。
4. **SSE 与 REST 共鉴权**：sse.ts 改 `import { getBearerForStream } from './api-client'`（把 89 行的回退逻辑挪进 api-client 导出），信封解包共用 `unwrapEnvelope`。
5. 泛型绑定：`useSemanticQuery<T>(key, fetcher: () => Promise<unknown>)` 改 `fetcher: () => Promise<T>`——现签名允许 `useSemanticQuery<HealthData>(…, () => controlApi.statsCalls())` 编译通过（T 与 fetcher 返回不校验），是中央层类型漏斗。

### 1.4 取证命令

```bash
grep -rn "fetch(" webui/src --include=*.ts --include=*.tsx        # 中央外 fetch=0
grep -rn "axios\|XMLHttpRequest" webui/src                        # 0 命中
grep -rn "refetchInterval" webui/src --include=*.tsx              # 10 处间隔字面量
grep -rn "isNotFound" webui/src                                   # 3 份定义 3 份调用
```

---

## 二、状态管理口径盘点

1. **服务器态**：react-query 单一（全部经 `useSemanticQuery`，key 手写数组）。✅ 同端点跨页共享成立：app-shell 与 knowledge 页都用 `['knowledge','collections']`，天然去重。缺陷：key 无中央注册表，`['health']`、`['stats-calls', window, 'overview'|'page']` 靠自觉——漂移只能靠 tsc 之外的人眼。
2. **UI 态**：页面本地 `useState`（窗口/桶/暂停/过滤/选中节点）——各页自持，无跨页需求，可接受。
3. **持久态四风格**（F9-P2-6）：
   - api-client：`storageGet/storageSet` 带 try-catch 封装（✅ 正确形态）；
   - theme-context.tsx:20,63：**直取 localStorage**（同款 try-catch 手写一遍）；
   - logs.tsx:116,134：直取 sessionStorage（游标本就该 per-tab，语义✅，风格未走封装）；
   - i18next 探测器自管 `i18nextLng` 键（带外，键名破坏 `webui:` 前缀约定——5 个自管键全部 `webui:*`，唯独语言键不是）。
   改法：`lib/storage.ts` 导出 `storageGet/storageSet/sessionGet/sessionSet` + 键常量表（`KEYS = { baseUrl:'webui:baseUrl', … }`），三处直取全部改走它。
4. **theme 双源判定**：localStorage `webui:theme` 是唯一持久源，context 只是运行期内存视图，刷新后 localStorage 赢——**无双源打架**（审读确认，仅 `defaultTheme='system'` 是 prop 缺省、无第二真值）。
5. **跨组件暗总线**：`'webui:open-settings'` CustomEvent 字面量 ×3（semantic-state.tsx:12 定义 `openSettings()`、app-shell.tsx:116 **绕过导出的 openSettings 手拼同一字面量**、settings-dialog.tsx:34 监听）。改法：常量 + 在 `vite-env.d.ts` 声明 `declare global { interface WindowEventMap { 'webui:open-settings': CustomEvent } }`；app-shell 116 行改 `onClick={openSettings}`。
6. **缓存失效策略**：无中央约定——`refetchInterval` 每调用点手填（见 §三表 A），`staleTime` 全局 10s 一处，settings 保存后以 `window.location.reload()`（600ms 魔法数）核弹式失效。判定：能跑，但「统一参数」不成立。

---

## 三、类型与常量的单源性

### 表 A · 魔法数字清单（35 条，全部给建议常量名）

| # | 坐标 | 字面量 | 语义 | 建议常量 |
|---|---|---|---|---|
| 1-3 | dashboard.tsx:93,94 / latency.tsx:54 | `30_000` | 快轮询 | `POLL.fast` |
| 4-9 | dashboard.tsx:95-99(×4) / calls.tsx:95 / tokens.tsx:78 | `60_000` | 常规轮询 | `POLL.normal` |
| 10 | affinity.tsx:69 | `120_000` | 慢轮询 | `POLL.slow` |
| 11-13 | dashboard.tsx:95,97,98 | `limit:5 / 1 / 5` | 总览 TopN | `LIMITS.*` |
| 14 | calls.tsx:94 | `limit:10` | 页 TopN | `LIMITS.callsPage` |
| 15 | tokens.tsx:77 | `limit:20` | 族数 | `LIMITS.tokensPage` |
| 16 | affinity.tsx:68 | `limit:100` | 榜单 | `LIMITS.affinityPage`（且与 api-client.ts:463 缺省 `50` 冲突） |
| 17 | api-client.ts:471 | `page_size ?? 20` | 词条分页 | `LIMITS.knowledgePageSize` |
| 18 | api-client.ts:477 | `max_nodes ?? 200` | 图上限 | `LIMITS.graphMaxNodes` |
| 19 | knowledge.tsx:109 | `300` | 搜索防抖 | `DEBOUNCE_SEARCH_MS` |
| 20 | knowledge.tsx:51 | `96` | 释义展开阈值 | `KNOWLEDGE_TERM_CLAMP_CHARS`（与 `line-clamp-4` 两处各管一段，注释互不提及） |
| 21 | logs.tsx:18,19 | `500`/`45_000` | 行上限/心跳窗 | 已是常量✅ 但 **locales zh/en `logs.rows` 文案里「500/cap 500」是第二份**（改数即撒谎，F9-P1-4） |
| 22 | logs.tsx:126 | `1000` | 秒表 tick | `LOGS.tickMs` |
| 23 | logs.tsx:41 | `200` | details 截断 | `LOGS.detailsMax` |
| 24 | locales latency.source | 「30s 自动刷新」 | 与 #1-3 双源（同 F9-P1-4） | 文案改 `{{seconds}}` 插值 |
| 25 | settings-dialog.tsx:67 | `600` | 保存后延迟 reload | `SETTINGS_RELOAD_DELAY_MS` |
| 26-27 | calls.tsx:77 / 同左 | `Math.max(2, …)` 条形最小宽 | 展示参数 | `BAR_MIN_PCT` |
| 28-31 | calls.tsx:161-171 与 tokens.tsx:139-156 | `borderRadius:12`×2、`width={36}/{150}`、`barSize={14}`、margin 六元组、`h-64/h-72` | recharts 版式**双文件手抄**且 `12` 脱离圆角三档(30/18/14) | `lib/chart.ts` 导出 `CHART_MARGIN/CHART_TOOLTIP_STYLE/Y_AXIS_WIDTH`（宪法门不查内联 style 数字=门盲区） |
| 32 | memory-graph.tsx:183 | `height:480` | 画布高 | `GRAPH_CANVAS_H`（注释自称「内联 style 白名单#1」，但白名单没有机器登记） |
| 33 | memory-canvas.tsx:82,106,176,181 | `0.0015`、`4/k`、`1.6`、`18/17` | 缩放/命中/标签 | 同文件已有 ZOOM_MIN/MAX 常量先例，补齐即一致 |
| 34 | memory-canvas.tsx:179 | `font:'12px "Segoe UI", …'` | canvas 字体硬编码（前轮审计 P1-6 已记，**不重复入账**，引用之） | 引 index.css 栈常量 |
| 35 | app-shell.tsx:66-67 | `slice(0,8)` + `>8` ×2 | 侧栏集合数上限 | `NAV_MAX_COLLECTIONS` |

### 表 B · 与后端重复定义的「手写镜像」清单（无生成物、无锁）

| 族 | 前端位置 | 后端真相源 | 现状一致性 | 风险 |
|---|---|---|---|---|
| DTO 28 型 | api-client.ts:223-433（`export interface/type` 计数命令：`grep -c "export interface\|export type" webui/src/lib/api-client.ts` → 28） | `control_plane/webui_stats.py` / `webui_knowledge.py` / `webui_plugins.py` / `webui_memory_graph.py` / `api/events.py` 的 dict 字面量 | 逐字段人工对表（注释里自认「真相源=××.py」） | 后端加/改字段，TS 静默漂移；`resolveSemantic` 无运行时校验，形状突变→页面 `.filter` 直接 TypeError |
| reason 码 18 条 | semantic-state.tsx:17-37 白名单数组 + locales `reason.*`（zh/en 各 18） | webui_*.py 各失败面字符串 | 三份当前对得齐 | 无机器锁；**plugins.tsx:24 `reasonText` 干脆不过白名单直接 `t('reason.'+reason)`**——第四份口径 |
| knowledge scope 5 条 | knowledge.tsx:26 `SCOPE_KEYS` | webui_knowledge.py `"scope":"general"/"kb_doc"/"acg_source"`（grep 实证行 243/388/489） | 齐 | 镜像无锁；emotion/scene 两值走 `sorted(bucket["scopes"])` 动态路径，前端只认 5 词 |
| 插件组序 4 条 | plugins.tsx:17 `GROUP_ORDER` + api-client.ts:383 联合类型 | webui_plugins.py 固定四组 | 齐 | api-client 联合 `'builtins' | … | string` **被 `string` 吞并**（等价裸 string，联合失去拼写防线）|
| 日志 category 7 条 | logs.tsx:21-29 `CATEGORY_TONE` | log_collectors 输出 | 未逐查 | 缺项静默落 `'flat'`（有兜底，可接受）但 tone 映射是前端第二定义点 |
| StreamStatus 7 条 | sse.ts:10 类型 + locales `logs.status.*`×2 语 | events.py 无此枚举（纯前端概念） | 前端内部三方镜像 | 改名三处必须同步，无锁 |
| StatsWindow/GraphWindow | api-client.ts:437,396 联合 | events/webui_stats query 校验 | 齐 | 联合类型是真锁✅（本表里唯一的好形态，推广之） |

### 类型不一致（可空性/字面量）个案

- `LatencyData.history: { status; reason }` 声明**非空**，latency.tsx:91-101 却全程 `?.` 防御——「类型说必有、代码说不一定」，二者必有一错（建议类型改 `history?: … | null` 或后端契约测试钉死必有）。
- `TokensData.totals` 非空声明 vs dashboard 并发修复后仍保留 `totals?.calls` 可选链——同上。
- `MemoryGraphData.sources: Record<string,string>`，注释自述 `∈ ok/missing/unreadable` 却不落联合类型。
- `useSemanticQuery` 的 `T` 与 fetcher 解绑（§一-5）。

---

## 四、错误 / 空 / 降级语义统一

中央件齐套：`SemanticState`（六态：loading/ok 之外五相）+ `DataState` 六相位 + `'—'` 未知值约定（format.ts 全 null→'—'，✅ 与后端「不造数」同构）。**分叉点 7 条**：

| # | 分叉 | 坐标 | 性质 |
|---|---|---|---|
| 1 | **错误相位丢字段 → 正则识 404** | use-semantic-query.ts:49（只带 message）；knowledge.tsx:28 / plugins.tsx:19 / memory-graph.tsx:34 **三份同体 `isNotFound = /HTTP 404/.test(message)`** | P1。后端错误体若带 `message`，`apiRequest` 会用它**覆盖**状态行文案（api-client.ts:182-185），正则即刻失明→「未部署」页降级成通用错误卡。中央丢字段是根因，页面正则是在错误接口上打补丁 |
| 2 | **空列表渲染成 '—'** | calls.tsx:65 TopList 空态 | P1（语义欺骗向）。'—' 在本案语义=「值未知」（formatInt(null)），用在「列表为空」处即「把空当未知」；其余 6 处空态用 `t('state.noData')`（latency:73、tokens:135/206、affinity:97、calls:157、SemanticState:94）。同一个「空」两种话术 |
| 3 | **文案内嵌常量数字** | locales `logs.rows`「上限 500」×2 语、`latency.source`「30s」×2 语 | P1。代码改数文案不改=界面撒谎（降级语义的可信度破坏） |
| 4 | **reason→人话三实现** | semantic-state.tsx:16（白名单→key）；dashboard.tsx:33 `fallbackLine`（白名单+前缀拼接）；plugins.tsx:24 `reasonText`（**绕白名单**直查 i18n） | P2。三处措辞形态互异：卡内一行 / `暂无数据：X` / `：X` |
| 5 | **总览页卡内降级不带重试** | dashboard.tsx:109 `<SemanticState state={blocking.state} />` 及 `withFallback`（不传 onRetry）；其余 8 页全传 `query.refetch` | P2。同一降级在总览是死卡、在他页可重试；统一改法：`withFallback` 收第二个参数 `onRetry` |
| 6 | **latency history 未知态落到「暂无数据」** | latency.tsx:101：`status==='unavailable' ? noHistory : state.noData`——若后端将来回 `status:'ok'` 前端仍显示「暂无数据」 | P3（当前契约恒 unavailable，属日历型埋雷） |
| 7 | **「把降级当正常」反向检查** | dashboard 健康卡 `ok?在线:降级` ✅；memory-graph 源降级有黄字 ✅；tokens quality 徽标 `?N/~N` ✅——**未发现把降级粉饰成正常的实例** | 记功 |

**结论**：四态组件本体是统一的（9/9 页 import SemanticState），分叉集中在**中央信息漏斗丢字段**与**空/未知的文案语义冲撞**，不需要重写组件，需要把接口的「码」补全并让 3 处手写补丁退役。

---

## 五、命名与目录约定一致性（违背自家约定清单）

项目约定（从 22 个源文件的既成事实归纳，非成文规范——「约定未成文」本身记 P3）：文件 kebab-case、组件命名导出、`use-*` 前缀仅 hook 目录、页导出 `XxxPage`、props 一律内联类型（零 `XxxProps`，✅ 全库一致无漂移）、i18n `域.段.键` 三层。

| # | 违例 | 坐标 | 说明 |
|---|---|---|---|
| 1 | `useState` 变量名 `window` 遮蔽全局 | calls.tsx:89、tokens.tsx:73、memory-graph.tsx:40 | 组件内此后任何 `window.*` 静默拿错对象；改 `statsWindow/graphWindow` |
| 2 | 目录收口不一 | `components/patterns/patterns.tsx`（6 组件一文件）vs 同层 `graph/`、`settings/`、`semantic/` 单件单文 | 二选一即可；建议 patterns 拆文件或明文规定「原子壳层允许合册」 |
| 3 | 跨命名空间取文案 | tokens.tsx:103 `t(\`calls.window.${item}\`)`；affinity 页宽 `max-w-4xl` vs 其余 8 页 `max-w-6xl` 无注释 | 窗口文案应上收 `common.window.*`；页宽漂移应有理由 |
| 4 | locale 键混用蛇形/驼峰 | `tokens.cache_read`（贴 API 字段）vs `knowledge.chunkCount`（贴组件惯例） | 立则：展示键一律驼峰，键值映射不依赖 API 字段名 |
| 5 | 组件内硬编码双语文案 | settings-dialog.tsx:50-54 `baseUrlErrorText` | 注释自认「locales 不在本改动域」——属越界披露而非违规，但**它就是约定漂移的实例**；文案入 `settings.baseUrlError.*` |
| 6 | 注释引用不存在的工具 | logs.tsx:121,144 `eslint-disable-next-line`（webui 无 eslint 依赖） | 前轮审计已记（P3），引用之 |
| 7 | 事件名以字面量三处散布（详见 §二-5） | app-shell.tsx:116 等 | 命名 `webui:*` 前缀本身统一✅，散的是引用方式 |
| 8 | 导出风格 | 全库 named export，唯 i18n.ts `export default` | 框架惯例可豁免；记录之 |

---

## 六、同职多实现族表（统一函数）

| 族 | 实现清单 | 差异 | 保留 | 其余合并 |
|---|---|---|---|---|
| **F1 「404→未部署」判定** | knowledge.tsx:28 / plugins.tsx:19 / memory-graph.tsx:34（三份逐字同体） | 无（正因相同才暴露中央丢 status） | 中央：use-semantic-query 的 error 相位补 `status`+`code` | 三页统一 `state.phase==='error' && state.status===404`；删三份正则 |
| **F2 reason→人话** | semantic-state.reasonKey（白名单）+ dashboard.fallbackLine + plugins.reasonText + locales 表 | 白名单被绕、措辞前缀三样 | `reasonKey`（唯一白名单点，且该数组上收 `lib/constants.ts`） | fallbackLine/reasonText 均改「t(reasonKey(r)) || 原码」单函数（抽 `lib/semantic-text.ts`，纯函数可测） |
| **F3 窗口/桶切换器** | calls.tsx WindowSwitch 组件 / tokens.tsx:91-106 内联同功能 / memory-graph 类型 chips / knowledge 集合 chips | 三种 DOM 形态三种 className 拼法，选中态一个用 `bg-primary` 两个用 CategoryChip | 抽 `patterns.ToggleChipGroup`（数据驱动 `{options, value, onChange}`） | 四处消费；版式归一 |
| **F4 空态文案** | SemanticState 卡 / 手写 `py-6 text-center` ×6 / SectionCard 空壳 ×3（knowledge/memory-graph/plugins）/ '—' ×1 | 「空列表」何时用卡、何时用行内句没有规则 | patterns 增 `EmptyInline`（收敛 `py-6 text-center fs-caption text-muted-foreground` 抄写） | 六处行内全替换；TopList 改 `t('state.noData')` |
| **F5 骨架屏** | knowledge.tsx 两处手写循环 / plugins GroupSkeleton / dashboard.tsx:78-82 / memory-graph 两处 / SemanticState loading | 每页自数格子数 | 保留各处（形态确实不同），但循环模式统一 `<SkeletonGrid n={6} class=…/>` 一行式 | 只合并「数组 map」样板，不动高度 |
| **F6 存储访问** | api-client.storageGet/Set、theme-context 内联、logs sessionStorage 直取、i18next 带外 | try-catch 抄两遍、前缀约定破 | `lib/storage.ts`（§二-3） | 三处改引 |
| **F7 鉴权头组装** | api-client.ts:152-160 与 sse.ts:88-92 | Content-Type vs Accept 不同可接受；token 回退同码两写 | api-client 导出 `buildAuthHeaders(base)` | sse.ts 改 `buildAuthHeaders({Accept:'text/event-stream'})` |
| **F8 徽章** | ui/Badge（variant 系）与 patterns/CategoryChip（tone 系）并存 | 无成文「何时 Badge 何时 Chip」；source 用 Badge、状态用 Chip 靠默契 | 都在用✅ | 在 docs 立一段两行规则即可，不建议合并（职责确有别） |
| 格式化 | `lib/format.ts` 7 函数**全库单源✅**（无第二实现；`compactNumber` 零消费=死导出，删或入用） | — | format.ts | — |

---

## 七、可测性架构（前端无组件测试根因与最小改造）

**根因判定**：不是「没装框架」（node ≥23 原生 `node --test`+TS 剥离已有 `graph-layout.test.ts` 7 例先例），而是**纯逻辑被埋在 JSX/组件闭包里**，不抽出来就没有可 `node --test` 的目标；同时三门（tsc/宪法/node-test）不挂常驻 pytest，写了也没人跑（前轮 P1-5 实锤：`grep -rn "layout-constitution|tsc -b|node --test" tests/` 命中 0）。

**最小改造清单**（全部「抽纯函数 + 同名单测」，与 graph-layout.test.ts 完全同构，零新依赖）：

| 抽什么 | 从哪 | 去处 | 测什么 |
|---|---|---|---|
| `fallbackLine/reasonText/reasonKey` → `describeReason(reason, t)` | dashboard/plugins/semantic-state | `lib/semantic-text.ts` | 白名单命中/未命中/回退原码 |
| `stateTone` | latency.tsx:13 | `lib/state-tone.ts` | fail/degrade/timeout/空 四类 |
| `tierTone/scoreClass` | affinity.tsx:15,24 | `lib/tiers.ts` | 8 档边界 |
| `detailsOneLine` | logs.tsx:38 | `lib/format.ts`（加长截断） | 200 字符边界 |
| `isNotFound`（退役）+ error 相位含 status | 见 F1 | hook 内 | 404 分类不再依赖文案 |
| Pager 的 `start/end/totalPages` 计算 | patterns.tsx:140-142 | `lib/pager.ts` 纯函数，组件消费 | 空集/越界 |
| `format*` 全家 | 已在 lib ✅ | 补 `format.test.ts` | null→'—'、ms/s 分档、时区畸形原样透出 |

**跑法裁决（二选一，不两头下注）**：**推荐 `node --test` + 一条常驻 pytest 子进程门**（`tests/test_webui_gates.py`：探测 node 可用→依次跑 `tsc -b --noEmit`、`node scripts/layout-constitution.mjs`、`node --test src/`（package.json 补 `"test": "node --test src/**/*.test.ts"`），无 node 环境 `pytest.skip`——这与「离线 pytest 门 + dev.ps1 四件套」现有体系同构、零 npm 依赖）。vitest 的代价：引入 devDependency 全家（jsdom/vitest/config）、与「禁为测试装依赖」的在场纪律冲突、且组件级测试会引火到「该不该测 React 渲染」的无底洞——本案 90% 风险在纯逻辑与门缺位，不在交互渲染。

---

## 八、一致性锁现状（哪些有门、哪些裸奔）

| 面 | 门 | 常驻? | 证据 |
|---|---|---|---|
| TS 类型 | `tsc -b`（npm run typecheck） | ❌ 仅手动 | dev.ps1 里 `typecheck`=mypy（scripts/dev.ps1:768），不含前端 |
| 版式宪法 | `scripts/layout-constitution.mjs` | ❌ 仅 `npm run build` 前置 | 门自身盲区：不扫 `w-*/h-*/size-*/max-h-[60vh]/内联 style 数字`（size-[1.2rem] theme-switch.tsx:19、h-1.5 calls.tsx:74、borderRadius:12 均漏网）；圆角三档零门 |
| 前端单测 | `node --test`（graph-layout 7 例） | ❌ 连 package.json scripts 都未登记 | 前轮实跑过（记录页 §28 行），非常驻 |
| 后端契约 | `tests/test_webui_{http,stats,knowledge,plugins,memory_graph}.py` | ✅ pytest 常驻 | 锁的是**信封/reason/只读性**（Python 侧），不锁 TS 类型与文案 |
| 真机目验 | `scripts/webui_acceptance.py`（9 页 data/graceful 双判据+控制台白名单） | ❌ 手动脚本 | 其「ok 标志文案」直接抄 zh common.json 字符串——**键改名/文案改词会静默击落验收**，两处无锁互联 |
| 产物 | `pre_restart_check.check_webui`：dist 存在/非 0 字节/<10MB/无外链 | ✅（重启预检第 8 项） | **不查新鲜度、不查 src↔dist 对应**：本次 `find webui/src -newer webui/dist/index.html` 命中 3 文件即活证据（并发修复后差距还会拉大） |
| 哈希册 | `tests/verify_hashes.py` | — | `grep -n "webui\|dist" tests/verify_hashes.py` → **0 命中：webui 全族未入册**，/ui 实际伺服的 dist/index.html 无字节锁 |
| i18n 双语对齐 | 无门 | ❌ | 本次 python 实对：zh/en 各 **238 键、差集 0**（当下干净；漂移无拦阻） |
| 信封漂移 | `unwrapEnvelope`「宽容解包」哲学（api-client.ts:114 注释自称避免耦合） | ❌ | 哲学性放弃锁定：后端顶层若出现名为 `data` 的业务字段会被误剥一层——现契约不触发，属登记的信任点 |

**收口风险总判**：「加了统一层但没有门守住」在本案**全部命中**——中央客户端、四态 hook、SemanticState、值册 token、宪法门都在，但除后端契约五件外，**前端自身没有任何一条常驻门**。当前 dist 旧于 src 是唯一在快照时刻可实证的既遂事故（其余为风险）。

---

## 九、新发现台账（F9；七要素。前轮审计已记项以「引用 P1-x」标注，不重复开账）

**F9-P1-1 中央错误相位丢 status/code，逼出三份 404 正则补丁**
- 严重度：P1
- 坐标：`webui/src/hooks/use-semantic-query.ts:40-51`；`pages/knowledge.tsx:28`、`pages/plugins.tsx:19`、`pages/memory-graph.tsx:34`
- 锚点：`return { state: { phase: 'error', message: error.message }, …}` / `function isNotFound(message: string)`
- 根因：hook 把 `ApiError`（含 status/code，中央明明有）压成纯字符串；页面为了「未部署」特判只能正则啃展示文案，后端一旦回带 `error.message` 的非 200（api-client.ts:182 会用其覆盖 `HTTP 404:` 状态行）判定即失效。
- 建议改法：`error` 相位 `{ phase:'error'; message:string; status:number; code:string|null }`（before：三页 `isNotFound(state.message)` → after：`state.status === 404`）；删三份 isNotFound。
- 验证：`cd webui && npx tsc -b`；`grep -rn "isNotFound\|HTTP 404" webui/src` 应只剩 0 命中。
- 回归锁：无（改造时在 test_webui_gates.py 加 grep 负断言，或 hook 纯函数化后 node --test 分类逻辑）。

**F9-P1-2 重试策略三份清单互不一致，全局那份实际零消费**
- 严重度：P1
- 坐标：`webui/src/main.tsx:18-22`（`[401,403,404,500]`）、`hooks/use-semantic-query.ts:32-35`（`[401,403,404,422]`）、`lib/sse.ts:114`（`401/403/422/503`）
- 锚点：`if (error instanceof ApiError && [401, 403, 404, 500].includes(error.status))`
- 根因：中央写了 QueryClient 缺省 retry，但唯一取数入口 hook 又自带 retry 覆写——全局清单只对「不存在的直接 useQuery」生效（写了没接线，正是六统一命题的负样本）；且 500 与 422 两清单互相「可重试对方拦截项」。
- 建议改法：只留 main.tsx 一份 `RETRY_NO_RETRY_STATUSES=[401,403,404,422,500]`（入 constants），hook 删 `retry`；sse.ts 的状态码集合同文件注释互指。
- 验证：`cd webui && npx tsc -b`；人工断言 hook 不再覆写。
- 回归锁：无。

**F9-P1-3 空列表渲染成 '—'，与「未知值='—'」全站语义冲撞**
- 严重度：P1
- 坐标：`webui/src/pages/calls.tsx:65`
- 锚点：`{entries.length === 0 && <p className='py-6 text-center fs-caption text-muted-foreground'>—</p>}`
- 根因：'—' 在 format.ts/后端「不造数」文化里=「值未知不可得」；TopList 用它表达「列表为空」，两义撞一枚符号（且该卡同页 trend 空态用的是 `state.noData`——同文件都不一致）。
- 建议改法：before `>—<` → after `{t('state.noData')}`（并入 F4 空态行组件一次改完）。
- 验证：`grep -n ">—</p>" webui/src/pages/calls.tsx` 0 命中；webui_acceptance calls 页判据不含该串（不受影响）。
- 回归锁：无。

**F9-P1-4 界面文案内嵌代码常量（500 行上限 / 30s 轮询），改数即撒谎**
- 严重度：P1
- 坐标：`locales/zh-CN/common.json:192` 与 `locales/en/common.json:192`（「上限 500」/「cap 500」）、两文件 `:149`（latency.source「30s」）；对照 `pages/logs.tsx:18 MAX_ROWS=500`、`pages/latency.tsx:54 30_000`
- 锚点：`（上限 500）` / `30s 自动刷新`
- 根因：常量第二真值藏进 i18n 文本，无插值。
- 建议改法：文案改 `t('logs.rows',{shown,dropped,cap: MAX_ROWS})`、`latency.source` 增 `{{seconds}}` 插值；locale 双文件同步改。
- 验证：`grep -n "500\|30s" webui/src/locales/*/common.json` 0 命中；`python scripts/webui_acceptance.py`（默认 MOCKUI）9 页仍 PASS（rows/source 非 ok 判据文案）。
- 回归锁：无（改造后该串对账逻辑可从 acceptance 里长出来：判据字符串单源于 locales）。

**F9-P1-5 三份镜像枚举零机器锁（reason 18 / StreamStatus 7 / SCOPE 5 / GROUP 4）**
- 严重度：P1（六统一之「统一变量/枚举字面量」正面反例；当前实对=齐，属无锁之齐）
- 坐标：`semantic-state.tsx:17-37`；`locales *.json reason.*`；`knowledge.tsx:26`；`plugins.tsx:17`；`lib/sse.ts:10`+`locales logs.status.*`
- 锚点：`const known = [ 'audit_source_not_configured',`
- 根因：白名单数组在组件文件里、locale 键在 JSON、后端字面量在 .py——三处各自演化无交叉断言。
- 建议改法：①数组上收 `lib/constants.ts`；②新增 `node --test` 用例 `lib/enum-parity.test.ts`：读两份 locale JSON 断言 `reason.*` 键集 === 白名单、`logs.status.*` 键集 === StreamStatus 字面量表；③后端侧在 `tests/test_webui_stats.py` 族加一条「reason 产出集 ⊆ 前端白名单」清单（Python 常量表落 `webui_stats.py` 或 contracts，测试引用之）。zh/en 键集对等（现 238/238，实跑命令见 §十一）一并锁死。
- 验证：`cd webui && node --test src/lib/enum-parity.test.ts`。
- 回归锁：改造本身即锁。

**F9-P2-6 存储访问四风格 / `webui:` 前缀被 i18next 破**（§二-3；改法=lib/storage.ts；验证 `grep -rn "localStorage" webui/src | grep -v lib/storage` 仅 i18next 带外 0 命中；无锁）
**F9-P2-7 `apiRequest.signal` 全链零接线 + 双通道均无超时**（§一；改法=signal 透传+`AbortSignal.timeout`；验证=mock server `--delay-ms 30000` 下页面 15s 落 error 态；无锁）
**F9-P2-8 `useSemanticQuery<T>` 与 fetcher 返回类型解绑**（api-client 11 方法改返回 `Promise<T>` 直连：`fetcher: () => Promise<A>` 并 `resolveSemantic<A>` 由 hook 内部推——改一处签名；验证=故意错位编译应红；无锁）
**F9-P2-9 `resolveSemantic` 兜底「非语义包一律当 ok」+ 无运行时形状校验**（api-client.ts:208-219；后端形状突变→`knowledge.tsx:97 collections.state.data.items.filter` 直接 TypeError 炸整页（无 ErrorBoundary，引用前轮 P1-x）；改法=最低限度 `Array.isArray(x?.items)` 级守卫入各 DTO 消费前，或引入轻量 schema 断言纯函数进 lib 可测；无锁）
**F9-P2-10 `PluginGroup.id` 联合被 `| string` 吞并**（api-client.ts:383 锚点 `'migrated_modules' | string;`；改法=删 `| string`（后端确只有四组，未知组 plugins.tsx 排序自然沉底不崩）；验证 tsc；无锁）
**F9-P2-11 open-settings 事件字面量 ×3 且 app-shell 绕过已导出的 `openSettings()`**（§二-5；改法=常量+WindowEventMap 声明+116 行改 `onClick={openSettings}`；验证 `grep -c "webui:open-settings" src/**` 定义点=1；无锁）
**F9-P2-12 dev proxy 缺 `/admin/api/v1`**（`webui/vite.config.ts:18-23` 锚点 `'/api/v1': {`——同源开发模式 dashboard 健康/进程两卡必 404；引用：前轮审计 P2 坐标表曾记 vite 行，本条给出具体改法：proxy 增 `'/admin': { target: 同 }`；验证：dev 模式起 mock（mock 已含 legacy 裸体端点）看两卡入态；无锁）
**F9-P2-13 webui 全族未入 verify_hashes，dist 无新鲜度锁（快照时点 src 已新于 dist：活证据）**（§八；改法：`verify_hashes.py --write` 补 `webui/dist/index.html`（+可选 api-client.ts 作为契约镜像首件）；pre_restart_check.check_webui 增「`webui/src` 最新 mtime > dist mtime → WARN」；验证：`find webui/src -newer webui/dist/index.html -type f` 修复后应为空；此改法牵动哈希册重录——**本席不重录**）

**F9-P3 汇总**：dashboard 降级卡无重试（§四-5）；`compactNumber` 死导出；eslint-disable 幽灵引用（引用前轮）；页宽 max-w-4xl 孤例；window 变量遮蔽 ×3（§五-1）；recharts 版式双文件手抄（表 A #28-31，建议 `lib/chart.ts`）；canvas 内联「白名单#1」无机器登记；`LatencyData.history`/`TokensData.totals` 可空性与消费面矛盾。

---

## 十、重构收口顺序建议（含哈希册牵动披露）

原则：**先加锁、后动语义、再动版式**；每步都可独立回滚。`webui/src` 全未跟踪，git 面回滚=删工作树文件（前轮 §411 已裁定），故不必过度切小。

1. **步骤①（零行为变化，不炸任何验收）**：新建 `lib/constants.ts`、`lib/storage.ts`、`lib/chart.ts` 并回填引用（§一-1、§二-3、表 A #28-31）+ 命名违例五项（§五 1/5/7、F9-P2-10/11）。门：`tsc -b` + 宪法 + acceptance 全绿即可推。
2. **步骤②（错误接口改造，牵 5 文件）**：F9-P1-1 + F9-P1-2 一次做完（error 相位扩字段 → 三页 isNotFound 退役 → 重试单源）。locale 与 DOM 零变化，acceptance 文案判据不受影响。
3. **步骤③（语义三小刀）**：F9-P1-3 空态、F9-P1-4 文案插值、§四-5 重试补齐。改 locales 双 JSON——**须同步核 acceptance 的 ok 判据串是否被动**（现判据多为段落标题，rows/source 行不在判据内，预判不炸，仍要实跑）。
4. **步骤④（可测性+门上线）**：§七纯函数抽离 + `enum-parity.test.ts`（F9-P1-5）+ package.json `test` 脚本 + `tests/test_webui_gates.py` 常驻门（含 tsc/宪法/node-test 三段、无 node skip）。此步起，步骤①-③的成果全部被锁。
5. **步骤⑤（行为面）**：F9-P2-7 超时/abort 接线（唯一可能改变用户可感时序的一步：挂起后端 15s 后从永久 loading 变 error 卡——mock `--delay-ms` 目验后合流）。
6. **步骤⑥（版式收敛，动 DOM）**：F3 切换器统一 + F4 EmptyInline + 骨架 map 收敛——**会动截图基线**，单独一波：先 `npm run build` 重建 dist、跑 acceptance 9 页 + 双轮基线核图（沿用 uiux 波次的字节等值判据），再合流。
7. **步骤⑦（产物锁）**：`npm run build` → `tests/verify_hashes.py --write` 补登 `webui/dist/index.html`（**重录由主会话执行，F9 不动**）+ pre_restart_check 新鲜度 WARN 项。此后任何前端合流都以「重 build+重录+重验」三件套收尾。

**verify_hashes 牵动清单**：仅步骤⑦新增登记项；步骤①-⑥不触碰既有 12 交付物哈希（渲染域文件零交集——webui 无一处 import 渲染域，目录边界干净）。doc_sync/catalog 与前端无契约点，不受影响。

---

## 十一、附录：统计类结论的复跑命令

```bash
# 用例数/文件数
find webui/src -type f \( -name '*.ts' -o -name '*.tsx' \) | wc -l          # 26（+2 json+2 资产=30 件，另 index.html/vite.config/3 tsconfig/门脚本）
grep -c "export interface\|export type" webui/src/lib/api-client.ts          # 28
grep -rn "refetchInterval" webui/src --include=*.tsx | grep -c _             # 10
grep -rn "fetch(" webui/src --include=*.ts* | grep -vc "queryFn\|refetch"    # 2（api-client.ts:169, sse.ts:97，皆中央 lib 内）
grep -rn "isNotFound" webui/src | grep -c "function"                          # 3
# locale 键集对等（本次实跑：zh 238 / en 238 / 差集 0）
../ChatBot_Runtime/venv/Scripts/python.exe -c "import json;…keys 递归对差…"   # 见会话记录，纯 stdlib 只读
# dist 新鲜度（本次实跑命中 3 文件 = P2-13 活证据）
find webui/src -newer webui/dist/index.html -type f
# 门缺位（引用前轮审计 P1-5，本席复核命中 0 一致）
grep -rn "layout-constitution\|tsc -b\|node --test" tests/ scripts/dev.ps1   # 0
```

> 诚实披露：①行号以 16:29-16:40 快照为准，并发修改可能令 §五/§九 行号 ±漂移，锚点字符串不受影响；②§四-7「无粉饰实例」只覆盖 9 页现存降级面，Phase B 未接端点系文案明示「未接入」✅；③后端 .py 真相源逐字段全量 diff 未做（28 型工作量），本表按抽查 4 族 + 注释自述口径记账。

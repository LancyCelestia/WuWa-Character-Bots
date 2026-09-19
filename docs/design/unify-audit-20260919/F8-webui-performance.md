# F8 · WebUI 性能与资源增长审计（2026-09-19）

> 快照声明：本审计于 **`date` = 2026-09-19 16:30:00 +0800** 的源码/产物快照上完成，**全程只读**（除本文件外零新建/编辑/删除）。未跑浏览器、未起 dev server、未占端口、未发真实请求、未触发渲染截图、未 `npm run build`。凡无实跑数据支撑的结论一律标注「静态推断」。诚实红线：「无泄漏」只写成「未发现泄漏证据」；本文不含任何「已修复」措辞（改代码的是主会话，不是我）。
> 范围独占面：**性能与资源增长**。页面/契约/门禁/渲染/安全由并列 F 席覆盖，此处不重复主张。

## 0. 结论速览

- **前端长连（SSE）**：日志页为 fetch-流式自实现（非 EventSource），`LogsStreamClient` 单实例、`start()` 先 `stopInternal()`（abort 旧 controller + clearTimeout），重连经 `signal.aborted` 短路——**未发现重连叠加/多流并存的泄漏证据**。唯一无界增长向量：`paused` 态下 `backlogRef` 无限追堆（见 L-1）。
- **24 小时挂机内存判定（静态推断）**：常驻态**不塌**——`rows` 封顶 500、storage 键全为固定常量、react-query 后台标签默认停轮询、无 `seenRef` 类无界 Set（本页根本没有该结构）。**但两处在特定操作下吃内存/磁盘**：①日志页「暂停」超 24h（L-1，前端内存）；②TTS 音频落盘目录无字节/条数配额（L-6，磁盘）。
- **首屏/包体**：`dist/index.html` = **973,154 B（950.35 KiB）单文件自包含、0 chunk、0 `.map`**（vite-plugin-singlefile 全内联）；dist mtime(03:55) 新于最新 src(03:54)，**体积结论来自当前产物、非旧产物**。
- **外部 CDN 依赖：0 条**（详见 §3）。所有 http(s) 串均为错误信息/命名空间/baseURL 白名单文本，无任何 `<script src=http>`/`<link href=http>`/`@import url(http)`/`font src url(http)`/`url(http)` 真实资源加载。字体全系统栈（Segoe UI / 微软雅黑 / PingFang / ui-monospace）。**离线优先成立**。
- **网络请求统一度**：REST 走**单一** `apiRequest` 封装（统一性好），但**零超时、零切页 abort**、轮询间隔**魔数散落 9 处**（违反「统一参数」，见 §4 + L-4）。
- **性能锁**：`tests/test_perf_regression.py` 只锁**路由判定 + 整包导入**；`scripts/measure_latency_chains.py` 覆盖路由+渲染后端但是**手动脚本非断言门**；**前端零性能门**（L-7）。渲染后端 C-1 线程中毒已有 `tests/test_browser_ctx_leak.py` 回归锁（现状核实=已修已锁）。

---

## 1. 泄漏 / 无界增长清单（坐标 + 判定依据）

| # | 严重度 | 坐标 | 判定依据 | 24h 影响（静态推断） |
|---|---|---|---|---|
| L-1 | **Medium** | `webui/src/pages/logs.tsx:102-104`（`onEvent`→`backlogRef.current.push(row)`）、`:61`（`backlogRef=useRef([])`） | 暂停期间每条事件无条件 push，无上限、无淘汰；恢复时才一次性灌入 `appendRows`（届时才受 MAX_ROWS 裁剪，但恢复前堆积无界） | 若用户停在日志页且按「暂停」并挂机：busy 日志流下 `backlogRef` 单调增长 = **内存吃紧** |
| L-2 | Low | `logs.tsx:131-135`（每 `rows` 变写 `sessionStorage.webui:logsCursor`） | 每 SSE 事件一次写；值为单键覆盖 | 单键不增长；仅高频写的小开销（注释自陈「高频但轻量」，可接受） |
| L-3 | **无（正向确认）** | storage 键：`api-client.ts:12-14`(`webui:baseUrl/bearer/bearer:ro`)、`theme-context.tsx:7`(`webui:theme`)、`i18n.ts:45`(`i18nextLng`)、`logs.tsx:17`(`webui:logsCursor`) | 全部为**固定常量键**，无任何按 id/时间拼键的动态写入 → **无 storage 键增长**（未发现证据即视为无） | 不增长 |
| L-4 | **无（正向确认）** | 各页 `setInterval`/重连：`logs.tsx:126-128` 有 `clearInterval`；其余页轮询全走 react-query `refetchInterval`（`use-semantic-query.ts:26-36`，卸载由 react-query 自管） | 未发现「卸载后仍 setState」的裸定时器路径；SSE 客户端 `stop()` 在 `useEffect` 卸载清理里调用（`logs.tsx:118-120`） | 不泄漏 |
| L-5 | **无（正向确认）** | 图表数据累积：`calls.tsx:144`、`tokens.tsx:120`、`memory-graph.tsx` | 图表数据源=每次 refetch 返回的新数组，无「历史 push 累积」模式；记忆图节点后端 `max_nodes≤200` 截断（`api-client.ts:476`） | 不累积 |
| L-6 | **Medium** | `domains/media/capabilities/tts.py:265-269`（`_store_cache` 仅 pop 内存项，**不删磁盘文件**）、`:370-372`（每次合成 `output_dir/{key}.wav` 落盘）、`_output_dir` 默认 `data/tts_output`、全文件无 `enforce_quota`/`prune`/`max_bytes` | 内存 `_CACHE` 有 LRU 上限 512（`_CACHE_LRU_CAP`，L-6 不犯内存错），但淘汰只 `popitem` 丢引用、**对应 .wav 永不清理**；每个新 (text,ref,params) 生成新文件 | 磁盘**无界增长**（每段新语音一个几百 KB 的 wav，随对话内容永不回收）；RAM 不受影响 |
| L-7（后端 SSE 资源，非前端） | Low | `control_plane/api/events.py:165-226`（每订阅者一循环，空闲时每 `min(heartbeat,0.25)=0.25s` 一次 SQLite 查询）、无并发订阅者上限 | 单订阅者 4 次查询/秒；Starlette 断连即取消该迭代器（`stop()` 的 abort 关 TCP→服务端感知） | 本机单用户 N 小；多标签页开日志时 DB 查询按 N×4/s 线性放大，无封顶 |

补充核实（后端存储，正向）：`control_plane/events.py` 事件库 `max_events=10000` 计数裁剪、`RuntimeEventBus` 队列 `capacity=1024` 有界；`metrics.py` 读预算 1s + limit 1..100；`resources.py` 快照 0.25s 缓存。**服务端存储层无无界增长。**

---

## 2. 体积与 chunk 表

| 项 | 值 | 依据 |
|---|---|---|
| `webui/dist/index.html` | **973,154 B（950.35 KiB）** | `find dist -type f` 实测；**唯一产物**，JS/CSS/HTML 全内联 |
| chunk 数 | 1（0 独立 .js / 0 独立 .css） | vite-plugin-singlefile 设计使然 |
| `.map` 文件 | **0** | `find dist -name '*.map'` = 0（源码映射不外泄，卫生合格） |
| dist vs src 新鲜度 | dist(2026-09-19 03:55) **新于** 最新 src(03:54) | 体积结论来自**当前产物**，非旧产物 |
| recharts 占比 | **静态推断 ~30–45%**（约 300–430 KiB） | 无法精确归属（单文件无 sourcemap，禁 build 分析）；recharts v3 拖入 victory-vendor + d3-scale/shape + redux（`redux.js.org/Errors` 串即旁证），是最大单一贡献者 |
| 大件排序（静态推断） | recharts ≫ react-dom(≈130K) > react-router/query(各≈半树) > i18next(+detector) > d3-force(小) > lucide(仅用图标，tree-shake 后小) | install-size 与 bundle 不成正比（`node_modules` 计数仅作旁证，不可当结论） |

**代码分割机会（静态）**：`router.tsx:2-11` 九页全部**顶层静态 import**，`calls.tsx:6-14`/`tokens.tsx:6-15` 顶层静态 `import 'recharts'`、`memory-canvas` 顶层 `import 'd3-force'`（`graph-layout.ts:1`）——**首屏无论去不去图表页都要解析+执行 recharts/d3-force**。可改法见 L-8：路由级 `React.lazy` + `Suspense`，把 recharts/d3-force 移出初始同步执行链（即便 singlefile 内联，动态 import 仍延后求值）。

---

## 3. 外部 CDN 依赖点名（离线优先核查）

`dist/index.html` 内出现的全部 http(s) 串及定性：

| 串 | 定性 | 是否资源加载 |
|---|---|---|
| `http://www.w3.org/{1998/Math/MathML,1999/xhtml,1999/xlink,2000/svg,XML/1998/namespace}` | XML/SVG 命名空间 URI | 否 |
| `http://127.0.0.1:8742`、`http://localhost` | baseURL 缺省/白名单常量文本（`api-client.ts:42`） | 否（运行期由用户配置、且限回环） |
| `https://react.dev/errors/`、`https://redux(.js|-toolkit.js.org)/Errors`、`https://bit.ly/3cXEKWf`、`https://locize.com`、`i18next.com/...` | 库内置**错误信息/文档链接文本**（throw 文案），不发起网络 | 否 |

**外部 CDN 依赖条数 = 0。** `<img>` 远程封面在**渲染后端 Python 侧**处理（`render_backends.py` ORB 图床回源 + mermaid CDN 已被 `page.route` 本地换血，`_MERMAID_CDN_URL`），与浏览器前端无关。**离线环境前端不会挂。**

---

## 4. 网络请求模式碎片化表（每页怎么发请求）

所有 REST 均经**唯一** `apiRequest`（`api-client.ts:148`）→ 统一度良好；下表标出的差异在**参数与超时/abort 层**：

| 页 | 端点（`controlApi.*`） | 轮询间隔（魔数） | 超时 | 切页 abort | 备注 |
|---|---|---|---|---|---|
| dashboard | health/statusBot(×2) + statsCalls(×2) + statsTokens + statsLatency | 30s×2、60s×4（`:93-99`） | 无 | 无 | 一进页 **6 个并发**请求（并行非瀑布） |
| calls | statsCalls | 60s（`:95`） | 无 | 无 | |
| tokens | statsTokens | 60s（`:78`） | 无 | 无 | |
| latency | statsLatency | **30s**（`:53`） | 无 | 无 | |
| affinity | affinityBoard | **120s**（`:69`） | 无 | 无 | |
| knowledge | knowledgeCollections →（依赖）knowledgeTerms | 无（手动/`refetch`） | 无 | 无 | **两段瀑布**（terms 依 collections 结果）；分页 20/页有界 |
| plugins | pluginsCatalog | 无 | 无 | 无 | |
| memory-graph | memoryGraph(maxNodes=200) | 无 | 无 | 无 | |
| app-shell（常驻） | knowledgeCollections（key 与 knowledge 页同 → react-query 去重 ✓） | 无 | 无 | 无 | |
| logs | logsSources + **SSE `/api/v1/logs/stream`**（源 `sse.ts`，唯一自带 `signal`） | 秒表 1s | 无（靠 45s 心跳判活） | 有（唯一） | |

**碎片化裁决**：实现只有 **1 套 fetch 封装**（统一 ✓），但 **超时/退避/abort 参数三缺一**：
- 超时：`apiRequest` 无 `AbortSignal.timeout`、`controlApi.*` 不接受 `signal` → **慢端点/挂端点会让 react-query 卡 `loading`、骨架无限转**（L-5 见台账）。
- abort：`useSemanticQuery`（`:26-36`）不把 `signal` 透传给 fetcher → **切页/卸载后在飞 REST 不 abort**（react-query 不主动取消 fetch），最多多跑一次；对只读幂等 GET 影响小，但违背「统一 abort」。
- 轮询魔数 **9 处各写一份**（30/60/120s），无集中常量 → **直接违反用户「统一参数」命题**。

---

## 5. 渲染后端资源面（读代码判定，未跑）

`domains/render/render_backends.py`（真身；`capabilities/.../render_backends` 为历史垫片路径）现状核实：

- **并发/等待**：`PlaywrightRenderBackend._lock` 已升级为 `BoundedSemaphore(max_concurrency)`（`:451`，缺省 1=串行），`BOT_RENDER_MAX_CONCURRENCY`/`BOT_RENDER_WAIT_BUDGET_MS` 三态解析（`:322-349`）。等待预算 `_wait_render_budget`（`:211`）总时长封顶 ≤ budget_ms。
- **page 生命周期**：`render_card` `finally` 内 `page.close()`（`:707-712`），`set_default_timeout=8000ms`（`:655-657`）防慢资源长期持锁。
- **C-1（历史事故，AGENTS #26）现状**：`_get_browser` launch 失败分支已当场 `__exit__(started ctx)`（`:501-506`），退避 sleep 移出槽位临界区（`_release_slot_backoff` `:523-549`）。**同类中毒路径未发现残余**；`tests/test_browser_ctx_leak.py`（4+ 例）为常驻回归锁 → **已修已锁（非本席修复，仅核实）**。
- **崩溃自愈**：`_MAX_CONSECUTIVE_PAGE_FAILURES=2` + `_browser_looks_broken`（`:718`）；空闲 600s 回收（`:420`）。
- **一处高上限（Low）**：`_IMAGE_BYTES_CACHE` 封面 LRU 上限 **64 条 × 每条 ≤8 MiB**（`:77-78`）→ 单进程理论内存顶 **≈512 MiB**（实配图多远小于此，且只缓存成功）。有界但天花板偏高，可下调。
- **cards 落盘配额（核实）**：`render_card_png` 用**内容哈希文件名**（`card_{digest}.png`，`content_parser.py:463-464`）+ 落盘后 `_sweep_quota`→`enforce_quota(max_bytes=bot_card_cache_max_bytes)`；`config.py:768` 缺省 **268435456（256 MiB）** + 60s 限频扫（`:346-360`）→ **有界**。stocks/market/fx/affinity/help/divination 各自 `prune_prefixed(keep=120~200)`/`_prune_card_dirs(keep=120)`（计数有界）。AGENTS #34⑨「占卜卡每抽一子目录不受 enforce_quota」**已按计数口径收口**（keep=120），非字节口径但不再无界。**未发现无界卡片增长**——除 TTS 音频（L-6，独立目录，无 sweep）。

---

## 6. 可观测的性能退化（前端侧）

- **控制面资源指标端点存在但不进前端**：`ResourceMetricsService.snapshot()`（`resources.py`，CPU%/RSS/线程数/uptime）能力齐，但 `api-client.ts` `controlApi` **无对应方法**、`webui/src` 无任何 `resources`/`/metrics` 消费（grep 无命中）→ **WebUI 不显示任何后端资源/处理耗时**（`CallsData` 无时延字段；仅 latency 页显示**渠道** EWMA/最近 ms，非请求处理耗时）。
- **前端无耗时上报**：全树无 `performance.now`/`PerformanceObserver`/Web Vitals 打点，无耗时统计口径。
- **慢端点无超时保护**：见 §4——REST 无 `AbortSignal.timeout`，挂端点=挂该查询的 UI（不崩，但空转骨架）。

---

## 7. 新发现台账（七要素，可直接落手；主会话改，我不改）

> `严重度｜坐标｜锚点字符串｜根因｜建议改法 before→after｜验证命令（离线可复跑量法）｜有无回归锁`

**L-1｜Medium｜`webui/src/pages/logs.tsx:61,102-104`｜`backlogRef.current.push(row)`**
根因：暂停态对每条事件无条件入 `backlogRef`，无上限、无淘汰；挂机即无界堆积（前端内存）。
改法 before→after：给 `backlogRef` 设容量并丢最旧——`backlogRef.current.push(row); if (backlogRef.current.length > MAX_ROWS) { setDroppedCount(c=>c+ backlogRef.current.length - MAX_ROWS); backlogRef.current.splice(0, backlogRef.current.length - MAX_ROWS); }`（或干脆 `if (backlogRef.current.length >= MAX_ROWS) return;` 直接丢弃并计数）。
验证：`grep -n "MAX_ROWS" webui/src/pages/logs.tsx` 应命中 push 分支的裁剪；静态断言 `backlogRef` 每次 append 后有 `length` 上界。
回归锁：**无**。

**L-2｜Medium｜`webui/src/pages/logs.tsx:52,126,288-302`｜`const [nowTick, setNowTick]` + `setInterval(...,1000)` + `rows.map(...)`**
根因：每秒 `setNowTick` 触发 `LogsPage` 整体重渲染 → 500 行列表每秒全量 diff，且每行 `formatTime(row.created_at)`（`Intl.toLocaleTimeString`，昂贵）与 `detailsOneLine`→`JSON.stringify(details)` 每帧重算（≈500 次/秒）。
改法 before→after：①把「心跳存活秒表」下沉成独立子组件 `<Heartbeat age=...>`（`nowTick` 只在子组件内），使主 `LogsPage` 不再每秒 re-render；②抽 `<LogRow>` 用 `memo`，props 传**预格式化的字符串**；③在 `appendRows` 入库时一次性算好 `displayTime`/`detailsLine` 附到行对象（或 `useMemo` 包 rows→映射），避免渲染期反复 Intl/JSON。
验证：`grep -c "rows.map" webui/src/pages/logs.tsx` 由行内 map 改为引用 memo 化子组件；人工核对 nowTick 不再出现在 list 的渲染依赖里。
回归锁：**无**。

**L-3｜Low（前端 CPU，可观测但不卡死）｜`webui/src/pages/logs.tsx:101,77-88,148-150`｜`onEvent: (row) => { ... appendRows([row]) }`**
根因：每条 SSE 事件一次 `setRows` + 一次 `useEffect[rows]`（写 sessionStorage + `scrollIntoView`）→ 高频日志流打断主线程、逐帧滚动。
改法 before→after：`sse` 侧或页侧做批处理——用一个 `pendingRef` 收事件、`requestAnimationFrame`/`setTimeout(≈100ms)` 合并一次 `appendRows(batch)`；`scrollIntoView` 同样节流。
验证：静态确认 `onEvent` 不再 1:1 直连 `setRows`（存在合并窗口）。
回归锁：**无**。

**L-4｜Medium（违背「统一参数」）｜9 处轮询魔数：`dashboard.tsx:93-99`、`calls.tsx:95`、`tokens.tsx:78`、`latency.tsx:53`、`affinity.tsx:69`｜字面量 `30_000/60_000/120_000`**
根因：各页各端点各写一份 `refetchInterval` 与 SSE 退避常量（`sse.ts:20-21` `MAX_BACKOFF_MS/BASE_BACKOFF_MS`），无集中真相源。
改法 before→after：新建 `webui/src/lib/polling.ts` 导出 `export const POLL = { health: 30_000, stats: 60_000, latency: 30_000, affinity: 120_000 }` + `SSE_BACKOFF = {base, max}`；各页 `refetchInterval: POLL.stats` 取代裸数字。
验证：`grep -rEn "refetchInterval: [0-9]" webui/src/pages` 命中数应为 0（全部引常量）。
回归锁：**无**。

**L-5｜Medium｜`webui/src/lib/api-client.ts:148-199`（`apiRequest`）+ `hooks/use-semantic-query.ts:26-36`**
根因：`apiRequest` 无超时、`controlApi.*` 不接 `signal`、`useSemanticQuery` 不向 fetcher 透传 react-query 的 `signal` → 挂端点空转骨架、切页在飞请求不 abort。
改法 before→after：`apiRequest` 增 `options.timeoutMs` 并在缺省处 `signal = AbortSignal.any([options.signal, AbortSignal.timeout(15_000)])`（无外部 signal 时也挂 timeout）；`useSemanticQuery` 用 react-query 的 `{ signal }` context 传进 fetcher：`queryFn: ({signal}) => fetcher(signal)`，`controlApi.*` 末位接受 `signal` 透传给 `apiRequest`。
验证：`grep -n "AbortSignal.timeout\|queryFn: ({ signal })" webui/src` 命中；`grep -n "signal" webui/src/lib/api-client.ts` 覆盖 `apiRequest`。
回归锁：**无**。

**L-6｜Medium｜`plugins/bot_unified_runtime/domains/media/capabilities/tts.py:265-269,370-372,395-396`｜`_CACHE.popitem(last=False)` / `output_dir / f"{key}.wav"`**
根因：TTS 磁盘产物无字节/条数/保鲜期配额；LRU 只丢内存引用不删文件 → `data/tts_output` 随新语音无界增长（RAM 有界、磁盘无界）。
改法 before→after：仿 `content_parser._sweep_quota`——`_store_cache` 淘汰时 `try: evicted_path.unlink(missing_ok=True)`（丢引用前删盘上文件）；或落盘后对 `_output_dir` 调 `enforce_quota(dir, max_bytes=cfg.bot_tts_cache_max_bytes, max_age_days=cfg.bot_tts_cache_max_age_days)`（config 新增两键并入 catalog/.env.example，缺省给非 0 上限如 64 MiB/7 天）。
验证：`grep -nE "enforce_quota|unlink|_sweep" domains/media/capabilities/tts.py` 命中；离线量法：构造 N 次不同文本合成后统计 `data/tts_output` 文件数是否封顶。
回归锁：**无**。

**L-7｜Low｜`tests/test_perf_regression.py`（全文件）**
根因：性能门只覆盖**路由判定吞吐 + 单次 max + 整包导入时长**；渲染后端时延仅在手动脚本 `scripts/measure_latency_chains.py`（非断言门），**前端完全无性能门**（不锁 dist 体积/chunk 数、不锁 SSE 重连/裁剪行为、不锁轮询参数）。
改法 before→after：加两条常驻门——①前端产物体积门：断言 `webui/dist/index.html` 的 `st_size` < 某上限（如 1.2 MiB）且 chunk 数==1、`.map` 数==0；②日志页行为静态门：断言 `logs.tsx` 含 `MAX_ROWS` 裁剪与 `clearInterval`（防回退）。
验证：`../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_perf_regression.py -k frontend -p no:cacheprovider`。
回归锁：**无**（本条即「加了优化却没有锁」的风险点本身）。

**L-8｜Low（首屏）｜`webui/src/router.tsx:2-11`（九页静态 import）+ `calls.tsx:6`/`tokens.tsx:6`（静态 `import 'recharts'`）+ `graph-layout.ts:1`（`import 'd3-force'`）**
根因：重依赖（recharts/d3-force）在初始同步执行链内，无论用户是否访问图表页都要解析求值。
改法 before→after：`calls/tokens/memory-graph` 三页改 `const CallsPage = lazy(() => import('@/pages/calls'))`，路由 `component` 包 `<Suspense fallback={<Skeleton/>}>`；recharts 随页动态载入。
验证：`grep -nE "React.lazy|lazy\(" webui/src/router.tsx` 命中；重构建后 `grep -c 'recharts' dist/index.html` 的**执行位置**从入口内联块移入延后块（singlefile 下仍以体积不变、求值延后为准，需 build 后核对，本席不 build）。
回归锁：**无**。

---

## 8. 「若主会话照改，牵动哈希册 / 需重录」标注（我不重录，只点名）

- **L-1/L-2/L-3/L-4/L-5/L-8 全在 `webui/**` 前端域**：前端源码改动本身不进 `tests/verify_hashes.py` 的 12 交付物哈希清单（该册锁的是卡片/渲染域交付物）——但**一旦重新 `npm run build` 出 `dist/index.html`，dist 字节会变**；若任何哈希/门禁断言到 dist 或其内联内容（本席未发现此类断言），需连带重录。**结论：纯前端 .tsx/.ts 改动不触发哈希册；触发的是 dist 产物重录（构建期，非本席职责）。**
- **L-6（TTS 磁盘配额）**：若新增 `bot_tts_cache_max_bytes`/`_max_age_days` 两 config 键 → **必动 `config.py` 字段数**（当前 529，机器册 `docs/auto-facts.md` 口径）+ **`docs/config-catalog.md` A26 补录** + `.env.example` + **`scripts/doc_sync.py` 事实册再生** + `tests/test_doc_sync_gates.py::test_config_catalog_*` 门禁。属跨域改动，谨慎与在飞 TTS 席协调。
- **L-7（新增常驻性能门）**：往 `tests/test_perf_regression.py` 加断言即扩门——规矩「只许新增/收紧，禁放宽阈值」，新门不得反向松动既有三条。
- 本席**未改任何文件、未重录任何哈希**；以上仅为改动方标注。

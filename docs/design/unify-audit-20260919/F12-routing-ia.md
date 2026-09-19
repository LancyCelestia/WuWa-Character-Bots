# F12 前端信息架构与路由审计（2026-09-19）

> **快照声明**：本审计基于 `date` 实测 **2026-09-19 16:32 (+08)** 的 `webui/src` 工作树实盘（多席并发，前端文件可能在动；本报告所有坐标为当时行号，落手前请重读最新态）。全程只读，未跑 build/dev server/浏览器，未触任何禁触域。所有「路由数/键数」均以实盘文件为准（非文档抄录）。
> 技术底座实盘：`@tanstack/react-router` package.json 钉 `^1.121.34`，**node_modules 实装 1.170.38**；`createHashHistory()`（router.tsx:94）= hash 路由；code-based routeTree，无文件路由插件。

---

## 一、路由实盘穷举（问题域 1）

路由表唯一定义处：`webui/src/router.tsx:23-96`。可达路径 **9 条**（含 index）：

| # | path | 路由文件行 | 页面组件 | validateSearch | 侧栏导航项 | acceptance PAGE_SPECS |
|---|---|---|---|---|---|---|
| 1 | `/`（index） | router.tsx:25 | dashboard.tsx | 无 | app-shell.tsx:47 ✓ | ✓ |
| 2 | `/calls` | router.tsx:27-31 | calls.tsx | 无 | :48 ✓ | ✓ |
| 3 | `/tokens` | router.tsx:33-37 | tokens.tsx | 无 | :49 ✓ | ✓ |
| 4 | `/latency` | router.tsx:39-43 | latency.tsx | 无 | :50 ✓ | ✓ |
| 5 | `/affinity` | router.tsx:45-49 | affinity.tsx | 无 | :51 ✓ | ✓ |
| 6 | `/logs` | router.tsx:51-55 | logs.tsx | 无 | :52 ✓ | ✓ |
| 7 | `/knowledge` | router.tsx:57-65 | knowledge.tsx | **collection（全站唯一）** | :53 ✓ + 动态子分组（≤8 集合+「更多…」，:89-95） | ✓ |
| 8 | `/plugins` | router.tsx:67-71 | plugins.tsx | 无 | :54 ✓ | ✓ |
| 9 | `/memory-graph` | router.tsx:73-77 | memory-graph.tsx | 无 | :55 ✓ | ✓ |

- **默认重定向**：无显式 redirect；index 路由即 `/`（hash 空 = `#/`）。
- **孤儿判定**：「有路由无导航」= 0；「有导航无路由」= 0。**九页导航与路由当前双向对齐，但靠人肉维护**——同一份清单复制在 4 处（router.tsx、app-shell.tsx nav 数组、webui_acceptance.py PAGE_SPECS、该脚本 `--pages` help 文案 :351），零机械锁（见第八节）。
- **404/未匹配行为（非白屏但不可用）**：未配 `defaultNotFoundComponent`、无任何 route 级 `notFoundComponent`。库源码实证（`webui/node_modules/@tanstack/react-router/dist/esm/renderRouteNotFound.js:14-24`）：缺配置时回落内置 `DefaultGlobalNotFound` = 裸 `<p>Not Found</p>`（dev 期 console.warn 自证「overly generic」）。即手敲 `#/settings` 会在应用壳内渲染**无样式、无 i18n、无回首页链接**的英文「Not Found」。
- **hash 路由选型本身正确**（单文件 dist、file:// 直开、/ui 静态挂载免 SPA fallback——router.tsx:13-14 注释与 `test_webui_http.py:171-187` 互证），前进/后退在 hash history 下工作正常；logs 页离页 `clientRef.current?.stop()`（logs.tsx:118-120）+ sessionStorage 游标续传，回退不炸流。

## 二、导航结构合理性（问题域 2）

- **分组依据与后端域模型分叉**：侧栏 9 项按**观测面功能**分组（总览/统计×3/好感/日志/知识/插件/图谱），数据源实际混合了后端 3 类前缀（`/admin/api/v1/*` health×2、`/api/v1/stats/*`×3、`/api/v1/{affinity,logs,knowledge,plugins,memory}`×5，见 api-client.ts:448-483）。后端 20 域（domains/）与 features 树**在导航层零映射**——导航既不对齐「域」也不对齐「端点前缀」，是第三套自造分类。**结论：前端 IA 与后端域模型分叉属实**；但 Phase A 只有九页，强行按 20 域拆导航也不成立，裁定建议=把「导航分组=后端资源族」写成显式文档口径并锁住，而非立即重排。
- **命名/顺序/图标**：九图标全 lucide、`size-4`、顺序与路由表注册序一致 ✓。命名分叉一处：dashboard 页标题用 `t('nav.overview')`（dashboard.tsx:108,126），其余页用自域 `t('<page>.title')`——同层级键两套写法。
- **当前路由高亮（前缀匹配陷阱）**：resolveIsActive 实证（`@tanstack/react-router/dist/esm/Link.js:34-41`）默认=**路径前缀匹配**（非 exact）+ search 子集匹配。九条路径互不为前缀（`/logs` vs `/knowledge` 等无 `/a/b` 嵌套），当前无实伤；但这是对未来的裸奔点：一旦新增 `/calls/:id` 之类子路由，`/calls` 的 `to` 链接天然高亮全族（有时想要、有时不想要），**且现在没有任何测试钉住这个语义**。真实可见小 bug：knowledge 子分组「更多集合…」`NavSubItem` 不带 collection（app-shell.tsx:94 → search `{}`），子集语义使其**在 /knowledge 任何状态下恒高亮**，与选中集合项双高亮并存。
- **md 以下无导航（P2-12 复验：仍在，属实锤）**：`app-shell.tsx:71-73` 侧栏 `hidden ... md:flex`；顶栏（:106-119）在 `md:hidden` 下只有 logo/主题/设置三枚，**无任何页面切换入口**。手机端只能手敲 hash——控制面场景不可接受。最小改法见台账 F12-02。
- 设置入口经 `window.dispatchEvent(new CustomEvent('webui:open-settings'))` 字符串事件总线（app-shell.tsx:116 ↔ settings-dialog.tsx:34，魔法串两处硬编码、无类型约束）。

## 三、深链与可分享性逐项判定（问题域 3）

**九页中仅 1 页（knowledge 的 collection 一项）状态进了 URL；其余 6 页全部关键视图状态只活在内存，刷新即丢、无法把「某个具体视图」发给别人**（logs 游标在 sessionStorage=跨标签页不共享、不可分享，且对「回放窗口」语义是正确选择，应保留）。

| 页 | 视图状态 | 现行载体 | 刷新丢 | 可分享 | 行号锚 |
|---|---|---|---|---|---|
| dashboard | 无（两窗口写死 24h/7d） | — | — | 整页可分享（无态） | dashboard.tsx:95-97 |
| calls | window(24h/7d/30d)、bucket(hour/day) | useState | 是 | 否 | calls.tsx:89-90 |
| tokens | window | useState | 是 | 否 | tokens.tsx:73 |
| latency | 无 | — | — | 整页可分享 | — |
| affinity | order(desc/asc)；（隐含 100 条截断位） | useState | 是 | 否 | affinity.tsx:64 |
| logs | source/category 过滤 | useState | 是 | 否 | logs.tsx:56-57 |
| logs | 游标 cursor | sessionStorage `webui:logsCursor` | 否（同标签页） | 否（**设计正确**，勿上 URL） | logs.tsx:17,116,134 |
| knowledge | **collection** | **URL search ✓** | 否 | **是 ✓**（非法值静默回退不改 URL，见 F12-09） | router.tsx:61-63、knowledge.tsx:99-102 |
| knowledge | q（搜索词）、page | useState | 是 | 否 | knowledge.tsx:104-106 |
| plugins | 无（组序固定） | — | — | 整页可分享 | — |
| memory-graph | window(24h/7d/30d/all)、typesHidden、label 过滤、**selectedId 节点** | useState×4 | 是 | 否（节点 id 稳定、详情视图=刚需） | memory-graph.tsx:40-43 |

同名参数多页写法不一致：24h 窗口在 calls/tokens（`StatsWindow`，api-client.ts:437）与 memory-graph（`GraphWindow` 多一档 `all`，:396）是两套类型两套标签文案（zh 字典 `calls.window.24h`=「24 小时」vs `memoryGraph.window.24h`=「近 24 小时」），tokens 页直接借用 `t('calls.window.*')`（tokens.tsx:103）——第三个引用点。

### 统一 query 参数约定草案（可直接落手）

1. **载体**：一律 TanStack `validateSearch` + `useSearch` + `navigate({ to, search })`，样板=knowledge（router.tsx:61-63 是全站正解，推广到其余八页）。
2. **缺省即省略**：值=缺省时不写入 URL（validateSearch 归一为 undefined）；非法枚举值→**回退缺省且 `navigate(replace)` 改写 URL**，保证「URL 所见=页面所得」。
3. **键名表**（与后端 REST query 保持同名，「统一参数」到端）：
   - `window`：`24h|7d|30d|all`（页面不支持 all 则枚举收窄），缺省 `24h`；
   - `bucket`：`hour|day`，缺省 `hour`；
   - `q`：字符串 ≤200 字符，缺省省略；
   - `page`：整数 ≥1，缺省 1；`page_size` 暂不进 URL（后端钉 20）；
   - `order`：`asc|desc`，缺省 `desc`；
   - `collection`：字符串（现状保留）；
   - `types`：可见节点类型逗号表（`person,group,memory,rule,conversation`），缺省=全选（注意：**编码「可见」而非「隐藏」**，防双否定）；
   - `source` / `category`：日志过滤，字符串，缺省省略；
   - `node`：memory-graph 选中节点 id，缺省无；
   - **cursor 明确不进 URL**（sessionStorage per-tab 语义正确，写进约定文档防后人「顺手统一」）。
4. **时间一律相对窗 token，禁裸 ISO 进 hash**（时区两义性）。
5. 实现顺序建议：calls/tokens/memory-graph 的 window → knowledge q+page（用户最常有分享诉求）→ logs 过滤 → affinity order → graph node。

## 四、页内骨架一致性分叉清单（问题域 4）

版式宪法组件（patterns.tsx，自称「全站卡片唯一外壳」）实被 2/9 页绕开。分叉穷举（10 条）：

| # | 分叉 | 坐标 |
|---|---|---|
| S1 | 页头手搓（裸 `<h1 className='fs-page'>`+自定义 flex 行）不用 `PageHeader` | calls.tsx:102-131、tokens.tsx:89-107 |
| S2 | 窗口切换器两份实现：calls `WindowSwitch` 组件（calls.tsx:25-44）vs tokens 内联复制改版（tokens.tsx:91-106，样式串不同） | 同左 |
| S3 | 卡壳直用裸 `Card/CardHeader/CardTitle`，绕开 `SectionCard`（其 title 默认已含 fs-card，调用方再手写 `className='fs-card'` 双保险漂移） | calls.tsx:59-83,148、tokens.tsx:125,170,199 |
| S4 | **组标题与页面标题同字号**（一席已发现，扩展穷举）：插件组标题 `<h2 className='fs-page'>`（18px=页 h1 同径） | plugins.tsx:128 |
| S5 | 同类问题第二处：设置弹窗标题 `<h2 className='fs-page'>` | settings-dialog.tsx:87 |
| S6 | 文档大纲：`CardTitle` 是 `<div>`（card.tsx:30-32），全站卡标题无语义层级；仅 plugins h2 与 settings h2 是 heading——九页大纲各页不成体系 | card.tsx:30 |
| S7 | 空态三形态：卡内居中 `py-6 state.noData`（latency:73/tokens:135/affinity:97）vs `SectionCard` 包裹专属文案（knowledge:252/memory-graph:164）vs **裸段落不居中无卡**（plugins emptyGroup:133）vs 字面量 `'—'` 不走 i18n（calls TopList:65） | 同左 |
| S8 | 加载骨架 5 套自写：knowledge（knowledge.tsx:131-145）、plugins `GroupSkeleton`（102-110）、memory-graph 两处（95-99,152）、dashboard `CallsDetailGroup`（78-82）、SemanticState 通用（semantic-state.tsx:45-53）——无统一 PageSkeleton | 同左 |
| S9 | 工具条/过滤条三页三写（logs select 行 logs.tsx:244-276、knowledge 居中搜索 :198-214、memory-graph 工具行 :112-148），无 FilterBar 抽象 | 同左 |
| S10 | 容器宽度/间距分叉：8 页 `max-w-6xl gap-4`，affinity `max-w-4xl`（affinity.tsx:75，单表可辩护但未声明），plugins 根 `gap-6`（plugins.tsx:158） | 同左 |

分页器仅 knowledge 一处消费 `Pager`；affinity 无分页（见 F12-08 截断问题）。

## 五、跨页数据口径一致性（问题域 5）

| # | 实体/口径 | 分叉实况 | 坐标 |
|---|---|---|---|
| D1 | **时区呈现（最误导）** | calls 趋势脚注带后端 `timezone`；dashboard 健康 `generated_at`、bot `started_at`、affinity `updated_at`、logs `created_at` 全部 `toLocaleString('zh-CN')` 浏览器本地时区**零标注**——同屏 UTC 源数据两种时钟读感；logs 行内只有 `formatTime`（时分秒无日期），跨日尾流误读 | calls.tsx:152 vs dashboard.tsx:147,159、affinity.tsx:56、format.ts:26-37 |
| D2 | **24h 窗口措辞 5 变体** | 「调用数（24h）」/「今日（24 小时）」/「24 小时」/「近 24 小时」/字典键 `24h` 三种渲染文案+两种括注风格 | dashboard.tsx:167,zh 字典 :78,91；calls.window.24h；memoryGraph.window.24h |
| D3 | **好感度榜截断口径** | 前端请求 `limit:100`、api-client 缺省 50、后端上限 200（`webui_stats.py:235`）、页脚显「共 total 人」真值——total>100 时**只列 100 行且无「已截断」提示无翻页**，同卡并列两口径 | affinity.tsx:68、api-client.ts:463、webui_stats.py:234-236 |
| D4 | 只读用户健康面板口径（详见 F12-07） | `/admin/api/v1/health`+`status/bot` 仅认主令牌（`_app.py:313-320` `_auth_dependency`），其余 `/api/v1/*` 读依赖双令牌皆收（:152-179）；前端把第二槽位命名「只读令牌」实为 super_admin 令牌 | 见台账 |
| D5 | 渠道异常判定：dashboard「连败>0 计异常」(:121) 与 latency 页 `stateTone`（含 fail/dead/error 词面+连败，latency.tsx:13-19）**两实现两处逻辑**，当前语义等价、无共享函数保证恒等价 | |
| D6 | 数字/日期 locale：`formatInt/formatDateTime` 硬编码 `'zh-CN'`（format.ts:5,30），切到 en 界面数字日期仍 zh 格式（i18n 有 en 全量字典 238 键、实测与 zh 键集全等，但**格式化不随 i18n 语言**且**无语言切换入口**） | |
| D7 | 刷新频率各自为政：30s（health/botStatus/latency）/60s（calls/tokens）/120s（affinity）/手动（knowledge/plugins）/SSE（logs）——不算错，但「多新鲜」在页面上无统一呈现（无「更新于」全局约定，仅 latency 副标题带「30s 自动刷新」） | |

## 六、页标题 / document.title / 图标 / 书签（问题域 6）

- `document.title` **不随路由更新**：index.html:14 静态「守岸人控制台」，全 src 无 `document.title`/`HeadContent`/route `head()`（grep 实证）。九页书签/标签页全同名。
- favicon：index.html:13 `<link rel="icon" href="data:,">` 空 data URI（=有意置空），九页无区分度。
- meta description：无。manifest/PWA：无（「离线可用」主张=file:// 单文件直开，不依赖 PWA，口径自洽，无虚标）。
- lang 固定 `zh-CN`（index.html:2），不随 i18n 切换。
- 前进/后退：hash 路由 + TanStack Link 正常；logs 回退重挂有游标续传。唯一历史坑=knowledge 非法 collection 不改写 URL（F12-09）。

## 七、权限与可见性 IA（问题域 7，只判 IA 层）

- 导航对 admin/super/只读**完全同构**（无角色过滤逻辑，app-shell.tsx:46-56 静态数组）→ 无「点了必 403 的菜单项」**除一处例外**：持 super-admin 令牌（即前端语义的「只读令牌」槽位）用户在 dashboard 页，health/statusBot 两查询 401 → `phase==='auth'` 命中 blocking（dashboard.tsx:101-112）→ **整页降级为「令牌无效或无权限」卡**，而其余八页该令牌全可读。入口诚实性破损=「只读令牌用户 1/9 页被整页拒」。
- 令牌槽位命名与后端语义错位：settings「主令牌（读写）」暗示有写——**WebUI 全站零写端点（Phase A 纯只读）**；「只读令牌」实收的是 super_admin 令牌。两枚标签都不诚实（措辞级，非泄权）。
- 设置面板暴露面：baseUrl+两令牌全本机 localStorage、baseUrl 白名单校验已在（api-client.ts:51-71），IA 层无额外不该暴露能力；`cross_process_introspection_unavailable` 等 reason 文案对 plugins 组不可用有诚实解释（zh 字典 :67）。

## 八、锁与最小 IA 锁设计（问题域 8）

现状盘点：

| 对象 | 有无锁 | 证据 |
|---|---|---|
| 路由↔导航↔字典键↔acceptance 清单 四方一致 | **无**（四处人肉副本） | router.tsx/app-shell/webui_acceptance.py:51-88/--pages help:351 |
| 404 行为 | **无**（acceptance 无负例路由） | webui_acceptance.py 全文无 unmatched-route 断言 |
| 逐路由真访问 | 半有：PAGE_SPECS 九路由逐个 goto+文案/DOM 标志+白屏检测，但 `#/xxx` 不在 nav_hrefs 时判 **SKIP 不算失败**（:262-265），路由缺失可静默滑过退出码 | |
| HTTP 契约（信封/认证/422/静态壳） | 有（`test_webui_http.py` 6 测常驻），但 READ_PATHS 只 4 端点、knowledge/plugins/memory-graph/logs 四族不在其中（他族测试是否覆盖属契约席，此处只报 IA 相关） | test_webui_http.py:101-106 |
| 深链参数进 URL 后的回归 | 无（仅 collection 有 spec 注释无测试） | |
| 版式（hex/字号/间距） | 有构建门 `layout-constitution.mjs`（不含 PageHeader 使用率/h 层级/nav 集） | package.json:8 |
| 前端单测 | 全站仅 `graph-layout.test.ts` 一件，无路由/壳测试 | webui/src/**/*.test.* 实盘 |

**最小 IA 锁建议（一条 pytest 常驻，零浏览器）**：新增 `tests/test_webui_ia_gates.py`，纯文本解析三源做集合恒等：

1. 从 `webui/src/router.tsx` 正则提取 `path: '...'` → 路由集 R；
2. 从 `webui/src/components/layout/app-shell.tsx` nav 数组提取 `to: '...'` → 导航集 N；
3. 从 `scripts/webui_acceptance.py` `PAGE_SPECS` 提取 `"route": "..."` → 验收集 A；
4. 从 `webui/src/locales/zh-CN/common.json` + en 提 `nav.*` 键 → 字典集 D（双语键集全等另断言一条）；
5. 断言 `R == N == A` 且顺序一致（导航序=路由序）；断言九页的 `nav.<k>` 均在字典；
6. 追加两条行为锁（离线可断）：router.tsx 必须含 `defaultNotFoundComponent`（正则存在性）；`grep 站内无新增裸 <h1`（PageHeader 唯一性，白名单=PageHeader 自身）。

acceptance 侧最小增量：PAGE_SPECS 加一条 `{"name":"notfound","route":"/no-such-route","ok":[],"graceful_extra":["<新 404 卡的 zh 文案>"]}` 负例（现 SKIP 逻辑会先查 nav_hrefs——负例需豁免该行，改 3 行）；同时把「路由未构建→SKIP」改为 FAIL（或 --allow-skip 显式开关），否则清单漂移永远绿。

---

## 九、新发现台账（七要素）

> 编号 F12-xx；「建议改法」before→after 可直接落手。验证命令均为只读/可复跑形态。

**F12-01｜P1｜`webui/src/components/layout/app-shell.tsx:71-73`（配合 :105-121）**
- 锚点：`'sticky top-0 hidden h-svh w-60 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground md:flex'`
- 根因：侧栏 `hidden md:flex` 且顶栏 `md:hidden` 分支无任何页面切换件——<768px 视口（手机）九页只能手敲 hash（P2-12 复验仍在）。
- 建议改法：在 `<div className='flex min-w-0 flex-1 flex-col'>` 内 `</header>` 与 `<main>` 之间插入与侧栏**同数据源**的横滚导航条：
  ```tsx
  {/* 移动导航（<md）：与侧栏共用同一 nav 数组，横向滚动，当前项实心 */}
  <nav className='flex gap-1 overflow-x-auto border-b px-2 py-2 md:hidden' aria-label={t('nav.overview')}>
    {nav.map((item) => (
      <Link key={item.to} to={item.to}
        className='shrink-0 rounded-full px-3 py-1 fs-caption text-muted-foreground [&.active]:bg-primary [&.active]:font-medium [&.active]:text-primary-foreground'
        activeProps={{ className: 'active' }}>
        {item.label}
      </Link>
    ))}
  </nav>
  ```
  （knowledge 子分组深链在移动条暂不复制——集合 chips 页内已有，避免双入口；间距全在 4px 栅格内，不过宪法门。）
- 验证：`node webui/scripts/layout-constitution.mjs`（exit 0）+ `python scripts/webui_acceptance.py --pages all`（viewport 若仍 1440 则加跑一条 390px 变体或在 check_page 里断言移动条 `nav[aria-label]` 可见）。
- 回归锁：无。

**F12-02｜P1｜`webui/src/pages/calls.tsx:89-90`、`tokens.tsx:73`、`affinity.tsx:64`、`logs.tsx:56-57`、`memory-graph.tsx:40-43`、`knowledge.tsx:104-106`**
- 锚点：`const [window, setWindow] = useState<StatsWindow>('24h');`（calls/tokens 同形）、`const [order, setOrder] = useState<'desc' | 'asc'>('desc');`、`const [sourceFilter, setSourceFilter] = useState('');`、`const [selectedId, setSelectedId] = useState<string | null>(null);`、`const [page, setPage] = useState(1);`
- 根因：除 `/knowledge?collection` 外，全部关键视图状态活在内存——刷新丢、不可分享、前进后退不记视图（「统一参数」在 UI 最深的一层破口）。
- 建议改法（样板已存在=knowledge:99-102/123-125）：①router.tsx 各 `createRoute` 加 `validateSearch`（按第三节键名表，缺省省略、非法值归一）；②页面 `useState` 换 `useSearch({ from: '<route>' })` + `navigate({ search: {...} })`；③memory-graph `selectedId`→`node`、typesHidden→`types`（编码可见集）；④logs 仅 `source/category` 进 URL，游标保留 sessionStorage 并在注释写明「设计裁定：游标不分享」。
- 验证：`cd webui && npm run typecheck`（validateSearch 类型会编译期抓漏改）；acceptance 增一条「goto `#/calls?window=7d` 断言 7 天按钮为选中态」的 ok_dom 用例（属脚本改法，落手席执行）。
- 回归锁：无（collection 一项也只有注释无测试）。

**F12-03｜P2｜`webui/src/router.tsx:92-96`**
- 锚点：`export const router = createRouter({ routeTree, history: createHashHistory(), defaultPreload: 'intent', });`
- 根因：无 `defaultNotFoundComponent`、无路由级 notFound → 未匹配 hash 渲染库内置裸 `<p>Not Found</p>`（库源码 renderRouteNotFound.js:14-24 实证），无 i18n/无样式/无回首页。
- 建议改法：rootRoute 挂 `notFoundComponent`（或 createRouter 加 `defaultNotFoundComponent`）：
  ```tsx
  function NotFound() {
    const { t } = useTranslation();
    return (
      <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
        <PageHeader title={t('state.notFound')} />
        <SectionCard title={t('state.notFoundHint')}>
          <Link to='/' className='fs-body text-primary hover:underline'>{t('state.backHome')}</Link>
        </SectionCard>
      </div>
    );
  }
  const rootRoute = createRootRoute({ component: RootLayout, notFoundComponent: NotFound });
  ```
  + 双语字典补 `state.notFound`（「页面未找到」/「Not found」）、`state.notFoundHint`、`state.backHome`。
- 验证：`python scripts/webui_acceptance.py`（按第八节加负例路由后）；或人工 `#/nope`。
- 回归锁：无。

**F12-04｜P2｜`webui/src/pages/plugins.tsx:128` 与 `webui/src/components/settings/settings-dialog.tsx:87`**
- 锚点：`<h2 className='fs-page'>{group.name}</h2>`；`<h2 className='flex items-center gap-2 fs-page'>`
- 根因：五档阶梯无 h2 专档，两处区块/弹窗标题直接吃页标题档 fs-page(18px)——组标题与页 h1 同字号（一席发现的扩展穷举：全站就这两处）。
- 建议改法：`before: h2 className='fs-page'` → `after: h2 className='fs-card'`（14px w600，与卡标题同径——组头本就该是卡级），两处同改。若用户裁定组头须高于卡题，则在 index.css 加第六档（牵动宪法门，先问再动）。
- 验证：`node webui/scripts/layout-constitution.mjs`（五档白名单内不违规）。
- 回归锁：无。

**F12-05｜P2｜`webui/src/pages/calls.tsx:102-131,148-181` + `webui/src/pages/tokens.tsx:89-107,125-211`**
- 锚点：`<h1 className='fs-page'>{t('calls.title')}</h1>`（tokens.tsx:90 同形）
- 根因：两页绕开 patterns.tsx「唯一外壳」——页头手搓、卡壳裸 Card、窗口切换器复制粘贴两份（S1/S2/S3）——「统一架构」的前端版在这两页失守。
- 建议改法：calls/tokens 页头改 `<PageHeader title subtitle actions={<WindowSwitch .../>}/>`；`WindowSwitch` 从 calls.tsx 提出到 patterns.tsx（props: value/onChange/labels 前缀），tokens 删内联版复用；两页 `Card+CardHeader+CardTitle className='fs-card'` 全部换 `SectionCard title=... description=...`（视觉零变化，壳归一）。
- 验证：`node webui/scripts/layout-constitution.mjs` + `cd webui && npm run typecheck` + acceptance `--pages calls,tokens` 文案标志不变（ok 标记「窗口内调用」「窗口总量」保持渲染即通过）。
- 回归锁：无。

**F12-06｜P2｜`webui/src/pages/affinity.tsx:66-69`（配合 `plugins/bot_unified_runtime/control_plane/webui_stats.py:234-236`）**
- 锚点：`() => controlApi.affinityBoard({ limit: 100, order })`
- 根因：请求 100/缺省 50/后端上限 200 三处口径互不一致；total>100 时页脚显真 total、列表静默截 100 行，无截断提示无翻页——同卡两口径不诚实（D3）。
- 建议改法：短期 `before: limit:100 无提示` → `after:` 渲染后判 `data.items.length < data.total` 时 SectionCard 底部补一行 `<p className='fs-caption text-muted-foreground'>{t('affinity.truncatedHint', { shown: data.items.length })}</p>`（字典新键「仅列出前 {{shown}} 人，翻页接入前不冒充全量」）；中期接 `Pager`+URL `page`（随 F12-02）。
- 验证：`python scripts/webui_acceptance.py --pages affinity`（有数据环境见列表）+ 单测（落手席在 tests/ 增设截断提示断言）。
- 回归锁：无。

**F12-07｜P2｜IA 诚实双错｜`webui/src/pages/dashboard.tsx:93-94,101-112` + `plugins/bot_unified_runtime/control_plane/_app.py:313-320` + `webui/src/locales/zh-CN/common.json:30-33`**
- 锚点：`const health = useSemanticQuery<HealthData>(['health'], () => controlApi.health(), ...)`；`dependencies=[Depends(_auth_dependency(auth, provisioned))]`；`"adminToken": "主令牌（读写）"` / `"roToken": "只读令牌"`
- 根因：`/admin/api/v1/health`、`status/bot` 只收主令牌，其余 `/api/v1/*` 双令牌皆收 → 仅持第二槽位令牌的用户 dashboard **整页** auth 卡（blocking 不分卡降级），其余八页正常=「入口在、这一页对他说必 401」；且槽位命名双虚——「只读令牌」实为 super_admin 令牌、「读写」在 WebUI 无任何写端点。
- 建议改法：①dashboard blocking 分面降级——health/botStatus 任一 auth 时**不进 blocking**，两卡各自 `withFallback` 显态（其余查询 blocking 逻辑保留）：`before: queries 含 health/botStatus` → `after: const blocking = [calls, calls7d, tokens, latency].find(...)`；②字典措辞对齐后端真相：`"adminToken": "管理令牌（本机全部数据面可读）"`、`"roToken": "备用令牌（超级管理员，可选）"`+hint 同步（en 同改）；③（可选裁定）后端 health/status 挂 `_v1_read_dependency` 与其余读面归一——涉控制面域，本席只登记不施工。
- 验证：`powershell ... dev.ps1 -Task test`（control_plane 相关域）+ 实令牌双槽位手测（重启后）。
- 回归锁：无（test_webui_http.py 只测主令牌路径）。

**F12-08｜P2｜`webui/src/lib/format.ts:26-38`（消费面 dashboard.tsx:147,159、affinity.tsx:56、logs.tsx:290）**
- 锚点：`return date.toLocaleString('zh-CN', { hour12: false });`
- 根因：①全站时刻默认浏览器本地时区零标注，唯 calls 脚注带后端 tz（D1，两口径最误导者）；②logs 行内 formatTime 无日期跨日误读；③en 界面仍 zh 日期数字（locale 硬编码）。
- 建议改法：①`formatDateTime(iso, { tzLabel?: string })` 增参或在 PageHeader/卡片脚注统一挂「浏览器本地时区」一次性说明（最省=app 底部 footer `t('app.footer')` 拼 ` · {Intl.DateTimeFormat().resolvedOptions().timeZone}`）；②logs 行日期列改 `formatDateTime`（含日期）或首行/跨日插日期分隔行；③`toLocaleString(i18n.language === 'en' ? 'en-GB' : 'zh-CN', { hour12: false })`（i18n 实例可 import，纯函数改造）。
- 验证：acceptance 文案标志不含时间串不受影响；落手席补 format 单测。
- 回归锁：无。

**F12-09｜P3｜`webui/src/pages/knowledge.tsx:99-102`**
- 锚点：`search.collection && available.some((item) => item.id === search.collection) ? search.collection : (available[0]?.id ?? null);`
- 根因：URL 指向非法/已停用 collection 时页面**静默**改用默认集合而不回写 URL——分享出去的链接「所见≠所得」，回退不可见。
- 建议改法：`after:` `useEffect` 检测 `search.collection !== selected` 时 `navigate({ to:'/knowledge', search:{ collection: selected }, replace: true })`（并把此裁定写进 F12-02 统一约定的「非法值改写 URL」条款）。
- 验证：`#/knowledge?collection=__bogus__` 地址栏自动清洗为实际集合。
- 回归锁：无。

**F12-10｜P3｜`webui/src/components/layout/app-shell.tsx:94`（+ Link.js:34-41 子集高亮语义）**
- 锚点：`{hasMoreCollections && <NavSubItem label={t('nav.moreCollections')} />}`
- 根因：「更多…」链接 search=`{}` 为任何当前位置 search 的子集 → 在 /knowledge 全状态恒 active，与选中集合子项双高亮；点击落默认集合语义暧昧（「更多」实为「重置」）。
- 建议改法：`before: <NavSubItem label={t('nav.moreCollections')} />` → `after:` 改为普通 `<button onClick={() => navigate({ to:'/knowledge', search:{ collection: undefined } })}>`（非路由项不给 href/active），或给它 `activeOptions={{ includeSearch: true, exact: true }}`。
- 验证：手测 /knowledge?collection=x 时仅选中项+父项高亮。
- 回归锁：无。

**F12-11｜P3｜`webui/index.html:13-14`（document.title/favicon 域）**
- 锚点：`<title>守岸人控制台</title>` + `<link rel="icon" href="data:," />`
- 根因：标题不随路由变（九标签页同名书签不可辨）、无 meta description；favicon 置空是诚实（无素材）但可一行改 `data:` SVG「守」字圆点零资产引入。
- 建议改法：router 层订阅 `router.subscribe('resolved', ({ toLocation }) => { document.title = \`${t(routeTitle(toLocation))} · 守岸人控制台\`; })`（title 键=路由元数据表，或各页 useEffect 上抛）；favicon 内联 32×32 SVG data URI。
- 验证：切换路由看标签页标题；无。
- 回归锁：无。

**F12-12｜P3｜语言切换入口缺失｜`webui/src/lib/i18n.ts:32-52`**
- 锚点：`detection: { order: ['localStorage', 'navigator', 'htmlTag'], ... }`
- 根因：en 全量字典 238 键与 zh 实测全等（本次 node 程序化 diff），但界面无任何语言切换控件——只能清 localStorage `i18nextLng` 或改浏览器语言，功能存在 IA 不可见。
- 建议改法：顶栏 ThemeSwitch 旁加一枚 `Languages` 按钮二态切换 `i18n.changeLanguage(lng === 'zh-CN' ? 'en' : 'zh-CN')`；或在 i18n.ts 注释明确「en 为开发期镜像非承诺面」并在 settings 面板补一行（择一裁定）。
- 验证：目验 + locale 键集 diff 脚本可收编为常驻测试。
- 回归锁：无（键集全等目前靠自觉）。

**F12-13｜P3｜清单四方副本无锁｜`router.tsx` / `app-shell.tsx:46-56` / `webui_acceptance.py:51-88,351`**
- 根因：同一路由清单一式四份；acceptance 对「导航无该链接」的路由判 SKIP 不判 FAIL（:262-265）——新页漏挂导航/漏注册可永远绿。
- 建议改法：落第八节 `tests/test_webui_ia_gates.py`（R==N==A==D 恒等+顺序断言+defaultNotFoundComponent 存在性+裸 `<h1>` 白名单），acceptance SKIP 改 FAIL 或 `--allow-skip` 显式化。
- 验证：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_webui_ia_gates.py -p no:cacheprovider --basetemp="$TEMP/ia-gates"`。
- 回归锁：本条即锁的设计（现状=无）。

---

## 十、裁定优先级建议

- P0：**0 条**（未发现白屏/崩溃级；404 非白屏是壳内裸英文行，降级 P2）。
- P1：F12-01（手机无导航）、F12-02（深链全面缺位，含最小锁先行）。
- P2：F12-03（404 兜底卡）、F12-04（h2 同字号两处）、F12-05（两页骨架收编）、F12-06（好感截断）、F12-07（令牌槽位双虚标+dashboard 整页拒）、F12-08（时区/日期口径）。
- P3：F12-09~13。
- 交叉引用：P2-12（移动导航）本席独立复验=**仍在**；一席 h1/h2 问题本席穷举补 settings-dialog 第二处；「九页」数以实盘路由表=9 条路径核实，与文档口径巧合一致（非抄录）。

# UNI1 · 前端「同一判据四套实现」收口实做台账

> **快照口径**：`date` 实跑 = `Sat Sep 19 19:29:17 2026`；`node -v` = `v26.7.0`。
> 本席性质：**写代码**（六统一之前端片）。§三的锚点计数为本席落盘后复跑 grep 的实况，非估。
> 输入件 = `F23-frontend-testable-draft.md`（17:05 快照的**提案稿**）；其结论逐条对过今日现树，
> 过期部分见 §一。

---

## 〇、一句话总裁决（fix1 按评审 C-1/M-1/M-3 修订：原版「各只有一处真值」为超卖，此处是实况）

单源已立、尚未全清：**reason→人话**只剩 `lib/semantics.ts` 一份（白名单==双语 locale 键集三向对账
钉死，无死条目）；**时间窗枚举+标签+跨度语义**单源在 `lib/labels.ts`，已收口所辖 calls/dashboard/
plugins/latency 各页并于 **fix1 迁完 tokens.tsx**，残余 = `memory-graph.tsx` 一处 `WINDOWS` 手抄
（只读面，shrink-only 棘轮钉「只减不增、新抄即红」）+ locale 两份镜像表 `calls.window.*`（fix1 后
已零生产消费者，待另批删表）/`memoryGraph.window.*`（值由锁钉死与单源相等）；**未知符号**单源在
`format.ts UNKNOWN_VALUE`，残余 1 处字面量 = `pages/logs.tsx:98`（只读面；台账 §四-3 登记时点坐标
为 :293，logs 席改动后现坐标如左。tokens 页两处已于 fix1 清除）。
**跨语言同值**（窗枚举/跨度/桶/reason 码 ⊆ 白名单）自 fix1 起由 pytest
`tests/test_webui_labels_backend_parity.py` 锁定（C-1 裁定：control_plane 三件 .py 本波未入库，
JS 直读=干净克隆 ENOENT 红；pytest 侧缺文件显式 skip 并点名路径），`node --test` 套件恢复**密封**
（只读 webui/ 以内，已用无 plugins/ 兄弟树的克隆模拟实跑 29/29 证明）。
`node --test` 29 例全绿（labels 仍 8 例，下限不变），pytest parity 新增 5 例，常驻门宪法 5 例不变。

---

## 一、草案核验：哪些结论已经过期（落手前逐条实测）

| 草案主张 | 今日现树实况（19:14 复核） | 本席处置 |
|---|---|---|
| §一.1 三份同体正则 `/HTTP 404/.test(message)` | **已由他席收口**：`lib/semantics.ts:15 isNotFound(state)` 走 `state.status === 404`，knowledge:171/260、plugins:168、memory-graph:181 全部改引它，`grep "HTTP 404" webui/src` 只剩注释与测试负样本 | 不再动；草案 §3.1/3.2 的 `not-found.ts` **不建**（建了就是第五份真值 + 第二条「写了没接线」） |
| §二 error 相位缺 status/code | **已落**：`use-semantic-query.ts:15,52` 已透 `status?/code?`（本席只读核验） | 零改动（该文件也只读） |
| §四 需改 `package.json` 的 `test` 入口为通配 | **已落**：`package.json:11` = `node --test "src/**/*.test.ts"`，常驻门 `test_pure_function_tests` 同形跑通配，`test_package_json_entries_match_gates` 断言通配串 | 不改（只读文件，且无需改） |
| §六.1 冲突预警（`graph-layout.test.ts` 点名断言会红） | 该断言已改成锁通配，预警不成立 | 无 |
| §一.2/§一.3 四套 reason、三份枚举四份标签表、11 处 `'—'` | **全部成立**，逐处坐标已复核 | 本席收口，见 §二 |
| §三.5 新建 `empty-state.ts`、§3.1 新建 `not-found.ts`、§3.7 新建 `window-switcher.ts` | 三件新模块与仓库「删垫片、删再导出层」的方向相反 | 一律不建：语义上收进**既有** `semantics.ts`/`format.ts` + 唯一一个新件 `labels.ts`（标签/枚举本就无归宿，且任务书点名可写） |

---

## 二、四项判据的单源落点（收口后坐标，19:29 复跑 grep）

### 1) reason 码 → 人话：4 套 → 1 函数 + 1 名单

| 角色 | 落点 | 说明 |
|---|---|---|
| 白名单（唯一） | `webui/src/lib/semantics.ts` `KNOWN_REASONS`（18 码，逐字从 `semantic-state.tsx` 上收） + `isKnownReason()` + `reasonKey()` | 名单注释带后端真相源指针 |
| 取词（唯一） | 同文件 `describeReason(reason, t)` | 已知码→译文；未知码→原码；locale 缺键→原码（**绝不把 `reason.xxx` 甩上屏**）；null/''→'' |
| 消费面 ① | `components/semantic/semantic-state.tsx:70`（降级卡第二行） | 原 `reasonKey` 函数**已从组件删除** |
| 消费面 ② | `pages/dashboard.tsx:43` `fallbackLine`（一行式） | 原「借名单 + 自拼回退」6 行 → 1 行 |
| 消费面 ③ | `pages/plugins.tsx:105-115` `reasonSuffix`（组级不可用行） | 原**绕过白名单**的 `reasonText` 已删除，本页只拼「：」外壳 |
| 文案本体 | `locales/{zh-CN,en}/common.json` 的 `reason.*`（各 18 键） | 与名单的等值由测试三向对账 |

锁：`semantics.test.ts` 新增 7 例——名单无重复且双语有值 / 三向对账（白名单 == zh 键集 == en 键集）/
describeReason 四态 / 缺键回退原码（并演示收口前写法会显键）/ **收口前后逐码等输出**（把旧
dashboard 与旧 plugins 两套实现作为夹具在同一份 locale 上逐码比对，证明「行为不变」不是口头承诺）/
COMMON_GRACEFUL 四串键位锁 / **双语全键集递归对账**。

### 2) 时间窗枚举 + 标签：3 份枚举 + 4 份标签表 → `lib/labels.ts`

| 件 | 落点 | 消费者 |
|---|---|---|
| 枚举 | `STATS_WINDOWS`/`GRAPH_WINDOWS`/`BUCKETS`（`as const`，联合类型由数组派生） | calls.tsx、tokens.tsx（fix1 迁入）、`BucketCode`/`StatsWindowCode` 类型 |
| 缺省 | `DEFAULT_WINDOW`/`DEFAULT_BUCKET` | calls.tsx useState、dashboard.tsx 取数与标签、tokens.tsx useState（fix1） |
| 跨度 | `WINDOW_SECONDS`（`all: null` 不造上界） | **pytest parity 门直读后端对账**（fix1 移交，见 `tests/test_webui_labels_backend_parity.py`）：`metrics.py:89 _WINDOW_SECONDS`、`webui_stats.py:46 _WINDOW_SECONDS`+`:47 _BUCKETS`、`webui_memory_graph.py:43 _WINDOWS` |
| 名实 | `WINDOW_IS_ROLLING`（有限窗=true） | 前端侧 `labels.test.ts` 自洽锁；后端 `now - timedelta` 口径对账在 pytest 侧，配「标签不得含今日/当天/本周/本月/今天、en 不得匹配 today」的文案门 |
| 标签 | `WINDOW_LABEL_KEYS` → 新命名空间 `window.{24h,7d,30d,all}`；取词口 `windowLabel(t, code)`/`bucketLabel(t, code)`；`nextBucket` | calls.tsx:49、dashboard.tsx:224-225（卡标题与取数窗口引同一变量 `DETAIL_WINDOW_24H/7D`，值不变故 queryKey/缓存键不变）、tokens.tsx 按钮（fix1，见 §五-3′） |

「近 24 小时」这一枚**前席的滚动窗改名本席保持不动**（`labels.test.ts` 还加了一条「zh 标签必须以『近』
开头、en 必须以 `Last ` 开头」的正向门，防止它被改回「今日」）。

### 3) 未知值渲染：11 处字面量 → `format.ts` 的 `UNKNOWN_VALUE`

- `format.ts` 内 5 处 `return '—'` 改 `return UNKNOWN_VALUE`（同字节），符号定义只此一处（带 U+2014 与「空≠未知」语义注释）。
- 页面侧「先判 null 再手写符号」的重复判定，改为**直接走格式化函数**：`dashboard.tsx`（active_users/last_message_at 两行）、`latency.tsx`（ema_ms/latency_ms 两格）——格式化函数本就对 null 返回该符号，输出逐字节不变，删掉 4 处平行判定。
- 无格式化函数可接的纯文本位改引符号常量：`calls.tsx:77`（空列表行）、`calls.tsx:211`（未知用户标签位）、`latency.tsx:25`（渠道名空串位）。
- 桶联合 `'hour' | 'day'` 在 `formatBucket` 签名里是第二份枚举，已改用 `BucketCode`（type-only import，运行时零依赖不变）。

### 4) 新模块的准入自证

`labels.ts` 是本轮唯一新增文件（任务书点名可写）。它成立是因为**标签与枚举在既有文件里无归宿**：
`semantics.ts` 管「数据态判定」，`format.ts` 管「值怎么印」，把「有哪些窗、叫什么」塞进任一个都是错放。
草案另三件新模块（`not-found.ts`/`reason.ts`/`empty-state.ts`/`window-switcher.ts`）全部**未采纳**，
语义按上文归进既有文件；同时本席拒绝写入无消费者的 `safeStatsWindow`（先写后删，见 git-free 记录）。

---

## 三、实跑取证（三条验证命令 + 门形状 + 双语对账）

```
$ cd webui && npx tsc --noEmit -p tsconfig.app.json     → 无输出  TSC_EXIT=0
$ cd webui && npx tsc --noEmit -p tsconfig.node.json    → 无输出  TSC_NODE_EXIT=0（常驻门也跑这个）
$ cd webui && npm run lint:layout                        → exit=0，stdout 含「全部通过」
  版式宪法机器门：全部通过（自测 58/58；hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0 /
  margin 同栅格 / 圆角三档+full 白名单 / 同元素双写=0 / …）
$ cd webui && npm test                                   → TEST_EXIT=0
  ℹ tests 29  ℹ pass 29  ℹ fail 0  ℹ cancelled 0  ℹ duration_ms 192.5721
$ cd webui && node --test --test-reporter=tap "src/**/*.test.ts"   # 与常驻门同形（TAP 摘要行）
  # tests 29 / # pass 29 / # fail 0 / # cancelled 0        GATE_SHAPE_EXIT=0
$ cd webui && node -e "<递归拉平两份 locale 键集双向 diff>"        # 双语对账独立复跑（不依赖测试）
  zh keys=255  en keys=255   zh-only=[]   en-only=[]       LOCALE_PARITY_EXIT=0
```

基线对照（改动前实跑）：`npm test` = `pass 14 / fail 0`（graph-layout 7 + semantics 7）。
新增 15 例 = semantics +7、labels +8。

**未跑**：`npm run build`、`tsc -b`、`pytest`、任何 git 写操作（按硬约束）。
`tests/verify_hashes.py` 覆盖度复grep：`grep -n "webui\|dist"` → **0 命中**，本轮 .ts/.tsx/locales 改动不触发哈希册重录。

---

## 四、注册残余（只读面，本席不动；逐条给坐标与迁法）

| # | 坐标（19:29 复跑） | 还差什么 | 为什么本席不动 |
|---|---|---|---|
| 1 | ~~`pages/tokens.tsx:25/:86/:116`~~ **✅ fix1 已迁**（`STATS_WINDOWS`+`DEFAULT_WINDOW`+`windowLabel`，该页转 §三 严检清单） | — （迁后 `calls.window.*` 失去最后一个消费者 → 转本表 #11） | — |
| 2 | `pages/memory-graph.tsx:26`、`:51`、`:128`、`:278` | 枚举改 `GRAPH_WINDOWS`、取词改 `windowLabel`（含 `all`）；迁完删 `memoryGraph.window.*` | 只读面（graph 席在飞）。残余由 shrink-only 棘轮管「只减不增、新抄即红」（fix1 改造，评审 I-2） |
| 3 | `pages/logs.tsx:98`（`lastCursor ?? '—'`，登记时点坐标 :293，logs 席改动后漂移） | 改 `?? UNKNOWN_VALUE`（from `@/lib/format`） | 只读；改后同字节 |
| 4 | ~~`pages/tokens.tsx:74`、`:210`~~ **✅ fix1 已清**（直 `formatInt(block.value)`，null 路径同字节，取证见 UNI1-fix1 台账） | — | — |
| 5 | `lib/api-client.ts:396,437`（`GraphWindow`/`StatsWindow` 联合类型第二份枚举源） | 让 api-client `import type` 自 labels，或页面直接从 labels 取类型 | 任务书点名 api-client 只读。现两者值集**由 `labels.test.ts` 枚举次序锁 + `tests/test_webui_labels_backend_parity.py` 后端对账双重夹住**，不会漂 |
| 6 | `hooks/use-semantic-query.ts:45-49`（503+码 / 401·403 两组字面判定散在钩子里） | 若要再上一谓词（草案 `classifyError`），先在 `semantics.ts` 里长出来再换钩子消费 | 只读 + 现状判定与 `isNotFound` 同源无分叉，本席无证据说它错 |
| 7 | `pages/knowledge.tsx:34-40 DISABLED_REASON_LABEL_KEYS` | **不是** reason→人话族的重复：那是「集合禁用短标签」（码空间含 `no_dedicated_store`，两码合一短词），与 `describeReason` 的整句人话语义不同源；若要并轨，需先裁「短标签 vs 整句」的口径 | 只读 + 语义本就不一致，强行并轨会改知识库页文案 |
| 8 | `calls.tsx:77` 空 TopList 现仍显 `UNKNOWN_VALUE`（「值未知」）而非「暂无数据」（「查过了、是空」） | 换成 `t('state.noData')` 即根治 F9-P1-3；该串在验收 `COMMON_GRACEFUL` 白名单内，**安全但属用户可见文案变更** | 本席授权只覆盖「符号上收，不动语义」；改文案越出「除名实不符外行为不变」的硬约束，故只路由 + 留行内注释 |
| 9 | `calls.tsx:211`（未知用户显 `—`）与同栏 `:199`/`:205`（未知能力/会话显 `（能力未知）`/`（会话未知）`）三态不同形 | 补 `calls.unknownUser` 键并统一为「（用户未知）」 | 新增文案 = 用户可见变更，越权；且双语键集需同批改（本席未加键） |
| 10 | 草案 §三.9(c) 的 `SectionCard` 空态/`plugins.emptyGroup`「暂无条目」 | 不动是对的：`暂无条目` 在 `webui_acceptance.py:78` 的 **ok（数据态）** 判据里，统一成「暂无数据」会让 plugins 页从 data 掉到 graceful | 本席按草案 §七 的「不可动文案清单」执行，未触碰 |
| 11 | locale `calls.window.{24h,7d,30d}`（zh/en） | fix1 迁完 tokens 后**零生产消费者**（calls 页前批已换 `window.*`），删表是收尾动作 | locale 本波只读（评审席在飞）；删前由 `labels.test.ts` 镜像等值锁钉住，漂一字即红 |
| 12 | `metrics.py:200/:205` 嵌套诊断 `reason: "not_recorded_reliably"`（attempt_total/failover_calls 质量块，parity 门首跑实抓） | 前端不消费该字段 → 永不上屏，无需进白名单 | api-client `TokenBlock` 无 reason 字段、两键全树 0 消费者（grep 取证在 UNI1-fix1 台账）；pytest 侧登记**防腐豁免**（码一旦出现在 webui/src 即转红），防未来偷偷上屏 |
| 13 | `pages/latency.tsx:92` `t('latency.historyUnavailable', { reason: … })` 把裸码插进整句（`not_persisted` 与他页 `describeReason` 面孔不一，评审 M-4 补登） | 整句内嵌译名 vs 裸码留痕，属文案口径裁决 | 改渲染=用户可见变更，越出「不可动文案清单」授权；fix1 起登记在此，等裁定 |

---

## 五、用户可见变化清单（穷举，共 3 串 + 1 处不可达角落）

| # | 位置 | 前 | 后 | 依据 |
|---|---|---|---|---|
| 1 | calls 页窗口按钮 ×3（zh） | 「24 小时」/「7 天」/「30 天」 | 「近 24 小时」/「近 7 天」/「近 30 天」 | 任务书第 2 项「一份真值 + 不得暗示自然日」；单源取值取**已带滚动口径**的那一份（memoryGraph 与 dashboard 前席改名后的现值），另两份向它对齐。「24 小时」不算撒谎，但四表并存的下一刀必然是撒谎，本席按「统一到不带歧义的措辞」执行 |
| 2 | 同上（en） | 24 hours / 7 days / 30 days | Last 24 hours / Last 7 days / Last 30 days | 同 |
| 3 | tokens 页窗口按钮（借用同一 locale 键） | 24 小时 等 | 近 24 小时 等 | `tokens.tsx:116` 本就 `t(\`calls.window.*\`)`——本席改的是**它借的那份表**的值，故它被动对齐；这**正是**它对齐后应当如此（该页窗口同样是滚动窗），且与 #1 同源同批 |
| 3′ | （fix1 追加）tokens 页改直取 `window.*` + `DEFAULT_WINDOW` + `STATS_WINDOWS` | 「近 24 小时」等（经 calls.window.* 镜像） | **逐字不变**（直取 window.* 同值） | 操作者所见零变化；`queryKey ['stats-tokens', window, 'page']` 缺省值仍 `'24h'` → 缓存键不变。逐键对照与双语值表在 `UNI1-fix1.md` 台账 §三 |
| — | dashboard 两窗标题 | 「近 24 小时」「近 7 天」 | **逐字不变**（只是键从 `dashboard.overview.windowToday` 换成 `window.24h`） | 前席改名保持 |
| — | memory-graph chips / 各页空态 / 降级卡 / 未知符号 | — | **逐字不变** | 符号与取词等价改写；`UNKNOWN_VALUE` 与 `'—'` 同码点 U+2014 |

**一处不可达角落的行为变化（诚实披露）**：`SemanticState` 降级行在「码在白名单、locale 却缺键」时，
收口前会把 i18n 键本身 `reason.missing_source` 显示给用户，收口后显示原码 `missing_source`。
该角落被 `reason 三向对账` 锁成不可达（名单==双语键集），且新行为更符合「绝不把内部键甩上屏」，
故采纳；测试 `describeReason：locale 缺键时回退原码` 把两种写法并置留证。

---

## 六、常驻门改动（唯一越界件，按任务书授权执行）

`tests/test_webui_constitution.py:114` `assert passed >= 14` → `>= 29`，消息里的基线分解同步为
「graph-layout 7 + semantics 14 + labels 8」。**理由**：本席新增 15 例（§三），棘轮下限随实跑上抬；
只动这个数字与其说明串，未动该文件其它任何断言（该文件归主会话）。
任务书原文：「your new tests should raise that number, and you may raise the floor … record why」。

`test_package_json_entries_match_gates` 未放宽（它锁的是通配串，本席没改 `package.json`）；
草案 §六.1 预警的冲突因此不存在。

---

## 七、纪律自证

- 只写授权清单内文件：`lib/{semantics,format,labels}.ts`、`lib/{semantics,labels}.test.ts`、
  `components/semantic/semantic-state.tsx`、`pages/{dashboard,calls,latency,plugins}.tsx`
  （`pages/affinity.tsx` 复核后**无 `—`、无枚举、无 reason 判定**，故未改）、
  `locales/{zh-CN,en}/common.json`、本台账；加一处授权例外（§六）。
- 未碰：`api-client.ts`、`hooks/**`、`pages/{logs,knowledge,memory-graph,tokens}.tsx`、
  `components/**`（semantic-state 除外）、`index.css`、`scripts/layout-constitution.mjs`、`package.json`、任何 `.py`（§六除外）。
- 新代码零 `enum`、零参数属性、零 `namespace`（strip-only 约束）；`labels.ts`/`semantics.ts` 运行时零依赖
  （只 `import type`），故 `node --test` 直跑；无 git 写、无删除、无 build。
- 未削弱任何既有断言：原 14 例逐条保留（semantics 7 例文本未改，仅追加导入与新增用例）。

## 八、删除面的引用复核（19:3x 复跑，防「删了导出、留了消费者」）

- `grep -rn "reasonKey|describeReason" webui/src` → 除 `lib/semantics.ts` 自身与其测试外，
  只剩三处**消费**（`semantic-state.tsx:70`、`dashboard.tsx:43`、`plugins.tsx:106`），**0 处**再从
  `semantic-state` 引 `reasonKey`。
- `grep -n "SemanticState" webui/src/**` 九页 + `error-boundary.tsx` 全部只引 `SemanticState`/`openSettings`
  （二者导出未动），故本席删掉的组件内 `reasonKey` 无悬挂消费者。
- 最硬的一层是**全项目** `tsc --noEmit -p tsconfig.app.json` = **exit 0**（含只读面 tokens/logs/
  memory-graph/knowledge/app-shell/router 一起编译）——只读页未改一行而整体类型闭合，即收口未砸邻居。
- `tests/test_webui_constitution.py` 改后 `ast.parse` = `PY_SYNTAX_OK`（禁 pytest，故只做纯解析零写入，
  `PYTHONDONTWRITEBYTECODE=1` + venv python）。


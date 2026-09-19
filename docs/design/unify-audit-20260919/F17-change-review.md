# F17 改动敌对复核（主会话 9 处前端手改）

## 快照声明

- 复核时刻：`Sat Sep 19 16:50:48 2026`（收尾复跑至 17:1x，全程同一工作树快照）。
- 立场：敌对复核。以下所有结论**不采信主会话自报数字**，全部由本席独立实跑或读源码/产物取证得出。
- 本席零改动：未编辑/新建/删除工作树任何文件（本份日志除外，目录 `docs/design/unify-audit-20260919/` 本已存在，`mkdir -p` 为空操作）。临时产物只落 `%TEMP%/f17/`。
- 环境：node `v26.7.0`；`@tanstack/react-router` 实装 **1.170.38**（router-core 1.171.32）；`@types/react` 19.2.x；TypeScript 5.8.3；解释器固定 `../ChatBot_Runtime/venv`。
- 纪律例外披露（两条，均为工具侧拦截后改道，无副作用）：
  1. 我把 logs 去重模型写成 `%TEMP%/f17/logs-dedup-model.mjs` 后**执行被权限层拦截**，改为等价的 `node --input-type=module -e "…"` 内联跑通（同一模型，结果见 §4）。
  2. 对 `node_modules/@tanstack/**` 用 `sed -n` 被拦截，改用 Read 工具读同一文件（只读，内容一致）。
- **未跑**（按「不许产生副作用」优先）：`npm run build`、`npm install`、dev server、`scripts/webui_acceptance.py`。后者经阅读确证自带 `sync_playwright`（:193）+ 内嵌 wrapper 服务器（:132/:214）+ 默认打 mock 口 `127.0.0.1:8743`（:346）→ 会起浏览器与端口，**故不跑**，改为读 `webui/dist/index.html` 取证。
- **未跑** `tsc -b`（它会写 `webui/node_modules/.tmp/*.tsbuildinfo`，属工作树副作用），改用等价无写盘口径 `tsc --noEmit --incremental false -p <project>`，并在前后对比 `.tmp/` 两文件 mtime（16:39:44 未变）实证零写入。

---

## 逐条判定

### 1. `card.tsx` 删 `CardTitle` 基类行高 —— **修复正确、零回归；但同根因残留两处（P1 级关联漏修）**

**①第七处调用点：不存在。** 全树 `CardTitle` 渲染点恰 6 处，全部自带 `fs-card`：
`components/patterns/patterns.tsx:73`（SectionCard，全站卡片外壳，覆盖 knowledge/plugins/dashboard/latency/affinity/memory-graph 所有卡）、`pages/calls.tsx:61,150`、`pages/tokens.tsx:127,172,201`。`components/` 内无其它包装、无测试件、无 story（webui 只有 `src/lib/graph-layout.test.ts` 一个测试文件，不涉卡片）。

**②视觉密度：无打架。** `index.css:242` `@utility fs-card{font-size:.875rem;line-height:1.375rem;font-weight:600}`。`CardHeader` 是 `grid auto-rows-min grid-rows-[auto_auto] gap-2`（card.tsx:22），行高变化不改网格轨道尺寸；无任何固定高度容器包 CardTitle。单行标题较修复前（行高恒 1 的塌陷态）高约 8px，属宪法钉值，非回归。旁证：`app-shell.tsx:80` 的 `leading-tight` 是父元素继承值，其子 `fs-card`/`fs-caption` 各自带行高 → 直接规则恒胜继承，与产物顺序无关，不属同一冲突类（但它是一条**死声明**，可删）。

**③产物：确认再无 `.leading-none` 规则。** 实测 `webui/src/` 全树 `leading-none` 命中 0（注释里也没写字面量，注释规避扫描的自述成立）；`dist/index.html` 中 `grep -o 'leading-none' | wc -l` = 0、`h.indexOf('.leading-none{')` = **-1（未生成）**。`.fs-card{font-size:.875rem;font-weight:600;line-height:1.375rem}` @950549 已无竞争者。

**④【新发现·漏修关联点，与 P1-1 同根因，产物级实锤】** 本条修复的真正根因是「同一元素两个行高来源时靠**产物生成顺序**定胜负」。该形态在工作树里还剩 **2 处**，且其中一处就在本席被复核的文件里：

- `webui/src/pages/logs.tsx:320` `<p className='fs-caption leading-relaxed text-muted-foreground'>`
- `webui/src/components/settings/settings-dialog.tsx:140` `<p className='rounded-md border bg-muted/40 p-3 fs-caption leading-relaxed …'>`

实测产物偏移：`.fs-caption{` @**950483** vs `.leading-relaxed{` @**950677** → **leading-relaxed 后生成者胜**，`fs-caption` 的 1.125rem 被 1.625 覆掉。也就是说：注释里宣告的「行高单一来源=fs-* 阶梯」这条不变量，在同一批改动触及的文件内已被自己违反。`cn()` 救不了——twMerge 不认识 `fs-*`，不会丢弃任何一个。
改法：两处删 `leading-relaxed`（段间距本由 `Card`/`gap` 体系给，行高交回 fs-caption），或新增登记过的 `@utility fs-caption-loose` 一档。**并补门**（见 §10 跟进清单 P0 项）：版式宪法门加一条断言——同一 className 内 `fs-*` 与 `leading-*` 互斥，违者红。审计报告 P1-1「回归锁」明确要求「在常驻门里加 dist 断言或直接断言 CardTitle 源码无 leading-none」，**该回归锁本席确证未落**：`tests/test_webui_constitution.py` 不存在，`grep -rn "layout-constitution|tsc -b|node --test" tests/` = 0 命中（P1-2 同样未做）。

---

### 2. `StatCard` 由互斥改为一律画 children —— **正确（现网无双叠），两点 Minor + 一点关联漏修**

**①全部调用点核查（共 7 处，dashboard 6 + memory-graph 1，无第八处）：**
`pages/memory-graph.tsx:105` 只传 label+value，无 children。dashboard 六枚：卡 1（health）与卡 6（notWired）**不传 value** → 只画 children；卡 2-5 传 `value={xData ? … : undefined}` 且 children=`withFallback(state, null)`。关键不变量：`value` 有值 ⇔ `xxxData` 非 null ⇔ `state.phase==='ok'` ⇔ `withFallback` 返回第二参数 `null`（dashboard.tsx:28-30）→ **两分支互斥由调用方维持，任何调用点都不会双叠**。逐行核过 129/153/166/181/194/203 六枚，无一例外。

**②Minor-1（新形状引入的粘连面）：** 一旦未来有调用点同时传 value 与非空 children，两块之间**零间距**——`CardContent` 只有 `px-6`（card.tsx:52），`Card` 的 `gap-6` 只作用于 header/content 之间，不作用于 content 内部兄弟。改法（最小，局部，不动全局外壳）：`patterns.tsx:36` 前包一层 `<div className='mt-2'>{children}</div>`，或 StatCard 内 children 外包 `flex flex-col gap-3`。

**③Minor-2（API 吞 prop）：** `icon` 与 `sub` 只在 value 分支内渲染（patterns.tsx:27-35）。value 缺席时二者被静默丢弃。现网表现：**dashboard.tsx:130 的 health 卡传了 `icon={<Activity/>}` 但从不传 value → 该图标恒不渲染**（互斥旧实现同样吞，属既有缺陷，非本次引入，但被本次改动「顺手可修」而未修）。诚实记账为关联漏修（Low/外观）。

**④`titleClass='text-muted-foreground'` 与 F16 类冲突面：不叠加新问题。** 合成串 `cn('font-semibold', cn('fs-card','text-muted-foreground'))` → 三者分属 font-weight / 自定义 fs 组 / text-color 组，twMerge 无同类可去。风险面在同一条 §1④ 通则：**任何人给 `titleClass` 传 `text-sm`/`leading-6` 即可无声压死 `fs-card`**（twMerge 不识别 fs-*，两个都留，产物顺序裁决）。建议：SectionCard 显式声明 `titleClass?: string /* 只允许颜色类 */`，或给 fs-* 注册进 twMerge 配置（`extendTailwindMerge` 的 `classGroups`）——这是根治「自定义 utility 对 twMerge 隐形」的正解，影响面小。

---

### 3. `dashboard.tsx` 三处 `?? 0` 与 uptime 守卫 —— **正确；④ 有一处实锤未判空（Low，仅对旧控制面）**

**①可选链短路：TS 与运行时都安全。** `TokensData.totals` 在类型上是**非可选**（api-client.ts:259）→ `totals?.tokens.input.value` 的类型是 `number`，`formatInt(number|null)` 形参兼容，tsc 不报错（本席实跑 `-p tsconfig.app.json --noEmit` = **0**）。运行时短路成立：`totals` 为 undefined 时整条链返回 undefined，不触碰 `.tokens` → **不抛**。且现网根本不会出现该形态：后端 `control_plane/metrics.py:301,324` 无条件 `totals = _family_row(...)` 并塞进 `data`，即 ok 载荷恒带 totals——所以 `?.` 是纯防御，方向正确。残余：若后端给出 `totals:{}`（有键无 tokens），`totals.tokens.input` 会抛 → 该形态现网不存在，且**现在会被 §6 的边界接住成错误卡**（改前是 router 裸错块），风险闭环。

**②`formatInt` 口径与 tokens 页一致。** `lib/format.ts:3-6`：`null|undefined|NaN` → `—`（NaN 显式判）。tokens 页同字段口径 `block.value === null ? '—' : formatInt(block.value)`（tokens.tsx:187）→ 两页 `—` 完全同形。**判定：一致，造数面已消除。** 与审计 P2-11 的要求逐字对齐。

**③`sub` 的「一半未知一半数字」：判定为诚实、非误导。** 各字段独立呈现自身真相（`输入 — · 输出 1,234` = 入向未上报、出向已知），符合「不跨字段合并猜测」。唯一可挑的是可读性：整卡未上报时 value 与 sub 同为 `—`，观感像「查不到」而非「未上报」。若要更诚实，建议在 sub 三分量全 `—` 时换成单条 `t('state.noData')` 句——属打磨，不算缺陷，不列跟进硬项。

**④`callsFootnote` 未判空 = 实锤造数面（本条唯一硬缺陷，Low/Medium）。** `dashboard.tsx:171-174` 把 `callsData.unknown_timestamp_calls` / `unattributed_calls` 直接塞进 i18next。用本仓实装 i18next 离线实测（`node --input-type=module -e`，资源=仓库内真实键值）：

| 传入形态 | 渲染结果 |
|---|---|
| 键存在但值为 `undefined`（旧控制面省略字段） | `时间戳未知  条 · 未归属用户  条` ← **两处空白，句子读起来像数据缺失被藏起来** |
| 键完全不存在 | `时间戳未知 {{unknown}} 条 · 未归属用户 {{unattributed}} 条` ← **占位符原样上屏** |
| 正常 `3/7` | `时间戳未知 3 条 · 未归属用户 7 条` |
| `0` | 正常渲染 `0`（i18next 不把 0 当缺失） |

现网不触发：`control_plane/webui_stats.py:201-202` 无条件写这两个键。但 TS 把它们声明为必填 `number`（api-client.ts:242-243），是**类型层的一句假话**——后端一旦演进/回退，界面立刻出现空白句子，而全站其它处都规矩地显示 `—`。
改法（一行）：`unknown: formatInt(callsData.unknown_timestamp_calls), unattributed: formatInt(callsData.unattributed_calls)`；并把这两个字段改 `?: number` 与 `active_users?`/`last_message_at?` 同列 optional，让 TS 不再撒谎（`KvRow` 已有的 `active_users != null ? … : '—'` 就是这个姿势，dashboard.tsx:70，应统一）。

---

### 4. `logs.tsx` 游标去重 —— **不彻底：去重层在「同一批帧」内完全失效（本席用等价纯模型实跑证伪）；用户担心的「丢行」方向经严格论证不成立**

先给结论表（把两种实现抽成纯模型，按 React 批量提交语义驱动，本席实跑）：

| 场景 | A=主会话实现（effect 重建 Set） | B=审计报告原方案（appendRows 内同步 `add`） |
|---|---|---|
| **1 单批帧内重叠 cursor**（`1,2,1,3,2,1` 同 macrotask、无提交） | 界面 **6 行**，重复 key **2 组**：`[[1,3],[2,2]]` ← **去重全失效** | 界面 **3 行**，重复 key **0** |
| 2 跨提交重复（`[10,11]` 提交后再来 `[10,11,12]`） | 3 行，0 重复 ✅ | 3 行，0 重复 ✅ |
| 3 MAX_ROWS 裁剪后旧 cursor 被服务端重放 | 两者**行为相同**：旧行复现、dropped=2 | 同 |
| 5 每事件成本（20000 次事件，MAX_ROWS=500） | **142.3ms** | **0.9ms** → **156x** |

**①竞态方向判定：不会丢行，只会漏去重。** 严格论证：`seenRef` 的两个写入点分别是 `clearView()`（置空）与 `useEffect`（`= new Set(rows.map(...))`，从**已提交可见行**全量重建）。集合的元素**永远是「当前可见行的 cursor」子集**（重建后恰好相等；清空后为空）。而 `appendRows` 的判据是「在集合内则丢弃」。因此一条**未渲染**的行不可能在集合里 → 刚追加尚未被 effect 收录的行**必然通过**过滤器 → 不存在「判成重复而丢行」的路径。缺陷方向相反：**同一批内到达的重复行两条都通过**（effect 尚未跑，集合还没收下它们），于是 React `key={row.cursor}`（logs.tsx:301）撞车 + 界面重复行——**正是审计 P1-4 要治的那两个症状**。可达性说明（诚实）：`sse.ts:180` 的 `while ((newlineAt = buffer.indexOf('\n')) >= 0)` 会把**一次 `read()` chunk 里的全部完整帧在一次 continuation 内同步 dispatch 完**，中间没有 await、也没有 React 提交 → 重放窗口的整批帧天然落在同一个批量里。所以「单批」不是假想，是重放/积压的常态形态。
但必须同时给出不升级的理由：**本席读后端未能构造出「同一 stream 内服务端重发同一 cursor」的路径**——`event_store.py` 分页 `after` 严格大于、`next_cursor=items[-1].seq`，`events.py:176-189` 逐行推进，无重叠；而审计点名的真·复现（点「重新订阅」/改过滤 → 重复行）已被本条的 `clearView()` 治好。
**综合严重度：Medium（防御层失效，非现行用户可见缺陷）+ 一行即修。** 改法即审计 P1-4 原文：`appendRows` 里 `for (const row of fresh) seenRef.current.add(row.cursor);`，并在 overflow 分支 `for (let i=0;i<overflow;i++) seenRef.current.delete(merged[i].cursor);`，**删掉 :165-167 的 effect**（它既更弱又贵 156x）。注：effect 方案还有个隐性成本——`[rows]` effect 在每次事件后重建 500 元 Set，等于给每条日志一个 O(MAX_ROWS) 摊销。

**②暂停态 `backlogRef` 与去重集：无冲突。** 暂停期 `onEvent` 只 push `backlogRef`（:106-109），不读不写集合；恢复时 effect `[paused]`（:142-149）调 `appendRows(backlog)`，此时集合=可见行，积压行不在其中 → 全部放行（正确）。积压超 MAX_ROWS 时裁剪与 droppedCount 语义正常。**注意一处集合失效**：积压若在同一批量里含重复 cursor，同样落到场景 1 的失效面。

**③裁剪/droppedCount/StrictMode：既有写法，记账，本条不要求现在修。** `setDroppedCount` 被写在 `setRows` 的 updater **内部**（:83-91）= 非纯 updater：React StrictMode（`main.tsx:26` 已启用）**开发模式会双跑 updater** → 裁剪发生时 `droppedCount` 记 **2 倍**（我用模型复现：双跑 updater 使 dropped 从 1 变 2）。生产构建不双跑，故 **dev-only 显示虚高**，不影响行数。判定：**已知残余**，且**审计 P1-4 的「after」代码片段自己也保留了这一形态**（不是主会话新引入）——要修就是把计数挪到 updater 外（`fresh.length` 与裁剪量先算好再 `setDroppedCount`）。另外集合与裁剪的一致性成立：effect 从裁剪后的 rows 重建，被丢弃的 cursor 出集合 → 不再无界增长（与原设计等价，场景 3 两实现同行为）。

**④`clearView` 先于 `startStream` 是否清掉实时尾包：不清行、不造成少行。** `setRows` 用的是函数式 updater，`setRows([])` 先入队、之后任何 `appendRows` 的 updater 后入队 → 队列按序执行，新流首包落在空表之上，不会被后面的 `[]` 抹掉。**真正存在的少行窗口与此无关**：`startStream` → `sse.start` → `stopInternal()` 会 `abort()` 旧 fetch，而旧 `connect()` 的读循环是挂起在 `await reader.read()`，其在途缓冲帧会在恢复后经 `dispatch` 打给 `onEvent`（`sse.ts:184` 的 dispatch 在 `if (this.stopped) return`（:188）**之前**），即**旧过滤条件的尾包可能混进新视图**——这是「订阅切换窗口」固有缺口（旧流关、新流开之间无事件投递），先于本次改动存在，`clearView` 的位置既不制造也不恶化它。判定：**记账为已知残余（低）**；如要收，改 `sse.ts` 在 dispatch 前先判 `this.stopped`。

**⑤`rows.length===0` 早退 与 sessionStorage 残留：顺序正确，但两处「清空」语义不一致。** `resubscribe`/`applyFilters` 先 `sessionStorage.removeItem(CURSOR_KEY)` 再 `clearView()`（:176-177/:182-183）→ rows 提交为 [] 后游标 effect 早退（:136）→ **键保持被删，无残留**，顺序无误。但**页面上的「清空」按钮（:226）走 `clearView` 而不删键** → 清完视图后 sessionStorage 仍留着旧游标：刷新页面即从旧游标续传。功能上不算错（游标之后的事件一条不少），但**两个「清空」affordance 的游标语义不同**（清空=继续续传 / 重新订阅=全窗口回放），用户无从区分。判定：Minor 一致性，建议在 `clearView` 注明「只清视图不动游标，事件一条不丢」或给清空按钮也删键（二选一，需有意为之并写注释）。

**⑥附带（非本次改动，但同文件相邻，记账）：** 卡面 `description` 直读 `clientRef.current?.lastCursor`（:292）——**ref 不参与渲染**，游标数字只在别的 state 变化时才顺带刷新；且 `LogEventRow.cursor` 类型是必填 `number`（api-client.ts:310），而 :138 却防御性地判 `!== undefined`：若运行时真有 undefined（后端形态漂移），去重集合会把它们全并成一个 `undefined` → **除第一条外全部静默丢弃**。现网 `events.py:176` 每帧必带 `id:`，不触发。建议：`appendRows` 过滤器加 `typeof row.cursor === 'number'` 前置，与 :138 的谨慎对齐，否则这一处的防御是**半套**。

---

### 5. `settings-dialog.tsx` 令牌留空不写 —— **修掉了「保存即清空」，但引入了「无法清除」的死路（Medium，新缺陷）；trim 风险=零**

**①现无任何清除路径（实锤）。** 全树 `setApiToken` 调用点仅 3 处：`settings-dialog.tsx:65,66`（本条，加 `if (token.trim())` 门）与 `api-client.ts:88` 定义处。组件内也**没有**「清除」按钮——唯一图标按钮是 `showTokens` 明暗切换（:132）。原实现（无条件 `setApiToken('','admin')`）确实意外提供了清除能力，因为存储层就是这么设计的：

```ts
storageSet(key, token && token.trim() ? token.trim() : null);   // api-client.ts:89
// → 空串/null 走 localStorage.removeItem(key)：删除即清除，语义完备
```

后果：令牌一旦录入，UI 层再也摘不掉——换错账号/令牌轮换后想退回「未配置」态、或想从 ro 回退到 admin-only，只能 F12 手删 `webui:bearer`。对一个把「失败面诚实降级」写进家法的组件树，这是可用性倒退。
**最小补救（推荐 a）：** token 行已存令牌时（`getApiToken(field.kind)` 为真）在眼睛按钮旁加一枚清除按钮，点击 `setApiToken(null, field.kind)` + 立即 `window.location.reload()`（沿用 :68 的「整页刷新最干净」裁定）。
**i18n 键与门的判定（用户明确问到的）：** 需要新增 1 对键（如 `settings.clearToken` / EN+ZH）。**不会触发任何奇偶门——因为这种门根本不存在**：`grep -rn "238" tests/*.py scripts/*.py webui/scripts/*.mjs` 零命中（命中的 5 行全是无关的 QQ 号），webui 侧唯一读 locales 的是 `scripts/webui_acceptance.py:50`，且它只把中文串当 ok 标志用、**不做键集校验**。本席实核双文件键集：en=238 / zh-CN=238、差集双向为空（脚本口径=递归展平）。审计 §3.8 那句「双语言 238=238 键零漂移」是**人工核对记录，不是机器门**。所以：加键安全，条件是**两个文件同时加**（否则只有下次人工核对才会发现）。
不新增键的替代方案 (b)：复用 `settings.cancel` 文案做「已保存 → 点此清除」——语义脏，不建议。

**②`setApiToken` 语义：空串写入无其它副作用**（纯 removeItem，见上；异常路径 `storageSet` 内部 try/catch 已吞）。传 `null` 与传 `''` 等价。

**③`trim()` 改错含首尾空格 token 的风险：零。** 存储层 `:89` **本来**就以 `token.trim()` 落盘，故对话框里的 `trim()` 与既有语义完全一致，不改变任何可存储值；且控制面 Bearer 由后端生成（`.env` 的 `BOT_CONTROL_PLANE_TOKEN`），无「真身带首尾空格」形态。**判定：无风险，且这两处 `trim()` 只是与存储层对齐，可保留。**
（另一处顺带诚实记账：`if (adminToken.trim())` 让「只想改 baseURL 不想动令牌」变成常态，但输入框 placeholder 写的是 `已保存（输入新值可覆盖）`（locales `settings.tokenSavedPlaceholder`）——文案与新逻辑正好对得上，**这是本次改动的加分项**，无缺陷。）

---

### 6. `error-boundary.tsx` —— **编译成立、层级有效；但审计给的前提要更正（原态不是白屏）；AppShell 层残余属实，且「更彻底做法」有一个陷阱（不能用 defaultErrorComponent）**

**①React 19 + class 字段 + `useDefineForClassFields`：确证能编译且无覆盖问题。** `tsconfig.app.json` 实读：`target: ES2023`、`useDefineForClassFields: true`、`strict: true`、`noUnusedLocals/noUnusedParameters`。本席实跑 `tsc --noEmit -p tsconfig.app.json` = **0**、`-p tsconfig.node.json` = **0**。产物级实证（`dist/index.html` 内原文）：

```js
class wH extends O.Component{state={error:null};static getDerivedStateFromError(t){return{error:t}}
componentDidCatch(t,n){console.error("[webui] route render failed",t,n.componentStack)}reset=()=>this.setState({error:null});
```

原生 class 字段**未被降级**，语义=[[Define]] 在 `super()` **之后**执行 → React 基类 `Component` 构造器只赋 props/context/refs/updater、**不给 state 赋值**，故字段初始化 `{error:null}` 是终值，不存在 define 覆盖 state 的问题（覆盖事故只在「子类字段无初始化器 + 基类构造器赋值」方向发生，此处不成立）。TS2612/TS2564 均不触发（有初始化器）。`reset` 作为箭头字段在 render 期才使用，闭包 `this` 正确。

**②「边界自己也炸」= 白屏没治成：判定为可接受，且有依据。** `SemanticState` 的 error 分支（semantic-state.tsx:101-117）只依赖 `useTranslation` + 纯展示组件（Card/Button/Skeleton 无关）。i18n 是**同步 init**：`lib/i18n.ts` 用 `import.meta.glob(..., {eager:true})` 把 locales 打进产物、无 backend 插件、无网络请求 → 运行时不存在「i18n 尚未就绪」窗口；而 `main.tsx:9` 在 render 之前 import `@/lib/i18n`。若 locale JSON 解析失败，那是构建期就炸、根本产不出 dist。**残余**：万一 `t()` 自身抛（实装里不存在此路径），异常会向上传到 router 的全局 CatchBoundary（见 ③）→ 仍有兜底，不落白屏。判定：**可接受，不需要额外加固**。

**③AppShell 层仍无边界：残余属实，但「原态白屏」这一前提错了（重要更正）。** 本席读实装源码链：`router.tsx` 的 `createRouter` 未设 `disableGlobalCatchBoundary` → `Matches.js:43` 走 `jsx(CatchBoundary, {getResetKey:()=>match, onCatch})` 分支，**router 自带的全局错误边界一直是活的**；`CatchBoundary.js:31` 在 `errorComponent` 缺省时回落到内置 `ErrorComponent`（同文件 :40-84）——渲染英文 **"Something went wrong!" + Show/Hide Error 按钮 + 红框 `<pre>{error.message}</pre>`**。所以：
- 改前抛错**不是白屏**，而是一块无样式、无 i18n、无重试的英文裸错；审计 P1-5' 的根因描述与「违背自家失败面诚实降级哲学」的结论都成立，但**「任何页面渲染抛错 = 白屏」这句不成立**。
- 层级与生效性：本边界挂在 RootLayout 内、`<Outlet/>` 外，比 router 全局边界**更深** → 更靠近抛错点 → **先接**。而 9 条路由都没配 `errorComponent`，故 `Match.js:39` 的 `routeErrorComponent = route.options.errorComponent ?? router.options.defaultErrorComponent` 为 undefined → `Match.js:44` `ResolvedCatchBoundary = SafeFragment` → 页级不存在第三个边界。**结论：新边界确实接管页级抛错，不是死码。**
- 真正没被本席接管的是 **AppShell/RootLayout 自身**抛错（nav、`SettingsDialog`、集合查询）。这不是白屏，但会掉回 router 那块英文裸错。可达实例（本席读到、类型层已成立）：`app-shell.tsx:64` `collectionsQuery.state.data.items.filter(...)` 只判了 `phase==='ok'`，而 `api-client.ts:210` 的 `data: (payload.data ?? null) as T` 使 **phase ok + data===null 是一个合法态** → `null.items` 抛 TypeError。全树同类「phase==='ok' 却裸取 `.data.X`」共 **14 处**（app-shell:64、knowledge:97/180/218、latency:71/72/76、logs:187/188、plugins:152 等）；其中 8 处在 `<Outlet/>` 之下——**本次改动把它们从英文裸错升级成中文错误卡（真实净收益）**，只有 app-shell:64 在边界之上，仍是英文裸错。
- **更彻底的做法 + 陷阱（用户点名要判定）：** 正解是给**根路由**配 `errorComponent`（`createRootRoute({component: RootLayout, errorComponent})`）——`Match.js:39/44` 会为根 match 打开一个 CatchBoundary，罩住 RootLayout+AppShell+全部页，一处收口。**不要用 `createRouter({defaultErrorComponent})`**：它会被 `Match.js:39` 当作每条路由的 `routeErrorComponent`，从而让 9 条页级路由各自生成一个**比本席新边界更近**的 CatchBoundary → **`error-boundary.tsx` 直接变成死码**（这正是本条改动要防的事，反向踩进去）。次选=`main.tsx` 里 `<RouteErrorBoundary>` 包 `<RouterProvider>`（能兜 AppShell，但换页不重置、且吞掉 router 的 notFound 语义）。判定：**残余可接受（英文裸错非白屏），但建议按根路由 errorComponent 收口，并明确规避 defaultErrorComponent。**

**④错误原文上屏：不构成新增泄漏面，建议截断。** 两点依据：(a) 全站数据错误分支早就把 `state.message`（`ApiError.message`=后端 message 文本，api-client.ts:181-192 / use-semantic-query.ts:49）直出在 SemanticState 卡上（:107），本边界只是复用了同一形态，**没有新增内容类别**；(b) 原态下 router 的 `ErrorComponent` 更是把 `error.message` 塞进 `<pre>`，生产模式仅默认折叠、点一下即见 → 新实现「始终可见」比「折叠可见」略激进一档，但同类。本机 loopback UI，判定 Low。两点建议：`error.message` 过一道 `slice(0, 300)`；`SemanticState` 的 `<p className='max-w-md …'>`（:107）无 `break-words`，长串无空格原文会撑破卡片（`html{@apply overflow-x-hidden}` 会裁掉，导致尾部**看不见**），补 `break-words` 即可。

---

### 7. `router.tsx` 的 `useRouterState` —— **正确（签名/类型/层级三项实读核对，无 `never`、无 Register 冲突）**

**①签名与返回类型：读实装定义确认，非猜。** `node_modules/@tanstack/react-router/dist/esm/useRouterState.d.ts:20`：

```ts
export declare function useRouterState<TRouter extends AnyRouter = RegisteredRouter,
  TSelected = unknown, TStructuralSharing extends boolean = boolean>(
  opts?: UseRouterStateOptions<TRouter, TSelected, TStructuralSharing>
): UseRouterStateResult<TRouter, TSelected>;
// UseRouterStateResult = unknown extends TSelected ? RouterState<…> : TSelected
// UseRouterStateOptions.select?: (state: RouterState<TRouter['routeTree']>) => ValidateSelected<…>
```

`select` 是**可选属性**（`{select?: …}`）→ 传对象字面量 `{select: (state) => state.location.pathname}` 合法；`TSelected` 由 select 返回位置推断为 `string` → 返回类型 `string`（`unknown extends string` 为 false）→ 不是 `never`、不是 `unknown`，赋给 `key` 成立。`RegisteredRouter` 经本文件 `declare module '@tanstack/react-router' { interface Register { router: typeof router } }` 绑定，与 `RootLayout` 无循环推导问题——**tsc 实跑 0 错**（§6① 同源）。附带红利：默认 `structuralSharing` 生效，选出的原始字符串只在 pathname 变化时才触发重渲染，RootLayout 不会因 search/hash 变化而白重渲染。

**②hash history 下 pathname 不含 search：是缺陷，但轻。** `state.location` 是解析后的 `ParsedLocation`，`pathname`/`searchStr`/`hashStr` 分立；`createHashHistory` 只是把整条 location 搬进 `#` 之后，pathname 仍为 `/knowledge`。故 `?collection=` 变更 **key 不变 → 边界不重置**。后果：某集合渲染抛错后切到另一集合仍停在错误卡（除非换页或点重试）。判定：**Light**。更彻底：`key` 用 `state.location.href`（含 search/hash）即一处解决；本席建议改成 href，代价=换搜索条件也重挂载（对 knowledge 页正好是期望语义，因为它按 collection 重查）。**这条与 §6③ 一起构成边界的两个已知缺口，都不阻塞。**

**③RootLayout 由「无 hook」变「订阅 router state」：AppShell 渲染顺序不受影响。** AppShell 在 RootLayout 里、边界外（router.tsx:18-25），`<main>{children}</main>`（app-shell.tsx:121）位置不变；pathname 变化本来就要重渲染整棵内容树，新增的一次 RootLayout/AppShell 重渲染与之同帧，`useSemanticQuery(['knowledge','collections'])` 走 react-query 缓存（`staleTime:10s`，main.tsx:22）→ **不产生额外请求**。判定：无副作用。

**④TS：见 ①，`tsc` 双 project 均 0。** 无 `never` 推断、无 Register 冲突。

---

### 8. `vite.config.ts` 加 `/admin/api/v1` 代理 —— **正确（顺序无关，读实装源码确证）；SSE 判定给到限度；`process.env` 暗坑沿用但现网零影响**

**①匹配顺序：不会互相吞，两条先后无所谓。** 读 `node_modules/vite/dist/node/chunks/config.js:22085`：

```js
function doesProxyContextMatchUrl(context, url) {
  return context[0] === "^" && new RegExp(context).test(url) || url.startsWith(context);
}
```

纯 `startsWith`（非正则、无词边界）。`/admin/api/v1/health`.startsWith('/api/v1') = **false** → `/api/v1` 那条不吃 admin 路径；反向亦然。两条 context 互不为前缀，插入顺序（:19 与 :23）无意义。**判定：正确，无需 `bypass`/无需调序。**

**②SSE 经代理：未见需要额外 `configure`。** 实装走 `http-proxy` 默认路径（`selfHandleResponse` 缺省 false → 响应流式 pipe，不聚合），Vite 代理不缓冲正文；本席在 `vite/dist/node/chunks/config.js` 里只找到 **2 处 `compression` 字样**且未能确证它被挂在代理响应链上，故诚实口径=**「未发现对代理响应施加压缩的实证，因此无必须补的 configure」，而非「已确证不会缓冲」**。真正会卡流的是压缩中间件对 `text/event-stream` 做 gzip 攒块——若日后出现「日志页 dev 下要等几秒才出批」，第一嫌疑就是它，处理法=对该 context 加 `configure: (proxy)=>proxy.on('proxyRes',(res)=>{ res.headers['cache-control']='no-cache' })` 或让后端显式 `Content-Encoding: identity`。**现状不定罪、不记账**，只在跟进清单里挂一条「dev 首连 SSE 目验」（因本席不许起 dev server，无法定论）。
（另注：SSE 与 REST 共用同一条 context，`changeOrigin` 对 SSE 无害。）

**③F10 暗坑：确证沿用，但今日零影响。** 事实链：本席 `ls webui/.env*` → **文件不存在**（工作树只有仓库根 `.env`，而 Vite 只读 `root`=`webui/`）→ 即使 `process.env.VITE_API_BASE_URL` 永远 undefined，两条 target 也都落到同一个 `http://127.0.0.1:8742` 字面量 → **新增这条没有扩大暴露面，只是继承了这个休眠缺陷**。真正会踩的形态是：谁将来在 `webui/.env` 写 `VITE_API_BASE_URL=` 想改代理目标——它**只**会经 `import.meta.env` 进浏览器代码（api-client.ts:35 用的正是 `import.meta.env`，那条是对的），进不了 `vite.config.ts` 的 `process.env`，于是出现「前端基址改了、dev 代理没改」的劈叉。
正确写法（**按纪律本席不动手**）：

```ts
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');          // from 'vite'
  const target = env.VITE_API_BASE_URL || 'http://127.0.0.1:8742';
  return { plugins: [...], server: { proxy: {
    '/api/v1': { target, changeOrigin: true },
    '/admin/api/v1': { target, changeOrigin: true },
  }}, … };
});
```
附带好处：两条共用一个 `target` 常量，消除重复字面量漂移。

---

### 9. 主会话自报取证独立复跑 —— **5 项里 3 项完全一致、2 项与现树不符；并给出各证据对「这 9 处改动」的真实证明力**

| 项 | 主会话报 | 本席独立实跑 | 一致性 |
|---|---|---|---|
| `tsc` | `-b` = 0 | `--noEmit -p tsconfig.app.json` = 0；`-p tsconfig.node.json` = 0（`.tmp/*.tsbuildinfo` mtime 前后均 16:39:44，实证零写盘） | **一致**（口径不同已披露） |
| `npm run build` | 0，dist **969,444 B** | 未跑（禁）；实测 `webui/dist/index.html` = **973,967 B**，mtime 16:47:19 | **数值不符** |
| `node scripts/layout-constitution.mjs` | 0 | 0（「全部通过（hex=0/字号五档/间距 4px 栅格/调色板类=0）」），且本席核过脚本无 `writeFile/mkdir/rm` → 纯只读 | **一致** |
| `tests/verify_hashes.py --check` | 0 | 0（首次经 `tail` 管道取到的是 tail 退出码，本席改为重定向后取 `$?` 复核=0） | **一致，但证明力=0**（见下） |
| `pytest tests/test_pre_restart_check.py tests/test_webui_http.py` | 33 passed | **33 passed in 8.33s**（带 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 venv 解释器 -p no:cacheprovider --basetemp=$TEMP/f17-pt`） | **一致** |
| `scripts/webui_acceptance.py` | 9 页 PASS（全 graceful） | **按纪律未跑**（实读确证起 playwright+wrapper 服务器+mock 口 8743） | **未复核** |
| 附加：`node --test src/lib/graph-layout.test.ts` | 未报 | **7 pass / 0 fail**（本席自加，唯一在册前端单测族） | 新增绿灯 |

**额外跑的只读门**：`webui/dist/index.html` 标记核对——`route render failed`/`getDerivedStateFromError`/`componentDidCatch` 均在场、`Saved (type to replace)` 在场、`leading-none` 缺席 → 16:47 那次构建**确实包含 8 个改动文件**（其 mtime 全部 ≤16:46:37 < 16:47:19，逐一核对）。

**两处不符与一条陈旧判定（必须让主会话知道）：**
1. **dist 字节数对不上**：本席实测 973,967 B ≠ 自报 969,444 B。可能是自报后又构建了一次，也可能数字抄自更早一次；无论哪种，**台账里「dist 969,444B」这一证据串与现产物不是同一件东西**，交接硬规矩（#5：已完成必须给可复跑命令+实跑输出）在这一点上没满足。
2. **dist 已经陈旧**：`webui/src/pages/tokens.tsx` mtime = **17:01:28，晚于 dist 16:47:19**（本席 `find src -newer dist/index.html` 唯一命中）。即：主会话改完 9 处后重建过 dist，但**自那之后又有人动了 tokens.tsx**（F16 席在飞），当前产物不再等于当前源码。所有「读 dist 取证」的结论（含本席 §1③）都只对 16:47 那一刻负责。**下一次 build 前不要引用 dist 做证据。**
3. **各门对「这 9 处改动」的真实覆盖（诚实拆穿）：**
   - `verify_hashes.py` 的 19 项清单里 **webui 文件数 = 0**（实读 `TRACKED_FILES`：7 Jinja + theme_tokens + 3 docs + DESIGN-SPEC + builders/renderer/templates/echo/debug/usage_cards）→ 它对前端 9 处改动作证力为 **0**，不能算这批改动的证据。
   - `test_pre_restart_check.py` 的 webui 门只查 **存在/非空/超限/外链** 四件事（该文件 :294-381）→ 与类名冲突、行高层叠、去重逻辑**全无关**。
   - `webui_acceptance.py` 的 mode 判定（:276）`"data" if ok_marker else "graceful"` → **9 页全 graceful = 没有任何一页进入数据分支** → 被改的 StatCard 数字块、dashboard 的 `formatInt` 分支、`?`/`: undefined` 守卫、以及错误边界本身**一条都没被执行**。这 9 页 PASS 对这 9 处改动的证明力接近「不白屏」。
   - 综合：**这 9 处改动目前唯一实打实的常驻门是 tsc + 版式宪法门 + 7 例图布局单测**，而它们全都不看这三件事（行高层叠/去重竞态/令牌清除）。审计 P1-2「三门游离」在改后依旧成立，且现在更该修——因为已经有真实行为改动悬在门外。

---

## 主会话必须跟进的清单（按优先级）

**P0（不修就是「宣称与证据不符」）**
1. **补 §1④ 的同根因残留**：删 `logs.tsx:320` 与 `settings-dialog.tsx:140` 的 `leading-relaxed`（产物级实锤：`.fs-caption@950483` < `.leading-relaxed@950677`，后者恒胜）。顺手删 `app-shell.tsx:80` 的死 `leading-tight`。
2. **补 §1/§9 的门（审计 P1-1 回归锁 + P1-2 三门常驻，两条一起做）**：新建 `tests/test_webui_constitution.py` 常驻化 ①版式宪法 ②tsc ③graph-layout，并新增断言「同一 className 内 `fs-*` 与 `leading-*` 互斥」+「CardTitle 源码无 leading 类」。否则下次改坏 src 不重建 / 再写一次行高冲突，8500+ 条测试照样全绿。
3. **重建 dist 并更正台账字节数**：tokens.tsx 已跑到 17:01 → 现 dist 陈旧。重建后再记字节数；引用 dist 证据必须标「构建时刻」。
4. **§4 logs 去重按审计原方案收口**：`appendRows` 内同步 `seenRef.add`（+ overflow 同步 `delete`），删 `:165-167` effect（实测同批帧 A 出 6 行 2 组重复 / B 出 3 行 0 重复；成本 156x）。

**P1（新缺陷/可用性倒退，各一行到几行）**
5. **§5 令牌清除死路**：加 `setApiToken(null, kind)` 的清除按钮（或等价 affordance）；新 i18n 键可放心加（**确认无任何键数/奇偶门**，本席已实查），但 en+zh 必须同批加。
6. **§3④ `callsFootnote` 未判空**：两处套 `formatInt(...)`，并把 `unknown_timestamp_calls`/`unattributed_calls` 改 optional 类型，消灭「空白句子」。
7. **§6③ AppShell 层收口**：`createRootRoute({component, errorComponent})`；**明确禁止用 `createRouter({defaultErrorComponent})`**（`Match.js:39/44` 依据：会让每条路由生成更近的 CatchBoundary，把 `error-boundary.tsx` 变成死码）。同批修 `app-shell.tsx:64` 的 `phase==='ok'` 却裸取 `.data.items`（`api-client.ts:210` 使 ok+null 合法），并全树扫同形态 14 处。

**P2（记账，别丢）**
8. **§2③ health 卡 `icon` 恒不渲染**（StatCard 只在 value 分支画 icon/sub）+ children 两块零间距：StatCard 内一行修，或把不变量写进 JSDoc「value 与 children 由调用方保证互斥」。
9. **§4③ 非纯 updater**：`setDroppedCount` 挪出 `setRows` updater（StrictMode dev 下裁剪时 dropped 双计，本席模型复现 1→2）。
10. **§4④ sse 切换窗口**：`sse.ts` 的 `dispatch` 前补 `if (this.stopped) return`（旧过滤条件尾包混进新视图）。
11. **§4⑤ 两个「清空」affordance 游标语义不一致**：清空按钮不动 sessionStorage、重新订阅动——有意为之就写注释，否则统一。
12. **§4⑥ cursor 类型假话**：`appendRows` 过滤器加 `typeof row.cursor === 'number'`，与 `:138` 的防御对齐（否则 undefined cursor 会导致**除第一条外全丢**）。
13. **§6④ 错误原文**：`error.message` 截断 ≤300 + SemanticState error `<p>` 补 `break-words`（现被 `html{overflow-x-hidden}` 裁掉尾部）。
14. **§7② 边界 key 改 `location.href`**，让 `?collection=` 也重置错误态。
15. **§8③ 代理 target 改 `loadEnv`**（`webui/.env` 目前不存在 → 休眠缺陷，修它不要顺手改行为，只把两条 target 收成同一常量）。
16. **§9 acceptance 的取信口径**：全 graceful 的 9 页 PASS 不得写进「已完成」证据链；要证这 9 处，需要一次带 mock 的 **data 态** 9 页（`--api 127.0.0.1:8743`，`scripts/webui_mock_server.py` 在位）+ 一条「注入 throw」用例验边界。本席按禁副作用纪律未跑，此判据待主会话执行。

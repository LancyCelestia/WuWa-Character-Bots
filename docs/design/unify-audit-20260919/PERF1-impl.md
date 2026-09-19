# PERF1 · 日志尾流页 + 记忆图 canvas 性能实做台账

> **快照口径**：`date` 实跑 = `2026-09-19 20:09:59 +0800`；`node -v` = `v26.7.0`、`npm -v` = `11.19.0`。
> 本文所有计数/坐标为落盘后复跑 grep 的实况，非估。输入件 = `F8-webui-performance.md`（16:30 快照）。
> 本席性质：**写代码**，独占面 = `webui/src/pages/logs.tsx` + `webui/src/components/graph/memory-canvas.tsx`
> 两文件；`webui/src/lib/**`、locales、宪法门脚本、`.py` 一律只读。未跑浏览器、未起 dev server、
> 未 `npm run build`、未 `tsc -b`、无 git 写操作、无删除。**凡无实跑数据支撑的结论一律标「静态推断」。**

---

## 〇、一句话总裁决

F8 落在我这两个文件的三条（**L-1 暂停积压无界、L-2 每秒整页重渲染、L-3 逐条事件重建 state**）
**全部为真**，已修并各带测量；我在任务书指引下自查出的 canvas 侧四项（**每帧 8 次 getComputedStyle、
每帧 601 次 toLowerCase、每帧重建 backing store、挂载双绘**）也全部为真并已修。**一条判为「不成立/不必动」**
（表 §1-L2 的 sessionStorage 每批一写——它本来就不是每事件一次，见 §一）。
两文件的改造**可见输出等值性不是口头承诺**：绘制侧 5 组状态 ×2,212 笔落笔逐笔等值（§四-1），
日志侧 3 万条混合流 ×3 种窗口宽度可见游标序列/dropped 总量/判重集终态全等（§四-2、四-3）。
用户可见差异只有两类，都在时序不在内容：**行入库最迟晚一帧（16ms）**、**暂停积压峰值内存从 413 MiB 级降到 0.2 MiB 级**（后者正是修复本身）。

---

## 一、逐条判定（真/已修/伪 + 背后的数字）

| # | 主张（F8 原文坐标为 16:30 快照） | 判定 | 现坐标（20:0x 复跑） | 处置与数字 |
|---|---|---|---|---|
| **L-1** | `backlogRef` 暂停期无条件 push、无上限（`logs.tsx:61,102-104`） | **真（Medium）** | `logs.tsx:142,214-228` | 已修：积压与视图同界（≤`MAX_ROWS`），超界最旧行就地裁掉并把枚数暂存 `backlogDroppedRef`，恢复时并入 `droppedCount`。**实测**：20 万行积压 = **95.5 MiB（501 B/行）**，10 条/秒 × 24h = **86.4 万行 ≈ 413 MiB** 无上限堆积；封顶后同场景 **0.24 MiB**（§三-测1 段 3）。账面等价证明见 §四-3（dropped 1200→1200、可见游标序列全等）。 |
| **L-2**（§7 版，Medium） | 每秒 `setNowTick` → 整页重渲染，500 行 `formatTime`(Intl) + `detailsOneLine`(JSON) 每帧重算 | **真，且比审计估的更贵** | 原 `logs.tsx:52,126,301-315` → 现 `logs.tsx:56-121,309,395-397` | 已修两刀：①秒表关进叶子（`useSecondTick` + `StatusChip`/`CursorLine`），父页不再每秒渲染；②`const LogRow = memo(...)`，存量行浅比较即跳过。**实测**：500 行一趟取格 = **33.6 ms**（单行 **67.3 µs**，其中 `formatTime` 现场建 Intl formatter 占 29.6 µs）→ 每秒一趟 = **2907 s 主线程/24h**，且**单趟已超一帧预算 16.7ms**；改造后同一趟降为 **0.004 ms**（8524×）。 |
| **L-3**（Low） | 每条事件一次 `setRows` + 一次 `[rows]` effect（`logs.tsx:101,77-88,148-150`） | **真（但要说清它贵在哪）** | `logs.tsx:159-201` | 已修：到达即判重登记（不变量 a 原样保留），行入 `pendingRef`，**16ms 合并窗口**一次并入。**实测**（同批 k 条）：k=50 → **92.1 µs → 2.8 µs（32.9×）**，k=500 → **1001.6 µs → 6.3 µs（158.5×）**，元素复制 **375,500 → 1,000**；k=1 稳态 **2180 → 1752 ns（1.2×，噪声级，无回退）**。诚实更正审计的一处措辞：React 18+ 自动批处理下，同一 chunk 的 k 条事件**本就只提交一次渲染**，所以贵的不是「k 次渲染」而是 **k 个排队的 `[...current,...fresh]` updater（O(k·n)）**，以及每提交一次的 sessionStorage 写 + `scrollIntoView`（这两项频次随合并窗口同步下降）。 |
| **表 §1-L-2**（Low） | 每 SSE 事件写一次 `sessionStorage.webui:logsCursor` | **不成立（判「伪」）** | `logs.tsx:252-256`（effect `[rows]` 原样未动） | 该 effect 挂在 **rows 变化**上，不是挂在事件上：改造前同一 chunk 的 k 条事件被 React 合批后**已经只写一次**。合并窗口只是让写入再稀疏一点（≤60 次/秒）。为它单开一刀没有可指的工作量（「k 条 → 1 写」的差值 = 0 到 1 次/秒的 µs 级写），**不做，登记**。 |
| **自查-1** | 绘制 effect 每帧 8 次 `getComputedStyle(documentElement)` + 8 次 `getPropertyValue` | **真** | 原 `memory-canvas.tsx:129-134` → 现 `:61-70`（`palette` useMemo，deps=[themeTick]） | **实测 60 帧拖拽：480 → 8 次（每帧 8.00 → 0.13，60×）**。取色与交互态无关，只该随主题切换重读。 |
| **自查-2** | 每帧 `new Map(nodes.map(...))` + 每帧 5 项 colors Map + 每帧新建 `matches` 闭包，循环内每条边/每个节点再做 `toLowerCase()+includes()` | **真** | 原 `:128,135-139` → 现 `:59`（`nodeById`，deps=[nodes]）、`:73-82`（`matchedIds` 命中集，deps=[nodes,query]） | **实测 60 帧：Map 构造 120 → 2 次、`String.toLowerCase()` 36,060 → 201 次（每帧 601 → 3.35，179×）**；新增 1 枚 Set（每 query 变化一次，≤200 项）。 |
| **自查-3** | 每帧无条件 `canvas.width = …` | **真（静态推断为最贵的一项）** | 原 `:121-122` → 现 `:159-165`（尺寸不变则不赋值） | **实测 60 帧：赋值 60 → 1 次**。赋值本身让浏览器丢弃并重建位图：容器 `1100×480`（memory-graph.tsx:213 内联 height:480）@dpr2 = **2200×960×4 B = 8.1 MiB/次** → 拖拽 60 帧/秒 ≈ **483 MiB/秒位图 churn**。**未跑浏览器，此字节数为算术推断**，赋值次数才是实测。 |
| **自查-4** | 挂载即双绘：`measure()` 立即测一次 + ResizeObserver 强制首报同值 → 两个新对象 → 绘制 effect 白跑一遍 | **真** | 原 `:58` → 现 `:86-98`（同值 `return prev`） | **实测挂载序列：重渲染 2→1、整幅绘制 2→1**。真实绘制成本未测（无浏览器），但每省一次 = 省 200 节点 + 400 边的整幅光栅化。 |
| **任务书第 3 问**：这两个文件里有没有「只增不减」的 Map/Set/数组 | **无（未发现泄漏证据）** | — | `logs.tsx:158`（seen）、`memory-canvas.tsx:57-82`（layout/degrees/nodeById/matchedIds） | 判重集实测上界 = `MAX_ROWS + 单帧缓冲`：**2 万条连续到达 → seen 峰值 501、终态 500**（§三-测1 段 3c，改造前后同界）；canvas 四个容器全部 ≤200 项（后端 `max_nodes=200` 封顶，`api-client.ts:476`，16:30 快照坐标至今未漂移），且 useMemo 换代即整体替换；ResizeObserver/MutationObserver 均在 cleanup 里 disconnect。合并窗口本身也不随挂机时长增长——后台标签页定时器最坏被节流到 ~1 次/秒，缓冲 = 到达率 × 窗口，不随分钟数累积。 |
| L-4 / L-5 / L-6 / L-7 / L-8 | 轮询魔数、apiRequest 超时/abort、TTS 磁盘配额、性能门、路由级 lazy | **不在本席两文件内** | 复跑 `grep -rn "refetchInterval: [0-9]" webui/src/pages` = **10 处**（16:30 快照记 9 处，并发波新增 1 处，如实记） | 本席零改动，只在此点名归属（§七-3）。 |

---

## 二、改了什么（只列形状，逐字看文件）

### `webui/src/pages/logs.tsx`（325 → 407 行，增量几乎全是注释与新子件）

1. `useSecondTick()`（:56）+ `StatusChip`（:66）+ `CursorLine`（:93）：每秒 `setNowTick` 从父页搬进叶子。
   节奏与相位与改造前一致（无条件 1000ms `setInterval`，挂载即起，卸载即清）。
2. `LogRow = memo(...)`（:107）：原 `rows.map` 内联 JSX 整段搬进 memo 子件，`key={row.cursor}` 留在 map 处。
   行对象引用在追加/裁切中保持稳定（只做数组拼接），浅比较即可判定。
3. `appendRows`（:181）改为「到达即同步判重登记 → 入 `pendingRef`」，新增 `commitPending`（:163）在
   `FLUSH_WINDOW_MS = 16`（:26）的 `setTimeout` 到点时一次性并入视图。三条不变量原样成立：
   **(a)** 判重与登记同在到达瞬间（没有回到「effect 里重建集合」的漏判形态，原注释逐字保留在 :183）；
   **(b)** 裁出的行当场 `seenRef.delete`（:173）；**(c)** `clearView`（:281）同帧重置 rows + droppedCount + seen，
   并新增「丢弃未入库的 `pendingRef`」——否则已判重的行会越过「清空」重新现身。
4. 暂停分支（:214-228）加 `MAX_ROWS` 上界 + `backlogDroppedRef` 暂存；恢复分支（:259-268）把暂存枚数并进
   `droppedCount` 后再冲积压。**不**在 `clearView` 里清 backlog（改造前也不清，语义原样）。
5. 卸载 cleanup（:240-248）多清一个合并窗口定时器并丢弃缓冲（防卸载后 setState）。

### `webui/src/components/graph/memory-canvas.tsx`（227 → 260 行）

1. `nodeById`（:59）、`palette`（:61）、`matchedIds`（:73）三个 useMemo：把与交互态无关的量提到渲染外。
2. 绘制 effect（:152-221）内只留查表 + 落笔：删掉帧内取色、帧内建表、帧内 `toLowerCase`；
   `context.font` / `textBaseline` 从节点循环内提到循环外**各一次**（字符串字面量逐字未改，仍在本文件，
   见 §六-1 关于宪法棘轮的说明）。
3. `canvas.width/height` 赋值加同值门（:159-165）。
4. ResizeObserver 回调用函数式 `setSize` 吸收同值回写（:86-98）。
5. 绘制 effect 依赖表补 `nodeById/palette/matchedIds`（:220），原 10 项全留：**触发重绘的条件集合不缩小**
   （新增三项的identity变化必然伴随原 dep 变化，不会多画一帧）。

---

## 三、实跑取证

### 三条验证命令（命令原文 + exit code）

```
cd webui && npx tsc --noEmit -p tsconfig.app.json        → TSC_EXIT=0（0 错误）
cd webui && npm run lint:layout                          → LINT_EXIT=0，输出含「全部通过」
   版式宪法机器门：全部通过（自测 102/102；…；canvas 字体字面量；行级豁免 0/0 基线，棘轮只减不增；
   权重双写白名单 16 处存量在册；脱栅棘轮 1 处存量在册（只减不增））
   —— 注：本席开工前基线为「自测 58/58」，跑完已变 102/102，是并发席加强门脚本所致，非本席改动。
   —— 「脱栅棘轮 1 处在册」无「条目富余」提示 = memory-canvas.tsx 的 canvas-font-12px 仍被认领 1 次（未赎债）。
cd webui && npm test                                     → TEST_EXIT=0，tests 29 / pass 29 / fail 0（基线同 29，未跌）
```

基线（改前跑）：`tsc=0`、`lint:layout=0`、`npm test=29 pass/0 fail`。改后三项全绿，形状不变。
**落盘后复跑两次（20:16 与 20:2x）三命令仍是 0 / 0（全部通过，脱栅棘轮 1 处仍在册）/ 29 pass 0 fail**。
本席两文件 mtime = `logs.tsx 19:48:57`、`memory-canvas.tsx 19:49:51`，而 `webui/dist/index.html`
mtime = `18:23:11` → **现产物不含本席改动**，收尾席须重跑 `npm run build`（本席按任务书禁 build，未跑）。

### 测1 = `%TEMP%\perf1\perf1-logs-measure.mjs`（`node --expose-gc`）

`formatTime` 用 `src/lib/format.ts` 经 esbuild 原样转译的**真身**（`%TEMP%\perf1\format.mjs`），
`detailsOneLine` 为该 4 行的逐字复刻（宿主文件是 JSX，Node 侧跑不了）。React 元素构造一项用
`createRequire` 从 `webui/node_modules` 取**真 react**（development 构建，故为上界）。

```
=== 1) 每秒 tick 的行内容工作量（500 行 = MAX_ROWS，一整趟） ===
  before：一趟 500 × (formatTime + detailsOneLine)        33642661 ns/次（5 轮取最优）
  after ：同 500 行改为 memo 浅比较一趟（上界）                      3947 ns/次（5 轮取最优）
  → 单行取格成本 = 67285 ns（formatTime 每次现场 new Intl.DateTimeFormat，实测最贵项）
  → before：每秒 tick 强制整页重渲染 → list 一趟 = 33.64 ms/tick × 86400 = 2907 s 主线程/24h（且单趟已超一帧预算 16.7ms）
  → after ：每秒 tick 只重渲染 StatusChip 叶子，list 完全不参与；33.64ms 只在「真有 state 更新」时发生，且降为 0.004ms（500 行浅比较上界）
  → 每次真实更新（事件入库/心跳/过滤）的行内容成本：33.64 ms → 0.004 ms（降幅 8524×）
  after 残余：rows.map 造 500 个 React 元素（真 react.createElement） 1029910 ns/次（5 轮取最优）
  → 改造后每次父页渲染（每 ≤16ms 窗口一次）残余元素构造 = 1029.9 µs，替代原先的 33643 µs 取格 + 500 子树渲染

=== 2) 重放/连 burst（k 条事件同批到达）的数组重建量 ===
  k=  1：2180ns → 1752ns（1.2×；元素复制 501.5 → 501）
  k= 50：92094ns → 2802ns（32.9×；元素复制 26,300 → 550）
  k=500：1001629ns → 6319ns（158.5×；元素复制 375,500 → 1,000）

=== 3) 暂停积压 backlogRef 的堆占用（--expose-gc） ===
  无界形态：200,000 行积压 = 95.5 MiB（≈501 B/行）
  封顶形态：500 行积压 = 0.24 MiB（≈508 B/行）
  → 10 条/秒挂机 24h = 864,000 行 ≈ 413 MiB 无上限堆积
  → 封顶后同一场景 ≈ 0.2 MiB（差 412 MiB）

=== 3b) droppedCount 账面等价（暂停 1200 条 / 视图已满 500 行） ===
  before：dropped=1200 可见行数=500
  after ：dropped=1200 可见行数=500（暂停期暂存 700 + 恢复裁剪 500）
  可见游标序列逐一相等 = true；dropped 总量相等 = true

=== 4) 判重/裁切等值性（3 万条混合流） ===
  窗口=  1：可见游标序列等值=TRUE dropped 24250→24250(=) seen 500→500（流含 5,250 条重复 cursor / 30,000 帧）
  窗口= 20：可见游标序列等值=TRUE dropped 24250→24250(=) seen 500→500（同上）
  窗口=200：可见游标序列等值=TRUE dropped 24250→24250(=) seen 500→500（同上）

=== 3c) 判重集 seenRef 上界（改造后含一个合并窗口缓冲） ===
  2 万条连续到达（每帧一提交）：rows=500，seen 峰值=501，终态 seen=500（=MAX_ROWS + 单帧缓冲）
```

### 测2 = `%TEMP%\perf1\perf1-canvas-measure.mjs`

绘制体 before/after **逐字复刻**，`getComputedStyle`/`Map`/`Set`/`toLowerCase`/`width` 赋值全部计数假件，
ctx 为记账假件；200 节点 / 400 边 / 过滤词命中 / dpr=2 / 60 帧拖拽（transform 与 hover 每帧变，数据不变）。
计时与计数分离（各跑各的，计数只跑一趟）。

```
before 60 帧: 5.38 ms / 60 帧（90 µs/帧）
after  60 帧: 1.73 ms / 60 帧（29 µs/帧）

=== 60 帧拖拽（200 节点 / 400 边 / 过滤词命中 / dpr=2）===
  getComputedStyle 调用                        每帧   8.00 →   0.13 次（60 帧合计 480 → 8，60.0×）
  getPropertyValue 调用                        每帧   8.00 →   0.13 次（60 帧合计 480 → 8，60.0×）
  new Map()（含 colors/nodeById）               每帧   2.00 →   0.03 次（60 帧合计 120 → 2，60.0×）
  new Set()                                  每帧   0.00 →   0.02 次（60 帧合计 0 → 1，新增）
  String.toLowerCase()                       每帧    601 →   3.35 次（60 帧合计 36060 → 201，179.4×）
  canvas.width 赋值（backing store 重建）          每帧   1.00 →   0.02 次（60 帧合计 60 → 1，60.0×）
  帧耗时（Node 侧复刻体，不含真实绘制）：90 µs/帧 → 29 µs/帧（3.1×）
  静态推断（未跑浏览器）：单次 width 赋值 = 重建 2200×960×4B = 8.1 MiB 位图；before 60 帧 = 483 MiB/秒的位图churn → after 1 次 = 8.1 MiB

=== 挂载序列：measure() 与 ResizeObserver 强制首报同值 ===
  before：挂载 2 次重渲染 / 整幅绘制 2 次 → after：1 次重渲染 / 1 次绘制（同值回写被吸收）

=== 0) 绘制指令逐笔等值性（改造前 vs 改造后，同一状态） ===
  k=1.2 过滤命中 + hover/selected        落笔  2212 笔 / 等值 = TRUE
  k=2.0 无过滤词（全标签显示）                  落笔  2404 笔 / 等值 = TRUE
  k=0.5 精确过滤 + 无选中                   落笔  2208 笔 / 等值 = TRUE
  k=1.6 边界 + 纯空白查询词                  落笔  2407 笔 / 等值 = TRUE
  悬空端点边（防御分支）                        落笔   688 笔 / 等值 = TRUE
  五组状态合计等值 = TRUE（改造前后光栅化信息逐笔一致）
```

### 测3 = `%TEMP%\perf1\perf1-intl-format-eq.mjs`（给 §七-1 的补丁做等值性与收益取证）

```
样本 56827 枚（本机 TZ=Asia/Singapore，locale=zh-CN）
formatTime 复用 formatter 逐枚等值 = TRUE
formatDateTime 复用 formatter 逐枚等值 = TRUE
  现状 formatTime（每次现场建 formatter）  14822888 ns/趟(500 枚)
  提案 复用模块级 formatter              397862 ns/趟(500 枚)
  → 一趟 500 行：14.82 ms → 0.40 ms（37×；单行 29646ns → 796ns）
```

### 本席**没有**测到的东西（如实交底，不暗示跑过浏览器）

- 真实帧时间/掉帧、真实 `canvas` 光栅化耗时、真实 backing store 重建成本（浏览器才有）。
- 真实 SSE 流吞吐与真实事件速率（未起服务、未连控制面、未发一个请求）。§一中所有「k 条/秒」的场景都是**给定到达率的投影**，不是观测值。
- React 调和/子树跳过的真实耗时（`memo` 的跳子是 React 文档语义，本席只测了它省掉的纯 JS 工作量）。
- `npm test` 无 DOM 环境（`node --test "src/**/*.test.ts"`，无 jsdom/happy-dom/RTL，Node 类型剥离不吃 JSX）→ 两文件的组件级测试**跑不起来**，见 §七-2。

---

## 四、等值性证据（「行为不变」的三块硬证据）

1. **canvas 绘制**：把「每个落笔操作 + 落笔时影响该笔结果的样式（fill←globalAlpha/fillStyle；
   stroke←globalAlpha/strokeStyle/lineWidth；fillText←再加 font/textBaseline）+ CTM 操作序列」录成指令表，
   before/after 同状态逐笔 JSON 比对，5 组状态（含 k=1.6 标签阈值边界、空白查询词、悬空端点边防御分支）
   **全 TRUE**。首轮比对曾报 FALSE，差异**只**在 `font`/`textBaseline` 的赋值时机（after 提到循环外一次）——
   而圆 `fill()` 不读 font，两赋之间无任何读 font 的操作 → 光栅化无从不同，遂把比对器改为「只取影响该笔的属性」。
   另注：`canvas.width` 赋值在浏览器里会重置 ctx 状态，省掉赋值后本帧仍显式写完所有被读的样式
   （globalAlpha/fillStyle/strokeStyle/lineWidth 每笔前都赋、CTM 每帧 `setTransform` 重置、
   `lineCap/lineJoin/miterLimit` 两版都从不触碰=保持出厂默认），不存在「沿用上一帧残留」的读侧。
2. **日志判重/裁切**：30,000 帧混合流（5,250 条重复 cursor，重放块最长 ~40 条）× 合并窗口 1/20/200 条，
   改造前/后**可见游标序列逐枚相等**、`droppedCount` 总量相等（24250→24250）、判重集终态相等（500→500）。
   窗口=1 即「改造前逐条提交」的同构，另两档证明合批不改变结果。
3. **暂停积压封顶**：dropped 总量与可见游标序列全等（§三-测1 段 3b）。原理：被积压裁掉的最旧行
   在改造前也必然在恢复时被 `MAX_ROWS` 裁掉，本席只是把「同一次裁剪」拆成两段并分别记账。

**刻意保留的存量形状**（不在本席授权内，动它就是行为改动）：
`setDroppedCount` 仍嵌在 `setRows` 的 updater 内部（StrictMode 双跑语义与改造前一致）；
`pausedRef.current = paused` 的渲染期赋值、`startStream` 的 `[]` deps 闭包形态、
游标 effect 的「每提交一写」全部原样。

---

## 五、用户可见差异清单（穷举）

| # | 差异 | 性质 | 判定 |
|---|---|---|---|
| 1 | 行从「随 React 合批提交」变为「随 ≤16ms 合并窗口提交」 | 时序，非内容 | 一帧级，肉眼无从分辨；重放大批时反而更快齐（一次画完 vs 逐条画）。§四-2 已证集合与计数不变。 |
| 2 | 暂停挂机时 `droppedCount` 的增长时机：改造前恢复瞬间一次性跳到 N，改造后暂停期间也稳定（值仍等于同一批的裁剪总数，只是分两段记账） | 时序 | 总量逐枚相等（§四-3）。 |
| 3 | 暂停积压峰值内存 413 MiB 级 → 0.2 MiB 级 | 资源 | 这就是 L-1 修复本身。 |
| 4 | 游标行/心跳 chip 的每秒刷新不再牵动整页 | 时序 | 文本内容与刷新节奏（1s）逐字同改造前；`lastCursor` 在暂停期仍每秒推进（`CursorLine` 自带秒表），实时期仍随父页渲染推进。 |
| 5 | 恢复暂停时，同一批积压里**重复 cursor** 由「渲染成两行 + React key 撞车」变为「判重成一行」 | 内容（角落） | 见 §七-4：这是把多行入口收进单行入口的**必然后果**，也是唯一可能的可见差异；重复 key 本身是 React 事故形态，本席不新增该风险。 |
| 6 | 后台标签页：合并窗口定时器被浏览器节流时，行的可见延迟随节流档位放大（≥1s） | 时序 | 不可见期间无肉眼差异；回前台一帧内追平。改造前的 updater 链同样受同一节流支配（回调本就在 fetch 读流里）。 |

除此之外：**状态机、缺口横幅、410 重订阅、过滤器、断开/连接按钮、自动滚底开关、行文本本体、卡片外壳，全部逐字未动。**
本席**没有**去修任何顺手可见的 UX 问题（§六列了三项，只登记）。

---

## 六、拒绝动的东西（带数字与理由）

1. **`memory-canvas.tsx` 的 `12px` canvas 字体**：任务书点名的在册债，且与宪法门有**键耦合**——
   `webui/scripts/layout-constitution.mjs` 的 `OFFGRID_RATCHET` 条目形如
   `components/graph/memory-canvas.tsx|canvas-font-12px`（棘轮键含**相对路径**）。把该字面量移出本文件
   （或移进新 `.ts` 模块）会让旧键「条目富余」+ 新键「未登记认领」= **门直接红**，而门脚本对本席只读。
   本席只把**赋值次数**从「每节点一次」提到「每帧一次」，字符串字面量与所在文件不变（现仍恰 1 处命中，门输出「脱栅棘轮 1 处存量在册」）。
2. **`<LogList>` 再包一层 memo**：实测父页渲染残余 = 500 个 `react.createElement` **1.03 ms**（dev 构建口径，上界）。
   但改造后父页渲染**只在 rows 真变化时发生**，包一层只在心跳（1/15s）与状态变更路上省 1.03 ms
   ≈ **0.1% CPU** → 说不清「N 行→省多少次扫描」，按任务书「不可证明就不做」，不动，登记。
3. **`useSecondTick` 加开关（不显示距今秒数时干脆不转）**：能再省掉不连接时的 1 次/秒微渲染，
   但要引入「何时有显示」的判定，且首个可见值有相位风险；收益量级 µs → 不做。
4. **`formatTime` 的 Intl 现场建形制**：单枚 29.6 µs 是日志页残余最贵项，但真身在**只读** `lib/format.ts`，
   且被全站页面消费 → 补丁原文交主会话（§七-1），本席不动一行。
5. **`pick()` 每次 pointermove 一次 `getBoundingClientRect()`**（`memory-canvas.tsx:128-146`，命中检测必需，鼠标速率级）：
   缓存 rect 需引入 scroll/resize 失效链，风险 > 收益 → 登记不改。
6. **心跳 `onHeartbeat` 改纯 ref**（可让父页 15s 一次的重渲染也没了）：会把「距今 N 秒」归零显示拖慢 ≤1s，
   属可见差异 → 不改，登记。
7. **`logs.tsx:98` 的 `'—'` 字面量**（应为 `format.ts` 的 `UNKNOWN_VALUE`）：UNI1 §四已登记为只读面残余，
   本席搬迁时**逐字保留**，不越权收口。
8. 表 §1-L2（sessionStorage 每提交一写）、L-4/L-5/L-6/L-7/L-8：见 §一判定行与 §七-3。

---

## 七、待主会话（本席无权动，逐条给坐标与改法）

### 1) `webui/src/lib/format.ts`：Intl formatter 现场建 → 模块级复用（**实测 37×**，等值性已证）

现状（`formatTime` 单枚 29.6 µs；`formatDateTime` 同形）：

```ts
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN_VALUE;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString('zh-CN', { hour12: false });
}
```

提案（守卫两行逐字不动，只换最后一行的取格方式；`formatDateTime` 同法）：

```ts
// zh-CN 时间/日期时间两枚常驻 formatter（现场构造 Intl formatter 是本库最大的单项开销：
// 实测单枚 29.6µs → 复用 0.80µs，37×；等值性 56,827 枚样本逐枚全等，见 PERF1-impl.md §三-测3）。
// 注：本库口径写死 zh-CN（与 i18next 语言无关），故 formatter 无需按 locale 建 key；
//     若将来改成跟随 UI 语言，必须换 Map<locale, formatter>，否则会串语言。
const ZH_TIME = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const ZH_DATE_TIME = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: 'numeric', day: 'numeric',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});
// formatTime → return ZH_TIME.format(date);
// formatDateTime → return ZH_DATE_TIME.format(date);
```

取证与边界：等值性在 **TZ=Asia/Singapore（无 DST）/ locale zh-CN / 2022-01-01→2025-12-31 每 37 分钟一枚
= 56,827 枚 + 5 枚手工边界**上逐枚全等；**DST 时区未覆盖**（同选项集下理论上不应差异，但那是推断不是实测）。
`formatInt`/`formatBucket`/`compactNumber` 同族未验证，若一并收口需同法逐枚对账。
建议采纳时同步在 `src/lib/format.test.ts`（本席只读，写不了）把「逐枚等值」做成常驻锁。

### 2) 两文件的测试提案（本席无权建，且现测试基建吃不下）

`package.json:11` 的 test 入口 = `node --test "src/**/*.test.ts"`（Node 原生类型剥离），**没有 DOM 环境**、
**不吃 JSX**（`.tsx` 进不来），`src/lib/*.test.ts` 对本席只读；`src/components/graph/` 虽在本席名下，
但要在那里放可跑的测试就得把绘制体抽成 `.ts` 模块 → 触发 §六-1 的棘轮键耦合（门红）。两条路请主会话裁：

- **路 A（推荐，零新基建）**：把「行的判重/合并/裁切/暂停积压」这套纯逻辑从 `logs.tsx` 抽到
  `webui/src/lib/logs-buffer.ts`（纯函数 + 注入 `now`），配 `logs-buffer.test.ts` 钉死三条不变量：
  ①同批重复 cursor 只留一条；②裁出的行可被再次接受（判重位已释放）；③`clear` 后 rows/dropped/seen 同归零；
  ④暂停积压永不超过 `MAX_ROWS` 且 dropped 总量 == 改造前一次性裁剪的枚数。
  代价 = 多一个 lib 文件 + logs.tsx 变薄（本席**没有**做，因为跨了只读面）。
- **路 B（要新基建）**：给 `webui` 加 `jsdom` + 组件级 runner，钉「每秒 tick 不重排 list」
  （断言行渲染次数，而非实现形状）。这是 F8-L-7「前端零性能门」的正解，但需用户裁定引入依赖。

### 3) 本席面外但已在 F8 在册的四条（只点名，未动）

- **L-4** 轮询魔数：现复跑 `grep -rn "refetchInterval: [0-9]" webui/src/pages` = **10 处**（审计记 9，并发波 +1）。
- **L-5** `apiRequest` 零超时 / `useSemanticQuery` 不透传 `signal`（`lib/**`，本席只读）。
- **L-8** `router.tsx` 九页顶层静态 import（recharts/d3-force 进首屏同步链）。
- **L-6/L-7** 后端 TTS 磁盘配额、前端产物体积门（`.py` 面，本席不碰，未跑 pytest）。

### 4) 一处请复核的语义收口（本席主动统一，非任务书要求）

改造前多行入口 `appendRows(backlog)` 用的是 `incoming.filter(r => !seen.has(r.cursor))`，
**同批内重复的 cursor 不会被折叠**（两条同 cursor 会一起进视图 → React key 撞车）；
单条入口因每次只喂一条而碰不到它。本席把两条入口统一成「逐条同步判重+登记」，于是该角落从
「两行 + 撞 key」变成「一行」。这是 §五-5 的唯一内容级差异，方向是更安全，
但**它是差异**，按规矩交主会话过目（若要逐字复刻旧形态，就得在合并路径上重新引入撞 key，本席不做）。

### 5) 哈希/构建牵动

本席只改两个 `.tsx`，**未 build**（`dist/index.html` 仍是 16:30 快照那 973,154 B 旧产物）。
按 F8 §八：纯前端源码改动不进 `tests/verify_hashes.py` 的 12 交付物册；触发的是收尾席的**统一重构建**。

---

## 八、纪律自证

- 写操作只落在两个授权文件 + 本台账；测量脚本一律 `%TEMP%\perf1\`（三个 `.mjs` + 一个 esbuild 产物 `format.mjs`），
  源码树零新增文件、零 `__pycache__`（未跑过 Python：零 `.py` 改动，未跑 pytest）。
- 未跑 `npm run build`、未跑 `tsc -b`；只跑 `npx tsc --noEmit -p tsconfig.app.json`。
- 无 git 写操作、无删除、未起服务、未占端口、未发真实请求、未读 `.env`。
- 只读面（`webui/src/lib/**`、locales、`scripts/layout-constitution.mjs`、`package.json`、
  `components/layout/**`、`router.tsx`、全部 `.py`）零改动——门脚本从 58 自测涨到 102 自测是并发席所为，
  本席复跑确认与本席两文件无冲突。
- 引用坐标前先复跑 grep（本文所有行号为 2026-09-19 20:0x 快照口径；F8 原文行号是 16:30 快照，两者不等，故逐条并列给出）。

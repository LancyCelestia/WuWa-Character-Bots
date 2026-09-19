# F3 · WebUI 页面与组件层穷尽式实读审计（2026-09-19）

## 快照声明

- 审计时间：`date` 实跑 = **2026-09-19 16:07:38**（本地）。
- 树并发：本席只读不动源；`git status --porcelain=v1 | wc -l` = **878**（工作树大量在飞改动，本文件为唯一新增落盘物）。
- 产物参照：`webui/dist/index.html` mtime 09-19 03:55，最新 src（settings-dialog/api-client）mtime 03:54 → **dist 不早于全部 src**，其 CSS 字节序可作为层叠裁决证据；若后续会话再改 src 未重建，该证据需重取。
- 纪律：未跑 `npm build/dev`、未开浏览器、未做任何 git 写操作；全部结论以源码实读 + 只读程序化统计为据。

## 〇、实盘页数与总体量

- `webui/src/pages/` 实盘 **9 页**：dashboard / calls / tokens / latency / affinity / logs / knowledge / plugins / memory-graph（`ls` 实测，与「9 页」宣称一致）。
- 字典：`locales/{en,zh-CN}/common.json` 展平后 **238 = 238 键，零单侧键、零空值**（命令见 §六，宣称属实）。
- 全 src：`role=` **0 处**、`tabIndex` **0 处**、`ErrorBoundary` **0 处**（命令：`grep -rn "role=\|tabIndex\|ErrorBoundary" webui/src` → 无匹配）。

---

## 一、九页逐页审计表

图例：✓ 有 / ✗ 缺 / — 不适用。「ok-null」= `useSemanticQuery` phase='ok' 但 `data=null`（`api-client.ts:210` 明文 `payload.data ?? null`）时的行为。

### 1. dashboard（总览）

| 维度 | 判定 | 证据 |
|---|---|---|
| 数据加载 | react-query 6 路 + `refetchInterval` 30/60s | `:93-99` |
| loading | ✓（骨架 + SemanticState 骨架卡） | `:77-84`、`:28-30` |
| empty | ✓（'—' 占位） | `:70/74` |
| error/unavailable | **部分✓——botProcess 卡静默降级**：`value={formatUptime(...)}` 恒为字符串→StatCard `value!==undefined` 分支恒真，`withFallback(botStatus.state, null)`（`:163`）永不渲染，错误/未配置只显 '—' 无原因 | `patterns.tsx:27` + `dashboard.tsx:156-163` |
| 可空渲染 | null-data 全页有 `x ? … : null` 三元防护 ✓；但 `latencyData.items.filter/length`（`:121-122`）、`totals?.tokens.input.value`（`:187`，`tokens.input` 段无 `?.`）依赖 DTO 形状 | ok-null → 不炸（三元兜住） |
| 字号 | 全走 fs-*；P2-11 残余 `?? 0` 把未知画成 0（`:184/:187`）——**仍在** | — |
| 键盘/焦点 | 原生 Button/Link ✓ | — |
| aria | PageHeader h1 ✓；卡片标题全 div（无 h2 层级）；60s 静默刷新无 aria-live（读屏无感，与 logs 相反的取舍） | — |

### 2. calls（调用统计）

| 维度 | 判定 | 证据 |
|---|---|---|
| 加载 | ✓ react-query + 60s 轮询；`SemanticState` 四态全 | `:92-96` |
| loading/empty/error | ✓✓✓（trend 空、TopList 空均有文案位） | `:65/:156-157` |
| 可空渲染 | **ok-null 炸**：phase ok 直接把 `query.state.data` 传入 `CallsBody`（`:134`），`[...data.trend.items]`（`:144`）、三处 `data.by_*.map`（`:186-198`）无判空 → data=null 时 TypeError | — |
| 字号 | 控件（WindowSwitch/bucket 钮）挂 fs-caption ✓；无裸字号 | — |
| 键盘 | 原生 button ✓；窗口切换钮无 `aria-pressed`（选中态只靠色） | `:30-41` |
| aria/语义 | h1 ✓；图表 SVG 无文字替代（同数据有 TopList 文本面，可接受）；`window` 遮蔽全局（`:89`） | — |

### 3. tokens

| 维度 | 判定 | 证据 |
|---|---|---|
| 三态 | ✓✓✓；空族列表有文案 | `:135/:206` |
| 可空渲染 | **ok-null 炸两处**：`data.families.some`（`:84`）与 `TokensBody` 内 `[...data.families]`（`:120`）；`totals.tokens[key]`（`:182`）链无 `?.` | — |
| 字号 | 窗口钮同 calls 不同实现（重复造轮，见 §四-5）；fs-caption ✓ | `:91-106` |
| 内联样式 | recharts `contentStyle borderRadius:12` 字面量（`:156`）、`fontFamily:'monospace'` 字面量（`:151`）——绕 token | — |
| aria | h1 ✓；`?${n}/~${n}` 质量徽章符号语义硬编码（`:34/:40`） | — |

### 4. latency

| 维度 | 判定 | 证据 |
|---|---|---|
| 三态 | ✓✓✓（history 的 `not_persisted` 诚实态做得最好：全 `?.` 链） | `:91-101` |
| 可空渲染 | **ok-null 炸**：`query.state.data.items.length/map`（`:71/:72/:76`） | — |
| 响应式 | **390px 不可用重灾区**：DataGridRow 固定列宽 `w-56+w-24+w-20×3+w-12` ≈ 608px+gap，`shrink-0` 全列不许收缩，全 src 横向滚动容器=0，`html overflow-x-hidden`（index.css:206）→ 右列（错误/最近成功）直接裁没、无法滑看 | `:25-45` |
| 语义 | 渠道表 div 拼的，无 table/role/列头——读屏器把每行读成无关联文本流 | — |
| 硬编码 | `EWMA / {t(…)} / {t(…)}` 斜杠拼接组句（`:63-65`）、`×${fails}` 徽章（`:40`） | — |

### 5. affinity

| 维度 | 判定 | 证据 |
|---|---|---|
| 三态 | loading/empty/error ✓；**ok-null → 页面开天窗**：`:94` 条件 `phase==='ok' && data` 不满足时把 **phase 'ok'** 传给 `SemanticState`，而它 `phase==='ok'` 分支 `return null`（semantic-state.tsx:120）→ 内容区整体空白无任何提示 | 静态可判 |
| 可空渲染 | `item.score.toFixed(1)`（`:49`）裸调——score 契约 number，null/undefined 即炸；`data.items.length`（`:96`） | — |
| 字号 | 控件钮 fs-caption ✓；分数用 `fs-card`（14px w600）——与宪法「fs-card=卡片标题」语义档位错位（数值合规、语义漂移） | `:47` |
| 响应式 | 行固定列 `w-8/w-24/w-24/w-36`+gap ≈ 416px > 390px → flex-1 昵称列被压至零宽 | — |
| aria | 排序钮有图标+文字 ✓；无 `aria-pressed`；榜单无 list/table 语义 | — |

### 6. logs

| 维度 | 判定 | 证据 |
|---|---|---|
| 三态 | 流式页无查询态：status 徽章七态全字典覆盖 ✓、gap/auth 横幅 ✓、waiting/idle ✓ | `:184-242` |
| 静默面 | `sources` 查询失败零提示：`:175-176` 非 ok → 空数组，两个 select 永远只剩「全部」项，无一行「来源列表加载失败」——**无提示降级**；且 `sources.state.data.items` 同属 ok-null 炸族 | — |
| aria | **`aria-live='polite'` 挂在 ≤500 行实时追加列表**（`:287`）——每条 SSE 事件都进读屏播报队列，轰炸实锤（P2-13② 仍在）；两个 `<select>` 无可访问名（旁边 `<span>` 非 label、无 aria-label）`:246-269` | — |
| 竞态/泄漏 | 心跳秒表 interval 有清理；SSE 卸载 stop；`key={row.cursor}` 在重放重复游标时撞 key（与 P1-4 联动，仍在） | `:125-128` |
| 其它 | `eslint-disable-next-line` ×2 但项目无 eslint 依赖（指令空转）；行分隔线 flex 无 overflow-x——长 message 已 `break-words` ✓ | — |

### 7. knowledge

| 维度 | 判定 | 证据 |
|---|---|---|
| 三态 | 全仓最齐：collections loading 骨架 / error 404 特判「未部署」/ unavailable / not_provisioned / auth / 全禁用诚实态 / 搜索空态 + 清除钮 | `:128-189/:251-269` |
| 可空渲染 | **ok-null 炸**：`:97` `collections.state.data.items.filter` 在 return 前无条件执行；`item.aliases.length`（`:45`）——DTO 注释自认「字段随集合类型增减」但 aliases 钉为必填，meme_tags 类若省略即炸 | — |
| 竞态 | 300ms 防抖有清理；react-query 按 key 隔离无覆盖问题 ✓ | `:108-115` |
| aria | 搜索框无 label/aria-label（仅 placeholder）`:198-207`；词条网格非 list 语义 | — |
| 展开钮 | `definition.length > 96` 硬编码阈值配 `line-clamp-4`——CJK 与 latin 宽度差下「可见截断但无钮/有钮无截断」双向错位 | `:51` |

### 8. plugins

| 维度 | 判定 | 证据 |
|---|---|---|
| 三态 | ✓✓✓（组级 unavailable 一卡诚实、三字段缺省全不渲染——本波 BACKEND3 兼容做法正确） | `:114-124/:41-45` |
| 可空渲染 | **ok-null 炸**：`:152` `[...query.state.data.groups]`；`group.items.length/map`（`:129/132/136`） | — |
| 标题 | h1（PageHeader）+ 组标题 `<h2 className='fs-page'>`——**与 h1 同字号**（P2-13③ 仍在）；卡内标题仍 div | `:128` |
| key | `key={`${item.name}:${index}`}` 含 index——列表重排时 diff 失效（轻） | `:137` |
| 排序 | `GROUP_ORDER.indexOf(id)` 未知 id → -1 混排（后端加组即顺序漂移，轻） | `:152-154` |

### 9. memory-graph

| 维度 | 判定 | 证据 |
|---|---|---|
| 三态 | loading 骨架 / error 404 特判 / 非 ok→SemanticState / 空图诚实 ✓；**unavailable 时统计卡整块静默消失**（`:102` `data &&`，无一行提示，与画布区的诚实横幅不对称） | `:95-109` |
| 可空渲染 | `Object.entries(data.sources)`（`:74`）、`data.stats.*`（`:81-86`）、`data.nodes/edges.length`——ok-null/缺段即炸；`selectedNode.weight` 裸数字不经 `formatInt`（`:230`，统一参数漂移） | — |
| 内联样式 | `style={{ height: 480 }}` = 登记「内联白名单 #1」原样在（`:183`）；`memory-canvas.tsx:179` canvas `context.font='12px "Segoe UI"…'` 硬编码字体**仍未收**、仍无豁免登记（P1-3④ 残余） | — |
| 键盘 | **画布零键盘面**：canvas 无 tabIndex、无键盘选点途径、无列表替代——图数据对键盘/读屏完全不可达（全 src tabIndex=0 处） | memory-canvas.tsx:188-224 |
| 移动端 | canvas `touch-none` 吞触摸滚动，480px 高画布区=滑动黑洞；侧详情 `xl:w-80` 已堆叠 ✓ | `:192` |
| 注释漂移 | 头注「d3-force 静态画布」——实现是 `graph-layout.ts` 自研布局（d3-force 仅依赖在册），文档口径不符 | `:21` |

---

## 二、鲁棒性 / 白屏面

1. **ErrorBoundary 现状 = 零自建**（`grep -rn "ErrorBoundary\|defaultErrorComponent\|errorComponent" webui/src` 无匹配）。缓解因素：TanStack Router ≥1.x 的 `RouterProvider` 对**路由渲染期**异常自带默认错误组件（非白屏，但是裸英文样式崩坏页）；`ThemeProvider`/`QueryClientProvider` 自身渲染抛错在 RouterProvider 之上，**无任何兜底**；`main.tsx:29` `getElementById('root')!` 非空断言。结论：旧审计「一炸全白」**措辞偏重、方向成立**——路由内崩溃=英文默认错误页（对本项目等于体验全毁），壳层崩溃=白屏。P1-5' 判「仍在（修正表述）」。
2. **ok-null / 字段漂移崩溃族**：10 文件约 30 处点号链（逐坐标见各页表；统计命令 `grep -n "state.data\." webui/src/pages/*.tsx`）。根因单点：`useSemanticQuery` 在 `resolveSemantic` 返回 `{state:'ok', data:null}` 时原样透出 phase='ok'（api-client.ts:210 `?? null` 是自家注释承认的形态）。**一处收编改法**：在 hook 里把 `phase==='ok' && data==null` 归为 `{phase:'unavailable', reason:'empty_payload'}`，九页同刻免疫——这是「统一架构/统一函数」在前端的正确落点，当前缺。
3. **useEffect/清理审计**：15 个 effect 中 13 个清理正确（ResizeObserver/MutationObserver/wheel/matchMedia/自定义事件/debounce timer/interval/stream stop）；settings-dialog 保存路径 `setTimeout(reload,600)` 未清理（600ms 后整页刷新，实际无害）；logs 挂载 effect `[]`+eslint-disable 双重豁免但无 eslint 基建。**未发现卸载后 setState 路径**（SSE 回调经 stop 阻断）。**未发现 async 竞态**：窗口/集合/页码切换全部走 queryKey 变更，react-query 按 key 隔离缓存。
4. 常驻门：`tests/test_webui_constitution.py` **不存在**（`ls` 实测）→ P1-2「三门游离」仍在；pytest 全量对 webui/src 破坏裸 hex/删种子零感知。

---

## 三、响应式与 390px 视口逐页判定

共同前提：aside `hidden … md:flex`（app-shell.tsx:73），**md 以下全站无任何导航替代**（P2-12 仍在：顶栏只有主题+设置两钮，九页可达性=手敲 hash）；`html overflow-x-hidden` 且全 src `overflow-x` 容器 **0 处**（grep 实跑，total: 0）→ 横向溢出内容不可达。

| 页 | 390px 判定 | 决定性缺陷 |
|---|---|---|
| dashboard | 可用 | 仅缺导航（1 列堆叠正常） |
| calls | 可用 | 头行 flex-wrap ✓；图表 ResponsiveContainer 自适应 |
| tokens | 勉强 | YAxis `width={150}` 竖排类目吃掉 39% 视口宽度 |
| latency | **不可用** | 固定列宽 ≈608px，无横滚容器，右列（错误详情）被裁死 |
| affinity | 差 | 固定列 ≈416px → 昵称列压至零宽 |
| logs | 可用 | 动作钮 wrap ✓；行 `break-words` ✓ |
| knowledge | 可用 | 搜索/ chips / 卡 1 列 ✓ |
| plugins | 可用 | 同 knowledge |
| memory-graph | 差 | canvas `touch-none` 滑动黑洞 + 图不可键盘达；统计/工具行 ✓ |

其它桌面成立面：settings-dialog `max-w-lg`+`p-6`（小屏 16px 内边距尚可）；`h-svh` 全家（正常）；Pager `justify-end` 小屏换行未设（轻）。

---

## 四、组件库统一性（统一参数·前端版）

1. **`cn()` 裁决：确实是 tailwind-merge**。`webui/src/lib/utils.ts:5-7` = `twMerge(clsx(inputs))`；`node_modules/tailwind-merge` 实装 **3.7.0**（v3 默认配置支持 Tailwind v4）；全 src 无 `extendTailwindMerge`。→ 旧 P1-1 若被归因「cn 没用 tw-merge」属**报告写错**；该条自己的「dist 字节层叠」归因才是对的。
2. **真根因：twMerge 对自定义 `@utility` 全盲 + Tailwind 输出顺序**。fs-* 不在 twMerge 任何冲突组 → 与 `leading-*`/`font-*` 永不互斥；dist 实测序：`.fs-body@949545 < .fs-caption@949609 < .fs-card@949675 < .leading-none@949803 < .font-medium@950016 < .font-semibold@950204`，同特异性后来胜 → **内建工具恒压 fs-* 同名属性**。
3. **同族隐患点名（全量 4 处）**：
   - `card.tsx:31` `leading-none` vs 页面传入 `fs-card` → 行高恒 1（多行标题粘连，P1-1 症状仍在）；
   - `button.tsx:9` 基类自带 `fs-body font-medium` → w400 档声明恒被 w500 压掉（若属有意，则「五档阶梯」表 w400 一行对按钮族名不副实）；
   - `badge.tsx:9` 同型 `fs-caption font-medium`；
   - `patterns.tsx:116` CategoryChip 同型。
   修法方向（不落盘）：CardTitle 删 `leading-none`；或 `extendTailwindMerge` 把 fs-* 注册进 font-size/line-height/font-weight 三组。**当前无任何回归锁**。
4. cva 口径：button/badge 用 cva 且尺寸族齐（含 icon-sm/lg）；card/skeleton 无 cva（纯基类）——组件间无第二套 token，间距全 4px 栅格 ✓；语义色全走 tone-*/chart-* ✓（宪法门 1-4 条覆盖，实跑绿否以门自身输出为准，本席未跑构建）。
5. **同功能两实现**：calls.tsx:25-44 `WindowSwitch` 组件 vs tokens.tsx:91-106 内联复制（类表差 `transition-colors`、active 分支写法不同）——「统一组件」违例；三页窗口钮 + memory-graph 窗口 chip 组实为第四种形态。
6. 硬编码 zh-CN locale 五处（format.ts:5/30/37/45/53）：`formatInt/formatDateTime/formatTime/formatBucket/compactNumber` 在 en 语言下仍按 zh-CN 出数——「统一变量」未贯通到格式化层（应传 `i18n.language`）。

---

## 五、无障碍与语义三件（P2-13/14 核销 + 穷举）

| 项 | 现状 | 证据 |
|---|---|---|
| 弹窗 role/aria-modal/Esc/焦点陷阱/归还 | **全缺（仍在）**：settings-dialog.tsx:78-84 两 div onClick、零 role、无 keydown/Esc 监听、打开不移焦、关闭不归还、h2 无 id 可 labelledby | 实读 |
| 长列表 aria-live | **仍在**：logs.tsx:287；且页头 status 徽章每秒心跳秒数更新不在任何 live 区（该报的不报、不该轰炸的在轰炸——两头都错） | 实读 |
| 标题层级 vs 字号 | h1 九页齐 ✓；层级第二档仅 plugins h2（fs-page 与 h1 同字号，P2-13③ 仍在）与弹窗 h2；**卡片/区块标题全 div**——七页无中间层标题 | grep `<h[1-6]` = 5 命中 |
| 图标钮可访问名 | app-shell 设置钮/ThemeSwitch/弹窗关闭/显隐钮 4 处 aria-label ✓（全 src aria 面=4×aria-label+1×aria-live）；logs 两 select 与 knowledge/memory-graph 两搜索框**零可访问名** | grep |
| 绝对定位参照 | theme-switch Moon `absolute`、Button 基类无 `relative`（P2-14 仍在）——按 CSS 规范 flex 容器 abspos 子元静态位置=「视作唯一 flex 元」居中，**当前不飞属规范行为而非巧合**，但参照物确非按钮（header sticky 才是 containing block），header 结构一改即飞 | theme-switch.tsx:19-20 |
| 导航当前页 | 侧栏 active 仅类名 `[&.active]`，无 `aria-current='page'` → 读屏器不知在哪个页 | app-shell.tsx:34 |
| 表格语义 | DataGrid 族全 div；latency/affinity/logs 三张数据表无 table/role/列头 | patterns.tsx:84-96 |
| 画布 | canvas 无 tabIndex、无键盘替代列表 | memory-canvas.tsx:190 |

---

## 六、双语言 / 文案一致性（实盘数，不抄宣称）

- **键数：en 238 = zh-CN 238，差集两侧均空，值空串 0**（命令：固定 venv `python -` 展平比对，输出 `en keys: 238 zh keys: 238 / en-only: [] / zh-only: []`）。「238=238」宣称**属实**。
- 代码静态 `t()` 192 键**零缺键**；46 个「看似未用」键全部由 10 个动态模板前缀（`calls.window.*`/`logs.status.*`/`knowledge.scope.*`/`memoryGraph.window|type.*`/`tokens.${key}`/`reason.*`）消费，reasonKey 白名单 18 码与字典 18 个 `reason.*` 键**一一对表零漂移**。
- 复数：27 键带 `{{count}}` 且**两侧均无 `_one/_other` 键**；node -e 实跑 i18next 25.x：缺复数后缀时回退基键正常渲染（`count=1 → "1 unattributed"`），**无 missingKey 事故**，但英文单复数同形（"2 calls" 类由文案自带、"1 memes" 出现在 knowledge.memeCount）属用户裁量项。
- 插值口径：字典内 **28 键全部 `{{var}}` 单形态，零 `{n}`/`${n}` 混写** ✓；**但组件侧 9 处拼接绕参数机制**：dashboard.tsx:159/187 与 :38-42（`：`连接）、latency.tsx:63-65（`/` 连接）、tokens.tsx:130/34/40（`· `、`?${n}`、`~${n}`）、plugins.tsx:28（`：`前缀）、knowledge.tsx:46（`、`分隔符）——「统一参数」未完成面。
- **硬编码用户可见文案 6 处 + 1**：settings-dialog.tsx:51-53 三条双语串（自带「披露于 progress-HARDEN.md」注释=有意豁免但未进门禁/未入字典）、sse.ts:126「响应无正文流」、sse.ts:159 缺口兜底句（两者会经插值直接上屏）、format.ts:20-22 运行时长中文单位、index.html:15 `<title>守岸人控制台</title>` 语言永不切换。

---

## 七、内联样式 / 资源穷举（含已登记豁免核实现状）

JSX `style={{}}` 全 src **2 处**：calls.tsx:77（条宽动态 %，语义正当）、memory-graph.tsx:183（`height:480`，「内联白名单 #1」**仍标仍用**，未扩号）。
宪法门不可见的内联面（recharts props，6 处）：calls.tsx:166/169/171、tokens.tsx:143/151/156——其中**字面量违规 3**：`borderRadius:12` ×2（12 不在 webui 圆角三档 30/18/14）、`fontFamily:'monospace'` ×1（--font-mono 有 token 不吃）；其余 `stroke/tick.fill` 走 `var(--token)` 合法。
canvas 内联 1：memory-canvas.tsx:179 字体串「12px Segoe UI/Microsoft YaHei」——与 --font-sans 同族但手抄，**仍未登记豁免**（P1-3④ 残余）。
图标：lucide 统一 ✓；`size-4/size-2` 全走类 ✓；`no-scrollbar`（index.css:217）**定义零消费**=死码。

---

## 八、新发现台账（七要素；严重度按 P0 阻断/P1 会错/P2 欠账/P3 卫生）

> 验证命令统一前缀：只读 grep/python，均在仓库根执行；「回归锁」列指**现状**有无。

1. **P1｜设置面板「保存」清空已存双令牌**｜`webui/src/components/settings/settings-dialog.tsx:64-65`+`:41-42`＋`lib/api-client.ts:88-90`｜锚点 `setApiToken(adminToken, 'admin')`｜根因：弹窗每次打开把输入框重置为空串（不回显），save() 无条件把空串走 setApiToken → 空值=删除 localStorage；用户只改 baseURL 不重贴 token 即静默清权，全站降级 not_provisioned｜改法：`save` 内 `if (adminToken.trim()) setApiToken(...)`（空输入=保持原值），或「仅当用户触碰过输入框才写」｜验证：`grep -n "setApiToken(adminToken" webui/src/components/settings/settings-dialog.tsx`＋单测断言空输入不调用 setApiToken｜回归锁：**无**。
2. **P1｜dashboard botProcess 卡静默吞三态**｜`pages/dashboard.tsx:156-163`＋`patterns/patterns.tsx:27`｜锚点 `value={formatUptime(botData?.uptime_seconds)}`｜根因：value 恒为字符串，StatCard 恒走 value 分支，children 里的 withFallback 成死码——botStatus error/unavailable 只显示 '—'｜改法：`value={botData ? formatUptime(...) : undefined}`（其余卡同型写法本就如此）｜验证：`node --experimental-strip-types` 不适用；静态 `grep -n "value={formatUptime" webui/src/pages/dashboard.tsx` 应带三元｜回归锁：无。
3. **P1｜fs-* 阶梯属性被内建工具恒压（twMerge 盲区族）**｜`ui/card.tsx:31`、`ui/button.tsx:9`、`ui/badge.tsx:9`、`patterns/patterns.tsx:116`｜锚点 `cn('leading-none font-semibold', className)`｜根因：twMerge 不识 `@utility fs-*`（无 extendTailwindMerge）+ dist 序 fs-* 在前 → line-height/font-weight 冲突内建恒胜；行高塌陷致多行卡标题粘连（fs-card 22px 行高名存实亡）｜改法：CardTitle 删 `leading-none`；并加 dist 断言门（`.fs-card{` 偏移必须 > `.leading-none{` 或源码级禁 CardTitle 基类含 leading-*）｜验证：`node -e "const h=require('fs').readFileSync('webui/dist/index.html','utf8');console.log(h.indexOf('.fs-card{'),h.indexOf('.leading-none{'))"`（现状 `949675 949803`→后者胜）｜回归锁：无（宪法门不扫 leading/font-weight）。
4. **P2｜ok-null/字段漂移崩溃族（30 处/10 文件）+ affinity 开天窗**｜坐标全列于 §一各页表｜锚点 `payload.data ?? null`（api-client.ts:210）｜根因：hook 对 `{status:'ok',data:null}` 无归一，页面点号链裸奔；affinity 页把 ok 态传进只认非 ok 的 SemanticState → null｜改法：hook 单点：`semantic.data==null → phase:'unavailable'`；页面免逐处补判空｜验证：`grep -c "state.data\." webui/src/pages/*.tsx`｜回归锁：无。
5. **P2｜latency/affinity 390px 固定宽表不可达**｜`pages/latency.tsx:25-45`、`affinity.tsx:36-57`｜锚点 `w-56 shrink-0`｜根因：固定列宽和 > 视口、无 `overflow-x-auto` 容器、`html overflow-x-hidden` 裁死｜改法：表外层 `overflow-x-auto` 一行（列定义不动）｜验证：`grep -rn "overflow-x" webui/src`（现状 0）｜回归锁：无。
6. **P2｜弹窗无 dialog 语义/Esc/焦点管理**｜`settings-dialog.tsx:78-91`｜锚点 `<div className='fixed inset-0 z-50`｜改法：`role='dialog' aria-modal='true' aria-labelledby` + keydown Esc + open 时 focus 首输入框 + 关闭归还（旧 P2-13① 的施工图，维持有效）｜回归锁：无。
7. **P2｜logs 筛选控件无可访问名 + sources 失败无提示降级**｜`pages/logs.tsx:175-176/246-269`｜锚点 `<select value={sourceFilter}`（无 id/aria-label）｜改法：select 补 `aria-label={t('logs.filters')}` 族；sources 非 ok 时筛选行右侧挂一行人话｜验证：`grep -n "aria-label" webui/src/pages/logs.tsx`（现状 0）｜回归锁：无。
8. **P2｜本地化贯穿缺失：zh-CN 硬编码于格式化层**｜`lib/format.ts:5/20-22/30/37/45/53`｜锚点 `toLocaleString('zh-CN')`、`${days}天${hours}小时`｜改法：format* 接 locale 参数（i18n.language 注入）或全量走 `Intl.*` 默认 locale；单位进字典｜回归锁：无。
9. **P2｜P1-2 三门未常驻**（承接旧账，非新发现，此处核销用）：`ls tests/test_webui_constitution.py` → 不存在。
10. **P3｜同功能钮多实现漂移**：calls.tsx:25-44 vs tokens.tsx:91-106 vs memory-graph.tsx:115-119（三形态窗口切换钮）。改法：抽 `patterns.tsx` 一个 `WindowTabs`。
11. **P3｜window 标识符遮蔽全局 ×3**：calls.tsx:89、tokens.tsx:73、memory-graph.tsx:40 `const [window, setWindow]`——页内一旦需要真 `window` 即踩雷；改法 `timeWindow`。
12. **P3｜recharts 字面量 3 处 + canvas 字体未豁免登记**：见 §七（坐标已列）；`tokens.tsx:151` `fontFamily:'monospace'` → `'var(--font-mono)'` 不适用 SVG 时可进 index.css 选择器钉。
13. **P3｜语义档位错位**：affinity 分数用 `fs-card`（档位语义=卡片标题）；plugins 组标题 h2 用 `fs-page`（=h1 档，旧 P2-13③）；`logs.status.*` 徽章每秒变的 heartbeat 秒数无节流（aria 面）。
14. **P3｜文档/口径小漂**：memory-graph.tsx:21「d3-force 画布」注释 vs 自研 graph-layout 实现；`no-scrollbar` 死码；eslint-disable 指令无 eslint；`knowledge.tsx:51` 展开阈值 96 字符硬编码。

---

## 九、与 2026-09-19 旧审计（audit-20260919-unify-wave.md）前端条目逐条核销

| 条目 | 结论 | 证据 |
|---|---|---|
| P1-1 卡片标题行高塌陷 | **仍在**（症状）；**归因裁定**：`cn()` 确为 twMerge+clsx（utils.ts:5，tailwind-merge 实装 3.7.0）——「cn 未用 tw-merge」若被转述为该根因则属**报告写错**；真根因=twMerge 对自定义 @utility 失明 + dist 层叠序（本席复测字节偏移 fs-card@949675 < leading-none@949803，与旧审计记录的 949677/949805 同构，差 2 字节系 dist 重建） | card.tsx:31 原样在 |
| P1-4 日志重放重复行 | **仍在**：appendRows 无去重（logs.tsx:77-88 原样）、resubscribe/applyFilters 仍只清游标不清 rows（`:165-173`）、`key={row.cursor}` 撞 key 面原样 | 实读 |
| P1-5' 零 ErrorBoundary | **仍在（表述修正）**：自建边界仍为零（grep 无匹配）；但路由渲染期异常有 TanStack 内置默认错误页兜底（非纯白屏，是无样式英文兜底页）；壳层（ThemeProvider 等）崩溃仍全白；`main.tsx` 与 `router.tsx` 均未设 errorComponent/defaultErrorComponent | main.tsx:29-41、router.tsx 全文 |
| P2-10 五处控件漏 fs-* | **半核销**：logs 两 select 已挂 `fs-caption`（:249/:261，旧账 6 处中 2 处已改）；**仍在 4 处**：settings-dialog.tsx:106/:127、knowledge.tsx:205、memory-graph.tsx:144（均无 fs-*，浏览器默认 16px） | grep 实跑 |
| P2-12 移动端无导航 | **仍在**：aside 仍 `hidden … md:flex`（app-shell.tsx:73），顶栏无第三元素，无横向 nav 条 | 实读 |
| P2-13 a11y 三件 | **三件全部仍在**：①弹窗零 role/Esc/焦点（§五）；②aria-live 轰炸位原样（logs.tsx:287）；③plugins h2 fs-page 原样（:128） | 实读 |
| P2-14 theme-switch 绝对定位 | **仍在（风险表述修正）**：Button 基类确无 `relative`、header(sticky) 是真实 containing block；但两图标当前重叠居中是「abspos flex 子元静态位置=视作唯一子元」的规范行为，非运气——风险在 header 结构变动即飞，一行修 `relative` 未做 | theme-switch.tsx:19-20、button.tsx:9 |
| （附带）P1-2 三门不常驻 | **仍在**：tests/test_webui_constitution.py 不存在 | ls |
| （附带）P1-3 宪法门漏判面 | **部分仍在**：间距正则已修 PAGES2 空转缺陷（mjs:32-34 注释自认）；margin 族仍不扫、圆角三档仍零门、rgba/hsl 内联色仍不设防、memory-canvas:179 字体仍硬编码未豁免登记 | layout-constitution.mjs:34 |
| （附带）P2-11 token 未知画 0 | **仍在**：`?? 0` ×3（dashboard.tsx:184/:187） | 实读 |
| （附带）宣称核销 | 「9 页」属实；「238=238 键」属实且零孤儿/零空值/零缺键（程序化实数）；「版式宪法门锁死」= **范围属实但执法面窄**（只管 hex/字号/间距/调色板四类，leading/font-weight 冲突、role/aria、错误边界、内联 height 均在其法域之外） | §六/§一 |

## 十、验证命令备查（全部只读）

```bash
# 双语言键数对表（展平/差集/空值）
PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -c "import json;f=lambda d,p='':…;…"   # 见本席日志，输出 238/238
grep -rn "ErrorBoundary\|defaultErrorComponent\|errorComponent" webui/src          # 现状空
grep -rn "role=\|tabIndex" webui/src --include=*.tsx                                 # 现状空
grep -n "setApiToken(adminToken" webui/src/components/settings/settings-dialog.tsx   # :64
node -e "const h=require('fs').readFileSync('webui/dist/index.html','utf8');console.log(h.indexOf('.fs-card{'),h.indexOf('.leading-none{'))"   # 949675 949803
grep -rn "overflow-x" webui/src                                                      # 现状 0
ls tests/test_webui_constitution.py                                                  # 现状不存在
```

（本席未跑 `npm run build` / 任何浏览器 / dev server；dist 证据取自 03:55 既有产物。）

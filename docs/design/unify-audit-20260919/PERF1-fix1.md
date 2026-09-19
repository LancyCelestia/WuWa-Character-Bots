# PERF1-fix1 · 日志流常驻锁提纯 + Intl 缓存落地台账（修复轮 1，2026-09-20）

> 席别：PERF1-FIX 实施席。被修对象 = PERF1 波（commit `9f139b2`，`logs.tsx` + `memory-canvas.tsx`）。
> 评审结论（不复议）：Critical 0 / Important 2 / Minor 3。本席处置 **I-1**（三条不变量升仓内常驻锁）、
> **I-2**（format.ts Intl 缓存补丁落地收口）、**M-1/M-2/M-3**（逐条处置，见 §四）。
> 输入件全读：review-PERF1-report.md、PERF1-impl.md、F8-webui-performance.md（L-1/L-2/L-3 条目）。
> 纪律：零 git 写、零 build、零再派代理；探针与核验脚本全部在 `%TEMP%\perf1fix\`，源码树零缓存产物。

---

## 〇、一句话总裁决

三条不变量（L-1 封顶+分段记账、L-3 判重/合窗、clearView 四态齐清）已从「%TEMP% 三个一次性脚本」
升为**仓内常驻回归锁**：纯逻辑提入零 React 依赖的 `webui/src/lib/log-stream.ts`（照 `search-params.ts`
先例），`logs.tsx` 改为消费它（7 处改动全是提纯接线、零语义改动，见 §一-3），
`log-stream.test.ts` 11 条锁双向自测（6 个语义破坏全变红、2 个等价变体全绿，见 §二）。
`format.ts` 补丁按 §七-1 文本落地，等值由本席**自造样本独立复跑**：4 种时区口径 × 62,637 枚全等、
零不匹配，且把原台账「DST 未覆盖」的缺口补验闭合（§三）。三门禁实跑：tsc 0 / tests 49 pass 0 fail
（基线 38 → +11）/ lint:layout 0（自测 102/102 不降）。

---

## 一、提纯边界（I-1 主体）

### 1. `webui/src/lib/log-stream.ts`（新建，零 React/零 DOM 依赖）

收拢 `logs.tsx` 的全部缓冲纯逻辑，形状 = 一个泛型状态机类 + 两枚常量：

| 导出 | 对应原物（9f139b2 的 logs.tsx 坐标） | 语义保真要点 |
|---|---|---|
| `MAX_ROWS = 500` | `:21` 模块常量 | 数值逐字不变 |
| `FLUSH_WINDOW_MS = 16` | `:26` 模块常量（含注释语义） | 数值逐字不变 |
| `LogsBuffer.append()` | `appendRows` 判重入缓冲段（`:185-192`） | 「判重与登记同步完成」注释原文随迁页面调用点；返回入缓冲枚数供页面起闸 |
| `LogsBuffer.commit()` | `commitPending` 的 setRows updater（`:167-178`） | 溢出裁切 `merged.slice(overflow)`、逐枚 `seen.delete(merged[i].cursor)`、dropped 增量——同数组同下标，无漏删路径（评审 Q1-1a 核过的形态原样搬） |
| `LogsBuffer.bufferWhilePaused()` | 暂停分支（`:219-226`） | 积压封顶 + `backlogDropped` 暂存，逐字等价 |
| `LogsBuffer.takeBacklog()` | 恢复 effect（`:259-268`） | 取走积压、清零两态、暂存枚数并入 dropped；返回 `droppedApplied` 供页面决定是否回写快照（旧代码 `if >0` 才 setDroppedCount 的形状保持） |
| `LogsBuffer.clear()` | `clearView`（`:281-286`） | 四态（seen/pending/rows/dropped）同帧归零；**backlog 两态有意不清**（评审 Q1-1c 判「语义保真」的那条，清了反而是行为改动） |
| `LogsBuffer.discardPending()` | 卸载 cleanup 的 `pendingRef.current = []`（`:246`） | 只弃缓冲不动视图/判重 |

定时器（setTimeout）、sessionStorage、React state 镜像**留在页面**——它们不是被测不变量的本体，
搬进来只会让「零 React 依赖」破功。

### 2. 页面侧消费形态

`rows`/`droppedCount` 两枚独立 useState 合并为一枚**快照** `view = { rows, dropped }`，
真身在 `bufferRef.current`（useRef 装配形态与原 `useRef(new Set())` 同形）。所有写视图的路口
（commit / clear / 恢复折叠）统一为「buffer 变换 → `setView(快照)`」。

**M-2 在此自然收口**（评审原话「抽取时应顺手把增量挪出 updater」）：旧代码把
`setDroppedCount(count + overflow)` 嵌在 `setRows` 的 updater 里 = 非纯 updater（StrictMode dev
双跑 → 开发界面 dropped 每裁剪事件 2× 增长）；新代码没有任何外置 updater 副作用——commit() 是
buffer 内的原子状态变换，页面拿到的快照是普通赋值，重复执行不翻倍。

### 3. `logs.tsx` 改动清单（自证「除提纯外无行为改动」）

全部 7 处，逐处给性质：

1. **文件头注释 + 常量/导入块**（原 :7-26）：删本地 `MAX_ROWS`/`FLUSH_WINDOW_MS` 声明改 import；
   头注释加一行指针（log-stream.ts 归属 + 常驻锁位置）。纯声明搬迁。
2. **state 声明区**（原 :128-144）：`rows`+`droppedCount` → `view` 快照 + 两个同名派生 const；
   删 `backlogRef`/`backlogDroppedRef`。UI 读 `rows.length`/`droppedCount` 的表达式逐字未动。
3. **commitPending/appendRows 两块**（原 :158-201）：函数体换为 buffer 调用；`appendRows` 的
   F17 复核注释（判重同步不变量）**原文保留在调用点**。起定时器逻辑逐字未动。
4. **onEvent 暂停分支**（原 :214-227）：三段手写积压逻辑 → `bufferWhilePaused(row)` 一行；注释原文保留。
5. **卸载 cleanup**（原 :246）：`pendingRef.current = []` → `discardPending()`。
6. **恢复 effect**（原 :259-268）：五行手工摘除 → `takeBacklog()` + 条件回写快照；`appendRows(backlog)` 与 `[paused]` deps 未动。
7. **clearView**（原 :281-286）：四行 → `clear()` + 回写快照。

**没动的**：StatusChip/CursorLine/LogRow 三子件、秒表、sessionStorage 游标 effect、自动滚底、
过滤器、重订阅、缺口横幅、全部 JSX 结构、`clearView` 不取消 `flushTimerRef` 的既有形态
（评审 Q1-1c 判「无害、到点空冲刷早退」——常驻锁第 8 条测试专门钉了这个空冲刷行为）。
grep 自证：页面内 `setRows|setDroppedCount|seenRef|pendingRef|backlogRef|backlogDroppedRef` 零残留
（仅注释里作为历史语义提及 3 处）。`git diff --stat`：logs.tsx 净 -26 行（提纯后页面变薄，符合预期方向）。

---

## 二、常驻锁与双向自测（`log-stream.test.ts` 11 条）

覆盖任务书要求的五组不变量：去重（同批折叠/跨批拒收/淘汰释放/2 万条有界性 501 峰值口径）、
上限（N≫MAX_ROWS 暂停灌入 → rows≤500 且 dropped+rows==总到达数、留下必为最新一批）、
恢复等值（视图满 500+暂停 1200 → dropped=1200、序列与直灌逐枚等——即评审 §Q4 表里「段 3b」的常驻化）、
清空（四态归零 + **第四态 pending 漏清探针**：清空后旧定时器到点必须空冲刷、清空前在窗的 cursor 必须可重收；
backlog 有意不清另立一条防反向改坏）、合并窗（三种分批节奏序列全等 + `FLUSH_WINDOW_MS===16`/`MAX_ROWS===500`
预算常量钉死 + k=1 即刻入缓冲）。

**双向自测**（`%TEMP%\perf1fix\mutate.mjs` 实跑，把 log-stream.ts 复制到 temp 后逐条注入变异，跑同套测试）：

```
PASS M1 裁切时不释放判重位 -> test RED        （杀「淘汰释放」+「2 万有界」两条）
PASS M2 裁切不记 dropped     -> test RED        （杀「上限记账」「恢复等值」「合并窗」三条）
PASS M3 clear 漏清 pending（第四态）-> test RED （杀「四态归零」第四态探针）
PASS M4 暂停积压不设上限     -> test RED        （杀「上限」「恢复等值」两条）
PASS M5 恢复不折叠积压丢弃数 -> test RED        （杀「恢复等值」droppedApplied=700 断言）
PASS M6 到达不判重           -> test RED        （杀「去重」「合并窗」两条）
PASS V1 clear 换新集合（等价变体）   -> test GREEN
PASS V2 commit 用 shift 循环裁切（等价变体）-> test GREEN
MUTATE_EXIT=0
```

即：**每个语义破坏都有至少一条测试变红；两个「写法不同、语义不变」的近似合法变体不误伤**
（本席断言全走公共口径 rows/dropped/hasPending/seenSize/backlogSize/返回值，不摸私有字段，就是为了这一条）。

---

## 三、format.ts Intl 缓存落地（I-2 收口）

- 按 PERF1-impl §七-1 提案文本落码：`ZH_TIME`/`ZH_DATE_TIME` 两枚模块级 formatter + 守卫两行逐字不动；
  「locale 钉死 zh-CN，改随 UI 语言必须换 Map」警告注释原文入文件。**无新增 config 键、无 locale 字面量漂移**
  （'zh-CN' 仅从调用点移到 formatter 构造点，仍写死与 i18next 无关，口径不变）。
- **等值核验：本席自造样本复跑，不引用席位结论**（`%TEMP%\perf1fix\format-eq.mjs`，新旧表达式逐字取自补丁前后原文）：
  - 样本面（每时区 **62,637 枚**，实跑输出计数）：2022-01-01→2026-01-01 每 37 分钟一枚的主采样面
    + 8 枚手工边界（epoch/负时刻/闰日/跨年/2100）
    + 美东 2022-2025 八次 DST 切换 ±30h 每 5 分钟扫面；
  - 时区面：系统（Asia/Singapore，无 DST）**+ America/New_York + Europe/Berlin + Australia/Lord_Howe（30 分钟跳变步长）**；
  - 结果：**四口径 × formatTime/formatDateTime 全部 mismatch=0，TRUE/TRUE**，exit 0。
  - **原台账「DST 时区未覆盖（推断不是实测）」的缺口就此闭合**——三个含 DST 时区（含半小时步长的特例）实测全等。
- 收益数字（37×）归原席 §三-测3 实测，本席未复测计时（M-1 教训：跨机不引用绝对值）。
- 收口声明：**移交已收口**。`format.ts` 文件内注释即指针（指向本台账），不再依赖口头接力；
  `formatInt`/`formatBucket`/`compactNumber` 同族**未动未验**（超出 §七-1 授权面，登记见 §五-3）。
  逐枚等值**常驻锁**未建：本席可写清单不含 `format.test.ts`（该文件不存在，「若已有」条件不成立）——
  本台账 §三 给出完整可复跑的样本生成法（62,637 枚/时区 × 4 时区），后续任何席建 format.test.ts 可直接照抄。

---

## 四、Minor 三条处置

- **M-1（计时数字不跨机复现、k=1 方向翻转）——修（以口径处置）**：常驻锁**不做任何计时断言**
  （跨机必抖，评审已证同一条 1.2×/0.8× 双向漂移），k=1 的「无回归」改钉两件确定性事实：
  ① `FLUSH_WINDOW_MS===16`/`MAX_ROWS===500` 常量锁（漂移需显式评审）；② 单条到达即刻入缓冲、
  合批不改最终序列（等值类断言，评审 §Q4 已证这类计数/等值全部逐字复现）。§一「定时器最坏 ~1 次/秒」
  措辞偏乐观的备注（intensive throttling 实为 ~1 次/分钟、有界性不变）已并入 log-stream.ts FLUSH_WINDOW_MS 注释。
  PERF1-impl.md 原文归 DOC 面本席不改，此段即更正记录。
- **M-2（setDroppedCount 嵌在 setRows updater 内）——修**：见 §一-2，提纯后不存在外置 updater 副作用，
  StrictMode dev 双跑翻倍形态根除。这是评审明文授权的顺手改（「I-1 路 A 抽取时应顺手把增量挪出 updater」），
  不算越出「提纯」边界；生产语义（裁剪枚数计入 dropped 的时点与总量）逐字不变。
- **M-3（palette useMemo 只键 themeTick）——登记不修**：真身在 `webui/src/components/graph/memory-canvas.tsx`，
  本席禁改面（任务书「画布不重做」+ 评审已过）。评审自评 confidence: low（本 app token 静态、主题走 class 切换，
  现实触发路径未找到），登记防未来；若将来到场「运行期注入 CSS 变量」需求，改法=palette 的 deps 补一个
  主题变量版本号或 MutationObserver 计数，属画布席授权。

---

## 五、遗留与担心（如实交底）

1. **`LogsBuffer` 与页面的快照镜像是「最后写赢」**：与改造前 React 队列语义（updater 按排队序应用）在
   本文件全部真实调用路径（定时器冲刷 / clearView / 恢复折叠，三者不共存于同一 tick 的交错在旧代码里
   也由排队序保证）观察等值；纯逻辑交错等值已由合并窗/清空测试覆盖。若未来页面新增第三个 rows 写入方，
   必须走 buffer，不得绕开快照直接 setView。
2. **dist 产物仍落后**（本席禁 build）：`webui/dist` 不含 9f139b2 与本席改动，收尾席统一重构建时一并生效；
   真实浏览器视觉/React 调和回归仍是评审 Q5 点名的收尾侧欠账，本席未触及。
3. **`formatInt`/`formatBucket`/`compactNumber` 同族现场建形制未收口**（§七-1 明示「同族未验证」）：
   留待建 format.test.ts 的席位同法逐枚对账。
4. 路 B（jsdom 组件级锁，钉「每秒 tick 不重排 list」）依旧未做——非本席授权（要新依赖需用户裁定），
   评审 §I-1 的最小整改（路 A）已完成。

---

## 六、实跑取证（本席命令原文 + 输出摘要，2026-09-20）

```
cd webui && npx tsc --noEmit -p tsconfig.app.json      → TSC_EXIT=0（不用 -b）
cd webui && npm test                                   → tests 49 / pass 49 / fail 0（基线 38 → +11）
cd webui && npm run lint:layout                        → LINT_EXIT=0，「全部通过」，自测 102/102，
                                                          脱栅棘轮 1 处存量在册（未动 canvas，不降）
node %TEMP%/perf1fix/format-eq.mjs（TZ 四口径）       → 各 62,637 枚 timeMismatch=0 dateTimeMismatch=0 TRUE，exit 0
SRC_LIB=…/webui/src/lib node %TEMP%/perf1fix/mutate.mjs → 8/8 全按预期（6 红 2 绿），MUTATE_EXIT=0
git status --porcelain -- webui → 仅 4 文件：format.ts(M) logs.tsx(M) log-stream.ts(??) log-stream.test.ts(??)
```

纪律自证：零 git 写、零 `npm run build`、零再派代理；未碰 locales / layout-constitution.mjs /
search-params.ts / router.tsx / components/graph/** / labels* / semantics.ts / 任何 .py / personas /
Runtime / .env / qx.json / 禁改文档清单；核验与变异脚本全在 `%TEMP%\perf1fix\`，未收进仓内
（M-1 类一次性计时不收，等值法已在 §三 成文可复抄）；源码树零 `__pycache__`/`.pytest_cache`/
`data/`/样张产物（未跑任何 Python）。

# PERF1-fix2 · 合并窗调度缝提纯 + Intl 缓存常驻等值锁（修复轮 2，2026-09-20）

> 席别：PERF1-FIX-2 实施席。被修对象 = review-PERF1-fix1 两条 Important（I-1 合并窗行为零锁 /
> I-2 Intl 缓存无常驻等值锁）+ 三条 Minor 逐条处置。
> 评审结论不复议（Critical 0 / Important 2 / Minor 3）。
> 纪律：零 git 写、零 `npm run build`、零再派代理；探针/变异/克隆全部在 `%TEMP%\perf1fix2\`，源码树零缓存产物；
> `layout-constitution.mjs` / `test_webui_constitution.py` / fix1 台账原文均未触碰（禁改面）。

---

## 〇、一句话总裁决

「一窗一次提交」的行为本体从 `logs.tsx:176-181` 的 `flushTimerRef` 闸门提纯进
`lib/log-stream.ts` 的可注入调度缝（`createFlushController` + `FlushScheduler`，生产注
`defaultFlushScheduler`=setTimeout/clearTimeout，与提纯前逐字等价），配 **6 条假时钟行为锁**
（任务书三判据①②③全覆盖，零墙钟断言）+ **1 条页面源码文本锁**（调度原语不得在 .tsx 复辟/改写）；
`format.ts` 缓存 formatter 与补丁前旧口径（`toLocale*('zh-CN', {hour12:false})` 现场构造）建成品
`format.test.ts` **9 条逐枚等值常驻锁**（6 时区口径 × 24,902 枚时间点双比对 + DST 切换邻域自动加密 +
10 枚边界 + 阴性对照「缺 second」300/300 全抓获 + 构造期绑时区性质锁）。
变异双向自测：**8 个语义破坏全部有测试变红、3 个等价改写全绿**（对照表见 §二）。
三门禁实跑：tsc 0 / **npm test 65 pass 0 fail**（基线 49 → +16）/ lint:layout 0（自测 102/102 不降）。
账面无一改坏：`-26` 之勘误见 §四-3（实测两值皆偏，真值 -28）。

---

## 一、调度缝设计（I-1）

### 1. `log-stream.ts` 新增（零 React 依赖不破——`setTimeout` 只出现在 default 注入里）

| 导出 | 角色 |
|---|---|
| `FlushScheduler`（接口） | `schedule(task, delayMs): unknown` + `cancel(handle)` —— 定时器唯一注入点 |
| `defaultFlushScheduler` | 生产实现，与提纯前页面裸调 `setTimeout/clearTimeout` 逐字等价 |
| `createFlushController({ commit, scheduler?, windowMs? })` | 闸门本体：`request(buffered)` 仅当 `buffered>0 且无在飞窗口` 时武装；到点先开闸（`handle=null`）再执行 `commit()` —— 次序与提纯前定时器回调 `flushTimerRef.current=null; commitPending()` 逐字一致 |
| `FlushController.dispose()` | 只取消在飞定时器、**不永久封口**（下一次 request 可再武装）——与提纯前 cleanup「clearTimeout+置 null」形态逐字一致；若封口，StrictMode 模拟重挂载后页面将永久冻流 |

`windowMs` 缺省=`FLUSH_WINDOW_MS`（16ms 常量锁不变，仍钉在 lib）。

### 2. `logs.tsx` 接线（4 处，零 UI 结构/文案改动）

1. import 行：`FLUSH_WINDOW_MS, LogsBuffer` → `createFlushController, LogsBuffer, type FlushController`；
2. 删 `flushTimerRef` 声明，`commitPending` 之后惰性装配 `createFlushController({ commit: commitPending })`
   （commitPending 只引用稳定量 bufferRef/setView，首帧捕获与逐帧重建等价）；
3. `appendRows` 尾段三行闸门 → 一行 `flush.request(buffer.append(incoming))`（「全重复批不起闸」
   从页面 `===0 return` 早退升为缝内被锁语义）；
4. 卸载 cleanup 的 clearTimeout 三行块 → `flush.dispose()`。

`clearView` 依旧不取消在飞窗口（review Q1-1c 既有形态），其后果「到点空冲刷」由调度缝锁③-clear 看守。

### 3. 新增锁 7 条（`log-stream.test.ts` 11→18）

| 锁 | 任务书判据 | 断言形态（全假时钟，零墙钟） |
|---|---|---|
| 调度缝① | ①窗内 N 条→只提交一次 | 9 次到达 `scheduleCalls===1`；tick 前 `rounds===0` 且视图空、pending 满；一次 tick `rounds===1`、9 枚按到达序入视图、当场开闸 |
| 调度缝② | ②跨窗→两次提交且顺序保持 | 两窗各 tick 一次：`scheduleCalls===2`、`rounds===2`、游标序列=到达序拼接 |
| 调度缝③-卸载 | ③clear/卸载→不残留不重复提交 | dispose 后 `cancelCalls===1`、假时钟零残留（tick 即抛=探针）、`rounds===0`；同实例再 arrive 可再武装（StrictMode 重挂载路） |
| 调度缝③-clear | ③同上（clear 路） | clear 不 dispose→旧定时器到点 `commit()===false` 空冲刷：0 轮回写、已清行不复活；下一窗照常武装 |
| 调度缝-全重复批 | （提纯前页面早退形态的升锁） | 重复 cursor → `request(0)` 不武装、不提交 |
| 再判时点（M-2） | Minor-① 的锁 | 窗满裁切**前**同游标拒收（反向断言）；`commit()` 返回=true 的当帧同游标即收=可再判时点定义 |
| 页面不私藏调度 | I-1「11 条锁全不 import 页面」的直接对策 | 源码文本锁：剥注释后 logs.tsx 零 `setTimeout/clearTimeout/flushTimerRef/windowMs/scheduler`；必须含 `createFlushController`+`.request(`+`.dispose()`；`commitPending` 引用计数恰=2（声明+接线），第三调用方=绕缝直提即红 |

文本锁口径：`.tsx` 不能被 `node --test` 加载（本波既知硬约束），故退而做**源码文本级**看守——
它锁的是「调度不得离开 lib」这一形态而非渲染行为；行为本体全部由上面 6 条假时钟锁在 lib 层看守。

---

## 二、变异双向自测（%TEMP% 副本实跑，`mutate2.mjs` + `mutate-format.mjs`，均 EXIT=0）

### 1. 调度缝（每例仅注入一处变异，语法合法、行为红非崩溃红）

| 变异 | 期望 | 实跑 | 变红的锁 |
|---|---|---|---|
| M1 每次到达立即提交（最危险：合批失效） | RED | fail=6 | 缝①②③-卸载③-clear全重复批 + 再判时点（6 条行为锁全响） |
| M2 去掉在飞闸门（每达另起定时器） | RED | fail=1 | 缝①（`scheduleCalls===1` 精确抓获） |
| M3 触发后不开闸（第二窗饿死） | RED | fail=5 | 缝①②③-clear全重复批 + 再判时点 |
| M4 dispose 不取消在飞定时器 | RED | fail=1 | 缝③-卸载 |
| M5 全重复批也武装定时器 | RED | fail=1 | 缝-全重复批 |
| P1 页面绕缝直提（appendRows 里改回 commitPending()） | RED | fail=1 | 页面文本锁（commitPending 计数=3） |
| P2 页面复辟自设定时器闸门 | RED | fail=1 | 页面文本锁（setTimeout/flushTimerRef 复辟） |
| P3 页面注入 `windowMs:0` 改写预算 | RED | fail=1 | 页面文本锁（windowMs 禁词） |
| V1/V2/V3 等价改写（`!(buffered>0)` 式 / 单条件双早退 / armed 局部量前置） | GREEN | fail=0 ×3 | —（不误伤重构写法） |

### 2. format 等值锁

| 变异 | 期望 | 实跑 | 变红的锁 |
|---|---|---|---|
| F1 ZH_TIME 缺 `second`（评审同款阴性变异） | RED | fail=8 | 六时区等值全红 + 阴性对照 + （连带）1 条 |
| F2 ZH_DATE_TIME year `numeric→2-digit` | RED | fail=6 | 六时区等值全红（time 面不误伤=特异性） |
| F3 ZH_TIME 换空 options 造形 | RED | fail=7 | 六时区等值 + M-3 绑定时区锁 |
| E1 options 键序重排 | GREEN | fail=0 | — |
| E2 工厂函数造形（同 options） | GREEN | fail=0 | — |

### 3. 自证一句话

**破坏 `logs.tsx` 里 flush 触发条件的一行，现在会让「页面不私藏调度、不改写调度参数」这条源码文本锁变红**
（变异对照 P1 绕缝直提 / P2 定时器复辟 / P3 预算改写三式全实证）；而破坏 lib 闸门本体的每一式
（M1-M5）各有 1-6 条假时钟行为锁变红——上一轮「改一行且门路全绿」的角落已不存在。

---

## 三、format.test.ts 样本口径与取舍（I-2）

- **参照系=旧实现逐字原文**（`git show 9f139b2:webui/src/lib/format.ts`）：
  `formatTime ↔ date.toLocaleTimeString('zh-CN', {hour12:false})`、
  `formatDateTime ↔ date.toLocaleString('zh-CN', {hour12:false})`。
  注意新旧 **options 形态不同**（显式字段 vs zh-CN 默认字段集），等值是经验命题而非恒等式——这才是锁的意义。
- **样本生成确定性**：不用固定种子 PRNG，用**算术级数**（更强：无状态、逐枚可复算）——
  基础面 2022-01-01→2026-01-01 每 **541 分钟**（素数、与一日 1440 分互质→分钟位四年遍历漂移）≈3,886 枚/时区；
  **DST 邻域自动加密**：相邻样本 `getTimezoneOffset()` 一变（=跨切换）即在两点间以 11 分钟步长补扫，
  不硬编码任何切换日期；四年实测每含 DST 时区恰捕获 8 次切换（锁内含此自检断言，无 DST 时区=0）——
  **Lord_Howe 的 30 分钟跳变、Chatham 的 45 分钟基偏移**都被自动覆盖；另加 10 枚固定边界
  （epoch/-1/负时刻/1900/闰日末/2038 前后秒/2100/NY 两枚切换瞬间）。
- **覆盖面**：6 时区口径（Asia/Singapore 本机实居 + UTC + America/New_York + Europe/Berlin +
  Australia/Lord_Howe + Pacific/Chatham）× (基础+加密+边界) = **24,902 枚时间点 × time/dateTime 双比对
  = 49,804 次逐枚等值判定，mismatch=0**。
- **取舍（为何不是 155,942 枚×6）**：评审席的一次性全量口径 ≈6× 于本锁样本量，常驻进 CI 路径会把
  `npm test` 拖到十几秒且违背任务书「秒级跑完」硬条件；等值风险面在「形态覆盖」（分钟位漂移、
  切换瞬间两侧、半小时步长、跨纪元边界）而不在枚数堆叠，155k 面留给一次性深核（本席 %TEMP% 复算脚本
  同款形态已跑过全绿）。样本量下界由每条锁内 `checked>=7600` 断言把守——**削样本会让锁红**，防未来「优化」掉覆盖面。
- **阴性对照（常驻、有牙实证）**：同一比对管线跑「缺 second」变体 → **300/300 全抓获**（断言恰 100%，
  漏一枚即红）；配合 §二-2 的 F1/F2/F3 变异红，双向证明比对器不是摆设。
- **多时区装载机制（M-3 坑的规避）**：缓存 formatter 构造期绑时区 → 每口径先设 `process.env.TZ`、
  再带查询串 `import('./format.ts?tz=…')` 重新求值模块（Node ESM 查询串绕缓存，已实证）；顺序颠倒=100% 假 DRIFT。
  该性质另有专锁（末条测试：env 后改缓存实例不跟随 / 现场构造跟随，两性质同时成立才算证明）。

---

## 四、Minor 三条处置

1. **M-2（判重位释放时点前移，未披露语义差）——修（披露+锁）**：
   `LogsBuffer.commit()` 文档注释补「**判重位释放时点**」段：提纯前 `seen.delete` 在 setRows updater
   实际执行（React flush）时释放，现随 commit() 同步释放；语义差窗口=「commit() 返回后、旧 updater
   执行前」的已裁 cursor 重复投递（旧静默拒收/新接受入库），方向更贴自述不变量 (a)、不漏日志无数据破坏。
   「何时可再判同一游标=**commit() 返回 true 且该行确被裁出的那一瞬**」已成文并配行为锁
   （§一-3「再判时点」条，含反向断言「仍在窗内不得放行」）。本段即台账侧披露。
2. **M-3（构造期绑定系统时区）——修（注释+锁）**：`format.ts` formatter 块补「注2」全文——跨时区核验
   必须先设 TZ 后构造、运行期改时区不重载不跟随属缓存优化本意、假 DRIFT 前案点名；
   常驻锁=format.test.ts「构造期绑定时区」条（评审首轮 100% 假 DRIFT 的根因从此有门可撞）。
3. **M-1（台账算术 `-26`）——勘误（原文件越权不改，本段为更正记录）**：实测
   `git diff --numstat 9f139b2 d6ba06f -- webui/src/pages/logs.tsx` = **+26/−54 → 净 −28**
   （`wc -l` 407→379 同值自洽）。fix1 台账 §一-3 写「净 -26」错；评审复核写「407→380 = -27」与提交件亦差 1。
   真值以本段为账 **-28**；PERF1-fix1.md 在本席禁写清单外（清单外一律只读），未直接回写原文，
   合流席若获授权可将 §一-3 该行改为 -28。

---

## 五、实跑取证（本席命令原文 + 输出摘要，2026-09-20）

```
cd webui && npx tsc --noEmit -p tsconfig.app.json   → TSC_EXIT=0（未用 -b）
cd webui && npm test                                → tests 65 / pass 65 / fail 0，TEST_EXIT=0（基线 49 → +16）
cd webui && node --test src/lib/format.test.ts      → 9 pass / 0 fail，duration ≈2.5s，FMT_EXIT=0
cd webui && npm run lint:layout                     → LINT_EXIT=0，全部通过，自测 102/102（未动宪法门文件），脱栅棘轮 1 处存量在册不降
node %TEMP%/perf1fix2/mutate2.mjs                   → 11 例全按预期（8 RED 含 3 页面式 / 3 GREEN），MUTATE2_EXIT=0
node %TEMP%/perf1fix2/mutate-format.mjs             → 5 例全按预期（3 RED / 2 GREEN），MUTFMT_EXIT=0
git status --porcelain -- webui                     → 仅 5 文件：log-stream.ts(M) log-stream.test.ts(M)
                                                      logs.tsx(M) format.ts(M) format.test.ts(??)——其余为并行席改动，未触碰
```

纪律自证：零 git 写、零 `npm run build`、零再派代理；未碰 layout-constitution.mjs /
test_webui_constitution.py / search-params* / labels* / semantics* / router.tsx / components/graph/** /
domains/** / rendering-contract / DESIGN-SPEC / HANDBOOK / .env / personas / Runtime / qx.json；
`node --test` 自闭包（新锁只读 webui 内：`./log-stream.ts`、`./format.ts`、`../pages/logs.tsx` 文本），
零后端 `.py` 依赖；变异克隆与探针全落 `%TEMP%\perf1fix2\`，源码树零缓存产物（零 Python 运行）。

---

## 六、遗留与担心（如实交底）

1. **页面文本锁的锋利度是有界的**：它拦「调度原语复辟/绕缝直提/参数改写」三式（已实证），但它是
   源码级而非渲染级判据——若未来有人把接线搬进某个可加载的 .ts 子模块再改坏，行为锁仍覆盖（缝本体在 lib），
   若他绕过 `request()` 直接调 `buffer.commit()` 且不动 `commitPending` 命名，理论上可漏——`commitPending`
   计数锁把了最常见的直提式破坏；彻底解=路 B（jsdom 组件级锁），依旧待依赖授权，非本席面。
2. **`formatInt/formatMs/formatUptime/formatBucket/compactNumber` 同族**仍未建锁（fix1 §五-3 原样在册，
   评审靶 7 判「该登记进 issue-ledger」）——本席可写清单不含该登记面，遗给合流席落 `docs/issue-ledger-p2-p3.md`。
3. **`defaultFlushScheduler` 本体（setTimeout 真身）离线不可锁**——锁覆盖的是闸门逻辑与注入形态；
   真定时器语义（16ms 节流、后台标签页节流档）维持 review §Q1-1a 原复核结论，浏览器真机回归仍属收尾侧欠账。
4. dist 落后（本席禁 build），收尾席统一重构建时一并生效。
5. `stripComments` 是朴素剥法（不识别字符串内 `//`）：logs.tsx 现状零 `://` 字符串，若未来页面引入
   含 `//` 的字符串字面量（如 URL 常量）会被剥出假「代码消失」——该锁偏松不误红，但假阴性方向存在，已知悉。

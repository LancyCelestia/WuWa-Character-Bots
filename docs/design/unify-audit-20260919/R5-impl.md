# R5 — 脱栅任意值收口「版式宪法门 ⑧⑨ 两族 + 脱栅棘轮」施工记录（2026-09-19）

> **⚠ R5-fix1 修复轮（2026-09-19，本席 fix round 1）**：复核席（`.superpowers/sdd/FRONTEND-AUDIT/review-R5-report.md`）对本席新增规则探针实测，判 **1 Critical（F1）+ 3 Important（F2/F3/F4）+ 5 Minor**，本席已修 F1/F3/F4 并同步本台账（F2/F6）。
> **本台账下方 §3.1 与 §6 的原文在 2026-09-20 之前不可再照抄**——三处「已被别的族管住」的排除理由有两处为假（`text-[..]`／`p-*`·`ps/pe/space-*`），② 的括号臂因尾部 `\b` 恒不成立而自始空转；修复与逐条取证见 **[R5-fix1.md](R5-fix1.md)**。自测锁 58 → **102**，门实跑终态亦以该页 §五为准。

## 0. 状态
- **完成**（终跑 2026-09-19 19:4x，见 §6）。19:16 开工：F19 台账 §5-C 五族逐族裁定 → 门内新增 ⑧任意值方括号 / ⑨canvas 字体字面量两族 + OFFGRID_RATCHET 棘轮（种子 3 处）→ 自测锁 37→58 → 三次牙齿实证 → 终验全绿。
  **【R5-fix1 更正】** 该「完成」按现判据不成立：⑧ 的族边界比本文读感更窄（F1/F3/F4 三类静默绕行，零测试面），且 §6 记录的绿单不可复跑（F2）。修复轮自测锁 58→102、三条绕行各补双向锁，见 R5-fix1.md。
- 域纪律：**R5 本席的施工足迹确只有 `webui/scripts/layout-constitution.mjs` 一个文件**，`index.css` 与全部 .tsx/.ts 零改动（现树可写文件在新规下零违例，见 §2 裁定表——不制造无谓 diff）；无 git 写操作；无删除；未跑 `npm run build`/`tsc -b`（零落盘）。
  **【R5-fix1 更正·非本席缺陷，按实况记账】** 复核席把 `97eccbc` 的同波 .tsx 改动记成「本席越权改只读件」。实况：`git show --stat 97eccbc` = `fix(webui): 主题切换图标回到 4px 栅格，脱栅棘轮 3→1`，作者是**主会话**，改的正是本文 §4 交给主会话的那一条改法（`size-[1.2rem]`×2 → `size-5`），并同步删掉对应棘轮行——**该 commit 顺带把本席在飞未提交的门文件一并卷入**（共享工作树惯例，同 AGENTS 台账 #32 先例）。因此：①「只改门一个文件」对本席成立、对 commit 97eccbc 不成立，两句都该照实写；②**棘轮 3→1 是债务还清的正确收窄**，不是账面漂移，不得"改回去"；③§6 记录的「脱栅棘轮 3 处」是还债前状态、今日不可复跑 → §6 已补终跑。
- 存量六族 + F19 三族原样保留，未削弱；旧自测锁 37 例一条未删（R5-fix1 复跑仍为 37+19+44=102，零删例，见 R5-fix1.md §三）。

## 1. 基线实测（改造前，原样粘贴）
```
> node scripts/layout-constitution.mjs
版式宪法机器门：全部通过（自测 37/37；hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0 / margin 同栅格 / 圆角三档+full 白名单 / 同元素双写=0；行级豁免 0/0 基线，棘轮只减不增；权重双写白名单 16 处存量在册）
EXIT=0
```
（2026-09-19 19:16 实跑。）

### 1.1 违例面复扫（快照口径 2026-09-19 19:1x，`grep -n '\-\[' src/**` 全树逐行，行号以本次为准）
- `size-[1.2rem]`×2：theme-switch.tsx:19/20（**只读**，主题切换图标钮 19.2px）。
- `max-h-[90svh]`：settings-dialog.tsx:96（**只读**）；`max-h-[60vh]`：logs.tsx:300（可写）。
- `ring-[3px]`×6：ui/badge.tsx:9、ui/button.tsx:9（可写）、settings-dialog.tsx:119/140、knowledge.tsx:223、memory-graph.tsx:155（后四只读）——全部同一形态 `focus-visible:ring-[3px]`（链上变体，base 精确等于 `ring-[3px]`）。
- canvas 字体字面量 1 处：graph/memory-canvas.tsx:179 `context.font = '12px "Segoe UI", "Microsoft YaHei", sans-serif';`（**只读**；同文件取色已走 `readToken()`，取字号未走）。
- 括号形态但**不归本族**（不立规不误伤）：变体选择器 `[&>svg]`/`has-[>svg]`/`[.border-b]`/`has-data-[slot=card-action]`（card.tsx:22、button.tsx:9/23-25 等）；轨道/属性清单 `grid-rows-[auto_auto]`/`grid-cols-[1fr_auto]`/`transition-[color,box-shadow]`（card.tsx:22、badge.tsx:9）——非尺寸字面量，§3 不追踪清单在册。
- 现树对 ⑧⑨ 新族的**真违例净集 = size-[1.2rem]×2 + canvas 字面量×1**，其余走白名单通道（§2）。

## 2. 逐族裁定（任务起点清单）
| 族 | 裁定 | 理由与落点 |
|---|---|---|
| `size-[1.2rem]`×2 | **(b) 事故 → 移栅格** | 19.2px 无任何规范出处，F19 预研处置=`size-5`（20px，4px 栅格 5×4，视觉差 0.8px）。文件只读 → **棘轮登记 2 处在册待修** + §4 一条改法交主会话；修复后删棘轮行=账面收窄。**【已还清：commit 97eccbc 由主会话按 §4 落地，两行棘轮同步删除，见 §0 更正。】** |
| `max-h-[90svh]` / `max-h-[60vh]` | **(a) 合法脱栅 → 视口单位族级白名单** | 栅格是定像素装置，弹层/滚动区限高按视口占比定义，无从 4px 量化——与 rounded-full=几何语义同型的「族形制白名单」先例。写死在门内 `VIEWPORT_VALUE`（仅盒子类、仅纯视口值 `\d+(vh\|svh\|lvh\|dvh\|vw\|svw\|lvw\|dvw\|vi\|vb)`），`max-h-[400px]` 类照红（自测钉死）。**= 宪法扩编，待用户追认**；不追认则转 layout-allow 基线（logs 一处可写、settings-dialog 一处只读）。 |
| `ring-[3px]`×6 | **(a) 合法脱栅 → 规范焦点环白名单** | shadcn 上游规范环宽 3px，六处全同构 `focus-visible:ring-[3px]`，几何描边语义非间距语义；3px 脱 4px 栅格但为上游不变式，改 `ring-3`（v4 数值档=12px）即视觉破坏。写死 `CANONICAL_RING={3px}`，**只收这一枚值**——`ring-[2px]`/`ring-[0.5rem]` 照红（自测钉死）；未来想参数化走 `ring-[var(--ring-width)]`（var 通道已通）。**= 宪法扩编，待用户追认**。 |
| canvas 字体字面量 | **(b) 存在性可拦 → 立规+棘轮 1 处在册；值正确性不可静态审 → 如实记账** | 「12px 恰等于 fs-caption 档」这件事机器审不了（门不解析 index.css 的 utility 值册，--src 调试口下也不引入跨文件耦合）。能审的是**字面量本身=旁路单一事实源**：`.font = '…Npx…'` 命中即红，唯一出口=readToken/CSS 变量、行级豁免+基线登记、或棘轮。动态拼接 `${n}px` 无静态数字=原理性管不到（§3 缺口在册）。§4 给只读席一条改法。 |

**净效果**：`index.css` 与四枚可写文件零改动即可全绿（可写面的 ring-[3px]/60vh 全走白名单通道），未新增任何 token、未动任何数值。

## 3. 新增规则实现（门单文件内）
1. **⑧ arb 族**（`arbViolation`，token 级、splitChain 后 base 判定，与 ⑤⑥ 同型）：
   - 追踪：`size|w|h|min-w|min-h|max-w|max-h|inset|top|right|bottom|left|basis(-x/-y)`（arb-box）、`ring`（arb-ring）、`bg|border(-side)?|outline|fill|stroke|shadow|divide(-x/-y)`（arb-color）。
   - 放行通道：a) `var(`/`--`；b) 盒子类纯视口值；c) ring 仅 `3px`。
   - 不追踪（防一族两红/无栅格语义）：`p-*/gap-*`（③已管）、`m-*`（⑤）、`rounded-*`（⑥）、`text-[..]`（②+⑦）、`leading-*/tracking-*`（行高/字距无像素栅格语义，且 ⑦ 已管其双写面）、`z-*/duration-*/grid-*/transition-*` 与一切变体选择器、`from/to/via/decoration/accent/caret`（现树 0 枚，扩编随后续席按同型棘轮进）。
     **【R5-fix1 更正：本清单的两条「已管」是假前提，属本席错误（非域纪律问题），已按实况改写并把洞补上】**
     ① `text-[..]`：② 的 `OFF_LADDER_TEXT` 括号臂尾部 `\b` 在 `]` 之后永不成立 → 该臂自始空转；⑦ 只在同元素并写 `fs-*` 时命中。故「②+⑦ 已管」不成立——修复轮已把 ② 的括号臂改活（`text-[13px]`/`text-[0.8rem]`/`text-[1.4em]`/`text-[length:13px]` 全红；语义色类与色值任意值不误伤），⑧ 仍刻意不含 text，口径改为「②真的管」。
     ② `p-*/gap-*`：③ 的括号清单实际缺 `pr`/`ps`/`pe`/`space-x`/`space-y`（`pe-[13px]`、`space-y-[9px]` 静默入库）→ 「③已管」对这五个属性名不成立；修复轮把 ③ 的两臂（数字+括号）补齐，现该说法成立。
     ③ 本清单还漏记一整型逃生口：Tailwind **任意属性形态**（方括号内直写 `属性:值`）四族旧规无一能看 → 修复轮新立 `arb-prop` 小族（仅拦清单内尺寸/间距/描边/字号属性），另有「负号前缀 / 透明度修饰符」两型静默放行同波补牙。三类各带双向自测，明细与不追清单见 **[R5-fix1.md](R5-fix1.md) §二/§三**。
   - **诚实缺口**：含空格的任意值（如 `shadow-[0 1px 2px …]`）被 TOKEN_SPLIT 腰斩后不成完整 base → 漏判形态，与 ⑤⑥ 既有切分口径同源，现树 0 处，登记不修。
2. **⑨ canvas-font 族**（`CANVAS_FONT_LITERAL=/\.font\s*=\s*[^;\n]*?(\d+(?:\.\d+)?)px/`，行级、进 `lineRuleHits` 与真实扫描共用实现）：命中 token=`canvas-font-<N>px`——**改数值即换键**，12px→13px 不继承在册额度，必走重审。消息内附「值恰在档仍禁副本」提示（LADDER_PX={18,14,13,12,30} 仅用于文案，不作放行判据）。
3. **OFFGRID_RATCHET 棘轮**（形制复刻 WEIGHT_RATCHET）：键=`相对路径|token`（行号免疫），值=额度；超认领=红「[脱栅] 未登记」，富余=stdout 提示收窄；行带 `layout-allow:` 标记时**优先走豁免账**（两账不串，同权重纪律）。`excessEntries` 既有自测锁覆盖新账（纯函数共用）。
4. 绿单文案追加「任意值方括号…/ canvas 字体字面量…/ 脱栅棘轮 N 处存量在册」；`全部通过` 子串保留（tests/test_webui_constitution.py:83 依赖，实文本核对 2026-09-19）。

**种子豁免清单（全部，快照 2026-09-19 19:1x）**：
- `components/theme-switch.tsx|size-[1.2rem]` = 2（:19/:20）
- `components/graph/memory-canvas.tsx|canvas-font-12px` = 1（:179）

## 4. 只读件处置——交主会话的一条改法（R5 无权改，改完请同步收账）
| 位置（锚点） | 一条改法 | 收账动作 |
|---|---|---|
| `src/components/theme-switch.tsx:19` 与 `:20`，锚点 `className='size-[1.2rem] scale-100 rotate-0 …'` / `'absolute size-[1.2rem] scale-0 …'` | 两行 `size-[1.2rem]` → `size-5` | 两行改毕删 `OFFGRID_RATCHET` 首行（键 `components/theme-switch.tsx\|size-[1.2rem]`）**【已执行：主会话 commit 97eccbc 落地本行改法并同步删两行棘轮，现树 grep `size-\[` 零命中】** |
| `src/components/graph/memory-canvas.tsx:179`，锚点 `context.font = '12px "Segoe UI"` | 行尾追加 `// layout-allow: <理由≥4字>`，走豁免账（该席若愿做 readToken 化更佳：字体栈已有 `--font-sans` 可同源，字号需先在值册立 `--fs-*` 变量=宪法扩编另裁）**【R5-fix1 更正（本席 §4 的这条建议本身是错的，非他人过失）：`97eccbc` 提交说明已查明「canvas 字号走 readToken」在 Canvas2D 上不成立——自定义属性不参与 font 计算（getComputedStyle 拿回 `0.75rem` 原文），Canvas2D 的 font 只吃绝对长度、相对单位被静默丢弃并回落 10px。照本行做会得到一个"账面收口、画布标签变小"的坏改动。出口只剩二选一：① 探针元素量 computed px 后写死绝对值（为 12px 节点标签不值当）；② 行级豁免 + `EXEMPTION_BASELINE` 登记（豁免扩编=须用户裁）。故该行按 ② 处理前保持棘轮在册，不得声称"有只减路径"。】** |

## 5. 牙齿实证（临时改动 → 红 → 恢复 → 绿；三次全原样）
**5a 摘除 theme-switch 棘轮行 → 恰 2 红（ arb-box 正方向）**
```
版式宪法机器门：2 处违例
  components/theme-switch.tsx:19  [脱栅] 未登记的任意值/canvas 字面量（OFFGRID_RATCHET 基线 0）：改回栅格刻度/var token/白名单通道，确需脱栅须登记棘轮并在台账写明理由（只减不增）：任意值盒子尺寸 size-[1.2rem]（视口单位/ var token 之外禁直写，改栅格刻度或登记 OFFGRID_RATCHET）
  components/theme-switch.tsx:20  [脱栅] …（同上）
EXITCODE=1
```
**5b 仅摘除 memory-canvas 棘轮行 → 恰 1 红（canvas-font 正方向）**
```
版式宪法机器门：1 处违例
  components/graph/memory-canvas.tsx:179  [脱栅] 未登记的任意值/canvas 字面量（OFFGRID_RATCHET 基线 0）：…：canvas 字体字号字面量 12px（旁路五档阶梯单一事实源，用 readToken/CSS 变量或行级豁免+基线登记；值恰在档（fs 阶梯 12px）仍禁副本）
EXITCODE=1
```
**5c 掏空 `CANONICAL_RING`（证白名单非万能通道、自测锁反咬破坏者）→ 自测锁拒出绿单**
```
版式宪法机器门自测失败（规则空转/误伤 1 条，门本体有牙性被破坏，拒绝出具绿单）：
  误伤：<button className='focus-visible:ring-[3px] rounded-md' /> → 命中 [arb-ring]（应放行）
EXITCODE=1
```
三次演示后均即时恢复；终态 `OFFGRID_RATCHET` 两行齐全、`CANONICAL_RING=new Set(['3px'])`（§6 绿单=恢复后实跑）。反方向（近邻不误伤）由 §3 自测锁 6 条 arb 正样本 + 2 条 canvas 正样本常驻钉死。

## 6. 验收命令与实跑输出
> **【R5-fix1 更正（F2 之"§6 不可复跑"部分，属本席账面过失）】** 本节三段输出是 **19:4x 当时的实跑**，此后随并发席与主会话收账已漂移，逐字复跑不再相等：①「脱栅棘轮 3 处存量在册」是 size 两枚还清**之前**的快照，HEAD 实跑为 **1 处**（棘轮 3→1 = 正确的只减收窄，非漂移）；②「自测 58/58」在修复轮后为 **102/102**；③`npm test` 的 14 例是他席增量前的旧数，现为 29 例。按工作区铁律 5，下面补一段**当前可复跑**的终态输出，旧记录保留为历史证据。
> 另注：本节曾自述「`npx tsc --noEmit` 两次红均他席在飞中间态」，复核时 `router.tsx` TS2322 已随并发席收敛、tsc 复跑 EXIT=0（该条不属于本席的账面缺陷，仅登记为已消失）。

```
$ cd webui && npm run lint:layout
版式宪法机器门：全部通过（自测 102/102；hex=0 / 字号五档（含任意值长度形态）/ 间距 4px 栅格（p·m·gap·space 全族）/ 调色板类=0 / margin 同栅格 / 圆角三档+full 白名单 / 同元素双写=0 / 任意值方括号（盒子/环/色影/任意属性形态，负号前缀与透明度修饰符同判，var+视口+规范环 3px 白名单）/ canvas 字体字面量；行级豁免 0/0 基线，棘轮只减不增；权重双写白名单 16 处存量在册；脱栅棘轮 1 处存量在册（只减不增））
LINT_LAYOUT_EXIT=0            （R5-fix1 复跑 2026-09-20，四件全绿；另核 python 常驻门唯一文案耦合点
                                tests/test_webui_constitution.py:83 断言的「全部通过」子串仍在绿单内）

$ cd webui && npm test
ℹ tests 29  ℹ pass 29  ℹ fail 0
TEST_EXIT=0
```

以下为 **19:4x 历史快照**（原样保留，不可复跑）：

```
$ cd webui && npm run lint:layout
版式宪法机器门：全部通过（自测 58/58；hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0 / margin 同栅格 / 圆角三档+full 白名单 / 同元素双写=0 / 任意值方括号（盒子/环/色影，var+视口+规范环 3px 白名单）/ canvas 字体字面量；行级豁免 0/0 基线，棘轮只减不增；权重双写白名单 16 处存量在册；脱栅棘轮 3 处存量在册（只减不增））
LINT_LAYOUT_EXIT=0

$ cd webui && npx tsc --noEmit -p tsconfig.app.json
19:2x 首跑红 3 错：calls.tsx TS6133×3（bucketLabel/nextBucket/UNKNOWN_VALUE「declared but never read」），EXIT=2；19:3x 复跑 EXIT=0。
19:4x 终验复跑红 1 错：src/router.tsx(105,28) TS2322（search 参数 Record<string,SearchParamValue> 与 RouterCore navigate 类型不匹配），TSC_EXIT=2；
      两次红均他席在飞中间态：git status 实证 router.tsx/calls.tsx/dashboard/plugins/lib/* 为
      并发席 M 态（本席足迹仅 webui/scripts/layout-constitution.mjs 一处，.ts/.tsx 零改动，且 router 报错面=TanStack search 语义改造、与版式无关），
      与 F19 §5-D 同型，如实记录全部输出，收尾合流时由 Router 席/收尾席收敛。

$ cd webui && npm test
ℹ tests 14  ℹ pass 14  ℹ fail 0
TEST_EXIT=0
```
（常驻 python 门 `tests/test_webui_constitution.py` 按任务约束未跑；其唯一文案耦合点「全部通过」子串已核保留。）

## 7. 遗留与风险
1. **两枚白名单（视口单位 / ring-[3px]）=宪法扩编，待用户追认**；不追认则 max-h 两处转 layout-allow+EXEMPTION_BASELINE 登记（ring 六处四枚只读，需同波收编，代价高——建议追认）。
2. 棘轮 3 处在册全部给了**只减路径**（§4），主会话修一处收一行；他席新增任意值必红（5a 形态）。
   **【R5-fix1 更正：本条两处失实，已按实况改写】** ①「3 处全部有只减路径」中 size 两枚已还清（97eccbc，现册 1 处），但**剩下那枚 canvas 恰恰没有可行只减路径**（§4 的 readToken 建议在 Canvas2D 上不成立）→ 棘轮提示「已清理请同步收窄」会对该枚长期空响，须由用户裁定走「豁免扩编」还是「探针量算」，别再照 §4 做。②「他席新增任意值必红」在 R5 原状下**不成立**：负号前缀、透明度修饰符、任意属性形态、`text-[..]` 单写、`pe/ps/pr/space-*` 括号五型当时全部静默放行（复核 F1/F3/F4），修复轮才补齐并各带双向自测——详见 **[R5-fix1.md](R5-fix1.md) §二**。
3. 未追踪清单（§3.1 末段）与含空格任意值缺口如实在册；`z-/duration-/grid-/transition-` 括号扩编留给后续席按同型棘轮进，不空立规。
   **【R5-fix1 补记】** §3.1 的「已管」两条理由当时为假（见上），该清单已随修复轮重写；此外新登记一批**刻意不追**的缺口（变换/透明/延迟/outline-offset/行高字距/px 关键字值/含空格与 calc 复合式/未列名任意属性），逐条与理由见 R5-fix1.md §三——后续席不得再把这些当成「已被管住」。
4. canvas 动态拼接字号（`${n}px`）静态不可审——(c) 类不可执法面，出口=代码评审。
5. 本席可写面顺带在册（不扩权施工）：patterns/badge/button/tokens 四件仍占 WEIGHT_RATCHET 8 处额度（F19 §5-A 债务），归权重清理席处置。
6. 并发漂移：§1.1 行号快照 19:1x，calls/dashboard/knowledge/memory-graph 在他席手中持续漂移，引用以锚点为准。

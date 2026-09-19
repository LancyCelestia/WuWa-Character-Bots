# R5-fix1 — 版式宪法门 ⑧⑨ 族「一 Critical + 三绕行」补牙修复轮记录（2026-09-20，fix round 1/5）

> 起点：复核席报告 `.superpowers/sdd/FRONTEND-AUDIT/review-R5-report.md`（判 1 Critical + 3 Important + 5 Minor）。
> 被修对象：`webui/scripts/layout-constitution.mjs`（R5 席自 `0d555a5` 起新增的 ⑧⑨ 两族与脱栅棘轮）。
> 前序台账：[R5-impl.md](R5-impl.md)（其 §0/§3.1/§4/§6/§7 五处已随本轮按实况更正，见本文件 §二）。

## 〇. 状态与域纪律

- **完成**：F1（Critical）+ F3（三型绕行）+ F4（③ 未列名间距族）全部收口，每条**双向自测常驻**；F2/F6 台账更正落盘；F5/F7/F8/F9 与新增不追清单在 §三/§四 明写「未覆盖」，不再冒称「已被管住」。
- **门终态**：`npm run lint:layout` **EXIT=0**，自测 **58 → 102**（严格递增，旧 37+19 例一条未删、一条未改判据）；`npm test` **29 pass / 0 fail**（未回退）。原样输出见 §五。
- 足迹（本席可写三件，全为独占）：`webui/scripts/layout-constitution.mjs`、`docs/design/unify-audit-20260919/R5-impl.md`（更正）、本文件。
  `index.css` 与全部 .ts/.tsx **零改动**；只读件（lib/locales/layout/router/logs/graph）一律未碰；无 git 写、无删除、未跑 `npm run build`/`tsc -b`（零落盘）；探针夹具全部落在 `%TEMP%/r5fix1-*`（源码树零污染，见 §五末「卫生自证」）。
- **`OFFGRID_RATCHET` 未新增任何种子**，理由=现树零存量（本席自证，非引用任务书）：
  `grep -rn 'text-\[' webui/src` → **0 命中**；`grep -rn '\-\[' webui/src` → 12 行，逐条为 `grid-rows-[auto_auto]`、`[&>svg]`、`has-[>svg]`、`[.border-b]`、`has-data-[slot=…]`、`transition-[color,box-shadow]`、`grid-cols-[1fr_auto]`、`ring-[3px]`×6、`max-h-[60vh]`、`max-h-[90svh]` —— 全部落在白名单/变体选择器/轨道清单三类既有通道内；负号前缀、透明度后缀、任意属性形态、`pr/ps/pe/space-*` 括号四型现树各 **0 处**。故本轮无需登记存量债，改门不改码。

## 一. 逐条修复（根因 → 改法 → 双向锁）

| # | 症状（复核探针） | 根因（一句话） | 本轮改法（落点） | 双向自测 |
|---|---|---|---|---|
| **F1** | `text-[13px]` 单写全绿，而 R5 §3.1 记为「②+⑦ 已管」 | ② 的 `OFF_LADDER_TEXT` 以 `\b` 收尾，`]` 之后永不构成词边界 → **括号臂自始空转**；⑦ 只在并写 `fs-*` 时命中 | ② 拆成两臂：档位臂 `\btext-(xs…6xl)\b` **一字不动**（旧行为零削弱）；括号臂改为显式值形 `\btext-\[(?:length:)?[^\]]*[\d.](长度单位)\]`（单位集 px/rem/em/ch/ex/pt/pc/in/cm/mm/%/vh 族）——**只收长度值**，色值任意值天然不沾 | 负 6：`text-[13px]`、`text-[13px] mt-1`、`text-[0.8rem] rounded-md`、`text-[1.4em]`、`text-[length:13px]`、档位臂回归锁 `text-xs`；正 5：`text-muted-foreground`、`text-primary`、`fs-caption text-tone-warn`、`text-[color:var(--brand)]`、`text-[hsl(var(--card))]` |
| **F3-①** | `-top-[3px]` 绿 | ⑧ 三条正则裸 `^` 锚定 utility 名，而 ⑤⑥ 都先剥负号 → **兄弟族不对称** | `arbViolation` 入口 `base.replace(/^-+/, '')` 后再匹配（消息仍回显原串，人看得见自己写的东西） | 负 3：`-top-[3px]`、`-inset-x-[5px]`、`-basis-[10%]`；正 2：`-top-[50vh]`（剥负号后视口白名单照旧生效）、`-rotate-[13.5deg]`（变换族刻意不追，§三在册） |
| **F3-②** | `bg-[oklch(…)]/50`、`border-[2px]/50` 绿 | 旧式 `(.*)\]$` 要求 `]` 收尾，**带透明度修饰符永不匹配**（非 hex 色字面量全裸奔） | 同入口再 `.replace(OPACITY_MODIFIER, '')`（`/nn`、`/n.n`），剥后走**同一批**白名单通道（不新增放行面） | 负 3：`bg-[oklch(0.5_0.1_200)]/50`、`border-[2px]/50`、`focus-visible:ring-[2px]/50`（证剥后缀后环白名单仍只认 3px）；正 2：`bg-[hsl(var(--card))]/50`（var 通道）、`ring-ring/50 aria-invalid:ring-destructive/20`（语义类后缀不得凭空造命中） |
| **F3-③** | `[width:13px]`、`[font-size:13px]`、`[margin:3px_auto]`、`[&>*]:[width:7px]` 全绿 | Tailwind 官方逃生口「方括号内直写 CSS 属性:值」绕过工具名解析，**②③⑤⑥⑧ 旧臂无一能看**，且 R5 台账连这一型都没登记 | 新立 `arb-prop` 小族：**行级** `matchAll`（`[` 前还有变体选择器时 token 切分必被腰斩，故不进 base 判定）；只拦 34 枚清单内尺寸/间距/描边/字号属性；值须真是「数字+长度单位」才红；`var(`/`--` 放行。family 以 `arb-` 开头 → 自动进既有脱栅棘轮账（键含全值 `[width:13px]`，**改数值即换键**，与 ⑨ 同纪律） | 负 5：`[width:13px]`、`[font-size:13px]`、`[margin:3px_auto]`、`[&>*]:[width:7px]`、`[padding:1.4rem_0.7rem]`；正 5：`[width:var(--content-max)]`、`type SizeBox = [width: number, height: number];`（TS 标注元组零误伤）、`[transform:translateX(13px)]`（未列名属性刻意不追）、`[color:var(--brand)] [.border-b]:pb-6`、`transition-[color,box-shadow] grid-rows-[auto_auto]`（现树真形制） |
| **F4** | `pe-[13px]`、`space-y-[9px]`、`space-x-[9px]` 绿，R5 §3.1 记为「③已管」 | ③ `OFF_SCALE_ARBITRARY` 实际清单缺 `pr/ps/pe/space-x/space-y`（`pl/gap-x` 有），数字臂 `OFF_SCALE_SPACING` 同样缺 `pr/space-*` → **五个属性名长期执法空白** | 两臂同补（`pr` 是 ③ 规则名「padding」本族、`space-*` 是兄弟间距且 ⑤ 只认 m 族）；改前自证现树全在档：`pr-2`×3（=8px）、`space-*` 0 处，其余 `p/px/py/pt/pb/pl/ps/pe/gap/gap-x/gap-y` 后缀 ⊂ {0,1,2,3,4,6} → 补孔零存量、不改出口码 | 负 4：`pe-[13px]`、`space-y-[9px] space-x-[9px]`、`pr-[13px]`、`pr-7 space-y-7`；正 2：`pr-2 pl-6 pe-3 ps-1 space-y-2 gap-x-4`（新列名属性的在档值照旧放行）、`pointer-events-none select-none`（词内 `pe-`/`p-` 误伤反证） |

**为什么 ⑧ 不再收 text（一条即可，不做两处）**：本轮按复核建议只在 ② 补臂。② 是「字号阶梯」单一事实轴，硬红 + `layout-allow` 出口，与 ⑧ 的「脱栅棘轮」两本账互不重叠；把 text 塞进 ⑧ 会让同一行同时进两本账（一族两红 + 键空间混淆），且 ⑦ 的双写账不受影响。
**已核对的双写面**：`fs-num text-[13px]` 现报 2 条——`[legacy] 阶梯外字号`（② 管「脱档」）+ `[dup-font-size]`（⑦ 管「双写」）——两条不同的轴、两本不同的账，不是同族重复计数；实测原样见 §五 附加探针。

## 二. 台账更正（复核判 ❌ 的三条，分清「本席的错」与「不是本席的错」）

| 复核条 | 判定 | 本轮处置 |
|---|---|---|
| #11 域纪律「只改门一个文件」被 `97eccbc` 推翻 | **不是 R5 的错误**（复核席归因错了一层）：`git show --stat 97eccbc` 作者是**主会话**，改的正是 R5 §4 交给主会话的那一条（`size-[1.2rem]`×2 → `size-5`），并同步删两行棘轮；该 commit 顺带卷入本席在飞未提交的门文件（共享工作树惯例，同 AGENTS 台账 #32 先例）。**棘轮 3→1 是债务还清的正确收窄，不是漂移，不得"改回去"** | R5-impl §0 改写为「本席足迹=仅门」+「97eccbc=主会话按 §4 落地」两句并存，并注明现树 `grep size-\[` 零命中 |
| #12 §6「脱栅棘轮 3 处」不可复跑 | **R5 的账面过失**（铁律 5：已完成必附可复跑输出） | §6 补一段**当前可复跑**终态（102/102、棘轮 1 处、npm test 29），旧 58/58+3 处快照标注为「19:4x 历史、不可复跑」；§0 的「完成」加更正，按现判据不成立 |
| #15 §3.1 两条「已管」为假 | **R5 的错误，且后果最重的一族**（后续席会据以省规则） | §3.1 内联更正三条（①text ②p 族 ③漏记任意属性形态一整型），并指向本文件；§7.2「他席新增任意值必红」同波更正为「原状不成立、本轮起成立」 |
| （#14 附）门内注释「快照 2 枚 size 在册待修」陈旧 + §4「readToken 化更佳」在 Canvas2D 上有害 | 前者=账面漂移，后者=**R5 给的一条改法本身是错的** | 门内 `:34` 与棘轮旁注均改为实况（种子 3→在册 1，readToken 不成立、只剩「探针量算」或「豁免扩编（须用户裁）」二选一）；R5-impl §2/§4/§7.2 同步更正（复核 F2/F6） |

## 三. 刻意不追 / 已知未覆盖（后续席与评审**不得**再当作已管）

| 形态 | 现状 | 不修理由（本轮裁定） |
|---|---|---|
| `ring-[3px]` 无 `focus-visible:` 链（常驻实环）、`hover:ring-[3px]` | 绿 | 复核 F5。白名单是**族形制**（chain-agnostic），而 R5 §2 的立论写的是「六处全为 focus-visible 同构」——本轮**只把这条落差登记为刻意不修**：收窄到链=改动已上线白名单的语义（宪法的 ring 族定义变了），且一旦现席某处合法地写 `hover:ring-[3px]` 即误伤。要收口请由用户裁定「ring 白名单仅限 focus* 链」后一行接线（`arbViolation` 已具备接 chain 的位置）。 |
| `w-[100vw]`、`top-[50vh]`、`basis-[33vw]` 纯视口值 | 绿 | 视口白名单同为族形制（限宽/定位皆可）。R5 §2 的立论只提「限高/限宽」，`top/left` 一类定位视口值属**顺带放行**，此处明写。若要只放 `max-h/min-h/h/w` 需用户裁（同族收窄）。 |
| `w-[calc(100%-32px)]`、`min-h-[calc(100vh-64px)]` | **红**（误伤面，复核 F7） | 修它=**扩写白名单**（`calc(<纯视口值>±<定值>)` 形态），属宪法扩编须用户追认；本轮 fix 只收「静默放行」不放行「误伤」。登记为待裁。 |
| `bg-[url(/img/x.png)]`、`bg-[radial-gradient(…)]` | **红**，且消息把它叫成「色/描边/阴影字面量」（复核 F7） | 同上（放行=扩编）。消息分「色 / 图与渐变」两路是纯文案活，本轮不动文案以免与他席哈希耦合；交后续席一行改。 |
| 代码行尾解释性注释含被禁字面量（`// 原 size-[1.2rem]`） | **红** | `COMMENT_LINE` 只跳整行注释（旧口径，F19 起）。根治=改跳「token 前的行内注释段」，牵动 ⑤⑥⑦⑧⑨ 五族，属另立修复轮；本轮规避=写码时别在尾注里留字面量（与 §四「注释类字面量外溢」同一条纪律）。 |
| `-translate-y-[7px]`、`translate-x-[7px]`、`rotate-[13.5deg]`、`origin-*`、`offset-*`、`order-[3]`、`indent-[7px]` | 绿 | 变换/位移/旋转/序/缩进**刻意不进 ⑧ 清单**：无 4px 栅格语义（`rotate` 甚至不是长度）。R5 §3.1 原清单未列名=账面缺口，本轮在此列名补齐。 |
| `opacity-[0.7]`、`outline-offset-[3px]`、`delay-[200ms]`、`border-spacing-x-[2px]` | 绿 | `opacity-/delay-` 无长度语义；`outline-offset` 被 `outline` 的 `-\[` 紧邻要求截断（清单与实现的缝），本轮登记不补——补它要把 `-offset` 塞进色影正则，与 ring 族同样需用户裁。 |
| `p-px`、`gap-px`、`space-y-px`（`px` 关键字值=1px，脱 4px 栅格） | 绿 | ③ 数字臂要求 `\d+`，单位关键字不在语法内。收它要把 ③ 的数字臂改成「非刻度即红」的宽臂，误伤面（`p-dbl`、`gap-x-reverse`、类型标注）显著大于收益 → 登记，交后续席带独立双向锁另开一轮。 |
| `w-[calc(100% - 32px)]`（**含空格**）与 `shadow-[0 1px 2px …]` | 绿 | TOKEN_SPLIT 腰斩 → 不成完整 base（R5 §3.1「诚实缺口」原样保留，与 ⑤⑥ 同源）。⑧ 的任意属性形态因走行级 matchAll 反而不受此限，余下 utility 形态仍受。 |
| `[line-height:1.8]`、`[letter-spacing:0.4px]`、`[grid-template-columns:…]`、`[--brand:10px]`、`[transform:…]` | 绿 | 属性白名单制（34 枚具名），未列名一律不追：行高/字距沿 R5 对 `leading-*/tracking-*` 的「无像素栅格语义」旧裁定；`grid-template-*` 沿「grid-\* 轨道清单不追」旧裁定；`--*` 是自定义属性定义=var 通道同口径。 |
| canvas 动态拼接 `ctx.font = \`${n}px …\``、内联 `style={{ font: '12px …' }}` | 绿 | 无静态数字 / 非 `.font =` 形态 = 原理性管不到（R5 §3.2、§7.4 旧登记，本轮不改判）。出口=代码评审。 |
| 脱栅棘轮的「命中 → 超额红」端到端 | 已有常驻锁（本轮补） | 复核 F9：该路径原先只有一次性手工实证 5a/5b。本轮抽出纯函数 `offgridRatchetClaim(hit, lineText)` 供 check() 与自测共用，并加 7 条双向锁（含「带 `layout-allow:` 时改走豁免账=两账不串」「margin/radius 不得混进棘轮」）。`excessEntries` 既有正/负双向锁不动。 |

## 四. 交主会话 / 用户的三条（本席越域，一律未动）

1. **F8（Tailwind 吞门脚本）**：`index.css` 加 `@source not "../scripts";` 一行即断根。本轮**未动**（越域）。**如实记账本波次的放大面**：双向自测要真能证「这条字面量必红」，样本就必须以真实字面量存在，故本席向 `SELFTEST`/`LEGACY_SELFTEST`/`CLAIM_SELFTEST` 三张表新增约 44 枚类串（`text-[13px]`、`pr-7`、`space-y-[9px]`、`-top-[3px]`、`[width:13px]`…）——它们会随自动源扫描编进 `dist` 的 CSS（无消费者、零视觉影响，但产物字节与测试串耦合更紧了）。折衷是明摆着的：**要么真锁，要么假锁**，本席按任务判据（"无负样本即不算修复"）选真锁，并把外溢代价登记在此，等 F8 那一行断根。散文级注释本席则一律**不写**类名（且顺手清掉两枚陈旧字面量：门内 `:34` 与棘轮旁注的 `size-[1.2rem]`）→ **下次 `npm run build` 产物字节必变，属预期，非回归**。`tests/verify_hashes.py` 清单不含 `webui/scripts/**`（本席 grep 实证 0 命中），故无需 `--write` 重录。
2. **canvas 那枚脱栅债（R5 §4/§7.1 已更正）**：`components/graph/memory-canvas.tsx|canvas-font-12px` 无「只减」路径 → 请裁：①探针量 computed px 后改绝对值；②`layout-allow` + `EXEMPTION_BASELINE` 登记（豁免扩编=用户裁定后由门维护席登记）。不裁则该枚棘轮提示长期空响（现树 exit 0 不受影响，只是富余提示常驻）。
3. **两枚白名单追认**（R5 §7.1 遗留，本轮不扩大）：视口单位族 / `ring-[3px]` 族仍待用户追认；追认时请连带 §三 前两行的「链不设门」「定位视口值顺带放行」两句一并裁掉，别再留读感落差。

## 五. 验收命令与实跑输出（2026-09-20，原样粘贴）

```
$ cd webui && npm run lint:layout
版式宪法机器门：全部通过（自测 102/102；hex=0 / 字号五档（含任意值长度形态）/ 间距 4px 栅格（p·m·gap·space 全族）/ 调色板类=0 / margin 同栅格 / 圆角三档+full 白名单 / 同元素双写=0 / 任意值方括号（盒子/环/色影/任意属性形态，负号前缀与透明度修饰符同判，var+视口+规范环 3px 白名单）/ canvas 字体字面量；行级豁免 0/0 基线，棘轮只减不增；权重双写白名单 16 处存量在册；脱栅棘轮 1 处存量在册（只减不增））
LINT_LAYOUT_EXIT=0
```

自测计数分解（102=76+17+7+2）：`SELFTEST`（⑤—⑨，走 `lineRuleHits`）37 旧 + 19（R5）+ **20（本轮）** = 76；`LEGACY_SELFTEST`（①—④，**本轮新建**、复用同一批正则对象）17；`CLAIM_SELFTEST`（棘轮路由，本轮新建）7；`ALLOW_MARK` 两断言 2（旧口径的 `+2`）。绿单计数改为 `SELFTEST_TOTAL` 实算，不再写死。

**逐案探针**（门的真实调试口是其自身 `--src <目录>`，非字符串入参：向 `%TEMP%/r5fix1-one/src/one.tsx` 写单行夹具、每案一次实跑；`RED` = 门 exit 1 且打印该famility）：

```
=== F1: ② 任意值字号 ===
RED   F1 red     const a = 'text-[13px]';                     (family=[legacy])
RED   F1 red     const a = 'text-[13px] mt-1';                (family=[legacy])
RED   F1 red     const a = 'text-[0.8rem]';                   (family=[legacy])
RED   F1 red     const a = 'text-[length:13px]';              (family=[legacy])
RED   旧臂回归   const a = 'text-xs';                          (family=[legacy])
GREEN F1 green   const a = 'text-muted-foreground';
GREEN F1 green   const a = 'text-primary';
GREEN F1 green   const a = 'fs-caption text-tone-warn';
GREEN F1 green   const a = 'text-[color:var(--brand)]';
=== F3-① 负号前缀 ===
RED   F3-1 red     const a = '-top-[3px]';                    (family=[脱栅])
RED   F3-1 red     const a = '-inset-x-[5px]';                (family=[脱栅])
GREEN F3-1 green   const a = '-top-[50vh]';
GREEN F3-1 green   const a = '-rotate-[13.5deg]';
=== F3-② 透明度后缀 ===
RED   F3-2 red     const a = 'bg-[oklch(0.5_0.1_200)]/50';    (family=[脱栅])
RED   F3-2 red     const a = 'border-[2px]/50';               (family=[脱栅])
GREEN F3-2 green   const a = 'bg-[hsl(var(--card))]/50';
GREEN F3-2 green   const a = 'ring-ring/50';
=== F3-③ 任意属性形态 ===
RED   F3-3 red     const a = '[width:13px]';                  (family=[脱栅])
RED   F3-3 red     const a = '[font-size:13px]';              (family=[脱栅])
RED   F3-3 red     const a = '[margin:3px_auto]';             (family=[脱栅])
RED   F3-3 red     const a = '[&>*]:[width:7px]';             (family=[脱栅])
GREEN F3-3 green   const a = '[width:var(--content-max)]';
GREEN F3-3 green   const a = '[transform:translateX(13px)]';
GREEN F3-3 green   type T = [width: number, height: number];
=== F4: ③ 未列名间距族 ===
RED   F4 red       const a = 'pe-[13px]';                     (family=[legacy])
RED   F4 red       const a = 'space-y-[9px]';                 (family=[legacy])
RED   F4 red       const a = 'pr-[13px]';                     (family=[legacy])
RED   F4 red       const a = 'pr-7';                          (family=[legacy])
GREEN F4 green     const a = 'pr-2 pe-3 space-y-2';
GREEN F4 green     const a = 'pointer-events-none';
=== 现树真形制（必须全绿） ===
GREEN tree  const a = 'focus-visible:ring-[3px] rounded-md';
GREEN tree  const a = 'max-h-[60vh]';
GREEN tree  const a = 'max-h-[90svh]';
GREEN tree  const a = '[&>svg]:size-4 has-[>svg]:px-3';
GREEN tree  const a = 'grid-rows-[auto_auto] transition-[color,box-shadow]';
GREEN tree  const a = '[.border-b]:pb-6 has-data-[slot=card-action]:grid-cols-[1fr_auto]';
GREEN tree  const a = '[&_svg:not([class*="size-"])]:size-4';
```

**整批夹具一次跑**（`%TEMP%/r5fix1-probe/src/probe.tsx`，59 行 = 24 条应红（c 系列 3–26）+ 21 条应绿（k 系列 28–48）+ 10 条 §三 在册缺口（g 系列 50–59）+ 表头与空行）→ `26 处违例`、`PROBE_EXIT=1`：24 条 c 系列**逐行全红无遗漏**（② 七条 `[legacy] 阶梯外字号` / ③ 五条 `[legacy] 间距` / ⑧ 十二条 `[脱栅]`，含 arb-box·arb-color·arb-ring·arb-prop 四族），k 系列 21 行**一条不红**，g 系列除刻意登记的 `w-[calc(100%-32px)]`（行 50）与 `bg-[url(…)]`（行 51）两枚误伤（§三 在册，F7）外全绿（含行 59 的含空格 calc 静默缺口）。摘要：

```
版式宪法机器门：26 处违例
  probe.tsx:3  [legacy] 阶梯外字号（…）: text-[13px]
  probe.tsx:5  [legacy] 阶梯外字号（…）: text-[0.8rem]
  probe.tsx:7  [legacy] 阶梯外字号（…）: text-[length:13px]
  probe.tsx:10 [脱栅] 未登记的任意值/canvas 字面量（OFFGRID_RATCHET 基线 0）：…：任意值盒子尺寸 -top-[3px]（…）
  probe.tsx:13 [脱栅] …：任意值色/描边/阴影字面量 bg-[oklch(0.5_0.1_200)]/50（…）
  probe.tsx:15 [脱栅] …：任意值焦点环宽 ring-[2px]/50（规范环仅 ring-[3px]，…）
  probe.tsx:16 [脱栅] …：任意属性形态 [width:13px]（width 属尺寸/间距/描边/字号轴，…）
  probe.tsx:21 [legacy] 任意值间距（用栅格刻度）: pe-[
  probe.tsx:24 [legacy] 间距脱离 4px 栅格 {0,4,8,12,16,24}: pr-7
  …（余 17 条同型，行号 4/6/8/9/11/12/14/17/18/19/20/22/23/25/26/50/51）
PROBE_EXIT=1
```

**⑦/② 双账不冲突**（附加探针，单行 `fs-num text-[13px]`）：

```
版式宪法机器门：2 处违例
  one.tsx:1  [legacy] 阶梯外字号（五档：…）: text-[13px]
  one.tsx:1  [dup-font-size] 同元素 font-size 双写（fs-* 多属性合一，胜负靠层叠，禁）：fs-num + text-[13px]: fs-num+text-[13px]
```

**削弱反证（旧「已管住」清单 25 形再跑，`%TEMP%/r5fix1-regress/src/r.tsx`）**：本轮改法只可能"多红"，此批证明"少红"为零——`size-[1.2rem]`、`inset-x-[3px]`、`basis-y-[10%]`、`border-y-[2px]`、`divide-x-[2px]`、`top-[3px]`、`w-[10px]`、`max-w-[10px]`、`min-w-[52ch]`、`max-h-[400px]`、`h-[10rem]`、`left-[7px]`、`w-[10px]!`、`!w-[10px]`、`ring-[2px]`、`ring-[0.5rem]`、`fill-[#fff]`、`bg-[rgba(31,35,41,0.04)]`、`text-xl`、`p-[9px]`、`gap-8`、`mt-7`、`rounded-sm`、`fs-body font-medium`、canvas 14px 字面量 —— **25 行全红无一行转绿**（行 3–27；其中行 19 同报 hex+脱栅，与复核席 §一.3 的旧实测一致），族别 `[脱栅]×19 / [legacy]×4 / [margin]×1 / [radius]×1 / [dup-font-weight]×1`（26 条命中落在 25 行上，行 19 双族）：

```
REGRESS_EXIT=1（= 有违例，正是本批要的判据）
```

```
$ cd webui && npm test
ℹ tests 29   ℹ pass 29   ℹ fail 0   ℹ cancelled 0   ℹ skipped 0
TEST_EXIT=0
```

python 常驻门（`tests/test_webui_constitution.py`）按任务约束未跑；其对本脚本的**唯一**耦合点是第 83 行 `assert "全部通过" in stdout`，本轮绿单原样保留该子串（上方实跑可见）。

**卫生自证**：全部夹具写在 `%TEMP%\r5fix1-probe\`、`%TEMP%\r5fix1-one\`；源码树未新增任何文件/目录，`webui/src`、`webui/dist`、`data/` 零触碰，无 `__pycache__`/`.pytest_cache`/`.ruff_cache` 产生（未起 Python 进程）。

## 六. 遗留与风险

1. 本轮**只补牙、不放行**：三条改法全部是「原本该红而没红」方向；唯一可能的行为变化面是 ③ 两臂补 `pr/space-*` 与 ② 括号臂复活，均经现树全量 grep 自证零存量（§〇 末段），故真树仍 exit 0。若他席在本轮之后新写这些形态，必红——那正是本宪法要的结局。
2. 白名单收窄类（复核 F5 两行、F7 三行、`p-px` 宽臂）一律**待用户裁**，本轮不擅自扩大也不擅自收窄；§三 已把「已放行」与「未覆盖」逐条分名，杜绝 R5 这次的「读感以为已管」。
3. 自测锁仍**只测规则命中面**，不测 `walk()` 的文件遍历与豁免账收账全流程（后者由 `report()`/`settleRatchets()` 承载，本轮仅路由判定抽出常驻）；端到端真红证据由 §五 的 `--src` 夹具批提供，两者互补。
4. 门脚本自身的类名字面量外溢（复核 F8）未在本轮根治（越域），已给一行修法；本轮产物字节影响为「少两条无消费者规则」，非回归。
5. 全波未 commit；本席三件改动的收账指针在 AGENTS/HANDBOOK 合流时统一登记（编号承接 R5 台账 #41/#42 口径）。

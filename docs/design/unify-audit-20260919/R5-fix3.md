# R5-fix3 — 版式宪法门 C-3 结构性空洞修复（放行清单地基重答辩）

Status: STARTED

- 任务：修 `webui/scripts/layout-constitution.mjs` 的 C-3（A1/A2「定义侧受管辖」地基为空话——`walk()` 只看 `.ts|.tsx`，`.css` 一个字不看；`text-[length:var(--radius-sm)]` 活体编译出 `font-size: var(--radius-sm)`，`--radius-sm: 8px` 在 `src/index.css`）。
- 路线裁决：二选一（纳入 `.css` 扫描面 / 取消「token 读」整类放行），见下文各节。
- I-6（门本体不在哈希册）：只登记不动手，禁止触碰 `tests/verify_hashes.py`、`tests/test_verify_hashes.py`、不 `--write`。
- 硬约束：可写仅本门 + 本日志 + %TEMP%；`webui/src/**` 禁写；禁 git 写；禁 `npm run build`；类型检查只 `npx tsc -p tsconfig.app.json --noEmit`。
- 基线：改前门自测 170/170、EXIT=0；棘轮/行级豁免基线数改前先实测记录。

（本文件按落盘纪律随进度 append，不攒最后一次性成文。）

---

## §0 改前基线（实跑）

```
$ cd webui && node scripts/layout-constitution.mjs
版式宪法机器门：全部通过（自测 170/170；…；行级豁免 0/0 基线，棘轮只减不增；
权重双写白名单 16 处存量在册；脱栅棘轮 1 处存量在册）          GATE_EXIT=0
```
- 自测 170（SELFTEST+LEGACY_SELFTEST+CLAIM_SELFTEST+2）；行级豁免基线 **0/0**（真 src 零 `layout-allow` 标记，grep 实证）；WEIGHT_RATCHET 合计 16；OFFGRID_RATCHET 合计 1。本波结束判据：这三本账**只准更紧不准更松**。
- 真 `src/**/*.{ts,tsx}` 任意值类面清点（grep 实跑）：仅 `max-h-[90svh]`、`max-h-[60vh]`（A3）、`ring-[3px]`×5（A4）、`transition-[color,box-shadow]`（A6）、`grid-rows-[auto_auto]`、`grid-cols-[1fr_auto]`（A5）、`has-[>svg]`/`[&_svg]:`/`has-data-[slot=card-action]`（选择器形）。**类面 token 读=0 枚**。⇒ 取消 A1 对真 src 零冲击（数据前提，非拍脑袋）。
- 真 src 唯一 `.css`=`src/index.css`（find 实跑），`main.tsx` 单点 import。

## §1 路线裁决：取消「token 读」整类放行（A1 废除）**并**把本地 `.css` 纳入扫描面（评审给的两条路各堵半个洞，实证如下；「二选一」在证据面前不成立，本节给出必须并施的理由与最小机判集）

改前门对评审 C-3 活体反例全绿（实跑 `%TEMP%/r5fix3/greenprobe/gp.tsx`，9 枚 token 读，CURRENT_GATE_ON_EXPLOITS_EXIT=**0**）：
`text-[length:var(--radius-sm)] font-[var(--radius-md)] rounded-[var(--radius-sm)] m-[length:var(--radius-sm)] gap-(--radius-sm) text-(--radius-sm) w-[var(--radius-sm)] leading-[var(--radius-sm)] border-[var(--radius-sm)]`

**编译实证（仓库自带 tailwindcss 4.3.3 JS API，真身 `webui/src/index.css` 做底，产物 stdout，脚本 `%TEMP%/r5fix3/compile-evidence.mjs`）**：
```
### text-[length:var(--radius-sm)]  →  .text-\[length\:var\(--radius-sm\)\] { font-size: var(--radius-sm); }   （同次编译 :root 实发 --radius-sm: 8px）
### font-[var(--radius-md)]         →  { --tw-font-weight: var(--radius-md); font-weight: var(--radius-md); }
### rounded-[var(--radius-sm)]      →  { border-radius: var(--radius-sm); }        （8px=脱三档 14/18/30）
### text-(--radius-sm)              →  { color: var(--radius-sm); }                （圆括号形同通道）
### m-[length:var(--radius-sm)]     →  { margin: var(--radius-sm); }               （⑤ 的 var 臂=同洞）
### gap-(--radius-sm)               →  { gap: var(--radius-sm); }                  （③ 括号全红、括号形却绿=M-7 不对称的根源）
### w-[var / leading-[var / border-[var 同通道各出 width/line-height/border-color
```

### 为什么「只选①（纳入 .css、A1 保留按值校验）」不够
读侧要判「这枚 var 读编到哪个属性」必须维护 utility→CSS 属性的全量映射（`text-` 一名三轴、`font-` 两名、`-length:` 提示换轴……）。这个映射的完备性**不可证**——它正是 R5-fix2 把「枚举坏形态」倒换为「默认拒绝」的同一失败模式。跨轴洗白（`--radius-sm: 8px` 对间距合法、被 `length:` 提示读成 8px 字号）在「每 token 单轴档位」制度下结构不可见。⇒ 读侧整类取消，不给「映射完备性」当免责地基。

### 为什么「只选②（取消 token 读、`.css` 仍不可见」不够（编译实证，`%TEMP%/r5fix3/defcss/`）
```
P1  @theme { --radius-md: 37px; }      + rounded-md  → .rounded-md{border-radius:var(--radius-md)}, :root 实发 --radius-md: 37px
P2  @theme { --text-rogue: 8px; }      + text-rogue  → .text-rogue{font-size:var(--text-rogue)}=8px 脱五档破12px下限
P3  @theme { --font-weight-heavy: 900; } + font-heavy → font-weight: 900 >700
P4  :root { --evil: url("https://evil.example/x.woff2"); } @theme inline{--font-evil:var(--evil),sans-serif} + font-evil
                                        → .font-evil{font-family:var(--evil),sans-serif}（远端拉取洗进「合法」具名类）
P5  @theme { --spacing: 7px; }         + p-1 → padding: calc(var(--spacing)*1)，一枚定义毒化**全部**栅格刻度工具类
P6  @layer base{body{font-size:9px}} + @utility rogue-pad{padding:7px} → 字面直传产物（layer 包裹/@utility 体内声明）
P7  c.css→@import'./a.css'→@import'./b.css'（:root{--radius-md:21px}）+ evil-in-import{font-size:var(--radius-md)} → 21px 字号经**导入链**进产物
```
P1/P2/P3/P5 走的是**具名工具类**（`rounded-md`/`text-rogue`/`p-1`），根本不经过 A1-A8 任意值命名空间——取消读放行对它们零防御；现门对 gp2.tsx（`text-rogue font-heavy evil-in-import rogue-pad` 四枚毒类名）**CURRENT_GATE 全绿 EXIT=0**（实跑）。⇒「定义侧受管辖」必须真的被机器看见，且扫描面须含 `@theme` 命名空间带、受管声明带、导入链。
**裁决**：A1 整类取消（含 ⑤⑥ 的 var 臂与 A1 型提示通道）+ 本地 `.css`（含 @theme/:root/@layer/@utility 内一切自定义属性写入与受管声明）纳入扫描、值带机判。两半共同兑现「定义侧受管辖」。不可机判残余（值册颜色语义、html 内联 style 等）§7 逐条具名登记，不再写「已管」。

## §2 A1—A8 逐条重答辩（判据=能编出什么/可否产出脱栅几何·非token色·非五档字号·脱三档圆角）

- **A1（裸 var token 读：`x-[var(--t)]`/`x-[<hint>:var(--t)]`/`x-(--t)`）→ 取消，全默认拒**。答辩失败：上表 9 通道编译实证逐一命中受管轴（字号 8px/字重/圆角/间距/宽高/行高/描边色），且「产出恒等于 token 本值」的旧论证把安全性外包给从未被扫描的定义侧。改判后消费只剩受管具名类（fs-*/rounded-md·lg·xl/语义色/tone-*）+ 定义侧值带机判。
- **A2（`hsl|rgb|hsla|rgba(var(--t))` 老式色包装，仅色工具族+text）→ 保留**。实证：`bg-[hsl(var(--card))]` → `background-color: hsl(var(--card))`——正则形状锁死「包装内只能是 var(--t)」，字面色（hsl(220_10%_50%) 等）在清单外已红（SELFTEST C2 组锁）；本仓库 `--card`=oklch()，`hsl(oklch())` 非法声明被浏览器整条丢弃（实测编译产物即上述文本），**能产出的最好结果=无效声明，最坏结果=读一个值册颜色 token**（值册即 token 唯一住所，色带不在三判据内，见 §7 登记）。无一轴可达。真 src 0 枚在用（纯兼容臂）。
- **A3（纯视口数值，仅 N_GEOM 盒子几何族）→ 保留**。实证：`max-h-[90svh]`→max-height:90svh、`basis-[33vw]`→flex-basis:33vw。可达轴=脱栅几何——但视口相对值**定义上**无从 4px 量化，属 R5 旧裁定的「合法脱栅」（几何带管定值，不管父容器相对分配）；正则 `^\d+(\.\d+)?(vh|vw|…)$` 单值无函数字节；**字号/行高/圆角/环宽四轴拿不到此通道**：text-[50vh] 由 ② 长度单位臂红（vh 在单位表内，锁在 LEGACY 面）、`leading-[9vh]` 非 A8 比例红、`rounded-[10vw]` ⑥ 无 var 臂红、`ring-[5vh]` 非 A4 集合红（逐条自测锁，§4）。真 src 在用（90svh/60vh 弹层限高）。
- **A4（`ring-[3px]` 具名定值）→ 保留**。实证：→ `--tw-ring-shadow: … calc(3px + …)`。value=闭合单元素集 {3px}、name 锁死 ring——造不出第四个值。真 src 5 枚在用（shadcn 焦点环规范值）。
- **A5（网格轨道 auto|0|Nfr|minmax(同形)）→ 保留**。实证：`grid-cols-[1fr_auto]`→grid-template-columns:1fr auto；`grid-rows-[auto_1fr_minmax(0,1fr)]`→minmax(0,1fr)。语法内**不存在任何固定长度字面量**（fr/auto=父容器相对分配，与 A3 同理），minmax 参数递归锁同形。拒函数嵌套（`repeat()` 不在集内=M-8 已知摩擦，登记不扩，扩编须用户裁）。真 src 在用。
- **A6（transition-[标识符清单]）→ 保留**。实证：`transition-[color,box-shadow]`→transition-property:color,box-shadow。逗号分段每段 `^[a-z][a-z0-9-]*$`——**零值字节**（无数字/括号/var/斜杠可藏），动画属性清单不产声明值。时长/延迟走 `duration-*`/`delay-*` 具名类，任意值形 `delay-[13ms]` 不在清单=红（arb-ns）。真 src 在用。
- **A7（纯角度，name 锁 rotate/skew-x/skew-y，deg|grad|rad|turn）→ 保留**。实证：`rotate-[45deg]`→rotate:45deg；`skew-x-[3deg]`→--tw-skew-x:skewX(3deg)。无长度量纲；`translate-x-[7px]` 能造脱栅位移 ⇒ translate 不在具名集、红锁在册（SELFTEST 668-669）。真 src 0 枚（保守留：角度轴无危害路径，误伤面为零）。
- **A8（leading-[无单位比例]）→ 保留**。实证：`leading-[1.07]`→line-height:1.07。比例=乘数，正则 `^\d+(\.\d+)?$` 无单位无函数⇒不产长度、触不到四判据；长度形 `leading-[13px]` 清单外红（668 锁）；与 fs-* 并写仍被 ⑦ dup-line-height 抓（566-567 锁）。残余=无 fs-* 元素上比例可超常（9.99），行高带不在三判据内，§7 登记。

## §3 既有自测改判账（逐条：改了哪条/原断言/新断言/为什么原断言是错的）

原则申明：改自测=纠正被钉死的错误结论，不是放宽门——12 条全部是 green→red（收紧方向），无一例外；改后总数 170→196。行号按改前文件（b37e019 态）。

| # | 行 | 样本 | 原断言 | 新断言 | 原断言为何是错的 |
|---|----|------|--------|--------|------------------|
| 1 | :551 | `m-[length:var(--toolong)]` | null（⑤ var 臂放行） | 'margin' | 编译实证 `margin: var(--x)`——⑤ 的「var token 除外」臂与 A1 同洞：token 值不受管时任意脱栅 margin 两步即达 |
| 2 | :564 | `rounded-[var(--r-tile)]` | null（⑥ var 臂放行） | 'radius' | 编译实证 `border-radius: var(--x)`；同文件 `--radius-sm: 8px` 使 `rounded-[var(--radius-sm)]`=8px 脱三档（§1 实证），⑥ 的 var 例外让「三档具名档」形同虚设 |
| 3 | :597 | `w-[var(--content-max)] ring-[color:var(--ring)]` | null | 'arb-box' | A1 无轴校验：w 读任意 token=脱栅几何（评审 C-3 同通道） |
| 4 | :687 | `text-(--brand)` | null | 'arb-ns' | 圆括号读=color: var(--x)，token 侧不受管即非 token 色通道（旧论证的安全前提从未机器兑现） |
| 5 | :688 | `size-(--x)` | null | 'arb-box' | width/height: var(--x)（§1 实证），同上 |
| 6 | :689 | `h-(--x)` | null | 'arb-box' | 同上 |
| 7 | :690 | `p-(--x)` | null | 'arb-ns' | 编译实证 `padding: var(--x)`；且与 `gap-[var(…)]` 恒红(M-7 不对称)自相矛盾——本波连同括号形一并归一为拒 |
| 8 | :691 | `w-[var(--x)]` | null | 'arb-box' | A1 本体（评审 §6 点名件） |
| 9 | :692 | `bg-[var(--x)]/[0.55]` | null | 'arb-color' | A1+透明度=任意色通道 |
| 10 | :693 | `text-[color:var(--brand)]` | null | 'arb-color' | 同 4（色轴读） |
| 11 | :694 | `dark:text-[color:var(--brand)]` | null | 'arb-color' | 同 10（带链形） |
| 12 | :695 | `text-[length:var(--fs-brand)]` | null | 'arb-ns' | **评审点名最讽刺件**：门把 C-3 活体漏洞（length: 提示换轴读）钉成「必须绿」契约；`--fs-brand` 这类名字根本不存在于值册也照绿——将来收口必被此锁判红，故必须改判。改后 `text-[length:var(--radius-sm)]`→font-size:8px 判红（§4 实跑） |

非断言类文本修正（不是改判，是把已作废的理由文案改正）：ARB_PROP_FORM 拒绝理由尾句「token 读一律走 utility 形 x-[var(--t)]」→「类侧无 var 读通道」（旧文案给出的规避路径正是漏洞本身，评审 C-3④ 点名）；vardef 文案「消费走 x-[var(--token)]」→「消费走受管具名类」；V 臂文案「定义侧受管辖＝只剩 index.css 台账面」→ 补「台账面自身进 ⑩ 受值带机判」；⑧′ 块注与绿单行同步。
未动的既有锁：LEGACY_SELFTEST 全部 17 条一字未动（:745/:746 两条只锁「② 不越界」——text-[color:var]/hsl 两形在 legacy 六正则面上确实零命中，与 ⑧′ 改判无冲突）；CLAIM_SELFTEST 原 10 条未动（只追加，见 §4）；⑤⑥⑦⑨①—④ 判定面零放宽。
棘轮/账目核对（只减不增自证）：WEIGHT_RATCHET 16 处不变、OFFGRID_RATCHET 1 处不变、EXEMPTION_BASELINE 0/0 不变；css-* 与 arb-* 同纪律硬红不入账（新 CLAIM 锁 3 条钉死，见 §4）。

## §4 新增反例账（19 枚入门锁 + 1 组 --src 实跑；每枚=编译证据在前、门红在后）

**读通道（SELFTEST +4，证据=§1 电池）**：`gap-(--radius-sm)`→gap:var ✓arb-ns；`border-[var(--radius-sm)]`→border-color:var ✓arb-color；`leading-[var(--radius-sm)]`→line-height:var ✓arb-ns；`m-(--radius-md)`→margin:var（补编译实跑 `.m-\(--radius-md\){margin:var(--radius-md)}`）✓arb-ns（并带 ⑤ 双锁）。评审记录未见的通道：圆括号 m/gap 形、border 色读、leading 读——上轮 39 探针与旧自测均未覆盖括号形 ⑤⑥ 邻族。
**定义侧（CSS_SELFTEST 18 条=15 负+3 正，负样本证据编号=P#）**：css-tier×4（P1 直写 37px／var 链归一 21px／@utility 体内 --radius-xl:13px 梯值不赦／calc 函数形）、css-ladder×4（P2 --text-rogue:8px／P6 @layer 声明 9px／@utility 体内 font-size:9px／font 简写零放行）、css-weight（P3 layer 包裹 --font-weight-heavy:900）、css-spacing（P5 --spacing:7px 毒化全树刻度）、css-url（P4 --evil:url() 远端拉取）、css-scale（P6 @utility padding:7px）、css-tier 声明（@utility border-radius:9px）、css-hex（--card:#fff）、css-apply×2（@apply text-xs / rounded-sm——补编译实证 `.b{border-radius:var(--radius-sm); font-size:var(--text-xs)}`，@layer 包裹）。正样本锁=值册现行全形态复刻（含注释内 hex、多长度 shadow 定义、@apply 具名语义类、var 链、@theme inline 转发——防过拦）+在带 --text-fs-caption:12px+包 @import。
**棘轮路由锁（CLAIM +3）**：css-tier/css-ladder/css-url 硬红不入账。
**import 提取断言（+1）**：三写法 specifier 全列出（跟随逻辑失明即红）。
**--src 实跑（`%TEMP%/r5fix3/redprobe/`，REDPROBE_EXIT=1，24 处违例逐条见终端实录）**：含链式导入 `chain.css→'../outside/evil.css'`（毒定义文件在扫描根**之外**、walk 不可达，仅凭导入跟随被逮住=跟随逻辑活证）；对照面：同一 redprobe 读通道 10 枚形态在改前门上全绿（§1 gp.tsx EXIT=0 实跑）。
**总账**：自测 170→**196/196**（SELFTEST 145 + LEGACY 17 + CLAIM 13 + CSS 18 + 3 断言）。

## §5 真 src 零误伤 + 账目基线（收严后）

- `cd webui && node scripts/layout-constitution.mjs` → **全部通过（自测 196/196）GATE_EXIT=0**（真 src，.ts/.tsx/.css 全进面）。
- 行级豁免基线：**0/0**（EXEMPTION_BASELINE 空集不变，真 src 零 `layout-allow` 标记——未新增任何豁免）。
- WEIGHT_RATCHET 存量 16 不变；OFFGRID_RATCHET 存量 1（canvas 专属）不变。三本账零膨胀。
- `npm test` → 65 tests/65 pass/0 fail（前端纯函数面与本改无交集，回归自证）。
- `pytest tests/test_webui_constitution.py -p no:cacheprovider --basetemp=$TEMP/gate3 -q` → **5 passed**（含两 project tsc --noEmit、node --test、cn() 行为锁、门 rc=0+「全部通过」锚——门本体三态全绿）。
- 发现真 src 违例：**0 枚**（index.css 值册全部落带；--radius-sm:8px 属「消费面无受管通道」的遗留定义——rounded-sm 类面恒红、类侧无 var 读，无可用路径，语义在 §7-R3 具名登记，未动 src 一字）。

## §6 I-6 登记（按令：只登记不动手）

门本体 `webui/scripts/layout-constitution.mjs` **仍不在** `tests/verify_hashes.py` 哈希册（本席未碰、未 `--write`）。补锁需同动三处、代价如下，交回用户裁（台账项 Y3）：
1. `tests/verify_hashes.py` → `TRACKED_FILES` 追加 `webui/scripts/layout-constitution.mjs` 一行；
2. `tests/test_verify_hashes.py:92` 硬编码件数断言 `== 19` 同步 `== 20`；
3. 一次 `python tests/verify_hashes.py --write` 重录 `tests/render_hashes.json`。
代价/风险：哈希册属其它波次地盘且 Y3 未裁；多会话共享树下任何人跑 `--write` 会把**全部在飞脏件**一并免检（I-5 已实证一次：CAP1 十件被无关繁體提交抢录）——必须「改动同笔提交内+工作树对在册件干净」才安全，故只可在合流波统一执行。本席自证：本次门改动完成后 `git status --porcelain -- webui/` 仅 `M webui/scripts/layout-constitution.mjs` 一件，无连带漂移。

## §7 不可机判残余（具名登记，不写「已管」）

- R1 包导入样式（`@import 'tailwindcss'` 等）：扫描面外，由 package.json/lockfile 评审面管（门对每条跳过打「@import 跳过」提示行，失明不可静默）。
- R2 值册**颜色**语义：色带不在三判据（脱栅几何/非 token 色/非五档字号）内，定义侧只判 hex/url；「把 --primary 改成荧光粉」仍是评审面非机器面。
- R3 `--radius-sm: 8px` 类「档位命名空间外」的遗留长度定义：现无任何受管消费面（rounded-sm 类红、var 读取消），但若将来新工具类命名撞上，定义带不覆盖——登记为值册扩建评审点。
- R4 line-height：类侧只锁「脱 fs-* 合一」（⑦）与 A8 比例形；样式表内 line-height 声明/`--text-*--line-height` 不判（非三判据轴）。
- R5 `index.html` 内联 `<style>`/style 属性与 locale JSON：扫描面外（现树 index.html 仅 CSP+data: favicon，实读核对）。
- R6 JS 动态拼出的类名运行期取值（`[\`m-${x}\`]` 产物面）：原理性不可见（截断形已判红，残余同 R5-fix2 §五）。
- R7 named 具名 w/h/max-w 定值类（如 w-24）本就不在 4px 执法面——既有范围裁定，非本波新洞，沿记。

## §8 终态

Status: DONE。路线=A1 整类取消+⑩ 定义侧进面（并施理由与实证=§1）；A2—A8 全表带编译实证保留（§2）；自测 196/196；反例新增 19 入门锁+1 组 --src 实跑（每枚先编译后判红）；真 src EXIT=0 零误伤、豁免 0/0 不增、三本账不膨胀；I-6 只登记未动手；`webui/src/**` 一字未动。验证三件（门/npm test/pytest 5 门）终态全绿，命令与输出如上。工作树本席痕迹=门 1 件修改+本日志 1 件新增（git status --porcelain -- webui/ 实跑为证）；未执行任何 git 写操作、未跑 npm run build、未碰 verify_hashes 任何件、未派子代理。探针与编译产物全在 %TEMP%/r5fix3/（compile-evidence.mjs/greenprobe/redprobe/defcss/out/），仓库零污染。

# F11-b — 实测对比度账（2026-09-19，只读席位）

> 本席位只出**算术实算值**，不出估算。所有比值由脚本 `f11b_contrast.py` 解析 `webui/src/index.css` 现算，转换器对 5 枚 index.css 注释里的对照 hex 逐字复现（见 §1 验证），故可信。凡"计数"均为**快照口径**（重跑前须 re-grep）。

## 0. 状态（进行中/完成 + 时间戳）
- 状态：**完成**
- 快照时间戳：2026-09-19 17:48:05（本地）
- 只读席位：源码零写入（除本账 + `%TEMP%` 脚本目录）；未 commit / 未 build / 未 pytest / 未 npm install / 未 pip install（转换器纯手写、零依赖）。
- 一句话结论：**暗色零缺陷；亮色 8 条独立缺陷配对（5 文本 AA 失败 + 3 非文本 <3:1 控件）**；`SEMANTIC_WARNING #b07d1a` 统一化对文本 AA **救回 0 处**（2.65→3.00，仍远低于 4.5，F11 的 U-4 警告被实数证实）；救回全部需把 `--tone-warn`（亮）压到 ≈ `oklch(0.522 0.1074 58)` ≈ **#965820**（比 F11 提的 `#975820` 再深一毫，`#975820` 卡在 4.48 差 0.02）。

## 1. 方法（公式、取色来源、如何解析 CSS 变量与 color-mix/oklch）

**取色唯一真源**：`webui/src/index.css`（Tailwind v4 `@theme` / CSS 变量）。脚本按大括号配对提取**两个** `:root` 块与**两个** `.dark` 块（tone 色在第二组里）合并，逐 `--name: value;` 解析，注释先剥离。
- `var(--x)` 递归解引用（`--background→--wash-mist`、`--secondary→--wash-1`、`--muted→--wash-3`、`--accent→--wash-2`、`--card-foreground→--foreground`、`--sidebar→--card`、`--tone-purple→--sk-purple` 全部实测解析成功）。
- 暗块未覆盖的 token 回落到 `:root`（如 `--sk-*`/`--wash-*` 无暗变体）。
- `@theme inline` 只是 `--color-X: var(--X)` 的别名映射，组件类名 `text-tone-warn→--color-tone-warn→--tone-warn`，故直接以 `:root/.dark` 的语义 token 为准。
- **未硬编码任何假设 hex**（候选值 `#b07d1a`/`#975820` 等仅用于 §5 的"若改成它"的情景重算，其对照比值同样现算）。

**色空间转换**（oklch→sRGB，Björn Ottosson OKLab，脚本注释含矩阵）：
`a=C·cos h, b=C·sin h → l_,m_,s_ →(立方)l,m,s → 线性 sRGB 3×3 → sRGB 复合伽马(1.055·c^(1/2.4)−0.055) → 0..255`。

**验证**（脚本自打印，逐字复现 index.css 注释 hex）：
| token | 解析值 | 注释对照 | 判定 |
|---|---|---|---|
| light `--primary` | `#318ce7` | `#318ce7` | OK |
| light `--wash-mist` | `#f4f5f6` | `#f4f5f6` | OK |
| light `--tone-warn` | `#e27100` | `#e27100`(amber-600 系) | OK |
| dark `--background` | `#1c2031` | `#1c2031` | OK |
| dark `--card` | `#24293d` | `#24293d` | OK |
5/5 精确命中 ⇒ 转换器可信。

**相对亮度与比值**（WCAG 2.x）：`L=0.2126R+0.7152G+0.0722B`（R/G/B 由 sRGB 逐通道 `c≤0.04045? c/12.92 : ((c+0.055)/1.055)^2.4` 线性化）；`CR=(L1+0.05)/(L2+0.05)`。阈值：正文 4.5、大文本 3.0、非文本 UI 3.0。

**color-mix / 半透明合成**：`tone-face-* = color-mix(in srgb, tone P%, transparent)` 与 `bg-muted/40`（Tailwind v4 = `color-mix(in oklab, muted 40%, transparent)`）等价于"该色按 P% 不透明叠在不透明父面上"，父面为**实渲染背景**（卡片→`--card`，页底→`--background`）。浏览器源覆盖合成在非线性 sRGB 上进行，故脚本用 `over(fg,α,bg)=α·fg+(1−α)·bg`（0..255 伽马域）再算亮度。与纯 `color-mix 与 transparent` 数学一致（与 transparent 混只压 α、不改色相）。

**大文本资格（实测字号阶梯，1rem=16px，index.css 无 html font-size 覆盖）**：
`fs-page 18px/w600`｜`fs-card 14px/w600`｜`fs-body 13px/w400`｜`fs-caption 12px/w400`｜`fs-num 30px/w600`。
WCAG 大文本=≥24px 常规 或 ≥18.66px 且 bold(≥700)。**所有 amber 文字站点只用 `fs-card`(14px/w600) 与 `fs-caption`(12px/w400)**，均 <18.66px 且权重 600<700 → **一律按正文 4.5 判定，无一枚 amber 文字够格走 3.0 大文本豁免**（`fs-page` 18px 也 <18.66px 且非 700，仍不达大文本；`fs-num` 30px 虽达但从不着 amber）。

## 2. 令牌色值实测表（light / dark 解析后 RGB + 相对亮度 L*）

| token | light | L* | dark | L* |
|---|---|---|---|---|
| --background | #f4f5f6 | 0.912 | #1c2031 | 0.015 |
| --foreground | #242a42 | 0.024 | #ecedee | 0.846 |
| --card | #fafbfc | 0.963 | #24293d | 0.023 |
| --popover | #fcfcfd | 0.974 | #282e43 | 0.028 |
| --primary | #318ce7 | 0.252 | #4999e9 | 0.301 |
| --primary-foreground | #ffffff | 1.000 | #1d2135 | 0.016 |
| --secondary | #d9e0e7 | 0.738 | #2e3245 | 0.033 |
| --secondary-foreground | #3950ac | 0.096 | #ecedee | 0.846 |
| --muted | #dcdfea | 0.739 | #2c2f3d | 0.029 |
| --muted-foreground | #5a617c | 0.122 | #b3b7bc | 0.471 |
| --accent | #dfdae7 | 0.716 | #433a50 | 0.048 |
| --accent-foreground | #683da2 | 0.089 | #ecedee | 0.846 |
| --destructive | #ee3439 | 0.209 | #fb575c | 0.281 |
| --success | #2e9e6b | 0.261 | #4ca779 | 0.306 |
| --border | #d6dbe1 | 0.704 | #434756 | 0.064 |
| --ring | #318ce7 | 0.252 | #4999e9 | 0.301 |
| **--tone-warn** | **#e27100** | **0.280** | **#e9c16c** | 0.565 |
| --tone-good | #009965 | 0.237 | #00d492 | 0.492 |
| --tone-bad | #e7000b | 0.170 | #ffa2a3 | 0.497 |
| --tone-info | #0069a8 | 0.129 | #74d4ff | 0.580 |
| --tone-purple | #824dcb | 0.144 | #b49ad8 | 0.378 |
| --tone-magenta | #bd24da | 0.171 | #ffa9ff | 0.569 |
| --sk-purple | #824dcb | 0.144 | #824dcb | 0.144 |
| --sk-deep | #3950ac | 0.096 | #3950ac | 0.096 |
| --wash-1 / 2 / 3 | #d9e0e7 / #dfdae7 / #dcdfea | 0.738 / 0.716 / 0.739 | 同左(无暗变体) | |
| --wash-mist | #f4f5f6 | 0.912 | 同左 | |
| --sidebar | #fafbfc | 0.963 | #202537 | 0.019 |

> 派生面合成实测：`tone-face-warn(14%) over card` = **#f7e8d9**；`over background` = **#f1e3d4**；`bg-muted/40 over background` = **#eaecf1**；`over card` = **#eef0f5**。

## 3. 前景/背景配对实测矩阵（真实渲染配对）

组件实渲染背景经源码核：`Card=bg-card`(不透明)；`main`=无 bg→继承 `bg-background`；页级横幅为 main 直接子→落 `background`；`SectionCard` 内条/Chip→落 `card`；`outline Badge`/透明面→显父面。

**LIGHT（amber `--tone-warn` #e27100）**
| # | 配对（消费锚） | 类型 | 阈值 | 实测比 | fg/bg | 判定 |
|---|---|---|---|---|---|---|
| 1 | affinity.tsx:28 分数 fs-card14 | text | 4.5 | **3.07** | #e27100/#fafbfc | **FAIL** |
| 2 | tokens.tsx:39 Badge `~N` fs-cap12 | text | 4.5 | **3.07** | #e27100/#fafbfc | **FAIL** |
| 3 | semantic-state.tsx:76 图标 size-8 | ui | 3.0 | 3.07 | #e27100/#fafbfc | PASS(险过) |
| 4 | latency.tsx:98 图标 size-4 | ui | 3.0 | 3.07 | #e27100/#fafbfc | PASS(险过) |
| 5 | CategoryChip warn 文字 over card（patterns:101 扇出） | text | 4.5 | **2.65** | #e27100/#f7e8d9 | **FAIL** |
| 6 | logs.tsx:241 RotateCcw over face-on-bg | ui | 3.0 | **2.53** | #e27100/#f1e3d4 | **FAIL** |
| 7 | logs.tsx:240 border-tone-warn vs background | ui | 3.0 | **2.92** | #e27100/#f4f5f6 | **FAIL** |
| 8 | memory-graph.tsx:169 说明 over muted/40-on-bg | text | 4.5 | **2.69** | #e27100/#eaecf1 | **FAIL** |
| 9 | memory-graph.tsx:168 图标 over muted/40-on-bg | ui | 3.0 | **2.69** | #e27100/#eaecf1 | **FAIL** |
| 10 | memory-graph.tsx:284 说明 over muted/40-on-card | text | 4.5 | **2.79** | #e27100/#eef0f5 | **FAIL** |

**DARK（amber `--tone-warn` #e9c16c）**：同 10 配对全部 **PASS**（最低 6.18 = 类别章 over dark-card；plain card 8.43；border vs dark-bg 9.47）。→ **缺陷亮色专属**。

**永不发生的配对（非缺陷，按铁律不列）**：amber 文字直接压在 `--primary`/`--destructive`/`--success`/scrim/popover-foreground 上——grep 全仓无此类组合；amber 仅现于 warn 语义（卡面/页底/muted/40/tone-face-warn）。

## 4. 缺陷清单（实测；快照 2026-09-19）

亮态 **8 条独立缺陷配对** = **5 文本(AA<4.5)** + **3 非文本控件(<3:1)**。暗态 **0 条**。

文本 AA 失败（阈值 4.5，全部 amber 均正文档，见 §1）：
- **D-T1** `memory-graph.tsx:169` fs-caption over `bg-muted/40`-on-background = **2.69**｜文本｜非大文本豁免
- **D-T2** `memory-graph.tsx:284` fs-caption over `bg-muted/40`-on-card = **2.79**｜文本
- **D-T3** `patterns.tsx:101 CategoryChip tone='warn'`（扇出 `affinity.tsx:53`、`logs.tsx:304`、`latency.tsx:27`、`memory-graph.tsx:171`）文字 over `tone-face-warn`-on-card = **2.65**｜文本｜**最差文本**
- **D-T4** `affinity.tsx:28` 分数 over card = **3.07**｜文本
- **D-T5** `tokens.tsx:39` Badge over card = **3.07**｜文本

非文本 UI 控件 **<3:1**（1.4.11）：
- **D-N1** `logs.tsx:241` RotateCcw size-4 over `tone-face-warn`-on-background = **2.53**｜**全局最差**
- **D-N2** `memory-graph.tsx:168` TriangleAlert size-4 over `bg-muted/40` = **2.69**
- **D-N3** `logs.tsx:240` `border-tone-warn` vs `background` = **2.92**（边界 <3:1）

> 险过线（未列缺陷但需守）：`semantic-state.tsx:76`(3.07)、`latency.tsx:98`(3.07) 图标 = 卡面上 ui≥3.0 勉强通过；一旦换底或改色即翻车。
> 站点计数（快照口径，非配对数）：amber 源锚 ≈ **15 处**（`patterns.tsx:101`、`affinity.tsx:20/28/53`、`latency.tsx:16/27/98`、`semantic-state.tsx:76`、`logs.tsx:25/33/240/241/304`、`memory-graph.tsx:168/169/171/284`、`tokens.tsx:39`；`utils.ts:24` 仅类名白名单不计），其中多数按数据态门控（tier∈{-1,-2}/warning 行/degradedSources/latency 降级），**实际渲染 DOM 节点数随数据浮动**（见 §6）。F11 报的"~23"应为其运行时按行展开的估算，静态源锚与实测配对均不支持"35 AA 缺陷"。

## 5. SEMANTIC_WARNING / `--tone-warn` 改值影响面

先厘清两个"warning"：值册 `SEMANTIC_WARNING = #b07d1a`（`theme_tokens.py:246`，供 bot 卡片 playwright 截图用，白卡不同语境）；WebUI 琥珀 = `--tone-warn`（亮 `oklch(0.666 0.179 58)`=`#e27100`）。§5 情景 = "把 `--tone-warn` 改成候选值，15 处 amber 站点全移动"，脚本现算：

| 候选（亮） | hex | 文本缺陷数 | 非文本缺陷数 | 最差文本比 | chip-face over card 文字 | plain card | border vs bg | 14% face 合成色 |
|---|---|---|---|---|---|---|---|---|
| 现值 | #e27100 | **5** | **4\*** | 2.65 | 2.65 | 3.07 | 2.92 | #f7e8d9 |
| **统一=值册 `SEMANTIC_WARNING`** | #b07d1a | **5** | 1 | **3.00** | 3.00 | 3.50 | 3.32 | #f0e9dc |
| F11 提案 | #975820 | 1 | 0 | **4.48**（差 0.02） | 4.48 | 5.43 | 5.15 | #ece4dd |
| 本席最小全清 AA | #965820 ≈ oklch(0.522 0.1074 58) | **0** | **0** | 4.50 | 4.50 | 5.46 | 5.18 | #e7e0d8 |
| 带余量 | #8f5a1e | 0 | 0 | **4.57** | 4.57 | 5.55 | 5.27 | — |
| 过深(不建议) | oklch(.46 .12 58)=#884300 | 0 | 0 | 5.71 | — | — | — | — |

> \* 脚本另列了"chip 作为 ui 图形"一行（2.65），但 CategoryChip 内容是**文字**，应按 4.5 归文本；故权威计数：文本 5、非文本 3（§4）。此表"非文本缺陷数 4"含该冗余行，权威以 §4 的 3 为准。

**判定（硬结论）**：
- **"统一采用值册 `SEMANTIC_WARNING #b07d1a`" 不修任何文本 AA 缺陷**：chip 文字 2.65→3.00、plain card 3.07→3.50、muted/40 说明→~3.1，**5 条文本仍全部 FAIL 4.5**（minText 3.00）。只让 border 从 2.92→3.32 勉强过 3.0。→ **F11 的 U-4 警告被实数坐实**：照"统一=无脑取值册"改会把账面做成"已对齐"而实际 2.65 只抬到 3.00，仍不达标，属**假修**。
- **F11 提案 `#975820` 差一口气**：绑定约束是 **chip-face-on-card 文字（4.48 < 4.5）**，非 plain-card（5.43）。压 face 上只有 ~1 的救回空间被 14% 面同色拖累（文字与面同色系，暗化时面也随之暗）。
- **真正救回全部 8 条的最浅改值 ≈ `oklch(0.522 0.1074 58)` ≈ `#965820`**（比 #975820 再深一毫）；要留可执行余量取 **#8f5a1e**（chip 4.57）。
- **代价**：① 亮态 amber 一旦深到 #965820，即**放弃与值册 `SEMANTIC_WARNING #b07d1a` 的数值统一**（webui 与 bot 卡片各走各的琥珀，需接受这层"不统一"或以 webui 值反灌值册并复跑卡片渲染契约）；② 14% chip face 更灰一档（#f7e8d9→#e7e0d8）；③ **暗态绝不可跟暗**——暗 amber #e9c16c 现全 PASS(≥6.18)，本改值是**仅 `:root` 亮块**、`.dark` 不动；④ amber 与 `--tone-bad #e7000b` 色相相距远(58 vs 27)，不发生 1.4.1 可辨性冲突。

## 6. 无法静态判定的（需实机截图取色）
1. **实际渲染的 amber DOM 节点总数**：D-T3(Chip) 与各分数/说明均按数据态门控（affinity tier∈{-1,-2}、logs `warning` 行数、`memory-graph degradedSources.length`、`latency` 降级行数）。静态只能给源锚 ≈15 / 配对 8；**可见 amber 节点数随数据浮动**，须实机灌真数据截图后逐节点数。
2. **`bg-muted/40` / `tone-face-*` 的真实落定像素**：脚本按"半透明叠不透明父面(sRGB 域源覆盖)"建模，与数学一致；但页级横幅父面判定为 `--background`（依 JSX 嵌套），**若该横幅实际落在某 Card 内**则父面为 `--card`、比值 ~±0.1 漂移（#eaecf1 vs #eef0f5 → 2.69 vs 2.79，结论不变：仍 FAIL）。要 100% 钉死父面需运行时 DevTools 取样。
3. **图标类抗锯齿边缘 / 顶栏 `bg-background/80 backdrop-blur` 半透明**：亚像素与滤镜后的实际感知对比非纯色值可算；但**无 amber 文字坐落在顶栏或 scrim 上**（grep 证实），故对缺陷清单无影响，仅影响 §4"险过线"两枚图标（3.07）的鲁棒性判断。

## 7. 复算脚本位置与运行方式
- 脚本（**不在仓库内**，零污染源码树）：`C:/Users/LancyCelestia/AppData/Local/Temp/f11b/f11b_contrast.py`
- 运行（纯标准库，无依赖；不落字节码）：
  ```
  cd "C:/Users/LancyCelestia/AppData/Local/Temp/f11b"
  PYTHONDONTWRITEBYTECODE=1 python f11b_contrast.py
  ```
- 输出：① 5 枚 index.css 注释 hex 逐字验证；② light/dark 令牌表(RGB+L*)；③ light/dark amber 配对矩阵；④ `--tone-warn` 候选情景扫描(文本/非文本缺陷数、最差比、face 合成色)；⑤ 最小全清 AA 值二分求解。
- 改配对/候选：编辑脚本内 `PAIRS` / `CANDS` 列表（引用的是解析出的 token 名与 CSS 合成参数，非硬编码色值）。
- 快照口径：配对/站点计数为 2026-09-19 快照；fix 波若已动 `index.css` 或组件类名，re-grep 后重跑即刷新。

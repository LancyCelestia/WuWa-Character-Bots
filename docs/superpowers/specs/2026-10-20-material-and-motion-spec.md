# 《材质与动效规格书》—— 守岸人 WebUI

> W18 阶段 1 交付。本文件的每一条都是**可验收的参数**，不是形容词。
> 复跑命令逐条附在条目旁边；任一参数不达标即该条验收失败。
> 生成时刻：2026-10-20 08:52（本机时区 **UTC+08:00**）。

---

## 〇、这份文件为什么存在

用户原话：「'好看'必须可验收」。上一版报告里出现了「玻璃感通透」「釉瑚层次」
这类词，它们无法被判定通过或失败。本文件把每个这类词换成 **三件套**：
定值 + 上限 + 降级路径。三条缺一，该条不算规格。

---

## 一、材质层

### 1.1 液态玻璃（Liquid Glass）

| 参数 | 定值 | 上限 | 降级路径 | 实测 |
|---|---|---|---|---|
| blur 半径 | `18px` (`--glass-blur`) | **40px**（`glass-budget.mjs` 硬判） | `lite` 档 → `none` | 5 处 backdrop-filter，全部 ≤40px |
| saturate | `148%` (`--glass-saturate`) | 不设（饱和度不影响采样成本） | 同上 | — |
| 描边强度 | `0.56 × 70% = 39%` 墨色 | 上限 70% | 不支持时保留描边 | 对比度 **>3:1**（WCAG 1.4.11） |
| 顶沿高光 | `inset 0 1px 0 color-mix(oklch(1 0 0) 62%, transparent)` | — | 保留 | — |
| 底沿暗线 | `inset 0 -1px 0 color-mix(var(--foreground) 8%, transparent)` | — | 保留 | — |
| 外圈投影 | `--shell-glow`（两层：18px/40px + 4px/12px） | — | 保留 | — |

**层数上限（硬指标）**：同一视口内同时可见的玻璃面 **≤3**。
当前恰好 3：侧栏 `window` + 顶栏 `mica-bar` + 主内容 `content-field`。
判据：`node webui/scripts/glass-budget.mjs` → `全部通过：玻璃层数上限 3 / blur 上限 40px / 无嵌套 / @supports 降级在位`

**禁止嵌套**：`surface` / `surface-flat` / `glass-panel` / `window` / `mica-bar` 不得在同一元素上叠两个。
理由：同一像素被采样两次，中端 Android 掉到 20fps（实测）。

**降级路径（`@supports not (backdrop-filter…)`）**：
玻璃退成 94–96% 实面，**保留层次、放弃通透**。描边与投影不动，所以版式观感不变。
不降级的后果不是审美问题：Firefox 旧版/关硬件加速时是「半透明白底 + 不模糊」，
文字压在壁纸细节上，实测对比度掉到 **1.6:1**（要 4.5:1）。

### 1.2 云母（Mica）

| 参数 | 值 | 为什么是这个值 |
|---|---|---|
| 面板不透明度 | **90%** (`--mica-panel`) | 原 72% 时 `--muted-foreground` 在面板上只有 **3.6:1** |
| 侧栏 | **90%** (`--mica-sided`) | 原 68% 时实测底色 rgb(196 203 220)，12px 说明文字不可读 |
| 顶栏 | **86%** (`--mica-header`) | 原 58% 时实测 rgb(197 198 211)，3.61:1 |
| 阅读面 | **74%** (`.content-field`) | 正文不再直接压壁纸；这是**结构性**修法不是调参 |
| blur | `blur(30px) saturate(1.4)` | Win11 Mica 的等效配方 |
| 颗粒 | 两层交叉 radial-gradient（0.6px / 0.5px 点阵） | 不用 feTurbulence data URI：版式宪法 ⑩ 对 `url(` 一律判红 |

**Win11 Mica 的诚实边界**：网页**没有 API 读系统壁纸**，「Mica for Web」这个 CSS 标准不存在。
本仓能做的是分层仿制（底材从缝透 + 内容坐填充层）+ 失焦降级，**不是**真 Mica。
这一点必须写在文档里，否则就是虚假宣传。

### 1.3 油膜虹彩流光

> **术语说明**：原需求写「动态油壶渐变色」，按语音输入推断为**油膜**（thin-film iridescence）。
> 若原意是机油壶/油桶，请指出，我按原意重做；不自行发挥。

| 参数 | 值 | 判据 |
|---|---|---|
| 周期 | **14s** | **≥12s**（`--iris-stroke`）。短于此被读成加载指示器 |
| 用途 | accents only：选中导航项、页标题釉线、品牌环 | 三处消费方，不满屏撒 |
| 角度插值 | `@property --iris-angle { syntax: '<angle>' }` | 不注册则 CSS 无法插值，虹彩只剩静止渐变 |
| 浅色档端点 | brand `rgb(40 118 200)` / purple `oklch(.46)` / deep `oklch(.40)` | 实测虹彩数字 **7.41:1**（原 1.9:1） |
| 深色档端点 | 三枚全部 `oklch(.66 …)` | 实测 **4.36:1**（原 2.46:1） |
| 描边圆环 | 两层 mask + `mask-composite: exclude` | 只留 1px 环 |

**深色档的一个陷阱（已踩过）**：不能直接在 `.dark` 里重定义 `--sk-purple` / `--sk-deep` / `--brand-accent`。
`components/appearance/appearance-wiring.css` 用 `html:root { … }`（特异性 0,1,1）把这三枚钉到外观页色号上，
`.dark`（0,1,0）**压不过它**。实测：改完构建产物里两条都在，但计算值仍是 wiring 那条，虹彩纹丝不动。
正确做法是只覆盖派生品 `--iris-stroke`。

### 1.4 粒子（气泡场）

| 参数 | 值 | 判据 |
|---|---|---|
| 数量 | `clamp(26, viewportWidth / 20, 74)` | **≤74** 硬顶；`cap` 传 9999 也只得 74 |
| lite 档 | 基数的一半（下限 26） | `particleBudget()` |
| 渲染路径 | full + WebGL2 → `webgl`；其余 → `canvas2d`；off → `none`（**不建画布**） | `pickParticlePath()` |
| DPR 上限 | **2** | 再高只烧 GPU 不增可见度 |
| 层级 | `z-index: -25`（单背景层） | 不参与内容层叠 |
| 停播条件 | IntersectionObserver ≤1% / `visibilitychange hidden` / `data-saver=1` / 档位 off | 四条全测 |

---

## 二、动效三层闸

### 2.1 档位判定（全部来自环境事实，不是随机或时间）

| 档位 | 触发条件（按优先级，前一条命中即停） | 结果 |
|---|---|---|
| **off** | ① `prefers-reduced-motion: reduce` ② 外观页关掉动效 | 无动画、无粒子、无自定义光标；**功能全保留** |
| **lite** | ③ `saveData` ② `hardwareConcurrency ≤ 2` ③ `viewport ≤ 900px` | 玻璃退实面、光斑停漂移、粒子降 2D 且减半；**功能全保留** |
| **full** | 以上都不成立 | WebGL2 粒子、自定义光标、reveal 全开 |

### 2.2 停播名单的单一事实源（这是 R4 的教训）

`:root[data-motion='off']` 与 `@media (prefers-reduced-motion: reduce)` **两份名单必须覆盖同一批宿主**。
曾各自演化，结果「外观页关动效」只停了 5 个、漏了 7 个。
现由 `tests/test_webui_motion_switch.py` 逐宿主比对（含 `@utility` 内 `&::before` 形态），新加无限动画忘了登记即红。

🔴 **`animation-duration: 0.01ms` 停不掉 `infinite`**：它把周期压到 0.01ms，
动画反而以约 10 万次/秒重放，CPU 比不关还高。唯一真正的停止是 `animation: none`。

实测：默认 `running=11` → `data-motion='off'` 下 **`running=0`**。

### 2.3 lite 档的降级（曾写了没人消费）

`motion-chrome.tsx` 一直往 `<html>` 写 `data-motion-tier`，但全树**零消费方** —— 档位算出来是 lite，
画面和 full 一模一样。现补上 `:root[data-motion-tier='lite']` 段：
砍 `backdrop-filter`（这条线上最贵的单点）、砍光斑漂移；保留入场、reveal、面板过渡、图表描边（一次性动画不影响静置功耗）。

---

## 三、文字与对比度

| 参数 | 值 | 判据 |
|---|---|---|
| 正文对比度 | **≥4.5:1** | WCAG 1.4.3 |
| 大字对比度 | **≥3:1**（≥24px，或 ≥18.66px 且 bold） | 同上 |
| 非文本对比度（焦点环/图标/边界） | **≥3:1** | WCAG 1.4.11 |
| 字号五档 | 12 / 13 / 14 / 18 / 30 px | 版式宪法硬判 |
| 字重上限 | **700** | 只允许 thin..bold 六档命名值 |
| 字体 | 系统栈（不自托管 woff2） | 20GiB/月 + TTI 双约束下，一套 CJK 子集字体 = 1.5–3 MiB，单项占比最大 |
| 字距 | 全局 `--ty-track`（默认 0em） | 每元素单独写 `letter-spacing` 判红 |

**实测结果（真实像素，不是计算样式）**：

| 档 | 路由数 | 采样 | 不达标 | 最差 |
|---|---|---|---|---|
| 浅色桌面 | 7 | 117 | **0** | ≥4.75:1 |
| 深色桌面 | 7 | 117 | **0** | ≥5.26:1 |
| 移动 390×844 | 7 | 76 | **0** | 4.75:1 |
| 渐变文字（浅/深） | — | 各 1 | **0** | 7.41:1 / 4.36:1 |

复跑：
```bash
node webui/scripts/contrast-audit.mjs webui/tmp/w18b-contrast3.json        # 浅色
node webui/tmp/contrast-dark.mjs webui/tmp/w18b-dark.json                  # 深色
node webui/scripts/gradient-text-contrast.mjs webui/tmp/w18b-light.json    # 渐变文字
```

**为什么必须取像素**：玻璃面板的 background 是 `color-mix(… transparent)`，计算样式只给带
alpha 的半透明值；WCAG 要的是**最终合成到屏幕上的颜色**。按计算样式算过一次，给全部面板判通过，
但它们实际压在一张亮蓝壁纸上——假绿。

**渐变文字的单独口径**：`background-clip: text` + `color: transparent` 的元素，
`getComputedStyle().color` 是 `rgba(0,0,0,0)`，通用测法会量出 1.47:1 这种无意义的值。
它的前景在 `background-image` 的渐变停靠点上，只有像素知道。这类元素从通用扫描里**排除**，
由 `gradient-text-contrast.mjs` 单独测（极性先判：浅档字暗底亮、深档字亮底暗，写死一侧必错）。

---

## 四、语义化动效清单（每条都有触发时机与时长）

| 动效 | 触发 | 时长 / 曲线 | 降级 |
|---|---|---|---|
| 首帧幕布 | 每会话首次挂载 | hold 520ms / linger 1100ms / safety 2600ms | off 档不挂 |
| 标题遮罩揭示 | 元素进视口 | `translateY(114%)`→0，1.35s `--ease-out-quint` | 已在视口内直接 in（首屏不闪） |
| 兄弟递进 | reveal 容器内 | 0.09s 一档，最多 5 档 | off 档 `transition-delay: 0s` |
| 面板入场 | 路由切换（`key={pathname}`） | 0.9s `--ease-out-quint` | 同路径搜索参数变化**不重播** |
| 滚动进度 | 滚动 | 2px 高，`scaleX(progress)`，`--brand-grad` | off 档 `display:none` |
| 导航指示器 | 路由/悬停 | 0.6s `--ease-out-quint`，`translate3d` + 尺寸 | off 档 `transition:none` |
| 自定义光标 | 指针移动 | dot 4px / ring 34px，`lerp 0.16`，悬停 56px 0.45s | 触屏/窄屏/reduce 不挂 |
| 光斑漂移 | 常驻 | 28s / 41s / 53s，只动 `transform` | lite/off 档 `animation:none` |
| 品牌环自转 | 常驻 | **120s** linear | 两份停播名单 |
| 虹彩流转 | 常驻 | **14s** linear | 两份停播名单 |

🔴 **全部用 `transform` / `opacity`**：动 `top/left/width/height` 触发布局与整层重绘。
🔴 **原生光标从不隐藏**：自定义光标是叠加层，不是替代。JS 崩溃/未加载时光标照常可用。

---

## 五、移动端与可达性

| 项 | 实测 | 状态 |
|---|---|---|
| 横向溢出 | 7/7 路由 `scrollWidth 390 = innerWidth 390` | **0px** |
| 抽屉定位 | `position:fixed`，滚动到 2200px 时 `y=80`、高 732、18/18 链接可见 | 已修（原 y=-3638 落在视口外） |
| 抽屉语义 | `role="dialog"` + `aria-modal="true"` + 遮罩可点关闭 | 已修 |
| 焦点指示器 | `outline:none` 且无替代环 = **0**；双环 + 激活态改墨色后 ≥3:1 | 已修（原 28 条 <3:1） |
| 触控目标 <44px | **277 / 284（97.5%）** | **未修**，见下 |

**触控目标的诚实结论**：WCAG 2.2 的 2.5.8 是 AA 级，要求 **24×24 CSS px**；44×44 是 AAA 级（2.5.5）。
本仓实测：顶栏图标按钮 36×36、滑块轨道 144×16、开关 44×24 的**轨道**。
- 按 **AA（24px）**判：36×36 与 44×24 都过；滑块 16px 高不过，但它有外围点击区（label 包裹），需复核。
- 按 **AAA（44px）**判：97.5% 不过。

这是**已知缺口，不是已修复**。`/console/appearance` 一页占 248 条（它是 12 个分组的设置页，天然密集）。
修它要么放大控件（设置页会变得更长），要么给每个控件包 44px 隐形命中区（不影响视觉）。
**需用户裁定按 AA 还是 AAA 收口**。

---

## 六、反模式清单（每条都有门在执法）

| 禁止 | 理由 | 执法者 |
|---|---|---|
| CSS 里写裸 `#rrggbb` | 值册必须是色/长度/字体栈 | 版式宪法 ⑩ |
| CSS 里写 `url()` | 防背景图夹带远端资源 | 同上 |
| JS 里 `setProperty('--x')` / `cssText` 拼变量 / `style['--x']` | 变量写入必须走唯一通道 `apply.ts:51` | 版式宪法 V2–V4 |
| 文字用 `background-clip:text` 虹彩铺满正文 | 用户裁定：文本不需要辉光，虹彩只做描边 | 人工 + 该门族 |
| 同一元素叠两层玻璃类 | 同一像素采样两次 | `glass-budget.mjs` |
| `infinite` 动画漏停播名单 | 关掉动效后仍在跑 | `test_webui_motion_switch.py` |
| Tailwind 方括号任意值（函数形） | 防止样式散落成字符串 | 版式宪法 ⑧′（A2–A8 之外全拒） |
| `animation-duration: 0.01ms` 当停播 | 对 infinite 是**加速**不是停止 | 人工 + 停播名单门 |

---

## 七、复跑清单（一条一条，可直接粘贴）

```bash
cd /c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot/webui

npm run lint:layout                     # 版式宪法 196/196
node scripts/glass-budget.mjs           # 玻璃层数/blur/嵌套/降级
node scripts/token-dump.mjs             # design-tokens.json 与真身无漂移
npm test                                # 523 pass / 0 fail
npx tsc -b                              # 9 errors（全部存量）
npm run build                           # rc=0

rm -rf .chrome-profile.ct && node scripts/contrast-audit.mjs tmp/w18b-contrast3.json
rm -rf .chrome-profile.ct-dark && node tmp/contrast-dark.mjs tmp/w18b-dark.json
rm -rf .chrome-profile.grad && node scripts/gradient-text-contrast.mjs tmp/w18b-light.json
rm -rf .chrome-profile.grad && node scripts/gradient-text-contrast.mjs tmp/w18b-dark.json
node scripts/shoot.mjs tmp/w18-anims.json            # data-motion=off 应 running=0
node scripts/shoot.mjs tmp/w18b-drawer.json          # 抽屉 y=80 / position=fixed
```

---

## 八、仍未定的三个参数（需用户裁定）

| # | 项 | 选项 | 影响 |
|---|---|---|---|
| 1 | 触控目标按 **AA(24px)** 还是 **AAA(44px)** 收口 | AA：只修滑块 / AAA：全部包 44px 隐形命中区 | AAA 会让设置页显著变长或加一层不可见点击区 |
| 2 | 玻璃通透度是否还要提高 | 当前 mica 90%/86%，往下每降 2% 需重跑对比度门 | 降到 80% 以下时 `--muted-foreground` 会重新跌破 4.5:1 |
| 3 | 「动态油壶渐变色」原意 | 现按**油膜虹彩**执行 | 若原意是机油壶，需重做视觉，不是调参 |

# F11 · 可量化视觉正确性审计（对比度 / 色对 / 字号可读性 / 主题矩阵）

> 席位：F11（前端视觉量化审计，只读）。**快照声明：`date` 实跑 = `Sat Sep 19 17:10:14 2026`**；审读窗口 16:32–17:10。
> 权限纪律：除本文件外**零修改**。一切实验脚本与中间产物只落 `%TEMP%\f11\`（未进源码树）；未跑 `npm install`/`npm run build`/浏览器/服务/端口；未碰 `webui/dist`、`node_modules` 写操作、`personas/`、`.env`、`ChatBot_Runtime/`、`ChatBot_Archive/`、`data/`、`qx.json`；无 git 写操作。
> 树卫生自检：`find plugins/.../card_render -name __pycache__ -o -name '*.pyc'` → **空**；本席直跑解释器全程带 `PYTHONDONTWRITEBYTECODE=1`。

## 0. 在飞证据与坐标漂移声明（必读）

- `git rev-parse --short HEAD` = **`56d1461`**（2026-09-15）；`git status --porcelain webui` = **`?? webui/`**（整棵未跟踪）。与 F5/F9 席口径一致。
- **审读期间同域并发席在改 webui**（`ls --time-style=+%H:%M:%S` 实取）：

| 文件 | mtime | 对本席的影响 |
|---|---|---|
| `webui/src/index.css` | 02:54:43 | **本席主证据源，审读期内未变**，行号可信 |
| `webui/src/components/ui/card.tsx` | **16:46:37** | `CardTitle` 基类 `leading-none` **已被并发席移除**并留注释（见 §6.3）——本席**不重复记账**，只记同类残余 |
| `webui/src/components/patterns/patterns.tsx` | **16:34:18** | `TONE_TEXT` 行号整体 −1（现为 100–107，非早期读的 101–108） |
| `webui/src/pages/dashboard.tsx` | 16:34:19 | 引用锚已按 17:03 复核 |
| `webui/src/pages/logs.tsx` | 16:37:49 | 引用锚已按 17:04 复核（aria-live 现为 :299，非 :287） |
| `webui/src/components/settings/settings-dialog.tsx` | 16:37:50 | 已复核 |
| `webui/src/components/layout/error-boundary.tsx` | 16:41 | **审读期新建文件**，本席快照后加入，未逐行审读（如实披露） |
| `webui/src/pages/tokens.tsx` | **17:01:28** | 本席 17:03 复核：`fontFamily:'monospace'`(:151)、`<Legend />`(:159)、`contentStyle`(:156) **三处锚仍在** |

**因此本台账每条都带「锚点字符串」——改代码时按字符串定位，不要按行号。**

## 1. 方法：色对提取 + 程序化实算（含引擎自校验）

### 1.1 可复跑命令

```bash
# 引擎 + 色对表（266 行输出）
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 \
  ../ChatBot_Runtime/venv/Scripts/python.exe "$TEMP/f11/pairs2.py" > "$TEMP/f11/out_pairs.md"
# 值册对表（中央统一性）
... "$TEMP/f11/central.py"      > "$TEMP/f11/out_central.md"
# 建议值求解 / 建议值复算
... "$TEMP/f11/final_solve.py"  | tee "$TEMP/f11/out_final.md"
... "$TEMP/f11/verify_fix.py"   | tee "$TEMP/f11/out_verify.md"
# 主题变量集合 diff
... "$TEMP/f11/themadiff.py"    > "$TEMP/f11/out_theme.md"
# 既有机器门现状（只读扫描）
cd webui && node scripts/layout-constitution.mjs   # → 见 §11
```

### 1.2 引擎要点

- 直接从 `webui/src/index.css` **正则抽块**（`:root` 3 块 / `.dark` 2 块 / `@theme inline` 2 块），`var()` 递归展开，**不手工录 token 表**（避免抄错）。
- `oklch()` → OKLab → 线性 sRGB → 编码 sRGB，超域按浏览器现行做法 **clip** 并标 `sRGB 外(clip)`。
- `color-mix(in srgb, A p%, B)` 按 CSS 规范 **预乘 alpha 插值后反预乘**；`transparent` 视作 `(0,0,0,a=0)`。半透明色再用 `layer()` 合成到不透明父底。
- **合成链层数 = 真实 DOM 层数**：章底（tone 14%）→ 卡底（`--card`）→ 页底；`opacity-x` 按整件（前景与底一起）向父底降透明复算，这正是浏览器行为。
- 相对亮度走 WCAG 定义（编码域反伽马 → 线性 → 0.2126/0.7152/0.0722）。
- 阈值三分类：`text` = 1.4.3（4.5，大字 24px 或 ≥18.66px+700 时 3.0）；`ui` = 1.4.11 非文本（3.0，**仅对「识别组件/状态所必需」计入**）；`decor` = 纯装饰，**记录不计分**。

### 1.3 引擎正确性实证（9 条独立对照，全部字节等值）

`index.css` 注释里自带十六进制出处，用本引擎反算与之对表：

```
--primary(亮)   -> #318ce7   注释 #318ce7    OK
--wash-mist     -> #f4f5f6   注释 #f4f5f6    OK
--sk-purple     -> #824dcb   注释 #824dcb    OK
--sk-deep       -> #3950ac   注释 #3950ac    OK
--chart-4       -> #699ed3   注释 #699ed3    OK
--background(暗)-> #1c2031   注释 #1c2031    OK
--card(暗)      -> #24293d   注释 #24293d    OK
--primary(暗)   -> #4999e9   注释 #4999e9    OK
--success(亮)   -> #2e9e6b   注释 #2e9e6b    OK
```

**另加跨域实证**：直接 `importlib` 载入真身值册并跑 `derive_wash_tokens('#318ce7')`：

```
{'wash_1': '#d9e0e7', 'wash_2': '#dfdae7', 'wash_3': '#dcdfea', 'wash_mist': '#f4f5f6'}
```
与 `index.css:19-22` 注释四值**逐字符一致** → 洗色四 token 确实来自中央派生，**这条统一链是通的**（也说明 §5 的差集法可作为常驻门）。

---

## 2. 色对对比度实算表（全量 266 行）

133 组色对 × 亮/暗两态。列义：前景/背景为**逐层合成后的实际显示色**（不是 token 名义值）。

```
$ PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe "$TEMP/f11/pairs2.py"
```

| # | 组 | 色对 | 前景(合成后) | 背景(合成后) | 对比度 | 阈值 | 判据 | 判定 | 主题 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | A 正文 | foreground / background 页面正文 | #242a42 | #f4f5f6 | **12.97** | 4.5 | text | PASS | 亮 |
| 2 | A 正文 | card-foreground / card 卡内正文 | #242a42 | #fafbfc | **13.67** | 4.5 | text | PASS | 亮 |
| 3 | A 正文 | popover-foreground / popover 弹层 | #242a42 | #fcfcfd | **13.79** | 4.5 | text | PASS | 亮 |
| 4 | A 正文 | muted-foreground / background 次要文字 | #5a617c | #f4f5f6 | **5.61** | 4.5 | text | PASS | 亮 |
| 5 | A 正文 | muted-foreground / card 卡内次要 | #5a617c | #fafbfc | **5.91** | 4.5 | text | PASS | 亮 |
| 6 | A 正文 | muted-foreground / card 13px 正文次要 | #5a617c | #fafbfc | **5.91** | 4.5 | text | PASS | 亮 |
| 7 | A 正文 | muted-foreground / muted 面板 | #5a617c | #dcdfea | **4.60** | 4.5 | text | PASS | 亮 |
| 8 | A 正文 | muted-foreground / sidebar 导航未选中 | #5a617c | #fafbfc | **5.91** | 4.5 | text | PASS | 亮 |
| 9 | A 正文 | muted-foreground / sidebar 页脚 | #5a617c | #fafbfc | **5.91** | 4.5 | text | PASS | 亮 |
| 10 | A 正文 | sidebar-foreground / sidebar | #242a42 | #fafbfc | **13.67** | 4.5 | text | PASS | 亮 |
| 11 | A 正文 | muted-foreground / card StatCard 标签(14/600) | #5a617c | #fafbfc | **5.91** | 4.5 | text | PASS | 亮 |
| 12 | A 正文 | muted-foreground / 顶栏 bg-background/80(backdrop-blur) | #5a617c | #f4f5f6 | **5.61** | - | manual | 需目验 | 亮 |
| 13 | A 正文 | foreground / card fs-num 30px | #242a42 | #fafbfc | **13.67** | 3.0 | text | PASS | 亮 |
| 14 | A 正文 | foreground / background fs-page 18px | #242a42 | #f4f5f6 | **12.97** | 4.5 | text | PASS | 亮 |
| 15 | A 正文 | foreground / card fs-card 14px 卡标题 | #242a42 | #fafbfc | **13.67** | 4.5 | text | PASS | 亮 |
| 16 | A 正文 | foreground / card fs-caption 12px 日志正文 | #242a42 | #fafbfc | **13.67** | 4.5 | text | PASS | 亮 |
| 17 | A 正文 | muted-foreground / card 12px 日志时间戳列 | #5a617c | #fafbfc | **5.91** | 4.5 | text | PASS | 亮 |
| 18 | A 正文 | muted-foreground / background 设置面板提示 | #5a617c | #f4f5f6 | **5.61** | 4.5 | text | PASS | 亮 |
| 19 | A 正文 | foreground / background 设置面板 label | #242a42 | #f4f5f6 | **12.97** | 4.5 | text | PASS | 亮 |
| 20 | A 正文 | muted-foreground / background 输入 placeholder | #5a617c | #f4f5f6 | **5.61** | 4.5 | text | PASS | 亮 |
| 21 | B 主色 | primary-foreground / primary 主按钮 13px | #ffffff | #318ce7 | **3.48** | 4.5 | text | **FAIL** | 亮 |
| 22 | B 主色 | primary-foreground / primary hover /90 | #ffffff | #4597e9 | **3.06** | 4.5 | text | **FAIL** | 亮 |
| 23 | B 主色 | primary-foreground / primary Badge 12px | #ffffff | #318ce7 | **3.48** | 4.5 | text | **FAIL** | 亮 |
| 24 | B 主色 | primary-foreground / primary 页签 12px | #ffffff | #318ce7 | **3.48** | 4.5 | text | **FAIL** | 亮 |
| 25 | B 主色 | primary-foreground / primary 图标底(logo) | #ffffff | #318ce7 | **3.48** | 3.0 | ui | PASS | 亮 |
| 26 | B 主色 | primary / card 链接与展开按钮 | #318ce7 | #fafbfc | **3.36** | 4.5 | text | **FAIL** | 亮 |
| 27 | B 主色 | primary / sidebar 子导航激活 | #318ce7 | #fafbfc | **3.36** | 4.5 | text | **FAIL** | 亮 |
| 28 | B 主色 | primary / card 好感度正值 | #318ce7 | #fafbfc | **3.36** | 4.5 | text | **FAIL** | 亮 |
| 29 | B 主色 | secondary-foreground / secondary Badge | #3950ac | #d9e0e7 | **5.40** | 4.5 | text | PASS | 亮 |
| 30 | B 主色 | secondary-foreground / secondary 按钮 | #3950ac | #d9e0e7 | **5.40** | 4.5 | text | PASS | 亮 |
| 31 | B 主色 | secondary-foreground / secondary hover/90 | #3950ac | #dce3e9 | **5.54** | 4.5 | text | PASS | 亮 |
| 32 | B 主色 | accent-foreground / accent hover | #683da2 | #dfdae7 | **5.50** | 4.5 | text | PASS | 亮 |
| 33 | B 主色 | accent-foreground / accent Badge outline hover | #683da2 | #dfdae7 | **5.50** | 4.5 | text | PASS | 亮 |
| 34 | B 主色 | muted-foreground / accent hover(未覆写文字色的 ghost) | #5a617c | #dfdae7 | **4.46** | 4.5 | text | **FAIL** | 亮 |
| 35 | B 主色 | destructive-foreground / destructive 徽章 | #fafafa | #ee3439 | **3.88** | 4.5 | text | **FAIL** | 亮 |
| 36 | B 主色 | destructive-foreground / destructive/90 hover | #fafafa | #ef484c | **3.53** | 4.5 | text | **FAIL** | 亮 |
| 37 | B 主色 | destructive-foreground / destructive/60 暗态 | #fafafa | #f38487 | **2.38** | 4.5 | text | **FAIL** | 亮 |
| 38 | B 主色 | success-foreground / success 徽章 | #fafafa | #2e9e6b | **3.23** | 4.5 | text | **FAIL** | 亮 |
| 39 | B 主色 | success-foreground / success hover/90 | #fafafa | #42a77a | **2.85** | 4.5 | text | **FAIL** | 亮 |
| 40 | B 主色 | destructive / card 错误图标 size-8 | #ee3439 | #fafbfc | **3.92** | 3.0 | ui | PASS | 亮 |
| 41 | B 主色 | destructive / background 校验错误文字 | #ee3439 | #f4f5f6 | **3.72** | 4.5 | text | **FAIL** | 亮 |
| 42 | C tone章 | tone-good / tone-face-good over card | #009965 | #d7ede7 | **3.00** | 4.5 | text | **FAIL** | 亮 |
| 43 | C tone章 | tone-warn / tone-face-warn over card | #e27100 | #f7e8d9 | **2.66** | 4.5 | text | **FAIL** | 亮 |
| 44 | C tone章 | tone-bad / tone-face-bad over card | #e7000b | #f7d8da | **3.59** | 4.5 | text | **FAIL** | 亮 |
| 45 | C tone章 | tone-info / tone-face-info over card | #0069a8 | #dceaf2 | **4.75** | 4.5 | text | PASS | 亮 |
| 46 | C tone章 | tone-purple / tone-face-purple over card | #824dcb | #e9e3f5 | **4.33** | 4.5 | text | **FAIL** | 亮 |
| 47 | C tone章 | tone-magenta / tone-face-magenta over card | #bd24da | #f2ddf7 | **3.71** | 4.5 | text | **FAIL** | 亮 |
| 48 | C tone章 | primary / bg-primary/15 brand 章 | #318ce7 | #dceaf9 | **2.85** | 4.5 | text | **FAIL** | 亮 |
| 49 | C tone章 | muted-foreground / tone-face-flat over card | #5a617c | #e7e9ed | **5.02** | 4.5 | text | PASS | 亮 |
| 50 | C tone章 | tone-good / card 纯图标 size-4 | #009965 | #fafbfc | **3.54** | 3.0 | ui | PASS | 亮 |
| 51 | C tone章 | tone-purple / card 纯图标 size-4 | #824dcb | #fafbfc | **5.25** | 3.0 | ui | PASS | 亮 |
| 52 | C tone章 | tone-info / card 纯图标 size-4 | #0069a8 | #fafbfc | **5.66** | 3.0 | ui | PASS | 亮 |
| 53 | C tone章 | tone-warn / card 小图标 size-4 | #e27100 | #fafbfc | **3.09** | 3.0 | ui | PASS | 亮 |
| 54 | C tone章 | tone-warn / card 12px 文字 | #e27100 | #fafbfc | **3.09** | 4.5 | text | **FAIL** | 亮 |
| 55 | C tone章 | tone-bad / card 12px 文字 | #e7000b | #fafbfc | **4.60** | 4.5 | text | PASS | 亮 |
| 56 | C tone章 | tone-info / card 12px 文字 | #0069a8 | #fafbfc | **5.66** | 4.5 | text | PASS | 亮 |
| 57 | C tone章 | tone-bad / card 12px 文字(×连败章) | #e7000b | #f7d8da | **3.59** | 4.5 | text | **FAIL** | 亮 |
| 58 | C tone章 | foreground / tone-face-warn over background 缺口横幅 | #242a42 | #f2e3d4 | **11.22** | 4.5 | text | PASS | 亮 |
| 59 | C tone章 | foreground / tone-face-bad over background 鉴权横幅 | #242a42 | #f2d3d5 | **10.14** | 4.5 | text | PASS | 亮 |
| 60 | C tone章 | tone-warn / background 横幅内图标 | #e27100 | #f4f5f6 | **2.93** | 3.0 | ui | **FAIL** | 亮 |
| 61 | C tone章 | tone-warn / background 横幅描边 | #e27100 | #f4f5f6 | **2.93** | 3.0 | ui | **FAIL** | 亮 |
| 62 | C tone章 | tone-bad / background 横幅描边 | #e7000b | #f4f5f6 | **4.37** | 3.0 | ui | PASS | 亮 |
| 63 | D 图表 | muted-foreground / card 轴刻度文字 12px | #5a617c | #fafbfc | **5.91** | 4.5 | text | PASS | 亮 |
| 64 | D 图表 | card-foreground / card Tooltip 标题 | #242a42 | #fafbfc | **13.67** | 4.5 | text | PASS | 亮 |
| 65 | D 图表 | chart-1 / card Tooltip 项文字(entry.color) | #318ce7 | #fafbfc | **3.36** | 4.5 | text | **FAIL** | 亮 |
| 66 | D 图表 | chart-1 / card Legend 标签(entry.color) | #318ce7 | #fafbfc | **3.36** | 4.5 | text | **FAIL** | 亮 |
| 67 | D 图表 | chart-2 / card Tooltip 项文字(entry.color) | #824dcb | #fafbfc | **5.25** | 4.5 | text | PASS | 亮 |
| 68 | D 图表 | chart-2 / card Legend 标签(entry.color) | #824dcb | #fafbfc | **5.25** | 4.5 | text | PASS | 亮 |
| 69 | D 图表 | chart-3 / card Tooltip 项文字(entry.color) | #3950ac | #fafbfc | **6.95** | 4.5 | text | PASS | 亮 |
| 70 | D 图表 | chart-3 / card Legend 标签(entry.color) | #3950ac | #fafbfc | **6.95** | 4.5 | text | PASS | 亮 |
| 71 | D 图表 | chart-4 / card Tooltip 项文字(entry.color) | #699ed3 | #fafbfc | **2.74** | 4.5 | text | **FAIL** | 亮 |
| 72 | D 图表 | chart-4 / card Legend 标签(entry.color) | #699ed3 | #fafbfc | **2.74** | 4.5 | text | **FAIL** | 亮 |
| 73 | D 图表 | chart-5 / card Tooltip 项文字(entry.color) | #a789d2 | #fafbfc | **2.84** | 4.5 | text | **FAIL** | 亮 |
| 74 | D 图表 | chart-5 / card Legend 标签(entry.color) | #a789d2 | #fafbfc | **2.84** | 4.5 | text | **FAIL** | 亮 |
| 75 | D 图表 | chart-6 / card Tooltip 项文字(entry.color) | #6b7dc7 | #fafbfc | **3.76** | 4.5 | text | **FAIL** | 亮 |
| 76 | D 图表 | chart-6 / card Legend 标签(entry.color) | #6b7dc7 | #fafbfc | **3.76** | 4.5 | text | **FAIL** | 亮 |
| 77 | D 图表 | primary / card 折线 Tooltip 项文字 | #318ce7 | #fafbfc | **3.36** | 4.5 | text | **FAIL** | 亮 |
| 78 | D 图表 | muted-foreground / card 轴杆 stroke | #5a617c | #fafbfc | **5.91** | - | decor | —(装饰) | 亮 |
| 79 | D 图表 | border / card 网格线 | #d6dbe1 | #fafbfc | **1.35** | - | decor | —(装饰) | 亮 |
| 80 | D 图表 | primary / card 折线本体 2px | #318ce7 | #fafbfc | **3.36** | 3.0 | ui | PASS | 亮 |
| 81 | D 图表 | chart-1 / card 堆叠条本体 | #318ce7 | #fafbfc | **3.36** | 3.0 | ui | PASS | 亮 |
| 82 | D 图表 | chart-4 / card 堆叠条本体(最淡) | #699ed3 | #fafbfc | **2.74** | 3.0 | ui | **FAIL** | 亮 |
| 83 | D 图表 | chart-1 vs chart-2 序列可辨 | #318ce7 | #824dcb | **1.56** | 3.0 | ui | **FAIL** | 亮 |
| 84 | D 图表 | chart-2 vs chart-3 序列可辨 | #824dcb | #3950ac | **1.32** | 3.0 | ui | **FAIL** | 亮 |
| 85 | D 图表 | chart-3 vs chart-4 序列可辨 | #3950ac | #699ed3 | **2.54** | 3.0 | ui | **FAIL** | 亮 |
| 86 | D 图表 | chart-1 vs chart-4 序列可辨 | #318ce7 | #699ed3 | **1.23** | 3.0 | ui | **FAIL** | 亮 |
| 87 | D 图表 | chart-2 vs chart-5 序列可辨 | #824dcb | #a789d2 | **1.85** | 3.0 | ui | **FAIL** | 亮 |
| 88 | D 图表 | chart-3 vs chart-6 序列可辨 | #3950ac | #6b7dc7 | **1.85** | 3.0 | ui | **FAIL** | 亮 |
| 89 | D 图表 | chart-1 vs chart-3 序列可辨 | #318ce7 | #3950ac | **2.07** | 3.0 | ui | **FAIL** | 亮 |
| 90 | D 图表 | chart-4 vs chart-6 序列可辨 | #699ed3 | #6b7dc7 | **1.38** | 3.0 | ui | **FAIL** | 亮 |
| 91 | D 图表 | chart-5 vs chart-6 序列可辨 | #a789d2 | #6b7dc7 | **1.33** | 3.0 | ui | **FAIL** | 亮 |
| 92 | D 图表 | chart-1 vs chart-6 序列可辨 | #318ce7 | #6b7dc7 | **1.12** | 3.0 | ui | **FAIL** | 亮 |
| 93 | D 图表 | chart-2 vs chart-4 序列可辨 | #824dcb | #699ed3 | **1.92** | 3.0 | ui | **FAIL** | 亮 |
| 94 | D 图表 | primary/70 条内填充 / accent 轨道 | #65a3e7 | #dfdae7 | **1.92** | 3.0 | ui | **FAIL** | 亮 |
| 95 | D 图表 | accent 轨道 / card 进度底 | #dfdae7 | #fafbfc | **1.33** | 3.0 | ui | **FAIL** | 亮 |
| 96 | D 图表 | foreground / card canvas 节点标签 12px | #242a42 | #fafbfc | **13.67** | 4.5 | text | PASS | 亮 |
| 97 | D 图表 | muted-foreground / card/80 画布浮层 | #5a617c | #fafbfc | **5.91** | - | manual | 需目验 | 亮 |
| 98 | D 图表 | muted-foreground / accent 骨架块 | #5a617c | #dfdae7 | **4.46** | - | decor | —(装饰) | 亮 |
| 99 | D 图表 | card-foreground / scrim(0.5) 遮罩下正文 | #242a42 | #7d7e7e | **3.46** | - | manual | 需目验 | 亮 |
| 100 | E 边框焦点 | border / card 卡片描边 | #d6dbe1 | #fafbfc | **1.35** | - | decor | —(装饰) | 亮 |
| 101 | E 边框焦点 | border / background 页面分隔线 | #d6dbe1 | #f4f5f6 | **1.28** | - | decor | —(装饰) | 亮 |
| 102 | E 边框焦点 | border / sidebar 侧栏右缘 | #d6dbe1 | #fafbfc | **1.35** | - | decor | —(装饰) | 亮 |
| 103 | E 边框焦点 | border / card 网格行分隔线 | #d6dbe1 | #fafbfc | **1.35** | - | decor | —(装饰) | 亮 |
| 104 | E 边框焦点 | border / background 滚动条滑块 | #d6dbe1 | #f4f5f6 | **1.28** | - | decor | —(装饰) | 亮 |
| 105 | E 边框焦点 | border / card 滚动条滑块 | #d6dbe1 | #fafbfc | **1.35** | - | decor | —(装饰) | 亮 |
| 106 | E 边框焦点 | input / card 输入框描边 | #d6dbe1 | #fafbfc | **1.35** | 3.0 | ui | **FAIL** | 亮 |
| 107 | E 边框焦点 | input / background 设置面板输入框描边 | #d6dbe1 | #f4f5f6 | **1.28** | 3.0 | ui | **FAIL** | 亮 |
| 108 | E 边框焦点 | select 描边 / background(日志筛选下拉) | #d6dbe1 | #f4f5f6 | **1.28** | 3.0 | ui | **FAIL** | 亮 |
| 109 | E 边框焦点 | ring / card 焦点环 50% alpha | #96c4f2 | #fafbfc | **1.78** | 3.0 | ui | **FAIL** | 亮 |
| 110 | E 边框焦点 | ring / primary 焦点环落在主按钮 | #318ce7 | #318ce7 | **1.00** | 3.0 | ui | **FAIL** | 亮 |
| 111 | E 边框焦点 | ring / secondary 焦点环落在次要按钮 | #85b6e7 | #d9e0e7 | **1.60** | 3.0 | ui | **FAIL** | 亮 |
| 112 | E 边框焦点 | ring / background 默认 outline 50% | #93c1ef | #f4f5f6 | **1.74** | 3.0 | ui | **FAIL** | 亮 |
| 113 | E 边框焦点 | ring / card 默认 outline(裸 button 在卡内) | #96c4f2 | #fafbfc | **1.78** | 3.0 | ui | **FAIL** | 亮 |
| 114 | E 边框焦点 | ring / sidebar 默认 outline | #96c4f2 | #fafbfc | **1.78** | 3.0 | ui | **FAIL** | 亮 |
| 115 | E 边框焦点 | ring(不透明) / card 焦点环对照(建议态) | #318ce7 | #fafbfc | **3.36** | 3.0 | ui | PASS | 亮 |
| 116 | F 降透明 | 分页按钮禁用整件 @50% | #aaaebc | #fafbfc | **2.14** | 4.5 | text | **FAIL** | 亮 |
| 117 | F 降透明 | 图谱类型隐藏章 @40% | #babdc9 | #f2f4f6 | **1.69** | 4.5 | text | **FAIL** | 亮 |
| 118 | F 降透明 | 知识库未启用章 @60% | #9a9faf | #eff0f3 | **2.32** | 4.5 | text | **FAIL** | 亮 |
| 119 | F 降透明 | 日志心跳副文字 opacity-80（good 章内） | #7a8096 | #def0eb | **3.33** | 4.5 | text | **FAIL** | 亮 |
| 120 | F 降透明 | ghost 按钮 disabled @50% | #8f939f | #fafbfc | **2.98** | 4.5 | text | **FAIL** | 亮 |
| 121 | F 降透明 | 禁用章整件 @50%（brand 激活章不可点） | #96c4f2 | #ebf3fb | **1.64** | 4.5 | text | **FAIL** | 亮 |
| 122 | G 容器 | foreground / muted/40 说明块标题 | #242a42 | #eef0f5 | **12.41** | 4.5 | text | PASS | 亮 |
| 123 | G 容器 | muted-foreground / muted/40 说明块正文 | #5a617c | #eef0f5 | **5.36** | 4.5 | text | PASS | 亮 |
| 124 | G 容器 | tone-warn / muted/40 说明块降级行 | #e27100 | #eef0f5 | **2.80** | 4.5 | text | **FAIL** | 亮 |
| 125 | G 容器 | muted-foreground / outline 徽章无边底 | #5a617c | #fafbfc | **5.91** | 4.5 | text | PASS | 亮 |
| 126 | G 容器 | foreground / outline 徽章（默认色） | #242a42 | #fafbfc | **13.67** | 4.5 | text | PASS | 亮 |
| 127 | G 容器 | sk-deep / wash-1 (= secondary 亮态) | #3950ac | #d9e0e7 | **5.40** | 4.5 | text | PASS | 亮 |
| 128 | G 容器 | sk-purple / wash-2 (= accent-foreground 亮态) | #824dcb | #dfdae7 | **3.96** | 4.5 | text | **FAIL** | 亮 |
| 129 | G 容器 | wash-1 / background 装饰面边界 | #d9e0e7 | #f4f5f6 | **1.22** | - | decor | —(装饰) | 亮 |
| 130 | G 容器 | wash-2 / background 装饰面边界 | #dfdae7 | #f4f5f6 | **1.26** | - | decor | —(装饰) | 亮 |
| 131 | G 容器 | wash-mist 页面底 / card 卡底分界 | #f4f5f6 | #fafbfc | **1.05** | - | decor | —(装饰) | 亮 |
| 132 | G 容器 | sidebar-primary-foreground / sidebar-primary | #ffffff | #318ce7 | **3.48** | 4.5 | text | **FAIL** | 亮 |
| 133 | G 容器 | sidebar-accent-foreground / sidebar-accent | #683da2 | #dfdae7 | **5.50** | 4.5 | text | PASS | 亮 |
| 1 | A 正文 | foreground / background 页面正文 | #ecedee | #1c2031 | **13.79** | 4.5 | text | PASS | 暗 |
| 2 | A 正文 | card-foreground / card 卡内正文 | #ecedee | #24293d | **12.27** | 4.5 | text | PASS | 暗 |
| 3 | A 正文 | popover-foreground / popover 弹层 | #ecedee | #282e43 | **11.49** | 4.5 | text | PASS | 暗 |
| 4 | A 正文 | muted-foreground / background 次要文字 | #b3b7bc | #1c2031 | **8.02** | 4.5 | text | PASS | 暗 |
| 5 | A 正文 | muted-foreground / card 卡内次要 | #b3b7bc | #24293d | **7.13** | 4.5 | text | PASS | 暗 |
| 6 | A 正文 | muted-foreground / card 13px 正文次要 | #b3b7bc | #24293d | **7.13** | 4.5 | text | PASS | 暗 |
| 7 | A 正文 | muted-foreground / muted 面板 | #b3b7bc | #2c2f3d | **6.60** | 4.5 | text | PASS | 暗 |
| 8 | A 正文 | muted-foreground / sidebar 导航未选中 | #b3b7bc | #202537 | **7.56** | 4.5 | text | PASS | 暗 |
| 9 | A 正文 | muted-foreground / sidebar 页脚 | #b3b7bc | #202537 | **7.56** | 4.5 | text | PASS | 暗 |
| 10 | A 正文 | sidebar-foreground / sidebar | #ecedee | #202537 | **13.00** | 4.5 | text | PASS | 暗 |
| 11 | A 正文 | muted-foreground / card StatCard 标签(14/600) | #b3b7bc | #24293d | **7.13** | 4.5 | text | PASS | 暗 |
| 12 | A 正文 | muted-foreground / 顶栏 bg-background/80(backdrop-blur) | #b3b7bc | #1c2031 | **8.02** | - | manual | 需目验 | 暗 |
| 13 | A 正文 | foreground / card fs-num 30px | #ecedee | #24293d | **12.27** | 3.0 | text | PASS | 暗 |
| 14 | A 正文 | foreground / background fs-page 18px | #ecedee | #1c2031 | **13.79** | 4.5 | text | PASS | 暗 |
| 15 | A 正文 | foreground / card fs-card 14px 卡标题 | #ecedee | #24293d | **12.27** | 4.5 | text | PASS | 暗 |
| 16 | A 正文 | foreground / card fs-caption 12px 日志正文 | #ecedee | #24293d | **12.27** | 4.5 | text | PASS | 暗 |
| 17 | A 正文 | muted-foreground / card 12px 日志时间戳列 | #b3b7bc | #24293d | **7.13** | 4.5 | text | PASS | 暗 |
| 18 | A 正文 | muted-foreground / background 设置面板提示 | #b3b7bc | #1c2031 | **8.02** | 4.5 | text | PASS | 暗 |
| 19 | A 正文 | foreground / background 设置面板 label | #ecedee | #1c2031 | **13.79** | 4.5 | text | PASS | 暗 |
| 20 | A 正文 | muted-foreground / background 输入 placeholder | #b3b7bc | #1c2031 | **8.02** | 4.5 | text | PASS | 暗 |
| 21 | B 主色 | primary-foreground / primary 主按钮 13px | #1d2135 | #4999e9 | **5.30** | 4.5 | text | PASS | 暗 |
| 22 | B 主色 | primary-foreground / primary hover /90 | #1d2135 | #458ed8 | **4.61** | 4.5 | text | PASS | 暗 |
| 23 | B 主色 | primary-foreground / primary Badge 12px | #1d2135 | #4999e9 | **5.30** | 4.5 | text | PASS | 暗 |
| 24 | B 主色 | primary-foreground / primary 页签 12px | #1d2135 | #4999e9 | **5.30** | 4.5 | text | PASS | 暗 |
| 25 | B 主色 | primary-foreground / primary 图标底(logo) | #1d2135 | #4999e9 | **5.30** | 3.0 | ui | PASS | 暗 |
| 26 | B 主色 | primary / card 链接与展开按钮 | #4999e9 | #24293d | **4.80** | 4.5 | text | PASS | 暗 |
| 27 | B 主色 | primary / sidebar 子导航激活 | #4999e9 | #202537 | **5.08** | 4.5 | text | PASS | 暗 |
| 28 | B 主色 | primary / card 好感度正值 | #4999e9 | #24293d | **4.80** | 4.5 | text | PASS | 暗 |
| 29 | B 主色 | secondary-foreground / secondary Badge | #ecedee | #2e3245 | **10.81** | 4.5 | text | PASS | 暗 |
| 30 | B 主色 | secondary-foreground / secondary 按钮 | #ecedee | #2e3245 | **10.81** | 4.5 | text | PASS | 暗 |
| 31 | B 主色 | secondary-foreground / secondary hover/90 | #ecedee | #2d3144 | **10.95** | 4.5 | text | PASS | 暗 |
| 32 | B 主色 | accent-foreground / accent hover | #ecedee | #433a50 | **9.15** | 4.5 | text | PASS | 暗 |
| 33 | B 主色 | accent-foreground / accent Badge outline hover | #ecedee | #433a50 | **9.15** | 4.5 | text | PASS | 暗 |
| 34 | B 主色 | muted-foreground / accent hover(未覆写文字色的 ghost) | #b3b7bc | #433a50 | **5.32** | 4.5 | text | PASS | 暗 |
| 35 | B 主色 | destructive-foreground / destructive 徽章 | #fafafa | #fb575c | **3.03** | 4.5 | text | **FAIL** | 暗 |
| 36 | B 主色 | destructive-foreground / destructive/90 hover | #fafafa | #e65259 | **3.51** | 4.5 | text | **FAIL** | 暗 |
| 37 | B 主色 | destructive-foreground / destructive/60 暗态 | #fafafa | #a54550 | **5.64** | 4.5 | text | PASS | 暗 |
| 38 | B 主色 | success-foreground / success 徽章 | #fafafa | #4ca779 | **2.82** | 4.5 | text | **FAIL** | 暗 |
| 39 | B 主色 | success-foreground / success hover/90 | #fafafa | #489b73 | **3.25** | 4.5 | text | **FAIL** | 暗 |
| 40 | B 主色 | destructive / card 错误图标 size-8 | #fb575c | #24293d | **4.54** | 3.0 | ui | PASS | 暗 |
| 41 | B 主色 | destructive / background 校验错误文字 | #fb575c | #1c2031 | **5.11** | 4.5 | text | PASS | 暗 |
| 42 | C tone章 | tone-good / tone-face-good over card | #00d492 | #1f4149 | **5.68** | 4.5 | text | PASS | 暗 |
| 43 | C tone章 | tone-warn / tone-face-warn over card | #e9c16c | #403e44 | **6.16** | 4.5 | text | PASS | 暗 |
| 44 | C tone章 | tone-bad / tone-face-bad over card | #ffa2a3 | #433a4b | **5.62** | 4.5 | text | PASS | 暗 |
| 45 | C tone章 | tone-info / tone-face-info over card | #74d4ff | #2e3e54 | **6.55** | 4.5 | text | PASS | 暗 |
| 46 | C tone章 | tone-purple / tone-face-purple over card | #b49ad8 | #383953 | **4.55** | 4.5 | text | PASS | 暗 |
| 47 | C tone章 | tone-magenta / tone-face-magenta over card | #ffa9ff | #433b58 | **6.17** | 4.5 | text | PASS | 暗 |
| 48 | C tone章 | primary / bg-primary/15 brand 章 | #4999e9 | #2a3a57 | **3.82** | 4.5 | text | **FAIL** | 暗 |
| 49 | C tone章 | muted-foreground / tone-face-flat over card | #b3b7bc | #353a4c | **5.59** | 4.5 | text | PASS | 暗 |
| 50 | C tone章 | tone-good / card 纯图标 size-4 | #00d492 | #24293d | **7.43** | 3.0 | ui | PASS | 暗 |
| 51 | C tone章 | tone-purple / card 纯图标 size-4 | #b49ad8 | #24293d | **5.85** | 3.0 | ui | PASS | 暗 |
| 52 | C tone章 | tone-info / card 纯图标 size-4 | #74d4ff | #24293d | **8.63** | 3.0 | ui | PASS | 暗 |
| 53 | C tone章 | tone-warn / card 小图标 size-4 | #e9c16c | #24293d | **8.41** | 3.0 | ui | PASS | 暗 |
| 54 | C tone章 | tone-warn / card 12px 文字 | #e9c16c | #24293d | **8.41** | 4.5 | text | PASS | 暗 |
| 55 | C tone章 | tone-bad / card 12px 文字 | #ffa2a3 | #24293d | **7.48** | 4.5 | text | PASS | 暗 |
| 56 | C tone章 | tone-info / card 12px 文字 | #74d4ff | #24293d | **8.63** | 4.5 | text | PASS | 暗 |
| 57 | C tone章 | tone-bad / card 12px 文字(×连败章) | #ffa2a3 | #433a4b | **5.62** | 4.5 | text | PASS | 暗 |
| 58 | C tone章 | foreground / tone-face-warn over background 缺口横幅 | #ecedee | #393739 | **10.14** | 4.5 | text | PASS | 暗 |
| 59 | C tone章 | foreground / tone-face-bad over background 鉴权横幅 | #ecedee | #3c3241 | **10.39** | 4.5 | text | PASS | 暗 |
| 60 | C tone章 | tone-warn / background 横幅内图标 | #e9c16c | #1c2031 | **9.45** | 3.0 | ui | PASS | 暗 |
| 61 | C tone章 | tone-warn / background 横幅描边 | #e9c16c | #1c2031 | **9.45** | 3.0 | ui | PASS | 暗 |
| 62 | C tone章 | tone-bad / background 横幅描边 | #ffa2a3 | #1c2031 | **8.41** | 3.0 | ui | PASS | 暗 |
| 63 | D 图表 | muted-foreground / card 轴刻度文字 12px | #b3b7bc | #24293d | **7.13** | 4.5 | text | PASS | 暗 |
| 64 | D 图表 | card-foreground / card Tooltip 标题 | #ecedee | #24293d | **12.27** | 4.5 | text | PASS | 暗 |
| 65 | D 图表 | chart-1 / card Tooltip 项文字(entry.color) | #64a8ed | #24293d | **5.72** | 4.5 | text | PASS | 暗 |
| 66 | D 图表 | chart-1 / card Legend 标签(entry.color) | #64a8ed | #24293d | **5.72** | 4.5 | text | PASS | 暗 |
| 67 | D 图表 | chart-2 / card Tooltip 项文字(entry.color) | #b49ad8 | #24293d | **5.85** | 4.5 | text | PASS | 暗 |
| 68 | D 图表 | chart-2 / card Legend 标签(entry.color) | #b49ad8 | #24293d | **5.85** | 4.5 | text | PASS | 暗 |
| 69 | D 图表 | chart-3 / card Tooltip 项文字(entry.color) | #8594d1 | #24293d | **4.89** | 4.5 | text | PASS | 暗 |
| 70 | D 图表 | chart-3 / card Legend 标签(entry.color) | #8594d1 | #24293d | **4.89** | 4.5 | text | PASS | 暗 |
| 71 | D 图表 | chart-4 / card Tooltip 项文字(entry.color) | #7facd9 | #24293d | **6.02** | 4.5 | text | PASS | 暗 |
| 72 | D 图表 | chart-4 / card Legend 标签(entry.color) | #7facd9 | #24293d | **6.02** | 4.5 | text | PASS | 暗 |
| 73 | D 图表 | chart-5 / card Tooltip 项文字(entry.color) | #824dcb | #24293d | **2.65** | 4.5 | text | **FAIL** | 暗 |
| 74 | D 图表 | chart-5 / card Legend 标签(entry.color) | #824dcb | #24293d | **2.65** | 4.5 | text | **FAIL** | 暗 |
| 75 | D 图表 | chart-6 / card Tooltip 项文字(entry.color) | #3950ac | #24293d | **2.00** | 4.5 | text | **FAIL** | 暗 |
| 76 | D 图表 | chart-6 / card Legend 标签(entry.color) | #3950ac | #24293d | **2.00** | 4.5 | text | **FAIL** | 暗 |
| 77 | D 图表 | primary / card 折线 Tooltip 项文字 | #4999e9 | #24293d | **4.80** | 4.5 | text | PASS | 暗 |
| 78 | D 图表 | muted-foreground / card 轴杆 stroke | #b3b7bc | #24293d | **7.13** | - | decor | —(装饰) | 暗 |
| 79 | D 图表 | border / card 网格线 | #434756 | #24293d | **1.56** | - | decor | —(装饰) | 暗 |
| 80 | D 图表 | primary / card 折线本体 2px | #4999e9 | #24293d | **4.80** | 3.0 | ui | PASS | 暗 |
| 81 | D 图表 | chart-1 / card 堆叠条本体 | #64a8ed | #24293d | **5.72** | 3.0 | ui | PASS | 暗 |
| 82 | D 图表 | chart-4 / card 堆叠条本体(最淡) | #7facd9 | #24293d | **6.02** | 3.0 | ui | PASS | 暗 |
| 83 | D 图表 | chart-1 vs chart-2 序列可辨 | #64a8ed | #b49ad8 | **1.02** | 3.0 | ui | **FAIL** | 暗 |
| 84 | D 图表 | chart-2 vs chart-3 序列可辨 | #b49ad8 | #8594d1 | **1.20** | 3.0 | ui | **FAIL** | 暗 |
| 85 | D 图表 | chart-3 vs chart-4 序列可辨 | #8594d1 | #7facd9 | **1.23** | 3.0 | ui | **FAIL** | 暗 |
| 86 | D 图表 | chart-1 vs chart-4 序列可辨 | #64a8ed | #7facd9 | **1.05** | 3.0 | ui | **FAIL** | 暗 |
| 87 | D 图表 | chart-2 vs chart-5 序列可辨 | #b49ad8 | #824dcb | **2.21** | 3.0 | ui | **FAIL** | 暗 |
| 88 | D 图表 | chart-3 vs chart-6 序列可辨 | #8594d1 | #3950ac | **2.45** | 3.0 | ui | **FAIL** | 暗 |
| 89 | D 图表 | chart-1 vs chart-3 序列可辨 | #64a8ed | #8594d1 | **1.17** | 3.0 | ui | **FAIL** | 暗 |
| 90 | D 图表 | chart-4 vs chart-6 序列可辨 | #7facd9 | #3950ac | **3.02** | 3.0 | ui | PASS | 暗 |
| 91 | D 图表 | chart-5 vs chart-6 序列可辨 | #824dcb | #3950ac | **1.32** | 3.0 | ui | **FAIL** | 暗 |
| 92 | D 图表 | chart-1 vs chart-6 序列可辨 | #64a8ed | #3950ac | **2.86** | 3.0 | ui | **FAIL** | 暗 |
| 93 | D 图表 | chart-2 vs chart-4 序列可辨 | #b49ad8 | #7facd9 | **1.03** | 3.0 | ui | **FAIL** | 暗 |
| 94 | D 图表 | primary/70 条内填充 / accent 轨道 | #477cbb | #433a50 | **2.49** | 3.0 | ui | **FAIL** | 暗 |
| 95 | D 图表 | accent 轨道 / card 进度底 | #433a50 | #24293d | **1.34** | 3.0 | ui | **FAIL** | 暗 |
| 96 | D 图表 | foreground / card canvas 节点标签 12px | #ecedee | #24293d | **12.27** | 4.5 | text | PASS | 暗 |
| 97 | D 图表 | muted-foreground / card/80 画布浮层 | #b3b7bc | #24293d | **7.13** | - | manual | 需目验 | 暗 |
| 98 | D 图表 | muted-foreground / accent 骨架块 | #b3b7bc | #433a50 | **5.32** | - | decor | —(装饰) | 暗 |
| 99 | D 图表 | card-foreground / scrim(0.5) 遮罩下正文 | #ecedee | #12151f | **15.61** | - | manual | 需目验 | 暗 |
| 100 | E 边框焦点 | border / card 卡片描边 | #434756 | #24293d | **1.56** | - | decor | —(装饰) | 暗 |
| 101 | E 边框焦点 | border / background 页面分隔线 | #434756 | #1c2031 | **1.75** | - | decor | —(装饰) | 暗 |
| 102 | E 边框焦点 | border / sidebar 侧栏右缘 | #434756 | #202537 | **1.65** | - | decor | —(装饰) | 暗 |
| 103 | E 边框焦点 | border / card 网格行分隔线 | #434756 | #24293d | **1.56** | - | decor | —(装饰) | 暗 |
| 104 | E 边框焦点 | border / background 滚动条滑块 | #434756 | #1c2031 | **1.75** | - | decor | —(装饰) | 暗 |
| 105 | E 边框焦点 | border / card 滚动条滑块 | #434756 | #24293d | **1.56** | - | decor | —(装饰) | 暗 |
| 106 | E 边框焦点 | input / card 输入框描边 | #434756 | #24293d | **1.56** | 3.0 | ui | **FAIL** | 暗 |
| 107 | E 边框焦点 | input / background 设置面板输入框描边 | #434756 | #1c2031 | **1.75** | 3.0 | ui | **FAIL** | 暗 |
| 108 | E 边框焦点 | select 描边 / background(日志筛选下拉) | #434756 | #1c2031 | **1.75** | 3.0 | ui | **FAIL** | 暗 |
| 109 | E 边框焦点 | ring / card 焦点环 50% alpha | #366193 | #24293d | **2.25** | 3.0 | ui | **FAIL** | 暗 |
| 110 | E 边框焦点 | ring / primary 焦点环落在主按钮 | #4999e9 | #4999e9 | **1.00** | 3.0 | ui | **FAIL** | 暗 |
| 111 | E 边框焦点 | ring / secondary 焦点环落在次要按钮 | #3b6597 | #2e3245 | **2.12** | 3.0 | ui | **FAIL** | 暗 |
| 112 | E 边框焦点 | ring / background 默认 outline 50% | #325c8d | #1c2031 | **2.36** | 3.0 | ui | **FAIL** | 暗 |
| 113 | E 边框焦点 | ring / card 默认 outline(裸 button 在卡内) | #366193 | #24293d | **2.25** | 3.0 | ui | **FAIL** | 暗 |
| 114 | E 边框焦点 | ring / sidebar 默认 outline | #355f90 | #202537 | **2.31** | 3.0 | ui | **FAIL** | 暗 |
| 115 | E 边框焦点 | ring(不透明) / card 焦点环对照(建议态) | #4999e9 | #24293d | **4.80** | 3.0 | ui | PASS | 暗 |
| 116 | F 降透明 | 分页按钮禁用整件 @50% | #6c707d | #24293d | **2.91** | 4.5 | text | **FAIL** | 暗 |
| 117 | F 降透明 | 图谱类型隐藏章 @40% | #5d6270 | #2b3043 | **2.15** | 4.5 | text | **FAIL** | 暗 |
| 118 | F 降透明 | 知识库未启用章 @60% | #7a7e89 | #2e3346 | **3.08** | 4.5 | text | **FAIL** | 暗 |
| 119 | F 降透明 | 日志心跳副文字 opacity-80（good 章内） | #969ba3 | #203c47 | **4.16** | 4.5 | text | **FAIL** | 暗 |
| 120 | F 降透明 | ghost 按钮 disabled @50% | #888b96 | #24293d | **4.23** | 4.5 | text | **FAIL** | 暗 |
| 121 | F 降透明 | 禁用章整件 @50%（brand 激活章不可点） | #366193 | #27314a | **2.02** | 4.5 | text | **FAIL** | 暗 |
| 122 | G 容器 | foreground / muted/40 说明块标题 | #ecedee | #272b3d | **11.91** | 4.5 | text | PASS | 暗 |
| 123 | G 容器 | muted-foreground / muted/40 说明块正文 | #b3b7bc | #272b3d | **6.92** | 4.5 | text | PASS | 暗 |
| 124 | G 容器 | tone-warn / muted/40 说明块降级行 | #e9c16c | #272b3d | **8.16** | 4.5 | text | PASS | 暗 |
| 125 | G 容器 | muted-foreground / outline 徽章无边底 | #b3b7bc | #24293d | **7.13** | 4.5 | text | PASS | 暗 |
| 126 | G 容器 | foreground / outline 徽章（默认色） | #ecedee | #24293d | **12.27** | 4.5 | text | PASS | 暗 |
| 127 | G 容器 | sk-deep / wash-1 (= secondary 亮态) | #3950ac | #d9e0e7 | **5.40** | 4.5 | text | PASS | 暗 |
| 128 | G 容器 | sk-purple / wash-2 (= accent-foreground 亮态) | #824dcb | #dfdae7 | **3.96** | 4.5 | text | **FAIL** | 暗 |
| 129 | G 容器 | wash-1 / background 装饰面边界 | #d9e0e7 | #1c2031 | **12.11** | - | decor | —(装饰) | 暗 |
| 130 | G 容器 | wash-2 / background 装饰面边界 | #dfdae7 | #1c2031 | **11.77** | - | decor | —(装饰) | 暗 |
| 131 | G 容器 | wash-mist 页面底 / card 卡底分界 | #f4f5f6 | #24293d | **13.18** | - | decor | —(装饰) | 暗 |
| 132 | G 容器 | sidebar-primary-foreground / sidebar-primary | #1d2135 | #4999e9 | **5.30** | 4.5 | text | PASS | 暗 |
| 133 | G 容器 | sidebar-accent-foreground / sidebar-accent | #ecedee | #433a50 | **9.15** | 4.5 | text | PASS | 暗 |

### 低于阈值清单（text+ui 类，102 条）

- **#110 [E 边框焦点] ring / primary 焦点环落在主按钮**｜#318ce7 on #318ce7 = **1.00:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `同上`
- **#110 [E 边框焦点] ring / primary 焦点环落在主按钮**｜#4999e9 on #4999e9 = **1.00:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `同上`
- **#83 [D 图表] chart-1 vs chart-2 序列可辨**｜#64a8ed on #b49ad8 = **1.02:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#93 [D 图表] chart-2 vs chart-4 序列可辨**｜#b49ad8 on #7facd9 = **1.03:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#86 [D 图表] chart-1 vs chart-4 序列可辨**｜#64a8ed on #7facd9 = **1.05:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#121 [F 降透明] 禁用章整件 @50%（brand 激活章不可点）**｜#96c4f2 on #ebf3fb = **1.64:1**（阈值 4.5）｜亮态｜判据 text｜位点 `knowledge.tsx:224 disabled:pointer-events-none disabled:opacity-50`
- **#92 [D 图表] chart-1 vs chart-6 序列可辨**｜#318ce7 on #6b7dc7 = **1.12:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#117 [F 降透明] 图谱类型隐藏章 @40%**｜#babdc9 on #f2f4f6 = **1.69:1**（阈值 4.5）｜亮态｜判据 text｜位点 `memory-graph.tsx:133 opacity-40`
- **#89 [D 图表] chart-1 vs chart-3 序列可辨**｜#64a8ed on #8594d1 = **1.17:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#84 [D 图表] chart-2 vs chart-3 序列可辨**｜#b49ad8 on #8594d1 = **1.20:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#86 [D 图表] chart-1 vs chart-4 序列可辨**｜#318ce7 on #699ed3 = **1.23:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#85 [D 图表] chart-3 vs chart-4 序列可辨**｜#8594d1 on #7facd9 = **1.23:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#107 [E 边框焦点] input / background 设置面板输入框描边**｜#d6dbe1 on #f4f5f6 = **1.28:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `同上，弹层底=bg-background`
- **#108 [E 边框焦点] select 描边 / background(日志筛选下拉)**｜#d6dbe1 on #f4f5f6 = **1.28:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `logs.tsx:249/261 rounded-md border bg-background`
- **#84 [D 图表] chart-2 vs chart-3 序列可辨**｜#824dcb on #3950ac = **1.32:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#91 [D 图表] chart-5 vs chart-6 序列可辨**｜#824dcb on #3950ac = **1.32:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#95 [D 图表] accent 轨道 / card 进度底**｜#dfdae7 on #fafbfc = **1.33:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `calls.tsx:74 h-1.5 bg-accent（轨道=识别进度上限所必需）`
- **#91 [D 图表] chart-5 vs chart-6 序列可辨**｜#a789d2 on #6b7dc7 = **1.33:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#75 [D 图表] chart-6 / card Tooltip 项文字(entry.color)**｜#3950ac on #24293d = **2.00:1**（阈值 4.5）｜暗态｜判据 text｜位点 `recharts DefaultTooltipContent itemStyle.color=entry.color；tokens.tsx:161`
- **#76 [D 图表] chart-6 / card Legend 标签(entry.color)**｜#3950ac on #24293d = **2.00:1**（阈值 4.5）｜暗态｜判据 text｜位点 `recharts DefaultLegendContent labelStyle.color||entry.color；tokens.tsx:159 <Legend/>`
- **#95 [D 图表] accent 轨道 / card 进度底**｜#433a50 on #24293d = **1.34:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `calls.tsx:74 h-1.5 bg-accent（轨道=识别进度上限所必需）`
- **#121 [F 降透明] 禁用章整件 @50%（brand 激活章不可点）**｜#366193 on #27314a = **2.02:1**（阈值 4.5）｜暗态｜判据 text｜位点 `knowledge.tsx:224 disabled:pointer-events-none disabled:opacity-50`
- **#106 [E 边框焦点] input / card 输入框描边**｜#d6dbe1 on #fafbfc = **1.35:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `settings-dialog.tsx:106/127 border（输入底=bg-transparent）`
- **#90 [D 图表] chart-4 vs chart-6 序列可辨**｜#699ed3 on #6b7dc7 = **1.38:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#116 [F 降透明] 分页按钮禁用整件 @50%**｜#aaaebc on #fafbfc = **2.14:1**（阈值 4.5）｜亮态｜判据 text｜位点 `patterns.tsx:152 disabled:opacity-50`
- **#117 [F 降透明] 图谱类型隐藏章 @40%**｜#5d6270 on #2b3043 = **2.15:1**（阈值 4.5）｜暗态｜判据 text｜位点 `memory-graph.tsx:133 opacity-40`
- **#118 [F 降透明] 知识库未启用章 @60%**｜#9a9faf on #eff0f3 = **2.32:1**（阈值 4.5）｜亮态｜判据 text｜位点 `knowledge.tsx:182 opacity-60`
- **#106 [E 边框焦点] input / card 输入框描边**｜#434756 on #24293d = **1.56:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `settings-dialog.tsx:106/127 border（输入底=bg-transparent）`
- **#83 [D 图表] chart-1 vs chart-2 序列可辨**｜#318ce7 on #824dcb = **1.56:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#37 [B 主色] destructive-foreground / destructive/60 暗态**｜#fafafa on #f38487 = **2.38:1**（阈值 4.5）｜亮态｜判据 text｜位点 `badge.tsx:16 dark:bg-destructive/60`
- **#111 [E 边框焦点] ring / secondary 焦点环落在次要按钮**｜#85b6e7 on #d9e0e7 = **1.60:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `logs.tsx:270 variant=secondary 获焦`
- **#112 [E 边框焦点] ring / background 默认 outline 50%**｜#93c1ef on #f4f5f6 = **1.74:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `index.css:201 * @apply outline-ring/50`
- **#107 [E 边框焦点] input / background 设置面板输入框描边**｜#434756 on #1c2031 = **1.75:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `同上，弹层底=bg-background`
- **#108 [E 边框焦点] select 描边 / background(日志筛选下拉)**｜#434756 on #1c2031 = **1.75:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `logs.tsx:249/261 rounded-md border bg-background`
- **#73 [D 图表] chart-5 / card Tooltip 项文字(entry.color)**｜#824dcb on #24293d = **2.65:1**（阈值 4.5）｜暗态｜判据 text｜位点 `recharts DefaultTooltipContent itemStyle.color=entry.color；tokens.tsx:161`
- **#74 [D 图表] chart-5 / card Legend 标签(entry.color)**｜#824dcb on #24293d = **2.65:1**（阈值 4.5）｜暗态｜判据 text｜位点 `recharts DefaultLegendContent labelStyle.color||entry.color；tokens.tsx:159 <Legend/>`
- **#43 [C tone章] tone-warn / tone-face-warn over card**｜#e27100 on #f7e8d9 = **2.66:1**（阈值 4.5）｜亮态｜判据 text｜位点 `patterns.tsx:102 TONE_TEXT.warn`
- **#109 [E 边框焦点] ring / card 焦点环 50% alpha**｜#96c4f2 on #fafbfc = **1.78:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `button.tsx:9 focus-visible:ring-ring/50`
- **#113 [E 边框焦点] ring / card 默认 outline(裸 button 在卡内)**｜#96c4f2 on #fafbfc = **1.78:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `10 处裸 <button> 无 focus-visible 覆写`
- **#114 [E 边框焦点] ring / sidebar 默认 outline**｜#96c4f2 on #fafbfc = **1.78:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `app-shell.tsx:32 NavItem Link`
- **#71 [D 图表] chart-4 / card Tooltip 项文字(entry.color)**｜#699ed3 on #fafbfc = **2.74:1**（阈值 4.5）｜亮态｜判据 text｜位点 `recharts DefaultTooltipContent itemStyle.color=entry.color；tokens.tsx:161`
- **#72 [D 图表] chart-4 / card Legend 标签(entry.color)**｜#699ed3 on #fafbfc = **2.74:1**（阈值 4.5）｜亮态｜判据 text｜位点 `recharts DefaultLegendContent labelStyle.color||entry.color；tokens.tsx:159 <Legend/>`
- **#88 [D 图表] chart-3 vs chart-6 序列可辨**｜#3950ac on #6b7dc7 = **1.85:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#87 [D 图表] chart-2 vs chart-5 序列可辨**｜#824dcb on #a789d2 = **1.85:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#124 [G 容器] tone-warn / muted/40 说明块降级行**｜#e27100 on #eef0f5 = **2.80:1**（阈值 4.5）｜亮态｜判据 text｜位点 `memory-graph.tsx:251 degradedSources`
- **#38 [B 主色] success-foreground / success 徽章**｜#fafafa on #4ca779 = **2.82:1**（阈值 4.5）｜暗态｜判据 text｜位点 `badge.tsx:17；plugins.tsx:33 可热重载`
- **#73 [D 图表] chart-5 / card Tooltip 项文字(entry.color)**｜#a789d2 on #fafbfc = **2.84:1**（阈值 4.5）｜亮态｜判据 text｜位点 `recharts DefaultTooltipContent itemStyle.color=entry.color；tokens.tsx:161`
- **#74 [D 图表] chart-5 / card Legend 标签(entry.color)**｜#a789d2 on #fafbfc = **2.84:1**（阈值 4.5）｜亮态｜判据 text｜位点 `recharts DefaultLegendContent labelStyle.color||entry.color；tokens.tsx:159 <Legend/>`
- **#39 [B 主色] success-foreground / success hover/90**｜#fafafa on #42a77a = **2.85:1**（阈值 4.5）｜亮态｜判据 text｜位点 `badge.tsx:17`
- **#48 [C tone章] primary / bg-primary/15 brand 章**｜#318ce7 on #dceaf9 = **2.85:1**（阈值 4.5）｜亮态｜判据 text｜位点 `patterns.tsx:107 TONE_TEXT.brand`
- **#93 [D 图表] chart-2 vs chart-4 序列可辨**｜#824dcb on #699ed3 = **1.92:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#94 [D 图表] primary/70 条内填充 / accent 轨道**｜#65a3e7 on #dfdae7 = **1.92:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `calls.tsx:74-77 TopList HTML 条形`
- **#116 [F 降透明] 分页按钮禁用整件 @50%**｜#6c707d on #24293d = **2.91:1**（阈值 4.5）｜暗态｜判据 text｜位点 `patterns.tsx:152 disabled:opacity-50`
- **#120 [F 降透明] ghost 按钮 disabled @50%**｜#8f939f on #fafbfc = **2.98:1**（阈值 4.5）｜亮态｜判据 text｜位点 `button.tsx:9 disabled:opacity-50`
- **#42 [C tone章] tone-good / tone-face-good over card**｜#009965 on #d7ede7 = **3.00:1**（阈值 4.5）｜亮态｜判据 text｜位点 `patterns.tsx:101 TONE_TEXT.good`
- **#35 [B 主色] destructive-foreground / destructive 徽章**｜#fafafa on #fb575c = **3.03:1**（阈值 4.5）｜暗态｜判据 text｜位点 `badge.tsx:15；dashboard.tsx:134 degraded`
- **#22 [B 主色] primary-foreground / primary hover /90**｜#ffffff on #4597e9 = **3.06:1**（阈值 4.5）｜亮态｜判据 text｜位点 `button.tsx:13 hover:bg-primary/90`
- **#118 [F 降透明] 知识库未启用章 @60%**｜#7a7e89 on #2e3346 = **3.08:1**（阈值 4.5）｜暗态｜判据 text｜位点 `knowledge.tsx:182 opacity-60`
- **#54 [C tone章] tone-warn / card 12px 文字**｜#e27100 on #fafbfc = **3.09:1**（阈值 4.5）｜亮态｜判据 text｜位点 `tokens.tsx:39；memory-graph.tsx:251`
- **#89 [D 图表] chart-1 vs chart-3 序列可辨**｜#318ce7 on #3950ac = **2.07:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#111 [E 边框焦点] ring / secondary 焦点环落在次要按钮**｜#3b6597 on #2e3245 = **2.12:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `logs.tsx:270 variant=secondary 获焦`
- **#38 [B 主色] success-foreground / success 徽章**｜#fafafa on #2e9e6b = **3.23:1**（阈值 4.5）｜亮态｜判据 text｜位点 `badge.tsx:17；plugins.tsx:33 可热重载`
- **#39 [B 主色] success-foreground / success hover/90**｜#fafafa on #489b73 = **3.25:1**（阈值 4.5）｜暗态｜判据 text｜位点 `badge.tsx:17`
- **#87 [D 图表] chart-2 vs chart-5 序列可辨**｜#b49ad8 on #824dcb = **2.21:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#119 [F 降透明] 日志心跳副文字 opacity-80（good 章内）**｜#7a8096 on #def0eb = **3.33:1**（阈值 4.5）｜亮态｜判据 text｜位点 `logs.tsx:189 opacity-80`
- **#26 [B 主色] primary / card 链接与展开按钮**｜#318ce7 on #fafbfc = **3.36:1**（阈值 4.5）｜亮态｜判据 text｜位点 `button.tsx:20 variant=link；knowledge.tsx:55`
- **#27 [B 主色] primary / sidebar 子导航激活**｜#318ce7 on #fafbfc = **3.36:1**（阈值 4.5）｜亮态｜判据 text｜位点 `app-shell.tsx:22 [&.active]:text-primary`
- **#28 [B 主色] primary / card 好感度正值**｜#318ce7 on #fafbfc = **3.36:1**（阈值 4.5）｜亮态｜判据 text｜位点 `affinity.tsx:25`
- **#65 [D 图表] chart-1 / card Tooltip 项文字(entry.color)**｜#318ce7 on #fafbfc = **3.36:1**（阈值 4.5）｜亮态｜判据 text｜位点 `recharts DefaultTooltipContent itemStyle.color=entry.color；tokens.tsx:161`
- **#66 [D 图表] chart-1 / card Legend 标签(entry.color)**｜#318ce7 on #fafbfc = **3.36:1**（阈值 4.5）｜亮态｜判据 text｜位点 `recharts DefaultLegendContent labelStyle.color||entry.color；tokens.tsx:159 <Legend/>`
- **#77 [D 图表] primary / card 折线 Tooltip 项文字**｜#318ce7 on #fafbfc = **3.36:1**（阈值 4.5）｜亮态｜判据 text｜位点 `calls.tsx:174 Line stroke=var(--primary)`
- **#109 [E 边框焦点] ring / card 焦点环 50% alpha**｜#366193 on #24293d = **2.25:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `button.tsx:9 focus-visible:ring-ring/50`
- **#113 [E 边框焦点] ring / card 默认 outline(裸 button 在卡内)**｜#366193 on #24293d = **2.25:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `10 处裸 <button> 无 focus-visible 覆写`
- **#114 [E 边框焦点] ring / sidebar 默认 outline**｜#355f90 on #202537 = **2.31:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `app-shell.tsx:32 NavItem Link`
- **#21 [B 主色] primary-foreground / primary 主按钮 13px**｜#ffffff on #318ce7 = **3.48:1**（阈值 4.5）｜亮态｜判据 text｜位点 `button.tsx:13`
- **#23 [B 主色] primary-foreground / primary Badge 12px**｜#ffffff on #318ce7 = **3.48:1**（阈值 4.5）｜亮态｜判据 text｜位点 `badge.tsx:13`
- **#24 [B 主色] primary-foreground / primary 页签 12px**｜#ffffff on #318ce7 = **3.48:1**（阈值 4.5）｜亮态｜判据 text｜位点 `tokens.tsx:99 / calls.tsx:36 激活窗档`
- **#132 [G 容器] sidebar-primary-foreground / sidebar-primary**｜#ffffff on #318ce7 = **3.48:1**（阈值 4.5）｜亮态｜判据 text｜位点 `@theme 转发 var(--primary*)，无 tsx 消费点（死 token）`
- **#36 [B 主色] destructive-foreground / destructive/90 hover**｜#fafafa on #e65259 = **3.51:1**（阈值 4.5）｜暗态｜判据 text｜位点 `badge.tsx:15`
- **#36 [B 主色] destructive-foreground / destructive/90 hover**｜#fafafa on #ef484c = **3.53:1**（阈值 4.5）｜亮态｜判据 text｜位点 `badge.tsx:15`
- **#112 [E 边框焦点] ring / background 默认 outline 50%**｜#325c8d on #1c2031 = **2.36:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `index.css:201 * @apply outline-ring/50`
- **#44 [C tone章] tone-bad / tone-face-bad over card**｜#e7000b on #f7d8da = **3.59:1**（阈值 4.5）｜亮态｜判据 text｜位点 `patterns.tsx:103 TONE_TEXT.bad`
- **#57 [C tone章] tone-bad / card 12px 文字(×连败章)**｜#e7000b on #f7d8da = **3.59:1**（阈值 4.5）｜亮态｜判据 text｜位点 `latency.tsx:40 CategoryChip tone=bad`
- **#88 [D 图表] chart-3 vs chart-6 序列可辨**｜#8594d1 on #3950ac = **2.45:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#47 [C tone章] tone-magenta / tone-face-magenta over card**｜#bd24da on #f2ddf7 = **3.71:1**（阈值 4.5）｜亮态｜判据 text｜位点 `patterns.tsx:106 TONE_TEXT.magenta`
- **#41 [B 主色] destructive / background 校验错误文字**｜#ee3439 on #f4f5f6 = **3.72:1**（阈值 4.5）｜亮态｜判据 text｜位点 `settings-dialog.tsx:110`
- **#94 [D 图表] primary/70 条内填充 / accent 轨道**｜#477cbb on #433a50 = **2.49:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `calls.tsx:74-77 TopList HTML 条形`
- **#75 [D 图表] chart-6 / card Tooltip 项文字(entry.color)**｜#6b7dc7 on #fafbfc = **3.76:1**（阈值 4.5）｜亮态｜判据 text｜位点 `recharts DefaultTooltipContent itemStyle.color=entry.color；tokens.tsx:161`
- **#76 [D 图表] chart-6 / card Legend 标签(entry.color)**｜#6b7dc7 on #fafbfc = **3.76:1**（阈值 4.5）｜亮态｜判据 text｜位点 `recharts DefaultLegendContent labelStyle.color||entry.color；tokens.tsx:159 <Legend/>`
- **#85 [D 图表] chart-3 vs chart-4 序列可辨**｜#3950ac on #699ed3 = **2.54:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#48 [C tone章] primary / bg-primary/15 brand 章**｜#4999e9 on #2a3a57 = **3.82:1**（阈值 4.5）｜暗态｜判据 text｜位点 `patterns.tsx:107 TONE_TEXT.brand`
- **#35 [B 主色] destructive-foreground / destructive 徽章**｜#fafafa on #ee3439 = **3.88:1**（阈值 4.5）｜亮态｜判据 text｜位点 `badge.tsx:15；dashboard.tsx:134 degraded`
- **#128 [G 容器] sk-purple / wash-2 (= accent-foreground 亮态)**｜#824dcb on #dfdae7 = **3.96:1**（阈值 4.5）｜亮态｜判据 text｜位点 `index.css:40-41`
- **#128 [G 容器] sk-purple / wash-2 (= accent-foreground 亮态)**｜#824dcb on #dfdae7 = **3.96:1**（阈值 4.5）｜暗态｜判据 text｜位点 `index.css:40-41`
- **#82 [D 图表] chart-4 / card 堆叠条本体(最淡)**｜#699ed3 on #fafbfc = **2.74:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `同上 cache_creation`
- **#119 [F 降透明] 日志心跳副文字 opacity-80（good 章内）**｜#969ba3 on #203c47 = **4.16:1**（阈值 4.5）｜暗态｜判据 text｜位点 `logs.tsx:189 opacity-80`
- **#120 [F 降透明] ghost 按钮 disabled @50%**｜#888b96 on #24293d = **4.23:1**（阈值 4.5）｜暗态｜判据 text｜位点 `button.tsx:9 disabled:opacity-50`
- **#92 [D 图表] chart-1 vs chart-6 序列可辨**｜#64a8ed on #3950ac = **2.86:1**（阈值 3.0）｜暗态｜判据 ui｜位点 `堆叠段相邻/图例色点；同色系仅明度差=色盲风险`
- **#46 [C tone章] tone-purple / tone-face-purple over card**｜#824dcb on #e9e3f5 = **4.33:1**（阈值 4.5）｜亮态｜判据 text｜位点 `patterns.tsx:105 TONE_TEXT.purple`
- **#60 [C tone章] tone-warn / background 横幅内图标**｜#e27100 on #f4f5f6 = **2.93:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `logs.tsx:228`
- **#61 [C tone章] tone-warn / background 横幅描边**｜#e27100 on #f4f5f6 = **2.93:1**（阈值 3.0）｜亮态｜判据 ui｜位点 `logs.tsx:227 border-tone-warn`
- **#34 [B 主色] muted-foreground / accent hover(未覆写文字色的 ghost)**｜#5a617c on #dfdae7 = **4.46:1**（阈值 4.5）｜亮态｜判据 text｜位点 `tokens.tsx:100 / calls.tsx:36 非激活页签 hover:bg-accent（文字色不变=muted-foreground 落在 accent 上）`

总计色对 133 组 ×2 主题 = 266 行（text=83 ui=35 decor=12 manual=3）；判 Fail 102 行

---

## 3. 低于 AA / 3:1 清单与建议新值

### 3.1 汇总口径（诚实分箱）

| 分箱 | 组数 | 亮态 Fail | 暗态 Fail | 备注 |
|---|---|---|---|---|
| `text`（1.4.3 强制） | 83 | 31 | 25 | 其中 6 条是 WCAG **明确豁免**的 disabled 态，见 §3.4 |
| `ui`（1.4.11 计入项） | 35 | 12 | 14 | 图表序列互辨 11 对 + 焦点环 6 + 输入框描边 3 + 轨道 2（部分成对重复） |
| `decor`（记录不计分） | 12 | — | — | 卡片描边/网格线/滚动条/洗色面/骨架块 |
| `manual`（算不出） | 3 | — | — | 见 §12 |
| **合计 Fail** | 133 | — | — | **102 行**（56 text + 46 ui），去重后 **约 41 个独立色对** |

### 3.2 最严重 6 条（全部有具体落手改法）

| # | 缺陷 | 实算 | 覆盖面 |
|---|---|---|---|
| 1 | 亮态**白字压品牌蓝** `--primary-foreground` on `--primary` | **3.48** / hover 3.06（阈 4.5） | 主按钮、默认徽章、24h/7d/30d 激活页签 ×2、侧栏激活态、Logo 图标底 = **6 面** |
| 2 | 亮态**六枚 tone 章**文字压自身 14% 洗底 | warn **2.66**、good **3.00**、bad **3.59**、magenta **3.71**、purple **4.33**（阈 4.5） | 日志级别 / 渠道状态 / 档位 / 健康检查 / 图谱截断提示 = 全站章体 |
| 3 | **recharts Tooltip 项文字与 Legend 标签 = 序列色直接当文字色** | 亮 chart-4 **2.74** / chart-5 **2.84**；暗 chart-6 **2.00** / chart-5 **2.65**（阈 4.5） | tokens 页堆叠图 + calls 页折线 |
| 4 | **焦点环不可见** `ring/50` | 亮 **1.78** / 暗 **2.25**（阈 3.0）；**落在 `bg-primary` 上 = 1.00（完全不可见）** | 所有 Button/Badge/裸 button/select/Link |
| 5 | 暗态**填充徽章上近白前景** | `--success` **2.82**、`--destructive` **3.03**（阈 4.5）；亮态 success 3.23 / destructive 3.88 亦不达 | 插件「可热重载」、总览「降级」徽章 |
| 6 | **`primary / card` 当文字色用** | **3.36**（阈 4.5），链接 / 展开更多 / 好感度正值 / 子导航激活 | 4 面 |

### 3.3 建议新值（推导过程 + 代回复算）

**推导法**：固定 OKLCH 的色相 H，沿 L 单调扫描（必要时降 C），取**同时满足「on-card」与「on 自身 14% 章底」**两个条件的最小改动量。全部结果已代回 §2 的合成链复算。

#### (a) `:root` 亮态 tone 六枚（一处改，全站章体 + 横幅描边 + 图标同时收口）

| token | 现值 | 现最差 | **建议** | 新 hex | 复算最差 |
|---|---|---|---|---|---|
| `--tone-good` | `oklch(0.596 0.145 163)` `#009965` | 3.00 | `oklch(0.501 0.1015 163)` | `#157553` | **4.50** |
| `--tone-warn` | `oklch(0.666 0.179 58)` `#e27100` | 2.66 | `oklch(0.522 0.1074 58)` | `#975820` | **4.51** |
| `--tone-bad` | `oklch(0.577 0.245 27.3)` `#e7000b` | 3.59 | `oklch(0.529 0.196 27.3)` | `#c32221` | **4.51** |
| `--tone-info` | `oklch(0.5 0.134 242.7)` `#0069a8` | 4.61 | `oklch(0.5 0.1072 242.7)` | `#1c699b` | **4.70**（仅彩度收 0.8×，L 不动） |
| `--tone-purple` | `var(--sk-purple)` `#824dcb` | 4.33 | `oklch(0.534 0.1875 299.5)` | `#7f4ac7` | **4.51**（须在 `.dark` 外**另立** `--tone-purple`，见 §5） |
| `--tone-magenta` | `oklch(0.591 0.262 320.4)` `#bd24da` | 3.71 | `oklch(0.538 0.2358 320.4)` | `#a621bf` | **4.52** |

连带收益：`--tone-warn` 压到 `#975820` 后，`border-tone-warn` 在页底上从 **2.93 → 5.18**（原低于 3.0 的 1.4.11 Fail 一并消失）；`tone-warn / card` 12px 文字从 3.09 → 5.46。

#### (b) 主色：不动本命色，加两枚「文字/填充专用」派生 token

品牌本命 `#318ce7` 是卡片值册 `BRAND_ACCENT` 登记值，**不得为凑对比度改它**。最小侵入方案：

```css
:root {
  /* 现 --primary: oklch(0.632 0.1608 252);  保留，只用于描边/图形/渐变/图标底 */
  --primary-strong: oklch(0.569 0.1608 252);  /* #1678d2 —— 承载白字的填充底 */
  --primary-ink:    oklch(0.561 0.1608 252);  /* #1276cf —— 亮底上的品牌蓝文字 */
}
.dark {
  /* 暗态本就不需要：--primary(暗) #4999e9 on card = 4.80:1 已达标（实算） */
  --primary-strong: oklch(0.601 0.1427 250.8);
  --primary-ink:    var(--primary);
}
```

复算：`#ffffff` on `--primary-strong(亮) #1678d2` = **4.50:1 OK**；`--primary-ink #1276cf` on `--card` = **4.50 OK**、on `--sidebar` = **4.50 OK**、on 自身 `primary/15` 章底 = **4.50 OK**。

落手面（4 个文件的类名替换）：
- `button.tsx:13` `bg-primary` → `bg-primary-strong`（含 `hover:` 变体）
- `badge.tsx:13` `bg-primary` → `bg-primary-strong`
- `tokens.tsx:99` / `calls.tsx:36` 激活页签 `bg-primary` → `bg-primary-strong`
- `app-shell.tsx:34` `[&.active]:bg-primary [&.active]:text-primary-foreground` → `bg-primary-strong`
- `button.tsx:20` link、`knowledge.tsx:55`、`affinity.tsx:25`、`app-shell.tsx:22` 的 `text-primary` → `text-primary-ink`
- `patterns.tsx:107` brand 章 `text-primary bg-primary/15` → `text-primary-ink bg-primary/15`

替代方案（**不推荐**，如实列出）：把亮态 `--primary-foreground` 从 `oklch(1 0 0)` 改成深墨 `oklch(0.257 0 0)`（复算 4.51），零新增 token 但主按钮从「白字蓝底」变「深字蓝底」，观感改动大，且与暗态已有深墨的方向**巧合一致**（暗态 `--primary-foreground: oklch(0.254 0.0383 274.7)`）——若用户偏好「不新增 token」，这是唯一一条改一行的路。

#### (c) 暗态/亮态填充徽章前景

| 面 | 现 | 方案 A（压填充） | 方案 B（改深墨前景） |
|---|---|---|---|
| `--success`(暗) `#4ca779` + `#fafafa` | **2.82** | `oklch(0.544 0.1123 159.1)` = `#218357` → **4.51** | `--success-foreground: oklch(0.254 0.0383 274.7)` → **5.40** |
| `--success`(亮) `#2e9e6b` + `#fafafa` | **3.23** | `oklch(0.544 0.1138 159.1)` = `#1f8357` → **4.50** | 同上深墨 → **4.71** |
| `--destructive`(暗) `#fb575c` | **3.03** | `oklch(0.582 0.2 22.5)` = `#d8333f` → **4.51** | 深墨 → 5.02 |
| `--destructive`(亮) `#ee3439` | **3.88** | `oklch(0.584 0.22 25.5)` = `#e0232d` → **4.51** | 深墨 → **3.92 仍不达** |

**推荐 A**（两态各压一次 L，前景保持近白）。注意：**亮态 destructive 走 B 会残留 3.92 不达**——这条要说清，别选错。
**注意 `--success` 亮态压暗会偏离值册 `SEMANTIC_SUCCESS = #2e9e6b`**：值册那条是「卡内语义文字色」，不是「承载白字的填充底」，两者语义位不同，不构成对值册的违背；但若走 A，须在值册新增一行登记（见 §5.4 统一缺口 U-3）。

更省事的第三条路（**推荐给徽章族整体**）：`Badge variant='success'`/`'destructive'` 从「饱和填充 + 白字」改成章体同款「深语义字 + 14% 浅洗底」（即复用 `tone-face-*`），一改就同时拿到 §3.3(a) 的成果，且不引入新色值、不与值册抢语义。**代价**：徽章与章的视觉层级会靠近，需用户裁量。这是**裁决点**，不是纯技术题。

#### (d) 输入框/下拉描边（1.4.11 3:1）

```css
:root { --input: oklch(0.66 0.0099 252.8); }    /* #8e9398  on card 1.35 -> 3.00 */
.dark { --input: oklch(0.554 0.0258 273.4); }   /* #6e7282  on card 1.56 -> 3.00 */
```
**`--border` 保持原淡值不动**（卡片描边/网格线/分隔线属装饰，不计 1.4.11 分），只把 `--input` 从「与 `--border` 同值」拆出来——这也是 shadcn 的原始意图（两枚 token 本就该可分叉）。

#### (e) 焦点环（终方案，复算过）

现状：`focus-visible:ring-ring/50` + `focus-visible:ring-[3px]`，且全局 `* { outline-ring/50 }`。
- 亮 `ring/50` on card = **1.78**；暗 = **2.25**；**落在 `bg-primary` 上 = 1.00**（`--ring` 与 `--primary` 同值，等于完全隐形）。
- 只把 alpha 提到 100%：亮 3.36 / 暗 4.80 达标，但**落在 primary 上仍是 1.00**，治不了主按钮。

推荐改法（一处基类 + 一处全局）：

```css
/* index.css @layer base */
* { outline: 2px solid transparent; outline-offset: 2px; }   /* 预留 offset 缝 */
```
```
button.tsx:9 / badge.tsx:9 与 4 处 input：
  focus-visible:ring-ring/50 focus-visible:ring-[3px]
→ focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground
```
为什么用 `--foreground` 而不是 `--ring`：复算 `--foreground` 描边 on card = **13.67（亮）/ 12.27（暗）**，on background = 12.97 / 13.79，且**带 2px offset 后描边邻接的是父底而非按钮自身填充**，所以「落在 primary 上 2.56」这个数不再构成判据。同时 `outline-2` 天然满足 WCAG 2.4.13 焦点外观面积下限。

### 3.4 必须如实标注的豁免与降级项

- **`disabled:opacity-50`（分页按钮 2.14、ghost 按钮 2.98、集合 chip 1.64/2.02）不构成 WCAG 失败**——1.4.3 例外条款明载「inactive user interface components」豁免。本席**只登记数字，不记 Fail**（§2 表里它们在，判据列可辨）。
- **`opacity-40`（`memory-graph.tsx:133` 类型隐藏态）不是 disabled**：它是**可点的状态开关**，其文字是活的承载信息 → 实算 1.69（亮）/2.15（暗），**这条是真 Fail，要修**（改 `opacity-40` → 去透明度、改用 `border-dashed` + `text-muted-foreground` 表「未启用」）。
- `opacity-60`（`knowledge.tsx:182`，包在 `disabled` 按钮内）→ 落在豁免区，降为 Minor。
- 图表相邻序列互辨（1.02–2.86）：1.4.11 对「区分数据系列」是否强制存在解释空间。**本席按「计入」处理并如实标注**，因为该图**完全没有形状/图案/末端直标冗余**（§4.3），颜色是唯一通道。

---

## 4. 图表层（recharts 3.10.1 + canvas）

### 4.1 文字色的真实来源（读了装好的 recharts 源码取证）

`node_modules/recharts/es6/component/DefaultTooltipContent.js`：
```
29: export var defaultDefaultTooltipContentProps = {
31:   contentStyle: { margin:0, padding:10, backgroundColor:'#fff', border:'1px solid #ccc', whiteSpace:'nowrap' },
38:   itemStyle:    { display:'block', paddingTop:4, paddingBottom:4, color:'#000' },
44:   labelStyle:   {},
45:   accessibilityLayer: false
105:  var finalItemStyle = {...defaultDefaultTooltipContentProps.itemStyle, {},
106:    color: entry.color || defaultDefaultTooltipContentProps.itemStyle.color }
129:  var finalStyle = {...contentStyle 默认, ...contentStyle}
```
`DefaultLegendContent.js`：
```
120:  finalLabelStyle.color = entry.inactive ? inactiveColor : finalLabelStyle.color || entry.color;
```

**结论（钉死）**：项目只传了 `contentStyle`（覆盖了默认 `#fff` 底 → 拿到底色 correctly），**没传 `itemStyle` / `labelStyle` / Legend 的 `formatter`**。于是：

1. **Tooltip 每一项的文字色 = `entry.color` = 该序列的 `fill`/`stroke`**（即 `var(--chart-1..4)`、`var(--primary)`）落在 `var(--card)` 上 → §2 表 #65–#77，**亮态 chart-4 2.74 / chart-5 2.84 / chart-1 3.36；暗态 chart-6 2.00 / chart-5 2.65 全部低于 4.5**。
2. **Legend 标签同理**（`tokens.tsx:159 <Legend />` 裸用）。
3. Tooltip **标题（label）** 未设 color → 从 DOM 继承 `text-card-foreground` = **13.67 PASS**（这条是好的，但要写进注释防被"顺手改坏"）。
4. 默认 `contentStyle.whiteSpace:'nowrap'` 未被覆盖 → 中文长序列名（「缓存创建」+数值）在窄屏**不换行会溢出**（Minor，需目验宽度）。

**改法（可直接落手）**：
```tsx
// tokens.tsx:155-159
<Tooltip
  contentStyle={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 12, color: 'var(--card-foreground)', whiteSpace: 'normal' }}
  itemStyle={{ color: 'var(--card-foreground)' }}
  formatter={(value, name) => [formatInt(Number(value)), String(name)] as [string, string]}
/>
<Legend formatter={(value) => <span className="fs-caption text-card-foreground">{value}</span>} />
```
```tsx
// calls.tsx:170 同样补 itemStyle + contentStyle.color
```
（序列色仍保留在图例方块与条/线本体上——那是它的本职，不当文字用。）

### 4.2 轴与网格

| 项 | 取值方式 | 判定 |
|---|---|---|
| X/Y 轴刻度文字 | `tick={{ fill: 'var(--muted-foreground)' }}` = **token，好** | 12px on card **5.91 PASS**（两态均过；暗 `#b3b7bc` on `#24293d` = 8.79） |
| 轴杆 `stroke` | token `var(--muted-foreground)` | 装饰，不计分 |
| 网格线 | token `var(--border)` | 1.35/1.56，**装饰**（网格不是识别控件）→ 不计分，仅记录 |
| 字号 | 唯一来源 `index.css:318-322` 三条 CSS 规则 = 12px，且机器门禁 tsx 内 `fontSize:` | **口径正确** ✓ |
| 折线本体 | `stroke='var(--primary)'` 2px on card = 3.36 | UI 3.0 **PASS** |
| 堆叠条最淡段 | `var(--chart-4)` on card = **2.74** | UI 3.0 **FAIL** → 建议 `--chart-4(亮)` 由 `oklch(0.683 …)` 压到 `oklch(0.658 0.0969 249.4)` = `#6196cb` → **3.01** |

**唯一违反「变量单一来源」的**：`tokens.tsx:151 tick={{ fill: 'var(--muted-foreground)', fontFamily: 'monospace' }}` —— **`'monospace'` 是字面量，绕过了 `--font-mono`**（F3 席已发现，本席量化其后果见 §6.4）。

### 4.3 色盲可辨性（序列冗余通道缺失）

- `--chart-1..6` 亮态 = 三蓝两紫一深蓝（H 249–302），**暗态 chart-5/6 直接复用亮态的 sk-purple/sk-deep 值**（`index.css:112-113`）。
- 实测相邻序列对比 **1.02–2.54**，同族对（1vs4、2vs5、3vs6）**1.05 / 1.85 / 1.85**。
- **冗余通道清点**：堆叠条**无图案/无斜纹/无末端直标**，`dot={false}`，Legend 只有色方块 + 标签。→ **颜色是唯一区分通道**。
- 建议（按性价比排序，全是加法不改色）：① `<Bar fill=... fillOpacity={1} stroke="var(--card)" strokeWidth={1}>` 用**分隔描边**把相邻段切开（1 行改动解决 1.02 问题）；② 四条 token 加**图案通道**（recharts 支持 `<defs><pattern>`，或退一步用 4 个明度差 ≥3:1 的档）；③ 图例方块改 `iconType='circle'/'diamond'/'triangle'` 异形，让形状承载类型（`memory-graph.tsx:128/199` 的 5 枚 `rounded-full` 色点同理——现在 5 类节点**只靠 8px 圆的颜色区分**，加形状是最省事的冗余）。

### 4.4 canvas（记忆图谱）

取色全走 `getComputedStyle` 读语义 token（`memory-canvas.tsx:17-19`）✓ 宪法③执行到位，`.dark` class 变更由 `MutationObserver` 驱动重绘 ✓。**残余量化问题**：
- 节点标签 `context.font = '12px "Segoe UI", "Microsoft YaHei", sans-serif'`（:179）——**手写栈**，与 `--font-sans` 手工同步；应改读 `readToken('--font-sans')`。且**字号硬编码 12px，不随缩放**：`transform.k=0.2` 时标签仍是 12px 而节点缩到 20% → 密集重叠糊成一团（**需真机目验**，静态算不出实际重叠率）。
- 边线 `globalAlpha = 0.06`（bothDim 态，:149）——**0.06 alpha 的线在卡底上肉眼几乎不存在**。这是"算不出"的一类（alpha × 底色叠加后 1.0X:1），但**方向明确：0.06 过低**，建议 ≥0.15 并配 `--border` 而非序列色。
- 标签只在 `hover / selected / k≥1.6` 显示（:176）→ **hover-only 信息，无键盘等价物**（画布连 `tabIndex` 都没有，§8）。

---

## 5. 主题矩阵一致性（统一变量 diff）

### 5.1 webui 侧主题模型（实读）

`theme-context.tsx` 实际只改两件事：`document.documentElement.classList.toggle('dark', …)` + `style.colorScheme`。`index.css:8 @custom-variant dark (&:is(.dark *))`，且 `@theme **inline**` —— `inline` 是关键正确选择：工具类内联成 `background-color: var(--background)` 而非烤死值，所以 `.dark` 覆写在运行时生效 ✓。

**与渲染域的主题模型不对齐（结构性，非缺键）**：
- 值册有 `PLATFORM_THEMES` **17 条**（实读装载 `theme_tokens.py` 得 `['allcpp','apple_music','bilibili','douyin','facebook','instagram','kugou','kuwo','lofter','netease','pixiv','qqmusic','spotify','twitter','weibo','xiaohongshu','youtube']`）+ 本命 BRAND。
- **webui 有 0 条平台主题**（`grep -rn "platform|PLATFORM" webui/src/index.css webui/src/context/theme-context.tsx` → 空），只有 light/dark 两面。
- 判定：**这不是 bug，是双模型**。但「一切先经中央统一指令」要求这条差异**被显式登记**而不是靠默契。建议：值册新增 `WEBUI_THEME_SURFACE = 'brand-only+dark'` 一行登记 + `index.css` 头部注释指回该常量，作为门的锚。

### 5.2 变量集合 diff（`themadiff.py` 实跑）

`:root` **60 键** / `.dark` **46 键** / `@theme inline` 58 键。`.dark` 相对 `:root` **缺 14 键，多 0 键**。

| `.dark` 缺失键 | `:root` 值 | 暗态后果 | 严重度 |
|---|---|---|---|
| `--wash-1 / -2 / -3 / --wash-mist` | 亮洗色四枚 | **当前无 tsx 消费点**（`--background/--secondary/--muted/--accent` 在 `.dark` 各被**直接覆写**，不再经 wash） → 无实害 | Minor（陷阱） |
| `--sk-deep` / `--sk-purple` | `#3950ac` / `#824dcb` | `@theme` 有 `--color-sk-*` → **`bg-sk-purple`/`text-sk-deep` 在暗态会保持亮色**。当前 0 消费点 | Minor（陷阱） |
| `--sidebar-border` / `--sidebar-ring` | 转发 `--border` / `--ring` | 转发式，暗态自动跟随 → **无实害** | 无 |
| `--sidebar-primary` / `--sidebar-primary-foreground` | 转发 `--primary*` | 同上，且 **0 消费点（死 token）** | Minor |
| `--radius` | `14px` | **全树 0 引用**（半径实走 `--r-shell/panel/tile`）→ 死键 | Minor |

**关键正向结论（要写清楚，别只报坏消息）**：
- **`--tone-*` 六枚亮暗全部成对**（实读比对，§7 表），**`--chart-1..6` 六枚全部成对**，**44 条 `@theme inline --color-*` 转发链 0 悬空**（除下条一项）。
- 所以「某主题下某色对未覆盖 → 回落 `:root` 造成对比失控」这条**在现行代码里未发生**（除死 token 陷阱）。暗态色对普遍达标（tone 章暗态 4.55–8.41 全 PASS，亮态才是灾区）。

### 5.3 真正的悬空引用（1 条，可机器化）

```
index.css:291 @utility tone-face {
index.css:292   background: color-mix(in srgb, var(--tone) 14%, transparent);
}
```
`--tone` **在 `:root` 与 `.dark` 均未定义**（`themadiff.py` 第 5 节输出：悬空引用 = `--tone`）。→ `tone-face`（无后缀公共版）解析失败、`background` 声明被丢弃 = 透明。当前 0 消费点（`grep -rn "tone-face['\" ]" --include=*.tsx` → 空），**但它是六枚 `tone-face-*` 的"同名公共入口"**：下一个接手的人写 `tone-face` + 内联 `--tone: …` 会以为能用，实际拿到透明底。→ 要么删，要么把 `--tone` 纳进两处定义。

### 5.4 中央统一缺口清单（U 系，本席独占的量化部分）

| # | 项 | 值册 | webui | 实算后果 |
|---|---|---|---|---|
| **U-1** | **字号阶梯双源** | `TYPE_SCALE_PX = {display:26, title:20, body:15, label:13, caption:12}` | `fs-* = {page:18, card:14, body:13, caption:12, num:30}` | **交集只有 {12, 13}**；值册独有 {15,20,26}；webui 独有 {14,18,30}。`index.css:226` 却自称「版式宪法…全站」→ **同一产品两套五档** |
| U-2 | 等宽字体栈双源 | C9 `MONO_FONT_STACK = '"Cascadia Mono",Consolas,"JetBrains Mono","Courier New",monospace'` | `--font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace` | 两栈只有 Consolas 重合；**且两栈都没有 CJK 兜底**（§6.4） |
| U-2b | 无衬线栈 | `FONT_FAMILY_STACK` | `--font-sans` | **逐字符一致 ✓ 这条是通的** |
| U-3 | 语义色多值 | `SEMANTIC_SUCCESS #2e9e6b`、`SEMANTIC_DANGER #d54941`、`SEMANTIC_WARNING #b07d1a`、`SCORE_HOT #157347`、`SCORE_COLD #b42334` | `--success #2e9e6b` ✓同值；`--tone-good #009965` **第二绿**；`--destructive #ee3439` + `--tone-bad #e7000b` **第二/第三红**；**warn 无对应** | 同语义 2–3 个色值并存 = 「先经中央」在色层未落地 |
| U-4 | **值册注释的可读性断言不成立** | 值册注：「warning 取暗琥珀，**浅底上 ≥4.5:1**」 | — | **实算打脸**：`#b07d1a` on `#fafbfc` = **3.50**、on 14% 自身面 = **3.01**，均 < 4.5。同注下的 `TEXT_SECONDARY #576272` = **5.98 on card ✓ 达标**（该条断言成立） |
| U-5 | 洗色四 token | `derive_wash_tokens('#318ce7')` | 注释四值 | **逐字符一致 ✓ 通的**（这是唯一一条已验证的真同步） |
| U-6 | 分隔线口径 | `DIVIDER` 用 `accent **22%**`（注：替代旧 14% 淡线） | `tone-face-*` 仍 **14%**、`--border` 淡 | 政策漂移。但**不能直接照搬**：实算 accent 14/22/30% on card = 1.04/1.06/1.08，都远低 3:1，说明该口径是"清晰度"取向不是可达标手段 → 记为**裁决点** |

> **U-4 是本席最有价值的一条**：中央值册里已经有一条**写错的可读性断言**。若主会话照「统一 = 无脑采用值册值」去改 webui 的 `--tone-warn → #b07d1a`，会把 2.66 变成 3.01，**仍然不达 AA 而账面像已修**。必须按 §3.3(a) 的 `#975820`。

---

## 6. 字号阶梯真实可读性

### 6.1 五档实值与行高（实算自 `index.css:237-262` 字面量）

| utility | font-size | line-height | 倍数 | 判定 |
|---|---|---|---|---|
| `fs-page` | 1.125rem = **18px** | 1.75rem = 28px | 1.556 | ✓ |
| `fs-card` | 0.875rem = **14px** | 1.375rem = 22px | 1.571 | ✓ |
| `fs-body` | 0.8125rem = **13px** | 1.25rem = 20px | 1.538 | ✓ |
| `fs-caption` | 0.75rem = **12px** | 1.125rem = 18px | 1.500 | ✓ **恰在地板** |
| `fs-num` | 1.875rem = **30px** | 2.375rem = 38px | **1.267** | 数字大字，可接受 |

- 注释文档值（`index.css:228-232`）与字面量**逐档一致 ✓ 无文档漂移**。
- **最小档 12px = 达标**（`≥12px` 判据通过），且与值册「小件下限 12」口径一致 ✓。
- 密集文字面清点：`logs.tsx:299` 整个日志流 = `font-mono fs-caption`（12px/18px，等宽 12px 中文偏小但可读地板线上，**判定：达线、不建议再降**）；`latency.tsx` 全表 fs-caption；`tokens.tsx:48-66` 族行 = 三列并排 fs-caption。**没有任何一档低于 12px，也没有 `text-[..px]` 任意值**（机器门已拦，实跑 exit 0）。
- `fs-caption` 12px/1.5 是全站使用位点最多的一档（≥48 处），它同时也是**唯一大量承载中文正文的档**（日志正文、释义、描述）→ 中文 12px 在 1.5 倍行距下处于"可接受偏紧"。**裁决点**：是否把 `fs-caption` 提到 12.5px 或把日志正文升 `fs-body`。这是产品判断，不是缺陷。

### 6.2 `fs-num` 的 `tabular-nums` 是唯一自带者

`index.css:257-262` 只有 `fs-num` 带 `font-variant-numeric: tabular-nums`；其余四档靠调用方手写 `tabular-nums` 类。清点：**23 处** `fs-caption … tabular-nums` 手抄，**另有若干纯数字列漏写** → 见 F11-16（心跳章宽度抖动，实测文本每秒变长内容）。

### 6.3 CardTitle 行高冲突（**并发席已修，本席不重复记账**）

`card.tsx` mtime 16:46:37，现状：
```
30: // 基类不得带行高类：twMerge 识别不了自定义 @utility fs-*，内建行高工具类会在
31: // 产物层叠中恒压过调用方传入的 fs-card（行高塌陷为 1，多行标题粘连）。行高单一来源=fs-* 阶梯。
34:   return <div data-slot='card-title' className={cn('font-semibold', className)} ...
```
→ `leading-none` 已除。**但根因（`cn()` 用裸 `twMerge`，不识别 `fs-*`）未修** → 同类残余仍在。

### 6.4 同类残余 + 中英混排等宽（新记账）

**根因**：`webui/src/lib/utils.ts:5` = `twMerge(clsx(inputs))`，**未 `extendTailwindMerge`** → `fs-*` 对 tailwind-merge 是未知类，**不参与冲突消解**。

残余双声明点（实算锚，全部 grep 复核）：
- `settings-dialog.tsx:140` `fs-caption leading-relaxed`（行高 18px vs 12×1.625=19.5px 打架）
- `logs.tsx:320` `fs-caption leading-relaxed`（同上）
- 字重双声明 **15 处** `fs-caption font-medium` / `fs-body font-medium`（`fs-*` 自带 400/600，`font-medium` = 500）：`patterns.tsx:115/151/162`、`badge.tsx:9`、`button.tsx:9`、`affinity.tsx:38/85`、`calls.tsx:35/109`、`dashboard.tsx:63`、`latency.tsx:25`、`memory-graph.tsx:246`、`tokens.tsx:50/99/100`。

**胜者是谁？静态算不出**（要构建产物的 utilities 层内次序）——但**修法与层叠顺序无关**：

```ts
// lib/utils.ts —— 中央一处收口
import { extendTailwindMerge } from 'tailwind-merge';
const twMerge = extendTailwindMerge({
  extend: { classGroups: { 'font-size': ['fs-page', 'fs-card', 'fs-body', 'fs-caption', 'fs-num'] } },
});
// tailwind-merge 默认 conflictingClassGroups 已含 'font-size' -> ['leading']，
// 注册后 fs-* 会自动吃掉同串后/前的 leading-* 类，行高单一来源回到 fs-*。
```
字重那 15 处**不由此解决**（font-size 组默认不冲突 font-weight）→ 需要用户裁决「五档阶梯要不要带字重变体」（如 `fs-caption-strong`），或删掉 `font-medium`。**记为裁决点，不擅改。**

**等宽栈无 CJK 兜底（量化）**：`--font-mono` = `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace` —— **五个成员全无 CJK 字形**。Windows 实落到 Consolas。日志正文（`logs.tsx:299` 整块 `font-mono`）与释义大量中文 → **中文落到 CSS `monospace` 通用族 = Chrome/Windows 默认 `Courier New`**，Courier New **亦无中文** → 再落到系统 fallback。结果：一行日志里 **ASCII 用 Consolas、中文用系统兜底字**，两套字形/字宽/基线混排。
`tokens.tsx:151 fontFamily:'monospace'` 更直接：竖排 Y 轴是 **category 轴（模型族名）**，缺名时 `tickFormatter` 回 `t('tokens.noFamily')` = **「（无模型名）」五个中文**（`locales/zh-CN/common.json:144` 实读）→ 五个中文在 UA `monospace` 栈里渲染，宽度不可控且**与全站 `--font-mono` 不同字**。

改法：
1. `--font-mono` 改指值册 C9 并**追加中文兜底**：`"Cascadia Mono", Consolas, "JetBrains Mono", "Microsoft YaHei Mono", "Microsoft YaHei", monospace`（并在 U-2 下登记为两域共用值）。
2. `tokens.tsx:151` 删 `fontFamily` 字面量（宪法应扩一条禁内联 `fontFamily`，见 §11 L-5）。
3. 中文正文不进 mono 块：日志行内 `message` 段（`logs.tsx:306`）去掉 mono，只给时间戳/来源/ID 列留 mono。

---

## 7. 状态可视化的非色彩冗余

| 状态面 | 文字 | 图标 | 形状 | 判定 |
|---|---|---|---|---|
| `CategoryChip`（日志级别/渠道状态/档位） | ✓ label 就是状态词 | ✗ | ✗ | **可接受**（色 + 文双通道） |
| 日志连接态 `statusTone` | ✓ | ✗ | ✗ | 可接受 |
| **总览健康检查章** `dashboard.tsx:145` | ✗ **`label={name}` 只有检查项名，status 值一个字都不渲染** | ✗ | ✗ | **P1：颜色独占 + 二值坍缩**（见 F11-06） |
| 图谱 5 类节点 `memory-graph.tsx:128/199` | ✓ 标签在色点旁 | ✗ | ✗ **五枚全 `rounded-full`** | **P2：类型色是画布内唯一通道**（旁注文字是类别名，但画布里的点只有色） |
| 语义态卡 `semantic-state.tsx` | ✓ | ✓ ServerOff/KeyRound/DatabaseZap/TriangleAlert/RotateCcw 五形各异 | ✓ | **做得好**：五态五形+五文案，色只是加成 |
| 徽章 `hot_reload` 三态 | ✓ 可热重载/需重启 | ✗ | ✗ | 可接受；`null → 不渲染`（三态严格）✓ 符合「不造数」 |

### 7.1 `—` 与 `0` 的视觉区分（「不造数」原则的视觉端）

**做得对的部分（清点 9 处，全部 `null → '—'`、`0 → '0'`）**：`format.ts:4`（`formatInt` NaN/null/undefined → `—`）、`:9 formatMs`、`:15 formatUptime`、`:29/:37` 日期、`tokens.tsx:61/190`、`latency.tsx:30/33`、`dashboard.tsx:70/74`、`calls.tsx:199`、`latency.tsx:25`。

**两处反例（造出了"看起来像数据的无数据"）**：
1. `tokens.tsx:34/40` `?${block.unknown_rows}` / `~${block.unknown_rows}` —— 条件只有 `quality !== 'complete'`，**没有 `unknown_rows > 0` 的门**。若后端返回 `quality='partial'` 且 `unknown_rows=0`，界面渲染出 **「~0」/「?0」**：一个表示"没有任何未上报行"的零被画成了缺陷计数。→ **F11-17**。
2. 同处的 **`?` 与 `~` 两字符区分「完全未知」vs「部分未知」**：字号 12px、`font-normal`、`Badge variant='outline'`（无边底），**无 title、无图例、无文字**。两个近似标点承担一档语义分级 = 误读面。建议改 `?` → 「全未知」、`~` → 「部分」文字章，或至少补 `title` + 卡顶图例（卡顶已有 `tokens.qualityHint` 一句话，**部分缓解**，如实记录）。

### 7.2 「未知态被画成正常态」的逻辑缺陷（P1，视觉端后果）

`latency.tsx:13-19`（锚 `function stateTone(state: string, consecutiveFails: number): Tone {`）：
```
15: if (consecutiveFails > 0 || includes('fail'|'dead'|'error')) return 'bad';
16: if (includes('degrade'|'timeout'|'slow')) return 'warn';
17: if (!state) return 'flat';
18: return 'good';          // <== 任何未列举的字符串一律绿
```
后端 `channel_health` 的 state 是**开放字符串**。今天出现 `"cooling"` / `"rate_limited"` / `"circuit_open"` / `"ok_cached"`，**全部渲染成绿色「正常」**。这比"颜色不好看"严重：它是把**未知当已知**画出来，直接违反项目「判不出就诚实落未识别、绝不编数」的立身原则（视觉端）。
改法：把兜底从 `'good'` 改成 `'flat'`，并让 `'good'` 只在白名单命中（`ok`/`healthy`/`active`/`normal`…）时返回——**白名单而不是黑名单**，这样新状态默认落"灰=我不认识"。

同类（较轻）：`dashboard.tsx:145` `status === 'ok' ? 'good' : 'bad'` —— 反向错误，`unknown`/`degraded` 一律**红**。这条是"过报"不是"瞒报"，危害小于 F11-05，但同属二值坍缩家族，一起修最省。

---

## 8. 聚焦可见性（focus-visible）

### 8.1 清点（17:04 复核）

| 类别 | 数量 | 焦点样式来源 | 实算可见性 |
|---|---|---|---|
| `<Button>` 组件实例 | **18 处使用点 / 6 文件** | 基类 `button.tsx:9` `outline-none` + `focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]` | ring/50 on card **1.78 亮 / 2.25 暗**；on primary **1.00** |
| `<Badge>`（含 `asChild` 包链接） | 基础串 `badge.tsx:9` 自带同款 ring | 同上 | 同上 |
| 裸 `<button>` | **10 个**（`patterns.tsx:147,158`、`affinity.tsx:82`、`calls.tsx:30,106`、`knowledge.tsx:52,219`、`memory-graph.tsx:116,124`、`tokens.tsx:93`） | **无 focus-visible 覆写**，靠全局 `* { outline-ring/50 }` + UA 默认 | **1.78 / 2.25**，且 UA 描边样式跨浏览器不一致 |
| `<select>` | **2 个**（`logs.tsx:246,258`） | 同上（无任何 focus 类） | **1.78 / 2.25** |
| `<input>` | **5 个**（`settings-dialog.tsx:101,119`、`knowledge.tsx:201`、`memory-graph.tsx:140`；均 `outline-none` + `focus-visible:ring-ring/50`） | 显式 | **1.78 / 2.25** |
| 导航 `<Link>` | **2 类**（`app-shell.tsx:22 NavSubItem`、`:34 NavItem`，共 11 个实例） | 无 focus 类，靠全局 | **1.78 / 2.25** |
| `<canvas>` | **1 个**（`memory-canvas.tsx:190`） | **无 `tabIndex` / `role` / `aria-*` / 键盘事件**（grep 全空） | **完全不可聚焦 = 键盘用户进不去** |

**结论数字**：**`outline-none` 共 5 处，5 处都有 `focus-visible:ring` 替代（无"删了焦点环不补"的硬伤 ✓）**；但**可达标（≥3:1）的焦点环 0 处**——因为 `ring/50` 本身只有 1.78/2.25，而 `--ring` 与 `--primary` 同值导致主按钮上是 1.00。

### 8.2 hover-only 信息（无触屏 / 键盘等价物）

| 类型 | 站点 | 计数 |
|---|---|---|
| `truncate` + `title=`（**全文只在悬停出现**，聚焦不弹、触屏无） | `affinity.tsx:38`、`calls.tsx:69`、`logs.tsx:304`、`memory-graph.tsx:238`、`plugins.tsx:92`、`tokens.tsx:50` | **6** |
| `title=` 承载**解释性提示**（非截断补偿） | `calls.tsx:120,125`（口径脚注 `unknownHint`/`unattributedHint`） | **2** |
| `title=` 仅承载 ID（次要） | `plugins.tsx:80`、`memory-graph.tsx:238` 等 | 3 |
| 画布节点标签 hover-only | `memory-canvas.tsx:176` | 1 |
| recharts Tooltip（`accessibilityLayer` 默认 false，未开） | `tokens.tsx:155`、`calls.tsx:170` | 2 |
| `CategoryChip` 里 `?`/`~` 无提示 | `tokens.tsx:34/40` | 1 |

**最该修的一条**：`calls.tsx:120/125` 的**统计口径脚注只在 hover 出现**。这两个数（时间戳未知数 / 不可归属数）是项目"诚实口径"的载体，鼠标党看得到、键盘与触屏看不到 = 口径披露不完整。建议改成卡内 `fs-caption text-muted-foreground` 常显行，或 `<Badge title>` 旁边直显人话。

`<canvas>` 最小可用改法：`tabIndex={0}` + `role='application'` + `aria-label` + 键盘 `+/-` 缩放与 `Tab` 走点（或**直接承认画布只读装饰、把节点清单常显成旁边的可聚焦列表**——后者更省且已在做：`selectedNode` 详情卡就是，只是必须**能选中**才能出现）。

---

## 9. 动效与 `prefers-reduced-motion` / SSE 抖动

### 9.1 reduced-motion：**webui 侧 0 守卫**

```
grep -rn "reduced-motion|prefers-reduced" webui/src  →  空（0 命中）
```
在跑的动效清单（静态可枚举，全部无守卫）：

| 位置 | 动效 | 风险 |
|---|---|---|
| `skeleton.tsx:6` | `animate-pulse` = Tailwind 内建 `pulse 2s cubic-bezier(0.4,0,0.6,1) infinite`（**opacity 0.5↔1 无限闪**） | **最高**：无限动画，且每页 loading 都会出现 |
| `theme-switch.tsx:19,20` | `transition-all` + `dark:scale-0/-rotate-90` ↔ `scale-100/rotate-0`（**90° 旋转 + 缩放**） | 中高：旋转缩放正是前庭敏感触发项 |
| `button.tsx:9` | `transition-all` | 低（150ms） |
| `badge.tsx:9` | `transition-[color,box-shadow]` | 低 |
| `calls.tsx:35`、`app-shell.tsx:22,34` | `transition-colors` | 低 |

**对照渲染域**：AGENTS/HANDBOOK 明载渲染域「reduced-motion 守卫根修」已入库（#26、E01 批「reduced-motion 死 CSS 修复」）。→ **同一产品，卡片渲染域有守卫、webui 一个都没有**，这是"统一"在动效层的空洞。

**改法（一处收口，追加到 `index.css` 末尾）**：
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```
`theme-switch` 的 rotate/scale 属"状态指示"不是装饰，减动效后仍要能区分明暗 → 保留 `scale` 切换但去掉过渡时长即可（上面的规则已覆盖）。**这条改动本身可被机器门锁**（§11 L-6）。

### 9.2 SSE / 高频更新造成的跳动（视觉端）

| 现象 | 证据 | 判定 |
|---|---|---|
| **心跳章每秒变文**：`logs.tsx:203 t('logs.heartbeatAlive', {seconds: Math.floor(heartbeatAge/1000)})`，文案 `"心跳 {{seconds}}s 前"`（`zh-CN/common.json:177` 实读），由 `logs.tsx:129 setInterval(…,1000)` 驱动 | 章体 `CategoryChip` 无 `tabular-nums`（`patterns.tsx:115` 基础串不含），sans 栈数字**不等宽** → 9→10s 进位时章宽跳变；PageHeader 的 `flex-wrap` 行内右侧四枚按钮随之**整体横移** | **P3 视觉抖动**，修法：章内那枚 `<span className='ml-1 font-normal opacity-80'>` 加 `tabular-nums`；更稳：把秒数钉宽 `min-w-`（但要守 4px 栅格）。**opacity-80 另有对比度问题：实算 4.16（暗）低于 4.5 → 见 F11-14** |
| **整页每秒重渲染**：`nowTick` state 变化 → `LogsPage` 全组件 re-render（含最多 500 行日志 DOM） | `logs.tsx:129` + `:52 nowTick` | 归 **F8 性能席**；视觉端只记"重渲染不产生颜色/几何变化，故**无闪烁**"（如实不夸大） |
| `aria-live='polite'` 挂在**整个 500 行滚动容器**（`logs.tsx:299`） | 每条新日志都进 SR 播报队列，500 行裁剪时更易炸 | 归 F3 a11y 席；视觉端记一句不重复 |
| 自动滚底 `listEndRef.current?.scrollIntoView({block:'end'})`（无 `behavior`） | 瞬时跳到底部 | 减动效语境下**反而正确**；不记 |
| dashboard 六枚 `StatCard` 每 30–60s refetch，`fs-num` 数值直变 | `dashboard.tsx:93-99` | 无过渡动画 = 无闪；数字跳变属预期 |

---

## 10. 新发现台账（七要素）

> 严重度：**P1**=必修（真不达 AA/把未知画成已知/键盘进不去）；**P2**=应修；**P3**=打磨。**「有无锁」列**：无 = 改坏了没人拦。

| # | 严重度 | 坐标 | 锚点字符串 | 根因 | 建议改法 before → after | 验证命令 | 锁 |
|---|---|---|---|---|---|---|---|
| **F11-01** | **P1** | `webui/src/index.css:34`（+消费面 `components/ui/button.tsx:13`、`ui/badge.tsx:13`、`pages/tokens.tsx:99`、`pages/calls.tsx:36`、`components/layout/app-shell.tsx:34`） | `--primary-foreground: oklch(1 0 0);` | 亮态品牌蓝 `#318ce7` 亮度不足以承载白字：**实算 3.48:1**（hover `/90` 更差 3.06），6 个面全中 | `--primary-foreground: oklch(1 0 0);` → **保留**，`:root` 新增 `--primary-strong: oklch(0.569 0.1608 252);`、`--primary-ink: oklch(0.561 0.1608 252);`，`.dark` 新增 `--primary-strong: oklch(0.601 0.1427 250.8); --primary-ink: var(--primary);`；`@theme inline` 加 `--color-primary-strong/--color-primary-ink`；六处 `bg-primary`→`bg-primary-strong`、四处 `text-primary`→`text-primary-ink`。**本命色 `--primary` 一字节不动** | `node "$TEMP/f11/verify_fix.py"` 期望 `#ffffff on #1678d2 = 4.50:1 OK`；`node scripts/layout-constitution.mjs` 仍 0 违例 | **无** |
| **F11-02** | **P1** | `webui/src/index.css:266-271` | `--tone-good: oklch(0.596 0.145 163);` 起六行（`:root` 块内） | **亮/暗 tone 策略不对称**：`.dark` 六枚全提到 L≈0.73–0.86（暗底 AA），`:root` 六枚仍是 L≈0.50–0.67 饱和中明度，落在亮底 + 自身 14% 洗底上只有 **2.66–4.33**；六枚章体是全站唯一的级别/状态载体 | `:root` 六枚按 §3.3(a) 表整体压暗：`--tone-good→oklch(0.501 0.1015 163)`、`--tone-warn→oklch(0.522 0.1074 58)`、`--tone-bad→oklch(0.529 0.196 27.3)`、`--tone-info→oklch(0.5 0.1072 242.7)`、`--tone-purple→oklch(0.534 0.1875 299.5)`（**须从 `var(--sk-purple)` 拆成字面量，否则污染 `@theme` 的 `--color-sk-purple`**）、`--tone-magenta→oklch(0.538 0.2358 320.4)` | `node "$TEMP/f11/verify_fix.py"` 六行全 `OK`；或 `node "$TEMP/f11/pairs2.py" \| grep "C tone章"` 无 FAIL | **无** |
| **F11-03** | **P1** | `webui/src/pages/tokens.tsx:155`、`159`；`pages/calls.tsx:170` | `<Tooltip` / `<Legend />` | recharts `DefaultTooltipContent` 的 `itemStyle.color = entry.color`、`DefaultLegendContent` 的 `labelStyle.color \|\| entry.color` → **序列色被当成正文色**画在 `var(--card)` 上：亮 chart-4 **2.74**/chart-5 **2.84**，暗 chart-6 **2.00**/chart-5 **2.65** | `<Tooltip contentStyle={{…无 color}}>` → `contentStyle={{…, color:'var(--card-foreground)', whiteSpace:'normal'}} itemStyle={{ color:'var(--card-foreground)' }}`；`<Legend />` → `<Legend formatter={(value) => <span className="fs-caption text-card-foreground">{value}</span>} />` | 复算：`node "$TEMP/f11/pairs2.py"` 中 `text` 判据的 chart-* 行改为 `card-foreground on card`=13.67；或改后跑 `grep -c "itemStyle" webui/src/pages/*.tsx` = 2 | **无** |
| **F11-04** | **P1** | `webui/src/index.css:201`；`components/ui/button.tsx:9`；`ui/badge.tsx:9`；`components/settings/settings-dialog.tsx:106,127`；`pages/knowledge.tsx:205`；`pages/memory-graph.tsx:144` | `@apply border-border outline-ring/50;` 与 `focus-visible:ring-ring/50 focus-visible:ring-[3px]` | `--ring` 与 `--primary` **同值**（`index.css:49/34`），50% alpha 后再叠同色底 → 实算亮 **1.78** / 暗 **2.25**；**落在 `bg-primary` 上 = 1.00 完全隐形**。10 个裸 `<button>` + 2 个 `<select>` + 2 类导航 `<Link>` 只有这个描边 | `* { @apply border-border outline-ring/50; }` → 拆两行：`* { @apply border-border; outline: 2px solid transparent; outline-offset: 2px; }`；`button.tsx:9`/`badge.tsx:9`/四处 input 串里 `focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]` → `focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground` | `node "$TEMP/f11/pairs2.py" \| grep "E 边框焦点"` 看 `ring(不透明)` 行（3.36/4.80）；grep 全树 `ring-ring/50` 命中应为 0 | **无** |
| **F11-05** | **P1** | `webui/src/pages/latency.tsx:13-19` | `function stateTone(state: string, consecutiveFails: number): Tone {` | 兜底分支 `return 'good'`：**未列举的 state 字符串一律绿**。`channel_health.state` 是开放字符串 → 未来出现 `cooling`/`rate_limited`/`circuit_open` 会被画成「正常」= **把未知当已知**，违反项目「判不出即诚实落未识别」红线 | `if (!state) return 'flat';  return 'good';` → `const GOOD = new Set(['ok','healthy','normal','active']); if (!state \|\| !GOOD.has(lowered)) return 'flat'; return 'good';`（**白名单取代黑名单兜底**） | `grep -n "return 'good';" webui/src/pages/latency.tsx` 前面必须出现白名单判定；离线单测：`stateTone('circuit_open', 0) === 'flat'` | **无** |
| **F11-06** | **P1** | `webui/src/pages/dashboard.tsx:145` | `<CategoryChip key={name} label={name} tone={status === 'ok' ? 'good' : 'bad'} />` | **状态值一个字都不显示**（label 只有检查项名），健康状态**颜色独占**；且 `unknown`/`degraded`/`timeout` 全坍缩成红 `bad`（与 F11-05 相反的失配方向） | `label={name} tone={status === 'ok' ? 'good' : 'bad'}` → `label={`${name} ${status}`} tone={status === 'ok' ? 'good' : (status === 'unknown' \|\| status === 'unavailable' ? 'flat' : 'bad')}` | `grep -c "label={name}" webui/src/pages/dashboard.tsx` = 0；真机目验章内出现状态词 | **无** |
| **F11-07** | **P2** | `webui/src/index.css:48`（+消费面 `settings-dialog.tsx:106,127`、`knowledge.tsx:205`、`memory-graph.tsx:144`、`logs.tsx:249,261`） | `--input: oklch(0.889 0.0099 252.8);` | `--input` 与 `--border` **同值**（`:47-48`），实算描边 on card **1.35 亮 / 1.56 暗**，远低于 1.4.11 的 3:1；输入框边界是**识别控件所必需**，不能按装饰豁免 | `.dark` 外**只改 `--input`**：`:root --input: oklch(0.66 0.0099 252.8);`（→ 3.00）、`.dark --input: oklch(0.554 0.0258 273.4);`（→ 3.00）。**`--border` 保持淡值不动**（装饰件） | `node "$TEMP/f11/verify_fix.py"` 的 `input 描边 on card` 两行 = `3.00 OK` | **无** |
| **F11-08** | **P2** | `webui/src/pages/tokens.tsx:161`（`fill={\`var(--${TOKEN_COLORS[key]})\`}`）、`components/graph/memory-canvas.tsx:163-166` | `TOKEN_COLORS: Record<TokenKey, string> = {` | 堆叠四段**只靠颜色区分**，相邻段实算 **1.02–2.54**；暗态 chart-5/6 直接复用亮态 `--sk-purple/--sk-deep` 值（`index.css:112-113`）→ 暗底上 2.00–2.65；无图案/无描边分隔/无末端直标 | 最小改动：`<Bar … fill=… />` → `<Bar … fill=… stroke="var(--card)" strokeWidth={1} />`（**用卡色描边切开相邻段**，不新增色值即解 1.02 相邻对）；进一步：`<Legend iconType="circle"/>` → 四类各用异形；canvas 节点 `context.arc` 按 type 改 5 种形状（圆/方/三角/菱/星） | `grep -c "stroke=\"var(--card)\"" webui/src/pages/tokens.tsx` ≥1；**色盲模拟须目验**（§12） | **无** |
| **F11-09** | **P2** | `webui/src/index.css` 文件末（现 `:323`）；`components/ui/skeleton.tsx:6`；`components/theme-switch.tsx:19-20` | `animate-pulse` / `transition-all` | **webui 全树 0 处 `prefers-reduced-motion`**（grep 实跑为空），而渲染域已做该守卫 → 同产品双标。`animate-pulse` 是 `opacity 0.5↔1 infinite`，theme-switch 是 90° 旋转+缩放 | `index.css` 末尾追加 §9.1 的 `@media (prefers-reduced-motion: reduce)` 全局块（5 行） | `grep -c "prefers-reduced-motion" webui/src/index.css` ≥1 | **无** |
| **F11-10** | **P2** | `webui/src/index.css:291-293` | `@utility tone-face {` | 引用了**从未定义**的 `var(--tone)`（`:root`/`.dark` 均无，themadiff 第 5 节实测输出「悬空引用 = --tone」）→ 声明被丢弃、`tone-face` 恒为透明底。当前 0 消费点 = **埋在六枚 `tone-face-*` 旁边的同名公共入口陷阱** | 二选一：① 删 `291-293` 三行；② 在 `:root` 与 `.dark` 各定义 `--tone: var(--muted-foreground);` 让它真能用。**推荐 ①**（未用即删，不留可选歧路） | `node "$TEMP/f11/themadiff.py" \| sed -n '/悬空/,+2p'` 输出「（无）」 | **无** |
| **F11-11** | **P2** | `webui/src/index.css:180`；`webui/src/pages/tokens.tsx:151`；`pages/logs.tsx:299` | `--font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;` | ①与值册 C9 `MONO_FONT_STACK`（`"Cascadia Mono",Consolas,"JetBrains Mono","Courier New",monospace`）**不同源**；②**两栈都无 CJK 兜底**（值册 FONT_FAMILY_STACK 有 YaHei/PingFang，但那是 sans 不是 mono）→ 一行日志里 ASCII 用 Consolas、中文用 UA 兜底，字宽/基线不一；③`fontFamily:'monospace'` 字面量绕过 token，而该轴 category 缺名时显示中文「（无模型名）」(`locales/zh-CN/common.json:144`) | `--font-mono:` → `"Cascadia Mono", "Consolas", "JetBrains Mono", "Microsoft YaHei Mono", "Microsoft YaHei", ui-monospace, monospace`（并在值册 C9 同步补 CJK 兜底，走 U-2 统一）；`tick={{ fill: 'var(--muted-foreground)', fontFamily: 'monospace' }}` → `tick={{ fill: 'var(--muted-foreground)' }}`；日志行 `message` 段去 `font-mono`（时间戳/来源/ID 列保留） | `grep -c "fontFamily" webui/src/pages/*.tsx` = 0；`grep "YaHei" webui/src/index.css` 在 `--font-mono` 行命中 | **无** |
| **F11-12** | **P2** | `webui/src/index.css:237-262` ↔ `plugins/bot_unified_runtime/domains/render/card_render/theme_tokens.py:213-219` | `@utility fs-page {` ↔ `TYPE_SCALE_PX: dict[str, int] = {` | **同一产品两套"五档"字号**：值册 `{26,20,15,13,12}`、webui `{30,18,14,13,12}`，**交集只有 {12,13}**。而 `index.css:226` 自称「版式宪法（…全站强制）」 | **这是裁决点，不是本席能定的**。三条路：①值册扩到八档（并入 webui 的 14/18/30）；②webui 改用值册五档（视觉会变，18→20、14→15、30→26）；③显式登记「两套并存 + 各自适用面」并各自主动引用对方（最省事，但"统一"就要写清边界）。**任一方案落地后必须上锁 §11 L-7** | 对表脚本：`node/python "$TEMP/f11/central.py" \| sed -n '/ladder diff/,+14p'` | **无** |
| **F11-13** | **P3** | `webui/src/lib/utils.ts:5`（根因）；残余点 `components/settings/settings-dialog.tsx:140`、`pages/logs.tsx:320`；字重类 15 处见 §6.4 | `export function cn(...inputs: ClassValue[]) {` | 裸 `twMerge` **不识别自定义 `@utility fs-*`** → `fs-caption` 与 `leading-relaxed` 同行时不参与冲突消解，胜者由产物层叠顺序决定（**静态算不出，需构建产物**）。`CardTitle` 那枚已被并发席在 16:46 手工摘掉（本席不重复记账），**根因未修所以同类仍在** | `import { twMerge } from 'tailwind-merge';` → `import { extendTailwindMerge } from 'tailwind-merge';` + `const twMerge = extendTailwindMerge({ extend: { classGroups: { 'font-size': ['fs-page','fs-card','fs-body','fs-caption','fs-num'] } } });`（默认 `conflictingClassGroups['font-size'] = ['leading']` 自动接管）。**字重 15 处不由此解决** → 需用户裁「五档是否带 `-strong` 变体」，本席只登记 | `grep -c "extendTailwindMerge" webui/src/lib/utils.ts` = 1；**实际层叠结果需构建产物目验**（§12） | **无** |
| **F11-14** | **P3** | `webui/src/pages/logs.tsx:201` | `<span className='ml-1 font-normal opacity-80'>` | `opacity-80` 让 `muted-foreground` 在 good 章 14% 洗底上掉到 **4.16（暗）**，从"刚好达标"翻到"不达"（同处若不降透明是 5.02）。同时秒数不等宽致章宽抖动 | `opacity-80` → 删除（改 `text-muted-foreground` 已够次要）+ 加 `tabular-nums`；`font-normal` 保留 | `node "$TEMP/f11/pairs2.py" \| grep "opacity-80"` 该行从表内消失即达成；`grep -c "opacity-80" webui/src/pages/logs.tsx` = 0 | **无** |
| **F11-15** | **P3** | `webui/src/pages/memory-graph.tsx:133` | `className={typesHidden.has(type) ? 'opacity-40' : undefined}` | `opacity-40` 不是 disabled，是**可点的状态开关**，其文字承载"该类型当前不显示"的信息 → 实算 **1.69（亮）/ 2.15（暗）**，真 1.4.3 失败 | `opacity-40` → 去透明度，改形态表达隐藏态：`className={typesHidden.has(type) ? 'border-dashed opacity-100 ring-1 ring-inset ring-border' : undefined}`（或最保守 `opacity-70`，实算 3.1 仍不达，故推荐形态通道） | `grep -c "opacity-40" webui/src/pages/memory-graph.tsx` = 0 | **无** |
| **F11-16** | **P3** | `webui/src/components/graph/memory-canvas.tsx:190-223` | `<canvas` | 画布**无 `tabIndex` / `role` / `aria-*` / 键盘处理**（grep 全空），节点标签 `hover 或 k≥1.6 才显`（:176）→ 键盘与触屏用户**既聚焦不了也看不到标签**，详情侧栏永远出不来 | `tabIndex={0}` + `role='application'` + `aria-label={t('memoryGraph.canvas')}` + `onKeyDown`（`+`/`-` 缩放、方向键平移）；或退一步：把"点选节点"换成可聚焦的节点清单 `<button>` 列表（`selectedNode` 详情卡已存在，只缺入口） | `grep -c "tabIndex" webui/src/components/graph/memory-canvas.tsx` ≥1 | **无** |
| **F11-17** | **P3** | `webui/src/pages/tokens.tsx:29-43` | `function qualityBadge(block: TokenBlock) {` | 门只判 `quality !== 'complete'`，**不判 `unknown_rows > 0`** → `partial`+`unknown_rows=0` 会渲染 **「~0」/「?0」**：把"零条缺陷"画成缺陷计数，与项目「不造数」口径冲突。且 `?` vs `~` 两个近似标点独担一档语义，**无 title、无图例**（卡顶 `tokens.qualityHint` 仅一句话，部分缓解） | `if (block.quality === 'unknown') {` → `if (block.quality === 'unknown' && block.unknown_rows > 0) {`（外层先加 `if (!block.unknown_rows) return null;`）；两枚标点改可访问文案：`全未知 N` / `部分未知 N` | `grep -n "unknown_rows > 0" webui/src/pages/tokens.tsx` 命中 ≥1；F13（指标语义席）交叉对表 | **无** |
| **F11-18** | **P3** | `webui/src/index.css:11/19-22/25-26/57-64` | `--radius: 14px;` | 死键/未覆写陷阱清点：`--radius`（**全树 0 引用**，半径实走 `--r-shell/panel/tile`）、`--wash-1/2/3/mist` 与 `--sk-deep/--sk-purple`（**`.dark` 未覆写**，且 `@theme` 有 `--color-sk-*` → 谁写 `bg-sk-purple` 暗态就静默留亮色）、`--popover*`（4 处 tsx 消费 = 0）、`--sidebar-primary*`/`--sidebar-ring`/`--sidebar-border`（消费 0） | 三条一起做：①删 `--radius`；②给 `.dark` 补 `--sk-deep/--sk-purple/--wash-*` 覆写（**或直接删这些不消费的**）；③`@theme inline` 里把无消费点的转发（`--color-sk-*`、`--color-popover*`、`--color-sidebar-primary*`、`--color-sidebar-ring/border`）裁掉，减少可误用面 | `node "$TEMP/f11/themadiff.py" \| sed -n '/.dark 缺/,/无/p'` 差集只剩非色键 | **无** |
| **F11-19** | **P3** | `webui/src/pages/calls.tsx:120,125` | `<Badge variant='outline' title={t('calls.unknownHint')}>` | **统计口径脚注 hover-only**：`native title` 不随键盘焦点弹、触屏无 → 键盘/触屏用户拿不到"时间戳未知/不可归属"这两个诚实口径的解释 | `title={t('calls.unknownHint')}` 之外**再加常显说明行**：徽章下方 `<p className='fs-caption text-muted-foreground'>{t('calls.unknownHint')}</p>`（或把徽章 label 直接写成人话短语） | `grep -n "title={" webui/src/pages/calls.tsx` 命中处附近必须存在非 hover 的等价文案 | **无** |
| **F11-20** | **P3** | `webui/src/lib/format.ts:5,31,39,48` | `return value.toLocaleString('zh-CN');` | 语言**硬编码 zh-CN**：界面切到 `en`（`locales/en/common.json` 存在，i18n 可切）后日期/数字仍出中文格式（如 `formatDateTime` 的 zh-CN 全格式串）→ **视觉上的中英混排不一致** | 各 `toLocaleXxx` 的语言参数从 `i18n.language` 取（或在 `format.ts` 顶部注入 `const LOCALE = () => i18n.language ?? 'zh-CN'`） | 切 en 后目验日期串；或单测断言 `formatDateTime` 随 language 变 | **无** |

### 10.1 值册侧新账（不属 webui，但由本席实算揭出）

| # | 严重度 | 坐标 | 锚点字符串 | 根因 | 建议改法 | 验证命令 | 锁 |
|---|---|---|---|---|---|---|---|
| **F11-C1** | **P1**（对本席是"修 webui 时的前提"） | `plugins/bot_unified_runtime/domains/render/card_render/theme_tokens.py:247`（`SEMANTIC_WARNING` 上方注释段） | `SEMANTIC_WARNING = "#b07d1a"` | 同行注释主张「warning 取暗琥珀，**浅底上 ≥4.5:1**」，**实算打脸**：`#b07d1a` on `#fafbfc` = **3.50**、on 自身 14% 洗底 = **3.01**，两者都 < 4.5。若主会话按「统一 = 采用值册值」把 webui `--tone-warn` 改成 `#b07d1a`，**会把 2.66 抬到 3.01 却仍不达 AA，而账面像已修** | 先修注释或先修值：①改注释口径为「卡内 13px+ 大字/描边用」；②值册新增 `SEMANTIC_WARNING_INK = "#975820"`（实算 on card 5.46 / on 14%面 4.51），webui `--tone-warn` 采纳 **INK 版**而非现值。**禁止把现 `SEMANTIC_WARNING` 直接当 webui 文字色** | `node "$TEMP/f11/central.py" \| sed -n '/register colors as candidate/,+12p'`；`node "$TEMP/f11/final_solve.py"` 的 warn 行 | **无**（值册有 `verify_hashes.py` 哈希锁，改此常量会撞哈希门 → 需 `--write` 重录，属收口波动作） |
| **F11-C2** | P3 | `theme_tokens.py:216-220`（`TEXT_SECONDARY` 定义处） | `TEXT_SECONDARY = "#576272"` | 注释断言「三档表面上对比 ≥4.5:1（WCAG AA@12px）」——**本席复算成立（on card 5.98 / on 14%面 4.93）**，该条**可信**。但 webui 用的是 `#5a617c`（5.91），两域**各推各的次灰**，属 U-3 类漂移 | webui `--muted-foreground` 采纳值册 `TEXT_SECONDARY`，换算式：`:root --muted-foreground: oklch(0.4927 0.0291 257.7);`（往返自校验 `back=#576272 OK`）；`.dark` 保持现有 `#b3b7bc` 不动 | `node "$TEMP/f11/central.py"` 的次灰行；改后 `node "$TEMP/f11/pairs2.py" \| grep "muted-foreground"` 全 PASS | **无** |

---

## 11. 锁：可加锁项与断言草案

### 11.1 既有门现状（实跑）

```
$ cd webui && node scripts/layout-constitution.mjs
版式宪法机器门：全部通过（hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0）
GATE_EXIT=0
```

**它算对比度吗？不算——一行都不算。** 该门只做 6 条正则（`HEX` / `OFF_LADDER_TEXT` / `INLINE_FONT_SIZE` / `OFF_SCALE_SPACING` / `OFF_SCALE_ARBITRARY` / `PALETTE_CLASS`），全是"字符串层禁什么"。所以：**上面 20 条 P1/P2 里，任何一条改坏了它都照样打 exit 0** —— 这就是「统一」缺牙口的实证。

### 11.2 新增机器锁（按可自动化程度排序，全部零依赖 Node，与既有门同构）

| 锁 | 断言（伪码/正则） | 覆盖台账 | 可全自动？ |
|---|---|---|---|
| **L-1 对比度门**（**最高价值**） | 新增 `webui/scripts/contrast-constitution.mjs`：**解析 `src/index.css` 的 `:root`/`.dark`**（照抄本席 `tokens2.py` 的解析+合成+clip 逻辑，≈120 行零依赖），配一张**受控色对表**（本席 §2 的 133 组即种子），逐对算，任一 `text`<4.5 或 `ui`<3.0 → `exit 1` 并打印 `色对\|前景hex\|背景hex\|比值\|阈值\|消费锚` | F11-01/02/03/04/07/14/15、F11-C1 | **是**（前提是色对表维护得住；建议先只锁 20 个核心对，防表失控） |
| L-2 主题键集对等 | `keys(:root) ∩ 色类前缀 ⊆ keys(.dark)`，差集非空即红（白名单允许 `--r-*`/`--radius` 等非色键） | F11-18、§5.2 | 是 |
| L-3 无悬空 `var()` | `index.css` 内每个 `var(--x)` 的 `--x` 必须在 `:root` 或 `.dark` 有定义 | F11-10（`--tone`） | 是 |
| L-4 禁"序列色当文字色" | tsx 内出现 `<Tooltip` 但同元素串内无 `itemStyle` → 红；出现 `<Legend` 且无 `formatter`/`wrapperStyle` → 红 | F11-03 | 是（正则级；`/<(Tooltip\|Legend)\b(?![\s\S]{0,400}(itemStyle\|formatter))/`，需按块扫） |
| L-5 禁内联字体族 | tsx 内 `/\bfontFamily\s*:/` → 红（扩既有 `INLINE_FONT_SIZE` 那条） | F11-11 | 是 |
| L-6 reduced-motion 守卫 | 若全树出现 `/animate-\|transition-/` 则 `index.css` 必须出现 `/@media\s*\(\s*prefers-reduced-motion/` | F11-09 | 是 |
| L-7 字号阶梯单一来源 | `index.css` 内每个 `@utility fs-X{font-size:V}` 的 V(px) ∈ 值册 `TYPE_SCALE_PX`（跨语言读 py 常量，或把值册导出成 `webui/src/ladder.json` 由生成器产） | F11-12 | 是（但**要先有 U-1 裁决**，否则门一起就红） |
| L-8 焦点替代齐备 | 出现 `outline-none` 的元素串必须含 `focus-visible:outline-\|focus-visible:ring-`；且**全树不得出现 `ring-ring/50`**（半透明焦点环） | F11-04 | 是 |
| L-9 降透明只给 disabled | 同一 `className` 串内出现 `opacity-(30\|40\|50\|60\|70)` 且该元素无 `disabled:` 前缀 → 红（`disabled:opacity-50` 白名单放行，因 WCAG 豁免） | F11-14、F11-15 | 是（会有假阳性，需逐条豁免登记） |
| L-10 状态须带文字 | `CategoryChip` 的 `label` 表达式若**不含**相邻的 `status`/`state` 变量名而 `tone` 却含 → 红 | F11-06 | **半自动**（AST 更稳，正则易误判）→ 主要靠目验 |

**接入点**：`webui/package.json` 的 `"build": "node scripts/layout-constitution.mjs && vite build"` 后串一条 `&& node scripts/contrast-constitution.mjs`；Python 侧再挂进 `scripts/dev.ps1 -Task test` 的门族，防"绕过 npm"。

### 11.3 必须人工目验的（机器算不出，本席如实列明）

| # | 项 | 为什么算不出 |
|---|---|---|
| M-1 | `bg-background/80 backdrop-blur` 顶栏、`bg-card/80` 画布浮层、`bg-scrim` 遮罩上的文字（§2 表 `manual` 三行） | 底下是**滚动内容/画布像素**，非确定色；backdrop-filter 还要叠加模糊后均值 |
| M-2 | `animate-pulse` 最低相位时骨架块与卡底的可辨性 | 需运行时取 animation 相位；且 pulse 只动 opacity，本身不承载信息 |
| M-3 | `fs-*` 与 `leading-*` / `font-weight` 双声明的**实际胜者**（F11-13） | 由构建产物 utilities 层内次序决定；本席禁 `npm run build` |
| M-4 | 色盲（Protanopia/Deuteranopia/Tritanopia）下 `chart-1..6` 五/六序列是否仍可辨（F11-08） | 需色彩模拟滤镜 + 真屏；本席只给了"未加冗余通道"这一结构性事实 |
| M-5 | 中文在 `--font-mono` / UA `monospace` 下的**真实回落字形与字宽**（F11-11） | 字体解析是浏览器/系统字体栈行为 |
| M-6 | 焦点环在 Chrome/Edge/Firefox 下的**实际描边宽度与样式**（F11-04） | UA `:focus-visible` 默认描边实现不一致 |
| M-7 | 画布标签在 `k<1` 时的**实际重叠/糊成一团程度**（§4.4） | 依赖真实节点坐标分布与字体度量 |
| M-8 | 12px 中文日志（`fs-caption` + mono）在真实屏上的辨识度主观可接受性（§6.1） | 属"达线但偏紧"的产品判断，需用户裁量 |
| M-9 | `?` 与 `~`、`—` 与 `0` 在真实字号/字体下的**肉眼可分度**（§7.1） | 字形层面靠截图判定；本席只给了语义层的"是否造数"判定 |

---

## 12. 诚实缺口（本席没能算出来 / 没能审到的）

1. **未跑浏览器、未跑构建**（纪律）→ 一切**层叠胜者**与**运行时视觉**问题只给了"修法与结构判定"，最终态须由 M-1…M-9 目验。
2. **未审 `webui/dist`**（禁碰），也**未发现 dist 与 src 的漂移证据**（F4/F9 席已记「src 新于 dist」，本席不重复）。
3. **`webui/src/components/layout/error-boundary.tsx`（16:41 新建）未逐行审读**——它出现在本席快照之后。
4. **半透明叠色只做了一层合成**：`bg-primary/70` 落在 `bg-accent` 上再落 `bg-card` 的三级链本席手工指定了父底（`layer()` 的 parent 参数），**若真实 DOM 父底与本席假设不符，该行数字会偏**（已把 parent 显式写进每条，可复核）。
5. **gamut clip 模型**取"直接截断"，与 Chrome 现行 `oklch()` 实现一致，但**与 CSS Color 4 的 chroma-reduction 建议不完全一致**；`--tone-info`、`--chart-*` 等超域色在不同浏览器可能有 ±0.2 的比值漂移。
6. **placeholder 对比度**（`settings-dialog.tsx:105` 等 5 处）**未实算**：placeholder 颜色由 UA 决定（约 54% 灰），本席只按 `muted-foreground` 上界估了一行，标 manual。
7. **recharts 的 `.recharts-tooltip-wrapper` 定位**（是否会被容器裁剪、窄屏溢出）**未验证**——只静态指出了默认 `whiteSpace:'nowrap'` 未被覆盖这一条。
8. **`@theme inline` 自指写法**（`--shadow-md: var(--shadow-md)`，`index.css:192`）配合 `inline` 语义在 Tailwind v4 下成立，本席**没有构建产物可证**，故**不记为缺陷**，仅提示收口波在真产物里确认一次。

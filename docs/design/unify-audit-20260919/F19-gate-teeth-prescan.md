# F19 · 宪法门补牙预扫描（只读取证，零改动）— 2026-09-19

## 快照声明

- **时间**：`Sat Sep 19 17:13:43 2026`（最终复扫定格；17:0x 首扫与 17:13 复扫 diff=零漂移）
- **扫描器**（全部在 `%TEMP%/f19/`，源码树零残留）：
  - `f19-scan.mjs`（v1，selftest 抓到两缺陷后弃用：hsl( 漏配、rounded-sm 被单字方向组截胡静默放行）
  - `f19-scan-v2.mjs`（**最终版**，含负样本自测锁）
  - `selftest/fixture.tsx` + `selftest-out2.txt`（负样本：mt-7/-mb-2/rounded-[9px]/rounded-sm/space-x-5/rgba/hsl/cn模板串 全数命中，on-scale/on-tier 全数放行——证明正则非空转，PAGES2 教训不重演）
  - 输出件：`src-out-final3.txt`（最终明细）
- **覆盖**：`webui/src/**` **33 文件**（32 ts/tsx + 1 css）一次全量。
- **原版门现状**：`node scripts/layout-constitution.mjs` 实跑 **exit 0**（只读，未改）。
- **白名单基准=实盘**：间距栅格 `{0,1,2,3,4,6}`（=0/4/8/12/16/24px，index.css 宪法注释②+门内注释同源）；字号五档 `fs-page/card/body/caption/num`（@utility 实盘）；圆角三档 `--r-tile:14/--r-panel:18/--r-shell:30` → `rounded-md/lg/xl`（@theme inline 显式钉死；`--radius-sm:8px` 存在但宪法注释未列——单列裁决点）；色 token=`:root/.dark/@theme` 全集（background…chart-6/sidebar-*/tone-good|warn|bad|info|purple|magenta/sk-purple/sk-deep/scrim）。
- **纪律**：本席未改任何门/前端文件；`webui/` 整目录 `git status=?? 未提交`，故一切「新增/存量」判定无 git 基线可证处，如实标「不可判」。

## 一句话结论

**补牙不会把前端判死。** 全量红线账 = **24 处**（原始命中 50，剔除 26 处「门必须结构性放行」的误报），其中**硬违例仅 12**，且 9 处可走「族级白名单/规范值收编」零代码改动；**只补 margin+圆角两族的最小档位：硬红线 = 0**（若 `rounded-full` 不先行收编白名单则 12）。

## 一、违例总账（确定数字）

### 1.1 总数口径

| 口径 | 数字 | 命令证据（`src-out-final3.txt` 计数行） |
|---|---|---|
| 补牙扫描原始命中 | **50** | `TOTAL_RAW=50` |
| 其中 误报（门本体应结构性放行） | **26** | `CSS_DEF_LAYER_FALSEPOSITS=20` + `A5c-arbStruct|structural(门应放行): 6` |
| **违例总账（剔除误报）** | **24** | 50−26 |
| 其中 硬违例（不含豁免候选 rounded-full） | **12** | `TOTAL_ADJUSTED(硬违例…)=12` |
| **最小档位（只补 margin+圆角）硬红线** | **0** | `MR_REDLINE(margin+radius两族，硬)=0`（不认 rounded-full 白名单则 12） |

**前三重灾文件**（按违例总账计）：`components/ui/badge.tsx`(2：rounded-full+ring-[3px])、`components/settings/settings-dialog.tsx`(3：max-h+2×ring)、`pages/memory-graph.tsx`(6：4×rounded-full+ring)——按族计 memory-graph.tsx 6 处居首、settings-dialog.tsx 3 处、badge.tsx/theme-switch.tsx 各 3 处（含 size-[1.2rem]×2）。

### 1.2 族 × 文件计数表

| 族 | 命中 | 分布 |
|---|---|---|
| ①margin 全族（含 ms/me、半档、任意值） | **0** | 现存 margin 共 22 处：`mx-auto`×17+`ml-auto`×1（auto 放行）+`mt-1`×3+`mt-3`+`ml-1`+`mb-4`+`m-2`（全在栅格上）。**负 margin=0**（`M1b-marginNegAll=0`） |
| ②圆角脱三档 | **12** | 全部 `rounded-full`：patterns:115、theme-switch:15、badge:9、calls:74/76、knowledge:137/224、memory-graph:116/124/128/199/212。**任意值圆角（含 rounded-[9px]）实盘 0**、rounded-sm/2xl/none/方向变体 0 |
| ③内联 rgba/hsl/color-mix（tsx） | **0** | tsx 色全部 var()/语义类消费（recharts stroke/fill 亦走 var(--token)）；`fill={\`var(--${TOKEN_COLORS[key]})\`}`(tokens.tsx:161) 是 CSS 变量名模板拼接、色仍来自 token=合规，但登记给门③的拼接盲区（见 1.4-D8 注） |
| ④space-* | **0** | 全树未用 |
| ⑤任意盒尺寸/宽度 | **4+6** | `max-h-[90svh]`(settings-dialog:84)、`size-[1.2rem]`×2(theme-switch:19,20)、`max-h-[60vh]`(logs:299)；`ring-[3px]`×6(settings-dialog:107,128、badge:9、button:9、knowledge:205、memory-graph:144) |
| ⑥.css 文件本体 | **21** | index.css：定义层 rgba(--shadow-*)×12 + tone-face color-mix×8（=误报，token 实现位）；消费位 `font-size:12px`(.recharts 钉，L320)×1 |
| ⑦canvas 字体字面量 | **1** | memory-canvas.tsx:179 `context.font = '12px "Segoe UI"…'`（F4 点名的现役活体，实锤在案） |
| ⑧字符串拼接类名 | **0** | `cn(\`…${}\`)`/`className={\`…\`}`/`'mt-'+x` 三探测全零（正则经 fixture 正样本验证非空转） |
| 结构类任意值（应放行，列作门收紧素材） | **6(+1 盲区)** | badge:9 `transition-[color,box-shadow]`、button:23/24/25 `has-[>svg]`×3、card:22 `grid-rows-[auto_auto]`+`grid-cols-[1fr_auto]`；card:22 `has-data-[slot=card-action]` 为复合变体前缀、扫描器分桶盲区、同属结构类（覆盖率枚举 `has-data-[...]:1` 抓到） |

### 1.3 每处三分类处置（违例总账 24 处）

**A. 改代码合规化 — 3 处**

| 位置 | 命中 | 具体改法 |
|---|---|---|
| theme-switch.tsx:19,20 | `size-[1.2rem]`(=19.2px) ×2 | → `size-5`（20px，栅格在册；视觉差 0.8px） |
| memory-canvas.tsx:179 | canvas 字体字面量 `'12px "Segoe UI"…'` | `readToken()` 旁路新增 `const labelFont = getComputedStyle(el).fontSize`（el=挂 fs-caption 的隐藏节点）或至少把 12 提为与 index.css:320 共享的常量并加豁免标记（见 B） |

**B. 登记豁免（或收编白名单）— 21 处**

| 子型 | 处数 | 理由与登记格式草案 |
|---|---|---|
| `rounded-full` 几何圆 | 12 | 圆点/胶囊/进度条=9999px 几何语义，非「圆角档位」。**建议族级白名单**而非 12 条行级豁免（棘轮只锁增量）：门内 `RADIUS_OK = {md,lg,xl,full-几何}`，full 仅允许出现在「无方向后缀」形制 |
| `ring-[3px]` 焦点环 | 6 | shadcn 原生焦点环宽、上游移植件同值。**建议规范值白名单** `CANONICAL_ARB = ['ring-[3px]']`（精确串匹配收编，其余 ring-[…] 仍全禁） |
| `max-h-[90svh]` / `max-h-[60vh]` | 2 | 视口相对滚动限高，px 栅格语义不适用。行级豁免草案：`// layout-allow: 弹层/日志流经视口高限卷，非栅格维度` |
| index.css:320 `.recharts 12px` | 1 | 图轴字号唯一钉位、与 fs-caption 同源注释在案。css 消费位行级豁免：`/* layout-allow: 图表 tick 与 fs-caption 同值钉位 */` |

**C. 误报（门本体要更精确，不算违例）— 26 处**

| 位置 | 命中 | 正则收紧方案 |
|---|---|---|
| index.css:66-68,81,119-126 rgba ×12 | `--shadow-*` 值里的 rgba | .css 扫描按「块」分级：`:root/.dark/@theme/@utility` 定义层只禁 hex，rgba/color-mix/oklch 为 token 实现手段=放行 |
| index.css:291-312 color-mix ×8 | tone-face-* 派生底 | 同上（定义层白名单块） |
| badge/button/card 结构任意值 ×6(+1) | `has-[>svg]`/`transition-[…]`/`grid-{rows,cols}-[…]`/`has-data-[…]` | 任意值族按「前缀∈尺寸/颜色/圆角维度集」触发，结构/变体选择器前缀放行；复合变体 `has-data-` 需按整 token 解析而非单边界匹配 |

### 1.4 对 F4/旧审计点名的几项如实校正

- `rounded-[9px]`：webui/src 现状 **0 命中**（F4 沙箱产物或旧代）；margin 全族现状 **0 脱档**；space-\* **0 使用**——漏判族属实，但**现值大多干净**，补牙的即时炸线主要在任意值/圆角 full/canvas 三处。
- 本席扫描器自身也被自测抓到 2 条静默漏判（hsl、rounded-sm）——**给补牙实施席的教训：门改动必须配负样本夹具进 pytest**，否则「补了个假牙」。

## 二、档位设计建议（裁决点材料）

1. **负 margin 放行与否：推荐「禁，但可行级豁免」**。依据：实盘 `-m*` = **0 处**（`M1b=0`），无既成用户；负 margin 在纯 flex/grid 栅格布局里几乎总能被 gap/justify 替代，放行的维护成本>收益。留豁免口子（叠压徽章、描边仿真等未来合法手法）即可，不预先开闸。
2. **任意值 `w-[…]` 等：推荐「禁，双通道放行」**——(a) 走 CSS 变量：`w-[var(--某token)]` 自动合规（扫描器 arb-var 规则已验证）；(b) 视口/滚动语义（max-h-[Nvh]）走行级豁免。不推荐建宽度登记表 token 族：现盘无此需求面，先禁再说。
3. **`.css` 纳入扫描：推荐纳入，但必须带「定义层/消费层」分级**——不分级直接炸 20 处误报（index.css 全身 token）。分级后净炸线 **1 处**（.recharts 钉，走行级豁免）。
4. **`rounded-sm`（8px）**：主题里有、宪法注释没列——本席现状 0 使用；建议补牙时**一并禁**，要 8px 圆角就显式改三档之一，档位扩编留给用户裁决。
5. **裸 `rounded`（0.25rem）**：现状 0 使用；同禁。

## 三、`layout-constitution.mjs` 门改动稿（before→after，未落盘）

### 3.1 before（现行，节选 L28-56）

```js
const HEX = /#(?:[0-9a-fA-F]{3,8})\b/g;
const OFF_LADDER_TEXT = /\btext-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|\[[^\]]*\])\b/g;
const INLINE_FONT_SIZE = /\bfontSize\s*:/g;
const OFF_SCALE_SPACING = /\b(?:p|px|py|pt|pb|pl|ps|pe|gap|gap-x|gap-y)-(?!0(?![\d.])|1(?![\d.])|2(?![\d.])|3(?![\d.])|4(?![\d.])|6(?![\d.]))(?:\d+(?:\.\d+)?)\b/g;
const OFF_SCALE_ARBITRARY = /\b(?:p|px|py|pt|pb|pl|gap|gap-x|gap-y)-\[/g;
const PALETTE_CLASS = /\b(?:text|bg|border|ring|...)-(?:red|orange|...)(?:-\d{2,3})?(?:\/\d{1,3})?\b/g;
```

### 3.2 after（新增件全稿；现行六条不动）

```js
// —— 补牙波（F19 预扫描 2026-09-19）：⑤margin 同栅格 ⑥圆角三档 ⑦内联色函数 ⑧space ⑨任意盒尺寸
// ⑩canvas 字体 ⑪.css 消费层。负样本夹具：scripts/fixtures/constitution-negative.tsx（必须全命中）
// + constitution-positive.tsx（必须零命中），由 tests/test_webui_constitution.py 双向锁死。——
const B = String.raw`(?:^|[\s'"\x60:{(=])`;                       // 类 token 起始界（含变体冒号）
const OFF_SCALE_MARGIN = new RegExp(
  B + String.raw`(-)?(m|mx|my|mt|mb|ml|mr|ms|me)-(?:\[(?!.*?var\()][^\]]*\]|`
    + `(?!0(?![\d.])|1(?![\d.])|2(?![\d.])|3(?![\d.])|4(?![\d.])|6(?![\d.]))(auto|\d+(?:\.\d+)?))`, 'gm');
  // ↑ 内部 (auto|…) 捕获组：'auto' 在 check 里跳过；负号捕获组仅用于消息「负margin」；
  //   任意值内含 var(-- 放行。注意先判 auto：`if (m[5]==='auto') continue;`
// 圆角：token 级解析，杜绝「rounded-sm 被单字方向组截胡」型静默漏判（F19 selftest 实锤缺陷）
const RADIUS_TOKEN = new RegExp(B + String.raw`rounded(?:-[A-Za-z0-9()[\]._%$-]+)?`, 'g');
function radiusViolation(tok) {                       // tok 例：rounded / rounded-t-lg / rounded-[9px]
  const rest = tok.slice('rounded'.length);
  if (rest === '') return '裸rounded=0.25rem 脱三档';
  let seg = rest.slice(1);
  if (seg.startsWith('[')) return /var\(|--/.test(seg) ? null : `任意值圆角 ${seg}`;
  const parts = seg.split('-'); const DIRS = new Set(['t','b','l','r','x','y','s','e']);
  let tier = DIRS.has(parts[0]) && parts.length > 1 ? parts[1] : parts[0];
  if (['md','lg','xl'].includes(tier)) return null;
  if (tier === 'full') return null;                   // 族级白名单：几何圆（圆点/胶囊）——豁免登记见 §四
  return `脱三档圆角 rounded-${tier}`;                 // sm/none/2xl/… 全禁
}
const INLINE_COLOR_FN = new RegExp(B + String.raw`(rgba|hsla|hsl|rgb|oklch|color-mix)\((?!.*?var\()`, 'gm');
const OFF_SCALE_SPACE = new RegExp(B + String.raw`space-(x|y)-(?:\[(?!.*?var\()][^\]]*\]|`
  + `(?!0(?![\d.])|1(?![\d.])|2(?![\d.])|3(?![\d.])|4(?![\d.])|6(?![\d.]))(\d+(?:\.\d+)?))`, 'gm');
const ARB_BOX = new RegExp(B + String.raw`(w|h|size|min-w|max-w|min-h|max-h|basis|inset)-\[(?!.*?(var\(|--))[^\]]*\]`, 'gm');
const ARB_RING_NON_CANON = new RegExp(B + String.raw`ring-\[(?!3px)[^\]]*\]`, 'gm');   // 规范值收编：ring-[3px]
const CANVAS_FONT_PX = new RegExp(String.raw`\.font\s*=\s*[\x27\x22\x60][^\x27\x22\x60]*\d+(?:\.\d+)?px`, 'g');
// .css：定义层块(:root/.dark/@theme/@utility/@layer)=只禁裸hex；消费层=hex/裸px字号/函数色全禁(可行级豁免)
```

`check()` 内对应 `scan(...)` 七行 + 圆角走 `for (const m of text.matchAll(RADIUS_TOKEN)) { const v = radiusViolation(m[0].trim()); if (v) push(...) }`；`walk()` 增 `else if (/\.css$/.test(name)) checkCss(path)`（带块归属状态机，参考 `%TEMP%/f19/f19-scan-v2.mjs` 已实装逻辑）。

**豁免机制（并入同一改动稿）**：

```js
// 行级豁免：命中行行尾带  // layout-allow: <理由>  （css 用 /* layout-allow: <理由> */）
const EXEMPT_MARK = /layout-allow:\s*(.+)/;
// check 前：命中行 text 行尾匹配 EXEMPT_MARK → 移入 EXEMPTED[] 不入 VIOLATIONS；
// 理由长度 <6 字符 → 记违例「空豁免理由」（防 layout-allow: 空转后门）。
// 棘轮：EXEMPTED 逐条 (file, family, reason-hash) 与 scripts/layout-exemptions.baseline.json 对比：
//   当前条数 > baseline.count → exit 1「豁免膨胀：新增 X 条，需用户裁定后 --write 降档」
//   < count → exit 1「豁免面收窄，请 --write 重录基线（只减不增棘轮）」
// 绿文案升级：`版式宪法机器门：全部通过（违例=0；当前豁免 ${EXEMPTED.length} 条，基线 ${baseline.count}）`
```

### 3.3 豁免基线快照草案（`webui/scripts/layout-exemptions.baseline.json`）

```json
{ "count": 3,
  "entries": [
    { "file": "pages/logs.tsx", "family": "arb-box", "reason": "日志流经视口高限卷，非栅格维度" },
    { "file": "components/settings/settings-dialog.tsx", "family": "arb-box", "reason": "弹层最大高走 svh，防超屏" },
    { "file": "index.css", "family": "css-consumer-fontsize", "reason": "recharts 轴字号与 fs-caption 同值钉位" }
  ] }
```

（rounded-full 12 与 ring-[3px] 6 走族级白名单，**不占豁免额度**——白名单是宪法扩编须用户裁定，豁免是行级逃生门，两账分开，棘轮只数后者。若用户不批 rounded-full 白名单，则这 12 处转入豁免登记、baseline.count=15。）

## 四、锁与回归（补牙完成后防复发）

1. **pytest 常驻已有五例门**（`tests/test_webui_constitution.py`，F18 域），`test_layout_constitution_gate` 每次全量跑真身——补牙**零新增接线成本**，执法面自动常驻。需**新增两例**：
   - `test_constitution_negative_fixtures`：门扫 `scripts/fixtures/constitution-negative.tsx` 必须命中≥N 条（防「补假牙」：本席 v1 就被 selftest 抓到 2 条静默漏判）；扫 positive 夹具必须 0 命中。
   - `test_exemption_ratchet`：解析门 stdout `当前豁免 (\d+) 条` 与 baseline JSON count 比对，`assert current <= baseline`（只减不增）。
2. **计数快照**：豁免账走 baseline JSON（进 F4 席的 verify_hashes 交付清单同族，改动=显式重录）；违例数不另设快照（恒 0 才是合法态，>0 直接红）。
3. **文档措辞**（建议文本，本席不改文档）：现行 AGENTS.md/HANDBOOK「版式宪法门锁死」「机器门拦截」类表述应改为——「版式宪法门执法 **13 族**：hex/字号五档/内联fontSize/间距栅格/任意间距值/调色板直引（存量 6 族）+ **margin 栅格(含负值禁令)/圆角三档/内联色函数/space 栅格/任意盒尺寸(规范值白名单除外)/canvas 字体字面量/.css 消费层（补牙 7 族）**；行级豁免以 `layout-allow` 标记+基线棘轮（count=N，只减不增）执法，豁免清单见 `webui/scripts/layout-exemptions.baseline.json`」。在补牙落地前，文档应写「现门执法四族（hex/字号/间距/调色板），margin/圆角/内联色/任意值/canvas 字体**暂不在执法面**（2026-09-19 F19 预扫描在册）」——避免「锁死」措辞超前于执法事实。

## 五、与主会话本轮改动的相互影响（只读取证）

| 文件 | 本轮改动面 | 新增违例判定 |
|---|---|---|
| `components/layout/error-boundary.tsx`（新） | `mx-auto w-full max-w-6xl` | **0 违例**：mx-auto=auto 放行；w-full/max-w-6xl 为具名宽度档——**宽度无登记表是设计缺口非违例**（max-w-6xl 若收编建议对齐 `max-w-page` 语义 token，留裁决） |
| `components/ui/card.tsx` | CardTitle 删基类行高 | 0 新增违例；该文件仅有的 3 处任意值（grid-rows/grid-cols/has-data）全为**结构类误报族**（§1.3-C），且注释明示「不写行高类字面量」防 Tailwind v4 扫描器——与门 text-based 机制自洽 |
| `components/patterns/patterns.tsx` | StatCard 值与降级并存 | `rounded-full:115` 在册（豁免候选族）；**是否本轮新增不可判**（webui 未提交，无基线） |
| `pages/logs.tsx` | 去重+清视图 | `max-h-[60vh]:299` 位于日志流容器，**疑随本轮清视图进入**——无基线不判死，若属新增按 §1.3-B 行级豁免或 token 化 |
| `pages/dashboard.tsx` | 去 `?? 0` | 0 命中 |
| `router.tsx` | 错误边界接线 | 0 命中（纯路由件） |
| `vite.config.ts` | proxy | 不在 src 扫描域，0 |

**dist 与 src 同代取证**：`dist/index.html`（单文件构建，973,983 B）mtime **17:09:36**；本轮六件套改动时间戳 16:33-16:46 + tokens.tsx 17:01 均早于它 → **主会话本轮改动已进构建**；唯 `src/lib/utils.ts` **17:10:44**（构建后 68s）晚于 dist → **dist 落后一个 utils.ts（注释级）改动，判定「近同代、差一文件」**；字节级复验不可做（本席禁 build、webui 未提交无哈希链）。扫描全程以 src 为准。

## 六、命令与输出证据（可复跑）

```
$ node scripts/layout-constitution.mjs            # 原版门，只读
版式宪法机器门：全部通过（hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0）  EXIT=0

$ node $TEMP/f19/f19-scan-v2.mjs <workspace>/webui/src   # 补牙扫描（最终版）
SCANNED_FILES=33
TOTAL_RAW=50
CSS_DEF_LAYER_FALSEPOSITS=20
TOTAL_ADJUSTED(硬违例，剔除CSS定义层与放行候选与裁决素材)=12
MR_REDLINE(margin+radius两族，硬)=0
```

族×处置计数行（同上输出）：`A5-arbSize|arb: 4`、`A5b-arbOther|arb: 6`、`A5c-arbStruct|structural(门应放行): 6`、`CSS6-cssFile|定义层color-mix: 8`、`CSS6-cssFile|定义层阴影rgba: 12`、`CSS6-cssFile|消费位裸字号: 1`、`F7-canvasFont|canvas-literal: 1`、`R2-radius|full(豁免候选): 12`；margin/space/内联色/动态类四族全 0。

> 本文件为 F19 席唯一交付物；除本文件外工作树零改动（补牙扫描器与全部中间产物在 `%TEMP%/f19/`）。所有「违例」均为**补牙假设口径**下的在册账，非现行门的红；现行门实跑仍绿。

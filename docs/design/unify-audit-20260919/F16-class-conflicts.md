# F16 — 前端类名冲突穷举审计 + twMerge 认知边界 + 一次性根治方案

> **快照声明**
> - 席位：F16（前端类名冲突审计，只读）
> - 生成时刻：**2026-09-19 16:40（`date` 实跑输出：Sat Sep 19 16:40:38 2026）**；取证延续至 17:2x
> - 工作树状态：**主会话正在并发编辑 `webui/src/**`**。本席全程零修改工作区文件。已实测到的并发活动：
>   `src/components/ui/card.tsx` mtime `16:46:37`、`webui/dist/index.html` mtime `16:47:19`（本席两次探测分别打在 16:41 版与 16:47 版产物上，差异见 §2.4）、
>   `src/components/layout/error-boundary.tsx` 于 16:41 新建（`router.tsx` 已引用）。
> - 因此本文所有 `文件:行` 均附**锚点字符串**；行号若与他席报告不一致，以锚点为准。
> - 复现脚本位置说明：Git Bash 的 `$TEMP` 解析为 `/tmp` → `C:\tmp`，故实验脚本落在 **`C:\tmp\f16\`**（工作区外，未写入任何项目目录）。
>   twMerge 行为实测全部以 `node -e` 内联方式在 `webui/` 为 cwd 执行、只 `require` 既有 `webui/node_modules/tailwind-merge`（**未 npm install、未在 webui 下新建文件、未起服务、未占端口、未跑 build**）。

---

## 0. 一句话结论（先给裁决）

根因**确认且比两席描述更宽**：`@utility` 自定义类对 tailwind-merge 完全不可见，而本项目的五档字号 `fs-*` 是**三属性合一**（`font-size` + `line-height` + `font-weight`）的工具类——**tailwind-merge 的「一类一组」模型在原理上无法表达多属性 utility**，所以「注册进某个组」只能修好三属性中的一到两条，其余必须靠「约定 + 静态门」。

产物层叠实测（现行 16:47 dist）给出硬证据：**五枚 `fs-*` 全部生成在两枚 `leading-*` 与三枚 `font-*` 权重类之前**，且全部同处一个 `@layer utilities` → 「删一类取胜」只是运气，**方案 ①（注册）+ ③（门）必须同时上**，②（约定）作为门的一条子句。

**我自己的冲突对计数：24 对**（同元素双写 17 + 跨合并边界 7），外加 **4 类「今天无触发点、根因在场」的潜在族**。与 F4 的「5+2+16」差异及逐条对账见 §1.4。

---

## 1. 冲突对穷举（本席独立复算，未抄他席计数）

### 1.1 判据与扫描方法（可复跑）

「冲突对」= 同一 CSS 属性被同一元素的两条 class 各写一次。属性归属由 `src/index.css` 实读的 utility 定义决定（见 §4.1），非猜：

| 类族 | 命中的 CSS 属性 |
|---|---|
| `fs-page/card/body/caption/num` | **font-size + line-height + font-weight**（`fs-num` 另加 font-variant-numeric） |
| `text-{xs..5xl}` / `text-[..]` | font-size |
| `leading-*` | line-height |
| `font-{thin..black}` | font-weight |
| `tone-face*` / `bg-*` | background |

扫描命令（只读，cwd=`webui`，按行 tokenize，**修饰符前缀相同的才互比**，注释行剔除）：

```bash
cd webui && node -e '  # 见本文末 §1.5 附录脚本；行内 split 非 [^A-Za-z0-9_\-\[\]().\/:%,#*]+ 切词
'
```

跨合并边界（基类 ↔ 调用点）的对，用 Grep 全量枚举 `<CardTitle|<CardDescription|<Card|<CardContent|<CardHeader|<Badge|<Button|<CategoryChip|<Skeleton|<DataGrid*` 的 `className` 实参逐条人工判属性（本席已逐元素读过 9 页 + 11 组件全文）。

### 1.2 A 类：同一字符串内（同元素）双写 — **17 处**

**A1 `font-weight` 双写（fs-* + 无条件 `font-medium`）— 15 处**

产物裁决：`.fs-*`@9503xx–9506xx **早于** `.font-medium`@950829 → **`font-medium` 恒胜（500）**，`fs-*` 自带的 `font-weight:400/600` 声明是死代码。

| # | 位点 | 锚点字符串 | 传入/基类关系 | 谁胜 | 视觉后果 |
|---|---|---|---|---|---|
| 1 | `src/components/ui/button.tsx:9` | `"inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md fs-body font-medium"` | cva 基类内部 | font-medium(500) | 无（今天即想要 500）；`fs-body` 的 400 永不生效 |
| 2 | `src/components/ui/badge.tsx:9` | `'… px-2 py-1 fs-caption font-medium w-fit whitespace-nowrap …'` | cva 基类内部 | font-medium(500) | 同上 |
| 3 | `src/components/patterns/patterns.tsx:115` | `'inline-flex shrink-0 items-center rounded-full px-2 py-1 fs-caption font-medium'` | CategoryChip 基类内部 | font-medium(500) | 同上 |
| 4 | `src/components/patterns/patterns.tsx:151` | `'rounded-md border px-3 py-1 fs-caption font-medium text-muted-foreground hover:bg-accent disabled:pointer-events-none disabled:opacity-50'` | Pager「‹」原生 button | font-medium(500) | 同上（且绕开 Button 基类，见 F16-11） |
| 5 | `src/components/patterns/patterns.tsx:162` | 同上，`labels?.next` 支 | Pager「›」 | font-medium(500) | 同上 |
| 6 | `src/pages/affinity.tsx:38` | `<div className='truncate fs-body font-medium' title={item.nickname \|\| item.sender_id}>` | 页面传入 | font-medium(500) | 正文档被加权，阶梯的 w400 语义失效 |
| 7 | `src/pages/affinity.tsx:85` | `'flex items-center gap-2 rounded-md border px-3 py-1 fs-caption font-medium …'` | 排序原生 button | font-medium(500) | 同 #4 |
| 8 | `src/pages/calls.tsx:35` | `'rounded-md px-3 py-1 fs-caption font-medium transition-colors'` | WindowSwitch | font-medium(500) | 同上 |
| 9 | `src/pages/calls.tsx:109` | `'rounded-md border px-3 py-1 fs-caption font-medium text-muted-foreground hover:bg-accent'` | 粒度切换 button | font-medium(500) | 同上 |
| 10 | `src/pages/dashboard.tsx:63` | `<p className='fs-caption font-medium text-muted-foreground'>{label}</p>` | 窗口小标题 | font-medium(500) | 同上 |
| 11 | `src/pages/latency.tsx:25` | `<DataGridCell className='w-56 shrink-0 font-mono fs-caption font-medium'>` | 渠道名单元格 | font-medium(500) | 同上 |
| 12 | `src/pages/memory-graph.tsx:246` | `<div className='fs-caption font-medium'>{t('memoryGraph.dataScope')}</div>` | 「数据范围」小标题 | font-medium(500) | 同上 |
| 13 | `src/pages/tokens.tsx:50` | `<span className='truncate font-mono fs-caption font-medium' title={row.family …}>` | 模型族名 | font-medium(500) | 同上 |
| 14 | `src/pages/tokens.tsx:99` | `'rounded-md bg-primary px-3 py-1 fs-caption font-medium text-primary-foreground'` | 时间窗选中态 | font-medium(500) | 同上（未复用 Button，同 #4） |
| 15 | `src/pages/tokens.tsx:100` | `'rounded-md px-3 py-1 fs-caption font-medium text-muted-foreground hover:bg-accent'` | 时间窗未选态 | font-medium(500) | 同上 |

> **有修饰符前缀的 `fs-*` + `[&.active]:font-*`（2 处，我判定为「非违例」）**：
> `src/components/layout/app-shell.tsx:22`（NavSubItem，`… [&.active]:text-primary [&.active]:font-medium`）与
> `app-shell.tsx:34`（NavItem，`… [&.active]:bg-primary … [&.active]:font-medium`）。
> 产物实测选择器为 `.\[\&\.active\]\:font-medium.active{…}`（@960767），特异性 **(0,2,0) > `.fs-body`(0,1,0)** →
> **胜者由特异性确定，不由层叠顺序决定** → 结构上安全（仍属可读性瑕疵）。这是本席与 F4 计数差的主要来源，见 §1.4。

**A2 `line-height` 双写（fs-caption + `leading-relaxed`）— 2 处（真违例，值确实不同）**

| # | 位点 | 锚点 | 谁胜 | 视觉后果 |
|---|---|---|---|---|
| 16 | `src/components/settings/settings-dialog.tsx:140`（F4 报 139） | `<p className='rounded-md border bg-muted/40 p-3 fs-caption leading-relaxed text-muted-foreground'>` | `.leading-relaxed`@950659 > `.fs-caption`@950465 | 行高被放宽为 **1.625（≈19.5px）**，宪法规定的 fs-caption 18px 静默失效 |
| 17 | `src/pages/logs.tsx:320`（F4 报 308） | `<p className='fs-caption leading-relaxed text-muted-foreground'>{t('logs.transportNote')}</p>` | 同上 | 同上 |

> 这两处是 **P1-1 的同族且方案 ① 修不了**（原因见 §3.2 的单向冲突表实测）。

### 1.3 B 类：组件基类 ↔ 调用点（跨 `cn()` 合并边界）— **7 对**

| # | 组件位点（基类） | 调用点（传入） | 冲突属性 | 谁胜 | 视觉后果 |
|---|---|---|---|---|---|
| 18 | `ui/card.tsx:33` CardTitle 基类 `'font-semibold'` | `pages/calls.tsx:61` `<CardTitle className='fs-card'>` | font-weight | font-semibold@951017（600） | 无（600=600）；**结构与已删的 `leading-none` 完全同源**：调用方的 `fs-card` 权重声明永不可生效 |
| 19 | 同上 | `pages/calls.tsx:150` `<CardTitle className='fs-card'>{t('calls.trend')}` | font-weight | 同上 | 同上 |
| 20 | 同上 | `pages/tokens.tsx:127` | font-weight | 同上 | 同上 |
| 21 | 同上 | `pages/tokens.tsx:172` | font-weight | 同上 | 同上 |
| 22 | 同上 | `pages/tokens.tsx:201` | font-weight | 同上 | 同上 |
| 23 | 同上 | `components/patterns/patterns.tsx:73` `<CardTitle className={cn('fs-card', titleClass)}>`（覆盖全部 SectionCard/StatCard，含 StatCard 的 `titleClass='text-muted-foreground'`→ 不冲突） | font-weight | 同上 | 同上 |
| 24 | `ui/card.tsx:37` CardDescription 基类 `'text-muted-foreground fs-caption'` | `components/patterns/patterns.tsx:74` `<CardDescription className='fs-caption'>` | font-size / line-height / font-weight | **同类双写（同值）** | 无视觉差；方案 ① 生效后会被折叠成一个（行为等价） |

**已核实的「零冲突」基类/调用点组合**（列出来是为了证明扫过而不是漏了）：

- `<Button>` 全部 20 个调用点中仅 `theme-switch.tsx:15` 传 `className='rounded-full'`（基类 `rounded-md`）→ **两侧都是内建类，twMerge 正常合并**，无 fs 面冲突。
- `<Badge>` 传入 `font-mono`（knowledge:65、plugins:52,88）= `font-family` 组，与 fs-* 无冲突；传入 `font-normal …`（tokens:33,39）**今天就被 twMerge 反向删掉了基类的 `font-medium`**（内建 vs 内建），留下的 `fs-caption`(400) + `font-normal`(400) 同值 → 无害。
- `<CategoryChip>` 传入 `font-mono`（logs:303）、`opacity-60`（knowledge:182）、`opacity-40`（memory-graph:133）→ 无冲突。
- `<Skeleton>` 传入 h-*/w-*/`rounded-full` → 基类 `bg-accent animate-pulse rounded-md`，`rounded-full` 与 `rounded-md` **内建对合并正常**。
- `<DataGridCell>` 传入的 `fs-*` 与基类 `min-w-0 truncate`（无排版声明）→ 无冲突。
- 全树 `text-{xs|sm|base|lg|xl|…}` / `text-[..]` **零使用**（dist 内 `.text-xs`/`.text-sm` 规则 n=0 实测），故 font-size 组目前只有 fs-* 一个写者 → 阶梯在 font-size 这一维**今天没被打穿，被打穿的是 line-height 与 font-weight**。

### 1.4 与 F4「5+2+16」的对账（本席自算，不抄）

| 维度 | F4 口径 | 本席实测 | 差异原因（逐条落到锚点） |
|---|---|---|---|
| `fs-card + leading-none` | 5 | **6**（本席把 `patterns.tsx:73` SectionCard 这条传入也算一对；它同样压进 CardTitle 基类）+ **该族在现行 src 已随基类 `leading-none` 删除而清零** | F4 只数页面直调 5 处，未数 patterns 壳内那条 |
| `fs-caption + leading-relaxed` | 2 | **2** ✅ 完全一致 | 行号漂移（139→140、308→320）系主会话并发改文件，锚点相同 |
| `fs-* + font-medium` | 16（其清单实列 17 条） | **15** | 本席把 `app-shell.tsx:22,34` 两条**移出违例**——它们是 `[&.active]:font-medium`，产物选择器带 `.active` 类、特异性 (0,2,0) 胜过 (0,1,0)，**裁决确定、不依赖层叠顺序**；F4 未做特异性分析。本席另含 patterns:115（F4 记 116，同一处、行号漂移） |
| 跨边界（基类 ↔ 传入） | 未单列 | **7** | 本席把「基类内建类 + 传入 fs-*」这一族独立计（B 类 18–24），因为它才是 P1-1 的**真正复发面** |
| **本席总数** | — | **24 对**（17 + 7）+ 4 类潜在族（下节） | |

### 1.5 附录：同元素扫描脚本（只读复跑）

```bash
cd webui && node -e '
const fs=require("fs");const files=[];
(function walk(d){for(const n of fs.readdirSync(d)){const p=d+"/"+n;const s=fs.statSync(p);
if(s.isDirectory())walk(p);else if(/[.]tsx$/.test(n))files.push(p);}})("src");
const FS=/^fs-(page|card|body|caption|num)$/;
const W=/^font-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black|[[])/;
function props(b){const P=[];
 if(FS.test(b))P.push("font-size","line-height","font-weight");
 if(/^text-(xs|sm|base|lg|xl|2xl|3xl|4xl|5xl)$/.test(b)||/^text-\[/.test(b))P.push("font-size");
 if(/^leading-/.test(b))P.push("line-height");
 if(W.test(b))P.push("font-weight");
 if(/^(tabular|oldstyle|lining|proportional)-nums$/.test(b))P.push("font-variant-numeric");
 if(/^tone-face/.test(b)||/^bg-/.test(b))P.push("background");return P;}
for(const f of files){const L=fs.readFileSync(f,"utf8").split(String.fromCharCode(10));
 L.forEach((ln,i)=>{if(/^\s*(\/\/|\*|\/\*)/.test(ln))return;
  const map=new Map();
  for(const t of ln.split(/[^A-Za-z0-9_\-\[\]().\/:%,#*]+/).filter(Boolean)){
   const k=t.lastIndexOf(":");const mods=k<0?"":t.slice(0,k),b=k<0?t:t.slice(k+1);
   for(const p of props(b)){const key=p+"#"+mods;const a=map.get(key)||[];a.push(t);map.set(key,a);}}
  for(const [key,list] of map) if(new Set(list).size>1)
   console.log(key.split("#")[0], key.split("#")[1]||"ROOT", f+":"+(i+1), [...new Set(list)].join(" + "));});}
'
```

期望输出 = §1.2 的 17 行。

---

## 2. twMerge 认知边界：实测结论（**已实测，非静态论证**）

方法：`cd webui && node -e`，用 `createRequire` **只读**加载 `webui/node_modules/tailwind-merge`（版本 `3.7.0`，`package.json` 声明 `^3.3.1`，实装 3.7.0）。未 `npm install`、未在 `webui/` 写文件。

### 2.1 默认可见性：`fs-*` / `tone-face-*` / `no-scrollbar` **全部不可见**

```
twMerge("font-semibold","fs-card")            => "font-semibold fs-card"
twMerge("fs-caption","leading-relaxed")       => "fs-caption leading-relaxed"
twMerge("fs-body","text-[13px]")              => "fs-body text-[13px]"
twMerge("fs-body","fs-caption")               => "fs-body fs-caption"     ← 两条自定义类之间也从不折叠
twMerge("fs-caption","font-medium")           => "fs-caption font-medium"
twMerge("bg-primary","tone-face-good")        => "bg-primary tone-face-good"
```

对照（theme 派生的类**可见**，因为命中的是内建 `bg-*` / `text-*` 组 + `isAny` 校验）：

```
twMerge("text-muted-foreground","text-tone-good") => "text-tone-good"    ← text-tone-* 可见
twMerge("bg-background","bg-scrim")               => "bg-scrim"          ← bg-scrim 可见
twMerge("h-9","h-full")                           => "h-full"
twMerge("rounded-md","rounded-full")              => "rounded-full"
```

默认组表实读（`getDefaultConfig()`，379 组）：

```
font-size      : [{text:["base",null,null,null]}]     ← 只有 text-* 前缀，无任何 fs
leading        : [{leading:["none",null,null,null,null]}]
font-weight    : [{font:[null,null,null]}]
text-color     : [{text:[null,null,null]}]
conflictingClassGroups["font-size"] = ["leading"]     ← 单向！
conflictingClassGroups["leading"]   = undefined
conflictingClassGroups["font-weight"]= undefined
含字面量 "fs-" 的组：[] （零命中）
```

**顺带实测到一个与本缺陷无关但同族可见性的边界**：`text-xs` 与 `text-tone-good` 分属 `font-size` / `text-color` 两组，`twMerge("text-xs","text-tone-good")` **两条都留**——即 twMerge 认为「字号与文字色不冲突」。这解释了为什么把 `fs-*` 注册进 `font-size` 组**不会误伤**全站大量 `text-muted-foreground` / `text-tone-*` / `text-primary`（§3.1 已实测）。

### 2.2 致命陷阱：`extendTailwindMerge` 的 v2 扁平写法在 3.7.0 **静默失效**

实读 `node_modules/tailwind-merge/src/lib/merge-configs.ts`：`mergeConfigs(base, {cacheSize, prefix, experimentalParseClassName, extend, override})` —— **顶层 `classGroups` / `theme` / `conflictingClassGroups` 参数在 3.7.0 已不存在**，网上绝大多数旧例（含本项目若照 `extendTailwindMerge({ classGroups: {...} })` 抄写）会**一个都不生效**：

```
extendTailwindMerge({classGroups:{"font-size":[...fs 五档]}})
  → mergeConfigs(getDefaultConfig(),{classGroups:…}).classGroups["font-size"]
  = [{"text":["base",null,null,null]}]           ← 原封不动，扩展被吞
  且 twMerge("fs-body","fs-caption") 仍 => "fs-body fs-caption"
extendTailwindMerge({classGroups:{"fs-ladder":[...]}})  → 同样零效果
```

正确写法是 **`extendTailwindMerge({ extend: { classGroups: { … } } })`**（TS 层会拒绝扁平写法 → `tsc -b` 能拦；纯 JS 运行时不报，故若有人绕过类型就是「修了个寂寞」）。登记为 **F16-6**。

### 2.3 方案 ① 生效后的实测矩阵（`extend: { classGroups: { 'font-size': [五档] } }`）

| 输入（基类在前、传入在后） | 默认 `cn()` | 注册后 `cn()` | 判定 |
|---|---|---|---|
| `leading-none`, `fs-card` | 都留 → 层叠定 | **`"fs-card"`** | ✅ P1-1 本尊被根治（不再依赖「谁恰好手写删了 leading-none」） |
| `fs-caption`, `leading-relaxed` | 都留 → leading 胜 | **都留 → leading 胜** | ❌ **A2 两处修不了**（冲突表单向：后到的 `leading` 不删先到的 `font-size`） |
| `fs-body`, `fs-caption` | 都留 → 层叠定（fs-caption 恰胜） | **`"fs-caption"`** | ✅ 折叠，且胜者变成「字符串里在后者的那条」= 调用方，语义正确 |
| `text-[13px]`, `fs-body` | 都留 | **`"fs-body"`** | ✅ 任意值字号被阶梯挤掉（阶梯权威性↑） |
| `fs-num`, `text-2xl` | 都留 | **`"text-2xl"`** | ✅ 同族（全站现在零 `text-{size}`，无回归面） |
| `text-muted-foreground`, `fs-body` | 都留 | **都留** | ✅ **无误伤**（关键安全性） |
| `font-semibold`, `fs-card` / 反序 | 都留 | **都留** | ⚠️ 权重双写不属 ① 管辖 → 必须靠 ②/③ |
| `fs-body`, `font-medium` | 都留 | **都留** | ⚠️ 同上 |
| `tabular-nums`, `fs-num` | 都留 | **都留** | ✅ 现状不变 |
| `px-4`, `fs-body` | 都留 | **都留** | ✅ 无误伤 |

再测「双向冲突表」变体（自建组 + `leading:['fs-ladder']`）：

```
B("fs-caption","leading-relaxed") => "leading-relaxed"      ← fs-caption 被删！
```

即：**反向声明会让元素彻底丢掉 font-size（退回继承 16px）**，比现在更坏。这就是「twMerge 的一类一组模型无法表达多属性 utility」的实证——写进 §3 的方案否决理由。

### 2.4 产物层叠顺序实测（两次快照，证明「顺序不可控」）

同一份源码在 16:41 版与 16:47 版 dist 中的偏移（主会话在 16:46 改过 `card.tsx`，16:47 重建）：

| 规则 | 16:41 dist | 16:47 dist |
|---|---|---|
| `.fs-num{` | 950303 | 950303 |
| `.fs-body{` | 950401 | 950401 |
| `.fs-caption{` | 950465 | 950465 |
| `.fs-card{` | 950531 | 950531 |
| `.fs-page{` | 950595 | 950595 |
| `.leading-none{` | 950659 | **不存在（n=0）** |
| `.leading-relaxed{` | 950702 | 950659 |
| `.leading-tight{` | 950790 | 950747 |
| `.font-medium{` | 950872 | 950829 |
| `.font-normal{` | 950966 | 950923 |
| `.font-semibold{` | 951060 | 951017 |
| `.tabular-nums{` | 952068 | 952025 |

两条独立结论：

1. **删除一个类会让后面所有规则的字节偏移整体前移** → 任何「钉死 dist 偏移」的锁天生脆弱（见 §6 的裁决：锁不建在产物上）。
2. `.leading-none` 在 16:47 版产物中 n=0 → 主会话那次基类删除**已随一次真实构建落地**（本席只观测产物，不写「已修复」；源码 `src/components/ui/card.tsx:33` 现值 `className={cn('font-semibold', className)}`，上方 30–31 行已留下解释性注释）。

**五档之间的层叠优先级（实测，反直觉）**：`fs-page(950595) > fs-card > fs-caption > fs-body > fs-num(950303)`
→ **`fs-num`（30px 数字大字）是五档中层叠最弱者**：任何人给它传 `fs-body`/`fs-caption` 都赢它。登记 **F16-4**。

---

## 3. 根治方案：三案对比 + 推荐 + 可落手代码

### 3.1 方案 ①（推荐主案）：把五档注册进 `font-size` 组

**完整 `webui/src/lib/utils.ts` 替换稿**（before → after；本席**未写入**，交主会话落）：

before（现行 7 行）：

```ts
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

// 移植自 AxonHub frontend/src/lib/utils.ts（Apache-2.0，已注明修改；裁剪为本项目所需子集）。
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

after（全文替换稿）：

```ts
import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

// 移植自 AxonHub frontend/src/lib/utils.ts（Apache-2.0，已注明修改；裁剪为本项目所需子集）。
//
// 【为什么必须自定义 merger —— 版式宪法缺陷根治，2026-09-19 F16 席实证】
// src/index.css 的五档字号用 Tailwind v4 `@utility fs-*` 定义，tailwind-merge 3.7.0 的默认
// class group 表里没有任何 "fs-" 字面量（实测：getDefaultConfig().classGroups 379 组零命中），
// 于是 cn() 从不折叠它们：组件基类的内建 leading-*/text-[..] 与调用方 fs-* 撞同一 CSS 属性时，
// 两个都留在最终 class 串里，胜负交给产物层叠顺序——实测五枚 fs-* 全部早于 leading-*/font-*
// （.fs-page@950595 < .leading-relaxed@950659 < .font-semibold@951017），故“基类恒胜、调用方静默失效”。
// 把五档注册进内建 font-size 组后：
//   ① 同组冲突生效（fs-body+fs-caption 折叠为一条，且由“后者胜”= 调用方胜，语义正确）；
//   ② 借默认 conflictingClassGroups['font-size'] = ['leading']，基类 leading-* + 调用方 fs-* 会被删
//      （= 旧审计 P1-1 那一族，从此不依赖「恰好手删了一类」）；
//   ③ 实测不误伤：text-color 与 font-size 是两组（text-muted-foreground / text-tone-* / text-primary 安全）。
// 已知不覆盖：基类 fs-* + 调用方 leading-*（冲突表单向，后到的 leading 不删先到的 font-size）。
//   —— 那两处只能靠「基类/同元素禁双写」的静态门守（scripts/layout-constitution.mjs 规则 F1）。
// 不做反向冲突（leading:['font-size']）：实测会把 fs-* 整条删掉、元素彻底失去 font-size 退回 16px 继承，更坏。
const TYPE_LADDER = ['fs-page', 'fs-card', 'fs-body', 'fs-caption', 'fs-num'];
// tone-face-* 与内建 bg-* 同打 background。注册后二者互删（不注册则恒由 tone-face-* 按层叠取胜，
// 导致 CategoryChip 的 6 个 tone 不可被调用方 bg-* 覆盖、而 brand tone 却可以——语义不一致）。
const TONE_FACE = [
  'tone-face',
  'tone-face-good',
  'tone-face-warn',
  'tone-face-bad',
  'tone-face-info',
  'tone-face-purple',
  'tone-face-magenta',
  'tone-face-flat',
];

// ⚠️ tailwind-merge 3.x：必须写在 extend 里。顶层 classGroups 是 2.x 旧写法，
//    在 3.7.0 会被 mergeConfigs 静默丢弃（实测扩展完全无效，而 tsc 才会报类型）。
const cnMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': TYPE_LADDER,
      background: TONE_FACE,
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return cnMerge(clsx(inputs));
}
```

**需要的档名清单（`src/index.css` 实读，不是记忆）**：`fs-page`(237) / `fs-card`(242) / `fs-body`(247) / `fs-caption`(252) / `fs-num`(257) —— 共 **5** 档，与宪法注释「全站只有这五档」一致；`@utility` 全集另含 `no-scrollbar`(217) 与 `tone-face`+7 个 `tone-face-*`(291–314)。

**代价与回归面（这是本席给的最大风险提示）**：

| 回归向量 | 实测/静态结论 | 需要盯的位点 |
|---|---|---|
| 吃掉 `text-*` 颜色类 | **不会**（font-size 与 text-color 两组不互删，实测） | 全站 **135 处** text-color 类实装（`text-muted-foreground`/`text-tone-*`/`text-primary`… 计数脚本见 §1.5 附注）全安全；对照：`fs-*` 全站 130 处、`bg-*` 58 处 |
| 吃掉 `font-medium`/`font-semibold` | **不会**（font-weight 组与 font-size 无冲突条目） | A1 的 15 处、B 的 6 处**行为完全不变** → ①对它们既不治也不伤 |
| 同元素两条不同 `fs-*` 从「都保留」变「折叠成后者」 | **会变**（正是想要的），但若有人依赖「层叠恰好让基类赢」就翻案 | 现网仅 `patterns.tsx:74`（CardDescription 基类 `fs-caption` + 传入 `fs-caption`，**同值 → 无差**）→ **实测零回归** |
| `background` 组注册 `tone-face-*` 后，`bg-*` + `tone-face-*` 由「层叠定」变「后者胜」 | 方向不变（今天也是 tone-face 胜，因它在 @954xxx 晚于 bg-*@948–949k） | 现网 **0 处**同一元素同时带 `bg-*` 与 `tone-face-*`（已 grep 穷举：`TONE_TEXT` 每 tone 只给一条）→ 安全，但属「行为可观察变化」，主会话若要最小改动可**先只注册 font-size、tone-face 留作第二批** |
| `defaultLogger` 风险 | 本方案**不启用** `@tailwindcss-merge/logger`（未装依赖、devDeps 里没有）→ 无该风险；真正的静默风险是 §2.2 的扁平写法（tsc 拦得住、运行时拦不住） | 在锁里加一条「fs-* 必须被 cn 折叠」的行为断言（§6 的 L2），专治这一类「修了个寂寞」 |

### 3.2 方案 ②（约定层，必须与 ① 并行，因为它管 ① 管不到的部分）

**规则**：*任何元素上，`font-size / line-height / font-weight` 三个属性各只许有一个写者；字号与行高由五档 `fs-*` 唯一供给，需要改权重就换档或用 `font-*` 而不得与 `fs-*` 并写。*

改动清单（**要删的基类/传入类**，逐条可落手）：

1. `settings-dialog.tsx:140` 删 `leading-relaxed`（行高交 fs-caption 的 1.125rem）。
2. `logs.tsx:320` 删 `leading-relaxed`。
3. 组件基类的权重声明：`button.tsx:9`、`badge.tsx:9`、`patterns.tsx:115` 三条基类里的 `font-medium` 与自带 `fs-*` 权重二选一——**本席不建议删**（删了按钮字重 500→400，是可见的视觉变更，属用户裁定面）；建议改为「保留 `font-medium`、并在宪法文档明示 `fs-*` 的 font-weight 分量是文档性声明」。
4. CardTitle 基类 `font-semibold`（`card.tsx:33`）：与 fs-card 同值，保留即可，但**基类永不再引入任何 `leading-*` / `text-{size}`**（`leading-none` 已被主会话删除，这条要写进门防复发）。
5. 页面侧「裸 button 复刻 Button 外观」的 6 处（`patterns.tsx:151,162`、`affinity.tsx:85`、`calls.tsx:35,109`、`tokens.tsx:99,100`、`memory-graph.tsx` 的 `<button className='rounded-full'>` 包装件）——长期应收敛到 `buttonVariants({size:'sm'})`，权重双写集中在这里；本轮只登记不改。

代价：纯删类，**零新增依赖**；但**没有任何机器保证**，一次「顺手加个 leading-relaxed」即复发 → 必须配 ③。

### 3.3 方案 ③（静态门，锁的落点；实现草案见 §6）

### 3.4 推荐与理由（一句话）

> **推荐：①（`extend` 版注册，只 `font-size` 组）+ ③（门规则 F1/F2/F3）同时上，②作为门的条文；tone-face 注册作为第二批。**
> 理由：①把「能不能折叠」交给库（一次性覆盖全站所有现在与未来的 `cn()` 调用点，**实测对 15+6 处权重双写零影响、对 40 处 `text-*` 零误伤**）；
> ③补①的原理性盲区（`fs-*` 是多属性类、冲突表单向、`@utility` 层叠顺序不可控）；
> 单用 ② 是「靠人自觉」，已被本轮 `leading-none` 事故证明会复发。

---

## 4. Tailwind v4 特有问题面：`@utility` 的生成顺序**不可控**（裁决 + 依据）

**裁决：不可控 → 「靠删一类取胜」是权宜，必须走 ① 或 ③。**

依据（三条，全部实读/实测，非推测）：

1. **同层、同特异性、无 `@layer` 抓手。** 产物层结构实测：
   `@layer properties{`@936679 → `@layer theme{`@937851 → `@layer base{`@938728 → `@layer components;@layer utilities{`@942897。
   **全部工具类（内建 + `@utility` 自定义）都落进同一个 `@layer utilities`**（`.fs-*` 与 `.leading-*`/`.font-*` 都在其内），特异性一律 (0,1,0) → 唯一裁决器是文件内出现次序。
   `@theme inline`（`src/index.css:130/282`）只喂 CSS 变量，与次序无关。
2. **源码次序 ≠ 产物次序（实测）。** `src/index.css` 声明顺序是 `fs-page → fs-card → fs-body → fs-caption → fs-num`(237/242/247/252/257)，产物却是 **`fs-num → fs-body → fs-caption → fs-card → fs-page`**（§2.4）。次序由 Tailwind 内部 utility 排序决定，**项目层无从声明"我在内建类之后/之前"**。
3. **仅存的两个次序抓手都不合用**：
   - 挪进 `@layer components`：产物里 `@layer components;` 是**空层且排在 utilities 之前** → 只会更弱，方向相反。
   - 挪出所有层（裸写 CSS 规则）：未分层 CSS 在级联中**压过一切分层规则** → `fs-*` 变成恒胜，那会把缺陷**反向固化**（调用方再也压不过基类）。故否。
4. 附带观测（不作为依据，但佐证"顺序脆弱"）：**删掉一个类就让后续规则整体前移 43 字节**（§2.4 两版对照）→ 依赖产物偏移的任何做法都会随构建漂移。

结论：唯一**不依赖次序**的杠杆是让**最终 class 串里根本不存在两个写者** —— 即 ①（合并期删一条）+ ③（写码期禁止第二条）。

### 4.1 自定义类「twMerge 不可见」全集（从 `index.css` 实读，15 枚 `@utility`）

| utility | 定义行 | 写的 CSS 属性 | twMerge 可见? | 撞车对象（内建类） | 谁恒胜（产物实测） | 现网有无触发点 |
|---|---|---|---|---|---|---|
| `fs-page` | 237 | font-size / line-height / font-weight | ❌ | `text-{size}` `text-[..]` `leading-*` `font-*` | **内建**（950595 < 950659/951017）；档内最强势自定义档 | 0（全站零 `text-{size}`） |
| `fs-card` | 242 | 同上 | ❌ | 同上 | 内建 | B 类 6 对（font-semibold，同值） |
| `fs-body` | 247 | 同上 | ❌ | 同上 | 内建 | A1 #1/#6 |
| `fs-caption` | 252 | 同上 | ❌ | 同上 | 内建 | A1 13 处 + A2 2 处（**真视觉差**） |
| `fs-num` | 257 | + font-variant-numeric | ❌ | 同上 + `tabular-nums` | 内建；且**五档中最弱** | 3 使用点均无并写（patterns:31、tokens:179,189） |
| `tone-face` | 291 | background | ❌ | `bg-*` | **tone-face 恒胜**（954xxx > 948–949k） | 未使用 |
| `tone-face-good/warn/bad/info/purple/magenta/flat` | 294–314 | background | ❌ | `bg-*` | 同上 | **0 并写**，但 `TONE_TEXT.brand` 用 `bg-primary/15`（可覆盖）而其余 6 tone 用 `tone-face-*`（不可覆盖）→ 覆盖语义不一致（F16-3） |
| `no-scrollbar` | 217 | scrollbar-width / ::-webkit-scrollbar | ❌ | （无内建对手） | — | **定义未用**（dist n=0，src 零引用）→ 死 utility（F16-9） |

### 4.2 「第二、第三族」判定结论（**这些不属于病灶，已实测为可见/不适用**）

| 自定义 token 面 | 类形态 | twMerge 判定 | 结论 |
|---|---|---|---|
| `--color-scrim` | `bg-scrim` | ✅ 可见（`bg-*` + isAny；`twMerge("bg-background","bg-scrim")=>"bg-scrim"` 实测） | 无病 |
| `--color-tone-*` | `text-tone-*` / `border-tone-*` | ✅ 可见（实测 `text-muted-foreground` 与 `text-tone-good` 正确互删） | 无病 |
| `--chart-1..6` | `bg-chart-*` / `text-chart-*` | ✅ 可见（同 `bg-*`/`text-*` 组） | 无病 |
| `--r-shell/panel/tile` → 钉 `--radius-xl/lg/md` | `rounded-xl/lg/md` | ✅ 可见（内建类名，只是值被重钉） | 无合并病；**语义病**：`rounded-xl` 在本项目=30px 而非 0.75rem，属认知成本，登记为 P3 观察项 |
| `--shadow-*` 重钉 | `shadow-md/lg/xl` | ✅ 可见（内建类名） | 无病 |
| `h-svh` / `min-h-svh` / `max-h-[60vh]` / `max-h-[90svh]` / `h-9` / `size-9` | 内建动态/任意值 | ✅ 可见（`h-*`/`size-*` 组支持单位后缀与任意值；`h-9`+`h-full` 实测正确互删） | 无病 |
| `font-sans`/`font-mono`（`--font-*`） | `font-sans`/`font-mono` | ✅ 可见（`font-mono` 独立于 `font-weight` 组，实测 `tabular-nums`/`font-mono` 与 fs-* 均不误删） | 无病 |

→ **除 `fs-*` 外的第二族 = `tone-face-*`（8 枚，含 1 枚未用）**；**第三族 = `no-scrollbar`（1 枚，零使用、也无内建对手 → 当前无风险，但注册表必须留位）**。

---

## 5. 顺带核销（旧审计 P2-10 / P2-13 / P2-14 与本域重叠部分）

### 5.1 「裸字号控件」——本席自数：**4 处 `<input>` 站点（5 个渲染实例），其中真违例 2 处**

先给一条**纠正两席口径的前提事实**（产物实读）：本项目 v4 preflight 为
`button,input,select,optgroup,textarea{font:inherit;font-feature-settings:inherit;font-variation-settings:inherit;letter-spacing:inherit;color:inherit;opacity:1;…}`（`@layer base`@+1716 处）——
**`font: inherit` 且无 `font-size:100%` 覆写**。所以「裸控件 = 16px」不成立：**裸控件继承父级 fs-\***，是否违例要看祖先链。

| 位点 | 锚点 | 自身 fs-* | 祖先链字号 | 判定 |
|---|---|---|---|---|
| `settings-dialog.tsx:102`（baseUrl input，`className='h-9 rounded-md border bg-transparent px-3 outline-none …'`） | ✅ 无 | 外层 `<div className='flex flex-col gap-4 fs-body'>`(:97) → **继承 13px/400** | **不违例**（但靠继承兜，宪法未明示这一路径） |
| `settings-dialog.tsx:120`（`fields.map` 内 token input，`className='h-9 flex-1 rounded-md …'`） | ✅ 无 | 同上（渲染 2 实例） | **不违例**（同上） |
| `knowledge.tsx:201`（搜索 input，`className='h-9 w-full rounded-md border bg-transparent pl-6 pr-2 outline-none …'`） | ✅ 无 | `div.relative.flex-1` → `div.mx-auto…gap-3` → 页面容器 → `main` → `body`（**无 fs-***）→ **16px** | **真违例**（阶梯外） |
| `memory-graph.tsx:140`（过滤 input，`className='h-9 w-full rounded-md border bg-transparent pl-6 pr-2 …'`） | ✅ 无 | 同上链路 → **16px** | **真违例** |
| `logs.tsx:261 / :273`（两个 `<select className='h-8 rounded-md border bg-background px-2 fs-caption'>`） | ✅ 有 `fs-caption` | — | **已挂档**（两席所称一致，本席独立复验） |

- 原生 `<button>` 侧：`patterns.tsx:147,158`、`affinity.tsx:82`、`calls.tsx:30,106`、`tokens.tsx:93`、`knowledge.tsx:52` 均自带 `fs-caption`；`knowledge.tsx:219`、`memory-graph.tsx:116,124` 三处 `<button className='rounded-full'>` 是 **CategoryChip 的空壳包装**（文本在子 chip 上，chip 基类带 `fs-caption`）→ 不算裸控件。
- **本席净结论**：两席所称「余 4 处」在**站点数**上与实读一致，但**真视觉违例只有 2 处**（knowledge / memory-graph 的 input 渲染 16px）；settings-dialog ×2 由外层 `fs-body` 继承救住。修法建议：给这 4 处 input 一律显式挂 `fs-body`（或 `fs-caption`），别靠继承。

### 5.2 `theme-switch.tsx` 基类缺 `relative`（P2-14）——现状：**问题仍在，本席实测源码**

`src/components/theme-switch.tsx:11-21`：`<Button variant='ghost' size='icon' className='rounded-full'>` 内
`<Moon className='absolute size-[1.2rem] …' />`，而 **`Button`/`buttonVariants` 基类（`button.tsx:9`）无 `relative`、`theme-switch` 传入的也只有 `rounded-full`**。
产物侧亦无任何让 button 定位化的规则 → `<Moon>` 的包含块 = 最近定位祖先 = `app-shell.tsx:106` 的 `<header className='sticky top-0 z-10 …'>`（`position:sticky` 构成定位祖先）。
后果（可复现推断，未起浏览器实测 → **标注：静态论证**）：暗色下 Sun 缩放为 0、Moon 显示，但 Moon 贴在**页头左上角**而非图标按钮内 → 暗档出现一枚游离月亮。
`h-9` 侧另一条：`size='icon'` 给 `size-9`，`rounded-full` 与之不冲突 ✔。
修法：`className='relative rounded-full'`（或基类侧给 Button 补 `relative`——但那是全站改动，风险大，建议只在本组件补）。
同类已正确写法可对照：`knowledge.tsx:199` `<div className='relative flex-1'>`、`memory-graph.tsx:138` `<div className='relative w-48'>`（其 Search 图标 `absolute` 有参照）→ 唯 `theme-switch` 漏。

### 5.3 P2-13（a11y 三件）与本域重叠部分：**Esc / 焦点陷阱**属 F3 席面板，本席不动；但需指出一条与本席同源的**结构缺陷**：`settings-dialog.tsx:79-86` 遮罩与面板全是裸 `<div>`（无 `role='dialog'`、无定位 utility 类参与，故无类名冲突），**不受类名合并病灶影响** → 本席在该项下无追加发现。

---

## 6. 锁：现状判定 + 最小可常驻锁设计

### 6.1 现状：**零锁**（三处都验过）

| 候选 | 判定 | 证据 |
|---|---|---|
| `tsc -b` | 管不到 | className 是 `string`，类型层无 CSS 属性语义 |
| `webui/scripts/layout-constitution.mjs` | 扫不到 | 实读全文 67 行：六条规则（HEX / OFF_LADDER_TEXT / INLINE_FONT_SIZE / OFF_SCALE_SPACING / OFF_SCALE_ARBITRARY / PALETTE_CLASS），**没有任何一条比较「同一元素的两条 class」**；它甚至**要求**页面写 `fs-*`，却不拦 `fs-* + leading-*` 并写 |
| `scripts/webui_acceptance.py` | 看不出 | 实读计数（只读脚本统计）：`font` 关键字 **0** 次、`getComputedStyle`/`fontSize`/`lineHeight`/`classList` **0** 次；只有 `evaluate`×3、`inner_text`×2、`screenshot`×4 → 判据是「有没有文本/有没有崩」，版式不在其视野内 |
| `tests/**` | 不覆盖 | `grep -rln 'layout-constitution\|webui/src' tests/` → **零命中**（本席实跑，无结果） |

### 6.2 二选一裁决：**静态断言**（不选 dist 层叠断言）

理由（有实测支撑）：**产物偏移会随任何一次无关改动而整体漂移**（§2.4 实测：删一个 `leading-none` → 后续规则前移 43 字节），把锁建在偏移上必然 flaky；而「同一元素不存在两个写者」这一不变量**在源码层就可判定、与构建器无关、且能挡住未来新增的 `@utility`**。
（若要加产物锁，只加**一条**非偏移式断言即可：`'.fs-' 出现次数 === 5` 且 `每条 .fs-X 规则体含 font-size+line-height+font-weight 三属性`，用于监视 ladder 定义被改动 —— 本席不建议现在加。）

### 6.3 锁 L1（静态，接进现有宪法门，零依赖）

`webui/scripts/layout-constitution.mjs` 增量草案（插在 `PALETTE_CLASS` 之后、`check()` 内 `scan` 序列里）：

```js
// —— F16 增补：同元素「一个 CSS 属性只许一个写者」——
// 判据：fs-*（五档，实读 src/index.css @utility）同打 font-size/line-height/font-weight，
// 而 tailwind-merge 默认组表不认识它（实测 3.7.0 classGroups 零命中 "fs-"）→
// 与内建 leading-*/font-*/text-{size} 并写时谁胜由产物层叠决定（不可控，见 index.css 注释）。
const FS_UTIL = /\bfs-(?:page|card|body|caption|num)\b/;
const FS_PROPS = ['font-size', 'line-height', 'font-weight'];
const BUILT_IN = {
  'font-size': /^text-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|[[].+[]])$/,
  'line-height': /^leading-(?:none|tight|snug|normal|relaxed|loose|[[].+[]])$/,
  'font-weight': /^font-(?:thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$/,
};
// 权重双写「棘轮白名单」：这 15 处是有意覆盖（要 500），2026-09-19 实测冻结；
// 只许变少不许变多——新增即红，删除即要求同步删本清单。
const WEIGHT_RATCHET = new Set([
  'components/ui/button.tsx:9',
  'components/ui/badge.tsx:9',
  'components/patterns/patterns.tsx:115',
  'components/patterns/patterns.tsx:151',
  'components/patterns/patterns.tsx:162',
  'pages/affinity.tsx:38',
  'pages/affinity.tsx:85',
  'pages/calls.tsx:35',
  'pages/calls.tsx:109',
  'pages/dashboard.tsx:63',
  'pages/latency.tsx:25',
  'pages/memory-graph.tsx:246',
  'pages/tokens.tsx:50',
  'pages/tokens.tsx:99',
  'pages/tokens.tsx:100',
]);
// 行内 token 切分（保留 [ ] : / % . # , ( ) 与 - _ ：只切空白/引号/花括号/分号等）
const TOKEN_SPLIT = /[^A-Za-z0-9_[\]()./%,#*:-]+/;

function checkWriters(rel, lines) {
  lines.forEach((raw, i) => {
    if (/^\s*(\/\/|\*|\/\*)/.test(raw)) return; // 注释与本文档性描述不算
    const seen = new Map(); // prop+modifierChain -> [tokens]
    for (const tok of raw.split(TOKEN_SPLIT)) {
      if (!tok) continue;
      const c = tok.lastIndexOf(':');
      const chain = c < 0 ? '' : tok.slice(0, c);
      const base = c < 0 ? tok : tok.slice(c + 1);
      const hit = (prop, re) => re.test(base) && !seen.has(prop + chain) && push(prop + chain, tok);
      const push = (k, t) => { const a = seen.get(k) || []; a.push(t); seen.set(k, a); };
      if (FS_UTIL.test(base)) FS_PROPS.forEach((p) => push(p + chain, base));
      for (const [prop, re] of Object.entries(BUILT_IN)) {
        // 只有「无修饰符链」的内建类才与 fs-* 抢层叠同一条；带 :active/:hover/[] 的按特异性裁决，另计
        if (prop !== 'font-size' && chain === '') hit(prop, re);
        else if (prop === 'font-size' && chain === '') hit(prop, re);
      }
    }
    for (const [key, list] of seen) {
      const uniq = [...new Set(list)];
      if (uniq.length < 2) continue;
      const prop = key.slice(0, key.indexOf(/^[a-z-]+(?=\/|#|$)/.test(key) ? 1e9 : key.length));
      const at = `${rel}:${i + 1}`;
      const isWeightPair = uniq.some((t) => /^font-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$/.test(t))
        && uniq.some(FS_UTIL.test);
      if (/^font-weight/.test(key) && isWeightPair) {
        if (!WEIGHT_RATCHET.has(at)) VIOLATIONS.push(`${at}  权重双写未登记（fs-* + font-*）: ${uniq.join(' + ')}`);
        continue; // 白名单内：现状保留，由 F16 台账追踪
      }
      VIOLATIONS.push(`${at}  同元素属性双写（${/^([a-z-]+)/.exec(key)[1]}，fs-* 对 tailwind-merge 不可见）: ${uniq.join(' + ')}`);
    }
  });
}
```

> 上面是**草案**（`push`/`prop` 两行的取键写法在落地时需按 lint 收紧；核心判据与正则已在本席沙箱用等价 node 片段跑通，输出恰为 §1.2 的 17 行 + app-shell 两条被特异性排除）。
> 建议的硬拦三态：**line-height 双写 = 红**（现网 2 处，改完即零）、**font-size 双写 = 红**（现网 0 处）、**font-weight 双写 = 棘轮**（15 处白名单，只减不增）。

### 6.4 锁 L2（行为断言，专治 §2.2 的「修了个寂寞」，30 行零依赖）

`webui/scripts/class-merge-lock.mjs`（新增件，接进 `package.json` 的 `lint:layout` 之后或并入宪法门）：

```js
// 断言 cn() 真把五档注册进了 tailwind-merge：不注册时 twMerge("fs-body","fs-caption") 保留两条。
// 同时挡住 v2 扁平写法（extendTailwindMerge({classGroups}) 在 3.x 被静默丢弃）。
import { createRequire } from 'node:module';
const require = createRequire(new URL('../package.json', import.meta.url));
const { cn } = require('../src/lib/utils.ts'); // 需经 vite/esbuild 装载；若不便，改为直接 import 编译后入口
const bad = ['fs-body fs-caption', 'leading-none fs-card'];
const got = [cn('fs-body', 'fs-caption'), cn('leading-none', 'fs-card')];
if (got[0] !== 'fs-caption' || got[1] !== 'fs-card') {
  console.error('类合并锁失败：fs-* 未注册进 tailwind-merge。got=', got);
  process.exit(1);
}
console.log('类合并锁：通过（fs-* 已进 font-size 组，冲突可折叠）');
```

（若加载 TS 入口不便，可退化为「静态断言 `utils.ts` 含 `extend: { classGroups` 且含五档全部字面量」，仍是两条正则的事。）

### 6.5 可选锁 L3（产物不变量，非偏移式；本席不建议现在上）

断言「产物里每条 `.fs-X` 规则体含三属性」+「`src/index.css` 的 `@utility fs-*` 名单 == utils.ts 注册名单」→ 防「改了阶梯忘了注册」。后者其实用一条 grep 式比对就能在 `doc_sync`/门里常驻，成本更低，建议以这条替代 L3。

---

## 7. 新发现台账（七要素：严重度｜坐标 文件:行｜锚点｜根因｜建议改法｜验证命令｜有无回归锁）

> 严重度口径：P1 = 根因级/全站静默取胜；P2 = 单点可见缺陷或结构病灶；P3 = 认知/卫生。**本席全程只读，未修任何一条。**

**F16-1｜P1｜`webui/src/lib/utils.ts:1-7`（全项目 cn() 咽喉）**
锚点：`return twMerge(clsx(inputs));`
根因：tailwind-merge 3.7.0 默认组表**零认识** `@utility fs-*`（实测 `classGroups` 379 组无 `fs-` 字面量）→ 同属性双写永不折叠，裁决权交给产物层叠；且 `fs-*` 是三属性合一类，**一类一组模型原理上不能完整表达**。
建议改法：见 §3.1 全文替换稿（`extendTailwindMerge({ extend: { classGroups: { 'font-size': 五档 } } })`）。
验证命令：`cd webui && node -e "…cn('leading-none','fs-card')…"` 期望 `"fs-card"`；§1.5 扫描脚本期望输出从 17 行降到 15（A2 两条清零）。
有无回归锁：**无**（§6.1 三处全验）→ 落地时须同时上 L1+L2。

**F16-2｜P1（现网 2 处真视觉差）｜`webui/src/components/settings/settings-dialog.tsx:140`、`webui/src/pages/logs.tsx:320`**
锚点：`className='rounded-md border bg-muted/40 p-3 fs-caption leading-relaxed text-muted-foreground'` / `className='fs-caption leading-relaxed text-muted-foreground'`
根因：`fs-caption`(line-height 1.125rem)@950465 早于 `leading-relaxed`(1.625)@950659 → 内建恒胜；**方案 ① 修不了（`conflictingClassGroups` 单向，实测反向声明会把 fs-* 删掉致元素丢字号）**。
建议改法：删 `leading-relaxed`（§3.2 第 1/2 条）；若确需宽行距，走 ② 的档位新增并同步注册表。
验证命令：§1.5 脚本 → `line-height` 行应消失；`node webui/scripts/layout-constitution.mjs`（加 L1 后）应红→绿。
有无回归锁：**无**。

**F16-3｜P1（结构病灶，现网视觉零差）｜`webui/src/components/ui/card.tsx:33` ↔ 6 调用点（`pages/calls.tsx:61,150`、`pages/tokens.tsx:127,172,201`、`components/patterns/patterns.tsx:73`）**
锚点：`className={cn('font-semibold', className)}`
根因：基类内建 `font-semibold`@951017 恒压调用方 `fs-card`@950531 的 font-weight 分量（600=600 所以今天看不出来）——**与已删的 `leading-none` 同源同族**；「一类一修」留下的洞就在这里。
建议改法：基类侧永不再引入 `leading-*` / `text-{size}` / `fs-*`（写成 L1 的门规则：`components/{ui,patterns,semantic,layout}` 的**首个字符串实参**（`cva()`/`cn()` 基类位）禁含 `leading-`）；权重同值可保留但须在注释里点名「fs-* 的权重分量在此不生效」。
验证命令：§1.3 的 Grep 枚举复跑（应仍 6 处但门规则保证不再增长）；`git grep -n "leading-\|text-xs\|text-sm" webui/src/components/ui/`。
有无回归锁：**无**。

**F16-4｜P2｜`webui/src/index.css:237-262`（五档定义区）**
锚点：`@utility fs-num {`
根因：**产物次序 = `fs-page > fs-card > fs-caption > fs-body > fs-num`（层叠后写者胜，实测偏移 950595/950531/950465/950401/950303），与视觉阶梯大小反向** → 五档里「数字大字」最脆：任何人给它并写一条更小的 `fs-*`，`fs-num` 必输。
建议改法：① 生效后此次序被「字符串后写者胜」取代，风险解除；过渡期在 index.css 注释区补一行「五档不得并写」。
验证命令：§1.5 脚本（`font-size` 类目现网 0 命中即为达标）。
有无回归锁：**无**。

**F16-5｜P2（第二族，latent）｜`webui/src/index.css:291-314` + `webui/src/components/patterns/patterns.tsx:99-108`**
锚点：`good: 'text-tone-good tone-face-good',` / `brand: 'text-primary bg-primary/15',`
根因：`tone-face-*` 同样对 twMerge 不可见，且产物 @954542–954724 **晚于一切内建 `bg-*`（@948068–949383）** → 「基类恒胜调用方」方向；同时 `TONE_TEXT` 内 6 个 tone 走不可覆盖的 `tone-face-*`、`brand` 走可覆盖的 `bg-primary/15` → **同一 prop 的覆盖语义在 7 个 tone 之间不一致**。
建议改法：§3.1 已含 `background: TONE_FACE` 注册（作为**第二批**，需先确认 0 并写——本席已 grep 确认为 0）；或把 `brand` 也改成一枚 `tone-face-brand`（七 tone 同构）。
验证命令：`node -e` 断言 `cn('bg-primary/15','tone-face-flat')===\"tone-face-flat\"`；`grep -n \"bg-.*tone-face\\|tone-face.*bg-\" src/**`（同元素并写应为 0）。
有无回归锁：**无**。

**F16-6｜P1（施工安全，会直接决定 ① 成败）｜`node_modules/tailwind-merge/src/lib/merge-configs.ts:6-15`（3.7.0 API）↔ 即将改写的 `webui/src/lib/utils.ts`**
锚点：`extend = {}, override = {}`
根因：3.7.0 的 `extendTailwindMerge` **只认 `extend`/`override`**；顶层 `classGroups` 是 2.x 旧写法，实测**静默丢弃**（`mergeConfigs(getDefaultConfig(),{classGroups:…})` 返回原组表）→ 照旧例抄代码＝「修了个寂寞」，且**运行时不报错**（只有 `tsc` 会报类型）。
建议改法：§3.1 已按 `extend:{classGroups}` 写；并在 §6.4 的 L2 行为锁里断言折叠真实生效。
验证命令：`cd webui && node -e` 两行式：`extendTailwindMerge({classGroups:{'font-size':['fs-body','fs-caption']}})('fs-body','fs-caption')` 仍是两条（证明扁平无效）vs `extend` 版返回 `"fs-caption"`。
有无回归锁：**无**（L2 即为其锁）。

**F16-7｜P2（核销 P2-10 修正版）｜`webui/src/pages/knowledge.tsx:201`、`webui/src/pages/memory-graph.tsx:140`（真违例 2）＋ `settings-dialog.tsx:102,120`（靠继承兜住）**
锚点：`className='h-9 w-full rounded-md border bg-transparent pl-6 pr-2 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]'`
根因：input 自身无 `fs-*`；v4 preflight `button,input,select,optgroup,textarea{font:inherit;…}`（**无 `font-size:100%`**）→ 无 fs-\* 祖先时落到根 16px，跳出五档。
建议改法：4 处 input 一律显式挂 `fs-body`（或 `fs-caption`），别依赖继承。
验证命令：`grep -n \"<input\" -A6 src/pages/*.tsx src/components/settings/*.tsx` 逐条含 `fs-`；建议进 L1 加一条「原生 input/select/textarea/button 的行内 class 必含一枚 fs-\*（CategoryChip 空壳包装除外）」。
有无回归锁：**无**（现宪法门只管 `text-*`，不管「缺 fs-\*」）。

**F16-8｜P2｜`webui/src/components/theme-switch.tsx:11-21`**
锚点：`<Moon className='absolute size-[1.2rem] scale-0 rotate-90 transition-all dark:scale-100 dark:rotate-0' />`
根因：`Button` 基类与调用点均无 `relative` → 绝对定位参照落到 `app-shell.tsx:106` 的 `sticky` header。
建议改法：`className='relative rounded-full'`（组件局部，勿动全站 Button）。
验证命令：静态 `grep -n \"relative\" webui/src/components/theme-switch.tsx`；真机=暗档截图（本席未起浏览器，**静态论证**）。
有无回归锁：**无**。

**F16-9｜P3（卫生）｜`webui/src/index.css:217-223`**
锚点：`@utility no-scrollbar {`
根因：定义存在、**全站零引用**（dist 内 `.no-scrollbar` n=0，`grep -rn no-scrollbar src` 只命中 index.css）；同属 twMerge 不可见类，未来若与内建滚动类并写即复发同类病灶。
建议改法：要么用起来（长列表容器），要么删定义；无论哪种，都应在 §3.1 的注册表注释里登记全部 `@utility` 名单。
验证命令：`grep -c \"no-scrollbar\" webui/src/*.tsx webui/src/**/*.tsx`（现=0 使用）。
有无回归锁：**无**。

**F16-10｜P1（治理缺口）｜`webui/scripts/layout-constitution.mjs:28-56` + `scripts/webui_acceptance.py`**
锚点：`scan(OFF_LADDER_TEXT, '阶梯外字号…')`
根因：门只查「用了阶梯外的字号类」，**从不查「同一元素两个写者」**；acceptance 里 `font` 关键字 0 次 → 三类判具（`getComputedStyle`/`fontSize`/`classList`）全缺 → 整个病灶族**零锁**。
建议改法：§6.3 L1 + §6.4 L2；`package.json` 的 `build` 已前置 `node scripts/layout-constitution.mjs`（实测 `scripts.build`），故 L1 天然常驻，只需扩规则。
验证命令：`cd webui && node scripts/layout-constitution.mjs`（当前应仍 exit 0；加 F16 规则后应红 2 条 = F16-2 两处，修完归绿）。
有无回归锁：**本条即锁的方案**。

**F16-11｜P3（结构成因）｜`webui/src/components/patterns/patterns.tsx:151,162`、`pages/affinity.tsx:85`、`pages/calls.tsx:35,109`、`pages/tokens.tsx:99,100`**
锚点：`className='rounded-md border px-3 py-1 fs-caption font-medium text-muted-foreground hover:bg-accent disabled:pointer-events-none disabled:opacity-50'`
根因：**7 处原生 `<button>` 手抄 Button 外观** → `fs-* + font-medium` 双写集中爆发地；`pager` 两按钮与 `Pager` 本就在 `patterns.tsx` 里，最该复用 `buttonVariants({ variant:'outline', size:'sm' })`。
建议改法：换 `Button size='sm' variant='outline'`（权重单点由 Badge/Button 基类供给），删除 7 处手抄串。
验证命令：`grep -c \"<button\" src/**/*.tsx` 应下降；§1.5 脚本的 A1 计数应随之减少。
有无回归锁：**无**。

---

## 8. 本席未做 / 边界声明（诚实红线）

- 未起浏览器、未跑 `npm run build/dev`、未 `npm install`、未在 `webui/**` 写过任何文件、未改 `node_modules` 与 `dist`（只读打开）。
- twMerge 行为为**实测**（node 只读 require 既有包）；产物层叠为**实测**（Python 只读读 `dist/index.html` 取偏移）；`theme-switch` 的视觉后果与「input 落 16px」的因果链为 **preflight 规则实读 + 静态推断，未实跑浏览器**，已就地标注。
- 未对 F3/F4/F5/S8 各席报告作二次核验，只在本席计数与 F4 计数不一致处做对账（§1.4）。
- 所有「已完成/已修复」措辞本席一律未使用：本文只描述观测到的源码与产物现状，以及可落手的方案。

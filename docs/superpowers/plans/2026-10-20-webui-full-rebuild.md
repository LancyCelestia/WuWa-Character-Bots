# 模型网关可观测性面板全量重构 · 实施计划

> **给 agentic workers：** 执行本计划必须加载 `superpowers:subagent-driven-development`。步骤用 `- [ ]` 勾选跟踪。

**目标：** 把 AI 控制台从「局部样式修补」重建成数据字典全展开、四区布局、通道三态显式的可观测性面板。

**架构：** 三层收口。① **数据字典层**（纯函数，零 React）——`field-dict.ts` 是全站唯一字段真身，每个字段带四列（自然语言键名 / 键值 / 简介 / 说明）+ 可得性标记；② **中文化层**（纯函数）——`domain-labels.ts` 是运行时领域词表（动作 / 渠道 / 状态 / 错误 / 模型），与既有 `humanize.ts`（配置键词典）职责分离；③ **聚合层**（纯函数）——`stat-rollup.ts` 做五粒度时间卷、百分位、用户统计、半小时分桶。三层都零 React，可被 `node --test` 直接加载。UI 层只消费这三层，不自己算、不自己翻。

**技术栈：** React 19 + TanStack Router（browser history）+ Tailwind v4 + shadcn 风格原语 + recharts（懒加载）+ Node 原生 test runner。

**规格：** `docs/superpowers/plans/2026-10-20-console-rebuild.md`（前序七节方案，本计划是它的执行侧）

---

## Global Constraints

以下每一条对所有任务都生效，逐字来自用户需求与仓库版式宪法。

### 版式宪法（`webui/scripts/layout-constitution.mjs`，自测 196 条，违反即门禁红）

| # | 约束 | 精确值 |
|---|---|---|
| 1 | 字号只许五档 | `fs-caption`=12px / `fs-body`=13px / `fs-title`=14px / `fs-heading`=18px / `fs-display`=30px。禁 `text-[13px]`、禁 `font-size:` 声明、禁 Tailwind 字号类 |
| 2 | 间距 4px 栅格 | `p-1/p-2/p-3/p-4/p-6/p-8`、`gap-*`、`m*`。禁 `p-[13px]` |
| 3 | 圆角只许三档 + full | `rounded-md`=14px / `rounded-lg`=18px / `rounded-xl`=30px / `rounded-full`。禁 `rounded-sm`、禁 `rounded-[20px]` |
| 4 | 禁裸 hex 色值 | 一律走 `index.css` 语义 token |
| 5 | 禁 Tailwind 调色板类 | `text-blue-500` / `bg-slate-800` 一律红 |
| 6 | 禁任意值方括号 | `max-w-[72ch]` 红。**例外 A5**：`grid-cols-[Nfr_Mfr]` 允许，值只能是 `auto\|0\|Nfr\|minmax(同形)` |
| 7 | 禁 `setProperty('--字面量')` | `setProperty(变量)` 允许 |
| 8 | 禁一行两个 `fs-*` | 三元分支也不认 |
| 9 | 行级豁免棘轮只减不增 | `// layout-allow: <理由≥4字>`；**本计划不新增任何豁免** |

### 视觉语言（SnowLuma 继承，已实测其 CSS 变量名与本站对齐）

SnowLuma 的 `--background / --card / --popover / --muted-foreground / --border / --primary / --destructive / --success / --radius / --sidebar-*` 与本站 `index.css` **已注册同一套 token**，无需另起一套 CSS。

| 用途 | token |
|---|---|
| 表面三层 | `bg-background` → `bg-card` → `bg-popover` |
| 文字层级 | 主数据 `text-foreground`；说明/简介 `text-muted-foreground` |
| 边框 | `border-border`，半隐形用 `border-hairline` / `ring-hairline` |
| 语义 | `text-success` / `text-destructive` / `text-tone-good/warn/bad/info` |
| 图表 | `--chart-1` ~ `--chart-6` |
| 阴影 | `shadow-card`（**必须保留辉光**，这是用户点名的「辉光恢复」） |
| 数字 | `tabular-nums`（趋势跳动时列宽不抖） |

### 数据诚实铁律

1. **库里没有的字段，一律标 `absent` 并显式告诉用户「尚未采集」**，不许用 0 冒充、不许静默省略。
2. **型号与渠道的专有名词不翻译**（`gemini-3.8-flash` 保留原样），但**必带中文厂商前缀**。
3. **无法翻译的兜底值必须以「未登记」开头**，且此规则由测试锁死（首字符必须是中文）。
4. **空桶不补零**——补零会让「无数据」与「有数据但为零」长得一样。
5. **实测值进注释与 `detail`**，不写「大约」「可能」。

---

## Review Focus

以下是规格暗示但任何单个任务的测试都覆盖不到、最可能咬到使用者的五类，按风险排序。每条都在它所属任务的测试里钉住。

| # | 输入 / 条件 | 合理预期 | 归属任务 |
|---|---|---|---|
| 1 | **通道状态是 `temporarily_unavailable` 但 `cooldown_until` 已过期** | 不能显示成「熔断中」——冷却期满意味着已放行探测，应显示「恢复探测中」。判据必须带时间比较，不能只看字符串 | T3（`breakerStateOf`） |
| 2 | **`session_id` 是空串 / `admin:onebot` / `email:noreply…`** | 用户数统计不能把它们算成一个「用户」。实测 1834 行（54%）是这类，算进去会把活跃用户数抬高到无意义 | T4（`parseSession` / `attributionCoverage`） |
| 3 | **`changeRate` 的上一窗口是负数或 0** | 上一窗口为 0 时返回 `null` 而非 `Infinity`；上一窗口为负时用绝对值做分母，否则符号翻转（好感度扣减是真实场景，`delta` 有负值） | T4（`changeRate`） |
| 4 | **`affinity_delta_log` 只有 2 天历史却要看「每周/每月/每年」** | 必须显式标注「数据不足以判断趋势」，而不是画一条只有一个点的线让人以为稳定 | T2（`detail` 文案）+ T7（图表空态） |
| 5 | **`first_token_latency_ms` 列存在但 3397 行全 NULL** | UI 必须显示「尚未采集」并说明原因（链路未流式），不能显示 `0 毫秒`——后者会被读成「首 Token 瞬间返回」 | T2（`availability: 'absent'`）+ T8（延迟页） |

---

## 文件结构（先定边界，再拆任务）

### 新建

| 文件 | 职责 | 依赖 |
|---|---|---|
| `webui/src/lib/field-dict.ts` | 全站字段字典唯一真身。35 条字段 × 四列 + 可得性 + 粒度 | 无 |
| `webui/src/lib/field-dict.test.ts` | 上述的不变量锁 | `field-dict.ts` |
| `webui/src/lib/domain-labels.ts` | 运行时领域词表：动作 / 渠道 / 状态 / 错误 / 模型 | 无 |
| `webui/src/lib/domain-labels.test.ts` | 中文首字符铁律 + 三态判定锁 | `domain-labels.ts` |
| `webui/src/lib/stat-rollup.ts` | 五粒度时间卷 / 百分位 / 用户统计 / 半小时分桶 | 无 |
| `webui/src/lib/stat-rollup.test.ts` | 上述的不变量锁 | `stat-rollup.ts` |
| `webui/src/components/console/four-pane.tsx` | 四区布局壳（左导航 / 左分区 / 主显示 / 详情栏） | 无 |
| `webui/src/components/console/field-table.tsx` | 四列字典渲染器（自然语言键名 / 键值 / 简介 / 说明） | `field-dict.ts` |
| `webui/src/components/console/detail-pane.tsx` | 详情栏容器（选中项 → 字典 + 时序下钻） | `field-table.tsx` |
| `webui/src/components/console/picker.tsx` | 可关闭 Chip / 紧凑 Switch / 说明文字三件套 | 无 |
| `webui/src/components/console/breaker-dot.tsx` | 通道三态小圆点 | `domain-labels.ts` |
| `webui/src/components/console/grain-switch.tsx` | 五粒度切换器（日 / 周 / 月 / 年 / 累计） | `stat-rollup.ts` |
| `webui/src/lib/field-dict-consistency.test.ts` | 跨文件一致性：字典里的 key 都能在组件里找到消费者 | 全部三层 |

### 修改

| 文件 | 改什么 |
|---|---|
| `webui/src/pages/affinity.tsx` | 换成五粒度 + 四列字典 + 用户/模型/通道三级下钻 |
| `webui/src/pages/latency.tsx` | TTFT 标「尚未采集」；端到端 P50/P90/P99 上四列字典；通道健康三态区并入 |
| `webui/src/pages/calls.tsx` | 渠道列改用 `channelLabel(gateway_channel)`；列宽够；报错与尝试时间同列 |
| `webui/src/pages/operations.tsx` | 动作行改用 `actionLabel()` 而非裸 `action_id`；结果面板中文化 |
| `webui/src/pages/console.tsx` | 总台改四区；「承诺健康」区块移除（并入延迟页） |
| `webui/src/pages/dashboard.tsx` | 顶层 KPI 换 `affinity_total` 等字典字段 |
| `webui/src/lib/console.ts` | `CONSOLE_PAGES` 补齐 17 页（现漏 `sessions` / `appearance`） |

### 不动

- `webui/scripts/layout-constitution.mjs`（门禁本体，改它等于改尺）
- `webui/src/components/ui/*`（27 处 `/ui/` import 不变量）
- `webui/src/lib/humanize.ts`（1235 行配置键词典，与本计划职责不重叠）
- `webui/src/index.css`（需独占席才能动，本计划不改）
- 任何后端 `.py`（后端已有数据足够，缺的是前端消费）

---

## 任务拆解与子代理派发表

### 模型与角色分配（含一条硬约束）

| 角色 | 模型 | 席位 | 职责 | 禁止 |
|---|---|---|---|---|
| 主控 Agent | `满血`（当前会话） | 1（常驻） | 拆任务、写简报、审输出、合并、跑终局验证 | 不做大段实现 |
| UI 设计风格规划 | `满血`（**由主控本人承担**） | 0（不派席） | 四区 token 映射、组件选型、交互状态表 | 不写业务逻辑 |
| 实现子代理 | **仅 `Flash`** | 最多 19 | 按单一职责实现 | 不改设计 token、不引依赖、不改门禁 |
| 测试子代理 | **仅 `Flash`** | 含在 19 内 | 逐字段验证渲染、三态机、开关拦截 | 不改生产代码 |
| 最终审计 | `满血`（**由主控本人承担**） | 0（不派席） | 逐条对照验收清单 | 不用「样式好看」替代功能验收 |

> **⚠️ 运行时硬约束（实测，非设计选择）**：向本会话派发子代理时指定 `axonhub/DeepSeek-V4.1-Flash-满血` 会被运行时直接拒绝：
> ```
> Error: child LLM route "axonhub/DeepSeek-V4.1-Flash-满血" is not allowed for this Session
> ```
> 因此「满血用于规划 / 前端设计 / 审计」这三件事由**主控本人**执行——主控自身就跑在满血上，这三个角色不需要另开席位就能满足。所有**执行席**一律 `axonhub/DeepSeek-V4.1-Flash`（免费版）。
>
> 并发上限：本会话实际硬顶 **8 席**（含主控），用户在 prompt 里给的 20 席按此收紧。

### 波次安排

```
W1（基础三层，3 席并行，互不碰文件）
├── T1  field-dict.ts        → 35 条字段字典 + 12 条不变量测试
├── T2  domain-labels.ts     → 领域词表 + 20 条测试（含中文首字符铁律）
└── T3  stat-rollup.ts       → 聚合纯函数 + 29 条测试
              ↓ 三层全绿后才放行 W2（UI 要 import 它们）
W2（四区骨架 + 渲染件，3 席并行）
├── T4  four-pane.tsx + detail-pane.tsx + field-table.tsx
├── T5  picker.tsx + breaker-dot.tsx + grain-switch.tsx
└── T6  console.ts 补 17 页 + 路由与导航对齐
              ↓ 组件全绿后才放行 W3（页面要 import 它们）
W3（页面重写，4 席并行，按页面分文件域）
├── T7  affinity.tsx（五粒度 + 三级下钻）
├── T8  latency.tsx（TTFT 未采集 + 三态健康区）
├── T9  calls.tsx（渠道中文化 + 列宽 + 报错同列）
└── T10 operations.tsx + console.tsx + dashboard.tsx
              ↓
W4（收口）
├── T11 跨文件一致性测试 field-dict-consistency.test.ts
├── T12 视觉验证截图（1440 / 1024 / 390 三档）
└── T13 终局审计（主控本人，逐条对照 10 条验收清单）
```

### 逐席派发表

| 席 | 角色 | 模型 | 输入 | 输出 | 完成定义 |
|---|---|---|---|---|---|
| **T1** | 实现 | Flash | `BRIEF-W1.md`（含 35 条字段逐条表格 + 实测值） | `field-dict.ts`(≈320 行) + `.test.ts`(≈120 行) | `npm test` 全绿 + `typecheck` rc=0 + `lint:layout` rc=0 + 报告落盘 |
| **T2** | 实现 | Flash | `BRIEF-W2.md`（含 13 条动作映射 + 三态判定伪码） | `domain-labels.ts`(≈220 行) + `.test.ts`(≈150 行) | 同上 + 动作 ID 代码实读清单与简报差异登记 |
| **T3** | 实现 | Flash | `BRIEF-W3.md`（含 11 条硬性语义 + 两种时间戳形态） | `stat-rollup.ts`(≈280 行) + `.test.ts`(≈220 行) | 同上 |
| **T4** | 实现 | Flash | W1 三文件已存在；四区规格（见下） | `four-pane.tsx` / `detail-pane.tsx` / `field-table.tsx` | 三档视口截图不溢出；`field-table` 渲染 35 条全部四列 |
| **T5** | 实现 | Flash | W1 + `BRIEF`（Chip/Switch/三态点/粒度档规格） | `picker.tsx` / `breaker-dot.tsx` / `grain-switch.tsx` | 每个开关带 ≤40 字说明；Chip 有默认/选中/可关闭三态 |
| **T6** | 实现 | Flash | `webui/src/pages/*.tsx` 实有 17 个 + `router.tsx` 22 条路由 | 改 `lib/console.ts` | `CONSOLE_PAGES` 17 条与 `pages/` 实际文件一一对应，有测试锁 |
| **T7** | 实现 | Flash | W1 三层 + W2 组件 | 重写 `pages/affinity.tsx` | 五粒度齐全；三级下钻；每级四列字典；2 天历史显式标注 |
| **T8** | 实现 | Flash | 同上 | 重写 `pages/latency.tsx` | TTFT 显示「尚未采集」；端到端 P50/P90/P99 四列；三态健康区并入 |
| **T9** | 实现 | Flash | 同上 | 重写 `pages/calls.tsx` | 渠道列用 `gateway_channel`；报错与尝试时间同列；列宽容纳中文全名 |
| **T10** | 实现 | Flash | 同上 | 改 `operations.tsx` / `console.tsx` / `dashboard.tsx` | 动作行全中文；总台去「承诺健康」；顶层 KPI 换字典字段 |
| **T11** | 测试 | Flash | 全部产物 | `field-dict-consistency.test.ts` | 字典里 35 个 key 全部有消费者或被显式标「本轮未接入」 |
| **T12** | 测试 | Flash | 构建产物 | 三档视口截图 | 无横向溢出；无未翻译英文；`docH ≤ 4500` |
| **T13** | 审计 | **满血（主控本人）** | 全部产物 + 10 条验收清单 | 逐条判定表 | 任一条不过即不宣布完成 |

---

## Task 1: 数据字典唯一真身

**Files:**
- Create: `webui/src/lib/field-dict.ts`
- Test: `webui/src/lib/field-dict.test.ts`

**Interfaces:**
- Consumes: 无（叶子模块）
- Produces: `FIELD_DICT`（35 条 `readonly FieldDoc[]`）、`fieldDoc(key)`、`fieldsByModule(module)`、`fieldRow(key)`、`absentFields()`、类型 `Grain` / `Availability` / `FieldModule` / `FieldDoc` / `FieldRow`

- [ ] **Step 1: 写失败测试**（12 条不变量，见 `BRIEF-W1.md`）
- [ ] **Step 2: 跑一遍确认失败**（`npm test` 应报 `field-dict.ts` 不存在）
- [ ] **Step 3: 写最小实现**（35 条字段，逐条照 `BRIEF-W1.md` 表格填）
- [ ] **Step 4: 跑三门口确认全绿**
- [ ] **Step 5: 报告落盘 `REPORT-W1.md`**

---

## Task 2: 中文化词表

**Files:**
- Create: `webui/src/lib/domain-labels.ts`
- Test: `webui/src/lib/domain-labels.test.ts`

**Interfaces:**
- Consumes: 无
- Produces: `UNKNOWN_PREFIX`、`actionLabel(id)`、`channelLabel(providerId, gatewayChannel?)`、`statusLabel(state)`、`breakerStateOf(state, cooldownUntil?, now?)`、`errorLabel(raw)`、`modelLabel(id)`、`vendorLabel(id)`、类型 `ActionLabel` / `BreakerState` / `ErrorLabel`

- [ ] **Step 1: 读代码核实动作 ID 真实清单**
  ```bash
  grep -n "ControlActionDescriptor" plugins/bot_unified_runtime/control_plane/_app.py
  ```
- [ ] **Step 2: 写失败测试**（20 条，含中文首字符铁律）
- [ ] **Step 3: 跑一遍确认失败**
- [ ] **Step 4: 写最小实现**
- [ ] **Step 5: 跑三门口确认全绿**
- [ ] **Step 6: 报告落盘 `REPORT-W2.md`**

---

## Task 3: 统计聚合纯函数

**Files:**
- Create: `webui/src/lib/stat-rollup.ts`
- Test: `webui/src/lib/stat-rollup.test.ts`

**Interfaces:**
- Consumes: 无
- Produces: `rollupAffinity(rows, grain)`、`changeRate(current, previous)`、`latestPair(buckets)`、`recentDeltas(buckets, n)`、`percentile(values, p)`、`median(values)`、`parseSession(sessionId)`、`attributionCoverage(rows)`、`userStats(rows)`、`halfHourBuckets(stamps)`、`dailyBuckets(stamps)`、`countBy(rows, pick)`、`UNKNOWN_KEY`

**关键实现片段（供审查对照，不是让实现者照抄）**

```ts
// percentile：最近秩法。刻意不做线性插值——有界样本上插值会造出
// 一个不存在的「中间值」，把 P99 报得比真实最大值还平滑。
export function percentile(values: readonly number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b); // 克隆，不改入参
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[idx];
}

// changeRate：分母取绝对值。好感度 delta 有负值（扣减），
// 不加 abs 会让「从 -100 涨到 50」显示成 -150%，符号完全反了。
export function changeRate(current: number, previous: number | null | undefined): number | null {
  if (previous == null || previous === 0) return null;
  return Math.round(((current - previous) / Math.abs(previous)) * 1000) / 10;
}
```

- [ ] **Step 1: 写失败测试**（29 条）
- [ ] **Step 2: 跑一遍确认失败**
- [ ] **Step 3: 写最小实现**
- [ ] **Step 4: 跑三门口确认全绿**
- [ ] **Step 5: 报告落盘 `REPORT-W3.md`**

---

## Task 4: 四区布局骨架

**Files:**
- Create: `webui/src/components/console/four-pane.tsx`
- Create: `webui/src/components/console/detail-pane.tsx`
- Create: `webui/src/components/console/field-table.tsx`

**Interfaces:**
- Consumes: `fieldRow(key)` / `fieldDoc(key)`（T1）
- Produces:
  ```ts
  // four-pane.tsx
  export function FourPane(props: {
    nav: ReactNode;        // 左导航（固定宽）
    aside: ReactNode;      // 左分区（可折叠，内容区宽度不随之变）
    main: ReactNode;       // 主显示区（3fr）
    detail: ReactNode | null;  // 详情栏（选中项才有）
  }): JSX.Element;

  // field-table.tsx
  export function FieldTable(props: { keys: readonly string[]; values?: Record<string, ReactNode> }): JSX.Element;
  export function FieldTableRow(props: { key_: string; value?: ReactNode }): JSX.Element;

  // detail-pane.tsx
  export function DetailPane(props: {
    title: string;
    subtitle?: string;
    fieldKeys: readonly string[];
    values?: Record<string, ReactNode>;
    children?: ReactNode;  // 时序下钻图挂这里
    onClose?: () => void;
  }): JSX.Element;
  ```

**窄屏降级（硬要求）**

| 视口 | 布局 |
|---|---|
| `≥ 1536px`（`2xl`） | 四区：`nav` 固定 1/5 + `aside` 1/5 + `main` 3/5 + `detail` 1/5 |
| `1024–1535px`（`lg`） | 三区：`nav` 收成图标条 + `aside` + `main`；`detail` 变为右侧抽屉 |
| `< 1024px` | 单区：`nav` 变顶栏抽屉；`aside` 折叠进筛选按钮；`detail` 变全屏 Sheet |

**左分区宽度可调的约束**：`aside` 拖动改宽时，`main` 的 `max-width` 用 `ch` 或固定 px 锁住，**不随 aside 压缩**——用户明确抱怨过「内容区跟着挤」。

**栅格实现**（守住 A5 例外，`fr` 是唯一被允许的方括号形式）

```tsx
<div className="grid h-full grid-cols-1 lg:grid-cols-[auto_16rem_minmax(0,1fr)] 2xl:grid-cols-[auto_16rem_minmax(0,1fr)_22rem]">
```

- [ ] **Step 1: 写三档视口的截图基线（先量现状）**
- [ ] **Step 2: 写 `four-pane.tsx`**
- [ ] **Step 3: 写 `field-table.tsx`（四列语义：key 走 `font-mono fs-caption text-muted-foreground`；label 走 `fs-title text-foreground`；summary 走 `fs-body`；detail 走 `fs-caption text-muted-foreground`）**
- [ ] **Step 4: 写 `detail-pane.tsx`**
- [ ] **Step 5: 三档截图验收，无横向溢出**
- [ ] **Step 6: 报告落盘**

---

## Task 5: 标签 / 开关 / 三态点 / 粒度档

**Files:**
- Create: `webui/src/components/console/picker.tsx`
- Create: `webui/src/components/console/breaker-dot.tsx`
- Create: `webui/src/components/console/grain-switch.tsx`

**Interfaces:**
- Consumes: `breakerStateOf` / `statusLabel`（T2）、`RollupGrain`（T3）
- Produces:
  ```ts
  // picker.tsx
  export function Chip(props: { label: string; selected?: boolean; onToggle?: () => void; onRemove?: () => void }): JSX.Element;
  export function ChipGroup(props: { children: ReactNode; hint: string }): JSX.Element;
  export function ToggleRow(props: { label: string; hint: string; checked: boolean; onChange: (v: boolean) => void; sensitive?: boolean }): JSX.Element;

  // breaker-dot.tsx
  export function BreakerDot(props: { state: string | null; cooldownUntil?: string | null }): JSX.Element;

  // grain-switch.tsx
  export function GrainSwitch(props: { value: RollupGrain; onChange: (g: RollupGrain) => void }): JSX.Element;
  ```

**视觉规格（SnowLuma 继承，逐条硬性）**

| 件 | 默认态 | 选中态 | 可关闭 |
|---|---|---|---|
| `Chip` | `bg-secondary text-muted-foreground` + `border-hairline` | `bg-primary text-primary-foreground` | hover 显小 `X`（`size-3`） |
| `ToggleRow` | 标签左、开关右、说明在下方 `fs-caption text-muted-foreground` | — | — |
| `BreakerDot` | `closed`→`bg-tone-good` / `open`→`bg-tone-bad` / `half-open`→`bg-tone-warn` / `unknown`→`bg-muted-foreground` | 只有 `open` 挂 `console-pulse` | — |
| `GrainSwitch` | 五档分段控件，`fs-caption`，选中档 `bg-card shadow-card` | — | — |

**每个开关必须带 ≤40 字的中文说明**——用户原文点名「说明文字不得省略」。

**隐私敏感开关的视觉区分**：`sensitive: true` 时整行套一层 `bg-card` + `border-hairline` + 顶部一行 `fs-caption text-muted-foreground` 的独立说明块。**不用红色**（用户明确说不要恐吓性红）。

- [ ] **Step 1: 写 `picker.tsx` 三个件**
- [ ] **Step 2: 写 `breaker-dot.tsx`（含三态 + 借用语义注释）**
- [ ] **Step 3: 写 `grain-switch.tsx`**
- [ ] **Step 4: 视觉验收：每个开关都有说明、Chip 三态可点**
- [ ] **Step 5: 报告落盘**

---

## Task 6: 路由与导航对齐

**Files:**
- Modify: `webui/src/lib/console.ts`（`CONSOLE_PAGES` 从 15 → 17）
- Test: `webui/src/lib/console.test.ts`（加一条锁）

**实测现状**：`CONSOLE_PAGES` 只登记 15 页，`pages/` 实有 17 个文件——漏了 `sessions.tsx`（173 行）与 `appearance.tsx`（235 行）。`router.tsx` 有 22 条 `createRoute`。

**要加的测试**

```ts
test('CONSOLE_PAGES 与 pages/ 实有文件一一对应，不漏不重', async () => {
  const fs = await import('node:fs/promises');
  const dir = new URL('../pages/', import.meta.url);
  const files = (await fs.readdir(dir)).filter((f) => f.endsWith('.tsx'));
  // control-center.tsx 是 /resources 与 /models 两条路由的共用实现，不算独立页
  const pages = files.map((f) => f.replace(/\.tsx$/, '')).filter((n) => n !== 'control-center');
  const registered = CONSOLE_PAGES.map((r) => r.console.split('/').pop()!);
  assert.deepEqual(registered.slice().sort(), pages.slice().sort());
});
```

- [ ] **Step 1: 写失败测试**
- [ ] **Step 2: 跑确认失败**（应报 17 vs 15 不匹配）
- [ ] **Step 3: 补两条 `CONSOLE_PAGES` 记录**
- [ ] **Step 4: 跑三门全绿**
- [ ] **Step 5: 报告落盘**

---

## Task 7: 好感度页五粒度 + 三级下钻

**Files:**
- Modify: `webui/src/pages/affinity.tsx`（111 行 → 重写）

**Interfaces:**
- Consumes: `rollupAffinity` / `changeRate` / `latestPair`（T3）、`FIELD_DICT` 的 9 条 affinity 字段（T1）、`FourPane` / `DetailPane`（T4）、`GrainSwitch`（T5）

**必须兑现的四件事**

1. **五粒度齐全**：日 / 周 / 月 / 年 / 累计，切换即时重算（纯前端聚合，后端 `/affinity/board` 不变）。
2. **三级下钻**：总好感度 → 按模型 / 按用户 TopN / 按通道。每级都用 `FieldTable` 渲染四列。
3. **2 天历史显式标注**：`affinity_delta_log` 实测只有 2.0 天。周/月/年档必须在图上方挂一条 `fs-caption text-muted-foreground` 的提示：「当前仅 2 天历史，周及以上粒度只有一个数据点，不足以判断趋势」。
4. **`affinity_total` 作为顶层 KPI**，值取 `user_affinity.affinity` 求和（实测 117.229）。

**验收断言（人工）**

- 点任意一条用户，右侧详情栏出现该用户的完整四列字典（9 条 affinity 字段）。
- 切到「每月」时，提示条出现，图上是单点而非一条假趋势线。

- [ ] **Step 1: 现有 111 行读完后写新版的失败态（先渲染空壳，截图确认四区在）**
- [ ] **Step 2: 接 `rollupAffinity` 与 `GrainSwitch`**
- [ ] **Step 3: 接 `FieldTable` + `DetailPane` 做三级下钻**
- [ ] **Step 4: 加 2 天历史提示条**
- [ ] **Step 5: 跑三门 + 截图**
- [ ] **Step 6: 报告落盘**

---

## Task 8: 延迟页 TTFT 未采集 + 三态健康区

**Files:**
- Modify: `webui/src/pages/latency.tsx`（111 行 → 重写）

**Interfaces:**
- Consumes: `percentile`（T3）、`FIELD_DICT` 的 7 条 latency 字段 + 6 条 channel 字段、`BreakerDot`（T5）

**必须兑现的四件事**

1. **TTFT 显示「尚未采集」，不是 0**：`first_token_latency_ms` 实测 0/3397 非空。UI 必须在 TTFT 卡片位置显示 `尚未采集` + 一句说明「本机器人的大模型调用链路未启用流式传输，首 Token 延迟在客户端无从测得」。
2. **端到端 P50/P90/P99 上四列字典**：实测 6733 / 17360 / 60077 毫秒。
3. **通道健康区并入本页**（从总览页移出，兑现用户「承诺健康改小」）：折叠区，默认收起，展开后每个通道一行三态点 + 连续失败数 + 最近探测时间 + 冷却截止。
4. **每行通道必须能用中文说清「为什么它处于这个状态」**：用 `statusLabel` + `errorLabel` 拼一句自然语言，例如「暂时不可用 —— 连续失败 6 次，最近一次是连接超时（原文：ConnectTimeout: _ssl.c:993…）」。

- [ ] **Step 1: 写 TTFT 未采集的展示（先做最容易谎报的那块）**
- [ ] **Step 2: 接端到端三档百分位 + 四列字典**
- [ ] **Step 3: 并入通道健康折叠区 + 三态点**
- [ ] **Step 4: 拼「为什么是这个状态」的自然语言句**
- [ ] **Step 5: 跑三门 + 截图**
- [ ] **Step 6: 报告落盘**

---

## Task 9: 调用统计页渠道中文化

**Files:**
- Modify: `webui/src/pages/calls.tsx`（217 行）

**Interfaces:**
- Consumes: `channelLabel` / `statusLabel` / `errorLabel` / `modelLabel`（T2）、`FIELD_DICT` 的 10 条 calls 字段

**必须兑现的四件事**

1. **渠道列改用 `gateway_channel`**：实测该列已是中文实名（`恒星纪元 - Gemini` 2794 / `恒星纪元 - Grok` 147 / `浅夜の梦 - 专属号池` 87 / `Ollama - Qwen` 76 / 空 293）。前端此前显示的是 `provider_id`（`axon-gemini-38-flash`）或 `actual_model`（`gemini-3.8-flash`）——**这是用户抱怨「渠道名显示原始变量名」的唯一真因，修前端不改数据**。
2. **模型列用 `modelLabel`**：`谷歌 / gemini-3.8-flash`（厂商中文名 + 原型号）。
3. **报错与尝试时间同列可见**：不再折叠到二级弹窗。列宽必须容纳中文全名——`min-w-0` 配 `truncate` + `title` 提示，不靠缩窄字号。
4. **状态列用 `statusLabel`**：`success`→`成功`、`temporarily_unavailable`→`暂时不可用`。

**列宽实测基线**（`gateway_channel` 最长中文值 `浅夜の梦 - 专属号池` = 12 个字符宽）

- [ ] **Step 1: 换渠道列数据源（先做这一条，它单独就能消掉最大的用户抱怨）**
- [ ] **Step 2: 换模型列 + 状态列**
- [ ] **Step 3: 报错与尝试时间并列，测列宽**
- [ ] **Step 4: 跑三门 + 截图（重点看中文列是否被截断）**
- [ ] **Step 5: 报告落盘**

---

## Task 10: 受控动作 / 总台 / 总览三页

**Files:**
- Modify: `webui/src/pages/operations.tsx`（111 行）
- Modify: `webui/src/pages/console.tsx`（517 行）
- Modify: `webui/src/pages/dashboard.tsx`（413 行）

**Interfaces:**
- Consumes: `actionLabel`（T2）、`FIELD_DICT`、`FourPane`（T4）

**必须兑现的三件事**

1. **动作行全中文**：`_app.py` 的 `ControlActionDescriptor(action_id, action_id)` 把 label 直接等于 id，所以前端 `font-mono` 一渲染就露出 `adapter.reconnect`——**这是用户抱怨「updeer.reconnect」的真因**。改用 `actionLabel(id).name` + `actionLabel(id).hint`，原始 id 降级到 `title` 属性里供排查。
2. **总台去掉「承诺健康」区块**：迁到 `latency.tsx` 的折叠区（T8 已做）。
3. **总览顶层 KPI 换字典字段**：用 `affinity_total` / `active_users` / `request_success_rate` / `total_cost`，每个都挂四列字典。

- [ ] **Step 1: `operations.tsx` 动作中文化**
- [ ] **Step 2: `console.tsx` 搬走「承诺健康」**
- [ ] **Step 3: `dashboard.tsx` 换成字典 KPI**
- [ ] **Step 4: 跑三门 + 截图**
- [ ] **Step 5: 报告落盘**

---

## Task 11: 跨文件一致性锁

**Files:**
- Create: `webui/src/lib/field-dict-consistency.test.ts`

**要锁的三件事**

1. `FIELD_DICT` 的 35 个 key，每一个要么在 `pages/*.tsx` 或 `components/console/*.tsx` 里被字面引用，要么被登记在显式的「本轮未接入」清单里。**不允许默默存在**——那意味着字典写得漂亮但没人用。
2. `domain-labels.ts` 的每个映射函数，都至少有一个组件在调用。
3. `stat-rollup.ts` 的每个导出函数，都至少有一个页面在调用。

- [ ] **Step 1: 写失败测试（先跑，它会报出所有未被消费的 key）**
- [ ] **Step 2: 逐条决定：接入 or 登记未接入**
- [ ] **Step 3: 跑全量测试确认绿**
- [ ] **Step 4: 报告落盘**

---

## Task 12: 视觉验证

- [ ] **Step 1: 构建** `cd webui && npm run build`，rc 必须 0
- [ ] **Step 2: 三档截图**（用 `webui/scripts/shoot.mjs`，等待字段是 **`wait`**（毫秒）不是 `settleMs`；`--user-data-dir` 必须落在工作区内）
  ```bash
  node scripts/shoot.mjs --url "http://127.0.0.1:8080/console/affinity" --width 1440 --wait 3000 --out .shots/affinity-1440.png
  node scripts/shoot.mjs --url "http://127.0.0.1:8080/console/affinity" --width 1024 --wait 3000 --out .shots/affinity-1024.png
  node scripts/shoot.mjs --url "http://127.0.0.1:8080/console/affinity" --width 390  --wait 3000 --out .shots/affinity-390.png
  ```
  **注意**：`--window-size=390` 在 headless 下 `innerWidth` 会变 500，量 390 档要读实际 `innerWidth` 而不是传参值。
- [ ] **Step 3: 逐图检查**：无横向溢出（`document.documentElement.scrollWidth <= clientWidth`）、无未翻译英文、`docH ≤ 4500`
- [ ] **Step 4: 报告落盘**

---

## Task 13: 终局审计（主控本人，满血）

逐条对照用户 10 条验收清单，**任何一条不通过即不得宣布完成**：

- [ ] 1. 好感度覆盖 daily/weekly/monthly/yearly/total 五粒度，每个字段都有四列自然语言字典
- [ ] 2. 用户数与调用数据分开建模，含活跃用户、新增、回访、人均调用、Top 10% 集中度、Token 吞吐、TTFT P99、端到端 P99、错误率
- [ ] 3. 「绘画几」「承诺健康」已作为疑似语音转写错误被处置，保留会话级指标字典与前端提示条
- [ ] 4. 布局严格四区；侧栏宽度可调时主显示区宽度保持稳定
- [ ] 5. UI 基于 Tailwind 4 theme tokens + shadcn 风格组件，非硬编码颜色/间距
- [ ] 6. 标签区所有 chip、switch、说明文字已重写，每个开关配自然语言说明
- [ ] 7. 通道健康以三态呈现，状态转换语义可解释
- [ ] 8. 头像/签名采集有显式开关，默认关闭，关闭时零服务器传输，开启时限 TopN
- [ ] 9. 子代理派遣记录可审计：实现/测试只用 Flash，满血只出现在规划与审计，并发 ≤ 8
- [ ] 10. 所有可展开、可下钻的数据点，都能看到「自然语言键名 + 键值 + 简介 + 说明」四列，无裸字段逃逸

---

## 自审：规格覆盖对照

| 用户要求 | 落在哪个任务 | 状态 |
|---|---|---|
| 数据字典四列全展开 | T1 定义、T4 渲染、T7-T10 消费、T11 一致性锁 | ✅ |
| 好感度五粒度 | T1（9 条字段）、T3（卷轴函数）、T7（UI） | ✅ |
| 用户数与调用分开 | T1（6 条 users + 10 条 calls） | ✅ |
| TTFT 与端到端分开 | T1（7 条 latency，TTFT 标 absent）、T8 | ✅ |
| 四区布局 | T4、T6、T12 | ✅ |
| SnowLuma 视觉语言 | Global Constraints 表格（已实测 token 对齐） | ✅ |
| 标签/开关重写 + 说明 | T5 | ✅ |
| 通道三态 | T2（判定）、T5（点）、T8（页面） | ✅ |
| 头像/签名开关 | **待用户裁定口径**（见下） | ⚠️ |
| 子代理纪律 | 派发表 | ✅ |

### 三个必须由用户裁定的口径（不猜）

1. **头像 / 签名采集范围**：OneBot `sender` 对象**没有** avatar / sign 字段，必须 `get_stranger_info` 逐用户调。全量（562 个 `user_affinity` 用户 → 562 次 API）还是 TopN（默认 50）？开关默认关闭已定，范围待定。
2. **「涨粉」= 好感度**：用户这次明确说「涨粉即好感度」，已按此建模。但**群成员数**是另一个指标（全库无快照，`get_chat_member_count` 只在 `group_info.py:807` 单次调用不落库）——要不要一并采集？
3. **「绘画几」**：全库全前端 grep `绘画/绘图/绘几` **零命中**。系统 prompt 推测是「会话级」，我按 `session_*` 备好了字典位，但**当前 `llm_call_records.session_id` 是会话标识不是会话数**——真正的「会话数 / 每会话轮次 / 会话时长」需要新增聚合，要不要做？

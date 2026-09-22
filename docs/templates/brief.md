<!-- @schema:BEGIN
sections: 输入? | 任务? | 验收? | 边界? | 落点?
params:
- wave_id | text | literal | req | nonempty
- brief_scope | text | literal | req | nonempty
- owner_board | text | auto:category_owner_board | req | nonempty
@aliases: 输入=输入|前置|前置条件|已存在交付物|起点|背景|为什么派你|范围|任务书|目标|需求
@aliases: 任务=任务|要做的事|独占领地|独占|可写面|独占可写面|任务清单|待办|队列
@aliases: 验收=验收|判据|检查点|落盘检查点|红线|硬约束|纪律|禁写面|预算
@aliases: 边界=边界|不碰|不许|护栏|责任面|交回|PARKED|归属
@aliases: 落点=落点|交付|产出|输出|目标类别|目标模板|工单|去向
@schema:END -->

# 模板：brief（任务书 / 无 H2 过程账 · 唯一模板源）

本文件是 `.superpowers/**` 里**没有任何 H2 小节**的那批任务书 / README / PLAN 子簇（类别 `sdd-brief`，
从 `sdd-ledger` 另立）的唯一模板。这类页的自由散文里本就没有分节标题，硬套 `sdd-ledger` 的十槽骨架
会 100% 判「缺必填 / 表外节」，故独立一类。一类内容一份模板；内容页通过页首 front-matter 调用，
`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。
渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段，标记外正文归人。

## 骨架怎么从语料真形长出来（席 S21R，2026-09-22）

判据来自 S5 分簇账 `%TEMP%/S5-clusters.txt`：`sdd-ledger` 分簇里 **n_h2==0 的有 27 枚**（任务书 /
README / PLAN 族），这批页既不是席位日志（`seat-report` 族），也没有台账分节可对齐，故本席 §S21R-①
令其另立一类。因该类页**无 H2**，任何"必须出现某节"的必填都会 0 页命中（准绳：「必填参无真身来源＝
该类 0 页可转」）⇒ 本模板 **sections 全部可选**，只锁「允许哪几类节、出现时的顺序、不重复」，
不强制任何节必须存在。`@aliases` 收录任务书族常见写法（输入 / 独占可写面 / 判据 / 预算 / 交回 …），
只收同义不同写。

> **落地依赖（本席只交回注册表行＋模板，见报告 PARKED）**：类别名 `sdd-brief` 需同步进
> `CENSUS.md §一`（S16 所有）与 `scripts/doc_template_sync.py::classify()` 的 `.superpowers/` 分支
> （S20 所有）——建议机械判据：**无任何 H2 且文件名属 `BRIEFS/README/PLAN` 族**。三处不同步则
> G-T5「集合相等」与「声明无页」两条在册断言会红，按前言「让它红着」，不由本席代改。

## 怎么用（内容页侧）

```markdown
---
template: sdd-brief
params:
  wave_id: 2026-09-22-taxonomy
  brief_scope: BRIEFS
  owner_board: B10
---
```

- `wave_id`＝页所在 `.superpowers/sdd/<wave_id>/` 路径段；`brief_scope`＝文件名主干；
  `owner_board`＝注册表 `CATEGORIES_BY_ID["sdd-brief"].owner_board`。三值均有既存事实来源，人手照抄不凭印象。
- 「已完成」必须带可复跑命令 + 实跑输出；过程件禁写会过期的实况计数（与 G-T3 同尺）。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections 或落在 @aliases 同义集内）

<!-- TEMPLATE-AUTO:BEGIN -->
- wave_id：{{fact:wave_id}}
- brief_scope：{{fact:brief_scope}}
- owner_board：{{fact:owner_board}}
<!-- TEMPLATE-AUTO:END -->

## 输入（可选：前置、已存在交付物、为什么派你）

## 任务（可选：要做什么、独占可写面）

## 验收（可选：判据、检查点、红线、预算）

## 边界（可选：不碰什么、需交回他席的依赖）

## 落点（可选：产出、目标类别 / 模板、工单去向）

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选（本类全可选，无 H2 页天然合规）；表外节 / 顺序偏离 / 同槽重节各自独立码。
- `@aliases:` 一行一槽位，只收**同一语义槽位的不同写法**；把「缺节」写成命中＝放宽判据，禁止。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。

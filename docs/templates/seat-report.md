<!-- @schema:BEGIN
sections: 任务书? | 账目? | 交付 | 发现? | 自报
params:
- seat_id | text | literal | req | nonempty
- wave | text | literal | req | nonempty
- status | enum | literal | req | enum:STARTED,RUNNING,BLOCKED,DONE
- role | enum | literal | req | enum:impl,readonly,conversion,gate,measurement,report
- report_class | enum | auto:seat_class | req | enum:SEAT,report,progress,log
- ledger_events | number | auto:page_stat:ledger | req | int:0..999999
@schema:END -->

# 模板：seat-report（席位工作日志 · 唯一模板源）

本文件是 `.superpowers/**` 席位工作日志这一类内容的**唯一模板**。一类内容一份模板，内容页只通过
front-matter 参数调用它；`@schema` 覆盖不到的字段一律视为**规格外内容**，由
`scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段，
标记外正文归人。

## 怎么用（内容页侧）

页首写 front-matter（自定义行语法子集，禁嵌套），例如：

```markdown
---
template: seat-report
params:
  seat_id: T-EXAMPLE
  wave: 2026-09-22-taxonomy
  status: DONE
  role: measurement
  report_class: auto:seat_class
  ledger_events: auto:page_stat:ledger
---
```

- 有真身事实的参数**必须**写 `auto:`（值由渲染器现算，人手不碰数）：`report_class` 由文件名派生，
  `ledger_events` 由本页「账目」节的条目数现算。写了别的字面值即 `AUTO_SOURCE_MISMATCH` 红。
- `literal` 参数把值直接写在 `params:` 下；schema 之外的键 = 规格外，判红。
- 正文小节只准用骨架节名（允许「节名（自由补充）」形式，门只比对括号前主干）；
  必填节 `交付`，`任务书/账目/发现/自报` 可省略但出现时必须保持下面的顺序。

## 骨架（新页照抄；机器段由 --write 注入）

<!-- TEMPLATE-AUTO:BEGIN -->
- 席位：{{fact:seat_id}}｜波次：{{fact:wave}}｜状态：{{fact:status}}｜性质：{{fact:role}}
- 报告族：{{fact:report_class}}（文件名派生）｜账目条数：{{fact:ledger_events}}（正文现算）
<!-- TEMPLATE-AUTO:END -->

## 任务书（可选：一句话任务 + 准绳指针）

## 账目（可选：按时刻追加的流水，一条一行）

## 交付（必填：产出清单 + 实跑证据）

## 发现（可选：给下游席位的警讯）

## 自报（可选：错误与没做到，全为过去式）

## @schema 字段语义（门侧口径）

- `sections`：竖线分隔的有序节序列，尾缀 `?` ＝ 可选节；必填节缺失、出现表外节、
  出现顺序偏离，各自是独立违规码。
- `params` 每行五列：`key | kind | source | req | domain`。
  kind ∈ text/number/path/list/enum；source = `literal` 或 `auto:<provider>[:arg]`；
  req ∈ req/opt；domain ∈ nonempty / any / `enum:a,b,c` / `int:min,max`。
- 渲染区（TEMPLATE-AUTO 之间）只准出现 `{{fact:KEY}}` 占位，KEY 必须在 params 内，
  否则 schema 装载即红。
- 字节确定性：渲染只用 LF 写盘、列表按 schema 声明序输出、机器段零时间戳；
  同输入两次 `--write` 字节必须相等（常驻用例断言）。

## 类别侧口径（本模板管辖什么页）

`.superpowers/**` 下文件名以 `SEAT-` / `report-` / `progress-` 开头、或以 `-log.md`
结尾的 .md —— 与 `.superpowers/sdd/2026-09-22-taxonomy/CENSUS.md` 的 seat-report 判据同源。
批量转换由后续切片执行；本模板落地当刻仅试点页带 front-matter，未迁移页照常计入
`--report` 的「未模板驱动」列，不判红。

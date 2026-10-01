<!-- @schema:BEGIN
sections: 事实与时间线 | 影响面 | 处置 | 摘要? | 复盘与红线?
freeform: on
params:
- report_subject | text | auto:filename_stem | req | nonempty
- owner_board | text | auto:category_owner_board | req | nonempty
- report_window | text | literal | opt | any
@aliases: 摘要=总览|能力全景|快速上手
@aliases: 事实与时间线=已完成工作|执行台账|交付史与提交索引|工作区根目录
@aliases: 处置=修复回归要求
@aliases: 复盘与红线=纪律声明|不要做的事情|已知残余与建议|尚未完善部分|归档入口|硬性约束
@schema:END -->

# 模板：incident-report（事件报告 / 台账叙事件 · 唯一模板源）

本文件是「一次事件一份报告」类内容件（类别 `root-report`）的唯一模板：仓库根报告件、事故复盘、含半生成台账（`COMMANDS.md`）的报告面都走它。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: incident-report
params:
  report_subject: auto:filename_stem
  owner_board: auto:category_owner_board
  report_window: （可省略）
---
```

- 时间线用绝对日期，不用「今天/昨晚」；每条目要能指向提交哈希或可复跑命令。
- `report_subject` 有真身来源（`auto:filename_stem`，由文件名主干现算，人手不碰数；空主干/占位符形 ⇒
  `PROVIDER_FAIL`，绝不发明）；`owner_board` 由类别注册表现算；`report_window`（可省略）写覆盖区间。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- report_subject：{{fact:report_subject}}
- owner_board：{{fact:owner_board}}
- report_window：{{fact:report_window}}
<!-- TEMPLATE-AUTO:END -->

## 事实与时间线

## 影响面

## 处置

## 摘要（可选）

## 复盘与红线（可选）

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（`report_subject`/`owner_board` 走现算 `auto:`，`report_window` 为 `literal` 可省略）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。

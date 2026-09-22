<!-- @schema:BEGIN
sections: 术语与结构 | 文件结构规范 | 命名规范 | 开发约束 | 自动化变更契约 | 统一口径 | 问题处理分级 | 代码质量红线
params:
- convention_scope | text | literal | req | nonempty
- owner_board | text | auto:category_owner_board | req | nonempty
- enforcement_gate | text | literal | opt | any
@schema:END -->

# 模板：convention（规范本体 / 结构规范台账件 · 唯一模板源）

本文件是「写给人读、由门执法的规范」类内容件（类别 `board-meta`）的唯一模板：`docs/boards/_conventions.md` 规范本体与 `docs/boards/_meta/**` 台账件都归这类。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: convention
params:
  convention_scope: （必填）
  owner_board: （必填）
  enforcement_gate: （可省略）
---
```

- 每条硬约束必须点名执法它的门；只有散文没有门＝债。
- 计数（板块数/功能数/入口数）指向生成物，不在此手写。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- convention_scope：{{fact:convention_scope}}
- owner_board：{{fact:owner_board}}
- enforcement_gate：{{fact:enforcement_gate}}
<!-- TEMPLATE-AUTO:END -->

## 术语与结构

## 文件结构规范

## 命名规范

## 开发约束

## 自动化变更契约

## 统一口径

## 问题处理分级

## 代码质量红线

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。

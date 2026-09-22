<!-- @schema:BEGIN
sections: 用途 | 口径 | 取数口 | 维护规矩 | 明细?
params:
- ledger_scope | text | literal | req | nonempty
- owner_board | text | auto:category_owner_board | req | nonempty
- refresh_cmd | text | literal | opt | any
@schema:END -->

# 模板：ledger（目录 / 清单 / 台账件 · 唯一模板源）

本文件是「一份事实一张表」类内容件的唯一模板（类别 `catalog` 与 `route-matrix` 都调用它）。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由
`scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: ledger
params:
  ledger_scope: config-catalog
  owner_board: B10
  refresh_cmd: python scripts/doc_sync.py
---
```

- 三枚皆 `literal`：`ledger_scope`（这本账记什么域）、`owner_board`（归属板块）、
  `refresh_cmd`（可省略：重算命令）。
- **计数 / 条目数禁裸写**：这类册子的正确居所是取数口，正文只准写「以 `--report` / 生成器现算
  为准」或指向真身文件，与 G-T3 同尺；确需保留旧数字则同行标「当时值」。
- 必填节 `用途 / 口径 / 取数口 / 维护规矩`，`明细` 可选。

## 骨架（新页照抄；机器段由 --write 注入）

<!-- TEMPLATE-AUTO:BEGIN -->
- 台账域：{{fact:ledger_scope}}｜归属板块：{{fact:owner_board}}｜重算：{{fact:refresh_cmd}}
<!-- TEMPLATE-AUTO:END -->

## 用途

## 口径

## 取数口

## 维护规矩

## 明细（可选）

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。

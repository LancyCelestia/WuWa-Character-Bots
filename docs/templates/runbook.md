<!-- @schema:BEGIN
sections: 前置 | 步骤 | 检查表 | 已知边界?
freeform: on
params:
- runbook_scope | text | literal | req | nonempty
- audience | text | literal | opt | any
- owner_board | text | auto:category_owner_board | req | nonempty
@schema:END -->

# 模板：runbook（操作手册 / 验收清单件 · 唯一模板源）

本文件是「照做就能复现」类操作件（类别 `acceptance`）的唯一模板：安装、接入、重启验收清单都是它。步骤必须可按序执行，检查表必须可勾选。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: runbook
params:
  runbook_scope: （必填）
  audience: （可省略）
  owner_board: （必填）
---
```

- 每步给命令原文与预期输出判据；「观察一下」不是步骤。
- 批次验收节是 append-only 序列，同 `handbook` 的开放节问题一并 PARKED。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- runbook_scope：{{fact:runbook_scope}}
- audience：{{fact:audience}}
- owner_board：{{fact:owner_board}}
<!-- TEMPLATE-AUTO:END -->

## 前置

## 步骤

## 检查表

## 已知边界（可选）

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。

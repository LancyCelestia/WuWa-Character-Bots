<!-- @schema:BEGIN
sections: 池身份 | 副本与游标 | 红线
params:
- pool_id | text | auto:copy_pool_id | req | nonempty
- render_home | text | auto:category_code_home | req | nonempty
- single_source_gate | text | literal | opt | any
@schema:END -->

# 模板：copy-pool（用户可见文案池 · 唯一模板源）

本文件是 `surface="code"` 类 `incode-copy-pool` 的 schema 契约：一处参数源 + 一处渲染，多副本必须先收编再扩写。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: copy-pool
params:
  pool_id: （必填）
  render_home: （必填）
  single_source_gate: （可省略）
---
```

- 人格红线一条不许动：守岸人语气、好感度任何档位不攻击/不强硬、算法只定性、R-18 六硬线。
- 同一句话术的第二真身由文案单源执法（`tests/test_copy_single_source.py`）。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- pool_id：{{fact:pool_id}}
- render_home：{{fact:render_home}}
- single_source_gate：{{fact:single_source_gate}}
<!-- TEMPLATE-AUTO:END -->

## 池身份

## 副本与游标

## 红线

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。

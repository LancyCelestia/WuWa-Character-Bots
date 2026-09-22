<!-- @schema:BEGIN
sections: 字段序 | 元数据 schema | 生成物
params:
- topic_id | text | auto:help_topic_id | req | nonempty
- entry_home | text | auto:category_code_home | req | nonempty
- catalog_cmd | text | literal | opt | any
@schema:END -->

# 模板：help-entry（帮助主题（代码内声明） · 唯一模板源）

本文件是 `surface="code"` 类 `help-topic` 的 schema 契约：`_HELP_ENTRIES` 元组序 + `_HELP_ENTRY_META` 一张 schema，缺字段由中央默认派生，禁逐条手写特例。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: help-entry
params:
  topic_id: （必填）
  entry_home: （必填）
  catalog_cmd: （可省略）
---
```

- 参数源唯一：`scripts/command_catalog.py` → `docs/command-catalog.md`；改完必须 `--write` 后 `--check` EXIT 0。
- topic 数以生成物为准，任何叙述件不手写。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- topic_id：{{fact:topic_id}}
- entry_home：{{fact:entry_home}}
- catalog_cmd：{{fact:catalog_cmd}}
<!-- TEMPLATE-AUTO:END -->

## 字段序

## 元数据 schema

## 生成物

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
